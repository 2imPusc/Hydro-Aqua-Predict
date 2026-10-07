import pandas as pd

from core.forecast_train import GRANULARITY_CONFIG, build_features


def test_build_features_minute_keeps_native_resolution_and_horizon():
    idx = pd.date_range("2026-07-01 00:00:00", periods=90, freq="min", tz="UTC")
    df = pd.DataFrame({"Temperature": range(90)}, index=idx)

    spec = build_features(
        df=df,
        param="Temperature",
        granularity="minute",
        freq=GRANULARITY_CONFIG["minute"]["freq"],
        lags=GRANULARITY_CONFIG["minute"]["lags"],
        horizon=60,
    )

    assert {"lag_1", "lag_2", "lag_3", "lag_5", "lag_10", "lag_30"} <= set(spec["frame"].columns)
    assert len(spec["future_index"]) == 60
    assert spec["series"].index[1] - spec["series"].index[0] == pd.Timedelta(minutes=1)


def test_build_features_hour_adds_hour_of_day_after_resample():
    idx = pd.date_range("2026-07-01 00:00:00", periods=240, freq="15min", tz="UTC")
    df = pd.DataFrame({"pH": [7.5 + (i % 8) * 0.01 for i in range(240)]}, index=idx)

    spec = build_features(
        df=df,
        param="pH",
        granularity="hour",
        freq=GRANULARITY_CONFIG["hour"]["freq"],
        lags=GRANULARITY_CONFIG["hour"]["lags"],
        horizon=24,
    )

    assert {"lag_1", "lag_2", "lag_24", "hour_of_day"} <= set(spec["frame"].columns)
    assert len(spec["future_index"]) == 24
    assert spec["series"].index[1] - spec["series"].index[0] == pd.Timedelta(hours=1)


def test_build_features_day_adds_calendar_features():
    idx = pd.date_range("2026-06-01", periods=20, freq="D", tz="UTC")
    df = pd.DataFrame({"DO_imputed": [5.0 + (i % 4) * 0.2 for i in range(20)]}, index=idx)

    spec = build_features(
        df=df,
        param="DO",
        granularity="day",
        freq=GRANULARITY_CONFIG["day"]["freq"],
        lags=GRANULARITY_CONFIG["day"]["lags"],
        horizon=7,
    )

    assert {"lag_1", "lag_2", "lag_7", "day_of_week", "month_sin", "month_cos"} <= set(spec["frame"].columns)
    assert len(spec["future_index"]) == 7
    assert spec["series"].index[1] - spec["series"].index[0] == pd.Timedelta(days=1)
