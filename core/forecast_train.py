import json
from pathlib import Path
from typing import Dict, List

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from xgboost import XGBRegressor

from core import paths
from core.config import STATIONS
from core.forecast import (
    DO_TARGET_COLUMN,
    FORECAST_MODEL_DIR,
    FORECAST_PARAMS,
    GRANULARITY_CONFIG,
    XGB_PARAMS,
    build_features,
    normalize_station_key,
    prepare_forecast_frame,
)
from core.quality import check_series

EXPORT_DIR = paths.GREENLAB_ALL_DATA_DIR
METRICS_PATH = FORECAST_MODEL_DIR / "forecast_metrics.json"
TRAINABLE_SERIALS = ["06M26042801", "06M26042802", "06M26042804", "06M26042803"]


def _station_csv_path(station_serial: str) -> Path:
    matches = sorted(EXPORT_DIR.glob(f"{station_serial}_*_All.csv"))
    if not matches:
        raise FileNotFoundError(f"Khong tim thay export CSV cho station {station_serial}")
    return matches[0]


def load_station_export(station_serial: str) -> pd.DataFrame:
    df = pd.read_csv(_station_csv_path(station_serial))
    if "Temp" in df.columns and "Temperature" not in df.columns:
        df = df.rename(columns={"Temp": "Temperature"})
    return df


def build_station_training_frame(station_serial: str) -> pd.DataFrame:
    region = STATIONS[station_serial]["region"]
    raw = load_station_export(station_serial)
    return prepare_forecast_frame(raw, region=region)


def _evaluate_holdout(model: XGBRegressor, X_holdout: np.ndarray, y_holdout: np.ndarray) -> Dict[str, float]:
    preds = model.predict(X_holdout)
    rmse = float(np.sqrt(mean_squared_error(y_holdout, preds)))
    return {
        "mae": round(float(mean_absolute_error(y_holdout, preds)), 4),
        "rmse": round(rmse, 4),
        "r2": round(float(r2_score(y_holdout, preds)), 4) if len(y_holdout) >= 2 else None,
    }


def _save_bundle(station_key: str, granularity: str, param: str, model: XGBRegressor, feature_columns: List[str], lags: List[int], freq: str) -> None:
    bundle = {
        "model": model,
        "station": station_key,
        "granularity": granularity,
        "param": param,
        "feature_columns": feature_columns,
        "lags": lags,
        "freq": freq,
        "target_column": DO_TARGET_COLUMN if param == "DO" else param,
    }
    joblib.dump(bundle, FORECAST_MODEL_DIR / f"{station_key}_{granularity}_{param}.pkl")


def train_station_granularity_param(station_serial: str, granularity: str, param: str) -> Dict[str, float]:
    station_key = normalize_station_key(station_serial)
    cfg = GRANULARITY_CONFIG[granularity]
    df = build_station_training_frame(station_serial)

    if param == "COD" and station_key == "haiphong":
        raise ValueError("COD khong nam trong scope target cua Haiphong.")
    if param == "COD" and station_key == "quangninh":
        cod_daily = df["COD"].resample("1D").mean() if "COD" in df.columns else pd.Series(dtype=float)
        if check_series("COD", cod_daily) != "VALID":
            raise ValueError("COD Quang Ninh khong dat QC series.")

    spec = build_features(
        df=df,
        param=param,
        granularity=granularity,
        freq=cfg["freq"],
        lags=cfg["lags"],
        horizon=cfg["horizon"],
    )
    frame = spec["frame"]
    if len(frame) < 8:
        raise ValueError(f"Khong du du lieu de train {station_key}/{granularity}/{param} (n={len(frame)}).")

    split_idx = max(1, int(len(frame) * 0.8))
    if split_idx >= len(frame):
        split_idx = len(frame) - 1
    train_df = frame.iloc[:split_idx]
    holdout_df = frame.iloc[split_idx:]

    X_train = train_df[spec["feature_columns"]].values
    y_train = train_df[spec["target_col"]].values
    X_holdout = holdout_df[spec["feature_columns"]].values
    y_holdout = holdout_df[spec["target_col"]].values

    model = XGBRegressor(**XGB_PARAMS[param], verbosity=0)
    model.fit(X_train, y_train)
    metrics = _evaluate_holdout(model, X_holdout, y_holdout)

    full_X = frame[spec["feature_columns"]].values
    full_y = frame[spec["target_col"]].values
    full_model = XGBRegressor(**XGB_PARAMS[param], verbosity=0)
    full_model.fit(full_X, full_y)
    _save_bundle(station_key, granularity, param, full_model, spec["feature_columns"], spec["lags"], spec["freq"])

    metrics.update({"n_train": int(len(train_df)), "n_holdout": int(len(holdout_df))})
    return metrics


def train(force: bool = False) -> Dict[str, Dict[str, Dict[str, Dict[str, float]]]]:
    if METRICS_PATH.exists() and not force:
        with open(METRICS_PATH, encoding="utf-8") as f:
            return json.load(f)

    FORECAST_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    metrics: Dict[str, Dict[str, Dict[str, Dict[str, float]]]] = {}
    for station_serial in TRAINABLE_SERIALS:
        station_key = normalize_station_key(station_serial)
        metrics[station_key] = {}
        for granularity in ["minute"]:
            metrics[station_key][granularity] = {}
            for param in FORECAST_PARAMS:
                try:
                    result = train_station_granularity_param(station_serial, granularity, param)
                    metrics[station_key][granularity][param] = result
                    print(f"[{station_key}/{granularity}/{param}] {result}")
                except Exception as exc:
                    metrics[station_key][granularity][param] = {
                        "error": str(exc),
                        "n_train": 0,
                        "n_holdout": 0,
                    }
                    print(f"[{station_key}/{granularity}/{param}] bo qua: {exc}")

    with open(METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    return metrics


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.train or args.force:
        results = train(force=args.force)
        print(json.dumps(results, indent=2, ensure_ascii=False))
