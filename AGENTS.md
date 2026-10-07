# AGENTS.md — Hydro-Aqua-Predict

Canonical instructions for AI coding agents (Claude Code, Codex, Cursor…) and humans.
`CLAUDE.md` only imports this file. Keep it current when layout, commands or rules change.

## What this project is

Near-real-time water-quality monitoring, forecasting and risk advisory for coastal cage
aquaculture (cobia/oyster) in northern Vietnam. GreenLab IoT sensors (COD, NH4, pH,
Temperature, TSS; ~1–3 min cadence) are QC'd, NH4 is converted to NH3, missing
parameters are imputed from historical provincial monitoring data, sites are scored
against QCVN 10:2023 B1 / species thresholds, and short-term forecasts + advisories are
produced in **shadow mode** (logged and scored, never pushed to farmers).

Split out of the thesis repo `DATN-20225064` (folder `lab-realtime/`, working tree of
commit `9a95cdd` incl. uncommitted work) on 2026-10-08. Older docs under `docs/guide/` still call this project `lab-realtime`;
read that name as "this repo". There is no runtime dependency on DATN.

## Layout

| Path | Role |
| --- | --- |
| `core/` | Pipeline: `fetch` → `quality` → `chemistry` (NH4→NH3) → `impute` → `classify` → `forecast*` → `alerts`/`forecast_advisory`; `shadow_runner.py` daemon; `report.py` CLI |
| `core/paths.py` | **Only** place that defines filesystem paths (env-overridable `HAP_*`) |
| `core/config.py` | Env flags, station registry, QC ranges, QCVN thresholds |
| `core/models/` | Small runtime models (imputers, forecast, contextual, spatial) — tracked |
| `hap_shared/` | Scoring/preprocessing vendored from DATN `src/` + `thresholds/*.json`. No ML classifier pickles: `classify_grid` falls back to rule scoring (core only uses `_classify_by_scoring`) |
| `app/demo_app.py` | Streamlit demo dashboard |
| `research-map/` | Separate stack: FastAPI backend + worker (Postgres) + React/Vite/Leaflet frontend |
| `ingest/` | Node/Python GreenLab fetchers, `stations.yaml` (station registry) |
| `experiments/` | Research scripts; results index in `experiments/RESULTS.md` |
| `tests/` | pytest suite (imports `core.*`, `experiments.*`) |
| `docs/guide/` | Numbered design/run-log docs (00 = Vietnamese overview) |
| `scripts/` | Repo utilities (data manifest, isolation check, water-mask clip, task installers) |
| `data/` `artifacts/` `runtime/` | **Gitignored local state** — see `docs/data-policy.md` |

## Setup

Two virtualenvs on purpose: streamlit 1.64 pins a starlette that breaks fastapi 0.115.

```powershell
py -3.11 -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt
cd research-map\backend-fastapi; py -3.11 -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt
cd ..\frontend; npm ci
Copy-Item .env.example .env   # repo root; fill TK_DHTB / MK_DHTB / MONGODB_URI
```

`data/` must be restored separately (not in git): `python scripts/data_manifest.py --check`.

## Run

Run everything from the repo root with the root `.venv`.

```powershell
.venv\Scripts\python -m pytest -q                       # 135 tests (~30 s)
.venv\Scripts\python core\report.py --station 06M26042804
.venv\Scripts\streamlit run app\demo_app.py             # http://localhost:8501
.venv\Scripts\python core\shadow_runner.py --station 06M26042804 --interval-seconds 60
powershell -ExecutionPolicy Bypass -File research-map\dev-local.ps1   # api :8010, vite :5173, postgres :5434 (docker)
.venv\Scripts\python scripts\check_isolation.py         # no imports/paths escape the repo
cd research-mapackend-fastapi; $env:PYTHONPATH='.'; .venv\Scripts\python -m pytest tests -q   # backend tests (own venv)
```

`GREENLAB_FETCH_MODE=cache` gives a stable offline run from local history (no API calls);
the shadow runner then reports `stale_sensor_data` and issues nothing — that is the guard working.

research-map Docker: compose reads `research-map/.env` only (not the root `.env`), so the
worker polls GreenLab only if `TK_DHTB`/`MK_DHTB` are set there. The compose project is
named `research-map` — the same name DATN used — so it reuses the existing Postgres
volume. Run only one research-map stack (docker or `dev-local.ps1`) at a time.

## Hard rules

1. **Never delete, overwrite or truncate** anything in `data/`, `artifacts/`, `runtime/`,
   `research-map/cache/`, or the research-map Postgres volume. Sensor history and
   snapshot JSONL files are append-only. Before any risky git op (`clean`, `reset --hard`,
   `checkout -- .`, worktree removal) stop and confirm — `data/` is gitignored, so git
   cannot restore it.
2. **Paths only via `core/paths.py`.** No `Path(__file__).parents[N]` walking to data,
   no cwd-relative `"data/..."` strings in new code. Experiment outputs go to
   `paths.EXPERIMENT_OUTPUT_DIR / <run-name>/` plus a row in `experiments/RESULTS.md`.
3. **No secrets in git.** `.env`, `research-map/.env`, `data/greenlab/handover/` hold
   credentials. Only `.env.example` files are tracked.
4. **Shadow-mode honesty.** Never present stale cache, CSV fallback or mock data as live.
   The shadow runner must not issue a forecast from stale/demo data; mock map mode must
   stay labelled. Weather is observation-only and must not drive alerts directly.
5. **Do not push or open PRs without explicit approval.** Commit messages: short
   (subject ≤ 72 chars, body only if needed).
6. Keep `hap_shared/` self-contained — never re-add an import of DATN `src/`.

## Domain gotchas (read before touching data logic)

- **One live station.** Only `06M26042804` (Cát Bà, Hải Phòng; anchor `NB1`) streams
  data. The research map shows 14 historical stations, but all 14 reuse that single
  sensor's readings; only weather differs per point.
- **COD rail 558.8 = dead sensor**, not pollution. `core/quality.py` flags rail/flatline.
- **NH4 unit**: raw NH4 treated as µg/L ×0.001 → mg/L, then Emerson un-ionised fraction
  (pH, Temperature) → NH3. Gated by `NH4_CONVERSION_CONFIRMED`; vendor confirmation
  is still pending, so keep the basis visible in outputs.
- **VN2000 meridian is per province** (QN 107°45', HP 105°45', TB 105°30').
  `hap_shared/preprocessing.vn2000_to_wgs84` hardcodes 107°45' — wrong for HP data
  (~120 km shift). Only `experiments/prep_exogenous.py` calls it today; fix before reuse.
- Inland stations `06M26042801/02` (Hưng Yên) are out of scope for marine aquaculture.
- QN PO4 values are LOQ-censored constants — screen out before computing forecast skill.
- Imputed parameters (DO, Salinity, PO4…) are model guesses; reports must show the
  imputed fraction.

## Known issues

- `tests/test_observations.py::test_unverified_nh4_to_nh3_conversion_basis_is_visible`
  fails whenever `.env` sets `NH4_CONVERSION_CONFIRMED=true` (test reads live env).
- A machine-wide `PGSSLMODE=require` breaks the local Postgres; `dev-local.ps1` overrides it.
- `app/demo_app.py` runs the full pipeline twice on first load (`st.rerun`) — slow.
- `experiments/archive/` scripts need extras (torch, tabpfn) and are not maintained.
- research-map backend: 2 bathymetry tests fail — xarray needs a netCDF engine
  (`netCDF4` or `scipy`) that the backend venv lacks. Same in DATN.

## Docs map

Start with `docs/guide/00-tong-quan-du-an.md` (overview), `06-runbook.md` (ops),
`07-alerts.md` (alert logic), `17/18` (forecast shadow + advisory),
`23-research-map-implementation-roadmap.md`, `docs/data-policy.md`.
