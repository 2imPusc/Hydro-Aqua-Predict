"""Paper 1 / T2 covariate helpers in experiments/paper1_t2_chronos2_cov.py (no torch needed)."""
import numpy as np
import pandas as pd
import pytest

from experiments import foundation_zero_shot as fz
from experiments.forecast_external_context import join_as_issued
from experiments.paper1_t2_chronos2_cov import (
    HarmonicTide,
    WeatherAsIssued,
    add_profile,
    anomaly_target,
    as_inputs,
    calendar,
    covariate_arrays,
    h1_verdict,
    window_centres,
)


def _snapshots(n_runs=4):
    """Daily runs at 12:00 UTC covering R-12h .. R+59h; value = run index * 100 + hour of valid."""
    rows = []
    for r in range(n_runs):
        retrieved = pd.Timestamp("2026-09-01T12:00Z") + pd.Timedelta(days=r)
        for k in range(72):
            valid = retrieved - pd.Timedelta(hours=12) + pd.Timedelta(hours=k)
            rows.append({"station": "S", "location_id": "L", "provider": "p", "product": "q", "provenance_class": "reconstructed_run",
                         "issued_at": retrieved, "retrieved_at": retrieved, "valid_at": valid,
                         "features": {"temperature_2m": r * 100 + valid.hour, "cloud_cover": 1.0, "wind_speed_10m": 2.0, "precipitation": 0.0}})
    return pd.DataFrame(rows)


def _hours(w, times):
    return ((pd.DatetimeIndex(times) - w.h0) / pd.Timedelta(hours=1)).to_numpy().astype(int)


def test_weather_past_rule_uses_freshest_run_issued_by_then():
    w = WeatherAsIssued(_snapshots())
    origin = np.array([np.datetime64("2026-09-03T13:00")])
    # 2026-09-02 05:00: runs 09-01 12:00 and 09-02 12:00 cover it; min(t, tau + 12 h) = 09-02 17:00 -> run 1.
    # 2026-09-01 20:00: tau + 12 h = 09-02 08:00 -> only run 0 retrieved by then.
    # 2026-09-04 06:00 (future): latest run retrieved by t = run 2 (09-03 12:00).
    times = pd.to_datetime(["2026-09-02T05:00Z", "2026-09-01T20:00Z", "2026-09-04T06:00Z"])
    vals, runs = w.hourly(origin, _hours(w, times)[None, :])
    assert runs[0].tolist() == [1, 0, 2]
    assert vals[0, :, 0].tolist() == [105.0, 20.0, 206.0]


def test_weather_future_matches_join_as_issued():
    snaps = _snapshots()
    w = WeatherAsIssued(snaps)
    issued = pd.Series(pd.to_datetime(["2026-09-02T13:15Z", "2026-09-03T11:59Z", "2026-09-04T00:00Z"]))
    valid = issued.dt.floor("h") + pd.Timedelta(hours=7)
    joined = join_as_issued(pd.DataFrame({"issued_at": issued, "valid_at": valid, "station": "S"}), snaps, prefix="e")
    mine, _ = w.hourly(issued.dt.tz_convert(None).to_numpy(), _hours(w, valid)[:, None])
    assert np.allclose(mine[:, 0, 0], joined["e_temperature_2m"].astype(float))


def test_weather_interpolates_between_hours():
    w = WeatherAsIssued(_snapshots())
    origin = np.array([np.datetime64("2026-09-03T13:00")])
    out = w.at(origin, np.array([[np.datetime64("2026-09-03T15:30")]]))
    assert out[0, 0, 0] == pytest.approx(215.5)


def test_window_centres_match_interpolate_horizon_convention():
    issued = pd.Series(pd.to_datetime(["2026-09-10T00:00Z"]))
    past, fut = window_centres(issued, step=15, context=2, length=2)
    t = np.datetime64("2026-09-10T00:00")
    assert ((t - past[0]) / np.timedelta64(1, "s")).tolist() == [(15 + 7.5 + 0.5) * 60, (7.5 + 0.5) * 60]
    assert ((fut[0] - t) / np.timedelta64(1, "s")).tolist() == [(7.5 - 0.5) * 60, (22.5 - 0.5) * 60]


def test_harmonic_fit_recovers_synthetic_tide():
    times = np.arange(np.datetime64("2026-06-01T00:00"), np.datetime64("2026-09-01T00:00"), np.timedelta64(1, "h"))
    tide = HarmonicTide({"M2": 28.9841042, "K1": 15.0410686})
    hours = (times - np.datetime64("2026-01-01T00:00")) / np.timedelta64(1, "h")
    level = 0.5 + 0.8 * np.cos(np.deg2rad(28.9841042) * hours - 1.0) + 0.3 * np.sin(np.deg2rad(15.0410686) * hours)
    diag = tide.fit(times, level)
    assert diag["r2"] > 0.9999
    assert diag["amplitude_m"]["M2"] == pytest.approx(0.8, abs=1e-6) and diag["amplitude_m"]["K1"] == pytest.approx(0.3, abs=1e-6)


def test_calendar_uses_local_hour():
    out = calendar(np.array([np.datetime64("2026-09-10T17:00")]))  # 00:00 in Asia/Ho_Chi_Minh
    assert out["hour_sin"][0] == pytest.approx(0.0, abs=1e-12) and out["hour_cos"][0] == pytest.approx(1.0)


def _grid(days=10, value=lambda m: 25 + np.sin(2 * np.pi * (m % 1440) / 1440)):
    start = pd.Timestamp("2026-09-01T00:00Z")
    minutes = np.arange(days * 1440)
    raw = pd.DataFrame({"fetchedAt": start + pd.to_timedelta(minutes, unit="min"), "Temperature": value(minutes)})
    return fz.Grid(raw, "Temperature"), start


def test_anomaly_round_trip_on_pure_daily_cycle():
    grid, start = _grid()
    issued = pd.Series([start + pd.Timedelta(days=9)])
    context = grid.contexts(issued, 15, 8)
    target, profile, fallback = anomaly_target(grid, issued, 15, context, 4)
    assert not fallback.any()
    assert np.allclose(target, 0, atol=1e-6)  # a perfect daily cycle has zero anomaly
    future = add_profile(np.zeros((1, 4, 3)), profile)
    truth = grid.contexts(pd.Series([issued[0] + pd.Timedelta(minutes=60)]), 15, 4)[0]
    assert np.allclose(future[0, :, 1], truth, atol=1e-6)


def test_anomaly_falls_back_without_history_and_guards_long_paths():
    grid, start = _grid(days=2)
    issued = pd.Series([start + pd.Timedelta(hours=20)])  # < 1 day of history: no profile at all
    context = grid.contexts(issued, 15, 8)
    target, profile, fallback = anomaly_target(grid, issued, 15, context, 4)
    assert fallback.tolist() == [True]
    assert np.array_equal(target, context) and (profile == 0).all()
    with pytest.raises(AssertionError, match="profile_reads_after_issue"):
        anomaly_target(grid, issued, 15, context, 100)  # 100 x 15 min > 1 day


def test_covariates_reject_nan_and_inputs_check_keys():
    w = WeatherAsIssued(_snapshots(n_runs=2))
    issued = pd.Series(pd.to_datetime(["2026-09-09T00:00Z"]))  # far after the last run's coverage
    with pytest.raises(ValueError, match="covariate_nan"):
        covariate_arrays(("weather",), issued, 15, 4, 4, w, None)
    with pytest.raises(ValueError, match="future_covariates_not_in_past"):
        as_inputs(np.zeros((1, 4), np.float32), {"a": np.zeros((1, 4))}, {"b": np.zeros((1, 2))})
    items = as_inputs(np.zeros((2, 4), np.float32), {"a": np.ones((2, 4))}, {"a": np.ones((2, 2))})
    assert set(items[1]) == {"target", "past_covariates", "future_covariates"}


def test_h1_needs_ratio_and_gate_at_both_long_horizons():
    rows = [{"candidate": "c", "reference": "B", "horizon_minutes": h, "mae_ratio": r, "outcome": o}
            for h, r, o in ((360, 0.90, "chronos2_wins"), (720, 0.94, "chronos2_wins"))]
    assert h1_verdict(pd.DataFrame(rows), "c", "B")["H1_holds"]
    rows[1]["mae_ratio"] = 0.96
    assert not h1_verdict(pd.DataFrame(rows), "c", "B")["H1_holds"]
