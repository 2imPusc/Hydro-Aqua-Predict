"""Strict temporal weather ablation for NB1 spatial-reference experiments.

Legacy work used shuffled folds. This script preserves chronology and labels
results exploratory when quarterly sample size is too small for promotion.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBRegressor

ANCHOR = "NB1"
TARGETS = ("DO", "Salinity")
SENSOR_FEATURES = ("pH", "Temperature", "TSS", "NH3")
WEATHER_FEATURES = ("Rain_median", "Wind_median", "Wave_median")


def paired_frame(data: pd.DataFrame, target_station: str) -> pd.DataFrame:
    required = ["Station", "Quarter", *SENSOR_FEATURES, *WEATHER_FEATURES, *TARGETS]
    source = data.dropna(subset=required).copy()
    anchor = source[source["Station"] == ANCHOR].set_index("Quarter")
    target = source[source["Station"] == target_station].set_index("Quarter")
    return anchor.join(target, how="inner", lsuffix="_anchor", rsuffix="_target").sort_index()


def _metrics(actual: np.ndarray, prediction: np.ndarray) -> dict:
    return {"mae": float(mean_absolute_error(actual, prediction)), "rmse": float(np.sqrt(mean_squared_error(actual, prediction))), "r2": float(r2_score(actual, prediction))}


def evaluate_pair(frame: pd.DataFrame, target: str, include_weather: bool) -> dict:
    features = [f"{name}_anchor" for name in SENSOR_FEATURES]
    if include_weather:
        features += [f"{name}_anchor" for name in WEATHER_FEATURES]
    outcome = f"{target}_target"
    sample = frame.dropna(subset=[*features, outcome]).copy()
    if len(sample) < 12:
        return {"status": "not_evaluated", "reason": "fewer_than_12_paired_quarters", "n": len(sample)}
    cv = TimeSeriesSplit(n_splits=min(3, len(sample) - 1))
    actual, predicted = [], []
    for train_idx, test_idx in cv.split(sample):
        train, test = sample.iloc[train_idx], sample.iloc[test_idx]
        model = XGBRegressor(n_estimators=50, max_depth=2, learning_rate=.05, random_state=42, verbosity=0)
        model.fit(train[features], train[outcome])
        actual.extend(test[outcome].to_numpy())
        predicted.extend(model.predict(test[features]))
    return {"status": "evaluated", "evidence": "exploratory_only" if len(sample) < 30 else "candidate", "n": len(sample), "n_test": len(actual), **_metrics(np.asarray(actual), np.asarray(predicted))}


def run(input_path: Path) -> pd.DataFrame:
    data = pd.read_csv(input_path)
    rows = []
    for station in sorted(set(data["Station"]) - {ANCHOR}):
        frame = paired_frame(data, station)
        for target in TARGETS:
            for feature_set, include_weather in (("sensor_only", False), ("sensor_plus_weather", True)):
                rows.append({"anchor": ANCHOR, "target_station": station, "target": target, "feature_set": feature_set, **evaluate_pair(frame, target, include_weather)})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("haiphong_exogenous.csv"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
