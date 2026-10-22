import numpy as np
import pandas as pd

from experiments import heat_skill as k


def test_contingency_counts_and_scores():
    obs = np.array([1, 1, 1, 0, 0, 0], bool)
    pred = np.array([1, 0, 0, 1, 1, 0], bool)
    c = k.contingency(obs, pred)
    assert (c["hits"], c["misses"], c["false_alarms"], c["correct_neg"]) == (1, 2, 2, 1)
    assert c["POD"] == round(1 / 3, 3) and c["FAR"] == round(2 / 3, 3) and c["CSI"] == round(1 / 5, 3)
    assert c["freq_bias"] == 1.0


def test_contingency_no_events_gives_none():
    c = k.contingency(np.zeros(4, bool), np.zeros(4, bool))
    assert c["POD"] is None and c["FAR"] is None and c["CSI"] is None


def test_offset_and_linear_fit_recover_known_relation():
    p = np.linspace(28, 32, 20)
    s = 2.0 + 0.9 * p
    assert abs(k.fit_offset(s, p) - np.median(s - p)) < 1e-12
    coef = k.fit_linear(s, p)
    assert np.allclose(coef, [2.0, 0.9])
    assert np.allclose(k.apply_linear(coef, p), s)
    a = np.sin(np.arange(20))
    coef2 = k.fit_linear(s + 0.3 * a, p, a)
    assert np.allclose(coef2, [2.0, 0.9, 0.3])


def test_best_threshold_finds_shifted_cut():
    sensor = np.array([29.5, 30.5, 31.5, 32.0, 29.0, 31.2])
    product = sensor - 1.0  # product runs 1 C cold
    assert k.best_threshold(sensor >= 31, product, 31.0) == 30.2 or 30.0 < k.best_threshold(sensor >= 31, product, 31.0) <= 30.5


def test_folds_split_has_no_leakage_and_lomo_covers_all():
    idx = pd.date_range("2026-05-29", "2026-10-20")
    (_, tr, te), = list(k.folds(idx, "split"))
    assert not (tr & te).any() and idx[tr].max() <= k.TRAIN_END < idx[te].min()
    seen = np.zeros(len(idx), int)
    for _, tr, te in k.folds(idx, "lomo"):
        assert not (tr & te).any()
        seen += te
    assert (seen == 1).all()


def test_oof_never_uses_test_rows_for_fit():
    idx = pd.date_range("2026-05-29", "2026-10-20")
    rng = np.random.default_rng(0)
    prod = 29 + rng.normal(0, 0.5, len(idx))
    df = pd.DataFrame({"sensor": prod + 1.0, "p": prod, "air": 30.0}, index=idx)
    base = k.oof_predict(df, "p", "offset", "split", 31.0)
    df2 = df.copy()
    df2.loc[df2.index > k.TRAIN_END, "sensor"] += 5.0  # change test truth only
    again = k.oof_predict(df2, "p", "offset", "split", 31.0)
    assert np.allclose(base["est"].dropna(), again["est"].dropna())
    assert np.allclose(base["est"].dropna(), df.loc[df.index > k.TRAIN_END, "p"] + 1.0)


def test_horizon_labels():
    assert k.horizon("oisst") == "same-day hindcast"
    assert k.horizon("air") == "same-day hindcast"
    assert k.horizon("marine_lag2") == "lead 2 (persistence)"
    assert k.horizon("air_lag3") == "lead 3 (persistence)"


def test_air_only_baseline_rows_fit_on_air_only():
    idx = pd.date_range("2026-05-29", "2026-10-20")
    rng = np.random.default_rng(1)
    air = pd.Series(28 + 3 * np.sin(np.arange(len(idx)) / 9) + rng.normal(0, 0.3, len(idx)), index=idx)
    sensor = 5.0 + 0.85 * air
    sst = pd.Series(29.0 + rng.normal(0, 0.5, len(idx)), index=idx)
    df = k.build_frame(sensor, sst, sst + 0.2, air)
    res = k.oof_predict(df, "air", "lin", "split", 31.0)
    test = df.index > k.TRAIN_END
    assert np.allclose(res.loc[test, "est"], sensor[test], atol=1e-6)  # recovers sensor ~ air exactly
    metrics, _, _ = k.evaluate(df)
    air_rows = metrics[metrics["product"].str.startswith("air")]
    assert set(air_rows["product"]) == {"air", "air_lag1", "air_lag2", "air_lag3"}
    assert "lin_air" not in set(air_rows["method"]) and "lin" in set(air_rows["method"])
    assert set(metrics.loc[metrics["product"] == "air", "horizon"]) == {"same-day hindcast"}
    assert set(metrics.loc[metrics["product"] == "oisst_lag1", "horizon"]) == {"lead 1 (persistence)"}


def test_continuous_metrics():
    m = k.continuous(np.array([30.0, 31.0, 32.0]), np.array([31.0, 31.0, 31.0]))
    assert m["bias_c"] == 0.0 and m["MAE_c"] == round(2 / 3, 3)
