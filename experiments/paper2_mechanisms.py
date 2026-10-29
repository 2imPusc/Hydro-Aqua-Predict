"""Paper 2 / F3: forecasting through injected sensor faults - handling mechanisms (a)-(e) compared (research-only).

PRE-REGISTRATION (fixed 2026-10-29 before any scoring run; later changes go to NOTES.md "debug"):

Scoring vs runtime (deliberate asymmetry).  Forecast error and PI coverage are scored against the CLEAN
(uninjected) value - the water, which is the answer key of the injection design.  Everything a mechanism does at
runtime (masking, change points, level shifts, online residuals, ACI feedback) uses only the FAULTED observed stream
up to the origin, because that is all a deployed system has.  Expected consequence, stated in advance: under a
persistent re-scale, mechanisms that adapt to the observed stream track the broken sensor and can score worse than
(a) against truth.  That is a finding, not a bug.

Placements.  Exactly the F2 placements and paired shams (``paper2-f2-20261028/injections.csv``; NERRS 2009-2011,
33 stations, 9 fault types, F1 parameters).  Detectors / thresholds: F2 (``thresholds.json``), causal.

Mechanisms (input to the model at origin t, built from data <= t; target variable of the fault only):
  (a) ``a``       ignore: the faulted observations as they are.
  (b) ``b``       QC mask: samples flagged by F2 ``flags`` (range | stuck | gap | drift) -> missing.
  (c) ``c``       (b) + context restart: drop everything before the latest change point detected by t
                  (F2 ``changepoints`` = step | cross on the target column; episode start - (W-1) samples).
  (c') ``c_align`` (b) + level re-alignment (pre-registered extension; RL-72: NB1 steps are multiplicative
                  re-scales of the same probe): at each change point detected by t, shift = median z[cp, alarm] -
                  median z[cp-W, cp) on the observed stream in F2 transform space (log(x + c) for positive
                  variables), subtracted from all later z; shifts accumulate.  For (c) and (c') the change point is
                  re-located causally to the split in (alarm - 2W, alarm] with the largest median difference (the
                  "episode start - (W-1)" estimate lands mid-step; found by a unit test before any scoring).
  (d) ``d``       online adaptation PROXY (not FSNet / TAFAS, which are model-specific and heavy): (a) forecast +
                  exponentially weighted mean of realised residuals (observed - forecast) at the same horizon,
                  half-life 6 h, a residual being realised at t_i + h.
  (e) ACI         delayed-feedback adaptive conformal on top of each mechanism's base interval (CQR score
                  max(lo - y, y - hi) on observed y, last 7 d of realised scores, alpha_0 = 0.2, gamma = 0.05,
                  alpha clipped to [0.001, 0.999], < 10 scores -> no widening).  Base PI80: Chronos q0.1 / q0.9;
                  ridge +- the 80 % quantile of |training residual|.  ``static`` = base interval.

Models.  ``ridge``: paper 1's shared Delta-target diurnal representation (``transfer_forecast.Series15`` /
``FEATURES``, RL-68 - the NERRS counterpart of B4D), StandardScaler + Ridge(alpha=1), fit per station x variable x
horizon on clean 2007-2008 (same split as F2); feature NaN -> 0 in training and inference; ridge inputs are
forward-filled (no limit) after masking, so ``current`` = last usable reading.  ``bolt``: Chronos-Bolt small,
zero-shot, NaN-native context of 672 samples (7 d), 2 torch threads.  Chronos-2 dropped for budget (87 ms / series
vs 45 ms) - stated, not tested.  A context with no finite value falls back to (a)'s forecast (counted).

Origins.  Hourly from onset - 48 h to onset + 48 h, then every 3 h to onset + 7 d.  Windows: warm-up
[-48 h, -24 h) (excluded), baseline [-24 h, 0), post24 [0, 24 h), post7 [24 h, 7 d).  Horizons 1 h (primary) and 6 h.

Subsets.  ridge: every F2 placement + every sham.  bolt: per fault type up to ``BOLT_PER_TYPE`` placements (at most
one per station, seeded) + ``BOLT_SHAM_PER_TYPE`` shams per type.

Metrics.  Per injection x model x mechanism x horizon: MAE in baseline / post24 / post7; recovery time = first
origin after onset at which the mean |error| of the last 6 origins <= 1.5 x baseline MAE (censored at 7 d); PI80
coverage (static and ACI) vs truth in post24 and post7.  Scale-free comparison: per-injection ratio MAE_m / MAE_a.

Success rule (handoff, made precise here).  A mechanism is USEFUL for a model if at h = 1 h its post24 MAE reduction
vs (a), 1 - geomean(ratio), is >= 30 % with a bootstrap-by-injection 95 % CI excluding 0 on >= 6 of the 8 non-gap
fault types (gap excluded: (a) and (b) see the same missing data by construction).  PI rule: an interval method
passes for a type if pooled post7 coverage (i.e. from 24 h after onset) lies in [0.75, 0.85].  Harm on shams:
geomean(ratio) - 1 on paired shams, flagged if > +5 %.  Station-cluster CIs reported as secondary.

NB1 (no truth): Chronos-Bolt only, around E1 (NH4 31/07 14:06), E3 (NH4 16/09 15:34) and pH 19/09; mean forecast
level after the event per mechanism vs the pre- and post-event observed levels, coverage vs OBSERVED.  Illustration,
not scored against RL-72's ~70 % belief.  NERRS 2021-2025 (``nerrs_cdmo/raw/726235.zip``) available, not used.

    python experiments/paper2_mechanisms.py [--run-name paper2-f3-20261029] [--output DIR]
           [--max-ridge N] [--skip-bolt] [--bolt-per-type N]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
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
from experiments.paper2_faults import git_head, inject_event  # noqa: E402

F2_RUN = paths.EXPERIMENT_OUTPUT_DIR / "paper2-f2-20261028"
MECHS = ("a", "b", "c", "c_align", "d")
HORIZONS = {60: 4, 360: 24}          # minutes -> steps
CTX = 7 * DAY
BIAS_HALFLIFE_H = 6.0
ACI_ALPHA, ACI_GAMMA, ACI_WINDOW_H, ACI_MIN = 0.2, 0.05, 7 * 24, 10
RECOVERY_FACTOR, RECOVERY_RUN = 1.5, 6
RIDGE_ALPHA = 1.0
BOLT_REPO = "amazon/chronos-bolt-small"
BOLT_PER_TYPE, BOLT_SHAM_PER_TYPE = 20, 4
TORCH_THREADS = 2
SEED = 20261029
USEFUL_REDUCTION, USEFUL_TYPES = 0.30, 6
PI_BAND = (0.75, 0.85)
WINDOWS = {"warmup": (-48, -24), "baseline": (-24, 0), "post24": (0, 24), "post7": (24, 7 * 24)}


# ---------------------------------------------------------------------------------------------
# origins and mechanism inputs (causal)
# ---------------------------------------------------------------------------------------------

def origin_times(onset: pd.Timestamp) -> pd.DatetimeIndex:
    hourly = pd.date_range(onset - pd.Timedelta(hours=48), onset + pd.Timedelta(hours=47), freq="1h")
    sparse = pd.date_range(onset + pd.Timedelta(hours=48), onset + pd.Timedelta(days=7) - pd.Timedelta(hours=1), freq="3h")
    return hourly.append(sparse)


def change_points(cp_alarm: pd.Series) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """(alarm time, change point estimate) per change-point episode; estimate = start - (W - 1) samples."""
    step = cp_alarm.index[1] - cp_alarm.index[0] if len(cp_alarm) > 1 else pd.Timedelta(minutes=15)
    return [(a, a - (W - 1) * step) for a in episodes(cp_alarm)]


class Inputs:
    """Mechanism input series for one target column; ``series(mech, t)`` uses only flags / change points <= t."""

    def __init__(self, obs: pd.Series, flags: pd.Series, cps: list, var: str, c: float | None = None):
        self.obs, self.var, self.c = obs.astype(float), var, c
        self.masked = self.obs.where(~flags.reindex(obs.index).fillna(False).astype(bool))
        self.z_obs = transform(self.obs, var, c)
        self.cps = sorted(self._refine(a, cp) for a, cp in cps)
        self._cache: dict = {}

    def _refine(self, alarm: pd.Timestamp, cp: pd.Timestamp) -> tuple:
        """Causal re-location of a change point: the split k in (alarm - 2W, alarm] maximising
        |median z(k..alarm) - median z(k-W..k-1)| on the observed stream; also returns that level shift."""
        z = self.z_obs.to_numpy()
        a = self.obs.index.get_indexer([alarm])[0]
        best = (0.0, cp, 0.0)
        for k in range(max(W, a - 2 * W + 1), a + 1):
            post, pre = z[k:a + 1], z[k - W:k]
            post, pre = post[np.isfinite(post)], pre[np.isfinite(pre)]
            if len(post) and len(pre):
                d = float(np.median(post) - np.median(pre))
                if abs(d) > best[0]:
                    best = (abs(d), self.obs.index[k], d)
        return alarm, best[1], best[2]

    def active(self, t: pd.Timestamp) -> int:
        return sum(1 for a, _, _ in self.cps if a <= t)

    def series(self, mech: str, t: pd.Timestamp) -> pd.Series:
        if mech in ("a", "d"):
            return self.obs
        if mech == "b":
            return self.masked
        k = self.active(t)
        key = (mech, k)
        if key not in self._cache:
            self._cache[key] = self._build(mech, k)
        return self._cache[key]

    def _build(self, mech: str, k: int) -> pd.Series:
        if k == 0:
            return self.masked
        if mech == "c":
            cp = self.cps[k - 1][1]
            return self.masked.where(self.masked.index >= cp)
        z = transform(self.masked, self.var, self.c).copy()
        for _, cp, shift in self.cps[:k]:
            z.iloc[z.index.searchsorted(cp):] -= shift
        if VAR_CFG[self.var]["log"]:
            c = VAR_CFG[self.var]["c"] if self.c is None else self.c
            return np.exp(z) - c
        return z


# ---------------------------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------------------------

class RidgeModel:
    """Per station x variable x horizon ridge on the shared Delta representation (transfer_forecast)."""

    def __init__(self, utc_offset_h: float):
        self.offset = utc_offset_h
        self.fits: dict = {}

    def _series(self, values: pd.Series):
        from experiments.transfer_forecast import Series15

        start = values.index[0]
        return Series15(values.to_numpy(dtype=float), values.to_numpy(dtype=float),
                        (start - pd.Timedelta(hours=self.offset)).tz_localize("UTC"), self.offset)

    def fit(self, clean: list[pd.Series], horizon: int) -> None:
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        from experiments.transfer_forecast import FEATURES

        rows = pd.concat([self._series(s).training_rows(horizon) for s in clean if s.notna().sum() > 30 * DAY],
                         ignore_index=True)
        X = rows[FEATURES].fillna(0.0).to_numpy()
        y = rows["delta"].to_numpy()
        model = make_pipeline(StandardScaler(), Ridge(alpha=RIDGE_ALPHA)).fit(X, y)
        q80 = float(np.quantile(np.abs(y - model.predict(X)), 0.8))
        self.fits[horizon] = (model, q80)

    def predict(self, values: pd.Series, origins: pd.DatetimeIndex, horizon: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        from experiments.transfer_forecast import FEATURES

        model, q80 = self.fits[horizon]
        ser = self._series(values.ffill())
        idx = values.index.get_indexer(origins)
        feat = ser.features(idx, horizon)
        pred = feat["current"].to_numpy() + model.predict(feat[FEATURES].fillna(0.0).to_numpy())
        return pred, pred - q80, pred + q80


class BoltModel:
    def __init__(self, threads: int = TORCH_THREADS):
        import torch
        from chronos import BaseChronosPipeline

        torch.set_num_threads(threads)
        self.torch = torch
        self.pipe = BaseChronosPipeline.from_pretrained(BOLT_REPO, device_map="cpu", torch_dtype=torch.float32)

    def quantiles(self, contexts: np.ndarray, batch: int = 64) -> np.ndarray:
        """contexts (n, CTX) -> (n, 24, 3) quantiles 0.1 / 0.5 / 0.9 for steps 1..24."""
        out = []
        for i in range(0, len(contexts), batch):
            q, _ = self.pipe.predict_quantiles(self.torch.tensor(contexts[i:i + batch], dtype=self.torch.float32),
                                               prediction_length=24, quantile_levels=[0.1, 0.5, 0.9])
            out.append(q.float().numpy())
        return np.concatenate(out) if out else np.zeros((0, 24, 3))


def contexts_for(values: pd.Series, origins: pd.DatetimeIndex) -> np.ndarray:
    arr = values.to_numpy(dtype=float)
    pos = values.index.get_indexer(origins)
    out = np.full((len(origins), CTX), np.nan)
    for i, p in enumerate(pos):
        lo = max(0, p - CTX + 1)
        seg = arr[lo:p + 1]
        out[i, CTX - len(seg):] = seg
    return out


# ---------------------------------------------------------------------------------------------
# online post-processing: (d) bias proxy, (e) ACI
# ---------------------------------------------------------------------------------------------

def _hours(t: pd.DatetimeIndex) -> np.ndarray:
    return np.asarray(t.asi8, dtype=float) / 3.6e12


def online_bias(origins: pd.DatetimeIndex, pred: np.ndarray, obs_future: np.ndarray, horizon_min: int,
                halflife_h: float = BIAS_HALFLIFE_H) -> np.ndarray:
    """EW mean of residuals realised (t_i + h <= t) before each origin t; 0 when none."""
    t = _hours(origins)
    real_t = t + horizon_min / 60
    resid = obs_future - pred
    fin = np.isfinite(resid)
    bias = np.zeros(len(origins))
    for j in range(len(t)):
        ok = (real_t <= t[j]) & fin
        if ok.any():
            w = 0.5 ** ((t[j] - real_t[ok]) / halflife_h)
            bias[j] = float(np.sum(w * resid[ok]) / np.sum(w))
    return bias


def aci_intervals(origins: pd.DatetimeIndex, lo: np.ndarray, hi: np.ndarray, obs_future: np.ndarray, horizon_min: int,
                  alpha0: float = ACI_ALPHA, gamma: float = ACI_GAMMA, window_h: float = ACI_WINDOW_H,
                  min_scores: int = ACI_MIN) -> tuple[np.ndarray, np.ndarray]:
    """Delayed-feedback ACI widening of [lo, hi]; feedback from observed y at t_i + h <= t, in realisation order."""
    t = _hours(origins)
    real_t = t + horizon_min / 60
    score = np.maximum(lo - obs_future, obs_future - hi)
    order = np.argsort(real_t, kind="stable")
    alpha, done = alpha0, 0
    used = np.zeros(len(t), dtype=bool)
    q = np.zeros(len(t))
    for j in range(len(t)):
        while done < len(order) and real_t[order[done]] <= t[j]:
            i = order[done]
            done += 1
            if not np.isfinite(score[i]):
                continue
            covered = score[i] <= q[i]
            alpha = float(np.clip(alpha + gamma * (alpha0 - (0.0 if covered else 1.0)), 0.001, 0.999))
            used[i] = True
        recent = used & (real_t > t[j] - window_h)
        n = int(recent.sum())
        q[j] = float(np.quantile(score[recent], min(1.0, (1 - alpha) * (1 + 1 / n)))) if n >= min_scores else 0.0
    return lo - q, hi + q


# ---------------------------------------------------------------------------------------------
# per injection
# ---------------------------------------------------------------------------------------------

def window_mask(origins: pd.DatetimeIndex, onset: pd.Timestamp, name: str) -> np.ndarray:
    a, b = WINDOWS[name]
    rel = (origins - onset) / pd.Timedelta(hours=1)
    return np.asarray((rel >= a) & (rel < b))


def recovery_hours(origins: pd.DatetimeIndex, err: np.ndarray, onset: pd.Timestamp, base_mae: float) -> float:
    post = np.flatnonzero(np.asarray(origins >= onset))
    if not np.isfinite(base_mae) or not len(post):
        return np.nan
    for k in range(len(post)):
        run = err[post[max(0, k - RECOVERY_RUN + 1):k + 1]]
        run = run[np.isfinite(run)]
        if len(run) >= min(RECOVERY_RUN, k + 1) and len(run) and run.mean() <= RECOVERY_FACTOR * base_mae:
            return float((origins[post[k]] - onset) / pd.Timedelta(hours=1))
    return 7 * 24.0


def prepare(frame: pd.DataFrame, kind: str, onset: pd.Timestamp, params: dict, sham: bool, target: str):
    win = frame[onset - pd.Timedelta(days=40):onset + pd.Timedelta(days=8)]
    faulted, _ = inject_event(win, fault_specs(kind, win, onset), onset)
    obs = win if sham else faulted
    det = detect(obs, params)
    cps = change_points(changepoints_of(det)[target])
    inputs = Inputs(obs[target], flags_of(det)[target], cps, target)
    return win[target], obs[target], inputs, len(cps)


def forecasts(model_name: str, model, inputs: Inputs, origins: pd.DatetimeIndex) -> dict:
    """{(mech, horizon): (pred, lo, hi, fallback count)} for mechanisms a, b, c, c_align."""
    out = {}
    for mech in ("a", "b", "c", "c_align"):
        groups: dict = {}
        for j, t in enumerate(origins):
            key = 0 if mech in ("a", "b") else inputs.active(t)
            groups.setdefault(key, []).append(j)
        res = {h: [np.full(len(origins), np.nan) for _ in range(3)] for h in HORIZONS}
        for key, js in groups.items():
            ser = inputs.series(mech, origins[js[-1]])
            o = origins[js]
            if model_name == "ridge":
                for h in HORIZONS:
                    p, lo, hi = model.predict(ser, o, h)
                    for arr, v in zip(res[h], (p, lo, hi)):
                        arr[js] = v
            else:
                ctx = contexts_for(ser, o)
                q = model.quantiles(ctx)
                for h, s in HORIZONS.items():
                    for arr, col in zip(res[h], (1, 0, 2)):
                        arr[js] = q[:, s - 1, col]
                none = ~np.isfinite(ctx).any(axis=1)
                for h in HORIZONS:
                    for arr in res[h]:
                        arr[np.asarray(js)[none]] = np.nan
        for h in HORIZONS:
            out[(mech, h)] = res[h]
    # fallback: missing forecast -> (a)'s
    fallbacks = {}
    for (mech, h), (p, lo, hi) in out.items():
        bad = ~np.isfinite(p)
        fallbacks[(mech, h)] = int(bad.sum())
        if mech != "a" and bad.any():
            pa, la, ha = out[("a", h)]
            p[bad], lo[bad], hi[bad] = pa[bad], la[bad], ha[bad]
    return out, fallbacks


def score_one(model_name: str, model, frame: pd.DataFrame, kind: str, target: str, onset: pd.Timestamp,
              params: dict, sham: bool) -> list[dict]:
    truth, obs, inputs, n_cp = prepare(frame, kind, onset, params, sham, target)
    origins = origin_times(onset)
    fc, fallbacks = forecasts(model_name, model, inputs, origins)
    rows = []
    for h, steps in HORIZONS.items():
        tgt = origins + pd.Timedelta(minutes=h)
        y_true = truth.reindex(tgt).to_numpy(dtype=float)
        y_obs = obs.reindex(tgt).to_numpy(dtype=float)
        pa = fc[("a", h)]
        variants = {m: fc[(m, h)] for m in ("a", "b", "c", "c_align")}
        bias = online_bias(origins, pa[0], y_obs, h)
        variants["d"] = (pa[0] + bias, pa[1] + bias, pa[2] + bias)
        for mech, (p, lo, hi) in variants.items():
            alo, ahi = aci_intervals(origins, lo, hi, y_obs, h)
            err = np.abs(p - y_true)
            row = {"kind": kind, "target": target, "onset": onset, "sham": sham, "model": model_name, "mech": mech,
                   "horizon_min": h, "n_cp": n_cp, "fallbacks": fallbacks.get((mech, h), 0)}
            for w in WINDOWS:
                m = window_mask(origins, onset, w) & np.isfinite(err)
                row[f"mae_{w}"] = float(err[m].mean()) if m.any() else np.nan
                row[f"n_{w}"] = int(m.sum())
                inside = np.isfinite(y_true) & window_mask(origins, onset, w)
                row[f"cov_static_{w}"] = float(((y_true >= lo) & (y_true <= hi))[inside].mean()) if inside.any() else np.nan
                row[f"cov_aci_{w}"] = float(((y_true >= alo) & (y_true <= ahi))[inside].mean()) if inside.any() else np.nan
                row[f"width_aci_{w}"] = float((ahi - alo)[inside].mean()) if inside.any() else np.nan
            row["recovery_h"] = recovery_hours(origins, err, onset, row["mae_baseline"])
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------------------------
# summaries
# ---------------------------------------------------------------------------------------------

def _boot(values: np.ndarray, groups: np.ndarray | None, n: int = 2000, seed: int = SEED) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    v = np.asarray(values, dtype=float)
    if groups is None:
        stats = [np.mean(v[rng.integers(0, len(v), len(v))]) for _ in range(n)]
    else:
        ug = pd.unique(groups)
        idx = {g: np.flatnonzero(groups == g) for g in ug}
        stats = []
        for _ in range(n):
            pick = rng.choice(ug, len(ug))
            stats.append(np.mean(np.concatenate([v[idx[g]] for g in pick])))
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def summarise(res: pd.DataFrame) -> pd.DataFrame:
    """Per model x kind x mechanism x horizon: reduction vs (a) in post24 / post7, CIs, recovery, coverage."""
    key = ["model", "station", "year", "kind", "onset", "sham", "horizon_min"]
    a = res[res["mech"] == "a"][key + ["mae_post24", "mae_post7"]].rename(columns={"mae_post24": "a24", "mae_post7": "a7"})
    m = res.merge(a, on=key)
    rows = []
    for (model, kind, sham, h, mech), g in m.groupby(["model", "kind", "sham", "horizon_min", "mech"], sort=False):
        r = {"model": model, "kind": kind, "sham": sham, "horizon_min": h, "mech": mech, "n": len(g)}
        for w, col in (("post24", "a24"), ("post7", "a7")):
            ok = (g[f"mae_{w}"] > 0) & (g[col] > 0)
            lr = np.log(g.loc[ok, f"mae_{w}"] / g.loc[ok, col]).to_numpy()
            if len(lr):
                r[f"reduction_{w}"] = 1 - float(np.exp(lr.mean()))
                lo, hi = _boot(lr, None)
                r[f"reduction_{w}_ci_lo"], r[f"reduction_{w}_ci_hi"] = 1 - np.exp(hi), 1 - np.exp(lo)
                slo, shi = _boot(lr, g.loc[ok, "station"].to_numpy())
                r[f"reduction_{w}_station_ci_lo"], r[f"reduction_{w}_station_ci_hi"] = 1 - np.exp(shi), 1 - np.exp(slo)
        r["recovery_h_median"] = g["recovery_h"].median()
        r["recovered_within_24h"] = float((g["recovery_h"] <= 24).mean())
        for w in ("post24", "post7"):
            r[f"cov_static_{w}"] = g[f"cov_static_{w}"].mean()
            r[f"cov_aci_{w}"] = g[f"cov_aci_{w}"].mean()
        r["mae_baseline_median"] = g["mae_baseline"].median()
        r["mae_post24_median"] = g["mae_post24"].median()
        rows.append(r)
    return pd.DataFrame(rows)


def verdict(summ: pd.DataFrame) -> pd.DataFrame:
    rows = []
    s = summ[(~summ["sham"]) & (summ["horizon_min"] == 60) & (summ["kind"] != "gap")]
    for (model, mech), g in s.groupby(["model", "mech"]):
        ok = (g["reduction_post24"] >= USEFUL_REDUCTION) & (g["reduction_post24_ci_lo"] > 0)
        sh = summ[(summ["sham"]) & (summ["horizon_min"] == 60) & (summ["model"] == model) & (summ["mech"] == mech)]
        harm = float((-sh["reduction_post24"]).max()) if len(sh) else np.nan
        rows.append({"model": model, "mech": mech, "types_passing": int(ok.sum()), "types": int(len(g)),
                     "passing": ", ".join(g.loc[ok, "kind"]), "useful": bool(ok.sum() >= USEFUL_TYPES),
                     "worst_sham_harm": harm, "sham_harm_flag": bool(harm > 0.05) if np.isfinite(harm) else None})
    for model in summ["model"].unique():
        for mech in MECHS:
            for kind_pi in ("static", "aci"):
                g = summ[(~summ["sham"]) & (summ["horizon_min"] == 60) & (summ["kind"] != "gap") &
                         (summ["model"] == model) & (summ["mech"] == mech)]
                inband = g[f"cov_{kind_pi}_post7"].between(*PI_BAND)
                rows.append({"model": model, "mech": f"{mech}+{kind_pi}_PI", "types_passing": int(inband.sum()),
                             "types": int(len(g)), "passing": ", ".join(g.loc[inband, "kind"]),
                             "useful": bool(inband.sum() >= USEFUL_TYPES)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------
# NB1 illustration (no truth)
# ---------------------------------------------------------------------------------------------

NB1_EVENTS = (("E1_NH4", "NH4", "2026-07-31 14:06"), ("E3_NH4", "NH4", "2026-09-16 15:34"), ("D1_pH", "pH", "2026-09-19 10:22"))


def nb1_illustration(model: "BoltModel", params: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    from experiments.paper2_detect import NB1_OFFSETS, NB1_TO_NERRS, nb1_detect, nb1_frame

    full = nb1_frame()
    traj, summ = [], []
    for name, col, t0 in NB1_EVENTS:
        onset = pd.Timestamp(t0).floor("15min")
        # same window as the NERRS injections: detectors / change points from onset - 40 d only
        f = full[onset - pd.Timedelta(days=40):onset + pd.Timedelta(days=8)]
        det = nb1_detect(f, params)
        cps = change_points(changepoints_of(det)[col])
        inputs = Inputs(f[col], flags_of(det)[col], cps, NB1_TO_NERRS[col], NB1_OFFSETS.get(col))
        origins = origin_times(onset)
        fc, _ = forecasts("bolt", model, inputs, origins)
        y_obs = f[col].reindex(origins + pd.Timedelta(minutes=60)).to_numpy(dtype=float)
        pre = float(f[col][onset - pd.Timedelta(hours=24):onset - pd.Timedelta(minutes=15)].median())
        post = float(f[col][onset + pd.Timedelta(hours=1):onset + pd.Timedelta(hours=24)].median())
        pa = fc[("a", 60)]
        bias = online_bias(origins, pa[0], y_obs, 60)
        variants = {m: fc[(m, 60)] for m in ("a", "b", "c", "c_align")}
        variants["d"] = (pa[0] + bias, pa[1] + bias, pa[2] + bias)
        p24 = window_mask(origins, onset, "post24")
        for mech, (p, lo, hi) in variants.items():
            alo, ahi = aci_intervals(origins, lo, hi, y_obs, 60)
            for j, t in enumerate(origins):
                traj.append({"event": name, "mech": mech, "origin": t, "pred_1h": p[j], "lo": lo[j], "hi": hi[j],
                             "aci_lo": alo[j], "aci_hi": ahi[j], "obs_1h": y_obs[j]})
            ok = p24 & np.isfinite(y_obs)
            summ.append({"event": name, "variable": col, "mech": mech, "pre_level": pre, "post_level_obs": post,
                         "mean_pred_post24": float(np.nanmean(p[p24])),
                         "pred_over_pre": float(np.nanmean(p[p24]) / pre) if pre else np.nan,
                         "pred_over_post_obs": float(np.nanmean(p[p24]) / post) if post else np.nan,
                         "cov_static_vs_obs_post24": float(((y_obs >= lo) & (y_obs <= hi))[ok].mean()),
                         "cov_aci_vs_obs_post24": float(((y_obs >= alo) & (y_obs <= ahi))[ok].mean()),
                         "n_cp_detected": len(cps)})
    return pd.DataFrame(traj), pd.DataFrame(summ)


# ---------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------

def bolt_subset(inj: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    picks = []
    for kind, g in inj[~inj["sham"]].groupby("kind", sort=False):
        g = g.iloc[rng.permutation(len(g))].drop_duplicates("station").head(BOLT_PER_TYPE)
        picks.append(g)
        sh = inj[inj["sham"] & (inj["kind"] == kind)]
        sh = sh.iloc[rng.permutation(len(sh))].head(BOLT_SHAM_PER_TYPE)
        picks.append(sh)
    return pd.concat(picks)


def main(argv: list[str] | None = None) -> int:
    from experiments import nerrs_multi as nm
    from experiments.paper2_detect import stage_nerrs

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-name", default="paper2-f3-20261029")
    ap.add_argument("--output", type=Path, default=None)
    ap.add_argument("--max-ridge", type=int, default=None, help="dry runs: first N placements (+ shams)")
    ap.add_argument("--skip-bolt", action="store_true")
    ap.add_argument("--bolt-per-type", type=int, default=BOLT_PER_TYPE)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    out = args.output or paths.EXPERIMENT_OUTPUT_DIR / args.run_name
    out.mkdir(parents=True, exist_ok=False)
    t0 = time.perf_counter()

    params = json.loads((F2_RUN / "thresholds.json").read_text(encoding="utf-8"))["params"]
    inj = pd.read_csv(F2_RUN / "injections.csv", parse_dates=["onset"])[["station", "year", "kind", "target", "onset", "sham"]]
    if args.max_ridge:
        keep = inj[~inj["sham"]].groupby("kind", sort=False).head(max(1, args.max_ridge // 9))
        inj = inj.merge(keep[["station", "year", "kind", "onset"]], on=["station", "year", "kind", "onset"])
    stations = sorted(inj["station"].unique())
    frames, files = stage_nerrs()
    offset = {f"{r.code}{c}": r.utc_offset_h for r in nm.RESERVES.values() for c in r.wq_stations}
    print(f"staged {len(frames)} station-years, {len(inj)} injection rows, {time.perf_counter() - t0:.0f}s", flush=True)

    # --- ridge: fit per station x variable x horizon on clean 2007-2008 ---
    models: dict = {}
    for st in stations:
        for var in ("DO_mgl", "Turb", "pH"):
            clean = [frames[(st, y)][var] for y in (2007, 2008) if (st, y) in frames]
            if not clean or sum(s.notna().sum() for s in clean) < 60 * DAY:
                continue
            rm = RidgeModel(offset[st])
            for h in HORIZONS:
                rm.fit(clean, h)
            models[(st, var)] = rm
    print(f"ridge fits {len(models)} ({time.perf_counter() - t0:.0f}s)", flush=True)

    rows, skipped = [], []
    for i, r in enumerate(inj.itertuples(index=False)):
        rm = models.get((r.station, r.target))
        if rm is None:
            skipped.append({"station": r.station, "kind": r.kind, "onset": r.onset, "sham": r.sham, "reason": "no_ridge_fit"})
            continue
        for row in score_one("ridge", rm, frames[(r.station, r.year)], r.kind, r.target, r.onset, params, r.sham):
            rows.append({"station": r.station, "year": r.year} | row)
        if i % 200 == 0:
            print(f"ridge {i}/{len(inj)} ({time.perf_counter() - t0:.0f}s)", flush=True)
    res = pd.DataFrame(rows)
    res.to_csv(out / "results_ridge.csv", index=False)

    if not args.skip_bolt:
        bolt = BoltModel()
        sub = bolt_subset(inj)
        if args.bolt_per_type != BOLT_PER_TYPE:
            sub = sub.groupby(["kind", "sham"], sort=False).head(args.bolt_per_type)
        sub.to_csv(out / "bolt_subset.csv", index=False)
        brows = []
        for i, r in enumerate(sub.itertuples(index=False)):
            for row in score_one("bolt", bolt, frames[(r.station, r.year)], r.kind, r.target, r.onset, params, r.sham):
                brows.append({"station": r.station, "year": r.year} | row)
            if i % 20 == 0:
                print(f"bolt {i}/{len(sub)} ({time.perf_counter() - t0:.0f}s)", flush=True)
        bres = pd.DataFrame(brows)
        bres.to_csv(out / "results_bolt.csv", index=False)
        res = pd.concat([res, bres], ignore_index=True)
        traj, nb1 = nb1_illustration(bolt, params)
        traj.to_csv(out / "nb1_trajectories.csv", index=False)
        nb1.to_csv(out / "nb1_summary.csv", index=False)
        print(nb1.round(3).to_string(index=False), flush=True)

    summ = summarise(res)
    summ.to_csv(out / "summary.csv", index=False)
    ver = verdict(summ)
    ver.to_csv(out / "verdict.csv", index=False)
    pd.DataFrame(skipped).to_csv(out / "skipped.csv", index=False)
    cols = ["model", "kind", "horizon_min", "mech", "n", "reduction_post24", "reduction_post24_ci_lo",
            "reduction_post24_ci_hi", "reduction_post7", "recovery_h_median", "cov_static_post7", "cov_aci_post7"]
    print(summ[(~summ["sham"]) & (summ["horizon_min"] == 60)][cols].round(3).to_string(index=False), flush=True)
    print(ver.to_string(index=False), flush=True)

    hist = paths.EXPERIMENT_OUTPUT_DIR / "sensor-history-20261024" / "06M26042804.csv"
    manifest = {"run": out.name, "script": "experiments/paper2_mechanisms.py", "git_head": git_head(),
                "created": pd.Timestamp.now(tz="UTC").isoformat(), "seconds": time.perf_counter() - t0,
                "args": {k: str(v) for k, v in vars(args).items()},
                "inputs": [{"path": str(p), "sha256": sha256(p)} for p in
                           (F2_RUN / "thresholds.json", F2_RUN / "injections.csv", hist)],
                "nerrs_files": files, "bolt_repo": BOLT_REPO, "torch_threads": TORCH_THREADS,
                "outputs": sorted(p.name for p in out.iterdir())}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"done in {time.perf_counter() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
