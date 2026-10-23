"""Alert-tier configuration (core/alert_config.py). All IO goes to tmp dirs."""
import copy
import json
import threading

import pytest

from core import alert_config as ac
from core import paths


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    d = tmp_path / "alert-config"
    monkeypatch.setattr(paths, "ALERT_CONFIG_DIR", d)
    return d


@pytest.fixture
def base():
    return ac.load_default()


def test_default_is_valid(base):
    assert ac.validate(base) == []


def test_effective_is_default_without_versions(cfg_dir, base):
    assert ac.load_effective()["config_version"] == base["config_version"]
    assert ac.effective_source() == "default"
    assert ac.list_versions() == []


def test_save_and_effective(cfg_dir, base):
    new = copy.deepcopy(base)
    new["hazards"]["storm_wind"]["thresholds"]["2"] = 7
    v = ac.save_version(new, changed_by="tester", reason_vi="thử")
    assert v.startswith("v0001-") and (cfg_dir / f"{v}.json").is_file()
    eff = ac.load_effective()
    assert eff["config_version"] == v
    assert eff["hazards"]["storm_wind"]["thresholds"]["2"] == 7
    saved = ac.get_version(v)
    assert saved["parent_version"] == base["config_version"]
    assert saved["changes"] == [{"path": "hazards.storm_wind.thresholds.2", "old": 8, "new": 7}]
    assert ac.effective_source() == "runtime"
    summary = ac.list_versions()[0]
    assert summary["n_changes"] == 1 and summary["changed_by"] == "tester"


def test_second_version_parent_and_diff(cfg_dir, base):
    a = copy.deepcopy(base)
    a["hazards"]["heat"]["thresholds"]["1"] = 30.5
    v1 = ac.save_version(a, changed_by="x", reason_vi="r")
    b = ac.load_effective()
    b["hazards"]["heat"]["thresholds"]["1"] = 30.0
    v2 = ac.save_version(b, changed_by="x", reason_vi="r")
    saved = ac.get_version(v2)
    assert v2.startswith("v0002-") and saved["parent_version"] == v1
    assert saved["changes"] == [{"path": "hazards.heat.thresholds.1", "old": 30.5, "new": 30.0}]
    assert [v["config_version"] for v in ac.list_versions()] == [v1, v2]


def test_save_invalid_raises_and_writes_nothing(cfg_dir, base):
    bad = copy.deepcopy(base)
    bad["hazards"]["storm_wind"]["thresholds"]["2"] = 5
    with pytest.raises(ac.ConfigValidationError) as e:
        ac.save_version(bad, changed_by="x", reason_vi="r")
    assert e.value.errors
    assert not cfg_dir.exists() or not list(cfg_dir.iterdir())


def test_corrupt_or_invalid_newest_is_skipped(cfg_dir, base):
    good = ac.save_version(copy.deepcopy(base), changed_by="x", reason_vi="r")
    (cfg_dir / "v0002-20991231T000000Z.json").write_text("{not json", encoding="utf-8")
    broken = copy.deepcopy(base)
    broken["hazards"]["heat"]["thresholds"] = {"1": 40, "2": 30}
    (cfg_dir / "v0003-20991231T000001Z.json").write_text(json.dumps(broken), encoding="utf-8")
    assert ac.load_effective()["config_version"] == good
    assert len(ac.list_versions()) == 2  # corrupt one skipped in listing


def test_get_version_rejects_traversal_and_missing(cfg_dir):
    for bad in ("../x", "v1", "nope", ""):
        with pytest.raises(KeyError):
            ac.get_version(bad)
    with pytest.raises(KeyError):
        ac.get_version("v0009-20261023T000000Z")


@pytest.mark.parametrize("mutate,needle", [
    (lambda c: c["hazards"]["storm_wind"]["thresholds"].update({"3": 8}), "strictly greater"),
    (lambda c: c["hazards"]["cold"]["thresholds"].update({"2": 23}), "strictly less"),
    (lambda c: c["hazards"]["storm_wind"]["thresholds"].update({"1": 3}), "guardrail min"),
    (lambda c: c["hazards"]["storm_wind"]["thresholds"].update({"4": 20}), "guardrail max"),
    (lambda c: c["hazards"]["storm_wind"]["thresholds"].update({"7": 20}), "unknown tier"),
    (lambda c: c["hazards"]["storm_wind"]["thresholds"].update({"0": 1}), "tier 0"),
    (lambda c: c["hazards"]["storm_wind"]["thresholds"].update({"1": "x"}), "finite number"),
    (lambda c: c["hazards"]["storm_wind"]["thresholds"].update({"1": float("nan")}), "finite number"),
    (lambda c: c["hazards"]["storm_wind"]["actions_vi"].pop("3"), "missing action"),
    (lambda c: c["hazards"]["storm_wind"].update({"bogus": 1}), "unknown key"),
    (lambda c: c.update({"bogus": 1}), "unknown top-level"),
    (lambda c: c["hazards"]["heat"].update({"direction": "up"}), "direction"),
    (lambda c: c["hazards"]["heat"]["persistence_days"].update({"2": 0}), ">= 1"),
    (lambda c: c["scopes"]["exposure_class"].update({"huge": {}}), "unknown exposure class"),
    (lambda c: c["scopes"]["station"].update({"NB1": {"nope": {}}}), "unknown hazard"),
    (lambda c: c["scopes"]["station"].update({"NB1": {"storm_wind": {"thresholds": {"2": 5}}}}), "strictly"),
    (lambda c: c["scopes"]["station"].update({"NB1": {"storm_wind": {"zzz": 1}}}), "unknown key"),
])
def test_validation_rules(base, mutate, needle):
    c = copy.deepcopy(base)
    mutate(c)
    errs = ac.validate(c)
    assert any(needle in e for e in errs), errs


def test_scope_merge_precedence(cfg_dir, base):
    c = copy.deepcopy(base)
    c["scopes"]["exposure_class"]["exposed"] = {"storm_wind": {"thresholds": {"2": 7}}}
    c["scopes"]["station"]["NB1"] = {"storm_wind": {"thresholds": {"2": 7.5}}}
    ac.save_version(c, changed_by="x", reason_vi="r")
    assert ac.load_effective()["hazards"]["storm_wind"]["thresholds"]["2"] == 8
    assert ac.load_effective(exposure_class="exposed")["hazards"]["storm_wind"]["thresholds"]["2"] == 7
    eff = ac.load_effective("NB1", "exposed")
    assert eff["hazards"]["storm_wind"]["thresholds"] == {"1": 6, "2": 7.5, "3": 10, "4": 12}
    assert ac.load_effective("OTHER", "semi")["hazards"]["storm_wind"]["thresholds"]["2"] == 8
    # persistence_days passes through untouched
    assert eff["hazards"]["heat"]["persistence_days"] == {"2": 3, "3": 3}


def test_tier_for_directions_and_nan(base):
    assert ac.tier_for("storm_wind", 5.9, base) == 0
    assert ac.tier_for("storm_wind", 6, base) == 1
    assert ac.tier_for("storm_wind", 10.5, base) == 3
    assert ac.tier_for("storm_wind", 99, base) == 4
    assert ac.tier_for("cold", 25, base) == 0
    assert ac.tier_for("cold", 22, base) == 1
    assert ac.tier_for("cold", 17, base) == 2
    assert ac.tier_for("cold", 10, base) == 3
    assert ac.tier_for("heat", float("nan"), base) is None
    assert ac.tier_for("heat", None, base) is None
    with pytest.raises(KeyError):
        ac.tier_for("nope", 1, base)


def test_concurrent_saves_never_collide(cfg_dir, base):
    n = 12
    results, errors = [], []
    barrier = threading.Barrier(n)

    def work(i):
        c = copy.deepcopy(base)
        c["hazards"]["heat"]["thresholds"]["1"] = 30.0 + i / 100
        barrier.wait()
        try:
            results.append(ac.save_version(c, changed_by=f"t{i}", reason_vi="r"))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert len(set(results)) == n
    numbers = sorted(int(v[1:5]) for v in results)
    assert numbers == list(range(1, n + 1))
    assert len(list(cfg_dir.glob("v*.json"))) == n


@pytest.mark.parametrize("mutate,needle", [
    (lambda c: c["hazards"]["heat"].update({"metric": "x"}), "heat.metric"),
    (lambda c: c["hazards"]["heat"].update({"unit": "x"}), "heat.unit"),
    (lambda c: c["hazards"]["cold"].update({"direction": "ge"}), "cold.direction"),
    (lambda c: c["hazards"]["heat"].update({"label_vi": "x"}), "heat.label_vi"),
    (lambda c: c["hazards"]["heat"].update({"evidence": []}), "heat.evidence"),
    (lambda c: c["hazards"]["storm_wind"]["guardrails"]["max"].update({"4": 20}), "guardrails"),
    (lambda c: c["tiers"].pop(), "tiers"),
    (lambda c: c["hazards"].pop("cold"), "cannot be removed"),
    (lambda c: c["hazards"].update({"zz": copy.deepcopy(c["hazards"]["heat"])}), "cannot be added"),
    (lambda c: c["scopes"]["station"].update({"NB1": {"heat": {"unit": "K"}}}), "not editable"),
])
def test_structure_locked(cfg_dir, base, mutate, needle):
    c = copy.deepcopy(base)
    mutate(c)
    assert any(needle in e for e in ac.structural_errors(c, base)), ac.structural_errors(c, base)
    with pytest.raises(ac.ConfigValidationError):
        ac.save_version(c, changed_by="x", reason_vi="r")


def test_structure_default_and_allowed_edits_ok(base):
    c = copy.deepcopy(base)
    c["hazards"]["heat"]["thresholds"]["1"] = 30.5
    c["hazards"]["heat"]["actions_vi"]["1"] = "mới"
    c["scopes"]["station"]["NB1"] = {"heat": {"persistence_days": {"2": 5}}}
    assert ac.structural_errors(c, base) == []
