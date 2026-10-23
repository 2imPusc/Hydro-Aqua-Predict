from app.network import add_current_influence


def test_regional_point_never_claims_dynamic_influence():
    network = {"type": "FeatureCollection", "features": [], "influence_status": "unavailable", "influence_reason": "current_grid_required"}
    current = {"kind": "regional_point", "geojson": {"type": "FeatureCollection", "features": []}}
    result = add_current_influence(network, current)
    assert result["influence_status"] == "unavailable"
    assert result["influence_reason"] == "current_grid_required"


def test_vector_grid_adds_only_exploratory_influence():
    network = {
        "type": "FeatureCollection", "influence_status": "unavailable", "influence_reason": "current_grid_required",
        "features": [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[107.0, 20.7], [107.02, 20.7]]}, "properties": {"station_a": "A", "station_b": "B"}}],
    }
    current = {"kind": "vector_grid", "geojson": {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [107.01, 20.7]}, "properties": {"u_m_s": 0.3, "v_m_s": 0.0}}]}}
    result = add_current_influence(network, current)
    assert result["influence_status"] == "exploratory"
    assert result["features"][0]["properties"]["influence_status"] == "exploratory"
    assert result["features"][0]["properties"]["forward_alignment"] > 0.9
