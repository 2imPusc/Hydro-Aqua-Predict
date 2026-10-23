import numpy as np
import pandas as pd
import pytest

from experiments.forecast_dm_test import diebold_mariano, dm_table, write_dm_tests


def _ar1(n, phi, scale, seed):
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, scale, n)
    out = np.empty(n)
    out[0] = noise[0]
    for i in range(1, n):
        out[i] = phi * out[i - 1] + noise[i]
    return out


def test_identical_errors_give_zero_statistic_and_unit_p_value():
    errors = _ar1(500, 0.8, 1.0, 1)
    stat, p_value = diebold_mariano(errors, errors.copy(), horizon_steps=15)
    assert stat == 0.0
    assert p_value == 1.0


def test_clearly_better_model_is_significant_with_negative_statistic():
    base = _ar1(3000, 0.9, 1.0, 2)
    model = 0.5 * base + _ar1(3000, 0.5, 0.05, 3)
    stat, p_value = diebold_mariano(model, base, horizon_steps=30)
    assert stat < 0
    assert p_value < 0.05
    stat_sq, p_sq = diebold_mariano(model, base, horizon_steps=30, loss="squared")
    assert stat_sq < 0 and p_sq < 0.05


def test_worse_model_gives_positive_statistic():
    base = _ar1(2000, 0.5, 0.2, 4)
    stat, _ = diebold_mariano(base * 3, base, horizon_steps=1)
    assert stat > 0


@pytest.mark.parametrize("n,h", [(1, 1), (2, 1), (5, 30), (40, 720), (50, 10), (800, 720)])
def test_large_lag_and_small_samples_never_crash(n, h):
    base = _ar1(n, 0.7, 1.0, 5)
    model = base + _ar1(n, 0.2, 0.3, 6)
    stat, p_value = diebold_mariano(model, base, horizon_steps=h)
    assert np.isnan(stat) == np.isnan(p_value)
    if not np.isnan(p_value):
        assert 0.0 <= p_value <= 1.0


def test_hac_lag_changes_statistic_for_autocorrelated_differences():
    base = _ar1(2000, 0.95, 1.0, 7)
    model = base * 0.97 + _ar1(2000, 0.95, 0.2, 8)
    stat_short, _ = diebold_mariano(model, base, horizon_steps=1)
    stat_long, _ = diebold_mariano(model, base, horizon_steps=60)
    assert np.isfinite(stat_short) and np.isfinite(stat_long)
    # Positive autocorrelation inflates the long-run variance.
    assert abs(stat_long) < abs(stat_short)


def test_rejects_unknown_loss_and_mismatched_lengths():
    with pytest.raises(ValueError):
        diebold_mariano(np.zeros(5), np.zeros(5), 1, loss="pinball")
    with pytest.raises(ValueError):
        diebold_mariano(np.zeros(5), np.zeros(4), 1)


def _predictions():
    issued = pd.date_range("2026-01-01", periods=400, freq="min", tz="UTC")
    actual = 28 + np.sin(np.arange(400) / 20)
    base = _ar1(400, 0.8, 0.3, 9)
    rows = []
    for split in ("rolling", "lockbox"):
        for model, err in (("persistence", base), ("ridge", base * 0.3), ("drift", base.copy())):
            rows.append(pd.DataFrame({"split": split, "fold": 0, "target": "Temperature", "horizon_minutes": 15, "feature_set": "B0_lags", "model": model, "issued_at": issued, "valid_at": issued + pd.Timedelta(minutes=15), "actual": actual, "prediction": actual + err}))
    frame = pd.concat(rows, ignore_index=True)
    # Shuffle to prove alignment is by issued_at, not row order.
    return frame.sample(frac=1.0, random_state=0).reset_index(drop=True)


def test_dm_table_pairs_with_persistence_on_lockbox():
    table = dm_table(_predictions())
    assert list(table.columns) == ["target", "horizon_minutes", "feature_set", "model", "n", "mean_loss_diff", "dm_stat", "p_value", "model_better"]
    assert set(table.model) == {"ridge", "drift"}
    ridge = table[table.model.eq("ridge")].iloc[0]
    assert ridge.n == 400
    assert ridge.dm_stat < 0 and ridge.p_value < 0.05 and bool(ridge.model_better)
    drift = table[table.model.eq("drift")].iloc[0]
    assert drift.dm_stat == 0 and drift.p_value == 1 and not bool(drift.model_better)


def test_write_dm_tests_refuses_to_overwrite(tmp_path):
    _predictions().to_parquet(tmp_path / "predictions.parquet", index=False)
    out = write_dm_tests(tmp_path)
    assert out == tmp_path / "dm_tests.csv"
    assert len(pd.read_csv(out)) == 2
    with pytest.raises(FileExistsError):
        write_dm_tests(tmp_path)


def test_rectangular_kernel_option_and_fallback():
    base = _ar1(3000, 0.9, 1.0, 2)
    model = 0.5 * base + _ar1(3000, 0.5, 0.05, 3)
    stat_bartlett, _ = diebold_mariano(model, base, horizon_steps=30)
    stat_rect, p_rect = diebold_mariano(model, base, horizon_steps=30, kernel="rectangular")
    assert stat_rect < 0 and p_rect < 0.05 and stat_rect != stat_bartlett
    with pytest.raises(ValueError):
        diebold_mariano(model, base, horizon_steps=30, kernel="parzen")
    errors = _ar1(200, 0.8, 1.0, 1)
    assert diebold_mariano(errors, errors, 15, kernel="rectangular") == (0.0, 1.0)
