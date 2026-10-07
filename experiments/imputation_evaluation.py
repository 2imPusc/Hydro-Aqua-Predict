"""Leakage-resistant evaluation harness for imputation against ground truth.

This is deliberately an experiments-only module: it must establish evidence
before a candidate imputer is promoted into ``core/impute.py``.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd


DEFAULT_FEATURES = ("COD", "NH4", "NH3", "pH", "Temperature", "TSS")
SUPPORTED_MODELS = ("median", "seasonal_median", "ridge", "elasticnet", "extra_trees", "xgboost")


def temporal_split(df: pd.DataFrame, time_col: str = "observed_at", test_fraction: float = 0.2) -> tuple[np.ndarray, np.ndarray]:
    """Return chronological train/test indices; no future record can train a model."""
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must be between 0 and 1")
    ordered = df.sort_values(time_col).index.to_numpy()
    boundary = max(1, int(len(ordered) * (1 - test_fraction)))
    if boundary >= len(ordered):
        raise ValueError("not enough rows for a temporal holdout")
    return ordered[:boundary], ordered[boundary:]


def station_holdout_splits(df: pd.DataFrame, station_col: str = "station_serial") -> Iterator[tuple[str, np.ndarray, np.ndarray]]:
    """Yield leave-one-station-out splits for spatial generalisation evidence."""
    stations = sorted(df[station_col].dropna().astype(str).unique())
    if len(stations) < 2:
        raise ValueError("station holdout requires at least two stations")
    for station in stations:
        test = df.index[df[station_col].astype(str) == station].to_numpy()
        train = df.index[df[station_col].astype(str) != station].to_numpy()
        yield station, train, test


def evaluate_predictions(
    actual: pd.Series | np.ndarray,
    predicted: pd.Series | np.ndarray,
    *,
    risk_threshold: float | None = None,
    risk_direction: Literal["below", "above"] = "below",
    lower: pd.Series | np.ndarray | None = None,
    upper: pd.Series | np.ndarray | None = None,
) -> dict:
    """Return regression, tail-error and safety-decision metrics for one target."""
    y = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    valid = np.isfinite(y) & np.isfinite(p)
    y, p = y[valid], p[valid]
    if len(y) == 0:
        raise ValueError("no finite actual/predicted pairs")
    error = p - y
    result = {
        "n": int(len(y)),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
        "bias": float(np.mean(error)),
        "p95_absolute_error": float(np.quantile(np.abs(error), 0.95)),
        "r2": float(1 - np.sum(error ** 2) / np.sum((y - np.mean(y)) ** 2)) if np.std(y) else None,
    }
    if risk_threshold is not None:
        actual_risk = y <= risk_threshold if risk_direction == "below" else y >= risk_threshold
        predicted_risk = p <= risk_threshold if risk_direction == "below" else p >= risk_threshold
        tp = int(np.sum(actual_risk & predicted_risk))
        fn = int(np.sum(actual_risk & ~predicted_risk))
        fp = int(np.sum(~actual_risk & predicted_risk))
        tn = int(np.sum(~actual_risk & ~predicted_risk))
        result["risk_decision"] = {
            "threshold": risk_threshold, "direction": risk_direction,
            "tp": tp, "fn": fn, "fp": fp, "tn": tn,
            "recall": tp / (tp + fn) if tp + fn else None,
            "precision": tp / (tp + fp) if tp + fp else None,
            "false_alert_rate": fp / (fp + tn) if fp + tn else None,
        }
    if lower is not None and upper is not None:
        lo, hi = np.asarray(lower, dtype=float)[valid], np.asarray(upper, dtype=float)[valid]
        interval_valid = np.isfinite(lo) & np.isfinite(hi)
        result["interval"] = {
            "n": int(interval_valid.sum()),
            "coverage": float(np.mean((y[interval_valid] >= lo[interval_valid]) & (y[interval_valid] <= hi[interval_valid]))) if interval_valid.any() else None,
            "mean_width": float(np.mean(hi[interval_valid] - lo[interval_valid])) if interval_valid.any() else None,
        }
    return result


def nearest_sensor_context(
    ground_truth: pd.DataFrame,
    sensor_wide: pd.DataFrame,
    *,
    tolerance: str = "15min",
) -> pd.DataFrame:
    """Pair lab samples to the nearest prior/next sensor snapshot within a fixed window."""
    required_lab = {"observed_at", "station_serial"}
    required_sensor = {"fetchedAt", "station_serial"}
    if missing := required_lab - set(ground_truth.columns):
        raise ValueError(f"ground truth missing: {sorted(missing)}")
    if missing := required_sensor - set(sensor_wide.columns):
        raise ValueError(f"sensor data missing: {sorted(missing)}")
    left = ground_truth.copy()
    right = sensor_wide.copy()
    left["observed_at"] = pd.to_datetime(left["observed_at"], utc=True)
    right["fetchedAt"] = pd.to_datetime(right["fetchedAt"], utc=True)
    return pd.merge_asof(
        left.sort_values("observed_at"), right.sort_values("fetchedAt"),
        left_on="observed_at", right_on="fetchedAt", by="station_serial",
        direction="nearest", tolerance=pd.Timedelta(tolerance), suffixes=("", "_sensor"),
    )


def _seasonal_median(train: pd.DataFrame, test: pd.DataFrame, target: str) -> np.ndarray:
    """Causal station-month median, with station/month/global fallbacks."""
    train = train.copy()
    test = test.copy()
    train["eval_month"] = train["observed_at"].dt.month
    test["eval_month"] = test["observed_at"].dt.month
    global_value = float(train[target].median())
    by_station_month = train.groupby(["station_serial", "eval_month"])[target].median()
    by_station = train.groupby("station_serial")[target].median()
    by_month = train.groupby("eval_month")[target].median()
    return np.asarray([
        by_station_month.get((row.station_serial, row.eval_month), by_station.get(row.station_serial, by_month.get(row.eval_month, global_value)))
        for row in test.itertuples()
    ], dtype=float)


def _predict(train: pd.DataFrame, test: pd.DataFrame, features: list[str], target: str, model: str) -> np.ndarray:
    if model == "median":
        return np.repeat(float(train[target].median()), len(test))
    if model == "seasonal_median":
        return _seasonal_median(train, test, target)
    if model == "ridge":
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        estimator = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    elif model == "elasticnet":
        from sklearn.linear_model import ElasticNet
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        estimator = make_pipeline(StandardScaler(), ElasticNet(alpha=0.05, l1_ratio=0.5, max_iter=10_000, random_state=42))
    elif model == "extra_trees":
        from sklearn.ensemble import ExtraTreesRegressor
        estimator = ExtraTreesRegressor(n_estimators=200, min_samples_leaf=2, random_state=42, n_jobs=-1)
    elif model == "xgboost":
        from xgboost import XGBRegressor
        estimator = XGBRegressor(n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42, verbosity=0)
    else:
        raise ValueError(f"model must be one of {SUPPORTED_MODELS}")
    estimator.fit(train[features], train[target])
    return estimator.predict(test[features])


def run_evaluation(
    df: pd.DataFrame, *, target: str = "actual", features: list[str] | None = None,
    split: Literal["temporal", "station"] = "temporal", model: str = "median",
    risk_threshold: float | None = None, risk_direction: Literal["below", "above"] = "below",
) -> dict:
    """Evaluate one candidate, returning pooled out-of-sample metrics and evidence."""
    features = features or [c for c in DEFAULT_FEATURES if c in df.columns]
    required = ["observed_at", "station_serial", target] + ([] if model in {"median", "seasonal_median"} else features)
    missing = set(required) - set(df.columns)
    if missing:
        raise ValueError(f"evaluation input missing: {sorted(missing)}")
    work = df.dropna(subset=required).copy()
    work["observed_at"] = pd.to_datetime(work["observed_at"], utc=True)
    if len(work) < 10:
        raise ValueError("need at least 10 complete ground-truth rows")

    predictions: list[pd.DataFrame] = []
    if split == "temporal":
        train_i, test_i = temporal_split(work)
        parts = [("temporal_holdout", train_i, test_i)]
    elif split == "station":
        parts = station_holdout_splits(work)
    else:
        raise ValueError("split must be 'temporal' or 'station'")
    for name, train_i, test_i in parts:
        train, test = work.loc[train_i], work.loc[test_i]
        predicted = _predict(train, test, features, target, model)
        predictions.append(pd.DataFrame({"split": name, "actual": test[target].to_numpy(), "predicted": predicted}))
    paired = pd.concat(predictions, ignore_index=True)
    return {
        "model": model, "split": split, "target": target, "features": features,
        "metrics": evaluate_predictions(paired.actual, paired.predicted, risk_threshold=risk_threshold, risk_direction=risk_direction),
        "predictions": paired,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate imputation candidates against manual-lab ground truth.")
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--target", default="actual")
    parser.add_argument("--features", nargs="*", default=None)
    parser.add_argument("--split", choices=["temporal", "station"], default="temporal")
    parser.add_argument("--model", choices=SUPPORTED_MODELS, default="median")
    parser.add_argument("--risk-threshold", type=float)
    parser.add_argument("--risk-direction", choices=["below", "above"], default="below")
    parser.add_argument("--output", type=Path, help="Optional JSON metrics output; predictions are not persisted.")
    args = parser.parse_args()
    result = run_evaluation(pd.read_csv(args.input_csv), target=args.target, features=args.features, split=args.split, model=args.model, risk_threshold=args.risk_threshold, risk_direction=args.risk_direction)
    printable = {key: value for key, value in result.items() if key != "predictions"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    if args.output:
        args.output.write_text(json.dumps(printable, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
