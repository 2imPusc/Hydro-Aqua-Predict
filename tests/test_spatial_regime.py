"""Unit tests for the H4.1 salinity-regime / regime-split P0-P1 script (synthetic data)."""
import numpy as np
import pandas as pd
import pytest

from experiments import spatial_regime as sr


def test_vn2000_meridian_is_per_province():
    # HP NB1 (Cat Ba): only lon_0 = 105.75 lands near 107.04 E; 107.75 would put it ~200 km east.
    lat, lon = sr.vn2000_to_wgs84([2292268.0], [634641.0], 105.75)
    assert lat[0] == pytest.approx(20.718, abs=0.01)
    assert lon[0] == pytest.approx(107.045, abs=0.01)
    _, lon_wrong = sr.vn2000_to_wgs84([2292268.0], [634641.0], 107.75)
    assert lon_wrong[0] > 108.5
    # QN NB1 (Bai Chay) with 107.75
    lat_q, lon_q = sr.vn2000_to_wgs84([2318587.0], [428692.0], 107.75)
    assert 20.9 < lat_q[0] < 21.0 and 107.0 < lon_q[0] < 107.1


def test_coordinate_suspect_flagged_by_province_box():
    assert sr.in_bbox([20.95, 19.37], [107.06, 107.39], sr.PROVINCE_BBOX["quangninh"]).tolist() == [True, False]


def test_classify_regime_cut_offs():
    out = sr.classify_regime([10.0, 19.99, 20.0, 27.9, 28.0, 33.0, np.nan])
    assert out.tolist() == ["estuarine_brackish", "estuarine_brackish", "transitional", "transitional",
                            "marine", "marine", "unknown"]


def test_regime_relation_threshold_two_psu():
    assert sr.regime_relation([30.0, 30.0, np.nan], [31.9, 32.0, 30.0]).tolist() == ["same_regime", "different_regime", "unknown"]


def _frame():
    dates = pd.to_datetime(["2021-01-01", "2021-07-01", "2022-01-01", "2022-07-01", "2023-01-01", "2023-07-01"])
    rows = []
    for station, x, base_sal in (("A", 0.0, 30.0), ("B", 1500.0, 30.5), ("C", 8000.0, 15.0)):
        for i, d in enumerate(dates):
            wet = d.month == 7
            rows.append({"station": station, "date": d, "X": 2_300_000.0 + x, "Y": 450_000.0,
                         "Salinity": base_sal - (3.0 if wet else 0.0), "Temperature": 25.0 + i * 0.1 + x / 10_000,
                         "pH": 8.0, "DO": 6.5, "coordinate_suspect": False, "region": "test",
                         "lat": 20.8, "lon": 107.0 + x / 100_000})
    return pd.DataFrame(rows)


def test_station_regime_uses_wet_months_and_flags_source():
    reg = sr.station_regime(_frame()).set_index("station")
    assert reg.loc["A", "wet_median_sal"] == pytest.approx(27.0)
    assert reg.loc["A", "dry_median_sal"] == pytest.approx(30.0)
    assert reg.loc["C", "regime_class"] == "estuarine_brackish"
    assert (reg["salinity_source"] == "observed").all()


def test_transfer_rows_estimate_is_anchor_value_and_hsi_from_anchor_only():
    frame = _frame()
    reg = sr.station_regime(frame)
    rows = sr.transfer_rows(frame, reg, ["Salinity", "Temperature", "pH", "DO"])
    sal = rows[(rows.variable == "Salinity") & (rows.anchor == "A") & (rows.target == "C")]
    assert (sal["estimate"] - sal["y"]).abs().min() == pytest.approx(15.0)
    assert set(sal["regime_relation"]) == {"different_regime"}
    ab = rows[(rows.variable == "Salinity") & (rows.anchor == "A") & (rows.target == "B")]
    assert set(ab["regime_relation"]) == {"same_regime"} and set(ab["distance_bin"]) == {"0-2"}
    # Perturbing the target's values must not change the HSI estimate for that target.
    perturbed = frame.copy()
    perturbed.loc[perturbed.station == "C", ["Salinity", "pH", "DO", "Temperature"]] = [1.0, 6.0, 1.0, 35.0]
    rows2 = sr.transfer_rows(perturbed, reg, ["Salinity", "Temperature", "pH", "DO"])
    key = ["anchor", "target", "target_date"]
    h1 = rows[(rows.variable == "HSI") & (rows.target == "C")].set_index(key)["estimate"].sort_index()
    h2 = rows2[(rows2.variable == "HSI") & (rows2.target == "C")].set_index(key)["estimate"].sort_index()
    pd.testing.assert_series_equal(h1, h2)


def test_gate_insufficient_below_thirty_dates_and_relaxed_is_separate():
    dates = pd.date_range("2021-01-01", periods=16, freq="QS")
    rows = pd.DataFrame({"target_date": np.repeat(dates, 5), "anchor": "A", "target": "B", "within": True,
                         "err": 0.0, "variable": "pH", "regime_relation": "same_regime", "distance_bin": "0-2"})
    cells = sr.summarise_cells(rows, ["variable", "regime_relation", "distance_bin"], n_boot=200)
    assert cells.loc[0, "gate_80"] == "insufficient"
    assert cells.loc[0, "diagnostic_relaxed_80"] == "pass"


def test_climatology_is_leave_one_year_out():
    frame = _frame()
    clim = sr.climatology_loyo(frame, ["Temperature"])
    a = clim[(clim.target == "A") & (clim.target_date == pd.Timestamp("2022-01-01"))]["clim"].iloc[0]
    # other Januaries of A: 2021 (i=0) and 2023 (i=4) -> median of 25.0 and 25.4
    assert a == pytest.approx(25.2)


def test_within_tolerance_relative_floor():
    assert sr.within_tolerance("TSS", [10.0, 30.0], [12.0, 38.0]).tolist() == [True, False]
    assert sr.within_tolerance("NH3", [0.001, 0.02], [0.005, 0.03]).tolist() == [True, False]


def test_fast_conformal_matches_spatial_applicability():
    from experiments import spatial_applicability as sa
    rng = np.random.default_rng(0)
    rows = []
    for d in pd.date_range("2020-01-01", periods=10, freq="QS"):
        for i, st in enumerate("ABCDEF"):
            rows.append({"Station": st, "observed_at": d, "X": 2_300_000.0 + i * 1500, "Y": 450_000.0 + i * 700,
                         "DO": 6 + rng.normal(0, .3)})
    pairs = sa.pairwise_anchor_copy(pd.DataFrame(rows), "DO")
    _, original = sa.error_bound_benchmarks(pairs, ["DO"])
    fast = sr.fast_error_bound_benchmarks(pairs, ["DO"])
    keys = ["split", "parameter", "model", "distance_bin_km", "coverage_target"]
    merged = original.merge(fast, on=keys, suffixes=("_o", "_f"))
    assert len(merged) == len(original) == len(fast) > 0
    np.testing.assert_allclose(merged.empirical_coverage_o, merged.empirical_coverage_f)
    np.testing.assert_allclose(merged.mean_bound_o, merged.mean_bound_f)
