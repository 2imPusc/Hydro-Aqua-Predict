"""Direction-4 reliability on the Indian River Lagoon Observatory Network (IRLON) (H4.7).

Data: IRLON (Harbor Branch Oceanographic Institute at FAU) via the open SECOORA ERDDAP
mirror, 13 stations, hourly (``experiments/irlon_load.py``). Acknowledgement: "Indian
River Lagoon Observatory Network of Environmental Sensors (IRLON), Harbor Branch
Oceanographic Institute at Florida Atlantic University".

Question (as RL-12/14/20-23): can one in-situ sensor (anchor) stand in for another
location (target)? Reliability = share of hours (or days) with
|estimate - target observation| <= tolerance.

Protocol (shared with the other direction-4 datasets)
* Values with QARTOD aggregate flag 1 only (rain: flag 1-2, never evaluated) + range
  check. Data are hourly: a single reading per hour is accepted (deviation from the
  >= 2 obs/hour of the 15-min networks; same as Texas RL-22).
* Tolerances (``nerrs_reliability.TOLERANCES``): Temp 0.5 C, Sal 1 psu, DO 0.5 mg/L,
  pH 0.2, Turb max(2 NTU, 20 %). Exploratory nutrients (umol/L): NO3 max(2 umol/L, 30 %),
  PO4 max(0.1 umol/L, 30 %) -- 30 % relative as the HK NH3 row, with a floor at the
  sensor accuracy (SUNA nitrate ~2 umol/L; WET Labs Cycle-PO4 ~0.1 umol/L) because
  lagoon nitrate sits near 0.
* Pairs: every ordered station pair with >= 365 days of overlapping hourly data per
  variable; bins 0-2, 2-5, 5-10, 10-20, 20-30, >30 km (>30 km reported, not in radius).
* Local time: EST = UTC-5 fixed (no DST) for calendar days, season and day/night.
* Season / regime: season stratum wet = Jun-Oct (Florida rainy season). The salinity
  minimum lags the rains by ~2-3 months, so the regime uses the 5 lowest-salinity calendar
  months of the network (median over stations of station-month medians; per-cluster
  check in ``wet_season.csv``). Regime per station = median hourly salinity in those
  months; pair "same" if |delta| < 2 psu (``dsal``). Robustness columns: ``dsal_junoct``
  (Jun-Oct medians) and ``dsal_overlap`` (pair's common hours; stations cover different
  years, the northern three only from 2022).
* Transfers: ``raw`` (estimate = anchor) and ``calibrated_30d`` (a + b*anchor, OLS on the
  pair's hours in [t-30 d, t), >= 240 h; ``nerrs_reliability.rolling_linear_transfer``).
* Gates 80/90/95 %: day-block bootstrap (500, seed 20261016) lower 95 % bound >= gate and
  >= 30 days; cells pool pairs, resampling unit = calendar day (all pairs of that day).
* Strata: season; day/night (solar elevation at the target); rain at the TARGET.
  Primary rain = ERA5 hourly precipitation (Open-Meteo archive) at each target station:
  the station gauges (``lwe_precipitation_rate`` mm/h, QARTOD never run) have good hourly
  coverage in many station-years but annual totals far below ERA5 and weak daily
  correlation (``rain_gauge_check.csv``), i.e. under-catch/clogging, which would shift
  the mm thresholds. Gauge strata (own gauge in station-years with >= 80 % hours, gaps
  filled from the nearest qualifying gauge <= 30 km) are a sensitivity
  (``rain_effect_gauge.csv``, ``g_rain*`` in ``strata.csv``). Classes: prior 24 h >= 10 mm
  vs < 1 mm; prior 72 h >= 20 mm vs < 1 mm. Rain is observation-only, a stratifier.
* Daily scale (``daily_cells.csv``): a day counts for a pair x transfer when >= 18 of its
  24 LST hours have both estimate and observation; daily mean estimate vs daily mean
  observation on those hours, same tolerances. Each pair-day is one sample; the bootstrap
  resamples days (all pairs of that day together).
* No-transfer baseline (``baseline_compare.csv``): target's own calendar-month median from
  OTHER years (leave-one-year-out, >= 3 other years), hourly values for the hourly scale
  and >= 18 h daily means for the daily scale; compared on exactly the rows where both
  the transfer and the climatology exist.
* Radius: ``nerrs_multi_reliability.radius_table`` (``radius_km`` skips bins without
  evidence; ``radius_km_strict`` stops at the first bin that is not "pass").

Run:  .venv\\Scripts\\python experiments\\irlon_reliability.py
Outputs: artifacts/experiments/irlon-h4-reliability-20261017-r3/ (refuses to overwrite).
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
from experiments import irlon_load as il  # noqa: E402
from experiments import usgs_reliability as ur  # noqa: E402
from experiments.hk_epd_reliability import haversine_km  # noqa: E402
from experiments.nerrs_multi_reliability import (  # noqa: E402
    load_or_fetch_era5_daily,
    radius_table,
    rain_gauge_check,
    wet_months,
)
from experiments.nerrs_reliability import (  # noqa: E402
    TOLERANCES,
    bootstrap_share,
    bootstrap_share_difference,
    gate_status,
    prepare_output_dir,
    prior_window_sum,
    rolling_linear_transfer,
    sha256,
    solar_elevation_deg,
)

# first attempt (same code minus the memory fix) aborted with MemoryError and left a partial
# irlon-h4-reliability-20261017/ and -r2/ without manifest (MemoryError); write-once rule -> -r3.
# Outputs are now written only after all tables are computed.
RUN_NAME = "irlon-h4-reliability-20261017-r3"
DATASET = "irlon"
GATES = (0.80, 0.90, 0.95)
N_BOOT, SEED, MIN_DAYS = 500, 20261016, 30
MIN_OVERLAP_DAYS = 365
LST_OFFSET_H = -5
WET_MONTHS = (6, 7, 8, 9, 10)
REGIME_DSAL_PSU = 2.0
CAL_WINDOW, CAL_MIN_HOURS = "30D", 240
DAILY_MIN_HOURS = 18
CLIM_MIN_OTHER_YEARS = 3
RAIN24_HEAVY_MM, RAIN72_HEAVY_MM, RAIN_NONE_MM = 10.0, 20.0, 1.0
RAIN_MIN_YEAR_COVERAGE = 0.80
ERA5_START, ERA5_END = "2014-05-01", "2026-10-10"
REGIME_MONTHS_N = 5
RAIN_FILL_MAX_KM = 30.0
CORE_VARS = {"Temp": "Temp", "Sal": "Sal", "DO": "DO_mgl", "pH": "pH", "Turb": "Turb"}
# exploratory nutrients: (absolute floor umol/L, relative)
NUTRIENT_TOL = {"NO3": (2.0, 0.30), "PO4": (0.1, 0.30)}
ALL_VARS = (*CORE_VARS, *NUTRIENT_TOL)
TRANSFERS = ("raw", "calibrated_30d")
CELL_COLS = ["dataset", "var", "regime", "distance_bin", "transfer", "n_days", "share", "ci_low", "gate80",
             "gate90", "gate95", "n_pairs", "n_hours", "ci_high", "mae"]


# ---------------------------------------------------------------- primitives
def to_lst(index_utc) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(index_utc) + pd.Timedelta(hours=LST_OFFSET_H)


def season_of(index_lst, wet=WET_MONTHS) -> np.ndarray:
    return np.where(pd.DatetimeIndex(index_lst).month.isin(list(wet)), "wet", "dry")


def within(var: str, estimate, observed) -> np.ndarray:
    """Tolerance test; core variables via nerrs TOLERANCES, nutrients max(floor, 30 %)."""
    if var in NUTRIENT_TOL:
        absolute, relative = NUTRIENT_TOL[var]
    else:
        _, absolute, relative, _ = TOLERANCES[CORE_VARS[var]]
    observed = np.asarray(observed, dtype=float)
    bound = np.maximum(absolute, relative * np.abs(observed))
    return np.abs(observed - np.asarray(estimate, dtype=float)) <= bound + 1e-9


def overlap_days(a: pd.Series, b: pd.Series) -> int:
    joint = pd.concat([a, b], axis=1).dropna()
    return int(to_lst(joint.index).normalize().nunique())


def cluster_wet_months(sal_wide: pd.DataFrame, stations: pd.DataFrame, n: int = len(WET_MONTHS)) -> pd.DataFrame:
    """Lowest-salinity months per cluster (median over stations of station-month medians)."""
    month = to_lst(sal_wide.index).month
    per_station = sal_wide.groupby(month).median()  # month x station
    cl = stations.set_index("site")["cluster"]
    rows = []
    groups = {"all": list(per_station.columns)}
    for c in sorted(cl.unique()):
        groups[c] = [s for s in per_station.columns if cl.get(s) == c]
    for name, sites in groups.items():
        if not sites:
            continue
        monthly = per_station[sites].median(axis=1)
        rec = {"cluster": name, "n_stations": len(sites),
               "lowest_sal_months": ",".join(str(m) for m in wet_months(monthly, n))}
        rec.update({f"m{m:02d}": round(float(monthly.get(m, np.nan)), 2) for m in range(1, 13)})
        rows.append(rec)
    return pd.DataFrame(rows)


def regime_medians(sal_wide: pd.DataFrame, months=WET_MONTHS) -> pd.DataFrame:
    """Per station median hourly salinity inside ``months`` (low-salinity season) and outside."""
    inside = pd.DatetimeIndex(to_lst(sal_wide.index)).month.isin(list(months))
    rows = {}
    for site in sal_wide:
        s = sal_wide[site]
        rows[site] = {"sal_wet_median": s[inside].median(), "sal_dry_median": s[~inside].median(),
                      "sal_wet_hours": int(s[inside].notna().sum()), "sal_dry_hours": int(s[~inside].notna().sum())}
    return pd.DataFrame.from_dict(rows, orient="index")


def pair_table(stations: pd.DataFrame, wide: dict[str, pd.DataFrame], regime_months=WET_MONTHS) -> pd.DataFrame:
    """All ordered pairs: distance, regime (|delta median salinity in ``regime_months``| < 2 psu; ``dsal``),
    robustness columns ``dsal_overlap`` (pair's common hours) and ``dsal_junoct`` (Jun-Oct months)."""
    med = regime_medians(wide["Sal"], regime_months) if "Sal" in wide else pd.DataFrame()
    med_jo = regime_medians(wide["Sal"], WET_MONTHS) if "Sal" in wide else pd.DataFrame()
    s = stations.set_index("site")
    rows = []
    for a in s.index:
        for t in s.index:
            if a == t:
                continue
            km = float(haversine_km(s.at[a, "lat"], s.at[a, "lon"], s.at[t, "lat"], s.at[t, "lon"]))
            both = a in med.index and t in med.index
            dsal = abs(med.at[a, "sal_wet_median"] - med.at[t, "sal_wet_median"]) if both else np.nan
            dsal_jo = abs(med_jo.at[a, "sal_wet_median"] - med_jo.at[t, "sal_wet_median"]) if both else np.nan
            rec = {"anchor": a, "target": t, "anchor_cluster": s.at[a, "cluster"], "target_cluster": s.at[t, "cluster"],
                   "km": round(km, 3), "distance_bin": ur.distance_bin([km])[0], "dsal": round(float(dsal), 3),
                   "regime": ur.regime_label([dsal])[0], "dsal_overlap": np.nan,
                   "dsal_junoct": round(float(dsal_jo), 3), "regime_junoct": ur.regime_label([dsal_jo])[0]}
            if "Sal" in wide and a in wide["Sal"] and t in wide["Sal"]:
                joint = wide["Sal"][[a, t]].dropna()
                wet = joint[pd.DatetimeIndex(to_lst(joint.index)).month.isin(list(regime_months))]
                if len(wet):
                    rec["dsal_overlap"] = round(float(abs(wet[a].median() - wet[t].median())), 3)
            for var, table in wide.items():
                rec[f"n_days_{var}"] = overlap_days(table[a], table[t]) if a in table and t in table else 0
            rows.append(rec)
    out = pd.DataFrame(rows)
    out["regime_overlap"] = ur.regime_label(out["dsal_overlap"])
    return out


def climatology_loyo(series: pd.Series, min_other_years: int = CLIM_MIN_OTHER_YEARS) -> pd.Series:
    """Same-calendar-month median over OTHER years (leave-one-year-out); index is LST-like."""
    s = series.dropna()
    out = pd.Series(np.nan, index=s.index)
    if s.empty:
        return out
    idx = pd.DatetimeIndex(s.index)
    years, months = idx.year.to_numpy(), idx.month.to_numpy()
    values = s.to_numpy(float)
    for m in np.unique(months):
        in_m = months == m
        yrs = np.unique(years[in_m])
        for y in yrs:
            others = in_m & (years != y)
            if len(np.unique(years[others])) >= min_other_years:
                out.iloc[np.flatnonzero(in_m & (years == y))] = np.median(values[others])
    return out


def daily_means(hourly_wide: pd.DataFrame, min_hours: int = DAILY_MIN_HOURS) -> pd.DataFrame:
    """LST-day means per station with >= min_hours hourly values (index = LST date)."""
    day = to_lst(hourly_wide.index).normalize()
    grouped = hourly_wide.groupby(day)
    return grouped.mean().where(grouped.count() >= min_hours)


def transfer_frame(anchor: pd.Series, target: pd.Series, var: str, clim: pd.Series | None = None) -> pd.DataFrame:
    """Hourly rows (transfer, est, obs, within, clim, within_clim) on the pair's common hours."""
    joint = pd.concat([anchor.rename("x"), target.rename("y")], axis=1).dropna().sort_index()
    frames = []
    for name in TRANSFERS:
        est = joint["x"] if name == "raw" else rolling_linear_transfer(joint["x"], joint["y"], CAL_WINDOW, CAL_MIN_HOURS)
        f = pd.DataFrame({"est": est, "obs": joint["y"]}).dropna()
        f["within"] = within(var, f["est"].to_numpy(), f["obs"].to_numpy())
        f["clim"] = clim.reindex(f.index).to_numpy() if clim is not None else np.nan
        f["within_clim"] = within(var, f["clim"].to_numpy(), f["obs"].to_numpy()) & f["clim"].notna().to_numpy()
        f["transfer"] = name
        frames.append(f)
    return pd.concat(frames)


def daily_frame(hourly: pd.DataFrame, var: str, clim_daily: pd.Series | None = None,
                min_hours: int = DAILY_MIN_HOURS) -> pd.DataFrame:
    """Daily-mean rows per transfer from a ``transfer_frame`` (>= min_hours common hours per LST day)."""
    h = hourly.copy()
    h["date"] = to_lst(h.index).normalize()
    agg = h.groupby(["transfer", "date"]).agg(est=("est", "mean"), obs=("obs", "mean"), hours=("obs", "size"))
    agg = agg[agg["hours"] >= min_hours].reset_index()
    agg["within"] = within(var, agg["est"].to_numpy(), agg["obs"].to_numpy())
    clim = clim_daily.reindex(agg["date"]).to_numpy() if clim_daily is not None else np.full(len(agg), np.nan)
    agg["clim"] = clim
    agg["within_clim"] = within(var, agg["clim"].to_numpy(), agg["obs"].to_numpy()) & agg["clim"].notna().to_numpy()
    return agg


def counts_from(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Per-key sums: w/n (all rows), wt/nc (transfer within / count on rows with climatology), wc (clim within)."""
    f = frame.copy()
    f["err_abs"] = (f["obs"] - f["est"]).abs()
    has_clim = f["clim"].notna()
    f["wt"] = f["within"] & has_clim
    f["nc"] = has_clim.astype(int)
    f["wc"] = f["within_clim"]
    return f.groupby(keys, observed=True).agg(w=("within", "sum"), n=("within", "size"), abs_err=("err_abs", "sum"),
                                              wt=("wt", "sum"), nc=("nc", "sum"), wc=("wc", "sum")).reset_index()


def build_strata(hours_utc: pd.DatetimeIndex, lat: float, lon: float, rain: pd.Series | None,
                 gauge: pd.Series | None = None) -> pd.DataFrame:
    """season, day/night, rain classes from ``rain`` (rain24h/rain72h) and from ``gauge`` (g_rain24h/g_rain72h)."""
    lst = to_lst(hours_utc)
    strata = pd.DataFrame(index=hours_utc)
    strata["date"] = lst.normalize()
    strata["season"] = season_of(lst)
    elev = solar_elevation_deg(lst + pd.Timedelta(minutes=30), lat, lon, utc_offset_h=LST_OFFSET_H)
    strata["daynight"] = np.where(elev > 0, "day", "night")
    for label, hours, heavy, series in (("rain24h", 24, RAIN24_HEAVY_MM, rain), ("rain72h", 72, RAIN72_HEAVY_MM, rain),
                                        ("g_rain24h", 24, RAIN24_HEAVY_MM, gauge),
                                        ("g_rain72h", 72, RAIN72_HEAVY_MM, gauge)):
        if series is None or series.dropna().empty:
            strata[label] = "na"
            continue
        total = prior_window_sum(series, hours).reindex(hours_utc)
        strata[label] = np.select([total.isna(), total < RAIN_NONE_MM, total >= heavy], ["na", "none", "heavy"], "mid")
    return strata


def load_or_fetch_era5_hourly(lat: float, lon: float, start: str = ERA5_START, end: str = ERA5_END,
                              cache_dir: Path = il.DERIVED_DIR, allow_fetch: bool = True) -> tuple[pd.Series | None, dict]:
    """Open-Meteo ERA5 hourly precipitation (UTC) at a point; cached write-once."""
    path = Path(cache_dir) / f"open_meteo_era5_precip_hourly_utc_{lat:.3f}_{lon:.3f}_{start}_{end}.csv"
    url = ("https://archive-api.open-meteo.com/v1/archive?"
           f"latitude={lat:.3f}&longitude={lon:.3f}&start_date={start}&end_date={end}"
           "&hourly=precipitation&models=era5&timezone=GMT")
    meta = {"file": path.name, "url": url}
    if not path.exists():
        if not allow_fetch:
            return None, {**meta, "status": "absent_no_fetch"}
        try:
            req = urllib.request.Request(url, headers={"User-Agent": il.USER_AGENT})
            with urllib.request.urlopen(req, timeout=300) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # network failure must not block the deliverable
            return None, {**meta, "status": f"fetch_failed: {exc!r}"}
        frame = pd.DataFrame({"time_utc": payload["hourly"]["time"], "precip_mm": payload["hourly"]["precipitation"]})
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "x", encoding="utf-8", newline="") as handle:  # write-once
            frame.to_csv(handle, index=False)
        time.sleep(1.0)
    frame = pd.read_csv(path, parse_dates=["time_utc"])
    rain = frame.set_index("time_utc")["precip_mm"].astype(float)
    return rain, {**meta, "status": "ok", "sha256": sha256(path), "n_hours": int(rain.notna().sum())}


def rain_coverage(rain_wide: pd.DataFrame) -> pd.DataFrame:
    """Share of hours with an accepted rain value per station x calendar year (UTC)."""
    full = rain_wide.reindex(pd.date_range(rain_wide.index.min().floor("D"), rain_wide.index.max(), freq="h"))
    yr = full.index.year
    present = full.notna().groupby(yr).sum()
    hours = full.groupby(yr).size()
    cov = present.div(hours, axis=0)
    out = cov.stack().rename("coverage").reset_index()
    out.columns = ["year", "site", "coverage"]
    out["hours_present"] = present.stack().to_numpy()
    tot = full.groupby(yr).sum(min_count=1).stack().rename("total_mm").reset_index()
    tot.columns = ["year", "site", "total_mm"]
    return out.merge(tot, on=["year", "site"], how="left")


def station_rain(rain_wide: pd.DataFrame, stations: pd.DataFrame, coverage: pd.DataFrame,
                 min_cov: float = RAIN_MIN_YEAR_COVERAGE, max_km: float = RAIN_FILL_MAX_KM) -> dict[str, pd.Series]:
    """Per target: own gauge in station-years with coverage >= min_cov; gaps filled hour by hour from the
    nearest gauge (<= max_km) whose station-year also passes."""
    if rain_wide.empty:
        return {}
    full = rain_wide.reindex(pd.date_range(rain_wide.index.min().floor("D"), rain_wide.index.max(), freq="h"))
    ok = coverage[coverage["coverage"] >= min_cov]
    good = pd.DataFrame(False, index=full.index, columns=full.columns)
    for r in ok.itertuples():
        if r.site in good:
            good.loc[full.index.year == r.year, r.site] = True
    usable = full.where(good)
    s = stations.set_index("site")
    out = {}
    for t in s.index:
        series = usable[t].copy() if t in usable else pd.Series(np.nan, index=full.index)
        others = sorted(((float(haversine_km(s.at[t, "lat"], s.at[t, "lon"], s.at[o, "lat"], s.at[o, "lon"])), o)
                         for o in usable.columns if o != t and o in s.index))
        for km, o in others:
            if km > max_km:
                break
            series = series.fillna(usable[o])
        out[t] = series
    return out


def baseline_compare(counts: pd.DataFrame, scale: str) -> pd.DataFrame:
    """Transfer vs leave-one-year-out climatology on common rows, by var x regime x bin (+ bin 'all')."""
    rows = []
    c = counts[counts["nc"] > 0]
    for bin_scope in ("by_bin", "all"):
        g0 = c[["var", "regime", "distance_bin", "transfer", "date", "pair", "km", "wt", "nc", "wc"]]
        if bin_scope == "all":
            g0 = g0[g0["km"] <= 30].assign(distance_bin="all_le30")
        for (var, regime, dbin, transfer), grp in g0.groupby(["var", "regime", "distance_bin", "transfer"],
                                                             observed=True):
            per_day = grp.groupby("date")[["wt", "nc", "wc"]].sum()
            per_pair = grp.groupby("pair", observed=True)[["wt", "nc", "wc"]].sum()
            per_pair = per_pair[per_pair["nc"] > 0]
            share_t = per_day["wt"].sum() / per_day["nc"].sum()
            share_c = per_day["wc"].sum() / per_day["nc"].sum()
            diff, lo, hi = bootstrap_share_difference(per_day["wt"], per_day["nc"], per_day["wc"], per_day["nc"],
                                                      N_BOOT, SEED)
            beats = (per_pair["wt"] / per_pair["nc"]) > (per_pair["wc"] / per_pair["nc"])
            rows.append({"dataset": DATASET, "scale": scale, "var": var, "regime": regime, "distance_bin": dbin,
                         "transfer": transfer, "n_pairs": int(len(per_pair)), "n_days": int(len(per_day)),
                         "n_rows": int(per_day["nc"].sum()), "share_transfer": round(float(share_t), 4),
                         "share_climatology": round(float(share_c), 4),
                         "diff_transfer_minus_clim": round(diff, 4), "ci_low": round(lo, 4), "ci_high": round(hi, 4),
                         "pairs_transfer_beats_clim": int(beats.sum()),
                         "transfer_better": bool(lo > 0), "climatology_better": bool(hi < 0)})
    return pd.DataFrame(rows)


def climatology_cells(wide: dict[str, pd.DataFrame], clim_h: dict, daily_wide: dict, clim_d: dict) -> pd.DataFrame:
    """Climatology alone vs each station's own record (station level, all rows with a climatology)."""
    rows = []
    for scale, values, clim in (("hourly", wide, clim_h), ("daily", daily_wide, clim_d)):
        for var, table in values.items():
            for site in table:
                obs = table[site].dropna()
                est = clim[var][site].reindex(obs.index)
                ok = est.notna()
                if not ok.any():
                    continue
                f = pd.DataFrame({"w": within(var, est[ok].to_numpy(), obs[ok].to_numpy()).astype(int), "n": 1},
                                 index=obs.index[ok])
                day = to_lst(f.index).normalize() if scale == "hourly" else f.index
                per_day = f.groupby(day)[["w", "n"]].sum()
                share, lo, hi = bootstrap_share(per_day["w"], per_day["n"], N_BOOT, SEED)
                rec = {"dataset": DATASET, "scale": scale, "var": var, "site": site, "n_days": int(len(per_day)),
                       "n_rows": int(per_day["n"].sum()), "share": round(share, 4), "ci_low": round(lo, 4),
                       "ci_high": round(hi, 4), "exploratory": var in NUTRIENT_TOL}
                for g in GATES:
                    rec[f"gate{int(g * 100)}"] = gate_status(lo, len(per_day), g, MIN_DAYS)
                rows.append(rec)
    return pd.DataFrame(rows)


def pair_record(p, var: str, transfer: str, sub: pd.DataFrame, scale: str) -> dict:
    per_day = sub.groupby("date")[["w", "n"]].sum()
    share, lo, hi = bootstrap_share(per_day["w"], per_day["n"], N_BOOT, SEED)
    nc = sub["nc"].sum()
    return {"dataset": DATASET, "scale": scale, "anchor": p.anchor, "target": p.target, "var": var,
            "transfer": transfer, "km": p.km, "distance_bin": p.distance_bin, "regime": p.regime, "dsal": p.dsal,
            "dsal_overlap": p.dsal_overlap, "regime_overlap": p.regime_overlap,
            "anchor_cluster": p.anchor_cluster, "target_cluster": p.target_cluster,
            "n_days": int(len(per_day)), "n_rows": int(per_day["n"].sum()), "share": round(share, 4),
            "ci_low": round(lo, 4), "mae": round(float(sub["abs_err"].sum() / sub["n"].sum()), 4),
            "share_clim_rows": round(float(sub["wt"].sum() / nc), 4) if nc else np.nan,
            "share_climatology": round(float(sub["wc"].sum() / nc), 4) if nc else np.nan,
            **{f"gate{int(g * 100)}": gate_status(lo, len(per_day), g, MIN_DAYS) for g in GATES}}


def cell_table(counts: pd.DataFrame) -> pd.DataFrame:
    cells = ur.summarise(counts, ["var", "regime", "distance_bin", "transfer"])
    cells.insert(0, "dataset", DATASET)
    return cells[CELL_COLS]


def radius_with_stop(cells: pd.DataFrame) -> pd.DataFrame:
    """radius_table restricted to bins <= 30 km (its walk ignores '>30')."""
    return radius_table(cells[cells["distance_bin"] != ">30"])


def quantisation_check(hourly: pd.DataFrame) -> pd.DataFrame:
    """Per site x var x year: share of hours equal to the previous hour's value (Texas-style check)."""
    h = hourly.sort_values(["site", "var", "hour_utc"]).copy()
    h["year"] = h["hour_utc"].dt.year
    prev = h.groupby(["site", "var"])["value"].shift()
    gap = h.groupby(["site", "var"])["hour_utc"].diff() == pd.Timedelta(hours=1)
    h["repeat"] = (h["value"] == prev) & gap
    h["consec"] = gap
    out = h.groupby(["site", "var", "year"]).agg(n_hours=("value", "size"), repeats=("repeat", "sum"),
                                                 consecutive=("consec", "sum")).reset_index()
    out["repeat_share"] = (out["repeats"] / out["consecutive"].where(out["consecutive"] > 0)).round(4)
    return out


def category_dtypes(pairs: pd.DataFrame, wide: dict) -> dict[str, pd.CategoricalDtype]:
    """Fixed categories so per-pair count frames concatenate as compact categoricals."""
    cat = pd.CategoricalDtype
    sites = sorted(set(pairs["anchor"]) | set(pairs["target"]))
    return {"pair": cat(sorted(f"{a}>{t}" for a, t in zip(pairs["anchor"], pairs["target"]))),
            "anchor": cat(sites), "target": cat(sites), "var": cat(list(wide)),
            "distance_bin": cat(list(ur.BIN_LABELS)), "regime": cat(["same", "different", "unknown"]),
            "transfer": cat(list(TRANSFERS)), "season": cat(["wet", "dry"]), "daynight": cat(["day", "night"]),
            **{c: cat(["na", "none", "mid", "heavy"]) for c in ("rain24h", "rain72h", "g_rain24h", "g_rain72h")}}


def compact(frame: pd.DataFrame, dtypes: dict) -> pd.DataFrame:
    for col, dt in dtypes.items():
        if col in frame:
            frame[col] = frame[col].astype(dt)
    return frame


def decategorise(frame: pd.DataFrame) -> pd.DataFrame:
    """Plain strings for the summary steps that group without observed=True."""
    out = frame.copy()
    for col in out.select_dtypes("category"):
        out[col] = out[col].astype(str)
    return out


def rain_input(counts: pd.DataFrame, col24: str, col72: str) -> pd.DataFrame:
    """Collapse pairs/day-night before ``usgs_reliability.rain_effect`` (sums per day are unchanged)."""
    keys = ["var", "transfer", "regime", "season", col24, col72, "date"]
    agg = counts.groupby(keys, observed=True)[["w", "n"]].sum().reset_index()
    return decategorise(agg).rename(columns={col24: "rain24h", col72: "rain72h"})


def git_commit() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "experiments/irlon_load.py",
                                "experiments/irlon_reliability.py"], cwd=ROOT, capture_output=True, text=True).stdout
        return sha + ("+uncommitted-irlon-scripts" if dirty.strip() else "")
    except OSError:
        return "unknown"


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output-dir", type=Path, default=paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME)
    ap.add_argument("--raw-dir", type=Path, default=il.RAW_DIR)
    ap.add_argument("--no-fetch", action="store_true", help="do not fetch ERA5 (rain strata become 'na')")
    args = ap.parse_args(argv)
    tables: dict[str, pd.DataFrame] = {}  # written only at the end (no partial run dirs on failure)

    stations = il.station_table()
    hourly, report = il.build_hourly(args.raw_dir)
    hourly = hourly[hourly["var"].isin([*ALL_VARS, "Rain"])].reset_index(drop=True)
    wide = {var: hourly[hourly["var"] == var].pivot(index="hour_utc", columns="site", values="value")
            for var in (*ALL_VARS, "Rain") if (hourly["var"] == var).any()}
    rain_wide = wide.pop("Rain", pd.DataFrame())

    # --- coverage, QC, season verification
    tables["qc_counts.csv"] = report["qc_counts"]
    cov = hourly.assign(year=hourly["hour_utc"].dt.year).groupby(["site", "var", "year"])["hour_utc"].agg(
        n_hours="size", first="min", last="max").reset_index()
    tables["coverage.csv"] = cov
    tables["quantisation_check.csv"] = quantisation_check(hourly[hourly["var"].isin(ALL_VARS)])
    wet_tab = cluster_wet_months(wide["Sal"], stations, n=REGIME_MONTHS_N)
    tables["wet_season.csv"] = wet_tab
    regime_months = tuple(int(m) for m in wet_tab.set_index("cluster").at["all", "lowest_sal_months"].split(","))

    # --- rain
    rcov = rain_coverage(rain_wide) if not rain_wide.empty else pd.DataFrame(columns=["year", "site", "coverage"])
    tables["rain_coverage.csv"] = rcov
    gauge_by_target = station_rain(rain_wide, stations, rcov)
    era5_by_target, era5_hourly_meta = {}, {}
    for r in stations.itertuples():
        series, meta = load_or_fetch_era5_hourly(round(r.lat, 3), round(r.lon, 3), allow_fetch=not args.no_fetch)
        era5_by_target[r.site], era5_hourly_meta[r.site] = series, meta
    era5_rows, era5_meta = [], {}
    centroid = (round(stations["lat"].median(), 3), round(stations["lon"].median(), 3))
    era5, era5_meta = load_or_fetch_era5_daily(centroid[0], centroid[1], "2014-05-01", "2026-09-30",
                                               cache_dir=il.DERIVED_DIR, allow_fetch=not args.no_fetch)
    if era5 is not None:
        for site in rain_wide.columns:
            lst_series = rain_wide[site].copy()
            lst_series.index = to_lst(lst_series.index)
            chk = rain_gauge_check(lst_series, LST_OFFSET_H, era5)
            era5_rows.append(chk.assign(site=site))
    gauge_chk = pd.concat(era5_rows, ignore_index=True) if era5_rows else pd.DataFrame()
    tables["rain_gauge_check.csv"] = gauge_chk

    # --- stations / pairs
    pairs = pair_table(stations, wide, regime_months)
    med = regime_medians(wide["Sal"], regime_months)
    tables["stations.csv"] = stations.merge(med, left_on="site", right_index=True, how="left")
    n_day_cols = [f"n_days_{v}" for v in wide]
    tables["pairs.csv"] = pairs[["anchor", "target", "anchor_cluster", "target_cluster", "km", "distance_bin", "regime",
                                 "dsal", "dsal_overlap", "regime_overlap", "dsal_junoct", "regime_junoct", *n_day_cols]]

    # --- climatology per station (hourly values indexed UTC; daily means indexed LST date)
    clim_h, clim_d, daily_wide = {}, {}, {}
    for var, table in wide.items():
        lst_table = table.copy()
        lst_table.index = to_lst(lst_table.index)
        clim_h[var] = {s: pd.Series(climatology_loyo(lst_table[s]).to_numpy(), index=table[s].dropna().index)
                       for s in table}
        daily_wide[var] = daily_means(table)
        clim_d[var] = {s: climatology_loyo(daily_wide[var][s]) for s in table}

    all_hours = pd.DatetimeIndex(sorted(hourly["hour_utc"].unique()))
    del hourly  # free the long table before the pair loop
    st = stations.set_index("site")
    strata = {t: build_strata(all_hours, st.at[t, "lat"], st.at[t, "lon"], era5_by_target.get(t),
                              gauge_by_target.get(t)) for t in st.index}

    keys_h = ["transfer", "date", "season", "daynight", "rain24h", "rain72h", "g_rain24h", "g_rain72h"]
    dtypes = category_dtypes(pairs, wide)
    sums = ["w", "n", "abs_err", "wt", "nc", "wc"]
    day_h, counts_d, pair_rows = [], [], []
    strata_parts = {c: [] for c in ("season", "daynight", "rain24h", "rain72h", "g_rain24h", "g_rain72h")}
    rain_parts = {"era5": [], "gauge": []}
    for p in pairs.itertuples(index=False):
        for var, table in wide.items():
            if getattr(p, f"n_days_{var}") < MIN_OVERLAP_DAYS:
                continue
            frame = transfer_frame(table[p.anchor], table[p.target], var, clim_h[var][p.target])
            tags = dict(pair=f"{p.anchor}>{p.target}", var=var, km=p.km, distance_bin=p.distance_bin, regime=p.regime)
            ch = counts_from(frame.join(strata[p.target], how="left"), keys_h)
            # collapse the hourly strata right away (all summaries are sums over pairs per date)
            dh = ch.groupby(["transfer", "date"], observed=True)[sums].sum().reset_index().assign(**tags)
            day_h.append(compact(dh, dtypes))
            for col in strata_parts:
                part = ch[ch[col] != "na"].groupby(["transfer", "date", col], observed=True)[["w", "n", "abs_err"]].sum()
                strata_parts[col].append(compact(part.reset_index().assign(var=var, regime=p.regime), dtypes))
            for name, (c24, c72) in (("era5", ("rain24h", "rain72h")), ("gauge", ("g_rain24h", "g_rain72h"))):
                part = ch.groupby(["transfer", "date", "season", c24, c72], observed=True)[["w", "n"]].sum()
                rain_parts[name].append(compact(part.reset_index().assign(var=var, regime=p.regime), dtypes))
            dframe = daily_frame(frame, var, clim_d[var][p.target])
            dframe["season"] = season_of(dframe["date"])
            cd = counts_from(dframe, ["transfer", "date", "season"]).assign(**tags)
            counts_d.append(compact(cd, dtypes))
            for transfer in TRANSFERS:
                sub_h, sub_d = dh[dh["transfer"] == transfer], cd[cd["transfer"] == transfer]
                if len(sub_h):
                    pair_rows.append(pair_record(p, var, transfer, sub_h, "hourly"))
                if len(sub_d):
                    pair_rows.append(pair_record(p, var, transfer, sub_d, "daily"))
            del frame, ch
    counts_h = pd.concat(day_h, ignore_index=True)
    counts_d = pd.concat(counts_d, ignore_index=True)
    pair_rel = pd.DataFrame(pair_rows)
    is_nut_p = pair_rel["var"].isin(list(NUTRIENT_TOL))
    tables["pair_reliability.csv"] = pair_rel[~is_nut_p]
    tables["nutrient_pair_reliability.csv"] = pair_rel[is_nut_p]

    core = list(CORE_VARS)
    core_h = counts_h[counts_h["var"].isin(core)]
    core_d = counts_d[counts_d["var"].isin(core)]
    nut_h = counts_h[counts_h["var"].isin(list(NUTRIENT_TOL))]
    nut_d = counts_d[counts_d["var"].isin(list(NUTRIENT_TOL))]

    cells = cell_table(core_h)
    cells_all = cell_table(core_h.assign(regime="all"))
    tables["cells.csv"], tables["cells_all_regimes.csv"] = cells, cells_all
    tables["radius.csv"] = radius_with_stop(pd.concat([cells, cells_all]))
    dcells = cell_table(core_d)
    dcells_all = cell_table(core_d.assign(regime="all"))
    tables["daily_cells.csv"], tables["daily_cells_all_regimes.csv"] = dcells, dcells_all
    tables["daily_radius.csv"] = radius_with_stop(pd.concat([dcells, dcells_all]))

    # exploratory nutrients
    if not nut_h.empty:
        ncells = pd.concat([cell_table(nut_h).assign(scale="hourly"), cell_table(nut_d).assign(scale="daily"),
                            cell_table(nut_h.assign(regime="all")).assign(scale="hourly"),
                            cell_table(nut_d.assign(regime="all")).assign(scale="daily")], ignore_index=True)
        tables["nutrient_cells.csv"] = ncells
        tables["nutrient_radius.csv"] = pd.concat([radius_with_stop(ncells[ncells["scale"] == s]).assign(scale=s)
                                                   for s in ("hourly", "daily")])

    # strata (pairs pooled per date; n_pairs not tracked here)
    strata_rows = []
    for col, parts in strata_parts.items():
        sel = pd.concat(parts, ignore_index=True)
        sel = sel[sel["var"].isin(core)]
        if sel.empty:
            continue
        sel = sel.groupby(["var", "regime", "transfer", col, "date"], observed=True)[["w", "n", "abs_err"]].sum()
        s = ur.summarise(sel.reset_index(), ["var", "regime", "transfer", col]).rename(columns={col: "level"})
        strata_rows.append(s.assign(stratum=col))
    strata_cells = pd.concat(strata_rows, ignore_index=True)
    strata_cells.insert(0, "dataset", DATASET)
    tables["strata.csv"] = strata_cells

    rvd = pd.concat([ur.regime_vs_distance(pair_rel[(pair_rel["scale"] == s) & ~is_nut_p]).assign(scale=s)
                     for s in ("hourly", "daily")], ignore_index=True)
    rvd["dataset"] = DATASET
    tables["regime_vs_distance.csv"] = rvd
    for name, fname, (c24, c72) in (("era5", "rain_effect.csv", ("rain24h", "rain72h")),
                                    ("gauge", "rain_effect_gauge.csv", ("g_rain24h", "g_rain72h"))):
        parts = pd.concat(rain_parts[name], ignore_index=True)
        eff = ur.rain_effect(rain_input(parts[parts["var"].isin(core)], c24, c72))
        if not eff.empty:
            eff["dataset"] = DATASET
            eff.insert(1, "rain_source", "era5_hourly_target" if name == "era5" else "station_gauge")
        tables[fname] = eff

    base = pd.concat([baseline_compare(counts_h, "hourly"), baseline_compare(counts_d, "daily")], ignore_index=True)
    base["exploratory"] = base["var"].isin(list(NUTRIENT_TOL))
    tables["baseline_compare.csv"] = base
    tables["climatology_cells.csv"] = climatology_cells(wide, clim_h, daily_wide, clim_d)

    raw = il.raw_files(args.raw_dir)
    manifest = {
        "run": RUN_NAME, "dataset": DATASET, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_commit": git_commit(),
        "acknowledgement": "Indian River Lagoon Observatory Network of Environmental Sensors (IRLON), Harbor Branch "
                           "Oceanographic Institute at Florida Atlantic University; via SECOORA ERDDAP",
        "inputs": {"raw_dir": str(args.raw_dir), "n_raw_files": len(raw),
                   "raw_bytes": int(sum(p.stat().st_size for p in raw)),
                   "raw_files_sha256": {p.relative_to(args.raw_dir).as_posix(): sha256(p) for p in raw},
                   "era5_gauge_check": era5_meta, "era5_hourly_rain": era5_hourly_meta},
        "parameters": {"period_end": il.PERIOD_END, "qc": "QARTOD qc_agg == 1 (rain: 1-2) + ranges",
                       "accepted_flags_exceptions": il.ACCEPTED_FLAGS, "ranges": il.RANGES,
                       "single_reading_per_hour_accepted": True, "tolerances_key": CORE_VARS,
                       "nutrient_tolerances_abs_rel_umolL": NUTRIENT_TOL,
                       "min_overlap_days": MIN_OVERLAP_DAYS, "gates": GATES, "min_days": MIN_DAYS, "n_boot": N_BOOT,
                       "seed": SEED, "cal_window": CAL_WINDOW, "cal_min_hours": CAL_MIN_HOURS,
                       "regime_dsal_psu": REGIME_DSAL_PSU, "season_wet_months": WET_MONTHS,
                       "regime_months_lowest_salinity": regime_months,
                       "lst_offset_h": LST_OFFSET_H, "daily_min_hours": DAILY_MIN_HOURS,
                       "climatology": f"leave-one-year-out same-month median, >= {CLIM_MIN_OTHER_YEARS} other years",
                       "rain": {"primary": "ERA5 hourly (Open-Meteo archive) at each target station",
                                "sensitivity": "target station gauge (lwe_precipitation_rate, mm/h as hourly total)",
                                "gauge_min_station_year_coverage": RAIN_MIN_YEAR_COVERAGE,
                                "gauge_fill_from_nearest_gauge_km": RAIN_FILL_MAX_KM,
                                "thresholds_mm": {"24h_heavy": RAIN24_HEAVY_MM, "72h_heavy": RAIN72_HEAVY_MM,
                                                  "none_lt": RAIN_NONE_MM}},
                       "distance_bins": list(ur.BIN_LABELS)},
        "qc": {"n_raw_rows": report["n_raw_rows"], "n_accepted": report["n_accepted"]},
        "n_pairs_evaluated": int(pair_rel[["anchor", "target", "var"]].drop_duplicates().shape[0]),
    }
    out = prepare_output_dir(args.output_dir)
    for name, table in tables.items():
        table.to_csv(out / name, index=False)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
