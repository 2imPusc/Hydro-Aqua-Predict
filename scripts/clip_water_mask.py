"""Extract the regional subset of the OSM split water polygons.

Whole source polygons that intersect the bbox are copied unchanged (no
geometric clipping), so any query fully inside the bbox returns exactly the
same geometry as the global 1.2 GB shapefile.

    python scripts/clip_water_mask.py --source <water-polygons-split-4326/water_polygons.shp>
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import shapefile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402

# Hai Phong, Quang Ninh, Hung Yen, Thai Binh with a generous margin.
DEFAULT_BBOX = (105.5, 20.0, 108.5, 22.0)


def clip(source: Path, target: Path, bbox: tuple[float, float, float, float]) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    reader = shapefile.Reader(str(source))
    writer = shapefile.Writer(str(target.with_suffix("")), shapeType=reader.shapeType)
    writer.fields = reader.fields[1:]
    count = 0
    for record in reader.iterShapeRecords(bbox=bbox):
        writer.shape(record.shape)
        writer.record(*record.record)
        count += 1
    writer.close()
    for suffix in (".prj", ".cpg"):
        sidecar = source.with_suffix(suffix)
        if sidecar.exists():
            shutil.copyfile(sidecar, target.with_suffix(suffix))
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, default=paths.WATER_SHAPEFILE)
    parser.add_argument("--bbox", type=float, nargs=4, default=DEFAULT_BBOX, metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"))
    args = parser.parse_args()
    count = clip(args.source, args.target, tuple(args.bbox))
    print(f"wrote {count} polygons to {args.target}")


if __name__ == "__main__":
    main()
