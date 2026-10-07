import os
import sys
import pandas as pd
import numpy as np
import math
from xgboost import XGBRegressor
from sklearn.metrics import mean_squared_error, mean_absolute_error

# Add root to sys path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from hap_shared.sirl.arws import RHO_GRID

def _recency_weighted_mean(vals, rho):
    vals = np.asarray(vals, float)
    n = len(vals)
    if n == 0:
        return np.nan
    age = (n - 1) - np.arange(n)
    w = np.power(float(rho), age)
    return float(np.sum(w * vals) / np.sum(w))

def predict_rt_arws(history_values, history_times, target_time, phase_type="daily", rho=0.7):
    """
    RT-ARWS prediction.
    phase_type: 'daily' (0-23) or 'weekly' (0-167)
    """
    if len(history_values) == 0:
        return np.nan
        
    if phase_type == "daily":
        t_phase = target_time.hour
        h_phases = np.array([t.hour for t in history_times])
    else: # weekly
        t_phase = target_time.dayofweek * 24 + target_time.hour
        h_phases = np.array([t.dayofweek * 24 + t.hour for t in history_times])
        
    # Get all historical values that match the target phase
    mask = (h_phases == t_phase)
    same_phase_vals = np.array(history_values)[mask]
    
    if len(same_phase_vals) == 0:
        # Fallback to the latest value if no phase match
        return history_values[-1]
        
    return _recency_weighted_mean(same_phase_vals, rho)

def predict_physical_sine(latest_val, latest_time, target_time, param):
    """
    Physical Sine Model (Current Web App Baseline)
    """
    if pd.isna(latest_val): return np.nan
    
    h_current = latest_time.hour
    h_target = target_time.hour
    
    def get_sine(h):
        return math.sin((2 * math.pi / 24) * (h - 8))
        
    if param == "Temperature": AMP = 2.0
    elif param == "DO": AMP = 1.5
    elif param == "pH": AMP = 0.2
    else: AMP = 0.0 # Không có giả định chu kỳ vật lý rõ ràng cho NH4/TSS
    
    baseline = latest_val - (AMP * get_sine(h_current))
    f_val = baseline + (AMP * get_sine(h_target))
    
    if param == "pH":
        f_val = max(0.1, f_val)
    return f_val

def load_and_prep_data():
    csv_path = os.path.join(PROJECT_ROOT, "data", "greenlab", "greenlab_export.csv")
    df = pd.read_csv(csv_path)
    df['fetchedAt'] = pd.to_datetime(df['fetchedAt'])
    df = df.sort_values('fetchedAt')
    
    # Lấy trạm có data
    df = df[df['device'] == '06M26042804']
    
    # Đặt index để resample
    df.set_index('fetchedAt', inplace=True)
    
    # Resample 1 Hour
    df_hourly = df[['Temperature', 'pH', 'COD', 'NH4', 'TSS']].resample('1h').mean()
    
    # Nội suy tuyến tính những khoảng trống nhỏ
    df_hourly = df_hourly.interpolate(method='linear')
    df_hourly = df_hourly.dropna()
    return df_hourly

def run_experiment():
    print("Loading data...")
    df = load_and_prep_data()
    print(f"Data shape after resampling: {df.shape}")
    print(f"Time range: {df.index.min()} to {df.index.max()}")
    
    targets = ["Temperature", "pH", "NH4", "TSS"]
    results = []
    
    # Thông số Walk-forward
    train_window = 7 * 24 # 7 ngày lịch sử
    horizon = 24 # Dự báo 24 giờ
    step = 12 # Trượt mỗi 12 giờ
    
    for param in targets:
        print(f"\nEvaluating: {param}")
        
        y_true_all = []
        preds_snaive = []
        preds_sine = []
        preds_arws_d = []
        preds_arws_w = []
        
        # XGBoost preparation
        xgb_preds = []
        
        start_idx = train_window
        while start_idx + horizon <= len(df):
            # Train window
            train_df = df.iloc[start_idx - train_window : start_idx]
            # Test window (24h)
            test_df = df.iloc[start_idx : start_idx + horizon]
            
            history_vals = train_df[param].values
            history_times = train_df.index.tolist()
            
            latest_val = history_vals[-1]
            latest_time = history_times[-1]
            
            # Predict horizon
            for i in range(horizon):
                t_val = test_df[param].iloc[i]
                t_time = test_df.index[i]
                
                y_true_all.append(t_val)
                
                # SNaive: same hour yesterday (24h ago from target)
                snaive_val = train_df[param].iloc[-(24 - i)] if (24 - i) <= len(train_df) else latest_val
                preds_snaive.append(snaive_val)
                
                # Sine
                preds_sine.append(predict_physical_sine(latest_val, latest_time, t_time, param))
                
                # ARWS Daily
                preds_arws_d.append(predict_rt_arws(history_vals, history_times, t_time, "daily", rho=0.7))
                
                # ARWS Weekly
                preds_arws_w.append(predict_rt_arws(history_vals, history_times, t_time, "weekly", rho=0.7))
            
            # Prepare XGBoost features for this window
            # XGB is trained on the train_window
            X_train, y_train = [], []
            for j in range(24, len(train_df)):
                v1 = train_df[param].iloc[j-1]
                v2 = train_df[param].iloc[j-2]
                v3 = train_df[param].iloc[j-3]
                vel = v1 - v2
                acc = (v1 - v2) - (v2 - v3)
                
                # Lags: t-1, t-2, t-24, hour, vel, acc
                feats = [
                    v1, v2, train_df[param].iloc[j-24], train_df.index[j].hour, vel, acc
                ]
                X_train.append(feats)
                y_train.append(train_df[param].iloc[j])
                
            model = XGBRegressor(n_estimators=50, max_depth=3, random_state=42)
            model.fit(X_train, y_train)
            
            # Autoregressive prediction
            last_1 = train_df[param].iloc[-1]
            last_2 = train_df[param].iloc[-2]
            last_3 = train_df[param].iloc[-3]
            last_24_arr = train_df[param].iloc[-24:].values
            
            for i in range(horizon):
                last_24 = last_24_arr[i] # simplistic lag 24
                vel = last_1 - last_2
                acc = (last_1 - last_2) - (last_2 - last_3)
                
                feats = np.array([[last_1, last_2, last_24, test_df.index[i].hour, vel, acc]])
                pred = float(model.predict(feats)[0])
                xgb_preds.append(pred)
                
                # Update lags
                last_3 = last_2
                last_2 = last_1
                last_1 = pred
            
            start_idx += step
            
        # Tính toán Metrics
        def calc_metrics(trues, preds):
            trues, preds = np.array(trues), np.array(preds)
            mask = ~np.isnan(preds) & ~np.isnan(trues)
            if not mask.any(): return np.inf, np.inf
            mae = mean_absolute_error(trues[mask], preds[mask])
            rmse = math.sqrt(mean_squared_error(trues[mask], preds[mask]))
            return mae, rmse
            
        m_snaive = calc_metrics(y_true_all, preds_snaive)
        m_sine = calc_metrics(y_true_all, preds_sine)
        m_arws_d = calc_metrics(y_true_all, preds_arws_d)
        m_arws_w = calc_metrics(y_true_all, preds_arws_w)
        m_xgb = calc_metrics(y_true_all, xgb_preds)
        
        res = {
            "Parameter": param,
            "SNaive": m_snaive[1],
            "Sine": m_sine[1],
            "XGBoost": m_xgb[1],
            "RT-ARWS (Daily)": m_arws_d[1],
            "RT-ARWS (Weekly)": m_arws_w[1],
        }
        # Format 3 decimals
        for k, v in res.items():
            if isinstance(v, float):
                res[k] = round(v, 3)
                
        results.append(res)
        
    print("\n=== FINAL RESULTS (RMSE) ===")
    res_df = pd.DataFrame(results)
    print(res_df.to_markdown(index=False))
    
    # Save to file
    out_path = os.path.join(BASE_DIR, "rt_arws_results.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Kết quả Thực nghiệm Realtime ARWS\n\n")
        f.write(res_df.to_markdown(index=False))
        
if __name__ == "__main__":
    run_experiment()
