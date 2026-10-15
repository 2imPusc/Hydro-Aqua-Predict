"""Per-day sensor coverage and COD health for one station (roadmap D0.1, D0.5).

Gate: each local day has >= 90 % of 1,440 one-minute readings.

    python scripts/sensor_coverage.py --station 06M26042804             # full report, written as artifact
    python scripts/sensor_coverage.py --station 06M26042804 --last-days 7 --no-write   # collector health
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.greenlab_api import load_cached_history  # noqa: E402
from core.quality import check_series, is_in_range  # noqa: E402

MINUTES_PER_DAY = 1440
COD_RAIL = 558.8
LOCAL_TZ = "Asia/Ho_Chi_Minh"
COLUMNS = ["date", "minutes", "coverage", "meets_gate", "cod_status", "cod_median", "cod_in_range_share", "cod_rail_share"]


def daily_coverage(history: pd.DataFrame, min_fraction: float = 0.9) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame(columns=COLUMNS)
    frame = history.copy()
    frame["minute"] = pd.to_datetime(frame["fetchedAt"], utc=True).dt.tz_convert(LOCAL_TZ).dt.floor("min")
    frame["date"] = frame["minute"].dt.date
    rows = []
    for day, group in frame.groupby("date"):
        minutes = int(group["minute"].nunique())
        cod = pd.to_numeric(group["COD"], errors="coerce").dropna()
        rows.append({
            "date": day,
            "minutes": minutes,
            "coverage": round(minutes / MINUTES_PER_DAY, 3),
            "meets_gate": minutes / MINUTES_PER_DAY >= min_fraction,
            "cod_status": check_series("COD", cod),
            "cod_median": round(float(cod.median()), 2) if len(cod) else float("nan"),
            "cod_in_range_share": round(float(cod.map(lambda v: is_in_range("COD", v)).mean()), 3) if len(cod) else float("nan"),
            "cod_rail_share": round(float((cod.round(1) == COD_RAIL).mean()), 3) if len(cod) else float("nan"),
        })
    out = pd.DataFrame(rows).set_index("date")
    all_days = pd.date_range(min(out.index), max(out.index), freq="D").date
    out = out.reindex(all_days)
    out["minutes"] = out["minutes"].fillna(0).astype(int)
    out["coverage"] = out["coverage"].fillna(0.0)
    out["meets_gate"] = out["meets_gate"].eq(True)
    out["cod_status"] = out["cod_status"].fillna("NO_DATA")
    return out.rename_axis("date").reset_index()[COLUMNS]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--station", required=True)
    parser.add_argument("--last-days", type=int, help="only judge the last N complete local days")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    report = daily_coverage(load_cached_history(args.station))
    if report.empty:
        print("no sensor history")
        return 1
    today = pd.Timestamp.now(tz=LOCAL_TZ).date()
    report = report[report["date"] < today]  # today is never complete
    judged = report.tail(args.last_days) if args.last_days else report

    if not args.no_write:
        run_dir = paths.EXPERIMENT_OUTPUT_DIR / f"sensor-coverage-{today:%Y%m%d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        target = run_dir / f"{args.station}_daily.csv"
        if target.exists():
            print(f"exists, not overwritten: {target}")
        else:
            report.to_csv(target, index=False)
            print(f"wrote {target}")

    failing = judged[~judged["meets_gate"]]
    print(f"days judged: {len(judged)}  meeting gate: {len(judged) - len(failing)}  "
          f"range: {judged['date'].min()} .. {judged['date'].max()}")
    print("COD status counts:", judged["cod_status"].value_counts().to_dict())
    if not failing.empty:
        print("below gate:")
        print(failing[["date", "minutes", "coverage"]].to_string(index=False))
    return 0 if failing.empty else 1


if __name__ == "__main__":
    sys.exit(main())
