import pandas as pd

from core.realtime_guards import assess_sensor_freshness


def test_freshness_blocks_old_cache_data():
    raw = pd.DataFrame({"fetchedAt": ["2026-08-21T12:00:00Z"]})
    raw.attrs["data_source"] = "greenlab_api_cache"
    result = assess_sensor_freshness(raw, "06M26042804", now="2026-08-21T12:12:00Z")
    assert result["status"] == "stale"
    assert result["reason"] == "sensor_data_stale"
    assert result["age_minutes"] == 12.0


def test_freshness_allows_recent_observation_and_marks_replay():
    raw = pd.DataFrame({"fetchedAt": [pd.Timestamp("2026-08-21T12:00:00Z")]})
    live = assess_sensor_freshness(raw, "06M26042804", now="2026-08-21T12:05:00Z")
    replay = assess_sensor_freshness(raw, "06M26042804", now="2026-08-21T13:00:00Z", replay=True)
    assert live["status"] == "fresh"
    assert replay["status"] == "replay"
    assert replay["replay"] is True


def test_fallback_source_is_never_live_even_with_recent_timestamp():
    raw = pd.DataFrame({"fetchedAt": ["2026-08-21T12:00:00Z"]})
    raw.attrs["data_source"] = "greenlab_api_cache_stale"
    result = assess_sensor_freshness(raw, "06M26042804", now="2026-08-21T12:01:00Z")
    assert result["status"] == "stale"
    assert result["reason"] == "fallback_source_not_live"
