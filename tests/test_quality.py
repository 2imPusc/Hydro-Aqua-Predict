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


# ---- pH plausibility (probe drift from 2026-09-19, research log RL-13) -------
from core.config import PH_PLAUSIBLE_BAND, PH_MAX_CHANGE_PER_HOUR, PH_DAY_MAX_OUT_OF_BAND_FRACTION
from core.quality import ph_in_band, ph_rate_suspect, ph_reading_suspect


def _ph_day(values, start="2026-09-01T00:00:00Z"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="min"))


def _diurnal(n=1440, lo=7.6, hi=8.2, seed=0):
    t = np.arange(n)
    base = (lo + hi) / 2 + (hi - lo) / 2 * np.sin(2 * np.pi * t / 1440)
    return np.round(base + np.random.default_rng(seed).normal(0, 0.01, n), 2)


def test_ph_band_constants():
    assert PH_PLAUSIBLE_BAND == (7.0, 8.6)
    assert PH_MAX_CHANGE_PER_HOUR == 0.5
    assert 0 < PH_DAY_MAX_OUT_OF_BAND_FRACTION < 0.5


def test_ph_in_band():
    assert ph_in_band(7.0) and ph_in_band(8.6) and ph_in_band(7.9)
    assert not ph_in_band(6.9) and not ph_in_band(8.7) and not ph_in_band(float("nan"))


def test_ph_out_of_band_is_suspect_not_invalid():
    assert is_in_range("pH", 6.8)                        # hard range unchanged
    assert check_series("pH", pd.Series(_diurnal() - 1.1)) == "VALID"
    r = sensor_day_health("pH", _ph_day(_diurnal(lo=6.6, hi=7.0)))
    assert r["status"] == "SUSPECT" and "ph_median_out_of_band" in r["reasons"]


def test_ph_normal_diurnal_ok():
    r = sensor_day_health("pH", _ph_day(_diurnal()))
    assert r["status"] == "OK" and r["reasons"] == []
    assert r["metrics"]["oob_fraction"] == 0 and r["metrics"]["rate_jumps"] == 0


def test_ph_out_of_range_majority_still_invalid():
    r = sensor_day_health("pH", pd.Series([3.0] * 150 + [7.5] * 50))
    assert r["status"] == "INVALID" and "out_of_range" in r["reasons"]


def test_ph_partial_out_of_band_fraction_suspect():
    v = _diurnal()
    v[:216] = 6.8                                         # 15 % of the day below 7.0, median in band
    r = sensor_day_health("pH", _ph_day(v))
    assert r["status"] == "SUSPECT"
    assert "ph_out_of_band_fraction" in r["reasons"] and "ph_median_out_of_band" not in r["reasons"]


def test_ph_small_out_of_band_fraction_ok():
    v = _diurnal()
    v[:60] = 6.95                                         # ~4 %: below the day threshold
    assert sensor_day_health("pH", _ph_day(v))["status"] == "OK"


def test_ph_rate_rule_flags_jump_within_hour():
    v = np.full(180, 7.9)
    v[90:] = 7.2                                          # 0.7 step
    flags = ph_rate_suspect(_ph_day(v))
    assert flags.iloc[90:150].all() and not flags.iloc[:90].any() and not flags.iloc[151:].any()


def test_ph_rate_rule_slow_change_ok():
    s = _ph_day(np.linspace(7.6, 8.2, 1440))            # 0.6 per day
    assert not ph_rate_suspect(s).any()


def test_ph_rate_rule_needs_datetime_index():
    flags = ph_rate_suspect(pd.Series([7.9] * 50 + [7.0] * 50))
    assert not flags.any()
    r = sensor_day_health("pH", pd.Series(_diurnal()))   # integer index: no error, rate skipped
    assert r["status"] == "OK" and r["metrics"]["rate_jumps"] is None


def test_ph_reading_suspect_combines_band_and_rate():
    v = np.full(180, 7.9)
    v[10] = 6.8
    v[120:] = 7.3
    flags = ph_reading_suspect(_ph_day(v))
    assert flags.iloc[10] and flags.iloc[120] and not flags.iloc[0] and not flags.iloc[100]


def test_non_ph_params_have_no_ph_rules():
    r = sensor_day_health("TSS", _ph_day(_noisy(base=5.0, sd=0.5)))
    assert "oob_fraction" not in r["metrics"]
