import pandas as pd
import numpy as np
from sklearn.model_selection import KFold
from sklearn.metrics import r2_score
from xgboost import XGBRegressor
import warnings
warnings.filterwarnings("ignore")

def evaluate_all_stations():
    print("=== THỰC NGHIỆM TRẠM ẢO TOÀN DIỆN (ALL STATIONS) ===")
    
    df = pd.read_csv("data/haiphong/clean_data.csv")
    
    # Cố định Anchor Station là Trạm Mỏ neo (NB1 proxy cho Làng bè anh Toàn)
    anchor_station = "NB1"
    all_stations = df["Station"].unique()
    target_stations = [s for s in all_stations if s != anchor_station]
    
    df_anchor = df[df["Station"] == anchor_station].set_index("Quarter")
    features = ["pH_anchor", "Temperature_anchor", "TSS_anchor", "NH3_anchor", "DO_anchor", "Salinity_anchor"]
    targets = ["DO", "Salinity"]
    
    results = []
    
    for target_station in target_stations:
        df_target = df[df["Station"] == target_station].set_index("Quarter")
        merged = df_anchor.join(df_target, lsuffix="_anchor", rsuffix="_target", how="inner")
        
        merged = merged.dropna(subset=features + [f"{t}_target" for t in targets])
        if len(merged) < 5:
            continue
            
        X = merged[features].values
        kf = KFold(n_splits=3, shuffle=True, random_state=42)
        
        row_res = {"Target": target_station, "Samples": len(merged)}
        
        for t in targets:
            y = merged[f"{t}_target"].values
            preds, trues = [], []
            
            for tr, te in kf.split(X):
                if len(np.unique(y[tr])) < 2: continue
                m = XGBRegressor(n_estimators=50, max_depth=3, learning_rate=0.1, random_state=42, verbosity=0)
                m.fit(X[tr], y[tr])
                preds.extend(m.predict(X[te]))
                trues.extend(y[te])
                
            if len(trues) > 0:
                row_res[t] = r2_score(trues, preds)
            else:
                row_res[t] = np.nan
                
        results.append(row_res)
        
    # In báo cáo dạng bảng
    res_df = pd.DataFrame(results).round(4)
    print("\nBảng Đánh giá R² của Trạm Proxy NB1 dự đoán 13 trạm còn lại:")
    print(res_df.to_string(index=False))
    
    print("\nNhận xét: Các trạm có R²(Salinity) > 0.5 chứng tỏ có thể map Trạm Ảo rất tốt.")

if __name__ == "__main__":
    evaluate_all_stations()
