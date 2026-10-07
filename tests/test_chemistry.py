# lab/realtime_greenlab/tests/test_chemistry.py
import math
from core.chemistry import emerson_nh3, nh3_fraction

def test_nh3_fraction_range():
    f = nh3_fraction(pH=7.95, temp_c=30.0)
    assert 0.0 < f < 1.0

def test_nh3_fraction_increases_with_ph():
    f_low  = nh3_fraction(pH=7.0, temp_c=30.0)
    f_high = nh3_fraction(pH=8.5, temp_c=30.0)
    assert f_high > f_low   # pH cao → nhiều NH3 hơn

def test_nh3_fraction_increases_with_temp():
    f_cold = nh3_fraction(pH=7.95, temp_c=20.0)
    f_warm = nh3_fraction(pH=7.95, temp_c=35.0)
    assert f_warm > f_cold

def test_emerson_known_value():
    # NH4 raw=114.59, scale default 0.001, pH=7.95, T=30 → ~0.0077 mg/L
    nh3 = emerson_nh3(nh4_raw=114.59, pH=7.95, temp_c=30.0, scale=0.001)
    assert abs(nh3 - 0.0077) < 0.002

def test_emerson_scale_flips_magnitude():
    nh3_ug = emerson_nh3(nh4_raw=114.59, pH=7.95, temp_c=30.0, scale=0.001)
    nh3_mg = emerson_nh3(nh4_raw=114.59, pH=7.95, temp_c=30.0, scale=1.0)
    assert nh3_mg > nh3_ug * 900   # scale 1000× → NH3 ~1000×

def test_emerson_nonnegative():
    assert emerson_nh3(nh4_raw=0.0, pH=7.95, temp_c=30.0) == 0.0
