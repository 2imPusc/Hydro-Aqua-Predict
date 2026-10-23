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

def _recency_weighted_mean(vals, rho):
    vals = np.asarray(vals, float)
    n = len(vals)
    if n == 0:
        return np.nan
    age = (n - 1) - np.arange(n)
    w = np.power(float(rho), age)
    return float(np.sum(w * vals) / np.sum(w))

def predict_rt_arws(history_values, history_times, target_time, phase_type="daily", rho=0.7):
    if len(history_values) == 0:
        return np.nan
        
    if phase_type == "daily":
        t_phase = target_time.hour
        h_phases = np.array([t.hour for t in history_times])
    else: # weekly
        t_phase = target_time.dayofweek * 24 + target_time.hour
        h_phases = np.array([t.dayofweek * 24 + t.hour for t in history_times])
        
    mask = (h_phases == t_phase)
    same_phase_vals = np.array(history_values)[mask]
    
    if len(same_phase_vals) == 0:
        return history_values[-1]
        
    return _recency_weighted_mean(same_phase_vals, rho)

def load_and_prep_data():
    csv_path = os.path.join(PROJECT_ROOT, "data", "greenlab", "greenlab_export.csv")
    df = pd.read_csv(csv_path)
    df['fetchedAt'] = pd.to_datetime(df['fetchedAt'])
    df = df.sort_values('fetchedAt')
    df = df[df['device'] == '06M26042804']
    df.set_index('fetchedAt', inplace=True)
    df_hourly = df[['Temperature', 'pH', 'NH4', 'TSS']].resample('1h').mean()
    df_hourly = df_hourly.interpolate(method='linear')
    df_hourly = df_hourly.dropna()
    return df_hourly

def run_experiment():
    print("Loading data...")
    df = load_and_prep_data()
    print(f"Data shape after resampling: {df.shape}")
    
    targets = ["Temperature", "pH", "NH4", "TSS"]
    results = []
    
    train_window = 7 * 24
    horizon = 24
    step = 12
    
    for param in targets:
        print(f"\nEvaluating: {param}")
        
        y_true_all = []
        preds_arws_d = []
        preds_arws_w = []
        preds_ms_arws = []
        xgb_preds = []
        
        start_idx = train_window
        while start_idx + horizon <= len(df):
            train_df = df.iloc[start_idx - train_window : start_idx]
            test_df = df.iloc[start_idx : start_idx + horizon]
            
            # --- Dynamic Weight Calculation (Validation on last 24h of train_df) ---
            val_df = train_df.iloc[-24:]
            hist_for_val = train_df.iloc[:-24]
            h_vals = hist_for_val[param].values
            h_times = hist_for_val.index.tolist()
            
            err_d, err_w = 0.0, 0.0
            count = 0
            for i in range(24):
                v_true = val_df[param].iloc[i]
                v_time = val_df.index[i]
                p_d = predict_rt_arws(h_vals, h_times, v_time, "daily", rho=0.7)
                p_w = predict_rt_arws(h_vals, h_times, v_time, "weekly", rho=0.8)
                
                if not pd.isna(p_d) and not pd.isna(p_w):
                    err_d += abs(v_true - p_d)
                    err_w += abs(v_true - p_w)
                    count += 1
            
            if count > 0:
                mae_d = err_d / count
                mae_w = err_w / count
                # Inverse proportional weighting
                # Add small epsilon to prevent div by zero
                eps = 1e-6
                w_d = (1.0 / (mae_d + eps)) / ((1.0 / (mae_d + eps)) + (1.0 / (mae_w + eps)))
                w_w = 1.0 - w_d
            else:
                w_d, w_w = 0.8, 0.2 # default fallback
                
            # --- Test Window Prediction ---
            history_vals = train_df[param].values
            history_times = train_df.index.tolist()
            
            for i in range(horizon):
                t_val = test_df[param].iloc[i]
                t_time = test_df.index[i]
                y_true_all.append(t_val)
                
                p_d = predict_rt_arws(history_vals, history_times, t_time, "daily", rho=0.7)
                p_w = predict_rt_arws(history_vals, history_times, t_time, "weekly", rho=0.8)
                
                preds_arws_d.append(p_d)
                preds_arws_w.append(p_w)
                
                p_ms = (w_d * p_d) + (w_w * p_w)
                preds_ms_arws.append(p_ms)
                
            # --- XGBoost ---
            X_train, y_train = [], []
            for j in range(24, len(train_df)):
                feats = [
                    train_df[param].iloc[j-1],
                    train_df[param].iloc[j-2],
                    train_df[param].iloc[j-24],
                    train_df.index[j].hour
                ]
                X_train.append(feats)
                y_train.append(train_df[param].iloc[j])
                
            model = XGBRegressor(n_estimators=50, max_depth=3, random_state=42)
            model.fit(X_train, y_train)
            
            last_1 = train_df[param].iloc[-1]
            last_2 = train_df[param].iloc[-2]
            last_24_arr = train_df[param].iloc[-24:].values
            
            for i in range(horizon):
                last_24 = last_24_arr[i]
                feats = np.array([[last_1, last_2, last_24, test_df.index[i].hour]])
                pred = float(model.predict(feats)[0])
                xgb_preds.append(pred)
                last_2 = last_1
                last_1 = pred
            
            start_idx += step
            
        def calc_metrics(trues, preds):
            trues, preds = np.array(trues), np.array(preds)
            mask = ~np.isnan(preds) & ~np.isnan(trues)
            if not mask.any(): return np.inf, np.inf
            rmse = math.sqrt(mean_squared_error(trues[mask], preds[mask]))
            return rmse
            
        m_d = calc_metrics(y_true_all, preds_arws_d)
        m_w = calc_metrics(y_true_all, preds_arws_w)
        m_ms = calc_metrics(y_true_all, preds_ms_arws)
        m_xgb = calc_metrics(y_true_all, xgb_preds)
        
        res = {
            "Parameter": param,
            "XGBoost": round(m_xgb, 3),
            "RT-ARWS (Daily)": round(m_d, 3),
            "RT-ARWS (Weekly)": round(m_w, 3),
            "MS-ARWS (Lai ghép)": round(m_ms, 3)
        }
        results.append(res)
        
    print("\n=== FINAL RESULTS (RMSE) ===")
    res_df = pd.DataFrame(results)
    print(res_df.to_markdown(index=False))
    
    out_path = os.path.join(BASE_DIR, "ms_arws_results.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Kết quả Thực nghiệm MS-ARWS (Multi-Scale)\n\n")
        f.write(res_df.to_markdown(index=False))
        
if __name__ == "__main__":
    run_experiment()
