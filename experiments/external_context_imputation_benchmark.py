"""Retrospective real-data ablation for DO/Salinity reconstruction.

This runner is research-only.  CMEMS reanalysis is explicitly labelled
retrospective: it is not evidence that the same feature would be available in
realtime.  Synthetic data is intentionally not accepted here.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from pyproj import Proj

from imputation_evaluation import SUPPORTED_MODELS, run_evaluation

HP_PROJ = Proj(proj="tmerc", lat_0=0, lon_0=105.75, k=0.9999, x_0=500000, y_0=0, ellps="WGS84", towgs84="-191.90441429,-39.30318279,-111.45032835,-0.00928836,0.01975479,-0.00427372,0.252906278")
BASE_FEATURES = ["NH3", "pH", "Temperature", "TSS"]


def _coordinates(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    lon, lat = HP_PROJ(out["Y"].to_numpy(float), out["X"].to_numpy(float), inverse=True)
    out["latitude"], out["longitude"] = lat, lon
    return out


def cmems_context(frame: pd.DataFrame, cache: Path) -> pd.DataFrame:
    """Extract nearest valid surface CMEMS cell at each observation time."""
    ds = xr.open_dataset(cache)
    rows: list[dict] = []
    try:
        for row in frame.itertuples(index=False):
            day = np.datetime64(pd.Timestamp(row.Quarter).date())
            point = ds.sel(time=day, latitude=row.latitude, longitude=row.longitude, method="nearest").squeeze()
            rows.append({"cmems_thetao": float(point["thetao"].values), "cmems_so": float(point["so"].values)})
    finally:
        ds.close()
    return pd.DataFrame(rows, index=frame.index)


def evaluate(source: Path, cmems_cache: Path, output: Path, models: tuple[str, ...]) -> pd.DataFrame:
    raw = pd.read_csv(source)
    if "data-v3" in str(source).lower() or "data-v4" in str(source).lower():
        raise ValueError("synthetic_data_is_not_valid_for_real_external_context_benchmark")
    frame = _coordinates(raw)
    frame = pd.concat([frame, cmems_context(frame, cmems_cache)], axis=1)
    frame["observed_at"] = pd.to_datetime(frame["Quarter"], utc=True)
    frame["station_serial"] = frame["Station"].astype(str)
    rows: list[dict] = []
    for target in ("DO", "Salinity"):
        variants = {
            "sensor_only": BASE_FEATURES,
            "sensor_plus_cmems_reanalysis": BASE_FEATURES + ["cmems_thetao", "cmems_so"],
        }
        if "chirps_rain_prev_month_mm" in frame:
            variants["sensor_plus_chirps_prior_month"] = BASE_FEATURES + ["chirps_rain_prev_month_mm"]
            variants["sensor_plus_chirps_cmems_reanalysis"] = BASE_FEATURES + ["chirps_rain_prev_month_mm", "cmems_thetao", "cmems_so"]
        for variant, features in variants.items():
            for split in ("temporal", "station"):
                for model in models:
                    result = run_evaluation(frame, target=target, features=features, split=split, model=model, risk_threshold=5.0 if target == "DO" else None)
                    rows.append({"scope": "retrospective_reanalysis_exploratory", "target": target, "variant": variant, "features": "+".join(features), "split": split, "model": model, **result["metrics"]})
    report = pd.DataFrame(rows)
    output.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output / "haiphong_cmems_context.csv", index=False)
    report.to_csv(output / "cmems_imputation_metrics.csv", index=False)
    (output / "manifest.json").write_text('{"scope":"retrospective_reanalysis_exploratory","allowed_for_runtime":false,"synthetic_training":false,"source":"CMEMS GLORYS cache"}', encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/haiphong/clean_data.csv")); parser.add_argument("--cmems-cache", type=Path, required=True); parser.add_argument("--output", type=Path, required=True); parser.add_argument("--models", choices=SUPPORTED_MODELS, nargs="+", default=["ridge", "extra_trees"])
    args = parser.parse_args()
    report = evaluate(args.source, args.cmems_cache, args.output, tuple(args.models))
    print(report[["target", "variant", "split", "model", "mae", "rmse", "r2"]].to_string(index=False))


if __name__ == "__main__":
    main()
