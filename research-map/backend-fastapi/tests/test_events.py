"""Field event log API. Writes go to a tmp dir only."""
import csv
import io
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import events  # import first: its fallback puts the repo root on sys.path for `core`
from core import field_events as fe
from core import paths


@pytest.fixture
def events_dir(tmp_path, monkeypatch):
    d = tmp_path / "events"
    monkeypatch.setattr(paths, "EVENTS_DIR", d)
    return d


@pytest.fixture
def client(events_dir):
    app = FastAPI()
    app.include_router(events.router)
    return TestClient(app)


def _body(**over):
    body = {
        "observed_at": "2026-10-20T06:30",
        "station_id": "NB1",
        "event_type": "ca_bo_an",
        "severity": 2,
        "measurements": {"do_mg_l": 3.4, "water_temp_c": 29.5},
        "note": "Cá lồng 3 bỏ ăn buổi sáng",
        "reporter": "anh Hùng",
        "source": "nguoi_nuoi",
    }
    body.update(over)
    return body


def _post(client, **over):
    return client.post("/api/v1/events", json=_body(**over))


def test_create_and_list(client, events_dir):
    r = _post(client)
    assert r.status_code == 201
    ev = r.json()["event"]
    assert fe.ID_RE.match(ev["event_id"])
    assert ev["observed_at"] == "2026-10-20T06:30:00+07:00"
    assert ev["measurements"] == {"do_mg_l": 3.4, "water_temp_c": 29.5}
    assert ev["supersedes"] is None and ev["schema_version"] == 1
    stored = json.loads((events_dir / f"{ev['event_id']}.json").read_text(encoding="utf-8"))
    assert stored["note"] == "Cá lồng 3 bỏ ăn buổi sáng" and "superseded_by" not in stored
    body = client.get("/api/v1/events").json()
    assert body["status"] == "ready" and body["count"] == 1 and body["total_active"] == 1
    assert body["events"][0]["event_id"] == ev["event_id"]
    assert body["min_events_for_calibration"] == 10
    assert body["event_types"]["ca_chet"] == "Cá chết"


def test_empty_list_without_dir(client, events_dir):
    body = client.get("/api/v1/events").json()
    assert body["events"] == [] and body["total_active"] == 0
    assert not events_dir.exists()


def test_aware_time_converted_to_vn(client):
    ev = _post(client, observed_at="2026-10-20T00:00:00Z").json()["event"]
    assert ev["observed_at"] == "2026-10-20T07:00:00+07:00"


def test_list_newest_first_and_filters(client):
    a = _post(client, observed_at="2026-10-01T08:00").json()["event"]["event_id"]
    b = _post(client, observed_at="2026-10-15T08:00", station_id="TEST01", event_type="mua_lon").json()["event"]["event_id"]
    c = _post(client, observed_at="2026-10-10T08:00", station_id="khac", station_other="Lồng bè Gia Luận").json()["event"]["event_id"]
    ids = [e["event_id"] for e in client.get("/api/v1/events").json()["events"]]
    assert ids == [b, c, a]
    assert [e["event_id"] for e in client.get("/api/v1/events", params={"station": "TEST01"}).json()["events"]] == [b]
    assert [e["event_id"] for e in client.get("/api/v1/events", params={"event_type": "ca_bo_an"}).json()["events"]] == [c, a]
    rng = client.get("/api/v1/events", params={"from": "2026-10-05", "to": "2026-10-10"}).json()["events"]
    assert [e["event_id"] for e in rng] == [c]
    assert client.get("/api/v1/events", params={"from": "not-a-date"}).status_code == 422


def test_supersede_hides_old_keeps_export(client, events_dir):
    old = _post(client).json()["event"]["event_id"]
    r = _post(client, severity=3, supersedes=old)
    assert r.status_code == 201
    new = r.json()["event"]["event_id"]
    listed = client.get("/api/v1/events").json()
    assert [e["event_id"] for e in listed["events"]] == [new]
    assert listed["total_active"] == 1 and listed["total_superseded"] == 1
    full = client.get("/api/v1/events", params={"include_superseded": "true"}).json()["events"]
    assert {e["event_id"]: e["superseded_by"] for e in full} == {old: new, new: None}
    # the original file is untouched
    assert json.loads((events_dir / f"{old}.json").read_text(encoding="utf-8"))["severity"] == 2
    rows = list(csv.DictReader(io.StringIO(client.get("/api/v1/events/export.csv").text.lstrip("﻿"))))
    flags = {row["event_id"]: (row["superseded"], row["superseded_by"], row["supersedes"]) for row in rows}
    assert flags == {old: ("true", new, ""), new: ("false", "", old)}


def test_supersede_only_head(client):
    old = _post(client).json()["event"]["event_id"]
    _post(client, supersedes=old)
    r = _post(client, supersedes=old)
    assert r.status_code == 409 and r.json()["reason"] == "already_superseded"


def test_supersede_claim_blocks_race(client, events_dir):
    old = _post(client).json()["event"]["event_id"]
    (events_dir / f"{old}.superseded.claim").write_text("")  # a concurrent correction holds the claim
    assert _post(client, supersedes=old).status_code == 409


def test_supersede_unknown_404(client):
    assert _post(client, supersedes="20261020T063000000Z-abcdef").status_code == 404
    r = _post(client, supersedes="../../etc/passwd")
    assert r.status_code == 422 and any("supersedes" in e for e in r.json()["errors"])


def test_export_csv(client):
    _post(client, note="=HYPERLINK(\"x\")", station_id="khac", station_other="Bè ông Tư")
    r = client.get("/api/v1/events/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert r.content.startswith("﻿".encode("utf-8"))
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿"))))
    assert len(rows) == 1
    row = rows[0]
    assert list(row) == events.CSV_COLUMNS
    assert row["note"].startswith("'=")
    assert row["event_type_vi"] == "Cá bỏ ăn" and row["source_vi"] == "Người nuôi"
    assert row["do_mg_l"] == "3.4" and row["salinity_psu"] == "" and row["station_other"] == "Bè ông Tư"


@pytest.mark.parametrize("over, needle", [
    ({"observed_at": None}, "observed_at"),
    ({"observed_at": "hôm qua"}, "observed_at"),
    ({"observed_at": "2099-01-01T00:00"}, "future"),
    ({"observed_at": "2020-01-01T00:00"}, "observed_at"),
    ({"station_id": "ZZZ"}, "unknown station"),
    ({"station_id": "khac"}, "station_other"),
    ({"station_other": "x"}, "station_other"),
    ({"event_type": "ca_vui"}, "event_type"),
    ({"severity": 4}, "severity"),
    ({"severity": True}, "severity"),
    ({"severity": "2"}, "severity"),
    ({"measurements": {"do_mg_l": 35}}, "plausible"),
    ({"measurements": {"salinity_psu": -1}}, "plausible"),
    ({"measurements": {"secchi_m": "1,2"}}, "number"),
    ({"measurements": {"ph": 8}}, "unknown measurement"),
    ({"event_type": "do_tay", "measurements": {}}, "at least one"),
    ({"event_type": "khac", "note": "  "}, "note"),
    ({"note": "x" * 1001}, "note"),
    ({"reporter": "x" * 121}, "reporter"),
    ({"source": "ai"}, "source"),
    ({"extra": 1}, "unknown field"),
])
def test_validation_422_no_write(client, events_dir, over, needle):
    r = _post(client, **over)
    assert r.status_code == 422, r.text
    assert any(needle in e for e in r.json()["errors"]), r.json()["errors"]
    assert not events_dir.exists()


def test_nan_and_bad_json_rejected(client, events_dir):
    raw = json.dumps(_body()).replace("3.4", "NaN")
    assert client.post("/api/v1/events", content=raw, headers={"content-type": "application/json"}).status_code == 422
    assert client.post("/api/v1/events", content="{", headers={"content-type": "application/json"}).status_code == 422
    assert client.post("/api/v1/events", json=[1, 2]).status_code == 422
    assert not events_dir.exists()


def test_oversized_body_413(client, events_dir):
    r = client.post("/api/v1/events", json=_body(note="x" * (events.MAX_BODY_BYTES + 1)))
    assert r.status_code == 413
    assert not events_dir.exists()


def test_exclusive_create_never_overwrites(events_dir, monkeypatch):
    fields, errors = fe.validate(_body(), {"NB1"})
    assert errors == []
    monkeypatch.setattr(fe.secrets, "token_hex", lambda n: "aaaaaa")
    from datetime import datetime, timezone
    fixed = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
    first = fe.create(fields, now=fixed)
    path = events_dir / f"{first['event_id']}.json"
    before = path.read_bytes()
    suffixes = iter(["aaaaaa", "bbbbbb"])
    monkeypatch.setattr(fe.secrets, "token_hex", lambda n: next(suffixes))
    second = fe.create(fields, now=fixed)  # same instant: the id collides once, then a new suffix is drawn
    assert second["event_id"] != first["event_id"] and second["event_id"].endswith("-bbbbbb")
    assert path.read_bytes() == before


def test_unwritable_dir_503(client, events_dir, monkeypatch):
    def boom(*args, **kwargs):
        raise PermissionError("read-only file system")
    monkeypatch.setattr(events.fe, "create", boom)
    r = _post(client)
    assert r.status_code == 503 and r.json()["reason"] == "events_dir_not_writable"


def test_write_failure_releases_claim(client, events_dir, monkeypatch):
    old = _post(client).json()["event"]["event_id"]

    def boom(*args, **kwargs):
        raise PermissionError("disk full")
    monkeypatch.setattr(fe, "_write_new", boom)
    assert _post(client, supersedes=old).status_code == 503
    assert not (events_dir / f"{old}.superseded.claim").exists()
    monkeypatch.undo()
    monkeypatch.setattr(paths, "EVENTS_DIR", events_dir)
    assert _post(client, supersedes=old).status_code == 201


def test_registry_unavailable_503(client, monkeypatch):
    def missing():
        raise FileNotFoundError("station_registry_unavailable")
    monkeypatch.setattr(events, "station_records", missing)
    r = _post(client)
    assert r.status_code == 503 and r.json()["reason"] == "station_registry_unavailable"
    assert _post(client, station_id="khac", station_other="Bè ông Tư").status_code == 201


def test_unreadable_files_skipped(client, events_dir):
    _post(client)
    (events_dir / "20261020T063000000Z-ffffff.json").write_text("{not json", encoding="utf-8")
    (events_dir / "notes.txt").write_text("x", encoding="utf-8")
    assert client.get("/api/v1/events").json()["count"] == 1
    assert os.listdir(events_dir)  # nothing was removed
