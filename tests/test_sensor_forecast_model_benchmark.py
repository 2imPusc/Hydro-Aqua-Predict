import numpy as np
import pandas as pd

from experiments.sensor_forecast_model_benchmark import selection_summary, supervised_frame


def test_supervised_frame_uses_future_calendar_time_without_leakage():
    index = pd.date_range("2026-07-01", periods=40, freq="3min", tz="UTC")
    frame, features = supervised_frame(pd.Series(np.arange(40), index=index), steps=5, include_time=True)
    assert {"lag_1", "hour_sin", "hour_cos", "dow_sin", "dow_cos"} <= set(features)
    assert frame.iloc[0]["target"] == 15


def test_selection_requires_both_metrics_at_all_horizons():
    rows = []
    for horizon in (15, 30, 60):
        rows += [
            {"param": "Temperature", "horizon_minutes": horizon, "model": "persistence", "feature_set": "lags", "mae": 2., "rmse": 3.},
            {"param": "Temperature", "horizon_minutes": horizon, "model": "xgboost", "feature_set": "lags_plus_time", "mae": 1., "rmse": 2.},
        ]
    result = selection_summary(pd.DataFrame(rows))
    assert result.iloc[0]["verdict"] == "candidate"
