"""Retrospective evaluation on existing quarterly historical datasets.

Results from this module are development evidence only.  They are not an
independent validation of the realtime hardware-to-lab workflow.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from .imputation_evaluation import DEFAULT_FEATURES, SUPPORTED_MODELS, run_evaluation
except ImportError:  # pragma: no cover
    from imputation_evaluation import DEFAULT_FEATURES, SUPPORTED_MODELS, run_evaluation


def historical_to_evaluation_frame(source: pd.DataFrame, target: str) -> pd.DataFrame:
    """Map the legacy quarterly schema to the evaluator's explicit schema."""
    required = {"Quarter", "Station", target}
    missing = required - set(source.columns)
    if missing:
        raise ValueError(f"historical dataset missing: {sorted(missing)}")
    frame = source.copy()
    frame["observed_at"] = pd.to_datetime(frame["Quarter"], utc=True, errors="coerce")
    frame["month"] = frame["observed_at"].dt.month
    frame["month_sin"] = np.sin(2 * np.pi * frame["month"] / 12)
    frame["month_cos"] = np.cos(2 * np.pi * frame["month"] / 12)
    frame["station_serial"] = frame["Station"].astype(str)
    frame["target_metric"] = target
    frame["actual"] = pd.to_numeric(frame[target], errors="coerce")
    return frame


def run_retrospective(
    source: pd.DataFrame, *, target: str, risk_threshold: float | None = None,
    risk_direction: str = "below", models: tuple[str, ...] = SUPPORTED_MODELS,
    splits: tuple[str, ...] = ("temporal", "station"),
) -> dict:
    frame = historical_to_evaluation_frame(source, target)
    features = [feature for feature in DEFAULT_FEATURES if feature in frame.columns]
    results: dict = {"scope": "retrospective_historical_not_realtime_ground_truth", "target": target, "features": features}
    for split in splits:
        for model in models:
            key = f"{split}_{model}"
            try:
                outcome = run_evaluation(
                    frame, target="actual", features=features, split=split, model=model,
                    risk_threshold=risk_threshold, risk_direction=risk_direction,
                )
                results[key] = outcome["metrics"]
            except ValueError as exc:
                results[key] = {"not_evaluated": str(exc)}
    return results


def flatten_metrics(region: str, target: str, result: dict) -> list[dict]:
    rows = []
    for key, metrics in result.items():
        if key in {"scope", "target", "features"}:
            continue
        split, model = key.split("_", 1)
        row = {"region": region, "target": target, "split": split, "model": model}
        if "not_evaluated" in metrics:
            row.update({"status": "not_evaluated", "reason": metrics["not_evaluated"]})
        else:
            row.update({"status": "evaluated", **metrics})
        rows.append(row)
    return rows


def retrospective_verdict(inventory_row: pd.Series, metric_rows: pd.DataFrame) -> tuple[str, str]:
    """Conservative automated label; never promotes a runtime model."""
    if inventory_row["artifact_suspect"]:
        return "reject", str(inventory_row["artifact_reason"])
    evaluated = metric_rows[metric_rows["status"] == "evaluated"]
    if evaluated.empty:
        return "median", "no_evaluated_candidate"
    piv = evaluated.pivot(index="model", columns="split", values="rmse")
    r2_piv = evaluated.pivot(index="model", columns="split", values="r2")
    candidates = [m for m in piv.index if m not in {"median", "seasonal_median"}]
    if {"temporal", "station"}.issubset(piv.columns) and "median" in piv.index:
        baseline = piv.loc["median", ["temporal", "station"]]
        winners = [model for model in candidates if (
            (piv.loc[model, ["temporal", "station"]] < baseline).all()
            and (r2_piv.loc[model, ["temporal", "station"]] > 0).all()
        )]
        if winners:
            winner = min(winners, key=lambda model: float(piv.loc[model, ["temporal", "station"]].sum()))
            return "contextual_retrospective_candidate", f"{winner}_lowest_rmse_and_positive_r2_both_splits"
    return "median", "no_candidate_beats_global_median_with_positive_r2_both_splits"


def run_region_batch(source: pd.DataFrame, *, region: str, targets: list[str], models: tuple[str, ...], splits: tuple[str, ...], known_artifacts: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    inventory = target_inventory(source, targets, known_artifacts)
    metric_rows: list[dict] = []
    verdict_rows: list[dict] = []
    for _, item in inventory.iterrows():
        target = str(item["target"])
        if item["artifact_suspect"]:
            verdict_rows.append({"region": region, "target": target, "verdict": "reject", "reason": str(item["artifact_reason"])})
            continue
        result = run_retrospective(source, target=target, models=models, splits=splits)
        rows = flatten_metrics(region, target, result)
        metric_rows.extend(rows)
        verdict, reason = retrospective_verdict(item, pd.DataFrame(rows))
        verdict_rows.append({"region": region, "target": target, "verdict": verdict, "reason": reason})
    inventory.insert(0, "region", region)
    return inventory, pd.DataFrame(metric_rows), pd.DataFrame(verdict_rows)


def time_features_for_target(region: str, target: str) -> list[str]:
    """Return only calendar features already configured for this target at runtime."""
    from core.impute import SEASONALITY_CONFIG
    seasonality = SEASONALITY_CONFIG.get(region, {}).get(target)
    if seasonality == "month":
        return ["month"]
    if seasonality == "cyclical":
        return ["month_sin", "month_cos"]
    return []


def run_time_ablation(source: pd.DataFrame, *, region: str, target: str, models: tuple[str, ...] = ("ridge", "elasticnet", "extra_trees", "xgboost")) -> pd.DataFrame:
    """Compare sensor-only against the configured calendar features on identical splits."""
    frame = historical_to_evaluation_frame(source, target)
    sensor_features = [feature for feature in DEFAULT_FEATURES if feature in frame.columns]
    calendar_features = [feature for feature in time_features_for_target(region, target) if feature in frame.columns]
    if not calendar_features:
        return pd.DataFrame()
    rows = []
    for variant, features in {"sensor_only": sensor_features, "sensor_plus_time": sensor_features + calendar_features}.items():
        for split in ("temporal", "station"):
            for model in models:
                outcome = run_evaluation(frame, target="actual", features=features, split=split, model=model)
                rows.append({"region": region, "target": target, "variant": variant, "features": "+".join(features), "split": split, "model": model, **outcome["metrics"]})
    return pd.DataFrame(rows)


def target_inventory(source: pd.DataFrame, targets: list[str], known_artifacts: set[str] | None = None) -> pd.DataFrame:
    """Describe evidence quality before any model benchmark is interpreted."""
    known_artifacts = known_artifacts or set()
    rows = []
    for target in targets:
        if target not in source.columns:
            continue
        value = pd.to_numeric(source[target], errors="coerce")
        valid = value.dropna()
        reasons = []
        if len(valid) < 30:
            reasons.append("too_few_valid_rows")
        if valid.nunique() <= 1:
            reasons.append("constant_target")
        if target in known_artifacts:
            reasons.append("known_artifact_target")
        rows.append({"target": target, "n_valid": len(valid), "missing_rate": round(float(value.isna().mean()), 4),
                     "n_stations": int(source.loc[value.notna(), "Station"].nunique()), "n_times": int(source.loc[value.notna(), "Quarter"].nunique()),
                     "p05": valid.quantile(.05) if len(valid) else None, "median": valid.median() if len(valid) else None,
                     "p95": valid.quantile(.95) if len(valid) else None, "n_unique": int(valid.nunique()),
                     "artifact_suspect": bool(reasons), "artifact_reason": ";".join(reasons)})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run retrospective imputation evidence on the existing HP/QN datasets.")
    parser.add_argument("--region", choices=["haiphong", "quangninh"], required=True)
    parser.add_argument("--target", help="Existing target column, for example DO or Salinity")
    parser.add_argument("--all-targets", action="store_true", help="Benchmark all configured targets in the selected region")
    parser.add_argument("--time-ablation", action="store_true", help="Compare sensor-only vs configured calendar features")
    parser.add_argument("--models", nargs="+", choices=SUPPORTED_MODELS, default=list(SUPPORTED_MODELS))
    parser.add_argument("--risk-threshold", type=float)
    parser.add_argument("--risk-direction", choices=["below", "above"], default="below")
    parser.add_argument("--output", type=Path, help="Optional JSON report to create")
    parser.add_argument("--output-dir", type=Path, help="Directory for inventory.csv, metrics.csv and verdicts.csv in batch mode")
    args = parser.parse_args()
    from core.impute import build_training_data

    if sum((bool(args.target), args.all_targets, args.time_ablation)) != 1:
        parser.error("provide exactly one of --target, --all-targets or --time-ablation")
    from core.impute import ARTIFACT_TARGETS, IMPUTATION_TARGETS
    source = build_training_data(args.region)
    if args.time_ablation:
        if not args.output_dir:
            parser.error("--time-ablation requires --output-dir")
        output = []
        for target in IMPUTATION_TARGETS:
            if target in source.columns:
                output.append(run_time_ablation(source, region=args.region, target=target, models=tuple(args.models)))
        ablation = pd.concat([item for item in output if not item.empty], ignore_index=True)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        ablation.to_csv(args.output_dir / f"{args.region}_time_ablation.csv", index=False)
        print(ablation.to_string(index=False))
        return
    if args.all_targets:
        inventory, metrics, verdicts = run_region_batch(source, region=args.region, targets=IMPUTATION_TARGETS, models=tuple(args.models), splits=("temporal", "station"), known_artifacts=ARTIFACT_TARGETS)
        if not args.output_dir:
            parser.error("--all-targets requires --output-dir")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        inventory.to_csv(args.output_dir / f"{args.region}_target_inventory.csv", index=False)
        metrics.to_csv(args.output_dir / f"{args.region}_metrics.csv", index=False)
        verdicts.to_csv(args.output_dir / f"{args.region}_verdicts.csv", index=False)
        print(verdicts.to_string(index=False))
        return
    result = run_retrospective(source, target=args.target,
        risk_threshold=args.risk_threshold, risk_direction=args.risk_direction, models=tuple(args.models),
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
