import numpy as np
import pandas as pd
import pytest

from experiments.transfer_forecast import (
    EVAL_B_TEST_START,
    EVAL_B_TRAIN_END,
    FEATURES,
    Prep,
    Series15,
    assert_no_lookahead,
    eval_b_masks,
    fold_starts,
    inner_split,
    nb1_series,
    origin_features,
    purge,
    train_mask,
)


def _raw(days: int = 10, seed: int = 0) -> pd.DataFrame:
    times = pd.date_range("2026-08-20 17:00", periods=days * 1440, freq="min", tz="UTC")
    minute = np.arange(len(times))
    rng = np.random.default_rng(seed)
    temp = 29 + 1.5 * np.sin(2 * np.pi * minute / 1440) + 0.05 * rng.standard_normal(len(times))
    raw = pd.DataFrame({"fetchedAt": times + pd.Timedelta(seconds=20), "Temperature": temp})
    return raw.drop(index=rng.choice(len(raw), len(raw) // 5, replace=False)).reset_index(drop=True)


def test_nb1_point_uses_only_bins_before_the_mark():
    times = pd.date_range("2026-10-01", periods=120, freq="min", tz="UTC")
    raw = pd.DataFrame({"fetchedAt": times, "Temperature": np.arange(120, dtype=float)})
    s = nb1_series(raw, "Temperature")
    # mark 2 = minute 30: p = mean of minutes 27, 28, 29; y = mean of minutes 28..32
    assert s.p[2] == pytest.approx(28.0)
    assert s.y[2] == pytest.approx(30.0)


def test_features_are_causal_against_truncated_data():
    raw = _raw()
    series = nb1_series(raw, "Temperature")
    issued = pd.Series(pd.date_range("2026-08-27 00:00", periods=40, freq="15min", tz="UTC") + pd.Timedelta(seconds=37))
    for h in (15, 180, 720):
        assert assert_no_lookahead(raw, "Temperature", series, issued, h, n=8) == 8


def test_future_changes_do_not_move_features():
    raw = _raw()
    t = pd.Timestamp("2026-08-28 06:15:12", tz="UTC")
    a = origin_features(nb1_series(raw, "Temperature"), pd.Series([t]), 360)
    tampered = raw.copy()
    tampered.loc[tampered["fetchedAt"] >= t.floor("min"), "Temperature"] += 50  # not seen by lag_1m
    b = origin_features(nb1_series(tampered, "Temperature"), pd.Series([t]), 360)
    np.testing.assert_allclose(a[FEATURES + ["current"]].to_numpy(float), b[FEATURES + ["current"]].to_numpy(float), equal_nan=True)


def test_delta_target_and_horizon_features():
    p = np.arange(2000, dtype=float)
    s = Series15(p, p, pd.Timestamp("2026-01-01", tz="UTC"), 7)
    f = s.features(np.array([1000]), 60)
    assert f["delta"].iloc[0] == 4  # 60 min = 4 steps
    assert f["d15"].iloc[0] == -1 and f["d720"].iloc[0] == -48
    assert f["s24"].iloc[0] == (1000 + 4 - 96) - 1000
    assert f["prof7"].iloc[0] == pytest.approx(4.0)
    with pytest.raises(ValueError):
        s.features(np.array([1000]), 1440)


def _frame(start="2026-08-01", days=40, h=60):
    issued = pd.date_range(start, periods=days * 96, freq="15min", tz="UTC")
    return pd.DataFrame({"issued_at": issued, "valid_at": issued + pd.Timedelta(minutes=h)})


def test_fold_train_mask_is_purged():
    frame = _frame(h=720)
    start = pd.Timestamp("2026-08-30", tz="UTC")
    train = frame[train_mask(frame, start, 720)]
    assert train["valid_at"].max() < start - pd.Timedelta(minutes=720)
    assert purge(15) == pd.Timedelta(minutes=60)


def test_inner_split_is_disjoint_and_purged():
    frame = _frame(h=360)
    fit, val = inner_split(frame, 360)
    assert not (fit & val).any()
    val_start = frame.loc[val, "issued_at"].min()
    assert frame.loc[fit, "valid_at"].max() < val_start - pd.Timedelta(minutes=360)
    assert frame.loc[val, "issued_at"].max() - val_start <= pd.Timedelta(days=7)


def test_eval_b_split_boundaries():
    frame = _frame(start="2026-08-20", days=50, h=720)
    tmask, emask = eval_b_masks(frame, frame)
    assert frame.loc[tmask, "valid_at"].max() < EVAL_B_TRAIN_END
    assert frame.loc[emask, "issued_at"].min() >= EVAL_B_TEST_START
    assert EVAL_B_TEST_START - EVAL_B_TRAIN_END == pd.Timedelta(days=14)
    assert EVAL_B_TRAIN_END == pd.Timestamp("2026-08-31 17:00", tz="UTC")


def test_fold_starts_reads_b4_rows():
    check = [{"feature_set": "B4_quality", "horizon_minutes": 60, "fold": k, "lockbox_start": "2026-10-10T05:00:00+00:00", "test_issued_from": f"2026-09-0{k}T05:00:00+00:00"} for k in range(1, 6)]
    check.append({"feature_set": "B4_quality_nopH", "horizon_minutes": 60, "fold": 1, "lockbox_start": "x", "test_issued_from": "x"})
    lock, folds = fold_starts(check, 60)
    assert lock == pd.Timestamp("2026-10-10 05:00", tz="UTC") and len(folds) == 5


def test_prep_statistics_come_from_fit_rows_only():
    train = pd.DataFrame({"a": [1.0, 2.0, np.nan, 3.0]})
    test = pd.DataFrame({"a": [1000.0, np.nan]})
    prep = Prep().fit(train)
    assert prep.median[0] == 2.0
    out = prep.transform(test)
    assert out[1, 0] == pytest.approx((2.0 - prep.mu[0]) / prep.sd[0])
    assert prep.mu[0] == pytest.approx(2.0)


def test_shrunk_ridge_interpolates_between_foreign_and_nb1():
    from experiments.transfer_forecast import RidgeFamily, shrunk_ridge

    rng = np.random.default_rng(0)
    n = 4000
    foreign = pd.DataFrame(rng.standard_normal((n, len(FEATURES))), columns=FEATURES)
    foreign["delta"] = 2.0 * foreign["d15"]
    nb1 = pd.DataFrame(rng.standard_normal((500, len(FEATURES))), columns=FEATURES)
    nb1["delta"] = -1.0 * nb1["d15"]
    pre = RidgeFamily().pretrain(foreign)
    probe = pd.DataFrame(np.zeros((2, len(FEATURES))), columns=FEATURES); probe.loc[1, "d15"] = 1.0

    def slope(predict):
        out = predict(probe)
        return out[1] - out[0]

    assert slope(shrunk_ridge(pre, nb1, 1e9)) == pytest.approx(slope(lambda f: RidgeFamily.zero_shot(pre, f)), abs=1e-3)
    assert slope(shrunk_ridge(pre, nb1, 1e-6)) == pytest.approx(-1.0, abs=0.05)
