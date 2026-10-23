# lab/realtime_greenlab/tests/test_classify.py
import pytest
from core.classify import classify_station, LABEL_NAMES

@pytest.fixture
def measured_no_cod():
    return {"NH3": 0.01, "pH": 7.9, "Temperature": 30.0, "TSS": 47.0}

def test_required_keys(measured_no_cod):
    r = classify_station("06M26042804", measured_no_cod, "cobia", region="haiphong")
    for k in ["label", "score", "params", "imputed_fraction", "feature_set", "region", "warning"]:
        assert k in r

def test_score_in_range(measured_no_cod):
    r = classify_station("06M26042804", measured_no_cod, "cobia")
    assert 0.0 <= r["score"] <= 1.0

def test_label_valid(measured_no_cod):
    r = classify_station("06M26042804", measured_no_cod, "cobia")
    assert r["label"] in LABEL_NAMES.values()

def test_imputed_fraction_range(measured_no_cod):
    r = classify_station("06M26042804", measured_no_cod, "cobia")
    assert 0.0 <= r["imputed_fraction"] <= 1.0

def test_provenance_groups(measured_no_cod):
    r = classify_station("06M26042804", measured_no_cod, "cobia")
    for g in ["measured", "imputed", "defaulted"]:
        assert g in r["params"]
    assert "NH3" in r["params"]["measured"]

def test_oyster_path(measured_no_cod):
    r = classify_station("06M26042803", measured_no_cod, "oyster", region="quangninh")
    assert r["label"] in LABEL_NAMES.values()
    assert r["region"] == "quangninh"
