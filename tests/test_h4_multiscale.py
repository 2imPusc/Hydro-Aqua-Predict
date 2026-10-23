"""Unit tests for experiments/h4_multiscale.py (synthetic fixtures, no network, no data/)."""
import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import cohen_kappa_score

from experiments import h4_multiscale as hm


# ---------------------------------------------------------------- classes
def test_class_edges():
    assert hm.classify("DO", [3.99, 4.0, 4.99, 5.0, 9.0, np.nan]).tolist() == [2, 1, 1, 0, 0, -1]
    assert hm.classify("Temp", [17.9, 18.0, 24.9, 25.0, 30.0, 30.1, 33.0, 33.1]).tolist() == [2, 1, 1, 0, 0, 1, 1, 2]
    assert hm.classify("Sal", [14.9, 15.0, 25.9, 26.0, 32.0, 32.1]).tolist() == [2, 1, 1, 0, 0, 1]
    assert hm.classify("pH", [6.9, 7.0, 7.49, 7.5, 8.2, 8.3, 8.5, 8.51]).tolist() == [2, 1, 1, 0, 0, 1, 1, 2]
    assert hm.classify("Turb", [1.0, 50.0]).tolist() == [-1, -1]


def test_class_rules_match_cobia_table():
    bp = {k: dict(v) for k, v in hm.cobia_breakpoints().items()}
    assert bp["DO"][4.0] == 0.5 and bp["DO"][5.0] == 1.0
    assert bp["Temp"][18] == 0.5 and bp["Temp"][25] == 1.0 and bp["Temp"][30] == 1.0 and bp["Temp"][33] == 0.5
    assert bp["Sal"][15] == 0.0 and bp["Sal"][26] == 1.0 and bp["Sal"][32] == 1.0
    assert bp["pH"][7.0] == 0.5 and bp["pH"][7.5] == 1.0 and bp["pH"][8.2] == 1.0 and bp["pH"][8.5] == 0.5


def test_kappa_matches_sklearn_and_bad_miss():
    rng = np.random.default_rng(0)
    obs = rng.integers(0, 3, 400)
    est = np.where(rng.random(400) < 0.7, obs, rng.integers(0, 3, 400))
    conf = np.bincount(3 * obs + est, minlength=9)
    assert hm.kappa_from_conf(conf) == pytest.approx(cohen_kappa_score(obs, est), abs=1e-12)
    # hand case: 4 obs-bad, estimate says bad for 1 of them
    conf = np.zeros(9)
    conf[8], conf[6], conf[7], conf[0] = 1, 2, 1, 10
    s = hm.class_summary(conf)
    assert s["n_bad"] == 4 and s["bad_miss_rate"] == pytest.approx(0.75)
    assert s["bad_base_rate"] == pytest.approx(4 / 14)
    assert np.isnan(hm.kappa_from_conf(np.r_[5, np.zeros(8)]))  # one class only -> undefined


# ---------------------------------------------------------------- baselines
def test_climatology_is_strictly_past_years():
    idx = pd.date_range("2010-01-01", "2012-12-31", freq="D")
    s = pd.Series(idx.year.astype(float) * 10, index=idx)  # 20100 / 20110 / 20120
    clim = hm.monthly_climatology(s)
    assert clim.loc["2010-06-15":"2010-06-30"].isna().all()           # no earlier year
    assert clim.loc["2011-06-15"] == pytest.approx(20100.0)           # 2010 only, no leak of 2011/2012
    assert clim.loc["2012-06-15"] == pytest.approx(20105.0)           # mean of 2010 and 2011


def test_climatology_needs_min_days():
    idx = pd.DatetimeIndex(list(pd.date_range("2010-03-01", periods=9, freq="D")) + ["2011-03-05"])
    clim = hm.monthly_climatology(pd.Series(1.0, index=idx))
    assert np.isnan(clim.loc["2011-03-05"])  # only 9 earlier March days < 10


def _hours(start, n, value=None, seed=0):
    idx = pd.date_range(start, periods=n, freq="h")
    rng = np.random.default_rng(seed)
    v = value if value is not None else 20 + rng.normal(0, 1, n)
    return pd.Series(v, index=idx)


def test_daily_stats_joint_hours_and_min_hours():
    y = _hours("2015-01-01", 48, value=np.arange(48, dtype=float))
    x = y + 0.1
    x.iloc[30:37] = np.nan  # day 2 keeps 17 joint hours -> dropped
    x.iloc[0] = 100.0       # min/max of est use joint hours only
    d = hm.daily_stats(x, y)
    assert list(d.index) == [pd.Timestamp("2015-01-01")]
    assert d.loc["2015-01-01", "hours"] == 24
    assert d.loc["2015-01-01", "obs_min"] == 0 and d.loc["2015-01-01", "est_max"] == 100.0


def test_pair_unit_tables_persistence_and_calibration():
    n = 24 * 60
    y = _hours("2015-01-01", n, seed=1)
    x = y * 1.1 + 3.0
    tgt = {"hourly": y, "hourly_clim": hm.monthly_climatology(y), "daily": hm.target_daily(y)}
    tgt["daily_clim"] = pd.DataFrame({c: hm.monthly_climatology(tgt["daily"][c]) for c in tgt["daily"]},
                                     index=tgt["daily"].index)
    t = hm.pair_unit_tables(x, y, tgt)
    h = t["hourly"]
    ts = pd.Timestamp("2015-02-10 05:00")
    assert h.loc[ts, "persistence_1d"] == y.loc[ts - pd.Timedelta(hours=24)]
    assert h.loc[ts, "persistence_7d"] == y.loc[ts - pd.Timedelta(hours=168)]
    assert h["calibrated"].iloc[:239].isna().all()                     # needs 240 past hours
    assert np.allclose(h["calibrated"].dropna(), h.loc[h["calibrated"].notna(), "obs"])  # exact linear map
    d = t["daily_mean"]
    day = pd.Timestamp("2015-02-10")
    assert d.loc[day, "persistence_1d"] == pytest.approx(y.loc["2015-02-09"].mean())
    assert d.loc[day, "persistence_7d"] == pytest.approx(y.loc["2015-02-03"].mean())
    assert d["climatology"].isna().all()                               # single year -> no climatology
    # the first calibrated day is the first whose every hour is calibrated
    assert d["calibrated"].first_valid_index() == pd.Timestamp("2015-01-11")  # hour 240 = Jan 11 00:00


def test_week_blocks_and_weekly_min_days():
    days = pd.date_range("2015-01-05", periods=14, freq="D")  # Monday, two ISO weeks
    dm = pd.DataFrame({"obs": np.arange(14.0), "raw": np.arange(14.0)}, index=days)
    mask = np.ones(14, bool)
    mask[7:10] = False  # second week keeps 4 days -> dropped
    wk = hm.weekly_table(dm, "raw", mask)
    assert list(wk.index) == [pd.Timestamp("2015-01-05")]
    assert wk.loc["2015-01-05", "obs"] == pytest.approx(3.0)
    assert hm.week_start(pd.DatetimeIndex(["2015-01-11", "2015-01-12"])).tolist() == [
        pd.Timestamp("2015-01-05"), pd.Timestamp("2015-01-12")]


def test_unit_counts_and_blocks():
    idx = pd.DatetimeIndex(["2015-01-01 01:00", "2015-01-01 02:00", "2015-01-02 01:00"])
    blocks = hm.block_ids(idx, group=2)
    assert blocks[0] == blocks[1] and blocks[2] == blocks[0] + 1 and blocks[0] // 100000 == 2
    c = hm.unit_counts("DO", np.array([3.0, 6.0, 6.0]), np.array([3.4, 4.5, 6.0]), blocks)
    assert c["n"].tolist() == [2, 1]
    assert c["w"].tolist() == [1.0, 1.0]  # |0.4| ok, |1.5| not
    # day 1: obs bad/est bad (c8), obs ok/est caution (c1)
    assert c.loc[0, "c8"] == 1 and c.loc[0, "c1"] == 1 and c.loc[1, "c0"] == 1


def test_pair_counts_common_support_subset_of_own():
    n = 24 * 80
    y = _hours("2015-01-01", n, seed=2)
    x = y + 0.2
    tgt = {"hourly": y, "hourly_clim": hm.monthly_climatology(y), "daily": hm.target_daily(y)}
    tgt["daily_clim"] = pd.DataFrame({c: hm.monthly_climatology(tgt["daily"][c]) for c in tgt["daily"]},
                                     index=tgt["daily"].index)
    counts = hm.pair_counts("Temp", hm.pair_unit_tables(x, y, tgt), group=0)
    own = counts[(counts["support"] == "own") & (counts["scale"] == "hourly") & (counts["method"] == "raw")]
    assert own["n"].sum() == n and own["w"].sum() == n  # 0.2 < 0.5 everywhere
    # climatology is NaN in a single year -> common support empty
    assert counts[counts["support"] == "common"].empty
    assert set(counts.loc[counts["scale"] == "weekly_mean", "method"]) == {"raw", "calibrated", "persistence_7d"}


# ---------------------------------------------------------------- radius / gates / cells
def test_strict_radius_rules():
    r = hm.strict_radius
    assert r({"0-2": "pass", "2-5": "pass", "5-10": "fail", "10-20": "pass"}) == (5.0, "fail@5-10")
    assert r({"0-2": "fail"}) == (0.0, "fail@0-2")
    assert r({"2-5": "pass", "10-20": "pass"}) == (20.0, "no_pairs_beyond@10-20")  # empty bins skipped
    rad, stop = r({"0-2": "insufficient", "2-5": "pass"})
    assert np.isnan(rad) and stop == "insufficient@0-2"
    assert r({"0-2": "pass", "2-5": "insufficient", "5-10": "pass"}) == (2.0, "insufficient@2-5")
    assert np.isnan(r({})[0])
    assert r({b: "pass" for b in hm.RADIUS_BINS}) == (30.0, "all_pass")


def test_cell_record_gate_and_class():
    blocks = pd.DataFrame({"block": np.arange(40), "n": 10, "w": 10, "sae": 0.0,
                           **{c: 0 for c in hm.CONF_COLS}})
    blocks["c0"], blocks["c8"] = 8, 2
    rec = hm._cell_record(blocks, "value", "daily_mean", n_boot=50)
    assert rec["share"] == 1.0 and rec["gate95"] == "pass" and rec["n_days"] == 40
    rec = hm._cell_record(blocks.head(20), "class", "weekly_mean", n_boot=50)
    assert rec["gate80"] == "insufficient" and rec["block"] == "iso_week"
    assert rec["kappa"] == pytest.approx(1.0) and rec["bad_miss_rate"] == 0.0
    assert rec["bad_base_rate"] == pytest.approx(0.2)


def test_cell_table_and_baseline_compare_smoke():
    rows = []
    for method in hm.METHODS:
        for support in ("own", "common"):
            for b in range(35):
                w = 9 if method in hm.TRANSFERS else 5
                rows.append({"var": "DO", "scale": "daily_mean", "method": method, "support": support,
                             "regime": "same", "distance_bin": "0-2", "block": b, "n": 10, "w": w, "sae": 1.0,
                             **{c: 0 for c in hm.CONF_COLS}, "c0": 10})
    counts = pd.DataFrame(rows)
    members = counts[["var", "scale", "method", "regime", "distance_bin"]].drop_duplicates().assign(pair="0:a>b")
    cells = hm.cell_table("x", counts, members, n_boot=50)
    assert set(cells["regime"]) == {"same", "all"}
    raw = cells[(cells["metric"] == "value") & (cells["transfer_or_baseline"] == "raw")]
    assert set(cells["support"]) == {"own"}
    assert raw["share"].iloc[0] == 0.9 and raw["n_pairs"].iloc[0] == 1
    bc = hm.baseline_compare("x", counts, n_boot=50)
    rad = hm.radius_table(cells, bc)
    assert set(rad["transfer"]) == {"raw", "calibrated"}
    r80 = rad[(rad["regime"] == "same") & (rad["metric"] == "value") & (rad["transfer"] == "raw") & (rad["gate"] == 80)]
    assert r80["radius_km"].iloc[0] == 2.0 and bool(r80["beats_climatology_within"].iloc[0])
    row = bc[(bc["method"] == "raw") & (bc["metric"] == "value") & (bc["scope"] == "le30km") & (bc["regime"] == "same")]
    assert row["diff_vs_climatology"].iloc[0] == pytest.approx(0.4) and bool(row["beats_climatology"].iloc[0])
    cls = bc[(bc["metric"] == "class")]
    assert cls["class_degenerate"].all()  # no bad days at all
