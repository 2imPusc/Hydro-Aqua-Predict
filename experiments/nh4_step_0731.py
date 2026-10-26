"""What happened to NB1 NH4 / TSS on 2026-07-31 ~14:06 local?  (research-only, read-only)

Question (owner, 2026-10-26): NH4 fell ~20x in one step and TSS ~70 -> 3-4 mg/L while pH and
Temperature did not move.  Real change in the water, or a change in the instrument?  And for
farming: is the post-step state better, worse, or an artefact?

Evidence assembled here (all inputs read-only, sha256 in manifest.json):

1. Step anatomy on the raw GreenLab interval exports (2 readings / minute): exact sample of
   the step per variable (``detect_level_step``), data gaps, repeated readings, the 30-minute
   instrument cycle (``cycle_profile``) and whether the step falls on it.  A second event
   (2026-08-12, 2.4 h gap, COD rail -> 0.0) is analysed the same way as a contrast.
2. Signal character before vs after (frozen history, 1-min): level, relative spread, minute
   noise in log space, tidal correlation with modelled sea level, hour-of-day amplitude,
   hour-lag autocorrelation.  A multiplicative rescale of a working sensor keeps the relative
   structure; a dead / saturated probe loses it.
3. Environment around the step: ERA5 rain / wind, modelled sea level, CMEMS GLO12 surface
   salinity / temperature (nearest sea cell), CMEMS ocean-colour SPM / CHL / KD490 (4 km cell
   2.3 km from NB1), IBTrACS storms.
4. Plausibility of each regime against background levels: provincial monitoring (HP Cat Ba /
   Lach Huyen, QN), RIMF 2013 Cat Ba cage zones (Le Tuan Son et al. 2014), satellite SPM.

    python experiments/nh4_step_0731.py [--run-name nh4-step-0731-20261026]

Writes a NEW run dir under paths.EXPERIMENT_OUTPUT_DIR (exist_ok=False).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.config import NH4_TO_N_FACTOR, NH4_UNIT_SCALE  # noqa: E402

STATION = "06M26042804"
LOCAL_TZ = "Asia/Ho_Chi_Minh"
NB1_LAT, NB1_LON = 20.71894498573044, 107.042635855355  # ingest/stations.yaml weather_location
VARS = ("COD", "NH4", "pH", "Temperature", "TSS")
RAW_NAME = {"Temp": "Temperature"}

HISTORY = paths.EXPERIMENT_OUTPUT_DIR / "sensor-history-20261024" / f"{STATION}.csv"
RAW_FILES = (
    paths.GREENLAB_INTERVALS_DIR / f"{STATION}_HAIPHONG_20260726_to_20260801.csv",
    paths.GREENLAB_INTERVALS_DIR / f"{STATION}_HAIPHONG_20260807_to_20260813.csv",
    paths.GREENLAB_INTERVALS_DIR / f"{STATION}_HAIPHONG_20260912_to_20260918.csv",
)
CONTEXT_DIR = paths.EXPERIMENT_OUTPUT_DIR / "external-context-06M26042804-2026-05-28_2026-10-24"
SEA_LEVEL = CONTEXT_DIR / "sea_level_openmeteo_marine.csv"
ERA5_PRECIP = paths.HAZARD_DATA_DIR / "era5" / "openmeteo_era5_precip_nb1_1982_20261018.csv"
ERA5_WIND = paths.HAZARD_DATA_DIR / "era5" / "era5_nb1_1982_20261020.csv"
IBTRACS = paths.HAZARD_DATA_DIR / "ibtracs" / "ibtracs.last3years.list.v04r01.20261022.csv"
OC_DIR = paths.VN_PUBLIC_DIR / "cmems_oceancolour" / "derived"
OC_SERIES = {
    "SPM": OC_DIR / "oc_transp_4km__SPM__nb1_series.csv",
    "KD490": OC_DIR / "oc_transp_4km__KD490__nb1_series.csv",
    "CHL": OC_DIR / "oc_chl_4km__CHL__nb1_series.csv",
}
CMEMS_PHY = paths.CMEMS_DIR / "GLOBAL_ANALYSISFORECAST_PHY_001_024"
CMEMS_FILES = {
    "salinity_psu": CMEMS_PHY / "anfc_so_d__cmems_mod_glo_phy-so_anfc_0.083deg_P1D-m__so__106.8_20.55_107.35_20.95__20220601_20261022.nc",
    "sst_c": CMEMS_PHY / "anfc_thetao_d__cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m__thetao__106.8_20.55_107.35_20.95__20220601_20261022.nc",
}

# Event windows (local time).  E1 = the question; E2 = 12/08 (2.4 h gap, COD rail -> 0) and
# E3 = 16/09 (COD 0 -> in range together with an NH4 step) are other interventions, as contrast.
E1_SEARCH = ("2026-07-31 12:00", "2026-07-31 16:00")
E2_SEARCH = ("2026-08-12 15:00", "2026-08-12 21:00")
E3_SEARCH = ("2026-09-16 10:00", "2026-09-16 17:00")
PRE = ("2026-07-17 00:00", "2026-07-31 12:00")      # 14.5 days before E1
POST = ("2026-07-31 16:00", "2026-08-12 16:00")     # 12 days after E1, before E2
ENV_WINDOW = ("2026-07-17", "2026-08-14")
SAT_PRE = ("2026-06-15", "2026-07-30")
SAT_POST = ("2026-08-01", "2026-09-15")

# RIMF annual monitoring 2013, Cat Ba cage zones (Le Tuan Son et al. 2014, VJS 14(3):265-271,
# data/vn_public/rimf_farm_zones/vjs_2014_le-tuan-son_catba-cage-pollution.pdf, p. 268):
# N-NH4+ Ben Beo 1 0.103-0.133, Ben Beo 2 0.093-0.137, Tung Trang 0.089-0.146 mg/L; max 0.146.
RIMF_2013_N_NH4 = {"min": 0.089, "max": 0.146, "source": "Le Tuan Son et al. 2014 (RIMF 2013), p.268"}
QCVN_AMMONIUM = 0.1  # QCVN 10:2023 B1 / 10:2008 aquaculture, mg/L N


# ---------------------------------------------------------------------------------------------
# helpers (unit-tested in tests/test_nh4_step_0731.py)
# ---------------------------------------------------------------------------------------------

def detect_level_step(series: pd.Series, half_window: int = 10, log: bool = True) -> dict:
    """Locate the largest level shift in ``series`` (time-indexed, sorted).

    For each split k the score is |median(x[k-w:k]) - median(x[k:k+w])| (on log values when
    ``log``); the split with the largest score wins.  Returns the first sample of the new level,
    the last sample of the old level, both local medians and the multiplicative ratio
    before/after (``log``) or the difference (linear).
    """
    s = series.dropna()
    s = s[s > 0] if log else s
    n = len(s)
    if n < 2 * half_window + 1:
        raise ValueError("series too short for the requested half_window")
    x = np.log(s.to_numpy(dtype=float)) if log else s.to_numpy(dtype=float)
    ks = np.arange(half_window, n - half_window + 1)
    scores = np.array([abs(np.median(x[k - half_window:k]) - np.median(x[k:k + half_window])) for k in ks])
    best = float(scores.max())
    # medians plateau over several splits around a clean step: among near-best splits take the
    # one with the largest single-sample jump, i.e. the actual step sample
    near = ks[scores >= 0.95 * best]
    best_k = int(near[np.argmax(np.abs(x[near] - x[near - 1]))])
    before = float(np.median(s.iloc[best_k - half_window:best_k]))
    after = float(np.median(s.iloc[best_k:best_k + half_window]))
    return {
        "last_old_sample": s.index[best_k - 1],
        "first_new_sample": s.index[best_k],
        "before_median": before,
        "after_median": after,
        "ratio_before_over_after": before / after if log else float("nan"),
        "difference_after_minus_before": after - before,
        "score": float(best),
    }


def step_factor(before: pd.Series, after: pd.Series) -> float:
    """Multiplicative factor between two positive samples: exp(median log before - median log after)."""
    b = np.log(before[before > 0].to_numpy(dtype=float))
    a = np.log(after[after > 0].to_numpy(dtype=float))
    return float(math.exp(np.median(b) - np.median(a)))


def relative_spread(x: pd.Series) -> float:
    """(p95 - p5) / median - scale-free spread."""
    x = x.dropna()
    med = x.median()
    return float((x.quantile(0.95) - x.quantile(0.05)) / med) if med else float("nan")


def cycle_profile(series: pd.Series, period_min: int = 30) -> pd.DataFrame:
    """Mean and mean-absolute 1-sample change by minute-of-cycle (minute of hour mod ``period_min``).

    An instrument self-cleaning / measurement cycle shows up as one or two cycle minutes with a
    much larger mean change than the rest.
    """
    s = series.dropna().sort_index()
    d = s.diff()
    d = d[(s.index.to_series().diff() <= pd.Timedelta(minutes=2)).to_numpy()]
    minute = pd.Index(d.index.minute % period_min, name="cycle_minute")
    out = pd.DataFrame({"mean_change": d.groupby(minute).mean(), "mean_abs_change": d.abs().groupby(minute).mean(),
                        "n": d.groupby(minute).size()})
    base = out["mean_abs_change"].mean()
    out["abs_change_vs_mean"] = out["mean_abs_change"] / base if base else np.nan
    return out.reset_index()


def upward_jumps(series: pd.Series, threshold: float) -> list[pd.Timestamp]:
    """Timestamps where the series rises by >= ``threshold`` in one sample (instrument-cycle marks)."""
    s = series.dropna().sort_index()
    d = s.diff()
    return list(d.index[d >= threshold])


def event_scan(hist: pd.DataFrame, ratio: float = 3.0, gap_min: float = 60.0) -> pd.DataFrame:
    """Days with instrument-like changes: NH4 daily median x/÷ >= ``ratio`` vs previous day,
    COD state change (rail 558.8 / stuck 0 / in range), or a data gap >= ``gap_min`` minutes."""
    g = hist.groupby(hist.index.date)
    med = g["NH4"].median()
    cod = g["COD"].median().map(lambda v: "rail" if v >= 550 else ("zero" if v == 0 else "in_range"))
    gap = g.apply(lambda f: max_gap(f.index).total_seconds() / 60)
    r = med / med.shift(1)
    rows = []
    for day in med.index[1:]:
        reasons = []
        if r[day] >= ratio or r[day] <= 1 / ratio:
            reasons.append(f"NH4 x{r[day]:.2f}")
        if cod[day] != cod.shift(1)[day]:
            reasons.append(f"COD {cod.shift(1)[day]}->{cod[day]}")
        if gap[day] >= gap_min:
            reasons.append(f"gap {gap[day]:.0f} min")
        if reasons:
            rows.append({"local_date": str(day), "nh4_median": med[day], "nh4_ratio_vs_prev_day": r[day],
                         "cod_state": cod[day], "max_gap_min": gap[day], "reasons": "; ".join(reasons)})
    return pd.DataFrame(rows)


def max_gap(index: pd.DatetimeIndex) -> pd.Timedelta:
    if len(index) < 2:
        return pd.Timedelta(0)
    return index.to_series().diff().max()


def haversine_km(lat1, lon1, lat2, lon2):
    r = np.radians
    a = np.sin(r(np.asarray(lat2) - lat1) / 2) ** 2 + np.cos(r(lat1)) * np.cos(r(np.asarray(lat2))) * np.sin(r(np.asarray(lon2) - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------------------------
# loaders
# ---------------------------------------------------------------------------------------------

def load_history() -> pd.DataFrame:
    raw = pd.read_csv(HISTORY)
    raw = raw[raw["device"].astype(str).eq(STATION)]
    t = pd.to_datetime(raw["fetchedAt"], utc=True).dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)
    frame = raw.assign(t=t).groupby("t")[list(VARS)].median().sort_index()
    return frame


def load_raw() -> pd.DataFrame:
    """Long-format interval exports (naive local time, ~2 readings per minute)."""
    parts = []
    for path in RAW_FILES:
        df = pd.read_csv(path)
        df = df[df["DeviceSerialNumber"].astype(str).eq(STATION)]
        parts.append(df)
    raw = pd.concat(parts, ignore_index=True).drop_duplicates()
    raw["SensorType"] = raw["SensorType"].replace(RAW_NAME)
    raw["Date"] = pd.to_datetime(raw["Date"])
    grp = raw.groupby(["Date", "SensorType"])
    raw["seq"] = grp.cumcount()
    raw["per_min"] = grp["Value"].transform("size")
    # k readings in the same minute -> spread them evenly over the minute (order as exported)
    raw["t"] = raw["Date"] + pd.to_timedelta(raw["seq"] * 60.0 / raw["per_min"], unit="s")
    return raw


def raw_series(raw: pd.DataFrame, var: str, start: str, end: str) -> pd.Series:
    sub = raw[(raw["SensorType"] == var) & (raw["t"] >= start) & (raw["t"] <= end)]
    return sub.set_index("t")["Value"].astype(float).sort_index()


def load_hourly(path: Path, col: str) -> pd.Series:
    df = pd.read_csv(path)
    tcol = df.columns[0]
    t = pd.to_datetime(df[tcol], utc=True).dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)
    return pd.Series(df[col].to_numpy(dtype=float), index=t, name=col).sort_index()


def cmems_point(path: Path, var: str) -> tuple[pd.Series, dict]:
    import xarray as xr

    with xr.open_dataset(path) as ds:
        da = ds[var].isel(depth=0)
        lats, lons = ds["latitude"].to_numpy(), ds["longitude"].to_numpy()
        valid = da.sel(time="2026-07-31").notnull().to_numpy().squeeze()
        la, lo = np.meshgrid(lats, lons, indexing="ij")
        dist = haversine_km(NB1_LAT, NB1_LON, la, lo)
        dist = np.where(valid, dist, np.inf)
        i, j = np.unravel_index(int(np.argmin(dist)), dist.shape)
        series = da.isel(latitude=i, longitude=j).to_series()
    series.index = pd.to_datetime(series.index)
    return series.astype(float), {"lat": float(lats[i]), "lon": float(lons[j]), "dist_km": float(dist[i, j])}


def storms_near(start: str, end: str) -> pd.DataFrame:
    d = pd.read_csv(IBTRACS, skiprows=[1], low_memory=False, usecols=["SID", "NAME", "ISO_TIME", "LAT", "LON"])
    d["ISO_TIME"] = pd.to_datetime(d["ISO_TIME"])
    d = d[(d["ISO_TIME"] >= start) & (d["ISO_TIME"] <= end)].copy()
    d["LAT"] = pd.to_numeric(d["LAT"], errors="coerce")
    d["LON"] = pd.to_numeric(d["LON"], errors="coerce")
    d["dist_km"] = haversine_km(NB1_LAT, NB1_LON, d["LAT"], d["LON"])
    idx = d.groupby("SID")["dist_km"].idxmin()
    out = d.loc[idx, ["SID", "NAME", "ISO_TIME", "LAT", "LON", "dist_km"]].rename(columns={"ISO_TIME": "closest_time_utc"})
    return out.sort_values("dist_km").reset_index(drop=True)


# ---------------------------------------------------------------------------------------------
# analyses
# ---------------------------------------------------------------------------------------------

def anatomy(raw: pd.DataFrame, window: tuple[str, str], label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, frames = [], []
    for var in VARS:
        s = raw_series(raw, var, *window)
        frames.append(s.rename(var))
        row = {"event": label, "variable": var, "n": len(s), "max_gap_min": max_gap(s.index).total_seconds() / 60,
               "max_identical_run": int(s.groupby((s != s.shift()).cumsum()).size().max()) if len(s) else 0}
        if len(s) > 1:
            gaps = s.index.to_series().diff()
            g_end = gaps.idxmax()
            row["max_gap_start"] = str(s.index[s.index.get_loc(g_end) - 1])
            row["max_gap_end"] = str(g_end)
        positive = (s > 0).mean() > 0.9
        if positive and len(s) > 1:
            jumps = np.log(s).diff().abs()
            row["largest_single_jump_at"] = str(jumps.idxmax())
            row["largest_single_jump_from"] = float(s.shift(1).loc[jumps.idxmax()])
            row["largest_single_jump_to"] = float(s.loc[jumps.idxmax()])
        try:
            st = detect_level_step(s, half_window=10, log=positive)
            row.update({k: (str(v) if isinstance(v, pd.Timestamp) else v) for k, v in st.items()})
            row["log_scale"] = positive
        except ValueError:
            pass
        rows.append(row)
    return pd.DataFrame(rows), pd.concat(frames, axis=1)


def signal_character(hist: pd.DataFrame, sea: pd.Series) -> pd.DataFrame:
    rows = []
    for name, (a, b) in {"pre": PRE, "post": POST}.items():
        w = hist.loc[a:b]
        for var in VARS:
            x = w[var].dropna()
            row = {"window": name, "start": a, "end": b, "variable": var, "n": len(x), "median": x.median(),
                   "p05": x.quantile(.05), "p95": x.quantile(.95), "relative_spread": relative_spread(x)}
            pos = x[x > 0]
            if len(pos) > 0.9 * len(x) and var != "COD":
                lx = np.log(pos)
                d1 = lx.diff()[pos.index.to_series().diff() <= pd.Timedelta(minutes=1)]
                row["log_sd"] = lx.std()
                row["minute_noise_log_mad"] = float((d1 - d1.median()).abs().median() * 1.4826)
                hourly = lx.resample("1h").median()
                anom = hourly - hourly.rolling(25, center=True, min_periods=12).median()
                row["hour_lag1_autocorr_anom"] = anom.autocorr(1)
                sl = sea.reindex(anom.index)
                ok = anom.notna() & sl.notna()
                row["corr_anom_sea_level"] = float(np.corrcoef(anom[ok], sl[ok])[0, 1]) if ok.sum() > 48 else np.nan
                prof = anom.groupby(anom.index.hour).mean()
                row["diurnal_amplitude_log"] = float(prof.max() - prof.min())
                row["diurnal_peak_hour"] = int(prof.idxmax())
                vals = np.unique(np.round(pos.to_numpy(), 4))
                steps = np.diff(vals)
                row["min_value_step"] = float(steps[steps > 0].min()) if (steps > 0).any() else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def daily_table(hist: pd.DataFrame) -> pd.DataFrame:
    g = hist.groupby(hist.index.date)
    out = pd.DataFrame({
        "n": g["NH4"].size(),
        "nh4_raw_median": g["NH4"].median(),
        "tan_mg_l_median": g["NH4"].median() * NH4_UNIT_SCALE * NH4_TO_N_FACTOR,
        "nh4_log_sd": g["NH4"].apply(lambda x: np.log(x[x > 0]).std()),
        "tss_median": g["TSS"].median(),
        "tss_p95": g["TSS"].quantile(.95),
        "ph_median": g["pH"].median(),
        "temp_median": g["Temperature"].median(),
        "temp_daily_range_p98_p2": g["Temperature"].quantile(.98) - g["Temperature"].quantile(.02),
        "cod_median": g["COD"].median(),
        "max_gap_min": g.apply(lambda f: max_gap(f.index).total_seconds() / 60),
    })
    out.index.name = "local_date"
    return out


def environment(hist_index: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    a, b = ENV_WINDOW
    precip = load_hourly(ERA5_PRECIP, "precipitation")
    wind = load_hourly(ERA5_WIND, "wind_speed_10m")
    air = load_hourly(ERA5_WIND, "temperature_2m")
    sea = load_hourly(SEA_LEVEL, "sea_level_m")
    daily = pd.DataFrame({
        "precip_mm": precip.loc[a:b].resample("D").sum(),
        "wind_mean": wind.loc[a:b].resample("D").mean(),
        "air_temp_mean_c": air.loc[a:b].resample("D").mean(),
        "sea_level_range_m": sea.loc[a:b].resample("D").max() - sea.loc[a:b].resample("D").min(),
    })
    meta = {}
    for col, path in CMEMS_FILES.items():
        var = "so" if col.startswith("salinity") else "thetao"
        s, cell = cmems_point(path, var)
        daily[col] = s.reindex(daily.index)
        meta[col] = cell
    sat = {}
    for var, path in OC_SERIES.items():
        df = pd.read_csv(path, parse_dates=["date"]).set_index("date")[var].dropna()
        daily[f"sat_{var}"] = df.reindex(daily.index)
        sat[var] = {"pre_median": float(df.loc[SAT_PRE[0]:SAT_PRE[1]].median()), "pre_n": int(df.loc[SAT_PRE[0]:SAT_PRE[1]].size),
                    "post_median": float(df.loc[SAT_POST[0]:SAT_POST[1]].median()), "post_n": int(df.loc[SAT_POST[0]:SAT_POST[1]].size),
                    "last_before_step": str(df.loc[:"2026-07-31"].index.max().date()),
                    "first_after_step": str(df.loc["2026-08-01":].index.min().date())}
    meta["satellite"] = sat
    hourly = pd.DataFrame({"precip_mm": precip, "wind_ms": wind, "sea_level_m": sea}).loc["2026-07-31 06:00":"2026-07-31 20:00"]
    meta["sea_level_series"] = sea
    return daily, hourly, meta


def plausibility(hist: pd.DataFrame, sat_meta: dict) -> pd.DataFrame:
    hp = pd.read_csv(paths.clean_data("haiphong"))
    qn = pd.read_csv(paths.clean_data("quangninh"))
    hp_aug = hp[pd.to_datetime(hp["Quarter"]).dt.month.isin([6, 8])]
    pre = hist.loc[PRE[0]:PRE[1]]
    post = hist.loc[POST[0]:POST[1]]
    tan = lambda s: s * NH4_UNIT_SCALE * NH4_TO_N_FACTOR  # noqa: E731
    rows = []

    def add(var, source, x=None, **kw):
        row = {"variable": var, "source": source}
        if x is not None:
            x = pd.Series(x).dropna()
            row.update({"n": len(x), "p01": x.quantile(.01), "p05": x.quantile(.05), "median": x.median(),
                        "p95": x.quantile(.95), "min": x.min(), "max": x.max()})
        row.update(kw)
        rows.append(row)

    add("ammonium_TAN_mg_l", "sensor pre-step (17-31/07)", tan(pre["NH4"]))
    add("ammonium_TAN_mg_l", "sensor post-step (31/07-12/08)", tan(post["NH4"]))
    add("ammonium_TAN_mg_l", "sensor mid-Sep (10-16/09)", tan(hist.loc["2026-09-10":"2026-09-16", "NH4"]))
    add("ammonium_TAN_mg_l", "HP provincial, all quarters 2020-2024", hp["NH3"])
    add("ammonium_TAN_mg_l", "HP provincial, Jun+Aug quarters", hp_aug["NH3"])
    add("ammonium_TAN_mg_l", "QN provincial, all quarters 2021-2024", qn["NH3"])
    add("ammonium_TAN_mg_l", "RIMF 2013 Cat Ba cage zones (range)", min=RIMF_2013_N_NH4["min"], max=RIMF_2013_N_NH4["max"],
        note=RIMF_2013_N_NH4["source"])
    add("ammonium_TAN_mg_l", "QCVN 10:2023 B1 limit", median=QCVN_AMMONIUM)
    add("TSS_mg_l", "sensor pre-step (17-31/07)", pre["TSS"])
    add("TSS_mg_l", "sensor post-step (31/07-12/08)", post["TSS"])
    add("TSS_mg_l", "HP provincial, all quarters", hp["TSS"])
    add("TSS_mg_l", "QN provincial, all quarters", qn["TSS"])
    for key in ("pre", "post"):
        m = sat_meta["SPM"]
        add("TSS_mg_l", f"satellite SPM 4 km ({key}: {SAT_PRE if key == 'pre' else SAT_POST})",
            median=m[f"{key}_median"], n=m[f"{key}_n"], note="g/m3 = mg/L, surface optical, daily cloud-free only")
    out = pd.DataFrame(rows)
    hp_p01 = hp["NH3"].quantile(.01)
    qn_p01 = qn["NH3"].quantile(.01)
    out.attrs.update({"hp_p01": hp_p01, "qn_p01": qn_p01, "hp_min": hp["NH3"].min(), "hp_tss_max": hp["TSS"].max(),
                      "qn_tss_p95": qn["TSS"].quantile(.95)})
    return out


# ---------------------------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------------------------
PRE_C, POST_C, REF_C, EVENT_C = "#2a78d6", "#eb6834", "#8a8984", "#52514e"


def _style(ax):
    ax.grid(True, color="#e6e5e0", lw=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def fig_step_window(win: pd.DataFrame, step_t: pd.Timestamp, out: Path, title: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    fig, axes = plt.subplots(5, 1, figsize=(10, 10), sharex=True)
    for ax, var in zip(axes, ("NH4", "TSS", "pH", "Temperature", "COD")):
        s = win[var].dropna()
        ax.plot(s.index, s.to_numpy(), lw=1.0, color=PRE_C, marker="o", ms=1.5)
        if var in ("NH4", "TSS"):
            ax.set_yscale("log")
        ax.axvline(step_t, color=EVENT_C, lw=1, ls="--")
        ax.set_ylabel(var + (" (log)" if var in ("NH4", "TSS") else ""))
        _style(ax)
    axes[0].set_title(title, loc="left", fontsize=11)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def fig_timeline(daily: pd.DataFrame, plaus: pd.DataFrame, out: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    idx = pd.to_datetime(daily.index)
    e1, e2, e3 = pd.Timestamp("2026-07-31"), pd.Timestamp("2026-08-12"), pd.Timestamp("2026-09-16")
    fig, axes = plt.subplots(5, 1, figsize=(10, 11), sharex=True)
    hp = plaus[(plaus.variable == "ammonium_TAN_mg_l") & (plaus.source == "HP provincial, all quarters 2020-2024")].iloc[0]
    ax = axes[0]
    ax.axhspan(hp["p05"], hp["p95"], color=REF_C, alpha=0.18, lw=0, label="HP tỉnh p5–p95 (TAN)")
    ax.axhline(QCVN_AMMONIUM, color=EVENT_C, lw=1, ls=":", label="QCVN 0,1 mg/L")
    ax.plot(idx, daily["tan_mg_l_median"], color=PRE_C, lw=1.6, label="cảm biến (TAN, trung vị ngày)")
    ax.set_yscale("log"); ax.set_ylabel("Amoni TAN mg/L")
    ax.legend(fontsize=8, loc="lower left")
    ax = axes[1]
    hpt = plaus[(plaus.variable == "TSS_mg_l") & (plaus.source == "HP provincial, all quarters")].iloc[0]
    ax.axhspan(hpt["p05"], hpt["p95"], color=REF_C, alpha=0.18, lw=0, label="HP tỉnh p5–p95")
    ax.plot(idx, daily["tss_median"], color=PRE_C, lw=1.6, label="cảm biến (trung vị ngày)")
    ax.set_yscale("log"); ax.set_ylabel("TSS mg/L"); ax.legend(fontsize=8, loc="lower left")
    axes[2].plot(idx, daily["ph_median"], color=PRE_C, lw=1.6); axes[2].set_ylabel("pH (trung vị)")
    axes[3].plot(idx, daily["temp_daily_range_p98_p2"], color=PRE_C, lw=1.6); axes[3].set_ylabel("Biên độ nhiệt ngày °C")
    axes[4].plot(idx, daily["nh4_log_sd"], color=PRE_C, lw=1.6); axes[4].set_ylabel("SD log NH4 trong ngày")
    for ax in axes:
        ax.axvline(e1, color=EVENT_C, lw=1, ls="--")
        ax.axvline(e2, color=EVENT_C, lw=1, ls=":")
        ax.axvline(e3, color=EVENT_C, lw=1, ls=":")
        _style(ax)
    axes[0].set_title("NB1 theo ngày: bước 31/07 14:06 (gạch); can thiệp 12/08 và 16/09 (chấm)", loc="left", fontsize=11)
    fig.tight_layout(); fig.savefig(out, dpi=130); plt.close(fig)


def fig_distributions(hist: pd.DataFrame, factor: float, plaus: pd.DataFrame, out: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pre = hist.loc[PRE[0]:PRE[1]]
    post = hist.loc[POST[0]:POST[1]]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    ax = axes[0]
    bins = np.logspace(np.log10(3e-3), np.log10(0.3), 70)
    scale = NH4_UNIT_SCALE * NH4_TO_N_FACTOR
    ax.hist(pre["NH4"] * scale, bins=bins, color=PRE_C, alpha=0.75, label="trước bậc")
    ax.hist(post["NH4"] * scale, bins=bins, color=POST_C, alpha=0.75, label="sau bậc")
    ax.hist(post["NH4"] * scale * factor, bins=bins, histtype="step", color=POST_C, lw=1.4, ls="--",
            label=f"sau bậc × {factor:.1f}")
    for src, ls in (("HP provincial, all quarters 2020-2024", "-"), ("QN provincial, all quarters 2021-2024", "--")):
        r = plaus[(plaus.variable == "ammonium_TAN_mg_l") & (plaus.source == src)].iloc[0]
        ax.axvline(r["p01"], color=REF_C, ls=ls, lw=1)
    ax.axvline(QCVN_AMMONIUM, color=EVENT_C, ls=":", lw=1)
    ax.axvspan(RIMF_2013_N_NH4["min"], RIMF_2013_N_NH4["max"], color=REF_C, alpha=0.18, lw=0, label="RIMF 2013 lồng Cát Bà")
    ax.set_xscale("log"); ax.set_xlabel("Amoni TAN mg/L (log); xám: p1 tỉnh HP (liền) / QN (gạch); chấm: QCVN")
    ax.set_ylabel("số phút"); ax.legend(fontsize=8); _style(ax)
    ax = axes[1]
    bins = np.logspace(0, np.log10(500), 70)
    ax.hist(pre["TSS"], bins=bins, color=PRE_C, alpha=0.75, label="trước bậc")
    ax.hist(post["TSS"], bins=bins, color=POST_C, alpha=0.75, label="sau bậc")
    hpt = plaus[(plaus.variable == "TSS_mg_l") & (plaus.source == "HP provincial, all quarters")].iloc[0]
    ax.axvspan(hpt["min"], hpt["max"], color=REF_C, alpha=0.18, lw=0, label="HP tỉnh min–max")
    for key, ls in (("pre", "-"), ("post", "--")):
        r = plaus[(plaus.variable == "TSS_mg_l") & plaus.source.str.startswith(f"satellite SPM 4 km ({key}")].iloc[0]
        ax.axvline(r["median"], color=EVENT_C, ls=ls, lw=1)
    ax.set_xscale("log"); ax.set_xlabel("TSS mg/L (log); đen: SPM vệ tinh trung vị trước (liền) / sau (gạch)")
    ax.legend(fontsize=8); _style(ax)
    fig.suptitle("Phân bố trước (17–31/07) và sau (31/07–12/08) bậc so với nền", x=0.01, ha="left", fontsize=11)
    fig.tight_layout(); fig.savefig(out, dpi=130); plt.close(fig)


def fig_environment(env_daily: pd.DataFrame, sea: pd.Series, hist: pd.DataFrame, out: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    a, b = ENV_WINDOW
    step = pd.Timestamp("2026-07-31 14:06")
    fig, axes = plt.subplots(6, 1, figsize=(10, 12), sharex=True)
    idx = env_daily.index
    axes[0].bar(idx, env_daily["precip_mm"], width=0.8, color=PRE_C); axes[0].set_ylabel("Mưa ERA5 mm/ngày")
    axes[1].plot(idx, env_daily["wind_mean"], color=PRE_C, lw=1.6); axes[1].set_ylabel("Gió 10 m TB ngày")
    s = sea.loc[a:b]
    axes[2].plot(s.index, s.to_numpy(), color=PRE_C, lw=0.8); axes[2].set_ylabel("Mực nước mô hình m")
    axes[3].plot(idx, env_daily["salinity_psu"], color=PRE_C, lw=1.6); axes[3].set_ylabel("Độ mặn GLO12 psu")
    sat = env_daily["sat_SPM"].dropna()
    axes[4].plot(sat.index, sat.to_numpy(), "o", color=PRE_C, ms=5, label="SPM vệ tinh 4 km")
    axes[4].set_ylabel("SPM / TSS mg/L")
    tss = hist.loc[a:b, "TSS"].resample("D").median()
    axes[4].plot(tss.index, tss.to_numpy(), color=POST_C, lw=1.4, label="TSS cảm biến (trung vị ngày)")
    axes[4].set_yscale("log"); axes[4].legend(fontsize=8)
    nh4 = hist.loc[a:b, "NH4"].resample("1h").median()
    axes[5].plot(nh4.index, nh4.to_numpy(), color=PRE_C, lw=1.0); axes[5].set_yscale("log"); axes[5].set_ylabel("NH4 thô (log)")
    for ax in axes:
        ax.axvline(step, color=EVENT_C, lw=1, ls="--")
        _style(ax)
    axes[0].set_title("Môi trường quanh 31/07 — không có tác nhân vật lý trùng thời điểm bậc", loc="left", fontsize=11)
    fig.tight_layout(); fig.savefig(out, dpi=130); plt.close(fig)


def fig_signature(hist: pd.DataFrame, sea: pd.Series, out: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, var in zip(axes, ("NH4", "TSS")):
        for name, (a, b), c in (("trước", PRE, PRE_C), ("sau", POST, POST_C)):
            x = hist.loc[a:b, var]
            lx = np.log(x[x > 0]).resample("1h").median()
            anom = lx - lx.rolling(25, center=True, min_periods=12).median()
            prof = anom.groupby(anom.index.hour).mean()
            ax.plot(prof.index, prof.to_numpy(), color=c, lw=2, marker="o", ms=4, label=name)
        ax.axhline(0, color=REF_C, lw=0.8)
        ax.set_xlabel("giờ địa phương"); ax.set_ylabel(f"dị thường log {var} (TB theo giờ)")
        ax.set_title(f"{var}: chu kỳ ngày tương đối", loc="left", fontsize=10)
        ax.legend(fontsize=8); _style(ax)
    fig.tight_layout(); fig.savefig(out, dpi=130); plt.close(fig)


# ---------------------------------------------------------------------------------------------

def make_figures(win1, win2, win3, an2, an3, step_t, daily, plaus, factor, env_daily, sea, hist, out: Path) -> None:
    fig_step_window(win1, step_t, out / "fig_step_window_20260731.png",
                    "NB1 31/07 12:00–16:00, dữ liệu thô 2 lần/phút (gạch: mẫu đầu của mức NH4 mới)")
    e2_t = pd.Timestamp(an2.set_index("variable").loc["COD", "first_new_sample"])
    fig_step_window(win2, e2_t, out / "fig_step_window_20260812.png",
                    "NB1 12/08 15:00–21:00 (đối chứng: mất dữ liệu 2,4 h, COD 558,8 → 0)")
    e3_t = pd.Timestamp(an3.set_index("variable").loc["NH4", "first_new_sample"])
    fig_step_window(win3, e3_t, out / "fig_step_window_20260916.png",
                    "NB1 16/09 10:00–17:00 (đối chứng: NH4 và COD cùng đổi mức, không mất dữ liệu)")
    fig_timeline(daily, plaus, out / "fig_timeline_daily.png")
    fig_distributions(hist, factor, plaus, out / "fig_distributions_pre_post.png")
    fig_environment(env_daily, sea, hist, out / "fig_environment.png")
    fig_signature(hist, sea, out / "fig_diurnal_signature.png")


def _f(x, nd=3) -> str:
    """Vietnamese decimal comma."""
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "–"
    return f"{x:.{nd}f}".replace(".", ",")


def write_notes(out: Path, *, an: pd.DataFrame, factor: float, tss_first_low: tuple, bumps: list, sig: pd.DataFrame,
                env_daily: pd.DataFrame, env_hourly: pd.DataFrame, env_meta: dict, storms: pd.DataFrame,
                plaus: pd.DataFrame, events: pd.DataFrame, daily: pd.DataFrame) -> None:
    a = an.set_index(["event", "variable"])
    e1n = a.loc[("E1_2026-07-31", "NH4")]
    e3 = {v: a.loc[("E3_2026-09-16", v)] for v in ("NH4", "pH", "COD", "TSS")}
    e2c = a.loc[("E2_2026-08-12", "COD")]
    sg = sig.set_index(["window", "variable"])
    pl = plaus.set_index(["variable", "source"])
    tan = lambda src: pl.loc[("ammonium_TAN_mg_l", src)]  # noqa: E731
    tssr = lambda src: pl.loc[("TSS_mg_l", src)]  # noqa: E731
    pre_t, post_t, sep_t = tan("sensor pre-step (17-31/07)"), tan("sensor post-step (31/07-12/08)"), tan("sensor mid-Sep (10-16/09)")
    hp, hp_aug, qn = tan("HP provincial, all quarters 2020-2024"), tan("HP provincial, Jun+Aug quarters"), tan("QN provincial, all quarters 2021-2024")
    pre_s, post_s = tssr("sensor pre-step (17-31/07)"), tssr("sensor post-step (31/07-12/08)")
    hp_s, qn_s = tssr("HP provincial, all quarters"), tssr("QN provincial, all quarters")
    sat = env_meta["satellite"]
    ed = env_daily
    d = lambda day, col: ed.loc[pd.Timestamp(day), col]  # noqa: E731
    h14 = env_hourly.loc[pd.Timestamp("2026-07-31 14:00")]
    h13 = env_hourly.loc[pd.Timestamp("2026-07-31 13:00")]
    storm = storms.iloc[0]
    sal = env_meta["salinity_psu"]
    first_week = pd.to_datetime(pd.Series(daily.index, index=daily.index))
    jan = daily.loc[((first_week >= "2026-05-30") & (first_week <= "2026-06-05")).to_numpy(), "tss_median"]

    def sig_row(var, label):
        p, q = sg.loc[("pre", var)], sg.loc[("post", var)]
        return (f"| {label} | {_f(p['median'], 2)} → {_f(q['median'], 2)} | {_f(p['relative_spread'], 2)} → {_f(q['relative_spread'], 2)} "
                f"| {_f(p['minute_noise_log_mad'], 4)} → {_f(q['minute_noise_log_mad'], 4)} "
                f"| {_f(p['corr_anom_sea_level'], 2)} → {_f(q['corr_anom_sea_level'], 2)} "
                f"| {_f(p['diurnal_amplitude_log'], 3)} → {_f(q['diurnal_amplitude_log'], 3)} "
                f"| {_f(p['hour_lag1_autocorr_anom'], 2)} → {_f(q['hour_lag1_autocorr_anom'], 2)} |")

    ev_lines = "\n".join(f"| {r.local_date} | {r.reasons} |" for r in events.itertuples())
    text = f"""# nh4-step-0731-20261026 — Bước nhảy NH4 / TSS ngày 31/07/2026 tại NB1 (06M26042804)

Script: `experiments/nh4_step_0731.py` (chỉ đọc; đầu vào và sha256 trong `manifest.json`). Giờ địa phương (UTC+7).

## Câu hỏi

Ngày 31/07/2026 khoảng 14:06, NH4 cảm biến NB1 tụt một bậc ~÷20 và TSS ~70 → 3–4 mg/L, còn nhiệt độ và pH
không đổi (RL-58, RL-69). Đây là thay đổi thật của nước hay thay đổi của thiết bị (bảo dưỡng / vệ sinh /
hiệu chuẩn / thay đầu dò / đổi thang đo / firmware / dời vị trí)? Với nuôi trồng, trạng thái sau bậc tốt hơn,
xấu hơn, hay chỉ là sai số đo?

## Bằng chứng

- Dữ liệu thô GreenLab (`intervals/…20260726_to_20260801`, `…20260807_to_20260813`, `…20260912_to_20260918`;
  2 bản ghi / phút, cột Status) và lịch sử đóng băng `sensor-history-20261024` (trung vị theo phút).
- Môi trường: mưa / gió ERA5 tại NB1, mực nước mô hình (Open-Meteo marine), CMEMS GLO12 độ mặn / nhiệt độ mặt
  (ô biển gần nhất cách {_f(sal['dist_km'], 1)} km), CMEMS ocean colour SPM / KD490 / CHL (ô 4 km cách 2,3 km), IBTrACS.
- Nền: quan trắc tỉnh HP (14 điểm Cát Bà / Lạch Huyện, 2020–2024) và QN (99 điểm, 2021–2024), cột "NH3" = amoni
  tổng theo N (RL-69); RIMF 2013 vùng lồng Cát Bà (Lê Tuấn Sơn và nnk 2014, tr. 268); SPM vệ tinh.
- Web (công khai): không tìm thấy thông báo bảo dưỡng trạm GreenLab / ĐH Thái Bình, cũng không có tin sự cố môi
  trường ở Cát Bà cuối 07 – đầu 08/2026. Tin gần nhất: cá lồng chết ở Phù Long (Tiền Phong 10/07/2026, cuối 06 –
  đầu 07, nghi nước thải trại tôm) — sai thời điểm và cách NB1 > 10 km; chỉ ghi làm ứng viên sự kiện cho RL-56.
- Nhà cung cấp chưa trả lời; hệ thống ghi đơn vị NH4 là "mg/L" (Status "Good" cả trước và sau bậc).

## Kết quả

### 1. Giải phẫu bước nhảy (dữ liệu thô)

- **NH4:** mẫu cuối mức cũ {e1n['last_old_sample']} = {_f(e1n['largest_single_jump_from'], 2)}, mẫu đầu mức mới
  {e1n['first_new_sample']} = {_f(e1n['largest_single_jump_to'], 2)}: đổi mức trong **một mẫu (≤ 30 s)**, không có giá trị trung gian,
  không quá độ. Tỉ số trung vị 5 phút hai bên {_f(e1n['ratio_before_over_after'], 2)}; trung vị 24 h hai bên {_f(factor, 2)}.
- **TSS:** mẫu thấp đầu tiên {tss_first_low[0]} ({_f(tss_first_low[1], 1)} → {_f(tss_first_low[2], 1)} mg/L), tức ~1 phút sau NH4; sau đó
  lắng xuống 4–5 mg/L lúc ~14:15. Trước bậc TSS rất nhiễu (đỉnh 150–500 mg/L từng đợt 1–2 h, cũng có các ngày 29–30/07).
- **pH, nhiệt độ, COD:** không đổi mức (COD vẫn kẹt 558,8). Nhiệt độ 14:06–14:15 vẫn 30,4–30,8 °C trong khi không khí
  ~27 °C → đầu dò không bị kéo lên khỏi nước lâu. Khoảng trống dữ liệu lớn nhất trong 12:00–16:00 là 1 phút.
- **Chu kỳ thiết bị 30 phút:** pH tăng ≥ 0,02 trong một mẫu đúng lúc {', '.join(str(t)[11:16] for t in bumps)} (phút :14 / :44,
  có hai bản ghi trùng ở :12–:13 / :42–:43) — chu kỳ tự làm sạch / đo của sonde, chạy liên tục qua bậc.
  Bậc 14:06 **không** nằm trên chu kỳ này → không phải thao tác tự động định kỳ.
- **Đối chứng 16/09 (E3, chắc chắn là can thiệp vì COD "sống lại"):** pH đổi mức lúc {e3['pH']['first_new_sample']},
  NH4 {e3['NH4']['first_new_sample']} ({_f(e3['NH4']['before_median'], 2)} → {_f(e3['NH4']['after_median'], 2)}, ×{_f(1 / e3['NH4']['ratio_before_over_after'], 1)}),
  COD {e3['COD']['first_new_sample']} (0 → {_f(e3['COD']['after_median'], 1)}), TSS dao động từ ~16:15; không mất dữ liệu.
  Cùng kiểu với 31/07: nhiều đầu dò đổi mức trong vài phút, giờ hành chính, không có khoảng trống.
- **Đối chứng 12/08 (E2):** mất dữ liệu {_f(e2c['max_gap_min'], 0)} phút ({e2c['max_gap_start'][11:16]}–{e2c['max_gap_end'][11:16]}), sau đó COD 558,8 → 0,0
  và nhiễu NH4 ×~20 ở cùng mức trung vị (`daily_sensor.csv`, `fig_step_window_20260812.png`).
- **Quét toàn chuỗi (`instrument_event_scan.csv`):**

| Ngày | Dấu hiệu |
| --- | --- |
{ev_lines}

  (31/07 hiện ở dòng 01/08 vì quét theo trung vị ngày.) Sau 31/07, NH4 không còn bậc ≥ ×3 trong một ngày ngoài 16–17/09,
  nhưng **trôi dần** từ {_f(daily.loc[pd.Timestamp('2026-08-01').date(), 'nh4_raw_median'], 2)} (01/08) xuống ~0,24 (giữa 09), rồi lên 2–10 (10/2026) cùng lúc pH trôi xuống ~6,9.

### 2. Đặc tính tín hiệu trước (17–31/07 12:00) → sau (31/07 16:00 – 12/08 16:00)

| Biến | Trung vị | (p95−p5)/trung vị | Nhiễu phút (MAD Δlog) | r(dị thường giờ, mực nước) | Biên độ ngày (log) | Tự tương quan giờ |
| --- | --- | --- | --- | --- | --- | --- |
{sig_row('NH4', 'NH4 thô')}
{sig_row('TSS', 'TSS mg/L')}
{sig_row('pH', 'pH')}
{sig_row('Temperature', 'Nhiệt độ °C')}

- NH4 sau bậc **vẫn là tín hiệu sống**: độ trải tương đối, biên độ ngày–đêm tương đối và tự tương quan giờ gần như giữ nguyên;
  chỉ nhiễu phút tương đối tăng ×2 (độ phân giải 0,01 trên số nhỏ hơn 20 lần). Đây là dấu hiệu của **một hệ số nhân mới trên
  cùng đầu dò** (đổi hiệu chuẩn / offset điện cực — với điện cực chọn lọc ion, đổi E0 là đổi hệ số nhân), không phải đầu dò chết.
- Sau bậc NH4 tương quan với mực nước mạnh hơn hẳn ({_f(sg.loc[('pre', 'NH4'), 'corr_anom_sea_level'], 2)} → {_f(sg.loc[('post', 'NH4'), 'corr_anom_sea_level'], 2)}): triều lên → NH4 lên. Nước biển ngoài khơi
  thường nghèo amoni hơn nước ven bờ, nên dấu này hợp với nhiễu ion (Na⁺/K⁺ theo độ mặn) hơn là amoni thật — gợi ý, chưa chứng minh.
- TSS sau bậc ít đỉnh nhiễu hơn hẳn (p95 {_f(pre_s['p95'], 0)} → {_f(post_s['p95'], 0)} mg/L).

### 3. Môi trường quanh bậc — không có tác nhân

| Yếu tố | Giá trị |
| --- | --- |
| Mưa ERA5 | 31/07: {_f(d('2026-07-31', 'precip_mm'), 1)} mm/ngày; 13 h {_f(h13['precip_mm'], 1)} mm, 14 h {_f(h14['precip_mm'], 1)} mm (mưa phùn); mưa lớn hơn đến sau bậc (01–07/08: 17–35 mm/ngày) |
| Gió 10 m (TB ngày) | 30/07 {_f(d('2026-07-30', 'wind_mean'), 1)}, 31/07 {_f(d('2026-07-31', 'wind_mean'), 1)} — lặng |
| Bão (IBTrACS 15/07–15/08) | gần nhất {storm['NAME']} cách {_f(storm['dist_km'], 0)} km ({str(storm['closest_time_utc'])[:10]}) |
| Triều (mô hình) | 14:00 {_f(h14['sea_level_m'], 2)} m, đang lên (13:00 {_f(h13['sea_level_m'], 2)}); kỳ triều cường, không phải nước đứng / nước ròng |
| Độ mặn GLO12 | 30/07 {_f(d('2026-07-30', 'salinity_psu'), 2)} → 31/07 {_f(d('2026-07-31', 'salinity_psu'), 2)} → 01/08 {_f(d('2026-08-01', 'salinity_psu'), 2)} psu |
| Nhiệt độ mặt GLO12 | 30/07 {_f(d('2026-07-30', 'sst_c'), 2)} → 01/08 {_f(d('2026-08-01', 'sst_c'), 2)} °C |
| SPM vệ tinh (4 km) | trung vị {SAT_PRE[0][5:]}…{SAT_PRE[1][5:]}: {_f(sat['SPM']['pre_median'], 1)} (n={sat['SPM']['pre_n']}); {SAT_POST[0][5:]}…{SAT_POST[1][5:]}: {_f(sat['SPM']['post_median'], 1)} (n={sat['SPM']['post_n']}); ảnh cuối trước bậc {sat['SPM']['last_before_step']}, đầu sau bậc {sat['SPM']['first_after_step']} |
| CHL vệ tinh | trước {_f(sat['CHL']['pre_median'], 1)}, sau {_f(sat['CHL']['post_median'], 1)} mg/m³ |

Một khối nước mới làm amoni giảm 20 lần trong 30 giây phải kéo theo đổi nhiệt độ / pH / độ mặn; không có dấu hiệu nào như vậy.

### 4. Mức nền — chế độ nào hợp lý?

| Đại lượng | Nguồn | p1 | trung vị | p95 |
| --- | --- | --- | --- | --- |
| Amoni TAN mg/L | cảm biến trước bậc | {_f(pre_t['p01'], 3)} | {_f(pre_t['median'], 3)} | {_f(pre_t['p95'], 3)} |
| | cảm biến sau bậc (đến 12/08) | {_f(post_t['p01'], 4)} | {_f(post_t['median'], 4)} | {_f(post_t['p95'], 4)} |
| | cảm biến 10–16/09 | {_f(sep_t['p01'], 4)} | {_f(sep_t['median'], 4)} | {_f(sep_t['p95'], 4)} |
| | tỉnh HP 2020–2024 (min {_f(hp['min'], 3)}) | {_f(hp['p01'], 3)} | {_f(hp['median'], 3)} | {_f(hp['p95'], 3)} |
| | tỉnh HP quý 6 + 8 | {_f(hp_aug['p01'], 3)} | {_f(hp_aug['median'], 3)} | {_f(hp_aug['p95'], 3)} |
| | tỉnh QN 2021–2024 (LOQ 0,010–0,015) | {_f(qn['p01'], 3)} | {_f(qn['median'], 3)} | {_f(qn['p95'], 3)} |
| | RIMF 2013 vùng lồng Cát Bà | | {_f(RIMF_2013_N_NH4['min'], 3)}–{_f(RIMF_2013_N_NH4['max'], 3)} | |
| TSS mg/L | cảm biến trước bậc (17–31/07) | {_f(pre_s['p01'], 1)} | {_f(pre_s['median'], 1)} | {_f(pre_s['p95'], 1)} |
| | cảm biến sau bậc | {_f(post_s['p01'], 1)} | {_f(post_s['median'], 1)} | {_f(post_s['p95'], 1)} |
| | cảm biến tuần đầu (30/05–05/06, trung vị ngày) | | {_f(jan.min(), 1)}–{_f(jan.max(), 1)} | |
| | tỉnh HP (max {_f(hp_s['max'], 1)}) | {_f(hp_s['p01'], 1)} | {_f(hp_s['median'], 1)} | {_f(hp_s['p95'], 1)} |
| | tỉnh QN | {_f(qn_s['p01'], 1)} | {_f(qn_s['median'], 1)} | {_f(qn_s['p95'], 1)} |
| | SPM vệ tinh (trước / sau) | | {_f(sat['SPM']['pre_median'], 1)} / {_f(sat['SPM']['post_median'], 1)} | |

- **NH4:** trước bậc khớp nền (trung vị tỉnh HP, RIMF vùng lồng, sát QCVN 0,1); sau bậc thấp hơn **mọi** mẫu HP, dưới
  p1 QN (≈ LOQ phòng thí nghiệm) và ~20–30 lần dưới RIMF vùng lồng; giữa 09 còn thấp thêm ~20 lần. Không có cơ chế tự nhiên
  nào giữ amoni vùng lồng bè ở mức 0,0003–0,005 mg/L suốt mùa mưa.
- **TSS:** ngược lại — trước bậc (35–130) vượt cả max tỉnh HP và cao gấp ~10 lần SPM vệ tinh; sau bậc (3–5) khớp QN, vệ tinh
  và chính tuần đầu lắp đặt. TSS tăng dần từ đầu 06 (~6 → ~85 mg/L đến 07/06), cùng lúc COD hỏng (06–08/06) → nhiều khả năng cửa sổ quang bị bám bẩn
  từ đầu 06 và được làm sạch / hiệu chuẩn lúc 31/07.

## Kết luận

1. **Bậc 31/07 14:06 là thay đổi của thiết bị, không phải của nước — độ tin cậy cao (~90–95 %).** Lý do: NH4 đổi
   mức trong ≤ 30 s, không quá độ, không mất dữ liệu; TSS đổi ~1 phút sau; pH / nhiệt độ / độ mặn / thủy triều / mưa /
   gió / vệ tinh không có gì trùng thời điểm; không có bão; hai chế độ lệch khỏi nền theo **hai hướng ngược nhau** (NH4
   trước hợp lý – sau không; TSS trước không – sau hợp lý); cùng kiểu với can thiệp chắc chắn ngày 16/09. Kịch bản phù hợp
   nhất: một lượt bảo dưỡng tại lồng (giờ hành chính, thứ Sáu) — làm sạch / hiệu chuẩn đầu TSS và đặt lại hệ số / hiệu chuẩn
   đầu NH4 — hoặc lệnh cấu hình từ xa. Không phân biệt được hai cách này nếu không hỏi nhà cung cấp.
2. **NH4: chế độ trước bậc gần sự thật hơn — độ tin cậy trung bình (~70 %).** Sau bậc là cùng đầu dò với hệ số khác (tín
   hiệu tương đối vẫn sống) rồi trôi thêm ~20 lần trong 6 tuần. Không loại trừ hoàn toàn khả năng bậc là một lần hiệu chuẩn
   "đúng" và trước đó đọc cao (điện cực NH4 trong nước biển dễ bị Na⁺/K⁺ làm đọc cao), nhưng kết quả sau đó nằm dưới mọi số liệu
   nền và trôi liên tục, nên dù có hiệu chuẩn thì hiệu chuẩn ấy không giữ được.
3. **TSS: chế độ sau bậc gần sự thật hơn — độ tin cậy trung bình (~70 %);** trước bậc (07/06–31/07) nghi bám bẩn.
4. Không có giai đoạn nào sau 31/07 mà NH4 cảm biến dùng được như số đo tuyệt đối.

## Ý nghĩa cho nuôi trồng

- **Không phải nước sạch hơn, cũng không phải nước xấu đi — đây là sai số / thay đổi của máy đo.** Không có bằng chứng
  amoni trong lồng giảm sau 31/07.
- Cách hiểu an toàn: amoni tại vùng lồng vẫn quanh **~0,1 mg/L N (sát hoặc hơi vượt QCVN 0,1)** như trước 31/07 và như số
  liệu tỉnh / RIMF — tức mức "cần theo dõi", không phải mức "rất sạch". Phần NH3 không ion (độc) ở mức đó vẫn thấp hơn
  ngưỡng theo dõi 0,05 mg/L trong điều kiện pH ~8, 30 °C (RL-69).
- TSS: nước nhiều khả năng **vẫn trong như trước** (vệ tinh 4–6 mg/L cả hai giai đoạn); mức 35–130 mg/L tháng 6–7 là do đầu
  đo bẩn, không phải nước đục.
- Vì vậy không được nói với người nuôi rằng "từ cuối tháng 7 amoni giảm / nước tốt lên".

## Hạn chế

- Chưa có xác nhận của nhà cung cấp / người vận hành (nhật ký bảo dưỡng, hệ số hiệu chuẩn, loại đầu dò NH4).
- Một trạm; không có trạm cùng hãng đang chạy để đối chứng (QN 06M26042803 kẹt NH4 = 500 / pH 5,2 ngày 31/07; hai trạm Hưng Yên
  không có dữ liệu cuối 07).
- Vệ tinh không có ảnh 27/07–08/08 (mây); GLO12 là mô hình, ô 5 km; mực nước là mô hình.
- Nền amoni là mẫu rời, phương pháp phòng thí nghiệm, năm khác (2013, 2020–2024); cơ sở NH4 (ion hay N) do RL-69 / nghiên cứu
  `nh4-basis-evidence-*` xử lý — không đổi kết luận ở đây vì hệ số 0,78 nhỏ hơn rất nhiều so với ÷20.
- Mốc thời gian 30 s trong một phút là suy ra từ thứ tự xuất file.

## Đề xuất

1. **Cờ QC `nh4_tss_regime_change_20260731`** từ 2026-07-31 14:06 (+07) cho NH4 và TSS (trạm 06M26042804), không tự hết hạn:
   - NH4 sau mốc: `suspect_scale` — coi là **thiếu** cho QCVN amoni, HSI, mô hình nội suy, điểm neo không gian; **không**
     nhân ×20 ngầm. NH3 không ion tính từ NH4 sau mốc không được dùng để kết luận "an toàn" (cảnh báo độc tính sẽ không bao
     giờ bật — im lặng không có nghĩa là an toàn).
   - TSS: đánh dấu `suspect_fouling` cho 2026-06-07 → 2026-07-31 14:15; sau mốc dùng được nhưng ghi "chưa xác nhận".
   - Thêm cờ cho các can thiệp khác: `instrument_intervention_20260812` (khoảng trống 16:58–19:25, COD → 0, nhiễu NH4 ×20) và
     `instrument_intervention_20260916` (15:31–15:36; NH4 ×~7, COD trở lại) để mô hình / chấm điểm không học qua các bậc này.
2. **Runtime / alerts:** QCVN amoni và HSI hiển thị "không đánh giá được (cảm biến NH4 nghi đổi thang đo từ 31/07)" thay vì
   "đạt"; nếu cần một giá trị cho bản đồ, dùng nền tỉnh (HP trung vị ~0,094 mg/L N) có nhãn "tham khảo, không phải đo".
3. **Người dùng:** dòng chú thích ngắn: "Từ 31/07/2026 số đo amoni và độ đục của trạm NB1 đổi đột ngột do thiết bị (đang chờ
   nhà cung cấp xác nhận). Amoni thực tế nhiều khả năng vẫn quanh 0,1 mg/L như trước."
4. **Hỏi nhà cung cấp (khi có kênh):** có bảo dưỡng / hiệu chuẩn ngày 31/07 ~14:00, 12/08 ~17:00, 16/09 ~15:30 không; hệ số
   NH4 trước / sau; loại đầu dò NH4 (ISE? bù K⁺/độ mặn?) và đơn vị thật; đầu TSS có gạt / làm sạch không.
5. **Ảnh hưởng lên kết quả cũ:**
   - RL-54 / RL-62 / RL-66 (NH4): mọi fold và lockbox 10–24/10 nằm sau bậc → "kỹ năng NH4" là kỹ năng dự báo **tín hiệu đầu dò**
     (đã trôi và có bậc 16/09), không phải amoni nước. Ghi chú vào kết quả; không chọn mô hình NH4 cho runtime dựa trên đó.
     Kết quả nhiệt độ của RL-54/62/66 không bị bậc 31/07 ảnh hưởng; biên độ nhiệt ngày tăng từ ~09–12/08 (RL-57) trùng sát
     can thiệp 12/08 — chỉ ghi nhận sự liền kề, chưa kết luận nhân quả.
   - RL-58: đã tách chế độ; kết quả NH4 / TSS sau bậc là phản ứng của đầu dò. TSS "insufficient_evidence" trước bậc có thể do bẩn.
   - RL-65: Spearman SPM–TSS 0,13 nên tính lại chỉ trên phần sau 31/07 14:15.
   - RL-69: số ngày vượt QCVN amoni sau bậc (0/85) là do thiết bị, không phải do nước.
6. Không đổi runtime trong lượt này (chủ dự án quyết).

## Tệp

`step_anatomy.csv`, `raw_window_*.csv`, `signal_character_pre_post.csv`, `cycle_profile_30min.csv`, `instrument_event_scan.csv`,
`daily_sensor.csv`, `environment_daily.csv`, `environment_hourly_20260731.csv`, `storms_jul_aug_2026.csv`,
`plausibility_background.csv`, `summary.json`, `manifest.json`; hình `fig_step_window_20260731.png`, `fig_step_window_20260812.png`,
`fig_step_window_20260916.png`, `fig_timeline_daily.png`, `fig_distributions_pre_post.png`, `fig_environment.png`, `fig_diurnal_signature.png`.
"""
    (out / "NOTES.md").write_text(text, encoding="utf-8")


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1], text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-name", default="nh4-step-0731-20261026")
    ap.add_argument("--output", type=Path, default=None, help="override run dir (scratch runs)")
    args = ap.parse_args(argv)
    out = args.output or (paths.EXPERIMENT_OUTPUT_DIR / args.run_name)
    out.mkdir(parents=True, exist_ok=False)

    hist = load_history()
    raw = load_raw()

    an1, win1 = anatomy(raw, E1_SEARCH, "E1_2026-07-31")
    an2, win2 = anatomy(raw, E2_SEARCH, "E2_2026-08-12")
    an3, win3 = anatomy(raw, E3_SEARCH, "E3_2026-09-16")
    an = pd.concat([an1, an2, an3], ignore_index=True)
    an.to_csv(out / "step_anatomy.csv", index=False)
    win1.to_csv(out / "raw_window_20260731_1200_1600.csv", index_label="t_local")
    win2.to_csv(out / "raw_window_20260812_1500_2100.csv", index_label="t_local")
    win3.to_csv(out / "raw_window_20260916_1000_1700.csv", index_label="t_local")
    bumps = upward_jumps(win1["pH"], 0.02)
    events = event_scan(hist)
    events.to_csv(out / "instrument_event_scan.csv", index=False)

    nh4_step = an1.set_index("variable").loc["NH4"]
    step_t = pd.Timestamp(nh4_step["first_new_sample"])
    factor = step_factor(hist.loc["2026-07-30 14:06":"2026-07-31 14:05", "NH4"],
                         hist.loc["2026-07-31 14:06":"2026-08-01 14:05", "NH4"])

    cyc_rows = []
    for var in ("pH", "TSS", "NH4"):
        for name, (a, b) in {"pre": PRE, "post": POST}.items():
            prof = cycle_profile(hist.loc[a:b, var])
            prof.insert(0, "window", name); prof.insert(0, "variable", var)
            cyc_rows.append(prof)
    cyc = pd.concat(cyc_rows, ignore_index=True)
    cyc.to_csv(out / "cycle_profile_30min.csv", index=False)
    top = (cyc.sort_values("abs_change_vs_mean", ascending=False).groupby(["variable", "window"]).head(2)
           .sort_values(["variable", "window", "abs_change_vs_mean"], ascending=[True, True, False]))

    env_daily, env_hourly, env_meta = environment(hist.index)
    sea = env_meta.pop("sea_level_series")
    env_daily.to_csv(out / "environment_daily.csv", index_label="date_local")
    env_hourly.to_csv(out / "environment_hourly_20260731.csv", index_label="t_local")
    storms = storms_near("2026-07-15", "2026-08-15")
    storms.to_csv(out / "storms_jul_aug_2026.csv", index=False)

    sig = signal_character(hist, sea)
    sig.to_csv(out / "signal_character_pre_post.csv", index=False)
    daily = daily_table(hist)
    daily.to_csv(out / "daily_sensor.csv")
    plaus = plausibility(hist, env_meta["satellite"])
    plaus.to_csv(out / "plausibility_background.csv", index=False)

    try:
        import matplotlib  # noqa: F401  (root .venv has no matplotlib: run with an env from requirements-experiments.txt)
        figures = True
    except ImportError:
        figures = False
    if figures:
        make_figures(win1, win2, win3, an2, an3, step_t, daily, plaus, factor, env_daily, sea, hist, out)

    tss_after = win1["TSS"].dropna().loc[step_t:]
    low = tss_after[tss_after < 30]
    t_low = low.index[0]
    tss_first_low = (str(t_low)[11:19], float(tss_after.shift(1).loc[t_low]), float(low.iloc[0]))
    write_notes(out, an=an, factor=factor, tss_first_low=tss_first_low, bumps=bumps, sig=sig, env_daily=env_daily,
                env_hourly=env_hourly, env_meta=env_meta, storms=storms, plaus=plaus, events=events, daily=daily)

    inputs = [HISTORY, *RAW_FILES, SEA_LEVEL, ERA5_PRECIP, ERA5_WIND, IBTRACS, *OC_SERIES.values(), *CMEMS_FILES.values(),
              paths.clean_data("haiphong"), paths.clean_data("quangninh")]
    summary = {
        "run": out.name, "station": STATION, "git_head": git_head(),
        "step_e1": {"nh4_first_new_sample_local": str(step_t), "nh4_last_old_sample_local": str(nh4_step["last_old_sample"]),
                    "nh4_ratio_local": float(nh4_step["ratio_before_over_after"]), "nh4_factor_24h_medians": factor,
                    "tss": an1.set_index("variable").loc["TSS"].to_dict(),
                    "max_gap_min_window": float(an1["max_gap_min"].max())},
        "step_e2": an2.set_index("variable")[["first_new_sample", "before_median", "after_median", "max_gap_min"]].to_dict(orient="index"),
        "step_e3": an3.set_index("variable")[["first_new_sample", "before_median", "after_median", "ratio_before_over_after",
                                               "max_gap_min"]].to_dict(orient="index"),
        "e1_ph_upward_jumps_ge_0.02": [str(t) for t in bumps],
        "instrument_event_days": events.to_dict(orient="records"),
        "cycle_top_minutes": top.to_dict(orient="records"),
        "environment_cells": env_meta,
        "nearest_storm": storms.iloc[0].to_dict() if len(storms) else None,
        "plausibility_attrs": {k: float(v) for k, v in plaus.attrs.items()},
        "windows": {"pre": PRE, "post": POST, "sat_pre": SAT_PRE, "sat_post": SAT_POST},
        "nh4_basis": {"NH4_UNIT_SCALE": NH4_UNIT_SCALE, "NH4_TO_N_FACTOR": NH4_TO_N_FACTOR,
                      "note": "TAN = raw x scale x factor (RL-69); basis study is a separate run"},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    manifest = {"run": out.name, "script": "experiments/nh4_step_0731.py", "git_head": summary["git_head"],
                "created_local": pd.Timestamp.now(tz=LOCAL_TZ).isoformat(),
                "inputs": [{"path": str(p), "sha256": sha256(p), "bytes": p.stat().st_size} for p in inputs],
                "python": sys.version.split()[0], "pandas": pd.__version__, "figures": figures,
                "outputs": sorted(p.name for p in out.iterdir())}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("step_e1", "step_e2", "nearest_storm")}, indent=2, default=str))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
