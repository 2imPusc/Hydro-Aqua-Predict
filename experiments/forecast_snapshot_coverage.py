"""Report whether as-issued snapshots can support a causal B5 evaluation (roadmap H2.1).

Two outputs, both optional:

* ``--output table.csv`` - per target x horizon, sensor pairs that get an
  as-issued snapshot through ``join_as_issued`` (the exact B5 join) on the
  union of the scheduled-task and research-map worker captures;
* ``--summary-json summary.json`` - the weekly H2.1 summary from
  ``core.b5_coverage``: 7-day / since-start coverage per source and combined,
  causal B5 origins aligned with the sensor history, eligible days and the
  projected date the 63-day H2.2 window is reached at the current rate.

Weekly run (writes a new ``artifacts/experiments/b5-coverage-<YYYYMMDD-HHMM>/``)::

    python experiments/forecast_snapshot_coverage.py --station 06M26042804 --weekly
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import b5_coverage, paths
from core.quality import is_in_range
from experiments.forecast_external_context import join_as_issued, read_snapshot_union
from experiments.forecast_sensor_v2 import HORIZONS, TARGETS, TOLERANCE, load_sensor_data


def coverage(telemetry: Path, station: str, snapshots_path: Path, extra_snapshot_paths: tuple[Path, ...] = ()) -> pd.DataFrame:
    raw = load_sensor_data(telemetry, station)
    snapshots = read_snapshot_union(snapshots_path, tuple(path for path in extra_snapshot_paths if Path(path).exists()))
    rows: list[dict] = []
    for target in TARGETS:
        if target not in raw:
            continue
        actual = raw[["fetchedAt", target]].dropna().rename(columns={"fetchedAt": "actual_at", target: "actual"}).sort_values("actual_at")
        issued = raw[["fetchedAt", target]].dropna().rename(columns={"fetchedAt": "issued_at", target: "current"})
        for horizon in HORIZONS:
            left = issued.copy(); left["valid_at"] = left["issued_at"] + pd.Timedelta(minutes=horizon)
            frame = pd.merge_asof(left.sort_values("valid_at"), actual, left_on="valid_at", right_on="actual_at", direction="nearest", tolerance=TOLERANCE).dropna(subset=["actual"])
            frame["station"] = station
            frame["location_id"] = b5_coverage.LOCATION_ID  # build_frame joins on the B5 location id too
            joined = join_as_issued(frame, snapshots, prefix="weather")
            fields = [column for column in joined if column.startswith("weather_")]
            available = joined[fields].notna().all(axis=1) if fields else pd.Series(False, index=joined.index)
            rows.append({"target": target, "horizon_minutes": horizon, "eligible_sensor_pairs": len(frame), "as_issued_weather_pairs": int(available.sum()), "coverage_rate": float(available.mean()) if len(available) else 0.0, "telemetry_start": None if frame.empty else frame.issued_at.min(), "telemetry_end": None if frame.empty else frame.issued_at.max(), "snapshot_issued_start": None if snapshots.empty else snapshots.issued_at.min(), "snapshot_issued_end": None if snapshots.empty else snapshots.issued_at.max(), "status": "ready" if len(frame) and available.all() else "insufficient_as_issued_coverage"})
    return pd.DataFrame(rows)


def weekly_summary(telemetry: Path, station: str, snapshots_path: Path, worker_snapshots_path: Path | None,
                   now: datetime | None = None) -> dict:
    """``core.b5_coverage.coverage_report`` on the range-filtered sensor history (same QC as B5)."""
    now = now or datetime.now(timezone.utc)
    target = b5_coverage.REFERENCE_TARGET
    raw = load_sensor_data(telemetry, station)
    sensor = raw[["fetchedAt", target]].rename(columns={target: "value"})
    sensor = sensor[sensor["value"].map(lambda value: is_in_range(target, value))]
    captures = {b5_coverage.PRIMARY_SOURCE: b5_coverage.scan_captures(snapshots_path, station, b5_coverage.PRIMARY_SOURCE)}
    if worker_snapshots_path is not None:
        captures[b5_coverage.WORKER_SOURCE] = b5_coverage.scan_captures(worker_snapshots_path, station, b5_coverage.WORKER_SOURCE)
    report = b5_coverage.coverage_report(captures, sensor, now, station=station, sensor_run=Path(telemetry).parent.name)
    report["inputs"] = {"telemetry": str(telemetry), "snapshots": str(snapshots_path),
                        "worker_snapshots": None if worker_snapshots_path is None else str(worker_snapshots_path),
                        "worker_snapshots_present": bool(worker_snapshots_path and Path(worker_snapshots_path).exists())}
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("telemetry", type=Path, nargs="?", help="sensor history CSV (default: newest artifacts/experiments/sensor-history-*/<station>.csv)")
    parser.add_argument("--station", required=True)
    parser.add_argument("--snapshots", type=Path, default=paths.WEATHER_SNAPSHOTS, help="scheduled-task capture (primary)")
    parser.add_argument("--worker-snapshots", type=Path, default=paths.WEATHER_SNAPSHOTS_WORKER, help="research-map worker capture (second source)")
    parser.add_argument("--no-worker", action="store_true", help="primary source only")
    parser.add_argument("--output", type=Path, help="per target x horizon table (CSV, exact join_as_issued)")
    parser.add_argument("--summary-json", type=Path, help="weekly H2.1 summary (JSON)")
    parser.add_argument("--weekly", action="store_true", help="write summary.json + daily.csv to a new artifacts/experiments/b5-coverage-<YYYYMMDD-HHMM>/")
    args = parser.parse_args()
    if not (args.output or args.summary_json or args.weekly):
        parser.error("give --output, --summary-json or --weekly")
    telemetry = args.telemetry or b5_coverage.latest_sensor_history(paths.EXPERIMENT_OUTPUT_DIR, args.station)
    if telemetry is None:
        parser.error("no sensor-history export found; pass the telemetry CSV")
    worker = None if args.no_worker else args.worker_snapshots
    result: dict = {"telemetry": str(telemetry)}
    if args.output:
        report = coverage(telemetry, args.station, args.snapshots, () if worker is None else (worker,))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        report.to_csv(args.output, index=False)
        result.update({"output": str(args.output), "ready_rows": int((report.status == "ready").sum()), "rows": len(report)})
    if args.summary_json or args.weekly:
        summary = weekly_summary(telemetry, args.station, args.snapshots, worker)
        targets = [args.summary_json] if args.summary_json else []
        if args.weekly:
            run_dir = paths.EXPERIMENT_OUTPUT_DIR / f"b5-coverage-{datetime.now(timezone.utc):%Y%m%d-%H%M}"
            run_dir.mkdir(parents=True, exist_ok=False)  # write-once run directory
            targets.append(run_dir / "summary.json")
            pd.DataFrame(summary["days"]["daily"]).to_csv(run_dir / "daily.csv", index=False)
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        result.update({"summary": [str(target) for target in targets], "combined": {key: summary["combined"][key] for key in ("captures_total", "coverage_7d", "coverage_since_start", "eligible_origins")},
                       "eligible_days_window": summary["days"]["window_eligible_days"], "projection": summary["projection"]})
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
