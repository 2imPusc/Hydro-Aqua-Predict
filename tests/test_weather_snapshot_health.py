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
