# lab/realtime_greenlab/classify.py
"""Build full param row (measured + imputed + defaulted) → suitability classification.

measured ở đây đã qua QC + derive amoni từ fetch: TAN (amoni tổng theo N — cơ sở
dữ liệu tỉnh, dùng cho imputer/HSI) và NH3 không ion (chỉ để hiển thị/cảnh báo độc
tính, không vào HSI). COD chỉ có mặt khi sensor sống.
"""
import pandas as pd
from typing import Dict

from hap_shared.classification import _classify_by_scoring, LABEL_NAMES as _SRC_LABELS
from core.chemistry import provincial_basis_row
from core.impute import impute_params, load_ood_flags, ood_metric_label, DEFAULT_REGION
from core.config import NH4_UNIT_NOTE

LABEL_NAMES = _SRC_LABELS


def classify_station(station_serial: str, measured: Dict[str, float],
                     species: str, date: str = None,
                     region: str = DEFAULT_REGION, ood_flags: Dict | None = None) -> Dict:
    """Classify suitability cho 1 trạm-ngày.

    Parameters
    ----------
    station_serial : device serial
    measured : params đo được đã QC ({TAN, pH, Temperature, TSS} (+COD nếu sống);
               NH3 không ion nếu có chỉ đi kèm, không vào HSI)
    species  : "oyster" | "cobia"
    date     : ISO date string (optional, để label)
    region   : "haiphong" | "quangninh" — chọn bộ imputer + median theo vùng
    ood_flags: bật/tắt cờ ngoài dải theo chỉ số (``load_ood_flags()``; None → đọc
               alert-config hiệu lực). Chỉ đổi phần hiển thị, chẩn đoán luôn ghi đủ.
    """
    ood_flags = ood_flags if ood_flags is not None else load_ood_flags()
    imp = impute_params(measured, region=region, ood_flags=ood_flags)
    imputed, defaulted = imp["imputed"], imp["defaulted"]
    confidence = imp.get("confidence", {})
    diagnostics = imp.get("diagnostics", {})

    # measured đè imputed đè defaulted.  HSI breakpoints "NH3" are provincial
    # ammonium → scoring row carries TAN in that slot (provincial_basis_row).
    full_row = provincial_basis_row({**defaulted, **imputed, **measured})
    available = list(full_row.keys())

    result_df = _classify_by_scoring(pd.DataFrame([full_row]), available, species)
    score = float(result_df["suitability_score"].iloc[0])
    label = int(result_df["suitability_label"].iloc[0])

    # TAN is a second view of the same NH4 reading — not counted as an extra param.
    total = len([k for k in available if k != "TAN"])
    n_measured = len([k for k in measured if k != "TAN"])
    imputed_fraction = round(1 - n_measured / total, 3) if total else 1.0

    strong = [t for t, c in confidence.items() if c == "strong"]
    weak   = [t for t, c in confidence.items() if c == "weak"]

    warn = [f"{round(imputed_fraction*100)}% params không đo trực tiếp — tham khảo",
            f"Amoni (TAN, NH4+-N) dựa giả định đơn vị NH4: {NH4_UNIT_NOTE}; "
            "NH3 không ion chỉ dùng cho cảnh báo độc tính"]
    if diagnostics.get("missing_features"):
        warn.append(f"Thiếu input imputer: {', '.join(diagnostics['missing_features'])} "
                    "(NH3 = amoni TAN) — giá trị nội suy kém tin cậy")
    flags = diagnostics.get("ood_flags") or {}

    def ood_label(feature: str) -> str:  # imputer feature "NH3" is shown as TAN
        return ood_metric_label(feature, ood_flags)

    if diagnostics.get("ood_features_surfaced"):
        warn.append(f"Input ngoài dải huấn luyện (p1–p99) "
                    f"{', '.join(ood_label(f) for f in diagnostics['ood_features_surfaced'])} "
                    "— giá trị nội suy là ngoại suy, gắn cờ OOD")
    if diagnostics.get("ood_features_muted"):
        warn.append(f"Cờ ngoài dải huấn luyện đã tắt cho "
                    f"{', '.join(ood_label(f) for f in diagnostics['ood_features_muted'])} "
                    f"(cấu hình {flags.get('config_version') or 'mặc định'}; vẫn ghi trong chẩn đoán)")
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
        "imputation_diagnostics": diagnostics,
        "warning": " | ".join(warn),
    }
