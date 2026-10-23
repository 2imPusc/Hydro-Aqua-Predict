# lab/realtime_greenlab/classify.py
"""Build full param row (measured + imputed + defaulted) → suitability classification.

measured ở đây đã qua QC + NH3 derive (từ fetch). COD chỉ có mặt khi sensor sống.
"""
import pandas as pd
from typing import Dict

from hap_shared.classification import _classify_by_scoring, LABEL_NAMES as _SRC_LABELS
from core.impute import impute_params, DEFAULT_REGION
from core.config import NH4_UNIT_NOTE

LABEL_NAMES = _SRC_LABELS


def classify_station(station_serial: str, measured: Dict[str, float],
                     species: str, date: str = None,
                     region: str = DEFAULT_REGION) -> Dict:
    """Classify suitability cho 1 trạm-ngày.

    Parameters
    ----------
    station_serial : device serial
    measured : params đo được đã QC ({NH3, pH, Temperature, TSS} (+COD nếu sống))
    species  : "oyster" | "cobia"
    date     : ISO date string (optional, để label)
    region   : "haiphong" | "quangninh" — chọn bộ imputer + median theo vùng
    """
    imp = impute_params(measured, region=region)
    imputed, defaulted = imp["imputed"], imp["defaulted"]
    confidence = imp.get("confidence", {})

    # measured đè imputed đè defaulted
    full_row = {**defaulted, **imputed, **measured}
    available = list(full_row.keys())

    result_df = _classify_by_scoring(pd.DataFrame([full_row]), available, species)
    score = float(result_df["suitability_score"].iloc[0])
    label = int(result_df["suitability_label"].iloc[0])

    total = len(available)
    imputed_fraction = round(1 - len(measured) / total, 3) if total else 1.0

    strong = [t for t, c in confidence.items() if c == "strong"]
    weak   = [t for t, c in confidence.items() if c == "weak"]

    warn = [f"{round(imputed_fraction*100)}% params không đo trực tiếp — tham khảo",
            f"NH3 dựa giả định đơn vị NH4: {NH4_UNIT_NOTE}"]
    if strong:
        warn.append(f"ML-mạnh (R²≥0.4): {', '.join(strong)}")
    if weak:
        warn.append(f"ML-yếu (0.2≤R²<0.4, độ tin thấp): {', '.join(weak)}")
    if "Salinity" in defaulted:
        warn.append(f"Salinity dùng median vùng {imp['region']}")
    if "COD" not in measured:
        warn.append("COD sensor chết → dùng median + imputer 4-feature")

    return {
        "station": station_serial, "date": date, "species": species,
        "region": imp["region"],
        "label": LABEL_NAMES[label], "score": round(score, 4),
        "feature_set": imp["feature_set"],
        "params": {"measured": measured, "imputed": imputed, "defaulted": defaulted},
        "confidence": confidence,
        "imputed_fraction": imputed_fraction,
        "cv_r2": {t: r for t, r in imp["cv_r2"].items() if r is not None},
        "warning": " | ".join(warn),
    }
