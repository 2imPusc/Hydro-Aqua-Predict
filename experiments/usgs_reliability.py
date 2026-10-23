"""Direction-4 reliability on USGS continuous water-quality sites in San Francisco Bay (H4.5).

Question (as RL-12 NERRS Jobos, RL-14 HK EPD): can one in-situ sensor (anchor)
stand in for another location (target)? Reliability = share of hours with
|estimate - target observation| <= tolerance.

Protocol (shared with the other direction-4 datasets)
* Hourly means of USGS-approved (code "A") values, >= 2 raw obs per hour
  (``experiments/usgs_load.py``). Salinity from specific conductance (PSS-78 at 25 C).
* Tolerances (``nerrs_reliability.TOLERANCES``): Temp 0.5 C, Sal 1 psu, DO 0.5 mg/L,
  pH 0.2, Turbidity max(2 FNU, 20 %).
* Pairs: every ordered station pair with >= 365 days of overlapping hourly data
  for that variable; distances reported for all, bins 0-2, 2-5, 5-10, 10-20, 20-30, >30 km.
* Salinity regime per station: median hourly salinity in the wet (Nov-Apr) and dry
  (May-Oct) season over WY2018-WY2025; pair "same" regime if |delta wet median| < 2 psu.
  ``dsal`` = continuous |delta wet median|. Because station records cover different
  years (wet 2017/2019/2023 vs drought 2021-22), ``dsal_overlap`` (computed on the
  pair's common hours only) is also reported as a robustness column.
* Transfers: ``raw`` (estimate = anchor) and ``calibrated_30d`` (a + b*anchor, OLS on
  the pair's hours in [t - 30 d, t), >= 240 h; ``nerrs_reliability.rolling_linear_transfer``).
* Gates 80/90/95 %: day-block bootstrap (500 resamples, seed 20261016) lower 95 % bound
  >= gate and >= 30 days. Cells pool all pairs of a cell; the resampling unit is the
  calendar day (LST), all pairs of that day together.
* Strata: season; day/night (solar elevation, LST = UTC-8); rain from ERA5 hourly
  precipitation (Open-Meteo archive) at the bay centroid 37.85 N, -122.25 E: prior 24 h
  ``>= 10 mm`` heavy vs ``< 1 mm`` none, prior 72 h ``>= 20 mm`` heavy vs ``< 1 mm`` none.
  Rain is observation-only, used as a stratifier. Tide phase not done.
* Radius: walking distance bins outward, empty bins (no pair) are skipped; radius =
  upper edge of the last bin of the contiguous passing run that starts at the first
  populated bin; 0 if the first populated bin does not pass. ``stop`` =
  ``no_pairs_beyond@<bin>`` marks a radius censored by missing farther pairs.
* Sensor depth: near-surface preferred; B19/CM16 (and SMB/DMB DO) only have near-bottom
  sensors, so ``mixed_depth`` flags pairs whose series come from different depths.

Local reimplementations (signatures in the RL-12/RL-14 modules do not fit):
``season_of`` (SF wet = Nov-Apr), ``distance_bin``/``reliability_radius`` (6 bins incl.
20-30 and >30), ``salinity_regime`` (HK version calls the HK season), rain fetch
(hourly, UTC; HK fetch is daily in HK time).

Run:  .venv\\Scripts\\python experiments\\usgs_reliability.py
Outputs: artifacts/experiments/usgs-sfbay-h4-reliability-20261017/ (refuses to overwrite).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import paths  # noqa: E402
from experiments import usgs_load as ul  # noqa: E402
from experiments.hk_epd_reliability import haversine_km  # noqa: E402
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

RUN_NAME = "usgs-sfbay-h4-reliability-20261017"
DATASET = "usgs_sfbay"
GATES = (0.80, 0.90, 0.95)
MIN_DAYS = 30
N_BOOT = 500
SEED = 20261016
MIN_OVERLAP_DAYS = 365
LST_OFFSET_H = -8
REGIME_DSAL_PSU = 2.0
CAL_WINDOW = "30D"
CAL_MIN_HOURS = 240
RAIN24_HEAVY_MM, RAIN72_HEAVY_MM, RAIN_NONE_MM = 10.0, 20.0, 1.0
CENTROID = (37.85, -122.25)
RAIN_START, RAIN_END = "2017-09-01", "2025-09-30"
BIN_EDGES = [0, 2, 5, 10, 20, 30, np.inf]
BIN_LABELS = ["0-2", "2-5", "5-10", "10-20", "20-30", ">30"]
BIN_UPPER_KM = dict(zip(BIN_LABELS, [2.0, 5.0, 10.0, 20.0, 30.0, np.inf]))
# protocol variable -> key in nerrs_reliability.TOLERANCES
VARS = {"Temp": "Temp", "Sal": "Sal", "DO": "DO_mgl", "pH": "pH", "Turb": "Turb"}
TRANSFERS = ("raw", "calibrated_30d")
# USGS parameter code of the series behind each variable (Sal is derived from SpC 00095)
VAR_PCODE = {"00010": "Temp", "00095": "Sal", "00300": "DO", "00400": "pH", "63680": "Turb"}


# ---------------------------------------------------------------- primitives
def season_of(index_lst) -> np.ndarray:
    """SF Bay Mediterranean climate: wet Nov-Apr, dry May-Oct."""
    return np.where(pd.DatetimeIndex(index_lst).month.isin([11, 12, 1, 2, 3, 4]), "wet", "dry")


def distance_bin(km) -> np.ndarray:
    return pd.cut(np.asarray(km, dtype=float), BIN_EDGES, labels=BIN_LABELS, right=False).astype(str)


def to_lst(index_utc) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(index_utc) + pd.Timedelta(hours=LST_OFFSET_H)


def regime_medians(sal_wide: pd.DataFrame) -> pd.DataFrame:
    """Per station median hourly salinity in wet and dry season (+ hours used)."""
    season = season_of(to_lst(sal_wide.index))
    rows = {}
    for site in sal_wide:
        s = sal_wide[site]
        rows[site] = {"sal_wet_median": s[season == "wet"].median(), "sal_dry_median": s[season == "dry"].median(),
                      "sal_wet_hours": int(s[season == "wet"].notna().sum()),
                      "sal_dry_hours": int(s[season == "dry"].notna().sum())}
    return pd.DataFrame.from_dict(rows, orient="index")


def regime_label(dsal) -> np.ndarray:
    d = np.asarray(dsal, dtype=float)
    return np.where(np.isnan(d), "unknown", np.where(d < REGIME_DSAL_PSU, "same", "different"))


def overlap_days(a: pd.Series, b: pd.Series) -> int:
    joint = pd.concat([a, b], axis=1).dropna()
    return int(to_lst(joint.index).normalize().nunique())


def pair_table(stations: pd.DataFrame, wide: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """All ordered pairs with distance, regime, and overlapping days per variable."""
    med = regime_medians(wide["Sal"]) if "Sal" in wide else pd.DataFrame()
    s = stations.set_index("site")
    rows = []
    for a in s.index:
        for t in s.index:
            if a == t:
                continue
            km = float(haversine_km(s.at[a, "lat"], s.at[a, "lon"], s.at[t, "lat"], s.at[t, "lon"]))
            dsal = abs(med.at[a, "sal_wet_median"] - med.at[t, "sal_wet_median"]) \
                if a in med.index and t in med.index else np.nan
            rec = {"anchor": a, "target": t, "anchor_code": s.at[a, "code"], "target_code": s.at[t, "code"],
                   "km": round(km, 3), "distance_bin": distance_bin([km])[0], "dsal": round(float(dsal), 3),
                   "regime": regime_label([dsal])[0]}
            if "Sal" in wide and a in wide["Sal"] and t in wide["Sal"]:
                joint = wide["Sal"][[a, t]].dropna()
                wet = joint[season_of(to_lst(joint.index)) == "wet"]
                rec["dsal_overlap"] = round(float(abs(wet[a].median() - wet[t].median())), 3) if len(wet) else np.nan
            for var, table in wide.items():
                rec[f"n_days_{var}"] = overlap_days(table[a], table[t]) if a in table and t in table else 0
            rows.append(rec)
    out = pd.DataFrame(rows)
    out["regime_overlap"] = regime_label(out.get("dsal_overlap", np.nan))
    return out


def transfer_frame(anchor: pd.Series, target: pd.Series, var: str) -> pd.DataFrame:
    """Hourly rows (transfer, est, obs, within) for both transfers on the pair's common hours."""
    joint = pd.concat([anchor.rename("x"), target.rename("y")], axis=1).dropna().sort_index()
    frames = []
    for name in TRANSFERS:
        est = joint["x"] if name == "raw" else rolling_linear_transfer(joint["x"], joint["y"], CAL_WINDOW, CAL_MIN_HOURS)
        f = pd.DataFrame({"est": est, "obs": joint["y"]}).dropna()
        f["within"] = within_tolerance(VARS[var], f["est"].to_numpy(), f["obs"].to_numpy())
        f["transfer"] = name
        frames.append(f)
    return pd.concat(frames)


def build_strata(hours_utc: pd.DatetimeIndex, rain: pd.Series | None) -> pd.DataFrame:
    lst = to_lst(hours_utc)
    strata = pd.DataFrame(index=hours_utc)
    strata["date"] = lst.normalize()
    strata["season"] = season_of(lst)
    elev = solar_elevation_deg(lst + pd.Timedelta(minutes=30), CENTROID[0], CENTROID[1], utc_offset_h=LST_OFFSET_H)
    strata["daynight"] = np.where(elev > 0, "day", "night")
    for label, hours, heavy in (("rain24h", 24, RAIN24_HEAVY_MM), ("rain72h", 72, RAIN72_HEAVY_MM)):
        if rain is None:
            strata[label] = "na"
            continue
        total = prior_window_sum(rain, hours).reindex(hours_utc)
        strata[label] = np.select([total.isna(), total < RAIN_NONE_MM, total >= heavy], ["na", "none", "heavy"], "mid")
    return strata


def daily_counts(frame: pd.DataFrame, strata: pd.DataFrame) -> pd.DataFrame:
    keys = ["transfer", "date", "season", "daynight", "rain24h", "rain72h"]
    f = frame.join(strata, how="left")
    f["err_abs"] = (f["obs"] - f["est"]).abs()
    return f.groupby(keys, observed=True).agg(w=("within", "sum"), n=("within", "size"),
                                              abs_err=("err_abs", "sum")).reset_index()


def summarise(counts: pd.DataFrame, keys: list[str], n_boot: int = N_BOOT, seed: int = SEED) -> pd.DataFrame:
    """Pooled share per cell with a day-block (calendar day, all pairs together) bootstrap CI."""
    out = []
    for cell, grp in counts.groupby(keys, observed=True, sort=True):
        per_day = grp.groupby("date")[["w", "n", "abs_err"]].sum()
        share, lo, hi = bootstrap_share(per_day["w"], per_day["n"], n_boot=n_boot, seed=seed)
        rec = dict(zip(keys, cell if isinstance(cell, tuple) else (cell,)))
        rec.update({"n_pairs": int(grp["pair"].nunique()) if "pair" in grp else np.nan,
                    "n_hours": int(per_day["n"].sum()), "n_days": int(len(per_day)),
                    "mae": round(float(per_day["abs_err"].sum() / per_day["n"].sum()), 4),
                    "share": round(share, 4), "ci_low": round(lo, 4), "ci_high": round(hi, 4)})
        for g in GATES:
            rec[f"gate{int(g * 100)}"] = gate_status(lo, len(per_day), g, min_days=MIN_DAYS)
        out.append(rec)
    return pd.DataFrame(out)


def reliability_radius(cells: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Radius per (keys, gate); empty bins skipped, run must start at the first populated bin."""
    out = []
    for cell, grp in cells.groupby(keys, sort=True):
        status = grp.set_index("distance_bin")
        for g in GATES:
            col = f"gate{int(g * 100)}"
            radius, first_bin, stop, last_seen = 0.0, None, None, None
            for label in BIN_LABELS:
                if label not in status.index:
                    continue
                first_bin, last_seen = first_bin or label, label
                st = status.at[label, col]
                if st == "pass":
                    radius = BIN_UPPER_KM[label]
                    continue
                stop = f"{st}@{label}"
                break
            if stop is None:  # every populated bin passed: radius is censored at the last tested bin
                stop = "all_pass" if last_seen == BIN_LABELS[-1] else f"no_pairs_beyond@{last_seen}"
            rec = dict(zip(keys, cell if isinstance(cell, tuple) else (cell,)))
            rec.update({"gate": col, "radius_km": radius, "first_populated_bin": first_bin, "stop": stop})
            out.append(rec)
    return pd.DataFrame(out)


def standardised_ols(y, *xs) -> tuple[np.ndarray, float]:
    """OLS of y on z-scored predictors; returns (coefficients excluding intercept, R^2)."""
    y = np.asarray(y, float)
    X = np.column_stack([(np.asarray(x, float) - np.mean(x)) / np.std(x) for x in xs])
    X1 = np.column_stack([np.ones(len(y)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    resid = y - X1 @ beta
    r2 = 1 - (resid @ resid) / ((y - y.mean()) @ (y - y.mean()))
    return beta[1:], float(r2)


def regime_vs_distance(pair_rel: pd.DataFrame) -> pd.DataFrame:
    """Per var x transfer x scope (pairs <= 30 km = primary protocol scope; all pairs = secondary)."""
    rows = []
    for (var, transfer, scope), g in pd.concat([pair_rel.assign(scope="le30km")[pair_rel["km"] <= 30],
                                                pair_rel.assign(scope="all_pairs")]).groupby(
            ["var", "transfer", "scope"], sort=False):
        g = g.dropna(subset=["dsal"])
        rec = {"dataset": DATASET, "var": var, "transfer": transfer, "scope": scope, "n_ordered_pairs": len(g),
               "n_unordered_pairs": int(g.apply(lambda r: tuple(sorted((r.anchor, r.target))), axis=1).nunique())
               if len(g) else 0}
        if len(g) >= 4 and g["km"].std() > 0 and g["dsal"].std() > 0:
            rec["spearman_share_km"] = round(float(g["share"].rank().corr(g["km"].rank())), 3)
            rec["spearman_share_dsal"] = round(float(g["share"].rank().corr(g["dsal"].rank())), 3)
            rec["corr_km_dsal"] = round(float(g["km"].corr(g["dsal"])), 3)
            (b_km, b_ds), r2 = standardised_ols(g["share"], g["km"], g["dsal"])
            rec.update({"beta_km_std": round(float(b_km), 4), "beta_dsal_std": round(float(b_ds), 4),
                        "r2": round(r2, 3)})
            for name, x in (("km", g["km"]), ("dsal", g["dsal"])):
                (b,), r2_1 = standardised_ols(g["share"], x)
                rec[f"r2_{name}_only"] = round(r2_1, 3)
        rec["mean_share_same"] = round(float(g.loc[g.regime == "same", "share"].mean()), 4)
        rec["mean_share_different"] = round(float(g.loc[g.regime == "different", "share"].mean()), 4)
        rows.append(rec)
    return pd.DataFrame(rows)


def rain_effect(counts: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (var, transfer, regime), grp in counts.groupby(["var", "transfer", "regime"]):
        for contrast, col in (("prior24h>=10mm_vs_<1mm", "rain24h"), ("prior72h>=20mm_vs_<1mm", "rain72h")):
            for scope in ("all", "wet_season"):
                g = grp if scope == "all" else grp[grp["season"] == "wet"]
                g = g[g[col].isin(["heavy", "none"])]
                agg = g.groupby(["date", col])[["w", "n"]].sum().unstack(col, fill_value=0)
                if ("n", "heavy") not in agg or ("n", "none") not in agg:
                    continue
                da, db = int((agg[("n", "heavy")] > 0).sum()), int((agg[("n", "none")] > 0).sum())
                if da < 10 or db < 10:
                    continue
                sa = agg[("w", "heavy")].sum() / agg[("n", "heavy")].sum()
                sb = agg[("w", "none")].sum() / agg[("n", "none")].sum()
                diff, lo, hi = bootstrap_share_difference(agg[("w", "heavy")], agg[("n", "heavy")],
                                                          agg[("w", "none")], agg[("n", "none")], N_BOOT, SEED)
                rows.append({"dataset": DATASET, "var": var, "transfer": transfer, "regime": regime,
                             "contrast": contrast, "scope": scope, "days_heavy": da, "days_none": db,
                             "share_heavy": round(float(sa), 4), "share_none": round(float(sb), 4),
                             "diff_heavy_minus_none": round(diff, 4), "ci_low": round(lo, 4), "ci_high": round(hi, 4),
                             "significant": bool(hi < 0 or lo > 0)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- inputs
def load_or_fetch_rain(derived_dir: Path = ul.DERIVED_DIR, allow_fetch: bool = True) -> tuple[pd.Series | None, dict]:
    lat, lon = CENTROID
    path = derived_dir / f"open_meteo_era5_precip_hourly_utc_{lat:.2f}_{lon:.2f}_{RAIN_START}_{RAIN_END}.csv"
    url = ("https://archive-api.open-meteo.com/v1/archive?"
           f"latitude={lat:.2f}&longitude={lon:.2f}&start_date={RAIN_START}&end_date={RAIN_END}"
           "&hourly=precipitation&models=era5&timezone=GMT")
    meta = {"file": str(path), "url": url}
    if not path.exists():
        if not allow_fetch:
            return None, {**meta, "status": "absent_no_fetch"}
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ul.USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # network failure must not block the deliverable
            return None, {**meta, "status": f"fetch_failed: {exc!r}"}
        frame = pd.DataFrame({"time_utc": payload["hourly"]["time"], "precip_mm": payload["hourly"]["precipitation"]})
        derived_dir.mkdir(parents=True, exist_ok=True)
        with open(path, "x", encoding="utf-8", newline="") as handle:  # write-once
            frame.to_csv(handle, index=False)
        meta_path = path.with_suffix(".json")
        if not meta_path.exists():
            meta_path.write_text(json.dumps({"url": url, "fetched_utc": datetime.now(timezone.utc).isoformat(
                timespec="seconds"), "grid_lat": payload.get("latitude"), "grid_lon": payload.get("longitude")},
                indent=2), encoding="utf-8")
    frame = pd.read_csv(path, parse_dates=["time_utc"])
    rain = frame.set_index("time_utc")["precip_mm"].astype(float)
    return rain, {**meta, "status": "ok", "sha256": sha256(path), "n_hours": int(rain.notna().sum())}


def git_commit() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "experiments/usgs_load.py",
                                "experiments/usgs_reliability.py"], cwd=ROOT, capture_output=True, text=True).stdout
        return sha + ("+uncommitted-usgs-scripts" if dirty.strip() else "")
    except OSError:
        return "unknown"


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output-dir", type=Path, default=paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME)
    ap.add_argument("--raw-dir", type=Path, default=ul.RAW_DIR)
    ap.add_argument("--no-fetch", action="store_true", help="do not fetch rain if absent")
    args = ap.parse_args(argv)
    out = prepare_output_dir(args.output_dir)

    catalog = ul.read_catalog(args.raw_dir / "site_series_catalog.rdb.gz")
    stations = ul.station_table(catalog)
    hourly, report = ul.build_hourly(args.raw_dir)
    hourly = hourly[(hourly["hour_utc"] >= pd.Timestamp(ul.PERIOD_START) - pd.Timedelta(hours=LST_OFFSET_H))
                    & (hourly["hour_utc"] < pd.Timestamp(ul.PERIOD_END) + pd.Timedelta(days=1, hours=-LST_OFFSET_H))]
    wide = {var: hourly[hourly["var"] == var].pivot(index="hour_utc", columns="site", values="value")
            for var in VARS if (hourly["var"] == var).any()}
    rain, rain_meta = load_or_fetch_rain(allow_fetch=not args.no_fetch)

    pairs = pair_table(stations, wide)
    sel = report["series"]
    depth = {(r.site, VAR_PCODE[r.pcode]): r.depth for r in sel.itertuples() if r.pcode in VAR_PCODE}
    pairs["anchor_depth"] = [depth.get((a, "Sal"), "") for a in pairs["anchor"]]
    pairs["target_depth"] = [depth.get((t, "Sal"), "") for t in pairs["target"]]
    pairs["mixed_depth"] = pairs["anchor_depth"] != pairs["target_depth"]
    med = regime_medians(wide["Sal"])
    st_out = stations.merge(med, left_on="site", right_index=True, how="left")
    coverage = hourly[hourly["var"].isin(list(VARS))].groupby(["site", "var"])["hour_utc"].agg(
        n_hours="size", first="min", last="max").reset_index()
    st_out.to_csv(out / "stations.csv", index=False)
    coverage.to_csv(out / "coverage.csv", index=False)
    report["series"].to_csv(out / "series_selected.csv", index=False)
    report["qc_counts"].to_csv(out / "qc_counts.csv", index=False)
    ul.salinity_validation(hourly).to_csv(out / "salinity_validation.csv", index=False)

    n_day_cols = [f"n_days_{v}" for v in wide]
    pairs_out = pairs[["anchor", "target", "anchor_code", "target_code", "km", "distance_bin", "regime", "dsal",
                       "dsal_overlap", "regime_overlap", "anchor_depth", "target_depth", "mixed_depth", *n_day_cols]]
    pairs_out.to_csv(out / "pairs.csv", index=False)

    all_hours = pd.DatetimeIndex(sorted(hourly["hour_utc"].unique()))
    strata = build_strata(all_hours, rain)
    counts, pair_rows = [], []
    for p in pairs.itertuples(index=False):
        for var, table in wide.items():
            if getattr(p, f"n_days_{var}") < MIN_OVERLAP_DAYS:
                continue
            frame = transfer_frame(table[p.anchor], table[p.target], var)
            c = daily_counts(frame, strata)
            c = c.assign(pair=f"{p.anchor}>{p.target}", anchor=p.anchor, target=p.target, var=var, km=p.km,
                         distance_bin=p.distance_bin, regime=p.regime, dsal=p.dsal)
            counts.append(c)
            for transfer, sub in c.groupby("transfer"):
                per_day = sub.groupby("date")[["w", "n"]].sum()
                share, lo, hi = bootstrap_share(per_day["w"], per_day["n"], n_boot=N_BOOT, seed=SEED)
                pair_rows.append({"dataset": DATASET, "anchor": p.anchor, "target": p.target,
                                  "anchor_code": p.anchor_code, "target_code": p.target_code, "var": var,
                                  "transfer": transfer, "km": p.km, "distance_bin": p.distance_bin, "regime": p.regime,
                                  "dsal": p.dsal, "dsal_overlap": p.dsal_overlap,
                                  "anchor_depth": depth.get((p.anchor, var), ""),
                                  "target_depth": depth.get((p.target, var), ""),
                                  "mixed_depth": depth.get((p.anchor, var)) != depth.get((p.target, var)),
                                  "n_days": len(per_day),
                                  "n_hours": int(per_day["n"].sum()), "share": round(share, 4),
                                  "ci_low": round(lo, 4), "mae": round(float(sub["abs_err"].sum() / sub["n"].sum()), 4),
                                  **{f"gate{int(g * 100)}": gate_status(lo, len(per_day), g) for g in GATES}})
    counts = pd.concat(counts, ignore_index=True)
    pair_rel = pd.DataFrame(pair_rows)
    pair_rel.to_csv(out / "pair_reliability.csv", index=False)

    cells = summarise(counts, ["var", "regime", "distance_bin", "transfer"])
    cells.insert(0, "dataset", DATASET)
    cells = cells[["dataset", "var", "regime", "distance_bin", "transfer", "n_days", "share", "ci_low", "gate80",
                   "gate90", "gate95", "n_pairs", "n_hours", "ci_high", "mae"]]
    cells.to_csv(out / "cells.csv", index=False)
    # regime-free view (all pairs) for comparison with RL-12
    cells_all = summarise(counts.assign(regime="all"), ["var", "regime", "distance_bin", "transfer"])
    cells_all.insert(0, "dataset", DATASET)
    cells_all.to_csv(out / "cells_all_regimes.csv", index=False)

    radius = reliability_radius(pd.concat([cells, cells_all]), ["dataset", "var", "regime", "transfer"])
    radius.to_csv(out / "radius.csv", index=False)

    strata_rows = []
    for col in ("season", "daynight", "rain24h", "rain72h"):
        s = summarise(counts[counts[col] != "na"], ["var", "regime", "transfer", col]).rename(columns={col: "level"})
        strata_rows.append(s.assign(stratum=col))
    strata_cells = pd.concat(strata_rows, ignore_index=True)
    strata_cells.insert(0, "dataset", DATASET)
    strata_cells.to_csv(out / "strata.csv", index=False)

    regime_vs_distance(pair_rel).to_csv(out / "regime_vs_distance.csv", index=False)
    rain_effect(counts).to_csv(out / "rain_effect.csv", index=False)

    raw = ul.raw_files(args.raw_dir)
    manifest = {
        "run": RUN_NAME, "dataset": DATASET, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_commit": git_commit(),
        "inputs": {"raw_dir": str(args.raw_dir), "n_raw_files": len(raw),
                   "raw_bytes": int(sum(p.stat().st_size for p in raw)),
                   "raw_files_sha256": {p.relative_to(args.raw_dir).as_posix(): sha256(p) for p in raw},
                   "catalog_sha256": sha256(args.raw_dir / "site_series_catalog.rdb.gz"), "rain": rain_meta},
        "parameters": {"period": [str(ul.PERIOD_START), str(ul.PERIOD_END)], "good_code": ul.GOOD_CODE,
                       "ranges": ul.RANGES, "min_obs_per_hour": ul.MIN_OBS_PER_HOUR,
                       "salinity": "PSS-78 from SpC (00095) at t=25 C", "tolerances_key": VARS,
                       "min_overlap_days": MIN_OVERLAP_DAYS, "gates": GATES, "min_days": MIN_DAYS, "n_boot": N_BOOT,
                       "seed": SEED, "cal_window": CAL_WINDOW, "cal_min_hours": CAL_MIN_HOURS,
                       "regime_dsal_psu": REGIME_DSAL_PSU, "season_wet_months": [11, 12, 1, 2, 3, 4],
                       "lst_offset_h": LST_OFFSET_H, "rain_centroid": CENTROID,
                       "rain_thresholds_mm": {"24h_heavy": RAIN24_HEAVY_MM, "72h_heavy": RAIN72_HEAVY_MM,
                                              "none_lt": RAIN_NONE_MM}, "distance_bins": BIN_LABELS},
        "qc": {"n_raw_rows": report["n_raw_rows"], "n_accepted": report["n_accepted"]},
        "n_pairs_evaluated": int(pair_rel[["anchor", "target", "var"]].drop_duplicates().shape[0]),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
