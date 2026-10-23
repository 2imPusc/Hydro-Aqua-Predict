"""Report whether as-issued snapshots can support a causal B5 evaluation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.forecast_external_context import join_as_issued, read_snapshots
from experiments.forecast_sensor_v2 import HORIZONS, TARGETS, TOLERANCE, load_sensor_data


def coverage(telemetry: Path, station: str, snapshots_path: Path) -> pd.DataFrame:
    raw = load_sensor_data(telemetry, station)
    snapshots = read_snapshots(snapshots_path)
    rows: list[dict] = []
    for target in TARGETS:
        if target not in raw:
            continue
        actual = raw[["fetchedAt", target]].dropna().rename(columns={"fetchedAt": "actual_at", target: "actual"}).sort_values("actual_at")
        issued = raw[["fetchedAt", target]].dropna().rename(columns={"fetchedAt": "issued_at", target: "current"})
        for horizon in HORIZONS:
            left = issued.copy(); left["valid_at"] = left["issued_at"] + pd.Timedelta(minutes=horizon)
            frame = pd.merge_asof(left.sort_values("valid_at"), actual, left_on="valid_at", right_on="actual_at", direction="nearest", tolerance=TOLERANCE).dropna(subset=["actual"])
            joined = join_as_issued(frame, snapshots, prefix="weather")
            fields = [column for column in joined if column.startswith("weather_")]
            available = joined[fields].notna().all(axis=1) if fields else pd.Series(False, index=joined.index)
            rows.append({"target": target, "horizon_minutes": horizon, "eligible_sensor_pairs": len(frame), "as_issued_weather_pairs": int(available.sum()), "coverage_rate": float(available.mean()) if len(available) else 0.0, "telemetry_start": None if frame.empty else frame.issued_at.min(), "telemetry_end": None if frame.empty else frame.issued_at.max(), "snapshot_issued_start": None if snapshots.empty else snapshots.issued_at.min(), "snapshot_issued_end": None if snapshots.empty else snapshots.issued_at.max(), "status": "ready" if len(frame) and available.all() else "insufficient_as_issued_coverage"})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("telemetry", type=Path); parser.add_argument("--station", required=True); parser.add_argument("--snapshots", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = coverage(args.telemetry, args.station, args.snapshots)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(args.output, index=False)
    print(json.dumps({"output": str(args.output), "ready_rows": int((report.status == "ready").sum()), "rows": len(report)}, default=str))


if __name__ == "__main__":
    main()
