"""H4.6 -- direction-4 spatial reliability at several time scales, as threshold-class
agreement, against causal climatology and persistence baselines.

Question: at hourly scale almost nothing transfers between sondes (RL-20..RL-24:
tides, diurnal heating). Does an anchor sensor become usable for another location
at *daily* scale and/or as *aquaculture threshold classes* -- the resolution an
advisory actually needs -- and does it beat what the target's own history gives?

Inputs (no downloads): the four foreign hourly datasets, loaded with each
dataset's own loader/QC, and the ordered pair lists (``pairs.csv``: km, distance
bin, salinity regime, overlap days) of the hourly runs:

=========  ==========================================  =============================  ===========
dataset    loader                                      hourly run                     eligibility
=========  ==========================================  =============================  ===========
nerrs      ``nerrs_multi.load_wq_hourly`` 2007-2011    nerrs-multi-h4-reliability-…   >= 365 d, no vertical pairs
mddnr      ``mddnr_load.load_hourly`` 2004-2009        mddnr-h4-reliability-…         >= 90 d (seasonal)
twdb       ``twdb_load.load_hourly`` 2008-2019         twdb-h4-reliability-…          >= 365 d
usgs       ``usgs_load.build_hourly`` WY2018-2025      usgs-sfbay-h4-reliability-…    >= 365 d
=========  ==========================================  =============================  ===========

NERRS is evaluated as one pooled dataset (bootstrap block = (reserve, day)), as
``nerrs_pooled`` in the hourly run. USGS hours are shifted UTC -> LST (UTC-8)
before any day grouping, as in the hourly run.

Scales (all from the pair's *joint* hours, i.e. hours where anchor and target
both have a QC-good hourly value):

* ``hourly``      -- the hourly protocol itself (reproduces the hourly cells).
* ``daily_mean`` / ``daily_min`` / ``daily_max`` -- statistic over the joint
  hours of a calendar day; a day counts only with >= 18 joint hours.
* ``weekly_mean`` -- mean of the daily means over a non-overlapping ISO week
  (Monday-Sunday) with >= 5 valid days. Bootstrap block = week; the gate needs
  >= 30 weeks (not 30 days).

Estimators (``transfer_or_baseline``):

* ``raw``           anchor value (same statistic over the same hours).
* ``calibrated``    hourly OLS map a + b*anchor fitted on the pair's strictly-past
  30 days (>= 240 joint hours; ``nerrs_reliability.rolling_linear_transfer``),
  then aggregated like the target. A day is calibrated only if *every* joint
  hour of it has a calibrated estimate (so obs is identical to ``raw``).
* ``climatology``   target's own calendar-month mean of the same-scale statistic
  over strictly previous years (>= 10 days of that month in those years); at
  hourly scale the month mean of hourly values. Causal: the first year of each
  station has no climatology.
* ``persistence_1d`` / ``persistence_7d`` -- target's own value 24 h / 168 h
  earlier (hourly), its own daily statistic 1 / 7 days earlier (daily scales; the
  target daily statistic needs >= 18 of its own hours). Weekly scale: only
  ``persistence_7d`` (the mean of the daily means 7 days earlier, i.e. the
  previous week).

Metrics:

* ``value`` -- |estimate - obs| within tolerance (Temp 0.5 C, Sal 1 psu, DO 0.5
  mg/L, pH 0.2, Turb max(2 NTU, 20 %); ``nerrs_reliability.within_tolerance``).
* ``class`` -- estimate and obs fall in the same aquaculture class (ok / caution /
  bad; see ``CLASS_RULES``). Reported with Cohen's kappa (pooled 3x3 matrix),
  base rate of the bad class, and the miss rate of the bad class
  (obs bad, estimate not bad). Turbidity has no class: the cobia table has TSS
  in mg/L, not NTU.

Gates: share = pooled within/agree count over units; 95 % CI by block bootstrap
(500, seed 20261016, blocks = day, (reserve, day) for NERRS, ISO week for the
weekly scale); gate g passes if lower bound >= g and >= 30 blocks.

Radius (``radius.csv``), per dataset x var x regime x scale x metric x transfer x
gate: walk 0-2, 2-5, 5-10, 10-20, 20-30 km; a bin with no pair is skipped; a
populated bin that passes extends the radius to its upper edge; the walk stops at
the first populated bin that fails *or* is insufficient. Radius 0 = the first
populated bin fails; NaN = the first populated bin is insufficient or no bin is
populated. ``>30`` km is reported in cells.csv only.

Supports: ``own`` = every unit where that estimator exists; ``common`` = units
where *all* estimators of the scale exist (used by ``baseline_compare.csv`` so
coverage cannot confound the anchor-vs-baseline comparison).

Run:  .venv\\Scripts\\python experiments\\h4_multiscale.py [--datasets usgs twdb nerrs mddnr]
Outputs: artifacts/experiments/h4-multiscale-20261017/ (write-once).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import paths  # noqa: E402
from experiments.nerrs_reliability import (  # noqa: E402
    bootstrap_share,
    bootstrap_share_difference,
    gate_status,
    rolling_linear_transfer,
    sha256,
    within_tolerance,
)

RUN_NAME = "h4-multiscale-20261017"
GATES = (0.80, 0.90, 0.95)
MIN_BLOCKS = 30
N_BOOT = 500
SEED = 20261016
MIN_DAY_HOURS = 18
MIN_WEEK_DAYS = 5
CLIM_MIN_DAYS = 10
CAL_WINDOW, CAL_MIN_HOURS = "30D", 240
BIN_LABELS = ("0-2", "2-5", "5-10", "10-20", "20-30", ">30")
RADIUS_BINS = BIN_LABELS[:-1]
BIN_UPPER_KM = {"0-2": 2.0, "2-5": 5.0, "5-10": 10.0, "10-20": 20.0, "20-30": 30.0}
VARS = ("Temp", "Sal", "DO", "pH", "Turb")
TOL_KEY = {"Temp": "Temp", "Sal": "Sal", "DO": "DO_mgl", "pH": "pH", "Turb": "Turb"}
SCALES = ("hourly", "daily_mean", "daily_min", "daily_max", "weekly_mean")
TRANSFERS = ("raw", "calibrated")
BASELINES = ("climatology", "persistence_1d", "persistence_7d")
METHODS = TRANSFERS + BASELINES
CONF_COLS = tuple(f"c{i}" for i in range(9))  # index = 3 * obs_class + est_class
COUNT_COLS = ("n", "w", "sae") + CONF_COLS

# ---------------------------------------------------------------- aquaculture classes
# 0 = ok, 1 = caution, 2 = bad. Sources:
#   cobia = paths.COBIA_THRESHOLDS (hap_shared/thresholds/cobia_thresholds.json, piecewise score)
#   alerts = core/alerts.py DO profile (watch 5.0, warning 4.0, emergency 3.0 mg/L)
#   QCVN = core/config.QCVN10_B1 (QCVN 10:2023/BTNMT B1: pH 6.5-8.5, Temperature max 30 C)
CLASS_RULES = {
    "DO": {"bad": "< 4.0", "caution": "4.0-<5.0", "ok": ">= 5.0",
           "source": "cobia score 0.5 at 4, 1.0 from 5; core/alerts.py warning 4.0 / watch 5.0. "
                     "Cobia supersaturation penalty (> 8 mg/L) ignored."},
    "Temp": {"bad": "< 18 or > 33", "caution": "18-<25 or >30-33", "ok": "25-30",
             "source": "cobia score: optimal 25-30 (1.0), 0.5 at 18 and 33; QCVN B1 max 30 = ok/caution edge."},
    "Sal": {"bad": "< 15", "caution": "15-<26 or > 32", "ok": "26-32",
            "source": "cobia score: 0 below 15, optimal 26-32 (1.0). QCVN B1 has no salinity limit."},
    "pH": {"bad": "< 7.0 or > 8.5", "caution": "7.0-<7.5 or >8.2-8.5", "ok": "7.5-8.2",
           "source": "cobia score 0.5 at 7.0 and 8.5, optimal 7.5-8.2; QCVN B1 6.5-8.5 (upper edge = bad edge)."},
    "Turb": {"source": "no class: cobia/QCVN give TSS in mg/L, turbidity is NTU/FNU."},
}


def classify(var: str, values) -> np.ndarray:
    """Class code per value (0 ok, 1 caution, 2 bad, -1 missing or no class for the variable)."""
    v = np.asarray(values, dtype=float)
    out = np.full(v.shape, -1, dtype=np.int8)
    ok = np.isfinite(v)
    if var == "DO":
        cls = np.where(v < 4.0, 2, np.where(v < 5.0, 1, 0))
    elif var == "Temp":
        cls = np.where((v < 18.0) | (v > 33.0), 2, np.where((v < 25.0) | (v > 30.0), 1, 0))
    elif var == "Sal":
        cls = np.where(v < 15.0, 2, np.where((v < 26.0) | (v > 32.0), 1, 0))
    elif var == "pH":
        cls = np.where((v < 7.0) | (v > 8.5), 2, np.where((v < 7.5) | (v > 8.2), 1, 0))
    else:
        return out
    out[ok] = cls[ok]
    return out


def cobia_breakpoints(path: Path = paths.COBIA_THRESHOLDS) -> dict:
    """Cobia score breakpoints {var: [(x, score), ...]} -- used to check CLASS_RULES against the table."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    names = {"DO": "DO", "Temp": "Temperature", "Sal": "Salinity", "pH": "pH"}
    return {k: [tuple(p) for p in raw[v]["breakpoints"]] for k, v in names.items()}


def kappa_from_conf(conf) -> float:
    """Cohen's kappa from a flattened 3x3 confusion vector (row = obs, column = estimate)."""
    m = np.asarray(conf, dtype=float).reshape(3, 3)
    total = m.sum()
    if total == 0:
        return np.nan
    po = np.trace(m) / total
    pe = float((m.sum(1) * m.sum(0)).sum()) / total ** 2
    return float((po - pe) / (1 - pe)) if pe < 1 - 1e-12 else np.nan


def class_summary(conf) -> dict:
    m = np.asarray(conf, dtype=float).reshape(3, 3)
    total = m.sum()
    n_bad = m[2].sum()
    est_bad = m[:, 2].sum()
    return {"kappa": kappa_from_conf(conf), "n_bad": int(n_bad),
            "bad_base_rate": float(n_bad / total) if total else np.nan,
            "bad_miss_rate": float((n_bad - m[2, 2]) / n_bad) if n_bad else np.nan,
            "bad_false_alarm_rate": float((est_bad - m[2, 2]) / est_bad) if est_bad else np.nan,
            "majority_class_share": float(m.sum(1).max() / total) if total else np.nan}


# ---------------------------------------------------------------- baselines
def monthly_climatology(series: pd.Series, min_days: int = CLIM_MIN_DAYS) -> pd.Series:
    """Per timestamp: mean of ``series`` in the same calendar month over strictly earlier years.

    NaN unless those earlier years hold values on >= ``min_days`` distinct days of that month.
    """
    s = series.dropna()
    if s.empty:
        return pd.Series(np.nan, index=series.index)
    idx = pd.DatetimeIndex(s.index)
    frame = pd.DataFrame({"y": idx.year, "m": idx.month, "v": s.to_numpy(), "d": idx.normalize()})
    g = frame.groupby(["m", "y"]).agg(sum=("v", "sum"), cnt=("v", "size"), days=("d", "nunique")).reset_index()
    g = g.sort_values(["m", "y"])
    # every (month, year) in the series index, incl. years with no data of that month
    full = pd.DatetimeIndex(series.index)
    keys = pd.DataFrame({"m": full.month, "y": full.year})
    # prior totals for (m, y) = cumulative totals of all years < y
    out = np.full(len(full), np.nan)
    for m, gm in g.groupby("m"):
        years = gm["y"].to_numpy()
        csum = np.concatenate([[0.0], np.cumsum(gm["sum"].to_numpy())])
        ccnt = np.concatenate([[0.0], np.cumsum(gm["cnt"].to_numpy())])
        cday = np.concatenate([[0.0], np.cumsum(gm["days"].to_numpy())])
        sel = (keys["m"] == m).to_numpy()
        pos = np.searchsorted(years, keys.loc[sel, "y"].to_numpy(), side="left")  # years strictly before
        with np.errstate(invalid="ignore", divide="ignore"):
            val = np.where(cday[pos] >= min_days, csum[pos] / ccnt[pos], np.nan)
        out[sel] = val
    return pd.Series(out, index=series.index)


def target_daily(series: pd.Series, min_hours: int = MIN_DAY_HOURS) -> pd.DataFrame:
    """Target's own daily mean/min/max (days with >= ``min_hours`` hourly values)."""
    s = series.dropna()
    g = s.groupby(pd.DatetimeIndex(s.index).normalize())
    d = pd.DataFrame({"count": g.size(), "mean": g.mean(), "min": g.min(), "max": g.max()})
    return d[d["count"] >= min_hours].drop(columns="count")


class TargetCache:
    """Per (var, station): hourly series, hourly climatology, own daily statistics and their climatology."""

    def __init__(self, wide: dict[str, pd.DataFrame]):
        self.wide = wide
        self._store: dict = {}

    def get(self, var: str, station: str) -> dict:
        key = (var, station)
        if key not in self._store:
            s = self.wide[var][station].dropna()
            daily = target_daily(s)
            self._store[key] = {
                "hourly": s, "hourly_clim": monthly_climatology(s),
                "daily": daily, "daily_clim": pd.DataFrame({c: monthly_climatology(daily[c]) for c in daily.columns},
                                                           index=daily.index),
            }
        return self._store[key]


# ---------------------------------------------------------------- per-pair unit tables
def daily_stats(est: pd.Series, obs: pd.Series, min_hours: int = MIN_DAY_HOURS) -> pd.DataFrame:
    """Daily mean/min/max of est and obs over the same hours; days with >= ``min_hours`` hours."""
    frame = pd.DataFrame({"est": est, "obs": obs}).dropna()
    if frame.empty:
        return pd.DataFrame(columns=[f"{w}_{s}" for w in ("est", "obs") for s in ("mean", "min", "max")] + ["hours"])
    g = frame.groupby(pd.DatetimeIndex(frame.index).normalize())
    out = pd.concat({"est": g["est"].agg(["mean", "min", "max"]), "obs": g["obs"].agg(["mean", "min", "max"])}, axis=1)
    out.columns = [f"{a}_{b}" for a, b in out.columns]
    out["hours"] = g.size()
    return out[out["hours"] >= min_hours]


def pair_unit_tables(x: pd.Series, y: pd.Series, tgt: dict) -> dict[str, pd.DataFrame]:
    """Unit tables per scale: index = unit timestamp, columns obs + one estimate column per method."""
    joint = pd.DataFrame({"x": x, "y": y}).dropna().sort_index()
    if joint.empty:
        return {}
    cal = rolling_linear_transfer(joint["x"], joint["y"], CAL_WINDOW, CAL_MIN_HOURS)
    idx = joint.index
    hs = tgt["hourly"]
    hourly = pd.DataFrame({
        "obs": joint["y"], "raw": joint["x"], "calibrated": cal,
        "climatology": tgt["hourly_clim"].reindex(idx).to_numpy(),
        "persistence_1d": hs.reindex(idx - pd.Timedelta(hours=24)).to_numpy(),
        "persistence_7d": hs.reindex(idx - pd.Timedelta(hours=168)).to_numpy(),
    }, index=idx)
    tables = {"hourly": hourly}

    raw_d = daily_stats(joint["x"], joint["y"])
    cal_d = daily_stats(cal, joint["y"])
    # a calibrated day only when every joint hour of the day is calibrated (obs then equals raw obs)
    cal_d = cal_d[cal_d["hours"] == raw_d["hours"].reindex(cal_d.index)]
    days = raw_d.index
    tdaily, tclim = tgt["daily"], tgt["daily_clim"]
    for stat in ("mean", "min", "max"):
        tables[f"daily_{stat}"] = pd.DataFrame({
            "obs": raw_d[f"obs_{stat}"], "raw": raw_d[f"est_{stat}"],
            "calibrated": cal_d[f"est_{stat}"].reindex(days),
            "climatology": tclim[stat].reindex(days).to_numpy() if len(tclim) else np.nan,
            "persistence_1d": tdaily[stat].reindex(days - pd.Timedelta(days=1)).to_numpy() if len(tdaily) else np.nan,
            "persistence_7d": tdaily[stat].reindex(days - pd.Timedelta(days=7)).to_numpy() if len(tdaily) else np.nan,
        }, index=days)
    return tables


def week_start(index) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(index).normalize()
    return idx - pd.to_timedelta(idx.dayofweek, unit="D")


def weekly_table(daily_mean: pd.DataFrame, method: str, mask: np.ndarray, min_days: int = MIN_WEEK_DAYS) -> pd.DataFrame:
    """Weekly (ISO week) means of obs and one estimator over the masked days; weeks with >= min_days days."""
    sub = daily_mean.loc[mask, ["obs", method]]
    if sub.empty:
        return pd.DataFrame(columns=["obs", method])
    g = sub.groupby(week_start(sub.index))
    out = g.mean()
    return out[g.size() >= min_days]


def methods_for(scale: str) -> tuple[str, ...]:
    return tuple(m for m in METHODS if not (scale == "weekly_mean" and m == "persistence_1d"))


def unit_counts(var: str, obs: np.ndarray, est: np.ndarray, block: np.ndarray) -> pd.DataFrame:
    """Per block: n, w (within tolerance), sae, 3x3 class confusion counts."""
    tol = TOL_KEY[var]
    uniq, inv = np.unique(block, return_inverse=True)
    nb = len(uniq)
    within = within_tolerance(tol, est, obs).astype(float)
    out = {"block": uniq, "n": np.bincount(inv, minlength=nb), "w": np.bincount(inv, weights=within, minlength=nb),
           "sae": np.bincount(inv, weights=np.abs(obs - est), minlength=nb)}
    co, ce = classify(var, obs), classify(var, est)
    valid = (co >= 0) & (ce >= 0)
    conf = np.bincount(inv[valid] * 9 + 3 * co[valid].astype(int) + ce[valid].astype(int), minlength=nb * 9)
    conf = conf.reshape(nb, 9)
    for i in range(9):
        out[f"c{i}"] = conf[:, i]
    return pd.DataFrame(out)


def block_ids(index, group: int, weekly: bool = False) -> np.ndarray:
    """Integer bootstrap block: group * 100000 + days since 1970 (of the day, or of the ISO-week start)."""
    days = week_start(index) if weekly else pd.DatetimeIndex(index).normalize()
    epoch_days = ((days - pd.Timestamp("1970-01-01")) // pd.Timedelta(days=1)).to_numpy().astype(np.int64)
    return (group * 100000 + epoch_days).astype(np.int32)


def pair_counts(var: str, tables: dict[str, pd.DataFrame], group: int) -> pd.DataFrame:
    """Long counts (scale, method, support, block, n, w, sae, c0..c8) for one pair x variable."""
    pieces = []

    def add(scale, method, support, obs, est, blocks):
        if len(obs) == 0:
            return
        c = unit_counts(var, np.asarray(obs, float), np.asarray(est, float), blocks)
        pieces.append(c.assign(scale=pd.Categorical([scale] * len(c), dtype=KEY_DTYPES["scale"]),
                               method=pd.Categorical([method] * len(c), dtype=KEY_DTYPES["method"]),
                               support=pd.Categorical([support] * len(c), dtype=KEY_DTYPES["support"])))

    for scale in SCALES:
        if scale == "weekly_mean":
            if "daily_mean" not in tables:
                continue
            dm = tables["daily_mean"]
            meths = methods_for(scale)
            common = dm[list(meths)].notna().all(axis=1).to_numpy()
            for m in meths:
                for support, mask in (("own", dm[m].notna().to_numpy()), ("common", common)):
                    wk = weekly_table(dm, m, mask)
                    if len(wk):
                        add(scale, m, support, wk["obs"], wk[m], block_ids(wk.index, group, weekly=True))
            continue
        if scale not in tables:
            continue
        t = tables[scale]
        meths = methods_for(scale)
        common = t[list(meths)].notna().all(axis=1).to_numpy()
        blocks = block_ids(t.index, group)
        obs = t["obs"].to_numpy(float)
        for m in meths:
            est = t[m].to_numpy(float)
            own = np.isfinite(est)
            add(scale, m, "own", obs[own], est[own], blocks[own])
            add(scale, m, "common", obs[common], est[common], blocks[common])
    if not pieces:
        return pd.DataFrame()
    out = pd.concat(pieces, ignore_index=True)
    for col in ("n",) + CONF_COLS:
        out[col] = out[col].astype(np.int32)
    return out


# ---------------------------------------------------------------- dataset adapters
def _read_pairs(run: str) -> pd.DataFrame:
    return pd.read_csv(paths.EXPERIMENT_OUTPUT_DIR / run / "pairs.csv", dtype={"anchor": str, "target": str})


def _wide(long: pd.DataFrame, time_col: str, station_col: str, var_col: str, var_map: dict) -> dict[str, pd.DataFrame]:
    out = {}
    for src, var in var_map.items():
        sub = long[long[var_col] == src]
        if not sub.empty:
            w = sub.pivot(index=time_col, columns=station_col, values="value").sort_index()
            w.columns = w.columns.astype(str)
            out[var] = w
    return out


DATASETS = {
    "nerrs": {"run": "nerrs-multi-h4-reliability-20261017", "min_overlap": 365, "ref_dataset": "nerrs_pooled",
              "label": "nerrs_pooled", "var_cols": {"Temp": "Temp", "Sal": "Sal", "DO": "DO_mgl", "pH": "pH", "Turb": "Turb"}},
    "mddnr": {"run": "mddnr-h4-reliability-20261017", "min_overlap": 90, "ref_dataset": "mddnr", "label": "mddnr",
              "var_cols": {"Temp": "Temp", "Sal": "Sal", "DO": "DO_mgl", "pH": "pH", "Turb": "Turb"}},
    "twdb": {"run": "twdb-h4-reliability-20261017", "min_overlap": 365, "ref_dataset": "TWDB", "label": "twdb",
             "var_cols": {"Temp": "Temp", "Sal": "Sal", "DO": "DO_mgl"}},
    "usgs": {"run": "usgs-sfbay-h4-reliability-20261017", "min_overlap": 365, "ref_dataset": "usgs_sfbay",
             "label": "usgs_sfbay", "var_cols": {"Temp": "Temp", "Sal": "Sal", "DO": "DO", "pH": "pH", "Turb": "Turb"}},
}


def load_units(name: str):
    """Yield (group_code, wide{var: DataFrame (LST hourly x station)}, pairs) for a dataset, one chunk at a time."""
    cfg = DATASETS[name]
    pairs = _read_pairs(cfg["run"])
    if name == "nerrs":
        from experiments import nerrs_multi as nm
        pairs = pairs[~pairs["vertical_pair"].astype(bool)]
        for gi, code in enumerate(sorted(pairs["reserve"].unique())):
            wq, _ = nm.load_wq_hourly(nm.RESERVES[code], years=nm.QC_YEARS)
            wide = _wide(wq, "time_lst", "station", "variable", {v: k for k, v in cfg["var_cols"].items()})
            yield gi, wide, pairs[pairs["reserve"] == code]
    elif name == "mddnr":
        from experiments import mddnr_load as ml
        hourly, _, _ = ml.load_hourly(ml.MDDNR_DIR)
        yield 0, _wide(hourly, "time_est", "station", "variable", {v: k for k, v in cfg["var_cols"].items()}), pairs
    elif name == "twdb":
        from experiments import twdb_load as tl
        hourly, _, _ = tl.load_hourly(data_dir=tl.RAW_DIR, years=range(2008, 2020))
        yield 0, _wide(hourly, "time_lst", "station", "variable", {v: k for k, v in cfg["var_cols"].items()}), pairs
    elif name == "usgs":
        from experiments import usgs_load as ul
        hourly, _ = ul.build_hourly(ul.RAW_DIR)
        lst = -8
        hourly = hourly[(hourly["hour_utc"] >= pd.Timestamp(ul.PERIOD_START) - pd.Timedelta(hours=lst))
                        & (hourly["hour_utc"] < pd.Timestamp(ul.PERIOD_END) + pd.Timedelta(days=1, hours=-lst))].copy()
        hourly["time_lst"] = hourly["hour_utc"] + pd.Timedelta(hours=lst)
        yield 0, _wide(hourly, "time_lst", "site", "var", {v: k for k, v in cfg["var_cols"].items()}), pairs
    else:
        raise KeyError(name)


def n_days_col(pairs: pd.DataFrame, var: str, src_var: str) -> pd.Series:
    col = f"n_days_{src_var}"
    if col not in pairs:
        col = f"n_days_{var}"
    return pairs[col] if col in pairs else pd.Series(0, index=pairs.index)


KEYS = ["var", "scale", "method", "support", "regime", "distance_bin", "block"]
KEY_DTYPES = {"var": pd.CategoricalDtype(VARS), "scale": pd.CategoricalDtype(SCALES),
              "method": pd.CategoricalDtype(METHODS), "support": pd.CategoricalDtype(("own", "common")),
              "regime": pd.CategoricalDtype(("same", "different", "unknown")),
              "distance_bin": pd.CategoricalDtype(BIN_LABELS)}


def _reduce(frames: list[pd.DataFrame]) -> pd.DataFrame:
    out = pd.concat(frames, ignore_index=True).groupby(KEYS, observed=True)[list(COUNT_COLS)].sum().reset_index()
    for col in ("n",) + CONF_COLS:
        out[col] = out[col].astype(np.int32)
    return out


def evaluate_dataset(name: str, log=print):
    """Yield (var, per-block counts, pair membership) for one dataset, one variable at a time.

    The hourly data of every group (NERRS reserve) is loaded once; counts are accumulated and
    released per variable so memory stays ~ (cells of one variable) x blocks.
    """
    cfg = DATASETS[name]
    units = list(load_units(name))
    for var, src in cfg["var_cols"].items():
        acc, buffer, members = [], [], []

        def flush():
            if buffer:  # fold the buffer into the single running total
                acc[:] = [_reduce(acc + buffer)]
                buffer.clear()

        t0, n_done = time.time(), 0
        for group, wide, pairs in units:
            if var not in wide:
                continue
            cache = TargetCache(wide)
            table = wide[var]
            elig = pairs[n_days_col(pairs, var, src).fillna(0) >= cfg["min_overlap"]]
            for p in elig.itertuples(index=False):
                if p.anchor not in table or p.target not in table:
                    continue
                tables = pair_unit_tables(table[p.anchor], table[p.target], cache.get(var, p.target))
                counts = pair_counts(var, tables, group)
                if counts.empty:
                    continue
                n = len(counts)
                counts = counts.assign(var=pd.Categorical([var] * n, dtype=KEY_DTYPES["var"]),
                                       regime=pd.Categorical([p.regime] * n, dtype=KEY_DTYPES["regime"]),
                                       distance_bin=pd.Categorical([p.distance_bin] * n, dtype=KEY_DTYPES["distance_bin"]))
                buffer.append(counts)
                members.append(counts[counts["support"] == "own"][["var", "scale", "method", "regime", "distance_bin"]]
                               .drop_duplicates().assign(pair=f"{group}:{p.anchor}>{p.target}"))
                n_done += 1
                if len(buffer) >= 40:
                    flush()
            flush()
            del cache
        if not acc:
            continue
        log(f"[{name}] {var}: {n_done} pairs in {time.time() - t0:.0f}s, {len(acc[0])} count rows", flush=True)
        counts = acc[0]
        for col in KEYS[:-1]:  # plain strings downstream (one variable at a time)
            counts[col] = counts[col].astype(str)
        yield var, counts, pd.concat(members, ignore_index=True).astype(str)
        del counts, acc


# ---------------------------------------------------------------- aggregation
def _with_all_regime(counts: pd.DataFrame) -> pd.DataFrame:
    keys = [k for k in KEYS if k != "regime"]
    allr = counts.groupby(keys, observed=True)[list(COUNT_COLS)].sum().reset_index().assign(regime="all")
    return pd.concat([counts[counts["regime"].isin(["same", "different"])], allr], ignore_index=True)


def _cell_record(per_block: pd.DataFrame, metric: str, scale: str, n_boot: int = N_BOOT) -> dict:
    per_block = per_block.sort_values("block")
    n = per_block["n"].to_numpy(float)
    conf = per_block[list(CONF_COLS)].to_numpy(float)
    if metric == "value":
        w = per_block["w"].to_numpy(float)
    else:
        w = conf[:, [0, 4, 8]].sum(1)
        n = conf.sum(1)
    keep = n > 0
    w, n = w[keep], n[keep]
    share, lo, hi = bootstrap_share(w, n, n_boot=n_boot, seed=SEED)
    rec = {"n_days": int(keep.sum()), "n_units": int(n.sum()), "share": round(share, 4), "ci_low": round(lo, 4),
           "ci_high": round(hi, 4), "block": "iso_week" if scale == "weekly_mean" else "day"}
    for g in GATES:
        rec[f"gate{int(g * 100)}"] = gate_status(lo, rec["n_days"], g, min_days=MIN_BLOCKS)
    if metric == "value":
        rec["mae"] = round(float(per_block["sae"].sum() / per_block["n"].sum()), 4)
    else:
        cs = class_summary(conf.sum(0))
        rec.update({k: (round(v, 4) if isinstance(v, float) else v) for k, v in cs.items()})
    return rec


def cell_table(dataset: str, counts: pd.DataFrame, members: pd.DataFrame, n_boot: int = N_BOOT) -> pd.DataFrame:
    """cells.csv rows: dataset x var x scale x metric x regime x distance bin x method (own support)."""
    allc = _with_all_regime(counts[counts["support"] == "own"])
    mem = pd.concat([members[members["regime"].isin(["same", "different"])], members.assign(regime="all")])
    npairs = mem.groupby(["var", "scale", "method", "regime", "distance_bin"])["pair"].nunique()
    rows = []
    for (var, scale, method, support, regime, dbin), grp in allc.groupby(
            ["var", "scale", "method", "support", "regime", "distance_bin"], observed=True):
        for metric in ("value", "class"):
            if metric == "class" and var == "Turb":
                continue
            rec = {"dataset": dataset, "var": var, "scale": scale, "metric": metric, "regime": regime,
                   "distance_bin": dbin, "transfer_or_baseline": method, "support": support,
                   "n_pairs": int(npairs.get((var, scale, method, regime, dbin), 0))}
            rec.update(_cell_record(grp.groupby("block")[list(COUNT_COLS)].sum().reset_index(), metric, scale, n_boot))
            rows.append(rec)
    return pd.DataFrame(rows)


def strict_radius(status_by_bin: dict, bins=RADIUS_BINS) -> tuple[float, str]:
    """(radius_km, stop) -- see module doc: empty bins skipped, stop at first populated non-pass bin."""
    radius, first = np.nan, True
    for b in bins:
        if b not in status_by_bin:
            continue
        st = status_by_bin[b]
        if st == "pass":
            radius = BIN_UPPER_KM[b]
            first = False
            continue
        if first:
            radius = 0.0 if st == "fail" else np.nan
        return radius, f"{st}@{b}"
    if first:
        return np.nan, "no_pairs"
    last = [b for b in bins if b in status_by_bin][-1]
    return radius, "all_pass" if last == bins[-1] else f"no_pairs_beyond@{last}"


def radius_table(cells: pd.DataFrame, compare: pd.DataFrame | None = None) -> pd.DataFrame:
    """Strict radius per dataset x var x regime x scale x metric x transfer x gate.

    With ``compare`` (baseline_compare.csv rows), each radius > 0 also says whether the transfer beat
    climatology / persistence (common-support difference CI above 0) in *every* bin within the radius.
    For the class metric the smallest kappa and largest majority-class share over those bins are added
    (a radius with kappa ~ 0 or one dominant class is an artefact of the class map).
    """
    sub = cells[(cells["support"] == "own") & cells["transfer_or_baseline"].isin(TRANSFERS)]
    rows = []
    for key, grp in sub.groupby(["dataset", "var", "regime", "scale", "metric", "transfer_or_baseline"]):
        g_bin = grp.set_index("distance_bin")
        for g in GATES:
            col = f"gate{int(g * 100)}"
            status = g_bin[col].to_dict()
            r, stop = strict_radius(status)
            rec = dict(zip(["dataset", "var", "regime", "scale", "metric", "transfer"], key),
                       gate=int(g * 100), radius_km=r, stop=stop,
                       evidence=",".join(f"{b}:{status.get(b, 'none')}" for b in RADIUS_BINS))
            inside = [b for b in RADIUS_BINS if b in status and np.isfinite(r) and BIN_UPPER_KM[b] <= r]
            if inside and key[4] == "class":
                rec["kappa_min_within"] = round(float(g_bin.loc[inside, "kappa"].min()), 4)
                rec["majority_class_share_max_within"] = round(float(g_bin.loc[inside, "majority_class_share"].max()), 4)
                rec["bad_base_rate_within"] = round(float(np.average(g_bin.loc[inside, "bad_base_rate"],
                                                                     weights=g_bin.loc[inside, "n_units"])), 4)
            if inside and compare is not None and len(compare):
                cmp = compare[(compare["dataset"] == key[0]) & (compare["var"] == key[1]) & (compare["regime"] == key[2])
                              & (compare["scale"] == key[3]) & (compare["metric"] == key[4])
                              & (compare["method"] == key[5]) & compare["scope"].isin(inside)]
                for ref in BASELINES:
                    c = f"diff_vs_{ref}_ci_low"
                    if c in cmp and len(cmp) == len(inside) and cmp[c].notna().all():
                        rec[f"beats_{ref}_within"] = bool((cmp[c] > 0).all())
            rows.append(rec)
    return pd.DataFrame(rows)


def baseline_compare(dataset: str, counts: pd.DataFrame, n_boot: int = N_BOOT) -> pd.DataFrame:
    """Anchor transfers vs baselines on common support, scope <= 30 km pooled and per distance bin."""
    allc = _with_all_regime(counts[counts["support"] == "common"])
    rows = []
    scopes = [("le30km", list(RADIUS_BINS))] + [(b, [b]) for b in RADIUS_BINS]
    for (var, scale, regime), grp in allc.groupby(["var", "scale", "regime"], observed=True):
        meths = methods_for(scale)
        for scope, bins in scopes:
            g = grp[grp["distance_bin"].isin(bins)]
            if g.empty:
                continue
            blocks = {m: g[g["method"] == m].groupby("block")[list(COUNT_COLS)].sum() for m in meths}
            idx = sorted(set().union(*[b.index for b in blocks.values()]))
            blocks = {m: b.reindex(idx, fill_value=0).rename_axis("block") for m, b in blocks.items()}
            for metric in ("value", "class"):
                if metric == "class" and var == "Turb":
                    continue

                def wn(b):
                    conf = b[list(CONF_COLS)].to_numpy(float)
                    if metric == "value":
                        return b["w"].to_numpy(float), b["n"].to_numpy(float)
                    return conf[:, [0, 4, 8]].sum(1), conf.sum(1)

                base = {"dataset": dataset, "var": var, "scale": scale, "metric": metric, "regime": regime,
                        "scope": scope}
                for m in meths:
                    rec = {**base, "method": m}
                    rec.update(_cell_record(blocks[m].reset_index(), metric, scale, n_boot))
                    w_m, n_m = wn(blocks[m])
                    for ref in BASELINES:
                        if ref not in meths or ref == m:
                            continue
                        w_r, n_r = wn(blocks[ref])
                        ok = (n_m > 0) & (n_r > 0)
                        if ok.sum() < 2:
                            continue
                        d, lo, hi = bootstrap_share_difference(w_m[ok], n_m[ok], w_r[ok], n_r[ok], n_boot=n_boot,
                                                               seed=SEED)
                        rec[f"diff_vs_{ref}"] = round(d, 4)
                        rec[f"diff_vs_{ref}_ci_low"] = round(lo, 4)
                        rec[f"diff_vs_{ref}_ci_high"] = round(hi, 4)
                    rows.append(rec)
    out = pd.DataFrame(rows)
    if not out.empty:
        lo = out.get("diff_vs_climatology_ci_low")
        out["beats_climatology"] = (lo > 0) if lo is not None else False
        degenerate = (out["metric"] == "class") & (
            (out.get("n_bad", 0) < 30) | (out.get("bad_base_rate", 0) < 0.05) | (out.get("bad_base_rate", 0) > 0.95)
            | (out.get("majority_class_share", 0) > 0.95))
        out["class_degenerate"] = degenerate
    return out


def hourly_check(dataset_key: str, cells: pd.DataFrame) -> pd.DataFrame:
    """Compare own-support hourly value cells with the hourly run's cells.csv."""
    cfg = DATASETS[dataset_key]
    ref = pd.read_csv(paths.EXPERIMENT_OUTPUT_DIR / cfg["run"] / "cells.csv")
    ref = ref[ref["dataset"] == cfg["ref_dataset"]].copy()
    ref["var"] = ref["var"].replace({"DO_mgl": "DO"})
    ref["transfer"] = ref["transfer"].replace({"calibrated_30d": "calibrated"})
    mine = cells[(cells["scale"] == "hourly") & (cells["metric"] == "value") & (cells["support"] == "own")
                 & cells["transfer_or_baseline"].isin(TRANSFERS)].rename(columns={"transfer_or_baseline": "transfer"})
    m = mine.merge(ref, on=["var", "regime", "distance_bin", "transfer"], suffixes=("_new", "_ref"))
    out = m[["var", "regime", "distance_bin", "transfer", "n_days_new", "n_days_ref", "share_new", "share_ref",
             "ci_low_new", "ci_low_ref"]].copy()
    out.insert(0, "dataset", cfg["label"])
    out["delta_share"] = (out["share_new"] - out["share_ref"]).round(4)
    out["delta_ci_low"] = (out["ci_low_new"] - out["ci_low_ref"]).round(4)
    return out


# ---------------------------------------------------------------- main
def _git() -> dict:
    def run(*cmd):
        try:
            return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=30).stdout.strip()
        except Exception:  # noqa: BLE001
            return ""
    return {"commit": run("git", "rev-parse", "HEAD"),
            "script_dirty": bool(run("git", "status", "--porcelain", "--", "experiments/h4_multiscale.py"))}


def _rel(p: Path) -> str:
    p = Path(p)
    return str(p.relative_to(paths.PROJECT_ROOT)).replace("\\", "/") if p.is_relative_to(paths.PROJECT_ROOT) else str(p)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output-dir", type=Path, default=paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME)
    ap.add_argument("--datasets", nargs="+", default=["usgs", "twdb", "nerrs", "mddnr"], choices=list(DATASETS))
    ap.add_argument("--n-boot", type=int, default=N_BOOT)
    ap.add_argument("--resume", action="store_true",
                    help="reuse per-dataset parts/ already written in this output dir (never overwritten)")
    args = ap.parse_args(argv)
    out = Path(args.output_dir)
    parts = out / "parts"
    if out.exists() and any(p for p in out.iterdir() if p.name != "parts"):
        raise FileExistsError(f"refusing to overwrite non-empty output dir: {out}")
    if parts.exists() and any(parts.iterdir()) and not args.resume:
        raise FileExistsError(f"{parts} holds earlier parts; pass --resume to reuse them")
    parts.mkdir(parents=True, exist_ok=True)
    part_names = ("cells", "radius", "baseline_compare", "hourly_check")

    cells, radii, compares, checks = [], [], [], []
    for name in args.datasets:
        files = {k: parts / f"{name}_{k}.csv" for k in part_names}
        if all(f.exists() for f in files.values()):
            print(f"[{name}] reusing parts", flush=True)
            loaded = {k: pd.read_csv(f) for k, f in files.items()}
            cells.append(loaded["cells"]), radii.append(loaded["radius"])
            compares.append(loaded["baseline_compare"]), checks.append(loaded["hourly_check"])
            continue
        t0 = time.time()
        label = DATASETS[name]["label"]
        parts_c, parts_b = [], []
        for var, counts, members in evaluate_dataset(name):
            parts_c.append(cell_table(label, counts, members, args.n_boot))
            parts_b.append(baseline_compare(label, counts, args.n_boot))
            del counts, members
        c = pd.concat(parts_c, ignore_index=True)
        cells.append(c)
        compares.append(pd.concat(parts_b, ignore_index=True))
        radii.append(radius_table(c, compares[-1]))
        checks.append(hourly_check(name, c))
        chk = checks[-1]
        print(f"[{name}] done in {time.time() - t0:.0f}s; hourly check max |delta share| = "
              f"{chk['delta_share'].abs().max() if len(chk) else float('nan')}", flush=True)
        for k, frame in zip(part_names, (cells[-1], radii[-1], compares[-1], checks[-1])):
            with open(files[k], "x", encoding="utf-8", newline="") as handle:  # write-once
                frame.to_csv(handle, index=False)

    cells = pd.concat(cells, ignore_index=True)
    cells.to_csv(out / "cells.csv", index=False)  # parts/ keeps the per-dataset copies
    pd.concat(radii, ignore_index=True).to_csv(out / "radius.csv", index=False)
    pd.concat(compares, ignore_index=True).to_csv(out / "baseline_compare.csv", index=False)
    pd.concat(checks, ignore_index=True).to_csv(out / "hourly_check.csv", index=False)

    hourly_runs = {}
    for name in args.datasets:
        run_dir = paths.EXPERIMENT_OUTPUT_DIR / DATASETS[name]["run"]
        hourly_runs[name] = {f: {"file": _rel(run_dir / f), "sha256": sha256(run_dir / f)}
                             for f in ("manifest.json", "pairs.csv", "cells.csv")}
    manifest = {
        "run": RUN_NAME, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "experiments/h4_multiscale.py", "code": _git(),
        "datasets": {n: {k: v for k, v in DATASETS[n].items()} for n in args.datasets},
        "hourly_runs": hourly_runs,
        "inputs_note": "raw data files and their sha256 are listed in each hourly run's manifest.json "
                       "(same loaders, same data directories under paths.FOREIGN_DATA_DIR)",
        "parameters": {
            "scales": {"hourly": "hourly protocol", "daily_mean/min/max": f">= {MIN_DAY_HOURS} joint hours per day",
                       "weekly_mean": f"ISO week (Mon-Sun) mean of daily means, >= {MIN_WEEK_DAYS} valid days; "
                                      f"block = week, gate needs >= {MIN_BLOCKS} weeks"},
            "tolerances": {"Temp": 0.5, "Sal": 1.0, "DO": 0.5, "pH": 0.2, "Turb": "max(2, 20 % of obs)"},
            "transfers": {"raw": "anchor value, same statistic over the same hours",
                          "calibrated": f"hourly OLS on strictly-past {CAL_WINDOW} (>= {CAL_MIN_HOURS} joint h), "
                                        "aggregated; day kept only if all its joint hours are calibrated"},
            "baselines": {"climatology": f"target calendar-month mean of the same-scale statistic over strictly "
                                         f"earlier years, >= {CLIM_MIN_DAYS} days of that month",
                          "persistence_1d": "target value 24 h (hourly) / 1 day earlier (daily scales); not weekly",
                          "persistence_7d": "target value 168 h / 7 days earlier; weekly = previous week's days"},
            "classes": CLASS_RULES, "class_codes": {"0": "ok", "1": "caution", "2": "bad"},
            "class_metrics": "agreement share (bootstrap), Cohen's kappa from pooled 3x3 matrix (point), "
                             "bad_miss_rate = P(est not bad | obs bad), bad_false_alarm_rate = P(obs not bad | est bad)",
            "class_degenerate_rule": "n_bad < 30 or bad_base_rate < 0.05 or > 0.95 or majority_class_share > 0.95",
            "gates": list(GATES), "gate_rule": f"block-bootstrap 2.5 % lower bound >= gate and >= {MIN_BLOCKS} blocks",
            "n_boot": args.n_boot, "seed": SEED,
            "blocks": {"nerrs_pooled": "(reserve, day)", "others": "calendar day (LST)", "weekly_mean": "ISO week"},
            "radius_rule": "walk 0-2..20-30 km; bins with no pair skipped; stop at first populated bin that fails "
                           "or is insufficient; 0 = first populated bin fails; NaN = first populated bin insufficient",
            "supports": {"own": "units where the estimator exists (cells.csv, radius.csv)",
                         "common": "units where all estimators of the scale exist (baseline_compare.csv)"},
            "radius_extras": "beats_<baseline>_within = common-support difference CI low > 0 in every bin "
                             "within the radius; class radius carries kappa_min / majority share max within",
            "regime": "taken from each hourly run's pairs.csv (|delta wet/high-flow median salinity| < 2 psu)",
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
