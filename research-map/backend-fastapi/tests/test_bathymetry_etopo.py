from __future__ import annotations

import numpy as np
import xarray as xr
from shapely.geometry import box

from app import bathymetry_etopo as etopo


def _raw(tmp_path):
    lon = np.round(np.arange(107.0, 107.1001, 0.01), 5)
    lat = np.round(np.arange(20.7, 20.8001, 0.01), 5)
    xx, yy = np.meshgrid(lon, lat)
    z = -(5.0 + (20.8 - yy) * 300)           # 5 m (north) to 35 m (south, open sea)
    z[7:9, 2:4] = -90.0                       # enclosed bogus hole in the "bay"
    z[5, 8] = 3.0                              # an ETOPO land cell inside OSM water
    path = tmp_path / "etopo.nc"
    xr.Dataset({"z": (("lat", "lon"), z.astype("float32"))}, coords={"lat": lat, "lon": lon}).to_netcdf(path, engine="h5netcdf")
    return path


def test_suspect_mask_flags_only_enclosed_deep_basins():
    depth = np.full((6, 6), 10.0)
    depth[0, :] = 40.0                         # open-sea edge row, deep but connected
    depth[3:5, 3] = 80.0                       # enclosed hole
    mask = etopo.suspect_mask(depth)
    assert mask[3, 3] and mask[4, 3]
    assert not mask[0, 0]


def test_upsample_bilinear_keeps_nodes():
    values = np.array([[0.0, 2.0], [4.0, 6.0]])
    fine = etopo.upsample_bilinear(values, 4)
    assert fine.shape == (5, 5)
    assert fine[0, 0] == 0 and fine[-1, -1] == 6 and np.isclose(fine[2, 2], 3.0)


def test_etopo_artifact_is_water_clipped_flagged_and_write_once(tmp_path):
    water = box(106.99, 20.69, 107.11, 20.81).difference(box(107.0, 20.76, 107.02, 20.81))
    cache = str(tmp_path / "cache")
    manifest = etopo.ensure_etopo_artifact(cache, str(_raw(tmp_path)), water=water)
    assert manifest["status"] == "ready"
    assert manifest["coarse_cell_count"] == 1
    assert manifest["suspect_cell_count"] >= 4
    bands = etopo.load_geojson(cache, manifest, "isobands", "high")
    assert bands["features"] and all(f["properties"]["kind"] == "etopo_isoband" for f in bands["features"])
    assert {f["properties"]["confidence"] for f in bands["features"]} == {"ok", "coarse", "suspect"}
    flags = {f["properties"]["flag"] for f in etopo.load_geojson(cache, manifest, "flags", "high")["features"]}
    assert flags == {"coarse", "suspect"}
    lines = etopo.load_geojson(cache, manifest, "isobaths", "high")
    assert {f["properties"]["depth_m"] for f in lines["features"]} >= {10.0, 20.0}
    point = etopo.sample(cache, manifest, 107.05, 20.76)  # 5 + 0.04*300 = 17 m
    assert point["status"] == "available" and abs(point["etopo_depth_m"] - 17.0) < 0.2
    assert etopo.sample(cache, manifest, 108.0, 20.72)["reason_code"] == "outside_etopo_extent"
    # Second call must reuse the keyed folder, never rebuild it.
    stamp = (tmp_path / "cache" / "bathymetry-etopo" / manifest["artifact_key"] / "manifest.json").stat().st_mtime_ns
    again = etopo.ensure_etopo_artifact(cache, str(tmp_path / "etopo.nc"), water=water)
    assert again["artifact_key"] == manifest["artifact_key"]
    assert (tmp_path / "cache" / "bathymetry-etopo" / manifest["artifact_key"] / "manifest.json").stat().st_mtime_ns == stamp
    assert etopo.load_manifest(cache)["artifact_key"] == manifest["artifact_key"]


def test_missing_file_is_unavailable(tmp_path):
    result = etopo.ensure_etopo_artifact(str(tmp_path), str(tmp_path / "nope.nc"), water=box(0, 0, 1, 1))
    assert result == {"status": "unavailable", "reason_code": "etopo_bathymetry_file_missing", "raw_path": "nope.nc"}
