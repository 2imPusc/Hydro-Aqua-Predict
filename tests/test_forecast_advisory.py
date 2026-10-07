from core.forecast_advisory import evaluate_forecast_advisory


def test_low_forecast_do_is_capped_at_warning_advisory():
    future = {"status": "ready", "timeline": [{"horizon_minutes": 15, "sensors": {"Temperature": 29}, "inferred": {"DO": 2.8, "Salinity": 31}}]}
    result = evaluate_forecast_advisory(future)
    assert result["severity"] == "WARNING"
    assert result["notification_eligible"] is False
    assert result["used_by_emergency"] is False


def test_forecast_without_do_or_temperature_stress_is_normal():
    future = {"status": "ready", "timeline": [{"horizon_minutes": 15, "sensors": {"Temperature": 29}, "inferred": {}}]}
    assert evaluate_forecast_advisory(future)["severity"] == "NORMAL"


def test_advisory_returns_explainable_risk_timeline_for_each_horizon():
    future = {"status": "ready", "timeline": [
        {"horizon_minutes": 15, "timestamp": "2026-07-01T00:15:00Z", "sensors": {"Temperature": 31.2, "NH3": .06}, "sensor_sources": {"Temperature": "xgboost_time"}, "inferred": {"DO": 4.8, "Salinity": 30}, "contextual_status": "ready"},
        {"horizon_minutes": 30, "timestamp": "2026-07-01T00:30:00Z", "sensors": {"Temperature": 33.1, "NH3": .11}, "sensor_sources": {"Temperature": "xgboost_time"}, "inferred": {"DO": 3.7}, "contextual_status": "ready"},
    ]}
    result = evaluate_forecast_advisory(future)
    assert result["severity"] == "WARNING"
    assert result["earliest_horizon_minutes"] == 15
    assert [point["severity"] for point in result["timeline"]] == ["WATCH", "WARNING"]
    assert result["timeline"][1]["inputs"]["NH3"] == .11
    assert all(point["used_by_emergency"] is False for point in result["timeline"])


def test_display_interpolation_does_not_move_a_model_advisory_earlier():
    future = {"status": "ready", "timeline": [
        {"horizon_minutes": 1, "sensors": {"Temperature": 33.2}, "inferred": {}, "evaluatable": False,
         "interpolation_method": "linear_between_now_and_15m_model"},
        {"horizon_minutes": 15, "sensors": {"Temperature": 31.2}, "inferred": {}, "evaluatable": True},
    ]}
    result = evaluate_forecast_advisory(future)
    assert result["severity"] == "WATCH"
    assert result["earliest_horizon_minutes"] == 15
    assert [point["severity"] for point in result["timeline"]] == ["WARNING", "WATCH"]


def test_inferred_do_notification_requires_persistence_or_compound_stress():
    future = {"status": "ready", "timeline": [{"horizon_minutes": 15, "sensors": {"Temperature": 29, "NH3": .01}, "inferred": {"DO": 3.8}, "contextual_status": "ready"}]}
    first = evaluate_forecast_advisory(future)
    second = evaluate_forecast_advisory(future, first)
    assert first["severity"] == "WATCH"
    assert first["notification_eligible"] is False
    assert second["severity"] == "WARNING"
    assert first["notification_eligible"] is False
    assert second["notification_eligible"] is False
    assert second["notification_reason"].startswith("shadow_only")


def test_critical_inferred_do_needs_persistence_and_compound_stress():
    future = {"status": "ready", "timeline": [{"horizon_minutes": 15, "sensors": {"Temperature": 31.2, "NH3": .01}, "inferred": {"DO": 2.9}, "contextual_status": "ready"}]}
    first = evaluate_forecast_advisory(future)
    second = evaluate_forecast_advisory(future, first)
    assert first["severity"] == "WARNING"
    assert second["severity"] == "CRITICAL_ADVISORY"
    assert second["notification_eligible"] is False
    assert second["notification_reason"].startswith("shadow_only")
    assert second["used_by_emergency"] is False
