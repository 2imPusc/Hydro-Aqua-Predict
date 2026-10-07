from shapely.geometry import Point, shape

from app.domain import build_context_domain, station_records


def test_context_domain_is_deterministic_and_contains_station_hull():
    first = build_context_domain(5000)
    second = build_context_domain(5000)
    assert first["geometry_hash"] == second["geometry_hash"]
    assert first["station_count"] == len(station_records()) == 14
    boundary = shape(next(item["geometry"] for item in first["features"] if item["properties"]["kind"] == "context_domain_boundary"))
    for station in station_records():
        assert boundary.covers(Point(station["longitude"], station["latitude"]))


def test_water_feature_reports_whether_mask_was_applied():
    domain = build_context_domain(5000)
    water = next(item for item in domain["features"] if item["properties"]["kind"] == "context_domain_water")
    assert water["properties"]["water_clipped"] == domain["water_clipped"]
    assert not shape(water["geometry"]).is_empty

