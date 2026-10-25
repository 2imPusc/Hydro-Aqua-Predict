"""H1.7: foreign pretraining + NB1 fine-tuning vs NB1-only forecasts (research-only, shadow).

Question (owner, 2026-10-25): NB1 (06M26042804) has 5 months of history and no winter.  Does
pretraining on multi-year foreign coastal sonde data and fine-tuning on NB1 beat NB1-only models
on NB1, especially when the test period lies outside the NB1 training range?

Pre-registered design (fixed before any test result was looked at)
------------------------------------------------------------------
Data
  * NB1: frozen ``sensor-history-20261024`` loaded with ``forecast_sensor_v2.load_sensor_data``
    (same QC as the benchmark).  pH truncated at the ``baseline-pH-pre-drift`` end (18/09, RL-13).
  * Foreign: NERRS SWMP (NCEI 0052765), 8 reserves (job rkb apa gtm mar gnd wkb sap), all 2007-2011
    WQ stations, 15-min sonde readings, CDMO flag ``<0>`` only (``nerrs_load.read_wq_file``), plausibility
    Temp in [-2, 40] C, pH in [6, 9.5].  Other foreign sets on disk (TWDB hourly, MDDNR temperate,
    IRLON, USGS SF Bay) are not used: one homogeneous 15-min QC'd source keeps the step identical.
  * Targets: Temperature (primary, horizons 15/60/180/360/720 min) and pH on the pre-drift period
    (60/180 min, the horizons of ``baseline-pH-pre-drift``).  TSS is left out (foreign turbidity is NTU,
    NB1 TSS is mg/L; no defensible mapping).  NH4 has no continuous foreign analogue (skipped).
Representation (identical for every model and site)
  * Common step 15 min.  Point series p[i] at 15-min marks: foreign = the sonde reading at the mark;
    NB1 = mean of the 1-minute bins [mark-3, mark-1] (data strictly before the mark).  For a benchmark
    origin issued at t, mark T = floor(t, min) (stride-15 origins sit on marks), so p[T] uses only bins
    <= floor(t - 1 min): the ridge ``lag_1m`` information set.  Asserted on 20 random origins by
    rebuilding the features from raw data truncated at the cutoff.
  * Target = delta: y(T + h) - p[T] (native units, C or pH).  NB1 training label y = mean of the 1-min
    bins [T+h-2, T+h+2]; evaluation uses the benchmark ``actual``.  Translation-invariant by construction.
  * Features (25): deltas to p[T] of lags 15/30/45/60/90/120/180/240/360/480/720 min; same time of day
    as the target 24 h / 48 h back (``s24``, ``s48``) and as now 24 h back (``y24``); 7-day mean diurnal
    profile change P(T+h) - P(T) (``prof7``, >= 3 days); trailing-24 h range, std, mean - p, trailing-7-day
    mean - p; ``diurnal_missing`` flag; hour of day (local standard time: NB1 UTC+7, NERRS per-reserve
    LST) at T and at T+h as sin/cos; day-of-year sin/cos.
  * Linear / MLP inputs: NaN -> training median, then standardised; statistics fitted on the rows the
    model is fitted on (foreign pretraining rows for transfer variants, the split's NB1 training rows for
    NB1-only) - never on test rows.
Model families (every family: NB1-only, foreign-only zero-shot, foreign-pretrain + NB1-fine-tune; two
foreign site sets ``all`` and ``sim``)
  * ridge: NB1-only Ridge (lambda in {0.1, 1, 10, 100, 1000}); foreign Ridge (lambda 1); fine-tune =
    ridge shrunk towards the foreign weights, min |y - Xw|^2 + lambda |w - w_foreign|^2
    (lambda in {1, 10, 1e2, 1e3, 1e4, 1e5}).
  * xgb: NB1-only (depth 4, eta .05, <= 1500 rounds); foreign (depth 6, eta .1, mcw 50, <= 800 rounds,
    early stop on foreign year 2011); fine-tune = continued boosting from the foreign booster
    (depth 4, eta .03, 0..600 extra rounds in steps of 10, 0 allowed).  Control ``xgb-nb1-abs``:
    NB1-only, *absolute* target with the level p[T] as an extra feature - the representation of the old
    runtime XGBoost that never predicted below 29.15 C.  It separates "the delta representation fixed
    the out-of-range failure" from "foreign data fixed it".
  * mlp (torch, ``.venv-fm`` only): 25-128-128-1 GELU (~20k parameters), AdamW wd 1e-4.  Pretrain
    lr 1e-3, batch 1024, <= 10 epochs, best epoch on foreign year 2011.  NB1-only: lr 1e-3, batch 256,
    <= 60 epochs.  Fine-tune: 5 epochs head-only (lr 1e-3) then all layers lr 1e-4, 0..40 epochs.
    Mean of seeds 0/1/2.
  * Chronos-Bolt fine-tuning (family c) is skipped: not cheap on 4 CPU cores; zero-shot Chronos is a
    reference instead.
  * Every NB1 choice (lambda, rounds, epochs) uses an inner validation = the last 7 days of the split's
    NB1 training rows (fit rows purged by max(60 min, h) before it), MAE criterion, then a refit on all
    training rows with the chosen value.  Nothing is tuned on fold, lockbox or Eval-B test rows.
  * Foreign origins: every valid mark, thinned to a fixed 1/8 random subset (seed = horizon) to bound
    CPU; pretraining happens once per (target, horizon, site set), never inside the fold loop.
Site selection (``sim``), fixed rule: stations with >= 50,000 valid temperature readings and median
  salinity >= 15 PSU, ranked by |p5 - p5_NB1| + |p95 - p95_NB1| of temperature, where the NB1 values
  come from the OISST daily climatology 1991-2020 at 20.625 N 107.125 E (no NB1 sensor data); top 8.
  The selected list is written by ``prepare`` before any model is fitted.
Evaluation A (standard): the stride-15 origins of ``foundation-zero-shot-20261024/baseline-<tag>``
  (= ``forecast_sensor_v2.run_benchmark`` folds, purge, 14-day lockbox).  NB1 training rows for fold k:
  valid_at < fold start - max(60 min, h); lockbox: valid_at < lockbox start - purge.  References on the
  same origins: persistence, ridge B4 / B4_nopH (saved predictions), diurnal-anomaly-7d, Chronos-Bolt
  base (Temperature) / small (pH) zero-shot (saved ``fm-*`` predictions; nothing recomputed).  Gate #16
  (``foundation_zero_shot.evaluate_frame``: >= 4/5 folds better MAE and RMSE + lockbox DM abs loss,
  rectangular kernel, HLN, p < 0.05).  "Best NB1-only" per horizon = lowest mean rolling-fold MAE among
  {ridge B4, ridge B4_nopH, diurnal-anomaly-7d, ridge-nb1, xgb-nb1, xgb-nb1-abs, mlp-nb1} - folds only.
Evaluation B (season shift, Temperature only): NB1 training rows valid_at < 2026-09-01 00:00 local
  (29/05-31/08, warm season), test = the same benchmark origins issued 15/09-24/10 local.  Metrics, DM
  over all test origins (HLN), and weekly blocks (from 15/09) won on MAE and RMSE as the fold analogue.
  Out-of-range share: actual outside the NB1 training-label envelope (min/max and p1/p99) of 29/05-31/08.
  pH has no Eval B: 15/09-24/10 is the pH drift period (RL-13).
Regime: origins with trailing-24 h range ``amp24`` > 3.0 C = "large diurnal" (RL-57: range grew ~5x from
  mid-August; summer weekly median range 1.5-2.2 C).

Stages (run from the repo root; HAP_* env vars may point at the main checkout's data/artifacts):
    .venv/Scripts/python experiments/transfer_forecast.py prepare  --run-name transfer-forecast-20261025
    .venv/Scripts/python experiments/transfer_forecast.py features --run-name ... --target Temperature
    .venv/Scripts/python experiments/transfer_forecast.py fit      --run-name ... --target Temperature --family ridge|xgb
    .venv-fm/Scripts/python experiments/transfer_forecast.py fit   --run-name ... --target Temperature --family mlp
    .venv/Scripts/python experiments/transfer_forecast.py evaluate --run-name ... --target Temperature --eval A|B
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402

STATION = "06M26042804"
NB1_UTC_OFFSET_H = 7
BASE_RUN = "foundation-zero-shot-20261024"
SENSOR_CSV = paths.EXPERIMENT_OUTPUT_DIR / "sensor-history-20261024" / f"{STATION}.csv"
OISST_CSV = paths.DATA_DIR / "hazards" / "sst" / "oisst_20.625_107.125_1982_20261020.csv"
TARGETS = {
    # target -> (baseline tag, horizons, foreign column, plausible range, chronos reference)
    "Temperature": ("Temperature", (15, 60, 180, 360, 720), "Temp", (-2.0, 40.0), "chronos-bolt-base"),
    "pH": ("pH-pre-drift", (60, 180), "pH", (6.0, 9.5), "chronos-bolt-small"),
}
STEP = 15
DAY = 96  # 15-min steps per day
LAG_STEPS = (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48)
FEATURES = [f"d{k * STEP}" for k in LAG_STEPS] + ["s24", "s48", "y24", "prof7", "amp24", "std24", "mean24", "mean7d", "diurnal_missing", "hod_sin", "hod_cos", "hodv_sin", "hodv_cos", "doy_sin", "doy_cos"]
FOREIGN_FRACTION = 8
FOREIGN_HOLDOUT_YEAR = 2011
INNER_VAL_DAYS = 7
EVAL_B_TRAIN_END = pd.Timestamp("2026-09-01 00:00", tz="Asia/Ho_Chi_Minh").tz_convert("UTC")
EVAL_B_TEST_START = pd.Timestamp("2026-09-15 00:00", tz="Asia/Ho_Chi_Minh").tz_convert("UTC")
LARGE_DIURNAL_C = 3.0
SIM_TOP_K, SIM_MIN_SAL, SIM_MIN_N = 8, 15.0, 50_000
RIDGE_NB1_LAMBDAS = (0.1, 1.0, 10.0, 100.0, 1000.0)
RIDGE_FT_LAMBDAS = (1.0, 10.0, 1e2, 1e3, 1e4, 1e5)
SEEDS = (0, 1, 2)


def run_dir(name: str) -> Path:
    return paths.EXPERIMENT_OUTPUT_DIR / name


def _write_new(path: Path, writer) -> None:
    if path.exists():
        raise FileExistsError(f"refusing_to_overwrite:{path}")
    writer(path)


def _write_json(path: Path, obj) -> None:
    _write_new(path, lambda p: p.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _versions() -> dict:
    from importlib.metadata import PackageNotFoundError, version

    found = {"python": sys.version.split()[0], "platform": platform.platform()}
    for name in ("numpy", "pandas", "scikit-learn", "xgboost", "torch", "pyarrow"):
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            pass
    return found


# --------------------------------------------------------------------------- series + features
class Series15:
    """Regular 15-minute point series of one site and the causal rolling statistics on it."""

    def __init__(self, p: np.ndarray, y: np.ndarray, start_utc: pd.Timestamp, utc_offset_h: float, name: str = ""):
        if start_utc.minute % STEP or start_utc.second:
            raise ValueError("series_start_not_on_15min_mark")
        self.p, self.y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
        self.start, self.offset, self.name = start_utc, float(utc_offset_h), name
        s = pd.Series(self.p)
        r96 = s.rolling(DAY, min_periods=DAY // 2)  # window ends at i inclusive: causal
        self.max96, self.min96, self.std96, self.mean96 = (r96.max().to_numpy(), r96.min().to_numpy(), r96.std().to_numpy(), r96.mean().to_numpy())
        self.mean672 = s.rolling(7 * DAY, min_periods=7 * DAY // 2).mean().to_numpy()

    def index_of(self, marks_utc: pd.Series | pd.DatetimeIndex) -> np.ndarray:
        delta = (pd.DatetimeIndex(marks_utc) - self.start).total_seconds().to_numpy() / 60
        if np.any(delta % STEP):
            raise ValueError("origin_not_on_15min_mark")
        return (delta // STEP).astype(np.int64)

    def _at(self, j: np.ndarray) -> np.ndarray:
        out = np.full(len(j), np.nan)
        ok = (j >= 0) & (j < len(self.p))
        out[ok] = self.p[j[ok]]
        return out

    def features(self, idx: np.ndarray, horizon: int) -> pd.DataFrame:
        """Feature rows for origins at mark indices ``idx``; reads only p[<= idx]."""
        idx = np.asarray(idx, dtype=np.int64)
        hs = horizon // STEP
        if hs * STEP != horizon or hs >= DAY:
            raise ValueError("horizon_must_be_multiple_of_15_below_one_day")
        c = self._at(idx)
        f = {f"d{k * STEP}": self._at(idx - k) - c for k in LAG_STEPS}
        f["s24"] = self._at(idx + hs - DAY) - c
        f["s48"] = self._at(idx + hs - 2 * DAY) - c
        f["y24"] = self._at(idx - DAY) - c
        future = np.stack([self._at(idx + hs - DAY * d) for d in range(1, 8)])
        now = np.stack([self._at(idx - DAY * d) for d in range(1, 8)])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN columns -> NaN
            prof = np.nanmean(future, axis=0) - np.nanmean(now, axis=0)
        enough = (np.isfinite(future).sum(0) >= 3) & (np.isfinite(now).sum(0) >= 3)
        f["prof7"] = np.where(enough, prof, np.nan)
        safe = np.clip(idx, 0, len(self.p) - 1)
        f["amp24"] = self.max96[safe] - self.min96[safe]
        f["std24"] = self.std96[safe]
        f["mean24"] = self.mean96[safe] - c
        f["mean7d"] = self.mean672[safe] - c
        f["diurnal_missing"] = (~np.isfinite(f["s24"]) | ~np.isfinite(f["prof7"]) | ~np.isfinite(f["mean7d"])).astype(float)
        local = self.start + pd.to_timedelta(idx * STEP + self.offset * 60, unit="min")
        hour = (local.hour + local.minute / 60).to_numpy(dtype=float)
        hour_v = (hour + horizon / 60) % 24
        doy = local.dayofyear.to_numpy(dtype=float)
        f["hod_sin"], f["hod_cos"] = np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24)
        f["hodv_sin"], f["hodv_cos"] = np.sin(2 * np.pi * hour_v / 24), np.cos(2 * np.pi * hour_v / 24)
        f["doy_sin"], f["doy_cos"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)
        out = pd.DataFrame(f)[FEATURES]
        out["current"] = c
        out["issued_at"] = self.start + pd.to_timedelta(idx * STEP, unit="min")
        out["valid_at"] = out["issued_at"] + pd.Timedelta(minutes=horizon)
        future_y = np.full(len(idx), np.nan)
        ok = (idx + hs >= 0) & (idx + hs < len(self.y))
        future_y[ok] = self.y[idx[ok] + hs]
        out["y_future"] = future_y
        out["delta"] = future_y - c
        return out

    def training_rows(self, horizon: int) -> pd.DataFrame:
        frame = self.features(np.arange(len(self.p)), horizon)
        core = ["current", "d15", "d30", "d45", "d60", "delta"]
        return frame.dropna(subset=core).reset_index(drop=True)


def nb1_series(raw: pd.DataFrame, target: str) -> Series15:
    """NB1 1-minute grid -> p (mean of the 3 one-minute bins before each mark), y (5-min centred)."""
    from experiments.foundation_zero_shot import Grid

    grid = Grid(raw, target)
    first = (-grid.start.minute) % STEP  # first 15-min mark at or after the grid start
    # Up to the last mark whose 3-bin window still touches the grid, so a series truncated at an
    # origin's cutoff still has that origin's mark even when the last minutes are empty.
    marks = first + np.arange(0, (grid.n + 2 - first) // STEP + 1) * STEP
    p = grid.window_mean(marks, 3)          # bins [mark-3, mark-1]
    y = grid.window_mean(marks + 3, 5)      # bins [mark-2, mark+2]
    return Series15(p, y, grid.start + pd.Timedelta(minutes=int(first)), NB1_UTC_OFFSET_H, "NB1")


def origin_features(series: Series15, issued: pd.Series, horizon: int) -> pd.DataFrame:
    """Features at benchmark origins: mark = floor(issued_at, minute) (stride-15 origins sit on marks)."""
    marks = issued.dt.floor("min")
    out = series.features(series.index_of(marks), horizon)
    out["issued_at"] = issued.to_numpy()
    return out.drop(columns=["valid_at", "y_future", "delta"])


def assert_no_lookahead(raw: pd.DataFrame, target: str, series: Series15, issued: pd.Series, horizon: int, n: int = 20) -> int:
    """Features must equal those rebuilt from rows a ridge ``lag_1m`` feature could also see."""
    sample = issued.drop_duplicates().sample(min(n, issued.nunique()), random_state=1)
    full = origin_features(series, sample.reset_index(drop=True), horizon)
    for k, t in enumerate(sample):
        cutoff = (t - pd.Timedelta(minutes=1)).floor("min") + pd.Timedelta(minutes=1)
        assert cutoff <= t
        truncated = nb1_series(raw[raw["fetchedAt"] < cutoff], target)
        assert truncated.start == series.start
        part = origin_features(truncated, pd.Series([t]), horizon)
        a = full.iloc[[k]][FEATURES + ["current"]].to_numpy(dtype=float)
        b = part[FEATURES + ["current"]].to_numpy(dtype=float)
        if not np.allclose(a, b, equal_nan=True, rtol=0, atol=1e-9):
            raise AssertionError(f"lookahead_in_features:{t}:{horizon}")
    return len(sample)


# --------------------------------------------------------------------------- splits
def purge(horizon: int) -> pd.Timedelta:
    return max(pd.Timedelta(minutes=60), pd.Timedelta(minutes=int(horizon)))


def fold_starts(fold_check: list[dict], horizon: int) -> tuple[pd.Timestamp, dict[int, pd.Timestamp]]:
    """Lockbox start and rolling-fold test starts of the benchmark (B4_quality rows)."""
    rows = [r for r in fold_check if r["feature_set"] == "B4_quality" and int(r["horizon_minutes"]) == horizon]
    if not rows:
        raise ValueError(f"no_fold_rows:{horizon}")
    lock = pd.Timestamp(rows[0]["lockbox_start"])
    return lock, {int(r["fold"]): pd.Timestamp(r["test_issued_from"]) for r in rows}


def train_mask(frame: pd.DataFrame, test_start: pd.Timestamp, horizon: int) -> np.ndarray:
    """Training rows: label valid strictly before ``test_start - purge``."""
    return (frame["valid_at"] < test_start - purge(horizon)).to_numpy()


def inner_split(train: pd.DataFrame, horizon: int, days: int = INNER_VAL_DAYS) -> tuple[np.ndarray, np.ndarray]:
    """(fit, validation) masks inside a training set: validation = last ``days`` days of issue
    times, fit rows purged so no fit label is valid at or after validation start - purge."""
    val_start = train["issued_at"].max() - pd.Timedelta(days=days)
    val = (train["issued_at"] >= val_start).to_numpy()
    fit = (train["valid_at"] < val_start - purge(horizon)).to_numpy()
    return fit, val


def eval_b_masks(train_frame: pd.DataFrame, origins: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    return (train_frame["valid_at"] < EVAL_B_TRAIN_END).to_numpy(), (origins["issued_at"] >= EVAL_B_TEST_START).to_numpy()


# --------------------------------------------------------------------------- preprocessing / models
class Prep:
    """Median imputation + standardisation, fitted on the rows a model is fitted on."""

    def fit(self, X: pd.DataFrame) -> "Prep":
        values = X.to_numpy(dtype=float)
        self.columns = list(X.columns)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            self.median = np.nan_to_num(np.nanmedian(values, axis=0))
        filled = np.where(np.isfinite(values), values, self.median)
        self.mu, self.sd = filled.mean(0), filled.std(0)
        self.sd[self.sd < 1e-9] = 1.0
        return self

    def transform(self, X: pd.DataFrame) -> np.ndarray:
        values = X[self.columns].to_numpy(dtype=float)
        return (np.where(np.isfinite(values), values, self.median) - self.mu) / self.sd


def _mae(a, b) -> float:
    return float(np.mean(np.abs(np.asarray(a) - np.asarray(b))))


class RidgeFamily:
    name = "ridge"

    def pretrain(self, foreign: pd.DataFrame) -> dict:
        from sklearn.linear_model import Ridge

        prep = Prep().fit(foreign[FEATURES])
        model = Ridge(alpha=1.0).fit(prep.transform(foreign[FEATURES]), foreign["delta"])
        return {"prep": prep, "model": model}

    @staticmethod
    def zero_shot(pre: dict, X: pd.DataFrame) -> np.ndarray:
        return pre["model"].predict(pre["prep"].transform(X[FEATURES]))

    def nb1(self, train: pd.DataFrame, test: pd.DataFrame, horizon: int) -> tuple[np.ndarray, dict]:
        from sklearn.linear_model import Ridge

        fit, val = inner_split(train, horizon)
        prep = Prep().fit(train.loc[fit, FEATURES])
        scores = {lam: _mae(Ridge(alpha=lam).fit(prep.transform(train.loc[fit, FEATURES]), train.loc[fit, "delta"]).predict(prep.transform(train.loc[val, FEATURES])), train.loc[val, "delta"]) for lam in RIDGE_NB1_LAMBDAS}
        lam = min(scores, key=scores.get)
        prep = Prep().fit(train[FEATURES])
        model = Ridge(alpha=lam).fit(prep.transform(train[FEATURES]), train["delta"])
        return model.predict(prep.transform(test[FEATURES])), {"lambda": lam}

    def finetune(self, pre: dict, train: pd.DataFrame, test: pd.DataFrame, horizon: int) -> tuple[np.ndarray, dict]:
        fit, val = inner_split(train, horizon)
        scores = {lam: _mae(shrunk_ridge(pre, train[fit], lam)(train[val]), train.loc[val, "delta"]) for lam in RIDGE_FT_LAMBDAS}
        lam = min(scores, key=scores.get)
        return shrunk_ridge(pre, train, lam)(test), {"lambda": lam}


def shrunk_ridge(pre: dict, train: pd.DataFrame, lam: float):
    """argmin |y - Xw|^2 + lam |w - w_foreign|^2 (foreign preprocessing; intercept free)."""
    from sklearn.linear_model import Ridge

    X = pre["prep"].transform(train[FEATURES])
    residual = train["delta"].to_numpy() - pre["model"].predict(X)
    corr = Ridge(alpha=lam).fit(X, residual)
    return lambda frame: RidgeFamily.zero_shot(pre, frame) + corr.predict(pre["prep"].transform(frame[FEATURES]))


class XGBFamily:
    name = "xgb"
    NB1 = {"max_depth": 4, "eta": 0.05, "subsample": 0.8, "colsample_bytree": 0.8, "min_child_weight": 10, "objective": "reg:squarederror", "seed": 42, "nthread": 4}
    FOREIGN = {"max_depth": 6, "eta": 0.1, "subsample": 0.8, "colsample_bytree": 0.8, "min_child_weight": 50, "objective": "reg:squarederror", "seed": 42, "nthread": 4, "tree_method": "hist"}
    FT = {"max_depth": 4, "eta": 0.03, "subsample": 0.8, "colsample_bytree": 0.8, "min_child_weight": 10, "objective": "reg:squarederror", "seed": 42, "nthread": 4}

    def __init__(self):
        import xgboost as xgb

        self.xgb = xgb

    def _d(self, frame: pd.DataFrame, label: str | None = "delta", cols=FEATURES):
        return self.xgb.DMatrix(frame[cols].to_numpy(dtype=float), label=None if label is None else frame[label].to_numpy(dtype=float), missing=np.nan)

    def pretrain(self, foreign: pd.DataFrame) -> dict:
        hold = foreign["year"].eq(FOREIGN_HOLDOUT_YEAR).to_numpy()
        dfit, dval = self._d(foreign[~hold]), self._d(foreign[hold])
        booster = self.xgb.train(self.FOREIGN, dfit, num_boost_round=800, evals=[(dval, "hold")], early_stopping_rounds=50, verbose_eval=False)
        rounds = booster.best_iteration + 1
        booster = self.xgb.train(self.FOREIGN, self._d(foreign), num_boost_round=rounds)
        return {"booster": booster, "rounds": rounds}

    def zero_shot(self, pre: dict, X: pd.DataFrame) -> np.ndarray:
        return pre["booster"].predict(self._d(X, None))

    def _nb1_fit(self, train, label, cols, rounds=None):
        if rounds is None:
            fit, val = inner_split(train, int(train.attrs["horizon"]))
            dval = self._d(train[val], label, cols)
            booster = self.xgb.train(self.NB1, self._d(train[fit], label, cols), num_boost_round=1500, evals=[(dval, "val")], early_stopping_rounds=50, verbose_eval=False)
            return booster.best_iteration + 1
        return self.xgb.train(self.NB1, self._d(train, label, cols), num_boost_round=rounds)

    def nb1(self, train: pd.DataFrame, test: pd.DataFrame, horizon: int, absolute: bool = False) -> tuple[np.ndarray, dict]:
        train = train.copy(); train.attrs["horizon"] = horizon
        label, cols = ("y_future", FEATURES + ["current"]) if absolute else ("delta", FEATURES)
        rounds = self._nb1_fit(train, label, cols)
        booster = self._nb1_fit(train, label, cols, rounds)
        pred = booster.predict(self._d(test, None, cols))
        return (pred - test["current"].to_numpy()) if absolute else pred, {"rounds": rounds}

    def _continue(self, pre: dict, frame: pd.DataFrame, extra: int):
        base = pre["booster"].copy()
        if extra == 0:
            return base
        return self.xgb.train(self.FT, self._d(frame), num_boost_round=extra, xgb_model=base)

    def finetune(self, pre: dict, train: pd.DataFrame, test: pd.DataFrame, horizon: int) -> tuple[np.ndarray, dict]:
        fit, val = inner_split(train, horizon)
        booster = self._continue(pre, train[fit], 600)
        dval = self._d(train[val], None)
        n0 = pre["rounds"]
        truth = train.loc[val, "delta"].to_numpy()
        scores = {k: _mae(booster.predict(dval, iteration_range=(0, n0 + k)), truth) for k in range(0, 601, 10)}
        extra = min(scores, key=scores.get)
        final = self._continue(pre, train, extra)
        return final.predict(self._d(test, None)), {"extra_rounds": extra, "foreign_rounds": n0}


class MLPFamily:
    """Small MLP in torch (``.venv-fm`` only; torch imported lazily)."""

    name = "mlp"

    def __init__(self, threads: int = 4):
        import torch

        torch.set_num_threads(threads)
        self.torch = torch

    def _net(self, n_in: int, seed: int):
        nn = self.torch.nn
        self.torch.manual_seed(seed)
        return nn.Sequential(nn.Linear(n_in, 128), nn.GELU(), nn.Linear(128, 128), nn.GELU(), nn.Linear(128, 1))

    def _epochs(self, net, X, y, epochs, lr, batch, seed, params=None, Xv=None, yv=None):
        """Train ``epochs`` epochs; returns validation MAE (scaled units) after each epoch."""
        torch = self.torch
        opt = torch.optim.AdamW(params if params is not None else net.parameters(), lr=lr, weight_decay=1e-4)
        Xt, yt = torch.tensor(X, dtype=torch.float32), torch.tensor(y, dtype=torch.float32)[:, None]
        gen = torch.Generator().manual_seed(seed)
        history = []
        for _ in range(epochs):
            net.train()
            order = torch.randperm(len(Xt), generator=gen)
            for i in range(0, len(Xt), batch):
                sel = order[i:i + batch]
                opt.zero_grad()
                loss = torch.nn.functional.mse_loss(net(Xt[sel]), yt[sel])
                loss.backward()
                opt.step()
            if Xv is not None:
                history.append(_mae(self._predict(net, Xv), yv))
        return history

    def _predict(self, net, X) -> np.ndarray:
        net.eval()
        with self.torch.no_grad():
            return net(self.torch.tensor(X, dtype=self.torch.float32)).numpy()[:, 0]

    def pretrain(self, foreign: pd.DataFrame) -> dict:
        import copy

        prep = Prep().fit(foreign[FEATURES])
        scale = float(foreign["delta"].std()) or 1.0
        hold = foreign["year"].eq(FOREIGN_HOLDOUT_YEAR).to_numpy()
        X, y = prep.transform(foreign[FEATURES]), foreign["delta"].to_numpy() / scale
        net = self._net(len(FEATURES), 0)
        best, best_state, best_epoch = np.inf, None, 0
        for epoch in range(1, 11):
            score = self._epochs(net, X[~hold], y[~hold], 1, 1e-3, 1024, epoch, Xv=X[hold], yv=y[hold])[0]
            if score < best:
                best, best_state, best_epoch = score, copy.deepcopy(net.state_dict()), epoch
        net.load_state_dict(best_state)
        return {"prep": prep, "scale": scale, "net": net, "epochs": best_epoch}

    def zero_shot(self, pre: dict, X: pd.DataFrame) -> np.ndarray:
        return self._predict(pre["net"], pre["prep"].transform(X[FEATURES])) * pre["scale"]

    def nb1(self, train: pd.DataFrame, test: pd.DataFrame, horizon: int) -> tuple[np.ndarray, dict]:
        fit, val = inner_split(train, horizon)
        preds, chosen = [], []
        for seed in SEEDS:
            prep = Prep().fit(train.loc[fit, FEATURES]); scale = float(train.loc[fit, "delta"].std()) or 1.0
            net = self._net(len(FEATURES), seed)
            hist = self._epochs(net, prep.transform(train.loc[fit, FEATURES]), train.loc[fit, "delta"].to_numpy() / scale, 60, 1e-3, 256, seed, Xv=prep.transform(train.loc[val, FEATURES]), yv=train.loc[val, "delta"].to_numpy() / scale)
            epochs = int(np.argmin(hist)) + 1
            prep = Prep().fit(train[FEATURES]); scale = float(train["delta"].std()) or 1.0
            net = self._net(len(FEATURES), seed)
            self._epochs(net, prep.transform(train[FEATURES]), train["delta"].to_numpy() / scale, epochs, 1e-3, 256, seed)
            preds.append(self._predict(net, prep.transform(test[FEATURES])) * scale)
            chosen.append(epochs)
        return np.mean(preds, axis=0), {"epochs": chosen}

    def _finetune_net(self, pre, X, y, seed, epochs, Xv=None, yv=None):
        import copy

        net = copy.deepcopy(pre["net"])
        head = list(net[-1].parameters())
        self._epochs(net, X, y, 5, 1e-3, 256, seed, params=head)
        hist = [_mae(self._predict(net, Xv), yv)] if Xv is not None else []
        hist += self._epochs(net, X, y, epochs, 1e-4, 256, seed + 100, Xv=Xv, yv=yv)
        return net, hist

    def finetune(self, pre: dict, train: pd.DataFrame, test: pd.DataFrame, horizon: int) -> tuple[np.ndarray, dict]:
        fit, val = inner_split(train, horizon)
        prep, scale = pre["prep"], pre["scale"]
        X, y = prep.transform(train[FEATURES]), train["delta"].to_numpy() / scale
        preds, chosen = [], []
        for seed in SEEDS:
            _, hist = self._finetune_net(pre, X[fit], y[fit], seed, 40, X[val], y[val])
            epochs = int(np.argmin(hist))  # 0 = head-only phase only
            net, _ = self._finetune_net(pre, X, y, seed, epochs)
            preds.append(self._predict(net, prep.transform(test[FEATURES])) * scale)
            chosen.append(epochs)
        return np.mean(preds, axis=0), {"epochs_after_head": chosen}


FAMILIES = {"ridge": RidgeFamily, "xgb": XGBFamily, "mlp": MLPFamily}


# --------------------------------------------------------------------------- prepare
def _foreign_files():
    from experiments import nerrs_multi as nm

    for reserve in nm.RESERVES.values():
        for code in reserve.wq_stations:
            for path in sorted(reserve.data_dir.glob(f"{reserve.code}{code}wq*.csv")):
                if int(path.stem[-4:]) in nm.QC_YEARS:
                    yield reserve, code, path


def stage_prepare(args) -> None:
    from experiments import nerrs_load as nl

    root = run_dir(args.run_name)
    root.mkdir(parents=True, exist_ok=False)
    t0 = time.perf_counter()
    pieces, files = [], []
    for reserve, code, path in _foreign_files():
        frame, _ = nl.read_wq_file(path, ("Temp", "pH", "Sal"))
        frame = frame[frame.index.minute % STEP == 0]
        frame = frame[~frame.index.duplicated()]
        out = pd.DataFrame({"station": f"{reserve.code}{code}", "reserve": reserve.code, "utc_offset_h": reserve.utc_offset_h, "time_utc": (frame.index - pd.Timedelta(hours=reserve.utc_offset_h)).tz_localize("UTC")})
        for col, (lo, hi) in (("Temp", TARGETS["Temperature"][3]), ("pH", TARGETS["pH"][3]), ("Sal", (0.0, 45.0))):
            values = frame[col].to_numpy(dtype=float) if col in frame else np.full(len(frame), np.nan)
            out[col] = np.where((values >= lo) & (values <= hi), values, np.nan)
        pieces.append(out)
        files.append({"file": str(path.relative_to(paths.FOREIGN_DATA_DIR)), "sha256": _sha256(path), "rows": len(out)})
    foreign = pd.concat(pieces, ignore_index=True).drop_duplicates(["station", "time_utc"]).sort_values(["station", "time_utc"]).reset_index(drop=True)
    foreign.to_parquet(root / "foreign-15min.parquet", index=False)
    oisst = pd.read_csv(OISST_CSV, parse_dates=["time"])
    clim = oisst[(oisst["time"] >= "1991-01-01") & (oisst["time"] < "2021-01-01")]["sst"]
    nb1_p5, nb1_p95 = float(clim.quantile(.05)), float(clim.quantile(.95))
    stats = foreign.groupby("station").agg(reserve=("reserve", "first"), n_temp=("Temp", "count"), temp_p5=("Temp", lambda s: s.quantile(.05)), temp_p95=("Temp", lambda s: s.quantile(.95)), sal_median=("Sal", "median"), n_ph=("pH", "count"), first=("time_utc", "min"), last=("time_utc", "max")).reset_index()
    stats["eligible"] = stats["n_temp"].ge(SIM_MIN_N) & stats["sal_median"].ge(SIM_MIN_SAL)
    stats["similarity_score"] = (stats["temp_p5"] - nb1_p5).abs() + (stats["temp_p95"] - nb1_p95).abs()
    ranked = stats[stats["eligible"]].sort_values("similarity_score")
    similar = ranked["station"].head(SIM_TOP_K).tolist()
    stats["similar"] = stats["station"].isin(similar)
    stats.to_csv(root / "foreign_site_stats.csv", index=False)
    manifest = {"stage": "prepare", "created": pd.Timestamp.now(tz="UTC").isoformat(), "seconds": time.perf_counter() - t0, "foreign_rows": len(foreign), "foreign_files": files, "oisst": {"file": str(OISST_CSV), "sha256": _sha256(OISST_CSV), "climatology": "daily 1991-2020", "p5": nb1_p5, "p95": nb1_p95}, "similarity_rule": f"n_temp >= {SIM_MIN_N}, median Sal >= {SIM_MIN_SAL}, rank |p5-{nb1_p5:.2f}|+|p95-{nb1_p95:.2f}|, top {SIM_TOP_K}", "similar_stations": similar, "packages": _versions()}
    _write_json(root / "manifest-prepare.json", manifest)
    print(json.dumps({k: manifest[k] for k in ("seconds", "foreign_rows", "similar_stations")}, indent=1))
    print(stats.sort_values("similarity_score").to_string(index=False))


# --------------------------------------------------------------------------- features
def load_nb1(target: str):
    from experiments.forecast_sensor_v2 import load_sensor_data, truncate_local_date

    tag = TARGETS[target][0]
    base = paths.EXPERIMENT_OUTPUT_DIR / BASE_RUN / f"baseline-{tag}"
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    raw = truncate_local_date(load_sensor_data(Path(manifest["input"]), STATION), manifest.get("last_local_date"))
    return raw, base, manifest


def stage_features(args) -> None:
    from experiments.foundation_zero_shot import load_origins

    root = run_dir(args.run_name)
    tag, horizons, fcol, _, _ = TARGETS[args.target]
    out = root / f"features-{args.target}"
    out.mkdir(exist_ok=False)
    t0 = time.perf_counter()
    raw, base, base_manifest = load_nb1(args.target)
    series = nb1_series(raw, args.target)
    origins = load_origins(base, STEP)
    origins = origins[origins["horizon_minutes"].isin(horizons)].reset_index(drop=True)
    foreign = pd.read_parquet(root / "foreign-15min.parquet", columns=["station", "utc_offset_h", "time_utc", fcol])
    stats = pd.read_csv(root / "foreign_site_stats.csv")
    similar = set(stats.loc[stats["similar"], "station"])
    checks, meta = {}, {"target": args.target, "baseline": str(base), "baseline_input_sha256": base_manifest["input_sha256"], "horizons": list(horizons)}
    foreign_series = []
    for station, group in foreign.groupby("station"):
        group = group.dropna(subset=[fcol])
        if len(group) < DAY * 14:
            continue
        start = group["time_utc"].min()
        index = pd.date_range(start, group["time_utc"].max(), freq=f"{STEP}min")
        values = group.set_index("time_utc")[fcol].reindex(index).to_numpy(dtype=float)
        foreign_series.append(Series15(values, values, start, float(group["utc_offset_h"].iloc[0]), station))
    for h in horizons:
        nb1_train = series.training_rows(h)
        nb1_train.to_parquet(out / f"nb1-train-h{h}.parquet", index=False)
        ori = origins[origins["horizon_minutes"].eq(h)].reset_index(drop=True)
        feats = origin_features(series, ori["issued_at"], h)
        evalf = pd.concat([ori[["split", "fold", "horizon_minutes", "issued_at", "actual"]].reset_index(drop=True), feats.drop(columns=["issued_at"]).reset_index(drop=True)], axis=1)
        evalf.to_parquet(out / f"nb1-eval-h{h}.parquet", index=False)
        checks[h] = assert_no_lookahead(raw, args.target, series, ori["issued_at"], h)
        rng = np.random.default_rng(h)
        blocks = []
        for s in foreign_series:
            rows = s.training_rows(h)
            rows = rows[rng.random(len(rows)) < 1 / FOREIGN_FRACTION]
            rows["station"] = s.name
            rows["year"] = rows["issued_at"].dt.year
            rows["similar"] = s.name in similar
            blocks.append(rows)
        frn = pd.concat(blocks, ignore_index=True)
        frn.to_parquet(out / f"foreign-h{h}.parquet", index=False)
        meta[f"h{h}"] = {"nb1_train_rows": len(nb1_train), "eval_origins": len(evalf), "eval_missing_current": int(evalf["current"].isna().sum()), "foreign_rows": len(frn), "foreign_rows_similar": int(frn["similar"].sum()), "lookahead_checked_origins": checks[h]}
        print(json.dumps({h: meta[f"h{h}"]}), flush=True)
    meta["seconds"] = time.perf_counter() - t0
    meta["foreign_sampling"] = f"1/{FOREIGN_FRACTION} random valid marks per horizon, numpy default_rng(seed=horizon)"
    _write_json(out / "manifest.json", meta)


# --------------------------------------------------------------------------- fit
def _splits_a(fold_check, h, train: pd.DataFrame, evalf: pd.DataFrame):
    lock, folds = fold_starts(fold_check, h)
    for k, start in sorted(folds.items()):
        test = evalf[evalf["split"].astype(str).eq("rolling") & evalf["fold"].eq(k)]
        if len(test) and test["issued_at"].min() < start:
            raise AssertionError(f"fold_test_before_start:{h}:{k}")
        yield "A", "rolling", k, train[train_mask(train, start, h)], test
    test = evalf[evalf["split"].astype(str).eq("lockbox")]
    if test["issued_at"].min() < lock:
        raise AssertionError("lockbox_test_before_start")
    yield "A", "lockbox", 0, train[train_mask(train, lock, h)], test


def _split_b(train: pd.DataFrame, evalf: pd.DataFrame):
    tmask, emask = eval_b_masks(train, evalf)
    yield "B", "evalB", -1, train[tmask], evalf[emask]


def stage_fit(args) -> None:
    root = run_dir(args.run_name)
    feat_dir = root / f"features-{args.target}"
    out = root / f"pred-{args.target}-{args.family}.parquet"
    if out.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out}")
    tag, horizons, _, _, _ = TARGETS[args.target]
    fold_check = json.loads((paths.EXPERIMENT_OUTPUT_DIR / BASE_RUN / f"baseline-{tag}" / "fold_label_check.json").read_text(encoding="utf-8"))
    family = FAMILIES[args.family]()
    blocks, hyper, timing = [], [], []
    for h in args.horizon or horizons:
        train = pd.read_parquet(feat_dir / f"nb1-train-h{h}.parquet")
        evalf = pd.read_parquet(feat_dir / f"nb1-eval-h{h}.parquet")
        evalf = evalf.dropna(subset=["current"]).reset_index(drop=True)
        foreign = pd.read_parquet(feat_dir / f"foreign-h{h}.parquet")
        pre = {}
        for site_set in ("all", "sim"):
            part = foreign if site_set == "all" else foreign[foreign["similar"]]
            t0 = time.perf_counter()
            pre[site_set] = family.pretrain(part.reset_index(drop=True))
            timing.append({"horizon": h, "step": f"pretrain-{site_set}", "rows": len(part), "seconds": time.perf_counter() - t0})
            print(json.dumps(timing[-1]), flush=True)
        splits = list(_splits_a(fold_check, h, train, evalf))
        if args.target == "Temperature":
            splits += list(_split_b(train, evalf))
        for ev, split, fold, tr, te in splits:
            if not len(te):
                continue
            tr = tr.reset_index(drop=True)
            t0 = time.perf_counter()
            preds = {}
            preds[f"{args.family}-nb1"], hp = family.nb1(tr, te, h)
            hyper.append({"eval": ev, "split": split, "fold": fold, "horizon": h, "model": f"{args.family}-nb1", **{k: str(v) for k, v in hp.items()}})
            if args.family == "xgb":
                preds["xgb-nb1-abs"], hp = family.nb1(tr, te, h, absolute=True)
                hyper.append({"eval": ev, "split": split, "fold": fold, "horizon": h, "model": "xgb-nb1-abs", **{k: str(v) for k, v in hp.items()}})
            for site_set in ("all", "sim"):
                preds[f"{args.family}-foreign-{site_set}"] = family.zero_shot(pre[site_set], te)
                preds[f"{args.family}-ft-{site_set}"], hp = family.finetune(pre[site_set], tr, te, h)
                hyper.append({"eval": ev, "split": split, "fold": fold, "horizon": h, "model": f"{args.family}-ft-{site_set}", **{k: str(v) for k, v in hp.items()}})
            timing.append({"horizon": h, "step": f"{ev}-{split}-{fold}", "rows": len(tr), "seconds": time.perf_counter() - t0})
            print(json.dumps(timing[-1]), flush=True)
            for name, delta in preds.items():
                blocks.append(pd.DataFrame({"eval": ev, "split": split, "fold": fold, "horizon_minutes": h, "issued_at": te["issued_at"].to_numpy(), "model": name, "prediction": te["current"].to_numpy() + np.asarray(delta, dtype=float), "n_train": len(tr), "train_last_valid": tr["valid_at"].max()}))
    pred = pd.concat(blocks, ignore_index=True)
    pred.to_parquet(out, index=False)
    pd.DataFrame(hyper).to_csv(out.with_name(f"hyper-{args.target}-{args.family}.csv"), index=False)
    meta = {"family": args.family, "target": args.target, "timing": timing, "total_seconds": float(sum(t["seconds"] for t in timing)), "packages": _versions(), "pretrain_info": {s: {k: v for k, v in p.items() if k in ("rounds", "epochs")} for s, p in pre.items()}}
    _write_json(out.with_suffix(".json"), meta)


# --------------------------------------------------------------------------- evaluate
def _wide_references(target: str) -> pd.DataFrame:
    from experiments.foundation_zero_shot import thin_mask

    tag, horizons, _, _, chronos = TARGETS[target]
    base_run = paths.EXPERIMENT_OUTPUT_DIR / BASE_RUN
    pred = pd.read_parquet(base_run / f"baseline-{tag}" / "predictions.parquet", columns=["split", "fold", "horizon_minutes", "feature_set", "model", "issued_at", "actual", "prediction"])
    pred = pred[thin_mask(pred["issued_at"], STEP) & pred["horizon_minutes"].isin(horizons)]
    pred["name"] = np.where(pred["model"].astype(str).eq("persistence"), "persistence", "ridge_" + pred["feature_set"].astype(str))
    pred = pred[~(pred["name"].eq("persistence") & ~pred["feature_set"].astype(str).eq("B4_quality"))]
    wide = pred.pivot_table(index=["split", "fold", "horizon_minutes", "issued_at", "actual"], columns="name", values="prediction", observed=True).reset_index()
    wide.columns.name = None
    wide["split"] = wide["split"].astype(str)
    for model in ("diurnal-anomaly-7d", chronos):
        fm = pd.read_parquet(base_run / f"fm-{tag}-{model}-stride{STEP}.parquet")
        fm = fm[["split", "fold", "horizon_minutes", "issued_at", "prediction"]].rename(columns={"prediction": model})
        fm["split"] = fm["split"].astype(str)
        wide = wide.merge(fm, on=["split", "fold", "horizon_minutes", "issued_at"], how="left", validate="one_to_one")
    return wide


def _load_predictions(root: Path, target: str, ev: str) -> pd.DataFrame:
    parts = []
    for path in sorted(root.glob(f"pred-{target}-*.parquet")):
        p = pd.read_parquet(path)
        parts.append(p[p["eval"].eq(ev)])
    pred = pd.concat(parts, ignore_index=True)
    return pred.pivot_table(index=["horizon_minutes", "issued_at"], columns="model", values="prediction").reset_index()


NB1_ONLY = ("ridge_B4_quality", "ridge_B4_quality_nopH", "diurnal-anomaly-7d", "ridge-nb1", "xgb-nb1", "xgb-nb1-abs", "mlp-nb1")


def _attach_amp(root: Path, target: str, frame: pd.DataFrame) -> pd.DataFrame:
    amps = []
    for h in sorted(frame["horizon_minutes"].unique()):
        e = pd.read_parquet(root / f"features-{target}" / f"nb1-eval-h{h}.parquet", columns=["horizon_minutes", "issued_at", "amp24"])
        amps.append(e)
    return frame.merge(pd.concat(amps), on=["horizon_minutes", "issued_at"], how="left", validate="many_to_one")


def stage_evaluate(args) -> None:
    from experiments.forecast_dm_test import diebold_mariano
    from experiments.foundation_zero_shot import _metrics, evaluate_frame

    root = run_dir(args.run_name)
    out = root / f"eval{args.eval}-{args.target}"
    out.mkdir(exist_ok=False)
    wide = _wide_references(args.target)
    mine = _load_predictions(root, args.target, args.eval)
    wide = wide.merge(mine, on=["horizon_minutes", "issued_at"], how="inner" if args.eval == "A" else "inner", validate="one_to_one")
    models = [c for c in wide.columns if c not in ("split", "fold", "horizon_minutes", "issued_at", "actual", "persistence")]
    n_before = len(wide)
    wide = wide.dropna(subset=["actual", "persistence", *models]).reset_index(drop=True)
    meta = {"eval": args.eval, "target": args.target, "rows": len(wide), "rows_dropped_missing_any_model": n_before - len(wide), "models": models}
    wide = _attach_amp(root, args.target, wide)
    wide.to_parquet(out / "wide.parquet", index=False)
    if args.eval == "A":
        metrics, dm, gate = evaluate_frame(wide.drop(columns=["amp24"]), models, models, STEP)
        rolling = metrics[metrics["split"].eq("rolling")]
        best = rolling[rolling["model"].isin(NB1_ONLY)].groupby(["horizon_minutes", "model"])["mae"].mean().reset_index().sort_values("mae").groupby("horizon_minutes").head(1)
        best = best.rename(columns={"model": "best_nb1_only", "mae": "best_nb1_only_fold_mean_mae"})
        best.to_csv(out / "best_nb1_only.csv", index=False)
        metrics.to_csv(out / "metrics.csv", index=False)
        dm.to_csv(out / "dm_tests.csv", index=False)
        gate.to_csv(out / "gate16.csv", index=False)
        regime = []
        lock = wide[wide["split"].eq("lockbox")]
        for (h, large), g in lock.groupby(["horizon_minutes", lock["amp24"] > LARGE_DIURNAL_C]):
            for m in ["persistence", *models]:
                regime.append({"horizon_minutes": h, "large_diurnal": bool(large), "model": m, **_metrics(g["actual"].to_numpy(), g[m].to_numpy())})
        pd.DataFrame(regime).to_csv(out / "lockbox_regime.csv", index=False)
        fold_amp = wide.groupby(["split", "fold"])["amp24"].agg(["mean", "median"]).reset_index()
        fold_amp.to_csv(out / "fold_amp24.csv", index=False)
        meta["best_nb1_only"] = best.to_dict("records")
    else:
        lo_hi = _training_envelope(root, args.target)
        meta["training_envelope"] = lo_hi
        wide["block"] = ((wide["issued_at"] - EVAL_B_TEST_START) // pd.Timedelta(days=7)).astype(int)
        rows, dm_rows, block_rows = [], [], []
        for h, g in wide.groupby("horizon_minutes"):
            g = g.sort_values("issued_at")
            subsets = {"all": g, "out_minmax": g[(g["actual"] < lo_hi["min"]) | (g["actual"] > lo_hi["max"])], "out_p1p99": g[(g["actual"] < lo_hi["p1"]) | (g["actual"] > lo_hi["p99"])], "large_diurnal": g[g["amp24"] > LARGE_DIURNAL_C], "small_diurnal": g[g["amp24"] <= LARGE_DIURNAL_C]}
            base = {k: _metrics(s["actual"].to_numpy(), s["persistence"].to_numpy()) if len(s) else None for k, s in subsets.items()}
            for m in ["persistence", *models]:
                for k, s in subsets.items():
                    if len(s):
                        mm = _metrics(s["actual"].to_numpy(), s[m].to_numpy())
                        rows.append({"horizon_minutes": h, "subset": k, "share": len(s) / len(g), "model": m, **mm, "skill_vs_persistence": 1 - mm["mae"] / base[k]["mae"]})
            for m in models:
                for ref in ["persistence", *models]:
                    if ref == m:
                        continue
                    stat, p = diebold_mariano((g[m] - g["actual"]).to_numpy(), (g[ref] - g["actual"]).to_numpy(), horizon_steps=int(np.ceil(h / STEP)), loss="abs", kernel="rectangular")
                    per_block = g.groupby("block").apply(lambda b: pd.Series({"mae": np.mean(np.abs(b[m] - b["actual"])) < np.mean(np.abs(b[ref] - b["actual"])), "rmse": np.mean((b[m] - b["actual"]) ** 2) < np.mean((b[ref] - b["actual"]) ** 2)}), include_groups=False)
                    wins = int((per_block["mae"] & per_block["rmse"]).sum())
                    dm_rows.append({"horizon_minutes": h, "model": m, "reference": ref, "n": len(g), "mae": np.mean(np.abs(g[m] - g["actual"])), "mae_ref": np.mean(np.abs(g[ref] - g["actual"])), "rel_change": np.mean(np.abs(g[m] - g["actual"])) / np.mean(np.abs(g[ref] - g["actual"])) - 1, "dm_stat": stat, "p_value": p, "blocks_beating": wins, "blocks": len(per_block), "pass_like_gate16": bool(wins >= int(np.ceil(0.8 * len(per_block))) and np.isfinite(p) and stat < 0 and p < 0.05)})
            for (blk), b in g.groupby("block"):
                for m in ["persistence", *models]:
                    block_rows.append({"horizon_minutes": h, "block": blk, "from": b["issued_at"].min(), "to": b["issued_at"].max(), "amp24_mean": b["amp24"].mean(), "model": m, **_metrics(b["actual"].to_numpy(), b[m].to_numpy())})
        pd.DataFrame(rows).to_csv(out / "metrics.csv", index=False)
        pd.DataFrame(dm_rows).to_csv(out / "dm_blocks.csv", index=False)
        pd.DataFrame(block_rows).to_csv(out / "metrics_blocks.csv", index=False)
    meta["packages"] = _versions()
    _write_json(out / "manifest.json", meta)
    print(json.dumps({k: v for k, v in meta.items() if k != "packages"}, indent=1, default=str))


def _training_envelope(root: Path, target: str) -> dict:
    """Eval-B NB1 training-label envelope (warm season)."""
    tr = pd.read_parquet(root / f"features-{target}" / f"nb1-train-h{TARGETS[target][1][0]}.parquet", columns=["valid_at", "y_future"])
    y = tr.loc[tr["valid_at"] < EVAL_B_TRAIN_END, "y_future"].dropna()
    return {"min": float(y.min()), "max": float(y.max()), "p1": float(y.quantile(.01)), "p99": float(y.quantile(.99))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="stage", required=True)
    for stage in ("prepare", "features", "fit", "evaluate"):
        p = sub.add_parser(stage)
        p.add_argument("--run-name", default="transfer-forecast-20261025")
        if stage != "prepare":
            p.add_argument("--target", required=True, choices=tuple(TARGETS))
        if stage == "fit":
            p.add_argument("--family", required=True, choices=tuple(FAMILIES))
            p.add_argument("--horizon", type=int, action="append")
        if stage == "evaluate":
            p.add_argument("--eval", required=True, choices=("A", "B"))
    args = parser.parse_args()
    if args.stage == "evaluate" and args.eval == "B" and args.target != "Temperature":
        raise SystemExit("eval_B_is_temperature_only")
    {"prepare": stage_prepare, "features": stage_features, "fit": stage_fit, "evaluate": stage_evaluate}[args.stage](args)


if __name__ == "__main__":
    main()
