"""Freeze the canonical sensor history into one hashed CSV (roadmap D0.4).

Canonical store = append-only files under data/greenlab/exports/ (decisions #11),
merged by core.greenlab_api.load_cached_history(). Benchmarks read the frozen CSV,
so every result can name the exact input by sha256.

    python scripts/export_sensor_history.py --station 06M26042804
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.greenlab_api import load_cached_history  # noqa: E402


def export_history(station: str, out_dir: Path) -> dict:
    history = load_cached_history(station)
    if history.empty:
        raise RuntimeError(f"no sensor history for {station}")
    last = history["fetchedAt"].max()
    run = f"sensor-history-{last:%Y%m%d}"
    run_dir = out_dir / run
    run_dir.mkdir(parents=True, exist_ok=True)
    csv_path = run_dir / f"{station}.csv"
    if csv_path.exists():
        raise FileExistsError(csv_path)
    history.to_csv(csv_path, index=False)
    manifest = {
        "run": run,
        "station": station,
        "rows": int(len(history)),
        "first": history["fetchedAt"].min().isoformat(),
        "last": last.isoformat(),
        "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "source": "core.greenlab_api.load_cached_history (all_data + intervals + live-cache)",
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--station", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(export_history(args.station, paths.EXPERIMENT_OUTPUT_DIR), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
