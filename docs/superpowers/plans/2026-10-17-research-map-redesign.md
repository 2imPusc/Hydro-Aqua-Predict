# Research-map redesign — implementation plan

> **For agentic workers:** execute task-by-task; steps use checkbox (`- [ ]`) syntax. Owner-approved design (2026-10-17).

**Goal:** turn `research-map/` from a single-screen demo into a modern, fast research dashboard: a primary *sea monitoring* map plus one view per research direction (H1 forecast, H2 weather advisory, H3 zoning, H4 reliability incl. foreign validation).

**Architecture:** the root `.venv` exports compact, versioned JSON research artifacts (`artifacts/research-map/<YYYYMMDD-HHMM>/`, write-once). The FastAPI backend (own venv, Docker mounts the repo read-only at `/workspace`) serves them read-only via a new `research` router, plus a live read-only view of the shadow ledger. The React frontend is restructured into views with a shared design system, hash routing, lazy-loaded views and visibility-aware polling.

**Tech stack:** FastAPI, pydantic; React 18 + TypeScript + Vite 6 + Tailwind v4 + react-leaflet 4 + lucide-react. No new runtime dependencies unless justified (remove unused `maplibre-gl`).

---

## Hard rules (all tasks)
- AGENTS.md hard rules apply: never delete/overwrite anything in `data/`, `artifacts/`, `runtime/`, `research-map/cache/`, Postgres volume. Export dirs are write-once (new timestamped dir per run).
- Shadow-mode honesty: every view shows data provenance and state (`live` / `fresh` / `stale` / `cache` / `mock` / `research_only` / `withdrawn` / `unavailable`). Never fabricate values when an artifact is missing — show an explicit empty state with the reason.
- Weather is observation-only; never shown as an alert trigger.
- Maryland DNR (Chesapeake) raw data must not be redistributed: export only aggregated pair/radius statistics, and show the credit "Maryland Department of Natural Resources, Tidewater Ecosystem Assessment Division". Credit every foreign source (HK EPD, NOAA NERRS, USGS, TWDB, IRLON/HBOI-FAU).
- Untracked `research-map/frontend/src/main.pre-vector-particles.tsx.bak` must not be deleted (untracked = unrecoverable); leave it alone.
- Commits: subject ≤ 72 chars, end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Stage explicit paths only. No push.

## API contract (backend ⇄ frontend) — prefix `/api/v1/research`

All responses include `"export_version"` (dir name or `null`) and `"status"` ∈ `ready | unavailable` (+ `"reason"` when unavailable).

| Endpoint | Response |
| --- | --- |
| `GET /overview` | `{status, export_version, generated_at, directions: [{id: "H1"\|"H2"\|"H3"\|"H4", title, stage, headline, findings: [str], limitations: [str], research_log: [str], next: [str]}]}` |
| `GET /forecast/long?station=06M26042804` | Live read of `runtime/forecast-shadow/` long ledger (read-only). `{status, station, ledger_state: "empty"\|"active"\|"missing", latest_issued_at, items: [{target, horizon_min, feature_set, model_variant, bundle_role, issued_at, valid_at, value, pi80: [lo, hi]\|null, pi90: [lo, hi]\|null, ph_input_status, sensor_status}], skips: [{target, horizon_min, feature_set, reason, at}], withdrawn: [{target, feature_set, horizon_min, reason}], scoring: [{target, horizon_min, model_variant, n, mae, persistence_mae, coverage80, coverage90}]}` |
| `GET /forecast/benchmark` | From export: gate-#16 tables (H1.2, A1 nopH, A3 pH clean) and conformal coverage (v3, aci_amp). `{status, export_version, temperature: [{horizon_min, feature_set, skill, folds_won, dm_p, gate}], ph_clean: [...], conformal: [{method, horizon_min, level, coverage, coverage_late, width, winkler}]}` |
| `GET /weather/status?station=` | Read-only from the weather snapshot JSONL (`artifacts/experiments/forecast-v2/weather-snapshots.jsonl`): `{status, coverage_24h, coverage_7d, health: "healthy"\|"degraded"\|"unavailable", last_captured_at, hourly: [{hour, captured: bool}] (last 7 d), note: "observation-only"}` |
| `GET /suitability?variant=A_W_SUM\|N1_W_SUM&region=vn\|hk` | From export: `{status, export_version, variant, region, cells: GeoJSON FeatureCollection (point or square cells with score 0–1, layer scores), farms: GeoJSON (validation polygons/points), auc: number\|null, notes: [str]}` |
| `GET /reliability/foreign` | `{status, export_version, datasets: [{id, name, region, country, cadence, n_stations, n_pairs, period, climate, licence, credit, redistributable: bool, headline, bbox: [minLon, minLat, maxLon, maxLat], scales: ["hourly", ...]}]}` |
| `GET /reliability/foreign/{id}?var=Temp&scale=hourly&transfer=raw` | `{status, export_version, id, stations: GeoJSON points {station, habitat?, regime_class, wet_sal_median}, pairs: [{anchor, target, km, same_regime: bool, dsal, share, ci_low, gate80, gate90, gate95, lon1, lat1, lon2, lat2}], radius: [{var, regime, transfer, scale, gate, radius_km}], findings: [str], available: {vars: [...], scales: [...], transfers: [...]}}` |
| `GET /reliability/vn` | VN salinity-regime layer from the A6 run if present, else `unavailable` with reason `a6_not_exported`. `{status, export_version, stations: GeoJSON, layer: GeoJSON\|null, nb1_regime, pass_counts, notes}` |

## Tasks

### Task 1 (backend, parallel with Task 2) — export script + research router
- `scripts/export_research_map_artifacts.py` (root venv; paths via `core.paths`): reads run dirs listed in `experiments/RESULTS.md` (H1.2/A1/A3 benchmark & gate tables, conformal v3 + amp, `suitability-h3-2024-draft`/nearshore + `suitability-hk-2024`, `hk-epd-reliability-20261016`, `nerrs-h4-pilot-20261016`, `nerrs-multi-h4-reliability-20261017`, `mddnr-h4-reliability-20261017` (aggregates only), `twdb-h4-reliability-20261017`, `usgs-sfbay-h4-reliability-20261017`, plus later `h4-multiscale-20261017`, `irlon-h4-reliability-20261017`, `vn-salinity-regime-h41-20261017` if they exist) and `docs/research-log.md` headlines; writes `artifacts/research-map/<stamp>/{overview,forecast_benchmark,suitability_<region>_<variant>,reliability_foreign_index,reliability_foreign_<id>,reliability_vn}.json` + `manifest.json` (sources + sha256). Missing inputs → omitted with a reason in manifest, never fabricated. Station coordinates come from each dataset's `stations.csv`/loader outputs. Keep each JSON small (round floats, no raw series).
- `research-map/backend-fastapi/app/research.py` (APIRouter) + settings `research_export_dir` (default `/workspace/artifacts/research-map` if exists else repo `artifacts/research-map`), `hap_runtime_dir` (default `/workspace/runtime` else repo `runtime`), `weather_snapshots_path`. Picks the newest export dir by name; caches parsed JSON by mtime; never writes. Live ledger read tails the JSONL efficiently (only last N MB / last 48 h).
- Tests: root `tests/test_export_research_map_artifacts.py` (synthetic run dirs in tmp_path); backend `research-map/backend-fastapi/tests/test_research_api.py` (FastAPI TestClient against a tmp export dir and tmp ledger; unavailable states).
- Run: root pytest + isolation; backend tests (`cd research-map\backend-fastapi; $env:PYTHONPATH='.'; .venv\Scripts\python -m pytest tests -q`). Run the export once for real and report the export dir.

### Task 2 (frontend core, parallel with Task 1) — design system, shell, monitoring view, performance
- Design system: CSS variables (light + dark via `prefers-color-scheme` and a toggle), Inter/system font stack, spacing/radius/shadow tokens, glass panels over the map, consistent status chips, accessible contrast, Vietnamese labels.
- Shell: left navigation rail (Giám sát · H1 Dự báo · H2 Thời tiết · H3 Phân vùng · H4 Độ tin cậy), top bar with live status chips (sensor fresh/stale/age, context snapshot age, data mode live/mock), hash routing (`#/monitor`, `#/forecast`, `#/weather`, `#/zoning`, `#/reliability`, `#/reliability/foreign/<id>`), views loaded with `React.lazy`.
- Structure: `src/app/` (shell, routing), `src/views/<view>/`, `src/components/map/overlays/<Overlay>.tsx` (split `MapOverlays.tsx`, one overlay per file, behaviour unchanged), `src/components/ui/` (Panel, Chip, Stat, Legend, EmptyState, Tabs, Toggle), `src/hooks/usePolling.ts` (AbortController, pause when `document.hidden`, backoff on error, stops "building" retries after N), `src/api/` (typed client incl. the research endpoints from the contract, stubs allowed until Task 1 lands), `src/types/`.
- Monitoring view = current map features re-laid out: map + floating layer control (grouped: Bối cảnh, Dòng chảy & gió, Độ sâu, Mạng trạm), right inspector panel (sensor latest with QC + freshness, layer provenance, bathymetry sample), legends; keep mock-mode labelling.
- Performance: remove unused `maplibre-gl`; Leaflet `preferCanvas`; memoize GeoJSON data/styles and stable keys; avoid re-rendering the MapContainer on panel state changes; throttle zoom state; split vendor chunks (leaflet) in Vite; particles only when enabled and paused when tab hidden. Report bundle size before/after (`npm run build`).
- Verify: `npm run build` clean (tsc strict as configured).

### Task 3 (frontend research views; after Tasks 1–2) — H1–H4 pages
- H1 Dự báo: live shadow cards per target/horizon (with/without pH side by side, PI bands, withdrawn pH listed with reason, skip reasons), benchmark tables/charts (skill vs persistence, gate pass), conformal coverage chart. Small SVG charts, no heavy chart lib.
- H2 Thời tiết: coverage heat-strip (7 d × 24 h), health chip, observation-only note.
- H3 Phân vùng: map with variant switch (Ghaderi vs nearshore), region switch VN/HK, farms overlay, AUC/notes panel.
- H4 Độ tin cậy: VN tab (regime layer or explicit unavailable state + legacy HSI labelled "chưa kiểm chứng") and Foreign tab: dataset cards (headline, cadence, stations, licence/credit), dataset map (stations coloured by regime class, pair lines coloured by share; filters var/scale/transfer/same-vs-different regime), radius table, cross-dataset summary table (RL-24), findings list.
- Verify: `npm run build`; run backend locally + vite, open with Playwright (Chromium) and save screenshots of every view to the scratchpad; check console errors.

### Task 4 — docs
- Update `research-map/README.md` (views, research endpoints, export step), `AGENTS.md` run section (export command), add RL entry and RESULTS row if an export run dir is created under artifacts/experiments (the research-map export lives in artifacts/research-map, document it in docs/data-policy.md).
