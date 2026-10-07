"""Append-only, research-only as-issued external forecast snapshot store."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.weather import _fetch_open_meteo
from core.config import weather_location_for_station


def snapshot_id(record: dict) -> str:
    key = "|".join(str(record.get(k, "")) for k in ("station", "provider", "issued_at", "valid_at", "product"))
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def append_snapshot(path: Path, record: dict) -> bool:
    """Write immutable records once; this is not read by runtime models."""
    record = dict(record); record["snapshot_id"] = snapshot_id(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and any(json.loads(line).get("snapshot_id") == record["snapshot_id"] for line in path.read_text(encoding="utf-8").splitlines() if line):
        return False
    payload = json.dumps(record, sort_keys=True, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as stream: stream.write(payload + "\n")
    return True


def capture_open_meteo(station: str, output: Path) -> int:
    location = weather_location_for_station(station)
    if not location:
        raise ValueError("station_coordinates_missing")
    
    # R2 compliance
    payload = _fetch_open_meteo(location)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    issued_at = datetime.now(timezone.utc).isoformat()
    
    hourly = payload.get("hourly", {}); times = hourly.get("time", [])
    provider_timezone = payload.get("timezone", "Asia/Ho_Chi_Minh")
    payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    written = 0
    fields = ("temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m", "wind_direction_10m", "cloud_cover", "surface_pressure")
    for index, provider_valid_at in enumerate(times):
        valid_at = datetime.fromisoformat(provider_valid_at)
        if valid_at.tzinfo is None:
            valid_at = valid_at.replace(tzinfo=ZoneInfo(provider_timezone))
        valid_at_utc = valid_at.astimezone(timezone.utc).isoformat()
        features = {name: hourly.get(name, [None] * len(times))[index] for name in fields}
        
        record = {
            "station": station, 
            "station_id": station,
            "provider": "open_meteo", 
            "product": payload.get("model", "open_meteo_forecast"), 
            "source_timezone": provider_timezone, 
            "issued_at": issued_at, 
            "valid_at": valid_at_utc, 
            "retrieved_at": retrieved_at, 
            "provider_run_at": None,
            "location": location, 
            "location_id": location.get("source", "unknown"),
            "units": payload.get("hourly_units", {}),
            "raw_payload_hash": payload_hash, 
            "features": features, 
            "provenance_class": "captured_live",
            "research_only": True
        }
        written += append_snapshot(output, record)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--station", required=True); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); print({"written": capture_open_meteo(args.station, args.output)})


if __name__ == "__main__":
    main()
