"""Hourly health check of the dev-machine data collection (ops task 1.1).

Checks the research-map Docker containers, the freshness of the snapshot files and job logs,
7-day weather-snapshot coverage, yesterday's sensor coverage and the HAP-* scheduled tasks.
Read-only except one JSON line appended to ``paths.HEALTH_LOG`` per run.

    python scripts/health_check.py                 # check, append to runtime/logs/health.log, popup on change
    python scripts/health_check.py --no-notify     # manual run: no popup
    python scripts/health_check.py --no-log        # print only

Exit code: 0 ok, 1 warn, 2 fail. A popup (WScript.Shell, closes itself after 30 s) is shown when
the overall status is FAIL, or WARN and different from the previous logged run, so a week of
low coverage does not pop up every hour.

``--fix-docker-stale-sockets`` (default off): when ``docker ps`` fails and no Docker Desktop
process is running, rename ``%LOCALAPPDATA%\\Docker\\run`` to ``run.stale-<stamp>`` (never delete)
and start Docker Desktop. This is the 2026-10-30 unclean-shutdown failure (docs/guide/06-runbook.md).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.greenlab_api import _PARAMS, _normalize_export, _read_jsonl_frame  # noqa: E402
from experiments.weather_snapshot_health import check_health as snapshot_health  # noqa: E402
from scripts.sensor_coverage import LOCAL_TZ, daily_coverage  # noqa: E402

STATION = "06M26042804"
OK, WARN, FAIL = "ok", "warn", "fail"
SEVERITY = {OK: 0, WARN: 1, FAIL: 2}

DOCKER_CONTAINERS = ["research-map-api-1", "research-map-worker-1", "research-map-postgres-1", "research-map-frontend-1"]
DOCKER_TIMEOUT_S = 30
FRESHNESS_LIMITS_H = {"shadow_runner_log": 20 / 60, "hazard_jobs_log": 2.0}
SNAPSHOT_STALE_H = 2.0
MIN_COVERAGE = 0.9
SENSOR_GATE = 0.9
# HAP-SensorCollector writes yesterday's interval file at 06:13 local; before this hour a
# below-gate yesterday is expected (only the live cache has it), so it is not a warning.
SENSOR_READY_HOUR_LOCAL = 7
OWN_TASK = "HAP-HealthCheck"
EXPECTED_TASKS = [f"HAP-WeatherSnapshot-{STATION}", f"HAP-SensorCollector-{STATION}",
                  "HAP-ShadowRunner", "HAP-HazardRunner", "HAP-ECMWFStorms"]
# Task Scheduler last-result codes that are not failures (compared as unsigned 32-bit).
TASK_OK_CODES = {
    0,
    0x41301,     # task is currently running
    0x41303,     # task has not yet run
    0x41325,     # task is queued
    0x800710E0,  # operator refused: IgnoreNew re-trigger while an instance runs
}
TAIL_BYTES = 16384
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash when run by pythonw from Task Scheduler

_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")
_INTERVAL_RE = re.compile(r"_(\d{8})_to_(\d{8})\.csv$")


def _result(name: str, status: str, **detail) -> dict:
    return {"name": name, "status": status, **detail}


def worst(statuses) -> str:
    return max(statuses, key=SEVERITY.__getitem__, default=OK)


# --- Docker -----------------------------------------------------------------------------------

def check_docker(ps_output: str | None, error: str | None = None,
                 required: list[str] = DOCKER_CONTAINERS) -> dict:
    """``ps_output`` is ``docker ps --format '{{.Names}}\\t{{.Status}}'``; None means docker did not answer."""
    if ps_output is None:
        return _result("docker", FAIL, reason="docker_not_responding", error=error)
    running = {}
    for line in ps_output.splitlines():
        if "\t" in line:
            name, status = line.split("\t", 1)
            running[name.strip()] = status.strip()
    containers, statuses = {}, []
    for name in required:
        status = running.get(name)
        if status is None or not status.startswith("Up"):
            level = FAIL
        elif "unhealthy" in status:
            level = WARN
        else:
            level = OK
        containers[name] = status or "missing"
        statuses.append(level)
    return _result("docker", worst(statuses), containers=containers)


def run_docker_ps(timeout: int = DOCKER_TIMEOUT_S) -> tuple[str | None, str | None]:
    try:
        proc = subprocess.run(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
                              capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
    except FileNotFoundError:
        return None, "docker CLI not found"
    except subprocess.TimeoutExpired:
        return None, f"docker ps timed out after {timeout}s"
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout).strip()[:300]
    return proc.stdout, None


# --- Freshness ----------------------------------------------------------------------------------

def _parse_ts(text: str) -> dt.datetime | None:
    match = _TS_RE.search(text)
    if not match:
        return None
    value = dt.datetime.fromisoformat(match.group(0).replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def newest_log_time(path: Path) -> tuple[dt.datetime | None, str]:
    """Timestamp of the newest log line (last parseable line in the tail); falls back to mtime."""
    with open(path, "rb") as f:
        f.seek(max(0, path.stat().st_size - TAIL_BYTES))
        tail = f.read().decode("utf-8", errors="replace")
    for line in reversed(tail.splitlines()):
        stamp = _parse_ts(line[:64])
        if stamp is not None:
            return stamp, "last_line"
    return dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc), "mtime"


def check_log_freshness(name: str, path: Path, max_age_hours: float, now: dt.datetime) -> dict:
    if not path.exists():
        return _result(name, FAIL, reason="file_not_found", path=str(path))
    newest, source = newest_log_time(path)
    age_h = (now - newest).total_seconds() / 3600
    status = OK if age_h <= max_age_hours else FAIL
    return _result(name, status, newest=newest.isoformat(), age_hours=round(age_h, 2),
                   max_age_hours=round(max_age_hours, 2), source=source)


def check_snapshots(name: str, path: Path, now: dt.datetime, station: str = STATION,
                    min_coverage: float = MIN_COVERAGE) -> dict:
    """Freshness (FAIL when > 2 h) and 7-day coverage (WARN when < min) via weather_snapshot_health."""
    health = snapshot_health(station, path, now=now, min_coverage=min_coverage)
    if health["status"] == "missing":
        return _result(name, FAIL, reason=health.get("reason"), path=str(path))
    age_h = health["age_hours"]
    coverage = health["coverage_7d"]
    if age_h > SNAPSHOT_STALE_H:
        status = FAIL
    elif coverage < min_coverage:
        status = WARN
    else:
        status = OK
    return _result(name, status, last_capture_at=health["last_capture_at"], age_hours=age_h,
                   coverage_7d=coverage, min_coverage=min_coverage, captures_24h=health["captures_24h"])


# --- Sensor coverage --------------------------------------------------------------------------

def sensor_target_day(now: dt.datetime) -> tuple[dt.date, bool]:
    """Yesterday (local) and whether the daily collector should already have fetched it."""
    local = pd.Timestamp(now).tz_convert(LOCAL_TZ)
    return (local - pd.Timedelta(days=1)).date(), local.hour >= SENSOR_READY_HOUR_LOCAL


def load_day_history(station: str, day: dt.date, intervals_dir: Path | None = None,
                     live_cache_dir: Path | None = None) -> pd.DataFrame:
    """Only the interval files that cover ``day`` plus that day's live cache (seconds, not the 37 s full load)."""
    intervals_dir = intervals_dir or paths.GREENLAB_INTERVALS_DIR
    live_cache_dir = live_cache_dir or paths.GREENLAB_LIVE_CACHE_DIR
    frames = []
    for path in sorted(intervals_dir.glob(f"{station}_*.csv")) if intervals_dir.exists() else []:
        match = _INTERVAL_RE.search(path.name)
        if not match:
            continue
        start, end = (dt.datetime.strptime(v, "%Y%m%d").date() for v in match.groups())
        if start <= day < end or start == end == day:
            frames.append(_normalize_export(path, station))
    live = live_cache_dir / station / f"{day:%Y%m%d}.jsonl"
    if live.exists():
        frames.append(_read_jsonl_frame(live))
    frames = [f for f in frames if not f.empty and {"device", "fetchedAt"}.issubset(f.columns)]
    if not frames:
        return pd.DataFrame(columns=["device", "fetchedAt", *_PARAMS])
    combined = pd.concat(frames, ignore_index=True)
    combined["fetchedAt"] = pd.to_datetime(combined["fetchedAt"], utc=True)
    params = [p for p in _PARAMS if p in combined.columns]
    return combined.groupby(["device", "fetchedAt"], as_index=False)[params].median()


def check_sensor_coverage(history: pd.DataFrame, day: dt.date, collector_due: bool,
                          gate: float = SENSOR_GATE) -> dict:
    report = daily_coverage(history, min_fraction=gate, until=day)
    row = report[report["date"] == day]
    coverage = float(row["coverage"].iloc[0]) if len(row) else 0.0
    minutes = int(row["minutes"].iloc[0]) if len(row) else 0
    if coverage >= gate:
        status, note = OK, None
    elif not collector_due:
        status, note = OK, "collector_not_due_yet"
    else:
        status, note = WARN, "below_gate"
    out = _result("sensor_coverage_yesterday", status, date=str(day), minutes=minutes,
                  coverage=round(coverage, 3), gate=gate)
    if note:
        out["note"] = note
    return out


# --- Scheduled tasks ----------------------------------------------------------------------------

TASKS_PS = (
    "Get-ScheduledTask -TaskName 'HAP-*' | ForEach-Object { $i = $_ | Get-ScheduledTaskInfo; "
    "[pscustomobject]@{name=$_.TaskName; state=[string]$_.State; last_result=[int64]$i.LastTaskResult; "
    "last_run=$i.LastRunTime.ToString('o')} } | ConvertTo-Json -Compress"
)


def check_tasks(tasks_json: str | None, error: str | None = None,
                expected: list[str] = EXPECTED_TASKS, own_task: str = OWN_TASK) -> dict:
    """``tasks_json`` is ConvertTo-Json output of name/state/last_result/last_run (object or list)."""
    if tasks_json is None:
        return _result("scheduled_tasks", WARN, reason="query_failed", error=error)
    data = json.loads(tasks_json) if tasks_json.strip() else []
    tasks = {t["name"]: t for t in ([data] if isinstance(data, dict) else data)}
    out, statuses = {}, []
    for name in sorted(set(expected) | set(tasks)):
        if name == own_task:
            continue
        task = tasks.get(name)
        if task is None:
            level, info = FAIL, {"state": "missing"}
        else:
            code = int(task.get("last_result") or 0) & 0xFFFFFFFF
            info = {"state": task.get("state"), "last_result": hex(code), "last_run": task.get("last_run")}
            if task.get("state") == "Disabled":
                level = FAIL if name in expected else OK
            elif task.get("state") == "Running" or code in TASK_OK_CODES:
                level = OK
            else:
                level = WARN
        info["status"] = level
        out[name] = info
        statuses.append(level)
    return _result("scheduled_tasks", worst(statuses), tasks=out)


def query_tasks(timeout: int = 60) -> tuple[str | None, str | None]:
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", TASKS_PS],
                              capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)[:300]
    if proc.returncode != 0:
        return None, proc.stderr.strip()[:300]
    return proc.stdout, None


# --- Run / log / notify ------------------------------------------------------------------------

def run_checks(now: dt.datetime, docker_ps: Callable = run_docker_ps,
               tasks_query: Callable = query_tasks, station: str = STATION) -> dict:
    checks = [check_docker(*docker_ps())]
    checks.append(check_snapshots("weather_snapshots_task", paths.WEATHER_SNAPSHOTS, now, station))
    checks.append(check_snapshots("weather_snapshots_worker", paths.WEATHER_SNAPSHOTS_WORKER, now, station))
    checks.append(check_log_freshness("shadow_runner_log", paths.SHADOW_RUNNER_LOG,
                                      FRESHNESS_LIMITS_H["shadow_runner_log"], now))
    checks.append(check_log_freshness("hazard_jobs_log", paths.HAZARD_JOBS_LOG,
                                      FRESHNESS_LIMITS_H["hazard_jobs_log"], now))
    day, due = sensor_target_day(now)
    try:
        checks.append(check_sensor_coverage(load_day_history(station, day), day, due))
    except Exception as exc:  # a broken file must not hide the other checks
        checks.append(_result("sensor_coverage_yesterday", WARN, reason="error", error=repr(exc)[:300]))
    checks.append(check_tasks(*tasks_query()))
    status = worst(c["status"] for c in checks)
    return {"checked_at": now.isoformat(timespec="seconds"), "station": station, "status": status,
            "problems": [c["name"] for c in checks if c["status"] != OK], "checks": checks}


def exit_code(status: str) -> int:
    return SEVERITY[status]


def previous_status(log_path: Path) -> str | None:
    if not log_path.exists():
        return None
    with open(log_path, "rb") as f:
        f.seek(max(0, log_path.stat().st_size - TAIL_BYTES))
        lines = [ln for ln in f.read().decode("utf-8", errors="replace").splitlines() if ln.strip()]
    try:
        return json.loads(lines[-1]).get("status") if lines else None
    except json.JSONDecodeError:
        return None


def should_notify(status: str, previous: str | None) -> bool:
    return status == FAIL or (status == WARN and previous != WARN)


def append_log(result: dict, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def notify(result: dict) -> str:
    """Non-blocking WScript.Shell popup (closes after 30 s); never fails the run."""
    text = f"HAP health: {result['status'].upper()} - " + ", ".join(result["problems"])
    text = text.replace("'", "")
    cmd = f"(New-Object -ComObject WScript.Shell).Popup('{text}', 30, 'Hydro-Aqua-Predict health', 48) | Out-Null"
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", cmd],
                         creationflags=NO_WINDOW)
        return "shown"
    except OSError as exc:
        return f"error: {exc}"


# --- Optional Docker stale-socket recovery ------------------------------------------------------

DOCKER_DESKTOP_EXE = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe"


def docker_desktop_running() -> bool:
    try:
        proc = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Docker Desktop.exe", "/NH"],
                              capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return True  # unknown: do not touch anything
    return "Docker Desktop.exe" in proc.stdout


def fix_docker_stale_sockets(run_dir: Path, now: dt.datetime, desktop_running: Callable[[], bool] = docker_desktop_running,
                             start_desktop: Callable[[], None] | None = None) -> dict:
    """Rename (never delete) the Docker run dir and start Docker Desktop. Only when Desktop is not running."""
    if desktop_running():
        return {"action": "skipped", "reason": "docker_desktop_running"}
    if not run_dir.exists():
        return {"action": "skipped", "reason": "run_dir_missing", "run_dir": str(run_dir)}
    target = run_dir.with_name(f"{run_dir.name}.stale-{now:%Y%m%dT%H%M%SZ}")
    try:
        run_dir.rename(target)
    except OSError as exc:
        return {"action": "rename_failed", "error": str(exc)[:300]}
    start = start_desktop or (lambda: subprocess.Popen([str(DOCKER_DESKTOP_EXE)]))
    try:
        start()
    except OSError as exc:
        return {"action": "renamed", "renamed_to": str(target), "start_error": str(exc)[:300]}
    return {"action": "renamed_and_started", "renamed_to": str(target)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--station", default=STATION)
    parser.add_argument("--no-log", action="store_true", help="do not append to the health log")
    parser.add_argument("--no-notify", action="store_true", help="never show a popup")
    parser.add_argument("--fix-docker-stale-sockets", action="store_true",
                        help="on docker FAIL with Docker Desktop not running: rename %%LOCALAPPDATA%%\\Docker\\run, start Desktop")
    args = parser.parse_args(argv)

    now = dt.datetime.now(dt.timezone.utc)
    result = run_checks(now, station=args.station)
    docker = next(c for c in result["checks"] if c["name"] == "docker")
    if args.fix_docker_stale_sockets and docker.get("reason") == "docker_not_responding":
        run_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Docker" / "run"
        docker["fix"] = fix_docker_stale_sockets(run_dir, now)

    previous = previous_status(paths.HEALTH_LOG)
    if not args.no_notify and should_notify(result["status"], previous):
        result["notified"] = notify(result)
    if not args.no_log:
        append_log(result, paths.HEALTH_LOG)

    print(f"{result['checked_at']}  status={result['status'].upper()}")
    for check in result["checks"]:
        detail = {k: v for k, v in check.items() if k not in {"name", "status", "containers", "tasks"}}
        print(f"  {check['status'].upper():4s} {check['name']:26s} {json.dumps(detail, ensure_ascii=False)}")
        for key in ("containers", "tasks"):
            for name, info in (check.get(key) or {}).items():
                print(f"         {name:36s} {info if isinstance(info, str) else json.dumps(info)}")
    return exit_code(result["status"])


if __name__ == "__main__":
    sys.exit(main())
