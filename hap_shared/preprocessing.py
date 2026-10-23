import pandas as pd
import numpy as np
from pyproj import Proj


WATER_QUALITY_PARAMS = [
    'DO', 'Temperature', 'pH', 'Salinity', 'NH3', 'PO4', 'TSS',
    'Coliform', 'Transparency', 'COD', 'CN', 'As', 'Cd', 'Pb',
    'Cu', 'Hg', 'Zn', 'Total_Cr', 'H2S', 'BOD5', 'Alkalinity'
]

METADATA_COLUMNS = {'Station', 'Quarter', 'X', 'Y', 'Lat', 'Lon',
                    'year', 'quarter_num', 'time_idx'}


def detect_water_quality_params(df):
    """Auto-detect water quality parameter columns from DataFrame.

    Returns columns that are numeric and not in METADATA_COLUMNS.
    Order: known params first (preserving WATER_QUALITY_PARAMS order), then unknown.
    """
    numeric_cols = df.select_dtypes(include='number').columns.tolist()
    detected = [c for c in numeric_cols if c not in METADATA_COLUMNS]
    known = [p for p in WATER_QUALITY_PARAMS if p in detected]
    unknown = [p for p in detected if p not in WATER_QUALITY_PARAMS]
    return known + unknown


# NB74, NB78 nằm gần cửa sông/kênh nội địa, có giá trị NH3 và Salinity
# lệch hệ thống so với phần còn lại của vịnh (+25-58%), có thể gây nhiễu
# khi huấn luyện mô hình chung. Loại trừ ở cả app và script đánh giá.
EXCLUDED_STATIONS = ['NB74', 'NB78']


def _clean_numeric_column(series: pd.Series) -> pd.Series:
    """Handle non-numeric water quality values like '<0,0003', '< 0.005'.

    Values below detection limit (e.g. '<0.005') are replaced with LOD/2,
    which is the standard convention in environmental monitoring.
    Comma decimals (e.g. '0,0003') are converted to dots.
    """
    if pd.api.types.is_numeric_dtype(series):
        return series

    cleaned = series.astype(object).copy()
    mask_str = cleaned.apply(lambda x: isinstance(x, str))
    if not mask_str.any():
        return pd.to_numeric(cleaned, errors='coerce')

    str_vals = cleaned[mask_str].copy()
    # Replace comma decimal separator with dot
    str_vals = str_vals.str.replace(',', '.', regex=False)
    # Strip whitespace
    str_vals = str_vals.str.strip()

    # Handle '<' prefix (below detection limit -> LOD / 2)
    below_lod = str_vals.str.startswith('<')
    if below_lod.any():
        lod_vals = str_vals[below_lod].str.lstrip('<').str.strip()
        lod_numeric = pd.to_numeric(lod_vals, errors='coerce')
        str_vals.loc[below_lod] = (lod_numeric / 2).astype(str)

    cleaned[mask_str] = str_vals
    return pd.to_numeric(cleaned, errors='coerce')


def load_data(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df['Quarter'] = pd.to_datetime(df['Quarter'])
    # Convert water-quality columns to numeric (handle '<0,0003' etc.)
    for col in WATER_QUALITY_PARAMS:
        if col in df.columns:
            df[col] = _clean_numeric_column(df[col])
    df = df.sort_values(['Station', 'Quarter']).reset_index(drop=True)
    return df


def build_features_for_station(station_df: pd.DataFrame, param: str) -> pd.DataFrame:
    """Tạo features cho 1 trạm và 1 chỉ số: lag, rolling mean, seasonal."""
    df = station_df[['Quarter', param]].copy()
    df = df.sort_values('Quarter').reset_index(drop=True)

    df['year'] = df['Quarter'].dt.year
    df['quarter_num'] = df['Quarter'].dt.quarter
    df['time_idx'] = np.arange(len(df))

    # Seasonal encoding
    df['sin_quarter'] = np.sin(2 * np.pi * df['quarter_num'] / 4)
    df['cos_quarter'] = np.cos(2 * np.pi * df['quarter_num'] / 4)

    # Lag features
    for lag in [1, 2, 4]:
        df[f'lag_{lag}'] = df[param].shift(lag)

    # Rolling mean (shifted to avoid data leakage)
    df['rolling_mean_4'] = df[param].shift(1).rolling(window=4, min_periods=2).mean()

    return df


def prepare_train_data(df: pd.DataFrame, station: str, param: str):
    """Chuẩn bị X, y cho 1 trạm + 1 chỉ số."""
    station_df = df[df['Station'] == station].copy()
    feat_df = build_features_for_station(station_df, param)
    feat_df = feat_df.dropna()

    feature_cols = ['time_idx', 'sin_quarter', 'cos_quarter',
                    'lag_1', 'lag_2', 'lag_4', 'rolling_mean_4']
    X = feat_df[feature_cols].values
    y = feat_df[param].values

    return X, y, feature_cols, feat_df


# VN-2000 TM-3: mui chieu 3 do, kinh tuyen trung tam 107°45'E
# Phu hop vung Quang Ninh / Hai Phong
# k=0.9999 (mui 3 do), towgs84 = tham so chuyen datum VN-2000 → WGS84
_VN2000_TM6 = Proj(
    proj='tmerc',
    lat_0=0,
    lon_0=107.75,
    k=0.9999,
    x_0=500000,
    y_0=0,
    ellps='WGS84',
    towgs84='-191.90441429,-39.30318279,-111.45032835,'
            '0.00928836,-0.01975479,0.00427372,0.252906278',
    units='m',
    no_defs=True
)


def vn2000_to_wgs84(x_northing, y_easting):
    """Chuyen VN-2000 TM-6 sang WGS84 lat/lon.
    X = Northing (~2,300,000), Y = Easting (~400,000-500,000).
    """
    lon, lat = _VN2000_TM6(y_easting, x_northing, inverse=True)
    return lat, lon


def get_station_coords(df: pd.DataFrame, with_latlon: bool = True) -> pd.DataFrame:
    """Lay toa do duy nhat cua tung tram. Neu with_latlon=True thi chuyen sang WGS84."""
    coords = df.groupby('Station')[['X', 'Y']].first().reset_index()
    if with_latlon:
        lats, lons = vn2000_to_wgs84(
            coords['X'].values, coords['Y'].values
        )
        coords['lat'] = lats
        coords['lon'] = lons
    return coords
