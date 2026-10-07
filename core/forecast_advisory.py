"""Inferred-DO forecast risk policy for the Hai Phong operational advisory."""
from __future__ import annotations


_RANK = {"NORMAL": 0, "WATCH": 1, "WARNING": 2, "CRITICAL_ADVISORY": 3}


def _point_risk(point: dict) -> dict:
    horizon = int(point["horizon_minutes"])
    sensors, inferred = point.get("sensors", {}), point.get("inferred", {})
    drivers: list[dict] = []
    do = inferred.get("DO")
    if do is not None:
        do = float(do)
        status = "critical_inferred_forecast" if do <= 3 else "warning_inferred_forecast" if do <= 4 else "watch_inferred_forecast" if do <= 5 else None
        if status:
            drivers.append({"metric": "DO", "value": do, "status": status, "source": "inferred_forecast"})
    temp = sensors.get("Temperature")
    if temp is not None and float(temp) >= 31:
        drivers.append({"metric": "Temperature", "value": float(temp), "status": "warning_forecast" if float(temp) >= 33 else "watch_forecast", "source": "sensor_forecast"})
    nh3 = sensors.get("NH3")
    if nh3 is not None and float(nh3) >= .05:
        drivers.append({"metric": "NH3", "value": float(nh3), "status": "warning_forecast" if float(nh3) >= .10 else "watch_forecast", "source": "derived_forecast"})
    severity = "CRITICAL_ADVISORY" if any(d["status"] == "critical_inferred_forecast" for d in drivers) else "WARNING" if any("warning" in d["status"] for d in drivers) else "WATCH" if drivers else "NORMAL"
    diagnostics = point.get("inference_diagnostics", {}).get("DO", {})
    accepted_do = do is not None and point.get("contextual_status") == "ready" and diagnostics.get("status", "accepted") == "accepted"
    # Contextual DO is inferred from other sensors in the current pilot.  It
    # can explain a warning, but it is never promoted to a high-confidence
    # operational signal without a direct DO observation and calibrated model.
    direct_do = bool(point.get("direct_do", False))
    model_confidence = diagnostics.get("confidence", point.get("inference_confidence", "limited"))
    confidence = "high" if accepted_do and direct_do and model_confidence == "high" else "limited"
    return {"horizon_minutes": horizon, "timestamp": point.get("timestamp"), "severity": severity, "drivers": drivers,
            "inputs": {"Temperature": temp, "NH3": nh3, "DO_inferred": do, "Salinity_inferred": inferred.get("Salinity")},
            "inference_status": point.get("contextual_status"), "sensor_sources": point.get("sensor_sources", {}),
            "evaluatable": bool(point.get("evaluatable", True)),
            "interpolation_method": point.get("interpolation_method"),
            "confidence": confidence, "notification_eligible": False, "used_by_emergency": False}


def evaluate_forecast_advisory(sensor_future: dict, previous: dict | None = None) -> dict:
    """Assess forecast horizons; inferred DO may notify, never creates Emergency."""
    future = sensor_future or {}
    if future.get("status") != "ready":
        return {"severity": "BLOCKED", "state": "BLOCKED", "source": "sensor_future_inferred_do", "reason": future.get("reason", "forecast_unavailable"), "timeline": [], "notification_eligible": False, "used_by_emergency": False, "drivers": []}
    timeline = [_point_risk(point) for point in future.get("timeline", [])]
    # The minute-by-minute values before the model endpoint make the dashboard
    # readable, but they are display interpolation, not independently validated
    # forecasts.  Operational advisory decisions therefore use only evaluatable
    # model horizons (currently +15 minutes).
    evaluatable_timeline = [point for point in timeline if point["evaluatable"]]
    do_points = [point for point in evaluatable_timeline if point["inputs"]["DO_inferred"] is not None]
    low_do_points = [point for point in do_points if point["inputs"]["DO_inferred"] <= 4]
    worst = max(evaluatable_timeline, key=lambda point: _RANK[point["severity"]], default=None)
    low_do = min((point["inputs"]["DO_inferred"] for point in do_points), default=None)
    confidence = "high" if low_do_points and all(point["confidence"] == "high" for point in low_do_points) else "limited"
    has_contextual_do = any(point.get("inference_status") == "ready" for point in low_do_points)
    prior_count = int((previous or {}).get("do_risk_count", 0))
    do_risk_count = prior_count + 1 if low_do is not None and low_do <= 4 else 0
    compound = any((point["inputs"]["Temperature"] or 0) >= 31 or (point["inputs"]["NH3"] or 0) >= .05 for point in low_do_points)
    # Pilot policy: advisory is visible and evaluated, but never sends a
    # notification.  This remains false even when a future direct-DO policy
    # would otherwise satisfy persistence/compound-stress rules.
    notification_eligible = False
    notification_reason = "shadow_only_policy"
    severity = worst["severity"] if worst else "NORMAL"
    if low_do is not None and low_do <= 3:
        severity = "WARNING"
    if low_do is not None and has_contextual_do:
        if low_do <= 3 and do_risk_count >= 2 and compound:
            severity, notification_reason = "CRITICAL_ADVISORY", "shadow_only_inferred_do_le_3_persistent_with_compound_stress"
        elif low_do <= 4 and (do_risk_count >= 2 or compound):
            severity, notification_reason = "WARNING", "shadow_only_inferred_do_le_4_persistent_or_compound_stress"
        elif low_do <= 4:
            severity = "WATCH"
    for point in timeline:
        point["notification_eligible"] = notification_eligible and point in low_do_points
    risks = [point for point in evaluatable_timeline if point["severity"] != "NORMAL"]
    earliest = min(risks, key=lambda point: point["horizon_minutes"], default=None)
    drivers = [{**driver, "horizon_minutes": point["horizon_minutes"]} for point in evaluatable_timeline for driver in point["drivers"]]
    return {"severity": severity, "state": "OPEN" if risks else "RESOLVED", "source": "sensor_future_inferred_do",
            "earliest_horizon_minutes": earliest["horizon_minutes"] if earliest else None, "drivers": drivers, "timeline": timeline,
            "confidence": confidence, "do_risk_count": do_risk_count, "compound_stress": compound,
            "notification_eligible": notification_eligible, "notification_reason": notification_reason,
            "used_by_emergency": False,
            "recommended_actions": (["Kiem tra thuc dia va chuan bi suc khi/dieu chinh van hanh truoc moc du bao.", "Xac minh DO noi suy bang dau hieu vat nuoi va dieu kien long nuoi."] if risks else ["Tiep tuc theo doi theo chu ky sensor."]),
            "disclaimer": "DO la noi suy tu sensor; co the kich hoat warning van hanh khi du dieu kien xac nhan, nhung khong tao Emergency."}
