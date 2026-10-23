# lab/realtime_greenlab/fetch.py
"""Fetch GreenLab snapshots -> tidy DataFrame.

Source = GreenLab API + local raw cache, then MongoDB Atlas fallback.
Daily aggregate uses MEDIAN (robust to sensor outliers) + range-filter + QC.
NH3 is derived from raw NH4 via chemistry.emerson_nh3.
"""
import pandas as pd

from core.config import (
    MONGODB_URI, MONGODB_DB_NAME, MONGODB_COLLECTION,
    USE_LOCAL_CSV, LOCAL_CSV_PATH, GREENLAB_API_ENABLED, GREENLAB_FETCH_MODE,
)
from core.greenlab_api import append_snapshot, fetch_latest_snapshot, load_cached_history
from core.chemistry import emerson_nh3
from core.observations import CONTRACT_VERSION, contract_issues
from core.quality import filter_valid_rows, check_series

_SENSOR_ALIAS = {"Temp": "Temperature"}
_RAW_PARAMS = ["COD", "NH4", "pH", "Temperature", "TSS"]


def _local_csv_available() -> bool:
    return LOCAL_CSV_PATH.exists()


def _fallback_to_local_csv(station_serial: str, exc: Exception) -> pd.DataFrame:
    if not _local_csv_available():
        raise exc

    df = _read_csv(station_serial)
    df.attrs["data_source"] = "local_csv_fallback"
    df.attrs["data_warning"] = (
        f"Khong the doc MongoDB ({exc}). Da chuyen sang file local: {LOCAL_CSV_PATH.name}."
    )
    return df


def _read_api_cache(station_serial: str) -> pd.DataFrame:
    snapshot = fetch_latest_snapshot(station_serial)
    append_snapshot(snapshot)
    history = load_cached_history(station_serial)
    history.attrs["data_source"] = "greenlab_api_cache"
    return history


def _read_cached_history(station_serial: str) -> pd.DataFrame:
    """Return the full locally cached series without making a network call."""
    history = load_cached_history(station_serial)
    if history.empty:
        raise RuntimeError("greenlab_api_cache_empty")
    history.attrs["data_source"] = "greenlab_api_cache"
    history.attrs["data_warning"] = (
        "Dang dung cache du lieu da khoa cho demo; khong goi API/Mongo trong lan tai nay."
    )
    return history


def _read_mongo(station_serial: str) -> pd.DataFrame:
    if not MONGODB_URI:
        raise RuntimeError("Chua cau hinh MONGODB_URI")

    from pymongo import MongoClient

    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=10_000, tls=True)
    col = client[MONGODB_DB_NAME][MONGODB_COLLECTION]
    query = {"type": "greenlab_latest_snapshot", "deviceSerialNumbers": station_serial}
    rows = []
    for doc in col.find(query, sort=[("fetchedAt", 1)]):
        for dev in doc.get("devices", []):
            if dev["DeviceSerialNumber"] != station_serial or not dev.get("success"):
                continue
            row = {"fetchedAt": doc["fetchedAt"]}
            for reading in dev.get("readings", []):
                name = _SENSOR_ALIAS.get(reading["SensorType"], reading["SensorType"])
                row[name] = reading["Value"]
            rows.append(row)
    client.close()
    return pd.DataFrame(rows)


def _read_csv(station_serial: str) -> pd.DataFrame:
    df = pd.read_csv(LOCAL_CSV_PATH)
    df = df[df["device"] == station_serial].copy()
    return df


def fetch_raw(station_serial: str) -> pd.DataFrame:
    """Raw tidy DF. Columns: fetchedAt(UTC tz-aware), COD, NH4, pH, Temperature, TSS, NH3."""
    if USE_LOCAL_CSV:
        df = _read_csv(station_serial)
        df.attrs["data_source"] = "local_csv"
    elif GREENLAB_FETCH_MODE == "cache":
        df = _read_cached_history(station_serial)
    else:
        try:
            if not GREENLAB_API_ENABLED:
                raise RuntimeError("greenlab_api_disabled")
            df = _read_api_cache(station_serial)
            df.attrs.setdefault("data_source", "greenlab_api_cache")
        except Exception as api_exc:
            try:
                df = _read_mongo(station_serial)
                df.attrs["data_source"] = "mongodb"
                df.attrs["data_warning"] = f"GreenLab API unavailable ({api_exc}); using MongoDB."
            except Exception as mongo_exc:
                cached = load_cached_history(station_serial)
                if not cached.empty:
                    df = cached
                    df.attrs["data_source"] = "greenlab_api_cache_stale"
                    df.attrs["data_warning"] = f"GreenLab API unavailable ({api_exc}); MongoDB unavailable ({mongo_exc}); using stale local API cache."
                else:
                    df = _fallback_to_local_csv(station_serial, RuntimeError(f"GreenLab API unavailable ({api_exc}); MongoDB unavailable ({mongo_exc})"))

    if df.empty:
        empty_df = pd.DataFrame(columns=["fetchedAt"] + _RAW_PARAMS + ["NH3"])
        empty_df.attrs.update(df.attrs)
        return empty_df

    source_attrs = dict(df.attrs)
    df["fetchedAt"] = pd.to_datetime(df["fetchedAt"], utc=True)
    df["NH3"] = df.apply(
        lambda row: emerson_nh3(row["NH4"], row["pH"], row["Temperature"]), axis=1
    )
    out = df.sort_values("fetchedAt").reset_index(drop=True)
    out.attrs.update(source_attrs)
    out.attrs["observation_contract_version"] = CONTRACT_VERSION
    issues = contract_issues(station_serial)
    if issues:
        contract_warning = "Data-contract requires review: " + ", ".join(issues) + "."
        existing_warning = out.attrs.get("data_warning")
        out.attrs["data_warning"] = f"{existing_warning} {contract_warning}" if existing_warning else contract_warning
    return out


def fetch_daily(station_serial: str) -> pd.DataFrame:
    """Daily-MEDIAN aggregate (UTC+7 day). Range-filtered raw readings."""
    raw = fetch_raw(station_serial)
    if raw.empty:
        return pd.DataFrame()

    raw["date"] = raw["fetchedAt"].dt.tz_convert("Asia/Bangkok").dt.date
    filtered = filter_valid_rows(raw, ["pH", "Temperature", "TSS", "NH4"])

    agg_params = ["COD", "NH4", "pH", "Temperature", "TSS", "NH3"]
    out_rows = []
    for date_val, grp in filtered.groupby("date"):
        row = {"date": date_val, "n_readings": len(grp)}
        for param in agg_params:
            row[param] = round(float(grp[param].median()), 4) if param in grp else float("nan")
        cod_day = raw[raw["date"] == date_val]["COD"]
        row["cod_status"] = check_series("COD", cod_day)
        out_rows.append(row)

    return pd.DataFrame(out_rows).sort_values("date").reset_index(drop=True)
