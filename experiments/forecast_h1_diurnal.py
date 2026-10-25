"""H1.9: multi-day diurnal features for the ridge sensor forecast (research-only).

Stages, all writing into one run directory under ``paths.EXPERIMENT_OUTPUT_DIR`` (write-once):

``init``       create the run directory (exist_ok=False) and write ``preregistration.json``
               (feature list, fill rule, verdict rules, code sha256) BEFORE any result exists.
``bench``      ``forecast_sensor_v2.run_benchmark`` (ridge) for B4 / B4D / B5 / B5D (+ _nopH) of one
               config, then ``forecast_gate16_report.report`` (gate vs persistence) and the
               diurnal-vs-parent gate #16 (``foundation_zero_shot.evaluate_frame``, stride 1).
``compare-fm`` the ridge predictions thinned like H1.4 (minute-of-day % stride == 0) against the
               saved H1.4 foundation-model / diurnal-anomaly predictions on identical origins.
``seasonal``   Temperature, train valid_at < 01/09 (local), test issued 15/09-24/10: B4 vs B4D
               (and _nopH), persistence and the naive 7-day diurnal anomaly.

    set HAP_ARTIFACTS_DIR=D:/2impusc/Hydro-Aqua-Predict/artifacts
    .venv/Scripts/python experiments/forecast_h1_diurnal.py init
    .venv/Scripts/python experiments/forecast_h1_diurnal.py bench --tag Temperature
    .venv/Scripts/python experiments/forecast_h1_diurnal.py compare-fm --tag Temperature --stride 15
    .venv/Scripts/python experiments/forecast_h1_diurnal.py seasonal
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from experiments import forecast_sensor_v2 as fs  # noqa: E402

STATION = "06M26042804"
RUN_NAME = "forecast-h1-diurnal-20261025"
INPUT = paths.EXPERIMENT_OUTPUT_DIR / "sensor-history-20261024" / f"{STATION}.csv"
SNAPSHOTS = paths.EXPERIMENT_OUTPUT_DIR / "external-context-06M26042804-2026-05-28_2026-10-24" / "weather-snapshots-reconstructed.jsonl"
FM_RUN = paths.EXPERIMENT_OUTPUT_DIR / "foundation-zero-shot-20261024"
ALL_SETS = ("B4_quality", "B4_quality_nopH", "B4_quality_diurnal", "B4_quality_diurnal_nopH",
            "B5_external_as_issued", "B5_external_as_issued_nopH", "B5_external_as_issued_diurnal", "B5_external_as_issued_diurnal_nopH")
CONFIGS = {
    "Temperature": {"target": "Temperature", "horizons": (15, 30, 60, 180, 360, 720), "feature_sets": ALL_SETS, "end": None},
    "pH-pre-drift": {"target": "pH", "horizons": (60, 180), "feature_sets": ("B4_quality", "B4_quality_diurnal", "B5_external_as_issued", "B5_external_as_issued_diurnal"), "end": "2026-09-18"},
    "NH4": {"target": "NH4", "horizons": (60, 180), "feature_sets": ALL_SETS, "end": None},
}
# (candidate, reference) for paired lockbox DM (feature-set contributions).
DIURNAL_PAIRS = (
    ("B4_quality_diurnal", "B4_quality"), ("B4_quality_diurnal_nopH", "B4_quality_nopH"),
    ("B5_external_as_issued_diurnal", "B5_external_as_issued"), ("B5_external_as_issued_diurnal_nopH", "B5_external_as_issued_nopH"),
    ("B5_external_as_issued_diurnal", "B4_quality_diurnal"), ("B5_external_as_issued_diurnal_nopH", "B4_quality_diurnal_nopH"),
)
FM_FILES = {
    "Temperature": {15: ("chronos-bolt-base", "chronos-bolt-small", "diurnal-anomaly-7d"), 60: ("timesfm-2.5-200m",)},
    "pH-pre-drift": {15: ("chronos-bolt-small", "diurnal-anomaly-7d")},
    "NH4": {15: ("chronos-bolt-small", "diurnal-anomaly-7d")},
}
SEASONAL = {"train_valid_before_local": "2026-09-01", "test_issued_from_local": "2026-09-15", "sets": ("B4_quality", "B4_quality_diurnal", "B4_quality_nopH", "B4_quality_diurnal_nopH")}
VERDICT_RULES = {
    "replace": "B4D replaces B4 only if B4D passes gate #16 vs ridge B4 at >= 4 of 6 Temperature horizons AND passes gate #16 vs persistence at all 6 horizons. Same rule reported for B4D_nopH vs B4_nopH and B5D vs B5 (secondary).",
    "gate16": ">= 4/5 rolling folds with lower MAE and RMSE than the reference AND lockbox Diebold-Mariano (abs loss, rectangular kernel, HLN, horizon_steps = ceil(h / stride)) p < 0.05 with the candidate better.",
    "fm_gap": "MAE ratio ridge/FM per horizon on identical thinned origins (H1.4 stride 15; TimesFM stride 60). Gap 'closed' at a horizon if ratio <= 1.05 and the FM does not pass gate #16 vs the ridge; else 'narrowed' if ratio(B4D/FM) < ratio(B4/FM).",
    "seasonal": "Diurnal block 'degrades out of range' if on the 15/09-24/10 test B4D has higher MAE than B4 at any horizon with DM p < 0.05 (B4D worse).",
}


def run_dir() -> Path:
    return paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _new_dir(path: Path) -> Path:
    if not run_dir().exists():
        raise FileNotFoundError("run_init_first")
    path.mkdir(parents=False, exist_ok=False)
    return path


def _write(path: Path, obj) -> None:
    if path.exists():
        raise FileExistsError(f"refusing_to_overwrite:{path}")
    if isinstance(obj, pd.DataFrame):
        obj.to_csv(path, index=False)
    else:
        path.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")


# --------------------------------------------------------------------------- init
def stage_init(_args) -> None:
    root = run_dir()
    root.mkdir(parents=True, exist_ok=False)
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1]).stdout.strip()
    except OSError:
        head = None
    _write(root / "preregistration.json", {
        "question": "H1.9: does a multi-day diurnal block close the ridge gap to the naive diurnal anomaly / foundation models (RL-62)?",
        "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "git_head": head,
        "code_sha256": {"forecast_sensor_v2.py": _sha256(Path(fs.__file__)), "forecast_h1_diurnal.py": _sha256(Path(__file__))},
        "diurnal_columns": list(fs.DIURNAL_COLUMNS), "window_minutes": fs.DIURNAL_WINDOW_MINUTES, "profile_days": fs.DIURNAL_PROFILE_DAYS,
        "min_days": fs.DIURNAL_MIN_DAYS, "amp_min_minutes": fs.DIURNAL_AMP_MIN_MINUTES, "fill_rule": fs.DIURNAL_FILL_RULE,
        "information_set": "1-minute median bins strictly before the bin of issued_at - 1 min",
        "configs": CONFIGS, "seasonal": SEASONAL, "fm_files": {k: {str(s): v for s, v in d.items()} for k, d in FM_FILES.items()},
        "input": str(INPUT), "input_sha256": _sha256(INPUT), "snapshots": str(SNAPSHOTS), "snapshots_sha256": _sha256(SNAPSHOTS),
        "verdict_rules": VERDICT_RULES,
    })
    print(root)


# --------------------------------------------------------------------------- bench
def _wide(pred: pd.DataFrame, persistence_set: str, sets: list[str]) -> pd.DataFrame:
    pred = pred[pred["feature_set"].isin(sets)].copy()
    pred = pred[(pred["model"] == "ridge") | (pred["feature_set"] == persistence_set)]
    pred["name"] = np.where(pred["model"] == "persistence", "persistence", "ridge_" + pred["feature_set"])
    wide = pred.pivot_table(index=["split", "fold", "horizon_minutes", "issued_at", "actual"], columns="name", values="prediction").reset_index()
    wide.columns.name = None
    return wide


def _family_gate(pred: pd.DataFrame, stride: int = 1) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    from experiments.foundation_zero_shot import evaluate_frame

    out = [], [], []
    present = set(pred["feature_set"])
    for parent in ("B4_quality", "B5_external_as_issued"):
        sets = [s for s in ALL_SETS if fs.base_feature_set(s) == parent and s in present]
        if parent not in sets:
            continue
        wide = _wide(pred, parent, sets)
        refs = [f"ridge_{s}" for s in sets if not fs.is_diurnal(s)]
        cands = [f"ridge_{s}" for s in sets if fs.is_diurnal(s)]
        for target, frame in zip(out, evaluate_frame(wide, cands, refs, stride)):
            target.append(frame.assign(family=parent))
    return tuple(pd.concat(parts, ignore_index=True) for parts in out)


def _load_predictions(path: Path) -> pd.DataFrame:
    pred = pd.read_parquet(path, columns=["split", "fold", "target", "horizon_minutes", "feature_set", "model", "issued_at", "actual", "prediction"])
    for column in ("split", "target", "feature_set", "model"):
        pred[column] = pred[column].astype(str)
    return pred


def stage_bench(args) -> None:
    from experiments.forecast_gate16_report import paired_dm, report

    cfg = CONFIGS[args.tag]
    out = run_dir() / f"bench-{args.tag}"
    if out.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out}")
    fs.run_benchmark(INPUT, STATION, out, SNAPSHOTS, write_predictions=True, selected_feature_sets=cfg["feature_sets"], selected_models=("ridge",),
                     selected_targets=(cfg["target"],), selected_horizons=cfg["horizons"], prediction_models=("ridge",), last_local_date=cfg["end"])
    report(out)
    pred = _load_predictions(out / "predictions.parquet")
    metrics, dm, gate = _family_gate(pred)
    _write(out / "diurnal_family_metrics.csv", metrics)
    _write(out / "diurnal_family_dm.csv", dm)
    _write(out / "diurnal_family_gate16.csv", gate)
    pairs = [p for p in DIURNAL_PAIRS if set(p) <= set(pred["feature_set"])]
    _write(out / "diurnal_paired_dm.csv", paired_dm(pred, pairs))
    print(gate[gate["model"].str.contains("diurnal")].to_string(index=False))


# --------------------------------------------------------------------------- compare-fm
def stage_compare_fm(args) -> None:
    from experiments.foundation_zero_shot import evaluate_frame, summary_table, thin_mask

    bench = run_dir() / f"bench-{args.tag}"
    pred = _load_predictions(bench / "predictions.parquet")
    pred = pred[thin_mask(pred["issued_at"], args.stride)]
    files = [m for stride, models in FM_FILES[args.tag].items() if args.stride % stride == 0 for m in models]
    sources = {m: FM_RUN / f"fm-{args.tag}-{m}-stride{s}.parquet" for s, models in FM_FILES[args.tag].items() if args.stride % s == 0 for m in models}
    out = run_dir() / f"eval-fm-{args.tag}-stride{args.stride}"
    if out.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out}")
    results, checks = {}, {}
    for scope, sets in (("B4family", [s for s in ALL_SETS if fs.base_feature_set(s) == "B4_quality"]), ("withB5", list(ALL_SETS))):
        sets = [s for s in sets if s in set(pred["feature_set"])]
        wide = _wide(pred, "B4_quality", sets)
        wide["split"] = wide["split"].astype(str)
        for model in files:
            fm = pd.read_parquet(sources[model])
            fm = fm[thin_mask(fm["issued_at"], args.stride)]
            fm = fm[["split", "fold", "horizon_minutes", "issued_at", "actual", "prediction"]].rename(columns={"prediction": model, "actual": f"_actual_{model}"})
            fm["split"] = fm["split"].astype(str)
            fm["fold"] = fm["fold"].astype(wide["fold"].dtype)
            fm["horizon_minutes"] = fm["horizon_minutes"].astype(wide["horizon_minutes"].dtype)
            wide = wide.merge(fm, on=["split", "fold", "horizon_minutes", "issued_at"], how="left", validate="one_to_one")
            both = wide[f"_actual_{model}"].notna()
            checks[f"{scope}:{model}"] = {"matched": int(both.sum()), "rows": int(len(wide)), "max_abs_actual_diff": float((wide.loc[both, "actual"] - wide.loc[both, f"_actual_{model}"]).abs().max())}
            if checks[f"{scope}:{model}"]["max_abs_actual_diff"] > 1e-9:
                raise AssertionError(f"origin_mismatch:{model}")
            wide = wide.drop(columns=f"_actual_{model}")
        models = [c for c in wide.columns if c.startswith("ridge_")] + files
        n_before = len(wide)
        wide = wide.dropna(subset=models)
        checks[f"{scope}:rows_kept"] = {"before": n_before, "after": int(len(wide))}
        metrics, dm, gate = evaluate_frame(wide, [], models, args.stride)
        results[scope] = (metrics, dm, gate, summary_table(metrics, dm, gate))
    out.mkdir(parents=False, exist_ok=False)
    for scope, frames in results.items():
        for name, frame in zip(("metrics", "dm_tests", "gate16", "summary"), frames):
            _write(out / f"{name}-{scope}.csv", frame)
    lock = results["B4family"][0]
    lock = lock[lock["split"].astype(str).eq("lockbox")].pivot(index="horizon_minutes", columns="model", values="mae")
    ratios = pd.DataFrame(index=lock.index)
    for ridge in [c for c in lock.columns if c.startswith("ridge_")]:
        for model in files:
            ratios[f"{ridge}/{model}"] = lock[ridge] / lock[model]
    _write(out / "mae_ratio_lockbox-B4family.csv", ratios.reset_index())
    _write(out / "manifest.json", {"tag": args.tag, "stride_minutes": args.stride, "bench": str(bench), "fm_sources": {m: str(p) for m, p in sources.items()},
                                   "fm_sha256": {m: _sha256(p) for m, p in sources.items()}, "origin_checks": checks,
                                   "scopes": {"B4family": "B4/B4D(+nopH) + FMs on every H1.4 origin", "withB5": "adds B5/B5D(+nopH); origins without a B5 forecast dropped"},
                                   "gate16": VERDICT_RULES["gate16"]})
    print(lock.round(4).to_string())
    print(ratios.round(3).to_string())


# --------------------------------------------------------------------------- seasonal
def stage_seasonal(_args) -> None:
    from sklearn.base import clone

    from experiments.forecast_dm_test import diebold_mariano

    out = run_dir() / "seasonal-shift"
    if out.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out}")
    raw = fs.load_sensor_data(INPUT, STATION)
    target = "Temperature"
    grid = fs.MinuteGrid(raw, target)
    train_end = pd.Timestamp(SEASONAL["train_valid_before_local"], tz=fs.LOCAL_TZ).tz_convert("UTC")
    test_start = pd.Timestamp(SEASONAL["test_issued_from_local"], tz=fs.LOCAL_TZ).tz_convert("UTC")
    rows, dm_rows, weekly, blocks, amp_rows = [], [], [], [], []
    for horizon in CONFIGS["Temperature"]["horizons"]:
        frame, all_features = fs.build_frame(raw, target, horizon, "B4_quality", station=STATION)
        frame = frame.join(fs.diurnal_features(grid, frame["issued_at"], horizon, frame[f"{target}_lag_1m"].to_numpy()))
        train = frame[frame["valid_at"] < train_end]
        test = frame[frame["issued_at"] >= test_start]
        preds = {"persistence": test[f"{target}_lag_1m"].to_numpy(),
                 "diurnal_anomaly_7d_naive": (test[f"{target}_lag_1m"] + test["diel_anom_7d"]).to_numpy()}
        for name in SEASONAL["sets"]:
            features = fs.feature_subset(all_features, target, name.replace(fs.DIURNAL_SUFFIX, ""))
            if fs.is_diurnal(name):
                features += list(fs.DIURNAL_COLUMNS)
            model = clone(fs._models()["ridge"]).fit(train[features], train["target"])
            preds[f"ridge_{name}"] = model.predict(test[features])
        actual = test["target"].to_numpy()
        for name, p in preds.items():
            err = p - actual
            rows.append({"horizon_minutes": horizon, "model": name, "n_train": len(train), "n_test": len(test), "mae": float(np.mean(np.abs(err))),
                         "rmse": float(np.sqrt(np.mean(err ** 2))), "bias": float(err.mean()), "p95_ae": float(np.quantile(np.abs(err), .95))})
            week = test["issued_at"].dt.tz_convert(fs.LOCAL_TZ).dt.strftime("%G-W%V").to_numpy()
            for w, grp in pd.DataFrame({"week": week, "ae": np.abs(err)}).groupby("week"):
                weekly.append({"horizon_minutes": horizon, "model": name, "iso_week": w, "n": len(grp), "mae": float(grp["ae"].mean())})
            blocks.append(pd.DataFrame({"horizon_minutes": horizon, "model": name, "issued_at": test["issued_at"].to_numpy(), "actual": actual, "prediction": p}))
        for cand, ref in (("ridge_B4_quality_diurnal", "ridge_B4_quality"), ("ridge_B4_quality_diurnal_nopH", "ridge_B4_quality_nopH"),
                          ("ridge_B4_quality_diurnal", "persistence"), ("ridge_B4_quality", "persistence"), ("ridge_B4_quality_nopH", "persistence"),
                          ("ridge_B4_quality_diurnal_nopH", "persistence"), ("ridge_B4_quality_diurnal", "diurnal_anomaly_7d_naive"), ("ridge_B4_quality_diurnal_nopH", "diurnal_anomaly_7d_naive")):
            stat, p = diebold_mariano(preds[cand] - actual, preds[ref] - actual, horizon_steps=horizon, loss="abs", kernel="rectangular")
            mc, mr = float(np.mean(np.abs(preds[cand] - actual))), float(np.mean(np.abs(preds[ref] - actual)))
            dm_rows.append({"horizon_minutes": horizon, "candidate": cand, "reference": ref, "n": len(actual), "mae_candidate": mc, "mae_reference": mr,
                            "mae_change_pct": (mc / mr - 1) * 100, "dm_stat": stat, "dm_p": p, "candidate_better": bool(np.isfinite(p) and stat < 0 and p < 0.05),
                            "candidate_worse": bool(np.isfinite(p) and stat > 0 and p < 0.05)})
        for split, part in (("train", train), ("test", test)):
            q = part["diel_amp_24h"].quantile([.1, .5, .9])
            amp_rows.append({"horizon_minutes": horizon, "split": split, "amp_p10": q.iloc[0], "amp_p50": q.iloc[1], "amp_p90": q.iloc[2],
                             "fill_rate": float(part["diel_fill_flag"].mean()), "issued_from": str(part["issued_at"].min()), "issued_to": str(part["issued_at"].max()),
                             "valid_to": str(part["valid_at"].max())})
    out.mkdir(parents=False, exist_ok=False)
    _write(out / "metrics.csv", pd.DataFrame(rows))
    _write(out / "dm_tests.csv", pd.DataFrame(dm_rows))
    _write(out / "metrics_weekly.csv", pd.DataFrame(weekly))
    _write(out / "amplitude_train_vs_test.csv", pd.DataFrame(amp_rows))
    pd.concat(blocks, ignore_index=True).to_parquet(out / "predictions.parquet", index=False)
    _write(out / "manifest.json", {"input": str(INPUT), "input_sha256": _sha256(INPUT), **SEASONAL, "train_rule": "valid_at < train_valid_before_local 00:00",
                                   "test_rule": "issued_at >= test_issued_from_local 00:00 until end of history", "dm": "abs loss, rectangular kernel, HLN, horizon_steps = h",
                                   "note": "pH drift from 19/09 is inside the test; the _nopH pair is the clean comparison"})
    print(pd.DataFrame(rows).pivot(index="horizon_minutes", columns="model", values="mae").round(4).to_string())
    print(pd.DataFrame(dm_rows)[["horizon_minutes", "candidate", "reference", "mae_change_pct", "dm_p"]].round(4).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="stage", required=True)
    sub.add_parser("init")
    p = sub.add_parser("bench"); p.add_argument("--tag", required=True, choices=tuple(CONFIGS))
    p = sub.add_parser("compare-fm"); p.add_argument("--tag", required=True, choices=tuple(CONFIGS)); p.add_argument("--stride", type=int, default=15)
    sub.add_parser("seasonal")
    args = parser.parse_args()
    {"init": stage_init, "bench": stage_bench, "compare-fm": stage_compare_fm, "seasonal": stage_seasonal}[args.stage](args)


if __name__ == "__main__":
    main()
