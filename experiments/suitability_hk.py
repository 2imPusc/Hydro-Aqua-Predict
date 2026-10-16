"""Direction 3, out-of-sample check: cobia cage suitability on Hong Kong waters vs the 28 AFCD Fish Culture Zones.

Runs the variants of experiments/suitability_map.py (Ghaderi replication A/A_W, nearshore N1/N1_W/N2_W, and
B_W) on a 1/60 deg grid of Hong Kong waters with thresholds imported unchanged (COBIA_RANGES, NEARSHORE_RANGES;
decisions #15). The FCZs (data/foreign/hk_epd/fish_culture_zones.csv) were designated by AFCD and were never used
to set any threshold, so this is the independent validation that the VN run (RL-05/RL-06) lacks.

Layers (raw inputs write-once under data/suitability_hk/<year>/):
  SWH, SCS, CSCD, SST  Open-Meteo Marine, requested on the native 1/12 deg cell centres (cell_selection=sea);
                       every fine cell takes the nearest requested point -> effective resolution ~9 km
  WS                   Open-Meteo Archive (ERA5 best match), 0.25 deg
  DEP + grid           ETOPO1 (1 arc-min) nodes = the 1/60 deg fine grid
  DfS, sea mask        OSM natural=coastline (Overpass), polygonised with the bbox; faces holding an EPD station = sea
  HK waters            OSM relation ISO3166-1=HK (cells outside HK are dropped: no EPD data, not FCZ-eligible)
  DfP, DfPA            OSM ports / protected areas (same query as the VN run)
  SSS, DO, NH3, TSS, pH  HK EPD marine monitoring, surface samples 2020-2024, station medians, IDW (k=5, p=2)

Two sea masks are scored: "etopo" (coastline sea AND ETOPO altitude < 0) and "coast" (coastline sea only; bay cells
that ETOPO calls land get DEP = 0, which penalises the depth-using variants).

    python experiments/suitability_hk.py --year 2024
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import shapely
from pyproj import Transformer
from scipy.stats import mannwhitneyu, spearmanr
from shapely import wkt
from shapely.geometry import LineString, Point, box
from shapely.ops import linemerge, polygonize, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from experiments.suitability_collect_layers import USER_AGENT, _hourly_batches, fetch_etopo, fetch_osm, write_once  # noqa: E402
from experiments.suitability_map import NEARSHORE_RANGES, idw, nearest_distance_km, piecewise, score_variants  # noqa: E402
from hap_shared.fuzzy_suitability import (  # noqa: E402
    COBIA_RANGES, direction_stability, distance_membership, minmax, temporal_score, triangular,
)

BBOX = (113.82, 22.13, 114.50, 22.57)  # min_lon, min_lat, max_lon, max_lat: Hong Kong waters
MARINE_STEP = 1 / 12
WIND_STEP = 0.25
FINE_STEP = 1 / 60
CELL_KM = 1.8  # "within one cell" of an FCZ polygon (1/60 deg ~ 1.85 km N-S, 1.71 km E-W at 22.4 N)
MARINE_VARS = ("wave_height", "ocean_current_velocity", "ocean_current_direction", "sea_surface_temperature")
EPD_YEARS = range(2020, 2025)
EPD_COLUMNS = {"Salinity": "Salinity (psu)", "DO": "Dissolved Oxygen (mg/L)", "NH3": "Unionised Ammonia (mg/L)",
               "TSS": "Suspended Solids (mg/L)", "pH": "pH"}
HK_DIR = paths.DATA_DIR / "foreign" / "hk_epd"
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True)  # UTM 50N, metres
OVERPASS = "https://overpass-api.de/api/interpreter"


# ---------------------------------------------------------------- helpers (unit-tested)

def parse_censored(values: pd.Series) -> pd.Series:
    """EPD strings to float; '<LOQ' becomes LOQ/2, anything unparsable NaN."""
    text = values.astype("string").str.strip()
    censored = text.str.startswith("<").fillna(False)
    number = pd.to_numeric(text.str.lstrip("<"), errors="coerce").astype(float)
    return number.where(~censored, number / 2.0)


def nearest_index(points_xy: np.ndarray, targets_xy: np.ndarray) -> np.ndarray:
    return np.argmin(((points_xy[:, None, :] - targets_xy[None, :, :]) ** 2).sum(axis=2), axis=1)


def label_zones(points_xy: np.ndarray, zones: dict, max_dist: float) -> dict[str, np.ndarray]:
    """Indices of cells whose centre is inside or within ``max_dist`` of each zone geometry (same units)."""
    pts = shapely.points(points_xy)
    return {zone: np.flatnonzero(shapely.distance(pts, geom) <= max_dist) for zone, geom in zones.items()}


def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """Mann-Whitney AUC: P(pos > neg) + 0.5 P(tie)."""
    stat = mannwhitneyu(pos, neg, alternative="two-sided").statistic
    return float(stat / (len(pos) * len(neg)))


def zone_bootstrap_auc(scores: np.ndarray, zone_cells: dict, neg_mask: np.ndarray, n_boot: int = 1000,
                       seed: int = 0) -> tuple[float, float, float]:
    """AUC of FCZ cells vs non-FCZ cells; 95 % CI from resampling zones (not cells) with replacement."""
    cells = [c for c in zone_cells.values() if len(c)]
    neg = scores[neg_mask]
    point = auc(scores[np.unique(np.concatenate(cells))], neg)
    rng = np.random.default_rng(seed)
    boot = [auc(scores[np.concatenate([cells[i] for i in rng.integers(0, len(cells), len(cells))])], neg)
            for _ in range(n_boot)]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return point, float(lo), float(hi)


def paired_zone_bootstrap_diff(scores_a: np.ndarray, scores_b: np.ndarray, zone_cells: dict, neg_mask: np.ndarray,
                               n_boot: int = 1000, seed: int = 0) -> tuple[float, float, float]:
    """AUC(a) - AUC(b) with a 95 % CI from the same zone resamples for both score vectors."""
    cells = [c for c in zone_cells.values() if len(c)]
    allpos = np.unique(np.concatenate(cells))
    point = auc(scores_a[allpos], scores_a[neg_mask]) - auc(scores_b[allpos], scores_b[neg_mask])
    rng = np.random.default_rng(seed)
    boot = []
    for _ in range(n_boot):
        pos = np.concatenate([cells[i] for i in rng.integers(0, len(cells), len(cells))])
        boot.append(auc(scores_a[pos], scores_a[neg_mask]) - auc(scores_b[pos], scores_b[neg_mask]))
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return float(point), float(lo), float(hi)


def zone_percentiles(pct: np.ndarray, zone_cells: dict) -> dict[str, float]:
    """Mean percentile of each zone's cells (NaN for a zone with no evaluable cell)."""
    return {z: float(np.mean(pct[c])) if len(c) else np.nan for z, c in zone_cells.items()}


def zones_in_top(zone_pct: dict[str, float], share: float) -> int:
    return int(sum(v >= 1.0 - share for v in zone_pct.values() if not np.isnan(v)))


def polygon_from_lines(lines):
    """Assemble an area from (possibly split) boundary ways."""
    return unary_union(list(polygonize(linemerge(unary_union(lines)))))


def sea_faces(coast_lines, bbox, seeds):
    """Polygonise coastline + bbox edge; faces containing any seed point are sea."""
    frame = box(*bbox)
    clipped = [line.intersection(frame) for line in coast_lines]
    faces = list(polygonize(unary_union([*clipped, frame.boundary])))
    return unary_union([f for f in faces if any(f.contains(s) for s in seeds)])


# ---------------------------------------------------------------- collection

def _overpass(query: str) -> dict:
    for attempt in range(4):
        response = requests.post(OVERPASS, data={"data": query}, timeout=300,
                                 headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        if response.status_code in {429, 502, 503, 504} and attempt < 3:
            time.sleep(60 * (attempt + 1))
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError("unreachable")


def _bbox_q(bbox) -> str:
    return f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}"


def marine_points(bbox=BBOX) -> pd.DataFrame:
    """Native Open-Meteo Marine cell centres ((k + 0.5) / 12 deg) covering the bbox."""
    def centres(lo, hi):
        k = np.arange(np.ceil(lo / MARINE_STEP - 1.0), np.floor(hi / MARINE_STEP) + 1)
        return np.round((k + 0.5) * MARINE_STEP, 4)
    lon, lat = np.meshgrid(centres(bbox[0], bbox[2]), centres(bbox[1], bbox[3]))
    frame = pd.DataFrame({"lat": lat.ravel(), "lon": lon.ravel()})
    frame.insert(0, "point_id", [f"m{i:03d}" for i in range(len(frame))])
    return frame


def wind_points(bbox=BBOX) -> pd.DataFrame:
    lons = np.arange(np.floor(bbox[0] / WIND_STEP), np.ceil(bbox[2] / WIND_STEP) + 1) * WIND_STEP
    lats = np.arange(np.floor(bbox[1] / WIND_STEP), np.ceil(bbox[3] / WIND_STEP) + 1) * WIND_STEP
    lon, lat = np.meshgrid(lons, lats)
    frame = pd.DataFrame({"lat": lat.ravel(), "lon": lon.ravel()})
    frame.insert(0, "point_id", [f"w{i:02d}" for i in range(len(frame))])
    return frame


def collect(year: int) -> Path:
    out = paths.DATA_DIR / "suitability_hk" / str(year)
    write_once(out / "etopo1_bathymetry.csv", lambda p: fetch_etopo(BBOX).to_csv(p, index=False))
    write_once(out / "osm_features.csv", lambda p: fetch_osm(BBOX).to_csv(p, index=False))
    b = _bbox_q(BBOX)
    write_once(out / "osm_coastline.json", lambda p: p.write_text(json.dumps(_overpass(
        f'[out:json][timeout:180];way["natural"="coastline"]({b});out geom;')), encoding="utf-8"))
    write_once(out / "osm_hk_boundary.json", lambda p: p.write_text(json.dumps(_overpass(
        '[out:json][timeout:180];rel["ISO3166-1"="HK"]["boundary"="administrative"];out geom;')), encoding="utf-8"))
    mpts, wpts = marine_points(), wind_points()
    write_once(out / "marine_points.csv", lambda p: mpts.to_csv(p, index=False))
    write_once(out / "wind_points.csv", lambda p: wpts.to_csv(p, index=False))
    if not all((out / f"marine_{v}.parquet").exists() for v in MARINE_VARS):
        marine = _hourly_batches("https://marine-api.open-meteo.com/v1/marine", mpts, MARINE_VARS, year,
                                 {"cell_selection": "sea"})
        for variable, frame in marine.items():
            write_once(out / f"marine_{variable}.parquet", frame.to_parquet)
    if not (out / "wind_speed_10m.parquet").exists():
        wind = _hourly_batches("https://archive-api.open-meteo.com/v1/archive", wpts, ("wind_speed_10m",), year,
                               {"wind_speed_unit": "ms"})
        write_once(out / "wind_speed_10m.parquet", wind["wind_speed_10m"].to_parquet)
    write_once(out / "manifest.json", lambda p: p.write_text(json.dumps({
        "retrieved_at": datetime.now(timezone.utc).isoformat(), "year": year, "bbox": BBOX,
        "fine_step_deg": FINE_STEP, "marine_step_deg": MARINE_STEP, "wind_step_deg": WIND_STEP,
        "marine_vars": MARINE_VARS, "effective_marine_resolution": "1/12 deg (~9 km); fine cells take nearest point",
        "sources": {"marine": "Open-Meteo Marine API (cell_selection=sea)", "wind": "Open-Meteo Archive (ERA5)",
                    "bathymetry": "NOAA ETOPO1 via ERDDAP etopo180", "osm": "Overpass API (features, coastline, HK boundary)",
                    "water_quality": "HK EPD marine monitoring (data/foreign/hk_epd)"},
    }, indent=2), encoding="utf-8"))
    return out


# ---------------------------------------------------------------- criteria

def _xy(lon, lat) -> np.ndarray:
    x, y = TO_UTM.transform(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
    return np.column_stack([x, y])


def _to_utm(geom):
    return shapely.transform(geom, lambda c: _xy(c[:, 0], c[:, 1]))


def _way_lines(payload: dict) -> list[LineString]:
    lines = []
    for element in payload["elements"]:
        members = element.get("members", [element]) if element["type"] == "relation" else [element]
        for m in members:
            if m.get("type") == "way" and m.get("geometry") and m.get("role", "outer") in {"outer", ""}:
                lines.append(LineString([(g["lon"], g["lat"]) for g in m["geometry"]]))
    return lines


def epd_station_medians() -> pd.DataFrame:
    frames = [pd.read_csv(HK_DIR / f"marine-historical-{y}-en.csv", dtype=str) for y in EPD_YEARS]
    epd = pd.concat(frames, ignore_index=True)
    epd = epd[epd["Depth"] == "Surface Water"]
    values = pd.DataFrame({k: parse_censored(epd[c]) for k, c in EPD_COLUMNS.items()})
    values["station"] = epd["Station"].to_numpy()
    med = values.groupby("station").median()
    med["n_samples"] = values.groupby("station").size()
    stations = pd.read_csv(HK_DIR / "stations.csv")[["station", "lat", "lon"]]
    return stations.merge(med.reset_index(), on="station", how="inner")


def load_zones() -> tuple[dict, pd.DataFrame]:
    fcz = pd.read_csv(HK_DIR / "fish_culture_zones.csv")
    fcz["geom"] = fcz.wkt.map(wkt.loads)
    zones = {}
    for fid, sub in fcz.groupby("fcz_id"):
        zones[f"{int(fid):02d}_{sub.code.iloc[0]}"] = _to_utm(unary_union(list(sub.geom)))
    info = fcz.groupby("fcz_id").agg(code=("code", "first"), name_en=("name_en", "first"), area_sqm=("area_sqm", "sum"),
                                     lat=("lat", "mean"), lon=("lon", "mean")).reset_index()
    info["zone"] = [f"{int(f):02d}_{c}" for f, c in zip(info.fcz_id, info.code)]
    return zones, info


def build_cells(raw_dir: Path) -> tuple[pd.DataFrame, dict]:
    """Fine 1/60 deg cells inside HK waters and the coastline sea, with static raw criteria."""
    etopo = pd.read_csv(raw_dir / "etopo1_bathymetry.csv")
    stations = epd_station_medians()
    coast = _way_lines(json.loads((raw_dir / "osm_coastline.json").read_text(encoding="utf-8")))
    hk = polygon_from_lines(_way_lines(json.loads((raw_dir / "osm_hk_boundary.json").read_text(encoding="utf-8"))))
    sea = sea_faces(coast, BBOX, [Point(lo, la) for lo, la in zip(stations.lon, stations.lat)])
    pts = shapely.points(etopo.longitude.to_numpy(), etopo.latitude.to_numpy())
    etopo["in_hk"] = shapely.contains(hk, pts)
    etopo["sea_coast"] = shapely.contains(sea, pts)
    etopo["sea_etopo"] = etopo.altitude < 0
    _, info = load_zones()
    diag = {
        "etopo_nodes": int(len(etopo)), "hk_area_km2": float(_to_utm(hk).area / 1e6), "coast_ways": len(coast),
        "in_hk": int(etopo.in_hk.sum()), "sea_coast&hk": int((etopo.sea_coast & etopo.in_hk).sum()),
        "sea_etopo&hk": int((etopo.sea_etopo & etopo.in_hk).sum()),
        "sea_both&hk": int((etopo.sea_coast & etopo.sea_etopo & etopo.in_hk).sum()),
        "etopo_sea_but_coast_land&hk": int((etopo.sea_etopo & ~etopo.sea_coast & etopo.in_hk).sum()),
        "epd_stations_in_hk_poly": int(shapely.contains(hk, shapely.points(stations.lon, stations.lat)).sum()),
        "fcz_centroids_in_coast_sea": int(shapely.contains(sea, shapely.points(info.lon, info.lat)).sum()),
        "fcz_centroids_in_hk": int(shapely.contains(hk, shapely.points(info.lon, info.lat)).sum()),
    }
    cells = etopo[etopo.sea_coast & etopo.in_hk].reset_index(drop=True)
    cells = cells.rename(columns={"latitude": "lat", "longitude": "lon"})
    cells.insert(0, "cell_id", [f"c{i:04d}" for i in range(len(cells))])
    cells = cells.set_index("cell_id")
    cxy = _xy(cells.lon, cells.lat)
    cells["DEP"] = (-cells.altitude).clip(lower=0)
    cells["DfS"] = shapely.distance(shapely.points(cxy), _to_utm(unary_union(coast))) / 1000.0
    osm = pd.read_csv(raw_dir / "osm_features.csv")
    for code, kind in (("DfP", "port"), ("DfPA", "protected_area")):
        sub = osm[osm.kind == kind]
        cells[code] = nearest_distance_km(cxy, _xy(sub.lon, sub.lat))
    sxy = _xy(stations.lon, stations.lat)
    for name in EPD_COLUMNS:
        ok = stations[name].notna().to_numpy()
        cells["SSS" if name == "Salinity" else name] = idw(cxy, sxy[ok], stations[name].to_numpy()[ok])
    diag.update({"epd_stations_used": int(len(stations)), "osm_ports": int((osm.kind == "port").sum()),
                 "osm_protected": int((osm.kind == "protected_area").sum()),
                 "osm_aquaculture": int((osm.kind == "aquaculture").sum())})
    return cells, diag


def dynamic_scores(raw_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Temporal fuzzy scores and annual means per requested marine / wind point (not yet min-max scaled)."""
    def series(name):
        return pd.read_parquet(raw_dir / f"marine_{name}.parquet")
    swh, scs, sst = series("wave_height"), series("ocean_current_velocity") / 3.6, series("sea_surface_temperature")
    cdir = series("ocean_current_direction")
    marine = pd.DataFrame({
        "SWH": temporal_score(swh, *COBIA_RANGES["SWH"]), "SCS": temporal_score(scs, *COBIA_RANGES["SCS"]),
        "SCS_near": temporal_score(scs, *NEARSHORE_RANGES["SCS"]), "SST": temporal_score(sst, *COBIA_RANGES["SST"]),
        "CSCD": direction_stability(cdir),
        "SWH_mean": swh.mean(), "SCS_mean": scs.mean(), "SST_mean": sst.mean()})
    wind = pd.read_parquet(raw_dir / "wind_speed_10m.parquet")
    winds = pd.DataFrame({"WS": temporal_score(wind, *COBIA_RANGES["WS"]), "WS_mean": wind.mean()})
    nulls = {f"marine_{k}": float(v.isna().to_numpy().mean()) for k, v in
             (("wave_height", swh), ("ocean_current_velocity", scs), ("sea_surface_temperature", sst),
              ("ocean_current_direction", cdir))}
    nulls["wind_speed_10m"] = float(wind.isna().to_numpy().mean())
    nulls["marine_points_all_null_wave"] = int(swh.isna().all().sum())
    nulls["marine_points_all_null_current"] = int(scs.isna().all().sum())
    return marine, winds, pd.DataFrame(), nulls


def criteria(cells: pd.DataFrame, raw_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Raw and fuzzy criteria for the given cells; min-max and distance scaling are over these cells only."""
    marine, winds, _, nulls = dynamic_scores(raw_dir)
    cxy = _xy(cells.lon, cells.lat)
    mpts = pd.read_csv(raw_dir / "marine_points.csv")
    wpts = pd.read_csv(raw_dir / "wind_points.csv")
    m_id = mpts.point_id.to_numpy()[nearest_index(cxy, _xy(mpts.lon, mpts.lat))]
    w_id = wpts.point_id.to_numpy()[nearest_index(cxy, _xy(wpts.lon, wpts.lat))]
    raw = cells.copy()
    raw["marine_point"], raw["wind_point"] = m_id, w_id
    raw["SWH"], raw["SCS"], raw["SST"] = (marine.loc[m_id, f"{c}_mean"].to_numpy() for c in ("SWH", "SCS", "SST"))
    raw["WS"] = winds.loc[w_id, "WS_mean"].to_numpy()
    fuzzy = pd.DataFrame(index=cells.index)
    for name in ("SWH", "SCS", "SST", "SCS_near", "CSCD"):
        fuzzy[name] = minmax(marine.loc[m_id, name].to_numpy())
    fuzzy["WS"] = minmax(winds.loc[w_id, "WS"].to_numpy())
    fuzzy["DEP"] = triangular(raw.DEP, *COBIA_RANGES["DEP"])
    fuzzy["DfS"] = triangular(raw.DfS, *COBIA_RANGES["DfS"])
    fuzzy["DfS_near"] = triangular(raw.DfS, *NEARSHORE_RANGES["DfS"])
    fuzzy["DfP"] = distance_membership(raw.DfP, closer_is_better=True)
    fuzzy["DfPA"] = distance_membership(raw.DfPA, closer_is_better=False)
    fuzzy["SSS"] = triangular(raw.SSS, *COBIA_RANGES["SSS"])
    thresholds = json.loads(paths.COBIA_THRESHOLDS.read_text(encoding="utf-8"))
    fuzzy["SSS_repo"] = piecewise(raw.SSS, thresholds["Salinity"]["breakpoints"])
    for v in ("DO", "NH3", "TSS", "pH"):
        fuzzy[f"WQ_{v}"] = piecewise(raw[v], thresholds[v]["breakpoints"])
    return raw, fuzzy, nulls


# ---------------------------------------------------------------- validation

def validate(scores: pd.DataFrame, fuzzy: pd.DataFrame, raw: pd.DataFrame, mask: str, n_boot: int = 1000):
    zones, info = load_zones()
    zone_cells = label_zones(_xy(raw.lon, raw.lat), zones, CELL_KM * 1000.0)
    pos = np.zeros(len(raw), dtype=bool)
    for c in zone_cells.values():
        pos[c] = True
    rows, zrows = [], []
    for column in scores:
        s = scores[column].to_numpy()
        ok = ~np.isnan(s)
        pct = pd.Series(s).rank(pct=True).to_numpy()
        zc = {z: c[ok[c]] for z, c in zone_cells.items()}
        point, lo, hi = zone_bootstrap_auc(np.where(ok, s, -np.inf), zc, ~pos & ok, n_boot=n_boot)
        zp = zone_percentiles(pct, zc)
        rows.append({"mask": mask, "variant": column, "n_cells": int(ok.sum()), "n_fcz_cells": int((pos & ok).sum()),
                     "n_zones_evaluable": int(sum(len(c) > 0 for c in zc.values())),
                     "mean_percentile_fcz_cells": float(np.mean(pct[pos & ok])),
                     "mean_zone_percentile": float(np.nanmean(list(zp.values()))),
                     "auc": point, "auc_lo": lo, "auc_hi": hi,
                     "zones_top20": zones_in_top(zp, 0.2), "zones_top40": zones_in_top(zp, 0.4)})
        zrows += [{"mask": mask, "variant": column, "zone": z, "n_cells": int(len(zc[z])), "zone_percentile": v}
                  for z, v in zp.items()]
    drivers = pd.DataFrame({"mask": mask, "fcz_mean": fuzzy[pos].mean(), "all_mean": fuzzy.mean(),
                            "nonfcz_mean": fuzzy[~pos].mean()})
    drivers["diff_fcz_minus_nonfcz"] = drivers.fcz_mean - drivers.nonfcz_mean
    raw_cols = ["DEP", "DfS", "DfP", "DfPA", "SWH", "SCS", "SST", "WS", "SSS", "DO", "NH3", "TSS", "pH"]
    raw_drivers = pd.DataFrame({"mask": mask, "fcz_mean": raw.loc[pos, raw_cols].mean(),
                                "nonfcz_mean": raw.loc[~pos, raw_cols].mean()})
    return pd.DataFrame(rows), pd.DataFrame(zrows).merge(info[["zone", "name_en", "area_sqm"]], on="zone"), \
        drivers.rename_axis("criterion").reset_index(), raw_drivers.rename_axis("criterion").reset_index(), pos


ABLATION_BASE = ["SWH", "WS", "SST", "SSS", "DEP", "DfS", "SCS", "CSCD", "DfP", "DfPA"]


def ablation_sets() -> dict[str, list[str]]:
    """Criterion sets that separate 'drop DEP' from the nearshore DfS / SCS thresholds (A -> N1 one step at a time)."""
    no_dep = [c for c in ABLATION_BASE if c != "DEP"]
    swap = {"DfS": "DfS_near", "SCS": "SCS_near"}
    n1 = [swap.get(c, c) for c in no_dep]
    return {"A": ABLATION_BASE, "A_noDEP": no_dep,
            "A_noDEP_DfSnear": [{"DfS": "DfS_near"}.get(c, c) for c in no_dep],
            "A_noDEP_SCSnear": [{"SCS": "SCS_near"}.get(c, c) for c in no_dep],
            "N1": n1, "N1_withDEP": n1 + ["DEP"]}


def run_ablation(run_dir: Path, n_boot: int = 1000) -> pd.DataFrame:
    """Post-hoc ablation on a finished run's fuzzy criteria; writes ablation.csv (refuses overwrite)."""
    from hap_shared.fuzzy_suitability import GHADERI_WEIGHTS, integrate
    target = run_dir / "ablation.csv"
    if target.exists():
        raise FileExistsError(target)
    zones, _ = load_zones()
    weights = {**GHADERI_WEIGHTS, "DfS_near": GHADERI_WEIGHTS["DfS"], "SCS_near": GHADERI_WEIGHTS["SCS"]}
    rows, diag = [], {}
    for mask in ("coast", "etopo"):
        fuzzy = pd.read_csv(run_dir / f"criteria_fuzzy_{mask}.csv", index_col=0)
        raw = pd.read_csv(run_dir / f"criteria_raw_{mask}.csv", index_col=0)
        xy = _xy(raw.lon, raw.lat)
        zone_cells = label_zones(xy, zones, CELL_KM * 1000.0)
        pos = np.zeros(len(raw), dtype=bool)
        for c in zone_cells.values():
            pos[c] = True
        diag[mask] = {z: round(float(shapely.distance(shapely.points(xy), g).min() / 1000.0), 3)
                      for z, g in zones.items() if not len(zone_cells[z])}
        for weighted in (False, True):
            for method, gamma in (("SUM", 0.0), ("GAMMA_0.9", 0.9)):
                scores = {name: integrate(fuzzy[cols], gamma, weights if weighted else None).to_numpy()
                          for name, cols in ablation_sets().items()}
                aucs = {name: zone_bootstrap_auc(s, zone_cells, ~pos, n_boot=n_boot) for name, s in scores.items()}
                pairs = [(name, "A") for name in scores if name != "A"] + [("N1", "A_noDEP"), ("A", "N1_withDEP")]
                for name, ref in [("A", "")] + pairs:
                    row = {"mask": mask, "weighted": weighted, "method": method, "set": name,
                           "auc": aucs[name][0], "auc_lo": aucs[name][1], "auc_hi": aucs[name][2], "diff_ref": ref}
                    if ref:
                        row["diff"], row["diff_lo"], row["diff_hi"] = paired_zone_bootstrap_diff(
                            scores[name], scores[ref], zone_cells, ~pos, n_boot=n_boot)
                    rows.append(row)
    table = pd.DataFrame(rows)
    table.to_csv(target, index=False)
    (run_dir / "ablation_unmatched_zones_km.json").write_text(json.dumps(diag, indent=2), encoding="utf-8")
    return table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--run", default=None, help="output folder name under EXPERIMENT_OUTPUT_DIR")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--n-boot", type=int, default=1000)
    parser.add_argument("--ablation", action="store_true", help="post-hoc DEP / threshold ablation on a finished run")
    args = parser.parse_args(argv)
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / (args.run or f"suitability-hk-{args.year}")
    if args.ablation:
        table = run_ablation(run_dir, args.n_boot)
        print(table.round(3).to_string(index=False))
        print((run_dir / "ablation_unmatched_zones_km.json").read_text(encoding="utf-8"))
        return 0
    if not args.collect_only and run_dir.exists():
        print(f"exists, not overwritten: {run_dir}")
        return 1
    raw_dir = collect(args.year)
    if args.collect_only:
        return 0
    cells, diag = build_cells(raw_dir)
    print(json.dumps(diag, indent=1))
    outputs = {}
    for mask, keep in (("etopo", cells.altitude < 0), ("coast", pd.Series(True, index=cells.index))):
        raw, fuzzy, nulls = criteria(cells[keep], raw_dir)
        scores = score_variants(fuzzy)
        outputs[mask] = (raw, fuzzy, scores, *validate(scores, fuzzy, raw, mask, args.n_boot))
    run_dir.mkdir(parents=True)
    summary = {"diagnostics": diag, "nulls": nulls, "cell_km": CELL_KM, "bbox": BBOX, "year": args.year,
               "loq_rule": "'<LOQ' -> LOQ/2", "epd_years": [min(EPD_YEARS), max(EPD_YEARS)], "spearman": {}}
    tables = {"validation": [], "zones": [], "drivers": [], "drivers_raw": []}
    for mask, (raw, fuzzy, scores, check, zones, drivers, raw_drivers, pos) in outputs.items():
        raw.assign(fcz=pos).to_csv(run_dir / f"criteria_raw_{mask}.csv")
        fuzzy.to_csv(run_dir / f"criteria_fuzzy_{mask}.csv")
        scores.join(raw[["lat", "lon"]]).assign(fcz=pos).to_csv(run_dir / f"scores_{mask}.csv")
        for key, table in zip(tables, (check, zones, drivers, raw_drivers)):
            tables[key].append(table)
        summary["spearman"][mask] = {f"{a}~{b}": float(spearmanr(scores[a], scores[b]).statistic)
                                     for a, b in (("A_W_SUM", "N1_W_SUM"), ("A_SUM", "N1_SUM"))}
    for key, parts in tables.items():
        pd.concat(parts).to_csv(run_dir / f"{key}.csv", index=False)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    pd.set_option("display.width", 200)
    print(pd.concat(tables["validation"]).round(3).to_string(index=False))
    print(pd.concat(tables["drivers"]).round(3).to_string(index=False))
    print(pd.concat(tables["drivers_raw"]).round(3).to_string(index=False))
    print(json.dumps(summary["spearman"], indent=1), json.dumps(nulls, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
