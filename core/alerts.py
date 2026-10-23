"""Safety-first aquaculture alerts for the realtime demo.

The alert score is intentionally independent from suitability/WQI.  It is a
decision-support signal, not a mortality prediction.  Emergency alerts require
valid *direct* sensor evidence; imputed and forecast values can only create an
early warning.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from core.quality import is_in_range
from core.sensor_health import assess_sensor_health


# Provisional operational profile. Values must be reviewed with the farm and
# calibrated against local DO measurements before any notification integration.
COBIA_PROFILE: Dict[str, Any] = {
    "version": "cobia-v1-provisional",
    "metrics": {
        "DO": {"watch": 5.0, "warning": 4.0, "emergency": 3.0, "drop_15m": -0.8},
        "Temperature": {"watch": 31.0, "warning": 33.0, "emergency": 35.0},
        "NH3": {"watch": 0.05, "warning": 0.10, "emergency": 0.20},
    },
    "minimum_samples": 3,
}

_SEVERITIES = ((75, "EMERGENCY"), (50, "WARNING"), (25, "WATCH"), (0, "NORMAL"))


def _severity(score: int) -> str:
    return next(name for threshold, name in _SEVERITIES if score >= threshold)


def _as_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _metric_risk(metric: str, value: float | None, profile: Dict[str, Any]) -> tuple[int, str | None]:
    if value is None:
        return 0, None
    limits = profile["metrics"][metric]
    if metric == "DO":
        if value <= limits["emergency"]:
            return 85, "critical"
        if value <= limits["warning"]:
            return 60, "warning"
        if value <= limits["watch"]:
            return 30, "watch"
    else:
        if value >= limits["emergency"]:
            return 85, "critical"
        if value >= limits["warning"]:
            return 60, "warning"
        if value >= limits["watch"]:
            return 30, "watch"
    return 0, None


def _recommendations(severity: str, drivers: List[Dict[str, Any]]) -> List[str]:
    if severity == "NORMAL":
        return ["Tiếp tục theo dõi theo chu kỳ sensor."]
    actions = ["Kiểm tra thực địa và đo đối chứng các chỉ số đang bất thường."]
    if any(item["metric"] == "DO" for item in drivers):
        actions.append("Kiểm tra hệ thống sục khí, dòng chảy và điều kiện lồng nuôi.")
    if severity in {"WARNING", "EMERGENCY"}:
        actions.append("Thông báo người phụ trách nuôi và ghi nhận hành động xử lý.")
    return actions


def evaluate_aquaculture_risk(
    history_df: pd.DataFrame,
    species: str = "cobia",
    profile: Dict[str, Any] | None = None,
    previous_alert: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Evaluate recent direct sensor history and return an explainable alert.

    ``history_df`` must contain ``fetchedAt`` plus any monitored metrics.  DO is
    optional because the current hardware does not provide it.  If it is absent,
    the engine explicitly reports that emergency DO alerts are unavailable.
    """
    if species != "cobia":
        raise ValueError(f"Chưa có alert profile cho loài: {species}")
    profile = profile or COBIA_PROFILE
    if history_df.empty:
        return {
            "profile_version": profile["version"], "risk_score": 0, "severity": "NORMAL",
            "state": "NO_DATA", "confidence": "none", "drivers": [],
            "sensor_health": {"status": "missing", "missing_metrics": ["history"]},
            "recommended_actions": ["Kiểm tra kết nối và dữ liệu sensor."],
        }

    df = history_df.copy()
    if "fetchedAt" in df.columns:
        df["fetchedAt"] = pd.to_datetime(df["fetchedAt"], utc=True)
        df = df.sort_values("fetchedAt")
    latest = df.iloc[-1]
    sensor_health = assess_sensor_health(df)
    drivers: List[Dict[str, Any]] = []
    scores: List[int] = []
    missing_metrics: List[str] = []

    for metric in ("Temperature", "NH3", "DO"):
        if metric not in df.columns:
            if metric != "DO":
                missing_metrics.append(metric)
            continue
        value = _as_float(latest[metric])
        if value is None:
            missing_metrics.append(metric)
            continue
        health = sensor_health["metrics"].get(metric, {})
        if health.get("status") in {"invalid", "suspect"}:
            # Keep driver states in the public ``<state>_sensor`` vocabulary;
            # the sensor-health module itself retains ``invalid/suspect``.
            drivers.append({"metric": metric, "value": value, "source": "sensor", "status": health["status"] + "_sensor", "flags": health.get("flags", [])})
            continue
        # NH3 is derived from direct NH4/pH/temperature readings, so it can
        # support a warning but remains labelled as derived evidence.
        source = "derived_sensor" if metric == "NH3" else "sensor"
        valid = is_in_range(metric, value)
        if not valid:
            drivers.append({"metric": metric, "value": value, "source": source, "status": "invalid_sensor"})
            continue
        risk, status = _metric_risk(metric, value, profile)
        if risk:
            scores.append(risk)
            drivers.append({"metric": metric, "value": value, "source": source, "status": status, "risk": risk})

    # Rate-of-change is only meaningful with direct DO sensor data.  The last
    # 15 minutes are used when timestamps are available; otherwise it is skipped.
    if "DO" in df.columns and "fetchedAt" in df.columns:
        now = df["fetchedAt"].iloc[-1]
        earlier = df[df["fetchedAt"] <= now - pd.Timedelta(minutes=15)]
        if not earlier.empty:
            old = _as_float(earlier.iloc[-1]["DO"])
            current = _as_float(latest["DO"])
            if old is not None and current is not None:
                delta = current - old
                if delta <= profile["metrics"]["DO"]["drop_15m"]:
                    scores.append(70)
                    drivers.append({"metric": "DO_drop_15m", "value": round(delta, 3), "source": "sensor", "status": "rapid_decline", "risk": 70})

    driver_metrics = {driver["metric"] for driver in drivers}
    if "DO" in driver_metrics and "Temperature" in driver_metrics:
        scores.append(75)
        drivers.append({"metric": "DO+Temperature", "value": None, "source": "sensor", "status": "combined_stress", "risk": 75})

    risk_score = max(scores, default=0)
    severity = _severity(risk_score)
    latest_do = _as_float(latest.get("DO"))
    do_health = sensor_health["metrics"].get("DO", {})
    has_direct_do = latest_do is not None and is_in_range("DO", latest_do) and do_health.get("status") == "valid"
    # Safety gate: an emergency must be evidenced by a direct DO observation.
    if severity == "EMERGENCY" and not has_direct_do:
        severity, risk_score = "WARNING", min(risk_score, 74)

    sensor_status = sensor_health["overall_status"]
    if missing_metrics and sensor_status == "valid":
        sensor_status = "degraded"
    confidence = "high" if has_direct_do and sensor_status == "valid" else "limited"
    previous_severity = (previous_alert or {}).get("severity", "NORMAL")
    if severity == "NORMAL" and previous_severity not in {"NORMAL", ""}:
        recovery_count = int((previous_alert or {}).get("recovery_count", 0)) + 1
        state = "RESOLVING" if recovery_count < 2 else "RESOLVED"
    else:
        recovery_count = 0
        state = "ESCALATED" if previous_severity in {"WATCH", "WARNING"} and severity == "EMERGENCY" else ("OPEN" if severity != "NORMAL" else "RESOLVED")
    return {
        "profile_version": profile["version"],
        "risk_score": risk_score,
        "severity": severity,
        "state": state,
        "recovery_count": recovery_count,
        "confidence": confidence,
        "drivers": drivers,
        "sensor_health": {**sensor_health, "status": sensor_status, "missing_metrics": missing_metrics, "direct_do_available": has_direct_do},
        "recommended_actions": _recommendations(severity, drivers),
        "disclaimer": "Cảnh báo hỗ trợ quyết định; cần xác minh thực địa. Ngưỡng cobia-v1 đang ở trạng thái provisional.",
    }
