import pytest
from datetime import datetime, timezone
from core.weather_advisory import evaluate_weather_advisory

def test_weather_advisory_is_context_only_and_summarizes_windows():
    weather = {
        "status": "ready", "provider": "open_meteo", "timezone": "UTC",
        "hourly_units": {"wind_speed_10m": "km/h"},
        "hourly": {
            "time": ["2026-09-05T00:00", "2026-09-05T01:00", "2026-09-05T02:00", "2026-09-05T03:00", "2026-09-05T04:00", "2026-09-05T05:00"],
            "precipitation": [5, 6, 0, 0, 0, 0], "wind_speed_10m": [20, 36, 18, 10, 10, 10],
            "wind_direction_10m": [90, 100, 110, 120, 120, 120],
        },
    }
    result = evaluate_weather_advisory(weather, now=datetime(2026, 9, 5, tzinfo=timezone.utc))
    assert result["severity"] == "WATCH"
    assert result["windows"]["next_3h"]["status"] == "complete"
    assert result["windows"]["next_6h"]["status"] == "complete"
    assert result["windows"]["next_6h"]["rain_sum_mm"] == 11.0
    assert result["windows"]["next_6h"]["max_wind"] == 36.0
    assert result["windows"]["next_12h"]["status"] == "partial"
    assert not result["used_by_models"]

def test_missing_weather_or_past_hours_handled():
    assert evaluate_weather_advisory(None)["status"] == "unavailable"
    assert evaluate_weather_advisory({})["status"] == "unavailable"
    weather = {"status": "ready", "hourly": {"time": ["2026-09-01T00:00"], "precipitation": [0]}}
    assert evaluate_weather_advisory(weather, now=datetime(2026, 9, 5, tzinfo=timezone.utc))["status"] == "unavailable"

def test_missing_hours_unavailable():
    weather = {
        "status": "ready", "provider": "open_meteo", "timezone": "UTC",
        "hourly_units": {"wind_speed_10m": "km/h"},
        "hourly": {
            "time": ["2026-09-05T00:00", "2026-09-05T02:00", "2026-09-05T03:00", "2026-09-05T04:00", "2026-09-05T05:00"],
            "precipitation": [5, 0, 0, 0, 0], "wind_speed_10m": [20, 18, 10, 10, 10],
        },
    }
    result = evaluate_weather_advisory(weather, now=datetime(2026, 9, 5, tzinfo=timezone.utc))
    # Missing 01:00 => 3h and 6h windows are partial
    assert result["windows"]["next_3h"]["status"] == "partial"
    assert result["windows"]["next_6h"]["status"] == "partial"
    assert result["severity"] == "UNAVAILABLE"

def test_stale_weather_stays_stale():
    weather = {
        "status": "stale", "provider": "open_meteo", "timezone": "UTC",
        "hourly": {
            "time": ["2026-09-05T00:00", "2026-09-05T01:00", "2026-09-05T02:00", "2026-09-05T03:00", "2026-09-05T04:00", "2026-09-05T05:00"],
            "precipitation": [5, 6, 0, 0, 0, 0], "wind_speed_10m": [20, 36, 18, 10, 10, 10],
        },
    }
    result = evaluate_weather_advisory(weather, now=datetime(2026, 9, 5, tzinfo=timezone.utc))
    assert result["status"] == "stale"
