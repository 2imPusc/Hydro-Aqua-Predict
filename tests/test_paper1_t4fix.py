"""RL-T4FIX: known_at with ingest latency (synthetic frames only, no data)."""
import json

import numpy as np
import pandas as pd
import pytest

from experiments import paper1_t4_conformal as t4
from experiments import paper1_t4fix_knownat as fix
from experiments.forecast_conformal import calibration_residuals, known_at


def _frame(actual_at):
    valid = pd.to_datetime(["2026-10-10 00:15", "2026-10-10 00:30", "2026-10-10 00:45"], utc=True)
    return pd.DataFrame({"valid_at": valid, "actual_at": pd.to_datetime(actual_at, utc=True)})


def test_lockbox_nat_actual_at_gives_valid_plus_latency_not_valid():
    f = _frame([pd.NaT, pd.NaT, pd.NaT])
    out = fix.nb1_known_at(f)
    assert (out == f["valid_at"] + pd.Timedelta(minutes=15)).all()
    assert (out > f["valid_at"]).all()


def test_rolling_uses_max_of_valid_and_actual_plus_latency():
    f = _frame(["2026-10-10 00:16", "2026-10-10 00:29", pd.NaT])
    out = fix.nb1_known_at(f, pd.Timedelta(minutes=15))
    expected = pd.to_datetime(["2026-10-10 00:31", "2026-10-10 00:45", "2026-10-10 01:00"], utc=True)
    assert list(out) == list(expected)


def test_zero_latency_reproduces_old_rule_and_keeps_utc():
    f = _frame(["2026-10-10 00:16", pd.NaT, "2026-10-10 00:44"])
    old = f["valid_at"].where(~(f["actual_at"].notna() & (f["actual_at"] > f["valid_at"])), f["actual_at"])
    new = known_at(f)
    assert list(new) == list(old)
    assert str(new.dt.tz) == "UTC" and str(fix.nb1_known_at(f).dt.tz) == "UTC"


def test_negative_latency_is_refused():
    with pytest.raises(ValueError):
        known_at(_frame([pd.NaT] * 3), pd.Timedelta(minutes=-1))


def _scores_path(latency, n=40, h=60):
    issued = pd.date_range("2026-10-10", periods=n, freq="15min", tz="UTC")
    frame = pd.DataFrame({"valid_at": issued + pd.Timedelta(minutes=h), "actual_at": pd.NaT})
    frame["actual_at"] = pd.to_datetime(frame["actual_at"], utc=True)
    kn = known_at(frame, latency)
    score = np.random.default_rng(3).uniform(0, 2, n)
    return t4.aci_amp_path(np.linspace(0.05, 1, 40), issued, kn, score, np.full(n, 2.0), 0.5, 0.2, 0.05)


def test_any_latency_up_to_one_stride_gives_same_eligibility_on_15min_grid():
    np.testing.assert_array_equal(_scores_path(pd.Timedelta(minutes=1)), _scores_path(pd.Timedelta(minutes=15)))
    assert not np.array_equal(_scores_path(pd.Timedelta(0)), _scores_path(pd.Timedelta(minutes=15)))
    assert not np.array_equal(_scores_path(pd.Timedelta(minutes=15)), _scores_path(pd.Timedelta(minutes=16)))


def test_latency_delays_feedback_by_one_origin():
    n, h = 40, 60
    issued = pd.date_range("2026-10-10", periods=n, freq="15min", tz="UTC")
    frame = pd.DataFrame({"valid_at": issued + pd.Timedelta(minutes=h), "actual_at": pd.NaT})
    frame["actual_at"] = pd.to_datetime(frame["actual_at"], utc=True)
    score = np.full(n, 0.5)
    score[0] = 500.0

    def path(lat):
        return t4.aci_amp_path(np.linspace(0.05, 1, 40), issued, known_at(frame, lat), score, np.full(n, 2.0), 0.5, 0.2, 0.05)
    old, new = path(pd.Timedelta(0)), path(pd.Timedelta(minutes=15))
    # outcome of origin 0 is known at origin 4 under the old rule, at origin 5 with 15 min latency
    assert old[4] != old[3] and new[4] == new[3] and new[5] != new[4]


def test_calibration_leak_filter_uses_latency():
    issued = pd.date_range("2026-10-01", periods=8, freq="15min", tz="UTC")
    df = pd.DataFrame({"issued_at": issued, "valid_at": issued + pd.Timedelta(minutes=15), "fold": 1,
                       "actual": 1.0, "prediction": 0.5, "split": "rolling"})
    df["actual_at"] = pd.to_datetime(pd.Series([pd.NaT] * 8), utc=True)
    lock = issued[-1] + pd.Timedelta(minutes=15)
    _, d0 = calibration_residuals(df, 1, lock)
    _, d15 = calibration_residuals(df, 1, lock, pd.Timedelta(minutes=15))
    assert (d0, d15) == (1, 2)


def test_effective_lag():
    assert t4.effective_lag(15, 15) == 1 and t4.effective_lag(15, 15, pd.Timedelta(minutes=15)) == 2
    assert t4.effective_lag(720, 15, pd.Timedelta(minutes=15)) == 49 and t4.effective_lag(15, 15, pd.Timedelta(minutes=1)) == 2


def test_gamma_override_default_is_preregistered():
    rng = np.random.default_rng(0)
    n = 60
    issued = pd.date_range("2026-10-10", periods=n, freq="15min", tz="UTC")
    y = rng.normal(0, 1, n)
    block = pd.DataFrame({"issued_at": issued, "known_at": issued + pd.Timedelta(minutes=60), "y": y,
                          "point": y + rng.normal(0, 0.5, n), "amp": 2.0})
    a = t4.methods_for_group(block, block, 0.5, 60, 15, "point")
    b = t4.methods_for_group(block, block, 0.5, 60, 15, "point", gamma=t4.gamma_primary(60, 15))
    c = t4.methods_for_group(block, block, 0.5, 60, 15, "point", gamma=0.5)
    np.testing.assert_array_equal(a["ridge_aci_amp"][0], b["ridge_aci_amp"][0])
    assert not np.array_equal(a["ridge_aci_amp"][0], c["ridge_aci_amp"][0])


def test_check_control_detects_mismatch():
    cells = pd.DataFrame({"horizon_minutes": [15, 30], "n": [100, 100], "coverage": [0.8, 0.79],
                          "frac_infinite": [0.0, 0.0], "winkler_ratio": [0.9, 0.95], "h3_pass": [True, True]})
    assert fix.check_control(cells, cells.copy()) == 0.0
    bad = cells.copy()
    bad.loc[0, "coverage"] = 0.81
    with pytest.raises(SystemExit):
        fix.check_control(cells, bad)


def test_amendment_declares_primary_and_control():
    spec = json.loads(fix.PREREG_FILE.read_text(encoding="utf-8"))
    assert set(spec["variants"]) == set(fix.VARIANTS)
    assert fix.VARIANTS["primary_latency_15min"][0] == pd.Timedelta(minutes=15)
    assert fix.VARIANTS["rl81_control_latency_0"][0] == pd.Timedelta(0)
