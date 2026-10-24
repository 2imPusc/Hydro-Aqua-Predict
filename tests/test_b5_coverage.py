"""H2.1: two capture sources, union by issue hour, causal B5 origins, projection."""
import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from core import b5_coverage as b
from experiments.forecast_external_context import join_as_issued, read_snapshot_union, read_snapshots

STATION = "06M26042804"
T0 = datetime(2026, 10, 1, 0, 30, tzinfo=timezone.utc)


def _capture(issued: datetime, *, hours=range(0, 72), source=None, provenance="captured_live", location="map_station_NB1", station=STATION):
    """Records of one capture: valid hours from the issue's UTC midnight (Open-Meteo returns whole days)."""
    start = issued.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for hour in hours:
        record = {"station": station, "provider": "open_meteo", "product": "open_meteo_forecast", "issued_at": issued.isoformat(),
                  "retrieved_at": issued.isoformat(), "valid_at": (start + timedelta(hours=hour)).isoformat(),
                  "features": {"temperature_2m": 27.0 + hour / 100, "precipitation": 0.0}, "location_id": location}
        if provenance is not None:
            record["provenance_class"] = provenance
        if source is not None:
            record["capture_source"] = source
        rows.append(record)
    return rows


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def _sensor(start: datetime, minutes: int, step: int = 1) -> pd.DataFrame:
    times = pd.date_range(start, periods=minutes // step, freq=f"{step}min", tz="UTC")
    return pd.DataFrame({"fetchedAt": times, "value": 28.0})


def test_scan_captures_groups_issues_and_labels_sources(tmp_path):
    path = tmp_path / "snap.jsonl"
    _write(path, _capture(T0) + _capture(T0 + timedelta(hours=1), source=b.WORKER_SOURCE) + _capture(T0, station="OTHER"))
    path.open("a").write("\n")
    frame = b.scan_captures(path, STATION, b.PRIMARY_SOURCE)
    assert len(frame) == 2 and frame["records"].tolist() == [72, 72]
    assert frame["capture_source"].tolist() == [b.PRIMARY_SOURCE, b.WORKER_SOURCE]
    assert frame.loc[0, "valid_max"] - frame.loc[0, "valid_min"] == pd.Timedelta(hours=71)
    assert b.scan_captures(tmp_path / "missing.jsonl", STATION, b.WORKER_SOURCE).empty


def test_dedupe_primary_wins_hour_worker_fills_gap_and_same_source_kept():
    issues = pd.DataFrame({
        "station": STATION,
        "issued_at": pd.to_datetime([T0, T0 + timedelta(minutes=20), T0 + timedelta(minutes=10), T0 + timedelta(hours=1, minutes=5),
                                     T0 + timedelta(hours=2)], utc=True),
        "capture_source": [b.PRIMARY_SOURCE, b.PRIMARY_SOURCE, b.WORKER_SOURCE, b.WORKER_SOURCE, b.PRIMARY_SOURCE]})
    issues["retrieved_at"] = issues["issued_at"]
    kept = b.dedupe_issues(issues)
    assert kept["issued_at"].tolist() == [issues.issued_at[0], issues.issued_at[1], issues.issued_at[3], issues.issued_at[4]]
    assert kept["capture_source"].tolist() == [b.PRIMARY_SOURCE, b.PRIMARY_SOURCE, b.WORKER_SOURCE, b.PRIMARY_SOURCE]


def test_eligible_origins_match_join_as_issued(tmp_path):
    """Same verdict per origin as the B5 join, incl. truncated-capture fallback, age, provenance, location."""
    path = tmp_path / "snap.jsonl"
    _write(path, _capture(T0))                                                     # full 72 h
    _write(path, _capture(T0 + timedelta(hours=10), hours=range(0, 11)))          # truncated: valid only to 10:00
    _write(path, _capture(T0 + timedelta(hours=30), provenance="reconstructed_run"))
    _write(path, _capture(T0 + timedelta(hours=31), provenance=None))             # legacy row without provenance
    _write(path, _capture(T0 + timedelta(hours=32), location="elsewhere"))
    _write(path, _capture(T0 + timedelta(hours=60)))
    sensor = _sensor(T0 - timedelta(hours=2), 80 * 60, step=5)
    origins = b.sensor_origins(sensor, 60)
    captures = b.scan_captures(path, STATION, b.PRIMARY_SOURCE)
    fast = b.eligible_origins(origins, captures)
    frame = origins.copy()
    frame["station"] = STATION
    frame["location_id"] = "map_station_NB1"
    snapshots = read_snapshots(path)
    # join_as_issued also admits reconstructed_run; H2.2 evidence is captured_live only (decisions #13).
    joined = join_as_issued(frame, snapshots[snapshots["provenance_class"] != "reconstructed_run"], prefix="external")
    slow = joined[[c for c in joined if c.startswith("external_")]].notna().all(axis=1)
    assert fast.tolist() == slow.tolist()
    assert fast.any() and not fast.all()
    # the truncated 10:30 capture lacks 12:00, so an origin at 11:00 (+60 min) falls back to the 00:30 capture
    at = origins.index[(origins.issued_at >= T0 + timedelta(hours=10, minutes=30)) & (origins.issued_at <= T0 + timedelta(hours=11, minutes=30))]
    assert fast.loc[at].all()
    # > 24 h after the last usable capture (00:30 day 1 / 10:30) nothing is eligible until the 60 h capture
    gap = origins.index[(origins.issued_at > T0 + timedelta(hours=34, minutes=31)) & (origins.issued_at < T0 + timedelta(hours=60))]
    assert len(gap) and not fast.loc[gap].any()


def test_capture_coverage_counts_unique_hours():
    issued = [T0 + timedelta(hours=h) for h in range(0, 168, 2)] + [T0 + timedelta(minutes=20)]
    frame = pd.DataFrame({"issued_at": pd.to_datetime(issued, utc=True)})
    frame["retrieved_at"] = frame["issued_at"]
    now = T0 + timedelta(hours=167, minutes=20)
    result = b.capture_coverage(frame, now)
    assert result["captures_total"] == 85 and result["capture_hours_total"] == 84
    assert result["coverage_7d"] == 0.5 and result["coverage_since_start"] == 0.5


def test_project_ready_rules():
    as_of = date(2026, 10, 23)
    all_days = pd.Series({as_of - timedelta(days=k): True for k in range(63)})
    assert b.project_ready(all_days, as_of, 1.0) == as_of
    recent = pd.Series({as_of - timedelta(days=k): k < 10 for k in range(63)})
    assert b.project_ready(recent, as_of, 1.0) == as_of + timedelta(days=47)  # 57 eligible days needed in the window
    assert b.project_ready(recent, as_of, 0.5) is None
    assert b.project_ready(recent, as_of, 0.95) is not None


def test_coverage_report_worker_fills_gaps(tmp_path):
    primary, worker = tmp_path / "p.jsonl", tmp_path / "w.jsonl"
    start = datetime(2026, 9, 30, 17, 5, tzinfo=timezone.utc)  # 00:05 local, 1 Oct
    for h in range(0, 24 * 10):
        when = start + timedelta(hours=h)
        local_day = (when + timedelta(hours=7)).day
        if local_day % 2 or when.hour % 2 == 0:  # task misses odd hours on even local days...
            _write(primary, _capture(when))
        if local_day in (2, 4, 6) and when.hour % 2:  # ...the worker covers them
            _write(worker, _capture(when + timedelta(minutes=3), source=b.WORKER_SOURCE))
    sensor = _sensor(start, 24 * 10 * 60)
    now = start + timedelta(days=10, minutes=30)
    captures = {b.PRIMARY_SOURCE: b.scan_captures(primary, STATION, b.PRIMARY_SOURCE), b.WORKER_SOURCE: b.scan_captures(worker, STATION, b.WORKER_SOURCE)}
    report = b.coverage_report(captures, sensor, now, station=STATION, sensor_run="sensor-history-test")
    task, wk = report["sources"]
    assert task["source"] == b.PRIMARY_SOURCE and wk["source"] == b.WORKER_SOURCE
    assert report["combined"]["captures_total"] == task["captures_total"] + wk["captures_total"]
    assert report["combined"]["coverage_since_start"] > task["coverage_since_start"]
    assert report["origins"]["eligible_origins"] >= task["eligible_origins"]
    assert report["days"]["as_of"] == "2026-10-10" and report["days"]["eligible_days_total"] == 10
    assert report["projection"]["earliest_ready_date"] is not None
    json.dumps(report)  # plain JSON for the API


def test_read_snapshot_union_dedupes_by_issue_hour(tmp_path):
    primary, worker = tmp_path / "p.jsonl", tmp_path / "w.jsonl"
    _write(primary, _capture(T0, hours=range(0, 3)))
    _write(worker, _capture(T0 + timedelta(minutes=10), hours=range(0, 3), source=b.WORKER_SOURCE))       # same hour: dropped
    _write(worker, _capture(T0 + timedelta(hours=1, minutes=10), hours=range(0, 3), source=b.WORKER_SOURCE))  # gap hour: kept
    union = read_snapshot_union(primary, (worker,))
    assert sorted(union["capture_source"].value_counts().items()) == [(b.PRIMARY_SOURCE, 3), (b.WORKER_SOURCE, 3)]
    assert union.loc[union.capture_source == b.WORKER_SOURCE, "issued_at"].iloc[0] == pd.Timestamp(T0 + timedelta(hours=1, minutes=10))
    single = read_snapshot_union(primary)
    pd.testing.assert_frame_equal(single, read_snapshots(primary))
    assert read_snapshot_union(primary, (tmp_path / "missing.jsonl",)).shape[0] == 3


def test_weekly_summary_cli_function(tmp_path):
    from experiments.forecast_snapshot_coverage import weekly_summary
    primary, worker = tmp_path / "p.jsonl", tmp_path / "w.jsonl"
    start = datetime(2026, 10, 1, 0, 5, tzinfo=timezone.utc)
    for h in range(0, 72):
        _write(primary if h % 3 else worker, _capture(start + timedelta(hours=h), source=None if h % 3 else b.WORKER_SOURCE))
    csv = tmp_path / "sensor-history-20261004" / f"{STATION}.csv"
    csv.parent.mkdir()
    times = pd.date_range(start, periods=72 * 60, freq="1min", tz="UTC")
    pd.DataFrame({"device": STATION, "fetchedAt": times.astype(str), "Temperature": 28.0, "pH": 7.9}).to_csv(csv, index=False)
    summary = weekly_summary(csv, STATION, primary, worker, now=start + timedelta(hours=72))
    assert summary["inputs"]["worker_snapshots_present"] is True
    assert summary["combined"]["coverage_since_start"] == pytest.approx(72 / 73, abs=0.02)
    assert summary["sources"][1]["captures_total"] == 24
    assert summary["sensor_history"]["run"] == "sensor-history-20261004"
    from experiments.forecast_snapshot_coverage import coverage
    table = coverage(csv, STATION, primary, (worker,))
    assert len(table) == 12  # Temperature and pH x 6 horizons
    row = table[(table.target == "Temperature") & (table.horizon_minutes == 60)].iloc[0]
    assert row.as_issued_weather_pairs > 0
    primary_only = coverage(csv, STATION, primary)
    assert row.as_issued_weather_pairs >= primary_only[(primary_only.target == "Temperature") & (primary_only.horizon_minutes == 60)].iloc[0].as_issued_weather_pairs
