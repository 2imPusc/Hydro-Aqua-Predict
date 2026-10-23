"""ECMWF TIGGE tropical-cyclone track forecasts (CXML) for the western North Pacific.

Source: NCAR GDEX/RDA dataset d330003 ("TIGGE Model Tropical Cyclone Track Data"), served
anonymously through the OSDF HTTPS cache (probed 2026-10-23, no login needed):
    https://osdf-director.osg-htc.org/ncar/rda/d330003/ecmf/<YYYY>/<YYYYMMDD>/z_tigge_c_ecmf_<YYYYMMDDHH>0000_ifs_glob_prod_all_glo.xml
One file per run (~9 MB, global): analysis, HRES ("forecast"), control + 50 perturbed members.
Licence: CC BY 4.0, non-commercial research use.

    python experiments/tigge_tracks.py fetch --start 2024-05-01 --end 2024-12-15 --hour 0

Only disturbances whose analysis/first fix lies in 0-45 N, 95-180 E are kept.  The raw XML is
NOT stored (space); the write-once output is one CSV of extracted fixes plus a manifest that
lists every source URL with its sha256 and size, so each row is traceable.  Parsed days are
cached in the session scratch directory (``--cache``) so an interrupted fetch can resume.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from experiments.hazard_data import write_once  # noqa: E402

BASE_URL = "https://osdf-director.osg-htc.org/ncar/rda/d330003/ecmf"
FILE_FMT = "z_tigge_c_ecmf_{stamp}0000_ifs_glob_prod_all_glo.xml"
WP_BOX = (0.0, 45.0, 95.0, 180.0)  # lat_min, lat_max, lon_min, lon_max
COLUMNS = ["base_time", "member", "disturbance_id", "name", "number", "hour", "valid_time", "lat", "lon",
           "pmin_hpa", "vmax_ms"]


def run_url(day: date, hour: int) -> str:
    stamp = f"{day:%Y%m%d}{hour:02d}"
    return f"{BASE_URL}/{day:%Y}/{day:%Y%m%d}/{FILE_FMT.format(stamp=stamp)}"


def _lon_east(text: str, units: str) -> float:
    v = float(text)
    if "W" in (units or "") and v > 0:
        v = -v
    return v % 360.0


def _lat_north(text: str, units: str) -> float:
    v = float(text)
    if "S" in (units or "") and v > 0:
        v = -v
    return v


def _member_label(data: ET.Element) -> str | None:
    kind = data.get("type")
    if kind == "forecast":
        return "hres"
    if kind == "ensembleForecast":
        return f"ens{int(data.get('member', '-1')):02d}"
    return None  # analysis / other: not a forecast


def parse_cxml(payload: bytes, box=WP_BOX) -> pd.DataFrame:
    """Forecast fixes (HRES + ensemble) of disturbances starting inside ``box``."""
    root = ET.parse(io.BytesIO(payload)).getroot()
    base = root.findtext("header/baseTime")
    rows = []
    for data in root.iter("data"):
        member = _member_label(data)
        if member is None:
            continue
        for dist in data.iter("disturbance"):
            fixes = []
            for fix in dist.iter("fix"):
                lat_el, lon_el = fix.find("latitude"), fix.find("longitude")
                if lat_el is None or lon_el is None or lat_el.text is None or lon_el.text is None:
                    continue
                speed = fix.findtext("cycloneData/maximumWind/speed")
                pres = fix.findtext("cycloneData/minimumPressure/pressure")
                fixes.append((int(fix.get("hour", "0")), fix.findtext("validTime"),
                              _lat_north(lat_el.text, lat_el.get("units")), _lon_east(lon_el.text, lon_el.get("units")),
                              float(pres) if pres else None, float(speed) if speed else None))
            if not fixes:
                continue
            lat0, lon0 = fixes[0][2], fixes[0][3]
            if not (box[0] <= lat0 <= box[1] and box[2] <= lon0 <= box[3]):
                continue
            for hour, valid, lat, lon, pres, speed in fixes:
                rows.append((base, member, dist.get("ID"), dist.findtext("cycloneName"), dist.findtext("cycloneNumber"),
                             hour, valid, lat, lon, pres, speed))
    return pd.DataFrame(rows, columns=COLUMNS)


def _fetch_day(day: date, hour: int, cache: Path, tries: int = 4) -> dict:
    cached = cache / f"{day:%Y%m%d}{hour:02d}.csv"
    meta_path = cache / f"{day:%Y%m%d}{hour:02d}.json"
    if cached.exists() and meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    url = run_url(day, hour)
    for attempt in range(tries):
        try:
            resp = requests.get(url, timeout=300)
            if resp.status_code == 404:
                meta = {"url": url, "status": 404}
                meta_path.write_text(json.dumps(meta), encoding="utf-8")
                return meta
            resp.raise_for_status()
            break
        except requests.RequestException:
            if attempt == tries - 1:
                return {"url": url, "status": "error"}
            time.sleep(5 * (attempt + 1))
    payload = resp.content
    df = parse_cxml(payload)
    df.to_csv(cached, index=False)
    meta = {"url": url, "status": 200, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
            "rows": int(len(df))}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return meta


def fetch(start: date, end: date, hour: int, cache: Path) -> dict:
    cache.mkdir(parents=True, exist_ok=True)
    metas, frames = [], []
    day = start
    while day <= end:
        run_hour = hour
        meta = _fetch_day(day, run_hour, cache)
        if meta.get("status") == 404:
            # a run file exists only when some TC is being tracked at that base time; fall back to +12 h
            metas.append(meta)
            run_hour = (hour + 12) % 24
            meta = _fetch_day(day, run_hour, cache)
        metas.append(meta)
        cached = cache / f"{day:%Y%m%d}{run_hour:02d}.csv"
        if meta.get("status") == 200 and cached.exists():
            frames.append(pd.read_csv(cached))
        print(day, meta.get("status"), meta.get("rows"), flush=True)
        day += timedelta(days=1)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
    fetched = datetime.now(timezone.utc)
    target = (paths.HAZARD_DATA_DIR / "tigge" /
              f"ecmf_cxml_wp_tracks_{start:%Y%m%d}_{end:%Y%m%d}_{hour:02d}z_fetched{fetched:%Y%m%d}.csv")
    return write_once(target, df.to_csv(index=False).encode(), f"{BASE_URL}/<YYYY>/<YYYYMMDD>/",
                      extra={"dataset": "NCAR GDEX d330003 TIGGE TC tracks (ECMWF), via OSDF anonymous HTTPS",
                             "run_selection": f"{hour:02d}Z daily; {(hour + 12) % 24:02d}Z when the {hour:02d}Z file is absent (404)",
                             "licence": "CC BY 4.0; non-commercial research",
                             "box": WP_BOX, "run_hour_utc": hour,
                             "raw_xml_stored": False,
                             "sources": metas})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--start", required=True, type=date.fromisoformat)
    f.add_argument("--end", required=True, type=date.fromisoformat)
    f.add_argument("--hour", type=int, default=0)
    f.add_argument("--cache", required=True, type=Path, help="scratch dir for per-day parsed CSV (resume)")
    args = ap.parse_args(argv)
    meta = fetch(args.start, args.end, args.hour, args.cache)
    print(json.dumps({k: v for k, v in meta.items() if k != "sources"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
