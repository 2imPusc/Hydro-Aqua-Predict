import pytest

from app.providers import display_bearing, normalize_current_speed, unavailable_layer


def test_meteorological_from_direction_is_converted_for_display():
    assert display_bearing(0) == 180
    assert display_bearing(270) == 90


def test_unavailable_layer_never_contains_invented_geometry():
    layer = unavailable_layer("bathymetry", "gebco_subset_not_configured")
    assert layer["status"] == "unavailable"
    assert layer["geojson"] is None
    assert layer["raster"] is None


def test_current_velocity_is_normalized_from_documented_default_kmh():
    assert normalize_current_speed(3.6, "km/h") == pytest.approx(1.0)
    assert normalize_current_speed(1.0, "m/s") == pytest.approx(1.0)


def test_missing_current_velocity_is_not_treated_as_calm():
    assert normalize_current_speed(None, "km/h") is None

def test_advisory_forecast_layer_contract():
    from app.schemas import LayerPayload
    payload = {
        "layer": "advisory_forecast",
        "kind": "point_cloud",
        "status": "fresh",
        "geojson": {
            "type": "FeatureCollection",
            "features": [{"geometry": {"type": "Point", "coordinates": [107.0, 20.7]}, "properties": {"rain_6h_mm": 5.0}}]
        }
    }
    layer = LayerPayload.model_validate(payload)
    assert layer.layer == "advisory_forecast"
    assert layer.kind == "point_cloud"
