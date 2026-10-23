"""Unit tests for the multi-reserve NERRS loader and H4.3 reliability helpers (no network)."""
import numpy as np
import pandas as pd
import pytest

from experiments import nerrs_multi as nm
from experiments import nerrs_multi_reliability as nmr

LISTING = (
    '<tr><td><a href="rkbfbwq2006.csv">rkbfbwq2006.csv</a></td><td align="right">2011-08-11 11:12  </td>'
    '<td align="right">2.1M</td><td>&nbsp;</td></tr>\n'
    '<tr><td><a href="rkbfbwq2007.csv">rkbfbwq2007.csv</a></td><td align="right">2011-08-11 11:12  </td>'
    '<td align="right">4.7M</td><td>&nbsp;</td></tr>\n'
    '<tr><td><a href="rkbuhmet2009.csv">rkbuhmet2009.csv</a></td><td align="right">2011-08-11  </td>'
    '<td align="right">5.0M</td><td>&nbsp;</td></tr>\n'
    '<tr><td><a href="rkbbmwq2008.csv">rkbbmwq2008.csv</a></td><td align="right">2011-08-11  </td>'
    '<td align="right">1.0M</td><td>&nbsp;</td></tr>\n'
    '<tr><td><a href="rkbfbnut2008.csv">rkbfbnut2008.csv</a></td><td align="right">2011-08-11  </td>'
    '<td align="right">20K</td><td>&nbsp;</td></tr>\n'
    '<tr><td><a href="rkbwq01-12.06m.doc">rkbwq01-12.06m.doc</a></td><td align="right">2011-08-11  </td>'
    '<td align="right">300K</td><td>&nbsp;</td></tr>\n'
    '<tr><td><a href="apawq01-12.06m.doc">apawq01-12.06m.doc</a></td><td align="right">2011-08-11  </td>'
    '<td align="right">300K</td><td>&nbsp;</td></tr>\n'
)


def test_parse_listing_and_select_files_keep_qc_years_known_stations_and_metadata():
    names = nm.parse_listing(LISTING)["name"].tolist()
    assert len(names) == 7
    picked = nm.select_files(names, nm.RESERVES["rkb"])
    assert picked == ["rkbfbwq2007.csv", "rkbuhmet2009.csv", "rkbwq01-12.06m.doc"]
    assert nm.select_files(names, nm.RESERVES["rkb"], metadata_only=True) == ["rkbwq01-12.06m.doc"]


def test_parse_coordinates_degree_decimal_minutes_and_paren_attribution():
    text = ("The Cat Point (CP) sampling site is located in St. George Sound. The piling location is latitude "
            "29\x8142.12\x81 N and longitude 84\x8152.81\x81 W. The Dry Bar (DB) site ... latitude 29(40.48( N "
            "and longitude 85(03.50( W.")
    coords = nm.parse_coordinates(text, "apa", ("cp", "db", "eb", "es"))
    assert coords["cp"] == pytest.approx((29.702, -84.880167), abs=1e-5)
    assert coords["db"] == pytest.approx((29.674667, -85.058333), abs=1e-5)


def test_parse_coordinates_bracket_and_decimal_degree_formats():
    text = ("Aransas Bay (AB): [27\xb0 58.791'N, 97\xb0 1.727'W]. Ship Channel (SC): [27\xb0 50.296'N, 97\xb0 3.017'W]. "
            "Henderson Creek (rkblhwq): Lat/Long (Decimal Degrees): 26.0257 N 81.7332 W")
    mar = nm.parse_coordinates(text, "mar", ("ab", "sc"))
    assert mar["ab"] == pytest.approx((27.97985, -97.028783), abs=1e-5)
    assert mar["sc"][0] == pytest.approx(27.838267, abs=1e-5)
    rkb = nm.parse_coordinates(text, "rkb", ("lh",))
    assert rkb == {"lh": (26.0257, -81.7332)}


def test_first_coordinate_handles_space_separated_degrees():
    text = "The weather station is located at latitude 29 47.472' N and longitude 84 53.005' W."
    assert nm.first_coordinate(text) == pytest.approx((29.7912, -84.883417), abs=1e-5)


WQ_CSV = (
    '"DateTimeStamp","Historical","ProvisionalPlus","F_Record","Temp","F_Temp","Sal","F_Sal",\n'
    '01/01/2008 0:00,0,0,"",20.0,<0> ,30.0,<0> ,\n'
    '01/01/2008 0:15,0,0,"",20.2,<0> ,30.2,<2> ,\n'
    '01/01/2008 0:30,0,0,"",20.4,<1> ,30.4,<0> ,\n'
    '01/01/2008 1:00,0,0,"",21.0,<0> ,31.0,<0> ,\n'
)
MET_CSV = (
    '"DateTimeStamp","Historical","ProvisionalPlus","Frequency","F_Record","WSpd","F_WSpd","TotPrcp","F_TotPrcp",\n'
    '01/01/2008 0:00,0,0,15,"",1.0,<0> ,0.5,<0> ,\n'
    '01/01/2008 0:15,0,0,15,"",1.0,<0> ,0.5,<0> ,\n'
    '01/01/2008 0:30,0,0,15,"",1.0,<0> ,0.5,<0> ,\n'
    '01/01/2008 0:45,0,0,15,"",1.0,<0> ,0.5,<0> ,\n'
)


def test_reserve_loaders_read_good_flags_and_merge_met_stations(tmp_path):
    reserve = nm.Reserve("tst", "Test", "XX", -5, ("aa",), ("m1", "m2"))
    (tmp_path / "tstaawq2008.csv").write_text(WQ_CSV)
    (tmp_path / "tstaawq2006.csv").write_text(WQ_CSV)  # outside QC years: ignored
    (tmp_path / "tstm2met2008.csv").write_text(MET_CSV)
    wq, flags = nm.load_wq_hourly(reserve, data_dir=tmp_path)
    temp = wq[wq["variable"] == "Temp"].set_index("time_lst")["value"]
    assert temp.to_dict() == {pd.Timestamp("2008-01-01 00:00"): pytest.approx(20.1)}  # hour 01 has 1 obs only
    sal = wq[wq["variable"] == "Sal"]
    assert sal["value"].tolist() == [pytest.approx(30.2)]  # <2> excluded
    assert set(flags["year"]) == {2008}
    met, _ = nm.load_met_hourly(reserve, data_dir=tmp_path)
    assert met.loc[pd.Timestamp("2008-01-01 00:00"), "TotPrcp"] == pytest.approx(2.0)


def test_distance_bin_edges():
    assert list(nmr.distance_bin([0, 1.99, 2, 9.9, 20, 29.9, 30, 45])) == [
        "0-2", "0-2", "2-5", "5-10", "20-30", "20-30", ">30", ">30"]


def test_wet_months_picks_lowest_salinity_months():
    monthly = pd.Series([30, 31, 32, 33, 34, 35, 20, 21, 22, 23, 24, 25.0], index=range(1, 13))
    assert nmr.wet_months(monthly) == (7, 8, 9, 10, 11, 12)
    assert nmr.wet_months(monthly, n=2) == (7, 8)


def test_regime_table_uses_wet_season_medians():
    t = pd.to_datetime(["2008-07-01", "2008-07-02", "2008-01-01", "2008-07-01", "2008-01-01"])
    wq = pd.DataFrame({"time_lst": t, "station": ["a", "a", "a", "b", "b"], "variable": "Sal",
                       "value": [10.0, 12.0, 30.0, 12.5, 11.0]})
    pairs = pd.DataFrame({"anchor": ["a", "b"], "target": ["b", "a"]})
    out = nmr.regime_table(wq, pairs, wet=(7,))
    assert out["dsal"].tolist() == [1.5, 1.5]
    assert out["regime"].tolist() == ["same", "same"]
    out = nmr.regime_table(wq, pairs, wet=(7,), threshold=1.0)
    assert out["regime"].tolist() == ["different", "different"]


def test_rain_class_thresholds():
    s = pd.Series([np.nan, 0.0, 0.99, 1.0, 9.9, 10.0])
    assert list(nmr.rain_class(s, heavy=10.0)) == ["na", "none", "none", "mid", "mid", "heavy"]


@pytest.mark.parametrize("status, loose, strict", [
    ({"0-2": "pass", "2-5": "pass", "5-10": "fail"}, 5.0, 5.0),
    ({"0-2": "fail"}, 0.0, 0.0),
    ({"2-5": "pass", "5-10": "pass", "10-20": "fail"}, 10.0, np.nan),
    ({"0-2": "pass", "2-5": "insufficient", "5-10": "pass", "10-20": "fail"}, 10.0, 2.0),
    ({}, np.nan, np.nan),
    ({"0-2": "pass", "2-5": "pass", "5-10": "pass", "10-20": "pass", "20-30": "pass"}, 30.0, 30.0),
])
def test_radius_rules(status, loose, strict):
    got_loose, got_strict, evidence = nmr.radius(status)
    np.testing.assert_equal(got_loose, loose)
    np.testing.assert_equal(got_strict, strict)
    assert evidence.startswith("0-2:")


def test_daily_counts_and_cell_table_pool_pairs_per_day():
    idx = pd.date_range("2008-01-01", periods=24 * 40, freq="h")
    strata = pd.DataFrame({"daynight": "day", "rain24": "none", "rain72": "none"}, index=idx)
    frame = pd.DataFrame({"within": np.tile([True, True, True, False], len(idx) // 4), "err": 0.1}, index=idx)
    d = nmr.daily_counts(frame, strata)
    allrows = d[d["stratum"] == "all"]
    assert len(allrows) == 40 and allrows["n"].eq(24).all() and allrows["w"].eq(18).all()
    rows = []
    for anchor, target in (("a", "b"), ("b", "a")):
        rows.append(d.assign(reserve="tst", anchor=anchor, target=target, var="Temp", transfer="raw",
                             km=1.0, distance_bin="0-2", regime="same", dsal=0.5))
    elig = pd.concat(rows, ignore_index=True)
    cells = nmr.cell_table(elig)
    row = cells[(cells["dataset"] == "nerrs_tst") & (cells["regime"] == "same")].iloc[0]
    assert row["n_days"] == 40 and row["n_pairs"] == 2 and row["share"] == pytest.approx(0.75)
    assert row["gate80"] == "fail" and row["gate90"] == "fail"
    assert set(cells["dataset"]) == {"nerrs_tst", "nerrs_pooled"}


def test_effect_row_requires_ten_days_each_and_reports_difference():
    dates = pd.date_range("2008-01-01", periods=30, freq="D")
    grp = pd.DataFrame({"reserve": "tst", "date": np.repeat(dates, 2), "level": ["heavy", "none"] * 30,
                        "w": [5, 9] * 30, "n": [10, 10] * 30, "sae": [1.0, 1.0] * 30})
    row = nmr._effect_row(grp, "level", "heavy", "none", {"dataset": "x"})
    assert row["share_a"] == pytest.approx(0.5) and row["share_b"] == pytest.approx(0.9)
    assert row["diff_a_minus_b"] == pytest.approx(-0.4) and row["significant"]
    assert nmr._effect_row(grp.iloc[:10], "level", "heavy", "none", {}) is None


def test_rain_gauge_check_aligns_lst_to_utc_days():
    idx = pd.date_range("2008-01-01 19:00", periods=48, freq="h")  # LST, UTC-5 -> UTC 2008-01-02 00:00 ..
    rain = pd.Series(1.0, index=idx)
    era5 = pd.Series([0.0, 24.0, 24.0], index=pd.to_datetime(["2008-01-01", "2008-01-02", "2008-01-03"]))
    out = nmr.rain_gauge_check(rain, -5, era5)
    assert out["complete_days"].tolist() == [2]
    assert out["ratio_gauge_over_era5"].tolist() == [1.0]


def test_regime_vs_distance_recovers_dsal_effect():
    rng = np.random.default_rng(0)
    rows = []
    stations = list("abcdefgh")
    sal = dict(zip(stations, rng.uniform(5, 35, len(stations))))
    pos = dict(zip(stations, rng.uniform(0, 25, len(stations))))
    for r in ("r1", "r2"):
        for a in stations:
            for b in stations:
                if a != b:
                    dsal, km = abs(sal[a] - sal[b]), abs(pos[a] - pos[b])
                    rows.append({"reserve": r, "anchor": a, "target": b, "var": "Sal", "transfer": "raw",
                                 "km": km, "dsal": dsal, "share": 0.9 - 0.02 * dsal + rng.normal(0, 0.01)})
    out = nmr.regime_vs_distance(pd.DataFrame(rows), n_boot=50)
    pooled = out[(out["dataset"] == "nerrs_pooled") & (out["response"] == "share")].iloc[0]
    assert pooled["beta_z_dsal"] < 0 and abs(pooled["beta_z_dsal"]) > abs(pooled["beta_z_km"])
    assert pooled["ci_high_dsal"] < 0
