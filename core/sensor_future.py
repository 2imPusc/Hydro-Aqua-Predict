"""Shadow sensor-first forecasts for Hai Phong short horizons."""
from __future__ import annotations

from pathlib import Path
import joblib
import numpy as np
import pandas as pd

from core.chemistry import emerson_nh3
from core.contextual_models import predict_haiphong_contextual
from core.quality import is_in_range

MODEL_DIR = Path(__file__).resolve().parent / "models" / "sensor_future"
# The deployed model is evaluated at +15 minutes.  Intermediate one-minute
# points are a display interpolation to make the short-horizon demo readable.
HORIZONS = tuple(range(1, 16))
MODEL_HORIZON_MINUTES = 15
LAGS = (1, 2, 3, 5, 10)
SENSOR_PARAMS = ("Temperature", "pH", "NH4", "TSS")


def _time_features(timestamp: pd.Timestamp) -> dict:
    local = timestamp.tz_convert("Asia/Ho_Chi_Minh")
    hour = local.hour + local.minute / 60
    day = local.dayofweek
    return {"hour_sin": float(np.sin(2 * np.pi * hour / 24)), "hour_cos": float(np.cos(2 * np.pi * hour / 24)), "dow_sin": float(np.sin(2 * np.pi * day / 7)), "dow_cos": float(np.cos(2 * np.pi * day / 7))}


def _series(raw: pd.DataFrame, param: str) -> pd.Series:
    valid = raw.loc[raw[param].map(lambda value: is_in_range(param, value)), ["fetchedAt", param]].copy()
    valid["fetchedAt"] = pd.to_datetime(valid["fetchedAt"], utc=True)
    return valid.set_index("fetchedAt")[param].resample("3min").median().dropna()


def _native_series(raw: pd.DataFrame, param: str) -> pd.Series:
    """Valid readings at their original cadence (normally one minute).

    TSS is trained with timestamp-aware targets, so it must not be resampled
    before its lag features are made.  Duplicate readings in one timestamp are
    reduced deterministically; long gaps are rejected at prediction time.
    """
    valid = raw.loc[raw[param].map(lambda value: is_in_range(param, value)), ["fetchedAt", param]].copy()
    valid["fetchedAt"] = pd.to_datetime(valid["fetchedAt"], utc=True)
    return valid.groupby("fetchedAt")[param].median().sort_index()


def _temperature_features(series: pd.Series, future_time: pd.Timestamp) -> pd.DataFrame:
    if len(series) < max(LAGS):
        raise ValueError("insufficient_sensor_history")
    row = {f"lag_{lag}": float(series.iloc[-lag]) for lag in LAGS}
    row.update(_time_features(future_time))
    return pd.DataFrame([row])


def _temperature_bundle_path(horizon_minutes: int) -> Path:
    return MODEL_DIR / f"haiphong_temperature_xgboost_time_{horizon_minutes}m.pkl"


def _tss_bundle_path(horizon_minutes: int) -> Path:
    return MODEL_DIR / f"haiphong_tss_xgboost_lags_{horizon_minutes}m.pkl"


def _lag_features(series: pd.Series) -> pd.DataFrame:
    if len(series) < max(LAGS):
        raise ValueError("insufficient_sensor_history")
    return pd.DataFrame([{f"lag_{lag}": float(series.iloc[-lag]) for lag in LAGS}])


def _forecast_tss(native_tss: pd.Series, horizon: int) -> tuple[float, str]:
    """Use the promoted timestamp-aware TSS model, otherwise fail safely over.

    A model trained on consecutive raw readings should not silently bridge a
    telemetry outage.  Persistence is retained until the next valid history.
    """
    path = _tss_bundle_path(horizon)
    if not path.exists() or len(native_tss) < max(LAGS):
        return float(native_tss.iloc[-1]), "persistence"
    recent_span = native_tss.index[-1] - native_tss.index[-max(LAGS)]
    if recent_span > pd.Timedelta(minutes=30):
        return float(native_tss.iloc[-1]), "persistence_gap"
    bundle = joblib.load(path)
    prediction = bundle["model"].predict(_lag_features(native_tss)[bundle["features"]])[0]
    return float(prediction), "xgboost_lags"


def forecast_sensor_first(raw: pd.DataFrame, station_serial: str) -> dict:
    """Forecast installed sensors then contextual DO/salinity, all shadow-only."""
    if station_serial != "06M26042804":
        return {"status": "not_applicable", "reason": "station_not_promoted", "timeline": []}
    if raw.empty or any(param not in raw for param in SENSOR_PARAMS):
        return {"status": "unavailable", "reason": "sensor_columns_missing", "timeline": []}
    series = {param: _series(raw, param) for param in SENSOR_PARAMS}
    if any(values.empty for values in series.values()):
        return {"status": "unavailable", "reason": "no_valid_sensor_history", "timeline": []}
    base_time = min(values.index[-1] for values in series.values())
    native_tss = _native_series(raw, "TSS")
    model_horizon = MODEL_HORIZON_MINUTES
    path = _temperature_bundle_path(model_horizon)
    if not path.exists():
        return {"status": "unavailable", "reason": "temperature_bundle_missing", "timeline": []}
    bundle = joblib.load(path)
    endpoint_temperature = float(bundle["model"].predict(_temperature_features(series["Temperature"], base_time + pd.Timedelta(minutes=model_horizon))[bundle["features"]])[0])
    endpoint_tss, endpoint_tss_source = _forecast_tss(native_tss, model_horizon)
    base_temperature = float(series["Temperature"].iloc[-1])
    base_tss = float(native_tss.iloc[-1])
    timeline = []
    for horizon in HORIZONS:
        future_time = base_time + pd.Timedelta(minutes=horizon)
        ratio = horizon / model_horizon
        temperature = base_temperature + ratio * (endpoint_temperature - base_temperature)
        tss = base_tss + ratio * (endpoint_tss - base_tss)
        interpolated = horizon != model_horizon
        tss_source = f"interpolated_to_{model_horizon}m_{endpoint_tss_source}" if interpolated else endpoint_tss_source
        sensors = {"Temperature": round(temperature, 4), "pH": float(series["pH"].iloc[-1]), "NH4": float(series["NH4"].iloc[-1]), "TSS": tss}
        sensors["NH3"] = emerson_nh3(sensors["NH4"], sensors["pH"], sensors["Temperature"])
        contextual = predict_haiphong_contextual(sensors, future_time)
        predictions = contextual.get("predictions", {})
        diagnostics = {
            target: {
                "status": item.get("status", "unavailable"),
                "missing_features": item.get("missing_features", []),
                "invalid_features": item.get("invalid_features", []),
                "ood_features": item.get("ood_features", []),
            }
            for target, item in predictions.items()
        }
        timeline.append({"horizon_minutes": horizon, "timestamp": future_time.isoformat(), "sensors": sensors, "sensor_sources": {"Temperature": f"interpolated_to_{model_horizon}m_xgboost_time" if interpolated else "xgboost_time", "pH": "persistence", "NH4": "persistence", "TSS": tss_source}, "inferred": {target: item.get("value") for target, item in predictions.items() if item.get("status") == "accepted"}, "inference_diagnostics": diagnostics, "contextual_status": contextual.get("status"), "contextual_reason": contextual.get("reason"), "evaluatable": not interpolated, "interpolation_method": None if not interpolated else "linear_between_now_and_15m_model"})
    return {"status": "ready", "mode": "shadow", "used_by_alerts": False, "used_by_suitability": False, "base_timestamp": base_time.isoformat(), "timeline": timeline, "evaluated_horizons_minutes": [model_horizon]}
