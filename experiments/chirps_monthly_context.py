"""Extract causal prior-month CHIRPS rainfall at historical Hai Phong stations.

The quarterly observation month is never read.  Each row receives precipitation
from the immediately preceding completed calendar month only.  This source is
for retrospective context research, not minute-level or as-issued forecasting.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path

import pandas as pd
import rasterio
import requests
from pyproj import Proj
from rasterio.io import MemoryFile

HP_PROJ = Proj(proj="tmerc", lat_0=0, lon_0=105.75, k=0.9999, x_0=500000, y_0=0, ellps="WGS84", towgs84="-191.90441429,-39.30318279,-111.45032835,-0.00928836,0.01975479,-0.00427372,0.252906278")
URL = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_monthly/tifs/chirps-v2.0.{year:04d}.{month:02d}.tif.gz"


def station_coordinates(frame: pd.DataFrame) -> pd.DataFrame:
    stations = frame[["Station", "X", "Y"]].drop_duplicates("Station").copy()
    lon, lat = HP_PROJ(stations.Y.to_numpy(float), stations.X.to_numpy(float), inverse=True)
    stations["latitude"], stations["longitude"] = lat, lon
    return stations


def sample_month(year: int, month: int, stations: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    url = URL.format(year=year, month=month)
    response = requests.get(url, timeout=90)
    response.raise_for_status()
    raw_hash = hashlib.sha256(response.content).hexdigest()
    with MemoryFile(gzip.decompress(response.content)) as memory:
        with memory.open() as raster:
            values = [item[0] for item in raster.sample(list(zip(stations.longitude, stations.latitude)))]
            nodata = raster.nodata
    out = stations[["Station"]].copy(); out["chirps_rain_prev_month_mm"] = [None if value == nodata else float(value) for value in values]
    return out, {"url": url, "sha256": raw_hash, "year": year, "month": month}


def build(source: Path, output: Path) -> pd.DataFrame:
    frame = pd.read_csv(source); frame["Quarter"] = pd.to_datetime(frame["Quarter"])
    stations = station_coordinates(frame)
    periods = sorted((date.to_period("M") - 1 for date in frame.Quarter.unique()))
    cached: dict[pd.Period, pd.DataFrame] = {}; provenance = []
    for period in periods:
        values, record = sample_month(period.year, period.month, stations)
        cached[period] = values.set_index("Station"); provenance.append(record)
    frame["_prior_month"] = frame.Quarter.dt.to_period("M") - 1
    frame["chirps_rain_prev_month_mm"] = [cached[period].loc[station, "chirps_rain_prev_month_mm"] for station, period in zip(frame.Station, frame._prior_month)]
    frame = frame.drop(columns="_prior_month")
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    output.with_suffix(".manifest.json").write_text(json.dumps({"provider": "CHIRPS-2.0", "context": "previous_completed_month_only", "exploratory_only": True, "downloads": provenance}, indent=2), encoding="utf-8")
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--source", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); result = build(args.source, args.output)
    print({"rows": len(result), "missing_rain": int(result.chirps_rain_prev_month_mm.isna().sum())})


if __name__ == "__main__":
    main()
