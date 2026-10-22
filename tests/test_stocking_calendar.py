import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
import stocking_calendar as sc  # noqa: E402


def test_iso_week_start_is_monday():
    d = sc.iso_week_start(2024, 1)
    assert d == pd.Timestamp("2024-01-01") and d.weekday() == 0
    assert sc.iso_week_start(2021, 52) == pd.Timestamp("2021-12-27")


def test_window_counts_complete_and_incomplete():
    idx = pd.date_range("2020-01-01", "2020-03-31", freq="D")
    sst = pd.Series(20.0, index=idx)
    sst["2020-01-03":"2020-01-05"] = 32.0
    out = sc.window_sst_counts(sst, pd.Timestamp("2020-01-01"), 10, (31.0, 33.0), (20.0, 18.0), (25.0, 30.0))
    assert out["heat_ge1"] == 3 and out["heat_ge2"] == 0 and out["cold_ge1"] == 0 and out["cold_ge2"] == 0
    assert out["suitable"] == 0
    assert sc.window_sst_counts(sst, pd.Timestamp("2020-03-25"), 10, (31, 33), (20, 18), (25, 30)) is None
    with_nan = sst.copy()
    with_nan["2020-01-02"] = np.nan
    assert sc.window_sst_counts(with_nan, pd.Timestamp("2020-01-01"), 10, (31, 33), (20, 18), (25, 30)) is None


def test_cold_is_strictly_below():
    sst = pd.Series([17.9, 18.0, 19.9, 20.0], index=pd.date_range("2020-01-01", periods=4))
    out = sc.window_sst_counts(sst, sst.index[0], 4, (31, 33), (20, 18), (25, 30))
    assert out["cold_ge1"] == 3 and out["cold_ge2"] == 1


def test_suitable_band_inclusive():
    sst = pd.Series([24.9, 25.0, 30.0, 30.1], index=pd.date_range("2020-06-01", periods=4))
    out = sc.window_sst_counts(sst, sst.index[0], 4, (31, 33), (20, 18), (25, 30))
    assert out["suitable"] == 2


def test_storm_counts_by_threshold():
    dates = pd.DatetimeIndex(["2020-07-02", "2020-07-05", "2020-08-01"])
    beau = np.array([8, 6, 9])
    s = pd.Timestamp("2020-07-01")
    assert sc.window_storm_counts(dates, beau, s, 7, 8) == 1
    assert sc.window_storm_counts(dates, beau, s, 7, 6) == 2
    assert sc.window_storm_counts(dates, beau, pd.Timestamp("2020-07-08"), 7, 6) == 0


def test_minmax_constant_is_zero():
    assert list(sc.minmax(pd.Series([2.0, 2.0, 2.0]))) == [0, 0, 0]
    assert list(sc.minmax(pd.Series([1.0, 2.0, 3.0]))) == [0, 0.5, 1.0]


def test_composite_score_range_and_direction():
    risks = pd.DataFrame({"heat": [0, 1.0], "cold": [0, 1.0], "storm": [0, 1.0], "early": [0, 1.0], "growth": [0, 1.0]})
    w = {"heat": 0.2, "cold": 0.2, "storm": 0.25, "early": 0.2, "growth": 0.15}
    s = sc.composite_score(risks, w)
    assert s.iloc[0] == pytest.approx(1.0) and s.iloc[1] == pytest.approx(0.0)
    with pytest.raises(ValueError):
        sc.composite_score(risks, {**w, "heat": 0.9})


def test_top_k_and_top_share():
    scores = [pd.Series([0.9, 0.8, 0.1], index=[1, 2, 3]), pd.Series([0.9, 0.2, 0.8], index=[1, 2, 3])]
    assert sc.top_k(scores[0], 2) == [1, 2]
    share = sc.top_share(scores, 1)
    assert share[1] == 1.0 and share[2] == 0.0


def test_month_of_week_and_weight_sets_sum_to_one():
    assert sc.month_of_week(1) == 1 and sc.month_of_week(27) == 7 and sc.month_of_week(52) == 12
    for w in sc.WEIGHT_SETS.values():
        assert sum(w.values()) == pytest.approx(1.0)


def test_week_table_main_and_early_windows_do_not_overlap():
    idx = pd.date_range("2019-12-01", "2021-12-31", freq="D")
    sst = pd.Series(27.0, index=idx)
    sst["2020-01-06":"2020-01-12"] = 32.0  # ISO week 2 of 2020: first 7 days of the early window
    thr = {"heat": (31.0, 33.0), "cold": (20.0, 18.0), "suit": (25.0, 30.0)}
    t = sc.week_table(sst, pd.DatetimeIndex([]), np.array([]), (2020, 2020), 12, thr).loc[2]
    assert t["early_heat_ge1"] == 7 and t["heat_ge1"] == 0
    assert t["suitable"] == 7 * (12 - sc.EARLY_WEEKS) and t["early_suitable"] == 7 * sc.EARLY_WEEKS - 7


def test_classify_months_uses_absolute_cuts_and_flags_ties():
    vals = {1: 0.70, 2: 0.69, 3: 0.50, 4: 0.30}
    s = pd.Series([vals.get(sc.month_of_week(w), 0.10) for w in range(1, 53)], index=range(1, 53))
    out = sc.classify_months({26: s})
    assert out.loc[1, "class_26w"] == "good" and out.loc[3, "class_26w"] == "caution" and out.loc[4, "class_26w"] == "avoid"
    assert out.loc[1, "indist_group_26w"] == out.loc[2, "indist_group_26w"] != out.loc[3, "indist_group_26w"]
    assert "class" not in out.columns


def _daily(val, start="2020-01-01", n=100):
    return pd.Series(val, index=pd.date_range(start, periods=n, freq="D"))


def test_cold_flag_run_rule_and_lethal_day():
    s = _daily(25.0)
    s.iloc[10:23] = 17.0  # 13 days < 18
    assert sc.cold_mortality_flag(s, s.index[0], 60) is False
    s.iloc[10:24] = 17.0  # 14 days
    assert sc.cold_mortality_flag(s, s.index[0], 60) is True
    s2 = _daily(25.0)
    s2.iloc[5] = 15.0  # single day <= 15
    assert sc.cold_mortality_flag(s2, s2.index[0], 60) is True
    s3 = _daily(25.0)
    s3.iloc[5] = 15.1
    assert sc.cold_mortality_flag(s3, s3.index[0], 60) is False
    assert sc.cold_mortality_flag(s3, s3.index[50], 60) is None  # incomplete


def test_cold_flag_ignores_cold_outside_window():
    s = _daily(25.0)
    s.iloc[70:90] = 10.0
    assert sc.cold_mortality_flag(s, s.index[0], 60) is False


def test_feasible_mask_gate_boundary():
    t = pd.DataFrame({"early_ok_share": [0.79, 0.80, 1.0]}, index=[1, 2, 3])
    assert list(sc.feasible_mask(t)) == [False, True, True]
    assert list(sc.feasible_mask(t, 0.5)) == [True, True, True]


def test_winter_offset_only_applies_dec_to_mar():
    s = pd.Series(20.0, index=pd.to_datetime(["2020-01-15", "2020-07-15", "2020-12-01", "2020-04-01"]))
    out = sc.apply_offset(s, 0.3, -1.5)
    assert list(out) == pytest.approx([18.8, 20.3, 18.8, 20.3])


def _weeks_table():
    return pd.DataFrame({
        "heat_ge1": [0.0, 0, 0], "heat_ge2": [0.0, 0, 0], "cold_ge1": [0.0, 10, 0], "cold_ge2": [0.0, 5, 0],
        "storm_ge8": [0.0, 0, 0], "storm_ge6": [0.0, 0, 0], "suitable": [50.0, 50, 50],
        "early_heat_ge1": [0.0, 0, 0], "early_heat_ge2": [0.0, 0, 0], "early_cold_ge1": [0.0, 0, 0],
        "early_cold_ge2": [0.0, 0, 0], "early_storm_ge8": [0.0, 0, 0], "early_storm_ge6": [0.0, 0, 0],
        "early_ok_share": [1.0, 1.0, 0.5], "cold_flag_share": [0.0, 1.0, 1.0]}, index=[1, 2, 3])


def test_final_score_gate_and_penalty():
    t = _weeks_table()
    s = sc.final_score(t, sc.WEIGHTS)
    assert np.isnan(s[3])  # infeasible -> NaN
    assert s[1] - s[2] > sc.COLD_FLAG_PENALTY  # flagged week loses penalty plus relative-cold risk
    assert sc.top_k(s, 3) == [1, 2]


def test_classify_months_avoid_cold_when_gate_fails():
    s = pd.Series([0.9 if sc.month_of_week(w) != 1 else float("nan") for w in range(1, 53)], index=range(1, 53))
    feas = pd.Series([sc.month_of_week(w) != 1 for w in range(1, 53)], index=range(1, 53))
    out = sc.classify_months({26: s}, feasible_by_len={26: feas})
    assert out.loc[1, "class_26w"] == sc.CLASS_AVOID_COLD and out.loc[2, "class_26w"] == "good"
