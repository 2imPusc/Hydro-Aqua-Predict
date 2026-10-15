"""Backfill GreenLab sensor history via /Datums/DataByDate (roadmap D0.1, D0.3).

Writes one long-format CSV per chunk into data/greenlab/exports/intervals/.
Existing files are never overwritten. Chunks overlap by one day so no gap can
fall between them; load_cached_history() de-duplicates by timestamp.

--since-last resumes from the newest interval file, so it assumes the files
are contiguous: never write a file for a range ahead of the newest one (use
--start/--end only to fill behind it). scripts/sensor_coverage.py catches a
gap if one slips through.

    python scripts/backfill_sensor.py --station 06M26042804 --region HAIPHONG --start 2026-07-26
    python scripts/backfill_sensor.py --station 06M26042804 --region HAIPHONG --since-last
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.greenlab_api import fetch_by_date_csv  # noqa: E402

MAX_CHUNK_DAYS = 7
LOCAL_TZ = "Asia/Ho_Chi_Minh"
_END_DATE = re.compile(r"_to_(\d{8})\.csv$")


def plan_chunks(start: date, end: date, max_days: int = MAX_CHUNK_DAYS) -> list[tuple[date, date]]:
    """Inclusive (start, end) chunks of at most ``max_days`` days, overlapping by one day."""
    if max_days < 2:
        raise ValueError("max_days must be >= 2 so chunks can overlap and still advance")
    if end < start:
        return []
    chunks, cursor = [], start
    while True:
        chunk_end = min(cursor + timedelta(days=max_days - 1), end)
        chunks.append((cursor, chunk_end))
        if chunk_end >= end:
            return chunks
        cursor = chunk_end


def chunk_path(intervals_dir: Path, station: str, region: str, start: date, end: date) -> Path:
    return intervals_dir / f"{station}_{region}_{start:%Y%m%d}_to_{end:%Y%m%d}.csv"


def last_covered_date(intervals_dir: Path, station: str) -> date | None:
    ends = [
        datetime.strptime(match.group(1), "%Y%m%d").date()
        for path in intervals_dir.glob(f"{station}_*.csv")
        if (match := _END_DATE.search(path.name))
    ]
    return max(ends, default=None)


def write_new(path: Path, text: str) -> bool:
    """Create ``path`` with ``text``; return False (and leave it alone) if it exists."""
    try:
        with path.open("x", encoding="utf-8", newline="") as handle:
            handle.write(text)
    except FileExistsError:
        return False
    return True


def run_backfill(station: str, region: str, start: date, end: date, intervals_dir: Path,
                 fetch: Callable[[str, str, str], str] = fetch_by_date_csv,
                 log: Callable[[str], None] = print) -> list[dict]:
    intervals_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for chunk_start, chunk_end in plan_chunks(start, end):
        target = chunk_path(intervals_dir, station, region, chunk_start, chunk_end)
        rows = 0
        if target.exists():
            status = "exists"
        else:
            text = fetch(station, chunk_start.isoformat(), chunk_end.isoformat())
            rows = max(0, len(text.strip().splitlines()) - 1)
            if rows == 0:
                status = "empty"
            else:
                status = "written" if write_new(target, text) else "exists"
        results.append({"chunk": target.name, "status": status, "rows": rows})
        log(f"{status:8s} {target.name} rows={rows}")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--station", required=True)
    parser.add_argument("--region", required=True, help="file-name region, e.g. HAIPHONG (see ingest/stations.yaml)")
    parser.add_argument("--start", help="YYYY-MM-DD (local date)")
    parser.add_argument("--end", help="YYYY-MM-DD (local date); default: yesterday")
    parser.add_argument("--since-last", action="store_true", help="start from the newest existing interval file")
    args = parser.parse_args(argv)

    end = date.fromisoformat(args.end) if args.end else pd.Timestamp.now(tz=LOCAL_TZ).date() - timedelta(days=1)
    if args.since_last:
        start = last_covered_date(paths.GREENLAB_INTERVALS_DIR, args.station)
        if start is None:
            parser.error("no interval files for this station yet; pass --start")
        if start >= end:
            print(f"up to date: newest file ends {start}")
            return 0
    elif args.start:
        start = date.fromisoformat(args.start)
    else:
        parser.error("pass --start or --since-last")

    results = run_backfill(args.station, args.region, start, end, paths.GREENLAB_INTERVALS_DIR)
    written = sum(r["status"] == "written" for r in results)
    print(f"{written} written, {len(results) - written} skipped; range {start} .. {end}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
