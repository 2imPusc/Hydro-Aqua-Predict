"""Two ammonia quantities: TAN (provincial/QCVN/imputer/HSI basis) vs un-ionised NH3 (toxicity)."""
import math

import numpy as np
import pandas as pd
import pytest

from core import chemistry, config, impute
from core.alerts import evaluate_aquaculture_risk
from core.chemistry import emerson_nh3, nh3_fraction, provincial_basis_row, tan_mg_l
from core.monitor import check_params


# --- chemistry -------------------------------------------------------------------

def test_tan_is_raw_times_unit_scale_by_default():
    assert config.NH4_TO_N_FACTOR == 1.0
    assert tan_mg_l(114.59) == pytest.approx(0.11459)
    assert tan_mg_l(-3.0) == 0.0


def test_tan_applies_n_factor(monkeypatch):
    assert tan_mg_l(100.0, n_factor=0.7766) == pytest.approx(0.07766)
    monkeypatch.setattr(chemistry, "NH4_TO_N_FACTOR", 0.7766)
    assert tan_mg_l(100.0) == pytest.approx(0.07766)
    # The toxic fraction shares the factor: NH3 = TAN × Emerson fraction.
    assert emerson_nh3(100.0, 8.0, 28.0) == pytest.approx(0.07766 * nh3_fraction(8.0, 28.0))


def test_unionised_nh3_is_a_fraction_of_tan():
    tan, nh3 = tan_mg_l(107.0), emerson_nh3(107.0, 7.9, 29.0)
    assert nh3 == pytest.approx(tan * nh3_fraction(7.9, 29.0))
    assert 10 < tan / nh3 < 40   # 13–25× at Cát Bà conditions


def test_provincial_basis_row_fills_nh3_slot_from_tan_only():
    row = provincial_basis_row({"TAN": 0.1, "NH3": 0.004, "pH": 7.9})
    assert row["NH3"] == 0.1 and row["pH"] == 7.9
    # Without TAN the un-ionised value must not leak into the provincial slot.
    assert "NH3" not in provincial_basis_row({"NH3": 0.004, "pH": 7.9})
    assert "NH3" not in provincial_basis_row({"TAN": float("nan"), "NH3": 0.004})


def test_fetch_raw_derives_both_tan_and_unionised_nh3(monkeypatch):
    from core import fetch
    history = pd.DataFrame({"device": ["06M26042804"], "fetchedAt": ["2026-07-26T11:21:29Z"],
                            "COD": [1.0], "NH4": [107.0], "pH": [7.9], "Temperature": [29.0], "TSS": [5.0]})
    monkeypatch.setattr(fetch, "USE_LOCAL_CSV", False)
    monkeypatch.setattr(fetch, "GREENLAB_FETCH_MODE", "cache")
    monkeypatch.setattr(fetch, "load_cached_history", lambda station: history.copy())
    out = fetch.fetch_raw("06M26042804")
    assert out["TAN"].iloc[0] == pytest.approx(0.107)
    assert out["NH3"].iloc[0] == pytest.approx(emerson_nh3(107.0, 7.9, 29.0))


# --- imputer ---------------------------------------------------------------------

class _Recorder:
    def __init__(self):
        self.rows = []

    def predict(self, X):
        self.rows.append(np.asarray(X, dtype=float)[0].tolist())
        return np.array([5.0])


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(impute.joblib, "load", lambda path: rec)
    return rec


def test_imputer_receives_tan_not_unionised_nh3(recorder):
    result = impute.impute_params({"TAN": 0.1, "NH3": 0.004, "pH": 7.9, "Temperature": 28.0, "TSS": 20.0}, region="haiphong")
    features = result["diagnostics"]["feature_values"]
    assert features["NH3"] == 0.1
    assert recorder.rows and all(row[0] == 0.1 for row in recorder.rows)   # "NH3" is the first model feature
    assert result["diagnostics"]["ammonia_basis"] == "TAN"
    assert result["diagnostics"]["missing_features"] == []


def test_imputer_without_tan_marks_ammonium_missing(recorder):
    result = impute.impute_params({"NH3": 0.004, "pH": 7.9, "Temperature": 28.0, "TSS": 20.0}, region="haiphong")
    assert result["diagnostics"]["missing_features"] == ["NH3"]
    assert result["input_flagged"] is True
    assert all(math.isnan(row[0]) for row in recorder.rows)


def test_low_tan_is_flagged_out_of_training_range():
    low = impute.impute_params({"TAN": 0.004, "pH": 7.9, "Temperature": 28.0, "TSS": 20.0}, region="haiphong")
    diag = low["diagnostics"]
    assert diag["bounds_source"] == "imputer_feature_bounds.json"
    assert "NH3" in diag["ood_features"] and diag["ood"] is True
    assert 0.004 < diag["training_range"]["NH3"][0]
    assert "DO" in diag["ood_targets"]
    normal = impute.impute_params({"TAN": 0.1, "pH": 7.9, "Temperature": 28.0, "TSS": 20.0}, region="haiphong")
    assert "NH3" not in normal["diagnostics"]["ood_features"]


def test_bounds_file_is_on_provincial_tan_basis():
    bounds = impute._load_bounds()
    hp = bounds["regions"]["haiphong"]["NH3"]
    assert 0.02 <= hp["p_lo"] < hp["p_hi"] <= 0.8
    assert bounds["quantiles"] == [0.01, 0.99]


# --- QCVN / alerts ---------------------------------------------------------------

def test_qcvn_ammonium_limit_uses_tan():
    assert "NH3" not in config.QCVN10_B1 and config.QCVN10_B1["TAN"] == {"max": 0.1}
    r = check_params({"TAN": 0.15, "NH3": 0.005, "pH": 7.9})
    assert r["TAN"].status == "EXCEED" and "NH3" not in r
    r = check_params({"TAN": 0.05, "NH3": 0.2})
    assert r["TAN"].status == "OK" and "NH3" not in r


def _history(**columns):
    n = len(next(iter(columns.values())))
    times = pd.date_range("2026-07-01T00:00:00Z", periods=n, freq="1min")
    return pd.DataFrame({"fetchedAt": times, **columns})


def test_toxicity_alert_uses_unionised_nh3_not_tan():
    quiet = evaluate_aquaculture_risk(_history(Temperature=[29.0] * 4, NH3=[0.01] * 4, TAN=[0.5] * 4))
    assert not [d for d in quiet["drivers"] if d["metric"] in {"NH3", "TAN"}]
    watch = evaluate_aquaculture_risk(_history(Temperature=[29.0] * 4, NH3=[0.06] * 4, TAN=[0.06] * 4))
    driver = next(d for d in watch["drivers"] if d["metric"] == "NH3")
    assert driver["value"] == 0.06 and driver["label"] == "NH3 không ion (độc tính)"


# --- contextual models (same provincial basis) -----------------------------------

def test_contextual_model_feature_nh3_is_fed_from_tan(monkeypatch):
    from core import contextual_models
    monkeypatch.setattr(contextual_models, "NH4_CONVERSION_CONFIRMED", True)
    sensors = {"pH": 7.8, "Temperature": 29.0, "TSS": 10.0}
    ok = contextual_models.predict_haiphong_contextual({**sensors, "TAN": 0.1, "NH3": 0.004}, "2026-07-25T00:00:00Z")
    assert ok["predictions"]["DO"]["status"] == "accepted"
    no_tan = contextual_models.predict_haiphong_contextual({**sensors, "NH3": 0.1}, "2026-07-25T00:00:00Z")
    assert no_tan["predictions"]["DO"]["missing_features"] == ["NH3"]
    low = contextual_models.predict_haiphong_contextual({**sensors, "TAN": 0.004}, "2026-07-25T00:00:00Z")
    assert low["predictions"]["DO"]["ood_features"] == ["NH3"]


def test_classify_scores_hsi_with_tan_and_reports_ood():
    from core.classify import classify_station
    base = {"pH": 7.9, "Temperature": 28.0, "TSS": 20.0}
    high = classify_station("06M26042804", {**base, "TAN": 0.3, "NH3": 0.01}, "cobia", region="haiphong")
    low = classify_station("06M26042804", {**base, "TAN": 0.05, "NH3": 0.01}, "cobia", region="haiphong")
    assert high["score"] < low["score"]   # HSI NH3 breakpoints see TAN
    tiny = classify_station("06M26042804", {**base, "TAN": 0.004, "NH3": 0.0002}, "cobia", region="haiphong")
    assert "NH3" in tiny["imputation_diagnostics"]["ood_features"]
    assert "OOD" in tiny["warning"]
