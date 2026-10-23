"""Detailed, lockbox-only error analysis for shortlisted forecast candidates.

Consumes the ``predictions.parquet`` (or legacy ``predictions.csv``) produced by ``forecast_sensor_v2``.
It never refits models and keeps the comparison paired with persistence at the
same issued timestamps.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def _metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    error = frame["prediction"] - frame["actual"]
    absolute = error.abs()
    return {
        "n": len(frame),
        "mae": float(absolute.mean()),
        "rmse": float(np.sqrt((error**2).mean())),
        "bias": float(error.mean()),
        "p95_ae": float(absolute.quantile(0.95)),
    }


def evaluate(predictions: Path, output: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    if Path(predictions).suffix == ".parquet":
        data = pd.read_parquet(predictions)
        # Label columns are stored as categoricals; plain strings keep groupby semantics.
        data = data.astype({column: object for column in data.select_dtypes("category").columns})
    else:
        data = pd.read_csv(predictions, parse_dates=["issued_at", "valid_at"], low_memory=False)
    data = data[data["split"] == "lockbox"].copy()
    if data.empty:
        raise ValueError("no_lockbox_predictions")
    keys = ["target", "horizon_minutes", "feature_set", "issued_at", "valid_at"]
    persistence = data[data.model == "persistence"][keys + ["actual", "absolute_error"]].rename(columns={"absolute_error": "persistence_ae"})
    candidates = data[data.model != "persistence"].merge(persistence, on=keys + ["actual"], how="inner", validate="many_to_one")
    if candidates.empty:
        raise ValueError("no_paired_candidate_predictions")
    candidates["error"] = candidates.prediction - candidates.actual
    candidates["mae_delta_vs_persistence"] = candidates.absolute_error - candidates.persistence_ae
    candidates["day_night"] = np.where(candidates.night.astype(bool), "night", "day")
    candidates["gap_stratum"] = np.where(candidates.gap.astype(bool), "gap", "no_gap")
    candidates["high_target"] = candidates.groupby(["target", "horizon_minutes"])["actual"].transform(lambda series: series >= series.quantile(0.9))

    dimensions = ["overall", "day_night", "gap_stratum", "high_target"]
    rows: list[dict] = []
    for dimension in dimensions:
        grouping = ["target", "horizon_minutes", "feature_set", "model"]
        if dimension != "overall":
            grouping.append(dimension)
        for key, group in candidates.groupby(grouping, dropna=False):
            names = dict(zip(grouping, key if isinstance(key, tuple) else (key,)))
            rows.append(names | {"stratum": dimension, **_metrics(group), "persistence_mae": float(group.persistence_ae.mean()), "mae_delta_vs_persistence": float(group.mae_delta_vs_persistence.mean())})
    detail = pd.DataFrame(rows)
    overall = detail[detail.stratum == "overall"].copy()
    output.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(output / "paired_lockbox_errors.csv", index=False)
    detail.to_csv(output / "detailed_lockbox_metrics.csv", index=False)
    overall.to_csv(output / "detailed_lockbox_overall.csv", index=False)
    return detail, overall


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _, overall = evaluate(args.predictions, args.output)
    print(overall.to_string(index=False))


if __name__ == "__main__":
    main()
