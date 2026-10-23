"""Per-station hazard alerts (Track G) and active storms (Track D), read-only.

Contract: docs/superpowers/plans/2026-10-23-phase1-parallel.md (C2, C3).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

from .settings import settings

router = APIRouter(prefix="/api/v1/research", tags=["hazards"])

# --- /storms/active (Track D) -------------------------------------------------------------------
# Written by experiments/ecmwf_opendata.py (one exclusive-create JSON per ECMWF ENS run); read here only.
STORMS_FILE = re.compile(r"^storms_active_(\d{10})\.json$")
STORMS_STALE_AFTER_H = 36.0  # ENS track runs every 6-12 h; older than 36 h = at least two runs missed


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hazard_shadow_dir() -> Path:
    return Path(settings.hap_runtime_dir) / "hazard-shadow"


@router.get("/hazards/stations")
def station_hazards() -> dict:
    return {"status": "unavailable", "reason": "not_implemented"}


@router.get("/storms/active")
def active_storms() -> dict:
    folder = _hazard_shadow_dir()
    files = sorted((p for p in folder.glob("storms_active_*.json") if STORMS_FILE.match(p.name)),
                   key=lambda p: p.name, reverse=True) if folder.is_dir() else []
    if not files:
        return {"status": "unavailable", "reason": "no_storm_track_summary", "source": "ecmwf_opendata", "storms": [],
                "used_by_alerts": False}
    for path in files:
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(body, dict) or not isinstance(body.get("storms"), list):
            continue
        run = datetime.strptime(STORMS_FILE.match(path.name).group(1), "%Y%m%d%H").replace(tzinfo=timezone.utc)
        age_h = (_now() - run).total_seconds() / 3600.0
        stale = age_h > STORMS_STALE_AFTER_H
        out = {**body, "status": "ready", "file": path.name, "run_age_hours": round(age_h, 1),
               "data_status": "stale" if stale else "fresh", "used_by_alerts": False, "notification_eligible": False}
        if stale:
            out["reason"] = "stale_run"
        return out
    return {"status": "unavailable", "reason": "unreadable_storm_track_summary", "source": "ecmwf_opendata",
            "storms": [], "used_by_alerts": False}
