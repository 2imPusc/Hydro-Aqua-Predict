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
)
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


def _load_json(path: Path, what: str) -> dict:
    if not path.exists():
        raise RuntimeError(f"{what} not found — chạy `impute.py --train` trước.")
    with open(path) as f:
        return json.load(f)


def impute_params(measured: Dict[str, float], region: str = DEFAULT_REGION) -> Dict:
    """Adaptive impute theo VÙNG. COD trong measured → 5feat; vắng → 4feat.

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
                
            feat_vals = np.array([[measured.get(f, np.nan) for f in target_features]])
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

    return {"imputed": imputed, "defaulted": defaulted, "confidence": confidence,
            "cv_r2": cv_r2, "feature_set": tag, "region": region}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.train or args.force:
        print("Training per-region imputer (HP + QN, mỗi vùng 5feat + 4feat)...")
        res = train(force=args.force)
        print("\nCV R² summary:")
        for region, tags in res.items():
            for tag in ("5feat", "4feat"):
                print(f" [{region}/{tag}]", {t: r for t, r in tags[tag].items()})
