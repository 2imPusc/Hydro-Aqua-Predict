"""H1.8: foreign pretraining + VN fine-tuning for the cross-parameter imputers (shadow research).

Question (owner, 2026-10-25): the live sensor (Cat Ba NB1) gives Temperature, pH, NH4 and TSS; DO,
Salinity, PO4 and Transparency are imputed by models trained on Vietnamese provincial monitoring
(QN, HP; few campaigns per year, few years). Does pretraining on similar foreign data (Hong Kong
EPD marine monitoring; NERRS daily means) and fine-tuning on VN data beat VN-only imputers on
held-out VN data? Nothing here touches the runtime imputers in ``core/models/``.

PRE-REGISTERED DESIGN (fixed before any test score was looked at; later changes are labelled
"post-hoc" in NOTES.md)
--------------------------------------------------------------------------------------------
Data and harmonisation (table written to ``unit_mapping.csv``)
  * VN: ``data/{haiphong,quangninh}/clean_data.csv`` via ``hap_shared.preprocessing.load_data``,
    minus ``EXCLUDED_STATIONS`` (NB74/NB78, coordinates ~200 km off), rows missing any input dropped.
    - VN column ``NH3`` is total ammonia nitrogen (QCVN 10:2023 B1 limit 0.1 mg/L is the NH4+-as-N
      limit; HP median 0.10 mg/L would be lethal if un-ionised). Mapped to ``TAN`` (mg/L as N).
    - HP Temperature and Salinity are GLORYS 1/12 deg model values, not measurements (RL-25). HP
      Salinity is therefore reported as "proxy_glorys" and never decides the verdict; HP stations
      whose Temperature+Salinity series are identical on every shared date (same model cell) are
      merged into one cross-validation group.
    - HP 2020-08 and 2020-11 rows with identical DO/pH/TAN/TSS/PO4 at a station are copies: the
      later copy is dropped.
    - QN PO4 is LOQ-censored (92 % at 0.01): PO4 is evaluated on HP only. Transparency exists on
      QN only.
  * Hong Kong EPD (2015-2025, 94 stations, monthly): SURFACE samples only (VN grab samples are
    surface). Ammonia Nitrogen (mg/L, total ammonia as N) -> TAN; Suspended Solids (mg/L) -> TSS
    (Turbidity NTU is NOT used for TSS); DO mg/L (not % saturation); Salinity psu (= ppt for this
    purpose); Orthophosphate Phosphorus mg/L -> PO4 (VN PO4 is phosphate as P); Secchi depth m ->
    Transparency. Censored cells "<LOD" -> LOD/2 for inputs; censored PO4 is excluded as a target.
  * NERRS (8 reserves, 2007-2011, CDMO flag 0 only): hourly means -> daily means (>= 18 hours),
    then one seeded random day per station-month (grab-sample analogue). Temp, Sal, DO_mgl, pH.
    NERRS has no ammonia and no TSS (Turb NTU is not converted): TAN and TSS are left MISSING
    (XGBoost routes missing values natively) - nothing is guessed. Used for DO and Salinity only.
  * Target plausibility screens (same for every source): DO (0, 20] mg/L (core.config
    PLAUSIBLE_RANGE; drops QN 60.5), Salinity [0, 40], PO4 (0, 2], Transparency (0, 10] m.

Inputs (identical for every variant): Temperature, pH, TAN, TSS, sin/cos(2 pi month / 12).
VN only has month resolution, so the season terms use the month for every source.

Evaluation units (region x target): HP DO, QN DO, QN Salinity (primary); HP PO4, QN Transparency
(secondary); HP Salinity (proxy_glorys, reported only).

Splits (VN test rows only; VN training rows only from the training side):
  (i)  loso   - leave-station-group-out. HP: one fold per group (GLORYS-duplicate stations merged).
              QN: 97 stations in 10 seeded station folds.
  (ii) time   - train years < last year, test the last year (2024 for both regions).
  (iii) season - partial-year stress test: train months 5-10, test months 11-4.
Inner tuning (VN sample weight) uses 3 station-group folds inside the training rows only.

Variants
  baselines : vn_median (training median, runtime fallback), vn_clim (training month mean),
              vn_runtime (exact runtime recipe: 4 inputs + region/target season config, XGB 100/4/0.1),
              vn_only (common inputs, XGB 100/4/0.1), vn_pooled (QN+HP training rows; HP Salinity
              rows never used as targets for QN).
  zero-shot : hk_zero (all HK surface stations), hk_sim_zero (pre-defined similar HK stations),
              hknerrs_zero (HK + NERRS; DO/Salinity only).
  transfer  : pool_w   <- PRIMARY transfer variant: HK + VN pooled, VN sample weight in
                          {1, 10, 100} tuned on inner VN folds only.
              pool_w_sim (same, similar HK stations), pool_hknerrs_w (HK + NERRS + VN),
              ft_warm (XGB pretrained on HK, +100 trees boosted on VN residuals),
              stack_feat (VN XGB on inputs + HK prediction), da_std (domain-adaptation-lite:
              per-domain z-scores of log-inputs and of the target, pooled + tuned weight,
              back-transformed with VN training stats), mlp_ft (sklearn MLP pretrained on HK,
              warm-start fine-tuned on VN).
Similar HK stations (pre-defined, uses no VN target): HK stations with median surface salinity
>= 28 psu (marine regime like NB1 / most QN / all HP), then the nearest half by z-distance on
(temperature amplitude p90-p10, median log TSS, median pH) to the VN region's station medians.

Metrics: MAE, RMSE, R2, bias (pred - obs). Paired MAE difference (variant - vn_only) with
bootstrap CIs (2000 draws) resampling station-month rows (owner-specified block = one VN row);
sensitivity CIs resample whole campaigns and whole station groups.
Threshold-class view (cobia, hap_shared/thresholds/cobia_thresholds.json and RL-27): "DO < 5"
(watch) and "DO < 4" (bad); "Salinity outside 26-32" (outside the cobia optimum). POD, false-alarm
ratio, POFD, kappa, prevalence. A class with prevalence < 5 % or > 95 % or < 10 events is
DEGENERATE and cannot block or support a verdict (then the rule uses MAE + bias only).

Decision rule (per region x target; applied to pool_w, reported for every transfer variant as
exploratory): transfer is USEFUL only if MAE(variant) - MAE(vn_only) has a 95 % CI (row blocks)
entirely below 0 in >= 2 of the 3 split types, and on those splits the POD of every
non-degenerate class is not lower than vn_only's by more than 0.05. "Robust" additionally needs the
campaign-cluster CI below 0 on the same splits.

Learning curve: loso split, VN training rows subsampled to 100/50/25/10 % (3 seeds below 100 %),
variants vn_only, vn_clim, pool_w, ft_warm, stack_feat (hk_zero is constant).

Run:  python experiments/transfer_impute.py [--run-name transfer-impute-20261025] [--jobs 6]
Output: paths.EXPERIMENT_OUTPUT_DIR / <run-name>/ (created with exist_ok=False).
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.config import PLAUSIBLE_RANGE  # noqa: E402

RUN_NAME = "transfer-impute-20261025"
SEED = 20261025
FEATURES = ["Temperature", "pH", "TAN", "TSS", "m_sin", "m_cos"]
RAW_INPUTS = ["Temperature", "pH", "TAN", "TSS"]
TARGETS = ["DO", "Salinity", "PO4", "Transparency"]
XGB_PARAMS = dict(n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42, verbosity=0, n_jobs=1)
WEIGHT_GRID = (1.0, 10.0, 100.0)
INNER_FOLDS = 3
QN_OUTER_FOLDS = 10
N_BOOT = 2000
PRIMARY_VARIANT = "pool_w"
SPLITS = ("loso", "time", "season")
WET_MONTHS = (5, 6, 7, 8, 9, 10)
LC_FRACTIONS = (1.0, 0.5, 0.25, 0.1)
LC_SEEDS = 3
LC_VARIANTS = ("vn_only", "vn_clim", "pool_w", "ft_warm", "stack_feat", "hk_zero")
HK_MARINE_SAL = 28.0
POD_TOLERANCE = 0.05

EVAL_UNITS = [  # (region, target, role)
    ("haiphong", "DO", "primary"),
    ("quangninh", "DO", "primary"),
    ("quangninh", "Salinity", "primary"),
    ("haiphong", "PO4", "secondary"),
    ("quangninh", "Transparency", "secondary"),
    ("haiphong", "Salinity", "proxy_glorys"),
]
NERRS_TARGETS = {"DO", "Salinity"}
TARGET_RANGE = {  # (low, high, low_inclusive)
    "DO": (PLAUSIBLE_RANGE["DO"][0], PLAUSIBLE_RANGE["DO"][1], False),
    "Salinity": (0.0, 40.0, True),
    "PO4": (0.0, 2.0, False),
    "Transparency": (0.0, 10.0, False),
}
# runtime season config, copied from core/impute.py SEASONALITY_CONFIG (do not import: keeps the
# reproduction pinned to what produced cv_r2.json)
RUNTIME_SEASON = {("haiphong", "Salinity"): ["month"], ("haiphong", "PO4"): ["m_sin", "m_cos"],
                  ("quangninh", "Transparency"): ["month"]}
THRESHOLD_EVENTS = {  # name -> (target, function(values) -> bool event)
    "DO<5": ("DO", lambda v: v < 5.0),
    "DO<4": ("DO", lambda v: v < 4.0),
    "Sal_outside_26_32": ("Salinity", lambda v: (v < 26.0) | (v > 32.0)),
}

UNIT_MAPPING = [
    dict(param="Temperature", vn="Temperature (degC; HP = GLORYS model value)", hk="Temperature (degC), surface",
         nerrs="Temp (degC)", rule="identity", note="HP input is modelled; sensor measures (deployment shift)"),
    dict(param="pH", vn="pH", hk="pH", nerrs="pH", rule="identity", note=""),
    dict(param="TAN", vn="NH3 column = NH4+ as N (mg/L)", hk="Ammonia Nitrogen (mg/L, as N)",
         nerrs="absent -> missing", rule="identity; HK '<LOD' -> LOD/2",
         note="NOT HK 'Unionised Ammonia'. Runtime feeds Emerson un-ionised NH3 to imputers trained on this TAN column"),
    dict(param="TSS", vn="TSS (mg/L)", hk="Suspended Solids (mg/L)", nerrs="absent -> missing (Turb NTU not converted)",
         rule="identity; HK '<0.5' -> 0.25", note="Turbidity NTU dropped, never converted to mg/L"),
    dict(param="DO", vn="DO (mg/L)", hk="Dissolved Oxygen (mg/L)", nerrs="DO_mgl (mg/L)",
         rule="identity; target screen (0, 20]", note="HK % saturation column not used"),
    dict(param="Salinity", vn="Salinity (QN measured; HP = GLORYS)", hk="Salinity (psu)", nerrs="Sal (psu)",
         rule="psu == ppt; screen [0, 40]", note="HP salinity is model output -> proxy only"),
    dict(param="PO4", vn="PO4 (mg/L as P; QN LOQ-censored -> excluded)", hk="Orthophosphate Phosphorus (mg/L as P)",
         nerrs="not used", rule="identity; censored HK values excluded as target", note="evaluated on HP only"),
    dict(param="Transparency", vn="Transparency (m, QN only)", hk="Secchi Disc Depth (m)", nerrs="not used",
         rule="identity; screen (0, 10] m", note="evaluated on QN only"),
    dict(param="season", vn="month of campaign (day unknown)", hk="month of sample date", nerrs="month of day",
         rule="sin/cos(2 pi month/12)", note="month resolution for all sources"),
    dict(param="depth", vn="surface grab sample", hk="Depth == 'Surface Water' only", nerrs="fixed sonde (often near bottom)",
         rule="filter", note="NERRS depth mismatch is a known limitation"),
]

HK_COLUMNS = {  # prefix in the EPD header -> harmonised name
    "Ammonia Nitrogen": "TAN",
    "Dissolved Oxygen (mg/L)": "DO",
    "Orthophosphate Phosphorus": "PO4",
    "pH": "pH",
    "Salinity": "Salinity",
    "Secchi Disc Depth": "Transparency",
    "Suspended Solids": "TSS",
    "Temperature": "Temperature",
}


# ------------------------------------------------------------------ harmonisation helpers
def parse_censored(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Numeric values with '<x' -> x/2; returns (values, censored_flag)."""
    raw = series.astype(str).str.strip()
    cens = raw.str.startswith("<")
    num = pd.to_numeric(raw.str.lstrip("<").str.strip(), errors="coerce")
    num = num.where(~cens, num / 2.0)
    return num, cens & num.notna()


def add_season(df: pd.DataFrame) -> pd.DataFrame:
    df["m_sin"] = np.sin(2 * np.pi * df["month"] / 12.0)
    df["m_cos"] = np.cos(2 * np.pi * df["month"] / 12.0)
    return df


def screen_targets(df: pd.DataFrame, source: str) -> list[dict]:
    """Set implausible target values to NaN in place; return a QC log."""
    log = []
    for t, (lo, hi, lo_inc) in TARGET_RANGE.items():
        if t not in df.columns:
            continue
        v = df[t]
        ok_lo = v >= lo if lo_inc else v > lo
        bad = v.notna() & ~(ok_lo & (v <= hi))
        if bad.any():
            log.append(dict(source=source, item=f"{t} outside plausible range", n=int(bad.sum()),
                            values=";".join(f"{x:g}" for x in v[bad].head(10))))
        df.loc[bad, t] = np.nan
    return log


def duplicate_series_groups(df: pd.DataFrame, cols=("Temperature", "Salinity"), min_overlap: int = 3) -> dict:
    """Union stations whose ``cols`` are identical on every shared date (>= min_overlap dates)."""
    stations = sorted(df["station"].unique())
    parent = {s: s for s in stations}

    def find(s):
        while parent[s] != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s

    piv = {s: g.set_index("date")[list(cols)] for s, g in df.groupby("station")}
    for i, a in enumerate(stations):
        for b in stations[i + 1:]:
            common = piv[a].index.intersection(piv[b].index)
            if len(common) < min_overlap:
                continue
            if np.allclose(piv[a].loc[common].to_numpy(float), piv[b].loc[common].to_numpy(float), atol=1e-9):
                parent[find(b)] = find(a)
    return {s: find(s) for s in stations}


def load_vn(region: str) -> tuple[pd.DataFrame, list[dict]]:
    from hap_shared.preprocessing import EXCLUDED_STATIONS, load_data

    raw = load_data(str(paths.clean_data(region)))
    log = [dict(source=region, item="rows in clean_data", n=len(raw), values="")]
    raw = raw[~raw["Station"].isin(EXCLUDED_STATIONS)]
    df = pd.DataFrame({
        "source": region, "region": region, "station": raw["Station"].astype(str),
        "date": pd.to_datetime(raw["Quarter"]),
        "Temperature": raw["Temperature"], "pH": raw["pH"], "TAN": raw["NH3"], "TSS": raw["TSS"],
    })
    for t in TARGETS:
        df[t] = raw[t] if t in raw.columns else np.nan
    n0 = len(df)
    df = df.dropna(subset=RAW_INPUTS)
    log.append(dict(source=region, item="rows after EXCLUDED_STATIONS / dropped for missing input", n=n0,
                    values=f"dropped={n0 - len(df)}"))
    if region == "haiphong":
        key = ["station", "DO", "pH", "TAN", "TSS", "PO4"]
        dup = df.duplicated(subset=key, keep="first")
        log.append(dict(source=region, item="duplicated measurement rows dropped (later copy)", n=int(dup.sum()),
                        values=";".join(f"{s}@{d:%Y-%m}" for s, d in df.loc[dup, ["station", "date"]].itertuples(index=False))))
        df = df[~dup]
        groups = duplicate_series_groups(df)
        df["group"] = df["station"].map(groups)
        merged = {g: sorted(s for s, gg in groups.items() if gg == g) for g in set(groups.values())}
        log.append(dict(source=region, item="GLORYS-duplicate station groups", n=sum(len(v) > 1 for v in merged.values()),
                        values=";".join("=".join(v) for v in merged.values() if len(v) > 1)))
    else:
        df["group"] = df["station"]
        n_po4 = int(df["PO4"].notna().sum())
        log.append(dict(source=region, item="PO4 excluded (LOQ-censored)", n=n_po4,
                        values=f"share at 0.01 = {(df['PO4'] == 0.01).mean():.3f}"))
        df["PO4"] = np.nan
    log += screen_targets(df, region)
    df["month"] = df["date"].dt.month
    df["year"] = df["date"].dt.year
    df["campaign"] = df["date"].dt.strftime("%Y-%m")
    df = add_season(df.reset_index(drop=True))
    log.append(dict(source=region, item="rows used", n=len(df), values=f"stations={df['station'].nunique()} groups={df['group'].nunique()}"))
    return df, log


def hk_files() -> list[Path]:
    return sorted((paths.FOREIGN_DATA_DIR / "hk_epd").glob("marine-historical-*-en.csv"))


def harmonise_hk(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Surface-only HK EPD frame in the common schema (pure; used by tests)."""
    raw = raw[raw["Depth"].astype(str).str.strip() == "Surface Water"].copy()
    out = pd.DataFrame({"source": "hk", "region": "hk", "station": raw["Station"].astype(str),
                        "date": pd.to_datetime(raw["Dates"])})
    log = []
    for prefix, name in HK_COLUMNS.items():
        cols = [c for c in raw.columns if c.startswith(prefix)]
        if prefix == "pH":
            cols = [c for c in raw.columns if c.strip() == "pH"]
        if len(cols) != 1:
            raise KeyError(f"HK column for {prefix!r}: {cols}")
        vals, cens = parse_censored(raw[cols[0]])
        if name == "PO4":
            vals = vals.where(~cens)  # censored PO4 is not a usable target
        if cens.any():
            log.append(dict(source="hk", item=f"{name} censored '<LOD'", n=int(cens.sum()),
                            values="excluded" if name == "PO4" else "set to LOD/2"))
        out[name] = vals.to_numpy()
    out["group"] = out["station"]
    log += screen_targets(out, "hk")
    out["month"] = out["date"].dt.month
    out["year"] = out["date"].dt.year
    out["campaign"] = out["date"].dt.strftime("%Y-%m")
    return add_season(out.reset_index(drop=True)), log


def load_hk() -> tuple[pd.DataFrame, list[dict]]:
    raw = pd.concat([pd.read_csv(f, encoding="utf-8-sig", dtype=str) for f in hk_files()], ignore_index=True)
    df, log = harmonise_hk(raw)
    log.insert(0, dict(source="hk", item="surface rows", n=len(df), values=f"stations={df['station'].nunique()}"))
    return df, log


def station_profile(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("station")
    mt = df.groupby(["station", "month"])["Temperature"].median().groupby("station")
    return pd.DataFrame({
        "med_sal": g["Salinity"].median(),
        "temp_amp": mt.quantile(0.9) - mt.quantile(0.1),
        "med_logtss": np.log(g["TSS"].median().clip(lower=0.1)),
        "med_ph": g["pH"].median(),
        "n": g.size(),
    })


def select_similar_hk(hk: pd.DataFrame, vn: pd.DataFrame) -> pd.DataFrame:
    """Pre-defined similarity (no VN target used). Returns HK profile table with 'selected'."""
    prof = station_profile(hk)
    vprof = station_profile(vn)
    keys = ["temp_amp", "med_logtss", "med_ph"]
    ref = vprof[keys].median()
    scale = prof[keys].std().replace(0, 1.0)
    prof["distance"] = np.sqrt((((prof[keys] - ref) / scale) ** 2).sum(axis=1))
    prof["marine"] = prof["med_sal"] >= HK_MARINE_SAL
    marine = prof[prof["marine"]].sort_values("distance")
    keep = set(marine.index[: int(np.ceil(len(marine) / 2))])
    prof["selected"] = prof.index.isin(keep)
    for k in keys:
        prof[f"vn_ref_{k}"] = ref[k]
    return prof.sort_values("distance")


def load_nerrs_daily(seed: int = SEED) -> pd.DataFrame:
    from experiments import nerrs_multi as nm

    var_map = {"Temp": "Temperature", "Sal": "Salinity", "DO_mgl": "DO", "pH": "pH"}
    pieces = []
    for code, res in nm.RESERVES.items():
        wq, _ = nm.load_wq_hourly(res)
        wq = wq[wq["variable"].isin(var_map)]
        wq["day"] = pd.to_datetime(wq["time_lst"]).dt.floor("D")
        agg = wq.groupby(["station", "day", "variable"])["value"].agg(["mean", "count"]).reset_index()
        agg = agg[agg["count"] >= 18]
        wide = agg.pivot_table(index=["station", "day"], columns="variable", values="mean").reset_index()
        wide = wide.rename(columns=var_map)
        wide["station"] = code + wide["station"].astype(str)
        pieces.append(wide)
    d = pd.concat(pieces, ignore_index=True)
    d["ym"] = d["day"].dt.to_period("M")
    rng = np.random.default_rng(seed)
    d = d.iloc[rng.permutation(len(d))].groupby(["station", "ym"], sort=True).head(1)
    out = pd.DataFrame({"source": "nerrs", "region": "nerrs", "station": d["station"], "date": d["day"]})
    for c in ("Temperature", "pH", "Salinity", "DO"):
        out[c] = d[c].to_numpy() if c in d.columns else np.nan
    out["TAN"] = np.nan
    out["TSS"] = np.nan
    out["PO4"] = np.nan
    out["Transparency"] = np.nan
    out["group"] = out["station"]
    out["month"] = out["date"].dt.month
    out["year"] = out["date"].dt.year
    out["campaign"] = out["date"].dt.strftime("%Y-%m")
    out = out[out["pH"].between(6.0, 9.5) | out["pH"].isna()]
    return add_season(out.reset_index(drop=True))


# ------------------------------------------------------------------ splits
def group_folds(groups: pd.Series, n_folds: int | None, seed: int) -> list[np.ndarray]:
    """List of group-label arrays, one per fold. One group per fold if n_folds is None."""
    uniq = np.array(sorted(groups.unique()))
    if n_folds is None or n_folds >= len(uniq):
        return [np.array([g]) for g in uniq]
    rng = np.random.default_rng(seed)
    return [np.sort(a) for a in np.array_split(uniq[rng.permutation(len(uniq))], n_folds)]


def make_splits(df: pd.DataFrame, kind: str, n_folds: int | None = None, seed: int = SEED):
    """Yield (fold_id, train_index, test_index) over df.index labels."""
    if kind == "loso":
        for i, gs in enumerate(group_folds(df["group"], n_folds, seed)):
            te = df["group"].isin(gs)
            yield f"loso{i:02d}", df.index[~te], df.index[te]
    elif kind == "time":
        last = int(df["year"].max())
        yield f"time{last}", df.index[df["year"] < last], df.index[df["year"] == last]
    elif kind == "season":
        wet = df["month"].isin(WET_MONTHS)
        yield "season_wet_to_dry", df.index[wet], df.index[~wet]
    else:
        raise ValueError(kind)


def other_region_rows(other: pd.DataFrame, kind: str, last_year: int) -> pd.DataFrame:
    """Rows of the other VN region that respect the same split rule (no later year / no test season)."""
    if kind == "time":
        return other[other["year"] < last_year]
    if kind == "season":
        return other[other["month"].isin(WET_MONTHS)]
    return other


def inner_folds(train: pd.DataFrame, seed: int) -> list[tuple[pd.Index, pd.Index]]:
    key = "group" if train["group"].nunique() >= INNER_FOLDS else "campaign"
    folds = group_folds(train[key], INNER_FOLDS, seed)
    return [(train.index[~train[key].isin(g)], train.index[train[key].isin(g)]) for g in folds]


# ------------------------------------------------------------------ models
def xgb_fit(X, y, w=None, base=None):
    from xgboost import XGBRegressor

    m = XGBRegressor(**XGB_PARAMS)
    m.fit(np.asarray(X, float), np.asarray(y, float), sample_weight=w,
          xgb_model=None if base is None else base.get_booster())
    return m


def _xy(df: pd.DataFrame, target: str, feats=FEATURES):
    d = df[df[target].notna()]
    return d[feats].to_numpy(float), d[target].to_numpy(float)


def fit_pooled(foreign: pd.DataFrame, vn: pd.DataFrame, target: str, w_vn: float, feats=FEATURES):
    Xf, yf = _xy(foreign, target, feats)
    Xv, yv = _xy(vn, target, feats)
    X = np.vstack([Xf, Xv])
    y = np.concatenate([yf, yv])
    w = np.concatenate([np.ones(len(yf)), np.full(len(yv), w_vn)])
    return xgb_fit(X, y, w)


def _log_inputs(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    for c in ("TAN", "TSS"):
        d[c] = np.log(d[c].clip(lower=1e-3))
    return d


def domain_stats(df: pd.DataFrame, target: str) -> dict:
    d = _log_inputs(df)
    st = {c: (d[c].mean(), d[c].std() or 1.0) for c in RAW_INPUTS}
    st[target] = (df[target].mean(), df[target].std() or 1.0)
    return st


def standardise(df: pd.DataFrame, st: dict, target: str) -> pd.DataFrame:
    d = _log_inputs(df)
    for c in RAW_INPUTS + [target]:
        mu, sd = st[c]
        d[c] = (d[c] - mu) / (sd if np.isfinite(sd) and sd > 0 else 1.0)
    return d


def tune_weight(foreign: pd.DataFrame, train: pd.DataFrame, target: str, seed: int, fit_predict) -> tuple[float, dict]:
    """Pick the VN weight with the lowest inner-fold MAE (training rows only)."""
    scores = {}
    tr = train[train[target].notna()]
    if tr["group"].nunique() < 2 and tr["campaign"].nunique() < 2:
        return WEIGHT_GRID[1], {}
    folds = inner_folds(tr, seed)
    for w in WEIGHT_GRID:
        errs = []
        for tr, va in folds:
            pred = fit_predict(foreign, train.loc[tr], train.loc[va], target, w)
            errs.append(np.abs(pred - train.loc[va, target].to_numpy(float)))
        scores[w] = float(np.mean(np.concatenate(errs)))
    best = min(WEIGHT_GRID, key=lambda w: (scores[w], w))
    return best, scores


def _pool_fp(foreign, tr, te, target, w):
    return fit_pooled(foreign, tr, target, w).predict(te[FEATURES].to_numpy(float))


def _da_fp(foreign, tr, te, target, w):
    sf = domain_stats(foreign[foreign[target].notna()], target)
    sv = domain_stats(tr[tr[target].notna()], target)
    m = fit_pooled(standardise(foreign, sf, target), standardise(tr, sv, target), target, w)
    z = m.predict(standardise(te, sv, target)[FEATURES].to_numpy(float))
    mu, sd = sv[target]
    return z * (sd if np.isfinite(sd) and sd > 0 else 1.0) + mu


class MLPTransfer:
    """sklearn MLP pretrained on foreign rows, then warm-start fine-tuned on VN rows."""

    def __init__(self, seed: int = SEED):
        self.seed = seed

    def _x(self, df):
        return (_log_inputs(df)[FEATURES].to_numpy(float) - self.mu) / self.sd

    def pretrain(self, foreign: pd.DataFrame, target: str):
        from sklearn.neural_network import MLPRegressor

        d = foreign.dropna(subset=RAW_INPUTS + [target])
        xl = _log_inputs(d)[FEATURES].to_numpy(float)
        self.mu, self.sd = xl.mean(0), xl.std(0) + 1e-9
        self.ymu, self.ysd = d[target].mean(), d[target].std() + 1e-9
        self.model = MLPRegressor(hidden_layer_sizes=(32, 16), alpha=1e-3, max_iter=300,
                                  random_state=self.seed, early_stopping=False)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.model.fit(self._x(d), (d[target].to_numpy(float) - self.ymu) / self.ysd)
        return self

    def finetune_predict(self, train: pd.DataFrame, test: pd.DataFrame, target: str) -> np.ndarray:
        m = copy.deepcopy(self.model)
        m.set_params(warm_start=True, max_iter=200, early_stopping=False, learning_rate_init=3e-4)
        d = train[train[target].notna()]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m.fit(self._x(d), (d[target].to_numpy(float) - self.ymu) / self.ysd)
        return m.predict(self._x(test)) * self.ysd + self.ymu


def pretrain_all(foreign: dict, target: str) -> dict:
    """Foreign-only models (no VN data) - fit once per target."""
    out = {}
    for name in ("hk", "hk_sim", "hknerrs"):
        f = foreign.get(name)
        if f is None or f[target].notna().sum() < 30:
            continue
        X, y = _xy(f, target)
        out[name] = xgb_fit(X, y)
    if "hk" in foreign:
        out["mlp"] = MLPTransfer().pretrain(foreign["hk"], target)
    return out


def runtime_features(region: str, target: str) -> list[str]:
    return ["TAN", "pH", "Temperature", "TSS"] + RUNTIME_SEASON.get((region, target), [])


def predict_variants(train: pd.DataFrame, test: pd.DataFrame, target: str, region: str, foreign: dict,
                     pre: dict, pooled_extra: pd.DataFrame | None, seed: int, variants=None) -> tuple[dict, dict]:
    """Predictions for every variant on ``test`` (index-aligned arrays) + tuning log."""
    tr = train[train[target].notna()]
    want = (lambda v: True) if variants is None else (lambda v: v in variants)
    Xte = test[FEATURES].to_numpy(float)
    preds, tune = {}, {}
    y = tr[target].to_numpy(float)
    if want("vn_median"):
        preds["vn_median"] = np.full(len(test), np.median(y))
    if want("vn_clim"):
        clim = tr.groupby("month")[target].mean()
        preds["vn_clim"] = test["month"].map(clim).fillna(y.mean()).to_numpy(float)
    if want("vn_runtime"):
        rf = runtime_features(region, target)
        preds["vn_runtime"] = xgb_fit(tr[rf], y).predict(test[rf].to_numpy(float))
    vn_model = None
    if want("vn_only") or want("stack_feat"):
        vn_model = xgb_fit(tr[FEATURES], y)
        preds["vn_only"] = vn_model.predict(Xte)
    if want("vn_pooled") and pooled_extra is not None:
        pe = pooled_extra[pooled_extra[target].notna()]
        both = pd.concat([tr, pe])
        preds["vn_pooled"] = xgb_fit(both[FEATURES], both[target]).predict(Xte)
    for name, var in (("hk", "hk_zero"), ("hk_sim", "hk_sim_zero"), ("hknerrs", "hknerrs_zero")):
        if name in pre and want(var):
            preds[var] = pre[name].predict(Xte)
    for fname, var, fp in (("hk", "pool_w", _pool_fp), ("hk_sim", "pool_w_sim", _pool_fp),
                           ("hknerrs", "pool_hknerrs_w", _pool_fp), ("hk", "da_std", _da_fp)):
        if fname in pre and want(var):
            w, scores = tune_weight(foreign[fname], tr, target, seed, fp)
            tune[var] = dict(weight=w, **{f"inner_mae_w{k:g}": v for k, v in scores.items()})
            preds[var] = fp(foreign[fname], tr, test, target, w)
    if "hk" in pre and want("ft_warm"):
        preds["ft_warm"] = xgb_fit(tr[FEATURES], y, base=pre["hk"]).predict(Xte)
    if "hk" in pre and want("stack_feat"):
        f_tr = np.column_stack([tr[FEATURES].to_numpy(float), pre["hk"].predict(tr[FEATURES].to_numpy(float))])
        f_te = np.column_stack([Xte, pre["hk"].predict(Xte)])
        preds["stack_feat"] = xgb_fit(f_tr, y).predict(f_te)
    if "mlp" in pre and want("mlp_ft"):
        preds["mlp_ft"] = pre["mlp"].finetune_predict(tr, test, target)
    if variants is not None:
        preds = {k: v for k, v in preds.items() if k in variants}
    return preds, tune


# ------------------------------------------------------------------ metrics
def point_metrics(y: np.ndarray, p: np.ndarray) -> dict:
    e = p - y
    ss = np.sum((y - y.mean()) ** 2)
    return dict(n=len(y), mae=float(np.mean(np.abs(e))), rmse=float(np.sqrt(np.mean(e ** 2))),
                r2=float(1 - np.sum(e ** 2) / ss) if ss > 0 else np.nan, bias=float(np.mean(e)))


def block_bootstrap_diff(abs_a: np.ndarray, abs_b: np.ndarray, blocks: np.ndarray, n_boot: int = N_BOOT,
                         seed: int = SEED) -> tuple[float, float, float]:
    """Mean of (a - b) and 95 % percentile CI, resampling whole blocks with replacement."""
    d = abs_a - abs_b
    codes, uniq = pd.factorize(blocks)
    k = len(uniq)
    sums = np.bincount(codes, weights=d, minlength=k)
    cnts = np.bincount(codes, minlength=k).astype(float)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, k, size=(n_boot, k))
    est = sums[draws].sum(1) / cnts[draws].sum(1)
    lo, hi = np.percentile(est, [2.5, 97.5])
    return float(d.mean()), float(lo), float(hi)


def class_scores(obs_event: np.ndarray, pred_event: np.ndarray) -> dict:
    tp = int(np.sum(obs_event & pred_event))
    fn = int(np.sum(obs_event & ~pred_event))
    fp = int(np.sum(~obs_event & pred_event))
    tn = int(np.sum(~obs_event & ~pred_event))
    n = tp + fn + fp + tn
    prev = (tp + fn) / n if n else np.nan
    po = (tp + tn) / n if n else np.nan
    pe = (((tp + fn) * (tp + fp)) + ((fp + tn) * (fn + tn))) / n ** 2 if n else np.nan
    return dict(n=n, events=tp + fn, prevalence=prev, tp=tp, fn=fn, fp=fp, tn=tn,
                pod=tp / (tp + fn) if tp + fn else np.nan,
                far=fp / (tp + fp) if tp + fp else np.nan,
                pofd=fp / (fp + tn) if fp + tn else np.nan,
                kappa=(po - pe) / (1 - pe) if n and pe < 1 else np.nan,
                degenerate=bool(n == 0 or prev < 0.05 or prev > 0.95 or tp + fn < 10))


def decide(diff: pd.DataFrame, classes: pd.DataFrame, variant: str) -> dict:
    """Apply the pre-registered decision rule for one variant within one (region, target)."""
    d = diff[diff["variant"] == variant].set_index("split")
    beat = [s for s in SPLITS if s in d.index and d.loc[s, "ci_hi_row"] < 0]
    robust = [s for s in beat if d.loc[s, "ci_hi_campaign"] < 0]
    worse = []
    for s in beat:
        c = classes[(classes["split"] == s) & (~classes["degenerate_obs"])]
        for ev in c["event"].unique():
            cv = c[c["event"] == ev].set_index("variant")
            if variant in cv.index and "vn_only" in cv.index:
                if cv.loc[variant, "pod"] < cv.loc["vn_only", "pod"] - POD_TOLERANCE:
                    worse.append(f"{s}:{ev}")
    useful = len(beat) >= 2 and not worse
    return dict(variant=variant, splits_beating_vn_only=";".join(beat), n_beat=len(beat),
                robust_campaign=";".join(robust), pod_worse=";".join(worse), useful=useful,
                robust=useful and len(robust) >= 2)


# ------------------------------------------------------------------ orchestration
def run_fold(region, target, kind, fold_id, train, test, foreign, pre, pooled_extra, seed, variants=None):
    preds, tune = predict_variants(train, test, target, region, foreign, pre, pooled_extra, seed, variants)
    t = test[test[target].notna()]
    keep = test[target].notna().to_numpy()
    rows = []
    for v, p in preds.items():
        rows.append(pd.DataFrame({"region": region, "target": target, "split": kind, "fold": fold_id,
                                  "variant": v, "row_id": t.index, "station": t["station"].to_numpy(),
                                  "group": t["group"].to_numpy(), "campaign": t["campaign"].to_numpy(),
                                  "month": t["month"].to_numpy(), "obs": t[target].to_numpy(float),
                                  "pred": np.asarray(p)[keep]}))
    tl = [dict(region=region, target=target, split=kind, fold=fold_id, variant=k, n_train=int(train[target].notna().sum()), **v)
          for k, v in tune.items()]
    return pd.concat(rows, ignore_index=True), tl


def foreign_for(target: str, hk: pd.DataFrame, hk_sim: pd.DataFrame, nerrs: pd.DataFrame | None) -> dict:
    f = {"hk": hk, "hk_sim": hk_sim}
    if nerrs is not None and target in NERRS_TARGETS:
        f["hknerrs"] = pd.concat([hk, nerrs], ignore_index=True)
    return f


def evaluate(pred: pd.DataFrame, regimes: dict) -> dict[str, pd.DataFrame]:
    keys = ["region", "target", "split"]
    met, diffs, cls, strata = [], [], [], []
    for (r, t, s), g in pred.groupby(keys):
        base = g[g["variant"] == "vn_only"].set_index("row_id")
        for v, gv in g.groupby("variant"):
            gv = gv.set_index("row_id")
            met.append(dict(region=r, target=t, split=s, variant=v, **point_metrics(gv["obs"].to_numpy(), gv["pred"].to_numpy())))
            gv["season"] = np.where(gv["month"].isin(WET_MONTHS), "wet_5_10", "dry_11_4")
            gv["regime"] = gv["station"].map(regimes.get(r, {})).fillna("n/a")
            for col in ("season", "regime"):
                for lvl, gg in gv.groupby(col):
                    strata.append(dict(region=r, target=t, split=s, variant=v, stratum=col, level=lvl, n=len(gg),
                                       bias=float((gg["pred"] - gg["obs"]).mean()),
                                       mae=float((gg["pred"] - gg["obs"]).abs().mean())))
            if v != "vn_only":
                b = base.loc[gv.index]
                ea, eb = (gv["pred"] - gv["obs"]).abs().to_numpy(), (b["pred"] - b["obs"]).abs().to_numpy()
                row = dict(region=r, target=t, split=s, variant=v, n=len(gv), mae_variant=ea.mean(), mae_vn_only=eb.mean())
                for name, blocks in (("row", gv.index.to_numpy()), ("campaign", gv["campaign"].to_numpy()),
                                     ("group", gv["group"].to_numpy())):
                    m, lo, hi = block_bootstrap_diff(ea, eb, blocks)
                    row.update({"diff": m, f"ci_lo_{name}": lo, f"ci_hi_{name}": hi, f"n_blocks_{name}": len(np.unique(blocks))})
                diffs.append(row)
            for ev, (tt, fn) in THRESHOLD_EVENTS.items():
                if tt != t:
                    continue
                o = fn(gv["obs"].to_numpy())
                c = class_scores(o, fn(gv["pred"].to_numpy()))
                c["degenerate_obs"] = c.pop("degenerate")
                cls.append(dict(region=r, target=t, split=s, variant=v, event=ev, **c))
    return dict(metrics=pd.DataFrame(met), diff_ci=pd.DataFrame(diffs), threshold_class=pd.DataFrame(cls),
                bias_strata=pd.DataFrame(strata))


def reproduce_runtime_cv(vn: dict) -> pd.DataFrame:
    """impute.py recipe (ungrouped LOGO by station, no target QC) vs cv_r2.json, + honest re-run."""
    from hap_shared.preprocessing import EXCLUDED_STATIONS, load_data
    from sklearn.metrics import r2_score

    stored = json.loads((paths.MODELS_DIR / "cv_r2.json").read_text(encoding="utf-8"))
    rows = []
    for region in ("haiphong", "quangninh"):
        raw = load_data(str(paths.clean_data(region)))
        raw = raw[~raw["Station"].isin(EXCLUDED_STATIONS)].dropna(subset=["NH3", "pH", "Temperature", "TSS"]).reset_index(drop=True)
        raw["month"] = raw["Quarter"].dt.month
        raw["m_sin"] = np.sin(2 * np.pi * raw["month"] / 12)
        raw["m_cos"] = np.cos(2 * np.pi * raw["month"] / 12)
        raw["TAN"] = raw["NH3"]
        for target in ("DO", "Salinity", "PO4", "Transparency"):
            if target not in raw.columns:
                continue
            feats = runtime_features(region, target)
            valid = raw[target].notna().to_numpy()
            X, y, g = raw[feats].to_numpy(float), raw[target].to_numpy(float), raw["Station"].to_numpy()
            P, T = [], []
            for st in np.unique(g):
                tr, te = (g != st) & valid, (g == st) & valid
                if tr.sum() < 5 or te.sum() == 0:
                    continue
                P.extend(xgb_fit(X[tr], y[tr]).predict(X[te]))
                T.extend(y[te])
            rows.append(dict(region=region, target=target, protocol="impute.py LOGO (ungrouped, raw targets)",
                             r2=round(float(r2_score(T, P)), 4), mae=float(np.mean(np.abs(np.array(P) - np.array(T)))),
                             stored_cv_r2=stored.get(region, {}).get("4feat", {}).get(target), n=len(T)))
    return pd.DataFrame(rows)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-name", default=RUN_NAME)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--no-nerrs", action="store_true", help="skip NERRS (HK-only foreign data)")
    ap.add_argument("--no-learning-curve", action="store_true")
    args = ap.parse_args(argv)

    from joblib import Parallel, delayed

    out = paths.EXPERIMENT_OUTPUT_DIR / args.run_name
    out.mkdir(parents=True, exist_ok=False)
    t0 = time.time()
    log = []
    vn = {}
    for region in ("haiphong", "quangninh"):
        vn[region], lg = load_vn(region)
        log += lg
    hk, lg = load_hk()
    log += lg
    nerrs = None
    if not args.no_nerrs:
        nerrs = load_nerrs_daily()
        log.append(dict(source="nerrs", item="station-month daily rows", n=len(nerrs), values=f"stations={nerrs['station'].nunique()}"))
        nerrs.to_csv(out / "nerrs_station_month_days.csv.gz", index=False)
    pd.DataFrame(UNIT_MAPPING).to_csv(out / "unit_mapping.csv", index=False)
    print(f"[load] {time.time() - t0:.0f}s", flush=True)

    rr = reproduce_runtime_cv(vn)
    rr.to_csv(out / "runtime_reproduction.csv", index=False)
    print(rr.to_string(), flush=True)

    sims, regimes = {}, {}
    for region in vn:
        prof = select_similar_hk(hk, vn[region])
        prof.insert(0, "vn_region", region)
        sims[region] = prof
        med = vn[region].groupby("station")["Salinity"].median()
        regimes[region] = pd.cut(med, [-1, 20, 28, 99], labels=["estuarine<20", "transition20-28", "marine>=28"]).astype(str).to_dict()
        if region == "haiphong":
            regimes[region] = {k: f"{v} (GLORYS)" for k, v in regimes[region].items()}
    pd.concat(sims.values()).to_csv(out / "hk_similar_stations.csv")
    pd.DataFrame(log).to_csv(out / "data_qc.csv", index=False)

    tasks, lc_tasks = [], []
    for region, target, role in EVAL_UNITS:
        df = vn[region]
        if df[target].notna().sum() < 30:
            continue
        hk_sim = hk[hk["station"].isin(sims[region].index[sims[region]["selected"]])]
        foreign = foreign_for(target, hk, hk_sim, nerrs)
        pre = pretrain_all(foreign, target)
        other = vn["quangninh" if region == "haiphong" else "haiphong"]
        if target == "Salinity" and region == "quangninh":
            other = other.iloc[0:0]  # HP salinity is GLORYS, never a target for QN
        last = int(df["year"].max())
        for kind in SPLITS:
            nf = QN_OUTER_FOLDS if region == "quangninh" else None
            for fold_id, tr, te in make_splits(df, kind, nf):
                args_ = (region, target, kind, fold_id, df.loc[tr], df.loc[te], foreign, pre,
                         other_region_rows(other, kind, last), SEED)
                tasks.append(args_)
                if kind == "loso" and role != "proxy_glorys" and not args.no_learning_curve:
                    for frac in LC_FRACTIONS:
                        for s in range(1 if frac == 1.0 else LC_SEEDS):
                            rng = np.random.default_rng(SEED + 1000 * s + int(frac * 100))
                            trd = df.loc[tr]
                            n = max(8, int(round(frac * len(trd))))
                            sub = trd.iloc[np.sort(rng.choice(len(trd), size=min(n, len(trd)), replace=False))]
                            lc_tasks.append(((region, target, kind, fold_id, sub, df.loc[te], foreign, pre, None, SEED,
                                              set(LC_VARIANTS)), dict(fraction=frac, seed=s, n_train=len(sub))))
    print(f"[tasks] {len(tasks)} folds, {len(lc_tasks)} learning-curve fits", flush=True)
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(run_fold)(*a) for a in tasks)
    pred = pd.concat([r[0] for r in res], ignore_index=True)
    tune = pd.DataFrame([x for r in res for x in r[1]])
    pred.to_csv(out / "predictions.csv.gz", index=False)
    tune.to_csv(out / "tuned_weights.csv", index=False)
    ev = evaluate(pred, regimes)
    for name, frame in ev.items():
        frame.to_csv(out / f"{name}.csv", index=False)
    dec = []
    for (r, t), g in ev["diff_ci"].groupby(["region", "target"]):
        c = ev["threshold_class"]
        c = c[(c["region"] == r) & (c["target"] == t)]
        role = {(a, b): x for a, b, x in EVAL_UNITS}[(r, t)]
        for v in sorted(g["variant"].unique()):
            dec.append(dict(region=r, target=t, role=role, primary=(v == PRIMARY_VARIANT), **decide(g, c, v)))
    pd.DataFrame(dec).to_csv(out / "decision.csv", index=False)
    print(f"[eval] {time.time() - t0:.0f}s", flush=True)

    if lc_tasks:
        lres = Parallel(n_jobs=args.jobs, verbose=2)(delayed(run_fold)(*a) for a, _ in lc_tasks)
        lrows = []
        for (a, meta), (p, _) in zip(lc_tasks, lres):
            p = p.assign(**meta)
            lrows.append(p)
        lp = pd.concat(lrows, ignore_index=True)
        lc = (lp.groupby(["region", "target", "fraction", "seed", "variant"])
              .apply(lambda g: pd.Series(point_metrics(g["obs"].to_numpy(), g["pred"].to_numpy())), include_groups=False)
              .reset_index())
        lc.to_csv(out / "learning_curve.csv", index=False)
        (lc.groupby(["region", "target", "fraction", "variant"])["mae"].agg(["mean", "std", "count"]).reset_index()
         .to_csv(out / "learning_curve_summary.csv", index=False))

    inputs = [paths.clean_data("haiphong"), paths.clean_data("quangninh"),
              paths.FOREIGN_DATA_DIR / "hk_epd" / "stations.csv", *hk_files(),
              paths.MODELS_DIR / "cv_r2.json"]
    manifest = dict(
        run=args.run_name, script="experiments/transfer_impute.py", created_utc=pd.Timestamp.now(tz='UTC').isoformat(),
        seed=SEED, xgb_params=XGB_PARAMS, weight_grid=WEIGHT_GRID, splits=SPLITS, primary_variant=PRIMARY_VARIANT,
        n_boot=N_BOOT, nerrs="not used" if nerrs is None else "8 reserves via experiments/nerrs_multi.py (raw files hashed in data/foreign/nerrs_ncei/*/download_manifest_*.csv)",
        inputs={str(p.relative_to(paths.DATA_DIR)) if paths.DATA_DIR in p.parents else str(p.relative_to(paths.PROJECT_ROOT)): sha256(p)
                for p in inputs},
        outputs={f.name: sha256(f) for f in sorted(out.iterdir()) if f.is_file()},
        seconds=round(time.time() - t0, 1),
    )
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"[done] {out} {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
