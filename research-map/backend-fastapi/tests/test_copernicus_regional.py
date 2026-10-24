from __future__ import annotations

import numpy as np
import xarray as xr

from app import copernicus


def test_cells_skip_land_nan_and_keep_lattice():
    lat = np.array([20.5, 20.58333]); lon = np.array([107.0, 107.08333, 107.16667])
    a = xr.DataArray(np.array([[1.0, np.nan, 3.0], [4.0, 5.0, 6.0]]), coords={"latitude": lat, "longitude": lon}, dims=("latitude", "longitude"))
    cells = list(copernicus._cells(a))
    assert len(cells) == 5 and (107.08333, 20.5, [np.nan]) not in cells
    assert copernicus._step(a) == 0.08333


def test_no_credentials_means_no_cmems_layers(tmp_path, monkeypatch):
    placeholder = tmp_path / "creds"
    placeholder.write_text("")  # compose mounts an empty placeholder when CMEMS is not configured
    monkeypatch.setattr(copernicus, "CREDENTIALS_FILE", placeholder)
    layers = copernicus.fetch_copernicus_layers(username="", password="", current_dataset="x", sea_level_dataset="", mld_dataset="", wave_dataset="y",
                                                bbox=[107, 20, 108, 21], stale_minutes=90, buffer_m=5000, cache_dir=str(tmp_path))
    assert layers == []
