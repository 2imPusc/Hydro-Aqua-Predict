"""Copernicus Marine (CMEMS) salinity / temperature / waves / currents at the 14 cage stations.

Theory-track, shadow, NOT used by alerts. Products (decisions #18: always name the model):

* GLOBAL_MULTIYEAR_PHY_001_030  GLORYS12V1 reanalysis, 1/12 deg, daily, 1993 -> ~2026-09 (thetao, so, uo, vo)
* GLOBAL_ANALYSISFORECAST_PHY_001_024  Mercator GLO12 analysis/forecast, 1/12 deg (daily + hourly)
* GLOBAL_ANALYSISFORECAST_WAV_001_027  MFWAM global wave analysis/forecast, 1/12 deg, 3-hourly (VHM0, VMDR, VTPK)

No regional CMEMS product covers the Gulf of Tonkin (regional MFCs are ATL/ARC/BAL/BS/IBI/MED/NWS only).
Downloads are tiny box subsets, written once under ``paths.CMEMS_DIR/<product>/`` with a sidecar manifest.
The ``copernicusmarine`` toolbox (optional, requirements-hazards.txt) reads credentials from the user's
home config; this module never reads, logs or stores them.

    python experiments/cmems_sites.py --download      # fetch missing files only (write-once)
    python experiments/cmems_sites.py --stamp 20261024
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402

STATION = "06M26042804"
BASIS = {"used_by_alerts": False, "notification_eligible": False, "basis": "theory_only_unvalidated"}
BBOX = [106.80, 20.55, 107.35, 20.95]  # lon_min, lat_min, lon_max, lat_max: all 14 stations
VANDON_BBOX = [107.30, 20.85, 107.75, 21.20]  # Vân Đồn bay (approximate; kill site coordinates not published)
DEPTH_MAX = 10.5  # levels 0.49 ... 9.57 m
YAGI = ("2024-09-05", "2024-09-09")
MY = "GLOBAL_MULTIYEAR_PHY_001_030"
PHY = "GLOBAL_ANALYSISFORECAST_PHY_001_024"
WAV = "GLOBAL_ANALYSISFORECAST_WAV_001_027"


# ---------------- pure helpers ----------------
def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def nearest_sea_cell(lat, lon, lats, lons, sea_mask) -> tuple[int, int, float]:
    """Nearest cell with ``sea_mask[i, j]`` True (rows = lats, cols = lons). Returns (i, j, km)."""
    best = None
    for i, la in enumerate(lats):
        for j, lo in enumerate(lons):
            if not sea_mask[i, j]:
                continue
            d = haversine_km(lat, lon, float(la), float(lo))
            if best is None or d < best[2]:
                best = (i, j, d)
    if best is None:
        raise ValueError("no sea cell in grid")
    return best


def speed(u, v):
    return np.hypot(np.asarray(u, dtype=float), np.asarray(v, dtype=float))


def p95(values) -> float:
    a = np.asarray(values, dtype=float)
    a = a[~np.isnan(a)]
    return float(np.percentile(a, 95)) if a.size else float("nan")


def score(obs: pd.Series, pred: pd.Series) -> dict:
    """bias = product - sensor (positive: product warmer). mae_demeaned removes the in-sample mean bias."""
    j = pd.concat([obs.rename("o"), pred.rename("p")], axis=1).dropna()
    n = len(j)
    if n == 0:
        return {"n": 0, "bias": np.nan, "mae": np.nan, "rmse": np.nan, "mae_demeaned": np.nan, "r": np.nan}
    d = j["p"] - j["o"]
    return {"n": n, "bias": float(d.mean()), "mae": float(d.abs().mean()), "rmse": float(np.sqrt((d**2).mean())),
            "mae_demeaned": float((d - d.mean()).abs().mean()),
            "r": float(j["o"].corr(j["p"])) if n >= 3 else float("nan")}


def hot_day_counts(obs, pred, thr: float) -> dict:
    o, p = np.asarray(obs, dtype=float) >= thr, np.asarray(pred, dtype=float) >= thr
    h, m, fa = int((o & p).sum()), int((o & ~p).sum()), int((~o & p).sum())
    div = lambda a, b: a / b if b else float("nan")  # noqa: E731
    return {"H": h, "M": m, "FA": fa, "pod": div(h, h + m), "far": div(fa, h + fa), "csi": div(h, h + m + fa)}


def monthly_climatology(series: pd.Series) -> pd.DataFrame:
    g = series.dropna().groupby(series.dropna().index.month)
    out = pd.DataFrame({"mean": g.mean(), "p05": g.quantile(0.05), "p50": g.quantile(0.5), "p95": g.quantile(0.95),
                        "min": g.min(), "max": g.max(), "n": g.size()})
    return out.reindex(range(1, 13))


def low_runs(series: pd.Series, thr: float, min_days: int = 1) -> list[dict]:
    """Consecutive-day runs with value < thr (daily, gap-free index assumed)."""
    s = series.dropna()
    runs, cur = [], None
    for t, v in s.items():
        if v < thr and (cur is None or (t - cur["_last"]).days == 1):
            cur = cur or {"start": t, "min": v, "min_date": t, "days": 0}
            cur["days"] += 1
            cur["_last"] = t
            if v < cur["min"]:
                cur["min"], cur["min_date"] = v, t
        else:
            if cur is not None and cur["days"] >= min_days:
                runs.append(cur)
            cur = {"start": t, "min": v, "min_date": t, "days": 1, "_last": t} if v < thr else None
    if cur is not None and cur["days"] >= min_days:
        runs.append(cur)
    return [{"start": str(r["start"].date()), "end": str(r["_last"].date()), "days": r["days"],
             "min": float(r["min"]), "min_date": str(r["min_date"].date())} for r in runs]


def window_extreme(series: pd.Series, start: str, end: str, how: str = "max") -> float:
    w = series.loc[start:end].dropna()
    if w.empty:
        return float("nan")
    return float(w.max() if how == "max" else w.min())


def download_plan(end: str, my_end: str) -> list[dict]:
    """Subsets to fetch. ``end`` = last analysis day wanted; ``my_end`` = last day of GLORYS12 MY."""
    def e(key, product, dataset, model, version, variables, start, stop, bbox=BBOX, depth=(0.0, DEPTH_MAX)):
        return {"key": key, "product_id": product, "dataset_id": dataset, "model": model, "version": version,
                "variables": variables, "bbox": bbox, "depth": list(depth) if depth else None,
                "start": start, "end": stop}
    glorys = "GLORYS12V1 reanalysis (Mercator Ocean), 1/12 deg"
    glo12 = "Mercator GLO12 analysis/forecast (MOI GLO12), 1/12 deg"
    return [
        e("my_ts_1993", MY, "cmems_mod_glo_phy_my_0.083deg_P1D-m", glorys, "202311", ["thetao", "so"], "1993-01-01", my_end),
        e("my_uv", MY, "cmems_mod_glo_phy_my_0.083deg_P1D-m", glorys, "202311", ["uo", "vo"], "2024-01-01", my_end),
        e("vandon_my_ts", MY, "cmems_mod_glo_phy_my_0.083deg_P1D-m", glorys, "202311", ["thetao", "so"], "1993-01-01", my_end,
          bbox=VANDON_BBOX, depth=(0.0, 1.0)),
        e("vandon_anfc_so_d", PHY, "cmems_mod_glo_phy-so_anfc_0.083deg_P1D-m", glo12, "202406", ["so"], "2022-06-01", end,
          bbox=VANDON_BBOX, depth=(0.0, 1.0)),
        e("anfc_thetao_d", PHY, "cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m", glo12, "202406", ["thetao"], "2022-06-01", end),
        e("anfc_so_d", PHY, "cmems_mod_glo_phy-so_anfc_0.083deg_P1D-m", glo12, "202406", ["so"], "2022-06-01", end),
        e("anfc_hourly_sfc", PHY, "cmems_mod_glo_phy_anfc_0.083deg_PT1H-m", glo12, "202406", ["thetao", "so", "uo", "vo"],
          "2024-01-01", end, depth=(0.0, 1.0)),
        e("wav", WAV, "cmems_mod_glo_wav_anfc_0.083deg_PT3H-i", "MFWAM global wave analysis/forecast, 1/12 deg", "202411",
          ["VHM0", "VMDR", "VTPK"], "2024-01-01", end, depth=None),
    ]


def target_path(entry: dict, root: Path | None = None) -> Path:
    root = paths.CMEMS_DIR if root is None else root
    box = "_".join(f"{x:g}" for x in entry["bbox"])
    name = f"{entry['key']}__{entry['dataset_id']}__{'-'.join(entry['variables'])}__{box}__{entry['start'].replace('-', '')}_{entry['end'].replace('-', '')}.nc"
    return root / entry["product_id"] / name


def write_manifest(nc: Path, entry: dict, *, version: str, tool_version: str) -> dict:
    side = nc.with_name(nc.name + ".manifest.json")
    if side.exists():
        raise FileExistsError(side)
    data = nc.read_bytes()
    m = {"file": nc.name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
         "product_id": entry["product_id"], "dataset_id": entry["dataset_id"], "model": entry["model"],
         "version": version, "variables": entry["variables"], "bbox_lon_lat": entry["bbox"],
         "depth_m": entry.get("depth"), "start": entry["start"], "end": entry["end"],
         "toolbox": f"copernicusmarine {tool_version}", "downloaded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         **BASIS}
    with side.open("x", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
    return m


# ---------------- download (needs copernicusmarine + network) ----------------
def download_missing(plan: list[dict]) -> list[Path]:
    import copernicusmarine as cm  # optional dependency (requirements-hazards.txt)

    out = []
    for e in plan:
        dest = target_path(e)
        out.append(dest)
        if dest.exists():
            print("have", dest.name)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="cmems_"))
        kw = dict(dataset_id=e["dataset_id"], variables=e["variables"], minimum_longitude=e["bbox"][0],
                  maximum_longitude=e["bbox"][2], minimum_latitude=e["bbox"][1], maximum_latitude=e["bbox"][3],
                  start_datetime=e["start"], end_datetime=e["end"] + "T23:59:59", output_directory=str(tmp),
                  output_filename=dest.name, overwrite=False, disable_progress_bar=True)
        if e["depth"]:
            kw.update(minimum_depth=e["depth"][0], maximum_depth=e["depth"][1])
        print("fetch", dest.name)
        cm.subset(**kw)
        shutil.move(str(tmp / dest.name), str(dest))
        shutil.rmtree(tmp, ignore_errors=True)
        write_manifest(dest, e, version=e["version"], tool_version=cm.__version__)
    return out


# ---------------- analysis ----------------
def _stations() -> pd.DataFrame:
    return pd.read_csv(paths.DATA_DIR / "map" / "station_coordinates.csv")[["Station", "Station_Name", "Lat", "Lon"]]


def _cells(da, stations: pd.DataFrame) -> pd.DataFrame:
    """Nearest sea cell per station; ``da`` has dims (lat, lon) after taking first time/depth."""
    sea = da.notnull().values
    lats, lons = da["latitude"].values, da["longitude"].values
    rows = []
    for s in stations.itertuples():
        i, j, d = nearest_sea_cell(s.Lat, s.Lon, lats, lons, sea)
        rows.append({"station": s.Station, "lat": s.Lat, "lon": s.Lon, "i": i, "j": j, "cell_lat": float(lats[i]),
                     "cell_lon": float(lons[j]), "dist_km": round(d, 2)})
    return pd.DataFrame(rows)


def _series(ds, var, cell, depth_idx=None):
    x = ds[var]
    if "depth" in x.dims:
        x = x.isel(depth=depth_idx if depth_idx is not None else 0)
    x = x.isel(latitude=int(cell["i"]), longitude=int(cell["j"]))
    return x.to_series()


def _first_valid_2d(ds, var):
    x = ds[var]
    if "depth" in x.dims:
        x = x.isel(depth=0)
    return x.isel(time=0)


def _open(plan, key):
    import xarray as xr

    e = next(p for p in plan if p["key"] == key)
    return xr.open_dataset(target_path(e)), e


def run_analysis(plan: list[dict], run_dir: Path) -> dict:
    from core import heat_stress as hs
    from experiments.heat_hindcast import sensor_daily
    from experiments.heat_skill import load_inputs

    st = _stations()
    out: dict = {}
    # --- cells
    my, _ = _open(plan, "my_ts_1993")
    cells_my = _cells(_first_valid_2d(my, "thetao"), st)
    cells_my.to_csv(run_dir / "cells_glorys12.csv", index=False)
    nb1 = cells_my[cells_my.station == "NB1"].iloc[0]
    out["nb1_cell"] = {k: nb1[k] for k in ("cell_lat", "cell_lon", "dist_km")}

    # --- temperature vs cage sensor
    sensor = sensor_daily()
    (_, oisst, marine, _air) = load_inputs()
    sig = my["thetao"].sizes
    depths = my["depth"].values
    d5 = int(np.argmin(np.abs(depths - 5.0)))
    ser = {"GLORYS12 MY daily 0.49 m": _series(my, "thetao", nb1, 0),
           f"GLORYS12 MY daily {depths[d5]:.1f} m": _series(my, "thetao", nb1, d5)}
    ad, _ = _open(plan, "anfc_thetao_d")
    cells_anfc = _cells(_first_valid_2d(ad, "thetao"), st)
    nb1a = cells_anfc[cells_anfc.station == "NB1"].iloc[0]
    ser["GLO12 anfc daily 0.49 m"] = _series(ad, "thetao", nb1a, 0)
    ser[f"GLO12 anfc daily {ad['depth'].values[d5]:.1f} m"] = _series(ad, "thetao", nb1a, d5)
    hr, _ = _open(plan, "anfc_hourly_sfc")
    cells_hr = _cells(_first_valid_2d(hr, "thetao"), st)
    nb1h = cells_hr[cells_hr.station == "NB1"].iloc[0]
    h = _series(hr, "thetao", nb1h, 0).dropna()
    h.index = pd.DatetimeIndex(h.index).tz_localize("UTC")
    ser["GLO12 anfc hourly -> local day 0.49 m"] = hs.daily_from_hourly(h)
    ser["OISST (NOAA OISST v2.1)"] = oisst
    ser["Open-Meteo marine (best_match)"] = marine
    daily = pd.DataFrame({"sensor": sensor, **ser})
    daily.index.name = "date"
    daily.to_csv(run_dir / "temperature_daily.csv")
    rows = []
    prods = [c for c in daily.columns if c != "sensor"]
    window = daily["sensor"].notnull()
    sets = {"common": daily.dropna(subset=["sensor", *prods])}
    sets["own_overlap"] = daily[window]
    for sname, df in sets.items():
        for p in prods:
            sc = score(df["sensor"], df[p])
            hot = hot_day_counts(df.dropna(subset=["sensor", p])["sensor"], df.dropna(subset=["sensor", p])[p], 31.0)
            rows.append({"set": sname, "product": p, **sc, **{f"ge31_{k}": v for k, v in hot.items()},
                         "first": str(df[["sensor", p]].dropna().index.min().date()) if sc["n"] else "",
                         "last": str(df[["sensor", p]].dropna().index.max().date()) if sc["n"] else ""})
    tskill = pd.DataFrame(rows)
    tskill.to_csv(run_dir / "temperature_skill.csv", index=False)
    out["temperature"] = tskill
    out["n_sensor_days"] = int(sensor.notnull().sum())
    out["ge31_sensor_days_common"] = int((sets["common"]["sensor"] >= 31).sum())

    # --- salinity climatology + low-salinity events (GLORYS12 MY surface)
    clim_rows, ev_rows, oct25 = [], [], []
    so_all = {}
    for c in cells_my.itertuples():
        so = _series(my, "so", c._asdict(), 0).dropna()
        so_all[c.station] = so
        cl = monthly_climatology(so[so.index < "2026-01-01"])
        for m, r in cl.iterrows():
            clim_rows.append({"station": c.station, "month": m, **{k: round(float(r[k]), 3) for k in ("mean", "p05", "p50", "p95", "min", "max")}, "n": int(r["n"])})
        for thr in (25.0, 28.0, 30.0):
            for ev in low_runs(so, thr, min_days=1):
                ev_rows.append({"station": c.station, "threshold_psu": thr, **ev})
        o = so["2025-10-01":"2025-11-15"]
        ref = so[(so.index.month == 10) & (so.index < "2025-01-01")]
        oct25.append({"station": c.station, "min_2025_10_to_11_15": float(o.min()), "min_date": str(o.idxmin().date()),
                      "clim_oct_mean_1993_2024": float(ref.mean()), "clim_oct_p05": float(ref.quantile(0.05)),
                      "clim_oct_min": float(ref.min()), "annual_min_all_years": float(so.min()), "annual_min_date": str(so.idxmin().date())})
    pd.DataFrame(clim_rows).to_csv(run_dir / "salinity_climatology.csv", index=False)
    evdf = pd.DataFrame(ev_rows)
    evdf.to_csv(run_dir / "salinity_low_events.csv", index=False)
    pd.DataFrame(oct25).to_csv(run_dir / "salinity_oct2025_cat_ba.csv", index=False)
    out["sal_events"], out["sal_oct25"] = evdf, pd.DataFrame(oct25)
    out["sal_clim"] = pd.DataFrame(clim_rows)
    # Yagi / Sep-2024 and general freshwater episodes
    yg = []
    for stn, so in so_all.items():
        w = so["2024-08-25":"2024-10-15"]
        yg.append({"station": stn, "min": float(w.min()), "min_date": str(w.idxmin().date()),
                   "aug_mean": float(so["2024-08-01":"2024-08-25"].mean())})
    pd.DataFrame(yg).to_csv(run_dir / "salinity_yagi_sep2024.csv", index=False)
    out["sal_yagi"] = pd.DataFrame(yg)

    # --- Vân Đồn bay Oct 2025
    vd, _ = _open(plan, "vandon_my_ts")
    so_v = vd["so"].isel(depth=0)
    area = so_v.stack(cell=("latitude", "longitude")).dropna("cell", how="all")
    sea_cells = int(area.sizes["cell"])
    clim_mean = so_v.sel(time=slice("1993-01-01", "2024-12-31")).groupby("time.dayofyear").mean("time")
    vrows = []
    for t in pd.date_range("2025-09-15", "2025-11-15"):
        if t not in pd.DatetimeIndex(so_v.time.values):
            continue
        sl = so_v.sel(time=t)
        c0 = clim_mean.sel(dayofyear=t.dayofyear)
        vrows.append({"date": str(t.date()), "area_mean": float(sl.mean()), "area_min": float(sl.min()), "area_max": float(sl.max()),
                      "clim_area_mean_1993_2024": float(c0.mean()), "anomaly_area_mean": float(sl.mean() - c0.mean())})
    vdf = pd.DataFrame(vrows)
    vdf.to_csv(run_dir / "salinity_vandon_2025.csv", index=False)
    out["vandon"] = vdf
    out["vandon_cells"] = sea_cells
    vclim = so_v.sel(time=slice("1993-01-01", "2024-12-31"))
    out["vandon_hist_min"] = float(vclim.min())
    out["vandon_hist_cell_p01"] = float(np.nanpercentile(vclim.values, 1))

    # --- second model: GLO12 analysis salinity, 2022-06 -> (overlaps GLORYS12 MY until 2026-09-22)
    asd, _ = _open(plan, "anfc_so_d")
    cells_as = _cells(_first_valid_2d(asd, "so"), st)
    arows = []
    for c in cells_as.itertuples():
        a = _series(asd, "so", c._asdict(), 0).dropna()
        m = so_all[c.station]
        jj = pd.concat([m.rename("my"), a.rename("anfc")], axis=1).loc["2022-06-01":"2026-09-22"].dropna()
        o_m, o_a = m["2025-10-01":"2025-11-15"], a["2025-10-01":"2025-11-15"]
        arows.append({"station": c.station, "n_overlap": len(jj), "bias_anfc_minus_my": float((jj["anfc"] - jj["my"]).mean()),
                      "r": float(jj["my"].corr(jj["anfc"])), "oct25_min_my": float(o_m.min()), "oct25_min_anfc": float(o_a.min()),
                      "min_anfc_since_2022": float(a.min()), "min_anfc_date": str(a.idxmin().date()),
                      "n_days_lt_30_anfc": int((a < 30).sum()), "n_days_lt_30_my": int((jj["my"] < 30).sum())})
    adf = pd.DataFrame(arows)
    adf.to_csv(run_dir / "salinity_models_compare.csv", index=False)
    out["sal_models"] = adf
    va, _ = _open(plan, "vandon_anfc_so_d")
    sv = va["so"].isel(depth=0).sel(time=slice("2025-09-15", "2025-11-15"))
    out["vandon_anfc"] = {"area_min_oct": float(sv.sel(time=slice("2025-10-01", "2025-10-31")).min()),
                          "area_mean_oct": float(sv.sel(time=slice("2025-10-01", "2025-10-31")).mean()),
                          "area_min_since_2022": float(va["so"].isel(depth=0).min()),
                          "my_area_min_oct": float(so_v.sel(time=slice("2025-10-01", "2025-10-31")).min()),
                          "my_area_mean_oct": float(so_v.sel(time=slice("2025-10-01", "2025-10-31")).mean())}
    # percentile of Oct-2025 Vân Đồn area-mean against all October area-means 1993-2024
    octm = so_v.sel(time=so_v.time.dt.month == 10).mean(("latitude", "longitude")).to_series()
    out["vandon_oct_mean_rank"] = {"oct2025_mean": float(octm["2025-10-01":"2025-10-31"].mean()),
                                   "hist_oct_means_min": float(octm[:"2024-12-31"].groupby(octm[:"2024-12-31"].index.year).mean().min()),
                                   "hist_oct_means_p05": float(octm[:"2024-12-31"].groupby(octm[:"2024-12-31"].index.year).mean().quantile(0.05))}

    # --- waves at Yagi
    wv, _ = _open(plan, "wav")
    cells_w = _cells(wv["VHM0"].isel(time=0), st)
    peaks = pd.read_csv(paths.EXPERIMENT_OUTPUT_DIR / "site-exposure-20261023" / "yagi_peaks.csv")
    sx = pd.read_csv(paths.EXPERIMENT_OUTPUT_DIR / "site-exposure-20261023" / "stations.csv")
    wrows = []
    for c in cells_w.itertuples():
        hs_s = _series(wv, "VHM0", c._asdict()).dropna()
        w = hs_s.loc[YAGI[0]:YAGI[1] + " 23:59"]
        t_hs = w.idxmax() if len(w) else pd.NaT
        tp = _series(wv, "VTPK", c._asdict()).loc[t_hs] if len(w) else np.nan
        p = peaks[peaks.site_id == c.station].set_index("source")
        r = {"station": c.station, "cell_dist_km": c.dist_km, "cmems_hs_max_m": float(w.max()) if len(w) else np.nan,
             "cmems_time_hs_max_utc": str(t_hs), "cmems_tp_at_max_s": float(tp),
             "marine_wave_yagi_max_m_openmeteo": float(sx.loc[sx.site_id == c.station, "marine_wave_yagi_max_m"].iloc[0])}
        for src in ("best_track_radii_floor", "best_track_rankine", "era5_nb1_uniform"):
            r[f"spm_hs_{src}"] = float(p.loc[src, "hs_max_m"]) if src in p.index else np.nan
        wrows.append(r)
    wdf = pd.DataFrame(wrows)
    wdf.to_csv(run_dir / "waves_yagi.csv", index=False)
    out["waves"] = wdf
    # all-time wave stats (2024-01 ->) p99 per station for context
    out["wave_p99"] = {c.station: float(np.nanpercentile(_series(wv, "VHM0", c._asdict()).values, 99)) for c in cells_w.itertuples()}

    # --- currents p95 (hourly surface)
    crow = []
    for c in cells_hr.itertuples():
        u, v = _series(hr, "uo", c._asdict(), 0), _series(hr, "vo", c._asdict(), 0)
        sp = pd.Series(speed(u.values, v.values), index=u.index).dropna()
        yg_sp = sp.loc[YAGI[0]:YAGI[1] + " 23:59"]
        crow.append({"station": c.station, "cell_dist_km": c.dist_km, "n_hours": len(sp), "cmems_p50": float(sp.median()),
                     "cmems_p95": p95(sp.values), "cmems_max": float(sp.max()), "cmems_yagi_max": float(yg_sp.max()) if len(yg_sp) else np.nan})
    cdf = pd.DataFrame(crow)
    sxi = sx.set_index("site_id")
    for col in ("current_p50_ms", "current_p95_ms", "current_max_ms", "current_yagi_max_ms"):
        cdf[f"smoc_{col}"] = cdf.station.map(sxi[col])
    cdf.to_csv(run_dir / "currents_p95.csv", index=False)
    out["currents"] = cdf
    # cross-station summaries (14 stations share only 8 CMEMS cells, so n_eff is smaller)
    out["summary"] = {
        "wave_yagi": {src: {"mean_spm_m": float(wdf[f"spm_hs_{src}"].mean()), "pearson_vs_cmems": float(wdf["cmems_hs_max_m"].corr(wdf[f"spm_hs_{src}"])),
                            "spearman_vs_cmems": float(wdf["cmems_hs_max_m"].corr(wdf[f"spm_hs_{src}"], method="spearman")),
                            "mean_bias_spm_minus_cmems_m": float((wdf[f"spm_hs_{src}"] - wdf["cmems_hs_max_m"]).mean())}
                      for src in ("best_track_radii_floor", "best_track_rankine", "era5_nb1_uniform")},
        "wave_yagi_cmems_mean_m": float(wdf["cmems_hs_max_m"].mean()), "wave_yagi_cmems_min_max_m": [float(wdf["cmems_hs_max_m"].min()), float(wdf["cmems_hs_max_m"].max())],
        "wave_yagi_openmeteo_mean_m": float(wdf["marine_wave_yagi_max_m_openmeteo"].mean()),
        "wave_p99_m": out["wave_p99"],
        "current_p95": {"cmems_mean": float(cdf["cmems_p95"].mean()), "smoc_mean": float(cdf["smoc_current_p95_ms"].mean()),
                        "ratio_cmems_over_smoc": float((cdf["cmems_p95"] / cdf["smoc_current_p95_ms"]).mean()),
                        "pearson": float(cdf["cmems_p95"].corr(cdf["smoc_current_p95_ms"])),
                        "spearman": float(cdf["cmems_p95"].corr(cdf["smoc_current_p95_ms"], method="spearman"))},
        "n_distinct_cells": {"glorys12": int(cells_my[["cell_lat", "cell_lon"]].drop_duplicates().shape[0]),
                             "wave": int(cells_w[["cell_lat", "cell_lon"]].drop_duplicates().shape[0]),
                             "glo12_hourly": int(cells_hr[["cell_lat", "cell_lon"]].drop_duplicates().shape[0])},
        "cell_dist_km_glorys12": {"min": float(cells_my.dist_km.min()), "max": float(cells_my.dist_km.max())},
        "vandon_anfc": out["vandon_anfc"], "vandon_oct_mean_rank": out["vandon_oct_mean_rank"],
        "vandon_cells": out["vandon_cells"], "vandon_hist_min_1993_2024": out["vandon_hist_min"],
        "sal_events_count": {str(t): int((evdf["threshold_psu"] == t).sum()) if len(evdf) else 0 for t in (25.0, 28.0, 30.0)},
        "sal_global_min_my_surface": float(min(s.min() for s in so_all.values())),
    }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--download", action="store_true", help="fetch missing subsets, then stop")
    ap.add_argument("--stamp", default=None)
    ap.add_argument("--end", default="2026-10-22")
    ap.add_argument("--my-end", default="2026-09-22")
    args = ap.parse_args(argv)
    plan = download_plan(args.end, args.my_end)
    if args.download:
        download_missing(plan)
        return 0
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / f"cmems-sites-{args.stamp or '20261024'}"
    run_dir.mkdir(parents=True, exist_ok=False)
    res = run_analysis(plan, run_dir)
    files = [target_path(p) for p in plan]
    manifest = {"run": run_dir.name, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "inputs": [{"file": str(f.relative_to(paths.CMEMS_DIR)), "sha256": hashlib.sha256(f.read_bytes()).hexdigest()} for f in files],
                "products": sorted({p["product_id"] for p in plan}), "models": sorted({p["model"] for p in plan}),
                "nb1_cell": {k: float(v) for k, v in res["nb1_cell"].items()}, "convention": "bias = product - sensor; local day for sensor, UTC day for daily products unless stated",
                **BASIS}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(res["summary"], ensure_ascii=False, indent=2), encoding="utf-8")
    pd.set_option("display.width", 250, "display.max_columns", 40)
    for k in ("temperature", "sal_models", "waves", "currents"):
        print(f"\n== {k}\n{res[k].round(3).to_string()}")
    ev = res["sal_events"]
    print("\nsal events (<25/<28/<30):", [int((ev["threshold_psu"] == t).sum()) if len(ev) else 0 for t in (25.0, 28.0, 30.0)],
          "| vandon cells:", res["vandon_cells"], "| vandon hist min:", round(res["vandon_hist_min"], 2))
    print(res["vandon"].round(2).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
