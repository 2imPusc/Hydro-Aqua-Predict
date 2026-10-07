"""Diagnostic station connectivity and current-alignment overlays."""
from __future__ import annotations

import heapq
import json
import math
import os
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from pyproj import Transformer
from shapely import contains_xy, prepare
from shapely.geometry import LineString, Point, mapping
from shapely.ops import transform

from app.domain import TO_UTM, TO_WGS84, context_water_geometry, station_records


NEIGHBOURS = [
    (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
    (-1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)),
    (1, -1, math.sqrt(2)), (1, 1, math.sqrt(2)),
]
NETWORK_ALGORITHM_VERSION = "water-dijkstra-v8"


def _interpolate_vector(point: Point, samples: list[tuple[Point, float, float]]) -> tuple[float, float]:
    """Helper function to interpolate u, v at any point."""
    nearby = sorted(samples, key=lambda item: point.distance(item[0]))[:8]
    if not nearby:
        return 0.0, 0.0
    weights = [1.0 / max(point.distance(item[0]), 100.0) for item in nearby]
    total = sum(weights)
    east = sum(weight * item[1] for weight, item in zip(weights, nearby)) / total
    north = sum(weight * item[2] for weight, item in zip(weights, nearby)) / total
    return east, north


def _advance_sliding(current: tuple[float, float], east: float, north: float, sign: float, step_m: float, water) -> tuple[tuple[float, float] | None, bool]:
    """Advance with wall-sliding to avoid getting stuck at coasts. Returns (candidate, is_sliding)."""
    speed = math.hypot(east, north)
    if speed <= 0:
        return None, False
        
    base = math.atan2(sign * north, sign * east)
    
    # 1. Try advancing straight
    candidate = (current[0] + step_m * math.cos(base), current[1] + step_m * math.sin(base))
    if water.covers(LineString([current, candidate])):
        return candidate, False
        
    # 2. Slide along the coast if hit
    for degrees in (20, -20, 45, -45, 75, -75, 90, -90):
        angle = base + math.radians(degrees)
        slide_step = step_m * 0.6 
        slide_candidate = (current[0] + slide_step * math.cos(angle), current[1] + slide_step * math.sin(angle))
        if water.covers(LineString([current, slide_candidate])):
            return slide_candidate, True
            
    return None, False


def _build_flow_streamlines(samples: list[tuple[Point, float, float]], water, *, source: str, step_m: float = 150.0, max_steps: int = 300, min_speed_m_s: float = 0.05, seed_stride: int = 10) -> list[dict[str, Any]]:
    """Build diagnostic streamlines using RK2 (Midpoint) and wall-sliding."""
    lines: list[dict[str, Any]] = []
    prepare(water)
    
    for seed, _east, _north in samples[::max(1, seed_stride)]:
        for sign in (1.0, -1.0):
            current = (float(seed.x), float(seed.y))
            coordinates = [current]
            consecutive_slides = 0
            
            for _ in range(max_steps):
                p_current = Point(current)
                if not water.covers(p_current):
                    break
                    
                east, north = _interpolate_vector(p_current, samples)
                speed = math.hypot(east, north)
                
                if speed < min_speed_m_s:
                    break
                
                # RK2 (Midpoint): take a half step to get a better tangent
                mid_angle = math.atan2(sign * north, sign * east)
                mid_x = current[0] + (step_m / 2) * math.cos(mid_angle)
                mid_y = current[1] + (step_m / 2) * math.sin(mid_angle)
                
                mid_east, mid_north = _interpolate_vector(Point(mid_x, mid_y), samples)
                mid_speed = math.hypot(mid_east, mid_north)
                
                if mid_speed < min_speed_m_s:
                    break
                    
                current, is_sliding = _advance_sliding(current, mid_east, mid_north, sign, step_m, water)
                
                if current is None:
                    break
                    
                if is_sliding:
                    consecutive_slides += 1
                else:
                    consecutive_slides = 0
                    
                if consecutive_slides > 10:
                    break
                    
                # Loop detection: check distance to a point 15 steps ago
                if len(coordinates) >= 15:
                    past_point = coordinates[-15]
                    if math.hypot(current[0] - past_point[0], current[1] - past_point[1]) < step_m:
                        break
                        
                coordinates.append(current)
                
            if len(coordinates) >= 8:
                line = LineString(coordinates)
                lines.append({
                    "type": "Feature", 
                    "geometry": mapping(transform(TO_WGS84, line)),
                    "properties": {
                        "kind": "flow_streamline", 
                        "step_m": step_m, 
                        "source": source,
                        "integration": "RK2",
                        "mode": "exploratory",
                        "source_resolution": "~8 km",
                        "max_streamline_length_km": round(max_steps * step_m / 1000)
                    },
                })
    return lines


def build_flow_rays(
    current_layer: dict[str, Any] | None, *, spacing_m: int = 400,
    step_m: float = 110.0, steps: int = 3, min_speed_m_s: float = 0.05,
) -> list[dict[str, Any]]:
    """Create dense, short, water-constrained display rays for one snapshot.

    The provider's coarse current grid is interpolated with the same IDW field
    used by the diagnostics. Seeds are a regular metric grid *inside* the
    water mask; every segment is checked against the full polygon geometry.
    Near islands and narrow channels, `_advance_sliding` tries shorter
    water-only moves so rays can enter valid inlets without crossing land.
    """
    if not current_layer or current_layer.get("kind") not in {"vector_grid", "regional_grid"} or not current_layer.get("geojson"):
        return []
    samples: list[tuple[Point, float, float]] = []
    for feature in current_layer["geojson"].get("features", []):
        try:
            longitude, latitude = feature["geometry"]["coordinates"]
            east, north = float(feature["properties"]["u_m_s"]), float(feature["properties"]["v_m_s"])
            x, y = TO_UTM(longitude, latitude)
            if all(math.isfinite(value) for value in (east, north, x, y)) and math.hypot(east, north) >= min_speed_m_s:
                samples.append((Point(x, y), east, north))
        except (KeyError, TypeError, ValueError):
            continue
    if not samples:
        return []

    water = transform(TO_UTM, context_water_geometry())
    prepare(water)
    min_x, min_y, max_x, max_y = water.bounds
    xs = np.arange(min_x + spacing_m / 2, max_x, spacing_m)
    ys = np.arange(min_y + spacing_m / 2, max_y, spacing_m)
    xx, yy = np.meshgrid(xs, ys)
    mask = contains_xy(water, xx, yy)
    source = current_layer.get("provenance", {}).get("source", "provider current vector grid")
    rays: list[dict[str, Any]] = []

    for row, col in zip(*np.where(mask)):
        current = (float(xs[col]), float(ys[row]))
        east, north = _interpolate_vector(Point(current), samples)
        if math.hypot(east, north) < min_speed_m_s:
            continue
        coordinates = [current]
        for _ in range(steps):
            candidate, _sliding = _advance_sliding(current, east, north, 1.0, step_m, water)
            if candidate is None:
                # Preserve water-only behavior at complicated coasts by
                # progressively shortening the visual ray.
                for shortened_step in (step_m * .65, step_m * .35):
                    candidate, _sliding = _advance_sliding(current, east, north, 1.0, shortened_step, water)
                    if candidate is not None:
                        break
            if candidate is None:
                break
            coordinates.append(candidate)
            current = candidate
            east, north = _interpolate_vector(Point(current), samples)
            if math.hypot(east, north) < min_speed_m_s:
                break
        if len(coordinates) < 2:
            continue
        ray = LineString(coordinates)
        if not water.covers(ray):
            continue
        rays.append({
            "type": "Feature", "geometry": mapping(transform(TO_WGS84, ray)),
            "properties": {
                "kind": "flow_ray", "source": source, "speed_m_s": round(math.hypot(east, north), 3),
                "interpolation": "idw_8_nearest_water_constrained", "spacing_m": spacing_m,
                "water_clipped": True, "mode": "exploratory",
            },
        })
    return rays


def _snap_cells(xs: np.ndarray, ys: np.ndarray, mask: np.ndarray, stations: tuple[dict[str, Any], ...]) -> dict[str, tuple[int, int, float]]:
    rows, cols = np.where(mask)
    result: dict[str, tuple[int, int, float]] = {}
    for item in stations:
        x, y = TO_UTM(item["longitude"], item["latitude"])
        offsets = (xs[cols] - x) ** 2 + (ys[rows] - y) ** 2
        nearest = int(np.argmin(offsets))
        result[item["station"]] = (int(rows[nearest]), int(cols[nearest]), float(math.sqrt(offsets[nearest])))
    return result


def _route(prev_row: np.ndarray, prev_col: np.ndarray, start: tuple[int, int], target: tuple[int, int], xs: np.ndarray, ys: np.ndarray) -> LineString | None:
    row, col = target
    path: list[tuple[float, float]] = []
    limit = prev_row.size + 1
    while limit > 0:
        path.append((float(xs[col]), float(ys[row])))
        if (row, col) == start:
            break
        next_row, next_col = int(prev_row[row, col]), int(prev_col[row, col])
        if next_row < 0 or next_col < 0:
            return None
        row, col, limit = next_row, next_col, limit - 1
    if not path or (row, col) != start:
        return None
    path.reverse()
    # Keep the raster route vertices: unconstrained line simplification can
    # create a shortcut across a narrow island.
    return LineString(path)


def _water_edge_masks(mask: np.ndarray, xs: np.ndarray, ys: np.ndarray, water) -> dict[tuple[int, int], np.ndarray]:
    """Precompute edges fully covered by water, not merely water endpoints."""
    result: dict[tuple[int, int], np.ndarray] = {}
    rows_count, cols_count = mask.shape
    for delta_row, delta_col, _multiplier in NEIGHBOURS:
        allowed = np.zeros(mask.shape, dtype=bool)
        rows, cols = np.where(mask)
        next_rows, next_cols = rows + delta_row, cols + delta_col
        in_bounds = (next_rows >= 0) & (next_rows < rows_count) & (next_cols >= 0) & (next_cols < cols_count)
        rows, cols, next_rows, next_cols = rows[in_bounds], cols[in_bounds], next_rows[in_bounds], next_cols[in_bounds]
        valid_end = mask[next_rows, next_cols]
        rows, cols, next_rows, next_cols = rows[valid_end], cols[valid_end], next_rows[valid_end], next_cols[valid_end]
        if len(rows):
            start_x, start_y = xs[cols], ys[rows]
            end_x, end_y = xs[next_cols], ys[next_rows]
            samples = np.linspace(0.0, 1.0, 9)
            covered = np.ones(len(rows), dtype=bool)
            for fraction in samples:
                covered &= contains_xy(water, start_x + (end_x - start_x) * fraction, start_y + (end_y - start_y) * fraction)
            allowed[rows, cols] = covered
        result[(delta_row, delta_col)] = allowed
    return result


def _astar(mask: np.ndarray, edge_masks: dict[tuple[int, int], np.ndarray], xs: np.ndarray, ys: np.ndarray, start: tuple[int, int], target: tuple[int, int], grid_m: int, initial_distance: float, max_distance_m: float):
    """Find one water-only route without expanding the complete domain grid."""
    distances = np.full(mask.shape, np.inf, dtype=float)
    prev_row = np.full(mask.shape, -1, dtype=np.int32)
    prev_col = np.full(mask.shape, -1, dtype=np.int32)
    start_row, start_col = start
    target_row, target_col = target
    distances[start_row, start_col] = initial_distance
    heuristic = math.hypot(xs[target_col] - xs[start_col], ys[target_row] - ys[start_row])
    queue = [(initial_distance + heuristic, initial_distance, start_row, start_col)]
    while queue:
        _score, distance, row, col = heapq.heappop(queue)
        if distance != distances[row, col] or distance > max_distance_m:
            continue
        if (row, col) == target:
            return distance, prev_row, prev_col
        for delta_row, delta_col, multiplier in NEIGHBOURS:
            next_row, next_col = row + delta_row, col + delta_col
            if not (0 <= next_row < mask.shape[0] and 0 <= next_col < mask.shape[1]) or not mask[next_row, next_col]:
                continue
            if not edge_masks[(delta_row, delta_col)][row, col]:
                continue
            candidate = distance + grid_m * multiplier
            if candidate < distances[next_row, next_col] and candidate <= max_distance_m:
                distances[next_row, next_col] = candidate
                prev_row[next_row, next_col], prev_col[next_row, next_col] = row, col
                estimate = math.hypot(xs[target_col] - xs[next_col], ys[target_row] - ys[next_row])
                heapq.heappush(queue, (candidate + estimate, candidate, next_row, next_col))
    return None


@lru_cache(maxsize=4)
def build_station_network(buffer_m: int = 5_000, grid_m: int = 200, nearest_k: int = 3, max_distance_km: float = 15.0) -> dict[str, Any]:
    stations = station_records()
    water_utm = transform(TO_UTM, context_water_geometry(buffer_m))
    prepare(water_utm)
    min_x, min_y, max_x, max_y = water_utm.bounds
    xs = np.arange(min_x, max_x + grid_m, grid_m)
    ys = np.arange(min_y, max_y + grid_m, grid_m)
    xx, yy = np.meshgrid(xs, ys)
    mask = contains_xy(water_utm, xx, yy)
    edge_masks = _water_edge_masks(mask, xs, ys, water_utm)
    snapped = _snap_cells(xs, ys, mask, stations)
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    max_distance_m = max_distance_km * 1000

    for source in stations:
        source_id = source["station"]
        start_row, start_col, source_offset = snapped[source_id]
        distances = np.full(mask.shape, np.inf, dtype=float)
        prev_row = np.full(mask.shape, -1, dtype=np.int32)
        prev_col = np.full(mask.shape, -1, dtype=np.int32)
        distances[start_row, start_col] = source_offset
        queue = [(source_offset, start_row, start_col)]
        while queue:
            distance, row, col = heapq.heappop(queue)
            if distance != distances[row, col] or distance > max_distance_m:
                continue
            for delta_row, delta_col, multiplier in NEIGHBOURS:
                next_row, next_col = row + delta_row, col + delta_col
                if not (0 <= next_row < mask.shape[0] and 0 <= next_col < mask.shape[1]):
                    continue
                if not edge_masks[(delta_row, delta_col)][row, col]:
                    continue
                candidate = distance + grid_m * multiplier
                if candidate < distances[next_row, next_col] and candidate <= max_distance_m:
                    distances[next_row, next_col] = candidate
                    prev_row[next_row, next_col], prev_col[next_row, next_col] = row, col
                    heapq.heappush(queue, (candidate, next_row, next_col))

        candidates = []
        for target in stations:
            target_id = target["station"]
            if target_id == source_id:
                continue
            row, col, target_offset = snapped[target_id]
            distance = float(distances[row, col] + target_offset)
            if math.isfinite(distance) and distance <= max_distance_m:
                candidates.append((distance, target_id, row, col, target_offset))
        connected = sum(1 for pair in edges if source_id in pair)
        for distance, target_id, row, col, target_offset in sorted(candidates):
            if connected >= nearest_k:
                break
            key = tuple(sorted((source_id, target_id)))
            if key in edges:
                connected += 1
                continue
            route = _route(prev_row, prev_col, (start_row, start_col), (row, col), xs, ys)
            if route is None or not water_utm.covers(route):
                continue
            route_wgs84 = transform(TO_WGS84, route)
            edges[key] = {
                "type": "Feature", "geometry": mapping(route_wgs84),
                "properties": {
                    "kind": "water_path_station_edge", "station_a": source_id, "station_b": target_id,
                    "water_distance_km": round(distance / 1000, 3), "grid_m": grid_m,
                    "source_snap_m": round(source_offset, 1), "target_snap_m": round(target_offset, 1),
                    "relationship": "nearest_water_path_diagnostic",
                },
            }
            connected += 1
    return {
        "type": "FeatureCollection", "features": list(edges.values()),
        "station_count": len(stations), "edge_count": len(edges), "grid_m": grid_m,
        "nearest_k": nearest_k, "max_distance_km": max_distance_km,
        "network_status": "ready",
        "influence_status": "unavailable", "influence_reason": "current_grid_required",
    }


def _network_cache_path(cache_dir: str, buffer_m: int, grid_m: int) -> Path:
    from app.domain import build_context_domain

    geometry_hash = build_context_domain(buffer_m)["geometry_hash"]
    return Path(cache_dir) / f"station-network-{geometry_hash[:16]}-{grid_m}m-{NETWORK_ALGORITHM_VERSION}.json"


def load_station_network_cache(cache_dir: str, buffer_m: int, grid_m: int = 200) -> dict[str, Any] | None:
    target = _network_cache_path(cache_dir, buffer_m, grid_m)
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def ensure_station_network_cache(cache_dir: str, buffer_m: int, grid_m: int = 200) -> dict[str, Any]:
    cached = load_station_network_cache(cache_dir, buffer_m, grid_m)
    if cached is not None:
        return cached
    target = _network_cache_path(cache_dir, buffer_m, grid_m)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.with_suffix(f"{target.suffix}.lock")
    if lock.exists() and time.time() - lock.stat().st_mtime > 600:
        lock.unlink(missing_ok=True)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return load_station_network_cache(cache_dir, buffer_m, grid_m) or building_station_network()
    try:
        os.close(descriptor)
        network = build_station_network(buffer_m, grid_m)
        temporary = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(network, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, target)
        return network
    finally:
        lock.unlink(missing_ok=True)


def building_station_network() -> dict[str, Any]:
    return {
        "type": "FeatureCollection", "features": [], "station_count": len(station_records()),
        "edge_count": 0, "network_status": "building", "influence_status": "unavailable",
        "influence_reason": "station_network_cache_building",
    }


def add_current_influence(
    network: dict[str, Any], current_layer: dict[str, Any] | None, *,
    streamline_seed_stride: int = 10, streamline_max_steps: int = 300,
    include_streamlines: bool = True,
) -> dict[str, Any]:
    result = {**network, "features": [{**feature, "properties": dict(feature["properties"])} for feature in network["features"]]}
    if not current_layer or current_layer.get("kind") not in {"vector_grid", "regional_grid"} or not current_layer.get("geojson"):
        return result
    samples = []
    for feature in current_layer["geojson"].get("features", []):
        try:
            longitude, latitude = feature["geometry"]["coordinates"]
            east, north = float(feature["properties"]["u_m_s"]), float(feature["properties"]["v_m_s"])
            x, y = TO_UTM(longitude, latitude)
            if all(math.isfinite(value) for value in (east, north, x, y)) and math.hypot(east, north) >= 0.05:
                samples.append((Point(x, y), east, north))
        except (KeyError, TypeError, ValueError):
            continue
    if not samples:
        return result
    water_utm = transform(TO_UTM, context_water_geometry())
    source = current_layer.get("provenance", {}).get("source", "provider current vector grid")
    streamlines = _build_flow_streamlines(
        samples, water_utm, source=source, min_speed_m_s=0.05,
        seed_stride=streamline_seed_stride, max_steps=streamline_max_steps,
    ) if include_streamlines else []
    influenced = 0
    for feature in result["features"]:
        route = transform(TO_UTM, LineString(feature["geometry"]["coordinates"]))
        nearby = [(east, north) for point, east, north in samples if route.distance(point) <= 5_000]
        if not nearby:
            continue
        mean_east = sum(item[0] for item in nearby) / len(nearby)
        mean_north = sum(item[1] for item in nearby) / len(nearby)
        start, end = route.coords[0], route.coords[-1]
        delta_x, delta_y = end[0] - start[0], end[1] - start[1]
        length = math.hypot(delta_x, delta_y)
        if length <= 0:
            continue
        unit_x, unit_y = delta_x / length, delta_y / length
        projected = mean_east * unit_x + mean_north * unit_y
        speed = math.hypot(mean_east, mean_north)
        properties = feature["properties"]
        properties.update({
            "current_sample_count": len(nearby), "mean_current_speed_m_s": round(speed, 4),
            "forward_alignment": round(projected / speed, 4) if speed > 0 else 0,
            "forward_projected_speed_m_s": round(projected, 4),
            "forward_travel_hours": round(length / projected / 3600, 2) if projected > 0.01 else None,
            "mean_current_bearing_degrees": round((math.degrees(math.atan2(mean_east, mean_north)) + 360) % 360, 1),
            "route_type": "flow_aligned" if projected > 0.01 else "flow_against_or_cross",
            "influence_status": "exploratory",
        })
        influenced += 1
    result["influence_status"] = "exploratory" if influenced else "unavailable"
    result["influence_reason"] = None if influenced else "no_current_cells_near_edges"
    result["influenced_edge_count"] = influenced
    result["features"].extend(streamlines)
    result["flow_streamline_count"] = len(streamlines)
    return result
