# lab/realtime_greenlab/experiments/exp_clustering.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA

from core.impute import build_training_data
from core.config import FEATURES_4

def run_clustering(region: str, n_clusters: int = 3):
    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    df = build_training_data(region)
    if df.empty:
        print(f"No data for {region}")
        return
        
    # Extract month from the timestamp if available, else from quarter
    # Note: load_data usually provides 'time_idx', 'year', 'quarter_num'
    if "Quarter" in df.columns:
        month = pd.to_datetime(df["Quarter"]).dt.month
    elif "date" in df.columns:
        month = pd.to_datetime(df["date"]).dt.month
    else:
        print(f"Cannot find time column for {region}")
        return
        
    df["month_sin"] = np.sin(2 * np.pi * month / 12)
    df["month_cos"] = np.cos(2 * np.pi * month / 12)
    
    # Base features for clustering (we want to cluster states based on real-time available sensors + time)
    cluster_features = [f for f in FEATURES_4 if f in df.columns] + ["month_sin", "month_cos"]
    
    df_valid = df.dropna(subset=cluster_features).copy()
    if len(df_valid) < 20:
        print(f"Not enough valid data for {region}")
        return
        
    X = df_valid[cluster_features].values
    
    # Scale features (Crucial for KMeans)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # KMeans
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    clusters = kmeans.fit_predict(X_scaled)
    df_valid["Cluster"] = clusters
    
    # Profiling clusters (what does each cluster mean?)
    print(f"\n--- TỔNG KẾT CÁC CỤM (CLUSTERS) Ở {region.upper()} ---")
    cluster_profiles = df_valid.groupby("Cluster")[cluster_features].mean()
    
    # Also check what these clusters mean for DO, Salinity (if available)
    eval_targets = [t for t in ["DO", "Salinity", "TSS"] if t in df_valid.columns]
    if eval_targets:
        target_profiles = df_valid.groupby("Cluster")[eval_targets].mean()
        print("Đặc trưng theo chỉ số gốc:")
        print(target_profiles.round(2))
    
    # Print the "Time" profile for each cluster
    print("\nĐặc trưng theo Thời gian & Sensor:")
    for c in range(n_clusters):
        count = (df_valid["Cluster"] == c).sum()
        month_s = cluster_profiles.loc[c, "month_sin"]
        month_c = cluster_profiles.loc[c, "month_cos"]
        # Recover approximate month angle
        angle = np.arctan2(month_s, month_c)
        if angle < 0: angle += 2 * np.pi
        approx_month = int(round(angle / (2 * np.pi) * 12))
        if approx_month == 0: approx_month = 12
        
        temp = cluster_profiles.loc[c, "Temperature"] if "Temperature" in cluster_profiles else np.nan
        ph = cluster_profiles.loc[c, "pH"] if "pH" in cluster_profiles else np.nan
        
        print(f"Cụm {c} (n={count}): Khoảng Tháng {approx_month} | Nhiệt độ: {temp:.1f}°C | pH: {ph:.2f}")

    # Visualization using PCA (Reduce to 2D)
    pca = PCA(n_components=2)
    X_pca = pca.fit_transform(X_scaled)
    df_valid["PCA1"] = X_pca[:, 0]
    df_valid["PCA2"] = X_pca[:, 1]
    
    plt.figure(figsize=(10, 8))
    sns.scatterplot(
        data=df_valid, x="PCA1", y="PCA2", hue="Cluster", 
        palette="viridis", style="Cluster", s=100, alpha=0.8
    )
    plt.title(f"Phân cụm Không gian-Thời gian (KMeans PCA) - {region.upper()}")
    plt.xlabel(f"PCA Component 1 ({pca.explained_variance_ratio_[0]*100:.1f}%)")
    plt.ylabel(f"PCA Component 2 ({pca.explained_variance_ratio_[1]*100:.1f}%)")
    plt.grid(True, linestyle="--", alpha=0.5)
    
    plot_path = out_dir / f"cluster_pca_{region}.png"
    plt.savefig(plot_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"\nSaved PCA plot to {plot_path}")

if __name__ == "__main__":
    run_clustering("haiphong", n_clusters=3)
    print("\n========================================\n")
    run_clustering("quangninh", n_clusters=4)

