"""Gate #16 report for a ``forecast_sensor_v2`` run directory (research-only).

Writes, next to ``metrics_per_fold.csv`` / ``predictions.parquet`` (never overwriting):

- ``dm_tests.csv``            model vs persistence, lockbox, abs loss, rectangular kernel (decisions #16)
- ``gate16_summary.csv``      >= 4/5 rolling folds beat persistence (MAE) + DM lockbox p < 0.05
- ``lockbox_check.json``      every rolling-fold label ends before the lockbox, and the lockbox
                              window (start / last issue) is identical across feature sets
- ``nopH_vs_withpH_dm.csv``   B4/B5 vs their ``_nopH`` variant (same columns as A1, RL-18)
- ``paired_dm.csv``           feature-set contributions (B5 vs B4, B4 vs B0, ...), lockbox DM

    python experiments/forecast_gate16_report.py artifacts/experiments/<run>
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.forecast_dm_test import diebold_mariano, write_dm_tests  # noqa: E402

NOPH_PAIRS = (("B4_quality", "B4_quality_nopH"), ("B5_external_as_issued", "B5_external_as_issued_nopH"))
# (candidate, reference): DM < 0 means the candidate is better.
CONTRIBUTION_PAIRS = (
    ("B4_quality", "B0_lags"),
    ("B5_external_as_issued", "B4_quality"),
    ("B5_external_as_issued_nopH", "B4_quality_nopH"),
    ("B4_quality_nopH", "B0_lags"),
)


def gate16_summary(metrics: pd.DataFrame, dm: pd.DataFrame, model: str = "ridge") -> pd.DataFrame:
    """Gate #16: >= 4 of 5 rolling folds with lower MAE than persistence and lockbox DM p < 0.05
    (statistic < 0).  Fewer than 5 available folds can never pass."""
    rows = []
    keys = ["target", "horizon_minutes", "feature_set"]
    persistence = metrics[metrics["model"] == "persistence"]
    for (target, horizon, feature_set), grp in metrics[metrics["model"] == model].groupby(keys):
        base = persistence[(persistence["target"] == target) & (persistence["horizon_minutes"] == horizon)
                           & (persistence["feature_set"] == feature_set)]
        roll = grp[grp["split"] == "rolling"].set_index("fold")["mae"]
        proll = base[base["split"] == "rolling"].set_index("fold")["mae"].reindex(roll.index)
        lock = grp[grp["split"] == "lockbox"]
        plock = base[base["split"] == "lockbox"]
        if roll.empty or lock.empty or plock.empty:
            continue
        won = int((roll < proll).sum())
        test = dm[(dm["target"] == target) & (dm["horizon_minutes"] == horizon)
                  & (dm["feature_set"] == feature_set) & (dm["model"] == model)]
        p_value = float(test["p_value"].iloc[0]) if len(test) else math.nan
        stat = float(test["dm_stat"].iloc[0]) if len(test) else math.nan
        passed = len(roll) >= 5 and won >= 4 and p_value < 0.05 and stat < 0
        lock_mae, pers_mae = float(lock["mae"].iloc[0]), float(plock["mae"].iloc[0])
        rows.append({"target": target, "horizon_minutes": int(horizon), "feature_set": feature_set,
                     "n_lock": int(lock["n_test"].iloc[0]), "lock_mae": round(lock_mae, 4), "pers_mae": round(pers_mae, 4),
                     "skill_pct": round((1 - lock_mae / pers_mae) * 100, 1),
                     "rolling_skill_pct_mean": round(float(((proll - roll) / proll * 100).mean()), 1),
                     "folds_won": f"{won}/{len(roll)}", "dm_p": float(f"{p_value:.3g}") if np.isfinite(p_value) else p_value,
                     "dm_stat": round(stat, 2) if np.isfinite(stat) else stat, "gate": "PASS" if passed else "fail"})
    return pd.DataFrame(rows)


def lockbox_check(fold_labels: list[dict]) -> dict:
    """Re-assert decision #16 from ``fold_label_check.json`` and check the lockbox window is shared."""
    frame = pd.DataFrame(fold_labels)
    if frame.empty:
        return {"rows": 0, "fold_labels_clear_of_lockbox": None, "per_target_horizon": []}
    frame["max_fold_valid_at"] = pd.to_datetime(frame["max_fold_valid_at"], utc=True)
    frame["lockbox_start"] = pd.to_datetime(frame["lockbox_start"], utc=True)
    clear = bool((frame["max_fold_valid_at"] < frame["lockbox_start"]).all())
    per = []
    for (target, horizon), grp in frame.groupby(["target", "horizon_minutes"]):
        per.append({"target": target, "horizon_minutes": int(horizon),
                    "lockbox_start": sorted({str(v) for v in grp["lockbox_start"]}),
                    "last_issued_at": sorted(set(grp["last_issued_at"])),
                    "shared_lockbox_window": grp["lockbox_start"].nunique() == 1 and grp["last_issued_at"].nunique() == 1,
                    "folds_per_feature_set": {k: int(v) for k, v in grp.groupby("feature_set")["fold"].nunique().items()},
                    "max_fold_valid_at": str(grp["max_fold_valid_at"].max())})
    return {"rows": int(len(frame)), "fold_labels_clear_of_lockbox": clear,
            "all_windows_shared": all(item["shared_lockbox_window"] for item in per), "per_target_horizon": per}


def _paired(predictions: pd.DataFrame, target: str, horizon: int, candidate: str, reference: str, model: str) -> pd.DataFrame:
    sel = predictions[(predictions["target"] == target) & (predictions["horizon_minutes"] == horizon)
                      & (predictions["model"] == model) & (predictions["split"] == "lockbox")]
    a = sel[sel["feature_set"] == candidate][["issued_at", "actual", "prediction"]]
    b = sel[sel["feature_set"] == reference][["issued_at", "actual", "prediction"]]
    paired = a.merge(b, on="issued_at", suffixes=("_cand", "_ref"), validate="one_to_one").sort_values("issued_at")
    paired["e_cand"] = paired["prediction_cand"] - paired["actual_cand"]
    paired["e_ref"] = paired["prediction_ref"] - paired["actual_ref"]
    return paired


def paired_dm(predictions: pd.DataFrame, pairs, model: str = "ridge") -> pd.DataFrame:
    rows = []
    for (target, horizon), _ in predictions.groupby(["target", "horizon_minutes"], observed=True):
        for candidate, reference in pairs:
            paired = _paired(predictions, target, int(horizon), candidate, reference, model)
            if paired.empty:
                continue
            stat, p = diebold_mariano(paired["e_cand"].to_numpy(), paired["e_ref"].to_numpy(), horizon_steps=int(horizon), loss="abs", kernel="rectangular")
            mae_c, mae_r = float(paired["e_cand"].abs().mean()), float(paired["e_ref"].abs().mean())
            rows.append({"target": target, "horizon_minutes": int(horizon), "candidate": candidate, "reference": reference,
                         "n": int(len(paired)), "mae_candidate": mae_c, "mae_reference": mae_r,
                         "candidate_mae_change_pct": (mae_c / mae_r - 1) * 100, "dm_stat": stat, "dm_p": p})
    return pd.DataFrame(rows)


def nopH_vs_withpH(predictions: pd.DataFrame, metrics: pd.DataFrame, model: str = "ridge") -> pd.DataFrame:
    """Same columns as A1 ``nopH_vs_withpH_dm.csv`` (RL-18)."""
    rows = []
    for (target, horizon), _ in predictions.groupby(["target", "horizon_minutes"], observed=True):
        for with_ph, no_ph in NOPH_PAIRS:
            paired = _paired(predictions, target, int(horizon), no_ph, with_ph, model)
            if paired.empty:
                continue
            stat, p = diebold_mariano(paired["e_cand"].to_numpy(), paired["e_ref"].to_numpy(), horizon_steps=int(horizon), loss="abs", kernel="rectangular")
            mae_w, mae_n = float(paired["e_ref"].abs().mean()), float(paired["e_cand"].abs().mean())
            rows.append({"base": with_ph, "horizon_minutes": int(horizon), "split": "lockbox", "n": int(len(paired)), "mae_with_pH": mae_w,
                         "mae_nopH": mae_n, "nopH_mae_change_pct": (mae_n / mae_w - 1) * 100, "dm_stat_nopH_vs_pH": stat, "dm_p": p, "folds_nopH_better": ""})
            roll = metrics[(metrics["split"] == "rolling") & (metrics["model"] == model) & (metrics["target"] == target) & (metrics["horizon_minutes"] == horizon)]
            w = roll[roll["feature_set"] == with_ph].set_index("fold")
            n = roll[roll["feature_set"] == no_ph].set_index("fold")
            folds = w.index.intersection(n.index)
            if len(folds):
                n_test = w.loc[folds, "n_test"]
                mae_w = float((w.loc[folds, "mae"] * n_test).sum() / n_test.sum())
                mae_n = float((n.loc[folds, "mae"] * n_test).sum() / n_test.sum())
                better = int((n.loc[folds, "mae"] < w.loc[folds, "mae"]).sum())
                per_fold = ";".join(f"f{f}:{(n.loc[f, 'mae'] / w.loc[f, 'mae'] - 1) * 100:+.1f}%" for f in folds)
                rows.append({"base": with_ph, "horizon_minutes": int(horizon), "split": "rolling", "n": int(n_test.sum()), "mae_with_pH": mae_w,
                             "mae_nopH": mae_n, "nopH_mae_change_pct": (mae_n / mae_w - 1) * 100, "dm_stat_nopH_vs_pH": np.nan, "dm_p": np.nan,
                             "folds_nopH_better": f"{better}/{len(folds)} ({per_fold})"})
    return pd.DataFrame(rows)


def _write_once(path: Path, frame_or_obj) -> None:
    if path.exists():
        raise FileExistsError(f"refusing_to_overwrite:{path}")
    if isinstance(frame_or_obj, pd.DataFrame):
        frame_or_obj.to_csv(path, index=False)
    else:
        path.write_text(json.dumps(frame_or_obj, indent=1, default=str), encoding="utf-8")


def report(run_dir: Path, model: str = "ridge") -> dict:
    run_dir = Path(run_dir)
    write_dm_tests(run_dir, loss="abs", kernel="rectangular")
    metrics = pd.read_csv(run_dir / "metrics_per_fold.csv")
    dm = pd.read_csv(run_dir / "dm_tests.csv")
    gate = gate16_summary(metrics, dm, model)
    _write_once(run_dir / "gate16_summary.csv", gate)
    check = lockbox_check(json.loads((run_dir / "fold_label_check.json").read_text(encoding="utf-8")))
    if check["fold_labels_clear_of_lockbox"] is False:
        raise AssertionError("fold_label_in_lockbox")
    _write_once(run_dir / "lockbox_check.json", check)
    predictions = pd.read_parquet(run_dir / "predictions.parquet", columns=["split", "target", "horizon_minutes", "feature_set", "model", "issued_at", "actual", "prediction"])
    for column in ("target", "feature_set", "model", "split"):
        predictions[column] = predictions[column].astype(str)
    feature_sets = set(predictions["feature_set"])
    if any(no_ph in feature_sets for _, no_ph in NOPH_PAIRS):
        _write_once(run_dir / "nopH_vs_withpH_dm.csv", nopH_vs_withpH(predictions, metrics, model))
    pairs = [pair for pair in CONTRIBUTION_PAIRS if set(pair) <= feature_sets]
    if pairs:
        _write_once(run_dir / "paired_dm.csv", paired_dm(predictions, pairs, model))
    return {"gate": gate, "check": check}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--model", default="ridge")
    args = parser.parse_args()
    out = report(args.run_dir, args.model)
    print(out["gate"].to_string(index=False))
    print(json.dumps({k: v for k, v in out["check"].items() if k != "per_target_horizon"}, indent=1))


if __name__ == "__main__":
    main()
