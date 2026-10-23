import pandas as pd
import numpy as np
from sklearn.model_selection import LeaveOneGroupOut, KFold
from sklearn.metrics import r2_score
from xgboost import XGBRegressor

def evaluate_spatial_imputation():
    print("=== THỰC NGHIỆM TRẠM ẢO (SPATIAL SENSOR NETWORK) ===")
    
    # 1. Đọc dữ liệu
    df = pd.read_csv("data/haiphong/clean_data.csv")
    
    # Trạm Anchor (Đại diện proxy cho trạm Làng bè anh Toàn - cách 1.8km)
    anchor_station = "NB1"
    # Trạm Target (Cần dự báo, ví dụ Bến Bèo)
    target_station = "NB2"
    
    print(f"Anchor Station (Input): {anchor_station}")
    print(f"Target Station (Output): {target_station}")
    
    df_anchor = df[df["Station"] == anchor_station].set_index("Quarter")
    df_target = df[df["Station"] == target_station].set_index("Quarter")
    
    # Nối theo cột Quarter để căn chỉnh thời gian
    merged = df_anchor.join(df_target, lsuffix="_anchor", rsuffix="_target", how="inner")
    
    if merged.empty:
        print("Không có dữ liệu trùng khớp thời gian giữa 2 trạm.")
        return
        
    print(f"Số lượng mẫu chung thời gian: {len(merged)}")
    
    # 2. Xây dựng ma trận
    # Input: Các chỉ số đo được ở trạm Anchor
    features = ["pH_anchor", "Temperature_anchor", "TSS_anchor", "NH3_anchor", "DO_anchor", "Salinity_anchor"]
    # Output: Cần đoán DO và Salinity ở trạm Target
    targets = ["DO_target", "Salinity_target", "PO4_target"]
    
    # Bỏ dòng NaN
    merged = merged.dropna(subset=features + targets)
    if len(merged) < 5:
        print("Không đủ dữ liệu sạch sau khi dropna.")
        return
        
    X = merged[features].values
    
    print("\nKết quả kiểm định Không gian chéo (Cross-validation):")
    kf = KFold(n_splits=3, shuffle=True, random_state=42)
    
    for target in targets:
        y = merged[target].values
        
        preds = []
        trues = []
        
        for tr, te in kf.split(X):
            if len(np.unique(y[tr])) < 2: continue
            
            m = XGBRegressor(n_estimators=100, max_depth=3, learning_rate=0.1, random_state=42, verbosity=0)
            m.fit(X[tr], y[tr])
            preds.extend(m.predict(X[te]))
            trues.extend(y[te])
            
        if len(trues) > 0:
            r2 = r2_score(trues, preds)
            print(f"  -> Đoán {target}: R² = {r2:.4f}")
            
    print("\nKết luận: Nếu R² > 0.5, tính khả thi của Trạm ảo là CỰC KỲ CAO.")

if __name__ == "__main__":
    evaluate_spatial_imputation()
