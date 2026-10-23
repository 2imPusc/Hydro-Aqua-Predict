import json
import pytest
from datetime import datetime, timezone, timedelta
from experiments.weather_snapshot_health import check_health

def test_health_missing(tmp_path):
    res = check_health("s1", tmp_path / "non_existent.jsonl")
    assert res["status"] == "missing"

def test_health_healthy(tmp_path):
    p = tmp_path / "snap.jsonl"
    now = datetime.now(timezone.utc)
    with open(p, "w") as f:
        f.write(json.dumps({"station": "s1", "retrieved_at": now.isoformat()}) + "\n")
    res = check_health("s1", p)
    assert res["status"] == "healthy"
    assert res["captures_24h"] == 1

def test_health_stale_and_gaps(tmp_path):
    p = tmp_path / "snap.jsonl"
    now = datetime.now(timezone.utc)
    t1 = now - timedelta(hours=10)
    t2 = now - timedelta(hours=5)
    with open(p, "w") as f:
        f.write(json.dumps({"station": "s1", "retrieved_at": t1.isoformat()}) + "\n")
        f.write(json.dumps({"station": "s1", "retrieved_at": t2.isoformat()}) + "\n")
    res = check_health("s1", p)
    assert res["status"] == "stale" # t2 is 5 hours ago > 2
    assert len(res["gaps_gt_2h"]) == 1
    assert res["gaps_gt_2h"][0]["hours"] == 5.0


def _write_captures(path, times):
    with open(path, "w") as f:
        for t in times:
            f.write(json.dumps({"station": "s1", "retrieved_at": t.isoformat()}) + "\n")


def test_health_degraded_when_hourly_coverage_low(tmp_path):
    p = tmp_path / "snap.jsonl"
    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    # one capture every 3 h for 7 days, last one 30 min ago -> ~33% of hourly
    times = [now - timedelta(minutes=30) - timedelta(hours=3 * i) for i in range(56)]
    _write_captures(p, times)
    res = check_health("s1", p, now=now)
    assert res["status"] == "degraded"
    assert 0.30 <= res["coverage_7d"] <= 0.36


def test_health_full_hourly_coverage_is_healthy(tmp_path):
    p = tmp_path / "snap.jsonl"
    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    _write_captures(p, [now - timedelta(hours=i) for i in range(168)])
    res = check_health("s1", p, now=now)
    assert res["status"] == "healthy"
    assert res["coverage_7d"] == 1.0


def test_health_coverage_window_starts_at_first_capture(tmp_path):
    p = tmp_path / "snap.jsonl"
    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    # collector started 10 h ago and never missed a run
    _write_captures(p, [now - timedelta(hours=i) for i in range(11)])
    res = check_health("s1", p, now=now)
    assert res["status"] == "healthy"
