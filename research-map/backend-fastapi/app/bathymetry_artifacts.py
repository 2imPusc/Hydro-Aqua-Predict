"""Worker-built Copernicus SDB bathymetry artifacts; API handlers only read them."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr
from shapely import contains_xy, prepare
from app.domain import build_context_domain, water_geometry_for_bounds


BATHYMETRY_ARTIFACT_VERSION = "copernicus-sdb-100m-v6"
DATASET_ID = "cmems_obs-sdb_glo_phy_comp_my_100m-l4-s2_static"
QUALITY_ACCEPTED = (0, 1, 2)
QUALITY_RULE = "accept 0=Highly_reliable, 1=Reliable, 2=Moderately_reliable; reject 3=High_uncertainties and 4=Unknown_uncertainties"
# Keep even the overview meaningful in the island/estuary footprint.  The
# source is sparse, so 3-km aggregation hid nearly all valid shallow cells.
LODS = {"low": 16, "medium": 8, "high": 4}
CONTOURS = (0.25, 0.5, 0.75, 1.0, 2.0, 3.0, 5.0)


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}".encode()
    return hashlib.sha256(raw).hexdigest()


def _key(path: Path, geometry_hash: str) -> str:
    return hashlib.sha256(f"{geometry_hash}:{_fingerprint(path)}:{BATHYMETRY_ARTIFACT_VERSION}:{LODS}".encode()).hexdigest()


def _root(cache_dir: str) -> Path:
    return Path(cache_dir) / "bathymetry-artifacts"


def _manifest_path(cache_dir: str, key: str) -> Path:
    return _root(cache_dir) / f"manifest-{key}.json"


def load_manifest(cache_dir: str) -> dict[str, Any] | None:
    candidates = sorted(_root(cache_dir).glob("manifest-*.json"), key=lambda item: item.stat().st_mtime, reverse=True) if _root(cache_dir).exists() else []
    for path in candidates:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
    return None


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


def _feature(lon0: float, lat0: float, lon1: float, lat1: float, properties: dict[str, Any], water: Any) -> dict[str, Any] | None:
    from shapely.geometry import box, mapping
    clipped = box(lon0, lat0, lon1, lat1).intersection(water)
    if clipped.is_empty:
        return None
    return {"type": "Feature", "geometry": mapping(clipped), "properties": properties}


def _band(depth: float) -> str:
    if depth < 1: return "lt_1m"
    if depth < 2: return "1_2m"
    if depth < 3: return "2_3m"
    if depth < 5: return "3_5m"
    return "gt_5m"


def _mode(values: np.ndarray) -> int | None:
    valid = values[np.isfinite(values)].astype(int)
    if not len(valid): return None
    return int(np.bincount(valid).argmax())


def _depth_bands(lons: np.ndarray, lats: np.ndarray, depth: np.ndarray, valid: np.ndarray, quality: np.ndarray, sdb_type: np.ndarray, slope: np.ndarray, stride: int, water: Any) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for y in range(0, len(lats), stride):
        for x in range(0, len(lons), stride):
            selection = valid[y:y + stride, x:x + stride]
            if selection.sum() < max(1, selection.size // 8): continue
            values = depth[y:y + stride, x:x + stride][selection]
            value = float(np.nanmedian(values))
            q = _mode(quality[y:y + stride, x:x + stride][selection])
            kind = _mode(sdb_type[y:y + stride, x:x + stride][selection])
            s = slope[y:y + stride, x:x + stride][selection]
            lon0, lon1 = float(lons[x]), float(lons[min(len(lons) - 1, x + stride - 1)])
            lat0, lat1 = float(lats[y]), float(lats[min(len(lats) - 1, y + stride - 1)])
            feature = _feature(lon0, lat0, lon1, lat1, {"kind": "copernicus_depth_band", "depth_m": round(value, 2), "depth_band": _band(value), "quality_indicator": q, "sdb_type": kind, "slope_degrees": round(float(np.nanmedian(s)), 2) if np.isfinite(s).any() else None, "depth_source": "copernicus_sdb_100m", "coverage": "available"}, water)
            if feature is not None:
                features.append(feature)
    return {"type": "FeatureCollection", "features": features}


def _contours(lons: np.ndarray, lats: np.ndarray, depth: np.ndarray, valid: np.ndarray, stride: int, levels: tuple[float, ...], water: Any) -> dict[str, Any]:
    # Coarsen with medians then emit marching-square segments. Segments are
    # intentionally not joined; Leaflet can LOD/filter them cheaply.
    ny, nx = (len(lats) // stride), (len(lons) // stride)
    grid = np.full((ny, nx), np.nan, dtype=float)
    for y in range(ny):
        for x in range(nx):
            mask = valid[y * stride:(y + 1) * stride, x * stride:(x + 1) * stride]
            values = depth[y * stride:(y + 1) * stride, x * stride:(x + 1) * stride][mask]
            if len(values): grid[y, x] = np.median(values)
    features: list[dict[str, Any]] = []
    for level in levels:
        for y in range(ny - 1):
            for x in range(nx - 1):
                values = (grid[y, x], grid[y, x + 1], grid[y + 1, x + 1], grid[y + 1, x])
                if not all(np.isfinite(values)) or min(values) > level or max(values) < level: continue
                lon0, lon1 = float(lons[x * stride]), float(lons[min(len(lons)-1, (x + 1) * stride)])
                lat0, lat1 = float(lats[y * stride]), float(lats[min(len(lats)-1, (y + 1) * stride)])
                corners = ((lon0, lat0), (lon1, lat0), (lon1, lat1), (lon0, lat1))
                hits = []
                for i in range(4):
                    a, b = values[i], values[(i + 1) % 4]
                    if (a - level) * (b - level) <= 0 and a != b:
                        ratio = (level - a) / (b - a)
                        p, q = corners[i], corners[(i + 1) % 4]
                        hits.append([p[0] + ratio * (q[0] - p[0]), p[1] + ratio * (q[1] - p[1])])
                if len(hits) >= 2:
                    from shapely.geometry import LineString, mapping
                    clipped = LineString(hits[:2]).intersection(water)
                    if not clipped.is_empty:
                        features.append({"type": "Feature", "geometry": mapping(clipped), "properties": {"kind": "copernicus_contour", "depth_m": level}})
    return {"type": "FeatureCollection", "features": features}


def ensure_bathymetry_artifact(cache_dir: str, raw_path: str, buffer_m: int) -> dict[str, Any]:
    path = Path(raw_path)
    if not path.is_file():
        return {"status": "unavailable", "reason_code": "copernicus_bathymetry_file_missing", "raw_path": path.name}
    domain = build_context_domain(buffer_m)
    key = _key(path, domain["geometry_hash"])
    target = _manifest_path(cache_dir, key)
    if target.exists():
        return json.loads(target.read_text(encoding="utf-8"))
    with xr.open_dataset(path) as dataset:
        missing = {"height", "Quality_indicator", "SDB_type"}.difference(dataset.data_vars)
        if missing: return {"status": "unavailable", "reason_code": "copernicus_bathymetry_variables_missing", "missing": sorted(missing)}
        lons, lats = dataset.longitude.values.astype(float), dataset.latitude.values.astype(float)
        height = dataset.height.values.astype(float)
        quality = dataset.Quality_indicator.values.astype(float)
        sdb_type = dataset.SDB_type.values.astype(float)
    # Do not use the station-buffer water polygon: it truncates Cat Ba. Load
    # the OSM water geometry for the full NetCDF extent instead, then clip
    # both source pixels and the rendered cells/contours to it.
    water = water_geometry_for_bounds(float(lons.min()), float(lats.min()), float(lons.max()), float(lats.max()))
    if water is None or water.is_empty:
        return {"status": "unavailable", "reason_code": "bathymetry_water_mask_unavailable"}
    prepare(water)
    xx, yy = np.meshgrid(lons, lats)
    water_mask = np.isfinite(height) & (height < 0) & contains_xy(water, xx, yy)
    quality_int = np.where(np.isfinite(quality), quality, -1).astype(int)
    valid = water_mask & np.isin(quality_int, QUALITY_ACCEPTED)
    depth = np.where(valid, -height, np.nan)
    dy = max(1.0, abs(float(lats[1] - lats[0])) * 111_320)
    dx = max(1.0, abs(float(lons[1] - lons[0])) * 111_320 * np.cos(np.deg2rad(float(np.mean(lats)))))
    gy, gx = np.gradient(np.where(valid, depth, np.nan), dy, dx)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    root = _root(cache_dir); root.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for lod, stride in LODS.items():
        bands_name = f"bands-{key}-{lod}.json"; contours_name = f"contours-{key}-{lod}.json"
        _write_json_atomic(root / bands_name, _depth_bands(lons, lats, depth, valid, quality, sdb_type, slope, stride, water))
        requested_levels = (0.5, 1.0) if lod == "low" else CONTOURS
        available_levels = tuple(level for level in requested_levels if level <= float(np.nanmax(depth)))
        levels = available_levels or (float(np.nanmax(depth)),)
        _write_json_atomic(root / contours_name, _contours(lons, lats, depth, valid, stride, levels, water))
        files[f"bands_{lod}"], files[f"contours_{lod}"] = bands_name, contours_name
    grid_name = f"grid-{key}.npz"
    with tempfile.NamedTemporaryFile(dir=root, suffix=".npz", delete=False) as temporary:
        np.savez_compressed(temporary, longitude=lons, latitude=lats, depth=depth, valid=valid, quality=quality, sdb_type=sdb_type, slope=slope)
        temp_name = temporary.name
    os.replace(temp_name, root / grid_name)
    files["grid"] = grid_name
    manifest = {"status": "ready", "artifact_version": BATHYMETRY_ARTIFACT_VERSION, "artifact_key": key, "geometry_hash": domain["geometry_hash"], "dataset_id": DATASET_ID, "source": "Copernicus satellite-derived bathymetry (Sentinel-2 merged)", "source_resolution": "~100 m", "water_mask": "OSM water polygons over full Copernicus extent, intersected with negative-height SDB coverage", "quality_rule": QUALITY_RULE, "quality_flag_meanings": "0 Highly_reliable; 1 Reliable; 2 Moderately_reliable; 3 High_uncertainties; 4 Unknown_uncertainties", "sdb_type_meanings": "0 Intertidal; 1 Multi-spectral; 2 Wave kinematics; 3 Interpolated ground-truth control point; 4 Combined SDB", "coverage_fraction": round(float(valid.sum() / max(1, water_mask.sum())), 5), "valid_pixel_count": int(valid.sum()), "water_pixel_count": int(water_mask.sum()), "depth_source": "copernicus_sdb_100m", "gebco_fallback_status": "not_configured", "disclaimer": "Copernicus satellite-derived bathymetry; only valid where coverage and quality are available; research visualization, not for navigation.", "files": files}
    _write_json_atomic(target, manifest)
    return manifest


def load_geojson(cache_dir: str, manifest: dict[str, Any], kind: str, lod: str) -> dict[str, Any] | None:
    filename = manifest.get("files", {}).get(f"{kind}_{lod}")
    if not filename: return None
    try: return json.loads((_root(cache_dir) / filename).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError): return None


@lru_cache(maxsize=2)
def _grid(cache_dir: str, filename: str) -> dict[str, np.ndarray]:
    data = np.load(_root(cache_dir) / filename)
    return {name: data[name] for name in data.files}


def sample(cache_dir: str, manifest: dict[str, Any], longitude: float, latitude: float) -> dict[str, Any]:
    if manifest.get("status") != "ready": return {"status": "unavailable", "reason_code": manifest.get("reason_code", "bathymetry_artifact_building")}
    grid = _grid(cache_dir, manifest["files"]["grid"])
    x, y = int(np.abs(grid["longitude"] - longitude).argmin()), int(np.abs(grid["latitude"] - latitude).argmin())
    if not bool(grid["valid"][y, x]): return {"status": "unavailable", "reason_code": "copernicus_coverage_missing_or_not_water", "depth_source": "unavailable", "artifact_version": manifest["artifact_version"]}
    return {"status": "available", "copernicus_depth_m": round(float(grid["depth"][y, x]), 3), "quality_indicator": int(grid["quality"][y, x]), "sdb_type": int(grid["sdb_type"][y, x]), "slope_degrees": round(float(grid["slope"][y, x]), 3) if np.isfinite(grid["slope"][y, x]) else None, "depth_source": "copernicus_sdb_100m", "artifact_version": manifest["artifact_version"], "dataset_id": manifest["dataset_id"], "disclaimer": manifest["disclaimer"]}
