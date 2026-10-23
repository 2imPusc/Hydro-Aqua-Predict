"""Lightweight one-minute runner for the sensor-first shadow ledger.

Optional, opt-in hazard shadow (default OFF): set ``HAZARD_RUNNER_ENABLED=true`` and the loop in ``main``
also calls ``core.hazard_runner.run_once`` (per-station storm/wave/heat/cold/disease records into
``paths.HAZARD_SHADOW_DIR``), at most once every ``HAZARD_RUNNER_INTERVAL_MINUTES`` (default 60).
It is independent of sensor freshness and never raises into the sensor loop.  Marine inputs still need
``MARINE_ENABLED``; without it the temperature hazards are written as skip records.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.fetch import fetch_raw
from core.forecast_evaluation import latest_advisory_state, record_sensor_future, resolve_sensor_outcomes, sensor_metrics, _append_unique, STORE_DIR
from core.sensor_future import forecast_sensor_first
from core.sensor_future_long import issue_long_horizon
from core.weather import get_station_weather
from core.forecast_advisory import evaluate_forecast_advisory
from core.weather_advisory import evaluate_weather_advisory
from core.realtime_guards import assess_sensor_freshness, blocked_forecast

RISK_LOG = STORE_DIR / "risk_decisions.jsonl"
_last_hazard_run: datetime | None = None
_hazard_thread: threading.Thread | None = None


def hazard_runner_enabled() -> bool:
    return os.getenv("HAZARD_RUNNER_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def maybe_run_hazards(now: datetime | None = None) -> dict | None:
    """Opt-in hazard shadow run, throttled; returns the run summary, an error dict, or None when skipped."""
    global _last_hazard_run
    if not hazard_runner_enabled():
        return None
    now = now or datetime.now(timezone.utc)
    try:
        every = float(os.getenv("HAZARD_RUNNER_INTERVAL_MINUTES", "60"))
    except ValueError:
        every = 60.0
    if _last_hazard_run is not None and (now - _last_hazard_run).total_seconds() < every * 60:
        return None
    _last_hazard_run = now
    try:
        from core import hazard_runner
        return hazard_runner.run_once(now)
    except Exception as exc:  # the sensor loop must survive any hazard-runner failure
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}


def start_hazards_background(now: datetime | None = None) -> bool:
    """Run ``maybe_run_hazards`` in a daemon thread so a slow run (20 s – minutes) never blocks the
    sensor loop. At most one run at a time; returns True when a thread was started."""
    global _hazard_thread
    if not hazard_runner_enabled():
        return False
    if _hazard_thread is not None and _hazard_thread.is_alive():
        return False

    def _target() -> None:
        result = maybe_run_hazards(now)
        if result is not None:
            print({"hazard_runner": result}, flush=True)

    _hazard_thread = threading.Thread(target=_target, name="hazard-runner", daemon=True)
    _hazard_thread.start()
    return True

def record_risk_decision(station_serial: str, future: dict, weather_adv: dict, water_adv: dict) -> int:
    issued_at = future.get("base_timestamp", datetime.now(timezone.utc).isoformat())
    decision_id = hashlib.sha256(f"{station_serial}|{issued_at}|shadow-risk-v1".encode()).hexdigest()[:20]
    
    water_severity = water_adv.get("severity", "UNAVAILABLE")
    physical_severity = weather_adv.get("severity", "UNAVAILABLE")
    
    # NORMAL only if both are NORMAL or at least one is NORMAL and other is UNAVAILABLE... wait. 
    # "NORMAL chỉ khi mọi nguồn bắt buộc cho kết luận đó đủ và còn hạn." -> both must be present to say NORMAL.
    # If one is WARNING, it stays WARNING.
    severities = {"WARNING": 3, "WATCH": 2, "NORMAL": 1, "UNAVAILABLE": 0}
    
    water_score = severities.get(water_severity, 0)
    phys_score = severities.get(physical_severity, 0)
    
    if water_score == 3 or phys_score == 3:
        combined = "WARNING"
    elif water_score == 2 or phys_score == 2:
        combined = "WATCH"
    elif water_score == 1 and phys_score == 1:
        combined = "NORMAL"
    else:
        combined = "UNAVAILABLE"
        
    drivers = water_adv.get("drivers", []) + weather_adv.get("drivers", [])
    
    data_quality = "complete"
    if water_score == 0 and phys_score == 0:
        data_quality = "missing"
    elif water_score == 0 or phys_score == 0:
        data_quality = "partial"
        
    record = {
        "schema_version": "shadow-risk-v1",
        "decision_id": decision_id,
        "station_id": station_serial,
        "issued_at": issued_at,
        "valid_window": "24h",
        "model_versions": "pilot_policy_v1",
        "data_quality": data_quality,
        "water_risk": water_severity,
        "physical_risk": physical_severity,
        "combined_severity": combined,
        "drivers": drivers,
        "block_reasons": [],
        "notification_sent": False
    }
    
    return int(_append_unique(RISK_LOG, record, decision_id))

def run_long_horizon(raw, station_serial: str, freshness: dict, weather: dict, now=None) -> dict:
    """3/6/12 h shadow set (H1.5); its failure never blocks the 15/30/60 path."""
    try:
        return issue_long_horizon(raw, station_serial, freshness=freshness, weather=weather, now=now)
    except Exception as exc:  # logged in the runner output, no ledger record
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}", "issued": 0}

def run_once(station_serial: str, *, replay: bool = False, now=None) -> dict:
    raw = fetch_raw(station_serial)
    if raw.empty:
        return {"status": "no_data", "issued_records": 0, "resolved_outcomes": 0}
        
    freshness = assess_sensor_freshness(raw, station_serial, now=now, replay=replay)
    if freshness["status"] in {"stale", "missing"}:
        return {
            "status": "stale_sensor_data",
            "reason": freshness["reason"],
            "freshness": freshness,
            "issued_records": 0,
            "resolved_outcomes": 0,
        }
        
    if replay:
        return {
            "status": "replay_only",
            "reason": "replay_mode",
            "freshness": freshness,
            "future": blocked_forecast("replay_mode"),
            "issued_records": 0,
            "resolved_outcomes": 0,
        }
        
    weather = get_station_weather(station_serial)
    weather_adv = evaluate_weather_advisory(weather, now=now)
    long_horizon = run_long_horizon(raw, station_serial, freshness, weather, now)
    
    future = forecast_sensor_first(raw, station_serial)
    water_adv = evaluate_forecast_advisory(future, latest_advisory_state(station_serial))
    
    decisions_written = record_risk_decision(station_serial, future, weather_adv, water_adv)
    
    return {
        "status": future.get("status"), 
        "issued_records": record_sensor_future(station_serial, future, weather, water_adv) + decisions_written, 
        "resolved_outcomes": resolve_sensor_outcomes(raw), 
        "metrics": sensor_metrics(), 
        "future": future, 
        "water_advisory": water_adv,
        "weather_advisory": weather_adv,
        "long_horizon": long_horizon,
    }

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--station", default="06M26042804")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--replay", action="store_true", help="inspect historical data without issuing forecasts")
    parser.add_argument("--summary", action="store_true", help="Read-only print of risk decisions")
    args = parser.parse_args()
    
    if args.summary:
        if RISK_LOG.exists():
            with open(RISK_LOG, "r") as f:
                lines = [json.loads(l) for l in f if l.strip()]
                print(f"Risk decisions: {len(lines)}")
                if lines:
                    last = lines[-1]
                    print(f"Latest status: {last['combined_severity']} at {last['issued_at']}")
        else:
            print("No risk decisions recorded.")
        return

    while True:
        result = run_once(args.station, replay=args.replay)
        printable = {key: value for key, value in result.items() if key not in {"future", "metrics", "long_horizon"}}
        if "long_horizon" in result:
            printable["long_horizon"] = {key: value for key, value in result["long_horizon"].items() if key != "skips"}
        print(printable)
        if args.once:
            hazards = maybe_run_hazards()  # synchronous: a daemon thread would die with the process
            if hazards is not None:
                print({"hazard_runner": hazards})
        else:
            start_hazards_background()
        if args.once:
            return
        time.sleep(max(10, args.interval_seconds))

if __name__ == "__main__":
    main()
