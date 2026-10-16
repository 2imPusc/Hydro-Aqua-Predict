"""Collect the gridded layers that direction 3 (site suitability, HP + QN) lacks.

Mirrors the inputs of Ghaderi (2026, RSMA 101:105287) where a free source exists:
  SWH, SCS, current direction (CSCD), SST  -> Open-Meteo Marine, hourly, ~1/12 deg sea grid
  WS                                       -> Open-Meteo Archive (ERA5), hourly, 0.25 deg grid
  DEP                                      -> ETOPO1 (NOAA ERDDAP, 1 arc-min)
  DfP, DfPA, validation farms              -> OpenStreetMap (Overpass)
  DfS                                      -> existing OSM water polygons (paths.WATER_SHAPEFILE)
SSS and water quality come from our own in-situ monitoring (data/<region>/clean_data.csv).
Marine traffic (AIS) has no free source and is not collected.

Outputs go to paths.SUITABILITY_LAYERS_DIR / <year>/ and are never overwritten.

    python experiments/suitability_collect_layers.py --year 2024
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402

BBOX = (106.55, 20.45, 108.25, 21.65)  # min_lon, min_lat, max_lon, max_lat: Hai Phong + Quang Ninh waters
MARINE_STEP = 1 / 12
WIND_STEP = 0.25
MARINE_VARS = ("wave_height", "ocean_current_velocity", "ocean_current_direction", "sea_surface_temperature")
BATCH = 40
USER_AGENT = "Hydro-Aqua-Predict research (direction 3 site suitability)"


def grid(bbox: tuple[float, float, float, float], step: float) -> pd.DataFrame:
    min_lon, min_lat, max_lon, max_lat = bbox
    lons = np.round(np.arange(min_lon, max_lon + 1e-9, step), 4)
    lats = np.round(np.arange(min_lat, max_lat + 1e-9, step), 4)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    frame = pd.DataFrame({"lat": lat_grid.ravel(), "lon": lon_grid.ravel()})
    frame.insert(0, "point_id", [f"p{i:04d}" for i in range(len(frame))])
    return frame


def sea_points(points: pd.DataFrame, water) -> pd.DataFrame:
    keep = [water is not None and water.contains(Point(lon, lat)) for lat, lon in zip(points.lat, points.lon)]
    return points[keep].reset_index(drop=True)


def classify_osm(tags: dict) -> str | None:
    if tags.get("landuse") == "aquaculture" or tags.get("seamark:type") == "marine_farm":
        return "aquaculture"
    if "harbour" in tags or tags.get("industrial") == "port" or tags.get("landuse") == "port" or tags.get("seamark:type") == "harbour":
        return "port"
    if tags.get("boundary") in {"protected_area", "national_park"} or tags.get("leisure") == "nature_reserve":
        return "protected_area"
    return None


def write_once(path: Path, writer) -> bool:
    """Run ``writer(path)`` only if ``path`` does not exist yet; never overwrite inputs."""
    if path.exists():
        print(f"exists, skipped: {path}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    writer(path)
    print(f"wrote {path}")
    return True


def _get(url: str, params: dict, retries: int = 4) -> object:
    for attempt in range(retries):
        response = requests.get(url, params=params, timeout=300, headers={"User-Agent": USER_AGENT})
        if response.status_code == 429 and attempt < retries - 1:
            time.sleep(60 * (attempt + 1))
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError("unreachable")


def _hourly_batches(url: str, points: pd.DataFrame, variables: tuple[str, ...], year: int, extra: dict) -> dict[str, pd.DataFrame]:
    columns: dict[str, dict[str, list]] = {v: {} for v in variables}
    index = None
    for start in range(0, len(points), BATCH):
        chunk = points.iloc[start:start + BATCH]
        payload = _get(url, {
            "latitude": ",".join(f"{v:.4f}" for v in chunk.lat),
            "longitude": ",".join(f"{v:.4f}" for v in chunk.lon),
            "hourly": ",".join(variables), "start_date": f"{year}-01-01", "end_date": f"{year}-12-31",
            "timezone": "UTC", **extra,
        })
        payload = payload if isinstance(payload, list) else [payload]
        for point_id, location in zip(chunk.point_id, payload):
            index = location["hourly"]["time"]
            for variable in variables:
                columns[variable][point_id] = location["hourly"][variable]
        print(f"  {url.split('/')[2]} {start + len(chunk)}/{len(points)}")
    times = pd.to_datetime(index, utc=True)
    return {v: pd.DataFrame(columns[v], index=times).rename_axis("time") for v in variables}


def fetch_osm(bbox: tuple[float, float, float, float]) -> pd.DataFrame:
    min_lon, min_lat, max_lon, max_lat = bbox
    b = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    query = f"""[out:json][timeout:180];
(
 nwr["landuse"="aquaculture"]({b}); nwr["seamark:type"="marine_farm"]({b});
 nwr["harbour"]({b}); nwr["industrial"="port"]({b}); nwr["landuse"="port"]({b}); nwr["seamark:type"="harbour"]({b});
 nwr["boundary"="protected_area"]({b}); nwr["leisure"="nature_reserve"]({b}); nwr["boundary"="national_park"]({b});
);
out tags center;"""
    for attempt in range(4):  # the public Overpass server often answers 429/504 under load
        response = requests.post("https://overpass-api.de/api/interpreter", data={"data": query}, timeout=300,
                                  headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        if response.status_code in {429, 502, 503, 504} and attempt < 3:
            time.sleep(60 * (attempt + 1))
            continue
        response.raise_for_status()
        break
    rows = []
    for element in response.json()["elements"]:
        tags = element.get("tags", {})
        kind = classify_osm(tags)
        center = element.get("center") or {"lat": element.get("lat"), "lon": element.get("lon")}
        if kind and center.get("lat") is not None:
            rows.append({"osm_type": element["type"], "osm_id": element["id"], "kind": kind, "name": tags.get("name"),
                         "lat": center["lat"], "lon": center["lon"], "tags": json.dumps(tags, ensure_ascii=False)})
    return pd.DataFrame(rows)


def fetch_etopo(bbox: tuple[float, float, float, float]) -> pd.DataFrame:
    min_lon, min_lat, max_lon, max_lat = bbox
    url = (f"https://upwell.pfeg.noaa.gov/erddap/griddap/etopo180.csv?"
           f"altitude%5B({min_lat}):1:({max_lat})%5D%5B({min_lon}):1:({max_lon})%5D")
    response = requests.get(url, timeout=300, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return pd.read_csv(io.StringIO(response.text), skiprows=[1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=2024)
    args = parser.parse_args(argv)
    out = paths.SUITABILITY_LAYERS_DIR / str(args.year)

    from core.spatial_overlay import local_water_geometry
    water = local_water_geometry(*BBOX)
    marine_points = sea_points(grid(BBOX, MARINE_STEP), water)
    wind_points = grid(BBOX, WIND_STEP)
    print(f"marine sea points: {len(marine_points)}, wind points: {len(wind_points)}")

    write_once(out / "marine_points.csv", lambda p: marine_points.to_csv(p, index=False))
    write_once(out / "wind_points.csv", lambda p: wind_points.to_csv(p, index=False))
    if not all((out / f"marine_{v}.parquet").exists() for v in MARINE_VARS):
        marine = _hourly_batches("https://marine-api.open-meteo.com/v1/marine", marine_points, MARINE_VARS, args.year, {"cell_selection": "sea"})
        for variable, frame in marine.items():
            write_once(out / f"marine_{variable}.parquet", frame.to_parquet)
    if not (out / "wind_speed_10m.parquet").exists():
        wind = _hourly_batches("https://archive-api.open-meteo.com/v1/archive", wind_points, ("wind_speed_10m",), args.year, {"wind_speed_unit": "ms"})
        write_once(out / "wind_speed_10m.parquet", wind["wind_speed_10m"].to_parquet)
    write_once(paths.SUITABILITY_LAYERS_DIR / "etopo1_bathymetry.csv", lambda p: fetch_etopo(BBOX).to_csv(p, index=False))
    write_once(paths.SUITABILITY_LAYERS_DIR / "osm_features.csv", lambda p: fetch_osm(BBOX).to_csv(p, index=False))
    write_once(out / "manifest.json", lambda p: p.write_text(json.dumps({
        "retrieved_at": datetime.now(timezone.utc).isoformat(), "year": args.year, "bbox": BBOX,
        "marine_step_deg": MARINE_STEP, "wind_step_deg": WIND_STEP, "marine_vars": MARINE_VARS,
        "sources": {"marine": "Open-Meteo Marine API (cell_selection=sea)", "wind": "Open-Meteo Archive (ERA5)",
                    "bathymetry": "NOAA ETOPO1 via ERDDAP etopo180", "osm": "Overpass API"},
        "reference": "Ghaderi 2026, Regional Studies in Marine Science 101:105287",
    }, indent=2), encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
