"""Build an explicitly leaky weather-oracle upper bound for diagnosis only.

At issue hour H it exposes *realized* weather in H, H+1, and H+2.  These
records intentionally violate availability and must never be reported as
as-issued, used in a research gate, or deployed.  Their only purpose is to
answer whether perfectly known near-future weather could help sensor forecast.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.config import weather_location_for_station
from experiments.forecast_pseudo_as_issued_weather import FIELDS, fetch_archive
from experiments.forecast_snapshot_store import snapshot_id
from experiments.forecast_sensor_v2 import load_sensor_data


def build_oracle_snapshots(weather: pd.DataFrame, station: str, location: dict, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if output.exists():
        existing = {json.loads(line).get("snapshot_id") for line in output.read_text(encoding="utf-8").splitlines() if line.strip()}
    written = 0
    with output.open("a", encoding="utf-8") as stream:
        for issue_at in weather.index:
            for lead_hour in (0, 1, 2):
                valid_at = issue_at + pd.Timedelta(hours=lead_hour)
                if valid_at not in weather.index:
                    continue
                features = {field: float(weather.at[valid_at, field]) for field in FIELDS}
                raw_hash = hashlib.sha256(json.dumps({"valid_at": valid_at.isoformat(), "realized_weather": features}, sort_keys=True).encode()).hexdigest()
                record = {"station": station, "provider": "open_meteo_archive_oracle", "product": "oracle_realized_weather_upper_bound_v1", "issued_at": issue_at.isoformat(), "valid_at": valid_at.isoformat(), "retrieved_at": issue_at.isoformat(), "location": location, "raw_payload_hash": raw_hash, "features": features, "research_only": True, "oracle_leakage": True, "availability_rule": "INTENTIONALLY_LEAKY_realized_weather_at_valid_time"}
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
    weather = fetch_archive(location, raw.fetchedAt.min().date().isoformat(), raw.fetchedAt.max().date().isoformat())
    written = build_oracle_snapshots(weather, args.station, location, args.output)
    print(json.dumps({"written": written, "label": "ORACLE_LEAKAGE_UPPER_BOUND_ONLY", "weather_start": str(weather.index.min()), "weather_end": str(weather.index.max())}))


if __name__ == "__main__":
    main()
