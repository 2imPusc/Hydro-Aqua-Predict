"""Paper 1 / T1: zero-shot Chronos-2 (no covariates) on the H1.4 origins vs ridge B4D and Chronos-Bolt.

Stages share ``paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME`` (write-once files):

``init``      writes ``preregistration.json`` (models + HF revisions, context/step per horizon,
              quantiles, threads, references, verdict rules) before any Chronos-2 forecast exists.
``forecast``  (``.venv-fm``) Chronos-2 median + quantiles at the H1.4 Temperature origins
              (``foundation-zero-shot-20261024/baseline-Temperature``, stride 15).  Context
              construction, causality check and horizon interpolation are imported unchanged from
              ``foundation_zero_shot`` so the only difference to the stored Chronos-Bolt runs is the
              model.  ``--limit N`` writes a ``-pilotN`` file used only for CPU timing.
``evaluate``  merges Chronos-2 with the stored predictions of persistence, ridge B4 / B4D / B5D
              (``forecast-h1-diurnal-20261025/bench-Temperature``), Chronos-Bolt and the
              ``diurnal-anomaly-7d`` reference on identical origins (``actual`` asserted equal), then
              runs ``foundation_zero_shot.evaluate_frame`` (decision #16 gate, every model vs every
              model) in two scopes like ``forecast_h1_diurnal compare-fm``: ``B4family`` (all H1.4
              origins) and ``withB5`` (origins without a B5 forecast dropped).

Usage (repo root; HAP_* env vars point at the shared data / artifacts):
    .venv/Scripts/python experiments/paper1_t1_chronos2.py init
    .venv-fm/Scripts/python experiments/paper1_t1_chronos2.py forecast --model chronos-2-small --limit 64
    .venv-fm/Scripts/python experiments/paper1_t1_chronos2.py forecast --model chronos-2-base
    .venv/Scripts/python experiments/paper1_t1_chronos2.py evaluate
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
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from experiments import foundation_zero_shot as fz  # noqa: E402

RUN_NAME = "paper1-t1-20261028"
TAG = "Temperature"
STRIDE = 15
THREADS = 2  # the coordination session runs in parallel (HANDOFF: at most 2 cores)
BATCH = 64
FM_RUN = paths.EXPERIMENT_OUTPUT_DIR / "foundation-zero-shot-20261024"
DIURNAL_BENCH = paths.EXPERIMENT_OUTPUT_DIR / "forecast-h1-diurnal-20261025" / "bench-Temperature"
# Pinned HF revisions (checked 2026-10-28); both Apache-2.0.
CHRONOS2 = {
    "chronos-2-small": ("autogluon/chronos-2-small", "ddec01313e50b6bc58ebaa92ede81bc24a3d9f9a"),
    "chronos-2-base": ("amazon/chronos-2", "29ec3766d36d6f73f0696f85560a422f50e8498c"),
}
# Native levels of both checkpoints (small has 13, base 21): no interpolation needed. Kept for T4.
QUANTILES = (0.05, 0.1, 0.2, 0.5, 0.8, 0.9, 0.95)
STORED_FM = ("chronos-bolt-small", "chronos-bolt-base", "diurnal-anomaly-7d")
RIDGE_SETS = {
    "B4family": ("B4_quality", "B4_quality_nopH", "B4_quality_diurnal", "B4_quality_diurnal_nopH"),
    "withB5": ("B4_quality", "B4_quality_nopH", "B4_quality_diurnal", "B4_quality_diurnal_nopH",
               "B5_external_as_issued_diurnal", "B5_external_as_issued_diurnal_nopH"),
}
PRIMARY = "chronos-2-base"
VERDICT_RULES = {
    "gate16": ">= 4/5 rolling folds with lower MAE and RMSE than the reference AND lockbox Diebold-Mariano (abs loss, rectangular kernel, HLN, horizon_steps = ceil(h / 15)) p < 0.05 with the candidate better.",
    "vs_reference": "Per horizon and reference R: 'chronos2_wins' if Chronos-2 passes gate #16 vs R; 'reference_wins' if R passes gate #16 vs Chronos-2; else 'tie'. Over the 6 horizons: 'better' if chronos2_wins >= 4, 'worse' if reference_wins >= 4, else 'mixed'.",
    "primary_comparisons": "Chronos-2 base vs ridge B4D (ridge_B4_quality_diurnal, scope B4family) and vs Chronos-Bolt base (scope B4family). Holm correction over these 12 lockbox DM tests (2 references x 6 horizons) reported next to the raw p; the gate uses the raw p as in RL-62 / RL-66.",
    "secondary_comparisons": "Chronos-2 base vs ridge B4D_nopH, B5D, B5D_nopH (scope withB5 for B5D), vs diurnal-anomaly-7d, vs persistence; Chronos-2 small vs the same references. Reported, no Holm.",
    "gap": "MAE ratio Chronos-2 / reference on the lockbox per horizon. Gap to B4D 'closed' at a horizon if the ratio <= 1.05 and B4D does not pass gate #16 vs Chronos-2.",
    "size_for_T2": "T2 uses chronos-2-small instead of base only if small's lockbox MAE is within 3 % of base at every horizon and base does not pass gate #16 vs small at any horizon; otherwise base.",
    "speed": "Seconds per origin (all six horizons, three step groups) at torch threads = 2, batch 64, measured on the full run; pilot of 64 origins reported separately. Not comparable to RL-62 timings (8 threads) without that caveat.",
}


def run_dir() -> Path:
    return paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path: Path, obj) -> None:
    if path.exists():
        raise FileExistsError(f"refusing_to_overwrite:{path}")
    if isinstance(obj, pd.DataFrame):
        obj.to_csv(path, index=False)
    else:
        path.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")


def input_files() -> dict[str, Path]:
    files = {"baseline_predictions": FM_RUN / f"baseline-{TAG}" / "predictions.parquet", "diurnal_predictions": DIURNAL_BENCH / "predictions.parquet"}
    files.update({m: FM_RUN / f"fm-{TAG}-{m}-stride{STRIDE}.parquet" for m in STORED_FM})
    return files


# --------------------------------------------------------------------------- init
def stage_init(_args) -> None:
    root = run_dir()
    root.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[1]
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=repo).stdout.strip() or None
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "experiments", "tests"], capture_output=True, text=True, cwd=repo).stdout.strip()
    base_manifest = json.loads((FM_RUN / f"baseline-{TAG}" / "manifest.json").read_text(encoding="utf-8"))
    _write(root / "preregistration.json", {
        "question": "Paper 1 / T1: does zero-shot Chronos-2 (univariate, no covariates) beat ridge B4D and Chronos-Bolt base for NB1 water temperature at 15 min - 12 h on the H1.4 origins?",
        "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "git_head": head, "worktree_dirty": bool(dirty),
        "code_sha256": {"paper1_t1_chronos2.py": _sha256(Path(__file__)), "foundation_zero_shot.py": _sha256(Path(fz.__file__))},
        "models": {name: {"repo": repo_id, "revision": rev} for name, (repo_id, rev) in CHRONOS2.items()},
        "primary_model": PRIMARY,
        "covariates": "none (univariate target only; weather / tide come in T2)",
        "station": fz.STATION, "target": TAG, "horizons_minutes": list(fz.HORIZONS), "stride_minutes": STRIDE,
        "step_for_horizon": fz.STEP_FOR_HORIZON, "context_steps": fz.CONTEXT_STEPS,
        "context_note": "identical to H1.4 (RL-62) for an apples-to-apples model swap; Chronos-2's 8192-step context is not used in T1",
        "point_forecast": "median path, linearly interpolated at issued_at + h between window centres (foundation_zero_shot.interpolate_horizon)",
        "quantiles_saved": list(QUANTILES), "threads": THREADS, "batch": BATCH, "pilot_origins": 64,
        "information_set": "context ends at the 1-minute bin floor(issued_at - 1 min); foundation_zero_shot.assert_no_lookahead on 20 random origins",
        "origins": "persistence rows of B4_quality in baseline-Temperature/predictions.parquet thinned to minute-of-day % 15 == 0 (H1.4 set): 5 rolling folds x 7 days + lockbox 2026-10-10..24",
        "sensor_input": base_manifest["input"], "sensor_input_sha256": base_manifest["input_sha256"],
        "inputs_sha256": {k: _sha256(p) for k, p in input_files().items()},
        "scopes": {k: list(v) for k, v in RIDGE_SETS.items()},
        "references_stored": ["persistence", *[f"ridge_{s}" for s in RIDGE_SETS["withB5"]], *STORED_FM],
        "not_in_T1": "TimesFM 2.5 (only stride 60 stored; reported via --stride 60 as secondary), TiRex (licence 'other', deferred), conformal intervals (T4)",
        "verdict_rules": VERDICT_RULES,
        "lockbox_opened_for_chronos2": False,
    })
    print(root)


# --------------------------------------------------------------------------- forecast
def stack_quantiles(quantiles) -> np.ndarray:
    """Chronos-2 returns one ``(n_variates=1, H, Q)`` tensor per series -> ``(batch, H, Q)``."""
    return np.stack([np.asarray(q, dtype=np.float32)[0] for q in quantiles])


def as_univariate_batch(context: np.ndarray) -> np.ndarray:
    """``(batch, history)`` -> ``(batch, 1, history)``: Chronos-2 rejects 2-D input."""
    return np.ascontiguousarray(context[:, None, :])


def quantile_column(level: float) -> str:
    return f"q{int(round(level * 100)):02d}"


class Chronos2Forecaster:
    def __init__(self, repo: str, revision: str, threads: int):
        import torch
        from chronos import Chronos2Pipeline

        torch.set_num_threads(threads)
        self.torch = torch
        self.pipe = Chronos2Pipeline.from_pretrained(repo, revision=revision, device_map="cpu", torch_dtype=torch.float32)
        missing = set(QUANTILES) - set(self.pipe.quantiles)
        if missing:
            raise ValueError(f"quantiles_not_native:{sorted(missing)}")

    def quantile_paths(self, context: np.ndarray, length: int, batch: int) -> np.ndarray:
        out = []
        for i in range(0, len(context), batch):
            chunk = self.torch.tensor(as_univariate_batch(context[i:i + batch]))
            quantiles, _ = self.pipe.predict_quantiles(chunk, prediction_length=length, quantile_levels=list(QUANTILES), batch_size=batch)
            out.append(stack_quantiles(quantiles))
        return np.concatenate(out)


def stage_forecast(args) -> None:
    from experiments.forecast_sensor_v2 import load_sensor_data, truncate_local_date

    root = run_dir()
    if not (root / "preregistration.json").exists():
        raise FileNotFoundError("run_init_first")
    base = FM_RUN / f"baseline-{TAG}"
    base_manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    pilot = f"-pilot{args.limit}" if args.limit else ""
    out = root / f"fm-{TAG}-{args.model}-stride{STRIDE}{pilot}.parquet"
    if out.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out}")
    origins = fz.load_origins(base, STRIDE)
    if args.limit:
        origins = origins[origins["issued_at"].isin(origins["issued_at"].drop_duplicates().sample(args.limit, random_state=0))]
    raw = truncate_local_date(load_sensor_data(Path(base_manifest["input"]), fz.STATION), base_manifest.get("last_local_date"))
    grid = fz.Grid(raw, TAG)
    horizons = sorted(origins["horizon_minutes"].unique().tolist())
    steps = sorted({fz.STEP_FOR_HORIZON[h] for h in horizons})
    leak_checked = fz.assert_no_lookahead(raw, TAG, grid, origins["issued_at"].drop_duplicates(), steps)
    repo, revision = CHRONOS2[args.model]
    t0 = time.perf_counter()
    model = Chronos2Forecaster(repo, revision, THREADS)
    load_seconds = time.perf_counter() - t0
    blocks, timing = [], []
    for step in steps:
        step_h = [h for h in horizons if fz.STEP_FOR_HORIZON[h] == step]
        issued = origins.loc[origins["horizon_minutes"].isin(step_h), "issued_at"].drop_duplicates().sort_values().reset_index(drop=True)
        context = grid.contexts(issued, step, fz.CONTEXT_STEPS[step])
        length = fz.prediction_length(step, step_h)
        t1 = time.perf_counter()
        paths_q = model.quantile_paths(context, length, BATCH)
        seconds = time.perf_counter() - t1
        timing.append({"step_minutes": step, "context_steps": fz.CONTEXT_STEPS[step], "prediction_length": length, "n_forecasts": len(issued),
                       "seconds": seconds, "seconds_per_1000": 1000 * seconds / max(len(issued), 1), "context_nan_fraction": float(np.isnan(context).mean())})
        print(json.dumps(timing[-1]), flush=True)
        for h in step_h:
            block = {"horizon_minutes": h, "issued_at": issued}
            for j, level in enumerate(QUANTILES):
                block[quantile_column(level)] = fz.interpolate_horizon(paths_q[:, :, j], step, h)
            blocks.append(pd.DataFrame(block))
    preds = pd.concat(blocks, ignore_index=True)
    preds["prediction"] = preds[quantile_column(0.5)]
    preds = origins.merge(preds, on=["horizon_minutes", "issued_at"], how="left", validate="one_to_one")
    preds["model"] = args.model
    preds.to_parquet(out, index=False)
    n_origins = int(origins["issued_at"].nunique())
    meta = {"model": args.model, "repo": repo, "revision": revision, "stride_minutes": STRIDE, "threads": THREADS, "batch": BATCH,
            "load_seconds": load_seconds, "timing": timing, "n_origin_rows": len(preds), "n_unique_origins": n_origins,
            "seconds_per_origin_all_horizons": sum(t["seconds"] for t in timing) / max(n_origins, 1),
            "model_prediction_length": int(model.pipe.model_prediction_length), "model_context_length": int(model.pipe.model_context_length),
            "native_quantiles": list(model.pipe.quantiles), "limit": args.limit, "missing_predictions": int(preds["prediction"].isna().sum()),
            "lookahead_check_origins": leak_checked, "python": sys.version, "platform": platform.platform(), "cpu_count": os.cpu_count(),
            "env_threads": {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS")}, "packages": fz._versions()}
    _write(out.with_suffix(".json"), meta)
    print(json.dumps({k: meta[k] for k in ("model", "n_origin_rows", "n_unique_origins", "missing_predictions", "seconds_per_origin_all_horizons")}))


# --------------------------------------------------------------------------- evaluate
def _ridge_wide(pred: pd.DataFrame, sets: tuple[str, ...]) -> pd.DataFrame:
    pred = pred[pred["feature_set"].isin(sets)]
    pred = pred[pred["model"].eq("ridge") | (pred["model"].eq("persistence") & pred["feature_set"].eq("B4_quality"))].copy()
    pred["name"] = np.where(pred["model"].eq("persistence"), "persistence", "ridge_" + pred["feature_set"])
    wide = pred.pivot_table(index=["split", "fold", "horizon_minutes", "issued_at", "actual"], columns="name", values="prediction").reset_index()
    wide.columns.name = None
    return wide


def merge_model(wide: pd.DataFrame, fm: pd.DataFrame, name: str) -> tuple[pd.DataFrame, dict]:
    """Left-join one model's predictions on the origin key; its ``actual`` must equal ``wide``'s."""
    fm = fm[["split", "fold", "horizon_minutes", "issued_at", "actual", "prediction"]].rename(columns={"prediction": name, "actual": "_actual"})
    fm = fm.astype({"split": str, "fold": wide["fold"].dtype, "horizon_minutes": wide["horizon_minutes"].dtype})
    wide = wide.merge(fm, on=["split", "fold", "horizon_minutes", "issued_at"], how="left", validate="one_to_one")
    both = wide["_actual"].notna()
    diff = float((wide.loc[both, "actual"] - wide.loc[both, "_actual"]).abs().max()) if both.any() else float("nan")
    if not both.any() or diff > 1e-9:
        raise AssertionError(f"origin_mismatch:{name}:{diff}")
    return wide.drop(columns="_actual"), {"matched": int(both.sum()), "rows": int(len(wide)), "max_abs_actual_diff": diff}


def holm(p: pd.Series) -> pd.Series:
    order = p.sort_values().index
    m = len(p)
    adjusted = np.minimum(1.0, np.maximum.accumulate([(m - i) * p[k] for i, k in enumerate(order)]))
    return pd.Series(adjusted, index=order).reindex(p.index)


def verdicts(gate: pd.DataFrame, metrics: pd.DataFrame, candidate: str, references: list[str]) -> pd.DataFrame:
    """Per (reference, horizon) outcome under ``VERDICT_RULES['vs_reference']`` plus the lockbox MAE ratio."""
    lock = metrics[metrics["split"].astype(str).eq("lockbox")].set_index(["model", "horizon_minutes"])["mae"]
    rows = []
    for ref in references:
        for h in sorted(gate["horizon_minutes"].unique()):
            fwd = gate[(gate.model == candidate) & (gate.reference == ref) & (gate.horizon_minutes == h)]
            rev = gate[(gate.model == ref) & (gate.reference == candidate) & (gate.horizon_minutes == h)]
            if fwd.empty or rev.empty:
                continue
            win, lose = bool(fwd.iloc[0].gate16_pass), bool(rev.iloc[0].gate16_pass)
            ratio = float(lock[(candidate, h)] / lock[(ref, h)])
            rows.append({"candidate": candidate, "reference": ref, "horizon_minutes": int(h), "mae_ratio": ratio,
                         "folds_beating": int(fwd.iloc[0].folds_beating), "folds_beaten": int(rev.iloc[0].folds_beating),
                         "lockbox_dm_p": float(fwd.iloc[0].lockbox_dm_p),
                         "outcome": "chronos2_wins" if win else "reference_wins" if lose else "tie",
                         "gap_closed": bool(ratio <= 1.05 and not lose)})
    return pd.DataFrame(rows)


def summarise(table: pd.DataFrame) -> dict:
    out = {}
    for (cand, ref), part in table.groupby(["candidate", "reference"]):
        wins, losses = int((part.outcome == "chronos2_wins").sum()), int((part.outcome == "reference_wins").sum())
        out[f"{cand}__vs__{ref}"] = {"chronos2_wins": wins, "reference_wins": losses, "ties": int(len(part) - wins - losses),
                                    "overall": "better" if wins >= 4 else "worse" if losses >= 4 else "mixed",
                                    "gap_closed_horizons": part.loc[part.gap_closed, "horizon_minutes"].tolist()}
    return out


def size_choice(gate: pd.DataFrame, metrics: pd.DataFrame) -> dict:
    lock = metrics[metrics["split"].astype(str).eq("lockbox")].pivot(index="horizon_minutes", columns="model", values="mae")
    if not {"chronos-2-small", "chronos-2-base"} <= set(lock.columns):
        return {"choice": None, "reason": "both sizes needed"}
    rel = (lock["chronos-2-small"] / lock["chronos-2-base"] - 1)
    base_beats = gate[(gate.model == "chronos-2-base") & (gate.reference == "chronos-2-small") & gate.gate16_pass]["horizon_minutes"].tolist()
    small_ok = bool((rel <= 0.03).all() and not base_beats)
    return {"choice": "chronos-2-small" if small_ok else "chronos-2-base", "small_vs_base_rel_mae": rel.round(4).to_dict(), "base_gate_pass_vs_small": base_beats}


def stage_evaluate(args) -> None:
    from experiments.forecast_h1_diurnal import _load_predictions

    root = run_dir()
    out = root / f"eval-{TAG}-stride{args.stride}"
    if out.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out}")
    sources = {m: root / f"fm-{TAG}-{m}-stride{STRIDE}.parquet" for m in CHRONOS2}
    sources = {m: p for m, p in sources.items() if p.exists()}
    if PRIMARY not in sources:
        raise FileNotFoundError(f"missing_primary:{PRIMARY}")
    stored = {m: FM_RUN / f"fm-{TAG}-{m}-stride{STRIDE}.parquet" for m in STORED_FM}
    if args.stride % 60 == 0:
        stored["timesfm-2.5-200m"] = FM_RUN / f"fm-{TAG}-timesfm-2.5-200m-stride60.parquet"
    pred = _load_predictions(DIURNAL_BENCH / "predictions.parquet")
    pred = pred[fz.thin_mask(pred["issued_at"], args.stride)]
    chronos2 = list(sources)
    others = list(stored)
    results, checks = {}, {}
    for scope, sets in RIDGE_SETS.items():
        wide = _ridge_wide(pred, sets)
        wide["split"] = wide["split"].astype(str)
        for name, path in {**stored, **sources}.items():
            fm = pd.read_parquet(path)
            wide, checks[f"{scope}:{name}"] = merge_model(wide, fm[fz.thin_mask(fm["issued_at"], args.stride)], name)
        models = [c for c in wide.columns if c.startswith("ridge_")] + others + chronos2
        before = len(wide)
        wide = wide.dropna(subset=models)
        checks[f"{scope}:rows_kept"] = {"before": before, "after": int(len(wide))}
        metrics, dm, gate = fz.evaluate_frame(wide, [], models, args.stride)
        references = ["persistence", *[c for c in models if c not in chronos2]]
        table = pd.concat([verdicts(gate, metrics, cand, references + [c for c in chronos2 if c != cand]) for cand in chronos2], ignore_index=True)
        results[scope] = (metrics, dm, gate, fz.summary_table(metrics, dm, gate), table)
    primary = results["B4family"][4]
    mask = primary.candidate.eq(PRIMARY) & primary.reference.isin(["ridge_B4_quality_diurnal", "chronos-bolt-base"])
    for scope in results:
        tab = results[scope][4]
        tab["primary"] = False
        tab["holm_p"] = np.nan
        if scope == "B4family":
            tab.loc[mask, "primary"] = True
            tab.loc[mask, "holm_p"] = holm(tab.loc[mask, "lockbox_dm_p"])
    out.mkdir(parents=False, exist_ok=False)
    for scope, frames in results.items():
        for name, frame in zip(("metrics", "dm_tests", "gate16", "summary", "verdicts"), frames):
            _write(out / f"{name}-{scope}.csv", frame)
    lock = results["B4family"][0]
    lock = lock[lock["split"].astype(str).eq("lockbox")].pivot(index="horizon_minutes", columns="model", values="mae")
    _write(out / "lockbox_mae-B4family.csv", lock.reset_index())
    verdict = {scope: summarise(results[scope][4]) for scope in results}
    verdict["size_for_T2"] = size_choice(results["B4family"][2], results["B4family"][0])
    _write(out / "verdict.json", verdict)
    _write(out / "manifest.json", {"stride_minutes": args.stride, "chronos2_sources": {m: str(p) for m, p in sources.items()},
                                   "chronos2_sha256": {m: _sha256(p) for m, p in sources.items()},
                                   "stored_sources": {m: str(p) for m, p in stored.items()}, "stored_sha256": {m: _sha256(p) for m, p in stored.items()},
                                   "diurnal_bench_sha256": _sha256(DIURNAL_BENCH / "predictions.parquet"), "origin_checks": checks,
                                   "verdict_rules": VERDICT_RULES})
    print(lock.round(4).to_string())
    print(json.dumps(verdict, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="stage", required=True)
    sub.add_parser("init")
    p = sub.add_parser("forecast")
    p.add_argument("--model", required=True, choices=tuple(CHRONOS2))
    p.add_argument("--limit", type=int, help="pilot: random subset of origins (timing only, never evaluated)")
    p = sub.add_parser("evaluate")
    p.add_argument("--stride", type=int, default=STRIDE, choices=(15, 60))
    args = parser.parse_args()
    {"init": stage_init, "forecast": stage_forecast, "evaluate": stage_evaluate}[args.stage](args)


if __name__ == "__main__":
    main()
