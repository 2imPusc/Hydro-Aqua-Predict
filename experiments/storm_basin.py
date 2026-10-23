"""Basin-scale tropical-cyclone approach climatology and probability model for NB1 (Cát Bà).

Question: the operational path reads forecast wind AT the site and so "sees" a storm late.  How
much earlier could a basin view (storm centre, motion, intensity) warn, and at what false-alarm
cost?

    python experiments/storm_basin.py run --stamp 20261023

Inputs (read-only): IBTrACS v04r01 WP best track (``data/hazards/ibtracs``), the site-wind lead-time
results ``artifacts/experiments/storm-leadtime-20261023d`` and, if present, ECMWF TIGGE CXML track
extracts from ``experiments/tigge_tracks.py`` (``data/hazards/tigge``).

Definitions (also in the eval doc):
- Storm set: every non-spur IBTrACS WP track (TRACK_TYPE main / PROVISIONAL / US-PROVISIONAL) of
  seasons 1980-2026 = "all systems".  "TS+" = lifetime max wind >= 34 kt by any agency.
- Each track is regridded to a 3-hourly grid (linear; lon in 0-360).
- "Reach <= R" = any regridded point within R km of NB1, regardless of intensity or landfall.
- Gate crossing = first WESTWARD crossing of a meridian (first point with lon <= gate after a point
  east of it); storms whose first point is already west of the gate are not in that gate's
  denominator.
- Motion vector = BACKWARD difference over the last 12 h (6 h if younger) - realisable in real time.
  IBTrACS STORM_SPEED/STORM_DIR are not used.
- Model states: 6-hourly states (00/06/12/18 UTC) within 3000 km of NB1 whose track has not yet been
  within R; label(H) = track enters R within (t, t + H].  Track ending before t + H counts as 0.
- Evaluation: leave-one-season-out CV; Brier skill vs the training-fold base rate.

Best track is post-analysis: real-time positions carry ~20-50 km error and intensity is revised.
Nothing here drives alerts or notifications.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.storm_advisory import KNOT_MS, ONE_MIN_TO_TEN_MIN, haversine_km  # noqa: E402

SITE = (20.71894, 107.04264)
RADII = (200.0, 500.0)
HORIZONS = (24, 48, 72, 96, 120)
GATES_LON = (130.0, 125.0, 120.0, 115.0, 112.0)
GATES_DIST = (1000.0, 800.0, 600.0)
DOMAIN_KM = 3000.0
STEP_H = 3
STATE_STEP_H = 6
KM_PER_DEG = 111.195
THRESHOLDS = (0.2, 0.3, 0.5)
IBTRACS_FILE = "ibtracs.WP.list.v04r01.20261022.csv"
LEADTIME_RUN = "storm-leadtime-20261023d"
USECOLS = ["SID", "SEASON", "NAME", "ISO_TIME", "NATURE", "TRACK_TYPE", "LAT", "LON", "DIST2LAND",
           "WMO_WIND", "TOKYO_WIND", "HKO_WIND", "USA_WIND", "CMA_WIND", "USA_ATCF_ID"]
# Philippine archipelago as two boxes (main islands; Palawan).  Sabah/Borneo and Taiwan are outside.
PHILIPPINE_BOXES = ((5.5, 19.0, 119.5, 126.7), (8.3, 11.5, 117.1, 119.5))
FLAGS = {"used_by_models": False, "used_by_alerts": False, "notification_eligible": False,
         "basis": "theory_only_unvalidated"}


# --------------------------------------------------------------------------- pure helpers
def intensity_ms(df: pd.DataFrame) -> pd.Series:
    """10-min wind (m/s): TOKYO, HKO, USA x 0.93, CMA - the order of core.storm_advisory.storm_wind_ms."""
    out = pd.Series(np.nan, index=df.index, dtype=float)
    for col, factor in (("TOKYO_WIND", 1.0), ("HKO_WIND", 1.0), ("USA_WIND", ONE_MIN_TO_TEN_MIN), ("CMA_WIND", 1.0)):
        if col in df:
            out = out.fillna(pd.to_numeric(df[col], errors="coerce") * KNOT_MS * factor)
    return out


def regrid_track(g: pd.DataFrame, step_h: int = STEP_H) -> pd.DataFrame:
    """One storm -> uniform ``step_h`` grid (UTC hours divisible by step_h) inside the track's span.

    Duplicate times collapse to the row with most fields.  LAT/LON/wind/DIST2LAND interpolate
    linearly between valid original values; outside a column's valid span the value is NaN.
    """
    g = g.copy()
    g["_n"] = g.notna().sum(axis=1)
    g = g.sort_values(["ISO_TIME", "_n"], kind="stable").drop_duplicates("ISO_TIME", keep="last")
    t = g["ISO_TIME"].astype("int64").to_numpy() / 3.6e12  # hours since epoch
    step = float(step_h)
    grid = np.arange(np.ceil(t[0] / step) * step, t[-1] + 1e-9, step)
    out = {"ISO_TIME": pd.to_datetime(grid * 3.6e12, utc=True)}
    for col in ("LAT", "LON", "WIND_MS", "DIST2LAND"):
        if col not in g:
            out[col] = np.full(len(grid), np.nan)
            continue
        v = pd.to_numeric(g[col], errors="coerce").to_numpy(dtype=float)
        ok = ~np.isnan(v)
        vals = np.full(len(grid), np.nan)
        if ok.sum() >= 2:
            inside = (grid >= t[ok][0]) & (grid <= t[ok][-1])
            vals[inside] = np.interp(grid[inside], t[ok], v[ok])
        elif ok.sum() == 1:
            vals[np.isclose(grid, t[ok][0])] = v[ok][0]
        out[col] = vals
    res = pd.DataFrame(out)
    for col in ("SID", "SEASON", "NAME"):
        if col in g:
            res[col] = g[col].iloc[0]
    return res.dropna(subset=["LAT", "LON"]).reset_index(drop=True)


def first_westward_crossing(lons, gate: float) -> int | None:
    """Index of the first point with lon <= gate after the track started east of the gate."""
    lons = np.asarray(lons, dtype=float)
    if len(lons) == 0 or lons[0] <= gate:
        return None
    idx = np.flatnonzero(lons <= gate)
    return int(idx[0]) if len(idx) else None


def first_within(dist, radius: float) -> int | None:
    idx = np.flatnonzero(np.asarray(dist, dtype=float) <= radius)
    return int(idx[0]) if len(idx) else None


def backward_motion(lat, lon, step_h: int = STEP_H, back_h: int = 12, min_back_h: int = 6):
    """(u, v) km/h from the position ``back_h`` earlier (``min_back_h`` if the track is younger); NaN otherwise."""
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    n = len(lat)
    u, v = np.full(n, np.nan), np.full(n, np.nan)
    kmax, kmin = back_h // step_h, max(min_back_h // step_h, 1)
    for i in range(n):
        k = min(kmax, i)
        if k < kmin:
            continue
        j = i - k
        dt = k * step_h
        mlat = np.radians((lat[i] + lat[j]) / 2)
        u[i] = (lon[i] - lon[j]) * KM_PER_DEG * np.cos(mlat) / dt
        v[i] = (lat[i] - lat[j]) * KM_PER_DEG / dt
    return u, v


def approach_labels(dist, radius: float, horizons=HORIZONS, step_h: int = STEP_H):
    """eligible[i]: not yet within radius at or before i.  labels[H][i]: enters radius in (i, i + H]."""
    dist = np.asarray(dist, dtype=float)
    within = dist <= radius
    eligible = ~np.maximum.accumulate(within)
    first = first_within(dist, radius)
    n = len(dist)
    labels = {}
    idx = np.arange(n)
    for h in horizons:
        k = h // step_h
        lab = np.zeros(n, dtype=bool)
        if first is not None:
            lab = (idx < first) & (first <= idx + k)
        labels[h] = lab & eligible
    return eligible, labels


def in_philippines(lat, lon) -> np.ndarray:
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    m = np.zeros(len(lat), dtype=bool)
    for la0, la1, lo0, lo1 in PHILIPPINE_BOXES:
        m |= (lat >= la0) & (lat <= la1) & (lon >= lo0) & (lon <= lo1)
    return m


def corridor_at_120(lat_cross: float | None, born_west: bool) -> str:
    if born_west:
        return "SCS-born (west of 120E)"
    if lat_cross is None or np.isnan(lat_cross):
        return "never crossed 120E"
    if lat_cross < 12.0:
        return "120E <12N (Visayas/Mindanao)"
    if lat_cross < 16.5:
        return "120E 12-16.5N (central/S Luzon)"
    if lat_cross < 19.0:
        return "120E 16.5-19N (N Luzon)"
    if lat_cross < 22.5:
        return "120E 19-22.5N (Luzon Strait)"
    return "120E >=22.5N (Taiwan/north)"


def genesis_region(lon: float) -> str:
    if lon < 120.0:
        return "SCS (<120E)"
    if lon < 135.0:
        return "Philippine Sea (120-135E)"
    return "far WP (>=135E)"


def brier(p, y) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def brier_skill(p, y, p_ref) -> float:
    ref = brier(p_ref, y)
    return float("nan") if ref == 0 else 1.0 - brier(p, y) / ref


def reliability_table(p, y, edges=(0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001)) -> pd.DataFrame:
    p, y = np.asarray(p, float), np.asarray(y, float)
    b = np.clip(np.digitize(p, edges[1:-1]), 0, len(edges) - 2)
    rows = []
    for k in range(len(edges) - 1):
        m = b == k
        rows.append({"bin_lo": edges[k], "bin_hi": min(edges[k + 1], 1.0), "n": int(m.sum()),
                     "mean_p": float(p[m].mean()) if m.any() else np.nan,
                     "obs_freq": float(y[m].mean()) if m.any() else np.nan})
    return pd.DataFrame(rows)


def roc_auc(p, y) -> float:
    """Mann-Whitney AUC with average ranks for ties."""
    p, y = np.asarray(p, float), np.asarray(y, bool)
    n1, n0 = y.sum(), (~y).sum()
    if n1 == 0 or n0 == 0:
        return float("nan")
    ranks = pd.Series(p).rank(method="average").to_numpy()
    return float((ranks[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def event_leads(times, p, arrival, threshold: float) -> dict:
    """First and consistent threshold crossing before ``arrival``.

    ``times``/``p``: the storm's states before arrival (sorted).  Consistent = earliest state from
    which p stays >= threshold at every later state up to arrival.  Leads in hours (arrival - t).
    """
    times = pd.to_datetime(pd.Series(times), utc=True).reset_index(drop=True)
    p = np.asarray(p, float)
    keep = (times < arrival).to_numpy()
    times, p = times[keep].reset_index(drop=True), p[keep]
    out = {"first_lead_h": np.nan, "consistent_lead_h": np.nan}
    above = p >= threshold
    if not above.any():
        return out
    out["first_lead_h"] = (arrival - times[int(np.flatnonzero(above)[0])]).total_seconds() / 3600
    if above[-1]:
        below = np.flatnonzero(~above)
        start = 0 if len(below) == 0 else int(below[-1]) + 1
        out["consistent_lead_h"] = (arrival - times[start]).total_seconds() / 3600
    return out


def shrunk_rate(hits: np.ndarray, n: np.ndarray, base: float, k: float) -> np.ndarray:
    return (hits + k * base) / (n + k)


def extrapolate_hits(lat, lon, u, v, hours: int, radius: float, site=SITE, step_h: int = 3) -> np.ndarray:
    """CLIPER-style persistence: straight-line extrapolation of the current motion; 1 if it passes within radius."""
    lat, lon, u, v = (np.asarray(a, float) for a in (lat, lon, u, v))
    hit = np.zeros(len(lat), dtype=bool)
    for t in range(step_h, hours + 1, step_h):
        la = lat + v * t / KM_PER_DEG
        lo = lon + u * t / (KM_PER_DEG * np.cos(np.radians(lat)))
        d = haversine_km(la, lo, site[0], site[1])
        hit |= np.nan_to_num(d, nan=np.inf) <= radius
    return hit


# --------------------------------------------------------------------------- data
def load_tracks(path: Path, first_season: int = 1980) -> pd.DataFrame:
    df = pd.read_csv(path, skiprows=[1], usecols=lambda c: c in USECOLS, low_memory=False,
                     na_values=[" ", ""], keep_default_na=False)
    df = df[(pd.to_numeric(df["SEASON"], errors="coerce") >= first_season)
            & ~df["TRACK_TYPE"].astype(str).str.startswith("spur")
            & ~df["TRACK_TYPE"].astype(str).str.contains("_spur")].copy()
    df["ISO_TIME"] = pd.to_datetime(df["ISO_TIME"], utc=True)
    for c in ("LAT", "LON", "DIST2LAND", "WMO_WIND", "TOKYO_WIND", "HKO_WIND", "USA_WIND", "CMA_WIND"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["LON"] = df["LON"] % 360.0
    df["WIND_MS"] = intensity_ms(df)
    df["ANY_WIND_KT"] = df[["WMO_WIND", "TOKYO_WIND", "HKO_WIND", "USA_WIND", "CMA_WIND"]].max(axis=1)
    return df


def build(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """-> (storms summary, regridded 3-hourly tracks with features)."""
    storms, grids = [], []
    for sid, g in df.groupby("SID", sort=False):
        g = g.dropna(subset=["LAT", "LON"])
        if len(g) < 2:
            continue
        r = regrid_track(g[["SID", "SEASON", "NAME", "ISO_TIME", "LAT", "LON", "WIND_MS", "DIST2LAND"]])
        if len(r) < 2:
            continue
        r["dist_km"] = haversine_km(r["LAT"].to_numpy(), r["LON"].to_numpy(), *SITE)
        u, v = backward_motion(r["LAT"], r["LON"])
        r["u_kmh"], r["v_kmh"] = u, v
        k = 12 // STEP_H
        r["approach_kmh"] = (r["dist_km"].shift(k) - r["dist_km"]) / 12.0
        r["dwind_24h"] = r["WIND_MS"] - r["WIND_MS"].shift(24 // STEP_H)
        grids.append(r)
        orig = g.sort_values("ISO_TIME")
        rec = {"SID": sid, "SEASON": int(g["SEASON"].iloc[0]), "NAME": g["NAME"].iloc[0],
               "genesis_time": orig["ISO_TIME"].iloc[0], "genesis_lat": float(orig["LAT"].iloc[0]),
               "genesis_lon": float(orig["LON"].iloc[0]),
               "lmi_kt_any": float(g["ANY_WIND_KT"].max()) if g["ANY_WIND_KT"].notna().any() else np.nan,
               "min_dist_km": float(r["dist_km"].min()),
               "phil_land": bool((in_philippines(orig["LAT"], orig["LON"]) & (orig["DIST2LAND"] == 0)).any())}
        rec["ts_plus"] = bool(rec["lmi_kt_any"] >= 34) if not np.isnan(rec["lmi_kt_any"]) else False
        ts = orig[orig["ANY_WIND_KT"] >= 34]
        rec["ts_genesis_lat"] = float(ts["LAT"].iloc[0]) if len(ts) else np.nan
        rec["ts_genesis_lon"] = float(ts["LON"].iloc[0]) if len(ts) else np.nan
        rec["genesis_region"] = genesis_region(rec["genesis_lon"])
        lons, dist, times = r["LON"].to_numpy(), r["dist_km"].to_numpy(), r["ISO_TIME"]
        for radius in RADII:
            i = first_within(dist, radius)
            rec[f"arrive{int(radius)}"] = times.iloc[i] if i is not None else pd.NaT
        for gate in GATES_LON:
            i = first_westward_crossing(lons, gate)
            rec[f"cross{int(gate)}_time"] = times.iloc[i] if i is not None else pd.NaT
            rec[f"cross{int(gate)}_lat"] = float(r["LAT"].iloc[i]) if i is not None else np.nan
            rec[f"born_west_{int(gate)}"] = bool(lons[0] <= gate)
        for gd in GATES_DIST:
            i = first_within(dist, gd)
            rec[f"within{int(gd)}_time"] = times.iloc[i] if i is not None else pd.NaT
        rec["corridor"] = corridor_at_120(rec["cross120_lat"], rec["born_west_120"])
        storms.append(rec)
    return pd.DataFrame(storms), pd.concat(grids, ignore_index=True)


# --------------------------------------------------------------------------- climatology
def climatology_tables(st: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out = {}
    rows = []
    for subset, s in (("all", st), ("ts_plus", st[st["ts_plus"]])):
        for radius in RADII:
            hit = s[s[f"arrive{int(radius)}"].notna()]
            n = len(hit)
            row = {"set": subset, "radius_km": radius, "n_storms": n, "n_seasons": s["SEASON"].nunique(),
                   "per_year": n / s["SEASON"].nunique()}
            for reg, c in hit["genesis_region"].value_counts().items():
                row[f"genesis {reg}"] = c / n
            row["share_phil_land"] = hit["phil_land"].mean()
            for cor, c in hit["corridor"].value_counts().items():
                row[f"corridor {cor}"] = c / n
            rows.append(row)
    out["genesis_corridor_shares"] = pd.DataFrame(rows)
    # 5-degree genesis bins (map-able)
    g = st.copy()
    g["lat_bin"] = np.floor(g["genesis_lat"] / 5) * 5
    g["lon_bin"] = np.floor(g["genesis_lon"] / 5) * 5
    rows = []
    for (la, lo), s in g.groupby(["lat_bin", "lon_bin"]):
        rows.append({"lat_lo": la, "lon_lo": lo, "n_all": len(s), "n_ts_plus": int(s["ts_plus"].sum()),
                     "reach500_all": int(s["arrive500"].notna().sum()), "reach200_all": int(s["arrive200"].notna().sum()),
                     "reach500_ts": int((s["arrive500"].notna() & s["ts_plus"]).sum()),
                     "reach200_ts": int((s["arrive200"].notna() & s["ts_plus"]).sum())})
    gb = pd.DataFrame(rows)
    gb["p_reach500_all"] = gb["reach500_all"] / gb["n_all"]
    gb["p_reach200_all"] = gb["reach200_all"] / gb["n_all"]
    out["genesis_bins_5deg"] = gb[(gb["reach500_all"] > 0) | (gb["n_all"] >= 10)].sort_values(["lat_lo", "lon_lo"])
    # travel times
    rows = []
    for radius in RADII:
        arr = f"arrive{int(radius)}"
        gates = [(f"lon {int(x)}E", f"cross{int(x)}_time") for x in GATES_LON] + \
                [(f"within {int(x)} km", f"within{int(x)}_time") for x in GATES_DIST if x > radius]
        for label, col in gates:
            s = st[st[arr].notna() & st[col].notna()]
            h = (s[arr] - s[col]).dt.total_seconds() / 3600
            h = h[h >= 0]
            rows.append({"radius_km": radius, "gate": label, "n": len(h), "median_h": h.median(),
                         "q25_h": h.quantile(0.25), "q75_h": h.quantile(0.75), "q10_h": h.quantile(0.10),
                         "min_h": h.min(), "max_h": h.max()})
    out["travel_times"] = pd.DataFrame(rows)
    # by month of arrival (gate 120E and within 1000 km -> 200 km)
    rows = []
    s = st[st["arrive200"].notna()].copy()
    s["month"] = s["arrive200"].dt.month
    for col, label in (("cross120_time", "lon 120E"), ("within1000_time", "within 1000 km"), ("cross125_time", "lon 125E")):
        for m, grp in s.groupby("month"):
            h = (grp["arrive200"] - grp[col]).dt.total_seconds().dropna() / 3600
            rows.append({"gate": label, "arrival_month": m, "n_reach200": len(grp), "n_with_gate": len(h),
                         "median_h": h.median() if len(h) else np.nan,
                         "q25_h": h.quantile(.25) if len(h) else np.nan, "q75_h": h.quantile(.75) if len(h) else np.nan})
    out["travel_by_month"] = pd.DataFrame(rows)
    rows = []
    for radius in RADII:
        arr = f"arrive{int(radius)}"
        s = st[st[arr].notna()]
        for region, grp in [("all", s)] + list(s.groupby("genesis_region")):
            h = (grp[arr] - grp["genesis_time"]).dt.total_seconds() / 3600
            rows.append({"radius_km": radius, "genesis_region": region, "n": len(h), "median_h": h.median(),
                         "q25_h": h.quantile(.25), "q75_h": h.quantile(.75), "share_le_48h": (h <= 48).mean(),
                         "share_le_72h": (h <= 72).mean()})
    out["genesis_to_arrival"] = pd.DataFrame(rows)
    # gate base rates by latitude band at crossing
    rows = []
    for gate in GATES_LON:
        col = f"cross{int(gate)}"
        s = st[st[f"{col}_time"].notna()].copy()
        s["band"] = pd.cut(s[f"{col}_lat"], [-90, 10, 15, 20, 25, 90], right=False,
                           labels=["<10N", "10-15N", "15-20N", "20-25N", ">=25N"])
        for band, grp in [("all", s)] + list(s.groupby("band", observed=True)):
            after500 = (grp["arrive500"].notna() & (grp["arrive500"] >= grp[f"{col}_time"]))
            after200 = (grp["arrive200"].notna() & (grp["arrive200"] >= grp[f"{col}_time"]))
            rows.append({"gate": f"{int(gate)}E", "lat_band": band, "n_crossing": len(grp),
                         "share_reach500": after500.mean(), "share_reach200": after200.mean(),
                         "n_reach200": int(after200.sum())})
    out["gate_base_rates"] = pd.DataFrame(rows)
    return out


def position_bin_rates(grid: pd.DataFrame, st: pd.DataFrame, deg: float = 2.5) -> pd.DataFrame:
    """Share of storms visiting a lat/lon bin that later (after the first visit) reach NB1 <= 200/500 km."""
    g = grid[grid["dist_km"] <= DOMAIN_KM][["SID", "ISO_TIME", "LAT", "LON"]].copy()
    g["lat_lo"] = np.floor(g["LAT"] / deg) * deg
    g["lon_lo"] = np.floor(g["LON"] / deg) * deg
    first = g.groupby(["SID", "lat_lo", "lon_lo"], as_index=False)["ISO_TIME"].min()
    first = first.merge(st[["SID", "arrive200", "arrive500"]], on="SID")
    first["r200"] = first["arrive200"].notna() & (first["arrive200"] > first["ISO_TIME"])
    first["r500"] = first["arrive500"].notna() & (first["arrive500"] > first["ISO_TIME"])
    agg = first.groupby(["lat_lo", "lon_lo"]).agg(n_storms=("SID", "size"), share_reach500=("r500", "mean"),
                                                  share_reach200=("r200", "mean")).reset_index()
    return agg[agg["n_storms"] >= 5]


# --------------------------------------------------------------------------- model
FEATURES = ["LAT", "LON", "dist_km", "brg_sin", "brg_cos", "u_kmh", "v_kmh", "approach_kmh", "wind_ms",
            "wind_missing", "dwind_24h", "mon_sin", "mon_cos"]


def make_states(grid: pd.DataFrame, radius: float) -> pd.DataFrame:
    rows = []
    for sid, r in grid.groupby("SID", sort=False):
        eligible, labels = approach_labels(r["dist_km"].to_numpy(), radius)
        keep = eligible & (r["ISO_TIME"].dt.hour.to_numpy() % STATE_STEP_H == 0) & (r["dist_km"].to_numpy() <= DOMAIN_KM)
        if not keep.any():
            continue
        s = r.loc[keep].copy()
        for h, lab in labels.items():
            s[f"y{h}"] = lab[keep]
        rows.append(s)
    s = pd.concat(rows, ignore_index=True)
    return add_features(s)


def add_features(s: pd.DataFrame) -> pd.DataFrame:
    s = s.copy()
    lat0, lon0 = np.radians(SITE[0]), np.radians(SITE[1])
    la, lo = np.radians(s["LAT"].to_numpy()), np.radians(s["LON"].to_numpy())
    x = np.sin(lo - lon0) * np.cos(la)
    y = np.cos(lat0) * np.sin(la) - np.sin(lat0) * np.cos(la) * np.cos(lo - lon0)
    brg = np.arctan2(x, y)  # bearing NB1 -> storm
    s["brg_sin"], s["brg_cos"] = np.sin(brg), np.cos(brg)
    s["wind_missing"] = s["WIND_MS"].isna().astype(float)
    s["wind_ms"] = s["WIND_MS"]
    mon = s["ISO_TIME"].dt.month + s["ISO_TIME"].dt.day / 31.0
    s["mon_sin"], s["mon_cos"] = np.sin(2 * np.pi * mon / 12), np.cos(2 * np.pi * mon / 12)
    s["month"] = s["ISO_TIME"].dt.month
    return s


def _lr_matrix(df: pd.DataFrame) -> np.ndarray:
    base = df[FEATURES].copy()
    base["wind_ms"] = base["wind_ms"].fillna(15.0)
    for c in ("u_kmh", "v_kmh", "approach_kmh", "dwind_24h"):
        base[c] = base[c].fillna(0.0)
    x = base.to_numpy(float)
    lat, lon, u, v = base["LAT"].to_numpy(), base["LON"].to_numpy(), base["u_kmh"].to_numpy(), base["v_kmh"].to_numpy()
    dist = base["dist_km"].to_numpy() / 1000
    eta = base["dist_km"].to_numpy() / np.clip(base["approach_kmh"].to_numpy(), 2.0, None) / 24.0
    extra = np.column_stack([lat ** 2, lon ** 2, lat * lon, u * lat, v * lon, dist ** 2, np.log1p(eta)])
    return np.column_stack([x, extra])


def _season_bin(month: pd.Series) -> pd.Series:
    return pd.cut(month, [0, 5, 7, 9, 10, 12], labels=["Jan-May", "Jun-Jul", "Aug-Sep", "Oct", "Nov-Dec"])


def predict_condclim(train: pd.DataFrame, test: pd.DataFrame, ycol: str, base: float, deg: float = 2.5,
                     k: float = 10.0) -> np.ndarray:
    def keys(df):
        return (np.floor(df["LAT"] / deg).astype(int).astype(str) + "_" + np.floor(df["LON"] / deg).astype(int).astype(str)
                + "_" + _season_bin(df["month"]).astype(str))
    def keys_pos(df):
        return np.floor(df["LAT"] / deg).astype(int).astype(str) + "_" + np.floor(df["LON"] / deg).astype(int).astype(str)
    tr = train.assign(_k=keys(train).to_numpy(), _kp=keys_pos(train).to_numpy())
    pos = tr.groupby("_kp")[ycol].agg(["sum", "count"])
    pos_rate = shrunk_rate(pos["sum"].to_numpy(), pos["count"].to_numpy(), base, k)
    pos_rate = pd.Series(pos_rate, index=pos.index)
    full = tr.groupby("_k").agg(s=(ycol, "sum"), n=(ycol, "count"), kp=("_kp", "first"))
    prior = pos_rate.reindex(full["kp"]).to_numpy()
    full_rate = pd.Series((full["s"].to_numpy() + k * prior) / (full["n"].to_numpy() + k), index=full.index)
    te_k, te_kp = keys(test).to_numpy(), keys_pos(test).to_numpy()
    p = full_rate.reindex(te_k).to_numpy()
    fallback = pos_rate.reindex(te_kp).to_numpy()
    p = np.where(np.isnan(p), fallback, p)
    return np.where(np.isnan(p), base, p)


KNN_COLS = ["LAT", "LON", "u_kmh", "v_kmh", "mon_sin", "mon_cos"]
KNN_SCALE = np.array([1.0, 1.0, 1 / 5.0, 1 / 5.0, 2.0, 2.0])  # 1 deg ~ 5 km/h motion ~ 0.5 in month circle


def predict_knn(train: pd.DataFrame, test: pd.DataFrame, ycols: list[str], k: int = 50) -> dict[str, np.ndarray]:
    from sklearn.neighbors import NearestNeighbors
    def mat(df):
        m = df[KNN_COLS].copy()
        m[["u_kmh", "v_kmh"]] = m[["u_kmh", "v_kmh"]].fillna(0.0)
        return m.to_numpy(float) * KNN_SCALE
    nn = NearestNeighbors(n_neighbors=k).fit(mat(train))
    d, idx = nn.kneighbors(mat(test))
    w = 1.0 / (d + 0.25)
    out = {}
    for yc in ycols:
        yv = train[yc].to_numpy(float)[idx]
        out[yc] = (w * yv).sum(axis=1) / w.sum(axis=1)
    return out


def cross_validate(states: pd.DataFrame, radius: float, models=("clim", "condclim", "persistence", "logit", "hgb", "knn"),
                   noisy: pd.DataFrame | None = None, seed: int = 0) -> pd.DataFrame:
    """Leave-one-season-out predictions.  ``noisy``: test-feature replacement (same index) for the realism case."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    ycols = [f"y{h}" for h in HORIZONS]
    pred = pd.DataFrame(index=states.index)
    for season in sorted(states["SEASON"].unique()):
        te_mask = (states["SEASON"] == season).to_numpy()
        train = states.loc[~te_mask]
        test = states.loc[te_mask] if noisy is None else noisy.loc[te_mask]
        if "knn" in models:
            knn = predict_knn(train, test, ycols)
        for h, yc in zip(HORIZONS, ycols):
            ytr = train[yc].to_numpy(bool)
            base = ytr.mean()
            if "clim" in models:
                pred.loc[te_mask, f"clim_{h}"] = base
            if "condclim" in models:
                pred.loc[te_mask, f"condclim_{h}"] = predict_condclim(train, test, yc, base)
            if "persistence" in models:
                pred.loc[te_mask, f"persistence_{h}"] = extrapolate_hits(
                    test["LAT"], test["LON"], test["u_kmh"].fillna(0), test["v_kmh"].fillna(0), h, radius).astype(float)
            if "knn" in models:
                pred.loc[te_mask, f"knn_{h}"] = knn[yc]
            if ytr.sum() < 5:
                for m in ("logit", "hgb"):
                    if m in models:
                        pred.loc[te_mask, f"{m}_{h}"] = base
                continue
            if "logit" in models:
                lr = make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=2000))
                lr.fit(_lr_matrix(train), ytr)
                pred.loc[te_mask, f"logit_{h}"] = lr.predict_proba(_lr_matrix(test))[:, 1]
            if "hgb" in models:
                hgb = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
                                                     min_samples_leaf=40, l2_regularization=1.0, random_state=seed)
                hgb.fit(train[FEATURES].to_numpy(float), ytr)
                pred.loc[te_mask, f"hgb_{h}"] = hgb.predict_proba(test[FEATURES].to_numpy(float))[:, 1]
    return pred


def score_table(states: pd.DataFrame, pred: pd.DataFrame, radius: float, label: str) -> pd.DataFrame:
    rows = []
    models = sorted({c.rsplit("_", 1)[0] for c in pred.columns})
    for h in HORIZONS:
        y = states[f"y{h}"].to_numpy(bool)
        ref = pred[f"clim_{h}"].to_numpy()
        for m in models:
            p = pred[f"{m}_{h}"].to_numpy()
            rows.append({"case": label, "radius_km": radius, "horizon_h": h, "model": m, "n_states": len(y),
                         "n_pos": int(y.sum()), "base_rate": y.mean(), "brier": brier(p, y),
                         "bss_vs_clim": brier_skill(p, y, ref),
                         "bss_vs_condclim": brier_skill(p, y, pred[f"condclim_{h}"].to_numpy()) if f"condclim_{h}" in pred else np.nan,
                         "auc": roc_auc(p, y) if m != "clim" else np.nan})  # constant within a fold
    return pd.DataFrame(rows)


def perturb_states(grid: pd.DataFrame, states: pd.DataFrame, sigma_km: float, seed: int = 1) -> pd.DataFrame:
    """Recompute features from positions with independent Gaussian errors (per axis ``sigma_km``) at every 6-h fix."""
    rng = np.random.default_rng(seed)
    g = grid[grid["ISO_TIME"].dt.hour % STATE_STEP_H == 0].copy()
    g["LAT"] = g["LAT"] + rng.normal(0, sigma_km, len(g)) / KM_PER_DEG
    g["LON"] = g["LON"] + rng.normal(0, sigma_km, len(g)) / (KM_PER_DEG * np.cos(np.radians(g["LAT"])))
    parts = []
    for sid, r in g.groupby("SID", sort=False):
        r = r.copy()
        u, v = backward_motion(r["LAT"], r["LON"], step_h=STATE_STEP_H)
        r["u_kmh"], r["v_kmh"] = u, v
        r["dist_km"] = haversine_km(r["LAT"].to_numpy(), r["LON"].to_numpy(), *SITE)
        r["approach_kmh"] = (r["dist_km"].shift(2) - r["dist_km"]) / 12.0
        parts.append(r[["SID", "ISO_TIME", "LAT", "LON", "u_kmh", "v_kmh", "dist_km", "approach_kmh"]])
    noisy = pd.concat(parts, ignore_index=True)
    s = states.reset_index().merge(noisy, on=["SID", "ISO_TIME"], how="left", suffixes=("_true", ""))
    for c in ("LAT", "LON", "u_kmh", "v_kmh", "dist_km", "approach_kmh"):
        s[c] = s[c].fillna(s[f"{c}_true"])
    s = add_features(s.set_index("index"))
    return s.loc[states.index]


# --------------------------------------------------------------------------- event level
def event_level(states: pd.DataFrame, pred: pd.DataFrame, st: pd.DataFrame, model: str, horizon: int,
                radius: float = 200.0, watch_radius: float = 200.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Storm-level warnings from P(reach watch_radius within horizon) against arrival within ``radius``."""
    col = f"{model}_{horizon}"
    s = states[["SID", "SEASON", "ISO_TIME", "dist_km"]].join(pred[col].rename("p"))
    info = st.set_index("SID")
    rows = []
    for sid, grp in s.groupby("SID", sort=False):
        grp = grp.sort_values("ISO_TIME")
        rec = info.loc[sid]
        arrival = rec[f"arrive{int(radius)}"]
        row = {"SID": sid, "SEASON": rec["SEASON"], "NAME": rec["NAME"], "min_dist_km": rec["min_dist_km"],
               "reach200": pd.notna(rec["arrive200"]), "reach500": pd.notna(rec["arrive500"]),
               "genesis_region": rec["genesis_region"], "max_p": grp["p"].max(), "arrival": arrival}
        for thr in THRESHOLDS:
            if pd.notna(arrival):
                lead = event_leads(grp["ISO_TIME"], grp["p"], arrival, thr)
                row[f"first_lead_h_{thr}"] = lead["first_lead_h"]
                row[f"consistent_lead_h_{thr}"] = lead["consistent_lead_h"]
            row[f"crossed_{thr}"] = bool((grp["p"] >= thr).any())
        rows.append(row)
    ev = pd.DataFrame(rows)
    summ = []
    hit = ev[ev["reach200"]]
    n_seasons = st["SEASON"].nunique()
    for thr in THRESHOLDS:
        f = hit[f"first_lead_h_{thr}"]
        c = hit[f"consistent_lead_h_{thr}"]
        fa_never = ev[ev[f"crossed_{thr}"] & ~ev["reach500"]]
        fa_near = ev[ev[f"crossed_{thr}"] & ev["reach500"] & ~ev["reach200"]]
        summ.append({"model": model, "watch_radius_km": watch_radius, "horizon_h": horizon, "threshold": thr, "n_events_reach200": len(hit),
                     "n_warned": int(f.notna().sum()), "pod": f.notna().mean(),
                     "first_lead_median_h": f.median(), "first_lead_q25_h": f.quantile(.25), "first_lead_q75_h": f.quantile(.75),
                     "consistent_lead_median_h": c.median(), "consistent_lead_q25_h": c.quantile(.25),
                     "consistent_lead_q75_h": c.quantile(.75),
                     "n_storms_crossed": int(ev[f"crossed_{thr}"].sum()),
                     "fa_never_within500": len(fa_never), "near_miss_200_500": len(fa_near),
                     "fa_never500_per_season": len(fa_never) / n_seasons,
                     "false_alarm_ratio_storm": (len(fa_never) + len(fa_near)) / max(int(ev[f"crossed_{thr}"].sum()), 1)})
    return ev, pd.DataFrame(summ)


# --------------------------------------------------------------------------- comparison with site wind
def match_events_to_sids(events: pd.DataFrame, grid: pd.DataFrame) -> pd.Series:
    out = []
    for _, e in events.iterrows():
        t = pd.Timestamp(e["peak_time"])
        g = grid[(grid["ISO_TIME"] >= t - pd.Timedelta(hours=12)) & (grid["ISO_TIME"] <= t + pd.Timedelta(hours=12))]
        if g.empty:
            out.append(None)
            continue
        best = g.loc[g["dist_km"].idxmin()]
        out.append(best["SID"] if abs(best["dist_km"] - e["min_dist_km"]) < 150 else None)
    return pd.Series(out, index=events.index)


# --------------------------------------------------------------------------- TIGGE
def tigge_files() -> list[Path]:
    d = paths.HAZARD_DATA_DIR / "tigge"
    return sorted(d.glob("ecmf_cxml_wp_tracks_*.csv")) if d.exists() else []


def match_tigge(tg: pd.DataFrame, grid: pd.DataFrame, max_km: float = 300.0) -> pd.DataFrame:
    """Attach IBTrACS SID to each (base_time, disturbance) by nearest best-track position at the HRES/control t0."""
    t0 = tg[tg["hour"] == 0].groupby(["base_time", "disturbance_id"], as_index=False)[["lat", "lon"]].mean()
    gi = grid.set_index("ISO_TIME")
    sids = []
    for _, r in t0.iterrows():
        bt = pd.Timestamp(r["base_time"], tz="UTC")
        cand = grid[grid["ISO_TIME"] == bt]
        if cand.empty:
            sids.append((None, np.nan))
            continue
        d = haversine_km(cand["LAT"].to_numpy(), cand["LON"].to_numpy(), r["lat"], r["lon"])
        i = int(np.argmin(d))
        sids.append((cand["SID"].iloc[i], float(d[i])) if d[i] <= max_km else (None, float(d[i])))
    t0["SID"] = [s for s, _ in sids]
    t0["t0_err_km"] = [e for _, e in sids]
    del gi
    return t0


def tigge_eval(tg: pd.DataFrame, grid: pd.DataFrame, st: pd.DataFrame) -> dict[str, pd.DataFrame]:
    tg = tg.copy()
    tg["base_time"] = pd.to_datetime(tg["base_time"], utc=True)
    tg["valid_time"] = pd.to_datetime(tg["valid_time"], utc=True)
    tg["lon"] = tg["lon"] % 360.0
    key = match_tigge(tg.assign(base_time=tg["base_time"].dt.strftime("%Y-%m-%dT%H:%M:%S")), grid)
    key["base_time"] = pd.to_datetime(key["base_time"], utc=True)
    tg = tg.merge(key[["base_time", "disturbance_id", "SID", "t0_err_km"]], on=["base_time", "disturbance_id"], how="left")
    tg = tg[tg["SID"].notna()]
    # track error of HRES vs best track (interpolated 3-hourly grid), verifying points west of 130E
    g = grid[["SID", "ISO_TIME", "LAT", "LON"]].rename(columns={"ISO_TIME": "valid_time"})
    hres = tg[tg["member"] == "hres"].merge(g, on=["SID", "valid_time"], how="inner")
    hres["err_km"] = haversine_km(hres["lat"].to_numpy(), hres["lon"].to_numpy(), hres["LAT"].to_numpy(), hres["LON"].to_numpy())
    hres["dist_bt_km"] = haversine_km(hres["LAT"].to_numpy(), hres["LON"].to_numpy(), *SITE)
    # matching sanity: drop forecasts whose t0 is > 150 km from the best track (mismatch / genesis-stage)
    hres = hres[hres["t0_err_km"] <= 150.0]
    rows = []
    for region, m in (("all WP", np.ones(len(hres), bool)), ("verif <=1500 km of NB1", hres["dist_bt_km"] <= 1500)):
        for h in (0, 24, 48, 72, 96, 120):
            e = hres.loc[m & (hres["hour"] == h), "err_km"]
            rows.append({"region": region, "lead_h": h, "n": len(e), "n_storms": hres.loc[m & (hres["hour"] == h), "SID"].nunique(),
                         "median_km": e.median(), "mean_km": e.mean(), "q25_km": e.quantile(.25), "q75_km": e.quantile(.75)})
    track_err = pd.DataFrame(rows)
    # ensemble approach probability per (base_time, SID)
    ens = tg[tg["member"].str.startswith("ens")].copy()
    ens["d"] = haversine_km(ens["lat"].to_numpy(), ens["lon"].to_numpy(), *SITE)
    nmem = ens.groupby(["base_time", "SID"])["member"].nunique().rename("n_members")
    rows = []
    for (bt, sid), grp in ens.groupby(["base_time", "SID"]):
        r = {"base_time": bt, "SID": sid}
        for radius in RADII:
            for h in HORIZONS:
                hit = grp[(grp["hour"] > 0) & (grp["hour"] <= h) & (grp["d"] <= radius)]["member"].nunique()
                r[f"ens_p{int(radius)}_{h}"] = hit / max(nmem.loc[(bt, sid)], 1)
        rows.append(r)
    ensp = pd.DataFrame(rows).merge(nmem.reset_index(), on=["base_time", "SID"])
    return {"track_err": track_err, "ens_prob": ensp, "hres_points": hres}


# --------------------------------------------------------------------------- run
def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(stamp: str, fast: bool = False, out_root: Path | None = None) -> Path:
    ib = paths.HAZARD_DATA_DIR / "ibtracs" / IBTRACS_FILE
    df = load_tracks(ib)
    st, grid = build(df)
    clim = climatology_tables(st)
    clim["position_bin_rates"] = position_bin_rates(grid, st)
    results: dict[str, pd.DataFrame] = {"storms": st, **clim}
    scores, rel, ev_summ, events_all, preds = [], [], [], {}, {}
    for radius in RADII:
        states = make_states(grid, radius)
        pred = cross_validate(states, radius) if not fast else cross_validate(states, radius, models=("clim", "condclim", "knn"))
        preds[radius] = (states, pred)
        scores.append(score_table(states, pred, radius, "best_track"))
        noisy = perturb_states(grid, states, sigma_km=30.0)
        pred_n = cross_validate(states, radius, models=("clim", "condclim", "hgb", "logit", "knn") if not fast else ("clim", "knn"),
                                noisy=noisy)
        scores.append(score_table(states, pred_n, radius, "noisy_positions_30km_per_axis"))
        for m in [c.rsplit("_", 1)[0] for c in pred.columns if c.endswith("_120")]:
            for h in (48, 120):
                t = reliability_table(pred[f"{m}_{h}"], states[f"y{h}"])
                t.insert(0, "model", m)
                t.insert(0, "horizon_h", h)
                t.insert(0, "radius_km", radius)
                rel.append(t)
        if radius == 200.0:
            for m in [c.rsplit("_", 1)[0] for c in pred.columns if c.endswith("_120")]:
                if m in ("clim",):
                    continue
                for h in (72, 120):
                    ev, summ = event_level(states, pred, st, m, h)
                    events_all[f"{m}_{h}"] = ev
                    ev_summ.append(summ)
                    pn = pred_n.rename(columns=lambda c: c)
                    if f"{m}_{h}" in pn:
                        evn, summn = event_level(states, pn, st, m, h)
                        summn.insert(0, "case", "noisy_positions_30km_per_axis")
                        ev_summ.append(summn)
                        events_all[f"{m}_{h}_noisy"] = evn
    states500, pred500 = preds[500.0]
    for m in ("hgb", "logit", "knn", "condclim"):
        if f"{m}_120" in pred500:
            ev, summ = event_level(states500, pred500, st, m, 120, radius=200.0, watch_radius=500.0)
            events_all[f"{m}_120_watch500"] = ev
            ev_summ.append(summ)
    reg_rows = []
    for name, ev in events_all.items():
        if name.endswith("_noisy"):
            continue
        hit = ev[ev["reach200"]]
        for region, grp in [("all", hit)] + list(hit.groupby("genesis_region")):
            for thr in THRESHOLDS:
                if f"first_lead_h_{thr}" not in grp:
                    continue
                f = grp[f"first_lead_h_{thr}"]
                reg_rows.append({"run": name, "genesis_region": region, "threshold": thr, "n": len(grp),
                                 "pod": f.notna().mean(), "first_lead_median_h": f.median(),
                                 "first_lead_q25_h": f.quantile(.25), "first_lead_q75_h": f.quantile(.75),
                                 "consistent_lead_median_h": grp[f"consistent_lead_h_{thr}"].median()})
    results["event_lead_by_region"] = pd.DataFrame(reg_rows)
    results["model_scores"] = pd.concat(scores, ignore_index=True)
    results["reliability"] = pd.concat(rel, ignore_index=True)
    results["event_lead_summary"] = pd.concat(ev_summ, ignore_index=True)
    # comparison with site wind path
    lt = paths.EXPERIMENT_OUTPUT_DIR / LEADTIME_RUN / "events_ecmwf_ifs025_vs_era5.csv"
    sw_all = pd.read_csv(lt)
    bf8 = sw_all[sw_all["threshold_bf"] == 8].set_index("NAME")["consistent_lead_hours_truth"]
    sw = sw_all[sw_all["threshold_bf"] == 6].reset_index(drop=True)
    sw["SID"] = match_events_to_sids(sw, grid)
    states200, pred200 = preds[200.0]
    comp = []
    for _, e in sw.iterrows():
        rec = {"NAME": e["NAME"], "SID": e["SID"], "peak_time": e["peak_time"], "min_dist_km": round(e["min_dist_km"]),
               "era5_bf": e["truth_max_bf"], "track_bf": e["site_beaufort"],
               "site_wind_consistent_N_d": e["consistent_N_truth"], "site_wind_consistent_lead_h": e["consistent_lead_hours_truth"],
               "site_wind_any_lead_h": e["any_lead_hours_truth"],
               "site_wind_consistent_lead_h_track": e["consistent_lead_hours_track"],
               "site_wind_bf8_consistent_lead_h": bf8.get(e["NAME"]) if e["NAME"] == "YAGI" else np.nan}
        if e["SID"] is not None and isinstance(e["SID"], str):
            srec = st.set_index("SID").loc[e["SID"]]
            peak = pd.Timestamp(e["peak_time"])
            rec["arrive200"], rec["arrive500"] = srec["arrive200"], srec["arrive500"]
            rec["genesis_time"] = srec["genesis_time"]
            rec["hours_genesis_to_peak"] = (peak - srec["genesis_time"]).total_seconds() / 3600
            rec["corridor"], rec["genesis_region"] = srec["corridor"], srec["genesis_region"]
            rec["genesis_dist_km"] = float(haversine_km(srec["genesis_lat"], srec["genesis_lon"], *SITE))
            rec["n_states_r200"] = int((states200["SID"] == e["SID"]).sum())
            rec["unwarnable_r200"] = rec["n_states_r200"] == 0
            for radius, (sts, pr) in ((200.0, (states200, pred200)), (500.0, (states500, pred500))):
                s = sts[sts["SID"] == e["SID"]].sort_values("ISO_TIME")
                for m in ("hgb", "condclim"):
                    if f"{m}_120" not in pr:
                        continue
                    p = pr.loc[s.index, f"{m}_120"]
                    for thr in (0.3,):
                        lead = event_leads(s["ISO_TIME"], p, peak, thr)
                        rec[f"basin_{m}_r{int(radius)}_first_lead_h_to_peak"] = lead["first_lead_h"]
                        rec[f"basin_{m}_r{int(radius)}_consistent_lead_h_to_peak"] = lead["consistent_lead_h"]
                    rec[f"basin_{m}_r{int(radius)}_max_p120"] = p.max() if len(p) else np.nan
        comp.append(rec)
    results["comparison_site_wind"] = pd.DataFrame(comp)
    # TIGGE (optional)
    tfiles = tigge_files()
    tig_meta = []
    if tfiles:
        tg = pd.concat([pd.read_csv(f) for f in tfiles], ignore_index=True)
        tig_meta = [{"file": f.name, "sha256": _sha(f)} for f in tfiles]
        te = tigge_eval(tg, grid, st)
        results["tigge_hres_track_error"] = te["track_err"]
        results.update(tigge_vs_basin(te["ens_prob"], preds, st))
        tev = results["tigge_vs_basin_events"]
        keep = ["SID", "n_runs"] + [c for c in tev.columns if c.startswith("ecmwf_ens_")]
        results["comparison_site_wind"] = results["comparison_site_wind"].merge(
            tev[keep].rename(columns={"n_runs": "ens_n_runs_pre_arrival"}), on="SID", how="left")
    # write once
    out = (out_root or paths.EXPERIMENT_OUTPUT_DIR) / f"storm-basin-{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    for name, frame in results.items():
        frame.to_csv(out / f"{name}.csv", index=False)
    for name, ev in events_all.items():
        ev.to_csv(out / f"events_{name}.csv", index=False)
    for radius, (sts, pr) in preds.items():
        keep = sts[["SID", "SEASON", "NAME", "ISO_TIME", "LAT", "LON", "dist_km"] + [f"y{h}" for h in HORIZONS]]
        keep.join(pr).to_csv(out / f"oof_predictions_r{int(radius)}.csv", index=False)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "script": "experiments/storm_basin.py",
                "ibtracs": {"file": ib.name, "sha256": _sha(ib)}, "site_wind_events": {"file": str(lt.relative_to(paths.ARTIFACTS_DIR)), "sha256": _sha(lt)},
                "tigge": tig_meta, "site": SITE, "radii_km": RADII, "horizons_h": HORIZONS, "domain_km": DOMAIN_KM,
                "cv": "leave-one-season-out", "storm_set": "all non-spur IBTrACS WP tracks 1980-2026; ts_plus = LMI>=34 kt any agency",
                "figures": "skipped (matplotlib not installed in root venv)", "source": "best_track_oracle",
                **FLAGS, "files": sorted(p.name for p in out.iterdir())}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return out


def tigge_vs_basin(ensp: pd.DataFrame, preds: dict, st: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Same (storm, 00 UTC state) pairs: ECMWF ensemble fraction vs basin model OOF probability."""
    rows, evrows, relrows = [], [], []
    for radius, (sts, pr) in preds.items():
        s = sts[["SID", "ISO_TIME"] + [f"y{h}" for h in HORIZONS]].join(pr)
        m = s.merge(ensp, left_on=["SID", "ISO_TIME"], right_on=["SID", "base_time"], how="inner")
        for h in HORIZONS:
            y = m[f"y{h}"].to_numpy(bool)
            for name, col in (("ecmwf_ens", f"ens_p{int(radius)}_{h}"), ("hgb", f"hgb_{h}"), ("condclim", f"condclim_{h}"),
                              ("knn", f"knn_{h}"), ("clim", f"clim_{h}")):
                if col not in m:
                    continue
                p = m[col].to_numpy(float)
                rows.append({"radius_km": radius, "horizon_h": h, "model": name, "n_states": len(y), "n_pos": int(y.sum()),
                             "brier": brier(p, y), "bss_vs_clim": brier_skill(p, y, m[f"clim_{h}"].to_numpy()),
                             "auc": roc_auc(p, y)})
        if radius == 200.0:
            info = st.set_index("SID")
            for sid, grp in m.groupby("SID"):
                arrival = info.loc[sid, "arrive200"]
                rec = {"SID": sid, "NAME": info.loc[sid, "NAME"], "SEASON": info.loc[sid, "SEASON"],
                       "reach200": pd.notna(arrival), "reach500": pd.notna(info.loc[sid, "arrive500"]),
                       "n_runs": len(grp)}
                grp = grp.sort_values("ISO_TIME")
                for name, col in (("ecmwf_ens", "ens_p200_120"), ("hgb", "hgb_120")):
                    if col not in grp:
                        continue
                    for thr in THRESHOLDS:
                        rec[f"{name}_crossed_{thr}"] = bool((grp[col] >= thr).any())
                        if pd.notna(arrival):
                            lead = event_leads(grp["ISO_TIME"], grp[col], arrival, thr)
                            rec[f"{name}_first_lead_h_{thr}"] = lead["first_lead_h"]
                            rec[f"{name}_consistent_lead_h_{thr}"] = lead["consistent_lead_h"]
                    rec[f"{name}_max_p"] = grp[col].max()
                evrows.append(rec)
        for h in (48, 120):
            for name, col in (("ecmwf_ens", f"ens_p{int(radius)}_{h}"), ("hgb", f"hgb_{h}")):
                if col not in m:
                    continue
                t = reliability_table(m[col], m[f"y{h}"])
                t.insert(0, "model", name)
                t.insert(0, "horizon_h", h)
                t.insert(0, "radius_km", radius)
                relrows.append(t)
    ev = pd.DataFrame(evrows)
    summ = []
    seasons = ev["SEASON"].nunique() if len(ev) else 1
    for name in ("ecmwf_ens", "hgb"):
        if f"{name}_max_p" not in ev:
            continue
        hit = ev[ev["reach200"]]
        for thr in THRESHOLDS:
            f, c = hit[f"{name}_first_lead_h_{thr}"], hit[f"{name}_consistent_lead_h_{thr}"]
            crossed = ev[f"{name}_crossed_{thr}"]
            never = int((crossed & ~ev["reach500"]).sum())
            near = int((crossed & ev["reach500"] & ~ev["reach200"]).sum())
            summ.append({"model": name, "p": "P(<=200 km within 120 h)", "threshold": thr, "n_storms": len(ev),
                         "n_events_reach200": len(hit), "n_warned": int(f.notna().sum()), "pod": f.notna().mean(),
                         "first_lead_median_h": f.median(), "first_lead_q25_h": f.quantile(.25),
                         "first_lead_q75_h": f.quantile(.75), "consistent_lead_median_h": c.median(),
                         "n_storms_crossed": int(crossed.sum()), "fa_never_within500": never,
                         "near_miss_200_500": near, "fa_never500_per_season": never / seasons})
    return {"tigge_vs_basin_scores": pd.DataFrame(rows), "tigge_vs_basin_events": ev,
            "tigge_vs_basin_event_summary": pd.DataFrame(summ),
            "tigge_vs_basin_reliability": pd.concat(relrows, ignore_index=True) if relrows else pd.DataFrame()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--stamp", required=True)
    r.add_argument("--fast", action="store_true", help="skip logit/hgb (smoke test)")
    args = ap.parse_args(argv)
    print(run(args.stamp, fast=args.fast))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
