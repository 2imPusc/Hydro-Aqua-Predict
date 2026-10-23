"""Per-site exposure (fetch, topographic shelter, depth, current) and a Yagi 2024 demo.  Theory only.

    python experiments/site_exposure.py download-dem --stamp 20261023        # Copernicus GLO-30 DSM tiles
    python experiments/site_exposure.py download-era5-wind                   # ERA5 10 m wind + direction, 4-9 Sep 2024
    python experiments/site_exposure.py run --run-name site-exposure-20261023

Downloads are write-once (new names/stamps; never overwritten).  The run writes a new directory
``paths.EXPERIMENT_OUTPUT_DIR / <run-name>`` (exist_ok=False).  Method and citations:
``core/site_exposure.py`` and ``docs/eval/2026-10-23-site-exposure.md``.  Every advisory-like row carries
``used_by_alerts: False``, ``notification_eligible: False``, ``basis: theory_only_unvalidated``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import shapefile
import shapely
from pyproj import Geod
from shapely.geometry import Point, shape
from shapely.ops import nearest_points, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core import site_exposure as se  # noqa: E402
from core import storm_advisory as sa  # noqa: E402
from experiments.hazard_data import ARCHIVE_URL, write_once  # noqa: E402

GEOD = Geod(ellps="WGS84")
DEM_URL = ("https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{tile}_DEM/"
           "Copernicus_DSM_COG_10_{tile}_DEM.tif")
DEM_TILES = ("N20_00_E106_00", "N20_00_E107_00", "N21_00_E106_00", "N21_00_E107_00")
DEM_BOUNDS = (106.0, 20.0, 108.0, 22.0)  # lon_min, lat_min, lon_max, lat_max of the 2x2 mosaic
ETOPO_FILE = paths.DEPTH_DIR / "etopo2022-20261023" / "etopo2022_15s_hp_qn.nc"
MARINE_DIR = paths.SUITABILITY_LAYERS_DIR / "2024"
OSM_FEATURES = paths.SUITABILITY_LAYERS_DIR / "osm_features.csv"

FETCH_STEP_M = 100.0
FETCH_MAX_M = 200_000.0
SHELTER_STEP_M = 30.0
SHELTER_MAX_M = 15_000.0
SHELTER_SPREAD = (-10.0, -5.0, 0.0, 5.0, 10.0)  # rays averaged per direction (crude obstacle-width proxy)
STRAIGHT_SPREAD = (-6.0, 0.0, 6.0)  # median of 3 rays = straight-line fetch (suppresses single-ray gaps)
DEPTH_STEP_M = 250.0
GRID_BOUNDS = (106.85, 20.62, 107.65, 21.15)
GRID_STEP_DEG = 0.025
# Beaufort lower bounds (m/s) used for the "every direction" table: cấp 8, 10, 12
REFERENCE_WINDS = {8: 17.2, 10: 24.5, 12: 32.7}
NACA_FLOATING_HS_M = 1.0
DANGEROUS_HS_M = 2.0  # NS 9415 wave class D ("high exposure") starts at 2.0 m
YAGI_WINDOW = ("2024-09-05T00:00Z", "2024-09-09T00:00Z")
ERA5_WIND_START, ERA5_WIND_END = "2024-09-04", "2024-09-09"

# Yagi damage areas from VAST SAR (https://vast.gov.vn/... -125900-871.html); coordinates are OUR approximate
# reading of the area descriptions, snapped to water. Not survey points.
QN_REFERENCE_POINTS = (
    ("VAST_A1", "Vịnh Hạ Long, phía bắc đảo Cát Bà (vùng SAR 1: toàn bộ bị phá hủy)", 20.88, 107.10),
    ("VAST_A2", "Phía nam TP Cẩm Phả (vùng SAR 2: ~80 % lồng bị phá hủy)", 20.98, 107.30),
    ("VAST_A3", "Bái Tử Long, giữa đảo Vạn Cảnh và Ngọc Vừng (vùng SAR 3: toàn bộ bị phá hủy)", 20.95, 107.40),
    ("VAST_A4", "Phía tây đảo Trà Bản (vùng SAR 4: toàn bộ bị phá hủy)", 21.03, 107.42),
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ downloads

def download_dem(stamp: str) -> dict:
    target_dir = paths.TERRAIN_DIR / f"copernicus-glo30-{stamp}"
    target_dir.mkdir(parents=True, exist_ok=False)
    metas = []
    for tile in DEM_TILES:
        url = DEM_URL.format(tile=tile)
        resp = requests.get(url, timeout=600)
        resp.raise_for_status()
        metas.append(write_once(target_dir / f"{tile}.tif", resp.content, url))
    meta = {"source": "Copernicus DEM GLO-30 (DSM: includes canopy and buildings), AWS open data bucket copernicus-dem-30m",
            "resolution": "1 arc-second (~30 m)", "vertical_datum": "EGM2008", "licence": "Copernicus DEM licence (free, attribution)",
            "attribution": "Copernicus DEM (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the EU and ESA",
            "tiles": metas, "retrieved_at": datetime.now(timezone.utc).isoformat()}
    (target_dir / "manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def era5_wind_sites() -> pd.DataFrame:
    st = pd.read_csv(paths.STATION_COORDINATES)
    rows = [{"site_id": r.Station, "lat": r.Lat, "lon": r.Lon} for r in st.itertuples()]
    rows += [{"site_id": sid, "lat": lat, "lon": lon} for sid, _, lat, lon in QN_REFERENCE_POINTS]
    return pd.DataFrame(rows)


def download_era5_wind(fetched: date) -> dict:
    sites = era5_wind_sites()
    params = {"latitude": ",".join(f"{v:.5f}" for v in sites.lat), "longitude": ",".join(f"{v:.5f}" for v in sites.lon),
              "models": "era5", "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m", "wind_speed_unit": "ms",
              "timezone": "GMT", "start_date": ERA5_WIND_START, "end_date": ERA5_WIND_END}
    resp = requests.get(ARCHIVE_URL, params=params, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    data = data if isinstance(data, list) else [data]
    frames = []
    for site, item in zip(sites.itertuples(), data):
        df = pd.DataFrame(item["hourly"])
        df.insert(0, "site_id", site.site_id)
        df["grid_lat"], df["grid_lon"] = item["latitude"], item["longitude"]
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    target = paths.HAZARD_DATA_DIR / "era5" / f"openmeteo_era5_sites_wind_{ERA5_WIND_START:.10}_{ERA5_WIND_END:.10}_{fetched:%Y%m%d}.csv"
    return write_once(target, out.to_csv(index=False).encode(), ARCHIVE_URL,
                      {"model": "era5", "sites": sites.to_dict("records"), "params": {k: v for k, v in params.items()
                                                                                      if k not in ("latitude", "longitude")}})


def latest_era5_wind() -> Path:
    files = sorted((paths.HAZARD_DATA_DIR / "era5").glob("openmeteo_era5_sites_wind_*.csv"))
    if not files:
        raise FileNotFoundError("run: python experiments/site_exposure.py download-era5-wind")
    return files[-1]


def latest_dem_dir() -> Path:
    dirs = sorted(d for d in paths.TERRAIN_DIR.glob("copernicus-glo30-*") if d.is_dir())
    if not dirs:
        raise FileNotFoundError("run: python experiments/site_exposure.py download-dem --stamp <yyyymmdd>")
    return dirs[-1]


# ------------------------------------------------------------------ layers

class Layers:
    def __init__(self):
        reader = shapefile.Reader(str(paths.WATER_SHAPEFILE))
        self.extent = tuple(float(v) for v in reader.bbox)
        self.water = unary_union([shape(s.__geo_interface__) for s in reader.shapes()])
        shapely.prepare(self.water)
        self.dem_dir = latest_dem_dir()
        self.dem = np.zeros((7200, 7200), dtype=np.float32)
        from PIL import Image
        for tile in DEM_TILES:
            lat0, lon0 = int(tile[1:3]), int(tile[8:11])
            arr = np.asarray(Image.open(self.dem_dir / f"{tile}.tif"), dtype=np.float32)
            r0 = int(DEM_BOUNDS[3] - (lat0 + 1)) * 3600
            c0 = int(lon0 - DEM_BOUNDS[0]) * 3600
            self.dem[r0:r0 + 3600, c0:c0 + 3600] = arr
        import xarray as xr
        ds = xr.open_dataset(ETOPO_FILE)
        self.etopo_lat = ds["lat"].to_numpy()
        self.etopo_lon = ds["lon"].to_numpy()
        self.etopo_z = ds["z"].to_numpy().astype(float)
        ds.close()
        self.marine_points = pd.read_csv(MARINE_DIR / "marine_points.csv")
        cur = pd.read_parquet(MARINE_DIR / "marine_ocean_current_velocity.parquet") / 3.6  # km/h -> m/s
        self.current = cur
        self.marine_wave = pd.read_parquet(MARINE_DIR / "marine_wave_height.parquet")

    def is_water(self, lon, lat):
        return shapely.contains_xy(self.water, np.asarray(lon), np.asarray(lat))

    def dem_at(self, lon, lat):
        lon, lat = np.asarray(lon), np.asarray(lat)
        col = np.floor((lon - DEM_BOUNDS[0]) * 3600).astype(int)
        row = np.floor((DEM_BOUNDS[3] - lat) * 3600).astype(int)
        ok = (col >= 0) & (col < 7200) & (row >= 0) & (row < 7200)
        out = np.full(lon.shape, np.nan)
        out[ok] = self.dem[row[ok], col[ok]]
        return out

    def etopo_at(self, lon, lat):
        lon, lat = np.asarray(lon, dtype=float), np.asarray(lat, dtype=float)
        i = np.rint((lat - self.etopo_lat[0]) / (self.etopo_lat[1] - self.etopo_lat[0])).astype(int)
        j = np.rint((lon - self.etopo_lon[0]) / (self.etopo_lon[1] - self.etopo_lon[0])).astype(int)
        ok = (i >= 0) & (i < len(self.etopo_lat)) & (j >= 0) & (j < len(self.etopo_lon))
        out = np.full(lon.shape, np.nan)
        out[ok] = self.etopo_z[i[ok], j[ok]]
        return out

    def snap(self, lon, lat):
        p = Point(lon, lat)
        if self.water.contains(p):
            return lon, lat, 0.0
        q = nearest_points(p, self.water)[1]
        # step 30 m further into the water so the first fetch sample is not on the shoreline
        az, _, dist = GEOD.inv(lon, lat, q.x, q.y)
        lon2, lat2, _ = GEOD.fwd(lon, lat, az, dist + 30.0)
        if not self.water.contains(Point(lon2, lat2)):
            lon2, lat2 = q.x, q.y
        return float(lon2), float(lat2), float(dist + 30.0)


# ------------------------------------------------------------------ per-site profile

def site_profile(layers: Layers, lon: float, lat: float) -> dict:
    bearings = [b + o for b in se.BEARINGS16 for o in se.SAVILLE_OFFSETS]
    fetch = se.ray_fetch(layers.is_water, lon, lat, bearings, step_m=FETCH_STEP_M, max_m=FETCH_MAX_M,
                         extent=layers.extent, start_m=50.0)
    f = np.asarray(fetch["fetch_m"]).reshape(16, len(se.SAVILLE_OFFSETS))
    cens = np.asarray(fetch["censored"]).reshape(16, len(se.SAVILLE_OFFSETS))
    offs = list(se.SAVILLE_OFFSETS)
    straight_idx = [offs.index(int(o)) for o in STRAIGHT_SPREAD]
    rows = []
    for k, b in enumerate(se.BEARINGS16):
        straight = float(np.median(f[k, straight_idx]))
        eff = se.saville_effective_fetch(f[k], se.SAVILLE_OFFSETS)
        # depth: mean ETOPO depth along the central ray up to the straight-line fetch (water samples only)
        dists = np.arange(DEPTH_STEP_M, max(straight, DEPTH_STEP_M) + 1, DEPTH_STEP_M)
        dl, dt = se.ray_points(lon, lat, b, dists)
        z = layers.etopo_at(dl, dt)
        wet = z[(z < 0) & np.isfinite(z)]
        depth_mean = float(-wet.mean()) if wet.size else np.nan
        depth_max = float(-wet.min()) if wet.size else np.nan
        # shelter: DSM along upwind rays
        sd = np.arange(SHELTER_STEP_M, SHELTER_MAX_M + 1, SHELTER_STEP_M)
        ray_res = []
        for o in SHELTER_SPREAD:
            sl, st = se.ray_points(lon, lat, b + o, sd)
            ray_res.append(se.ray_shelter(sd, layers.dem_at(sl, st)))
        central = ray_res[SHELTER_SPREAD.index(0.0)]
        rows.append({"direction": se.COMPASS16[k], "bearing": b, "fetch_straight_m": straight,
                     "fetch_central_m": float(f[k, offs.index(0)]), "fetch_effective_m": eff,
                     "fetch_censored": bool(cens[k, straight_idx].any()),
                     "depth_mean_m": depth_mean, "depth_max_m": depth_max, "depth_samples": int(wet.size),
                     "shelter_factor": float(np.mean([r["factor"] for r in ray_res])),
                     "shelter_central": central["factor"],
                     "obstacle_height_m": central["obstacle_height_m"], "obstacle_distance_m": central["obstacle_distance_m"],
                     "max_elevation_angle_deg": max(r["max_elevation_angle_deg"] for r in ray_res)})
    return {"directions": pd.DataFrame(rows)}


def profile_dict(directions: pd.DataFrame) -> dict:
    depth = directions["depth_mean_m"].fillna(directions["depth_mean_m"].median()).fillna(10.0).clip(lower=1.0)
    return {"bearing": directions["bearing"].to_numpy(), "fetch_m": directions["fetch_straight_m"].to_numpy(),
            "depth_m": depth.to_numpy(), "shelter": directions["shelter_factor"].to_numpy()}


def current_stats(layers: Layers, lon: float, lat: float) -> dict:
    mp = layers.marine_points
    d = sa.haversine_km(mp["lat"].to_numpy(), mp["lon"].to_numpy(), lat, lon)
    i = int(np.argmin(d))
    pid = mp["point_id"].iloc[i]
    s = layers.current[pid].dropna()
    yagi = s[(s.index >= YAGI_WINDOW[0]) & (s.index < YAGI_WINDOW[1])]
    w = layers.marine_wave[pid].dropna()
    wy = w[(w.index >= YAGI_WINDOW[0]) & (w.index < YAGI_WINDOW[1])]
    return {"current_point": pid, "current_point_offset_km": float(d[i]),
            "current_p50_ms": float(s.quantile(0.5)), "current_p95_ms": float(s.quantile(0.95)),
            "current_max_ms": float(s.max()), "current_class_p95": se.current_class(float(s.quantile(0.95))),
            "current_yagi_max_ms": float(yagi.max()) if not yagi.empty else None,
            "marine_wave_yagi_max_m": float(wy.max()) if not wy.empty else None}


def reference_table(site_id: str, prof: dict, directions: pd.DataFrame, current_ms: float | None) -> pd.DataFrame:
    rows = []
    for level, wind in REFERENCE_WINDS.items():
        for _, d in directions.iterrows():
            ev = se.evaluate_site(wind, d["bearing"], prof, current_ms=current_ms)
            rows.append({"site_id": site_id, "beaufort_open": level, "wind_open_ms": wind, "direction": d["direction"],
                         "bearing": d["bearing"], "shelter_factor": ev["shelter_factor"],
                         "local_wind_ms": ev["local_wind_ms"], "local_beaufort": ev["local_beaufort"],
                         "fetch_m": ev["fetch_m"], "depth_m": ev["depth_m"], "hs_m": ev["hs_m"], "t_s": ev["t_s"],
                         "wave_class": ev["wave_class"], "tier": ev["tier"], "label_vi": ev["label_vi"]})
    return pd.DataFrame(rows)


def summarise(site: dict, directions: pd.DataFrame, ref: pd.DataFrame, cur: dict) -> dict:
    r8 = ref[ref.beaufort_open == 8].set_index("direction")
    r10 = ref[ref.beaufort_open == 10].set_index("direction")
    r12 = ref[ref.beaufort_open == 12].set_index("direction")
    worst = r10["hs_m"].idxmax()
    by_hs = r10.sort_values("hs_m", ascending=False)
    dangerous = by_hs[by_hs["hs_m"] >= DANGEROUS_HS_M].index.tolist()
    watch = by_hs[(by_hs["hs_m"] >= NACA_FLOATING_HS_M) & (by_hs["hs_m"] < DANGEROUS_HS_M)].index.tolist()
    hs8_max = float(r8["hs_m"].max())
    exposure = {"A": "kín (sheltered)", "B": "bán kín (semi)"}.get(se.wave_class(hs8_max), "hở (exposed)")
    sheltered_dirs = directions.loc[directions["shelter_factor"] < 0.75, "direction"].tolist()
    return {**site, "exposure_class": exposure, "exposure_rule": "NS 9415 wave class of max Hs at open wind cấp 8 (17.2 m/s): A kín, B bán kín, >=C hở (assumption)",
            "worst_direction": worst, "dangerous_directions": dangerous, "watch_directions": watch,
            "fetch_effective_max_km": float(directions["fetch_effective_m"].max() / 1000),
            "fetch_effective_mean_km": float(directions["fetch_effective_m"].mean() / 1000),
            "fetch_straight_worst_km": float(directions.set_index("direction").loc[worst, "fetch_straight_m"] / 1000),
            "open_sectors_censored": directions.loc[directions["fetch_censored"], "direction"].tolist(),
            "shelter_worst_dir": float(directions.set_index("direction").loc[worst, "shelter_factor"]),
            "sheltered_directions": sheltered_dirs,
            "max_terrain_angle_deg": float(directions["max_elevation_angle_deg"].max()),
            "hs_worst_c8_m": float(r8.loc[worst, "hs_m"]), "hs_worst_c10_m": float(r10.loc[worst, "hs_m"]),
            "hs_worst_c12_m": float(r12.loc[worst, "hs_m"]),
            "tier_worst_c8": int(r8["tier"].max()), "tier_worst_c10": int(r10["tier"].max()),
            "tier_worst_c12": int(r12["tier"].max()),
            "local_beaufort_worst_c10": int(r10.loc[worst, "local_beaufort"]),
            **cur, **se.FLAGS}


# ------------------------------------------------------------------ sites

def build_sites(layers: Layers, grid: bool = True) -> list[dict]:
    sites = []
    st = pd.read_csv(paths.STATION_COORDINATES)
    for r in st.itertuples():
        sites.append({"site_id": r.Station, "kind": "station", "name": r.Station_Name, "lat_src": r.Lat, "lon_src": r.Lon})
    for sid, name, lat, lon in QN_REFERENCE_POINTS:
        sites.append({"site_id": sid, "kind": "yagi_damage_ref", "name": name, "lat_src": lat, "lon_src": lon})
    osm = pd.read_csv(OSM_FEATURES)
    osm = osm[(osm["kind"] == "aquaculture") & (osm["lon"] < DEM_BOUNDS[2]) & (osm["lat"] < DEM_BOUNDS[3])]
    for r in osm.itertuples():
        sites.append({"site_id": f"osm_{r.osm_type}_{r.osm_id}", "kind": "osm_farm",
                      "name": r.name if isinstance(r.name, str) else "", "lat_src": r.lat, "lon_src": r.lon})
    if grid:
        lons = np.arange(GRID_BOUNDS[0], GRID_BOUNDS[2] + 1e-9, GRID_STEP_DEG)
        lats = np.arange(GRID_BOUNDS[1], GRID_BOUNDS[3] + 1e-9, GRID_STEP_DEG)
        gx, gy = np.meshgrid(lons, lats)
        wet = layers.is_water(gx.ravel(), gy.ravel())
        for x, y in zip(gx.ravel()[wet], gy.ravel()[wet]):
            sites.append({"site_id": f"grid_{y:.3f}_{x:.3f}", "kind": "grid", "name": "", "lat_src": float(y), "lon_src": float(x)})
    for s in sites:
        lon, lat, off = layers.snap(s["lon_src"], s["lat_src"])
        z = float(layers.etopo_at(lon, lat))
        s.update({"lon": lon, "lat": lat, "snap_offset_m": off,
                  "depth_site_m": -z if np.isfinite(z) and z < 0 else None,
                  "depth_site_flag": "etopo_land_cell" if not (np.isfinite(z) and z < 0) else None})
    return sites


# ------------------------------------------------------------------ Yagi

def yagi_track() -> pd.DataFrame:
    files = sorted((paths.HAZARD_DATA_DIR / "ibtracs").glob("ibtracs.WP.list.v04r01.*.csv"))
    tracks = sa.load_ibtracs(files[-1])
    yagi = tracks[(tracks["NAME"] == "YAGI") & (tracks["SEASON"] == 2024)]
    dense = sa.interpolate_track(yagi, "30min")
    t = dense["ISO_TIME"]
    return dense[(t >= YAGI_WINDOW[0]) & (t < YAGI_WINDOW[1])].reset_index(drop=True), files[-1]


def yagi_series(site: dict, prof: dict, current_ms, track: pd.DataFrame, era5: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in track.iterrows():
        exp = sa.site_exposure(r, site["lat"], site["lon"])
        if exp["site_wind_ms"] is None or exp["dist_km"] > 500:
            continue
        wfrom = se.cyclone_wind_from(r["LAT"], r["LON"], site["lat"], site["lon"])
        ev = se.evaluate_site(exp["site_wind_ms"], wfrom, prof, current_ms=current_ms)
        rows.append({"source": "best_track_radii_floor", "time": r["ISO_TIME"], "wind_ms": exp["site_wind_ms"],
                     "wind_from_deg": wfrom, "exposure_method": exp["exposure_method"], "dist_km": exp["dist_km"], **_ev(ev)})
        # pure modified Rankine from 10-min intensity and RMW (no wind-radii floor): shows the spatial gradient
        vmax, _ = sa.storm_wind_ms(r)
        if vmax is not None:
            rmw = sa.DEFAULT_RMW_NMI if pd.isna(r.get("USA_RMW")) else float(r["USA_RMW"])
            speed = sa.rankine_wind_ms(vmax, rmw * sa.NMI_KM, max(exp["dist_km"], 0.1))
            ev2 = se.evaluate_site(speed, wfrom, prof, current_ms=current_ms)
            rows.append({"source": "best_track_rankine", "time": r["ISO_TIME"], "wind_ms": speed, "wind_from_deg": wfrom,
                         "exposure_method": "rankine_pure", "dist_km": exp["dist_km"], **_ev(ev2)})
    for src, sub in (("era5_site", era5[era5.site_id == site.get("era5_id", site["site_id"])]),
                     ("era5_nb1_uniform", era5[era5.site_id == "NB1"])):
        for _, r in sub.iterrows():
            ev = se.evaluate_site(r["wind_speed_10m"], r["wind_direction_10m"], prof, current_ms=current_ms)
            rows.append({"source": src, "time": r["time"], "wind_ms": r["wind_speed_10m"], "wind_from_deg": r["wind_direction_10m"],
                         "exposure_method": "reanalysis_0.25deg", "dist_km": None, **_ev(ev)})
    return pd.DataFrame(rows)


def _ev(ev: dict) -> dict:
    keys = ("shelter_factor", "local_wind_ms", "local_beaufort", "fetch_m", "depth_m", "hs_m", "t_s", "wave_class", "tier", "label_vi")
    return {k: ev.get(k) for k in keys}


def yagi_peaks(site_id: str, series: pd.DataFrame) -> list[dict]:
    out = []
    for src, g in series.groupby("source"):
        g = g.dropna(subset=["hs_m"])
        if g.empty:
            out.append({"site_id": site_id, "source": src})
            continue
        i_w, i_h = g["local_wind_ms"].idxmax(), g["hs_m"].idxmax()
        out.append({"site_id": site_id, "source": src, "open_wind_max_ms": float(g["wind_ms"].max()),
                    "local_wind_max_ms": float(g.loc[i_w, "local_wind_ms"]), "local_beaufort_max": int(g.loc[i_w, "local_beaufort"]),
                    "wind_from_at_local_max": float(g.loc[i_w, "wind_from_deg"]), "time_local_max": str(g.loc[i_w, "time"]),
                    "hs_max_m": float(g.loc[i_h, "hs_m"]), "t_at_hs_max_s": float(g.loc[i_h, "t_s"]),
                    "wind_from_at_hs_max": float(g.loc[i_h, "wind_from_deg"]), "time_hs_max": str(g.loc[i_h, "time"]),
                    "tier_max": int(g["tier"].max()), "label_vi_max": g.loc[g["tier"].idxmax(), "label_vi"],
                    "exposure_method_at_local_max": g.loc[i_w, "exposure_method"], **se.FLAGS})
    return out


# ------------------------------------------------------------------ run

def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.isoformat()
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def run(run_name: str, grid: bool = True) -> Path:
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    layers = Layers()
    sites = build_sites(layers, grid=grid)
    era5_file = latest_era5_wind()
    era5 = pd.read_csv(era5_file)
    era5["time"] = pd.to_datetime(era5["time"], utc=True)
    track, ibtracs_file = yagi_track()

    summaries, per_dir, ref_rows, yagi_rows, yagi_ts = [], [], [], [], []
    for n, site in enumerate(sites):
        prof_raw = site_profile(layers, site["lon"], site["lat"])
        directions = prof_raw["directions"]
        prof = profile_dict(directions)
        cur = current_stats(layers, site["lon"], site["lat"])
        cur_ms = cur["current_p95_ms"]
        ref = reference_table(site["site_id"], prof, directions, cur_ms)
        summaries.append(summarise(site, directions, ref, cur))
        if site["kind"] in ("station", "yagi_damage_ref", "osm_farm"):
            d = directions.copy()
            d.insert(0, "site_id", site["site_id"])
            per_dir.append(d)
            ref_rows.append(ref)
        if site["kind"] in ("station", "yagi_damage_ref"):
            ser = yagi_series(site, prof, cur_ms, track, era5)
            ser.insert(0, "site_id", site["site_id"])
            yagi_ts.append(ser)
            yagi_rows += yagi_peaks(site["site_id"], ser)
        if n % 50 == 0:
            print(f"{n}/{len(sites)} {site['site_id']}", flush=True)

    summary = pd.DataFrame(summaries)
    list_cols = ["dangerous_directions", "watch_directions", "open_sectors_censored", "sheltered_directions"]
    flat = summary.copy()
    for c in list_cols:
        flat[c] = flat[c].map(lambda v: " ".join(v))
    flat[flat.kind == "station"].to_csv(run_dir / "stations.csv", index=False)
    flat.to_csv(run_dir / "all_sites.csv", index=False)
    (run_dir / "stations.json").write_text(json.dumps(summary[summary.kind.isin(["station", "yagi_damage_ref"])].to_dict("records"),
                                                      indent=2, ensure_ascii=False, default=_json_default), encoding="utf-8")
    pd.concat(per_dir).to_csv(run_dir / "per_direction.csv", index=False)
    pd.concat(ref_rows).to_csv(run_dir / "direction_scenarios.csv", index=False)
    pd.DataFrame(yagi_rows).to_csv(run_dir / "yagi_peaks.csv", index=False)
    pd.concat(yagi_ts).to_csv(run_dir / "yagi_timeseries.csv", index=False)

    features = []
    for s in summaries:
        props = {k: v for k, v in s.items() if k not in ("lon", "lat")}
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(s["lon"], 6), round(s["lat"], 6)]},
                         "properties": props})
    geo = {"type": "FeatureCollection", "name": "site_exposure", "features": features,
           "metadata": {"basis": "theory_only_unvalidated", "used_by_alerts": False, "notification_eligible": False,
                        "note": "Exposure index from OSM-mask fetch, DSM shelter and SPM 1984 waves; not a hazard forecast."}}
    (run_dir / "site_exposure.geojson").write_text(json.dumps(geo, ensure_ascii=False, default=_json_default), encoding="utf-8")

    manifest = {
        "run_name": run_name, "created_at": datetime.now(timezone.utc).isoformat(), **se.FLAGS,
        "counts": summary["kind"].value_counts().to_dict(),
        "inputs": {
            "water_mask": {"path": str(paths.WATER_SHAPEFILE), "sha256": sha256(paths.WATER_SHAPEFILE), "extent": layers.extent},
            "dem": {"dir": str(layers.dem_dir), "tiles": {t: sha256(layers.dem_dir / f"{t}.tif") for t in DEM_TILES},
                    "source": "Copernicus DEM GLO-30 DSM, 1 arc-second, EGM2008"},
            "etopo": {"path": str(ETOPO_FILE), "sha256": sha256(ETOPO_FILE)},
            "marine_2024": {"dir": str(MARINE_DIR), "current_unit_source": "km/h (divided by 3.6)",
                            "model": "Open-Meteo marine: MeteoFrance SMOC currents 0.08 deg (Eulerian + waves + tides), MFWAM waves"},
            "era5_wind": {"path": str(era5_file), "sha256": sha256(era5_file)},
            "ibtracs": {"path": str(ibtracs_file)},
            "osm_farms": {"path": str(OSM_FEATURES), "sha256": sha256(OSM_FEATURES)},
        },
        "parameters": {"fetch_step_m": FETCH_STEP_M, "fetch_max_m": FETCH_MAX_M, "straight_fetch": "median of rays at -6/0/+6 deg",
                       "saville_offsets_deg": list(se.SAVILLE_OFFSETS), "shelter_step_m": SHELTER_STEP_M,
                       "shelter_max_m": SHELTER_MAX_M, "shelter_spread_deg": list(SHELTER_SPREAD),
                       "shelter_curve_xH": list(se.SHELTER_XH), "shelter_curve_frac": list(se.SHELTER_FRAC),
                       "shelter_floor": se.SHELTER_FLOOR, "duration_h": se.DEFAULT_DURATION_H,
                       "reference_winds_ms": REFERENCE_WINDS, "grid_bounds": GRID_BOUNDS, "grid_step_deg": GRID_STEP_DEG,
                       "rankine_inflow_deg": 20.0, "current_for_tier": "2024 p95 at nearest Open-Meteo marine point",
                       "dangerous_direction_rule": f"Hs at open cấp 10 (24.5 m/s) >= {DANGEROUS_HS_M} m (NS 9415 class D+)",
                       "watch_direction_rule": f"Hs at open cấp 10 in [{NACA_FLOATING_HS_M}, {DANGEROUS_HS_M}) m (above NACA/FAO 1989 floating-cage 1.0 m)"},
        "outputs": sorted(p.name for p in run_dir.iterdir()) + ["manifest.json"],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=_json_default), encoding="utf-8")
    return run_dir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download-dem")
    d.add_argument("--stamp", default=f"{date.today():%Y%m%d}")
    sub.add_parser("download-era5-wind")
    r = sub.add_parser("run")
    r.add_argument("--run-name", default="site-exposure-20261023")
    r.add_argument("--no-grid", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "download-dem":
        print(json.dumps(download_dem(args.stamp), indent=2))
    elif args.cmd == "download-era5-wind":
        print(json.dumps(download_era5_wind(date.today()), indent=2, ensure_ascii=False)[:2000])
    else:
        print(run(args.run_name, grid=not args.no_grid))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
