"""Alert policy for inferred DO; deliberately separate from direct-sensor alerts."""
from __future__ import annotations
from typing import Any

def evaluate_inferred_do_alert(contextual: dict, measured: dict, previous: dict | None = None) -> dict:
    prediction = (contextual or {}).get("predictions", {}).get("DO", {})
    if (contextual or {}).get("status") != "ready" or prediction.get("status") != "accepted":
        return {"severity": "BLOCKED", "state": "BLOCKED", "source": "inferred_do", "reason": prediction.get("missing_features") or (contextual or {}).get("reason", "model_rejected"), "used_by_emergency": False}
    do = float(prediction["value"])
    if do <= 3: severity = "HIGH_RISK"
    elif do <= 4: severity = "WARNING"
    elif do <= 5: severity = "WATCH"
    else: severity = "NORMAL"
    prior_count = int((previous or {}).get("consecutive_risk_count", 0))
    count = prior_count + 1 if severity != "NORMAL" else 0
    temp = measured.get("Temperature")
    nh3 = measured.get("NH3")
    compound = (temp is not None and temp >= 33) or (nh3 is not None and nh3 >= .10)
    prior_do = (previous or {}).get("predicted_do")
    rapid_drop = prior_do is not None and do - float(prior_do) <= -.8
    # A single model prediction can watch; warning needs persistence, compound stress or rapid decline.
    if severity in {"WARNING", "HIGH_RISK"} and count < 2 and not compound and not rapid_drop:
        severity = "WATCH"
    actions = ["Kiểm tra thực địa và tăng sục khí/điều kiện dòng chảy nếu phù hợp."] if severity not in {"NORMAL", "BLOCKED"} else []
    return {"severity": severity, "state": "OPEN" if severity not in {"NORMAL", "BLOCKED"} else "RESOLVED", "source": "inferred_do", "predicted_do": do, "model_version": prediction.get("model_version"), "consecutive_risk_count": count, "compound_stress": compound, "rapid_drop": rapid_drop, "used_by_emergency": False, "recommended_actions": actions, "disclaimer": "Cảnh báo dựa trên DO nội suy; cần xác minh thực địa, không phải DO đo trực tiếp."}
