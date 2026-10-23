from __future__ import annotations

from shapely.geometry import box

from app.providers import _regional_points


def test_regional_points_cover_bbox_and_flag_water_nodes():
    water = box(107.0, 20.5, 107.3, 20.8)          # water only in part of the region
    points = _regional_points((106.5, 20.3, 107.5, 21.0), 0.125, water)
    lons = sorted({p[0] for p in points}); lats = sorted({p[1] for p in points})
    assert lons[0] == 106.5 and lons[-1] == 107.5 and len(lons) == 9
    assert lats[0] == 20.3 and lats[-1] == 20.925 and len(lats) == 6   # never past the bbox edge
    wet = [p for p in points if p[2]]
    assert 0 < len(wet) < len(points)
    assert all(106.875 <= lon <= 107.375 for lon, lat, _ in wet)       # cells touching the water box only


def test_regional_points_without_mask_are_all_water():
    points = _regional_points((107.0, 20.5, 107.25, 20.75), 0.125, None)
    assert len(points) == 9 and all(p[2] for p in points)
