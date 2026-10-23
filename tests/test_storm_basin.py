import numpy as np
import pandas as pd
import pytest

from core.storm_advisory import storm_wind_ms
from experiments import storm_basin as sb
from experiments import tigge_tracks as tt


def _times(n, step="3h", start="2024-09-01"):
    return pd.date_range(start, periods=n, freq=step, tz="UTC")


def test_intensity_order_matches_core():
    df = pd.DataFrame({"TOKYO_WIND": [np.nan, 50.0, np.nan], "HKO_WIND": [np.nan, 60.0, np.nan],
                       "USA_WIND": [100.0, 70.0, np.nan], "CMA_WIND": [80.0, 40.0, 30.0]})
    got = sb.intensity_ms(df)
    for i, row in df.iterrows():
        assert got[i] == pytest.approx(storm_wind_ms(row)[0])


def test_regrid_track_dedupes_and_aligns_to_grid():
    t = pd.to_datetime(["2024-09-01 01:00", "2024-09-01 07:00", "2024-09-01 07:00", "2024-09-01 13:00"], utc=True)
    g = pd.DataFrame({"SID": "X", "SEASON": 2024, "NAME": "A", "ISO_TIME": t, "LAT": [10.0, 11.0, 11.0, 12.0],
                      "LON": [130.0, 129.0, 129.0, 128.0], "WIND_MS": [np.nan, 20.0, np.nan, 30.0], "DIST2LAND": [1, 2, 2, 3]})
    r = sb.regrid_track(g, step_h=3)
    assert list(r["ISO_TIME"].dt.hour) == [3, 6, 9, 12]
    assert r["LAT"].iloc[0] == pytest.approx(10 + 2 / 6)
    # wind only valid from 07:00 -> NaN at 03 and 06
    assert r["WIND_MS"].iloc[:2].isna().all() and r["WIND_MS"].iloc[2] == pytest.approx(20 + 10 * 2 / 6)


def test_first_westward_crossing_requires_start_east():
    assert sb.first_westward_crossing([130, 126, 124, 123], 125) == 2
    assert sb.first_westward_crossing([124, 120], 125) is None
    assert sb.first_westward_crossing([130, 128], 125) is None


def test_backward_motion_uses_only_past():
    lat = np.array([10.0, 10.0, 10.0, 10.0, 10.0, 10.0])
    lon = np.array([130.0, 129.7, 129.4, 129.1, 128.8, 128.5])  # westward, 0.3 deg per 3 h
    u, v = sb.backward_motion(lat, lon, step_h=3)
    assert np.isnan(u[0]) and np.isnan(u[1])  # younger than 6 h
    expected = -0.3 * sb.KM_PER_DEG * np.cos(np.radians(10)) / 3
    assert u[2] == pytest.approx(expected) and u[5] == pytest.approx(expected)
    # changing a future point must not change the motion at earlier states
    lon2 = lon.copy()
    lon2[5] = 140
    u2, _ = sb.backward_motion(lat, lon2, step_h=3)
    assert np.allclose(u2[:5], u[:5], equal_nan=True)


def test_approach_labels_window_and_eligibility():
    dist = np.array([900, 700, 600, 450, 300, 600])  # step 3 h; first within 500 at index 3
    eligible, labels = sb.approach_labels(dist, 500, horizons=(3, 6), step_h=3)
    assert eligible.tolist() == [True, True, True, False, False, False]
    assert labels[3].tolist() == [False, False, True, False, False, False]
    assert labels[6].tolist() == [False, True, True, False, False, False]


def test_approach_labels_never_reached():
    eligible, labels = sb.approach_labels(np.array([900, 800]), 500, horizons=(24,))
    assert eligible.all() and not labels[24].any()


def test_in_philippines_boxes():
    assert sb.in_philippines([15.0], [121.0])[0]  # Luzon
    assert sb.in_philippines([10.0], [118.5])[0]  # Palawan
    assert not sb.in_philippines([23.5], [121.0])[0]  # Taiwan
    assert not sb.in_philippines([5.5], [117.0])[0]  # Sabah


def test_corridor_and_genesis_region():
    assert sb.corridor_at_120(np.nan, True).startswith("SCS")
    assert "Luzon Strait" in sb.corridor_at_120(20.0, False)
    assert sb.genesis_region(115.0).startswith("SCS")
    assert sb.genesis_region(140.0).startswith("far")


def test_brier_skill_and_auc():
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.2, 0.8, 0.9])
    assert sb.brier(p, y) == pytest.approx((0.01 + 0.04 + 0.04 + 0.01) / 4)
    assert sb.brier_skill(p, y, np.full(4, 0.5)) == pytest.approx(1 - 0.025 / 0.25)
    assert sb.roc_auc(p, y) == 1.0
    assert sb.roc_auc(np.array([0.5, 0.5, 0.5, 0.5]), y) == 0.5


def test_reliability_table_counts():
    t = sb.reliability_table([0.01, 0.02, 0.95, 0.97], [0, 1, 1, 1])
    assert t["n"].sum() == 4
    first = t.iloc[0]
    assert first["n"] == 2 and first["obs_freq"] == 0.5
    assert t.iloc[-1]["obs_freq"] == 1.0


def test_event_leads_first_and_consistent():
    times = _times(5, "6h")
    arrival = times[-1] + pd.Timedelta(hours=6)
    p = [0.4, 0.1, 0.35, 0.5, 0.6]
    out = sb.event_leads(times, p, arrival, 0.3)
    assert out["first_lead_h"] == 30.0
    assert out["consistent_lead_h"] == 18.0
    out = sb.event_leads(times, [0.1, 0.4, 0.1, 0.1, 0.1], arrival, 0.3)
    assert out["first_lead_h"] == 24.0 and np.isnan(out["consistent_lead_h"])


def test_event_leads_ignores_states_after_arrival():
    times = _times(3, "6h")
    out = sb.event_leads(times, [0.0, 0.0, 0.9], times[1], 0.5)
    assert np.isnan(out["first_lead_h"])


def test_shrunk_rate_pulls_sparse_bins_to_base():
    r = sb.shrunk_rate(np.array([1, 50]), np.array([1, 100]), 0.1, 10)
    assert r[0] == pytest.approx(2 / 11)
    assert r[1] == pytest.approx(51 / 110)


def test_extrapolate_hits_straight_line():
    # 600 km east of NB1, moving west at 25 km/h: reaches 200 km after ~16 h
    lat, lon = sb.SITE[0], sb.SITE[1] + 600 / (sb.KM_PER_DEG * np.cos(np.radians(sb.SITE[0])))
    hit24 = sb.extrapolate_hits([lat], [lon], [-25.0], [0.0], 24, 200)
    hit12 = sb.extrapolate_hits([lat], [lon], [-25.0], [0.0], 12, 200)
    away = sb.extrapolate_hits([lat], [lon], [25.0], [0.0], 120, 200)
    assert hit24[0] and not hit12[0] and not away[0]


def test_ens_leads_to_peak_skips_runs_inside_radius_and_after_peak():
    t = _times(4, "24h")
    ensp = pd.DataFrame({"SID": "S", "base_time": t, "ens_p200_120": [0.1, 0.4, 0.9, 0.9]})
    grid = pd.DataFrame({"SID": "S", "ISO_TIME": t, "dist_km": [900.0, 600.0, 150.0, 50.0]})
    peak = t[2] + pd.Timedelta(hours=12)
    out = sb.ens_leads_to_peak(ensp, grid, "S", peak, 200.0, 0.3)
    # run at t[2] is already inside 200 km and t[3] is after the peak -> only t[0], t[1] count
    assert out["first_lead_h"] == 36.0 and out["consistent_lead_h"] == 36.0
    # no run before the peak (storm formed late) -> NaN, not an error
    early = sb.ens_leads_to_peak(ensp, grid, "S", t[0] - pd.Timedelta(hours=1), 200.0, 0.3)
    assert np.isnan(early["first_lead_h"])


def test_parse_cxml_keeps_wp_forecasts_only():
    xml = b"""<?xml version='1.0'?><cxml><header><baseTime>2024-09-03T00:00:00</baseTime></header>
    <data origin="ecmf" type="analysis"><disturbance ID="a"><fix><validTime>2024-09-03T00:00:00Z</validTime>
      <latitude units="deg N">18.2</latitude><longitude units="deg E">119.6</longitude></fix></disturbance></data>
    <data origin="ecmf" type="forecast"><disturbance ID="a"><cycloneName>YAGI</cycloneName><cycloneNumber>13W</cycloneNumber>
      <fix hour="0"><validTime>2024-09-03T00:00:00Z</validTime><latitude units="deg N">18.6</latitude>
      <longitude units="deg E">119.0</longitude><cycloneData><minimumPressure><pressure>1000.0</pressure></minimumPressure>
      <maximumWind><speed>14.9</speed></maximumWind></cycloneData></fix>
      <fix hour="24"><validTime>2024-09-04T00:00:00Z</validTime><latitude units="deg N">19.0</latitude>
      <longitude units="deg E">117.0</longitude></fix></disturbance>
      <disturbance ID="b"><fix hour="0"><validTime>2024-09-03T00:00:00Z</validTime><latitude units="deg N">10.1</latitude>
      <longitude units="deg W">149.1</longitude></fix></disturbance></data>
    <data origin="ecmf" type="ensembleForecast" member="7"><disturbance ID="a"><fix hour="0">
      <validTime>2024-09-03T00:00:00Z</validTime><latitude units="deg N">18.5</latitude><longitude units="deg E">119.1</longitude></fix>
    </disturbance></data></cxml>"""
    df = tt.parse_cxml(xml)
    assert set(df["member"]) == {"hres", "ens07"}
    assert set(df["disturbance_id"]) == {"a"}  # 149.1 W is outside the WP box
    assert df.loc[df["hour"] == 0, "vmax_ms"].dropna().tolist() == [14.9]
    assert tt.run_url(pd.Timestamp("2024-09-03").date(), 0).endswith("z_tigge_c_ecmf_20240903000000_ifs_glob_prod_all_glo.xml")
