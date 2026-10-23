"""Unit tests for the HK EPD spatial-reliability analogue (synthetic data, no network)."""
import numpy as np
import pandas as pd
import pytest

from experiments.hk_epd_reliability import (
    calibrated_estimates,
    climatology_past,
    distance_bin,
    haversine_km,
    match_pairs,
    parse_censored,
    prepare_output_dir,
    prior_rain_sum,
    relation_differences,
    reliability_radius,
    salinity_regime,
    season_of,
    summarise_cells,
    within_tolerance,
    zone_median_loo,
)


def test_parse_censored_keeps_detection_limit_and_substitutes_half():
    parsed = parse_censored(pd.Series(["0.004", "<0.001", 0.02, None]))
    assert parsed["censored"].tolist() == [False, True, False, False]
    assert parsed["dl"].iloc[1] == pytest.approx(0.001)
    assert parsed["value"].iloc[1] == pytest.approx(0.0005)
    assert parsed["value"].iloc[0] == pytest.approx(0.004)
    assert np.isnan(parsed["value"].iloc[3])


def test_within_tolerance_variables():
    assert within_tolerance("Temp", np.array([20.0, 20.0]), np.array([20.5, 20.6])).tolist() == [True, False]
    # TSS: max(2 mg/L, 20 % of observed)
    assert within_tolerance("TSS", np.array([10.0, 30.0, 30.0]), np.array([12.0, 37.0, 38.0])).tolist() == [True, True, False]
    # NH3: max(30 %, 0.005 mg/L absolute floor)
    assert within_tolerance("NH3", np.array([0.001, 0.02]), np.array([0.005, 0.03])).tolist() == [True, False]
    # strict relative-only row
    assert within_tolerance("NH3@rel30", np.array([0.001]), np.array([0.005])).tolist() == [False]


def test_haversine_and_bins_and_season():
    # 0.01 deg latitude ~ 1.11 km
    assert haversine_km(22.3, 114.2, 22.31, 114.2) == pytest.approx(1.112, abs=0.01)
    assert distance_bin(np.array([0.5, 2.0, 4.9, 7, 15, 25])).tolist() == ["0-2", "2-5", "2-5", "5-10", "10-20", ">20"]
    assert season_of(pd.to_datetime(["2020-03-31", "2020-04-01", "2020-09-30", "2020-10-01"])).tolist() == ["dry", "wet", "wet", "dry"]


def _obs(rows):
    return pd.DataFrame(rows, columns=["station", "date", "Temp"]).assign(date=lambda d: pd.to_datetime(d.date))


def test_match_pairs_prefers_lag0_then_anchor_earlier_and_respects_window():
    obs = _obs([
        ("A", "2020-01-08", 1.0), ("A", "2020-01-10", 2.0), ("A", "2020-01-12", 3.0),
        ("B", "2020-01-10", 9.0),          # A same day -> lag 0
        ("C", "2020-01-11", 8.0),          # A on 10 (lag +1) and 12 (lag -1): prefer anchor earlier
        ("D", "2020-01-20", 7.0),          # nearest A is 8 days away -> no match
    ])
    pairs = pd.DataFrame({"anchor": ["A", "A", "A"], "target": ["B", "C", "D"], "distance_km": [1.0, 2.0, 3.0],
                          "relation": ["same_zone"] * 3})
    m = match_pairs(obs, pairs, ["Temp"], max_lag_days=3)
    got = m.set_index("target")
    assert set(got.index) == {"B", "C"}
    assert got.loc["B", "lag_days"] == 0 and got.loc["B", "a_Temp"] == 2.0 and got.loc["B", "t_Temp"] == 9.0
    assert got.loc["C", "lag_days"] == 1 and got.loc["C", "a_Temp"] == 2.0


def test_calibrated_estimates_strictly_past_window():
    dates = pd.date_range("2018-01-15", periods=40, freq="30D")
    x = np.linspace(10, 30, len(dates)) + np.sin(np.arange(len(dates)))
    frame = pd.DataFrame({"anchor": "A", "target": "B", "target_date": dates, "x": x, "y": 2 * x + 1})
    shocked = frame.copy()
    shocked.loc[shocked.index[-1], "y"] = 1000.0
    est = calibrated_estimates(frame, window="730D", min_points=12)
    est_shocked = calibrated_estimates(shocked, window="730D", min_points=12)
    assert est.iloc[-1] == pytest.approx(est_shocked.iloc[-1])  # own value not used
    assert est.iloc[-1] == pytest.approx(frame["y"].iloc[-1], rel=1e-6)
    assert est.iloc[:12].isna().all()  # needs 12 past points
    # window: points older than 730 days are dropped -> a shock 3 years back has no influence
    old = frame.copy()
    old.loc[0, "y"] = -500.0
    assert calibrated_estimates(old, window="730D", min_points=12).iloc[-1] == pytest.approx(est.iloc[-1])


def test_zone_median_loo_excludes_target():
    obs = _obs([("A", "2020-01-10", 1.0), ("B", "2020-01-10", 2.0), ("C", "2020-01-10", 10.0), ("D", "2020-01-10", 50.0)])
    zones = {"A": "Z", "B": "Z", "C": "Z", "D": "Y"}
    out = zone_median_loo(obs, zones, "Temp").set_index("station")
    assert out.loc["A", "estimate"] == pytest.approx(6.0)   # median(2, 10)
    assert out.loc["C", "estimate"] == pytest.approx(1.5)
    assert "D" not in out.index                               # no other station in zone Y


def test_climatology_past_uses_only_prior_years_same_month():
    rows = [("A", f"{y}-07-10", float(y - 2010)) for y in range(2015, 2021)]
    obs = _obs(rows)
    out = climatology_past(obs, "Temp", min_years=3).set_index("date")
    assert pd.isna(out.loc[pd.Timestamp("2017-07-10"), "estimate"])        # only 2 prior years
    assert out.loc[pd.Timestamp("2018-07-10"), "estimate"] == pytest.approx(6.0)   # median(5,6,7)
    assert out.loc[pd.Timestamp("2020-07-10"), "estimate"] == pytest.approx(7.0)   # median(5..9)


def test_summarise_cells_bootstraps_over_dates_and_gates():
    rng = np.random.default_rng(0)
    dates = pd.date_range("2016-01-01", periods=40, freq="30D")
    rows = pd.DataFrame({"target_date": np.repeat(dates, 5), "cell": "x"})
    rows["within"] = True
    rows["err"] = rng.normal(0, 0.1, len(rows))
    out = summarise_cells(rows, ["cell"]).iloc[0]
    assert out["n_dates"] == 40 and out["share_within"] == 1.0
    assert out["gate_95"] == "pass"
    few = summarise_cells(rows[rows.target_date < dates[10]], ["cell"]).iloc[0]
    assert few["gate_80"] == "insufficient"


def test_reliability_radius_is_contiguous_from_zero():
    cells = pd.DataFrame({
        "variable": "Temp", "distance_bin": ["0-2", "2-5", "5-10", "10-20", ">20"],
        "gate_80": ["pass", "pass", "fail", "pass", "pass"],
    })
    assert reliability_radius(cells, ["variable"], "gate_80").iloc[0]["radius"] == "5 km"
    cells["gate_80"] = ["fail"] + ["pass"] * 4
    assert reliability_radius(cells, ["variable"], "gate_80").iloc[0]["radius"] == "0 km"
    cells["gate_80"] = ["pass"] * 5
    assert reliability_radius(cells, ["variable"], "gate_80").iloc[0]["radius"] == ">20 km"
    cells["gate_80"] = ["insufficient"] + ["pass"] * 4
    assert reliability_radius(cells, ["variable"], "gate_80").iloc[0]["radius"] == "insufficient"


def test_prior_rain_sum_excludes_sampling_day():
    rain = pd.Series([1.0, 2.0, 4.0, 100.0], index=pd.date_range("2020-01-01", periods=4))
    got = prior_rain_sum(rain, pd.to_datetime(["2020-01-04", "2020-01-02"]), days=3)
    assert got.iloc[0] == pytest.approx(7.0)
    assert np.isnan(got.iloc[1])  # incomplete window


def test_prepare_output_dir_refuses_overwrite(tmp_path):
    target = tmp_path / "run"
    prepare_output_dir(target)
    with pytest.raises(FileExistsError):
        prepare_output_dir(target)


def test_salinity_regime_uses_wet_season_median():
    obs = pd.DataFrame({"station": ["A", "A", "B", "C"],
                        "date": pd.to_datetime(["2020-07-01", "2020-01-01", "2020-07-01", "2020-07-01"]),
                        "Sal": [30.0, 10.0, 29.0, 20.0]})
    pairs = pd.DataFrame({"anchor": ["A", "A"], "target": ["B", "C"]})
    out = salinity_regime(obs, pairs, threshold_psu=2.0)
    assert out["regime_relation"].tolist() == ["similar_regime", "different_regime"]   # dry 10 psu ignored


def test_relation_differences_lag0_only():
    dates = pd.date_range("2016-01-01", periods=20, freq="30D")
    rows = pd.DataFrame({"target_date": np.tile(dates, 2), "relation": ["same_zone"] * 20 + ["cross_zone"] * 20,
                         "within": [True] * 20 + [False] * 20, "lag_days": 0, "variable": "Temp",
                         "method": "persistence_in_space", "season": "dry", "distance_bin": "0-2"})
    lagged = rows.assign(lag_days=2, within=True)
    out = relation_differences(pd.concat([rows, lagged]))
    row = out[(out.season == "all")].iloc[0]
    assert row["diff_a_minus_b"] == pytest.approx(1.0) and row["rows_a"] == 20
