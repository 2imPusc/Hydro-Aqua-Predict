"""H1.9 diurnal block in experiments/forecast_sensor_v2.py: causality, alignment, fill rule."""
import json

import numpy as np
import pandas as pd
import pytest

from experiments.forecast_sensor_v2 import (
    DIURNAL_COLUMNS,
    DIURNAL_FEATURE_SETS,
    LEGACY_FEATURE_SETS,
    MinuteGrid,
    build_frame,
    diurnal_features,
    feature_subset,
    run_benchmark,
)

START = pd.Timestamp("2026-06-01", tz="UTC")


def _series(values, start=START, seconds=0):
    time = start + pd.to_timedelta(np.arange(len(values)), unit="min") + pd.Timedelta(seconds=seconds)
    return pd.DataFrame({"fetchedAt": time, "Temperature": values})


def _features(raw, issued, horizon, current=None):
    issued = pd.Series(pd.to_datetime(issued, utc=True))
    current = np.full(len(issued), -999.0) if current is None else current
    return diurnal_features(MinuteGrid(raw, "Temperature"), issued, horizon, current)


@pytest.mark.parametrize("horizon", [15, 60, 180, 720])
def test_linear_series_alignment(horizon):
    b = 0.001
    raw = _series(20 + b * np.arange(12 * 1440))
    t = START + pd.Timedelta(days=10, hours=3)  # issued on a whole minute
    row = _features(raw, [t], horizon).iloc[0]
    minute = lambda ts: (ts - START).total_seconds() / 60  # noqa: E731
    f = lambda ts: 20 + b * minute(ts)  # noqa: E731
    valid = t + pd.Timedelta(minutes=horizon)
    # Centred 15-minute mean of a linear series = the value at the centre.
    assert row.diel_y_valid_m24h == pytest.approx(f(valid - pd.Timedelta(hours=24)))
    assert row.diel_y_valid_m48h == pytest.approx(f(valid - pd.Timedelta(hours=48)))
    # Profile difference between valid and now time of day = slope * h.
    assert row.diel_anom_7d == pytest.approx(b * horizon)
    assert row.diel_anom_3d == pytest.approx(b * horizon)
    # Range of the 1440 bins before the bin of t - 1 min: t-1441 ... t-2.
    assert row.diel_amp_24h == pytest.approx(b * 1439)
    assert row.diel_amp_x_anom_7d == pytest.approx(b * 1439 * b * horizon)
    local = valid.tz_convert("Asia/Ho_Chi_Minh")
    hour = local.hour + local.minute / 60
    assert row.diel_valid_hour_sin == pytest.approx(np.sin(2 * np.pi * hour / 24))
    assert row.diel_valid_hour_cos2 == pytest.approx(np.cos(4 * np.pi * hour / 24))
    assert row.diel_fill_flag == 0


def test_daily_sinusoid_anomaly_tracks_the_cycle():
    m = np.arange(10 * 1440)
    raw = _series(np.sin(2 * np.pi * m / 1440))
    t = START + pd.Timedelta(days=9, hours=5)
    h = 360
    row = _features(raw, [t], h).iloc[0]
    # Centred 15-bin mean of a pure daily sine = attenuation * sine at the centre.
    k = np.arange(-7, 8)
    att = np.mean(np.cos(2 * np.pi * k / 1440))
    now, valid = 9 * 1440 + 300, 9 * 1440 + 300 + h
    assert row.diel_anom_7d == pytest.approx(att * (np.sin(2 * np.pi * valid / 1440) - np.sin(2 * np.pi * now / 1440)))
    assert row.diel_y_valid_m24h == pytest.approx(att * np.sin(2 * np.pi * valid / 1440))


@pytest.mark.parametrize("horizon", [15, 180, 720])
def test_features_unchanged_when_future_is_removed_or_perturbed(horizon):
    rng = np.random.default_rng(0)
    raw = _series(25 + np.cumsum(rng.normal(0, 0.05, 10 * 1440)), seconds=17)
    raw = raw.drop(index=rng.choice(len(raw), 2000, replace=False)).reset_index(drop=True)  # irregular gaps
    origins = raw["fetchedAt"].iloc[[3000, 7777, 9100, 11000, 12300]]
    full = _features(raw, origins, horizon)
    for i, t in enumerate(origins):
        visible = raw["fetchedAt"] <= t - pd.Timedelta(minutes=1)
        truncated = _features(raw[visible], [t], horizon)
        perturbed = raw.copy()
        perturbed.loc[~visible, "Temperature"] += rng.normal(5, 3, (~visible).sum())
        moved = _features(perturbed, [t], horizon)
        np.testing.assert_array_equal(full.iloc[[i]].to_numpy(), truncated.to_numpy())
        np.testing.assert_array_equal(full.iloc[[i]].to_numpy(), moved.to_numpy())


def test_observation_just_before_issue_is_not_read():
    """Even the last minute (issued_at - 1 min) is outside the block's information set."""
    values = np.full(3 * 1440, 10.0)
    raw = _series(values)
    t = START + pd.Timedelta(days=2, hours=12)
    base = _features(raw, [t], 15)
    spiked = raw.copy()
    spiked.loc[spiked["fetchedAt"] >= t - pd.Timedelta(minutes=1), "Temperature"] = 99.0
    np.testing.assert_array_equal(base.to_numpy(), _features(spiked, [t], 15).to_numpy())


def test_fill_rule_with_short_history():
    raw = _series(np.linspace(20, 21, int(1.5 * 1440)))
    t = START + pd.Timedelta(hours=30)
    row = _features(raw, [t], 60, current=np.array([20.7])).iloc[0]
    assert row.diel_y_valid_m48h == 20.7  # 48 h back is before the series: current value
    assert np.isfinite(row.diel_y_valid_m24h) and row.diel_y_valid_m24h != 20.7
    assert row.diel_anom_7d == 0.0  # 1 day < 4 required
    assert row.diel_anom_3d == 0.0  # 1 day < 2 required
    assert row.diel_amp_24h > 0
    assert row.diel_fill_flag == 1.0


def test_diurnal_feature_sets_add_block_to_parent():
    raw = _series(20 + np.sin(np.arange(3000) / 100))
    raw["pH"], raw["NH4"], raw["TSS"] = 7.8, .2, 10.0
    _, features = build_frame(raw, "Temperature", 60, "B4_quality")
    assert DIURNAL_FEATURE_SETS == ("B4_quality_diurnal", "B4_quality_diurnal_nopH", "B5_external_as_issued_diurnal", "B5_external_as_issued_diurnal_nopH")
    assert feature_subset(features, "Temperature", "B4_quality_diurnal") == feature_subset(features, "Temperature", "B4_quality")
    assert feature_subset(features, "Temperature", "B4_quality_diurnal_nopH") == feature_subset(features, "Temperature", "B4_quality_nopH")


def _raw_csv(tmp_path, days=60):
    n = days * 1440
    m = np.arange(n)
    raw = pd.DataFrame({"fetchedAt": START + pd.to_timedelta(m, unit="min"), "Temperature": 28 + 2 * np.sin(2 * np.pi * m / 1440) + np.sin(m / 5000),
                        "pH": 7.8, "NH4": .2, "TSS": 10 + m % 5})
    path = tmp_path / "sensor.csv"
    raw.to_csv(path, index=False)
    return path


def test_benchmark_runs_diurnal_on_identical_origins(tmp_path):
    path = _raw_csv(tmp_path, days=30)
    manifest = run_benchmark(path, "s", tmp_path / "out", write_predictions=True, fast=True, selected_feature_sets=("B4_quality", "B4_quality_diurnal", "B4_quality_diurnal_nopH"),
                             selected_models=("ridge",), selected_targets=("Temperature",), selected_horizons=(180,), prediction_models=("ridge",))
    predictions = pd.read_parquet(tmp_path / "out" / "predictions.parquet")
    by_set = predictions[predictions.model.eq("ridge")].groupby("feature_set", observed=True)["issued_at"].apply(tuple)
    assert by_set["B4_quality"] == by_set["B4_quality_diurnal"] == by_set["B4_quality_diurnal_nopH"]
    assert manifest["diurnal_block"]["columns"] == list(DIURNAL_COLUMNS)
    lock = pd.read_csv(tmp_path / "out" / "metrics_per_fold.csv").query("split == 'lockbox' and model == 'ridge'").set_index("feature_set")
    assert lock.loc["B4_quality_diurnal", "n_test"] == lock.loc["B4_quality", "n_test"]
    ridge = predictions[predictions.model.eq("ridge")]
    assert not np.allclose(ridge[ridge.feature_set.eq("B4_quality")]["prediction"].to_numpy(), ridge[ridge.feature_set.eq("B4_quality_diurnal")]["prediction"].to_numpy())


def test_legacy_runs_keep_legacy_categories_and_manifest(tmp_path):
    """Byte-identity guard: without H1.9 sets the parquet dictionary and manifest are unchanged."""
    path = _raw_csv(tmp_path, days=16)
    manifest = run_benchmark(path, "s", tmp_path / "out", write_predictions=True, fast=True, selected_feature_sets=("B0_lags",), selected_models=("ridge",),
                             selected_targets=("Temperature",), selected_horizons=(15,), prediction_models=("ridge",))
    predictions = pd.read_parquet(tmp_path / "out" / "predictions.parquet")
    assert list(predictions["feature_set"].cat.categories) == sorted(LEGACY_FEATURE_SETS)
    assert "diurnal_block" not in manifest
    assert "diurnal_block" not in json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
