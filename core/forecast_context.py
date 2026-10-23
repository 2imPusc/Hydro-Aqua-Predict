"""External context for the long-horizon shadow forecasts (B5 weather, B6 tide).

B5: only ``captured_live`` snapshots from the hourly collector are used, with
the ``join_as_issued`` rule of the research code (snapshot for the valid hour,
``retrieved_at <= origin``, age <= 24 h, latest retrieval wins).  Reconstructed
or legacy rows without provenance are never read at runtime.

B6: Open-Meteo Marine ``sea_level_height_msl`` from ``core.weather`` (its TTL
cache and ``MARINE_ENABLED`` gate apply).  Any gap gives a skip with a reason,
never a filled value.  Neither source drives alerts.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from core import paths
from core.weather import get_station_environment

WEATHER_SNAPSHOTS = paths.EXPERIMENT_OUTPUT_DIR / "forecast-v2" / "weather-snapshots.jsonl"
WEATHER_FIELDS = ("cloud_cover", "precipitation", "relative_humidity_2m", "surface_pressure", "temperature_2m", "wind_direction_10m", "wind_speed_10m")
MAX_AGE = pd.Timedelta(hours=24)
TIDE_VARIABLE = "sea_level_height_msl"
TIDE_HISTORY_HOURS = 24
_TIDE_HISTORY: dict[str, pd.DataFrame] = {}


class CapturedLiveWeather:
    """Parsed ``captured_live`` snapshots, re-read only when the file changes."""

    def __init__(self, path: Path = WEATHER_SNAPSHOTS):
        self.path = Path(path)
        self._signature: tuple | None = None
        self._frame = pd.DataFrame()

    def _load(self) -> pd.DataFrame:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            self._signature, self._frame = None, pd.DataFrame()
            return self._frame
        signature = (stat.st_size, stat.st_mtime_ns)
        if signature == self._signature:
            return self._frame
        rows = []
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                if '"captured_live"' not in line:
                    continue
                record = json.loads(line)
                if record.get("provenance_class") != "captured_live":
                    continue
                rows.append({
                    "station": record.get("station"), "location_id": record.get("location_id"),
                    "valid_at": record.get("valid_at"), "retrieved_at": record.get("retrieved_at"),
                    "issued_at": record.get("issued_at"), "provider": record.get("provider"), "product": record.get("product"),
                    "raw_payload_hash": record.get("raw_payload_hash"), "snapshot_id": record.get("snapshot_id"),
                    **{f"external_{name}": (record.get("features") or {}).get(name) for name in WEATHER_FIELDS},
                })
        frame = pd.DataFrame(rows)
        if not frame.empty:
            for column in ("valid_at", "retrieved_at"):
                frame[column] = pd.to_datetime(frame[column], utc=True)
            frame["valid_bucket"] = frame["valid_at"].dt.floor("h")
            frame = frame.sort_values("retrieved_at", kind="stable").reset_index(drop=True)
        self._signature, self._frame = signature, frame
        return frame

    def features_at(self, issued_at: pd.Timestamp, valid_at: pd.Timestamp, station: str, location_id: str) -> dict:
        frame = self._load()
        if frame.empty:
            return {"status": "skip", "reason": "no_captured_live_snapshot_within_24h", "latest_retrieved_at": None}
        site = frame[(frame["station"] == station) & (frame["location_id"] == location_id) & (frame["retrieved_at"] <= issued_at)]
        recent = site[site["retrieved_at"] >= issued_at - MAX_AGE]
        if recent.empty:
            latest = site["retrieved_at"].max() if not site.empty else None
            return {"status": "skip", "reason": "no_captured_live_snapshot_within_24h", "latest_retrieved_at": None if latest is None else latest.isoformat()}
        match = recent[recent["valid_bucket"] == pd.Timestamp(valid_at).floor("h")]
        if match.empty:
            return {"status": "skip", "reason": "snapshot_missing_valid_hour", "latest_retrieved_at": recent["retrieved_at"].max().isoformat()}
        row = match.iloc[-1]
        features = {f"external_{name}": row[f"external_{name}"] for name in WEATHER_FIELDS}
        if any(value is None or (isinstance(value, float) and math.isnan(value)) for value in features.values()):
            return {"status": "skip", "reason": "snapshot_feature_missing", "snapshot_id": row["snapshot_id"]}
        return {
            "status": "ok",
            "features": {name: float(value) for name, value in features.items()},
            "provenance": {
                "provenance_class": "captured_live", "provider": row["provider"], "product": row["product"],
                "retrieved_at": row["retrieved_at"].isoformat(), "valid_at": row["valid_at"].isoformat(),
                "snapshot_id": row["snapshot_id"], "raw_payload_hash": row["raw_payload_hash"],
                "age_hours": round((issued_at - row["retrieved_at"]).total_seconds() / 3600, 4),
                "source_file": str(self.path.name),
            },
        }


def tide_series_from_marine(marine: dict) -> tuple[pd.DataFrame, dict]:
    hourly = marine.get("hourly") or {}
    times = pd.to_datetime(pd.Series(hourly.get("time", [])), errors="coerce")
    zone = marine.get("timezone") or "Asia/Ho_Chi_Minh"
    if len(times) and times.dt.tz is None:
        times = times.dt.tz_localize(zone)
    levels = pd.to_numeric(pd.Series(hourly.get(TIDE_VARIABLE, [None] * len(times)), dtype=object), errors="coerce")
    series = pd.DataFrame({"valid_at": times.dt.tz_convert("UTC") if len(times) else times, "sea_level_m": levels}).dropna()
    provenance = {
        "provider": marine.get("provider"), "variable": TIDE_VARIABLE, "retrieved_at": marine.get("retrieved_at"),
        "model": marine.get("model"), "cache": marine.get("cache"), "marine_status": marine.get("status"),
        "location": (marine.get("location") or {}).get("source"),
    }
    return series.reset_index(drop=True), provenance


def marine_tide(station_serial: str, weather: dict | None) -> dict:
    """Sea-level forecast for B6 or a skip reason (never raises)."""
    try:
        marine = (get_station_environment(station_serial, weather=weather) or {}).get("marine") or {}
    except Exception as exc:  # defensive: context must never break the runner
        return {"status": "skip", "reason": "marine_request_error", "detail": str(exc)}
    if marine.get("status") not in {"ready", "stale"}:
        return {"status": "skip", "reason": marine.get("reason") or "marine_unavailable", "marine_status": marine.get("status")}
    series, provenance = tide_series_from_marine(marine)
    if series.empty:
        return {"status": "skip", "reason": "sea_level_missing", "marine_status": marine.get("status")}
    # The provider forecast starts at local midnight, so tide_slope_1h (issue - 1 h)
    # is out of range in the first local hour.  Keep earlier hours from previous
    # retrievals in this process (newest retrieval wins where they overlap).
    previous = _TIDE_HISTORY.get(station_serial)
    if previous is not None:
        older = previous[previous["valid_at"] < series["valid_at"].min()]
        older = older[older["valid_at"] >= series["valid_at"].min() - pd.Timedelta(hours=TIDE_HISTORY_HOURS)]
        provenance["earlier_hours_from_previous_retrieval"] = int(len(older))
        series = pd.concat([older, series], ignore_index=True)
    _TIDE_HISTORY[station_serial] = series
    return {"status": "ok", "series": series, "provenance": provenance}
