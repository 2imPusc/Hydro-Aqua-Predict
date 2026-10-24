"""Coverage of the as-issued weather capture for the B5 benchmark (roadmap H2.1).

Two append-only capture sources write the same record format (one line per
issue x valid hour, ``experiments/forecast_snapshot_store.py``):

* ``hap_weather_snapshot_task`` - the hourly Windows scheduled task;
* ``research_map_worker`` - the research-map worker (``app/weather_capture.py``).

This module answers, from those files and the sensor history export:

* how many issues each source (and their union) captured, 7-day and
  since-start hourly coverage;
* how many sensor origins B5 could use (``join_as_issued`` rule: a
  ``captured_live`` snapshot retrieved at or before the origin, at most 24 h
  old, that contains the valid hour);
* how many local days are eligible and when a 63-day window reaches the H2.2
  requirement at the current rate.

Pure stdlib + pandas so the research-map API can import it too; it never
writes anything and never reads ``core.config``.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

PRIMARY_SOURCE = "hap_weather_snapshot_task"
WORKER_SOURCE = "research_map_worker"
# Union rule: within one station x issue hour keep a single issue, the highest
# priority source first (then the earliest issue). The union therefore only
# fills hours the scheduled task missed.
SOURCE_PRIORITY = (PRIMARY_SOURCE, WORKER_SOURCE)
SOURCE_LABELS = {PRIMARY_SOURCE: "Task Windows mỗi giờ", WORKER_SOURCE: "Worker research-map"}
ACCEPTED_PROVENANCE = ("captured_live",)  # H2.2 evidence; reconstructed_run is never mixed in (decisions #13)
LOCATION_ID = "map_station_NB1"
LOCAL_TZ = "Asia/Ho_Chi_Minh"

MAX_AGE = pd.Timedelta(hours=24)  # experiments.forecast_external_context.join_as_issued default
PAIR_TOLERANCE = pd.Timedelta(minutes=2)  # experiments.forecast_sensor_v2.TOLERANCE
REFERENCE_TARGET = "Temperature"
REFERENCE_HORIZON_MINUTES = 60
COVERAGE_WINDOW_HOURS = 7 * 24

# 14-day warm-up + 5 x 7-day rolling folds + 14-day lockbox (docs/guide/22).
REQUIRED_DAYS = 63
MIN_WINDOW_FRACTION = 0.9  # a 63-day window may miss at most 6 days
DAILY_ORIGIN_FRACTION = 0.9  # a day counts when >= 90 % of a normal day's origins have weather
RECENT_DAYS = 14
PROJECTION_HORIZON_DAYS = 730

_FIELDS = ("station", "issued_at", "retrieved_at", "valid_at", "provenance_class", "location_id", "capture_source")
_STRING_PAIR = re.compile(rb'"([a-z_]+)":\s*"([^"]*)"')


def _record_fields(line: bytes) -> dict | None:
    pairs = dict(_STRING_PAIR.findall(line))  # flat string fields; the record's nested dicts hold none of _FIELDS
    found = {name: (value.decode() if (value := pairs.get(name.encode())) is not None else None) for name in _FIELDS}
    if found["station"] and found["retrieved_at"] and found["valid_at"]:
        return found
    try:  # non-canonical formatting: fall back to a real parse
        doc = json.loads(line)
    except ValueError:
        return None
    if not isinstance(doc, dict):
        return None
    return {name: (str(doc[name]) if doc.get(name) is not None else None) for name in _FIELDS}


def scan_captures(path: Path, station: str, default_source: str) -> pd.DataFrame:
    """One row per captured issue of ``station``: issued/retrieved time, valid range, provenance, source.

    Records without ``capture_source`` get ``default_source`` (the file's role).
    A missing file gives an empty frame.
    """
    columns = ["station", "issued_at", "retrieved_at", "valid_min", "valid_max", "provenance_class", "location_id", "capture_source", "records"]
    path = Path(path)
    if not path.is_file():
        return pd.DataFrame(columns=columns)
    rows: list[tuple] = []
    needle = station.encode()
    with path.open("rb") as handle:
        for line in handle:
            if needle not in line:
                continue
            fields = _record_fields(line)
            if fields is None or fields["station"] != station:
                continue
            rows.append((fields["issued_at"] or fields["retrieved_at"], fields["retrieved_at"], fields["valid_at"],
                         fields["provenance_class"], fields["location_id"], fields["capture_source"] or default_source))
    if not rows:
        return pd.DataFrame(columns=columns)
    records = pd.DataFrame(rows, columns=["issued_at", "retrieved_at", "valid_at", "provenance_class", "location_id", "capture_source"])
    for column in ("issued_at", "retrieved_at", "valid_at"):
        records[column] = pd.to_datetime(records[column], utc=True, format="ISO8601")
    frame = records.groupby(["issued_at", "capture_source"], as_index=False, dropna=False).agg(
        retrieved_at=("retrieved_at", "max"), valid_min=("valid_at", "min"), valid_max=("valid_at", "max"),
        provenance_class=("provenance_class", "first"), location_id=("location_id", "first"), records=("valid_at", "size"))
    frame["station"] = station
    return frame[columns].sort_values("retrieved_at").reset_index(drop=True)


def dedupe_issues(issues: pd.DataFrame, priority: tuple[str, ...] = SOURCE_PRIORITY) -> pd.DataFrame:
    """Union rule: per station x issue hour keep only the issues of the highest-priority source present.

    Within one source nothing is dropped, so a union whose secondary sources are
    empty equals the primary source exactly. ``issues`` needs ``station``,
    ``issued_at`` (UTC) and ``capture_source``.
    """
    if issues.empty:
        return issues.copy()
    frame = issues.copy()
    frame["_hour"] = frame["issued_at"].dt.floor("h")
    rank = {source: index for index, source in enumerate(priority)}
    frame["_rank"] = frame["capture_source"].map(lambda value: rank.get(value, len(rank)))
    best = frame.groupby(["station", "_hour"])["_rank"].transform("min")
    frame = frame[frame["_rank"] == best]
    return frame.drop(columns=["_hour", "_rank"]).sort_values("retrieved_at").reset_index(drop=True)


def capture_coverage(captures: pd.DataFrame, now: datetime) -> dict:
    """Unique capture hours: last 7 days (168 h ending with the current hour) and since the first capture."""
    if captures.empty:
        return {"captures_total": 0, "capture_hours_total": 0, "first_capture_at": None, "last_capture_at": None,
                "captures_7d": 0, "coverage_7d": None, "coverage_since_start": None, "hours_since_start": 0}
    now_ts = pd.Timestamp(now).tz_convert("UTC") if pd.Timestamp(now).tzinfo else pd.Timestamp(now, tz="UTC")
    current_hour = now_ts.floor("h")
    hours = pd.Index(captures["retrieved_at"].dt.floor("h").unique())
    hours = hours[hours <= current_hour]
    if hours.empty:
        return capture_coverage(captures.iloc[0:0], now)
    first_hour = hours.min()
    window_start = current_hour - pd.Timedelta(hours=COVERAGE_WINDOW_HOURS - 1)
    in_window = int((hours >= window_start).sum())
    expected_window = int((current_hour - max(window_start, first_hour)) / pd.Timedelta(hours=1)) + 1
    since_start = int((current_hour - first_hour) / pd.Timedelta(hours=1)) + 1
    return {
        "captures_total": int(len(captures)),
        "capture_hours_total": int(len(hours)),
        "first_capture_at": captures["retrieved_at"].min().isoformat(),
        "last_capture_at": captures["retrieved_at"].max().isoformat(),
        "captures_7d": in_window,
        "coverage_7d": round(min(1.0, in_window / max(1, expected_window)), 4),
        "coverage_since_start": round(min(1.0, len(hours) / max(1, since_start)), 4),
        "hours_since_start": since_start,
    }


def sensor_origins(sensor: pd.DataFrame, horizon_minutes: int = REFERENCE_HORIZON_MINUTES) -> pd.DataFrame:
    """B5 origins: sensor times with a value and an actual within 2 minutes of ``origin + horizon``.

    ``sensor`` has ``fetchedAt`` (UTC) and ``value`` (already range-filtered by the caller).
    """
    clean = sensor[["fetchedAt", "value"]].dropna().sort_values("fetchedAt").drop_duplicates("fetchedAt")
    if clean.empty:
        return pd.DataFrame(columns=["issued_at", "valid_at"])
    issued = pd.DataFrame({"issued_at": pd.to_datetime(clean["fetchedAt"], utc=True).reset_index(drop=True)})
    issued["valid_at"] = issued["issued_at"] + pd.Timedelta(minutes=horizon_minutes)
    actual = pd.DataFrame({"actual_at": issued["issued_at"]})
    paired = pd.merge_asof(issued.sort_values("valid_at"), actual, left_on="valid_at", right_on="actual_at",
                           direction="nearest", tolerance=PAIR_TOLERANCE)
    return paired.dropna(subset=["actual_at"]).sort_values("issued_at")[["issued_at", "valid_at"]].reset_index(drop=True)


def eligible_origins(origins: pd.DataFrame, captures: pd.DataFrame, *, location_id: str | None = LOCATION_ID,
                     max_age: pd.Timedelta = MAX_AGE) -> pd.Series:
    """Boolean per origin: some causal capture (retrieved <= origin, age <= max_age) holds the valid hour.

    Same rule as ``join_as_issued``: only ``captured_live`` rows (and the B5
    location id) count, and when the newest causal capture lacks the valid hour
    (a truncated payload) an older one within ``max_age`` is used. Feature
    values themselves are not inspected.
    """
    if origins.empty:
        return pd.Series([], dtype=bool)
    usable = captures[captures["provenance_class"].isin(ACCEPTED_PROVENANCE)] if not captures.empty else captures
    if location_id is not None and not usable.empty:
        usable = usable[usable["location_id"] == location_id]
    result = pd.Series(False, index=origins.index)
    if usable.empty:
        return result
    right = usable[["retrieved_at", "valid_min", "valid_max"]].sort_values("retrieved_at").reset_index(drop=True)
    pending = origins[["issued_at", "valid_at"]].rename_axis("_origin").reset_index()
    pending["bucket"] = pending["valid_at"].dt.floor("h")
    pending["oldest"] = pending["issued_at"] - max_age
    pending["cutoff"] = pending["issued_at"]
    for _ in range(len(right)):  # each round steps one capture further back for the misses
        joined = pd.merge_asof(pending.sort_values("cutoff"), right, left_on="cutoff", right_on="retrieved_at",
                               direction="backward", allow_exact_matches=True)
        causal = joined["retrieved_at"].notna() & (joined["retrieved_at"] >= joined["oldest"])
        hit = causal & (joined["valid_min"] <= joined["bucket"]) & (joined["bucket"] <= joined["valid_max"])
        result.loc[joined.loc[hit, "_origin"].to_numpy()] = True
        retry = joined[causal & ~hit]
        if retry.empty:
            break
        pending = retry[["_origin", "issued_at", "valid_at", "bucket", "oldest"]].copy()
        pending["cutoff"] = retry["retrieved_at"] - pd.Timedelta(microseconds=1)
    return result


def _local_dates(times: pd.Series) -> pd.Series:
    return times.dt.tz_convert(LOCAL_TZ).dt.date


def last_complete_day(sensor_end: pd.Timestamp, now: datetime) -> date:
    """Last local day fully inside both the sensor export and the clock."""
    end = min(pd.Timestamp(sensor_end), pd.Timestamp(now)) + pd.Timedelta(minutes=1)
    return (end.tz_convert(LOCAL_TZ) - pd.Timedelta(days=1)).date()


def daily_eligibility(origins: pd.DataFrame, eligible: pd.Series, first_day: date, as_of: date) -> pd.DataFrame:
    """Per local day: sensor origins, origins with weather, and whether the day counts for B5."""
    days = pd.Index(pd.date_range(first_day, as_of, freq="D").date, name="date") if first_day <= as_of else pd.Index([], name="date")
    if origins.empty:
        frame = pd.DataFrame(index=days, data={"origins": 0, "eligible_origins": 0})
        normal = 0.0
    else:
        dates = _local_dates(origins["issued_at"])
        per_day = pd.DataFrame({"date": dates.to_numpy(), "eligible": eligible.to_numpy()}).groupby("date")["eligible"].agg(["size", "sum"])
        normal = float(per_day["size"].median())
        frame = per_day.rename(columns={"size": "origins", "sum": "eligible_origins"}).reindex(days, fill_value=0)
    threshold = DAILY_ORIGIN_FRACTION * normal
    frame["eligible"] = (frame["eligible_origins"] >= threshold) & (frame["eligible_origins"] > 0)
    frame.attrs["min_daily_origins"] = math.ceil(threshold)
    return frame.astype({"origins": int, "eligible_origins": int})


def project_ready(eligible_days: pd.Series, as_of: date, rate: float) -> date | None:
    """First day D >= as_of whose 63-day window [D-62, D] reaches the required eligible days.

    Days after ``as_of`` count ``rate`` each (expected value). ``None`` when the
    requirement is not reached within the projection horizon.
    """
    need = math.ceil(MIN_WINDOW_FRACTION * REQUIRED_DAYS)
    known = {day: bool(value) for day, value in eligible_days.items()}
    for offset in range(PROJECTION_HORIZON_DAYS + 1):
        end = as_of + timedelta(days=offset)
        window = [end - timedelta(days=k) for k in range(REQUIRED_DAYS)]
        past = sum(1 for day in window if day <= as_of and known.get(day, False))
        future = sum(1 for day in window if day > as_of)
        if past + rate * future >= need - 1e-9:
            return end
    return None


def _streak(eligible_days: pd.Series) -> int:
    count = 0
    for value in reversed(list(eligible_days.to_numpy())):
        if not value:
            break
        count += 1
    return count


def coverage_report(captures_by_source: dict[str, pd.DataFrame], sensor: pd.DataFrame, now: datetime, *,
                    station: str, sensor_run: str | None = None, location_id: str | None = LOCATION_ID,
                    horizon_minutes: int = REFERENCE_HORIZON_MINUTES, target: str = REFERENCE_TARGET) -> dict:
    """Full H2.1 summary: per-source + combined capture coverage, B5 origins, eligible days, projection."""
    sources = []
    frames = []
    origins = sensor_origins(sensor, horizon_minutes)
    for source, captures in captures_by_source.items():
        frames.append(captures)
        sources.append({"source": source, "label": SOURCE_LABELS.get(source, source), **capture_coverage(captures, now),
                        "eligible_origins": int(eligible_origins(origins, captures, location_id=location_id).sum()) if not captures.empty else 0})
    present = [frame for frame in frames if not frame.empty]
    combined = dedupe_issues(pd.concat(present, ignore_index=True)) if present else pd.DataFrame(columns=frames[0].columns if frames else [])
    combined_coverage = capture_coverage(combined, now)
    eligible = eligible_origins(origins, combined, location_id=location_id) if not combined.empty else pd.Series(False, index=origins.index)
    observed = sensor[["fetchedAt", "value"]].dropna()["fetchedAt"]
    sensor_end = pd.to_datetime(observed, utc=True).max() if not origins.empty else None
    report = {
        "station": station,
        "generated_at": pd.Timestamp(now).isoformat(),
        "sources": sources,
        "combined": {**combined_coverage, "eligible_origins": int(eligible.sum()),
                     "union_rule": "one issue per station x issue hour; scheduled task wins, worker fills missed hours"},
        "origins": {"target": target, "horizon_minutes": horizon_minutes, "sensor_origins": int(len(origins)),
                    "eligible_origins": int(eligible.sum()), "max_age_hours": MAX_AGE.total_seconds() / 3600,
                    "accepted_provenance": list(ACCEPTED_PROVENANCE), "location_id": location_id},
        "sensor_history": {"run": sensor_run, "start": None if origins.empty else pd.to_datetime(observed, utc=True).min().isoformat(),
                           "end": None if sensor_end is None else sensor_end.isoformat()},
    }
    if combined.empty or sensor_end is None:
        report["days"] = {"as_of": None, "eligible_days_total": 0, "window_eligible_days": 0, "current_streak_days": 0,
                          "recent_day_rate": None, "min_daily_origins": None, "daily": []}
        report["projection"] = _projection(None, None, None, reason="no_captures" if combined.empty else "no_sensor_history")
        return report
    as_of = last_complete_day(sensor_end, now)
    usable = combined[combined["provenance_class"].isin(ACCEPTED_PROVENANCE)]
    first_day = (usable if not usable.empty else combined)["retrieved_at"].min().tz_convert(LOCAL_TZ).date()
    daily = daily_eligibility(origins, eligible, first_day, as_of)
    flags = daily["eligible"]
    recent = flags.iloc[-RECENT_DAYS:]
    rate = float(recent.mean()) if len(recent) else 0.0
    window = flags[flags.index > as_of - timedelta(days=REQUIRED_DAYS)]
    report["days"] = {
        "as_of": as_of.isoformat(), "first_day": first_day.isoformat(), "eligible_days_total": int(flags.sum()),
        "window_eligible_days": int(window.sum()), "current_streak_days": _streak(flags),
        "recent_day_rate": round(rate, 4), "recent_days": int(len(recent)),
        "min_daily_origins": daily.attrs.get("min_daily_origins"),
        "daily": [{"date": day.isoformat(), "origins": int(row.origins), "eligible_origins": int(row.eligible_origins), "eligible": bool(row.eligible)}
                  for day, row in daily.iloc[-REQUIRED_DAYS:].iterrows()],
    }
    report["projection"] = _projection(flags, as_of, rate)
    return report


def _projection(flags: pd.Series | None, as_of: date | None, rate: float | None, *, reason: str | None = None) -> dict:
    need = math.ceil(MIN_WINDOW_FRACTION * REQUIRED_DAYS)
    base = {"required_days": REQUIRED_DAYS, "min_eligible_days": need,
            "rule": f"cửa sổ {REQUIRED_DAYS} ngày có ≥ {need} ngày đạt; ngày đạt khi ≥ {int(DAILY_ORIGIN_FRACTION * 100)} % origin của một ngày bình thường có bản tin nhân quả",
            "ready_now": False, "projected_ready_date": None, "earliest_ready_date": None, "reason": reason}
    if flags is None or as_of is None:
        return base
    earliest = project_ready(flags, as_of, 1.0)
    projected = project_ready(flags, as_of, rate or 0.0)
    ready_now = earliest == as_of
    why = "rate_below_requirement" if projected is None and not ready_now else None
    return {**base, "ready_now": ready_now, "projected_ready_date": None if projected is None else projected.isoformat(),
            "earliest_ready_date": None if earliest is None else earliest.isoformat(), "reason": why}


def latest_sensor_history(experiments_dir: Path, station: str) -> Path | None:
    """Newest ``sensor-history-<YYYYMMDD>/<station>.csv`` export (scripts/export_sensor_history.py)."""
    candidates = sorted(Path(experiments_dir).glob(f"sensor-history-*/{station}.csv"))
    return candidates[-1] if candidates else None


def load_sensor_values(path: Path, station: str, target: str = REFERENCE_TARGET) -> pd.DataFrame:
    """Light reader for the sensor-history export: ``fetchedAt`` (UTC) + ``value`` of ``target``."""
    frame = pd.read_csv(path, usecols=lambda column: column in {"device", "fetchedAt", target})
    if "device" in frame:
        frame = frame[frame["device"].astype(str) == str(station)]
    frame["fetchedAt"] = pd.to_datetime(frame["fetchedAt"], utc=True, errors="coerce", format="ISO8601")
    values = pd.to_numeric(frame[target], errors="coerce") if target in frame else pd.Series(float("nan"), index=frame.index)
    return pd.DataFrame({"fetchedAt": frame["fetchedAt"], "value": values}).dropna()
