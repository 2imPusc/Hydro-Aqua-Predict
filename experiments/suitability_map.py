"""Direction 3: cobia cage-site suitability for Hai Phong + Quang Ninh waters.

Variant A replicates Ghaderi (2026) with the layers we have (no marine-traffic layer).
Variant B adds our in-situ water quality (DO, NH3, TSS, pH) through the repo's
cobia thresholds (hap_shared/thresholds/cobia_thresholds.json), which Ghaderi lacked.

Validation is weak by design: OSM-mapped aquaculture inside the sea polygon is compared
with all grid points (percentile of their scores). It is a sanity check, not ground truth.

    python experiments/suitability_map.py --year 2024
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point
from shapely.ops import transform as shapely_transform

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.spatial_overlay import local_water_geometry  # noqa: E402
from experiments.suitability_collect_layers import BBOX  # noqa: E402
from hap_shared.fuzzy_suitability import (  # noqa: E402
    COBIA_RANGES, GHADERI_WEIGHTS, METHODS, direction_stability, distance_membership, integrate, minmax,
    temporal_score, triangular,
)
from hap_shared.preprocessing import vn2000_to_wgs84  # noqa: E402  (107d45' meridian: correct for QN)

WQ_VARS = ("DO", "NH3", "TSS", "pH")
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32648", always_xy=True)  # UTM 48N, metres


def _xy(lon, lat) -> np.ndarray:
    x, y = TO_UTM.transform(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
    return np.column_stack([x, y])


def nearest_distance_km(points_xy: np.ndarray, targets_xy: np.ndarray) -> np.ndarray:
    d = np.sqrt(((points_xy[:, None, :] - targets_xy[None, :, :]) ** 2).sum(axis=2))
    return d.min(axis=1) / 1000.0


def idw(points_xy: np.ndarray, stations_xy: np.ndarray, values: np.ndarray, k: int = 5, power: float = 2.0) -> np.ndarray:
    d = np.sqrt(((points_xy[:, None, :] - stations_xy[None, :, :]) ** 2).sum(axis=2))
    order = np.argsort(d, axis=1)[:, :k]
    dk = np.take_along_axis(d, order, axis=1).clip(min=1.0)
    w = 1.0 / dk ** power
    return (w * values[order]).sum(axis=1) / w.sum(axis=1)


def piecewise(x, breakpoints) -> np.ndarray:
    xs, ys = zip(*breakpoints)
    return np.interp(np.asarray(x, dtype=float), xs, ys)


def station_medians() -> pd.DataFrame:
    """Per-station medians (2020-2024 quarters) for HP and QN with WGS84 coordinates."""
    coords_hp = pd.read_csv(paths.STATION_COORDINATES)[["Station", "Lat", "Lon"]]
    hp = pd.read_csv(paths.clean_data("haiphong")).merge(coords_hp, on="Station", how="left")
    qn = pd.read_csv(paths.clean_data("quangninh"))
    qn_xy = qn.groupby("Station")[["X", "Y"]].first()
    lat, lon = vn2000_to_wgs84(qn_xy["X"].to_numpy(), qn_xy["Y"].to_numpy())
    qn = qn.merge(pd.DataFrame({"Station": qn_xy.index, "Lat": lat, "Lon": lon}), on="Station")
    hp["Station"], qn["Station"] = "HP_" + hp["Station"], "QN_" + qn["Station"]
    both = pd.concat([hp, qn], ignore_index=True)
    return both.groupby("Station").agg(Lat=("Lat", "first"), Lon=("Lon", "first"),
                                       **{v: (v, "median") for v in ("Salinity", *WQ_VARS)}).reset_index()


def build_criteria(year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    root, layers = paths.SUITABILITY_LAYERS_DIR, paths.SUITABILITY_LAYERS_DIR / str(year)
    pts = pd.read_csv(layers / "marine_points.csv").set_index("point_id")
    pxy = _xy(pts.lon, pts.lat)
    raw = pd.DataFrame(index=pts.index)
    fuzzy = pd.DataFrame(index=pts.index)

    def series(name: str) -> pd.DataFrame:
        return pd.read_parquet(layers / f"marine_{name}.parquet")[pts.index]

    swh, scs, sst = series("wave_height"), series("ocean_current_velocity") / 3.6, series("sea_surface_temperature")
    raw["SWH"], raw["SCS"], raw["SST"] = swh.mean(), scs.mean(), sst.mean()  # SCS: API gives km/h, /3.6 -> m/s
    for name, frame in (("SWH", swh), ("SCS", scs), ("SST", sst)):
        fuzzy[name] = minmax(temporal_score(frame, *COBIA_RANGES[name]))
    fuzzy["CSCD"] = minmax(direction_stability(series("ocean_current_direction")))

    wind_pts = pd.read_csv(layers / "wind_points.csv")
    wind = pd.read_parquet(layers / "wind_speed_10m.parquet")
    nearest = np.argmin(((pxy[:, None, :] - _xy(wind_pts.lon, wind_pts.lat)[None, :, :]) ** 2).sum(axis=2), axis=1)
    ws = wind[wind_pts.point_id.to_numpy()[nearest]]
    ws.columns = pts.index
    raw["WS"] = ws.mean()
    fuzzy["WS"] = minmax(temporal_score(ws, *COBIA_RANGES["WS"]))

    etopo = pd.read_csv(root / "etopo1_bathymetry.csv")
    near_cell = np.argmin(((pxy[:, None, :] - _xy(etopo.longitude, etopo.latitude)[None, :, :]) ** 2).sum(axis=2), axis=1)
    raw["DEP"] = (-etopo.altitude.to_numpy()[near_cell]).clip(min=0)
    fuzzy["DEP"] = triangular(raw["DEP"], *COBIA_RANGES["DEP"])

    water = local_water_geometry(*BBOX)
    shore = water.boundary
    shore_utm = shapely_transform(lambda x, y, z=None: TO_UTM.transform(x, y), shore)
    raw["DfS"] = [shore_utm.distance(Point(x, y)) / 1000.0 for x, y in pxy]
    fuzzy["DfS"] = triangular(raw["DfS"], *COBIA_RANGES["DfS"])

    osm = pd.read_csv(root / "osm_features.csv")
    for code, kind, closer in (("DfP", "port", True), ("DfPA", "protected_area", False)):
        sub = osm[osm.kind == kind]
        raw[code] = nearest_distance_km(pxy, _xy(sub.lon, sub.lat))
        fuzzy[code] = distance_membership(raw[code], closer_is_better=closer)

    stations = station_medians()
    sxy = _xy(stations.Lon, stations.Lat)
    raw["SSS"] = idw(pxy, sxy, stations.Salinity.to_numpy())
    fuzzy["SSS"] = triangular(raw["SSS"], *COBIA_RANGES["SSS"])
    thresholds = json.loads((Path(paths.PROJECT_ROOT) / "hap_shared" / "thresholds" / "cobia_thresholds.json").read_text(encoding="utf-8"))
    fuzzy["SSS_repo"] = piecewise(raw["SSS"], thresholds["Salinity"]["breakpoints"])
    for v in WQ_VARS:
        raw[v] = idw(pxy, sxy, stations[v].to_numpy())
        fuzzy[f"WQ_{v}"] = piecewise(raw[v], thresholds[v]["breakpoints"])
    raw[["lat", "lon"]] = pts[["lat", "lon"]]
    return raw, fuzzy


def score_variants(fuzzy: pd.DataFrame) -> pd.DataFrame:
    base = ["SWH", "WS", "SST", "SSS", "DEP", "DfS", "SCS", "CSCD", "DfP", "DfPA"]
    with_wq = base + [f"WQ_{v}" for v in WQ_VARS]
    wq_weight = float(np.mean([GHADERI_WEIGHTS[c] for c in base]))
    weights_wq = {**GHADERI_WEIGHTS, **{f"WQ_{v}": wq_weight for v in WQ_VARS}}
    out = pd.DataFrame(index=fuzzy.index)
    for method, gamma in METHODS.items():
        out[f"A_{method}"] = integrate(fuzzy[base], gamma)
        out[f"A_W_{method}"] = integrate(fuzzy[base], gamma, GHADERI_WEIGHTS)
        out[f"B_W_{method}"] = integrate(fuzzy[with_wq], gamma, weights_wq)
    return out


def validate(scores: pd.DataFrame, raw: pd.DataFrame, max_km: float = 5.0) -> pd.DataFrame:
    osm = pd.read_csv(paths.SUITABILITY_LAYERS_DIR / "osm_features.csv")
    water = local_water_geometry(*BBOX)
    in_sea = np.array([water.contains(Point(lon, lat)) for lat, lon in zip(osm.lat, osm.lon)], dtype=bool)
    farms = osm[(osm.kind == "aquaculture").to_numpy() & in_sea]
    pxy, fxy = _xy(raw.lon, raw.lat), _xy(farms.lon, farms.lat)
    rows = []
    if len(farms):
        d = np.sqrt(((fxy[:, None, :] - pxy[None, :, :]) ** 2).sum(axis=2))
        near = d.argmin(axis=1)[d.min(axis=1) / 1000.0 <= max_km]
        for column in scores:
            pct = scores[column].rank(pct=True).to_numpy()[near]
            rows.append({"variant": column, "n_farms_marine": int(len(farms)), "n_matched": int(len(near)),
                         "mean_percentile": float(np.mean(pct)) if len(near) else np.nan})
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--run", default=None, help="output folder name under EXPERIMENT_OUTPUT_DIR")
    args = parser.parse_args(argv)
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / (args.run or f"suitability-h3-{args.year}")
    if run_dir.exists():
        print(f"exists, not overwritten: {run_dir}")
        return 1
    raw, fuzzy = build_criteria(args.year)
    scores = score_variants(fuzzy)
    check = validate(scores, raw)
    run_dir.mkdir(parents=True)
    raw.to_csv(run_dir / "criteria_raw.csv")
    fuzzy.to_csv(run_dir / "criteria_fuzzy.csv")
    scores.join(raw[["lat", "lon"]]).to_csv(run_dir / "scores.csv")
    check.to_csv(run_dir / "validation_osm_farms.csv", index=False)
    print(raw.describe().T[["mean", "min", "max"]].round(2).to_string())
    print(fuzzy.describe().T[["mean", "min", "max"]].round(2).to_string())
    print(check.round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
