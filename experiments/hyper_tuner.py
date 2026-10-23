import os
import sys
import pandas as pd
import numpy as np
import math
import optuna
from xgboost import XGBRegressor
from sklearn.metrics import mean_squared_error

# Add root to sys path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))
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
        
    t_phase = target_time.hour
    h_phases = np.array([t.hour for t in history_times])
    mask = (h_phases == t_phase)
    same_phase_vals = np.array(history_values)[mask]
    
    if len(same_phase_vals) == 0:
        return history_values[-1]
        
    return _recency_weighted_mean(same_phase_vals, rho)

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

def create_objective_arws(df, param):
    def objective(trial):
        rho = trial.suggest_float("rho", 0.05, 0.99)
        train_window = 7 * 24
        horizon = 24
        step = 24
        
        y_true_all = []
        preds = []
        start_idx = train_window
        while start_idx + horizon <= len(df):
            train_df = df.iloc[start_idx - train_window : start_idx]
            test_df = df.iloc[start_idx : start_idx + horizon]
            
            history_vals = train_df[param].values
            history_times = train_df.index.tolist()
            
            for i in range(horizon):
                t_val = test_df[param].iloc[i]
                t_time = test_df.index[i]
                y_true_all.append(t_val)
                preds.append(predict_rt_arws(history_vals, history_times, t_time, "daily", rho=rho))
            start_idx += step
            
        trues, preds = np.array(y_true_all), np.array(preds)
        mask = ~np.isnan(preds)
        return math.sqrt(mean_squared_error(trues[mask], preds[mask]))
    return objective

def create_objective_xgb(df, param):
    def objective(trial):
        max_depth = trial.suggest_int("max_depth", 2, 8)
        n_estimators = trial.suggest_int("n_estimators", 10, 100)
        learning_rate = trial.suggest_float("learning_rate", 0.01, 0.2)
        
        train_window = 7 * 24
        horizon = 24
        step = 24
        
        y_true_all = []
        preds = []
        start_idx = train_window
        while start_idx + horizon <= len(df):
            train_df = df.iloc[start_idx - train_window : start_idx]
            test_df = df.iloc[start_idx : start_idx + horizon]
            
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
                
            model = XGBRegressor(n_estimators=n_estimators, max_depth=max_depth, learning_rate=learning_rate, random_state=42)
            model.fit(X_train, y_train)
            
            last_1 = train_df[param].iloc[-1]
            last_2 = train_df[param].iloc[-2]
            last_24_arr = train_df[param].iloc[-24:].values
            
            for i in range(horizon):
                last_24 = last_24_arr[i]
                feats = np.array([[last_1, last_2, last_24, test_df.index[i].hour]])
                pred = float(model.predict(feats)[0])
                preds.append(pred)
                y_true_all.append(test_df[param].iloc[i])
                last_2 = last_1
                last_1 = pred
                
            start_idx += step
        return math.sqrt(mean_squared_error(y_true_all, preds))
    return objective

if __name__ == "__main__":
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    df = load_data()
    params = ["Temperature", "pH", "NH4", "TSS"]
    
    results = []
    
    for param in params:
        print(f"\n--- Tuning for {param} ---")
        
        study_arws = optuna.create_study(direction="minimize")
        study_arws.optimize(create_objective_arws(df, param), n_trials=20)
        
        study_xgb = optuna.create_study(direction="minimize")
        study_xgb.optimize(create_objective_xgb(df, param), n_trials=20)
        
        results.append({
            "Parameter": param,
            "Tuned XGBoost (RMSE)": round(study_xgb.best_value, 3),
            "XGBoost Params": str(study_xgb.best_params),
            "Tuned RT-ARWS (RMSE)": round(study_arws.best_value, 3),
            "RT-ARWS Params": str(study_arws.best_params)
        })
        
    res_df = pd.DataFrame(results)
    print("\n=== FINAL TUNED RESULTS ===")
    print(res_df.to_markdown(index=False))
