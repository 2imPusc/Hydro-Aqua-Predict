"""Paper 1 / T4c helpers (synthetic frames only, no data, no torch)."""
import numpy as np
import pandas as pd
import pytest

from experiments import paper1_t4c_hybrid_pi as t4c


def _frame(n=200, horizon=360, seed=0, start="2025-02-01"):
    rng = np.random.default_rng(seed)
    issued = pd.date_range(start, periods=n, freq="6h")
    y = 20 + rng.normal(0, 1, n)
    f = pd.DataFrame({"station": "apacpwq", "issued_at": issued, "horizon_minutes": horizon, "y": y,
                      t4c.STACK: y + rng.normal(0, 0.3, n), t4c.RIDGE: y + rng.normal(0, 0.35, n),
                      t4c.RIDGE3H: y + rng.normal(0, 0.35, n), "amp": rng.uniform(1, 3, n)})
    f["q50"] = y + rng.normal(0, 0.4, n)
    f["q10"], f["q90"] = f["q50"] - 0.5, f["q50"] + 0.7
    f["known_at"] = t4c.known_at_of(f)
    return f


def test_six_candidates_and_reference_uses_same_rule():
    assert len(t4c.CANDIDATES) == 6
    for name, (_model, method, rule) in t4c.CANDIDATES.items():
        assert method.endswith(rule)
        assert t4c.reference_of(name) == (t4c.RIDGE, f"abs_{rule}")
    assert t4c.reference_of("cqr_shift_aci", t4c.RIDGE3H) == (t4c.RIDGE3H, "abs_aci")


def test_shifted_quantiles_keep_chronos_spread_around_point():
    lo, hi = t4c.shifted_quantiles([10.0, 5.0], [8.0, 1.0], [9.0, 2.0], [11.0, 4.0])
    np.testing.assert_allclose(lo, [9.0, 4.0])
    np.testing.assert_allclose(hi, [12.0, 7.0])
    np.testing.assert_allclose(hi - lo, [3.0, 3.0])


def test_known_at_is_valid_time():
    f = pd.DataFrame({"issued_at": pd.to_datetime(["2025-03-01 06:00", "2025-03-01 06:00"]), "horizon_minutes": [15, 720]})
    assert list(t4c.known_at_of(f)) == list(pd.to_datetime(["2025-03-01 06:15", "2025-03-01 18:00"]))


def test_split_drops_straddlers():
    f = _frame(n=400, horizon=720)
    cal, ev, straddle = t4c.split_cal_eval(f)
    assert (cal["known_at"] < t4c.EVAL_START).all() and (ev["issued_at"] >= t4c.EVAL_START).all()
    assert straddle == 2  # origins at 2025-04-30 12:00 and 18:00 mature after 05-01
    assert len(cal) + len(ev) + straddle == len(f)


def _intervals(f):
    cal, ev, _ = t4c.split_cal_eval(f)
    return {m: v for m, v in t4c.intervals_for_group(cal, ev, 0.5, int(f["horizon_minutes"].iloc[0]))}


def test_future_outcome_cannot_change_earlier_intervals():
    f = _frame(n=400, horizon=720)
    base = _intervals(f)
    _, ev, _ = t4c.split_cal_eval(f)
    k = 30
    target = ev.index[k]
    changed = f.copy()
    changed.loc[target, "y"] += 50.0
    new = _intervals(changed)
    # origin k matures 2 origins later (720 min, stride 360): intervals up to k + 1 are unchanged
    for model in base:
        for method, (lo, hi) in base[model].items():
            np.testing.assert_array_equal(new[model][method][0][: k + 2], lo[: k + 2])
    lo_aci = new[t4c.STACK]["abs_aci"][0]
    assert not np.array_equal(lo_aci[k + 2:], base[t4c.STACK]["abs_aci"][0][k + 2:])


def test_all_constructions_present():
    out = _intervals(_frame())
    assert set(out[t4c.STACK]) >= {"abs_static", "abs_aci", "abs_aci_amp"}
    assert set(out[t4c.STACK_CQR]) >= {"raw", "cqr_static", "cqr_aci", "cqr_aci_amp"}
    assert set(out[t4c.CHRONOS]) >= {"raw", "cqr_static", "cqr_aci", "cqr_aci_amp"}
    # raw of the shifted construction is centred on the stack point
    f = _frame()
    _, ev, _ = t4c.split_cal_eval(f)
    ev = ev.sort_values("issued_at")
    lo, hi = out[t4c.STACK_CQR]["raw"]
    np.testing.assert_allclose(lo, ev[t4c.STACK] - 0.5)
    np.testing.assert_allclose(hi, ev[t4c.STACK] + 0.7)


def _cell(cov=0.80, inf=0.0, ratio=1.0, n=100):
    m = pd.DataFrame({"group": ["A"], "horizon_minutes": [15], "n": [n], "coverage": [cov], "frac_infinite": [inf]})
    r = pd.DataFrame({"group": ["A"], "horizon_minutes": [15], "winkler_ratio": [ratio]})
    return t4c.cells(m, r, ["group", "horizon_minutes"]).iloc[0]


def test_cell_rule_boundaries():
    assert _cell(ratio=1.00)["cell_pass"]
    assert not _cell(ratio=1.0001)["cell_pass"]
    assert _cell(cov=0.75)["cell_pass"] and _cell(cov=0.85)["cell_pass"]
    assert not _cell(cov=0.749)["cell_pass"] and not _cell(cov=0.851)["cell_pass"]
    assert not _cell(inf=0.011)["cell_pass"]
    assert not _cell(n=49)["cell_pass"]
    assert _cell(cov=0.9)["cell_winkler"] and not _cell(cov=0.9)["cell_coverage"]


def _table(spec):
    rows = []
    for cand, (cov_cells, pass_cells, common) in spec.items():
        for i in range(18):
            rows.append({"candidate": cand, "cell_coverage": i < cov_cells, "cell_pass": i < pass_cells, "winkler_ratio_common": common})
    return pd.DataFrame(rows)


def test_selection_rule_eligibility_then_pass_then_common_ratio_then_simplicity():
    base = {c: (18, 10, 1.0) for c in t4c.CANDIDATES}
    spec = dict(base, abs_aci=(14, 17, 0.5))           # most passes but not eligible
    spec["cqr_shift_aci_amp"] = (16, 12, 0.95)
    spec["abs_aci_amp"] = (15, 12, 0.90)
    assert t4c.select_primary(_table(spec))["selected"] == "abs_aci_amp"
    tie = dict(base)
    tie["abs_aci_amp"] = (18, 12, 0.9)
    tie["cqr_shift_static"] = (18, 12, 0.9)
    assert t4c.select_primary(_table(tie))["selected"] == "cqr_shift_static"
    none_eligible = {c: (10, 3, 1.0) for c in t4c.CANDIDATES}
    none_eligible["cqr_shift_aci"] = (10, 4, 1.0)
    out = t4c.select_primary(_table(none_eligible))
    assert out["selected"] == "cqr_shift_aci" and not out["any_eligible"]


def test_verdict_labels():
    t = pd.DataFrame({"group": ["A"] * 6 + ["B"] * 6 + ["C"] * 6, "cell_pass": [True] * 17 + [False]})
    per = t4c.reserve_verdict(t)
    assert per == {"A": True, "B": True, "C": False}
    assert t4c.overall_verdict(per) == "partially_supported"
    assert t4c.overall_verdict({"A": True, "B": True, "C": True}) == "supported"
    assert t4c.overall_verdict({"A": True, "B": False, "C": False}) == "rejected"
    assert t4c.overall_verdict({"A": True, "B": True}) == "rejected"
    short = t.iloc[1:]
    assert not t4c.reserve_verdict(short)["A"]


def test_stage_conf_refuses_without_preregistration(tmp_path, monkeypatch):
    monkeypatch.setattr(t4c, "run_dir", lambda: tmp_path)
    with pytest.raises(FileNotFoundError):
        t4c.stage_conf(None)
