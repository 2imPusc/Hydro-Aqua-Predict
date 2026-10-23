"""Reconstructed weather snapshots (decisions #13) and modelled sea level for one station.

Weather: Open-Meteo Previous Runs API gives, for each valid hour t, the value forecast by the
run of N days earlier (``<var>_previous_dayN``). We do not know when that run was published, so
availability is set conservatively to the END of the run day plus a safety lag:
    retrieved_at = floor_day(t) - N days + 1 day + LAG
This can only make a bulletin look later than it really was, never earlier. Records carry
``provenance_class = "reconstructed_run"`` and live in their own JSONL, never mixed with
captured_live snapshots.

Sea level: Open-Meteo Marine ``sea_level_height_msl`` (model tide + surge) at the station, hourly.
Treated as a known-in-advance driver for the B6 tide experiment (astronomical tide is predictable);
the surge part is a small, labelled approximation.

    python experiments/reconstruct_external_context.py --station 06M26042804 --start 2026-05-28 --end 2026-10-15
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.config import weather_location_for_station  # noqa: E402

VARIABLES = ("temperature_2m", "relative_humidity_2m", "precipitation", "cloud_cover", "surface_pressure",
             "wind_speed_10m", "wind_direction_10m")
LEADS = (1, 2, 3)
LAG = pd.Timedelta(hours=12)


def availability(valid_at: pd.Series, lead_days: int, lag: pd.Timedelta = LAG) -> pd.Series:
    return valid_at.dt.floor("D") - pd.Timedelta(days=lead_days) + pd.Timedelta(days=1) + lag


def to_records(hourly: pd.DataFrame, station: str, location: dict, lead_days: int) -> list[dict]:
    """One snapshot record per valid hour for one lead, in the captured_live schema."""
    valid = pd.to_datetime(hourly["time"], utc=True)
    avail = availability(valid, lead_days)
    records = []
    for i in range(len(hourly)):
        features = {v: hourly[f"{v}_previous_day{lead_days}"].iloc[i] for v in VARIABLES}
        if all(pd.isna(x) for x in features.values()):
            continue
        features = {k: (None if pd.isna(x) else float(x)) for k, x in features.items()}
        record = {
            "station": station, "location_id": location.get("source", "unknown"), "location": location,
            "provider": "open_meteo", "product": "open_meteo_forecast",
            "issued_at": avail.iloc[i].isoformat(), "retrieved_at": avail.iloc[i].isoformat(),
            "valid_at": valid.iloc[i].isoformat(), "provider_run_at": None, "lead_days": lead_days,
            "availability_rule": f"end_of_run_day_plus_{int(LAG.total_seconds() // 3600)}h",
            "provenance_class": "reconstructed_run", "research_only": True, "features": features,
        }
        record["raw_payload_hash"] = hashlib.sha256(json.dumps(features, sort_keys=True).encode()).hexdigest()
        records.append(record)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--station", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args(argv)
    location = weather_location_for_station(args.station)
    out = paths.EXPERIMENT_OUTPUT_DIR / f"external-context-{args.station}-{args.start}_{args.end}"
    if out.exists():
        print(f"exists, not overwritten: {out}")
        return 1

    hourly_vars = [f"{v}_previous_day{n}" for v in VARIABLES for n in LEADS]
    weather = requests.get("https://previous-runs-api.open-meteo.com/v1/forecast", params={
        "latitude": location["latitude"], "longitude": location["longitude"], "hourly": ",".join(hourly_vars),
        "start_date": args.start, "end_date": args.end, "timezone": "UTC"}, timeout=300).json()["hourly"]
    weather = pd.DataFrame(weather)
    marine = requests.get("https://marine-api.open-meteo.com/v1/marine", params={
        "latitude": location["latitude"], "longitude": location["longitude"], "hourly": "sea_level_height_msl",
        "start_date": args.start, "end_date": args.end, "timezone": "UTC", "cell_selection": "sea"}, timeout=300).json()

    out.mkdir(parents=True)
    records = [r for n in LEADS for r in to_records(weather, args.station, location, n)]
    with (out / "weather-snapshots-reconstructed.jsonl").open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    sea = pd.DataFrame({"valid_at": pd.to_datetime(marine["hourly"]["time"], utc=True),
                        "sea_level_m": marine["hourly"]["sea_level_height_msl"]})
    sea.to_csv(out / "sea_level_openmeteo_marine.csv", index=False)
    manifest = {"station": args.station, "location": location, "start": args.start, "end": args.end,
                "weather_records": len(records), "leads_days": LEADS, "lag_hours": LAG.total_seconds() / 3600,
                "marine_grid_point": [marine.get("latitude"), marine.get("longitude")],
                "sea_level_non_null": int(sea.sea_level_m.notna().sum()), "decision": "decisions #13"}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
