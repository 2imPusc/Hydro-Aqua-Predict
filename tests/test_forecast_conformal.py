import numpy as np
import pandas as pd
import pytest

from experiments.forecast_conformal import (
    aci_intervals,
    calibration_residuals,
    conformal_quantile,
    evaluate_target,
    write_outputs,
)

T0 = pd.Timestamp("2026-09-01 00:00", tz="UTC")


def test_finite_sample_quantile_toy():
    residuals = np.arange(1, 11, dtype=float)  # n = 10
    assert conformal_quantile(residuals, 0.2) == 9.0  # ceil(11*0.8)=9
    assert conformal_quantile(residuals, 0.1) == 10.0  # ceil(11*0.9)=10
    assert np.isinf(conformal_quantile(residuals, 0.05))  # ceil(11*0.95)=11 > n
    assert conformal_quantile(residuals, 1.0) == 0.0


def _frame(n, split, fold, start, rng, scale=1.0):
    issued = start + pd.to_timedelta(np.arange(n), unit="min")
    valid = issued + pd.Timedelta(minutes=15)
    actual = rng.normal(0, scale, n)
    return pd.DataFrame(
        {
            "split": split,
            "fold": fold,
            "target": "pH",
            "horizon_minutes": 15,
            "feature_set": "B4_quality",
            "model": "ridge",
            "issued_at": issued,
            "valid_at": valid,
            "actual_at": valid,
            "actual": actual,
            "prediction": 0.0,
            "night": (np.arange(n) // 60) % 2,
            "gap": False,
        }
    )


def test_static_coverage_close_to_nominal_on_iid_residuals():
    rng = np.random.default_rng(0)
    cal = pd.concat([_frame(700, "rolling", f, T0 + pd.Timedelta(days=f), rng) for f in (1, 2, 3)])
    lock = _frame(20000, "lockbox", 0, T0 + pd.Timedelta(days=10), rng)
    persistence = lock.assign(model="persistence")
    df = pd.concat([cal, cal.assign(model="persistence"), lock, persistence], ignore_index=True)
    coverage, daily, _ = evaluate_target(df, alphas=(0.2, 0.1), k_folds=3, gamma=0.005)
    rows = coverage[(coverage.model == "ridge") & (coverage.method == "static")]
    for nominal, cov in zip(rows.nominal, rows.coverage):
        assert abs(cov - nominal) < 0.03
    aci = coverage[(coverage.model == "ridge") & (coverage.method == "aci")]
    for nominal, cov in zip(aci.nominal, aci.coverage):
        assert abs(cov - nominal) < 0.03
    assert {"static", "aci", "static_night", "aci_scaled"} <= set(coverage.method)
    assert {"frac_infinite", "coverage_finite"} <= set(coverage.columns)
    assert not daily.empty


def test_calibration_drops_rows_known_after_lockbox_start_and_uses_last_k_folds():
    rng = np.random.default_rng(1)
    folds = [_frame(10, "rolling", f, T0 + pd.Timedelta(days=f), rng) for f in (1, 2, 3, 4)]
    lock_start = T0 + pd.Timedelta(days=4, minutes=20)
    df = pd.concat(folds, ignore_index=True)
    res, dropped = calibration_residuals(df, k_folds=2, lockbox_start=lock_start)
    # fold 4 rows: issued T0+4d+0..9 min, known at +15..24 min -> those >= +20 dropped (5 rows)
    assert dropped == 5
    assert len(res) == 10 + 5  # fold 3 full + fold 4 partial; folds 1-2 excluded


def test_aci_does_not_use_residual_before_it_is_observed():
    issued = T0 + pd.to_timedelta([0, 1, 2], unit="min")
    valid = issued + pd.Timedelta(minutes=15)
    residual = np.array([1000.0, 0.5, 0.5])
    cal = np.linspace(0.0, 1.0, 99)
    q, _ = aci_intervals(cal, issued.values, valid.values, residual, alpha=0.2, gamma=0.5)
    # Origin 0 is known only at T0+15 min, so origins 1 and 2 must see the
    # same quantile as origin 0 (no feedback, no huge residual in the pool).
    assert q[0] == q[1] == q[2]
    q_late, _ = aci_intervals(
        cal,
        issued.values,
        (issued + pd.Timedelta(minutes=1)).values,  # origin 0 observed by origin 1
        residual,
        alpha=0.2,
        gamma=0.5,
    )
    assert q_late[1] != q_late[0]


def test_refuses_to_overwrite_existing_output(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    with pytest.raises(FileExistsError):
        write_outputs(out, pd.DataFrame(), pd.DataFrame(), {})
    fresh = tmp_path / "fresh"
    write_outputs(fresh, pd.DataFrame({"a": [1]}), pd.DataFrame({"b": [2]}), {"k": 1})
    assert (fresh / "coverage.csv").exists() and (fresh / "manifest.json").exists()


def test_known_at_falls_back_to_valid_at_when_actual_at_missing():
    from experiments.forecast_conformal import known_at

    df = pd.DataFrame(
        {
            "valid_at": pd.to_datetime(["2026-09-30 17:00", "2026-09-30 17:01"], utc=True),
            "actual_at": pd.to_datetime([None, "2026-09-30 17:03"], utc=True),
        }
    )
    out = known_at(df)
    assert out.iloc[0] == df["valid_at"].iloc[0]
    assert out.iloc[1] == df["actual_at"].iloc[1]


def test_aci_reacts_on_tz_aware_object_timestamps():
    issued = pd.Series(T0 + pd.to_timedelta(np.arange(200), unit="min"))
    known = issued + pd.Timedelta(minutes=15)
    residual = np.full(200, 10.0)  # every origin miscovered by the static interval
    cal = np.linspace(0.0, 1.0, 99)
    q, alpha_t = aci_intervals(cal, issued.to_numpy(), known.to_numpy(), residual, alpha=0.2, gamma=0.01)
    assert (alpha_t[:15] == 0.2).all()  # nothing observed during the first 15 min
    assert alpha_t.min() < 0.2  # miscoverage feedback arrived afterwards
    assert q.max() > q[0]


def test_delay_scaled_step_avoids_infinite_intervals_under_long_feedback_delay():
    rng = np.random.default_rng(3)
    n, delay = 6000, 720
    issued = pd.Series(T0 + pd.to_timedelta(np.arange(n), unit="min"))
    known = issued + pd.Timedelta(minutes=delay)
    scale = np.where(np.arange(n) < n // 2, 1.0, 2.0)
    residual = np.abs(rng.normal(0, 1, n)) * scale
    cal = np.abs(rng.normal(0, 1, 3000))
    q_fixed, _ = aci_intervals(cal, issued.to_numpy(), known.to_numpy(), residual, 0.2, 0.005)
    q_scaled, _ = aci_intervals(cal, issued.to_numpy(), known.to_numpy(), residual, 0.2, 0.005 * 15 / delay)
    assert np.isinf(q_fixed).mean() > 0.05
    assert np.isinf(q_scaled).mean() < 0.05


# --- A4: amplitude-aware intervals (aci_amp) ---------------------------------


def test_trailing_amplitude_is_causal():
    from experiments.forecast_conformal import trailing_amplitude

    times = T0 + pd.to_timedelta(np.arange(3000), unit="min")
    values = np.sin(np.arange(3000) / 200.0)
    series = pd.Series(values, index=times)
    spiked = series.copy()
    spiked.iloc[2001:] += 50.0  # everything after minute 2000 changes
    at = times[[1600, 1800, 2000, 2001, 2500]]
    base = trailing_amplitude(series, at, window="24h", kind="range", min_count=10)
    leak = trailing_amplitude(spiked, at, window="24h", kind="range", min_count=10)
    np.testing.assert_array_equal(base[:3], leak[:3])  # amplitude at t ignores data after t
    assert leak[3] > base[3] + 40  # an observation at exactly t is usable at t
    # query between observations uses only the past
    mid = pd.DatetimeIndex([times[2000] + pd.Timedelta(seconds=30)])
    assert trailing_amplitude(spiked, mid, "24h", "range", 10)[0] == base[2]
    std = trailing_amplitude(series, at, window="24h", kind="std", min_count=10)
    assert np.all(std > 0) and np.all(std < base)


def test_trailing_amplitude_nan_when_window_too_sparse():
    from experiments.forecast_conformal import trailing_amplitude

    times = T0 + pd.to_timedelta(np.arange(100), unit="min")
    series = pd.Series(np.arange(100.0), index=times)
    out = trailing_amplitude(series, times[[5, 99]], "24h", "range", min_count=50)
    assert np.isnan(out[0]) and out[1] == 99.0
    before = trailing_amplitude(series, pd.DatetimeIndex([T0 - pd.Timedelta(minutes=1)]), "24h", "range", 1)
    assert np.isnan(before[0])


def test_observed_series_comes_from_persistence_rows_only():
    from experiments.forecast_conformal import observed_series

    df = pd.DataFrame(
        {
            "model": ["persistence", "persistence", "ridge", "persistence"],
            "issued_at": pd.to_datetime(["2026-09-01 00:00", "2026-09-01 00:01", "2026-09-01 00:02", "2026-09-01 00:01"], utc=True),
            "prediction": [1.0, 2.0, 99.0, 2.0],
        }
    )
    s = observed_series(df)
    assert list(s.to_numpy()) == [1.0, 2.0]
    assert s.index.is_monotonic_increasing


def _hetero_frame(n, split, fold, start, rng, amp_of_minute):
    """Series with diurnal amplitude A(t); residuals scale with A at issue time."""
    minutes = np.arange(n)
    issued = start + pd.to_timedelta(minutes, unit="min")
    amp = amp_of_minute(issued)
    level = 0.5 * amp * np.sin(2 * np.pi * (issued.hour * 60 + issued.minute).to_numpy() / 1440.0)
    resid = rng.normal(0, 0.3, n) * amp
    common = {
        "split": split, "fold": fold, "target": "Temperature", "horizon_minutes": 15,
        "feature_set": "B4_quality", "issued_at": issued, "valid_at": issued + pd.Timedelta(minutes=15),
        "actual_at": issued + pd.Timedelta(minutes=15), "night": 0, "gap": False,
    }
    ridge = pd.DataFrame({**common, "model": "ridge", "prediction": level, "actual": level + resid})
    pers = pd.DataFrame({**common, "model": "persistence", "prediction": level, "actual": level + resid})
    return pd.concat([ridge, pers], ignore_index=True)


def test_aci_amp_tracks_amplitude_regime_where_static_undercovers():
    rng = np.random.default_rng(7)
    switch = T0 + pd.Timedelta(days=30)

    def amp(issued):
        return np.where(issued < switch, 1.0, 3.0)

    cal = pd.concat(
        [_hetero_frame(3 * 1440, "rolling", f, T0 + pd.Timedelta(days=12 + 3 * f), rng, amp) for f in (1, 2, 3)]
    )
    lock = _hetero_frame(18 * 1440, "lockbox", 0, T0 + pd.Timedelta(days=24), rng, amp)
    df = pd.concat([cal, lock], ignore_index=True)
    coverage, _, info = evaluate_target(df, alphas=(0.2,), k_folds=3, gamma=0.005, late_start=switch)
    ridge = coverage[coverage.model == "ridge"].set_index("method")
    assert {"aci_amp", "static_amp", "aci_amp_std", "aci_amp_72h"} <= set(ridge.index)
    assert ridge.loc["static", "coverage_late"] < 0.6  # calibrated on amplitude 1
    assert abs(ridge.loc["aci_amp", "coverage_late"] - 0.8) < 0.04
    assert abs(ridge.loc["aci_amp", "coverage_early"] - 0.8) < 0.04
    assert ridge.loc["aci_amp", "mean_width_late"] > 2 * ridge.loc["aci_amp", "mean_width_early"]
    for col in ("winkler", "winkler_late", "coverage_oct", "mean_width_oct"):
        assert col in ridge.columns
    assert info["amplitude"]["calibration_rows_dropped_no_amplitude"] >= 0


def test_winkler_score_symmetric():
    from experiments.forecast_conformal import winkler_score

    resid = np.array([0.5, 1.0, 3.0])
    q = np.array([1.0, 1.0, 1.0])
    # widths 2 each; third row misses by 2 -> penalty 2/alpha*2 = 20 at alpha 0.2
    np.testing.assert_allclose(winkler_score(resid, q, 0.2), [2.0, 2.0, 22.0])


def test_calibration_rows_without_amplitude_are_dropped_and_counted():
    rng = np.random.default_rng(11)
    amp = lambda issued: np.ones(len(issued))  # noqa: E731
    cal = pd.concat([_hetero_frame(1440, "rolling", f, T0 + pd.Timedelta(days=f - 1), rng, amp) for f in (1, 2, 3)])
    lock = _hetero_frame(1440, "lockbox", 0, T0 + pd.Timedelta(days=3), rng, amp)
    df = pd.concat([cal, lock], ignore_index=True)
    _, _, info = evaluate_target(df, alphas=(0.2,), k_folds=3, gamma=0.005)
    # 24 h window needs >= 720 points: the first 719 minutes of history have no
    # amplitude (counted over both models' calibration rows)
    dropped = info["amplitude"]["calibration_rows_dropped_no_amplitude"]
    assert dropped == 2 * 719
