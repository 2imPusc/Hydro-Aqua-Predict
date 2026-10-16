"""H4.3 -- RL-12 extended to several subtropical/tropical NERRS reserves.

Question (direction 4): can one in-situ sonde ("anchor") stand in for another
location ("target")? Same protocol as RL-12 (Jobos) and RL-14 (HK EPD) so the
three datasets compare:

* Data: NCEI accession 0052765 (NERRS CDMO archive), years 2007-2011 (the only
  years with automated CDMO QAQC flags), QAQC flag ``<0>`` only, hourly means of
  >= 2 good 15-min values, local standard time (see ``experiments/nerrs_multi.py``).
* Variables / tolerances: Temp 0.5 C, Sal 1 psu, DO 0.5 mg/L, pH 0.2,
  Turbidity max(2 NTU, 20 %) -- ``nerrs_reliability.TOLERANCES``.
* Pairs: every ordered WQ-station pair within a reserve; a (pair, variable)
  enters the reliability cells only with >= 365 distinct days that have >= 1
  joint good hour. Co-located surface/bottom sondes (apa EB/ES) are listed in
  ``pairs.csv`` but excluded from all distance analyses.
* Distance bins 0-2, 2-5, 5-10, 10-20, 20-30 km; > 30 km reported separately.
* Season: per reserve the 6 calendar months with the lowest reserve-median
  salinity (2007-2011) = "wet" (low-salinity / high-flow half-year), the other
  6 = "dry". Data-driven so that e.g. Apalachicola (river high flow in winter-
  spring) and Florida summer-rain reserves are treated alike.
* Salinity regime: station median salinity in the wet season; pair "same" if
  |difference| < 2 psu, else "different"; |difference| kept as ``dsal``.
* Transfers: ``raw`` = anchor value; ``calibrated_30d`` = OLS map fitted on the
  pair over the strictly-past 30 days (>= 240 joint hours).
* Gates 80/90/95 %: day-block bootstrap (500 resamples, seed 20261016) 2.5 %
  lower bound >= gate and >= 30 distinct days. Within a reserve the block is a
  calendar day (all pairs of the cell pooled per day); for ``nerrs_pooled`` the
  block is (reserve, day).
* Strata (observation-only): reserve met station prior-24 h rain >= 10 mm vs
  < 1 mm, prior-72 h >= 20 mm vs < 1 mm (hourly sums need >= 5/6 coverage);
  season; day/night by solar elevation.
* Regime vs distance: pair-level share ~ z(km) + z(dsal) (OLS, linear and logit
  share; pooled model with reserve fixed effects), 95 % CI by cluster bootstrap
  over unordered pairs.

Run:  .venv\\Scripts\\python experiments\\nerrs_multi_reliability.py
Outputs: artifacts/experiments/nerrs-multi-h4-reliability-20261017/ (refuses to overwrite).
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
from experiments import nerrs_load as nl  # noqa: E402
from experiments import nerrs_multi as nm  # noqa: E402
from experiments import nerrs_reliability as nr  # noqa: E402

RUN_NAME = "nerrs-multi-h4-reliability-20261017"
DEFAULT_RESERVES = ("job", "rkb", "apa", "gtm", "mar", "gnd", "wkb", "sap")
VARIABLES = ("Temp", "Sal", "DO_mgl", "pH", "Turb")  # keys of nr.TOLERANCES (pH@0.1 not used)
TRANSFERS = ("raw", "calibrated_30d")
GATES = nr.GATES
N_BOOT, SEED, MIN_DAYS = 500, 20261016, nr.MIN_DAYS
MIN_OVERLAP_DAYS = 365
REGIME_DSAL_PSU = 2.0
WET_MONTHS_N = 6
RAIN24_HEAVY_MM, RAIN72_HEAVY_MM, RAIN_NONE_MM = 10.0, 20.0, 1.0
BIN_EDGES = (0, 2, 5, 10, 20, 30, np.inf)
BIN_LABELS = ("0-2", "2-5", "5-10", "10-20", "20-30", ">30")
BIN_UPPER_KM = {"0-2": 2.0, "2-5": 5.0, "5-10": 10.0, "10-20": 20.0, "20-30": 30.0}
RADIUS_BINS = BIN_LABELS[:-1]


# ---------------------------------------------------------------- primitives
def distance_bin(km) -> np.ndarray:
    return pd.cut(np.asarray(km, dtype=float), list(BIN_EDGES), labels=list(BIN_LABELS), right=False).astype(str)


def wet_months(monthly_sal: pd.Series, n: int = WET_MONTHS_N) -> tuple[int, ...]:
    """The ``n`` calendar months with the lowest salinity (ties -> earlier month)."""
    ordered = monthly_sal.dropna().sort_values(kind="mergesort")
    return tuple(sorted(int(m) for m in ordered.index[:n]))


def reserve_monthly_salinity(wq: pd.DataFrame) -> pd.Series:
    """Median over stations of each station's calendar-month median salinity."""
    sal = wq[wq["variable"] == "Sal"]
    per_station = sal.groupby(["station", sal["time_lst"].dt.month])["value"].median()
    return per_station.groupby(level=1).median()


def season_label(index: pd.DatetimeIndex, wet: tuple[int, ...]) -> np.ndarray:
    return np.where(pd.DatetimeIndex(index).month.isin(wet), "wet", "dry")


def regime_table(wq: pd.DataFrame, pairs: pd.DataFrame, wet: tuple[int, ...],
                 threshold: float = REGIME_DSAL_PSU) -> pd.DataFrame:
    sal = wq[(wq["variable"] == "Sal")]
    sal = sal[season_label(sal["time_lst"], wet) == "wet"]
    med = sal.groupby("station")["value"].median()
    out = pairs.copy()
    out["sal_wet_anchor"] = out["anchor"].map(med).round(2)
    out["sal_wet_target"] = out["target"].map(med).round(2)
    d = (out["sal_wet_anchor"] - out["sal_wet_target"]).abs()
    out["dsal"] = d.round(2)
    out["regime"] = np.select([d.isna(), d < threshold], ["unknown", "same"], "different")
    return out


def rain_class(total: pd.Series, heavy: float, none: float = RAIN_NONE_MM) -> np.ndarray:
    return np.select([total.isna(), total < none, total >= heavy], ["na", "none", "heavy"], "mid")


def build_strata(met: pd.DataFrame, hours: pd.DatetimeIndex, lat: float, lon: float, utc_offset_h: float,
                 wet: tuple[int, ...]) -> pd.DataFrame:
    strata = pd.DataFrame(index=hours)
    strata["season"] = season_label(hours, wet)
    elevation = nr.solar_elevation_deg(hours + pd.Timedelta(minutes=30), lat, lon, utc_offset_h)
    strata["daynight"] = np.where(elevation > 0, "day", "night")
    rain = met["TotPrcp"] if "TotPrcp" in met else pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    if rain.dropna().empty:
        strata["rain24"] = strata["rain72"] = "na"
        return strata
    rain = rain.reindex(pd.date_range(min(rain.index.min(), hours.min()), max(rain.index.max(), hours.max()), freq="h"))
    strata["rain24"] = rain_class(nr.prior_window_sum(rain, 24).reindex(hours), RAIN24_HEAVY_MM)
    strata["rain72"] = rain_class(nr.prior_window_sum(rain, 72).reindex(hours), RAIN72_HEAVY_MM)
    return strata


def radius(status_by_bin: dict, bins=RADIUS_BINS) -> tuple[float, float, str]:
    """(radius_km, radius_km_strict, evidence) from per-bin gate status.

    ``radius_km``: bins without evidence ('insufficient' or absent) are skipped;
    the radius is the upper edge of the last passing bin before the first
    failing one (0 if the first evidenced bin fails, NaN if none has evidence).
    ``radius_km_strict`` (RL-14 rule): the walk stops at the first bin that is
    not 'pass'; NaN if 0-2 km has no evidence.
    """
    evidence = ",".join(f"{b}:{status_by_bin.get(b, 'none')}" for b in bins)
    loose, seen = np.nan, False
    for b in bins:
        st = status_by_bin.get(b, "insufficient")
        if st == "pass":
            loose, seen = BIN_UPPER_KM[b], True
        elif st == "fail":
            loose = loose if seen else 0.0
            seen = True
            break
    strict = 0.0
    for i, b in enumerate(bins):
        st = status_by_bin.get(b, "insufficient")
        if st == "pass":
            strict = BIN_UPPER_KM[b]
            continue
        if st != "fail" and i == 0:
            strict = np.nan
        break
    return loose, strict, evidence


# ---------------------------------------------------------------- per-reserve evaluation
def station_pairs(stations: pd.DataFrame, reserve: nm.Reserve) -> pd.DataFrame:
    wq = stations[stations["kind"] == "wq"].set_index("station")
    vertical = {frozenset(p) for p in reserve.vertical_pairs}
    rows = []
    for a in wq.index:
        for b in wq.index:
            if a == b:
                continue
            km = float(nl.haversine_km(wq.at[a, "lat"], wq.at[a, "lon"], wq.at[b, "lat"], wq.at[b, "lon"]))
            rows.append({"reserve": reserve.code, "dataset": f"nerrs_{reserve.code}", "anchor": a, "target": b,
                         "km": round(km, 3), "vertical_pair": frozenset((a, b)) in vertical})
    out = pd.DataFrame(rows)
    out["distance_bin"] = distance_bin(out["km"])
    return out


def pair_hours(wide: pd.DataFrame, anchor: str, target: str, var: str) -> dict[str, pd.DataFrame]:
    """Hourly frames (est, obs, err, within) per transfer for one pair and variable."""
    if anchor not in wide or target not in wide:
        return {}
    joint = wide[[anchor, target]].dropna()
    if joint.empty:
        return {}
    x, y = joint[anchor], joint[target]
    out = {}
    for name, est in (("raw", x), ("calibrated_30d", nr.rolling_linear_transfer(x, y))):
        frame = pd.DataFrame({"est": est, "obs": y}).dropna()
        if frame.empty:
            continue
        frame["err"] = frame["obs"] - frame["est"]
        frame["within"] = nr.within_tolerance(var, frame["est"], frame["obs"])
        out[name] = frame
    return out


def daily_counts(frame: pd.DataFrame, strata: pd.DataFrame) -> pd.DataFrame:
    """Per-day within/total counts overall and per hour-level stratum level."""
    joined = frame[["within", "err"]].join(strata[["daynight", "rain24", "rain72"]], how="left")
    joined["date"] = joined.index.normalize()
    joined["abs_err"] = joined["err"].abs()
    pieces = [joined.groupby("date").agg(w=("within", "sum"), n=("within", "size"), sae=("abs_err", "sum"))
              .assign(stratum="all", level="all")]
    for col in ("daynight", "rain24", "rain72"):
        g = joined.groupby(["date", col]).agg(w=("within", "sum"), n=("within", "size"), sae=("abs_err", "sum"))
        g = g.reset_index(level=1).rename(columns={col: "level"}).assign(stratum=col)
        pieces.append(g)
    out = pd.concat(pieces).reset_index()
    out["w"] = out["w"].astype("int32")
    out["n"] = out["n"].astype("int32")
    return out


ERA5_DIR = nm.NERRS_ROOT / "era5_rain"


def load_or_fetch_era5_daily(lat: float, lon: float, start: str = "2007-01-01", end: str = "2011-12-31",
                             cache_dir: Path = ERA5_DIR, allow_fetch: bool = True) -> tuple[pd.Series | None, dict]:
    """Open-Meteo ERA5 daily precipitation (UTC days) -- used only to sanity-check the met gauges."""
    import urllib.request
    path = Path(cache_dir) / f"open_meteo_era5_precip_daily_utc_{lat:.3f}_{lon:.3f}_{start}_{end}.csv"
    url = ("https://archive-api.open-meteo.com/v1/archive?"
           f"latitude={lat:.3f}&longitude={lon:.3f}&start_date={start}&end_date={end}"
           "&daily=precipitation_sum&models=era5&timezone=GMT")
    meta = {"file": _rel(path), "url": url}
    if not path.exists():
        if not allow_fetch:
            return None, {**meta, "status": "absent_no_fetch"}
        try:
            req = urllib.request.Request(url, headers={"User-Agent": nm.USER_AGENT})
            with urllib.request.urlopen(req, timeout=90) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 -- the check is optional
            return None, {**meta, "status": f"fetch_failed: {exc!r}"}
        path.parent.mkdir(parents=True, exist_ok=True)
        daily = pd.DataFrame({"date": payload["daily"]["time"], "precip_mm": payload["daily"]["precipitation_sum"]})
        with open(path, "x", encoding="utf-8", newline="") as handle:  # write-once
            daily.to_csv(handle, index=False)
    daily = pd.read_csv(path, parse_dates=["date"])
    return daily.set_index("date")["precip_mm"].astype(float), {**meta, "status": "ok", "sha256": nr.sha256(path)}


def rain_gauge_check(rain_hourly_lst: pd.Series, utc_offset_h: float, era5_daily: pd.Series) -> pd.DataFrame:
    """Per year: gauge vs ERA5 totals on UTC days with 24/24 gauge hours, and daily Pearson r."""
    utc = rain_hourly_lst.dropna().copy()
    utc.index = utc.index - pd.Timedelta(hours=utc_offset_h)
    grouped = utc.groupby(utc.index.normalize())
    days = grouped.sum()[grouped.count() == 24]
    joint = pd.DataFrame({"gauge": days, "era5": era5_daily.reindex(days.index)}).dropna()
    rows = []
    for year, grp in joint.groupby(joint.index.year):
        rows.append({"year": int(year), "complete_days": int(len(grp)), "gauge_mm": round(float(grp["gauge"].sum()), 1),
                     "era5_mm": round(float(grp["era5"].sum()), 1),
                     "ratio_gauge_over_era5": round(float(grp["gauge"].sum() / grp["era5"].sum()), 3) if grp["era5"].sum() else np.nan,
                     "pearson_r_daily": round(float(grp["gauge"].corr(grp["era5"])), 3) if len(grp) > 10 else np.nan})
    return pd.DataFrame(rows)


def evaluate_reserve(reserve: nm.Reserve, data_dir: Path | None = None, allow_fetch: bool = True):
    """Load one reserve -> (stations, pairs, daily, wet, flags, coverage, met_summary, gauge_check)."""
    data_dir = Path(data_dir or reserve.data_dir)
    stations = nm.station_table(reserve, data_dir)
    wq, flags = nm.load_wq_hourly(reserve, years=nm.QC_YEARS, data_dir=data_dir)
    met, met_flags = nm.load_met_hourly(reserve, years=nm.QC_YEARS, data_dir=data_dir)
    monthly = reserve_monthly_salinity(wq)
    wet = wet_months(monthly)
    pairs = regime_table(wq, station_pairs(stations, reserve), wet)
    wqs = stations[stations["kind"] == "wq"]
    hours = pd.date_range(wq["time_lst"].min().floor("D"), wq["time_lst"].max().ceil("D"), freq="h")
    strata = build_strata(met, hours, wqs["lat"].mean(), wqs["lon"].mean(), reserve.utc_offset_h, wet)
    wide = {v: wq[wq["variable"] == v].pivot(index="time_lst", columns="station", values="value") for v in VARIABLES}
    daily, pair_extra = [], []
    for pair in pairs.itertuples(index=False):
        extra = {"anchor": pair.anchor, "target": pair.target}
        for var in VARIABLES:
            frames = pair_hours(wide[var], pair.anchor, pair.target, var)
            n_days = int(frames["raw"].index.normalize().nunique()) if "raw" in frames else 0
            extra[f"n_days_{var}"] = n_days
            for transfer, frame in frames.items():
                d = daily_counts(frame, strata)
                d.insert(0, "var", var)
                d.insert(0, "transfer", transfer)
                d.insert(0, "target", pair.target)
                d.insert(0, "anchor", pair.anchor)
                d.insert(0, "reserve", reserve.code)
                daily.append(d)
        pair_extra.append(extra)
    pairs = pairs.merge(pd.DataFrame(pair_extra), on=["anchor", "target"])
    daily = pd.concat(daily, ignore_index=True) if daily else pd.DataFrame()
    if not daily.empty:
        daily["season"] = season_label(daily["date"], wet)
    flags_all = pd.concat([flags, met_flags], ignore_index=True)
    flags_all.insert(0, "reserve", reserve.code)
    coverage = (wq.assign(year=wq["time_lst"].dt.year).groupby(["station", "variable", "year"]).size()
                .rename("good_hours").reset_index())
    coverage.insert(0, "reserve", reserve.code)
    rain = met["TotPrcp"] if "TotPrcp" in met else pd.Series(dtype=float)
    met_summary = {
        "reserve": reserve.code, "met_stations": list(reserve.met_stations),
        "rain_hours": int(rain.notna().sum()),
        "rain_annual_mm_observed_hours": {int(y): round(float(v), 1) for y, v in rain.groupby(rain.index.year).sum().items()},
        "rain_hour_coverage_by_year": {int(y): round(float(v) / 8760, 3) for y, v in rain.groupby(rain.index.year).count().items()},
        "strata_hours": {c: strata[c].value_counts().to_dict() for c in ("rain24", "rain72", "season", "daynight")},
        "wet_months": list(wet), "monthly_median_salinity": {int(k): round(float(v), 2) for k, v in monthly.items()},
    }
    era5, era5_meta = load_or_fetch_era5_daily(round(wqs["lat"].mean(), 3), round(wqs["lon"].mean(), 3),
                                               allow_fetch=allow_fetch)
    gauge = rain_gauge_check(rain, reserve.utc_offset_h, era5) if era5 is not None and not rain.empty else pd.DataFrame()
    if not gauge.empty:
        gauge.insert(0, "reserve", reserve.code)
    met_summary["era5_check"] = era5_meta
    stations = stations.assign(dataset=f"nerrs_{reserve.code}")
    return stations, pairs, daily, wet, flags_all, coverage, met_summary, gauge


# ---------------------------------------------------------------- aggregation
def _share_record(per_block: pd.DataFrame) -> dict:
    share, lo, hi = nr.bootstrap_share(per_block["w"].to_numpy(), per_block["n"].to_numpy(), n_boot=N_BOOT, seed=SEED)
    n_days = int(len(per_block))
    rec = {"n_days": n_days, "n_hours": int(per_block["n"].sum()),
           "mae": round(float(per_block["sae"].sum() / per_block["n"].sum()), 4) if per_block["n"].sum() else np.nan,
           "share": round(share, 4), "ci_low": round(lo, 4), "ci_high": round(hi, 4)}
    for g in GATES:
        rec[f"gate{int(g * 100)}"] = nr.gate_status(lo, n_days, g, min_days=MIN_DAYS)
    return rec


def eligible_daily(daily: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """Overall-stratum daily rows of non-vertical pairs with >= MIN_OVERLAP_DAYS for that variable."""
    keep = []
    for var in VARIABLES:
        ok = pairs[(~pairs["vertical_pair"]) & (pairs[f"n_days_{var}"] >= MIN_OVERLAP_DAYS)][["reserve", "anchor", "target"]]
        keep.append(ok.assign(var=var))
    keep = pd.concat(keep, ignore_index=True)
    meta = pairs[["reserve", "anchor", "target", "km", "distance_bin", "regime", "dsal"]]
    return daily.merge(keep, on=["reserve", "anchor", "target", "var"]).merge(meta, on=["reserve", "anchor", "target"])


def _blocks(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.groupby(["reserve", "date"])[["w", "n", "sae"]].sum()


def cell_table(elig: pd.DataFrame) -> pd.DataFrame:
    """cells.csv: per reserve and pooled; regime in {same, different, all}."""
    base = elig[elig["stratum"] == "all"]
    rows = []
    for dataset, scope in [(f"nerrs_{r}", base[base["reserve"] == r]) for r in sorted(base["reserve"].unique())] + [
            ("nerrs_pooled", base)]:
        for regime in ("same", "different", "all"):
            sub = scope if regime == "all" else scope[scope["regime"] == regime]
            for (var, dbin, transfer), grp in sub.groupby(["var", "distance_bin", "transfer"]):
                rec = {"dataset": dataset, "var": var, "regime": regime, "distance_bin": dbin, "transfer": transfer,
                       "n_pairs": int(grp[["reserve", "anchor", "target"]].drop_duplicates().shape[0]),
                       "n_reserves": int(grp["reserve"].nunique())}
                rec.update(_share_record(_blocks(grp)))
                rows.append(rec)
    order = {b: i for i, b in enumerate(BIN_LABELS)}
    out = pd.DataFrame(rows)
    return out.sort_values(["dataset", "var", "regime", "transfer", "distance_bin"],
                           key=lambda s: s.map(order) if s.name == "distance_bin" else s).reset_index(drop=True)


def radius_table(cells: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (dataset, var, regime, transfer), grp in cells.groupby(["dataset", "var", "regime", "transfer"]):
        for g in GATES:
            col = f"gate{int(g * 100)}"
            loose, strict, evidence = radius(grp.set_index("distance_bin")[col].to_dict())
            rows.append({"dataset": dataset, "var": var, "regime": regime, "transfer": transfer, "gate": col,
                         "radius_km": loose, "radius_km_strict": strict, "evidence": evidence})
    return pd.DataFrame(rows)


def pair_reliability(elig: pd.DataFrame) -> pd.DataFrame:
    base = elig[elig["stratum"] == "all"]
    rows = []
    for (reserve, anchor, target, var, transfer), grp in base.groupby(["reserve", "anchor", "target", "var", "transfer"]):
        rec = {"dataset": f"nerrs_{reserve}", "reserve": reserve, "anchor": anchor, "target": target, "var": var,
               "transfer": transfer, "km": grp["km"].iloc[0], "distance_bin": grp["distance_bin"].iloc[0],
               "regime": grp["regime"].iloc[0], "dsal": grp["dsal"].iloc[0]}
        rec.update(_share_record(grp.set_index("date")[["w", "n", "sae"]]))
        rows.append(rec)
    return pd.DataFrame(rows)


def _ols(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(X, y, rcond=None)[0]


def _design(frame: pd.DataFrame, fixed_effects: bool) -> tuple[np.ndarray, list[str]]:
    zk = (frame["km"] - frame["km"].mean()) / frame["km"].std(ddof=0)
    zs = (frame["dsal"] - frame["dsal"].mean()) / frame["dsal"].std(ddof=0)
    cols, names = [np.ones(len(frame)), zk.to_numpy(), zs.to_numpy()], ["const", "z_km", "z_dsal"]
    if fixed_effects:
        for r in sorted(frame["reserve"].unique())[1:]:
            cols.append((frame["reserve"] == r).to_numpy(float))
            names.append(f"fe_{r}")
    return np.column_stack(cols), names


def regime_vs_distance(pairrel: pd.DataFrame, n_boot: int = N_BOOT, seed: int = SEED) -> pd.DataFrame:
    """Standardised OLS of pair share on km and |dsal|; cluster bootstrap over unordered pairs."""
    rows = []
    rel = pairrel[(pairrel["km"] <= 30) & pairrel["dsal"].notna()].copy()
    rel["cluster"] = rel["reserve"] + ":" + rel.apply(lambda r: "-".join(sorted((r.anchor, r.target))), axis=1)
    scopes = [(f"nerrs_{r}", rel[rel["reserve"] == r], False) for r in sorted(rel["reserve"].unique())]
    scopes.append(("nerrs_pooled", rel, True))
    rng_master = np.random.default_rng(seed)
    for dataset, scope, fe in scopes:
        for (var, transfer), grp in scope.groupby(["var", "transfer"]):
            grp = grp.reset_index(drop=True)
            if len(grp) < 6 or grp["km"].std() == 0 or grp["dsal"].std() == 0:
                continue
            clip = grp["share"].clip(0.005, 0.995)
            targets = {"share": grp["share"].to_numpy(), "logit_share": np.log(clip / (1 - clip)).to_numpy()}
            X, names = _design(grp, fe)
            clusters = grp["cluster"].to_numpy()
            uniq = np.unique(clusters)
            members = {c: np.flatnonzero(clusters == c) for c in uniq}
            rng = np.random.default_rng(rng_master.integers(1 << 31))
            boot_idx = []
            for _ in range(n_boot):
                pick = rng.choice(uniq, size=len(uniq), replace=True)
                boot_idx.append(np.concatenate([members[c] for c in pick]))
            corr = float(np.corrcoef(grp["km"], grp["dsal"])[0, 1])
            for yname, y in targets.items():
                beta = _ols(y, X)
                boots = []
                for idx in boot_idx:
                    sub = grp.iloc[idx]
                    if sub["km"].std() == 0 or sub["dsal"].std() == 0:
                        continue
                    Xb, nb = _design(sub, fe)
                    if len(nb) != len(names):
                        continue
                    boots.append(_ols(y[idx], Xb)[1:3])
                boots = np.array(boots)
                lo = np.nanpercentile(boots, 2.5, axis=0) if len(boots) else [np.nan, np.nan]
                hi = np.nanpercentile(boots, 97.5, axis=0) if len(boots) else [np.nan, np.nan]
                fitted = X @ beta
                r2 = 1 - np.sum((y - fitted) ** 2) / np.sum((y - y.mean()) ** 2) if np.var(y) > 0 else np.nan
                rows.append({"dataset": dataset, "var": var, "transfer": transfer, "response": yname,
                             "n_pairs_ordered": int(len(grp)), "n_pairs_unordered": int(len(uniq)),
                             "reserve_fixed_effects": fe, "corr_km_dsal": round(corr, 3),
                             "beta_z_km": round(float(beta[1]), 4), "ci_low_km": round(float(lo[0]), 4),
                             "ci_high_km": round(float(hi[0]), 4),
                             "beta_z_dsal": round(float(beta[2]), 4), "ci_low_dsal": round(float(lo[1]), 4),
                             "ci_high_dsal": round(float(hi[1]), 4),
                             "abs_dsal_gt_abs_km": bool(abs(beta[2]) > abs(beta[1])),
                             "r2": round(float(r2), 3), "n_boot_used": int(len(boots)),
                             "descriptive_only": not fe})
    return pd.DataFrame(rows)


EFFECTS = (("rain24_heavy_vs_none", "rain24", "heavy", "none"),
           ("rain72_heavy_vs_none", "rain72", "heavy", "none"),
           ("night_vs_day", "daynight", "night", "day"))


def effect_table(elig: pd.DataFrame, effects=EFFECTS) -> pd.DataFrame:
    """Share difference A - B (blocks resampled jointly) per dataset x var x transfer x regime."""
    rows = []
    datasets = [(f"nerrs_{r}", elig[elig["reserve"] == r]) for r in sorted(elig["reserve"].unique())]
    datasets.append(("nerrs_pooled", elig))
    for dataset, scope in datasets:
        for name, col, a, b in effects:
            sub = scope[scope["stratum"] == col]
            for regime in ("all", "same", "different"):
                reg = sub if regime == "all" else sub[sub["regime"] == regime]
                for (var, transfer), grp in reg.groupby(["var", "transfer"]):
                    rows.append(_effect_row(grp, "level", a, b, {"dataset": dataset, "effect": name, "var": var,
                                                                 "transfer": transfer, "regime": regime}))
        # season is a day-level stratum
        base = scope[scope["stratum"] == "all"]
        for regime in ("all", "same", "different"):
            reg = base if regime == "all" else base[base["regime"] == regime]
            for (var, transfer), grp in reg.groupby(["var", "transfer"]):
                rows.append(_effect_row(grp, "season", "wet", "dry", {"dataset": dataset, "effect": "wet_vs_dry_season",
                                                                      "var": var, "transfer": transfer, "regime": regime}))
    return pd.DataFrame([r for r in rows if r is not None])


def _effect_row(grp: pd.DataFrame, column: str, a: str, b: str, key: dict) -> dict | None:
    agg = {}
    for lab, level in (("a", a), ("b", b)):
        part = grp[grp[column] == level]
        agg[lab] = part.groupby(["reserve", "date"])[["w", "n", "sae"]].sum()
    table = agg["a"].join(agg["b"], how="outer", lsuffix="_a", rsuffix="_b").fillna(0)
    days_a, days_b = int((table["n_a"] > 0).sum()), int((table["n_b"] > 0).sum())
    if days_a < 10 or days_b < 10:
        return None
    diff, lo, hi = nr.bootstrap_share_difference(table["w_a"], table["n_a"], table["w_b"], table["n_b"],
                                                 n_boot=N_BOOT, seed=SEED)
    return {**key, "level_a": a, "level_b": b, "days_a": days_a, "days_b": days_b,
            "hours_a": int(table["n_a"].sum()), "hours_b": int(table["n_b"].sum()),
            "share_a": round(float(table["w_a"].sum() / table["n_a"].sum()), 4),
            "share_b": round(float(table["w_b"].sum() / table["n_b"].sum()), 4),
            "diff_a_minus_b": round(diff, 4), "diff_ci_low": round(lo, 4), "diff_ci_high": round(hi, 4),
            "mae_a": round(float(table["sae_a"].sum() / table["n_a"].sum()), 4),
            "mae_b": round(float(table["sae_b"].sum() / table["n_b"].sum()), 4),
            "significant": bool(lo > 0 or hi < 0)}


# ---------------------------------------------------------------- main
def prepare_output_dir(path: Path) -> Path:
    """Write-once output dir: create it, or reuse it only if it exists and is empty."""
    path = Path(path)
    if path.exists():
        if any(path.iterdir()):
            raise FileExistsError(f"refusing to overwrite non-empty output dir: {path}")
        return path
    return nr.prepare_output_dir(path)


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _rel(path: Path) -> str:
    path = Path(path)
    return str(path.relative_to(paths.PROJECT_ROOT)).replace("\\", "/") if path.is_relative_to(paths.PROJECT_ROOT) else str(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME)
    parser.add_argument("--reserves", nargs="+", default=list(DEFAULT_RESERVES), choices=list(nm.RESERVES))
    parser.add_argument("--no-fetch", action="store_true", help="do not fetch the ERA5 gauge-check series")
    args = parser.parse_args(argv)
    out = prepare_output_dir(args.output_dir)

    stations, pairs, daily, flags, coverage, met_info, inputs, gauges = [], [], [], [], [], [], [], []
    for code in args.reserves:
        reserve = nm.RESERVES[code]
        print(f"[{code}] loading", flush=True)
        st, pr, dl, wet, fl, cov, met, gauge = evaluate_reserve(reserve, allow_fetch=not args.no_fetch)
        stations.append(st), pairs.append(pr), daily.append(dl), flags.append(fl), coverage.append(cov)
        met_info.append(met), gauges.append(gauge)
        if met["era5_check"].get("status") == "ok":
            era5_path = paths.PROJECT_ROOT / met["era5_check"]["file"]
            inputs.append({"file": met["era5_check"]["file"], "bytes": era5_path.stat().st_size,
                           "sha256": met["era5_check"]["sha256"]})
        used = [p for p in sorted(reserve.data_dir.glob(f"{code}*.csv"))
                if nm._FILE_RE.match(p.name) and int(p.stem[-4:]) in nm.QC_YEARS
                and (p.name[3:5] in reserve.wq_stations + reserve.met_stations) and "nut" not in p.name]
        used += nm.metadata_docs(reserve, "wq") + nm.metadata_docs(reserve, "met")
        inputs += [{"file": _rel(p), "bytes": p.stat().st_size, "sha256": nr.sha256(p)} for p in used]
    if nm.STAT_LOCS_CSV.exists():
        inputs.append({"file": _rel(nm.STAT_LOCS_CSV), "bytes": nm.STAT_LOCS_CSV.stat().st_size,
                       "sha256": nr.sha256(nm.STAT_LOCS_CSV)})
    stations = pd.concat(stations, ignore_index=True)
    pairs = pd.concat(pairs, ignore_index=True)
    daily = pd.concat(daily, ignore_index=True)
    flags = pd.concat(flags, ignore_index=True)
    coverage = pd.concat(coverage, ignore_index=True)

    print("aggregating", flush=True)
    elig = eligible_daily(daily, pairs)
    cells = cell_table(elig)
    radius_df = radius_table(cells)
    pairrel = pair_reliability(elig)
    rvd = regime_vs_distance(pairrel)
    effects = effect_table(elig)

    flag_shares = flags.groupby(["reserve", "station", "year", "variable", "flag"], as_index=False)["n"].sum()
    flag_shares["share"] = (flag_shares["n"] / flag_shares.groupby(["reserve", "station", "year", "variable"])["n"]
                            .transform("sum")).round(4)

    pair_cols = ["dataset", "reserve", "anchor", "target", "km", "distance_bin", "vertical_pair", "regime", "dsal",
                 "sal_wet_anchor", "sal_wet_target"] + [f"n_days_{v}" for v in VARIABLES]
    stations.to_csv(out / "stations.csv", index=False)
    pairs[pair_cols].to_csv(out / "pairs.csv", index=False)
    cells.to_csv(out / "cells.csv", index=False)
    radius_df.to_csv(out / "radius.csv", index=False)
    rvd.to_csv(out / "regime_vs_distance.csv", index=False)
    effects[effects["effect"].str.startswith("rain")].to_csv(out / "rain_effect.csv", index=False)
    effects[~effects["effect"].str.startswith("rain")].to_csv(out / "strata_effect.csv", index=False)
    pairrel.to_csv(out / "pair_reliability.csv", index=False)
    flag_shares.to_csv(out / "flag_shares.csv", index=False)
    coverage.to_csv(out / "coverage.csv", index=False)
    pd.concat(gauges, ignore_index=True).to_csv(out / "rain_gauge_check.csv", index=False)

    manifest = {
        "run": RUN_NAME, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "experiments/nerrs_multi_reliability.py", "loader": "experiments/nerrs_multi.py",
        "code_commit": _git_commit(),
        "source": f"NOAA NCEI accession {nm.NCEI_ACCESSION} (NERRS CDMO archive v2.2), {nm.NCEI_BASE}",
        "reserves": {c: {"name": nm.RESERVES[c].name, "state": nm.RESERVES[c].state,
                         "wq_stations": list(nm.RESERVES[c].wq_stations), "met_stations": list(nm.RESERVES[c].met_stations),
                         "utc_offset_h": nm.RESERVES[c].utc_offset_h} for c in args.reserves},
        "parameters": {
            "years": list(nm.QC_YEARS), "good_flag": 0, "hourly_min_obs": 2,
            "tolerances": {v: {"abs": nr.TOLERANCES[v][1], "rel": nr.TOLERANCES[v][2]} for v in VARIABLES},
            "transfers": {"raw": "anchor value", "calibrated_30d": "OLS on strictly-past 30 d, >= 240 joint hours"},
            "min_overlap_days": MIN_OVERLAP_DAYS, "distance_bins_km": list(BIN_LABELS),
            "season_rule": f"per reserve the {WET_MONTHS_N} calendar months with lowest reserve-median salinity = wet",
            "regime_rule": f"|wet-season median salinity difference| < {REGIME_DSAL_PSU} psu -> same",
            "gates": list(GATES), "gate_rule": "day-block bootstrap 2.5% lower bound >= gate and n_days >= 30",
            "bootstrap_blocks": {"per_reserve": "calendar day", "nerrs_pooled": "(reserve, day)"},
            "n_boot": N_BOOT, "seed": SEED,
            "rain": {"source": "reserve met station TotPrcp (flag <0>), hourly sum needs 4/4 quarter-hours; "
                               "prior windows need >= 5/6 hourly coverage",
                     "rain24_heavy_mm": RAIN24_HEAVY_MM, "rain72_heavy_mm": RAIN72_HEAVY_MM,
                     "none_below_mm": RAIN_NONE_MM},
            "radius_rules": {"radius_km": "skip bins without evidence; upper edge of last pass before first fail",
                             "radius_km_strict": "RL-14 rule: stop at first non-pass bin; NaN if 0-2 km lacks evidence"},
            "regression": "pair share (and logit share) ~ z(km) + z(dsal) [+ reserve FE pooled]; pairs <= 30 km, "
                          "non-vertical, >= 365 overlap days; 95% CI cluster bootstrap over unordered pairs",
            "excluded_pairs": "co-located vertical sondes (apa eb/es)",
        },
        "met": met_info,
        "inputs": inputs,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
