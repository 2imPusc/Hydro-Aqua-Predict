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
| 2026-07-25 | `retrospective-2026-07-25/` | 0.1 MB | 16 | — | [10-imputation-evaluation](../docs/guide/10-imputation-evaluation.md), [12-retrospective-run-log](../docs/guide/12-retrospective-run-log.md), [15-hp-sensor-forecast-backte](../docs/guide/15-hp-sensor-forecast-backtest.md) | HP DO and Salinity contextual retrospective (ExtraTrees), QN DO median; sensor forecast: Temperature XGBoost+time beats persistence, pH/NH4 persistence (see 12, 15) |
| 2026-07-26 | `retrospective-2026-07-26/` | 5.6 MB | 2 | — | [15-hp-sensor-forecast-backte](../docs/guide/15-hp-sensor-forecast-backtest.md) | Temperature MAE XGBoost+time vs persistence 0.150/0.158/0.181 vs 0.182/0.189/0.207 at 15/30/60 min; pH and NH4 persistence wins (15) |
| 2026-07-26 | `spatial-applicability-p0-haiphong/` | 0.6 MB | 8 | — | [20-spatial-applicability-p0-](../docs/guide/20-spatial-applicability-p0-run-log.md) | anchor-copy baseline, 216 records, 14 stations; no tier promoted to map or pipeline, research shadow only (20) |
| 2026-07-26 | `spatial-applicability-p0-quangninh/` | 33.7 MB | 8 | — | — | — |
| 2026-07-26 | `spatial-applicability-p1-haiphong/` | 4.5 MB | 11 | — | — | — |
| 2026-08-01 | `external-context-imputation-cmems-v1/` | 0.1 MB | 5 | — | — | — |
| 2026-08-01 | `external-context-imputation-v2/` | 0.1 MB | 4 | — | — | — |
| 2026-08-01 | `spatial-applicability-hsi-v2/` | 4.6 MB | 18 | `spatial_applicability.py` | — | — |
| 2026-09-05 | `retrospective-2026-09-05/` | 13.0 MB | 12 | — | — | — |
| 2026-09-26 | `weather-risk-pilot/` | 15.1 MB | 32 | `forecast_sensor_v2.py`, `pilot_p0_inventory.py` | [00-tong-quan-du-an](../docs/guide/00-tong-quan-du-an.md), [24-pilot-weather-risk-agent-](../docs/guide/24-pilot-weather-risk-agent-handoff.md), [25-weather-risk-pilot-remedi](../docs/guide/25-weather-risk-pilot-remediation-handoff.md) | round 3: B5 pipeline runs on fixture only; 0 causal sensor-weather origins on real data, so B5 is insufficient_evidence (see 26) |
| 2026-10-08 | `forecast-v2/` | 243.3 MB | 71 | `weather_snapshot_health.py`, `capture_weather_snapshot.ps1`, `run_weather_snapshot.ps1` | [data-policy](../docs/data-policy.md), [00-tong-quan-du-an](../docs/guide/00-tong-quan-du-an.md), [21-forecast-sensor-v2-experi](../docs/guide/21-forecast-sensor-v2-experiments.md) | benchmark v2 (Ridge + lags + calendar, 14-day lockbox): Temperature MAE -20.0% / -18.6% / -17.4% vs persistence at 15/30/60 min; predates timestamp fix, rerun to confirm (00, 21) |
| 2026-10-15 | `sensor-coverage-20261015/` | 0.0 MB (8 KB) | 1 | `scripts/sensor_coverage.py` | [phase0 plan](../docs/superpowers/plans/2026-10-15-phase0-data-foundation.md) | Gate: 90 % of 1,440 local minutes/day. Artifact (written before the July refetch and the zero-flatline QC fix): 122/139 days pass, COD VALID 47 / INVALID 92. Current re-run: 123/139 days pass, 2026-05-29 to 2026-10-14, COD VALID 13 / INVALID 126. 16 days below gate, all persisting after refetch (provider/sensor-side gaps): 07-02, 07-22...27, 08-02...04, 08-12, 09-07...10, 09-13 (worst 08-03 at 0.102) |
| 2026-10-15 | `sensor-history-20261014/` | 14 MB | 2 | `scripts/export_sensor_history.py` | same | 191,167 rows, 2026-05-29 00:00 to 2026-10-14 23:58 local, sha256 eb84b513e5a1; forecast_sensor_v2 --fast smoke run (Temperature 60 min) OK |
| 2026-10-16 | `forecast-h1.1-20261016-{Temperature,TSS,pH,NH4}/` | 0.5 MB | 12 | `forecast_sensor_v2.py --fast` | [master plan](../docs/superpowers/plans/2026-10-15-master-execution-plan.md) | H1.1 on tz-corrected history (sensor-history-20261014). Ridge passes gate (5-fold + lockbox CI) for **Temperature** (−15…17 % MAE vs persistence, 15/30/60 min) and **pH** (−10…16 % rolling, −4…6 % lockbox). NH4 not robust (lockbox gain, rolling loss) → keep persistence. TSS: all models worse than persistence → keep persistence. Tree models (fast preset) never pass. First attempt with `--write-predictions` ran out of RAM (16 GB). |
| 2026-10-16 | `forecast-h1.2-20261016-{Temperature,pH,NH4,TSS}/`, `…-addon-dm/` | ~60 MB | 25 | `forecast_sensor_v2.py --fast`, `forecast_dm_test.py --kernel rectangular` | [research-log RL-08](../docs/research-log.md) | Horizons 15 min–12 h. Temperature passes gate at all horizons (B4 +13…37 %, B5 +13…46 % vs persistence); weather (reconstructed_run) adds +8–14 % over B4 at 3–12 h (DM p<0.001). pH passes ≤60 min, 3 h with tide only; tide adds +5–7 % at 6–12 h. NH4, TSS: no model passes. Preliminary: reconstructed forecasts, one station, 14-day lockbox. |
| 2026-10-16 | `forecast-h1.3-conformal-20261016-v3/` | <1 MB | 3 | `forecast_conformal.py` | [RL-09](../docs/research-log.md) | Temperature ridge static PI80 0.54–0.76 (passes 15 min only, Oct regime shift); ACI-scaled 0.75–0.80 passes 15/18; pH static_night 13/18; fixed-γ ACI degenerate ≥60 min. Runs `-20261016`, `-v2` superseded. |
| 2026-10-16 | `nerrs-h4-pilot-20261016/` | ~0.6 MB | 9 | `nerrs_reliability.py` | [RL-12](../docs/research-log.md) | NERRS Jobos 4 stations 1–5 km: raw transfer fails all gates; habitat > distance; calibrated pH±0.2 passes 80 % in 5/12 pairs; heavy rain lowers calibrated reliability (−0.11). |
| 2026-10-16 | `suitability-h3-2024-draft/` | 0.1 MB | 4 | `suitability_map.py` | same | Ghaderi (2026) cobia criteria on 154 HP+QN sea points (2024 layers). 22 OSM-mapped marine farms sit at the 24th percentile under expert weights (52nd unweighted SUM): farm cells lie 0–0.8 km from shore (Ghaderi DfS needs 2–10 km) and score high on shelter (SWH, WS) and port access → offshore criteria do not match VN nearshore bay cages; local recalibration needed. Caveats: ETOPO1 depth (1.8 km) reads 0–1 m at farm cells (too coarse nearshore; 100 m SDB covers only 0.3 % of cells); 22 farms map to ~5 grid cells; DfPA uses PA centroids. Draft, exploratory. |

Runs dated before 2026-10-15 that read GreenLab export files used timestamps shifted by +7 h (decisions #12); rerun before reuse.

Older summary tables kept next to the scripts: `experiments/*_results.md`.
