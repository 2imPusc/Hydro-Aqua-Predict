"""GreenLab latest-snapshot client with an append-only local raw cache."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import requests

from core.config import (
    GREENLAB_API_BASE_URL, GREENLAB_API_CACHE_DIR,
    GREENLAB_API_PASSWORD, GREENLAB_API_USERNAME,
)

_ALIASES = {"Temp": "Temperature"}
_PARAMS = ["COD", "NH4", "pH", "Temperature", "TSS"]


def fetch_latest_snapshot(station_serial: str) -> pd.DataFrame:
    """Fetch and pivot the authenticated API latest endpoint into one row."""
    if not GREENLAB_API_USERNAME or not GREENLAB_API_PASSWORD:
        raise RuntimeError("greenlab_api_credentials_missing")
    response = requests.get(
        f"{GREENLAB_API_BASE_URL.rstrip('/')}/Datums/LastestDataByDevice",
        params={"DeviceSerialNumber": station_serial},
        auth=(GREENLAB_API_USERNAME, GREENLAB_API_PASSWORD), timeout=20,
    )
    response.raise_for_status()
    readings = response.json()
    if not isinstance(readings, list) or not readings:
        return pd.DataFrame(columns=["device", "fetchedAt", *_PARAMS])
    frame = pd.DataFrame(readings)
    required = {"SensorType", "ReceivedDate", "Value"}
    if not required.issubset(frame.columns):
        raise RuntimeError("greenlab_api_unrecognized_payload")
    frame["SensorType"] = frame["SensorType"].replace(_ALIASES)
    frame["fetchedAt"] = pd.to_datetime(frame["ReceivedDate"], utc=True)
    frame["device"] = frame.get("DeviceSerialNumber", station_serial).fillna(station_serial)
    pivot = frame.groupby(["device", "fetchedAt", "SensorType"], as_index=False)["Value"].median().pivot(
        index=["device", "fetchedAt"], columns="SensorType", values="Value"
    ).reset_index()
    for param in _PARAMS:
        if param not in pivot:
            pivot[param] = float("nan")
    return pivot[["device", "fetchedAt", *_PARAMS]]


_LONG_HEADER = "Date,DeviceSerialNumber,SensorType,Value"


def fetch_by_date_csv(station_serial: str, start: str, end: str) -> str:
    """Long-format CSV for ``start``..``end`` (YYYY-MM-DD) from /Datums/DataByDate.

    Returned as decoded text (UTF-8, BOM stripped) so the caller can store it as-is.
    """
    if not GREENLAB_API_USERNAME or not GREENLAB_API_PASSWORD:
        raise RuntimeError("greenlab_api_credentials_missing")
    response = requests.get(
        f"{GREENLAB_API_BASE_URL.rstrip('/')}/Datums/DataByDate",
        params={"DeviceSerialNumber": station_serial, "StartDate": start, "EndDate": end},
        auth=(GREENLAB_API_USERNAME, GREENLAB_API_PASSWORD), timeout=180,
    )
    response.raise_for_status()
    text = response.content.decode("utf-8-sig")
    if not text.startswith(_LONG_HEADER):
        raise RuntimeError("greenlab_by_date_unexpected_payload")
    return text


def _daily_path(station_serial: str, timestamp: pd.Timestamp) -> Path:
    return GREENLAB_API_CACHE_DIR / station_serial / f"{timestamp.tz_convert('Asia/Ho_Chi_Minh'):%Y%m%d}.jsonl"


def append_snapshot(snapshot: pd.DataFrame) -> None:
    """Append unseen API snapshots locally; raw records are never overwritten."""
    for _, row in snapshot.iterrows():
        timestamp = pd.to_datetime(row["fetchedAt"], utc=True)
        path = _daily_path(str(row["device"]), timestamp)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {key: (None if pd.isna(value) else value) for key, value in row.to_dict().items()}
        record["fetchedAt"] = timestamp.isoformat()
        existing = set()
        if path.exists():
            existing = {json.loads(line).get("fetchedAt") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
        if record["fetchedAt"] not in existing:
            with path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(record, ensure_ascii=False) + "\n")


def _normalize_export(path: Path, station_serial: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if {"device", "fetchedAt"}.issubset(frame.columns):
        frame = frame.rename(columns=_ALIASES)
    elif {"Date", "DeviceSerialNumber", "SensorType", "Value"}.issubset(frame.columns):
        frame["fetchedAt"] = pd.to_datetime(frame["Date"], utc=True)
        frame["SensorType"] = frame["SensorType"].replace(_ALIASES)
        frame = frame.groupby(["fetchedAt", "DeviceSerialNumber", "SensorType"], as_index=False)["Value"].median().pivot(
            index=["fetchedAt", "DeviceSerialNumber"], columns="SensorType", values="Value"
        ).reset_index().rename(columns={"DeviceSerialNumber": "device"})
    else:
        return pd.DataFrame()
    frame["device"] = frame["device"].astype(str)
    frame = frame[frame["device"].eq(station_serial)].copy()
    frame["fetchedAt"] = pd.to_datetime(frame["fetchedAt"], utc=True)
    for param in _PARAMS:
        if param not in frame:
            frame[param] = float("nan")
    return frame[["device", "fetchedAt", *_PARAMS]]


def load_cached_history(station_serial: str) -> pd.DataFrame:
    """Load export bootstrap plus API snapshots, returning a deduplicated series."""
    root = GREENLAB_API_CACHE_DIR.parent
    paths = list((root / "all_data").glob(f"{station_serial}_*.csv"))
    paths += list((root / "intervals").glob(f"{station_serial}_*.csv"))
    frames = [_normalize_export(path, station_serial) for path in paths]
    station_cache = GREENLAB_API_CACHE_DIR / station_serial
    for path in station_cache.glob("*.jsonl") if station_cache.exists() else []:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if records:
            frames.append(pd.DataFrame(records))
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=["device", "fetchedAt", *_PARAMS])
    combined = pd.concat(frames, ignore_index=True)
    combined["fetchedAt"] = pd.to_datetime(combined["fetchedAt"], utc=True)
    return combined.groupby(["device", "fetchedAt"], as_index=False)[_PARAMS].median().sort_values("fetchedAt").reset_index(drop=True)
