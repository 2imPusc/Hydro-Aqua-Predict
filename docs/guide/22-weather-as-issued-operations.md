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

## Second capture source: research-map worker (H2.1)

The scheduled task misses every hour in which it fails or the laptop sleeps
through its trigger. The research-map worker (`app/weather_capture.py`) checks
every minute and, once per UTC hour, makes one single-point Open-Meteo request
for NB1 with the same variables, 3 forecast days and provider timezone. It
appends to its own file
`artifacts/experiments/forecast-v2/worker-capture/weather-snapshots-worker.jsonl`
(append-only; Docker mounts only that directory writable). Records are
field-for-field the task's format plus `capture_source: research_map_worker`;
new task records carry `capture_source: hap_weather_snapshot_task`. Disable with
`WEATHER_CAPTURE_ENABLED=false`. Both sources run on the same machine, so a
sleeping laptop still stops both; the worker only closes gaps from task
failures and catches up within a minute after a wake-up.

The two files are unioned per station x issue hour: an hour the task captured
keeps only the task issue, the worker fills hours the task missed
(`core.b5_coverage.dedupe_issues`, `read_snapshot_union`).

Weekly coverage report (per source and combined 7-day / since-start coverage,
causal B5 origins against the newest `sensor-history-*` export, eligible days,
projected H2.2 date; writes a new `artifacts/experiments/b5-coverage-<stamp>/`):

```powershell
python experiments/forecast_snapshot_coverage.py --station 06M26042804 --weekly
```

A day is eligible when at least 90 % of a normal day's origins (Temperature,
60 min) have a causal `captured_live` snapshot; H2.2 needs a 63-day window
with at least 57 eligible days. The same numbers are served at
`/api/v1/research/weather/b5-coverage` and shown on the H2 weather page.

When coverage exists, run a B5 candidate explicitly, rather than adding it to
all ablations implicitly (add `--extra-snapshots <worker file>` to use both
sources):

```powershell
python experiments/forecast_sensor_v2.py <telemetry.csv> `
  --station 06M26042804 `
  --snapshots artifacts/experiments/forecast-v2/weather-snapshots.jsonl `
  --feature-set B5_external_as_issued --model ridge `
  --output artifacts/experiments/forecast-v2/run-b5
```
