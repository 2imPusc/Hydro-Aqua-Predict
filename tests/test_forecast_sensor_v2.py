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
    
    # Check the lockbox split the benchmark actually uses.
    from experiments.forecast_sensor_v2 import lockbox_split
    train_lock, test_lock = lockbox_split(frame)
    assert train_lock.valid_at.max() < test_lock.issued_at.min() - PURGE

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
    labels = {column: object for column in ("split", "target", "feature_set", "model")}
    pd.testing.assert_frame_equal(actual.astype(labels), expected, check_dtype=False)
    assert actual["gap"].dtype == bool
    # Fixed categorical dtypes survive concat, keeping ~60 bytes per row.
    for column in ("split", "target", "feature_set", "model"):
        assert isinstance(actual[column].dtype, pd.CategoricalDtype), column
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
    assert (strata["n"] > 0).all()
    lock_ridge = lockbox[lockbox.model.eq("ridge")]
    lock_metric = with_metrics[with_metrics.split.eq("lockbox") & with_metrics.model.eq("ridge") & with_metrics.feature_set.eq("B0_lags")].iloc[0]
    assert lock_ridge["absolute_error"].mean() == pytest.approx(lock_metric.mae)
    assert strata[strata.split.eq("lockbox") & strata.model.eq("ridge")]["n"].sum() == len(lock_ridge)


def test_long_horizons_are_available_and_short_ones_kept():
    from experiments.forecast_sensor_v2 import HORIZONS

    assert set(HORIZONS) == {15, 30, 60, 180, 360, 720}


def test_effective_purge_is_at_least_the_horizon():
    from experiments.forecast_sensor_v2 import effective_purge

    assert effective_purge(15) == PURGE
    assert effective_purge(60) == PURGE
    assert effective_purge(720) == pd.Timedelta(minutes=720)


@pytest.mark.parametrize("horizon", [60, 720])
def test_purge_keeps_train_targets_clear_of_test_window_for_long_horizon(horizon):
    from experiments.forecast_sensor_v2 import lockbox_split

    frame, _ = build_frame(_raw(), "Temperature", horizon, "B0_lags")
    window = pd.Timedelta(minutes=max(horizon, 60))
    folds = rolling_folds(frame)
    assert len(folds) == 5
    for train, test in folds:
        test_start = test.issued_at.min()
        # No training label may be valid inside [test_start - horizon, ...).
        assert train.valid_at.max() < test_start - window
        assert train.actual_at.max() < test_start - window + pd.Timedelta(minutes=2)
        # No training origin inside the test window either.
        assert train.issued_at.max() < test_start
    train, test = lockbox_split(frame)
    lock_start = frame.issued_at.max() - pd.Timedelta(days=LOCKBOX_DAYS)
    assert test.issued_at.min() >= lock_start
    assert train.valid_at.max() < lock_start - window
    assert len(train) and len(test)


def test_lag_features_never_read_after_issue_time_at_long_horizon():
    raw = _raw(3000)
    frame, features = build_frame(raw, "Temperature", 720, "B0_lags")
    lookup = raw.set_index("fetchedAt")["Temperature"]
    row = frame.iloc[50]
    for minute in (1, 15, 60):
        assert row[f"Temperature_lag_{minute}m"] == lookup[row.issued_at - pd.Timedelta(minutes=minute)]
    assert row.target == lookup[row.valid_at]


@pytest.mark.parametrize("horizon", [15, 720])
def test_rolling_fold_labels_never_reach_the_lockbox(horizon):
    frame, _ = build_frame(_raw(), "Temperature", horizon, "B0_lags")
    lock_start = frame.issued_at.max() - pd.Timedelta(days=LOCKBOX_DAYS)
    for train, test in rolling_folds(frame):
        assert test.valid_at.max() < lock_start
        assert train.valid_at.max() < lock_start


def test_tide_features_interpolate_and_mask_outside_series():
    from experiments.forecast_sensor_v2 import tide_features

    tide = pd.DataFrame({"valid_at": pd.to_datetime(["2026-01-01 00:00", "2026-01-01 01:00", "2026-01-01 02:00"], utc=True),
                         "sea_level_m": [0.0, 1.0, 0.0]})
    frame = pd.DataFrame({"issued_at": pd.to_datetime(["2026-01-01 01:00", "2026-01-01 01:30"], utc=True),
                          "valid_at": pd.to_datetime(["2026-01-01 01:30", "2026-01-01 03:00"], utc=True)})
    out = tide_features(frame, tide)
    assert out.tide_issue.tolist() == [1.0, 0.5]
    assert out.tide_valid.iloc[0] == 0.5 and np.isnan(out.tide_valid.iloc[1])
    assert out.tide_delta.iloc[0] == -0.5
    assert out.tide_slope_1h.iloc[0] == 1.0


def test_b6_tide_runs_and_requires_tide_csv(tmp_path):
    from experiments.forecast_sensor_v2 import run_benchmark

    path = _synthetic_csv(tmp_path)
    hours = pd.date_range("2025-12-31", "2026-03-31", freq="h", tz="UTC")
    tide_csv = tmp_path / "tide.csv"
    pd.DataFrame({"valid_at": hours, "sea_level_m": np.sin(np.arange(len(hours)) * 2 * np.pi / 24.8)}).to_csv(tide_csv, index=False)
    common = dict(fast=True, selected_feature_sets=("B4_quality", "B6_tide"), selected_models=("ridge",), selected_targets=("Temperature",), selected_horizons=(60,))
    with pytest.raises(ValueError, match="tide_feature_set_requires_tide_csv"):
        run_benchmark(path, "s", tmp_path / "no_tide", **common)
    run_benchmark(path, "s", tmp_path / "tide", tide_path=tide_csv, **common)
    metrics = pd.read_csv(tmp_path / "tide" / "metrics_per_fold.csv")
    assert {"B4_quality", "B6_tide"} <= set(metrics.feature_set)


def test_nopH_feature_sets_drop_only_ph_features():
    from experiments.forecast_sensor_v2 import feature_subset

    frame, all_features = build_frame(_raw(3000), "Temperature", 60, "B4_quality")
    b4 = feature_subset(all_features, "Temperature", "B4_quality")
    nopH = feature_subset(all_features, "Temperature", "B4_quality_nopH")
    assert {"pH_lag_1m", "pH_lag_15m"} <= set(b4)
    assert not any(name.startswith("pH_") for name in nopH)
    assert [name for name in b4 if not name.startswith("pH_")] == nopH
    assert {"NH4_lag_1m", "TSS_lag_15m", "temperature_x_nh4", "age_minutes"} <= set(nopH)
    with pytest.raises(ValueError, match="nopH_variant_invalid_for_pH"):
        feature_subset(build_frame(_raw(3000), "pH", 60, "B4_quality")[1], "pH", "B4_quality_nopH")


def test_nopH_benchmark_runs_with_predictions(tmp_path):
    from experiments.forecast_sensor_v2 import run_benchmark

    path = _synthetic_csv(tmp_path)
    run_benchmark(path, "s", tmp_path / "out", write_predictions=True, fast=True, selected_feature_sets=("B4_quality", "B4_quality_nopH"), selected_models=("ridge",), selected_targets=("Temperature",), selected_horizons=(60,), prediction_models=("ridge",))
    predictions = pd.read_parquet(tmp_path / "out" / "predictions.parquet")
    assert set(predictions.feature_set) == {"B4_quality", "B4_quality_nopH"}
    # Same frame rows for both sets, so the comparison is paired.
    by_set = predictions[predictions.model.eq("ridge")].groupby("feature_set", observed=True)["issued_at"].apply(lambda s: tuple(s))
    assert by_set["B4_quality"] == by_set["B4_quality_nopH"]


@pytest.mark.parametrize("horizon", [60, 720])
def test_end_window_keeps_fold_labels_out_of_lockbox(tmp_path, horizon):
    from experiments.forecast_sensor_v2 import run_benchmark, truncate_local_date

    raw = _raw()
    end = "2026-02-25"
    cut = truncate_local_date(raw, end)
    assert cut.fetchedAt.max() < pd.Timestamp("2026-02-25 17:00", tz="UTC")
    frame, _ = build_frame(cut, "Temperature", horizon, "B0_lags")
    lock_start = frame.issued_at.max() - pd.Timedelta(days=LOCKBOX_DAYS)
    assert frame.valid_at.max() < pd.Timestamp("2026-02-25 17:00", tz="UTC") + pd.Timedelta(minutes=2)
    for train, test in rolling_folds(frame):
        assert test.valid_at.max() < lock_start and train.valid_at.max() < lock_start
    path = _synthetic_csv(tmp_path)
    manifest = run_benchmark(path, "s", tmp_path / "w", fast=True, selected_feature_sets=("B0_lags",), selected_models=("ridge",), selected_targets=("Temperature",), selected_horizons=(horizon,), last_local_date=end)
    assert manifest["last_local_date"] == end
    import json
    check = json.loads((tmp_path / "w" / "fold_label_check.json").read_text())
    assert check and all(row["max_fold_valid_at"] < row["lockbox_start"] for row in check)
    assert all(row["lockbox_start"] < "2026-02-25T17:00" for row in check)
