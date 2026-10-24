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


_EXPORT_TZ = "Asia/Ho_Chi_Minh"


def _export_time(values: pd.Series) -> pd.Series:
    """GreenLab exports write naive local time (decisions #12); aware values are kept."""
    parsed = pd.to_datetime(values)
    if parsed.dt.tz is None:
        parsed = parsed.dt.tz_localize(_EXPORT_TZ)
    return parsed.dt.tz_convert("UTC")


def _normalize_export(path: Path, station_serial: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if {"device", "fetchedAt"}.issubset(frame.columns):
        frame = frame.rename(columns=_ALIASES)
        frame["fetchedAt"] = _export_time(frame["fetchedAt"])
    elif {"Date", "DeviceSerialNumber", "SensorType", "Value"}.issubset(frame.columns):
        frame["fetchedAt"] = _export_time(frame["Date"])
        frame["SensorType"] = frame["SensorType"].replace(_ALIASES)
        frame = frame.groupby(["fetchedAt", "DeviceSerialNumber", "SensorType"], as_index=False)["Value"].median().pivot(
            index=["fetchedAt", "DeviceSerialNumber"], columns="SensorType", values="Value"
        ).reset_index().rename(columns={"DeviceSerialNumber": "device"})
    else:
        return pd.DataFrame()
    frame["device"] = frame["device"].astype(str)
    frame = frame[frame["device"].eq(station_serial)].copy()
    for param in _PARAMS:
        if param not in frame:
            frame[param] = float("nan")
    return frame[["device", "fetchedAt", *_PARAMS]]


# Per-file parse cache keyed by (mtime, size): the long-running shadow runner calls load_cached_history every
# minute and re-parsing ~200k rows took ~40 s per pass; now only files that changed (today's live cache) are read.
_FRAME_CACHE: dict[str, tuple[tuple[int, int], pd.DataFrame]] = {}


def _cached_frame(path: Path, loader) -> pd.DataFrame:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return pd.DataFrame()
    key = (stat.st_mtime_ns, stat.st_size)
    hit = _FRAME_CACHE.get(str(path))
    if hit is not None and hit[0] == key:
        return hit[1]
    frame = loader()
    _FRAME_CACHE[str(path)] = (key, frame)
    return frame


def _read_jsonl_frame(path: Path) -> pd.DataFrame:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return pd.DataFrame(records) if records else pd.DataFrame()


def load_cached_history(station_serial: str) -> pd.DataFrame:
    """Load export bootstrap plus API snapshots, returning a deduplicated series."""
    root = GREENLAB_API_CACHE_DIR.parent
    paths = list((root / "all_data").glob(f"{station_serial}_*.csv"))
    paths += list((root / "intervals").glob(f"{station_serial}_*.csv"))
    frames = [_cached_frame(path, lambda p=path: _normalize_export(p, station_serial)) for path in paths]
    station_cache = GREENLAB_API_CACHE_DIR / station_serial
    for path in station_cache.glob("*.jsonl") if station_cache.exists() else []:
        frames.append(_cached_frame(path, lambda p=path: _read_jsonl_frame(p)))
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=["device", "fetchedAt", *_PARAMS])
    combined = pd.concat(frames, ignore_index=True)
    combined["fetchedAt"] = pd.to_datetime(combined["fetchedAt"], utc=True)
    return combined.groupby(["device", "fetchedAt"], as_index=False)[_PARAMS].median().sort_values("fetchedAt").reset_index(drop=True)


# Live mode fills the minutes between the newest daily export (HAP-SensorCollector writes yesterday's file at
# 06:13) and now from /Datums/DataByDate, so the 3–12 h models have their 1-minute lags (they skipped with
# `insufficient_sensor_history` when only the latest reading was appended). Throttled in-process.
RECENT_REFRESH_MINUTES = 15
_last_recent_refresh: dict[str, pd.Timestamp] = {}


def refresh_recent_history(station_serial: str, now: pd.Timestamp | None = None) -> int:
    """Append yesterday's and today's (local) minutes to the API cache; returns rows written. Append-only."""
    now = now if now is not None else pd.Timestamp.now(tz="UTC")
    last = _last_recent_refresh.get(station_serial)
    if last is not None and (now - last).total_seconds() < RECENT_REFRESH_MINUTES * 60:
        return 0
    _last_recent_refresh[station_serial] = now
    today = now.tz_convert(_EXPORT_TZ).date()
    text = fetch_by_date_csv(station_serial, (today - pd.Timedelta(days=1)).isoformat(), today.isoformat())
    import io
    frame = pd.read_csv(io.StringIO(text))
    frame["fetchedAt"] = _export_time(frame["Date"])
    frame["SensorType"] = frame["SensorType"].replace(_ALIASES)
    frame = frame[frame["DeviceSerialNumber"].astype(str).eq(station_serial)]
    if frame.empty:
        return 0
    wide = frame.groupby(["fetchedAt", "SensorType"], as_index=False)["Value"].median().pivot(index="fetchedAt", columns="SensorType", values="Value").reset_index()
    written = 0
    for day, rows in wide.groupby(wide["fetchedAt"].dt.tz_convert(_EXPORT_TZ).dt.date):
        path = GREENLAB_API_CACHE_DIR / station_serial / f"{day:%Y%m%d}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = set()
        if path.exists():
            existing = {json.loads(line).get("fetchedAt") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
        with path.open("a", encoding="utf-8") as output:
            for _, row in rows.iterrows():
                stamp = row["fetchedAt"].isoformat()
                if stamp in existing:
                    continue
                record = {"device": station_serial, "fetchedAt": stamp, "source": "greenlab_by_date_recent"}
                record.update({param: (None if pd.isna(row.get(param)) else float(row.get(param))) for param in _PARAMS})
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
    return written
