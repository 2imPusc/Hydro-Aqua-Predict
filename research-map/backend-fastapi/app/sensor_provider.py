"""Small, append-only GreenLab API adapter for the research-map sensor store."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx


_ALIASES = {"Temp": "Temperature"}
_UNITS = {
    "Temperature": "degC",
    "pH": "pH",
    # The vendor endpoint does not publish unit/basis metadata. Keep these
    # explicit until a signed calibration sheet confirms the conversion.
    "DO": "vendor_unit_unknown",
    "COD": "vendor_unit_unknown",
    "NH4": "vendor_unit_unknown",
    "TSS": "vendor_unit_unknown",
}


def _observation_id(station: str, metric: str, observed_at: datetime, value: float) -> str:
    key = f"greenlab_api|{station}|{metric}|{observed_at.isoformat()}|{value:.12g}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _parse_datetime(raw: Any) -> datetime:
    value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def normalize_readings(readings: list[dict[str, Any]], station_serial: str, retrieved_at: datetime | None = None) -> list[dict[str, Any]]:
    """Convert the vendor's latest-reading list into API rows.

    Invalid rows are skipped deliberately; they must not become zero-filled
    observations. Duplicate metric/timestamp rows are retained only once.
    """
    retrieved_at = retrieved_at or datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, datetime, float]] = set()
    for item in readings:
        try:
            metric = _ALIASES.get(str(item["SensorType"]), str(item["SensorType"]))
            observed_at = _parse_datetime(item["ReceivedDate"])
            value = float(item["Value"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not metric or not value == value:
            continue
        key = (metric, observed_at, value)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "observation_id": _observation_id(station_serial, metric, observed_at, value),
            "station_serial": station_serial,
            "metric": metric,
            "value": value,
            "unit": _UNITS.get(metric, "vendor_unit_unknown"),
            "observed_at": observed_at,
            "ingested_at": retrieved_at,
            "source_type": "greenlab_api",
            "qc_status": "UNCHECKED",
            "qc_reason": None,
            "provenance": {"provider": "greenlab", "endpoint": "LastestDataByDevice"},
        })
    return rows


async def fetch_station(station_serial: str, base_url: str, username: str, password: str, timeout_seconds: float = 20.0) -> list[dict[str, Any]]:
    if not username or not password:
        raise RuntimeError("greenlab_api_credentials_missing")
    url = f"{base_url.rstrip('/')}/Datums/LastestDataByDevice"
    async with httpx.AsyncClient(timeout=timeout_seconds, auth=(username, password)) as client:
        response = await client.get(url, params={"DeviceSerialNumber": station_serial})
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("greenlab_api_unrecognized_payload")
    return payload


# GreenLab /Datums/DataByDate returns naive LOCAL timestamps (decisions #12); Việt Nam has no DST.
GREENLAB_LOCAL_TZ = timezone(timedelta(hours=7))
HISTORY_HEADER = "Date,DeviceSerialNumber,SensorType,Value,Unit,Status"


async def fetch_station_history(station_serial: str, base_url: str, username: str, password: str, start: date, end: date, timeout_seconds: float = 180.0) -> str:
    """Long-format CSV for start..end (inclusive local dates) from /Datums/DataByDate."""
    if not username or not password:
        raise RuntimeError("greenlab_api_credentials_missing")
    url = f"{base_url.rstrip('/')}/Datums/DataByDate"
    async with httpx.AsyncClient(timeout=timeout_seconds, auth=(username, password)) as client:
        response = await client.get(url, params={"DeviceSerialNumber": station_serial, "StartDate": start.isoformat(), "EndDate": end.isoformat()})
        response.raise_for_status()
    text = response.content.decode("utf-8-sig")
    if not text.startswith(HISTORY_HEADER):
        raise RuntimeError("greenlab_by_date_unexpected_payload")
    return text


def normalize_history_csv(text: str, station_serial: str, retrieved_at: datetime | None = None) -> list[dict[str, Any]]:
    """DataByDate CSV -> observation rows (same id scheme as the latest feed; duplicates dropped)."""
    import csv
    import io

    retrieved_at = retrieved_at or datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, datetime, float]] = set()
    for item in csv.DictReader(io.StringIO(text)):
        try:
            if str(item.get("DeviceSerialNumber", "")).strip() != station_serial:
                continue
            metric = _ALIASES.get(str(item["SensorType"]).strip(), str(item["SensorType"]).strip())
            value = float(item["Value"])
            observed_at = datetime.strptime(str(item["Date"]).strip(), "%Y-%m-%d %H:%M").replace(tzinfo=GREENLAB_LOCAL_TZ).astimezone(timezone.utc)
        except (KeyError, TypeError, ValueError):
            continue
        if not metric or not value == value:
            continue
        key = (metric, observed_at, value)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "observation_id": _observation_id(station_serial, metric, observed_at, value),
            "station_serial": station_serial, "metric": metric, "value": value,
            "unit": _UNITS.get(metric, "vendor_unit_unknown"), "observed_at": observed_at, "ingested_at": retrieved_at,
            "source_type": "greenlab_by_date", "qc_status": "UNCHECKED", "qc_reason": None,
            "provenance": {"provider": "greenlab", "endpoint": "DataByDate", "vendor_status": item.get("Status")},
        })
    return rows
