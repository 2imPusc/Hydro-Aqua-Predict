import pandas as pd
import numpy as np
from sklearn.model_selection import KFold
from sklearn.metrics import r2_score
from xgboost import XGBRegressor
import joblib
import os
import warnings
warnings.filterwarnings("ignore")

def train_all_spatial_models():
    print("=== HUẤN LUYỆN MẠNG LƯỚI TRẠM ẢO (VIRTUAL SENSOR NETWORK) ===")
    
    df = pd.read_csv("data/haiphong/clean_data.csv")
    anchor_station = "NB2"
    all_stations = df["Station"].unique()
    target_stations = [s for s in all_stations if s != anchor_station]
    
    df_anchor = df[df["Station"] == anchor_station].set_index("Quarter")
    
    # Sử dụng toàn bộ 8 biến cốt lõi của Trạm Mỏ neo (sau khi đã được Local Impute)
    features = ["pH_anchor", "Temperature_anchor", "TSS_anchor", "NH3_anchor", 
                "DO_anchor", "Salinity_anchor", "PO4_anchor", "Coliform_anchor"]
    
    # Biến cần dự đoán cho các Trạm Ảo
    targets = ["DO", "Salinity", "PO4", "Coliform", "TSS", "pH", "Temperature", "NH3"]
    
    os.makedirs("core/models/spatial", exist_ok=True)
    
    success_count = 0
    
    for target_station in target_stations:
        df_target = df[df["Station"] == target_station].set_index("Quarter")
        merged = df_anchor.join(df_target, lsuffix="_anchor", rsuffix="_target", how="inner")
        
        for t in targets:
            # Lọc NaN
            temp_merged = merged.dropna(subset=features + [f"{t}_target"])
            if len(temp_merged) < 10:
                continue
                
            X = temp_merged[features].values
            y = temp_merged[f"{t}_target"].values
            
            if len(np.unique(y)) < 2: continue
                
            # Đánh giá R2 bằng Cross-validation
            kf = KFold(n_splits=3, shuffle=True, random_state=42)
            preds, trues = [], []
            
            for tr, te in kf.split(X):
                if len(np.unique(y[tr])) < 2: continue
                m_cv = XGBRegressor(n_estimators=50, max_depth=3, learning_rate=0.1, random_state=42, verbosity=0)
                m_cv.fit(X[tr], y[tr])
                preds.extend(m_cv.predict(X[te]))
                trues.extend(y[te])
                
            if len(trues) > 0:
                r2 = r2_score(trues, preds)
                
                # CHỈ LƯU MÔ HÌNH NẾU R2 > 0.5 (Ngưỡng chất lượng Spatial Imputation)
                if r2 > 0.5:
                    # Train model cuối cùng trên toàn bộ dữ liệu
                    final_model = XGBRegressor(n_estimators=50, max_depth=3, learning_rate=0.1, random_state=42, verbosity=0)
                    final_model.fit(X, y)
                    
                    model_path = f"core/models/spatial/{anchor_station}_{target_station}_{t}.pkl"
                    joblib.dump(final_model, model_path)
                    print(f"[+] Đã lưu Model: {anchor_station} -> {target_station} | {t} (R² = {r2:.4f})")
                    success_count += 1
                    
    print(f"\n[Hoàn tất] Đã huấn luyện thành công {success_count} mô hình phóng chiếu Không gian đủ tiêu chuẩn!")

if __name__ == "__main__":
    train_all_spatial_models()
