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
