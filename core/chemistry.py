# lab/realtime_greenlab/chemistry.py
"""NH4+ → NH3 conversion via Emerson et al. (1975) ammonia equilibrium.

Sensor đo tổng amoni (NH4+); QCVN đánh giá độc tính theo NH3 (không phân ly).
Tỉ lệ NH3 phụ thuộc pH và nhiệt độ.
"""
from core.config import NH4_UNIT_SCALE


def nh3_fraction(pH: float, temp_c: float) -> float:
    """Tỉ lệ NH3 / tổng amoni theo Emerson (freshwater approximation).

    pKa = 0.09018 + 2729.92 / T(Kelvin)
    f   = 1 / (1 + 10^(pKa − pH))
    """
    t_kelvin = temp_c + 273.15
    pka = 0.09018 + 2729.92 / t_kelvin
    return 1.0 / (1.0 + 10 ** (pka - pH))


def emerson_nh3(nh4_raw: float, pH: float, temp_c: float, scale: float = None) -> float:
    """Quy đổi NH4 raw sensor → NH3 (mg/L).

    Parameters
    ----------
    nh4_raw : giá trị thô từ sensor
    pH, temp_c : đo cùng thời điểm
    scale : hệ số đơn vị (default config.NH4_UNIT_SCALE = 0.001 µg/L→mg/L)
    """
    if scale is None:
        scale = NH4_UNIT_SCALE
    nh4_mgL = max(0.0, nh4_raw) * scale
    return nh4_mgL * nh3_fraction(pH, temp_c)
