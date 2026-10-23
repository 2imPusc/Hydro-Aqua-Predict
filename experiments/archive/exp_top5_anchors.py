import pandas as pd
import numpy as np
from sklearn.model_selection import KFold
from sklearn.metrics import r2_score
from xgboost import XGBRegressor
from pyproj import Transformer
import warnings
warnings.filterwarnings("ignore")

def evaluate_top5_anchors():
    print("=== TÌM KIẾM ANCHOR TỐT NHẤT TRONG TOP 5 TRẠM GẦN NHẤT ===")
    
    # 1. Tọa độ Sensor Bến Bèo
    lat = 20.733483
    lon = 107.060584
    
    proj_str = "+proj=tmerc +lat_0=0 +lon_0=105.75 +k=0.9999 +x_0=500000 +y_0=0 +ellps=WGS84 +units=m +no_defs"
    transformer_vn = Transformer.from_crs("EPSG:4326", proj_str, always_xy=True)
    x_vn, y_vn = transformer_vn.transform(lon, lat)
    
    # 2. Tìm Top 5 trạm gần nhất
    df = pd.read_csv("data/haiphong/clean_data.csv")
    df_coords = df[['Station', 'Station_Name', 'X', 'Y']].drop_duplicates()
    
    # X=Northing, Y=Easting trong data chuẩn
    df_coords['dist_vn'] = np.sqrt((df_coords['X'] - y_vn)**2 + (df_coords['Y'] - x_vn)**2)
    top5_df = df_coords.sort_values('dist_vn').head(5)
    
    top5_stations = top5_df['Station'].tolist()
    print("Top 5 trạm gần cảm biến nhất:")
    for _, row in top5_df.iterrows():
        print(f"- {row['Station']} ({row['Station_Name']}): {row['dist_vn']:.0f} mét")
        
    print("\nĐang chạy Benchmark chéo cho từng Trạm làm Anchor...")
    
    best_results = []
    features = ["pH_anchor", "Temperature_anchor", "TSS_anchor", "NH3_anchor", "DO_anchor", "Salinity_anchor"]
    
    for anchor in top5_stations:
        df_anchor = df[df["Station"] == anchor].set_index("Quarter")
        if len(df_anchor) < 10:
            print(f"[!] Bỏ qua {anchor} vì chỉ có {len(df_anchor)} dòng dữ liệu.")
            continue
            
        salinity_r2s = []
        target_stations = [s for s in df["Station"].unique() if s != anchor]
        
        for target in target_stations:
            df_target = df[df["Station"] == target].set_index("Quarter")
            merged = df_anchor.join(df_target, lsuffix="_anchor", rsuffix="_target", how="inner")
            merged = merged.dropna(subset=features + ["Salinity_target"])
            
            if len(merged) < 10:
                continue
                
            X = merged[features].values
            y = merged["Salinity_target"].values
            
            if len(np.unique(y)) < 2: continue
                
            kf = KFold(n_splits=3, shuffle=True, random_state=42)
            preds, trues = [], []
            for tr, te in kf.split(X):
                if len(np.unique(y[tr])) < 2: continue
                m = XGBRegressor(n_estimators=50, max_depth=3, learning_rate=0.1, random_state=42, verbosity=0)
                m.fit(X[tr], y[tr])
                preds.extend(m.predict(X[te]))
                trues.extend(y[te])
                
            if len(trues) > 0:
                score = r2_score(trues, preds)
                salinity_r2s.append(score)
                
        if salinity_r2s:
            mean_r2 = np.mean(salinity_r2s)
            positive_ratio = sum(1 for r in salinity_r2s if r > 0.3) / len(salinity_r2s)
            best_results.append({
                "Anchor": anchor,
                "Mean_Salinity_R2": round(mean_r2, 4),
                "Targets_Count": len(salinity_r2s),
                "Success_Ratio (R2>0.3)": f"{positive_ratio*100:.0f}%"
            })
            
    print("\nKết quả Đánh giá Tổng thể (dựa trên khả năng phóng chiếu Độ mặn):")
    res_df = pd.DataFrame(best_results).sort_values("Mean_Salinity_R2", ascending=False)
    print(res_df.to_string(index=False))

if __name__ == "__main__":
    evaluate_top5_anchors()
