"""Canonical spatial domain shared by the worker, API, and map.

The provider is queried with the rectangular bounds, while values shown on
the map are filtered by the water-clipped polygon.  The HSI geometry is not
read or changed here.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.geometry import MultiPoint, Point, box, mapping, shape
from shapely.ops import transform


_SOURCE_PATH = Path(__file__).resolve()
_LOCAL_REPO_ROOT = next(
    (candidate for candidate in _SOURCE_PATH.parents if (candidate / "data" / "map" / "station_coordinates.csv").is_file()),
    None,
)
_LOCAL_REPO_REGISTRY = (_LOCAL_REPO_ROOT / "data" / "map" / "station_coordinates.csv") if _LOCAL_REPO_ROOT else Path("__local_registry_unavailable__")
_LOCAL_PROJECT_ROOT = _LOCAL_REPO_ROOT if _LOCAL_REPO_ROOT else Path("__local_project_root_unavailable__")
STATION_REGISTRY = Path(os.getenv("STATION_REGISTRY_PATH", "/workspace/data/map/station_coordinates.csv"))
if not STATION_REGISTRY.is_file() and _LOCAL_REPO_REGISTRY.is_file():
    STATION_REGISTRY = _LOCAL_REPO_REGISTRY
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32648", always_xy=True).transform
TO_WGS84 = Transformer.from_crs("EPSG:32648", "EPSG:4326", always_xy=True).transform


@lru_cache(maxsize=1)
def station_records() -> tuple[dict[str, Any], ...]:
    if not STATION_REGISTRY.is_file():
        raise FileNotFoundError("station_registry_unavailable")
    records: list[dict[str, Any]] = []
    with STATION_REGISTRY.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                records.append({
                    "station": str(row["Station"]),
                    "name": row.get("Station_Name") or str(row["Station"]),
                    "longitude": float(row["Lon"]),
                    "latitude": float(row["Lat"]),
                })
            except (KeyError, TypeError, ValueError):
                continue
    if len(records) < 3:
        raise ValueError("insufficient_station_coordinates")
    return tuple(sorted(records, key=lambda item: item["station"]))


def stations_geojson() -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [item["longitude"], item["latitude"]]},
                "properties": {"station": item["station"], "name": item["name"]},
            }
            for item in station_records()
        ],
        "source": "station_coordinates.csv",
    }


def _load_water(bounds: tuple[float, float, float, float]):
    try:
        # Docker supplies /workspace (project root) via PYTHONPATH.  In a
        # Windows local-dev run, discover that sibling directory so the same
        # authoritative water mask is used instead of falling back to the
        # broad station buffer (which includes land).
        if (_LOCAL_PROJECT_ROOT / "core").is_dir() and str(_LOCAL_PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(_LOCAL_PROJECT_ROOT))
        from core.spatial_overlay import local_water_geometry

        return local_water_geometry(*(round(value, 4) for value in bounds))
    except (FileNotFoundError, ImportError):
        return None


def water_geometry_for_bounds(min_lon: float, min_lat: float, max_lon: float, max_lat: float):
    """Authoritative OSM water mask for an arbitrary local WGS84 extent.

    Unlike ``context_water_geometry`` this is not cropped to the station
    buffer, which lets bathymetry cover the Cat Ba island field while keeping
    every land polygon excluded.
    """
    return _load_water((min_lon, min_lat, max_lon, max_lat))


@lru_cache(maxsize=4)
def build_context_domain(buffer_m: int = 5_000) -> dict[str, Any]:
    if buffer_m <= 0:
        raise ValueError("context_buffer_must_be_positive")
    stations = station_records()
    coordinates = [(item["longitude"], item["latitude"]) for item in stations]
    hull = MultiPoint(coordinates).convex_hull
    buffered = transform(TO_WGS84, transform(TO_UTM, hull).buffer(buffer_m, resolution=24))
    water = _load_water(buffered.bounds)
    water_clipped = buffered.intersection(water) if water is not None else None
    is_water_clipped = water_clipped is not None and not water_clipped.is_empty
    display_water = water_clipped if is_water_clipped else buffered
    registry_hash = hashlib.sha256(STATION_REGISTRY.read_bytes()).hexdigest()
    canonical = json.dumps(
        {"registry_hash": registry_hash, "buffer_m": buffer_m, "geometry": mapping(display_water)},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    geometry_hash = hashlib.sha256(canonical).hexdigest()
    provider_bbox = [float(value) for value in buffered.bounds]
    return {
        "type": "FeatureCollection",
        "domain_id": f"haiphong-context-{geometry_hash[:12]}",
        "station_count": len(stations),
        "buffer_m": buffer_m,
        "provider_bbox": provider_bbox,
        "water_clipped": is_water_clipped,
        "reason_code": None if is_water_clipped else "water_mask_unavailable",
        "geometry_hash": geometry_hash,
        "station_registry_hash": registry_hash,
        "features": [
            {"type": "Feature", "geometry": mapping(hull), "properties": {"kind": "station_network_hull", "station_count": len(stations)}},
            {"type": "Feature", "geometry": mapping(buffered), "properties": {"kind": "context_domain_boundary", "buffer_m": buffer_m, "station_count": len(stations)}},
            {"type": "Feature", "geometry": mapping(display_water), "properties": {"kind": "context_domain_water", "buffer_m": buffer_m, "station_count": len(stations), "water_clipped": is_water_clipped}},
        ],
    }


@lru_cache(maxsize=4)
def context_water_geometry(buffer_m: int = 5_000):
    domain = build_context_domain(buffer_m)
    water_feature = next(item for item in domain["features"] if item["properties"]["kind"] == "context_domain_water")
    return shape(water_feature["geometry"])


def point_inside_context(longitude: float, latitude: float, buffer_m: int = 5_000) -> bool:
    return bool(context_water_geometry(buffer_m).covers(Point(float(longitude), float(latitude))))


def domain_center(buffer_m: int = 5_000) -> tuple[float, float]:
    min_lon, min_lat, max_lon, max_lat = build_context_domain(buffer_m)["provider_bbox"]
    return (min_lat + max_lat) / 2, (min_lon + max_lon) / 2


@lru_cache(maxsize=4)
def region_water_geometry(bbox: tuple[float, ...]):
    """OSM water mask for the regional environment grid (None when the mask is unavailable)."""
    min_lon, min_lat, max_lon, max_lat = bbox
    return _load_water((min_lon, min_lat, max_lon, max_lat))


@lru_cache(maxsize=4)
def region_geojson(bbox: tuple[float, ...], step_deg: float, tolerance_deg: float = 0.002) -> dict[str, Any]:
    """Regional grid extent + a simplified (~200 m) water polygon for clipping marine fields in the browser."""
    water = region_water_geometry(bbox)
    simplified = water.simplify(tolerance_deg, preserve_topology=True) if water is not None else box(*bbox)
    return {
        "type": "FeatureCollection",
        "bbox": list(bbox), "step_deg": step_deg, "water_clipped": water is not None,
        "features": [
            {"type": "Feature", "geometry": mapping(box(*bbox)), "properties": {"kind": "region_boundary"}},
            {"type": "Feature", "geometry": mapping(simplified), "properties": {"kind": "region_water", "simplify_deg": tolerance_deg}},
        ],
    }
