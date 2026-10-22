import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
import stocking_calendar as sc  # noqa: E402


def test_iso_week_start_is_monday():
    d = sc.iso_week_start(2024, 1)
    assert d == pd.Timestamp("2024-01-01") and d.weekday() == 0
    assert sc.iso_week_start(2021, 52) == pd.Timestamp("2021-12-27")


def test_window_counts_complete_and_incomplete():
    idx = pd.date_range("2020-01-01", "2020-03-31", freq="D")
    sst = pd.Series(20.0, index=idx)
    sst["2020-01-03":"2020-01-05"] = 32.0
    out = sc.window_sst_counts(sst, pd.Timestamp("2020-01-01"), 10, (31.0, 33.0), (20.0, 18.0), (25.0, 30.0))
    assert out["heat_ge1"] == 3 and out["heat_ge2"] == 0 and out["cold_ge1"] == 0 and out["cold_ge2"] == 0
    assert out["suitable"] == 0
    assert sc.window_sst_counts(sst, pd.Timestamp("2020-03-25"), 10, (31, 33), (20, 18), (25, 30)) is None
    with_nan = sst.copy()
    with_nan["2020-01-02"] = np.nan
    assert sc.window_sst_counts(with_nan, pd.Timestamp("2020-01-01"), 10, (31, 33), (20, 18), (25, 30)) is None


def test_cold_is_strictly_below():
    sst = pd.Series([17.9, 18.0, 19.9, 20.0], index=pd.date_range("2020-01-01", periods=4))
    out = sc.window_sst_counts(sst, sst.index[0], 4, (31, 33), (20, 18), (25, 30))
    assert out["cold_ge1"] == 3 and out["cold_ge2"] == 1


def test_suitable_band_inclusive():
    sst = pd.Series([24.9, 25.0, 30.0, 30.1], index=pd.date_range("2020-06-01", periods=4))
    out = sc.window_sst_counts(sst, sst.index[0], 4, (31, 33), (20, 18), (25, 30))
    assert out["suitable"] == 2


def test_storm_counts_by_threshold():
    dates = pd.DatetimeIndex(["2020-07-02", "2020-07-05", "2020-08-01"])
    beau = np.array([8, 6, 9])
    s = pd.Timestamp("2020-07-01")
    assert sc.window_storm_counts(dates, beau, s, 7, 8) == 1
    assert sc.window_storm_counts(dates, beau, s, 7, 6) == 2
    assert sc.window_storm_counts(dates, beau, pd.Timestamp("2020-07-08"), 7, 6) == 0


def test_minmax_constant_is_zero():
    assert list(sc.minmax(pd.Series([2.0, 2.0, 2.0]))) == [0, 0, 0]
    assert list(sc.minmax(pd.Series([1.0, 2.0, 3.0]))) == [0, 0.5, 1.0]


def test_composite_score_range_and_direction():
    risks = pd.DataFrame({"heat": [0, 1.0], "cold": [0, 1.0], "storm": [0, 1.0], "early": [0, 1.0], "growth": [0, 1.0]})
    w = {"heat": 0.2, "cold": 0.2, "storm": 0.25, "early": 0.2, "growth": 0.15}
    s = sc.composite_score(risks, w)
    assert s.iloc[0] == pytest.approx(1.0) and s.iloc[1] == pytest.approx(0.0)
    with pytest.raises(ValueError):
        sc.composite_score(risks, {**w, "heat": 0.9})


def test_top_k_and_top_share():
    scores = [pd.Series([0.9, 0.8, 0.1], index=[1, 2, 3]), pd.Series([0.9, 0.2, 0.8], index=[1, 2, 3])]
    assert sc.top_k(scores[0], 2) == [1, 2]
    share = sc.top_share(scores, 1)
    assert share[1] == 1.0 and share[2] == 0.0


def test_month_of_week_and_weight_sets_sum_to_one():
    assert sc.month_of_week(1) == 1 and sc.month_of_week(27) == 7 and sc.month_of_week(52) == 12
    for w in sc.WEIGHT_SETS.values():
        assert sum(w.values()) == pytest.approx(1.0)
