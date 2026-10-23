"""Canonical observation contract for realtime sensor and lab data.

The running pipeline still consumes a wide dataframe for backwards
compatibility.  This module is the lossless adapter to the long-form contract
used for provenance, QC and future ground-truth evaluation.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd

from core.config import NH4_CONVERSION_CONFIRMED, NH4_UNIT_SCALE, STATIONS
from core.quality import is_in_range


CONTRACT_VERSION = "1.0"
RAW_METRICS = ("COD", "NH4", "pH", "Temperature", "TSS", "DO")
REQUIRED_COLUMNS = (
    "observation_id", "observed_at", "station_serial", "metric", "value",
    "unit", "source_type", "qc_status", "ingested_at", "provenance",
)


def station_units(station_serial: str) -> dict[str, str]:
    """Return declared hardware units; unknown stations deliberately have no unit."""
    station = STATIONS.get(station_serial, {})
    # The registry is global today. Keeping this lookup station-scoped permits
    # heterogeneous hardware contracts later without changing the API.
    del station
    # The deployed GreenLab NH4 channel is raw µg/L.  It is converted once to
    # mg/L before Emerson NH3 chemistry; preserving the raw unit here avoids
    # silently treating a 0.001 scale factor as an unexplained correction.
    return {"COD": "mg/L", "NH4": "ug/L_raw", "pH": "-", "Temperature": "degC", "TSS": "mg/L", "DO": "mg/L"}


def contract_issues(station_serial: str) -> list[str]:
    """Return unsafe configuration conflicts that require a human decision."""
    issues: list[str] = []
    if station_serial not in STATIONS:
        issues.append("unknown_station")
    # NH4 is a valid measured input for deriving NH3 only after the reported
    # raw unit/basis has been confirmed for this hardware contract.
    if station_units(station_serial).get("NH4") != "ug/L_raw" or NH4_UNIT_SCALE != 0.001 or not NH4_CONVERSION_CONFIRMED:
        issues.append("nh4_conversion_basis_unverified")
    return issues


def _observation_id(station_serial: str, observed_at: pd.Timestamp, metric: str, value: float, source_type: str) -> str:
    material = "|".join((station_serial, observed_at.isoformat(), metric, repr(float(value)), source_type))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def to_raw_observations(
    df: pd.DataFrame,
    station_serial: str,
    source_type: str,
    metrics: Iterable[str] = RAW_METRICS,
    ingested_at: datetime | None = None,
) -> pd.DataFrame:
    """Losslessly normalize a wide sensor frame without applying QC or imputation."""
    if "fetchedAt" not in df.columns:
        raise ValueError("wide sensor frame must contain fetchedAt")
    units = station_units(station_serial)
    captured_at = pd.to_datetime(ingested_at or datetime.now(timezone.utc), utc=True)
    rows: list[dict] = []
    for _, record in df.iterrows():
        observed_at = pd.to_datetime(record["fetchedAt"], utc=True)
        for metric in metrics:
            if metric not in df.columns or pd.isna(record[metric]):
                continue
            value = float(record[metric])
            rows.append({
                "observation_id": _observation_id(station_serial, observed_at, metric, value, source_type),
                "observed_at": observed_at,
                "station_serial": station_serial,
                "metric": metric,
                "value": value,
                "unit": units.get(metric, "unknown"),
                "source_type": source_type,
                "qc_status": "UNCHECKED",
                "ingested_at": captured_at,
                "provenance": "hardware_sensor",
                "contract_version": CONTRACT_VERSION,
            })
    return pd.DataFrame(rows, columns=[*REQUIRED_COLUMNS, "contract_version"])


def apply_range_qc(raw_observations: pd.DataFrame) -> pd.DataFrame:
    """Create a separate QC view; never mutate or discard the raw observations."""
    validate_observations(raw_observations)
    qc = raw_observations.copy()
    qc["qc_status"] = qc.apply(
        lambda row: "VALID" if is_in_range(str(row["metric"]), float(row["value"])) else "INVALID",
        axis=1,
    )
    qc["qc_reason"] = qc["qc_status"].map({"VALID": "range_ok", "INVALID": "outside_plausible_range"})
    return qc


def validate_observations(observations: pd.DataFrame) -> None:
    missing = set(REQUIRED_COLUMNS) - set(observations.columns)
    if missing:
        raise ValueError(f"observation contract missing columns: {sorted(missing)}")
    if observations["observation_id"].duplicated().any():
        raise ValueError("observation_id must be unique")
    if observations["observed_at"].isna().any() or observations["ingested_at"].isna().any():
        raise ValueError("observed_at and ingested_at are required")
    if observations["value"].isna().any():
        raise ValueError("raw observations cannot contain null values")
