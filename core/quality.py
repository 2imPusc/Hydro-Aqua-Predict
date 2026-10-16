# lab/realtime_greenlab/quality.py
"""Sensor quality control — phát hiện out-of-range + flatline/rail-stuck.

COD ở Cát Bà drift rồi dính rail 558.8 (sensor chết). QC dùng để:
  1. Loại từng dòng reading nằm ngoài dải vật lý (range filter)
  2. Đánh giá 1 chuỗi (1 ngày) cả series có dùng được không (flatline/rail)
"""
import pandas as pd
from core.config import PLAUSIBLE_RANGE

# Series được coi flatline nếu coefficient of variation < ngưỡng này
_FLATLINE_CV = 0.001


def is_in_range(param: str, value: float) -> bool:
    """Giá trị có nằm trong dải vật lý hợp lý không. Param lạ → True (bỏ qua)."""
    if param not in PLAUSIBLE_RANGE:
        return True
    lo, hi = PLAUSIBLE_RANGE[param]
    if value != value:   # NaN
        return False
    return lo <= value <= hi


def check_series(param: str, series: pd.Series) -> str:
    """Đánh giá 1 chuỗi reading của 1 param trong 1 ngày.

    Returns "VALID" | "INVALID".
    INVALID nếu: rỗng | đa số ngoài range | flatline (rail-stuck).
    """
    s = series.dropna()
    if len(s) == 0:
        return "INVALID"

    # Đa số nằm ngoài dải → INVALID
    in_range = s.apply(lambda v: is_in_range(param, v))
    if in_range.mean() < 0.5:
        return "INVALID"

    # Flatline / rail-stuck: gần như không dao động
    s_valid = s[in_range]
    if len(s_valid) >= 5:
        mean = s_valid.mean()
        # Dính cứng đúng 0.0: mean == 0 nên CV không xác định → xét riêng bằng std == 0
        if s_valid.std() == 0:
            return "INVALID"
        if mean != 0:
            cv = s_valid.std() / abs(mean)
            if cv < _FLATLINE_CV:
                return "INVALID"
    return "VALID"


def filter_valid_rows(df: pd.DataFrame, params: list) -> pd.DataFrame:
    """Giữ các dòng mà MỌI param trong `params` đều in-range. Range-filter outliers."""
    mask = pd.Series(True, index=df.index)
    for p in params:
        if p in df.columns:
            mask &= df[p].apply(lambda v: is_in_range(p, v))
    return df[mask].reset_index(drop=True)


# --- Per-day health (OK / SUSPECT / INVALID) -------------------------------------
# Thresholds derived from 139 local days of 06M26042804 (2026-05-29..2026-10-14),
# see research-log entry on TSS "stuck vs calm". SUSPECT = "stuck / low-information":
#   distinct values <= max_distinct  AND  fraction of minute-to-minute changes == 0
#   >= min_zero_step  AND  CV < max_cv.
# Why not "longest identical run": runs of ~29 min occur on busy days too (sensor
# update cadence), so it does not discriminate. Normal days: TSS >= 33 distinct
# except a handful of floor-limited days; pH min 15 distinct (res 0.01), Temp >= 17,
# NH4 >= 46. TSS floor days (2026-10-06..10: 7-9 distinct, zero-step 0.85-0.89,
# CV 0.013-0.027; 09-23/24 too) are flagged; 09-19, 09-25..28 (zero-step < 0.75) are not.
HEALTH_MIN_POINTS = 60  # fewer valid points: not enough to judge low-information
_HEALTH_DEFAULT = {"max_distinct": 8, "min_zero_step": 0.90, "max_cv": 0.05}
HEALTH_THRESHOLDS = {
    "TSS": {"max_distinct": 15, "min_zero_step": 0.75, "max_cv": 0.05},
}


def sensor_day_health(param: str, series: pd.Series) -> dict:
    """Grade one day of one sensor. Returns {"status": OK|SUSPECT|INVALID, "reasons": [...], "metrics": {...}}.

    INVALID: empty, majority out of range, or flatline (same rule as check_series).
    SUSPECT: stuck / low-information (see HEALTH_THRESHOLDS). check_series is unchanged.
    """
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) == 0:
        return {"status": "INVALID", "reasons": ["empty"], "metrics": {"n": 0}}
    in_range = s.apply(lambda v: is_in_range(param, v))
    if in_range.mean() < 0.5:
        return {"status": "INVALID", "reasons": ["out_of_range"], "metrics": {"n": len(s)}}
    if check_series(param, s) == "INVALID":
        return {"status": "INVALID", "reasons": ["flatline"], "metrics": {"n": len(s)}}
    v = s[in_range]
    mean = v.mean()
    d = v.diff().dropna()
    metrics = {
        "n": len(v),
        "distinct": int(v.nunique()),
        "cv": float(v.std() / abs(mean)) if mean != 0 else float("inf"),
        "zero_step": float((d == 0).mean()) if len(d) else 1.0,
    }
    th = HEALTH_THRESHOLDS.get(param, _HEALTH_DEFAULT)
    if (len(v) >= HEALTH_MIN_POINTS and metrics["distinct"] <= th["max_distinct"]
            and metrics["zero_step"] >= th["min_zero_step"] and metrics["cv"] < th["max_cv"]):
        return {"status": "SUSPECT", "reasons": ["low_information"], "metrics": metrics}
    return {"status": "OK", "reasons": [], "metrics": metrics}
