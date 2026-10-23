"""GET /api/v1/research/hazards/stations (Track G): per-station view of the C2 ledger, read-only."""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import hazard_api
from app.settings import settings

NOW = datetime(2026, 10, 23, 9, 0, tzinfo=timezone.utc)
FLAGS = {"used_by_alerts": False, "notification_eligible": False, "basis": "theory_only_unvalidated"}
WINDOWS = ((0, 24), (24, 48), (48, 72), (72, 120))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(hazard_api, "settings", replace(settings, hap_runtime_dir=str(runtime)))
    monkeypatch.setattr(hazard_api, "_now", lambda: NOW)
    app = FastAPI()
    app.include_router(hazard_api.router)
    return {"client": TestClient(app), "dir": runtime / "hazard-shadow"}


def _iso(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def rec(station="NB1", hazard="storm_wind", lead=0, tier=0, value=4, issued=NOW - timedelta(hours=1), span=None,
        status="fresh", skip=None, source="forecast", model="ecmwf_ifs025", **extra):
    span = span or (48 if lead == 72 else 24)
    vf = issued.replace(minute=0, second=0) + timedelta(hours=lead)
    out = {"issued_at": _iso(issued), "station": station, "exposure_class": "exposed", "hazard": hazard,
           "valid_from": _iso(vf), "valid_to": _iso(vf + timedelta(hours=span)), "lead_hours": lead,
           "value": None if skip else value, "unit": "cấp Beaufort", "tier": None if skip else tier,
           "action_vi": "Gia cố neo." if tier else None, "inputs": {"source": source, "model": model},
           "data_status": status, "config_version": "default-2026-10-23", **FLAGS, **extra}
    if skip:
        out["skip_reason"] = skip
    return out


def write(folder, day, records):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / f"hazard_{day}.jsonl").open("a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def station(body, sid="NB1"):
    return next(s for s in body["stations"] if s["id"] == sid)


def get(env):
    return env["client"].get("/api/v1/research/hazards/stations").json()


def test_unavailable_without_ledger(env):
    body = get(env)
    assert body["status"] == "unavailable" and body["reason"] == "no_hazard_ledger" and body["stations"] == []
    assert body["used_by_alerts"] is False


def test_latest_run_wins_and_builds_current_and_outlook(env):
    old = NOW - timedelta(hours=2)
    new = NOW - timedelta(hours=1)
    write(env["dir"], "20261023", [rec(issued=old, tier=3, value=10)])
    write(env["dir"], "20261023",
          [rec(issued=new, lead=a, tier=t, value=v) for (a, _), t, v in zip(WINDOWS, (2, 1, 0, 3), (8, 6, 4, 10))]
          + [rec(issued=new, hazard="heat", lead=0, skip="marine_disabled", status="unavailable")])
    body = get(env)
    assert body["status"] == "ready" and body["issued_at"] == _iso(new)
    assert body["config_version"] == "default-2026-10-23" and body["notification_eligible"] is False
    nb1 = station(body)
    assert nb1["data_status"] == "fresh" and nb1["max_tier"] == 2 and nb1["exposure_class"] == "exposed"
    assert nb1["name"].startswith("NB1") and nb1["lat"] is not None
    wind = next(c for c in nb1["current"] if c["hazard"] == "storm_wind")
    assert wind["tier"] == 2 and wind["value"] == 8 and wind["action_vi"]
    heat = next(c for c in nb1["current"] if c["hazard"] == "heat")
    assert heat["tier"] is None and heat["skip_reason"] == "marine_disabled" and heat["data_status"] == "unavailable"
    assert [d["max_tier"] for d in nb1["outlook"]] == [2, 1, 0, 3, 3]  # 72-120 h window fills days 4 and 5
    assert nb1["outlook"][0]["date"] == "2026-10-23" and nb1["outlook"][4]["date"] == "2026-10-27"


def test_old_run_is_stale_and_shows_no_tier(env):
    write(env["dir"], "20261023", [rec(issued=NOW - timedelta(hours=4), tier=3, value=10)])
    nb1 = station(get(env))
    assert nb1["data_status"] == "stale" and nb1["max_tier"] is None
    assert nb1["current"][0]["data_status"] == "stale" and nb1["current"][0]["tier"] == 3  # kept for "cũ" detail
    assert nb1["outlook"][0]["max_tier"] is None


def test_runner_reported_stale_input_stays_stale(env):
    write(env["dir"], "20261023", [rec(skip="stale_forecast", status="stale")])
    nb1 = station(get(env))
    assert nb1["data_status"] == "stale" and nb1["max_tier"] is None


def test_registry_station_without_records_is_unavailable(env):
    write(env["dir"], "20261023", [rec()])
    other = station(get(env), "TEST01")
    assert other["data_status"] == "unavailable" and other["reason"] == "no_records" and other["current"] == []


def test_reads_previous_day_file_and_ignores_bad_lines(env):
    write(env["dir"], "20261022", [rec(station="TEST01", issued=NOW - timedelta(hours=10), tier=1)])
    write(env["dir"], "20261023", [rec()])
    (env["dir"] / "hazard_20261023.jsonl").open("a", encoding="utf-8").write('{"truncated": ')
    body = get(env)
    assert body["ledger_files"] == ["hazard_20261023.jsonl", "hazard_20261022.jsonl"]
    assert station(body, "TEST01")["data_status"] == "stale"


def test_replay_records_are_flagged(env):
    write(env["dir"], "20261023", [rec(model="era5", replay={"label": "reanalysis_as_forecast"})])
    body = get(env)
    nb1 = station(body)
    assert nb1["replay"] is True and body["replay"] is True and nb1["replay_labels"] == ["reanalysis_as_forecast"]
    write(env["dir"], "20261023", [rec(station="TEST01", source="reanalysis", model="x")])
    assert station(get(env), "TEST01")["replay"] is True


def test_storm_watch_from_ledger_record(env):
    run = NOW - timedelta(hours=9)
    watch = rec(hazard="storm_watch", lead=120, tier=1, value=0.42, span=120,
                source="ecmwf_opendata", model="ecmwf_ifs_ens_tc_tracks")
    watch["inputs"].update({"run_time": _iso(run), "storm_id": "36W"})
    write(env["dir"], "20261023", [rec(), watch])
    nb1 = station(get(env))
    sw = nb1["storm_watch"]
    assert sw["source"] == "ledger" and sw["p_within_500km_120h"] == 0.42 and sw["tier"] == 1
    assert sw["storm_id"] == "36W" and sw["data_status"] == "fresh"
    assert all(c["hazard"] != "storm_watch" for c in nb1["current"])  # watch never mixes into current tiers


def test_storm_watch_falls_back_to_storms_active(env):
    write(env["dir"], "20261023", [rec()])
    (env["dir"] / "storms_active_2026102300.json").write_text(json.dumps(
        {"status": "ready", "run_time": "2026-10-23T00:00:00Z",
         "storms": [{"id": "36W", "name": "CHAMPI", "p_within_500km_120h": 0.12, "p_within_200km_120h": 0.0}]}),
        encoding="utf-8")
    sw = station(get(env))["storm_watch"]
    assert sw["source"] == "storms_active" and sw["p_within_500km_120h"] == 0.12
    assert sw["data_status"] == "fresh" and sw["site_note"] == "basin_summary_site_not_per_station"
