from core.contextual_models import predict_haiphong_contextual

def test_shadow_model_is_disabled_until_nh4_conversion_is_confirmed(monkeypatch):
    monkeypatch.setattr("core.contextual_models.NH4_CONVERSION_CONFIRMED", False)
    result = predict_haiphong_contextual({"NH3": .01, "pH": 7.8, "Temperature": 29, "TSS": 10}, "2026-07-25T00:00:00Z")
    assert result["status"] == "disabled"
    assert result["used_by_alerts"] is False
