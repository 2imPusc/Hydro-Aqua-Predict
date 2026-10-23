"""Unit tests for the NERRS direction-4 reliability pilot (metrics, no look-ahead)."""
import numpy as np
import pandas as pd
import pytest

from experiments.nerrs_reliability import (
    bootstrap_share,
    bootstrap_share_difference,
    gate_status,
    prepare_output_dir,
    prior_window_sum,
    rolling_linear_transfer,
    season_of,
    solar_elevation_deg,
    within_tolerance,
)


def test_within_tolerance_absolute_and_relative_turbidity():
    est = np.array([20.0, 20.0, 1.0])
    obs = np.array([20.4, 21.0, 1.5])
    assert within_tolerance("Temp", est, obs).tolist() == [True, False, True]
    # Turb: max(2 NTU, 20 % of target)
    assert within_tolerance("Turb", np.array([10.0, 10.0, 30.0]), np.array([12.0, 13.0, 37.0])).tolist() == [True, False, True]
    assert within_tolerance("pH@0.1", np.array([8.0]), np.array([8.15])).tolist() == [False]


def test_rolling_linear_transfer_uses_only_strictly_past_30_days():
    idx = pd.date_range("2008-01-01", periods=24 * 60, freq="h")
    anchor = pd.Series(np.sin(np.arange(len(idx)) / 7.0) + 10, index=idx)
    target = 2 * anchor + 1
    # A shock on the last hour must not influence that hour's own estimate.
    target_shocked = target.copy()
    target_shocked.iloc[-1] = 1000.0
    est = rolling_linear_transfer(anchor, target, min_hours=240)
    est_shocked = rolling_linear_transfer(anchor, target_shocked, min_hours=240)
    assert est.iloc[-1] == pytest.approx(est_shocked.iloc[-1])
    assert est.iloc[-1] == pytest.approx(target.iloc[-1], rel=1e-6)
    # Not enough history in the first 10 days -> no estimate.
    assert est.iloc[: 240].isna().all()
    # A shock long ago (> 30 days before the last hour) is outside the window.
    old = target.copy()
    old.iloc[0] = 1000.0
    assert rolling_linear_transfer(anchor, old, min_hours=240).iloc[-1] == pytest.approx(est.iloc[-1])


def test_prior_window_sum_excludes_current_hour_and_needs_coverage():
    idx = pd.date_range("2008-01-01", periods=10, freq="h")
    rain = pd.Series([0, 0, 0, 0, 0, 0, 5.0, 0, 0, 0], index=idx)
    out = prior_window_sum(rain, hours=3, min_coverage=1.0)
    assert out.iloc[6] == 0.0      # rain in hour 6 is not "previous" for hour 6
    assert out.iloc[7] == 5.0
    assert out.iloc[9] == 5.0
    assert np.isnan(out.iloc[10 - 10 + 2])  # only 2 prior hours exist at index 2
    gappy = rain.drop(idx[5])
    assert np.isnan(prior_window_sum(gappy, hours=3, min_coverage=1.0).loc[idx[7]])


def test_season_and_solar_elevation():
    assert season_of(pd.DatetimeIndex(["2008-05-01", "2008-11-30", "2008-12-01", "2008-04-30"])).tolist() == [
        "wet", "wet", "dry", "dry"]
    noon = solar_elevation_deg(pd.DatetimeIndex(["2008-06-21 12:30"]), 17.94, -66.24, utc_offset_h=-4)[0]
    midnight = solar_elevation_deg(pd.DatetimeIndex(["2008-06-21 00:30"]), 17.94, -66.24, utc_offset_h=-4)[0]
    assert noon > 80 and midnight < -40


def test_bootstrap_share_is_day_blocked_and_brackets_point():
    within = np.array([24] * 50 + [0] * 50)
    total = np.full(100, 24)
    share, lo, hi = bootstrap_share(within, total, n_boot=400, seed=1)
    assert share == pytest.approx(0.5)
    # 100 independent days, p=0.5 -> CI width ~ +/-0.1 (not the +/-0.013 of 2400 iid hours)
    assert 0.35 < lo < 0.45 and 0.55 < hi < 0.65


def test_bootstrap_share_difference_sign():
    w_a, n_a = np.array([2, 2, 2, 2] * 20), np.array([10, 10, 10, 10] * 20)
    w_b, n_b = np.array([9, 9, 9, 9] * 20), np.array([10, 10, 10, 10] * 20)
    diff, lo, hi = bootstrap_share_difference(w_a, n_a, w_b, n_b, n_boot=300, seed=2)
    assert diff == pytest.approx(-0.7)
    assert hi < 0


def test_gate_status():
    assert gate_status(lower=0.91, n_days=60, target=0.90, min_days=30) == "pass"
    assert gate_status(lower=0.85, n_days=60, target=0.90, min_days=30) == "fail"
    assert gate_status(lower=0.99, n_days=10, target=0.90, min_days=30) == "insufficient"


def test_prepare_output_dir_refuses_overwrite(tmp_path):
    out = tmp_path / "run"
    prepare_output_dir(out)
    assert out.is_dir()
    with pytest.raises(FileExistsError):
        prepare_output_dir(out)
