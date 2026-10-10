# lab/realtime_greenlab/tests/test_impute.py
import pytest
from core.impute import (
    build_training_data, impute_params, IMPUTATION_TARGETS,
)

@pytest.fixture
def measured_full():
    # COD sống → đường 5-feature
    return {"COD": 10.0, "NH3": 0.05, "pH": 7.8, "Temperature": 28.0, "TSS": 20.0}

@pytest.fixture
def measured_no_cod():
    # COD chết → đường 4-feature
    return {"NH3": 0.05, "pH": 7.8, "Temperature": 28.0, "TSS": 20.0}

@pytest.mark.requires_data
def test_build_training_data_per_region():
    df = build_training_data("haiphong")
    for f in ["NH3", "pH", "Temperature", "TSS"]:
        assert f in df.columns

@pytest.mark.requires_data
def test_build_training_data_no_null_features():
    df = build_training_data("haiphong")
    cols = [c for c in ["NH3", "pH", "Temperature", "TSS"] if c in df.columns]
    assert df[cols].isnull().sum().sum() == 0

def test_impute_5feat_returns_structure(measured_full):
    r = impute_params(measured_full, region="haiphong")
    assert set(r) >= {"imputed", "defaulted", "cv_r2", "feature_set", "region"}
    assert r["feature_set"] == "5feat"

def test_impute_4feat_when_no_cod(measured_no_cod):
    r = impute_params(measured_no_cod, region="haiphong")
    assert r["feature_set"] == "4feat"

def test_impute_region_recorded(measured_no_cod):
    r = impute_params(measured_no_cod, region="haiphong")
    assert r["region"] == "haiphong"

def test_unknown_region_falls_back(measured_no_cod):
    r = impute_params(measured_no_cod, region="khong_ton_tai")
    assert r["region"] == "haiphong"   # DEFAULT_REGION

def test_hp_do_imputed_4feat(measured_no_cod):
    # HP-only: DO đạt R²>=0.4 ngay cả 4feat → phải nằm trong imputed, không phải median
    r = impute_params(measured_no_cod, region="haiphong")
    assert "DO" in r["imputed"]
    assert r["imputed"]["DO"] >= 0

def test_salinity_imputed_strong(measured_full):
    # Salinity R²≈0.6-0.67 cả HP/QN → ML-target mức MẠNH, phải nằm trong imputed
    r = impute_params(measured_full, region="haiphong")
    assert "Salinity" in r["imputed"]
    assert r["confidence"].get("Salinity") == "strong"
    assert "Salinity" not in r["defaulted"]

def test_heavy_metals_still_defaulted(measured_full):
    # Kim loại không đoán được → vẫn median (đã kiểm định R²<0.2)
    r = impute_params(measured_full, region="quangninh")
    assert "As" in r["defaulted"] and "As" not in r["imputed"]

def test_cod_defaulted_when_absent(measured_no_cod):
    # COD chết → vắng trong measured → defaulted (QN có cột COD; HP không có)
    r = impute_params(measured_no_cod, region="quangninh")
    assert "COD" in r["defaulted"]
