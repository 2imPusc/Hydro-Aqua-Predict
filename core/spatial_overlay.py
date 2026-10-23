"""Water-clipped, research-only spatial applicability overlays for the demo map."""
from __future__ import annotations

import json
import heapq
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import shapefile
from pyproj import Geod, Transformer
from shapely import contains_xy
from shapely.geometry import Point, Polygon, box, mapping, shape
from shapely.ops import nearest_points, transform, unary_union

from core import paths


WATER_SHAPEFILE = paths.WATER_SHAPEFILE
GATE_CONFIG = paths.ASSETS_DIR / "spatial_applicability" / "haiphong_gate_v1.json"
HSI_GATE_CONFIG = paths.ASSETS_DIR / "spatial_applicability" / "hsi_gate_v2.json"
HP_HISTORICAL = paths.clean_data("haiphong")
STATION_COORDINATES = paths.STATION_COORDINATES
GEOD = Geod(ellps="WGS84")
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32648", always_xy=True).transform
TO_WGS84 = Transformer.from_crs("EPSG:32648", "EPSG:4326", always_xy=True).transform
# A 200 m square grid resolves the 0.5 km HSI-radius zones.  Polygon output
# is rounded with a circular kernel before water clipping, so the map does not
# expose hard raster corners.
WATER_PATH_GRID_M = 200.0


def geodesic_disk(longitude: float, latitude: float, radius_km: float, *, vertices: int = 96) -> Polygon:
    """Return a WGS84 polygon approximating a radius in kilometres."""
    if radius_km <= 0:
        raise ValueError("radius_km must be positive")
    azimuths = [index * 360 / vertices for index in range(vertices)]
    longitudes, latitudes, _ = GEOD.fwd(
        [longitude] * vertices, [latitude] * vertices, azimuths, [radius_km * 1000] * vertices,
    )
    return Polygon(zip(longitudes, latitudes))


@lru_cache(maxsize=32)
def local_water_geometry(min_lon: float, min_lat: float, max_lon: float, max_lat: float):
    """Read only OSM water polygons intersecting a small WGS84 bounding box."""
    if not WATER_SHAPEFILE.exists():
        raise FileNotFoundError(f"water polygon source missing: {WATER_SHAPEFILE}")
    bounds = box(min_lon, min_lat, max_lon, max_lat)
    reader = shapefile.Reader(str(WATER_SHAPEFILE))
    geometries = [shape(item.__geo_interface__) for item in reader.iterShapes(bbox=(min_lon, min_lat, max_lon, max_lat))]
    if not geometries:
        return None
    return unary_union(geometries).intersection(bounds)


@lru_cache(maxsize=1)
def haiphong_water_geometry():
    """One reusable water mask for the complete Hai Phong station cluster."""
    coordinates = pd.read_csv(STATION_COORDINATES, usecols=["Lat", "Lon"])
    # 0.35 degrees comfortably covers the 30 km legacy search radius.
    return local_water_geometry(
        round(float(coordinates.Lon.min() - .35), 4), round(float(coordinates.Lat.min() - .35), 4),
        round(float(coordinates.Lon.max() + .35), 4), round(float(coordinates.Lat.max() + .35), 4),
    )


def display_water_position(longitude: float, latitude: float, *, water_wgs84: Any | None = None) -> dict[str, float]:
    """Return a display-only point on water while preserving source provenance."""
    water = water_wgs84 if water_wgs84 is not None else haiphong_water_geometry()
    source = Point(longitude, latitude)
    snapped = source if water.covers(source) else nearest_points(source, water)[1]
    _, _, distance_m = GEOD.inv(source.x, source.y, snapped.x, snapped.y)
    return {
        "longitude": float(snapped.x),
        "latitude": float(snapped.y),
        "source_longitude": float(longitude),
        "source_latitude": float(latitude),
        "offset_m": float(distance_m),
    }


def water_clipped_band(longitude: float, latitude: float, inner_km: float, outer_km: float) -> dict[str, Any] | None:
    """Clip a geodesic disk/ring to water; land is excluded from the geometry."""
    if inner_km < 0 or outer_km <= inner_km:
        raise ValueError("require 0 <= inner_km < outer_km")
    outer = geodesic_disk(longitude, latitude, outer_km)
    band = outer if inner_km == 0 else outer.difference(geodesic_disk(longitude, latitude, inner_km))
    min_lon, min_lat, max_lon, max_lat = band.bounds
    water = local_water_geometry(round(min_lon, 4), round(min_lat, 4), round(max_lon, 4), round(max_lat, 4))
    if water is None:
        return None
    clipped = band.intersection(water)
    return mapping(clipped) if not clipped.is_empty else None


def _water_cost_surface(longitude: float, latitude: float, outer_km: float, grid_m: float, *, water_wgs84: Any | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, Any] | None:
    """Build a local water-only distance surface in UTM zone 48N.

    Land cells are absent from the graph, so a path cannot cross an island.
    The configured grid is intentionally a display/research approximation, not a
    hydrodynamic transport model.
    """
    disk = geodesic_disk(longitude, latitude, outer_km)
    min_lon, min_lat, max_lon, max_lat = disk.bounds
    if water_wgs84 is None:
        water_wgs84 = local_water_geometry(round(min_lon, 4), round(min_lat, 4), round(max_lon, 4), round(max_lat, 4))
    else:
        water_wgs84 = water_wgs84.intersection(box(min_lon, min_lat, max_lon, max_lat))
    if water_wgs84 is None or water_wgs84.is_empty:
        return None

    water = transform(TO_UTM, water_wgs84)
    center_x, center_y = TO_UTM(longitude, latitude)
    radius_m = outer_km * 1000
    x_values = np.arange(center_x - radius_m, center_x + radius_m + grid_m, grid_m)
    y_values = np.arange(center_y - radius_m, center_y + radius_m + grid_m, grid_m)
    xx, yy = np.meshgrid(x_values, y_values)
    water_mask = contains_xy(water, xx, yy)
    if not np.any(water_mask):
        return None

    distances = np.full(water_mask.shape, np.inf, dtype=float)
    # A station coordinate can be placed on the shore in the registry. Snap it
    # to a nearby water cell, but retain the snap limit as provenance.
    candidate_rows, candidate_cols = np.where(water_mask)
    squared = (x_values[candidate_cols] - center_x) ** 2 + (y_values[candidate_rows] - center_y) ** 2
    nearest = int(np.argmin(squared))
    start_row, start_col = int(candidate_rows[nearest]), int(candidate_cols[nearest])
    start_distance = float(np.sqrt(squared[nearest]))
    if start_distance > max(1500.0, 3 * grid_m):
        return None

    distances[start_row, start_col] = start_distance
    frontier = [(start_distance, start_row, start_col)]
    neighbours = [
        (-1, 0, grid_m), (1, 0, grid_m), (0, -1, grid_m), (0, 1, grid_m),
        (-1, -1, grid_m * np.sqrt(2)), (-1, 1, grid_m * np.sqrt(2)),
        (1, -1, grid_m * np.sqrt(2)), (1, 1, grid_m * np.sqrt(2)),
    ]
    rows, cols = water_mask.shape
    while frontier:
        distance, row, col = heapq.heappop(frontier)
        if distance != distances[row, col]:
            continue
        if distance > radius_m:
            break
        for delta_row, delta_col, step in neighbours:
            next_row, next_col = row + delta_row, col + delta_col
            if not (0 <= next_row < rows and 0 <= next_col < cols) or not water_mask[next_row, next_col]:
                continue
            candidate = distance + step
            if candidate < distances[next_row, next_col] and candidate <= radius_m:
                distances[next_row, next_col] = candidate
                heapq.heappush(frontier, (candidate, next_row, next_col))
    return x_values, y_values, water_mask, distances, water


def _distance_mask_geometry(x_values: np.ndarray, y_values: np.ndarray, distances: np.ndarray, threshold_m: float, water: Any, grid_m: float, *, smooth: bool = True) -> Any | None:
    """Turn a raster threshold into compact horizontal strips, then clip water."""
    accepted = distances <= threshold_m
    strips = []
    for row, columns in enumerate(accepted):
        start = None
        for col, enabled in enumerate(np.append(columns, False)):
            if enabled and start is None:
                start = col
            elif not enabled and start is not None:
                strips.append(box(x_values[start] - grid_m / 2, y_values[row] - grid_m / 2,
                                  x_values[col - 1] + grid_m / 2, y_values[row] + grid_m / 2))
                start = None
    if not strips:
        return None
    geometry = unary_union(strips).intersection(water)
    if smooth:
        # The calculation remains a square-cell water-path raster.  Apply a
        # circular-kernel opening (erode then round-dilate) only *inside* the
        # selected cells.  Unlike outward smoothing this cannot create overlap
        # with a neighbouring anchor partition or reconnect across land.
        smoothing_m = grid_m * .35
        smoothed = geometry.buffer(-smoothing_m, join_style=1).buffer(smoothing_m, join_style=1)
        if not smoothed.is_empty:
            geometry = smoothed.intersection(water)
    return geometry if not geometry.is_empty else None


def _cell_mask_geometry(x_values: np.ndarray, y_values: np.ndarray, enabled: np.ndarray, water: Any, grid_m: float, *, smooth: bool = True) -> Any | None:
    distances = np.where(enabled, 0.0, np.inf)
    return _distance_mask_geometry(x_values, y_values, distances, 0.0, water, grid_m, smooth=smooth)


def water_path_band(longitude: float, latitude: float, inner_km: float, outer_km: float, *, grid_m: float = WATER_PATH_GRID_M, water_wgs84: Any | None = None) -> dict[str, Any] | None:
    """Return a band based on shortest traversable-water distance, not a disk."""
    if inner_km < 0 or outer_km <= inner_km:
        raise ValueError("require 0 <= inner_km < outer_km")
    surface = _water_cost_surface(longitude, latitude, outer_km, grid_m, water_wgs84=water_wgs84)
    if surface is None:
        return None
    x_values, y_values, _water_mask, distances, water = surface
    outer = _distance_mask_geometry(x_values, y_values, distances, outer_km * 1000, water, grid_m)
    if outer is None:
        return None
    if inner_km > 0:
        inner = _distance_mask_geometry(x_values, y_values, distances, inner_km * 1000, water, grid_m)
        if inner is not None:
            outer = outer.difference(inner)
    return mapping(transform(TO_WGS84, outer)) if not outer.is_empty else None


def water_path_distances(longitude: float, latitude: float, targets: pd.DataFrame, *, max_distance_km: float = 30.0, grid_m: float = WATER_PATH_GRID_M, water_wgs84: Any | None = None) -> pd.Series:
    """Shortest water-path distance from one station to target station points."""
    surface = _water_cost_surface(longitude, latitude, max_distance_km, grid_m, water_wgs84=water_wgs84)
    result = pd.Series(np.inf, index=targets.index, dtype=float)
    if surface is None:
        return result
    x_values, y_values, water_mask, distances, _water = surface
    target_x, target_y = Transformer.from_crs("EPSG:4326", "EPSG:32648", always_xy=True).transform(
        targets["Lon"].to_numpy(), targets["Lat"].to_numpy()
    )
    for index, x_value, y_value in zip(targets.index, target_x, target_y):
        col = int(np.argmin(np.abs(x_values - x_value)))
        row = int(np.argmin(np.abs(y_values - y_value)))
        if water_mask[row, col] and np.isfinite(distances[row, col]):
            result.loc[index] = distances[row, col] / 1000
    return result


def water_path_nearest_partition(stations: pd.DataFrame, *, max_distance_km: float = 5.0, grid_m: float = WATER_PATH_GRID_M, water_wgs84: Any | None = None) -> dict[str, Any] | None:
    """Assign every reachable water cell to exactly one nearest station.

    This multi-source Dijkstra surface is the primary-map geometry contract;
    station ID resolves exact distance ties deterministically.
    """
    required = {"station", "longitude", "latitude"}
    if not required.issubset(stations.columns):
        raise ValueError("partition_requires_station_longitude_latitude")
    if water_wgs84 is None:
        water_wgs84 = haiphong_water_geometry()
    if water_wgs84 is None or water_wgs84.is_empty:
        return None
    xs, ys = TO_UTM(stations.longitude.to_numpy(float), stations.latitude.to_numpy(float))
    margin = max_distance_km * 1000
    x_values = np.arange(min(xs) - margin, max(xs) + margin + grid_m, grid_m)
    y_values = np.arange(min(ys) - margin, max(ys) + margin + grid_m, grid_m)
    xx, yy = np.meshgrid(x_values, y_values)
    water = transform(TO_UTM, water_wgs84)
    mask = contains_xy(water, xx, yy)
    distance = np.full(mask.shape, np.inf); owner = np.full(mask.shape, "", dtype="U32")
    frontier = []
    snap_reasons = {}
    for station, x, y in sorted(zip(stations.station.astype(str), xs, ys)):
        rows, cols = np.where(mask)
        if not len(rows):
            continue
        offsets = (x_values[cols] - x) ** 2 + (y_values[rows] - y) ** 2
        pos = int(np.argmin(offsets)); row, col = int(rows[pos]), int(cols[pos]); start = float(np.sqrt(offsets[pos]))
        if start > max(1500.0, 3 * grid_m):
            snap_reasons[station] = "station_snap_exceeds_limit"; continue
        if start < distance[row, col] or (start == distance[row, col] and (not owner[row, col] or station < owner[row, col])):
            distance[row, col], owner[row, col] = start, station; heapq.heappush(frontier, (start, station, row, col))
    neighbours = [(-1, 0, grid_m), (1, 0, grid_m), (0, -1, grid_m), (0, 1, grid_m), (-1, -1, grid_m*np.sqrt(2)), (-1, 1, grid_m*np.sqrt(2)), (1, -1, grid_m*np.sqrt(2)), (1, 1, grid_m*np.sqrt(2))]
    while frontier:
        dist, station, row, col = heapq.heappop(frontier)
        if dist != distance[row, col] or station != owner[row, col] or dist > margin:
            continue
        for dr, dc, step in neighbours:
            nr, nc = row + dr, col + dc
            if not (0 <= nr < mask.shape[0] and 0 <= nc < mask.shape[1]) or not mask[nr, nc]:
                continue
            candidate = dist + step
            if candidate <= margin and (candidate < distance[nr, nc] or (candidate == distance[nr, nc] and station < owner[nr, nc])):
                distance[nr, nc], owner[nr, nc] = candidate, station; heapq.heappush(frontier, (candidate, station, nr, nc))
    return {"x_values": x_values, "y_values": y_values, "water": water, "water_mask": mask, "distance_m": distance, "owner": owner, "grid_m": grid_m, "snap_reasons": snap_reasons}


def _clip_bands_to_one_water_mask(bands: list[tuple[dict[str, Any], Any]]) -> list[dict[str, Any]]:
    """Clip many nearby bands with one indexed water-polygon lookup."""
    all_bounds = [geometry.bounds for _metadata, geometry in bands]
    min_lon, min_lat = min(item[0] for item in all_bounds), min(item[1] for item in all_bounds)
    max_lon, max_lat = max(item[2] for item in all_bounds), max(item[3] for item in all_bounds)
    water = local_water_geometry(round(min_lon, 4), round(min_lat, 4), round(max_lon, 4), round(max_lat, 4))
    if water is None:
        return []
    output = []
    for metadata, geometry in bands:
        clipped = geometry.intersection(water)
        if not clipped.is_empty:
            output.append({**metadata, "geometry": mapping(clipped)})
    return output


def _legacy_hsi(row: pd.Series) -> float:
    """The cobia HSI shape used by the original aqua-forecast radius demo."""
    rules = {
        "DO": ("min", 6.0), "Temperature": ("range", 24.0, 28.0),
        "pH": ("range", 8.0, 8.5), "Salinity": ("range", 27.0, 33.0),
        "NH3": ("max", .1), "TSS": ("max", 50.0),
    }
    scores = []
    for name, rule in rules.items():
        value = pd.to_numeric(row.get(name), errors="coerce")
        if pd.isna(value):
            continue
        if rule[0] == "range":
            low, high = rule[1], rule[2]
            score = value / low if value < low else (2 * high - value) / high if value > high else 1.0
        elif rule[0] == "min":
            score = min(1.0, value / rule[1])
        else:
            score = 1.0 - value / rule[1]
        scores.append(float(np.clip(score, 0, 1)))
    return float(np.mean(scores)) if scores else np.nan


def _legacy_hsi_label(value: float) -> str:
    if value >= .85:
        return "very_suitable"
    if value >= .75:
        return "suitable"
    if value >= .5:
        return "less_suitable"
    return "not_suitable"


def _legacy_radius(period: pd.DataFrame, station: str, *, max_distance_km: float = 30.0, bin_km: float = 1.0, alpha: float = .6) -> float:
    """Reproduce aqua-forecast's Euclidean HSI radius rule for the demo."""
    center = period.loc[period.Station.eq(station)].iloc[0]
    sigma = period.hsi.std()
    if not np.isfinite(sigma) or sigma == 0:
        return np.nan
    distances = np.hypot(period.X - center.X, period.Y - center.Y) / 1000
    neighbours = period.loc[(period.Station != station) & (distances <= max_distance_km)].copy()
    if neighbours.empty:
        return np.nan
    neighbours["distance_km"] = distances.loc[neighbours.index]
    neighbours["delta_hsi"] = (neighbours.hsi - center.hsi).abs()
    neighbours["bin"] = pd.cut(neighbours.distance_km, bins=np.arange(0, max_distance_km + bin_km, bin_km), include_lowest=True)
    result = 0.0
    center_label = _legacy_hsi_label(center.hsi)
    for interval, group in neighbours.groupby("bin", observed=True):
        if group.delta_hsi.mean() >= alpha * sigma or any(group.hsi.map(_legacy_hsi_label) != center_label):
            break
        result = float(interval.right)
    return min(max_distance_km, max(result, .5))


def _legacy_confidence(period: pd.DataFrame, station: str, radius_km: float, *, alpha: float = .6) -> dict[str, Any]:
    """Heuristic display confidence for legacy HSI, never a calibrated interval."""
    center = period.loc[period.Station.eq(station)].iloc[0]
    sigma = float(period.hsi.std())
    distances = np.hypot(period.X - center.X, period.Y - center.Y) / 1000
    neighbours = period.loc[(period.Station != station) & (distances <= radius_km)].copy()
    if neighbours.empty or not np.isfinite(sigma) or sigma <= 0:
        return {"band": "low", "score": 0.0, "n_neighbours": 0, "kind": "heuristic_not_calibrated"}
    delta = (neighbours.hsi - center.hsi).abs()
    similarity = float(np.clip(1 - delta.mean() / (alpha * sigma), 0, 1))
    label_match = float((neighbours.hsi.map(_legacy_hsi_label) == _legacy_hsi_label(center.hsi)).mean())
    support = min(len(neighbours) / 5, 1.0)
    score = float(np.clip(.45 * similarity + .30 * label_match + .25 * support, 0, 1))
    band = "high" if score >= .70 else "medium" if score >= .45 else "low"
    return {"band": band, "score": score, "n_neighbours": int(len(neighbours)), "kind": "heuristic_not_calibrated"}


@lru_cache(maxsize=1)
def legacy_hsi_demo_overlays() -> tuple[str, list[dict[str, Any]]]:
    """Build all-station legacy circles for the latest complete HP period."""
    source = pd.read_csv(HP_HISTORICAL)
    source["Quarter"] = pd.to_datetime(source["Quarter"], errors="coerce")
    counts = source.groupby("Quarter").Station.nunique()
    period_at = counts[counts.eq(counts.max())].index.max()
    columns = ["Station", "X", "Y", "DO", "Temperature", "pH", "Salinity", "NH3", "TSS"]
    period = source.loc[source.Quarter.eq(period_at), columns].copy()
    coordinates = pd.read_csv(STATION_COORDINATES, usecols=["Station", "Lat", "Lon"])
    period = period.merge(coordinates, on="Station", how="left", validate="many_to_one")
    period["hsi"] = period.apply(_legacy_hsi, axis=1)
    period = period.dropna(subset=["Station", "X", "Y", "Lat", "Lon", "hsi"])
    bands = []
    for row in period.itertuples(index=False):
        radius_km = _legacy_radius(period, row.Station)
        if not np.isfinite(radius_km):
            continue
        confidence = _legacy_confidence(period, row.Station, float(radius_km))
        metadata = {"station": row.Station, "hsi": float(row.hsi), "hsi_label": _legacy_hsi_label(float(row.hsi)),
                    "radius_km": float(radius_km), "period": period_at.date().isoformat(),
                    "mode": "legacy_hsi_demo_not_validated", "used_by_alerts": False,
                    "distance_metric": "euclidean_vn2000", "land_clipped": True,
                    "confidence": confidence}
        bands.append((metadata, geodesic_disk(float(row.Lon), float(row.Lat), float(radius_km))))
    return period_at.date().isoformat(), _clip_bands_to_one_water_mask(bands)


def load_gate_config() -> dict[str, Any]:
    with GATE_CONFIG.open(encoding="utf-8") as handle:
        return json.load(handle)


def build_shadow_overlays(longitude: float, latitude: float) -> list[dict[str, Any]]:
    """Return only configured research candidates, clipped to the water mask."""
    config = load_gate_config()
    overlays = []
    for candidate in config.get("candidates", []):
        if candidate.get("gate_status") != "shadow_candidate":
            continue
        geometry = water_path_band(longitude, latitude, float(candidate["inner_km"]), float(candidate["outer_km"]))
        if geometry is not None:
            overlays.append({**candidate, "geometry": geometry, "mode": "research_shadow_only", "distance_metric": "water_path_grid", "grid_resolution_m": WATER_PATH_GRID_M})
    return overlays


def build_hsi_partition_overlays() -> list[dict[str, Any]]:
    """Return non-overlapping, gate-filtered HSI research polygons."""
    if not HSI_GATE_CONFIG.exists():
        return []
    config = json.loads(HSI_GATE_CONFIG.read_text(encoding="utf-8"))
    candidates = [item for item in config.get("candidates", []) if item.get("gate_status") == "shadow_candidate"]
    if not candidates:
        return []
    coords = pd.read_csv(STATION_COORDINATES, usecols=["Station", "Lat", "Lon"]).rename(columns={"Station": "station", "Lat": "latitude", "Lon": "longitude"})
    surface = water_path_nearest_partition(coords, max_distance_km=float(config.get("research_max_distance_km", 5.0)))
    if surface is None:
        return []
    output = []
    for candidate in candidates:
        text = str(candidate["distance_bin_km"]).strip("()[]")
        low, high = (float(value.strip()) for value in text.split(","))
        for station in sorted(set(surface["owner"].ravel()) - {""}):
            enabled = (surface["owner"] == station) & (surface["distance_m"] > low * 1000) & (surface["distance_m"] <= high * 1000)
            geometry = _cell_mask_geometry(surface["x_values"], surface["y_values"], enabled, surface["water"], surface["grid_m"])
            if geometry is not None:
                output.append({**candidate, "anchor_station": station, "geometry": mapping(transform(TO_WGS84, geometry)), "mode": "hsi_research_gate_90", "distance_metric": "water_path_nearest_anchor", "grid_resolution_m": surface["grid_m"], "used_by_alerts": False, "reason_codes": candidate.get("reason_codes", "")})
    return output


def build_water_path_demo_overlays(*, max_distance_km: float = 5.0) -> list[dict[str, Any]]:
    """Render the unvalidated nearest-water-path partition for the demo.

    This is deliberately a geometric reference layer, not a confidence map:
    it makes station ownership and water distance inspectable before the
    historical HSI gate has enough observations to be shown in the product.
    """
    coords = pd.read_csv(STATION_COORDINATES, usecols=["Station", "Lat", "Lon"]).rename(
        columns={"Station": "station", "Lat": "latitude", "Lon": "longitude"}
    )
    surface = water_path_nearest_partition(coords, max_distance_km=max_distance_km)
    if surface is None:
        return []
    output = []
    for station in sorted(set(surface["owner"].ravel()) - {""}):
        enabled = (surface["owner"] == station) & np.isfinite(surface["distance_m"])
        geometry = _cell_mask_geometry(surface["x_values"], surface["y_values"], enabled, surface["water"], surface["grid_m"])
        if geometry is not None:
            output.append({
                "anchor_station": station,
                "geometry": mapping(transform(TO_WGS84, geometry)),
                "mode": "water_path_reference_demo",
                "status": "not_validated_not_used_by_alerts",
                "distance_metric": "water_path_nearest_anchor",
                "max_distance_km": max_distance_km,
                "grid_resolution_m": surface["grid_m"],
                "reason_code": "demo_reference_layer",
            })
    return output


@lru_cache(maxsize=1)
def build_observed_hsi_partition_demo_overlays(*, max_radius_km: float = 5.0) -> tuple[str, list[dict[str, Any]]]:
    """Apply the historical per-station HSI radius inside a water-path partition.

    The radius is calculated from the latest complete historical observation
    period, capped at ``max_radius_km``.  A cell first belongs to only one
    nearest water-path anchor, then survives only when within that anchor's
    HSI-derived radius.  This preserves the old HSI visual idea without
    overlapping circles or paths across land.
    """
    source = pd.read_csv(HP_HISTORICAL)
    source["Quarter"] = pd.to_datetime(source["Quarter"], errors="coerce")
    counts = source.groupby("Quarter").Station.nunique()
    period_at = counts[counts.eq(counts.max())].index.max()
    columns = ["Station", "X", "Y", "DO", "Temperature", "pH", "Salinity", "NH3", "TSS"]
    period = source.loc[source.Quarter.eq(period_at), columns].copy()
    coordinates = pd.read_csv(STATION_COORDINATES, usecols=["Station", "Lat", "Lon"])
    period = period.merge(coordinates, on="Station", how="inner", validate="many_to_one")
    period["hsi"] = period.apply(_legacy_hsi, axis=1)
    period = period.dropna(subset=["Station", "Lat", "Lon", "hsi"])
    if period.empty:
        return "unknown", []
    # Preserve the original HSI neighbourhood search, then cap only the final
    # display/influence radius.  Limiting the *search* to 5 km incorrectly
    # made remote anchors appear to have no HSI radius at all.
    period["radius_km"] = [
        min(max_radius_km, float(radius)) if np.isfinite(radius) else np.nan
        for radius in (_legacy_radius(period, station, max_distance_km=30.0) for station in period.Station)
    ]
    stations = period.rename(columns={"Station": "station", "Lat": "latitude", "Lon": "longitude"})[
        ["station", "latitude", "longitude"]
    ]
    surface = water_path_nearest_partition(stations, max_distance_km=max_radius_km)
    if surface is None:
        return period_at.date().isoformat(), []
    water_wgs84 = transform(TO_WGS84, surface["water"])
    output = []
    for row in period.sort_values("Station").itertuples(index=False):
        if not np.isfinite(row.radius_km):
            continue
        # Cells determine exclusive nearest-anchor ownership.  The displayed
        # extent itself is a real circle from the HSI radius, clipped to water
        # and then to that exclusive owner partition.
        owner_cells = surface["owner"] == str(row.Station)
        owner_geometry = _cell_mask_geometry(
            surface["x_values"], surface["y_values"], owner_cells,
            surface["water"], surface["grid_m"], smooth=False,
        )
        anchor = display_water_position(float(row.Lon), float(row.Lat), water_wgs84=water_wgs84)
        disk = transform(TO_UTM, geodesic_disk(anchor["longitude"], anchor["latitude"], float(row.radius_km)))
        geometry = disk.intersection(surface["water"])
        if owner_geometry is not None:
            geometry = geometry.intersection(owner_geometry)
        if geometry is not None and not geometry.is_empty:
            output.append({
                "anchor_station": str(row.Station),
                "geometry": mapping(transform(TO_WGS84, geometry)),
                "hsi": float(row.hsi),
                "hsi_label": _legacy_hsi_label(float(row.hsi)),
                "radius_km": float(row.radius_km),
                "period": period_at.date().isoformat(),
                "mode": "historical_hsi_radius_partition_demo",
                "status": "historical_demo_not_validated_not_used_by_alerts",
                "distance_metric": "nearest_water_path_with_hsi_radius_cap",
                "max_radius_km": max_radius_km,
                "grid_resolution_m": surface["grid_m"],
                "reason_code": "observed_hsi_radius_capped_and_nearest_anchor_partition",
            })
    return period_at.date().isoformat(), output
