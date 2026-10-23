import pandas as pd

from core.alerts import evaluate_aquaculture_risk


def _history(**values):
    timestamps = pd.date_range("2026-07-01T00:00:00Z", periods=4, freq="5min")
    return pd.DataFrame({"fetchedAt": timestamps, **values})


def test_temperature_warning_is_explainable_without_direct_do():
    result = evaluate_aquaculture_risk(_history(Temperature=[30, 31, 33.2, 33.4], NH3=[0.01] * 4))
    assert result["severity"] == "WARNING"
    assert result["confidence"] == "limited"
    assert any(driver["metric"] == "Temperature" for driver in result["drivers"])


def test_missing_do_cannot_create_emergency():
    result = evaluate_aquaculture_risk(_history(Temperature=[36.0] * 4, NH3=[0.01] * 4))
    assert result["severity"] == "WARNING"
    assert result["sensor_health"]["direct_do_available"] is False


def test_direct_low_do_creates_emergency():
    result = evaluate_aquaculture_risk(_history(Temperature=[29.0] * 4, NH3=[0.01] * 4, DO=[4.0, 3.8, 3.4, 2.8]))
    assert result["severity"] == "EMERGENCY"
    assert result["confidence"] == "high"


def test_rapid_do_decline_raises_warning_before_critical_level():
    result = evaluate_aquaculture_risk(_history(Temperature=[29.0] * 4, NH3=[0.01] * 4, DO=[6.0, 5.8, 5.4, 5.0]))
    assert result["severity"] == "WARNING"
    assert any(driver["metric"] == "DO_drop_15m" for driver in result["drivers"])


def test_invalid_do_is_not_used_as_emergency_evidence():
    result = evaluate_aquaculture_risk(_history(Temperature=[29.0] * 4, NH3=[0.01] * 4, DO=[99.0] * 4))
    assert result["severity"] == "NORMAL"
    assert any(driver["status"] == "invalid_sensor" for driver in result["drivers"])


def test_flatline_do_cannot_open_emergency():
    timestamps = pd.date_range("2026-07-01T00:00:00Z", periods=10, freq="3min")
    history = pd.DataFrame({"fetchedAt": timestamps, "Temperature": [29.0 + i * 0.01 for i in range(10)], "NH3": [0.01] * 10, "DO": [2.8] * 10})
    result = evaluate_aquaculture_risk(history)
    assert result["severity"] != "EMERGENCY"
    assert result["sensor_health"]["direct_do_available"] is False


def test_alert_requires_two_clean_cycles_before_resolved():
    clean = _history(Temperature=[29.0, 29.1, 29.2, 29.3], NH3=[0.01] * 4)
    previous = {"severity": "WARNING", "recovery_count": 0}
    resolving = evaluate_aquaculture_risk(clean, previous_alert=previous)
    resolved = evaluate_aquaculture_risk(clean, previous_alert=resolving)
    assert resolving["state"] == "RESOLVING"
    assert resolved["state"] == "RESOLVED"
