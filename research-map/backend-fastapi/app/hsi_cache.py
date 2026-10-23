"""Build/read the expensive historical HSI geometry outside API requests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_hsi_cache(path: str | Path) -> dict[str, Any]:
    from core.spatial_overlay import build_observed_hsi_partition_demo_overlays

    observed_at, overlays = build_observed_hsi_partition_demo_overlays(max_radius_km=5.0)
    payload = {
        "observed_at": observed_at,
        "mode": "historical_hsi_reference_only",
        "status": "ready",
        "used_by_alerts": False,
        "features": [
            {"type": "Feature", "geometry": item["geometry"], "properties": {key: value for key, value in item.items() if key != "geometry"}}
            for item in overlays
        ],
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    temporary.replace(target)
    return payload


def load_hsi_cache(path: str | Path) -> dict[str, Any] | None:
    target = Path(path)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
