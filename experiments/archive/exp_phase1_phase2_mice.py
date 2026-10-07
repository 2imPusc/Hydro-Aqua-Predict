import pandas as pd
import numpy as np
from sklearn.model_selection import KFold
from sklearn.linear_model import BayesianRidge
from sklearn.metrics import r2_score
from sklearn.experimental import enable_iterative_imputer
from sklearn.impute import IterativeImputer
import xgboost as xgb
import warnings
warnings.filterwarnings('ignore')

def compute_metrics(y_true, y_pred):
    if len(y_true) < 2:
        return np.nan
    return r2_score(y_true, y_pred)

def run_experiment():
    df = pd.read_csv("haiphong_exogenous.csv")
    
    # Parse month and cyclical encoding
    dt = pd.to_datetime(df['Quarter'], format='mixed')
    df['Month'] = dt.dt.month
    df['Month_sin'] = np.sin(2 * np.pi * df['Month'] / 12)
    df['Month_cos'] = np.cos(2 * np.pi * df['Month'] / 12)
    
    # Fill missing exogenous features with median
    for col in ['Rain_median', 'Wind_median', 'Wave_median']:
        df[col] = df[col].fillna(df[col].median())
        
    targets = ["DO", "Salinity", "PO4", "Coliform", "As", "Cd", "Pb", "Cu", "Zn", "Total_Cr"]
    df = df.dropna(subset=['pH', 'Temperature', 'TSS', 'NH3'] + targets).reset_index(drop=True)
    
    features_base = ["pH", "Temperature", "TSS", "NH3", "Month_sin", "Month_cos"]
    features_weather = features_base + ["Rain_median", "Wind_median", "Wave_median"]
    
    print("=== THỰC NGHIỆM TÍCH HỢP SO SÁNH 2 PHASE (TẤT CẢ CHỈ SỐ) ===")
    
    # ==========================================
    # PHASE 1: LOCAL IMPUTATION (Global on 216 samples)
    # ==========================================
    print("\n--- PHASE 1: LOCAL IMPUTATION (GLOBAL MODEL TRÊN TOÀN BỘ TRẠM HẢI PHÒNG) ---")
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    
    phase1_results = {}
    for feat_name, feat_cols in [("Base", features_base), ("Base + Thời tiết", features_weather)]:
        res = {f'XGB {t}': [] for t in targets}
        res.update({f'MICE {t}': [] for t in targets})
        
        for train_idx, test_idx in kf.split(df):
            X_train, X_test = df.loc[train_idx, feat_cols], df.loc[test_idx, feat_cols]
            
            for target in targets:
                y_train, y_test = df.loc[train_idx, target], df.loc[test_idx, target]
                
                # XGBoost
                xgb_model = xgb.XGBRegressor(random_state=42, objective='reg:squarederror')
                xgb_model.fit(X_train, y_train)
                res[f'XGB {target}'].append(compute_metrics(y_test, xgb_model.predict(X_test)))
                
                # MICE (BayesianRidge)
                br = BayesianRidge()
                br.fit(X_train, y_train)
                res[f'MICE {target}'].append(compute_metrics(y_test, br.predict(X_test)))
                
        phase1_results[feat_name] = {k: np.mean(v) for k, v in res.items()}
        
    # Print Phase 1
    header = f"{'Cấu hình':<20}" + "".join([f" | XGB {t[:4]:<4} | MICE {t[:4]:<4}" for t in targets])
    print(header)
    for k, v in phase1_results.items():
        row = f"{k:<20}"
        for t in targets:
            row += f" | {v[f'XGB {t}']:<8.4f} | {v[f'MICE {t}']:<9.4f}"
        print(row)

    # ==========================================
    # PHASE 2: SPATIAL EXTRAPOLATION (NB1 -> NB15, NB4, NB16, NB3)
    # ==========================================
    print("\n--- PHASE 2: SPATIAL EXTRAPOLATION (ANCHOR NB1 -> TARGETS: NB15, NB4, NB16, NB3) ---")
    df_anchor = df[df['Station'] == 'NB1']
    target_stations = ['NB15', 'NB4', 'NB16', 'NB3']
    df_targets = df[df['Station'].isin(target_stations)]
    
    phase2_results = {}
    for feat_name, feat_cols in [("Base", features_base), ("Base + Thời tiết", features_weather)]:
        res = {f'XGB {t}': [] for t in targets}
        res.update({f'MICE {t}': [] for t in targets})
        
        # Train on Anchor
        X_train = df_anchor[feat_cols]
        models_xgb = {}
        models_mice = {}
        for target in targets:
            y_train = df_anchor[target]
            
            xgb_model = xgb.XGBRegressor(random_state=42, objective='reg:squarederror')
            xgb_model.fit(X_train, y_train)
            models_xgb[target] = xgb_model
            
            br = BayesianRidge()
            br.fit(X_train, y_train)
            models_mice[target] = br
            
        # Test on Targets
        phase2_results[feat_name] = {}
        for st in target_stations:
            df_st = df_targets[df_targets['Station'] == st]
            if len(df_st) == 0: continue
            
            X_test = df_st[feat_cols]
            st_res = {}
            for target in targets:
                y_test = df_st[target]
                st_res[f'XGB {target}'] = compute_metrics(y_test, models_xgb[target].predict(X_test))
                st_res[f'MICE {target}'] = compute_metrics(y_test, models_mice[target].predict(X_test))
            phase2_results[feat_name][st] = st_res
                
    # Print Phase 2 per station
    print(header)
    for feat_name, st_dict in phase2_results.items():
        print(f"\n--- Cấu hình: {feat_name} ---")
        for st, metrics in st_dict.items():
            row = f"Trạm {st:<15}"
            for t in targets:
                row += f" | {metrics[f'XGB {t}']:<8.4f} | {metrics[f'MICE {t}']:<9.4f}"
            print(row)

if __name__ == "__main__":
    run_experiment()
