import os
import sys
import math
import numpy as np
import pandas as pd
from xgboost import XGBRegressor
from sklearn.metrics import mean_squared_error

# Add root to sys path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Tuned Hyperparameters from Optuna
XGB_PARAMS = {
    "Temperature": {'max_depth': 5, 'n_estimators': 21, 'learning_rate': 0.165},
    "pH": {'max_depth': 6, 'n_estimators': 14, 'learning_rate': 0.142},
    "NH4": {'max_depth': 3, 'n_estimators': 97, 'learning_rate': 0.022},
    "TSS": {'max_depth': 4, 'n_estimators': 64, 'learning_rate': 0.049}
}

ALL_PARAMS = ["Temperature", "pH", "NH4", "TSS"]

# Ma trận tương quan đã tính toán:
# Temperature: pH (0.72), NH4 (-0.47), TSS (-0.43)
# pH: Temp (0.72), NH4 (-0.38)
# NH4: Temp (-0.47), pH (-0.38)
# TSS: Temp (-0.43)
CORRELATED_FEATURES = {
    "Temperature": ["pH", "NH4", "TSS"],
    "pH": ["Temperature", "NH4"],
    "NH4": ["Temperature", "pH"],
    "TSS": ["Temperature"]
}

def load_data():
    csv_path = os.path.join(PROJECT_ROOT, "data", "greenlab", "greenlab_export.csv")
    df = pd.read_csv(csv_path)
    df['fetchedAt'] = pd.to_datetime(df['fetchedAt'])
    df = df.sort_values('fetchedAt')
    df = df[df['device'] == '06M26042804']
    df.set_index('fetchedAt', inplace=True)
    df_hourly = df[ALL_PARAMS].resample('1h').mean()
    df_hourly = df_hourly.interpolate(method='linear')
    df_hourly = df_hourly.dropna()
    return df_hourly

def run_selective_experiment():
    df = load_data()
    train_window = 7 * 24
    horizon = 24
    step = 24
    
    results = []
    
    for target in ALL_PARAMS:
        print(f"\n--- Testing Selective Multivariate for {target} ---")
        y_true, preds_sel = [], []
        
        start_idx = train_window
        while start_idx + horizon <= len(df):
            train_df = df.iloc[start_idx - train_window : start_idx]
            test_df = df.iloc[start_idx : start_idx + horizon]
            
            # --- Selective Multivariate Training ---
            X_sel, y_sel = [], []
            selected_exogenous = CORRELATED_FEATURES[target]
            
            for j in range(24, len(train_df)):
                feats = [
                    train_df[target].iloc[j-1],
                    train_df[target].iloc[j-2],
                    train_df[target].iloc[j-24],
                    train_df.index[j].hour
                ]
                # Chỉ thêm các biến có tương quan mạnh
                for p in selected_exogenous:
                    feats.append(train_df[p].iloc[j-1])
                
                X_sel.append(feats)
                y_sel.append(train_df[target].iloc[j])
                
            model_sel = XGBRegressor(**XGB_PARAMS[target], random_state=42)
            model_sel.fit(X_sel, y_sel)
            
            # --- Inference (24h) ---
            state_multi = {p: train_df[p].iloc[-1] for p in ALL_PARAMS}
            last_24_arr = train_df[target].iloc[-24:].values
            
            for i in range(horizon):
                t_time = test_df.index[i]
                
                feats_sel = [
                    state_multi[target],
                    train_df[target].iloc[-2] if i == 0 else preds_sel[-1] if len(preds_sel) > 0 else state_multi[target],
                    last_24_arr[i],
                    t_time.hour
                ]
                
                for p in selected_exogenous:
                    feats_sel.append(state_multi[p])
                    
                pred_sel = float(model_sel.predict(np.array([feats_sel]))[0])
                preds_sel.append(pred_sel)
                y_true.append(test_df[target].iloc[i])
                
                # Update states
                for p in ALL_PARAMS:
                    if p == target:
                        state_multi[p] = pred_sel
                    else:
                        state_multi[p] = test_df[p].iloc[i] 

            start_idx += step
            
        rmse_sel = math.sqrt(mean_squared_error(y_true, preds_sel))
        
        results.append({
            "Parameter": target,
            "RMSE Đa biến Chọn lọc": round(rmse_sel, 3)
        })
        
    res_df = pd.DataFrame(results)
    print("\n=== SELECTIVE MULTIVARIATE RESULTS ===")
    
    
    with open("selective_results.md", "w", encoding="utf-8") as f:
        f.write("# Kết quả Thực nghiệm Đa biến Chọn lọc\n\n")
        f.write(res_df.to_markdown(index=False))

if __name__ == "__main__":
    run_selective_experiment()
