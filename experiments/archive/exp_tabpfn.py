# lab/realtime_greenlab/experiments/exp_tabpfn.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import os

# --- NẠP TABPFN VÀ HF TOKEN ---
import re
token_file = Path(__file__).parent / ".env.tabpfn"
if token_file.exists():
    token_text = token_file.read_text(encoding="utf-8")
    
    match_tab = re.search(r'tabpfn_sk_[a-zA-Z0-9_-]+', token_text)
    if match_tab:
        os.environ["TABPFN_TOKEN"] = match_tab.group(0)
        
    match_hf = re.search(r'hf_[a-zA-Z0-9_-]+', token_text)
    if match_hf:
        os.environ["HF_TOKEN"] = match_hf.group(0)
# ------------------------

import pandas as pd
import numpy as np
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.metrics import r2_score
from tabpfn import TabPFNRegressor
from xgboost import XGBRegressor
import warnings

warnings.filterwarnings("ignore")

from core.impute import build_training_data
from core.config import FEATURES_4

def evaluate_tabpfn():
    print("=== THỰC NGHIỆM TABPFN (FOUNDATION MODEL) TRÊN DỮ LIỆU HẢI PHÒNG ===")
    df = build_training_data("haiphong")
    
    if "Quarter" in df.columns:
        month = pd.to_datetime(df["Quarter"]).dt.month
    else:
        month = pd.Series([6]*len(df))
        
    df = df.copy()
    df["month_sin"] = np.sin(2 * np.pi * month / 12)
    df["month_cos"] = np.cos(2 * np.pi * month / 12)
    
    features = [f for f in FEATURES_4 if f in df.columns] + ["month_sin", "month_cos"]
    targets = [c for c in df.columns if c not in features and c not in ["Station", "Time", "Quarter"] and pd.api.types.is_numeric_dtype(df[c])]
    
    logo = LeaveOneGroupOut()
    groups = df["Station"].values
    
    print(f"Tổng số mẫu: {len(df)}")
    print(f"Features: {features}\n")
    
    for target in targets:
        df_valid = df.dropna(subset=features + [target, "Station"])
        X = df_valid[features].values
        y = df_valid[target].values
        g = df_valid["Station"].values
        
        preds_tab = []
        preds_xgb = []
        trues = []
        
        for tr, te in logo.split(X, y, g):
            if len(np.unique(y[tr])) < 2: continue
            
            # TabPFN
            m_tab = TabPFNRegressor()
            m_tab.fit(X[tr], y[tr])
            preds_tab.extend(m_tab.predict(X[te]))
                
            # XGBoost
            m_xgb = XGBRegressor(n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42, verbosity=0)
            m_xgb.fit(X[tr], y[tr])
            preds_xgb.extend(m_xgb.predict(X[te]))
            
            trues.extend(y[te])
            
        if len(trues) > 0 and len(preds_tab) == len(trues):
            r2_tab = r2_score(trues, preds_tab)
            r2_xgb = r2_score(trues, preds_xgb)
            print(f"[{target}] R² TabPFN = {r2_tab:.4f} | R² XGBoost = {r2_xgb:.4f}")
        else:
            print(f"[{target}] Lỗi hoặc không đủ dữ liệu dự đoán.")

if __name__ == "__main__":
    evaluate_tabpfn()
