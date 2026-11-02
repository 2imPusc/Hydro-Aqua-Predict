"""F5 (NH4 faults on hourly MOF data): injection, clean filter, split, detectors, mechanisms, decision rule."""
import numpy as np
import pandas as pd
import pytest

from experiments import paper2_f5_nh4 as f5

LN = np.log


def _hours(n, start="2020-01-01"):
    return pd.date_range(start, periods=n, freq="h")


def _nh4(n=24 * 60, level=100.0, seed=0, start="2020-01-01"):
    """Positive hourly series with a diurnal cycle and multiplicative noise, resolution 0.5."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    x = level * np.exp(0.3 * np.sin(2 * np.pi * t / 24) + rng.normal(0, 0.1, n))
    return pd.Series(np.round(x / 0.5) * 0.5, index=_hours(n, start), name="NH4")


def _frame(n=24 * 60, seed=0, start="2020-01-01"):
    x = _nh4(n, seed=seed, start=start)
    rng = np.random.default_rng(seed + 1)
    return pd.DataFrame({"NH4": x, "temp": 20 + rng.normal(0, 0.05, n), "sal": 30 + rng.normal(0, 0.1, n)}, index=x.index)


# ----------------------------------------------------------------------------------------- faults

@pytest.mark.parametrize("kind,factor", [("scale_down", f5.E1_FACTOR), ("scale_up", f5.E3_FACTOR)])
def test_rescale_one_sample_requantised(kind, factor):
    fr = _frame()
    t = fr.index[24 * 30]
    out, lab = f5.inject_nh4(fr, kind, t, 0.5)
    assert out["NH4"][:t - pd.Timedelta(hours=1)].equals(fr["NH4"][:t - pd.Timedelta(hours=1)])
    post = out["NH4"][t:]
    assert np.allclose(post, np.round(fr["NH4"][t:] * factor / 0.5) * 0.5)
    assert np.allclose(post / 0.5, np.round(post / 0.5))  # on the resolution grid
    assert lab["NH4"][t:].eq("scale_step").all() and lab["NH4"][:t - pd.Timedelta(hours=1)].eq("").all()
    assert out[["temp", "sal"]].equals(fr[["temp", "sal"]])


def test_task_factors_match_f1_catalogue():
    assert 1 / f5.E1_FACTOR == pytest.approx(20.013, abs=1e-3)
    assert f5.E3_FACTOR == pytest.approx(6.72, abs=0.01)  # the "x6.7" of RL-72 / the task (30-s anatomy)
    assert 1 / f5.DRIFT_FACTOR == pytest.approx(12.52, abs=0.01)


def test_drift_down_log_linear_then_held():
    fr = _frame()
    fr["NH4"] = 400.0
    t = fr.index[24 * 20]
    out, lab = f5.inject_nh4(fr, "drift_down", t, 0.0)
    half = t + pd.Timedelta(hours=f5.DRIFT_DAYS * 12)
    assert out["NH4"][half] == pytest.approx(400 * f5.DRIFT_FACTOR ** 0.5)
    end = t + pd.Timedelta(days=f5.DRIFT_DAYS)
    assert out["NH4"][end:].to_numpy() == pytest.approx(400 * f5.DRIFT_FACTOR)
    assert out["NH4"][t] == pytest.approx(400.0) and lab["NH4"][t:].eq("ramp").all()


def test_stuck_freezes_last_valid_value():
    fr = _frame()
    t = fr.index[24 * 20]
    fr.loc[t - pd.Timedelta(hours=1), "NH4"] = np.nan
    before = fr["NH4"][t - pd.Timedelta(hours=2)]
    out, lab = f5.inject_nh4(fr, "stuck", t, 0.5)
    assert (out["NH4"][t:] == before).all()
    assert lab["NH4"][t:].eq("stuck").all()


def test_gap_is_three_hourly_samples_on_all_channels():
    fr = _frame()
    t = fr.index[24 * 20]
    out, _ = f5.inject_nh4(fr, "gap", t, 0.5)
    miss = out.isna().all(axis=1)
    assert list(out.index[miss]) == [t, t + pd.Timedelta(hours=1), t + pd.Timedelta(hours=2)]


# ----------------------------------------------------------------------------------------- clean filter

def test_clean_filter_rules():
    x = _nh4(24 * 30)
    x.iloc[100:106] = 50.0           # 6 h stuck -> invalid + dirty
    x.iloc[200:205] = 60.0           # 5 h -> valid
    x.iloc[300] = 0.0                # zero -> missing, dirty (hard)
    x.iloc[301] = -3.0               # negative -> missing, not present
    x.iloc[400:] = x.iloc[400:] * 5  # persistent x5 shift -> marker, +-24 h dirty, values kept
    cf = f5.clean_filter(x)
    v, d = cf["valid"].to_numpy(), cf["dirty"].to_numpy()
    assert not v[100:106].any() and d[100:106].all()
    assert v[200:205].all() and not d[200:205].any()
    assert not v[300] and d[300] and not v[301]
    assert x.index[400] in cf["markers"]
    assert d[400 - 24:400 + 25].all() and v[400:410].all()
    assert cf["base"].iloc[400] == x.iloc[400]
    assert cf["shares"]["stuck_share"] == pytest.approx(6 / cf["shares"]["present_hours"], abs=1e-5)
    sens = f5.clean_filter(x, stuck_h=3, zero_invalid=False)
    assert not sens["valid"].to_numpy()[200:205].any() and sens["valid"].to_numpy()[300]


def test_shift_markers_ignore_reverting_spike():
    x = _nh4(24 * 30)
    x.iloc[300:303] *= 10            # 3-h spike that reverts: not persistent over 72 h
    assert len(f5.shift_markers(x, 72)) == 0


# ----------------------------------------------------------------------------------------- split + placement

def test_split_and_scoring_windows_never_touch_calibration():
    n = 24 * 400
    x = _nh4(n)
    cf = f5.clean_filter(x)
    ts = f5.time_split(cf["valid"])
    assert abs(cf["valid"][:ts].sum() - cf["valid"].sum() / 2) <= 1
    score = (ts, x.index[-1] + pd.Timedelta(hours=1))
    cand = f5.eligible_onsets(cf["valid"], cf["dirty"], score)
    assert len(cand) and (cand - f5.WIN_BEFORE >= ts).all() and (cand + f5.WIN_AFTER <= x.index[-1]).all()
    cal = f5.eligible_onsets(cf["valid"], cf["dirty"], (x.index[0], ts))
    assert (cal + f5.WIN_AFTER < ts).all()
    a = f5.place_h(cand, 40, f5._rng("s", "score"))
    b = f5.place_h(cand, 40, f5._rng("s", "score"))
    assert a == b and len(a) > 5
    assert all(np.diff(pd.DatetimeIndex(a)) >= f5.MIN_SEP)


def test_eligible_excludes_dirty_and_low_validity():
    n = 24 * 120
    x = _nh4(n)
    x.iloc[24 * 60:24 * 60 + 8] = 70.0          # stuck run at day 60
    x.iloc[24 * 90:24 * 100] = np.nan           # 10 d missing
    cf = f5.clean_filter(x)
    cand = f5.eligible_onsets(cf["valid"], cf["dirty"], (x.index[0], x.index[-1] + pd.Timedelta(hours=1)))
    stuck_t = x.index[24 * 60]
    assert not ((cand > stuck_t - pd.Timedelta(days=7)) & (cand < stuck_t + pd.Timedelta(days=2, hours=8))).any()
    hole = x.index[24 * 95]
    assert not (abs(cand - hole) < pd.Timedelta(days=4)).any()


# ----------------------------------------------------------------------------------------- detectors

def test_detectors_are_causal():
    x = _nh4(24 * 50)
    y = x.copy()
    y.iloc[24 * 40:] *= 20
    for fn in (f5.step_score_h, f5.drift_score_h):
        a, b = fn(x), fn(y)
        pd.testing.assert_series_equal(a.iloc[:24 * 40], b.iloc[:24 * 40])
    params = {"theta_step": 10.0, "theta_drift": 5.0, "stuck_k": 6}
    da, db = f5.detect_h(x, params), f5.detect_h(y, params)
    for k in da:
        assert da[k].iloc[:24 * 40].equals(db[k].iloc[:24 * 40])


def test_calibration_meets_fa_target_and_detects_rescale():
    x = _nh4(24 * 200, seed=3)
    p = f5.calibrate_h([x])
    det = f5.detect_h(x, p)
    days = x.notna().sum() / 24
    assert len(f5.episodes(det["step"], f5.MERGE_H)) * 30 / days <= f5.FA_TARGET_PER_30D
    y, _ = f5.inject_nh4(pd.DataFrame({"NH4": x}), "scale_down", x.index[24 * 150], 0.5)
    hit = f5.detect_h(y["NH4"], p)["step"].loc[x.index[24 * 150]:x.index[24 * 150] + pd.Timedelta(hours=6)]
    assert hit.any()


def test_refine_and_assess_match_f3_f4_with_w4():
    """Hourly re-statements reproduce F3 ``Inputs._refine`` and F4 ``assess_cp`` when w = 4 (F2's W)."""
    from experiments.paper2_bounded_align import assess_cp
    from experiments.paper2_mechanisms import Inputs

    x = _nh4(24 * 20, seed=5)
    x.iloc[300:] = x.iloc[300:] / 20
    t = pd.Series(20.0, index=x.index)
    t.iloc[301:] += 0.7
    z = f5.z_of(x).to_numpy()
    for a_i in (301, 302, 304):
        alarm = x.index[a_i]
        f3 = Inputs(x, pd.Series(False, index=x.index), [(alarm, alarm - pd.Timedelta(hours=3))], "DO_mgl", c=1.0)
        _, cp3, d3 = f3.cps[0]
        k, d = f5.refine_cp(z, a_i, 4)
        assert x.index[k] == cp3 and d == pytest.approx(d3)
        ref4 = assess_cp(z, k, a_i, d, True, {"Temp": t.to_numpy()})
        ref5 = f5.assess_cp_h(z, k, a_i, d, {"temp": t.to_numpy()}, w=4)
        for key in ("instant", "magnitude", "ref_quiet", "jump"):
            assert ref5[key] == ref4[key]


# ----------------------------------------------------------------------------------------- mechanisms

def _inputs(sal_step=0.0, factor=1 / 20):
    fr = _frame(24 * 50, seed=7)
    t = fr.index[24 * 45]
    fr.loc[t:, "NH4"] *= factor
    fr.loc[t:, "sal"] += sal_step
    params = {"theta_step": 8.0, "theta_drift": 1e9, "stuck_k": None}
    det = f5.detect_h(fr["NH4"], params)
    inp = f5.F5Inputs(fr["NH4"], f5.flags_h(det), f5.change_points_h(det["step"]), ref=fr[["temp", "sal"]])
    return fr, t, inp


def test_bounded_variants_trigger_and_realign():
    fr, t, inp = _inputs()
    later = t + pd.Timedelta(hours=12)
    for v in ("v2", "c_align"):
        key = inp.key(v, later)
        assert key[0] in ("shift", "c_align")
        ser = inp.build(key)
        ratio = ser[t:later].median() / fr["NH4"][t - pd.Timedelta(hours=24):t].median()
        assert 0.6 < ratio < 1.6       # back near the pre-fault level (x1/20 undone)
    assert inp.key("v2", t - pd.Timedelta(hours=1)) == ("a",)
    assert inp.key("a", later) == ("a",) and inp.key("d", later) == ("a",)
    k3 = inp.key("v3", t + pd.Timedelta(hours=72 + 3))
    assert k3[0] == "shift" and k3[2] < 0.55


def test_v2_blocked_when_salinity_moves():
    _, t, inp = _inputs(sal_step=3.0)
    assert inp.key("v2", t + pd.Timedelta(hours=12)) == ("a",)
    assert inp.key("v1", t + pd.Timedelta(hours=12))[0] == "shift"


def test_ridge_features_causal_and_fit_predict():
    fr = _frame(24 * 60, seed=9)
    idx = np.arange(24 * 30, 24 * 31)
    a = f5.ridge_features(fr["NH4"], fr[["temp", "sal"]], idx, 6)
    g = fr.copy()
    g.iloc[24 * 31:] = g.iloc[24 * 31:] * 3
    b = f5.ridge_features(g["NH4"], g[["temp", "sal"]], idx, 6)
    pd.testing.assert_frame_equal(a[f5.RIDGE_FEATURES + ["current"]], b[f5.RIDGE_FEATURES + ["current"]])
    m = f5.RidgeH().fit(fr["NH4"][:24 * 40], fr[["temp", "sal"]][:24 * 40])
    o = fr.index[24 * 45:24 * 46]
    p, lo, hi = m.predict(fr["NH4"], fr[["temp", "sal"]], o, 60)
    assert np.all(lo <= p) and np.all(p <= hi)
    assert np.mean(np.abs(p - fr["NH4"].reindex(o + pd.Timedelta(hours=1)).to_numpy())) < 30


def test_run_injection_end_to_end_ridge():
    fr = _frame(24 * 60, seed=11)
    t = fr.index[24 * 45]
    m = f5.RidgeH().fit(fr["NH4"][:24 * 30], fr[["temp", "sal"]][:24 * 30])
    params = f5.calibrate_h([fr["NH4"][:24 * 30]])
    win = fr[t - f5.WIN_BEFORE:t + f5.WIN_AFTER]
    rows = f5.run_injection("ridge", m, win, win["NH4"], "scale_down", t, params, 0.5, False, 1e9)
    df = pd.DataFrame(rows)
    assert set(df["mech"]) == set(f5.MECHS) and set(df["horizon_min"]) == {60, 360}
    one = df[df["horizon_min"] == 60].set_index("mech")
    assert one.loc["v2", "mae_post24"] < 0.5 * one.loc["a", "mae_post24"]  # bounded re-alignment undoes /20
    sham = pd.DataFrame(f5.run_injection("ridge", m, win, win["NH4"], "sham_random", t, params, 0.5, True, 1e9))
    s1 = sham[sham["horizon_min"] == 60].set_index("mech")
    assert s1.loc["v2", "mae_post24"] == pytest.approx(s1.loc["a", "mae_post24"])  # silent trigger == (a)


# ----------------------------------------------------------------------------------------- decision rule

def test_reduction_stats_and_holm():
    rng = np.random.default_rng(0)
    a = rng.uniform(1, 2, 20)
    r = f5.reduction_stats(0.5 * a * np.exp(rng.normal(0, 0.05, 20)), a)
    assert r["reduction"] == pytest.approx(0.5, abs=0.05) and r["p"] < 0.01 and r["ci_lo"] > 0.4
    adj = f5.holm({"x": 0.01, "y": 0.04, "z": 0.03})
    assert adj == pytest.approx({"x": 0.03, "z": 0.06, "y": 0.06})


def _summary(red: dict, harm: dict, n=20, p=0.001):
    rows = []
    for st, per_type in red.items():
        for mech in f5.TESTED:
            for kind in f5.RULE_KINDS:
                rr = per_type.get(kind, 0.0) if mech == "c_align" else 0.0
                rows.append({"model": "ridge", "station": st, "set": kind, "mech": mech, "n": n, "reduction": rr,
                             "ci_lo": rr - 0.1, "ci_hi": rr + 0.1, "p": p if rr else 0.8})
            for s in ("sham_random", "sham_event"):
                h = harm.get(st, 0.0) if mech == "c_align" else 0.0
                rows.append({"model": "ridge", "station": st, "set": s, "mech": mech, "n": n, "reduction": -h,
                             "ci_lo": -h - 0.1, "ci_hi": -h + 0.1, "p": 0.5})
    return pd.DataFrame(rows)


def test_rule_three_of_four_types_two_of_three_stations():
    good = {"scale_down": 0.6, "scale_up": 0.5, "drift_down": 0.35}
    summ = _summary({"A": good, "B": good, "C": {"scale_down": 0.6, "scale_up": 0.5}}, {"A": 0.03, "B": 0.04})
    _, st = f5.verdict(summ)
    c = st[st["mech"] == "c_align"].set_index("station")
    assert c.loc["A", "useful_station"] and c.loc["B", "useful_station"]
    assert not c.loc["C", "useful_station"]            # only the two re-scales: 2/4
    assert c["useful"].all() and c["stations_useful"].iloc[0] == 2
    assert not st[st["mech"] == "b"]["useful"].any()


def test_rule_harm_above_five_percent_fails_station():
    good = {"scale_down": 0.6, "scale_up": 0.5, "stuck": 0.4}
    _, st = f5.verdict(_summary({"A": good, "B": good, "C": good}, {"A": 0.06, "B": 0.06, "C": 0.01}))
    c = st[st["mech"] == "c_align"].set_index("station")
    assert not c.loc["A", "useful_station"] and c.loc["C", "useful_station"]
    assert not c["useful"].any()                       # 1/3 stations


def test_rule_small_gain_or_small_n_does_not_pass():
    summ = _summary({"A": {"scale_down": 0.25, "scale_up": 0.6, "drift_down": 0.6, "stuck": 0.6}}, {})
    tests, _ = f5.verdict(summ)
    t = tests[tests["mech"] == "c_align"].set_index("set")
    assert not t.loc["scale_down", "pass"] and t.loc["scale_up", "pass"]
    tests2, st2 = f5.verdict(_summary({"A": {"scale_down": 0.6, "scale_up": 0.6, "drift_down": 0.6}}, {}, n=5))
    assert not tests2["pass"].any() and not st2["useful_station"].any()


def test_rule_holm_can_remove_a_marginal_pass():
    red = {"A": {"scale_down": 0.6, "scale_up": 0.6, "drift_down": 0.6}}
    tests, _ = f5.verdict(_summary(red, {}, p=0.002))
    assert tests[tests["mech"] == "c_align"]["pass"].sum() == 3   # smallest of 20: 0.002 x 20 = 0.04 < 0.05
    t2, _ = f5.verdict(_summary(red, {}, p=0.004))
    assert t2[t2["mech"] == "c_align"]["pass"].sum() == 0          # raw 0.004, Holm 0.08


def test_write_new_refuses_overwrite(tmp_path):
    p = tmp_path / "x.json"
    f5._write_new(p, {"a": 1})
    with pytest.raises(FileExistsError):
        f5._write_new(p, {"a": 2})
