from datetime import date

import numpy as np
import pandas as pd
import pytest

from experiments import storm_leadtime as sl


def _hours(n, start="2024-09-05"):
    return pd.date_range(start, periods=n, freq="h", tz="UTC")


def test_chunk_ranges_cover_without_overlap():
    ch = sl.chunk_ranges(date(2024, 1, 1), date(2024, 3, 10), days=30)
    assert ch[0][0] == date(2024, 1, 1) and ch[-1][1] == date(2024, 3, 10)
    for (_, b), (a, _) in zip(ch, ch[1:]):
        assert (a - b).days == 1


def test_api_name_and_variables():
    assert sl.api_name("wind", 0) == "wind_speed_10m"
    assert sl.api_name("gust", 3) == "wind_gusts_10m_previous_day3"
    assert len(sl.hourly_variables()) == 16


def test_parse_previous_runs_handles_nulls_and_missing_keys():
    payload = {"hourly": {"time": ["2024-01-01T00:00", "2024-01-01T01:00"],
                          "wind_speed_10m": [3.0, 4.0],
                          "wind_speed_10m_previous_day1": [None, 5.0]}}
    df = sl.parse_previous_runs(payload)
    assert str(df["time"].dt.tz) == "UTC"
    assert np.isnan(df.loc[0, "wind_d1"]) and df.loc[1, "wind_d1"] == 5.0
    assert df["gust_d7"].isna().all()


def test_first_exceed_uses_beaufort_lower_bound():
    s = pd.Series([5.0, 10.7, 10.8, 20.0], index=_hours(4))
    assert sl.first_exceed(s, 6) == s.index[2]
    assert sl.first_exceed(s, 10) is None


def test_earliest_warning_longest_lead_and_hours():
    idx = _hours(48)
    fc = pd.DataFrame({sl.wind_col(n): 3.0 for n in range(8)}, index=idx)
    fc.loc[idx[30], sl.wind_col(2)] = 12.0  # lead 2 sees it at t=30 h
    fc.loc[idx[34], sl.wind_col(5)] = 12.0  # lead 5 sees it at t=34 h
    truth = idx[36]
    w = sl.earliest_warning(fc, 6, truth)
    assert w["earliest_N"] == 5
    assert w["hits"][2] and w["hits"][5] and not w["hits"][3]
    assert w["lead_hours"] == pytest.approx(24 * 5 + 2)  # forecast hit 2 h before truth
    assert sl.earliest_warning(fc, 8, truth)["earliest_N"] is None
    assert sl.earliest_warning(fc, 6, None)["lead_hours"] is None


def test_contingency_scores():
    fc = np.array([1, 1, 1, 0, 0, 0, 0, 0], bool)
    ob = np.array([1, 1, 0, 1, 0, 0, 0, 0], bool)
    c = sl.contingency(fc, ob)
    assert (c["hits"], c["misses"], c["false_alarms"], c["correct_negatives"]) == (2, 1, 1, 4)
    assert c["POD"] == pytest.approx(2 / 3)
    assert c["FAR"] == pytest.approx(1 / 3)
    assert c["CSI"] == pytest.approx(2 / 4)
    assert c["freq_bias"] == pytest.approx(1.0)
    assert np.isnan(sl.contingency(np.zeros(3, bool), np.zeros(3, bool))["POD"])


def test_daily_max_drops_incomplete_days():
    s = pd.Series(np.arange(30, dtype=float), index=_hours(30))
    out = sl.daily_max(s)
    assert out.iloc[0] == 23.0 and np.isnan(out.iloc[1])
    assert sl.daily_max(s, min_hours=1).notna().sum() == 2


def test_error_by_lead_bias():
    idx = _hours(10)
    j = pd.DataFrame({"obs": 5.0}, index=idx)
    for n in sl.LEADS:
        j[sl.wind_col(n)] = 4.0
    out = sl.error_by_lead(j, "obs", sl.wind_col)
    assert out["bias"].iloc[1] == pytest.approx(-1.0) and out["MAE"].iloc[1] == pytest.approx(1.0)
