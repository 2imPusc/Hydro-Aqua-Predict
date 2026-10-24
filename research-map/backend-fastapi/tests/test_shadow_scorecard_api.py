"""H1.5 scorecard endpoint: newest scorecard JSON + live ledger progress, read-only."""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import research
from app.settings import settings

NOW = datetime(2026, 10, 31, 6, 0, tzinfo=timezone.utc)
STATION = "06M26042804"
URL = "/api/v1/research/forecast/long/scorecard"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    runtime, experiments = tmp_path / "runtime", tmp_path / "experiments"
    monkeypatch.setattr(research, "settings", replace(
        settings, research_export_dir=str(tmp_path / "research-map"), hap_runtime_dir=str(runtime),
        experiments_dir=str(experiments), ledger_tail_bytes=1 << 20))
    monkeypatch.setattr(research, "_now", lambda: NOW)
    research.clear_cache()
    app = FastAPI()
    app.include_router(research.router)
    return {"client": TestClient(app), "runtime": runtime, "experiments": experiments}


def _card(generated: datetime, station=STATION, status="insufficient_evidence", n_scored=0):
    return {"schema_version": "shadow-scorecard-v1", "station": station, "generated_at": generated.isoformat(), "status": status,
            "evidence_reasons": ["n_scored<200", "days<7"] if status != "sufficient" else [],
            "thresholds": {"min_resolved": 200, "min_days": 7, "gate_days": 28, "pi80_target": [0.75, 0.85]},
            "ledger": {"n_forecasts": 84, "n_scored": n_scored}, "gate": {"status": "collecting", "progress": 0.0},
            "groups": [{"target": "Temperature", "base_feature_set": "B4_quality", "variant": "with_pH", "horizon_minutes": 180,
                        "n_scored": n_scored, "evidence": status}],
            "paired": [], "weekly": [], "paired_weekly": [], "skips": []}


def _write_card(root, name, card):
    out = root / name
    out.mkdir(parents=True)
    (out / "scorecard.json").write_text(json.dumps(card), encoding="utf-8")


def _ledger(path, issued_times, station=STATION, partial=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(json.dumps({"record_id": str(i), "station_serial": station, "issued_at": t.isoformat()}) + "\n"
                    for i, t in enumerate(issued_times))
    path.write_text(lines + ('{"record_id": "x", "station' if partial else ""), encoding="utf-8")


def test_missing_scorecard_and_ledger_is_honest(env):
    body = env["client"].get(URL).json()
    assert body["status"] == "unavailable" and body["reason"] == "scorecard_missing"
    assert body["export_version"] is None and body["used_by_alerts"] is False
    assert body["live"]["ledger_state"] == "missing" and body["live"]["gate_progress"] == 0.0


def test_newest_scorecard_for_station_and_live_progress(env):
    experiments = env["experiments"]
    _write_card(experiments, "shadow-scorecard-20261024", _card(NOW - timedelta(days=7)))
    _write_card(experiments, "shadow-scorecard-20261030", _card(NOW - timedelta(hours=30), status="sufficient", n_scored=4000))
    _write_card(experiments, "shadow-scorecard-20261030-1800", _card(NOW - timedelta(hours=12), station="OTHER"))
    (experiments / "shadow-scorecard-20261031").mkdir()  # run in progress: no scorecard.json yet
    (experiments / "shadow-scorecard-old-format").mkdir()
    first = NOW - timedelta(days=7)
    _ledger(env["runtime"] / "forecast-shadow" / "long_forecasts.jsonl",
            [first, first + timedelta(minutes=1), NOW - timedelta(minutes=1)], partial=True)
    body = env["client"].get(URL + f"?station={STATION}").json()
    assert body["status"] == "ready" and body["export_version"] == "shadow-scorecard-20261030"
    assert body["evidence"] == "sufficient" and body["evidence_reasons"] == []
    assert body["scorecard_age_hours"] == 30.0
    assert body["groups"][0]["n_scored"] == 4000 and body["mode"] == "shadow"
    live = body["live"]
    assert live["ledger_state"] == "active" and live["first_issued_at"] == first.isoformat()
    assert live["latest_issued_at"] == (NOW - timedelta(minutes=1)).isoformat()
    assert live["ledger_days"] == pytest.approx(7.0, abs=0.002)
    assert live["gate_progress"] == pytest.approx(0.25, abs=0.001) and live["gate_days"] == 28


def test_empty_ledger_with_scorecard(env):
    _write_card(env["experiments"], "shadow-scorecard-20261024", _card(NOW - timedelta(hours=1)))
    _ledger(env["runtime"] / "forecast-shadow" / "long_forecasts.jsonl", [])
    body = env["client"].get(URL).json()
    assert body["status"] == "ready" and body["evidence"] == "insufficient_evidence"
    assert body["live"]["ledger_state"] == "empty" and body["live"]["ledger_days"] == 0.0
