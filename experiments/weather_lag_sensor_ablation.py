"""Test delayed observed-weather effects on hourly Hai Phong sensor forecasts.

Weather columns are shifted before rolling, so each row only sees weather that
was available before its forecast origin. This is a causal-lag study, not an
as-issued forecast-weather backtest; it must not promote a production model.

Two modes:

    # legacy forecast ablation (unpinned archive weather = best_match, decisions #18)
    python experiments/weather_lag_sensor_ablation.py <csv> --station ... --latitude ... --longitude ... --output ...

    # H2.3 rain -> sensor lag response (ERA5 pinned, models=era5)
    python experiments/weather_lag_sensor_ablation.py lag-response --run-name weather-lag-20261024 [--fetch-sea-level]

``lag-response`` quantifies whether, and with what delay, rain changes NH4 / TSS (Temperature
is the positive control) at 06M26042804: hourly medians after core.quality QC, centred
rolling-median detrend, diurnal + tidal harmonics + model sea level as nuisance terms, a
binned distributed-lag regression on rain (0-72 h) with moving-block bootstrap CIs and a
circular-shift permutation test, a cross-correlation, and rain events (>= 10 mm / 6 h)
contrasted with same-hour matched dry periods. Output: paths.EXPERIMENT_OUTPUT_DIR/<run-name>/.
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


# =====================================================================================
# H2.3 lag-response: does rain change NH4 / TSS, and with what delay?
# =====================================================================================
STATION = "06M26042804"
LAG_PARAMS = ("NH4", "TSS", "Temperature")
LOG_PARAMS = frozenset({"NH4", "TSS"})  # positive, multiplicative: analyse log(y + eps), report % change
LOG_EPS = 0.1
# NH4 and TSS step down together on 2026-07-31 ~13:45 local (NH4 106 -> 5.3, TSS ~70 -> ~10);
# Temperature and pH do not move, so it is a probe service/recalibration, not water. Detrending
# never spans the step and the transition hours are dropped.
BREAK_AT = pd.Timestamp("2026-07-31 06:45", tz="UTC")
BREAK_GAP = (pd.Timestamp("2026-07-31 06:00", tz="UTC"), pd.Timestamp("2026-07-31 08:00", tz="UTC"))
BREAK_PARAMS = frozenset({"NH4", "TSS"})
MIN_READINGS_PER_HOUR = 30
# Rain lag bins (hours, inclusive). Lag 0 = rain falling during the sensor hour itself.
LAG_BINS = ((0, 2), (3, 5), (6, 11), (12, 17), (18, 23), (24, 35), (36, 47), (48, 59), (60, 72))
MAX_LAG = 72
DIURNAL_PERIODS_H = (24.0, 12.0, 8.0)
# Main tidal constituents resolvable in ~3500 h (S2 = diurnal 12 h harmonic, K2/P1 not separable).
TIDAL_PERIODS_H = {"O1": 25.8193, "K1": 23.9345, "Q1": 26.8684, "M2": 12.4206, "N2": 12.6583}
EVENT_THRESHOLD_MM = 10.0
EVENT_WINDOW_H = 6
EVENT_MIN_SEPARATION_H = 72  # = longest response window, so one storm episode gives one event
BASELINE_H = (-17, -6)  # relative to t0 = hour the 6-h sum first reaches the threshold
RESPONSE_WINDOWS_H = ((1, 6), (7, 12), (13, 24), (25, 48), (49, 72))
# "Clean" event: the 72 h after t0 get < CLEAN_FOLLOW_ON_MM, so late windows are not the early
# response to the next storm (overlap in the monsoon season). Primary event set; all events = sensitivity.
CLEAN_FOLLOW_ON_MM = 10.0
DRY_SEARCH_DAYS = (15, 30)
DRY_MAX_TOTAL_MM = 2.0
DRY_MAX_HOURLY_MM = 0.5
# Dry controls must also not sit in the recovery phase of an earlier storm.
DRY_ANTECEDENT_H = (-89, -18)
DRY_ANTECEDENT_MAX_MM = 5.0
MIN_WINDOW_COVERAGE = 0.75
BLOCK_HOURS = 48
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
EXTERNAL_CONTEXT_RUN = "external-context-06M26042804-2026-05-28_2026-10-15"


# ---------------------------------------------------------------- inputs
def load_hourly_sensor(csv_path: Path, params=LAG_PARAMS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hourly medians on a regular UTC grid after core.quality QC.

    Per reading: core.quality.is_in_range. Per local day: core.quality.sensor_day_health must
    be OK (drops TSS floor/stuck days, RL-04/RL-10). Per hour: >= MIN_READINGS_PER_HOUR readings.
    Returns (hourly, excluded_days).
    """
    from core.quality import sensor_day_health

    raw = pd.read_csv(csv_path)
    raw = raw[raw["device"].astype(str).eq(STATION)].copy()
    raw["t"] = pd.to_datetime(raw["fetchedAt"], utc=True)
    raw = raw.set_index("t").sort_index()
    local_day = raw.index.tz_convert("Asia/Ho_Chi_Minh").date
    grid = pd.date_range(raw.index.min().floor("h"), raw.index.max().floor("h"), freq="h")
    hourly, excluded = pd.DataFrame(index=grid), []
    for param in params:
        values = pd.to_numeric(raw[param], errors="coerce")
        keep = values.map(lambda v: is_in_range(param, v)).astype(bool)
        for day, group in values.groupby(local_day):
            status = sensor_day_health(param, group)
            if status["status"] != "OK":
                keep &= ~pd.Series(local_day == day, index=raw.index)
                excluded.append({"param": param, "local_day": str(day), "status": status["status"],
                                 "reasons": ";".join(status["reasons"])})
        kept = values[keep]
        agg = kept.resample("1h").agg(["median", "count"]).reindex(grid)
        series = agg["median"].where(agg["count"] >= MIN_READINGS_PER_HOUR)
        if param in BREAK_PARAMS:
            series[(series.index >= BREAK_GAP[0]) & (series.index < BREAK_GAP[1])] = np.nan
        hourly[param] = series
    return hourly, pd.DataFrame(excluded, columns=["param", "local_day", "status", "reasons"])


def load_archive_hourly(path: Path, column: str) -> pd.Series:
    df = pd.read_csv(path)
    index = pd.to_datetime(df["time"], utc=True)
    return pd.Series(pd.to_numeric(df[column], errors="coerce").to_numpy(), index=index, name=column).sort_index()


def rain_on_sensor_grid(precip: pd.Series) -> pd.Series:
    """Open-Meteo hourly precipitation is the sum over the hour ENDING at the stamp. Re-stamp to the
    hour start so rain[t] is the rain falling during sensor bin [t, t+1): lag 0 = same hour."""
    rain = precip.copy()
    rain.index = rain.index - pd.Timedelta(hours=1)
    return rain.asfreq("h")


def fetch_sea_level(latitude: float, longitude: float, start: str, end: str, target: Path) -> dict:
    """Write-once Open-Meteo Marine ``sea_level_height_msl`` (model tide + surge) into the run dir."""
    import hashlib
    from datetime import datetime, timezone

    import requests

    if target.exists():
        raise FileExistsError(target)
    params = {"latitude": latitude, "longitude": longitude, "hourly": "sea_level_height_msl",
              "start_date": start, "end_date": end, "timezone": "UTC", "cell_selection": "sea"}
    response = requests.get(MARINE_URL, params=params, timeout=120)
    response.raise_for_status()
    payload = response.json()
    sea = pd.DataFrame({"valid_at": pd.to_datetime(payload["hourly"]["time"], utc=True),
                        "sea_level_m": payload["hourly"]["sea_level_height_msl"]})
    target.parent.mkdir(parents=True, exist_ok=True)
    body = sea.to_csv(index=False).encode()
    target.write_bytes(body)
    meta = {"file": target.name, "url": MARINE_URL, "params": params, "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(), "fetched_at": datetime.now(timezone.utc).isoformat(),
            "grid_point": [payload.get("latitude"), payload.get("longitude")],
            "non_null": int(sea["sea_level_m"].notna().sum())}
    Path(f"{target}.manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def load_sea_level(paths_in: list[Path]) -> pd.Series:
    """Concatenate sea-level files; earlier files win on overlap."""
    parts = []
    for path in paths_in:
        df = pd.read_csv(path)
        parts.append(pd.Series(pd.to_numeric(df["sea_level_m"], errors="coerce").to_numpy(),
                               index=pd.to_datetime(df["valid_at"], utc=True)).dropna())
    out = parts[0]
    for part in parts[1:]:
        out = out.combine_first(part)
    return out.sort_index().asfreq("h")


# ---------------------------------------------------------------- transforms / design
def transform(param: str, values: pd.Series) -> pd.Series:
    return np.log(values + LOG_EPS) if param in LOG_PARAMS else values


def segments_for(param: str, index: pd.DatetimeIndex) -> pd.Series:
    seg = pd.Series(0, index=index)
    if param in BREAK_PARAMS:
        seg[index >= BREAK_AT] = 1
    return seg


def detrend(series: pd.Series, segments: pd.Series, window_h: int) -> pd.Series:
    """Subtract a centred rolling median (window_h hours, >= window_h/2 valid) computed per segment."""
    out = pd.Series(np.nan, index=series.index)
    for _, idx in series.groupby(segments).groups.items():
        part = series.loc[idx]
        trend = part.rolling(window_h, center=True, min_periods=window_h // 2).median()
        out.loc[idx] = part - trend
    return out


def harmonic_design(index: pd.DatetimeIndex, tidal: bool = True) -> pd.DataFrame:
    hours = (index - pd.Timestamp("2026-01-01", tz="UTC")) / pd.Timedelta(hours=1)
    hours = np.asarray(hours, dtype=float) + 0.5  # bin centre
    periods = {f"d{p:g}": p for p in DIURNAL_PERIODS_H}
    if tidal:
        periods.update(TIDAL_PERIODS_H)
    cols = {}
    for name, period in periods.items():
        cols[f"{name}_sin"] = np.sin(2 * np.pi * hours / period)
        cols[f"{name}_cos"] = np.cos(2 * np.pi * hours / period)
    return pd.DataFrame(cols, index=index)


def sea_level_design(index: pd.DatetimeIndex, sea: pd.Series) -> pd.DataFrame:
    eta = sea.reindex(index)
    return pd.DataFrame({"eta": eta, "deta": eta - sea.shift(1).reindex(index)}, index=index)


def rain_lag_bins(rain: pd.Series, index: pd.DatetimeIndex, bins=LAG_BINS) -> pd.DataFrame:
    """rain_l{a}_{b}[t] = sum of rain[t - l] for l in a..b (mm). NaN if any lag is missing."""
    rain = rain.asfreq("h")
    cols = {}
    for a, b in bins:
        total = sum(rain.shift(lag) for lag in range(a, b + 1))
        cols[f"rain_l{a:02d}_{b:02d}"] = total.reindex(index)
    return pd.DataFrame(cols, index=index)


def _ols(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, float]:
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    return beta, float(resid @ resid)


# ---------------------------------------------------------------- statistics
def _block_sample(positions: np.ndarray, block: int, rng: np.random.Generator) -> np.ndarray:
    """Moving-block bootstrap on the hourly grid: draw block starts on grid positions, keep the
    rows whose position falls inside, until the sample has as many rows as the data."""
    lo, hi = positions.min(), positions.max() - block + 1
    order = np.argsort(positions)
    sorted_pos = positions[order]
    picked, n = [], 0
    while n < len(positions):
        start = rng.integers(lo, max(hi, lo + 1))
        a, b = np.searchsorted(sorted_pos, [start, start + block])
        picked.append(order[a:b])
        n += b - a
    return np.concatenate(picked)[: len(positions)]


class _ShiftedRain:
    """Circular-shift null helper: rain over [start - MAX_LAG h, end] as an array, rotated by ``shift`` hours
    (keeps the rain autocorrelation), with lag sums for the given row times built by cumulative sums."""

    def __init__(self, rain: pd.Series, rows: pd.DatetimeIndex):
        start, end = rows.min(), rows.max()
        window = rain.asfreq("h").loc[start - pd.Timedelta(hours=MAX_LAG): end]
        self.values = window.fillna(0.0).to_numpy()
        self.pos = ((rows - window.index[0]) / pd.Timedelta(hours=1)).astype(int).to_numpy()
        self.span = len(self.values)

    def bins(self, shift: int, bins=LAG_BINS) -> np.ndarray:
        cs = np.concatenate([[0.0], np.cumsum(np.roll(self.values, shift))])
        # sum_{l=a..b} x[p - l] = cs[p - a + 1] - cs[p - b]
        return np.column_stack([cs[self.pos - a + 1] - cs[self.pos - b] for a, b in bins])

    def lags(self, shift: int, max_lag: int = MAX_LAG) -> np.ndarray:
        rolled = np.roll(self.values, shift)
        return rolled[self.pos[:, None] - np.arange(max_lag + 1)[None, :]]


def distributed_lag(y: pd.Series, nuisance: pd.DataFrame, rain: pd.Series, *, n_boot: int, n_perm: int,
                    seed: int = 20261024, extra: pd.DataFrame | None = None) -> dict:
    """Binned distributed-lag OLS of detrended y on rain lags + nuisance terms.

    CIs: moving-block bootstrap (BLOCK_HOURS) of rows. Joint test of "any rain effect at 0-72 h":
    circular-shift permutation of the rain series (>= 7 d shifts) on the partial-R2 of the rain block.
    """
    rng = np.random.default_rng(seed)
    lagx = rain_lag_bins(rain, y.index)
    base = nuisance if extra is None else nuisance.join(extra)
    frame = pd.concat([y.rename("y"), base, lagx], axis=1).dropna()
    if len(frame) < 500:
        return {"n_rows": len(frame), "status": "insufficient_rows"}
    rain_cols = list(lagx.columns)
    base_cols = list(base.columns)
    yv = frame["y"].to_numpy()
    xb = np.column_stack([np.ones(len(frame)), frame[base_cols].to_numpy()])
    xf = np.column_stack([xb, frame[rain_cols].to_numpy()])
    beta, rss_full = _ols(yv, xf)
    _, rss_base = _ols(yv, xb)
    stat = (rss_base - rss_full) / rss_base
    coefs = beta[-len(rain_cols):]

    grid0 = frame.index.min()
    positions = ((frame.index - grid0) / pd.Timedelta(hours=1)).astype(int).to_numpy()
    boot = np.empty((n_boot, len(rain_cols)))
    for i in range(n_boot):
        rows = _block_sample(positions, BLOCK_HOURS, rng)
        boot[i] = _ols(yv[rows], xf[rows])[0][-len(rain_cols):]

    start, end = frame.index.min(), frame.index.max()
    shifter = _ShiftedRain(rain, frame.index)
    assert np.allclose(shifter.bins(0), frame[rain_cols].to_numpy())
    null = np.empty(n_perm)
    for i in range(n_perm):
        xs = shifter.bins(int(rng.integers(168, shifter.span - 168)))
        _, rss_s = _ols(yv, np.column_stack([xb, xs]))
        null[i] = (rss_base - rss_s) / rss_base
    perm_p = float((1 + (null >= stat).sum()) / (1 + n_perm))

    peak = int(np.argmax(np.abs(coefs)))
    boot_peak = np.argmax(np.abs(boot), axis=1)
    resid_sd = float(np.sqrt(rss_base / len(frame)))
    rows_out = []
    for k, (col, (a, b)) in enumerate(zip(rain_cols, LAG_BINS)):
        lo, hi = np.percentile(boot[:, k], [2.5, 97.5])
        rows_out.append({"bin": col, "lag_from_h": a, "lag_to_h": b, "beta_per_mm": float(coefs[k]),
                         "ci_lo": float(lo), "ci_hi": float(hi), "ci_excludes_0": bool(lo > 0 or hi < 0),
                         "boot_peak_share": float((boot_peak == k).mean())})
    return {"status": "ok", "n_rows": len(frame), "start": str(start), "end": str(end),
            "partial_r2_rain": float(stat), "perm_p": perm_p, "null_q95": float(np.quantile(null, 0.95)),
            "resid_sd": resid_sd, "peak_bin": rain_cols[peak], "peak_lag_h": list(LAG_BINS[peak]),
            "peak_beta_per_mm": float(coefs[peak]), "peak_ci": [rows_out[peak]["ci_lo"], rows_out[peak]["ci_hi"]],
            "peak_boot_share": rows_out[peak]["boot_peak_share"], "rain_total_mm": float(frame[rain_cols[0]].sum()),
            "coefficients": rows_out}


def cross_correlation(resid: pd.Series, rain: pd.Series, *, n_boot: int, n_perm: int, seed: int = 7) -> tuple[pd.DataFrame, dict]:
    """corr(resid[t], rain[t - lag]) for lag 0..MAX_LAG; circular-shift null for the max |r|."""
    rng = np.random.default_rng(seed)
    resid = resid.dropna()
    idx = resid.index
    lagged = pd.DataFrame({lag: rain.asfreq("h").shift(lag).reindex(idx) for lag in range(MAX_LAG + 1)})
    ok = lagged.notna().all(axis=1)
    e, lagged = resid[ok].to_numpy(), lagged[ok].to_numpy()

    def corr_all(x: np.ndarray, rows=None) -> np.ndarray:
        ee = e if rows is None else e[rows]
        xx = x if rows is None else x[rows]
        ee = ee - ee.mean()
        xx = xx - xx.mean(axis=0)
        den = np.sqrt((ee @ ee) * (xx * xx).sum(axis=0))
        return np.where(den > 0, (ee @ xx) / np.where(den > 0, den, 1), 0.0)

    r = corr_all(lagged)
    positions = ((idx[ok] - idx[ok].min()) / pd.Timedelta(hours=1)).astype(int).to_numpy()
    boot = np.array([corr_all(lagged, _block_sample(positions, BLOCK_HOURS, rng)) for _ in range(n_boot)])
    shifter = _ShiftedRain(rain, idx[ok])
    assert np.allclose(shifter.lags(0), lagged)
    null_max, null_point = np.empty(n_perm), []
    for i in range(n_perm):
        rr = corr_all(shifter.lags(int(rng.integers(168, shifter.span - 168))))
        null_max[i] = np.abs(rr).max()
        null_point.append(rr)
    null_point = np.abs(np.array(null_point))
    table = pd.DataFrame({"lag_h": np.arange(MAX_LAG + 1), "r": r,
                          "ci_lo": np.percentile(boot, 2.5, axis=0), "ci_hi": np.percentile(boot, 97.5, axis=0),
                          "null_pointwise_abs_q95": np.quantile(null_point, 0.95, axis=0)})
    peak = int(np.argmax(np.abs(r)))
    summary_ = {"peak_lag_h": peak, "peak_r": float(r[peak]), "peak_ci": [float(table.ci_lo[peak]), float(table.ci_hi[peak])],
                "null_max_abs_q95": float(np.quantile(null_max, 0.95)),
                "max_abs_p": float((1 + (null_max >= abs(r[peak])).sum()) / (1 + n_perm)), "n": int(len(e))}
    return table, summary_


def find_rain_events(rain: pd.Series, threshold: float = EVENT_THRESHOLD_MM, window: int = EVENT_WINDOW_H,
                     min_separation: int = EVENT_MIN_SEPARATION_H) -> pd.DataFrame:
    """t0 = first hour whose trailing ``window``-h rain sum reaches ``threshold``; later crossings within
    ``min_separation`` h of the previous t0 are merged into it (declustering)."""
    rain = rain.asfreq("h").fillna(0.0)
    total = rain.rolling(window, min_periods=window).sum()
    events, last = [], None
    for t in total.index[total >= threshold]:
        if last is not None and (t - last) < pd.Timedelta(hours=min_separation):
            continue
        last = t
        after = float(rain.loc[t + pd.Timedelta(hours=1): t + pd.Timedelta(hours=RESPONSE_WINDOWS_H[-1][1])].sum())
        events.append({"t0": t, "rain_6h_mm": float(total[t]), "rain_72h_after_mm": after,
                       "rain_max_1h_mm": float(rain.loc[t - pd.Timedelta(hours=window - 1): t].max()),
                       "clean": after < CLEAN_FOLLOW_ON_MM})
    return pd.DataFrame(events, columns=["t0", "rain_6h_mm", "rain_72h_after_mm", "rain_max_1h_mm", "clean"])


def _window_deltas(resid: pd.Series, t0: pd.Timestamp) -> dict | None:
    def window_mean(a: int, b: int):
        part = resid.loc[t0 + pd.Timedelta(hours=a): t0 + pd.Timedelta(hours=b)]
        need = (b - a + 1) * MIN_WINDOW_COVERAGE
        return part.mean() if part.notna().sum() >= need else np.nan

    base = window_mean(*BASELINE_H)
    if not np.isfinite(base):
        return None
    return {f"w{a:02d}_{b:02d}": window_mean(a, b) - base for a, b in RESPONSE_WINDOWS_H}


def _is_dry(rain: pd.Series, t: pd.Timestamp) -> bool:
    part = rain.loc[t + pd.Timedelta(hours=BASELINE_H[0]): t + pd.Timedelta(hours=RESPONSE_WINDOWS_H[-1][1])]
    expected = RESPONSE_WINDOWS_H[-1][1] - BASELINE_H[0] + 1
    if not (len(part.dropna()) == expected and part.sum() < DRY_MAX_TOTAL_MM and part.max() <= DRY_MAX_HOURLY_MM):
        return False
    before = rain.loc[t + pd.Timedelta(hours=DRY_ANTECEDENT_H[0]): t + pd.Timedelta(hours=DRY_ANTECEDENT_H[1])]
    return len(before.dropna()) == DRY_ANTECEDENT_H[1] - DRY_ANTECEDENT_H[0] + 1 and before.sum() < DRY_ANTECEDENT_MAX_MM


def event_responses(resid: pd.Series, rain: pd.Series, events: pd.DataFrame) -> pd.DataFrame:
    """Per event: response (window mean - pre-rain baseline) minus the mean response at same-hour dry
    origins within +-15 d (widened to +-30 d if fewer than 3)."""
    rain = rain.asfreq("h")
    rows = []
    for event in events.itertuples(index=False):
        deltas = _window_deltas(resid, event.t0)
        if deltas is None:
            continue
        controls = []
        for days in DRY_SEARCH_DAYS:
            candidates = [event.t0 + pd.Timedelta(days=d) for d in range(-days, days + 1) if d != 0]
            controls = [c for c in candidates if _is_dry(rain, c)]
            controls = [d for d in (_window_deltas(resid, c) for c in controls) if d is not None]
            if len(controls) >= 3:
                break
        if len(controls) < 3:
            continue
        dry = pd.DataFrame(controls).mean()
        row = {"t0": event.t0, "rain_6h_mm": event.rain_6h_mm, "rain_72h_after_mm": event.rain_72h_after_mm,
               "clean": bool(event.clean), "n_dry_controls": len(controls)}
        for key, value in deltas.items():
            row[f"{key}_event"] = value
            row[f"{key}_dry"] = float(dry[key])
            row[f"{key}_contrast"] = value - float(dry[key]) if np.isfinite(value) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def summarise_events(param: str, responses: pd.DataFrame, n_boot: int, seed: int = 11) -> list[dict]:
    rng = np.random.default_rng(seed)
    out = []
    for a, b in RESPONSE_WINDOWS_H:
        col = f"w{a:02d}_{b:02d}_contrast"
        values = responses[col].dropna().to_numpy() if col in responses else np.array([])
        row = {"window": f"{a}-{b}h", "n_events": int(len(values))}
        if len(values) >= 3:
            means = np.array([rng.choice(values, len(values)).mean() for _ in range(n_boot)])
            lo, hi = np.percentile(means, [2.5, 97.5])
            row.update({"mean_contrast": float(values.mean()), "ci_lo": float(lo), "ci_hi": float(hi),
                        "ci_excludes_0": bool(lo > 0 or hi < 0), "share_positive": float((values > 0).mean()),
                        "mean_event": float(responses[f"w{a:02d}_{b:02d}_event"].dropna().mean()),
                        "mean_dry": float(responses[f"w{a:02d}_{b:02d}_dry"].dropna().mean())})
            if param in LOG_PARAMS:
                row.update({"pct_change": 100 * (np.exp(row["mean_contrast"]) - 1),
                            "pct_ci_lo": 100 * (np.exp(lo) - 1), "pct_ci_hi": 100 * (np.exp(hi) - 1)})
        out.append(row)
    return out


def verdict(dlm: dict, event_rows: list[dict], n_events: int) -> tuple[str, str]:
    """Rule v1 - pre-registered (written before the first run). Applied to the clean-event set:

    detectable_effect     : DLM permutation p < 0.05 AND >= 1 event window whose 95% CI excludes 0 with the
                            sign of the DLM peak coefficient.
    no_detectable_effect  : DLM p >= 0.05, >= 10 usable events, no event window CI excludes 0, and every event
                            CI bound lies within +-1 residual SD (effects larger than that are ruled out).
    insufficient_evidence : anything else (few events, wide CIs, or DLM and event check disagree).
    """
    if dlm.get("status") != "ok" or n_events < 5:
        return "insufficient_evidence", f"usable events {n_events} < 5 or DLM not estimable"
    sign = np.sign(dlm["peak_beta_per_mm"])
    sig = [r for r in event_rows if r.get("ci_excludes_0")]
    agree = [r for r in sig if np.sign(r["mean_contrast"]) == sign]
    if dlm["perm_p"] < 0.05 and agree:
        return "detectable_effect", f"DLM p={dlm['perm_p']:.3f}; event windows {[r['window'] for r in agree]} agree in sign"
    bound = max((max(abs(r["ci_lo"]), abs(r["ci_hi"])) for r in event_rows if "ci_lo" in r), default=np.inf)
    if dlm["perm_p"] >= 0.05 and n_events >= 10 and not sig and bound <= dlm["resid_sd"]:
        return "no_detectable_effect", f"DLM p={dlm['perm_p']:.3f}; max |event CI bound| {bound:.3g} <= resid SD {dlm['resid_sd']:.3g}"
    return "insufficient_evidence", (f"DLM p={dlm['perm_p']:.3f}; significant event windows {[r['window'] for r in sig]}; "
                                     f"max |event CI bound| {bound:.3g} vs resid SD {dlm['resid_sd']:.3g}")


def verdict_v2(dlm: dict, ccf: dict) -> tuple[str, str]:
    """Rule v2 - REVISED after a 100-boot / 50-perm debug pass, because the Temperature positive control
    (DLM p at the permutation floor, CCF max-|r| p = 0.005) failed the event arm of v1: monsoon storms
    overlap, so few clean events exist and the event arm cannot reach significance. v2 uses the two
    selection-corrected global tests; events are a sign/magnitude check only (reported, not gating).

    detectable_effect     : DLM permutation p < 0.05 AND CCF max-|r| permutation p < 0.05 AND the DLM peak
                            coefficient and the CCF peak r have the same sign.
    no_detectable_effect  : both p >= 0.05 AND every DLM bin's 95% CI for 10 mm of rain lies within +-1
                            residual SD (larger effects ruled out).
    insufficient_evidence : anything else.
    """
    if dlm.get("status") != "ok":
        return "insufficient_evidence", "DLM not estimable"
    p_dlm, p_ccf = dlm["perm_p"], ccf["max_abs_p"]
    same_sign = np.sign(dlm["peak_beta_per_mm"]) == np.sign(ccf["peak_r"])
    if p_dlm < 0.05 and p_ccf < 0.05 and same_sign:
        return "detectable_effect", f"DLM p={p_dlm:.3f}, CCF max|r| p={p_ccf:.3f}, same sign"
    bound = max(10 * max(abs(c["ci_lo"]), abs(c["ci_hi"])) for c in dlm["coefficients"])
    if p_dlm >= 0.05 and p_ccf >= 0.05 and bound <= dlm["resid_sd"]:
        return "no_detectable_effect", f"DLM p={p_dlm:.3f}, CCF p={p_ccf:.3f}; max |10-mm CI bound| {bound:.3g} <= resid SD {dlm['resid_sd']:.3g}"
    return "insufficient_evidence", (f"DLM p={p_dlm:.3f}, CCF p={p_ccf:.3f}, same_sign={bool(same_sign)}; "
                                     f"max |10-mm CI bound| {bound:.3g} vs resid SD {dlm['resid_sd']:.3g}")


# ---------------------------------------------------------------- orchestration
def _residual(param: str, hourly: pd.DataFrame, detrend_h: int) -> pd.Series:
    y = transform(param, hourly[param])
    return detrend(y, segments_for(param, y.index), detrend_h)


def _nuisance(index: pd.DatetimeIndex, sea: pd.Series | None, tidal: bool) -> pd.DataFrame:
    design = harmonic_design(index, tidal=tidal)
    if tidal and sea is not None:
        design = design.join(sea_level_design(index, sea))
    return design


def _nuisance_residual(y: pd.Series, nuisance: pd.DataFrame) -> pd.Series:
    frame = pd.concat([y.rename("y"), nuisance], axis=1).dropna()
    x = np.column_stack([np.ones(len(frame)), frame.drop(columns="y").to_numpy()])
    beta, _ = _ols(frame["y"].to_numpy(), x)
    return pd.Series(frame["y"].to_numpy() - x @ beta, index=frame.index).reindex(y.index)


def analyse_variant(name: str, hourly: pd.DataFrame, rain: pd.Series, sea: pd.Series | None, *, params=LAG_PARAMS,
                    detrend_h: int = 168, tidal: bool = True, wind: pd.Series | None = None,
                    regime: str | None = None, threshold: float = EVENT_THRESHOLD_MM, rain_transform: str | None = None,
                    n_boot: int, n_perm: int, end: pd.Timestamp | None = None) -> dict:
    rain_end = rain.dropna().index.max()
    limit = min(rain_end, end) if end is not None else rain_end
    # Regression/CCF input; events are always defined on rain in mm.
    model_rain = np.log1p(rain) if rain_transform == "log1p" else rain
    results = {}
    for param in params:
        y = _residual(param, hourly, detrend_h)
        y = y[y.index <= limit]
        if regime and param in BREAK_PARAMS:
            y = y[y.index < BREAK_AT] if regime == "A" else y[y.index >= BREAK_AT]
        nuisance = _nuisance(y.index, sea, tidal)
        extra = None
        if wind is not None:
            extra = rain_lag_bins(wind, y.index).rename(columns=lambda c: c.replace("rain", "wind"))
            y = y[y.index <= wind.dropna().index.max()]
            nuisance, extra = nuisance.loc[y.index], extra.loc[y.index]
        dlm = distributed_lag(y, nuisance, model_rain, n_boot=n_boot, n_perm=n_perm, extra=extra)
        resid = _nuisance_residual(y, nuisance)
        ccf_table, ccf = cross_correlation(resid, model_rain, n_boot=max(n_boot // 2, 200), n_perm=n_perm)
        events = find_rain_events(rain.loc[: limit], threshold=threshold)
        events = events[(events.t0 >= y.dropna().index.min()) & (events.t0 <= y.dropna().index.max())]
        responses = event_responses(resid, rain, events)
        clean = responses[responses["clean"]] if len(responses) else responses
        event_rows = ([{"event_set": "clean", **r} for r in summarise_events(param, clean, n_boot=max(n_boot, 1000))]
                      + [{"event_set": "all", **r} for r in summarise_events(param, responses, n_boot=max(n_boot, 1000))])
        n_clean = int(len(clean))
        label, reason = verdict(dlm, [r for r in event_rows if r["event_set"] == "clean"], n_clean)
        label2, reason2 = verdict_v2(dlm, ccf)
        results[param] = {"variant": name, "param": param, "dlm": dlm, "ccf": ccf, "ccf_table": ccf_table,
                          "events": event_rows, "n_rain_events_in_period": int(len(events)),
                          "n_clean_events_in_period": int(events["clean"].sum()) if len(events) else 0,
                          "n_events_usable": int(len(responses)), "n_clean_events_usable": n_clean,
                          "verdict_v1": label, "verdict_v1_reason": reason, "verdict_v2": label2,
                          "verdict_v2_reason": reason2, "responses": responses, "resid": resid}
    return results


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_lag_response(args) -> int:
    import subprocess

    from core import paths
    from core.config import weather_location_for_station
    from experiments import hazard_data as hd

    out = paths.EXPERIMENT_OUTPUT_DIR / args.run_name
    if out.exists():
        print(f"exists, not overwritten: {out}")
        return 1
    sensor_csv = args.sensor_csv or paths.EXPERIMENT_OUTPUT_DIR / "sensor-history-20261024" / f"{STATION}.csv"
    era5_file = args.precip or hd.latest_precip("era5")
    best_file = args.precip_best_match or hd.latest_precip("best_match")
    wind_file = hd.latest_era5("era5")
    sea_files = [paths.EXPERIMENT_OUTPUT_DIR / EXTERNAL_CONTEXT_RUN / "sea_level_openmeteo_marine.csv"]
    out.mkdir(parents=True)
    (out / "inputs").mkdir()
    loc = weather_location_for_station(STATION)
    if args.fetch_sea_level:
        target = out / "inputs" / f"sea_level_openmeteo_marine_{args.sea_level_start.replace('-', '')}_{args.sea_level_end.replace('-', '')}.csv"
        fetch_sea_level(loc["latitude"], loc["longitude"], args.sea_level_start, args.sea_level_end, target)
        sea_files.append(target)

    hourly, excluded = load_hourly_sensor(sensor_csv)
    era5 = rain_on_sensor_grid(load_archive_hourly(era5_file, "precipitation"))
    best = rain_on_sensor_grid(load_archive_hourly(best_file, "precipitation"))
    wind = rain_on_sensor_grid(load_archive_hourly(wind_file, "wind_speed_10m"))
    sea = load_sea_level(sea_files)
    window = slice(hourly.index.min(), hourly.index.max())
    overlap = era5.loc[window].dropna().index.intersection(best.loc[window].dropna().index)
    rain_check = {"era5_vs_best_match_corr_hourly": float(np.corrcoef(era5[overlap], best[overlap])[0, 1]),
                  "era5_total_mm": float(era5.loc[overlap].sum()), "best_match_total_mm": float(best.loc[overlap].sum()),
                  "era5_end": str(era5.dropna().index.max()), "best_match_end": str(best.dropna().index.max()),
                  "sea_level_end": str(sea.dropna().index.max())}
    if len(sea_files) > 1:
        a, b = (load_sea_level([f]) for f in sea_files[:2])
        both = a.dropna().index.intersection(b.dropna().index)
        rain_check["sea_level_overlap_hours"] = int(len(both))
        rain_check["sea_level_overlap_max_abs_diff_m"] = float((a[both] - b[both]).abs().max()) if len(both) else None

    nb, npm = args.n_boot, args.n_perm
    sb, sp = max(nb // 3, 200), max(npm // 3, 200)
    variants = [
        ("primary_era5", dict(rain=era5, n_boot=nb, n_perm=npm)),
        ("precip_best_match_ifs", dict(rain=best, n_boot=sb, n_perm=sp)),
        ("no_tide_terms", dict(rain=era5, tidal=False, n_boot=sb, n_perm=sp)),
        ("detrend_72h", dict(rain=era5, detrend_h=72, n_boot=sb, n_perm=sp)),
        ("detrend_336h", dict(rain=era5, detrend_h=336, n_boot=sb, n_perm=sp)),
        ("plus_era5_wind_lags", dict(rain=era5, wind=wind, n_boot=sb, n_perm=sp)),
        ("event_threshold_5mm", dict(rain=era5, threshold=5.0, n_boot=sb, n_perm=sp)),
        ("regime_A_pre_0731", dict(rain=era5, regime="A", params=tuple(BREAK_PARAMS & set(LAG_PARAMS)), n_boot=sb, n_perm=sp)),
        ("regime_B_post_0731", dict(rain=era5, regime="B", params=tuple(BREAK_PARAMS & set(LAG_PARAMS)), n_boot=sb, n_perm=sp)),
        # post-hoc (added after the debug pass): log1p(mm) limits the leverage of a few storm hours
        ("posthoc_rain_log1p", dict(rain=era5, rain_transform="log1p", n_boot=sb, n_perm=sp)),
    ]
    if args.only_primary:
        variants = variants[:1]
    all_results = {}
    for name, kw in variants:
        rain = kw.pop("rain")
        print(f"[{name}]", flush=True)
        all_results[name] = analyse_variant(name, hourly, rain, sea, **kw)

    coef_rows, test_rows, event_rows, response_frames, ccf_frames = [], [], [], [], []
    count_keys = ("n_rain_events_in_period", "n_clean_events_in_period", "n_events_usable", "n_clean_events_usable",
                  "verdict_v1", "verdict_v1_reason", "verdict_v2", "verdict_v2_reason")
    for name, per_param in all_results.items():
        for param, res in per_param.items():
            dlm = res["dlm"]
            for c in dlm.get("coefficients", []):
                row = {"variant": name, "param": param, **c, "effect_10mm": 10 * c["beta_per_mm"],
                       "effect_10mm_ci_lo": 10 * c["ci_lo"], "effect_10mm_ci_hi": 10 * c["ci_hi"]}
                if param in LOG_PARAMS:
                    row.update({"pct_10mm": 100 * (np.exp(10 * c["beta_per_mm"]) - 1),
                                "pct_10mm_ci_lo": 100 * (np.exp(10 * c["ci_lo"]) - 1),
                                "pct_10mm_ci_hi": 100 * (np.exp(10 * c["ci_hi"]) - 1)})
                coef_rows.append(row)
            test_rows.append({"variant": name, "param": param, **{k: res[k] for k in count_keys},
                              **{k: v for k, v in dlm.items() if k != "coefficients"},
                              **{f"ccf_{k}": v for k, v in res["ccf"].items()}})
            for r in res["events"]:
                event_rows.append({"variant": name, "param": param, **r})
            if len(res["responses"]):
                response_frames.append(res["responses"].assign(variant=name, param=param))
            ccf_frames.append(res["ccf_table"].assign(variant=name, param=param))

    pd.DataFrame(coef_rows).to_csv(out / "dlm_coefficients.csv", index=False)
    pd.DataFrame(test_rows).to_csv(out / "dlm_tests.csv", index=False)
    pd.DataFrame(event_rows).to_csv(out / "event_summary.csv", index=False)
    if response_frames:
        pd.concat(response_frames).to_csv(out / "event_responses.csv", index=False)
    pd.concat(ccf_frames).to_csv(out / "ccf.csv", index=False)
    find_rain_events(era5.loc[hourly.index.min(): era5.dropna().index.max()]).to_csv(out / "rain_events_era5.csv", index=False)
    excluded.to_csv(out / "excluded_days.csv", index=False)
    hourly.join(era5.rename("rain_era5_mm")).join(best.rename("rain_best_match_mm")).join(sea.rename("sea_level_m")).to_csv(out / "hourly_inputs.csv", index_label="hour_start_utc")

    primary = {param: {**{k: r[k] for k in count_keys},
                       **{k: v for k, v in r["dlm"].items() if k != "coefficients"}, "ccf": r["ccf"],
                       "events": r["events"]} for param, r in all_results["primary_era5"].items()}
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        commit = None
    manifest = {
        "run": args.run_name, "station": STATION, "script": "experiments/weather_lag_sensor_ablation.py lag-response",
        "git_commit": commit, "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "inputs": {str(p): _sha256(Path(p)) for p in [sensor_csv, era5_file, best_file, wind_file, *sea_files]},
        "labels": {"precip_primary": "ERA5 (models=era5, decisions #18)",
                   "precip_sensitivity": "best_match (ERA5 < 2017, ECMWF IFS 9 km from 2017; RL-31) - NOT ERA5",
                   "sea_level": "Open-Meteo Marine sea_level_height_msl (model tide + surge)"},
        "settings": {"params": LAG_PARAMS, "log_params": sorted(LOG_PARAMS), "log_eps": LOG_EPS, "break_at": str(BREAK_AT),
                     "lag_bins_h": LAG_BINS, "tidal_periods_h": TIDAL_PERIODS_H, "diurnal_periods_h": DIURNAL_PERIODS_H,
                     "event_threshold_mm_6h": EVENT_THRESHOLD_MM, "event_min_separation_h": EVENT_MIN_SEPARATION_H,
                     "baseline_h": BASELINE_H, "response_windows_h": RESPONSE_WINDOWS_H, "dry_total_mm": DRY_MAX_TOTAL_MM,
                     "dry_hourly_mm": DRY_MAX_HOURLY_MM, "dry_antecedent_h": DRY_ANTECEDENT_H,
                     "dry_antecedent_max_mm": DRY_ANTECEDENT_MAX_MM, "clean_follow_on_mm": CLEAN_FOLLOW_ON_MM,
                     "block_hours": BLOCK_HOURS, "n_boot": nb, "n_perm": npm,
                     "sensitivity_n_boot": sb, "sensitivity_n_perm": sp},
        "verdict_rules": {"v1": "pre-registered: DLM perm p<0.05 AND clean-event window CI excludes 0 (same sign)",
                          "v2": "revised after debug pass (positive control failed v1 event arm): DLM perm p<0.05 "
                                "AND CCF max|r| p<0.05, same sign"},
        "rain_check": rain_check, "hourly_valid": {p: int(hourly[p].notna().sum()) for p in LAG_PARAMS},
        "excluded_days": excluded.groupby("param").size().to_dict() if len(excluded) else {},
        "nh4_units": "raw sensor units (NH4_CONVERSION_CONFIRMED pending); effects reported as % change of raw NH4",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps({"primary_era5": primary,
                                                   "sensitivity": [{k: v for k, v in r.items() if k not in ("coefficients",)}
                                                                   for r in test_rows if r["variant"] != "primary_era5"]},
                                                  indent=2, default=str), encoding="utf-8")
    print(pd.DataFrame(test_rows)[["variant", "param", "verdict_v1", "verdict_v2", "perm_p", "ccf_max_abs_p", "peak_bin",
                                   "peak_beta_per_mm", "ccf_peak_lag_h", "n_clean_events_usable", "n_events_usable"]].to_string(index=False))
    print(f"wrote {out}")
    return 0


def lag_response_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="weather_lag_sensor_ablation.py lag-response")
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--sensor-csv", type=Path)
    parser.add_argument("--precip", type=Path, help="ERA5 (models=era5) hourly precip; default hazard_data.latest_precip('era5')")
    parser.add_argument("--precip-best-match", type=Path)
    parser.add_argument("--fetch-sea-level", action="store_true", help="write-once Marine sea level for the gap after external-context")
    parser.add_argument("--sea-level-start", default="2026-10-14")
    parser.add_argument("--sea-level-end", default="2026-10-24")
    parser.add_argument("--n-boot", type=int, default=1000)
    parser.add_argument("--n-perm", type=int, default=500)
    parser.add_argument("--only-primary", action="store_true")
    return run_lag_response(parser.parse_args(argv))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "lag-response":
        sys.exit(lag_response_main(sys.argv[2:]))
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
