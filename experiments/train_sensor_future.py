"""Train promoted direct sensor bundles for the Hai Phong shadow runtime."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import joblib
import pandas as pd
from xgboost import XGBRegressor

from core.sensor_future import (
    HORIZONS, LAGS, MODEL_DIR, _native_series, _series,
    _temperature_bundle_path, _time_features, _tss_bundle_path,
)


def train(raw_csv: Path, station: str) -> list[Path]:
    raw = pd.read_csv(raw_csv)
    raw = raw[raw["device"].astype(str).eq(station)].copy()
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    series = _series(raw, "Temperature")
    saved = []
    for horizon in HORIZONS:
        steps = horizon // 3
        frame = pd.DataFrame({"value": series, "target": series.shift(-steps)})
        for lag in LAGS:
            frame[f"lag_{lag}"] = frame.value.shift(lag)
        future = frame.index + pd.Timedelta(minutes=horizon)
        for name, values in _time_features_index(future).items():
            frame[name] = values
        frame = frame.dropna()
        features = [f"lag_{lag}" for lag in LAGS] + ["hour_sin", "hour_cos", "dow_sin", "dow_cos"]
        model = XGBRegressor(n_estimators=120, max_depth=3, learning_rate=.05, subsample=.9, colsample_bytree=.9, random_state=42, verbosity=0).fit(frame[features], frame.target)
        path = _temperature_bundle_path(horizon)
        joblib.dump({"model": model, "features": features, "horizon_minutes": horizon, "station": station, "model_version": "hp-temperature-xgb-time-v1"}, path)
        saved.append(path)
    saved.extend(train_tss(raw, station))
    return saved


def _timestamp_aware_frame(series: pd.Series, horizon: int) -> pd.DataFrame:
    """Build the exact raw-cadence target alignment used by the TSS benchmark."""
    base = pd.DataFrame({"issued_at": series.index, "value": series.to_numpy()})
    for lag in LAGS:
        base[f"lag_{lag}"] = base.value.shift(lag)
    base["valid_at"] = base.issued_at + pd.Timedelta(minutes=horizon)
    actual = pd.DataFrame({"actual_at": series.index, "target": series.to_numpy()})
    return pd.merge_asof(
        base.sort_values("valid_at"), actual.sort_values("actual_at"),
        left_on="valid_at", right_on="actual_at", direction="nearest",
        tolerance=pd.Timedelta(minutes=2),
    ).dropna()


def train_tss(raw: pd.DataFrame, station: str) -> list[Path]:
    """Fit TSS at original timestamps; pH/NH4 deliberately remain persistence."""
    series = _native_series(raw, "TSS")
    features = [f"lag_{lag}" for lag in LAGS]
    saved = []
    for horizon in HORIZONS:
        frame = _timestamp_aware_frame(series, horizon)
        if len(frame) < 100:
            raise ValueError(f"insufficient_tss_training_rows_{horizon}m")
        model = XGBRegressor(
            n_estimators=120, max_depth=3, learning_rate=.05,
            subsample=.9, colsample_bytree=.9, random_state=42, verbosity=0,
        ).fit(frame[features], frame.target)
        path = _tss_bundle_path(horizon)
        joblib.dump({
            "model": model, "features": features, "horizon_minutes": horizon,
            "station": station, "model_version": "hp-tss-xgb-native-v1",
            "training_alignment": "nearest target within +/-2 minutes at native cadence",
        }, path)
        saved.append(path)
    return saved


def _time_features_index(index):
    return {name: [(_time_features(timestamp))[name] for timestamp in index] for name in ("hour_sin", "hour_cos", "dow_sin", "dow_cos")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--station", default="06M26042804")
    args = parser.parse_args()
    print("\n".join(str(path) for path in train(args.csv, args.station)))
