import pandas as pd
import pytest

from core.observations import apply_range_qc, contract_issues, to_raw_observations, validate_observations


def test_raw_observations_are_long_form_and_qc_is_separate():
    wide = pd.DataFrame({"fetchedAt": ["2026-07-24T00:00:00Z"], "Temperature": [29.5], "TSS": [1500.0]})
    raw = to_raw_observations(wide, "06M26042804", "local_csv")
    assert set(raw["qc_status"]) == {"UNCHECKED"}
    assert len(raw) == 2

    qc = apply_range_qc(raw)
    assert raw.loc[raw.metric == "TSS", "qc_status"].item() == "UNCHECKED"
    assert qc.loc[qc.metric == "TSS", "qc_status"].item() == "INVALID"


def test_contract_rejects_duplicate_observation_ids():
    raw = to_raw_observations(
        pd.DataFrame({"fetchedAt": ["2026-07-24T00:00:00Z"], "pH": [7.5]}),
        "06M26042804", "local_csv",
    )
    with pytest.raises(ValueError, match="unique"):
        validate_observations(pd.concat([raw, raw], ignore_index=True))


def test_unverified_nh4_to_nh3_conversion_basis_is_visible(monkeypatch):
    # Hermetic: the real .env may already confirm the conversion.
    monkeypatch.setattr("core.observations.NH4_CONVERSION_CONFIRMED", False)
    assert "nh4_conversion_basis_unverified" in contract_issues("06M26042804")


def test_confirmed_nh4_basis_is_not_flagged(monkeypatch):
    monkeypatch.setattr("core.observations.NH4_CONVERSION_CONFIRMED", True)
    assert "nh4_conversion_basis_unverified" not in contract_issues("06M26042804")
