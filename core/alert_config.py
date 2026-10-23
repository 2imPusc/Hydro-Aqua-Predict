"""Alert-tier configuration: defaults, append-only admin versions, validation, tier lookup.

Contract C1 in docs/superpowers/plans/2026-10-23-phase1-parallel.md; decisions #20.

* Defaults: ``paths.ALERT_CONFIG_DEFAULT`` (tracked, never written here).
* Versions: ``paths.ALERT_CONFIG_DIR/v<NNNN>-<UTC>.json``. Created exclusively, never overwritten
  or deleted. Sequence numbers are claimed with an exclusive ``v<NNNN>.claim`` marker first, so two
  concurrent saves can never both take the same number (their timestamps would differ, which
  an exclusive create on the version file alone would not catch).
* Scope overrides (``scopes.exposure_class.<c>`` / ``scopes.station.<id>``) are a mapping
  ``hazard_id -> partial hazard dict`` (e.g. ``{"storm_wind": {"thresholds": {"2": 7}}}``).
  Merge order: base < exposure_class < station.
* Structure is locked (controller decision): saves may change only ``thresholds``, ``actions_vi``,
  ``persistence_days`` (and scope overrides of those three) relative to the defaults; see
  ``structural_errors``. ``validate`` only checks internal consistency.
* ``persistence_days`` is validated and returned, never applied here (the hazard runner applies it).

Stdlib only so the research-map backend (which imports this module) stays light.
"""
from __future__ import annotations

import copy
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core import paths

EXPOSURE_CLASSES = ("sheltered", "semi", "exposed")
DIRECTIONS = ("ge", "le")
_VERSION_RE = re.compile(r"^v(\d{4,})-(\d{8}T\d{6}Z)$")
_CLAIM_RE = re.compile(r"^v(\d{4,})\.claim$")

_META_KEYS = {"config_version", "parent_version", "changed_at", "changed_by", "reason_vi", "changes"}
_TOP_KEYS = _META_KEYS | {"schema_version", "note_vi", "tiers", "hazards", "scopes"}
_TIER_KEYS = {"tier", "label_vi", "color"}
_HAZARD_KEYS = {"label_vi", "metric", "unit", "direction", "thresholds", "persistence_days",
                "actions_vi", "guardrails", "evidence"}
_SCOPE_KEYS = {"exposure_class", "station"}


class ConfigValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# ---------------------------------------------------------------- IO

def _config_dir() -> Path:
    return Path(paths.ALERT_CONFIG_DIR)


def load_default() -> dict:
    with open(paths.ALERT_CONFIG_DEFAULT, encoding="utf-8") as fh:
        return json.load(fh)


def _version_files() -> list[Path]:
    d = _config_dir()
    if not d.is_dir():
        return []
    return sorted((p for p in d.glob("v*.json") if _VERSION_RE.match(p.stem)), key=lambda p: p.name)


def _read(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _newest_valid() -> dict | None:
    for path in reversed(_version_files()):
        data = _read(path)
        if data is not None and not validate(data):
            return data
    return None


def effective_source() -> str:
    return "runtime" if _newest_valid() is not None else "default"


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for key, val in over.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = copy.deepcopy(val)
    return out


def load_effective(station_id: str | None = None, exposure_class: str | None = None) -> dict:
    """Newest valid version (else defaults), with scope overrides merged into ``hazards``."""
    cfg = copy.deepcopy(_newest_valid() or load_default())
    scopes = cfg.get("scopes") or {}
    hazards = cfg.get("hazards", {})
    for over in (
        (scopes.get("exposure_class") or {}).get(exposure_class) if exposure_class else None,
        (scopes.get("station") or {}).get(station_id) if station_id else None,
    ):
        if over:
            hazards = _deep_merge(hazards, {h: v for h, v in over.items() if h in hazards})
    cfg["hazards"] = hazards
    return cfg


def list_versions() -> list[dict]:
    """Summaries, oldest first. Unreadable files are skipped."""
    out = []
    for path in _version_files():
        d = _read(path)
        if d is None:
            continue
        out.append({
            "config_version": d.get("config_version", path.stem),
            "changed_at": d.get("changed_at"),
            "changed_by": d.get("changed_by"),
            "reason_vi": d.get("reason_vi"),
            "n_changes": len(d.get("changes") or []),
        })
    return out


def get_version(v: str) -> dict:
    if not _VERSION_RE.match(v or ""):
        raise KeyError(v)
    data = _read(_config_dir() / f"{v}.json")
    if data is None:
        raise KeyError(v)
    return data


# ---------------------------------------------------------------- validation

def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _tier_id(key: Any) -> int | None:
    try:
        return int(key)
    except (TypeError, ValueError):
        return None


def _validate_hazard(hid: str, h: Any, tier_ids: set[int], errs: list[str], where: str) -> None:
    p = f"{where}.{hid}"
    if not isinstance(h, dict):
        errs.append(f"{p}: must be an object")
        return
    for k in sorted(set(h) - _HAZARD_KEYS):
        errs.append(f"{p}: unknown key '{k}'")
    for k in ("metric", "unit"):
        if not isinstance(h.get(k), str) or not h.get(k):
            errs.append(f"{p}.{k}: required non-empty string")
    direction = h.get("direction")
    if direction not in DIRECTIONS:
        errs.append(f"{p}.direction: must be 'ge' or 'le'")
    thr = h.get("thresholds")
    thr_tiers: dict[int, float] = {}
    if not isinstance(thr, dict) or not thr:
        errs.append(f"{p}.thresholds: required non-empty object")
    else:
        for k, v in thr.items():
            t = _tier_id(k)
            if t is None or t not in tier_ids:
                errs.append(f"{p}.thresholds.{k}: unknown tier")
            elif t == 0:
                errs.append(f"{p}.thresholds.{k}: tier 0 is the baseline and has no threshold")
            elif not _is_num(v):
                errs.append(f"{p}.thresholds.{k}: must be a finite number")
            else:
                thr_tiers[t] = float(v)
        if direction in DIRECTIONS:
            ordered = sorted(thr_tiers.items())
            for (ta, va), (tb, vb) in zip(ordered, ordered[1:]):
                ok = vb > va if direction == "ge" else vb < va
                if not ok:
                    errs.append(f"{p}.thresholds: tier {tb} ({vb:g}) must be strictly "
                                f"{'greater' if direction == 'ge' else 'less'} than tier {ta} ({va:g}) "
                                f"for direction '{direction}'")
    actions = h.get("actions_vi")
    if not isinstance(actions, dict):
        errs.append(f"{p}.actions_vi: required object")
    else:
        for k, v in actions.items():
            t = _tier_id(k)
            if t is None or t not in tier_ids:
                errs.append(f"{p}.actions_vi.{k}: unknown tier")
            elif not isinstance(v, str):
                errs.append(f"{p}.actions_vi.{k}: must be a string")
        for t in sorted(thr_tiers):
            a = actions.get(str(t))
            if not isinstance(a, str) or not a.strip():
                errs.append(f"{p}.actions_vi.{t}: missing action for threshold tier {t}")
    pers = h.get("persistence_days")
    if pers is not None:
        if not isinstance(pers, dict):
            errs.append(f"{p}.persistence_days: must be an object")
        else:
            for k, v in pers.items():
                t = _tier_id(k)
                if t is None or t not in thr_tiers:
                    errs.append(f"{p}.persistence_days.{k}: not a threshold tier")
                elif isinstance(v, bool) or not isinstance(v, int) or v < 1:
                    errs.append(f"{p}.persistence_days.{k}: must be an integer >= 1")
    gr = h.get("guardrails")
    if gr is not None:
        if not isinstance(gr, dict) or set(gr) - {"min", "max"}:
            errs.append(f"{p}.guardrails: must be an object with only 'min' and 'max'")
        else:
            for side in ("min", "max"):
                for k, bound in (gr.get(side) or {}).items():
                    t = _tier_id(k)
                    if t is None or t not in thr_tiers:
                        errs.append(f"{p}.guardrails.{side}.{k}: not a threshold tier")
                    elif not _is_num(bound):
                        errs.append(f"{p}.guardrails.{side}.{k}: must be a finite number")
                    elif side == "min" and thr_tiers[t] < bound:
                        errs.append(f"{p}.thresholds.{k}: {thr_tiers[t]:g} below guardrail min {bound:g}")
                    elif side == "max" and thr_tiers[t] > bound:
                        errs.append(f"{p}.thresholds.{k}: {thr_tiers[t]:g} above guardrail max {bound:g}")
    ev = h.get("evidence")
    if ev is not None and not (isinstance(ev, list) and all(isinstance(x, str) for x in ev)):
        errs.append(f"{p}.evidence: must be a list of strings")
    if h.get("label_vi") is not None and not isinstance(h.get("label_vi"), str):
        errs.append(f"{p}.label_vi: must be a string")


def validate(config: dict) -> list[str]:
    """Return a list of error strings (empty = valid)."""
    errs: list[str] = []
    if not isinstance(config, dict):
        return ["config: must be an object"]
    for k in sorted(set(config) - _TOP_KEYS):
        errs.append(f"unknown top-level key '{k}'")
    tiers = config.get("tiers")
    tier_ids: set[int] = set()
    if not isinstance(tiers, list) or not tiers:
        errs.append("tiers: required non-empty list")
    else:
        for i, t in enumerate(tiers):
            if not isinstance(t, dict) or set(t) - _TIER_KEYS or not isinstance(t.get("tier"), int) \
                    or isinstance(t.get("tier"), bool):
                errs.append(f"tiers.{i}: must be {{tier:int, label_vi, color}}")
            else:
                tier_ids.add(t["tier"])
        if 0 not in tier_ids:
            errs.append("tiers: tier 0 is required")
    hazards = config.get("hazards")
    if not isinstance(hazards, dict) or not hazards:
        errs.append("hazards: required non-empty object")
        return errs
    for hid, h in hazards.items():
        _validate_hazard(hid, h, tier_ids, errs, "hazards")
    scopes = config.get("scopes", {})
    if not isinstance(scopes, dict):
        errs.append("scopes: must be an object")
        return errs
    for k in sorted(set(scopes) - _SCOPE_KEYS):
        errs.append(f"scopes: unknown key '{k}'")
    for kind in _SCOPE_KEYS & set(scopes):
        group = scopes[kind]
        if not isinstance(group, dict):
            errs.append(f"scopes.{kind}: must be an object")
            continue
        for name, over in group.items():
            where = f"scopes.{kind}.{name}"
            if kind == "exposure_class" and name not in EXPOSURE_CLASSES:
                errs.append(f"{where}: unknown exposure class")
            if not isinstance(over, dict):
                errs.append(f"{where}: must be an object")
                continue
            for hid, part in over.items():
                if hid not in hazards:
                    errs.append(f"{where}.{hid}: unknown hazard")
                elif not isinstance(part, dict):
                    errs.append(f"{where}.{hid}: must be an object")
                else:
                    unknown = sorted(set(part) - _HAZARD_KEYS)
                    for k in unknown:
                        errs.append(f"{where}.{hid}: unknown key '{k}'")
                    if not unknown and isinstance(hazards[hid], dict):
                        # the override must still yield a valid hazard once merged
                        merged = _deep_merge(hazards[hid], part)
                        sub: list[str] = []
                        _validate_hazard(hid, merged, tier_ids, sub, where)
                        errs.extend(e for e in sub if e not in errs)
    return errs


_EDITABLE = ("thresholds", "actions_vi", "persistence_days")
_LOCKED = ("metric", "unit", "direction", "label_vi", "evidence", "guardrails")


def structural_errors(config: dict, defaults: dict | None = None) -> list[str]:
    """Errors for any change outside thresholds / actions_vi / persistence_days vs the defaults."""
    if not isinstance(config, dict):
        return ["config: must be an object"]
    defaults = defaults if defaults is not None else load_default()
    errs: list[str] = []
    if config.get("tiers") != defaults.get("tiers"):
        errs.append("tiers: not editable")
    hz, dz = config.get("hazards"), defaults.get("hazards", {})
    if not isinstance(hz, dict):
        return errs + ["hazards: must be an object"]
    for hid in sorted(set(dz) - set(hz)):
        errs.append(f"hazards.{hid}: hazard cannot be removed")
    for hid in sorted(set(hz) - set(dz)):
        errs.append(f"hazards.{hid}: hazard cannot be added")
    for hid in sorted(set(hz) & set(dz)):
        h, d = hz[hid], dz[hid]
        if not isinstance(h, dict):
            continue
        for k in _LOCKED:
            if h.get(k) != d.get(k):
                errs.append(f"hazards.{hid}.{k}: not editable")
    scopes = config.get("scopes")
    if isinstance(scopes, dict):
        for kind, group in scopes.items():
            for name, over in (group.items() if isinstance(group, dict) else []):
                for hid, part in (over.items() if isinstance(over, dict) else []):
                    for k in (part if isinstance(part, dict) else []):
                        if k not in _EDITABLE:
                            errs.append(f"scopes.{kind}.{name}.{hid}.{k}: not editable "
                                        f"(only {', '.join(_EDITABLE)})")
    return errs


# ---------------------------------------------------------------- tier lookup

def tier_for(hazard_id: str, value: float, config: dict) -> int | None:
    """Highest tier whose threshold is reached; 0 below all; None for missing/NaN values."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(v):
        return None
    h = config["hazards"][hazard_id]
    ge = h["direction"] == "ge"
    tier = 0
    for k, thr in sorted(h["thresholds"].items(), key=lambda kv: int(kv[0])):
        if (v >= thr) if ge else (v <= thr):
            tier = int(k)
    return tier


# ---------------------------------------------------------------- save

def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(obj, dict) and obj:
        out: dict[str, Any] = {}
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
        return out
    return {prefix: obj}


def compute_changes(old: dict, new: dict) -> list[dict]:
    a = _flatten({k: v for k, v in old.items() if k not in _META_KEYS})
    b = _flatten({k: v for k, v in new.items() if k not in _META_KEYS})
    out = []
    for path in sorted(set(a) | set(b)):
        if a.get(path) != b.get(path) or (path in a) != (path in b):
            out.append({"path": path, "old": a.get(path), "new": b.get(path)})
    return out


def _next_number(d: Path) -> int:
    nums = [0]
    for p in d.iterdir():
        m = _VERSION_RE.match(p.stem) if p.suffix == ".json" else _CLAIM_RE.match(p.name)
        if m:
            nums.append(int(m.group(1)))
    return max(nums) + 1


def save_version(config: dict, *, changed_by: str, reason_vi: str) -> str:
    """Validate and write a new version file; returns its config_version. Never overwrites."""
    errors = validate(config) + structural_errors(config)
    if errors:
        raise ConfigValidationError(errors)
    d = _config_dir()
    d.mkdir(parents=True, exist_ok=True)
    parent = _newest_valid() or load_default()
    body = {k: copy.deepcopy(v) for k, v in config.items() if k not in _META_KEYS}
    body.setdefault("schema_version", parent.get("schema_version", 1))
    while True:
        n = _next_number(d)
        try:
            with open(d / f"v{n:04d}.claim", "x", encoding="utf-8"):
                pass
        except FileExistsError:
            continue
        now = datetime.now(timezone.utc)
        version = f"v{n:04d}-{now:%Y%m%dT%H%M%SZ}"
        record = {
            **body,
            "config_version": version,
            "parent_version": parent.get("config_version"),
            "changed_at": now.isoformat(),
            "changed_by": changed_by or "admin-ui",
            "reason_vi": reason_vi,
            "changes": compute_changes(parent, body),
        }
        try:
            with open(d / f"{version}.json", "x", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False, indent=2)
                fh.flush()
        except FileExistsError:
            continue
        return version
