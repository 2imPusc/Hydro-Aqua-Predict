# lab/realtime_greenlab/experiments/exp_deepdive.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.metrics import r2_score
from xgboost import XGBRegressor
from sklearn.preprocessing import StandardScaler

from core.impute import build_training_data, MEDIAN_DEFAULTS
from core.config import FEATURES_4

def analyze_heavy_metals(df_qn, df_hp):
    print("=== 1. Phân tích Phân bố Kim loại nặng (Heavy Metals) ===")
    metals = ["As", "Cd", "Pb", "Cu", "Zn", "Hg"]
    
    for name, df in [("Hải Phòng", df_hp), ("Quảng Ninh", df_qn)]:
        if df.empty: continue
        valid_cols = [c for c in metals if c in df.columns]
        desc = df[valid_cols].describe().T[['mean', 'std', 'min', 'max']]
        # Tính hệ số biến thiên (Coefficient of Variation = std/mean)
        desc['CV (%)'] = (desc['std'] / desc['mean'] * 100).round(2)
        print(f"\n{name}:")
        print(desc.round(4))

def analyze_data_leakage(df_qn, df_hp):
    print("\n=== 2. Phân tích Rò rỉ Dữ liệu (Data Leakage - BOD5, Alkalinity) ===")
    targets = ["COD", "BOD5", "Alkalinity", "DO"]
    for name, df in [("Hải Phòng", df_hp), ("Quảng Ninh", df_qn)]:
        if df.empty: continue
        valid_cols = [c for c in targets if c in df.columns]
        if len(valid_cols) > 1:
            corr = df[valid_cols].corr()
            print(f"\nMa trận tương quan {name}:")
            print(corr.round(4))
            
            # Kiểm tra công thức BOD5 = a * COD
            if "BOD5" in df.columns and "COD" in df.columns:
                ratio = (df["BOD5"] / df["COD"]).describe()
                print(f"Tỉ lệ BOD5 / COD ở {name}: mean={ratio['mean']:.4f}, std={ratio['std']:.4f}")

def analyze_do_clusters(df, name):
    print(f"\n=== 3. Phân tích DO ở {name} (Cluster-based XGBoost) ===")
    if df.empty or "DO" not in df.columns:
        return
        
    print(f"Thống kê chung DO ở {name}: mean={df['DO'].mean():.2f}, std={df['DO'].std():.2f}")
    
    # Tạo cụm như exp_clustering
    if "Quarter" in df.columns:
        month = pd.to_datetime(df["Quarter"]).dt.month
    else:
        month = pd.Series([6]*len(df)) # Fake fallback
        
    df = df.copy()
    df["month_sin"] = np.sin(2 * np.pi * month / 12)
    df["month_cos"] = np.cos(2 * np.pi * month / 12)
    
    cluster_features = [f for f in FEATURES_4 if f in df.columns] + ["month_sin", "month_cos"]
    df_valid = df.dropna(subset=cluster_features + ["DO", "Station"]).copy()
    
    X_scale = StandardScaler().fit_transform(df_valid[cluster_features])
    
    n_clusters = 3 if name == "Hải Phòng" else 4
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    df_valid["Cluster"] = kmeans.fit_predict(X_scale)
    
    # Thử chạy XGBoost DO trên TỪNG CỤM
    logo = LeaveOneGroupOut()
    for c in range(n_clusters):
        df_c = df_valid[df_valid["Cluster"] == c]
        if len(df_c) < 20:
            print(f"Cụm {c}: Quá ít dữ liệu ({len(df_c)} mẫu)")
            continue
            
        X = df_c[cluster_features].values
        y = df_c["DO"].values
        groups = df_c["Station"].values
        
        preds, trues = [], []
        # Fallback if only 1 group
        if len(set(groups)) < 2:
             continue
             
        for tr, te in logo.split(X, y, groups):
            if len(np.unique(y[tr])) < 2: continue # Needs variance to train
            m = XGBRegressor(n_estimators=50, max_depth=3, random_state=42, verbosity=0)
            m.fit(X[tr], y[tr])
            preds.extend(m.predict(X[te]))
            trues.extend(y[te])
            
        if len(trues) > 5:
            r2 = r2_score(trues, preds)
            print(f"Cụm {c} (n={len(df_c)}): R² DO = {r2:.4f} | DO mean={df_c['DO'].mean():.2f}, std={df_c['DO'].std():.2f}")

if __name__ == "__main__":
    df_hp = build_training_data("haiphong")
    df_qn = build_training_data("quangninh")
    
    # analyze_heavy_metals(df_qn, df_hp)
    # analyze_data_leakage(df_qn, df_hp)
    analyze_do_clusters(df_hp, "Hải Phòng")
    analyze_do_clusters(df_qn, "Quảng Ninh")
