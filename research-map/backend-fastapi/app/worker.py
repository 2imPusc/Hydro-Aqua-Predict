from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.bathymetry import describe_gebco
from app.providers import fetch_open_meteo_context, unavailable_layer
from app.copernicus import fetch_copernicus_layers
from app import refresh
from app.domain import build_context_domain, region_water_geometry
from app.repository import SnapshotRepository
from app.settings import settings
from app.network import ensure_station_network_cache
from app.flow_artifacts import FLOW_ARTIFACT_VERSION, build_flow_artifact, load_flow_artifact
from app.hsi_cache import build_hsi_cache
from app.bathymetry_artifacts import ensure_bathymetry_artifact
from app.bathymetry_etopo import ensure_etopo_artifact
from app.bathymetry_gebco import ensure_gebco_artifact
from app.sensor_provider import GREENLAB_LOCAL_TZ, fetch_station, fetch_station_history, normalize_history_csv, normalize_readings
from app.aquaculture_artifacts import build_aquaculture_artifacts

logger = logging.getLogger(__name__)
# How often the worker looks for a map refresh request between scheduled snapshots.
REFRESH_CHECK_SECONDS = 5


def _snapshot(layers: list[dict], domain: dict) -> dict:
    retrieved_at = datetime.now(timezone.utc)
    valid_times = [
        item["provenance"]["valid_at"]
        for item in layers
        if item.get("provenance") and item["provenance"].get("valid_at")
    ]
    raw = json.dumps({"domain_hash": domain["geometry_hash"], "layers": layers}, sort_keys=True, separators=(",", ":")).encode()
    return {
        "snapshot_id": str(uuid.uuid4()), "retrieved_at": retrieved_at,
        "issued_at": retrieved_at, "valid_at": max(valid_times) if valid_times else None,
        "stale_after": retrieved_at + timedelta(minutes=settings.stale_minutes),
        "bbox": domain["provider_bbox"], "domain_id": domain["domain_id"], "geometry_hash": domain["geometry_hash"],
        "layers": layers, "payload_hash": hashlib.sha256(raw).hexdigest(), "worker_status": "ready",
    }


async def run_once(repository: SnapshotRepository) -> bool:
    domain = build_context_domain(settings.context_buffer_m)
    min_lon, min_lat, max_lon, max_lat = domain["provider_bbox"]
    latitude, longitude = (min_lat + max_lat) / 2, (min_lon + max_lon) / 2
    region_bbox = tuple(settings.context_region_bbox)
    try:
        # Environment fields cover the whole region (Hải Phòng – Cát Bà – Hạ Long), not only the 5 km station buffer;
        # the station network, flow rays and advisories still use the station domain.
        layers = await fetch_open_meteo_context(
            latitude, longitude, settings.stale_minutes,
            bbox=list(region_bbox), buffer_m=settings.context_buffer_m,
            region_step=settings.context_region_step_deg, region_water=region_water_geometry(region_bbox),
        )
    except Exception as exc:
        # Preserve the last known-good immutable snapshot. Replacing it with
        # an all-unavailable fetch failure makes a transient provider outage
        # erase the map's usable environmental context. Say why, so a quota
        # (HTTP 429) or outage is visible instead of a silently "stale" map.
        status = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning("Open-Meteo regional fetch failed (%s%s); keeping the last snapshot", type(exc).__name__, f", HTTP {status}" if status else "")
        return False
    copernicus_layers = await asyncio.to_thread(
        fetch_copernicus_layers,
        username=settings.copernicus_username,
        password=settings.copernicus_password,
        current_dataset=settings.copernicus_current_dataset or settings.copernicus_physics_dataset,
        sea_level_dataset=settings.copernicus_sea_level_dataset or settings.copernicus_physics_dataset,
        mld_dataset=settings.copernicus_mld_dataset or settings.copernicus_physics_dataset,
        wave_dataset=settings.copernicus_wave_dataset,
        bbox=list(region_bbox), stale_minutes=settings.stale_minutes,
        buffer_m=settings.context_buffer_m,
    )
    if copernicus_layers:
        replacements = {item["layer"]: item for item in copernicus_layers}
        layers = [replacements.pop(item["layer"], item) for item in layers]
        layers.extend(replacements.values())
    if not any(item["layer"] == "mixed_layer_depth" for item in layers):
        layers.append(unavailable_layer("mixed_layer_depth", "copernicus_not_configured"))
    layers.append(describe_gebco(settings.gebco_raster_path, settings.stale_minutes))
    snapshot = _snapshot(layers, domain)
    inserted = repository.insert_immutable(snapshot)
    # Re-use the original immutable row on a duplicate payload so old
    # snapshots created before this feature also receive an artifact.
    snapshot_row = snapshot if inserted else repository.by_payload_hash(snapshot["payload_hash"])
    network = await asyncio.to_thread(ensure_station_network_cache, settings.cache_dir, settings.context_buffer_m)
    if snapshot_row is not None:
        await asyncio.to_thread(build_flow_artifact, snapshot_row, network, settings.cache_dir)
    await asyncio.to_thread(build_aquaculture_artifacts, repository, settings.cache_dir, settings.greenlab_station_serials, settings.latitude, settings.longitude, settings.nh4_unit_scale, settings.sensor_stale_minutes, settings.nh3_max_metric_gap_minutes)
    return inserted


# Full sensor history up to now: the latest-reading endpoint only gives the newest value, so gaps (worker down,
# missing credentials) are filled from /Datums/DataByDate, from the newest stored day to today (<= 30 days back).
SENSOR_BACKFILL_MINUTES = 30
SENSOR_BACKFILL_MAX_DAYS = 30
SENSOR_BACKFILL_CHUNK_DAYS = 7


async def backfill_sensor_history(repository: SnapshotRepository) -> int:
    if not settings.greenlab_api_enabled or not settings.greenlab_api_username or not settings.greenlab_api_password:
        return 0
    today = datetime.now(GREENLAB_LOCAL_TZ).date()
    inserted = 0
    for station_serial in settings.greenlab_station_serials:
        try:
            newest = await asyncio.to_thread(repository.latest_observed_at, station_serial)
            start = newest.astimezone(GREENLAB_LOCAL_TZ).date() if newest else today - timedelta(days=14)
            start = max(start, today - timedelta(days=SENSOR_BACKFILL_MAX_DAYS))
            while start <= today:
                end = min(today, start + timedelta(days=SENSOR_BACKFILL_CHUNK_DAYS - 1))
                text = await fetch_station_history(station_serial, settings.greenlab_api_base_url, settings.greenlab_api_username, settings.greenlab_api_password, start, end)
                inserted += await asyncio.to_thread(repository.insert_sensor_observations, normalize_history_csv(text, station_serial))
                start = end + timedelta(days=1)
        except Exception as exc:
            logger.warning("GreenLab history backfill failed for %s (%s)", station_serial, type(exc).__name__)
    if inserted:
        logger.warning("GreenLab history backfill: %d new observations", inserted)
    return inserted


async def ingest_sensor_once(repository: SnapshotRepository) -> int:
    """Poll configured stations and append only unseen observations.

    A provider outage is isolated per station so context snapshots keep
    running. The latest-sensor API exposes the resulting stale state.
    """
    if not settings.greenlab_api_enabled or not settings.greenlab_api_username or not settings.greenlab_api_password:
        return 0
    inserted = 0
    for station_serial in settings.greenlab_station_serials:
        try:
            readings = await fetch_station(
                station_serial, settings.greenlab_api_base_url,
                settings.greenlab_api_username, settings.greenlab_api_password,
            )
            observations = normalize_readings(readings, station_serial)
            inserted += await asyncio.to_thread(repository.insert_sensor_observations, observations)
        except Exception:
            # Do not erase or replace the last good rows on an outage.
            continue
    return inserted


async def serve() -> None:
    repository = SnapshotRepository(settings.database_url)
    repository.initialize()
    # Mock scenarios are deterministic and do not depend on bathymetry or
    # external providers. Publish them first so the demo mode is available
    # immediately after a worker restart while heavier artifacts build.
    await asyncio.to_thread(
        build_aquaculture_artifacts,
        repository, settings.cache_dir, settings.greenlab_station_serials,
        settings.latitude, settings.longitude, settings.nh4_unit_scale, settings.sensor_stale_minutes, settings.nh3_max_metric_gap_minutes,
    )
    hsi_cache_path = f"{settings.cache_dir}/hsi_zones.json"
    # Bathymetry is the map's spatial safety boundary. Build it first so a
    # CPU-heavy optional HSI cache cannot delay publication of the water-mask
    # corrected artifact after deployment.
    await asyncio.to_thread(
        ensure_bathymetry_artifact,
        settings.cache_dir,
        settings.copernicus_bathymetry_path,
        settings.context_buffer_m,
    )
    # Regional ETOPO depth (Cat Ba / Ha Long / Bai Tu Long), where SDB has no pixels.
    await asyncio.to_thread(ensure_etopo_artifact, settings.cache_dir, settings.etopo_bathymetry_path)
    # GEBCO 2024 + TID confidence: the default depth layer. A failure must not stop the loop;
    # the API then reports building/unavailable for this layer.
    try:
        gebco_result = await asyncio.to_thread(ensure_gebco_artifact, settings.cache_dir, settings.gebco_bathymetry_path)
        if gebco_result.get("status") != "ready":
            logger.warning("GEBCO artifact not built: %s", gebco_result.get("reason_code"))
    except Exception:
        logger.exception("GEBCO artifact build failed; layer stays unavailable")
    if not __import__("pathlib").Path(hsi_cache_path).exists():
        # This is intentionally outside FastAPI request handling. It may take
        # several minutes on a cold cache because it builds water-path zones.
        asyncio.create_task(asyncio.to_thread(build_hsi_cache, hsi_cache_path))
    # A deployment can introduce a new artifact algorithm while the provider
    # returns an identical immutable snapshot. Backfill that latest snapshot
    # immediately instead of waiting for an external data change.
    latest = repository.latest()
    if latest is not None:
        existing = load_flow_artifact(settings.cache_dir, latest["snapshot_id"])
        if existing is None or existing.get("algorithm_version") != FLOW_ARTIFACT_VERSION:
            network = await asyncio.to_thread(ensure_station_network_cache, settings.cache_dir, settings.context_buffer_m)
            await asyncio.to_thread(build_flow_artifact, latest, network, settings.cache_dir)
    loop = asyncio.get_running_loop()
    
    async def context_loop():
        while True:
            t0 = loop.time()
            started = datetime.now(timezone.utc)
            await run_once(repository)
            elapsed = loop.time() - t0
            # Sleep until the next scheduled snapshot, waking early when the map asks for a refresh.
            deadline = loop.time() + max(10, settings.snapshot_minutes * 60 - elapsed)
            while loop.time() < deadline and not refresh.due(settings.cache_dir, started):
                await asyncio.sleep(min(REFRESH_CHECK_SECONDS, max(0.0, deadline - loop.time())))

    async def sensor_loop():
        last_backfill: datetime | None = None
        while True:
            t0 = loop.time()
            now = datetime.now(timezone.utc)
            if last_backfill is None or (now - last_backfill).total_seconds() >= SENSOR_BACKFILL_MINUTES * 60 or refresh.due(settings.cache_dir, last_backfill):
                last_backfill = now
                await backfill_sensor_history(repository)
            await ingest_sensor_once(repository)
            await asyncio.to_thread(build_aquaculture_artifacts, repository, settings.cache_dir, settings.greenlab_station_serials, settings.latitude, settings.longitude, settings.nh4_unit_scale, settings.sensor_stale_minutes, settings.nh3_max_metric_gap_minutes)
            elapsed = loop.time() - t0
            await asyncio.sleep(max(5, settings.sensor_poll_seconds - elapsed))

    await asyncio.gather(context_loop(), sensor_loop())


if __name__ == "__main__":
    asyncio.run(serve())
