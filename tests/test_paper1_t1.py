"""Paper 1 / T1 helpers in experiments/paper1_t1_chronos2.py (no torch needed)."""
import numpy as np
import pandas as pd
import pytest

from experiments.paper1_t1_chronos2 import (
    QUANTILES,
    as_univariate_batch,
    holm,
    merge_model,
    quantile_column,
    size_choice,
    stack_quantiles,
    summarise,
    verdicts,
)


def test_stack_quantiles_drops_variate_axis():
    per_series = [np.full((1, 5, 3), i, dtype=np.float32) for i in range(4)]
    out = stack_quantiles(per_series)
    assert out.shape == (4, 5, 3)
    assert out[2].tolist() == np.full((5, 3), 2.0).tolist()


def test_univariate_batch_is_three_dimensional():
    ctx = np.arange(12, dtype=np.float32).reshape(3, 4)
    out = as_univariate_batch(ctx)
    assert out.shape == (3, 1, 4)
    assert out[1, 0].tolist() == ctx[1].tolist()


def test_quantile_columns_are_unique_and_include_median():
    names = [quantile_column(q) for q in QUANTILES]
    assert len(set(names)) == len(names)
    assert quantile_column(0.5) == "q50" and quantile_column(0.05) == "q05"


def _wide():
    issued = pd.to_datetime(["2026-10-10 00:00", "2026-10-10 00:15"], utc=True)
    return pd.DataFrame({"split": ["lockbox", "lockbox"], "fold": [0, 0], "horizon_minutes": [15, 15], "issued_at": issued, "actual": [28.0, 28.5]})


def test_merge_model_requires_identical_actual():
    wide = _wide()
    fm = wide.assign(prediction=[28.1, 28.4])
    merged, check = merge_model(wide, fm, "m")
    assert merged["m"].tolist() == [28.1, 28.4] and check["matched"] == 2
    with pytest.raises(AssertionError):
        merge_model(wide, fm.assign(actual=[28.0, 28.6]), "m")


def test_holm_matches_hand_computation():
    p = pd.Series([0.01, 0.04, 0.03], index=["a", "b", "c"])
    # sorted 0.01, 0.03, 0.04 -> 0.03, 0.06, max(0.06, 0.04) = 0.06
    assert holm(p).round(6).to_dict() == {"a": 0.03, "b": 0.06, "c": 0.06}


def _gate_and_metrics():
    rows, mrows = [], []
    for h, (win, lose, cand_mae) in {15: (True, False, 0.9), 60: (False, True, 1.2), 180: (False, False, 1.04)}.items():
        rows.append({"horizon_minutes": h, "model": "c2", "reference": "ref", "folds_beating": 5 if win else 1, "lockbox_dm_p": 0.01, "gate16_pass": win})
        rows.append({"horizon_minutes": h, "model": "ref", "reference": "c2", "folds_beating": 5 if lose else 1, "lockbox_dm_p": 0.5, "gate16_pass": lose})
        mrows += [{"split": "lockbox", "model": "c2", "horizon_minutes": h, "mae": cand_mae}, {"split": "lockbox", "model": "ref", "horizon_minutes": h, "mae": 1.0}]
    return pd.DataFrame(rows), pd.DataFrame(mrows)


def test_verdicts_follow_preregistered_rule():
    gate, metrics = _gate_and_metrics()
    table = verdicts(gate, metrics, "c2", ["ref"]).set_index("horizon_minutes")
    assert table.outcome.to_dict() == {15: "chronos2_wins", 60: "reference_wins", 180: "tie"}
    assert table.gap_closed.to_dict() == {15: True, 60: False, 180: True}
    summary = summarise(table.reset_index())["c2__vs__ref"]
    assert summary["overall"] == "mixed" and summary["gap_closed_horizons"] == [15, 180]


def test_size_choice_prefers_base_unless_small_is_close():
    metrics = pd.DataFrame([{"split": "lockbox", "model": m, "horizon_minutes": h, "mae": v}
                            for h, small in ((15, 1.02), (60, 1.01)) for m, v in (("chronos-2-small", small), ("chronos-2-base", 1.0))])
    gate = pd.DataFrame(columns=["model", "reference", "horizon_minutes", "gate16_pass"])
    assert size_choice(gate, metrics)["choice"] == "chronos-2-small"
    worse = metrics.assign(mae=np.where(metrics.model.eq("chronos-2-small"), 1.05, 1.0))
    assert size_choice(gate, worse)["choice"] == "chronos-2-base"
