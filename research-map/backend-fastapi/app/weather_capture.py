"""Second as-issued weather capture source for B5 (roadmap H2.1), run by the worker.

The Windows scheduled task (``experiments/capture_weather_snapshot.ps1`` ->
``experiments/forecast_snapshot_store.py``) misses hours whenever it fails or
the machine sleeps through its trigger. The worker runs this capture once per
UTC hour (checked every minute, so it also fires shortly after a wake-up) and
appends to its OWN append-only file, in the same record format plus
``capture_source = "research_map_worker"`` so the two sources stay
distinguishable. ``core.b5_coverage`` / ``read_snapshot_union`` union them,
de-duplicated by issue hour (the scheduled task wins).

One single-point Open-Meteo request per capture (same variables, 3 forecast
days and provider timezone as ``core.weather._fetch_open_meteo``) at the NB1
point; the regional map grid is not reused because it has neither the B5
variables nor the NB1 location. Research-only: nothing here feeds alerts.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

CAPTURE_SOURCE = "research_map_worker"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
# Must match core.weather.HOURLY_VARIABLES / forecast_snapshot_store field list.
HOURLY_VARIABLES = "temperature_2m,relative_humidity_2m,precipitation,cloud_cover,surface_pressure,wind_speed_10m,wind_direction_10m"
FIELDS = ("temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m", "wind_direction_10m", "cloud_cover", "surface_pressure")
PROVIDER_TIMEZONE = "Asia/Ho_Chi_Minh"
FORECAST_DAYS = 3
TAIL_BYTES = 256 * 1024


def snapshot_id(record: dict) -> str:
    """Identical to ``experiments.forecast_snapshot_store.snapshot_id``."""
    key = "|".join(str(record.get(k, "")) for k in ("station", "provider", "issued_at", "valid_at", "product"))
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def nb1_location(latitude: float, longitude: float) -> dict:
    """The B5 location record of station 06M26042804 (``core.config`` weather_location, NB1 anchor)."""
    return {"accuracy": "nearby_reference_station", "latitude": latitude, "longitude": longitude, "source": "map_station_NB1"}


def build_records(payload: dict, station: str, location: dict, retrieved_at: datetime) -> list[dict]:
    """One record per valid hour, field-for-field the scheduled task's format plus ``capture_source``."""
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    provider_timezone = payload.get("timezone", PROVIDER_TIMEZONE)
    payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    issued = retrieved_at.astimezone(timezone.utc).isoformat()
    records = []
    for index, provider_valid_at in enumerate(times):
        valid_at = datetime.fromisoformat(provider_valid_at)
        if valid_at.tzinfo is None:
            valid_at = valid_at.replace(tzinfo=ZoneInfo(provider_timezone))
        record = {
            "station": station,
            "station_id": station,
            "provider": "open_meteo",
            "product": payload.get("model", "open_meteo_forecast"),
            "source_timezone": provider_timezone,
            "issued_at": issued,
            "valid_at": valid_at.astimezone(timezone.utc).isoformat(),
            "retrieved_at": issued,
            "provider_run_at": None,
            "location": location,
            "location_id": location.get("source", "unknown"),
            "units": payload.get("hourly_units", {}),
            "raw_payload_hash": payload_hash,
            "features": {name: hourly.get(name, [None] * len(times))[index] for name in FIELDS},
            "provenance_class": "captured_live",
            "capture_source": CAPTURE_SOURCE,
            "research_only": True,
        }
        record["snapshot_id"] = snapshot_id(record)
        records.append(record)
    return records


def _tail_lines(path: Path) -> list[bytes]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        handle.seek(max(0, size - TAIL_BYTES))
        data = handle.read()
    lines = data.split(b"\n")
    if size > TAIL_BYTES:
        lines = lines[1:]  # first line may be cut
    return [line for line in lines if line.strip()]


def last_issued_at(path: Path) -> datetime | None:
    """Issue time of the newest record (append-only file: read only its tail)."""
    if not path.is_file():
        return None
    for line in reversed(_tail_lines(path)):
        try:
            value = json.loads(line).get("issued_at")
        except ValueError:
            continue
        if value:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def captured_this_hour(path: Path, now: datetime) -> bool:
    last = last_issued_at(path)
    if last is None:
        return False
    hour = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return last.astimezone(timezone.utc) >= hour


def append_records(path: Path, records: list[dict]) -> int:
    """Append records whose ``snapshot_id`` is not already in the file's tail; never rewrites.

    Every record of one capture shares its issue time, so a duplicate can only
    sit among the most recent lines.
    """
    if not records:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    if path.is_file():
        for line in _tail_lines(path):
            try:
                seen.add(json.loads(line).get("snapshot_id"))
            except ValueError:
                continue
    fresh = [record for record in records if record["snapshot_id"] not in seen]
    if not fresh:
        return 0
    payload = "".join(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n" for record in fresh)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(payload)
    return len(fresh)


async def fetch_point(latitude: float, longitude: float, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    params = {"latitude": latitude, "longitude": longitude, "hourly": HOURLY_VARIABLES, "forecast_days": FORECAST_DAYS, "timezone": PROVIDER_TIMEZONE}
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        response = await client.get(OPEN_METEO_FORECAST, params=params)
        response.raise_for_status()
        return response.json()
    finally:
        if owns:
            await client.aclose()


async def capture_once(path: Path, station: str, latitude: float, longitude: float, *,
                       now: datetime | None = None, client: httpx.AsyncClient | None = None) -> int:
    """Capture the NB1 forecast unless this UTC hour already has a worker capture. Returns records written.

    ``now`` (tests only) fixes both the hour check and the issue time; otherwise
    the issue time is taken right after the response, as the scheduled task does.
    """
    if captured_this_hour(path, now or datetime.now(timezone.utc)):
        return 0
    payload = await fetch_point(latitude, longitude, client)
    retrieved_at = now or datetime.now(timezone.utc)
    return append_records(path, build_records(payload, station, nb1_location(latitude, longitude), retrieved_at))

