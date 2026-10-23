import pandas as pd

from experiments.weather_lag_sensor_ablation import weather_lag_features


def test_weather_lags_exclude_current_hour():
    index = pd.date_range("2026-06-01", periods=30, freq="h", tz="UTC")
    weather = pd.DataFrame({"precipitation": range(30), "wind_speed_10m": range(30), "temperature_2m": range(30), "cloud_cover": range(30), "surface_pressure": range(1000, 1030)}, index=index)
    features = weather_lag_features(weather)
    assert features.loc[index[2], "rain_sum_1h"] == 1
    assert features.loc[index[4], "rain_sum_3h"] == 1 + 2 + 3
