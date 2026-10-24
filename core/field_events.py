"""Field event log ("Nhật ký sự kiện"): ground-truth reports from the cages.

Feeds H2.4 (alert-threshold calibration) and H2.5. Storage rules mirror the alert-config
write path (decisions #20):

* one JSON file per event in ``paths.EVENTS_DIR``, created exclusively (``"x"`` mode);
* never modified or deleted — a correction is a NEW event with ``supersedes: <id>``;
* an event can be superseded once: ``<id>.superseded.claim`` is created exclusively before
  the correction is written, so two concurrent corrections of the same event cannot both
  land. Claim files are the only non-event files in the directory; readers ignore them.

Stdlib + ``core.paths`` only, so the research-map API and the experiments read the same
records. Validation returns a list of messages (empty = valid), like ``core.alert_config``.
"""
from __future__ import annotations

import json
import logging
import math
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import paths

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
VN_TZ = timezone(timedelta(hours=7))
OTHER_STATION = "khac"
MIN_EVENTS_FOR_CALIBRATION = 10

EVENT_TYPES: dict[str, str] = {
    "ca_chet": "Cá chết",
    "ca_bo_an": "Cá bỏ ăn",
    "ca_lo_do_noi_dau": "Cá bơi lờ đờ / nổi đầu",
    "nuoc_duc_doi_mau": "Nước đục / đổi màu",
    "tao_no_hoa": "Tảo nở hoa",
    "mua_lon": "Mưa lớn",
    "gio_manh_bao": "Gió mạnh / bão",
    "hu_hong_long": "Hư hỏng lồng",
    "do_tay": "Đo tay (DO / độ mặn / nhiệt độ)",
    "khac": "Khác",
}
SOURCES: dict[str, str] = {"nguoi_nuoi": "Người nuôi", "can_bo": "Cán bộ", "nghien_cuu": "Nghiên cứu"}
SEVERITY_LABELS: dict[int, str] = {1: "Nhẹ", 2: "Vừa", 3: "Nặng"}
# Plausible ranges for hand measurements in coastal cages (not QC thresholds): outside = typo.
MEASUREMENTS: dict[str, dict] = {
    "do_mg_l": {"label": "DO", "unit": "mg/L", "min": 0.0, "max": 20.0},
    "salinity_psu": {"label": "Độ mặn", "unit": "psu", "min": 0.0, "max": 45.0},
    "water_temp_c": {"label": "Nhiệt độ nước", "unit": "°C", "min": 5.0, "max": 40.0},
    "secchi_m": {"label": "Độ trong Secchi", "unit": "m", "min": 0.0, "max": 30.0},
}

NOTE_MAX = 1000
SHORT_TEXT_MAX = 120
FUTURE_TOLERANCE = timedelta(minutes=15)
OLDEST_OBSERVED = datetime(2025, 1, 1, tzinfo=VN_TZ)

ID_RE = re.compile(r"^\d{8}T\d{9}Z-[0-9a-f]{6}$")
_ALLOWED_KEYS = {"observed_at", "station_id", "station_other", "event_type", "severity", "measurements",
                 "note", "reporter", "source", "supersedes"}


class EventValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class SupersedeConflict(Exception):
    """The target is unknown, or already has a correction (corrections must point at the current head)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def events_dir() -> Path:
    return Path(paths.EVENTS_DIR)  # read at call time so tests can redirect it


def parse_observed_at(value: object) -> datetime | None:
    """Naive strings are Vietnam local time; aware ones are converted to +07:00."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=VN_TZ)
    return parsed.astimezone(VN_TZ).replace(microsecond=0)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _text(body: dict, key: str, limit: int, errors: list[str], *, required: bool = False) -> str | None:
    value = body.get(key)
    if value is None:
        if required:
            errors.append(f"{key}: required")
        return None
    if not isinstance(value, str):
        errors.append(f"{key}: must be text")
        return None
    value = value.strip()
    if len(value) > limit:
        errors.append(f"{key}: at most {limit} characters")
    if required and not value:
        errors.append(f"{key}: required")
    return value or None


def validate(body: object, known_stations: set[str] | None, *, now: datetime | None = None) -> tuple[dict, list[str]]:
    """Return (normalised fields, errors). ``known_stations=None`` means the registry is unavailable."""
    if not isinstance(body, dict):
        return {}, ["body: must be an object"]
    errors = [f"{key}: unknown field" for key in sorted(set(body) - _ALLOWED_KEYS)]
    out: dict = {}

    observed = parse_observed_at(body.get("observed_at"))
    if observed is None:
        errors.append("observed_at: required, ISO local time (YYYY-MM-DDTHH:MM)")
    else:
        current = (now or datetime.now(timezone.utc)).astimezone(VN_TZ)
        if observed > current + FUTURE_TOLERANCE:
            errors.append("observed_at: in the future")
        elif observed < OLDEST_OBSERVED:
            errors.append(f"observed_at: before {OLDEST_OBSERVED.date().isoformat()}")
        out["observed_at"] = observed.isoformat()

    station = body.get("station_id")
    station_other = _text(body, "station_other", SHORT_TEXT_MAX, errors)
    if not isinstance(station, str) or not station.strip():
        errors.append("station_id: required")
    elif station == OTHER_STATION:
        if not station_other:
            errors.append("station_other: required when station_id is 'khac'")
        out["station_id"], out["station_other"] = OTHER_STATION, station_other
    elif known_stations is None:
        errors.append("station_id: station registry unavailable")
    elif station not in known_stations:
        errors.append(f"station_id: unknown station '{station[:40]}'")
    else:
        if station_other:
            errors.append("station_other: only with station_id 'khac'")
        out["station_id"], out["station_other"] = station, None

    event_type = body.get("event_type")
    if event_type not in EVENT_TYPES:
        errors.append(f"event_type: one of {', '.join(EVENT_TYPES)}")
    else:
        out["event_type"] = event_type

    severity = body.get("severity")
    if not isinstance(severity, int) or isinstance(severity, bool) or severity not in SEVERITY_LABELS:
        errors.append("severity: integer 1, 2 or 3")
    else:
        out["severity"] = severity

    raw_meas = body.get("measurements")
    measurements: dict[str, float] = {}
    if raw_meas is not None and not isinstance(raw_meas, dict):
        errors.append("measurements: must be an object")
    elif raw_meas:
        for key, value in raw_meas.items():
            spec = MEASUREMENTS.get(key)
            if spec is None:
                errors.append(f"measurements.{str(key)[:40]}: unknown measurement")
            elif value is None:
                continue
            elif not _is_number(value):
                errors.append(f"measurements.{key}: must be a number")
            elif not spec["min"] <= value <= spec["max"]:
                errors.append(f"measurements.{key}: outside plausible range {spec['min']:g}–{spec['max']:g} {spec['unit']}")
            else:
                measurements[key] = float(value)
    out["measurements"] = measurements
    if event_type == "do_tay" and not measurements and not any(e.startswith("measurements") for e in errors):
        errors.append("measurements: at least one value required for 'do_tay'")

    out["note"] = _text(body, "note", NOTE_MAX, errors)
    if event_type == "khac" and not out["note"]:
        errors.append("note: required for event_type 'khac'")
    out["reporter"] = _text(body, "reporter", SHORT_TEXT_MAX, errors)

    source = body.get("source")
    if source not in SOURCES:
        errors.append(f"source: one of {', '.join(SOURCES)}")
    else:
        out["source"] = source

    supersedes = body.get("supersedes")
    if supersedes is not None and (not isinstance(supersedes, str) or not ID_RE.match(supersedes)):
        errors.append("supersedes: not a valid event id")
    else:
        out["supersedes"] = supersedes
    return out, errors


def _new_id(now: datetime) -> str:
    return f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z-{secrets.token_hex(3)}"


def _read(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, ValueError) as exc:
        logger.warning("field event %s unreadable: %s", path.name, exc)
        return None
    if not isinstance(record, dict) or record.get("event_id") != path.stem:
        logger.warning("field event %s ignored: id does not match file name", path.name)
        return None
    return record


def load_all() -> list[dict]:
    """Every stored event (superseded included), each with a derived ``superseded_by``."""
    d = events_dir()
    if not d.is_dir():
        return []
    records = [r for p in sorted(d.glob("*.json")) if ID_RE.match(p.stem) and (r := _read(p)) is not None]
    superseded_by: dict[str, str] = {}
    for record in sorted(records, key=lambda r: r["event_id"]):
        target = record.get("supersedes")
        if target:
            superseded_by.setdefault(target, record["event_id"])  # the claim file allows only one
    return [{**r, "superseded_by": superseded_by.get(r["event_id"])} for r in records]


def create(fields: dict, *, now: datetime | None = None) -> dict:
    """Write one new event file (exclusive create) and return the stored record.

    Raises ``SupersedeConflict`` when ``supersedes`` names an unknown or already-corrected event,
    and ``OSError`` when the directory is not writable.
    """
    d = events_dir()
    target = fields.get("supersedes")
    if target:
        if not (d / f"{target}.json").is_file():
            raise SupersedeConflict("supersedes_not_found")
        if any(r.get("supersedes") == target for r in load_all()):
            raise SupersedeConflict("already_superseded")
    d.mkdir(parents=True, exist_ok=True)
    if target:
        try:
            with open(d / f"{target}.superseded.claim", "x", encoding="utf-8"):
                pass
        except FileExistsError:
            raise SupersedeConflict("already_superseded") from None
    try:
        return _write_new(d, fields, now)
    except OSError:
        if target:  # release our own lock so the correction can be retried; no event file was written
            (d / f"{target}.superseded.claim").unlink(missing_ok=True)
        raise


def _write_new(d: Path, fields: dict, now: datetime | None) -> dict:
    while True:
        stamp = now or datetime.now(timezone.utc)
        record = {
            "event_id": _new_id(stamp),
            "schema_version": SCHEMA_VERSION,
            "created_at": stamp.astimezone(timezone.utc).isoformat(timespec="seconds"),
            **{k: fields.get(k) for k in sorted(_ALLOWED_KEYS)},
        }
        try:
            with open(d / f"{record['event_id']}.json", "x", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False, indent=2)
                fh.flush()
        except FileExistsError:
            now = None  # same millisecond and same random suffix: draw again
            continue
        return record


def active(records: list[dict]) -> list[dict]:
    return [r for r in records if not r.get("superseded_by")]
