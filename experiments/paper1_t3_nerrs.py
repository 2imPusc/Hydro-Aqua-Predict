"""Paper 1 / T3: multi-station NERRS benchmark of Chronos-2 with weather covariates.

Question: is the T2 result on NB1 (Chronos-2 + as-issued weather does not beat ridge B5D at 6-12 h,
RL-74) specific to NB1? And how much is weather worth as its source improves from none to as-issued
forecast to observed (the "upper bound" of HANDOFF H2)?

Two NERRS data sets (15-min sonde water temperature, CDMO flag <0> only):
  * CDMO request 726235 (``data/foreign/nerrs_cdmo/raw/726235.zip``), primary. 8 WQ stations of
    Rookery Bay, Guana Tolomato Matanzas and Mission-Aransas + their met station (observed weather) +
    Open-Meteo Previous Runs forecasts at each WQ station (as-issued weather; full coverage from
    2024-01-22). Ridge trains 2024-02-01 .. 2025-01-31, test 2025-02-01 .. 2025-12-31 (4 origins/day: 00/06/12/18 LST).
  * NCEI 0052765 2007-2011 (``data/foreign/nerrs_ncei/``), replication without forecasts. 33 WQ stations
    of 8 reserves + reserve met. Ridge trains 2007-2009, test 2010-01-01 .. 2011-08-31 (1 origin/day,
    hour rotating 00/06/12/18 LST).

Models (all on the same origins; an origin needs the target at t, >= 50 % of the 7-day context, and
every weather source >= 75 % present in (t-24h, t] and (t, t+12h]):
  * persistence; diurnal-7d (current + 7-day same-slot profile change, ``Series15.prof7``)
  * ridge B4D-n: per-station ridge on the H1.7 delta-target feature set (lags, diurnal profile, calendar)
  * ridge B5D-{fc,obs}: B4D-n + 10 weather features of that source (B5D analogue)
  * Chronos-2 small zero-shot, 15-min step, 672-step context, 48 steps ahead:
      none / cal / cal-fc / cal-obs (direct) and anom-cal-fc (7-day anomaly target, T2 recipe)

Pre-registered rules: ``preregistration.json`` (written by ``init`` before any forecast). Stages:

    python experiments/paper1_t3_nerrs.py init
    python experiments/paper1_t3_nerrs.py fetch-weather            # Open-Meteo Previous Runs, write-once
    python experiments/paper1_t3_nerrs.py prepare --dataset cdmo|ncei
    python experiments/paper1_t3_nerrs.py origins --dataset cdmo|ncei
    python experiments/paper1_t3_nerrs.py ridge --dataset cdmo|ncei
    .venv-fm/Scripts/python experiments/paper1_t3_nerrs.py forecast --dataset cdmo --config cal-fc [--limit N]
    python experiments/paper1_t3_nerrs.py evaluate --dataset cdmo|ncei
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import time
import warnings
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402

RUN_NAME = "paper1-t3-20261029"
THREADS = 2
BATCH = 32
STEP = 15                      # minutes; NERRS native interval
DAY = 96                       # 15-min steps per day
CONTEXT = 672                  # 7 days, = NB1 setting for 6-12 h (T1)
LENGTH = 48                    # 12 h
HORIZONS = (15, 30, 60, 180, 360, 720)
PAST_WX = DAY                  # ridge past-weather window (t-24h, t]
MIN_WX_FRACTION = 0.75
MIN_CONTEXT_FRACTION = 0.5
ANOMALY_DAYS = 7
CDMO_ZIP = paths.FOREIGN_DATA_DIR / "nerrs_cdmo" / "raw" / "726235.zip"
NCEI_ROOT = paths.FOREIGN_DATA_DIR / "nerrs_ncei"

LOAD_OBS_VARS = ("ATemp", "WSpd", "TotPAR", "TotPrcp")  # kept in the prepared station files
FETCH_FC_VARS = ("temperature_2m", "wind_speed_10m", "shortwave_radiation", "precipitation")  # fetched
# Covariates used: PAR dropped after the pre-registration coverage check (rkbuhmet TotPAR ~50 % in 2025,
# gtmpcmet none Oct-Dec 2025), so shortwave is dropped too to keep obs/forecast 1:1.
OBS_VARS = ("ATemp", "WSpd", "TotPrcp")
FC_VARS = ("temperature_2m", "wind_speed_10m", "precipitation")  # 1:1 with OBS_VARS
ORIGINS_FILE = "origins-3wx.parquet"
FC_LEADS = (1, 2, 3)
FC_LAG = pd.Timedelta(hours=12)  # reconstruct_external_context.LAG: run of day D-N usable from D-N+1d+12h
FC_START = "2024-01-15"
FC_END = "2025-12-31"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"

# CDMO request 726235: WQ station -> (met station, UTC offset of LST). Coordinates from the zip's
# sampling_stations.csv (west longitudes stored positive there).
CDMO_STATIONS = {
    "rkbfbwq": ("rkbuhmet", -5), "rkbfuwq": ("rkbuhmet", -5), "rkblhwq": ("rkbuhmet", -5), "rkbmbwq": ("rkbuhmet", -5),
    "gtmfmwq": ("gtmpcmet", -5), "gtmpiwq": ("gtmpcmet", -5), "gtmsswq": ("gtmpcmet", -5),
    "marscwq": ("marcemet", -6),
}
DATASETS = {
    "cdmo": {"train": ("2024-02-01", "2025-02-01"), "test": ("2025-02-01", "2025-12-31 12:00"), "origin_hours": (0, 6, 12, 18),
             "rotate": False, "sources": ("fc", "obs")},
    "ncei": {"train": ("2007-01-01", "2010-01-01"), "test": ("2010-01-01", "2011-08-31 12:00"), "origin_hours": (0, 6, 12, 18),
             "rotate": True, "sources": ("obs",)},
}
CONFIGS = {
    "none": {"anomaly": False, "calendar": False, "weather": None},
    "cal": {"anomaly": False, "calendar": True, "weather": None},
    "cal-fc": {"anomaly": False, "calendar": True, "weather": "fc"},
    "cal-obs": {"anomaly": False, "calendar": True, "weather": "obs"},
    "anom-cal-fc": {"anomaly": True, "calendar": True, "weather": "fc"},
}
RUN_PLAN = {"cdmo": ("none", "cal", "cal-fc", "cal-obs", "anom-cal-fc"), "ncei": ("none", "cal", "cal-obs")}
CHRONOS_MODEL = "chronos-2-small"
TRAIN_EVERY = 2                # ridge training origins every 30 min (memory)
RIDGE_LAMBDAS = (0.1, 1.0, 10.0, 100.0, 1000.0)
N_BLOCKS = 5
N_BOOT = 1000

VERDICT_RULES = {
    "gate_nerrs": ("candidate beats reference at a horizon iff (a) test MAE and RMSE (pooled over stations) are lower in >= 4 of 5 "
                   "consecutive equal time blocks of the test period AND (b) DM-HLN on the per-origin-slot loss averaged over "
                   "stations (absolute loss, rectangular kernel, lag = ceil(horizon / origin spacing)) gives p < 0.05 in its favour. "
                   "Adapts decisions #16 to many stations: blocks play the folds, the whole test period plays the lockbox."),
    "T3_H1_primary": ("CDMO 2025: Chronos-2 small cal-fc (direct target, calendar + as-issued forecast weather) vs ridge B5D-fc: "
                      "test MAE ratio <= 0.95 AND gate_nerrs pass at BOTH 360 and 720 min. Primary because it is H1 of the paper "
                      "moved off NB1; direct target chosen from T2 (RL-74), where the 7-day anomaly target was the main loss."),
    "primary_tests": "Holm over 12: cal-fc vs ridge B5D-fc x 6 horizons, cal-fc vs Chronos-2 none x 6 (CDMO).",
    "H2_weather_ladder": ("Value of weather by source, CDMO, for Chronos (cal -> cal-fc -> cal-obs) and ridge (B4D-n -> B5D-fc -> "
                          "B5D-obs): MAE ratio vs the no-weather model with 95 % day-block bootstrap CI (1000 resamples). The "
                          "ordering none >= fc >= obs (MAE) 'holds' at a horizon when both point ratios are ordered and the obs "
                          "CI excludes 1. Gate verdicts reported for fc vs none and obs vs none."),
    "replication_ncei": ("NCEI 2010-2011: Chronos-2 cal-obs vs ridge B5D-obs and Chronos-2 none vs ridge B4D-n with the same gate; "
                         "same direction as CDMO counts as replicated. No forecasts exist for 2007-2011."),
    "anomaly_check": "CDMO: anom-cal-fc vs cal-fc; T2 predicts anomaly worse at 360/720 (secondary, gate reported).",
    "outcome_labels": "per pair: 'better' if candidate wins >= 4/6 horizons, 'worse' if reference wins >= 4/6, else 'mixed' (as T1/T2).",
    "post_hoc": "anything not listed here is labelled post-hoc in NOTES.md.",
}


# --------------------------------------------------------------------------- io
def run_dir() -> Path:
    return paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write(path: Path, obj) -> None:
    if path.exists():
        raise FileExistsError(f"refusing_to_overwrite:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, pd.DataFrame):
        if path.suffix == ".parquet":
            obj.to_parquet(path, index=False)
        else:
            obj.to_csv(path, index=False)
    else:
        path.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")


def _git_head() -> dict:
    root = Path(__file__).resolve().parents[1]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout.strip()
    return {"git_head": head, "worktree_clean": not dirty}


# --------------------------------------------------------------------------- flags / parsing
def parse_flags(cells: pd.Series) -> pd.Series:
    """CDMO QAQC flag code (``<0> [GSM]`` -> 0); blank -> NaN."""
    return pd.to_numeric(cells.astype(str).str.extract(r"<(-?\d)>")[0], errors="coerce")


def good_values(values: pd.Series, flags: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values.astype(str).str.strip(), errors="coerce")
    return numeric.where(parse_flags(flags) == 0)


def regular_grid(frame: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Reindex on the 15-min LST grid [start, end); duplicate stamps keep the first value."""
    frame = frame[~frame.index.duplicated()].sort_index()
    grid = pd.date_range(start, end, freq=f"{STEP}min", inclusive="left", name="time_lst")
    return frame.reindex(grid)


# --------------------------------------------------------------------------- forecast weather (as issued)
def availability(valid_utc: np.ndarray, lead: int) -> np.ndarray:
    """When the ``previous_day{lead}`` value for UTC hour ``valid_utc`` may be used (conservative, decision #13)."""
    day = valid_utc.astype("datetime64[D]").astype("datetime64[ns]")
    return day - np.timedelta64(lead - 1, "D") + FC_LAG.to_timedelta64()


class ForecastAsIssued:
    """Hourly Open-Meteo previous-run values, picked per (origin, valid hour) by the as-issued rule.

    Value at hour tau for origin t = smallest lead N with availability(tau, N) <= min(t, tau + 12 h): the
    future part is what was published by t; the past part is the day-ahead forecast as it stood 12 h after
    the hour (same rule as T2's reconstructed snapshots). All times UTC, tz-naive datetime64[ns].
    """

    def __init__(self, hourly: pd.DataFrame):
        times = pd.to_datetime(hourly["time"]).to_numpy().astype("datetime64[ns]")
        if np.any(np.diff(times) != np.timedelta64(1, "h")):
            raise ValueError("forecast_hours_not_regular")
        self.h0, self.n = times[0], len(times)
        self.values = np.stack([np.stack([hourly[f"{v}_previous_day{n}"].to_numpy(dtype=float) for v in FC_VARS], axis=-1)
                                for n in FC_LEADS])  # [lead, hour, var]

    def hourly(self, origins_utc: np.ndarray, hours_utc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """origins [n], hours [n, k] (datetime64[ns]) -> values [n, k, var], lead used [n, k] (0 = none)."""
        idx = ((hours_utc - self.h0) / np.timedelta64(1, "h")).astype(np.int64)
        inside = (idx >= 0) & (idx < self.n)
        limit = np.minimum(origins_utc[:, None], hours_utc + FC_LAG.to_timedelta64())
        out = np.full(hours_utc.shape + (len(FC_VARS),), np.nan)
        lead_used = np.zeros(hours_utc.shape, dtype=np.int8)
        for li, lead in enumerate(FC_LEADS):
            ok = inside & (lead_used == 0) & (availability(hours_utc, lead) <= limit)
            vals = self.values[li, np.clip(idx, 0, self.n - 1)]
            out[ok] = vals[ok]
            lead_used[ok] = lead
        return out, lead_used

    def at_marks(self, origins_utc: np.ndarray, marks_utc: np.ndarray) -> np.ndarray:
        """15-min marks [n, k] -> [n, k, var]: linear in time for state variables between the two
        surrounding hours (each with its own as-issued lead); precipitation = the hour-ending total / 4."""
        lo = marks_utc.astype("datetime64[h]").astype("datetime64[ns]")
        frac = ((marks_utc - lo) / np.timedelta64(1, "h"))[..., None]
        v_lo, _ = self.hourly(origins_utc, lo)
        v_hi, _ = self.hourly(origins_utc, lo + np.timedelta64(1, "h"))
        out = (1 - frac) * v_lo + frac * v_hi
        exact = (frac[..., 0] == 0)
        rain = FC_VARS.index("precipitation")
        hour_end = np.where(exact, v_lo[..., rain], v_hi[..., rain])
        out[..., rain] = hour_end / 4.0
        out[exact] = np.where(np.arange(len(FC_VARS)) == rain, out[exact], v_lo[exact])
        return out


# --------------------------------------------------------------------------- station series
class Station:
    """One WQ station on the regular 15-min LST grid: target + observed met (+ forecast)."""

    def __init__(self, name: str, frame: pd.DataFrame, utc_offset_h: float, forecast: ForecastAsIssued | None = None):
        self.name, self.offset, self.forecast = name, float(utc_offset_h), forecast
        self.t0 = frame.index[0].to_datetime64()
        self.temp = frame["Temp"].to_numpy(dtype=float)
        self.obs = frame[list(OBS_VARS)].to_numpy(dtype=float)
        self.n = len(frame)

    def utc(self, lst: np.ndarray) -> np.ndarray:
        return lst - np.timedelta64(int(self.offset * 60), "m")

    def index_of(self, lst: np.ndarray) -> np.ndarray:
        d = (lst - self.t0) / np.timedelta64(STEP, "m")
        if np.any(d % 1):
            raise ValueError("origin_not_on_15min_mark")
        return d.astype(np.int64)

    def _take(self, arr: np.ndarray, j: np.ndarray) -> np.ndarray:
        ok = (j >= 0) & (j < self.n)
        out = np.full(j.shape + arr.shape[1:], np.nan)
        out[ok] = arr[j[ok]]
        return out

    def target(self, idx: np.ndarray, offsets: np.ndarray) -> np.ndarray:
        return self._take(self.temp, idx[:, None] + offsets[None, :])

    def weather(self, source: str, idx: np.ndarray, offsets: np.ndarray) -> np.ndarray:
        """[n, k, 4] weather at marks idx + offsets as known at origin idx (obs: measured; fc: as issued)."""
        j = idx[:, None] + offsets[None, :]
        if source == "obs":
            return self._take(self.obs, j)
        if source == "fc":
            if self.forecast is None:
                raise ValueError(f"no_forecast:{self.name}")
            marks = self.utc(self.t0 + j * np.timedelta64(STEP, "m"))
            origins = self.utc(self.t0 + idx * np.timedelta64(STEP, "m"))
            return self.forecast.at_marks(origins, marks)
        raise ValueError(f"unknown_source:{source}")

    def calendar(self, idx: np.ndarray, offsets: np.ndarray) -> dict[str, np.ndarray]:
        minutes = ((idx[:, None] + offsets[None, :]) * STEP + (self.t0.astype("datetime64[m]").astype(np.int64) % 1440)) % 1440
        angle = 2 * np.pi * minutes / 1440.0
        return {"hour_sin": np.sin(angle), "hour_cos": np.cos(angle)}


def profile(st: Station, idx: np.ndarray, offsets: np.ndarray, days: int = ANOMALY_DAYS) -> np.ndarray:
    """Same-slot mean over the previous 1..days days (>= 3 present), reading only marks < idx + offsets - 95."""
    if offsets.max() >= DAY:
        raise AssertionError("profile_reads_after_issue")
    stack = np.stack([st.target(idx, offsets - DAY * d) for d in range(1, days + 1)])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        prof = np.nanmean(stack, axis=0)
    return np.where(np.isfinite(stack).sum(0) >= 3, prof, np.nan)


PAST = np.arange(-CONTEXT + 1, 1)          # context marks t-671 .. t
FUTURE = np.arange(1, LENGTH + 1)          # t+1 .. t+48
RIDGE_PAST = np.arange(-PAST_WX + 1, 1)


def eligible(st: Station, idx: np.ndarray, sources: tuple[str, ...]) -> np.ndarray:
    ctx = st.target(idx, PAST)
    ok = np.isfinite(ctx[:, -1]) & (np.isfinite(ctx).mean(1) >= MIN_CONTEXT_FRACTION)
    for source in sources:
        for offs in (RIDGE_PAST, FUTURE):
            ok &= (np.isfinite(st.weather(source, idx, offs)).mean(1) >= MIN_WX_FRACTION).all(1)
    return ok


def origin_marks(start: str, end: str, hours: tuple[int, ...], rotate: bool) -> pd.DatetimeIndex:
    days = pd.date_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize(), freq="D")
    if rotate:
        marks = days + pd.to_timedelta([hours[i % len(hours)] for i in range(len(days))], unit="h")
    else:
        marks = pd.DatetimeIndex(np.concatenate([(days + pd.Timedelta(hours=h)).to_numpy() for h in hours])).sort_values()
    return marks[(marks >= pd.Timestamp(start)) & (marks <= pd.Timestamp(end))]


# --------------------------------------------------------------------------- ridge
def weather_features(st: Station, source: str, idx: np.ndarray, horizon: int) -> pd.DataFrame:
    """10 features: per variable mean over (t, t+h] and (t-24h, t]; air temperature at t+h and t."""
    hs = horizon // STEP
    fut = st.weather(source, idx, np.arange(1, hs + 1))
    past = st.weather(source, idx, RIDGE_PAST)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        f = {f"wx_fut_{v}": np.nanmean(fut[..., i], axis=1) for i, v in enumerate(OBS_VARS)}
        f.update({f"wx_past_{v}": np.nanmean(past[..., i], axis=1) for i, v in enumerate(OBS_VARS)})
    f["wx_atemp_valid"], f["wx_atemp_now"] = fut[:, -1, 0], past[:, -1, 0]
    return pd.DataFrame(f)


def ridge_fit_predict(train: pd.DataFrame, test: pd.DataFrame, features: list[str], horizon: int) -> tuple[np.ndarray, float]:
    """Ridge on the delta target; lambda by MAE on the last 20 % of training time (purged by the horizon)."""
    from sklearn.linear_model import Ridge
    from experiments.transfer_forecast import Prep

    train = train.sort_values("issued_at")
    cut = train["issued_at"].quantile(0.8)
    fit = train["issued_at"] < cut - pd.Timedelta(minutes=horizon)
    val = train["issued_at"] >= cut
    prep = Prep().fit(train.loc[fit, features])
    scores = {}
    for lam in RIDGE_LAMBDAS:
        model = Ridge(alpha=lam).fit(prep.transform(train.loc[fit, features]), train.loc[fit, "delta"])
        scores[lam] = float(np.mean(np.abs(model.predict(prep.transform(train.loc[val, features])) - train.loc[val, "delta"])))
    lam = min(scores, key=scores.get)
    prep = Prep().fit(train[features])
    model = Ridge(alpha=lam).fit(prep.transform(train[features]), train["delta"])
    return model.predict(prep.transform(test[features])), lam


# --------------------------------------------------------------------------- evaluation helpers
def gate_nerrs(frame: pd.DataFrame, cand: str, ref: str, spacing_h: float) -> pd.DataFrame:
    """frame: issued_at (LST), station, horizon_minutes, actual, <cand>, <ref>, block. One row per horizon."""
    from experiments.forecast_dm_test import diebold_mariano

    rows = []
    for h, part in frame.groupby("horizon_minutes"):
        part = part.dropna(subset=["actual", cand, ref])
        ec, er = (part[cand] - part["actual"]).abs(), (part[ref] - part["actual"]).abs()
        blocks = 0
        for _, b in part.assign(ec=ec, er=er).groupby("block"):
            blocks += int(b.ec.mean() < b.er.mean() and np.sqrt((b.ec ** 2).mean()) < np.sqrt((b.er ** 2).mean()))
        slot = part.assign(ec=ec, er=er).groupby("issued_at")[["ec", "er"]].mean().sort_index()
        lag = max(1, int(np.ceil(h / 60 / spacing_h)))
        stat, p = diebold_mariano(slot.ec.to_numpy(), slot.er.to_numpy(), lag, kernel="rectangular")
        better = bool(np.isfinite(stat) and stat < 0)
        rows.append({"horizon_minutes": int(h), "model": cand, "reference": ref, "n": int(len(part)), "n_slots": int(len(slot)),
                     "mae": float(ec.mean()), "mae_ref": float(er.mean()), "mae_ratio": float(ec.mean() / er.mean()),
                     "blocks_beating": blocks, "dm_stat": stat, "dm_p": p,
                     "gate_pass": bool(blocks >= 4 and better and p < 0.05)})
    return pd.DataFrame(rows)


def pair_outcomes(fwd: pd.DataFrame, rev: pd.DataFrame) -> pd.DataFrame:
    out = fwd[["horizon_minutes", "model", "reference", "mae_ratio", "blocks_beating", "dm_p", "gate_pass"]].copy()
    out["blocks_beaten"] = rev.set_index("horizon_minutes").loc[out.horizon_minutes, "blocks_beating"].to_numpy()
    lose = rev.set_index("horizon_minutes").loc[out.horizon_minutes, "gate_pass"].to_numpy()
    out["outcome"] = np.where(out.gate_pass, "candidate_wins", np.where(lose, "reference_wins", "tie"))
    return out


def overall(outcomes: pd.DataFrame) -> str:
    wins, losses = int((outcomes.outcome == "candidate_wins").sum()), int((outcomes.outcome == "reference_wins").sum())
    return "better" if wins >= 4 else "worse" if losses >= 4 else "mixed"


def h1_rule(outcomes: pd.DataFrame) -> dict:
    sub = outcomes.set_index("horizon_minutes")
    horizons = {int(h): {"mae_ratio": float(sub.loc[h, "mae_ratio"]), "gate": bool(sub.loc[h, "gate_pass"])} for h in (360, 720)}
    return {"horizons": horizons, "holds": all(v["mae_ratio"] <= 0.95 and v["gate"] for v in horizons.values())}


def bootstrap_ratio(part: pd.DataFrame, cand: str, ref: str, n_boot: int = N_BOOT, seed: int = 0) -> tuple[float, float, float]:
    """MAE ratio with a day-block bootstrap 95 % CI (days resampled with replacement, all stations of a day kept)."""
    part = part.dropna(subset=["actual", cand, ref])
    day = part["issued_at"].dt.floor("D")
    g = pd.DataFrame({"ec": (part[cand] - part.actual).abs(), "er": (part[ref] - part.actual).abs(), "day": day}).groupby("day")[["ec", "er"]].agg(["sum", "count"])
    sc, sr, n = g[("ec", "sum")].to_numpy(), g[("er", "sum")].to_numpy(), g[("ec", "count")].to_numpy()
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(sc), size=(n_boot, len(sc)))
    ratios = sc[draws].sum(1) / sr[draws].sum(1)
    return float(sc.sum() / sr.sum()), float(np.quantile(ratios, 0.025)), float(np.quantile(ratios, 0.975))


# --------------------------------------------------------------------------- loaders
def load_cdmo() -> tuple[dict[str, pd.DataFrame], dict]:
    """15-min good-flag Temp per WQ station joined with its met station's 4 variables (LST)."""
    cols = ["StationCode", "DateTimeStamp", "Temp", "F_Temp"] + [c for v in LOAD_OBS_VARS for c in (v, f"F_{v}")]
    with zipfile.ZipFile(CDMO_ZIP) as z:
        raw = pd.read_csv(z.open("726235.csv"), usecols=cols, dtype=str, keep_default_na=False)
    raw["StationCode"] = raw["StationCode"].str.strip()
    raw["time_lst"] = pd.to_datetime(raw["DateTimeStamp"].str.strip(), format="%m/%d/%Y %H:%M")
    tally, frames = {}, {}
    met = {}
    for code in sorted({m for m, _ in CDMO_STATIONS.values()}):
        part = raw[raw.StationCode == code].set_index("time_lst")
        met[code] = pd.DataFrame({v: good_values(part[v], part[f"F_{v}"]) for v in LOAD_OBS_VARS})
        tally[code] = {v: float(met[code][v].notna().mean()) for v in LOAD_OBS_VARS}
    for code, (met_code, _) in CDMO_STATIONS.items():
        part = raw[raw.StationCode == code].set_index("time_lst")
        temp = good_values(part["Temp"], part["F_Temp"]).rename("Temp")
        tally[code] = {"Temp": float(temp.notna().mean()), "rows": int(len(part))}
        m = met[met_code]
        frames[code] = pd.concat([temp[~temp.index.duplicated()], m[~m.index.duplicated()]], axis=1)
    return frames, tally


def load_ncei() -> tuple[dict[str, pd.DataFrame], dict, dict]:
    from experiments import nerrs_load as nl
    from experiments import nerrs_multi as nm

    frames, tally, offsets = {}, {}, {}
    for res in nm.RESERVES.values():
        met_pieces = []
        for code in res.met_stations:  # first listed preferred (nerrs_multi.load_met_hourly rule)
            files = sorted(res.data_dir.glob(f"{res.code}{code}met*.csv"))
            parts = [nl.read_met_file(p, LOAD_OBS_VARS)[0] for p in files if int(p.stem[-4:]) in nm.QC_YEARS]
            parts = [p for p in parts if not p.empty]
            if parts:
                m = pd.concat(parts).sort_index()
                met_pieces.append(m[~m.index.duplicated()])
        if not met_pieces:
            raise ValueError(f"no_met:{res.code}")
        met = met_pieces[0]
        for extra in met_pieces[1:]:
            met = met.combine_first(extra)
        met = met.reindex(columns=list(LOAD_OBS_VARS))
        for st in res.wq_stations:
            files = sorted(res.data_dir.glob(f"{res.code}{st}wq*.csv"))
            parts = [nl.read_wq_file(p, ("Temp",))[0] for p in files if int(p.stem[-4:]) in nm.QC_YEARS]
            temp = pd.concat(parts).sort_index()["Temp"]
            name = f"{res.code}{st}wq"
            frames[name] = pd.concat([temp[~temp.index.duplicated()], met], axis=1)
            offsets[name] = res.utc_offset_h
            tally[name] = {"Temp": float(temp.notna().mean()), **{v: float(met[v].notna().mean()) for v in LOAD_OBS_VARS}}
    return frames, tally, offsets


def cdmo_coordinates() -> dict[str, tuple[float, float]]:
    with zipfile.ZipFile(CDMO_ZIP) as z:
        s = pd.read_csv(io.BytesIO(z.read("sampling_stations.csv")), encoding="latin1")
    s.columns = [c.strip() for c in s.columns]
    s["Station Code"] = s["Station Code"].astype(str).str.strip()
    s = s.set_index("Station Code")
    return {code: (float(s.loc[code, "Latitude"]), -abs(float(s.loc[code, "Longitude"]))) for code in CDMO_STATIONS}


def read_forecast(code: str) -> ForecastAsIssued:
    payload = json.loads((run_dir() / "weather-fc" / f"{code}.json").read_text(encoding="utf-8"))
    return ForecastAsIssued(pd.DataFrame(payload["hourly"]))


def stations(dataset: str) -> dict[str, Station]:
    root = run_dir() / f"data-{dataset}"
    meta = json.loads((root / "stations.json").read_text(encoding="utf-8"))
    out = {}
    for name, info in meta.items():
        frame = pd.read_parquet(root / f"{name}.parquet").set_index("time_lst")
        fc = read_forecast(name) if dataset == "cdmo" else None
        out[name] = Station(name, frame, info["utc_offset_h"], fc)
    return out


# --------------------------------------------------------------------------- stages
def stage_init(_args) -> None:
    root = run_dir()
    root.mkdir(parents=True, exist_ok=True)
    from experiments import paper1_t1_chronos2 as t1

    repo, rev = t1.CHRONOS2[CHRONOS_MODEL]
    _write(root / "preregistration.json", {
        "run": RUN_NAME, "written_at_utc": pd.Timestamp.now("UTC").isoformat(), **_git_head(),
        "question": __doc__.split("\n\n")[1], "datasets": DATASETS, "cdmo_stations": CDMO_STATIONS,
        "inputs": {"cdmo_zip": str(CDMO_ZIP), "cdmo_zip_sha256": "1f629d8acdabaef4d38e400536c23c32abeb6967f8d7239d8b9a1d811ffc67c9",
                   "ncei_root": str(NCEI_ROOT)},
        "qc": "CDMO flag <0> only for Temp and met; NCEI via nerrs_load readers (same rule); 15-min LST grid",
        "weather": {"observed": list(OBS_VARS), "forecast": list(FC_VARS), "forecast_leads": FC_LEADS,
                    "forecast_rule": "smallest lead N with floor_day(tau) - (N-1) d + 12 h <= min(t, tau + 12 h); hourly, linear to 15 min, precipitation hour total / 4",
                    "forecast_source": f"{PREVIOUS_RUNS_URL} models=best_match, per WQ station coordinates, {FC_START}..{FC_END}",
                    "eligibility": f"target at t present, >= {MIN_CONTEXT_FRACTION:.0%} of 7-day context, each weather source >= {MIN_WX_FRACTION:.0%} present in (t-24h, t] and (t, t+12h]; same origins for every model"},
        "chronos": {"model": CHRONOS_MODEL, "repo": repo, "revision": rev, "context_steps": CONTEXT, "prediction_length": LENGTH,
                    "step_minutes": STEP, "configs": CONFIGS, "run_plan": RUN_PLAN, "threads": THREADS, "point": "median", "quantiles": t1.QUANTILES},
        "ridge": {"features_B4D_n": "experiments.transfer_forecast.FEATURES (delta target, lags, s24/s48, prof7, amp24, calendar)",
                  "features_B5D": "B4D_n + 10 weather features of the source (mean over (t, t+h] and (t-24h, t] per variable; air temp at t+h and t)",
                  "per_station_per_horizon": True, "lambdas": RIDGE_LAMBDAS, "lambda_selection": "MAE on the last 20 % of training time", "training_origins": "every 30 min in the train window"},
        "baselines": ["persistence", "diurnal-7d (current + prof7)", "ridge B4D-n", "ridge B5D-fc", "ridge B5D-obs"],
        "horizons": HORIZONS, "verdict_rules": VERDICT_RULES,
        "notes": ["Ridge on CDMO trains on 2024-02-01..2025-01-31 (a full seasonal cycle, forecasts exist from 2024-01-22) so every ridge variant sees the same months; test starts 2025-02-01; 2021-2023 unused.",
                  "Missing covariate values (context or future) are passed to Chronos-2 as NaN (native missing-value support, checked on synthetic gaps before this file was written); ridge median-imputes test features and drops training rows with missing weather.",
                  "Origin eligibility uses only the PRESENCE of target / weather values (never their values); the same origins are scored for every model, including no-weather ones.",
                  "Weather covariates = 3 variables (ATemp/WSpd/TotPrcp ~ temperature_2m/wind_speed_10m/precipitation). TotPAR and shortwave_radiation were dropped BEFORE any forecast because of coverage (rkbuhmet TotPAR ~50 % in 2025, gtmpcmet none Oct-Dec 2025): with them rkb stations had 0 eligible origins. The superseded 4-variable origin file data-cdmo/origins.parquet is kept (write-once) and unused. Without a solar/cloud variable the value of weather may be understated.",
                  "CPU: OMP/MKL/OPENBLAS threads = 2 for every stage (runner exports them), torch threads = 2.",
                  "2025 CDMO metadata are provisional; reported as a limitation.",
                                    "Eligible origins (checked before init, presence only): CDMO 7,708 over 8 stations; NCEI 11,083 over 33 stations. NCEI 2011 met files carry no flag-<0> values at the checked reserves, so the NCEI test is effectively 2010.",
                  "No tide covariate in T3 (T2: neutral on NB1; NERRS has only sonde depth).",
                  "marscwq starts 2024-02-06: included (ridge training from its first data)."],
    })
    print(f"wrote {root / 'preregistration.json'}")


def stage_fetch_weather(_args) -> None:
    import requests

    out = run_dir() / "weather-fc"
    hourly = ",".join(f"{v}_previous_day{n}" for v in FETCH_FC_VARS for n in FC_LEADS)
    log = []
    for code, (lat, lon) in cdmo_coordinates().items():
        path = out / f"{code}.json"
        if path.exists():
            raise FileExistsError(f"refusing_to_overwrite:{path}")
        params = {"latitude": lat, "longitude": lon, "hourly": hourly, "start_date": FC_START, "end_date": FC_END,
                  "timezone": "UTC", "models": "best_match"}
        r = requests.get(PREVIOUS_RUNS_URL, params=params, timeout=300, headers={"User-Agent": "Hydro-Aqua-Predict research (academic)"})
        r.raise_for_status()
        _write(path, r.json())
        log.append({"station": code, "url": PREVIOUS_RUNS_URL, "params": params, "retrieved_at_utc": pd.Timestamp.now("UTC").isoformat(),
                    "grid_lat": r.json().get("latitude"), "grid_lon": r.json().get("longitude"), "sha256": _sha256(path)})
        time.sleep(2)
    _write(out / "fetch_log.json", log)
    print(json.dumps(log, indent=1)[:2000])


def stage_prepare(args) -> None:
    ds = DATASETS[args.dataset]
    root = run_dir() / f"data-{args.dataset}"
    if args.dataset == "cdmo":
        frames, tally = load_cdmo()
        offsets = {k: v[1] for k, v in CDMO_STATIONS.items()}
    else:
        frames, tally, offsets = load_ncei()
    start = (pd.Timestamp(ds["train"][0]) - pd.Timedelta(days=21)).strftime("%Y-%m-%d")
    end = (pd.Timestamp(ds["test"][1]) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    meta = {}
    for name, frame in frames.items():
        grid = regular_grid(frame, start, end)
        _write(root / f"{name}.parquet", grid.reset_index())
        meta[name] = {"utc_offset_h": offsets[name], "grid": [start, end], "coverage": {c: float(grid[c].notna().mean()) for c in grid.columns}}
    _write(root / "stations.json", meta)
    _write(root / "qc_tally.json", tally)


def stage_origins(args) -> None:
    """Eligible test origins (presence of target / weather only) -> data-<ds>/ORIGINS_FILE."""
    ds = DATASETS[args.dataset]
    root = run_dir() / f"data-{args.dataset}"
    rows, summary = [], {}
    marks = origin_marks(*ds["test"], ds["origin_hours"], ds["rotate"])
    for name, st in stations(args.dataset).items():
        ok = eligible(st, st.index_of(marks.to_numpy()), ds["sources"])
        rows.append(pd.DataFrame({"station": name, "issued_at": marks[ok]}))
        summary[name] = {"eligible": int(ok.sum()), "possible": int(len(marks))}
    origins = pd.concat(rows, ignore_index=True)
    _write(root / ORIGINS_FILE, origins)
    _write(root / ORIGINS_FILE.replace(".parquet", "_summary.json"), {"weather_vars": list(OBS_VARS), "stations": summary})
    print(origins.groupby("station").size().to_string(), len(origins))


def _series15(st: Station):
    from experiments.transfer_forecast import Series15

    start_utc = pd.Timestamp(st.utc(np.array([st.t0]))[0]).tz_localize("UTC")
    return Series15(st.temp, st.temp, start_utc, st.offset, st.name)


def stage_ridge(args) -> None:
    from experiments.transfer_forecast import FEATURES

    ds = DATASETS[args.dataset]
    root = run_dir()
    out_path = root / f"ridge-{args.dataset}.parquet"
    if out_path.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out_path}")
    origins = pd.read_parquet(root / f"data-{args.dataset}" / ORIGINS_FILE)
    preds, lambdas = [], []
    for name, st in stations(args.dataset).items():
        test_marks = origins.loc[origins.station == name, "issued_at"].to_numpy()
        if not len(test_marks):
            continue
        s15 = _series15(st)
        test_idx = st.index_of(test_marks)
        lo, hi = st.index_of(np.array([np.datetime64(ds["train"][0]), np.datetime64(ds["train"][1])]))
        train_idx = np.arange(lo, hi - LENGTH, TRAIN_EVERY)
        for h in HORIZONS:
            hs = h // STEP
            tr = s15.features(train_idx, h).reset_index(drop=True)
            te = s15.features(test_idx, h)
            base = pd.DataFrame({"station": name, "issued_at": test_marks, "horizon_minutes": h,
                                 "actual": st.target(test_idx, np.array([hs]))[:, 0], "persistence": te["current"].to_numpy()})
            base["diurnal-7d"] = te["current"].to_numpy() + np.nan_to_num(te["prof7"].to_numpy())
            sets = {"ridge-B4D-n": (FEATURES, None)}
            sets.update({f"ridge-B5D-{s}": (None, s) for s in ds["sources"]})
            for label, (feats, source) in sets.items():
                trf, tef, cols = tr.copy(), te.reset_index(drop=True).copy(), list(FEATURES)
                if source:
                    wtr = weather_features(st, source, train_idx, h)
                    wte = weather_features(st, source, test_idx, h)
                    trf, tef = pd.concat([trf, wtr], axis=1), pd.concat([tef, wte], axis=1)
                    cols += list(wtr.columns)
                    keep = np.isfinite(wtr.to_numpy()).all(1)
                else:
                    keep = np.ones(len(trf), bool)
                keep &= trf[["current", "d15", "d30", "d45", "d60", "delta"]].notna().all(1).to_numpy()
                trf = trf.loc[keep]
                pred_delta, lam = ridge_fit_predict(trf, tef, cols, h)
                base[label] = tef["current"].to_numpy() + pred_delta
                lambdas.append({"station": name, "horizon_minutes": h, "model": label, "lambda": lam, "n_train": int(len(trf))})
            preds.append(base)
        print(f"ridge {name} done", flush=True)
    _write(out_path, pd.concat(preds, ignore_index=True))
    _write(root / f"ridge-{args.dataset}-lambdas.csv", pd.DataFrame(lambdas))


def stage_forecast(args) -> None:
    from experiments import paper1_t1_chronos2 as t1
    from experiments import paper1_t2_chronos2_cov as t2

    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[var] = str(THREADS)
    cfg = CONFIGS[args.config]
    root = run_dir()
    pilot = f"-pilot{args.limit}" if args.limit else ""
    out = root / f"fm-{args.dataset}-{CHRONOS_MODEL}-{args.config}{pilot}.parquet"
    if out.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out}")
    origins = pd.read_parquet(root / f"data-{args.dataset}" / ORIGINS_FILE)
    if args.limit:
        origins = origins.sample(args.limit, random_state=0).sort_values(["station", "issued_at"])
    sts = stations(args.dataset)
    repo, rev = t1.CHRONOS2[CHRONOS_MODEL]
    fm = t2.Chronos2CovForecaster(repo, rev, THREADS)
    t_start, frames, fallback = time.perf_counter(), [], 0
    for name, part in origins.groupby("station"):
        st = sts[name]
        idx = st.index_of(part["issued_at"].to_numpy())
        target = st.target(idx, PAST)
        past, future = {}, {}
        if cfg["calendar"]:
            for k, v in st.calendar(idx, PAST).items():
                past[k] = v
            for k, v in st.calendar(idx, FUTURE).items():
                future[k] = v
        if cfg["weather"]:
            wp, wf = st.weather(cfg["weather"], idx, PAST), st.weather(cfg["weather"], idx, FUTURE)
            for i, v in enumerate(OBS_VARS):
                past[f"wx_{v}"], future[f"wx_{v}"] = wp[..., i], wf[..., i]
        add = np.zeros((len(idx), LENGTH))
        if cfg["anomaly"]:
            pp, pf = profile(st, idx, PAST), profile(st, idx, FUTURE)
            bad = ~np.isfinite(pf).all(1)
            fallback += int(bad.sum())
            target = np.where(bad[:, None], target, target - pp)
            add = np.where(bad[:, None], 0.0, pf)
        target = target.astype(np.float32)
        if past:
            paths_q = fm.quantile_paths_cov(target, past, future, LENGTH, BATCH)
        else:
            paths_q = fm.quantile_paths(target, LENGTH, BATCH)
        paths_q = paths_q + add[:, :, None]
        for h in HORIZONS:
            j = h // STEP - 1
            row = pd.DataFrame({"station": name, "issued_at": part["issued_at"].to_numpy(), "horizon_minutes": h})
            for qi, q in enumerate(t1.QUANTILES):
                row[t1.quantile_column(q)] = paths_q[:, j, qi]
            frames.append(row)
        print(f"{name}: {len(idx)} origins, {time.perf_counter() - t_start:.0f} s", flush=True)
    seconds = time.perf_counter() - t_start
    result = pd.concat(frames, ignore_index=True)
    result["model"] = f"{CHRONOS_MODEL}+{args.config}"
    _write(out, result)
    _write(out.with_suffix(".json"), {"dataset": args.dataset, "config": args.config, "cfg": cfg, "repo": repo, "revision": rev,
                                       "n_origins": int(len(origins)), "seconds": seconds, "seconds_per_origin": seconds / max(len(origins), 1),
                                       "anomaly_fallback": fallback, "threads": THREADS, "batch": BATCH, "python": sys.version,
                                       "platform": platform.platform(), "cpu_count": os.cpu_count()})
    print(json.dumps({"seconds_per_origin": seconds / max(len(origins), 1), "fallback": fallback}))


def _wide(dataset: str) -> tuple[pd.DataFrame, list[str]]:
    root = run_dir()
    wide = pd.read_parquet(root / f"ridge-{dataset}.parquet")
    models = [c for c in wide.columns if c not in ("station", "issued_at", "horizon_minutes", "actual")]
    for config in RUN_PLAN[dataset]:
        path = root / f"fm-{dataset}-{CHRONOS_MODEL}-{config}.parquet"
        fm = pd.read_parquet(path)[["station", "issued_at", "horizon_minutes", "q50"]].rename(columns={"q50": config})
        n = len(wide)
        wide = wide.merge(fm, on=["station", "issued_at", "horizon_minutes"], how="left")
        if len(wide) != n or wide[config].isna().any():
            raise AssertionError(f"origin_mismatch:{config}")
        models.append(config)
    return wide.dropna(subset=["actual"]).reset_index(drop=True), models


def stage_evaluate(args) -> None:
    from experiments import paper1_t1_chronos2 as t1

    ds = DATASETS[args.dataset]
    block_end = getattr(args, "block_end", None)
    out = run_dir() / (f"eval-{args.dataset}" + (f"-posthoc-blocks-to-{block_end}" if block_end else ""))
    if out.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out}")
    wide, models = _wide(args.dataset)
    # Post-hoc only: --block-end moves the end of the block window (the test window itself is unchanged).
    end = pd.Timestamp(block_end) if block_end else pd.Timestamp(ds["test"][1])
    edges = pd.date_range(ds["test"][0], end + pd.Timedelta(minutes=1), periods=N_BLOCKS + 1)
    wide["block"] = np.clip(np.searchsorted(edges.to_numpy(), wide["issued_at"].to_numpy(), side="right") - 1, 0, N_BLOCKS - 1)
    empty = sorted(set(range(N_BLOCKS)) - set(wide["block"].unique()))
    if empty:
        print(f"WARNING empty_blocks:{empty} (gate needs >= 4 of {N_BLOCKS} blocks)")
    spacing = 24.0 / len(ds["origin_hours"]) if not ds["rotate"] else 24.0

    metrics = []
    for m in models:
        err = wide[m] - wide["actual"]
        for (st, h), e in err.groupby([wide.station, wide.horizon_minutes]):
            metrics.append({"scope": st, "model": m, "horizon_minutes": h, "n": len(e), "mae": e.abs().mean(), "rmse": np.sqrt((e ** 2).mean()), "bias": e.mean()})
        for h, e in err.groupby(wide.horizon_minutes):
            metrics.append({"scope": "pooled", "model": m, "horizon_minutes": h, "n": len(e), "mae": e.abs().mean(), "rmse": np.sqrt((e ** 2).mean()), "bias": e.mean()})
    metrics = pd.DataFrame(metrics)
    pooled = metrics[metrics.scope == "pooled"].pivot(index="horizon_minutes", columns="model", values="mae")

    pairs = []
    if args.dataset == "cdmo":
        pairs += [("cal-fc", "ridge-B5D-fc", "primary"), ("cal-fc", "none", "primary"),
                  ("cal-obs", "ridge-B5D-obs", "secondary"), ("none", "ridge-B4D-n", "secondary"), ("cal-fc", "ridge-B4D-n", "secondary"),
                  ("cal-fc", "cal", "ladder"), ("cal-obs", "cal", "ladder"), ("cal-obs", "cal-fc", "ladder"),
                  ("ridge-B5D-fc", "ridge-B4D-n", "ladder"), ("ridge-B5D-obs", "ridge-B4D-n", "ladder"), ("ridge-B5D-obs", "ridge-B5D-fc", "ladder"),
                  ("anom-cal-fc", "cal-fc", "anomaly_check"), ("cal", "none", "secondary")]
    else:
        pairs += [("cal-obs", "ridge-B5D-obs", "replication"), ("none", "ridge-B4D-n", "replication"),
                  ("cal-obs", "cal", "ladder"), ("ridge-B5D-obs", "ridge-B4D-n", "ladder"), ("cal", "none", "secondary")]
    tables, gates = [], []
    for cand, ref, role in pairs:
        fwd, rev = gate_nerrs(wide, cand, ref, spacing), gate_nerrs(wide, ref, cand, spacing)
        gates += [fwd, rev]
        o = pair_outcomes(fwd, rev)
        o["role"] = role
        cis = [bootstrap_ratio(wide[wide.horizon_minutes == h], cand, ref) for h in o.horizon_minutes]
        o["ratio_ci_lo"], o["ratio_ci_hi"] = [c[1] for c in cis], [c[2] for c in cis]
        o["stations_cand_better"] = [int((metrics[(metrics.scope != "pooled") & (metrics.model == cand) & (metrics.horizon_minutes == h)].set_index("scope").mae
                                         < metrics[(metrics.scope != "pooled") & (metrics.model == ref) & (metrics.horizon_minutes == h)].set_index("scope").mae).sum())
                                     for h in o.horizon_minutes]
        tables.append(o)
    table = pd.concat(tables, ignore_index=True)
    primary = table.role.eq("primary")
    table.loc[primary, "holm_p"] = t1.holm(table.loc[primary, "dm_p"]).to_numpy()

    verdict = {"dataset": args.dataset, "posthoc_block_end": block_end, "empty_blocks": empty, "n_rows": int(len(wide)), "n_stations": int(wide.station.nunique()),
               "n_origins": int(wide[["station", "issued_at"]].drop_duplicates().shape[0]),
               "pairs": {f"{c}__vs__{r}": overall(table[(table.model == c) & (table.reference == r)]) for c, r, _ in pairs}}
    if args.dataset == "cdmo":
        verdict["T3_H1"] = h1_rule(table[(table.model == "cal-fc") & (table.reference == "ridge-B5D-fc")])
        ladder = {}
        for family, (none, fc, obs) in {"chronos": ("cal", "cal-fc", "cal-obs"), "ridge": ("ridge-B4D-n", "ridge-B5D-fc", "ridge-B5D-obs")}.items():
            for h in HORIZONS:
                rf = table[(table.model == fc) & (table.reference == none) & (table.horizon_minutes == h)].iloc[0]
                ro = table[(table.model == obs) & (table.reference == none) & (table.horizon_minutes == h)].iloc[0]
                ladder.setdefault(family, {})[int(h)] = {"fc_vs_none": [round(rf.mae_ratio, 4), round(rf.ratio_ci_lo, 4), round(rf.ratio_ci_hi, 4)],
                                                         "obs_vs_none": [round(ro.mae_ratio, 4), round(ro.ratio_ci_lo, 4), round(ro.ratio_ci_hi, 4)],
                                                         "holds": bool(ro.mae_ratio <= rf.mae_ratio <= 1.0 and ro.ratio_ci_hi < 1.0)}
        verdict["H2_ladder"] = ladder
    else:
        verdict["replication"] = {f"{c}__vs__{r}": h1_rule(table[(table.model == c) & (table.reference == r)]) for c, r in (("cal-obs", "ridge-B5D-obs"), ("none", "ridge-B4D-n"))}
    out.mkdir(parents=True)
    _write(out / "metrics.csv", metrics)
    _write(out / "pooled_mae.csv", pooled.reset_index())
    _write(out / "gate.csv", pd.concat(gates, ignore_index=True))
    _write(out / "verdicts.csv", table)
    _write(out / "verdict.json", verdict)
    _write(out / "manifest.json", {"inputs": {p.name: _sha256(p) for p in sorted(run_dir().glob(f"*{args.dataset}*.parquet"))}, "spacing_h": spacing})
    pd.set_option("display.width", 250)
    print(pooled.round(3).to_string())
    print(json.dumps(verdict, indent=1, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="stage", required=True)
    sub.add_parser("init")
    sub.add_parser("fetch-weather")
    for name in ("prepare", "origins", "ridge", "evaluate"):
        p = sub.add_parser(name)
        p.add_argument("--dataset", choices=sorted(DATASETS), required=True)
    p.add_argument("--block-end", default=None, help="POST-HOC: end of the gate block window (default: test end)")
    p = sub.add_parser("forecast")
    p.add_argument("--dataset", choices=sorted(DATASETS), required=True)
    p.add_argument("--config", choices=sorted(CONFIGS), required=True)
    p.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    {"init": stage_init, "fetch-weather": stage_fetch_weather, "prepare": stage_prepare, "origins": stage_origins, "ridge": stage_ridge,
     "forecast": stage_forecast, "evaluate": stage_evaluate}[args.stage](args)


if __name__ == "__main__":
    main()
