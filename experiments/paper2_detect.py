"""Paper 2 / F2: causal regime-change detectors + QC mask, scored on injected faults in NERRS (research-only).

PRE-REGISTRATION (fixed 2026-10-28 before any scoring run; changes after a dry run go to NOTES.md "debug"):

Data.  NERRS SWMP 2007-2011, 8 reserves / 33 stations (``nerrs_multi.RESERVES``), 15-min WQ, CDMO flag ``<0>``
only (``nerrs_load.read_wq_file``), variables DO_mgl, Turb, pH, Temp.  **Calibration** = 2007-2008 (clean,
nothing injected), **test** = 2009-2011.  NB1 (``sensor-history-20261024``, 15-min medians) is the real
illustration, scored with the NERRS thresholds (no NB1 tuning).

Detectors (all causal: the value at t uses data <= t only; scale-free; z = log(x + c) for positive variables,
z = x for pH / Temp; ``VAR_CFG``):
  * ``range``  x outside ``RANGE[var]``, or Turb >= 1000 NTU (probe rail, NERRS metadata).
  * ``stuck``  >= k identical consecutive readings; k per variable, smallest of ``STUCK_K_GRID`` meeting the FA
               target (no k meets it -> detector off for that variable).
  * ``step``   |median z(last w) - median z(the w before)| / sigma, w = 4 samples (1 h); sigma = 1.4826 x median
               |dz| over the trailing 7 days, ending before both windows, floored at ``SIGMA_FLOOR[var]``.
               Changepoint estimate = t - w + 1.  Causal re-statement of RL-72's ``detect_level_step``.
  * ``drift``  |median z(last 24 h) - median z(t-8 d .. t-1 d)| / tau, tau = 1.4826 x median |24 h-median change
               over 1 day| over 30 days ending 8 days before t, floored at ``SIGMA_FLOOR[var]``.
  * ``cross``  RL-72 signature: step score >= ``CROSS_FRACTION`` x threshold in >= 2 of DO_mgl / Turb / pH within
               the last 3 samples.
  * ``gap``    >= 8 missing samples (2 h): data-availability flag only (not an alarm, not FA-calibrated).
Thresholds for step / drift: smallest value on ``THETA_GRID`` with pooled alarm episodes <= ``FA_TARGET_PER_30D``
per variable on the calibration years (episodes = alarm runs merged when < 6 h apart).  No noise-level detector
(F1: the injector multiplies NH4 noise, real E3 noise is additive - a noise feature would score an artefact).

Outputs for F3: ``flags`` (per-sample suspect mask = range | stuck | gap | drift) and ``changepoints``
(step / cross alarms).

Injected faults (test years; F1 library ``paper2_faults``, parameters from ``paper2-f1-20261028``):
  scale_down DO /20.013, scale_up DO x8.1, gap all 146 min, stuck0 Turb = 0.0, ph_ramp pH -1.01 in 6.25 h,
  fouling Turb x12.52 in 6.25 d, rail Turb log-ramp from the trailing-24 h median to 1000 NTU x1.36 reaching the rail
  after 3.75 d, E1 (DO /20.013 + Turb fouled from -14 d (x12.52 in 6.25 d) cleared at +1.5 min, residual 4.53, settle
  3.92 min), E3 (DO x8.1 + Turb stuck 0 for the 24 h before onset + pH +0.22 at -2.5 min).
  ``N_PER_STATION_YEAR`` onsets per station-year x type, ``place_onsets`` with a seed from (station, year, type),
  >= 80 % valid target data in [onset - 8 d, onset + 7 d].

Metrics: detection = any alarm (range / stuck / step / drift / cross; gap only for the gap type) in the credit window
[onset + ``CREDIT_START_H``, onset + H], H = 24 h (abrupt) or 7 d (fouling, rail); delay = first alarm - onset;
per-detector rates; mask recall = faulted samples in [onset, onset + 7 d] covered by ``flags``; coverage with
changepoints = flags OR after the first changepoint in the credit window; clean FA episodes / 30 d (test years,
uninjected) and clean fraction flagged; 95 % CI of detection rate by station-cluster bootstrap (2000 draws).

DEVIATIONS after dry run 1 (before any full run; NOTES "debug"): (1) alarms are credited only on the faulted
columns, and every injection is paired with a **sham** (same window and columns, nothing injected) whose detection
rate is the chance level; the summary reports ``excess_over_sham`` (with ~2-3 natural alarm episodes / 30 d per
variable, "any alarm on any column within 7 d" is hit by chance most of the time).  (2) NB1 only: the known COD rail
558.8 joins the range rule for COD, and the NB1 event table counts alarm episodes that START in the window (COD was
already stuck before E2 / E3).

    python experiments/paper2_detect.py [--run-name paper2-f2-20261028] [--output DIR] [--max-stations N]
"""
from __future__ import annotations

import argparse
import json
import time
import zlib
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from experiments.nh4_step_0731 import sha256  # noqa: E402
from experiments.paper2_faults import (  # noqa: E402
    COD_RAIL, NB1_TO_NERRS, TURB_RAIL_NTU, FaultSpec, git_head, inject_event, place_onsets)

STEP_MIN = 15
DAY = 96
W = 4
VAR_CFG = {"DO_mgl": {"log": True, "c": 0.1}, "Turb": {"log": True, "c": 1.0},
           "pH": {"log": False, "c": 0.0}, "Temp": {"log": False, "c": 0.0}}
RANGE = {"DO_mgl": (0.0, 25.0), "Turb": (0.0, TURB_RAIL_NTU), "pH": (5.0, 10.0), "Temp": (-2.0, 40.0)}
RAIL = {"Turb": TURB_RAIL_NTU}
SIGMA_FLOOR = {"DO_mgl": 0.01, "Turb": 0.02, "pH": 0.02, "Temp": 0.02}
STUCK_K_GRID = (4, 8, 12, 16, 24, 32, 48, 64, 96, 192)
THETA_GRID = tuple(np.round(np.geomspace(2.0, 400.0, 80), 3))
FA_TARGET_PER_30D = 1.0
EPISODE_MERGE = 24          # samples (6 h)
GAP_MIN_SAMPLES = 8
CROSS_FRACTION = 0.5
CROSS_VARS = ("DO_mgl", "Turb", "pH")
CAL_YEARS, TEST_YEARS = (2007, 2008), (2009, 2010, 2011)
N_PER_STATION_YEAR = 2
MIN_VALID = 0.8
SEED = 20261028
ALARM_DETECTORS = ("range", "stuck", "step", "drift", "cross")
F1_RUN = paths.EXPERIMENT_OUTPUT_DIR / "paper2-f1-20261028"


# ---------------------------------------------------------------------------------------------
# detectors (pure, causal)
# ---------------------------------------------------------------------------------------------

def transform(x: pd.Series, var: str, c: float | None = None) -> pd.Series:
    """log(x + c) for positive variables (``c`` defaults to the variable's offset), x otherwise."""
    cfg = VAR_CFG[var]
    c = cfg["c"] if c is None else c
    return np.log(x.clip(lower=0) + c) if cfg["log"] else x.astype(float)


def step_score(x: pd.Series, var: str, w: int = W, c: float | None = None) -> pd.Series:
    z = transform(x, var, c)
    a = z.rolling(w, min_periods=w - 1).median()
    b = a.shift(w)
    sig = 1.4826 * z.diff().abs().rolling(7 * DAY, min_periods=DAY).median().shift(2 * w)
    return (a - b).abs() / sig.clip(lower=SIGMA_FLOOR[var])


def drift_score(x: pd.Series, var: str, c: float | None = None) -> pd.Series:
    z = transform(x, var, c)
    m24 = z.rolling(DAY, min_periods=DAY // 2).median()
    base = z.rolling(7 * DAY, min_periods=7 * DAY // 2).median().shift(DAY)
    dd = (m24 - m24.shift(DAY)).abs()
    tau = 1.4826 * dd.rolling(30 * DAY, min_periods=7 * DAY).median().shift(8 * DAY)
    return (m24 - base).abs() / tau.clip(lower=SIGMA_FLOOR[var])


def stuck_run(x: pd.Series) -> pd.Series:
    """Length of the current run of identical consecutive non-NaN readings (0 at NaN)."""
    new = (x != x.shift()) | x.isna()
    run = x.groupby(new.cumsum()).cumcount() + 1
    return run.where(x.notna(), 0).astype(int)


def range_flag(x: pd.Series, var: str, rail: float | None = None) -> pd.Series:
    lo, hi = RANGE[var]
    bad = (x < lo) | (x > hi)
    rail = RAIL.get(var) if rail is None else rail
    if rail is not None:
        bad |= x >= rail
    return bad.fillna(False).astype(bool)


def gap_flag(x: pd.Series, min_samples: int = GAP_MIN_SAMPLES) -> pd.Series:
    """True on missing samples belonging to a run of >= ``min_samples`` NaNs (causal: from the min_samples-th on)."""
    na = x.isna()
    run = na.groupby((~na).cumsum()).cumsum()
    return (run >= min_samples) & na


def episodes(alarm: pd.Series, merge: int = EPISODE_MERGE) -> list[pd.Timestamp]:
    """Start times of alarm episodes (alarm runs merged when separated by < ``merge`` samples)."""
    a = alarm.fillna(False).to_numpy(dtype=bool)
    starts, last = [], -10 ** 9
    for i in np.flatnonzero(a):
        if i - last > merge:
            starts.append(alarm.index[i])
        last = i
    return starts


def detect(frame: pd.DataFrame, params: dict, var_map: dict | None = None,
           offsets: dict | None = None, rails: dict | None = None) -> dict[str, pd.DataFrame]:
    """Run every detector on every column of ``frame`` (regular 15-min grid).

    ``params[var]`` = {"theta_step", "theta_drift", "stuck_k"} keyed by the NERRS variable; ``var_map`` maps
    a column to the NERRS variable whose config / thresholds it uses, ``offsets`` overrides log offsets per
    column (NB1).  Returns detector -> boolean frame.
    """
    var_map = var_map or {c: c for c in frame.columns}
    offsets = offsets or {}
    rails = rails or {}
    out = {k: pd.DataFrame(False, index=frame.index, columns=frame.columns) for k in ALARM_DETECTORS + ("gap",)}
    scores = {}
    for col in frame.columns:
        var = var_map[col]
        p = params[var]
        x = frame[col]
        out["range"][col] = range_flag(x, var, rails.get(col))
        out["gap"][col] = gap_flag(x)
        if p.get("stuck_k"):
            out["stuck"][col] = (stuck_run(x) >= p["stuck_k"]).to_numpy()
        s = step_score(x, var, c=offsets.get(col))
        scores[col] = s
        out["step"][col] = (s > p["theta_step"]).fillna(False).to_numpy()
        out["drift"][col] = (drift_score(x, var, c=offsets.get(col)) > p["theta_drift"]).fillna(False).to_numpy()
    cross_cols = [c for c in frame.columns if var_map[c] in CROSS_VARS]
    if len(cross_cols) >= 2:
        hit = pd.DataFrame({c: (scores[c] >= CROSS_FRACTION * params[var_map[c]]["theta_step"]).fillna(False)
                            .rolling(3, min_periods=1).max().astype(bool) for c in cross_cols})
        both = hit.sum(axis=1) >= 2
        for c in cross_cols:
            out["cross"][c] = (both & hit[c]).to_numpy()
    return out


def flags_of(det: dict) -> pd.DataFrame:
    return det["range"] | det["stuck"] | det["gap"] | det["drift"]


def changepoints_of(det: dict) -> pd.DataFrame:
    return det["step"] | det["cross"]


# ---------------------------------------------------------------------------------------------
# calibration
# ---------------------------------------------------------------------------------------------

def _rate(n_episodes: int, n_days: float) -> float:
    return 30.0 * n_episodes / n_days if n_days else np.inf


def calibrate_thresholds(series: list[pd.Series], var: str) -> dict:
    """Smallest step / drift threshold and stuck k with pooled episodes <= FA target on clean series."""
    days = sum(s.notna().sum() for s in series) / DAY
    st = [step_score(s, var) for s in series]
    dr = [drift_score(s, var) for s in series]
    runs = [stuck_run(s) for s in series]
    out = {"days": float(days)}
    for name, scs in (("theta_step", st), ("theta_drift", dr)):
        chosen, curve = None, []
        for th in THETA_GRID:
            r = _rate(sum(len(episodes(sc > th)) for sc in scs), days)
            curve.append((float(th), r))
            if chosen is None and r <= FA_TARGET_PER_30D:
                chosen = float(th)
        out[name] = chosen if chosen is not None else float(THETA_GRID[-1])
        out[name + "_curve"] = curve
    out["stuck_k"] = None
    out["stuck_curve"] = []
    for k in STUCK_K_GRID:
        r = _rate(sum(len(episodes(rn >= k)) for rn in runs), days)
        out["stuck_curve"].append((k, r))
        if out["stuck_k"] is None and r <= FA_TARGET_PER_30D:
            out["stuck_k"] = k
    return out


# ---------------------------------------------------------------------------------------------
# NERRS data
# ---------------------------------------------------------------------------------------------

def stage_nerrs(max_stations: int | None = None) -> tuple[dict, list[dict]]:
    """{(station, year): 15-min frame of VAR_CFG columns on a regular grid}, input file list."""
    from experiments import nerrs_load as nl
    from experiments import nerrs_multi as nm

    frames, files = {}, []
    stations = [(r, c) for r in nm.RESERVES.values() for c in r.wq_stations]
    for reserve, code in stations[:max_stations]:
        for path in sorted(reserve.data_dir.glob(f"{reserve.code}{code}wq*.csv")):
            year = int(path.stem[-4:])
            if year not in nm.QC_YEARS:
                continue
            f, _ = nl.read_wq_file(path, tuple(VAR_CFG))
            f = f[~f.index.duplicated()]
            f = f[f.index.minute % STEP_MIN == 0]
            grid = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:45", freq=f"{STEP_MIN}min")
            f = f.reindex(grid).reindex(columns=list(VAR_CFG))
            frames[(f"{reserve.code}{code}", year)] = f
            files.append({"file": str(path.relative_to(paths.FOREIGN_DATA_DIR)), "sha256": sha256(path), "rows": int(len(f))})
    return frames, files


# ---------------------------------------------------------------------------------------------
# fault types on NERRS
# ---------------------------------------------------------------------------------------------

F1 = {"e1_factor": 1 / 20.013, "e3_factor": 8.1, "gap_min": 146.0, "ph_delta": -1.01, "ph_duration_h": 6.25,
      "foul_gain": 12.520661157024799, "foul_days": 6.25, "rail_days": 3.75, "rail_overshoot": 1.3611111111111112,
      "clear_residual": 4.53, "clear_settle_min": 3.92, "e3_ph": 0.22}

FAULT_TYPES = {  # target variable, horizon (h), credit start offset (h)
    "scale_down": ("DO_mgl", 24, 0), "scale_up": ("DO_mgl", 24, 0), "gap": ("DO_mgl", 24, 0),
    "stuck0": ("Turb", 24, 0), "ph_ramp": ("pH", 24, 0), "fouling": ("Turb", 7 * 24, 0),
    "rail": ("Turb", 7 * 24, 0), "E1": ("DO_mgl", 24, 0), "E3": ("DO_mgl", 24, -24),
}


def fault_specs(kind: str, frame: pd.DataFrame, onset: pd.Timestamp) -> list[FaultSpec]:
    if kind == "scale_down":
        return [FaultSpec("DO_mgl", "scale_step", 0.0, {"factor": F1["e1_factor"]})]
    if kind == "scale_up":
        return [FaultSpec("DO_mgl", "scale_step", 0.0, {"factor": F1["e3_factor"]})]
    if kind == "gap":
        return [FaultSpec("*", "gap", 0.0, {"duration": F1["gap_min"]})]
    if kind == "stuck0":
        return [FaultSpec("Turb", "stuck", 0.0, {"value": 0.0})]
    if kind == "ph_ramp":
        return [FaultSpec("pH", "ramp", 0.0, {"delta": F1["ph_delta"], "duration": F1["ph_duration_h"] * 60})]
    if kind == "fouling":
        return [FaultSpec("Turb", "fouling", 0.0, {"growth": F1["foul_days"] * 1440, "gain": F1["foul_gain"]})]
    if kind == "rail":
        base = frame["Turb"][onset - pd.Timedelta(hours=24):onset - pd.Timedelta(minutes=1)].median()
        if not np.isfinite(base):
            base = frame["Turb"][:onset - pd.Timedelta(minutes=1)].dropna().iloc[-DAY:].median()
        f_rail = TURB_RAIL_NTU / max(base, 0.1)
        factor = f_rail * F1["rail_overshoot"]
        duration = F1["rail_days"] * 1440 * np.log(factor) / np.log(f_rail)
        return [FaultSpec("Turb", "ramp", 0.0, {"factor": factor, "duration": duration, "cap": TURB_RAIL_NTU})]
    if kind == "E1":
        return [FaultSpec("DO_mgl", "scale_step", 0.0, {"factor": F1["e1_factor"]}),
                FaultSpec("Turb", "fouling", -14 * 1440.0, {"growth": F1["foul_days"] * 1440, "gain": F1["foul_gain"],
                                                            "clear_after_min": 1.5, "residual": F1["clear_residual"],
                                                            "settle": F1["clear_settle_min"]})]
    if kind == "E3":
        return [FaultSpec("DO_mgl", "scale_step", 0.0, {"factor": F1["e3_factor"]}),
                FaultSpec("Turb", "stuck", -24 * 60.0, {"value": 0.0}, end_offset_min=0.0),
                FaultSpec("pH", "ramp", -2.5, {"delta": F1["e3_ph"], "duration": 0.5})]
    raise KeyError(kind)


def _seed(station: str, year: int, kind: str) -> np.random.Generator:
    return np.random.default_rng([SEED, zlib.crc32(f"{station}|{year}|{kind}".encode())])


def score_injection(frame: pd.DataFrame, kind: str, onset: pd.Timestamp, params: dict, sham: bool = False) -> dict:
    """Detection, delay and mask coverage for one injected fault.  Alarms count only on the faulted columns.
    ``sham``: same window and columns, nothing injected -> chance detection rate."""
    target, horizon_h, credit_h = FAULT_TYPES[kind]
    win = frame[onset - pd.Timedelta(days=40):onset + pd.Timedelta(days=8)]
    faulted, labels = inject_event(win, fault_specs(kind, win, onset), onset)
    cols = [c for c in labels.columns if labels[c].ne("").any()]
    det = detect(win if sham else faulted, params)
    c0, c1 = onset + pd.Timedelta(hours=credit_h), onset + pd.Timedelta(hours=horizon_h)
    use = ("gap",) if kind == "gap" else ALARM_DETECTORS
    row = {"kind": kind, "target": target, "onset": onset, "sham": sham}
    first = None
    for d in ALARM_DETECTORS + ("gap",):
        hit = det[d].loc[c0:c1, cols].any(axis=1)
        t = hit.index[hit.to_numpy()][0] if hit.any() else None
        row[f"det_{d}"] = t is not None
        if d in use and t is not None and (first is None or t < first):
            first = t
    row["detected"] = first is not None
    row["delay_h"] = (first - onset) / pd.Timedelta(hours=1) if first is not None else np.nan
    # mask recall on faulted samples of all labelled columns in [onset, onset + 7 d]
    lab = labels[onset:onset + pd.Timedelta(days=7)].ne("")
    flg = flags_of(det)[onset:onset + pd.Timedelta(days=7)]
    n_f = int(lab.to_numpy().sum())
    row["n_faulted"] = n_f
    row["mask_recall"] = float((lab & flg).to_numpy().sum() / n_f) if n_f else np.nan
    cp = changepoints_of(det).loc[c0:c1, cols].any(axis=1)
    if cp.any():
        t_cp = cp.index[cp.to_numpy()][0]
        after = np.asarray(lab.index >= t_cp)[:, None]
        cov = lab.to_numpy() & (flg.to_numpy() | after)
        row["cover_with_cp"] = float(cov.sum() / n_f) if n_f else np.nan
    else:
        row["cover_with_cp"] = row["mask_recall"]
    return row


def clean_fa(frame: pd.DataFrame, params: dict) -> dict:
    det = detect(frame, params)
    row = {}
    days = frame.notna().sum() / DAY
    for d in ALARM_DETECTORS:
        for v in frame.columns:
            row[f"{d}|{v}"] = len(episodes(det[d][v]))
    anyal = pd.concat([det[d] for d in ALARM_DETECTORS]).groupby(level=0).max()
    for v in frame.columns:
        row[f"any|{v}"] = len(episodes(anyal[v]))
        row[f"days|{v}"] = float(days[v])
        valid = frame[v].notna()
        row[f"flagged|{v}"] = int((flags_of(det)[v] & valid).sum())
        row[f"valid|{v}"] = int(valid.sum())
    return row


def cluster_ci(df: pd.DataFrame, col: str, n: int = 2000, seed: int = SEED) -> tuple[float, float]:
    groups = [g[col].to_numpy(dtype=float) for _, g in df.groupby("station")]
    rng = np.random.default_rng(seed)
    stats = []
    for _ in range(n):
        pick = rng.integers(0, len(groups), len(groups))
        vals = np.concatenate([groups[i] for i in pick])
        stats.append(np.nanmean(vals))
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


# ---------------------------------------------------------------------------------------------
# NB1 illustration
# ---------------------------------------------------------------------------------------------

NB1_COLS = ("NH4", "TSS", "COD", "pH", "Temperature")
NB1_OFFSETS = {"NH4": 0.01, "TSS": 1.0, "COD": 1.0}
NB1_KNOWN = [  # (label, start, end, variables) local time; credit windows around catalogued faults (F1)
    ("TSS bám bẩn bắt đầu", "2026-05-31", "2026-06-08", ("TSS",)),
    ("COD lên trần 1", "2026-06-05", "2026-06-12", ("COD",)),
    ("E1 31/07 14:06", "2026-07-31 14:00", "2026-08-01 14:06", ("NH4", "TSS")),
    ("E2 12/08 16:58", "2026-08-12 16:45", "2026-08-13 19:25", ("COD", "NH4", "TSS", "pH", "Temperature")),
    ("E3 16/09 15:34", "2026-09-15 15:34", "2026-09-17 15:34", ("NH4", "COD", "pH")),
    ("pH 19/09 (06:00 +0,22; tụt từ ~10:20)", "2026-09-19 05:45", "2026-09-20 10:00", ("pH",)),
    ("COD lên trần 2", "2026-09-19", "2026-09-22", ("COD",)),
]


def nb1_frame() -> pd.DataFrame:
    from experiments.paper2_faults import load_history

    h = load_history()
    f = h[list(NB1_COLS)].resample(f"{STEP_MIN}min").median()
    return f


def nb1_detect(f: pd.DataFrame, params: dict) -> dict:
    """NERRS thresholds on NB1: NH4 / TSS / pH play DO / Turb / pH in the cross-channel rule; COD uses Turb's."""
    return detect(f, params, var_map=dict(NB1_TO_NERRS), offsets=NB1_OFFSETS, rails={"COD": COD_RAIL})


def nb1_report(f: pd.DataFrame, det: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for label, a, b, cols in NB1_KNOWN:
        r = {"event": label, "window": f"{a} → {b}"}
        firsts = []
        for d in ALARM_DETECTORS:
            starts = [t for c in cols for t in episodes(det[d][c]) if pd.Timestamp(a) <= t <= pd.Timestamp(b)]
            t = min(starts) if starts else None
            r[d] = str(t) if t is not None else ""
            if t is not None:
                firsts.append(t)
        r["first_alarm"] = str(min(firsts)) if firsts else ""
        rows.append(r)
    ep = []
    for d in ALARM_DETECTORS:
        for col in f.columns:
            for t in episodes(det[d][col]):
                inside = any(pd.Timestamp(a) <= t <= pd.Timestamp(b) and col in cols for _, a, b, cols in NB1_KNOWN)
                ep.append({"detector": d, "variable": col, "start": t, "in_known_window": inside})
    return pd.DataFrame(rows), pd.DataFrame(ep)


# ---------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-name", default="paper2-f2-20261028")
    ap.add_argument("--output", type=Path, default=None, help="override run dir (scratch runs)")
    ap.add_argument("--max-stations", type=int, default=None, help="dry runs only")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    out = args.output or paths.EXPERIMENT_OUTPUT_DIR / args.run_name
    out.mkdir(parents=True, exist_ok=False)
    t0 = time.perf_counter()

    frames, files = stage_nerrs(args.max_stations)
    print(f"staged {len(frames)} station-years in {time.perf_counter() - t0:.0f}s", flush=True)

    # --- calibration (2007-2008, clean) ---
    params, curves = {}, {}
    for var in VAR_CFG:
        ser = [f[var] for (st, yr), f in frames.items() if yr in CAL_YEARS and f[var].notna().sum() > 30 * DAY]
        cal = calibrate_thresholds(ser, var)
        params[var] = {k: cal[k] for k in ("theta_step", "theta_drift", "stuck_k")}
        curves[var] = {k: cal[k] for k in cal if k.endswith("_curve")} | {"days": cal["days"], "n_series": len(ser)}
        print(var, params[var], flush=True)
    (out / "thresholds.json").write_text(json.dumps({"params": params, "fa_target_per_30d": FA_TARGET_PER_30D,
                                                     "calibration_years": CAL_YEARS, "curves": curves}, indent=1),
                                         encoding="utf-8")

    # --- clean FA on test years ---
    fa_rows = []
    for (st, yr), f in frames.items():
        if yr in TEST_YEARS:
            fa_rows.append({"station": st, "year": yr} | clean_fa(f, params))
    fa = pd.DataFrame(fa_rows)
    fa.to_csv(out / "clean_fa_by_station_year.csv", index=False)
    fa_sum = []
    for v in VAR_CFG:
        days = fa[f"days|{v}"].sum()
        r = {"variable": v, "days": days, "flagged_fraction": fa[f"flagged|{v}"].sum() / max(fa[f"valid|{v}"].sum(), 1)}
        for d in ALARM_DETECTORS + ("any",):
            r[f"{d}_per_30d"] = _rate(int(fa[f"{d}|{v}"].sum()), days)
        fa_sum.append(r)
    fa_sum = pd.DataFrame(fa_sum)
    fa_sum.to_csv(out / "clean_fa_summary.csv", index=False)
    print(fa_sum.round(3).to_string(index=False), flush=True)

    # --- injections (test years) ---
    rows = []
    for (st, yr), f in frames.items():
        if yr not in TEST_YEARS:
            continue
        for kind, (target, _, _) in FAULT_TYPES.items():
            valid = f[target].notna()
            if valid.mean() < 0.3:
                continue
            try:
                onsets = place_onsets(f.index, N_PER_STATION_YEAR, _seed(st, yr, kind), before=pd.Timedelta(days=40),
                                      after=pd.Timedelta(days=8), min_separation=pd.Timedelta(days=50), valid=valid,
                                      min_valid_fraction=MIN_VALID, max_tries=400)
            except (RuntimeError, ValueError):
                continue
            for onset in onsets:
                if kind == "E1" and f["Turb"][onset - pd.Timedelta(days=15):onset].notna().mean() < 0.5:
                    continue
                rows.append({"station": st, "year": yr} | score_injection(f, kind, onset, params))
                rows.append({"station": st, "year": yr} | score_injection(f, kind, onset, params, sham=True))
    allrows = pd.DataFrame(rows)
    allrows.to_csv(out / "injections.csv", index=False)
    inj, shm = allrows[~allrows["sham"]], allrows[allrows["sham"]]
    summ = []
    for kind, g in inj.groupby("kind", sort=False):
        lo, hi = cluster_ci(g, "detected")
        sg = shm[shm["kind"] == kind]
        key = ["station", "year", "onset"]
        pair = g[key + ["detected"]].merge(sg[key + ["detected"]], on=key, suffixes=("", "_sham"))
        pair["excess"] = pair["detected"].astype(float) - pair["detected_sham"].astype(float)
        ex_lo, ex_hi = cluster_ci(pair, "excess")
        r = {"kind": kind, "n": len(g), "stations": g["station"].nunique(), "detection_rate": g["detected"].mean(),
             "ci_lo": lo, "ci_hi": hi, "sham_rate": sg["detected"].mean(),
             "excess_over_sham": pair["excess"].mean(), "excess_ci_lo": ex_lo, "excess_ci_hi": ex_hi, "median_delay_h": g["delay_h"].median(),
             "mask_recall_median": g["mask_recall"].median(), "cover_with_cp_median": g["cover_with_cp"].median()}
        for d in ALARM_DETECTORS + ("gap",):
            r[f"rate_{d}"] = g[f"det_{d}"].mean()
        summ.append(r)
    summ = pd.DataFrame(summ)
    summ.to_csv(out / "detection_summary.csv", index=False)
    print(summ.round(3).to_string(index=False), flush=True)

    # --- NB1 illustration ---
    nb1 = nb1_frame()
    det = nb1_detect(nb1, params)
    known, ep = nb1_report(nb1, det)
    known.to_csv(out / "nb1_known_events.csv", index=False)
    ep.to_csv(out / "nb1_alarm_episodes.csv", index=False)
    print(known.to_string(index=False), flush=True)
    nb1_days = (nb1.index[-1] - nb1.index[0]) / pd.Timedelta(days=1)
    nb1_sum = ep.groupby(["detector", "variable", "in_known_window"]).size().unstack(fill_value=0)
    nb1_sum.to_csv(out / "nb1_episode_counts.csv")

    hist = paths.EXPERIMENT_OUTPUT_DIR / "sensor-history-20261024" / "06M26042804.csv"
    manifest = {"run": out.name, "script": "experiments/paper2_detect.py", "git_head": git_head(),
                "created": pd.Timestamp.now(tz="UTC").isoformat(), "seconds": time.perf_counter() - t0,
                "max_stations": args.max_stations, "params": params, "nb1_days": nb1_days,
                "inputs": [{"path": str(hist), "sha256": sha256(hist)}, {"path": str(F1_RUN / "nb1_fault_catalog.json"),
                           "sha256": sha256(F1_RUN / "nb1_fault_catalog.json")}],
                "nerrs_files": files, "outputs": sorted(p.name for p in out.iterdir())}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"done in {time.perf_counter() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
