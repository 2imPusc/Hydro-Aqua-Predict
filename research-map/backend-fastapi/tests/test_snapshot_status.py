from datetime import datetime, timedelta, timezone

from app.repository import snapshot_status


def test_snapshot_becomes_stale_only_after_deadline():
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)
    assert snapshot_status({"stale_after": now + timedelta(seconds=1)}, now) == "fresh"
    assert snapshot_status({"stale_after": now - timedelta(seconds=1)}, now) == "stale"
    assert snapshot_status(None, now) == "unavailable"
