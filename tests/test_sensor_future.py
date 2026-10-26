import joblib
import numpy as np
import pandas as pd
import pytest

from core import forecast_evaluation, sensor_future
from core.sensor_future_long import b4_feature_names

FEATURES = b4_feature_names("Temperature")
REAL_VERSION = "hp-temperature-ridge-b4-15m-v2"


class ConstantModel:
    def __init__(self, value):
        self.value = value

    def predict(self, frame):
        assert list(frame.columns) == FEATURES
        return np.full(len(frame), self.value)


class LastLagModel:
    """Linear-like stand-in: returns the 1-minute lag plus an offset."""

    def __init__(self, offset=0.0):
        self.offset = offset

    def predict(self, frame):
        return frame["Temperature_lag_1m"].to_numpy() + self.offset


def _guard_bundle(model, lo=24.0, hi=34.0):
    return {"model": model, "features": FEATURES, "model_version": "test-ridge-v2", "training_range": [lo, hi],
            "range_margin": 1.5, "max_abs_change": 1.5,
            "guard_features": [name for name in FEATURES if name.startswith(("Temperature_lag_", "roll_mean_", "roll_median_", "roll_min_", "roll_max_"))]}


def _raw(temperature, minutes=90, tss=2.8, start="2026-10-20T00:00:00Z"):
    time = pd.date_range(start, periods=minutes, freq="1min", tz="UTC")
    values = temperature(np.arange(minutes)) if callable(temperature) else np.full(minutes, float(temperature))
    return pd.DataFrame({"fetchedAt": time, "Temperature": values, "pH": 7.8, "NH4": .2, "TSS": tss})


@pytest.fixture
def stub_context(monkeypatch):
    monkeypatch.setattr(sensor_future, "predict_haiphong_contextual", lambda measured, observed_at: {"status": "ready", "predictions": {"DO": {"status": "accepted", "value": 5.1}}})


@pytest.fixture
def fake_bundle(tmp_path, monkeypatch, stub_context):
    def install(bundle):
        monkeypatch.setattr(sensor_future, "MODEL_DIR", tmp_path)
        sensor_future._BUNDLE_CACHE.clear()
        joblib.dump(bundle, sensor_future.temperature_bundle_path())
    yield install
    sensor_future._BUNDLE_CACHE.clear()


def test_output_contract_is_shadow_with_model_version(fake_bundle):
    fake_bundle(_guard_bundle(ConstantModel(29.0)))
    result = sensor_future.forecast_sensor_first(_raw(lambda m: 28.6 + m * 0.001), "06M26042804")
    assert result["status"] == "ready" and result["mode"] == "shadow"
    assert result["used_by_alerts"] is False and result["used_by_suitability"] is False
    assert result["model_version"] == "test-ridge-v2"
    assert result["model_versions"] == {"Temperature": "test-ridge-v2", "pH": "persistence", "NH4": "persistence", "TSS": "persistence"}
    assert result["evaluated_horizons_minutes"] == [15]
    assert result["base_timestamp"] == "2026-10-20T01:29:00+00:00"
    timeline = result["timeline"]
    assert [p["horizon_minutes"] for p in timeline] == list(range(1, 16))
    last, first = timeline[-1], timeline[0]
    assert last["sensors"]["Temperature"] == 29.0
    assert last["evaluatable"] is True and last["interpolation_method"] is None
    assert first["evaluatable"] is False and first["interpolation_method"] == "linear_between_now_and_15m_model"
    assert last["sensor_sources"] == {"Temperature": "ridge_b4", "pH": "persistence", "NH4": "persistence", "TSS": "persistence"}
    assert first["sensor_sources"]["Temperature"] == "interpolated_to_15m_ridge_b4"
    assert first["sensor_sources"]["TSS"] == "interpolated_to_15m_persistence"
    assert last["model_version"] == "test-ridge-v2"
    assert {"NH3", "TAN", "pH", "NH4", "TSS"} <= set(last["sensors"])
    assert last["sensors"]["TAN"] > last["sensors"]["NH3"]  # un-ionised is a fraction of TAN
    assert last["inferred"] == {"DO": 5.1} and last["inference_diagnostics"]["DO"]["status"] == "accepted"


def test_tss_is_persistence_with_reason(fake_bundle):
    fake_bundle(_guard_bundle(ConstantModel(29.0)))
    raw = _raw(29.0, tss=2.8)
    raw.loc[raw.index[-1], "TSS"] = 3.1
    result = sensor_future.forecast_sensor_first(raw, "06M26042804")
    assert all(p["sensors"]["TSS"] == pytest.approx(3.1) for p in result["timeline"])
    assert result["timeline"][-1]["sensor_sources"]["TSS"] == "persistence"
    assert result["sensor_source_reasons"]["TSS"] == "offline_15m_tss_models_fail_gate_rl54"


def test_out_of_range_input_falls_back_to_persistence(fake_bundle):
    fake_bundle(_guard_bundle(LastLagModel(), lo=24.0, hi=34.0))
    result = sensor_future.forecast_sensor_first(_raw(18.0), "06M26042804")  # below 24 - 1.5
    last = result["timeline"][-1]
    assert last["sensors"]["Temperature"] == 18.0
    assert last["sensor_sources"]["Temperature"] == "persistence_out_of_range"
    assert result["model_versions"]["Temperature"] == "persistence"
    assert result["temperature_guard"]["reason"] == "input_outside_training_range"


def test_out_of_range_prediction_falls_back_to_persistence(fake_bundle):
    fake_bundle(_guard_bundle(ConstantModel(37.0), lo=24.0, hi=34.0))
    result = sensor_future.forecast_sensor_first(_raw(33.8), "06M26042804")
    assert result["timeline"][-1]["sensors"]["Temperature"] == 33.8
    assert result["timeline"][-1]["sensor_sources"]["Temperature"] == "persistence_out_of_range"
    assert result["temperature_guard"]["model_value"] == 37.0


def test_implausible_change_falls_back_to_persistence(fake_bundle):
    fake_bundle(_guard_bundle(LastLagModel(offset=2.0)))
    result = sensor_future.forecast_sensor_first(_raw(28.0), "06M26042804")
    assert result["timeline"][-1]["sensors"]["Temperature"] == 28.0
    assert result["timeline"][-1]["sensor_sources"]["Temperature"] == "persistence_implausible_change"


def test_short_history_falls_back_to_persistence(fake_bundle):
    fake_bundle(_guard_bundle(ConstantModel(29.0)))
    result = sensor_future.forecast_sensor_first(_raw(28.0, minutes=20), "06M26042804")  # no 30/60 min lags
    assert result["status"] == "ready"
    assert result["timeline"][-1]["sensors"]["Temperature"] == 28.0
    assert result["timeline"][-1]["sensor_sources"]["Temperature"] == "persistence_insufficient_history"


def test_guard_rules_directly():
    bundle = _guard_bundle(None, lo=24.0, hi=34.0)
    features = {name: 28.0 for name in bundle["guard_features"]}
    assert sensor_future.guard_temperature(bundle, features, 28.0, 28.4)["source"] == "ridge_b4"
    assert sensor_future.guard_temperature(bundle, features, 28.0, 29.6)["source"] == "persistence_implausible_change"
    assert sensor_future.guard_temperature(bundle, features, 28.0, float("nan"))["source"] == "persistence_invalid_output"
    assert sensor_future.guard_temperature(bundle, {**features, "Temperature_lag_60m": 40.0}, 28.0, 28.1)["inputs_outside"] == ["Temperature_lag_60m"]
    # margin is inclusive: 24 - 1.5 = 22.5 is still accepted
    edge = {name: 22.5 for name in bundle["guard_features"]}
    assert sensor_future.guard_temperature(bundle, edge, 22.5, 22.6)["source"] == "ridge_b4"


def test_missing_bundle_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(sensor_future, "MODEL_DIR", tmp_path)
    sensor_future._BUNDLE_CACHE.clear()
    assert sensor_future.forecast_sensor_first(_raw(28.0), "06M26042804") == {"status": "unavailable", "reason": "temperature_bundle_missing", "timeline": []}


def test_other_stations_not_applicable():
    assert sensor_future.forecast_sensor_first(_raw(28.0), "06M26042801")["status"] == "not_applicable"


# --- committed runtime bundle -----------------------------------------------

def test_committed_bundle_is_guarded_ridge_b4():
    sensor_future._BUNDLE_CACHE.clear()
    bundle = sensor_future.load_temperature_bundle()
    assert bundle["model_version"] == REAL_VERSION
    assert bundle["features"] == FEATURES
    assert bundle["feature_set"] == "B4_quality" and bundle["horizon_minutes"] == 15
    assert bundle["range_margin"] == 1.5 and bundle["max_abs_change"] == 1.5
    lo, hi = bundle["training_range"]
    assert lo < 24 < 31 < hi
    assert set(bundle["guard_features"]) >= {f"Temperature_lag_{m}m" for m in (1, 3, 5, 10, 15, 30, 60)}
    # old XGBoost pickles stay in git but are no longer the runtime bundle
    assert sensor_future._temperature_bundle_path(15).exists() and sensor_future._tss_bundle_path(15).exists()
    assert "xgboost" not in sensor_future.TEMPERATURE_BUNDLE_FILE


@pytest.mark.parametrize("level", [24.0, 25.0, 26.0])
def test_committed_bundle_extrapolates_cool_water(stub_context, level):
    """The old XGBoost never went below 29.15 °C; the ridge must follow 24-26 °C water."""
    sensor_future._BUNDLE_CACHE.clear()
    raw = _raw(lambda m: level + 0.2 * np.sin(m / 40), minutes=120)
    result = sensor_future.forecast_sensor_first(raw, "06M26042804")
    last = result["timeline"][-1]
    current = float(raw["Temperature"].iloc[-1])
    assert last["sensor_sources"]["Temperature"] == "ridge_b4"
    assert abs(last["sensors"]["Temperature"] - current) < 0.5
    assert last["sensors"]["Temperature"] < 27.0
    assert result["model_version"] == REAL_VERSION


def test_ledger_records_model_version(fake_bundle, tmp_path, monkeypatch):
    fake_bundle(_guard_bundle(ConstantModel(29.0)))
    store = tmp_path / "ledger"
    monkeypatch.setattr(forecast_evaluation, "FORECAST_LOG", store / "forecasts.jsonl")
    monkeypatch.setattr(forecast_evaluation, "OUTCOME_LOG", store / "outcomes.jsonl")
    raw = _raw(28.8)
    future = sensor_future.forecast_sensor_first(raw, "06M26042804")
    assert forecast_evaluation.record_sensor_future("06M26042804", future) == 1  # only the 15-min endpoint
    record = forecast_evaluation._read_jsonl(forecast_evaluation.FORECAST_LOG)[0]
    assert record["model_version"] == "test-ridge-v2"
    assert record["sensor_sources"]["Temperature"] == "ridge_b4"
    assert record["sensor_source_reasons"]["TSS"] == "offline_15m_tss_models_fail_gate_rl54"
    later = pd.concat([raw, _raw(28.9, minutes=20, start="2026-10-20T01:30:00Z")], ignore_index=True)
    assert forecast_evaluation.resolve_sensor_outcomes(later) == 1
    outcome = forecast_evaluation._read_jsonl(forecast_evaluation.OUTCOME_LOG)[0]
    assert outcome["model_version"] == "test-ridge-v2"
    metrics = forecast_evaluation.sensor_metrics()
    assert {"param": "Temperature", "model": "ridge_b4"}.items() <= next(m for m in metrics if m["param"] == "Temperature").items()
