"""Create causally replayed, *pseudo* as-issued hourly weather forecasts.

The Open-Meteo archive supplies historical observations only as a source for
the replay.  For an issue hour H, every forecast feature is calculated solely
from observations at or before H-1; no actual weather at H or later is used.
This is exploratory and is not a replay of forecasts actually issued by a
provider.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.config import weather_location_for_station
from experiments.forecast_snapshot_store import snapshot_id
from experiments.forecast_sensor_v2 import load_sensor_data

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FIELDS = ("temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m", "wind_direction_10m", "cloud_cover", "surface_pressure")


def fetch_archive(location: dict, start: str, end: str) -> pd.DataFrame:
    query = urlencode({"latitude": location["latitude"], "longitude": location["longitude"], "start_date": start, "end_date": end, "hourly": ",".join(FIELDS), "timezone": "Asia/Ho_Chi_Minh"})
    with urlopen(f"{ARCHIVE_URL}?{query}", timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    weather = pd.DataFrame(payload["hourly"])
    weather["time"] = pd.to_datetime(weather["time"]).dt.tz_localize(payload.get("timezone", "Asia/Ho_Chi_Minh")).dt.tz_convert("UTC")
    return weather.set_index("time").sort_index()[list(FIELDS)]


def build_pseudo_snapshots(weather: pd.DataFrame, station: str, location: dict, output: Path) -> int:
    """Issue persistence forecasts for the current and next two valid hours."""
    known_completed_hour = weather.shift(1)
    output.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if output.exists():
        existing = {json.loads(line).get("snapshot_id") for line in output.read_text(encoding="utf-8").splitlines() if line.strip()}
    written = 0
    with output.open("a", encoding="utf-8") as stream:
        for issue_at, values in known_completed_hour.dropna().iterrows():
            features = {field: float(values[field]) for field in FIELDS}
            source_hash = hashlib.sha256(json.dumps({"issue_at": issue_at.isoformat(), "completed_weather": features}, sort_keys=True).encode()).hexdigest()
            for lead_hour in (0, 1, 2):
                record = {"station": station, "provider": "open_meteo_archive_replay", "product": "pseudo_as_issued_persistence_v1", "issued_at": issue_at.isoformat(), "valid_at": (issue_at + pd.Timedelta(hours=lead_hour)).isoformat(), "retrieved_at": issue_at.isoformat(), "location": location, "raw_payload_hash": source_hash, "features": features, "research_only": True, "pseudo_as_issued": True, "availability_rule": "weather_observed_through_previous_completed_hour"}
                record["snapshot_id"] = snapshot_id(record)
                if record["snapshot_id"] not in existing:
                    stream.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
                    existing.add(record["snapshot_id"])
                    written += 1
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("telemetry", type=Path); parser.add_argument("--station", required=True); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    location = weather_location_for_station(args.station)
    if not location:
        raise ValueError("station_coordinates_missing")
    raw = load_sensor_data(args.telemetry, args.station)
    start = raw.fetchedAt.min().date().isoformat(); end = raw.fetchedAt.max().date().isoformat()
    weather = fetch_archive(location, start, end)
    written = build_pseudo_snapshots(weather, args.station, location, args.output)
    print(json.dumps({"written": written, "weather_start": str(weather.index.min()), "weather_end": str(weather.index.max()), "label": "pseudo_as_issued_exploratory"}))


if __name__ == "__main__":
    main()
