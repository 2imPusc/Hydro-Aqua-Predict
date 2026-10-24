"""H1.4: zero-shot time-series foundation models vs the ridge benchmark (research-only).

Three stages share one run directory under ``paths.EXPERIMENT_OUTPUT_DIR``:

``baseline``  (root ``.venv``)  re-fits persistence + ridge B4 / B4_nopH with
              ``forecast_sensor_v2.run_benchmark`` and keeps its predictions.  Those rows
              *are* the origin set (rolling folds + 14-day lockbox, purge, label checks),
              so nothing about the fold/origin construction is re-implemented here.
``forecast``  (``.venv-fm``)  zero-shot forecasts (Chronos-Bolt, optionally TimesFM) at
              the baseline origins, thinned by a fixed ``--stride`` (minutes).
``evaluate``  MAE / skill vs persistence per fold, decision #16 gate (>= 4/5 folds and a
              lockbox Diebold-Mariano test, abs loss, rectangular kernel) vs persistence
              *and* vs each ridge variant, on identical origins.

Information set: ridge sees observations up to ``issued_at - 1 min`` (``lag_1m``), so the
foundation-model context ends at the 1-minute bin ``floor(issued_at - 1 min)``.  Context
points are means of ``step``-minute windows of the 1-minute grid (NaN where empty; Chronos
masks NaN).  The forecast for horizon ``h`` is the median path linearly interpolated at
``issued_at + h`` using window centres - a window mean, while the target is a point value
(negligible for Temperature at step <= 15 min; stated in NOTES).

Usage (from the repo root):
    .venv/Scripts/python experiments/foundation_zero_shot.py baseline --run-name foundation-zero-shot-20261024 --tag Temperature --target Temperature
    .venv-fm/Scripts/python experiments/foundation_zero_shot.py forecast --run-name ... --tag Temperature --model chronos-bolt-small --stride 15
    .venv-fm/Scripts/python experiments/foundation_zero_shot.py evaluate --run-name ... --tag Temperature
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402

STATION = "06M26042804"
DEFAULT_INPUT = paths.EXPERIMENT_OUTPUT_DIR / "sensor-history-20261024" / f"{STATION}.csv"
HORIZONS = (15, 30, 60, 180, 360, 720)
# (step minutes, context steps) per horizon: horizon / step <= 64 keeps Chronos-Bolt inside its
# native one-shot prediction length; context spans 2.8-7 days.
STEP_FOR_HORIZON = {15: 2, 30: 2, 60: 2, 180: 5, 360: 15, 720: 15}
CONTEXT_STEPS = {2: 2048, 5: 2016, 15: 672}
MODELS = {
    "chronos-bolt-tiny": ("chronos", "amazon/chronos-bolt-tiny"),
    "chronos-bolt-mini": ("chronos", "amazon/chronos-bolt-mini"),
    "chronos-bolt-small": ("chronos", "amazon/chronos-bolt-small"),
    "chronos-bolt-base": ("chronos", "amazon/chronos-bolt-base"),
    "chronos-2": ("chronos", "amazon/chronos-2"),
    "timesfm-2.5-200m": ("timesfm", "google/timesfm-2.5-200m-pytorch"),
    "diurnal-anomaly-7d": ("naive", None),  # reference: is the FM gain just the daily cycle?
}
RIDGE_FEATURE_SETS = ("B4_quality", "B4_quality_nopH")


def run_dir(name: str) -> Path:
    return paths.EXPERIMENT_OUTPUT_DIR / name


def _write_new(path: Path, writer) -> None:
    if path.exists():
        raise FileExistsError(f"refusing_to_overwrite:{path}")
    writer(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- baseline
def stage_baseline(args) -> None:
    from experiments.forecast_sensor_v2 import run_benchmark

    out = run_dir(args.run_name) / f"baseline-{args.tag}"
    if out.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out}")
    feature_sets = ("B4_quality",) if args.target == "pH" else RIDGE_FEATURE_SETS
    manifest = run_benchmark(
        Path(args.input), STATION, out, write_predictions=True, selected_feature_sets=feature_sets,
        selected_models=("ridge",), selected_targets=(args.target,), selected_horizons=tuple(args.horizon or HORIZONS),
        prediction_models=("ridge",), last_local_date=args.end,
    )
    print(json.dumps({"baseline": str(out), "window": manifest["window"], "sha256": manifest["input_sha256"]}, indent=1))


def load_origins(base: Path, stride: int) -> pd.DataFrame:
    """Persistence rows of the B4 frame = the benchmark origin set, thinned by ``stride``."""
    pred = pd.read_parquet(base / "predictions.parquet", columns=["split", "fold", "target", "horizon_minutes", "feature_set", "model", "issued_at", "actual", "prediction"])
    pred = pred[pred["feature_set"].astype(str).eq("B4_quality")]
    origins = pred[pred["model"].astype(str).eq("persistence")].drop(columns=["model", "feature_set", "prediction"])
    return origins[thin_mask(origins["issued_at"], stride)].reset_index(drop=True)


def thin_mask(issued: pd.Series, stride: int) -> np.ndarray:
    minute = issued.dt.floor("min")
    return ((minute.dt.hour * 60 + minute.dt.minute) % stride == 0).to_numpy()


# --------------------------------------------------------------------------- forecast
class Grid:
    """1-minute grid of a sensor series with prefix sums for causal window means."""

    def __init__(self, raw: pd.DataFrame, target: str):
        series = raw[["fetchedAt", target]].dropna()
        minute = series["fetchedAt"].dt.floor("min")
        per_minute = series.groupby(minute)[target].median()
        self.start = per_minute.index.min()
        index = pd.date_range(self.start, per_minute.index.max(), freq="min")
        values = per_minute.reindex(index).to_numpy(dtype=float)
        ok = np.isfinite(values)
        self.csum = np.concatenate([[0.0], np.cumsum(np.where(ok, values, 0.0))])
        self.ccnt = np.concatenate([[0], np.cumsum(ok)])
        self.n = len(values)

    def last_index(self, issued: pd.Series) -> np.ndarray:
        """Grid index of the last minute a forecast issued at ``issued`` may see (issued - 1 min)."""
        last = ((issued - pd.Timedelta(minutes=1)).dt.floor("min") - self.start).dt.total_seconds().to_numpy() // 60
        return last.astype(np.int64)

    def window_mean(self, ends: np.ndarray, length: int) -> np.ndarray:
        """Mean of the 1-minute bins ``[ends - length, ends)``; NaN when the window is empty."""
        # Minutes outside the grid hold no observation, so clipping only drops empty bins.
        s, e = np.clip(ends - length, 0, self.n), np.clip(ends, 0, self.n)
        count = self.ccnt[e] - self.ccnt[s]
        with np.errstate(invalid="ignore", divide="ignore"):
            out = (self.csum[e] - self.csum[s]) / count
        out[count == 0] = np.nan
        return out

    def contexts(self, issued: pd.Series, step: int, length: int) -> np.ndarray:
        """``(len(issued), length)`` window means, oldest first, last window ends at issued-1min."""
        ends = self.last_index(issued)[:, None] + 1 - step * np.arange(length)[::-1][None, :]  # exclusive
        return self.window_mean(ends, step).astype(np.float32)


def diurnal_anomaly(grid: Grid, issued: pd.Series, horizon: int, days: int = 7, window: int = 15) -> np.ndarray:
    """Naive reference: last value + change of the mean daily profile from now to now + h.

    ``P(x)`` = mean over the previous ``days`` days of the ``window``-minute mean centred on
    ``x - k days``.  Every bin read lies at or before ``issued - 1 min`` for h < 1 day - window.
    """
    if horizon + window // 2 + 1 >= 1440:
        raise ValueError("diurnal_anomaly_needs_horizon_below_one_day")
    last = grid.last_index(issued)
    current = grid.window_mean(last + 1, 1)
    fallback = grid.window_mean(last + 1, window)
    current = np.where(np.isfinite(current), current, fallback)

    def profile(centre: np.ndarray) -> np.ndarray:
        ends = centre[:, None] - 1440 * np.arange(1, days + 1)[None, :] + window // 2 + 1
        with np.errstate(invalid="ignore"):
            return np.nanmean(grid.window_mean(ends, window), axis=1)

    with np.errstate(invalid="ignore"):
        change = profile(last + 1 + horizon) - profile(last)
    return current + np.where(np.isfinite(change), change, 0.0)


def assert_no_lookahead(raw: pd.DataFrame, target: str, grid: Grid, issued: pd.Series, steps, n: int = 20) -> int:
    """Contexts must equal those rebuilt from data the ridge model could also see.

    Rebuilds the grid from rows with ``fetchedAt < floor(issued_at - 1 min) + 1 min`` (all a
    ridge ``lag_1m`` feature could have seen, and nothing at or after ``issued_at``) and checks
    every context window is identical.
    """
    sample = issued.sample(min(n, len(issued)), random_state=1)
    for t in sample:
        cutoff = (t - pd.Timedelta(minutes=1)).floor("min") + pd.Timedelta(minutes=1)
        assert cutoff <= t
        truncated = Grid(raw[raw["fetchedAt"] < cutoff], target)
        assert truncated.start == grid.start
        for step in steps:
            a = grid.contexts(pd.Series([t]), step, CONTEXT_STEPS[step])
            b = truncated.contexts(pd.Series([t]), step, CONTEXT_STEPS[step])
            if not np.array_equal(a, b, equal_nan=True):
                raise AssertionError(f"lookahead_in_context:{t}:{step}")
    return len(sample)


def interpolate_horizon(path: np.ndarray, step: int, horizon: int) -> np.ndarray:
    """Median path (n, H) -> value at issued + h by linear interpolation between window centres.

    The context's last window ends just before minute ``t`` (for on-minute ``t``), so forecast
    window j (1-based) holds the 1-minute bins t+(j-1)*step ... t+j*step-1, centred at
    t + (j - 0.5) * step - 0.5 minutes.
    """
    centres = (np.arange(1, path.shape[1] + 1) - 0.5) * step - 0.5
    return np.array([np.interp(horizon, centres, row) for row in path])


def prediction_length(step: int, horizons) -> int:
    return int(math.ceil(max(horizons) / step + 0.5)) + 1


class ChronosForecaster:
    def __init__(self, repo: str, threads: int):
        import torch
        from chronos import BaseChronosPipeline

        torch.set_num_threads(threads)
        self.torch = torch
        self.pipe = BaseChronosPipeline.from_pretrained(repo, device_map="cpu", torch_dtype=torch.float32)

    def median(self, context: np.ndarray, length: int, batch: int) -> np.ndarray:
        out = []
        for i in range(0, len(context), batch):
            chunk = self.torch.tensor(context[i:i + batch])
            quantiles, _ = self.pipe.predict_quantiles(chunk, prediction_length=length, quantile_levels=[0.5])
            out.append(quantiles[..., 0].float().numpy())
        return np.concatenate(out)


class TimesFMForecaster:
    def __init__(self, repo: str, threads: int):
        import timesfm
        import torch

        torch.set_num_threads(threads)
        # torch.compile needs a C++ toolchain on Windows; eager mode gives identical numbers.
        self.model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(repo, torch_compile=False)
        self.timesfm = timesfm
        self.compiled_for = None

    def median(self, context: np.ndarray, length: int, batch: int) -> np.ndarray:
        key = (context.shape[1], length, batch)
        if self.compiled_for != key:
            self.model.compile(self.timesfm.ForecastConfig(max_context=int(math.ceil(context.shape[1] / 32) * 32), max_horizon=int(math.ceil(length / 128) * 128), per_core_batch_size=batch, normalize_inputs=True))
            self.compiled_for = key
        # TimesFM strips leading NaN and linearly interpolates interior gaps itself (context only).
        series = [row if np.isfinite(row).any() else np.zeros(3, dtype=np.float32) for row in context]
        point, _ = self.model.forecast(horizon=length, inputs=series)
        return np.asarray(point)[:, :length]


def stage_forecast(args) -> None:
    from experiments.forecast_sensor_v2 import load_sensor_data, truncate_local_date

    root = run_dir(args.run_name)
    base = root / f"baseline-{args.tag}"
    base_manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    pilot = f"-pilot{args.limit}" if args.limit else ""  # pilots never feed ``evaluate``
    out = root / f"fm-{args.tag}-{args.model}-stride{args.stride}{pilot}.parquet"
    if out.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out}")
    origins = load_origins(base, args.stride)
    if args.limit:
        origins = origins[origins["issued_at"].isin(origins["issued_at"].drop_duplicates().sample(args.limit, random_state=0))]
    target = str(origins["target"].iloc[0])
    raw = truncate_local_date(load_sensor_data(Path(base_manifest["input"]), STATION), base_manifest.get("last_local_date"))
    grid = Grid(raw, target)
    leak_checked = assert_no_lookahead(raw, target, grid, origins["issued_at"].drop_duplicates(), sorted({STEP_FOR_HORIZON[h] for h in origins["horizon_minutes"].unique()}))
    kind, repo = MODELS[args.model]
    threads = args.threads or os.cpu_count()
    t0 = time.perf_counter()
    model = {"chronos": ChronosForecaster, "timesfm": TimesFMForecaster}[kind](repo, threads) if kind != "naive" else None
    load_seconds = time.perf_counter() - t0
    horizons = sorted(origins["horizon_minutes"].unique().tolist())
    blocks, timing = [], []
    for h in horizons if kind == "naive" else ():
        issued = origins.loc[origins["horizon_minutes"].eq(h), "issued_at"].drop_duplicates().sort_values().reset_index(drop=True)
        blocks.append(pd.DataFrame({"horizon_minutes": h, "issued_at": issued, "prediction": diurnal_anomaly(grid, issued, h)}))
    for step in sorted({STEP_FOR_HORIZON[h] for h in horizons}) if kind != "naive" else ():
        step_h = [h for h in horizons if STEP_FOR_HORIZON[h] == step]
        issued = origins.loc[origins["horizon_minutes"].isin(step_h), "issued_at"].drop_duplicates().sort_values().reset_index(drop=True)
        context = grid.contexts(issued, step, CONTEXT_STEPS[step])
        length = prediction_length(step, step_h)
        t1 = time.perf_counter()
        path = model.median(context, length, args.batch)
        seconds = time.perf_counter() - t1
        timing.append({"step_minutes": step, "context_steps": CONTEXT_STEPS[step], "prediction_length": length, "n_forecasts": len(issued), "seconds": seconds, "seconds_per_1000": 1000 * seconds / max(len(issued), 1), "context_nan_fraction": float(np.isnan(context).mean())})
        print(json.dumps(timing[-1]), flush=True)
        for h in step_h:
            blocks.append(pd.DataFrame({"horizon_minutes": h, "issued_at": issued, "prediction": interpolate_horizon(path, step, h)}))
    preds = pd.concat(blocks, ignore_index=True)
    preds = origins.merge(preds, on=["horizon_minutes", "issued_at"], how="left", validate="one_to_one")
    preds["model"] = args.model
    preds.to_parquet(out, index=False)
    meta = {"model": args.model, "repo": repo, "kind": kind, "stride_minutes": args.stride, "threads": threads, "batch": args.batch, "load_seconds": load_seconds, "timing": timing, "n_origin_rows": len(preds), "limit": args.limit, "missing_predictions": int(preds["prediction"].isna().sum()), "lookahead_check_origins": leak_checked, "python": sys.version, "platform": platform.platform(), "packages": _versions(), "hf_revision": _hf_revision(repo) if repo else None}
    _write_new(out.with_suffix(".json"), lambda p: p.write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8"))
    print(json.dumps({k: meta[k] for k in ("model", "n_origin_rows", "missing_predictions", "load_seconds")}))


def _versions() -> dict:
    from importlib.metadata import PackageNotFoundError, version

    found = {}
    for name in ("torch", "chronos-forecasting", "timesfm", "transformers", "numpy", "pandas"):
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            pass
    return found


def _hf_revision(repo: str) -> str | None:
    try:
        from huggingface_hub import HfApi

        return HfApi().model_info(repo).sha
    except Exception as error:  # offline or private: record why
        return f"unavailable:{type(error).__name__}"


# --------------------------------------------------------------------------- evaluate
def _metrics(actual: np.ndarray, pred: np.ndarray) -> dict:
    err = pred - actual
    return {"n": int(len(err)), "mae": float(np.mean(np.abs(err))), "rmse": float(np.sqrt(np.mean(err ** 2))), "bias": float(err.mean()), "p95_ae": float(np.quantile(np.abs(err), .95))}


def evaluate_frame(wide: pd.DataFrame, candidates: list[str], references: list[str], stride: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """``wide``: one row per origin with ``actual`` and one column per model."""
    from experiments.forecast_dm_test import diebold_mariano

    rows, dm_rows, gate_rows = [], [], []
    models = list(dict.fromkeys(["persistence", *references, *candidates]))
    for (split, fold, horizon), group in wide.groupby(["split", "fold", "horizon_minutes"], observed=True):
        group = group.dropna(subset=["actual", *models])
        base = _metrics(group["actual"].to_numpy(), group["persistence"].to_numpy())
        for model in models:
            m = _metrics(group["actual"].to_numpy(), group[model].to_numpy())
            rows.append({"split": split, "fold": int(fold), "horizon_minutes": int(horizon), "model": model, **m, "skill_vs_persistence": 1 - m["mae"] / base["mae"] if base["mae"] > 0 else np.nan})
    metrics = pd.DataFrame(rows)
    lock = wide[wide["split"].astype(str).eq("lockbox")].sort_values("issued_at")
    for horizon, group in lock.groupby("horizon_minutes"):
        group = group.dropna(subset=["actual", *models])
        steps = int(math.ceil(horizon / stride))
        for model in [m for m in models if m != "persistence"]:
            for ref in ["persistence", *references]:
                if ref == model:
                    continue
                stat, p = diebold_mariano((group[model] - group["actual"]).to_numpy(), (group[ref] - group["actual"]).to_numpy(), horizon_steps=steps, loss="abs", kernel="rectangular")
                diff = float(np.mean(np.abs(group[model] - group["actual"]) - np.abs(group[ref] - group["actual"])))
                dm_rows.append({"horizon_minutes": int(horizon), "model": model, "reference": ref, "n": len(group), "dm_horizon_steps": steps, "mean_abs_loss_diff": diff, "dm_stat": stat, "p_value": p, "model_better": bool(np.isfinite(p) and stat < 0 and p < 0.05)})
    dm = pd.DataFrame(dm_rows)
    rolling = metrics[metrics["split"].astype(str).eq("rolling")]
    for horizon in sorted(metrics["horizon_minutes"].unique()):
        for model in [m for m in models if m != "persistence"]:
            for ref in ["persistence", *references]:
                if ref == model:
                    continue
                cand = rolling[(rolling.horizon_minutes == horizon) & (rolling.model == model)].set_index("fold")
                refm = rolling[(rolling.horizon_minutes == horizon) & (rolling.model == ref)].set_index("fold")
                joined = cand.join(refm[["mae", "rmse"]], rsuffix="_ref", how="inner")
                beats = int(((joined.mae < joined.mae_ref) & (joined.rmse < joined.rmse_ref)).sum())
                test = dm[(dm.horizon_minutes == horizon) & (dm.model == model) & (dm.reference == ref)]
                dm_ok = bool(len(test) == 1 and test.iloc[0].model_better)
                lock_m = metrics[(metrics.split.astype(str) == "lockbox") & (metrics.horizon_minutes == horizon)].set_index("model")
                gate_rows.append({"horizon_minutes": int(horizon), "model": model, "reference": ref, "folds_beating": beats, "folds_available": int(len(joined)), "lockbox_mae": float(lock_m.loc[model, "mae"]), "lockbox_mae_ref": float(lock_m.loc[ref, "mae"]), "lockbox_rel_change": float(lock_m.loc[model, "mae"] / lock_m.loc[ref, "mae"] - 1), "lockbox_dm_p": float(test.iloc[0].p_value) if len(test) else np.nan, "lockbox_dm_better": dm_ok, "gate16_pass": bool(len(joined) >= 5 and beats >= 4 and dm_ok)})
    return metrics, dm, pd.DataFrame(gate_rows)


def stage_evaluate(args) -> None:
    root = run_dir(args.run_name)
    base = root / f"baseline-{args.tag}"
    # Any finer-stride run nests inside a coarser evaluation grid (stride 15 contains stride 60).
    strides = {path: path.stem.rsplit("stride", 1)[1] for path in root.glob(f"fm-{args.tag}-*-stride*.parquet")}
    fm_files = sorted(path for path, value in strides.items() if value.isdigit() and args.stride % int(value) == 0)  # pilots excluded
    if args.models:
        fm_files = [path for path in fm_files if any(f"-{m}-stride" in path.name for m in args.models)]
    if not fm_files:
        raise FileNotFoundError("no_foundation_predictions")
    pred = pd.read_parquet(base / "predictions.parquet", columns=["split", "fold", "horizon_minutes", "feature_set", "model", "issued_at", "actual", "prediction"])
    pred = pred[thin_mask(pred["issued_at"], args.stride)]
    pred["name"] = np.where(pred["model"].astype(str).eq("persistence"), "persistence", "ridge_" + pred["feature_set"].astype(str))
    pred = pred[~(pred["name"].eq("persistence") & ~pred["feature_set"].astype(str).eq("B4_quality"))]
    wide = pred.pivot_table(index=["split", "fold", "horizon_minutes", "issued_at", "actual"], columns="name", values="prediction", observed=True).reset_index()
    wide.columns.name = None
    references = [c for c in wide.columns if c.startswith("ridge_")]
    candidates = []
    for path in fm_files:
        fm = pd.read_parquet(path)
        fm = fm[thin_mask(fm["issued_at"], args.stride)]
        name = str(fm["model"].iloc[0])
        if fm["prediction"].isna().all():
            continue
        fm = fm[["split", "fold", "horizon_minutes", "issued_at", "prediction"]].rename(columns={"prediction": name})
        fm["split"] = fm["split"].astype(str); wide["split"] = wide["split"].astype(str)
        wide = wide.merge(fm, on=["split", "fold", "horizon_minutes", "issued_at"], how="left", validate="one_to_one")
        candidates.append(name)
        if MODELS[name][0] == "naive":
            references.append(name)  # foundation models must also beat the daily-cycle reference
    covered = wide.dropna(subset=candidates)
    dropped = int(len(wide) - len(covered))
    if dropped:
        print(json.dumps({"warning": "origins_without_fm_prediction", "dropped": dropped}))
    metrics, dm, gate = evaluate_frame(covered, candidates, references, args.stride)
    out = root / f"eval-{args.tag}-stride{args.stride}"
    if out.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out}")
    out.mkdir(parents=True)
    summary = summary_table(metrics, dm, gate)
    for name, frame in (("metrics", metrics), ("dm_tests", dm), ("gate16", gate), ("summary", summary)):
        frame.to_csv(out / f"{name}.csv", index=False)
    meta = {"tag": args.tag, "stride_minutes": args.stride, "fm_files": [p.name for p in fm_files], "references": ["persistence", *references], "origins_dropped_without_fm": dropped, "dm": "abs loss, rectangular kernel, HLN correction, horizon_steps = ceil(h / stride)", "gate16": ">= 4/5 rolling folds with lower MAE and RMSE than the reference AND lockbox DM p < 0.05 with the candidate better"}
    (out / "manifest.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(summary.to_string(index=False))


def summary_table(metrics: pd.DataFrame, dm: pd.DataFrame, gate: pd.DataFrame) -> pd.DataFrame:
    """One row per (model, horizon): lockbox MAE, skill, and gate #16 against every reference."""
    lock = metrics[metrics["split"].astype(str).eq("lockbox")][["model", "horizon_minutes", "n", "mae", "skill_vs_persistence"]]
    rows = lock.rename(columns={"n": "lockbox_n", "mae": "lockbox_mae"})
    for ref in gate["reference"].unique():
        part = gate[gate["reference"].eq(ref)][["model", "horizon_minutes", "folds_beating", "lockbox_rel_change", "lockbox_dm_p", "gate16_pass"]]
        part = part.rename(columns={c: f"{c}__vs_{ref}" for c in part.columns if c not in ("model", "horizon_minutes")})
        rows = rows.merge(part, on=["model", "horizon_minutes"], how="left")
    return rows.sort_values(["horizon_minutes", "lockbox_mae"]).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="stage", required=True)
    for stage in ("baseline", "forecast", "evaluate"):
        p = sub.add_parser(stage)
        p.add_argument("--run-name", default="foundation-zero-shot-20261024")
        p.add_argument("--tag", required=True, help="baseline sub-run label, e.g. Temperature or pH-pre-drift")
        if stage == "baseline":
            p.add_argument("--target", required=True, choices=("Temperature", "pH", "NH4", "TSS"))
            p.add_argument("--horizon", type=int, action="append", choices=HORIZONS)
            p.add_argument("--input", default=str(DEFAULT_INPUT))
            p.add_argument("--end", help="last local date kept (forecast_sensor_v2 --end)")
        if stage == "forecast":
            p.add_argument("--model", required=True, choices=tuple(MODELS))
            p.add_argument("--batch", type=int, default=128)
            p.add_argument("--threads", type=int)
            p.add_argument("--limit", type=int, help="pilot: random subset of origins")
        if stage == "evaluate":
            p.add_argument("--models", nargs="+", choices=tuple(MODELS), help="restrict to these foundation models (default: every run found)")
        if stage in ("forecast", "evaluate"):
            p.add_argument("--stride", type=int, default=15, help="keep origins whose minute-of-day %% stride == 0")
    args = parser.parse_args()
    {"baseline": stage_baseline, "forecast": stage_forecast, "evaluate": stage_evaluate}[args.stage](args)


if __name__ == "__main__":
    main()
