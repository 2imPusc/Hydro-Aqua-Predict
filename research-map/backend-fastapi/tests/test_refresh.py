from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import refresh

NOW = datetime(2026, 10, 24, 6, 0, tzinfo=timezone.utc)


def test_recent_snapshot_is_fresh_and_writes_nothing(tmp_path):
    result = refresh.request_refresh(str(tmp_path), NOW - timedelta(minutes=3), now=NOW)
    assert result["status"] == "fresh" and refresh.read_request(str(tmp_path)) is None


def test_old_snapshot_requests_once_then_reports_pending(tmp_path):
    latest = NOW - timedelta(minutes=50)
    assert refresh.request_refresh(str(tmp_path), latest, now=NOW)["status"] == "requested"
    assert refresh.request_refresh(str(tmp_path), latest, now=NOW + timedelta(seconds=30))["status"] == "pending"
    assert refresh.due(str(tmp_path), NOW - timedelta(minutes=50))          # worker ran before the request
    assert not refresh.due(str(tmp_path), NOW + timedelta(seconds=1))        # worker run started after it


def test_no_snapshot_yet_requests(tmp_path):
    assert refresh.request_refresh(str(tmp_path), None, now=NOW)["status"] == "requested"
