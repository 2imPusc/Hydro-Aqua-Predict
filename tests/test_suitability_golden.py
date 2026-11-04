"""Golden test for suitability scoring (H4.2, decisions #H42).

``tests/fixtures/suitability_golden.json`` holds outputs of the pre-refactor rule scorer
(``_classify_by_scoring``) and the legacy cobia HSI (``core.spatial_overlay`` and its copy in
``experiments.spatial_applicability``). Every public entry point must reproduce it exactly.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from core.spatial_overlay import _legacy_hsi, _legacy_hsi_label
from experiments.spatial_applicability import cobia_hsi, hsi_label
from hap_shared.classification import _classify_by_scoring

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "suitability_golden.json").read_text(encoding="utf-8"))


def _nan(value):
    return float("nan") if value is None else value


def _same(got, want) -> bool:
    got = float(got)
    return math.isnan(got) if want is None else got == want


def _rule_frame(species: str) -> pd.DataFrame:
    return pd.DataFrame(GOLDEN["rule"][species]["rows"]).astype(float)


RULE_CASES = [(sp, name) for sp, case in GOLDEN["rule"].items() for name in case["subsets"]]


@pytest.mark.parametrize("species,subset", RULE_CASES)
def test_classify_by_scoring_matches_golden(species, subset):
    want = GOLDEN["rule"][species]["subsets"][subset]
    out = _classify_by_scoring(_rule_frame(species), want["params"], species)
    assert list(out["suitability_score"]) == want["score"]
    assert [int(v) for v in out["suitability_label"]] == want["label"]
    assert list(out["suitability_name"]) == want["name"]
    assert list(out["classification_method"]) == want["method"]


def _hsi_rows():
    return [pd.Series(row, dtype=object) for row in GOLDEN["hsi"]["rows"]]


def test_legacy_hsi_matches_golden():
    for row, want in zip(_hsi_rows(), GOLDEN["hsi"]["scores"], strict=True):
        got = _legacy_hsi(row)
        assert _same(got, want["legacy"]), (dict(row), got, want)
        assert _legacy_hsi_label(got) == want["legacy_label"]


def test_experiment_cobia_hsi_matches_golden():
    for row, want in zip(_hsi_rows(), GOLDEN["hsi"]["scores"], strict=True):
        got = cobia_hsi(row)
        assert _same(got, want["experiment"]), (dict(row), got, want)
        assert hsi_label(got) == want["experiment_label"]


def test_hsi_labels_match_golden():
    for probe in GOLDEN["hsi"]["label_probes"]:
        value = _nan(probe["value"])
        assert _legacy_hsi_label(value) == probe["legacy"]
        assert hsi_label(value) == probe["experiment"]
