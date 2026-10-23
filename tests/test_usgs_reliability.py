"""Unit tests for the USGS SF Bay direction-4 reliability script (synthetic, no network)."""
import numpy as np
import pandas as pd

from experiments.usgs_reliability import (
    build_strata,
    distance_bin,
    pair_table,
    rain_effect,
    regime_label,
    regime_medians,
    reliability_radius,
    season_of,
    standardised_ols,
    summarise,
    transfer_frame,
)


def test_season_and_bins():
    idx = pd.DatetimeIndex(["2020-11-01", "2020-04-30", "2020-05-01", "2020-10-31"])
    assert season_of(idx).tolist() == ["wet", "wet", "dry", "dry"]
    assert distance_bin([0.5, 2.0, 9.9, 19.9, 25, 31]).tolist() == ["0-2", "2-5", "5-10", "10-20", "20-30", ">30"]


def test_regime_threshold_strict():
    assert regime_label([1.99, 2.0, np.nan]).tolist() == ["same", "different", "unknown"]


def _wide(n_days=400):
    idx = pd.date_range("2019-01-01", periods=24 * n_days, freq="h")
    rng = np.random.default_rng(0)
    base = 20 + 5 * np.sin(np.arange(len(idx)) / 500)
    sal = pd.DataFrame({"a": base + rng.normal(0, 0.1, len(idx)), "b": base + 0.3, "c": base - 8}, index=idx)
    return {"Sal": sal, "Temp": sal / 2}


def test_regime_medians_and_pair_table():
    wide = _wide()
    med = regime_medians(wide["Sal"])
    assert abs(med.at["b", "sal_wet_median"] - med.at["a", "sal_wet_median"] - 0.3) < 0.05
    stations = pd.DataFrame({"site": ["a", "b", "c"], "code": ["A", "B", "C"], "lat": [37.8, 37.81, 38.0],
                             "lon": [-122.4, -122.4, -122.2]})
    pairs = pair_table(stations, wide)
    assert len(pairs) == 6
    ab = pairs[(pairs.anchor == "a") & (pairs.target == "b")].iloc[0]
    assert ab.regime == "same" and ab.distance_bin == "0-2" and ab.n_days_Sal == 401  # 400 UTC days span 401 LST (UTC-8) dates
    ac = pairs[(pairs.anchor == "a") & (pairs.target == "c")].iloc[0]
    assert ac.regime == "different" and ac.regime_overlap == "different"


def test_transfer_frame_calibration_fixes_offset():
    wide = _wide(60)
    f = transfer_frame(wide["Sal"]["a"], wide["Sal"]["c"], "Sal")
    assert f[f.transfer == "raw"]["within"].mean() == 0.0
    cal = f[f.transfer == "calibrated_30d"]
    assert cal.index.min() >= pd.Timestamp("2019-01-11")  # needs 240 past hours
    assert cal["within"].mean() > 0.95


def _counts(share_by_bin):
    rows = []
    for b, share in share_by_bin.items():
        for d in pd.date_range("2020-01-01", periods=40):
            rows.append({"var": "Temp", "regime": "same", "distance_bin": b, "transfer": "raw", "date": d,
                         "pair": b, "w": int(round(share * 24)), "n": 24, "abs_err": 1.0})
    return pd.DataFrame(rows)


def test_summarise_and_radius_skip_empty_bins():
    cells = summarise(_counts({"2-5": 1.0, "5-10": 0.97, "10-20": 0.5}), ["var", "regime", "distance_bin", "transfer"])
    assert cells.set_index("distance_bin").at["2-5", "gate95"] == "pass"
    rad = reliability_radius(cells, ["var", "regime", "transfer"]).set_index("gate")
    assert rad.at["gate80", "radius_km"] == 10.0 and rad.at["gate80", "first_populated_bin"] == "2-5"
    assert rad.at["gate80", "stop"] == "fail@10-20"
    cells2 = summarise(_counts({"0-2": 0.5, "2-5": 1.0}), ["var", "regime", "distance_bin", "transfer"])
    assert reliability_radius(cells2, ["var", "regime", "transfer"]).set_index("gate").at["gate80", "radius_km"] == 0.0


def test_standardised_ols_recovers_dominant_predictor():
    rng = np.random.default_rng(1)
    km, dsal = rng.uniform(0, 30, 50), rng.uniform(0, 10, 50)
    y = 0.9 - 0.05 * dsal + rng.normal(0, 0.01, 50)
    (b_km, b_ds), r2 = standardised_ols(y, km, dsal)
    assert abs(b_ds) > 10 * abs(b_km) and r2 > 0.9


def test_build_strata_rain_classes_use_prior_hours_only():
    hours = pd.date_range("2020-01-01", periods=100, freq="h")
    rain = pd.Series(0.0, index=hours)
    rain.iloc[50] = 15.0
    s = build_strata(hours, rain)
    assert s["rain24h"].iloc[50] == "none"  # the hour itself is not "prior"
    assert s["rain24h"].iloc[51] == "heavy" and s["rain24h"].iloc[74] == "heavy" and s["rain24h"].iloc[75] == "none"
    assert s["rain24h"].iloc[0] == "na"


def test_rain_effect_detects_drop():
    rows = []
    for i, d in enumerate(pd.date_range("2020-01-01", periods=60)):
        heavy = i % 2 == 0
        rows.append({"var": "Sal", "transfer": "raw", "regime": "same", "season": "wet", "date": d,
                     "rain24h": "heavy" if heavy else "none", "rain72h": "mid", "w": 12 if heavy else 22, "n": 24})
    eff = rain_effect(pd.DataFrame(rows))
    row = eff[(eff.contrast.str.startswith("prior24h")) & (eff.scope == "all")].iloc[0]
    assert row.diff_heavy_minus_none < -0.3 and row.significant


def test_radius_censored_when_no_farther_pairs():
    cells = summarise(_counts({"10-20": 1.0}), ["var", "regime", "distance_bin", "transfer"])
    rad = reliability_radius(cells, ["var", "regime", "transfer"]).set_index("gate")
    assert rad.at["gate80", "radius_km"] == 20.0 and rad.at["gate80", "stop"] == "no_pairs_beyond@10-20"
