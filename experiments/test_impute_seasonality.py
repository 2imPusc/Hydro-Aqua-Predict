# lab/realtime_greenlab/experiments/test_impute_seasonality.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.impute import impute_params
import json

def test():
    print("=== TEST HAIPHONG ===")
    measured_hp = {
        "pH": 7.9,
        "Temperature": 28.5,
        "TSS": 15.0,
        "NH4": 0.5,
        "fetchedAt": "2026-07-15T12:00:00Z" # July
    }
    res_hp = impute_params(measured_hp, region="haiphong")
    print(json.dumps(res_hp["imputed"], indent=2))
    
    print("\n=== TEST QUANGNINH ===")
    measured_qn = {
        "pH": 8.1,
        "Temperature": 24.0,
        "TSS": 6.0,
        "NH4": 0.1,
        "date": "2026-12-01" # December
    }
    res_qn = impute_params(measured_qn, region="quangninh")
    print(json.dumps(res_qn["imputed"], indent=2))

if __name__ == "__main__":
    test()
