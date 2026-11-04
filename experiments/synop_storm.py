"""Shared helpers: 4TA SYNOP wind QC for the HP/QN stations + pairing with IBTrACS storm passages.

Used by ``experiments/synop_qc.py`` (task 1.5, descriptive QC) and
``experiments/storm_wind_calibration.py`` (task 2.1, pre-registered calibration).
Values are never edited: QC adds flag columns on an in-memory copy (docs/decisions.md #30).
Times: ``obs_utc`` (naive UTC) is matched to IBTrACS ``ISO_TIME`` (UTC).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core import paths
from core.storm_advisory import beaufort, haversine_km, interpolate_track, site_exposure

SYNOP_PATH = paths.VN_SYNOP_DIR / "derived" / "synop_3h_v2.parquet"

# exposure group: open_sea = island stations (closest analogue to an open-water cage),
# coastal = on the shore of an open bay / coast, sheltered = inside a bay or inland.
STATIONS = {
    "48839": {"name": "Bach Long Vi", "group": "open_sea",
              "note_vi": "Đảo giữa vịnh Bắc Bộ, cách bờ ~110 km; hở mọi hướng."},
    "48834": {"name": "Co To", "group": "open_sea",
              "note_vi": "Đảo ngoài cùng quần đảo Cô Tô, hở phía đông / nam."},
    "48828": {"name": "Hon Dau", "group": "open_sea",
              "note_vi": "Đảo nhỏ ngoài mũi Đồ Sơn, hở phía nam / đông."},
    "48829": {"name": "Van Ly", "group": "coastal",
              "note_vi": "Bờ biển Nam Định, đồng bằng thấp; không thuộc HP/QN, dùng đối chiếu."},
    "48836": {"name": "Cua Ong", "group": "coastal",
              "note_vi": "Bờ vịnh Bái Tử Long, có đảo che phía đông."},
    "48838": {"name": "Mong Cai", "group": "coastal",
              "note_vi": "Bờ biển sát biên giới, hở phía nam."},
    "48833": {"name": "Bai Chay", "group": "sheltered",
              "note_vi": "Trong vịnh Hạ Long, núi đá vôi che chắn; vẫn đo 45 m/s trong Yagi."},
    "48837": {"name": "Tien Yen", "group": "sheltered",
              "note_vi": "Cửa sông Tiên Yên, sâu trong vịnh, sát đồi."},
    "48/50": {"name": "Quang Ha", "group": "sheltered",
              "note_vi": "Trạm huyện Hải Hà, cách bờ vài km."},
    "48826": {"name": "Phu Lien", "group": "sheltered",
              "note_vi": "Đồi Phù Liễn (Kiến An), trong đất liền ~10 km."},
    "48/60": {"name": "Uong Bi", "group": "sheltered",
              "note_vi": "Trong đất liền, chân núi Yên Tử."},
}
HPQN_CODES = list(STATIONS)

WIND_MAX_VALID_MS = 60.0      # decisions #30 range flag (values 61-98 on calm days)
SPIKE_MIN_MS = 20.0           # only values >= this are spike candidates
SPIKE_NEIGHBOR_H = 6.0        # neighbours: same station, |dt| <= 6 h, not themselves flagged
SPIKE_RATIO = 0.5             # spike when max(neighbours) < ratio * value (no neighbour -> 0)
STORM_EXEMPT_KM = 300.0       # ... unless an IBTrACS centre is within this distance
STORM_EXEMPT_H = 12.0         # ... within this many hours of the obs


def load_synop(codes=None, columns=None) -> pd.DataFrame:
    codes = list(codes or HPQN_CODES)
    df = pd.read_parquet(SYNOP_PATH, columns=columns, filters=[("station_code", "in", codes)])
    return df.sort_values(["station_code", "obs_utc"], kind="stable").reset_index(drop=True)


def storm_near(obs_utc: pd.Series, track: pd.DataFrame, lat: float, lon: float,
               radius_km: float = STORM_EXEMPT_KM, pad_h: float = STORM_EXEMPT_H) -> np.ndarray:
    """True where any track point (ISO_TIME tz-aware UTC, LAT, LON) lies within ``radius_km`` of
    (lat, lon) and within ``pad_h`` hours of the obs time (naive UTC)."""
    pts = track.dropna(subset=["LAT", "LON"])
    d = haversine_km(pts["LAT"].to_numpy(), pts["LON"].to_numpy(), lat, lon)
    t = np.sort(pts.loc[d <= radius_km, "ISO_TIME"].dt.tz_convert("UTC").dt.tz_localize(None)
                .to_numpy(dtype="datetime64[ns]"))
    obs = pd.to_datetime(obs_utc).to_numpy(dtype="datetime64[ns]")
    if len(t) == 0:
        return np.zeros(len(obs), dtype=bool)
    pad = np.timedelta64(int(pad_h * 3600), "s")
    lo = np.searchsorted(t, obs - pad, side="left")
    hi = np.searchsorted(t, obs + pad, side="right")
    return hi > lo


def flag_wind(df: pd.DataFrame, near_storm: np.ndarray | None = None) -> pd.DataFrame:
    """Add ``wspd_range_bad``, ``wspd_spike``, ``wspd_valid`` (copy).  ``df`` = one or more stations
    with obs_utc, station_code, wspd_ms.  ``near_storm`` (aligned to ``df``) exempts spikes."""
    out = df.copy()
    w = out["wspd_ms"].astype(float)
    out["wspd_range_bad"] = w.notna() & ((w < 0) | (w > WIND_MAX_VALID_MS))
    ok = w.notna() & ~out["wspd_range_bad"]
    spike = np.zeros(len(out), dtype=bool)
    exempt = np.zeros(len(out), dtype=bool) if near_storm is None else np.asarray(near_storm, dtype=bool)
    pad = np.timedelta64(int(SPIKE_NEIGHBOR_H * 3600), "s")
    for _, idx in out.groupby("station_code", sort=False).indices.items():
        sub_ok = ok.to_numpy()[idx]
        t = out["obs_utc"].to_numpy(dtype="datetime64[ns]")[idx]
        v = w.to_numpy()[idx]
        order = np.argsort(t, kind="stable")
        t, v, sub_ok, pos = t[order], v[order], sub_ok[order], np.asarray(idx)[order]
        tv, vv = t[sub_ok], v[sub_ok]
        for i in np.flatnonzero(sub_ok & (v >= SPIKE_MIN_MS)):
            lo, hi = np.searchsorted(tv, t[i] - pad, "left"), np.searchsorted(tv, t[i] + pad, "right")
            nb = vv[lo:hi][tv[lo:hi] != t[i]]
            nb_max = float(nb.max()) if len(nb) else 0.0
            if nb_max < SPIKE_RATIO * v[i] and not exempt[pos[i]]:
                spike[pos[i]] = True
    out["wspd_spike"] = spike
    out["wspd_valid"] = ok & ~out["wspd_spike"]
    return out


def fit_factor(model, obs) -> float:
    """k minimising sum |obs - k * model| (weighted median of obs/model, weights = model)."""
    m, o = np.asarray(model, float), np.asarray(obs, float)
    keep = (m > 0) & np.isfinite(m) & np.isfinite(o)
    m, o = m[keep], o[keep]
    if len(m) == 0:
        return float("nan")
    r = o / m
    order = np.argsort(r, kind="stable")
    r, wt = r[order], m[order]
    cum = np.cumsum(wt)
    return float(r[np.searchsorted(cum, 0.5 * cum[-1], side="left")])


def tier_from_beaufort(level, thresholds: dict) -> int | None:
    if level is None or pd.isna(level):
        return None
    tier = 0
    for k, lo in sorted(((int(k), v) for k, v in thresholds.items())):
        if level >= lo:
            tier = k
    return tier


def station_passages(track: pd.DataFrame, obs: pd.DataFrame, lat: float, lon: float,
                     radius_km: float = 300.0, step: str = "30min", near_peak_h: float = 3.0) -> pd.DataFrame:
    """One row per storm whose densified track enters ``radius_km`` of the station.

    ``obs``: one station, columns obs_utc (naive UTC) + wspd_ms, already restricted to valid values.
    The model (``core.storm_advisory.site_exposure``) is evaluated at the SAME obs times as the
    observed max, so 3- or 6-hourly sampling affects both sides equally.  ``model_peak_cont_ms`` is
    the continuous-track peak, reported only as a secondary column.
    """
    o = obs[["obs_utc", "wspd_ms"]].dropna().sort_values("obs_utc")
    o_t = pd.to_datetime(o["obs_utc"]).dt.tz_localize("UTC")
    pts = track.dropna(subset=["LAT", "LON"])
    d0 = haversine_km(pts["LAT"].to_numpy(), pts["LON"].to_numpy(), lat, lon)
    rows = []
    for sid in pts.loc[d0 <= radius_km + 100.0, "SID"].unique():
        dense = interpolate_track(pts[pts["SID"] == sid], step)
        dense["dist_km"] = haversine_km(dense["LAT"].to_numpy(), dense["LON"].to_numpy(), lat, lon)
        inside = dense[dense["dist_km"] <= radius_km].reset_index(drop=True)
        if inside.empty:
            continue
        exp = pd.DataFrame([site_exposure(r, lat, lon) for _, r in inside.iterrows()])
        exp["ISO_TIME"] = inside["ISO_TIME"].to_numpy()
        exp["site_wind_ms"] = pd.to_numeric(exp["site_wind_ms"], errors="coerce")
        i_min = int(inside["dist_km"].idxmin())
        storm_close = exp.loc[i_min, "storm_wind_ms"]
        rec = {"SID": sid, "SEASON": int(inside["SEASON"].iloc[0]), "NAME": inside["NAME"].iloc[0],
               "min_dist_km": float(inside.loc[i_min, "dist_km"]), "closest_time": inside.loc[i_min, "ISO_TIME"],
               "storm_wind_closest_ms": None if pd.isna(storm_close) else float(storm_close),
               "storm_beaufort_closest": beaufort(None if pd.isna(storm_close) else float(storm_close)),
               "window_start": inside["ISO_TIME"].min(), "window_end": inside["ISO_TIME"].max()}
        if exp["site_wind_ms"].notna().any():
            pk = exp.loc[exp["site_wind_ms"].idxmax()]
            rec.update({"model_peak_cont_ms": float(pk["site_wind_ms"]), "model_peak_cont_time": pk["ISO_TIME"],
                        "model_peak_cont_method": pk["exposure_method"]})
        else:
            rec.update({"model_peak_cont_ms": np.nan, "model_peak_cont_time": pd.NaT,
                        "model_peak_cont_method": None})
        # pair obs to dense rows inside the radius (nearest within 15 min)
        win = (o_t >= rec["window_start"] - pd.Timedelta(minutes=15)) & (o_t <= rec["window_end"] + pd.Timedelta(minutes=15))
        ow = pd.DataFrame({"t": o_t[win].to_numpy(), "obs": o.loc[win.to_numpy(), "wspd_ms"].to_numpy(float)})
        ex = exp[["ISO_TIME", "site_wind_ms", "exposure_method"]].rename(columns={"ISO_TIME": "t"}).sort_values("t")
        ex["t"] = pd.to_datetime(ex["t"], utc=True)
        if len(ow):
            ow["t"] = pd.to_datetime(ow["t"], utc=True)
            pair = pd.merge_asof(ow.sort_values("t"), ex, on="t", direction="nearest",
                                 tolerance=pd.Timedelta(minutes=15)).dropna(subset=["site_wind_ms"])
        else:
            pair = pd.DataFrame(columns=["t", "obs", "site_wind_ms", "exposure_method"])
        rec["n_pairs"] = int(len(pair))
        if len(pair):
            io, im = pair["obs"].idxmax(), pair["site_wind_ms"].idxmax()
            rec.update({"obs_max_ms": float(pair.loc[io, "obs"]), "obs_max_time": pair.loc[io, "t"],
                        "model_max_ms": float(pair.loc[im, "site_wind_ms"]), "model_max_time": pair.loc[im, "t"],
                        "model_max_method": pair.loc[im, "exposure_method"]})
            pk_t = rec["model_peak_cont_time"]
            rec["obs_near_peak"] = bool(pd.notna(pk_t) and
                                        (abs(pair["t"] - pk_t) <= pd.Timedelta(hours=near_peak_h)).any())
        else:
            rec.update({"obs_max_ms": np.nan, "obs_max_time": pd.NaT, "model_max_ms": np.nan,
                        "model_max_time": pd.NaT, "model_max_method": None, "obs_near_peak": False})
        rows.append(rec)
    return pd.DataFrame(rows)


def distance_band(d: float) -> str:
    for hi, name in ((50, "0-50"), (100, "50-100"), (200, "100-200"), (300, "200-300")):
        if d <= hi:
            return name
    return ">300"


def intensity_class(level) -> str:
    if level is None or pd.isna(level):
        return "unknown"
    if level < 8:
        return "lt8"
    if level <= 11:
        return "8-11"
    return "ge12"
