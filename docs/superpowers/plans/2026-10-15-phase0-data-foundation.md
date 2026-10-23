# Phase 0 — Data Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the sensor-history gap (2026-07-26 → now), keep both the sensor and weather records continuous from now on, and make the collectors' health checks honest, so that roadmap gates H1.1 and H2.2 become reachable.

**Architecture:** Add a Python client for GreenLab `/Datums/DataByDate` next to the existing latest-snapshot client (`core/greenlab_api.py`). A backfill script writes one long-format CSV per ≤7-day chunk into `data/greenlab/exports/intervals/`; this is the format `load_cached_history()` already reads. Files are opened with mode `"x"`, so nothing is ever overwritten. The same script, run daily with `--since-last`, becomes the sensor collector, and it catches up on its own after missed runs. A per-day coverage report gates the backfill, and a hashed history export gives the benchmarks one reproducible input.

**Tech Stack:** Python 3.11, pandas, requests, pytest (root `.venv`), PowerShell Task Scheduler.

**Parent plan:** [2026-10-15-master-execution-plan.md](2026-10-15-master-execution-plan.md)

---

## Context the engineer needs

- Read `AGENTS.md` hard rules first. **Never overwrite or delete anything in `data/` or `artifacts/`.** Every path must come from `core/paths.py`.
- Run everything from the repo root with `.venv\Scripts\python`. Full test suite: `.venv\Scripts\python -m pytest -q` (136 pass at start).
- Scripts in `experiments/` and `scripts/` bootstrap imports with `sys.path.insert(0, str(Path(__file__).resolve().parents[1]))` before `from core ...`.
- GreenLab credentials are `TK_DHTB` / `MK_DHTB` in the root `.env`. `core/config.py` exposes them as `GREENLAB_API_USERNAME` / `GREENLAB_API_PASSWORD` (HTTP basic auth). Base URL: `GREENLAB_API_BASE_URL`.
- Long format returned by `DataByDate` (CSV): `Date,DeviceSerialNumber,SensorType,Value,Unit,Status`, about one row per sensor per minute. `core/greenlab_api._normalize_export()` already pivots this format, and `load_cached_history()` already globs `intervals/*.csv`.
- The current healthcheck (`experiments/weather_snapshot_health.py`) reports `healthy` at about 32% hourly coverage (54 captures in 7 days, against 168 expected), because it only checks the age of the last capture.
- Commit messages: subject ≤ 72 chars (AGENTS.md rule 5), followed by the session's attribution trailer if one is required. Do not push.
- **Task 1 waits for the owner** to confirm the 1 → 2 ‖ 3 → 4 order. Tasks 2–11 do not depend on the order and can start immediately.
- `core/config.PLAUSIBLE_RANGE["COD"] = (0, 100)`. The 189.8 reading seen on 2026-09-20 is therefore *out of range*, so "COD recovered" is not yet established. The report in Task 6 must show this.

## File map

| File | Action | Responsibility |
| --- | --- | --- |
| `docs/decisions.md` | Modify (append) | #10 priority order, #11 canonical sensor store, #12 timezone finding |
| `docs/roadmap.md` | Modify | Priority line and table |
| `experiments/weather_snapshot_health.py` | Modify | 7-day coverage, `degraded` status, path from `core/paths.py` |
| `tests/test_weather_snapshot_health.py` | Modify | Coverage tests |
| `experiments/install_weather_snapshot_task.ps1` | Modify | `-WakeToRun` |
| `core/paths.py` | Modify | `GREENLAB_INTERVALS_DIR` |
| `core/greenlab_api.py` | Modify | `fetch_by_date_csv()` |
| `tests/test_greenlab_api.py` | Modify | Client tests |
| `scripts/backfill_sensor.py` | Create | Chunk planning, no-overwrite writes, `--since-last` |
| `tests/test_backfill_sensor.py` | Create | |
| `scripts/sensor_coverage.py` | Create | Per-day coverage and COD health |
| `tests/test_sensor_coverage.py` | Create | |
| `scripts/export_sensor_history.py` | Create | One hashed wide CSV for the benchmarks |
| `tests/test_export_sensor_history.py` | Create | |
| `scripts/install_sensor_collector_task.ps1` | Create | Daily `HAP-SensorCollector-<station>` |
| `AGENTS.md`, `experiments/RESULTS.md` | Modify | Scheduled jobs, results rows |

---

### Task 1: Record the new priority order

**Files:**
- Modify: `docs/decisions.md` (append at end)
- Modify: `docs/roadmap.md:5-15`

- [ ] **Step 1: Append decision #10**

Append to `docs/decisions.md`:

```markdown

## #10 — 2026-10-15 · Thứ tự ưu tiên 1 → 2 ‖ 3 → 4 (thay thế #8)

- **Quyết định:** mạch chính 1 → 2. Hướng 3 chạy song song để lấp khoảng chờ dữ liệu của hướng 2. Hướng 4 chỉ làm sớm H4.1 (sửa HSI rò rỉ) và H4.2 (interface); H4.3–H4.5 chờ verdict B5 (H2.2) và một điểm đo đối chứng.
- **Lý do:** hướng 2 bị giới hạn bởi lịch (cần ~63 ngày bản tin as-issued liên tục, không backfill được). Hướng 4 có mức sẵn sàng thấp, phụ thuộc kết quả hướng 2 và phần cứng (chỉ 1 sensor). Hướng 3 đã đủ dữ liệu quan trắc và có phương pháp tham khảo (Ghaderi 2026).
- **Hệ quả:** cập nhật bảng ưu tiên trong `roadmap.md`. Kế hoạch: `docs/superpowers/plans/2026-10-15-master-execution-plan.md`.
```

- [ ] **Step 2: Update roadmap header**

In `docs/roadmap.md`, replace:

```markdown
**Thứ tự ưu tiên đã chốt: 1 → 2 → 4 → 3.**
Trên slide đề xuất làm 3 song song và 4 sau 3. Chủ dự án chọn làm 4 trước 3; các điểm phụ thuộc phát sinh từ lựa chọn này ghi ở mục Hướng 4.
```

with:

```markdown
**Thứ tự ưu tiên đã chốt: 1 → 2 ‖ 3 → 4** (decisions #10, thay thế #8).
Hướng 3 chạy song song trong lúc hướng 2 chờ đủ chuỗi bản tin. Hướng 4 chỉ làm sớm H4.1 và H4.2; phần còn lại chờ gate.
```

In the same file's table, change the `Ưu tiên` column to: hướng 1 → `**1**`, hướng 2 → `**2**`, hướng 4 → `**4** (H4.1–H4.2 sớm)`, hướng 3 → `**3** (song song)`.

- [ ] **Step 3: Commit**

```bash
git add docs/decisions.md docs/roadmap.md docs/superpowers/plans/
git commit -m "Record priority order 1 > 2 || 3 > 4 and execution plan"
```

---

### Task 2: Honest weather-snapshot healthcheck

**Files:**
- Modify: `experiments/weather_snapshot_health.py` (whole file)
- Test: `tests/test_weather_snapshot_health.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_weather_snapshot_health.py`:

```python
def _write_captures(path, times):
    with open(path, "w") as f:
        for t in times:
            f.write(json.dumps({"station": "s1", "retrieved_at": t.isoformat()}) + "\n")


def test_health_degraded_when_hourly_coverage_low(tmp_path):
    p = tmp_path / "snap.jsonl"
    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    # one capture every 3 h for 7 days, last one 30 min ago -> ~33% of hourly
    times = [now - timedelta(minutes=30) - timedelta(hours=3 * i) for i in range(56)]
    _write_captures(p, times)
    res = check_health("s1", p, now=now)
    assert res["status"] == "degraded"
    assert 0.30 <= res["coverage_7d"] <= 0.36


def test_health_full_hourly_coverage_is_healthy(tmp_path):
    p = tmp_path / "snap.jsonl"
    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    _write_captures(p, [now - timedelta(hours=i) for i in range(168)])
    res = check_health("s1", p, now=now)
    assert res["status"] == "healthy"
    assert res["coverage_7d"] == 1.0


def test_health_coverage_window_starts_at_first_capture(tmp_path):
    p = tmp_path / "snap.jsonl"
    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    # collector started 10 h ago and never missed a run
    _write_captures(p, [now - timedelta(hours=i) for i in range(11)])
    res = check_health("s1", p, now=now)
    assert res["status"] == "healthy"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_weather_snapshot_health.py -v`
Expected: the 3 new tests FAIL with `TypeError: check_health() got an unexpected keyword argument 'now'`. The 3 old tests PASS.

- [ ] **Step 3: Replace the implementation**

Replace the whole of `experiments/weather_snapshot_health.py` with:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_weather_snapshot_health.py -v`
Expected: 6 passed.

- [ ] **Step 5: Check against real data**

Run: `.venv\Scripts\python experiments/weather_snapshot_health.py --station 06M26042804`
Expected: `"status": "degraded"`, `coverage_7d` around 0.3, exit code 1. (On 2026-10-15, 54 of the expected 168 captures were present.)

- [ ] **Step 6: Commit**

```bash
git add experiments/weather_snapshot_health.py tests/test_weather_snapshot_health.py
git commit -m "Healthcheck: flag degraded 7-day snapshot coverage"
```

---

### Task 3: Fewer missed weather captures on the laptop (stop-gap)

This task does not replace an always-on host (owner decision 1 in the master plan). It only stops the task from missing runs while the laptop is asleep.

**Files:**
- Modify: `experiments/install_weather_snapshot_task.ps1:28`

- [ ] **Step 1: Add `-WakeToRun`**

Replace the `$settings = ...` line with:

```powershell
# WakeToRun: the laptop sleeps between uses; without it the hourly record has
# multi-day holes (7-day coverage was ~32% on 2026-10-15). Wake timers must
# also be enabled in the power plan (see AGENTS.md).
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
```

- [ ] **Step 2: Re-register the task and enable wake timers**

Run in an elevated PowerShell. Re-registering keeps the task name, so the existing JSONL file is not touched:

```powershell
powershell -ExecutionPolicy Bypass -File experiments\install_weather_snapshot_task.ps1
powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
powercfg /setactive SCHEME_CURRENT
(Get-ScheduledTask -TaskName HAP-WeatherSnapshot-06M26042804).Settings.WakeToRun
```

Expected: the last line prints `True`.

- [ ] **Step 3: Commit**

```bash
git add experiments/install_weather_snapshot_task.ps1
git commit -m "Weather snapshot task wakes the machine to run"
```

- [ ] **Step 4: Re-check after 7 days**

Run Task 2's healthcheck on 2026-10-22. If `coverage_7d` is still below 0.9, escalate owner decision 1 (move the collector to an always-on host). Do not consider this task done until the coverage is ≥ 0.9.

---

### Task 4: GreenLab `DataByDate` client

**Files:**
- Modify: `core/paths.py` (after `GREENLAB_ALL_DATA_DIR`)
- Modify: `core/greenlab_api.py` (after `fetch_latest_snapshot`)
- Test: `tests/test_greenlab_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_greenlab_api.py`:

```python
import pytest

_LONG_CSV = (
    "Date,DeviceSerialNumber,SensorType,Value,Unit,Status\r\n"
    "2026-07-27 00:00,06M26042804,pH,8.01,,Good\r\n"
)


def _patch_credentials(monkeypatch):
    monkeypatch.setattr(greenlab_api, "GREENLAB_API_USERNAME", "user")
    monkeypatch.setattr(greenlab_api, "GREENLAB_API_PASSWORD", "password")


def test_fetch_by_date_csv_requests_range_and_returns_text(monkeypatch):
    seen = {}

    class Response:
        text = "\ufeff" + _LONG_CSV
        def raise_for_status(self): pass

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return Response()

    _patch_credentials(monkeypatch)
    monkeypatch.setattr(greenlab_api.requests, "get", fake_get)
    text = greenlab_api.fetch_by_date_csv("06M26042804", "2026-07-27", "2026-08-02")
    assert seen["url"].endswith("/Datums/DataByDate")
    assert seen["params"] == {"DeviceSerialNumber": "06M26042804", "StartDate": "2026-07-27", "EndDate": "2026-08-02"}
    assert text == _LONG_CSV


def test_fetch_by_date_csv_rejects_unexpected_payload(monkeypatch):
    class Response:
        text = "<html>login</html>"
        def raise_for_status(self): pass

    _patch_credentials(monkeypatch)
    monkeypatch.setattr(greenlab_api.requests, "get", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="greenlab_by_date_unexpected_payload"):
        greenlab_api.fetch_by_date_csv("06M26042804", "2026-07-27", "2026-07-28")


def test_fetch_by_date_csv_requires_credentials(monkeypatch):
    monkeypatch.setattr(greenlab_api, "GREENLAB_API_USERNAME", "")
    with pytest.raises(RuntimeError, match="greenlab_api_credentials_missing"):
        greenlab_api.fetch_by_date_csv("06M26042804", "2026-07-27", "2026-07-28")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_greenlab_api.py -v`
Expected: the 3 new tests FAIL with `AttributeError: module 'core.greenlab_api' has no attribute 'fetch_by_date_csv'`.

- [ ] **Step 3: Add the path constant**

In `core/paths.py`, after the `GREENLAB_ALL_DATA_DIR = ...` line:

```python
GREENLAB_INTERVALS_DIR = GREENLAB_EXPORTS_DIR / "intervals"
```

- [ ] **Step 4: Implement the client**

In `core/greenlab_api.py`, after `fetch_latest_snapshot`:

```python
_LONG_HEADER = "Date,DeviceSerialNumber,SensorType,Value"


def fetch_by_date_csv(station_serial: str, start: str, end: str) -> str:
    """Long-format CSV for ``start``..``end`` (YYYY-MM-DD) from /Datums/DataByDate.

    Returned as text so the caller can store the provider's bytes unchanged.
    """
    if not GREENLAB_API_USERNAME or not GREENLAB_API_PASSWORD:
        raise RuntimeError("greenlab_api_credentials_missing")
    response = requests.get(
        f"{GREENLAB_API_BASE_URL.rstrip('/')}/Datums/DataByDate",
        params={"DeviceSerialNumber": station_serial, "StartDate": start, "EndDate": end},
        auth=(GREENLAB_API_USERNAME, GREENLAB_API_PASSWORD), timeout=180,
    )
    response.raise_for_status()
    text = response.text.lstrip("\ufeff")
    if not text.startswith(_LONG_HEADER):
        raise RuntimeError("greenlab_by_date_unexpected_payload")
    return text
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_greenlab_api.py -v`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add core/paths.py core/greenlab_api.py tests/test_greenlab_api.py
git commit -m "Add GreenLab DataByDate client and intervals path"
```

---

### Task 5: Backfill script (never overwrites)

**Files:**
- Create: `scripts/backfill_sensor.py`
- Test: `tests/test_backfill_sensor.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_backfill_sensor.py`:

```python
from datetime import date

import pytest

from scripts.backfill_sensor import (
    chunk_path, last_covered_date, plan_chunks, run_backfill, write_new,
)

HEADER = "Date,DeviceSerialNumber,SensorType,Value,Unit,Status\n"


def test_plan_chunks_overlap_by_one_day_and_cap_length():
    chunks = plan_chunks(date(2026, 7, 26), date(2026, 8, 10), max_days=7)
    assert chunks == [
        (date(2026, 7, 26), date(2026, 8, 1)),
        (date(2026, 8, 1), date(2026, 8, 7)),
        (date(2026, 8, 7), date(2026, 8, 10)),
    ]
    assert all((end - start).days <= 6 for start, end in chunks)


def test_plan_chunks_single_day_and_empty():
    assert plan_chunks(date(2026, 9, 1), date(2026, 9, 1)) == [(date(2026, 9, 1), date(2026, 9, 1))]
    assert plan_chunks(date(2026, 9, 2), date(2026, 9, 1)) == []


def test_plan_chunks_rejects_max_days_below_two():
    with pytest.raises(ValueError):
        plan_chunks(date(2026, 9, 1), date(2026, 9, 5), max_days=1)


def test_chunk_path_matches_node_fetcher_naming(tmp_path):
    path = chunk_path(tmp_path, "06M26042804", "HAIPHONG", date(2026, 7, 5), date(2026, 7, 26))
    assert path.name == "06M26042804_HAIPHONG_20260705_to_20260726.csv"


def test_last_covered_date_reads_csv_names_only(tmp_path):
    (tmp_path / "06M26042804_HAIPHONG_20260705_to_20260726.csv").write_text(HEADER)
    (tmp_path / "06M26042804_HAIPHONG_20260801_to_20260901.json").write_text("{}")
    (tmp_path / "06M26042803_QUANGNINH_20260101_to_20261001.csv").write_text(HEADER)
    assert last_covered_date(tmp_path, "06M26042804") == date(2026, 7, 26)
    assert last_covered_date(tmp_path, "XXXX") is None


def test_write_new_never_overwrites(tmp_path):
    target = tmp_path / "a.csv"
    assert write_new(target, "first") is True
    assert write_new(target, "second") is False
    assert target.read_text() == "first"


def test_run_backfill_skips_existing_and_empty_chunks(tmp_path):
    existing = chunk_path(tmp_path, "S", "R", date(2026, 7, 26), date(2026, 8, 1))
    existing.write_text("original")
    calls = []

    def fake_fetch(station, start, end):
        calls.append((start, end))
        if start == "2026-08-07":
            return HEADER  # provider had no rows for this chunk
        return HEADER + f"{start} 00:00,S,pH,8.0,,Good\n"

    results = run_backfill("S", "R", date(2026, 7, 26), date(2026, 8, 10), tmp_path, fetch=fake_fetch, log=lambda _: None)
    assert [r["status"] for r in results] == ["exists", "written", "empty"]
    assert calls == [("2026-08-01", "2026-08-07"), ("2026-08-07", "2026-08-10")]
    assert existing.read_text() == "original"
    assert not chunk_path(tmp_path, "S", "R", date(2026, 8, 7), date(2026, 8, 10)).exists()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_backfill_sensor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.backfill_sensor'`.

- [ ] **Step 3: Implement**

Create an empty `scripts/__init__.py`. `experiments/` already has one; this makes `from scripts.… import` explicit rather than relying on namespace packages. Tasks 6 and 10 also depend on it.

Create `scripts/backfill_sensor.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_backfill_sensor.py -v`
Expected: 7 passed.

- [ ] **Step 5: Isolation check and full suite**

Run: `.venv\Scripts\python scripts\check_isolation.py; .venv\Scripts\python -m pytest -q`
Expected: the isolation check passes; all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/__init__.py scripts/backfill_sensor.py tests/test_backfill_sensor.py
git commit -m "Add no-overwrite GreenLab sensor backfill script"
```

---

### Task 6: Per-day coverage and COD report

**Files:**
- Create: `scripts/sensor_coverage.py`
- Test: `tests/test_sensor_coverage.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sensor_coverage.py`:

```python
import numpy as np
import pandas as pd

from scripts.sensor_coverage import daily_coverage

TZ = "Asia/Ho_Chi_Minh"


def _minutes(start_local: str, periods: int) -> pd.Series:
    return pd.Series(pd.date_range(start_local, periods=periods, freq="min", tz=TZ).tz_convert("UTC"))


def _frame(times: pd.Series, cod) -> pd.DataFrame:
    return pd.DataFrame({"device": "S", "fetchedAt": times, "COD": cod})


def test_daily_coverage_counts_local_minutes_and_fills_missing_days():
    day1 = _frame(_minutes("2026-09-01 00:00", 1440), np.linspace(20, 30, 1440))
    day3 = _frame(_minutes("2026-09-03 00:00", 720), np.linspace(20, 30, 720))
    out = daily_coverage(pd.concat([day1, day3], ignore_index=True)).set_index("date")
    assert out.loc[pd.Timestamp("2026-09-01").date(), "coverage"] == 1.0
    assert bool(out.loc[pd.Timestamp("2026-09-01").date(), "meets_gate"]) is True
    assert out.loc[pd.Timestamp("2026-09-02").date(), "minutes"] == 0
    assert out.loc[pd.Timestamp("2026-09-02").date(), "cod_status"] == "NO_DATA"
    assert out.loc[pd.Timestamp("2026-09-03").date(), "coverage"] == 0.5
    assert bool(out.loc[pd.Timestamp("2026-09-03").date(), "meets_gate"]) is False


def test_daily_coverage_flags_cod_rail_and_out_of_range():
    rail = _frame(_minutes("2026-09-01 00:00", 60), [558.8] * 60)
    high = _frame(_minutes("2026-09-02 00:00", 60), np.linspace(185, 195, 60))
    ok = _frame(_minutes("2026-09-03 00:00", 60), np.linspace(20, 30, 60))
    out = daily_coverage(pd.concat([rail, high, ok], ignore_index=True)).set_index("date")
    d = lambda s: pd.Timestamp(s).date()
    assert out.loc[d("2026-09-01"), "cod_status"] == "INVALID"
    assert out.loc[d("2026-09-01"), "cod_rail_share"] == 1.0
    assert out.loc[d("2026-09-02"), "cod_status"] == "INVALID"   # >100 is outside PLAUSIBLE_RANGE
    assert out.loc[d("2026-09-02"), "cod_in_range_share"] == 0.0
    assert out.loc[d("2026-09-03"), "cod_status"] == "VALID"
    assert out.loc[d("2026-09-03"), "cod_median"] == 25.0


def test_daily_coverage_empty():
    assert daily_coverage(pd.DataFrame(columns=["device", "fetchedAt", "COD"])).empty
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_sensor_coverage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.sensor_coverage'`.

- [ ] **Step 3: Implement**

Create `scripts/sensor_coverage.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_sensor_coverage.py -v`
Expected: 3 passed.

- [ ] **Step 5: Baseline on the current data (before the backfill)**

Run: `.venv\Scripts\python scripts/sensor_coverage.py --station 06M26042804 --no-write`
Expected: exit 1. Days after 2026-07-26 are listed as below the gate, apart from the few days in `live-cache/`.

- [ ] **Step 6: Commit**

```bash
git add scripts/sensor_coverage.py tests/test_sensor_coverage.py
git commit -m "Add per-day sensor coverage and COD health report"
```

---

### Task 7: Run the backfill (operational; needs credentials)

**Files:** none tracked. New files appear in `data/greenlab/exports/intervals/` (gitignored).

**Do not write a one-off probe file first.** `--since-last` resumes from the *newest* interval file. A probe such as `20260920_to_20260921.csv` would move that marker forward, and the range 07-26 → 09-20 would be silently skipped. The first chunk below is the credential check.

- [ ] **Step 1: Full backfill with an explicit start**

Run: `.venv\Scripts\python scripts/backfill_sensor.py --station 06M26042804 --region HAIPHONG --start 2026-07-26`
Expected: about 12 chunks from 2026-07-26 to yesterday. Each chunk is either `written` or `exists`. A healthy week chunk is on the order of 7 × 28,000 rows (the one-day probe on 2026-09-20 returned 28,690 rows). If the first chunk fails with a 401/403, fix `TK_DHTB`/`MK_DHTB` in `.env` and re-run.

If a chunk raises an HTTP error, re-run the same command. Chunks already written are skipped.

- [ ] **Step 2: Go to Task 8 now**

The per-day coverage report depends on the timezone of the `Date` column. Its run directory is dated and is never overwritten, so a report produced with the wrong offset cannot be regenerated on the same day. Run the coverage report at the end of Task 8 (Step 6), not here.

---

### Task 8: Timezone of the `Date` column (D0.2)

`_normalize_export()` parses the naive `Date` column (and the naive `fetchedAt` in `all_data/*_All.csv`) as **UTC**. If GreenLab writes local time (UTC+7), every backfilled timestamp is shifted by 7 h. That would corrupt the weather joins (B5) and the day/night features. Verify this before any benchmark run.

**Files:** possibly `core/greenlab_api.py`, `tests/test_greenlab_api.py`, `docs/decisions.md`

- [ ] **Step 1: Compare backfilled data with live-cache readings (which are tz-aware)**

Save the following as a scratch file (outside the repo) and run it with `.venv\Scripts\python <scratch>.py`:

```python
import json, sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, r"D:\2impusc\Hydro-Aqua-Predict")
from core import paths
from core.greenlab_api import _normalize_export

station = "06M26042804"
live_rows = []
for day in ("20260905", "20261008"):
    path = paths.GREENLAB_LIVE_CACHE_DIR / station / f"{day}.jsonl"
    live_rows += [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
live = pd.DataFrame(live_rows)
live["t"] = pd.to_datetime(live["fetchedAt"], utc=True).dt.floor("min")
files = sorted(paths.GREENLAB_INTERVALS_DIR.glob(f"{station}_*_to_*.csv"))
hist = pd.concat([_normalize_export(p, station) for p in files], ignore_index=True)
for hours in (-7, 0, 7):
    shifted = hist.assign(t=hist["fetchedAt"].dt.floor("min") + pd.Timedelta(hours=hours))
    m = live.merge(shifted, on="t", suffixes=("_live", "_hist"))
    print(hours, len(m),
          (m["Temperature_live"] - m["Temperature_hist"]).abs().median(),
          (m["pH_live"] - m["pH_hist"]).abs().median())
```

How to read the output: the correct offset is the row with many matches and median differences close to 0.
- Best row `0` → `Date` is UTC. No code change. Go to Step 4.
- Best row `-7` → `Date` is local time. Do Steps 2–3.

- [ ] **Step 2 (only if the best offset is -7): write the failing test**

Append to `tests/test_greenlab_api.py`:

```python
def test_long_format_date_is_local_time(tmp_path):
    path = tmp_path / "06M26042804_HAIPHONG_20261008_to_20261008.csv"
    path.write_text(
        "Date,DeviceSerialNumber,SensorType,Value,Unit,Status\n"
        "2026-10-08 15:00,06M26042804,pH,8.0,,Good\n",
        encoding="utf-8",
    )
    frame = greenlab_api._normalize_export(path, "06M26042804")
    assert frame.iloc[0]["fetchedAt"] == pd.Timestamp("2026-10-08 08:00", tz="UTC")
```

Run: `.venv\Scripts\python -m pytest tests/test_greenlab_api.py::test_long_format_date_is_local_time -v`
Expected: FAIL (the value is 15:00 UTC).

- [ ] **Step 3 (only if the best offset is -7): fix the parsing**

In `core/greenlab_api._normalize_export`, replace:

```python
        frame["fetchedAt"] = pd.to_datetime(frame["Date"], utc=True)
```

with:

```python
        # GreenLab DataByDate writes naive local (UTC+7) time; see decisions #12.
        frame["fetchedAt"] = pd.to_datetime(frame["Date"]).dt.tz_localize("Asia/Ho_Chi_Minh").dt.tz_convert("UTC")
```

Re-run the scratch script. Expected: the `0` row is now the best match. Then run the full suite: `.venv\Scripts\python -m pytest -q`. All tests must pass.

Also check `all_data/*_All.csv`, which has a naive `fetchedAt`: compare its rows for 2026-07-01..07-04 against `intervals/06M26042804_HAIPHONG_20260703_to_20260704.csv` with the same shift method. If it is also local time, apply the same localisation in the `{"device", "fetchedAt"}` branch, adding a test in the same style.

- [ ] **Step 4: Record the finding**

Append to `docs/decisions.md`:

```markdown

## #12 — 2026-10-?? · Múi giờ của cột `Date` trong GreenLab DataByDate

- **Kết quả kiểm tra:** <offset tốt nhất, số mốc khớp, sai lệch trung vị Temperature/pH>.
- **Quyết định:** <giữ UTC | localize Asia/Ho_Chi_Minh rồi đổi sang UTC> cho `intervals/` <và `all_data/`>.
- **Hệ quả:** <không đổi | mọi kết quả benchmark trước ngày này dùng mốc lệch 7 h và phải chạy lại>.
```

Fill in the `<...>` values from the Step 1 output. Do this at execution time; do not commit the placeholders.

- [ ] **Step 5: Commit**

```bash
git add docs/decisions.md core/greenlab_api.py tests/test_greenlab_api.py
git commit -m "Verify GreenLab DataByDate timezone"
```

- [ ] **Step 6: Coverage report (after the timezone is settled)**

Run: `.venv\Scripts\python scripts/sensor_coverage.py --station 06M26042804`
Expected: writes `artifacts/experiments/sensor-coverage-<today>/06M26042804_daily.csv`. Copy the summary lines (days judged, days meeting the gate, COD status counts, below-gate list) into the notes for Task 11.

---

### Task 9: Daily sensor collector task (D0.3)

Sensor history can be fetched after the fact, so `--since-last` catches up on any days the laptop missed. No always-on host is needed for sensor collection (unlike weather snapshots).

**Files:**
- Create: `scripts/install_sensor_collector_task.ps1`
- Modify: `AGENTS.md` (section "Scheduled jobs on the dev machine")

- [ ] **Step 1: Write the installer**

Create `scripts/install_sensor_collector_task.ps1`:

```powershell
param(
    [string]$Station = "06M26042804",
    [string]$Region = "HAIPHONG",
    [string]$TaskName = "",
    [string]$At = "06:13",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
if (-not $TaskName) { $TaskName = "HAP-SensorCollector-$Station" }

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "Removed scheduled task: $TaskName"
    exit 0
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Root venv not found: $python" }

# Daily catch-up: DataByDate is retrospective, so a missed day is fetched by
# the next successful run (--since-last). Existing files are never overwritten.
$action = New-ScheduledTaskAction -Execute $python -WorkingDirectory $repoRoot -Argument "scripts\backfill_sensor.py --station $Station --region $Region --since-last"
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Daily GreenLab DataByDate catch-up for $Station (append-only files)." -Force | Out-Null
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
```

- [ ] **Step 2: Install and trigger once**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_sensor_collector_task.ps1
Start-ScheduledTask -TaskName HAP-SensorCollector-06M26042804
Get-ScheduledTask -TaskName HAP-SensorCollector-06M26042804 | Get-ScheduledTaskInfo | Select LastRunTime, LastTaskResult
```

Expected now: `LastTaskResult` is `0`. This only shows that the task starts, because the script reports `up to date` without calling the API.

**Real check, the next morning:** a new `…_to_<yesterday>.csv` exists in `data/greenlab/exports/intervals/`, and `LastTaskResult` is `0`. That proves `.env` credentials load under Task Scheduler's context. Do not tick this task until that file exists.

- [ ] **Step 3: Document it**

In `AGENTS.md`, under "Scheduled jobs on the dev machine", add:

```markdown
- `HAP-SensorCollector-06M26042804` — daily 06:13 `scripts/backfill_sensor.py --since-last`
  into `data/greenlab/exports/intervals/` (append-only, catches up after missed days).
  Install/remove: `scripts/install_sensor_collector_task.ps1 [-Remove]`.
  Health: `python scripts/sensor_coverage.py --station 06M26042804 --last-days 7 --no-write`.
  `--since-last` resumes from the newest interval file: never write a probe file ahead of it
  (use `--start/--end` to fill behind); the coverage report catches any gap that slips through.
```

In the same section, change the weather-task line "(append-only; runs on battery)" to "(append-only; runs on battery, wakes the machine)". Add the health note: "`status` is `degraded` when 7-day coverage < 90%".

- [ ] **Step 4: Commit**

```bash
git add scripts/install_sensor_collector_task.ps1 AGENTS.md
git commit -m "Add daily GreenLab sensor collector task"
```

---

### Task 10: One canonical, hashed history export (D0.4)

**Files:**
- Create: `scripts/export_sensor_history.py`
- Test: `tests/test_export_sensor_history.py`
- Modify: `docs/decisions.md`

- [ ] **Step 1: Write the failing test**

Create `tests/test_export_sensor_history.py`:

```python
import hashlib
import json

import pytest

from core import greenlab_api
from experiments.forecast_sensor_v2 import load_sensor_data
from scripts.export_sensor_history import export_history

LONG = (
    "Date,DeviceSerialNumber,SensorType,Value,Unit,Status\n"
    "2026-08-01 00:00,06M26042804,Temp,30.1,C,Good\n"
    "2026-08-01 00:00,06M26042804,pH,8.0,,Good\n"
    "2026-08-01 00:01,06M26042804,Temp,30.2,C,Good\n"
    "2026-08-01 00:01,06M26042804,pH,8.1,,Good\n"
)


def test_export_history_writes_hashed_csv_readable_by_benchmark(tmp_path, monkeypatch):
    exports = tmp_path / "exports"
    (exports / "intervals").mkdir(parents=True)
    (exports / "intervals" / "06M26042804_HAIPHONG_20260801_to_20260801.csv").write_text(LONG, encoding="utf-8")
    monkeypatch.setattr(greenlab_api, "GREENLAB_API_CACHE_DIR", exports / "live-cache")

    manifest = export_history("06M26042804", tmp_path / "out")
    csv_path = tmp_path / "out" / manifest["run"] / "06M26042804.csv"
    assert manifest["rows"] == 2
    assert manifest["sha256"] == hashlib.sha256(csv_path.read_bytes()).hexdigest()
    assert json.loads((csv_path.parent / "manifest.json").read_text())["sha256"] == manifest["sha256"]

    frame = load_sensor_data(csv_path, "06M26042804")
    assert list(frame["Temperature"]) == [30.1, 30.2]

    with pytest.raises(FileExistsError):
        export_history("06M26042804", tmp_path / "out")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_export_sensor_history.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.export_sensor_history'`.

- [ ] **Step 3: Implement**

Create `scripts/export_sensor_history.py`:

```python
"""Freeze the canonical sensor history into one hashed CSV (roadmap D0.4).

Canonical store = append-only files under data/greenlab/exports/ (decisions #11),
merged by core.greenlab_api.load_cached_history(). Benchmarks read the frozen CSV,
so every result can name the exact input by sha256.

    python scripts/export_sensor_history.py --station 06M26042804
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.greenlab_api import load_cached_history  # noqa: E402


def export_history(station: str, out_dir: Path) -> dict:
    history = load_cached_history(station)
    if history.empty:
        raise RuntimeError(f"no sensor history for {station}")
    last = history["fetchedAt"].max()
    run = f"sensor-history-{last:%Y%m%d}"
    run_dir = out_dir / run
    run_dir.mkdir(parents=True, exist_ok=True)
    csv_path = run_dir / f"{station}.csv"
    if csv_path.exists():
        raise FileExistsError(csv_path)
    history.to_csv(csv_path, index=False)
    manifest = {
        "run": run,
        "station": station,
        "rows": int(len(history)),
        "first": history["fetchedAt"].min().isoformat(),
        "last": last.isoformat(),
        "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "source": "core.greenlab_api.load_cached_history (all_data + intervals + live-cache)",
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--station", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(export_history(args.station, paths.EXPERIMENT_OUTPUT_DIR), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_export_sensor_history.py -v`
Expected: 1 passed.

- [ ] **Step 5: Export the real history (after Tasks 7–8)**

Run: `.venv\Scripts\python scripts/export_sensor_history.py --station 06M26042804`
Expected: a manifest with `first` 2026-05-29 and `last` around yesterday. Rows ≈ number of minutes covered.

Then verify that the benchmark accepts it (smoke run only, not the H1.1 study):

`.venv\Scripts\python experiments/forecast_sensor_v2.py artifacts\experiments\<run>\06M26042804.csv --station 06M26042804 --output <scratchpad>\smoke --fast --target Temperature --horizon 60`

Expected: it finishes without error.

- [ ] **Step 6: Record decision #11**

Append to `docs/decisions.md`:

```markdown

## #11 — 2026-10-?? · Kho lịch sử sensor chuẩn

- **Quyết định:** nguồn chuẩn là các file append-only trong `data/greenlab/exports/` (`all_data/`, `intervals/`, `live-cache/`), gộp bằng `core.greenlab_api.load_cached_history()`. Postgres của research-map chỉ phục vụ bản đồ. Benchmark đọc bản xuất cố định từ `scripts/export_sensor_history.py` (có sha256 trong manifest).
- **Lý do:** Postgres chỉ có những ngày worker chạy; `DataByDate` lấy lại được mọi ngày.
- **Hệ quả:** `HAP-SensorCollector` (Task 9) giữ kho này liên tục.
```

Use the execution date in place of `??`.

- [ ] **Step 7: Commit**

```bash
git add scripts/export_sensor_history.py tests/test_export_sensor_history.py docs/decisions.md
git commit -m "Add hashed sensor history export; canonical store decision"
```

---

### Task 11: Results index and Phase 0 gate review

**Files:**
- Modify: `experiments/RESULTS.md`, `AGENTS.md` (COD gotcha)

- [ ] **Step 1: Add rows for the new runs**

Append rows to the table in `experiments/RESULTS.md`, using the real numbers from the coverage report (Task 8, Step 6, after the timezone check) and from Task 10:

```markdown
| 2026-10-?? | `sensor-coverage-YYYYMMDD/` | … | 1 | `scripts/sensor_coverage.py` | [phase0 plan](../docs/superpowers/plans/2026-10-15-phase0-data-foundation.md) | N/M days ≥ 90 %; gaps: …; COD: VALID x / INVALID y |
| 2026-10-?? | `sensor-history-YYYYMMDD/` | … | 2 | `scripts/export_sensor_history.py` | same | rows …, 2026-05-29 → …, sha256 … (first 12 chars) |
```

- [ ] **Step 2: Fill the empty "Key result" cells for the main runs**

For `retrospective-*`, `spatial-applicability-*`, `weather-risk-pilot/` and `forecast-v2/`, copy the headline number or verdict from the guide linked in the "Discussed in" column (for example `docs/guide/20-…` for P0, and `docs/guide/26-…` for the pilot round 3, where gates A/B/C passed on the fixture and there were 0 real origins). Write "—" only for single-figure rows with no linked guide.

- [ ] **Step 3: Update the COD gotcha**

In `AGENTS.md`, replace the "COD rail 558.8 = dead sensor" bullet with the finding from the Task 7 report. For example: "COD rail 558.8 until <date>; from <date> median ≈ <x> (outside PLAUSIBLE_RANGE 0–100 → still INVALID)". Use the actual numbers. If COD is now in range and VALID, say so and note that `core/quality.py` needs no change.

In the same file, update the test count in the "Run" section (`# 136 tests`) to the number reported by `pytest -q`.

- [ ] **Step 4: Phase 0 gate review**

Check each gate. Every box must be ticked before Phase 1 planning starts:

- [ ] `scripts/sensor_coverage.py --station 06M26042804` shows ≥ 90 % on every day from 2026-07-26, or each gap is listed with its cause (provider gap vs. our error) in the `RESULTS.md` row
- [ ] The timezone decision (#12) is recorded
- [ ] `HAP-SensorCollector` last result is `0`, and `--last-days 7 --no-write` exits 0
- [ ] The weather healthcheck reports `healthy` (coverage_7d ≥ 0.9), or owner decision 1 (always-on host) has been raised
- [ ] Full suite green: `.venv\Scripts\python -m pytest -q` and `scripts\check_isolation.py`

- [ ] **Step 5: Commit**

```bash
git add experiments/RESULTS.md AGENTS.md
git commit -m "Phase 0: record coverage, history export and COD status"
```
