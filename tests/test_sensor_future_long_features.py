"""Runtime single-origin features must equal the research training frame."""
import numpy as np
import pandas as pd
import pytest

from core import sensor_future_long as sfl
from experiments.forecast_sensor_v2 import TIDE_COLUMNS, build_frame, feature_subset, load_sensor_data, tide_features


def _raw(periods=600, seed=0):
    rng = np.random.default_rng(seed)
    time = pd.date_range("2026-08-01 10:00", periods=periods, freq="min", tz="UTC")
    raw = pd.DataFrame({
        "fetchedAt": time,
        "Temperature": 29 + np.sin(np.arange(periods) / 50) + rng.normal(0, .05, periods),
        "pH": 7.9 + .05 * np.cos(np.arange(periods) / 70) + rng.normal(0, .01, periods),
        "NH4": 60 + rng.normal(0, 2, periods),
        "TSS": 10 + rng.normal(0, 1, periods),
    })
    # a 7-minute telemetry gap, an out-of-range pH reading and an irregular stamp
    raw = raw.drop(index=range(200, 207))
    raw.loc[300, "pH"] = 99.0
    raw.loc[400, "fetchedAt"] = raw.loc[400, "fetchedAt"] + pd.Timedelta(seconds=20)
    return raw.reset_index(drop=True)


def _research_source(raw, tmp_path):
    path = tmp_path / "history.csv"
    raw.to_csv(path, index=False)
    return load_sensor_data(path, "06M26042804")


@pytest.mark.parametrize("target", ["Temperature", "pH"])
def test_single_origin_features_match_build_frame(tmp_path, target):
    raw = _raw()
    source = _research_source(raw, tmp_path)
    frame, all_features = build_frame(source, target, 180, "B4_quality", station="06M26042804")
    features = feature_subset(all_features, target, "B4_quality")
    runtime_source = sfl.clean_raw(raw)
    checked = 0
    for issued_at in frame["issued_at"].iloc[::37]:
        truncated = runtime_source[runtime_source["fetchedAt"] <= issued_at]
        result = sfl.origin_features(truncated, target)
        assert result["status"] == "ok", result
        assert result["issued_at"] == issued_at
        expected = frame.loc[issued_at, features].astype(float).to_numpy()
        got = np.array([result["features"][name] for name in features], dtype=float)
        np.testing.assert_allclose(got, expected, rtol=1e-9, atol=1e-9)
        checked += 1
    assert checked >= 5


def test_runtime_feature_order_matches_feature_subset(tmp_path):
    raw = _raw()
    source = _research_source(raw, tmp_path)
    _, all_features = build_frame(source, "Temperature", 360, "B4_quality", station="06M26042804")
    assert sfl.b4_feature_names("Temperature") == feature_subset(all_features, "Temperature", "B4_quality")


def test_missing_lag_returns_skip_not_value():
    raw = _raw()
    source = sfl.clean_raw(raw)
    # origin right after the 7-minute gap: the 5- and 10-minute lags are missing
    gap_end = source["fetchedAt"].iloc[200]
    result = sfl.origin_features(source[source["fetchedAt"] <= gap_end], "Temperature")
    assert result["status"] == "skip"
    assert result["reason"] == "insufficient_sensor_history"
    assert result["missing_features"]


def test_tide_features_match_research(tmp_path):
    raw = _raw()
    source = _research_source(raw, tmp_path)
    frame, _ = build_frame(source, "pH", 180, "B4_quality", station="06M26042804")
    tide = pd.DataFrame({"valid_at": pd.date_range("2026-08-01 00:00", periods=48, freq="h", tz="UTC")})
    tide["sea_level_m"] = np.sin(np.arange(48) / 4)
    expected = tide_features(frame, tide)
    for issued_at in frame["issued_at"].iloc[::90]:
        got = sfl.tide_features_at(issued_at, issued_at + pd.Timedelta(minutes=180), tide)
        assert got["status"] == "ok"
        for column in TIDE_COLUMNS:
            assert got["features"][column] == pytest.approx(expected.loc[issued_at, column])


def test_tide_out_of_range_is_skipped():
    tide = pd.DataFrame({"valid_at": pd.date_range("2026-08-01 00:00", periods=6, freq="h", tz="UTC"), "sea_level_m": np.arange(6.0)})
    got = sfl.tide_features_at(pd.Timestamp("2026-08-01 04:00", tz="UTC"), pd.Timestamp("2026-08-01 16:00", tz="UTC"), tide)
    assert got["status"] == "skip"
    assert got["reason"] == "tide_range_insufficient"
