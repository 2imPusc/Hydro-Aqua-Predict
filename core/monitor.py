# lab/realtime_greenlab/monitor.py
"""QCVN-10 B1 threshold check. NH3 đã được derive trước (chemistry).

COD chỉ được check khi caller truyền vào (sensor sống); sensor chết →
caller không đưa COD → không báo EXCEED giả.
"""
from dataclasses import dataclass
from typing import Dict
from core.config import QCVN10_B1


@dataclass
class ParamStatus:
    param: str
    value: float
    status: str        # "OK" | "EXCEED"
    limit_type: str    # "max" | "min" | "range"
    limit_value: float
    limits: dict       # raw QCVN10_B1[param] để hiển thị đầy đủ (vd range cả min+max)

    def limit_str(self) -> str:
        """Chuỗi ngưỡng human-readable (range hiển thị cả 2 cận)."""
        if "min" in self.limits and "max" in self.limits:
            return f"{self.limits['min']}–{self.limits['max']}"
        if "max" in self.limits:
            return f"≤{self.limits['max']}"
        return f"≥{self.limits['min']}"


def check_params(measured: Dict[str, float]) -> Dict[str, ParamStatus]:
    """Check params chống QCVN 10:2023/BTNMT B1. Chỉ params có trong QCVN10_B1."""
    results = {}
    for param, value in measured.items():
        if param not in QCVN10_B1:
            continue
        limits = QCVN10_B1[param]
        if "min" in limits and "max" in limits:
            ok = limits["min"] <= value <= limits["max"]
            lt, lv = "range", limits["max"]
        elif "max" in limits:
            ok = value <= limits["max"]
            lt, lv = "max", limits["max"]
        else:  # only min
            ok = value >= limits["min"]
            lt, lv = "min", limits["min"]
        results[param] = ParamStatus(
            param=param, value=value,
            status="OK" if ok else "EXCEED",
            limit_type=lt, limit_value=lv, limits=limits,
        )
    return results
