from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from core.chemistry import emerson_nh3
from core.config import STATIONS
from core.impute import impute_params
from core.quality import filter_valid_rows
from hap_shared.classification import _classify_by_scoring

FORECAST_MODEL_DIR = Path(__file__).resolve().parent / "models" / "forecast"
FORECAST_MODEL_DIR.mkdir(parents=True, exist_ok=True)

FORECAST_PARAMS = ["Temperature", "pH", "NH4", "TSS", "DO"]
DO_TARGET_COLUMN = "DO_imputed"

XGB_PARAMS = {
    "Temperature": {"max_depth": 5, "n_estimators": 21, "learning_rate": 0.165, "random_state": 42},
    "pH": {"max_depth": 6, "n_estimators": 14, "learning_rate": 0.142, "random_state": 42},
    "NH4": {"max_depth": 3, "n_estimators": 97, "learning_rate": 0.022, "random_state": 42},
    "TSS": {"max_depth": 4, "n_estimators": 64, "learning_rate": 0.049, "random_state": 42},
    "DO": {"max_depth": 4, "n_estimators": 64, "learning_rate": 0.05, "random_state": 42},
}

GRANULARITY_CONFIG = {
    "minute": {
        "freq": None,
        "lags": [1, 2, 3, 5, 10, 30],
        "horizon": 60,
        "offset": lambda steps: pd.to_timedelta(steps, unit="min"),
        "timestamp_format": "%Y-%m-%d %H:%M:%S",
    },
    "hour": {
        "freq": "1h",
        "lags": [1, 2, 24],
        "horizon": 24,
        "offset": lambda steps: pd.to_timedelta(steps, unit="h"),
        "timestamp_format": "%Y-%m-%d %H:%M:%S",
    },
    "day": {
        "freq": "1D",
        "lags": [1, 2, 7],
        "horizon": 7,
        "offset": lambda steps: pd.to_timedelta(steps, unit="D"),
        "timestamp_format": "%Y-%m-%d",
    },
}


def normalize_station_key(station_serial: str) -> str:
    station = STATIONS.get(station_serial)
    if not station:
        raise KeyError(f"Khong tim thay station serial: {station_serial}")
    return station["region"]


def station_region(station_serial: str) -> str:
    return normalize_station_key(station_serial)


def _ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "Temp" in out.columns and "Temperature" not in out.columns:
        out = out.rename(columns={"Temp": "Temperature"})
    if "fetchedAt" in out.columns:
        out["fetchedAt"] = pd.to_datetime(out["fetchedAt"], utc=True)
        out = out.sort_values("fetchedAt").set_index("fetchedAt")
    if not isinstance(out.index, pd.DatetimeIndex):
        raise ValueError("Du lieu forecast phai co cot fetchedAt hoac DatetimeIndex.")
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    return out.sort_index()


def prepare_forecast_frame(df_raw: pd.DataFrame, region: str) -> pd.DataFrame:
    df = _ensure_datetime_index(df_raw)
    required = [col for col in ["NH4", "pH", "Temperature", "TSS"] if col in df.columns]
    if required:
        df = filter_valid_rows(df.reset_index(), required)
        df["fetchedAt"] = pd.to_datetime(df["fetchedAt"], utc=True)
        df = df.set_index("fetchedAt").sort_index()

    if "NH3" not in df.columns:
        df["NH3"] = df.apply(
            lambda row: emerson_nh3(row["NH4"], row["pH"], row["Temperature"]),
            axis=1,
        )

    do_values = []
    for timestamp, row in df.iterrows():
        measured = {
            "NH3": row.get("NH3"),
            "pH": row.get("pH"),
            "Temperature": row.get("Temperature"),
            "TSS": row.get("TSS"),
            "fetchedAt": timestamp.isoformat(),
        }
        cod_value = row.get("COD")
        if pd.notna(cod_value):
            measured["COD"] = cod_value
        imp = impute_params(dict(measured), region=region)
        do_values.append(imp["imputed"].get("DO", imp["defaulted"].get("DO", np.nan)))

    df[DO_TARGET_COLUMN] = do_values
    keep_cols = [col for col in ["COD", "NH4", "pH", "Temperature", "TSS", "NH3", DO_TARGET_COLUMN] if col in df.columns]
    return df[keep_cols].dropna(subset=["NH4", "pH", "Temperature", "TSS", DO_TARGET_COLUMN]).sort_index()


def _build_time_features(index: pd.DatetimeIndex, granularity: str) -> Dict[str, Any]:
    if granularity == "hour":
        return {"hour_of_day": index.hour}
    if granularity == "day":
        month = index.month
        return {
            "day_of_week": index.dayofweek,
            "month_sin": np.sin(2 * np.pi * month / 12),
            "month_cos": np.cos(2 * np.pi * month / 12),
        }
    return {}


def build_features(
    df: pd.DataFrame,
    param: str,
    granularity: str,
    freq: Optional[str],
    lags: List[int],
    horizon: int,
) -> Dict[str, Any]:
    if granularity not in GRANULARITY_CONFIG:
        raise ValueError(f"Granularity khong hop le: {granularity}")

    series_col = DO_TARGET_COLUMN if param == "DO" else param
    if series_col not in df.columns:
        raise KeyError(f"Khong tim thay cot {series_col} de build features.")

    base = _ensure_datetime_index(df[[series_col]])
    if freq:
        series = base.resample(freq).mean().interpolate(method="time").dropna()
    else:
        series = base.dropna()

    feature_frame = pd.DataFrame(index=series.index)
    target_col = "target"
    value_col = "value"
    feature_frame[value_col] = series[series_col]
    for lag in lags:
        feature_frame[f"lag_{lag}"] = feature_frame[value_col].shift(lag)
    for name, values in _build_time_features(feature_frame.index, granularity).items():
        feature_frame[name] = values
    feature_frame[target_col] = feature_frame[value_col]
    supervised = feature_frame.dropna().copy()
    feature_columns = [col for col in supervised.columns if col not in {target_col, value_col}]
    future_index = make_future_index(series.index[-1], granularity, horizon) if not series.empty else pd.DatetimeIndex([])
    return {
        "series": series.rename(columns={series_col: value_col}),
        "frame": supervised,
        "feature_columns": feature_columns,
        "future_index": future_index,
        "freq": freq or "native",
        "lags": list(lags),
        "horizon": horizon,
        "granularity": granularity,
        "param": param,
        "target_col": target_col,
        "value_col": value_col,
    }


def make_future_index(last_timestamp: pd.Timestamp, granularity: str, horizon: int) -> pd.DatetimeIndex:
    cfg = GRANULARITY_CONFIG[granularity]
    offsets = [cfg["offset"](step) for step in range(1, horizon + 1)]
    return pd.DatetimeIndex([last_timestamp + offset for offset in offsets])


def _future_feature_row(history_values: List[float], timestamp: pd.Timestamp, granularity: str, lags: List[int]) -> Dict[str, float]:
    feats = {f"lag_{lag}": float(history_values[-lag]) for lag in lags}
    if granularity == "hour":
        feats["hour_of_day"] = timestamp.hour
    elif granularity == "day":
        feats["day_of_week"] = timestamp.dayofweek
        feats["month_sin"] = float(np.sin(2 * np.pi * timestamp.month / 12))
        feats["month_cos"] = float(np.cos(2 * np.pi * timestamp.month / 12))
    return feats


def _model_path(station_key: str, granularity: str, param: str) -> Path:
    return FORECAST_MODEL_DIR / f"{station_key}_{granularity}_{param}.pkl"


def load_forecast_bundle(station_key: str, granularity: str, param: str) -> Dict[str, Any]:
    path = _model_path(station_key, granularity, param)
    if not path.exists():
        raise FileNotFoundError(
            f"Thieu model forecast: {path.name}. Hay chay `python core/forecast_train.py --train --force`."
        )
    return joblib.load(path)


def _recursive_forecast(model: Any, spec: Dict[str, Any], horizon: int) -> List[float]:
    history_values = spec["series"]["value"].tolist()
    if not history_values:
        raise ValueError("Khong co du lieu lich su de du bao.")
    future_index = make_future_index(spec["series"].index[-1], spec["granularity"], horizon)
    preds = []
    for timestamp in future_index:
        row = _future_feature_row(history_values, timestamp, spec["granularity"], spec["lags"])
        feature_order = spec["feature_columns"]
        feats = np.array([[row[col] for col in feature_order]], dtype=float)
        pred = float(model.predict(feats)[0])
        preds.append(pred)
        history_values.append(pred)
    return preds


def train_and_forecast_xgboost(df_hourly: pd.DataFrame, param: str, horizon: int = 24) -> List[float]:
    spec = build_features(
        _ensure_datetime_index(df_hourly[[param]]),
        param=param,
        granularity="hour",
        freq="1h",
        lags=GRANULARITY_CONFIG["hour"]["lags"],
        horizon=horizon,
    )
    frame = spec["frame"]
    if len(frame) < 5:
        last_val = float(spec["series"]["value"].iloc[-1]) if not spec["series"].empty else 0.0
        return [last_val] * horizon

    X_train = frame[spec["feature_columns"]].values
    y_train = frame[spec["target_col"]].values
    model = XGBRegressor(**XGB_PARAMS[param])
    model.fit(X_train, y_train)
    return _recursive_forecast(model, spec, horizon)


def forecast(
    df_raw: pd.DataFrame,
    station_serial: str,
    granularity: str,
    current_time_str: str,
    species: str,
    horizon: Optional[int] = None,
) -> Dict[str, Any]:
    if granularity not in GRANULARITY_CONFIG:
        raise ValueError(f"Granularity khong hop le: {granularity}")

    try:
        base_time = pd.to_datetime(current_time_str, utc=True)
    except Exception:
        base_time = pd.Timestamp.now(tz="UTC")

    station_key = normalize_station_key(station_serial)
    region = station_region(station_serial)
    cfg = GRANULARITY_CONFIG[granularity]
    horizon = horizon or cfg["horizon"]

    prepared = prepare_forecast_frame(df_raw, region=region)
    preds_dict: Dict[str, List[float]] = {}
    for param in FORECAST_PARAMS:
        bundle = load_forecast_bundle(station_key, granularity, param)
        spec = build_features(
            prepared,
            param=param,
            granularity=granularity,
            freq=bundle.get("freq", cfg["freq"]),
            lags=bundle.get("lags", cfg["lags"]),
            horizon=horizon,
        )
        preds_dict[param] = _recursive_forecast(bundle["model"], spec, horizon)

    forecast_timeline = []
    min_do = float("inf")
    min_do_time = None
    max_temp = float("-inf")
    max_temp_time = None
    future_index = make_future_index(base_time, granularity, horizon)

    for offset, future_time in enumerate(future_index, start=1):
        f_params = {
            "Temperature": preds_dict["Temperature"][offset - 1],
            "pH": preds_dict["pH"][offset - 1],
            "NH4": preds_dict["NH4"][offset - 1],
            "TSS": preds_dict["TSS"][offset - 1],
            "DO": preds_dict["DO"][offset - 1],
        }

        res_df = _classify_by_scoring(pd.DataFrame([f_params]), list(f_params.keys()), species)
        wqi_val = float(res_df["suitability_score"].iloc[0])
        wqi_label = str(res_df["suitability_name"].iloc[0])

        point = {
            "offset": offset,
            "timestamp": future_time.strftime(cfg["timestamp_format"]),
            "Temperature": round(f_params["Temperature"], 2),
            "pH": round(f_params["pH"], 2),
            "NH4": round(f_params["NH4"], 2),
            "TSS": round(f_params["TSS"], 2),
            "DO": round(f_params["DO"], 2),
            "WQI": round(wqi_val, 2),
            "label": wqi_label,
        }
        if granularity == "hour":
            point["hour_offset"] = offset
        forecast_timeline.append(point)

        if f_params["DO"] < min_do:
            min_do = float(f_params["DO"])
            min_do_time = future_time.strftime(cfg["timestamp_format"])
        if f_params["Temperature"] > max_temp:
            max_temp = float(f_params["Temperature"])
            max_temp_time = future_time.strftime(cfg["timestamp_format"])

    warnings = []
    if min_do < 4.0 and min_do_time:
        warnings.append(f"Nguy co tut Oxy hoa tan (DO = {min_do:.1f} mg/L) tai {min_do_time}.")
    if max_temp > 33.0 and max_temp_time:
        warnings.append(f"Canh bao soc nhiet (Nhiet do = {max_temp:.1f}°C) tai {max_temp_time}.")

    return {
        "granularity": granularity,
        "horizon": horizon,
        "timeline": forecast_timeline,
        "early_warnings": warnings,
        "extremes": {"min_do": min_do, "max_temp": max_temp},
    }


def forecast_24h(
    df_raw: pd.DataFrame,
    current_time_str: str,
    species: str = "cobia",
    current_do: float = 6.0,
    horizon: int = 24,
) -> Dict[str, Any]:
    del current_do
    return forecast(
        df_raw=df_raw,
        station_serial="06M26042804",
        granularity="hour",
        current_time_str=current_time_str,
        species=species,
        horizon=horizon,
    )
