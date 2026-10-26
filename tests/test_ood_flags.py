"""Per-metric toggles of the imputer "outside training range" flag (alert-config ``ood_flags``).

Toggles change what is surfaced (aggregate ``ood``, warnings); the per-feature list is always logged.
"""
import copy
import json

import pytest

from core import alert_config as ac
from core import impute, paths

# HP p1–p99: TAN 0.040–0.497, pH 7.40–8.40, Temperature 16.5–32.5, TSS 10.5–27.7
IN_RANGE = {"TAN": 0.1, "NH3": 0.004, "pH": 7.9, "Temperature": 28.0, "TSS": 20.0}


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    d = tmp_path / "alert-config"
    monkeypatch.setattr(paths, "ALERT_CONFIG_DIR", d)
    return d


def _flags(**enabled):
    cfg = ac.load_default()
    for metric, on in enabled.items():
        cfg["ood_flags"]["metrics"][metric]["enabled"] = on
    return ac.ood_flag_settings(cfg)


# --- defaults / settings ---------------------------------------------------------

def test_default_toggles_tss_muted_with_reason():
    s = ac.ood_flag_settings()
    assert s["source"] == "config" and s["config_version"] == ac.load_default()["config_version"]
    assert s["muted_metrics"] == ["TSS"] and s["muted_features"] == ["TSS"]
    on = {f: v["enabled"] for f, v in s["features"].items()}
    assert on == {"NH3": True, "pH": True, "Temperature": True, "TSS": False, "COD": True}
    assert s["features"]["NH3"]["metric"] == "TAN"
    assert "cơ sở TSS" in s["features"]["TSS"]["muted_reason_vi"]


def test_broken_section_falls_back_to_all_enabled():
    cfg = ac.load_default()
    cfg["ood_flags"]["metrics"]["TSS"]["enabled"] = "no"
    s = ac.ood_flag_settings(cfg)
    assert s["source"] == "fallback_all_enabled" and s["muted_metrics"] == [] and s["features"] == {}


# --- impute: logged always, surfaced per toggle -----------------------------------

def test_muted_tss_is_logged_but_not_surfaced():
    r = impute.impute_params({**IN_RANGE, "TSS": 80.0}, region="haiphong", ood_flags=_flags())
    d = r["diagnostics"]
    assert d["ood_features"] == ["TSS"]            # always recorded
    assert d["ood_features_muted"] == ["TSS"] and d["ood_features_surfaced"] == []
    assert d["ood"] is False and d["ood_any"] is True
    assert d["ood_targets"] == [] and d["ood_targets_all"] == sorted(r["imputed"])
    assert r["input_flagged"] is False
    assert d["ood_flags"]["muted_metrics"] == ["TSS"]


def test_enabling_tss_surfaces_it():
    r = impute.impute_params({**IN_RANGE, "TSS": 80.0}, region="haiphong", ood_flags=_flags(TSS=True))
    d = r["diagnostics"]
    assert d["ood"] is True and d["ood_features_surfaced"] == ["TSS"] and d["ood_features_muted"] == []
    assert d["ood_targets"] == sorted(r["imputed"]) and r["input_flagged"] is True
    assert d["ood_flags"]["muted_metrics"] == []


def test_tan_toggle_maps_to_provincial_nh3_feature():
    low = {**IN_RANGE, "TAN": 0.004}
    on = impute.impute_params(dict(low), region="haiphong", ood_flags=_flags())["diagnostics"]
    assert on["ood"] is True and on["ood_features_surfaced"] == ["NH3"]
    off = impute.impute_params(dict(low), region="haiphong", ood_flags=_flags(TAN=False))["diagnostics"]
    assert off["ood"] is False and off["ood_features"] == ["NH3"] and off["ood_features_muted"] == ["NH3"]


def test_mixed_muted_and_surfaced():
    d = impute.impute_params({**IN_RANGE, "TAN": 0.004, "TSS": 80.0}, region="haiphong",
                             ood_flags=_flags())["diagnostics"]
    assert d["ood_features"] == ["NH3", "TSS"]
    assert d["ood_features_surfaced"] == ["NH3"] and d["ood_features_muted"] == ["TSS"] and d["ood"] is True


def test_impute_without_flags_reads_effective_config(cfg_dir):
    d = impute.impute_params({**IN_RANGE, "TSS": 80.0}, region="haiphong")["diagnostics"]
    assert d["ood"] is False and d["ood_flags"]["config_version"] == ac.load_default()["config_version"]
    cfg = ac.load_effective()
    cfg["ood_flags"]["metrics"]["TSS"]["enabled"] = True
    v = ac.save_version(cfg, changed_by="t", reason_vi="bật lại TSS")
    d = impute.impute_params({**IN_RANGE, "TSS": 80.0}, region="haiphong")["diagnostics"]
    assert d["ood"] is True and d["ood_flags"]["config_version"] == v


# --- classify warning ----------------------------------------------------------------

def test_classify_warning_states_muted_metric():
    from core.classify import classify_station
    r = classify_station("06M26042804", {**IN_RANGE, "TSS": 80.0}, "cobia", region="haiphong", ood_flags=_flags())
    assert "gắn cờ OOD" not in r["warning"]
    assert "đã tắt cho TSS" in r["warning"]
    assert r["imputation_diagnostics"]["ood_features"] == ["TSS"]
    r2 = classify_station("06M26042804", {**IN_RANGE, "TAN": 0.004}, "cobia", region="haiphong", ood_flags=_flags())
    assert "Input ngoài dải huấn luyện (p1–p99) TAN" in r2["warning"]


# --- contextual gate unchanged, muted annotated ------------------------------------

def test_contextual_still_rejects_but_annotates_muted(monkeypatch):
    from core import contextual_models
    monkeypatch.setattr(contextual_models, "NH4_CONVERSION_CONFIRMED", True)
    out = contextual_models.predict_haiphong_contextual({**IN_RANGE, "TSS": 80.0}, "2026-07-25T00:00:00Z",
                                                        ood_flags=_flags())
    do = out["predictions"]["DO"]
    assert do["status"] == "rejected" and do["ood_features"] == ["TSS"] and do["ood_features_muted"] == ["TSS"]


# --- config schema / versioning -------------------------------------------------------

def test_default_config_valid_and_toggle_saves_as_new_version(cfg_dir):
    base = ac.load_default()
    assert ac.validate(base) == [] and ac.structural_errors(base) == []
    cfg = copy.deepcopy(base)
    cfg["ood_flags"]["metrics"]["TSS"]["enabled"] = True
    v1 = ac.save_version(cfg, changed_by="t", reason_vi="r")
    saved = ac.get_version(v1)
    assert saved["changes"] == [{"path": "ood_flags.metrics.TSS.enabled", "old": False, "new": True}]
    assert ac.load_effective()["ood_flags"]["metrics"]["TSS"]["enabled"] is True
    # restore = save the older content again as a newer version; nothing is overwritten
    v2 = ac.save_version(copy.deepcopy(base), changed_by="t", reason_vi="khôi phục")
    assert v2 > v1 and (cfg_dir / f"{v1}.json").is_file()
    assert ac.ood_flag_settings()["muted_metrics"] == ["TSS"]


@pytest.mark.parametrize("mutate,needle", [
    (lambda c: c["ood_flags"]["metrics"]["TSS"].__setitem__("feature", "Turbidity"), "TSS.feature: not editable"),
    (lambda c: c["ood_flags"]["metrics"]["TSS"].__setitem__("label_vi", "x"), "TSS.label_vi: not editable"),
    (lambda c: c["ood_flags"]["metrics"].pop("COD"), "COD: metric cannot be removed"),
    (lambda c: c["ood_flags"]["metrics"].__setitem__("DO", {"feature": "DO", "enabled": True}), "DO: metric cannot be added"),
])
def test_structure_locked(mutate, needle):
    cfg = ac.load_default()
    mutate(cfg)
    assert any(needle in e for e in ac.structural_errors(cfg))


def test_validate_rejects_bad_types():
    cfg = ac.load_default()
    cfg["ood_flags"]["metrics"]["pH"]["enabled"] = 1
    cfg["ood_flags"]["metrics"]["COD"]["feature"] = "pH"
    cfg["ood_flags"]["extra"] = {}
    errs = ac.validate(cfg)
    assert any("pH.enabled: must be true or false" in e for e in errs)
    assert any("COD.feature: 'pH' already used" in e for e in errs)
    assert any("unknown key 'extra'" in e for e in errs)


def test_pre_schema2_version_stays_valid_and_gets_default_toggles(cfg_dir):
    old = ac.load_default()
    old.pop("ood_flags")
    old["schema_version"] = 1
    old["hazards"]["heat"]["thresholds"]["1"] = 30.5
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "v0001-20261024T000000Z.json").write_text(
        json.dumps({**old, "config_version": "v0001-20261024T000000Z"}), encoding="utf-8")
    eff = ac.load_effective()
    assert eff["config_version"] == "v0001-20261024T000000Z"
    assert eff["ood_flags"] == ac.load_default()["ood_flags"]
    assert ac.ood_flag_settings()["muted_metrics"] == ["TSS"]
    # saving on top of it diffs against the effective toggles, not "everything added"
    eff["ood_flags"]["metrics"]["pH"]["enabled"] = False
    v = ac.save_version(eff, changed_by="t", reason_vi="r")
    saved = ac.get_version(v)
    assert saved["schema_version"] == 2
    paths_changed = [c["path"] for c in saved["changes"]]
    assert "ood_flags.metrics.pH.enabled" in paths_changed
    assert not any(p.startswith("ood_flags.metrics.TSS") for p in paths_changed)


def test_shadow_ledger_keeps_full_and_muted_ood_detail(tmp_path, monkeypatch):
    from core import forecast_evaluation as fe
    monkeypatch.setattr(fe, "STORE_DIR", tmp_path)
    monkeypatch.setattr(fe, "FORECAST_LOG", tmp_path / "forecasts.jsonl")
    diag = {"DO": {"status": "rejected", "missing_features": [], "invalid_features": [],
                   "ood_features": ["TSS"], "ood_features_muted": ["TSS"]}}
    future = {"status": "ready", "base_timestamp": "2026-07-01T00:00:00+00:00", "timeline": [{
        "horizon_minutes": 15, "timestamp": "2026-07-01T00:15:00+00:00",
        "sensors": {"Temperature": 30., "pH": 7.8, "NH4": .1, "TSS": 80.}, "sensor_sources": {},
        "inferred": {}, "contextual_status": "ready", "inference_diagnostics": diag}]}
    assert fe.record_sensor_future("06M26042804", future) == 1
    assert fe._read_jsonl(fe.FORECAST_LOG)[0]["inference_diagnostics"] == diag
