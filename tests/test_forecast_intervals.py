import math

import numpy as np
import pandas as pd
import pytest

from core import forecast_intervals as fi
from experiments.forecast_conformal import aci_intervals, conformal_quantile


def test_quantile_matches_research():
    rng = np.random.default_rng(0)
    scores = rng.exponential(size=101)
    for alpha in (0.2, 0.1, 0.01, 0.001):
        assert fi.conformal_quantile(scores, alpha) == conformal_quantile(scores, alpha)


def test_stateless_aci_replays_research_aci_with_delayed_feedback():
    """Rebuilding alpha_t from the matured ledger at each origin equals the research loop."""
    rng = np.random.default_rng(3)
    cal = rng.exponential(size=200)
    n, horizon = 400, 180
    issued = pd.date_range("2026-10-01", periods=n, freq="min", tz="UTC")
    known = issued + pd.Timedelta(minutes=horizon) + pd.to_timedelta(rng.integers(0, 120, n), unit="s")
    residual = rng.exponential(scale=1.4, size=n)  # drifted: errors larger than calibration
    alpha, gamma = 0.2, 0.005 * 15 / horizon
    expected_q, expected_alpha = aci_intervals(cal, issued.to_numpy(), known.to_numpy(), residual, alpha, gamma)
    q_logged = np.empty(n)
    for i in range(n):
        matured = [(residual[s], q_logged[s]) for s in range(i) if known[s] <= issued[i]]
        got = fi.aci_half_width(cal, matured, alpha, gamma)
        q_logged[i] = got["q"]
        assert got["alpha_t"] == pytest.approx(expected_alpha[i], abs=1e-12)
    np.testing.assert_allclose(q_logged, expected_q)


def test_aci_infinite_when_alpha_drops_below_zero():
    got = fi.aci_half_width([1.0, 2.0], [(10.0, 1.0)] * 50, 0.2, 0.05)
    assert got["alpha_t"] < 0
    assert math.isinf(got["q"])


def test_static_night_uses_stratum_and_live_residuals():
    small = {0: np.array([1.0, 2.0, 3.0]), 1: np.array([10.0, 20.0, 30.0])}
    assert fi.static_night_half_width(small, {}, night=0, alpha=0.1)["q"] == math.inf  # rank 4 > n=3
    cal ={0: np.arange(1.0, 20.0), 1: np.arange(100.0, 119.0)}
    day = fi.static_night_half_width(cal, {}, night=0, alpha=0.2)
    night = fi.static_night_half_width(cal, {}, night=1, alpha=0.2)
    assert day["q"] == conformal_quantile(cal[0], 0.2)
    assert night["q"] == conformal_quantile(cal[1], 0.2)
    live = fi.static_night_half_width(cal, {0: [50.0] * 10}, night=0, alpha=0.2)
    assert live["q"] == conformal_quantile(np.concatenate([cal[0], [50.0] * 10]), 0.2)
    assert live["n_live"] == 10


def test_stateless_aci_amp_replays_research_normalised_aci():
    """aci_amp half-width = A(t) * ACI quantile of amplitude-normalised scores (delayed feedback)."""
    rng = np.random.default_rng(5)
    n, horizon, floor = 300, 180, 0.2
    cal_res = rng.exponential(size=200)
    cal_amp = rng.uniform(0.5, 3.0, size=200)
    cal_norm = cal_res / np.maximum(cal_amp, floor)
    issued = pd.date_range("2026-10-05", periods=n, freq="min", tz="UTC")
    known = issued + pd.Timedelta(minutes=horizon)
    amp = np.where(np.arange(n) < n // 2, 1.0, 4.0) * rng.uniform(0.05, 1.5, n)
    scale = np.maximum(amp, floor)
    residual = rng.exponential(size=n) * scale
    alpha, gamma = 0.1, 0.005 * 15 / horizon
    q_norm, expected_alpha = aci_intervals(cal_norm, issued.to_numpy(), known.to_numpy(), residual / scale, alpha, gamma)
    q_logged = np.empty(n)
    for i in range(n):
        matured = [(residual[s], amp[s], q_logged[s]) for s in range(i) if known[s] <= issued[i]]
        got = fi.aci_amp_half_width(cal_norm, matured, amp[i], alpha, gamma, floor)
        q_logged[i] = got["q"]
        assert got["alpha_t"] == pytest.approx(expected_alpha[i], abs=1e-12)
        assert got["amplitude"] == pytest.approx(scale[i])
    np.testing.assert_allclose(q_logged, q_norm * scale)


def test_aci_amp_missing_amplitude_is_reported_not_guessed():
    got = fi.aci_amp_half_width([0.1, 0.2, 0.3], [], math.nan, 0.2, 0.001, 0.1)
    assert math.isinf(got["q"]) and got["reason"] == "amplitude_unavailable"


def test_runtime_trailing_amplitude_matches_research_and_is_causal():
    from experiments.forecast_conformal import trailing_amplitude

    times = pd.date_range("2026-10-01", periods=4000, freq="min", tz="UTC")
    values = np.sin(np.arange(4000) / 150.0) * np.linspace(1, 3, 4000)
    t = times[3000]
    full = fi.trailing_amplitude_at(times, values, t, "24h", "range", 720)
    assert full == trailing_amplitude(pd.Series(values, index=times), pd.DatetimeIndex([t]), "24h", "range", 720)[0]
    future = values.copy()
    future[3001:] += 100.0
    assert fi.trailing_amplitude_at(times, future, t, "24h", "range", 720) == full
    assert math.isnan(fi.trailing_amplitude_at(times[:100], values[:100], times[99], "24h", "range", 720))
