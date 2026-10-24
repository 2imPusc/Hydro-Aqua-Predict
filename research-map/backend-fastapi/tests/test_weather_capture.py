"""Worker-side as-issued weather capture for B5 (H2.1): same record format, append-only, hourly."""
import asyncio
import json
from datetime import datetime, timezone

import httpx

from app import weather_capture as wc

NOW = datetime(2026, 10, 24, 5, 12, tzinfo=timezone.utc)
STATION = "06M26042804"
LAT, LON = 20.71894498573044, 107.042635855355
# Field set of a current scheduled-task record (experiments/forecast_snapshot_store.py).
TASK_FIELDS = {"features", "issued_at", "location", "location_id", "product", "provenance_class", "provider", "provider_run_at",
               "raw_payload_hash", "research_only", "retrieved_at", "snapshot_id", "source_timezone", "station", "station_id", "units",
               "valid_at", "capture_source"}


def _payload(hours=72):
    times = [f"2026-10-{24 + h // 24:02d}T{h % 24:02d}:00" for h in range(hours)]
    hourly = {"time": times, **{name: [float(i) for i in range(hours)] for name in wc.FIELDS}}
    return {"timezone": "Asia/Ho_Chi_Minh", "hourly": hourly, "hourly_units": {"temperature_2m": "°C", "time": "iso8601"}}


def test_records_match_scheduled_task_format():
    records = wc.build_records(_payload(), STATION, wc.nb1_location(LAT, LON), NOW)
    assert len(records) == 72
    first = records[0]
    assert set(first) == TASK_FIELDS
    assert first["capture_source"] == "research_map_worker" and first["provenance_class"] == "captured_live"
    assert first["location_id"] == "map_station_NB1" and first["location"]["accuracy"] == "nearby_reference_station"
    assert first["product"] == "open_meteo_forecast" and first["provider"] == "open_meteo"
    assert first["issued_at"] == first["retrieved_at"] == "2026-10-24T05:12:00+00:00"
    assert first["valid_at"] == "2026-10-23T17:00:00+00:00"  # local midnight -> UTC
    assert set(first["features"]) == set(wc.FIELDS)
    assert len(first["raw_payload_hash"]) == 64


def test_snapshot_id_matches_experiments_store():
    # experiments.forecast_snapshot_store.snapshot_id of the same key fields
    record = {"station": STATION, "provider": "open_meteo", "issued_at": "2026-10-24T05:00:00+00:00",
              "valid_at": "2026-10-23T17:00:00+00:00", "product": "open_meteo_forecast"}
    assert wc.snapshot_id(record) == "b7df5d7a2f0ae077d799603b"


def test_append_only_and_idempotent(tmp_path):
    path = tmp_path / "worker-capture" / "w.jsonl"
    records = wc.build_records(_payload(3), STATION, wc.nb1_location(LAT, LON), NOW)
    assert wc.append_records(path, records) == 3
    before = path.read_bytes()
    assert wc.append_records(path, records) == 0
    assert path.read_bytes() == before
    later = wc.build_records(_payload(3), STATION, wc.nb1_location(LAT, LON), NOW.replace(hour=6))
    assert wc.append_records(path, later) == 3
    assert path.read_bytes().startswith(before)  # never rewritten, only appended
    assert [json.loads(line)["issued_at"][:13] for line in path.read_text(encoding="utf-8").splitlines()] == ["2026-10-24T05"] * 3 + ["2026-10-24T06"] * 3


def test_capture_once_per_utc_hour(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        return httpx.Response(200, json=_payload())

    path = tmp_path / "w.jsonl"

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await wc.capture_once(path, STATION, LAT, LON, now=NOW, client=client)
            again = await wc.capture_once(path, STATION, LAT, LON, now=NOW.replace(minute=50), client=client)
            next_hour = await wc.capture_once(path, STATION, LAT, LON, now=NOW.replace(hour=6, minute=1), client=client)
            return first, again, next_hour

    assert asyncio.run(run()) == (72, 0, 72)
    assert len(calls) == 2
    assert calls[0]["hourly"] == wc.HOURLY_VARIABLES and calls[0]["forecast_days"] == "3" and calls[0]["timezone"] == "Asia/Ho_Chi_Minh"
    assert wc.last_issued_at(path) == NOW.replace(hour=6, minute=1)


def test_capture_failure_writes_nothing(tmp_path):
    path = tmp_path / "w.jsonl"

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(429))) as client:
            await wc.capture_once(path, STATION, LAT, LON, now=NOW, client=client)

    try:
        asyncio.run(run())
    except httpx.HTTPStatusError:
        pass
    else:
        raise AssertionError("expected HTTP error")
    assert not path.exists()
