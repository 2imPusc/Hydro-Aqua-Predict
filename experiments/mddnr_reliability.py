"""Direction-4 reliability on Maryland DNR Eyes on the Bay ConMon (H4.4): can one
in-situ sensor (anchor) stand in for another location (target)?

Data: ``experiments/mddnr_load.py`` (15-min, hourly means of QC-good values,
>= 2 obs/h, EST). 2004-2009 station-years whose station had >= 4 other ConMon
stations active within 30 km (span-based selection; real overlap is counted
from the data). Co-located bottom sensors were dropped (surface kept).

Protocol (shared with RL-12 NERRS / RL-14 HK EPD):
* Tolerances Temp 0.5 C, Sal 1 psu, DO 0.5 mg/L, pH 0.2, Turb max(2 NTU, 20 %)
  (``nerrs_reliability.within_tolerance``).
* Ordered pairs (anchor -> target) with distance <= MAX_KM. Overlap: >= 1 year
  of joint data is rare because ConMon runs seasonal (Apr-Oct) deployments, so
  the inclusion rule is relaxed to >= 90 overlapping days per pair x variable
  (``overlap_tier`` in pairs.csv records 90d vs 365d).
* Transfers: ``raw`` (anchor value) and ``calibrated`` (a + b*anchor, OLS on the
  pair's strictly-past 30 days, >= 240 joint hours; NaN after each winter gap
  until 10 days of joint data exist -> calibrated n_days < raw n_days).
* Salinity regime: per station median hourly salinity in spring high flow
  (Apr-Jun) and late-summer low flow (Aug-Sep), all years pooled. Same regime
  if |delta spring median| < 2 psu; ``dsal`` = that |delta| (continuous).
* Gates 80/90/95: day-block bootstrap (500 resamples, seed 20261016) lower 95 %
  bound >= gate and >= 30 days. Cells pool pairs; the bootstrap resamples
  calendar dates (all pairs of one date move together -> conservative).
* Radius: upper edge of the last passing distance bin before the first failing
  bin, starting at 0-2 km; ``insufficient`` bins are skipped (counted in
  ``n_skipped``); 0 if the first sufficient bin fails; NaN if none sufficient.
* Regime vs distance: unordered pair reliability (mean of both directions) on
  z-scored distance and z-scored dsal: OLS on share and logistic on
  share >= 0.80 (pairs <= 30 km; plus a <= MAX_KM variant).
* Rain: ERA5 hourly precipitation (Open-Meteo archive) for the ERA5 0.25 deg
  cell containing each target station; prior 24 h (>= 10 mm vs < 1 mm) and prior
  72 h (>= 20 mm vs < 1 mm), windows strictly before the hour.
* Day/night from solar elevation at the target (EST = UTC-5); seasons DJF/MAM/JJA/SON.

Run:  .venv\\Scripts\\python experiments\\mddnr_reliability.py
Outputs: artifacts/experiments/mddnr-h4-reliability-20261017/ (refuses to overwrite).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import paths  # noqa: E402
from experiments import mddnr_load as ml  # noqa: E402
from experiments.nerrs_reliability import (  # noqa: E402
    bootstrap_share,
    bootstrap_share_difference,
    gate_status,
    prepare_output_dir,
    prior_window_sum,
    rolling_linear_transfer,
    sha256,
    solar_elevation_deg,
    within_tolerance,
)

RUN_NAME = "mddnr-h4-reliability-20261017"
DATASET = "mddnr"
VARIABLES = ("Temp", "Sal", "DO_mgl", "pH", "Turb")
GATES = (0.80, 0.90, 0.95)
MIN_DAYS = 30
N_BOOT = 500
SEED = 20261016
MIN_OVERLAP_DAYS = 90
YEAR_OVERLAP_DAYS = 365
MAX_KM = 50.0
REGIME_DSAL_PSU = 2.0
SPRING_MONTHS = (4, 5, 6)
LATE_SUMMER_MONTHS = (8, 9)
RAIN24_HEAVY_MM, RAIN72_HEAVY_MM, RAIN_NONE_MM = 10.0, 20.0, 1.0
BIN_EDGES = [0, 2, 5, 10, 20, 30, np.inf]
BIN_LABELS = ["0-2", "2-5", "5-10", "10-20", "20-30", ">30"]
BIN_UPPER_KM = {"0-2": 2.0, "2-5": 5.0, "5-10": 10.0, "10-20": 20.0, "20-30": 30.0}
RADIUS_BINS = BIN_LABELS[:-1]
TRANSFERS = ("raw", "calibrated")
DERIVED_DIR = ml.MDDNR_DIR / "derived"
RAIN_START, RAIN_END = "2004-01-01", "2009-12-31"


# ---------------------------------------------------------------- primitives
def distance_bin(km) -> np.ndarray:
    return pd.cut(np.asarray(km, dtype=float), BIN_EDGES, labels=BIN_LABELS, right=False).astype(str)


def season_of(index) -> np.ndarray:
    month = pd.DatetimeIndex(index).month
    return np.select([month.isin([12, 1, 2]), month.isin([3, 4, 5]), month.isin([6, 7, 8])],
                     ["DJF", "MAM", "JJA"], "SON")


def overlap_days(a: pd.Series, b: pd.Series) -> int:
    """Calendar days on which both series have >= 1 non-missing hour at the same time."""
    joint = pd.concat([a, b], axis=1).dropna()
    return int(joint.index.normalize().nunique())


def overlap_tier(n_days: int) -> str:
    if n_days >= YEAR_OVERLAP_DAYS:
        return "365d"
    return "90d" if n_days >= MIN_OVERLAP_DAYS else "below"


def station_regimes(hourly_sal: pd.DataFrame) -> pd.DataFrame:
    """Median hourly salinity per station in spring (Apr-Jun) and late summer (Aug-Sep)."""
    month = hourly_sal.index.month
    spring = hourly_sal[month.isin(SPRING_MONTHS)]
    late = hourly_sal[month.isin(LATE_SUMMER_MONTHS)]
    return pd.DataFrame({"sal_spring_median": spring.median(), "sal_spring_hours": spring.count(),
                         "sal_late_median": late.median(), "sal_late_hours": late.count()})


def regime_label(dsal) -> np.ndarray:
    dsal = np.asarray(dsal, dtype=float)
    return np.where(np.isnan(dsal), "unknown", np.where(dsal < REGIME_DSAL_PSU, "same", "different"))


def rain_class(total: pd.Series, heavy: float, none: float = RAIN_NONE_MM) -> np.ndarray:
    return np.select([total.isna(), total < none, total >= heavy], ["na", "none", "heavy"], "light")


def reliability_radius(cells: pd.DataFrame, keys, gate_col: str) -> pd.DataFrame:
    """See module doc: skip insufficient bins, stop at the first failing bin."""
    out = []
    for cell, grp in cells.groupby(keys, sort=True):
        status = grp.set_index("distance_bin")[gate_col].to_dict()
        radius, stop, skipped, seen = np.nan, "none_sufficient", 0, False
        for label in RADIUS_BINS:
            st = status.get(label, "insufficient")
            if st == "insufficient":
                skipped += 1
                continue
            if st == "pass":
                radius, seen = BIN_UPPER_KM[label], True
                stop = "all_sufficient_pass"
                continue
            if not seen:
                radius = 0.0
            stop = f"fail@{label}"
            break
        rec = dict(zip(keys, cell if isinstance(cell, tuple) else (cell,)))
        rec.update({"gate": gate_col, "radius_km": radius, "stop": stop, "n_skipped": skipped})
        out.append(rec)
    return pd.DataFrame(out)


def ols_standardised(y, X: pd.DataFrame) -> dict:
    """OLS of y on z-scored columns of X; classical SEs."""
    y = np.asarray(y, float)
    Z = (X - X.mean()) / X.std(ddof=0)
    A = np.column_stack([np.ones(len(Z)), Z.to_numpy(float)])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - A @ beta
    dof = max(len(y) - A.shape[1], 1)
    sigma2 = resid @ resid / dof
    cov = sigma2 * np.linalg.pinv(A.T @ A)
    se = np.sqrt(np.diag(cov))
    r2 = 1 - resid @ resid / ((y - y.mean()) @ (y - y.mean())) if np.var(y) > 0 else np.nan
    out = {"n": len(y), "r2": float(r2)}
    for i, col in enumerate(X.columns, start=1):
        out[f"coef_{col}"], out[f"se_{col}"] = float(beta[i]), float(se[i])
    return out


def logit_standardised(y, X: pd.DataFrame, iters: int = 100) -> dict:
    """Unpenalised logistic regression (Newton-Raphson) on z-scored X; SEs from the Hessian."""
    y = np.asarray(y, float)
    Z = (X - X.mean()) / X.std(ddof=0)
    A = np.column_stack([np.ones(len(Z)), Z.to_numpy(float)])
    out = {"n": len(y), "n_pos": int(y.sum())}
    if y.min() == y.max():
        return {**out, "status": "no_variation"}
    beta = np.zeros(A.shape[1])
    status = "ok"
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(A @ beta, -30, 30)))
        H = A.T @ (A * (p * (1 - p))[:, None])
        step = np.linalg.pinv(H) @ (A.T @ (y - p))
        beta += step
        if np.abs(step).max() < 1e-8:
            break
        if np.abs(beta).max() > 25:
            status = "separation"
            break
    p = 1 / (1 + np.exp(-np.clip(A @ beta, -30, 30)))
    se = np.sqrt(np.diag(np.linalg.pinv(A.T @ (A * (p * (1 - p))[:, None]))))
    out["status"] = status
    for i, col in enumerate(X.columns, start=1):
        out[f"coef_{col}"], out[f"se_{col}"] = float(beta[i]), float(se[i])
    return out


# ---------------------------------------------------------------- rain (write-once cache)
def era5_cell(lat: float, lon: float) -> tuple[float, float]:
    return round(round(lat * 4) / 4, 2), round(round(lon * 4) / 4, 2)


def load_or_fetch_rain_hourly(lat: float, lon: float, start: str = RAIN_START, end: str = RAIN_END,
                              derived_dir: Path = DERIVED_DIR, allow_fetch: bool = True):
    """ERA5 hourly precipitation (mm) indexed in EST (UTC-5); cached write-once."""
    path = derived_dir / f"open_meteo_era5_precip_hourly_{lat:.2f}_{lon:.2f}_{start}_{end}.csv"
    url = ("https://archive-api.open-meteo.com/v1/archive?"
           f"latitude={lat:.2f}&longitude={lon:.2f}&start_date={start}&end_date={end}"
           "&hourly=precipitation&models=era5&timezone=GMT")
    meta = {"file": str(path.relative_to(paths.PROJECT_ROOT)).replace("\\", "/")
            if path.is_relative_to(paths.PROJECT_ROOT) else str(path), "url": url}
    if not path.exists():
        if not allow_fetch:
            return None, {**meta, "status": "absent_no_fetch"}
        payload = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": ml.USER_AGENT})
                with urllib.request.urlopen(req, timeout=120) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                break
            except Exception as exc:  # noqa: BLE001 - network failure must not block the run
                if attempt == 3:
                    return None, {**meta, "status": f"fetch_failed: {exc!r}"}
                time.sleep(10 * 2 ** attempt)
        frame = pd.DataFrame({"time_utc": payload["hourly"]["time"], "precip_mm": payload["hourly"]["precipitation"]})
        derived_dir.mkdir(parents=True, exist_ok=True)
        with open(path, "x", encoding="utf-8", newline="") as handle:
            frame.to_csv(handle, index=False)
        meta_path = path.with_suffix(".json")
        if not meta_path.exists():
            meta_path.write_text(json.dumps({"url": url, "fetched_utc": datetime.now(timezone.utc).isoformat(
                timespec="seconds"), "grid_lat": payload.get("latitude"), "grid_lon": payload.get("longitude")},
                indent=2), encoding="utf-8")
        time.sleep(1.0)
    frame = pd.read_csv(path)
    index = pd.to_datetime(frame["time_utc"]) + pd.Timedelta(hours=ml.UTC_OFFSET_H)
    rain = pd.Series(frame["precip_mm"].astype(float).to_numpy(), index=pd.DatetimeIndex(index, name="time_est"))
    return rain, {**meta, "status": "ok", "sha256": sha256(path), "n_hours": int(rain.notna().sum())}


# ---------------------------------------------------------------- per-pair evaluation
STRATA = {  # column suffix -> (stratum column, level)
    "night": ("daynight", "night"), "day": ("daynight", "day"),
    "r24heavy": ("rain24", "heavy"), "r24none": ("rain24", "none"),
    "r72heavy": ("rain72", "heavy"), "r72none": ("rain72", "none"),
}


def pair_day_table(x: pd.Series, y: pd.Series, var: str, strata: pd.DataFrame | None) -> dict[str, pd.DataFrame]:
    """Per transfer: per-date counts (n, w, sae) overall and per stratum."""
    out = {}
    for transfer in TRANSFERS:
        est = x if transfer == "raw" else rolling_linear_transfer(x, y)
        frame = pd.DataFrame({"est": est, "obs": y}).dropna()
        if frame.empty:
            continue
        within = within_tolerance(var, frame["est"].to_numpy(), frame["obs"].to_numpy())
        cols = {"n": np.ones(len(frame), int), "w": within.astype(int),
                "sae": np.abs(frame["obs"].to_numpy() - frame["est"].to_numpy())}
        if strata is not None:
            s = strata.reindex(frame.index)
            for suffix, (col, level) in STRATA.items():
                hit = (s[col] == level).to_numpy()
                cols[f"n_{suffix}"] = hit.astype(int)
                cols[f"w_{suffix}"] = (hit & within).astype(int)
        grid = pd.DataFrame(cols, index=frame.index)
        out[transfer] = grid.groupby(frame.index.normalize()).sum()
    return out


def summarise(day_rows: pd.DataFrame, n_col: str = "n", w_col: str = "w") -> dict:
    per_date = day_rows.groupby("date")[[w_col, n_col]].sum()
    per_date = per_date[per_date[n_col] > 0]
    if per_date.empty:
        return {"n_days": 0, "n_hours": 0, "share": np.nan, "ci_low": np.nan, "ci_high": np.nan}
    share, lo, hi = bootstrap_share(per_date[w_col], per_date[n_col], n_boot=N_BOOT, seed=SEED)
    return {"n_days": int(len(per_date)), "n_hours": int(per_date[n_col].sum()),
            "share": round(share, 4), "ci_low": round(lo, 4), "ci_high": round(hi, 4)}


def cell_table(days: pd.DataFrame, keys) -> pd.DataFrame:
    rows = []
    for cell, grp in days.groupby(keys, sort=True, observed=True):
        rec = dict(zip(keys, cell if isinstance(cell, tuple) else (cell,)))
        rec.update({"dataset": DATASET, "n_pairs": int(grp["pair_id"].nunique()), **summarise(grp)})
        rec["mae"] = round(float(grp["sae"].sum() / grp["n"].sum()), 4)
        for g in GATES:
            rec[f"gate{int(g * 100)}"] = gate_status(rec["ci_low"], rec["n_days"], g, min_days=MIN_DAYS)
        rows.append(rec)
    return pd.DataFrame(rows)


def effect_rows(days: pd.DataFrame, keys, a: str, b: str, label: str) -> list[dict]:
    rows = []
    for cell, grp in days.groupby(keys, sort=True, observed=True):
        agg = grp.groupby("date")[[f"w_{a}", f"n_{a}", f"w_{b}", f"n_{b}"]].sum()
        da, db = int((agg[f"n_{a}"] > 0).sum()), int((agg[f"n_{b}"] > 0).sum())
        rec = dict(zip(keys, cell if isinstance(cell, tuple) else (cell,)))
        rec.update({"dataset": DATASET, "effect": label, "days_a": da, "days_b": db,
                    "hours_a": int(agg[f"n_{a}"].sum()), "hours_b": int(agg[f"n_{b}"].sum())})
        if da < 10 or db < 10:
            rows.append({**rec, "status": "insufficient"})
            continue
        diff, lo, hi = bootstrap_share_difference(agg[f"w_{a}"], agg[f"n_{a}"], agg[f"w_{b}"], agg[f"n_{b}"],
                                                  n_boot=N_BOOT, seed=SEED)
        rows.append({**rec, "status": "ok",
                     "share_a": round(agg[f"w_{a}"].sum() / agg[f"n_{a}"].sum(), 4),
                     "share_b": round(agg[f"w_{b}"].sum() / agg[f"n_{b}"].sum(), 4),
                     "diff_a_minus_b": round(diff, 4), "diff_ci_lo": round(lo, 4), "diff_ci_hi": round(hi, 4)})
    return rows


def regime_beats_distance(coef_dsal: float, coef_km: float) -> bool:
    """Regime dominates only if a larger salinity difference *lowers* reliability more than distance does."""
    return bool(coef_dsal < 0 and abs(coef_dsal) > abs(coef_km))


def regime_vs_distance(pair_rel: pd.DataFrame, max_km_scopes=(30.0, MAX_KM)) -> pd.DataFrame:
    rows = []
    for (var, transfer), grp in pair_rel.groupby(["variable", "transfer"]):
        und = grp.assign(key=[tuple(sorted(k)) for k in zip(grp["anchor"], grp["target"])])
        und = und.groupby("key").agg(km=("km", "first"), dsal=("dsal", "first"), share=("share", "mean"),
                                     depth_mismatch=("depth_mismatch", "first")).dropna(subset=["dsal", "share"])
        for scope in max_km_scopes:
            sub = und[und["km"] <= scope]
            base = {"dataset": DATASET, "variable": var, "transfer": transfer, "scope_max_km": scope}
            if len(sub) < 8 or sub["dsal"].std() == 0:
                rows.append({**base, "model": "ols_share", "n": len(sub), "status": "too_few_pairs"})
                continue
            for model, fn, y in (("ols_share", ols_standardised, sub["share"]),
                                 ("logit_share_ge_0.80", logit_standardised, (sub["share"] >= 0.80).astype(int))):
                for covs in (["km", "dsal"], ["km", "dsal", "depth_mismatch"]):
                    X = sub[covs].astype(float)
                    if (X.std(ddof=0) == 0).any():
                        continue
                    res = fn(y, X)
                    rec = {**base, "model": model, "covariates": "+".join(covs), "status": res.pop("status", "ok"), **res}
                    if "coef_km" in rec:
                        rec["abs_dsal_over_abs_km"] = round(abs(rec["coef_dsal"]) / abs(rec["coef_km"]), 3) \
                            if rec["coef_km"] else np.inf
                        rec["regime_beats_distance"] = regime_beats_distance(rec["coef_dsal"], rec["coef_km"])
                    rows.append(rec)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- main
def git_state() -> dict:
    def run(*cmd):
        try:
            return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=30).stdout.strip()
        except Exception:  # noqa: BLE001
            return ""
    return {"commit": run("git", "rev-parse", "HEAD"),
            "dirty_paths": [line[3:] for line in run("git", "status", "--porcelain").splitlines()]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME)
    parser.add_argument("--data-dir", type=Path, default=ml.MDDNR_DIR)
    parser.add_argument("--no-rain-fetch", action="store_true")
    args = parser.parse_args(argv)
    out = prepare_output_dir(args.output_dir)

    table = ml.read_station_table(args.data_dir / ml.STATION_TABLE_NAME)
    hourly, qc, files = ml.load_hourly(args.data_dir)
    wide = {v: hourly[hourly["variable"] == v].pivot(index="time_est", columns="station", values="value")
            for v in VARIABLES}
    stations = table[table["station"].isin(hourly["station"].unique())].set_index("station")
    regimes = station_regimes(wide["Sal"])
    stations = stations.join(regimes)
    for v in VARIABLES:
        stations[f"hours_{v}"] = wide[v].count().reindex(stations.index).fillna(0).astype(int)

    # rain + day/night strata per target station
    rain_meta, strata_by_station = [], {}
    hours = pd.date_range(f"{RAIN_START} 00:00", f"{RAIN_END} 23:00", freq="h")
    cells = {}
    for code, st in stations.iterrows():
        cell = era5_cell(st["lat"], st["lon"])
        if cell not in cells:
            rain, meta = load_or_fetch_rain_hourly(*cell, derived_dir=args.data_dir / "derived",
                                                   allow_fetch=not args.no_rain_fetch)
            cells[cell] = rain
            rain_meta.append({"cell": cell, **meta})
        rain = cells[cell]
        s = pd.DataFrame(index=hours)
        elev = solar_elevation_deg(hours + pd.Timedelta(minutes=30), st["lat"], st["lon"], utc_offset_h=ml.UTC_OFFSET_H)
        s["daynight"] = np.where(elev > 0, "day", "night")
        if rain is not None:
            r = rain.reindex(hours)
            s["rain24"] = rain_class(prior_window_sum(r, 24).reindex(hours), RAIN24_HEAVY_MM)
            s["rain72"] = rain_class(prior_window_sum(r, 72).reindex(hours), RAIN72_HEAVY_MM)
        else:
            s["rain24"] = s["rain72"] = "na"
        strata_by_station[code] = s
    stations["era5_cell"] = [str(era5_cell(a, b)) for a, b in zip(stations["lat"], stations["lon"])]

    # pairs
    codes = list(stations.index)
    pair_rows, day_frames, pair_id = [], [], 0
    for a in codes:
        for t in codes:
            if a == t:
                continue
            km = float(ml.haversine_km(stations.at[a, "lat"], stations.at[a, "lon"], stations.at[t, "lat"], stations.at[t, "lon"]))
            if km > MAX_KM:
                continue
            dsal = abs(stations.at[a, "sal_spring_median"] - stations.at[t, "sal_spring_median"])
            rec = {"anchor": a, "target": t, "km": round(km, 3), "distance_bin": distance_bin([km])[0],
                   "dsal": round(float(dsal), 3) if np.isfinite(dsal) else np.nan,
                   "regime": regime_label([dsal])[0],
                   "dsal_late": round(float(abs(stations.at[a, "sal_late_median"] - stations.at[t, "sal_late_median"])), 3),
                   "tributary_anchor": stations.at[a, "tributary"], "tributary_target": stations.at[t, "tributary"],
                   "sensor_anchor": stations.at[a, "sensor_type"], "sensor_target": stations.at[t, "sensor_type"],
                   "depth_mismatch": int(stations.at[a, "sensor_type"] != stations.at[t, "sensor_type"]),
                   "both_fresh": bool(max(stations.at[a, "sal_spring_median"], stations.at[t, "sal_spring_median"]) < 1.0)}
            any_var = False
            for v in VARIABLES:
                tbl = wide[v]
                if a not in tbl or t not in tbl:
                    rec[f"n_days_{v}"] = 0
                    continue
                n_days = overlap_days(tbl[a], tbl[t])
                rec[f"n_days_{v}"] = n_days
                if n_days < MIN_OVERLAP_DAYS:
                    continue
                any_var = True
                joint = tbl[[a, t]].dropna()
                for transfer, days in pair_day_table(joint[a], joint[t], v, strata_by_station[t]).items():
                    day_frames.append(days.reset_index(names="date").assign(
                        pair_id=pair_id, anchor=a, target=t, variable=v, transfer=transfer, km=rec["km"],
                        distance_bin=rec["distance_bin"], regime=rec["regime"], dsal=rec["dsal"],
                        depth_mismatch=rec["depth_mismatch"], both_fresh=rec["both_fresh"]))
            rec["overlap_tier"] = overlap_tier(max(rec.get(f"n_days_{v}", 0) for v in VARIABLES))
            if any_var:
                rec["pair_id"] = pair_id
                pair_rows.append(rec)
                pair_id += 1
    pairs = pd.DataFrame(pair_rows)
    days = pd.concat(day_frames, ignore_index=True)
    # Sal@nonfresh: drop pairs where both spring medians < 1 psu (1-psu tolerance passes trivially there)
    nonfresh = days[(days["variable"] == "Sal") & ~days["both_fresh"]].assign(variable="Sal@nonfresh")
    days = pd.concat([days, nonfresh], ignore_index=True)
    days["season"] = season_of(days["date"])
    days["distance_bin"] = pd.Categorical(days["distance_bin"], BIN_LABELS, ordered=True)

    # (1) cells: var x regime x distance bin x transfer
    cells_df = cell_table(days, ["variable", "regime", "distance_bin", "transfer"])
    cells_df = cells_df.rename(columns={"variable": "var", "share": "share"})
    cols = ["dataset", "var", "regime", "distance_bin", "transfer", "n_days", "share", "ci_low",
            "gate80", "gate90", "gate95", "n_pairs", "n_hours", "ci_high", "mae"]
    cells_df = cells_df[cols]
    # (2) radius
    radius = pd.concat([reliability_radius(cells_df[cells_df["regime"].isin(["same", "different"])],
                                           ["dataset", "var", "regime", "transfer"], g) for g in ("gate80", "gate90", "gate95")])
    radius["gate"] = radius["gate"].str.replace("gate", "").astype(int)
    # all-regime pooled radius as reference
    pooled = cell_table(days.assign(regime="any"), ["variable", "regime", "distance_bin", "transfer"]).rename(
        columns={"variable": "var"})
    radius_any = pd.concat([reliability_radius(pooled, ["dataset", "var", "regime", "transfer"], g)
                            for g in ("gate80", "gate90", "gate95")])
    radius_any["gate"] = radius_any["gate"].str.replace("gate", "").astype(int)
    radius = pd.concat([radius, radius_any], ignore_index=True)[
        ["dataset", "var", "regime", "transfer", "gate", "radius_km", "stop", "n_skipped"]]

    # (3) regime vs distance on pair-level reliability
    pair_rel = cell_table(days, ["pair_id", "variable", "transfer"]).merge(
        pairs[["pair_id", "anchor", "target", "km", "dsal", "regime", "depth_mismatch"]], on="pair_id")
    pair_rel = pair_rel[pair_rel["n_days"] >= MIN_DAYS]
    rvd = regime_vs_distance(pair_rel)

    # (4) rain effect + other strata
    in30 = days[days["km"] <= 30]
    rain_rows = []
    for a, b, label in (("r24heavy", "r24none", "rain24h_ge10_vs_lt1"), ("r72heavy", "r72none", "rain72h_ge20_vs_lt1")):
        rain_rows += effect_rows(in30, ["variable", "transfer", "regime"], a, b, label)
        rain_rows += effect_rows(in30.assign(regime="any"), ["variable", "transfer", "regime"], a, b, label)
    rain_effect = pd.DataFrame(rain_rows).rename(columns={"variable": "var"})
    other = effect_rows(in30.assign(regime="any"), ["variable", "transfer", "regime"], "night", "day", "night_vs_day")
    season_cells = cell_table(in30, ["variable", "regime", "season", "transfer"]).rename(columns={"variable": "var"})

    pairs_out = pairs.rename(columns={})
    pairs_out.to_csv(out / "pairs.csv", index=False)
    cells_df.to_csv(out / "cells.csv", index=False)
    radius.to_csv(out / "radius.csv", index=False)
    rvd.to_csv(out / "regime_vs_distance.csv", index=False)
    rain_effect.to_csv(out / "rain_effect.csv", index=False)
    pd.DataFrame(other).to_csv(out / "daynight_effect.csv", index=False)
    season_cells.to_csv(out / "season_cells.csv", index=False)
    pair_rel.to_csv(out / "pair_reliability.csv", index=False)
    stations.reset_index().to_csv(out / "stations.csv", index=False)
    qc_sum = qc.groupby(["station", "variable"])[["n_rows", "n_blank_source", "n_range", "n_spike", "n_flatline", "n_good"]].sum()
    qc.to_csv(out / "qc_tally.csv", index=False)

    inputs = [args.data_dir / ml.STATION_TABLE_NAME, *files]
    manifest = {
        "run": RUN_NAME, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "experiments/mddnr_reliability.py", "loader": "experiments/mddnr_load.py", "code": git_state(),
        "source": "Maryland DNR Eyes on the Bay continuous monitoring, contmon/JustDownload.cfm (15-min, post-QA years)",
        "parameters": {
            "years": list(ml.YEARS), "selection": "station-years with >= 5 ConMon sites (incl. itself) active within 30 km",
            "dropped_bottom_duplicates": list(ml.BOTTOM_DUPLICATES), "time_basis": "EST (UTC-5), no DST",
            "qc": {"source": "blank = failed DNR QA", "ranges": ml.RANGES, "spike_limits": ml.SPIKE,
                   "spike_rule": "|x - centred 5-pt rolling median| > limit", "flatline_run": ml.FLATLINE_RUN,
                   "flatline_exempt": ml.FLATLINE_EXEMPT, "hourly_min_obs": 2},
            "tolerances": {"Temp": 0.5, "Sal": 1.0, "DO_mgl": 0.5, "pH": 0.2, "Turb": "max(2 NTU, 20 % of target)"},
            "min_overlap_days": MIN_OVERLAP_DAYS, "overlap_relaxation": "seasonal deployments: >= 90 overlapping days per pair x var instead of >= 1 year",
            "max_km": MAX_KM, "distance_bins": BIN_LABELS,
            "regime": {"high_flow_months": SPRING_MONTHS, "low_flow_months": LATE_SUMMER_MONTHS,
                       "same_if_abs_dsal_spring_lt": REGIME_DSAL_PSU},
            "calibrated": "OLS a+b*anchor on strictly-past 30 days of joint hours, >= 240 h",
            "gates": GATES, "gate_rule": "date-block bootstrap lower 95% bound >= gate and n_days >= 30",
            "n_boot": N_BOOT, "seed": SEED,
            "rain": {"source": "Open-Meteo ERA5 archive hourly precipitation, ERA5 0.25 deg cell of target",
                     "rain24_heavy_mm": RAIN24_HEAVY_MM, "rain72_heavy_mm": RAIN72_HEAVY_MM, "none_lt_mm": RAIN_NONE_MM},
            "regression": "unordered pair share (mean of both directions), z-scored km and dsal; OLS on share, logistic on share>=0.80",
        },
        "counts": {"stations": int(len(stations)), "pairs_ordered": int(len(pairs)),
                   "pairs_le30km": int((pairs["km"] <= 30).sum()), "raw_files": len(files),
                   "raw_bytes": int(sum(p.stat().st_size for p in files))},
        "qc_totals": qc_sum.sum().astype(int).to_dict(),
        "rain_inputs": rain_meta,
        "inputs": [{"file": str(p.relative_to(paths.PROJECT_ROOT)).replace("\\", "/") if p.is_relative_to(paths.PROJECT_ROOT) else str(p),
                    "bytes": p.stat().st_size, "sha256": sha256(p)} for p in inputs],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
