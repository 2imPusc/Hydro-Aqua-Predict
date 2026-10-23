"""H4.2 -- direction-4 reliability on the Texas TWDB coastal sonde network.

Question (as RL-12 NERRS Jobos, RL-14 HK EPD): can an in-situ sensor ("anchor")
stand in for another location ("target")? Reliability = share of hours with
|anchor-derived estimate - target observation| <= tolerance.

Data: ``paths.FOREIGN_DATA_DIR / "texas_twdb"`` (see ``experiments/twdb_load.py``
and the SOURCES.md there). 18 TWDB/TPWD sondes in four Texas estuary systems
(Guadalupe/San Antonio Bay, Trinity-Galveston, Colorado-Lavaca/Matagorda,
Sabine), 2008-2019 (native hourly; 2020+ is served quantised -- see YEARS). Subtropical (26-30 N),
microtidal (diurnal range ~0.1-0.6 m), river-inflow-driven salinity gradients.
Variables: Temp, Sal (both rich), DO (few stations); pH/turbidity too sparse for
any pair (no pair -> reported as "no data").

Common H4 protocol (shared with the other foreign sets):
* Hourly means of QC-good values (twdb_load: provider range/spike/flatline
  limits); >= 2 obs/h where native cadence < 1 h, else the single hourly reading
  (protocol deviation: the network logged hourly until ~2019-20).
* Tolerances Temp 0.5 C, Sal 1 psu, DO 0.5 mg/L (``nerrs_reliability.within_tolerance``).
* Pairs: every ordered pair with >= 365 distinct days of joint hourly data;
  bins 0-2, 2-5, 5-10, 10-20, 20-30, >30 km.
* Season: **high-flow = Mar-Jul**, low-flow = Aug-Feb. Chosen from the data: in
  the 2008-2025 daily means of 13 stations, Mar-Jul are the five months with the
  lowest mean salinity rank (spring freshets; Texas river inflow peaks Apr-Jun).
* Regime: station median salinity in the high-flow season (all years);
  pair "same" if |delta| < 2 psu. Continuous ``dsal`` kept; ``dsal_joint`` uses
  only the pair's joint high-flow hours (sensitivity).
* Transfers: ``raw`` = anchor value; ``calibrated`` = a + b*anchor, OLS on the
  pair's strictly-past 30 days (``nerrs_reliability.rolling_linear_transfer``,
  >= 240 joint hours).
* Gates 80/90/95 %: day-block bootstrap lower 95 % bound (500 resamples, seed
  20261016) >= gate and >= 30 days (``bootstrap_share``/``gate_status``).
* Strata: season; rain from ERA5 (Open-Meteo archive, hourly, one point per
  system = station centroid; the TWDB sondes carry no rain gauge): prior 24 h
  >= 10 mm vs < 1 mm, prior 72 h >= 20 mm vs < 1 mm; day/night (solar elevation,
  LST = UTC-6). Rain for a pair = rain at the *target's* system. Tide not used.
* Radius: upper edge of the last contiguous passing bin, walking up from the
  first bin that has pairs (empty bins are skipped, an "insufficient" populated
  bin stops the walk). 0 = first populated bin fails.
* Regime vs distance: pair-level (n_days-weighted) OLS of share on z(km) and
  z(dsal), and a binomial logit on pooled hour counts with the same z
  predictors; CIs from 500 bootstrap resamples of *unordered* pairs.

Run:  .venv\\Scripts\\python experiments\\twdb_reliability.py
Outputs: artifacts/experiments/twdb-h4-reliability-20261017/ (refuses to overwrite).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import paths  # noqa: E402
from experiments import twdb_load as tl  # noqa: E402
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

RUN_NAME = "twdb-h4-reliability-20261017"
DATASET = "TWDB"
VARIABLES = ("Temp", "Sal", "DO_mgl")
TOLERANCE_TEXT = {"Temp": "0.5 C", "Sal": "1 psu", "DO_mgl": "0.5 mg/L"}
HIGH_FLOW_MONTHS = (3, 4, 5, 6, 7)
# Primary period. From ~2020 the API serves the 15-min record quantised (salinity to
# 1 psu = the tolerance, temperature to 0.1 C; 60-95 % repeated consecutive values),
# so 2020-2025 is excluded. 2008-2019 is native hourly at 0.001-0.01 resolution.
YEARS = range(2008, 2020)
GATES = (0.80, 0.90, 0.95)
MIN_DAYS = 30
MIN_OVERLAP_DAYS = 365
N_BOOT = 500
SEED = 20261016
REGIME_DSAL_PSU = 2.0
RAIN24_HEAVY_MM, RAIN72_HEAVY_MM, RAIN_NONE_MM = 10.0, 20.0, 1.0
BIN_EDGES = [0, 2, 5, 10, 20, 30, np.inf]
BIN_LABELS = ["0-2", "2-5", "5-10", "10-20", "20-30", ">30"]
BIN_UPPER_KM = {"0-2": 2.0, "2-5": 5.0, "5-10": 10.0, "10-20": 20.0, "20-30": 30.0, ">30": np.inf}
TRANSFERS = ("raw", "calibrated")


# ---------------------------------------------------------------- primitives
def season_of(index) -> np.ndarray:
    return np.where(pd.DatetimeIndex(index).month.isin(HIGH_FLOW_MONTHS), "high_flow", "low_flow")


def distance_bin(km) -> np.ndarray:
    return pd.cut(np.asarray(km, dtype=float), BIN_EDGES, labels=BIN_LABELS, right=False).astype(str)


def rain_class(total: pd.Series, heavy: float, none: float = RAIN_NONE_MM) -> np.ndarray:
    t = total.to_numpy(float)
    return np.select([np.isnan(t), t < none, t >= heavy], ["na", "none", "heavy"], "light")


def station_salinity_medians(hourly: pd.DataFrame) -> pd.DataFrame:
    sal = hourly[hourly["variable"] == "Sal"]
    season = season_of(sal["time_lst"])
    out = sal.assign(season=season).groupby(["station", "season"])["value"].median().unstack("season")
    return out.reindex(columns=["high_flow", "low_flow"]).round(2)


def build_pairs(stations: pd.DataFrame, medians: pd.DataFrame, threshold: float = REGIME_DSAL_PSU) -> pd.DataFrame:
    s = stations[["station", "system", "lat", "lon"]]
    p = s.merge(s, how="cross", suffixes=("_a", "_t"))
    p = p[p["station_a"] != p["station_t"]].reset_index(drop=True)
    hf = medians["high_flow"] if "high_flow" in medians else pd.Series(dtype=float)
    sal_a, sal_t = p["station_a"].map(hf), p["station_t"].map(hf)
    dsal = (sal_a - sal_t).abs()
    km = haversine_km(p["lat_a"], p["lon_a"], p["lat_t"], p["lon_t"])
    return pd.DataFrame({
        "anchor": p["station_a"], "target": p["station_t"], "system_anchor": p["system_a"],
        "system_target": p["system_t"], "km": np.round(km, 3), "distance_bin": distance_bin(km),
        "sal_hf_anchor": sal_a, "sal_hf_target": sal_t, "dsal": dsal.round(2),
        "regime": np.select([dsal.isna(), dsal < threshold], ["unknown", "same"], "different"),
    })


def build_strata(hours: pd.DatetimeIndex, rain: pd.Series | None, lat: float, lon: float) -> pd.DataFrame:
    strata = pd.DataFrame(index=hours)
    elevation = solar_elevation_deg(hours + pd.Timedelta(minutes=30), lat, lon, utc_offset_h=tl.LST_OFFSET_H)
    strata["daynight"] = np.where(elevation > 0, "day", "night")
    if rain is None:
        strata["rain24"] = strata["rain72"] = "na"
        return strata
    for label, h, heavy in (("rain24", 24, RAIN24_HEAVY_MM), ("rain72", 72, RAIN72_HEAVY_MM)):
        strata[label] = rain_class(prior_window_sum(rain, h).reindex(hours), heavy)
    return strata


def transfer_estimates(x: pd.Series, y: pd.Series) -> dict[str, pd.Series]:
    return {"raw": x, "calibrated": rolling_linear_transfer(x, y)}


def aggregate_days(frame: pd.DataFrame) -> pd.DataFrame:
    """frame(index=hour, within, abs_err, daynight, rain24, rain72) -> per day x stratum sums."""
    day = frame.index.normalize()
    g = frame.assign(day=day, w=frame["within"].astype(int), n=1).groupby(
        ["day", "daynight", "rain24", "rain72"], observed=True)
    return g.agg(w=("w", "sum"), n=("n", "sum"), abs_err_sum=("abs_err", "sum")).reset_index()


def summarise(agg: pd.DataFrame, keys, n_boot: int = N_BOOT, seed: int = SEED) -> pd.DataFrame:
    """Per cell: pooled share + day-block bootstrap CI + gates (days pooled across pairs)."""
    rows = []
    for cell, grp in agg.groupby(list(keys), observed=True, sort=True):
        per_day = grp.groupby("day")[["w", "n"]].sum()
        share, lo, hi = bootstrap_share(per_day["w"], per_day["n"], n_boot=n_boot, seed=seed)
        rec = dict(zip(keys, cell if isinstance(cell, tuple) else (cell,)))
        rec.update({"n_pairs": int(grp[["anchor", "target"]].drop_duplicates().shape[0]) if "anchor" in grp else np.nan,
                    "n_hours": int(per_day["n"].sum()), "n_days": int(len(per_day)),
                    "mae": round(float(grp["abs_err_sum"].sum() / per_day["n"].sum()), 4),
                    "share": round(share, 4), "ci_low": round(lo, 4), "ci_high": round(hi, 4)})
        for g in GATES:
            rec[f"gate{int(g * 100)}"] = gate_status(lo, len(per_day), g, min_days=MIN_DAYS)
        rows.append(rec)
    return pd.DataFrame(rows)


def reliability_radius(cells: pd.DataFrame, keys, gates=GATES) -> pd.DataFrame:
    """Upper km edge of the last contiguous passing bin, starting at the first populated bin."""
    rows = []
    for cell, grp in cells.groupby(list(keys), sort=True):
        for g in gates:
            col = f"gate{int(g * 100)}"
            status = grp.set_index("distance_bin")[col].to_dict()
            populated = [b for b in BIN_LABELS[:-1] if b in status]  # radius is capped at 30 km
            radius, stop = np.nan, "no_data"
            if populated:
                radius, stop = 0.0, "all_pass"
                for label in populated:
                    if status[label] == "pass":
                        radius = BIN_UPPER_KM[label]
                        continue
                    stop = f"{status[label]}@{label}"
                    if status[label] == "insufficient" and label == populated[0]:
                        radius = np.nan
                    break
            rec = dict(zip(keys, cell if isinstance(cell, tuple) else (cell,)))
            rec.update({"gate": int(g * 100), "radius_km": radius, "first_populated_bin": populated[0] if populated else None,
                        "stop": stop})
            rows.append(rec)
    return pd.DataFrame(rows)


def _zscore(v: np.ndarray) -> np.ndarray:
    sd = v.std()
    return (v - v.mean()) / sd if sd > 0 else v * 0.0


def _ols_std(share, km, dsal, weight) -> np.ndarray:
    X = np.column_stack([np.ones(len(km)), _zscore(km), _zscore(dsal)])
    sw = np.sqrt(weight)
    coef, *_ = np.linalg.lstsq(X * sw[:, None], share * sw, rcond=None)
    return coef


def _logit_std(w, n, km, dsal) -> np.ndarray:
    from sklearn.linear_model import LogisticRegression
    Z = np.column_stack([_zscore(km), _zscore(dsal)])
    X = np.vstack([Z, Z])
    y = np.r_[np.ones(len(w)), np.zeros(len(w))]
    sample_weight = np.r_[w, n - w].astype(float)
    keep = sample_weight > 0
    model = LogisticRegression(C=np.inf, max_iter=1000)
    model.fit(X[keep], y[keep], sample_weight=sample_weight[keep])
    return np.r_[model.intercept_, model.coef_[0]]


def regime_vs_distance(pair_rel: pd.DataFrame, n_boot: int = N_BOOT, seed: int = SEED,
                       dsal_col: str = "dsal") -> pd.DataFrame:
    """Standardised effects of distance and |delta salinity| on pair reliability."""
    rows = []
    for (var, transfer, scope), grp in _scoped(pair_rel).groupby(["variable", "transfer", "scope"]):
        grp = grp.dropna(subset=[dsal_col]).reset_index(drop=True)
        if len(grp) < 5 or grp["km"].std() == 0 or grp[dsal_col].std() == 0:
            continue
        km, ds = grp["km"].to_numpy(float), grp[dsal_col].to_numpy(float)
        w, n = grp["w"].to_numpy(float), grp["n"].to_numpy(float)
        share, weight = w / n, grp["n_days"].to_numpy(float)
        ols, logit = _ols_std(share, km, ds, weight), _logit_std(w, n, km, ds)
        key = grp.apply(lambda r: "|".join(sorted((r.anchor, r.target))), axis=1).to_numpy()
        uniq = np.unique(key)
        members = {k: np.flatnonzero(key == k) for k in uniq}
        rng = np.random.default_rng(seed)
        boot_ols, boot_logit = [], []
        for _ in range(n_boot):
            idx = np.concatenate([members[k] for k in rng.choice(uniq, size=len(uniq), replace=True)])
            if np.std(km[idx]) == 0 or np.std(ds[idx]) == 0:
                continue
            boot_ols.append(_ols_std(share[idx], km[idx], ds[idx], weight[idx]))
            boot_logit.append(_logit_std(w[idx], n[idx], km[idx], ds[idx]))
        bo, bl = np.array(boot_ols), np.array(boot_logit)
        rho_km = pd.Series(km).corr(pd.Series(share), method="spearman")
        rho_ds = pd.Series(ds).corr(pd.Series(share), method="spearman")
        rec = {"dataset": DATASET, "variable": var, "transfer": transfer, "scope": scope, "dsal_measure": dsal_col,
               "n_ordered_pairs": len(grp), "n_unordered_pairs": len(uniq),
               "km_range": f"{km.min():.1f}-{km.max():.1f}", "dsal_range": f"{ds.min():.1f}-{ds.max():.1f}",
               "corr_km_dsal": round(float(np.corrcoef(km, ds)[0, 1]), 3),
               "spearman_share_km": round(float(rho_km), 3), "spearman_share_dsal": round(float(rho_ds), 3)}
        for name, est, boot in (("ols", ols, bo), ("logit", logit, bl)):
            for j, term in ((1, "km"), (2, "dsal")):
                lo, hi = np.percentile(boot[:, j], [2.5, 97.5]) if len(boot) else (np.nan, np.nan)
                rec[f"{name}_beta_{term}"] = round(float(est[j]), 4)
                rec[f"{name}_beta_{term}_ci_low"] = round(float(lo), 4)
                rec[f"{name}_beta_{term}_ci_high"] = round(float(hi), 4)
            diff = np.abs(boot[:, 2]) - np.abs(boot[:, 1]) if len(boot) else np.array([np.nan])
            rec[f"{name}_p_abs_dsal_gt_abs_km"] = round(float(np.mean(diff > 0)), 3)
        rec["regime_beats_distance"] = bool(abs(logit[2]) > abs(logit[1]) and rec["logit_p_abs_dsal_gt_abs_km"] >= 0.95)
        rows.append(rec)
    return pd.DataFrame(rows)


def _scoped(pair_rel: pd.DataFrame) -> pd.DataFrame:
    near = pair_rel[pair_rel["km"] < 30].assign(scope="le30km")
    return pd.concat([near, pair_rel.assign(scope="all_km")], ignore_index=True)


EFFECTS = [  # (name, column, level A, level B)
    ("rain24h_ge10_vs_lt1", "rain24", "heavy", "none"),
    ("rain72h_ge20_vs_lt1", "rain72", "heavy", "none"),
    ("night_vs_day", "daynight", "night", "day"),
    ("high_flow_vs_low_flow", "season", "high_flow", "low_flow"),
]


def effect_table(agg: pd.DataFrame, group_keys, effects=EFFECTS, n_boot: int = N_BOOT, seed: int = SEED) -> pd.DataFrame:
    rows = []
    for cell, grp in agg.groupby(list(group_keys), observed=True, sort=True):
        base = dict(zip(group_keys, cell if isinstance(cell, tuple) else (cell,)))
        for scope in ("all", "high_flow"):
            g = grp if scope == "all" else grp[grp["season"] == "high_flow"]
            for name, col, a, b in effects:
                if scope == "high_flow" and col == "season":
                    continue
                sub = g.assign(is_a=g[col] == a, is_b=g[col] == b)
                days = sub.assign(w_a=sub["w"] * sub["is_a"], n_a=sub["n"] * sub["is_a"],
                                  w_b=sub["w"] * sub["is_b"], n_b=sub["n"] * sub["is_b"]).groupby("day")[
                    ["w_a", "n_a", "w_b", "n_b"]].sum()
                da, db = int((days["n_a"] > 0).sum()), int((days["n_b"] > 0).sum())
                if da < 10 or db < 10:
                    continue
                diff, lo, hi = bootstrap_share_difference(days["w_a"], days["n_a"], days["w_b"], days["n_b"],
                                                          n_boot=n_boot, seed=seed)
                rows.append({**base, "effect": name, "scope": scope, "days_a": da, "days_b": db,
                             "hours_a": int(days["n_a"].sum()), "hours_b": int(days["n_b"].sum()),
                             "share_a": round(days["w_a"].sum() / days["n_a"].sum(), 4),
                             "share_b": round(days["w_b"].sum() / days["n_b"].sum(), 4),
                             "diff_a_minus_b": round(diff, 4), "ci_low": round(lo, 4), "ci_high": round(hi, 4),
                             "significant": bool(lo > 0 or hi < 0)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- main evaluation
def evaluate(hourly: pd.DataFrame, pairs: pd.DataFrame, strata_by_system: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Returns (pair n_days table, per-pair reliability, day-level aggregate)."""
    n_days_rows, rel_rows, aggs = [], [], []
    for var in VARIABLES:
        sub = hourly[hourly["variable"] == var]
        if sub.empty:
            continue
        wide = sub.pivot(index="time_lst", columns="station", values="value")
        single = sub.pivot(index="time_lst", columns="station", values="n_obs") == 1
        for pair in pairs.itertuples(index=False):
            if pair.anchor not in wide or pair.target not in wide:
                continue
            joint = wide[[pair.anchor, pair.target]].dropna()
            n_days = int(joint.index.normalize().nunique())
            if n_days == 0:
                continue
            n_days_rows.append({"anchor": pair.anchor, "target": pair.target, "variable": var, "n_days": n_days})
            if n_days < MIN_OVERLAP_DAYS:
                continue
            x, y = joint[pair.anchor], joint[pair.target]
            single_share = float(single.reindex(joint.index)[[pair.anchor, pair.target]].any(axis=1).mean())
            strata = strata_by_system[pair.system_target]
            for transfer, est in transfer_estimates(x, y).items():
                frame = pd.DataFrame({"est": est, "obs": y}).dropna()
                if frame.empty:
                    continue
                frame["err"] = frame["obs"] - frame["est"]
                frame["abs_err"] = frame["err"].abs()
                frame["within"] = within_tolerance(var, frame["est"], frame["obs"])
                frame = frame.join(strata, how="left").fillna({"daynight": "na", "rain24": "na", "rain72": "na"})
                agg = aggregate_days(frame)
                agg["season"] = season_of(agg["day"])
                agg = agg.assign(anchor=pair.anchor, target=pair.target, variable=var, transfer=transfer)
                aggs.append(agg)
                per_day = agg.groupby("day")[["w", "n"]].sum()
                share, lo, hi = bootstrap_share(per_day["w"], per_day["n"])
                rel_rows.append({"anchor": pair.anchor, "target": pair.target, "variable": var, "transfer": transfer,
                                 "n_days": int(len(per_day)), "n_hours": int(per_day["n"].sum()),
                                 "w": int(per_day["w"].sum()), "n": int(per_day["n"].sum()),
                                 "first": frame.index.min().strftime("%Y-%m-%d"),
                                 "last": frame.index.max().strftime("%Y-%m-%d"),
                                 "share": round(share, 4), "ci_low": round(lo, 4), "ci_high": round(hi, 4),
                                 "mae": round(float(frame["abs_err"].mean()), 4),
                                 "bias_obs_minus_est": round(float(frame["err"].mean()), 4),
                                 "share_hours_single_obs": round(single_share, 4),
                                 **{f"gate{int(g * 100)}": gate_status(lo, len(per_day), g) for g in GATES}})
    n_days = pd.DataFrame(n_days_rows)
    rel = pd.DataFrame(rel_rows)
    agg = pd.concat(aggs, ignore_index=True) if aggs else pd.DataFrame()
    return n_days, rel, agg


def joint_dsal(hourly: pd.DataFrame, pairs: pd.DataFrame, min_hours: int = 24 * 30) -> pd.Series:
    """|delta median salinity| over the pair's joint high-flow hours (NaN if < min_hours)."""
    sal = hourly[hourly["variable"] == "Sal"].pivot(index="time_lst", columns="station", values="value")
    sal = sal[season_of(sal.index) == "high_flow"]
    out = {}
    for pair in pairs.itertuples(index=False):
        if pair.anchor in sal and pair.target in sal:
            s = sal[[pair.anchor, pair.target]].dropna()
            if len(s) >= min_hours:
                out[(pair.anchor, pair.target)] = round(float(abs(s[pair.anchor].median() - s[pair.target].median())), 2)
    return pd.Series(out, dtype=float)


def git_commit() -> dict:
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "experiments/twdb_load.py",
                                "experiments/twdb_reliability.py"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        return {"commit": head, "twdb_scripts_dirty": bool(dirty)}
    except Exception as exc:  # pragma: no cover
        return {"commit": None, "error": repr(exc)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME)
    parser.add_argument("--data-dir", type=Path, default=tl.RAW_DIR)
    parser.add_argument("--no-fetch", action="store_true", help="do not fetch ERA5 rain (use cache only)")
    parser.add_argument("--n-boot", type=int, default=N_BOOT)
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing output dir: {args.output_dir}")

    stations = tl.station_table(args.data_dir / "meta")
    hourly, qc, used = tl.load_hourly(data_dir=args.data_dir, years=YEARS)
    medians = station_salinity_medians(hourly)
    pairs = build_pairs(stations, medians)

    start, end = hourly["time_lst"].min(), hourly["time_lst"].max()
    hours = pd.date_range(start.floor("D"), end.ceil("D"), freq="h")
    strata_by_system, rain_meta, rain_files = {}, {}, []
    for system, grp in stations.groupby("system"):
        lat, lon = round(grp["lat"].mean(), 3), round(grp["lon"].mean(), 3)
        rain, meta = tl.load_or_fetch_rain_hourly(system.replace(" ", "_"), lat, lon,
                                                  f"{start.year - 1}-12-25", f"{end.year}-12-31",
                                                  allow_fetch=not args.no_fetch)
        rain_meta[system] = meta
        if meta["status"] == "ok":
            rain_files.append(Path(meta["file"]))
        strata_by_system[system] = build_strata(hours, rain, lat, lon)

    n_days, rel, agg = evaluate(hourly, pairs, strata_by_system)
    out = prepare_output_dir(args.output_dir)

    # pairs.csv: one row per ordered pair with any joint data
    wide_days = n_days.pivot_table(index=["anchor", "target"], columns="variable", values="n_days").add_prefix("n_days_")
    pairs_out = pairs.merge(wide_days.reset_index(), on=["anchor", "target"], how="inner")
    dj = joint_dsal(hourly, pairs_out)
    pairs_out["dsal_joint"] = [dj.get((a, t), np.nan) for a, t in zip(pairs_out["anchor"], pairs_out["target"])]
    pairs_out.to_csv(out / "pairs.csv", index=False)
    pair_rel = rel.merge(pairs_out[["anchor", "target", "km", "distance_bin", "regime", "dsal",
                                    "dsal_joint", "system_anchor",
                                    "system_target"]], on=["anchor", "target"])
    pair_rel.to_csv(out / "pair_reliability.csv", index=False)

    agg = agg.merge(pairs_out[["anchor", "target", "distance_bin", "regime"]], on=["anchor", "target"])
    agg_all = pd.concat([agg, agg.assign(regime="all")], ignore_index=True)
    cells = summarise(agg_all, ["variable", "regime", "distance_bin", "transfer"], n_boot=args.n_boot)
    cells.insert(0, "dataset", DATASET)
    cells["variable"] = cells["variable"].replace({"DO_mgl": "DO"})
    cells.rename(columns={"variable": "var"}).to_csv(out / "cells.csv", index=False)
    by_season = summarise(agg_all, ["variable", "regime", "distance_bin", "transfer", "season"], n_boot=args.n_boot)
    by_season.insert(0, "dataset", DATASET)
    by_season.to_csv(out / "cells_by_season.csv", index=False)

    radius = reliability_radius(cells.rename(columns={"variable": "var"}), ["dataset", "var", "regime", "transfer"])
    for var in ("pH", "Turbidity"):
        for regime in ("all", "same", "different"):
            for transfer in TRANSFERS:
                for g in GATES:
                    radius.loc[len(radius)] = {"dataset": DATASET, "var": var, "regime": regime, "transfer": transfer,
                                               "gate": int(g * 100), "radius_km": np.nan, "first_populated_bin": None,
                                               "stop": "no_data"}
    radius.to_csv(out / "radius.csv", index=False)

    rvd = regime_vs_distance(pair_rel, n_boot=args.n_boot)
    if pair_rel["dsal_joint"].notna().sum() >= 5:
        rvd = pd.concat([rvd, regime_vs_distance(pair_rel, n_boot=args.n_boot, dsal_col="dsal_joint")], ignore_index=True)
    rvd.to_csv(out / "regime_vs_distance.csv", index=False)

    near = agg_all[agg_all["distance_bin"].isin(BIN_LABELS[:-1])]
    rain_eff = effect_table(near, ["variable", "transfer", "regime"], effects=EFFECTS[:2], n_boot=args.n_boot)
    rain_eff.insert(0, "dataset", DATASET)
    rain_eff.insert(1, "distance_scope", "le30km")
    rain_eff.to_csv(out / "rain_effect.csv", index=False)
    other_eff = effect_table(near, ["variable", "transfer", "regime"], effects=EFFECTS[2:], n_boot=args.n_boot)
    other_eff.to_csv(out / "strata_effects.csv", index=False)

    stations.assign(sal_median_high_flow=stations["station"].map(medians["high_flow"]),
                    sal_median_low_flow=stations["station"].map(medians["low_flow"])).to_csv(out / "stations.csv", index=False)
    qc.to_csv(out / "qc_summary.csv", index=False)
    coverage = hourly.assign(year=hourly["time_lst"].dt.year).groupby(["station", "variable", "year"]).agg(
        hours=("value", "size"), single_obs_hours=("n_obs", lambda s: int((s == 1).sum()))).reset_index()
    coverage.to_csv(out / "coverage.csv", index=False)

    strata_counts = {s: {c: st[c].value_counts().to_dict() for c in ("daynight", "rain24", "rain72")}
                     for s, st in strata_by_system.items()}
    inputs = [*used, *sorted((args.data_dir / "meta").glob("*.json")), *rain_files]
    manifest = {
        "run": RUN_NAME, "dataset": DATASET, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scripts": ["experiments/twdb_load.py", "experiments/twdb_reliability.py"], "code": git_commit(),
        "source": "TWDB Texas coastal hydrology API https://www.waterdatafortexas.org/coastal/api (provisional data)",
        "parameters": {
            "variables": list(VARIABLES), "tolerances": TOLERANCE_TEXT, "time_basis": "LST = UTC-6 (CST, no DST)",
            "years": [YEARS[0], YEARS[-1]],
            "hourly_rule": ">=2 QC-good obs/h if native cadence < 60 min, else the single hourly reading",
            "qc": "provider MPRMIN/MPRMAX + physical band; spike |x-median3|>THRSHLD_LOW; flatline run>=REP_CNT_FAIL (Sal<=1 exempt)",
            "high_flow_months": list(HIGH_FLOW_MONTHS), "regime_dsal_psu": REGIME_DSAL_PSU,
            "regime_basis": "station median salinity in high-flow season, all years",
            "min_overlap_days": MIN_OVERLAP_DAYS, "distance_bins_km": BIN_LABELS,
            "calibrated": "OLS on strictly-past 30 days, >=240 joint hours", "gates": GATES,
            "gate_rule": "day-block bootstrap lower 95% bound >= gate and n_days >= 30", "n_boot": args.n_boot,
            "seed": SEED, "rain": {"source": "Open-Meteo ERA5 archive hourly precipitation at system centroid",
                                    "rain24_heavy_mm": RAIN24_HEAVY_MM, "rain72_heavy_mm": RAIN72_HEAVY_MM,
                                    "none_mm": RAIN_NONE_MM, "applies_to": "target system"},
            "radius_rule": "walk bins upward from first populated bin; empty bins skipped; stop at first non-pass",
        },
        "rain": rain_meta, "stratum_hour_counts": strata_counts,
        "share_eval_hours_single_obs": round(float((pair_rel["share_hours_single_obs"] * pair_rel["n_hours"]).sum()
                                                   / pair_rel["n_hours"].sum()), 4) if len(pair_rel) else None,
        "inputs": [{"file": str(p.relative_to(paths.PROJECT_ROOT)).replace("\\", "/") if p.is_relative_to(paths.PROJECT_ROOT) else str(p),
                    "bytes": p.stat().st_size, "sha256": sha256(p)} for p in inputs],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
