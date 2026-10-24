"""core.field_events: path wiring and the write-once store (API tests live in research-map backend)."""
from datetime import datetime, timezone

from core import field_events as fe
from core import paths

BODY = {"observed_at": "2026-10-20T06:30", "station_id": "NB1", "event_type": "ca_chet", "severity": 3, "source": "can_bo"}


def test_events_dir_under_runtime():
    assert paths.EVENTS_DIR == paths.RUNTIME_DIR / "events"


def test_validate_normalises_local_time():
    fields, errors = fe.validate(BODY, {"NB1"}, now=datetime(2026, 10, 24, tzinfo=timezone.utc))
    assert errors == []
    assert fields["observed_at"] == "2026-10-20T06:30:00+07:00"
    assert fields["measurements"] == {} and fields["supersedes"] is None


def test_registry_none_rejects_known_ids_only():
    _, errors = fe.validate(BODY, None)
    assert any("registry unavailable" in e for e in errors)
    _, errors = fe.validate({**BODY, "station_id": "khac", "station_other": "Bè A"}, None)
    assert errors == []


def test_store_roundtrip_and_supersede(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "EVENTS_DIR", tmp_path / "events")
    fields, _ = fe.validate(BODY, {"NB1"})
    first = fe.create(fields)
    fixed, _ = fe.validate({**BODY, "severity": 2, "supersedes": first["event_id"]}, {"NB1"})
    second = fe.create(fixed)
    records = {r["event_id"]: r for r in fe.load_all()}
    assert records[first["event_id"]]["superseded_by"] == second["event_id"]
    assert [r["event_id"] for r in fe.active(list(records.values()))] == [second["event_id"]]
