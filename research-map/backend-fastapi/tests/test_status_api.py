"""Light /api/v1/status endpoint and gzip compression on the main app (no Postgres, no startup hooks)."""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import main, research
from app.settings import settings


class _DownRepository:
    def __init__(self):
        self.calls = 0

    def status_summary(self, station_serial, connect_timeout=3):
        self.calls += 1
        raise psycopg.OperationalError("connection refused")


class _Repository:
    def __init__(self, snapshot, latest_observed_at):
        self.result = {"snapshot": snapshot, "latest_observed_at": latest_observed_at}
        self.stations = []

    def status_summary(self, station_serial, connect_timeout=3):
        self.stations.append(station_serial)
        return self.result


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "settings", replace(settings, research_export_dir=str(tmp_path / "research-map")))
    research.clear_cache()
    monkeypatch.setitem(main._status_db_down_until, "until", 0.0)
    # Plain TestClient (no context manager): startup hooks (DB init, shapefile domain) do not run.
    return TestClient(main.app)


def _export(root, stamp="20261017-1334", payload=None):
    out = root / stamp
    out.mkdir(parents=True)
    (out / "manifest.json").write_text(json.dumps({"export_version": stamp, "omitted": {}}), encoding="utf-8")
    (out / "overview.json").write_text(json.dumps(payload or {"directions": []}), encoding="utf-8")
    return out


def test_status_degrades_gracefully_when_database_is_down(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "repository", _DownRepository())
    _export(tmp_path / "research-map")
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["context"] == {"status": "unavailable", "reason": "database_unavailable"}
    assert body["sensor"]["status"] == "unavailable" and body["sensor"]["reason"] == "database_unavailable"
    assert body["research"] == {"status": "ready", "export_version": "20261017-1334"}


def test_status_remembers_database_failure_briefly(client, monkeypatch):
    repo = _DownRepository()
    monkeypatch.setattr(main, "repository", repo)
    first, second = client.get("/api/v1/status").json(), client.get("/api/v1/status").json()
    assert repo.calls == 1
    assert first["context"] == second["context"] == {"status": "unavailable", "reason": "database_unavailable"}


def test_status_reports_fresh_and_stale_ages(client, monkeypatch):
    now = datetime.now(timezone.utc)
    repo = _Repository({"snapshot_id": "snap-1", "retrieved_at": now - timedelta(minutes=5), "stale_after": now + timedelta(minutes=60)},
                       now - timedelta(hours=2))
    monkeypatch.setattr(main, "repository", repo)
    body = client.get("/api/v1/status?station=06M26042804").json()
    assert repo.stations == ["06M26042804"]
    assert body["context"]["status"] == "fresh" and body["context"]["snapshot_id"] == "snap-1"
    assert 290 <= body["context"]["age_seconds"] <= 310
    assert body["sensor"]["status"] == "stale" and 7190 <= body["sensor"]["age_seconds"] <= 7210
    assert body["status"] == "degraded"
    assert body["research"] == {"status": "unavailable", "export_version": None}


def test_status_without_snapshot_or_sensor_rows(client, monkeypatch):
    monkeypatch.setattr(main, "repository", _Repository(None, None))
    body = client.get("/api/v1/status").json()
    assert body["context"] == {"status": "unavailable", "reason": "no_context_snapshot"}
    assert body["sensor"]["reason"] == "sensor_observations_missing"


def test_large_responses_are_gzipped(client, tmp_path):
    _export(tmp_path / "research-map", payload={"directions": [{"id": "H1", "findings": ["x" * 80] * 40}]})
    response = client.get("/api/v1/research/overview", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"
    assert response.json()["directions"][0]["id"] == "H1"  # httpx decodes transparently


def test_small_responses_are_not_gzipped(client, monkeypatch):
    monkeypatch.setattr(main, "repository", _DownRepository())
    response = client.get("/api/v1/status", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in response.headers
