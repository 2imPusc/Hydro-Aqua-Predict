"""Tropical-cyclone exposure and risk for a cage site (theory only, shadow).

Beaufort bounds, storm classes and risk levels follow Quyết định 18/2021/QĐ-TTg
(Điều 42 for storms on the coastal waters off Đông Bắc Bộ).  IBTrACS rows are
best-track post-analysis: use them for hindcast exposure only, never as forecast
skill.  Nothing here drives alerts or notifications.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

KNOT_MS = 0.514444
NMI_KM = 1.852
# 1-min sustained -> 10-min mean at sea (Harper et al. 2010, WMO/TD-1555); 0.88 is the sensitivity case.
ONE_MIN_TO_TEN_MIN = 0.93
BEAUFORT_LOWER_MS = (0.0, 0.3, 1.6, 3.4, 5.5, 8.0, 10.8, 13.9, 17.2, 20.8, 24.5, 28.5,
                     32.7, 37.0, 41.5, 46.2, 51.0, 56.1)
_UNIT_TO_MS = {"m/s": 1.0, "ms": 1.0, "km/h": 1 / 3.6, "kmh": 1 / 3.6, "kn": KNOT_MS, "kt": KNOT_MS, "knots": KNOT_MS}
# Own proposal; needs review by farmers and the local disaster-prevention office.
SITE_ACTIONS_VI = (
    (12, 4, "rất nguy hiểm", "Người rời lồng bè vào nơi trú ẩn theo lệnh của địa phương."),
    (10, 3, "nguy hiểm", "Thu hoạch sớm cá thương phẩm nếu kịp; gia cố hoặc kéo lồng vào nơi kín gió; người rời lồng trước khi gió mạnh lên."),
    (8, 2, "chuẩn bị", "Gia cố neo, dây, phao; giảm hoặc ngừng cho ăn; chuẩn bị phương án thu hoạch và di dời."),
    (6, 1, "theo dõi", "Kiểm tra neo, dây, phao; theo dõi bản tin bão."),
)


def _missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value)


def to_ms(value: float, unit: str) -> float:
    key = unit.strip().lower()
    if key not in _UNIT_TO_MS:
        raise ValueError(f"unknown wind unit: {unit}")
    return float(value) * _UNIT_TO_MS[key]


def beaufort(speed_ms: float | None) -> int | None:
    if _missing(speed_ms):
        return None
    level = 0
    for lvl, lower in enumerate(BEAUFORT_LOWER_MS):
        if speed_ms >= lower:
            level = lvl
    return level


def storm_class_vi(level: int | None) -> str | None:
    if level is None or level < 6:
        return None
    if level <= 7:
        return "áp thấp nhiệt đới"
    if level <= 9:
        return "bão"
    if level <= 11:
        return "bão mạnh"
    if level <= 15:
        return "bão rất mạnh"
    return "siêu bão"


def qd18_risk_level(level: int | None) -> int | None:
    """Cấp độ rủi ro for a storm on coastal waters / Đông Bắc Bộ (QĐ 18/2021, Điều 42)."""
    if level is None or level < 6:
        return None
    if level <= 11:
        return 3
    if level <= 15:
        return 4
    return 5


def site_action(level: int | None) -> dict:
    base = {"basis": "proposal_needs_expert_review"}
    if level is None:
        return {**base, "tier": None, "label_vi": None, "action_vi": None}
    for min_level, tier, label, action in SITE_ACTIONS_VI:
        if level >= min_level:
            return {**base, "tier": tier, "label_vi": label, "action_vi": action}
    return {**base, "tier": 0, "label_vi": "bình thường", "action_vi": None}
