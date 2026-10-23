"""Provider adapters.  They produce provenance-rich, provider-neutral layers."""
from __future__ import annotations

import hashlib
import asyncio
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from shapely import prepare
from shapely.geometry import Point, box, mapping

from app.domain import context_water_geometry, point_inside_context


OPEN_METEO_WEATHER = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_MARINE = "https://marine-api.open-meteo.com/v1/marine"


def display_bearing(direction_from_degrees: float) -> float:
    """Convert meteorological 'from' direction to an arrow's 'to' bearing."""
    return (float(direction_from_degrees) + 180.0) % 360.0


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def _grid_points(bbox: list[float], buffer_m: int) -> tuple[list[tuple[float, float]], float]:
    """Create a bounded ~1–1.2 km provider query grid over the water domain."""
    min_lon, min_lat, max_lon, max_lat = bbox
    span_lon, span_lat = max_lon - min_lon, max_lat - min_lat
    # The provider is still the source of every sample; this only makes the
    # displayed water cells smaller and gives the map a useful spatial grain.
    step = max(0.008, min(0.01, max(span_lon, span_lat) / 32))
    nx = max(2, min(32, int(span_lon / step) + 1))
    ny = max(2, min(32, int(span_lat / step) + 1))
    lons = [min_lon + (max_lon - min_lon) * i / (nx - 1) for i in range(nx)]
    lats = [min_lat + (max_lat - min_lat) * j / (ny - 1) for j in range(ny)]
    water = context_water_geometry(buffer_m)
    prepare(water)
    points = [(lon, lat) for lat in lats for lon in lons if water.covers(Point(lon, lat))]
    return points, max(span_lon / max(nx - 1, 1), span_lat / max(ny - 1, 1))


def _as_response_list(payload: Any) -> list[dict[str, Any]]:
    return payload if isinstance(payload, list) else [payload]


def _sample_feature(longitude: float, latitude: float, properties: dict[str, Any], geometry: Any | None = None) -> dict[str, Any]:
    return {"type": "Feature", "geometry": mapping(geometry) if geometry is not None else {"type": "Point", "coordinates": [longitude, latitude]}, "properties": properties}


def _parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _hour_index(hourly: dict[str, list[Any]], now: datetime) -> int:
    timestamps = [_parse_time(value) for value in hourly.get("time", [])]
    if not timestamps:
        raise ValueError("provider_hourly_time_missing")
    return min(range(len(timestamps)), key=lambda index: abs(timestamps[index] - now))


def _number(value: Any) -> float | None:
    """Return a finite provider value, preserving null as missing data."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def normalize_speed(value: Any, unit: str | None) -> float | None:
    """Normalize Open-Meteo current velocity to m/s.

    Open-Meteo documents km/h as the default velocity unit, but returns the
    actual selected unit in ``hourly_units``.  Never silently treat a missing
    value as calm or a km/h value as m/s.
    """
    number = _number(value)
    if number is None:
        return None
    normalized = (unit or "km/h").strip().lower().replace(" ", "")
    if normalized in {"km/h", "kmh", "kph"}:
        return number / 3.6
    if normalized in {"m/s", "ms-1", "mps"}:
        return number
    if normalized in {"kn", "knot", "knots"}:
        return number * 0.514444
    if normalized in {"mph"}:
        return number * 0.44704
    raise ValueError(f"unsupported_current_velocity_unit:{unit}")


def normalize_current_speed(value: Any, unit: str | None) -> float | None:
    """Backward-compatible name for current velocity normalization."""
    return normalize_speed(value, unit)


def _provenance(*, source: str, product_id: str, resolution: str, retrieved_at: datetime, valid_at: datetime, payload_hash: str, stale_minutes: int, convention: str, source_resolution: str | None = None, temporal_mode: str = "hourly_nearest") -> dict[str, Any]:
    return {
        "source": source, "provider": "open_meteo", "product_id": product_id,
        "dataset_version": None, "grid_resolution": resolution,
        "display_grid_resolution": resolution,
        "source_grid_resolution": source_resolution or resolution,
        "temporal_mode": temporal_mode,
        "issued_at": retrieved_at.isoformat(), "valid_at": valid_at.isoformat(),
        "retrieved_at": retrieved_at.isoformat(), "payload_hash": payload_hash,
        "stale_after": (retrieved_at + timedelta(minutes=stale_minutes)).isoformat(),
        "direction_convention": convention,
    }


async def fetch_open_meteo_context(latitude: float, longitude: float, stale_minutes: int, client: httpx.AsyncClient | None = None, bbox: list[float] | None = None, buffer_m: int = 5_000) -> list[dict[str, Any]]:
    """Fetch a provider-backed spatial grid over the water domain.

    With no bbox this retains the single-point compatibility path. With a bbox,
    every displayed cell is an independently issued Open-Meteo sample; no
    interpolation or synthetic vector field is introduced.
    """
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=20)
    retrieved_at = datetime.now(timezone.utc)
    try:
        points, grid_step = _grid_points(bbox, buffer_m) if bbox else ([(longitude, latitude)], 0.0)
        weather_payloads: list[Any] = []
        marine_payloads: list[Any] = []
        # Keep URLs small enough for Open-Meteo/proxy limits while retaining
        # the finer spatial grid in one immutable snapshot.
        for offset in range(0, len(points), 80):
            batch = points[offset:offset + 80]
            query_latitudes = ",".join(f"{lat:.5f}" for lon, lat in batch)
            query_longitudes = ",".join(f"{lon:.5f}" for lon, lat in batch)
            params_weather = {"latitude": query_latitudes, "longitude": query_longitudes, "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation", "forecast_days": 2, "timezone": "UTC"}
            params_marine = {"latitude": query_latitudes, "longitude": query_longitudes, "hourly": "wave_height,wave_direction,wave_period,ocean_current_velocity,ocean_current_direction,sea_level_height_msl", "forecast_days": 2, "timezone": "UTC", "cell_selection": "sea"}
            weather_response, marine_response = await asyncio.gather(client.get(OPEN_METEO_WEATHER, params=params_weather), client.get(OPEN_METEO_MARINE, params=params_marine))
            weather_response.raise_for_status(); marine_response.raise_for_status()
            weather_payloads.extend(_as_response_list(weather_response.json()))
            marine_payloads.extend(_as_response_list(marine_response.json()))
        weather_items, marine_items = weather_payloads, marine_payloads
        if len(weather_items) != len(points) or len(marine_items) != len(points):
            raise ValueError("provider_grid_response_count_mismatch")
        raw = json.dumps({"weather": weather_payloads, "marine": marine_payloads}, sort_keys=True, separators=(",", ":")).encode()
        payload_hash = hashlib.sha256(raw).hexdigest()
        wind_features: list[dict[str, Any]] = []
        rain_features: list[dict[str, Any]] = []
        wave_features: list[dict[str, Any]] = []
        current_features: list[dict[str, Any]] = []
        sea_level_features: list[dict[str, Any]] = []
        advisory_features: list[dict[str, Any]] = []
        weather_valid, marine_valid = None, None
        provider_coords: list[tuple[float, float]] = []
        current_units: set[str] = set()
        for (requested_lon, requested_lat), weather, marine in zip(points, weather_items, marine_items):
            weather_hourly, marine_hourly = weather["hourly"], marine["hourly"]
            weather_index, marine_index = _hour_index(weather_hourly, retrieved_at), _hour_index(marine_hourly, retrieved_at)
            weather_valid = _parse_time(weather_hourly["time"][weather_index])
            marine_valid = _parse_time(marine_hourly["time"][marine_index])
            provider_lon = _number(marine.get("longitude")) or requested_lon
            provider_lat = _number(marine.get("latitude")) or requested_lat
            provider_coords.append((provider_lon, provider_lat))
            
            # Tính forecast 6h cho advisory
            series_valid = True
            rain_6h = None
            wind_6h = None
            if weather_index + 6 <= len(weather_hourly.get("time", [])):
                time_series = weather_hourly.get("time", [])[weather_index:weather_index+6]
                rain_series = weather_hourly.get("precipitation", [])[weather_index:weather_index+6]
                wind_series = weather_hourly.get("wind_speed_10m", [])[weather_index:weather_index+6]
                wind_unit = weather.get("hourly_units", {}).get("wind_speed_10m", "km/h")
                
                if len(time_series) == 6 and len(rain_series) == 6 and len(wind_series) == 6 and not any(_number(v) is None for v in rain_series) and not any(_number(v) is None for v in wind_series):
                    try:
                        from datetime import timedelta
                        times = [_parse_time(t) for t in time_series]
                        gaps = [(times[i+1] - times[i]).total_seconds() for i in range(5)]
                        if all(g == 3600 for g in gaps) and (retrieved_at - times[0]).total_seconds() <= 3600:
                            rain_6h = sum(_number(v) for v in rain_series)
                            wind_6h_ms = max(normalize_speed(v, wind_unit) for v in wind_series)
                            wind_6h = wind_6h_ms * 3.6 if wind_6h_ms is not None else None
                        else:
                            series_valid = False
                    except Exception:
                        series_valid = False
                else:
                    series_valid = False
            else:
                series_valid = False
                
            advisory_features.append({
                "lon": provider_lon, "lat": provider_lat, 
                "rain_6h_mm": rain_6h if series_valid else None,
                "wind_6h_kmh": wind_6h if series_valid else None,
                "series_complete": series_valid
            })
            
            wind_from = _number(weather_hourly["wind_direction_10m"][weather_index])
            wave_from = _number(marine_hourly["wave_direction"][marine_index])
            current_to = _number(marine_hourly["ocean_current_direction"][marine_index])
            wind_unit = weather.get("hourly_units", {}).get("wind_speed_10m", "km/h")
            wind_speed = normalize_speed(weather_hourly["wind_speed_10m"][weather_index], wind_unit)
            wind_gust = normalize_speed(weather_hourly["wind_gusts_10m"][weather_index], wind_unit)
            base_props = {"requested_lat": requested_lat, "requested_lon": requested_lon, "provider_lat": provider_lat, "provider_lon": provider_lon}
            if wind_from is not None and wind_speed is not None:
                wind_display = display_bearing(wind_from)
                wind_radians = math.radians(wind_display)
                # Render at the requested water-only sample location. Several
                # nearby requests can legitimately resolve to one coarse
                # provider cell; using provider coordinates collapsed them to
                # a few dots and hid the intended water-domain coverage.
                wind_features.append(_sample_feature(requested_lon, requested_lat, {
                    **base_props, 
                    "speed_m_s": wind_speed, 
                    "gust_m_s": wind_gust, 
                    "source_speed_unit": wind_unit, 
                    "direction_from_degrees": wind_from, 
                    "display_bearing_degrees": wind_display,
                    "u_m_s": wind_speed * math.sin(wind_radians),
                    "v_m_s": wind_speed * math.cos(wind_radians)
                }))
            marine_cell = box(requested_lon - grid_step / 2, requested_lat - grid_step / 2, requested_lon + grid_step / 2, requested_lat + grid_step / 2)
            try:
                clipped_cell = marine_cell.intersection(context_water_geometry(buffer_m))
            except Exception:
                clipped_cell = marine_cell
            if not clipped_cell.is_empty:
                rain_value = _number(weather_hourly["precipitation"][weather_index])
                sea_level_value = _number(marine_hourly["sea_level_height_msl"][marine_index])
                if rain_value is not None:
                    rain_features.append(_sample_feature(provider_lon, provider_lat, {**base_props, "value": rain_value, "variable": "precipitation", "unit": "mm"}, clipped_cell))
                if sea_level_value is not None:
                    sea_level_features.append(_sample_feature(provider_lon, provider_lat, {**base_props, "value": sea_level_value, "variable": "sea_level_height_msl", "unit": "m"}, clipped_cell))
            wave_height = _number(marine_hourly["wave_height"][marine_index])
            wave_period = _number(marine_hourly["wave_period"][marine_index])
            if wave_from is not None and wave_height is not None:
                wave_features.append(_sample_feature(requested_lon, requested_lat, {**base_props, "height_m": wave_height, "period_s": wave_period, "direction_from_degrees": wave_from, "display_bearing_degrees": display_bearing(wave_from)}))
            current_unit = marine.get("hourly_units", {}).get("ocean_current_velocity", "km/h")
            current_units.add(str(current_unit))
            current_speed = normalize_current_speed(marine_hourly["ocean_current_velocity"][marine_index], current_unit)
            if current_speed is not None and current_to is not None:
                current_radians = math.radians(current_to)
                current_features.append(_sample_feature(requested_lon, requested_lat, {**base_props, "speed_m_s": current_speed, "source_speed": _number(marine_hourly["ocean_current_velocity"][marine_index]), "source_speed_unit": current_unit, "display_bearing_degrees": current_to, "calm": current_speed < 0.35, "u_m_s": current_speed * math.sin(current_radians), "v_m_s": current_speed * math.cos(current_radians)}))
        resolution = f"display grid ~{grid_step * 111:.1f} km; water-clipped" if bbox else "provider grid; sampled at anchor"
        marine_source_resolution = "Open-Meteo marine model; resolution depends on selected wave/current product"
        current_source_resolution = "Open-Meteo ocean-current model ~8 km (0.08°); not a 1 km observation grid"
        kind = "regional_grid" if bbox else "regional_point"
        return [
            {"layer": "wind", "status": "fresh", "kind": kind, "reason_code": None, "provenance": _provenance(source="Open-Meteo forecast grid" if bbox else "regional forecast point", product_id="open-meteo-weather", resolution=resolution, retrieved_at=retrieved_at, valid_at=weather_valid, payload_hash=payload_hash, stale_minutes=stale_minutes, convention="wind_from converted to display_to", source_resolution="Open-Meteo weather model; see provider metadata"), "geojson": _feature_collection(wind_features), "raster": {"display_cell_count": len(wind_features), "domain_filtered": bool(bbox)}},
            {"layer": "rain", "status": "fresh", "kind": "scalar_grid" if bbox else kind, "reason_code": None, "provenance": _provenance(source="Open-Meteo forecast grid" if bbox else "regional forecast point", product_id="open-meteo-weather", resolution=resolution, retrieved_at=retrieved_at, valid_at=weather_valid, payload_hash=payload_hash, stale_minutes=stale_minutes, convention="not_applicable", source_resolution="Open-Meteo weather model; see provider metadata"), "geojson": _feature_collection(rain_features), "raster": {"display_cell_count": len(rain_features), "domain_filtered": bool(bbox)}},
            {"layer": "wave", "status": "fresh", "kind": kind, "reason_code": None, "provenance": _provenance(source="Open-Meteo marine forecast grid" if bbox else "regional marine forecast point", product_id="open-meteo-marine", resolution=resolution, retrieved_at=retrieved_at, valid_at=marine_valid, payload_hash=payload_hash, stale_minutes=stale_minutes, convention="wave_from converted to display_to", source_resolution=marine_source_resolution), "geojson": _feature_collection(wave_features), "raster": {"display_cell_count": len(wave_features), "domain_filtered": bool(bbox)}},
            {"layer": "current", "status": "fresh", "kind": kind, "reason_code": "copernicus_grid_not_configured", "provenance": _provenance(source="Open-Meteo marine forecast grid" if bbox else "regional marine forecast point", product_id="open-meteo-marine", resolution=resolution, retrieved_at=retrieved_at, valid_at=marine_valid, payload_hash=payload_hash, stale_minutes=stale_minutes, convention=f"current direction is provider to-bearing; velocity normalized to m/s from {','.join(sorted(current_units)) or 'unknown'}", source_resolution=current_source_resolution), "geojson": _feature_collection(current_features), "raster": {"display_cell_count": len(current_features), "domain_filtered": bool(bbox)}},
            {"layer": "sea_level", "status": "fresh", "kind": "scalar_grid" if bbox else kind, "reason_code": "copernicus_ssh_grid_not_configured", "provenance": _provenance(source="Open-Meteo marine forecast grid" if bbox else "regional marine forecast point", product_id="open-meteo-marine", resolution=resolution, retrieved_at=retrieved_at, valid_at=marine_valid, payload_hash=payload_hash, stale_minutes=stale_minutes, convention="not_applicable", source_resolution="Open-Meteo marine model ~8 km (0.08°); smooth display is interpolation, not finer data"), "geojson": _feature_collection(sea_level_features), "raster": {"display_cell_count": len(sea_level_features), "domain_filtered": bool(bbox)}},
            {"layer": "advisory_forecast", "status": "fresh", "kind": "point_cloud", "reason_code": None, "provenance": _provenance(source="Open-Meteo 6h forecast", product_id="open-meteo-weather", resolution=resolution, retrieved_at=retrieved_at, valid_at=weather_valid, payload_hash=payload_hash, stale_minutes=stale_minutes, convention="not_applicable", temporal_mode="6h_forward_aggregation"), "data": advisory_features},
        ]
    finally:
        if owns_client:
            await client.aclose()


def unavailable_layer(name: str, reason_code: str) -> dict[str, Any]:
    return {"layer": name, "status": "unavailable", "kind": "unavailable", "reason_code": reason_code, "provenance": None, "geojson": None, "raster": None}
