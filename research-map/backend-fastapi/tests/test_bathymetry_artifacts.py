from __future__ import annotations

import xarray as xr
from shapely.geometry import box

from app import bathymetry_artifacts as artifacts


def _raw_file(tmp_path):
    dataset = xr.Dataset(
        {
            "height": (("latitude", "longitude"), [[-1.0, -2.0, 0.2, -4.0], [-1.5, -2.5, -3.5, -4.5], [-1.0, -2.0, -3.0, -4.0], [-1.0, -2.0, -3.0, -4.0]]),
            "Quality_indicator": (("latitude", "longitude"), [[0, 1, 0, 3], [2, 0, 1, 4], [0, 1, 2, 0], [0, 1, 2, 0]]),
            "SDB_type": (("latitude", "longitude"), [[1, 2, 1, 3], [0, 1, 2, 4], [1, 2, 3, 4], [0, 1, 2, 3]]),
        },
        coords={"latitude": [20.0, 20.01, 20.02, 20.03], "longitude": [107.0, 107.01, 107.02, 107.03]},
    )
    path = tmp_path / "source.nc"
    dataset.to_netcdf(path, engine="h5netcdf")
    return path


def test_bathymetry_filters_quality_and_samples_only_water(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "build_context_domain", lambda _buffer: {"geometry_hash": "domain-a"})
    monkeypatch.setattr(artifacts, "water_geometry_for_bounds", lambda *_bounds: box(106.99, 19.99, 107.04, 20.04))
    manifest = artifacts.ensure_bathymetry_artifact(str(tmp_path / "cache"), str(_raw_file(tmp_path)), 5000)

    assert manifest["status"] == "ready"
    # Positive height and quality flags 3/4 must never become water-depth data.
    assert manifest["valid_pixel_count"] == 13
    assert artifacts.sample(str(tmp_path / "cache"), manifest, 107.0, 20.0)["status"] == "available"
    assert artifacts.sample(str(tmp_path / "cache"), manifest, 107.03, 20.0)["reason_code"] == "copernicus_coverage_missing_or_not_water"


def test_bathymetry_cache_key_changes_with_geometry(tmp_path, monkeypatch):
    raw = _raw_file(tmp_path)
    monkeypatch.setattr(artifacts, "water_geometry_for_bounds", lambda *_bounds: box(106.99, 19.99, 107.04, 20.04))
    monkeypatch.setattr(artifacts, "build_context_domain", lambda _buffer: {"geometry_hash": "domain-a"})
    first = artifacts.ensure_bathymetry_artifact(str(tmp_path / "cache"), str(raw), 5000)
    monkeypatch.setattr(artifacts, "build_context_domain", lambda _buffer: {"geometry_hash": "domain-b"})
    second = artifacts.ensure_bathymetry_artifact(str(tmp_path / "cache"), str(raw), 5000)
    assert first["artifact_key"] != second["artifact_key"]
