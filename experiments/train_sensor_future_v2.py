"""Train the production ridge bundles for the H1.5 shadow forecasts (3/6/12 h).

Uses the research frame builder unchanged (``forecast_sensor_v2.build_frame`` /
``feature_subset``) on the canonical sensor history and writes:

* ``core/models/sensor_future/haiphong_<target>_ridge_<feature_set>_<h>m_d<data-sha8>_f<features-sha8>.pkl``
  (joblib dict: model, ordered features, calibration scores, PI method, provenance)
* ``core/models/sensor_future/sensor_future_long_manifest.json`` (runtime entry point)
* a copy of the manifest under ``artifacts/experiments/<run-name>/`` (never overwritten)

Model: ``StandardScaler + Ridge(alpha=1)`` -- the H1.2 configuration -- fitted on
the full history (no lockbox: research gating already happened in H1.2/H1.3,
RL-08/RL-09).  In-sample metrics are a sanity check only.

Calibration scores (for conformal PIs) are *out-of-sample* absolute residuals
from ``rolling_folds`` (unchanged), last ``K=3`` folds, rows known before the
lockbox start dropped -- exactly the H1.3 recipe.  Because ``rolling_folds``
reserves the last 14 days, calibration ends 14 days before the fit data ends.

pH is trained only on local dates <= 2026-09-18: the probe appears to have
drifted/faulted from 2026-09-19 (median ~6.9, inverted diurnal cycle; RL-13).

    python experiments/train_sensor_future_v2.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import paths  # noqa: E402
from experiments.forecast_conformal import DEFAULT_GAMMA, REFERENCE_HORIZON, calibration_residuals, conformal_quantile  # noqa: E402
from experiments.forecast_external_context import join_as_issued, read_snapshots  # noqa: E402
from experiments.forecast_sensor_v2 import (  # noqa: E402
    EXTERNAL_FEATURE_SET, LOCKBOX_DAYS, TIDE_COLUMNS, TIDE_FEATURE_SET, build_frame, feature_subset,
    load_sensor_data, rolling_folds, tide_features,
)

STATION = "06M26042804"
DEFAULT_HISTORY = paths.EXPERIMENT_OUTPUT_DIR / "sensor-history-20261014" / f"{STATION}.csv"
CONTEXT_DIR = paths.EXPERIMENT_OUTPUT_DIR / "external-context-06M26042804-2026-05-28_2026-10-15"
DEFAULT_SNAPSHOTS = CONTEXT_DIR / "weather-snapshots-reconstructed.jsonl"
DEFAULT_TIDE = CONTEXT_DIR / "sea_level_openmeteo_marine.csv"
MODEL_DIR = paths.MODELS_DIR / "sensor_future"
MANIFEST_NAME = "sensor_future_long_manifest.json"
HORIZONS = (180, 360, 720)
K_FOLDS = 3
ALPHAS = (0.2, 0.1)
LOCAL_TZ = "Asia/Ho_Chi_Minh"
# target -> (feature sets, PI method, training cutoff local date or None, cutoff reason)
PLAN = {
    "Temperature": (("B4_quality", EXTERNAL_FEATURE_SET), "aci_scaled", None, None),
    "pH": (("B4_quality", TIDE_FEATURE_SET), "static_night", "2026-09-18", "ph_probe_suspect_from_2026-09-19, research-log RL-13"),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ridge():
    return make_pipeline(StandardScaler(), Ridge(alpha=1.0))


def bundle_name(target: str, feature_set: str, horizon: int, data_sha: str, features: list[str]) -> str:
    feature_sha = hashlib.sha256("|".join(features).encode()).hexdigest()
    return f"haiphong_{target.lower()}_ridge_{feature_set}_{horizon}m_d{data_sha[:8]}_f{feature_sha[:8]}.pkl"


def truncate_local_date(raw: pd.DataFrame, last_local_date: str | None) -> pd.DataFrame:
    """Keep rows whose Asia/Ho_Chi_Minh date is <= ``last_local_date``."""
    if last_local_date is None:
        return raw
    end = pd.Timestamp(last_local_date, tz=LOCAL_TZ) + pd.Timedelta(days=1)
    return raw[raw["fetchedAt"] < end.tz_convert("UTC")].copy()


def model_frame(raw: pd.DataFrame, target: str, horizon: int, feature_set: str, snapshots: pd.DataFrame | None, tide: pd.DataFrame | None) -> tuple[pd.DataFrame, list[str]]:
    """Same frame/feature construction as ``forecast_sensor_v2.run_benchmark``."""
    frame, all_features = build_frame(raw, target, horizon, "B4_quality", station=STATION)
    features = feature_subset(all_features, target, "B4_quality")
    if feature_set == TIDE_FEATURE_SET:
        frame = tide_features(frame, tide).dropna(subset=list(TIDE_COLUMNS))
        features += list(TIDE_COLUMNS)
    elif feature_set == EXTERNAL_FEATURE_SET:
        frame = join_as_issued(frame, snapshots, prefix="external")
        external = [column for column in frame if column.startswith("external_")]
        features += external
        frame = frame.dropna(subset=external)
        frame[external] = frame[external].astype(float)
    return frame, features


def calibration_scores(frame: pd.DataFrame, features: list[str]) -> tuple[pd.DataFrame, dict]:
    """Out-of-sample |residual| of the last K rolling folds (H1.3 recipe)."""
    rows = []
    for fold, (train, test) in enumerate(rolling_folds(frame), 1):
        model = _ridge().fit(train[features], train["target"])
        rows.append(pd.DataFrame({
            "split": "rolling", "fold": fold, "issued_at": test["issued_at"].to_numpy(), "valid_at": test["valid_at"].to_numpy(),
            "actual_at": test["actual_at"].to_numpy(), "actual": test["target"].to_numpy(), "prediction": model.predict(test[features]),
        }))
    folds = pd.concat(rows, ignore_index=True)
    lockbox_start = frame["issued_at"].max() - pd.Timedelta(days=LOCKBOX_DAYS)
    kept, dropped = calibration_residuals(folds, K_FOLDS, lockbox_start)
    kept["night"] = (pd.to_datetime(kept["issued_at"], utc=True).dt.tz_convert(LOCAL_TZ).dt.hour < 6).astype(int)
    info = {
        "folds_used": sorted(int(f) for f in kept["fold"].unique()),
        "rows": int(len(kept)),
        "rows_night": int(kept["night"].sum()),
        "rows_dropped_known_after_lockbox_start": dropped,
        "issued_from": str(kept["issued_at"].min()),
        "issued_to": str(kept["issued_at"].max()),
        "oos_mae": float(kept["residual"].mean()),
    }
    return kept, info


def train_one(raw: pd.DataFrame, target: str, horizon: int, feature_set: str, pi_method: str, data_sha: str, snapshots, tide) -> tuple[dict, dict]:
    frame, features = model_frame(raw, target, horizon, feature_set, snapshots, tide)
    model = _ridge().fit(frame[features], frame["target"])
    fitted = model.predict(frame[features])
    persistence = frame[f"{target}_lag_1m"].to_numpy()
    cal, cal_info = calibration_scores(frame, features)
    scores = np.sort(cal["residual"].to_numpy(dtype=float)).astype(np.float32)
    by_night = {int(v): np.sort(g["residual"].to_numpy(dtype=float)).astype(np.float32) for v, g in cal.groupby("night")}
    quantiles = {
        f"pi{int(round((1 - a) * 100))}": {
            "static": conformal_quantile(scores, a),
            "static_night": {str(v): conformal_quantile(s, a) for v, s in by_night.items()},
        }
        for a in ALPHAS
    }
    name = bundle_name(target, feature_set, horizon, data_sha, features)
    version = name.removesuffix(".pkl")
    gamma = DEFAULT_GAMMA * REFERENCE_HORIZON / horizon if pi_method == "aci_scaled" else None
    bundle = {
        "schema_version": "sensor-future-long-v1",
        "model_version": version,
        "station": STATION,
        "target": target,
        "horizon_minutes": horizon,
        "feature_set": feature_set,
        "features": features,
        "model": model,
        "training_data_sha256": data_sha,
        "training_window": [str(frame["issued_at"].min()), str(frame["issued_at"].max())],
        "pi_method": pi_method,
        "aci_gamma": gamma,
        "alphas": list(ALPHAS),
        "calibration_scores": scores,
        "calibration_scores_by_night": by_night,
        "calibration": cal_info,
    }
    error = fitted - frame["target"].to_numpy()
    entry = {
        "file": name,
        "model_version": version,
        "target": target,
        "horizon_minutes": horizon,
        "feature_set": feature_set,
        "features": features,
        "n_train": int(len(frame)),
        "training_window": bundle["training_window"],
        "in_sample": {
            "mae": float(np.abs(error).mean()),
            "rmse": float(np.sqrt(np.mean(error ** 2))),
            "persistence_mae": float(np.abs(persistence - frame["target"].to_numpy()).mean()),
        },
        "pi_method": pi_method,
        "aci_gamma": gamma,
        "calibration": cal_info,
        "calibration_quantiles": quantiles,
    }
    return bundle, entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--snapshots", type=Path, default=DEFAULT_SNAPSHOTS)
    parser.add_argument("--tide", type=Path, default=DEFAULT_TIDE)
    parser.add_argument("--model-dir", type=Path, default=MODEL_DIR)
    parser.add_argument("--run-name", default="sensor-future-v2-train-20261016")
    args = parser.parse_args(argv)

    run_dir = paths.EXPERIMENT_OUTPUT_DIR / args.run_name
    if run_dir.exists():
        raise SystemExit(f"refusing to overwrite existing run: {run_dir}")
    data_sha = _sha256(args.history)
    raw = load_sensor_data(args.history, STATION)
    snapshots = read_snapshots(args.snapshots)
    tide = pd.read_csv(args.tide)
    tide["valid_at"] = pd.to_datetime(tide["valid_at"], utc=True)
    args.model_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for target, (feature_sets, pi_method, cutoff, cutoff_reason) in PLAN.items():
        target_raw = truncate_local_date(raw, cutoff)
        for horizon in HORIZONS:
            for feature_set in feature_sets:
                bundle, entry = train_one(target_raw, target, horizon, feature_set, pi_method, data_sha, snapshots, tide)
                bundle["training_cutoff_local_date"] = entry["training_cutoff_local_date"] = cutoff
                bundle["training_cutoff_reason"] = entry["training_cutoff_reason"] = cutoff_reason
                path = args.model_dir / entry["file"]
                if path.exists():
                    raise SystemExit(f"refusing to overwrite bundle: {path}")
                joblib.dump(bundle, path, compress=3)
                entries.append(entry)
                print(f"{entry['file']}: n={entry['n_train']} in-sample MAE={entry['in_sample']['mae']:.4f} "
                      f"(persistence {entry['in_sample']['persistence_mae']:.4f}); cal rows={entry['calibration']['rows']}", flush=True)
    manifest = {
        "schema_version": "sensor-future-long-manifest-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "station": STATION,
        "training_data": {"path": str(args.history.relative_to(paths.PROJECT_ROOT)), "sha256": data_sha},
        "model": "StandardScaler + Ridge(alpha=1.0), fitted on the full history (no lockbox)",
        "frame_builder": "experiments.forecast_sensor_v2.build_frame(..., 'B4_quality') + feature_subset (unmodified)",
        "external_weather_training": {
            "path": str(args.snapshots.relative_to(paths.PROJECT_ROOT)), "sha256": _sha256(args.snapshots),
            "provenance_class": "reconstructed_run", "join": "join_as_issued (retrieved_at <= issued_at, age <= 24 h)",
            "runtime_provenance_class": "captured_live only (train/serve provenance shift, decisions #13)",
        },
        "tide_training": {"path": str(args.tide.relative_to(paths.PROJECT_ROOT)), "sha256": _sha256(args.tide), "source": "Open-Meteo Marine sea_level_height_msl (model tide + surge)"},
        "calibration": {"rule": "rolling_folds (unchanged), last 3 folds, drop known_at >= lockbox start; |actual - prediction|",
                        "note": "rolling_folds reserves the last 14 days, so calibration ends 14 days before the fit data"},
        "pi": {"Temperature": f"aci_scaled, gamma = {DEFAULT_GAMMA}*{REFERENCE_HORIZON}/h, pool seeded with calibration scores",
               "pH": "static_night split conformal (night = local hour < 6), live residuals appended"},
        "metrics_note": "in-sample only (sanity); out-of-sample evidence is RL-08/RL-09",
        "bundles": entries,
    }
    (args.model_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"wrote {len(entries)} bundles, {args.model_dir / MANIFEST_NAME}, {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
