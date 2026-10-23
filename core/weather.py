"""Read-only weather enrichment for a monitoring station."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import urlopen

from core.config import (
    MARINE_ENABLED,
    MARINE_PROVIDER,
    WEATHER_CACHE_TTL_MINUTES,
    WEATHER_ENABLED,
    WEATHER_PROVIDER,
    weather_location_for_station,
)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
HOURLY_VARIABLES = "temperature_2m,relative_humidity_2m,precipitation,cloud_cover,surface_pressure,wind_speed_10m,wind_direction_10m"
MARINE_HOURLY_VARIABLES = "wave_height,wave_direction,wave_period,ocean_current_velocity,ocean_current_direction,sea_level_height_msl,sea_surface_temperature"
_CACHE: dict[str, tuple[float, dict]] = {}
_MARINE_CACHE: dict[str, tuple[float, dict]] = {}


def _fetch_open_meteo(location: dict, timeout_seconds: int = 10) -> dict:
    query = urlencode({"latitude": location["latitude"], "longitude": location["longitude"], "hourly": HOURLY_VARIABLES, "forecast_days": 3, "timezone": "Asia/Ho_Chi_Minh"})
    with urlopen(f"{OPEN_METEO_URL}?{query}", timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_open_meteo_marine(location: dict, timeout_seconds: int = 10) -> dict:
    query = urlencode({
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "hourly": MARINE_HOURLY_VARIABLES,
        "forecast_days": 3,
        "timezone": "Asia/Ho_Chi_Minh",
        "cell_selection": "sea",
    })
    with urlopen(f"{OPEN_METEO_MARINE_URL}?{query}", timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def get_station_weather(station_serial: str, now: float | None = None) -> dict:
    """Return provider forecast with a process-local TTL cache; never raises."""
    if not WEATHER_ENABLED:
        return {"status": "disabled", "reason": "weather_disabled"}
    if WEATHER_PROVIDER != "open_meteo":
        return {"status": "unavailable", "reason": "unsupported_provider"}
    location = weather_location_for_station(station_serial)
    if location is None:
        return {"status": "unavailable", "reason": "station_coordinates_missing"}
    now = time.time() if now is None else now
    cached = _CACHE.get(station_serial)
    if cached and now - cached[0] < max(1, WEATHER_CACHE_TTL_MINUTES) * 60:
        return {**cached[1], "cache": "hit"}
    try:
        provider_data = _fetch_open_meteo(location)
    except Exception as exc:
        if cached:
            stale_payload = {**cached[1], "status": "stale", "cache": "stale", "stale_age_seconds": max(0, int(now - cached[0])), "reason": "provider_request_failed_using_last_known_good", "detail": str(exc)}
            return stale_payload
        return {"status": "unavailable", "reason": "provider_request_failed", "detail": str(exc)}
    payload = {"status": "ready", "provider": "open_meteo", "retrieved_at": datetime.now(timezone.utc).isoformat(), "location": location, "timezone": provider_data.get("timezone", "Asia/Ho_Chi_Minh"), "hourly": provider_data.get("hourly", {}), "hourly_units": provider_data.get("hourly_units", {}), "model": provider_data.get("model"), "cache": "miss", "used_by_models": False, "used_by_alerts": False}
    _CACHE[station_serial] = (now, payload)
    return payload


def get_station_environment(station_serial: str, *, weather: dict | None = None, now: float | None = None) -> dict:
    """Return station weather plus optional point marine context.

    The regional research-map grid remains the source for map rendering.  This
    adapter is deliberately point-based and keeps marine data separate so a
    missing marine layer can never silently become a zero-valued feature.
    """
    weather_payload = weather if weather is not None else get_station_weather(station_serial, now=now)
    result = {"status": weather_payload.get("status", "unavailable"), "weather": weather_payload, "marine": {"status": "disabled", "reason": "marine_disabled"}}
    if not MARINE_ENABLED:
        return result
    if MARINE_PROVIDER != "open_meteo":
        result["marine"] = {"status": "unavailable", "reason": "unsupported_provider"}
        return result
    location = weather_location_for_station(station_serial)
    if location is None:
        result["marine"] = {"status": "unavailable", "reason": "station_coordinates_missing"}
        return result
    timestamp = time.time() if now is None else now
    cached = _MARINE_CACHE.get(station_serial)
    if cached and timestamp - cached[0] < max(1, WEATHER_CACHE_TTL_MINUTES) * 60:
        result["marine"] = {**cached[1], "cache": "hit"}
        result["status"] = "ready" if weather_payload.get("status") in {"ready", "stale"} else weather_payload.get("status", "unavailable")
        return result
    try:
        provider_data = _fetch_open_meteo_marine(location)
    except Exception as exc:
        if cached:
            result["marine"] = {**cached[1], "status": "stale", "cache": "stale", "reason": "provider_request_failed_using_last_known_good", "detail": str(exc)}
        else:
            result["marine"] = {"status": "unavailable", "reason": "provider_request_failed", "detail": str(exc)}
        result["status"] = "stale" if weather_payload.get("status") == "stale" else weather_payload.get("status", "unavailable")
        return result
    payload = {
        "status": "ready",
        "provider": "open_meteo_marine",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "location": location,
        "timezone": provider_data.get("timezone", "Asia/Ho_Chi_Minh"),
        "hourly": provider_data.get("hourly", {}),
        "hourly_units": provider_data.get("hourly_units", {}),
        "model": provider_data.get("model"),
        "used_by_models": False,
        "used_by_alerts": False,
    }
    _MARINE_CACHE[station_serial] = (timestamp, payload)
    result["marine"] = payload
    result["status"] = "ready" if weather_payload.get("status") in {"ready", "stale"} else weather_payload.get("status", "unavailable")
    return result
