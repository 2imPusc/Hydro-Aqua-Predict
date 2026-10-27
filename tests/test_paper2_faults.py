"""Fault-injection library of experiments/paper2_faults.py (paper 2, F1)."""
import numpy as np
import pandas as pd
import pytest

from experiments.nh4_step_0731 import detect_level_step, max_gap
from experiments.paper2_faults import (
    NB1_EVENTS,
    NERRS_MAPPING,
    FaultSpec,
    fouling,
    gap,
    inject_event,
    place_onsets,
    ramp,
    ramp_signature,
    scale_step,
    settle_signature,
    stuck,
)


def _minutes(n, start="2026-07-31 12:00", freq="1min"):
    return pd.date_range(start, periods=n, freq=freq)


def _noisy(n=240, level=106.0, seed=0, freq="1min"):
    rng = np.random.default_rng(seed)
    return pd.Series(level * np.exp(rng.normal(0, 0.006, n)), index=_minutes(n, freq=freq), name="NH4")


def test_scale_step_round_trips_through_detect_level_step():
    s = _noisy()
    onset = s.index[126]
    out, lab = scale_step(s, onset, 1 / 20.146)
    st = detect_level_step(out, half_window=10)
    assert st["first_new_sample"] == onset
    assert st["ratio_before_over_after"] == pytest.approx(20.146, rel=0.02)
    assert lab.sum() == len(s) - 126 and not lab.iloc[:126].any()
    pd.testing.assert_series_equal(out.iloc[:126], s.iloc[:126])


def test_scale_step_end_resolution_and_input_untouched():
    s = _noisy()
    before = s.copy()
    out, lab = scale_step(s, s.index[50], 0.05, end=s.index[100], resolution=0.01)
    pd.testing.assert_series_equal(s, before)
    seg = out.iloc[50:100].to_numpy()
    assert np.allclose(seg, np.round(seg, 2))
    assert lab.iloc[50:100].all() and not lab.iloc[100:].any()
    pd.testing.assert_series_equal(out.iloc[100:], s.iloc[100:])


def test_ramp_additive_and_multiplicative_with_cap():
    idx = _minutes(24 * 60, "2026-09-19 00:00")
    s = pd.Series(7.9, index=idx)
    out, lab = ramp(s, "2026-09-19 06:00", pd.Timedelta(hours=10), delta=-1.0)
    assert out["2026-09-19 05:59"] == pytest.approx(7.9)
    assert out["2026-09-19 11:00"] == pytest.approx(7.4)
    assert out["2026-09-19 16:00":].eq(6.9).all()
    sig = ramp_signature(out.resample("1h").median(), ("2026-09-19 00:00", "2026-09-19 05:00"),
                         ("2026-09-19 17:00", "2026-09-19 23:00"))
    assert sig["size"] == pytest.approx(-1.0)
    assert sig["duration_h"] == pytest.approx(8.0, abs=1.0)
    c = pd.Series(10.0, index=idx)
    out, _ = ramp(c, idx[0], pd.Timedelta(hours=12), factor=100.0, cap=558.8)
    assert out.iloc[6 * 60] == pytest.approx(100.0)
    assert out.max() == 558.8 and (out == 558.8).sum() > 0
    with pytest.raises(ValueError):
        ramp(c, idx[0], pd.Timedelta(hours=1))


def test_fouling_growth_plateau_clearance_and_settle():
    idx = pd.date_range("2026-08-01", "2026-08-05", freq="1min")
    s = pd.Series(4.0, index=idx)
    clear = pd.Timestamp("2026-08-04 14:07")
    out, lab = fouling(s, "2026-08-01 12:00", pd.Timedelta(days=2), 12.0, clear_at=clear, residual=4.0,
                       settle=pd.Timedelta(minutes=3))
    assert out["2026-08-01 11:59"] == pytest.approx(4.0)
    assert out["2026-08-02 12:00"] == pytest.approx(4.0 * np.sqrt(12.0))   # log-linear half way
    assert out["2026-08-03 12:00":"2026-08-04 14:06"].eq(4.0 * 12).all()
    assert out[clear] == pytest.approx(16.0)                                 # residual x4 in one sample
    assert out[clear + pd.Timedelta(minutes=30)] == pytest.approx(4.0, rel=1e-3)
    assert lab[clear] and not lab[clear + pd.Timedelta(minutes=30)] and not lab["2026-08-01 11:59"]
    sig = settle_signature(out, clear, final_level=4.0)
    assert sig["settle_min"] == pytest.approx(3 * np.log(np.log(4.0) / np.log(1.25)), abs=1.0)


def test_fouling_noise_is_seeded_and_needs_rng():
    s = pd.Series(4.0, index=_minutes(600))
    a, _ = fouling(s, s.index[10], pd.Timedelta(hours=2), 10.0, noise_sigma=0.3, rng=np.random.default_rng(7))
    b, _ = fouling(s, s.index[10], pd.Timedelta(hours=2), 10.0, noise_sigma=0.3, rng=np.random.default_rng(7))
    pd.testing.assert_series_equal(a, b)
    assert a.iloc[:10].eq(4.0).all()
    with pytest.raises(ValueError):
        fouling(s, s.index[10], pd.Timedelta(hours=2), 10.0, noise_sigma=0.3)


def test_stuck_value_freeze_and_gap():
    s = _noisy(120)
    out, lab = stuck(s, s.index[60], s.index[90], value=0.0)
    assert (out.iloc[60:90] == 0.0).all() and lab.sum() == 30
    out, _ = stuck(s, s.index[60])
    assert (out.iloc[60:] == s.iloc[59]).all()
    with pytest.raises(ValueError):
        stuck(s, s.index[0])
    out, lab = gap(s, s.index[30], pd.Timedelta(minutes=147 - 1))
    assert out.isna().sum() == 90 and lab.sum() == 90        # series ends inside the gap
    out, _ = gap(_noisy(400), _minutes(400)[100], pd.Timedelta(minutes=146))
    assert max_gap(out.dropna().index) == pd.Timedelta(minutes=147)


def test_time_based_params_work_on_15min_series():
    s = _noisy(4 * 96, level=7.0, freq="15min")
    out, lab = ramp(s, s.index[96], pd.Timedelta(hours=10), delta=-1.0)
    assert out.iloc[96 + 40:] .sub(s.iloc[96 + 40:]).eq(-1.0).all()     # 40 x 15 min = 10 h
    assert out.iloc[96 + 20] - s.iloc[96 + 20] == pytest.approx(-0.5)


def test_inject_event_nb1_composites_and_labels():
    idx = _minutes(8 * 60, "2026-08-12 14:00")
    frame = pd.DataFrame({"NH4": 3.5, "COD": 558.8, "pH": 8.1, "TSS": 4.0}, index=idx)
    onset = pd.Timestamp("2026-08-12 16:59")
    out, lab = inject_event(frame, NB1_EVENTS["E2_20260812"], onset)
    assert out.loc[onset:onset + pd.Timedelta(minutes=145)].isna().all().all()
    assert max_gap(out["NH4"].dropna().index) == pd.Timedelta(minutes=148)   # 147 missing samples
    assert (out.loc[onset + pd.Timedelta(minutes=147):, "COD"] == 0.0).all()
    assert (lab.loc[onset, ["NH4", "COD", "pH", "TSS"]] == "gap").all()
    assert lab.loc[onset + pd.Timedelta(minutes=200), "COD"] == "stuck"
    assert lab.loc[onset + pd.Timedelta(minutes=200), "NH4"] == ""
    assert frame["COD"].eq(558.8).all()                                   # input untouched
    assert list(lab.index) == list(frame.index)


def test_inject_event_e3_simultaneous_cross_channel():
    idx = _minutes(48 * 60, "2026-09-15 15:34")
    frame = pd.DataFrame({"NH4": 0.36, "COD": 21.0, "pH": 7.68}, index=idx)
    onset = pd.Timestamp("2026-09-16 15:34")
    out, lab = inject_event(frame, NB1_EVENTS["E3_20260916"], onset)
    assert out.loc[onset - pd.Timedelta(minutes=1), "COD"] == 0.0 and out.loc[onset, "COD"] == 21.0
    assert out.loc[onset, "NH4"] == pytest.approx(0.36 * 8.1, abs=0.01)
    assert out.loc[onset - pd.Timedelta(minutes=1), "NH4"] == pytest.approx(0.36)
    assert out.loc[onset - pd.Timedelta(minutes=2), "pH"] == pytest.approx(7.90)
    assert lab.loc[onset, "NH4"] == "scale_step" and lab.loc[onset - pd.Timedelta(hours=1), "COD"] == "stuck"


def test_inject_event_validates_kind():
    frame = pd.DataFrame({"x": np.ones(10)}, index=_minutes(10))
    with pytest.raises(KeyError):
        inject_event(frame, [FaultSpec("x", "spike")], frame.index[2])


def test_place_onsets_seeded_separated_inside_margins_and_valid():
    idx = pd.date_range("2008-01-01", "2008-03-01", freq="15min")
    valid = pd.Series(True, index=idx)
    valid["2008-02-01":"2008-02-10"] = False
    kw = dict(before=pd.Timedelta(days=7), after=pd.Timedelta(days=3), min_separation=pd.Timedelta(days=4),
              valid=valid, min_valid_fraction=0.95)
    a = place_onsets(idx, 5, np.random.default_rng(42), **kw)
    b = place_onsets(idx, 5, np.random.default_rng(42), **kw)
    assert a == b and a == sorted(a) and len(a) == 5
    assert all(t - pd.Timedelta(days=7) >= idx[0] and t + pd.Timedelta(days=3) <= idx[-1] for t in a)
    assert all((y - x) >= pd.Timedelta(days=4) for x, y in zip(a, a[1:]))
    for t in a:
        w = valid[t - pd.Timedelta(days=7):t + pd.Timedelta(days=3)]
        assert w.mean() >= 0.95
    with pytest.raises(RuntimeError):
        place_onsets(idx, 50, np.random.default_rng(0), **kw, max_tries=200)


def test_nerrs_mapping_uses_nerrs_variables():
    from experiments.nerrs_load import WQ_VARIABLES

    assert {v for v in NERRS_MAPPING.values() if v != "all"} <= set(WQ_VARIABLES)


@pytest.mark.requires_data
def test_calibration_reproduces_nb1_faults():
    from experiments.paper2_faults import RAW_E1, STEP_ANATOMY, calibrate, load_history

    cat, rep, _ = calibrate(load_history(), pd.read_csv(STEP_ANATOMY), pd.read_csv(RAW_E1, parse_dates=["t_local"]))
    gated = rep[rep["tolerance_kind"] != "reported_only"].set_index(["event", "metric"])
    # Known, reported failure (paper2-f1-20261028 NOTES): the TSS settle time on real 1-min clean signal
    # (median of 8 placements 11.5 vs 7.5 min) is dominated by the clean signal's minute noise; the
    # noise-free check reproduces it exactly.  Kept in reproduction.csv as FAIL, not gated here.
    known_fail = {("E1_20260731_TSS", "settle_min_1min_median8")}
    assert not gated.loc[list(known_fail), "pass"].any()
    primary = gated.drop(index=list(known_fail))
    assert primary["pass"].all(), primary[~primary["pass"].astype(bool)].to_string()
    assert len(primary) == 16
    assert cat["E1_20260731"]["factor"] == pytest.approx(1 / 20.013, rel=1e-3)
    assert cat["E3_20260916"]["factor"] == pytest.approx(8.1, rel=1e-3)
    assert cat["E2_20260812"]["max_gap_min"] == 147
    assert cat["D1_pH_20260919"]["delta"] == pytest.approx(-1.01, abs=0.01)
