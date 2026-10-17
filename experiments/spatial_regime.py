"""H4.1 / A6 — salinity-regime layer for Hai Phong (HP) + Quang Ninh (QN) and a
regime-split rerun of the P0/P1 spatial-applicability benchmark.

Research only (``scope: research_only``, ``not_for_runtime``). Nothing here feeds
alerts, the shadow runner or the research map.

Inputs (read-only): ``paths.clean_data("haiphong"|"quangninh")`` (periodic
provincial monitoring; the ``Quarter`` column is a sampling-round month, day = 1
placeholder), ``paths.STATION_COORDINATES`` (HP WGS84 reference),
``paths.WATER_SHAPEFILE`` (OSM water polygons).

Key data facts handled explicitly
* Coordinates are VN-2000 TM-3 with X = northing, Y = easting; central meridian is
  per province (HP 105 deg 45', QN 107 deg 45'). ``vn2000_to_wgs84`` takes lon_0.
* HP ``Salinity``/``Temperature`` are *model-derived gridded* values (identical
  series for stations sharing a 1/12 deg GLORYS cell, 14-decimal floats). They are
  labelled ``model_derived_gridded`` and kept out of headline pass counts. HP
  DO/pH/TSS/NH3 are treated as observed.
* QN stations whose WGS84 point falls outside the province bounding box (NB74,
  NB78: northing ~200 km too small) are ``coordinate_suspect`` and excluded from
  every distance-based step. QN DO > 20 mg/L (one 60.5) is screened as a typo.

Regime: wet season = May-Oct (northern VN monsoon); with quarterly sampling the
wet samples are the Jul/Oct rounds (QN) and Jun/Aug/Oct (HP). Classes on the
wet-season median salinity: estuarine/brackish < 20 psu, transitional 20-28,
marine >= 28. Pair label as RL-14: |delta wet median| < 2 psu -> same regime.

Transfer benchmark (within a province; same sampling round):
* estimate(target, round) = anchor value (``anchor_copy``). The HSI estimate is
  computed from the anchor row only (fixes ``diagnostic_only_observed_hsi_leakage``;
  the legacy radius rule, which reads target HSI, is dropped).
* Tolerances as HK/RL-14 (Temp 0.5, Sal 1, DO 0.5, pH 0.2, TSS max(2,20 %),
  NH3 max(0.005,30 %)); HSI: same suitability label.
* Gates 80/90/95: lower bound of a percentile bootstrap that resamples target
  sampling dates, >= 30 dates (strict). HP has 22 rounds and QN 16, so the strict
  gate is ``insufficient`` everywhere by construction; a ``diagnostic_relaxed``
  view with >= 10 dates is reported and never called a pass.
* P1 conformal gate of ``spatial_applicability.spatial_gate_summary`` (>= 30 pairs,
  both outer protocols, 10 km research cap) rerun per regime relation, for the
  like-for-like comparison with the old 1/36.
* Climatology baseline: target's own same-month median over *other* years
  (leave-one-year-out, >= 2 other years). Compared on common rows.

Run:  .venv\\Scripts\\python experiments\\spatial_regime.py
Outputs: artifacts/experiments/vn-salinity-regime-h41-20261017/ (refuses to overwrite).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import paths  # noqa: E402
from experiments import spatial_applicability as sa  # noqa: E402
from experiments.nerrs_reliability import (  # noqa: E402
    bootstrap_share,
    bootstrap_share_difference,
    gate_status,
    prepare_output_dir,
    sha256,
)

RUN_NAME = "vn-salinity-regime-h41-20261017"
SCOPE = {"scope": "research_only", "not_for_runtime": True, "used_by_alerts": False}
REGIONS = ("haiphong", "quangninh")
PROVINCE_LON0 = {"haiphong": 105.75, "quangninh": 107.75}
# Same datum shift as hap_shared/preprocessing.py (only lon_0 differs per province).
TOWGS84 = "-191.90441429,-39.30318279,-111.45032835,0.00928836,-0.01975479,0.00427372,0.252906278"
# (min_lon, min_lat, max_lon, max_lat): generous coastal boxes for the sanity check.
PROVINCE_BBOX = {"haiphong": (106.40, 20.50, 107.30, 21.10), "quangninh": (106.60, 20.60, 108.15, 21.65)}
MODEL_DERIVED = {"haiphong": ("Salinity", "Temperature")}
SCREENS = {"DO": (0.0, 20.0)}
VARIABLES = ("Temperature", "Salinity", "pH", "DO", "TSS", "NH3")
WET_MONTHS = (5, 6, 7, 8, 9, 10)
CLASS_CUTS = (20.0, 28.0)
REGIME_DSAL_PSU = 2.0
NB1_LIVE = ("haiphong", "NB1")
TOLERANCES = {"Temperature": (0.5, 0.0), "Salinity": (1.0, 0.0), "DO": (0.5, 0.0), "pH": (0.2, 0.0),
              "TSS": (2.0, 0.20), "NH3": (0.005, 0.30)}
GATES = (0.80, 0.90, 0.95)
MIN_DATES = 30
RELAXED_MIN_DATES = 10
N_BOOT = 1000
SEED = 20261017
CLIM_MIN_OTHER_YEARS = 2
BIN_EDGES = [0, 2, 5, 10, 20, np.inf]
BIN_LABELS = ["0-2", "2-5", "5-10", "10-20", ">20"]
LAYER_STEP_M = 1000.0
LAYER_MAX_ASSIGN_KM = 10.0
IDW_RADIUS_KM = 20.0
WATER_TOLERANCE_M = 500.0
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32648", always_xy=True)
TO_WGS = Transformer.from_crs("EPSG:32648", "EPSG:4326", always_xy=True)


# ---------------------------------------------------------------- coordinates
def vn2000_to_wgs84(x_northing, y_easting, lon_0: float) -> tuple[np.ndarray, np.ndarray]:
    """VN-2000 TM-3 (X = northing, Y = easting) -> WGS84 (lat, lon) for a given central meridian."""
    proj = (f"+proj=tmerc +lat_0=0 +lon_0={lon_0} +k=0.9999 +x_0=500000 +y_0=0 +ellps=WGS84 "
            f"+towgs84={TOWGS84} +units=m +no_defs")
    transformer = Transformer.from_crs(proj, "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(np.asarray(y_easting, float), np.asarray(x_northing, float))
    return np.asarray(lat, float), np.asarray(lon, float)


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(a))


def in_bbox(lat, lon, bbox) -> np.ndarray:
    min_lon, min_lat, max_lon, max_lat = bbox
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    return (lon >= min_lon) & (lon <= max_lon) & (lat >= min_lat) & (lat <= max_lat)


def water_geometry_utm(bbox):
    """OSM water polygons intersecting ``bbox`` (WGS84), projected to UTM 48N."""
    import shapefile
    from shapely.geometry import box, shape
    from shapely.ops import transform, unary_union
    reader = shapefile.Reader(str(paths.WATER_SHAPEFILE))
    shapes = [shape(s.__geo_interface__) for s in reader.iterShapes(bbox=bbox)]
    if not shapes:
        return None
    import shapely
    water = unary_union(shapes).intersection(box(*bbox))
    water = transform(lambda x, y, z=None: TO_UTM.transform(x, y), water)
    shapely.prepare(water)
    return water


def distance_to_water_m(lat, lon, water_utm) -> np.ndarray:
    from shapely import contains_xy, distance, points
    x, y = TO_UTM.transform(np.asarray(lon, float), np.asarray(lat, float))
    inside = contains_xy(water_utm, x, y)
    dist = distance(water_utm, points(x, y))
    return np.where(inside, 0.0, dist)


# ---------------------------------------------------------------- loading
def load_region(region: str, source: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """Long-format-free tidy table: one row per (station, sampling round)."""
    frame = pd.read_csv(paths.clean_data(region)) if source is None else source.copy()
    frame = frame.rename(columns={"Station": "station", "Station_Name": "station_name"})
    frame["station"] = frame["station"].astype(str)
    frame["date"] = pd.to_datetime(frame["Quarter"], errors="coerce")
    frame = frame.dropna(subset=["date", "X", "Y"]).copy()
    frame["region"] = region
    lat, lon = vn2000_to_wgs84(frame["X"], frame["Y"], PROVINCE_LON0[region])
    frame["lat"], frame["lon"] = lat, lon
    frame["coordinate_suspect"] = ~in_bbox(lat, lon, PROVINCE_BBOX[region])
    screened = {}
    for var, (low, high) in SCREENS.items():
        if var in frame:
            values = pd.to_numeric(frame[var], errors="coerce")
            bad = (values < low) | (values > high)
            screened[var] = int(bad.sum())
            frame[var] = values.where(~bad)
    for var in VARIABLES:
        if var in frame:
            frame[var] = pd.to_numeric(frame[var], errors="coerce")
    return frame, {"region": region, "screened_out_of_range": screened}


def gridded_evidence(frame: pd.DataFrame, variables=VARIABLES) -> pd.DataFrame:
    """Per variable: station pairs with fully identical co-sampled series (grid-cell sharing)."""
    rows = []
    for var in variables:
        if var not in frame:
            continue
        pivot = frame.pivot_table(index="date", columns="station", values=var, aggfunc="first")
        stations = list(pivot.columns)
        identical = []
        for i, a in enumerate(stations):
            for b in stations[i + 1:]:
                both = pivot[[a, b]].dropna()
                if len(both) >= 3 and (both[a] == both[b]).all():
                    identical.append(f"{a}={b}")
        decimals = frame[var].dropna().map(lambda v: len(repr(float(v)).split(".")[1]) if "." in repr(float(v)) else 0)
        rows.append({"region": frame["region"].iloc[0], "variable": var, "n_identical_station_pairs": len(identical),
                     "identical_pairs": ";".join(identical), "median_decimals": float(decimals.median()),
                     "label": ("model_derived_gridded" if var in MODEL_DERIVED.get(frame["region"].iloc[0], ())
                               else "observed")})
    return pd.DataFrame(rows)


def station_inventory(frame: pd.DataFrame, water_utm=None) -> pd.DataFrame:
    region = frame["region"].iloc[0]
    rows = []
    for station, grp in frame.groupby("station", sort=True):
        dates = grp["date"].drop_duplicates().sort_values()
        steps = dates.diff().dt.days.dropna()
        observed = [v for v in VARIABLES if v in grp and grp[v].notna().any()
                    and v not in MODEL_DERIVED.get(region, ())]
        rows.append({
            "region": region, "station": station, "station_name": grp.get("station_name", pd.Series([""])).iloc[0],
            "x_northing": float(grp["X"].iloc[0]), "y_easting": float(grp["Y"].iloc[0]),
            "lon_0": PROVINCE_LON0[region], "lat": float(grp["lat"].iloc[0]), "lon": float(grp["lon"].iloc[0]),
            "n_coordinate_variants": int(grp[["X", "Y"]].drop_duplicates().shape[0]),
            "coordinate_suspect": bool(grp["coordinate_suspect"].iloc[0]),
            "first": dates.min().date().isoformat(), "last": dates.max().date().isoformat(),
            "n_dates": int(len(dates)), "median_interval_days": float(steps.median()) if len(steps) else np.nan,
            "observed_parameters": ";".join(observed),
            "salinity_source": "model_derived_gridded" if "Salinity" in MODEL_DERIVED.get(region, ()) else "observed",
            "n_salinity": int(grp["Salinity"].notna().sum()) if "Salinity" in grp else 0,
        })
    inv = pd.DataFrame(rows)
    if water_utm is not None and not inv.empty:
        inv["distance_to_water_m"] = distance_to_water_m(inv["lat"], inv["lon"], water_utm).round(1)
        inv["in_water_or_coast"] = inv["distance_to_water_m"] <= WATER_TOLERANCE_M
    return inv


# ---------------------------------------------------------------- regime
def season_of(dates) -> np.ndarray:
    return np.where(pd.DatetimeIndex(dates).month.isin(WET_MONTHS), "wet", "dry")


def classify_regime(wet_median) -> np.ndarray:
    values = np.asarray(wet_median, float)
    out = np.where(values < CLASS_CUTS[0], "estuarine_brackish",
                   np.where(values < CLASS_CUTS[1], "transitional", "marine"))
    return np.where(np.isfinite(values), out, "unknown")


def monthly_salinity(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.dropna(subset=["Salinity"]).assign(month=lambda d: d["date"].dt.month)
    out = work.groupby("month")["Salinity"].agg(["count", "median", "mean", "min"]).reset_index()
    out["season"] = np.where(out["month"].isin(WET_MONTHS), "wet", "dry")
    out["region"] = frame["region"].iloc[0]
    return out


def station_regime(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.dropna(subset=["Salinity"]).assign(season=lambda d: season_of(d["date"]))
    g = work.groupby(["station", "season"])["Salinity"].agg(["median", "count"]).unstack("season")
    out = pd.DataFrame({
        "station": g.index,
        "wet_median_sal": g[("median", "wet")].to_numpy() if ("median", "wet") in g else np.nan,
        "dry_median_sal": g[("median", "dry")].to_numpy() if ("median", "dry") in g else np.nan,
        "n_wet": g[("count", "wet")].fillna(0).astype(int).to_numpy() if ("count", "wet") in g else 0,
        "n_dry": g[("count", "dry")].fillna(0).astype(int).to_numpy() if ("count", "dry") in g else 0,
    })
    out["regime_class"] = classify_regime(out["wet_median_sal"])
    region = frame["region"].iloc[0]
    out["region"] = region
    out["salinity_source"] = "model_derived_gridded" if "Salinity" in MODEL_DERIVED.get(region, ()) else "observed"
    meta = frame.groupby("station")[["lat", "lon", "coordinate_suspect"]].first()
    return out.merge(meta, left_on="station", right_index=True, how="left")


def regime_relation(wet_a, wet_t, threshold: float = REGIME_DSAL_PSU) -> np.ndarray:
    diff = np.abs(np.asarray(wet_a, float) - np.asarray(wet_t, float))
    return np.where(~np.isfinite(diff), "unknown", np.where(diff < threshold, "same_regime", "different_regime"))


def nearest_observed(stations: pd.DataFrame, lat: float, lon: float, k: int = 6) -> pd.DataFrame:
    obs = stations[(stations["salinity_source"] == "observed") & ~stations["coordinate_suspect"]].copy()
    obs["distance_km"] = haversine_km(lat, lon, obs["lat"], obs["lon"]).round(2)
    return obs.sort_values("distance_km").head(k)


# ---------------------------------------------------------------- layer
def regime_layer(stations: pd.DataFrame, water_utm, *, step_m: float = LAYER_STEP_M,
                 max_assign_km: float = LAYER_MAX_ASSIGN_KM, idw_radius_km: float = IDW_RADIUS_KM) -> pd.DataFrame:
    """Water-masked UTM grid: nearest observed station (<= max_assign_km) + IDW of observed wet medians."""
    from shapely import contains_xy
    usable = stations[~stations["coordinate_suspect"] & stations["wet_median_sal"].notna()].copy()
    sx, sy = TO_UTM.transform(usable["lon"].to_numpy(float), usable["lat"].to_numpy(float))
    usable["ux"], usable["uy"] = sx, sy
    pad = 15_000.0
    gx = np.arange(sx.min() - pad, sx.max() + pad + step_m, step_m)
    gy = np.arange(sy.min() - pad, sy.max() + pad + step_m, step_m)
    xx, yy = np.meshgrid(gx, gy)
    xx, yy = xx.ravel(), yy.ravel()
    keep = contains_xy(water_utm, xx, yy)
    xx, yy = xx[keep], yy[keep]
    lon, lat = TO_WGS.transform(xx, yy)
    out = pd.DataFrame({"cell_x_utm48n": xx.round(1), "cell_y_utm48n": yy.round(1),
                        "lon": np.round(lon, 6), "lat": np.round(lat, 6)})
    for source, prefix in (("observed", "obs"), ("model_derived_gridded", "model")):
        part = usable[usable["salinity_source"] == source]
        if part.empty:
            continue
        d = np.hypot(xx[:, None] - part["ux"].to_numpy()[None, :], yy[:, None] - part["uy"].to_numpy()[None, :]) / 1000
        idx = d.argmin(axis=1)
        near_d = d[np.arange(len(xx)), idx]
        out[f"nearest_{prefix}_station"] = (part["region"].to_numpy()[idx] + ":" + part["station"].to_numpy()[idx])
        out[f"nearest_{prefix}_km"] = near_d.round(2)
        wet = part["wet_median_sal"].to_numpy()[idx]
        out[f"nearest_{prefix}_wet_median_sal"] = np.round(wet, 2)
        out[f"nearest_{prefix}_regime_class"] = np.where(near_d <= max_assign_km, classify_regime(wet), "unassigned")
        if source == "observed":
            with np.errstate(divide="ignore", invalid="ignore"):
                w = np.where(d <= idw_radius_km, 1.0 / np.maximum(d, 0.05) ** 2, 0.0)
                idw = (w * part["wet_median_sal"].to_numpy()[None, :]).sum(1) / w.sum(1)
            out["idw_obs_wet_median_sal"] = np.round(idw, 2)
            out["idw_obs_regime_class"] = classify_regime(idw)
    out["regime_class"] = out.get("nearest_obs_regime_class", pd.Series("unassigned", index=out.index))
    out["regime_basis"] = np.where(out["regime_class"] != "unassigned", "nearest_observed_station", "no_observed_station_within_10km")
    for key, value in SCOPE.items():
        out[key] = value
    return out


def to_geojson(frame: pd.DataFrame, properties: list[str], meta: dict) -> dict:
    features = []
    for row in frame.itertuples(index=False):
        props = {}
        for p in properties:
            v = getattr(row, p)
            props[p] = (None if isinstance(v, float) and not np.isfinite(v) else
                        v.item() if isinstance(v, np.generic) else v)
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(row.lon), float(row.lat)]},
                         "properties": props})
    return {"type": "FeatureCollection", "metadata": meta, "features": features}


# ---------------------------------------------------------------- transfer rows
def within_tolerance(var: str, estimate, observed) -> np.ndarray:
    absolute, relative = TOLERANCES[var]
    observed = np.asarray(observed, float)
    bound = np.maximum(absolute, relative * np.abs(observed))
    return np.abs(observed - np.asarray(estimate, float)) <= bound + 1e-12


def distance_bin(km) -> np.ndarray:
    return pd.cut(np.asarray(km, float), BIN_EDGES, labels=BIN_LABELS, right=False).astype(str)


def anchor_hsi(anchor_values: pd.DataFrame) -> pd.Series:
    """HSI from the anchor row only (no target column is visible to this function)."""
    cols = [c for c in sa.COBIA_RULES if c in anchor_values.columns]
    return anchor_values[cols].apply(sa.cobia_hsi, axis=1)


def transfer_rows(frame: pd.DataFrame, regimes: pd.DataFrame, variables) -> pd.DataFrame:
    """One row per (variable, anchor, target, round): estimate = anchor value, truth = target value."""
    usable = frame[~frame["coordinate_suspect"]]
    cols = [v for v in variables if v in usable.columns]
    hsi_cols = [c for c in sa.COBIA_RULES if c in usable.columns]
    base = usable[["station", "date", "X", "Y"] + sorted(set(cols) | set(hsi_cols))].drop_duplicates(["station", "date"])
    anchor = base.add_prefix("a_").rename(columns={"a_date": "date"})
    # Estimator input is built from anchor columns only, before any join to the target.
    anchor["a_HSI"] = anchor_hsi(anchor[[f"a_{c}" for c in hsi_cols]].rename(columns=lambda c: c[2:]))
    target = base.add_prefix("t_").rename(columns={"t_date": "date"})
    target["t_HSI"] = target[[f"t_{c}" for c in hsi_cols]].rename(columns=lambda c: c[2:]).apply(sa.cobia_hsi, axis=1)
    m = anchor.merge(target, on="date")
    m = m[m["a_station"] != m["t_station"]]
    m["distance_km"] = sa_distance(m)
    wet = regimes.set_index("station")["wet_median_sal"]
    m["wet_diff_psu"] = (m["a_station"].map(wet) - m["t_station"].map(wet)).abs().round(3)
    m["regime_relation"] = regime_relation(m["a_station"].map(wet), m["t_station"].map(wet))
    parts = []
    for var in cols + ["HSI"]:
        r = m[["date", "a_station", "t_station", "distance_km", "wet_diff_psu", "regime_relation",
               f"a_{var}", f"t_{var}"]].dropna(subset=[f"a_{var}", f"t_{var}"])
        r = r.rename(columns={"a_station": "anchor", "t_station": "target", f"a_{var}": "estimate", f"t_{var}": "y"})
        if var == "HSI":
            al, tl = r["estimate"].map(sa.hsi_label), r["y"].map(sa.hsi_label)
            within = (al == tl).to_numpy()
            r = r.assign(false_favourable=(al.isin(["very_suitable", "suitable"]) & ~tl.isin(["very_suitable", "suitable"])).to_numpy())
        else:
            within = within_tolerance(var, r["estimate"], r["y"])
        parts.append(r.assign(variable=var, err=r["y"] - r["estimate"], within=within))
    rows = pd.concat(parts, ignore_index=True)
    rows["region"] = frame["region"].iloc[0]
    rows["distance_bin"] = distance_bin(rows["distance_km"])
    rows["season"] = season_of(rows["date"])
    rows = rows.rename(columns={"date": "target_date"})
    return rows


def sa_distance(m: pd.DataFrame) -> np.ndarray:
    """Within-province Euclidean on projected VN-2000 metres (as spatial_applicability.distance_km)."""
    return (np.hypot(m["a_X"].to_numpy(float) - m["t_X"].to_numpy(float),
                     m["a_Y"].to_numpy(float) - m["t_Y"].to_numpy(float)) / 1000.0).round(3)


def climatology_loyo(frame: pd.DataFrame, variables, min_other_years: int = CLIM_MIN_OTHER_YEARS) -> pd.DataFrame:
    """Target's own same-month median over the *other* years (leave-one-year-out)."""
    out = []
    for var in variables:
        if var not in frame:
            continue
        o = frame[["station", "date", var]].dropna().drop_duplicates(["station", "date"]).copy()
        o["year"], o["month"] = o["date"].dt.year, o["date"].dt.month
        est = pd.Series(np.nan, index=o.index)
        for _, grp in o.groupby(["station", "month"]):
            years, values = grp["year"].to_numpy(), grp[var].to_numpy(float)
            for i, idx in enumerate(grp.index):
                other = years != years[i]
                if len(np.unique(years[other])) >= min_other_years:
                    est[idx] = np.median(values[other])
        out.append(pd.DataFrame({"variable": var, "target": o["station"], "target_date": o["date"], "clim": est}))
    return pd.concat(out, ignore_index=True).dropna(subset=["clim"])


# ---------------------------------------------------------------- summaries
def summarise_cells(rows: pd.DataFrame, keys, n_boot: int = N_BOOT, seed: int = SEED) -> pd.DataFrame:
    out = []
    for cell, grp in rows.groupby(keys, observed=True, sort=True):
        per_date = grp.groupby("target_date")["within"].agg(["sum", "count"])
        share, lo, hi = bootstrap_share(per_date["sum"], per_date["count"], n_boot=n_boot, seed=seed)
        abs_err = grp["err"].abs()
        rec = dict(zip(keys, cell if isinstance(cell, tuple) else (cell,)))
        rec.update({"n_rows": int(len(grp)), "n_dates": int(len(per_date)), "n_pairs": int(grp[["anchor", "target"]].drop_duplicates().shape[0]),
                    "mae": round(float(abs_err.mean()), 4), "share_within": round(share, 4),
                    "share_ci_lo": round(lo, 4), "share_ci_hi": round(hi, 4)})
        if "false_favourable" in grp and grp["false_favourable"].notna().any():
            rec["false_favourable_rate"] = round(float(grp["false_favourable"].astype(float).mean()), 4)
        for g in GATES:
            rec[f"gate_{int(g * 100)}"] = gate_status(lo, len(per_date), g, min_days=MIN_DATES)
            rec[f"diagnostic_relaxed_{int(g * 100)}"] = gate_status(lo, len(per_date), g, min_days=RELAXED_MIN_DATES)
        out.append(rec)
    return pd.DataFrame(out)


def climatology_comparison(rows: pd.DataFrame, clim: pd.DataFrame, keys) -> pd.DataFrame:
    """Anchor copy vs the target's own leave-one-year-out climatology, on common rows."""
    r = rows[rows["variable"] != "HSI"].merge(clim, on=["variable", "target", "target_date"], how="inner")
    if r.empty:
        return pd.DataFrame()
    clim_within = np.zeros(len(r), dtype=bool)
    for var, idx in r.groupby("variable").indices.items():
        clim_within[idx] = within_tolerance(var, r["clim"].to_numpy()[idx], r["y"].to_numpy()[idx])
    r["clim_within"] = clim_within
    out = []
    for cell, grp in r.groupby(keys, observed=True, sort=True):
        per_date = grp.groupby("target_date").agg(a=("within", "sum"), c=("clim_within", "sum"), n=("within", "size"))
        diff, lo, hi = bootstrap_share_difference(per_date["a"], per_date["n"], per_date["c"], per_date["n"],
                                                  n_boot=N_BOOT, seed=SEED)
        rec = dict(zip(keys, cell if isinstance(cell, tuple) else (cell,)))
        rec.update({"n_rows": int(len(grp)), "n_dates": int(len(per_date)),
                    "anchor_share_within": round(float(grp["within"].mean()), 4),
                    "clim_share_within": round(float(grp["clim_within"].mean()), 4),
                    "anchor_mae": round(float(grp["err"].abs().mean()), 4),
                    "clim_mae": round(float((grp["y"] - grp["clim"]).abs().mean()), 4),
                    "share_diff_anchor_minus_clim": round(diff, 4), "diff_ci_lo": round(lo, 4), "diff_ci_hi": round(hi, 4),
                    "anchor_beats_climatology": bool(lo > 0)})
        out.append(rec)
    return pd.DataFrame(out)


def _fast_quantile_bound(train: pd.DataFrame, calibration: pd.DataFrame, test: pd.DataFrame, *, coverage: float) -> pd.DataFrame:
    """Vectorised equivalent of ``spatial_applicability._fit_quantile_bound``.

    The original looks up an IntervalIndex per row, which is too slow for 97
    leave-target-station-out folds on QN. Bins are mapped through their string
    label instead; the numbers are identical (asserted in the unit tests).
    """
    global_bound = float(np.quantile(train.absolute_error, coverage))
    per_bin = train.groupby(train.distance_bin_km.astype(str), observed=True).absolute_error.agg(
        lambda values: float(np.quantile(values, coverage)) if len(values) >= 20 else global_bound)

    def predict_bound(frame: pd.DataFrame) -> np.ndarray:
        return frame.distance_bin_km.astype(str).map(per_bin).fillna(global_bound).to_numpy(float)

    calibration_bound = predict_bound(calibration)
    correction = float(np.quantile(calibration.absolute_error.to_numpy(float) - calibration_bound, coverage, method="higher"))
    correction = max(0.0, correction)
    output = test.copy()
    output["model_bound"] = np.maximum(0.0, predict_bound(test) + correction)
    output["fixed_calibration_bound"] = float(np.quantile(calibration.absolute_error, coverage))
    output["conformal_correction"] = correction
    output["coverage_target"] = coverage
    return output


def fast_error_bound_benchmarks(pairs: pd.DataFrame, targets, *, coverages=(.8, .9, .95)) -> pd.DataFrame:
    """Same two outer protocols as ``spatial_applicability.error_bound_benchmarks`` (metrics only)."""
    metrics = []
    for parameter in targets:
        work = pairs.loc[pairs.parameter.eq(parameter)]
        if work.empty:
            continue
        for coverage in coverages:
            # forward temporal 60/20/20 on sampling rounds
            periods = np.array(sorted(work.observed_at.unique()))
            if len(periods) >= 5:
                train_end, cal_end = max(1, int(len(periods) * .6)), max(2, int(len(periods) * .8))
                train = work.loc[work.observed_at.isin(periods[:train_end])]
                cal = work.loc[work.observed_at.isin(periods[train_end:cal_end])]
                test = work.loc[work.observed_at.isin(periods[cal_end:])]
                if min(len(train), len(cal), len(test)) >= 20:
                    pred = _fast_quantile_bound(train, cal, test, coverage=coverage)
                    metrics += sa._bound_metrics(pred, split="forward_temporal", parameter=parameter, coverage=coverage)
            # leave target station out
            outputs = []
            for held in sorted(work.target_station.unique()):
                test = work.loc[work.target_station.eq(held)]
                pool = work.loc[~work.target_station.eq(held)].sort_values("observed_at")
                boundary = max(1, int(len(pool) * .8))
                train, cal = pool.iloc[:boundary], pool.iloc[boundary:]
                if min(len(train), len(cal), len(test)) < 20:
                    continue
                outputs.append(_fast_quantile_bound(train, cal, test, coverage=coverage))
            if outputs:
                pred = pd.concat(outputs, ignore_index=True)
                metrics += sa._bound_metrics(pred, split="leave_target_station_out", parameter=parameter, coverage=coverage)
    return pd.DataFrame(metrics)


def conformal_gates(frame: pd.DataFrame, regimes: pd.DataFrame, variables) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Old P1 conformal gate (spatial_applicability) rerun per regime relation."""
    src = frame[~frame["coordinate_suspect"]].rename(columns={"station": "Station"}).assign(observed_at=lambda d: pd.to_datetime(d["date"], utc=True))
    pairs = [sa.pairwise_anchor_copy(src, v) for v in variables if v in src]
    pairs = pd.concat([p for p in pairs if not p.empty], ignore_index=True)
    wet = regimes.set_index("station")["wet_median_sal"]
    pairs["regime_relation"] = regime_relation(pairs["anchor_station"].map(wet), pairs["target_station"].map(wet))
    gates, metrics = [], []
    for relation in ("all", "same_regime", "different_regime"):
        part = pairs if relation == "all" else pairs[pairs["regime_relation"] == relation]
        if part.empty:
            continue
        m = fast_error_bound_benchmarks(part, list(variables))
        g = sa.spatial_gate_summary(m)
        if not g.empty:
            gates.append(g.assign(regime_relation=relation, n_dates=int(part["observed_at"].nunique())))
        if not m.empty:
            metrics.append(m.assign(regime_relation=relation))
    gate = pd.concat(gates, ignore_index=True) if gates else pd.DataFrame()
    metric = pd.concat(metrics, ignore_index=True) if metrics else pd.DataFrame()
    if not gate.empty:
        gate["distance_bin_km"] = gate["distance_bin_km"].astype(str)
        gate["note"] = "pair_count_gate;pairs_within_a_round_are_not_independent_dates"
    return gate, metric


def pass_counts(cells: pd.DataFrame, conformal: pd.DataFrame, region: str, model_vars) -> pd.DataFrame:
    rows = []
    if not cells.empty:
        for (var, relation), grp in cells.groupby(["variable", "regime_relation"]):
            for g in GATES:
                k = int(g * 100)
                rows.append({"region": region, "protocol": "tolerance_dayblock_bootstrap", "variable": var,
                             "regime_relation": relation, "coverage": g, "n_cells": len(grp),
                             "n_pass_strict": int((grp[f"gate_{k}"] == "pass").sum()),
                             "n_insufficient_strict": int((grp[f"gate_{k}"] == "insufficient").sum()),
                             "n_relaxed_diagnostic_pass": int((grp[f"diagnostic_relaxed_{k}"] == "pass").sum()),
                             "model_derived": var in model_vars})
    if not conformal.empty:
        for (var, relation, cov), grp in conformal.groupby(["parameter", "regime_relation", "coverage_target"]):
            rows.append({"region": region, "protocol": "p1_conformal_pair_gate", "variable": var,
                         "regime_relation": relation, "coverage": cov, "n_cells": len(grp),
                         "n_pass_strict": int((grp["gate_status"] == "shadow_candidate").sum()),
                         "n_insufficient_strict": np.nan, "n_relaxed_diagnostic_pass": np.nan,
                         "model_derived": var in model_vars})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- main
def reference_check(hp_inventory: pd.DataFrame) -> pd.DataFrame:
    """HP conversion residual against data/map/station_coordinates.csv (independent WGS84 copy)."""
    if not paths.STATION_COORDINATES.exists():
        return pd.DataFrame()
    ref = pd.read_csv(paths.STATION_COORDINATES, usecols=["Station", "Lat", "Lon"]).rename(columns={"Station": "station"})
    m = hp_inventory.merge(ref, on="station")
    m["residual_m_lon0_105_75"] = (haversine_km(m["lat"], m["lon"], m["Lat"], m["Lon"]) * 1000).round(2)
    lat_w, lon_w = vn2000_to_wgs84(m["x_northing"], m["y_easting"], 107.75)
    m["residual_km_if_lon0_107_75"] = haversine_km(lat_w, lon_w, m["Lat"], m["Lon"]).round(1)
    return m[["station", "lat", "lon", "Lat", "Lon", "residual_m_lon0_105_75", "residual_km_if_lon0_107_75"]]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME)
    args = parser.parse_args(argv)
    out = prepare_output_dir(args.output_dir)

    frames, screens = {}, []
    for region in REGIONS:
        frames[region], s = load_region(region)
        screens.append(s)
    all_lat = np.concatenate([f.loc[~f.coordinate_suspect, "lat"] for f in frames.values()])
    all_lon = np.concatenate([f.loc[~f.coordinate_suspect, "lon"] for f in frames.values()])
    bbox = (round(all_lon.min() - .3, 3), round(all_lat.min() - .3, 3), round(all_lon.max() + .3, 3), round(all_lat.max() + .3, 3))
    water = water_geometry_utm(bbox)

    inventory = pd.concat([station_inventory(f, water) for f in frames.values()], ignore_index=True)
    inventory.to_csv(out / "station_inventory.csv", index=False)
    ref = reference_check(inventory[inventory.region == "haiphong"])
    ref.to_csv(out / "coordinate_reference_check_hp.csv", index=False)
    evidence = pd.concat([gridded_evidence(f) for f in frames.values()], ignore_index=True)
    evidence.to_csv(out / "gridded_value_evidence.csv", index=False)
    monthly = pd.concat([monthly_salinity(f) for f in frames.values()], ignore_index=True)
    monthly.to_csv(out / "monthly_salinity.csv", index=False)

    regimes = {r: station_regime(f) for r, f in frames.items()}
    stations = pd.concat(regimes.values(), ignore_index=True)
    stations["wet_minus_dry_psu"] = (stations["wet_median_sal"] - stations["dry_median_sal"]).round(3)
    for key, value in SCOPE.items():
        stations[key] = value
    stations.to_csv(out / "station_regime.csv", index=False)
    distribution = (stations[~stations.coordinate_suspect].groupby(["region", "salinity_source", "regime_class"])
                    .size().rename("n_stations").reset_index())
    distribution.to_csv(out / "regime_class_distribution.csv", index=False)
    quantiles = stations.groupby("region")["wet_median_sal"].describe(percentiles=[.05, .25, .5, .75, .95]).reset_index()
    quantiles.to_csv(out / "wet_median_distribution.csv", index=False)

    nb1 = stations[(stations.region == NB1_LIVE[0]) & (stations.station == NB1_LIVE[1])].iloc[0]
    near = nearest_observed(stations, float(nb1.lat), float(nb1.lon), k=8)
    same_regime_obs = near[np.abs(near["wet_median_sal"] - near["wet_median_sal"].iloc[0]) < REGIME_DSAL_PSU]
    nb1_info = {**SCOPE, "nb1_lat": float(nb1.lat), "nb1_lon": float(nb1.lon),
                "nb1_model_derived_wet_median_sal": round(float(nb1.wet_median_sal), 3),
                "nb1_model_derived_class": str(nb1.regime_class),
                "nearest_observed_stations": near[["region", "station", "distance_km", "wet_median_sal", "dry_median_sal", "regime_class"]].to_dict("records"),
                "nb1_observed_regime_class_by_nearest": str(near["regime_class"].iloc[0]),
                "hp_stations_sharing_model_regime": stations[(stations.region == "haiphong") & (np.abs(stations.wet_median_sal - nb1.wet_median_sal) < REGIME_DSAL_PSU)]["station"].tolist(),
                "qn_observed_same_regime_as_nb1_nearest": int(((stations.region == "quangninh") & ~stations.coordinate_suspect &
                                                           (np.abs(stations.wet_median_sal - near["wet_median_sal"].iloc[0]) < REGIME_DSAL_PSU)).sum()),
                "nearest8_within_2psu_of_nearest": same_regime_obs["station"].tolist()}
    (out / "nb1_regime.json").write_text(json.dumps(nb1_info, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    layer = regime_layer(stations, water)
    layer.to_csv(out / "regime_layer.csv", index=False)
    meta = {**SCOPE, "run": RUN_NAME, "class_cuts_psu": CLASS_CUTS, "wet_months": WET_MONTHS,
            "assign_max_km": LAYER_MAX_ASSIGN_KM, "grid_step_m": LAYER_STEP_M, "idw_power": 2, "idw_radius_km": IDW_RADIUS_KM,
            "caveat": "HP salinity is model-derived gridded (GLORYS-like); classes use QN observed stations only"}
    layer_props = [c for c in layer.columns if c not in ("lon", "lat", "cell_x_utm48n", "cell_y_utm48n")]
    (out / "regime_layer.geojson").write_text(json.dumps(to_geojson(layer, layer_props, meta), ensure_ascii=False), encoding="utf-8")
    st_props = ["region", "station", "salinity_source", "wet_median_sal", "dry_median_sal", "regime_class", "coordinate_suspect"]
    (out / "station_regime.geojson").write_text(json.dumps(to_geojson(stations, st_props, meta), ensure_ascii=False), encoding="utf-8")

    all_cells, all_clim, all_conf, all_conf_metrics, counts, region_meta = [], [], [], [], [], {}
    for region, frame in frames.items():
        variables = [v for v in VARIABLES if v in frame and frame[v].notna().any()]
        rows = transfer_rows(frame, regimes[region], variables)
        keys = ["region", "variable", "regime_relation", "distance_bin"]
        cells = summarise_cells(rows, keys)
        cells["model_derived"] = cells["variable"].isin(MODEL_DERIVED.get(region, ())) | (
            (cells["variable"] == "HSI") & bool(MODEL_DERIVED.get(region)))
        all_cells.append(cells)
        clim = climatology_loyo(frame[~frame.coordinate_suspect], variables)
        comp = climatology_comparison(rows, clim, ["region", "variable", "regime_relation", "distance_bin"])
        comp_all = climatology_comparison(rows.assign(distance_bin="all"), clim, ["region", "variable", "regime_relation", "distance_bin"])
        all_clim += [comp, comp_all]
        conf_vars = [v for v in variables if v != "HSI"]
        conf, conf_m = conformal_gates(frame, regimes[region], conf_vars)
        if not conf.empty:
            all_conf.append(conf.assign(region=region, model_derived=conf["parameter"].isin(MODEL_DERIVED.get(region, ()))))
            all_conf_metrics.append(conf_m.assign(region=region))
        counts.append(pass_counts(cells, conf, region, MODEL_DERIVED.get(region, ())))
        region_meta[region] = {"n_rows_pairs": int(len(rows)), "n_dates": int(frame["date"].nunique()),
                               "n_stations_used": int(frame.loc[~frame.coordinate_suspect, "station"].nunique()),
                               "excluded_coordinate_suspect": sorted(frame.loc[frame.coordinate_suspect, "station"].unique().tolist()),
                               "regime_relation_counts": rows[rows.variable == "pH"].drop_duplicates(["anchor", "target"])["regime_relation"].value_counts().to_dict()}
    pd.concat(all_cells, ignore_index=True).to_csv(out / "tolerance_cells.csv", index=False)
    pd.concat([c for c in all_clim if not c.empty], ignore_index=True).to_csv(out / "climatology_comparison.csv", index=False)
    if all_conf:
        pd.concat(all_conf, ignore_index=True).to_csv(out / "conformal_gate_summary.csv", index=False)
        pd.concat(all_conf_metrics, ignore_index=True).to_csv(out / "conformal_metrics.csv", index=False)
    pass_table = pd.concat(counts, ignore_index=True)
    pass_table.to_csv(out / "pass_counts.csv", index=False)

    manifest = {**SCOPE, "run": RUN_NAME, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "inputs": {r: {"path": str(paths.clean_data(r)), "sha256": sha256(paths.clean_data(r))} for r in REGIONS},
                "water_mask": {"path": str(paths.WATER_SHAPEFILE), "sha256": sha256(paths.WATER_SHAPEFILE)},
                "province_lon0": PROVINCE_LON0, "towgs84": TOWGS84, "model_derived": MODEL_DERIVED, "screens": screens,
                "class_cuts_psu": CLASS_CUTS, "regime_dsal_psu": REGIME_DSAL_PSU, "wet_months": WET_MONTHS,
                "tolerances": TOLERANCES, "gates": GATES, "min_dates": MIN_DATES, "relaxed_min_dates": RELAXED_MIN_DATES,
                "n_boot": N_BOOT, "seed": SEED, "bins_km": BIN_LABELS, "climatology": "leave_one_year_out_same_month_median",
                "hsi_estimator": "anchor_row_only", "legacy_radius": "dropped (read target HSI)", "regions": region_meta}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"output": str(out), "regions": region_meta}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
