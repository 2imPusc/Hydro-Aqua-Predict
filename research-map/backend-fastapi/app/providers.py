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
from shapely.geometry import box, mapping



OPEN_METEO_WEATHER = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_MARINE = "https://marine-api.open-meteo.com/v1/marine"


def display_bearing(direction_from_degrees: float) -> float:
    """Convert meteorological 'from' direction to an arrow's 'to' bearing."""
    return (float(direction_from_degrees) + 180.0) % 360.0


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


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


def _regional_points(bbox: list[float] | tuple[float, ...], step: float, water) -> list[tuple[float, float, bool]]:
    """Regular lon/lat lattice over the region at ``step`` degrees (≈ the provider model grid).

    Every node is returned for the weather fields (rain and wind are real over land too); ``in_water`` marks
    the nodes whose cell touches the OSM water mask, which are the only ones used for marine fields.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    # floor: nodes never fall outside the bbox (the last row/column may stop short of the edge).
    nx = int(math.floor((max_lon - min_lon) / step + 1e-9)) + 1
    ny = int(math.floor((max_lat - min_lat) / step + 1e-9)) + 1
    if water is not None:
        prepare(water)
    points: list[tuple[float, float, bool]] = []
    for j in range(ny):
        lat = round(min_lat + j * step, 5)
        for i in range(nx):
            lon = round(min_lon + i * step, 5)
            cell = box(lon - step / 2, lat - step / 2, lon + step / 2, lat + step / 2)
            points.append((lon, lat, True if water is None else bool(water.intersects(cell))))
    return points


async def fetch_open_meteo_context(latitude: float, longitude: float, stale_minutes: int, client: httpx.AsyncClient | None = None, bbox: list[float] | None = None, buffer_m: int = 5_000, *, region_step: float = 0.125, region_water=None) -> list[dict[str, Any]]:
    """Fetch the regional environment grid (rain, wind, wave, current, sea level, 6 h advisory input).

    With a bbox, Open-Meteo is sampled on a regular lattice of ``region_step`` degrees (~13 km for 0.125°,
    close to the ECMWF IFS / marine model grids) over the whole region; the browser draws a smooth field
    between nodes and the legend says so. Marine values are kept only at nodes whose cell touches water.
    Without a bbox this keeps the single-point compatibility path.
    """
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30)
    retrieved_at = datetime.now(timezone.utc)
    try:
        nodes = _regional_points(bbox, region_step, region_water) if bbox else [(longitude, latitude, True)]
        weather_payloads: list[Any] = []
        marine_payloads: list[Any] = []
        marine_nodes = [node for node in nodes if node[2]]
        # Open-Meteo counts every location as one call: weather for all nodes, marine only for water nodes.
        for points, url, hourly, sink, extra in (
            (nodes, OPEN_METEO_WEATHER, "wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation", weather_payloads, {}),
            (marine_nodes, OPEN_METEO_MARINE, "wave_height,wave_direction,wave_period,ocean_current_velocity,ocean_current_direction,sea_level_height_msl", marine_payloads, {"cell_selection": "sea"}),
        ):
            for offset in range(0, len(points), 80):
                batch = points[offset:offset + 80]
                params = {"latitude": ",".join(f"{lat:.5f}" for lon, lat, _ in batch), "longitude": ",".join(f"{lon:.5f}" for lon, lat, _ in batch),
                          "hourly": hourly, "forecast_days": 2, "timezone": "UTC", **extra}
                response = await client.get(url, params=params)
                response.raise_for_status()
                sink.extend(_as_response_list(response.json()))
        if len(weather_payloads) != len(nodes) or len(marine_payloads) != len(marine_nodes):
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
        current_units: set[str] = set()

        for (requested_lon, requested_lat, _), weather in zip(nodes, weather_payloads):
            weather_hourly = weather["hourly"]
            weather_index = _hour_index(weather_hourly, retrieved_at)
            weather_valid = _parse_time(weather_hourly["time"][weather_index])
            base_props = {"requested_lat": requested_lat, "requested_lon": requested_lon,
                          "provider_lat": _number(weather.get("latitude")), "provider_lon": _number(weather.get("longitude"))}
            wind_unit = weather.get("hourly_units", {}).get("wind_speed_10m", "km/h")

            # 6 h forward rain sum and peak wind: the input of the "Khuyến nghị nuôi trồng" rules (10 mm / 6 h, 35 km/h).
            rain_6h = wind_6h = None
            series_valid = False
            if weather_index + 6 <= len(weather_hourly.get("time", [])):
                time_series = weather_hourly["time"][weather_index:weather_index + 6]
                rain_series = weather_hourly.get("precipitation", [])[weather_index:weather_index + 6]
                wind_series = weather_hourly.get("wind_speed_10m", [])[weather_index:weather_index + 6]
                if len(rain_series) == 6 and len(wind_series) == 6 and all(_number(v) is not None for v in rain_series + wind_series):
                    times = [_parse_time(t) for t in time_series]
                    if all((times[i + 1] - times[i]).total_seconds() == 3600 for i in range(5)) and (retrieved_at - times[0]).total_seconds() <= 3600:
                        rain_6h = sum(_number(v) for v in rain_series)
                        wind_peak = max(normalize_speed(v, wind_unit) for v in wind_series)
                        wind_6h = wind_peak * 3.6 if wind_peak is not None else None
                        series_valid = True
            advisory_features.append({"lon": requested_lon, "lat": requested_lat, "rain_6h_mm": rain_6h if series_valid else None,
                                      "wind_6h_kmh": wind_6h if series_valid else None, "series_complete": series_valid})

            wind_from = _number(weather_hourly["wind_direction_10m"][weather_index])
            wind_speed = normalize_speed(weather_hourly["wind_speed_10m"][weather_index], wind_unit)
            wind_gust = normalize_speed(weather_hourly["wind_gusts_10m"][weather_index], wind_unit)
            if wind_from is not None and wind_speed is not None:
                wind_display = display_bearing(wind_from)
                wind_radians = math.radians(wind_display)
                wind_features.append(_sample_feature(requested_lon, requested_lat, {
                    **base_props, "value": wind_speed, "unit": "m/s", "variable": "wind_speed_10m",
                    "speed_m_s": wind_speed, "gust_m_s": wind_gust, "source_speed_unit": wind_unit,
                    "direction_from_degrees": wind_from, "display_bearing_degrees": wind_display,
                    "u_m_s": wind_speed * math.sin(wind_radians), "v_m_s": wind_speed * math.cos(wind_radians),
                }))
            rain_value = _number(weather_hourly["precipitation"][weather_index])
            if rain_value is not None:
                rain_features.append(_sample_feature(requested_lon, requested_lat, {**base_props, "value": rain_value, "variable": "precipitation", "unit": "mm/h"}))

        for (requested_lon, requested_lat, _), marine in zip(marine_nodes, marine_payloads):
            marine_hourly = marine["hourly"]
            marine_index = _hour_index(marine_hourly, retrieved_at)
            marine_valid = _parse_time(marine_hourly["time"][marine_index])
            base_props = {"requested_lat": requested_lat, "requested_lon": requested_lon,
                          "provider_lat": _number(marine.get("latitude")), "provider_lon": _number(marine.get("longitude"))}
            sea_level_value = _number(marine_hourly["sea_level_height_msl"][marine_index])
            if sea_level_value is not None:
                sea_level_features.append(_sample_feature(requested_lon, requested_lat, {**base_props, "value": sea_level_value, "variable": "sea_level_height_msl", "unit": "m"}))
            wave_from = _number(marine_hourly["wave_direction"][marine_index])
            wave_height = _number(marine_hourly["wave_height"][marine_index])
            wave_period = _number(marine_hourly["wave_period"][marine_index])
            if wave_from is not None and wave_height is not None:
                wave_display = display_bearing(wave_from)
                wave_radians = math.radians(wave_display)
                # u/v carry the travel direction scaled by Hs, only so the particle layer can draw where waves go.
                wave_features.append(_sample_feature(requested_lon, requested_lat, {
                    **base_props, "value": wave_height, "unit": "m", "variable": "wave_height",
                    "height_m": wave_height, "period_s": wave_period, "direction_from_degrees": wave_from, "display_bearing_degrees": wave_display,
                    "u_m_s": wave_height * math.sin(wave_radians), "v_m_s": wave_height * math.cos(wave_radians), "vector_meaning": "travel direction, length = Hs (m)",
                }))
            current_unit = marine.get("hourly_units", {}).get("ocean_current_velocity", "km/h")
            current_units.add(str(current_unit))
            current_to = _number(marine_hourly["ocean_current_direction"][marine_index])
            current_speed = normalize_current_speed(marine_hourly["ocean_current_velocity"][marine_index], current_unit)
            if current_speed is not None and current_to is not None:
                current_radians = math.radians(current_to)
                current_features.append(_sample_feature(requested_lon, requested_lat, {
                    **base_props, "value": current_speed, "unit": "m/s", "variable": "ocean_current_velocity",
                    "speed_m_s": current_speed, "source_speed": _number(marine_hourly["ocean_current_velocity"][marine_index]),
                    "source_speed_unit": current_unit, "display_bearing_degrees": current_to, "calm": current_speed < 0.35,
                    "u_m_s": current_speed * math.sin(current_radians), "v_m_s": current_speed * math.cos(current_radians),
                }))

        step_km = region_step * 111
        resolution = f"query grid {region_step:g}° (~{step_km:.0f} km), whole region" if bbox else "provider grid; sampled at anchor"
        weather_source_resolution = f"Open-Meteo best_match (ECMWF IFS ~9 km / GFS ~13 km); queried every ~{step_km:.0f} km"
        marine_source_resolution = f"Open-Meteo marine (MeteoFrance / ECMWF wave models ~5–25 km); queried every ~{step_km:.0f} km"
        current_source_resolution = f"Open-Meteo ocean-current model ~8 km (0.08°); queried every ~{step_km:.0f} km"
        sea_level_source_resolution = f"Open-Meteo marine model ~8 km (0.08°); queried every ~{step_km:.0f} km"
        kind = "regional_grid" if bbox else "regional_point"
        grid = {"step_deg": region_step, "bbox": list(bbox) if bbox else None}

        def layer(name: str, layer_kind: str, features: list[dict[str, Any]], *, source: str, product: str, valid_at, convention: str, source_resolution: str, reason: str | None = None) -> dict[str, Any]:
            return {"layer": name, "status": "fresh", "kind": layer_kind, "reason_code": reason,
                    "provenance": _provenance(source=source, product_id=product, resolution=resolution, retrieved_at=retrieved_at, valid_at=valid_at, payload_hash=payload_hash,
                                              stale_minutes=stale_minutes, convention=convention, source_resolution=source_resolution),
                    "geojson": _feature_collection(features), "raster": {"display_cell_count": len(features), "domain_filtered": bool(bbox), **grid}}

        scalar = "scalar_grid" if bbox else kind
        return [
            layer("wind", kind, wind_features, source="Open-Meteo forecast grid", product="open-meteo-weather", valid_at=weather_valid, convention="wind_from converted to display_to", source_resolution=weather_source_resolution),
            layer("rain", scalar, rain_features, source="Open-Meteo forecast grid", product="open-meteo-weather", valid_at=weather_valid, convention="not_applicable", source_resolution=weather_source_resolution),
            layer("wave", kind, wave_features, source="Open-Meteo marine forecast grid", product="open-meteo-marine", valid_at=marine_valid, convention="wave_from converted to display_to", source_resolution=marine_source_resolution),
            layer("current", kind, current_features, source="Open-Meteo marine forecast grid", product="open-meteo-marine", valid_at=marine_valid,
                  convention=f"current direction is provider to-bearing; velocity normalized to m/s from {','.join(sorted(current_units)) or 'unknown'}",
                  source_resolution=current_source_resolution, reason="copernicus_grid_not_configured"),
            layer("sea_level", scalar, sea_level_features, source="Open-Meteo marine forecast grid", product="open-meteo-marine", valid_at=marine_valid, convention="not_applicable",
                  source_resolution=sea_level_source_resolution, reason="copernicus_ssh_grid_not_configured"),
            {"layer": "advisory_forecast", "status": "fresh", "kind": "point_cloud", "reason_code": None,
             "provenance": _provenance(source="Open-Meteo 6h forecast", product_id="open-meteo-weather", resolution=resolution, retrieved_at=retrieved_at, valid_at=weather_valid,
                                       payload_hash=payload_hash, stale_minutes=stale_minutes, convention="not_applicable", temporal_mode="6h_forward_aggregation",
                                       source_resolution=weather_source_resolution),
             "data": advisory_features, "raster": grid},
        ]
    finally:
        if owns_client:
            await client.aclose()


def unavailable_layer(name: str, reason_code: str) -> dict[str, Any]:
    return {"layer": name, "status": "unavailable", "kind": "unavailable", "reason_code": reason_code, "provenance": None, "geojson": None, "raster": None}
