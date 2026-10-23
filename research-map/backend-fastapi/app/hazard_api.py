"""Per-station hazard alerts (Track G) and active storms (Track D), read-only.

Contract: docs/superpowers/plans/2026-10-23-phase1-parallel.md (C2, C3).
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/research", tags=["hazards"])


@router.get("/hazards/stations")
def station_hazards() -> dict:
    return {"status": "unavailable", "reason": "not_implemented"}


@router.get("/storms/active")
def active_storms() -> dict:
    return {"status": "unavailable", "reason": "not_implemented"}
