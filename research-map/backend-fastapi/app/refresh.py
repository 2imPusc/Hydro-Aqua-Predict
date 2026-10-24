"""Refresh requests from the map (page open / "Đồng bộ" button) to the snapshot worker.

The API never fetches providers itself: the worker is the only writer and the only container with the
Copernicus credentials. The API drops a small request file in the shared cache volume; the worker loop checks
it every few seconds and runs a snapshot early. Requests within MIN_INTERVAL_MINUTES of the last snapshot
are answered "fresh" so opening many tabs cannot hammer Open-Meteo (free-tier quota, RL-49).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MIN_INTERVAL_MINUTES = 10
REQUEST_NAME = "refresh-request.json"


def _path(cache_dir: str) -> Path:
    return Path(cache_dir) / REQUEST_NAME


def read_request(cache_dir: str) -> datetime | None:
    try:
        value = json.loads(_path(cache_dir).read_text(encoding="utf-8")).get("requested_at")
        return datetime.fromisoformat(value) if value else None
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return None


def request_refresh(cache_dir: str, latest_retrieved_at: datetime | None, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    age_min = (now - latest_retrieved_at).total_seconds() / 60 if latest_retrieved_at else None
    if age_min is not None and age_min < MIN_INTERVAL_MINUTES:
        return {"status": "fresh", "snapshot_age_minutes": round(age_min, 1), "min_interval_minutes": MIN_INTERVAL_MINUTES}
    pending = read_request(cache_dir)
    if pending and (latest_retrieved_at is None or pending > latest_retrieved_at):
        return {"status": "pending", "requested_at": pending.isoformat(), "snapshot_age_minutes": None if age_min is None else round(age_min, 1)}
    folder = Path(cache_dir)
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=folder, suffix=".tmp", delete=False, encoding="utf-8") as handle:
        json.dump({"requested_at": now.isoformat()}, handle)
        temporary = handle.name
    os.replace(temporary, _path(cache_dir))
    return {"status": "requested", "requested_at": now.isoformat(), "snapshot_age_minutes": None if age_min is None else round(age_min, 1)}


def due(cache_dir: str, last_run_started: datetime | None) -> bool:
    """True when a request arrived after the worker's last snapshot run started."""
    requested = read_request(cache_dir)
    return requested is not None and (last_run_started is None or requested > last_run_started)
