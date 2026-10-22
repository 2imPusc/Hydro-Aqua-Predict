"""Write-once downloads of public hazard data into paths.HAZARD_DATA_DIR.

    python experiments/hazard_data.py ibtracs --subset WP
    python experiments/hazard_data.py ibtracs --subset last3years
    python experiments/hazard_data.py oisst --start-year 1982   # NOAA PSL THREDDS NCSS, daily 0.25 deg
    python experiments/hazard_data.py marine-sst --start 2023-07-01
    python experiments/hazard_data.py era5 --start-year 1982 --model era5 --end 2026-10-16

``era5`` pins the Open-Meteo archive model (``models=``). Without it the archive serves
``best_match`` = ERA5 only before 2017 and ECMWF IFS (9 km, operational) from 2017 on; the legacy
file ``era5/era5_nb1_1982_20261020.csv`` was fetched that way and is best_match, NOT ERA5.
True ERA5 lags ~5 days, so pass ``--end`` = last available day.

Every file gets a sidecar ``<name>.manifest.json`` (url, sha256, fetched_at). An existing file
is never overwritten: files carry the download date in their name.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
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
# NOAA PSL THREDDS NetCDF Subset Service, one file per year (1981-09 -> near present).
OISST_URL = ("https://psl.noaa.gov/thredds/ncss/grid/Datasets/noaa.oisst.v2.highres/sst.day.mean.{year}.nc?"
             "var=sst&latitude={lat}&longitude={lon}&time_start={start}T00:00:00Z&time_end={end}T00:00:00Z&accept=csv")
# Nearest non-land-masked OISST cell to NB1 (checked 2026-10-22; 20.875 N is land).
OISST_CELL = (20.625, 107.125)
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ARCHIVE_MODELS = ("era5", "era5_seamless", "best_match")


def write_once(target: Path, payload: bytes, url: str, extra: dict | None = None) -> dict:
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    meta = {"file": target.name, "url": url, "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "fetched_at": datetime.now(timezone.utc).isoformat(), **(extra or {})}
    Path(f"{target}.manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def parse_psl_ncss_csv(text: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text))
    sst_col = next(c for c in df.columns if c.split("[")[0] == "sst")
    return pd.Series(pd.to_numeric(df[sst_col], errors="coerce").to_numpy(),
                     index=pd.to_datetime(df["time"], utc=True), name="sst")


def _get(url: str, params: dict | None = None, timeout: int = 180) -> requests.Response:
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp


def fetch_ibtracs(subset: str) -> dict:
    url = IBTRACS_URL.format(subset=subset)
    target = paths.HAZARD_DATA_DIR / "ibtracs" / f"ibtracs.{subset}.list.v04r01.{date.today():%Y%m%d}.csv"
    return write_once(target, _get(url, timeout=600).content, url)


def _oisst_windows(start_year: int, end: date) -> list[tuple[int, date, date]]:
    """Quarter-year request windows: the PSL proxy 502s past ~60 s (~0.3 s per day requested)."""
    out = []
    for year in range(start_year, end.year + 1):
        for q in range(4):
            first = date(year, 3 * q + 1, 1)
            last = date(year, 3 * q + 3, [31, 30, 30, 31][q])
            if first <= end:
                out.append((year, first, min(last, end)))
    return out


def _fetch_oisst_window(year: int, first: date, last: date, lat: float, lon: float, tries: int = 4) -> pd.Series:
    url = OISST_URL.format(year=year, start=first.isoformat(), end=last.isoformat(), lat=lat, lon=lon)
    for attempt in range(tries):
        try:
            return parse_psl_ncss_csv(_get(url, timeout=120).text)
        except requests.RequestException:
            if attempt == tries - 1:
                raise
            time.sleep(5 * (attempt + 1))


def fetch_oisst(start_year: int, end: date) -> dict:
    lat, lon = OISST_CELL
    windows = _oisst_windows(start_year, end)
    urls = [OISST_URL.format(year=y, start=f.isoformat(), end=e.isoformat(), lat=lat, lon=lon) for y, f, e in windows]
    with ThreadPoolExecutor(max_workers=4) as pool:
        parts = list(pool.map(lambda w: _fetch_oisst_window(*w, lat, lon), windows))
    series = pd.concat(parts).sort_index()
    target = paths.HAZARD_DATA_DIR / "sst" / f"oisst_{lat}_{lon}_{start_year}_{end:%Y%m%d}.csv"
    series.index = series.index.strftime("%Y-%m-%dT%H:%M:%SZ")
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


def fetch_era5(start_year: int, end: date, model: str = "era5") -> dict:
    if model not in ARCHIVE_MODELS:
        raise ValueError(f"model must be one of {ARCHIVE_MODELS}: {model}")
    loc = weather_location_for_station(STATION)
    params = {"latitude": loc["latitude"], "longitude": loc["longitude"], "models": model,
              "hourly": "temperature_2m,wind_speed_10m,wind_gusts_10m", "wind_speed_unit": "ms", "timezone": "GMT"}
    chunks = [(f"{y}-01-01", min(date(y, 12, 31), end).isoformat()) for y in range(start_year, end.year + 1)]
    df = _open_meteo_hourly(ARCHIVE_URL, params, chunks)
    target = paths.HAZARD_DATA_DIR / "era5" / f"openmeteo_{model}_nb1_{start_year}_{end:%Y%m%d}.csv"
    return write_once(target, df.to_csv(index=False).encode(), ARCHIVE_URL, extra={"model": model})


# Legacy archive file fetched 2026-10-22 without ``models=`` -> best_match (ERA5 <2017, IFS 9 km >=2017).
LEGACY_BEST_MATCH_GLOB = "era5_nb1_*.csv"


def latest_era5(model: str = "era5") -> Path:
    """Newest archive file for ``model``; the legacy unlabelled file only ever counts as best_match."""
    files = sorted((paths.HAZARD_DATA_DIR / "era5").glob(f"openmeteo_{model}_nb1_*.csv"))
    if not files and model == "best_match":
        files = sorted((paths.HAZARD_DATA_DIR / "era5").glob(LEGACY_BEST_MATCH_GLOB))
    if not files:
        raise FileNotFoundError(f"no archive file for model={model}: run experiments/hazard_data.py era5 --model {model}")
    return files[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ibtracs").add_argument("--subset", choices=["WP", "last3years", "ACTIVE"], required=True)
    for name in ("oisst", "era5"):
        p = sub.add_parser(name)
        p.add_argument("--start-year", type=int, default=1982)
    sub.choices["era5"].add_argument("--model", choices=ARCHIVE_MODELS, default="era5")
    sub.add_parser("marine-sst").add_argument("--start", default="2023-07-01")
    for p in sub.choices.values():
        p.add_argument("--end", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)
    if args.cmd == "ibtracs":
        meta = fetch_ibtracs(args.subset)
    elif args.cmd == "oisst":
        meta = fetch_oisst(args.start_year, args.end)
    elif args.cmd == "era5":
        meta = fetch_era5(args.start_year, args.end, model=args.model)
    else:
        meta = fetch_marine_sst(args.start, args.end)
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
