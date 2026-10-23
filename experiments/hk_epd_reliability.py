"""Hong Kong EPD analogue of the VN P0/P1 spatial-applicability test and the NERRS
direction-4 pilot (RL-12), under VN-like periodic (~monthly) sampling.

Question: if one station's measurement is used for another location, how does the
error grow with distance, and does it depend on whether the two stations share a
Water Control Zone (WCZ)? RL-12 found habitat > distance on 4 NERRS stations; HK
gives 94 stations in 10 WCZs.

Data (read-only): ``data/foreign/hk_epd/marine-historical-<year>-en.csv`` (surface
water only) and ``stations.csv`` (EPD official WGS84 points, WCZ).

Matching: for each ordered pair (anchor -> target) and each target sampling date,
the anchor sample with the smallest |lag| within +/-3 days is used (ties -> the
anchor sampled *before* the target). ``lag_days = target_date - anchor_date``.
WCZs are sampled on separate cruise days, so cross-zone rows are mostly lagged
while same-zone rows are mostly lag 0. The **primary same-vs-cross comparison is
lag 0 only**; the +/-3 d pooled version is secondary.

Methods
* ``persistence_in_space``: estimate(target, t) = anchor value (VN P0
  ``anchor_copy_observed_value``).
* ``calibrated_24m``: estimate = a + b * anchor, OLS on the pair's matched samples
  whose information date max(target_date, anchor_date) lies in [t - 730 d, t);
  >= 12 points. No look-ahead (also guards the rare <= 3 d re-sampling case).
  Needs target history: it models a site that had reference sampling (H4.4).
* Baselines per (target, date): ``zone_median_loo`` (median of the other
  same-zone stations sampled the same day), nearest same-zone / nearest any
  anchor copy, ``climatology_past`` (target's own same-month median from >= 3
  prior years; the "no transfer" baseline asked for in guide 19 section 5).

Tolerances: Temp 0.5 C, Sal 1 psu, DO 0.5 mg/L, pH 0.2 (as NERRS/RL-12), TSS
max(2 mg/L, 20 %), NH3 (un-ionised, as reported by EPD) max(30 %, 0.005 mg/L).
The NH3 floor is 10 % of the first cobia breakpoint (0.05 mg/L in
hap_shared/thresholds/cobia_thresholds.json; QCVN limit 0.1 in core/config.py) and
5x the EPD detection limit (0.001). HK NH3 sits at ~0.001-0.02 mg/L, so the
primary NH3 row passes almost trivially; ``NH3@rel30`` (relative only, censored
pairs dropped) is the strict secondary row.

Censoring: ``<DL`` strings are parsed explicitly (``censored`` flag, ``dl``); the
value used is DL/2 (primary rows). This biases the NH3 calibrated fit slightly;
NH3@rel30 excludes censored samples on either side.

Gates 80/90/95: lower bound of a percentile bootstrap that resamples **target
sampling dates** (cluster), >= 30 dates per cell (NERRS helpers). Seasons: wet
Apr-Sep, dry Oct-Mar. Optional rain stratum: ERA5 daily precipitation (Open-Meteo
archive) at the station centroid, sum of the 3 days strictly before sampling;
fetched once into ``data/foreign/hk_epd/derived/`` (write-once).

Run:  .venv\\Scripts\\python experiments\\hk_epd_reliability.py
Outputs: artifacts/experiments/hk-epd-reliability-20261016/ (refuses to overwrite).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
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
    prepare_output_dir,
    sha256,
)

RUN_NAME = "hk-epd-reliability-20261016"
HK_DIR = paths.DATA_DIR / "foreign" / "hk_epd"
DERIVED_DIR = HK_DIR / "derived"
YEARS = range(2015, 2026)
GATES = (0.80, 0.90, 0.95)
MIN_DATES = 30
N_BOOT = 1000
SEED = 20261016
MAX_LAG_DAYS = 3
CAL_WINDOW = "730D"
CAL_MIN_POINTS = 12
CLIM_MIN_YEARS = 3
RAIN_DAYS = 3
RAIN_HEAVY_MM = 20.0
RAIN_NONE_MM = 1.0
REGIME_DSAL_PSU = 2.0
BIN_EDGES = [0, 2, 5, 10, 20, np.inf]
BIN_LABELS = ["0-2", "2-5", "5-10", "10-20", ">20"]
BIN_UPPER = {"0-2": "2 km", "2-5": "5 km", "5-10": "10 km", "10-20": "20 km", ">20": ">20 km"}

# key -> (EPD source column)
SOURCE_COLUMNS = {
    "Temp": "Temperature (°C)",
    "Sal": "Salinity (psu)",
    "DO": "Dissolved Oxygen (mg/L)",
    "pH": "pH",
    "TSS": "Suspended Solids (mg/L)",
    "NH3": "Unionised Ammonia (mg/L)",
}
# evaluation key -> (value column, absolute tol, relative tol, drop censored)
TOLERANCES = {
    "Temp": ("Temp", 0.5, 0.0, False),
    "Sal": ("Sal", 1.0, 0.0, False),
    "DO": ("DO", 0.5, 0.0, False),
    "pH": ("pH", 0.2, 0.0, False),
    "TSS": ("TSS", 2.0, 0.20, False),
    "NH3": ("NH3", 0.005, 0.30, False),
    "NH3@rel30": ("NH3", 0.0, 0.30, True),
}


# ---------------------------------------------------------------- primitives
def parse_censored(series: pd.Series) -> pd.DataFrame:
    """'<x' -> value x/2, censored True, dl x. Numbers pass through."""
    text = series.astype("string").str.strip()
    is_cens = text.str.startswith("<").fillna(False).astype(bool)
    dl = pd.to_numeric(text.str.lstrip("<").where(is_cens), errors="coerce")
    value = pd.to_numeric(text.where(~is_cens), errors="coerce")
    value = value.where(~is_cens, dl / 2)
    return pd.DataFrame({"value": value.astype(float).to_numpy(), "censored": is_cens.to_numpy(),
                         "dl": dl.astype(float).to_numpy()}, index=series.index)


def within_tolerance(var_key: str, estimate, observed) -> np.ndarray:
    _, absolute, relative, _ = TOLERANCES[var_key]
    observed = np.asarray(observed, dtype=float)
    bound = np.maximum(absolute, relative * np.abs(observed))
    return np.abs(observed - np.asarray(estimate, dtype=float)) <= bound + 1e-12


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(a))


def distance_bin(km) -> np.ndarray:
    return pd.cut(np.asarray(km, dtype=float), BIN_EDGES, labels=BIN_LABELS, right=False).astype(str)


def season_of(dates) -> np.ndarray:
    return np.where(pd.DatetimeIndex(dates).month.isin(range(4, 10)), "wet", "dry")


def prior_rain_sum(rain: pd.Series, dates, days: int = RAIN_DAYS) -> pd.Series:
    """Sum of daily rain on the ``days`` days strictly before each date; NaN if any missing."""
    full = rain.asfreq("D")
    window = full.rolling(days, min_periods=days).sum().shift(1)
    return pd.Series(window.reindex(pd.DatetimeIndex(dates)).to_numpy(), index=pd.DatetimeIndex(dates))


# ---------------------------------------------------------------- pairing
def station_pairs(stations: pd.DataFrame) -> pd.DataFrame:
    s = stations[["station", "lat", "lon", "water_control_zone"]]
    p = s.merge(s, how="cross", suffixes=("_a", "_t"))
    p = p[p.station_a != p.station_t]
    return pd.DataFrame({
        "anchor": p.station_a.to_numpy(), "target": p.station_t.to_numpy(),
        "anchor_zone": p.water_control_zone_a.to_numpy(), "target_zone": p.water_control_zone_t.to_numpy(),
        "distance_km": haversine_km(p.lat_a, p.lon_a, p.lat_t, p.lon_t).round(3),
        "relation": np.where(p.water_control_zone_a.to_numpy() == p.water_control_zone_t.to_numpy(),
                             "same_zone", "cross_zone"),
    })


def match_pairs(obs: pd.DataFrame, pairs: pd.DataFrame, variables, max_lag_days: int = MAX_LAG_DAYS) -> pd.DataFrame:
    """One row per (anchor, target, target_date): nearest anchor sample within +/-max_lag_days."""
    cols = [c for c in obs.columns if c not in ("station", "date", "zone")]
    target = obs[["station", "date", *cols]].rename(columns={"station": "target", "date": "target_date",
                                                             **{c: f"t_{c}" for c in cols}})
    anchor = obs[["station", "date", *cols]].rename(columns={"station": "anchor", "date": "anchor_date",
                                                             **{c: f"a_{c}" for c in cols}})
    base = target.merge(pairs, on="target")
    parts = []
    for lag in range(-max_lag_days, max_lag_days + 1):
        shifted = base.assign(anchor_date=base["target_date"] - pd.Timedelta(days=lag))
        parts.append(shifted.merge(anchor, on=["anchor", "anchor_date"]))
    m = pd.concat(parts, ignore_index=True)
    m["lag_days"] = (m["target_date"] - m["anchor_date"]).dt.days.astype(int)
    m["_order"] = m["lag_days"].abs() * 2 + (m["lag_days"] < 0)
    m = (m.sort_values(["anchor", "target", "target_date", "_order"])
          .drop_duplicates(["anchor", "target", "target_date"]).drop(columns="_order"))
    return m.reset_index(drop=True)


# ---------------------------------------------------------------- estimators
def calibrated_estimates(frame: pd.DataFrame, window: str = CAL_WINDOW, min_points: int = CAL_MIN_POINTS) -> pd.Series:
    """a + b*x per (anchor, target), OLS on rows with info date in [t - window, t).

    ``frame`` needs anchor, target, target_date, x, y (optional anchor_date). The info
    date of a row is max(target_date, anchor_date): both values must be known
    strictly before the target date being estimated.
    """
    f = frame.dropna(subset=["x", "y"])
    out = pd.Series(np.nan, index=frame.index)
    if f.empty:
        return out
    t_days = (f["target_date"].to_numpy("datetime64[D]").astype(np.int64))
    a_days = (f["anchor_date"].to_numpy("datetime64[D]").astype(np.int64) if "anchor_date" in f else t_days)
    info = np.maximum(t_days, a_days)
    key = pd.factorize(f["anchor"].astype(str) + "|" + f["target"].astype(str))[0].astype(np.int64)
    scale = np.int64(10_000_000)
    combined = key * scale + info
    order = np.argsort(combined, kind="stable")
    x, y = f["x"].to_numpy(float)[order], f["y"].to_numpy(float)[order]
    sorted_comb = combined[order]
    cum = {name: np.concatenate([[0.0], np.cumsum(v)]) for name, v in
           (("n", np.ones_like(x)), ("x", x), ("y", y), ("xx", x * x), ("xy", x * y))}
    win = int(pd.Timedelta(window).days)
    hi = np.searchsorted(sorted_comb, key * scale + t_days, side="left")
    lo = np.searchsorted(sorted_comb, key * scale + t_days - win, side="left")
    s = {k: v[hi] - v[lo] for k, v in cum.items()}
    n = s["n"]
    with np.errstate(invalid="ignore", divide="ignore"):
        mx, my = s["x"] / n, s["y"] / n
        var_x = s["xx"] / n - mx ** 2
        cov = s["xy"] / n - mx * my
        slope = np.where(var_x > 1e-12, cov / var_x, 1.0)  # flat anchor -> offset-only map
        est = my - slope * mx + slope * f["x"].to_numpy(float)
    est = np.where(n >= min_points, est, np.nan)
    out.loc[f.index] = est
    return out


def zone_median_loo(obs: pd.DataFrame, zones: dict, var: str) -> pd.DataFrame:
    """Median of the *other* same-zone stations sampled the same day."""
    o = obs[["station", "date", var]].dropna().assign(zone=lambda d: d["station"].map(zones))
    m = o.merge(o, on=["zone", "date"], suffixes=("", "_other"))
    m = m[m["station"] != m["station_other"]]
    g = m.groupby(["station", "date"])[f"{var}_other"].agg(["median", "count"]).reset_index()
    return g.rename(columns={"median": "estimate", "count": "n_others"})


def climatology_past(obs: pd.DataFrame, var: str, min_years: int = CLIM_MIN_YEARS) -> pd.DataFrame:
    """Target's own same-calendar-month median over strictly earlier years."""
    o = obs[["station", "date", var]].dropna().copy()
    o["year"], o["month"] = o["date"].dt.year, o["date"].dt.month
    est = pd.Series(np.nan, index=o.index)
    for _, grp in o.groupby(["station", "month"]):
        years, values = grp["year"].to_numpy(), grp[var].to_numpy(float)
        for i, idx in enumerate(grp.index):
            past = years < years[i]
            if len(np.unique(years[past])) >= min_years:
                est[idx] = np.median(values[past])
    o["estimate"] = est
    return o[["station", "date", "estimate"]].sort_index()


# ---------------------------------------------------------------- summaries
def summarise_cells(rows: pd.DataFrame, keys, n_boot: int = N_BOOT, seed: int = SEED) -> pd.DataFrame:
    """Pooled share within tolerance per cell; CI by resampling target dates."""
    out = []
    for cell, grp in rows.groupby(keys, observed=True, sort=True):
        per_date = grp.groupby("target_date")["within"].agg(["sum", "count"])
        share, lo, hi = bootstrap_share(per_date["sum"], per_date["count"], n_boot=n_boot, seed=seed)
        abs_err = grp["err"].abs()
        rec = dict(zip(keys, cell if isinstance(cell, tuple) else (cell,)))
        rec.update({"n_rows": int(len(grp)), "n_dates": int(len(per_date)),
                    "mae": round(float(abs_err.mean()), 4), "bias_obs_minus_est": round(float(grp["err"].mean()), 4),
                    "p95_abs_err": round(float(abs_err.quantile(0.95)), 4),
                    "share_within": round(share, 4), "share_ci_lo": round(lo, 4), "share_ci_hi": round(hi, 4)})
        for g in GATES:
            rec[f"gate_{int(g * 100)}"] = gate_status(lo, len(per_date), g, min_days=MIN_DATES)
        out.append(rec)
    return pd.DataFrame(out)


def reliability_radius(cells: pd.DataFrame, keys, gate_col: str) -> pd.DataFrame:
    """Upper edge of the last contiguous passing distance bin, starting at 0-2 km."""
    out = []
    for cell, grp in cells.groupby(keys, sort=True):
        status = grp.set_index("distance_bin")[gate_col].to_dict()
        radius, stop = "0 km", "all_pass"
        for i, label in enumerate(BIN_LABELS):
            st = status.get(label, "insufficient")
            if st == "pass":
                radius = BIN_UPPER[label]
                continue
            if st == "insufficient" and i == 0:
                radius = "insufficient"
            stop = f"{st}@{label}"
            break
        rec = dict(zip(keys, cell if isinstance(cell, tuple) else (cell,)))
        rec.update({"gate": gate_col, "radius": radius, "stop": stop})
        out.append(rec)
    return pd.DataFrame(out)


# ---------------------------------------------------------------- loading
def load_observations(data_dir: Path = HK_DIR, years=YEARS) -> tuple[pd.DataFrame, pd.DataFrame, list[Path]]:
    files = [data_dir / f"marine-historical-{y}-en.csv" for y in years]
    files = [f for f in files if f.exists()]
    raw = pd.concat([pd.read_csv(f, dtype=str, encoding="utf-8-sig") for f in files], ignore_index=True)
    raw = raw[raw["Depth"] == "Surface Water"].copy()
    obs = pd.DataFrame({"station": raw["Station"].to_numpy(), "zone": raw["Water Control Zone"].to_numpy(),
                        "date": pd.to_datetime(raw["Dates"]).to_numpy()})
    cens_rows = []
    for key, col in SOURCE_COLUMNS.items():
        parsed = parse_censored(raw[col].reset_index(drop=True))
        obs[key] = parsed["value"].to_numpy()
        obs[f"{key}_cens"] = parsed["censored"].to_numpy()
        yr = obs["date"].dt.year
        for year, idx in obs.groupby(yr).groups.items():
            p = parsed.loc[idx]
            cens_rows.append({"variable": key, "year": int(year), "n_rows": len(p),
                              "n_missing": int(p["value"].isna().sum()), "n_censored": int(p["censored"].sum()),
                              "censored_share": round(float(p["censored"].mean()), 4),
                              "detection_limits": ";".join(sorted({f"{v:g}" for v in p["dl"].dropna()}))})
    obs = obs.drop_duplicates(["station", "date"]).sort_values(["station", "date"]).reset_index(drop=True)
    return obs, pd.DataFrame(cens_rows), files


def load_or_fetch_rain(lat: float, lon: float, start: str, end: str, derived_dir: Path = DERIVED_DIR,
                       allow_fetch: bool = True) -> tuple[pd.Series | None, dict]:
    name = f"open_meteo_era5_precip_daily_{lat:.3f}_{lon:.3f}_{start}_{end}.csv"
    path = derived_dir / name
    url = ("https://archive-api.open-meteo.com/v1/archive?"
           f"latitude={lat:.3f}&longitude={lon:.3f}&start_date={start}&end_date={end}"
           "&daily=precipitation_sum&models=era5&timezone=Asia%2FHong_Kong")
    meta = {"file": str(path.relative_to(paths.PROJECT_ROOT)).replace("\\", "/")
            if path.is_relative_to(paths.PROJECT_ROOT) else str(path), "url": url}
    if not path.exists():
        if not allow_fetch:
            return None, {**meta, "status": "absent_no_fetch"}
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            daily = pd.DataFrame({"date": payload["daily"]["time"], "precip_mm": payload["daily"]["precipitation_sum"]})
        except Exception as exc:  # network failure must not block the deliverable
            return None, {**meta, "status": f"fetch_failed: {exc!r}"}
        derived_dir.mkdir(parents=True, exist_ok=True)
        with open(path, "x", encoding="utf-8", newline="") as handle:  # write-once
            daily.to_csv(handle, index=False)
        meta_path = path.with_suffix(".json")
        if not meta_path.exists():
            meta_path.write_text(json.dumps({"url": url, "fetched_utc": datetime.now(timezone.utc).isoformat(
                timespec="seconds"), "grid_lat": payload.get("latitude"), "grid_lon": payload.get("longitude")},
                indent=2), encoding="utf-8")
    daily = pd.read_csv(path, parse_dates=["date"])
    rain = daily.set_index("date")["precip_mm"].astype(float)
    return rain, {**meta, "status": "ok", "sha256": sha256(path), "n_days": int(rain.notna().sum())}


# ---------------------------------------------------------------- evaluation
def evaluation_rows(matches: pd.DataFrame, var_key: str) -> pd.DataFrame:
    col, _, _, drop_cens = TOLERANCES[var_key]
    keep = ["anchor", "target", "target_date", "anchor_date", "lag_days", "distance_km", "distance_bin",
            "relation", "regime_relation", "season", "rain3d"]
    f = matches[[c for c in keep if c in matches] + [f"a_{col}", f"t_{col}", f"a_{col}_cens", f"t_{col}_cens"]]
    f = f.dropna(subset=[f"a_{col}", f"t_{col}"])
    if drop_cens:
        f = f[~(f[f"a_{col}_cens"].astype(bool) | f[f"t_{col}_cens"].astype(bool))]
    f = f.rename(columns={f"a_{col}": "x", f"t_{col}": "y"})
    cal = calibrated_estimates(f)
    frames = []
    for method, est in (("persistence_in_space", f["x"]), ("calibrated_24m", cal)):
        r = f.assign(method=method, est=est.to_numpy()).dropna(subset=["est"])
        r = r.assign(err=r["y"] - r["est"], within=within_tolerance(var_key, r["est"], r["y"]))
        frames.append(r)
    out = pd.concat(frames, ignore_index=True)
    out["variable"] = var_key
    out["lag_class"] = np.where(out["lag_days"] == 0, "lag0", "lag1-3")
    return out


LAG_SCOPES = {"lag0": lambda d: d["lag_days"] == 0, "lag0-3": lambda d: d["lag_days"].abs() <= 3,
              "lag1-3": lambda d: d["lag_days"] != 0}


def cell_table(rows: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for scope, cond in LAG_SCOPES.items():
        scoped = rows[cond(rows)]
        for season in ("all", "wet", "dry"):
            sub = scoped if season == "all" else scoped[scoped["season"] == season]
            if sub.empty:
                continue
            t = summarise_cells(sub, ["variable", "method", "relation", "distance_bin"])
            parts.append(t.assign(lag_scope=scope, season=season))
    t = pd.concat(parts, ignore_index=True)
    first = ["variable", "method", "lag_scope", "season", "relation", "distance_bin"]
    t["distance_bin"] = pd.Categorical(t["distance_bin"], BIN_LABELS, ordered=True)
    return t[first + [c for c in t.columns if c not in first]].sort_values(first).reset_index(drop=True)


def relation_differences(rows: pd.DataFrame, column: str = "relation", a: str = "same_zone",
                         b: str = "cross_zone") -> pd.DataFrame:
    """share(a) - share(b) per distance bin at lag 0; target dates resampled jointly."""
    out = []
    lag0 = rows[rows["lag_days"] == 0]
    for var in lag0["variable"].unique():
        for method in lag0["method"].unique():
            for season in ("all", "wet", "dry"):
                sub = lag0[(lag0["variable"] == var) & (lag0["method"] == method)]
                if season != "all":
                    sub = sub[sub["season"] == season]
                for label in BIN_LABELS:
                    part = sub[sub["distance_bin"] == label]
                    agg = (part.assign(w=part["within"].astype(int), n=1).groupby(["target_date", column])[["w", "n"]]
                           .sum().unstack(column, fill_value=0))
                    if ("n", a) not in agg or ("n", b) not in agg:
                        continue
                    da, db = int((agg[("n", a)] > 0).sum()), int((agg[("n", b)] > 0).sum())
                    if da < 10 or db < 10:
                        continue
                    diff, lo, hi = bootstrap_share_difference(agg[("w", a)], agg[("n", a)], agg[("w", b)],
                                                              agg[("n", b)], n_boot=N_BOOT, seed=SEED)
                    out.append({"variable": var, "method": method, "season": season, "distance_bin": label,
                                "split": column, "a": a, "b": b, "dates_a": da, "dates_b": db,
                                "rows_a": int(agg[("n", a)].sum()), "rows_b": int(agg[("n", b)].sum()),
                                "share_a": round(agg[("w", a)].sum() / agg[("n", a)].sum(), 4),
                                "share_b": round(agg[("w", b)].sum() / agg[("n", b)].sum(), 4),
                                "diff_a_minus_b": round(diff, 4), "diff_ci_lo": round(lo, 4), "diff_ci_hi": round(hi, 4)})
    return pd.DataFrame(out)


def salinity_regime(obs: pd.DataFrame, pairs: pd.DataFrame, threshold_psu: float = REGIME_DSAL_PSU) -> pd.DataFrame:
    """Habitat proxy: |difference of wet-season median surface salinity| < threshold -> similar.

    Descriptive stratifier computed on all years (a static site descriptor, not a
    forecast feature). Separates Pearl-River-plume stations (Deep Bay, North
    Western) from oceanic ones independently of the administrative WCZ.
    """
    wet = obs[season_of(obs["date"]) == "wet"].groupby("station")["Sal"].median()
    d = (pairs["anchor"].map(wet) - pairs["target"].map(wet)).abs()
    return pairs.assign(wet_sal_median_diff=d.round(2),
                        regime_relation=np.where(d < threshold_psu, "similar_regime", "different_regime"))


def pair_summary(rows: pd.DataFrame) -> pd.DataFrame:
    g = rows.assign(abs_err=rows["err"].abs()).groupby(
        ["variable", "method", "anchor", "target", "relation", "distance_km"], observed=True)
    out = g.agg(n=("within", "size"), n_lag0=("lag_days", lambda s: int((s == 0).sum())),
                share_within=("within", "mean"), mae=("abs_err", "mean"), bias_obs_minus_est=("err", "mean"),
                first=("target_date", "min"), last=("target_date", "max")).reset_index()
    return out.round({"share_within": 4, "mae": 4, "bias_obs_minus_est": 4})


def baseline_table(obs: pd.DataFrame, matches: pd.DataFrame, rows_by_var: dict, zones: dict) -> pd.DataFrame:
    """Per (target, date) estimators compared on the common set where all exist."""
    out = []
    for var_key, rows in rows_by_var.items():
        col, _, _, drop_cens = TOLERANCES[var_key]
        o = obs[["station", "date", col, f"{col}_cens"]].dropna(subset=[col])
        if drop_cens:
            o = o[~o[f"{col}_cens"].astype(bool)]
        truth = o.rename(columns={"station": "target", "date": "target_date", col: "y"})[["target", "target_date", "y"]]
        ests = {}
        zm = zone_median_loo(o, zones, col)
        ests["zone_median_loo"] = zm.rename(columns={"station": "target", "date": "target_date"})
        cl = climatology_past(o, col)
        ests["climatology_past"] = cl.rename(columns={"station": "target", "date": "target_date"})
        for label, cond in (("nearest_same_zone_lag0", (rows["relation"] == "same_zone") & (rows["lag_days"] == 0)),
                            ("nearest_any_pm3d", rows["lag_days"].abs() <= 3)):
            for method, suffix in (("persistence_in_space", "copy"), ("calibrated_24m", "calibrated")):
                r = rows[cond & (rows["method"] == method)]
                r = r.assign(_abs_lag=r["lag_days"].abs())
                r = r.sort_values(["target", "target_date", "distance_km", "_abs_lag"]).drop_duplicates(
                    ["target", "target_date"])
                ests[f"{label}_{suffix}"] = r[["target", "target_date", "est"]].rename(columns={"est": "estimate"})
        common = truth[["target", "target_date"]]
        for e in ests.values():
            common = common.merge(e[["target", "target_date"]].dropna(), on=["target", "target_date"])
        common = common.drop_duplicates()
        for name, e in ests.items():
            r = (common.merge(truth, on=["target", "target_date"]).merge(e[["target", "target_date", "estimate"]],
                                                                        on=["target", "target_date"]))
            r = r.assign(err=r["y"] - r["estimate"], within=within_tolerance(var_key, r["estimate"], r["y"]),
                         season=season_of(r["target_date"]))
            for season in ("all", "wet", "dry"):
                sub = r if season == "all" else r[r["season"] == season]
                t = summarise_cells(sub.assign(variable=var_key, estimator=name), ["variable", "estimator"])
                out.append(t.assign(season=season, common_set_rows=len(common)))
    return pd.concat(out, ignore_index=True)


def rain_table(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    sub = rows[(rows["lag_days"] == 0) & rows["rain3d"].notna()]
    cells = summarise_cells(sub, ["variable", "method", "relation", "rain3d"])
    effects = []
    for (var, method, rel), grp in sub.groupby(["variable", "method", "relation"]):
        for scope in ("all", "wet"):
            g = grp if scope == "all" else grp[grp["season"] == "wet"]
            agg = (g.assign(w=g["within"].astype(int), n=1).groupby(["target_date", "rain3d"])[["w", "n"]].sum()
                   .unstack("rain3d", fill_value=0))
            if ("n", "heavy") not in agg or ("n", "none") not in agg:
                continue
            da, db = int((agg[("n", "heavy")] > 0).sum()), int((agg[("n", "none")] > 0).sum())
            if da < 10 or db < 10:
                continue
            diff, lo, hi = bootstrap_share_difference(agg[("w", "heavy")], agg[("n", "heavy")],
                                                      agg[("w", "none")], agg[("n", "none")], n_boot=N_BOOT, seed=SEED)
            effects.append({"variable": var, "method": method, "relation": rel, "scope": scope,
                            "dates_heavy": da, "dates_none": db, "diff_heavy_minus_none": round(diff, 4),
                            "diff_ci_lo": round(lo, 4), "diff_ci_hi": round(hi, 4)})
    return cells, pd.DataFrame(effects)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME)
    parser.add_argument("--data-dir", type=Path, default=HK_DIR)
    parser.add_argument("--no-rain-fetch", action="store_true", help="use cached rain only; never call Open-Meteo")
    args = parser.parse_args(argv)
    out = prepare_output_dir(args.output_dir)

    stations = pd.read_csv(args.data_dir / "stations.csv", encoding="utf-8")
    zones = stations.set_index("station")["water_control_zone"].to_dict()
    obs, censoring, files = load_observations(args.data_dir)
    zone_mismatch = int((obs["zone"] != obs["station"].map(zones)).sum())
    pairs = station_pairs(stations)
    pairs["distance_bin"] = distance_bin(pairs["distance_km"])
    pairs = salinity_regime(obs, pairs)

    matches = match_pairs(obs.drop(columns="zone"), pairs, list(SOURCE_COLUMNS))
    matches["season"] = season_of(matches["target_date"])
    lat, lon = float(stations["lat"].mean()), float(stations["lon"].mean())
    rain, rain_meta = load_or_fetch_rain(round(lat, 3), round(lon, 3), "2014-12-01", "2025-12-31",
                                         derived_dir=args.data_dir / "derived", allow_fetch=not args.no_rain_fetch)
    if rain is not None:
        r3 = prior_rain_sum(rain, matches["target_date"]).to_numpy()
        matches["rain3d_mm"] = r3
        matches["rain3d"] = np.select([np.isnan(r3), r3 < RAIN_NONE_MM, r3 < RAIN_HEAVY_MM],
                                      [None, "none", "light"], "heavy")
        matches.loc[np.isnan(r3), "rain3d"] = None
    else:
        matches["rain3d"] = None

    lag_dist = (matches.groupby(["relation", "lag_days"]).size().rename("n_rows").reset_index())
    lag_dist["share_within_relation"] = (lag_dist["n_rows"] / lag_dist.groupby("relation")["n_rows"].transform("sum")).round(4)
    bin_counts = (matches.assign(lag0=matches["lag_days"] == 0)
                  .groupby(["relation", "distance_bin", "lag0"])
                  .agg(n_rows=("target", "size"), n_target_dates=("target_date", "nunique"))
                  .reset_index())
    station_pair_counts = pairs.groupby(["relation", "regime_relation", "distance_bin"]).size().rename("n_ordered_station_pairs").reset_index()

    rows_by_var, cells, diffs, pair_tabs, rain_cells, rain_effects, regime_cells, regime_only = {}, [], [], [], [], [], [], []
    for var_key in TOLERANCES:
        rows = evaluation_rows(matches, var_key)
        rows_by_var[var_key] = rows
        cells.append(cell_table(rows))
        diffs.append(relation_differences(rows))
        diffs.append(relation_differences(rows, "regime_relation", "similar_regime", "different_regime"))
        lag0 = rows[rows["lag_days"] == 0]
        regime_cells.append(summarise_cells(lag0, ["variable", "method", "relation", "regime_relation", "distance_bin"]))
        for season in ("all", "wet", "dry"):
            sub = lag0 if season == "all" else lag0[lag0["season"] == season]
            regime_only.append(summarise_cells(sub, ["variable", "method", "regime_relation", "distance_bin"])
                               .assign(lag_scope="lag0", season=season))
        pair_tabs.append(pair_summary(rows))
        if rain is not None:
            c, e = rain_table(rows)
            rain_cells.append(c)
            rain_effects.append(e)
        print(f"{var_key}: {len(rows)} evaluation rows", flush=True)
    cells = pd.concat(cells, ignore_index=True)
    diffs = pd.concat(diffs, ignore_index=True)
    radius = pd.concat([reliability_radius(cells, ["variable", "method", "lag_scope", "season", "relation"], f"gate_{int(g * 100)}")
                        for g in GATES], ignore_index=True).assign(split="water_control_zone")
    regime_only = pd.concat(regime_only, ignore_index=True)
    radius_regime = pd.concat([reliability_radius(regime_only, ["variable", "method", "lag_scope", "season", "regime_relation"],
                                                  f"gate_{int(g * 100)}") for g in GATES], ignore_index=True)
    radius = pd.concat([radius, radius_regime.rename(columns={"regime_relation": "relation"})
                        .assign(split="salinity_regime")], ignore_index=True)
    baselines = baseline_table(obs, matches, rows_by_var, zones)

    # ---------------------------------------------------------------- write
    stations.assign(n_surface_samples=stations["station"].map(obs.groupby("station").size())).to_csv(
        out / "stations.csv", index=False, encoding="utf-8")
    keep = [c for c in matches.columns if not c.endswith("_cens") or c.startswith(("a_NH3", "t_NH3", "a_TSS", "t_TSS"))]
    matches[keep].to_csv(out / "matched_samples.csv.gz", index=False, encoding="utf-8", compression="gzip")
    pd.concat(pair_tabs, ignore_index=True).to_csv(out / "pairs.csv", index=False, encoding="utf-8")
    cells.to_csv(out / "reliability_by_cell.csv", index=False, encoding="utf-8")
    radius.to_csv(out / "reliability_radius.csv", index=False, encoding="utf-8")
    diffs.to_csv(out / "split_differences_lag0.csv", index=False, encoding="utf-8")
    regime_only.to_csv(out / "reliability_by_regime_lag0.csv", index=False, encoding="utf-8")
    pd.concat(regime_cells, ignore_index=True).to_csv(out / "reliability_by_zone_and_regime_lag0.csv", index=False,
                                                      encoding="utf-8")
    baselines.to_csv(out / "baselines.csv", index=False, encoding="utf-8")
    lag_dist.to_csv(out / "lag_distribution.csv", index=False, encoding="utf-8")
    bin_counts.to_csv(out / "bin_counts.csv", index=False, encoding="utf-8")
    station_pair_counts.to_csv(out / "station_pair_counts.csv", index=False, encoding="utf-8")
    censoring.to_csv(out / "censoring_summary.csv", index=False, encoding="utf-8")
    if rain is not None:
        pd.concat(rain_cells, ignore_index=True).to_csv(out / "reliability_by_rain.csv", index=False, encoding="utf-8")
        pd.concat(rain_effects, ignore_index=True).to_csv(out / "rain_effects.csv", index=False, encoding="utf-8")

    rel = lambda p: str(p.relative_to(paths.PROJECT_ROOT)).replace("\\", "/") if p.is_relative_to(paths.PROJECT_ROOT) else str(p)  # noqa: E731
    manifest = {
        "run": RUN_NAME, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "experiments/hk_epd_reliability.py",
        "source": "HK EPD marine water quality historical data (surface water), stations from CSDI EPD layer",
        "parameters": {"years": list(YEARS), "depth": "Surface Water", "max_lag_days": MAX_LAG_DAYS,
                       "tie_rule": "min |lag|, then anchor sampled before target",
                       "tolerances": {k: {"column": v[0], "abs": v[1], "rel": v[2], "drop_censored": v[3]}
                                      for k, v in TOLERANCES.items()},
                       "censoring": "'<DL' -> DL/2 with flag; NH3@rel30 drops censored on either side",
                       "distance_bins_km": BIN_LABELS, "regime_rule": f"|wet-season median Sal diff| < {REGIME_DSAL_PSU} psu -> similar_regime (all years, descriptive)", "seasons": "wet Apr-Sep, dry Oct-Mar",
                       "gates": GATES, "gate_rule": "target-date bootstrap lower 95% bound >= gate, n_dates >= 30",
                       "min_dates": MIN_DATES, "n_boot": N_BOOT, "seed": SEED,
                       "calibrated": f"OLS a+b*x on rows with max(target,anchor date) in [t-{CAL_WINDOW}, t), >= {CAL_MIN_POINTS} points",
                       "climatology_min_years": CLIM_MIN_YEARS,
                       "rain": {"days_strictly_prior": RAIN_DAYS, "none_lt_mm": RAIN_NONE_MM, "heavy_ge_mm": RAIN_HEAVY_MM,
                                "centroid_lat_lon": [round(lat, 3), round(lon, 3)], **rain_meta}},
        "checks": {"n_surface_samples": int(len(obs)), "n_stations": int(obs["station"].nunique()),
                   "date_range": [str(obs["date"].min().date()), str(obs["date"].max().date())],
                   "samples_per_year": obs.groupby(obs["date"].dt.year).size().to_dict(),
                   "zone_label_mismatch_rows": zone_mismatch, "n_matched_rows": int(len(matches)),
                   "matched_rows_by_relation_lag0": matches.groupby(["relation", matches["lag_days"] == 0]).size()
                   .rename(index=lambda v: f"lag0={v}" if isinstance(v, (bool, np.bool_)) else v).to_dict().__repr__()},
        "inputs": [{"file": rel(p), "bytes": p.stat().st_size, "sha256": sha256(p)}
                   for p in [*files, args.data_dir / "stations.csv"]],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
