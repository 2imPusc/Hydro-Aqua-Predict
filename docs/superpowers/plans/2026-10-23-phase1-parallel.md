# Phase 1 (parallel) — alert operations in shadow: contracts and tracks

> For agentic workers: this file is the shared contract. Each track owns only the files listed for it. Do not edit files owned by another track; ask the controller.

**Goal:** turn the theory-track hazard results into per-station shadow alerts, with thresholds an admin can edit inside the research-map. No authentication yet (owner decision 2026-10-23: accounts and roles are designed later). `MARINE_ENABLED` and scheduled tasks stay off until the owner enables them.

**Base:** branch `h1-ph-drift-followup` reset to `main` after PR #2 (commit 0001d6e) plus the Wave-0 commit that adds this file.

## Hard rules (all tracks)
- AGENTS.md hard rules. Write-once outputs; never delete or overwrite anything in data/, artifacts/, runtime/, research-map/cache/ — including directories you created (failed run → new stamp).
- **Single API write exception (decisions #20):** the research-map API may write only to `runtime/alert-config/`, and only by creating a new version file (`v<NNNN>-<UTC stamp>.json`, exclusive create). It never overwrites, never deletes, never writes anywhere else.
- Every alert output carries `used_by_alerts: False`, `notification_eligible: False`, `basis: "theory_only_unvalidated"`, plus `config_version`.
- Reanalysis / forecast downloads name their model (`models=`), per decisions #18.
- Worktree agents: first command `git reset --hard <base sha>`. Env for scripts: `HAP_DATA_DIR`, `HAP_ARTIFACTS_DIR`, `HAP_RUNTIME_DIR` pointing to the main checkout. Use your assigned ports and stop every server you start.
- Commits: subject ≤ 72 chars, explicit paths, `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. No push. Do not edit docs/research-log.md, experiments/RESULTS.md, docs/decisions.md (controller only).

## Contracts

### C1. Alert configuration
- Defaults (tracked, never edited at runtime): `config/alert_tiers.default.json` → `paths.ALERT_CONFIG_DEFAULT`.
- Admin versions (runtime, append-only): `paths.ALERT_CONFIG_DIR` = `runtime/alert-config/`. File `v0001-20261023T091500Z.json` with the full config plus `{"config_version": "v0001-…", "parent_version": "...", "changed_at": ISO, "changed_by": "admin-ui" | free text, "reason_vi": "...", "changes": [{"path": "hazards.storm_wind.thresholds.2", "old": 8, "new": 7}]}`.
- Effective config = newest valid version file, else defaults.
- Shape: see the default file. `tiers` 0–4; `hazards.<id>` with `metric`, `unit`, `direction` (`ge`|`le`), `thresholds` {tier: value}, optional `persistence_days`, `actions_vi`, optional `guardrails` {min,max per tier}, `evidence` (repo paths). `scopes.exposure_class.<sheltered|semi|exposed>` and `scopes.station.<id>` hold partial overrides of `hazards` (deep-merged, station > exposure_class > default).
- Validation: thresholds strictly monotonic in the hazard's direction; within guardrails when present; tiers present in `tiers`; unknown keys rejected.
- Python API (`core/alert_config.py`, owner Track A):
  - `load_effective(station_id: str | None = None, exposure_class: str | None = None) -> dict`
  - `validate(config: dict) -> list[str]` (empty = valid)
  - `tier_for(hazard_id: str, value: float, config: dict) -> int`
  - `save_version(config: dict, *, changed_by: str, reason_vi: str) -> str` (returns new config_version; exclusive create)
  - `list_versions() -> list[dict]`, `get_version(v: str) -> dict`

### C2. Hazard shadow ledger
- `paths.HAZARD_SHADOW_DIR` = `runtime/hazard-shadow/`, one JSONL per day `hazard_<YYYYMMDD>.jsonl`, append-only.
- Record:
```json
{"issued_at": "UTC ISO", "station": "NB1", "exposure_class": "exposed", "hazard": "storm_wind",
 "valid_from": "UTC ISO", "valid_to": "UTC ISO", "lead_hours": 24, "value": 8, "unit": "cấp Beaufort",
 "tier": 2, "action_vi": "...", "inputs": {"source": "forecast", "model": "ecmwf_ifs025", "wind_dir_deg": 225},
 "data_status": "fresh|stale|unavailable", "config_version": "default-2026-10-23",
 "used_by_alerts": false, "notification_eligible": false, "basis": "theory_only_unvalidated"}
```
- `hazard` ∈ config hazard ids. Skips are recorded with `"tier": null, "skip_reason": "..."`.

### C3. API (research-map backend; prefix `/api/v1`)
| Endpoint | Owner | Response |
| --- | --- | --- |
| `GET /admin/alert-config` | A | `{status, effective: {...}, config_version, source: "default"|"runtime"}` |
| `GET /admin/alert-config/versions` | A | `{status, versions: [{config_version, changed_at, changed_by, reason_vi, n_changes}]}` |
| `GET /admin/alert-config/versions/{v}` | A | full version |
| `POST /admin/alert-config` | A | body `{config, reason_vi, changed_by?}` → 201 `{config_version}` or 422 `{errors: [...]}` |
| `POST /admin/alert-config/preview` | A | body `{config}` → `{errors, tier_examples: [{hazard, value, tier}]}` (no write) |
| `GET /research/hazards/stations` | G (wave 2; stub now) | `{status, issued_at, config_version, stations: [{id, name, lat, lon, exposure_class, current: [{hazard, tier, value, action_vi}], outlook: [{date, max_tier, hazards: [...]}], data_status}]}` |
| `GET /research/storms/active` | D | `{status, fetched_at, source: "ecmwf_opendata", storms: [{id, name, run_time, members, p_within_500km_120h, p_within_200km_120h, closest_approach_km_median, eta_hours_median, track_median: [[lon, lat, valid_time]]}]}` |

Stub routers exist (Wave 0): `app/admin_config.py` (router `/api/v1/admin`), `app/hazard_api.py` (router `/api/v1/research`, endpoints return `{"status":"unavailable","reason":"not_implemented"}`). Both are already registered in `app/main.py`; tracks fill the bodies and must not touch `main.py`.

### C4. Frontend
- New routes (already registered): `#/alerts` → `views/alerts/AlertsView.tsx` (Wave 2, Track G), `#/settings/alerts` → `views/settings/AlertConfigView.tsx` (Track B). Placeholder components exist.
- API clients: `src/api/admin.ts` (Track B), `src/api/hazards.ts` (Track D adds `getActiveStorms`, Track G adds `getStationHazards`). Types in `src/types/alerts.ts` mirror C1–C3.

## Tracks

| Track | Model | Wave | Owns | Ports |
| --- | --- | --- | --- | --- |
| A admin config backend | sonnet | 1 | `core/alert_config.py`, `tests/test_alert_config.py`, `research-map/backend-fastapi/app/admin_config.py` + tests | backend 8031 |
| B admin config UI | opus | 1 | `frontend/src/views/settings/**`, `src/api/admin.ts`, `src/types/alerts.ts` (shared types: B owns, others request changes) | vite 5191, backend 8032 |
| C hazard shadow runner | sonnet | 1 | `core/hazard_runner.py`, `tests/test_hazard_runner.py`, `experiments/hazard_runner_replay.py` (no edits to `core/shadow_runner.py` in Wave 1; integration in Wave 2) | — |
| D ECMWF Open Data tracks | opus | 1 | `core/storm_tracks.py`, `experiments/ecmwf_opendata.py`, tests, `/research/storms/active` body in `app/hazard_api.py`, `getActiveStorms` in `src/api/hazards.ts` | backend 8033 |
| E map | opus | 1 | `frontend/src/components/map/**`, `views/monitor/**`, `views/zoning/**`, backend `app/aquaculture_artifacts.py` colouring only if needed | vite 5194, backend 8034 |
| F GEBCO 2024 | sonnet | 1 | `research-map/backend-fastapi/app/bathymetry_gebco.py`, `scripts/download_gebco2024_bathymetry.py`, tests, docs/eval note | backend 8035 |
| J disease evidence (web) | sonnet | 1 | `experiments/disease_events.csv` (append rows), `docs/references/disease-sources.md`, `data/references/disease/` | — |
| K TCVN 13997:2024 + cage standards | sonnet | 1 | `docs/references/cage-standards.md`, `experiments/storm_damage_engineering.csv` (append rows), `data/references/standards/` | — |
| L Copernicus Marine (salinity, waves, currents) | sonnet | 1 | `experiments/cmems_sites.py`, tests, `docs/eval/2026-10-24-cmems-sites.md`, `paths.CMEMS_DIR` data | — |
| G per-station alerts view + API | opus | 2 | `views/alerts/**`, `/research/hazards/stations` body, `getStationHazards` | vite 5196, backend 8036 |
| H end-to-end QA | opus | 2 | fixes only via controller | 5197/8037 |
| I enable marine + scheduled tasks | — | 2 | owner approval required | — |

Concurrency cap: 5 agents at once. Order: A, C, D, E, J first; B, F, K, L as slots free; Wave 2 after A, C, D merge.
