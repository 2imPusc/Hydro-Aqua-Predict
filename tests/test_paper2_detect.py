"""Causal detectors and scoring of experiments/paper2_detect.py (paper 2, F2)."""
import numpy as np
import pandas as pd
import pytest

from experiments.paper2_detect import (
    ALARM_DETECTORS,
    DAY,
    THETA_GRID,
    calibrate_thresholds,
    changepoints_of,
    detect,
    drift_score,
    episodes,
    fault_specs,
    flags_of,
    gap_flag,
    range_flag,
    score_injection,
    step_score,
    stuck_run,
)
from experiments.paper2_faults import inject_event

PARAMS = {v: {"theta_step": 8.0, "theta_drift": 8.0, "stuck_k": 8} for v in ("DO_mgl", "Turb", "pH", "Temp")}


def _frame(days=60, seed=0, start="2009-03-01"):
    idx = pd.date_range(start, periods=days * DAY, freq="15min")
    rng = np.random.default_rng(seed)
    t = np.arange(len(idx))
    diel = np.sin(2 * np.pi * t / DAY)
    return pd.DataFrame({
        "DO_mgl": 6.5 + 0.8 * diel + rng.normal(0, 0.08, len(idx)),
        "Turb": np.exp(np.log(8) + 0.2 * diel + rng.normal(0, 0.1, len(idx))),
        "pH": np.round(7.9 + 0.05 * diel + rng.normal(0, 0.03, len(idx)), 2),
        "Temp": 24 + 1.0 * diel + rng.normal(0, 0.05, len(idx)),
    }, index=idx)


def test_detectors_are_causal_truncation_invariant():
    f = _frame()
    f.iloc[40 * DAY:, 0] *= 0.05
    full = detect(f, PARAMS)
    cut = f.index[42 * DAY]
    part = detect(f[:cut], PARAMS)
    for d in ALARM_DETECTORS + ("gap",):
        pd.testing.assert_frame_equal(full[d][:cut], part[d], check_freq=False)
    s_full, s_part = step_score(f["DO_mgl"], "DO_mgl"), step_score(f["DO_mgl"][:cut], "DO_mgl")
    pd.testing.assert_series_equal(s_full[:cut], s_part, check_freq=False)
    pd.testing.assert_series_equal(drift_score(f["Turb"], "Turb")[:cut], drift_score(f["Turb"][:cut], "Turb"),
                                   check_freq=False)


def test_step_score_fires_after_w_samples_on_a_scale_step_and_is_quiet_before():
    f = _frame()
    onset = f.index[40 * DAY]
    x, _ = inject_event(f, fault_specs("scale_down", f, onset), onset)
    s = step_score(x["DO_mgl"], "DO_mgl")
    assert s[:onset - pd.Timedelta(minutes=15)].iloc[8 * DAY:].max() < 8
    first = s[s > 8].index[0]
    assert onset <= first <= onset + pd.Timedelta(hours=1)


def test_stuck_run_gap_flag_range_flag():
    idx = pd.date_range("2009-01-01", periods=20, freq="15min")
    x = pd.Series([1, 1, 1, 2, np.nan, 2, 2, 2, 2, 3] + [np.nan] * 9 + [4.0], index=idx)
    assert stuck_run(x).tolist()[:10] == [1, 2, 3, 1, 0, 1, 2, 3, 4, 1]
    g = gap_flag(x, 8)
    assert g.sum() == 2 and g.iloc[17] and g.iloc[18] and not g.iloc[16]
    t = pd.Series([5.0, 1000.0, -1.0, np.nan], index=idx[:4])
    assert range_flag(t, "Turb").tolist() == [False, True, True, False]


def test_episodes_merge_within_6h():
    idx = pd.date_range("2009-01-01", periods=200, freq="15min")
    a = pd.Series(False, index=idx)
    a.iloc[[10, 11, 20, 60, 61]] = True     # 20 is 9 samples after 11 -> merged; 60 is 40 after -> new
    assert episodes(a) == [idx[10], idx[60]]


def test_calibration_picks_smallest_threshold_meeting_target():
    series = [_frame(90, seed=s)["DO_mgl"] for s in range(3)]
    cal = calibrate_thresholds(series, "DO_mgl")
    curve = dict(cal["theta_step_curve"])
    assert curve[cal["theta_step"]] <= 1.0
    below = [th for th in THETA_GRID if th < cal["theta_step"]]
    assert not below or curve[below[-1]] > 1.0
    assert cal["stuck_k"] is not None


@pytest.mark.parametrize("kind,detector", [("scale_down", "step"), ("scale_up", "step"), ("stuck0", "stuck"),
                                           ("ph_ramp", "drift"), ("fouling", "drift"), ("rail", "range"),
                                           ("gap", "gap"), ("E3", "cross")])
def test_score_injection_detects_synthetic_faults(kind, detector):
    f = _frame(70)
    onset = f.index[50 * DAY + 37]
    row = score_injection(f, kind, onset, PARAMS)
    assert row["detected"], row
    assert row[f"det_{detector}"], row
    assert row["n_faulted"] > 0 and 0 <= row["mask_recall"] <= row["cover_with_cp"] <= 1


def test_mask_vs_changepoint_coverage_for_scale_step():
    f = _frame(70)
    onset = f.index[50 * DAY]
    row = score_injection(f, "scale_down", onset, PARAMS)
    # single samples after the step look normal: only the 24 h drift rule masks them, and only later
    assert row["mask_recall"] < 0.8
    assert row["cover_with_cp"] > 0.95 > row["mask_recall"]


def test_flags_and_changepoints_shapes():
    f = _frame(20)
    det = detect(f, PARAMS)
    assert flags_of(det).shape == f.shape == changepoints_of(det).shape
