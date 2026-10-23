"""Per-station hazard shadow runner (theory only, shadow mode).

``evaluate_station`` turns a forecast (wind, marine SST) into C2 ledger records
(docs/superpowers/plans/2026-10-23-phase1-parallel.md) for storm_wind, wave_height, heat, cold
and disease_env over lead windows 0-24, 24-48, 48-72, 72-120 h.  ``run_once`` appends them to
``paths.HAZARD_SHADOW_DIR/hazard_<YYYYMMDD>.jsonl`` (append-only).  Nothing here drives alerts.

Honesty rules: stale or missing inputs produce skip records (``tier: null`` + ``skip_reason``),
never a value; without exposure data the wind is assumed open-water and flagged, and no wave
height is invented; water temperature is the raw Open-Meteo marine SST (``correction: "none"``)
because no cited SST-to-water bias correction exists.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from core import disease_risk as dr
from core import heat_stress as hs
from core import paths
from core import site_exposure as se
from core import storm_advisory as sa

# --- TEMPORARY fallback until Track A's core/alert_config.py lands; remove with the try/except. ---
try:
    from core.alert_config import load_effective, tier_for
except ImportError:  # pragma: no cover - exercised only before Track A merges
    def load_effective(station_id: str | None = None, exposure_class: str | None = None) -> dict:
        return json.loads(Path(paths.ALERT_CONFIG_DEFAULT).read_text(encoding="utf-8"))

    def tier_for(hazard_id: str, value: float, config: dict) -> int:
        spec = config["hazards"][hazard_id]
        ge = spec["direction"] == "ge"
        tier = 0
        for k, thr in sorted(((int(k), float(v)) for k, v in spec["thresholds"].items())):
            if (value >= thr) if ge else (value <= thr):
                tier = k
        return tier
# ------------------------------------------------------------------------------------------------

LEAD_WINDOWS_H = ((0, 24), (24, 48), (48, 72), (72, 120))
FORECAST_MODEL = "ecmwf_ifs025"
MAX_AGE_HOURS = 6.0
LOCAL_TZ = "Asia/Ho_Chi_Minh"
FLAGS = {"used_by_alerts": False, "notification_eligible": False, "basis": "theory_only_unvalidated"}
HAZARDS = ("storm_wind", "wave_height", "heat", "cold", "disease_env")
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
EXPOSURE_KEYS = {"exposed": "exposed", "semi": "semi", "sheltered": "sheltered"}

# Extra evaluators (e.g. Track D's storm_watch): fn(station, ctx) -> list[record].  ctx has
# now, config, issued_at, windows.  Registered functions must build records with ``make_record``.
HAZARD_HOOKS: dict[str, Callable[[dict, dict], list[dict]]] = {}


def register_hazard(name: str, fn: Callable[[dict, dict], list[dict]]) -> None:
    HAZARD_HOOKS[name] = fn


def _utc(ts) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _iso(ts: pd.Timestamp) -> str:
    return ts.isoformat().replace("+00:00", "Z")


def _norm_class(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    low = raw.lower()
    for key in EXPOSURE_KEYS:
        if key in low:
            return key
    return None


# --------------------------------------------------------------------------- station inputs

def load_stations() -> list[dict]:
    """Stations from ``paths.STATION_COORDINATES`` joined with the latest site-exposure run."""
    coords = pd.read_csv(paths.STATION_COORDINATES)
    exposure = load_exposure()
    out = []
    for _, r in coords.iterrows():
        sid = str(r["Station"])
        ex = exposure.get(sid, {})
        out.append({"id": sid, "name": r.get("Station_Name"), "lat": float(r["Lat"]), "lon": float(r["Lon"]),
                    "exposure_class": ex.get("exposure_class"), "profile": ex.get("profile"),
                    "exposure_run": ex.get("run")})
    return out


def latest_exposure_dir() -> Path | None:
    root = paths.EXPERIMENT_OUTPUT_DIR
    if not root.is_dir():
        return None
    for d in sorted(root.glob("site-exposure-*"), reverse=True):
        if (d / "stations.csv").is_file() and (d / "per_direction.csv").is_file():
            return d
    return None


def load_exposure(run_dir: Path | None = None) -> dict[str, dict]:
    """{station: {exposure_class, profile, run}} from site-exposure-*/ (read-only); {} when absent."""
    run_dir = run_dir or latest_exposure_dir()
    if run_dir is None:
        return {}
    stations = pd.read_csv(run_dir / "stations.csv")
    per_dir = pd.read_csv(run_dir / "per_direction.csv")
    out = {}
    for sid, grp in per_dir.groupby("site_id"):
        row = stations[stations["site_id"] == sid]
        cls = _norm_class(row["exposure_class"].iloc[0]) if len(row) else None
        g = grp.sort_values("bearing")
        depth = g["depth_mean_m"].fillna(g["depth_mean_m"].median()).fillna(10.0).clip(lower=1.0)
        out[str(sid)] = {"exposure_class": cls, "run": run_dir.name,
                         "profile": {"bearing": g["bearing"].to_numpy(), "fetch_m": g["fetch_straight_m"].to_numpy(),
                                     "depth_m": depth.to_numpy(), "shelter": g["shelter_factor"].to_numpy(),
                                     "censored": g["fetch_censored"].to_numpy()}}
    return out


# --------------------------------------------------------------------------- input parsing

def _data_status(payload: dict | None, now: pd.Timestamp, max_age_h: float) -> tuple[str, str | None]:
    """(data_status, reason).  Anything but a fresh ``ready`` payload is not used (shadow honesty)."""
    payload = payload or {}
    status = payload.get("status")
    if status == "stale":
        return "stale", "stale_forecast"
    if status != "ready":
        return "unavailable", payload.get("reason") or "input_unavailable"
    ret = payload.get("retrieved_at")
    if ret:
        age_h = (now - _utc(ret)).total_seconds() / 3600.0
        if age_h > max_age_h:
            return "stale", "stale_forecast"
    return "fresh", None


def _hourly(payload: dict, key: str) -> pd.Series:
    hourly = payload.get("hourly") or {}
    times = pd.to_datetime(hourly.get("time") or [], errors="coerce")
    values = hourly.get(key)
    if values is None or len(times) == 0 or len(values) != len(times):
        return pd.Series(dtype=float)
    if getattr(times, "tz", None) is None:
        times = times.tz_localize(payload.get("timezone") or "UTC")
    s = pd.Series(pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(), index=times.tz_convert("UTC"))
    return s[~s.index.duplicated()].sort_index()


def make_record(*, issued_at, station: dict, hazard: str, window: tuple[pd.Timestamp, pd.Timestamp, int],
                config: dict, value=None, tier=None, inputs: dict | None = None, data_status: str = "fresh",
                skip_reason: str | None = None) -> dict:
    spec = config["hazards"].get(hazard, {})
    vf, vt, lead = window
    rec = {"issued_at": _iso(issued_at), "station": station["id"], "exposure_class": station.get("exposure_class"),
           "hazard": hazard, "valid_from": _iso(vf), "valid_to": _iso(vt), "lead_hours": lead,
           "value": None if value is None else (int(value) if hazard == "storm_wind" else round(float(value), 3)),
           "unit": spec.get("unit"),
           "tier": None if tier is None else int(tier),
           "action_vi": (spec.get("actions_vi") or {}).get(str(tier)) if tier else None,
           "inputs": inputs or {}, "data_status": data_status, "config_version": config.get("config_version"),
           **FLAGS}
    if skip_reason:
        rec.update({"tier": None, "value": None, "action_vi": None, "skip_reason": skip_reason})
    return rec


# --------------------------------------------------------------------------- hazard evaluators

def _wind_records(station, weather, now, issued_at, windows, config, max_age_h, mk) -> list[dict]:
    status, reason = _data_status(weather, now, max_age_h)
    base_in = {"source": "forecast", "model": (weather or {}).get("model") or FORECAST_MODEL}
    wind = _hourly(weather or {}, "wind_speed_10m") if status == "fresh" else pd.Series(dtype=float)
    direction = _hourly(weather or {}, "wind_direction_10m") if status == "fresh" else pd.Series(dtype=float)
    unit = ((weather or {}).get("hourly_units") or {}).get("wind_speed_10m", "km/h")
    profile = station.get("profile")
    out = []
    for hazard in ("storm_wind", "wave_height"):
        for w in windows:
            vf, vt, _ = w
            if status != "fresh":
                out.append(mk(hazard, w, data_status=status, skip_reason=reason, inputs=base_in))
                continue
            if hazard == "wave_height" and profile is None:
                out.append(mk(hazard, w, data_status=status, skip_reason="no_exposure_profile", inputs=base_in))
                continue
            sel = wind[(wind.index >= vf) & (wind.index < vt)].dropna()
            if sel.empty:
                out.append(mk(hazard, w, data_status=status, skip_reason="no_forecast_hours", inputs=base_in))
                continue
            try:
                ms = sel.map(lambda v: sa.to_ms(v, unit))
            except ValueError:
                out.append(mk(hazard, w, data_status=status, skip_reason="unknown_wind_unit", inputs=base_in))
                continue
            deg = direction.reindex(ms.index)
            if profile is None:  # open-water assumption: storm_wind only
                t_max = ms.idxmax()
                wd = None if pd.isna(deg.get(t_max)) else float(deg[t_max])
                level = sa.beaufort(float(ms.max()))
                inputs = {**base_in, "wind_dir_deg": wd, "max_wind_ms": round(float(ms.max()), 2),
                          "exposure_assumption": "open_water_no_exposure_data", "valid_at": _iso(t_max)}
                out.append(mk(hazard, w, value=level, inputs=inputs, tier=tier_for(hazard, level, config)))
                continue
            rows = []
            for t, v in ms.items():
                d = deg.get(t)
                if pd.isna(d):
                    continue
                ev = se.evaluate_site(float(v), float(d), profile)
                if ev.get("status") == "ok":
                    rows.append((t, float(v), float(d), ev))
            if not rows:
                out.append(mk(hazard, w, data_status=status, skip_reason="no_wind_direction", inputs=base_in))
                continue
            key = (lambda r: r[3]["local_wind_ms"]) if hazard == "storm_wind" else (lambda r: r[3]["hs_m"])
            t, v, d, ev = max(rows, key=key)
            idx = int(np.argmin(np.abs(((profile["bearing"] - d) + 180) % 360 - 180)))
            inputs = {**base_in, "wind_dir_deg": d, "open_wind_ms": round(v, 2), "valid_at": _iso(t),
                      "shelter_factor": round(ev["shelter_factor"], 3),
                      "exposure_run": station.get("exposure_run")}
            if hazard == "storm_wind":
                level = ev["local_beaufort"]
                out.append(mk(hazard, w, value=level, inputs={**inputs, "local_wind_ms": round(ev["local_wind_ms"], 2)},
                              tier=tier_for(hazard, level, config)))
            else:
                cens = profile.get("censored")
                inputs.update({"fetch_m": round(ev["fetch_m"]), "depth_m": round(ev["depth_m"], 1),
                               "fetch_censored": bool(cens[idx]) if cens is not None else None,
                               "wave_limited_by": ev["wave_limited_by"]})
                out.append(mk(hazard, w, value=ev["hs_m"], inputs=inputs, tier=tier_for(hazard, ev["hs_m"], config)))
    return out


def _run_tier(raw: pd.Series, hazard: str, config: dict, tiers: dict[int, int]) -> pd.Series:
    """Effective tier per day: tier k needs ``persistence_days[k]`` consecutive days with raw tier >= k."""
    spec = config["hazards"][hazard]
    persist = {int(k): int(v) for k, v in (spec.get("persistence_days") or {}).items()}
    out = []
    for i in range(len(raw)):
        eff = 0
        for k in sorted(tiers):
            need = persist.get(k, 1)
            if i + 1 >= need and (raw.iloc[i + 1 - need:i + 1] >= k).all():
                eff = k
        out.append(eff)
    return pd.Series(out, index=raw.index)


def _temperature_records(station, marine, now, issued_at, windows, config, max_age_h, mk) -> list[dict]:
    status, reason = _data_status(marine, now, max_age_h)
    base_in = {"source": "forecast", "model": (marine or {}).get("model") or "openmeteo_marine_default",
               "correction": "none", "variable": "sea_surface_temperature_raw"}
    daily = pd.Series(dtype=float)
    if status == "fresh":
        sst = _hourly(marine, "sea_surface_temperature")
        daily = hs.daily_from_hourly(sst) if not sst.dropna().empty else daily
        if not daily.empty:
            daily = daily.asfreq("D")
    out = []
    risk = dr.daily_disease_risk(daily) if len(daily.dropna()) else None
    for hazard in ("heat", "cold", "disease_env"):
        spec = config["hazards"].get(hazard, {})
        tiers = sorted(int(k) for k in spec.get("thresholds", {}))
        raw = None
        if hazard in ("heat", "cold") and len(daily):
            raw = daily.map(lambda v: np.nan if pd.isna(v) else tier_for(hazard, float(v), config))
            eff = _run_tier(raw.fillna(0), hazard, config, {k: 0 for k in tiers})
            eff = eff.where(raw.notna())
        for w in windows:
            vf, vt, _ = w
            if status != "fresh":
                out.append(mk(hazard, w, data_status=status, skip_reason=reason, inputs=base_in))
                continue
            # a local day belongs to the window when its midday falls inside it
            noon = daily.index.map(lambda d: pd.Timestamp(d).tz_localize(LOCAL_TZ).replace(hour=12).tz_convert("UTC"))
            m = (noon >= vf) & (noon < vt)
            days = daily[m].dropna()
            if days.empty:
                out.append(mk(hazard, w, data_status=status, skip_reason="no_complete_forecast_day", inputs=base_in))
                continue
            if hazard == "disease_env":
                idx = risk.loc[days.index, "index"].dropna()
                if idx.empty:
                    out.append(mk(hazard, w, data_status=status, skip_reason="no_valid_day", inputs=base_in))
                    continue
                d = idx.idxmax()
                out.append(mk(hazard, w, value=idx.max(), tier=tier_for(hazard, float(idx.max()), config),
                              inputs={**base_in, "date": d.date().isoformat(), "temp_c": round(float(days[d]), 2),
                                      "rain": "not_used"}))
                continue
            e = eff.loc[days.index]
            d = e.idxmax()
            val = days.max() if hazard == "heat" else days.min()
            vd = days.idxmax() if hazard == "heat" else days.idxmin()
            persist = (spec.get("persistence_days") or {})
            out.append(mk(hazard, w, value=val, tier=int(e.max()),
                          inputs={**base_in, "date": vd.date().isoformat(), "forecast_days_available": int(daily.notna().sum()),
                                  "persistence_days": persist, "persistence_basis": "forecast_days_only"}))
    return out


def evaluate_station(station: dict, weather: dict | None, marine: dict | None, *, now, config: dict,
                     max_age_hours: float = MAX_AGE_HOURS) -> list[dict]:
    """C2 records for one station.  ``station`` = {id, lat, lon, exposure_class, profile}."""
    now = _utc(now)
    issued_at = now
    start = now.floor("h")
    windows = [(start + pd.Timedelta(hours=a), start + pd.Timedelta(hours=b), a) for a, b in LEAD_WINDOWS_H]

    def mk(hazard, w, **kw):
        if station.get("exposure_class") is None:
            kw["inputs"] = {**(kw.get("inputs") or {}), "exposure_class_assumption": "unknown_open_water"}
        return make_record(issued_at=issued_at, station=station, hazard=hazard, window=w, config=config, **kw)

    out = _wind_records(station, weather, now, issued_at, windows, config, max_age_hours, mk)
    out += _temperature_records(station, marine, now, issued_at, windows, config, max_age_hours, mk)
    ctx = {"now": now, "config": config, "issued_at": issued_at, "windows": windows}
    for fn in HAZARD_HOOKS.values():
        out += fn(station, ctx)
    return out


# --------------------------------------------------------------------------- live fetch + ledger

def _get_json(url: str, params: dict, timeout: int = 15) -> dict:
    from urllib.parse import urlencode
    from urllib.request import urlopen
    with urlopen(f"{url}?{urlencode(params)}", timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_forecast(station: dict) -> dict:
    """Open-Meteo forecast for one station, model named (decisions #18); never raises."""
    try:
        d = _get_json(OPEN_METEO_URL, {"latitude": station["lat"], "longitude": station["lon"],
                                       "hourly": "wind_speed_10m,wind_direction_10m", "models": FORECAST_MODEL,
                                       "forecast_days": 6, "wind_speed_unit": "ms", "timezone": "UTC"})
    except Exception as exc:
        return {"status": "unavailable", "reason": "provider_request_failed", "detail": str(exc)}
    h = d.get("hourly", {})
    # models= suffixes variable names for some deployments; accept either spelling
    for k in ("wind_speed_10m", "wind_direction_10m"):
        if k not in h:
            alt = f"{k}_{FORECAST_MODEL}"
            if alt in h:
                h[k] = h[alt]
    return {"status": "ready", "provider": "open_meteo", "model": FORECAST_MODEL, "timezone": "UTC",
            "retrieved_at": datetime.now(timezone.utc).isoformat(), "hourly": h,
            "hourly_units": {"wind_speed_10m": "m/s"}}


def fetch_marine(station: dict) -> dict:
    from core.config import MARINE_ENABLED
    if not MARINE_ENABLED:
        return {"status": "disabled", "reason": "marine_disabled"}
    try:
        d = _get_json(OPEN_METEO_MARINE_URL, {"latitude": station["lat"], "longitude": station["lon"],
                                              "hourly": "sea_surface_temperature", "forecast_days": 6,
                                              "timezone": "UTC", "cell_selection": "sea"})
    except Exception as exc:
        return {"status": "unavailable", "reason": "provider_request_failed", "detail": str(exc)}
    return {"status": "ready", "provider": "open_meteo_marine", "model": "openmeteo_marine_default",
            "timezone": "UTC", "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "hourly": d.get("hourly", {}), "hourly_units": d.get("hourly_units", {})}


def append_records(records: list[dict], out_dir: Path, day: str) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"hazard_{day}.jsonl"
    with path.open("a", encoding="utf-8", newline="\n") as fh:  # append-only, never rewritten
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n")
    return path


def run_once(now=None, out_dir=None, *, stations: list[dict] | None = None, fetch_weather=fetch_forecast,
             fetch_marine_fn=fetch_marine, config_loader=load_effective) -> dict:
    """Evaluate every station once and append to the day's ledger.  Returns a small summary."""
    now = _utc(now if now is not None else datetime.now(timezone.utc))
    out_dir = Path(out_dir) if out_dir is not None else paths.HAZARD_SHADOW_DIR
    stations = stations if stations is not None else load_stations()
    records = []
    for st in stations:
        cfg = config_loader(st["id"], st.get("exposure_class"))
        records += evaluate_station(st, fetch_weather(st), fetch_marine_fn(st), now=now, config=cfg)
    path = append_records(records, out_dir, now.strftime("%Y%m%d"))
    return {"path": str(path), "n_records": len(records), "n_skipped": sum(1 for r in records if r.get("skip_reason")),
            "stations": len(stations)}
