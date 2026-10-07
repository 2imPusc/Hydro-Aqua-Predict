import os
import sys
import pandas as pd
import numpy as np
import math
from xgboost import XGBRegressor
from sklearn.metrics import mean_squared_error, mean_absolute_error
from sklearn.preprocessing import StandardScaler
import torch
import torch.nn as nn
import torch.optim as optim

# Add root to sys path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

class SimpleLSTM(nn.Module):
    def __init__(self, input_size=1, hidden_size=16, num_layers=1):
        super(SimpleLSTM, self).__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True)
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x):
        out, _ = self.lstm(x)
        out = self.fc(out[:, -1, :])
        return out

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

def predict_physical_sine(latest_val, latest_time, target_time, param):
    if pd.isna(latest_val): return np.nan
    h_current = latest_time.hour
    h_target = target_time.hour
    def get_sine(h):
        return math.sin((2 * math.pi / 24) * (h - 8))
        
    if param == "Temperature": AMP = 2.0
    elif param == "DO": AMP = 1.5
    elif param == "pH": AMP = 0.2
    else: AMP = 0.0
    
    baseline = latest_val - (AMP * get_sine(h_current))
    f_val = baseline + (AMP * get_sine(h_target))
    return f_val

def load_all_stations():
    data_dir = os.path.join(PROJECT_ROOT, "data", "greenlab", "exports", "all_data")
    if not os.path.exists(data_dir):
        print(f"Directory not found: {data_dir}")
        return []
        
    files = [f for f in os.listdir(data_dir) if f.endswith(".csv")]
    dfs = []
    print(f"Found {len(files)} CSV files in {data_dir}")
    
    for f in files:
        csv_path = os.path.join(data_dir, f)
        df = pd.read_csv(csv_path)
        if "Temp" in df.columns:
            df.rename(columns={"Temp": "Temperature"}, inplace=True)
            
        df['fetchedAt'] = pd.to_datetime(df['fetchedAt'])
        df = df.sort_values('fetchedAt')
        df.set_index('fetchedAt', inplace=True)
        
        # We need these 4 columns
        cols = ['Temperature', 'pH', 'NH4', 'TSS']
        missing_cols = [c for c in cols if c not in df.columns]
        if missing_cols:
            print(f"Skipping {f} because it misses columns: {missing_cols}")
            continue
            
        df_hourly = df[cols].resample('1h').mean()
        df_hourly = df_hourly.interpolate(method='linear')
        df_hourly = df_hourly.dropna()
        
        if len(df_hourly) > 7 * 24: # Must have at least 1 week
            dfs.append(df_hourly)
            print(f"Loaded {f} - shape: {df_hourly.shape}")
        else:
            print(f"Skipping {f} due to insufficient data length ({len(df_hourly)} hours).")
            
    return dfs

def run_experiment():
    dfs = load_all_stations()
    if not dfs:
        print("No valid data found.")
        return
        
    targets = ["Temperature", "pH", "NH4", "TSS"]
    results = []
    
    train_window = 7 * 24
    horizon = 24
    step = 12
    
    for param in targets:
        print(f"\nEvaluating: {param}")
        
        y_true_all = []
        preds_snaive = []
        preds_sine = []
        preds_arws_d = []
        preds_ms_arws = []
        xgb_preds = []
        lstm_preds = []
        
        for df in dfs:
            start_idx = train_window
            while start_idx + horizon <= len(df):
                train_df = df.iloc[start_idx - train_window : start_idx]
                test_df = df.iloc[start_idx : start_idx + horizon]
                
                history_vals = train_df[param].values
                history_times = train_df.index.tolist()
                
                latest_val = history_vals[-1]
                latest_time = history_times[-1]
                
                # --- Dynamic Weights for MS-ARWS ---
                val_df = train_df.iloc[-24:]
                hist_for_val = train_df.iloc[:-24]
                h_vals_val = hist_for_val[param].values
                h_times_val = hist_for_val.index.tolist()
                
                err_d, err_w = 0.0, 0.0
                count = 0
                for i in range(24):
                    v_true = val_df[param].iloc[i]
                    v_time = val_df.index[i]
                    p_d = predict_rt_arws(h_vals_val, h_times_val, v_time, "daily", rho=0.7)
                    p_w = predict_rt_arws(h_vals_val, h_times_val, v_time, "weekly", rho=0.8)
                    
                    if not pd.isna(p_d) and not pd.isna(p_w):
                        err_d += abs(v_true - p_d)
                        err_w += abs(v_true - p_w)
                        count += 1
                
                if count > 0:
                    mae_d = err_d / count
                    mae_w = err_w / count
                    eps = 1e-6
                    w_d = (1.0 / (mae_d + eps)) / ((1.0 / (mae_d + eps)) + (1.0 / (mae_w + eps)))
                    w_w = 1.0 - w_d
                else:
                    w_d, w_w = 0.8, 0.2
                
                # --- Predict Non-ML methods ---
                for i in range(horizon):
                    t_val = test_df[param].iloc[i]
                    t_time = test_df.index[i]
                    y_true_all.append(t_val)
                    
                    snaive_val = train_df[param].iloc[-(24 - i)] if (24 - i) <= len(train_df) else latest_val
                    preds_snaive.append(snaive_val)
                    
                    preds_sine.append(predict_physical_sine(latest_val, latest_time, t_time, param))
                    
                    p_d = predict_rt_arws(history_vals, history_times, t_time, "daily", rho=0.7)
                    p_w = predict_rt_arws(history_vals, history_times, t_time, "weekly", rho=0.8)
                    
                    preds_arws_d.append(p_d)
                    
                    p_ms = (w_d * p_d) + (w_w * p_w)
                    preds_ms_arws.append(p_ms)
                    
                # --- XGBoost ---
                X_train_xgb, y_train_xgb = [], []
                for j in range(24, len(train_df)):
                    v1 = train_df[param].iloc[j-1]
                    v2 = train_df[param].iloc[j-2]
                    v3 = train_df[param].iloc[j-3]
                    vel = v1 - v2
                    acc = (v1 - v2) - (v2 - v3)
                    
                    feats = [
                        v1, v2, train_df[param].iloc[j-24], train_df.index[j].hour, vel, acc
                    ]
                    X_train_xgb.append(feats)
                    y_train_xgb.append(train_df[param].iloc[j])
                    
                xgb_model = XGBRegressor(n_estimators=50, max_depth=3, random_state=42)
                xgb_model.fit(X_train_xgb, y_train_xgb)
                
                last_1 = train_df[param].iloc[-1]
                last_2 = train_df[param].iloc[-2]
                last_3 = train_df[param].iloc[-3]
                last_24_arr = train_df[param].iloc[-24:].values
                
                for i in range(horizon):
                    last_24 = last_24_arr[i]
                    vel = last_1 - last_2
                    acc = (last_1 - last_2) - (last_2 - last_3)
                    
                    feats = np.array([[last_1, last_2, last_24, test_df.index[i].hour, vel, acc]])
                    pred = float(xgb_model.predict(feats)[0])
                    xgb_preds.append(pred)
                    
                    last_3 = last_2
                    last_2 = last_1
                    last_1 = pred
                    
                # --- LSTM ---
                scaler = StandardScaler()
                train_vals_scaled = scaler.fit_transform(history_vals.reshape(-1, 1))
                
                X_lstm, y_lstm = [], []
                seq_len = 24
                for j in range(len(train_vals_scaled) - seq_len):
                    X_lstm.append(train_vals_scaled[j : j + seq_len])
                    y_lstm.append(train_vals_scaled[j + seq_len])
                    
                X_lstm = torch.tensor(np.array(X_lstm), dtype=torch.float32)
                y_lstm = torch.tensor(np.array(y_lstm), dtype=torch.float32)
                
                lstm_model = SimpleLSTM(input_size=1, hidden_size=16, num_layers=1)
                optimizer = optim.Adam(lstm_model.parameters(), lr=0.01)
                criterion = nn.MSELoss()
                
                # Train
                lstm_model.train()
                for epoch in range(25):
                    optimizer.zero_grad()
                    out = lstm_model(X_lstm)
                    loss = criterion(out, y_lstm)
                    loss.backward()
                    optimizer.step()
                    
                # Inference
                lstm_model.eval()
                curr_seq = train_vals_scaled[-seq_len:].tolist()
                
                with torch.no_grad():
                    for i in range(horizon):
                        x_tensor = torch.tensor([curr_seq[-seq_len:]], dtype=torch.float32)
                        pred_scaled = lstm_model(x_tensor).item()
                        curr_seq.append([pred_scaled])
                        
                        pred = scaler.inverse_transform([[pred_scaled]])[0][0]
                        lstm_preds.append(pred)
                
                start_idx += step
            
        def calc_metrics(trues, preds):
            trues, preds = np.array(trues), np.array(preds)
            mask = ~np.isnan(preds) & ~np.isnan(trues)
            if not mask.any(): return np.inf
            rmse = math.sqrt(mean_squared_error(trues[mask], preds[mask]))
            return rmse
            
        m_snaive = calc_metrics(y_true_all, preds_snaive)
        m_sine = calc_metrics(y_true_all, preds_sine)
        m_d = calc_metrics(y_true_all, preds_arws_d)
        m_ms = calc_metrics(y_true_all, preds_ms_arws)
        m_xgb = calc_metrics(y_true_all, xgb_preds)
        m_lstm = calc_metrics(y_true_all, lstm_preds)
        
        res = {
            "Parameter": param,
            "SNaive": round(m_snaive, 3),
            "Physical Sine": round(m_sine, 3),
            "XGBoost": round(m_xgb, 3),
            "LSTM (Deep Learning)": round(m_lstm, 3),
            "RT-ARWS (Daily)": round(m_d, 3),
            "MS-ARWS (Lai ghép)": round(m_ms, 3)
        }
        results.append(res)
        
    print("\n=== FINAL RESULTS (RMSE) ACROSS 4 STATIONS ===")
    res_df = pd.DataFrame(results)
    print(res_df.to_markdown(index=False))
    
    out_path = os.path.join(BASE_DIR, "all_stations_lstm_results.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Kết quả Thực nghiệm Toàn diện trên 4 Trạm (Cát Bà, Quảng Ninh, Thái Bình)\n\n")
        f.write(res_df.to_markdown(index=False))
        
if __name__ == "__main__":
    run_experiment()
