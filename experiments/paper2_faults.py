"""Paper 2 / F1: sensor-fault injection library calibrated on real NB1 instrument faults (research-only).

Library (pure functions, unit-tested in ``tests/test_paper2_faults.py``):

* Primitives on a time-indexed ``pd.Series``; durations are ``pd.Timedelta`` so the same spec works on
  NB1 1-min data and NERRS 15-min data.  Each returns ``(faulted, labels)``: a new series (the input is
  never mutated) and a boolean series, True where the fault is active.  Injected values are NOT clipped
  or QC-masked (except ``cap`` = an instrument rail, which is part of the fault): QC masking is mechanism
  (b) under test in F3, so the injector must leave the bad values in.

  - ``scale_step``  multiplicative re-scale in one sample (NB1 NH4 /20 on 31/07, x6.7 on 16/09)
  - ``ramp``        additive or log-linear change over ``duration`` then held (pH 19/09: ~-1 unit in ~10 h;
                    COD ramp to the 558.8 rail, 06-11/06), optional ``cap`` = rail
  - ``fouling``     multiplicative gain growing log-linearly to ``gain`` (TSS optical window, 06/06->),
                    plateau, optional clearance: gain drops to ``residual`` at once then decays to 1 with
                    time constant ``settle`` (TSS 31/07 14:07:30 -> 4-5 mg/L at ~14:15)
  - ``stuck``       constant value (COD exactly 0.0, or rail 558.8)
  - ``gap``         missing data (12/08: 147 min)

* ``FaultSpec`` + ``inject_event``: a composite event is data (list of specs on several columns with offsets
  from one onset), applied to a multi-column frame; returns the faulted frame and a label frame
  (column per variable, fault kind or "").  ``NB1_EVENTS`` holds the three RL-72 interventions.
* ``place_onsets``: seeded random onsets (explicit ``numpy.random.Generator``) with margins and a minimum
  separation, so F2 / F3 reuse identical placements.
* ``NERRS_MAPPING``: which NERRS variable carries each NB1 fault type (fixed here, before F3).

Calibration (``python experiments/paper2_faults.py [--run-name paper2-f1-20261028]``): measures the NB1 fault
catalogue from ``sensor-history-20261024`` and RL-72's ``step_anatomy.csv``, injects each catalogued fault
into a clean NB1 window of the same variable, re-measures the injected series with the same functions and
checks the pre-registered tolerances (``TOLERANCES``).  Writes a NEW run dir (exist_ok=False):
``nb1_fault_catalog.json``, ``reproduction.csv``, ``fig_reproduction.png``, ``NOTES.md``, ``manifest.json``.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from experiments.nh4_step_0731 import detect_level_step, max_gap, relative_spread, sha256  # noqa: E402

STATION = "06M26042804"
HISTORY = paths.EXPERIMENT_OUTPUT_DIR / "sensor-history-20261024" / f"{STATION}.csv"
RL72_RUN = paths.EXPERIMENT_OUTPUT_DIR / "nh4-step-0731-20261026"
STEP_ANATOMY = RL72_RUN / "step_anatomy.csv"
RAW_E1 = RL72_RUN / "raw_window_20260731_1200_1600.csv"

COD_RAIL = 558.8
NH4_RESOLUTION = 0.01

# Pre-registered before the first calibration run (2026-10-28).  "rel" = relative error of the injected
# signature vs the real one; "abs" = absolute; onset errors in samples of the measured series.
TOLERANCES = {
    "onset_samples": 1,          # step / clearance / unstick lands on the same sample (+-1)
    "ratio_rel": 0.10,           # multiplicative step factor
    "delta_abs_pH": 0.10,        # pH ramp size, pH units
    "duration_rel": 0.25,        # 10-90 % ramp / growth duration
    "gain_rel": 0.20,            # fouling plateau gain
    "settle_rel": 0.50,          # clearance settle time (few samples, coarse)
    "gap_minutes": 0,            # gap length exact
    "stuck_value_abs": 0.0,      # stuck value exact
}

# Which NERRS SWMP variable (nerrs_load.read_wq_file: Temp, Sal, DO_mgl, pH, Turb) carries each NB1 fault
# type in F3.  NERRS has no NH4 / COD: the NH4 ion-selective-electrode re-scale goes to DO_mgl (also an
# electrochemical probe, positive, multiplicative), optical fouling to Turb, pH ramp to pH, stuck-at-0 to
# DO_mgl, rail to Turb (cap = TURB_RAIL_NTU, YSI 6136 range end; to verify on NERRS metadata in F3).
TURB_RAIL_NTU = 1000.0
NERRS_MAPPING = {
    "scale_step": "DO_mgl",
    "fouling": "Turb",
    "ramp_pH": "pH",
    "stuck_zero": "DO_mgl",
    "ramp_to_rail": "Turb",
    "gap": "all",
}


# ---------------------------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------------------------

def _window(index: pd.DatetimeIndex, onset, end=None) -> np.ndarray:
    m = index >= pd.Timestamp(onset)
    if end is not None:
        m &= index < pd.Timestamp(end)
    return np.asarray(m)


def _labels(series: pd.Series, mask: np.ndarray) -> pd.Series:
    return pd.Series(mask, index=series.index, name=series.name, dtype=bool)


def scale_step(series: pd.Series, onset, factor: float, end=None, resolution: float | None = None):
    """Multiply by ``factor`` from ``onset`` (first faulted sample) to ``end`` (exclusive, None = series end).

    ``resolution`` re-quantises the faulted values to the instrument display step (NB1 NH4: 0.01), which a
    re-scaled reading inherits.
    """
    out = series.astype(float).copy()
    m = _window(out.index, onset, end)
    vals = out.to_numpy()[m] * factor
    if resolution:
        vals = np.round(vals / resolution) * resolution
    out.iloc[np.flatnonzero(m)] = vals
    return out, _labels(series, m)


def _progress(index: pd.DatetimeIndex, onset, duration: pd.Timedelta) -> np.ndarray:
    dt = (index - pd.Timestamp(onset)) / pd.Timedelta(duration)
    return np.clip(np.asarray(dt, dtype=float), 0.0, 1.0)


def ramp(series: pd.Series, onset, duration: pd.Timedelta, *, delta: float | None = None, factor: float | None = None,
         end=None, cap: float | None = None):
    """Linear additive (``delta``) or log-linear multiplicative (``factor``) change from ``onset`` reaching the
    full size after ``duration``, then held until ``end``.  ``cap`` clips at an instrument rail."""
    if (delta is None) == (factor is None):
        raise ValueError("give exactly one of delta / factor")
    out = series.astype(float).copy()
    m = _window(out.index, onset, end)
    p = _progress(out.index, onset, duration)[m]
    vals = out.to_numpy()[m]
    vals = vals + delta * p if delta is not None else vals * np.power(factor, p)
    if cap is not None:
        vals = np.minimum(vals, cap)
    out.iloc[np.flatnonzero(m)] = vals
    return out, _labels(series, m)


def fouling(series: pd.Series, onset, growth: pd.Timedelta, gain: float, *, clear_at=None, residual: float = 1.0,
            settle: pd.Timedelta = pd.Timedelta(0), noise_sigma: float = 0.0, rng: np.random.Generator | None = None):
    """Optical-window fouling: multiplicative gain 1 -> ``gain`` log-linearly over ``growth`` from ``onset``, held.

    At ``clear_at`` (cleaning) the gain drops to ``residual`` in one sample and then decays to 1 in log space
    with time constant ``settle``; the fault label ends when the remaining gain is < 1 %.  ``noise_sigma``
    adds multiplicative log-normal noise scaled by fouling progress (needs ``rng``).
    """
    out = series.astype(float).copy()
    idx = out.index
    log_g = np.log(gain) * _progress(idx, onset, growth)
    log_g[np.asarray(idx < pd.Timestamp(onset))] = 0.0
    active = np.asarray(idx >= pd.Timestamp(onset))
    if clear_at is not None:
        after = np.asarray(idx >= pd.Timestamp(clear_at))
        dt = np.asarray((idx[after] - pd.Timestamp(clear_at)) / pd.Timedelta(minutes=1), dtype=float)
        tau = pd.Timedelta(settle) / pd.Timedelta(minutes=1)
        log_g[after] = np.log(residual) * (np.exp(-dt / tau) if tau > 0 else (dt == 0).astype(float))
        active &= ~after | (np.abs(log_g) >= np.log(1.01))
    if noise_sigma:
        if rng is None:
            raise ValueError("noise_sigma needs rng")
        scale = np.abs(log_g) / np.log(gain) if gain != 1 else np.zeros(len(idx))
        log_g = log_g + rng.normal(0.0, noise_sigma, len(idx)) * scale
    out = out * np.exp(log_g)
    return out, _labels(series, active)


def stuck(series: pd.Series, onset, end=None, value: float | None = None):
    """Constant reading from ``onset`` to ``end``; ``value=None`` freezes the last value before onset."""
    out = series.astype(float).copy()
    m = _window(out.index, onset, end)
    if value is None:
        prior = out[out.index < pd.Timestamp(onset)].dropna()
        if prior.empty:
            raise ValueError("no value before onset to freeze")
        value = float(prior.iloc[-1])
    out.iloc[np.flatnonzero(m)] = value
    return out, _labels(series, m)


def gap(series: pd.Series, onset, duration: pd.Timedelta):
    """Missing data over [onset, onset + duration)."""
    out = series.astype(float).copy()
    m = _window(out.index, onset, pd.Timestamp(onset) + pd.Timedelta(duration))
    out.iloc[np.flatnonzero(m)] = np.nan
    return out, _labels(series, m)


PRIMITIVES = {"scale_step": scale_step, "ramp": ramp, "fouling": fouling, "stuck": stuck, "gap": gap}


# ---------------------------------------------------------------------------------------------
# composite events
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class FaultSpec:
    """One primitive on one column; ``offset`` from the event onset; time-valued params as minutes."""
    variable: str
    kind: str
    offset_min: float = 0.0
    params: dict = field(default_factory=dict)
    end_offset_min: float | None = None


_TIME_PARAMS = ("duration", "growth", "settle")


def _resolve(spec: FaultSpec, onset: pd.Timestamp, rng) -> dict:
    kw = dict(spec.params)
    for k in _TIME_PARAMS:
        if k in kw:
            kw[k] = pd.Timedelta(minutes=kw[k])
    if "clear_after_min" in kw:
        kw["clear_at"] = onset + pd.Timedelta(minutes=kw.pop("clear_after_min"))
    if spec.end_offset_min is not None:
        kw["end"] = onset + pd.Timedelta(minutes=spec.end_offset_min)
    if spec.kind == "fouling" and kw.get("noise_sigma"):
        kw["rng"] = rng
    return kw


def inject_event(frame: pd.DataFrame, specs: list[FaultSpec], onset, rng: np.random.Generator | None = None):
    """Apply ``specs`` (in order) to a copy of ``frame``.  Returns (faulted frame, label frame of fault kinds)."""
    onset = pd.Timestamp(onset)
    out = frame.copy()
    labels = pd.DataFrame("", index=frame.index, columns=frame.columns, dtype=object)
    for spec in specs:
        cols = list(frame.columns) if spec.variable == "*" else [spec.variable]
        start = onset + pd.Timedelta(minutes=spec.offset_min)
        kw = _resolve(spec, onset, rng)
        for col in cols:
            if spec.kind == "gap":
                faulted, lab = gap(out[col], start, kw["duration"])
            else:
                faulted, lab = PRIMITIVES[spec.kind](out[col], start, **kw)
            out[col] = faulted
            labels.loc[lab.to_numpy(), col] = spec.kind
    return out, labels


# E1 TSS clearance, measured by ``calibrate`` (raw 30-s window + 24 h after): pre-clearance 10-min level / settled
# level, first low sample / settled level, settle time constant (minutes).
E1_TSS_GAIN = 40.0
E1_TSS_RESIDUAL = 4.53
E1_TSS_SETTLE_MIN = 3.92

# The three RL-72 interventions as composite events (onset = first faulted sample of the lead variable).
# Values are the measured NB1 signatures (step_anatomy.csv, raw_window_20260731_1200_1600.csv); the
# calibration stage re-measures them and fails loudly if the stored numbers drift from the data.
NB1_EVENTS = {
    # 31/07 14:06:00 NH4 /20.0 in one sample; TSS (fouled since ~06/06) clears 90 s later, settles in minutes
    "E1_20260731": [
        FaultSpec("NH4", "scale_step", 0.0, {"factor": 1 / 20.013, "resolution": NH4_RESOLUTION}),
        FaultSpec("TSS", "fouling", -7 * 24 * 60.0, {"growth": 1.0, "gain": E1_TSS_GAIN, "clear_after_min": 1.5,
                                                    "residual": E1_TSS_RESIDUAL, "settle": E1_TSS_SETTLE_MIN}),
    ],
    # 12/08 16:58 147-min gap on every channel; COD comes back stuck at exactly 0.0 (was on the 558.8 rail)
    "E2_20260812": [
        FaultSpec("*", "gap", 0.0, {"duration": 147.0}),
        FaultSpec("COD", "stuck", 147.0, {"value": 0.0}),
    ],
    # 16/09 15:34:00 NH4 x8.1 (x6.7 on the 30-s raw window) and COD 0 -> in range in the same sample (stuck ends); pH +0.22 2.5 min earlier
    "E3_20260916": [
        FaultSpec("NH4", "scale_step", 0.0, {"factor": 8.1, "resolution": NH4_RESOLUTION}),
        FaultSpec("COD", "stuck", -24 * 60.0, {"value": 0.0}, end_offset_min=0.0),
        FaultSpec("pH", "ramp", -2.5, {"delta": 0.22, "duration": 0.5}),
    ],
}


# ---------------------------------------------------------------------------------------------
# placement
# ---------------------------------------------------------------------------------------------

def place_onsets(index: pd.DatetimeIndex, n: int, rng: np.random.Generator, *, before: pd.Timedelta,
                 after: pd.Timedelta, min_separation: pd.Timedelta, valid: pd.Series | None = None,
                 min_valid_fraction: float = 0.9, max_tries: int = 10_000) -> list[pd.Timestamp]:
    """Draw ``n`` onsets from ``index`` such that [onset - before, onset + after] lies inside the index,
    onsets are >= ``min_separation`` apart, and (if ``valid``, a boolean series on ``index``) at least
    ``min_valid_fraction`` of that window is valid.  Deterministic for a given generator state; sorted."""
    index = pd.DatetimeIndex(index)
    lo, hi = index[0] + pd.Timedelta(before), index[-1] - pd.Timedelta(after)
    cand = np.flatnonzero((index >= lo) & (index <= hi))
    if not len(cand):
        raise ValueError("series shorter than before + after")
    vcum = None
    if valid is not None:
        vcum = np.r_[0, np.cumsum(valid.reindex(index).fillna(False).to_numpy(dtype=int))]
    chosen: list[pd.Timestamp] = []
    for _ in range(max_tries):
        if len(chosen) == n:
            break
        t = index[int(rng.choice(cand))]
        if any(abs(t - c) < pd.Timedelta(min_separation) for c in chosen):
            continue
        if vcum is not None:
            a = index.searchsorted(t - pd.Timedelta(before))
            b = index.searchsorted(t + pd.Timedelta(after), side="right")
            if (vcum[b] - vcum[a]) / max(b - a, 1) < min_valid_fraction:
                continue
        chosen.append(t)
    if len(chosen) < n:
        raise RuntimeError(f"placed only {len(chosen)}/{n} onsets")
    return sorted(chosen)


# ---------------------------------------------------------------------------------------------
# signature measurement (same functions on real and injected series)
# ---------------------------------------------------------------------------------------------

def ramp_signature(series: pd.Series, before: tuple, after: tuple, log: bool = False) -> dict:
    """Size and 10-90 % duration of a monotone change between a ``before`` and an ``after`` window.

    ``series`` should be smoothed (hourly / daily medians).  Duration = time between the first crossing of
    10 % and of 90 % of the change (on log values when ``log``), searched between the two windows.
    """
    s = series.dropna()
    x = np.log(s[s > 0]) if log else s
    b = float(x[before[0]:before[1]].median())
    a = float(x[after[0]:after[1]].median())
    seg = x[before[1]:after[0]]
    frac = (seg - b) / (a - b)
    t10 = frac.index[np.argmax(frac.to_numpy() >= 0.1)]
    t90 = frac.index[np.argmax(frac.to_numpy() >= 0.9)]
    size = float(np.exp(a - b)) if log else a - b
    return {"before": float(np.exp(b)) if log else b, "after": float(np.exp(a)) if log else a,
            "size": size, "t10": t10, "t90": t90, "duration_h": (t90 - t10) / pd.Timedelta(hours=1)}


def settle_signature(series: pd.Series, clear_at, final_level: float, within: float = 0.25,
                     horizon: pd.Timedelta = pd.Timedelta(hours=1)) -> dict:
    """After a clearance: minutes from ``clear_at`` until the series is within ``within`` (relative, log) of
    ``final_level`` for 3 consecutive samples (searched over ``horizon``)."""
    level = float(final_level)
    seg = series[pd.Timestamp(clear_at):pd.Timestamp(clear_at) + horizon].dropna()
    ok = (np.abs(np.log(seg / level)) <= np.log(1 + within)).to_numpy()
    run = np.convolve(ok.astype(int), np.ones(3, dtype=int), mode="valid") == 3
    first = seg.index[int(np.argmax(run))] if run.any() else seg.index[-1]
    return {"final_level": level, "settle_min": (first - pd.Timestamp(clear_at)) / pd.Timedelta(minutes=1)}


def lag_autocorr(series: pd.Series, lag: pd.Timedelta) -> float:
    s = series.dropna()
    shifted = s.copy()
    shifted.index = shifted.index + lag
    j = pd.concat([s, shifted], axis=1, join="inner").dropna()
    return float(j.iloc[:, 0].corr(j.iloc[:, 1])) if len(j) > 2 else float("nan")


# ---------------------------------------------------------------------------------------------
# calibration stage (reads data; writes a new run dir)
# ---------------------------------------------------------------------------------------------

def load_history() -> pd.DataFrame:
    from experiments.nh4_step_0731 import load_history as _load

    return _load()


def _check(rows: list, event: str, metric: str, real: float, injected: float, tol: float, kind: str) -> None:
    if kind == "rel":
        err = abs(injected / real - 1) if real else abs(injected)
    else:
        err = abs(injected - real)
    rows.append({"event": event, "metric": metric, "real": real, "injected": injected, "error": err,
                 "tolerance": tol, "tolerance_kind": kind, "pass": bool(err <= tol + 1e-12)})


def _report(rows: list, event: str, metric: str, real: float, injected: float) -> None:
    rows.append({"event": event, "metric": metric, "real": real, "injected": injected, "error": abs(injected - real),
                 "tolerance": np.nan, "tolerance_kind": "reported_only", "pass": None})


def calibrate(hist: pd.DataFrame, anatomy: pd.DataFrame, raw_e1: pd.DataFrame) -> tuple[dict, pd.DataFrame, dict]:
    """Measure the NB1 catalogue, inject each fault into a clean window, re-measure, compare."""
    rows: list[dict] = []
    cat: dict = {}
    series_for_fig: dict = {}
    an = anatomy.set_index(["event", "variable"])
    T = TOLERANCES

    # --- E1 / E3: NH4 scale steps (1-min history) ---------------------------------------------
    for ev, onset, clean_onset, factor_key in (
        ("E1_20260731", "2026-07-31 14:06:00", "2026-07-24 14:06:00", "E1_2026-07-31"),
        ("E3_20260916", "2026-09-16 15:34:00", "2026-09-11 15:34:00", "E3_2026-09-16"),
    ):
        real_an = an.loc[(factor_key, "NH4")]
        onset, clean_onset = pd.Timestamp(onset), pd.Timestamp(clean_onset)
        win = pd.Timedelta(hours=2)
        real = hist["NH4"][onset - win:onset + win]
        st_real = detect_level_step(real, half_window=5)
        # factor on the same basis as the re-measurement (1-min history, 5-min medians each side)
        factor = 1 / st_real["ratio_before_over_after"]
        cat[ev] = {"variable": "NH4", "onset": str(onset), "factor": factor,
                   "anatomy_ratio_30s": float(real_an["ratio_before_over_after"]),
                   "history_ratio_1min": st_real["ratio_before_over_after"],
                   "transition_samples": 1, "resolution": NH4_RESOLUTION}
        spec = [s for s in NB1_EVENTS[ev] if s.variable == "NH4"][0]
        if abs(spec.params["factor"] / factor - 1) > 2e-3:
            raise AssertionError(f"NB1_EVENTS[{ev}] factor {spec.params['factor']} != measured {factor}")
        clean = hist["NH4"][clean_onset - win:clean_onset + pd.Timedelta(hours=24)]
        inj, _ = scale_step(clean, clean_onset, factor, resolution=NH4_RESOLUTION)
        st_inj = detect_level_step(inj[clean_onset - win:clean_onset + win], half_window=5)
        steps_real = real.index.get_indexer([st_real["first_new_sample"]])[0] - real.index.get_indexer([onset])[0]
        steps_inj = inj.index.get_indexer([st_inj["first_new_sample"]])[0] - inj.index.get_indexer([clean_onset])[0]
        _check(rows, ev, "onset_error_samples", 0.0, float(abs(steps_inj)), T["onset_samples"], "abs")
        _report(rows, ev, "real_onset_error_samples", 0.0, float(abs(steps_real)))
        _check(rows, ev, "step_ratio_before_over_after", st_real["ratio_before_over_after"],
               st_inj["ratio_before_over_after"], T["ratio_rel"], "rel")
        post_real = hist["NH4"][onset + pd.Timedelta(minutes=10):onset + pd.Timedelta(hours=24)]
        post_inj = inj[clean_onset + pd.Timedelta(minutes=10):clean_onset + pd.Timedelta(hours=24)]
        _report(rows, ev, "post24h_relative_spread", relative_spread(post_real), relative_spread(post_inj))
        _report(rows, ev, "post24h_minute_noise_mad_dlog",
                float(np.log(post_real[post_real > 0]).diff().abs().median()),
                float(np.log(post_inj[post_inj > 0]).diff().abs().median()))
        _report(rows, ev, "post24h_lag1h_autocorr", lag_autocorr(post_real, pd.Timedelta(hours=1)),
                lag_autocorr(post_inj, pd.Timedelta(hours=1)))
        series_for_fig[ev] = (real, inj[clean_onset - win:clean_onset + win], onset, clean_onset)

    # --- E1 TSS clearance (30-s raw window: settle takes minutes) ------------------------------
    tss = raw_e1.set_index("t_local")["TSS"].dropna()
    pre_med = float(an.loc[("E1_2026-07-31", "TSS"), "before_median"])
    near = tss[tss.index >= pd.Timestamp("2026-07-31 14:06:00")]
    first_low = near.index[int(np.argmax((near < 0.25 * pre_med).to_numpy()))]
    # settled level = median of the 24 h after the clearance (1-min history), skipping the first 5 min
    final_level = float(hist["TSS"][first_low + pd.Timedelta(minutes=5):first_low + pd.Timedelta(hours=24)].median())
    pre_level = float(tss[first_low - pd.Timedelta(minutes=10):first_low - pd.Timedelta(seconds=1)].median())
    sett_real = settle_signature(tss, first_low, final_level=final_level)
    first_val = float(tss[first_low])
    drop_gain = pre_level / final_level
    residual = first_val / final_level
    # log gain decays from ln(residual) to ln(1.25) at settle_min  =>  tau = t / ln(ln(residual) / ln(1.25))
    tau = sett_real["settle_min"] / np.log(np.log(residual) / np.log(1.25))
    cat["E1_20260731_TSS_clearance"] = {"variable": "TSS", "clear_at": str(first_low), "lag_after_NH4_s":
                                        (first_low - pd.Timestamp("2026-07-31 14:06:00")).total_seconds(),
                                        "pre_level_10min": pre_level, "first_low_value": first_val,
                                        "final_level_24h": final_level, "drop_gain": drop_gain, "residual_gain": residual,
                                        "settle_min_within25pct": sett_real["settle_min"], "settle_tau_min": float(tau)}
    for name, stored, measured in (("E1_TSS_GAIN", E1_TSS_GAIN, drop_gain), ("E1_TSS_RESIDUAL", E1_TSS_RESIDUAL, residual),
                                   ("E1_TSS_SETTLE_MIN", E1_TSS_SETTLE_MIN, tau)):
        if abs(stored / measured - 1) > 0.05:
            raise AssertionError(f"{name} {stored} != measured {measured}")
    # noise-free check of the injector maths, then clean post-clearance TSS (1-min history), fouled plateau
    # cleared at the same clock time on each full day 04/08-11/08 (one day is at the mercy of the clean
    # signal's own minute noise around the 25 % band)
    flat = pd.Series(1.0, index=pd.date_range("2026-08-05 12:00", "2026-08-05 16:00", freq="30s"))
    inj, _ = fouling(flat, "2026-08-05 00:00", pd.Timedelta(minutes=1), drop_gain, clear_at="2026-08-05 14:07:30",
                     residual=residual, settle=pd.Timedelta(minutes=float(tau)))
    _check(rows, "E1_20260731_TSS", "settle_min_noise_free_30s", sett_real["settle_min"],
           settle_signature(inj, pd.Timestamp("2026-08-05 14:07:30"), final_level=1.0)["settle_min"], T["settle_rel"], "rel")
    settles, drops = [], []
    for day in pd.date_range("2026-08-04", "2026-08-11", freq="1D"):
        clear_inj = day + pd.Timedelta(hours=14, minutes=7, seconds=30)
        clean_tss = hist["TSS"][clear_inj - pd.Timedelta(hours=2):clear_inj + pd.Timedelta(hours=25)]
        inj, _ = fouling(clean_tss, day, pd.Timedelta(minutes=1), drop_gain, clear_at=clear_inj,
                         residual=residual, settle=pd.Timedelta(minutes=float(tau)))
        final_inj = float(inj[clear_inj + pd.Timedelta(minutes=5):clear_inj + pd.Timedelta(hours=24)].median())
        settles.append(settle_signature(inj, clear_inj, final_level=final_inj)["settle_min"])
        drops.append(float(inj[clear_inj - pd.Timedelta(minutes=10):clear_inj - pd.Timedelta(seconds=1)].median()) / final_inj)
        if day == pd.Timestamp("2026-08-05"):
            series_for_fig["E1_20260731_TSS"] = (tss["2026-07-31 13:50":"2026-07-31 14:40"],
                                                 inj[clear_inj - pd.Timedelta(minutes=17):clear_inj + pd.Timedelta(minutes=33)],
                                                 first_low, clear_inj)
    # gate on the same 1-min basis as the injected placements (decided after dry run 3, see NOTES)
    settle_real_1min = settle_signature(hist["TSS"], first_low, final_level=final_level)["settle_min"]
    cat["E1_20260731_TSS_clearance"]["settle_min_within25pct_1min"] = settle_real_1min
    _report(rows, "E1_20260731_TSS", "settle_min_30s_vs_median8", sett_real["settle_min"], float(np.median(settles)))
    _check(rows, "E1_20260731_TSS", "settle_min_1min_median8", settle_real_1min, float(np.median(settles)), T["settle_rel"], "rel")
    _report(rows, "E1_20260731_TSS", "settle_min_1min_min8", settle_real_1min, float(np.min(settles)))
    _report(rows, "E1_20260731_TSS", "settle_min_1min_max8", settle_real_1min, float(np.max(settles)))
    _check(rows, "E1_20260731_TSS", "drop_ratio_pre_over_final_median8", drop_gain, float(np.median(drops)), T["gain_rel"], "rel")

    # --- E2: gap + COD stuck at 0 -------------------------------------------------------------
    e2 = an.loc[("E2_2026-08-12", "COD")]
    gap_start, gap_end = pd.Timestamp(e2["max_gap_start"]), pd.Timestamp(e2["max_gap_end"])
    real_gap = float(e2["max_gap_min"])
    cod_after = hist["COD"][gap_end:gap_end + pd.Timedelta(hours=24)]
    cat["E2_20260812"] = {"gap_start_last_sample": str(gap_start), "gap_end_first_sample": str(gap_end),
                          "max_gap_min": real_gap, "missing_minutes": real_gap - 1,
                          "cod_before": float(e2["before_median"]), "cod_after_value": float(cod_after.median()),
                          "cod_after_exact_zero_fraction_24h": float((cod_after == 0).mean())}
    clean = hist["2026-08-05 15:00":"2026-08-05 21:00"].copy()
    clean["COD"] = COD_RAIL
    onset = pd.Timestamp("2026-08-05 16:59")
    specs = [FaultSpec("*", "gap", 0.0, {"duration": real_gap - 1}), FaultSpec("COD", "stuck", real_gap - 1, {"value": 0.0})]
    inj, _ = inject_event(clean, specs, onset)
    _check(rows, "E2_20260812", "max_gap_min", real_gap, max_gap(inj["COD"].dropna().index) / pd.Timedelta(minutes=1),
           T["gap_minutes"], "abs")
    _check(rows, "E2_20260812", "cod_after_value", float(cod_after.median()),
           float(inj["COD"][onset + pd.Timedelta(minutes=real_gap):].median()), T["stuck_value_abs"], "abs")
    nb1_gap = [s for s in NB1_EVENTS["E2_20260812"] if s.kind == "gap"][0].params["duration"]
    if nb1_gap != real_gap:
        raise AssertionError(f"NB1_EVENTS E2 gap {nb1_gap} != measured {real_gap}")

    # --- E3: COD unstick + pH shift (same as anatomy) -----------------------------------------
    e3c, e3p = an.loc[("E3_2026-09-16", "COD")], an.loc[("E3_2026-09-16", "pH")]
    cat["E3_20260916"].update({"cod_unstick_at": str(e3c["first_new_sample"]), "cod_after": float(e3c["after_median"]),
                               "ph_shift_at": str(e3p["first_new_sample"]),
                               "ph_shift": float(e3p["difference_after_minus_before"])})

    # --- D1: pH ramp 19/09 (hourly medians) ---------------------------------------------------
    ph_h = hist["pH"].resample("1h").median()
    w_before, w_after = ("2026-09-18 00:00", "2026-09-19 05:59"), ("2026-09-19 17:00", "2026-09-20 05:59")
    sig = ramp_signature(ph_h, w_before, w_after)
    duration_full = sig["duration_h"] / 0.8
    onset_d1 = sig["t10"] - pd.Timedelta(hours=0.1 * duration_full)
    cat["D1_pH_20260919"] = {"variable": "pH", "delta": sig["size"], "before": sig["before"], "after": sig["after"],
                            "t10": str(sig["t10"]), "t90": str(sig["t90"]), "duration_10_90_h": sig["duration_h"],
                            "onset": str(onset_d1), "duration_h": duration_full,
                            "note": "hourly medians; after the ramp the diurnal cycle changes (not modelled)"}
    shift = pd.Timedelta(days=14)  # clean pH 04-06/09 (full days; 07-10/09 are partial)
    clean_ph = hist["pH"][pd.Timestamp(w_before[0]) - shift:pd.Timestamp(w_after[1]) - shift]
    inj, _ = ramp(clean_ph, onset_d1 - shift, pd.Timedelta(hours=duration_full), delta=sig["size"])
    sig_inj = ramp_signature(inj.resample("1h").median(), tuple(str(pd.Timestamp(w) - shift) for w in w_before),
                             tuple(str(pd.Timestamp(w) - shift) for w in w_after))
    _check(rows, "D1_pH_20260919", "delta_pH", sig["size"], sig_inj["size"], T["delta_abs_pH"], "abs")
    _check(rows, "D1_pH_20260919", "duration_10_90_h", sig["duration_h"], sig_inj["duration_h"], T["duration_rel"], "rel")
    _check(rows, "D1_pH_20260919", "t10_offset_h", 0.0, (sig_inj["t10"] + shift - sig["t10"]) / pd.Timedelta(hours=1), 1.0, "abs")
    series_for_fig["D1_pH_20260919"] = (ph_h[w_before[0]:w_after[1]], inj.resample("1h").median(), sig["t10"], sig["t10"] - shift)

    # --- F1: TSS fouling growth 30/05 -> 08/06 (daily medians), plateau to 31/07 -----------------
    tss_d = hist["TSS"].resample("1D").median()
    f_before, f_after = ("2026-05-30", "2026-06-01"), ("2026-06-07", "2026-06-11")
    fsig = ramp_signature(tss_d, f_before, f_after, log=True)
    plateau = float(hist["TSS"]["2026-07-17":"2026-07-31 12:00"].median())
    post = float(hist["TSS"]["2026-07-31 16:00":"2026-08-12 16:00"].median())
    growth_days = fsig["duration_h"] / 24 / 0.8
    f_onset = fsig["t10"] - pd.Timedelta(days=0.1 * growth_days)
    cat["F1_TSS_fouling"] = {"variable": "TSS", "baseline": fsig["before"], "peak_window_median": fsig["after"],
                             "growth_gain": fsig["size"], "duration_10_90_days": fsig["duration_h"] / 24,
                             "onset": str(f_onset), "growth_days": growth_days, "plateau_median_17_31jul": plateau,
                             "post_clear_median": post, "plateau_gain_vs_post": plateau / post,
                             "plateau_relative_spread": relative_spread(hist["TSS"]["2026-07-17":"2026-07-31 12:00"]),
                             "post_relative_spread": relative_spread(hist["TSS"]["2026-07-31 16:00":"2026-08-12 16:00"])}
    # inject on clean post-clearance TSS: one placement per 2 days from 01/08 to 02/09 (the clean signal's own
    # day-to-day changes move a daily-median crossing by ~1 day, so one placement is not a fair test)
    gains, durs = [], []
    for k in range(17):
        off = pd.Timestamp("2026-08-01") + pd.Timedelta(days=2 * k) - pd.Timestamp(f_before[0])
        clean_tss = hist["TSS"][pd.Timestamp(f_before[0]) + off:pd.Timestamp(f_after[1]) + off + pd.Timedelta(hours=23, minutes=59)]
        inj, _ = fouling(clean_tss, f_onset + off, pd.Timedelta(days=growth_days), fsig["size"])
        fsig_inj = ramp_signature(inj.resample("1D").median(), tuple(str(pd.Timestamp(w) + off) for w in f_before),
                                  tuple(str(pd.Timestamp(w) + off) for w in f_after), log=True)
        gains.append(fsig_inj["size"])
        durs.append(fsig_inj["duration_h"] / 24)
        if k == 0:
            series_for_fig["F1_TSS_fouling"] = (tss_d["2026-05-29":"2026-06-15"], inj.resample("1D").median(), fsig["t10"], fsig["t10"] + off)
    _check(rows, "F1_TSS_fouling", "growth_gain_median17", fsig["size"], float(np.median(gains)), T["gain_rel"], "rel")
    _check(rows, "F1_TSS_fouling", "duration_10_90_days_median17", fsig["duration_h"] / 24, float(np.median(durs)),
           T["duration_rel"], "rel")
    _report(rows, "F1_TSS_fouling", "duration_10_90_days_min17", fsig["duration_h"] / 24, float(np.min(durs)))
    _report(rows, "F1_TSS_fouling", "duration_10_90_days_max17", fsig["duration_h"] / 24, float(np.max(durs)))
    _report(rows, "F1_TSS_fouling", "duration_within_tol_fraction17", 1.0,
            float(np.mean(np.abs(np.array(durs) / (fsig["duration_h"] / 24) - 1) <= T["duration_rel"])))

    # --- R1: COD ramp to the 558.8 rail 06/06 -> 11/06 (daily medians) ---------------------------
    cod_d = hist["COD"].resample("1D").median()
    r_before, r_after = ("2026-05-30", "2026-06-05"), ("2026-06-11", "2026-06-14")
    rsig = ramp_signature(cod_d, r_before, r_after, log=True)
    r_days = rsig["duration_h"] / 24 / 0.8
    r_onset = rsig["t10"] - pd.Timedelta(days=0.1 * r_days)
    cat["R1_COD_rail"] = {"variable": "COD", "baseline": rsig["before"], "rail": COD_RAIL, "factor": rsig["size"],
                          "duration_10_90_days": rsig["duration_h"] / 24, "onset": str(r_onset), "duration_days": r_days,
                          "rail_exact_fraction_after": float((hist["COD"][r_after[0]:r_after[1]] == COD_RAIL).mean())}
    # clean COD exists only 29/05-05/06: synthesise a constant-baseline series with the real minute noise
    rng = np.random.default_rng(20261028)
    base = hist["COD"]["2026-05-30":"2026-06-05"]
    idx = pd.date_range(r_before[0], "2026-06-14 23:59", freq="1min")
    noise = rng.choice((base / base.median()).dropna().to_numpy(), len(idx))
    clean_cod = pd.Series(rsig["before"] * noise, index=idx)
    # the drift behind a rail is censored: the reading sits at exactly 558.8 although the true drift goes on.
    # Overshoot the rail by the inverse of the minute-noise p1, keeping the rail-crossing time unchanged.
    overshoot = 1 / float(np.quantile(noise, 0.01))
    f_rail = COD_RAIL / rsig["before"]
    cat["R1_COD_rail"]["overshoot"] = overshoot
    inj, _ = ramp(clean_cod, r_onset, pd.Timedelta(days=r_days * np.log(f_rail * overshoot) / np.log(f_rail)),
                  factor=f_rail * overshoot, cap=COD_RAIL)
    rsig_inj = ramp_signature(inj.resample("1D").median(), r_before, r_after, log=True)
    _check(rows, "R1_COD_rail", "factor_to_rail", rsig["size"], rsig_inj["size"], T["ratio_rel"], "rel")
    _check(rows, "R1_COD_rail", "duration_10_90_days", rsig["duration_h"] / 24, rsig_inj["duration_h"] / 24,
           T["duration_rel"], "rel")
    _check(rows, "R1_COD_rail", "rail_exact_fraction_after", cat["R1_COD_rail"]["rail_exact_fraction_after"],
           float((inj[r_after[0]:r_after[1]] == COD_RAIL).mean()), 0.05, "abs")
    series_for_fig["R1_COD_rail"] = (cod_d["2026-05-29":"2026-06-15"], inj.resample("1D").median(), rsig["t10"], rsig["t10"])

    return cat, pd.DataFrame(rows), series_for_fig


def make_figure(series_for_fig: dict, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    keys = list(series_for_fig)
    fig, axes = plt.subplots(len(keys), 2, figsize=(11, 2.4 * len(keys)))
    for row, key in zip(np.atleast_2d(axes), keys):
        real, inj, t_real, t_inj = series_for_fig[key]
        for ax, s, t, lab in ((row[0], real, t_real, "NB1 thật"), (row[1], inj, t_inj, "chèn vào đoạn sạch")):
            ax.plot(s.index, s.to_numpy(), lw=0.8, color="#1f4e79")
            ax.axvline(t, color="#c0392b", lw=0.8, ls="--")
            ax.set_title(f"{key} — {lab}", fontsize=9)
            if key.startswith(("E1", "E3", "F1", "R1")):
                ax.set_yscale("log")
            loc = mdates.AutoDateLocator(maxticks=6)
            ax.xaxis.set_major_locator(loc)
            ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
            ax.tick_params(labelsize=7)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1], text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-name", default="paper2-f1-20261028")
    ap.add_argument("--output", type=Path, default=None, help="override run dir (scratch runs)")
    args = ap.parse_args(argv)
    out = args.output or paths.EXPERIMENT_OUTPUT_DIR / args.run_name
    out.mkdir(parents=True, exist_ok=False)

    hist = load_history()
    anatomy = pd.read_csv(STEP_ANATOMY)
    raw_e1 = pd.read_csv(RAW_E1, parse_dates=["t_local"])
    cat, rep, figs = calibrate(hist, anatomy, raw_e1)

    cat_doc = {"station": STATION, "tolerances": TOLERANCES, "nerrs_mapping": NERRS_MAPPING,
               "turb_rail_ntu_assumed": TURB_RAIL_NTU,
               "nb1_events": {k: [asdict(s) for s in v] for k, v in NB1_EVENTS.items()}, "catalogue": cat}
    (out / "nb1_fault_catalog.json").write_text(json.dumps(cat_doc, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    rep.to_csv(out / "reproduction.csv", index=False)
    make_figure(figs, out / "fig_reproduction.png")
    gated = rep[rep["tolerance_kind"] != "reported_only"]
    summary = {"checks": int(len(gated)), "passed": int(gated["pass"].sum()),
               "failed": gated.loc[~gated["pass"].astype(bool), ["event", "metric"]].to_dict("records")}
    inputs = [HISTORY, STEP_ANATOMY, RAW_E1]
    manifest = {"run": out.name, "script": "experiments/paper2_faults.py", "git_head": git_head(),
                "created": pd.Timestamp.now(tz="UTC").isoformat(), "summary": summary,
                "inputs": [{"path": str(p), "sha256": sha256(p), "bytes": p.stat().st_size} for p in inputs],
                "outputs": sorted(p.name for p in out.iterdir())}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(rep.to_string(index=False))
    print(json.dumps(summary, indent=1, default=str))
    return 0 if not summary["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
