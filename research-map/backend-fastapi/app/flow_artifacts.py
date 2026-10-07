"""Immutable, snapshot-bound render artifacts for the map flow overlay."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from app.network import add_current_influence, build_flow_rays


FLOW_ARTIFACT_VERSION = "flow-render-v3"


def _path(cache_dir: str, snapshot_id: str) -> Path:
    return Path(cache_dir) / "flow-artifacts" / f"{snapshot_id}.json"


def load_flow_artifact(cache_dir: str, snapshot_id: str) -> dict[str, Any] | None:
    try:
        return json.loads(_path(cache_dir, snapshot_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def build_flow_artifact(snapshot: dict[str, Any], network: dict[str, Any], cache_dir: str) -> dict[str, Any]:
    """Calculate once in the worker; requests only read the resulting file.

    The station topology remains a separate static layer.  This artifact can
    contain visual streamlines and only *supported* station relationships for
    one immutable environmental snapshot.
    """
    target = _path(cache_dir, snapshot["snapshot_id"])
    existing = load_flow_artifact(cache_dir, snapshot["snapshot_id"])
    if existing and existing.get("algorithm_version") == FLOW_ARTIFACT_VERSION:
        return existing

    current = next((item for item in snapshot.get("layers", []) if item.get("layer") == "current"), None)
    influenced = add_current_influence(network, current, include_streamlines=False)
    # 650 m is visually dense at the map's default view while bounding the
    # one-off worker cost over the island-rich Hai Phong water geometry.
    rays = build_flow_rays(current, spacing_m=650)
    features: list[dict[str, Any]] = []
    for ray in rays:
        properties = dict(ray.get("properties", {}))
        properties.update({"snapshot_id": snapshot["snapshot_id"], "render_lod": "dense_water_grid"})
        features.append({**ray, "properties": properties})
    for feature in influenced.get("features", []):
        properties = dict(feature.get("properties", {}))
        kind = properties.get("kind")
        if kind == "flow_streamline":
            properties.update({"snapshot_id": snapshot["snapshot_id"], "render_lod": "demo"})
            features.append({**feature, "properties": properties})
        elif kind == "water_path_station_edge" and float(properties.get("forward_alignment", -1)) >= 0.45 and float(properties.get("forward_projected_speed_m_s", 0)) >= 0.05:
            # This is a compatibility diagnostic, not a re-routed transport
            # simulation.  Do not expose the previous pseudo travel-time.
            properties.update({
                "kind": "current_supported_station_edge",
                "relationship": "current_compatibility_exploratory",
                "snapshot_id": snapshot["snapshot_id"],
                "confidence": "low_source_grid_resolution",
            })
            properties.pop("forward_travel_hours", None)
            features.append({**feature, "properties": properties})

    current_status = current.get("status", "unavailable") if current else "unavailable"
    current_provenance = current.get("provenance", {}) if current else {}
    key = {
        "snapshot_id": snapshot["snapshot_id"], "payload_hash": snapshot["payload_hash"],
        "geometry_hash": snapshot.get("geometry_hash"), "algorithm_version": FLOW_ARTIFACT_VERSION,
    }
    artifact = {
        "artifact_id": hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest(),
        "algorithm_version": FLOW_ARTIFACT_VERSION,
        "snapshot_id": snapshot["snapshot_id"], "payload_hash": snapshot["payload_hash"],
        "geometry_hash": snapshot.get("geometry_hash"), "retrieved_at": snapshot["retrieved_at"].isoformat(),
        "valid_at": snapshot.get("valid_at"), "status": current_status,
        "provenance": current_provenance, "mode": "exploratory_precomputed",
        "type": "FeatureCollection", "features": features,
        "streamline_count": sum(1 for item in features if item["properties"].get("kind") == "flow_streamline"),
        "ray_count": sum(1 for item in features if item["properties"].get("kind") == "flow_ray"),
        "current_supported_station_edge_count": sum(1 for item in features if item["properties"].get("kind") == "current_supported_station_edge"),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(artifact, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
    os.replace(temporary, target)
    return artifact
