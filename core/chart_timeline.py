"""Time-safe helpers for joining observed and forecast chart traces."""
from __future__ import annotations

from typing import Iterable

import pandas as pd


def bridge_forecast_from_current(
    future_timestamps: Iterable[object],
    future_values: Iterable[object],
    *,
    current_timestamp: object | None,
    current_value: object | None,
    max_bridge_minutes: int = 5,
) -> tuple[list[pd.Timestamp], list[object], bool]:
    """Prefix forecast with the observed current point only when contiguous.

    The bridge is a charting aid, not an interpolated forecast.  It is omitted
    for stale/missing observations so the UI keeps genuine temporal gaps
    visible.
    """
    timestamps = [pd.to_datetime(value, utc=True) for value in future_timestamps]
    values = list(future_values)
    if not timestamps or current_timestamp is None or current_value is None or pd.isna(current_value):
        return timestamps, values, False
    current = pd.to_datetime(current_timestamp, utc=True)
    gap = timestamps[0] - current
    if pd.Timedelta(0) < gap <= pd.Timedelta(minutes=max_bridge_minutes):
        return [current, *timestamps], [current_value, *values], True
    return timestamps, values, False
