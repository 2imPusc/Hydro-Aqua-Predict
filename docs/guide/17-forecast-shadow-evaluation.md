# Forecast shadow evaluation

`core/forecast_evaluation.py` maintains an append-only ledger for the
Hai Phong sensor-first forecast. It is deliberately separate from alerts.

## Issuance

Every ready 15/30/60-minute `sensor_future` point is written once to
`runtime/forecast-shadow/forecasts.jsonl`. A record contains the
issue time, valid time, direct-sensor forecast, model source/version context,
shadow inferred values, and the Open-Meteo forecast payload available at issue
time. Duplicate issue/valid pairs are ignored.

## Resolution

When a later raw sensor snapshot is available within +/-4 minutes of a forecast
valid time, an immutable outcome is appended to `outcomes.jsonl`. Only directly
measured Temperature, pH, NH4 and TSS are scored. Inferred DO and salinity are
recorded for provenance but are not scored without independent observations.

The pipeline returns `forecast_evaluation.metrics` grouped by parameter,
horizon and model, with MAE, RMSE and bias. The dashboard displays the current
Temperature summary when resolved outcomes exist.

## One-minute collection runner

Use the lightweight runner for continuous collection, separately from Streamlit
and the legacy forecast pipeline:

```powershell
python core/shadow_runner.py --station 06M26042804 --interval-seconds 60
```

The default 60-second interval matches the MongoDB sensor cadence. It fetches
raw sensor observations, publishes only a new 15/30/60-minute forecast when
the 3-minute aggregate advances, resolves due outcomes, and never sends an
alert. For a single health check, add `--once`.

The runner now prefers GreenLab API latest snapshots and appends each unseen
raw snapshot to `data/greenlab/exports/live-cache/` by station/day. This local
cache is combined with the API historical exports to provide forecast history.
Fallback order is API -> MongoDB -> stale API cache -> CSV demo; stale cache
and CSV demo return `stale_fallback_data` and do not issue ledger records.

If MongoDB cannot be read and `fetch_raw` falls back to the historical local
CSV, the runner returns `stale_fallback_data` and writes neither forecasts nor
outcomes. This prevents historical readings being mislabelled as live evidence.

To register the runner at Windows logon and start it immediately:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_shadow_runner_task.ps1 -Start
```

It runs only while the configured user is logged in and can be removed with
`scripts/remove_shadow_runner_task.ps1`. The Streamlit **Forecast Shadow** tab
reads the append-only ledger and shows issued records, resolved outcomes and
per-horizon sensor metrics. Registering a task may require Windows Task
Scheduler permission; if it is unavailable, start the runner as a hidden
background process for the current session instead.

## Weather boundary

Weather is stored as issued provenance for future research. It is not currently
an input to the promoted sensor forecast. This distinction permits a later
as-issued weather backtest without replacing historical forecasts with observed
future weather.

## Initial live-data audit, 2026-07-25

The MongoDB fetch contained 63,681 unique one-minute observations from
2026-05-29 through 2026-07-25. This is sufficient density for offline direct
sensor training/backtesting. It is not continuous: 1,675 gaps exceeded five
minutes, including several gaps longer than one hour.

The live shadow ledger currently has 11 issued points for each horizon, but
only 6 resolved 15-minute outcomes and 4 each at 30 and 60 minutes. These
counts are useful only as a smoke test of matching and metrics, not as model
evidence. Do not revise model selection until at least 100 resolved outcomes
per horizon have accumulated across at least seven days with gap/OOD rates
reported separately.
