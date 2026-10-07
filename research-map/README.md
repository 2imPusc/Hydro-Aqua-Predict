# Environmental Context Research Map

Standalone Level-1 research application. It visualises environmental context
next to the historical HSI zones; it never changes HSI radius, confidence, or
alerts.

**Tài liệu:** [Hướng dẫn triển khai tiếp theo](../docs/guide/23-research-map-implementation-roadmap.md)

## Run

```powershell
cd research-map
Copy-Item .env.example .env
docker compose up --build
```

Open `http://localhost:8083`. FastAPI OpenAPI is available at
`http://localhost:8010/docs`.

Flow research endpoints are available at `/api/v1/flow/latest`,
`/api/v1/flow/scenarios`, `/api/v1/flow/{snapshot_id}/streamlines`, and
`/api/v1/flow/{snapshot_id}/station-routes`. The frontend applies zoom-based
LOD to streamline rendering; lower zoom levels decimate lines while higher
zoom levels reveal the full stored overlay.

The worker persists immutable snapshots every 30 minutes. Open-Meteo provides
the baseline spatial context by querying a bounded multi-point grid over the
water domain (typically about 1–1.2 km cells in this demo). Wind, wave, and current
are shown as provider-sampled fields; current velocity is normalized to m/s
and retains provider coordinates/source units; rain and sea level are water-clipped
cells. The 1-1.2 km display grid does not increase the underlying Open-Meteo
ocean-current model resolution (approximately 0.08 degree / 8 km). Copernicus
and GEBCO layers are optional:
they appear only after credentials/cache are configured and are never
fabricated from another provider.

The same worker polls configured GreenLab station(s) every
`SENSOR_POLL_SECONDS` (60 seconds by default) and appends normalized readings
to `sensor_observations`; inserts are idempotent and never overwrite raw rows.
Set `TK_DHTB`, `MK_DHTB`, and `GREENLAB_STATION_SERIALS` in `.env` to enable
the direct feed. `GET /api/v1/stations/{serial}/latest` returns an explicit
`fresh`, `stale`, or `unavailable` state. Sensor data is displayed in the
pilot panel but is not yet used to trigger notifications. Downstream model
jobs can consume `GET /api/v1/stations/{serial}/context`, which bundles the
latest sensor rows with the same environmental snapshot and returns
`model_input_status=blocked` unless both sides are fresh.
Chemical readings retain `vendor_unit_unknown` until the GreenLab calibration
document confirms unit and basis (especially NH4); no implicit conversion is
performed by this ingestion layer.

The spatial acquisition domain is the convex hull of the station registry,
buffered by `CONTEXT_BUFFER_M` (5 km by default) and clipped with the existing
water mask. The worker queries providers with the containing bbox, then filters
display samples/cells back to this water-only geometry. This is a provider
sample grid, not an interpolation or a synthetic vector field.

Copernicus datasets are configured independently because current, sea level,
mixed-layer depth, and waves may be published in separate datasets:

```text
COPERNICUS_CURRENT_DATASET=
COPERNICUS_SEA_LEVEL_DATASET=
COPERNICUS_MLD_DATASET=
COPERNICUS_WAVE_DATASET=
```

The marine request prefers sea grid cells (`cell_selection=sea`) to avoid
coastal land-cell selection. The station network uses cached 200 m water-path
routing and is diagnostic.
Its artifact remains independent from the HSI display grid even though both
currently use the same resolution.
Current alignment appears only when a real Copernicus `vector_grid` snapshot
is available, and remains explicitly labelled `exploratory`.

For GEBCO, place an already-downloaded, clipped GeoTIFF at
`research-map/cache/gebco.tif` (the cache directory is ignored by
Git), or configure `GEBCO_HOST_DIR` and `GEBCO_RASTER_PATH`. Level 1 exposes
its extent and provenance only; it does not expose the file itself or fabricate
tiles.

## Boundaries

- The application owns a separate `context_research` Postgres database.
- It reads HSI geometry and station/map data only; it does not modify them.
- `stale` means the last valid snapshot is being served after its freshness
  deadline, not that the value is current.
- Sensor observations are a separate append-only table; provider failures
  leave the last good values intact and surface as stale rather than silently
  filling missing values.
