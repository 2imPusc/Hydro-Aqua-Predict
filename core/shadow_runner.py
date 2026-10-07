"""Lightweight one-minute runner for the sensor-first shadow ledger."""
from __future__ import annotations

import argparse
import sys
import time
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.fetch import fetch_raw
from core.forecast_evaluation import latest_advisory_state, record_sensor_future, resolve_sensor_outcomes, sensor_metrics, _append_unique, STORE_DIR
from core.sensor_future import forecast_sensor_first
from core.weather import get_station_weather
from core.forecast_advisory import evaluate_forecast_advisory
from core.weather_advisory import evaluate_weather_advisory
from core.realtime_guards import assess_sensor_freshness, blocked_forecast

RISK_LOG = STORE_DIR / "risk_decisions.jsonl"

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
        "weather_advisory": weather_adv
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
        print({key: value for key, value in result.items() if key not in {"future", "metrics"}})
        if args.once:
            return
        time.sleep(max(10, args.interval_seconds))

if __name__ == "__main__":
    main()
