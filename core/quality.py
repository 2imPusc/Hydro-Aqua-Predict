# lab/realtime_greenlab/quality.py
"""Sensor quality control — phát hiện out-of-range + flatline/rail-stuck.

COD ở Cát Bà drift rồi dính rail 558.8 (sensor chết). QC dùng để:
  1. Loại từng dòng reading nằm ngoài dải vật lý (range filter)
  2. Đánh giá 1 chuỗi (1 ngày) cả series có dùng được không (flatline/rail)
"""
import pandas as pd
from core.config import (PH_DAY_MAX_OUT_OF_BAND_FRACTION, PH_MAX_CHANGE_PER_HOUR, PH_PLAUSIBLE_BAND,
                         PLAUSIBLE_RANGE)

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
    SUSPECT: stuck / low-information (see HEALTH_THRESHOLDS); for pH also median out of
    PH_PLAUSIBLE_BAND or > PH_DAY_MAX_OUT_OF_BAND_FRACTION of readings out of band.
    With a DatetimeIndex, pH metrics also count 60-min rate jumps (informational). check_series is unchanged.
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
    reasons = []
    th = HEALTH_THRESHOLDS.get(param, _HEALTH_DEFAULT)
    if (len(v) >= HEALTH_MIN_POINTS and metrics["distinct"] <= th["max_distinct"]
            and metrics["zero_step"] >= th["min_zero_step"] and metrics["cv"] < th["max_cv"]):
        reasons.append("low_information")
    if param == "pH":
        reasons += _ph_day_reasons(v, metrics)
    return {"status": "SUSPECT" if reasons else "OK", "reasons": reasons, "metrics": metrics}


# --- pH plausibility (probe drift from 2026-09-19, research log RL-13) ---------------
# Rules mark SUSPECT only; the hard PLAUSIBLE_RANGE (INVALID) is unchanged.
_RATE_TOLERANCE = pd.Timedelta(minutes=2)  # match t-60 min to the nearest reading within this


def ph_in_band(value: float) -> bool:
    """True if a pH reading is plausible for coastal seawater (PH_PLAUSIBLE_BAND). NaN -> False."""
    if value != value:
        return False
    lo, hi = PH_PLAUSIBLE_BAND
    return lo <= value <= hi


def ph_rate_suspect(series: pd.Series) -> pd.Series:
    """Per reading: |pH(t) - pH(t-60 min)| > PH_MAX_CHANGE_PER_HOUR.

    Needs a DatetimeIndex (t-60 min is matched to the nearest reading within 2 min);
    any other index or no reading an hour earlier -> False.
    """
    flags = pd.Series(False, index=series.index)
    if not isinstance(series.index, pd.DatetimeIndex) or len(series) < 2:
        return flags
    s = pd.to_numeric(series, errors="coerce").dropna()
    s = s.groupby(level=0).median().sort_index()
    if s.empty:
        return flags
    prior = s.reindex(s.index - pd.Timedelta(minutes=60), method="nearest", tolerance=_RATE_TOLERANCE)
    jump = pd.Series((s.to_numpy() - prior.to_numpy()), index=s.index).abs() > PH_MAX_CHANGE_PER_HOUR
    return pd.Series(jump.reindex(series.index).fillna(False).to_numpy(dtype=bool), index=series.index)


def ph_reading_suspect(series: pd.Series) -> pd.Series:
    """Per reading SUSPECT flag: outside PH_PLAUSIBLE_BAND or a > 0.5 change within 60 min."""
    band = pd.to_numeric(series, errors="coerce").map(ph_in_band).astype(bool)
    return ~band | ph_rate_suspect(series)


def _ph_day_reasons(v: pd.Series, metrics: dict) -> list:
    oob = 1.0 - float(v.map(ph_in_band).mean())
    rate = ph_rate_suspect(v) if isinstance(v.index, pd.DatetimeIndex) else None
    metrics.update({"median": float(v.median()), "oob_fraction": round(oob, 4),
                    "rate_jumps": int(rate.sum()) if rate is not None else None})
    reasons = []
    if not ph_in_band(metrics["median"]):
        reasons.append("ph_median_out_of_band")
    if oob > PH_DAY_MAX_OUT_OF_BAND_FRACTION:
        reasons.append("ph_out_of_band_fraction")
    return reasons
