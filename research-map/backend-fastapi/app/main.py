from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
import psycopg

from app.repository import SnapshotRepository, snapshot_status
from app.schemas import ContextSnapshot, LayerPayload, SensorLatest, SensorObservation, SensorObservationIn
from app.settings import settings
from app.domain import build_context_domain, stations_geojson
from app.aquaculture_artifacts import build_aquaculture_artifacts
from app.network import building_station_network, ensure_station_network_cache, load_station_network_cache
from app.hsi_cache import load_hsi_cache
from app.flow_artifacts import load_flow_artifact
from app.bathymetry_artifacts import LODS, load_geojson as load_bathymetry_geojson, load_manifest as load_bathymetry_manifest, sample as sample_bathymetry
from app import bathymetry_etopo
from app.aquaculture_artifacts import MODES as AQUACULTURE_MODES, SCENARIOS as AQUACULTURE_SCENARIOS, load_aquaculture_artifact
from app.research import latest_export_version, router as research_router
from app.admin_config import router as admin_config_router
from app.hazard_api import router as hazard_router


app = FastAPI(title="Environmental Context Research API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_allow_origins), allow_methods=["GET", "POST"], allow_headers=["*"])
# Research exports (foreign pairs, VN regime layer) are 0.1-1.3 MB of JSON; gzip cuts them ~10x.
app.add_middleware(GZipMiddleware, minimum_size=1024)
repository = SnapshotRepository(settings.database_url)
app.include_router(research_router)
app.include_router(hazard_router)
app.include_router(admin_config_router)
logger = logging.getLogger(__name__)


# Registered handlers run inside CORSMiddleware, so the browser sees a JSON error with CORS
# headers instead of a bare 500 (which Starlette emits outside CORS and shows as a CORS error).
@app.exception_handler(psycopg.OperationalError)
@app.exception_handler(psycopg.InterfaceError)
def database_unavailable(_request: Request, exc: psycopg.Error) -> JSONResponse:
    logger.warning("context database unavailable: %s", exc)
    return JSONResponse(status_code=503, content={"status": "unavailable", "reason": "database_unavailable"})


@app.exception_handler(psycopg.Error)
def database_error(_request: Request, exc: psycopg.Error) -> JSONResponse:
    logger.exception("context database error", exc_info=exc)
    return JSONResponse(status_code=500, content={"status": "error", "reason": "database_error"})


@app.on_event("startup")
def initialize_repository() -> None:
    try:
        repository.initialize()
    except psycopg.Error as exc:
        # Research endpoints (/api/v1/research) are file-backed and must stay up without
        # Postgres; database-backed endpoints keep failing until it is reachable.
        logger.warning("context database unavailable at startup: %s", exc)
    # Warm the shapefile-backed domain once so concurrent map requests do not
    # repeat the expensive water-mask intersection.
    build_context_domain(settings.context_buffer_m)


def _as_snapshot(row: dict) -> ContextSnapshot:
    now = datetime.now(timezone.utc)
    retrieved = row["retrieved_at"]
    if retrieved.tzinfo is None:
        retrieved = retrieved.replace(tzinfo=timezone.utc)
    status = snapshot_status(row, now)
    layers = []
    for item in row["layers"]:
        # A previously fresh provider layer becomes stale with its snapshot.
        if status == "stale" and item["status"] == "fresh":
            item = {**item, "status": "stale"}
        layers.append(LayerPayload.model_validate(item))
    return ContextSnapshot(snapshot_id=row["snapshot_id"], status=status, issued_at=row["issued_at"], valid_at=row["valid_at"], retrieved_at=retrieved, age_seconds=max(0, int((now - retrieved).total_seconds())), bbox=row["bbox"], domain_id=row.get("domain_id"), geometry_hash=row.get("geometry_hash"), layers=layers)


def latest_snapshot() -> ContextSnapshot:
    row = repository.latest()
    if row is None:
        raise HTTPException(status_code=503, detail={"reason_code": "no_context_snapshot"})
    return _as_snapshot(row)


@app.get("/api/v1/health")
def health() -> dict:
    try:
        snapshot = latest_snapshot()
        return {"status": "ok", "database": "ready", "latest_snapshot_id": snapshot.snapshot_id, "context_status": snapshot.status}
    except HTTPException:
        return {"status": "degraded", "database": "ready", "context_status": "unavailable", "reason_code": "no_context_snapshot"}


# A down database costs a connect timeout per call; remember the failure briefly so the
# shell's 20 s status poll (and several open tabs) do not each wait for it.
STATUS_DB_RETRY_SECONDS = 30.0
_status_db_down_until: dict[str, float] = {"until": 0.0}


@app.get("/api/v1/status")
def status(station: str | None = None) -> dict:
    """Light top-bar status: snapshot and sensor freshness without layer payloads, plus the research export.

    Database failures degrade to ``unavailable`` entries instead of an error, so the shell can keep polling.
    """
    station_serial = station or (settings.greenlab_station_serials[0] if settings.greenlab_station_serials else "06M26042804")
    now = datetime.now(timezone.utc)
    export_version = latest_export_version()
    research = {"status": "ready" if export_version else "unavailable", "export_version": export_version}
    unavailable = {"status": "unavailable", "reason": "database_unavailable"}
    summary = None
    if time.monotonic() >= _status_db_down_until["until"]:
        try:
            summary = repository.status_summary(station_serial)
        except psycopg.Error:
            _status_db_down_until["until"] = time.monotonic() + STATUS_DB_RETRY_SECONDS
    if summary is None:
        return {"status": "degraded", "generated_at": now.isoformat(), "context": dict(unavailable),
                "sensor": {**unavailable, "station_serial": station_serial}, "research": research}

    row = summary["snapshot"]
    if row is None:
        context = {"status": "unavailable", "reason": "no_context_snapshot"}
    else:
        retrieved = row["retrieved_at"] if row["retrieved_at"].tzinfo else row["retrieved_at"].replace(tzinfo=timezone.utc)
        context = {"status": snapshot_status(row, now), "snapshot_id": row["snapshot_id"], "retrieved_at": retrieved.isoformat(),
                   "age_seconds": max(0, int((now - retrieved).total_seconds()))}
    latest = summary["latest_observed_at"]
    if latest is None:
        sensor = {"status": "unavailable", "reason": "sensor_observations_missing", "station_serial": station_serial}
    else:
        latest = latest if latest.tzinfo else latest.replace(tzinfo=timezone.utc)
        age = max(0, int((now - latest).total_seconds()))
        sensor = {"status": "fresh" if age <= settings.sensor_stale_minutes * 60 else "stale", "station_serial": station_serial,
                  "latest_observed_at": latest.isoformat(), "age_seconds": age}
    overall = "ok" if context["status"] == "fresh" and sensor["status"] == "fresh" else "degraded"
    return {"status": overall, "generated_at": now.isoformat(), "context": context, "sensor": sensor, "research": research}


@app.get("/api/v1/context/latest", response_model=ContextSnapshot)
def context_latest(_bbox: Annotated[str | None, Query(alias="bbox")] = None) -> ContextSnapshot:
    # v1 stores the fixed Hai Phong research bbox. The query is retained as a
    # forward-compatible public interface for future spatial subsetting.
    return latest_snapshot()


@app.get("/api/v1/context/{snapshot_id}/layers/{layer}", response_model=LayerPayload)
def context_layer(snapshot_id: str, layer: str) -> LayerPayload:
    row = repository.by_id(snapshot_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"reason_code": "snapshot_not_found"})
    snapshot = _as_snapshot(row)
    for item in snapshot.layers:
        if item.layer == layer:
            return item
    raise HTTPException(status_code=404, detail={"reason_code": "layer_not_found"})


@app.get("/api/v1/hsi-zones")
def hsi_zones() -> dict:
    """Read the worker-produced HSI artifact; never calculate it in a request."""
    cached = load_hsi_cache(f"{settings.cache_dir}/hsi_zones.json")
    return cached or {"observed_at": None, "mode": "historical_hsi_reference_only", "status": "building", "used_by_alerts": False, "features": []}


@app.get("/api/v1/stations")
def stations() -> dict:
    """Read-only station markers from the existing map registry."""
    try:
        return stations_geojson()
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=503, detail={"reason_code": str(exc)}) from exc


@app.get("/api/v1/stations/{station_serial}/latest", response_model=SensorLatest)
def station_latest(station_serial: str) -> SensorLatest:
    """Return the latest normalized observations and an explicit freshness state."""
    rows = repository.latest_sensor(station_serial)
    if not rows:
        return SensorLatest(station_serial=station_serial, status="unavailable", observations=[], reason_code="sensor_observations_missing")
    latest = max(row["observed_at"] for row in rows)
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    age = max(0, int((datetime.now(timezone.utc) - latest).total_seconds()))
    status = "fresh" if age <= settings.sensor_stale_minutes * 60 else "stale"
    observations = [SensorObservation.model_validate(row) for row in rows]
    return SensorLatest(
        station_serial=station_serial,
        status=status,
        latest_observed_at=latest,
        age_seconds=age,
        observations=observations,
        reason_code=None if status == "fresh" else "sensor_data_stale",
    )


@app.post("/api/v1/stations/{station_serial}/observations")
def ingest_station_observations(
    station_serial: str,
    observations: list[SensorObservationIn],
    background_tasks: BackgroundTasks,
    x_ingest_token: str | None = Header(default=None),
) -> dict:
    """Internal ingestion boundary; raw payloads remain outside this table."""
    if settings.sensor_ingest_token and x_ingest_token != settings.sensor_ingest_token:
        raise HTTPException(status_code=401, detail={"reason_code": "invalid_sensor_ingest_token"})
    if any(item.station_serial != station_serial for item in observations):
        raise HTTPException(status_code=422, detail={"reason_code": "station_serial_mismatch"})
    ingested_at = datetime.now(timezone.utc)
    rows = [{**item.model_dump(), "ingested_at": ingested_at} for item in observations]
    inserted = repository.insert_sensor_observations(rows)
    background_tasks.add_task(build_aquaculture_artifacts, repository, settings.cache_dir, settings.greenlab_station_serials, settings.latitude, settings.longitude, settings.nh4_unit_scale, settings.sensor_stale_minutes, settings.nh3_max_metric_gap_minutes)
    return {"status": "accepted", "station_serial": station_serial, "received": len(rows), "inserted": inserted, "ingested_at": ingested_at.isoformat()}


@app.get("/api/v1/stations/{station_serial}/context")
def station_context(station_serial: str) -> dict:
    """Return the causal model-input bundle for a station.

    This is an integration contract, not an alert endpoint: downstream
    predictors must reject the bundle unless both sensor and environmental
    context are fresh. Notifications remain shadow-only in this pilot.
    """
    sensor = station_latest(station_serial)
    context = latest_snapshot()
    model_input_status = "ready" if sensor.status == "fresh" and context.status == "fresh" else "blocked"
    return {
        "station_serial": station_serial,
        "model_input_status": model_input_status,
        "prediction_mode": "shadow_only",
        "sensor": sensor.model_dump(mode="json"),
        "context": context.model_dump(mode="json"),
        "reason_code": None if model_input_status == "ready" else "sensor_or_context_not_fresh",
    }


@app.get("/api/v1/aquaculture-map")
def aquaculture_map(mode: str = "live", scenario: str = "normal") -> dict:
    """Serve worker-built station advisory geometry; never compute in a request."""
    if mode not in AQUACULTURE_MODES:
        raise HTTPException(status_code=422, detail={"reason_code": "invalid_mode", "allowed": sorted(AQUACULTURE_MODES)})
    if mode == "mock" and scenario not in AQUACULTURE_SCENARIOS:
        raise HTTPException(status_code=422, detail={"reason_code": "invalid_mock_scenario", "allowed": sorted(AQUACULTURE_SCENARIOS)})
    artifact = load_aquaculture_artifact(settings.cache_dir, mode, scenario)
    return artifact or {"status": "building", "mode": mode, "scenario": scenario, "artifact_version": "aquaculture-map-v1", "type": "FeatureCollection", "features": []}


@app.get("/api/v1/context-domain")
def context_domain() -> dict:
    """Convex-hull context domain buffered 5 km around the station network."""
    try:
        return build_context_domain(settings.context_buffer_m)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=503, detail={"reason_code": str(exc)}) from exc


def _bathymetry_manifest() -> dict:
    """The API is read-only: the worker owns all NetCDF and geometry work."""
    return load_bathymetry_manifest(settings.cache_dir) or {
        "status": "building",
        "reason_code": "bathymetry_artifact_not_ready",
        "artifact_version": "copernicus-sdb-100m-v6",
    }


@app.get("/api/v1/bathymetry/manifest")
def bathymetry_manifest() -> dict:
    return _bathymetry_manifest()


def _bathymetry_layer(kind: str, lod: str) -> dict:
    if lod not in LODS:
        raise HTTPException(status_code=422, detail={"reason_code": "invalid_lod", "allowed": list(LODS)})
    manifest = _bathymetry_manifest()
    if manifest.get("status") != "ready":
        return manifest
    geojson = load_bathymetry_geojson(settings.cache_dir, manifest, kind, lod)
    if geojson is None:
        return {"status": "building", "reason_code": "bathymetry_lod_not_ready", "lod": lod}
    return {**geojson, "status": "ready", "lod": lod, "artifact_version": manifest["artifact_version"], "depth_source": manifest["depth_source"]}


@app.get("/api/v1/bathymetry/depth-bands")
def bathymetry_depth_bands(lod: str = "low") -> dict:
    return _bathymetry_layer("bands", lod)


@app.get("/api/v1/bathymetry/contours")
def bathymetry_contours(lod: str = "low") -> dict:
    return _bathymetry_layer("contours", lod)


@app.get("/api/v1/bathymetry/sample")
def bathymetry_sample(lon: float, lat: float) -> dict:
    result = sample_bathymetry(settings.cache_dir, _bathymetry_manifest(), lon, lat)
    # Separate source, separate key: ETOPO never fills a Copernicus gap in place.
    result["etopo"] = bathymetry_etopo.sample(settings.cache_dir, bathymetry_etopo.load_manifest(settings.cache_dir), lon, lat)
    return result


def _etopo_manifest() -> dict:
    return bathymetry_etopo.load_manifest(settings.cache_dir) or {
        "status": "building", "reason_code": "etopo_artifact_not_ready", "artifact_version": bathymetry_etopo.ETOPO_ARTIFACT_VERSION,
    }


@app.get("/api/v1/bathymetry/etopo/manifest")
def bathymetry_etopo_manifest() -> dict:
    return _etopo_manifest()


@app.get("/api/v1/bathymetry/etopo/{kind}")
def bathymetry_etopo_layer(kind: str, lod: str = "low") -> dict:
    """ETOPO 2022 isobands / isobaths / confidence flags (worker-built, read-only here)."""
    if kind not in ("isobands", "isobaths", "flags"):
        raise HTTPException(status_code=404, detail={"reason_code": "unknown_layer", "allowed": ["isobands", "isobaths", "flags"]})
    if lod not in bathymetry_etopo.LOD_TOLERANCE:
        raise HTTPException(status_code=422, detail={"reason_code": "invalid_lod", "allowed": list(bathymetry_etopo.LOD_TOLERANCE)})
    manifest = _etopo_manifest()
    if manifest.get("status") != "ready":
        return manifest
    geojson = bathymetry_etopo.load_geojson(settings.cache_dir, manifest, kind, lod)
    if geojson is None:
        return {"status": "building", "reason_code": "etopo_lod_not_ready", "lod": lod}
    return {**geojson, "status": "ready", "lod": lod, "artifact_version": manifest["artifact_version"], "depth_source": manifest["depth_source"]}


def _static_network() -> dict:
    network = load_station_network_cache(settings.cache_dir, settings.context_buffer_m)
    if network is None:
        return building_station_network()
    return network


def _flow_artifact(snapshot_id: str) -> dict:
    row = repository.by_id(snapshot_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"reason_code": "snapshot_not_found"})
    artifact = load_flow_artifact(settings.cache_dir, snapshot_id)
    if artifact is None:
        raise HTTPException(status_code=409, detail={"reason_code": "flow_artifact_building", "snapshot_id": snapshot_id})
    if artifact.get("snapshot_id") != snapshot_id or artifact.get("payload_hash") != row["payload_hash"]:
        raise HTTPException(status_code=409, detail={"reason_code": "flow_artifact_snapshot_mismatch", "snapshot_id": snapshot_id})
    return artifact


@app.get("/api/v1/station-network")
def station_network(background_tasks: BackgroundTasks) -> dict:
    """Static water-only topology. Dynamic flow belongs to a snapshot artifact."""
    try:
        network = _static_network()
        if network.get("network_status") == "building":
            background_tasks.add_task(ensure_station_network_cache, settings.cache_dir, settings.context_buffer_m)
        return network
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=503, detail={"reason_code": str(exc)}) from exc


@app.get("/api/v1/flow/scenarios")
def flow_scenarios() -> dict:
    """Research scenarios; only configured providers are marked available."""
    row = repository.latest()
    current = next((item for item in (row["layers"] if row else []) if item.get("layer") == "current"), None)
    available = bool(current and current.get("status") in {"fresh", "stale"})
    return {"scenarios": [{"id": "latest", "label": "Latest provider current", "available": available, "mode": "exploratory" if available else "unavailable"}, {"id": "flood", "label": "Flood tide", "available": False, "mode": "not_configured"}, {"id": "ebb", "label": "Ebb tide", "available": False, "mode": "not_configured"}], "source": current.get("provenance", {}).get("source") if current else None}


@app.get("/api/v1/flow/latest")
def flow_latest() -> dict:
    """Flow metadata plus counts; geometry is served by the focused endpoints."""
    row = repository.latest()
    if row is None:
        return {"flow_id": None, "status": "unavailable", "mode": "unavailable", "streamline_count": 0, "station_route_count": 0}
    current = next((item for item in (row["layers"] if row else []) if item.get("layer") == "current"), None)
    artifact = load_flow_artifact(settings.cache_dir, row["snapshot_id"])
    return {"flow_id": row["snapshot_id"], "status": current.get("status", "unavailable") if current else "unavailable", "mode": artifact.get("mode", "building") if artifact else "building", "provenance": current.get("provenance") if current else None, "streamline_count": artifact.get("streamline_count", 0) if artifact else 0, "station_route_count": artifact.get("current_supported_station_edge_count", 0) if artifact else 0, "geometry_hash": row.get("geometry_hash")}


@app.get("/api/v1/flow/{flow_id}/artifact")
def flow_artifact(flow_id: str) -> dict:
    return _flow_artifact(flow_id)


@app.get("/api/v1/flow/{flow_id}/streamlines")
def flow_streamlines(flow_id: str) -> dict:
    artifact = _flow_artifact(flow_id)
    features = [feature for feature in artifact.get("features", []) if feature.get("properties", {}).get("kind") == "flow_streamline"]
    return {"flow_id": flow_id, "mode": artifact["mode"], "type": "FeatureCollection", "features": features}


@app.get("/api/v1/flow/{flow_id}/station-routes")
def flow_station_routes(flow_id: str) -> dict:
    artifact = _flow_artifact(flow_id)
    features = [feature for feature in artifact.get("features", []) if feature.get("properties", {}).get("kind") == "current_supported_station_edge"]
    return {"flow_id": flow_id, "mode": artifact["mode"], "type": "FeatureCollection", "features": features}
