"""GEBCO 2024 15" regional depth with TID-based confidence: isobands, isobaths, flags.

Same artifact shape as ``bathymetry_etopo`` (it reuses its contouring helpers) but the
source is the GEBCO_2024 grid *plus its Type Identifier (TID) grid*, which says what each
cell is based on.  Nothing here edits values.  Per band, confidence is one of:

* ``direct``   -- TID 10-17: depth from a direct measurement (single/multibeam, lidar, ...);
* ``indirect`` -- TID 40-45: interpolated / predicted / pre-generated grid;
* ``unknown``  -- any other TID, or land (TID 0) inside OSM water;
* ``coarse``   -- OSM water where the GEBCO cell is land (channels, karst islets);
* ``suspect``  -- >30 m basins not connected to the open Gulf that also stand >= 12 m above a shallow
  (< 25 m) surrounding and contain no direct sounding (stricter than ETOPO, RL-52).

``suspect`` and ``coarse`` win over the TID classes.  Geometry is clipped to the OSM
water mask.  Built write-once into ``<cache>/bathymetry-gebco/<key>/``; the API only reads.
Raw file: NetCDF with ``elevation`` (m, vs MSL) and ``tid`` (see
``scripts/download_gebco2024_bathymetry.py``).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from app.bathymetry_etopo import (
    BAND_EDGES, FLAG_THRESHOLD, ISOBATHS, LOD_MIN_AREA, LOD_TOLERANCE, SUSPECT_DEPTH_M, UPSAMPLE,
    _features, _filled_polygons, _fingerprint, _lines, _round_coordinates, _write_json,
    smooth, suspect_mask, upsample_bilinear,
)
from app.domain import water_geometry_for_bounds

GEBCO_ARTIFACT_VERSION = "gebco2024-15s-isobands-v3"  # v2: + slope classes; v3: stricter suspect holes
# Bottom-slope classes (degrees) from the ~460 m grid: it only resolves broad slopes, never narrow channels.
SLOPE_EDGES_DEG = (0.0, 0.5, 1.0, 2.0)
DIRECT_TID = range(10, 18)
INDIRECT_TID = range(40, 46)
CONFIDENCE_ORDER = ("suspect", "coarse", "direct", "indirect", "unknown")
DISCLAIMER = ("GEBCO_2024 15\" (~460 m) grid, heights vs mean sea level, not chart datum. Confidence from the TID grid: "
              "direct = measured soundings, indirect = interpolated/predicted. Karst islets and narrow channels "
              "are not resolved. Research visualization, not for navigation.")


# A flagged GEBCO hole must stand out from its surroundings, sit in shallow water and carry no direct sounding.
# Without these tests the ETOPO rule flagged ~22 patches of open-Gulf seabed that merely dip below 30 m next to
# 29 m water, and deep tidal channels between karst islands that GEBCO has measured (TID 17) (RL-52).
SUSPECT_MIN_CONTRAST_M = 12.0
SUSPECT_MAX_SURROUNDING_M = 25.0


def _clusters(mask: np.ndarray) -> list[np.ndarray]:
    """8-connected components of a boolean grid (no scipy in the API image)."""
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    ny, nx = mask.shape
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        member = np.zeros_like(mask, dtype=bool)
        stack = [(y, x)]
        seen[y, x] = member[y, x] = True
        while stack:
            a, b = stack.pop()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    c, d = a + dy, b + dx
                    if 0 <= c < ny and 0 <= d < nx and mask[c, d] and not seen[c, d]:
                        seen[c, d] = member[c, d] = True
                        stack.append((c, d))
        out.append(member)
    return out


def gebco_suspect_mask(depth: np.ndarray, tid_cls: np.ndarray, wet: np.ndarray) -> np.ndarray:
    """Isolated deep basins (ETOPO rule) kept only when they look like source artefacts:
    >= SUSPECT_MIN_CONTRAST_M deeper than the surrounding ring, ring median < SUSPECT_MAX_SURROUNDING_M,
    and no direct-measurement cell (TID class 1) inside."""
    candidate = suspect_mask(np.where(wet, depth, np.nan))
    keep = np.zeros_like(candidate, dtype=bool)
    for member in _clusters(candidate):
        ring = member.copy()
        for _ in range(3):
            grown = ring.copy()
            grown[1:, :] |= ring[:-1, :]; grown[:-1, :] |= ring[1:, :]
            grown[:, 1:] |= ring[:, :-1]; grown[:, :-1] |= ring[:, 1:]
            ring = grown
        ring &= ~member & wet
        if not ring.any():
            continue
        surrounding = float(np.median(depth[ring]))
        contrast = float(depth[member].max()) - surrounding
        if contrast >= SUSPECT_MIN_CONTRAST_M and surrounding < SUSPECT_MAX_SURROUNDING_M and not (tid_cls[member] == 1).any():
            keep |= member
    return keep



def tid_class(tid: np.ndarray) -> np.ndarray:
    """0 = unknown/land, 1 = direct (TID 10-17), 2 = indirect (TID 40-45)."""
    t = np.nan_to_num(np.asarray(tid, dtype=float), nan=0.0).astype(int)
    out = np.zeros(t.shape, dtype=np.int8)
    out[(t >= DIRECT_TID.start) & (t < DIRECT_TID.stop)] = 1
    out[(t >= INDIRECT_TID.start) & (t < INDIRECT_TID.stop)] = 2
    return out


def _root(cache_dir: str) -> Path:
    return Path(cache_dir) / "bathymetry-gebco"


def load_manifest(cache_dir: str) -> dict[str, Any] | None:
    root = _root(cache_dir)
    if not root.is_dir():
        return None
    for path in sorted(root.glob("*/manifest.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if manifest.get("artifact_version") == GEBCO_ARTIFACT_VERSION:
            return manifest
    return None


def ensure_gebco_artifact(cache_dir: str, raw_path: str, water=None) -> dict[str, Any]:
    """Build (once) the GEBCO artifact.  Existing keyed folders are never rewritten."""
    path = Path(raw_path)
    if not path.is_file():
        return {"status": "unavailable", "reason_code": "gebco_bathymetry_file_missing", "raw_path": path.name}
    with xr.open_dataset(path) as dataset:
        lon = dataset.lon.values.astype(float)
        lat = dataset.lat.values.astype(float)
        z = dataset.elevation.values.astype(float)
        tid = dataset.tid.values.astype(float) if "tid" in dataset else np.zeros_like(z)
        source = dataset.attrs.get("source", "GEBCO_2024 Grid")
        citation = dataset.attrs.get("citation", "")
    if lat[0] > lat[-1]:
        lat, z, tid = lat[::-1], z[::-1], tid[::-1]
    if water is None:
        pad = abs(float(lon[1] - lon[0]))
        water = water_geometry_for_bounds(float(lon.min()) - pad, float(lat.min()) - pad, float(lon.max()) + pad, float(lat.max()) + pad)
    if water is None or water.is_empty:
        return {"status": "unavailable", "reason_code": "bathymetry_water_mask_unavailable"}
    from shapely import contains_xy, prepare
    water_hash = hashlib.sha256(water.wkb).hexdigest()
    key = hashlib.sha256(f"{_fingerprint(path)}:{water_hash}:{GEBCO_ARTIFACT_VERSION}:{LOD_TOLERANCE}".encode()).hexdigest()[:24]
    target = _root(cache_dir) / key
    if (target / "manifest.json").exists():
        return json.loads((target / "manifest.json").read_text(encoding="utf-8"))

    prepare(water)
    xx, yy = np.meshgrid(lon, lat)
    in_water = contains_xy(water, xx, yy)
    sea = np.isfinite(z) & (z < 0)
    depth = np.where(sea, -z, 0.0)
    cls = tid_class(tid)
    suspect = gebco_suspect_mask(depth, cls, sea & in_water)
    lon_f = np.linspace(lon[0], lon[-1], (len(lon) - 1) * UPSAMPLE + 1)
    lat_f = np.linspace(lat[0], lat[-1], (len(lat) - 1) * UPSAMPLE + 1)
    width = UPSAMPLE + 1

    def field(mask: np.ndarray) -> np.ndarray:
        return smooth(upsample_bilinear(mask.astype(float), UPSAMPLE), width)

    depth_f = smooth(upsample_bilinear(depth, UPSAMPLE), width)
    sea_f, suspect_f = field(sea), field(suspect)
    direct_f, indirect_f = field(sea & (cls == 1)), field(sea & (cls == 2))
    coarse = _filled_polygons(lon_f, lat_f, sea_f, -1.0, FLAG_THRESHOLD)
    coarse = coarse.intersection(water) if coarse is not None else None
    suspect_geom = _filled_polygons(lon_f, lat_f, suspect_f, 1.0 - FLAG_THRESHOLD, 2.0)
    suspect_geom = suspect_geom.intersection(water) if suspect_geom is not None else None
    # Direct wins ties over indirect: classify a node by the larger smoothed share.
    direct_geom = _filled_polygons(lon_f, lat_f, direct_f - indirect_f, 0.05, 2.0)
    indirect_geom = _filled_polygons(lon_f, lat_f, indirect_f - direct_f, 0.05, 2.0)
    edges = list(BAND_EDGES) + [max(float(depth.max()) + 1.0, BAND_EDGES[-1] + 1.0)]
    band_geoms = []
    for lower, upper in zip(edges[:-1], edges[1:]):
        geometry = _filled_polygons(lon_f, lat_f, depth_f, lower, upper)
        if geometry is None:
            continue
        rest = geometry.intersection(water)
        for confidence, mask in (("suspect", suspect_geom), ("coarse", coarse), ("direct", direct_geom), ("indirect", indirect_geom)):
            if mask is not None and not rest.is_empty:
                band_geoms.append((lower, upper, confidence, rest.intersection(mask)))
                rest = rest.difference(mask)
        band_geoms.append((lower, upper, "unknown", rest))
    # Slope from the unsmoothed grid (metric spacing per row), then upsampled like the depth for contouring.
    dy_m = abs(float(lat[1] - lat[0])) * 111_320.0
    dx_m = abs(float(lon[1] - lon[0])) * 111_320.0 * np.cos(np.radians(lat))[:, None]
    grad_y, grad_x = np.gradient(depth)
    slope = np.degrees(np.arctan(np.hypot(grad_x / dx_m, grad_y / dy_m)))
    slope = np.where(sea & in_water, slope, 0.0)
    slope_f = smooth(upsample_bilinear(slope, UPSAMPLE), width)
    slope_edges = list(SLOPE_EDGES_DEG) + [max(float(slope.max()) + 1.0, SLOPE_EDGES_DEG[-1] + 1.0)]
    slope_geoms = []
    for index, (lower, upper) in enumerate(zip(slope_edges[:-1], slope_edges[1:])):
        geometry = _filled_polygons(lon_f, lat_f, slope_f, lower, upper)
        if geometry is not None:
            slope_geoms.append((index, lower, upper, geometry.intersection(water)))
    line_geoms = []
    for level in ISOBATHS:
        geometry = _lines(lon_f, lat_f, depth_f, level)
        line_geoms.append((level, geometry.intersection(water) if geometry is not None else None))

    _root(cache_dir).mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{key}.", dir=_root(cache_dir)))
    files: dict[str, str] = {}
    for lod, tolerance in LOD_TOLERANCE.items():
        min_area = LOD_MIN_AREA[lod]
        bands = []
        for lower, upper, confidence, geometry in band_geoms:
            index = BAND_EDGES.index(lower)
            last = index == len(BAND_EDGES) - 1
            label = f"≥ {lower:g} m" if last else f"{lower:g}–{upper:g} m"
            bands += _features(geometry, {"kind": "gebco_isoband", "band": index, "min_m": lower, "max_m": None if last else upper,
                                          "label": label, "confidence": confidence}, tolerance, min_area)
        lines = []
        for level, geometry in line_geoms:
            lines += _features(geometry, {"kind": "gebco_isobath", "depth_m": level}, tolerance, 0.0)
        flags = (_features(coarse, {"kind": "gebco_flag", "flag": "coarse"}, tolerance, min_area)
                 + _features(suspect_geom, {"kind": "gebco_flag", "flag": "suspect"}, tolerance, min_area))
        slopes = []
        for index, lower, upper, geometry in slope_geoms:
            last = index == len(SLOPE_EDGES_DEG) - 1
            slopes += _features(geometry, {"kind": "gebco_slope", "class": index, "min_deg": lower, "max_deg": None if last else upper,
                                           "label": f"≥ {lower:g}°" if last else f"{lower:g}–{upper:g}°"}, tolerance, min_area)
        for kind, features in (("isobands", bands), ("isobaths", lines), ("flags", flags), ("slope", slopes)):
            name = f"{kind}-{lod}.json"
            _write_json(staging / name, _round_coordinates({"type": "FeatureCollection", "features": features}))
            files[f"{kind}_{lod}"] = name
    np.savez_compressed(staging / "grid.npz", lon=lon, lat=lat, depth=depth, sea=sea, in_water=in_water,
                        suspect=suspect, tid=np.nan_to_num(tid, nan=0.0).astype("int16"), tid_class=cls)
    files["grid"] = "grid.npz"
    wet = in_water & sea
    manifest = {
        "status": "ready", "artifact_version": GEBCO_ARTIFACT_VERSION, "artifact_key": key,
        "depth_source": "gebco2024_15s", "source": source, "citation": citation,
        "source_file": path.name, "source_resolution": "15″ (~460 m)", "vertical_datum": "mean sea level, not chart datum",
        "bbox": [float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max())],
        "band_edges_m": list(BAND_EDGES), "isobaths_m": list(ISOBATHS), "upsample": UPSAMPLE, "slope_edges_deg": list(SLOPE_EDGES_DEG),
        "slope_max_deg": round(float(slope.max()), 2),
        "interpolation": "bilinear between grid nodes + ~1-cell moving-average smoothing for contouring; land cells = 0 m shoreline; sample endpoint uses unsmoothed bilinear",
        "water_mask": "OSM water polygons (all geometry clipped to it)",
        "confidence_classes": {"direct": "TID 10-17 (measured)", "indirect": "TID 40-45 (interpolated/predicted)",
                               "unknown": "other TID", "coarse": "OSM water, GEBCO land", "suspect": f"> {SUSPECT_DEPTH_M:g} m basin not open to the Gulf, >= {SUSPECT_MIN_CONTRAST_M:g} m deeper than a < {SUSPECT_MAX_SURROUNDING_M:g} m surrounding, no direct sounding"},
        "water_cell_count": int(in_water.sum()), "depth_cell_count": int(wet.sum()),
        "coarse_cell_count": int((in_water & ~sea).sum()), "suspect_cell_count": int(suspect.sum()),
        "direct_cell_count": int((wet & (cls == 1)).sum()), "indirect_cell_count": int((wet & (cls == 2)).sum()),
        "unknown_cell_count": int((wet & (cls == 0)).sum()),
        "max_depth_m": round(float(np.max(np.where(wet, -z, 0))), 1),
        "disclaimer": DISCLAIMER, "files": files,
    }
    _write_json(staging / "manifest.json", manifest)
    if target.exists():
        shutil.rmtree(staging)
        return json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    os.replace(staging, target)
    return manifest


def load_geojson(cache_dir: str, manifest: dict[str, Any], kind: str, lod: str) -> dict[str, Any] | None:
    filename = manifest.get("files", {}).get(f"{kind}_{lod}")
    if not filename:
        return None
    try:
        return json.loads((_root(cache_dir) / manifest["artifact_key"] / filename).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


@lru_cache(maxsize=2)
def _grid(cache_dir: str, key: str) -> dict[str, np.ndarray]:
    data = np.load(_root(cache_dir) / key / "grid.npz")
    return {name: data[name] for name in data.files}


def sample(cache_dir: str, manifest: dict[str, Any] | None, longitude: float, latitude: float) -> dict[str, Any]:
    if not manifest or manifest.get("status") != "ready":
        return {"status": "unavailable", "reason_code": (manifest or {}).get("reason_code", "gebco_artifact_not_ready")}
    grid = _grid(cache_dir, manifest["artifact_key"])
    lon, lat = grid["lon"], grid["lat"]
    if not (lon[0] <= longitude <= lon[-1] and lat[0] <= latitude <= lat[-1]):
        return {"status": "unavailable", "reason_code": "outside_gebco_extent"}
    fx = (longitude - lon[0]) / (lon[1] - lon[0]); fy = (latitude - lat[0]) / (lat[1] - lat[0])
    x0, y0 = min(int(fx), len(lon) - 2), min(int(fy), len(lat) - 2)
    tx, ty = fx - x0, fy - y0
    d = grid["depth"]
    value = (d[y0, x0] * (1 - tx) * (1 - ty) + d[y0, x0 + 1] * tx * (1 - ty)
             + d[y0 + 1, x0] * (1 - tx) * ty + d[y0 + 1, x0 + 1] * tx * ty)
    xi, yi = int(round(fx)), int(round(fy))
    code = int(grid["tid_class"][yi, xi])
    return {
        "status": "available", "gebco_depth_m": round(float(value), 1),
        "nearest_cell_is_sea": bool(grid["sea"][yi, xi]), "suspect": bool(grid["suspect"][yi, xi]),
        "tid": int(grid["tid"][yi, xi]), "tid_confidence": ("unknown", "direct", "indirect")[code],
        "depth_source": "gebco2024_15s", "source_resolution": manifest["source_resolution"],
        "vertical_datum": manifest["vertical_datum"], "artifact_version": manifest["artifact_version"],
    }


if __name__ == "__main__":
    import sys
    from app.settings import settings
    raw = sys.argv[1] if len(sys.argv) > 1 else os.getenv("GEBCO_BATHYMETRY_PATH", "")
    result = ensure_gebco_artifact(settings.cache_dir, raw)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, indent=2, ensure_ascii=False))


# Seabed relief shading: bay slopes are mostly < 0.5 deg, invisible at true scale, so depth is exaggerated.
HILLSHADE_EXAGGERATION = 30.0


@lru_cache(maxsize=2)
def _hillshade_cached(cache_dir: str, key: str, exaggeration: float, azimuth: float, altitude: float) -> dict[str, Any]:
    import base64
    grid = _grid(cache_dir, key)
    lon, lat, depth = grid["lon"], grid["lat"], grid["depth"].astype(float)
    wet = grid["sea"].astype(bool) & grid["in_water"].astype(bool)
    elevation = -depth * exaggeration                     # seabed as terrain (negative = deeper)
    dy = abs(float(lat[1] - lat[0])) * 111_320.0
    dx = abs(float(lon[1] - lon[0])) * 111_320.0 * np.cos(np.radians(lat))[:, None]
    gy, gx = np.gradient(elevation)
    gx, gy = gx / dx, gy / dy
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.radians(360.0 - azimuth + 90.0), np.radians(altitude)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    shade = np.clip(shade, 0.0, 1.0)
    flat = float(np.sin(alt))                              # value of a level seabed
    # Darkness relative to a flat bottom (0 = flat or lit side, 255 = darkest slope); land/no-data stays 0.
    dark = np.where(wet, np.clip((flat - shade) / max(flat, 1e-6), 0.0, 1.0), 0.0)
    light = np.where(wet, np.clip((shade - flat) / max(1.0 - flat, 1e-6), 0.0, 1.0), 0.0)
    # Row 0 = north for the image.
    dark_img, light_img = (np.flipud((a * 255).round().astype("uint8")) if lat[0] < lat[-1] else (a * 255).round().astype("uint8") for a in (dark, light))
    return {
        "status": "ready", "width": int(len(lon)), "height": int(len(lat)),
        "bbox": [float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max())],
        "exaggeration": exaggeration, "azimuth_deg": azimuth, "altitude_deg": altitude,
        "dark_b64": base64.b64encode(dark_img.tobytes()).decode(), "light_b64": base64.b64encode(light_img.tobytes()).decode(),
        "note": f"GEBCO 2024 15\" (~460 m); depth exaggerated x{exaggeration:g} so gentle bay slopes show; not for navigation",
    }


def hillshade(cache_dir: str, manifest: dict[str, Any] | None, exaggeration: float = HILLSHADE_EXAGGERATION, azimuth: float = 315.0, altitude: float = 45.0) -> dict[str, Any]:
    if not manifest or manifest.get("status") != "ready":
        return {"status": "building", "reason_code": "gebco_artifact_not_ready"}
    return _hillshade_cached(cache_dir, manifest["artifact_key"], float(exaggeration), float(azimuth), float(altitude))
