import pandas as pd
import numpy as np

def analyze_geographic_correlation():
    # Kết quả R2 từ mô hình Spatial Imputation
    r2_results = {
        'NB15': 0.7113, 'NB2': 0.7231, 'NB4': 0.6912, 
        'NB3': 0.6682, 'NB16': 0.6410, 'NB6': 0.5811, 'NB5': 0.5734,
        'NB17': 0.3263, 'NB19': 0.1309
    }
    
    df = pd.read_csv("data/haiphong/clean_data.csv")
    df_coords = df[['Station', 'Station_Name', 'X', 'Y']].drop_duplicates()
    
    # Tọa độ NB1 (Anchor)
    nb1 = df_coords[df_coords['Station'] == 'NB1'].iloc[0]
    nb1_x, nb1_y = nb1['X'], nb1['Y']
    
    analysis = []
    
    for _, row in df_coords.iterrows():
        station = row['Station']
        if station == 'NB1' or station not in r2_results:
            continue
            
        # Tính khoảng cách Euclidean (X, Y là VN-2000 tính bằng mét)
        # Chuyển sang KM
        dist_km = np.sqrt((row['X'] - nb1_x)**2 + (row['Y'] - nb1_y)**2) / 1000
        
        analysis.append({
            'Station': station,
            'Name': row['Station_Name'],
            'Distance_km': round(dist_km, 2),
            'Salinity_R2': r2_results[station]
        })
        
    res_df = pd.DataFrame(analysis).sort_values('Distance_km')
    print("=== PHÂN TÍCH ĐỒNG NHẤT GIỮA ĐỊA LÝ VÀ CHẤT LƯỢNG MÔ HÌNH (R²) ===")
    print(f"Trạm Mỏ neo (Anchor): NB1 (Cảng cá Cát Bà)\n")
    print(res_df.to_string(index=False))

if __name__ == "__main__":
    analyze_geographic_correlation()
