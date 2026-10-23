"""GEBCO endpoints + `gebco` key in /bathymetry/sample (no Postgres, no startup hooks)."""
from dataclasses import replace

import numpy as np
import xarray as xr
from fastapi.testclient import TestClient
from shapely.geometry import box

from app import bathymetry_gebco as gebco, main
from app.settings import settings


def _raw(tmp_path):
    lon = np.round(np.arange(107.0, 107.1001, 0.01), 5)
    lat = np.round(np.arange(20.7, 20.8001, 0.01), 5)
    xx, yy = np.meshgrid(lon, lat)
    z = -(5.0 + (20.8 - yy) * 300)
    tid = np.full(z.shape, 44, dtype="int8")
    tid[:, :5] = 11
    path = tmp_path / "gebco.nc"
    xr.Dataset({"elevation": (("lat", "lon"), z.astype("float32")), "tid": (("lat", "lon"), tid)},
               coords={"lat": lat, "lon": lon}).to_netcdf(path, engine="h5netcdf")
    return path


def _client(monkeypatch, cache, raw):
    monkeypatch.setattr(main, "settings", replace(settings, cache_dir=str(cache), gebco_bathymetry_path=str(raw)))
    return TestClient(main.app)


def test_default_path_points_at_gebco_2024():
    assert settings.gebco_bathymetry_path.replace("\\", "/").endswith("data/depth/gebco2024-20261023/gebco2024_15s_hp_qn.nc")


def test_gebco_endpoints_unavailable_then_ready(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    client = _client(monkeypatch, cache, tmp_path / "missing.nc")
    body = client.get("/api/v1/bathymetry/gebco/manifest").json()
    assert body["status"] == "unavailable" and body["reason_code"] == "gebco_bathymetry_file_missing"
    assert client.get("/api/v1/bathymetry/gebco/isobands").json()["status"] == "unavailable"
    raw = _raw(tmp_path)
    client = _client(monkeypatch, cache, raw)
    assert client.get("/api/v1/bathymetry/gebco/manifest").json()["status"] == "building"
    gebco.ensure_gebco_artifact(str(cache), str(raw), water=box(106.99, 20.69, 107.11, 20.81))
    manifest = client.get("/api/v1/bathymetry/gebco/manifest").json()
    assert manifest["status"] == "ready" and manifest["depth_source"] == "gebco2024_15s"
    for kind in ("isobands", "isobaths", "flags"):
        data = client.get(f"/api/v1/bathymetry/gebco/{kind}", params={"lod": "high"}).json()
        assert data["status"] == "ready" and data["lod"] == "high" and data["type"] == "FeatureCollection"
    bands = client.get("/api/v1/bathymetry/gebco/isobands", params={"lod": "high"}).json()
    assert {"direct", "indirect"} <= {f["properties"]["confidence"] for f in bands["features"]}
    assert client.get("/api/v1/bathymetry/gebco/nope").status_code == 404
    assert client.get("/api/v1/bathymetry/gebco/isobands", params={"lod": "bogus"}).status_code == 422


def test_sample_has_gebco_key_and_keeps_etopo(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    raw = _raw(tmp_path)
    client = _client(monkeypatch, cache, raw)
    gebco.ensure_gebco_artifact(str(cache), str(raw), water=box(106.99, 20.69, 107.11, 20.81))
    body = client.get("/api/v1/bathymetry/sample", params={"lon": 107.02, "lat": 20.76}).json()
    assert body["gebco"]["status"] == "available" and body["gebco"]["tid_confidence"] == "direct"
    assert "etopo" in body
    empty = _client(monkeypatch, tmp_path / "empty", raw).get("/api/v1/bathymetry/sample", params={"lon": 107.02, "lat": 20.76}).json()
    assert empty["gebco"]["status"] == "unavailable" and "etopo" in empty
