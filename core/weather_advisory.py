"""Weather-operational context, deliberately separate from water predictions."""
from __future__ import annotations

from datetime import datetime, timezone
import pandas as pd

def _number_at(values: list | None, index: int) -> float | None:
    if not values or index >= len(values) or values[index] is None:
        return None
    try:
        return float(values[index])
    except (TypeError, ValueError):
        return None

def evaluate_weather_advisory(weather: dict | None, now: datetime | None = None) -> dict:
    weather = weather or {}
    
    # R2: Weather stale phải giữ trạng thái stale
    status = weather.get("status")
    if status not in {"ready", "stale"}:
        return {
            "status": "unavailable", "reason": weather.get("reason", "weather_unavailable"),
            "used_by_models": False, "used_by_classification": False,
            "used_by_alerts": False, "notification_eligible": False,
        }
        
    hourly = weather.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return {
            "status": "unavailable", "reason": "weather_hourly_missing",
            "used_by_models": False, "used_by_classification": False,
            "used_by_alerts": False, "notification_eligible": False,
        }
        
    provider_timezone = weather.get("timezone", "Asia/Ho_Chi_Minh")
    timestamp = pd.Timestamp(now or datetime.now(timezone.utc))
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    timestamp = timestamp.tz_convert("UTC")
    
    parsed = pd.to_datetime(times, errors="coerce")
    if getattr(parsed, "tz", None) is None:
        parsed = parsed.tz_localize(provider_timezone).tz_convert("UTC")
    else:
        parsed = parsed.tz_convert("UTC")

    rows = []
    for index, valid_at in enumerate(parsed):
        if pd.isna(valid_at) or valid_at < timestamp.floor("h"):
            continue
        rows.append({
            "valid_at": valid_at,
            "precipitation_mm": _number_at(hourly.get("precipitation"), index),
            "wind_speed": _number_at(hourly.get("wind_speed_10m"), index),
            "wind_direction": _number_at(hourly.get("wind_direction_10m"), index),
        })
        
    if not rows:
        return {
            "status": "unavailable", "reason": "no_future_weather_hours",
            "used_by_models": False, "used_by_classification": False,
            "used_by_alerts": False, "notification_eligible": False,
        }

    # R2: Tính weather advisory theo khoảng thời gian thực, đủ 3/6/12/24 giờ liên tiếp
    # Thiếu giờ hay giá trị bắt buộc => window partial/unavailable
    df_rows = pd.DataFrame(rows)
    df_rows = df_rows.set_index("valid_at").sort_index()
    
    def window_summary(hours: int) -> dict:
        end_time = timestamp.floor("h") + pd.Timedelta(hours=hours-1)
        # We need exact hours rows from current hour to end_time
        expected_times = pd.date_range(timestamp.floor("h"), periods=hours, freq="h", tz="UTC")
        
        # Check if we have all required hours
        available = df_rows.reindex(expected_times)
        
        if available["precipitation_mm"].isna().any() or available["wind_speed"].isna().any():
            return {
                "hours": hours,
                "status": "partial" if available["precipitation_mm"].notna().any() else "unavailable",
                "rain_sum_mm": None,
                "max_wind": None
            }
            
        rain = available["precipitation_mm"].sum()
        wind = available["wind_speed"].max()
        return {
            "hours": hours,
            "status": "complete",
            "rain_sum_mm": round(float(rain), 2),
            "max_wind": round(float(wind), 2),
        }

    windows = {f"next_{hours}h": window_summary(hours) for hours in (3, 6, 12, 24)}
    
    # Dashboard-only pilot thresholds.
    w6 = windows["next_6h"]
    drivers = []
    
    if w6["status"] != "complete":
        severity = "UNAVAILABLE"
    else:
        rain_6h = w6["rain_sum_mm"]
        wind_6h = w6["max_wind"]
        severity = "WATCH" if rain_6h >= 10 or wind_6h >= 35 else "NORMAL"
        
        if rain_6h >= 10:
            drivers.append({"metric": "forecast_rain_6h", "value": rain_6h, "unit": "mm", "status": "watch"})
        if wind_6h >= 35:
            drivers.append({"metric": "forecast_max_wind_6h", "value": wind_6h, "unit": weather.get("hourly_units", {}).get("wind_speed_10m", "km/h"), "status": "watch"})
            
    return {
        "status": status, # Keep stale if stale
        "severity": severity, 
        "provider": weather.get("provider"),
        "retrieved_at": weather.get("retrieved_at"), 
        "location": weather.get("location"),
        "windows": windows, 
        "next_hours": [{"valid_at": r["valid_at"].isoformat(), "precipitation_mm": r["precipitation_mm"], "wind_speed": r["wind_speed"]} for r in rows[:6]], 
        "drivers": drivers,
        "recommended_actions": (["Theo dõi điều kiện lồng bè, cập nhật đo nước sau đợt mưa/gió."] if drivers else ["Theo dõi theo chu kỳ sensor thông thường."]),
        "used_by_models": False, "used_by_classification": False,
        "used_by_alerts": False, "notification_eligible": False,
        "disclaimer": "Weather advisory chỉ là ngữ cảnh vận hành; không điều chỉnh dự báo.",
    }
