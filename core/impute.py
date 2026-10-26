# lab/realtime_greenlab/impute.py
"""Per-region adaptive imputation of missing water-quality params.

Huấn luyện RIÊNG theo vùng (tránh trộn QN/HP làm nhiễu quan hệ sensor->chỉ số):
  - haiphong (HP-only)  → dùng cho trạm HP / cobia
  - quangninh (QN-only) → dùng cho trạm QN / oyster

Mỗi vùng train 2 bộ XGBoost (adaptive theo COD):
  - 5-feature [COD, NH3, pH, Temperature, TSS]  → khi COD sensor sống
  - 4-feature [NH3, pH, Temperature, TSS]       → khi COD chết
Mỗi target 1 model. R²<0.4 trên LOO-CV → fallback trung vị vùng.
Kim loại nặng/Coliform/độ muối luôn dùng trung vị (không có tín hiệu sensor).

Amoni: cột "NH3" của dữ liệu tỉnh là amoni tổng theo N (TAN), nên feature "NH3"
của model nhận giá trị ``measured["TAN"]`` qua ``provincial_basis_row``
(config.AMMONIA_FEATURE_SOURCE) — KHÔNG nhận NH3 không ion.  Thiếu TAN → feature
coi là thiếu (``missing_features``).  Input ngoài khoảng p1–p99 của dữ liệu huấn
luyện vùng (``imputer_feature_bounds.json``) → giá trị vẫn trả về nhưng gắn cờ
``ood_features`` / ``ood_targets`` trong ``diagnostics`` (ngoại suy, không tin).
Bật/tắt theo chỉ số (alert-config ``ood_flags``) chỉ đổi phần HIỂN THỊ (``ood``,
``ood_targets``, cảnh báo); ``ood_features`` luôn ghi đủ, ``ood_features_muted``
nêu chỉ số đã tắt (``apply_ood_flags``).
"""
import json
import sys
from pathlib import Path
from typing import Dict
from datetime import datetime

# Cho phép chạy trực tiếp `python core/impute.py` từ gốc repo
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd
import joblib
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.metrics import r2_score
from xgboost import XGBRegressor

from core.config import (
    QN_DATA_PATH, HP_DATA_PATH, HY_DATA_PATH, IMPUTER_DIR, FEATURES_5, FEATURES_4,
    AMMONIA_FEATURE_SOURCE,
)
from core.chemistry import provincial_basis_row
from core import alert_config
from hap_shared.preprocessing import load_data, EXCLUDED_STATIONS

# Salinity nằm trong targets: LOO-CV R²≈0.6-0.67 cả HP/QN (biến thiên thật,
# gradient cửa sông), là chỉ số importance_rank 4 — đoán được, không để median.
IMPUTATION_TARGETS = ["DO", "Salinity", "BOD5", "Transparency", "Alkalinity", "PO4"]

# Các chỉ số luôn dùng trung vị — đã KIỂM ĐỊNH không đoán được từ 4 input sensor
# (kim loại nặng/Coliform/H2S/COD: R²<0.2 hoặc cột hằng số, xem Mục kết quả).
MEDIAN_DEFAULTS = [
    "COD", "CN", "As", "Cd", "Pb", "Cu", "Hg",
    "Zn", "Total_Cr", "Coliform", "H2S", "Cr6", "Oil", "Fluoride", "Fe", "Mn",
]

# Vùng → file dữ liệu quý huấn luyện
REGION_DATA = {
    "haiphong": HP_DATA_PATH, 
    "quangninh": QN_DATA_PATH,
    "DongThuyAnh-HY": HY_DATA_PATH,
    "ThaiNinh-HY": HY_DATA_PATH
}
DEFAULT_REGION = "haiphong"

# Ngưỡng 3 mức tin cậy nội suy (LOO-CV R²)
R2_STRONG = 0.4   # >= 0.4 → ML-mạnh: dùng, tin
R2_WEAK   = 0.2   # 0.2..0.4 → ML-yếu: dùng nhưng gắn cờ độ tin thấp; < 0.2 → median
R2_MIN    = R2_WEAK   # ngưỡng tối thiểu để dùng model (alias, giữ tương thích)

# Chỉ số là artifact của dữ liệu tổng hợp (tương quan tất định với COD) →
# KHÔNG dùng ML dù R² cao, luôn fallback median. (BOD5/Alkalinity ở QN: R²≈1.0 giả).
ARTIFACT_TARGETS = {"BOD5", "Alkalinity"}

# Cấu hình Mùa vụ (Seasonality) cho từng chỉ tiêu đặc thù dựa trên thực nghiệm
SEASONALITY_CONFIG = {
    "haiphong": {
        "Salinity": "month",
        "PO4": "cyclical"
    },
    "quangninh": {
        "Transparency": "month"
    }
}

def r2_tier(target: str, r2) -> str:
    """Phân hạng tin cậy: 'artifact' | 'strong' | 'weak' | 'median'."""
    if target in ARTIFACT_TARGETS:
        return "artifact"
    if r2 is None:
        return "median"
    if r2 >= R2_STRONG:
        return "strong"
    if r2 >= R2_WEAK:
        return "weak"
    return "median"


_METADATA = {"Station", "Quarter", "X", "Y", "Lat", "Lon",
             "year", "quarter_num", "time_idx"}

_MEDIANS_FILE = IMPUTER_DIR / "regional_medians.json"
_CV_R2_FILE   = IMPUTER_DIR / "cv_r2.json"
_FEATCOLS_FILE = IMPUTER_DIR / "feat_cols.json"   # cột feature thực mỗi (vùng, tag)
_BOUNDS_FILE  = IMPUTER_DIR / "imputer_feature_bounds.json"  # p1–p99 input mỗi vùng
OOD_QUANTILES = (0.01, 0.99)
_BOUNDS_CACHE: dict = {}


def build_training_data(region: str) -> pd.DataFrame:
    """Load dữ liệu quý CỦA RIÊNG 1 vùng, bỏ trạm loại trừ, bỏ dòng thiếu feature lõi."""
    path = REGION_DATA[region]
    if not Path(path).exists():
        raise FileNotFoundError(f"Data vùng '{region}' không thấy: {path}")
    df = load_data(str(path))
    df = df[~df["Station"].isin(EXCLUDED_STATIONS)]
    core = [f for f in FEATURES_4 if f in df.columns]
    df = df.dropna(subset=core).reset_index(drop=True)
    
    if "Quarter" in df.columns:
        df["month"] = pd.to_datetime(df["Quarter"]).dt.month
    elif "date" in df.columns:
        df["month"] = pd.to_datetime(df["date"]).dt.month
        
    if "month" in df.columns:
        df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
        df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
        
    return df


def _train_one_set(df: pd.DataFrame, features: list, region: str, tag: str) -> dict:
    """Train per-target imputers cho 1 (vùng, feature set). Returns {target: cv_r2}."""
    logo = LeaveOneGroupOut()
    groups = df["Station"].values
    cv_r2 = {}

    for target in IMPUTATION_TARGETS:
        target_features = list(features)
        season_type = SEASONALITY_CONFIG.get(region, {}).get(target)
        if season_type == "month":
            target_features.append("month")
        elif season_type == "cyclical":
            target_features.extend(["month_sin", "month_cos"])
            
        target_feat_cols = [f for f in target_features if f in df.columns]
        X = df[target_feat_cols].values

        if target not in df.columns:
            cv_r2[target] = None
            continue
        y = df[target].values
        valid = ~np.isnan(y)
        if valid.sum() < 10:
            cv_r2[target] = None
            continue

        preds, trues = [], []
        for tr, te in logo.split(X, y, groups):
            tv = valid[tr]
            if tv.sum() < 5:
                continue
            m = XGBRegressor(n_estimators=100, max_depth=4, learning_rate=0.1,
                             random_state=42, verbosity=0)
            m.fit(X[tr][tv], y[tr][tv])
            ev = valid[te]
            if ev.sum() == 0:
                continue
            preds.extend(m.predict(X[te][ev]))
            trues.extend(y[te][ev])

        if len(trues) < 5:
            cv_r2[target] = None
            continue
        r2 = round(float(r2_score(trues, preds)), 4)
        cv_r2[target] = r2

        tier = r2_tier(target, r2)
        # Lưu model cho cả mức mạnh lẫn yếu (>=0.2); KHÔNG lưu artifact dù R² cao.
        if tier in ("strong", "weak"):
            m = XGBRegressor(n_estimators=100, max_depth=4, learning_rate=0.1,
                             random_state=42, verbosity=0)
            m.fit(X[valid], y[valid])
            joblib.dump(m, IMPUTER_DIR / f"{target}_{region}_{tag}.pkl")
            mark = "✓ mạnh" if tier == "strong" else "~ yếu (cờ độ tin thấp)"
            print(f"  [{region}/{tag}] {target}: R²={r2} {mark}")
        elif tier == "artifact":
            print(f"  [{region}/{tag}] {target}: R²={r2} ✗ ARTIFACT → median")
        else:
            print(f"  [{region}/{tag}] {target}: R²={r2} ✗ → median")
    return cv_r2


def train(force: bool = False) -> dict:
    """Train per-region (HP + QN), mỗi vùng 2 bộ feature. Returns cv_r2 dict.

    cv_r2.json shape:  {region: {tag: {target: r2}}}
    regional_medians.json shape: {region: {param: median}}
    """
    if _CV_R2_FILE.exists() and not force:
        with open(_CV_R2_FILE) as f:
            return json.load(f)

    cv_all, med_all, feat_all = {}, {}, {}
    for region in REGION_DATA:
        if not Path(REGION_DATA[region]).exists():
            print(f"(bỏ qua vùng '{region}' — không có data)")
            continue
        df = build_training_data(region)
        print(f"== Vùng {region}: {len(df)} dòng, {df['Station'].nunique()} trạm ==")

        numeric_cols = df.select_dtypes(include=['number']).columns
        params = [c for c in numeric_cols if c not in _METADATA]
        med_all[region] = {p: float(df[p].median()) for p in params if not df[p].isnull().all()}

        # Cột feature thực có trong vùng (vd HP thiếu COD → 5feat thực chất = 4 cột)
        feat_all[region] = {
            "5feat": [f for f in FEATURES_5 if f in df.columns],
            "4feat": [f for f in FEATURES_4 if f in df.columns],
        }
        cv_all[region] = {
            "5feat": _train_one_set(df, FEATURES_5, region, "5feat"),
            "4feat": _train_one_set(df, FEATURES_4, region, "4feat"),
        }

    with open(_MEDIANS_FILE, "w") as f:
        json.dump(med_all, f, indent=2)
    with open(_CV_R2_FILE, "w") as f:
        json.dump(cv_all, f, indent=2)
    with open(_FEATCOLS_FILE, "w") as f:
        json.dump(feat_all, f, indent=2)
    return cv_all


def compute_feature_bounds() -> dict:
    """p1–p99 (and min/max) of every imputer input feature, per region.

    Computed on ``build_training_data`` rows — exactly what the models saw.  The
    ``NH3`` entry is provincial ammonium (TAN basis).  Shape:
    ``{"quantiles": [0.01, 0.99], "regions": {region: {feature: {p_lo, p_hi, min, max, n}}}}``
    """
    regions = {}
    for region, path in REGION_DATA.items():
        if not Path(path).exists():
            continue
        df = build_training_data(region)
        regions[region] = {}
        for feature in FEATURES_5:
            if feature not in df.columns:
                continue
            values = pd.to_numeric(df[feature], errors="coerce").dropna()
            if values.empty:
                continue
            regions[region][feature] = {
                "p_lo": round(float(values.quantile(OOD_QUANTILES[0])), 6),
                "p_hi": round(float(values.quantile(OOD_QUANTILES[1])), 6),
                "min": round(float(values.min()), 6),
                "max": round(float(values.max()), 6),
                "n": int(len(values)),
            }
    return {
        "quantiles": list(OOD_QUANTILES),
        "basis": {"NH3": "TAN — total ammonium as N (provincial 'Amôni (NH4+ tính theo N)')"},
        "source": "core.impute.build_training_data (data/*/clean_data.csv, excluded stations dropped)",
        "regions": regions,
    }


def write_feature_bounds() -> dict:
    bounds = compute_feature_bounds()
    with open(_BOUNDS_FILE, "w", encoding="utf-8") as f:
        json.dump(bounds, f, indent=2, ensure_ascii=False)
    _BOUNDS_CACHE.clear()
    return bounds


def _load_bounds() -> dict | None:
    if "value" not in _BOUNDS_CACHE:
        _BOUNDS_CACHE["value"] = json.loads(_BOUNDS_FILE.read_text(encoding="utf-8")) if _BOUNDS_FILE.exists() else None
    return _BOUNDS_CACHE["value"]


def input_diagnostics(row: Dict[str, float], features: list, region: str) -> dict:
    """Missing / out-of-training-range check of the model input row.

    ``row`` is already on the provincial basis (``NH3`` = TAN).  OOD = outside
    the region's p1–p99 training range; values are still returned by the caller
    but flagged, following the ``ood_features`` convention of contextual_models.
    """
    bounds_doc = _load_bounds()
    region_bounds = (bounds_doc or {}).get("regions", {}).get(region)
    missing, ood, ranges, values = [], [], {}, {}
    for feature in features:
        value = row.get(feature)
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = float("nan")
        if value != value:
            missing.append(feature)
            continue
        values[feature] = round(value, 6)
        spec = (region_bounds or {}).get(feature)
        if spec is None:
            continue
        ranges[feature] = [spec["p_lo"], spec["p_hi"]]
        if value < spec["p_lo"] or value > spec["p_hi"]:
            ood.append(feature)
    return {
        "ammonia_basis": "TAN",
        "ammonia_feature_source": dict(AMMONIA_FEATURE_SOURCE),
        "feature_values": values,
        "missing_features": missing,
        "ood_features": ood,
        "training_range": ranges,
        "bounds_source": _BOUNDS_FILE.name if region_bounds is not None else "unavailable",
    }


def _load_json(path: Path, what: str) -> dict:
    if not path.exists():
        raise RuntimeError(f"{what} not found — chạy `impute.py --train` trước.")
    with open(path) as f:
        return json.load(f)


def load_ood_flags() -> dict:
    """Effective per-metric toggles (``core.alert_config.ood_flag_settings``); load once per run."""
    return alert_config.ood_flag_settings()


def apply_ood_flags(diagnostics: dict, imputed_targets: list, ood_flags: dict | None) -> dict:
    """Split ``ood_features`` into surfaced / muted per the admin toggles (in place).

    ``ood_features`` (every out-of-range input) is never filtered — it is what gets logged.
    ``ood`` / ``ood_targets`` (and the caller's ``input_flagged``) count only surfaced
    features; ``ood_any`` / ``ood_targets_all`` keep the unmuted answer; ``ood_flags``
    records the config version and which metrics were muted.
    """
    flags = ood_flags if ood_flags is not None else load_ood_flags()
    toggles = flags.get("features") or {}
    raw = list(diagnostics.get("ood_features") or [])
    muted = [f for f in raw if f in toggles and not toggles[f].get("enabled", True)]
    surfaced = [f for f in raw if f not in muted]
    diagnostics["ood_features_surfaced"] = surfaced
    diagnostics["ood_features_muted"] = muted
    diagnostics["ood_any"] = bool(raw)
    diagnostics["ood"] = bool(surfaced)
    diagnostics["ood_targets_all"] = list(imputed_targets) if raw else []
    diagnostics["ood_targets"] = list(imputed_targets) if surfaced else []
    diagnostics["ood_flags"] = {
        "config_version": flags.get("config_version"),
        "source": flags.get("source"),
        "muted_metrics": list(flags.get("muted_metrics") or []),
        "muted_features": list(flags.get("muted_features") or []),
    }
    return diagnostics


def ood_metric_label(feature: str, ood_flags: dict | None) -> str:
    """Display name of an imputer feature (``NH3`` → ``TAN``, the provincial ammonium basis)."""
    entry = ((ood_flags or {}).get("features") or {}).get(feature)
    if entry:
        return entry["metric"]
    return "TAN" if feature == "NH3" else feature


def impute_params(measured: Dict[str, float], region: str = DEFAULT_REGION,
                  ood_flags: dict | None = None) -> Dict:
    """Adaptive impute theo VÙNG. COD trong measured → 5feat; vắng → 4feat.

    ``ood_flags``: per-metric toggles from ``load_ood_flags()`` (None → load the effective
    alert-config). They change only what is surfaced; ``diagnostics["ood_features"]`` is
    always the full list.

    Returns {imputed, defaulted, cv_r2, feature_set, region}.
    """
    if not _CV_R2_FILE.exists():
        train()

    med_all  = _load_json(_MEDIANS_FILE, "Medians")
    cv_all   = _load_json(_CV_R2_FILE, "CV R²")
    feat_all = _load_json(_FEATCOLS_FILE, "Feature cols")

    if region not in cv_all:
        region = DEFAULT_REGION
    medians = med_all.get(region, {})
    cv_region = cv_all[region]

    use_5 = "COD" in measured and measured["COD"] == measured["COD"]  # present & not NaN
    tag = "5feat" if use_5 else "4feat"
    cv_r2 = cv_region[tag]
    # Dùng ĐÚNG cột feature model đã train (vd HP thiếu COD → bỏ COD khỏi vector)
    features = feat_all.get(region, {}).get(tag, FEATURES_5 if use_5 else FEATURES_4)

    # Inject seasonality values if needed
    month_val = None
    if "fetchedAt" in measured:
        month_val = pd.to_datetime(measured["fetchedAt"]).month
    elif "date" in measured:
        month_val = pd.to_datetime(measured["date"]).month
    else:
        month_val = datetime.now().month

    measured["month"] = month_val
    measured["month_sin"] = np.sin(2 * np.pi * month_val / 12)
    measured["month_cos"] = np.cos(2 * np.pi * month_val / 12)

    # Model input row on the provincial basis: feature "NH3" ← measured["TAN"]
    # (never the un-ionised NH3; absent TAN → feature missing).
    row = provincial_basis_row(measured)
    diagnostics = input_diagnostics(row, features, region)

    imputed, defaulted, confidence = {}, {}, {}

    for target in IMPUTATION_TARGETS:
        r2 = cv_r2.get(target)
        tier = r2_tier(target, r2)
        model_path = IMPUTER_DIR / f"{target}_{region}_{tag}.pkl"
        if tier in ("strong", "weak") and model_path.exists():
            target_features = list(features)
            season_type = SEASONALITY_CONFIG.get(region, {}).get(target)
            if season_type == "month":
                target_features.append("month")
            elif season_type == "cyclical":
                target_features.extend(["month_sin", "month_cos"])
                
            feat_vals = np.array([[row.get(f, np.nan) for f in target_features]], dtype=float)
            val = float(joblib.load(model_path).predict(feat_vals)[0])
            imputed[target] = round(max(0.0, val), 4)
            confidence[target] = tier      # 'strong' | 'weak'
        elif target in medians:
            defaulted[target] = round(medians[target], 4)

    for p in MEDIAN_DEFAULTS:
        # COD chỉ defaulted khi vắng trong measured (sensor chết)
        if p == "COD" and use_5:
            continue
        if p in medians:
            defaulted[p] = round(medians[p], 4)

    # Model outputs built from a missing or out-of-range input are extrapolations.
    diagnostics["missing_input_targets"] = sorted(imputed) if diagnostics["missing_features"] else []
    apply_ood_flags(diagnostics, sorted(imputed), ood_flags)
    flagged = bool(diagnostics["ood"] or diagnostics["missing_features"])

    return {"imputed": imputed, "defaulted": defaulted, "confidence": confidence,
            "cv_r2": cv_r2, "feature_set": tag, "region": region,
            "diagnostics": diagnostics, "input_flagged": flagged}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--bounds", action="store_true",
                    help="ghi imputer_feature_bounds.json (p1–p99 input mỗi vùng), không train lại")
    args = ap.parse_args()
    if args.bounds:
        out = write_feature_bounds()
        for region, feats in out["regions"].items():
            print(f" [{region}]", {f: [v["p_lo"], v["p_hi"]] for f, v in feats.items()})
    if args.train or args.force:
        print("Training per-region imputer (HP + QN, mỗi vùng 5feat + 4feat)...")
        res = train(force=args.force)
        print("\nCV R² summary:")
        for region, tags in res.items():
            for tag in ("5feat", "4feat"):
                print(f" [{region}/{tag}]", {t: r for t, r in tags[tag].items()})
