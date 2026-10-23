import re

with open("app/aquaculture_artifacts.py", "r", encoding="utf-8") as f:
    content = f.read()

parts = content.split("def build_aquaculture_artifacts(")
prefix = parts[0]

new_func = """def build_aquaculture_artifacts(repository: Any, cache_dir: str, station_serials: tuple[str, ...], latitude: float, longitude: float, nh4_scale: float, stale_minutes: int = 10, nh3_gap_minutes: int = 5, species: str = "cobia") -> None:
    \"\"\"Worker-only build for live and deterministic mock map overlays.\"\"\"
    from app.domain import station_records
    from datetime import datetime, timezone
    
    now = datetime.now(timezone.utc)
    snapshot = repository.latest()
    
    live_features = []
    
    pilot_serial = station_serials[0] if station_serials else "UNKNOWN"
    readings = repository.latest_sensor(pilot_serial)
    
    pilot_metrics = {}
    valid_observed_ats = []
    pilot_raw_metrics = {}
    
    if readings:
        for row in readings:
            if row["metric"] not in {"NH4", "pH", "Temperature", "TSS"}:
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
        
        if nh4_val is not None and ph_val is not None and temp_val is not None:
            times = [datetime.fromisoformat(m["observed_at"]) for m in (nh4_data, ph_data, temp_data)]
            gap = (max(times) - min(times)).total_seconds() / 60.0
            if gap > nh3_gap_minutes:
                nh4_val, ph_val, temp_val = None, None, None
                
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
        
        feature = _feature(st_lon, st_lat, station_id, "live", "latest", pilot_metrics, weather, pilot_observed_at, nh4_scale, species, data_status=pilot_data_status, pilot_reference=pilot_ref)
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
"""

with open("app/aquaculture_artifacts.py", "w", encoding="utf-8") as f:
    f.write(prefix + new_func)

