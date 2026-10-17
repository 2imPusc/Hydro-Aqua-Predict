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
from core.config import PH_PLAUSIBLE_BAND
from core.quality import is_in_range, ph_in_band

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


# --- Long-horizon (3/6/12 h) shadow ledger, roadmap H1.5 -------------------
# Separate files in the same store and with the same record conventions as
# above (record_id, station_serial, issued_at, valid_at, horizon_minutes,
# forecast, mode=shadow).  One-minute origins x 12 series is ~17k records/day,
# so files are indexed incrementally (only appended bytes are parsed) instead
# of being rescanned on every write.

LONG_FORECAST_LOG = STORE_DIR / "long_forecasts.jsonl"
LONG_OUTCOME_LOG = STORE_DIR / "long_outcomes.jsonl"
LONG_SKIP_LOG = STORE_DIR / "long_skips.jsonl"
LONG_SCHEMA = "sensor-future-long-v1"
LONG_TOLERANCE = pd.Timedelta(minutes=2)  # training target alignment (forecast_sensor_v2)
PH_PLAUSIBLE_SEAWATER = PH_PLAUSIBLE_BAND  # pH probe suspect from 2026-09-19 (RL-13); rule in core.quality
PI_LEVELS = ("pi80", "pi90")


class _JsonlIndex:
    def __init__(self, path: Path):
        self.path = path
        self.offset = 0
        self.records: list[dict] = []
        self.ids: set[str] = set()

    def refresh(self) -> "_JsonlIndex":
        size = self.path.stat().st_size if self.path.exists() else 0
        if size < self.offset:  # file replaced: start over
            self.offset, self.records, self.ids = 0, [], set()
        if size == self.offset:
            return self
        with self.path.open("rb") as handle:
            handle.seek(self.offset)
            chunk = handle.read()
        complete = chunk[: chunk.rfind(b"\n") + 1]
        for line in complete.decode("utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                self.records.append(record)
                self.ids.add(record.get("record_id"))
        self.offset += len(complete)
        return self

    def append(self, record: dict, record_id: str) -> bool:
        self.refresh()
        if record_id in self.ids:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = (json.dumps({"record_id": record_id, **record}, ensure_ascii=False) + "\n").encode("utf-8")
        with self.path.open("ab") as output:
            output.write(line)
        self.refresh()
        return True


_LONG_INDEXES: dict[Path, _JsonlIndex] = {}


def _long_index(path: Path) -> _JsonlIndex:
    path = Path(path)
    if path not in _LONG_INDEXES:
        _LONG_INDEXES[path] = _JsonlIndex(path)
    return _LONG_INDEXES[path].refresh()


def _reset_long_cache() -> None:
    _LONG_INDEXES.clear()
    _SCORED_BY_MODEL.clear()


def long_record_id(record: dict) -> str:
    key = "|".join(str(record.get(k)) for k in ("station_serial", "issued_at", "target", "horizon_minutes", "feature_set", "model_version"))
    return hashlib.sha256(f"{key}|{LONG_SCHEMA}".encode()).hexdigest()[:24]


def append_long_forecast(record: dict) -> bool:
    """Append one issued long-horizon forecast once; shadow only, never notified."""
    payload = {"schema_version": LONG_SCHEMA, **record, "mode": "shadow", "used_by_alerts": False, "used_by_advisory": False, "notification_eligible": False}
    return _long_index(LONG_FORECAST_LOG).append(payload, long_record_id(record))


def append_long_skip(record: dict) -> bool:
    """Log why a series was not issued: one line per series, reason and origin hour."""
    hour = pd.Timestamp(record["issued_at"]).floor("h").isoformat() if record.get("issued_at") else "none"
    key = "|".join(str(record.get(k)) for k in ("station_serial", "target", "horizon_minutes", "feature_set", "model_version", "reason"))
    record_id = hashlib.sha256(f"{key}|{hour}|skip".encode()).hexdigest()[:24]
    return _long_index(LONG_SKIP_LOG).append({"schema_version": f"{LONG_SCHEMA}-skip", **record}, record_id)


def _ph_plausible(value: float) -> bool:
    return ph_in_band(value)


def _valid_series(frame: pd.DataFrame, target: str) -> pd.Series:
    if target not in frame:
        return pd.Series(dtype=float)
    values = pd.to_numeric(frame[target], errors="coerce")
    keep = values.map(lambda value: is_in_range(target, value)).astype(bool)
    series = pd.Series(values[keep].to_numpy(), index=pd.DatetimeIndex(frame.loc[keep, "fetchedAt"]))
    return series.groupby(level=0).median().sort_index()


def resolve_long_outcomes(raw: pd.DataFrame) -> int:
    """Match due long-horizon forecasts to the nearest valid reading within 2 minutes."""
    forecasts = _long_index(LONG_FORECAST_LOG).records
    if not forecasts or raw is None or raw.empty:
        return 0
    frame = raw.copy()
    frame["fetchedAt"] = pd.to_datetime(frame["fetchedAt"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["fetchedAt"])
    if frame.empty:
        return 0
    first, latest = frame["fetchedAt"].min(), frame["fetchedAt"].max()
    resolved = _long_index(LONG_OUTCOME_LOG).ids
    series_cache: dict[str, pd.Series] = {}
    written = 0
    for forecast in list(forecasts):
        outcome_id = f"{forecast['record_id']}|actual"
        if outcome_id in resolved:
            continue
        target = forecast["target"]
        valid_at = pd.Timestamp(forecast["valid_at"])
        if valid_at - LONG_TOLERANCE > latest:
            continue
        if target not in series_cache:
            series_cache[target] = _valid_series(frame, target)
        series = series_cache[target]
        window = series[(series.index >= valid_at - LONG_TOLERANCE) & (series.index <= valid_at + LONG_TOLERANCE)]
        base = {key: forecast.get(key) for key in ("station_serial", "issued_at", "valid_at", "horizon_minutes", "target", "feature_set", "model_version",
                                                   "model_variant", "forecast", "current", "sensor_status", "ph_input_status")}
        base["forecast_record_id"] = forecast["record_id"]
        if window.empty:
            if latest < valid_at + LONG_TOLERANCE or first > valid_at - LONG_TOLERANCE:
                continue  # not decidable from this raw window yet
            outcome = {**base, "status": "no_observation", "known_at": (valid_at + LONG_TOLERANCE).isoformat()}
        else:
            distance = np.abs((window.index - valid_at).total_seconds())
            observed_at = window.index[int(np.argmin(distance))]
            actual = float(window.iloc[int(np.argmin(distance))])
            abs_error = abs(actual - float(forecast["forecast"]))
            pi = forecast.get("pi") or {}
            levels = [level for level in PI_LEVELS if isinstance(pi.get(level), dict) and pi[level].get("q") is not None]
            outcome = {**base, "status": "scored", "observed_at": observed_at.isoformat(), "known_at": max(valid_at, observed_at).isoformat(),
                       "actual": actual, "abs_error": abs_error, "covered": {level: bool(abs_error <= pi[level]["q"]) for level in levels},
                       "issued_q": {level: pi[level]["q"] for level in levels}, "night": pi.get("night")}
            if forecast.get("sensor_status", "ok") != "ok":
                outcome |= {"status": "excluded_sensor_suspect", "excluded_reason": f"input_{forecast['sensor_status']}"}
            elif target == "pH" and not _ph_plausible(actual):
                outcome |= {"status": "excluded_sensor_suspect", "excluded_reason": "actual_ph_outside_plausible_band"}
        written += int(_long_index(LONG_OUTCOME_LOG).append(outcome, outcome_id))
    return written


_SCORED_BY_MODEL: dict[Path, tuple[int, dict[str, list[tuple[int, dict]]]]] = {}


def matured_outcomes(model_version: str, issued_at: pd.Timestamp) -> list[dict]:
    """Scored outcomes of one model whose actual was known at or before ``issued_at``."""
    index = _long_index(LONG_OUTCOME_LOG)
    seen, by_model = _SCORED_BY_MODEL.get(index.path, (0, {}))
    if seen > len(index.records):  # index was rebuilt
        seen, by_model = 0, {}
    for outcome in index.records[seen:]:
        if outcome.get("status") == "scored":
            by_model.setdefault(outcome.get("model_version"), []).append((pd.Timestamp(outcome["known_at"]).value, outcome))
    _SCORED_BY_MODEL[index.path] = (len(index.records), by_model)
    cutoff = pd.Timestamp(issued_at).value
    return [outcome for known, outcome in by_model.get(model_version, []) if known <= cutoff]


def long_metrics() -> list[dict]:
    """MAE/RMSE/bias, last-observation persistence MAE and PI coverage/width per model."""
    outcomes = _long_index(LONG_OUTCOME_LOG).records
    if not outcomes:
        return []
    frame = pd.DataFrame(outcomes)
    rows = []
    for keys, group in frame.groupby(["target", "horizon_minutes", "feature_set", "model_version"]):
        scored = group[group["status"] == "scored"]
        row = {"target": keys[0], "horizon_minutes": int(keys[1]), "feature_set": keys[2], "model_version": keys[3],
               "n_scored": int(len(scored)), "n_excluded": int((group["status"] == "excluded_sensor_suspect").sum()),
               "n_no_observation": int((group["status"] == "no_observation").sum())}
        if len(scored):
            error = scored["forecast"].astype(float) - scored["actual"].astype(float)
            row |= {"mae": float(error.abs().mean()), "rmse": float(np.sqrt((error ** 2).mean())), "bias": float(error.mean()),
                    "persistence_mae": float((scored["current"].astype(float) - scored["actual"].astype(float)).abs().mean())}
            for level in PI_LEVELS:
                flags = [c[level] for c in scored["covered"] if isinstance(c, dict) and level in c]
                q = [d[level] for d in scored["issued_q"] if isinstance(d, dict) and level in d]
                finite = [2 * v for v in q if np.isfinite(v)]
                row[f"coverage_{level}"] = float(np.mean(flags)) if flags else None
                row[f"mean_width_{level}"] = float(np.mean(finite)) if finite else None
                row[f"n_infinite_{level}"] = int(len(q) - len(finite))
        rows.append(row)
    return rows
