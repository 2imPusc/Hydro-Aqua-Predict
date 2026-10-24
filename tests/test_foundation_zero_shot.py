import numpy as np
import pandas as pd
import pytest

from experiments.foundation_zero_shot import Grid, evaluate_frame, interpolate_horizon, prediction_length, thin_mask


def _raw(minutes: int = 600) -> pd.DataFrame:
    times = pd.date_range("2026-10-01", periods=minutes, freq="min", tz="UTC")
    return pd.DataFrame({"fetchedAt": times, "Temperature": np.arange(minutes, dtype=float)})


def test_context_is_causal_and_ends_one_minute_before_issue():
    grid = Grid(_raw(), "Temperature")
    issued = pd.Series(pd.to_datetime(["2026-10-01 05:00:00", "2026-10-01 05:00:40"], utc=True))
    ctx = grid.contexts(issued, step=1, length=5)
    # value == minute index; issued 05:00 -> minute 300; ridge lag_1m sees minute 299
    assert ctx[0].tolist() == [295, 296, 297, 298, 299]
    assert ctx[1].tolist() == [295, 296, 297, 298, 299]
    ctx5 = grid.contexts(issued, step=5, length=2)
    assert ctx5[0].tolist() == [np.mean(range(290, 295)), np.mean(range(295, 300))]


def test_context_left_pads_with_nan_and_skips_gaps():
    raw = _raw(30)
    raw.loc[10:14, "Temperature"] = np.nan
    grid = Grid(raw, "Temperature")
    ctx = grid.contexts(pd.Series(pd.to_datetime(["2026-10-01 00:20:00"], utc=True)), step=5, length=6)
    assert np.isnan(ctx[0, :2]).all()  # before the series starts
    assert np.isnan(ctx[0, 4])  # minutes 10-14 missing
    assert ctx[0, 5] == np.mean(range(15, 20))


def test_interpolation_hits_window_centre_for_linear_path():
    # a perfect forecast of the minute index t + k: window j mean = (j-0.5)*step - 0.5
    step, horizon = 5, 180
    length = prediction_length(step, [horizon])
    path = ((np.arange(1, length + 1) - 0.5) * step - 0.5)[None, :]
    assert interpolate_horizon(path, step, horizon)[0] == pytest.approx(horizon)


def test_thin_mask_uses_minute_of_day():
    issued = pd.Series(pd.to_datetime(["2026-10-01 05:00:20", "2026-10-01 05:07:00", "2026-10-01 05:15:00"], utc=True))
    assert thin_mask(issued, 15).tolist() == [True, False, True]


def test_gate_requires_folds_and_lockbox_dm():
    rng = np.random.default_rng(0)
    rows = []
    for split, folds in (("rolling", range(1, 6)), ("lockbox", [0])):
        for fold in folds:
            times = pd.date_range(f"2026-09-{fold + 1:02d}", periods=400, freq="15min", tz="UTC")
            actual = rng.normal(size=len(times))
            rows.append(pd.DataFrame({"split": split, "fold": fold, "horizon_minutes": 15, "issued_at": times, "actual": actual, "persistence": actual + rng.normal(scale=1.0, size=len(times)), "ridge_B4_quality": actual + rng.normal(scale=0.5, size=len(times)), "fm": actual + rng.normal(scale=0.25, size=len(times))}))
    metrics, dm, gate = evaluate_frame(pd.concat(rows), ["fm"], ["ridge_B4_quality"], stride=15)
    row = gate[(gate.model == "fm") & (gate.reference == "ridge_B4_quality")].iloc[0]
    assert row.folds_beating == 5 and row.gate16_pass
    assert set(dm.reference) == {"persistence", "ridge_B4_quality"}
    assert metrics[(metrics.model == "persistence")].skill_vs_persistence.eq(0).all()


def test_lookahead_check_passes_on_causal_contexts():
    from experiments.foundation_zero_shot import assert_no_lookahead

    raw = _raw(3000)
    raw.loc[2000:2003, "Temperature"] = np.nan  # gap just before some origins
    grid = Grid(raw, "Temperature")
    issued = pd.Series(pd.date_range("2026-10-02 09:00", periods=40, freq="7min", tz="UTC"))
    assert assert_no_lookahead(raw, "Temperature", grid, issued, [2, 5, 15], n=40) == 40


def test_diurnal_anomaly_recovers_a_pure_daily_cycle_causally():
    from experiments.foundation_zero_shot import diurnal_anomaly

    minutes = 10 * 1440
    times = pd.date_range("2026-10-01", periods=minutes, freq="min", tz="UTC")
    raw = pd.DataFrame({"fetchedAt": times, "Temperature": 28 + np.sin(2 * np.pi * np.arange(minutes) / 1440)})
    grid = Grid(raw, "Temperature")
    at = np.array([8 * 1440 + 100, 8 * 1440 + 700])
    issued = pd.Series(times[at])
    truth = 28 + np.sin(2 * np.pi * (at + 180) / 1440)
    assert diurnal_anomaly(grid, issued, 180) == pytest.approx(truth, abs=0.01)
    # data at or after issue time must not matter
    cut = Grid(raw[raw.fetchedAt < issued.iloc[0]], "Temperature")
    assert diurnal_anomaly(cut, issued.iloc[:1], 180)[0] == pytest.approx(diurnal_anomaly(grid, issued.iloc[:1], 180)[0])
