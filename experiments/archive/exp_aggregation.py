# lab/realtime_greenlab/experiments/exp_aggregation.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from core.fetch import fetch_raw
from core.impute import impute_params
from core.config import FEATURES_4

def run_agg_sensitivity():
    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Cát Bà sensor ID
    df = fetch_raw("06M26042804")
    if df.empty:
        print("No sensor data found.")
        return
        
    df_valid = df.dropna(subset=FEATURES_4).copy()
    if df_valid.empty:
        print("No valid rows with core features.")
        return
        
    # Lọc ra 1 ngày mới nhất có data
    latest_date = df_valid["fetchedAt"].dt.tz_convert("Asia/Bangkok").dt.date.max()
    df_today = df_valid[df_valid["fetchedAt"].dt.tz_convert("Asia/Bangkok").dt.date == latest_date]
    
    if df_today.empty:
        df_today = df_valid
        
    # 3 mức gom
    agg_instant = df_valid.iloc[-1][FEATURES_4].to_dict()
    agg_daily = df_today[FEATURES_4].median().to_dict()
    agg_window = df_valid[FEATURES_4].median().to_dict()
    
    # Impute (HP region, 4feat default for Cat Ba)
    # The impute_params handles missing COD internally
    res_instant = impute_params(agg_instant, region="haiphong")["imputed"]
    res_daily = impute_params(agg_daily, region="haiphong")["imputed"]
    res_window = impute_params(agg_window, region="haiphong")["imputed"]
    
    targets = set(res_instant.keys()) | set(res_daily.keys()) | set(res_window.keys())
    results = []
    
    for t in targets:
        v_inst = res_instant.get(t, np.nan)
        v_day = res_daily.get(t, np.nan)
        v_win = res_window.get(t, np.nan)
        spread = max(v_inst, v_day, v_win) - min(v_inst, v_day, v_win)
        
        results.append({
            "target": t,
            "y_instant": v_inst,
            "y_daily": v_day,
            "y_window": v_win,
            "spread": spread
        })
        
    df_res = pd.DataFrame(results).sort_values("spread", ascending=False)
    df_res.to_csv(out_dir / "agg_sensitivity.csv", index=False)
    print(df_res.to_string())
    
    # Plot figure
    if not df_res.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        
        x = np.arange(len(df_res))
        width = 0.25
        
        ax.bar(x - width, df_res["y_instant"], width, label="Instant")
        ax.bar(x, df_res["y_daily"], width, label="Daily")
        ax.bar(x + width, df_res["y_window"], width, label="Window")
        
        ax.set_xticks(x)
        ax.set_xticklabels(df_res["target"])
        ax.set_ylabel("Imputed Value")
        ax.set_title("Aggregation Sensitivity - Cat Ba Sensor (HP-4feat)")
        ax.legend()
        
        plt.tight_layout()
        plt.savefig(out_dir / "fig_agg_sensitivity.png", dpi=150)
        plt.close()
        
    print("Aggregation sensitivity completed.")
    return df_res

if __name__ == "__main__":
    run_agg_sensitivity()
