import joblib
import numpy as np
import pandas as pd

import core.forecast as forecast_module


class ConstantModel:
    def __init__(self, value):
        self.value = value

    def predict(self, X):
        return np.full((len(X),), self.value, dtype=float)


def test_forecast_returns_timeline_and_warnings(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast_module, "FORECAST_MODEL_DIR", tmp_path)

    prepared_idx = pd.date_range("2026-07-10 00:00:00", periods=120, freq="min", tz="UTC")
    prepared_df = pd.DataFrame(
        {
            "Temperature": np.linspace(29.0, 30.0, 120),
            "pH": np.linspace(7.6, 7.8, 120),
            "NH4": np.linspace(0.1, 0.2, 120),
            "TSS": np.linspace(20.0, 24.0, 120),
            "DO_imputed": np.linspace(5.0, 5.2, 120),
        },
        index=prepared_idx,
    )
    monkeypatch.setattr(forecast_module, "prepare_forecast_frame", lambda df_raw, region: prepared_df)
    monkeypatch.setattr(
        forecast_module,
        "_classify_by_scoring",
        lambda df, available, species: pd.DataFrame(
            [{"suitability_score": 0.82, "suitability_name": "Phu hop"}]
        ),
    )

    station_key = forecast_module.normalize_station_key("06M26042804")
    bundles = {
        "Temperature": {"model": ConstantModel(34.5), "freq": None, "lags": [1, 2, 3, 5, 10, 30]},
        "pH": {"model": ConstantModel(7.9), "freq": None, "lags": [1, 2, 3, 5, 10, 30]},
        "NH4": {"model": ConstantModel(0.15), "freq": None, "lags": [1, 2, 3, 5, 10, 30]},
        "TSS": {"model": ConstantModel(22.0), "freq": None, "lags": [1, 2, 3, 5, 10, 30]},
        "DO": {"model": ConstantModel(3.5), "freq": None, "lags": [1, 2, 3, 5, 10, 30]},
    }
    for param, bundle in bundles.items():
        joblib.dump(bundle, tmp_path / f"{station_key}_minute_{param}.pkl")

    result = forecast_module.forecast(
        df_raw=pd.DataFrame(),
        station_serial="06M26042804",
        granularity="minute",
        current_time_str="2026-07-10T01:59:00",
        species="cobia",
        horizon=5,
    )

    assert result["granularity"] == "minute"
    assert result["horizon"] == 5
    assert len(result["timeline"]) == 5
    assert {"timestamp", "Temperature", "pH", "NH4", "TSS", "DO", "WQI", "label"} <= set(result["timeline"][0].keys())
    assert result["timeline"][0]["WQI"] == 0.82
    assert len(result["early_warnings"]) == 2
