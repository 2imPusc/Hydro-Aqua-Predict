"""Leakage-safe direct sensor forecast benchmark (research-only).

This module deliberately has no dependency on the runtime forecast bundles.  It
evaluates direct forecasts for installed sensors at fixed horizons and writes a
fully reproducible experiment run under ``artifacts/experiments``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.quality import is_in_range

TARGETS = ("Temperature", "pH", "NH4", "TSS")
HORIZONS = (15, 30, 60, 180, 360, 720)
LAGS_MINUTES = (1, 3, 5, 10, 15, 30, 60)
WINDOWS_MINUTES = (5, 15, 30, 60)
FEATURE_SETS = ("B0_lags", "B1_calendar", "B2_dynamics", "B3_cross_sensor", "B4_quality")
EXTERNAL_FEATURE_SET = "B5_external_as_issued"
AVAILABLE_FEATURE_SETS = FEATURE_SETS + (EXTERNAL_FEATURE_SET,)
TOLERANCE = pd.Timedelta(minutes=2)
PURGE = pd.Timedelta(minutes=60)
LOCKBOX_DAYS = 14
FOLD_DAYS = 7
N_FOLDS = 5


def _utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def load_sensor_data(path: Path, station: str) -> pd.DataFrame:
    """Load only real raw telemetry; synthetic classification tables are rejected."""
    if "data-gen" in str(path).lower() or "data-v3" in str(path).lower():
        raise ValueError("synthetic_classification_data_is_not_valid_for_sensor_forecast")
    raw = pd.read_csv(path)
    if "device" in raw:
        raw = raw[raw["device"].astype(str).eq(str(station))].copy()
    if "fetchedAt" not in raw:
        raise ValueError("missing_fetchedAt")
    raw["fetchedAt"] = _utc(raw["fetchedAt"])
    raw = raw.dropna(subset=["fetchedAt"]).sort_values("fetchedAt")
    cols = [c for c in TARGETS if c in raw]
    if not cols:
        raise ValueError("no_direct_sensor_columns")
    for col in cols:
        raw.loc[~raw[col].map(lambda value: is_in_range(col, value)), col] = np.nan
    # A duplicate timestamp cannot create a second training sample.
    return raw.groupby("fetchedAt", as_index=False)[cols].median().sort_values("fetchedAt")


def _asof_values(source: pd.DataFrame, issue_times: pd.Series, column: str, offsets: tuple[int, ...]) -> pd.DataFrame:
    """Backward-only feature joins.  No feature may read after ``issued_at``."""
    right = source[["fetchedAt", column]].dropna().rename(columns={"fetchedAt": "observed_at", column: "value"}).sort_values("observed_at")
    out = pd.DataFrame(index=issue_times.index)
    for offset in offsets:
        left = pd.DataFrame({"wanted_at": issue_times - pd.Timedelta(minutes=offset)}, index=issue_times.index)
        joined = pd.merge_asof(left.sort_values("wanted_at"), right, left_on="wanted_at", right_on="observed_at", direction="backward", tolerance=TOLERANCE)
        out[f"{column}_lag_{offset}m"] = joined.set_index(left.sort_values("wanted_at").index)["value"].reindex(issue_times.index)
    return out


from core.config import weather_location_for_station
def build_frame(raw: pd.DataFrame, target: str, horizon_minutes: int, feature_set: str, station: str = "unknown") -> tuple[pd.DataFrame, list[str]]:
    """Create a direct-supervision frame with explicit issue/valid timestamps."""
    if target not in raw:
        return pd.DataFrame(), []
    source = raw[["fetchedAt", *[c for c in TARGETS if c in raw]]].copy().sort_values("fetchedAt")
    base = source[["fetchedAt", target]].dropna().rename(columns={"fetchedAt": "issued_at", target: "current"})
    base["valid_at"] = base["issued_at"] + pd.Timedelta(minutes=horizon_minutes)
    actual = source[["fetchedAt", target]].dropna().rename(columns={"fetchedAt": "actual_at", target: "target"}).sort_values("actual_at")
    base = pd.merge_asof(base.sort_values("valid_at"), actual, left_on="valid_at", right_on="actual_at", direction="nearest", tolerance=TOLERANCE).dropna(subset=["target"])
    base["station"] = station
    loc = weather_location_for_station(station)
    base["location_id"] = loc.get("source", "legacy_location") if loc else "legacy_location"
    base = base.set_index("issued_at", drop=False).sort_index()
    lags = _asof_values(source, base["issued_at"], target, LAGS_MINUTES)
    base = base.join(lags)
    features = list(lags.columns)
    if feature_set in FEATURE_SETS[1:]:
        local = base["issued_at"].dt.tz_convert("Asia/Ho_Chi_Minh")
        hour = local.dt.hour + local.dt.minute / 60
        base["hour_sin"], base["hour_cos"] = np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24)
        base["dow_sin"], base["dow_cos"] = np.sin(2 * np.pi * local.dt.dayofweek / 7), np.cos(2 * np.pi * local.dt.dayofweek / 7)
        features += ["hour_sin", "hour_cos", "dow_sin", "dow_cos"]
    if feature_set in FEATURE_SETS[2:]:
        for window in WINDOWS_MINUTES:
            cols = [f"{target}_lag_{minute}m" for minute in LAGS_MINUTES if minute <= window]
            base[f"roll_mean_{window}m"] = base[cols].mean(axis=1)
            base[f"roll_median_{window}m"] = base[cols].median(axis=1)
            base[f"roll_std_{window}m"] = base[cols].std(axis=1)
            base[f"roll_min_{window}m"] = base[cols].min(axis=1)
            base[f"roll_max_{window}m"] = base[cols].max(axis=1)
            features += [f"roll_mean_{window}m", f"roll_median_{window}m", f"roll_std_{window}m", f"roll_min_{window}m", f"roll_max_{window}m"]
        base["delta_15m"] = base[f"{target}_lag_1m"] - base[f"{target}_lag_15m"]
        base["slope_60m"] = (base[f"{target}_lag_1m"] - base[f"{target}_lag_60m"]) / 59
        features += ["delta_15m", "slope_60m"]
    if feature_set in FEATURE_SETS[3:]:
        for other in TARGETS:
            if other == target or other not in source:
                continue
            cross = _asof_values(source, base["issued_at"], other, (1, 15))
            cross.columns = [f"{other}_{name.split('_', 1)[1]}" for name in cross.columns]
            base = base.join(cross)
            features += list(cross.columns)
        if {"Temperature", "NH4"}.issubset(source.columns):
            temp = _asof_values(source, base["issued_at"], "Temperature", (1,)).iloc[:, 0]
            nh4 = _asof_values(source, base["issued_at"], "NH4", (1,)).iloc[:, 0]
            base["temperature_x_nh4"] = temp * nh4
            features.append("temperature_x_nh4")
    if feature_set == "B4_quality":
        observations = source[["fetchedAt", target]].dropna().rename(columns={"fetchedAt": "observed_at"}).sort_values("observed_at")
        observations["previous_at"] = observations["observed_at"].shift(1)
        # ``issued_at`` is intentionally both an audit column and the frame
        # index; reset the index before Pandas resolves the merge key.
        quality_left = base[["issued_at"]].reset_index(drop=True).sort_values("issued_at")
        joined = pd.merge_asof(quality_left, observations, left_on="issued_at", right_on="observed_at", direction="backward")
        joined = joined.set_index("issued_at")
        base["age_minutes"] = (joined.index.to_series() - joined["observed_at"]).dt.total_seconds().div(60).reindex(base.index)
        base["gap_before_minutes"] = (joined["observed_at"] - joined["previous_at"]).dt.total_seconds().div(60).reindex(base.index)
        base["quality_gap_flag"] = (base["age_minutes"] > 2).astype(float)
        features += ["age_minutes", "gap_before_minutes", "quality_gap_flag"]
    base["cadence_minutes"] = base["issued_at"].diff().dt.total_seconds().div(60)
    base["gap"] = base["cadence_minutes"].gt(5)
    return base.dropna(subset=features + ["target", "current"]), features


def effective_purge(horizon_minutes: int) -> pd.Timedelta:
    """Embargo between the last training label and the test start.

    It must cover the horizon so no training target window overlaps the test
    window's issue period, whatever the horizon.
    """
    return max(PURGE, pd.Timedelta(minutes=int(horizon_minutes)))


def _frame_horizon_minutes(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    return int(np.ceil((frame["valid_at"] - frame["issued_at"]).max().total_seconds() / 60))


def lockbox_split(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train on labels valid before ``lockbox_start - purge``; test the last 14 days."""
    lock_start = frame["issued_at"].max() - pd.Timedelta(days=LOCKBOX_DAYS)
    purge = effective_purge(_frame_horizon_minutes(frame))
    return frame[frame["valid_at"] < lock_start - purge], frame[frame["issued_at"] >= lock_start]


def rolling_folds(frame: pd.DataFrame) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """Five expanding-origin folds before a 14-day untouched lockbox."""
    purge = effective_purge(_frame_horizon_minutes(frame))
    end = frame["issued_at"].max()
    lockbox_start = end - pd.Timedelta(days=LOCKBOX_DAYS)
    candidate = frame[frame["issued_at"] < lockbox_start].copy()
    test_starts = pd.date_range(lockbox_start - pd.Timedelta(days=N_FOLDS * FOLD_DAYS), periods=N_FOLDS, freq=f"{FOLD_DAYS}D", tz="UTC")
    folds = []
    for start in test_starts:
        stop = start + pd.Timedelta(days=FOLD_DAYS)
        train = candidate[candidate["valid_at"] < start - purge]
        test = candidate[(candidate["issued_at"] >= start) & (candidate["issued_at"] < stop)]
        if len(train) and len(test):
            folds.append((train, test))
    return folds


def _models(fast: bool = False) -> dict:
    trees = 60 if fast else 200
    boosters = 40 if fast else 160
    return {
        "ridge": make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        "extra_trees": ExtraTreesRegressor(n_estimators=trees, min_samples_leaf=3, random_state=42, n_jobs=-1),
        "xgboost": XGBRegressor(n_estimators=boosters, max_depth=3, learning_rate=.04, subsample=.9, colsample_bytree=.9, random_state=42, n_jobs=-1, verbosity=0),
    }


def _baseline_predictions(train: pd.DataFrame, test: pd.DataFrame, target: str, horizon: int) -> dict[str, np.ndarray]:
    recent = test[f"{target}_lag_1m"].to_numpy()
    lag15 = test[f"{target}_lag_15m"].to_numpy()
    drift = recent + (recent - lag15) * (horizon / 14)
    rolling = test[[f"{target}_lag_{minute}m" for minute in LAGS_MINUTES if minute <= 15]].median(axis=1).to_numpy()
    history = train[["issued_at", "current"]].rename(columns={"issued_at": "wanted_at", "current": "seasonal"}).sort_values("wanted_at")
    wanted = test[["issued_at"]].copy(); wanted["wanted_at"] = wanted["issued_at"] - pd.Timedelta(days=1)
    seasonal = pd.merge_asof(wanted.sort_values("wanted_at"), history, on="wanted_at", direction="nearest", tolerance=TOLERANCE)["seasonal"].to_numpy()
    seasonal = np.where(np.isfinite(seasonal), seasonal, recent)
    return {"persistence": recent, "drift": drift, "rolling_median": rolling, "seasonal_naive_24h": seasonal}


def _metric_rows(actual: np.ndarray, pred: np.ndarray, train_target: np.ndarray) -> dict:
    error = pred - actual
    scale = np.mean(np.abs(np.diff(train_target))) if len(train_target) > 1 else np.nan
    return {"mae": float(mean_absolute_error(actual, pred)), "rmse": float(np.sqrt(mean_squared_error(actual, pred))), "bias": float(error.mean()), "p95_ae": float(np.quantile(np.abs(error), .95)), "mase": float(np.mean(np.abs(error)) / scale) if scale and scale > 0 else np.nan, "r2": float(r2_score(actual, pred))}


def bootstrap_mae_delta(actual: np.ndarray, candidate: np.ndarray, baseline: np.ndarray, seed: int = 42, rounds: int = 500, block: int = 60) -> tuple[float, float]:
    """Block bootstrap CI for MAE(candidate) - MAE(persistence)."""
    rng, n = np.random.default_rng(seed), len(actual)
    if n < block:
        return (np.nan, np.nan)
    starts = np.arange(0, n - block + 1)
    draws = []
    for _ in range(rounds):
        indices = np.concatenate([np.arange(start, min(start + block, n)) for start in rng.choice(starts, size=max(1, n // block), replace=True)])[:n]
        draws.append(np.mean(np.abs(candidate[indices] - actual[indices])) - np.mean(np.abs(baseline[indices] - actual[indices])))
    return tuple(map(float, np.quantile(draws, [.025, .975])))


def research_gate(metrics: pd.DataFrame) -> pd.DataFrame:
    """Apply the declared research gate; this function never promotes runtime code."""
    if metrics.empty:
        return pd.DataFrame()
    key = ["target", "horizon_minutes", "feature_set"]
    rolling = metrics[metrics["split"].eq("rolling")]
    lockbox = metrics[metrics["split"].eq("lockbox")]
    rows = []
    for values, group in rolling.groupby(key):
        persistence = group[group.model.eq("persistence")].set_index("fold")
        for model, candidate in group[~group.model.eq("persistence")].groupby("model"):
            merged = candidate.set_index("fold").join(persistence[["mae", "rmse", "p95_ae"]], lsuffix="_candidate", rsuffix="_persistence", how="inner")
            lock_candidate = lockbox[(lockbox.model.eq(model)) & np.logical_and.reduce([lockbox[column].eq(value) for column, value in zip(key, values)])]
            lock_persistence = lockbox[(lockbox.model.eq("persistence")) & np.logical_and.reduce([lockbox[column].eq(value) for column, value in zip(key, values)])]
            ci_clear = False; p95_ok = False
            if len(lock_candidate) == 1 and len(lock_persistence) == 1:
                ci_clear = float(lock_candidate.iloc[0].get("mae_delta_ci_high", np.nan)) < 0
                p95_ok = float(lock_candidate.iloc[0].p95_ae) <= 1.05 * float(lock_persistence.iloc[0].p95_ae)
            beats = (merged.mae_candidate < merged.mae_persistence) & (merged.rmse_candidate < merged.rmse_persistence)
            rows.append(dict(zip(key, values)) | {"model": model, "folds_beating_both": int(beats.sum()), "folds_available": int(len(merged)), "lockbox_ci_excludes_zero": ci_clear, "lockbox_p95_ok": p95_ok, "verdict": "signal" if len(merged) >= 5 and beats.sum() >= 4 and ci_clear and p95_ok else "keep_baseline"})
    return pd.DataFrame(rows)


def _prediction_block(split: str, fold: int, target: str, horizon: int, feature_set: str, model: str, test: pd.DataFrame, prediction: np.ndarray) -> pd.DataFrame:
    """Vectorised prediction rows for one (split, fold, model) block.

    ``actual_at`` is kept only for rolling folds, matching the historical CSV
    layout (lockbox rows never carried it and become NaT after concat).
    """
    issued = pd.to_datetime(test["issued_at"].to_numpy(), utc=True)
    prediction = np.asarray(prediction, dtype=float)
    actual = test["target"].to_numpy()
    n = len(test)
    columns = {"split": [split] * n, "fold": np.full(n, fold), "target": [target] * n, "horizon_minutes": np.full(n, horizon), "feature_set": [feature_set] * n, "model": [model] * n, "issued_at": issued, "valid_at": pd.to_datetime(test["valid_at"].to_numpy(), utc=True)}
    if split == "rolling":
        columns["actual_at"] = pd.to_datetime(test["actual_at"].to_numpy(), utc=True)
    columns |= {"actual": actual, "prediction": prediction, "absolute_error": np.abs(prediction - actual), "gap": test["gap"].to_numpy(dtype=bool), "night": (issued.tz_convert("Asia/Ho_Chi_Minh").hour < 6).astype(int)}
    return pd.DataFrame(columns)


def feature_subset(all_features: list[str], target: str, feature_set: str) -> list[str]:
    """Reuse the B4 frame for every ablation without rebuilding as-of joins."""
    lag_features = [f"{target}_lag_{minute}m" for minute in LAGS_MINUTES]
    calendar = ["hour_sin", "hour_cos", "dow_sin", "dow_cos"]
    dynamics = [name for name in all_features if name.startswith(("roll_", "delta_", "slope_"))]
    cross = [name for name in all_features if "_lag_" in name and not name.startswith(f"{target}_")]
    if "temperature_x_nh4" in all_features:
        cross.append("temperature_x_nh4")
    quality = [name for name in ("age_minutes", "gap_before_minutes", "quality_gap_flag") if name in all_features]
    groups = {
        "B0_lags": lag_features,
        "B1_calendar": lag_features + calendar,
        "B2_dynamics": lag_features + calendar + dynamics,
        "B3_cross_sensor": lag_features + calendar + dynamics + cross,
        "B4_quality": lag_features + calendar + dynamics + cross + quality,
        EXTERNAL_FEATURE_SET: lag_features + calendar + dynamics + cross + quality,
    }
    return [name for name in groups[feature_set] if name in all_features]


def run_benchmark(path: Path, station: str, output: Path, snapshots_path: Path | None = None, *, write_predictions: bool = False, fast: bool = False, selected_feature_sets: tuple[str, ...] | None = None, selected_models: tuple[str, ...] | None = None, selected_targets: tuple[str, ...] | None = None, selected_horizons: tuple[int, ...] | None = None, prediction_models: tuple[str, ...] | None = None, prediction_feature_sets: tuple[str, ...] | None = None) -> dict:
    raw = load_sensor_data(path, station)
    output.mkdir(parents=True, exist_ok=True)
    all_predictions, summary = [], []
    snapshots = None
    feature_sets = selected_feature_sets or FEATURE_SETS
    if not set(feature_sets).issubset(set(AVAILABLE_FEATURE_SETS)):
        raise ValueError("unknown_feature_set")
    model_names = selected_models or tuple(_models(fast))
    if not set(model_names).issubset(set(_models(fast))):
        raise ValueError("unknown_model")
    targets = selected_targets or TARGETS
    horizons = selected_horizons or HORIZONS
    if not set(targets).issubset(set(TARGETS)):
        raise ValueError("unknown_target")
    if not set(horizons).issubset(set(HORIZONS)):
        raise ValueError("unknown_horizon")
    prediction_keep = set(prediction_models or ()) | {"persistence"}
    prediction_feature_keep = set(prediction_feature_sets or feature_sets)
    if not prediction_feature_keep.issubset(set(AVAILABLE_FEATURE_SETS)):
        raise ValueError("unknown_prediction_feature_set")
    if snapshots_path is not None:
        from experiments.forecast_external_context import join_as_issued, read_snapshots
        snapshots = read_snapshots(snapshots_path)
    if EXTERNAL_FEATURE_SET in feature_sets and (snapshots is None or snapshots.empty):
        raise ValueError("external_snapshot_feature_set_requires_snapshots")
    for target in targets:
        for horizon in horizons:
            base_feature_sets = [value for value in feature_sets if value != EXTERNAL_FEATURE_SET]
            build_level = max(base_feature_sets, key=FEATURE_SETS.index) if base_feature_sets else "B4_quality"
            full_frame, all_features = build_frame(raw, target, horizon, build_level, station=station)
            for feature_set in feature_sets:
                frame = full_frame.copy()
                features = feature_subset(all_features, target, build_level if feature_set == EXTERNAL_FEATURE_SET else feature_set)
                if feature_set == EXTERNAL_FEATURE_SET and snapshots is not None:
                    frame = join_as_issued(frame, snapshots, prefix="external")
                    if feature_set == EXTERNAL_FEATURE_SET:
                        eligible_origins = len(frame.dropna(subset=[c for c in frame if c.startswith("external_")]))
                        if eligible_origins == 0:
                            (output / "b5_coverage.json").write_text(json.dumps({"eligible_origins": 0, "verdict": "insufficient_evidence"}), encoding="utf-8")
                            # don't run B5 since it's 0 origins
                            frame = pd.DataFrame()
    
                    external = [column for column in frame if column.startswith("external_")]
                    features += external
                    frame = frame.dropna(subset=external)
                if frame.empty:
                    continue
                for fold_number, (train, test) in enumerate(rolling_folds(frame), 1):
                    predictions = _baseline_predictions(train, test, target, horizon)
                    for name, model in _models(fast).items():
                        if name not in model_names:
                            continue
                        model.fit(train[features], train["target"])
                        predictions[name] = model.predict(test[features])
                    for model_name, prediction in predictions.items():
                        metrics = _metric_rows(test.target.to_numpy(), prediction, train.target.to_numpy())
                        summary.append({"split": "rolling", "fold": fold_number, "target": target, "horizon_minutes": horizon, "feature_set": feature_set, "model": model_name, "n_train": len(train), "n_test": len(test), "gap_rate": float(test.gap.mean()), **metrics})
                        if write_predictions and model_name in prediction_keep and feature_set in prediction_feature_keep:
                            all_predictions.append(_prediction_block("rolling", fold_number, target, horizon, feature_set, model_name, test, prediction))
                # lockbox is only evaluated after all rolling experiments; train excludes it.
                train, test = lockbox_split(frame)
                if len(train) and len(test):
                    predictions = _baseline_predictions(train, test, target, horizon)
                    for name, model in _models(fast).items():
                        if name not in model_names:
                            continue
                        model.fit(train[features], train.target); predictions[name] = model.predict(test[features])
                    persistence = predictions["persistence"]
                    for model_name, prediction in predictions.items():
                        metrics = _metric_rows(test.target.to_numpy(), prediction, train.target.to_numpy())
                        ci_low, ci_high = bootstrap_mae_delta(test.target.to_numpy(), prediction, persistence)
                        summary.append({"split": "lockbox", "fold": 0, "target": target, "horizon_minutes": horizon, "feature_set": feature_set, "model": model_name, "n_train": len(train), "n_test": len(test), "gap_rate": float(test.gap.mean()), "mae_delta_ci_low": ci_low, "mae_delta_ci_high": ci_high, **metrics})
                        if write_predictions and model_name in prediction_keep and feature_set in prediction_feature_keep:
                            all_predictions.append(_prediction_block("lockbox", 0, target, horizon, feature_set, model_name, test, prediction))
    metrics = pd.DataFrame(summary)
    # Concatenate once; per-row dicts exhausted 16 GB on 1-minute history.
    predictions = pd.concat(all_predictions, ignore_index=True) if all_predictions else pd.DataFrame()
    del all_predictions
    metrics.to_csv(output / "metrics_per_fold.csv", index=False)
    if write_predictions:
        predictions.to_parquet(output / "predictions.parquet", index=False)
    research_gate(metrics).to_csv(output / "research_gate.csv", index=False)
    if not predictions.empty:
        strata = predictions.groupby(["split", "target", "horizon_minutes", "feature_set", "model", "gap", "night"], dropna=False).agg(n=("actual", "size"), mae=("absolute_error", "mean"), p95_ae=("absolute_error", lambda x: x.quantile(.95))).reset_index()
        strata.to_csv(output / "metrics_strata.csv", index=False)
    manifest = {"schema_version": "forecast-sensor-v2", "station": station, "input": str(path), "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "targets": targets, "horizons_minutes": horizons, "feature_sets": feature_sets, "models": model_names, "prediction_models": sorted(prediction_keep), "prediction_feature_sets": sorted(prediction_feature_keep), "predictions_format": "parquet", "external_snapshots": None if snapshots_path is None else str(snapshots_path), "model_preset": "fast" if fast else "full", "target_alignment": "nearest_observation_within_2_minutes", "lockbox_days": LOCKBOX_DAYS, "rolling_folds": N_FOLDS, "purge_minutes": int(PURGE.total_seconds() / 60), "effective_purge_minutes": {str(h): int(effective_purge(h).total_seconds() / 60) for h in horizons}, "purge_rule": "train valid_at < test_start - max(purge_minutes, horizon)", "synthetic_data_policy": "rejected", "runtime_changed": False}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path); parser.add_argument("--station", required=True); parser.add_argument("--output", type=Path, required=True); parser.add_argument("--snapshots", type=Path); parser.add_argument("--write-predictions", action="store_true"); parser.add_argument("--fast", action="store_true", help="research preset: 60 ExtraTrees / 40 XGBoost estimators"); parser.add_argument("--feature-set", choices=AVAILABLE_FEATURE_SETS, action="append"); parser.add_argument("--model", choices=("ridge", "extra_trees", "xgboost"), action="append"); parser.add_argument("--target", choices=TARGETS, action="append"); parser.add_argument("--horizon", choices=HORIZONS, type=int, action="append"); parser.add_argument("--prediction-model", choices=("persistence", "drift", "rolling_median", "seasonal_naive_24h", "ridge", "extra_trees", "xgboost"), action="append"); parser.add_argument("--prediction-feature-set", choices=AVAILABLE_FEATURE_SETS, action="append", help="keep predictions only for these feature sets (default: all)")
    args = parser.parse_args(); print(json.dumps(run_benchmark(args.csv, args.station, args.output, args.snapshots, write_predictions=args.write_predictions, fast=args.fast, selected_feature_sets=tuple(args.feature_set) if args.feature_set else None, selected_models=tuple(args.model) if args.model else None, selected_targets=tuple(args.target) if args.target else None, selected_horizons=tuple(args.horizon) if args.horizon else None, prediction_models=tuple(args.prediction_model) if args.prediction_model else None, prediction_feature_sets=tuple(args.prediction_feature_set) if args.prediction_feature_set else None), indent=2))


if __name__ == "__main__":
    main()
