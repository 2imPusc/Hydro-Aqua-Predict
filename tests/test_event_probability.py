import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import roc_auc_score

from experiments import event_probability as ep


def test_max_jump_respects_six_hour_lag():
    values = np.full(24, 28.0)
    values[10] = 30.0  # +2.0 from bins 4..9
    rise, drop = ep.max_jump(values)
    assert rise == pytest.approx(2.0) and drop == pytest.approx(2.0)
    slow = np.linspace(28.0, 30.0, 24)  # 2 C over 23 h: never 1.5 C within 6 h
    assert ep.max_jump(slow)[0] < ep.JUMP_C


def test_window_label_coverage_and_kinds():
    values = np.full(24, 31.2)
    assert ep.window_label(values, "hot") == (1.0, pytest.approx(31.2))
    gappy = values.copy()
    gappy[:5] = np.nan  # 19 bins < 20
    assert np.isnan(ep.window_label(gappy, "hot")[0])
    ramp = np.r_[np.full(12, 28.0), np.full(12, 29.6)]
    assert ep.window_label(ramp, "rise")[0] == 1.0
    assert ep.window_label(ramp, "drop")[0] == 0.0


def test_hourly_bins_need_thirty_readings(tmp_path):
    t = pd.date_range("2026-07-01 00:00", periods=120, freq="1min", tz="UTC")
    temp = np.r_[np.full(60, 30.0), np.full(20, 31.0), np.full(40, np.nan)]
    path = tmp_path / "s.csv"
    pd.DataFrame({"fetchedAt": t.astype(str), "Temperature": temp + np.random.default_rng(0).normal(0, .05, 120)}).to_csv(path, index=False)
    hourly = ep.load_hourly(path)
    assert hourly.notna().sum() == 1 and abs(hourly.iloc[0] - 30.0) < 0.1


def _issues(days: int, per_day: int = 1) -> pd.DataFrame:
    start = pd.Timestamp("2026-06-01", tz=ep.LOCAL_TZ)
    rows = []
    for d in range(days):
        for k in range(per_day):
            t = (start + pd.Timedelta(days=d, hours=6 * k)).tz_convert("UTC")
            rows.append({"issued_at": t, "label_end": t + pd.Timedelta(hours=24),
                         "issue_day": (start + pd.Timedelta(days=d)).date().isoformat()})
    return pd.DataFrame(rows)


def test_splits_are_purged_and_lockbox_is_last_14_days():
    issues = _issues(120, per_day=4)
    splits = ep.make_splits(issues)
    lock = splits[-1]
    assert lock["name"] == "lockbox"
    assert issues.loc[lock["test"], "issue_day"].nunique() == ep.LOCKBOX_DAYS
    for s in splits:
        assert issues.loc[s["train"], "label_end"].max() <= s["start"]
        assert issues.loc[s["test"], "issued_at"].min() >= s["start"]
        if s["name"] != "lockbox":
            assert issues.loc[s["test"], "label_end"].max() <= lock["start"]
    assert splits[0]["start"] - issues["issued_at"].min() >= pd.Timedelta(days=ep.MIN_TRAIN_DAYS)


def test_auc_rank_matches_sklearn_and_scores():
    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 200).astype(float)
    p = np.round(rng.random(200), 1)  # ties
    assert ep.auc_rank(y, p) == pytest.approx(roc_auc_score(y, p))
    frame = pd.DataFrame({"y": y, "p": p, "p_clim": np.full(200, y.mean()), "p_persist": 1 - y,
                          "issue_day": np.repeat(np.arange(20), 10).astype(str)})
    s = ep.score(frame)
    assert s["bss_persist"] > 0 and s["brier_persist"] == pytest.approx(1.0)
    ci = ep.block_bootstrap(frame, 3, draws=50)
    assert ci["brier_ci_lo"] <= s["brier"] <= ci["brier_ci_hi"]


def test_verdict_rule():
    base = {"n": 14, "bss_clim": 0.3, "bss_clim_ci_lo": 0.1}
    assert ep.verdict(pd.Series(base | {"n_events": 0})) == "insufficient_evidence"
    assert ep.verdict(pd.Series(base | {"n_events": 12})) == "insufficient_evidence"
    assert ep.verdict(pd.Series(base | {"n_events": 6})) == "skill"
    assert ep.verdict(pd.Series(base | {"n_events": 6, "bss_clim_ci_lo": -0.1})) == "no_skill"


def test_lead_used_follows_reconstructed_availability():
    issue = pd.Timestamp("2026-08-01 17:00", tz="UTC")  # local 00:00 on 08-02
    assert ep.lead_used(issue, pd.Timestamp("2026-08-01 20:00", tz="UTC")) == 1
    assert ep.lead_used(issue, pd.Timestamp("2026-08-02 10:00", tz="UTC")) == 2
