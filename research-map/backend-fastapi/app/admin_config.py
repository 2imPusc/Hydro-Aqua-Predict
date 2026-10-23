"""Alert-tier configuration admin API (Track A fills this in).

Contract: docs/superpowers/plans/2026-10-23-phase1-parallel.md (C1, C3). The only place the API
may write is runtime/alert-config/, as new version files (decisions #20). No auth yet.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/alert-config")
def get_alert_config() -> dict:
    return {"status": "unavailable", "reason": "not_implemented"}
