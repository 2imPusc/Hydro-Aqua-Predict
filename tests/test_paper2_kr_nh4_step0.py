"""Coverage / stuck logic of experiments/paper2_kr_nh4_step0.py (F5 step 0)."""
import numpy as np
import pandas as pd

from experiments.paper2_kr_nh4_step0 import best_window, fault_stats, hourly_series, segments, stuck_mask, valid_hours


def _hours(n, start="2020-01-01"):
    return pd.date_range(start, periods=n, freq="h")


def _noisy(n, seed=0):
    return pd.Series(np.random.default_rng(seed).uniform(10, 500, n), index=_hours(n))


def test_hourly_median_drops_negative_and_nan():
    t = pd.Series(pd.to_datetime(["2020-01-01 00:00", "2020-01-01 00:05", "2020-01-01 00:10", "2020-01-01 02:00"]))
    v = pd.Series(["5", "-1", "nan", "7"])
    h = hourly_series(t, v)
    assert list(h.index) == list(_hours(3))
    assert h.iloc[0] == 5 and np.isnan(h.iloc[1]) and h.iloc[2] == 7


def test_stuck_needs_six_consecutive_present_hours():
    x = _noisy(20)
    x.iloc[2:8] = 3.0  # 6 h identical -> stuck
    x.iloc[10:15] = 4.0  # 5 h -> not stuck
    x.iloc[16:22] = 9.0
    x.iloc[18] = np.nan  # broken by a missing hour -> 2 + 3, not stuck
    m = stuck_mask(x)
    assert m.iloc[2:8].all() and not m.iloc[10:15].any() and not m.iloc[16:22].any()
    assert valid_hours(x).sum() == 20 - 6 - 1


def test_full_year_passes():
    v = valid_hours(_noisy(366 * 24))
    bw = best_window(v)
    assert bw["pass"] and bw["valid_fraction"] == 1.0 and bw["max_gap_days"] == 0


def test_gap_over_30_days_fails_even_with_high_fraction():
    x = _noisy(800 * 24)
    x.iloc[200 * 24:200 * 24 + 31 * 24] = np.nan  # 31-d hole
    y = x.iloc[:390 * 24]  # every 365-d window of a 390-d series contains the hole; the 800-d one has windows after it
    bw = best_window(valid_hours(y))
    assert bw["valid_fraction"] > 0.9 and bw["max_gap_days"] > 30 and not bw["pass"]
    assert best_window(valid_hours(x))["pass"]


def test_fraction_below_70_fails_and_edge_hole_counts():
    x = _noisy(366 * 24)
    mask = np.random.default_rng(1).uniform(size=len(x)) < 0.35  # ~65 % present, short gaps
    x[mask] = np.nan
    bw = best_window(valid_hours(x))
    assert not bw["pass"] and 0.6 < bw["valid_fraction"] < 0.7
    short = _noisy(300 * 24)  # series shorter than the window: no window at all
    assert not best_window(valid_hours(short))["pass"]


def test_segments_split_at_gap():
    x = _noisy(100 * 24)
    x.iloc[40 * 24:72 * 24] = np.nan  # 32-d gap
    segs = segments(valid_hours(x))
    assert len(segs) == 2 and segs[0]["valid_fraction"] == 1.0


def test_fault_stats_jumps_and_ceiling():
    x = pd.Series(np.full(200, 100.0) + np.arange(200) * 0.01, index=_hours(200))
    x.iloc[100:] *= 5  # persistent x5 shift
    x.iloc[150] = x.max() + 1
    s = fault_stats(x)
    assert s["persistent_shift_x3"] == 1 and s["jump_x3_pairs"] >= 1 and s["ceiling_hours"] == 1
