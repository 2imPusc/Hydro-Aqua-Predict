"""Read-only research endpoints (``/api/v1/research``).

Three sources, none of them ever written by the API:

* versioned research exports ``artifacts/research-map/<YYYYMMDD-HHMM>/`` written by
  ``scripts/export_research_map_artifacts.py`` (newest stamped dir wins, parsed JSON
  cached by mtime);
* the live long-horizon shadow ledger ``runtime/forecast-shadow/long_*.jsonl``
  (only the file tail is read);
* the hourly weather snapshot JSONL (observation-only; never an alert input).

Every response carries ``status`` (``ready`` | ``unavailable`` + ``reason``) and, for
export-backed endpoints, ``export_version``. Missing inputs give an explicit
unavailable state; nothing is filled in.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.settings import settings

router = APIRouter(prefix="/api/v1/research", tags=["research"])

STAMP_RE = re.compile(r"^\d{8}-\d{4}$")
DATASET_ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")
SUIT_VARIANTS = ("A_W_SUM", "N1_W_SUM")
SUIT_REGIONS = ("vn", "hk")
DEFAULT_STATION = "06M26042804"
LEDGER_WINDOW = timedelta(hours=48)
WEATHER_STALE_HOURS = 2.0
WEATHER_MIN_COVERAGE = 0.9
WEATHER_WINDOW = timedelta(days=7)
WEATHER_MAX_SCAN_BYTES = 256 * 1024 * 1024

_CACHE: dict[str, tuple[tuple, Any]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def clear_cache() -> None:
    _CACHE.clear()


def _json_safe(obj):
    if isinstance(obj, dict):
        return {key: _json_safe(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(value) for value in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def _file_key(path: Path) -> tuple:
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)


def _cached(name: str, path: Path, build):
    key = _file_key(path)
    hit = _CACHE.get(name)
    if hit and hit[0] == key:
        return hit[1]
    value = build()
    _CACHE[name] = (key, value)
    return value


def _load_json(path: Path) -> dict:
    return _cached(f"json:{path}", path, lambda: _json_safe(json.loads(path.read_text(encoding="utf-8"))))


# ---------------------------------------------------------------- versioned exports
def _latest_export() -> Path | None:
    root = Path(settings.research_export_dir)
    if not root.is_dir():
        return None
    dirs = [p for p in root.iterdir() if p.is_dir() and STAMP_RE.match(p.name) and (p / "manifest.json").is_file()]
    return max(dirs, key=lambda p: p.name) if dirs else None


def _unavailable(reason: str, export_version: str | None = None, **extra) -> dict:
    return {"status": "unavailable", "reason": reason, "export_version": export_version, **extra}


def _export_artifact(name: str) -> tuple[dict | None, dict | None]:
    """(payload, None) when the newest export has ``name``; else (None, unavailable response)."""
    export = _latest_export()
    if export is None:
        return None, _unavailable("research_export_missing")
    path = export / name
    if not path.is_file():
        omitted = _load_json(export / "manifest.json").get("omitted") or {}
        return None, _unavailable(omitted.get(name) or "artifact_not_in_export", export.name)
    payload = _load_json(path)
    return {**payload, "status": payload.get("status", "ready"), "export_version": export.name}, None


@router.get("/overview")
def overview() -> dict:
    payload, missing = _export_artifact("overview.json")
    return payload or missing


@router.get("/forecast/benchmark")
def forecast_benchmark() -> dict:
    payload, missing = _export_artifact("forecast_benchmark.json")
    return payload or missing


@router.get("/suitability")
def suitability(variant: str = "N1_W_SUM", region: str = "vn") -> dict:
    if variant not in SUIT_VARIANTS:
        raise HTTPException(status_code=422, detail={"reason_code": "invalid_variant", "allowed": list(SUIT_VARIANTS)})
    if region not in SUIT_REGIONS:
        raise HTTPException(status_code=422, detail={"reason_code": "invalid_region", "allowed": list(SUIT_REGIONS)})
    payload, missing = _export_artifact(f"suitability_{region}_{variant}.json")
    return payload or {**missing, "variant": variant, "region": region}


@router.get("/reliability/foreign")
def reliability_foreign_index() -> dict:
    payload, missing = _export_artifact("reliability_foreign_index.json")
    return payload or {**missing, "datasets": []}


def _pair_rows(detail: dict) -> list[dict]:
    table = detail.get("pairs") or {}
    if isinstance(table, list):  # tolerate an already expanded list
        return table
    columns = table.get("columns") or []
    return [dict(zip(columns, row)) for row in table.get("rows") or []]


def _expand_pairs(detail: dict, rows: list[dict], var: str | None, scale: str | None, transfer: str | None) -> list[dict]:
    """Filter pair rows and join station coordinates (lon1/lat1 = anchor, lon2/lat2 = target)."""
    coords = {}
    for feature in (detail.get("stations") or {}).get("features", []):
        lon, lat = ((feature.get("geometry") or {}).get("coordinates") or [None, None])[:2]
        coords[(feature.get("properties") or {}).get("station")] = (lon, lat)
    out = []
    for row in rows:
        if (var and row.get("var") != var) or (scale and row.get("scale") != scale) or (transfer and row.get("transfer") != transfer):
            continue
        a, t = coords.get(row.get("anchor"), (None, None)), coords.get(row.get("target"), (None, None))
        out.append({**row, "lon1": a[0], "lat1": a[1], "lon2": t[0], "lat2": t[1]})
    return out


def _pick(requested: str | None, options: list, preferred: str | None = None) -> str | None:
    if requested:
        return requested
    if preferred in options:
        return preferred
    return options[0] if options else None


@router.get("/reliability/foreign/{dataset_id}")
def reliability_foreign(dataset_id: str, var: str | None = None, scale: str | None = None,
                        transfer: str | None = None) -> dict:
    """Pairs filtered by var/scale/transfer (defaults: Temp, the pairs' native scale, raw); radius rows of ``var``."""
    if not DATASET_ID_RE.match(dataset_id):
        raise HTTPException(status_code=404, detail={"reason_code": "unknown_dataset"})
    index, missing = _export_artifact("reliability_foreign_index.json")
    detail, detail_missing = _export_artifact(f"reliability_foreign_{dataset_id}.json")
    if detail is None:
        # Known = carded in the index, or listed as omitted (with its reason) in the export manifest.
        known = (index is not None and any(d.get("id") == dataset_id for d in index.get("datasets", [])))             or detail_missing["reason"] not in ("artifact_not_in_export", "research_export_missing")
        if detail_missing["reason"] != "research_export_missing" and not known:
            raise HTTPException(status_code=404, detail={"reason_code": "unknown_dataset"})
        return {**detail_missing, "id": dataset_id}
    available = detail.get("available") or {}
    rows = _pair_rows(detail)
    pair_scales = [s for s in available.get("scales") or [] if any(r.get("scale") == s for r in rows)]
    var = _pick(var, available.get("vars") or [], "Temp")
    scale = _pick(scale, pair_scales or available.get("scales") or [])
    transfer = _pick(transfer, available.get("transfers") or [], "raw")
    result = {key: value for key, value in detail.items() if key not in ("pairs", "radius")}
    result.update({
        "id": dataset_id,
        "pairs": _expand_pairs(detail, rows, var, scale, transfer),
        "radius": [r for r in detail.get("radius") or [] if not var or r.get("var") == var],
        "selected": {"var": var, "scale": scale, "transfer": transfer},
    })
    return result


@router.get("/reliability/vn")
def reliability_vn() -> dict:
    payload, missing = _export_artifact("reliability_vn.json")
    return payload or missing


# ---------------------------------------------------------------- live long-horizon shadow ledger
def _tail_records(path: Path, max_bytes: int) -> list[dict]:
    """Complete JSON lines from the last ``max_bytes`` of an append-only JSONL (cached by mtime/size)."""
    def build():
        size = path.stat().st_size
        with path.open("rb") as handle:
            start = max(0, size - max_bytes)
            handle.seek(start)
            chunk = handle.read()
        if start > 0:
            chunk = chunk[chunk.find(b"\n") + 1:]  # drop the partial first line
        records = []
        for line in chunk.split(b"\n"):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue  # partial last line while the runner appends
        return records
    return _cached(f"tail:{path}:{max_bytes}", path, build)


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def _band(pi: dict | None, level: str) -> list[float] | None:
    band = (pi or {}).get(level)
    if not isinstance(band, dict):
        return None
    lower, upper = band.get("lower"), band.get("upper")
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (lower, upper)):
        return None
    return [round(float(lower), 4), round(float(upper), 4)]


def _withdrawn(skips: list[dict]) -> list[dict]:
    path = Path(settings.sensor_future_manifest_path)
    if path.is_file():
        manifest = _load_json(path)
        return [{"target": b.get("target"), "feature_set": b.get("feature_set"), "horizon_min": b.get("horizon_minutes"),
                 "reason": b.get("withdrawn_reason"), "withdrawn_at": b.get("withdrawn_at")}
                for b in manifest.get("bundles", []) if b.get("status") == "withdrawn"]
    seen = {}
    for skip in skips:
        if skip.get("reason") == "bundle_withdrawn":
            detail = skip.get("detail") or {}
            seen[(skip.get("target"), skip.get("feature_set"), skip.get("horizon_minutes"))] = {
                "target": skip.get("target"), "feature_set": skip.get("feature_set"), "horizon_min": skip.get("horizon_minutes"),
                "reason": detail.get("withdrawn_reason"), "withdrawn_at": detail.get("withdrawn_at")}
    return list(seen.values())


def _scoring(outcomes: list[dict]) -> list[dict]:
    groups: dict[tuple, dict] = defaultdict(lambda: {"err": [], "pers": [], "c80": [], "c90": [], "excluded": 0})
    for o in outcomes:
        key = (o.get("target"), o.get("horizon_minutes"), o.get("model_variant"), o.get("feature_set"))
        if o.get("status") == "excluded_sensor_suspect":
            groups[key]["excluded"] += 1
        if o.get("status") != "scored":
            continue
        g = groups[key]
        try:
            g["err"].append(abs(float(o["forecast"]) - float(o["actual"])))
            g["pers"].append(abs(float(o["current"]) - float(o["actual"])))
        except (KeyError, TypeError, ValueError):
            continue
        covered = o.get("covered") or {}
        if "pi80" in covered:
            g["c80"].append(bool(covered["pi80"]))
        if "pi90" in covered:
            g["c90"].append(bool(covered["pi90"]))

    def mean(values, digits=4):
        return round(sum(values) / len(values), digits) if values else None

    return [{"target": k[0], "horizon_min": k[1], "model_variant": k[2], "feature_set": k[3], "n": len(g["err"]),
             "n_excluded": g["excluded"], "mae": mean(g["err"]), "persistence_mae": mean(g["pers"]),
             "coverage80": mean(g["c80"], 3), "coverage90": mean(g["c90"], 3)}
            for k, g in sorted(groups.items(), key=lambda item: tuple(str(x) for x in item[0]))]


@router.get("/forecast/long")
def forecast_long(station: str = DEFAULT_STATION) -> dict:
    shadow = Path(settings.hap_runtime_dir) / "forecast-shadow"
    forecasts_path, skips_path, outcomes_path = (shadow / f"long_{n}.jsonl" for n in ("forecasts", "skips", "outcomes"))
    tail = settings.ledger_tail_bytes
    skips_all = [s for s in (_tail_records(skips_path, tail) if skips_path.is_file() else [])
                 if s.get("station_serial") == station]
    base = {"station": station, "mode": "shadow", "used_by_alerts": False,
            "window": f"last {LEDGER_WINDOW.total_seconds() / 3600:g} h of the ledger tail ({tail // (1024 * 1024)} MB per file)",
            "withdrawn": _withdrawn(skips_all)}
    if not forecasts_path.is_file():
        return {**base, "status": "unavailable", "reason": "ledger_missing", "ledger_state": "missing",
                "latest_issued_at": None, "items": [], "skips": [], "scoring": []}
    records = [r for r in _tail_records(forecasts_path, tail) if r.get("station_serial") == station]
    issued = [(t, r) for r in records if (t := _parse_time(r.get("issued_at"))) is not None]
    if not issued:
        return {**base, "status": "ready", "ledger_state": "empty", "latest_issued_at": None, "latest_age_minutes": None,
                "items": [], "skips": [], "scoring": []}
    latest_time = max(t for t, _ in issued)
    cutoff = latest_time - LEDGER_WINDOW
    latest: dict[tuple, tuple[datetime, dict]] = {}
    for t, r in issued:
        key = (r.get("target"), r.get("horizon_minutes"), r.get("feature_set"))
        if t >= cutoff and (key not in latest or t >= latest[key][0]):
            latest[key] = (t, r)
    items = []
    for _, r in sorted(latest.values(), key=lambda item: (str(item[1].get("target")), item[1].get("horizon_minutes") or 0,
                                                          str(item[1].get("feature_set")))):
        pi = r.get("pi") or {}
        items.append({"target": r.get("target"), "horizon_min": r.get("horizon_minutes"), "feature_set": r.get("feature_set"),
                      "model_variant": r.get("model_variant"), "bundle_role": r.get("bundle_role"),
                      "issued_at": r.get("issued_at"), "valid_at": r.get("valid_at"), "value": _json_safe(r.get("forecast")),
                      "current": _json_safe(r.get("current")), "pi80": _band(pi, "pi80"), "pi90": _band(pi, "pi90"),
                      "pi_method": pi.get("method"), "ph_input_status": r.get("ph_input_status"),
                      "sensor_status": r.get("sensor_status"), "model_version": r.get("model_version"),
                      "data_source": r.get("data_source")})
    now = _now()
    recent_skips: dict[tuple, dict] = {}
    for s in skips_all:
        at = s.get("issued_at") or s.get("recorded_at")
        when = _parse_time(s.get("recorded_at")) or _parse_time(at)
        if when is None or when < now - LEDGER_WINDOW:
            continue
        key = (s.get("target"), s.get("horizon_minutes"), s.get("feature_set"), s.get("reason"))
        if key not in recent_skips or str(at) >= str(recent_skips[key]["at"]):
            recent_skips[key] = {"target": key[0], "horizon_min": key[1], "feature_set": key[2], "reason": key[3], "at": at}
    outcomes = [o for o in (_tail_records(outcomes_path, tail) if outcomes_path.is_file() else [])
                if o.get("station_serial") == station]
    return {**base, "status": "ready", "ledger_state": "active", "latest_issued_at": latest_time.isoformat(),
            "latest_age_minutes": round((now - latest_time).total_seconds() / 60, 1), "items": items,
            "skips": sorted(recent_skips.values(), key=lambda s: str(s["at"]), reverse=True)[:100],
            "scoring": _scoring(outcomes)}


# ---------------------------------------------------------------- weather snapshot coverage
_RETRIEVED_RE = re.compile(rb'"retrieved_at":\s*"([^"]+)"')
_STATION_RE = re.compile(rb'"station":\s*"([^"]+)"')


def _weather_captures(path: Path, since: datetime) -> tuple[dict[str, list[datetime]], bool]:
    """station -> sorted unique capture times >= ``since``; read backwards from the end of the file.

    Returns (captures, reached_file_start). Lines are only regex-scanned, not JSON-parsed.
    """
    def build():
        size = path.stat().st_size
        found: dict[str, set[datetime]] = defaultdict(set)
        end, carry, reached_start, block = size, b"", False, 4 * 1024 * 1024
        with path.open("rb") as handle:
            while end > 0 and size - end < WEATHER_MAX_SCAN_BYTES:
                start = max(0, end - block)
                handle.seek(start)
                chunk = handle.read(end - start) + carry
                end = start
                if start > 0:
                    cut = chunk.find(b"\n")
                    carry, chunk = chunk[:cut], chunk[cut + 1:]
                else:
                    reached_start = True
                oldest = None
                for line in chunk.split(b"\n"):
                    t_match, s_match = _RETRIEVED_RE.search(line), _STATION_RE.search(line)
                    if not (t_match and s_match):
                        continue
                    when = _parse_time(t_match.group(1).decode())
                    if when is None:
                        continue
                    oldest = when if oldest is None or when < oldest else oldest
                    if when >= since:
                        found[s_match.group(1).decode()].add(when)
                if oldest is not None and oldest < since:
                    break  # append-only file: everything before is older
        return {station: sorted(times) for station, times in found.items()}, reached_start
    return _cached(f"weather:{path}:{since.date()}", path, build)


@router.get("/weather/status")
def weather_status(station: str = DEFAULT_STATION) -> dict:
    path = Path(settings.weather_snapshots_path)
    base = {"station": station, "note": "observation-only", "used_by_alerts": False,
            "source": "Open-Meteo forecast snapshots captured hourly (captured_live)"}
    empty = {"coverage_24h": None, "coverage_7d": None, "health": "unavailable", "last_captured_at": None, "hourly": []}
    if not path.is_file():
        return {**base, **empty, "status": "unavailable", "reason": "snapshot_file_missing"}
    now = _now()
    captures, reached_start = _weather_captures(path, now - WEATHER_WINDOW - timedelta(days=1))
    times = captures.get(station) or []
    if not times:
        return {**base, **empty, "status": "unavailable", "reason": "no_records_for_station"}
    last = times[-1]
    age_hours = (now - last).total_seconds() / 3600
    cap_24h = sum(1 for t in times if timedelta(0) <= now - t <= timedelta(hours=24))
    cap_7d = sum(1 for t in times if timedelta(0) <= now - t <= WEATHER_WINDOW)
    first = times[0] if reached_start else now - WEATHER_WINDOW
    window_start = max(first, now - WEATHER_WINDOW)
    expected = max(1.0, (now - window_start).total_seconds() / 3600)
    coverage_7d = round(min(1.0, cap_7d / expected), 3)
    if age_hours > WEATHER_STALE_HOURS:
        health, reason = "degraded", "stale_last_capture"
    elif coverage_7d < WEATHER_MIN_COVERAGE:
        health, reason = "degraded", "coverage_below_min"
    else:
        health, reason = "healthy", None
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    hours = {t.replace(minute=0, second=0, microsecond=0) for t in times}
    hourly = [{"hour": (h := current_hour - timedelta(hours=k)).isoformat(), "captured": h in hours} for k in range(167, -1, -1)]
    return {**base, "status": "ready", "health": health, "reason": reason, "coverage_24h": round(min(1.0, cap_24h / 24), 3),
            "coverage_7d": coverage_7d, "min_coverage": WEATHER_MIN_COVERAGE, "captures_24h": cap_24h, "captures_7d": cap_7d,
            "last_captured_at": last.isoformat(), "age_hours": round(age_hours, 2), "hourly": hourly}
