import pandas as pd

from core.sensor_health import assess_sensor_health


def _frame(values, freq="3min"):
    return pd.DataFrame({"fetchedAt": pd.date_range("2026-07-01", periods=len(values), freq=freq, tz="UTC"), "TSS": values})


def test_flatline_is_suspect():
    health = assess_sensor_health(_frame([10.0] * 10))
    assert health["metrics"]["TSS"]["status"] == "suspect"
    assert "flatline" in health["metrics"]["TSS"]["flags"]


def test_gap_is_degraded():
    health = assess_sensor_health(_frame([10.0, 11.0], freq="10min"))
    assert health["data_gap"] is True
    assert health["overall_status"] == "degraded"
