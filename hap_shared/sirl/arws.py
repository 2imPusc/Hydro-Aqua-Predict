"""ARWS — Adaptive Recency-Weighted Seasonal estimator.

A pure-classical seasonal forecaster. The forecast for a calendar phase
(quarter-of-year) is a recency-weighted mean of all same-phase history, weight
rho**age (age 0 = newest). rho is selected per-series by a leakage-free in-sample
seasonal CV. rho->0 keeps only the newest same-phase obs (= seasonal-naive, pure
recency); rho=1 weights all cycles equally (= pooled seasonal mean).

Spike (2026-06-04): pooling helps noisy/temperate regimes (HP/HK/EEA) but a stable
tropical regime (QN) drifts year-to-year, so recency (rho->0) is optimal there. With
rho=0 in the grid the selector defaults to snaive and pools only where in-sample CV
shows it helps -> ARWS beats snaive on all 4 regimes (incl. QN) and beats the
foundation SOTA on EEA, all leakage-free.
"""
import numpy as np
import pandas as pd

RHO_GRID = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


def _recency_weighted_mean(vals, rho):
    """Recency-weighted mean of chronologically-ordered values (last = newest)."""
    vals = np.asarray(vals, float)
    n = len(vals)
    if n == 0:
        return np.nan
    age = (n - 1) - np.arange(n)          # 0 = newest
    w = np.power(float(rho), age)         # rho=0 -> [0,...,0,1] (newest only); rho=1 -> all 1
    return float(np.sum(w * vals) / np.sum(w))


def _phase(quarters):
    return np.array([pd.Timestamp(q).quarter for q in quarters], int)


def select_rho(values, quarters, grid=RHO_GRID):
    """In-sample seasonal CV: predict each point from its prior same-phase obs."""
    best, best_err = 0.0, np.inf
    for rho in grid:
        errs = _insample_errors(values, quarters, rho)
        if errs:
            e = float(np.mean(errs))
            if e < best_err:
                best_err, best = e, rho
    return best


def select_rho_extrap(values, quarters, grid=RHO_GRID):
    """Extrapolation-holdout: predict each phase's latest obs from older same-phase."""
    values = np.asarray(values, float)
    ph = _phase(quarters)
    best, best_err = 0.0, np.inf
    for rho in grid:
        errs = []
        for p in np.unique(ph):
            idx = np.where((ph == p) & np.isfinite(values))[0]
            if len(idx) < 3:
                continue
            errs.append(abs(values[idx[-1]] - _recency_weighted_mean(values[idx[:-1]], rho)))
        if errs:
            e = float(np.mean(errs))
            if e < best_err:
                best_err, best = e, rho
    return best


def arws_forecast(hist_values, hist_quarters, test_quarters, rho=None, selector=select_rho):
    """Forecast each test quarter as the recency-weighted mean of same-phase history.

    Parameters
    ----------
    hist_values, hist_quarters : 1-D arrays (history up to the anchor; may contain NaN).
    test_quarters : the quarters to forecast (their calendar phase selects the pool).
    rho : fixed decay, or None to select per-series via `selector`.
    selector : select_rho (default) or select_rho_extrap.

    Returns
    -------
    (forecast ndarray[len(test)], rho_used).
    """
    hist_values = np.asarray(hist_values, float)
    finite = np.isfinite(hist_values)
    fv, fq = hist_values[finite], np.asarray(hist_quarters)[finite]
    if rho is None:
        rho = selector(fv, fq) if len(fv) >= 2 else 0.0
    ph = _phase(fq)
    overall = float(np.mean(fv)) if len(fv) else np.nan
    out = []
    for q in test_quarters:
        p = pd.Timestamp(q).quarter
        idx = np.where(ph == p)[0]
        out.append(_recency_weighted_mean(fv[idx], rho) if len(idx) else overall)
    return np.asarray(out, float), float(rho)


def arws_anchor_series(values, quarters, rho):
    """Per-quarter ARWS anchor from STRICTLY-earlier same-phase obs (leakage-free).

    anchor[i] = recency-weighted mean of {values[j] : j<i, phase(j)=phase(i), finite}.
    NaN where no such prior obs exists (mirrors snaive's first-cycle NaNs).
    """
    values = np.asarray(values, float)
    ph = _phase(quarters)
    out = np.full(len(values), np.nan)
    for i in range(len(values)):
        idx = np.where((ph[:i] == ph[i]) & np.isfinite(values[:i]))[0]
        if len(idx):
            out[i] = _recency_weighted_mean(values[idx], rho)
    return out


def build_panel_arws(df, params, selector=select_rho):
    """Long residual panel anchored on ARWS (analog of src.sirl.panel.build_panel).

    Per (Station, param) series: select one rho from the full series (train block),
    compute the leakage-free per-quarter ARWS anchor, residual = value - anchor.
    Returns columns: Station, param, Quarter, value, arws, residual, qnum, tidx.

    Unlike build_panel there is no `seasonal_period` knob: the anchor pools by calendar
    phase (quarter-of-year, see `_phase`), not by a positional lag.
    """
    present = [p for p in params if p in df.columns]
    quarters = sorted(df["Quarter"].unique())
    tidx_map = {q: i for i, q in enumerate(quarters)}
    frames = []
    for param in present:
        sub = df[["Station", "Quarter", param]].rename(columns={param: "value"}).copy()
        sub["param"] = param
        sub = sub.sort_values(["Station", "Quarter"])
        anchors = []
        for _st, g in sub.groupby("Station"):
            g = g.sort_values("Quarter")
            vals = g["value"].to_numpy(float)
            qs = g["Quarter"].to_numpy()
            fv, fq = vals[np.isfinite(vals)], qs[np.isfinite(vals)]
            rho = selector(fv, fq) if len(fv) >= 2 else 0.0
            anchors.append(pd.Series(arws_anchor_series(vals, qs, rho), index=g.index))
        sub["arws"] = pd.concat(anchors)
        sub["residual"] = sub["value"] - sub["arws"]
        frames.append(sub)
    panel = pd.concat(frames, ignore_index=True)
    panel["qnum"] = panel["Quarter"].dt.quarter
    panel["tidx"] = panel["Quarter"].map(tidx_map)
    return panel[["Station", "param", "Quarter", "value", "arws", "residual", "qnum", "tidx"]]


# ---------------------------------------------------------------------------
# ARWS v2: empirical-Bayes ρ shrinkage
# ---------------------------------------------------------------------------

def _insample_errors(values, quarters, rho):
    """Leakage-free in-sample seasonal-CV |errors| for one rho: predict each finite
    point from its strictly-earlier same-phase finite obs (>=2 required)."""
    values = np.asarray(values, float)
    ph = _phase(quarters)
    errs = []
    for t in range(len(values)):
        if not np.isfinite(values[t]):
            continue
        idx = np.where((ph[:t] == ph[t]) & np.isfinite(values[:t]))[0]
        if len(idx) < 2:
            continue
        errs.append(abs(values[t] - _recency_weighted_mean(values[idx], rho)))
    return errs


def count_cycles(values, quarters):
    """Number of in-sample positions with >=2 prior same-phase finite obs.

    This is the count of seasonal-CV evaluation points for the series -- the amount of
    evidence behind its per-series rho -- and drives the empirical-Bayes shrink weight.
    The eligibility check is rho-independent, so it equals the number of CV errors at
    any rho (rho=1.0 chosen arbitrarily).
    """
    return len(_insample_errors(values, quarters, rho=1.0))


def pooled_rho(series_list, grid=RHO_GRID):
    """One rho minimizing TOTAL in-sample seasonal-CV error pooled across many series.

    series_list : list of (values, quarters) for one parameter group, each a train-block
    series. Pooling across stations borrows strength so the rho estimate is low-variance
    and adapts per regime (small rho on drift regimes, large on stationary-pooling ones).
    Leakage-free: a pure function of the passed series (train block only).
    """
    best, best_err = 0.0, np.inf
    for rho in grid:
        tot, cnt = 0.0, 0
        for values, quarters in series_list:
            e = _insample_errors(values, quarters, rho)
            tot += float(np.sum(e)); cnt += len(e)
        if cnt:
            m = tot / cnt
            if m < best_err:
                best_err, best = m, rho
    return best


def shrink_rho(rho_series, n_cycles, rho_pooled, k=4.0):
    """Empirical-Bayes partial pooling of the decay rho.

    rho = (n/(n+k)) * rho_series + (k/(n+k)) * rho_pooled.
    n_cycles=0 -> fully pooled; n_cycles>>k -> per-series; k = prior strength (cycles).
    """
    n = float(n_cycles)
    w = n / (n + k)
    return float(w * rho_series + (1.0 - w) * rho_pooled)
