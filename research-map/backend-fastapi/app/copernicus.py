"""Optional Copernicus grid adapters, executed only by the snapshot worker."""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.domain import point_inside_context
from app.providers import unavailable_layer


def _coordinates(data_array):
    longitude = next((name for name in data_array.coords if name.lower() in {"longitude", "lon"}), None)
    latitude = next((name for name in data_array.coords if name.lower() in {"latitude", "lat"}), None)
    if not longitude or not latitude:
        raise ValueError("copernicus_coordinates_unrecognised")
    return latitude, longitude


def _surface_nearest(data_array, requested_at: datetime):
    selected = data_array
    for dimension in list(selected.dims):
        lowered = dimension.lower()
        if lowered == "time":
            try:
                selected = selected.sel({dimension: requested_at.replace(tzinfo=None)}, method="nearest")
            except Exception:
                selected = selected.isel({dimension: 0})
        elif lowered in {"depth", "depthu", "depthv"}:
            selected = selected.isel({dimension: 0})
    return selected.squeeze(drop=True)


def _as_iso_datetime(value: object, fallback: datetime) -> str:
    try:
        import pandas as pd

        converted = pd.Timestamp(value)
        if converted.tzinfo is None:
            converted = converted.tz_localize("UTC")
        return converted.isoformat()
    except Exception:
        return fallback.isoformat()


def _grid_resolution(data_array) -> str:
    try:
        import numpy as np

        lat_name, lon_name = _coordinates(data_array)
        lat = data_array[lat_name].values.astype(float)
        lon = data_array[lon_name].values.astype(float)
        lat_step = float(np.nanmedian(np.abs(np.diff(lat)))) if len(lat) > 1 else float("nan")
        lon_step = float(np.nanmedian(np.abs(np.diff(lon)))) if len(lon) > 1 else float("nan")
        return f"{lon_step:.5g}° x {lat_step:.5g}°"
    except Exception:
        return "provider grid; see dataset metadata"


def _metadata(*, dataset_id: str, dataset, target: Path, now: datetime, valid_at: str, stale_minutes: int, convention: str) -> dict[str, Any]:
    return {
        "source": "Copernicus Marine analysis/forecast spatial subset",
        "provider": "copernicus_marine",
        "product_id": dataset_id,
        "dataset_version": str(dataset.attrs.get("product_version", dataset.attrs.get("version", "provider_current"))),
        "grid_resolution": _grid_resolution(next(iter(dataset.data_vars.values()))),
        "issued_at": now.isoformat(), "valid_at": valid_at, "retrieved_at": now.isoformat(),
        "payload_hash": hashlib.sha256(target.read_bytes()).hexdigest(),
        "stale_after": (now + timedelta(minutes=stale_minutes)).isoformat(),
        "direction_convention": convention,
    }


def _download_subset(*, dataset_id: str, variables: list[str], bbox: list[float], username: str, password: str, cache_dir: str, tag: str):
    import copernicusmarine
    import xarray as xr

    now = datetime.now(timezone.utc)
    target = Path(cache_dir) / f"copernicus-{tag}-{now:%Y%m%dT%H%M%S}.nc"
    target.parent.mkdir(parents=True, exist_ok=True)
    kwargs = dict(
        dataset_id=dataset_id, username=username, password=password, variables=variables,
        minimum_longitude=float(bbox[0]), maximum_longitude=float(bbox[2]),
        minimum_latitude=float(bbox[1]), maximum_latitude=float(bbox[3]),
        start_datetime=(now - timedelta(hours=6)).isoformat(), end_datetime=(now + timedelta(hours=6)).isoformat(),
        coordinates_selection_method="outside", output_directory=str(target.parent), output_filename=target.name,
    )
    # Wave and sea-level products may have no depth dimension. Retry without
    # the surface constraint when the dataset rejects it.
    try:
        copernicusmarine.subset(**kwargs, minimum_depth=0, maximum_depth=1)
    except Exception:
        copernicusmarine.subset(**kwargs)
    return xr.open_dataset(target), target, now


def _valid_time(dataset, now: datetime) -> str:
    coordinate = dataset.coords.get("time")
    if coordinate is None or not len(coordinate):
        return now.isoformat()
    try:
        import pandas as pd

        timestamps = pd.to_datetime(coordinate.values, utc=True)
        nearest = min(timestamps, key=lambda value: abs(value.to_pydatetime() - now))
        return nearest.isoformat()
    except Exception:
        return _as_iso_datetime(coordinate[0].item(), now)


def _point_features(data_array, value_name: str, *, buffer_m: int, extra: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    lat_name, lon_name = _coordinates(data_array)
    features: list[dict[str, Any]] = []
    for lat_index in range(data_array.sizes[lat_name]):
        for lon_index in range(data_array.sizes[lon_name]):
            value = float(data_array.isel({lat_name: lat_index, lon_name: lon_index}).item())
            longitude = float(data_array[lon_name].isel({lon_name: lon_index}).item())
            latitude = float(data_array[lat_name].isel({lat_name: lat_index}).item())
            if not math.isfinite(value) or not point_inside_context(longitude, latitude, buffer_m):
                continue
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [longitude, latitude]}, "properties": {value_name: value, **(extra or {})}})
    return features


def _current_layer(*, dataset_id: str, username: str, password: str, bbox: list[float], stale_minutes: int, buffer_m: int, cache_dir: str) -> dict[str, Any]:
    dataset, target, now = _download_subset(dataset_id=dataset_id, variables=["uo", "vo"], bbox=bbox, username=username, password=password, cache_dir=cache_dir, tag="current")
    try:
        u, v = _surface_nearest(dataset["uo"], now), _surface_nearest(dataset["vo"], now)
        lat_name, lon_name = _coordinates(u)
        features = []
        for lat_index in range(u.sizes[lat_name]):
            for lon_index in range(u.sizes[lon_name]):
                east = float(u.isel({lat_name: lat_index, lon_name: lon_index}).item())
                north = float(v.isel({lat_name: lat_index, lon_name: lon_index}).item())
                longitude = float(u[lon_name].isel({lon_name: lon_index}).item())
                latitude = float(u[lat_name].isel({lat_name: lat_index}).item())
                if not all(math.isfinite(value) for value in (east, north)) or not point_inside_context(longitude, latitude, buffer_m):
                    continue
                features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [longitude, latitude]}, "properties": {"u_m_s": east, "v_m_s": north, "speed_m_s": math.hypot(east, north), "display_bearing_degrees": (90 - math.degrees(math.atan2(north, east))) % 360, "depth_m": 0}})
        metadata = _metadata(dataset_id=dataset_id, dataset=dataset, target=target, now=now, valid_at=_valid_time(dataset, now), stale_minutes=stale_minutes, convention="uo/vo converted to display_to")
        return {"layer": "current", "status": "fresh", "kind": "vector_grid", "reason_code": None, "provenance": metadata, "geojson": {"type": "FeatureCollection", "features": features}, "raster": {"source_cell_count": int(u.size), "display_cell_count": len(features), "domain_filtered": True}}
    finally:
        dataset.close()


def _scalar_layer(*, layer_name: str, variable: str, dataset_id: str, username: str, password: str, bbox: list[float], stale_minutes: int, buffer_m: int, cache_dir: str) -> dict[str, Any]:
    dataset, target, now = _download_subset(dataset_id=dataset_id, variables=[variable], bbox=bbox, username=username, password=password, cache_dir=cache_dir, tag=layer_name)
    try:
        values = _surface_nearest(dataset[variable], now)
        features = _point_features(values, "value", buffer_m=buffer_m, extra={"variable": variable, "unit": values.attrs.get("units")})
        metadata = _metadata(dataset_id=dataset_id, dataset=dataset, target=target, now=now, valid_at=_valid_time(dataset, now), stale_minutes=stale_minutes, convention="not_applicable")
        return {"layer": layer_name, "status": "fresh", "kind": "scalar_grid", "reason_code": None, "provenance": metadata, "geojson": {"type": "FeatureCollection", "features": features}, "raster": {"variable": variable, "source_cell_count": int(values.size), "display_cell_count": len(features), "domain_filtered": True}}
    finally:
        dataset.close()


def _wave_layer(*, dataset_id: str, username: str, password: str, bbox: list[float], stale_minutes: int, buffer_m: int, cache_dir: str) -> dict[str, Any]:
    dataset, target, now = _download_subset(dataset_id=dataset_id, variables=["VHM0", "VMDR", "VTPK"], bbox=bbox, username=username, password=password, cache_dir=cache_dir, tag="wave")
    try:
        height, direction, period = (_surface_nearest(dataset[name], now) for name in ("VHM0", "VMDR", "VTPK"))
        lat_name, lon_name = _coordinates(height)
        direction_is_from = "from_direction" in str(direction.attrs.get("standard_name", "")).lower()
        features = []
        for lat_index in range(height.sizes[lat_name]):
            for lon_index in range(height.sizes[lon_name]):
                wave_height = float(height.isel({lat_name: lat_index, lon_name: lon_index}).item())
                wave_direction = float(direction.isel({lat_name: lat_index, lon_name: lon_index}).item())
                wave_period = float(period.isel({lat_name: lat_index, lon_name: lon_index}).item())
                longitude = float(height[lon_name].isel({lon_name: lon_index}).item())
                latitude = float(height[lat_name].isel({lat_name: lat_index}).item())
                if not all(math.isfinite(value) for value in (wave_height, wave_direction, wave_period)) or not point_inside_context(longitude, latitude, buffer_m):
                    continue
                display = (wave_direction + 180) % 360 if direction_is_from else wave_direction % 360
                features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [longitude, latitude]}, "properties": {"height_m": wave_height, "period_s": wave_period, "provider_direction_degrees": wave_direction, "display_bearing_degrees": display}})
        convention = "wave_from converted to display_to" if direction_is_from else "provider wave direction displayed unchanged"
        metadata = _metadata(dataset_id=dataset_id, dataset=dataset, target=target, now=now, valid_at=_valid_time(dataset, now), stale_minutes=stale_minutes, convention=convention)
        return {"layer": "wave", "status": "fresh", "kind": "vector_grid", "reason_code": None, "provenance": metadata, "geojson": {"type": "FeatureCollection", "features": features}, "raster": {"source_cell_count": int(height.size), "display_cell_count": len(features), "domain_filtered": True}}
    finally:
        dataset.close()


def fetch_copernicus_layers(*, username: str, password: str, current_dataset: str, sea_level_dataset: str, mld_dataset: str, wave_dataset: str, bbox: list[float], stale_minutes: int, buffer_m: int, cache_dir: str = "/cache") -> list[dict[str, Any]]:
    """Fetch configured layers independently so one dataset failure is isolated."""
    if not username or not password:
        return []
    specifications = [
        ("current", current_dataset, lambda dataset_id: _current_layer(dataset_id=dataset_id, username=username, password=password, bbox=bbox, stale_minutes=stale_minutes, buffer_m=buffer_m, cache_dir=cache_dir)),
        ("sea_level", sea_level_dataset, lambda dataset_id: _scalar_layer(layer_name="sea_level", variable="zos", dataset_id=dataset_id, username=username, password=password, bbox=bbox, stale_minutes=stale_minutes, buffer_m=buffer_m, cache_dir=cache_dir)),
        ("mixed_layer_depth", mld_dataset, lambda dataset_id: _scalar_layer(layer_name="mixed_layer_depth", variable="mlotst", dataset_id=dataset_id, username=username, password=password, bbox=bbox, stale_minutes=stale_minutes, buffer_m=buffer_m, cache_dir=cache_dir)),
        ("wave", wave_dataset, lambda dataset_id: _wave_layer(dataset_id=dataset_id, username=username, password=password, bbox=bbox, stale_minutes=stale_minutes, buffer_m=buffer_m, cache_dir=cache_dir)),
    ]
    layers: list[dict[str, Any]] = []
    for layer_name, dataset_id, loader in specifications:
        if not dataset_id:
            continue
        try:
            layers.append(loader(dataset_id))
        except Exception as exc:
            layers.append(unavailable_layer(layer_name, f"copernicus_subset_failed:{type(exc).__name__}"))
    return layers
