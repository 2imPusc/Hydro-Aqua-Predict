"""Safety gates shared by realtime and shadow execution paths.

The lab can replay historical/cache data, but a replay must never be mistaken
for a live forecast.  This module keeps that distinction explicit and makes
the freshness decision deterministic for both the Streamlit pipeline and the
one-minute shadow runner.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from core.config import STATIONS


STALE_SOURCE_MARKERS = {"local_csv_fallback", "greenlab_api_cache_stale"}
DEFAULT_EXPECTED_CADENCE_MINUTES = 3
DEFAULT_MAX_STALENESS_MINUTES = 10


def _now_utc(now: datetime | pd.Timestamp | None = None) -> pd.Timestamp:
    if now is None:
        return pd.Timestamp.now(tz="UTC")
    return pd.Timestamp(now).tz_localize("UTC") if pd.Timestamp(now).tzinfo is None else pd.Timestamp(now).tz_convert("UTC")


def station_freshness_policy(station_serial: str) -> dict[str, int]:
    """Return the configured cadence and live freshness budget for a station."""
    station = STATIONS.get(station_serial, {})
    cadence = int(station.get("expected_cadence_minutes", DEFAULT_EXPECTED_CADENCE_MINUTES))
    configured_max = station.get("max_staleness_minutes")
    maximum = int(configured_max if configured_max is not None else max(DEFAULT_MAX_STALENESS_MINUTES, cadence * 3))
    return {"expected_cadence_minutes": max(1, cadence), "max_staleness_minutes": max(1, maximum)}


def assess_sensor_freshness(
    raw: pd.DataFrame,
    station_serial: str,
    *,
    now: datetime | pd.Timestamp | None = None,
    replay: bool = False,
) -> dict[str, Any]:
    """Assess whether *raw* is safe for issuing a new realtime forecast.

    Replay mode intentionally reports the same age but does not block.  A
    stale/fallback source is still labelled explicitly so callers can keep it
    out of operational metrics and alerts.
    """
    policy = station_freshness_policy(station_serial)
    source = str(raw.attrs.get("data_source", "unknown")) if hasattr(raw, "attrs") else "unknown"
    if raw is None or raw.empty or "fetchedAt" not in raw.columns:
        return {
            "status": "missing",
            "reason": "sensor_history_missing",
            "station_serial": station_serial,
            "data_source": source,
            "replay": bool(replay),
            **policy,
        }

    timestamps = pd.to_datetime(raw["fetchedAt"], utc=True, errors="coerce").dropna()
    if timestamps.empty:
        return {
            "status": "missing",
            "reason": "sensor_timestamp_missing",
            "station_serial": station_serial,
            "data_source": source,
            "replay": bool(replay),
            **policy,
        }

    latest = timestamps.max()
    age_minutes = max(0.0, (_now_utc(now) - latest).total_seconds() / 60.0)
    stale_source = source in STALE_SOURCE_MARKERS
    future_observation = latest > _now_utc(now) + pd.Timedelta(minutes=2)
    stale = stale_source or future_observation or age_minutes > policy["max_staleness_minutes"]
    if future_observation:
        reason = "sensor_timestamp_in_future"
    elif stale_source:
        reason = "fallback_source_not_live"
    elif age_minutes > policy["max_staleness_minutes"]:
        reason = "sensor_data_stale"
    else:
        reason = None
    return {
        "status": "replay" if replay else ("stale" if stale else "fresh"),
        "reason": reason,
        "station_serial": station_serial,
        "data_source": source,
        "latest_observed_at": latest.isoformat(),
        "age_minutes": round(age_minutes, 3),
        "replay": bool(replay),
        **policy,
    }


def blocked_forecast(reason: str, freshness: dict[str, Any] | None = None) -> dict[str, Any]:
    """Stable payload used when a forecast cannot be issued safely."""
    return {
        "status": "blocked",
        "reason": reason,
        "freshness": freshness or {},
        "timeline": [],
        "used_by_alerts": False,
        "used_by_suitability": False,
    }
