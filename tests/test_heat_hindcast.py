import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
import heat_hindcast as hh  # noqa: E402
from core import heat_stress as hs  # noqa: E402


def test_compare_median_and_insufficient():
    idx = pd.date_range("2026-06-01", periods=20, freq="D")
    product = pd.Series(28.0, index=idx)
    out = hh.compare(product + 1.5, product)
    assert out["n_days"] == 20 and out["median_diff_c"] == 1.5 and out["mae_c"] == 1.5
    assert hh.compare(product.iloc[:5], product)["status"] == "insufficient_overlap"


def test_yearly_drops_incomplete_and_counts_levels():
    idx = pd.date_range("2020-01-01", "2021-03-31", freq="D")
    temp = pd.Series(25.0, index=idx)
    temp["2020-07-01":"2020-07-05"] = 33.5
    days = hs.daily_heat_stress(temp)
    hot_calm = pd.Series(False, index=idx)
    hot_calm["2020-07-02"] = True
    table = hh.yearly(days, hot_calm)
    assert list(table.index) == [2020]  # 2021 has only 90 days
    row = table.loc[2020]
    assert row["days_alert_ge1"] == 5 and row["days_alert_ge2"] == 3 and row["days_alert_ge3"] == 0
    assert row["hot_calm_days"] == 1 and row["max_run_days"] == 5


def test_yearly_nan_gap_days_do_not_count_as_valid():
    idx = pd.date_range("2020-01-01", "2020-12-31", freq="D")
    temp = pd.Series(25.0, index=idx)
    temp.iloc[10:60] = np.nan  # 50 missing days -> 316 valid < 330
    table = hh.yearly(hs.daily_heat_stress(temp), pd.Series(False, index=idx))
    assert table.empty


def test_trend_detects_increase():
    table = pd.DataFrame({"x": np.arange(0, 20, 2)}, index=range(2000, 2010))
    out = hh.trend(table, "x")
    assert out["days_per_decade"] == 20.0 and out["years"] == [2000, 2009]


def test_calendar_share_by_iso_week():
    idx = pd.date_range("2019-01-01", "2020-12-31", freq="D")
    temp = pd.Series(25.0, index=idx)
    temp["2019-07-01":"2019-07-05"] = 33.5  # ISO week 27 of 2019 only
    cal = hh.calendar(hs.daily_heat_stress(temp))
    assert cal.loc[27, "share_years_with_stress_day"] == 0.5
    assert cal["share_years_with_stress_day"].drop(27).max() == 0.0
