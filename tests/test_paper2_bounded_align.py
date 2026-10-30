"""Trigger logic and bounded re-alignment of experiments/paper2_bounded_align.py (F4)."""
import json

import numpy as np
import pandas as pd
import pytest

from experiments.paper2_bounded_align import (
    DECAY_HALFLIFE_H,
    MECHS_RIDGE,
    BoundedInputs,
    assess_cp,
    forecasts,
    main,
    score,
    split_of,
)
from experiments.paper2_detect import DAY, changepoints_of, detect, fault_specs, flags_of
from experiments.paper2_faults import inject_event
from experiments.paper2_mechanisms import HORIZONS, RidgeModel, change_points, origin_times

PARAMS = {v: {"theta_step": 8.0, "theta_drift": 8.0, "stuck_k": 8} for v in ("DO_mgl", "Turb", "pH", "Temp")}
LN = np.log


def _z(level_pre=2.0, level_post=2.0 - LN(20), n=40, at=20, ramp=1):
    z = np.full(n, level_pre)
    z[at:] = level_post
    if ramp > 1:
        z[at:at + ramp] = level_pre + (level_post - level_pre) * (np.arange(1, ramp + 1) / ramp)
    return z


def _ref(n=40, at=20, step=0.0):
    t = np.full(n, 25.0)
    t[at:] += step
    return {"Temp": t}


def test_one_sample_step_passes_all_conditions():
    z = _z()
    s = assess_cp(z, 20, 22, -LN(20), True, _ref())
    assert s["instant"] and s["magnitude"] and s["ref_quiet"]
    assert s["jump_frac"] == pytest.approx(1.0)
    # the re-located split may land a few samples off the jump (dry run): still instantaneous
    for k in (18, 21, 22):
        assert assess_cp(z, k, 23, -LN(20), True, _ref())["instant"]


def test_ramp_over_four_samples_fails_instant():
    z = _z(ramp=4)
    s = assess_cp(z, 20, 23, -LN(20), True, _ref())
    assert not s["instant"] and s["magnitude"]
    # a two-sample step still counts as near-instantaneous
    s2 = assess_cp(_z(ramp=2), 20, 22, -LN(20), True, _ref())
    assert s2["instant"]


def test_coincident_temperature_move_fails_ref_quiet():
    s = assess_cp(_z(), 20, 22, -LN(20), True, _ref(step=0.8))
    assert s["instant"] and s["magnitude"] and not s["ref_quiet"]
    sal = {"Temp": _ref()["Temp"], "Sal": np.r_[np.full(20, 30.0), np.full(20, 26.0)]}
    assert not assess_cp(_z(), 20, 22, -LN(20), True, sal)["ref_quiet"]
    assert not assess_cp(_z(), 20, 22, -LN(20), True, {})["ref_quiet"]          # nothing to check -> not quiet


def test_small_ratio_and_linear_variables_fail_magnitude():
    z = _z(level_post=2.0 - LN(2))
    assert not assess_cp(z, 20, 22, -LN(2), True, _ref())["magnitude"]
    assert not assess_cp(_z(), 20, 22, -LN(20), False, _ref())["magnitude"]    # pH / Temp never re-aligned


def test_gap_before_the_step_fails_instant():
    z = _z()
    z[19] = np.nan
    assert not assess_cp(z, 20, 22, -LN(20), True, _ref())["instant"]


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


def _inputs(x, target="DO_mgl", temp_step_at=None):
    det = detect(x, PARAMS)
    ref = pd.DataFrame({"Temp": x["Temp"].copy()})
    if temp_step_at is not None:
        ref.loc[temp_step_at:, "Temp"] += 2.0
    return BoundedInputs(x[target], flags_of(det)[target], change_points(changepoints_of(det)[target]), target, ref=ref)


def _faulted(kind="scale_down", days=60, at=45):
    f = _frame(days)
    onset = f.index[at * DAY]
    x, _ = inject_event(f, fault_specs(kind, f, onset), onset)
    return f, x, onset


def test_variants_realign_an_injected_rescale_and_are_causal():
    f, x, onset = _faulted()
    inp = _inputs(x)
    assert inp.qual["v1"] and inp.qual["v2"]
    t = onset + pd.Timedelta(hours=12)
    pre = x["DO_mgl"][onset - pd.Timedelta(hours=24):onset - pd.Timedelta(minutes=15)].median()
    for v in ("v1", "v2"):
        s = inp.build(inp.key(v, t))[onset + pd.Timedelta(hours=1):t]
        assert abs(s.median() / pre - 1) < 0.25
    # before the alarm the variants use (a) exactly
    early = onset - pd.Timedelta(minutes=15)
    assert inp.key("v1", early) == ("a",)
    pd.testing.assert_series_equal(inp.build(inp.key("v2", early)), x["DO_mgl"].astype(float))
    # causality: truncating the data after t does not change the key / input up to t
    part = _inputs(x[:t])
    for v in ("v1", "v2", "v3"):
        assert inp.key(v, t) == part.key(v, t)
        pd.testing.assert_series_equal(inp.build(inp.key(v, t))[:t], part.build(part.key(v, t))[:t], check_freq=False)


def test_temperature_step_blocks_v2_but_not_v1():
    _, x, onset = _faulted()
    inp = _inputs(x, temp_step_at=onset)
    assert inp.qual["v1"] and not inp.qual["v2"] and not inp.qual["v3"]
    assert inp.key("v2", onset + pd.Timedelta(hours=6)) == ("a",)


def test_v3_decay_and_latest_only():
    _, x, onset = _faulted()
    inp = _inputs(x)
    i = inp.qual["v3"][-1]
    alarm = inp.assess[i]["alarm"]
    k = inp.key("v3", alarm + pd.Timedelta(hours=DECAY_HALFLIFE_H))
    assert k[0] == "shift" and k[2] == pytest.approx(0.5)
    # a second qualifying step replaces the first (no accumulation)
    y = x.copy()
    t2 = onset + pd.Timedelta(days=3)
    y.loc[t2:, "DO_mgl"] = y.loc[t2:, "DO_mgl"] * 10.0
    inp2 = _inputs(y)
    q = inp2.qual["v1"]
    assert len(q) >= 2
    late = t2 + pd.Timedelta(hours=6)
    key = inp2.key("v1", late)
    assert key[1] == q[-1]
    s = inp2.build(key)
    # only the latest shift (x10 -> about /10) is applied after t2; the /20 step before it stays uncorrected
    mid = s[onset + pd.Timedelta(hours=6):t2 - pd.Timedelta(hours=1)].median()
    assert mid == pytest.approx(x["DO_mgl"][onset + pd.Timedelta(hours=6):t2 - pd.Timedelta(hours=1)].median())


def test_silent_variants_reuse_the_a_forecast():
    f = _frame(70)
    rm = RidgeModel(-5)
    for h in HORIZONS:
        rm.fit([_frame(60, seed=5, start="2008-03-01")["DO_mgl"]], h)
    onset = f.index[55 * DAY]
    inp = _inputs(f)                               # clean: nothing qualifies
    assert not any(inp.qual.values())
    o = origin_times(onset)
    fc, _ = forecasts("ridge", rm, inp, o, MECHS_RIDGE)
    for v in ("v1", "v2", "v3"):
        for h in HORIZONS:
            np.testing.assert_array_equal(fc[(v, h)][0], fc[("a", h)][0])
    _, x, onset2 = _faulted(days=70, at=55)
    rows = score("ridge", rm, f["DO_mgl"], x["DO_mgl"], _inputs(x), onset2, MECHS_RIDGE)
    r = {(z["mech"], z["horizon_min"]): z for z in rows}
    assert r[("v2", 60)]["mae_post24"] < 0.5 * r[("a", 60)]["mae_post24"]


def test_split_is_deterministic_and_balanced_enough():
    sts = [f"s{i:02d}" for i in range(40)]
    s = [split_of(x) for x in sts]
    assert s == [split_of(x) for x in sts] and 10 <= s.count("cal") <= 30


def test_forecast_stages_require_preregistration(tmp_path):
    with pytest.raises(RuntimeError, match="prereg"):
        main(["ridge", "--output", str(tmp_path / "run")])
    main(["prereg", "--output", str(tmp_path / "run")])
    pre = json.loads((tmp_path / "run" / "preregistration.json").read_text(encoding="utf-8"))
    assert pre["git_head"] and pre["gate"]["G1"] and set(pre["variants"]) == {"v1", "v2", "v3"}
    with pytest.raises(FileExistsError):
        main(["prereg", "--output", str(tmp_path / "run")])
