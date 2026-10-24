"""Field event log API ("Nhật ký sự kiện"): ground truth for H2.4 threshold calibration. No auth yet.

Second API write path after the alert config (decisions #20 pattern): each POST creates one new
JSON file in ``paths.EVENTS_DIR`` (exclusive create); nothing is modified or deleted. A correction
is a new event with ``supersedes``. Logic and validation live in ``core.field_events`` so the
experiments read the same records. Docker needs ``runtime/events/`` mounted writable.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import sys
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

try:
    from core import field_events as fe
except ImportError:  # local dev run without PYTHONPATH pointing at the repo root
    _root = next((p for p in Path(__file__).resolve().parents if (p / "core" / "field_events.py").is_file()), None)
    if _root is None:
        raise
    sys.path.insert(0, str(_root))
    from core import field_events as fe

from app.domain import station_records

router = APIRouter(prefix="/api/v1/events", tags=["events"])
logger = logging.getLogger(__name__)

# One event is < 2 KB (note ≤ 1000 chars); this only stops abuse of the write path.
MAX_BODY_BYTES = 16 * 1024

CSV_COLUMNS = [
    "event_id", "observed_at", "station_id", "station_other", "event_type", "event_type_vi", "severity",
    *fe.MEASUREMENTS, "note", "reporter", "source", "source_vi", "supersedes", "superseded", "superseded_by",
    "created_at", "schema_version",
]
_FREE_TEXT = {"station_other", "note", "reporter"}


def _known_stations() -> set[str] | None:
    try:
        return {item["station"] for item in station_records()}
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("station registry unavailable for events: %s", exc)
        return None


def _reject_constant(token: str) -> None:
    raise ValueError(f"{token} is not JSON")  # NaN / Infinity: reject instead of storing a non-finite number


async def _read_body(request: Request) -> object:
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail={"reason_code": "body_too_large", "max_bytes": MAX_BODY_BYTES})
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:  # chunked bodies have no content-length
        raise HTTPException(status_code=413, detail={"reason_code": "body_too_large", "max_bytes": MAX_BODY_BYTES})
    try:
        return json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError):
        return None


def _filtered(records: list[dict], station: str | None, event_type: str | None,
              date_from: date | None, date_to: date | None) -> list[dict]:
    out = []
    for r in records:
        day = str(r.get("observed_at", ""))[:10]
        if station and r.get("station_id") != station:
            continue
        if event_type and r.get("event_type") != event_type:
            continue
        if date_from and day < date_from.isoformat():
            continue
        if date_to and day > date_to.isoformat():
            continue
        out.append(r)
    return sorted(out, key=lambda r: (str(r.get("observed_at", "")), r["event_id"]), reverse=True)


def _load() -> list[dict]:
    try:
        return fe.load_all()
    except OSError as exc:
        logger.error("events dir not readable: %s", exc)
        raise HTTPException(status_code=503, detail={"status": "unavailable", "reason": "events_dir_not_readable"}) from None


@router.post("", status_code=201)
async def create_event(request: Request):
    body = await _read_body(request)
    if body is None:
        return JSONResponse(status_code=422, content={"status": "invalid", "errors": ["body: not valid JSON"]})
    station = body.get("station_id") if isinstance(body, dict) else None
    known = _known_stations() if station != fe.OTHER_STATION else set()
    fields, errors = fe.validate(body, known)
    if known is None and isinstance(station, str) and station:
        return JSONResponse(status_code=503, content={"status": "unavailable", "reason": "station_registry_unavailable"})
    if errors:
        return JSONResponse(status_code=422, content={"status": "invalid", "errors": errors})
    try:
        record = fe.create(fields)
    except fe.SupersedeConflict as exc:
        status = 404 if exc.reason == "supersedes_not_found" else 409
        return JSONResponse(status_code=status, content={"status": "conflict", "reason": exc.reason})
    except OSError as exc:  # e.g. runtime/events not mounted writable in Docker
        logger.error("field event not written: %s", exc)
        return JSONResponse(status_code=503, content={"status": "unavailable", "reason": "events_dir_not_writable"})
    return {"status": "ready", "event": {**record, "superseded_by": None}}


@router.get("")
def list_events(
    station: str | None = Query(default=None, max_length=120),
    event_type: str | None = Query(default=None, max_length=40),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    include_superseded: bool = False,
) -> dict:
    records = _load()
    current = fe.active(records)
    shown = _filtered(records if include_superseded else current, station, event_type, date_from, date_to)
    return {
        "status": "ready",
        "events": shown,
        "count": len(shown),
        "total_active": len(current),
        "total_superseded": len(records) - len(current),
        "min_events_for_calibration": fe.MIN_EVENTS_FOR_CALIBRATION,
        "event_types": fe.EVENT_TYPES,
        "sources": fe.SOURCES,
        "measurements": fe.MEASUREMENTS,
    }


def _cell(key: str, value: object) -> object:
    if value is None:
        return ""
    if key in _FREE_TEXT and isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value  # spreadsheet formula injection guard
    return value


@router.get("/export.csv")
def export_events_csv(
    station: str | None = Query(default=None, max_length=120),
    event_type: str | None = Query(default=None, max_length=40),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> Response:
    """Every event including superseded ones (flagged), newest first. UTF-8 with BOM for Excel."""
    rows = _filtered(_load(), station, event_type, date_from, date_to)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    for r in rows:
        meas = r.get("measurements") or {}
        row = {
            **{k: r.get(k) for k in CSV_COLUMNS if k in r},
            **{k: meas.get(k) for k in fe.MEASUREMENTS},
            "event_type_vi": fe.EVENT_TYPES.get(r.get("event_type"), ""),
            "source_vi": fe.SOURCES.get(r.get("source"), ""),
            "superseded": "true" if r.get("superseded_by") else "false",
        }
        writer.writerow({k: _cell(k, row.get(k)) for k in CSV_COLUMNS})
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="nhat-ky-su-kien.csv"', "Cache-Control": "no-store"},
    )
