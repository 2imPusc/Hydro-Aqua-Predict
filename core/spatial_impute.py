import os
import glob
import joblib
import pandas as pd
import numpy as np
from pathlib import Path

from core import paths
from core.config import HP_DATA_PATH

SPATIAL_MODELS_DIR = paths.SPATIAL_MODELS_DIR
ANCHOR_STATION = "NB2" # Trạm vật lý anh Toàn map tới Bến Bèo

# Các biến được phép truyền từ Anchor (Theo train_spatial.py)
ANCHOR_FEATURES = ["pH", "Temperature", "TSS", "NH3", "DO", "Salinity", "PO4", "Coliform"]

# Lưu trữ các giá trị Trung vị lịch sử để làm Fallback
FALLBACK_MEDIANS = None
ALL_TARGETS = []
LOADED_MODELS = {}

def load_fallback_medians():
    global FALLBACK_MEDIANS, ALL_TARGETS
    if FALLBACK_MEDIANS is None:
        try:
            df = pd.read_csv(HP_DATA_PATH)
            numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
            ALL_TARGETS = [c for c in numeric_cols if c not in ["X", "Y"]]
            
            # Tính trung vị (Median) cho tất cả các trạm
            # Groupby Station and Parameter
            FALLBACK_MEDIANS = df.groupby("Station")[ALL_TARGETS].median().to_dict('index')
        except Exception as e:
            print(f"Lỗi load medians: {e}")
            FALLBACK_MEDIANS = {}
    return FALLBACK_MEDIANS

def predict_virtual_stations(anchor_imputed_params: dict):
    """
    Nhận vào dict 14 tham số của Trạm Mỏ neo (đã chạy qua Local Imputation).
    Trả về dict dạng:
    {
      "NB15": {"DO": 6.5, "Salinity": 29.5, ...},
      "NB16": {...}
    }
    """
    # 1. Chuẩn bị Vector Đầu vào (X)
    X_dict = {}
    for feat in ANCHOR_FEATURES:
        X_dict[f"{feat}_anchor"] = anchor_imputed_params.get(feat, np.nan)
        
    X_df = pd.DataFrame([X_dict])
    
    # 2. Quét Model
    model_files = glob.glob(str(SPATIAL_MODELS_DIR / f"{ANCHOR_STATION}_*.pkl"))
    
    predictions = {}
    load_fallback_medians()
    
    # Khởi tạo khung (skeleton) cho tất cả các trạm vệ tinh với giá trị Fallback
    # Lọc danh sách trạm từ lịch sử, trừ Anchor
    target_stations = [s for s in FALLBACK_MEDIANS.keys() if s != ANCHOR_STATION]
    
    for st in target_stations:
        predictions[st] = {
            "imputed_by": {},
            "values": {}
        }
        # Mặc định điền Trung vị cho tất cả các biến
        for t in ALL_TARGETS:
            predictions[st]["values"][t] = FALLBACK_MEDIANS.get(st, {}).get(t, np.nan)
            predictions[st]["imputed_by"][t] = "median"
            
    # 3. Chạy Suy diễn Không gian (Spatial Extrapolation) bằng XGBoost
    global LOADED_MODELS
    for model_path in model_files:
        filename = os.path.basename(model_path).replace(".pkl", "")
        # Format: {anchor_station}_{target_station}_{target_param}
        parts = filename.split("_")
        if len(parts) >= 3:
            target_station = parts[1]
            target_param = parts[2]
            
            try:
                if model_path not in LOADED_MODELS:
                    LOADED_MODELS[model_path] = joblib.load(model_path)
                model = LOADED_MODELS[model_path]
                
                # Dự đoán
                pred_val = float(model.predict(X_df)[0])
                
                # Cập nhật kết quả (Ghi đè lên Fallback Median)
                if target_station in predictions:
                    predictions[target_station]["values"][target_param] = pred_val
                    predictions[target_station]["imputed_by"][target_param] = "xgboost_spatial"
                    
            except Exception as e:
                pass
                
    return predictions
