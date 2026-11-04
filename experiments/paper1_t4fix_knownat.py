"""Paper 1 / T4-fix (RL-T4FIX): re-run the T4 NB1 cells with an ingest-latency ``known_at``.

RL-81 used ``known_at = max(valid_at, actual_at)``; the bench writes ``actual_at`` only for rolling folds, so on the
NB1 lockbox ``known_at = valid_at``: an outcome at valid time t fed the ACI state of the origin issued at t itself.
The live pipeline cannot do that.  Amendment ``experiments/paper1_t4fix_amendment.json`` (committed before this
runs) sets ``known_at = max(valid_at, actual_at) + 15 min`` on NB1 and fixes the variants and the comparison.

CDMO (already ``issued_at + h``) and T4c (CDMO only) are not re-run.  No re-forecasting, no torch.

Stages (write-once, in order):
    init      copy the amendment with the git head and its commit time; requires a clean worktree
    evaluate  all variants, comparison table, verdict
    manifest  sha256 of every file in the run dir (after NOTES.md is written)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from core import paths  # noqa: E402
from experiments import paper1_t4_conformal as t4  # noqa: E402

RUN_NAME = "paper1-t4fix-20261104"
PREREG_FILE = Path(__file__).with_name("paper1_t4fix_amendment.json")
RL81_RUN = "paper1-t4-20261102"
PRIMARY_LATENCY = pd.Timedelta(minutes=15)
# name -> (latency, gamma_latency, with_s1)
VARIANTS = {
    "rl81_control_latency_0": (pd.Timedelta(0), None, True),
    "primary_latency_15min": (PRIMARY_LATENCY, None, True),
    "latency_1min": (pd.Timedelta(minutes=1), None, False),
    "latency_60min": (pd.Timedelta(minutes=60), None, False),
    "latency_1440min_daily_collector": (pd.Timedelta(minutes=1440), None, False),
    "latency_15min_gamma_effective_lag": (PRIMARY_LATENCY, PRIMARY_LATENCY, False),
}
PRIMARY_CAND = ("chronos-2-small", "cqr_aci_amp")
PRIMARY_REF = (t4.RIDGE_B5D, "ridge_aci_amp")
BY_CELL = ["horizon_minutes", "regime"]
RL81_CDMO_VERDICT = "fail"  # RL-81 verdict.json; CDMO is not affected by this amendment
CONTROL_TOL = 1e-9


def run_dir() -> Path:
    return paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME


def nb1_known_at(frame: pd.DataFrame, latency=PRIMARY_LATENCY) -> pd.Series:
    """RL-T4FIX rule: ``max(valid_at, actual_at) + latency``; NaT ``actual_at`` (lockbox) falls back to ``valid_at``."""
    return t4.known_at(frame, latency)


def nb1_cells(rows: pd.DataFrame) -> pd.DataFrame:
    """The six H3 cells of T4 (primary scenario, Chronos-small + cqr_aci_amp vs ridge B5D + aci_amp), with CIs."""
    prim = rows[rows["scenario"] == "primary"]
    m = t4.summarise(prim[(prim["model"] == PRIMARY_CAND[0]) & (prim["method"] == PRIMARY_CAND[1])], BY_CELL)
    cells = t4.h3_cells(m, t4.winkler_ratio_cells(prim, PRIMARY_CAND, PRIMARY_REF, BY_CELL), BY_CELL)
    return t4._with_ci(cells, prim, PRIMARY_CAND, PRIMARY_REF, BY_CELL)


def nb1_sensitivity(rows: pd.DataFrame) -> pd.DataFrame:
    """The NB1 sensitivity rows of T4 (same list and names)."""
    prim = rows[rows["scenario"] == "primary"]
    spec = [
        ("nb1_literal_gamma", prim, ("chronos-2-small", "cqr_aci_amp_literal"), (t4.RIDGE_B5D, "ridge_aci_amp_literal")),
        ("nb1_sym", prim, ("chronos-2-small", "sym_aci_amp"), PRIMARY_REF),
        ("nb1_ridge_nopH", prim, PRIMARY_CAND, ("B5_external_as_issued_diurnal_nopH", "ridge_aci_amp")),
        ("nb1_ridge_B4D", prim, PRIMARY_CAND, ("B4_quality_diurnal", "ridge_aci_amp")),
        ("nb1_base_vs_small_ridge", prim, ("chronos-2-base", "cqr_aci_amp"), PRIMARY_REF),
        ("nb1_S1", rows[rows["scenario"] == "S1"], PRIMARY_CAND, PRIMARY_REF),
        ("nb1_ridge_aci_plain_vs_ridge_aci_amp", prim, (t4.RIDGE_B5D, "ridge_aci"), PRIMARY_REF),
        ("nb1_chronos_vs_ridge_aci_plain", prim, PRIMARY_CAND, (t4.RIDGE_B5D, "ridge_aci")),
    ]
    out = []
    for name, part, cand, ref in spec:
        if not len(part):
            continue
        mm = t4.summarise(part[(part["model"] == cand[0]) & (part["method"] == cand[1])], BY_CELL)
        out.append(t4.h3_cells(mm, t4.winkler_ratio_cells(part, cand, ref, BY_CELL), BY_CELL).assign(sensitivity=name))
    return pd.concat(out, ignore_index=True)


def check_control(cells: pd.DataFrame, rl81: pd.DataFrame) -> float:
    """Max abs difference of coverage / frac_infinite / winkler_ratio vs RL-81; raises if not reproduced."""
    a = cells.set_index("horizon_minutes").sort_index()
    b = rl81.set_index("horizon_minutes").sort_index()
    if list(a.index) != list(b.index) or not (a["n"].to_numpy() == b["n"].to_numpy()).all():
        raise SystemExit("control_does_not_reproduce_rl81_rows")
    diff = max(float(np.nanmax(np.abs(a[c].to_numpy(dtype=float) - b[c].to_numpy(dtype=float))))
               for c in ("coverage", "frac_infinite", "winkler_ratio"))
    if diff > CONTROL_TOL or not (a["h3_pass"].to_numpy() == b["h3_pass"].to_numpy()).all():
        raise SystemExit(f"control_does_not_reproduce_rl81: max_diff={diff}")
    return diff


def compare_table(cells_by_variant: dict[str, pd.DataFrame]) -> pd.DataFrame:
    keep = ["horizon_minutes", "regime", "n", "coverage", "coverage_lo", "coverage_hi", "frac_infinite", "mean_width",
            "winkler", "winkler_ratio", "winkler_ratio_lo", "winkler_ratio_hi", "h3a_coverage", "h3b_winkler", "h3_pass"]
    frames = [c[keep].assign(variant=name) for name, c in cells_by_variant.items()]
    out = pd.concat(frames, ignore_index=True)
    ctrl = cells_by_variant["rl81_control_latency_0"].set_index("horizon_minutes")
    out["d_coverage_vs_rl81"] = out["coverage"] - out["horizon_minutes"].map(ctrl["coverage"])
    out["d_winkler_ratio_vs_rl81"] = out["winkler_ratio"] - out["horizon_minutes"].map(ctrl["winkler_ratio"])
    return out[["variant"] + [c for c in out.columns if c != "variant"]]


def verdict_summary(cells_by_variant: dict[str, pd.DataFrame], info: dict) -> dict:
    per = {}
    for name, c in cells_by_variant.items():
        v = t4.verdict_nb1(c, 0)
        per[name] = {"nb1": v, "nb1_cells_pass": f"{int(c['h3_pass'].sum())}/{len(c)}",
                     "h3a_coverage_cells": f"{int(c['h3a_coverage'].sum())}/{len(c)}",
                     "h3b_winkler_cells": f"{int(c['h3b_winkler'].sum())}/{len(c)}",
                     "h3_overall_with_rl81_cdmo": t4.verdict_overall(v, RL81_CDMO_VERDICT), "info": info[name]}
    prim, ctrl = per["primary_latency_15min"], per["rl81_control_latency_0"]
    return {"primary_variant": "primary_latency_15min", "rl81_nb1": ctrl["nb1"], "t4fix_nb1": prim["nb1"],
            "nb1_verdict_changed": prim["nb1"] != ctrl["nb1"],
            "h3_overall_rl81": ctrl["h3_overall_with_rl81_cdmo"], "h3_overall_t4fix": prim["h3_overall_with_rl81_cdmo"],
            "h3_overall_changed": prim["h3_overall_with_rl81_cdmo"] != ctrl["h3_overall_with_rl81_cdmo"],
            "rl85_t4c": "unchanged by construction: CDMO only, known_at = issued_at + h already",
            "variants": per}


def stage_init(_args) -> None:
    root = run_dir()
    root.mkdir(parents=True, exist_ok=False)
    cwd = PREREG_FILE.parent
    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True, cwd=cwd).stdout
    if status.strip():
        raise SystemExit(f"worktree not clean:\n{status}")
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=cwd).stdout.strip()
    committed = subprocess.run(["git", "log", "-1", "--format=%H %cI", "--", PREREG_FILE.name],
                               capture_output=True, text=True, check=True, cwd=cwd).stdout.strip()
    if not committed:
        raise SystemExit("amendment not committed")
    prereg = json.loads(PREREG_FILE.read_text(encoding="utf-8"))
    prereg["git_head"], prereg["source_sha256"] = head, t4._sha256(PREREG_FILE)
    prereg["amendment_commit"] = dict(zip(("sha", "committed_at"), committed.split(" ", 1)))
    t4._write_json(root / "preregistration.json", prereg)
    print(f"wrote {root / 'preregistration.json'} at {head}")


def stage_evaluate(_args) -> None:
    root = run_dir()
    if (root / "verdict.json").exists():
        raise FileExistsError(f"refusing_to_overwrite:{root}")
    stored = json.loads((root / "preregistration.json").read_text(encoding="utf-8"))
    if stored["source_sha256"] != t4._sha256(PREREG_FILE):
        raise SystemExit("amendment changed after init")
    rl81 = pd.read_csv(paths.EXPERIMENT_OUTPUT_DIR / RL81_RUN / "h3_cells_nb1.csv")
    cells, sens, info, primary_rows = {}, [], {}, None
    for name, (latency, gamma_latency, with_s1) in VARIANTS.items():
        res = t4.evaluate_nb1(root, latency=latency, gamma_latency=gamma_latency, with_s1=with_s1)
        rows = res["rows"]
        cells[name] = nb1_cells(rows)
        sens.append(nb1_sensitivity(rows).assign(variant=name))
        info[name] = {"latency_minutes": latency.total_seconds() / 60,
                      "gamma_latency_minutes": None if gamma_latency is None else gamma_latency.total_seconds() / 60,
                      **{m: {k: res["info"][m][k] for k in ("n_cal", "rows_dropped_known_after_lockbox_start", "floor")}
                         for m in ("chronos-2-small", "chronos-2-base")},
                      "S1": res["info"].get("S1")}
        if name == "rl81_control_latency_0":
            info[name]["max_abs_diff_vs_rl81_cells"] = check_control(cells[name], rl81)
        if name == "primary_latency_15min":
            primary_rows = rows
        print(name, f"{int(cells[name]['h3_pass'].sum())}/6", flush=True)
    t4._write_csv(root / "compare_cells.csv", compare_table(cells))
    t4._write_csv(root / "sensitivity.csv", pd.concat(sens, ignore_index=True))
    for name, c in cells.items():
        t4._write_csv(root / f"h3_cells_nb1_{name}.csv", c)
    keep = ["station", "issued_at", "horizon_minutes", "y", "amp", "regime", "method", "lower", "upper", "model", "scenario"]
    primary_rows[keep].to_parquet(root / "intervals-nb1-primary.parquet", index=False)
    verdict = verdict_summary(cells, info)
    t4._write_json(root / "verdict.json", verdict)
    print(json.dumps({k: v for k, v in verdict.items() if k != "variants"}, indent=1))


def stage_manifest(_args) -> None:
    root = run_dir()
    files = {p.relative_to(root).as_posix(): t4._sha256(p) for p in sorted(root.rglob("*")) if p.is_file() and p.name != "manifest.json"}
    t4._write_json(root / "manifest.json", {"run": RUN_NAME, "sha256": files})
    print(f"manifest: {len(files)} files")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("init", "evaluate", "manifest"))
    args = parser.parse_args()
    {"init": stage_init, "evaluate": stage_evaluate, "manifest": stage_manifest}[args.stage](args)


if __name__ == "__main__":
    main()
