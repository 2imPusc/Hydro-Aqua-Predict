"""Alert-tier configuration admin API (contract C3, decisions #20). No auth yet.

Import choice: logic lives in ``core.alert_config`` (stdlib + ``core.paths`` only) and is imported
here, the same way ``app.domain`` / ``app.hsi_cache`` reach ``core``: Docker puts ``/workspace``
on PYTHONPATH, local dev falls back to the repo root found below. This keeps one validator for
the runner and the API. Docker needs ``config/`` readable and ``runtime/alert-config/`` writable
(``HAP_RUNTIME_DIR``). The only write is a new version file in ``paths.ALERT_CONFIG_DIR``.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

try:
    from core import alert_config as ac
except ImportError:  # local dev run without PYTHONPATH pointing at the repo root
    _root = next((p for p in Path(__file__).resolve().parents if (p / "core" / "alert_config.py").is_file()), None)
    if _root is None:
        raise
    sys.path.insert(0, str(_root))
    from core import alert_config as ac

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
logger = logging.getLogger(__name__)

# The default config is ~5 KB; a version stays far below this. Caps the size of a written version file.
MAX_BODY_BYTES = 256 * 1024


def _limit_body(request: Request) -> None:
    """413 when the declared body is larger than MAX_BODY_BYTES (re-checked after parsing for chunked bodies)."""
    try:
        size = int(request.headers.get("content-length") or 0)
    except ValueError:
        size = 0
    if size > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail={"reason_code": "body_too_large", "max_bytes": MAX_BODY_BYTES})


def _check_config_size(config: dict) -> None:
    if len(json.dumps(config, ensure_ascii=False).encode("utf-8")) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail={"reason_code": "body_too_large", "max_bytes": MAX_BODY_BYTES})


class SaveBody(BaseModel):
    config: dict
    reason_vi: str = Field(max_length=1000)
    changed_by: str | None = Field(default=None, max_length=120)


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


@router.post("/alert-config", status_code=201, dependencies=[Depends(_limit_body)])
def save_alert_config(body: SaveBody):
    _check_config_size(body.config)
    errors = ac.validate(body.config) + ac.structural_errors(body.config)
    if not body.reason_vi.strip():
        errors = errors + ["reason_vi: required"]
    if errors:
        return JSONResponse(status_code=422, content={"status": "invalid", "errors": errors})
    try:
        version = ac.save_version(body.config, changed_by=body.changed_by or "admin-ui", reason_vi=body.reason_vi)
    except ac.ConfigValidationError as exc:
        return JSONResponse(status_code=422, content={"status": "invalid", "errors": exc.errors})
    except OSError as exc:  # e.g. runtime/alert-config not mounted writable in Docker (decisions #20)
        logger.error("alert-config version not written: %s", exc)
        return JSONResponse(status_code=503, content={"status": "unavailable", "reason": "config_dir_not_writable"})
    return {"status": "ready", "config_version": version}


@router.post("/alert-config/preview", dependencies=[Depends(_limit_body)])
def preview_alert_config(body: PreviewBody) -> dict:
    _check_config_size(body.config)
    errors = ac.validate(body.config) + ac.structural_errors(body.config)
    return {"status": "ready", "errors": errors, "tier_examples": [] if errors else tier_examples(body.config)}
