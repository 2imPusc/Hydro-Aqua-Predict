"""Test delayed observed-weather effects on hourly Hai Phong sensor forecasts.

Weather columns are shifted before rolling, so each row only sees weather that
was available before its forecast origin. This is a causal-lag study, not an
as-issued forecast-weather backtest; it must not promote a production model.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from core.quality import is_in_range

PARAMS = ("Temperature", "pH", "NH4", "TSS")
HORIZONS = (1, 3, 6)
SENSOR_LAGS = (1, 2, 3, 6, 12)
WEATHER_WINDOWS = (1, 3, 6, 12, 24)
WEATHER_URL = "https://archive-api.open-meteo.com/v1/archive"


def fetch_weather_history(latitude: float, longitude: float, start_date: str, end_date: str) -> pd.DataFrame:
    query = urlencode({"latitude": latitude, "longitude": longitude, "start_date": start_date, "end_date": end_date, "hourly": "temperature_2m,precipitation,wind_speed_10m,cloud_cover,surface_pressure", "timezone": "Asia/Ho_Chi_Minh"})
    with urlopen(f"{WEATHER_URL}?{query}", timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    hourly = pd.DataFrame(payload["hourly"])
    hourly["time"] = pd.to_datetime(hourly["time"]).dt.tz_localize("Asia/Ho_Chi_Minh").dt.tz_convert("UTC")
    return hourly.set_index("time").sort_index()


def weather_lag_features(weather: pd.DataFrame) -> pd.DataFrame:
    """Aggregate only completed prior hours; no target-hour weather leakage."""
    out = pd.DataFrame(index=weather.index)
    past = weather.shift(1)
    for window in WEATHER_WINDOWS:
        out[f"rain_sum_{window}h"] = past["precipitation"].rolling(window, min_periods=window).sum()
        out[f"wind_mean_{window}h"] = past["wind_speed_10m"].rolling(window, min_periods=window).mean()
    out["air_temperature_lag_1h"] = past["temperature_2m"]
    out["cloud_cover_lag_1h"] = past["cloud_cover"]
    out["surface_pressure_lag_1h"] = past["surface_pressure"]
    return out


def _calendar(index: pd.DatetimeIndex) -> pd.DataFrame:
    local = index.tz_convert("Asia/Ho_Chi_Minh")
    hour, dow = local.hour, local.dayofweek
    return pd.DataFrame({"hour_sin": np.sin(2 * np.pi * hour / 24), "hour_cos": np.cos(2 * np.pi * hour / 24), "dow_sin": np.sin(2 * np.pi * dow / 7), "dow_cos": np.cos(2 * np.pi * dow / 7)}, index=index)


def supervised(sensor: pd.Series, weather_features: pd.DataFrame, horizon_hours: int, include_weather: bool) -> tuple[pd.DataFrame, list[str]]:
    frame = pd.DataFrame({"value": sensor})
    for lag in SENSOR_LAGS:
        frame[f"sensor_lag_{lag}h"] = frame["value"].shift(lag)
    future_index = frame.index + pd.Timedelta(hours=horizon_hours)
    for name, values in _calendar(future_index).items():
        frame[name] = values.to_numpy()
    if include_weather:
        frame = frame.join(weather_features, how="left")
    frame["target"] = frame["value"].shift(-horizon_hours)
    frame = frame.dropna()
    features = [c for c in frame if c.startswith("sensor_lag_") or c.endswith(("_sin", "_cos")) or (include_weather and c in weather_features.columns)]
    return frame, features


def _models():
    return {"ridge": make_pipeline(StandardScaler(), Ridge(alpha=1.0)), "extra_trees": ExtraTreesRegressor(n_estimators=200, min_samples_leaf=3, random_state=42, n_jobs=1), "xgboost": XGBRegressor(n_estimators=120, max_depth=3, learning_rate=.05, random_state=42, verbosity=0)}


def _metrics(actual, predicted):
    return {"mae": float(mean_absolute_error(actual, predicted)), "rmse": float(np.sqrt(mean_squared_error(actual, predicted))), "r2": float(r2_score(actual, predicted))}


def evaluate(sensor: pd.Series, weather: pd.DataFrame, param: str, horizon: int) -> list[dict]:
    rows = []
    for name, include_weather in (("sensor_plus_time", False), ("sensor_time_weather_lags", True)):
        frame, features = supervised(sensor, weather, horizon, include_weather)
        split = int(len(frame) * .8)
        if split < 48 or len(frame) - split < 24:
            rows.append({"param": param, "horizon_hours": horizon, "feature_set": name, "model": "not_evaluated", "n": len(frame), "reason": "insufficient_hourly_samples"})
            continue
        train, test = frame.iloc[:split], frame.iloc[split:]
        for model_name, model in _models().items():
            model.fit(train[features], train.target)
            rows.append({"param": param, "horizon_hours": horizon, "feature_set": name, "model": model_name, "n_train": len(train), "n_test": len(test), **_metrics(test.target, model.predict(test[features]))})
    return rows


def run(sensor_csv: Path, station: str, latitude: float, longitude: float) -> pd.DataFrame:
    raw = pd.read_csv(sensor_csv)
    raw = raw[raw["device"].astype(str).eq(station)].copy()
    raw["fetchedAt"] = pd.to_datetime(raw["fetchedAt"], utc=True)
    # Open-Meteo's archive is complete only through the previous UTC day.  A
    # live cache may include today, so asking for ``max + 1 day`` can request a
    # future date and fail with HTTP 400.
    latest_archive_day = pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)
    sensor_end_day = raw["fetchedAt"].max().normalize()
    archive_end_day = min(sensor_end_day, latest_archive_day)
    weather = fetch_weather_history(
        latitude,
        longitude,
        raw["fetchedAt"].min().date().isoformat(),
        archive_end_day.date().isoformat(),
    )
    lagged_weather = weather_lag_features(weather)
    rows = []
    for param in PARAMS:
        valid = raw.loc[raw[param].map(lambda v: is_in_range(param, v)), ["fetchedAt", param]].set_index("fetchedAt")[param]
        hourly = valid.resample("1h").median().dropna()
        for horizon in HORIZONS:
            rows.extend(evaluate(hourly, lagged_weather, param, horizon))
    return pd.DataFrame(rows)


def summary(result: pd.DataFrame) -> pd.DataFrame:
    usable = result[result.model.ne("not_evaluated")].copy()
    base = usable[usable.feature_set.eq("sensor_plus_time")].rename(columns={"mae": "base_mae", "rmse": "base_rmse", "r2": "base_r2"})
    weather = usable[usable.feature_set.eq("sensor_time_weather_lags")]
    merged = weather.merge(base[["param", "horizon_hours", "model", "base_mae", "base_rmse", "base_r2"]], on=["param", "horizon_hours", "model"])
    merged["rmse_delta"] = merged["rmse"] - merged["base_rmse"]
    merged["mae_delta"] = merged["mae"] - merged["base_mae"]
    return merged.sort_values(["param", "model", "horizon_hours"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--station", required=True)
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.csv, args.station, args.latitude, args.longitude)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    comparison = summary(result)
    comparison.to_csv(args.output.with_name(args.output.stem + "_comparison.csv"), index=False)
    print(comparison.to_string(index=False))


if __name__ == "__main__":
    main()
