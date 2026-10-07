# lab/realtime_greenlab/experiments/exp_cluster_eval.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score, r2_score
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import LeaveOneGroupOut
from xgboost import XGBRegressor

from core.impute import build_training_data
from core.config import FEATURES_4

def evaluate_optimal_k(df, region_name):
    print(f"\n{'='*50}\nĐÁNH GIÁ TỐI ƯU HÓA PHÂN CỤM CHO {region_name.upper()}\n{'='*50}")
    
    if df.empty:
        return None
        
    # Chuẩn bị dữ liệu
    if "Quarter" in df.columns:
        month = pd.to_datetime(df["Quarter"]).dt.month
    else:
        month = pd.Series([6]*len(df))
        
    df = df.copy()
    df["month_sin"] = np.sin(2 * np.pi * month / 12)
    df["month_cos"] = np.cos(2 * np.pi * month / 12)
    
    cluster_features = [f for f in FEATURES_4 if f in df.columns] + ["month_sin", "month_cos"]
    df_valid = df.dropna(subset=cluster_features + ["DO", "Station"]).copy()
    
    if len(df_valid) < 30:
        print("Không đủ dữ liệu để phân cụm.")
        return None
        
    X_scale = StandardScaler().fit_transform(df_valid[cluster_features])
    
    # Tính WCSS (Elbow) và Silhouette
    K_range = range(2, 9)
    wcss = []
    sil_scores = []
    
    for k in K_range:
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = kmeans.fit_predict(X_scale)
        wcss.append(kmeans.inertia_)
        sil_scores.append(silhouette_score(X_scale, labels))
        
    # Tìm K tối ưu (dựa trên Silhouette Score cao nhất)
    optimal_k = K_range[np.argmax(sil_scores)]
    max_sil = max(sil_scores)
    
    print(f"-> Phân tích Silhouette Scores: {[round(s, 3) for s in sil_scores]}")
    print(f"-> CHỌN K TỐI ƯU = {optimal_k} (Silhouette = {max_sil:.3f})")
    
    # Vẽ biểu đồ
    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    fig, ax1 = plt.subplots(figsize=(10, 5))
    color = 'tab:red'
    ax1.set_xlabel('Số lượng cụm (K)')
    ax1.set_ylabel('WCSS (Elbow Method)', color=color)
    ax1.plot(K_range, wcss, marker='o', color=color, linewidth=2)
    ax1.tick_params(axis='y', labelcolor=color)
    ax1.grid(True, linestyle="--", alpha=0.6)

    ax2 = ax1.twinx()  
    color = 'tab:blue'
    ax2.set_ylabel('Silhouette Score', color=color)  
    ax2.plot(K_range, sil_scores, marker='s', color=color, linewidth=2)
    ax2.tick_params(axis='y', labelcolor=color)
    
    # Đánh dấu K tối ưu
    ax2.axvline(x=optimal_k, color='green', linestyle='--', label=f'Optimal K={optimal_k}')
    ax2.legend(loc='upper right')

    plt.title(f"Xác định K tối ưu (Elbow & Silhouette) - {region_name}")
    fig.tight_layout()  
    plt.savefig(out_dir / f"optimal_k_{region_name}.png", dpi=300)
    plt.close()
    
    # --- BƯỚC 2: CHẠY LẠI XGboost TRÊN K TỐI ƯU ---
    print(f"\n--- THỰC NGHIỆM DỰ ĐOÁN DO TRÊN {optimal_k} CỤM ---")
    kmeans = KMeans(n_clusters=optimal_k, random_state=42, n_init=10)
    df_valid["Cluster"] = kmeans.fit_predict(X_scale)
    
    logo = LeaveOneGroupOut()
    for c in range(optimal_k):
        df_c = df_valid[df_valid["Cluster"] == c]
        if len(df_c) < 15:
            print(f"Cụm {c} (n={len(df_c)}): Bỏ qua do quá ít dữ liệu để chia Fold.")
            continue
            
        X = df_c[cluster_features].values
        y = df_c["DO"].values
        groups = df_c["Station"].values
        
        preds, trues = [], []
        if len(set(groups)) < 2:
             print(f"Cụm {c} (n={len(df_c)}): Bỏ qua do tập trung ở 1 trạm.")
             continue
             
        for tr, te in logo.split(X, y, groups):
            if len(np.unique(y[tr])) < 2: continue
            m = XGBRegressor(n_estimators=50, max_depth=3, random_state=42, verbosity=0)
            m.fit(X[tr], y[tr])
            preds.extend(m.predict(X[te]))
            trues.extend(y[te])
            
        if len(trues) > 5:
            r2 = r2_score(trues, preds)
            print(f"Cụm {c} (n={len(df_c)}): R² DO = {r2:7.4f} | DO mean = {df_c['DO'].mean():.2f}")
        else:
            print(f"Cụm {c} (n={len(df_c)}): Không đủ mẫu test CV.")
            
    return optimal_k

if __name__ == "__main__":
    df_hp = build_training_data("haiphong")
    df_qn = build_training_data("quangninh")
    
    evaluate_optimal_k(df_hp, "haiphong")
    evaluate_optimal_k(df_qn, "quangninh")
