# B5 weather as-issued operation

This is a research-only collection path for the sensor-forecast v2 experiment.
It does not modify the runtime cache, model bundle, alert policy, or dashboard.

Run the following script once per hour, for example with Windows Task
Scheduler:

```powershell
powershell -ExecutionPolicy Bypass -File experiments/capture_weather_snapshot.ps1
```

For this repository, install the local user Scheduled Task instead of creating
it manually. The task only appends research snapshots; it never changes the
runtime prediction, classification, or alert policy:

```powershell
powershell -ExecutionPolicy Bypass -File experiments/install_weather_snapshot_task.ps1
Get-ScheduledTask -TaskName DATN-WeatherSnapshot-06M26042804
```

It starts about two minutes after installation and then runs every 60 minutes.
Collector output is retained in
`artifacts/experiments/forecast-v2/weather-snapshot-collector.log`.
To remove the task deliberately:

```powershell
powershell -ExecutionPolicy Bypass -File experiments/install_weather_snapshot_task.ps1 -Remove
```

It appends immutable Open-Meteo records to
`artifacts/experiments/forecast-v2/weather-snapshots.jsonl`. A record
contains UTC issue and valid times, provider timezone, location, model/product,
complete-payload SHA-256 hash, and normalized hourly weather fields.

The initial snapshot was captured on 2026-08-01. It cannot recreate forecasts
for the historical lockbox already evaluated. Preserve continuous captures
before scoring B5 on a new period. With a 14-day initial training warm-up,
five 7-day rolling folds, and a 14-day lockbox, approximately 63 days of
continuous snapshot coverage is required for a full evaluation. Historical
weather, CHIRPS, and ocean reanalysis remain retrospective/exploratory inputs,
not B5 evidence.

When coverage exists, run a B5 candidate explicitly, rather than adding it to
all ablations implicitly:

```powershell
python experiments/forecast_sensor_v2.py <telemetry.csv> `
  --station 06M26042804 `
  --snapshots artifacts/experiments/forecast-v2/weather-snapshots.jsonl `
  --feature-set B5_external_as_issued --model ridge `
  --output artifacts/experiments/forecast-v2/run-b5
```
