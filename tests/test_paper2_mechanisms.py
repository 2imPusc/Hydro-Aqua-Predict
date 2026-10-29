"""Mechanism inputs, online post-processing and per-injection scoring of experiments/paper2_mechanisms.py (F3)."""
import numpy as np
import pandas as pd
import pytest

from experiments.paper2_detect import DAY, changepoints_of, detect, flags_of
from experiments.paper2_faults import inject_event
from experiments.paper2_detect import fault_specs
from experiments.paper2_mechanisms import (
    HORIZONS,
    MECHS,
    Inputs,
    RidgeModel,
    aci_intervals,
    change_points,
    contexts_for,
    online_bias,
    origin_times,
    recovery_hours,
    score_one,
)

PARAMS = {v: {"theta_step": 8.0, "theta_drift": 8.0, "stuck_k": 8} for v in ("DO_mgl", "Turb", "pH", "Temp")}


def _frame(days=60, seed=0, start="2009-03-01"):
    idx = pd.date_range(start, periods=days * DAY, freq="15min")
    rng = np.random.default_rng(seed)
    diel = np.sin(2 * np.pi * np.arange(len(idx)) / DAY)
    return pd.DataFrame({
        "DO_mgl": 6.5 + 0.8 * diel + rng.normal(0, 0.08, len(idx)),
        "Turb": np.exp(np.log(8) + 0.2 * diel + rng.normal(0, 0.1, len(idx))),
        "pH": np.round(7.9 + 0.05 * diel + rng.normal(0, 0.03, len(idx)), 2),
        "Temp": 24 + 1.0 * diel + rng.normal(0, 0.05, len(idx)),
    }, index=idx)


def _inputs(obs_frame, target="DO_mgl"):
    det = detect(obs_frame, PARAMS)
    return Inputs(obs_frame[target], flags_of(det)[target], change_points(changepoints_of(det)[target]), target)


def _faulted(kind="scale_down", days=60, at=45):
    f = _frame(days)
    onset = f.index[at * DAY]
    x, _ = inject_event(f, fault_specs(kind, f, onset), onset)
    return f, x, onset


def test_mechanism_inputs_are_causal():
    _, x, onset = _faulted()
    cut = onset + pd.Timedelta(hours=30)
    full, part = _inputs(x), _inputs(x[:cut])
    for t in origin_times(onset):
        if t > cut:
            break
        for mech in MECHS:
            a = full.series(mech, t)[:t]
            b = part.series(mech, t)[:t]
            pd.testing.assert_series_equal(a, b, check_freq=False, check_names=False)


def test_restart_and_level_alignment_after_scale_step():
    _, x, onset = _faulted()
    inp = _inputs(x)
    assert inp.cps, "step must be detected"
    t = onset + pd.Timedelta(hours=12)
    pre = x["DO_mgl"][onset - pd.Timedelta(hours=24):onset - pd.Timedelta(minutes=15)].median()
    c = inp.series("c", t)
    assert c[:onset - pd.Timedelta(hours=2)].isna().all() and c[onset:t].notna().any()
    al = inp.series("c_align", t)[onset + pd.Timedelta(hours=1):t]
    raw = x["DO_mgl"][onset + pd.Timedelta(hours=1):t]
    assert abs(al.median() / pre - 1) < 0.25 < abs(raw.median() / pre - 1)
    # before the change point is detected, (c) / (c') equal (b)
    early = onset - pd.Timedelta(hours=1)
    pd.testing.assert_series_equal(inp.series("c", early), inp.series("b", early))


def test_online_bias_converges_and_uses_only_realised_residuals():
    o = pd.date_range("2009-01-01", periods=100, freq="1h")
    pred = np.zeros(100)
    obs = np.full(100, 2.0)
    obs[60:] = 50.0                      # residuals realised only after t_i + 1 h
    b = online_bias(o, pred, obs, 60)
    assert b[0] == 0.0 and b[1] == pytest.approx(2.0)
    assert b[60] == pytest.approx(2.0)   # residual of origin 60 is realised at 61
    assert b[99] > 40


def test_aci_widens_after_a_shift_and_keeps_calibrated_case():
    o = pd.date_range("2009-01-01", periods=300, freq="1h")
    rng = np.random.default_rng(1)
    y = rng.normal(0, 1, 300)
    lo, hi = np.full(300, -1.2816), np.full(300, 1.2816)
    alo, ahi = aci_intervals(o, lo, hi, y, 60)
    assert 0.7 < np.mean((y >= alo) & (y <= ahi)) < 0.9
    y2 = y.copy()
    y2[150:] += 5
    blo, bhi = aci_intervals(o, lo, hi, y2, 60)
    assert np.mean((y2[220:] >= blo[220:]) & (y2[220:] <= bhi[220:])) > 0.6
    assert (bhi[:150] == ahi[:150]).all()   # nothing changes before the shift is realised


def test_contexts_pad_left_and_recovery():
    s = pd.Series(np.arange(10.0), index=pd.date_range("2009-01-01", periods=10, freq="15min"))
    ctx = contexts_for(s, s.index[[2, 9]])
    assert np.isnan(ctx[0, :-3]).all() and ctx[0, -1] == 2.0 and ctx[1, -1] == 9.0
    o = pd.date_range("2009-01-01", periods=30, freq="1h")
    err = np.r_[np.ones(10), np.full(8, 10.0), np.ones(12)]
    assert recovery_hours(o, err, o[10], 1.0) == pytest.approx(13.0)


def test_ridge_and_score_one_end_to_end():
    f = _frame(70)
    rm = RidgeModel(-5)
    for h in HORIZONS:
        rm.fit([_frame(60, seed=5, start="2008-03-01")["DO_mgl"]], h)
    onset = f.index[55 * DAY]
    rows = score_one("ridge", rm, f, "scale_down", "DO_mgl", onset, PARAMS, sham=False)
    assert len(rows) == len(MECHS) * len(HORIZONS)
    r = {(x["mech"], x["horizon_min"]): x for x in rows}
    assert r[("a", 60)]["mae_baseline"] < 0.5
    assert r[("c_align", 60)]["mae_post24"] < 0.5 * r[("a", 60)]["mae_post24"]
    sham = score_one("ridge", rm, f, "scale_down", "DO_mgl", onset, PARAMS, sham=True)
    assert all(np.isfinite(x["mae_post24"]) for x in sham)
