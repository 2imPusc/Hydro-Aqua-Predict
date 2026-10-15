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
