"""Paper 2 / F4: bounded level re-alignment at detected change points (research-only).

PRE-REGISTRATION (fixed 2026-10-30 and committed before any scoring run; ``preregistration.json`` in the run dir
records it with the git head; later changes go to NOTES.md "sai lệch"):

Why.  F3 (RL-78): level re-alignment (c') at every F2 change point fixes instrument re-scales (/20: -43 % ridge /
-74 % Bolt MAE 0-24 h; E1 -56 / -60 %) but on shams it multiplies error x2.9-x6.3 (ridge), because it "corrects"
natural changes and the shifts accumulate.  F4 tests whether a BOUNDED trigger keeps the gain and limits the harm.

Base.  The bounded variants are built on (a) (raw observed stream), not on (b): (b) itself costs up to +10.6 %
(ridge) / +15 % (Bolt) on F3 shams, which alone would use up the 10 % harm budget.  When the trigger is silent a
variant's input is exactly (a)'s, so its forecast is (a)'s (ratio 1 by construction; this is used to skip
foundation-model runs on silent shams, see Subsets).

Candidate change points.  F2 ``changepoints`` (step | cross) on the target column, re-located causally as in F3
(``Inputs._refine``: split k in (alarm - 2W, alarm] maximising the median difference; shift d = median z[k..alarm]
- median z[k-W..k-1], z = F2 transform, log(x + c) for positive variables).  Every condition uses data <= alarm.
  (i)   ``instant``    the step is realised within <= 2 samples: J = the largest in |.| of the 1-sample changes
                       z[j] - z[j-1] and 2-sample changes z[j+1] - z[j-1] for j in [k-W, min(k+W, alarm)] (the
                       re-located split is only accurate to a few samples; all samples finite, j + 1 <= alarm);
                       pass if sign(J) = sign(d) and |J| >= 0.8 |d|.  (Fixed in the 1-station dry run before the
                       pre-registration commit: J at k only missed real one-sample steps, k lands 1-3 samples off.)
  (iii) ``magnitude``  log-transformed variable (DO, Turb; NB1 NH4, TSS, COD) and |d| >= log(3) (ratio >= x3).
                       pH / Temp are never re-aligned.
  (ii)  ``ref_quiet``  physical reference channels did not move: Temp (and Sal where measured; NB1 has Temp only)
                       |median [k, alarm] - median [k-W, k)| < 0.5 degC (Temp) / 2.0 psu (Sal), each channel
                       needing >= 2 finite pre and >= 1 finite post samples, >= 1 channel available (none
                       available -> not quiet).  Thresholds fixed a priori (not tuned): a probe re-scale does not
                       move the water temperature / salinity, fronts, storms and river pulses do.  RL-72: NH4 and
                       TSS stepped together at E1 and NH4 / COD / pH at E3, so other water-quality channels are
                       NOT used as references (NB1 Temp moved <= 0.1 degC at E1 / E3).
Variants (nested; at most one correction active, i.e. latest qualifying change point only, no accumulation):
  ``v1``  (i) + (iii): at origin t, the latest change point with alarm <= t passing the conditions sets
          z[cp:] -= d (back-transformed); a later qualifying change point replaces it.
  ``v2``  v1 + (ii).
  ``v3``  v2 with a decaying correction z[cp:] -= d * 0.5 ** ((t - alarm) / 72 h).  Stated cost: a real re-scale is
          permanent, so v3 re-tracks the broken sensor over days (post7); its only value is on false triggers.
Reference mechanisms re-run here: (a), (b) (F3 QC mask); ridge also F3's unbounded (c') ``c_align``.

Faults / shams.  NERRS NCEI 2009-2011: exactly the F2 placements + paired shams (``paper2-f2-20261028``), F2 thresholds,
F3 window (onset - 40 d .. + 8 d) and origins (hourly -48 h..+48 h, 3-hourly to +7 d), horizons 1 h (primary) and 6 h,
scored against the clean value.  Extra natural shams from NERRS CDMO 2021-2025 (requests 726235 + 184841, good flag
``<0>`` only, latin-1): for every WQ station x variable (DO_mgl, Turb) with >= 60 d of good data in 2021-2022 (ridge
fit there): ``cdmo_random`` = 2 seeded onsets per station x variable x year 2023-2025 (same rules as F2: >= 80 %
valid in [-8 d, +7 d], >= 50 d apart); ``cdmo_event`` = up to 4 seeded onsets per station x variable x year at the
start of a natural F2 change-point episode (step | cross alarm on the target, full-series detection) - exactly the
places where unbounded (c') fires, i.e. fronts, storms, river pulses.  Nothing is injected in either; harm = MAE vs (a).
Also reported: qualifying triggers per 30 d per variant on the full clean 2021-2025 series.

Models.  ridge (F3 ``RidgeModel``, per station x variable x horizon; NCEI fit 2007-2008 as F3, CDMO fit 2021-2022);
Chronos-Bolt small (F3 ``BoltModel``); Chronos-2 small (paper 1 ``paper1_t1_chronos2.Chronos2Forecaster``, pinned
revision, q0.1 / q0.5 / q0.9), context 7 d, zero-shot.  2 torch threads, one process at a time.  PI80 = q0.1-q0.9
(FM) or +- q80 |training residual| (ridge); ACI as F3 (delayed feedback from the observed stream).

Split.  Station-level: ``crc32(station) % 2 == 0`` -> calibration, else held-out (same rule for CDMO stations).
Subsets.  ridge: every F2 placement and sham with a ridge fit; every CDMO sham.  Foundation models: per fault type one
seeded placement per station - re-scale types (scale_down, scale_up, E1, E3) on all stations (calibration + held-out),
other types (stuck0, ph_ramp, fouling, rail, gap) on held-out stations only; shams (F2 and CDMO) only where some
variant triggers in the scored span (silent -> ratio 1 exactly, counted in the sham denominator).

Metrics.  Per injection: MAE post24 [0, 24 h) / post7 [24 h, 7 d) vs clean; reduction vs (a) = 1 - geomean(MAE_m /
MAE_a); 95 % CIs by station-block bootstrap (primary, 2000 draws) and by injection (secondary); vs (b) likewise; PI80
coverage static / ACI post24 and post7; trigger rate and delay.

Selection (calibration stations only, h = 1 h).  For each variant: objective = min over the three models of the post24
reduction vs (a) on scale_down and E1 (the informative types: on DO, scale_up / E3 are already fixed by (b) through
the hard range, and that does not transfer to NB1); harm = max over models of [worst F2 sham kind, cdmo_random,
cdmo_event] (geomean ratio - 1).  Eligible: harm <= 10 %.  Choose the eligible variant with the largest objective;
within 0.01 of the best -> fewer conditions (v1 < v2 < v3).  No eligible variant -> the one with the smallest harm
(selection reported as "no eligible variant").

Gate (held-out stations, h = 1 h, per model; the selected variant is the headline, all three are reported):
  G1  re-scale gain: post24 reduction vs (a) >= 30 % with station-block 95 % CI lower bound > 0 on each of scale_down,
      scale_up, E1, E3 (scale_down / E1 are the informative ones);
  G2  sham harm <= 10 % on the worst F2 sham kind, on cdmo_random and on cdmo_event;
  G3  not worse than (b) on the other types: geomean(MAE_v / MAE_b) - 1 <= 10 % at post24 on stuck0, ph_ramp, fouling,
      rail, gap.
  PASS for a model if G1-G3 all hold; the F4 hypothesis ("bounded re-alignment is safe and useful") is supported only
  if the selected variant passes for all three models.  PI80 coverage is reported, not gated.

NB1 (descriptive, no truth): Bolt and Chronos-2 around E1 (NH4 31/07 14:06), E2 (12/08 16:58: NH4, COD), E3 (16/09
15:34: NH4, COD) and pH 19/09; per F2 change point the three condition values; mean 1-h forecast level 0-24 h after
the event per mechanism vs the observed pre / post levels.  F3 conventions (40-d window, NERRS thresholds, NB1 offsets).

    python experiments/paper2_bounded_align.py prereg                  # creates the run dir + preregistration.json
    python experiments/paper2_bounded_align.py ridge                   # NCEI injections + shams, ridge, triggers
    python experiments/paper2_bounded_align.py fm --model bolt|chronos2
    python experiments/paper2_bounded_align.py cdmo                    # CDMO shams: ridge + FMs on triggered
    python experiments/paper2_bounded_align.py nb1
    python experiments/paper2_bounded_align.py evaluate
  (``--output DIR`` for scratch runs; ``--max N`` dry runs.)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import zipfile
import zlib
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from experiments.nh4_step_0731 import sha256  # noqa: E402
from experiments.paper2_detect import (  # noqa: E402
    DAY, VAR_CFG, W, changepoints_of, detect, episodes, fault_specs, flags_of, transform)
from experiments.paper2_faults import git_head, inject_event, place_onsets  # noqa: E402
from experiments.paper2_mechanisms import (  # noqa: E402
    F2_RUN, HORIZONS, WINDOWS, Inputs, RidgeModel, _boot, aci_intervals, change_points, contexts_for, origin_times,
    recovery_hours, window_mask)

RUN_NAME = "paper2-f4-20261030"
SEED = 20261030
JUMP_FRACTION = 0.8
MIN_LOG_RATIO = float(np.log(3.0))
REF_THRESHOLDS = {"Temp": 0.5, "Sal": 2.0}
REF_MIN_PRE, REF_MIN_POST = 2, 1
DECAY_HALFLIFE_H = 72.0
VARIANTS = {"v1": ("instant", "magnitude"), "v2": ("instant", "magnitude", "ref_quiet"),
            "v3": ("instant", "magnitude", "ref_quiet")}
VARIANT_ORDER = ("v1", "v2", "v3")
MECHS_RIDGE = ("a", "b", "c_align", "v1", "v2", "v3")
MECHS_FM = ("a", "b", "v1", "v2", "v3")
MECHS_SHAM_FM = ("a", "v1", "v2", "v3")
RESCALE = ("scale_down", "scale_up", "E1", "E3")
INFORMATIVE = ("scale_down", "E1")
OTHER = ("stuck0", "ph_ramp", "fouling", "rail", "gap")
GAIN_MIN, HARM_MAX, VS_B_HARM_MAX, TIE = 0.30, 0.10, 0.10, 0.01
MODELS = ("ridge", "bolt", "chronos2")
CHRONOS2_NAME = "chronos-2-small"
TORCH_THREADS = 2
LAST_ORIGIN = pd.Timedelta(days=7)
CDMO_DIR = paths.FOREIGN_DATA_DIR / "nerrs_cdmo" / "raw"
CDMO_ZIPS = {"726235": ("726235.zip", "726235.csv", "1f629d8acdabaef4d38e400536c23c32abeb6967f8d7239d8b9a1d811ffc67c9"),
             "184841": ("184841.zip", "184841.csv", "04a8c6fd559530c93a21d2f9a7be786339b7b053fa73e406a41c3d9933193d37")}
CDMO_COLS = ("DO_mgl", "Turb", "pH", "Temp", "Sal")
CDMO_GRID = ("2021-01-01", "2025-12-31 23:45")
CDMO_FIT_END = "2022-12-31 23:45"
CDMO_SHAM_YEARS = (2023, 2024, 2025)
CDMO_VARS = ("DO_mgl", "Turb")
CDMO_RANDOM_PER_YEAR, CDMO_EVENT_PER_YEAR = 2, 4
NB1_EVENTS = (("E1_NH4", "NH4", "2026-07-31 14:06"), ("E2_NH4", "NH4", "2026-08-12 16:58"),
              ("E2_COD", "COD", "2026-08-12 16:58"), ("E3_NH4", "NH4", "2026-09-16 15:34"),
              ("E3_COD", "COD", "2026-09-16 15:34"), ("D1_pH", "pH", "2026-09-19 10:22"))


def split_of(station: str) -> str:
    return "cal" if zlib.crc32(station.encode()) % 2 == 0 else "held"


def _seed(*parts) -> np.random.Generator:
    return np.random.default_rng([SEED, zlib.crc32("|".join(map(str, parts)).encode())])


# ---------------------------------------------------------------------------------------------
# trigger conditions (pure, causal)
# ---------------------------------------------------------------------------------------------

def assess_cp(z: np.ndarray, k: int, a: int, d: float, log_var: bool, ref: dict[str, np.ndarray]) -> dict:
    """Bounded-trigger conditions for one re-located change point (split k, alarm index a >= k, shift d)."""
    if k < 1 or a < k:
        return {"shift": float(d), "jump": np.nan, "jump_frac": np.nan, "instant": False, "magnitude": False,
                "ref_dTemp": np.nan, "ref_dSal": np.nan, "ref_available": 0, "ref_quiet": False}
    jumps = []
    for j in range(max(1, k - W), min(k + W, a) + 1):   # the split k is only located to within a few samples
        if np.isfinite(z[j]) and np.isfinite(z[j - 1]):
            jumps.append(float(z[j] - z[j - 1]))
            if j + 1 <= a and np.isfinite(z[j + 1]):
                jumps.append(float(z[j + 1] - z[j - 1]))
    jump = max(jumps, key=abs) if jumps else np.nan
    instant = bool(np.isfinite(jump) and d != 0 and np.sign(jump) == np.sign(d) and abs(jump) >= JUMP_FRACTION * abs(d))
    magnitude = bool(log_var and abs(d) >= MIN_LOG_RATIO)
    out = {"shift": float(d), "jump": jump, "jump_frac": abs(jump) / abs(d) if d and np.isfinite(jump) else np.nan,
           "instant": instant, "magnitude": magnitude}
    available, stepped = 0, False
    for name, thr in REF_THRESHOLDS.items():
        arr = ref.get(name)
        out[f"ref_d{name}"] = np.nan
        if arr is None:
            continue
        pre, post = arr[max(0, k - W):k], arr[k:a + 1]
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


class BoundedInputs:
    """Mechanism inputs for one target column: (a), (b), F3 (c'), and the bounded variants v1-v3.

    ``key(mech, t)`` identifies the input series an origin t uses (data <= t decides it); ``build(key)`` makes it.
    Identical keys share one forecast, so a silent variant costs nothing and equals (a) exactly."""

    def __init__(self, obs: pd.Series, flags: pd.Series, cps: list, var: str, c: float | None = None,
                 ref: pd.DataFrame | None = None):
        self.base = Inputs(obs, flags, cps, var, c)
        self.obs, self.var = self.base.obs, var
        self.c = VAR_CFG[var]["c"] if c is None else c
        self.log = VAR_CFG[var]["log"]
        z = self.base.z_obs.to_numpy(dtype=float)
        refs = {} if ref is None else {n: ref[n].reindex(obs.index).to_numpy(dtype=float) for n in ref.columns}
        self.assess = []
        for alarm, cp, shift in self.base.cps:
            k, a = (int(i) for i in obs.index.get_indexer([cp, alarm]))
            self.assess.append({"alarm": alarm, "cp": cp, "k": k} | assess_cp(z, k, a, shift, self.log, refs))
        self.qual = {v: [i for i, s in enumerate(self.assess) if all(s[c] for c in conds)] for v, conds in VARIANTS.items()}
        self._cache: dict = {}

    def latest(self, variant: str, t: pd.Timestamp) -> int | None:
        q = [i for i in self.qual[variant] if self.assess[i]["alarm"] <= t]
        return max(q, key=lambda i: self.assess[i]["alarm"]) if q else None

    def key(self, mech: str, t: pd.Timestamp) -> tuple:
        if mech in ("a", "b"):
            return (mech,)
        if mech == "c_align":
            k = self.base.active(t)
            return ("c_align", k) if k else ("b",)
        i = self.latest(mech, t)
        if i is None:
            return ("a",)
        w = 1.0
        if mech == "v3":
            w = round(0.5 ** (((t - self.assess[i]["alarm"]) / pd.Timedelta(hours=1)) / DECAY_HALFLIFE_H), 6)
        return ("shift", i, w)

    def build(self, key: tuple) -> pd.Series:
        if key not in self._cache:
            self._cache[key] = self._build(key)
        return self._cache[key]

    def _build(self, key: tuple) -> pd.Series:
        if key[0] == "a":
            return self.obs
        if key[0] == "b":
            return self.base.masked
        if key[0] == "c_align":
            return self.base.series("c_align", self.base.cps[key[1] - 1][0])
        _, i, w = key
        s = self.assess[i]
        z = transform(self.obs, self.var, self.c).to_numpy(dtype=float).copy()
        z[s["k"]:] -= w * s["shift"]
        vals = np.exp(z) - self.c if self.log else z
        return pd.Series(vals, index=self.obs.index, name=self.obs.name)

    def trigger_info(self, onset: pd.Timestamp, last_origin: pd.Timestamp) -> dict:
        row = {"n_cp": len(self.assess)}
        for v in VARIANTS:
            q = self.qual[v]
            row[f"{v}_n"] = len(q)
            row[f"{v}_triggered"] = any(self.assess[i]["alarm"] <= last_origin for i in q)
            hits = [self.assess[i]["alarm"] for i in q if onset - pd.Timedelta(hours=1) <= self.assess[i]["alarm"]
                    <= onset + pd.Timedelta(hours=24)]
            row[f"{v}_hit24"] = bool(hits)
            row[f"{v}_delay_h"] = (min(hits) - onset) / pd.Timedelta(hours=1) if hits else np.nan
        near = [s for s in self.assess if onset - pd.Timedelta(hours=1) <= s["alarm"] <= onset + pd.Timedelta(hours=24)]
        row["cp_near"] = bool(near)
        if near:
            s = near[0]
            row["cp_delay_h"] = (s["alarm"] - onset) / pd.Timedelta(hours=1)
            for k in ("shift", "jump_frac", "instant", "magnitude", "ref_quiet", "ref_available", "ref_dTemp", "ref_dSal"):
                row[f"cp_{k}"] = s[k]
        return row


# ---------------------------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------------------------

class FM:
    """Chronos-Bolt small (F3 wrapper) or Chronos-2 small (paper 1 wrapper): contexts -> (n, 24, 3) q10/q50/q90."""

    def __init__(self, name: str, threads: int = TORCH_THREADS):
        self.name = name
        if name == "bolt":
            from experiments.paper2_mechanisms import BoltModel

            self.model = BoltModel(threads)
            self.meta = {"repo": "amazon/chronos-bolt-small"}
        elif name == "chronos2":
            from experiments import paper1_t1_chronos2 as t1

            repo, rev = t1.CHRONOS2[CHRONOS2_NAME]
            self.model = t1.Chronos2Forecaster(repo, rev, threads)
            self.cols = [t1.QUANTILES.index(q) for q in (0.1, 0.5, 0.9)]
            self.meta = {"repo": repo, "revision": rev}
        else:
            raise KeyError(name)

    def quantiles(self, contexts: np.ndarray) -> np.ndarray:
        out = np.full((len(contexts), 24, 3), np.nan)
        ok = np.isfinite(contexts).any(axis=1)
        if ok.any():
            if self.name == "bolt":
                out[ok] = self.model.quantiles(contexts[ok])
            else:
                out[ok] = self.model.quantile_paths(contexts[ok].astype(np.float32), 24, 64)[:, :, self.cols]
        return out


def forecasts(model_name: str, model, inp: BoundedInputs, origins: pd.DatetimeIndex, mechs) -> tuple[dict, dict]:
    """{(mech, horizon): [pred, lo, hi]} with one model call per distinct input series; missing -> (a)'s."""
    keys = {m: [inp.key(m, t) for t in origins] for m in mechs}
    need: dict = {}
    for m in mechs:
        for j, k in enumerate(keys[m]):
            need.setdefault(k, set()).add(j)
    vals = {}
    for k, js in need.items():
        js = np.array(sorted(js))
        ser, o = inp.build(k), origins[js]
        arrs = {h: [np.full(len(origins), np.nan) for _ in range(3)] for h in HORIZONS}
        if model_name == "ridge":
            for h in HORIZONS:
                for arr, v in zip(arrs[h], model.predict(ser, o, h)):
                    arr[js] = v
        else:
            q = model.quantiles(contexts_for(ser, o))
            for h, s in HORIZONS.items():
                for arr, col in zip(arrs[h], (1, 0, 2)):
                    arr[js] = q[:, s - 1, col]
        vals[k] = arrs
    out, fallbacks = {}, {}
    for m in mechs:
        for h in HORIZONS:
            res = [np.array([vals[k][h][i][j] for j, k in enumerate(keys[m])]) for i in range(3)]
            out[(m, h)] = res
    a_key = ("a",)
    for (m, h), (p, lo, hi) in out.items():
        bad = ~np.isfinite(p)
        fallbacks[(m, h)] = int(bad.sum())
        if m != "a" and bad.any():
            if ("a", h) in out:
                pa, la, ha = out[("a", h)]
            else:  # (a) not requested: compute it once
                if a_key not in vals:
                    sub = forecasts(model_name, model, inp, origins, ("a",))[0]
                    vals[a_key] = {hh: sub[("a", hh)] for hh in HORIZONS}
                pa, la, ha = vals[a_key][h]
            p[bad], lo[bad], hi[bad] = pa[bad], la[bad], ha[bad]
    return out, fallbacks


def score(model_name: str, model, truth: pd.Series, obs: pd.Series, inp: BoundedInputs, onset: pd.Timestamp,
          mechs) -> list[dict]:
    origins = origin_times(onset)
    fc, fallbacks = forecasts(model_name, model, inp, origins, mechs)
    rows = []
    for h in HORIZONS:
        tgt = origins + pd.Timedelta(minutes=h)
        y_true = truth.reindex(tgt).to_numpy(dtype=float)
        y_obs = obs.reindex(tgt).to_numpy(dtype=float)
        for m in mechs:
            p, lo, hi = fc[(m, h)]
            alo, ahi = aci_intervals(origins, lo, hi, y_obs, h)
            err = np.abs(p - y_true)
            row = {"model": model_name, "mech": m, "horizon_min": h, "fallbacks": fallbacks[(m, h)]}
            for w in WINDOWS:
                msk = window_mask(origins, onset, w)
                ok = msk & np.isfinite(err)
                row[f"mae_{w}"] = float(err[ok].mean()) if ok.any() else np.nan
                inside = np.isfinite(y_true) & msk
                row[f"cov_static_{w}"] = float(((y_true >= lo) & (y_true <= hi))[inside].mean()) if inside.any() else np.nan
                row[f"cov_aci_{w}"] = float(((y_true >= alo) & (y_true <= ahi))[inside].mean()) if inside.any() else np.nan
            row["recovery_h"] = recovery_hours(origins, err, onset, row["mae_baseline"])
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------------------------
# NERRS NCEI (F2 placements)
# ---------------------------------------------------------------------------------------------

def load_sal(keys) -> dict:
    """Good-flag Sal on the same 15-min grid as ``paper2_detect.stage_nerrs`` for the given (station, year)."""
    from experiments import nerrs_load as nl
    from experiments import nerrs_multi as nm

    out = {}
    for reserve in nm.RESERVES.values():
        for code in reserve.wq_stations:
            st = f"{reserve.code}{code}"
            for path in sorted(reserve.data_dir.glob(f"{st}wq*.csv")):
                year = int(path.stem[-4:])
                if (st, year) not in keys:
                    continue
                f, _ = nl.read_wq_file(path, ("Sal",))
                f = f[~f.index.duplicated()]
                f = f[f.index.minute % 15 == 0]
                grid = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:45", freq="15min")
                out[(st, year)] = f.reindex(grid)["Sal"] if "Sal" in f else pd.Series(np.nan, index=grid)
    return out


def prepare_nerrs(frame: pd.DataFrame, sal: pd.Series | None, kind: str, onset: pd.Timestamp, params: dict, sham: bool,
                  target: str):
    win = frame[onset - pd.Timedelta(days=40):onset + pd.Timedelta(days=8)]
    faulted, _ = inject_event(win, fault_specs(kind, win, onset), onset)
    obs = win if sham else faulted
    det = detect(obs, params)
    cps = change_points(changepoints_of(det)[target])
    ref = pd.DataFrame({"Temp": obs["Temp"],
                        "Sal": sal.reindex(win.index) if sal is not None else pd.Series(np.nan, index=win.index)})
    inp = BoundedInputs(obs[target], flags_of(det)[target], cps, target, ref=ref)
    return win[target], obs[target], inp


def fit_ridge(series: list[pd.Series], offset: float) -> RidgeModel | None:
    if not series or sum(s.notna().sum() for s in series) < 60 * DAY:
        return None
    rm = RidgeModel(offset)
    for h in HORIZONS:
        rm.fit(series, h)
    return rm


def load_f2() -> tuple[dict, pd.DataFrame]:
    params = json.loads((F2_RUN / "thresholds.json").read_text(encoding="utf-8"))["params"]
    inj = pd.read_csv(F2_RUN / "injections.csv", parse_dates=["onset"])[["station", "year", "kind", "target", "onset", "sham"]]
    inj["split"] = inj["station"].map(split_of)
    return params, inj


def fm_subset(inj: pd.DataFrame, triggers: pd.DataFrame) -> pd.DataFrame:
    """Foundation-model placements: one seeded placement per station x fault type (re-scale types: all stations,
    other types: held-out stations) + every F2 sham on which some variant triggers."""
    picks = []
    for kind, g in inj[~inj["sham"]].groupby("kind", sort=True):
        if kind not in RESCALE:
            g = g[g["split"] == "held"]
        g = g.iloc[_seed("fm", kind).permutation(len(g))].drop_duplicates("station").sort_values(["station", "onset"])
        picks.append(g)
    key = ["station", "year", "kind", "onset", "sham"]
    trig = triggers[triggers["sham"]].copy()
    trig["any_trig"] = trig[[f"{v}_triggered" for v in VARIANTS]].any(axis=1)
    sh = inj[inj["sham"]].merge(trig.loc[trig["any_trig"], key], on=key)
    picks.append(sh)
    return pd.concat(picks, ignore_index=True)


# ---------------------------------------------------------------------------------------------
# NERRS CDMO 2021-2025
# ---------------------------------------------------------------------------------------------

def load_cdmo() -> tuple[dict[str, pd.DataFrame], list[dict]]:
    """{station: 15-min LST frame of CDMO_COLS (good flag only)} for every WQ station in both requests."""
    from experiments.paper1_t3_nerrs import good_values

    usecols = ["StationCode", "DateTimeStamp"] + [c for v in CDMO_COLS for c in (v, f"F_{v}")]
    parts, inputs = [], []
    for name, (zname, member, sha) in CDMO_ZIPS.items():
        zp = CDMO_DIR / zname
        got = sha256(zp)
        if got != sha:
            raise RuntimeError(f"sha256 mismatch {zp}: {got}")
        inputs.append({"path": str(zp), "sha256": got})
        with zipfile.ZipFile(zp) as z:
            reader = pd.read_csv(z.open(member), usecols=usecols, dtype=str, keep_default_na=False, encoding="latin-1",
                                 chunksize=400_000)
            for ch in reader:
                ch["StationCode"] = ch["StationCode"].str.strip()
                ch = ch[ch["StationCode"].str.endswith("wq")]
                if ch.empty:
                    continue
                part = pd.DataFrame({"station": ch["StationCode"].str[:-2].to_numpy(),
                                     "t": pd.to_datetime(ch["DateTimeStamp"].str.strip(), format="%m/%d/%Y %H:%M").to_numpy()})
                for v in CDMO_COLS:
                    part[v] = good_values(ch[v], ch[f"F_{v}"]).to_numpy(dtype=float)
                parts.append(part)
    raw = pd.concat(parts, ignore_index=True)
    grid = pd.date_range(*CDMO_GRID, freq="15min")
    frames = {}
    for st, g in raw.groupby("station"):
        f = g.drop(columns="station").set_index("t").sort_index()
        f = f[~f.index.duplicated()]
        f = f[f.index.minute % 15 == 0]
        frames[st] = f.reindex(grid)
    return frames, inputs


def cdmo_offset(station: str) -> float:
    from experiments import nerrs_multi as nm

    return nm.RESERVES[station[:3]].utc_offset_h


def cdmo_shams(frames: dict, params: dict, fits: dict) -> pd.DataFrame:
    rows = []
    for st, f in sorted(frames.items()):
        det = detect(f[list(VAR_CFG)], params)
        cpa = changepoints_of(det)
        for var in CDMO_VARS:
            if (st, var) not in fits:
                continue
            valid = f[var].notna()
            vc = np.r_[0, np.cumsum(valid.to_numpy(dtype=int))]
            idx = f.index
            for year in CDMO_SHAM_YEARS:
                yi = idx[idx.year == year]
                try:
                    ons = place_onsets(yi, CDMO_RANDOM_PER_YEAR, _seed("random", st, var, year), before=pd.Timedelta(days=40),
                                       after=pd.Timedelta(days=8), min_separation=pd.Timedelta(days=50), valid=valid,
                                       min_valid_fraction=0.8, max_tries=400)
                except (RuntimeError, ValueError):
                    ons = []
                rows += [{"station": st, "var": var, "set": "cdmo_random", "onset": o} for o in ons]
                cand = []
                for t in episodes(cpa[var]):
                    if t.year != year or t - pd.Timedelta(days=40) < idx[0] or t + pd.Timedelta(days=8) > idx[-1]:
                        continue
                    a = idx.searchsorted(t - pd.Timedelta(days=8))
                    b = idx.searchsorted(t + pd.Timedelta(days=7), side="right")
                    if (vc[b] - vc[a]) / max(b - a, 1) >= 0.8:
                        cand.append(t)
                if cand:
                    pick = _seed("event", st, var, year).permutation(len(cand))[:CDMO_EVENT_PER_YEAR]
                    rows += [{"station": st, "var": var, "set": "cdmo_event", "onset": cand[i]} for i in sorted(pick)]
    out = pd.DataFrame(rows)
    out["split"] = out["station"].map(split_of)
    return out


def prepare_cdmo(f: pd.DataFrame, var: str, onset: pd.Timestamp, params: dict):
    win = f[onset - pd.Timedelta(days=40):onset + pd.Timedelta(days=8)]
    det = detect(win[list(VAR_CFG)], params)
    cps = change_points(changepoints_of(det)[var])
    inp = BoundedInputs(win[var], flags_of(det)[var], cps, var, ref=win[["Temp", "Sal"]])
    return win[var], win[var], inp


def cdmo_trigger_rates(frames: dict, params: dict) -> pd.DataFrame:
    rows = []
    for st, f in sorted(frames.items()):
        det = detect(f[list(VAR_CFG)], params)
        for var in CDMO_VARS:
            days = f[var].notna().sum() / DAY
            if days < 30:
                continue
            cps = change_points(changepoints_of(det)[var])
            inp = BoundedInputs(f[var], flags_of(det)[var], cps, var, ref=f[["Temp", "Sal"]])
            r = {"station": st, "var": var, "split": split_of(st), "valid_days": float(days), "f2_cp": len(cps)}
            for c in ("instant", "magnitude", "ref_quiet"):
                r[f"n_{c}"] = int(sum(s[c] for s in inp.assess))
            for v in ("v1", "v2"):
                r[f"{v}_n"] = len(inp.qual[v])
            rows.append(r)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------------------------

def _write_new(path: Path, df: pd.DataFrame | dict) -> None:
    if path.exists():
        raise FileExistsError(f"refusing_to_overwrite:{path}")
    if isinstance(df, pd.DataFrame):
        df.to_csv(path, index=False)
    else:
        path.write_text(json.dumps(df, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


def preregistration() -> dict:
    return {"run": RUN_NAME, "script": "experiments/paper2_bounded_align.py", "git_head": git_head(),
            "created": pd.Timestamp.now(tz="UTC").isoformat(), "seed": SEED,
            "conditions": {"instant": {"jump_fraction": JUMP_FRACTION, "max_samples": 2},
                           "magnitude": {"min_abs_log_ratio": MIN_LOG_RATIO, "ratio": 3.0, "log_variables_only": True},
                           "ref_quiet": {"thresholds": REF_THRESHOLDS, "min_pre": REF_MIN_PRE, "min_post": REF_MIN_POST,
                                         "windows": "pre [k-W, k), post [k, alarm]"}},
            "variants": {"v1": "instant + magnitude, latest qualifying change point only",
                         "v2": "v1 + ref_quiet", "v3": f"v2, correction decays with half-life {DECAY_HALFLIFE_H} h"},
            "base": "(a) raw observed stream", "references": {"ridge": list(MECHS_RIDGE), "fm": list(MECHS_FM)},
            "models": {"ridge": "F3 RidgeModel", "bolt": "amazon/chronos-bolt-small", "chronos2": CHRONOS2_NAME},
            "split": "crc32(station) % 2 == 0 -> cal, else held",
            "selection": {"objective": "min over models of post24 reduction vs (a) on " + ", ".join(INFORMATIVE),
                          "eligible": f"max harm over models of [worst F2 sham kind, cdmo_random, cdmo_event] <= {HARM_MAX}",
                          "ties": f"within {TIE} -> fewer conditions (v1 < v2 < v3)", "none_eligible": "smallest harm"},
            "gate": {"G1": f"held-out post24 reduction vs (a) >= {GAIN_MIN} and station-block CI lo > 0 on " + ", ".join(RESCALE),
                     "G2": f"sham harm <= {HARM_MAX} on worst F2 sham kind, cdmo_random, cdmo_event",
                     "G3": f"geomean(MAE_v/MAE_b) - 1 <= {VS_B_HARM_MAX} at post24 on " + ", ".join(OTHER),
                     "pass": "per model all of G1-G3; hypothesis supported if the selected variant passes for all three models",
                     "horizon_min": 60},
            "cdmo": {"zips": CDMO_ZIPS, "fit": [CDMO_GRID[0], CDMO_FIT_END], "sham_years": CDMO_SHAM_YEARS,
                     "vars": CDMO_VARS, "random_per_year": CDMO_RANDOM_PER_YEAR, "event_per_year": CDMO_EVENT_PER_YEAR},
            "nb1_events": NB1_EVENTS}


def stage_prereg(out: Path, _args) -> None:
    out.mkdir(parents=True, exist_ok=False)
    _write_new(out / "preregistration.json", preregistration())


def _require_prereg(out: Path) -> dict:
    p = out / "preregistration.json"
    if not p.exists():
        raise RuntimeError("run 'prereg' first: preregistration.json must exist before any forecast")
    return json.loads(p.read_text(encoding="utf-8"))


def stage_ridge(out: Path, args) -> None:
    from experiments import nerrs_multi as nm
    from experiments.paper2_detect import stage_nerrs

    _require_prereg(out)
    t0 = time.perf_counter()
    params, inj = load_f2()
    if args.max:
        keep = inj[~inj["sham"]].groupby("kind", sort=False).head(max(1, args.max // 9))
        inj = inj.merge(keep[["station", "year", "kind", "onset"]], on=["station", "year", "kind", "onset"])
    frames, files = stage_nerrs()
    sal = load_sal(set(zip(inj["station"], inj["year"])))
    offset = {f"{r.code}{c}": r.utc_offset_h for r in nm.RESERVES.values() for c in r.wq_stations}
    models = {}
    for st in sorted(inj["station"].unique()):
        for var in ("DO_mgl", "Turb", "pH"):
            clean = [frames[(st, y)][var] for y in (2007, 2008) if (st, y) in frames]
            rm = fit_ridge(clean, offset[st])
            if rm is not None:
                models[(st, var)] = rm
    print(f"staged, ridge fits {len(models)} ({time.perf_counter() - t0:.0f}s)", flush=True)
    rows, trig = [], []
    for i, r in enumerate(inj.itertuples(index=False)):
        truth, obs, inp = prepare_nerrs(frames[(r.station, r.year)], sal.get((r.station, r.year)), r.kind, r.onset,
                                        params, r.sham, r.target)
        last = origin_times(r.onset)[-1]
        base = {"station": r.station, "year": r.year, "kind": r.kind, "target": r.target, "onset": r.onset,
                "sham": r.sham, "split": r.split}
        rm = models.get((r.station, r.target))
        trig.append(base | {"ridge_fit": rm is not None} | inp.trigger_info(r.onset, last))
        if rm is not None:
            rows += [base | x for x in score("ridge", rm, truth, obs, inp, r.onset, MECHS_RIDGE)]
        if i % 200 == 0:
            print(f"ridge {i}/{len(inj)} ({time.perf_counter() - t0:.0f}s)", flush=True)
    _write_new(out / "triggers_nerrs.csv", pd.DataFrame(trig))
    _write_new(out / "results_ridge.csv", pd.DataFrame(rows))
    _write_new(out / "manifest_ridge.json", {"seconds": time.perf_counter() - t0, "git_head": git_head(),
                                             "inputs": [{"path": str(F2_RUN / n), "sha256": sha256(F2_RUN / n)}
                                                        for n in ("thresholds.json", "injections.csv")],
                                             "nerrs_files": files, "n_rows": len(inj), "max": args.max})
    print(f"ridge done {time.perf_counter() - t0:.0f}s", flush=True)


def stage_fm(out: Path, args) -> None:
    from experiments.paper2_detect import stage_nerrs

    _require_prereg(out)
    t0 = time.perf_counter()
    params, inj = load_f2()
    triggers = pd.read_csv(out / "triggers_nerrs.csv", parse_dates=["onset"])
    sub = fm_subset(inj, triggers)
    if args.max:
        sub = sub.groupby(["kind", "sham"], sort=False).head(max(1, args.max // 9))
    frames, _ = stage_nerrs()
    sal = load_sal(set(zip(sub["station"], sub["year"])))
    fm = FM(args.model)
    rows = []
    for i, r in enumerate(sub.itertuples(index=False)):
        truth, obs, inp = prepare_nerrs(frames[(r.station, r.year)], sal.get((r.station, r.year)), r.kind, r.onset,
                                        params, r.sham, r.target)
        mechs = MECHS_SHAM_FM if r.sham else MECHS_FM
        base = {"station": r.station, "year": r.year, "kind": r.kind, "target": r.target, "onset": r.onset,
                "sham": r.sham, "split": r.split}
        rows += [base | x for x in score(args.model, fm, truth, obs, inp, r.onset, mechs)]
        if i % 20 == 0:
            print(f"{args.model} {i}/{len(sub)} ({time.perf_counter() - t0:.0f}s)", flush=True)
    _write_new(out / f"fm_subset_{args.model}.csv", sub)
    _write_new(out / f"results_{args.model}.csv", pd.DataFrame(rows))
    _write_new(out / f"manifest_{args.model}.json", {"seconds": time.perf_counter() - t0, "git_head": git_head(),
                                                     "model": fm.meta, "threads": TORCH_THREADS, "n": len(sub),
                                                     "max": args.max})
    print(f"{args.model} done {time.perf_counter() - t0:.0f}s", flush=True)


def stage_cdmo(out: Path, args) -> None:
    _require_prereg(out)
    t0 = time.perf_counter()
    params, _ = load_f2()
    frames, inputs = load_cdmo()
    print(f"cdmo loaded {len(frames)} stations ({time.perf_counter() - t0:.0f}s)", flush=True)
    fits = {}
    for st, f in frames.items():
        for var in CDMO_VARS:
            rm = fit_ridge([f[var][:CDMO_FIT_END]], cdmo_offset(st))
            if rm is not None:
                fits[(st, var)] = rm
    shams = cdmo_shams(frames, params, fits)
    if args.max:
        shams = shams.groupby("set", sort=False).head(args.max)
    print(f"ridge fits {len(fits)}, shams {len(shams)} ({time.perf_counter() - t0:.0f}s)", flush=True)
    rows, trig, prepared = [], [], []
    for i, r in enumerate(shams.itertuples(index=False)):
        truth, obs, inp = prepare_cdmo(frames[r.station], r.var, r.onset, params)
        base = {"station": r.station, "kind": r.var, "target": r.var, "set": r.set, "onset": r.onset, "sham": True,
                "split": r.split}
        info = inp.trigger_info(r.onset, origin_times(r.onset)[-1])
        trig.append(base | info)
        rows += [base | x for x in score("ridge", fits[(r.station, r.var)], truth, obs, inp, r.onset, MECHS_RIDGE)]
        if any(info[f"{v}_triggered"] for v in VARIANTS):
            prepared.append((base, truth, obs, inp, r.onset))
        if i % 100 == 0:
            print(f"cdmo ridge {i}/{len(shams)} ({time.perf_counter() - t0:.0f}s)", flush=True)
    _write_new(out / "cdmo_shams.csv", shams)
    _write_new(out / "cdmo_triggers.csv", pd.DataFrame(trig))
    _write_new(out / "results_cdmo_ridge.csv", pd.DataFrame(rows))
    for name in ("bolt", "chronos2"):
        fm = FM(name)
        frows = []
        for base, truth, obs, inp, onset in prepared:
            frows += [base | x for x in score(name, fm, truth, obs, inp, onset, MECHS_SHAM_FM)]
        _write_new(out / f"results_cdmo_{name}.csv", pd.DataFrame(frows))
        print(f"cdmo {name} {len(prepared)} triggered shams ({time.perf_counter() - t0:.0f}s)", flush=True)
        del fm
    rates = cdmo_trigger_rates(frames, params)
    _write_new(out / "cdmo_trigger_rates.csv", rates)
    _write_new(out / "manifest_cdmo.json", {"seconds": time.perf_counter() - t0, "git_head": git_head(), "inputs": inputs,
                                            "stations": sorted(frames), "ridge_fits": sorted(f"{s}|{v}" for s, v in fits),
                                            "max": args.max})
    print(f"cdmo done {time.perf_counter() - t0:.0f}s", flush=True)


def stage_nb1(out: Path, _args) -> None:
    from experiments.paper2_detect import NB1_OFFSETS, NB1_TO_NERRS, nb1_detect, nb1_frame

    _require_prereg(out)
    params, _ = load_f2()
    full = nb1_frame()
    hist = paths.EXPERIMENT_OUTPUT_DIR / "sensor-history-20261024" / "06M26042804.csv"
    traj, summ, cps_rows = [], [], []
    fms = {n: FM(n) for n in ("bolt", "chronos2")}
    for name, col, t0 in NB1_EVENTS:
        onset = pd.Timestamp(t0).floor("15min")
        f = full[onset - pd.Timedelta(days=40):onset + pd.Timedelta(days=8)]
        det = nb1_detect(f, params)
        cps = change_points(changepoints_of(det)[col])
        inp = BoundedInputs(f[col], flags_of(det)[col], cps, NB1_TO_NERRS[col], NB1_OFFSETS.get(col),
                            ref=pd.DataFrame({"Temp": f["Temperature"]}))
        for i, s in enumerate(inp.assess):
            cps_rows.append({"event": name, "variable": col} | {k: s[k] for k in s if k != "k"} |
                            {f"qual_{v}": i in inp.qual[v] for v in VARIANTS})
        origins = origin_times(onset)
        y_obs = f[col].reindex(origins + pd.Timedelta(minutes=60)).to_numpy(dtype=float)
        pre = float(f[col][onset - pd.Timedelta(hours=24):onset - pd.Timedelta(minutes=15)].median())
        post = float(f[col][onset + pd.Timedelta(hours=1):onset + pd.Timedelta(hours=24)].median())
        p24 = window_mask(origins, onset, "post24")
        for mname, fm in fms.items():
            fc, _ = forecasts(mname, fm, inp, origins, ("a", "b", "c_align", "v1", "v2", "v3"))
            for mech in ("a", "b", "c_align", "v1", "v2", "v3"):
                p, lo, hi = fc[(mech, 60)]
                alo, ahi = aci_intervals(origins, lo, hi, y_obs, 60)
                for j, t in enumerate(origins):
                    traj.append({"event": name, "model": mname, "mech": mech, "origin": t, "pred_1h": p[j], "lo": lo[j],
                                 "hi": hi[j], "aci_lo": alo[j], "aci_hi": ahi[j], "obs_1h": y_obs[j]})
                ok = p24 & np.isfinite(y_obs)
                mp = float(np.nanmean(p[p24]))
                summ.append({"event": name, "variable": col, "model": mname, "mech": mech, "pre_level": pre,
                             "post_level_obs": post, "mean_pred_post24": mp,
                             "pred_over_pre": mp / pre if pre else np.nan, "pred_over_post_obs": mp / post if post else np.nan,
                             "cov_static_vs_obs_post24": float(((y_obs >= lo) & (y_obs <= hi))[ok].mean()) if ok.any() else np.nan,
                             "cov_aci_vs_obs_post24": float(((y_obs >= alo) & (y_obs <= ahi))[ok].mean()) if ok.any() else np.nan,
                             "n_cp": len(inp.assess), "n_qual_v1": len(inp.qual["v1"]), "n_qual_v2": len(inp.qual["v2"])})
    _write_new(out / "nb1_changepoints.csv", pd.DataFrame(cps_rows))
    _write_new(out / "nb1_summary.csv", pd.DataFrame(summ))
    _write_new(out / "nb1_trajectories.csv", pd.DataFrame(traj))
    _write_new(out / "manifest_nb1.json", {"git_head": git_head(), "inputs": [{"path": str(hist), "sha256": sha256(hist)}],
                                           "models": {n: m.meta for n, m in fms.items()}})


# ---------------------------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------------------------

def _reduction(lr: np.ndarray, groups: np.ndarray) -> dict:
    if not len(lr):
        return {"n": 0}
    lo, hi = _boot(lr, None)
    slo, shi = _boot(lr, groups)
    return {"n": int(len(lr)), "reduction": 1 - float(np.exp(lr.mean())), "ci_lo": 1 - float(np.exp(hi)),
            "ci_hi": 1 - float(np.exp(lo)), "station_ci_lo": 1 - float(np.exp(shi)), "station_ci_hi": 1 - float(np.exp(slo))}


def load_results(out: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """All scored rows (``set``: nerrs / cdmo_random / cdmo_event) and the sham universe per set."""
    res = []
    for m in MODELS:
        p = out / f"results_{m}.csv"
        if p.exists():
            res.append(pd.read_csv(p, parse_dates=["onset"]).assign(set="nerrs"))
        p = out / f"results_cdmo_{m}.csv"
        if p.exists() and p.stat().st_size > 2:
            res.append(pd.read_csv(p, parse_dates=["onset"]))
    res = pd.concat(res, ignore_index=True)
    res["year"] = res["year"].fillna(0).astype(int) if "year" in res else 0
    trig = pd.read_csv(out / "triggers_nerrs.csv", parse_dates=["onset"])
    uni = [trig[trig["sham"]].assign(set="nerrs")]
    if (out / "cdmo_triggers.csv").exists():
        uni.append(pd.read_csv(out / "cdmo_triggers.csv", parse_dates=["onset"]).assign(year=0))
    universe = pd.concat(uni, ignore_index=True)
    return res, universe


KEY = ["set", "station", "year", "kind", "onset", "sham"]


def summarise(res: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    """Per model x set x split x kind x sham x horizon x mech: reduction vs (a) and vs (b), coverage, recovery.
    FM sham sets: untriggered shams of the universe enter with log ratio 0 (identical input to (a))."""
    rows = []
    for (model, st, h), g in res.groupby(["model", "set", "horizon_min"], sort=False):
        a = g[g["mech"] == "a"][KEY + ["mae_post24", "mae_post7"]].rename(columns={"mae_post24": "a24", "mae_post7": "a7"})
        b = g[g["mech"] == "b"][KEY + ["mae_post24"]].rename(columns={"mae_post24": "b24"})
        m = g.merge(a, on=KEY, how="left").merge(b, on=KEY, how="left")
        for (split, kind, sham, mech), gg in m.groupby(["split", "kind", "sham", "mech"], sort=False):
            r = {"model": model, "set": st, "split": split, "kind": kind, "sham": sham, "horizon_min": h, "mech": mech,
                 "n_scored": len(gg)}
            ok = (gg["mae_post24"] > 0) & (gg["a24"] > 0)
            lr = np.log(gg.loc[ok, "mae_post24"] / gg.loc[ok, "a24"]).to_numpy()
            grp = gg.loc[ok, "station"].to_numpy()
            if sham and model != "ridge" and mech in VARIANTS:
                u = universe[(universe["set"] == st) & (universe["split"] == split) & (universe["kind"] == kind)]
                scored = set(zip(gg["station"], gg["year"], gg["onset"]))
                silent = u[[k not in scored for k in zip(u["station"], u["year"], u["onset"])]]
                lr = np.r_[lr, np.zeros(len(silent))]
                grp = np.r_[grp, silent["station"].to_numpy()]
                r["n_silent_added"] = len(silent)
            r |= {f"{k}_post24": v for k, v in _reduction(lr, grp).items()}
            ok7 = (gg["mae_post7"] > 0) & (gg["a7"] > 0)
            lr7 = np.log(gg.loc[ok7, "mae_post7"] / gg.loc[ok7, "a7"]).to_numpy()
            r["reduction_post7"] = 1 - float(np.exp(lr7.mean())) if len(lr7) else np.nan
            okb = (gg["mae_post24"] > 0) & (gg["b24"] > 0)
            lrb = np.log(gg.loc[okb, "mae_post24"] / gg.loc[okb, "b24"]).to_numpy()
            r["harm_vs_b_post24"] = float(np.exp(lrb.mean())) - 1 if len(lrb) else np.nan
            for w in ("post24", "post7"):
                r[f"cov_static_{w}"] = gg[f"cov_static_{w}"].mean()
                r[f"cov_aci_{w}"] = gg[f"cov_aci_{w}"].mean()
            r["recovered_within_24h"] = float((gg["recovery_h"] <= 24).mean())
            rows.append(r)
    # FM sham groups in which no sham triggered at all: every input equals (a)'s -> reduction exactly 0
    have = {(r["model"], r["set"], r["split"], r["kind"], r["mech"], r["horizon_min"]) for r in rows if r["sham"]}
    for model in [m for m in MODELS if m != "ridge" and m in set(res["model"])]:
        for (st, split, kind), u in universe.groupby(["set", "split", "kind"]):
            for h in HORIZONS:
                for mech in VARIANTS:
                    if (model, st, split, kind, mech, h) not in have:
                        rows.append({"model": model, "set": st, "split": split, "kind": kind, "sham": True,
                                     "horizon_min": h, "mech": mech, "n_scored": 0, "n_silent_added": len(u),
                                     "n_post24": len(u), "reduction_post24": 0.0, "ci_lo_post24": 0.0,
                                     "ci_hi_post24": 0.0, "station_ci_lo_post24": 0.0, "station_ci_hi_post24": 0.0})
    return pd.DataFrame(rows)


def _get(summ, model, st, split, kind, sham, mech, col, h=60):
    g = summ[(summ["model"] == model) & (summ["set"] == st) & (summ["split"] == split) & (summ["kind"] == kind) &
             (summ["sham"] == sham) & (summ["mech"] == mech) & (summ["horizon_min"] == h)]
    return float(g[col].iloc[0]) if len(g) and col in g and pd.notna(g[col].iloc[0]) else np.nan


def harms(summ: pd.DataFrame, model: str, split: str, mech: str) -> dict:
    s = summ[(summ["model"] == model) & (summ["split"] == split) & (summ["sham"]) & (summ["mech"] == mech) &
             (summ["horizon_min"] == 60)]
    out = {}
    nerrs = s[s["set"] == "nerrs"]
    out["f2_sham_worst"] = float((-nerrs["reduction_post24"]).max()) if len(nerrs) else np.nan
    for st in ("cdmo_random", "cdmo_event"):
        g = s[s["set"] == st]
        if len(g):  # pooled over variables, weighting by n
            lr = []
            for _, r in g.iterrows():
                lr.append((r["n_post24"], np.log(1 - r["reduction_post24"])))
            n = sum(x for x, _ in lr)
            out[st] = float(np.exp(sum(x * y for x, y in lr) / n)) - 1 if n else np.nan
        else:
            out[st] = np.nan
    return out


def select_variant(summ: pd.DataFrame) -> dict:
    cand = {}
    for v in VARIANT_ORDER:
        gains = [_get(summ, m, "nerrs", "cal", k, False, v, "reduction_post24") for m in MODELS for k in INFORMATIVE]
        hs = [h for m in MODELS for h in harms(summ, m, "cal", v).values()]
        cand[v] = {"objective": float(np.nanmin(gains)) if np.isfinite(gains).any() else np.nan,
                   "harm": float(np.nanmax(hs)) if np.isfinite(hs).any() else np.nan, "gains": gains}
    eligible = [v for v in VARIANT_ORDER if cand[v]["harm"] <= HARM_MAX]
    if eligible:
        best = max(cand[v]["objective"] for v in eligible)
        chosen = next(v for v in VARIANT_ORDER if v in eligible and cand[v]["objective"] >= best - TIE)
        note = "eligible"
    else:
        chosen = min(VARIANT_ORDER, key=lambda v: (cand[v]["harm"], -cand[v]["objective"]))
        note = "no eligible variant"
    return {"chosen": chosen, "note": note, "candidates": cand}


def verdict(summ: pd.DataFrame, variant: str, split: str = "held") -> pd.DataFrame:
    rows = []
    for m in MODELS:
        r = {"model": m, "variant": variant, "split": split}
        g1 = []
        for k in RESCALE:
            red = _get(summ, m, "nerrs", split, k, False, variant, "reduction_post24")
            lo = _get(summ, m, "nerrs", split, k, False, variant, "station_ci_lo_post24")
            r[f"G1_{k}"] = red
            r[f"G1_{k}_ci_lo"] = lo
            g1.append(bool(red >= GAIN_MIN and lo > 0))
        hs = harms(summ, m, split, variant)
        r |= {f"G2_{k}": v for k, v in hs.items()}
        g2 = [bool(np.isfinite(v) and v <= HARM_MAX) for v in hs.values()]
        g3 = []
        for k in OTHER:
            hb = _get(summ, m, "nerrs", split, k, False, variant, "harm_vs_b_post24")
            r[f"G3_{k}"] = hb
            g3.append(bool(np.isfinite(hb) and hb <= VS_B_HARM_MAX))
        r["G1"], r["G2"], r["G3"] = all(g1), all(g2), all(g3)
        r["G1_types_passing"] = int(sum(g1))
        r["pass"] = r["G1"] and r["G2"] and r["G3"]
        rows.append(r)
    return pd.DataFrame(rows)


def stage_evaluate(out: Path, _args) -> None:
    prereg = _require_prereg(out)
    res, universe = load_results(out)
    summ = summarise(res, universe)
    _write_new(out / "summary.csv", summ)
    sel = select_variant(summ)
    _write_new(out / "selection.json", sel)
    ver = pd.concat([verdict(summ, v) for v in VARIANT_ORDER] + [verdict(summ, "c_align").query("model == 'ridge'")],
                    ignore_index=True)
    ver["selected"] = ver["variant"] == sel["chosen"]
    _write_new(out / "verdict.csv", ver)
    files = sorted(p.name for p in out.iterdir())
    _write_new(out / "manifest.json", {"run": out.name, "script": prereg["script"], "git_head_prereg": prereg["git_head"],
                                       "git_head_evaluate": git_head(), "created": pd.Timestamp.now(tz="UTC").isoformat(),
                                       "outputs": files + ["manifest.json"],
                                       "output_sha256": {f: sha256(out / f) for f in files}})
    print(json.dumps(sel, indent=1, default=str))
    print(ver.round(3).T.to_string())


STAGES = {"prereg": stage_prereg, "ridge": stage_ridge, "fm": stage_fm, "cdmo": stage_cdmo, "nb1": stage_nb1,
          "evaluate": stage_evaluate}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stage", choices=list(STAGES))
    ap.add_argument("--run-name", default=RUN_NAME)
    ap.add_argument("--output", type=Path, default=None)
    ap.add_argument("--model", choices=("bolt", "chronos2"), default="bolt")
    ap.add_argument("--max", type=int, default=None, help="dry runs only")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    out = args.output or paths.EXPERIMENT_OUTPUT_DIR / args.run_name
    STAGES[args.stage](out, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
