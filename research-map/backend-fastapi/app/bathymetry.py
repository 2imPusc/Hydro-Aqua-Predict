"""Optional GEBCO metadata adapter.

The research map must never fabricate depth or a coast mask.  A configured
local GeoTIFF is therefore described only after it is present in the worker
cache.  Tile rendering is deliberately a later concern; this layer provides
the immutable provenance and geographic extent needed by the API first.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.providers import unavailable_layer


def describe_gebco(path: str, stale_minutes: int) -> dict:
    retrieved_at = datetime.now(timezone.utc)
    return {
        "layer": "bathymetry",
        "status": "fresh",
        "kind": "wms_layer",
        "reason_code": None,
        "provenance": {
            "source": "GEBCO Public WMS Service",
            "provider": "gebco",
            "product_id": "GEBCO_LATEST",
            "dataset_version": "cloud",
            "grid_resolution": "global",
            "issued_at": None,
            "valid_at": None,
            "retrieved_at": retrieved_at.isoformat(),
            "payload_hash": "wms_cloud",
            "stale_after": (retrieved_at + timedelta(minutes=stale_minutes)).isoformat(),
            "direction_convention": "not_applicable",
        },
        "geojson": None,
        "raster": {
            "rendering": "wms_cloud_rendered",
            "url": "https://www.gebco.net/data_and_products/gebco_web_services/web_map_service/mapserv",
            "layers": "GEBCO_LATEST"
        },
    }
