"""Versioned, shadow-only contextual models for Hai Phong."""
from __future__ import annotations
import json
import joblib
import pandas as pd
from core.config import IMPUTER_DIR, NH4_CONVERSION_CONFIRMED
from core.quality import is_in_range

MANIFEST = IMPUTER_DIR / "haiphong_contextual_manifest.json"

def predict_haiphong_contextual(measured: dict, observed_at=None) -> dict:
    result = {"mode": "shadow", "used_by_alerts": False, "used_by_suitability": False, "predictions": {}}
    if not NH4_CONVERSION_CONFIRMED:
        result.update({"status": "disabled", "reason": "nh4_conversion_unconfirmed"})
        return result
    if not MANIFEST.exists():
        result.update({"status": "unavailable", "reason": "model_bundle_missing"})
        return result
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for target, spec in manifest["targets"].items():
        values = dict(measured)
        if "month" in spec["features"]:
            values["month"] = pd.to_datetime(observed_at, utc=True).month if observed_at is not None else None
        missing = [f for f in spec["features"] if values.get(f) is None or pd.isna(values.get(f))]
        invalid = [f for f in spec["features"] if f in values and f != "month" and not pd.isna(values[f]) and not is_in_range(f, float(values[f]))]
        ood = [f for f in spec["features"] if f in spec["feature_bounds"] and f in values and values.get(f) is not None and (float(values[f]) < spec["feature_bounds"][f][0] or float(values[f]) > spec["feature_bounds"][f][1])]
        if missing or invalid or ood:
            result["predictions"][target] = {"status": "rejected", "missing_features": missing, "invalid_features": invalid, "ood_features": ood, "model_version": manifest["version"]}
            continue
        model = joblib.load(IMPUTER_DIR / spec["artifact"])
        value = float(model.predict(pd.DataFrame([[values[f] for f in spec["features"]]], columns=spec["features"]))[0])
        result["predictions"][target] = {"status": "accepted", "value": max(0.0, round(value, 4)), "source": "contextual_shadow", "model_version": manifest["version"], "confidence": "limited"}
    result["status"] = "ready"
    return result
