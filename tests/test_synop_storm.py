import numpy as np
import pandas as pd

from experiments import synop_storm as ss


def _station(values, start="2020-08-01 00:00", step_h=3, code="48839"):
    t = pd.date_range(start, periods=len(values), freq=f"{step_h}h")
    return pd.DataFrame({"station_code": code, "obs_utc": t, "wspd_ms": np.array(values, dtype=float)})


def test_flag_wind_range_and_spike():
    df = _station([3, 4, 98, 3, 2, 45, 3, 4, 30, 28, 4])
    out = ss.flag_wind(df)
    assert out["wspd_range_bad"].tolist()[2]
    # 45 with neighbours <= 3 -> spike; 30 next to 28 -> not a spike; 28 next to 30 -> not a spike
    assert out["wspd_spike"].tolist() == [False] * 5 + [True] + [False] * 5
    assert not out.loc[2, "wspd_valid"] and not out.loc[5, "wspd_valid"]
    assert out.loc[8, "wspd_valid"] and out.loc[9, "wspd_valid"]


def test_flag_wind_storm_exempts_spike_and_isolated_value():
    df = _station([3, 45, 3])
    near = np.array([False, True, False])
    assert not ss.flag_wind(df, near)["wspd_spike"].any()
    # isolated (no neighbour within 6 h) and >= 20 -> spike
    lone = _station([25], code="48834")
    assert ss.flag_wind(lone)["wspd_spike"].all()


def test_flag_wind_ignores_range_bad_neighbours():
    # the only neighbour of 30 is 98 (invalid) -> treated as no neighbour -> spike
    df = _station([98, 30])
    out = ss.flag_wind(df)
    assert out["wspd_range_bad"].tolist() == [True, False]
    assert out["wspd_spike"].tolist() == [False, True]


def test_storm_near():
    track = pd.DataFrame({"ISO_TIME": pd.to_datetime(["2020-08-01 12:00"], utc=True), "LAT": [20.5], "LON": [107.7]})
    obs = pd.Series(pd.to_datetime(["2020-08-01 00:00", "2020-07-31 23:00", "2020-08-02 00:00", "2020-08-02 01:00"]))
    assert ss.storm_near(obs, track, 20.13, 107.72).tolist() == [True, False, True, False]
    assert not ss.storm_near(obs, track, 10.0, 107.72).any()


def test_fit_factor_minimises_absolute_error():
    model = np.array([10.0, 20.0, 30.0, 0.0])
    obs = 0.5 * model[:3]
    assert ss.fit_factor(model, np.append(obs, 5.0)) == 0.5
    k = ss.fit_factor([10, 10, 10], [4, 5, 9])
    grid = np.linspace(0, 1.2, 1201)
    best = grid[np.argmin([np.abs(np.array([4, 5, 9]) - g * 10).sum() for g in grid])]
    assert abs(k - best) < 1e-9
    assert np.isnan(ss.fit_factor([0, 0], [1, 2]))


def test_tier_from_beaufort():
    th = {"1": 6, "2": 8, "3": 10, "4": 12}
    assert [ss.tier_from_beaufort(b, th) for b in (3, 6, 9, 10, 13)] == [0, 1, 2, 3, 4]
    assert ss.tier_from_beaufort(None, th) is None


def _track():
    t = pd.date_range("2020-08-01 00:00", periods=9, freq="3h", tz="UTC")
    lat = np.linspace(18.0, 22.0, 9)  # northward over lon 107.7, closest to the station at 20.13 near 12Z
    return pd.DataFrame({"SID": "S1", "SEASON": 2020, "NAME": "TEST", "ISO_TIME": t, "LAT": lat,
                         "LON": 107.7, "TOKYO_WIND": 70.0, "HKO_WIND": np.nan, "CMA_WIND": np.nan,
                         "USA_WIND": np.nan, "USA_RMW": 20.0,
                         **{f"USA_R{k}_{q}": np.nan for k in (34, 50, 64) for q in ("NE", "SE", "SW", "NW")}})


def test_station_passages_pairs_at_obs_times():
    obs = _station([5, 8, 12, 20, 30, 18, 9, 6, 4], start="2020-08-01 00:00")
    p = ss.station_passages(_track(), obs, 20.13, 107.72, radius_km=300.0)
    assert len(p) == 1
    r = p.iloc[0]
    assert r["min_dist_km"] < 5
    assert r["obs_max_ms"] == 30
    assert r["model_max_ms"] <= r["model_peak_cont_ms"] + 1e-9
    assert r["n_pairs"] >= 3 and r["obs_near_peak"]
    # 6-hourly obs only: model max is taken at those times, never above the continuous peak
    p6 = ss.station_passages(_track(), obs.iloc[::2], 20.13, 107.72, radius_km=300.0).iloc[0]
    assert p6["model_max_ms"] <= r["model_max_ms"] + 1e-9


def test_station_passages_far_storm_absent():
    obs = _station([5] * 9)
    assert ss.station_passages(_track(), obs, 10.0, 100.0, radius_km=300.0).empty


def test_bands():
    assert [ss.distance_band(d) for d in (10, 50, 75, 150, 250, 400)] == \
        ["0-50", "0-50", "50-100", "100-200", "200-300", ">300"]
    assert [ss.intensity_class(x) for x in (None, 7, 8, 11, 12)] == ["unknown", "lt8", "8-11", "8-11", "ge12"]
