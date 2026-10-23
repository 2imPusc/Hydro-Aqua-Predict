"""ETOPO 2022 15" regional depth: isobands, isobaths and confidence flags.

Why: Copernicus SDB (``bathymetry_artifacts``) has no valid pixel around Cat Ba,
Lan Ha or Ha Long (turbid water), so the map showed no depth where farms are.
ETOPO 2022 15" (~460 m, heights vs EGM2008 ~ MSL) covers every water cell but is
coarse and, in parts of Quang Ninh, plainly wrong.  Nothing here edits values:

* depth = -z where ETOPO is sea; ETOPO land cells act as the 0 m shoreline, so
  depth is only interpolated (bilinear) between the source grid and the coast;
* every polygon/line is clipped to the OSM water mask (coast follows OSM, not
  the 460 m grid);
* ``coarse`` = OSM water where ETOPO cells are land (channels/karst islets the
  grid cannot resolve) -> depth there is an interpolation towards 0 m;
* ``suspect`` = basins deeper than 30 m that are not connected to the open
  Gulf (south/east tile edge) through >30 m water -- e.g. 60-149 m "holes" in
  Cua Luc and Tien Yen / Dam Ha bays, implausible for these shallow bays.

Built by the worker (or ``python -m app.bathymetry_etopo``) into
``<cache>/bathymetry-etopo/<key>/``, write-once; the API only reads.
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

from app.domain import water_geometry_for_bounds

ETOPO_ARTIFACT_VERSION = "etopo2022-15s-isobands-v6"
BAND_EDGES = (0.0, 2.0, 5.0, 10.0, 20.0, 30.0, 50.0)
ISOBATHS = (2.0, 5.0, 10.0, 20.0, 30.0)
UPSAMPLE = 4
SUSPECT_DEPTH_M = 30.0
FLAG_THRESHOLD = 0.65
# Simplification tolerance (degrees) per level of detail; 1e-4 deg ~ 11 m.
LOD_TOLERANCE = {"low": 0.0012, "medium": 0.0004, "high": 0.00012}
LOD_MIN_AREA = {"low": 4e-6, "medium": 5e-7, "high": 0.0}
DISCLAIMER = ("ETOPO 2022 15\" (~460 m) relief; heights vs EGM2008 geoid (~MSL), not chart datum. "
              "Karst islets and narrow channels are not resolved. Research visualization, not for navigation.")


def _root(cache_dir: str) -> Path:
    return Path(cache_dir) / "bathymetry-etopo"


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return hashlib.sha256(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()


def _interp_matrix(n: int, k: int) -> np.ndarray:
    """Linear interpolation matrix from n source nodes to (n-1)*k+1 nodes."""
    m = (n - 1) * k + 1
    position = np.arange(m) / k
    lower = np.minimum(np.floor(position).astype(int), n - 2)
    frac = position - lower
    matrix = np.zeros((m, n))
    matrix[np.arange(m), lower] = 1 - frac
    matrix[np.arange(m), lower + 1] = frac
    return matrix


def upsample_bilinear(values: np.ndarray, k: int) -> np.ndarray:
    wy, wx = _interp_matrix(values.shape[0], k), _interp_matrix(values.shape[1], k)
    return wy @ values @ wx.T


def smooth(values: np.ndarray, width: int, passes: int = 2) -> np.ndarray:
    """Separable moving average (repeated -> ~Gaussian), edge-padded.

    GEBCO-lineage depths are integer metres with flat plateaus; contouring them
    exactly traces cell edges as stair steps.  A ~1-source-cell blur removes the
    steps without adding detail finer than the 460 m grid already has.
    """
    out = values.astype(float)
    pad = width // 2
    kernel = np.ones(width) / width
    for _ in range(passes):
        for axis in (0, 1):
            padded = np.pad(out, [(pad, pad) if a == axis else (0, 0) for a in (0, 1)], mode="edge")
            out = np.apply_along_axis(lambda row: np.convolve(row, kernel, mode="valid"), axis, padded)
    return out


def suspect_mask(depth: np.ndarray, threshold: float = SUSPECT_DEPTH_M) -> np.ndarray:
    """Cells in >threshold basins not 8-connected to the south/east tile edge (open Gulf)."""
    deep = np.nan_to_num(depth, nan=0.0) > threshold
    reached = np.zeros_like(deep)
    reached[0, :] = deep[0, :]
    reached[:, -1] |= deep[:, -1]
    stack = list(zip(*np.nonzero(reached)))
    ny, nx = deep.shape
    while stack:
        y, x = stack.pop()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                yy, xx = y + dy, x + dx
                if 0 <= yy < ny and 0 <= xx < nx and deep[yy, xx] and not reached[yy, xx]:
                    reached[yy, xx] = True
                    stack.append((yy, xx))
    isolated = deep & ~reached
    # One-cell halo: the transition ring around a bogus hole is just as unreliable.
    halo = isolated.copy()
    halo[1:, :] |= isolated[:-1, :]; halo[:-1, :] |= isolated[1:, :]
    halo[:, 1:] |= isolated[:, :-1]; halo[:, :-1] |= isolated[:, 1:]
    return halo & np.isfinite(depth)


def _filled_polygons(lon: np.ndarray, lat: np.ndarray, field: np.ndarray, lower: float, upper: float):
    import contourpy
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    generator = contourpy.contour_generator(lon, lat, field, fill_type="OuterOffset")
    points, offsets = generator.filled(lower, upper)
    polygons = []
    for pts, offs in zip(points, offsets):
        rings = [pts[offs[i]:offs[i + 1]] for i in range(len(offs) - 1)]
        rings = [ring for ring in rings if len(ring) >= 4]
        if rings:
            polygon = Polygon(rings[0], rings[1:]).buffer(0)
            if not polygon.is_empty:
                polygons.append(polygon)
    return unary_union(polygons) if polygons else None


def _lines(lon: np.ndarray, lat: np.ndarray, field: np.ndarray, level: float):
    import contourpy
    from shapely.geometry import LineString, MultiLineString
    generator = contourpy.contour_generator(lon, lat, field, line_type="Separate")
    lines = [LineString(item) for item in generator.lines(level) if len(item) >= 2]
    return MultiLineString(lines) if lines else None


def _features(geometry, properties: dict[str, Any], tolerance: float, min_area: float) -> list[dict[str, Any]]:
    from shapely.geometry import mapping
    if geometry is None or geometry.is_empty:
        return []
    simplified = geometry.simplify(tolerance, preserve_topology=True) if tolerance else geometry
    parts = getattr(simplified, "geoms", [simplified])
    out = []
    for part in parts:
        if part.is_empty or (part.geom_type == "Polygon" and part.area < min_area):
            continue
        if part.geom_type in ("LineString", "LinearRing") and part.length < tolerance * 6:
            continue
        out.append({"type": "Feature", "geometry": mapping(part), "properties": properties})
    return out


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _round_coordinates(collection: dict[str, Any]) -> dict[str, Any]:
    def walk(value):
        if isinstance(value, float):
            return round(value, 5)
        if isinstance(value, (list, tuple)):
            return [walk(item) for item in value]
        return value
    for feature in collection["features"]:
        feature["geometry"]["coordinates"] = walk(feature["geometry"]["coordinates"])
    return collection


def load_manifest(cache_dir: str) -> dict[str, Any] | None:
    root = _root(cache_dir)
    if not root.is_dir():
        return None
    candidates = sorted(root.glob("*/manifest.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if manifest.get("artifact_version") == ETOPO_ARTIFACT_VERSION:
            return manifest
    return None


def ensure_etopo_artifact(cache_dir: str, raw_path: str, water=None) -> dict[str, Any]:
    """Build (once) the ETOPO artifact.  Existing keyed folders are never rewritten."""
    path = Path(raw_path)
    if not path.is_file():
        return {"status": "unavailable", "reason_code": "etopo_bathymetry_file_missing", "raw_path": path.name}
    with xr.open_dataset(path) as dataset:
        lon = dataset.lon.values.astype(float)
        lat = dataset.lat.values.astype(float)
        z = dataset.z.values.astype(float)
        source = dataset.attrs.get("source", "ETOPO 2022 15 arc-second")
        citation = dataset.attrs.get("citation", "")
    if lat[0] > lat[-1]:
        lat, z = lat[::-1], z[::-1]
    if water is None:
        # Pad by one cell so edge nodes are strictly inside the mask (not on its boundary).
        pad = abs(float(lon[1] - lon[0]))
        water = water_geometry_for_bounds(float(lon.min()) - pad, float(lat.min()) - pad, float(lon.max()) + pad, float(lat.max()) + pad)
    if water is None or water.is_empty:
        return {"status": "unavailable", "reason_code": "bathymetry_water_mask_unavailable"}
    from shapely import contains_xy, prepare
    water_hash = hashlib.sha256(water.wkb).hexdigest()
    key = hashlib.sha256(f"{_fingerprint(path)}:{water_hash}:{ETOPO_ARTIFACT_VERSION}:{LOD_TOLERANCE}".encode()).hexdigest()[:24]
    target = _root(cache_dir) / key
    if (target / "manifest.json").exists():
        return json.loads((target / "manifest.json").read_text(encoding="utf-8"))

    prepare(water)
    xx, yy = np.meshgrid(lon, lat)
    in_water = contains_xy(water, xx, yy)
    sea = np.isfinite(z) & (z < 0)
    depth = np.where(sea, -z, 0.0)                      # land cells = 0 m shoreline
    suspect = suspect_mask(np.where(sea & in_water, -z, np.nan))
    lon_f = np.linspace(lon[0], lon[-1], (len(lon) - 1) * UPSAMPLE + 1)
    lat_f = np.linspace(lat[0], lat[-1], (len(lat) - 1) * UPSAMPLE + 1)
    depth_f = smooth(upsample_bilinear(depth, UPSAMPLE), UPSAMPLE + 1)
    # Flags are contoured from smoothed 0/1 masks; unsmoothed, the 0.5 line is a grid-aligned staircase.
    # Thresholds are conservative (flag area grows slightly) so a single-cell flag survives the blur.
    sea_f = smooth(upsample_bilinear(sea.astype(float), UPSAMPLE), UPSAMPLE + 1)
    suspect_f = smooth(upsample_bilinear(suspect.astype(float), UPSAMPLE), UPSAMPLE + 1)

    coarse = _filled_polygons(lon_f, lat_f, sea_f, -1.0, FLAG_THRESHOLD)
    coarse = coarse.intersection(water) if coarse is not None else None
    suspect_geom = _filled_polygons(lon_f, lat_f, suspect_f, 1.0 - FLAG_THRESHOLD, 2.0)
    suspect_geom = suspect_geom.intersection(water) if suspect_geom is not None else None
    edges = list(BAND_EDGES) + [max(float(depth.max()) + 1.0, BAND_EDGES[-1] + 1.0)]
    # Each band is split by confidence so the map can fade low-confidence parts (opacity by confidence).
    band_geoms = []
    for lower, upper in zip(edges[:-1], edges[1:]):
        geometry = _filled_polygons(lon_f, lat_f, depth_f, lower, upper)
        if geometry is None:
            continue
        rest = geometry.intersection(water)
        for confidence, mask in (("suspect", suspect_geom), ("coarse", coarse)):
            if mask is not None and not rest.is_empty:
                band_geoms.append((lower, upper, confidence, rest.intersection(mask)))
                rest = rest.difference(mask)
        band_geoms.append((lower, upper, "ok", rest))
    line_geoms = []
    for level in ISOBATHS:
        geometry = _lines(lon_f, lat_f, depth_f, level)
        line_geoms.append((level, geometry.intersection(water) if geometry is not None else None))

    _root(cache_dir).mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{key}.", dir=_root(cache_dir)))  # fresh, ours only
    files: dict[str, str] = {}
    for lod, tolerance in LOD_TOLERANCE.items():
        min_area = LOD_MIN_AREA[lod]
        bands = []
        for lower, upper, confidence, geometry in band_geoms:
            index = BAND_EDGES.index(lower)
            last = index == len(BAND_EDGES) - 1
            label = f"≥ {lower:g} m" if last else f"{lower:g}–{upper:g} m"
            bands += _features(geometry, {"kind": "etopo_isoband", "band": index, "min_m": lower, "max_m": None if last else upper,
                                          "label": label, "confidence": confidence}, tolerance, min_area)
        lines = []
        for level, geometry in line_geoms:
            lines += _features(geometry, {"kind": "etopo_isobath", "depth_m": level}, tolerance, 0.0)
        flags = (_features(coarse, {"kind": "etopo_flag", "flag": "coarse"}, tolerance, min_area)
                 + _features(suspect_geom, {"kind": "etopo_flag", "flag": "suspect"}, tolerance, min_area))
        for kind, features in (("isobands", bands), ("isobaths", lines), ("flags", flags)):
            name = f"{kind}-{lod}.json"
            _write_json(staging / name, _round_coordinates({"type": "FeatureCollection", "features": features}))
            files[f"{kind}_{lod}"] = name
    np.savez_compressed(staging / "grid.npz", lon=lon, lat=lat, depth=depth, sea=sea, in_water=in_water, suspect=suspect)
    files["grid"] = "grid.npz"
    water_cells = int(in_water.sum())
    manifest = {
        "status": "ready", "artifact_version": ETOPO_ARTIFACT_VERSION, "artifact_key": key,
        "depth_source": "etopo2022_15s", "source": source, "citation": citation,
        "source_file": path.name, "source_resolution": "15″ (~460 m)", "vertical_datum": "EGM2008 geoid (~MSL), not chart datum",
        "bbox": [float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max())],
        "band_edges_m": list(BAND_EDGES), "isobaths_m": list(ISOBATHS), "upsample": UPSAMPLE, "interpolation": "bilinear between grid nodes + ~1-cell moving-average smoothing for contouring; ETOPO land cells = 0 m shoreline; sample endpoint uses unsmoothed bilinear",
        "water_mask": "OSM water polygons (all geometry clipped to it)",
        "water_cell_count": water_cells,
        "depth_cell_count": int((in_water & sea).sum()),
        "coarse_cell_count": int((in_water & ~sea).sum()),
        "suspect_cell_count": int(suspect.sum()),
        "suspect_rule": f"basins > {SUSPECT_DEPTH_M:g} m not connected to the open Gulf (south/east edge) through > {SUSPECT_DEPTH_M:g} m water, + 1-cell halo",
        "max_depth_m": round(float(np.max(np.where(in_water & sea, -z, 0))), 1),
        "disclaimer": DISCLAIMER, "files": files,
    }
    _write_json(staging / "manifest.json", manifest)
    if target.exists():  # another builder won the race; keep theirs, drop our fresh staging copy
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
        return {"status": "unavailable", "reason_code": (manifest or {}).get("reason_code", "etopo_artifact_not_ready")}
    grid = _grid(cache_dir, manifest["artifact_key"])
    lon, lat = grid["lon"], grid["lat"]
    if not (lon[0] <= longitude <= lon[-1] and lat[0] <= latitude <= lat[-1]):
        return {"status": "unavailable", "reason_code": "outside_etopo_extent"}
    fx = (longitude - lon[0]) / (lon[1] - lon[0]); fy = (latitude - lat[0]) / (lat[1] - lat[0])
    x0, y0 = min(int(fx), len(lon) - 2), min(int(fy), len(lat) - 2)
    tx, ty = fx - x0, fy - y0
    d = grid["depth"]
    value = (d[y0, x0] * (1 - tx) * (1 - ty) + d[y0, x0 + 1] * tx * (1 - ty)
             + d[y0 + 1, x0] * (1 - tx) * ty + d[y0 + 1, x0 + 1] * tx * ty)
    xi, yi = int(round(fx)), int(round(fy))
    return {
        "status": "available", "etopo_depth_m": round(float(value), 1),
        "nearest_cell_is_sea": bool(grid["sea"][yi, xi]), "suspect": bool(grid["suspect"][yi, xi]),
        "depth_source": "etopo2022_15s", "source_resolution": manifest["source_resolution"],
        "vertical_datum": manifest["vertical_datum"], "artifact_version": manifest["artifact_version"],
    }


if __name__ == "__main__":
    from app.settings import settings
    result = ensure_etopo_artifact(settings.cache_dir, settings.etopo_bathymetry_path)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, indent=2))
