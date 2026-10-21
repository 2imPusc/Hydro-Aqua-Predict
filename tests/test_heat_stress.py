import numpy as np
import pandas as pd
import pytest

from core.heat_stress import daily_from_hourly, daily_heat_stress, evaluate_heat_advisory, hot_calm_flag


def _days(values):
    return pd.Series(values, index=pd.date_range("2026-07-01", periods=len(values), freq="D"), dtype=float)


def test_levels_runs_and_alert():
    out = daily_heat_stress(_days([30, 31, 31, 31, 33, 34, 29]))
    assert list(out["level"]) == [0, 1, 1, 1, 2, 3, 0]
    assert list(out["run_days"]) == [0, 1, 2, 3, 4, 5, 0]
    assert list(out["alert_level"]) == [0, 1, 1, 1, 2, 3, 0]
    assert list(out["degree_days_7d"]) == [0, 0, 0, 0, 2, 5, 5]


def test_short_spike_is_capped_at_watch():
    out = daily_heat_stress(_days([30, 34, 30]))
    assert list(out["level"]) == [0, 3, 0]
    assert list(out["alert_level"]) == [0, 1, 0]


def test_missing_day_breaks_run():
    out = daily_heat_stress(_days([31, np.nan, 31, 31]))
    assert np.isnan(out["level"].iloc[1])
    assert np.isnan(out["alert_level"].iloc[1])
    assert list(out["run_days"]) == [1, 0, 1, 2]


def test_hot_calm_flag():
    flag = hot_calm_flag(pd.Series([36.0, 36.0, 30.0, np.nan]), pd.Series([2.0, 4.0, 1.0, 1.0]))
    assert list(flag) == [True, False, False, False]


def test_daily_from_hourly_requires_coverage():
    idx = pd.date_range("2026-07-01T00:00", periods=30, freq="h", tz="Asia/Ho_Chi_Minh").tz_convert("UTC")
    daily = daily_from_hourly(pd.Series(30.0, index=idx), min_hours=18)
    assert list(daily.round(1)) == [30.0]      # 2026-07-02 has 6 h only -> dropped


def test_daily_from_hourly_does_not_mutate_input():
    idx = pd.date_range("2026-07-01T00:00", periods=24, freq="h", tz="UTC")
    s = pd.Series(30.0, index=idx)
    daily_from_hourly(s)
    assert str(s.index.tz) == "UTC"


def test_heat_advisory_from_marine_forecast():
    times = pd.date_range("2026-07-02T00:00", periods=72, freq="h").strftime("%Y-%m-%dT%H:%M").tolist()
    marine = {"status": "ready", "timezone": "Asia/Ho_Chi_Minh",
              "hourly": {"time": times, "sea_surface_temperature": [33.5] * 72}}
    out = evaluate_heat_advisory(marine, now=pd.Timestamp("2026-07-01T17:00Z"))
    assert out["max_level"] == 2 and out["max_alert_level"] == 2
    assert out["source"] == "forecast" and out["used_by_alerts"] is False
    assert out["notification_eligible"] is False and out["basis"] == "theory_only_unvalidated"
    assert evaluate_heat_advisory({"status": "disabled"})["status"] == "unavailable"


def test_heat_advisory_naive_now_and_all_missing():
    times = pd.date_range("2026-07-02T00:00", periods=24, freq="h").strftime("%Y-%m-%dT%H:%M").tolist()
    marine = {"status": "ready", "hourly": {"time": times, "sea_surface_temperature": [None] * 24}}
    out = evaluate_heat_advisory(marine, now=pd.Timestamp("2026-07-01T17:00"))
    assert out["status"] == "unavailable"
