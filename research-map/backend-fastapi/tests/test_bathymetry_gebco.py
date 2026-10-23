from __future__ import annotations

import numpy as np
import xarray as xr
from shapely.geometry import box

from app import bathymetry_gebco as gebco


def _raw(tmp_path):
    lon = np.round(np.arange(107.0, 107.1001, 0.01), 5)
    lat = np.round(np.arange(20.7, 20.8001, 0.01), 5)
    xx, yy = np.meshgrid(lon, lat)
    z = -(5.0 + (20.8 - yy) * 300)
    z[7:9, 2:4] = -90.0                        # enclosed bogus hole
    z[5, 8] = 3.0                               # land cell inside OSM water
    tid = np.full(z.shape, 44, dtype="int8")   # interpolated everywhere ...
    tid[:, :5] = 11                             # ... except a measured western strip
    tid[z >= 0] = 0
    path = tmp_path / "gebco.nc"
    xr.Dataset({"elevation": (("lat", "lon"), z.astype("float32")), "tid": (("lat", "lon"), tid)},
               coords={"lat": lat, "lon": lon}).to_netcdf(path, engine="h5netcdf")
    return path


def test_tid_class_groups():
    cls = gebco.tid_class(np.array([0, 10, 17, 18, 39, 40, 45, 46, 70]))
    assert cls.tolist() == [0, 1, 1, 0, 0, 2, 2, 0, 0]


def test_gebco_artifact_has_tid_confidence_and_is_write_once(tmp_path):
    water = box(106.99, 20.69, 107.11, 20.81)
    cache = str(tmp_path / "cache")
    manifest = gebco.ensure_gebco_artifact(cache, str(_raw(tmp_path)), water=water)
    assert manifest["status"] == "ready"
    assert manifest["direct_cell_count"] > 0 and manifest["indirect_cell_count"] > 0
    assert manifest["coarse_cell_count"] == 1 and manifest["suspect_cell_count"] >= 4
    bands = gebco.load_geojson(cache, manifest, "isobands", "high")
    assert all(f["properties"]["kind"] == "gebco_isoband" for f in bands["features"])
    assert {"direct", "indirect", "suspect", "coarse"} <= {f["properties"]["confidence"] for f in bands["features"]}
    assert {f["properties"]["flag"] for f in gebco.load_geojson(cache, manifest, "flags", "high")["features"]} == {"coarse", "suspect"}
    west = gebco.sample(cache, manifest, 107.02, 20.76)
    east = gebco.sample(cache, manifest, 107.09, 20.76)
    assert west["tid_confidence"] == "direct" and east["tid_confidence"] == "indirect"
    assert abs(west["gebco_depth_m"] - 17.0) < 0.2
    assert gebco.sample(cache, manifest, 108.0, 20.72)["reason_code"] == "outside_gebco_extent"
    stamp = (tmp_path / "cache" / "bathymetry-gebco" / manifest["artifact_key"] / "manifest.json").stat().st_mtime_ns
    again = gebco.ensure_gebco_artifact(cache, str(tmp_path / "gebco.nc"), water=water)
    assert again["artifact_key"] == manifest["artifact_key"]
    assert (tmp_path / "cache" / "bathymetry-gebco" / manifest["artifact_key"] / "manifest.json").stat().st_mtime_ns == stamp
    assert gebco.load_manifest(cache)["artifact_key"] == manifest["artifact_key"]


def test_missing_file_is_unavailable(tmp_path):
    result = gebco.ensure_gebco_artifact(str(tmp_path), str(tmp_path / "nope.nc"), water=box(0, 0, 1, 1))
    assert result["reason_code"] == "gebco_bathymetry_file_missing"
