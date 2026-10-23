import pandas as pd
import numpy as np
import math
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from hap_shared.preprocessing import vn2000_to_wgs84

# One-off prep: raw depth/weather handover files live outside this repo.
EXOGENOUS_SRC = os.getenv("HAP_EXOGENOUS_SRC", "D:/2impusc/BAN_GIAO_MODEL_GHEP_DU_LIEU")

def haversine_m(lat1, lon1, lat2, lon2):
    radius_m = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return 2 * radius_m * math.asin(math.sqrt(a))

def prepare_data():
    print("Loading clean_data.csv...")
    df = pd.read_csv("data/haiphong/clean_data.csv")
    
    print("Converting VN2000 to WGS84...")
    lats, lons = vn2000_to_wgs84(df['X'].values, df['Y'].values)
    df['latitude'] = lats
    df['longitude'] = lons
    
    print("Loading depth data...")
    depth_df = pd.read_csv(f"{EXOGENOUS_SRC}/dosau_QN.csv")
    
    print("Calculating nearest depth for each station...")
    unique_stations = df[['Station', 'latitude', 'longitude']].drop_duplicates()
    
    depth_results = []
    for _, row in unique_stations.iterrows():
        lat, lon = row['latitude'], row['longitude']
        min_dist = float('inf')
        best_depth = np.nan
        for _, d_row in depth_df.iterrows():
            dist = haversine_m(lat, lon, d_row['latitude'], d_row['longitude'])
            if dist < min_dist:
                min_dist = dist
                best_depth = d_row['DOSAU']
        depth_results.append({'Station': row['Station'], 'Depth': best_depth})
    
    depth_res_df = pd.DataFrame(depth_results)
    df = df.merge(depth_res_df, on='Station', how='left')
    
    print("Loading weather data...")
    w1 = pd.read_excel(f"{EXOGENOUS_SRC}/daily_weather_wave_2021_2024.xlsx")
    w2 = pd.read_excel(f"{EXOGENOUS_SRC}/daily_weather_wave_2025.xlsx")
    weather = pd.concat([w1, w2], ignore_index=True)
    weather['date'] = pd.to_datetime(weather['date'])
    weather['Year'] = weather['date'].dt.year
    weather['Quarter'] = weather['date'].dt.quarter
    
    print("Aggregating weather data by Median per Quarter...")
    weather_q = weather.groupby(['latitude', 'longitude', 'Year', 'Quarter'], as_index=False).agg({
        'rain_mm': 'median',
        'wind_m_s': 'median',
        'wave_m': 'median'
    })
    
    weather_coords = weather[['latitude', 'longitude']].drop_duplicates()
    station_weather_map = {}
    for _, row in unique_stations.iterrows():
        lat, lon = row['latitude'], row['longitude']
        min_dist = float('inf')
        best_lat = None
        best_lon = None
        for _, w_row in weather_coords.iterrows():
            dist = haversine_m(lat, lon, w_row['latitude'], w_row['longitude'])
            if dist < min_dist:
                min_dist = dist
                best_lat = w_row['latitude']
                best_lon = w_row['longitude']
        station_weather_map[row['Station']] = (best_lat, best_lon)
    
    print("Mapping weather to dataset...")
    dt = pd.to_datetime(df['Quarter'])
    df['dt_Year'] = dt.dt.year
    df['dt_Quarter'] = dt.dt.quarter
    
    rain_list, wind_list, wave_list = [], [], []
    for _, row in df.iterrows():
        st = row['Station']
        yr = row['dt_Year']
        qt = row['dt_Quarter']
        w_lat, w_lon = station_weather_map[st]
        
        match = weather_q[(weather_q['latitude'] == w_lat) & 
                          (weather_q['longitude'] == w_lon) & 
                          (weather_q['Year'] == yr) & 
                          (weather_q['Quarter'] == qt)]
        
        if not match.empty:
            rain_list.append(match['rain_mm'].values[0])
            wind_list.append(match['wind_m_s'].values[0])
            wave_list.append(match['wave_m'].values[0])
        else:
            rain_list.append(np.nan)
            wind_list.append(np.nan)
            wave_list.append(np.nan)
            
    df['Rain_median'] = rain_list
    df['Wind_median'] = wind_list
    df['Wave_median'] = wave_list
    
    out_path = "haiphong_exogenous.csv"
    df.to_csv(out_path, index=False)
    print(f"Data saved to {out_path}")
    print(df[['Station', 'Depth', 'Rain_median', 'Wind_median', 'Wave_median']].head())

if __name__ == "__main__":
    prepare_data()
