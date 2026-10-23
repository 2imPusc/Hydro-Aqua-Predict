"""Pure-helper tests for experiments/cmems_sites.py (no network, no copernicusmarine needed)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from experiments import cmems_sites as cs


def test_haversine_known_distance():
    # 0.1 deg of latitude ~ 11.1 km
    assert cs.haversine_km(20.0, 107.0, 20.1, 107.0) == pytest.approx(11.12, abs=0.05)
    assert cs.haversine_km(20.0, 107.0, 20.0, 107.0) == 0.0


def test_nearest_sea_cell_skips_land():
    lats = np.array([20.5, 20.6, 20.7])
    lons = np.array([106.9, 107.0, 107.1])
    sea = np.ones((3, 3), dtype=bool)
    sea[1, 1] = False  # the cell nearest to the point is land
    i, j, d = cs.nearest_sea_cell(20.6, 107.0, lats, lons, sea)
    assert (i, j) != (1, 1)
    assert d > 0
    assert cs.nearest_sea_cell(20.5, 106.9, lats, lons, sea)[:2] == (0, 0)


def test_nearest_sea_cell_all_land_raises():
    with pytest.raises(ValueError):
        cs.nearest_sea_cell(20.6, 107.0, np.array([20.6]), np.array([107.0]), np.zeros((1, 1), dtype=bool))


def test_speed_and_percentile():
    assert cs.speed(np.array([3.0]), np.array([4.0]))[0] == 5.0
    assert cs.p95(np.arange(101.0)) == pytest.approx(95.0)
    assert np.isnan(cs.p95(np.array([np.nan])))


def test_score_signs_and_counts():
    obs = pd.Series([30.0, 31.0, 32.0, np.nan], index=pd.date_range("2026-06-01", periods=4))
    pred = pd.Series([31.0, 32.0, 33.0, 34.0], index=obs.index)
    s = cs.score(obs, pred)
    assert s["n"] == 3
    assert s["bias"] == pytest.approx(1.0)  # product - sensor
    assert s["mae"] == pytest.approx(1.0)
    assert s["r"] == pytest.approx(1.0)
    assert s["mae_demeaned"] == pytest.approx(0.0)


def test_score_too_few_points():
    s = cs.score(pd.Series([1.0]), pd.Series([1.0]))
    assert s["n"] == 1 and np.isnan(s["r"])


def test_hot_day_contingency():
    obs = pd.Series([31.5, 31.2, 29.0, 29.5])
    pred = pd.Series([31.1, 30.0, 31.2, 29.0])
    c = cs.hot_day_counts(obs, pred, 31.0)
    assert (c["H"], c["M"], c["FA"]) == (1, 1, 1)
    assert c["pod"] == 0.5 and c["far"] == 0.5 and c["csi"] == pytest.approx(1 / 3)


def test_monthly_climatology():
    idx = pd.date_range("2000-01-01", "2001-12-31", freq="D")
    ser = pd.Series(np.where(idx.month == 7, 20.0, 30.0), index=idx)
    clim = cs.monthly_climatology(ser)
    assert list(clim.index) == list(range(1, 13))
    assert clim.loc[7, "mean"] == 20.0 and clim.loc[1, "mean"] == 30.0
    assert clim.loc[1, "n"] == 62


def test_low_runs_merges_and_thresholds():
    idx = pd.date_range("2025-10-01", periods=10)
    ser = pd.Series([30, 24, 23, 26, 30, 30, 24.9, 30, 30, 30], index=idx, dtype=float)
    runs = cs.low_runs(ser, 25.0, min_days=1)
    assert len(runs) == 2
    assert runs[0]["start"] == "2025-10-02" and runs[0]["end"] == "2025-10-03"
    assert runs[0]["min"] == 23.0 and runs[0]["days"] == 2
    assert cs.low_runs(ser, 25.0, min_days=2)[0]["days"] == 2
    assert len(cs.low_runs(ser, 25.0, min_days=2)) == 1


def test_window_extreme_ignores_nan():
    ser = pd.Series([1.0, np.nan, 5.0, 2.0], index=pd.date_range("2024-09-05", periods=4))
    assert cs.window_extreme(ser, "2024-09-05", "2024-09-07", "max") == 5.0
    assert cs.window_extreme(ser, "2024-09-05", "2024-09-05", "min") == 1.0
    assert np.isnan(cs.window_extreme(ser, "2025-01-01", "2025-01-02", "max"))


def test_download_plan_names_model_and_dataset_ids():
    plan = cs.download_plan(end="2026-10-22", my_end="2026-09-22")
    keys = {p["key"] for p in plan}
    assert {"my_ts_1993", "my_uv", "anfc_thetao_d", "anfc_so_d", "anfc_hourly_sfc", "wav", "vandon_my_ts"} <= keys
    for p in plan:
        assert p["product_id"].startswith(("GLOBAL_MULTIYEAR_PHY_001_030", "GLOBAL_ANALYSISFORECAST_"))
        assert p["dataset_id"].startswith("cmems_mod_glo")
        assert p["model"]  # decisions #18: always name the model/product
        assert p["variables"] and p["start"] < p["end"]
    my = next(p for p in plan if p["key"] == "my_ts_1993")
    assert my["start"] == "1993-01-01" and my["end"] == "2026-09-22"
    assert next(p for p in plan if p["key"] == "wav")["end"] == "2026-10-22"


def test_target_path_is_under_cmems_dir_and_deterministic(tmp_path):
    plan = cs.download_plan(end="2026-10-22", my_end="2026-09-22")
    p1 = cs.target_path(plan[0], root=tmp_path)
    assert p1 == cs.target_path(plan[0], root=tmp_path)
    assert tmp_path in p1.parents and p1.suffix == ".nc"
    assert plan[0]["product_id"] in p1.parts


def test_write_manifest_has_hash_and_request(tmp_path):
    f = tmp_path / "x.nc"
    f.write_bytes(b"abc")
    entry = {"key": "k", "product_id": "P", "dataset_id": "D", "model": "M", "variables": ["so"],
             "bbox": [1, 2, 3, 4], "start": "2020-01-01", "end": "2020-01-02"}
    m = cs.write_manifest(f, entry, version="202311", tool_version="2.5.0")
    side = json.loads((tmp_path / "x.nc.manifest.json").read_text(encoding="utf-8"))
    assert side == m
    assert m["sha256"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert m["version"] == "202311" and m["bytes"] == 3
    with pytest.raises(FileExistsError):
        cs.write_manifest(f, entry, version="202311", tool_version="2.5.0")
