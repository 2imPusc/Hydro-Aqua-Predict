import pandas as pd
import numpy as np
from sklearn.model_selection import KFold
from sklearn.metrics import r2_score
from xgboost import XGBRegressor
import warnings
warnings.filterwarnings("ignore")

def experiment_pipeline_order():
    print("=== THỬ NGHIỆM ĐÁNH GIÁ THỨ TỰ KIẾN TRÚC PIPELINE (A vs B) ===")
    
    df = pd.read_csv("data/haiphong/clean_data.csv")
    anchor_st = "NB1"
    target_st = "NB4"
    
    df_anchor = df[df["Station"] == anchor_st].set_index("Quarter")
    df_target = df[df["Station"] == target_st].set_index("Quarter")
    
    merged = df_anchor.join(df_target, lsuffix="_anchor", rsuffix="_target", how="inner")
    
    # Bỏ qua các hàng thiếu dữ liệu
    core_params = ["pH", "Temperature", "TSS", "NH3"]
    eval_params = ["DO", "Salinity"]
    
    cols_to_drop = [f"{p}_anchor" for p in core_params] + [f"{p}_target" for p in core_params] + \
                   [f"{p}_anchor" for p in eval_params] + [f"{p}_target" for p in eval_params]
    merged = merged.dropna(subset=cols_to_drop)
    
    if len(merged) < 10:
        print("Không đủ dữ liệu chung để test.")
        return
        
    X_anchor_raw = merged[[f"{p}_anchor" for p in core_params]].values
    X_target_raw = merged[[f"{p}_target" for p in core_params]].values
    
    kf = KFold(n_splits=3, shuffle=True, random_state=42)
    
    results_A = {"DO": {"trues": [], "preds": []}, "Salinity": {"trues": [], "preds": []}}
    results_B = {"DO": {"trues": [], "preds": []}, "Salinity": {"trues": [], "preds": []}}
    
    for tr, te in kf.split(X_anchor_raw):
        # -------------------------------------------------------------
        # ORDER A: LOCAL IMPUTE AT ANCHOR -> SPATIAL EXTRAPOLATION
        # -------------------------------------------------------------
        for param in eval_params:
            y_anchor_param = merged[f"{param}_anchor"].values
            y_target_param = merged[f"{param}_target"].values
            
            # Step A1: Huấn luyện Local Imputer tại Anchor
            local_imputer_A = XGBRegressor(n_estimators=50, max_depth=3, random_state=42)
            local_imputer_A.fit(X_anchor_raw[tr], y_anchor_param[tr])
            
            # Dự đoán giá trị Local Imputed cho cả tập Train và Test để làm feature cho bước 2
            imputed_anchor_train = local_imputer_A.predict(X_anchor_raw[tr]).reshape(-1, 1)
            imputed_anchor_test = local_imputer_A.predict(X_anchor_raw[te]).reshape(-1, 1)
            
            # Ghép feature gốc với feature imputed
            X_spatial_train = np.hstack([X_anchor_raw[tr], imputed_anchor_train])
            X_spatial_test = np.hstack([X_anchor_raw[te], imputed_anchor_test])
            
            # Step A2: Huấn luyện Spatial Extrapolator từ bộ feature đã ghép
            spatial_extrapolator_A = XGBRegressor(n_estimators=50, max_depth=3, random_state=42)
            spatial_extrapolator_A.fit(X_spatial_train, y_target_param[tr])
            
            # Dự đoán đích
            preds_A = spatial_extrapolator_A.predict(X_spatial_test)
            
            results_A[param]["preds"].extend(preds_A)
            results_A[param]["trues"].extend(y_target_param[te])

        # -------------------------------------------------------------
        # ORDER B: SPATIAL EXTRAPOLATION OF RAW PARAMS -> LOCAL IMPUTE AT TARGET
        # -------------------------------------------------------------
        # Step B1: Huấn luyện 4 mô hình Spatial Extrapolator cho 4 core params
        preds_target_raw_train = np.zeros_like(X_target_raw[tr])
        preds_target_raw_test = np.zeros_like(X_target_raw[te])
        
        for i, param in enumerate(core_params):
            y_target_core = merged[f"{param}_target"].values
            spatial_core_imputer = XGBRegressor(n_estimators=50, max_depth=3, random_state=42)
            spatial_core_imputer.fit(X_anchor_raw[tr], y_target_core[tr])
            
            preds_target_raw_train[:, i] = spatial_core_imputer.predict(X_anchor_raw[tr])
            preds_target_raw_test[:, i] = spatial_core_imputer.predict(X_anchor_raw[te])
            
        # Step B2: Huấn luyện Local Imputer tại Target
        for param in eval_params:
            y_target_param = merged[f"{param}_target"].values
            local_imputer_B = XGBRegressor(n_estimators=50, max_depth=3, random_state=42)
            
            # CHÚ Ý LỚN: Phải huấn luyện mô hình Local Bằng Dữ Liệu GỐC (Ground Truth) của Target
            # (Vì trên thực tế, ta học mô hình Local Imputer bằng Data lịch sử chuẩn)
            # Sau đó khi Inference, ta mới truyền dữ liệu đã suy diễn Không Gian vào
            local_imputer_B.fit(X_target_raw[tr], y_target_param[tr])
            
            # Inference bằng dữ liệu đã chạy qua Spatial Impute
            preds_B = local_imputer_B.predict(preds_target_raw_test)
            
            results_B[param]["preds"].extend(preds_B)
            results_B[param]["trues"].extend(y_target_param[te])

    print("\n[KẾT QUẢ R² SCORE: TỪ NB2 DỰ ĐOÁN NB15]")
    print(f"{'Chỉ số':<15} | {'ORDER A (Local -> Spatial)':<30} | {'ORDER B (Spatial -> Local)':<30}")
    print("-" * 80)
    for param in eval_params:
        r2_A = r2_score(results_A[param]["trues"], results_A[param]["preds"])
        r2_B = r2_score(results_B[param]["trues"], results_B[param]["preds"])
        print(f"{param:<15} | {r2_A:<30.4f} | {r2_B:<30.4f}")

if __name__ == "__main__":
    experiment_pipeline_order()
