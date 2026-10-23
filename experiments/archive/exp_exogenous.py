import pandas as pd
import numpy as np
from sklearn.model_selection import KFold
from sklearn.metrics import r2_score
from xgboost import XGBRegressor
import warnings
warnings.filterwarnings("ignore")

def run_experiment(df, anchor_st, target_st, anchor_features, target_features, name):
    df_anchor = df[df["Station"] == anchor_st].set_index("Quarter")
    df_target = df[df["Station"] == target_st].set_index("Quarter")
    
    merged = df_anchor.join(df_target, lsuffix="_anchor", rsuffix="_target", how="inner")
    
    eval_params = ["DO", "Salinity"]
    
    # Drop NAs
    cols_to_drop = anchor_features + target_features + [f"{p}_anchor" for p in eval_params] + [f"{p}_target" for p in eval_params]
    merged = merged.dropna(subset=cols_to_drop)
    
    if len(merged) < 5:
        return {"DO": np.nan, "Salinity": np.nan}
        
    X_anchor_data = merged[anchor_features].values
    X_target_data = merged[target_features].values if target_features else np.empty((len(merged), 0))
    
    kf = KFold(n_splits=3, shuffle=True, random_state=42)
    
    results = {}
    for param in eval_params:
        y_anchor = merged[f"{param}_anchor"].values
        y_target = merged[f"{param}_target"].values
        
        preds_target, trues_target = [], []
        
        for tr, te in kf.split(X_anchor_data):
            local_imputer = XGBRegressor(n_estimators=50, max_depth=3, random_state=42, verbosity=0)
            local_imputer.fit(X_anchor_data[tr], y_anchor[tr])
            
            imputed_anchor_train = local_imputer.predict(X_anchor_data[tr]).reshape(-1, 1)
            imputed_anchor_test = local_imputer.predict(X_anchor_data[te]).reshape(-1, 1)
            
            if target_features:
                X_spatial_train = np.hstack([X_anchor_data[tr], imputed_anchor_train, X_target_data[tr]])
                X_spatial_test = np.hstack([X_anchor_data[te], imputed_anchor_test, X_target_data[te]])
            else:
                X_spatial_train = np.hstack([X_anchor_data[tr], imputed_anchor_train])
                X_spatial_test = np.hstack([X_anchor_data[te], imputed_anchor_test])
            
            spatial_imputer = XGBRegressor(n_estimators=50, max_depth=3, random_state=42, verbosity=0)
            spatial_imputer.fit(X_spatial_train, y_target[tr])
            
            preds_target.extend(spatial_imputer.predict(X_spatial_test))
            trues_target.extend(y_target[te])
            
        results[param] = r2_score(trues_target, preds_target)
        
    return results

def main():
    print("=== THỰC NGHIỆM TÍCH HỢP ĐẶC TRƯNG NGOẠI LAI VÀO SPATIAL EXTRAPOLATION (FULL STATIONS) ===")
    df = pd.read_csv("haiphong_exogenous.csv")
    
    anchor_st = "NB1"
    all_targets = [st for st in df["Station"].unique() if st != anchor_st]
    
    base_anchor = [f"{p}_anchor" for p in ["pH", "Temperature", "TSS", "NH3"]]
    depth_anchor = ["Depth_anchor"]
    weather_anchor = ["Rain_median_anchor", "Wind_median_anchor", "Wave_median_anchor"]
    coords_anchor = ["latitude_anchor", "longitude_anchor"]
    
    depth_target = ["Depth_target"]
    weather_target = ["Rain_median_target", "Wind_median_target", "Wave_median_target"]
    coords_target = ["latitude_target", "longitude_target"]
    
    configs = {
        "Base (4 Chi so goc)": (base_anchor, []),
        "Base + Do sau": (base_anchor + depth_anchor, depth_target),
        "Base + Thoi tiet": (base_anchor + weather_anchor, weather_target),
        "Base + Toa do (Lat/Lon)": (base_anchor + coords_anchor, coords_target),
        "Base + Toa do + Thoi tiet": (base_anchor + coords_anchor + weather_anchor, coords_target + weather_target),
        "Tat ca (All)": (base_anchor + depth_anchor + weather_anchor + coords_anchor, depth_target + weather_target + coords_target)
    }
    
    print(f"\n[Ket qua R2 trung binh tu tram {anchor_st} du doan cho {len(all_targets)} tram Target]")
    print("-" * 80)
    print(f"{'Cau hinh (Feature Set)':<40} | {'DO (Oxy)':<15} | {'Salinity':<15}")
    print("-" * 80)
    
    for name, (anch_feats, targ_feats) in configs.items():
        do_scores = []
        sal_scores = []
        
        for tgt in all_targets:
            res = run_experiment(df, anchor_st, tgt, anch_feats, targ_feats, name)
            if not pd.isna(res['DO']):
                do_scores.append(res['DO'])
            if not pd.isna(res['Salinity']):
                sal_scores.append(res['Salinity'])
                
        mean_do = np.mean(do_scores) if do_scores else np.nan
        mean_sal = np.mean(sal_scores) if sal_scores else np.nan
        
        do_str = f"{mean_do:.4f}" if not pd.isna(mean_do) else "N/A"
        sal_str = f"{mean_sal:.4f}" if not pd.isna(mean_sal) else "N/A"
        
        print(f"{name:<40} | {do_str:<15} | {sal_str:<15}")

if __name__ == "__main__":
    main()

if __name__ == "__main__":
    main()
