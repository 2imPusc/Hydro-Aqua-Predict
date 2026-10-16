# lab/realtime_greenlab/tests/test_quality.py
import pandas as pd
from core.quality import is_in_range, check_series, filter_valid_rows

def test_in_range_ok():
    assert is_in_range("pH", 7.5) is True

def test_in_range_cod_rail_rejected():
    assert is_in_range("COD", 558.8) is False   # ngoài (0,100)

def test_in_range_cod_healthy():
    assert is_in_range("COD", 9.8) is True

def test_unknown_param_passes():
    assert is_in_range("Unknown", 12345) is True   # không có range → bỏ qua

def test_check_series_flatline_rail():
    # 100 readings dính cứng 558.8 → INVALID
    s = pd.Series([558.8] * 100)
    status = check_series("COD", s)
    assert status == "INVALID"

def test_check_series_healthy():
    s = pd.Series([8.5, 9.0, 10.2, 9.8, 11.0])
    status = check_series("COD", s)
    assert status == "VALID"

def test_check_series_stuck_at_zero_is_flatline():
    # Sensor dính cứng đúng 0.0 (mean == 0 nên CV không xét được) → INVALID
    s = pd.Series([0.0] * 10)
    assert check_series("COD", s) == "INVALID"

def test_check_series_varying_with_zeros_valid():
    # Có số 0 nhưng chuỗi vẫn dao động → không phải flatline
    s = pd.Series([0, 0.5, 1.2, 0, 2.0, 0.3])
    assert check_series("COD", s) == "VALID"

def test_check_series_few_zeros_keeps_valid():
    # < 5 điểm: quá ít để kết luận flatline → giữ hành vi cũ (VALID)
    s = pd.Series([0.0, 0.0, 0.0])
    assert check_series("COD", s) == "VALID"

def test_check_series_empty():
    assert check_series("COD", pd.Series([], dtype=float)) == "INVALID"

def test_filter_valid_rows_drops_out_of_range():
    df = pd.DataFrame({
        "COD": [9.0, 558.8, 10.0],
        "pH":  [7.5, 7.6, 20.0],     # 20 ngoài dải pH
    })
    out = filter_valid_rows(df, ["COD", "pH"])
    # Row 0 hợp lệ; row 1 COD rail; row 2 pH out → chỉ row 0 còn
    assert len(out) == 1
    assert out.iloc[0]["COD"] == 9.0


# ---- sensor_day_health -------------------------------------------------------
import numpy as np
from core.quality import sensor_day_health


def _noisy(n=1440, base=20.0, sd=3.0, seed=0):
    return pd.Series(np.round(base + np.random.default_rng(seed).normal(0, sd, n), 2))


def test_health_normal_noisy_ok():
    r = sensor_day_health("TSS", _noisy())
    assert r["status"] == "OK" and r["reasons"] == []


def test_health_flatline_invalid():
    r = sensor_day_health("COD", pd.Series([558.8] * 200))
    assert r["status"] == "INVALID"


def test_health_out_of_range_majority_invalid():
    r = sensor_day_health("pH", pd.Series([3.0] * 150 + [7.5] * 50))
    assert r["status"] == "INVALID" and "out_of_range" in r["reasons"]


def test_health_empty_invalid():
    assert sensor_day_health("TSS", pd.Series([], dtype=float))["status"] == "INVALID"


def test_health_tss_floor_stuck_suspect():
    # Few distinct values, long identical runs, tiny CV (the 2026-10-06..10 TSS pattern)
    rng = np.random.default_rng(1)
    s = pd.Series(np.repeat(rng.choice([2.8, 2.9, 3.0], 48, p=[.1, .8, .1]), 30))
    r = sensor_day_health("TSS", s)
    assert r["status"] == "SUSPECT" and "low_information" in r["reasons"]


def test_health_few_points_not_suspect():
    r = sensor_day_health("TSS", pd.Series([2.9, 2.9, 2.9, 3.0, 2.9, 2.9, 3.0]))
    assert r["status"] == "OK"


def test_health_check_series_unchanged():
    assert check_series("TSS", pd.Series([2.9] * 100)) == "INVALID"   # behaviour of old API untouched
