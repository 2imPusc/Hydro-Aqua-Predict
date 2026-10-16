"""Conformal prediction intervals for the long-horizon shadow forecasts.

Same definitions as ``experiments/forecast_conformal.py`` (H1.3, RL-09):
symmetric ``prediction +/- q`` on absolute residuals, finite-sample quantile
``ceil((n+1)(1-alpha))``-th smallest score (``inf`` if it exceeds ``n``).

The state is never stored separately: it is rebuilt at every origin from the
matured outcomes in the append-only ledger.  Because the ACI update is
additive, ``alpha_t = alpha + gamma * sum(alpha - err_s)`` over every origin
``s`` whose actual was known before origin ``t`` -- identical to the research
loop with the delayed-feedback rule.
"""
from __future__ import annotations

import math
from typing import Iterable, Mapping

import numpy as np
import pandas as pd


def conformal_quantile(scores, alpha: float) -> float:
    ordered = np.sort(np.asarray(scores, dtype=float))
    n = len(ordered)
    k = math.ceil((n + 1) * (1.0 - alpha) - 1e-9)
    if k > n:
        return math.inf
    if k <= 0:
        return 0.0
    return float(ordered[k - 1])


def aci_half_width(calibration, matured: Iterable[tuple[float, float]], alpha: float, gamma: float) -> dict:
    """``matured`` = (|residual|, half-width issued for that origin at this alpha)."""
    matured = list(matured)
    residuals = np.array([r for r, _ in matured], dtype=float)
    issued_q = np.array([q for _, q in matured], dtype=float)
    errors = (residuals > issued_q).astype(float) if len(matured) else np.array([])
    alpha_t = alpha + gamma * float(np.sum(alpha - errors))
    pool = np.concatenate([np.asarray(calibration, dtype=float), residuals])
    return {"q": conformal_quantile(pool, alpha_t), "alpha_t": alpha_t, "n_pool": int(len(pool)), "n_live": int(len(matured))}


def static_night_half_width(calibration_by_night: Mapping[int, np.ndarray], live_by_night: Mapping[int, list], night: int, alpha: float) -> dict:
    """Mondrian split conformal by the night flag, recalibrated with matured live residuals."""
    calibration = np.asarray(calibration_by_night.get(night, np.concatenate([np.asarray(v, dtype=float) for v in calibration_by_night.values()])), dtype=float)
    live = np.asarray(live_by_night.get(night, []), dtype=float)
    pool = np.concatenate([calibration, live])
    return {"q": conformal_quantile(pool, alpha), "n_pool": int(len(pool)), "n_live": int(len(live))}


def trailing_amplitude_at(times, values, issued_at, window: str = "24h", kind: str = "range", min_count: int = 720) -> float:
    """Diurnal amplitude of the target over ``(issued_at - window, issued_at]``.

    Only observations timestamped at or before ``issued_at`` are used.
    ``kind`` is ``range`` (max - min) or ``std``.  NaN when fewer than
    ``min_count`` finite values fall in the window.  Matches
    ``experiments/forecast_conformal.trailing_amplitude`` (A4).
    """
    idx = pd.DatetimeIndex(pd.to_datetime(pd.Series(times), utc=True))
    vals = np.asarray(values, dtype=float)
    t = pd.Timestamp(issued_at)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    keep = (idx <= t) & (idx > t - pd.Timedelta(window)) & np.isfinite(vals)
    window_values = vals[np.asarray(keep)]
    if len(window_values) < min_count or len(window_values) == 0:
        return math.nan
    if kind == "range":
        return float(window_values.max() - window_values.min())
    if kind == "std":
        return float(np.std(window_values, ddof=1)) if len(window_values) > 1 else math.nan
    raise ValueError(f"unknown_amplitude_kind:{kind}")


def aci_amp_half_width(calibration_normalised, matured: Iterable[tuple[float, float, float]], amplitude: float,
                       alpha: float, gamma: float, floor: float) -> dict:
    """ACI on amplitude-normalised scores (A4, ``aci_amp``); not the runtime default.

    ``calibration_normalised`` = calibration ``|residual| / max(A, floor)``;
    ``matured`` = (|residual|, amplitude at that origin's issue time, half-width
    issued for it at this alpha).  The half-width is ``max(A_now, floor)`` times
    the ACI quantile of the normalised pool.  A missing current amplitude gives
    an infinite interval with a reason, never a guessed scale.
    """
    matured = list(matured)
    residuals = np.array([r for r, _, _ in matured], dtype=float)
    amps = np.array([a for _, a, _ in matured], dtype=float)
    issued_q = np.array([q for _, _, q in matured], dtype=float)
    errors = (residuals > issued_q).astype(float) if len(matured) else np.array([])
    alpha_t = alpha + gamma * float(np.sum(alpha - errors))
    live = residuals / np.maximum(amps, floor) if len(matured) else np.array([])
    live = live[np.isfinite(live)]
    pool = np.concatenate([np.asarray(calibration_normalised, dtype=float), live])
    out = {"alpha_t": alpha_t, "n_pool": int(len(pool)), "n_live": int(len(live)), "floor": floor}
    if not (amplitude is not None and math.isfinite(amplitude)):
        return {**out, "q": math.inf, "q_norm": math.nan, "amplitude": math.nan, "reason": "amplitude_unavailable"}
    scale = max(float(amplitude), floor)
    q_norm = conformal_quantile(pool, alpha_t)
    return {**out, "q": q_norm * scale, "q_norm": q_norm, "amplitude": scale}
