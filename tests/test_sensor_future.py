import joblib
import numpy as np
import pandas as pd

from core import sensor_future


class ConstantModel:
    def predict(self, frame):
        return np.full(len(frame), 29.5)


class TssModel:
    def predict(self, frame):
        return np.full(len(frame), 13.25)


def test_sensor_first_forecast_is_shadow_and_uses_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr(sensor_future, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(sensor_future, "predict_haiphong_contextual", lambda measured, observed_at: {"status": "ready", "predictions": {"DO": {"status": "accepted", "value": 5.1}}})
    for horizon in sensor_future.HORIZONS:
        joblib.dump({"model": ConstantModel(), "features": [f"lag_{lag}" for lag in sensor_future.LAGS] + ["hour_sin", "hour_cos", "dow_sin", "dow_cos"]}, sensor_future._temperature_bundle_path(horizon))
    time = pd.date_range("2026-06-01", periods=20, freq="3min", tz="UTC")
    raw = pd.DataFrame({"fetchedAt": time, "Temperature": np.linspace(28, 29, 20), "pH": 7.8, "NH4": .2, "TSS": 12})
    result = sensor_future.forecast_sensor_first(raw, "06M26042804")
    assert result["status"] == "ready"
    assert result["used_by_alerts"] is False
    assert len(result["timeline"]) == 15
    assert result["timeline"][0]["horizon_minutes"] == 1
    assert result["timeline"][-1]["sensors"]["Temperature"] == 29.5
    assert result["timeline"][0]["evaluatable"] is False
    assert result["timeline"][-1]["evaluatable"] is True
    assert result["timeline"][0]["sensor_sources"]["NH4"] == "persistence"
    assert result["timeline"][0]["inference_diagnostics"]["DO"]["status"] == "accepted"


def test_sensor_first_uses_native_tss_bundle_when_available(tmp_path, monkeypatch):
    monkeypatch.setattr(sensor_future, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(sensor_future, "predict_haiphong_contextual", lambda measured, observed_at: {"status": "unavailable", "predictions": {}})
    for horizon in sensor_future.HORIZONS:
        joblib.dump({"model": ConstantModel(), "features": [f"lag_{lag}" for lag in sensor_future.LAGS] + ["hour_sin", "hour_cos", "dow_sin", "dow_cos"]}, sensor_future._temperature_bundle_path(horizon))
        joblib.dump({"model": TssModel(), "features": [f"lag_{lag}" for lag in sensor_future.LAGS]}, sensor_future._tss_bundle_path(horizon))
    # Temperature is intentionally 3-minute median-resampled; retain enough
    # native readings for both it and the TSS native-cadence model.
    time = pd.date_range("2026-06-01", periods=40, freq="1min", tz="UTC")
    raw = pd.DataFrame({"fetchedAt": time, "Temperature": np.linspace(28, 29, 40), "pH": 7.8, "NH4": .2, "TSS": 12})
    result = sensor_future.forecast_sensor_first(raw, "06M26042804")
    assert result["timeline"][-1]["sensors"]["TSS"] == 13.25
    assert result["timeline"][-1]["sensor_sources"]["TSS"] == "xgboost_lags"
