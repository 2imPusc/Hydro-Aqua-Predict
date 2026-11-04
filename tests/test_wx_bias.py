import json

import numpy as np
import pandas as pd
import pytest

from experiments import wx_bias as wb


def test_window_sum_uses_preceding_hours_inclusive_of_end():
    idx = pd.date_range("2024-03-01 00:00", periods=30, freq="h")
    hourly = pd.Series(np.arange(30, dtype=float), index=idx)
    end = pd.DatetimeIndex([pd.Timestamp("2024-03-01 12:00")])
    # 6 h window ending 12 UTC = hours 07..12 -> 7+8+9+10+11+12
    assert wb.window_sum(hourly, end, 6).iloc[0] == 57.0


def test_window_sum_nan_when_any_hour_missing():
    idx = pd.date_range("2024-03-01 00:00", periods=24, freq="h")
    hourly = pd.Series(1.0, index=idx)
    hourly.iloc[10] = np.nan
    ends = pd.DatetimeIndex([pd.Timestamp("2024-03-01 12:00"), pd.Timestamp("2024-03-01 18:00")])
    out = wb.window_sum(hourly, ends, 6)
    assert np.isnan(out.iloc[0]) and out.iloc[1] == 6.0


def test_qc_ok_drops_only_flagged_variable():
    df = pd.DataFrame({"wspd_ms": [5.0, 90.0, 39.0, np.nan], "ps_hpa": [1000, 1000, 1, 1000],
                       "qc_flags": ["", "wspd_ms;", "ps_hpa;", ""]})
    assert wb.qc_ok(df, "wspd_ms").tolist() == [True, False, True, False]
    assert wb.qc_ok(df, "ps_hpa").tolist() == [True, True, False, True]


def test_contingency_counts_and_scores():
    obs = [0, 12, 15, 3, 20, 0]
    fc = [11, 13, 2, 0, 25, 0]
    c = wb.contingency(obs, fc, 10)
    assert (c["hits"], c["false_alarms"], c["misses"], c["correct_neg"]) == (2, 1, 1, 2)
    assert c["pod"] == pytest.approx(2 / 3) and c["far"] == pytest.approx(1 / 3)
    assert c["csi"] == pytest.approx(0.5) and c["freq_bias"] == pytest.approx(1.0)


def test_contingency_no_events_gives_nan_not_error():
    c = wb.contingency([0, 1], [0, 2], 10)
    assert c["obs_events"] == 0 and np.isnan(c["pod"]) and np.isnan(c["csi"])


def test_quantile_mapping_recovers_scale_and_handles_ties_and_tail():
    rng = np.random.default_rng(0)
    obs = rng.gamma(2.0, 2.0, 5000)
    fc = obs * 0.5  # forecast too weak by half
    table = wb.fit_qm(obs, fc)
    mapped = wb.apply_qm(fc, table)
    assert np.median(np.abs(mapped - obs)) < 0.1
    # beyond the top fitted forecast quantile: constant shift, never below the floor
    top_fc, top_obs = table["q_fc"][-1], table["q_obs"][-1]
    assert wb.apply_qm([top_fc + 1.0], table)[0] == pytest.approx(top_obs + 1.0)
    # many zero forecasts (ties) map to one value, clipped at 0
    obs2 = np.r_[np.zeros(800), rng.gamma(1, 5, 200)]
    fc2 = np.r_[np.zeros(900), rng.gamma(1, 5, 100)]
    m2 = wb.apply_qm(np.zeros(3), wb.fit_qm(obs2, fc2))
    assert np.all(m2 >= 0) and len(set(m2)) == 1


def test_tier_map_matches_exceedance_frequency():
    obs = np.r_[np.zeros(90), np.full(10, 12.0)]  # 10 % obs >= 10.8
    fc = np.linspace(0, 9.9, 100)  # forecast never reaches 10.8
    t = wb.tier_map(obs, fc, 10.8)
    assert t["n_obs_exceed"] == 10 and t["n_fc_exceed"] == 0
    assert t["fc_equiv_threshold"] == pytest.approx(np.quantile(fc, 0.9))
    assert np.isnan(wb.tier_map(np.zeros(5), fc[:5], 10.8)["fc_equiv_threshold"])


def test_parse_payload_maps_names_and_nulls():
    names = wb.hourly_names()
    payload = {"hourly": {"time": ["2024-03-01T00:00", "2024-03-01T01:00"],
                          **{n: [1.5, None] for n in names}}}
    df = wb.parse_payload(payload)
    assert df.shape == (2, len(names)) and df.index[0] == pd.Timestamp("2024-03-01")
    assert df.loc[pd.Timestamp("2024-03-01"), "wind_d7"] == 1.5 and np.isnan(df.iloc[1]["precip_d1"])


def test_build_pairs_aligns_rain_windows_and_instant_values():
    idx = pd.date_range("2024-03-01", "2024-03-05", freq="h")
    f = pd.DataFrame({f"{v}_d{n}": 1.0 for v in wb.API_VARS for n in wb.LEADS}, index=idx)
    times = pd.date_range("2024-03-02", "2024-03-04 21:00", freq="3h")
    synop = pd.DataFrame({"obs_utc": times, "station_code": "48833", "t2m_c": 20.0, "rh_pct": 80.0, "wspd_ms": 3.0,
                          "rain6h_mm": np.where(times.hour % 6 == 0, 2.0, np.nan),
                          "rain24h_mm": np.where(times.hour % 6 == 0, 8.0, np.nan), "qc_flags": ""})
    p = wb.build_pairs(synop, {("48833", "best_match"): f})
    r6 = p[(p.variable == "rain6h") & (p.lead == 1)]
    assert set(r6.valid_utc.dt.hour) == {0, 6, 12, 18} and (r6.fc == 6.0).all()
    r24 = p[(p.variable == "rain24h") & (p.lead == 1)]
    assert set(r24.valid_utc.dt.hour) == {12} and (r24.fc == 24.0).all()
    r72 = p[(p.variable == "rain72h") & (p.lead == 1)]
    assert len(r72) == 1 and r72.obs.iloc[0] == 24.0 and r72.fc.iloc[0] == 72.0
    w = p[(p.variable == "wind") & (p.lead == 3)]
    assert len(w) == len(times) and (w.fc - w.obs == -2.0).all()


def test_season_uses_local_month():
    ts = pd.Series(pd.to_datetime(["2024-02-29 20:00", "2024-05-31 18:00"]))
    assert wb.season(ts).tolist() == ["MAM", "JJA"]


def test_preregistration_is_valid_json_with_rules():
    pre = json.loads(wb.PREREG.read_text(encoding="utf-8"))
    ids = {r["id"] for r in pre["primary_rules"]}
    assert ids == set(pre["leads"]) and "rain6h_10mm" in ids
