"""Paper 2 / F5: forecasting through injected NH4 faults on Korean MOF hourly NH4 (research-only).

PRE-REGISTRATION (fixed 2026-11-02; committed before any forecast or mechanism is run on the scoring period;
``preregistration.json`` in the run dir records the git head; later changes go to NOTES.md "sai lệch").
F1-F3 were exploratory (RL-80); F4 and this step are the confirmatory ones.

Question.  F1-F4 injected NB1-type faults into NERRS DO / Turb / pH.  F5 moves to NH4, the variable that really failed
at NB1 (RL-72: 31/07 /20, 16/09 x6.7), on the three MOF stations that passed step 0 (RL-84): Songdo 15159658,
Busan Suyeong 15159657, Oido 15159129 (hourly analyser, ug/L N by magnitude, no QC flags).  Which handling mechanism
keeps NH4 forecasts best after a fault?

Data.  ``paths.DATA_DIR/foreign/kr_mof/raw`` (write-once, sha256 in its manifest), read as strings with pandas only.
Hourly series = step-0 ``hourly_series`` (median of finite, >= 0 raw values per clock hour; naive local KST).
Channels: NH4 (target), temperature and salinity (ridge covariates and F4 reference channels; never faulted except gap).

Near-clean base (rule fixed before any scoring; ``clean_filter``).  On the hourly NH4:
  * NaN / negative -> missing (step 0); exactly 0 -> missing (LOQ / failure; Songdo 0.4 % of valid hours);
  * stuck: run of >= ``STUCK_H`` = 6 identical present hours -> missing AND dirty;
  * persistent x3 level shift: an hourly |log ratio| >= log 3 whose 72-h medians after / before also differ >= x3
    (step-0 definition with ``MARKER_W_H`` = 72 h instead of 24 h, markers > 72 h apart) -> the +-24 h around it is
    dirty (values kept: natural pulse or real fault cannot be told apart).  72 h: an instrument re-scale persists for
    days (NB1: weeks), natural NH4 pulses at Busan / Oido revert within 1-2 d; chosen after seeing marker counts and
    placement yields on the full series for 24 / 72 / 168 h (no forecast seen) -> 24 h and 168 h are sensitivity runs.
  Injections only where [onset - 2 d, onset + 7 d] contains no dirty hour and >= 80 % of [onset - 8 d, onset + 7 d]
  is valid (never on top of a real stuck run or level shift).  Reported: excluded / dirty share per station.

Time split (anti-leakage; ``time_split``).  Per station, T_split = the hour where the cumulative count of valid
(clean) NH4 hours reaches 50 %.  Calibration = hours < T_split: ridge fit, detector thresholds, timing.  Scoring =
hours >= T_split, and every scoring window [onset - 40 d, onset + 8 d] lies entirely >= T_split (40-d embargo: no
calibration hour enters any context, detector warm-up or score).  Nothing is fit, tuned or selected on scoring hours.

Fault types on NH4 (``inject_nh4``; one variable, five shapes, nothing counted twice; amplitudes from F1 on NB1):
  scale_down  x 1/20.013 in one sample, persistent (NB1 E1 31/07, 1-min history ratio, F1 catalogue).
  scale_up    x 6.722 in one sample, persistent (NB1 E3 16/09 30-s anatomy ratio 1/0.14876, = the task's "x6.7";
              F1's 1-min history ratio 8.1 is NOT used: on an hourly analyser the sample-level ratio is the analogue).
  drift_down  log-linear x 1/12.52 over 6.25 d, then held (shape and size of the only slow multiplicative NB1 fault,
              TSS fouling 06/06: x12.52 in 6.25 d; downward = loss of electrode / analyser sensitivity, and downward
              keeps it from being "fixed" by any range check; NB1 has no NH4 drift - borrowed, stated).
  stuck       frozen at the last valid value from onset, persistent (constant-value failure; NB1 COD stuck at 0.0
              for a month - frozen-last-value chosen instead of 0 so the shape is "no variance" and not a level
              drop that would duplicate scale_down).
  gap         147 min missing on every channel (NB1 E2 12/08) = 3 hourly samples.  Descriptive only: (a) and (b)
              see identical missing data by construction (as F3).
  Re-scaled / drifted values are re-quantised to the station resolution (step 0: Songdo / Busan 0.5, Oido 1.0).
  Hard range: OFF in (b) (instrument range unknown, RL-84; a calibration-max range would mask natural score-period
  highs, Busan score max 5151 vs calibration 2656).  Reported instead: share of scale_up injections whose faulted
  values exceed the calibration max (where a range check could have fired), and for scale_down the share of
  post-fault hours on <= 2 distinct values plus the stuck-detector hit rate (re-quantisation artefact = the F5
  analogue of RL-80's "x8.1 above the hard range" caveat).
Placements (``place_h``).  Per station up to ``N_MAX`` = 40 seeded onsets (SEED, station) on eligible hours,
>= 8 d apart (post-7-d windows of two onsets never overlap); EVERY type is injected at every onset (paired design)
and each onset is also a paired random sham (nothing injected).  Event shams (``event_onsets``, built inside the
score stage): up to ``N_EVENT_MAX`` = 30 seeded onsets at natural step-alarm episode starts on the uninjected
scoring-period NH4 (the places where re-alignment fires: F4 failed on exactly these), same validity rule, no stuck
/ zero hour in [onset - 2 d, onset + 7 d] (shift markers allowed - they are the natural events), >= 8 d apart.

Detectors (hourly, causal; F2 logic re-stated with explicit hourly constants, ``detect_h``).  z = log(NH4 + 1)
(c = 1 ug/L ~ resolution).  stuck: >= k identical readings; step: |median z(last W) - median z(W before)| / sigma,
W = 3 h, sigma = 1.4826 median |dz| over the trailing 7 d ending 2W before, floor 0.02; drift: 24-h median vs the
7-d median ending 1 d before, tau from 30 d ending 8 d before, floor 0.02; gap: >= 2 missing hours; range: x < 0
only.  Per station, on its calibration base: smallest theta on F2's THETA_GRID and smallest k on STUCK_K_GRID_H with
<= 1 alarm episode / 30 d (episodes merged < 6 h apart).  No ``cross`` (one faulted channel).  ``flags`` = range |
stuck | gap | drift; ``changepoints`` = step.

Models.  Primary: ``RidgeH`` - B4D-style ridge on z (lags 1-24 h, same-hour 1-2 d ago, 7-d diurnal profile,
24-h amplitude / std / mean, 7-d mean, hour-of-day of origin and target, temperature and salinity deviations from
their 24-h mean + 1-h salinity change + 24-h temperature change), Delta-target, StandardScaler + Ridge(alpha = 1), per
station x horizon, fit on the calibration base (no day-of-year terms: < 1 yr of calibration at Busan / Oido).  Feature
NaN -> 0; inputs forward-filled after masking (F3).  PI80 = +- q80 |training residual| in z.  Forecasts and MAE
back-transformed to ug/L.  Secondary: Chronos-2 small (paper 1 pinned revision, F4 wrapper), zero-shot,
univariate, context 672 h (28 d), q0.1 / q0.5 / q0.9, 2 torch threads, run in .venv-fm; run iff the calibration
timing (``timing`` stage, slowest injection x max planned injections) is <= ``FM_BUDGET_H`` = 12 h CPU
(``fm_will_run`` in preregistration.json, decided before scoring).

Mechanisms (input at origin t from data <= t; target NH4 only):
  (a) ``a``  ignore.   (b) ``b``  QC mask (flags -> missing).
  (c') ``c_align``  F3: (b) + level re-alignment at every change point (re-located split, accumulated shifts).
  F4 ``v2``  bounded: latest change point with (i) >= 80 % of the shift within <= 2 samples, (iii) |d| >= log 3,
           (ii) temperature < 0.5 degC and salinity < 2 psu medians unchanged across it; base (a); a priori F4
           thresholds, NOT re-tuned for hourly NH4 (F5 tests whether F4 transfers).  ``v3`` = v2 with 72-h half-life decay.
  (d) ``d``  online-adaptation PROXY: (a) + EW mean of realised residuals, half-life 6 h (F3).  Only a proxy, not
           FSNet / TAFAS.
  (e) ACI  F3 delayed-feedback ACI on each mechanism's PI80 (feedback from the observed, faulted stream).
Origins (F3 ``origin_times``): hourly from onset - 48 h to + 47 h, then 3-hourly to + 7 d.  Windows: baseline
[-24 h, 0), post24 [0, 24 h), post7 [24 h, 7 d).  Horizons 1 h (primary) and 6 h.  Truth = the clean base.

Metrics.  Per injection x model x mechanism x horizon: MAE baseline / post24 / post7 (ug/L), recovery time (F3),
PI80 coverage static / ACI vs truth, width; detection within 24 h (abrupt) / 7 d (drift) and paired-sham excess,
false-alarm episodes / 30 d on the uninjected scoring series.  Reduction vs (a) = 1 - geomean(MAE_m / MAE_a).

Decision rule (CONFIRMATORY; ridge, h = 1 h, post24; per station, never pooled - 3 stations are not a large sample):
  pass(station, type): reduction >= 30 % AND Holm-adjusted p < 0.05, where p = two-sided bootstrap p of the mean
    log ratio (by injection, 4000 draws, seed fixed; = the 95 % CI excludes 0 before adjustment).  Holm family =
    one model x station: 5 mechanisms (b, c_align, v2, v3, d) x 4 rule types (scale_down, scale_up, drift_down,
    stuck) = 20 tests.  A type with < ``MIN_N`` = 8 usable injections at a station is "not evaluable" (= not pass).
  useful(station): >= 3 of the 4 rule types pass (2/3 of 4 rounded up; since only 2 types are re-scales this needs at
    least one of drift_down / stuck: the RL-80 double-count lesson) AND sham harm (geomean ratio - 1, point estimate)
    <= 5 % on random shams AND on event shams (event set with < MIN_N onsets -> random only, reported).
  USEFUL (headline): useful at >= 2 of the 3 stations.  Same rule run separately for Chronos-2 (secondary
  confirmatory; the ridge verdict is the headline).
  Pre-stated power caveat: Oido / Busan have ~10-20 onsets per type -> wide CIs; "not passing" there is weak evidence.
DESCRIPTIVE: gap type; h = 6 h; post7; recovery; PI80 static / ACI vs band [0.75, 0.85]; detection / false alarms;
  v2 / v3 trigger rates and delays; station-month-cluster CIs; pooled numbers (labelled as such); NB1 illustration.
SENSITIVITY (ridge only, same code with a flag): stuck >= 3 h in the clean filter (step-0 sensitivity; mainly Oido),
  zero treated as valid, shift-marker window 24 h and 168 h.  Reported, never replaces the confirmatory verdict.

NB1 (``stage_nb1``, illustration only, outside the rule): NB1 NH4 hourly medians (``sensor-history-20261024``), detector
thresholds from NB1 2026-06-01..2026-07-30 (pre-E1) with the same FA rule, Chronos-2 small (no NB1 ridge),
around E1 31/07 14:00 and E3 16/09 15:00: mean 1-h forecast level 0-24 h after per mechanism vs observed pre / post.

Stages (write-once run dir ``paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME``; ``--output`` for scratch runs):
    python -I experiments/paper2_f5_nh4.py calibrate   # filter, split, thresholds, placements (no forecasts)
    python -I experiments/paper2_f5_nh4.py timing      # ridge + Chronos-2 on 3 CALIBRATION onsets of one station
    python -I experiments/paper2_f5_nh4.py prereg      # preregistration.json (git head, design, calibration sha256)
    python -I experiments/paper2_f5_nh4.py score --model ridge|chronos2 [--sensitivity NAME]
    python -I experiments/paper2_f5_nh4.py evaluate
    python -I experiments/paper2_f5_nh4.py nb1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import warnings
import zlib
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from experiments.paper2_detect import THETA_GRID, episodes, gap_flag, stuck_run  # noqa: E402
from experiments.paper2_faults import FaultSpec, git_head, inject_event  # noqa: E402
from experiments.paper2_mechanisms import (  # noqa: E402
    WINDOWS, aci_intervals, contexts_for, online_bias, origin_times, recovery_hours, window_mask)

RUN_NAME = "paper2-f5-20261102"
SCRIPT = "experiments/paper2_f5_nh4.py"
SEED = 20261102
STATIONS = {"15159658": ("songdo", 0.5), "15159657": ("busan_suyeong", 0.5), "15159129": ("oido", 1.0)}
KR_RAW = paths.DATA_DIR / "foreign" / "kr_mof" / "raw"
STEP0_RUN = paths.EXPERIMENT_OUTPUT_DIR / "paper2-f5step0-20261102"
F1_RUN = paths.EXPERIMENT_OUTPUT_DIR / "paper2-f1-20261028"

# --- clean filter / split / placement
STUCK_H = 6
MARKER_W_H = 72
MARKER_PAD_H = 24
ZERO_INVALID = True
SPLIT_FRACTION = 0.5
WIN_BEFORE, WIN_AFTER = pd.Timedelta(days=40), pd.Timedelta(days=8)
VALID_SPAN = (pd.Timedelta(days=8), pd.Timedelta(days=7))
CLEAN_SPAN = (pd.Timedelta(days=2), pd.Timedelta(days=7))
MIN_VALID = 0.8
MIN_SEP = pd.Timedelta(days=8)
N_MAX, N_EVENT_MAX = 40, 30
SENSITIVITY = {"stuck3": {"stuck_h": 3}, "zero_valid": {"zero_invalid": False},
               "marker24": {"marker_w": 24}, "marker168": {"marker_w": 168}}

# --- faults (F1 catalogue, NB1)
E1_FACTOR = 1 / 20.013145539906102          # F1 catalogue E1 history_ratio_1min
E3_FACTOR = 1 / 0.1487603305785124          # F1 catalogue E3 anatomy_ratio_30s (= x6.72)
DRIFT_FACTOR = 1 / 12.520661157024799       # F1 TSS fouling growth gain
DRIFT_DAYS = 6.25
GAP_MIN = 147.0
FAULT_KINDS = ("scale_down", "scale_up", "drift_down", "stuck", "gap")
RULE_KINDS = ("scale_down", "scale_up", "drift_down", "stuck")
RESCALE_KINDS = ("scale_down", "scale_up")
CREDIT_H = {"scale_down": 24, "scale_up": 24, "stuck": 24, "gap": 24, "drift_down": 7 * 24}

# --- detectors (hourly)
NH4_C = 1.0
W_H = 3
DAY_H = 24
SIGMA_FLOOR_H = 0.02
STUCK_K_GRID_H = (2, 3, 4, 5, 6, 8, 12, 24, 48)
FA_TARGET_PER_30D = 1.0
MERGE_H = 6
GAP_MIN_H = 2

# --- F4 bounded trigger (a priori, as F4)
JUMP_FRACTION = 0.8
MIN_LOG_RATIO = float(np.log(3.0))
REF_THRESHOLDS = {"temp": 0.5, "sal": 2.0}
REF_MIN_PRE, REF_MIN_POST = 2, 1
DECAY_HALFLIFE_H = 72.0

# --- models / scoring
H_STEPS = {60: 1, 360: 6}
LAGS_H = (1, 2, 3, 4, 6, 8, 12, 24)
RIDGE_ALPHA = 1.0
CHRONOS2_NAME = "chronos-2-small"
TORCH_THREADS = 2
FM_BUDGET_H = 12.0
MECHS =("a", "b", "c_align", "v2", "v3", "d")
TESTED = ("b", "c_align", "v2", "v3", "d")
GAIN_MIN, HARM_MAX, ALPHA, MIN_N = 0.30, 0.05, 0.05, 8
TYPES_NEEDED, STATIONS_NEEDED = 3, 2
N_BOOT = 4000
PI_BAND = (0.75, 0.85)


# =============================================================================================
# data
# =============================================================================================

def load_station(pk: str) -> pd.DataFrame:
    """Hourly NH4 / temp / sal of one MOF station (step-0 reader; pandas only, strings first)."""
    from experiments.paper2_kr_nh4_step0 import AUX, find_col, hourly_series, pick_columns, read_raw

    name = STATIONS[pk][0]
    path = KR_RAW / f"{pk}_{name}.csv"
    df = read_raw(path, pick=pick_columns)
    cols = list(df.columns)
    tcol, ncol = find_col(cols, ("관측일시",)), find_col(cols, ("암모니아",))
    out = {"NH4": hourly_series(df[tcol], df[ncol])}
    for key in ("temp", "sal"):
        c = find_col(cols, AUX[key], exclude=("기온",))
        out[key] = hourly_series(df[tcol], df[c]) if c else pd.Series(dtype=float)
    idx = out["NH4"].index
    return pd.DataFrame({k: v.reindex(idx) for k, v in out.items()})


# =============================================================================================
# near-clean base, split, placements (pure)
# =============================================================================================

def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    out, i = [], 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j + 1 < len(mask) and mask[j + 1]:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def stuck_mask_h(x: pd.Series, min_hours: int) -> np.ndarray:
    """True inside runs of >= min_hours consecutive present hours with identical value (step-0 rule)."""
    v = x.to_numpy(dtype=float)
    same = np.zeros(len(v), dtype=bool)
    same[1:] = np.isfinite(v[1:]) & np.isfinite(v[:-1]) & (v[1:] == v[:-1])
    out = np.zeros(len(v), dtype=bool)
    i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and same[j + 1]:
            j += 1
        if np.isfinite(v[i]) and j - i + 1 >= min_hours:
            out[i:j + 1] = True
        i = j + 1
    return out


def shift_markers(x: pd.Series, w: int) -> np.ndarray:
    """Indices h with |log x[h]/x[h-1]| >= log 3 and |log median(x[h..h+w-1]) / median(x[h-w..h-1])| >= log 3,
    de-duplicated (> w apart).  NaN / non-positive values are ignored (step-0 definition, window w)."""
    xv = x.where(x > 0)
    lx = np.log(xv.to_numpy(dtype=float))
    jump = np.zeros(len(lx), dtype=bool)
    with np.errstate(invalid="ignore"):
        jump[1:] = np.abs(lx[1:] - lx[:-1]) >= MIN_LOG_RATIO
    pre = xv.rolling(w, min_periods=w // 2).median().to_numpy()
    post = xv[::-1].rolling(w, min_periods=w // 2).median()[::-1].to_numpy()
    big = np.zeros(len(lx), dtype=bool)
    with np.errstate(divide="ignore", invalid="ignore"):
        big[1:] = np.abs(np.log(post[1:] / pre[:-1])) >= MIN_LOG_RATIO
    cand = np.flatnonzero(jump & big)
    if len(cand):
        cand = cand[np.insert(np.diff(cand) > w, 0, True)]
    return cand


def clean_filter(nh4: pd.Series, stuck_h: int = STUCK_H, marker_w: int = MARKER_W_H,
                 zero_invalid: bool = ZERO_INVALID, pad_h: int = MARKER_PAD_H) -> dict:
    """Near-clean base: ``base`` (NH4 with invalid hours NaN), ``valid``, ``dirty`` (stuck | zero | marker +-pad;
    blocks placement), ``nodata_fault`` (stuck | zero only; used by event shams), ``markers`` and shares."""
    x = nh4.astype(float)
    present = x.notna().to_numpy() & (x.to_numpy() >= 0)
    zero = present & (x.to_numpy() == 0) if zero_invalid else np.zeros(len(x), dtype=bool)
    st = stuck_mask_h(x.where(present), stuck_h)
    valid = present & ~zero & ~st
    base = x.where(valid)
    mk = shift_markers(base, marker_w)
    near = np.zeros(len(x), dtype=bool)
    for i in mk:
        near[max(0, i - pad_h):i + pad_h + 1] = True
    hard = st | zero
    n_present = max(int(present.sum()), 1)
    return {"base": base, "valid": pd.Series(valid, index=x.index), "dirty": pd.Series(hard | near, index=x.index),
            "hard": pd.Series(hard, index=x.index), "markers": x.index[mk],
            "shares": {"present_hours": int(present.sum()), "valid_hours": int(valid.sum()),
                       "zero_share": round(float(zero.sum() / n_present), 5),
                       "stuck_share": round(float(st.sum() / n_present), 5),
                       "marker_n": int(len(mk)), "marker_zone_share": round(float((near & present).sum() / n_present), 5),
                       "dirty_share": round(float(((hard | near) & present).sum() / n_present), 5),
                       "excluded_share": round(float((present & ~valid).sum() / n_present), 5)}}


def time_split(valid: pd.Series, fraction: float = SPLIT_FRACTION) -> pd.Timestamp:
    """First hour at which the cumulative count of valid hours reaches ``fraction`` of the total."""
    v = valid.to_numpy(dtype=bool)
    if not v.any():
        raise ValueError("no valid hours")
    cum = np.cumsum(v) / v.sum()
    return valid.index[int(np.searchsorted(cum, fraction))]


def eligible_onsets(valid: pd.Series, dirty: pd.Series, period: tuple, *, valid_span=VALID_SPAN,
                    clean_span=CLEAN_SPAN, min_valid: float = MIN_VALID) -> pd.DatetimeIndex:
    """Hours t with [t - 40 d, t + 8 d] inside ``period`` = [lo, hi), >= min_valid valid hours in
    [t - valid_span[0], t + valid_span[1]) and no dirty hour in [t - clean_span[0], t + clean_span[1])."""
    idx = valid.index
    lo, hi = pd.Timestamp(period[0]), pd.Timestamp(period[1])
    vc = np.r_[0, np.cumsum(valid.to_numpy(dtype=int))]
    dc = np.r_[0, np.cumsum(dirty.to_numpy(dtype=int))]
    t = idx[(idx - WIN_BEFORE >= lo) & (idx + WIN_AFTER < hi)]
    if not len(t):
        return t
    pos = idx.get_indexer(t)
    va, vb = idx.searchsorted(t - valid_span[0]), idx.searchsorted(t + valid_span[1])
    da, db = idx.searchsorted(t - clean_span[0]), idx.searchsorted(t + clean_span[1])
    frac = (vc[vb] - vc[va]) / np.maximum(vb - va, 1)
    ok = (frac >= min_valid) & ((dc[db] - dc[da]) == 0) & valid.to_numpy()[pos]
    return t[ok]


def place_h(candidates: pd.DatetimeIndex, n_max: int, rng: np.random.Generator,
            min_sep: pd.Timedelta = MIN_SEP) -> list[pd.Timestamp]:
    """Seeded greedy draw (random order) of up to n_max candidates pairwise >= min_sep apart; sorted."""
    chosen: list[pd.Timestamp] = []
    for i in rng.permutation(len(candidates)):
        t = candidates[int(i)]
        if all(abs(t - c) >= min_sep for c in chosen):
            chosen.append(t)
            if len(chosen) == n_max:
                break
    return sorted(chosen)


def _rng(*parts) -> np.random.Generator:
    return np.random.default_rng([SEED, zlib.crc32("|".join(map(str, parts)).encode())])


# =============================================================================================
# faults on NH4 (pure)
# =============================================================================================

def fault_specs_nh4(kind: str) -> list[FaultSpec]:
    if kind == "scale_down":
        return [FaultSpec("NH4", "scale_step", 0.0, {"factor": E1_FACTOR})]
    if kind == "scale_up":
        return [FaultSpec("NH4", "scale_step", 0.0, {"factor": E3_FACTOR})]
    if kind == "drift_down":
        return [FaultSpec("NH4", "ramp", 0.0, {"factor": DRIFT_FACTOR, "duration": DRIFT_DAYS * 1440})]
    if kind == "stuck":
        return [FaultSpec("NH4", "stuck", 0.0, {})]
    if kind == "gap":
        return [FaultSpec("*", "gap", 0.0, {"duration": GAP_MIN})]
    raise KeyError(kind)


def inject_nh4(frame: pd.DataFrame, kind: str, onset, resolution: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """F1 ``inject_event`` + re-quantisation of re-scaled / drifted NH4 to the station resolution."""
    out, labels = inject_event(frame, fault_specs_nh4(kind), onset)
    if kind in ("scale_down", "scale_up", "drift_down") and resolution:
        m = labels["NH4"].ne("").to_numpy()
        v = out["NH4"].to_numpy(dtype=float).copy()
        v[m] = np.round(v[m] / resolution) * resolution
        out["NH4"] = v
    return out, labels


def fault_diagnostics(truth: pd.Series, faulted: pd.Series, onset: pd.Timestamp, cal_max: float) -> dict:
    """Range / quantisation diagnostics of one injection over [onset, onset + 7 d)."""
    post = faulted[onset:onset + pd.Timedelta(days=7) - pd.Timedelta(hours=1)].dropna()
    p24 = faulted[onset:onset + pd.Timedelta(hours=23)].dropna()
    return {"exceeds_cal_max": bool((post > cal_max).any()) if len(post) else False,
            "share_above_cal_max": float((post > cal_max).mean()) if len(post) else np.nan,
            "distinct_post24": int(p24.nunique()), "low_distinct_post24": bool(p24.nunique() <= 2) if len(p24) else False,
            "pre24_median": float(truth[onset - pd.Timedelta(hours=24):onset - pd.Timedelta(hours=1)].median())}


# =============================================================================================
# hourly detectors (pure, causal)
# =============================================================================================

def z_of(x: pd.Series, c: float = NH4_C) -> pd.Series:
    return np.log(x.astype(float).clip(lower=0) + c)


def step_score_h(x: pd.Series, w: int = W_H, c: float = NH4_C, day: int = DAY_H) -> pd.Series:
    z = z_of(x, c)
    a = z.rolling(w, min_periods=w - 1).median()
    b = a.shift(w)
    sig = 1.4826 * z.diff().abs().rolling(7 * day, min_periods=day).median().shift(2 * w)
    return (a - b).abs() / sig.clip(lower=SIGMA_FLOOR_H)


def drift_score_h(x: pd.Series, c: float = NH4_C, day: int = DAY_H) -> pd.Series:
    z = z_of(x, c)
    m24 = z.rolling(day, min_periods=day // 2).median()
    base = z.rolling(7 * day, min_periods=7 * day // 2).median().shift(day)
    dd = (m24 - m24.shift(day)).abs()
    tau = 1.4826 * dd.rolling(30 * day, min_periods=7 * day).median().shift(8 * day)
    return (m24 - base).abs() / tau.clip(lower=SIGMA_FLOOR_H)


def detect_h(x: pd.Series, params: dict) -> dict[str, pd.Series]:
    """Boolean alarm series on the hourly NH4 ``x``: range (x < 0), stuck, step, drift, gap."""
    out = {"range": (x < 0).fillna(False).astype(bool), "gap": gap_flag(x, GAP_MIN_H)}
    k = params.get("stuck_k")
    out["stuck"] = (stuck_run(x) >= k) if k else pd.Series(False, index=x.index)
    out["step"] = (step_score_h(x) > params["theta_step"]).fillna(False).astype(bool)
    out["drift"] = (drift_score_h(x) > params["theta_drift"]).fillna(False).astype(bool)
    return out


def flags_h(det: dict) -> pd.Series:
    return det["range"] | det["stuck"] | det["gap"] | det["drift"]


def _rate(n: int, days: float) -> float:
    return 30.0 * n / days if days else np.inf


def calibrate_h(series: list[pd.Series]) -> dict:
    """Smallest step / drift theta (F2 grid) and stuck k with <= FA target episodes / 30 d on clean series."""
    days = sum(int(s.notna().sum()) for s in series) / 24.0
    out = {"days": round(days, 2)}
    for name, fn in (("theta_step", step_score_h), ("theta_drift", drift_score_h)):
        scs = [fn(s) for s in series]
        chosen, curve = None, []
        for th in THETA_GRID:
            r = _rate(sum(len(episodes(sc > th, MERGE_H)) for sc in scs), days)
            curve.append((float(th), round(r, 4)))
            if chosen is None and r <= FA_TARGET_PER_30D:
                chosen = float(th)
        out[name] = chosen if chosen is not None else float(THETA_GRID[-1])
        out[name + "_capped"] = chosen is None
        out[name + "_curve"] = curve
    runs = [stuck_run(s) for s in series]
    out["stuck_k"], out["stuck_curve"] = None, []
    for k in STUCK_K_GRID_H:
        r = _rate(sum(len(episodes(rn >= k, MERGE_H)) for rn in runs), days)
        out["stuck_curve"].append((k, round(r, 4)))
        if out["stuck_k"] is None and r <= FA_TARGET_PER_30D:
            out["stuck_k"] = k
    return out


def change_points_h(step_alarm: pd.Series, w: int = W_H) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """(alarm time, change-point estimate = alarm - (w - 1) h) per step-alarm episode."""
    return [(a, a - pd.Timedelta(hours=w - 1)) for a in episodes(step_alarm, MERGE_H)]


def refine_cp(z: np.ndarray, a: int, w: int) -> tuple[int, float]:
    """Causal re-location (F3 ``Inputs._refine``): split k in (a - 2w, a] maximising |median z[k..a] -
    median z[k-w..k-1]|; returns (k, signed shift).  k = -1 when nothing is computable."""
    best = (0.0, -1, 0.0)
    for k in range(max(w, a - 2 * w + 1), a + 1):
        post, pre = z[k:a + 1], z[k - w:k]
        post, pre = post[np.isfinite(post)], pre[np.isfinite(pre)]
        if len(post) and len(pre):
            d = float(np.median(post) - np.median(pre))
            if abs(d) > best[0]:
                best = (abs(d), k, d)
    return best[1], best[2]


def assess_cp_h(z: np.ndarray, k: int, a: int, d: float, ref: dict[str, np.ndarray], w: int = W_H) -> dict:
    """F4 ``assess_cp`` with an explicit window w (F4 used W = 4 samples); NH4 is log-transformed."""
    if k < 1 or a < k:
        return {"shift": float(d), "jump": np.nan, "jump_frac": np.nan, "instant": False, "magnitude": False,
                "ref_dtemp": np.nan, "ref_dsal": np.nan, "ref_available": 0, "ref_quiet": False}
    jumps = []
    for j in range(max(1, k - w), min(k + w, a) + 1):
        if np.isfinite(z[j]) and np.isfinite(z[j - 1]):
            jumps.append(float(z[j] - z[j - 1]))
            if j + 1 <= a and np.isfinite(z[j + 1]):
                jumps.append(float(z[j + 1] - z[j - 1]))
    jump = max(jumps, key=abs) if jumps else np.nan
    instant = bool(np.isfinite(jump) and d != 0 and np.sign(jump) == np.sign(d) and abs(jump) >= JUMP_FRACTION * abs(d))
    out = {"shift": float(d), "jump": jump, "jump_frac": abs(jump) / abs(d) if d and np.isfinite(jump) else np.nan,
           "instant": instant, "magnitude": bool(abs(d) >= MIN_LOG_RATIO)}
    available, stepped = 0, False
    for name, thr in REF_THRESHOLDS.items():
        arr = ref.get(name)
        out[f"ref_d{name}"] = np.nan
        if arr is None:
            continue
        pre, post = arr[max(0, k - w):k], arr[k:a + 1]
        pre, post = pre[np.isfinite(pre)], post[np.isfinite(post)]
        if len(pre) < REF_MIN_PRE or len(post) < REF_MIN_POST:
            continue
        delta = abs(float(np.median(post) - np.median(pre)))
        out[f"ref_d{name}"] = delta
        available += 1
        stepped |= delta >= thr
    out["ref_available"] = available
    out["ref_quiet"] = bool(available >= 1 and not stepped)
    return out


VARIANTS = {"v1": ("instant", "magnitude"), "v2": ("instant", "magnitude", "ref_quiet"),
            "v3": ("instant", "magnitude", "ref_quiet")}


class F5Inputs:
    """Mechanism inputs for the NH4 column: (a), (b), F3 (c'), F4 v1-v3.  ``key(mech, t)`` depends on data <= t only;
    identical keys share one forecast (a silent F4 variant is exactly (a))."""

    def __init__(self, obs: pd.Series, flags: pd.Series, cps: list, ref: pd.DataFrame | None = None,
                 c: float = NH4_C, w: int = W_H):
        self.obs, self.c, self.w = obs.astype(float), c, w
        self.masked = self.obs.where(~flags.reindex(obs.index).fillna(False).astype(bool).to_numpy())
        z = z_of(self.obs, c).to_numpy(dtype=float)
        refs = {} if ref is None else {n: ref[n].reindex(obs.index).to_numpy(dtype=float) for n in ref.columns}
        self.cps = []
        for alarm, cp in cps:
            a = int(obs.index.get_indexer([alarm])[0])
            k, d = refine_cp(z, a, w)
            if k < 0:  # nothing computable around the alarm: zero shift, never qualifies
                k, d = max(a - (w - 1), 1), 0.0
            self.cps.append({"alarm": alarm, "cp": obs.index[k], "k": k} | assess_cp_h(z, k, a, d, refs, w))
        self.cps.sort(key=lambda s: s["alarm"])
        self.qual = {v: [i for i, s in enumerate(self.cps) if all(s[cnd] for cnd in conds)] for v, conds in VARIANTS.items()}
        self._cache: dict = {}

    def active(self, t: pd.Timestamp) -> int:
        return sum(1 for s in self.cps if s["alarm"] <= t)

    def latest(self, variant: str, t: pd.Timestamp) -> int | None:
        q = [i for i in self.qual[variant] if self.cps[i]["alarm"] <= t]
        return q[-1] if q else None

    def key(self, mech: str, t: pd.Timestamp) -> tuple:
        if mech in ("a", "d"):
            return ("a",)
        if mech == "b":
            return ("b",)
        if mech == "c_align":
            n = self.active(t)
            return ("c_align", n) if n else ("b",)
        i = self.latest(mech, t)
        if i is None:
            return ("a",)
        wgt = 1.0
        if mech == "v3":
            wgt = round(0.5 ** (((t - self.cps[i]["alarm"]) / pd.Timedelta(hours=1)) / DECAY_HALFLIFE_H), 6)
        return ("shift", i, wgt)

    def build(self, key: tuple) -> pd.Series:
        if key not in self._cache:
            self._cache[key] = self._build(key)
        return self._cache[key]

    def _build(self, key: tuple) -> pd.Series:
        if key[0] == "a":
            return self.obs
        if key[0] == "b":
            return self.masked
        if key[0] == "c_align":
            z = z_of(self.masked, self.c).to_numpy(dtype=float).copy()
            for s in self.cps[:key[1]]:
                z[s["k"]:] -= s["shift"]
            return pd.Series(np.exp(z) - self.c, index=self.obs.index, name=self.obs.name)
        _, i, wgt = key
        s = self.cps[i]
        z = z_of(self.obs, self.c).to_numpy(dtype=float).copy()
        z[s["k"]:] -= wgt * s["shift"]
        return pd.Series(np.exp(z) - self.c, index=self.obs.index, name=self.obs.name)

    def trigger_info(self, onset: pd.Timestamp, last_origin: pd.Timestamp) -> dict:
        row = {"n_cp": len(self.cps)}
        for v in VARIANTS:
            q = self.qual[v]
            hits = [self.cps[i]["alarm"] for i in q
                    if onset - pd.Timedelta(hours=1) <= self.cps[i]["alarm"] <= onset + pd.Timedelta(hours=24)]
            row[f"{v}_n"] = len(q)
            row[f"{v}_triggered"] = any(self.cps[i]["alarm"] <= last_origin for i in q)
            row[f"{v}_hit24"] = bool(hits)
            row[f"{v}_delay_h"] = (min(hits) - onset) / pd.Timedelta(hours=1) if hits else np.nan
        return row


# =============================================================================================
# models
# =============================================================================================

RIDGE_FEATURES = ([f"d{k}" for k in LAGS_H] + ["s24", "s48", "prof7", "amp24", "std24", "mean24", "mean7d",
                  "hod_sin", "hod_cos", "hodv_sin", "hodv_cos", "sal_dev24", "sal_d1", "temp_dev24", "temp_d24"])


def ridge_features(nh4: pd.Series, cov: pd.DataFrame | None, idx: np.ndarray, hs: int, c: float = NH4_C) -> pd.DataFrame:
    """Hourly B4D-style features at origin positions ``idx`` (reads values at <= idx only) + target delta."""
    z = z_of(nh4, c).to_numpy(dtype=float)
    n = len(z)
    idx = np.asarray(idx, dtype=np.int64)

    def at(arr, j):
        out = np.full(len(j), np.nan)
        ok = (j >= 0) & (j < len(arr))
        out[ok] = arr[j[ok]]
        return out

    cur = at(z, idx)
    f = {f"d{k}": at(z, idx - k) - cur for k in LAGS_H}
    f["s24"] = at(z, idx + hs - 24) - cur
    f["s48"] = at(z, idx + hs - 48) - cur
    fut = np.stack([at(z, idx + hs - 24 * d) for d in range(1, 8)])
    now = np.stack([at(z, idx - 24 * d) for d in range(1, 8)])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN columns -> NaN
        prof = np.nanmean(fut, axis=0) - np.nanmean(now, axis=0)
    f["prof7"] = np.where((np.isfinite(fut).sum(0) >= 3) & (np.isfinite(now).sum(0) >= 3), prof, np.nan)
    zs = pd.Series(z)
    r24 = zs.rolling(24, min_periods=12)
    safe = np.clip(idx, 0, n - 1)
    f["amp24"] = (r24.max() - r24.min()).to_numpy()[safe]
    f["std24"] = r24.std().to_numpy()[safe]
    f["mean24"] = r24.mean().to_numpy()[safe] - cur
    f["mean7d"] = zs.rolling(168, min_periods=84).mean().to_numpy()[safe] - cur
    hour = np.asarray(nh4.index.hour, dtype=float)
    hr = at(hour, idx)
    hv = (hr + hs) % 24
    f["hod_sin"], f["hod_cos"] = np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24)
    f["hodv_sin"], f["hodv_cos"] = np.sin(2 * np.pi * hv / 24), np.cos(2 * np.pi * hv / 24)
    for name in ("sal", "temp"):
        if cov is not None and name in cov:
            a = cov[name].reindex(nh4.index).to_numpy(dtype=float)
            m24 = pd.Series(a).rolling(24, min_periods=12).mean().to_numpy()
            f[f"{name}_dev24"] = at(a, idx) - at(m24, idx)
            if name == "sal":
                f["sal_d1"] = at(a, idx) - at(a, idx - 1)
            else:
                f["temp_d24"] = at(a, idx) - at(a, idx - 24)
        else:
            f[f"{name}_dev24"] = np.full(len(idx), np.nan)
            f["sal_d1" if name == "sal" else "temp_d24"] = np.full(len(idx), np.nan)
    out = pd.DataFrame(f)[RIDGE_FEATURES]
    out["current"] = cur
    out["delta"] = at(z, idx + hs) - cur
    return out


class RidgeH:
    """Per station x horizon ridge on z = log(NH4 + c), Delta target; PI80 = +- q80 |train residual| in z."""

    def __init__(self, c: float = NH4_C):
        self.c = c
        self.fits: dict = {}

    def fit(self, nh4: pd.Series, cov: pd.DataFrame | None) -> "RidgeH":
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        for h, hs in H_STEPS.items():
            rows = ridge_features(nh4, cov, np.arange(len(nh4)), hs, self.c)
            rows = rows.dropna(subset=["current", "d1", "delta"])
            X, y = rows[RIDGE_FEATURES].fillna(0.0).to_numpy(), rows["delta"].to_numpy()
            model = make_pipeline(StandardScaler(), Ridge(alpha=RIDGE_ALPHA)).fit(X, y)
            q80 = float(np.quantile(np.abs(y - model.predict(X)), 0.8))
            self.fits[h] = (model, q80, int(len(rows)))
        return self

    def predict(self, values: pd.Series, cov: pd.DataFrame | None, origins: pd.DatetimeIndex, h: int):
        model, q80, _ = self.fits[h]
        ser = values.ffill()
        feat = ridge_features(ser, cov, ser.index.get_indexer(origins), H_STEPS[h], self.c)
        zhat = feat["current"].to_numpy() + model.predict(feat[RIDGE_FEATURES].fillna(0.0).to_numpy())
        back = lambda v: np.exp(v) - self.c  # noqa: E731
        return back(zhat), back(zhat - q80), back(zhat + q80)


def load_fm(name: str):
    from experiments.paper2_bounded_align import FM

    return FM(name, TORCH_THREADS)


# =============================================================================================
# per injection (forecast + score)
# =============================================================================================

def prepare_h(window: pd.DataFrame, kind: str, onset: pd.Timestamp, params: dict, resolution: float, sham: bool):
    """Observed stream, detectors and mechanism inputs for one injection (or sham) in ``window``."""
    obs = window if sham else inject_nh4(window, kind, onset, resolution)[0]
    det = detect_h(obs["NH4"], params)
    cps = change_points_h(det["step"])
    inp = F5Inputs(obs["NH4"], flags_h(det), cps, ref=obs[["temp", "sal"]])
    return obs, det, inp


def forecasts_h(model_name: str, model, inp: F5Inputs, cov: pd.DataFrame, origins: pd.DatetimeIndex, mechs) -> dict:
    """{(mech, h): [pred, lo, hi]}; one model call per distinct input series; (d) is derived later from (a)."""
    base = [m for m in mechs if m != "d"]
    keys = {m: [inp.key(m, t) for t in origins] for m in base}
    need: dict = {}
    for m in base:
        for j, k in enumerate(keys[m]):
            need.setdefault(k, set()).add(j)
    vals = {}
    for k, js in need.items():
        js = np.array(sorted(js))
        ser, o = inp.build(k), origins[js]
        arrs = {h: [np.full(len(origins), np.nan) for _ in range(3)] for h in H_STEPS}
        if model_name == "ridge":
            for h in H_STEPS:
                for arr, v in zip(arrs[h], model.predict(ser, cov, o, h)):
                    arr[js] = v
        else:
            q = model.quantiles(contexts_for(ser, o))
            for h, s in H_STEPS.items():
                for arr, col in zip(arrs[h], (1, 0, 2)):
                    arr[js] = q[:, s - 1, col]
        vals[k] = arrs
    out = {}
    for m in base:
        for h in H_STEPS:
            out[(m, h)] = [np.array([vals[k][h][i][j] for j, k in enumerate(keys[m])]) for i in range(3)]
    for (m, h), (p, lo, hi) in out.items():  # missing forecast -> (a)'s
        bad = ~np.isfinite(p)
        if m != "a" and bad.any() and ("a", h) in out:
            pa, la, ha = out[("a", h)]
            p[bad], lo[bad], hi[bad] = pa[bad], la[bad], ha[bad]
    return out


def score_h(model_name: str, fc: dict, truth: pd.Series, obs: pd.Series, onset: pd.Timestamp, mechs) -> list[dict]:
    origins = origin_times(onset)
    rows = []
    for h in H_STEPS:
        tgt = origins + pd.Timedelta(minutes=h)
        y_true = truth.reindex(tgt).to_numpy(dtype=float)
        y_obs = obs.reindex(tgt).to_numpy(dtype=float)
        for m in mechs:
            if m == "d":
                pa, la, ha = fc[("a", h)]
                bias = online_bias(origins, pa, y_obs, h)
                p, lo, hi = pa + bias, la + bias, ha + bias
            else:
                p, lo, hi = fc[(m, h)]
            alo, ahi = aci_intervals(origins, lo, hi, y_obs, h)
            err = np.abs(p - y_true)
            row = {"model": model_name, "mech": m, "horizon_min": h, "fallback_nan": int((~np.isfinite(p)).sum())}
            for wn in WINDOWS:
                msk = window_mask(origins, onset, wn)
                ok = msk & np.isfinite(err)
                row[f"mae_{wn}"] = float(err[ok].mean()) if ok.any() else np.nan
                row[f"n_{wn}"] = int(ok.sum())
                inside = np.isfinite(y_true) & msk
                row[f"cov_static_{wn}"] = float(((y_true >= lo) & (y_true <= hi))[inside].mean()) if inside.any() else np.nan
                row[f"cov_aci_{wn}"] = float(((y_true >= alo) & (y_true <= ahi))[inside].mean()) if inside.any() else np.nan
                row[f"width_aci_{wn}"] = float((ahi - alo)[inside].mean()) if inside.any() else np.nan
            row["recovery_h"] = recovery_hours(origins, err, onset, row["mae_baseline"])
            rows.append(row)
    return rows


def detection_row(det: dict, kind: str, onset: pd.Timestamp) -> dict:
    """First alarm on NH4 in [onset, onset + 7 d] (gap type: gap flag only); credited within CREDIT_H[kind]
    (24 h abrupt / 7 d drift; shams carry both so either credit window has a chance level)."""
    end7 = onset + pd.Timedelta(days=7)
    row, first = {}, None
    use = ("gap",) if kind == "gap" else ("range", "stuck", "step", "drift")
    for d in ("range", "stuck", "step", "drift", "gap"):
        hit = det[d].loc[onset:end7]
        t = hit.index[hit.to_numpy(dtype=bool)][0] if hit.any() else None
        row[f"det_{d}_24h"] = t is not None and t <= onset + pd.Timedelta(hours=24)
        if d in use and t is not None and (first is None or t < first):
            first = t
    row["detected_24h"] = first is not None and first <= onset + pd.Timedelta(hours=24)
    row["detected_7d"] = first is not None
    row["detected"] = row["detected_7d"] if CREDIT_H.get(kind, 24) > 24 else row["detected_24h"]
    row["delay_h"] = (first - onset) / pd.Timedelta(hours=1) if first is not None else np.nan
    return row


def detection_summary(res: pd.DataFrame) -> pd.DataFrame:
    """Per model x station x fault kind: detection rate in its credit window, paired random-sham rate, excess."""
    r = res[(res["mech"] == "a") & (res["horizon_min"] == 60)]
    rows = []
    for (model, st), g in r.groupby(["model", "station"], sort=False):
        sh = g[g["set"] == "sham_random"]
        for kind in FAULT_KINDS:
            k = g[g["set"] == kind]
            if not len(k):
                continue
            col = "detected_7d" if CREDIT_H[kind] > 24 else "detected_24h"
            rate, chance = float(k["detected"].mean()), float(sh[col].mean()) if len(sh) else np.nan
            rows.append({"model": model, "station": st, "kind": kind, "n": len(k), "detection": rate,
                         "sham_rate": chance, "excess_over_sham": rate - chance,
                         "delay_h_median": float(k["delay_h"].median()),
                         "stuck_hit_24h": float(k["det_stuck_24h"].mean())})
    return pd.DataFrame(rows)


def false_alarms(x: pd.Series, params: dict) -> dict:
    """Alarm episodes / 30 d per detector on an uninjected series."""
    det = detect_h(x, params)
    days = x.notna().sum() / 24.0
    return {f"fa_{d}_per30d": round(_rate(len(episodes(det[d], MERGE_H)), days), 3) for d in ("stuck", "step", "drift")} \
        | {"flagged_share": round(float((flags_h(det) & x.notna()).sum() / max(x.notna().sum(), 1)), 4),
           "days": round(float(days), 1)}


def run_injection(model_name: str, model, window: pd.DataFrame, truth: pd.Series, kind: str, onset: pd.Timestamp,
                  params: dict, resolution: float, sham: bool, cal_max: float, mechs=MECHS) -> list[dict]:
    obs, det, inp = prepare_h(window, kind, onset, params, resolution, sham)
    origins = origin_times(onset)
    cov = obs[["temp", "sal"]]
    fc = forecasts_h(model_name, model, inp, cov, origins, mechs)
    rows = score_h(model_name, fc, truth, obs["NH4"], onset, mechs)
    extra = detection_row(det, kind, onset) | inp.trigger_info(onset, origins[-1])
    if not sham:
        extra |= fault_diagnostics(truth, obs["NH4"], onset, cal_max)
    return [r | extra for r in rows]


# =============================================================================================
# summaries and the decision rule (pure)
# =============================================================================================

def boot_mean(lr: np.ndarray, n: int = N_BOOT, seed: int = SEED, groups: np.ndarray | None = None) -> np.ndarray:
    rng = np.random.default_rng(seed)
    lr = np.asarray(lr, dtype=float)
    if groups is None:
        return lr[rng.integers(0, len(lr), (n, len(lr)))].mean(axis=1)
    ug = pd.unique(groups)
    idx = [np.flatnonzero(groups == g) for g in ug]
    out = np.empty(n)
    for b in range(n):
        pick = rng.integers(0, len(ug), len(ug))
        out[b] = np.mean(np.concatenate([lr[idx[i]] for i in pick]))
    return out


def reduction_stats(mae_m: np.ndarray, mae_a: np.ndarray, groups: np.ndarray | None = None) -> dict:
    """1 - geomean(mae_m / mae_a), bootstrap 95 % CI, two-sided bootstrap p of mean log ratio = 0."""
    mae_m, mae_a = np.asarray(mae_m, dtype=float), np.asarray(mae_a, dtype=float)
    ok = np.isfinite(mae_m) & np.isfinite(mae_a) & (mae_m > 0) & (mae_a > 0)
    lr = np.log(mae_m[ok] / mae_a[ok])
    r = {"n": int(ok.sum()), "n_dropped": int((~ok).sum())}
    if not len(lr):
        return r | {"reduction": np.nan, "ci_lo": np.nan, "ci_hi": np.nan, "p": np.nan}
    bs = boot_mean(lr)
    p = min(1.0, 2 * min((np.sum(bs >= 0) + 1) / (len(bs) + 1), (np.sum(bs <= 0) + 1) / (len(bs) + 1)))
    lo, hi = np.percentile(bs, [2.5, 97.5])
    r |= {"reduction": 1 - float(np.exp(lr.mean())), "ci_lo": 1 - float(np.exp(hi)), "ci_hi": 1 - float(np.exp(lo)),
          "p": float(p)}
    if groups is not None:
        bg = boot_mean(lr, groups=np.asarray(groups)[ok])
        glo, ghi = np.percentile(bg, [2.5, 97.5])
        r |= {"month_ci_lo": 1 - float(np.exp(ghi)), "month_ci_hi": 1 - float(np.exp(glo))}
    return r


def holm(pvals: dict) -> dict:
    """Holm step-down adjusted p-values (monotone, capped at 1); NaN p -> NaN."""
    items = sorted(((p, k) for k, p in pvals.items() if np.isfinite(p)))
    m, out, run = len(items), {k: np.nan for k in pvals}, 0.0
    for i, (p, k) in enumerate(items):
        run = max(run, min(1.0, (m - i) * p))
        out[k] = run
    return out


def summarise(res: pd.DataFrame, horizon: int = 60, window: str = "post24") -> pd.DataFrame:
    """Per model x station x set x mechanism: reduction vs (a) at ``horizon`` / ``window``.  ``set`` = fault kind,
    'sham_random' or 'sham_event'."""
    key = ["model", "station", "set", "onset"]
    r = res[res["horizon_min"] == horizon]
    a = r[r["mech"] == "a"][key + [f"mae_{window}"]].rename(columns={f"mae_{window}": "mae_a"})
    m = r[r["mech"] != "a"].merge(a, on=key, how="inner")
    rows = []
    for (model, st, s, mech), g in m.groupby(["model", "station", "set", "mech"], sort=False):
        months = pd.to_datetime(g["onset"]).dt.strftime("%Y-%m").to_numpy()
        rows.append({"model": model, "station": st, "set": s, "mech": mech, "horizon_min": horizon, "window": window}
                    | reduction_stats(g[f"mae_{window}"].to_numpy(), g["mae_a"].to_numpy(), months))
    return pd.DataFrame(rows)


def verdict(summ: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Confirmatory rule on a 1-h post24 summary.  Returns (per test, per model x mechanism x station + overall)."""
    tests, stations = [], []
    for (model, st), g in summ.groupby(["model", "station"], sort=False):
        fam = g[g["set"].isin(RULE_KINDS) & g["mech"].isin(TESTED)]
        adj = holm({(r.mech, r.set): (r.p if r.n >= MIN_N else np.nan) for r in fam.itertuples()})
        for r in fam.itertuples():
            pa = adj[(r.mech, r.set)]
            ok = bool(r.n >= MIN_N and np.isfinite(pa) and pa < ALPHA and r.reduction >= GAIN_MIN)
            tests.append({"model": model, "station": st, "mech": r.mech, "set": r.set, "n": r.n,
                          "reduction": r.reduction, "ci_lo": r.ci_lo, "ci_hi": r.ci_hi, "p": r.p, "p_holm": pa,
                          "evaluable": bool(r.n >= MIN_N), "pass": ok})
    t = pd.DataFrame(tests)
    for (model, st), g in summ.groupby(["model", "station"], sort=False):
        for mech in TESTED:
            tm = t[(t["model"] == model) & (t["station"] == st) & (t["mech"] == mech)] if len(t) else t
            n_pass = int(tm["pass"].sum()) if len(tm) else 0
            harm = {}
            for s in ("sham_random", "sham_event"):
                row = g[(g["set"] == s) & (g["mech"] == mech)]
                harm[s] = (float(-row["reduction"].iloc[0]), int(row["n"].iloc[0])) if len(row) else (np.nan, 0)
            used = [s for s in ("sham_random", "sham_event") if harm[s][1] >= MIN_N]
            harm_ok = bool("sham_random" in used and all(harm[s][0] <= HARM_MAX for s in used))
            stations.append({"model": model, "station": st, "mech": mech, "types_passing": n_pass,
                             "passing": ", ".join(tm.loc[tm["pass"], "set"]) if len(tm) else "",
                             "harm_random": harm["sham_random"][0], "n_random": harm["sham_random"][1],
                             "harm_event": harm["sham_event"][0], "n_event": harm["sham_event"][1],
                             "event_used": "sham_event" in used, "harm_ok": harm_ok,
                             "useful_station": bool(n_pass >= TYPES_NEEDED and harm_ok)})
    s = pd.DataFrame(stations)
    if len(s):
        over = s.groupby(["model", "mech"], sort=False)["useful_station"].agg(["sum", "count"]).reset_index()
        over["useful"] = over["sum"] >= STATIONS_NEEDED
        s = s.merge(over.rename(columns={"sum": "stations_useful", "count": "stations"}), on=["model", "mech"])
    return t, s


# =============================================================================================
# stages
# =============================================================================================

def _write_new(path: Path, obj) -> None:
    if path.exists():
        raise FileExistsError(f"refusing_to_overwrite:{path}")
    if isinstance(obj, pd.DataFrame):
        obj.to_csv(path, index=False)
    else:
        path.write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def station_setup(pk: str, sens: dict | None = None) -> dict:
    """Load + filter + split one station (no thresholds, no forecasts)."""
    sens = sens or {}
    fr = load_station(pk)
    cf = clean_filter(fr["NH4"], stuck_h=sens.get("stuck_h", STUCK_H), marker_w=sens.get("marker_w", MARKER_W_H),
                      zero_invalid=sens.get("zero_invalid", ZERO_INVALID))
    t_split = time_split(cf["valid"])
    base = fr.assign(NH4=cf["base"])
    cal = base[base.index < t_split]
    return {"pk": pk, "name": STATIONS[pk][0], "resolution": STATIONS[pk][1], "frame": base, "filter": cf,
            "t_split": t_split, "cal": cal, "cal_max": float(cal["NH4"].max()),
            "period_cal": (base.index[0], t_split), "period_score": (t_split, base.index[-1] + pd.Timedelta(hours=1))}


def stage_calibrate(out: Path, args) -> None:
    """Filter, split, detector thresholds on the calibration period, random onsets for both periods."""
    out.mkdir(parents=True, exist_ok=False)
    summary, thresholds, onsets = [], {}, []
    for pk in STATIONS:
        s = station_setup(pk)
        cf, idx = s["filter"], s["frame"].index
        params = calibrate_h([s["cal"]["NH4"]])
        thresholds[pk] = {k: v for k, v in params.items() if not k.endswith("_curve")}
        thresholds[pk]["curves"] = {k: v for k, v in params.items() if k.endswith("_curve")}
        row = {"station": pk, "name": s["name"], "resolution": s["resolution"], "first": str(idx[0]),
               "last": str(idx[-1]), "t_split": str(s["t_split"]), "cal_max": s["cal_max"]} | cf["shares"]
        row["markers_cal"] = int((cf["markers"] < s["t_split"]).sum())
        for per in ("cal", "score"):
            cand = eligible_onsets(cf["valid"], cf["dirty"], s[f"period_{per}"])
            chosen = place_h(cand, N_MAX, _rng(pk, per, "random"))
            row[f"eligible_hours_{per}"] = int(len(cand))
            row[f"onsets_{per}"] = len(chosen)
            onsets += [{"station": pk, "period": per, "onset": str(t)} for t in chosen]
        # calibration-period descriptive checks (no forecasts): scale_up above cal max, scale_down low-distinct
        cal_on = [pd.Timestamp(o["onset"]) for o in onsets if o["station"] == pk and o["period"] == "cal"]
        up, low, stuck_hit = [], [], []
        for t in cal_on:
            win = s["frame"][t - WIN_BEFORE:t + WIN_AFTER]
            for kind in ("scale_up", "scale_down"):
                f, _ = inject_nh4(win, kind, t, s["resolution"])
                d = fault_diagnostics(win["NH4"], f["NH4"], t, s["cal_max"])
                if kind == "scale_up":
                    up.append(d["exceeds_cal_max"])
                else:
                    low.append(d["low_distinct_post24"])
                    det = detect_h(f["NH4"], thresholds[pk])
                    stuck_hit.append(bool(det["stuck"].loc[t:t + pd.Timedelta(hours=24)].any()))
        row["cal_scale_up_exceeds_cal_max_share"] = float(np.mean(up)) if up else np.nan
        row["cal_scale_down_low_distinct_share"] = float(np.mean(low)) if low else np.nan
        row["cal_scale_down_stuck_hit_share"] = float(np.mean(stuck_hit)) if stuck_hit else np.nan
        # calibration-period false alarms with the chosen thresholds (in-sample by construction)
        det = detect_h(s["cal"]["NH4"], thresholds[pk])
        days = s["cal"]["NH4"].notna().sum() / 24
        for d in ("stuck", "step", "drift"):
            row[f"cal_fa_{d}_per30d"] = round(_rate(len(episodes(det[d], MERGE_H)), days), 3)
        summary.append(row)
        print(json.dumps({k: row[k] for k in ("name", "t_split", "onsets_cal", "onsets_score", "dirty_share")}), flush=True)
    _write_new(out / "filter_summary.csv", pd.DataFrame(summary))
    _write_new(out / "thresholds.json", {"git_head": git_head(), "script": SCRIPT, "stations": thresholds})
    _write_new(out / "onsets_random.csv", pd.DataFrame(onsets))


def _station_params(out: Path) -> dict:
    return json.loads((out / "thresholds.json").read_text(encoding="utf-8"))["stations"]


def stage_timing(out: Path, args) -> None:
    """Runtime of ridge and Chronos-2 on 3 CALIBRATION onsets (scale_down + sham) of one station."""
    pk = args.station
    s = station_setup(pk)
    params = _station_params(out)[pk]
    on = pd.read_csv(out / "onsets_random.csv")
    on = [pd.Timestamp(t) for t in on[(on["station"].astype(str) == pk) & (on["period"] == "cal")]["onset"]][:3]
    res = {"station": pk, "onsets": [str(t) for t in on], "git_head": git_head()}
    t0 = time.perf_counter()
    ridge = RidgeH().fit(s["cal"]["NH4"], s["cal"][["temp", "sal"]])
    res["ridge_fit_s"] = round(time.perf_counter() - t0, 2)
    models = [("ridge", ridge)]
    if not args.skip_fm:
        t0 = time.perf_counter()
        models.append(("chronos2", load_fm("chronos2")))
        res["chronos2_load_s"] = round(time.perf_counter() - t0, 2)
    for name, model in models:
        times, n_ctx = [], []
        for t in on:
            win = s["frame"][t - WIN_BEFORE:t + WIN_AFTER]
            for kind, sham in (("scale_down", False), ("scale_down", True)):
                t1 = time.perf_counter()
                run_injection(name, model, win, win["NH4"], kind, t, params, s["resolution"], sham, s["cal_max"])
                times.append(time.perf_counter() - t1)
        res[f"{name}_s_per_injection"] = round(float(np.mean(times)), 3)
        res[f"{name}_s_per_injection_max"] = round(float(np.max(times)), 3)
    _write_new(out / f"timing_{pk}.json", res)
    print(json.dumps(res))


def preregistration(out: Path) -> dict:
    fs = pd.read_csv(out / "filter_summary.csv")
    timing = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("timing_*.json"))}
    planned = int((fs["onsets_score"] * (len(FAULT_KINDS) + 1)).sum())
    planned_max = planned + N_EVENT_MAX * len(fs)
    estimate = {}
    for tm in timing.values():
        for m in ("ridge", "chronos2"):
            if f"{m}_s_per_injection" in tm:
                estimate[m] = {"s_per_injection_mean": tm[f"{m}_s_per_injection"],
                               "hours_at_max_injections": round(planned_max * tm[f"{m}_s_per_injection"] / 3600, 2),
                               "hours_at_max_s_per_injection": round(planned_max * tm[f"{m}_s_per_injection_max"] / 3600, 2)}
    return {
        "run": RUN_NAME, "script": SCRIPT, "git_head": git_head(), "created": pd.Timestamp.now(tz="UTC").isoformat(),
        "status": "registered before any forecast / mechanism on the scoring period",
        "stations": {pk: {"name": v[0], "resolution": v[1]} for pk, v in STATIONS.items()},
        "inputs": {"kr_raw_manifest_sha256": _sha(KR_RAW / "manifest.json"),
                   "step0_verdict_sha256": _sha(STEP0_RUN / "verdict.json")},
        "calibration_outputs_sha256": {p.name: _sha(p) for p in sorted(out.iterdir())
                                       if p.is_file() and p.name != "preregistration.json"},
        "clean_filter": {"nan_negative": "missing", "zero": "missing" if ZERO_INVALID else "valid",
                         "stuck_h": STUCK_H, "shift_marker_window_h": MARKER_W_H, "marker_pad_h": MARKER_PAD_H,
                         "marker_rule": "hourly |log ratio| >= log 3 and 72-h medians after/before differ >= x3",
                         "placement_valid_span_d": [-8, 7], "min_valid": MIN_VALID, "dirty_free_span_d": [-2, 7]},
        "split": {"rule": "T_split = hour where cumulative valid hours reach 50 %; cal < T_split; every scoring window "
                          "[onset-40 d, onset+8 d] >= T_split", "per_station": dict(zip(fs["station"].astype(str), fs["t_split"]))},
        "placements": {"n_max": N_MAX, "min_separation_d": 8, "paired_types_and_random_sham": True,
                       "event_shams": {"n_max": N_EVENT_MAX, "rule": "step-alarm episode starts on uninjected scoring "
                                       "NH4, valid >= 80 % [-8 d, +7 d], no stuck/zero in [-2 d, +7 d], >= 8 d apart, "
                                       "seeded; built in the score stage"},
                       "onsets_score_per_station": dict(zip(fs["station"].astype(str), fs["onsets_score"].astype(int)))},
        "faults": {"scale_down": {"factor": E1_FACTOR, "source": "F1 E1 1-min history ratio 20.013"},
                   "scale_up": {"factor": E3_FACTOR, "source": "F1 E3 30-s anatomy ratio (task x6.7); F1 1-min 8.1 not used"},
                   "drift_down": {"factor": DRIFT_FACTOR, "days": DRIFT_DAYS, "shape": "log-linear then held",
                                  "source": "F1 TSS fouling gain/duration, borrowed (NB1 has no NH4 drift)"},
                   "stuck": {"value": "last valid value before onset", "persistent": True},
                   "gap": {"minutes": GAP_MIN, "channels": "all", "role": "descriptive"},
                   "requantise": "scale/drift to station resolution", "hard_range_in_b": "off (x < 0 only)",
                   "diagnostics": ["scale_up exceeding cal max", "scale_down <= 2 distinct values post24",
                                   "stuck-detector hits on re-scales"]},
        "detectors": {"z": f"log(NH4 + {NH4_C})", "W_h": W_H, "theta_grid": "F2 THETA_GRID", "stuck_k_grid": STUCK_K_GRID_H,
                      "fa_target_per_30d": FA_TARGET_PER_30D, "merge_h": MERGE_H, "gap_min_h": GAP_MIN_H,
                      "thresholds": _station_params(out)},
        "models": {"primary": "RidgeH (hourly B4D-style, z space, temp/sal covariates, alpha 1, no doy)",
                   "secondary": f"{CHRONOS2_NAME} zero-shot univariate, context 672 h, 2 threads (.venv-fm)",
                   "timing": timing, "planned_injections": {"random_and_paired": planned, "max_with_event_shams": planned_max},
                   "runtime_estimate": estimate,
                   "fm_budget_rule": f"Chronos-2 is run iff its hours_at_max_s_per_injection <= {FM_BUDGET_H} h "
                                     "(decided here from the calibration timing, not after scoring)",
                   "fm_will_run": bool(estimate.get("chronos2", {}).get("hours_at_max_s_per_injection", np.inf) <= FM_BUDGET_H)},
        "mechanisms": {"a": "ignore", "b": "QC mask (range x<0 | stuck | gap | drift)", "c_align": "F3 (c') unbounded",
                       "v2": "F4 bounded (i)+(ii)+(iii), a priori F4 thresholds", "v3": "v2 + 72 h decay",
                       "d": "online residual-bias PROXY (not FSNet/TAFAS)", "e": "ACI on each mechanism's PI80"},
        "rule": {"confirmatory": "ridge, h = 1 h, post24, per station", "gain_min": GAIN_MIN, "alpha_holm": ALPHA,
                 "p_value": "two-sided bootstrap of mean log ratio by injection, 4000 draws",
                 "holm_family": "model x station: 5 mechanisms x 4 rule types = 20", "min_n": MIN_N,
                 "rule_types": RULE_KINDS, "types_needed": TYPES_NEEDED, "harm_max": HARM_MAX,
                 "harm_sets": ["sham_random", "sham_event (if n >= min_n)"], "stations_needed": STATIONS_NEEDED,
                 "secondary_confirmatory": "same rule for chronos2"},
        "descriptive": ["gap", "h = 6 h", "post7", "recovery", "PI80 static/ACI vs [0.75, 0.85]", "detection / FA",
                        "trigger rates", "month-cluster CIs", "pooled numbers", "NB1 illustration"],
        "sensitivity": SENSITIVITY,
        "disclosed_prior_looks": ["step 0 (RL-84): whole-series coverage, segments, quantiles, stuck/jump/shift counts",
                                  "this design: valid-hour counts, cal/score quantiles, marker counts and candidate-onset "
                                  "yields for marker windows 24/72/168 h on the full series; no detector run, forecast "
                                  "or mechanism on scoring hours"],
        "deviation_policy": "any later change is listed in NOTES.md 'sai lệch' with reason; no re-run to improve results",
    }


def stage_prereg(out: Path, _args) -> None:
    _write_new(out / "preregistration.json", preregistration(out))
    print(out / "preregistration.json")


def _require_prereg(out: Path) -> dict:
    p = out / "preregistration.json"
    if not p.exists():
        raise FileNotFoundError("preregister_first")
    return json.loads(p.read_text(encoding="utf-8"))


def event_onsets(s: dict, params: dict) -> list[pd.Timestamp]:
    """Event-sham onsets on the scoring period (rule in the docstring)."""
    cf = s["filter"]
    x = s["frame"]["NH4"][s["period_score"][0]:]
    starts = episodes(detect_h(x, params)["step"], MERGE_H)
    ok = eligible_onsets(cf["valid"], cf["hard"], s["period_score"])
    cand = pd.DatetimeIndex([t for t in starts if t in set(ok)])
    return place_h(cand, N_EVENT_MAX, _rng(s["pk"], "event"))


def stage_score(out: Path, args) -> None:
    prereg = _require_prereg(out)
    sens = SENSITIVITY[args.sensitivity] if args.sensitivity else None
    if sens and args.model != "ridge":
        raise ValueError("sensitivity runs are ridge-only")
    tag = args.model + (f"_{args.sensitivity}" if args.sensitivity else "")
    params_all = prereg["detectors"]["thresholds"]
    model = load_fm(args.model) if args.model != "ridge" else None
    rows, ev_rows, fa_rows = [], [], []
    for pk in STATIONS:
        s = station_setup(pk, sens)
        params = params_all[pk] if not sens else calibrate_h([s["cal"]["NH4"]])
        if args.model == "ridge":
            model = RidgeH().fit(s["cal"]["NH4"], s["cal"][["temp", "sal"]])
        if sens:
            cand = eligible_onsets(s["filter"]["valid"], s["filter"]["dirty"], s["period_score"])
            random_on = place_h(cand, N_MAX, _rng(pk, "score", "random"))
        else:
            on = pd.read_csv(out / "onsets_random.csv")
            random_on = [pd.Timestamp(t) for t in on[(on["station"].astype(str) == pk) & (on["period"] == "score")]["onset"]]
        events = event_onsets(s, params)
        ev_rows += [{"station": pk, "onset": str(t)} for t in events]
        fa_rows.append({"station": pk} | false_alarms(s["frame"]["NH4"][s["period_score"][0]:], params))
        jobs = [(t, k, False) for t in random_on for k in FAULT_KINDS] + [(t, "sham_random", True) for t in random_on]
        jobs += [(t, "sham_event", True) for t in events]
        for i, (t, kind, sham) in enumerate(jobs[:args.max] if args.max else jobs):
            if t - WIN_BEFORE < s["period_score"][0]:
                raise RuntimeError(f"leak: scoring window starts before T_split at {t}")
            win = s["frame"][t - WIN_BEFORE:t + WIN_AFTER]
            for r in run_injection(args.model, model, win, win["NH4"], kind, t, params, s["resolution"], sham,
                                   s["cal_max"]):
                rows.append({"station": pk, "set": kind, "onset": t, "sham": sham} | r)
            if i % 25 == 0:
                print(f"{s['name']} {i}/{len(jobs)}", flush=True)
    _write_new(out / f"results_{tag}.csv", pd.DataFrame(rows))
    _write_new(out / f"onsets_event_{tag}.csv", pd.DataFrame(ev_rows))
    _write_new(out / f"fa_score_{tag}.csv", pd.DataFrame(fa_rows))


def stage_evaluate(out: Path, _args) -> None:
    _require_prereg(out)
    groups: dict = {}
    for p in sorted(out.glob("results_*.csv")):
        parts = p.stem.split("_", 2)  # results_<model>[_<sensitivity>]
        groups.setdefault(parts[2] if len(parts) == 3 else "", []).append(p)
    for sens, files in groups.items():
        res = pd.concat([pd.read_csv(p) for p in files], ignore_index=True)
        res["station"] = res["station"].astype(str)
        sfx = f"_{sens}" if sens else ""
        summ = pd.concat([summarise(res, h, w) for h in H_STEPS for w in ("post24", "post7")], ignore_index=True)
        tests, st = verdict(summ[(summ["horizon_min"] == 60) & (summ["window"] == "post24")])
        _write_new(out / f"summary{sfx}.csv", summ)
        _write_new(out / f"verdict_tests{sfx}.csv", tests)
        _write_new(out / f"verdict{sfx}.csv", st)
        _write_new(out / f"detection{sfx}.csv", detection_summary(res))


def nb1_hourly() -> pd.Series:
    from experiments.paper2_faults import load_history

    return load_history()["NH4"].resample("1h").median()


def stage_nb1(out: Path, _args) -> None:
    """Illustration (no truth): Chronos-2 around NB1 E1 / E3 per mechanism."""
    _require_prereg(out)
    x = nb1_hourly()
    params = calibrate_h([x["2026-06-01":"2026-07-30 23:00"]])
    fm = load_fm("chronos2")
    rows = []
    for name, t in (("E1_NH4", "2026-07-31 14:00"), ("E3_NH4", "2026-09-16 15:00")):
        t = pd.Timestamp(t)
        win = pd.DataFrame({"NH4": x[t - WIN_BEFORE:t + WIN_AFTER]})
        win["temp"], win["sal"] = np.nan, np.nan
        det = detect_h(win["NH4"], params)
        inp = F5Inputs(win["NH4"], flags_h(det), change_points_h(det["step"]), ref=None)
        origins = origin_times(t)
        fc = forecasts_h("chronos2", fm, inp, win[["temp", "sal"]], origins, MECHS)
        post = (origins >= t) & (origins < t + pd.Timedelta(hours=24))
        pre = float(win["NH4"][t - pd.Timedelta(hours=24):t - pd.Timedelta(hours=1)].median())
        obs_post = float(win["NH4"][t:t + pd.Timedelta(hours=23)].median())
        for m in MECHS:
            if m == "d":
                continue
            rows.append({"event": name, "mech": m, "mean_fc_post24": float(np.nanmean(fc[(m, 60)][0][post])),
                         "obs_pre24_median": pre, "obs_post24_median": obs_post, "n_cp": len(inp.cps)})
    _write_new(out / "nb1_illustration.csv", pd.DataFrame(rows))
    _write_new(out / "nb1_thresholds.json", {k: v for k, v in params.items() if not k.endswith("_curve")})


STAGES = {"calibrate": stage_calibrate, "timing": stage_timing, "prereg": stage_prereg, "score": stage_score,
          "evaluate": stage_evaluate, "nb1": stage_nb1}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=tuple(STAGES))
    ap.add_argument("--output", type=Path, default=None)
    ap.add_argument("--station", default="15159657")
    ap.add_argument("--model", default="ridge", choices=("ridge", "chronos2"))
    ap.add_argument("--sensitivity", default=None, choices=tuple(SENSITIVITY))
    ap.add_argument("--skip-fm", action="store_true")
    ap.add_argument("--max", type=int, default=None)
    args = ap.parse_args(argv)
    out = args.output or paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME
    STAGES[args.stage](out, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
