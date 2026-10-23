import numpy as np
import pandas as pd
import pytest

from core import disease_risk as dr


def _days(values, start="2026-07-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"), dtype=float)


def test_trapezoid_breakpoints_and_open_shoulder():
    t = np.array([14.0, 15.0, 18.75, 22.5, 26.0, 30.0, 31.25, 32.5, 34.0])
    mu = dr.trapezoid(t, (15.0, 22.5, 30.0, 32.5))
    assert list(np.round(mu, 3)) == [0, 0, 0.5, 1, 1, 1, 0.5, 0, 0]
    open_mu = dr.trapezoid(np.array([20.0, 22.5, 25.0, 40.0]), (20.0, 25.0, np.inf, np.inf))
    assert list(open_mu) == [0, 0.5, 1, 1]
    assert list(dr.trapezoid(np.array([34.0, 40.0]), (15.0, 21.0, 33.0, np.inf))) == [1, 1]  # finite c, open d
    assert np.isnan(dr.trapezoid(np.array([np.nan]), (15.0, 22.5, 30.0, 32.5))[0])


def test_group_memberships_at_cited_breakpoints():
    out = dr.daily_disease_risk(_days([20.0, 25.0, 26.5, 28.0, 29.0]))
    assert list(out["mu_vibrio"]) == [0, 1, 1, 1, 1]
    assert list(out["mu_streptococcus"]) == [0, 1, 1, 1, 0.5]
    assert out["mu_photobacterium"].iloc[1] == 1  # 25 C inside 22.5-30 optimum
    assert list(out["mu_amyloodinium"]) == [1, 1, 1, 1, 1]  # 18-30 C optimal reproduction


def test_cold_membership_and_run_escalation():
    temps = [16.0] * 15 + [25.0]
    out = dr.daily_disease_risk(_days(temps, start="2026-01-01"))
    mu = dr.cold_membership(np.array([15.0, 18.0, 22.0]))
    assert mu[0] == 1 and mu[2] == 0 and mu[1] == pytest.approx(4 / 7)
    assert out["cold_run_days"].iloc[13] == 14
    assert out["cold_risk"].iloc[12] == pytest.approx(dr.COLD_CAP_BEFORE_RUN)  # capped before 14 days
    assert out["cold_risk"].iloc[13] == pytest.approx(dr.cold_membership(np.array([16.0]))[0])
    assert out["cold_run_days"].iloc[15] == 0


def test_nan_day_stays_nan_and_breaks_cold_run():
    out = dr.daily_disease_risk(_days([16.0, np.nan, 16.0, 16.0]))
    assert np.isnan(out["index"].iloc[1]) and np.isnan(out["level"].iloc[1])
    assert list(out["cold_run_days"]) == [1, 0, 1, 2]


def test_absent_calendar_dates_become_nan_days():
    s = pd.Series([16.0, 16.0], index=pd.to_datetime(["2026-01-01", "2026-01-03"]))
    out = dr.daily_disease_risk(s)
    assert len(out) == 3 and np.isnan(out["temp_c"].iloc[1])


def test_index_bounds_levels_and_dominant_group():
    out = dr.daily_disease_risk(_days([10.0, 21.0, 23.0, 26.0, 40.0]))
    assert ((out["index"] >= 0) & (out["index"] <= 1)).all()
    assert out["level"].iloc[3] == 2 and out["dominant"].iloc[3] == "warm"
    # 21 C: vibrio 0.2, photobacterium 1, streptococcus 0, amyloodinium 1, cryptocaryon 1 -> mean 0.64
    assert out["warm_index"].iloc[1] == pytest.approx(0.64)
    assert out["warm_max"].iloc[1] == 1
    assert out["level"].iloc[1] == 1
    assert out["dominant"].iloc[0] == "cold" and out["level"].iloc[0] == 1  # 1 cold day: capped
    for lvl in (0, 1, 2):
        assert lvl in dr.LEVELS_VI


def test_rain_flag_rolling_three_days():
    temp = _days([20.0] * 6, start="2026-01-01")
    rain = _days([0.0, 60.0, 30.0, 20.0, 0.0, 0.0], start="2026-01-01")
    out = dr.daily_disease_risk(temp, rain_mm=rain)
    assert out["rain_3d_mm"].iloc[:2].isna().all()  # incomplete 3-day window -> unknown, not zero
    assert list(out["rain_3d_mm"].iloc[2:]) == [90, 110, 50, 20]
    assert list(out["heavy_rain_flag"]) == [False, False, False, True, False, False]
    assert out["index"].iloc[3] == pytest.approx(min(1.0, out["base_index"].iloc[3] + dr.STRESS_BUMP), abs=1e-4)
    assert out["index"].iloc[2] == pytest.approx(out["base_index"].iloc[2], abs=1e-4)
    no_rain = dr.daily_disease_risk(temp)
    assert not no_rain["heavy_rain_flag"].any() and no_rain["rain_3d_mm"].isna().all()


def test_rapid_change_flag():
    out = dr.daily_disease_risk(_days([28.0, 28.0, 27.0, 24.5, 24.5]))
    assert list(out["rapid_change_flag"]) == [False, False, False, True, True]
    assert out["temp_change_3d_c"].iloc[3] == pytest.approx(-3.5)


def test_shift_moves_all_breakpoints():
    base = dr.daily_disease_risk(_days([25.0]))
    shifted = dr.daily_disease_risk(_days([26.0]), shift_c=1.0)
    cols = [c for c in base.columns if c.startswith("mu_")]
    assert np.allclose(base[cols].to_numpy(), shifted[cols].to_numpy())


def test_latest_advisory_flags_and_label():
    out = dr.daily_disease_risk(_days([26.0, 27.0]))
    adv = dr.latest_advisory(out, source="sensor")
    assert adv["used_by_alerts"] is False and adv["notification_eligible"] is False
    assert adv["basis"] == "theory_only_unvalidated" and adv["source"] == "sensor"
    assert "không phải chẩn đoán" in adv["note_vi"]
    assert adv["date"] == "2026-07-02" and adv["level"] == 2
    empty = dr.latest_advisory(dr.daily_disease_risk(_days([np.nan])), source="sensor")
    assert empty["status"] == "unavailable" and empty["used_by_alerts"] is False
