"""GET /api/v1/research/storms/active (Track D): newest storms_active_<run>.json, read-only."""
import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import hazard_api
from app.settings import settings

NOW = datetime(2026, 10, 23, 9, 0, tzinfo=timezone.utc)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(hazard_api, "settings", replace(settings, hap_runtime_dir=str(runtime)))
    monkeypatch.setattr(hazard_api, "_now", lambda: NOW)
    app = FastAPI()
    app.include_router(hazard_api.router)
    return {"client": TestClient(app), "dir": runtime / "hazard-shadow"}


def _write(folder, run, storms, **extra):
    folder.mkdir(parents=True, exist_ok=True)
    body = {"status": "ready", "source": "ecmwf_opendata", "fetched_at": "2026-10-23T08:26:54Z",
            "run_time": f"{run[:4]}-{run[4:6]}-{run[6:8]}T{run[8:]}:00:00Z", "storms": storms, **extra}
    (folder / f"storms_active_{run}.json").write_text(json.dumps(body), encoding="utf-8")


STORM = {"id": "36W", "name": "CHAMPI", "run_time": "2026-10-23T00:00:00Z", "members": 51,
         "p_within_500km_120h": 0.0, "p_within_200km_120h": 0.0, "closest_approach_km_median": 1601.1,
         "eta_hours_median": None, "track_median": [[123.7, 22.7, "2026-10-23T00:00:00Z"]]}


def test_unavailable_without_files(env):
    body = env["client"].get("/api/v1/research/storms/active").json()
    assert body["status"] == "unavailable" and body["reason"] == "no_storm_track_summary" and body["storms"] == []


def test_newest_run_wins_and_is_fresh(env):
    _write(env["dir"], "2026102212", [{**STORM, "id": "OLD"}])
    _write(env["dir"], "2026102300", [STORM])
    (env["dir"] / "storms_active_latest.json").write_text("{}", encoding="utf-8")  # ignored: not a run stamp
    body = env["client"].get("/api/v1/research/storms/active").json()
    assert body["status"] == "ready" and body["source"] == "ecmwf_opendata"
    assert body["file"] == "storms_active_2026102300.json" and body["data_status"] == "fresh"
    assert body["run_age_hours"] == 9.0 and body["used_by_alerts"] is False
    assert [s["id"] for s in body["storms"]] == ["36W"]
    assert body["fetched_at"] == "2026-10-23T08:26:54Z"


def test_empty_storm_list_is_ready(env):
    _write(env["dir"], "2026102300", [])
    body = env["client"].get("/api/v1/research/storms/active").json()
    assert body["status"] == "ready" and body["storms"] == []


def test_stale_run_flagged(env):
    _write(env["dir"], "2026102100", [STORM])
    body = env["client"].get("/api/v1/research/storms/active").json()
    assert body["status"] == "ready" and body["data_status"] == "stale" and body["reason"] == "stale_run"
    assert body["run_time"] == "2026-10-21T00:00:00Z"


def test_unreadable_newest_falls_back(env):
    _write(env["dir"], "2026102212", [STORM])
    (env["dir"] / "storms_active_2026102300.json").write_text("{broken", encoding="utf-8")
    body = env["client"].get("/api/v1/research/storms/active").json()
    assert body["file"] == "storms_active_2026102212.json"
