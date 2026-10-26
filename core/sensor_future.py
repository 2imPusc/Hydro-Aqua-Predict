"""Shadow sensor-first forecasts for Hai Phong short horizons (+15 minutes).

Temperature: ridge on the research B4 feature set (``experiments/forecast_sensor_v2``),
features rebuilt at the forecast origin by ``core.sensor_future_long.origin_features``
(parity-tested against ``build_frame``).  A linear model extrapolates, unlike the
XGBoost bundles used before 2026-10-25, which never predicted below 29.15 °C
(trained May-July) and were far worse than persistence from August on.

Every model output passes a guard fixed at training time (stored in the bundle):
inputs or prediction outside the training range +/- a margin, or an implausible
15-minute change, fall back to persistence with an explicit source label.

TSS, pH and NH4 use persistence: no offline 15-minute TSS model beats
persistence (RL-54).  The old XGBoost pickles stay in git but are not loaded.
"""
from __future__ import annotations

import math
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from core import paths
from core.chemistry import emerson_nh3, tan_mg_l
from core.contextual_models import predict_haiphong_contextual
from core.quality import is_in_range
from core.sensor_future_long import clean_raw, origin_features

MODEL_DIR = paths.MODELS_DIR / "sensor_future"
# The deployed model is evaluated at +15 minutes.  Intermediate one-minute
# points are a display interpolation to make the short-horizon demo readable.
HORIZONS = tuple(range(1, 16))
MODEL_HORIZON_MINUTES = 15
SENSOR_PARAMS = ("Temperature", "pH", "NH4", "TSS")
PROMOTED_STATION = "06M26042804"

TEMPERATURE_BUNDLE_FILE = "haiphong_temperature_ridge_B4_quality_15m_v2.pkl"
TEMPERATURE_SOURCE = "ridge_b4"
PERSISTENCE = "persistence"
# Persistence fallbacks for the temperature model (sensor_sources labels).
PERSISTENCE_OUT_OF_RANGE = "persistence_out_of_range"
PERSISTENCE_IMPLAUSIBLE_CHANGE = "persistence_implausible_change"
PERSISTENCE_INSUFFICIENT_HISTORY = "persistence_insufficient_history"
PERSISTENCE_INVALID_OUTPUT = "persistence_invalid_output"
PERSISTENCE_REASONS = {
    "pH": "no_15m_model_promoted",
    "NH4": "no_15m_model_promoted",
    "TSS": "offline_15m_tss_models_fail_gate_rl54",
}

# --- Legacy (pre-2026-10-25) XGBoost helpers --------------------------------
# Kept only so ``experiments/train_sensor_future.py`` and the 15-minute fix
# backtest (``experiments/sensor_future_15m_fix.py``) can rebuild the old model
# inputs.  The runtime below never loads these bundles.
LAGS = (1, 2, 3, 5, 10)


def _time_features(timestamp: pd.Timestamp) -> dict:
    local = timestamp.tz_convert("Asia/Ho_Chi_Minh")
    hour = local.hour + local.minute / 60
    day = local.dayofweek
    return {"hour_sin": float(np.sin(2 * np.pi * hour / 24)), "hour_cos": float(np.cos(2 * np.pi * hour / 24)), "dow_sin": float(np.sin(2 * np.pi * day / 7)), "dow_cos": float(np.cos(2 * np.pi * day / 7))}


def _series(raw: pd.DataFrame, param: str) -> pd.Series:
    valid = raw.loc[raw[param].map(lambda value: is_in_range(param, value)), ["fetchedAt", param]].copy()
    valid["fetchedAt"] = pd.to_datetime(valid["fetchedAt"], utc=True)
    return valid.set_index("fetchedAt")[param].resample("3min").median().dropna()


def _temperature_bundle_path(horizon_minutes: int) -> Path:
    """Legacy XGBoost temperature bundle (not loaded at runtime)."""
    return MODEL_DIR / f"haiphong_temperature_xgboost_time_{horizon_minutes}m.pkl"


def _tss_bundle_path(horizon_minutes: int) -> Path:
    """Legacy XGBoost TSS bundle (not loaded at runtime)."""
    return MODEL_DIR / f"haiphong_tss_xgboost_lags_{horizon_minutes}m.pkl"


# --- Runtime -----------------------------------------------------------------

def _native_series(raw: pd.DataFrame, param: str) -> pd.Series:
    """Valid readings at their original cadence (normally one minute)."""
    valid = raw.loc[raw[param].map(lambda value: is_in_range(param, value)), ["fetchedAt", param]].copy()
    valid["fetchedAt"] = pd.to_datetime(valid["fetchedAt"], utc=True)
    return valid.groupby("fetchedAt")[param].median().sort_index()


def temperature_bundle_path() -> Path:
    return MODEL_DIR / TEMPERATURE_BUNDLE_FILE


_BUNDLE_CACHE: dict[tuple, dict] = {}


def load_temperature_bundle(path: Path | None = None) -> dict | None:
    path = Path(path or temperature_bundle_path())
    if not path.exists():
        return None
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _BUNDLE_CACHE:
        _BUNDLE_CACHE.clear()
        _BUNDLE_CACHE[key] = dict(joblib.load(path))
    return _BUNDLE_CACHE[key]


def guard_temperature(bundle: dict, features: dict, current: float, prediction: float) -> dict:
    """Accept the model value or fall back to persistence (``current``).

    Rules, all fixed in the bundle at training time:
    * any temperature-valued input (``guard_features`` + current reading) or the
      prediction outside ``[min - margin, max + margin]`` of the training target;
    * ``|prediction - current| > max_abs_change``;
    * non-finite values.
    Cross-sensor inputs (pH/NH4/TSS lags) are QC-ranged upstream; the change cap
    is the backstop for them.
    """
    lo, hi = bundle["training_range"]
    margin, cap = float(bundle["range_margin"]), float(bundle["max_abs_change"])
    low, high = lo - margin, hi + margin
    detail = {"allowed_range": [round(low, 4), round(high, 4)], "max_abs_change": cap}
    inputs = {name: features.get(name, math.nan) for name in bundle["guard_features"]}
    inputs["current"] = current
    if not all(np.isfinite(value) for value in inputs.values()):
        return {"value": float(current), "source": PERSISTENCE_INSUFFICIENT_HISTORY, "reason": "non_finite_input", **detail}
    outside = sorted(name for name, value in inputs.items() if not low <= value <= high)
    if outside:
        return {"value": float(current), "source": PERSISTENCE_OUT_OF_RANGE, "reason": "input_outside_training_range", "inputs_outside": outside, **detail}
    if not np.isfinite(prediction):
        return {"value": float(current), "source": PERSISTENCE_INVALID_OUTPUT, "reason": "non_finite_prediction", **detail}
    if not low <= prediction <= high:
        return {"value": float(current), "source": PERSISTENCE_OUT_OF_RANGE, "reason": "prediction_outside_training_range", "model_value": float(prediction), **detail}
    if abs(prediction - current) > cap:
        return {"value": float(current), "source": PERSISTENCE_IMPLAUSIBLE_CHANGE, "reason": "change_above_cap", "model_value": float(prediction), **detail}
    return {"value": float(prediction), "source": TEMPERATURE_SOURCE, "reason": None, **detail}


def _forecast_temperature(source: pd.DataFrame, bundle: dict, current: float) -> dict:
    origin = origin_features(source, "Temperature")
    if origin["status"] != "ok":
        return {"value": float(current), "source": PERSISTENCE_INSUFFICIENT_HISTORY, "reason": origin.get("reason"),
                "missing_features": origin.get("missing_features", [])}
    features = origin["features"]
    prediction = float(bundle["model"].predict(pd.DataFrame([features])[bundle["features"]])[0])
    return guard_temperature(bundle, features, float(origin["current"]), prediction)


def forecast_sensor_first(raw: pd.DataFrame, station_serial: str) -> dict:
    """Forecast installed sensors then contextual DO/salinity, all shadow-only."""
    if station_serial != PROMOTED_STATION:
        return {"status": "not_applicable", "reason": "station_not_promoted", "timeline": []}
    if raw.empty or any(param not in raw for param in SENSOR_PARAMS):
        return {"status": "unavailable", "reason": "sensor_columns_missing", "timeline": []}
    series = {param: _native_series(raw, param) for param in SENSOR_PARAMS}
    if any(values.empty for values in series.values()):
        return {"status": "unavailable", "reason": "no_valid_sensor_history", "timeline": []}
    bundle = load_temperature_bundle()
    if bundle is None:
        return {"status": "unavailable", "reason": "temperature_bundle_missing", "timeline": []}
    # Issue from the stalest sensor so every persisted value is observed by base_time.
    base_time = min(values.index[-1] for values in series.values())
    current = {param: float(values.loc[:base_time].iloc[-1]) for param, values in series.items()}
    source = clean_raw(raw)
    source = source[source["fetchedAt"] <= base_time]
    model_horizon = MODEL_HORIZON_MINUTES
    temperature = _forecast_temperature(source, bundle, current["Temperature"])
    endpoint = {"Temperature": temperature["value"], "pH": current["pH"], "NH4": current["NH4"], "TSS": current["TSS"]}
    endpoint_sources = {"Temperature": temperature["source"], "pH": PERSISTENCE, "NH4": PERSISTENCE, "TSS": PERSISTENCE}
    model_version = bundle["model_version"]
    model_versions = {"Temperature": model_version if temperature["source"] == TEMPERATURE_SOURCE else PERSISTENCE,
                      "pH": PERSISTENCE, "NH4": PERSISTENCE, "TSS": PERSISTENCE}
    reasons = {"Temperature": temperature.get("reason"), **PERSISTENCE_REASONS}
    timeline = []
    for horizon in HORIZONS:
        future_time = base_time + pd.Timedelta(minutes=horizon)
        ratio = horizon / model_horizon
        interpolated = horizon != model_horizon
        sensors = {param: current[param] + ratio * (endpoint[param] - current[param]) for param in SENSOR_PARAMS}
        sensors["Temperature"] = round(sensors["Temperature"], 4)
        # NH3 = un-ionised (toxicity advisory); TAN = total ammonium as N, the
        # basis the contextual models were trained on (provincial "NH3" column).
        sensors["NH3"] = emerson_nh3(sensors["NH4"], sensors["pH"], sensors["Temperature"])
        sensors["TAN"] = tan_mg_l(sensors["NH4"])
        sources = {param: (f"interpolated_to_{model_horizon}m_{label}" if interpolated and param in ("Temperature", "TSS") else label)
                   for param, label in endpoint_sources.items()}
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
        timeline.append({"horizon_minutes": horizon, "timestamp": future_time.isoformat(), "sensors": sensors, "sensor_sources": sources,
                         "sensor_source_reasons": reasons, "model_version": model_version,
                         "inferred": {target: item.get("value") for target, item in predictions.items() if item.get("status") == "accepted"},
                         "inference_diagnostics": diagnostics, "contextual_status": contextual.get("status"), "contextual_reason": contextual.get("reason"),
                         "evaluatable": not interpolated, "interpolation_method": None if not interpolated else "linear_between_now_and_15m_model"})
    return {"status": "ready", "mode": "shadow", "used_by_alerts": False, "used_by_suitability": False, "base_timestamp": base_time.isoformat(),
            "model_version": model_version, "model_versions": model_versions, "sensor_source_reasons": reasons,
            "temperature_guard": {key: value for key, value in temperature.items() if key != "value"},
            "timeline": timeline, "evaluated_horizons_minutes": [model_horizon]}
