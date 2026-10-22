import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
import disease_hindcast as dh  # noqa: E402
from core import disease_risk as dr  # noqa: E402


def _temps(start, end, value=26.0):
    idx = pd.date_range(start, end, freq="D")
    return pd.Series(value, index=idx, dtype=float)


def test_same_window_handles_leap_day_and_year_crossing():
    s, e = dh._same_window(pd.Timestamp("2007-12-18"), pd.Timestamp("2008-02-29"), 2010)
    assert s == pd.Timestamp("2009-12-18") and e == pd.Timestamp("2010-02-28")


def test_yearly_drops_incomplete_years_and_counts_levels():
    temp = _temps("2020-01-01", "2021-02-01", 26.0)
    temp["2020-01-01":"2020-01-20"] = 14.0
    days = dr.daily_disease_risk(temp)
    table = dh.yearly(days)
    assert list(table.index) == [2020]
    row = table.loc[2020]
    assert row["days_level2"] == 366 - 20 + 7  # 20 cold days: first 13 capped (level 1), last 7 full cold (level 2)
    assert row["days_cold_high"] == 7 and row["max_cold_run_days"] == 20


def test_evaluate_excludes_non_environmental_and_flags_insufficient():
    temp = _temps("2016-01-01", "2019-12-31", 26.0)
    days = dr.daily_disease_risk(temp)
    events = pd.DataFrame({"event_id": ["a", "phulong-2026"], "start_date": ["2018-07-10", "2018-07-10"],
                           "end_date": ["2018-07-12", "2018-07-12"]})
    table, summary = dh.evaluate(days, events, [2016, 2017, 2018, 2019])
    assert summary["n_events_listed"] == 2 and summary["n_scored"] == 1
    assert summary["verdict"] == "insufficient_evidence"
    row = table.set_index("event_id").loc["a"]
    assert row["window_start"] == "2018-06-26" and row["any_level2"]
    assert row["clim_p_any_level2"] == 1.0 and row["pre_n_valid_days"] == 14


def test_week_calendar_shares():
    temp = _temps("2020-01-06", "2020-01-19", 26.0)
    temp["2020-01-13":] = np.nan
    cal = dh.week_calendar(dr.daily_disease_risk(temp))
    assert list(cal.index) == [2] and cal.loc[2, "share_days_level2"] == 1.0
