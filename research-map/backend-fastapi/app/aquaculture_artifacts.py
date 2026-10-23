"""Precomputed, map-safe aquaculture advisory artifacts.

This module intentionally produces a station-level operational overlay, not a
spatial suitability interpolation.  One sensor cannot justify colouring an
entire bay as suitable/unsafe.  The worker writes compact JSON; API requests
and the browser only read/render it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from math import pow
from pathlib import Path
from typing import Any


ARTIFACT_VERSION = "aquaculture-map-v2"
MODES = {"live", "mock"}
# Keep this contract aligned with the deterministic demo inputs below and the
# scenario selector in the frontend.
SCENARIOS = {
    "normal", "rain_wind_watch", "nh3_watch", "temperature_warning",
    "extreme_hazard", "oyster_danger_cobia_safe", "missing_sensor_data",
}


def _path(cache_dir: str, mode: str, scenario: str) -> Path:
    return Path(cache_dir) / "aquaculture" / f"{mode}-{scenario}.json"


import uuid
def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f'.tmp.{uuid.uuid4()}')
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp_path.replace(path)


def load_aquaculture_artifact(cache_dir: str, mode: str, scenario: str = "normal") -> dict | None:
    if mode not in MODES or (mode == "mock" and scenario not in SCENARIOS):
        return None
    path = _path(cache_dir, mode, scenario if mode == "mock" else "latest")
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _emerson_nh3(nh4_raw: float | None, ph: float | None, temperature_c: float | None, scale: float) -> float | None:
    if nh4_raw is None or ph is None or temperature_c is None:
        return None
    temperature_k = temperature_c + 273.15
    if temperature_k <= 0:
        return None
    pka = 0.09018 + 2729.92 / temperature_k
    return max(0.0, nh4_raw) * scale / (1 + pow(10, pka - ph))



AQUACULTURE_THRESHOLDS = {
    "cobia": {
        "name": "CÃ¡ giÃ²",
        "NH3_limit": 0.05,
        "Temp_limit": 32,
        "rain_limit": 15,
        "wind_limit": 40
    },
    "oyster": {
        "name": "HÃ u",
        "NH3_limit": 0.02,
        "Temp_limit": 30,
        "rain_limit": 8,
        "wind_limit": 30
    },
    "default": {
        "name": "Chung",
        "NH3_limit": 0.05,
        "Temp_limit": 31,
        "rain_limit": 10,
        "wind_limit": 35
    }
}

def _condition(metrics: dict, weather: dict, nh4_scale: float, species: str = "default", nh3_error: str | None = None) -> tuple[str, list[dict]]:
    thresholds = AQUACULTURE_THRESHOLDS.get(species, AQUACULTURE_THRESHOLDS["default"])
    nh3 = _emerson_nh3(metrics.get("NH4"), metrics.get("pH"), metrics.get("Temperature"), nh4_scale) if not nh3_error else None if not nh3_error else None
    drivers: list[dict] = []
    
    overall_severity = "NORMAL"
    missing_data = []
    
    # 1. NH3 evaluation
    if nh3 is not None:
        if nh3 >= thresholds["NH3_limit"] * 1.5:
            drivers.append({"metric": "NH3_derived", "value": round(nh3, 6), "unit": "mg/L", "severity": "WARNING", "source": "sensor_derived"})
            overall_severity = "WARNING"
        elif nh3 >= thresholds["NH3_limit"]:
            drivers.append({"metric": "NH3_derived", "value": round(nh3, 6), "unit": "mg/L", "severity": "WATCH", "source": "sensor_derived"})
            if overall_severity == "NORMAL": overall_severity = "WATCH"
    else:
        if nh3_error:
            drivers.append({"metric": "NH3_derived", "value": None, "unit": None, "severity": "UNKNOWN", "source": "sensor_derived", "reason_code": nh3_error})
        else:
            missing_data.append("NH3_derived")
            
    # 2. Temperature evaluation
    temp = metrics.get("Temperature")
    if temp is not None:
        if temp >= thresholds["Temp_limit"] + 2.0:
            drivers.append({"metric": "Temperature", "value": temp, "unit": "degC", "severity": "WARNING", "source": "sensor"})
            overall_severity = "WARNING"
        elif temp >= thresholds["Temp_limit"]:
            drivers.append({"metric": "Temperature", "value": temp, "unit": "degC", "severity": "WATCH", "source": "sensor"})
            if overall_severity == "NORMAL": overall_severity = "WATCH"
    else:
        missing_data.append("Temperature")
            
    # 3. Rain evaluation
    rain = weather.get("rain_6h_mm")
    if rain is not None:
        if rain >= thresholds["rain_limit"] * 2.0:
            drivers.append({"metric": "forecast_rain_6h", "value": rain, "unit": "mm", "severity": "WARNING", "source": "context_forecast"})
            overall_severity = "WARNING"
        elif rain >= thresholds["rain_limit"]:
            drivers.append({"metric": "forecast_rain_6h", "value": rain, "unit": "mm", "severity": "WATCH", "source": "context_forecast"})
            if overall_severity == "NORMAL": overall_severity = "WATCH"
    else:
        missing_data.append("forecast_rain_6h")
            
    # 4. Wind evaluation
    wind = weather.get("wind_6h_kmh")
    if wind is not None:
        if wind >= thresholds["wind_limit"] + 15.0:
            drivers.append({"metric": "forecast_max_wind_6h", "value": wind, "unit": "km/h", "severity": "WARNING", "source": "context_forecast"})
            overall_severity = "WARNING"
        elif wind >= thresholds["wind_limit"]:
            drivers.append({"metric": "forecast_max_wind_6h", "value": wind, "unit": "km/h", "severity": "WATCH", "source": "context_forecast"})
            if overall_severity == "NORMAL": overall_severity = "WATCH"
    else:
        missing_data.append("forecast_max_wind_6h")
        
    if overall_severity == "NORMAL" and missing_data:
        overall_severity = "UNKNOWN"
        for m in missing_data:
            drivers.append({"metric": m, "value": None, "unit": None, "severity": "UNKNOWN", "source": "missing"})
            
    # Always report missing data as UNKNOWN drivers so frontend can display "Dữ liệu thiếu: ..."
    if overall_severity != "NORMAL" and overall_severity != "UNKNOWN" and missing_data:
        for m in missing_data:
            drivers.append({"metric": m, "value": None, "unit": None, "severity": "UNKNOWN", "source": "missing"})
        
    return overall_severity, drivers


def _weather_from_snapshot(snapshot: dict | None, target_lat: float, target_lon: float) -> dict[str, float | None]:
    import math
    
    def distance(lon1, lat1, lon2, lat2):
        return math.hypot(lon1 - lon2, lat1 - lat2)
        
    advisory_layer = None
    for layer in (snapshot or {}).get("layers", []):
        if layer.get("layer") == "advisory_forecast":
            advisory_layer = layer
            break
            
    if not advisory_layer or not advisory_layer.get("data"):
        return {"rain_6h_mm": None, "wind_6h_kmh": None}
        
    pts_rain = []
    pts_wind = []
    for item in advisory_layer["data"]:
        lon = item.get("lon")
        lat = item.get("lat")
        if lon is None or lat is None:
            continue
        if item.get("series_complete"):
            if item.get("rain_6h_mm") is not None:
                pts_rain.append((lon, lat, float(item["rain_6h_mm"])))
            if item.get("wind_6h_kmh") is not None:
                pts_wind.append((lon, lat, float(item["wind_6h_kmh"])))
                
    def interpolate(pts):
        if not pts:
            return None
        weighted_sum = 0.0
        weight_sum = 0.0
        for lon, lat, val in pts:
            d = distance(target_lon, target_lat, lon, lat)
            if d < 1e-5:
                return val
            w = 1.0 / (d ** 2)
            weighted_sum += val * w
            weight_sum += w
        return weighted_sum / weight_sum if weight_sum > 0 else None

    return {
        "rain_6h_mm": round(interpolate(pts_rain), 2) if pts_rain else None,
        "wind_6h_kmh": round(interpolate(pts_wind), 2) if pts_wind else None,
    }


def _feature(longitude: float, latitude: float, station: str, mode: str, scenario: str, metrics: dict, weather: dict, observed_at: str | None, nh4_scale: float, species: str = "default", data_status: str = "complete", pilot_reference: dict | None = None, nh3_error: str | None = None) -> dict:
    severity, drivers = _condition(metrics, weather, nh4_scale, species, nh3_error=nh3_error)
    nh3 = _emerson_nh3(metrics.get("NH4"), metrics.get("pH"), metrics.get("Temperature"), nh4_scale) if not nh3_error else None if not nh3_error else None
    res = {
        "type": "Feature", "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": {
            "kind": "aquaculture_station_advisory", "station_serial": station,
            "mode": mode, "scenario": scenario, "severity": severity,
            "data_status": data_status,
            "pilot_reference": pilot_reference,
            "policy_version": "v1.0-research",
            "species_applied": AQUACULTURE_THRESHOLDS.get(species, AQUACULTURE_THRESHOLDS["default"])["name"],
            "observed_at": observed_at, "metrics": metrics,
            "nh3_derived_mg_l": None if nh3 is None else round(nh3, 6),
            "weather": weather, "drivers": drivers,
            "used_by_models": False, "used_by_classification": False,
            "used_by_alerts": False, "notification_eligible": False,
        },
    }
    if nh3_error:
        res["properties"]["nh3_error"] = nh3_error
    return res


def build_aquaculture_artifacts(repository: Any, cache_dir: str, station_serials: tuple[str, ...], latitude: float, longitude: float, nh4_scale: float, stale_minutes: int = 10, nh3_gap_minutes: int = 5, species: str = "cobia") -> None:
    """Worker-only build for live and deterministic mock map overlays."""
    from app.domain import station_records
    from datetime import datetime, timezone
    
    now = datetime.now(timezone.utc)
    snapshot = repository.latest()
    
    live_features = []
    
    pilot_serial = station_serials[0] if station_serials else "UNKNOWN"
    readings = repository.latest_sensor(pilot_serial)
    
    pilot_metrics = {}
    nh3_error = None
    valid_observed_ats = []
    pilot_raw_metrics = {}
    
    if readings:
        for row in readings:
            if row["metric"] not in {"NH4", "pH", "Temperature", "TSS"}:
                continue
            if row["qc_status"] == "FAIL":
                continue
            try:
                val = float(row["value"])
                import math
                if not math.isfinite(val):
                    continue
            except (ValueError, TypeError):
                continue
                
            obs_time = row["observed_at"]
            if obs_time.tzinfo is None:
                obs_time = obs_time.replace(tzinfo=timezone.utc)
            is_stale = (now - obs_time).total_seconds() > stale_minutes * 60
            pilot_raw_metrics[row["metric"]] = {
                "value": float(row["value"]),
                "unit": row["unit"],
                "qc_status": row["qc_status"],
                "observed_at": obs_time.isoformat(),
                "is_stale": is_stale
            }
            if not is_stale:
                valid_observed_ats.append(obs_time)
                
        nh4_data = pilot_raw_metrics.get("NH4")
        ph_data = pilot_raw_metrics.get("pH")
        temp_data = pilot_raw_metrics.get("Temperature")
        
        nh4_val = nh4_data["value"] if nh4_data and not nh4_data["is_stale"] else None
        ph_val = ph_data["value"] if ph_data and not ph_data["is_stale"] else None
        temp_val = temp_data["value"] if temp_data and not temp_data["is_stale"] else None
        
        nh3_error = None
        if nh4_val is not None and ph_val is not None and temp_val is not None:
            times = [datetime.fromisoformat(m["observed_at"]) for m in (nh4_data, ph_data, temp_data)]
            gap = (max(times) - min(times)).total_seconds() / 60.0
            if gap > nh3_gap_minutes:
                nh3_error = "metric_time_gap"
                
        pilot_metrics = {
            "NH4": nh4_val,
            "pH": ph_val,
            "Temperature": temp_val,
            "TSS": pilot_raw_metrics.get("TSS", {}).get("value") if not pilot_raw_metrics.get("TSS", {}).get("is_stale", True) else None
        }
        
    pilot_observed_at = max(valid_observed_ats).isoformat() if valid_observed_ats else None
    valid_count = sum(1 for m in pilot_metrics.values() if m is not None)
    if valid_count == 4:
        pilot_data_status = "complete"
    elif valid_count > 0:
        pilot_data_status = "partial"
    else:
        pilot_data_status = "missing"
        
    try:
        registry = station_records()
    except Exception:
        registry = []
        
    pilot_ref = {"source_station_serial": pilot_serial, "scope": "bay_area"}
        
    for rec in registry:
        st_lat = rec["latitude"]
        st_lon = rec["longitude"]
        station_id = rec["station"]
        
        weather = _weather_from_snapshot(snapshot, st_lat, st_lon)
        
        feature = _feature(st_lon, st_lat, station_id, "live", "latest", pilot_metrics, weather, pilot_observed_at, nh4_scale, species, data_status=pilot_data_status, pilot_reference=pilot_ref, nh3_error=nh3_error)
        feature["properties"]["raw_metrics"] = pilot_raw_metrics
        live_features.append(feature)
        
    _write(_path(cache_dir, "live", "latest"), {
        "status": "ready" if live_features else "unavailable", "artifact_version": ARTIFACT_VERSION,
        "mode": "live", "scenario": "latest", "generated_at": now.isoformat(),
        "source": {"sensor": "greenlab_api_append_only", "environment": "context_snapshot_idw_interpolated", "snapshot_id": (snapshot or {}).get("snapshot_id")},
        "disclaimer": f"Trực quan theo điểm bản đồ thật; Nội suy thời tiết cục bộ; Chia sẻ trạng thái sinh học từ trạm tham chiếu.",
        "type": "FeatureCollection", "features": live_features,
    })
    
    mock_inputs = {
        "normal": ({"NH4": 0.7, "pH": 7.9, "Temperature": 28.0, "TSS": 10.0}, {"rain_6h_mm": 0.0, "wind_6h_kmh": 12.0}, "complete"),
        "rain_wind_watch": ({"NH4": 0.8, "pH": 7.9, "Temperature": 28.5, "TSS": 25.0}, {"rain_6h_mm": 18.0, "wind_6h_kmh": 42.0}, "complete"),
        "nh3_watch": ({"NH4": 400.0, "pH": 8.5, "Temperature": 31.5, "TSS": 30.0}, {"rain_6h_mm": 1.0, "wind_6h_kmh": 15.0}, "complete"),
        "temperature_warning": ({"NH4": 0.7, "pH": 8.0, "Temperature": 34.5, "TSS": 15.0}, {"rain_6h_mm": 0.0, "wind_6h_kmh": 5.0}, "complete"),
        "extreme_hazard": ({"NH4": 95.0, "pH": 8.6, "Temperature": 35.0, "TSS": 80.0}, {"rain_6h_mm": 45.0, "wind_6h_kmh": 65.0}, "complete"),
        "oyster_danger_cobia_safe": ({"NH4": 0.5, "pH": 8.0, "Temperature": 31.0, "TSS": 12.0}, {"rain_6h_mm": 10.0, "wind_6h_kmh": 35.0}, "complete"),
        "missing_sensor_data": ({"pH": 8.0, "Temperature": 29.0}, {"rain_6h_mm": 5.0, "wind_6h_kmh": 20.0}, "partial"),
    }
    
    for scenario, (metrics_val, mock_weather, m_status) in mock_inputs.items():
        mock_features = []
        for i, rec in enumerate(registry):
            st_lat = rec["latitude"]
            st_lon = rec["longitude"]
            station_id = rec["station"]
            
            import copy
            st_metrics = copy.deepcopy(metrics_val)
            st_weather = copy.deepcopy(mock_weather)
            
            if i % 3 == 1:
                if "Temperature" in st_metrics: st_metrics["Temperature"] -= 3.0
                if "wind_6h_kmh" in st_weather: st_weather["wind_6h_kmh"] *= 0.4
                if "pH" in st_metrics: st_metrics["pH"] = 7.5
            elif i % 3 == 2:
                if "NH4" in st_metrics: st_metrics["NH4"] = 0.1
                if "Temperature" in st_metrics: st_metrics["Temperature"] = 28.0
                if "rain_6h_mm" in st_weather: st_weather["rain_6h_mm"] = 0.0
                if "wind_6h_kmh" in st_weather: st_weather["wind_6h_kmh"] = 10.0
                
            feature = _feature(st_lon, st_lat, station_id, "mock", scenario, st_metrics, st_weather, now.isoformat(), nh4_scale, species, data_status=m_status, pilot_reference=None)
            mock_features.append(feature)
            
        _write(_path(cache_dir, "mock", scenario), {
            "status": "ready", "artifact_version": ARTIFACT_VERSION, "mode": "mock", "scenario": scenario,
            "generated_at": now.isoformat(), "source": {"sensor": "deterministic_demo", "environment": "deterministic_demo"},
            "disclaimer": "MOCK DATA: chỉ dùng trình diễn kịch bản, không phải quan trắc hay dự báo thực.",
            "type": "FeatureCollection", "features": mock_features,
        })
