"""Download a regional subset of GEBCO_2024 (15 arc-second) plus its Type Identifier (TID) grid (write-once).

Source: BODC / CEDA archive, the 90x90 degree GeoTIFF tiles ``n90.0_s0.0_w90.0_e180.0`` of
  * sub-ice topography/bathymetry (int16, m, relative to mean sea level; -32767 = nodata)
  * type identifier grid (int8; 0 land, 10-17 direct measurement, 40-45 interpolated/predicted)
Both are read with HTTP range requests through GDAL ``/vsicurl/`` (rasterio), so only the
rows of the bbox are transferred (a few MB), not the 0.9 GB / 0.47 GB tiles. No credentials.
Licence: GEBCO Grid is public domain, attribution required (see manifest).

Output (never overwritten; refuses if present):
  data/depth/gebco2024-<YYYYMMDD>/gebco2024_15s_hp_qn.nc     lat/lon/elevation/tid subset
  data/depth/gebco2024-<YYYYMMDD>/gebco2024_15s_hp_qn.json   manifest (urls, sha256, bbox, version, licence)

Usage: python scripts/download_gebco2024_bathymetry.py [--dry-run]
Needs rasterio (research-map backend venv) and xarray + h5netcdf.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402

CEDA = "https://dap.ceda.ac.uk/bodc/gebco/global/gebco_2024"
TILE = "n90.0_s0.0_w90.0_e180.0"
ELEVATION_URL = f"{CEDA}/sub_ice_topography_bathymetry/geotiff/gebco_2024_sub_ice_{TILE}.tif"
TID_URL = f"{CEDA}/type_identifier_grid/geotiff/gebco_2024_tid_{TILE}.tif"
BBOX = (106.50, 20.30, 108.20, 21.60)  # min_lon, min_lat, max_lon, max_lat (same as the ETOPO subset)
NAME = "gebco2024_15s_hp_qn"
NODATA = -32767
CITATION = ("GEBCO Compilation Group (2024) GEBCO 2024 Grid (doi:10.5285/1c44ce99-0a0d-5f4f-e063-7086abc0ea0f). "
            "Type Identifier grid from the same release.")
LICENCE = ("GEBCO Grid: public domain, no restrictions on use; acknowledge the source as "
           "'GEBCO Compilation Group (2024) GEBCO 2024 Grid'. Not to be used for navigation.")


def _read(url: str):
    import rasterio
    from rasterio.windows import from_bounds
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
        with rasterio.open(f"/vsicurl/{url}") as src:
            window = from_bounds(*BBOX, src.transform).round_offsets().round_lengths()
            data = src.read(1, window=window)
            transform = src.window_transform(window)
    ny, nx = data.shape
    lon = transform.c + transform.a * (np.arange(nx) + 0.5)
    lat = transform.f + transform.e * (np.arange(ny) + 0.5)  # descending
    return data, lon, lat, {"col_off": int(window.col_off), "row_off": int(window.row_off),
                            "width": int(window.width), "height": int(window.height)}


def fetch() -> tuple[xr.Dataset, dict]:
    elevation, lon, lat, window = _read(ELEVATION_URL)
    tid, lon_t, lat_t, _ = _read(TID_URL)
    if elevation.shape != tid.shape or not (np.allclose(lon, lon_t) and np.allclose(lat, lat_t)):
        raise RuntimeError("elevation and TID windows differ")
    z = np.where(elevation == NODATA, np.nan, elevation).astype("float32")
    ds = xr.Dataset(
        {"elevation": (("lat", "lon"), z[::-1], {"units": "m", "positive": "up", "long_name": "GEBCO_2024 elevation (sub-ice)"}),
         "tid": (("lat", "lon"), tid[::-1].astype("int8"), {"long_name": "GEBCO_2024 Type Identifier"})},
        coords={"lat": lat[::-1], "lon": lon})
    ds.attrs.update({"source": "GEBCO_2024 Grid (15 arc-second) + TID grid", "citation": CITATION, "licence": LICENCE,
                     "comment": "Research visualization only; not for navigation."})
    return ds, {"window": window, "shape": list(z.shape)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    subdir = f"gebco2024-{datetime.now(timezone.utc):%Y%m%d}"
    folder = paths.DEPTH_DIR / subdir
    target, meta_path = folder / f"{NAME}.nc", folder / f"{NAME}.json"
    if target.exists() or meta_path.exists():
        print(f"exists, skipped (write-once): {target}")
        return 0
    if args.dry_run:
        print("->", target)
        return 0
    ds, meta = fetch()
    heads = {url: requests.head(url, timeout=60, allow_redirects=True).headers for url in (ELEVATION_URL, TID_URL)}
    target.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(target, engine="h5netcdf")
    z, tid = ds.elevation.values, ds.tid.values
    meta.update({
        "file": target.name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "bbox": BBOX,
        "retrieved_at": datetime.now(timezone.utc).isoformat(), "version": "GEBCO_2024",
        "method": "HTTP range reads of 90x90 deg GeoTIFF tiles via GDAL /vsicurl/ (rasterio); no credentials",
        "source_urls": {"elevation": ELEVATION_URL, "tid": TID_URL},
        "source_remote": {k: {"content_length": h.get("Content-Length"), "last_modified": h.get("Last-Modified")} for k, h in heads.items()},
        "source": ds.attrs["source"], "citation": CITATION, "licence": LICENCE,
        "resolution": "15 arc-second (~460 m)", "vertical_datum": "mean sea level (GEBCO), not chart datum",
        "tid_legend": {"0": "land", "10-17": "direct measurement", "40-45": "interpolated / predicted / pre-generated grid"},
        "sea_cells": int(np.sum(z < 0)), "min_z": float(np.nanmin(z)), "max_z": float(np.nanmax(z)),
        "tid_counts_sea": {str(int(v)): int(c) for v, c in zip(*np.unique(tid[z < 0], return_counts=True))},
    })
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"wrote {target} ({z.shape}, sea cells {meta['sea_cells']}, min {meta['min_z']:.1f} m)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
