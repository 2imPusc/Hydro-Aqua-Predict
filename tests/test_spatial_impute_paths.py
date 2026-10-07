import pandas as pd

import core.spatial_impute as spatial_impute


def test_fallback_medians_use_configured_historical_data_path(tmp_path, monkeypatch):
    source = tmp_path / "historical.csv"
    pd.DataFrame(
        {
            "Station": ["NB1", "NB2"],
            "Temperature": [28.0, 29.0],
            "X": [1.0, 2.0],
            "Y": [3.0, 4.0],
        }
    ).to_csv(source, index=False)

    monkeypatch.setattr(spatial_impute, "HP_DATA_PATH", source)
    monkeypatch.setattr(spatial_impute, "FALLBACK_MEDIANS", None)
    monkeypatch.setattr(spatial_impute, "ALL_TARGETS", [])

    medians = spatial_impute.load_fallback_medians()

    assert medians["NB1"]["Temperature"] == 28.0
    assert "X" not in spatial_impute.ALL_TARGETS
