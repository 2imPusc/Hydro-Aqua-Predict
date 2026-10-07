# Weather enrichment for Hai Phong

## Current configuration

Station `06M26042804` uses the nearby reference station NB1 (Cat Ba fish port)
as its weather location. This is deliberately marked `nearby_reference_station`,
not as installation GPS. Weather at an offshore cage can differ from the port;
replace the coordinates with the installation GPS when available.

The local `.env` enables the Open-Meteo adapter. No API key is
required for the non-commercial lab use case. A process-local 60-minute cache
avoids repeated calls when the dashboard refreshes.

## Current role and safety boundary

`core/weather.py` returns hourly air temperature, humidity, precipitation,
cloud cover, surface pressure, and wind. It is attached to the realtime payload
for observation only. It does not currently change imputation, suitability, or
the inferred-DO alert.

The next research step is a time-aware ablation: sensor-only versus
sensor+time versus sensor+weather, using forecast values that would have been
available at each historical prediction timestamp. Only a stable improvement
may promote weather features to a realtime model.

The NB1 retrospective ablation is implemented in
`experiments/nb1_weather_ablation.py`. Unlike the archived shuffled K-fold
experiment, it uses chronological folds. Its old quarterly weather values are
observed aggregates rather than as-issued forecasts, so every result remains
diagnostic (`exploratory_only`) and cannot promote an alert model.

## NB1 temporal retrospective, 2026-07-25

The run was saved locally as
`artifacts/experiments/retrospective-2026-07-25/nb1_weather_temporal_ablation.csv`.
It evaluated 18 NB1-to-target / indicator pairs with 12--19 paired quarters:

| Target | Pairs | Weather improved R2 | Mean R2 change |
| --- | ---: | ---: | ---: |
| DO | 9 | 6 improved, 1 unchanged, 2 worse | +0.186 |
| Salinity | 9 | 9 improved | +0.939 |

This is useful evidence that weather deserves a second experiment, especially
for salinity. It is not evidence for deployment: the test values are historical
weather aggregates, not forecast runs available at the old timestamps, and the
sample is below the 30-pair promotion threshold.

## Hourly weather-lag sensor study, 2026-07-25

`experiments/weather_lag_sensor_ablation.py` retrieved the Open-Meteo weather
history for NB1 and formed only completed-prior-hour features: accumulated rain
and mean wind over 1/3/6/12/24 hours, plus prior-hour air temperature, cloud
cover and pressure. It compared each model with its identical sensor+time
version, at 1/3/6-hour horizons.

| Sensor | Result of adding weather lags | Interpretation |
| --- | --- | --- |
| NH4 | ExtraTrees and XGBoost lower MAE/RMSE at 1/3/6h | Promising delayed association |
| TSS | ExtraTrees improves at 3/6h, but not 1h | Possible delayed response; not stable |
| Temperature | Worse for all tested models/horizons | Keep sensor+time only |
| pH | Worse for all tested models/horizons | Keep sensor/persistence only |

The exact results are saved locally as
`artifacts/experiments/retrospective-2026-07-25/hp_weather_lag_sensor_ablation.csv`.
This remains a relationship study over roughly three weeks of weather and
uses observed past weather, not the forecast issued at each historical origin.
It may guide feature selection, but cannot promote a realtime weather model or
an alert rule yet.

## Per-station coordinates

The station registry is the default source. To override it without editing the
registry, add both values to `.env`:

```env
WEATHER_06M26042804_LATITUDE=<installation latitude>
WEATHER_06M26042804_LONGITUDE=<installation longitude>
```

When both are present, the payload labels the coordinate source as
`environment_override` and accuracy as `installation_gps`.
