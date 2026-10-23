"""Shadow-only 3/6/12-hour direct sensor forecasts (roadmap H1.5).

Runtime counterpart of ``experiments/forecast_sensor_v2.build_frame``: the
features of one forecast origin are rebuilt exactly as in training (parity is
tested against the research code), then ridge bundles trained by
``experiments/train_sensor_future_v2.py`` are applied.  Nothing here feeds
alerts, advisories or the dashboard risk; records go to a separate shadow
ledger (``core/forecast_evaluation.py``).

H1.6 (RL-18): manifest entries with ``status: withdrawn`` (the pH bundles) are
never issued, only logged as ``bundle_withdrawn`` skips.  Temperature
``*_nopH`` bundles (``variant: nopH``, ``role: parallel_shadow``) run next to
the with-pH bundles and need no pH input at all; with-pH records carry
``ph_input_status`` so the ledger can compare the two when the probe drifts.
"""
from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from core import forecast_evaluation as ledger
from core import paths
from core.config import weather_location_for_station
from core.forecast_context import CapturedLiveWeather, marine_tide
from core.forecast_intervals import aci_half_width, static_night_half_width
from core.quality import is_in_range, ph_in_band

MODEL_DIR = paths.MODELS_DIR / "sensor_future"
MANIFEST = MODEL_DIR / "sensor_future_long_manifest.json"
PROMOTED_STATION = "06M26042804"
EXTERNAL_FEATURE_SET = "B5_external_as_issued"
TIDE_FEATURE_SET = "B6_tide"
NOPH_SUFFIX = "_nopH"  # same suffix as experiments.forecast_sensor_v2 (tested)
WITHDRAWN = "withdrawn"
PH_PLAUSIBLE_SEAWATER = ledger.PH_PLAUSIBLE_SEAWATER
PI_ALPHAS = (("pi80", 0.2), ("pi90", 0.1))

TARGETS = ("Temperature", "pH", "NH4", "TSS")
LAGS_MINUTES = (1, 3, 5, 10, 15, 30, 60)
WINDOWS_MINUTES = (5, 15, 30, 60)
CROSS_LAGS_MINUTES = (1, 15)
TOLERANCE = pd.Timedelta(minutes=2)
CALENDAR = ("hour_sin", "hour_cos", "dow_sin", "dow_cos")
QUALITY = ("age_minutes", "gap_before_minutes", "quality_gap_flag")
TIDE_COLUMNS = ("tide_issue", "tide_valid", "tide_delta", "tide_slope_1h")
LOCAL_TZ = "Asia/Ho_Chi_Minh"


def clean_raw(raw: pd.DataFrame) -> pd.DataFrame:
    """Same cleaning as ``load_sensor_data``: out-of-range -> NaN, one row per timestamp."""
    cols = [c for c in TARGETS if c in raw]
    frame = raw[["fetchedAt", *cols]].copy()
    frame["fetchedAt"] = pd.to_datetime(frame["fetchedAt"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["fetchedAt"])
    for col in cols:
        values = pd.to_numeric(frame[col], errors="coerce")
        frame[col] = values.where(values.map(lambda value: is_in_range(col, value)))
    return frame.groupby("fetchedAt", as_index=False)[cols].median().sort_values("fetchedAt").reset_index(drop=True)


def base_feature_set(feature_set: str) -> str:
    return feature_set.removesuffix(NOPH_SUFFIX)


def is_nopH(feature_set: str) -> bool:
    return feature_set != base_feature_set(feature_set)


def b4_feature_names(target: str, available: tuple[str, ...] = TARGETS, exclude_ph: bool = False) -> list[str]:
    """Feature order of ``feature_subset(..., "B4_quality")`` (``"B4_quality_nopH"`` with ``exclude_ph``)."""
    if exclude_ph:
        if target == "pH":
            raise ValueError("nopH_variant_invalid_for_pH")
        return [name for name in b4_feature_names(target, available) if not name.startswith("pH_")]
    names = [f"{target}_lag_{minute}m" for minute in LAGS_MINUTES] + list(CALENDAR)
    for window in WINDOWS_MINUTES:
        names += [f"roll_{stat}_{window}m" for stat in ("mean", "median", "std", "min", "max")]
    names += ["delta_15m", "slope_60m"]
    others = [other for other in TARGETS if other != target and other in available]
    names += [f"{other}_lag_{minute}m" for other in others for minute in CROSS_LAGS_MINUTES]
    if {"Temperature", "NH4"}.issubset(available):
        names.append("temperature_x_nh4")
    return names + list(QUALITY)


def _asof(times: np.ndarray, values: np.ndarray, wanted: pd.Timestamp) -> float:
    """Backward as-of lookup with the research 2-minute tolerance."""
    position = np.searchsorted(times, wanted.to_datetime64(), side="right") - 1
    if position < 0:
        return math.nan
    if wanted.to_datetime64() - times[position] > TOLERANCE.to_timedelta64():
        return math.nan
    return float(values[position])


def _series_arrays(source: pd.DataFrame, column: str) -> tuple[np.ndarray, np.ndarray]:
    valid = source[["fetchedAt", column]].dropna()
    times = valid["fetchedAt"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")
    return times, valid[column].to_numpy(dtype=float)


def origin_features(source: pd.DataFrame, target: str, exclude_ph: bool = False) -> dict:
    """Features at the latest valid ``target`` observation (the forecast origin).

    ``source`` must come from :func:`clean_raw`.  Returns ``status="skip"`` with
    the missing feature names instead of ever filling a value.  With
    ``exclude_ph`` no pH-derived feature is required or returned (nopH bundles),
    so a missing or faulty pH probe cannot block the forecast.
    """
    if target not in source:
        return {"status": "skip", "reason": "target_column_missing"}
    times, values = _series_arrays(source, target)
    if len(times) < 2:
        return {"status": "skip", "reason": "insufficient_sensor_history"}
    issued_naive = pd.Timestamp(times[-1])
    issued_at = issued_naive.tz_localize("UTC")
    features: dict[str, float] = {}
    lags = {minute: _asof(times, values, issued_naive - pd.Timedelta(minutes=minute)) for minute in LAGS_MINUTES}
    for minute, value in lags.items():
        features[f"{target}_lag_{minute}m"] = value
    local = issued_at.tz_convert(LOCAL_TZ)
    hour = local.hour + local.minute / 60
    features.update({
        "hour_sin": float(np.sin(2 * np.pi * hour / 24)), "hour_cos": float(np.cos(2 * np.pi * hour / 24)),
        "dow_sin": float(np.sin(2 * np.pi * local.dayofweek / 7)), "dow_cos": float(np.cos(2 * np.pi * local.dayofweek / 7)),
    })
    for window in WINDOWS_MINUTES:
        window_values = pd.Series([lags[minute] for minute in LAGS_MINUTES if minute <= window], dtype=float)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN window -> NaN -> skip below
            features[f"roll_mean_{window}m"] = float(window_values.mean())
            features[f"roll_median_{window}m"] = float(window_values.median())
            features[f"roll_std_{window}m"] = float(window_values.std())
            features[f"roll_min_{window}m"] = float(window_values.min())
            features[f"roll_max_{window}m"] = float(window_values.max())
    features["delta_15m"] = lags[1] - lags[15]
    features["slope_60m"] = (lags[1] - lags[60]) / 59
    available = tuple(column for column in TARGETS if column in source)
    for other in TARGETS:
        if other == target or other not in source:
            continue
        other_times, other_values = _series_arrays(source, other)
        for minute in CROSS_LAGS_MINUTES:
            features[f"{other}_lag_{minute}m"] = _asof(other_times, other_values, issued_naive - pd.Timedelta(minutes=minute))
    if {"Temperature", "NH4"}.issubset(available):
        temp = features.get("Temperature_lag_1m") if target != "Temperature" else lags[1]
        nh4 = features.get("NH4_lag_1m") if target != "NH4" else lags[1]
        features["temperature_x_nh4"] = temp * nh4
    features["age_minutes"] = 0.0
    features["gap_before_minutes"] = float((times[-1] - times[-2]) / np.timedelta64(1, "m"))
    features["quality_gap_flag"] = 0.0
    names = b4_feature_names(target, available, exclude_ph=exclude_ph)
    missing = [name for name in names if not np.isfinite(features.get(name, math.nan))]
    current = float(values[-1])
    if missing:
        return {"status": "skip", "reason": "insufficient_sensor_history", "issued_at": issued_at, "missing_features": missing, "current": current}
    return {"status": "ok", "issued_at": issued_at, "features": {name: features[name] for name in names}, "current": current}


def tide_features_at(issued_at: pd.Timestamp, valid_at: pd.Timestamp, tide: pd.DataFrame) -> dict:
    """B6 features exactly as ``forecast_sensor_v2.tide_features`` (linear interpolation, no extrapolation)."""
    series = tide.dropna(subset=["sea_level_m"]).sort_values("valid_at")
    if series.empty:
        return {"status": "skip", "reason": "tide_series_empty"}
    x = series["valid_at"].astype("int64").to_numpy() / 1e9
    y = series["sea_level_m"].to_numpy(dtype=float)
    def at(moment: pd.Timestamp) -> float:
        s = pd.Timestamp(moment).value / 1e9
        if s < x.min() or s > x.max():
            return math.nan
        return float(np.interp(s, x, y))
    issue, valid, before = at(issued_at), at(valid_at), at(issued_at - pd.Timedelta(hours=1))
    values = {"tide_issue": issue, "tide_valid": valid, "tide_delta": valid - issue, "tide_slope_1h": issue - before}
    if not all(np.isfinite(v) for v in values.values()):
        return {"status": "skip", "reason": "tide_range_insufficient"}
    return {"status": "ok", "features": values}


_BUNDLE_CACHE: dict[tuple, list[dict]] = {}


MANIFEST_TAGS = ("status", "variant", "role", "withdrawn_reason", "withdrawn_at")
STUB_FIELDS = ("file", "model_version", "target", "horizon_minutes", "feature_set")


def _load_entry(directory: Path, entry: dict) -> dict:
    """One manifest entry -> bundle dict carrying the manifest tags (status/variant/role).

    Withdrawn entries are not unpickled: their stub only carries what the skip log needs.
    """
    tags = {key: entry[key] for key in MANIFEST_TAGS if key in entry}
    tags.setdefault("status", "active")
    if tags["status"] == WITHDRAWN:
        return {**{key: entry.get(key) for key in STUB_FIELDS}, **tags}
    bundle = dict(joblib.load(directory / entry["file"]))
    default_variant = "nopH" if is_nopH(bundle["feature_set"]) else ("pH_target" if bundle["target"] == "pH" else "with_pH")
    tags.setdefault("variant", default_variant)
    return {**bundle, **tags}


def load_bundles(manifest_path: Path = MANIFEST) -> list[dict]:
    """Bundles listed in the training manifest (cached on manifest mtime)."""
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        return []
    key = (str(manifest_path), manifest_path.stat().st_mtime_ns)
    if key not in _BUNDLE_CACHE:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _BUNDLE_CACHE.clear()
        _BUNDLE_CACHE[key] = [_load_entry(manifest_path.parent, entry) for entry in manifest.get("bundles", [])]
    return _BUNDLE_CACHE[key]


def _night(issued_at: pd.Timestamp) -> int:
    return int(issued_at.tz_convert(LOCAL_TZ).hour < 6)


def _intervals(bundle: dict, prediction: float, issued_at: pd.Timestamp) -> dict:
    """PI80/PI90 from calibration scores plus matured, scored live outcomes."""
    matured = ledger.matured_outcomes(bundle["model_version"], issued_at)
    night = _night(issued_at)
    pi = {"method": bundle["pi_method"], "night": night, "gamma": bundle.get("aci_gamma")}
    for level, alpha in PI_ALPHAS:
        if bundle["pi_method"] == "aci_scaled":
            pairs = [(o["abs_error"], (o.get("issued_q") or {}).get(level, math.inf)) for o in matured]
            band = aci_half_width(bundle["calibration_scores"], pairs, alpha, bundle["aci_gamma"])
        elif bundle["pi_method"] == "static_night":
            live: dict[int, list] = {}
            for outcome in matured:
                if outcome.get("night") is not None:
                    live.setdefault(int(outcome["night"]), []).append(outcome["abs_error"])
            band = static_night_half_width(bundle["calibration_scores_by_night"], live, night, alpha)
        else:
            raise ValueError(f"unknown_pi_method:{bundle['pi_method']}")
        band["lower"], band["upper"] = prediction - band["q"], prediction + band["q"]
        pi[level] = band
    return pi


def _sensor_status(target: str, origin: dict) -> str:
    if target != "pH":
        return "ok"
    values = [origin["current"]] + [origin["features"][f"pH_lag_{minute}m"] for minute in LAGS_MINUTES]
    return "ok" if all(ph_in_band(value) for value in values) else "ph_probe_suspect"


def _ph_input_status(bundle: dict, features: dict) -> str:
    """State of the pH inputs a non-pH bundle actually uses.

    Kept apart from ``sensor_status`` (target sensor; gates ledger scoring) so
    with-pH and nopH Temperature records stay comparable while pH drifts.
    """
    if bundle["target"] == "pH":
        return "target"
    used = [name for name in bundle["features"] if name.startswith("pH_")]
    if not used:
        return "not_used"
    return "ok" if all(ph_in_band(features[name]) for name in used) else "ph_probe_suspect"


_WEATHER_STORE: CapturedLiveWeather | None = None


def _default_weather_store() -> CapturedLiveWeather:
    global _WEATHER_STORE
    if _WEATHER_STORE is None:
        _WEATHER_STORE = CapturedLiveWeather()
    return _WEATHER_STORE


def issue_long_horizon(raw: pd.DataFrame, station_serial: str, *, freshness: dict, now=None, weather: dict | None = None,
                       weather_store: CapturedLiveWeather | None = None, tide_fn=None, manifest_path: Path = MANIFEST) -> dict:
    """Resolve matured long-horizon forecasts, then issue the 3/6/12 h shadow set.

    Issues only from fresh live sensor data (the runner's guard is re-checked
    here).  Missing weather/tide gives a logged skip, never a filled value.
    """
    summary = {"status": "ready", "issued": 0, "skipped": 0, "resolved": 0, "skips": []}
    if station_serial != PROMOTED_STATION:
        return {**summary, "status": "not_applicable", "reason": "station_not_promoted"}
    if freshness.get("status") != "fresh":
        return {**summary, "status": "blocked", "reason": freshness.get("reason") or f"freshness_{freshness.get('status')}"}
    bundles = load_bundles(manifest_path)
    if not bundles:
        return {**summary, "status": "unavailable", "reason": "long_horizon_bundles_missing"}
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    tide_fn = tide_fn or marine_tide
    summary["resolved"] = ledger.resolve_long_outcomes(raw)
    source = clean_raw(raw)
    max_age = float(freshness.get("max_staleness_minutes", 10))
    data_source = str(raw.attrs.get("data_source", "unknown"))
    location = weather_location_for_station(station_serial) or {}
    store = weather_store if weather_store is not None else _default_weather_store()
    origins: dict[str, dict] = {}
    tide: dict | None = None

    def skip(bundle: dict, reason: str, issued_at=None, **detail) -> None:
        record = {"station_serial": station_serial, "issued_at": None if issued_at is None else pd.Timestamp(issued_at).isoformat(),
                  "target": bundle["target"], "horizon_minutes": bundle["horizon_minutes"], "feature_set": bundle["feature_set"],
                  "model_version": bundle["model_version"], "reason": reason, "detail": detail, "data_source": data_source,
                  "recorded_at": now.isoformat()}
        ledger.append_long_skip(record)
        summary["skipped"] += 1
        summary["skips"].append({k: record[k] for k in ("target", "horizon_minutes", "feature_set", "reason")})

    for bundle in bundles:
        target = bundle["target"]
        status = bundle.get("status", "active")
        if status == WITHDRAWN:
            # never issued; the latest target reading only dates the skip line (hourly evidence)
            times = source.loc[source[target].notna(), "fetchedAt"] if target in source else pd.Series(dtype=object)
            skip(bundle, "bundle_withdrawn", None if times.empty else times.iloc[-1],
                 withdrawn_reason=bundle.get("withdrawn_reason"), withdrawn_at=bundle.get("withdrawn_at"))
            continue
        if status != "active":
            skip(bundle, "bundle_not_active", None, status=status)
            continue
        exclude_ph = is_nopH(bundle["feature_set"])
        if (target, exclude_ph) not in origins:
            origins[(target, exclude_ph)] = origin_features(source, target, exclude_ph=exclude_ph)
        origin = origins[(target, exclude_ph)]
        if origin["status"] != "ok":
            skip(bundle, origin["reason"], origin.get("issued_at"), missing_features=origin.get("missing_features", []))
            continue
        issued_at = origin["issued_at"]
        origin_age = (now - issued_at).total_seconds() / 60
        if origin_age > max_age:
            skip(bundle, "target_origin_stale", issued_at, origin_age_minutes=round(origin_age, 3))
            continue
        valid_at = issued_at + pd.Timedelta(minutes=bundle["horizon_minutes"])
        features = dict(origin["features"])
        extra: dict = {"weather_provenance": None, "tide_provenance": None}
        base_set = base_feature_set(bundle["feature_set"])
        if base_set == EXTERNAL_FEATURE_SET:
            context = store.features_at(issued_at, valid_at, station_serial, location.get("source", "unknown"))
            if context["status"] != "ok":
                skip(bundle, context["reason"], issued_at, **{k: v for k, v in context.items() if k not in {"status", "reason"}})
                continue
            features.update(context["features"])
            extra["weather_provenance"] = context["provenance"]
        elif base_set == TIDE_FEATURE_SET:
            if tide is None:
                tide = tide_fn(station_serial, weather)
            if tide["status"] != "ok":
                skip(bundle, tide["reason"], issued_at, marine_status=tide.get("marine_status"))
                continue
            context = tide_features_at(issued_at, valid_at, tide["series"])
            if context["status"] != "ok":
                skip(bundle, context["reason"], issued_at)
                continue
            features.update(context["features"])
            extra["tide_provenance"] = tide["provenance"]
            extra["tide_features"] = context["features"]
        missing = [name for name in bundle["features"] if name not in features or not np.isfinite(features[name])]
        if missing:
            skip(bundle, "feature_missing", issued_at, missing_features=missing)
            continue
        prediction = float(bundle["model"].predict(pd.DataFrame([features])[bundle["features"]])[0])
        record = {
            "station_serial": station_serial, "issued_at": issued_at.isoformat(), "valid_at": valid_at.isoformat(),
            "horizon_minutes": bundle["horizon_minutes"], "target": target, "feature_set": bundle["feature_set"],
            "model": "ridge", "model_version": bundle["model_version"], "model_variant": bundle.get("variant"),
            "bundle_role": bundle.get("role", "primary_shadow"), "forecast": prediction, "current": origin["current"],
            "pi": _intervals(bundle, prediction, issued_at), "sensor_status": _sensor_status(target, origin),
            "ph_input_status": _ph_input_status(bundle, features),
            "input_freshness": {"latest_observed_at": freshness.get("latest_observed_at"), "age_minutes": freshness.get("age_minutes"),
                                "origin_age_minutes": round(origin_age, 3), "gap_before_minutes": origin["features"]["gap_before_minutes"]},
            "data_source": data_source, "recorded_at": now.isoformat(), **extra,
        }
        summary["issued"] += int(ledger.append_long_forecast(record))
    return summary
