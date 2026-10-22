"""Download a regional subset of NOAA ETOPO 2022 15-arc-second relief (write-once).

Source: NOAA NCEI ETOPO 2022 v1, 15", "surface" tile N30E105 served over OPeNDAP
(THREDDS). Heights are metres relative to the EGM2008 geoid (~mean sea level), NOT
chart datum. Cell size 15" ~ 460 m: Ha Long / Bai Tu Long karst islets and narrow
channels are not resolved; in this area the sea part is largely inherited from GEBCO.

Output (never overwritten; refuses if present):
  data/depth/etopo2022-20261023/etopo2022_15s_hp_qn.nc        lat/lon/z subset
  data/depth/etopo2022-20261023/etopo2022_15s_hp_qn.json      provenance (url, index window, sha256, retrieved_at)

Usage: python scripts/download_etopo2022_bathymetry.py [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402

BASE = ("https://www.ngdc.noaa.gov/thredds/dodsC/global/ETOPO2022/15s/"
        "15s_surface_elev_netcdf/ETOPO_2022_v1_15s_N30E105_surface.nc")
# Hai Phong coast + Cat Ba + Ha Long + Bai Tu Long + Van Don / Co To (Quang Ninh).
BBOX = (106.50, 20.30, 108.20, 21.60)  # min_lon, min_lat, max_lon, max_lat
TILE_LAT0, TILE_LON0, STEP = 15.0 + 7.5 / 3600, 105.0 + 7.5 / 3600, 15 / 3600  # cell centres
NAME = "etopo2022_15s_hp_qn"
SUBDIR = "etopo2022-20261023"  # dated, write-once


def _window() -> tuple[int, int, int, int]:
    min_lon, min_lat, max_lon, max_lat = BBOX
    return (math.ceil((min_lat - TILE_LAT0) / STEP), math.floor((max_lat - TILE_LAT0) / STEP),
            math.ceil((min_lon - TILE_LON0) / STEP), math.floor((max_lon - TILE_LON0) / STEP))


def _parse_ascii_1d(text: str, name: str) -> np.ndarray:
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}["))
    return np.array([float(v) for v in lines[start + 1].split(",")])


def fetch() -> tuple[xr.Dataset, dict]:
    i0, i1, j0, j1 = _window()
    query = f"z[{i0}:1:{i1}][{j0}:1:{j1}],lat[{i0}:1:{i1}],lon[{j0}:1:{j1}]"
    url = f"{BASE}.ascii?{requests.utils.quote(query, safe=':,')}"
    response = requests.get(url, timeout=300)
    response.raise_for_status()
    text = response.text
    lat, lon = _parse_ascii_1d(text, "lat"), _parse_ascii_1d(text, "lon")
    body = text.split("z.z[", 1)[1].splitlines()[1:]
    rows = [[float(v) for v in line.split(",")[1:]] for line in body if line.startswith("[")][: len(lat)]
    z = np.array(rows, dtype="float32")
    if z.shape != (len(lat), len(lon)):
        raise RuntimeError(f"unexpected shape {z.shape} vs {(len(lat), len(lon))}")
    z = np.where(z <= -99990, np.nan, z)
    ds = xr.Dataset({"z": (("lat", "lon"), z, {"units": "m", "positive": "up", "vertical_datum": "EGM2008 geoid",
                                                    "long_name": "ETOPO 2022 15s surface elevation"})},
                    coords={"lat": lat, "lon": lon})
    ds.attrs.update({"source": "NOAA NCEI ETOPO 2022 v1 15 arc-second (surface)", "source_url": BASE,
                     "citation": "NOAA NCEI (2022). ETOPO 2022 15 Arc-Second Global Relief Model. doi:10.25921/fd45-gt74",
                     "comment": "Research visualization only; not for navigation. Heights vs EGM2008, not chart datum."})
    return ds, {"url": url, "index_window": {"lat": [i0, i1], "lon": [j0, j1]}, "shape": list(z.shape)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    folder = paths.DEPTH_DIR / SUBDIR
    target, meta_path = folder / f"{NAME}.nc", folder / f"{NAME}.json"
    if target.exists() or meta_path.exists():
        print(f"exists, skipped (write-once): {target}")
        return 0
    if args.dry_run:
        print("window", _window(), "->", target)
        return 0
    ds, meta = fetch()
    target.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(target, engine="h5netcdf")
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    z = ds.z.values
    meta.update({"file": target.name, "sha256": sha, "bbox": BBOX, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                 "source": ds.attrs["source"], "citation": ds.attrs["citation"], "resolution": "15 arc-second (~460 m)",
                 "vertical_datum": "EGM2008 geoid (~MSL), not chart datum",
                 "sea_cells": int(np.sum(z < 0)), "min_z": float(np.nanmin(z)), "max_z": float(np.nanmax(z))})
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"wrote {target} ({z.shape}, sea cells {meta['sea_cells']}, min {meta['min_z']:.1f} m)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
