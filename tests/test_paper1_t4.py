"""Paper 1 / T4 helpers (synthetic frames only, no data, no torch)."""
import json

import numpy as np
import pandas as pd
import pytest

from core.forecast_intervals import aci_amp_half_width
from experiments import paper1_t4_conformal as t4
from experiments.forecast_conformal import GATE_MAX_FRAC_INFINITE, GATE_PI80, aci_intervals, trailing_amplitude, winkler_score


def _times(n, stride=15, start="2026-01-01"):
    return pd.date_range(start, periods=n, freq=f"{stride}min")


def _path(score, horizon=60, stride=15, amp=None, known=None, gamma=0.05, floor=0.5, cal=None):
    issued = _times(len(score), stride)
    known = issued + pd.Timedelta(minutes=horizon) if known is None else known
    amp = np.full(len(score), 2.0) if amp is None else amp
    cal = np.linspace(0.05, 1.0, 40) if cal is None else cal
    return t4.aci_amp_path(cal, issued, known, score, amp, floor, 0.2, gamma)


def test_outcome_not_yet_known_cannot_change_the_interval():
    rng = np.random.default_rng(0)
    score = rng.uniform(0, 2, 60)
    base = _path(score)
    changed = score.copy()
    changed[20] = 500.0  # known at origin 24 (60 min, stride 15)
    q = _path(changed)
    np.testing.assert_array_equal(q[:24], base[:24])
    assert q[24] != base[24]


def test_known_at_one_second_after_issue_is_excluded_and_at_issue_is_included():
    issued = _times(8)
    score = np.array([9.0] * 8)
    late = pd.DatetimeIndex(issued + pd.Timedelta(minutes=60))
    # origin 0 exactly at the issue time of origin 4 -> used; 1 s later -> not used at origin 4
    at_issue = _path(score, known=late)
    one_second_late = late.to_series().copy()
    one_second_late.iloc[0] += pd.Timedelta(seconds=1)
    after = _path(score, known=pd.DatetimeIndex(one_second_late))
    assert at_issue[4] != after[4]
    np.testing.assert_array_equal(at_issue[:4], after[:4])


def test_known_before_issue_is_refused():
    issued = _times(3)
    with pytest.raises(ValueError):
        t4.aci_amp_path(np.ones(10), issued, issued - pd.Timedelta(seconds=1), np.ones(3), np.ones(3), 0.5, 0.2, 0.01)


def test_future_scores_never_change_past_q_at_any_cut():
    rng = np.random.default_rng(1)
    score = rng.uniform(0, 2, 50)
    base = _path(score)
    for cut in (10, 30):
        tail = score.copy()
        tail[cut:] = rng.uniform(5, 9, 50 - cut)
        np.testing.assert_array_equal(_path(tail)[:cut + 4], base[:cut + 4])


def test_path_matches_vectorised_aci_with_constant_amplitude():
    rng = np.random.default_rng(2)
    score = rng.uniform(0, 2, 80)
    cal = rng.uniform(0, 2, 60)
    issued = _times(80)
    known = issued + pd.Timedelta(minutes=60)
    q_core = t4.aci_amp_path(cal, issued, known, score, np.ones(80), 0.5, 0.2, 0.01)
    q_vec, _ = aci_intervals(cal, issued, known, score, 0.2, 0.01)
    np.testing.assert_allclose(q_core, q_vec)


def test_path_state_equals_direct_core_call_at_an_origin():
    rng = np.random.default_rng(3)
    score, amp = rng.uniform(0, 2, 30), rng.uniform(1, 4, 30)
    cal = rng.uniform(0, 1, 40)
    q = _path(score, amp=amp, cal=cal)
    i = 20
    # 60 min at stride 15: origin i knows origins s <= i - 4
    direct = aci_amp_half_width(cal, [(score[s], amp[s], q[s]) for s in range(i - 3)], amp[i], 0.2, 0.05, 0.5)
    assert direct["n_live"] == i - 3
    assert q[i] == pytest.approx(direct["q"])


def test_six_hour_stride_long_horizon_delays_feedback_two_origins():
    # h = 720, stride 360: origin t knows only origins <= t - 2
    score = np.full(6, 50.0)
    q_all = _path(score, horizon=720, stride=360)
    changed = score.copy()
    changed[3] = 0.0
    q = _path(changed, horizon=720, stride=360)
    np.testing.assert_array_equal(q[:5], q_all[:5])
    assert q[5] != q_all[5]
    assert t4.feedback_lag(720, 360) == 2 and t4.feedback_lag(15, 360) == 1


def test_gamma_rule_reduces_to_rl19_at_one_minute_stride():
    for h in t4.HORIZONS:
        assert t4.gamma_primary(h, 1) == pytest.approx(0.005 * 15 / h)
    assert t4.gamma_primary(15, 15) == pytest.approx(0.075)
    assert t4.gamma_primary(720, 360) == pytest.approx(0.0375)
    assert t4.gamma_literal(720) == pytest.approx(0.005 * 15 / 720)


def test_trailing_amplitude_ignores_future_spike():
    idx = _times(200)
    values = np.sin(np.arange(200) / 10.0)
    at = idx[[120]]
    base = trailing_amplitude(pd.Series(values, index=idx), at, "24h", "range", 48)
    spiked = values.copy()
    spiked[121:] = 99.0
    assert trailing_amplitude(pd.Series(spiked, index=idx), at, "24h", "range", 48)[0] == base[0]
    spiked[120] = 99.0  # the value stamped at the issue time is known then
    assert trailing_amplitude(pd.Series(spiked, index=idx), at, "24h", "range", 48)[0] != base[0]


def test_cqr_score_sign_and_interval():
    assert t4.cqr_score(np.array([5.0]), np.array([1.0]), np.array([3.0]))[0] == 2.0
    assert t4.cqr_score(np.array([2.0]), np.array([1.0]), np.array([3.0]))[0] == -1.0
    low, up = t4.interval_from_q(np.array([1.0]), np.array([3.0]), np.array([0.5]))
    assert (low[0], up[0]) == (0.5, 3.5)
    # covered exactly when score <= q
    y = np.array([0.4, 0.5, 3.5, 3.6])
    s = t4.cqr_score(y, np.full(4, 1.0), np.full(4, 3.0))
    low, up = t4.interval_from_q(np.full(4, 1.0), np.full(4, 3.0), np.full(4, 0.5))
    np.testing.assert_array_equal(s <= 0.5, (y >= low) & (y <= up))


def test_crossed_interval_collapses_to_midpoint():
    low, up = t4.interval_from_q(np.array([1.0]), np.array([3.0]), np.array([-5.0]))
    assert low[0] == up[0] == 2.0


def test_winkler_reduces_to_library_on_symmetric_interval():
    y = np.array([0.0, 1.5, -3.0])
    q = np.array([1.0, 1.0, 2.0])
    np.testing.assert_allclose(t4.winkler_interval(y, -q, q, 0.2), winkler_score(np.abs(y), q, 0.2))


def _group(n=40, seed=0):
    rng = np.random.default_rng(seed)
    issued = _times(n)
    y = rng.normal(20, 1, n)
    return pd.DataFrame({
        "issued_at": issued, "known_at": issued + pd.Timedelta(minutes=60), "y": y, "lo": y - rng.uniform(-1, 2, n),
        "hi": y + rng.uniform(-1, 2, n), "point": y + rng.normal(0, 0.5, n), "amp": rng.uniform(1, 3, n),
    })


def test_methods_all_present_and_static_constant_shift():
    cal, ev = _group(60, 1), _group(30, 2)
    q = t4.methods_for_group(cal, ev, 0.5, 60, 15, "quantile")
    assert set(q) == {"raw", "cqr_static", "cqr_aci", "cqr_aci_amp", "cqr_aci_amp_literal", "sym_aci_amp"}
    r = t4.methods_for_group(cal, ev, 0.5, 60, 15, "point")
    assert set(r) == {"ridge_static", "ridge_aci", "ridge_aci_amp", "ridge_aci_amp_literal"}
    width = r["ridge_static"][1] - r["ridge_static"][0]
    assert np.ptp(width) < 1e-9


def test_missing_amplitude_gives_infinite_not_guessed():
    cal, ev = _group(60, 1), _group(10, 2)
    ev.loc[3, "amp"] = np.nan
    low, up = t4.methods_for_group(cal, ev, 0.5, 60, 15, "point")["ridge_aci_amp"]
    assert np.isinf(up[3]) and np.isfinite(up[2])
    rows = t4.add_outcomes(pd.DataFrame({"y": ev["y"], "lower": low, "upper": up}))
    assert bool(rows["covered"].iloc[3]) and not bool(rows["finite"].iloc[3])
    assert np.isnan(rows["winkler"].iloc[3])


def test_winkler_ratio_uses_only_rows_finite_on_both_sides():
    base = {"issued_at": _times(3), "horizon_minutes": 15, "regime": "large"}
    a = pd.DataFrame({**base, "model": "a", "method": "m", "finite": [True, True, False], "winkler": [2.0, 2.0, np.nan]})
    b = pd.DataFrame({**base, "model": "b", "method": "m", "finite": [True, False, True], "winkler": [1.0, np.nan, 100.0]})
    out = t4.winkler_ratio_cells(pd.concat([a, b]), ("a", "m"), ("b", "m"), ["horizon_minutes", "regime"])
    assert out["n_paired"].iloc[0] == 1 and out["winkler_ratio"].iloc[0] == 2.0


def _cells(cov=0.8, inf=0.0, ratio=1.0, n=100):
    m = pd.DataFrame({"horizon_minutes": [15], "regime": ["large"], "n": [n], "coverage": [cov], "frac_infinite": [inf]})
    r = pd.DataFrame({"horizon_minutes": [15], "regime": ["large"], "winkler_ratio": [ratio]})
    return t4.h3_cells(m, r, ["horizon_minutes", "regime"])


def test_h3_cell_rule_boundaries():
    assert _cells()["h3_pass"].iloc[0]
    assert _cells(cov=0.75)["h3_pass"].iloc[0] and _cells(cov=0.85)["h3_pass"].iloc[0]
    assert not _cells(cov=0.749)["h3_pass"].iloc[0]
    assert not _cells(inf=0.02)["h3a_coverage"].iloc[0]
    assert not _cells(ratio=1.051)["h3_pass"].iloc[0] and _cells(ratio=1.051)["h3a_coverage"].iloc[0]
    assert not _cells(n=49)["h3_pass"].iloc[0]


def test_nb1_verdict_can_never_be_plain_pass_without_small_regime():
    ok = _cells()
    assert t4.verdict_nb1(ok, 0) == "not_fully_testable_large_only_pass"
    assert t4.verdict_nb1(_cells(cov=0.5), 0) == "fail"
    assert t4.verdict_overall("not_fully_testable_large_only_pass", "pass") == "partially_supported"
    assert t4.verdict_overall("fail", "pass") == "rejected"
    assert t4.verdict_overall("not_fully_testable_large_only_pass", "fail") == "rejected"


def test_cdmo_verdict_needs_all_cells():
    ok = pd.concat([_cells()] * 36)
    assert t4.verdict_cdmo(ok) == "pass"
    assert t4.verdict_cdmo(pd.concat([_cells()] * 35)) == "fail"
    assert t4.verdict_cdmo(pd.concat([_cells()] * 35 + [_cells(cov=0.6)])) == "fail"


def test_regime_by_median():
    assert t4.regime_by_median(np.array([1.0, 2.0, 3.0, np.nan]), 2.0).tolist() == ["small", "large", "large", "unknown"]


def test_block_boot_is_seeded_and_brackets():
    day = np.repeat(np.arange(20), 5)
    x = (np.arange(100) % 5 < 4).astype(float)
    assert t4.block_boot(day, x) == t4.block_boot(day, x)
    assert t4.block_boot(day, x) == pytest.approx((0.8, 0.8))


def test_preregistration_matches_code():
    pre = json.loads(t4.PREREG_FILE.read_text(encoding="utf-8"))
    h3 = pre["h3"]
    assert pre["run_name"] == t4.RUN_NAME and pre["alpha"] == t4.ALPHA
    assert tuple(h3["coverage_band"]) == tuple(GATE_PI80) and h3["max_frac_infinite"] == GATE_MAX_FRAC_INFINITE
    assert h3["max_winkler_ratio"] == t4.MAX_WINKLER_RATIO and h3["min_cell_rows"] == t4.MIN_CELL_ROWS
    assert tuple(h3["horizons_minutes"]) == t4.HORIZONS


def _fake_artifacts(root):
    rng = np.random.default_rng(0)
    exp = root / "experiments"
    t1, t3, bench = exp / "paper1-t1-20261028", exp / "paper1-t3-20261029", exp / "forecast-h1-diurnal-20261025" / "bench-Temperature"
    (t3 / "data-cdmo").mkdir(parents=True)
    t1.mkdir(parents=True)
    bench.mkdir(parents=True)
    minutes = pd.date_range("2026-09-01", "2026-10-02", freq="min", tz="UTC")
    temp = 28 + 2 * np.sin(np.arange(len(minutes)) / 229.0)
    pers = pd.DataFrame({"issued_at": minutes, "prediction": temp, "model": "persistence", "feature_set": t4.RIDGE_B5D, "horizon_minutes": 15})
    origins = minutes[minutes.minute % 15 == 0]
    origins = origins[origins >= pd.Timestamp("2026-09-03", tz="UTC")]
    base = pd.DataFrame([{"issued_at": t, "horizon_minutes": h} for t in origins[:1500] for h in t4.HORIZONS])
    base["actual"] = 28 + rng.normal(0, 0.5, len(base))
    base["split"] = "rolling"
    edges = base["issued_at"].rank(pct=True)
    base["fold"] = np.minimum(np.floor(edges * 6).astype(int) + 1, 6)
    base.loc[base["fold"] == 6, "split"] = "lockbox"
    base.loc[base["fold"] == 6, "fold"] = 0
    fm = base.assign(q50=base["actual"] + rng.normal(0, 0.3, len(base)))
    fm["q10"], fm["q90"] = fm["q50"] - 0.4, fm["q50"] + 0.4
    for m in ("chronos-2-small", "chronos-2-base"):
        fm.to_parquet(t1 / f"fm-Temperature-{m}-stride15.parquet")
    ridges = [base.assign(model="ridge", feature_set=f, prediction=base["actual"] + rng.normal(0, 0.3, len(base))) for f in t4.RIDGE_NB1]
    b = pd.concat(ridges)
    b["valid_at"] = b["issued_at"] + pd.to_timedelta(b["horizon_minutes"], unit="min")
    b["actual_at"] = pd.NaT
    b["actual_at"] = pd.to_datetime(b["actual_at"], utc=True)
    pd.concat([b, pers]).to_parquet(bench / "predictions.parquet")
    grid = pd.date_range("2024-01-11", "2026-01-01", freq="15min")
    marks = pd.date_range("2025-02-01", "2025-12-31", freq="6h")
    fm_rows, ridge_rows = [], []
    for st in t4.CDMO_STATIONS:
        temp = 22 + 1.5 * np.sin(np.arange(len(grid)) * 2 * np.pi / 96) + rng.normal(0, 0.2, len(grid))
        pd.DataFrame({"time_lst": grid, "Temp": temp}).to_parquet(t3 / "data-cdmo" / f"{st}.parquet")
        for h in t4.HORIZONS:
            y = 22 + rng.normal(0, 0.5, len(marks))
            q50 = y + rng.normal(0, 0.3, len(marks))
            fm_rows.append(pd.DataFrame({"station": st, "issued_at": marks, "horizon_minutes": h, "q10": q50 - 0.4, "q50": q50, "q90": q50 + 0.4}))
            ridge_rows.append(pd.DataFrame({"station": st, "issued_at": marks, "horizon_minutes": h, "actual": y,
                                            "ridge-B5D-fc": y + rng.normal(0, 0.3, len(marks)), "ridge-B4D-n": y + rng.normal(0, 0.3, len(marks))}))
    pd.concat(fm_rows).to_parquet(t3 / "fm-cdmo-chronos-2-small-none.parquet")
    pd.concat(ridge_rows).to_parquet(t3 / "ridge-cdmo.parquet")
    return exp


def test_evaluate_end_to_end_on_synthetic_artifacts(tmp_path, monkeypatch):
    exp = _fake_artifacts(tmp_path)
    monkeypatch.setattr(t4.paths, "EXPERIMENT_OUTPUT_DIR", exp)
    run = t4.run_dir()
    run.mkdir()
    (run / "preregistration.json").write_text(json.dumps({"source_sha256": t4._sha256(t4.PREREG_FILE)}), encoding="utf-8")
    t4.stage_evaluate(None)
    verdict = json.loads((run / "verdict.json").read_text(encoding="utf-8"))
    assert verdict["nb1"] in ("fail", "not_fully_testable_large_only_pass")
    assert verdict["nb1_small_regime_rows"] == 0
    assert len(pd.read_csv(run / "h3_cells_nb1.csv")) == 6
    assert len(pd.read_csv(run / "h3_cells_cdmo.csv")) == 36
    intervals = pd.read_parquet(run / "intervals-cdmo.parquet")
    assert intervals["issued_at"].min() >= t4.CDMO_EVAL_START
    with pytest.raises((FileExistsError, ValueError)):
        t4.stage_evaluate(None)  # write-once
