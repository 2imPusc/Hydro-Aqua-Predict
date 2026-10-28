"""Paper 1 / T2: Chronos-2 with as-issued weather + harmonic tide + calendar covariates on NB1.

Same origins, step / context grid and horizon interpolation as T1 (``paper1_t1_chronos2``), so the
only differences to the stored T1 forecasts are the covariates and (optionally) the 7-day diurnal
anomaly target.  Stages share ``paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME`` (write-once files):

``init``      ``preregistration.json`` (configs, covariates, as-issued rule, tide fit, anomaly
              definition, run plan, verdict rules) before any T2 forecast exists.
``forecast``  (``.venv-fm``) ``--model chronos-2-small|chronos-2-base --config <name> --stride 15|60``.
              ``--limit N`` = timing pilot on rolling-fold origins only (never evaluated).
``evaluate``  ``--stride 15|60``: merges every T2 file of that stride with ridge B4D / B5D,
              Chronos-Bolt, diurnal-anomaly-7d, T1 Chronos-2 (and TimesFM at stride 60) on identical
              origins, decision #16 gate every model vs every model, verdicts, Holm (stride 15).

Covariates (all known at ``issued_at``):
  weather   Open-Meteo Previous Runs (decision #13, ``reconstructed_run``), one run per day.  The value
            at hour tau for origin t comes from the run with the largest ``retrieved_at <=
            min(t, tau + 12 h)``: future hours use the latest run retrieved by t (= ``join_as_issued``),
            past hours the freshest run issued by then.  Hourly values are interpolated linearly to
            the window centres.
  tide      harmonic fit (M2 S2 N2 K1 O1 Q1 + mean) to the modelled Open-Meteo marine sea level
            before ``TIDE_FIT_END``, frozen, evaluated at past and future window centres.
  calendar  local hour-of-day sin / cos at the window centres.

Usage (repo root; HAP_* env vars point at the shared data / artifacts):
    .venv/Scripts/python experiments/paper1_t2_chronos2_cov.py init
    .venv-fm/Scripts/python experiments/paper1_t2_chronos2_cov.py forecast --model chronos-2-small --config anom-full --stride 15
    .venv/Scripts/python experiments/paper1_t2_chronos2_cov.py evaluate --stride 15
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from experiments import foundation_zero_shot as fz  # noqa: E402
from experiments import paper1_t1_chronos2 as t1  # noqa: E402

RUN_NAME = "paper1-t2-20261028"
TAG = "Temperature"
THREADS = t1.THREADS
BATCH = 32  # target series per call; Chronos-2's batch_size counts covariates too -> BATCH * (1 + n_cov)
T1_RUN = paths.EXPERIMENT_OUTPUT_DIR / t1.RUN_NAME
EXTERNAL = paths.EXPERIMENT_OUTPUT_DIR / "external-context-06M26042804-2026-05-28_2026-10-24"
SNAPSHOTS = EXTERNAL / "weather-snapshots-reconstructed.jsonl"
SEA_LEVEL = EXTERNAL / "sea_level_openmeteo_marine.csv"
WEATHER_VARS = ("temperature_2m", "cloud_cover", "wind_speed_10m", "precipitation")
PAST_LAG = pd.Timedelta(hours=12)  # a run retrieved at R covers valid hours R-12h ... R+59h
# Degrees per hour.  ~92 days of fit data separate these (Rayleigh); K2/S2 and P1/K1 need ~182 days.
TIDE_SPEEDS = {"M2": 28.9841042, "S2": 30.0, "N2": 28.4397295, "K1": 15.0410686, "O1": 13.9430356, "Q1": 13.3986609}
TIDE_FIT_END = pd.Timestamp("2026-08-28T00:00:00Z")  # first origin 2026-09-04 17:30 UTC minus the 7-day context
TIDE_EPOCH = pd.Timestamp("2026-01-01T00:00:00Z")
ANOMALY_DAYS = 7
CONFIGS = {
    "anom-full": {"anomaly": True, "covariates": ("calendar", "weather", "tide")},
    "direct-full": {"anomaly": False, "covariates": ("calendar", "weather", "tide")},
    "anom-cal-weather": {"anomaly": True, "covariates": ("calendar", "weather")},
    "anom-cal": {"anomaly": True, "covariates": ("calendar",)},
    "anom": {"anomaly": True, "covariates": ()},
}
PRIMARY_CONFIG = "anom-full"
PRIMARY_MODEL = "chronos-2-small"  # T1 size rule (eval-Temperature-stride15/verdict.json)
RUN_PLAN = [("chronos-2-small", "anom-full", 15), ("chronos-2-small", "anom-full", 60), ("chronos-2-small", "direct-full", 60),
            ("chronos-2-small", "anom-cal-weather", 60), ("chronos-2-small", "anom-cal", 60), ("chronos-2-small", "anom", 60),
            ("chronos-2-base", "anom-full", 60)]
STORED_T1 = ("chronos-2-small", "chronos-2-base")
STORED_FM = ("chronos-bolt-base", "diurnal-anomaly-7d")
RIDGE_SETS = t1.RIDGE_SETS["withB5"]
B5D = "ridge_B5_external_as_issued_diurnal"
VERDICT_RULES = {
    "gate16": t1.VERDICT_RULES["gate16"].replace("ceil(h / 15)", "ceil(h / stride)"),
    "vs_reference": t1.VERDICT_RULES["vs_reference"],
    "H1": "Primary candidate (chronos-2-small, anom-full, stride 15) vs ridge B5D (ridge_B5_external_as_issued_diurnal): H1 holds iff at BOTH 360 and 720 min the lockbox MAE ratio <= 0.95 AND the candidate passes gate #16 vs B5D.",
    "primary_tests": "12 lockbox DM tests at stride 15: primary candidate vs B5D x 6 horizons and vs T1 chronos-2-small (no covariates) x 6 horizons; Holm reported next to the raw p; the gate uses the raw p (as RL-62/66/73).",
    "secondary": "Primary candidate vs B5D_nopH (sota-and-plan.md:183 phrasing: 3/6/12 h), B4D, Chronos-Bolt base, diurnal-anomaly-7d, persistence, T1 chronos-2-base. Reported, no Holm.",
    "ablations_stride60": "On stride-60 origins (identical across files): tide value = anom-full vs anom-cal-weather; weather value = anom-cal-weather vs anom-cal; calendar value = anom-cal vs anom; anomaly value = anom vs T1 small and anom-full vs direct-full; size = base anom-full vs small anom-full. Each reported with the vs_reference rule; no Holm, exploratory.",
    "covariate_value": "'Weather adds value' only if anom-cal-weather passes gate #16 vs anom-cal at >= 1 of 180/360/720 and anom-cal passes at none vs anom-cal-weather (stride 60, exploratory).",
}


def run_dir() -> Path:
    return paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model_name(model: str, config: str) -> str:
    return f"{model}+{config}"


def forecast_path(model: str, config: str, stride: int, limit: int | None = None) -> Path:
    pilot = f"-pilot{limit}" if limit else ""
    return run_dir() / f"fm-{TAG}-{model}-{config}-stride{stride}{pilot}.parquet"


# --------------------------------------------------------------------------- covariates
class WeatherAsIssued:
    """Hourly weather per run; ``hourly`` picks the run with the largest retrieved_at <= min(t, tau + 12 h)."""

    def __init__(self, snapshots: pd.DataFrame, variables=WEATHER_VARS):
        snaps = snapshots
        if "provenance_class" in snaps:
            snaps = snaps[snaps["provenance_class"].isin(["captured_live", "reconstructed_run"])]
        snaps = snaps.assign(valid_hour=snaps["valid_at"].dt.floor("h"))
        self.variables = tuple(variables)
        self.runs = np.sort(snaps["retrieved_at"].dt.tz_convert(None).unique()).astype("datetime64[ns]")
        self.h0 = snaps["valid_hour"].min()
        n_hours = int((snaps["valid_hour"].max() - self.h0) / pd.Timedelta(hours=1)) + 1
        self.values = np.full((len(self.runs), n_hours, len(self.variables)), np.nan)
        run_idx = np.searchsorted(self.runs, snaps["retrieved_at"].dt.tz_convert(None).to_numpy())
        hour_idx = ((snaps["valid_hour"] - self.h0) / pd.Timedelta(hours=1)).to_numpy().astype(int)
        feats = pd.json_normalize(snaps["features"].tolist())
        for j, var in enumerate(self.variables):
            self.values[run_idx, hour_idx, j] = pd.to_numeric(feats[var], errors="coerce").to_numpy()

    def hourly(self, origins: np.ndarray, hours: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """``origins`` (n,) datetime64[ns, UTC-naive], ``hours`` (n, m) int hour index -> values (n, m, v), run used (n, m)."""
        hour_time = self.h0.tz_convert(None).to_datetime64() + hours.astype("timedelta64[h]")
        cutoff = np.minimum(origins[:, None], hour_time + PAST_LAG.to_timedelta64())
        k = np.searchsorted(self.runs, cutoff, side="right") - 1
        inside = (k >= 0) & (hours >= 0) & (hours < self.values.shape[1])
        out = np.full(hours.shape + (len(self.variables),), np.nan)
        out[inside] = self.values[k[inside], hours[inside]]
        return out, np.where(inside, k, -1)

    def at(self, origins: np.ndarray, times: np.ndarray) -> np.ndarray:
        """Linear interpolation between hourly values at ``times`` (n, m) datetime64[ns]."""
        u = (times - self.h0.tz_convert(None).to_datetime64()) / np.timedelta64(1, "h")
        lo = np.floor(u).astype(int)
        w = (u - lo)[..., None]
        a, _ = self.hourly(origins, lo)
        b, _ = self.hourly(origins, lo + 1)
        return np.where(w == 0, a, (1 - w) * a + w * b)


def read_weather(path: Path = SNAPSHOTS, station: str = fz.STATION) -> WeatherAsIssued:
    from experiments.forecast_external_context import read_snapshots

    snaps = read_snapshots(path)
    return WeatherAsIssued(snaps[snaps["station"].eq(station)])


class HarmonicTide:
    def __init__(self, speeds: dict[str, float] = TIDE_SPEEDS):
        self.speeds = dict(speeds)
        self.coef = None

    def _design(self, times: np.ndarray) -> np.ndarray:
        hours = (np.asarray(times, dtype="datetime64[ns]") - TIDE_EPOCH.tz_convert(None).to_datetime64()) / np.timedelta64(1, "h")
        cols = [np.ones_like(hours)]
        for speed in self.speeds.values():
            phase = np.deg2rad(speed) * hours
            cols += [np.cos(phase), np.sin(phase)]
        return np.stack(cols, axis=-1)

    def fit(self, times: np.ndarray, level: np.ndarray) -> dict:
        x, y = self._design(times), np.asarray(level, dtype=float)
        self.coef, *_ = np.linalg.lstsq(x, y, rcond=None)
        resid = y - x @ self.coef
        amps = {name: float(np.hypot(self.coef[1 + 2 * i], self.coef[2 + 2 * i])) for i, name in enumerate(self.speeds)}
        return {"n_hours": int(len(y)), "r2": float(1 - resid.var() / y.var()), "rmse_m": float(np.sqrt(np.mean(resid ** 2))), "amplitude_m": amps}

    def predict(self, times: np.ndarray) -> np.ndarray:
        return self._design(times) @ self.coef


def fit_tide(path: Path = SEA_LEVEL) -> tuple[HarmonicTide, dict]:
    level = pd.read_csv(path).dropna(subset=["sea_level_m"])
    level["valid_at"] = pd.to_datetime(level["valid_at"], utc=True)
    fit = level[level["valid_at"] < TIDE_FIT_END]
    tide = HarmonicTide()
    diag = tide.fit(fit["valid_at"].dt.tz_convert(None).to_numpy(), fit["sea_level_m"].to_numpy())
    later = level[level["valid_at"] >= TIDE_FIT_END]
    resid = later["sea_level_m"].to_numpy() - tide.predict(later["valid_at"].dt.tz_convert(None).to_numpy())
    diag.update({"fit_end": str(TIDE_FIT_END), "fit_start": str(fit["valid_at"].min()),
                 "after_fit_rmse_m": float(np.sqrt(np.mean(resid ** 2))), "after_fit_n_hours": int(len(later))})
    return tide, diag


def calendar(times: np.ndarray) -> dict[str, np.ndarray]:
    local = pd.DatetimeIndex(np.asarray(times, dtype="datetime64[ns]").ravel()).tz_localize("UTC").tz_convert("Asia/Ho_Chi_Minh")
    frac = ((local.hour * 60 + local.minute + local.second / 60) / 1440).to_numpy().reshape(np.shape(times))
    return {"hour_sin": np.sin(2 * np.pi * frac), "hour_cos": np.cos(2 * np.pi * frac)}


def window_centres(issued: pd.Series, step: int, context: int, length: int) -> tuple[np.ndarray, np.ndarray]:
    """Centre times (UTC-naive datetime64) of the context windows (oldest first) and of the forecast windows.

    Matches ``Grid.contexts`` (last window ends just before issued) and ``interpolate_horizon``
    (forecast window j centred at issued + (j - 0.5) * step - 0.5 min).
    """
    t = issued.dt.tz_convert(None).dt.floor("min").to_numpy()[:, None]
    back = step * np.arange(context)[::-1] + step / 2 + 0.5
    ahead = (np.arange(1, length + 1) - 0.5) * step - 0.5
    minute = np.timedelta64(60_000_000_000, "ns")
    return t - (back * minute.astype(float)).astype("timedelta64[ns]"), t + (ahead * minute.astype(float)).astype("timedelta64[ns]")


def diurnal_profile(grid: fz.Grid, ends: np.ndarray, step: int, last: np.ndarray, days: int = ANOMALY_DAYS) -> np.ndarray:
    """Mean of the same ``step``-window shifted back 1..days days; every bin read is <= ``last`` (asserted)."""
    shifted = ends[..., None] - 1440 * np.arange(1, days + 1)
    if (shifted.max(axis=tuple(range(1, shifted.ndim))) > last + 1).any():
        raise AssertionError("profile_reads_after_issue")
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(grid.window_mean(shifted, step), axis=-1)


def anomaly_target(grid: fz.Grid, issued: pd.Series, step: int, context: np.ndarray, length: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """-> (context - profile, future profile, fallback mask).  Fallback origins keep the raw context and a zero profile."""
    last = grid.last_index(issued)
    n_ctx = context.shape[1]
    ctx_ends = last[:, None] + 1 - step * np.arange(n_ctx)[::-1][None, :]
    fut_ends = last[:, None] + 1 + step * np.arange(1, length + 1)[None, :]
    ctx_prof = diurnal_profile(grid, ctx_ends, step, last)
    fut_prof = diurnal_profile(grid, fut_ends, step, last)
    fallback = ~np.isfinite(fut_prof).all(axis=1)
    target = np.where(fallback[:, None], context, context - ctx_prof).astype(np.float32)
    fut_prof = np.where(fallback[:, None], 0.0, fut_prof)
    return target, fut_prof, fallback


def add_profile(paths_q: np.ndarray, future_profile: np.ndarray) -> np.ndarray:
    """(n, H, Q) anomaly quantile paths + (n, H) profile; quantile order is preserved."""
    return paths_q + future_profile[:, :, None]


def covariate_arrays(kinds, issued: pd.Series, step: int, context: int, length: int, weather: WeatherAsIssued | None, tide: HarmonicTide | None) -> tuple[dict, dict, dict]:
    """-> past (n, context) and future (n, length) arrays per covariate name, plus weather-run diagnostics."""
    past_t, fut_t = window_centres(issued, step, context, length)
    past, future, diag = {}, {}, {}
    if "calendar" in kinds:
        for (name, p), f in zip(calendar(past_t).items(), calendar(fut_t).values()):
            past[name], future[name] = p, f
    if "weather" in kinds:
        origins = issued.dt.tz_convert(None).to_numpy()
        p, f = weather.at(origins, past_t), weather.at(origins, fut_t)
        for j, var in enumerate(weather.variables):
            past[var], future[var] = p[..., j], f[..., j]
        hours = np.ceil((fut_t - weather.h0.tz_convert(None).to_datetime64()) / np.timedelta64(1, "h")).astype(int)
        _, k = weather.hourly(origins, hours)
        run_time = weather.runs[np.maximum(k, 0)]
        if (run_time > origins[:, None]).any():
            raise AssertionError("weather_run_after_issue")
        diag = {"issue_age_hours_max": float(((origins - run_time[:, 0]) / np.timedelta64(1, "h")).max()),
                "lead_hours_max": float(((fut_t[:, -1] - run_time[:, -1]) / np.timedelta64(1, "h")).max())}
    if "tide" in kinds:
        past["tide"], future["tide"] = tide.predict(past_t), tide.predict(fut_t)
    for name in past:
        if not (np.isfinite(past[name]).all() and np.isfinite(future[name]).all()):
            raise ValueError(f"covariate_nan:{name}")
        past[name], future[name] = past[name].astype(np.float32), future[name].astype(np.float32)
    return past, future, diag


def as_inputs(target: np.ndarray, past: dict, future: dict) -> list[dict]:
    if set(future) - set(past):
        raise ValueError("future_covariates_not_in_past")
    inputs = []
    for i in range(len(target)):
        item = {"target": target[i]}
        if past:
            item["past_covariates"] = {k: v[i] for k, v in past.items()}
            item["future_covariates"] = {k: future[k][i] for k in future}
        inputs.append(item)
    return inputs


# --------------------------------------------------------------------------- init
def stage_init(_args) -> None:
    root = run_dir()
    root.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[1]
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=repo).stdout.strip() or None
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "experiments", "tests"], capture_output=True, text=True, cwd=repo).stdout.strip()
    _, tide_diag = fit_tide()
    t1_verdict = json.loads((T1_RUN / f"eval-{TAG}-stride15" / "verdict.json").read_text(encoding="utf-8"))
    inputs = {"snapshots": SNAPSHOTS, "sea_level": SEA_LEVEL, **{f"t1:{m}": T1_RUN / f"fm-{TAG}-{m}-stride15.parquet" for m in STORED_T1}, **t1.input_files()}
    t1._write(root / "preregistration.json", {
        "question": "Paper 1 / T2 (H1): does Chronos-2 with as-issued reconstructed weather + harmonic tide + calendar covariates, forecasting the 7-day diurnal anomaly, beat ridge B5D at 6-12 h on NB1?",
        "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "git_head": head, "worktree_dirty": bool(dirty),
        "code_sha256": {"paper1_t2_chronos2_cov.py": _sha256(Path(__file__)), "paper1_t1_chronos2.py": _sha256(Path(t1.__file__)), "foundation_zero_shot.py": _sha256(Path(fz.__file__))},
        "models": {m: {"repo": r, "revision": rev} for m, (r, rev) in t1.CHRONOS2.items()},
        "primary": {"model": PRIMARY_MODEL, "config": PRIMARY_CONFIG, "stride": 15, "size_rule_source": t1_verdict.get("size_for_T2")},
        "configs": CONFIGS, "run_plan": [{"model": m, "config": c, "stride": s} for m, c, s in RUN_PLAN],
        "run_plan_note": "Covariates cost ~(1 + n_cov)x (synthetic timing 2026-10-28: 9 covariates ~15x T1). The primary runs at stride 15 (H1.4 origins); ablations and the base size check at stride 60 (subset of the same origins, H1.4 TimesFM stride).",
        "covariates": {
            "weather": {"variables": list(WEATHER_VARS), "source": str(SNAPSHOTS), "provenance": "reconstructed_run (Open-Meteo Previous Runs, decision #13)",
                        "rule": "value at hour tau for origin t from the run with the largest retrieved_at <= min(t, tau + 12 h); future hours = latest run retrieved by t (join_as_issued semantics); hourly values linearly interpolated to window centres",
                        "dropped": "relative_humidity_2m, surface_pressure, wind_direction_10m (cost; B5D uses all seven)"},
            "tide": {"method": "least-squares harmonic fit, frozen", "constituents": TIDE_SPEEDS, "fit_window_end": str(TIDE_FIT_END), "source": str(SEA_LEVEL),
                     "note": "fit on modelled Open-Meteo marine sea level, not a tide gauge; K2/P1 omitted (need ~182 days)", "diagnostics": tide_diag},
            "calendar": ["hour_sin", "hour_cos (Asia/Ho_Chi_Minh local hour at window centre)"],
            "nan_rule": "covariate arrays must be finite (asserted)"},
        "anomaly": {"definition": "target window mean minus the mean of the same step-window shifted back 1..7 days (nanmean); the forecast anomaly quantile paths get the future profile added back before horizon interpolation",
                    "causality": "every shifted window ends <= issued - 1 min (asserted; step * prediction_length <= 1440)",
                    "fallback": "origins with any NaN future profile use the raw context and no profile (direct), counted in meta"},
        "station": fz.STATION, "target": TAG, "horizons_minutes": list(fz.HORIZONS), "step_for_horizon": fz.STEP_FOR_HORIZON, "context_steps": fz.CONTEXT_STEPS,
        "point_forecast": "median path interpolated at issued_at + h (as T1)", "quantiles_saved": list(t1.QUANTILES), "threads": THREADS, "batch_target_series": BATCH,
        "information_set": "target context ends at the 1-minute bin floor(issued_at - 1 min) (foundation_zero_shot.assert_no_lookahead); weather runs retrieved_at <= issued_at (asserted); future weather hourly values equal join_as_issued on a sample (asserted)",
        "origins": "T1 / H1.4 origins (baseline-Temperature persistence rows, stride 15 or thinned to 60)",
        "pilot": "--limit N samples rolling-fold origins only; timing only, never evaluated",
        "references": {"stride15": ["persistence", *[f"ridge_{s}" for s in RIDGE_SETS], *STORED_FM, *STORED_T1], "stride60_extra": ["timesfm-2.5-200m"]},
        "main_reference_note": "HANDOFF-paper1.md names ridge B5D the main reference at 6-12 h; 2026-10-27-sota-and-plan.md:183 says B5D_nopH at 3/6/12 h. HANDOFF (newer) is followed; the B5D_nopH readout is secondary.",
        "inputs_sha256": {k: _sha256(p) for k, p in inputs.items()},
        "verdict_rules": VERDICT_RULES,
        "caveats": "lockbox 2026-10-10..24 already opened for H1.4 / H1.9 / T1; step and context inherited from those runs",
    })
    print(root)


# --------------------------------------------------------------------------- forecast
class Chronos2CovForecaster(t1.Chronos2Forecaster):
    def quantile_paths_cov(self, target: np.ndarray, past: dict, future: dict, length: int, batch: int) -> np.ndarray:
        out = []
        for i in range(0, len(target), batch):
            sl = slice(i, i + batch)
            inputs = as_inputs(target[sl], {k: v[sl] for k, v in past.items()}, {k: v[sl] for k, v in future.items()})
            quantiles, _ = self.pipe.predict_quantiles(inputs, prediction_length=length, quantile_levels=list(t1.QUANTILES), batch_size=batch * (1 + len(past)))
            out.append(t1.stack_quantiles(quantiles))
        return np.concatenate(out)


def check_future_parity(weather: WeatherAsIssued, snapshots: pd.DataFrame, issued: pd.Series, n: int = 50) -> int:
    """Future hourly weather must equal ``join_as_issued`` for (issued_at, valid_at) pairs."""
    from experiments.forecast_external_context import join_as_issued

    sample = issued.drop_duplicates().sample(min(n, issued.nunique()), random_state=2).reset_index(drop=True)
    valid = sample.dt.floor("h") + pd.to_timedelta(np.random.default_rng(3).integers(1, 13, len(sample)), unit="h")
    frame = pd.DataFrame({"issued_at": sample, "valid_at": valid, "station": fz.STATION})
    joined = join_as_issued(frame, snapshots, prefix="ext")
    hours = ((valid - weather.h0) / pd.Timedelta(hours=1)).to_numpy().astype(int)[:, None]
    mine, _ = weather.hourly(sample.dt.tz_convert(None).to_numpy(), hours)
    for j, var in enumerate(weather.variables):
        ref = pd.to_numeric(joined[f"ext_{var}"], errors="coerce").to_numpy(dtype=float)
        if not np.allclose(mine[:, 0, j], ref, equal_nan=True):
            raise AssertionError(f"weather_parity:{var}")
    return len(sample)


def stage_forecast(args) -> None:
    from experiments.forecast_external_context import read_snapshots
    from experiments.forecast_sensor_v2 import load_sensor_data, truncate_local_date

    root = run_dir()
    if not (root / "preregistration.json").exists():
        raise FileNotFoundError("run_init_first")
    out = forecast_path(args.model, args.config, args.stride, args.limit)
    if out.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out}")
    cfg = CONFIGS[args.config]
    base = t1.FM_RUN / f"baseline-{TAG}"
    base_manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    origins = fz.load_origins(base, args.stride)
    if args.limit:
        rolling = origins.loc[origins["split"].astype(str).eq("rolling"), "issued_at"].drop_duplicates()
        origins = origins[origins["issued_at"].isin(rolling.sample(args.limit, random_state=0))]
    raw = truncate_local_date(load_sensor_data(Path(base_manifest["input"]), fz.STATION), base_manifest.get("last_local_date"))
    grid = fz.Grid(raw, TAG)
    horizons = sorted(origins["horizon_minutes"].unique().tolist())
    steps = sorted({fz.STEP_FOR_HORIZON[h] for h in horizons})
    leak_checked = fz.assert_no_lookahead(raw, TAG, grid, origins["issued_at"].drop_duplicates(), steps)
    weather = tide = None
    tide_diag, parity = None, None
    if "weather" in cfg["covariates"]:
        snaps = read_snapshots(SNAPSHOTS)
        weather = WeatherAsIssued(snaps[snaps["station"].eq(fz.STATION)])
        parity = check_future_parity(weather, snaps, origins["issued_at"])
    if "tide" in cfg["covariates"]:
        tide, tide_diag = fit_tide()
    repo, revision = t1.CHRONOS2[args.model]
    t0 = time.perf_counter()
    model = Chronos2CovForecaster(repo, revision, THREADS)
    load_seconds = time.perf_counter() - t0
    blocks, timing = [], []
    for step in steps:
        step_h = [h for h in horizons if fz.STEP_FOR_HORIZON[h] == step]
        issued = origins.loc[origins["horizon_minutes"].isin(step_h), "issued_at"].drop_duplicates().sort_values().reset_index(drop=True)
        n_ctx = fz.CONTEXT_STEPS[step]
        context = grid.contexts(issued, step, n_ctx)
        length = fz.prediction_length(step, step_h)
        fallback = np.zeros(len(issued), dtype=bool)
        profile = np.zeros((len(issued), length))
        target = context
        if cfg["anomaly"]:
            target, profile, fallback = anomaly_target(grid, issued, step, context, length)
        past, future, wdiag = covariate_arrays(cfg["covariates"], issued, step, n_ctx, length, weather, tide)
        t1_ = time.perf_counter()
        paths_q = add_profile(model.quantile_paths_cov(target, past, future, length, BATCH), profile)
        seconds = time.perf_counter() - t1_
        timing.append({"step_minutes": step, "context_steps": n_ctx, "prediction_length": length, "n_forecasts": len(issued), "n_covariates": len(past),
                       "seconds": seconds, "seconds_per_1000": 1000 * seconds / max(len(issued), 1), "context_nan_fraction": float(np.isnan(target).mean()),
                       "anomaly_fallback": int(fallback.sum()), **wdiag})
        print(json.dumps(timing[-1]), flush=True)
        for h in step_h:
            block = {"horizon_minutes": h, "issued_at": issued}
            for j, level in enumerate(t1.QUANTILES):
                block[t1.quantile_column(level)] = fz.interpolate_horizon(paths_q[:, :, j], step, h)
            blocks.append(pd.DataFrame(block))
    preds = pd.concat(blocks, ignore_index=True)
    preds["prediction"] = preds[t1.quantile_column(0.5)]
    preds = origins.merge(preds, on=["horizon_minutes", "issued_at"], how="left", validate="one_to_one")
    preds["model"] = model_name(args.model, args.config)
    preds.to_parquet(out, index=False)
    n_origins = int(origins["issued_at"].nunique())
    meta = {"model": args.model, "config": args.config, "config_spec": cfg, "repo": repo, "revision": revision, "stride_minutes": args.stride,
            "threads": THREADS, "batch_target_series": BATCH, "load_seconds": load_seconds, "timing": timing, "n_origin_rows": len(preds), "n_unique_origins": n_origins,
            "seconds_per_origin_all_horizons": sum(t["seconds"] for t in timing) / max(n_origins, 1), "limit": args.limit,
            "missing_predictions": int(preds["prediction"].isna().sum()), "lookahead_check_origins": leak_checked, "weather_parity_origins": parity,
            "tide": tide_diag, "python": sys.version, "platform": platform.platform(), "cpu_count": os.cpu_count(),
            "env_threads": {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS")}, "packages": fz._versions()}
    t1._write(out.with_suffix(".json"), meta)
    print(json.dumps({k: meta[k] for k in ("model", "config", "n_origin_rows", "missing_predictions", "seconds_per_origin_all_horizons")}))


# --------------------------------------------------------------------------- evaluate
ABLATIONS = (("anom-full", "anom-cal-weather", "tide"), ("anom-cal-weather", "anom-cal", "weather"), ("anom-cal", "anom", "calendar"),
             ("anom", "T1", "anomaly_no_cov"), ("anom-full", "direct-full", "anomaly_with_cov"))


def h1_verdict(table: pd.DataFrame, candidate: str, reference: str = B5D) -> dict:
    part = table[(table.candidate == candidate) & (table.reference == reference)].set_index("horizon_minutes")
    rows = {int(h): {"mae_ratio": float(part.loc[h, "mae_ratio"]), "gate16": bool(part.loc[h, "outcome"] == "chronos2_wins")} for h in (360, 720) if h in part.index}
    holds = len(rows) == 2 and all(r["mae_ratio"] <= 0.95 and r["gate16"] for r in rows.values())
    return {"candidate": candidate, "reference": reference, "horizons": rows, "H1_holds": bool(holds)}


def stage_evaluate(args) -> None:
    from experiments.forecast_h1_diurnal import _load_predictions

    root = run_dir()
    out = root / f"eval-{TAG}-stride{args.stride}"
    if out.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out}")
    sources = {model_name(m, c): forecast_path(m, c, s) for m, c, s in RUN_PLAN if s == args.stride and forecast_path(m, c, s).exists()}
    if not sources:
        raise FileNotFoundError("no_t2_forecasts")
    stored = {m: t1.FM_RUN / f"fm-{TAG}-{m}-stride15.parquet" for m in STORED_FM}
    stored.update({m: T1_RUN / f"fm-{TAG}-{m}-stride15.parquet" for m in STORED_T1})
    if args.stride % 60 == 0:
        stored["timesfm-2.5-200m"] = t1.FM_RUN / f"fm-{TAG}-timesfm-2.5-200m-stride60.parquet"
    pred = _load_predictions(t1.DIURNAL_BENCH / "predictions.parquet")
    pred = pred[fz.thin_mask(pred["issued_at"], args.stride)]
    wide = t1._ridge_wide(pred, RIDGE_SETS)
    wide["split"] = wide["split"].astype(str)
    checks = {}
    for name, path in {**stored, **sources}.items():
        fm = pd.read_parquet(path)
        wide, checks[name] = t1.merge_model(wide, fm[fz.thin_mask(fm["issued_at"], args.stride)], name)
    models = [c for c in wide.columns if c.startswith("ridge_")] + list(stored) + list(sources)
    before = len(wide)
    wide = wide.dropna(subset=models)
    checks["rows_kept"] = {"before": before, "after": int(len(wide))}
    metrics, dm, gate = fz.evaluate_frame(wide, [], models, args.stride)
    t2 = list(sources)
    references = ["persistence", *[c for c in models if c not in t2]]
    table = pd.concat([t1.verdicts(gate, metrics, cand, references + [c for c in t2 if c != cand]) for cand in t2], ignore_index=True)
    table["primary"], table["holm_p"] = False, np.nan
    primary = model_name(PRIMARY_MODEL, PRIMARY_CONFIG)
    verdict = {"summary": t1.summarise(table)}
    if args.stride == 15 and primary in t2:
        mask = table.candidate.eq(primary) & table.reference.isin([B5D, "chronos-2-small"])
        table.loc[mask, "primary"] = True
        table.loc[mask, "holm_p"] = t1.holm(table.loc[mask, "lockbox_dm_p"])
        verdict["H1"] = h1_verdict(table, primary)
        verdict["H1_secondary_B5D_nopH"] = h1_verdict(table, primary, B5D + "_nopH")
    abl = {}
    for cand, ref, label in ABLATIONS:
        c = model_name(PRIMARY_MODEL, cand)
        r = "chronos-2-small" if ref == "T1" else model_name(PRIMARY_MODEL, ref)
        part = table[(table.candidate == c) & (table.reference == r)]
        if not part.empty:
            abl[label] = {"candidate": c, "reference": r, **t1.summarise(part)[f"{c}__vs__{r}"],
                          "mae_ratio": part.set_index("horizon_minutes")["mae_ratio"].round(4).to_dict()}
    size = table[(table.candidate == model_name("chronos-2-base", "anom-full")) & (table.reference == model_name("chronos-2-small", "anom-full"))]
    if not size.empty:
        abl["size_base_vs_small"] = {"mae_ratio": size.set_index("horizon_minutes")["mae_ratio"].round(4).to_dict(), **t1.summarise(size)[f"{size.candidate.iloc[0]}__vs__{size.reference.iloc[0]}"]}
    verdict["ablations"] = abl
    out.mkdir(parents=False, exist_ok=False)
    summary = fz.summary_table(metrics, dm, gate)
    for name, frame in zip(("metrics", "dm_tests", "gate16", "summary", "verdicts"), (metrics, dm, gate, summary, table)):
        t1._write(out / f"{name}.csv", frame)
    lock = metrics[metrics["split"].astype(str).eq("lockbox")].pivot(index="horizon_minutes", columns="model", values="mae")
    t1._write(out / "lockbox_mae.csv", lock.reset_index())
    t1._write(out / "verdict.json", verdict)
    t1._write(out / "manifest.json", {"stride_minutes": args.stride, "t2_sources": {m: str(p) for m, p in sources.items()},
                                          "t2_sha256": {m: _sha256(p) for m, p in sources.items()}, "stored_sources": {m: str(p) for m, p in stored.items()},
                                          "stored_sha256": {m: _sha256(p) for m, p in stored.items()}, "diurnal_bench_sha256": _sha256(t1.DIURNAL_BENCH / "predictions.parquet"),
                                          "origin_checks": checks, "verdict_rules": VERDICT_RULES})
    print(lock.round(4).to_string())
    print(json.dumps(verdict, indent=1, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="stage", required=True)
    sub.add_parser("init")
    p = sub.add_parser("forecast")
    p.add_argument("--model", required=True, choices=tuple(t1.CHRONOS2))
    p.add_argument("--config", required=True, choices=tuple(CONFIGS))
    p.add_argument("--stride", type=int, required=True, choices=(15, 60))
    p.add_argument("--limit", type=int, help="pilot: random rolling-fold origins (timing only, never evaluated)")
    p = sub.add_parser("evaluate")
    p.add_argument("--stride", type=int, required=True, choices=(15, 60))
    args = parser.parse_args()
    {"init": stage_init, "forecast": stage_forecast, "evaluate": stage_evaluate}[args.stage](args)


if __name__ == "__main__":
    main()
