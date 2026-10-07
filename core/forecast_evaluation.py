"""Append-only shadow forecast ledger and delayed sensor-outcome evaluation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

from core import paths
from core.quality import is_in_range

STORE_DIR = Path(os.getenv("FORECAST_EVALUATION_DIR", paths.FORECAST_SHADOW_DIR))
FORECAST_LOG = STORE_DIR / "forecasts.jsonl"
OUTCOME_LOG = STORE_DIR / "outcomes.jsonl"
TOLERANCE = pd.Timedelta(minutes=4)
DIRECT_PARAMS = ("Temperature", "pH", "NH4", "TSS")


def _append_unique(path: Path, record: dict, record_id: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with path.open(encoding="utf-8") as existing:
            if any(json.loads(line).get("record_id") == record_id for line in existing if line.strip()):
                return False
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps({"record_id": record_id, **record}, ensure_ascii=False) + "\n")
    return True


def _weather_provenance(weather: dict | None) -> dict:
    weather = weather or {}
    return {key: weather.get(key) for key in ("status", "provider", "retrieved_at", "location", "timezone", "model", "hourly", "hourly_units") if key in weather}


def record_sensor_future(station_serial: str, future: dict, weather: dict | None = None, advisory: dict | None = None) -> int:
    """Persist each issued horizon once. Shadow records never include alerts."""
    if future.get("status") != "ready":
        return 0
    issued_at = future["base_timestamp"]
    written = 0
    for point in future.get("timeline", []):
        if not point.get("evaluatable", True):
            continue
        valid_at = point["timestamp"]
        key = f"{station_serial}|{issued_at}|{valid_at}|sensor-future-v1"
        record_id = hashlib.sha256(key.encode()).hexdigest()[:20]
        risk_point = next((item for item in (advisory or {}).get("timeline", []) if item.get("horizon_minutes") == point["horizon_minutes"]), None)
        summary = {key: (advisory or {}).get(key) for key in ("severity", "state", "confidence", "do_risk_count", "compound_stress", "notification_eligible", "notification_reason", "used_by_emergency")}
        record = {"station_serial": station_serial, "issued_at": issued_at, "valid_at": valid_at, "horizon_minutes": point["horizon_minutes"], "forecast": point["sensors"], "sensor_sources": point["sensor_sources"], "inferred": point.get("inferred", {}), "contextual_status": point.get("contextual_status"), "risk_advisory": risk_point, "advisory_summary": summary, "weather_forecast_as_issued": _weather_provenance(weather), "mode": "shadow", "used_by_alerts": False}
        written += int(_append_unique(FORECAST_LOG, record, record_id))
    return written


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def latest_advisory_state(station_serial: str) -> dict:
    """Return last issued advisory summary so persistence survives runner restarts."""
    rows = [row for row in _read_jsonl(FORECAST_LOG) if row.get("station_serial") == station_serial and row.get("advisory_summary")]
    if not rows:
        return {}
    return max(rows, key=lambda row: row.get("issued_at", "")).get("advisory_summary") or {}


def resolve_sensor_outcomes(raw: pd.DataFrame) -> int:
    """Match due forecasts to nearest valid raw sensor observation, append outcome."""
    forecasts = _read_jsonl(FORECAST_LOG)
    if not forecasts or raw.empty:
        return 0
    frame = raw.copy()
    frame["fetchedAt"] = pd.to_datetime(frame["fetchedAt"], utc=True)
    latest = frame["fetchedAt"].max()
    written = 0
    for forecast in forecasts:
        valid_at = pd.to_datetime(forecast["valid_at"], utc=True)
        if valid_at > latest:
            continue
        distance = (frame["fetchedAt"] - valid_at).abs()
        row = frame.loc[distance.idxmin()]
        if abs(row["fetchedAt"] - valid_at) > TOLERANCE:
            continue
        actual = {param: float(row[param]) for param in DIRECT_PARAMS if param in row and pd.notna(row[param]) and is_in_range(param, row[param])}
        if not actual:
            continue
        outcome_id = forecast["record_id"] + "|actual"
        outcome = {"forecast_record_id": forecast["record_id"], "station_serial": forecast["station_serial"], "issued_at": forecast["issued_at"], "valid_at": forecast["valid_at"], "observed_at": row["fetchedAt"].isoformat(), "horizon_minutes": forecast["horizon_minutes"], "forecast": forecast["forecast"], "sensor_sources": forecast["sensor_sources"], "actual": actual}
        written += int(_append_unique(OUTCOME_LOG, outcome, outcome_id))
    return written


def sensor_metrics() -> list[dict]:
    """Return MAE/RMSE/bias per sensor source and horizon from resolved records."""
    rows = []
    for outcome in _read_jsonl(OUTCOME_LOG):
        for param, actual in outcome.get("actual", {}).items():
            predicted = outcome.get("forecast", {}).get(param)
            if predicted is None:
                continue
            rows.append({"param": param, "horizon_minutes": outcome["horizon_minutes"], "model": outcome.get("sensor_sources", {}).get(param, "unknown"), "actual": actual, "predicted": predicted})
    if not rows:
        return []
    frame = pd.DataFrame(rows)
    metrics = []
    for keys, group in frame.groupby(["param", "horizon_minutes", "model"]):
        error = group.predicted - group.actual
        metrics.append({"param": keys[0], "horizon_minutes": int(keys[1]), "model": keys[2], "n": int(len(group)), "mae": float(mean_absolute_error(group.actual, group.predicted)), "rmse": float(np.sqrt(mean_squared_error(group.actual, group.predicted))), "bias": float(error.mean())})
    return metrics


def ledger_summary() -> dict:
    """Small operational summary for dashboard/CLI; logs remain append-only."""
    forecasts = _read_jsonl(FORECAST_LOG)
    outcomes = _read_jsonl(OUTCOME_LOG)
    return {
        "forecast_records": len(forecasts),
        "outcome_records": len(outcomes),
        "latest_issued_at": forecasts[-1].get("issued_at") if forecasts else None,
        "latest_observed_at": outcomes[-1].get("observed_at") if outcomes else None,
        "metrics": sensor_metrics(),
    }
