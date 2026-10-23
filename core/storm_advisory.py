"""Tropical-cyclone exposure and risk for a cage site (theory only, shadow).

Beaufort bounds, storm classes and risk levels follow Quyết định 18/2021/QĐ-TTg
(Điều 42 for storms on the coastal waters off Đông Bắc Bộ).  IBTrACS rows are
best-track post-analysis: use them for hindcast exposure only, never as forecast
skill.  Nothing here drives alerts or notifications.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

KNOT_MS = 0.514444
NMI_KM = 1.852
# 1-min sustained -> 10-min mean at sea (Harper et al. 2010, WMO/TD-1555); 0.88 is the sensitivity case.
ONE_MIN_TO_TEN_MIN = 0.93
BEAUFORT_LOWER_MS = (0.0, 0.3, 1.6, 3.4, 5.5, 8.0, 10.8, 13.9, 17.2, 20.8, 24.5, 28.5,
                     32.7, 37.0, 41.5, 46.2, 51.0, 56.1)
_UNIT_TO_MS = {"m/s": 1.0, "ms": 1.0, "km/h": 1 / 3.6, "kmh": 1 / 3.6, "kn": KNOT_MS, "kt": KNOT_MS, "knots": KNOT_MS}
# Own proposal; needs review by farmers and the local disaster-prevention office.
SITE_ACTIONS_VI = (
    (12, 4, "rất nguy hiểm", "Người rời lồng bè vào nơi trú ẩn theo lệnh của địa phương."),
    (10, 3, "nguy hiểm", "Thu hoạch sớm cá thương phẩm nếu kịp; gia cố hoặc kéo lồng vào nơi kín gió; người rời lồng trước khi gió mạnh lên."),
    (8, 2, "chuẩn bị", "Gia cố neo, dây, phao; giảm hoặc ngừng cho ăn; chuẩn bị phương án thu hoạch và di dời."),
    (6, 1, "theo dõi", "Kiểm tra neo, dây, phao; theo dõi bản tin bão."),
)


def _missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value)


def to_ms(value: float, unit: str) -> float:
    key = unit.strip().lower()
    if key not in _UNIT_TO_MS:
        raise ValueError(f"unknown wind unit: {unit}")
    return float(value) * _UNIT_TO_MS[key]


def beaufort(speed_ms: float | None) -> int | None:
    if _missing(speed_ms):
        return None
    level = 0
    for lvl, lower in enumerate(BEAUFORT_LOWER_MS):
        if speed_ms >= lower:
            level = lvl
    return level


def storm_class_vi(level: int | None) -> str | None:
    if level is None or level < 6:
        return None
    if level <= 7:
        return "áp thấp nhiệt đới"
    if level <= 9:
        return "bão"
    if level <= 11:
        return "bão mạnh"
    if level <= 15:
        return "bão rất mạnh"
    return "siêu bão"


def qd18_risk_level(level: int | None) -> int | None:
    """Cấp độ rủi ro for a storm on coastal waters / Đông Bắc Bộ (QĐ 18/2021, Điều 42)."""
    if level is None or level < 6:
        return None
    if level <= 11:
        return 3
    if level <= 15:
        return 4
    return 5


def site_action(level: int | None) -> dict:
    base = {"basis": "proposal_needs_expert_review"}
    if level is None:
        return {**base, "tier": None, "label_vi": None, "action_vi": None}
    for min_level, tier, label, action in SITE_ACTIONS_VI:
        if level >= min_level:
            return {**base, "tier": tier, "label_vi": label, "action_vi": action}
    return {**base, "tier": 0, "label_vi": "bình thường", "action_vi": None}


EARTH_RADIUS_KM = 6371.0088
DEFAULT_RMW_NMI = 30.0
RANKINE_ALPHA = 0.5
_RADII = (("USA_R64", 64.0), ("USA_R50", 50.0), ("USA_R34", 34.0))
_QUADS = ("NE", "SE", "SW", "NW")
IBTRACS_COLUMNS = ["SID", "SEASON", "NAME", "ISO_TIME", "LAT", "LON", "TOKYO_WIND", "HKO_WIND", "CMA_WIND",
                   "USA_WIND", "USA_RMW",
                   *[f"{p}_{q}" for p, _ in _RADII for q in _QUADS]]


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi, dlmb = p2 - p1, np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    """Initial bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def quadrant(bearing: float) -> str:
    return _QUADS[int(bearing // 90) % 4]


def rankine_wind_ms(vmax_ms: float, rmw_km: float, r_km: float, alpha: float = RANKINE_ALPHA) -> float:
    if r_km <= rmw_km:
        return vmax_ms * r_km / rmw_km
    return vmax_ms * (rmw_km / r_km) ** alpha


def storm_wind_ms(row: pd.Series, factor: float = ONE_MIN_TO_TEN_MIN) -> tuple[float | None, str | None]:
    if not _missing(row.get("TOKYO_WIND")):
        return float(row["TOKYO_WIND"]) * KNOT_MS, "tokyo_10min"
    if not _missing(row.get("HKO_WIND")):
        return float(row["HKO_WIND"]) * KNOT_MS, "hko_10min"
    if not _missing(row.get("USA_WIND")):
        return float(row["USA_WIND"]) * KNOT_MS * factor, "usa_1min_scaled"
    # CMA reports a 2-min mean; used without conversion, a slight overestimate vs a 10-min mean.
    # Order: 10-min agencies first, then JTWC with a documented 1->10 min factor, then CMA.
    if not _missing(row.get("CMA_WIND")):
        return float(row["CMA_WIND"]) * KNOT_MS, "cma_2min_unscaled"
    return None, None


def site_exposure(row: pd.Series, site_lat: float, site_lon: float, factor: float = ONE_MIN_TO_TEN_MIN) -> dict:
    dist = float(haversine_km(row["LAT"], row["LON"], site_lat, site_lon))
    quad = quadrant(bearing_deg(row["LAT"], row["LON"], site_lat, site_lon))
    vmax, wind_source = storm_wind_ms(row, factor)
    out = {"dist_km": dist, "quadrant": quad, "storm_wind_ms": vmax, "storm_wind_source": wind_source}
    for prefix, kt in _RADII:
        radius = row.get(f"{prefix}_{quad}")
        if not _missing(radius) and dist <= float(radius) * NMI_KM:
            speed = kt * KNOT_MS * factor
            return {**out, "site_wind_ms": speed, "site_beaufort": beaufort(speed), "exposure_method": "wind_radii"}
    if vmax is None:
        return {**out, "site_wind_ms": None, "site_beaufort": None, "exposure_method": "no_intensity"}
    rmw_nmi = DEFAULT_RMW_NMI if _missing(row.get("USA_RMW")) else float(row["USA_RMW"])
    speed = rankine_wind_ms(vmax, rmw_nmi * NMI_KM, max(dist, 0.1))
    method = "rankine"
    if not _missing(row.get(f"USA_R34_{quad}")):
        speed = min(speed, 34 * KNOT_MS * factor)
        method = "rankine_capped_by_r34"
    return {**out, "site_wind_ms": speed, "site_beaufort": beaufort(speed), "exposure_method": method}


def load_ibtracs(path) -> pd.DataFrame:
    # usecols keeps memory low on the full WP file (~250 MB, ~170 columns)
    df = pd.read_csv(path, skiprows=[1], usecols=lambda c: c in IBTRACS_COLUMNS, low_memory=False,
                     na_values=[" ", ""], keep_default_na=True)
    for col in IBTRACS_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    df = df[IBTRACS_COLUMNS].copy()
    df["ISO_TIME"] = pd.to_datetime(df["ISO_TIME"], utc=True)
    for col in IBTRACS_COLUMNS[4:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


_INTERP_COLS = ["LAT", "LON", "TOKYO_WIND", "HKO_WIND", "USA_WIND", "CMA_WIND", "USA_RMW",
                *[f"{p}_{q}" for p, _ in _RADII for q in _QUADS]]


def interpolate_track(grp: pd.DataFrame, step: str = "30min") -> pd.DataFrame:
    """Densify one storm's track to a ``step`` grid (original times kept, flagged ``interpolated=False``).

    A value at an interpolated time is filled only when both bracketing ORIGINAL rows have a value
    for that column; original rows keep their own value or NaN.  Duplicate ``ISO_TIME`` rows
    collapse to the one with the most non-NaN fields (ties: the last).
    """
    g = grp.sort_values("ISO_TIME", kind="stable").copy()
    g["_n"] = g.notna().sum(axis=1)
    # stable sort by (time, n) then keep the last -> most fields, ties -> last in input order
    g = g.sort_values(["ISO_TIME", "_n"], kind="stable").drop_duplicates("ISO_TIME", keep="last").drop(columns="_n")
    g = g.set_index("ISO_TIME")
    idx = pd.date_range(g.index[0], g.index[-1], freq=step).union(g.index)
    out = g.reindex(idx)
    is_new = ~idx.isin(g.index)
    out["interpolated"] = is_new
    if is_new.any():
        t_orig = g.index.asi8.astype(float)
        t_new = idx[is_new].asi8.astype(float)
        hi = np.searchsorted(t_orig, t_new, side="right")
        lo = hi - 1
        frac = (t_new - t_orig[lo]) / (t_orig[hi] - t_orig[lo])
        for col in out.columns.intersection(_INTERP_COLS):
            v = g[col].astype(float).to_numpy()
            # linear LON: no dateline unwrap (fine for this region).  NaN at either end -> NaN.
            # Wind radius 0 means "no such wind"; NaN means missing - both interpolate as plain numbers.
            col_vals = out[col].astype(float).to_numpy().copy()
            col_vals[is_new] = v[lo] + (v[hi] - v[lo]) * frac
            out[col] = col_vals
    for col in ("SID", "SEASON", "NAME"):
        if col in out.columns:
            out[col] = out[col].ffill()
    out.index.name = "ISO_TIME"
    return out.reset_index()


def storm_passages(track: pd.DataFrame, site_lat: float, site_lon: float, radius_km: float = 500.0,
                   coastal_radius_km: float = 200.0, factor: float = ONE_MIN_TO_TEN_MIN,
                   interp_step: str | None = "30min") -> pd.DataFrame:
    """One row per storm passing within ``radius_km``: peak site exposure + QĐ 18 level.

    Storm intensity (``storm_beaufort_max`` etc.) is the max over track rows within
    ``coastal_radius_km`` of the site (Điều 42 concerns the storm on the coastal waters);
    NA when no row is that close.  ``site_wind_lower_bound`` is True when the site wind
    comes from wind radii, which only give a floor.  With ``interp_step`` each storm's 3-hourly
    track is linearly densified first so a pass over the eyewall is not missed between rows.
    """
    cols = ["SID", "SEASON", "NAME", "peak_time", "min_dist_km", "storm_beaufort_max", "storm_class_vi",
            "qd18_level", "storm_wind_source", "site_wind_ms", "site_beaufort", "exposure_method",
            "site_wind_lower_bound", "source"]
    df = track.dropna(subset=["LAT", "LON"]).copy()
    df["dist_km"] = haversine_km(df["LAT"].to_numpy(), df["LON"].to_numpy(), site_lat, site_lon)
    if interp_step:
        # only storms with an original row near enough can have an interpolated point inside radius_km
        # (the +100 km margin assumes rows at most ~3-hourly apart)
        sids = df.loc[df["dist_km"] <= radius_km + 100.0, "SID"].unique()
        groups = []
        for sid in sids:
            dense = interpolate_track(df[df["SID"] == sid].drop(columns="dist_km"), interp_step)
            dense["dist_km"] = haversine_km(dense["LAT"].to_numpy(), dense["LON"].to_numpy(), site_lat, site_lon)
            dense = dense[dense["dist_km"] <= radius_km]
            if not dense.empty:
                groups.append((sid, dense))
    else:
        df = df[df["dist_km"] <= radius_km]
        groups = list(df.groupby("SID", sort=False))
    rows = []
    for sid, grp in groups:
        exposures = [site_exposure(r, site_lat, site_lon, factor) for _, r in grp.iterrows()]
        exp = pd.DataFrame(exposures, index=grp.index)
        exp["ISO_TIME"] = grp["ISO_TIME"]
        for col in ("site_wind_ms", "storm_wind_ms", "dist_km"):
            exp[col] = pd.to_numeric(exp[col], errors="coerce")
        peak = exp.sort_values(["site_wind_ms", "dist_km"], ascending=[False, True], na_position="last").iloc[0]
        storm_max = exp.loc[exp["dist_km"] <= coastal_radius_km, "storm_wind_ms"].max()
        storm_bf = beaufort(storm_max) if not _missing(storm_max) else None
        rows.append({"SID": sid, "SEASON": grp["SEASON"].iloc[0], "NAME": grp["NAME"].iloc[0],
                     "peak_time": peak["ISO_TIME"], "min_dist_km": float(exp["dist_km"].min()),
                     "storm_beaufort_max": storm_bf, "storm_class_vi": storm_class_vi(storm_bf),
                     "qd18_level": qd18_risk_level(storm_bf), "storm_wind_source": peak["storm_wind_source"],
                     "site_wind_ms": peak["site_wind_ms"],
                     "site_beaufort": peak["site_beaufort"], "exposure_method": peak["exposure_method"],
                     "site_wind_lower_bound": peak["exposure_method"] == "wind_radii",
                     "source": "best_track_oracle"})
    out = pd.DataFrame(rows, columns=cols)
    for col in ("storm_beaufort_max", "qd18_level", "site_beaufort"):
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")
    return out


_FLAGS = {"used_by_models": False, "used_by_alerts": False, "notification_eligible": False,
          "basis": "theory_only_unvalidated"}


def _future_hourly(weather: dict, key: str, now: pd.Timestamp, hours: int) -> pd.Series:
    hourly = weather.get("hourly") or {}
    times = pd.to_datetime(hourly.get("time") or [], errors="coerce")
    values = hourly.get(key)
    if values is None or len(times) == 0:
        return pd.Series(dtype=float)
    if getattr(times, "tz", None) is None:
        times = times.tz_localize(weather.get("timezone", "Asia/Ho_Chi_Minh"))
    series = pd.Series(pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(), index=times.tz_convert("UTC"))
    start = now.floor("h")
    return series[(series.index >= start) & (series.index < start + pd.Timedelta(hours=hours))].dropna()


def evaluate_storm_advisory(weather: dict | None, now=None, hours: int = 72) -> dict:
    """Forecast-wind advisory.  A naive ``now`` is interpreted as UTC."""
    weather = weather or {}
    status = weather.get("status")
    if status not in {"ready", "stale"}:
        return {"status": "unavailable", "reason": weather.get("reason", "weather_unavailable"), **_FLAGS}
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    units = weather.get("hourly_units") or {}
    wind = _future_hourly(weather, "wind_speed_10m", now, hours)
    if wind.empty:
        return {"status": "unavailable", "reason": "no_future_wind_hours", **_FLAGS}
    try:
        wind_ms = wind.map(lambda v: to_ms(v, units.get("wind_speed_10m", "km/h")))
        gust = _future_hourly(weather, "wind_gusts_10m", now, hours)
        gust_ms = gust.map(lambda v: to_ms(v, units.get("wind_gusts_10m", "km/h"))) if not gust.empty else gust
    except ValueError:
        return {"status": "unavailable", "reason": "unknown_wind_unit", **_FLAGS}
    level = beaufort(float(wind_ms.max()))
    extra = {k: weather[k] for k in ("stale_age_seconds", "reason") if k in weather}
    return {
        **extra,
        "status": status, "source": "forecast", "retrieved_at": weather.get("retrieved_at"),
        "window_hours": hours, "hours_available": int(len(wind_ms)),
        "max_wind_ms": round(float(wind_ms.max()), 2), "max_wind_at": wind_ms.idxmax().isoformat(),
        "max_gust_ms": round(float(gust_ms.max()), 2) if not gust_ms.empty else None,
        "site_beaufort": level, "action": site_action(level),
        "disclaimer": "Chỉ số lý thuyết, chưa kiểm chứng tại hiện trường; không thay thế bản tin của cơ quan khí tượng.",
        **_FLAGS,
    }
