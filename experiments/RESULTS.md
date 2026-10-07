# Experiment results index

Raw outputs live in `artifacts/experiments/` (gitignored, ~307 MB). This index is the tracked record:
one row per run folder, newest last. New scripts must write under `paths.EXPERIMENT_OUTPUT_DIR`
(`core/paths.py`) and add a row here with the key result.

| Last modified | Run | Size | Files | Produced by | Discussed in | Key result |
| --- | --- | ---: | ---: | --- | --- | --- |
| 2026-06-22 | `agg_sensitivity.csv` | 0.0 MB | 1 | — | — | |
| 2026-06-22 | `fig_agg_sensitivity.png` | 0.0 MB | 1 | — | — | |
| 2026-06-26 | `model_comparison.csv` | 0.0 MB | 1 | — | — | |
| 2026-06-27 | `cluster_pca_haiphong.png` | 0.3 MB | 1 | — | — | |
| 2026-06-27 | `cluster_pca_quangninh.png` | 0.8 MB | 1 | — | — | |
| 2026-06-27 | `fig_season_delta.png` | 0.1 MB | 1 | — | — | |
| 2026-06-27 | `optimal_k_haiphong.png` | 0.2 MB | 1 | — | — | |
| 2026-06-27 | `optimal_k_quangninh.png` | 0.2 MB | 1 | — | — | |
| 2026-06-27 | `season_ablation.csv` | 0.0 MB | 1 | — | — | |
| 2026-07-25 | `retrospective-2026-07-25/` | 0.1 MB | 16 | — | [10-imputation-evaluation](../docs/guide/10-imputation-evaluation.md), [12-retrospective-run-log](../docs/guide/12-retrospective-run-log.md), [15-hp-sensor-forecast-backte](../docs/guide/15-hp-sensor-forecast-backtest.md) | |
| 2026-07-26 | `retrospective-2026-07-26/` | 5.6 MB | 2 | — | [15-hp-sensor-forecast-backte](../docs/guide/15-hp-sensor-forecast-backtest.md) | |
| 2026-07-26 | `spatial-applicability-p0-haiphong/` | 0.6 MB | 8 | — | [20-spatial-applicability-p0-](../docs/guide/20-spatial-applicability-p0-run-log.md) | |
| 2026-07-26 | `spatial-applicability-p0-quangninh/` | 33.7 MB | 8 | — | — | |
| 2026-07-26 | `spatial-applicability-p1-haiphong/` | 4.5 MB | 11 | — | — | |
| 2026-08-01 | `external-context-imputation-cmems-v1/` | 0.1 MB | 5 | — | — | |
| 2026-08-01 | `external-context-imputation-v2/` | 0.1 MB | 4 | — | — | |
| 2026-08-01 | `spatial-applicability-hsi-v2/` | 4.6 MB | 18 | `spatial_applicability.py` | — | |
| 2026-09-05 | `retrospective-2026-09-05/` | 13.0 MB | 12 | — | — | |
| 2026-09-26 | `weather-risk-pilot/` | 15.1 MB | 32 | `forecast_sensor_v2.py`, `pilot_p0_inventory.py` | [00-tong-quan-du-an](../docs/guide/00-tong-quan-du-an.md), [24-pilot-weather-risk-agent-](../docs/guide/24-pilot-weather-risk-agent-handoff.md), [25-weather-risk-pilot-remedi](../docs/guide/25-weather-risk-pilot-remediation-handoff.md) | |
| 2026-10-08 | `forecast-v2/` | 243.3 MB | 71 | `weather_snapshot_health.py`, `capture_weather_snapshot.ps1`, `run_weather_snapshot.ps1` | [data-policy](../docs/data-policy.md), [00-tong-quan-du-an](../docs/guide/00-tong-quan-du-an.md), [21-forecast-sensor-v2-experi](../docs/guide/21-forecast-sensor-v2-experiments.md) | |

Older summary tables kept next to the scripts: `experiments/*_results.md`.
