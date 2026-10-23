import math

import numpy as np
import pytest

from core import site_exposure as se

G = 9.81


def _u10_for_ua(ua):
    return (ua / 0.71) ** (1 / 1.23)


def test_wind_stress_factor_spm_3_28a():
    assert se.wind_stress_factor(10.0) == pytest.approx(0.71 * 10 ** 1.23)


def test_deep_water_matches_spm_example():
    # SPM 1984 p. 3-47: U_A = 20 m/s, F = 30 km -> fetch-limited H "can only be 1.75 m" (nomogram);
    # eq. 3-33 gives 1.77 m.
    h, t = se.spm_deep_wave(_u10_for_ua(20.0), 30_000.0)
    assert h == pytest.approx(1.77, abs=0.03)
    assert t == pytest.approx(0.2857 * 20 / G * (G * 30_000 / 400) ** (1 / 3), rel=1e-3)


def test_deep_water_capped_at_fully_developed():
    u = 20.0
    ua = se.wind_stress_factor(u)
    h, t = se.spm_deep_wave(u, 5e7)
    assert h == pytest.approx(0.2433 * ua ** 2 / G, rel=1e-6)
    assert t == pytest.approx(8.134 * ua / G, rel=1e-6)


def test_shallow_tends_to_deep_for_large_depth_short_fetch():
    hd, _ = se.spm_deep_wave(15.0, 5_000.0)
    hs, _ = se.spm_shallow_wave(15.0, 5_000.0, 500.0)
    assert hs == pytest.approx(hd, rel=0.05)


def test_shallow_water_limits_height():
    hd, _ = se.spm_deep_wave(25.0, 50_000.0)
    hs, _ = se.spm_shallow_wave(25.0, 50_000.0, 5.0)
    assert hs < 0.7 * hd


def test_fetch_wave_duration_limit():
    long_dur = se.fetch_wave(25.0, 100_000.0, 20.0, duration_h=48)
    short_dur = se.fetch_wave(25.0, 100_000.0, 20.0, duration_h=1)
    assert short_dur["hs_m"] < long_dur["hs_m"]
    assert short_dur["limited_by"] == "duration"
    assert long_dur["limited_by"] == "fetch"


def test_fetch_wave_zero_inputs():
    assert se.fetch_wave(0.0, 10_000.0, 10.0)["hs_m"] == 0.0
    assert se.fetch_wave(20.0, 0.0, 10.0)["hs_m"] == 0.0


def test_saville_effective_fetch_urs_example():
    # Western Dam Engineering / TR-69 worked example (Table 2): 15 radials at 6 deg, F_e = 27.02 / 13.51 = 2.0 mi
    radials = [1.7, 1.8, 1.9, 2.0, 2.2, 2.3, 2.4, 2.6, 2.5, 2.4, 2.3, 2.1, 2.0, 1.8, 1.7]
    offsets = np.arange(-42, 43, 6)
    # the example rounds cos to 2 decimals (27.02 / 13.51); exact cosines give 1.97
    assert se.saville_effective_fetch(radials, offsets) == pytest.approx(2.0, abs=0.04)


def test_shelter_factor_solid_fence_curve():
    assert se.shelter_factor(10 * 100.0, 100.0) == pytest.approx(0.70)
    assert se.shelter_factor(15 * 100.0, 100.0) == pytest.approx(0.90)
    assert se.shelter_factor(40 * 100.0, 100.0) == pytest.approx(1.0)
    assert se.shelter_factor(2 * 100.0, 100.0) == pytest.approx(se.SHELTER_FLOOR)
    assert se.shelter_factor(1000.0, 0.0) == 1.0


def test_ray_shelter_takes_most_sheltering_obstacle():
    dist = np.array([500.0, 1000.0, 3000.0])
    elev = np.array([0.0, 50.0, 300.0])  # x/H = 20 (0.95) and 10 (0.70)
    out = se.ray_shelter(dist, elev)
    assert out["factor"] == pytest.approx(0.70)
    assert out["obstacle_height_m"] == 300.0
    assert out["obstacle_distance_m"] == 3000.0
    assert out["max_elevation_angle_deg"] == pytest.approx(math.degrees(math.atan(300 / 3000)))


def test_ray_fetch_direction_convention_and_censoring():
    lon0, lat0 = 107.0, 20.7
    # water everywhere west of a coast 10 km east of the site, mask extent 0.5 deg
    km_per_deg = 111.32 * math.cos(math.radians(lat0))
    coast = lon0 + 10 / km_per_deg

    def is_water(lon, lat):
        return np.asarray(lon) < coast

    extent = (lon0 - 0.5, lat0 - 0.5, lon0 + 0.5, lat0 + 0.5)
    res = se.ray_fetch(is_water, lon0, lat0, [90.0, 270.0], step_m=100.0, max_m=200_000.0, extent=extent)
    assert res["fetch_m"][0] == pytest.approx(10_000, abs=150)
    assert not res["censored"][0]
    # westward ray leaves the mask extent (~52 km) before hitting land -> censored, fetch set to cap
    assert res["censored"][1]
    assert res["fetch_m"][1] == 200_000.0


def test_fetch_for_wind_from_uses_upwind_rays():
    # wind FROM the east (90) blows over the water lying east of the site
    table = {"bearing": [0.0, 90.0, 180.0, 270.0], "fetch_m": [1.0, 10.0, 2.0, 3.0]}
    assert se.interp_direction(table["bearing"], table["fetch_m"], 90.0) == 10.0
    assert se.interp_direction(table["bearing"], table["fetch_m"], 45.0) == pytest.approx(5.5)
    assert se.interp_direction(table["bearing"], table["fetch_m"], 315.0) == pytest.approx(2.0)


def test_wave_and_current_classes_ns9415():
    assert [se.wave_class(h) for h in (0.2, 0.7, 1.5, 2.5, 3.5)] == list("ABCDE")
    assert [se.current_class(v) for v in (0.1, 0.4, 0.7, 1.2, 1.8)] == list("abcde")
    assert se.wave_class(None) is None


def test_risk_tier_combination():
    assert se.risk_tier(10.0, 0.3, 0.2)["tier"] == 0
    assert se.risk_tier(18.0, 0.3, 0.2)["tier"] == 2       # wind cap 8
    assert se.risk_tier(12.0, 1.4, 0.2)["tier"] == 2       # wave class C drives
    assert se.risk_tier(12.0, 1.4, 1.1)["tier"] == 3       # strong current bumps
    assert se.risk_tier(40.0, 4.0, 2.0)["tier"] == 4       # capped
    assert se.risk_tier(10.0, 0.3, 1.2)["tier"] == 0       # current alone does not raise a calm site


def test_rankine_direction_northern_hemisphere():
    # site due east of the centre: cyclonic flow blows toward the north, inflow turns it toward the centre
    d = se.cyclone_wind_from(20.0, 107.0, 20.0, 108.0, inflow_deg=20.0)
    assert d == pytest.approx(160.0, abs=1.0)
    d0 = se.cyclone_wind_from(20.0, 107.0, 20.0, 108.0, inflow_deg=0.0)
    assert d0 == pytest.approx(180.0, abs=1.0)


def _profile():
    bearings = np.arange(16) * 22.5
    return {
        "bearing": bearings,
        "fetch_m": np.where(bearings == 180.0, 40_000.0, 2_000.0),
        "depth_m": np.full(16, 10.0),
        "shelter": np.where(bearings == 0.0, 0.6, 1.0),
    }


def test_evaluate_site_wind_flags_and_shelter():
    prof = _profile()
    south = se.evaluate_site(25.0, 180.0, prof, current_ms=0.3)
    north = se.evaluate_site(25.0, 0.0, prof, current_ms=0.3)
    assert south["local_wind_ms"] == pytest.approx(25.0)
    assert north["local_wind_ms"] == pytest.approx(15.0)
    assert south["hs_m"] > north["hs_m"]
    assert south["tier"] >= north["tier"]
    for key, val in (("used_by_alerts", False), ("notification_eligible", False),
                     ("basis", "theory_only_unvalidated")):
        assert south[key] == val


def test_evaluate_site_missing_wind():
    out = se.evaluate_site(None, 90.0, _profile())
    assert out["status"] == "unavailable"
    assert out["used_by_alerts"] is False
