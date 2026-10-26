"""Helpers of experiments/nh4_step_0731.py (31/07 NH4 / TSS step study)."""
import numpy as np
import pandas as pd
import pytest

from experiments.nh4_step_0731 import (
    cycle_profile,
    detect_level_step,
    event_scan,
    relative_spread,
    step_factor,
    upward_jumps,
)


def _minutes(n, start="2026-07-31 12:00"):
    return pd.date_range(start, periods=n, freq="1min")


def test_detect_level_step_finds_multiplicative_step_with_noise():
    rng = np.random.default_rng(0)
    idx = _minutes(240)
    level = np.where(np.arange(240) < 126, 106.0, 5.3)
    s = pd.Series(level * np.exp(rng.normal(0, 0.006, 240)), index=idx)
    st = detect_level_step(s, half_window=10, log=True)
    assert st["first_new_sample"] == idx[126]
    assert st["last_old_sample"] == idx[125]
    assert st["ratio_before_over_after"] == pytest.approx(20.0, rel=0.02)


def test_detect_level_step_linear_and_short_series():
    idx = _minutes(60)
    s = pd.Series(np.r_[np.zeros(30), np.full(30, 22.0)], index=idx)
    st = detect_level_step(s, half_window=5, log=False)
    assert st["first_new_sample"] == idx[30]
    assert st["difference_after_minus_before"] == pytest.approx(22.0)
    with pytest.raises(ValueError):
        detect_level_step(s.iloc[:8], half_window=5)


def test_step_factor_and_relative_spread_are_scale_free():
    a = pd.Series([100.0, 110.0, 90.0, 105.0])
    b = a / 20.0
    assert step_factor(a, b) == pytest.approx(20.0)
    assert relative_spread(a) == pytest.approx(relative_spread(b))
    assert step_factor(pd.Series([10.0, 0.0, 10.0]), pd.Series([1.0, -1.0, 1.0])) == pytest.approx(10.0)


def test_cycle_profile_flags_the_30_min_bump_and_skips_gaps():
    idx = _minutes(24 * 60, "2026-07-30 00:00")
    values = np.full(len(idx), 7.95)
    bump = (idx.minute % 30) == 14
    values[bump] += 0.05          # rises at :14 / :44, falls back the next minute
    s = pd.Series(values, index=idx)
    prof = cycle_profile(s)
    top = prof.sort_values("abs_change_vs_mean", ascending=False)["cycle_minute"].iloc[:2].tolist()
    assert sorted(top) == [14, 15]
    assert prof.loc[prof.cycle_minute == 14, "mean_change"].iloc[0] == pytest.approx(0.05)
    # a 10-minute hole must not create a spurious change at the minute after it
    gappy = s.drop(s.index[100:110])
    assert cycle_profile(gappy)["n"].sum() == len(gappy) - 2


def test_upward_jumps():
    idx = _minutes(6)
    s = pd.Series([7.95, 7.95, 8.00, 7.99, 7.96, 7.99], index=idx)
    assert upward_jumps(s, 0.02) == [idx[2], idx[5]]


def test_event_scan_reports_nh4_ratio_cod_state_and_gaps():
    days = []
    for day, nh4, cod in (("2026-07-30", 100.0, 558.8), ("2026-07-31", 5.0, 558.8), ("2026-08-01", 5.0, 0.0)):
        idx = pd.date_range(day, periods=1440, freq="1min")
        if day == "2026-08-01":
            idx = idx.delete(slice(600, 700))
        days.append(pd.DataFrame({"NH4": nh4, "COD": cod}, index=idx))
    ev = event_scan(pd.concat(days)).set_index("local_date")
    assert "NH4 x0.05" in ev.loc["2026-07-31", "reasons"]
    assert "COD rail->zero" in ev.loc["2026-08-01", "reasons"]
    assert "gap 101 min" in ev.loc["2026-08-01", "reasons"]
