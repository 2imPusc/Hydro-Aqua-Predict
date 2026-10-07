"""Export Copernicus bathymetry pixels with coverage to a spreadsheet-friendly CSV."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import xarray as xr


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    with xr.open_dataset(args.input) as dataset:
        required = {"height", "Quality_indicator", "SDB_type"}
        missing = required - set(dataset.data_vars)
        if missing:
            raise ValueError(f"missing variables: {', '.join(sorted(missing))}")
        frame = dataset[list(sorted(required))].to_dataframe().reset_index()

    # The source uses negative height below the reference surface. Keep the
    # raw value as well, and expose depth only for water pixels.
    frame = frame.dropna(subset=["height"]).copy()
    frame["depth_m"] = np.where(frame["height"] < 0, -frame["height"], np.nan)
    frame["is_water_depth"] = frame["height"] < 0
    frame = frame.rename(columns={"height": "height_m", "Quality_indicator": "quality_indicator", "SDB_type": "sdb_type"})
    frame = frame[["longitude", "latitude", "height_m", "depth_m", "is_water_depth", "quality_indicator", "sdb_type"]]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"Exported {len(frame)} valid pixels to {args.output}")


if __name__ == "__main__":
    main()
