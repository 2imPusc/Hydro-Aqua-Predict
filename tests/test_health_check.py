import datetime as dt
import json
import os

import pandas as pd
import pytest

from core import paths
from scripts import health_check as hc

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 4, 3, 0, tzinfo=UTC)  # 10:00 local
ALL_UP = "\n".join(f"{name}\tUp 10 hours" for name in hc.DOCKER_CONTAINERS) + "\npostgres_db\tUp 10 hours (healthy)\n"


# --- docker ---

def test_docker_all_up_is_ok_and_ignores_extra_containers():
    assert hc.check_docker(ALL_UP)["status"] == hc.OK


def test_docker_not_responding_is_fail():
    out = hc.check_docker(None, "error during connect")
    assert out["status"] == hc.FAIL and out["reason"] == "docker_not_responding"


def test_docker_missing_or_exited_container_is_fail():
    text = ALL_UP.replace("research-map-worker-1\tUp 10 hours", "research-map-worker-1\tExited (1) 3 days ago")
    out = hc.check_docker(text)
    assert out["status"] == hc.FAIL
    assert out["containers"]["research-map-worker-1"].startswith("Exited")
    assert hc.check_docker("research-map-api-1\tUp 1 hour\n")["status"] == hc.FAIL


def test_docker_unhealthy_is_warn():
    text = ALL_UP.replace("research-map-api-1\tUp 10 hours", "research-map-api-1\tUp 2 hours (unhealthy)")
    assert hc.check_docker(text)["status"] == hc.WARN


# --- log freshness ---

def _write(path, text, mtime=None):
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime.timestamp(), mtime.timestamp()))
    return path


def test_shadow_log_uses_last_line_timestamp(tmp_path):
    log = _write(tmp_path / "shadow.log", "2026-11-04T02:00:00+00:00 {'status': 'ready'}\n"
                                          "2026-11-04T02:50:00+00:00 {'status': 'ready'}\n")
    out = hc.check_log_freshness("shadow_runner_log", log, 20 / 60, NOW)
    assert out["status"] == hc.OK and out["source"] == "last_line" and out["age_hours"] == pytest.approx(0.17, abs=0.01)
    out = hc.check_log_freshness("shadow_runner_log", log, 20 / 60, NOW + dt.timedelta(minutes=30))
    assert out["status"] == hc.FAIL


def test_hazard_log_bracket_format(tmp_path):
    log = _write(tmp_path / "hazard.log", '[2026-11-04T00:41:20.1741674Z] job=hazards exit=0 {"status": "ok"}\n')
    assert hc.check_log_freshness("hazard_jobs_log", log, 2.0, NOW)["status"] == hc.FAIL  # 2.3 h old
    log = _write(tmp_path / "hazard.log", '[2026-11-04T01:41:20.1741674Z] job=hazards exit=0 {"status": "ok"}\n')
    assert hc.check_log_freshness("hazard_jobs_log", log, 2.0, NOW)["status"] == hc.OK


def test_log_without_timestamp_falls_back_to_mtime(tmp_path):
    log = _write(tmp_path / "x.log", "no stamp here\n", mtime=NOW - dt.timedelta(minutes=5))
    out = hc.check_log_freshness("x", log, 1.0, NOW)
    assert out["source"] == "mtime" and out["status"] == hc.OK
    _write(log, "no stamp here\n", mtime=NOW - dt.timedelta(hours=3))
    assert hc.check_log_freshness("x", log, 1.0, NOW)["status"] == hc.FAIL


def test_missing_log_is_fail(tmp_path):
    assert hc.check_log_freshness("x", tmp_path / "nope.log", 1.0, NOW)["status"] == hc.FAIL


# --- snapshots ---

def _snapshots(path, hours):
    with open(path, "w", encoding="utf-8") as f:
        for h in hours:
            t = NOW - dt.timedelta(hours=h)
            f.write(json.dumps({"station": hc.STATION, "retrieved_at": t.isoformat()}) + "\n")
    return path


def test_snapshots_full_week_is_ok(tmp_path):
    path = _snapshots(tmp_path / "s.jsonl", range(0, 7 * 24))
    out = hc.check_snapshots("weather_snapshots_task", path, NOW)
    assert out["status"] == hc.OK and out["coverage_7d"] == 1.0


def test_snapshots_low_coverage_is_warn(tmp_path):
    hours = [h for h in range(0, 7 * 24) if not 24 <= h < 96]  # 3-day gap, like 31/10-03/11
    out = hc.check_snapshots("weather_snapshots_worker", _snapshots(tmp_path / "s.jsonl", hours), NOW)
    assert out["status"] == hc.WARN and out["coverage_7d"] < 0.9


def test_snapshots_stale_is_fail_and_missing_is_fail(tmp_path):
    path = _snapshots(tmp_path / "s.jsonl", range(3, 7 * 24))
    assert hc.check_snapshots("t", path, NOW)["status"] == hc.FAIL
    assert hc.check_snapshots("t", tmp_path / "none.jsonl", NOW)["status"] == hc.FAIL


# --- sensor coverage ---

def _minutes(day_local: str, n: int) -> pd.DataFrame:
    times = pd.date_range(day_local, periods=n, freq="min", tz=hc.LOCAL_TZ).tz_convert("UTC")
    return pd.DataFrame({"device": hc.STATION, "fetchedAt": times, "COD": 20.0, "pH": 8.0})


def test_sensor_target_day_and_due_hour():
    assert hc.sensor_target_day(NOW) == (dt.date(2026, 11, 3), True)
    early = dt.datetime(2026, 11, 3, 20, 0, tzinfo=UTC)  # 03:00 local on 11-04
    assert hc.sensor_target_day(early) == (dt.date(2026, 11, 3), False)


def test_sensor_coverage_ok_warn_and_not_due():
    day = dt.date(2026, 11, 3)
    assert hc.check_sensor_coverage(_minutes("2026-11-03", 1400), day, True)["status"] == hc.OK
    low = hc.check_sensor_coverage(_minutes("2026-11-03", 600), day, True)
    assert low["status"] == hc.WARN and low["coverage"] == pytest.approx(600 / 1440, abs=1e-3)
    early = hc.check_sensor_coverage(_minutes("2026-11-03", 600), day, False)
    assert early["status"] == hc.OK and early["note"] == "collector_not_due_yet"
    empty = hc.check_sensor_coverage(pd.DataFrame(columns=["device", "fetchedAt", "COD"]), day, True)
    assert empty["status"] == hc.WARN and empty["minutes"] == 0


def test_load_day_history_picks_covering_interval_files_and_live_cache(tmp_path):
    intervals, live = tmp_path / "intervals", tmp_path / "live-cache"
    intervals.mkdir()
    (live / hc.STATION).mkdir(parents=True)

    def export(name, day, n):
        stamps = pd.date_range(day, periods=n, freq="min").strftime("%Y-%m-%d %H:%M")
        pd.DataFrame({"Date": stamps, "DeviceSerialNumber": hc.STATION, "SensorType": "COD", "Value": 20.0,
                      "Unit": "mg/L", "Status": "Good"}).to_csv(intervals / name, index=False)

    export(f"{hc.STATION}_HAIPHONG_20261102_to_20261103.csv", "2026-11-02", 10)
    export(f"{hc.STATION}_HAIPHONG_20261103_to_20261104.csv", "2026-11-03", 100)
    export(f"{hc.STATION}_HAIPHONG_20261104_to_20261105.csv", "2026-11-04", 10)
    (live / hc.STATION / "20261103.jsonl").write_text(
        json.dumps({"device": hc.STATION, "fetchedAt": "2026-11-03T05:00:00+00:00", "COD": 21.0}) + "\n", encoding="utf-8")
    frame = hc.load_day_history(hc.STATION, dt.date(2026, 11, 3), intervals, live)
    local_days = set(frame["fetchedAt"].dt.tz_convert(hc.LOCAL_TZ).dt.date)
    assert local_days == {dt.date(2026, 11, 3)}
    assert len(frame) == 101


# --- scheduled tasks ---

def _tasks(**overrides):
    rows = [{"name": n, "state": "Ready", "last_result": 0, "last_run": "x"} for n in hc.EXPECTED_TASKS]
    for row in rows:
        row.update(overrides.get(row["name"], {}))
    return json.dumps(rows)


def test_tasks_all_ready_ok_and_running_shadow_runner_refused_code_ok():
    payload = _tasks(**{"HAP-ShadowRunner": {"state": "Running", "last_result": 2147946720}})
    assert hc.check_tasks(payload)["status"] == hc.OK
    # Same IgnoreNew code as a signed int while not running is still fine
    payload = _tasks(**{"HAP-ShadowRunner": {"state": "Ready", "last_result": -2147020576}})
    assert hc.check_tasks(payload)["status"] == hc.OK


def test_tasks_failed_result_is_warn_disabled_or_missing_is_fail():
    out = hc.check_tasks(_tasks(**{"HAP-HazardRunner": {"last_result": 1}}))
    assert out["status"] == hc.WARN and out["tasks"]["HAP-HazardRunner"]["last_result"] == "0x1"
    assert hc.check_tasks(_tasks(**{"HAP-ECMWFStorms": {"state": "Disabled"}}))["status"] == hc.FAIL
    rows = json.loads(_tasks())[1:]
    assert hc.check_tasks(json.dumps(rows))["status"] == hc.FAIL


def test_tasks_ignore_own_task_and_accept_single_object():
    rows = json.loads(_tasks()) + [{"name": hc.OWN_TASK, "state": "Ready", "last_result": 1}]
    out = hc.check_tasks(json.dumps(rows))
    assert out["status"] == hc.OK and hc.OWN_TASK not in out["tasks"]
    single = json.dumps({"name": "HAP-ShadowRunner", "state": "Running", "last_result": 0})
    assert hc.check_tasks(single, expected=["HAP-ShadowRunner"])["status"] == hc.OK
    assert hc.check_tasks(None, "boom")["status"] == hc.WARN


# --- aggregation, log, notify ---

def test_run_checks_aggregates_worst_and_exit_code(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "WEATHER_SNAPSHOTS", _snapshots(tmp_path / "t.jsonl", range(0, 7 * 24)))
    monkeypatch.setattr(paths, "WEATHER_SNAPSHOTS_WORKER", _snapshots(tmp_path / "w.jsonl", range(0, 7 * 24, 2)))
    monkeypatch.setattr(paths, "SHADOW_RUNNER_LOG", _write(tmp_path / "s.log", f"{NOW.isoformat()} ok\n"))
    monkeypatch.setattr(paths, "HAZARD_JOBS_LOG", _write(tmp_path / "h.log", f"[{NOW.isoformat()}] job=hazards\n"))
    monkeypatch.setattr(hc, "load_day_history", lambda station, day: _minutes("2026-11-03", 1440))
    result = hc.run_checks(NOW, docker_ps=lambda: (ALL_UP, None), tasks_query=lambda: (_tasks(), None))
    assert result["status"] == hc.WARN and result["problems"] == ["weather_snapshots_worker"]
    assert hc.exit_code(result["status"]) == 1

    result = hc.run_checks(NOW, docker_ps=lambda: (None, "timeout"), tasks_query=lambda: (_tasks(), None))
    assert result["status"] == hc.FAIL and hc.exit_code(result["status"]) == 2


def test_append_log_and_previous_status(tmp_path):
    log = tmp_path / "logs" / "health.log"
    assert hc.previous_status(log) is None
    hc.append_log({"status": "warn"}, log)
    hc.append_log({"status": "ok"}, log)
    assert log.read_text(encoding="utf-8").count("\n") == 2
    assert hc.previous_status(log) == "ok"


def test_should_notify_only_on_fail_or_new_warn():
    assert hc.should_notify(hc.FAIL, hc.FAIL)
    assert hc.should_notify(hc.WARN, hc.OK)
    assert hc.should_notify(hc.WARN, None)
    assert not hc.should_notify(hc.WARN, hc.WARN)
    assert not hc.should_notify(hc.OK, hc.FAIL)


# --- docker stale-socket fix ---

def test_fix_docker_renames_never_deletes_and_starts(tmp_path):
    run_dir = tmp_path / "Docker" / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "dockerInference").write_text("stale", encoding="utf-8")
    started = []
    out = hc.fix_docker_stale_sockets(run_dir, NOW, desktop_running=lambda: False, start_desktop=lambda: started.append(1))
    assert out["action"] == "renamed_and_started" and started == [1]
    assert not run_dir.exists()
    renamed = tmp_path / "Docker" / "run.stale-20261104T030000Z"
    assert (renamed / "dockerInference").read_text(encoding="utf-8") == "stale"


def test_fix_docker_skips_when_desktop_running(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    out = hc.fix_docker_stale_sockets(run_dir, NOW, desktop_running=lambda: True, start_desktop=lambda: 1 / 0)
    assert out["action"] == "skipped" and run_dir.exists()
