import os
import sys
import pandas as pd
import numpy as np
import math
import optuna
from xgboost import XGBRegressor
from sklearn.metrics import mean_squared_error
from sklearn.preprocessing import StandardScaler
import torch
import torch.nn as nn
import torch.optim as optim

# Add root to sys path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))
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
    t_phase = target_time.hour
    h_phases = np.array([t.hour for t in history_times])
    mask = (h_phases == t_phase)
    same_phase_vals = np.array(history_values)[mask]
    if len(same_phase_vals) == 0:
        return history_values[-1]
    return _recency_weighted_mean(same_phase_vals, rho)

def predict_physical_sine(latest_val, latest_time, target_time, amp, phase_shift):
    if pd.isna(latest_val): return np.nan
    h_current = latest_time.hour
    h_target = target_time.hour
    def get_sine(h):
        return math.sin((2 * math.pi / 24) * (h - phase_shift))
    baseline = latest_val - (amp * get_sine(h_current))
    f_val = baseline + (amp * get_sine(h_target))
    return f_val

def load_data():
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

# To speed up tuning, we use a step of 48h (2 days) for walk-forward CV
TRAIN_WINDOW = 7 * 24
HORIZON = 24
STEP = 48

def eval_snaive(df, param):
    y_true_all = []
    preds = []
    start_idx = TRAIN_WINDOW
    while start_idx + HORIZON <= len(df):
        train_df = df.iloc[start_idx - TRAIN_WINDOW : start_idx]
        test_df = df.iloc[start_idx : start_idx + HORIZON]
        latest_val = train_df[param].iloc[-1]
        for i in range(HORIZON):
            t_val = test_df[param].iloc[i]
            y_true_all.append(t_val)
            p = train_df[param].iloc[-(24 - i)] if (24 - i) <= len(train_df) else latest_val
            preds.append(p)
        start_idx += STEP
    trues, preds = np.array(y_true_all), np.array(preds)
    mask = ~np.isnan(preds)
    return math.sqrt(mean_squared_error(trues[mask], preds[mask]))

def create_objective_arws(df, param):
    def objective(trial):
        rho = trial.suggest_float("rho", 0.05, 0.99)
        y_true_all, preds = [], []
        start_idx = TRAIN_WINDOW
        while start_idx + HORIZON <= len(df):
            train_df = df.iloc[start_idx - TRAIN_WINDOW : start_idx]
            test_df = df.iloc[start_idx : start_idx + HORIZON]
            history_vals = train_df[param].values
            history_times = train_df.index.tolist()
            for i in range(HORIZON):
                t_val = test_df[param].iloc[i]
                t_time = test_df.index[i]
                y_true_all.append(t_val)
                preds.append(predict_rt_arws(history_vals, history_times, t_time, "daily", rho=rho))
            start_idx += STEP
        trues, preds = np.array(y_true_all), np.array(preds)
        mask = ~np.isnan(preds)
        return math.sqrt(mean_squared_error(trues[mask], preds[mask]))
    return objective

def create_objective_sine(df, param):
    def objective(trial):
        amp = trial.suggest_float("amp", 0.0, 5.0)
        phase_shift = trial.suggest_float("phase_shift", 0.0, 24.0)
        y_true_all, preds = [], []
        start_idx = TRAIN_WINDOW
        while start_idx + HORIZON <= len(df):
            train_df = df.iloc[start_idx - TRAIN_WINDOW : start_idx]
            test_df = df.iloc[start_idx : start_idx + HORIZON]
            history_vals = train_df[param].values
            history_times = train_df.index.tolist()
            latest_val = history_vals[-1]
            latest_time = history_times[-1]
            for i in range(HORIZON):
                t_val = test_df[param].iloc[i]
                t_time = test_df.index[i]
                y_true_all.append(t_val)
                preds.append(predict_physical_sine(latest_val, latest_time, t_time, amp, phase_shift))
            start_idx += STEP
        trues, preds = np.array(y_true_all), np.array(preds)
        mask = ~np.isnan(preds)
        return math.sqrt(mean_squared_error(trues[mask], preds[mask]))
    return objective

def create_objective_xgb(df, param):
    def objective(trial):
        max_depth = trial.suggest_int("max_depth", 2, 8)
        n_estimators = trial.suggest_int("n_estimators", 10, 100)
        learning_rate = trial.suggest_float("learning_rate", 0.01, 0.2)
        y_true_all, preds = [], []
        start_idx = TRAIN_WINDOW
        while start_idx + HORIZON <= len(df):
            train_df = df.iloc[start_idx - TRAIN_WINDOW : start_idx]
            test_df = df.iloc[start_idx : start_idx + HORIZON]
            X_train, y_train = [], []
            for j in range(24, len(train_df)):
                feats = [
                    train_df[param].iloc[j-1], train_df[param].iloc[j-2],
                    train_df[param].iloc[j-24], train_df.index[j].hour
                ]
                X_train.append(feats)
                y_train.append(train_df[param].iloc[j])
            model = XGBRegressor(n_estimators=n_estimators, max_depth=max_depth, learning_rate=learning_rate, random_state=42)
            model.fit(X_train, y_train)
            last_1 = train_df[param].iloc[-1]
            last_2 = train_df[param].iloc[-2]
            last_24_arr = train_df[param].iloc[-24:].values
            for i in range(HORIZON):
                feats = np.array([[last_1, last_2, last_24_arr[i], test_df.index[i].hour]])
                pred = float(model.predict(feats)[0])
                preds.append(pred)
                y_true_all.append(test_df[param].iloc[i])
                last_2 = last_1
                last_1 = pred
            start_idx += STEP
        return math.sqrt(mean_squared_error(y_true_all, preds))
    return objective

def create_objective_lstm(df, param):
    def objective(trial):
        hidden_size = trial.suggest_categorical("hidden_size", [8, 16, 32])
        lr = trial.suggest_float("lr", 0.005, 0.05)
        epochs = 15 # Keep small for speed
        
        y_true_all, preds = [], []
        start_idx = TRAIN_WINDOW
        while start_idx + HORIZON <= len(df):
            train_df = df.iloc[start_idx - TRAIN_WINDOW : start_idx]
            test_df = df.iloc[start_idx : start_idx + HORIZON]
            
            history_vals = train_df[param].values
            scaler = StandardScaler()
            train_vals_scaled = scaler.fit_transform(history_vals.reshape(-1, 1))
            
            X_lstm, y_lstm = [], []
            seq_len = 24
            for j in range(len(train_vals_scaled) - seq_len):
                X_lstm.append(train_vals_scaled[j : j + seq_len])
                y_lstm.append(train_vals_scaled[j + seq_len])
                
            X_lstm = torch.tensor(np.array(X_lstm), dtype=torch.float32)
            y_lstm = torch.tensor(np.array(y_lstm), dtype=torch.float32)
            
            model = SimpleLSTM(input_size=1, hidden_size=hidden_size, num_layers=1)
            optimizer = optim.Adam(model.parameters(), lr=lr)
            criterion = nn.MSELoss()
            
            model.train()
            for epoch in range(epochs):
                optimizer.zero_grad()
                out = model(X_lstm)
                loss = criterion(out, y_lstm)
                loss.backward()
                optimizer.step()
                
            model.eval()
            curr_seq = train_vals_scaled[-seq_len:].tolist()
            with torch.no_grad():
                for i in range(HORIZON):
                    x_tensor = torch.tensor([curr_seq[-seq_len:]], dtype=torch.float32)
                    pred_scaled = model(x_tensor).item()
                    curr_seq.append([pred_scaled])
                    pred = scaler.inverse_transform([[pred_scaled]])[0][0]
                    preds.append(pred)
                    y_true_all.append(test_df[param].iloc[i])
                    
            start_idx += STEP
        return math.sqrt(mean_squared_error(y_true_all, preds))
    return objective

if __name__ == "__main__":
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    df = load_data()
    params = ["Temperature", "pH", "NH4", "TSS"]
    
    results = []
    
    for param in params:
        print(f"\n--- Global Tuning for {param} ---")
        
        # 1. SNaive (No tuning)
        rmse_snaive = eval_snaive(df, param)
        print(f"SNaive RMSE: {rmse_snaive:.3f}")
        
        # 2. Sine
        study_sine = optuna.create_study(direction="minimize")
        study_sine.optimize(create_objective_sine(df, param), n_trials=15)
        print(f"Sine Tuned RMSE: {study_sine.best_value:.3f}")
        
        # 3. XGBoost
        study_xgb = optuna.create_study(direction="minimize")
        study_xgb.optimize(create_objective_xgb(df, param), n_trials=15)
        print(f"XGBoost Tuned RMSE: {study_xgb.best_value:.3f}")
        
        # 4. RT-ARWS
        study_arws = optuna.create_study(direction="minimize")
        study_arws.optimize(create_objective_arws(df, param), n_trials=15)
        print(f"RT-ARWS Tuned RMSE: {study_arws.best_value:.3f}")
        
        # 5. LSTM
        study_lstm = optuna.create_study(direction="minimize")
        study_lstm.optimize(create_objective_lstm(df, param), n_trials=10) # 10 trials for LSTM due to time
        print(f"LSTM Tuned RMSE: {study_lstm.best_value:.3f}")
        
        results.append({
            "Parameter": param,
            "SNaive": round(rmse_snaive, 3),
            "Tuned Sine": round(study_sine.best_value, 3),
            "Tuned XGBoost": round(study_xgb.best_value, 3),
            "Tuned LSTM": round(study_lstm.best_value, 3),
            "Tuned RT-ARWS": round(study_arws.best_value, 3),
        })
        
    res_df = pd.DataFrame(results)
    print("\n=== FINAL ALL-MODELS TUNED RESULTS ===")
    print(res_df.to_markdown(index=False))
