import pandas as pd
from pathlib import Path
from experiments.forecast_sensor_v2 import load_sensor_data

def test_sensor_data_parse_fidelity(tmp_path):
    # Output from our inventory script produces %Y-%m-%dT%H:%M:%SZ
    df = pd.DataFrame({
        "fetchedAt": ["2026-09-01T00:00:00Z", "2026-09-01T00:01:00Z"],
        "Temperature": [29.0, 29.1],
        "pH": [7.8, 7.8],
        "NH4": [0.1, 0.1],
        "TSS": [10.0, 10.0]
    })
    path = tmp_path / "standardized_sensor_data.csv"
    df.to_csv(path, index=False)
    
    # Reload using exactly load_sensor_data
    loaded = load_sensor_data(path, "06M26042804")
    
    # Assert timestamp count matches
    assert len(loaded) == 2
    assert loaded["fetchedAt"].iloc[0] == pd.Timestamp("2026-09-01T00:00:00Z")
    
