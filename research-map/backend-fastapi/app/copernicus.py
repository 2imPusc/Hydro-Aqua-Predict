"""Optional Copernicus grid adapters, executed only by the snapshot worker."""
from __future__ import annotations

import hashlib
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.providers import unavailable_layer

# Re-use a downloaded subset this long (CMEMS GLO12 / MFWAM analysis-forecast is updated once a day).
REUSE_HOURS = 3
# Credentials file written by `copernicusmarine login` (mounted read-only into the worker container).
CREDENTIALS_FILE = Path(os.getenv("COPERNICUS_CREDENTIALS_FILE", str(Path.home() / ".copernicusmarine" / ".copernicusmarine-credentials")))


def _credentials_available() -> bool:
    """A real credentials file (compose mounts an empty placeholder when CMEMS is not configured)."""
    return CREDENTIALS_FILE.is_file() and CREDENTIALS_FILE.stat().st_size > 0


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
        "source_grid_resolution": f"Copernicus Marine {_grid_resolution(next(iter(dataset.data_vars.values())))} (~9 km), whole region",
        "issued_at": now.isoformat(), "valid_at": valid_at, "retrieved_at": now.isoformat(),
        "payload_hash": hashlib.sha256(target.read_bytes()).hexdigest(),
        "stale_after": (now + timedelta(minutes=stale_minutes)).isoformat(),
        "direction_convention": convention,
    }


def _download_subset(*, dataset_id: str, variables: list[str], bbox: list[float], username: str | None, password: str | None, cache_dir: str, tag: str):
    """Spatial subset of one dataset, re-used for REUSE_HOURS (CMEMS analysis/forecast updates daily; the
    window spans now +/- 6 h so a reused file still brackets the current hour). Old files are never rewritten."""
    import copernicusmarine
    import xarray as xr

    now = datetime.now(timezone.utc)
    folder = Path(cache_dir)
    folder.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{dataset_id}:{','.join(variables)}:{','.join(f'{v:.4f}' for v in bbox)}".encode()).hexdigest()[:10]
    recent = sorted(folder.glob(f"copernicus-{tag}-{key}-*.nc"), key=lambda path: path.stat().st_mtime, reverse=True)
    if recent and (now.timestamp() - recent[0].stat().st_mtime) < REUSE_HOURS * 3600:
        return xr.open_dataset(recent[0]), recent[0], now
    target = folder / f"copernicus-{tag}-{key}-{now:%Y%m%dT%H%M%S}.nc"
    kwargs = dict(
        dataset_id=dataset_id, username=username, password=password, variables=variables,
        minimum_longitude=float(bbox[0]), maximum_longitude=float(bbox[2]),
        minimum_latitude=float(bbox[1]), maximum_latitude=float(bbox[3]),
        start_datetime=(now - timedelta(hours=6)).isoformat(), end_datetime=(now + timedelta(hours=6)).isoformat(),
        coordinates_selection_method="outside", output_directory=str(target.parent), output_filename=target.name,
    )
    if username is None and _credentials_available():
        kwargs["credentials_file"] = str(CREDENTIALS_FILE)
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


def _step(data_array) -> float:
    lat_name, lon_name = _coordinates(data_array)
    lon = data_array[lon_name].values.astype(float)
    return round(float(abs(lon[1] - lon[0])), 5) if len(lon) > 1 else 0.0833


def _cells(*arrays):
    """Yield (lon, lat, values) for every lattice node where all arrays are finite (CMEMS land = NaN)."""
    lat_name, lon_name = _coordinates(arrays[0])
    lats = arrays[0][lat_name].values.astype(float)
    lons = arrays[0][lon_name].values.astype(float)
    grids = [array.transpose(lat_name, lon_name).values.astype(float) for array in arrays]
    for j, latitude in enumerate(lats):
        for i, longitude in enumerate(lons):
            values = [grid[j, i] for grid in grids]
            if all(math.isfinite(value) for value in values):
                yield round(float(longitude), 5), round(float(latitude), 5), values


def _point(longitude: float, latitude: float, properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "properties": {"requested_lon": longitude, "requested_lat": latitude, **properties}}


def _current_layer(*, dataset_id: str, username: str | None, password: str | None, bbox: list[float], stale_minutes: int, buffer_m: int, cache_dir: str) -> dict[str, Any]:
    dataset, target, now = _download_subset(dataset_id=dataset_id, variables=["uo", "vo"], bbox=bbox, username=username, password=password, cache_dir=cache_dir, tag="current")
    try:
        u, v = _surface_nearest(dataset["uo"], now), _surface_nearest(dataset["vo"], now)
        features = []
        for longitude, latitude, (east, north) in _cells(u, v):
            speed = math.hypot(east, north)
            features.append(_point(longitude, latitude, {"value": speed, "unit": "m/s", "variable": "sea_water_velocity", "u_m_s": east, "v_m_s": north, "speed_m_s": speed,
                                                         "display_bearing_degrees": (90 - math.degrees(math.atan2(north, east))) % 360, "calm": speed < 0.35, "depth_m": 0}))
        metadata = _metadata(dataset_id=dataset_id, dataset=dataset, target=target, now=now, valid_at=_valid_time(dataset, now), stale_minutes=stale_minutes, convention="uo/vo converted to display_to")
        return {"layer": "current", "status": "fresh", "kind": "regional_grid", "reason_code": None, "provenance": metadata, "geojson": {"type": "FeatureCollection", "features": features},
                "raster": {"source_cell_count": int(u.size), "display_cell_count": len(features), "domain_filtered": False, "step_deg": _step(u), "bbox": list(bbox)}}
    finally:
        dataset.close()


def _scalar_layer(*, layer_name: str, variable: str, dataset_id: str, username: str | None, password: str | None, bbox: list[float], stale_minutes: int, buffer_m: int, cache_dir: str) -> dict[str, Any]:
    dataset, target, now = _download_subset(dataset_id=dataset_id, variables=[variable], bbox=bbox, username=username, password=password, cache_dir=cache_dir, tag=layer_name)
    try:
        values = _surface_nearest(dataset[variable], now)
        unit = values.attrs.get("units")
        features = [_point(longitude, latitude, {"value": value, "variable": variable, "unit": unit}) for longitude, latitude, (value,) in _cells(values)]
        metadata = _metadata(dataset_id=dataset_id, dataset=dataset, target=target, now=now, valid_at=_valid_time(dataset, now), stale_minutes=stale_minutes, convention="not_applicable")
        return {"layer": layer_name, "status": "fresh", "kind": "scalar_grid", "reason_code": None, "provenance": metadata, "geojson": {"type": "FeatureCollection", "features": features},
                "raster": {"variable": variable, "source_cell_count": int(values.size), "display_cell_count": len(features), "domain_filtered": False, "step_deg": _step(values), "bbox": list(bbox)}}
    finally:
        dataset.close()


def _wave_layer(*, dataset_id: str, username: str | None, password: str | None, bbox: list[float], stale_minutes: int, buffer_m: int, cache_dir: str) -> dict[str, Any]:
    dataset, target, now = _download_subset(dataset_id=dataset_id, variables=["VHM0", "VMDR", "VTPK"], bbox=bbox, username=username, password=password, cache_dir=cache_dir, tag="wave")
    try:
        height, direction, period = (_surface_nearest(dataset[name], now) for name in ("VHM0", "VMDR", "VTPK"))
        # MFWAM VMDR is the direction waves come FROM (CF sea_surface_wave_from_direction).
        direction_is_from = "from_direction" in str(direction.attrs.get("standard_name", "from_direction")).lower()
        features = []
        for longitude, latitude, (wave_height, wave_direction, wave_period) in _cells(height, direction, period):
            display = (wave_direction + 180) % 360 if direction_is_from else wave_direction % 360
            radians = math.radians(display)
            features.append(_point(longitude, latitude, {"value": wave_height, "unit": "m", "variable": "VHM0", "height_m": wave_height, "period_s": wave_period,
                                                         "provider_direction_degrees": wave_direction, "display_bearing_degrees": display,
                                                         "u_m_s": wave_height * math.sin(radians), "v_m_s": wave_height * math.cos(radians), "vector_meaning": "travel direction, length = Hs (m)"}))
        convention = "wave_from converted to display_to" if direction_is_from else "provider wave direction displayed unchanged"
        metadata = _metadata(dataset_id=dataset_id, dataset=dataset, target=target, now=now, valid_at=_valid_time(dataset, now), stale_minutes=stale_minutes, convention=convention)
        return {"layer": "wave", "status": "fresh", "kind": "regional_grid", "reason_code": None, "provenance": metadata, "geojson": {"type": "FeatureCollection", "features": features},
                "raster": {"source_cell_count": int(height.size), "display_cell_count": len(features), "domain_filtered": False, "step_deg": _step(height), "bbox": list(bbox)}}
    finally:
        dataset.close()


def fetch_copernicus_layers(*, username: str | None, password: str | None, current_dataset: str, sea_level_dataset: str, mld_dataset: str, wave_dataset: str, bbox: list[float], stale_minutes: int, buffer_m: int, cache_dir: str = "/cache") -> list[dict[str, Any]]:
    """Fetch configured layers independently so one dataset failure is isolated."""
    if not username or not password:
        # No password in the environment: let the toolbox read the credentials file written by
        # `copernicusmarine login` (mounted read-only; the secret never passes through .env or logs).
        if not _credentials_available():
            return []
        username = password = None
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
