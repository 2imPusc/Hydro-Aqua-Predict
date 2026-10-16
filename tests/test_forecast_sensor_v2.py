import numpy as np
import pandas as pd
import pytest

from experiments.forecast_sensor_v2 import PURGE, LOCKBOX_DAYS, build_frame, load_sensor_data, rolling_folds

def _raw(periods=110_000):
    time = pd.date_range("2026-01-01", periods=periods, freq="min", tz="UTC")
    return pd.DataFrame({"fetchedAt": time, "Temperature": 28 + np.sin(np.arange(periods) / 100), "pH": 7.8, "NH4": .2, "TSS": 10 + np.arange(periods) % 5})

def test_frame_aligns_target_in_the_future_and_never_uses_future_lags():
    raw = _raw(500)
    frame, features = build_frame(raw, "Temperature", 15, "B0_lags")
    row = frame.iloc[0]
    assert row.valid_at - row.issued_at == pd.Timedelta(minutes=15)
    assert row.actual_at >= row.valid_at - pd.Timedelta(minutes=2)
    assert row.actual_at <= row.valid_at + pd.Timedelta(minutes=2)
    assert "Temperature_lag_60m" in features
    assert row["Temperature_lag_1m"] != row.target

def test_rolling_folds_respect_purge_and_lockbox():
    raw = _raw()
    frame, _ = build_frame(raw, "Temperature", 60, "B0_lags")
    folds = rolling_folds(frame)
    assert len(folds) == 5
    for train, test in folds:
        # Train valid_at must be before start - PURGE
        # So train.valid_at.max() < test.issued_at.min()
        # Since test_starts defines the boundary:
        assert train.valid_at.max() < test.issued_at.min()
    
    # Check lockbox
    lock_start = frame.issued_at.max() - pd.Timedelta(days=LOCKBOX_DAYS)
    train_lock = frame[frame.valid_at < lock_start - PURGE]
    test_lock = frame[frame.issued_at >= lock_start]
    assert train_lock.valid_at.max() < test_lock.issued_at.min()

def test_synthetic_path_is_rejected(tmp_path):
    path = tmp_path / "data-v3.csv"
    _raw(10).to_csv(path, index=False)
    with pytest.raises(ValueError, match="synthetic_classification"):
        load_sensor_data(path, "station")


def _old_rows(split, fold, target, horizon, feature_set, model, test, prediction):
    """Reference copy of the pre-vectorisation per-row prediction logic."""
    rows = []
    for idx, row in test.reset_index(drop=True).iterrows():
        record = {"split": split, "fold": fold, "target": target, "horizon_minutes": horizon, "feature_set": feature_set, "model": model, "issued_at": row.issued_at, "valid_at": row.valid_at}
        if split == "rolling":
            record["actual_at"] = row.actual_at
        record |= {"actual": row.target, "prediction": prediction[idx], "absolute_error": abs(prediction[idx] - row.target), "gap": row.gap, "night": int(row.issued_at.tz_convert("Asia/Ho_Chi_Minh").hour < 6)}
        rows.append(record)
    return rows


def test_vectorised_prediction_block_matches_per_row_logic():
    from experiments.forecast_sensor_v2 import _prediction_block

    frame, _ = build_frame(_raw(3000).drop(index=range(500, 520)), "Temperature", 15, "B0_lags")
    test = frame.iloc[100:1500]
    prediction = test["Temperature_lag_1m"].to_numpy() + 0.01
    expected_rows = _old_rows("rolling", 2, "Temperature", 15, "B0_lags", "ridge", test, prediction) + _old_rows("lockbox", 0, "Temperature", 15, "B0_lags", "ridge", test, prediction)
    expected = pd.DataFrame(expected_rows)
    blocks = [
        _prediction_block("rolling", 2, "Temperature", 15, "B0_lags", "ridge", test, prediction),
        _prediction_block("lockbox", 0, "Temperature", 15, "B0_lags", "ridge", test, prediction),
    ]
    assert "actual_at" not in blocks[1].columns
    actual = pd.concat(blocks, ignore_index=True)
    assert list(actual.columns) == list(expected.columns)
    pd.testing.assert_frame_equal(actual, expected, check_dtype=False)
    assert actual["gap"].dtype == bool
    assert actual["night"].isin([0, 1]).all()


def _synthetic_csv(tmp_path):
    raw = _raw()
    path = tmp_path / "sensor.csv"
    raw.to_csv(path, index=False)
    return path


def test_predictions_written_as_parquet_and_metrics_unchanged(tmp_path):
    from experiments.forecast_sensor_v2 import run_benchmark

    path = _synthetic_csv(tmp_path)
    common = dict(fast=True, selected_feature_sets=("B0_lags", "B1_calendar"), selected_models=("ridge",), selected_targets=("Temperature",), selected_horizons=(15,), prediction_models=("ridge",))
    run_benchmark(path, "s", tmp_path / "with", write_predictions=True, prediction_feature_sets=("B0_lags",), **common)
    run_benchmark(path, "s", tmp_path / "without", **common)
    with_metrics = pd.read_csv(tmp_path / "with" / "metrics_per_fold.csv")
    without_metrics = pd.read_csv(tmp_path / "without" / "metrics_per_fold.csv")
    pd.testing.assert_frame_equal(with_metrics, without_metrics)
    assert not (tmp_path / "with" / "predictions.csv").exists()
    predictions = pd.read_parquet(tmp_path / "with" / "predictions.parquet")
    assert set(predictions.feature_set) == {"B0_lags"}
    assert set(predictions.model) == {"persistence", "ridge"}
    lockbox = predictions[predictions.split.eq("lockbox")]
    assert lockbox["actual_at"].isna().all()
    assert predictions[predictions.split.eq("rolling")]["actual_at"].notna().all()
    # metrics_strata still derives from the prediction rows.
    strata = pd.read_csv(tmp_path / "with" / "metrics_strata.csv")
    lock_ridge = lockbox[lockbox.model.eq("ridge")]
    lock_metric = with_metrics[with_metrics.split.eq("lockbox") & with_metrics.model.eq("ridge") & with_metrics.feature_set.eq("B0_lags")].iloc[0]
    assert lock_ridge["absolute_error"].mean() == pytest.approx(lock_metric.mae)
    assert strata[strata.split.eq("lockbox") & strata.model.eq("ridge")]["n"].sum() == len(lock_ridge)
