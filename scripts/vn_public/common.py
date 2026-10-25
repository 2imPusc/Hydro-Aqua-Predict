"""Write-once helpers shared by the vn_public collectors.

Every collected file ``X`` gets a sibling ``X.manifest.json`` (url, retrieval time, sha256,
bytes, licence/terms). Nothing is ever overwritten: an existing target raises ``FileExistsError``.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

NB1_LAT, NB1_LON = 20.719, 107.043  # GreenLab 06M26042804 anchor (AGENTS.md)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_path(target: Path) -> Path:
    return target.with_name(target.name + ".manifest.json")


def write_once_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "xb") as fh:  # "x" = fail if it exists (write-once)
        fh.write(data)


def write_manifest(target: Path, **fields) -> Path:
    """Write ``<target>.manifest.json`` for an already-written file (write-once)."""
    if not target.exists():
        raise FileNotFoundError(target)
    record = {
        "file": target.name,
        "sha256": sha256_file(target),
        "bytes": target.stat().st_size,
        "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **fields,
    }
    out = manifest_path(target)
    write_once_bytes(out, (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return out


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
