"""Fuzzy multi-criteria site suitability (direction 3).

Follows Ghaderi (2026), Regional Studies in Marine Science 101:105287:
  * triangular membership mu(x) for dynamic variables (Eq. 4), averaged over time (Eq. 5)
    and min-max normalised over the study area (Eq. 6);
  * current-direction stability S = 1 - |d theta| / pi, averaged over time (Eqs. 1-3);
  * linear distance membership for fixed variables (ports, protected areas, shoreline);
  * SUM / PRODUCT / GAMMA integration, unweighted (Eq. 7) or weighted (Eq. 8).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Rachycentron canadum (cobia), Ghaderi (2026) Table 2: (x_min, x_opt, x_max).
COBIA_RANGES = {
    "SWH": (0.0, 0.5, 1.0),      # significant wave height, m
    "WS": (0.0, 2.5, 5.1),       # wind speed, m/s
    "SST": (16.8, 24.5, 32.2),   # sea surface temperature, deg C
    "SSS": (5.0, 35.0, 44.5),    # sea surface salinity, psu
    "DEP": (6.0, 15.0, 20.0),    # depth, m
    "DfS": (2.0, 8.0, 10.0),     # distance from shoreline, km
    "SCS": (0.2, 0.4, 0.6),      # surface current speed, m/s
}

# Expert AHP weights, Ghaderi (2026) Table 3b (CR = 0.096).
GHADERI_WEIGHTS = {
    "DEP": 0.243, "SCS": 0.221, "SWH": 0.127, "WS": 0.110, "DfPA": 0.094, "SST": 0.064,
    "SSS": 0.043, "CSCD": 0.041, "DfP": 0.028, "DfS": 0.017, "DfMT": 0.012,
}

METHODS = {"SUM": 0.0, "PRODUCT": 1.0, "GAMMA_0.8": 0.8, "GAMMA_0.9": 0.9}


def triangular(x, x_min: float, x_opt: float, x_max: float) -> np.ndarray:
    """Eq. 4: 0 outside [x_min, x_max], 1 at x_opt, linear in between; NaN stays NaN."""
    x = np.asarray(x, dtype=float)
    rising = (x - x_min) / (x_opt - x_min) if x_opt > x_min else np.where(x >= x_opt, 1.0, 0.0)
    falling = (x_max - x) / (x_max - x_opt) if x_max > x_opt else np.where(x <= x_opt, 1.0, 0.0)
    mu = np.clip(np.minimum(rising, falling), 0.0, 1.0)
    return np.where(np.isnan(x), np.nan, mu)


def temporal_score(values: pd.DataFrame, x_min: float, x_opt: float, x_max: float) -> pd.Series:
    """Eq. 5: mean membership over time for each column (one column per grid point)."""
    mu = triangular(values.to_numpy(), x_min, x_opt, x_max)
    return pd.Series(np.nanmean(mu, axis=0), index=values.columns)


def direction_stability(direction_deg: pd.DataFrame) -> pd.Series:
    """Eqs. 1-3: mean of 1 - |wrapped change in direction| / pi between consecutive steps."""
    theta = np.deg2rad(direction_deg.to_numpy(dtype=float))
    delta = np.diff(theta, axis=0)
    wrapped = np.abs((delta + np.pi) % (2 * np.pi) - np.pi)
    return pd.Series(np.nanmean(1.0 - wrapped / np.pi, axis=0), index=direction_deg.columns)


def distance_membership(distance_km, closer_is_better: bool) -> np.ndarray:
    """Linear membership over the observed range (fixed variables, Ghaderi Section 2.3.1)."""
    d = np.asarray(distance_km, dtype=float)
    span = np.nanmax(d) - np.nanmin(d)
    if span == 0:
        return np.ones_like(d)
    scaled = (d - np.nanmin(d)) / span
    return 1.0 - scaled if closer_is_better else scaled


def minmax(values) -> np.ndarray:
    """Eq. 6."""
    v = np.asarray(values, dtype=float)
    span = np.nanmax(v) - np.nanmin(v)
    return np.zeros_like(v) if span == 0 else (v - np.nanmin(v)) / span


def integrate(scores: pd.DataFrame, gamma: float, weights: dict[str, float] | None = None) -> pd.Series:
    """Eq. 7 (weights=None) or Eq. 8: gamma * PRODUCT-term + (1 - gamma) * SUM-term.

    Weights are restricted to the columns present and renormalised to sum to 1.
    """
    x = scores.to_numpy(dtype=float)
    if weights is None:
        w = np.full(x.shape[1], 1.0 / x.shape[1])
    else:
        w = np.array([weights[c] for c in scores.columns], dtype=float)
        w = w / w.sum()
    with np.errstate(divide="ignore"):
        product = np.exp(np.sum(w * np.log(np.clip(x, 0.0, 1.0)), axis=1))
    total = np.sum(w * x, axis=1)
    return pd.Series(gamma * product + (1.0 - gamma) * total, index=scores.index)
