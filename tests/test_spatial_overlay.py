from shapely.geometry import MultiPolygon, Point, box, shape

import pandas as pd
import pytest

from core.spatial_overlay import display_water_position, geodesic_disk, legacy_hsi_demo_overlays, water_clipped_band, water_path_band, water_path_nearest_partition


def test_geodesic_disk_has_expected_center_area():
    disk = geodesic_disk(107.04, 20.72, 5)
    assert disk.is_valid
    assert disk.contains(disk.representative_point())


def test_water_clipped_band_excludes_land(monkeypatch):
    water = box(107.0, 20.70, 107.20, 20.85)
    monkeypatch.setattr("core.spatial_overlay.local_water_geometry", lambda *_: water)
    result = water_clipped_band(107.04, 20.72, 0, 5)
    geometry = shape(result)
    assert geometry.difference(water).is_empty


def test_water_path_band_does_not_cross_an_island_gap(monkeypatch):
    origin_water = box(107.000, 20.700, 107.010, 20.710)
    disconnected_water = box(107.016, 20.700, 107.026, 20.710)
    water = MultiPolygon([origin_water, disconnected_water])
    monkeypatch.setattr("core.spatial_overlay.local_water_geometry", lambda *_: water)

    result = water_path_band(107.005, 20.705, 0, 5, grid_m=100)

    assert result is not None
    geometry = shape(result)
    assert geometry.intersects(origin_water)
    assert not geometry.intersects(disconnected_water)


def test_display_position_snaps_land_marker_to_nearest_water():
    water = box(107.000, 20.700, 107.010, 20.710)

    position = display_water_position(107.015, 20.705, water_wgs84=water)

    assert position["offset_m"] > 0
    assert water.covers(Point(position["longitude"], position["latitude"]))


def test_water_path_partition_has_one_deterministic_owner_per_cell():
    water = box(107.000, 20.700, 107.030, 20.715)
    stations = pd.DataFrame([
        {"station": "A", "longitude": 107.005, "latitude": 20.707},
        {"station": "B", "longitude": 107.025, "latitude": 20.707},
    ])
    result = water_path_nearest_partition(stations, max_distance_km=2, grid_m=500, water_wgs84=water)
    assert result is not None
    owners = result["owner"][result["water_mask"] & (result["distance_m"] <= 2000)]
    assert set(owners) <= {"A", "B"}
    assert {"A", "B"}.issubset(set(owners))


@pytest.mark.requires_data
def test_legacy_demo_builds_all_complete_historical_stations():
    period, overlays = legacy_hsi_demo_overlays()
    assert period == "2024-11-01"
    assert len(overlays) == 14
    assert {item["station"] for item in overlays} >= {"NB1", "NB2", "NB3"}
    assert all(item["mode"] == "legacy_hsi_demo_not_validated" for item in overlays)
    assert all(item["distance_metric"] == "euclidean_vn2000" and item["land_clipped"] for item in overlays)
    assert all(item["confidence"]["kind"] == "heuristic_not_calibrated" for item in overlays)
