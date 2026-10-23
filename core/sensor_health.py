"""Causal sensor-health checks for realtime alerting.

These checks identify questionable observations; they never replace a reading
or declare a water-quality incident by themselves.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable

import numpy as np
import pandas as pd

from core.quality import is_in_range


DEFAULT_METRICS = ("DO", "Temperature", "NH3", "TSS")


def _as_number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _mad(values: np.ndarray) -> float:
    return float(np.median(np.abs(values - np.median(values))))


def _flatline(values: pd.Series, run: int = 10) -> bool:
    observed = values.dropna().to_numpy(dtype=float)
    if len(observed) < run:
        return False
    return bool(np.all(observed[-run:] == observed[-1]))


def _hampel_spike(values: pd.Series, window: int = 15, k: float = 3.5) -> bool:
    observed = values.dropna().to_numpy(dtype=float)
    if len(observed) < 11:
        return False
    history = observed[-(window + 1):-1]
    median = float(np.median(history))
    mad = _mad(history)
    if mad == 0:
        return False
    return abs(observed[-1] - median) / (1.4826 * mad) > k


def _cusum_shift(values: pd.Series, k: float = 0.5, h: float = 8.0) -> bool:
    observed = values.dropna().to_numpy(dtype=float)
    if len(observed) < 12:
        return False
    baseline = observed[:-1]
    mad = _mad(baseline)
    if mad == 0:
        return False
    z = (baseline - np.median(baseline)) / (1.4826 * mad)
    positive = negative = 0.0
    for value in z:
        positive = max(0.0, positive + value - k)
        negative = max(0.0, negative - value - k)
    latest_z = (observed[-1] - np.median(baseline)) / (1.4826 * mad)
    return max(0.0, positive + latest_z - k) > h or max(0.0, negative - latest_z - k) > h


def assess_sensor_health(
    history_df: pd.DataFrame,
    metrics: Iterable[str] = DEFAULT_METRICS,
    expected_interval_minutes: int = 3,
) -> Dict[str, Any]:
    """Return causal health flags for the latest observation of each metric."""
    if history_df.empty:
        return {"overall_status": "missing", "metrics": {}, "data_completeness": 0.0}

    df = history_df.copy()
    if "fetchedAt" in df.columns:
        df["fetchedAt"] = pd.to_datetime(df["fetchedAt"], utc=True)
        df = df.sort_values("fetchedAt")

    metric_result: Dict[str, Dict[str, Any]] = {}
    problematic = False
    for metric in metrics:
        if metric not in df.columns:
            metric_result[metric] = {"status": "unavailable", "flags": ["not_provided"]}
            continue
        values = pd.to_numeric(df[metric], errors="coerce")
        latest = _as_number(values.iloc[-1])
        flags = []
        if latest is None:
            flags.append("missing")
        elif not is_in_range(metric, latest):
            flags.append("out_of_range")
        else:
            if _flatline(values):
                flags.append("flatline")
            if _hampel_spike(values):
                flags.append("hampel_spike")
            if _cusum_shift(values):
                flags.append("level_shift")
        status = "valid" if not flags else ("invalid" if flags[0] in {"missing", "out_of_range"} else "suspect")
        problematic |= status in {"invalid", "suspect"}
        metric_result[metric] = {"status": status, "flags": flags, "latest_value": latest}

    gap = False
    if "fetchedAt" in df.columns and len(df) >= 2:
        gap = df["fetchedAt"].iloc[-1] - df["fetchedAt"].iloc[-2] > pd.Timedelta(minutes=expected_interval_minutes * 2)
    completeness = float(df[list(set(metrics) & set(df.columns))].notna().mean().mean()) if set(metrics) & set(df.columns) else 0.0
    return {
        "overall_status": "degraded" if problematic or gap else "valid",
        "metrics": metric_result,
        "data_gap": gap,
        "data_completeness": round(completeness, 3),
    }
