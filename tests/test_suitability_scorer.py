"""Unit tests for hap_shared.suitability_scorer (H4.2, decisions #31)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from experiments.spatial_applicability import COBIA_RULES
from hap_shared.suitability_scorer import (
    LEGACY_COBIA_HSI, ClassScheme, Criterion, SuitabilityConfig, SuitabilityScorer, legacy_cobia_hsi,
    species_rule_config,
)

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "suitability_golden.json").read_text(encoding="utf-8"))


def test_vectorised_legacy_hsi_matches_golden_rows():
    """Callers now score whole frames at once; that must equal the old row-by-row apply."""
    got = legacy_cobia_hsi(pd.DataFrame(GOLDEN["hsi"]["rows"]))
    for value, want in zip(got, GOLDEN["hsi"]["scores"], strict=True):
        assert (math.isnan(value) if want["legacy"] is None else value == want["legacy"])


def test_mean_equals_numpy_mean_of_present_scores():
    """Original HSI = float(np.mean(list_of_present_scores)); check the vectorised sum/count on random rows."""
    rng = np.random.default_rng(7)
    n = 5000
    frame = pd.DataFrame({"DO": rng.uniform(0, 12, n), "Temperature": rng.uniform(10, 40, n),
                          "pH": rng.uniform(6, 10, n), "Salinity": rng.uniform(0, 45, n),
                          "NH3": rng.uniform(0, 0.3, n), "TSS": rng.uniform(0, 120, n)})
    frame = frame.mask(rng.random(frame.shape) < 0.25)
    result = SuitabilityScorer(LEGACY_COBIA_HSI).score(frame)
    for i in range(n):
        present = [v for v in result.membership.iloc[i] if not math.isnan(v)]
        want = float(np.mean(present)) if present else float("nan")
        got = float(result.score.iloc[i])
        assert (math.isnan(got) and math.isnan(want)) or got == want


def test_legacy_config_matches_experiment_rules():
    assert [c.name for c in LEGACY_COBIA_HSI.criteria] == list(COBIA_RULES)
    for c in LEGACY_COBIA_HSI.criteria:
        assert (c.kind, *c.params) == COBIA_RULES[c.name]


def test_rule_result_contributions_flags_and_classes():
    config = species_rule_config("cobia")
    frame = pd.DataFrame({"DO": [5.5, np.nan, 20.0], "Temperature": [27.0, 27.0, 27.0], "Other": [1, 2, 3]})
    result = SuitabilityScorer(config).score(frame, criteria=["DO", "Temperature", "Other"])
    assert result.used == ["DO", "Temperature"]
    assert result.weights == pytest.approx({"DO": 2 / 3, "Temperature": 1 / 3})
    assert np.allclose(result.contributions.sum(axis=1), result.score)
    assert list(result.missing["DO"]) == [False, True, False]
    assert list(result.ood["DO"]) == [False, False, True]          # 20 mg/L beyond the 0–10 breakpoint domain
    assert result.contributions.loc[1, "DO"] == pytest.approx(0.5 * 2 / 3)  # missing → neutral 0.5
    frame_out = result.to_frame()
    assert {"suitability_score", "suitability_label", "suitability_name", "contrib_DO", "missing_DO", "ood_DO",
            "n_missing", "n_ood"} <= set(frame_out.columns)
    assert list(frame_out["n_missing"]) == [0, 1, 0]


def test_rule_unknown_requested_column_raises():
    with pytest.raises(KeyError):
        SuitabilityScorer(species_rule_config("cobia")).score(pd.DataFrame({"DO": [6.0]}), criteria=["DO", "pH"])


def test_legacy_reports_absent_criteria_as_missing():
    result = SuitabilityScorer(LEGACY_COBIA_HSI).score(pd.DataFrame({"DO": [3.0], "pH": [8.2]}))
    assert result.used == ["DO", "pH"]
    assert result.score.iloc[0] == pytest.approx((0.5 + 1.0) / 2)
    assert result.to_frame()["n_missing"].iloc[0] == 4
    assert result.label.iloc[0] == "suitable"                     # 0.75 reaches the 0.75 cut
    empty = SuitabilityScorer(LEGACY_COBIA_HSI).score(pd.DataFrame({"x": [1.0]}))
    assert math.isnan(empty.score.iloc[0]) and empty.label.iloc[0] == "not_suitable"


def test_fixed_weights_and_valid_range():
    config = SuitabilityConfig(
        name="toy", weighting="fixed",
        criteria=(Criterion("a", "min", (2.0,), weight=3.0, valid_range=(0.0, 5.0)), Criterion("b", "max", (10.0,), weight=1.0)),
        classes=ClassScheme((0.5,), ("low", "high")))
    result = SuitabilityScorer(config).score(pd.DataFrame({"a": [1.0, 9.0], "b": [5.0, 5.0]}))
    assert list(result.score) == pytest.approx([0.75 * 0.5 + 0.25 * 0.5, 0.75 + 0.25 * 0.5])
    assert list(result.ood["a"]) == [False, True]
    assert list(result.label) == ["high", "high"]


def test_config_validation():
    with pytest.raises(ValueError):
        Criterion("x", "bogus", ())
    with pytest.raises(ValueError):
        ClassScheme((0.7, 0.5), (0, 1, 2))
    with pytest.raises(ValueError):
        SuitabilityConfig(name="bad", criteria=(), classes=ClassScheme((), ("a",)), aggregation="mean", missing="neutral")
