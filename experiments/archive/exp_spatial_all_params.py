import pandas as pd
import numpy as np
from sklearn.model_selection import KFold
from sklearn.metrics import r2_score
from xgboost import XGBRegressor
import warnings
warnings.filterwarnings("ignore")

def evaluate_all_parameters():
    df = pd.read_csv("data/haiphong/clean_data.csv")
    
    anchor_station = "NB1"
    # Lấy 1 trạm vệ tinh tốt nhất làm ví dụ để phân tích sâu (NB15)
    target_station = "NB15"
    
    df_anchor = df[df["Station"] == anchor_station].set_index("Quarter")
    df_target = df[df["Station"] == target_station].set_index("Quarter")
    
    # 1. ĐẦU VÀO (INPUTS): CHỈ sử dụng những biến mà Sensor phần cứng CÓ THỂ ĐO ĐƯỢC
    # Sensor đo: pH, Temp, TSS, NH4 (quy đổi NH3), COD (Lịch sử ko có COD nên bỏ qua COD)
    features = ["pH_anchor", "Temperature_anchor", "TSS_anchor", "NH3_anchor"]
    
    # 2. ĐẦU RA (OUTPUTS): Các chỉ số cần suy diễn (Trừ kim loại nặng vì dùng Trung vị)
    targets = ["DO", "Salinity", "PO4", "Coliform", "TSS", "pH", "Temperature", "NH3"]
    
    merged = df_anchor.join(df_target, lsuffix="_anchor", rsuffix="_target", how="inner")
    
    results = []
    
    for t in targets:
        # Lọc bỏ NaN
        temp_merged = merged.dropna(subset=features + [f"{t}_target"])
        if len(temp_merged) < 10:
            continue
            
        X = temp_merged[features].values
        y = temp_merged[f"{t}_target"].values
        
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
            r2 = r2_score(trues, preds)
            results.append({"Parameter": t, "R2_Score": r2})
            
    res_df = pd.DataFrame(results).sort_values("R2_Score", ascending=False)
    print(f"=== ĐÁNH GIÁ KHẢ NĂNG PHÓNG CHIẾU TẤT CẢ CHỈ SỐ (NB1 -> {target_station}) ===")
    print("Input (Sensor nhà anh Toàn): pH, Nhiệt độ, TSS, NH4")
    print("Output (Dự đoán cho Vụng Trà Báu):\n")
    print(res_df.to_string(index=False))

if __name__ == "__main__":
    evaluate_all_parameters()
