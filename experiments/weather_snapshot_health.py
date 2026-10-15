"""Health of the hourly as-issued weather snapshot collector.

``healthy`` needs both a recent capture and >= 90 % of the expected captures
over the last 7 days (or since the first capture, if that is more recent).
A fresh last capture alone is not enough: B5 needs an unbroken record.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402

DEFAULT_SNAPSHOTS = paths.EXPERIMENT_OUTPUT_DIR / "forecast-v2" / "weather-snapshots.jsonl"
STALE_AFTER_HOURS = 2
COVERAGE_WINDOW = timedelta(days=7)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def check_health(station: str, path: Path, now: datetime | None = None,
                 interval_minutes: int = 60, min_coverage: float = 0.9):
    if not path.exists():
        return {"status": "missing", "reason": "file_not_found"}

    captures = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            doc = json.loads(line)
            if doc.get("station") == station and doc.get("retrieved_at"):
                captures[doc["retrieved_at"]] = doc

    if not captures:
        return {"status": "missing", "reason": "no_records_for_station"}

    now = now or datetime.now(timezone.utc)
    times = sorted(_parse(value) for value in captures)
    last_time = times[-1]
    last_record = max(captures.items(), key=lambda item: _parse(item[0]))[1]
    age_hours = (now - last_time).total_seconds() / 3600

    cap_24h = sum(1 for t in times if (now - t) <= timedelta(hours=24))
    cap_7d = sum(1 for t in times if (now - t) <= COVERAGE_WINDOW)
    window_start = max(times[0], now - COVERAGE_WINDOW)
    expected = max(1.0, (now - window_start).total_seconds() / 60 / interval_minutes)
    coverage_7d = round(min(1.0, cap_7d / expected), 3)

    if age_hours > STALE_AFTER_HOURS:
        status = "stale"
    elif coverage_7d < min_coverage:
        status = "degraded"
    else:
        status = "healthy"

    gaps = []
    for previous, current in zip(times, times[1:]):
        hours = (current - previous).total_seconds() / 3600
        if hours > 2:
            gaps.append({"start": previous.isoformat(), "end": current.isoformat(), "hours": round(hours, 1)})

    return {
        "status": status,
        "last_capture_at": last_time.isoformat(),
        "age_hours": round(age_hours, 1),
        "captures_24h": cap_24h,
        "captures_7d": cap_7d,
        "coverage_7d": coverage_7d,
        "min_coverage": min_coverage,
        "gaps_gt_2h": gaps,
        "location_id": last_record.get("location_id", "unknown"),
        "missing_forecast_hours": 0,  # simplified
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--station", required=True)
    parser.add_argument("--snapshots", type=Path, default=DEFAULT_SNAPSHOTS)
    parser.add_argument("--interval-minutes", type=int, default=60)
    parser.add_argument("--min-coverage", type=float, default=0.9)
    args = parser.parse_args()

    result = check_health(args.station, args.snapshots,
                          interval_minutes=args.interval_minutes, min_coverage=args.min_coverage)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "healthy" else 1


if __name__ == "__main__":
    sys.exit(main())
