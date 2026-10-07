# lab/realtime_greenlab/experiments/exp_season.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from core.impute import build_training_data, IMPUTATION_TARGETS, ARTIFACT_TARGETS
from core.config import FEATURES_5, FEATURES_4
from core.experiments._harness import loo_cv_r2

def run_season_ablation():
    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    results = []
    
    for region in ["haiphong", "quangninh"]:
        df = build_training_data(region)
        if df.empty:
            continue
            
        # Extract month and cyclic features
        df["month"] = pd.to_datetime(df["Quarter"]).dt.month
        df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
        df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
        
        for featset_name, base_feats in [("5feat", FEATURES_5), ("4feat", FEATURES_4)]:
            actual_base = [f for f in base_feats if f in df.columns]
            
            for target in IMPUTATION_TARGETS:
                if target not in df.columns:
                    continue
                
                r2_base, n = loo_cv_r2(df, actual_base, target)
                if r2_base is None:
                    continue
                    
                r2_month, _ = loo_cv_r2(df, actual_base + ["month"], target)
                r2_cyc, _ = loo_cv_r2(df, actual_base + ["month_sin", "month_cos"], target)
                
                if r2_month is None or r2_cyc is None:
                    continue
                    
                delta = max(r2_month, r2_cyc) - r2_base
                
                # Decision rules based on spec section 6
                best_variant = "month" if r2_month >= r2_cyc else "cyc"
                
                decision = "reject"
                if target in ARTIFACT_TARGETS:
                    decision = "reject (artifact)"
                elif delta >= 0.03:
                    decision = "adopt"
                elif r2_base < 0.2 and max(r2_month, r2_cyc) >= 0.2:
                    # rescue
                    decision = "adopt (rescue)"
                    
                results.append({
                    "region": region,
                    "featset": featset_name,
                    "target": target,
                    "n": n,
                    "r2_base": r2_base,
                    "r2_month": r2_month,
                    "r2_cyc": r2_cyc,
                    "best_variant": best_variant,
                    "delta": round(delta, 4),
                    "decision": decision
                })
                
    df_res = pd.DataFrame(results)
    df_res.to_csv(out_dir / "season_ablation.csv", index=False)
    print(df_res.to_string())
    
    # Plot figure
    if not df_res.empty:
        fig, ax = plt.subplots(figsize=(14, 7))
        
        labels = df_res["region"].str[:2].str.upper() + "-" + df_res["featset"].str[0] + "f-" + df_res["target"]
        x = np.arange(len(labels))
        
        colors = ["green" if "adopt" in str(d) else "gray" for d in df_res["decision"]]
        
        ax.bar(x, df_res["delta"], color=colors)
        ax.axhline(0.03, color="red", linestyle="--", label="Threshold +0.03")
        ax.axhline(0, color="black", linewidth=0.5)
        
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=90)
        ax.set_ylabel("ΔR² (Season - Base)")
        ax.set_title("Seasonality Ablation - ΔR² per Target")
        ax.legend()
        
        plt.tight_layout()
        plt.savefig(out_dir / "fig_season_delta.png", dpi=150)
        plt.close()
        
    print("Season ablation completed.")
    return df_res

if __name__ == "__main__":
    run_season_ablation()
