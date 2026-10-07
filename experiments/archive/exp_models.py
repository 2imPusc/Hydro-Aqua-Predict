# lab/realtime_greenlab/experiments/exp_models.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
from xgboost import XGBRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge

from core.impute import build_training_data, IMPUTATION_TARGETS
from core.config import FEATURES_5, FEATURES_4
from core.experiments._harness import loo_cv_r2

def run_model_comparison():
    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    models = {
        "XGBoost": None, # Defaults to XGBRegressor in harness
        "RandomForest": RandomForestRegressor(n_estimators=100, max_depth=4, random_state=42),
        "Ridge": Ridge(alpha=1.0)
    }
    
    results = []
    
    for region in ["haiphong", "quangninh"]:
        df = build_training_data(region)
        if df.empty:
            continue
            
        for featset_name, base_feats in [("5feat", FEATURES_5), ("4feat", FEATURES_4)]:
            actual_base = [f for f in base_feats if f in df.columns]
            
            for target in IMPUTATION_TARGETS:
                if target not in df.columns:
                    continue
                
                # Check if we have enough valid data before running all models
                required_cols = actual_base + [target, "Station"]
                df_valid = df.dropna(subset=required_cols)
                if len(df_valid) < 20 or df_valid["Station"].nunique() < 3:
                    continue
                
                row = {
                    "region": region,
                    "featset": featset_name,
                    "target": target,
                    "n": len(df_valid)
                }
                
                for model_name, estimator in models.items():
                    r2, _ = loo_cv_r2(df, actual_base, target, estimator=estimator)
                    row[f"r2_{model_name}"] = r2
                    
                results.append(row)
                
    df_res = pd.DataFrame(results)
    
    # Sort and save
    df_res = df_res.sort_values(by=["region", "featset", "target"])
    df_res.to_csv(out_dir / "model_comparison.csv", index=False)
    
    print(df_res.to_string())
    print(f"\nModel comparison completed. Saved to {out_dir / 'model_comparison.csv'}")

if __name__ == "__main__":
    run_model_comparison()
