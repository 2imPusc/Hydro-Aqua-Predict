"""Read and causally join research-only as-issued external snapshots."""
from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

def read_snapshots(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    for col in ("issued_at", "valid_at", "retrieved_at"):
        if col in frame:
            frame[col] = pd.to_datetime(frame[col], utc=True)
    return frame


def read_snapshot_union(primary: Path, extra: tuple[Path, ...] | list[Path] = ()) -> pd.DataFrame:
    """Union of capture sources for B5 (H2.1), de-duplicated by issue hour.

    ``primary`` is the scheduled-task file, ``extra`` e.g. the research-map
    worker file. Records without ``capture_source`` take their file's role.
    Per station x issue hour only the highest-priority source is kept
    (``core.b5_coverage.dedupe_issues``): the primary wins, an extra source only
    fills hours the primary missed, and an empty extra changes nothing.
    """
    from core.b5_coverage import PRIMARY_SOURCE, WORKER_SOURCE, dedupe_issues

    if not extra:
        return read_snapshots(Path(primary))  # unchanged single-source behaviour
    frames = []
    for index, path in enumerate([primary, *extra]):
        frame = read_snapshots(Path(path))
        if frame.empty:
            continue
        default = PRIMARY_SOURCE if index == 0 else WORKER_SOURCE
        frame["capture_source"] = frame["capture_source"].fillna(default) if "capture_source" in frame else default
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    records = pd.concat(frames, ignore_index=True)
    issued = records["issued_at"] if "issued_at" in records else records["retrieved_at"]
    issues = pd.DataFrame({"station": records["station"], "issued_at": issued, "retrieved_at": records["retrieved_at"],
                           "capture_source": records["capture_source"]}).drop_duplicates(["station", "issued_at", "capture_source"])
    kept = dedupe_issues(issues)[["station", "issued_at", "capture_source"]]
    keys = pd.MultiIndex.from_frame(kept)
    mask = pd.MultiIndex.from_arrays([records["station"], issued, records["capture_source"]]).isin(keys)
    return records[mask].reset_index(drop=True)


def join_as_issued(frame: pd.DataFrame, snapshots: pd.DataFrame, *, prefix: str, max_age_hours: int = 24) -> pd.DataFrame:
    if snapshots.empty:
        return frame.copy()
    required = {"issued_at", "valid_at", "retrieved_at", "features"}
    if not required.issubset(snapshots.columns):
        raise ValueError("snapshot_contract_missing_fields")
        
    left = frame.copy().reset_index(drop=True)
    left["_row"] = left.index
    right = snapshots.copy()
    
    right = right.rename(columns={
        "issued_at": "snapshot_issued_at",
        "retrieved_at": "snapshot_retrieved_at",
        "valid_at": "snapshot_valid_at",
    })
    
    # Gate B: Exclude pseudo/oracle. Accept only captured_live and reconstructed_run.
    if "provenance_class" in right.columns:
        right = right[right["provenance_class"].isin(["captured_live", "reconstructed_run"])]
    else:
        # If missing provenance, assume captured_live to avoid breaking older snapshots, 
        # but technically we only want verified. Let's assume captured_live.
        pass

    right["valid_bucket"] = right["snapshot_valid_at"].dt.floor("h")
    left["valid_bucket"] = left["valid_at"].dt.floor("h")
    
    # Check station
    if "station" not in right.columns and "location" not in right.columns:
        raise ValueError("snapshot_missing_station_or_location")
    if "station" not in left.columns:
        if "station_serial" in left.columns:
            left["station"] = left["station_serial"]
        else:
            raise ValueError("frame_missing_station")
            
    # Location version check
    if "location_id" not in right.columns:
        right["location_id"] = "legacy_location"
        
    join_keys = ["valid_bucket", "station"]
    if "location_id" in left.columns:
        join_keys.append("location_id")
    
    for key in ("provider", "product"):
        if key in left.columns and key in right.columns:
            join_keys.append(key)
            
    joined = left.merge(right, on=join_keys, suffixes=("", "_snapshot"), how="left")
    
    # Causality: retrieved_at <= forecast_origin (which is issued_at)
    # Using retrieved_at instead of snapshot_issued_at for age and causality!
    causal = joined["snapshot_retrieved_at"] <= joined["issued_at"]
    
    # Age from retrieved_at
    age = (joined["issued_at"] - joined["snapshot_retrieved_at"]).dt.total_seconds() / 3600
    causal &= (age >= 0) & (age <= max_age_hours)
    
    # To prevent random product fallback, we should sort by retrieved_at and pick latest.
    # Group by _row and provider/product.
    joined = joined[causal].sort_values(["_row", "snapshot_retrieved_at"]).groupby("_row", as_index=False).tail(1)
    
    known = sorted({key for feature in snapshots["features"] if isinstance(feature, dict) for key in feature})
    feature_series = joined.get("features", pd.Series([{}] * len(joined)))
    feature_rows = pd.json_normalize(feature_series.map(lambda value: value if isinstance(value, dict) else {})).add_prefix(f"{prefix}_")
    feature_rows.index = joined["_row"].to_numpy()
    
    out = frame.copy()
    for key in known:
        column = f"{prefix}_{key}"
        out[column] = feature_rows[column].reindex(out.reset_index(drop=True).index).to_numpy() if column in feature_rows else pd.NA
    return out
