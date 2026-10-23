"""Per-station hazard alerts (Track G) and active storms (Track D), read-only.

Contract: docs/superpowers/plans/2026-10-23-phase1-parallel.md (C2, C3).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
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


# --- /hazards/stations (Track G) ----------------------------------------------------------------
# Reads the C2 ledger (hazard_<YYYYMMDD>.jsonl, written by core.hazard_runner / experiments) read-only.
HAZARD_FILE = re.compile(r"^hazard_(\d{8})\.jsonl$")
LEDGER_FILES_READ = 2  # newest day + the one before: a run near 00:00 UTC spans both files
STATION_STALE_AFTER_H = 3.0  # a run older than this is not "current" (shadow honesty, AGENTS.md rule 4)
OUTLOOK_DAYS = 5
LOCAL_TZ_OFFSET_H = 7  # Asia/Ho_Chi_Minh, no DST
REPLAY_SOURCES = {"replay", "reanalysis", "reanalysis_as_forecast", "hindcast", "demo", "synthetic"}
REPLAY_MODELS = {"era5", "oisst"}
FLAGS = {"used_by_alerts": False, "notification_eligible": False, "basis": "theory_only_unvalidated"}


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def _iso(ts: datetime | None) -> str | None:
    return None if ts is None else ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _alert_config_module():
    """``core.alert_config`` (Track A) when importable, else None (labels/thresholds then come from records only)."""
    try:
        from core import alert_config  # type: ignore
        return alert_config
    except ImportError:
        import sys
        root = next((p for p in Path(__file__).resolve().parents if (p / "core" / "alert_config.py").is_file()), None)
        if root is None:
            return None
        sys.path.insert(0, str(root))
        try:
            from core import alert_config  # type: ignore
            return alert_config
        except ImportError:
            return None


def _config_for(station: str | None, exposure_class: str | None) -> dict | None:
    mod = _alert_config_module()
    if mod is None:
        return None
    try:
        return mod.load_effective(station, exposure_class)
    except Exception:  # an invalid runtime version must not take the read view down
        return None


def _station_registry() -> dict[str, dict]:
    try:
        from .domain import station_records
        return {r["station"]: r for r in station_records()}
    except Exception:
        return {}


def _read_ledger(folder: Path) -> tuple[list[dict], list[str]]:
    files = sorted((p for p in folder.glob("hazard_*.jsonl") if HAZARD_FILE.match(p.name)),
                   key=lambda p: p.name, reverse=True)[:LEDGER_FILES_READ] if folder.is_dir() else []
    records: list[dict] = []
    for path in files:
        try:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue  # a half-written last line while the runner appends
                    if isinstance(rec, dict) and rec.get("station") and rec.get("hazard") \
                            and _parse_ts(rec.get("issued_at")):
                        records.append(rec)
        except OSError:
            continue
    return records, [p.name for p in files]


def _is_replay(rec: dict) -> bool:
    inputs = rec.get("inputs") if isinstance(rec.get("inputs"), dict) else {}
    return bool(rec.get("replay")) or str(inputs.get("source", "")).lower() in REPLAY_SOURCES \
        or str(inputs.get("model", "")).lower() in REPLAY_MODELS


def _effective_status(rec: dict, now: datetime, stale_after_h: float) -> str:
    status = rec.get("data_status") if rec.get("data_status") in ("fresh", "stale", "unavailable") else "unavailable"
    if status == "fresh":
        issued = _parse_ts(rec.get("issued_at"))
        if issued is None or (now - issued).total_seconds() / 3600.0 > stale_after_h:
            return "stale"
    return status


def _hazard_entry(rec: dict, status: str, labels: dict) -> dict:
    out = {"hazard": rec["hazard"], "label_vi": labels.get(rec["hazard"]), "tier": rec.get("tier"),
           "value": rec.get("value"), "unit": rec.get("unit"), "action_vi": rec.get("action_vi"),
           "data_status": status, "lead_hours": rec.get("lead_hours"),
           "valid_from": rec.get("valid_from"), "valid_to": rec.get("valid_to"),
           "inputs": rec.get("inputs") if isinstance(rec.get("inputs"), dict) else {}}
    if rec.get("skip_reason"):
        out["skip_reason"] = rec["skip_reason"]
        out["tier"] = None
    return out


def _usable_tier(entry: dict) -> int | None:
    """Tier that may be shown as a state: only fresh, evaluated records."""
    if entry["data_status"] != "fresh" or entry.get("skip_reason") or entry.get("tier") is None:
        return None
    return int(entry["tier"])


def _max_tier(entries: list[dict]) -> int | None:
    tiers = [t for t in (_usable_tier(e) for e in entries) if t is not None]
    return max(tiers) if tiers else None


def _station_status(entries: list[dict]) -> str:
    """fresh = at least one fresh evaluated hazard; else stale if any input is stale; else unavailable."""
    if any(e["data_status"] == "fresh" and not e.get("skip_reason") for e in entries):
        return "fresh"
    if any(e["data_status"] == "stale" for e in entries):
        return "stale"
    return "unavailable"


def _window_hours(rec: dict) -> float:
    vf, vt = _parse_ts(rec.get("valid_from")), _parse_ts(rec.get("valid_to"))
    if vf is None or vt is None or vt <= vf:
        return 24.0
    return (vt - vf).total_seconds() / 3600.0


def _block_local_date(start: datetime) -> str:
    """Local (UTC+7) date whose noon falls in the 24 h block [start, start + 24 h).

    Same rule core.hazard_runner uses to put a forecast day into a lead window, so the label matches
    the heat / cold / disease day inside the block (a block starting 16:00 local is mostly tomorrow).
    """
    local = start + timedelta(hours=LOCAL_TZ_OFFSET_H)
    noon = local.replace(hour=12, minute=0, second=0, microsecond=0)
    return (noon if noon >= local else noon + timedelta(days=1)).date().isoformat()


def _outlook(records: list[dict], issued: datetime, statuses: dict[int, str], labels: dict) -> list[dict]:
    """Five 24 h lead blocks; a block takes every record whose lead window overlaps it (72-120 h fills days 4-5)."""
    days = []
    for i in range(OUTLOOK_DAYS):
        lo, hi = 24 * i, 24 * (i + 1)
        entries = []
        for idx, rec in enumerate(records):
            lead = rec.get("lead_hours")
            if not isinstance(lead, (int, float)):
                continue
            if lead < hi and lead + _window_hours(rec) > lo:
                entries.append(_hazard_entry(rec, statuses[idx], labels))
        start = issued.replace(minute=0, second=0, microsecond=0) + timedelta(hours=lo)
        days.append({"date": _block_local_date(start),
                     "block_from": _iso(start), "block_to": _iso(start + timedelta(hours=24)),
                     "lead_from_h": lo, "lead_to_h": hi,
                     "max_tier": _max_tier(entries),
                     "data_status": _station_status(entries) if entries else "unavailable",
                     "hazards": [{k: e.get(k) for k in ("hazard", "tier", "value", "unit", "data_status", "lead_hours",
                                                        "skip_reason") if k in e} for e in entries]})
    return days


def _storm_watch_from_record(rec: dict, now: datetime, config: dict | None) -> dict:
    inputs = rec.get("inputs") if isinstance(rec.get("inputs"), dict) else {}
    run = _parse_ts(inputs.get("run_time")) or _parse_ts(rec.get("valid_from"))
    status = rec.get("data_status") if rec.get("data_status") in ("fresh", "stale", "unavailable") else "unavailable"
    if status == "fresh" and (run is None or (now - run).total_seconds() / 3600.0 > STORMS_STALE_AFTER_H):
        status = "stale"
    out = {"source": "ledger", "p_within_500km_120h": rec.get("value"), "tier": rec.get("tier"),
           "threshold": _watch_threshold(config), "storm_id": inputs.get("storm_id"), "run_time": _iso(run),
           "issued_at": rec.get("issued_at"), "data_status": status, "action_vi": rec.get("action_vi"),
           "model": inputs.get("model")}
    if rec.get("skip_reason"):
        out.update({"skip_reason": rec["skip_reason"], "tier": None, "p_within_500km_120h": None})
    return out


def _watch_threshold(config: dict | None) -> float | None:
    try:
        thr = config["hazards"]["storm_watch"]["thresholds"]  # type: ignore[index]
        return float(min(thr.values()))
    except (TypeError, KeyError, ValueError):
        return None


def _storm_watch_from_summary(config: dict | None) -> dict | None:
    """Fallback when the ledger has no storm_watch record: basin-wide max from the newest storms_active file."""
    body = active_storms()
    if body.get("status") != "ready":
        return None
    storms = [s for s in body.get("storms") or [] if isinstance(s, dict)]
    p = max((float(s.get("p_within_500km_120h") or 0.0) for s in storms), default=0.0)
    top = max(storms, key=lambda s: float(s.get("p_within_500km_120h") or 0.0), default=None)
    thr = _watch_threshold(config)
    tier = None
    if config is not None:
        mod = _alert_config_module()
        try:
            tier = int(mod.tier_for("storm_watch", p, config)) if mod else None
        except Exception:
            tier = None
    return {"source": "storms_active", "file": body.get("file"), "p_within_500km_120h": round(p, 4), "tier": tier,
            "threshold": thr, "storm_id": top.get("id") if top and p > 0 else None,
            "storm_name": top.get("name") if top and p > 0 else None, "run_time": body.get("run_time"),
            "data_status": body.get("data_status", "unavailable"), "site_note": "basin_summary_site_not_per_station"}


@router.get("/hazards/stations")
def station_hazards() -> dict:
    folder = _hazard_shadow_dir()
    now = _now()
    records, files = _read_ledger(folder)
    if not records:
        return {"status": "unavailable", "reason": "no_hazard_ledger" if not files else "empty_hazard_ledger",
                "stations": [], "ledger_files": files, **FLAGS}

    by_station: dict[str, list[dict]] = {}
    for rec in records:
        by_station.setdefault(str(rec["station"]), []).append(rec)
    registry = _station_registry()
    default_cfg = _config_for(None, None)
    summary_watch: dict | None = None

    stations = []
    for sid in sorted(set(by_station) | set(registry)):
        meta = registry.get(sid, {})
        recs = by_station.get(sid, [])
        watch_recs = [r for r in recs if r["hazard"] == "storm_watch"]
        run_recs = [r for r in recs if r["hazard"] != "storm_watch"]
        exposure = next((r.get("exposure_class") for r in reversed(recs) if r.get("exposure_class")), None)
        cfg = _config_for(sid, exposure) if recs else default_cfg
        labels = {k: v.get("label_vi") for k, v in ((cfg or {}).get("hazards") or {}).items()}
        base = {"id": sid, "name": meta.get("name") or sid, "lat": meta.get("latitude"), "lon": meta.get("longitude"),
                "exposure_class": exposure}
        if not run_recs:
            current, outlook, issued, status, run = [], [], None, "unavailable", []
        else:
            issued = max(_parse_ts(r["issued_at"]) for r in run_recs)
            # one run only: records of the newest issue, last write wins per (hazard, lead)
            latest: dict[tuple, dict] = {}
            for r in run_recs:
                if _parse_ts(r["issued_at"]) == issued:
                    latest[(r["hazard"], r.get("lead_hours"))] = r
            run = list(latest.values())
            statuses = {i: _effective_status(r, now, STATION_STALE_AFTER_H) for i, r in enumerate(run)}
            current = [_hazard_entry(r, statuses[i], labels) for i, r in enumerate(run) if r.get("lead_hours") == 0]
            outlook = _outlook(run, issued, statuses, labels)
            status = _station_status(current) if current else "unavailable"
        watch = None
        if watch_recs:
            newest = max(watch_recs, key=lambda r: _parse_ts(r["issued_at"]))
            watch = _storm_watch_from_record(newest, now, cfg)
        else:
            if summary_watch is None:
                summary_watch = {"v": _storm_watch_from_summary(default_cfg)}
            watch = summary_watch["v"]
        all_run = run if run_recs else []
        sources = sorted({str((r.get("inputs") or {}).get("source")) for r in all_run if (r.get("inputs") or {}).get("source")})
        models = sorted({str((r.get("inputs") or {}).get("model")) for r in all_run if (r.get("inputs") or {}).get("model")})
        replay_labels = sorted({str((r.get("replay") or {}).get("label")) for r in all_run
                                if isinstance(r.get("replay"), dict) and r["replay"].get("label")})
        stations.append({
            **base, "issued_at": _iso(issued),
            "age_hours": None if issued is None else round((now - issued).total_seconds() / 3600.0, 1),
            "max_tier": _max_tier(current), "current": current, "outlook": outlook, "storm_watch": watch,
            "data_status": status, "reason": None if recs else "no_records",
            "config_version": next((r.get("config_version") for r in all_run if r.get("config_version")), None),
            "inputs_sources": sources, "inputs_models": models,
            "replay": any(_is_replay(r) for r in all_run), "replay_labels": replay_labels, **FLAGS})

    issued_all = [_parse_ts(s["issued_at"]) for s in stations if s["issued_at"]]
    versions = sorted({s["config_version"] for s in stations if s["config_version"]})
    newest = max(issued_all) if issued_all else None
    newest_version = next((s["config_version"] for s in stations if s["issued_at"] and _parse_ts(s["issued_at"]) == newest), None)
    return {"status": "ready", "issued_at": _iso(newest), "generated_at": _iso(now),
            "config_version": newest_version, "config_versions": versions,
            "tiers": (default_cfg or {}).get("tiers"), "stale_after_hours": STATION_STALE_AFTER_H,
            "ledger_files": files, "replay": any(s["replay"] for s in stations), "stations": stations, **FLAGS}


@router.get("/storms/active")
def active_storms() -> dict:
    folder = _hazard_shadow_dir()
    files = sorted((p for p in folder.glob("storms_active_*.json") if STORMS_FILE.match(p.name)),
                   key=lambda p: p.name, reverse=True) if folder.is_dir() else []
    if not files:
        return {"status": "unavailable", "reason": "no_storm_track_summary", "source": "ecmwf_opendata", "storms": [],
                **FLAGS}
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
               "data_status": "stale" if stale else "fresh", **FLAGS}
        if stale:
            out["reason"] = "stale_run"
        return out
    return {"status": "unavailable", "reason": "unreadable_storm_track_summary", "source": "ecmwf_opendata",
            "storms": [], **FLAGS}
