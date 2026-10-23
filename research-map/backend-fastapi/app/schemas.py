from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ContextStatus = Literal["fresh", "stale", "unavailable"]


class Provenance(BaseModel):
    source: str
    provider: str
    product_id: str | None = None
    dataset_version: str | None = None
    grid_resolution: str
    display_grid_resolution: str | None = None
    source_grid_resolution: str | None = None
    temporal_mode: str | None = None
    issued_at: datetime | None = None
    valid_at: datetime | None = None
    retrieved_at: datetime
    payload_hash: str
    stale_after: datetime
    direction_convention: str | None = None


class LayerPayload(BaseModel):
    layer: Literal["wind", "rain", "wave", "current", "sea_level", "mixed_layer_depth", "bathymetry", "advisory_forecast"]
    status: ContextStatus
    kind: Literal["regional_point", "regional_grid", "vector_grid", "scalar_grid", "raster", "wms_layer", "point_cloud", "unavailable"]
    reason_code: str | None = None
    provenance: Provenance | None = None
    geojson: dict[str, Any] | None = None
    raster: dict[str, Any] | None = None
    data: Any | None = None


class ContextSnapshot(BaseModel):
    snapshot_id: str
    status: ContextStatus
    issued_at: datetime | None = None
    valid_at: datetime | None = None
    retrieved_at: datetime
    age_seconds: int
    bbox: list[float] = Field(description="[min_lon, min_lat, max_lon, max_lat]")
    domain_id: str | None = None
    geometry_hash: str | None = None
    layers: list[LayerPayload]


class SensorObservationIn(BaseModel):
    observation_id: str
    station_serial: str
    metric: str
    value: float
    unit: str
    observed_at: datetime
    source_type: str = "greenlab_api"
    qc_status: str = "UNCHECKED"
    qc_reason: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class SensorObservation(SensorObservationIn):
    ingested_at: datetime


class SensorLatest(BaseModel):
    station_serial: str
    status: Literal["fresh", "stale", "unavailable"]
    latest_observed_at: datetime | None = None
    age_seconds: int | None = None
    observations: list[SensorObservation]
    reason_code: str | None = None
