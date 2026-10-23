"""Direction-4 methods pilot on NERRS Jobos Bay: how far, and under what weather,
can one station's data stand in for another location?

For every ordered pair (anchor -> target) and variable this computes the
hourly transfer error of

* ``persistence_in_space``: estimate(target, t) = anchor(t)  (the baseline the
  VN P0/P1 work calls ``anchor_copy_observed_value``), and
* ``calibrated_30d``: estimate = a + b * anchor(t), with (a, b) fitted by OLS on
  the pair's hourly data in the strictly-past window [t - 30 d, t) -- no
  look-ahead. NB: this needs target history, i.e. it models a site that already
  had a reference measurement (H4.4), not an unmeasured cell.

Reliability = share of hours with |error| <= tolerance; 80/90/95 % gates pass
only if the **day-block bootstrap** lower 95 % bound reaches the target (hours
are autocorrelated, so per-hour Wilson bounds would be over-confident) and the
stratum has >= MIN_DAYS distinct days. Strata come from the Jobos met station
(observation-only): prior-6 h / prior-24 h rain, concurrent wind tercile, plus
day/night (solar elevation, LST = UTC-4) and season (wet May-Nov).

Run:  .venv\\Scripts\\python experiments\\nerrs_reliability.py
Outputs: artifacts/experiments/nerrs-h4-pilot-20261016/ (refuses to overwrite).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import paths  # noqa: E402
from experiments import nerrs_load as nl  # noqa: E402

RUN_NAME = "nerrs-h4-pilot-20261016"
WQ_YEARS = range(2007, 2012)   # <0>-flag data only exists from 2007 (earlier = <4> historical)
MET_YEARS = range(2007, 2011)  # jobjbmet2011.csv is a mislabeled empty WQ file
GATES = (0.80, 0.90, 0.95)
MIN_DAYS = 30
N_BOOT = 500
SEED = 20261016
RAIN6_HEAVY_MM = 5.0
RAIN24_HEAVY_MM = 10.0

# variable key -> (source column, absolute tolerance, relative tolerance, sensor accuracy note)
# Tolerances are set at aquaculture-decision scale and never below sensor accuracy
# (YSI 6600 spec in jobwq metadata section 6: DO +/-0.2 mg/L, pH +/-0.2, Turb 5 % or 2 NTU).
TOLERANCES = {
    "Temp": ("Temp", 0.5, 0.0, "+/-0.15 C"),
    "Sal": ("Sal", 1.0, 0.0, "+/-1% of reading or 0.1 psu"),
    "DO_mgl": ("DO_mgl", 0.5, 0.0, "+/-0.2 mg/L"),
    "pH": ("pH", 0.2, 0.0, "+/-0.2 units"),
    "pH@0.1": ("pH", 0.1, 0.0, "+/-0.2 units (tolerance below accuracy: secondary row)"),
    "Turb": ("Turb", 2.0, 0.20, "+/-5% or 2 NTU"),
}


# ---------------------------------------------------------------- metric primitives
def within_tolerance(var_key: str, estimate, observed) -> np.ndarray:
    _, absolute, relative, _ = TOLERANCES[var_key]
    observed = np.asarray(observed, dtype=float)
    bound = np.maximum(absolute, relative * np.abs(observed))
    return np.abs(observed - np.asarray(estimate, dtype=float)) <= bound + 1e-9


def rolling_linear_transfer(anchor: pd.Series, target: pd.Series, window: str = "30D",
                            min_hours: int = 240) -> pd.Series:
    """Estimate target(t) = a + b*anchor(t) with OLS on [t - window, t) only."""
    joint = pd.DataFrame({"x": anchor, "y": target}).dropna().sort_index()
    x, y = joint["x"], joint["y"]
    terms = pd.DataFrame({"n": 1.0, "x": x, "y": y, "xx": x * x, "xy": x * y}, index=joint.index)
    past = terms.rolling(window, closed="left").sum()
    n = past["n"]
    mean_x, mean_y = past["x"] / n, past["y"] / n
    var_x = past["xx"] / n - mean_x ** 2
    cov_xy = past["xy"] / n - mean_x * mean_y
    slope = (cov_xy / var_x).where(var_x > 1e-9, 1.0)  # flat anchor -> offset-only map
    intercept = mean_y - slope * mean_x
    estimate = intercept + slope * x
    return estimate.where(n >= min_hours)


def prior_window_sum(series: pd.Series, hours: int, min_coverage: float = 5 / 6) -> pd.Series:
    """Sum over the ``hours`` hours strictly before each hour; NaN if coverage too low."""
    full = series.asfreq("h")
    window = full.rolling(hours, min_periods=1).agg(["sum", "count"]).shift(1)
    enough = window["count"] >= int(np.ceil(hours * min_coverage))
    return window["sum"].where(enough).reindex(full.index)


def season_of(index: pd.DatetimeIndex) -> np.ndarray:
    return np.where(index.month.isin(range(5, 12)), "wet", "dry")


def solar_elevation_deg(index_lst: pd.DatetimeIndex, lat: float, lon: float, utc_offset_h: float = -4) -> np.ndarray:
    """NOAA approximate solar elevation for local-standard-time timestamps (mid-hour if given)."""
    utc = index_lst - pd.Timedelta(hours=utc_offset_h)
    doy = utc.dayofyear.to_numpy()
    hour = (utc.hour + utc.minute / 60).to_numpy()
    gamma = 2 * np.pi / 365 * (doy - 1 + (hour - 12) / 24)
    eqtime = 229.18 * (0.000075 + 0.001868 * np.cos(gamma) - 0.032077 * np.sin(gamma)
                       - 0.014615 * np.cos(2 * gamma) - 0.040849 * np.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * np.cos(gamma) + 0.070257 * np.sin(gamma) - 0.006758 * np.cos(2 * gamma)
            + 0.000907 * np.sin(2 * gamma) - 0.002697 * np.cos(3 * gamma) + 0.00148 * np.sin(3 * gamma))
    true_solar_min = hour * 60 + eqtime + 4 * lon
    hour_angle = np.radians(true_solar_min / 4 - 180)
    phi = np.radians(lat)
    cos_zen = np.sin(phi) * np.sin(decl) + np.cos(phi) * np.cos(decl) * np.cos(hour_angle)
    return 90 - np.degrees(np.arccos(np.clip(cos_zen, -1, 1)))


def bootstrap_share(day_within, day_total, n_boot: int = N_BOOT, seed: int = SEED):
    """Pooled share sum(within)/sum(total) with a day-block percentile 95 % CI."""
    w, n = np.asarray(day_within, float), np.asarray(day_total, float)
    share = w.sum() / n.sum() if n.sum() else np.nan
    if len(n) == 0:
        return share, np.nan, np.nan
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(n), size=(n_boot, len(n)))
    with np.errstate(invalid="ignore", divide="ignore"):
        boots = w[idx].sum(1) / n[idx].sum(1)
    lo, hi = np.nanpercentile(boots, [2.5, 97.5])
    return float(share), float(lo), float(hi)


def bootstrap_share_difference(w_a, n_a, w_b, n_b, n_boot: int = N_BOOT, seed: int = SEED):
    """share_A - share_B; days (aligned rows) resampled jointly."""
    w_a, n_a, w_b, n_b = (np.asarray(v, float) for v in (w_a, n_a, w_b, n_b))
    diff = w_a.sum() / n_a.sum() - w_b.sum() / n_b.sum()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(n_a), size=(n_boot, len(n_a)))
    with np.errstate(invalid="ignore", divide="ignore"):
        boots = w_a[idx].sum(1) / n_a[idx].sum(1) - w_b[idx].sum(1) / n_b[idx].sum(1)
    lo, hi = np.nanpercentile(boots, [2.5, 97.5])
    return float(diff), float(lo), float(hi)


def gate_status(lower: float, n_days: int, target: float, min_days: int = MIN_DAYS) -> str:
    if n_days < min_days or not np.isfinite(lower):
        return "insufficient"
    return "pass" if lower >= target else "fail"


def prepare_output_dir(path: Path) -> Path:
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing output dir: {path}")
    path.mkdir(parents=True)
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------- strata
def build_strata(met: pd.DataFrame, hours: pd.DatetimeIndex, lat: float, lon: float) -> pd.DataFrame:
    strata = pd.DataFrame(index=hours)
    strata["season"] = season_of(hours)
    elevation = solar_elevation_deg(hours + pd.Timedelta(minutes=30), lat, lon)
    strata["daynight"] = np.where(elevation > 0, "day", "night")
    rain = met["TotPrcp"] if "TotPrcp" in met else pd.Series(dtype=float)
    for label, h, heavy in (("rain6h", 6, RAIN6_HEAVY_MM), ("rain24h", 24, RAIN24_HEAVY_MM)):
        total = prior_window_sum(rain, h).reindex(hours)
        strata[label] = np.select([total.isna(), total == 0, total < heavy], [None, "none", "light"], "heavy")
    wind = met["WSpd"].reindex(hours)
    q1, q2 = met["WSpd"].quantile([1 / 3, 2 / 3])
    strata["wind"] = np.select([wind.isna(), wind <= q1, wind <= q2], [None, "low", "mid"], "high")
    strata.attrs["wind_terciles_mps"] = (round(float(q1), 2), round(float(q2), 2))
    return strata


# ---------------------------------------------------------------- core loop
def _summary(frame: pd.DataFrame) -> dict:
    per_day = frame.groupby(frame.index.normalize())["within"].agg(["sum", "count"])
    share, lo, hi = bootstrap_share(per_day["sum"], per_day["count"])
    abs_err = frame["err"].abs()
    out = {
        "n_hours": int(len(frame)), "n_days": int(len(per_day)),
        "first": frame.index.min().strftime("%Y-%m-%d"), "last": frame.index.max().strftime("%Y-%m-%d"),
        "mae": round(float(abs_err.mean()), 4), "bias_target_minus_est": round(float(frame["err"].mean()), 4),
        "p95_abs_err": round(float(abs_err.quantile(0.95)), 4),
        "share_within": round(share, 4), "share_ci_lo": round(lo, 4), "share_ci_hi": round(hi, 4),
    }
    for g in GATES:
        out[f"gate_{int(g * 100)}"] = gate_status(lo, len(per_day), g)
    return out


EFFECTS = [  # (name, stratum column, A, B, scope)
    ("rain24h_heavy_vs_none", "rain24h", "heavy", "none", "all"),
    ("rain24h_heavy_vs_none", "rain24h", "heavy", "none", "wet_season"),
    ("rain6h_heavy_vs_none", "rain6h", "heavy", "none", "all"),
    ("wind_high_vs_low", "wind", "high", "low", "all"),
    ("night_vs_day", "daynight", "night", "day", "all"),
    ("wet_vs_dry_season", "season", "wet", "dry", "all"),
]


def _effect(frame: pd.DataFrame, column: str, a: str, b: str) -> dict | None:
    is_a, is_b = (frame[column] == a).to_numpy(), (frame[column] == b).to_numpy()
    within = frame["within"].to_numpy(bool)
    grid = pd.DataFrame({"w_a": within & is_a, "n_a": is_a, "w_b": within & is_b, "n_b": is_b},
                        index=frame.index).astype(int)
    agg = grid.groupby(frame.index.normalize()).sum()
    days_a, days_b = int((agg["n_a"] > 0).sum()), int((agg["n_b"] > 0).sum())
    if days_a < 10 or days_b < 10:
        return None
    diff, lo, hi = bootstrap_share_difference(agg["w_a"], agg["n_a"], agg["w_b"], agg["n_b"])
    mae_a = frame.loc[frame[column] == a, "err"].abs().mean()
    mae_b = frame.loc[frame[column] == b, "err"].abs().mean()
    return {"days_a": days_a, "days_b": days_b, "hours_a": int(agg["n_a"].sum()), "hours_b": int(agg["n_b"].sum()),
            "share_a": round(agg["w_a"].sum() / agg["n_a"].sum(), 4), "share_b": round(agg["w_b"].sum() / agg["n_b"].sum(), 4),
            "share_diff_a_minus_b": round(diff, 4), "diff_ci_lo": round(lo, 4), "diff_ci_hi": round(hi, 4),
            "mae_a": round(float(mae_a), 4), "mae_b": round(float(mae_b), 4),
            "mae_ratio_a_over_b": round(float(mae_a / mae_b), 3) if mae_b else np.nan}


def evaluate(wq: pd.DataFrame, strata: pd.DataFrame, pairs: pd.DataFrame):
    wide = {var: wq[wq["variable"] == var].pivot(index="time_lst", columns="station", values="value")
            for var in {spec[0] for spec in TOLERANCES.values()}}
    pair_rows, stratum_rows, effect_rows = [], [], []
    for pair in pairs.itertuples(index=False):
        for var_key, (column, absolute, relative, accuracy) in TOLERANCES.items():
            table = wide[column]
            if pair.anchor not in table or pair.target not in table:
                continue
            joint = table[[pair.anchor, pair.target]].dropna()
            x, y = joint[pair.anchor], joint[pair.target]
            for method, est in (("persistence_in_space", x), ("calibrated_30d", rolling_linear_transfer(x, y))):
                frame = pd.DataFrame({"est": est, "obs": y}).dropna()
                if frame.empty:
                    continue
                frame["err"] = frame["obs"] - frame["est"]
                frame["within"] = within_tolerance(var_key, frame["est"], frame["obs"])
                frame = frame.join(strata, how="left")
                base = {"anchor": pair.anchor, "target": pair.target, "distance_km": pair.distance_km,
                        "pair_type": pair.pair_type, "variable": var_key, "tolerance_abs": absolute,
                        "tolerance_rel": relative, "sensor_accuracy": accuracy, "method": method}
                pair_rows.append({**base, **_summary(frame)})
                for col in ("season", "daynight", "rain6h", "rain24h", "wind"):
                    for level, sub in frame.groupby(col):
                        if level is None or len(sub) == 0:
                            continue
                        stratum_rows.append({**base, "stratum_type": col, "stratum": level, **_summary(sub)})
                for name, col, a, b, scope in EFFECTS:
                    sub = frame[frame["season"] == "wet"] if scope == "wet_season" else frame
                    result = _effect(sub, col, a, b)
                    if result:
                        effect_rows.append({**base, "effect": name, "scope": scope, **result})
    return pd.DataFrame(pair_rows), pd.DataFrame(stratum_rows), pd.DataFrame(effect_rows)


def distance_trend(pair_summary: pd.DataFrame) -> pd.DataFrame:
    """Descriptive only: 6 unordered distances, confounded with habitat type."""
    rows = []
    for (var, method), grp in pair_summary.groupby(["variable", "method"]):
        und = grp.assign(key=grp.apply(lambda r: "-".join(sorted((r.anchor, r.target))), axis=1))
        und = und.groupby("key").agg(distance_km=("distance_km", "first"), pair_type=("pair_type", "first"),
                                     share=("share_within", "mean"), mae=("mae", "mean"))
        rho = und["distance_km"].rank().corr(und["share"].rank())
        rows.append({"variable": var, "method": method, "n_unordered_pairs": len(und),
                     "spearman_distance_vs_share": round(float(rho), 3) if np.isfinite(rho) else np.nan,
                     "mean_share_same_habitat": round(und.loc[und.pair_type == "same_habitat", "share"].mean(), 4),
                     "mean_share_cross_habitat": round(und.loc[und.pair_type == "cross_habitat", "share"].mean(), 4),
                     "mean_mae_same_habitat": round(und.loc[und.pair_type == "same_habitat", "mae"].mean(), 4),
                     "mean_mae_cross_habitat": round(und.loc[und.pair_type == "cross_habitat", "mae"].mean(), 4)})
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME)
    parser.add_argument("--data-dir", type=Path, default=nl.NERRS_DIR)
    args = parser.parse_args(argv)
    out = prepare_output_dir(args.output_dir)

    stations = nl.station_table(args.data_dir)
    pairs = nl.pairwise_distances(stations)
    wq, wq_flags = nl.load_wq_hourly(years=set(WQ_YEARS), data_dir=args.data_dir)
    met, met_flags = nl.load_met_hourly(years=set(range(2007, 2012)), data_dir=args.data_dir)
    nut = nl.load_nutrients(data_dir=args.data_dir)
    # Flag shares for all years (documents why pre-2007 drops out).
    _, all_wq_flags = nl.load_wq_hourly(data_dir=args.data_dir)

    bay = stations[stations.station.isin(nl.WQ_STATIONS)]
    hours = pd.date_range(f"{min(WQ_YEARS)}-01-01", f"{max(WQ_YEARS)}-12-31 23:00", freq="h")
    strata = build_strata(met, hours, bay["lat"].mean(), bay["lon"].mean())

    # Time-zone sanity: PAR should be ~0 at night if LST = UTC-4 holds.
    par = met["TotPAR"].reindex(hours)
    par_check = {dn: round(float(par[strata["daynight"] == dn].median()), 2) for dn in ("day", "night")}

    pair_summary, by_stratum, effects = evaluate(wq, strata, pairs)
    trend = distance_trend(pair_summary)

    flags = all_wq_flags.groupby(["station", "year", "variable", "flag"], as_index=False)["n"].sum()
    flags["share"] = (flags["n"] / flags.groupby(["station", "year", "variable"])["n"].transform("sum")).round(4)
    flags = pd.concat([flags, met_flags.groupby(["station", "year", "variable", "flag"], as_index=False)["n"].sum()])
    coverage = (wq.assign(year=wq.time_lst.dt.year).groupby(["station", "variable", "year"]).size()
                .rename("good_hours").reset_index())
    coverage["share_of_year_hours"] = (coverage["good_hours"] / coverage["year"].map(
        lambda y: 8784 if y % 4 == 0 else 8760)).round(3)
    nut_good = nut.dropna(subset=["NH4F"])  # good-flag NH4F only (pre-2007 grabs are <4>)
    nut_summary = (nut_good.assign(year=nut_good.time_lst.dt.year).groupby("station")
                   .agg(nh4f_good_samples=("NH4F", "count"), nh4f_median_mgl=("NH4F", "median"),
                        first_year=("year", "min"), last_year=("year", "max")).reset_index())

    stations.to_csv(out / "stations.csv", index=False)
    pair_summary.to_csv(out / "pairs.csv", index=False)
    by_stratum.to_csv(out / "reliability_by_stratum.csv", index=False)
    effects.to_csv(out / "weather_effects.csv", index=False)
    trend.to_csv(out / "distance_trend.csv", index=False)
    flags.to_csv(out / "flag_shares.csv", index=False)
    coverage.to_csv(out / "coverage.csv", index=False)
    nut_summary.to_csv(out / "nutrients_summary.csv", index=False)

    used = sorted({*args.data_dir.glob("job*wq*.csv"), *args.data_dir.glob("jobjbmet*.csv"),
                   *args.data_dir.glob("job*nut*.csv"),
                   args.data_dir / nl.WQ_COORD_PRIMARY, args.data_dir / nl.MET_COORD_DOC,
                   *args.data_dir.glob("jobwq01-12.*m.*")})
    manifest = {
        "run": RUN_NAME, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "experiments/nerrs_reliability.py", "source": "NOAA NCEI accession 0052765 (NERRS SWMP Jobos Bay)",
        "parameters": {"wq_years": list(WQ_YEARS), "met_years_with_data": list(MET_YEARS), "good_flag": 0,
                       "hourly_min_obs": 2, "tolerances": {k: {"abs": v[1], "rel": v[2], "sensor_accuracy": v[3]}
                                                           for k, v in TOLERANCES.items()},
                       "gates": GATES, "gate_rule": "day-block bootstrap lower 95% bound >= gate, n_days >= 30",
                       "min_days": MIN_DAYS, "n_boot": N_BOOT, "seed": SEED,
                       "rain6h_heavy_mm": RAIN6_HEAVY_MM, "rain24h_heavy_mm": RAIN24_HEAVY_MM,
                       "wind_terciles_mps": strata.attrs["wind_terciles_mps"],
                       "calibrated_window": "30D strictly past, min 240 joint hours",
                       "time_basis": "local standard time (AST, UTC-4, no DST)"},
        "checks": {"median_hourly_TotPAR_by_solar_daynight": par_check,
                   "stratum_hour_counts": {c: strata[c].value_counts(dropna=False).to_dict()
                                           for c in ("rain6h", "rain24h", "wind", "daynight", "season")}},
        "inputs": [{"file": str(p.relative_to(paths.PROJECT_ROOT)).replace("\\", "/") if p.is_relative_to(paths.PROJECT_ROOT) else str(p),
                    "bytes": p.stat().st_size, "sha256": sha256(p)} for p in used],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
