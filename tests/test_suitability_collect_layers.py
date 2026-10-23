from shapely.geometry import box

from experiments.suitability_collect_layers import classify_osm, grid, sea_points, write_once


def test_grid_covers_bbox_with_unique_ids():
    points = grid((106.0, 20.0, 106.5, 20.25), 0.25)
    assert len(points) == 3 * 2
    assert points.point_id.is_unique
    assert points.lon.min() == 106.0 and points.lon.max() == 106.5


def test_sea_points_keeps_only_points_inside_water():
    points = grid((106.0, 20.0, 106.5, 20.25), 0.25)
    water = box(106.2, 19.9, 106.6, 20.3)
    kept = sea_points(points, water)
    assert set(kept.lon) == {106.25, 106.5}
    assert sea_points(points, None).empty


def test_classify_osm_kinds():
    assert classify_osm({"landuse": "aquaculture"}) == "aquaculture"
    assert classify_osm({"seamark:type": "marine_farm"}) == "aquaculture"
    assert classify_osm({"harbour": "yes"}) == "port"
    assert classify_osm({"boundary": "national_park"}) == "protected_area"
    assert classify_osm({"amenity": "cafe"}) is None


def test_write_once_never_overwrites(tmp_path):
    target = tmp_path / "a" / "x.txt"
    assert write_once(target, lambda p: p.write_text("first")) is True
    assert write_once(target, lambda p: p.write_text("second")) is False
    assert target.read_text() == "first"
