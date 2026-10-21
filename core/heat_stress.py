"""Cobia heat-stress levels from water temperature (theory only, shadow).

Levels are growth/stress risk, not mortality:
  31 °C feed-conversion optimum (Sun & Chen 2014, 10–200 g cobia)
  33 °C growth optimum, declining above (Sun & Chen 2014; cobia_thresholds.json 33 -> 0.5)
  34 °C growth −36 % vs 30 °C, survival 100 % over 6 weeks (Le et al. 2024, doi:10.3389/faquc.2024.1476881)
The hot+calm flag (stratification -> low DO) is a hypothesis: no DO sensor to test it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WATCH_C, STRESS_C, SEVERE_C = 31.0, 33.0, 34.0
MIN_RUN_DAYS = 3
DEGREE_BASE_C, DEGREE_WINDOW_DAYS = 31.0, 7
HOT_AIR_C, CALM_WIND_MS = 35.0, 3.0
LABELS_VI = {0: "bình thường", 1: "theo dõi (≥31 °C)", 2: "stress nhiệt (≥33 °C)", 3: "stress nặng (≥34 °C)"}
_FLAGS = {"used_by_models": False, "used_by_alerts": False, "notification_eligible": False,
          "basis": "theory_only_unvalidated"}


def daily_heat_stress(sst_daily: pd.Series) -> pd.DataFrame:
    s = sst_daily.astype(float).sort_index()
    if isinstance(s.index, pd.DatetimeIndex) and len(s) > 1:
        s = s.asfreq("D")  # absent calendar dates become NaN days (break runs, count as zero degree-days)
    level = pd.Series(np.select([s >= SEVERE_C, s >= STRESS_C, s >= WATCH_C], [3, 2, 1], 0), index=s.index, dtype=float)
    level[s.isna()] = np.nan
    above = (s >= WATCH_C).astype(int)
    run = above.groupby((above == 0).cumsum()).cumsum()
    alert = level.where(run >= MIN_RUN_DAYS, level.clip(upper=1))
    degree = (s - DEGREE_BASE_C).clip(lower=0).fillna(0).rolling(DEGREE_WINDOW_DAYS, min_periods=1).sum()
    return pd.DataFrame({"temp_c": s, "level": level, "run_days": run, "alert_level": alert,
                         "degree_days_7d": degree.round(3)})


def hot_calm_flag(air_max_c: pd.Series, wind_mean_ms: pd.Series) -> pd.Series:
    return ((air_max_c >= HOT_AIR_C) & (wind_mean_ms < CALM_WIND_MS)).fillna(False).astype(bool)


def daily_from_hourly(series: pd.Series, tz: str = "Asia/Ho_Chi_Minh", min_hours: int = 18, how: str = "mean") -> pd.Series:
    local = series.dropna().copy()
    local.index = local.index.tz_convert(tz)
    grouped = local.groupby(local.index.date)
    daily = grouped.agg(how)[grouped.size() >= min_hours]
    daily.index = pd.to_datetime(daily.index)
    return daily


def evaluate_heat_advisory(marine: dict | None, now=None) -> dict:
    marine = marine or {}
    status = marine.get("status")
    if status not in {"ready", "stale"}:
        return {"status": "unavailable", "reason": marine.get("reason", "marine_unavailable"), **_FLAGS}
    hourly = marine.get("hourly") or {}
    times = pd.to_datetime(hourly.get("time") or [], errors="coerce")
    values = hourly.get("sea_surface_temperature")
    if values is None or len(times) == 0:
        return {"status": "unavailable", "reason": "sst_missing", **_FLAGS}
    if getattr(times, "tz", None) is None:
        times = times.tz_localize(marine.get("timezone", "Asia/Ho_Chi_Minh"))
    if len(values) != len(times):
        return {"status": "unavailable", "reason": "sst_length_mismatch", **_FLAGS}
    sst = pd.Series(pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(), index=times.tz_convert("UTC"))
    daily = daily_from_hourly(sst)  # full local days first (min_hours rule) so today is not truncated
    if now is not None:
        now = pd.Timestamp(now)
        now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
        daily = daily[daily.index >= pd.Timestamp(now.tz_convert("Asia/Ho_Chi_Minh").date())]
    days = daily_heat_stress(daily)
    days = days[days["level"].notna()]  # guard: never int() a NaN level
    if days.empty:
        return {"status": "unavailable", "reason": "no_complete_forecast_day", **_FLAGS}
    max_alert = int(days["alert_level"].max())
    return {"status": status, "source": "forecast",
            "days": [{"date": d.date().isoformat(), "temp_c": round(r.temp_c, 2), "level": int(r.level),
                      "alert_level": int(r.alert_level)} for d, r in days.iterrows()],
            "max_level": int(days["level"].max()), "max_alert_level": max_alert, "label_vi": LABELS_VI[max_alert],
            "note_vi": "Nguy cơ giảm tăng trưởng / stress, không phải dự báo cá chết. Chuỗi ≥3 ngày chỉ tính trên các ngày dự báo.",
            **_FLAGS}
