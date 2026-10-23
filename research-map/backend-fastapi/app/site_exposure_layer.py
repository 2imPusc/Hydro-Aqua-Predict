"""Site-exposure layer for the monitor map (``GET /api/v1/research/site-exposure``), read-only.

Source: the newest ``artifacts/experiments/site-exposure-*`` run (``experiments/site_exposure.py``,
docs/eval/2026-10-23-site-exposure.md). Only the 14 network stations are served:

* per-station aggregates from the strict ``site_exposure.geojson`` (never ``stations.json``:
  the 20261023 run wrote bare ``NaN`` tokens there);
* a 16-direction "dangerous direction" rose at open-water wind cấp 10 (24.5 m/s) joined from
  ``direction_scenarios.csv`` (fetch, Hs, wave class, tier per direction).

Theory only: every response carries ``used_by_alerts: False``, ``notification_eligible: False``,
``basis: "theory_only_unvalidated"``. Missing inputs give ``{"status": "unavailable", "reason"}``.
The API never writes anything.
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from app.settings import settings

router = APIRouter(prefix="/api/v1/research", tags=["site-exposure"])

RUN_RE = re.compile(r"^site-exposure-[0-9A-Za-z_-]+$")
ROSE_BEAUFORT = 10
DIRECTIONS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
# Same thresholds the experiment used for dangerous / watch directions (Hs at cấp 10).
DANGEROUS_HS_M = 2.0
WATCH_HS_M = 1.0
EXPOSURE_LABEL_VI = {"exposed": "hở", "semi": "bán kín", "sheltered": "kín"}
BASIS = {"used_by_alerts": False, "notification_eligible": False, "basis": "theory_only_unvalidated"}

_CACHE: dict[str, tuple[tuple, Any]] = {}


def _experiments_dir() -> Path:
    """``$SITE_EXPOSURE_ROOT`` or ``$HAP_ARTIFACTS_DIR/experiments``; default sits next to the research exports."""
    override = os.getenv("SITE_EXPOSURE_ROOT")
    if override:
        return Path(override)
    artifacts = os.getenv("HAP_ARTIFACTS_DIR")
    return (Path(artifacts) if artifacts else Path(settings.research_export_dir).parent) / "experiments"


def latest_run() -> Path | None:
    root = _experiments_dir()
    if not root.is_dir():
        return None
    runs = [p for p in root.iterdir() if p.is_dir() and RUN_RE.match(p.name) and (p / "site_exposure.geojson").is_file()]
    return max(runs, key=lambda p: p.name) if runs else None


def _finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _json_safe(obj):
    if isinstance(obj, dict):
        return {key: _json_safe(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(value) for value in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def exposure_key(raw: Any) -> str | None:
    """``"hở (exposed)"`` -> ``"exposed"``; also accepts the bare key or the Vietnamese label."""
    text = str(raw or "").strip()
    match = re.search(r"\(([a-z_]+)\)", text)
    key = match.group(1) if match else text.lower()
    if key in EXPOSURE_LABEL_VI:
        return key
    for candidate, label in EXPOSURE_LABEL_VI.items():
        if text.startswith(label):
            return candidate
    return None


def _rose(run: Path, station_ids: set[str]) -> dict[str, list[dict]]:
    path = run / "direction_scenarios.csv"
    if not path.is_file():
        return {}
    roses: dict[str, dict[str, dict]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            site = row.get("site_id")
            if site not in station_ids or _finite(row.get("beaufort_open")) != ROSE_BEAUFORT:
                continue
            direction = row.get("direction")
            if direction not in DIRECTIONS:
                continue
            fetch_m = _finite(row.get("fetch_m"))
            tier = _finite(row.get("tier"))
            local_bf = _finite(row.get("local_beaufort"))
            roses.setdefault(site, {})[direction] = {
                "direction": direction,
                "bearing": _finite(row.get("bearing")),
                "fetch_km": round(fetch_m / 1000, 2) if fetch_m is not None else None,
                "hs_m": _finite(row.get("hs_m")),
                "wave_class": row.get("wave_class") or None,
                "tier": int(tier) if tier is not None else None,
                "local_beaufort": int(local_bf) if local_bf is not None else None,
                "shelter_factor": _finite(row.get("shelter_factor")),
            }
    censored = _censored(run, station_ids)
    out: dict[str, list[dict]] = {}
    for site, by_dir in roses.items():
        items = []
        for direction in DIRECTIONS:
            item = by_dir.get(direction)
            if item is None:
                continue
            item["fetch_censored"] = censored.get((site, direction))
            items.append(item)
        out[site] = items
    return out


def _censored(run: Path, station_ids: set[str]) -> dict[tuple[str, str], bool]:
    path = run / "per_direction.csv"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {(row["site_id"], row["direction"]): str(row.get("fetch_censored", "")).lower() == "true"
                for row in csv.DictReader(handle) if row.get("site_id") in station_ids}


def _station(feature: dict, rose: list[dict]) -> dict | None:
    props = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates") or []
    if geometry.get("type") != "Point" or len(coords) < 2:
        return None
    key = exposure_key(props.get("exposure_class"))
    return {
        "id": props.get("site_id"),
        "name": props.get("name"),
        "lon": _finite(coords[0]),
        "lat": _finite(coords[1]),
        "exposure_class": key,
        "exposure_label_vi": EXPOSURE_LABEL_VI.get(key or "", None),
        "worst_direction": props.get("worst_direction"),
        "dangerous_directions": list(props.get("dangerous_directions") or []),
        "watch_directions": list(props.get("watch_directions") or []),
        "sheltered_directions": list(props.get("sheltered_directions") or []),
        "fetch_straight_worst_km": _finite(props.get("fetch_straight_worst_km")),
        "fetch_effective_max_km": _finite(props.get("fetch_effective_max_km")),
        "open_sectors_censored": list(props.get("open_sectors_censored") or []),
        "hs_worst_m": {"c8": _finite(props.get("hs_worst_c8_m")), "c10": _finite(props.get("hs_worst_c10_m")), "c12": _finite(props.get("hs_worst_c12_m"))},
        "tier_worst": {"c8": props.get("tier_worst_c8"), "c10": props.get("tier_worst_c10"), "c12": props.get("tier_worst_c12")},
        "depth_site_m": _finite(props.get("depth_site_m")),
        "depth_site_flag": props.get("depth_site_flag"),
        "snap_offset_m": _finite(props.get("snap_offset_m")),
        "current_p95_ms": _finite(props.get("current_p95_ms")),
        "current_class_p95": props.get("current_class_p95"),
        "rose": rose,
    }


def _build(run: Path) -> dict:
    # parse_constant: tolerate NaN/Infinity tokens should a run ever write them; they become null.
    geojson = json.loads((run / "site_exposure.geojson").read_text(encoding="utf-8"), parse_constant=lambda _token: None)
    features = [f for f in geojson.get("features") or [] if (f.get("properties") or {}).get("kind") == "station"]
    ids = {str((f.get("properties") or {}).get("site_id")) for f in features}
    roses = _rose(run, ids)
    stations = [s for s in (_station(f, roses.get(str(f["properties"].get("site_id")), [])) for f in features) if s and s["id"]]
    stations.sort(key=lambda s: s["id"])
    manifest_path = run / "manifest.json"
    created_at = None
    if manifest_path.is_file():
        try:
            created_at = json.loads(manifest_path.read_text(encoding="utf-8"), parse_constant=lambda _token: None).get("created_at")
        except (ValueError, OSError):
            created_at = None
    return _json_safe({
        "status": "ready" if stations else "unavailable",
        **({} if stations else {"reason": "no_station_features"}),
        "run_name": run.name,
        "created_at": created_at,
        "rose_beaufort": ROSE_BEAUFORT,
        "rose_wind_ms": 24.5,
        "dangerous_hs_m": DANGEROUS_HS_M,
        "watch_hs_m": WATCH_HS_M,
        "directions": list(DIRECTIONS),
        "method_vi": "Đà gió trên mặt nạ nước OSM, che chắn địa hình DSM, sóng SPM 1984; lớp phơi nhiễm theo Hs lớn nhất ở gió cấp 8 (NS 9415). Lý thuyết, chưa kiểm chứng hiện trường.",
        "stations": stations,
        **BASIS,
    })


@router.get("/site-exposure")
def site_exposure() -> dict:
    run = latest_run()
    if run is None:
        return {"status": "unavailable", "reason": "site_exposure_run_missing", **BASIS}
    geo = run / "site_exposure.geojson"
    csv_path = run / "direction_scenarios.csv"
    key = tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.is_file() else None for p in (geo, csv_path))
    hit = _CACHE.get(str(run))
    if hit and hit[0] == key:
        return hit[1]
    try:
        payload = _build(run)
    except (OSError, ValueError, KeyError) as exc:
        return {"status": "unavailable", "reason": "site_exposure_unreadable", "detail": type(exc).__name__, "run_name": run.name, **BASIS}
    _CACHE.clear()
    _CACHE[str(run)] = (key, payload)
    return payload
