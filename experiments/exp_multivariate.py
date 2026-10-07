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

def run_experiment():
    df = load_data()
    train_window = 7 * 24
    horizon = 24
    step = 24
    
    results = []
    
    for target in ALL_PARAMS:
        print(f"\n--- Testing Multivariate vs Univariate for {target} ---")
        y_true_uni, preds_uni = [], []
        y_true_multi, preds_multi = [], []
        
        start_idx = train_window
        while start_idx + horizon <= len(df):
            train_df = df.iloc[start_idx - train_window : start_idx]
            test_df = df.iloc[start_idx : start_idx + horizon]
            
            # --- 1. Univariate Training ---
            X_uni, y_uni = [], []
            for j in range(24, len(train_df)):
                feats = [
                    train_df[target].iloc[j-1],
                    train_df[target].iloc[j-2],
                    train_df[target].iloc[j-24],
                    train_df.index[j].hour
                ]
                X_uni.append(feats)
                y_uni.append(train_df[target].iloc[j])
                
            model_uni = XGBRegressor(**XGB_PARAMS[target], random_state=42)
            model_uni.fit(X_uni, y_uni)
            
            # --- 2. Multivariate Training ---
            X_multi, y_multi = [], []
            other_params = [p for p in ALL_PARAMS if p != target]
            for j in range(24, len(train_df)):
                feats = [
                    train_df[target].iloc[j-1],
                    train_df[target].iloc[j-2],
                    train_df[target].iloc[j-24],
                    train_df.index[j].hour
                ]
                # Thêm biến ngoại lai và đạo hàm bậc 1
                for p in other_params:
                    feats.append(train_df[p].iloc[j-1]) # Giá trị tuyệt đối
                    feats.append(train_df[p].iloc[j-1] - train_df[p].iloc[j-2]) # Vận tốc biến thiên
                
                X_multi.append(feats)
                y_multi.append(train_df[target].iloc[j])
                
            model_multi = XGBRegressor(**XGB_PARAMS[target], random_state=42)
            model_multi.fit(X_multi, y_multi)
            
            # --- Inference (24h) ---
            # Trạng thái hiện tại
            last_1_uni = train_df[target].iloc[-1]
            last_2_uni = train_df[target].iloc[-2]
            last_24_arr_uni = train_df[target].iloc[-24:].values
            
            state_multi = {p: train_df[p].iloc[-1] for p in ALL_PARAMS}
            state_multi_prev = {p: train_df[p].iloc[-2] for p in ALL_PARAMS}
            last_24_arr_multi = train_df[target].iloc[-24:].values
            
            for i in range(horizon):
                t_time = test_df.index[i]
                
                # Predict Univariate
                feats_uni = np.array([[last_1_uni, last_2_uni, last_24_arr_uni[i], t_time.hour]])
                pred_uni = float(model_uni.predict(feats_uni)[0])
                preds_uni.append(pred_uni)
                y_true_uni.append(test_df[target].iloc[i])
                
                last_2_uni = last_1_uni
                last_1_uni = pred_uni
                
                # Predict Multivariate
                feats_multi = [
                    state_multi[target],
                    state_multi_prev[target],
                    last_24_arr_multi[i],
                    t_time.hour
                ]
                for p in other_params:
                    feats_multi.append(state_multi[p])
                    feats_multi.append(state_multi[p] - state_multi_prev[p])
                    
                pred_multi = float(model_multi.predict(np.array([feats_multi]))[0])
                preds_multi.append(pred_multi)
                y_true_multi.append(test_df[target].iloc[i])
                
                # Cập nhật state_multi cho bước tiếp theo
                for p in ALL_PARAMS:
                    state_multi_prev[p] = state_multi[p]
                    if p == target:
                        state_multi[p] = pred_multi
                    else:
                        # Trong thực tế lúc dự báo tương lai ta không biết các biến khác,
                        # nên phải lấy giá trị thực tế để so sánh công bằng hoặc giả định nó giữ nguyên/nội suy.
                        # Tuy nhiên trong Walk-Forward đánh giá, XGBoost thường dùng dự đoán đa biến chéo.
                        # Để tránh phức tạp hóa mô hình VAR, ta tạm sử dụng giá trị thực tế của biến ngoại lai 
                        # tại t-1 (Teacher Forcing) để xem NẾU ta biết biến ngoại lai thì nó có giúp gì không.
                        state_multi[p] = test_df[p].iloc[i] 

            start_idx += step
            
        rmse_uni = math.sqrt(mean_squared_error(y_true_uni, preds_uni))
        rmse_multi = math.sqrt(mean_squared_error(y_true_multi, preds_multi))
        
        results.append({
            "Parameter": target,
            "RMSE Đơn biến (Univariate)": round(rmse_uni, 3),
            "RMSE Đa biến (Multivariate)": round(rmse_multi, 3),
            "Improvement": f"{((rmse_uni - rmse_multi) / rmse_uni) * 100:.1f}%"
        })
        
    res_df = pd.DataFrame(results)
    
    with open("multivariate_results.md", "w", encoding="utf-8") as f:
        f.write("# Kết quả Thực nghiệm Đa biến\n\n")
        f.write(res_df.to_markdown(index=False))
        
    print("Results saved to multivariate_results.md")

if __name__ == "__main__":
    run_experiment()
