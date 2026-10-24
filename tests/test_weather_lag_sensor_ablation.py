import numpy as np
import pandas as pd

from experiments.weather_lag_sensor_ablation import (
    LAG_BINS,
    MAX_LAG,
    _ShiftedRain,
    find_rain_events,
    rain_lag_bins,
    rain_on_sensor_grid,
    weather_lag_features,
)


def test_rain_restamped_to_hour_start():
    index = pd.date_range("2026-06-01 01:00", periods=3, freq="h", tz="UTC")
    rain = rain_on_sensor_grid(pd.Series([1.0, 2.0, 3.0], index=index))
    assert rain.index[0] == pd.Timestamp("2026-06-01 00:00", tz="UTC") and rain.iloc[0] == 1.0


def test_rain_lag_bins_match_cumsum_shifter():
    index = pd.date_range("2026-06-01", periods=400, freq="h", tz="UTC")
    rain = pd.Series(np.random.default_rng(0).gamma(0.3, 2.0, len(index)), index=index)
    rows = index[MAX_LAG + 10: 380]
    bins = rain_lag_bins(rain, rows)
    assert bins.loc[rows[0], "rain_l00_02"] == rain.loc[rows[0] - pd.Timedelta(hours=2): rows[0]].sum()
    shifter = _ShiftedRain(rain, rows)
    assert np.allclose(shifter.bins(0), bins.to_numpy())
    assert shifter.bins(5).shape == (len(rows), len(LAG_BINS))
    assert np.allclose(shifter.lags(0)[:, 3], rain.shift(3).reindex(rows).to_numpy())


def test_rain_events_declustered_and_clean_flag():
    index = pd.date_range("2026-06-01", periods=300, freq="h", tz="UTC")
    rain = pd.Series(0.0, index=index)
    rain.iloc[10:13] = 5.0   # event 1 (15 mm / 3 h), dry afterwards -> clean
    rain.iloc[100:102] = 6.0  # event 2 ...
    rain.iloc[130:132] = 6.0  # ... rain again 30 h later: merged (< 72 h) and makes event 2 not clean
    events = find_rain_events(rain)
    assert len(events) == 2
    assert bool(events.iloc[0]["clean"]) and not bool(events.iloc[1]["clean"])


def test_weather_lags_exclude_current_hour():
    index = pd.date_range("2026-06-01", periods=30, freq="h", tz="UTC")
    weather = pd.DataFrame({"precipitation": range(30), "wind_speed_10m": range(30), "temperature_2m": range(30), "cloud_cover": range(30), "surface_pressure": range(1000, 1030)}, index=index)
    features = weather_lag_features(weather)
    assert features.loc[index[2], "rain_sum_1h"] == 1
    assert features.loc[index[4], "rain_sum_3h"] == 1 + 2 + 3
