import csv
import io
import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from scripts.vn_public.common import NB1_LAT, NB1_LON, haversine_km, manifest_path, write_manifest, write_once_bytes
from scripts.vn_public.fetch_documents import parse_angle, sampling_points_csv
from scripts.vn_public.fetch_ocean_colour import nearest_usable, pixel_usability


def test_parse_angle_decimal_minutes_and_dms():
    assert parse_angle("20°44.388'") == pytest.approx(20 + 44.388 / 60)
    assert parse_angle("107°3'35.41\"") == pytest.approx(107 + 3 / 60 + 35.41 / 3600)
    # the two papers' CB1 (decimal minutes vs DMS) are the same site within ~200 m
    a = (parse_angle("20°44.388'"), parse_angle("107°03.595'"))
    b = (parse_angle("20°44'18.25\""), parse_angle("107°3'35.41\""))
    assert haversine_km(*a, *b) < 0.2


@pytest.mark.parametrize("bad", ["20.5", "20°61'", "20°44'61\"", "abc"])
def test_parse_angle_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        parse_angle(bad)


def test_sampling_points_csv_distances():
    rows = list(csv.DictReader(io.StringIO(sampling_points_csv())))
    assert len(rows) == 9
    hang_vem = [float(r["dist_nb1_km"]) for r in rows if r["zone"] == "Hang Vẹm - Vụng O"]
    assert all(2.5 < d < 3.2 for d in hang_vem)
    thoi_quyt = [float(r["dist_nb1_km"]) for r in rows if r["zone"].startswith("Hòn Thoi Quýt")]
    assert all(16 < d < 18 for d in thoi_quyt)


def test_write_once_and_manifest(tmp_path):
    target = tmp_path / "a" / "x.bin"
    write_once_bytes(target, b"abc")
    with pytest.raises(FileExistsError):
        write_once_bytes(target, b"zzz")
    assert target.read_bytes() == b"abc"
    m = write_manifest(target, url="u", terms="t")
    rec = json.loads(m.read_text(encoding="utf-8"))
    assert rec["bytes"] == 3 and rec["url"] == "u"
    assert rec["sha256"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert m == manifest_path(target)
    with pytest.raises(FileExistsError):
        write_manifest(target, url="again")


def test_pixel_usability_picks_nearest_pixel_with_enough_data():
    lats = np.array([NB1_LAT, NB1_LAT + 0.1])
    lons = np.array([NB1_LON, NB1_LON + 0.1])
    data = np.full((20, 2, 2), np.nan)
    data[0, 0, 0] = 1.0           # pixel on NB1: 1/20 = 5 %
    data[:10, 1, 1] = 2.0         # far pixel: 50 %
    da = xr.DataArray(data, dims=("time", "latitude", "longitude"),
                      coords={"time": pd.date_range("2025-01-01", periods=20), "latitude": lats, "longitude": lons})
    use = pixel_usability(da)
    assert use.iloc[0]["dist_km"] == pytest.approx(0, abs=1e-6)
    assert use.iloc[0]["valid_frac"] == pytest.approx(0.05)
    assert nearest_usable(use, 0.05)["dist_km"] == pytest.approx(0, abs=1e-6)
    best = nearest_usable(use, 0.10)
    assert best["valid_days"] == 10 and best["lat"] == pytest.approx(NB1_LAT + 0.1)
    assert nearest_usable(use, 0.9) is None
