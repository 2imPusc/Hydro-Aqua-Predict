"""Basin storm watch from ensemble tropical-cyclone track forecasts (theory only, shadow).

Input is a flat table of member track fixes (``TRACK_COLUMNS``), decoded from ECMWF Open Data
"tf" BUFR files by ``experiments/ecmwf_opendata.py`` or taken from the TIGGE CXML extracts of
``experiments/tigge_tracks.py`` (same ``member``/``hour``/``lat``/``lon`` columns).  This module
needs no BUFR decoder.

Probability rule = ``experiments/storm_basin.tigge_eval`` exactly, so the thresholds evaluated in
``docs/eval/2026-10-23-storm-basin.md`` apply: P(within R km in H h) = share of members with at
least one forecast fix ``0 < hour <= H`` at distance ``<= R`` from the site; the denominator is the
number of distinct members carrying that storm.  Fixes are used as given (6-hourly), without
interpolation, as in the evaluation.

Storms with an analysed position (numbered / named, e.g. ``36W``) are summarised per storm.
Tracks with ids ``7xX`` that start at hour 0 on an observed storm (same member, <= 300 km) are
that storm repeated by the tracker and are merged into it (``merge_duplicate_tracks``).  The remaining
7xX tracks are forecast genesis, numbered per member, so the same id in two members is not the same
system: they are pooled into one ``genesis`` entry (share of the whole
ensemble with any genesis track entering R) and never drive the watch tier, because the
evaluation only scored storms present at the base time.

Every record carries ``used_by_alerts: False``, ``notification_eligible: False`` and
``basis: "theory_only_unvalidated"``.  The watch never escalates into a warning by itself.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from core import paths
from core.storm_advisory import haversine_km

HAZARD_ID = "storm_watch"
SOURCE = "ecmwf_opendata"
MODEL = "ecmwf_ifs_ens_tc_tracks"
TRACK_COLUMNS = ["storm_id", "name", "member", "hour", "lat", "lon", "observed", "pmin_hpa", "vmax_ms"]
RADII = (200.0, 500.0)
HORIZONS = (24, 48, 72, 96, 120)
WATCH_RADIUS_KM = 500.0
WATCH_HORIZON_H = 120
ENSEMBLE_SIZE = 51  # control + 50 perturbed members
MIN_TRACK_MEMBER_SHARE = 0.5  # median track stops when fewer members still carry the storm
TRACK_MAX_H = 240
MERGE_RADIUS_KM = 300.0  # same t0 tolerance as storm_basin.match_tigge
STALE_AFTER_H = 36.0  # ENS runs every 12 h; older than 36 h = at least two runs missed
FLAGS = {"used_by_alerts": False, "notification_eligible": False, "basis": "theory_only_unvalidated"}


def _iso(ts) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ") if pd.Timestamp(ts).tzinfo \
        else pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(value) -> pd.Timestamp:
    t = pd.Timestamp(value)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _clean(tracks: pd.DataFrame) -> pd.DataFrame:
    df = tracks.copy()
    df["hour"] = pd.to_numeric(df["hour"], errors="coerce")
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df = df.dropna(subset=["hour", "lat", "lon"])
    df = df[(df["lat"].abs() <= 90) & (df["lon"].abs() <= 360)]
    return df


def _distances(df: pd.DataFrame, site_lat: float, site_lon: float) -> np.ndarray:
    return haversine_km(df["lat"].to_numpy(float), df["lon"].to_numpy(float), site_lat, site_lon)


def member_probabilities(tracks: pd.DataFrame, site_lat: float, site_lon: float, radii=RADII, horizons=HORIZONS,
                         n_members: int | None = None) -> dict:
    """``{"p<R>_<H>": share, "n_members": n}`` for one storm (storm_basin.tigge_eval rule)."""
    df = _clean(tracks)
    n = int(n_members) if n_members else int(df["member"].nunique())
    out: dict = {"n_members": n}
    d = _distances(df, site_lat, site_lon) if len(df) else np.array([])
    for radius in radii:
        for h in horizons:
            if n == 0 or not len(df):
                out[f"p{int(radius)}_{h}"] = 0.0
                continue
            m = (df["hour"].to_numpy() > 0) & (df["hour"].to_numpy() <= h) & (d <= radius)
            out[f"p{int(radius)}_{h}"] = df.loc[m, "member"].nunique() / n
    return out


def _wrap(lon: np.ndarray, ref: float) -> np.ndarray:
    return ((np.asarray(lon, float) - ref + 180.0) % 360.0) - 180.0 + ref


def _norm180(lon: float) -> float:
    v = ((lon + 180.0) % 360.0) - 180.0
    return 180.0 if v == -180.0 and lon > 0 else v


def median_track(tracks: pd.DataFrame, run_time, n_members: int, max_h: int = TRACK_MAX_H,
                 min_share: float = MIN_TRACK_MEMBER_SHARE) -> list[list]:
    """``[[lon, lat, valid_time_iso], ...]`` member median per forecast hour (lon in -180..180)."""
    df = _clean(tracks)
    df = df[df["hour"] <= max_h].drop_duplicates(["member", "hour"])  # merged duplicate tracks: first row wins
    if df.empty or n_members <= 0:
        return []
    t0 = _ts(run_time)
    first = np.radians(df.loc[df["hour"] == df["hour"].min(), "lon"].to_numpy(float))
    ref = float(np.degrees(np.arctan2(np.sin(first).mean(), np.cos(first).mean())))  # circular mean: dateline-safe
    df = df.assign(lon_u=_wrap(df["lon"].to_numpy(), ref))
    out = []
    for h, g in df.groupby("hour", sort=True):
        if g["member"].nunique() < min_share * n_members:
            break
        lon = _norm180(float(np.median(g["lon_u"])))
        out.append([round(lon, 3), round(float(np.median(g["lat"])), 3), _iso(t0 + pd.Timedelta(hours=float(h)))])
    return out


def summarize_storm(tracks: pd.DataFrame, site_lat: float, site_lon: float, run_time, n_members: int | None = None,
                    horizon_h: int = WATCH_HORIZON_H, eta_radius_km: float = WATCH_RADIUS_KM) -> dict:
    """Contract C3 storm entry for one storm (all rows share one ``storm_id``)."""
    df = _clean(tracks)
    probs = member_probabilities(df, site_lat, site_lon, n_members=n_members)
    n = probs["n_members"]
    df = df.assign(d=_distances(df, site_lat, site_lon)) if len(df) else df.assign(d=[])
    win = df[df["hour"] <= horizon_h]
    closest = win.groupby("member")["d"].min() if len(win) else pd.Series(dtype=float)
    inside = win[(win["hour"] > 0) & (win["d"] <= eta_radius_km)]
    eta = inside.groupby("member")["hour"].min() if len(inside) else pd.Series(dtype=float)
    name = None
    if "name" in df and df["name"].notna().any():
        name = str(df["name"].dropna().iloc[0]).strip() or None
    sid = str(df["storm_id"].iloc[0]).strip() if "storm_id" in df and len(df) else None
    vmax = pd.to_numeric(df.loc[df["hour"] == 0, "vmax_ms"], errors="coerce") if "vmax_ms" in df else pd.Series(dtype=float)
    pmin = pd.to_numeric(df.loc[df["hour"] == 0, "pmin_hpa"], errors="coerce") if "pmin_hpa" in df else pd.Series(dtype=float)
    return {
        "id": sid,
        "name": name or sid,
        "run_time": _iso(_ts(run_time)),
        "members": n,
        "p_within_500km_120h": round(float(probs["p500_120"]), 4),
        "p_within_200km_120h": round(float(probs["p200_120"]), 4),
        "probabilities": {k: round(float(v), 4) for k, v in probs.items() if k.startswith("p")},
        "closest_approach_km_median": round(float(closest.median()), 1) if len(closest) else None,
        "eta_hours_median": float(eta.median()) if len(eta) else None,
        "eta_members": int(len(eta)),
        "eta_basis": f"first forecast fix within {int(eta_radius_km)} km, members that enter within {horizon_h} h",
        "t0_vmax_ms_median": round(float(vmax.median()), 1) if vmax.notna().any() else None,
        "t0_pmin_hpa_median": round(float(pmin.median()), 1) if pmin.notna().any() else None,
        "track_median": median_track(df, run_time, n),
    }


def merge_duplicate_tracks(tracks: pd.DataFrame, max_km: float = MERGE_RADIUS_KM) -> pd.DataFrame:
    """Relabel a member's unobserved track (id 7xX) as an observed storm when both start at hour 0
    within ``max_km`` of each other in that member.

    ECMWF tf files repeat observed storms under 7xX ids (2026-10-23 00 UTC: 70W == 36W CHAMPI fix for
    fix in all 51 members).  storm_basin.match_tigge does the same union for TIGGE: every disturbance
    whose t0 lies within 300 km of the best-track position counts as that storm.  Observed rows are
    sorted first so de-duplication on (member, hour) keeps them.
    """
    if tracks.empty or "observed" not in tracks or tracks["observed"].astype(bool).all():
        return tracks
    df = tracks.copy()
    df["observed"] = df["observed"].astype(bool)
    df["_orig"] = df["storm_id"]
    t0 = df[df["hour"] == 0]
    obs0 = t0[t0["observed"]]
    for (member, sid), g in t0[~t0["observed"]].groupby(["member", "storm_id"]):
        cand = obs0[obs0["member"] == member]
        if cand.empty:
            continue
        d = haversine_km(cand["lat"].to_numpy(float), cand["lon"].to_numpy(float),
                         float(g["lat"].iloc[0]), float(g["lon"].iloc[0]))
        i = int(np.argmin(d))
        if d[i] <= max_km:
            sel = (df["member"] == member) & (df["_orig"] == sid) & ~df["observed"]
            df.loc[sel, ["storm_id", "name", "observed"]] = [cand["storm_id"].iloc[i], cand["name"].iloc[i], True]
            df.loc[sel, "merged_from"] = sid
    df["_rank"] = df["merged_from"].notna().astype(int) if "merged_from" in df else 0
    df = df.sort_values(["storm_id", "member", "hour", "_rank"], kind="stable").drop(columns=["_orig", "_rank"])
    return df.reset_index(drop=True)


def summarize_run(tracks: pd.DataFrame, site_lat: float, site_lon: float, run_time,
                  ensemble_size: int = ENSEMBLE_SIZE) -> dict:
    """All storms of one ensemble run relative to one site.

    ``storms``: observed storms sorted by P(500 km, 120 h) desc.  ``genesis``: pooled forecast-genesis
    tracks (share of ``ensemble_size``).  ``max_p_within_500km_120h`` / ``driving_storm`` use observed
    storms only (the evaluated quantity).
    """
    df = merge_duplicate_tracks(_clean(tracks)) if len(tracks) else pd.DataFrame(columns=TRACK_COLUMNS)
    obs_mask = df["observed"].astype(bool) if "observed" in df and len(df) else pd.Series(True, index=df.index)
    storms = [summarize_storm(g, site_lat, site_lon, run_time) for _, g in df[obs_mask].groupby("storm_id", sort=True)]
    storms.sort(key=lambda s: (-s["p_within_500km_120h"], -s["p_within_200km_120h"], s["id"] or ""))
    gen = df[~obs_mask]
    genesis = {"n_member_tracks": int(gen.groupby(["member", "storm_id"]).ngroups) if len(gen) else 0,
               "ensemble_size": ensemble_size,
               "note": "forecast-genesis tracks pooled; ids are per member, not one system; not used for the tier"}
    gp = member_probabilities(gen, site_lat, site_lon, n_members=ensemble_size) if len(gen) else {}
    genesis["p_within_500km_120h"] = round(float(gp.get("p500_120", 0.0)), 4)
    genesis["p_within_200km_120h"] = round(float(gp.get("p200_120", 0.0)), 4)
    top = storms[0] if storms else None
    return {"run_time": _iso(_ts(run_time)), "site": {"lat": site_lat, "lon": site_lon}, "storms": storms,
            "genesis": genesis,
            "max_p_within_500km_120h": top["p_within_500km_120h"] if top else 0.0,
            "max_p_within_200km_120h": max((s["p_within_200km_120h"] for s in storms), default=0.0),
            "driving_storm": top["id"] if top and top["p_within_500km_120h"] > 0 else None}


# --------------------------------------------------------------------------- tiers (contract C1)
def load_alert_config(station_id: str | None = None, exposure_class: str | None = None) -> dict:
    """Effective config via ``core.alert_config`` (Track A) when present, else the tracked defaults."""
    try:
        from core import alert_config  # type: ignore
        return alert_config.load_effective(station_id=station_id, exposure_class=exposure_class)
    except (ImportError, AttributeError):
        return json.loads(paths.ALERT_CONFIG_DEFAULT.read_text(encoding="utf-8"))


def watch_tier(value: float | None, config: dict) -> int | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        from core import alert_config  # type: ignore
        return int(alert_config.tier_for(HAZARD_ID, float(value), config))
    except (ImportError, AttributeError):
        pass
    hz = config["hazards"][HAZARD_ID]
    ge = hz.get("direction", "ge") == "ge"
    tier = 0
    for k, thr in sorted(hz["thresholds"].items(), key=lambda kv: int(kv[0])):
        if (value >= thr) if ge else (value <= thr):
            tier = int(k)
    return tier


def watch_record(station: dict, summary: dict | None, config: dict, run_time, issued_at=None,
                 inputs: dict | None = None, skip_reason: str | None = None) -> dict:
    """One C2 ledger record (hazard ``storm_watch``) for one station and one ensemble run."""
    issued = _ts(issued_at) if issued_at is not None else pd.Timestamp(datetime.now(timezone.utc))
    hz = config["hazards"][HAZARD_ID]
    base = {"issued_at": _iso(issued), "station": station["id"], "exposure_class": station.get("exposure_class"),
            "hazard": HAZARD_ID, "lead_hours": WATCH_HORIZON_H, "unit": hz.get("unit", "xác suất"),
            "config_version": config.get("config_version")}
    rec_inputs = {"source": SOURCE, "model": MODEL, "metric": hz.get("metric", "p_within_500km_120h"),
                  **(inputs or {})}
    if summary is None or skip_reason:
        return {**base, "valid_from": _iso(_ts(run_time)) if run_time else None,
                "valid_to": _iso(_ts(run_time) + pd.Timedelta(hours=WATCH_HORIZON_H)) if run_time else None,
                "value": None, "tier": None, "action_vi": None, "skip_reason": skip_reason or "no_summary",
                "inputs": rec_inputs, "data_status": "unavailable", **FLAGS}
    t0 = _ts(run_time)
    age_h = (issued - t0).total_seconds() / 3600.0
    value = float(summary["max_p_within_500km_120h"])
    tier = watch_tier(value, config)
    action = hz.get("actions_vi", {}).get(str(tier)) if tier else None
    rec_inputs.update({"run_time": _iso(t0), "run_age_hours": round(age_h, 1), "storm_id": summary["driving_storm"],
                       "p_within_200km_120h": summary["max_p_within_200km_120h"],
                       "storms": [{"id": s["id"], "p500": s["p_within_500km_120h"], "p200": s["p_within_200km_120h"]}
                                  for s in summary["storms"] if s["p_within_500km_120h"] > 0],
                       "genesis_p_within_500km_120h": summary["genesis"]["p_within_500km_120h"],
                       "n_observed_storms": len(summary["storms"])})
    return {**base, "valid_from": _iso(t0), "valid_to": _iso(t0 + pd.Timedelta(hours=WATCH_HORIZON_H)),
            "value": round(value, 4), "tier": tier, "action_vi": action, "inputs": rec_inputs,
            "data_status": "fresh" if age_h <= STALE_AFTER_H else "stale", **FLAGS}


__all__ = ["TRACK_COLUMNS", "member_probabilities", "median_track", "summarize_storm", "summarize_run",
           "load_alert_config", "watch_tier", "watch_record"]
