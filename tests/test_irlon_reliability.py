"""Unit tests for the IRLON direction-4 reliability script (synthetic data, no network)."""
import numpy as np
import pandas as pd

from experiments import irlon_reliability as ir


def _hours(days, start="2020-01-01"):
    return pd.date_range(start, periods=24 * days, freq="h")


def test_within_core_and_nutrient_floor():
    assert ir.within("Temp", [10.4], [10.0])[0] and not ir.within("Temp", [10.6], [10.0])[0]
    # nutrients: max(floor, 30 %) -> near-zero nitrate uses the 2 umol/L floor
    assert ir.within("NO3", [1.9], [0.0])[0] and not ir.within("NO3", [2.1], [0.0])[0]
    assert ir.within("NO3", [12.9], [10.0])[0] and not ir.within("NO3", [13.1], [10.0])[0]
    assert ir.within("PO4", [0.09], [0.0])[0] and ir.within("PO4", [1.29], [1.0])[0]


def test_season_lst_offset():
    idx = pd.DatetimeIndex(["2020-06-01 03:00"])  # UTC -> 2020-05-31 22:00 EST
    assert ir.season_of(ir.to_lst(idx))[0] == "dry"
    assert ir.season_of(pd.DatetimeIndex(["2020-10-31"]))[0] == "wet"


def test_climatology_leave_one_year_out():
    idx = pd.DatetimeIndex([f"{y}-03-15" for y in range(2015, 2020)])
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 100.0], index=idx)
    clim = ir.climatology_loyo(s, min_other_years=3)
    assert clim.loc["2019-03-15"] == 2.5  # median of 1,2,3,4 (own year excluded)
    assert clim.loc["2015-03-15"] == 3.5  # median of 2,3,4,100
    assert ir.climatology_loyo(s.iloc[:3], min_other_years=3).isna().all()


def test_daily_means_require_min_hours():
    idx = _hours(2)
    wide = pd.DataFrame({"A": np.arange(48, dtype=float)}, index=idx + pd.Timedelta(hours=5))  # aligned to EST days
    wide.iloc[30:40] = np.nan  # day 2 keeps 14 hours
    d = ir.daily_means(wide)
    assert d["A"].iloc[0] == np.arange(24).mean() and np.isnan(d["A"].iloc[1])


def test_transfer_and_daily_frame_with_climatology():
    idx = _hours(60) + pd.Timedelta(hours=5)
    rng = np.random.default_rng(0)
    anchor = pd.Series(20 + rng.normal(0, 0.05, len(idx)), index=idx)
    target = anchor + 3.0  # offset: raw fails, calibrated passes after 10 days
    clim = pd.Series(23.0, index=idx)
    f = ir.transfer_frame(anchor, target, "Temp", clim)
    raw, cal = f[f["transfer"] == "raw"], f[f["transfer"] == "calibrated_30d"]
    assert raw["within"].mean() == 0 and cal["within"].mean() > 0.99
    assert f["within_clim"].mean() > 0.99
    d = ir.daily_frame(f, "Temp", clim_daily=pd.Series(23.0, index=pd.date_range("2020-01-01", periods=60)))
    assert set(d["transfer"]) == {"raw", "calibrated_30d"}
    assert (d.loc[d["transfer"] == "raw", "within"] == False).all()  # noqa: E712
    assert d["hours"].min() >= ir.DAILY_MIN_HOURS
    c = ir.counts_from(d.assign(season="dry"), ["transfer", "date", "season"])
    assert (c["nc"] == 1).all() and (c["wc"] == 1).all()


def test_station_rain_fills_from_nearest_gauge_within_30km():
    idx = pd.date_range("2020-01-01", periods=24 * 366, freq="h")
    rain = pd.DataFrame({"JB": 1.0, "SLE": 2.0, "TV": 5.0}, index=idx)
    rain.loc[rain.index.month == 2, "JB"] = np.nan  # JB 2020 coverage ~92 % -> own gauge, gaps filled
    stations = pd.DataFrame({"site": ["JB", "SLE", "TV"], "lat": [27.2244, 27.1649, 28.5985],
                             "lon": [-80.2023, -80.1718, -80.7913], "cluster": ["st_lucie", "st_lucie", "north"]})
    cov = ir.rain_coverage(rain)
    out = ir.station_rain(rain, stations, cov)
    jb = out["JB"]
    assert jb[jb.index.month == 1].eq(1.0).all() and jb[jb.index.month == 2].eq(2.0).all()  # filled from SLE
    rain2 = rain.copy()
    rain2.loc[rain2.index.month <= 3, "JB"] = np.nan  # coverage < 80 % -> JB year unusable, SLE used
    out2 = ir.station_rain(rain2, stations, ir.rain_coverage(rain2))
    assert out2["JB"].eq(2.0).all()
    assert out2["TV"].eq(5.0).all()  # no neighbour within 30 km needed


def test_cluster_wet_months_picks_lowest_salinity():
    idx = pd.date_range("2020-01-01", "2021-12-31 23:00", freq="h")
    sal = 30 - 5 * idx.month.isin([6, 7, 8, 9, 10]).astype(float)
    wide = pd.DataFrame({"FP": sal, "NF": sal - 10}, index=idx)
    st = pd.DataFrame({"site": ["FP", "NF"], "cluster": ["lagoon", "st_lucie"]})
    tab = ir.cluster_wet_months(wide, st).set_index("cluster")
    assert tab.at["lagoon", "lowest_sal_months"] == "6,7,8,9,10"
    assert tab.at["all", "n_stations"] == 2


def _counts_fixture():
    dates = pd.date_range("2020-01-01", periods=60)
    rows = []
    for pair, km, wt, wc in (("A>B", 3.0, 1, 0), ("B>A", 3.0, 1, 0), ("A>C", 40.0, 0, 1)):
        for d in dates:
            rows.append({"var": "Sal", "regime": "same", "distance_bin": ir.ur.distance_bin([km])[0],
                         "transfer": "raw", "date": d, "pair": pair, "km": km, "wt": wt, "nc": 1, "wc": wc,
                         "w": wt, "n": 1, "abs_err": 0.1})
    return pd.DataFrame(rows)


def test_baseline_compare_flags_winner():
    base = ir.baseline_compare(_counts_fixture(), "daily").set_index(["distance_bin"])
    assert base.at["2-5", "transfer_better"] and base.at["2-5", "share_climatology"] == 0
    assert base.at[">30", "climatology_better"]
    assert base.at["all_le30", "n_pairs"] == 2  # >30 km excluded from the pooled row


def test_cell_table_and_radius_columns():
    c = _counts_fixture()
    cells = ir.cell_table(c)
    assert list(cells.columns[:11]) == ["dataset", "var", "regime", "distance_bin", "transfer", "n_days", "share",
                                        "ci_low", "gate80", "gate90", "gate95"]
    rad = ir.radius_with_stop(cells)
    assert list(rad.columns[:7]) == ["dataset", "var", "regime", "transfer", "gate", "radius_km", "radius_km_strict"]
    r80 = rad[rad["gate"] == "gate80"].iloc[0]
    assert r80["radius_km"] == 5.0  # 2-5 passes; >30 km not part of the walk
    assert np.isnan(r80["radius_km_strict"])  # no evidence at 0-2 km


def test_climatology_cells_station_level():
    idx = pd.DatetimeIndex([f"{y}-03-{d:02d} 12:00" for y in range(2015, 2020) for d in range(1, 29)])
    wide = {"Temp": pd.DataFrame({"FP": 20.0}, index=idx)}
    clim_h = {"Temp": {"FP": pd.Series(20.2, index=idx)}}
    daily = {"Temp": pd.DataFrame({"FP": 20.0}, index=idx.normalize())}
    clim_d = {"Temp": {"FP": pd.Series(21.0, index=idx.normalize())}}
    out = ir.climatology_cells(wide, clim_h, daily, clim_d).set_index("scale")
    assert out.at["hourly", "share"] == 1.0 and out.at["hourly", "gate95"] == "pass"
    assert out.at["daily", "share"] == 0.0


def test_quantisation_check_counts_repeats():
    h = pd.DataFrame({"site": "FP", "var": "Sal", "hour_utc": pd.date_range("2020-01-01", periods=5, freq="h"),
                      "value": [30.0, 30.0, 30.0, 31.0, 31.0]})
    q = ir.quantisation_check(h)
    assert q["repeats"].iloc[0] == 3 and q["repeat_share"].iloc[0] == 0.75


def test_pair_table_regime_months_and_robustness_columns():
    idx = pd.date_range("2020-01-01", "2021-12-31 23:00", freq="h")
    low = idx.month.isin([10, 11, 12, 1, 2])
    a = pd.Series(30.0, index=idx)
    b = pd.Series(np.where(low, 25.0, 30.0), index=idx)  # differs only in the low-salinity months
    wide = {"Sal": pd.DataFrame({"FP": a, "LP": b})}
    st = pd.DataFrame({"site": ["FP", "LP"], "cluster": ["lagoon", "lagoon"], "lat": [27.4756, 27.5348],
                       "lon": [-80.3266, -80.3431]})
    p = ir.pair_table(st, wide, regime_months=(10, 11, 12, 1, 2)).set_index("anchor")
    assert p.at["FP", "regime"] == "different" and p.at["FP", "dsal"] == 5.0
    assert p.at["FP", "regime_junoct"] == "same"  # Jun-Oct medians: only October differs
    assert p.at["FP", "distance_bin"] == "5-10" and p.at["FP", "n_days_Sal"] == 732  # UTC->EST adds 2019-12-31


def test_build_strata_era5_and_gauge_columns():
    hours = pd.date_range("2020-07-01", periods=96, freq="h")
    era5 = pd.Series(0.0, index=hours)
    era5.iloc[10] = 12.0
    gauge = pd.Series(0.0, index=hours)
    s = ir.build_strata(hours, 27.47, -80.33, era5, gauge)
    assert s["rain24h"].iloc[11] == "na"  # < 20 of 24 prior hours
    assert s["rain24h"].iloc[30] == "heavy" and s["rain24h"].iloc[40] == "none"
    assert s["g_rain24h"].iloc[30] == "none"
    assert set(s["season"]) == {"wet"}
