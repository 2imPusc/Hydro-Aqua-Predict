import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from core.fetch import fetch_raw
from core.classify import classify_station
from core.spatial_impute import predict_virtual_stations
from core.forecast import forecast
from core.alerts import evaluate_aquaculture_risk
from core.contextual_models import predict_haiphong_contextual
from core.model_alerts import evaluate_inferred_do_alert
from core.weather import get_station_environment, get_station_weather
from core.weather_advisory import evaluate_weather_advisory
from core.sensor_future import forecast_sensor_first
from core.forecast_evaluation import record_sensor_future, resolve_sensor_outcomes, sensor_metrics
from core.forecast_advisory import evaluate_forecast_advisory
from core.realtime_guards import assess_sensor_freshness, blocked_forecast
from hap_shared.classification import _classify_by_scoring


def _score_virtual_stations(anchor_imputed: dict, species: str) -> dict:
    """Project anchor parameters to historical NB locations with provenance."""
    virtual_stations = {}
    for station_id, station_data in predict_virtual_stations(anchor_imputed).items():
        values = station_data["values"]
        available = [column for column, value in values.items() if not pd.isna(value)]
        try:
            wqi = _classify_by_scoring(pd.DataFrame([values]), available, species).iloc[0]
            station_data["wqi"] = {
                "score": float(wqi["suitability_score"]) * 100,
                "label": wqi["suitability_name"],
            }
        except Exception:
            station_data["wqi"] = {"score": 0, "label": "Unknown"}
        virtual_stations[station_id] = station_data
    return virtual_stations


def _full_parameters(classification: dict) -> dict:
    params = classification["params"]
    return {**params.get("defaulted", {}), **params.get("imputed", {}), **params.get("measured", {})}


def _station_future(sensor_future: dict, station_serial: str, region: str, species: str) -> dict:
    """Create per-station future values; virtual stations are spatial projections."""
    output = {station_serial: []}
    if sensor_future.get("status") != "ready":
        return output
    for point in sensor_future.get("timeline", []):
        try:
            anchor = classify_station(
                station_serial=station_serial,
                measured=point["sensors"],
                species=species,
                date=point["timestamp"],
                region=region,
            )
        except Exception:
            continue
        anchor_values = _full_parameters(anchor)
        common = {
            "timestamp": point["timestamp"], "horizon_minutes": point["horizon_minutes"],
            "source": "sensor_first_forecast", "values": anchor_values,
            "wqi": {"score": float(anchor["score"]) * 100, "label": anchor["label"]},
        }
        output[station_serial].append(common)
        if region == "haiphong":
            for virtual_id, virtual in _score_virtual_stations(anchor["params"]["imputed"], species).items():
                output.setdefault(virtual_id, []).append({
                    "timestamp": point["timestamp"], "horizon_minutes": point["horizon_minutes"],
                    "source": "anchor_sensor_forecast_then_spatial_projection",
                    "values": virtual["values"], "wqi": virtual["wqi"],
                })
    return output


def run_pipeline(
    station_serial: str,
    region: str = "haiphong",
    species: str = "cobia",
    history_points: int = 10,
    forecast_granularity: str = "hour",
    forecast_horizon: int = 24,
    previous_alert: dict = None,
    previous_inferred_do_alert: dict = None,
    previous_forecast_advisory: dict = None,
    include_legacy_forecast: bool = False,
    replay: bool = False,
    now=None,
):
    """Run the realtime pipeline and return a payload for the demo UI.

    The historical legacy forecast is intentionally opt-in: preparing its
    feature frame replays the complete raw history and is too expensive for a
    dashboard refresh.  The sensor-first forecast remains part of every run.
    """
    started_at = time.perf_counter()
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] KICH HOAT QUET SENSOR TRAM: {station_serial}")

    try:
        df_raw = fetch_raw(station_serial)
    except Exception as exc:
        print(f"  Loi khi lay du lieu: {exc}")
        return {"status": "error", "message": f"Loi lay du lieu: {exc}"}
    fetch_seconds = time.perf_counter() - started_at

    data_warning = df_raw.attrs.get("data_warning")
    data_source = df_raw.attrs.get("data_source", "unknown")
    freshness = assess_sensor_freshness(df_raw, station_serial, now=now, replay=replay)

    if df_raw.empty:
        print("  Khong co du lieu nao tra ve tu nguon du lieu.")
        return {"status": "error", "message": "Khong co du lieu tra ve tu database."}

    if freshness["status"] in {"stale", "missing", "replay"}:
        latest_row = df_raw.sort_values("fetchedAt").iloc[-1]
        measured_params = {
            param: float(latest_row[param])
            for param in ["pH", "Temperature", "TSS", "NH4", "NH3", "COD"]
            if param in latest_row and not pd.isna(latest_row[param])
        }
        replay_only = freshness["status"] == "replay"
        block_reason = "replay_mode_no_issuance" if replay_only else (freshness["reason"] or "sensor_history_unavailable")
        # Weather remains useful as display-only operational context even when
        # stale sensor data blocks every water-quality forecast and alert.
        weather = get_station_weather(station_serial)
        environment = get_station_environment(station_serial, weather=weather)
        weather_advisory = evaluate_weather_advisory(weather, now=now)
        return {
            "status": "replay_only" if replay_only else "degraded",
            "reason": block_reason,
            "station": station_serial,
            "region": region,
            "timestamp": latest_row["fetchedAt"].isoformat(),
            "data_source": data_source,
            "warning": data_warning,
            "freshness": freshness,
            "measured_params": measured_params,
            "anchor_classification": None,
            "virtual_stations": {},
            "forecast": blocked_forecast(block_reason, freshness),
            "aquaculture_alert": {"severity": "BLOCKED", "reason": block_reason, "notification_eligible": False},
            "contextual_models": {"status": "blocked", "reason": block_reason, "predictions": {}},
            "inferred_do_alert": {"severity": "BLOCKED", "reason": block_reason, "notification_eligible": False, "used_by_emergency": False},
            "weather": weather,
            "environment": environment,
            "weather_advisory": weather_advisory,
            "sensor_future": blocked_forecast(block_reason, freshness),
            "station_future": {station_serial: []},
            "forecast_advisory": {"severity": "BLOCKED", "state": "BLOCKED", "reason": block_reason, "notification_eligible": False, "used_by_emergency": False},
            "forecast_evaluation": {"issued_records": 0, "resolved_outcomes": 0, "metrics": []},
            "history": [],
            "sensor_chart_history": [],
        }

    recent_df = df_raw.tail(history_points)
    historical_records = []

    for _, latest_row in recent_df.iterrows():
        date_str = latest_row["fetchedAt"].strftime("%Y-%m-%dT%H:%M:%S%z")

        measured_params = {}
        for param in ["pH", "Temperature", "TSS", "NH4", "NH3", "COD"]:
            if param in latest_row and not pd.isna(latest_row[param]):
                measured_params[param] = float(latest_row[param])

        try:
            result = classify_station(
                station_serial=station_serial,
                measured=measured_params,
                species=species,
                date=date_str,
                region=region,
            )
        except Exception:
            continue

        anchor_imputed = result["params"]["imputed"]
        virtual_stations = _score_virtual_stations(anchor_imputed, species) if region == "haiphong" else {}

        historical_records.append(
            {
                "timestamp": date_str,
                "measured_params": measured_params,
                "anchor_classification": result,
                "virtual_stations": virtual_stations if region == "haiphong" else {},
            }
        )

    if not historical_records:
        return {"status": "error", "message": "Khong the xu ly du lieu."}

    latest_record = historical_records[-1]
    history_seconds = time.perf_counter() - started_at - fetch_seconds
    chart_columns = ["fetchedAt", "Temperature", "pH", "NH4", "NH3", "TSS"]
    chart_history = []
    for _, row in df_raw.tail(120).iterrows():
        chart_history.append({
            column: row["fetchedAt"].isoformat() if column == "fetchedAt" else (None if column not in row or pd.isna(row[column]) else float(row[column]))
            for column in chart_columns
        })

    legacy_forecast_seconds = 0.0
    forecast_result = {
        "status": "deferred",
        "reason": "run_on_demand",
        "granularity": forecast_granularity,
        "horizon": forecast_horizon,
        "timeline": [],
        "early_warnings": [],
    }
    if include_legacy_forecast:
        print(f"  Dang chay du bao legacy ({forecast_granularity}, horizon={forecast_horizon}) bang mo hinh XGBoost pretrained...")
        legacy_started_at = time.perf_counter()
        forecast_result = forecast(
            df_raw=df_raw,
            station_serial=station_serial,
            granularity=forecast_granularity,
            current_time_str=latest_record["timestamp"],
            species=species,
            horizon=forecast_horizon,
        )
        legacy_forecast_seconds = time.perf_counter() - legacy_started_at
    shadow_started_at = time.perf_counter()
    aquaculture_alert = evaluate_aquaculture_risk(
        df_raw.tail(max(history_points, 20)), species=species, previous_alert=previous_alert
    )
    contextual_models = predict_haiphong_contextual(latest_record["measured_params"], latest_record["timestamp"]) if region == "haiphong" else {"status": "not_applicable", "predictions": {}}
    inferred_do_alert = evaluate_inferred_do_alert(contextual_models, latest_record["measured_params"], previous_inferred_do_alert)
    weather = get_station_weather(station_serial)
    environment = get_station_environment(station_serial, weather=weather)
    weather_advisory = evaluate_weather_advisory(weather, now=now)
    sensor_future = forecast_sensor_first(df_raw, station_serial) if region == "haiphong" else {"status": "not_applicable", "timeline": []}
    station_future = _station_future(sensor_future, station_serial, region, species)
    forecast_advisory = evaluate_forecast_advisory(sensor_future, previous_forecast_advisory) if region == "haiphong" else {"severity": "BLOCKED", "state": "BLOCKED"}
    evaluation = {"issued_records": record_sensor_future(station_serial, sensor_future, weather, forecast_advisory), "resolved_outcomes": resolve_sensor_outcomes(df_raw), "metrics": sensor_metrics()} if region == "haiphong" else {"issued_records": 0, "resolved_outcomes": 0, "metrics": []}
    shadow_seconds = time.perf_counter() - shadow_started_at

    payload = {
        "status": "success",
        "station": station_serial,
        "region": region,
        "timestamp": latest_record["timestamp"],
        "data_source": data_source,
        "warning": data_warning,
        "freshness": freshness,
        "measured_params": latest_record["measured_params"],
        "anchor_classification": latest_record["anchor_classification"],
        "virtual_stations": latest_record["virtual_stations"],
        "forecast": forecast_result,
        "aquaculture_alert": aquaculture_alert,
        "contextual_models": contextual_models,
        "inferred_do_alert": inferred_do_alert,
        "weather": weather,
        "environment": environment,
        "weather_advisory": weather_advisory,
        "sensor_future": sensor_future,
        "station_future": station_future,
        "forecast_advisory": forecast_advisory,
        "forecast_evaluation": evaluation,
        "processing_timing_seconds": {"fetch": round(fetch_seconds, 3), "history_and_spatial": round(history_seconds, 3), "legacy_forecast": round(legacy_forecast_seconds, 3), "shadow_and_ledger": round(shadow_seconds, 3), "total": round(time.perf_counter() - started_at, 3)},
        "history": historical_records,
        "sensor_chart_history": chart_history,
    }

    print("  HOAN TAT XU LY! KET QUA WQI (TRAM GOC):")
    print(f"     Nhan nuoi trong: {latest_record['anchor_classification']['label']}")
    print(f"     Diem so (Score): {latest_record['anchor_classification']['score']}/100")
    print("-" * 60)
    return payload


if __name__ == "__main__":
    print("=== KHOI DONG HE THONG REAL-TIME GREENLAB PIPELINE ===")
    print("Mo phong chu ky quet du lieu moi 3 phut (dry-run)...\n")

    test_stations = [{"serial": "06M26042804", "region": "haiphong"}]

    try:
        for cycle in range(1, 3):
            print(f"BAT DAU CHU KY #{cycle}")
            for station in test_stations:
                run_pipeline(station_serial=station["serial"], region=station["region"])

            if cycle < 2:
                print("\nDang cho chu ky tiep theo (mo phong: doi 5 giay)...\n")
                time.sleep(5)
    except KeyboardInterrupt:
        print("\nDa dung he thong theo yeu cau.")
