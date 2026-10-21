"""Write-once downloads of public hazard data into paths.HAZARD_DATA_DIR.

    python experiments/hazard_data.py ibtracs --subset WP
    python experiments/hazard_data.py ibtracs --subset last3years
    python experiments/hazard_data.py oisst --start-year 1982
    python experiments/hazard_data.py marine-sst --start 2023-07-01
    python experiments/hazard_data.py era5 --start-year 1982

Every file gets a sidecar ``<name>.manifest.json`` (url, sha256, fetched_at). An existing file
is never overwritten: files carry the download date in their name.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.config import weather_location_for_station  # noqa: E402

STATION = "06M26042804"
IBTRACS_URL = ("https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/"
               "v04r01/access/csv/ibtracs.{subset}.list.v04r01.csv")
OISST_URL = ("https://www.ncei.noaa.gov/erddap/griddap/ncdc_oisst_v2_avhrr_by_time_zlev_lat_lon.csv?"
             "sst%5B({start}T12:00:00Z):1:({end}T12:00:00Z)%5D%5B(0.0)%5D%5B({lat})%5D%5B({lon})%5D")
# Nearest non-land-masked OISST cell to NB1 (checked 2026-10-22; 20.875 N is land).
OISST_CELL = (20.625, 107.125)
# This NCEI ERDDAP dataset only starts 2020-02-28 (checked 2026-10-22); earlier requests 404.
# Pre-2020 history needs another host (coastwatch.pfeg timed out), so it is clamped here.
OISST_MIN_DATE = date(2020, 2, 28)
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def write_once(target: Path, payload: bytes, url: str) -> dict:
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    meta = {"file": target.name, "url": url, "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "fetched_at": datetime.now(timezone.utc).isoformat()}
    Path(f"{target}.manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def parse_erddap_csv(text: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text), skiprows=[1])
    return pd.Series(pd.to_numeric(df["sst"], errors="coerce").to_numpy(),
                     index=pd.to_datetime(df["time"], utc=True), name="sst")


def _get(url: str, params: dict | None = None, timeout: int = 180) -> requests.Response:
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp


def fetch_ibtracs(subset: str) -> dict:
    url = IBTRACS_URL.format(subset=subset)
    target = paths.HAZARD_DATA_DIR / "ibtracs" / f"ibtracs.{subset}.list.v04r01.{date.today():%Y%m%d}.csv"
    return write_once(target, _get(url, timeout=600).content, url)


def fetch_oisst(start_year: int, end: date) -> dict:
    lat, lon = OISST_CELL
    parts, urls = [], []
    for year in range(start_year, end.year + 1):
        stop = min(date(year, 12, 31), end)
        first = max(date(year, 1, 1), OISST_MIN_DATE)
        if first > stop:
            continue
        url = OISST_URL.format(start=first.isoformat(), end=stop.isoformat(), lat=lat, lon=lon)
        urls.append(url)
        parts.append(parse_erddap_csv(_get(url).text))
    series = pd.concat(parts).sort_index()
    target = paths.HAZARD_DATA_DIR / "sst" / f"oisst_{lat}_{lon}_{start_year}_{end:%Y%m%d}.csv"
    return write_once(target, series.rename("sst").to_csv(index_label="time").encode(), urls[0])


def _open_meteo_hourly(url: str, params: dict, chunks: list[tuple[str, str]]) -> pd.DataFrame:
    frames = []
    for start, stop in chunks:
        data = _get(url, {**params, "start_date": start, "end_date": stop}).json()
        frames.append(pd.DataFrame(data["hourly"]))
    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize("UTC")
    return df


def fetch_marine_sst(start: str, end: date) -> dict:
    loc = weather_location_for_station(STATION)
    params = {"latitude": loc["latitude"], "longitude": loc["longitude"], "hourly": "sea_surface_temperature,wave_height",
              "cell_selection": "sea", "timezone": "GMT"}
    df = _open_meteo_hourly(MARINE_URL, params, [(start, end.isoformat())])
    target = paths.HAZARD_DATA_DIR / "sst" / f"openmeteo_marine_nb1_{start.replace('-', '')}_{end:%Y%m%d}.csv"
    return write_once(target, df.to_csv(index=False).encode(), MARINE_URL)


def fetch_era5(start_year: int, end: date) -> dict:
    loc = weather_location_for_station(STATION)
    params = {"latitude": loc["latitude"], "longitude": loc["longitude"],
              "hourly": "temperature_2m,wind_speed_10m,wind_gusts_10m", "wind_speed_unit": "ms", "timezone": "GMT"}
    chunks = [(f"{y}-01-01", min(date(y, 12, 31), end).isoformat()) for y in range(start_year, end.year + 1)]
    df = _open_meteo_hourly(ARCHIVE_URL, params, chunks)
    target = paths.HAZARD_DATA_DIR / "era5" / f"era5_nb1_{start_year}_{end:%Y%m%d}.csv"
    return write_once(target, df.to_csv(index=False).encode(), ARCHIVE_URL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ibtracs").add_argument("--subset", choices=["WP", "last3years", "ACTIVE"], required=True)
    for name in ("oisst", "era5"):
        p = sub.add_parser(name)
        p.add_argument("--start-year", type=int, default=1982)
    sub.add_parser("marine-sst").add_argument("--start", default="2023-07-01")
    for p in sub.choices.values():
        p.add_argument("--end", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)
    if args.cmd == "ibtracs":
        meta = fetch_ibtracs(args.subset)
    elif args.cmd == "oisst":
        meta = fetch_oisst(args.start_year, args.end)
    elif args.cmd == "era5":
        meta = fetch_era5(args.start_year, args.end)
    else:
        meta = fetch_marine_sst(args.start, args.end)
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
