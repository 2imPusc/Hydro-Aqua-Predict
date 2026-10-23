"""Prepare a scientifically traceable paired lab--sensor evaluation dataset."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

try:  # package import for tests, local import when executed as a script
    from .imputation_evaluation import nearest_sensor_context
except ImportError:  # pragma: no cover
    from imputation_evaluation import nearest_sensor_context


LAB_REQUIRED = {"sample_id", "observed_at", "station_serial", "metric", "value", "unit", "method"}


def load_sensor_export(path: Path) -> pd.DataFrame:
    """Read the existing GreenLab CSV export without changing raw source data."""
    sensor = pd.read_csv(path)
    if "station_serial" not in sensor.columns and "device" in sensor.columns:
        sensor = sensor.rename(columns={"device": "station_serial"})
    required = {"fetchedAt", "station_serial"}
    missing = required - set(sensor.columns)
    if missing:
        raise ValueError(f"sensor export missing: {sorted(missing)}")
    return sensor


def prepare_paired_dataset(
    lab: pd.DataFrame,
    sensor: pd.DataFrame,
    *,
    target_metric: str,
    target_unit: str,
    tolerance: str = "15min",
) -> tuple[pd.DataFrame, dict]:
    """Match one lab target to nearby sensor context, refusing ambiguous units."""
    missing = LAB_REQUIRED - set(lab.columns)
    if missing:
        raise ValueError(f"lab observations missing: {sorted(missing)}")
    selected = lab.loc[lab["metric"].astype(str) == target_metric].copy()
    if selected.empty:
        raise ValueError(f"no lab observations for target metric: {target_metric}")
    bad_unit = selected["unit"].astype(str) != target_unit
    if bad_unit.any():
        found = sorted(selected.loc[bad_unit, "unit"].astype(str).unique())
        raise ValueError(f"unit mismatch for {target_metric}; expected {target_unit}, found {found}")
    selected["value"] = pd.to_numeric(selected["value"], errors="coerce")
    selected = selected.dropna(subset=["value"]).copy()
    selected = selected.rename(columns={"metric": "target_metric", "value": "actual"})
    matched = nearest_sensor_context(selected, sensor, tolerance=tolerance)
    paired = matched.loc[matched["fetchedAt"].notna()].copy()
    report = {
        "target_metric": target_metric,
        "target_unit": target_unit,
        "tolerance": tolerance,
        "lab_rows_selected": int(len(selected)),
        "paired_rows": int(len(paired)),
        "unmatched_rows": int(len(selected) - len(paired)),
        "match_rate": round(len(paired) / len(selected), 4) if len(selected) else 0.0,
    }
    return paired, report


def main() -> None:
    parser = argparse.ArgumentParser(description="Pair manual-lab ground truth with GreenLab sensor snapshots.")
    parser.add_argument("lab_csv", type=Path, help="Completed ground_truth_observations.csv")
    parser.add_argument("sensor_csv", type=Path, help="Raw GreenLab export; never modified")
    parser.add_argument("--metric", required=True, help="Lab target, for example DO or Salinity")
    parser.add_argument("--unit", required=True, help="Confirmed unit for the target, for example mg/L")
    parser.add_argument("--tolerance", default="15min")
    parser.add_argument("--output", type=Path, required=True, help="New paired CSV to create")
    parser.add_argument("--report", type=Path, help="Optional JSON pairing report")
    args = parser.parse_args()
    paired, report = prepare_paired_dataset(
        pd.read_csv(args.lab_csv), load_sensor_export(args.sensor_csv),
        target_metric=args.metric, target_unit=args.unit, tolerance=args.tolerance,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    paired.to_csv(args.output, index=False)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
