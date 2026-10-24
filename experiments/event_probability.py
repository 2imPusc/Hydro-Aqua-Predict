"""H2.5 (the part doable without DO): probabilistic 24 h event forecasts at NB1 vs the cage sensor.

Research-only. Nothing here feeds alerts or the shadow runner (``used_by_alerts: False``).

EVENT DEFINITIONS (fixed before any model was fitted; committed with this script)
------------------------------------------------------------------------------------
Sensor series: station 06M26042804, ``sensor-history-20261024`` (1-min Temperature). QC: readings
outside ``core.quality.is_in_range`` dropped; a local day graded INVALID by ``check_series`` is
dropped. Readings are reduced to HOURLY MEDIANS (bin [h, h+1 h), local hours = UTC hours + 7);
a bin needs >= 30 valid readings, otherwise it is missing. Medians, not means, so isolated
1-min spikes (e.g. 20.5 / 34.5 C single readings) cannot create or erase an event.

E1 hot day:   issued at local 00:00 of day D. y = 1 if the mean of day D's 24 hourly medians is
              >= 31.0 C (needs >= 20 of 24 bins). 31 C = "watch" level of decisions #17 / RL-30.
E2 fast rise: issued every 6 h (local 00, 06, 12, 18). Window = the 24 bins starting at issue
              time t (t .. t+23 h). y = 1 if there are bins i < j in the window with
              j - i <= 6 h and T_j - T_i >= 1.5 C (needs >= 20 of 24 bins).
              Hourly medians at <= 6 h spacing = "a rise of >= 1.5 C completed within 6 h,
              starting and ending inside the next 24 h". Both ends must be in the window, so
              a rise that started before issue time does not count (it is already observed).
E3 fast drop: as E2 with T_j - T_i <= -1.5 C (cold surge / heavy rain signature).
Label end (time the label is fully known) = t + 24 h for every event.

Persistence-of-yesterday reference: the same event rule applied to the 24 bins before t
(E1: yesterday's daily mean >= 31). Binary 0/1; if yesterday has too few bins the training
base rate is used (flagged).

FEATURES known at issue time t
------------------------------
Sensor (bins ending <= t): last value (latest of t-3..t-1 h), mean / max / min over 24 h,
mean over 6 h, 6 h change (mean t-3..t-1 minus mean t-9..t-7), largest 6 h rise and drop in
the last 24 h; for 6-hourly issues also the diurnal phase (sin/cos of issue hour).
Weather: Open-Meteo Previous Runs, ``reconstructed_run`` (decisions #13), the same fetch and
availability rule as B5 (``experiments/reconstruct_external_context.py``: a lead-N value is
usable from end of run day + 12 h) and the same causal join (``forecast_external_context.
join_as_issued``: latest record retrieved <= t). Re-fetched to cover the sensor window (the
B5 file stops at 2026-10-15) with ``models=best_match`` written down (decisions #18) and
``shortwave_radiation`` added. Aggregated over the 24 valid hours t .. t+23 h: air temperature
mean / max / min, max minus sensor last value, min minus sensor last value, shortwave sum,
cloud mean, precipitation sum, wind mean, humidity mean (needs >= 20 of 24 hours).
ERA5 (archive ``models=era5``) is used only as a covariate check (``logit_era5_check``): the
same aggregates from reanalysis instead of forecast. It is NOT a forecast (it is not known at
issue time) and never enters a verdict.

MODELS: climatology (training base rate), persistence, logit_sensor (sensor features only),
logit_full (sensor + weather), logit_full_platt (PRIMARY: logit_full + Platt scaling fitted on
time-ordered inner out-of-fold predictions of the training set only), gbm_full (E2/E3 only;
E1 has ~100 training rows). Logistic: standardised features, L2, C = 1.

VALIDATION: lockbox = newest 14 local days (issues on/after its first local midnight); before
it, rolling-origin folds of 14 days after >= 42 days of training, expanding window. Purge: a
training row is used only if its label end <= test start; no fold label reaches the lockbox
(asserted, decisions #16).

METRICS: Brier, BSS vs climatology (training base rate) and vs persistence, ROC-AUC,
reliability bins; 95 % CIs by circular moving-block bootstrap over issue days (block 3 days,
primary; 1-day blocks also stored), 2000 draws.

VERDICT per event (primary model, lockbox): ``insufficient_evidence`` if the lockbox has < 5
events or < 5 non-events; ``skill`` if BSS vs climatology > 0 and its CI lower bound > 0;
otherwise ``no_skill``. Beating persistence is reported separately.

    python experiments/event_probability.py --stamp 20261024
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.config import weather_location_for_station  # noqa: E402
from core.quality import check_series, is_in_range  # noqa: E402
from experiments.forecast_external_context import join_as_issued, read_snapshots  # noqa: E402
from experiments.reconstruct_external_context import VARIABLES as B5_VARIABLES  # noqa: E402
from experiments.reconstruct_external_context import to_records  # noqa: E402

STATION = "06M26042804"
LOCAL_TZ = "Asia/Ho_Chi_Minh"
SENSOR_RUN = "sensor-history-20261024"
B5_SNAPSHOTS = "external-context-06M26042804-2026-05-28_2026-10-15/weather-snapshots-reconstructed.jsonl"

HOUR_MIN_READINGS = 30
WINDOW_HOURS = 24
WINDOW_MIN_BINS = 20
E1_THRESHOLD_C = 31.0
JUMP_C = 1.5
JUMP_MAX_LAG_H = 6
EVENTS = {
    "E1_hot_day": {"issue_hours": (0,), "kind": "hot"},
    "E2_rise": {"issue_hours": (0, 6, 12, 18), "kind": "rise"},
    "E3_drop": {"issue_hours": (0, 6, 12, 18), "kind": "drop"},
}
LOCKBOX_DAYS = 14
FOLD_DAYS = 14
MIN_TRAIN_DAYS = 42
MIN_LOCKBOX_EVENTS = 5
BOOT_DRAWS = 2000
BOOT_BLOCK_DAYS = 3
PRIMARY = "logit_full_platt"

WEATHER_VARIABLES = B5_VARIABLES + ("shortwave_radiation",)
ERA5_VARIABLES = ("temperature_2m", "relative_humidity_2m", "precipitation", "cloud_cover",
                  "wind_speed_10m", "shortwave_radiation")
SENSOR_FEATURES = ["s_last", "s_mean24", "s_max24", "s_min24", "s_mean6", "s_delta6", "s_rise24", "s_drop24"]
PHASE_FEATURES = ["hour_sin", "hour_cos"]
WEATHER_FEATURES = ["w_t2m_mean", "w_t2m_max", "w_t2m_min", "w_t2m_max_minus_water", "w_t2m_min_minus_water",
                    "w_sw_sum", "w_cloud_mean", "w_precip_sum", "w_wind_mean", "w_rh_mean"]


# ---------------------------------------------------------------- sensor + labels
def load_hourly(path: Path) -> pd.Series:
    """QC'd hourly medians of Temperature, indexed by UTC bin start on a complete hourly grid."""
    raw = pd.read_csv(path, usecols=["fetchedAt", "Temperature"])
    raw["t"] = pd.to_datetime(raw["fetchedAt"], utc=True, errors="coerce")
    raw = raw.dropna(subset=["t", "Temperature"])
    raw = raw[raw["Temperature"].map(lambda v: is_in_range("Temperature", v))]
    local_day = raw["t"].dt.tz_convert(LOCAL_TZ).dt.date
    graded = raw.groupby(local_day)["Temperature"].apply(lambda s: check_series("Temperature", s))
    raw = raw[local_day.map(graded).eq("VALID")]
    grouped = raw.set_index("t")["Temperature"].resample("1h")
    hourly = grouped.median().where(grouped.count() >= HOUR_MIN_READINGS)
    return hourly.asfreq("1h")


def max_jump(values: np.ndarray, max_lag: int = JUMP_MAX_LAG_H) -> tuple[float, float]:
    """(largest rise, largest drop as a positive number) over pairs i < j, j - i <= max_lag."""
    rise, drop = np.nan, np.nan
    for j in range(1, len(values)):
        if np.isnan(values[j]):
            continue
        prior = values[max(0, j - max_lag):j]
        prior = prior[~np.isnan(prior)]
        if prior.size == 0:
            continue
        rise = np.nanmax([rise, values[j] - prior.min()])
        drop = np.nanmax([drop, prior.max() - values[j]])
    return float(rise), float(drop)


def window_label(values: np.ndarray, kind: str) -> tuple[float, float]:
    """(label 0/1 or NaN, continuous value) for one 24-bin window."""
    if np.sum(~np.isnan(values)) < WINDOW_MIN_BINS:
        return np.nan, np.nan
    if kind == "hot":
        mean = float(np.nanmean(values))
        return float(mean >= E1_THRESHOLD_C), mean
    rise, drop = max_jump(values)
    value = rise if kind == "rise" else drop
    if np.isnan(value):
        return np.nan, np.nan
    return float(value >= JUMP_C), value


def _bins(hourly: pd.Series, start: pd.Timestamp, n: int) -> np.ndarray:
    return hourly.reindex(pd.date_range(start, periods=n, freq="1h")).to_numpy(dtype=float)


def sensor_features(hourly: pd.Series, t: pd.Timestamp) -> dict:
    past = _bins(hourly, t - pd.Timedelta(hours=24), 24)  # bins ending <= t
    recent = past[-3:][~np.isnan(past[-3:])]
    if recent.size == 0 or np.sum(~np.isnan(past)) < 12 or np.sum(~np.isnan(past[-6:])) < 3:
        return {}
    a, b = past[-3:], past[-9:-6]
    if np.all(np.isnan(a)) or np.all(np.isnan(b)):
        return {}
    rise, drop = max_jump(past)
    return {"s_last": float(recent[-1]), "s_mean24": float(np.nanmean(past)), "s_max24": float(np.nanmax(past)),
            "s_min24": float(np.nanmin(past)), "s_mean6": float(np.nanmean(past[-6:])),
            "s_delta6": float(np.nanmean(a) - np.nanmean(b)),
            "s_rise24": 0.0 if np.isnan(rise) else rise, "s_drop24": 0.0 if np.isnan(drop) else drop}


def build_issues(hourly: pd.Series, event: str) -> pd.DataFrame:
    """One row per issue time: label, persistence, sensor features."""
    spec = EVENTS[event]
    first = hourly.dropna().index.min().tz_convert(LOCAL_TZ).normalize() + pd.Timedelta(days=1)
    last = hourly.dropna().index.max()
    rows = []
    for day in pd.date_range(first, last.tz_convert(LOCAL_TZ).normalize(), freq="D"):
        for hour in spec["issue_hours"]:
            t = (day + pd.Timedelta(hours=hour)).tz_convert("UTC")
            y, value = window_label(_bins(hourly, t, WINDOW_HOURS), spec["kind"])
            y_prev, _ = window_label(_bins(hourly, t - pd.Timedelta(hours=WINDOW_HOURS), WINDOW_HOURS), spec["kind"])
            local = t.tz_convert(LOCAL_TZ)
            row = {"event": event, "issued_at": t, "issued_local": local.isoformat(), "issue_day": local.date().isoformat(),
                   "label_end": t + pd.Timedelta(hours=WINDOW_HOURS), "y": y, "value": value, "persist_raw": y_prev,
                   "hour_sin": np.sin(2 * np.pi * local.hour / 24), "hour_cos": np.cos(2 * np.pi * local.hour / 24)}
            row |= sensor_features(hourly, t)
            rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- weather
def fetch_reconstructed(start: str, end: str, out_path: Path, station: str = STATION) -> dict:
    """Open-Meteo Previous Runs (reconstructed_run), same schema/availability as B5, written once."""
    import requests
    location = weather_location_for_station(station)
    leads = (1, 2, 3)
    params = {"latitude": location["latitude"], "longitude": location["longitude"],
              "hourly": ",".join(f"{v}_previous_day{n}" for v in WEATHER_VARIABLES for n in leads),
              "start_date": start, "end_date": end, "timezone": "UTC", "models": "best_match"}
    response = requests.get("https://previous-runs-api.open-meteo.com/v1/forecast", params=params, timeout=300)
    response.raise_for_status()
    hourly = pd.DataFrame(response.json()["hourly"])
    records = [r for n in leads for r in to_records(hourly, station, location, n, variables=WEATHER_VARIABLES)]
    for record in records:
        record["model"] = "best_match"
    with out_path.open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"url": response.url, "model": "best_match", "records": len(records), "start": start, "end": end,
            "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest()}


def fetch_era5(start: str, end: str, out_path: Path, station: str = STATION) -> dict:
    import requests
    location = weather_location_for_station(station)
    params = {"latitude": location["latitude"], "longitude": location["longitude"], "hourly": ",".join(ERA5_VARIABLES),
              "start_date": start, "end_date": end, "timezone": "UTC", "models": "era5"}
    response = requests.get("https://archive-api.open-meteo.com/v1/archive", params=params, timeout=300)
    response.raise_for_status()
    frame = pd.DataFrame(response.json()["hourly"])
    frame.to_csv(out_path, index=False, mode="x")
    last = frame.dropna(subset=["temperature_2m"])["time"].max()
    return {"url": response.url, "model": "era5", "rows": len(frame), "last_non_null": last,
            "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest()}


def b5_overlap_check(new: pd.DataFrame, old_path: Path) -> dict:
    """Do the re-fetched values equal the B5 file on the overlapping (valid_at, lead) pairs?"""
    old = read_snapshots(old_path)
    if old.empty:
        return {"status": "b5_file_missing"}
    def flat(frame: pd.DataFrame) -> pd.DataFrame:
        f = pd.json_normalize(frame["features"]).set_index(pd.MultiIndex.from_arrays([frame["valid_at"], frame["lead_days"]]))
        return f[list(B5_VARIABLES)]
    a, b = flat(new), flat(old)
    common = a.index.intersection(b.index)
    diff = (a.loc[common] - b.loc[common]).abs()
    both = a.loc[common].notna() & b.loc[common].notna()
    equal = ((diff <= 0.051) & both).sum().sum() / max(int(both.sum().sum()), 1)
    return {"overlap_pairs": int(len(common)), "fraction_equal_within_0.05": round(float(equal), 4),
            "max_abs_diff": {k: float(diff[k].max()) for k in diff}}


def _aggregate(hours: pd.DataFrame, s_last: float) -> dict:
    """Weather aggregates over one 24 h window (columns use Open-Meteo variable names)."""
    if hours["temperature_2m"].notna().sum() < WINDOW_MIN_BINS:
        return {}
    t2m = hours["temperature_2m"]
    return {"w_t2m_mean": t2m.mean(), "w_t2m_max": t2m.max(), "w_t2m_min": t2m.min(),
            "w_t2m_max_minus_water": t2m.max() - s_last, "w_t2m_min_minus_water": t2m.min() - s_last,
            "w_sw_sum": hours["shortwave_radiation"].sum(min_count=WINDOW_MIN_BINS) / 1000.0,
            "w_cloud_mean": hours["cloud_cover"].mean(), "w_precip_sum": hours["precipitation"].sum(min_count=WINDOW_MIN_BINS),
            "w_wind_mean": hours["wind_speed_10m"].mean(), "w_rh_mean": hours["relative_humidity_2m"].mean()}


def weather_features(issues: pd.DataFrame, snapshots: pd.DataFrame, station: str = STATION) -> pd.DataFrame:
    """As-issued weather aggregates via the B5 causal join (latest record retrieved <= issue)."""
    location = weather_location_for_station(station)
    pairs = pd.DataFrame([{"issued_at": t, "valid_at": t + pd.Timedelta(hours=h)}
                          for t in issues["issued_at"].unique() for h in range(WINDOW_HOURS)])
    pairs["station"] = station
    pairs["location_id"] = location.get("source", "unknown")
    joined = join_as_issued(pairs, snapshots, prefix="w", max_age_hours=48)
    joined = joined.rename(columns={f"w_{v}": v for v in WEATHER_VARIABLES})
    for v in WEATHER_VARIABLES:
        joined[v] = pd.to_numeric(joined[v], errors="coerce")
    s_last = issues.drop_duplicates("issued_at").set_index("issued_at")["s_last"]
    rows = {t: _aggregate(g, s_last.get(t, np.nan)) for t, g in joined.groupby("issued_at")}
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("issued_at").reset_index()


def lead_used(issued_at: pd.Timestamp, valid_at: pd.Timestamp) -> int | None:
    """Smallest lead (days) whose reconstructed availability is <= issue time."""
    for lead in (1, 2, 3):
        if valid_at.floor("D") - pd.Timedelta(days=lead) + pd.Timedelta(days=1, hours=12) <= issued_at:
            return lead
    return None


def era5_features(issues: pd.DataFrame, era5: pd.DataFrame) -> pd.DataFrame:
    era5 = era5.copy()
    era5["valid_at"] = pd.to_datetime(era5["time"], utc=True)
    era5 = era5.set_index("valid_at")
    rows = {}
    for t, s_last in issues.drop_duplicates("issued_at").set_index("issued_at")["s_last"].items():
        hours = era5.reindex(pd.date_range(t, periods=WINDOW_HOURS, freq="1h"))
        rows[t] = _aggregate(hours, s_last)
    frame = pd.DataFrame.from_dict(rows, orient="index").rename_axis("issued_at").reset_index()
    return frame.rename(columns={c: c.replace("w_", "e_", 1) for c in frame if c.startswith("w_")})


# ---------------------------------------------------------------- splits
def lockbox_start(issues: pd.DataFrame) -> pd.Timestamp:
    last_day = pd.Timestamp(issues["issue_day"].max(), tz=LOCAL_TZ)
    return (last_day - pd.Timedelta(days=LOCKBOX_DAYS - 1)).tz_convert("UTC")


def make_splits(issues: pd.DataFrame) -> list[dict]:
    """Rolling-origin folds then the lockbox; each split = dict(name, train idx, test idx, start)."""
    lock = lockbox_start(issues)
    first = pd.Timestamp(issues["issue_day"].min(), tz=LOCAL_TZ).tz_convert("UTC")
    splits, start, k = [], first + pd.Timedelta(days=MIN_TRAIN_DAYS), 1
    while start < lock:
        stop = min(start + pd.Timedelta(days=FOLD_DAYS), lock)
        test = issues.index[(issues["issued_at"] >= start) & (issues["issued_at"] < stop) & (issues["label_end"] <= lock)]
        train = issues.index[issues["label_end"] <= start]
        if len(test) and len(train):
            splits.append({"name": f"cv{k}", "start": start, "train": train, "test": test})
            k += 1
        start = stop
    splits.append({"name": "lockbox", "start": lock, "train": issues.index[issues["label_end"] <= lock],
                   "test": issues.index[issues["issued_at"] >= lock]})
    for s in splits:  # decisions #16: purge + no fold label in the lockbox
        assert issues.loc[s["train"], "label_end"].max() <= s["start"], s["name"]
        if s["name"] != "lockbox":
            assert issues.loc[s["test"], "label_end"].max() <= lock, s["name"]
    return splits


# ---------------------------------------------------------------- models
def _logit():
    return make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=5000))


def _gbm():
    return HistGradientBoostingClassifier(max_depth=2, max_iter=150, learning_rate=0.05, min_samples_leaf=20,
                                          l2_regularization=1.0, random_state=42)


def fit_predict(factory, train: pd.DataFrame, test: pd.DataFrame, features: list[str]) -> np.ndarray:
    y = train["y"].to_numpy(int)
    if y.min() == y.max():  # one class only: the honest forecast is the base rate
        return np.full(len(test), float(y.mean()))
    model = factory().fit(train[features].to_numpy(float), y)
    return model.predict_proba(test[features].to_numpy(float))[:, 1]


def inner_oof(factory, train: pd.DataFrame, features: list[str], n_inner: int = 4) -> tuple[np.ndarray, np.ndarray]:
    """Time-ordered out-of-fold predictions inside the training set (purged like the outer folds)."""
    train = train.sort_values("issued_at")
    edges = pd.to_datetime(np.quantile(train["issued_at"].astype("int64"), np.linspace(0, 1, n_inner + 2)), utc=True)
    p, y = [], []
    for lo, hi in zip(edges[1:-1], edges[2:]):
        inner_test = train[(train["issued_at"] >= lo) & (train["issued_at"] < hi)]
        inner_train = train[train["label_end"] <= lo]
        if len(inner_train) < 20 or len(inner_test) == 0 or inner_train["y"].nunique() < 2:
            continue
        p.append(fit_predict(factory, inner_train, inner_test, features))
        y.append(inner_test["y"].to_numpy(int))
    return (np.concatenate(p), np.concatenate(y)) if p else (np.array([]), np.array([]))


def _logit_of(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p)).reshape(-1, 1)


def platt_predict(factory, train: pd.DataFrame, test: pd.DataFrame, features: list[str]) -> tuple[np.ndarray, str]:
    raw = fit_predict(factory, train, test, features)
    p_oof, y_oof = inner_oof(factory, train, features)
    if len(y_oof) < 30 or y_oof.sum() < 3 or (len(y_oof) - y_oof.sum()) < 3:
        return raw, "none_insufficient_inner_oof"
    platt = LogisticRegression(C=1e4, max_iter=1000).fit(_logit_of(p_oof), y_oof)
    return platt.predict_proba(_logit_of(raw))[:, 1], f"platt_inner_oof_n{len(y_oof)}"


# ---------------------------------------------------------------- metrics
def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def score(frame: pd.DataFrame) -> dict:
    y, p = frame["y"].to_numpy(float), frame["p"].to_numpy(float)
    bs, bs_c, bs_p = brier(p, y), brier(frame["p_clim"], y), brier(frame["p_persist"], y)
    auc = float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else np.nan
    return {"brier": bs, "brier_clim": bs_c, "brier_persist": bs_p,
            "bss_clim": 1 - bs / bs_c if bs_c > 0 else np.nan,
            "bss_persist": 1 - bs / bs_p if bs_p > 0 else np.nan, "auc": auc}


def block_bootstrap(frame: pd.DataFrame, block_days: int, draws: int = BOOT_DRAWS, seed: int = 42) -> dict:
    """Circular moving-block bootstrap over issue days; returns 2.5/97.5 % for each score()."""
    days = sorted(frame["issue_day"].unique())
    if len(days) < 3:
        return {}
    by_day = [frame.index[frame["issue_day"].eq(d)].to_numpy() for d in days]
    rng = np.random.default_rng(seed)
    n, n_blocks = len(days), int(np.ceil(len(days) / block_days))
    stats = []
    for _ in range(draws):
        starts = rng.integers(0, n, n_blocks)
        picked = np.concatenate([(s + np.arange(block_days)) % n for s in starts])[:n]
        sample = frame.loc[np.concatenate([by_day[i] for i in picked])]
        stats.append(score(sample))
    table = pd.DataFrame(stats)
    out = {}
    for col in table:
        values = table[col].replace([np.inf, -np.inf], np.nan).dropna()
        out[f"{col}_ci_lo"] = float(values.quantile(0.025)) if len(values) else np.nan
        out[f"{col}_ci_hi"] = float(values.quantile(0.975)) if len(values) else np.nan
    return out


def reliability(frame: pd.DataFrame, bins: int = 10) -> pd.DataFrame:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(frame["p"], edges[1:-1]), 0, bins - 1)
    rows = []
    for b in range(bins):
        sel = frame[idx == b]
        rows.append({"bin": b, "p_lo": edges[b], "p_hi": edges[b + 1], "n": len(sel),
                     "mean_p": float(sel["p"].mean()) if len(sel) else np.nan,
                     "obs_freq": float(sel["y"].mean()) if len(sel) else np.nan})
    return pd.DataFrame(rows)


def verdict(row: pd.Series) -> str:
    if row["n_events"] < MIN_LOCKBOX_EVENTS or (row["n"] - row["n_events"]) < MIN_LOCKBOX_EVENTS:
        return "insufficient_evidence"
    if row["bss_clim"] > 0 and row["bss_clim_ci_lo"] > 0:
        return "skill"
    return "no_skill"


# ---------------------------------------------------------------- run
def models_for(event: str) -> dict:
    sensor = SENSOR_FEATURES + ([] if event == "E1_hot_day" else PHASE_FEATURES)
    full = sensor + WEATHER_FEATURES
    models = {"logit_sensor": (_logit, sensor, False), "logit_full": (_logit, full, False),
              "logit_full_platt": (_logit, full, True)}
    if event != "E1_hot_day":
        models["gbm_full"] = (_gbm, full, False)
    return models


def run_event(event: str, issues: pd.DataFrame, era5_cols: list[str]) -> tuple[pd.DataFrame, list[dict]]:
    models = models_for(event)
    needed = sorted({f for _, feats, _ in models.values() for f in feats})
    usable = issues.dropna(subset=["y", *needed]).reset_index(drop=True)
    splits = make_splits(usable)
    era5_feats = models["logit_sensor"][1] + era5_cols
    preds, split_log = [], []
    for s in splits:
        train, test = usable.loc[s["train"]], usable.loc[s["test"]]
        base = float(train["y"].mean())
        persist = test["persist_raw"].fillna(base).to_numpy(float)
        common = {"event": event, "split": s["name"], "issued_at": test["issued_at"].to_numpy(),
                  "issue_day": test["issue_day"].to_numpy(), "y": test["y"].to_numpy(float),
                  "p_clim": np.full(len(test), base), "p_persist": persist,
                  "persist_fallback": test["persist_raw"].isna().to_numpy()}
        outputs = {"climatology": (np.full(len(test), base), "none"), "persistence": (persist, "none")}
        for name, (factory, feats, platt) in models.items():
            outputs[name] = platt_predict(factory, train, test, feats) if platt else (fit_predict(factory, train, test, feats), "none")
        if s["name"] != "lockbox":
            ok_tr, ok_te = train.dropna(subset=era5_cols), test[test[era5_cols].notna().all(axis=1)]
            if len(ok_te) and len(ok_tr):
                p = np.full(len(test), np.nan)
                p[np.flatnonzero(test[era5_cols].notna().all(axis=1).to_numpy())] = fit_predict(_logit, ok_tr, ok_te, era5_feats)
                outputs["logit_era5_check"] = (p, "none")
        for name, (p, calibration) in outputs.items():
            preds.append(pd.DataFrame(common | {"model": name, "p": p, "calibration": calibration}))
        split_log.append({"event": event, "split": s["name"], "test_start": s["start"].isoformat(),
                          "train_n": len(train), "train_events": int(train["y"].sum()), "base_rate_train": base,
                          "train_last_label_end": train["label_end"].max().isoformat(),
                          "test_n": len(test), "test_events": int(test["y"].sum()),
                          "test_first_issue": test["issued_at"].min().isoformat() if len(test) else None,
                          "test_last_issue": test["issued_at"].max().isoformat() if len(test) else None,
                          "test_last_label_end": test["label_end"].max().isoformat() if len(test) else None})
    return pd.concat(preds, ignore_index=True), split_log


def evaluate(preds: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    preds = preds.copy()
    preds["scope"] = np.where(preds["split"].eq("lockbox"), "lockbox", "cv_pooled")
    rows, rel = [], []
    groups = list(preds.groupby(["event", "scope", "model"]))
    groups += [((e, f"{sp}", m), g) for (e, sp, m), g in preds[preds["scope"].eq("cv_pooled")].groupby(["event", "split", "model"])]
    for (event, scope, model), g in groups:
        g = g.dropna(subset=["p"]).reset_index(drop=True)
        if g.empty:
            continue
        row = {"event": event, "scope": scope, "model": model, "n": len(g), "n_events": int(g["y"].sum()),
               "n_days": g["issue_day"].nunique(), "event_rate": float(g["y"].mean()),
               "mean_p_clim": float(g["p_clim"].mean()), "persist_fallback_n": int(g["persist_fallback"].sum())}
        row |= score(g)
        if scope in ("cv_pooled", "lockbox"):
            row |= block_bootstrap(g, BOOT_BLOCK_DAYS)
            row |= {f"{k}_block1d": v for k, v in block_bootstrap(g, 1).items()}
            rel.append(reliability(g).assign(event=event, scope=scope, model=model))
        rows.append(row)
    metrics = pd.DataFrame(rows)
    # same-rows comparison for the ERA5 covariate check
    era = preds[preds["model"].eq("logit_era5_check") & preds["p"].notna()]
    for event, g in era.groupby("event"):
        keys = g[["split", "issued_at"]]
        for model in ("logit_full", "logit_sensor", "logit_era5_check"):
            sub = preds[preds["event"].eq(event) & preds["model"].eq(model)].merge(keys, on=["split", "issued_at"]).reset_index(drop=True)
            r = {"event": event, "scope": "cv_pooled_era5_rows", "model": model, "n": len(sub),
                 "n_events": int(sub["y"].sum()), "n_days": sub["issue_day"].nunique(), "event_rate": float(sub["y"].mean())}
            r |= score(sub) | block_bootstrap(sub, BOOT_BLOCK_DAYS)
            rows.append(r)
    return pd.DataFrame(rows), pd.concat(rel, ignore_index=True)


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parent, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stamp", required=True, help="run dir suffix: event-probability-<stamp>")
    parser.add_argument("--weather-jsonl", type=Path, help="reuse an already fetched reconstructed JSONL (no network)")
    parser.add_argument("--era5-csv", type=Path, help="reuse an already fetched ERA5 CSV (no network)")
    args = parser.parse_args(argv)
    out = paths.EXPERIMENT_OUTPUT_DIR / f"event-probability-{args.stamp}"
    if out.exists():
        print(f"exists, not overwritten: {out}")
        return 1
    out.mkdir(parents=True)
    sensor_path = paths.EXPERIMENT_OUTPUT_DIR / SENSOR_RUN / f"{STATION}.csv"
    hourly = load_hourly(sensor_path)
    start = (hourly.dropna().index.min() - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    end = (hourly.dropna().index.max() + pd.Timedelta(days=2)).strftime("%Y-%m-%d")

    weather_path = out / "weather-snapshots-reconstructed.jsonl"
    if args.weather_jsonl:
        weather_path.write_bytes(args.weather_jsonl.read_bytes())
        weather_info = {"reused_from": str(args.weather_jsonl), "sha256": hashlib.sha256(weather_path.read_bytes()).hexdigest()}
    else:
        weather_info = fetch_reconstructed(start, end, weather_path)
    era5_path = out / f"openmeteo_era5_nb1_{start}_{end}.csv"
    if args.era5_csv:
        era5_path.write_bytes(args.era5_csv.read_bytes())
        era5_info = {"reused_from": str(args.era5_csv), "model": "era5"}
    else:
        era5_info = fetch_era5(start, end, era5_path)
    snapshots = read_snapshots(weather_path)
    weather_info["b5_overlap_check"] = b5_overlap_check(snapshots, paths.EXPERIMENT_OUTPUT_DIR / B5_SNAPSHOTS)
    era5 = pd.read_csv(era5_path)

    all_preds, split_log, label_rows, lead_counts = [], [], [], {}
    for event in EVENTS:
        issues = build_issues(hourly, event)
        issues = issues.merge(weather_features(issues, snapshots), on="issued_at", how="left")
        issues = issues.merge(era5_features(issues, era5), on="issued_at", how="left")
        era5_cols = [c.replace("w_", "e_", 1) for c in WEATHER_FEATURES]
        leads = pd.Series([lead_used(t, t + pd.Timedelta(hours=h)) for t in issues["issued_at"] for h in range(WINDOW_HOURS)])
        lead_counts[event] = {str(k): int(v) for k, v in leads.value_counts(dropna=False).items()}
        preds, log = run_event(event, issues, era5_cols)
        all_preds.append(preds)
        split_log += log
        label_rows.append(issues)
    labels = pd.concat(label_rows, ignore_index=True)
    labels.to_csv(out / "issues_features_labels.csv", index=False)
    preds = pd.concat(all_preds, ignore_index=True)
    preds.to_csv(out / "predictions.csv", index=False)
    pd.DataFrame(split_log).to_csv(out / "splits.csv", index=False)
    metrics, rel = evaluate(preds)
    metrics.to_csv(out / "metrics.csv", index=False)
    rel.to_csv(out / "reliability.csv", index=False)

    verdicts = {}
    for event in EVENTS:
        lock = metrics[(metrics["event"] == event) & (metrics["scope"] == "lockbox") & (metrics["model"] == PRIMARY)].iloc[0]
        cv = metrics[(metrics["event"] == event) & (metrics["scope"] == "cv_pooled") & (metrics["model"] == PRIMARY)].iloc[0]
        verdicts[event] = {"verdict": verdict(lock), "primary_model": PRIMARY,
                           "lockbox": {k: lock[k] for k in ("n", "n_events", "n_days", "brier", "bss_clim", "bss_clim_ci_lo",
                                                            "bss_clim_ci_hi", "bss_persist", "bss_persist_ci_lo", "bss_persist_ci_hi", "auc")},
                           "beats_persistence_lockbox": bool(lock["bss_persist_ci_lo"] > 0) if pd.notna(lock.get("bss_persist_ci_lo")) else None,
                           "cv_pooled_supporting": {"verdict_rule_applied": verdict(cv),
                                                    **{k: cv[k] for k in ("n", "n_events", "bss_clim", "bss_clim_ci_lo", "bss_clim_ci_hi",
                                                                          "bss_persist", "bss_persist_ci_lo", "bss_persist_ci_hi", "auc")}}}
    (out / "verdict.json").write_text(json.dumps(verdicts, indent=2, default=float), encoding="utf-8")
    manifest = {
        "schema": "event-probability-v1", "station": STATION, "git_commit": _git_commit(),
        "sensor_input": str(sensor_path), "sensor_sha256": hashlib.sha256(sensor_path.read_bytes()).hexdigest(),
        "hourly_bins": int(hourly.size), "hourly_valid": int(hourly.notna().sum()),
        "weather": weather_info | {"provenance_class": "reconstructed_run", "variables": WEATHER_VARIABLES,
                                   "availability_rule": "end_of_run_day_plus_12h", "join": "forecast_external_context.join_as_issued(max_age_hours=48)"},
        "weather_lead_days_used": lead_counts,
        "era5": era5_info | {"role": "covariate_check_only_not_a_forecast"},
        "definitions": {"hour_min_readings": HOUR_MIN_READINGS, "window_hours": WINDOW_HOURS, "window_min_bins": WINDOW_MIN_BINS,
                        "e1_threshold_c": E1_THRESHOLD_C, "jump_c": JUMP_C, "jump_max_lag_h": JUMP_MAX_LAG_H,
                        "events": {k: {"issue_hours_local": v["issue_hours"], "kind": v["kind"]} for k, v in EVENTS.items()}},
        "validation": {"lockbox_days": LOCKBOX_DAYS, "fold_days": FOLD_DAYS, "min_train_days": MIN_TRAIN_DAYS,
                       "purge": "train label_end <= test start; fold label_end <= lockbox start (asserted)",
                       "bootstrap": {"draws": BOOT_DRAWS, "block_days_primary": BOOT_BLOCK_DAYS, "also": "1-day blocks (*_block1d)"},
                       "min_lockbox_events": MIN_LOCKBOX_EVENTS, "primary_model": PRIMARY},
        "used_by_alerts": False, "notification_eligible": False, "runtime_changed": False,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(json.dumps(verdicts, indent=2, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
