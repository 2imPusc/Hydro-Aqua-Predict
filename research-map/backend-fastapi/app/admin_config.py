"""Alert-tier configuration admin API (contract C3, decisions #20). No auth yet.

Import choice: logic lives in ``core.alert_config`` (stdlib + ``core.paths`` only) and is imported
here, the same way ``app.domain`` / ``app.hsi_cache`` reach ``core``: Docker puts ``/workspace``
on PYTHONPATH, local dev falls back to the repo root found below. This keeps one validator for
the runner and the API. Docker needs ``config/`` readable and ``runtime/alert-config/`` writable
(``HAP_RUNTIME_DIR``). The only write is a new version file in ``paths.ALERT_CONFIG_DIR``.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

try:
    from core import alert_config as ac
except ImportError:  # local dev run without PYTHONPATH pointing at the repo root
    _root = next((p for p in Path(__file__).resolve().parents if (p / "core" / "alert_config.py").is_file()), None)
    if _root is None:
        raise
    sys.path.insert(0, str(_root))
    from core import alert_config as ac

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class SaveBody(BaseModel):
    config: dict
    reason_vi: str
    changed_by: str | None = None


class PreviewBody(BaseModel):
    config: dict


def tier_examples(config: dict) -> list[dict]:
    out = []
    for hid, h in config["hazards"].items():
        for k in sorted(h["thresholds"], key=int):
            t = float(h["thresholds"][k])
            eps = max(abs(t) * 0.01, 1e-3)
            for v in (t - eps, t, t + eps):
                out.append({"hazard": hid, "value": round(v, 6), "tier": ac.tier_for(hid, v, config)})
    return out


@router.get("/alert-config")
def get_alert_config() -> dict:
    eff = ac.load_effective()
    return {"status": "ready", "effective": eff, "config_version": eff.get("config_version"),
            "source": ac.effective_source()}


@router.get("/alert-config/versions")
def list_alert_config_versions() -> dict:
    return {"status": "ready", "versions": ac.list_versions()}


@router.get("/alert-config/versions/{version}")
def get_alert_config_version(version: str) -> dict:
    try:
        return {"status": "ready", "version": ac.get_version(version)}
    except KeyError:
        raise HTTPException(status_code=404, detail="version not found") from None


@router.post("/alert-config", status_code=201)
def save_alert_config(body: SaveBody):
    errors = ac.validate(body.config) + ac.structural_errors(body.config)
    if not body.reason_vi.strip():
        errors = errors + ["reason_vi: required"]
    if errors:
        return JSONResponse(status_code=422, content={"status": "invalid", "errors": errors})
    try:
        version = ac.save_version(body.config, changed_by=body.changed_by or "admin-ui", reason_vi=body.reason_vi)
    except ac.ConfigValidationError as exc:
        return JSONResponse(status_code=422, content={"status": "invalid", "errors": exc.errors})
    return {"status": "ready", "config_version": version}


@router.post("/alert-config/preview")
def preview_alert_config(body: PreviewBody) -> dict:
    errors = ac.validate(body.config) + ac.structural_errors(body.config)
    return {"status": "ready", "errors": errors, "tier_examples": [] if errors else tier_examples(body.config)}
