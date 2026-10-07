"""Temporal model selection for dense Hai Phong direct-sensor forecasts.

Each horizon is evaluated as a direct forecast against a chronological holdout.
Features are strictly available at forecast issuance: sensor lags and the known
calendar timestamp of the future horizon. No interpolation is used.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from core.quality import is_in_range

DIRECT_PARAMS = ("Temperature", "pH", "NH4", "TSS")
HORIZONS = {15: 5, 30: 10, 60: 20}  # 3-minute sensor aggregates
LAGS = (1, 2, 3, 5, 10)


def _calendar_features(index: pd.DatetimeIndex) -> pd.DataFrame:
    local = index.tz_convert("Asia/Ho_Chi_Minh") if index.tz is not None else index
    hour = local.hour + local.minute / 60
    day = local.dayofweek
    return pd.DataFrame({
        "hour_sin": np.sin(2 * np.pi * hour / 24),
        "hour_cos": np.cos(2 * np.pi * hour / 24),
        "dow_sin": np.sin(2 * np.pi * day / 7),
        "dow_cos": np.cos(2 * np.pi * day / 7),
    }, index=index)


def supervised_frame(series: pd.Series, steps: int, include_time: bool) -> tuple[pd.DataFrame, list[str]]:
    frame = pd.DataFrame({"value": series.astype(float)})
    for lag in LAGS:
        frame[f"lag_{lag}"] = frame["value"].shift(lag)
    frame["target"] = frame["value"].shift(-steps)
    if include_time:
        future_index = frame.index + pd.Timedelta(minutes=3 * steps)
        for name, values in _calendar_features(future_index).items():
            frame[name] = values.to_numpy()
    frame = frame.dropna()
    return frame, [column for column in frame if column.startswith("lag_") or column.endswith(("_sin", "_cos"))]


def candidates() -> dict:
    return {
        "ridge": make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        "extra_trees": ExtraTreesRegressor(n_estimators=200, min_samples_leaf=2, random_state=42, n_jobs=1),
        "xgboost": XGBRegressor(n_estimators=120, max_depth=3, learning_rate=.05, subsample=.9, colsample_bytree=.9, random_state=42, verbosity=0),
    }


def _metrics(actual, prediction) -> dict:
    return {"mae": float(mean_absolute_error(actual, prediction)), "rmse": float(np.sqrt(mean_squared_error(actual, prediction))), "r2": float(r2_score(actual, prediction))}


def evaluate_series(series: pd.Series, param: str, horizon_minutes: int) -> list[dict]:
    steps = HORIZONS[horizon_minutes]
    rows = []
    for feature_set, use_time in (("lags", False), ("lags_plus_time", True)):
        frame, features = supervised_frame(series, steps, use_time)
        split = int(len(frame) * .8)
        if split < 30 or len(frame) - split < 10:
            rows.append({"param": param, "horizon_minutes": horizon_minutes, "model": "not_evaluated", "feature_set": feature_set, "reason": "insufficient_temporal_samples", "n": len(frame)})
            continue
        train, test = frame.iloc[:split], frame.iloc[split:]
        actual = test["target"]
        if feature_set == "lags":
            rows.append({"param": param, "horizon_minutes": horizon_minutes, "model": "persistence", "feature_set": "lags", "n_train": len(train), "n_test": len(test), **_metrics(actual, test["value"])})
        for name, model in candidates().items():
            model.fit(train[features], train["target"])
            rows.append({"param": param, "horizon_minutes": horizon_minutes, "model": name, "feature_set": feature_set, "n_train": len(train), "n_test": len(test), **_metrics(actual, model.predict(test[features]))})
    return rows


def run(csv_path: Path, station: str) -> pd.DataFrame:
    raw = pd.read_csv(csv_path)
    if "device" in raw:
        raw = raw[raw["device"].astype(str) == station].copy()
    raw["fetchedAt"] = pd.to_datetime(raw["fetchedAt"], utc=True)
    rows = []
    for param in DIRECT_PARAMS:
        if param not in raw:
            continue
        clean = raw.loc[raw[param].map(lambda value: is_in_range(param, value)), ["fetchedAt", param]].set_index("fetchedAt")[param]
        series = clean.resample("3min").median().dropna()
        for minutes in HORIZONS:
            rows.extend(evaluate_series(series, param, minutes))
    return pd.DataFrame(rows)


def selection_summary(results: pd.DataFrame) -> pd.DataFrame:
    """Promote only when both RMSE and MAE beat persistence at every horizon."""
    usable = results[results["model"].ne("not_evaluated")].copy()
    persistence = usable[usable["model"].eq("persistence")][["param", "horizon_minutes", "mae", "rmse"]].rename(columns={"mae": "persistence_mae", "rmse": "persistence_rmse"})
    candidates_only = usable[~usable["model"].eq("persistence")].merge(persistence, on=["param", "horizon_minutes"], how="inner")
    candidates_only["beats_both"] = (candidates_only["mae"] < candidates_only["persistence_mae"]) & (candidates_only["rmse"] < candidates_only["persistence_rmse"])
    summary = candidates_only.groupby(["param", "model", "feature_set"], as_index=False).agg(horizons=("horizon_minutes", "nunique"), horizons_beating_both=("beats_both", "sum"), mean_rmse=("rmse", "mean"))
    summary["verdict"] = np.where((summary["horizons"] == 3) & (summary["horizons_beating_both"] == 3), "candidate", "keep_persistence")
    return summary.sort_values(["param", "verdict", "mean_rmse"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--station", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.csv, args.station)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    summary = selection_summary(result)
    summary.to_csv(args.output.with_name(args.output.stem + "_selection.csv"), index=False)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
