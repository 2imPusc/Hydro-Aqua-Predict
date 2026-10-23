"""Unit tests for the MD DNR ConMon direction-4 reliability script (synthetic, no network)."""
import numpy as np
import pandas as pd
import pytest

from experiments import mddnr_reliability as mr


def test_distance_bins_include_20_30_and_beyond():
    assert mr.distance_bin([0, 1.99, 2, 9.9, 19.9, 20, 29.99, 30, 45]).tolist() == [
        "0-2", "0-2", "2-5", "5-10", "10-20", "20-30", "20-30", ">30", ">30"]


def test_overlap_days_and_tier():
    idx = pd.date_range("2006-06-01", periods=24 * 5, freq="h")
    a = pd.Series(1.0, index=idx)
    b = pd.Series(np.where(idx.day == 3, np.nan, 2.0), index=idx)
    assert mr.overlap_days(a, b) == 4
    assert mr.overlap_tier(400) == "365d" and mr.overlap_tier(120) == "90d" and mr.overlap_tier(30) == "below"


def test_station_regimes_and_labels():
    idx = pd.date_range("2006-01-01", "2006-12-31 23:00", freq="h")
    sal = pd.DataFrame({"fresh": 0.2, "meso": np.where(idx.month.isin([4, 5, 6]), 8.0, 12.0)}, index=idx)
    reg = mr.station_regimes(sal)
    assert reg.loc["meso", "sal_spring_median"] == pytest.approx(8.0)
    assert reg.loc["meso", "sal_late_median"] == pytest.approx(12.0)
    assert mr.regime_label([0.5, 2.0, np.nan]).tolist() == ["same", "different", "unknown"]


def test_season_and_rain_class():
    assert mr.season_of(pd.to_datetime(["2006-01-15", "2006-04-01", "2006-07-01", "2006-10-01"])).tolist() == [
        "DJF", "MAM", "JJA", "SON"]
    total = pd.Series([np.nan, 0.5, 5.0, 12.0])
    assert mr.rain_class(total, heavy=10.0).tolist() == ["na", "none", "light", "heavy"]


def _cells(statuses):
    return pd.DataFrame({"dataset": "mddnr", "var": "Temp", "regime": "same", "transfer": "raw",
                         "distance_bin": list(statuses), "gate80": list(statuses.values())})


def test_reliability_radius_skips_insufficient_and_stops_at_fail():
    cells = _cells({"0-2": "insufficient", "2-5": "pass", "5-10": "pass", "10-20": "fail", "20-30": "pass"})
    r = mr.reliability_radius(cells, ["dataset", "var", "regime", "transfer"], "gate80").iloc[0]
    assert r["radius_km"] == 10.0 and r["stop"] == "fail@10-20" and r["n_skipped"] == 1
    cells = _cells({"0-2": "fail", "2-5": "pass"})
    assert mr.reliability_radius(cells, ["dataset", "var", "regime", "transfer"], "gate80").iloc[0]["radius_km"] == 0.0
    cells = _cells({"0-2": "insufficient"})
    assert np.isnan(mr.reliability_radius(cells, ["dataset", "var", "regime", "transfer"], "gate80").iloc[0]["radius_km"])


def test_pair_day_table_raw_and_calibrated_counts():
    idx = pd.date_range("2006-05-01", periods=24 * 40, freq="h")
    x = pd.Series(20 + np.sin(np.arange(len(idx)) / 5.0), index=idx)
    y = x + 1.0  # constant offset: raw fails Temp 0.5, calibrated recovers it
    strata = pd.DataFrame({"daynight": np.where(idx.hour < 12, "night", "day"),
                           "rain24": "none", "rain72": "heavy"}, index=idx)
    out = mr.pair_day_table(x, y, "Temp", strata)
    assert out["raw"]["w"].sum() == 0 and out["raw"]["n"].sum() == len(idx)
    cal = out["calibrated"]
    assert cal["n"].sum() == len(idx) - 240  # first 10 days have no strictly-past fit
    assert cal["w"].sum() == cal["n"].sum()
    assert out["raw"]["n_night"].sum() == len(idx) // 2 and out["raw"]["n_r72heavy"].sum() == len(idx)


def test_ols_and_logit_standardised_recover_dominant_covariate():
    rng = np.random.default_rng(0)
    X = pd.DataFrame({"km": rng.uniform(0, 30, 200), "dsal": rng.uniform(0, 10, 200)})
    y = 0.9 - 0.06 * X["dsal"] - 0.001 * X["km"] + rng.normal(0, 0.01, 200)
    ols = mr.ols_standardised(y, X)
    assert abs(ols["coef_dsal"]) > 5 * abs(ols["coef_km"]) and ols["r2"] > 0.9
    logit = mr.logit_standardised((y >= 0.6).astype(int), X)
    assert logit["coef_dsal"] < 0 and abs(logit["coef_dsal"]) > abs(logit["coef_km"])
    assert mr.logit_standardised(np.ones(5), X.iloc[:5])["status"] == "no_variation"


def test_cell_table_gates_need_30_days():
    dates = pd.date_range("2006-06-01", periods=20, freq="D")
    days = pd.DataFrame({"date": dates, "n": 24, "w": 24, "sae": 1.0, "pair_id": 0, "variable": "Temp"})
    cell = mr.cell_table(days, ["variable"]).iloc[0]
    assert cell["share"] == 1.0 and cell["gate80"] == "insufficient"
    days = pd.DataFrame({"date": pd.date_range("2006-06-01", periods=40, freq="D"), "n": 24, "w": 24,
                         "sae": 1.0, "pair_id": 0, "variable": "Temp"})
    assert mr.cell_table(days, ["variable"]).iloc[0]["gate95"] == "pass"


def test_era5_cell_snaps_to_quarter_degree():
    assert mr.era5_cell(38.79, -76.71) == (38.75, -76.75)


def test_regime_beats_distance_requires_negative_dsal_effect():
    assert mr.regime_beats_distance(-0.04, -0.02)
    assert not mr.regime_beats_distance(0.04, -0.02)  # wrong sign: more dsal -> more reliable
    assert not mr.regime_beats_distance(-0.01, -0.02)
