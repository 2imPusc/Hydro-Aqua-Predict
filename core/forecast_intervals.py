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
