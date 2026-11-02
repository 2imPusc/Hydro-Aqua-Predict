"""Paper 1 / T4c: PI80 for the hybrid ``stack-B5D`` (Chronos-2 none + ridge B5D-fc), from stored forecasts only.

No re-forecasting, no torch.  Inputs (T4b run ``paper1-t4b-20261102``): ``predictions-{dev,conf}.parquet`` (points)
and Chronos-2 small ``none`` quantiles (conf: ``fm-conf/test-<station>.parquet``; dev: T3
``fm-cdmo-chronos-2-small-none.parquet``, the file T4b read for dev test origins).

Interval constructions (all through ``paper1_t4_conformal.methods_for_group``, i.e. the T4 code path):
  * ``abs_*``  conformal on |y - point| of a point model (static, ACI with delayed feedback, aci_amp).
  * ``cqr_*``  CQR on Chronos q10 / q90 shifted to be centred on the point: ``lo = point + (q10 - q50)``,
               ``hi = point + (q90 - q50)``, score ``max(lo - y, y - hi)``, then static / ACI / aci_amp.
Six candidates for the hybrid: stack-B5D x {abs, cqr_shift} x {static, aci, aci_amp}.  Reference for each candidate:
ridge B5D-fc (T3 recipe) + the same update rule on |residual|.  Chronos none + CQR (T4) is descriptive.

Time split inside each station (as T4 CDMO): calibration = rows with ``known_at < 2025-05-01``; evaluation = rows with
``issued_at >= 2025-05-01``; straddlers dropped and counted.  ``known_at = issued_at + horizon`` (the true value of a
forecast is known only at its valid time, never earlier); a matured outcome enters the ACI state only at origins with
``issued_at >= known_at``.  Origins are 00/06/12/18 LST, stride 360 min, gamma = 0.075 / ceil(h / 360) (T4 rule).

Dev selection rule (fixed in this file BEFORE the dev stage was run; see ``select_primary``):
  1. eligible = candidates with coverage in [0.75, 0.85] in >= 15 of the 18 dev cells (3 reserves x 6 horizons);
  2. among eligible, most dev cells passing the full cell rule (coverage band, frac_infinite <= 0.01, n >= 50 and
     Winkler ratio <= 1.00 vs ridge B5D-fc + same rule);
  3. tie -> lowest mean over cells of Winkler(candidate) / Winkler(ridge B5D-fc + abs_static) (common denominator);
  4. tie -> simpler (static < aci < aci_amp; abs < cqr_shift).
If no candidate is eligible, rule 2 is applied to all six.

Stages (each write-once):
    dev       exploratory: all constructions on the 8 T3 stations -> ``<run>/dev/`` + ``dev/selection.json``
    init      copy the tracked pre-registration with git head; requires a clean worktree and ``dev/selection.json``
    conf      score the 12 unseen stations once -> ``<run>/`` verdict, cells, metrics
    manifest  sha256 of every file in the run dir
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import paths  # noqa: E402
from experiments import paper1_t4_conformal as t4  # noqa: E402  (sets thread env to 2)
from experiments import paper1_t4b_hybrid as t4b  # noqa: E402
from experiments.forecast_conformal import AMP_FLOOR_FRAC, GATE_MAX_FRAC_INFINITE, GATE_PI80, trailing_amplitude  # noqa: E402

RUN_NAME = "paper1-t4c-20261102"
PREREG_FILE = Path(__file__).with_name("paper1_t4c_preregistration.json")
ALPHA = t4.ALPHA
HORIZONS = t4.HORIZONS
STRIDE = 360
EVAL_START = pd.Timestamp("2025-05-01")
MIN_COUNT_AMP = t4.CDMO_MIN_COUNT
MIN_CELL_ROWS = t4.MIN_CELL_ROWS
MAX_WINKLER_RATIO = 1.00
ELIGIBLE_MIN_COVERAGE_CELLS = 15
STRICT_KNOWN_OFFSET = pd.Timedelta(minutes=1)

STACK, RIDGE, RIDGE3H, CHRONOS = "stack-B5D", "ridge-B5D-fc", "ridge-B5D-fc-3h", "chronos-none"
STACK_CQR = "stack-B5D-cqr"
RULES = ("static", "aci", "aci_amp")
# candidate -> (model, method, rule)
CANDIDATES = {f"{fam}_{rule}": (STACK if fam == "abs" else STACK_CQR, f"{fam if fam == 'abs' else 'cqr'}_{rule}", rule)
              for fam in ("abs", "cqr_shift") for rule in RULES}
SIMPLICITY = {name: i for i, name in enumerate(
    ["abs_static", "cqr_shift_static", "abs_aci", "cqr_shift_aci", "abs_aci_amp", "cqr_shift_aci_amp"])}
COMMON_DENOMINATOR = (RIDGE, "abs_static")


def run_dir() -> Path:
    return paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME


def t4b_dir() -> Path:
    return paths.EXPERIMENT_OUTPUT_DIR / t4b.RUN_NAME


def reference_of(candidate: str, ridge: str = RIDGE) -> tuple[str, str]:
    return ridge, f"abs_{CANDIDATES[candidate][2]}"


# ------------------------------------------------------------------ pure functions


def shifted_quantiles(point, q10, q50, q90) -> tuple[np.ndarray, np.ndarray]:
    """Chronos q10 / q90 re-centred on ``point`` (keeps Chronos' asymmetric spread)."""
    point = np.asarray(point, dtype=float)
    return point + (np.asarray(q10, dtype=float) - q50), point + (np.asarray(q90, dtype=float) - q50)


def known_at_of(frame: pd.DataFrame) -> pd.Series:
    """The true value of a forecast is observed at its valid time ``issued_at + horizon`` and not earlier."""
    return frame["issued_at"] + pd.to_timedelta(frame["horizon_minutes"], unit="min")


def split_cal_eval(part: pd.DataFrame, start: pd.Timestamp = EVAL_START) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    cal = part[part["known_at"] < start]
    ev = part[part["issued_at"] >= start]
    return cal, ev, int(len(part) - len(cal) - len(ev))


def _rename(intervals: dict, mapping: dict[str, str]) -> dict:
    return {mapping[k]: v for k, v in intervals.items() if k in mapping}


POINT_MAP = {"ridge_static": "abs_static", "ridge_aci": "abs_aci", "ridge_aci_amp": "abs_aci_amp",
             "ridge_aci_amp_literal": "abs_aci_amp_literal"}
QUANT_MAP = {"raw": "raw", "cqr_static": "cqr_static", "cqr_aci": "cqr_aci", "cqr_aci_amp": "cqr_aci_amp",
             "cqr_aci_amp_literal": "cqr_aci_amp_literal"}


def intervals_for_group(cal: pd.DataFrame, ev: pd.DataFrame, floor: float, horizon: int) -> list[tuple[str, dict]]:
    """All constructions for one (station, horizon).  Frames hold y, amp, issued_at, known_at, the point columns
    and q10 / q50 / q90."""
    out = []
    for model in (STACK, RIDGE, RIDGE3H):
        c, e = cal.assign(point=cal[model]), ev.assign(point=ev[model])
        out.append((model, _rename(t4.methods_for_group(c, e, floor, horizon, STRIDE, "point"), POINT_MAP)))
    def shifted(frame):
        lo, hi = shifted_quantiles(frame[STACK], frame["q10"], frame["q50"], frame["q90"])
        return frame.assign(lo=lo, hi=hi, point=frame[STACK])
    out.append((STACK_CQR, _rename(t4.methods_for_group(shifted(cal), shifted(ev), floor, horizon, STRIDE, "quantile"), QUANT_MAP)))
    c = cal.assign(lo=cal["q10"], hi=cal["q90"], point=cal["q50"])
    e = ev.assign(lo=ev["q10"], hi=ev["q90"], point=ev["q50"])
    out.append((CHRONOS, _rename(t4.methods_for_group(c, e, floor, horizon, STRIDE, "quantile"), QUANT_MAP)))
    return out


def cells(metrics: pd.DataFrame, ratios: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    lo, hi = GATE_PI80
    out = metrics.merge(ratios, on=by, how="left")
    enough = out["n"] >= MIN_CELL_ROWS
    out["cell_coverage"] = enough & out["coverage"].between(lo, hi) & (out["frac_infinite"] <= GATE_MAX_FRAC_INFINITE)
    out["cell_winkler"] = enough & (out["winkler_ratio"] <= MAX_WINKLER_RATIO)
    out["cell_pass"] = out["cell_coverage"] & out["cell_winkler"]
    return out


def candidate_table(rows: pd.DataFrame, by: list[str], ridge: str = RIDGE) -> pd.DataFrame:
    frames = []
    for name, (model, method, _rule) in CANDIDATES.items():
        sel = rows[(rows["model"] == model) & (rows["method"] == method)]
        m = t4.summarise(sel, by)
        r = t4.winkler_ratio_cells(rows, (model, method), reference_of(name, ridge), by)
        common = t4.winkler_ratio_cells(rows, (model, method), COMMON_DENOMINATOR, by)[by + ["winkler_ratio"]]
        c = cells(m, r, by).merge(common.rename(columns={"winkler_ratio": "winkler_ratio_common"}), on=by, how="left")
        frames.append(c.assign(candidate=name, model=model, method=method))
    return pd.concat(frames, ignore_index=True)


def select_primary(table: pd.DataFrame) -> dict:
    """Apply the dev selection rule (module docstring) to a candidate x cell table."""
    stats = table.groupby("candidate").agg(
        n_cells=("cell_pass", "size"), coverage_cells=("cell_coverage", "sum"), pass_cells=("cell_pass", "sum"),
        mean_ratio_common=("winkler_ratio_common", "mean")).reset_index()
    stats["eligible"] = stats["coverage_cells"] >= ELIGIBLE_MIN_COVERAGE_CELLS
    pool = stats[stats["eligible"]] if stats["eligible"].any() else stats
    pool = pool.assign(simplicity=pool["candidate"].map(SIMPLICITY))
    pool = pool.sort_values(["pass_cells", "mean_ratio_common", "simplicity"], ascending=[False, True, True])
    return {"selected": str(pool.iloc[0]["candidate"]), "any_eligible": bool(stats["eligible"].any()),
            "table": stats.to_dict(orient="records")}


def reserve_verdict(cell_table: pd.DataFrame, column: str = "cell_pass", n_horizons: int = len(HORIZONS)) -> dict[str, bool]:
    return {g: bool(len(p) == n_horizons and p[column].all()) for g, p in cell_table.groupby("group")}


def overall_verdict(per_reserve: dict[str, bool], n_reserves: int = 3) -> str:
    k = sum(per_reserve.values())
    if len(per_reserve) != n_reserves:
        return "rejected"
    return "supported" if k == n_reserves else "partially_supported" if k == n_reserves - 1 else "rejected"


# ------------------------------------------------------------------ data


def amp_series(which: str, station: str) -> pd.Series:
    if which == "conf":
        path = t4b_dir() / "data-conf" / f"{station}.parquet"
    else:
        path = paths.EXPERIMENT_OUTPUT_DIR / "paper1-t3-20261029" / "data-cdmo" / f"{station}.parquet"
    data = pd.read_parquet(path, columns=["time_lst", "Temp"])
    return pd.Series(data["Temp"].to_numpy(), index=pd.DatetimeIndex(data["time_lst"])).dropna().sort_index()


def load_chronos(which: str) -> pd.DataFrame:
    cols = ["station", "issued_at", "horizon_minutes", "q10", "q50", "q90"]
    if which == "dev":
        return pd.read_parquet(paths.EXPERIMENT_OUTPUT_DIR / "paper1-t3-20261029" / "fm-cdmo-chronos-2-small-none.parquet", columns=cols)
    files = sorted((t4b_dir() / "fm-conf").glob("test-*.parquet"))
    return pd.concat([pd.read_parquet(f, columns=cols) for f in files], ignore_index=True)


def load_frame(which: str) -> tuple[pd.DataFrame, dict]:
    keys = ["station", "issued_at", "horizon_minutes"]
    pred = pd.read_parquet(t4b_dir() / f"predictions-{which}.parquet",
                           columns=keys + ["actual", "none", STACK, RIDGE, RIDGE3H])
    fm = load_chronos(which)
    frame = pred.merge(fm, on=keys, how="left", validate="one_to_one")
    n_all = len(frame)
    frame = frame[frame["actual"].notna()].copy()
    need = [STACK, RIDGE, RIDGE3H, "q10", "q50", "q90"]
    if frame[need].isna().any().any():
        raise ValueError(f"missing_inputs:{frame[need].isna().sum().to_dict()}")
    if not np.allclose(frame["none"], frame["q50"], atol=1e-4):
        raise ValueError("chronos_q50_does_not_match_t4b_none")
    frame["y"] = frame["actual"]
    frame["known_at"] = known_at_of(frame)
    frame["group"] = frame["station"].map(t4b.reserve_of)
    return frame, {"rows_in": n_all, "actual_nan_dropped": int(n_all - len(frame)), "rows": len(frame)}


def build_rows(which: str, frame: pd.DataFrame, known_offset: pd.Timedelta = pd.Timedelta(0),
               models: tuple[str, ...] | None = None) -> tuple[pd.DataFrame, dict]:
    rows, info = [], {}
    for station, part in frame.groupby("station", sort=True):
        part = part.copy()
        part["known_at"] = part["known_at"] + known_offset
        part["amp"] = trailing_amplitude(amp_series(which, station), part["issued_at"], "24h", "range", MIN_COUNT_AMP)
        cal_all, ev_all, straddle = split_cal_eval(part)
        floor = AMP_FLOOR_FRAC * float(np.nanmedian(cal_all["amp"]))
        info[station] = {"group": part["group"].iloc[0], "floor": floor, "n_cal": len(cal_all), "n_eval": len(ev_all),
                         "dropped_straddling_eval_start": straddle, "eval_amp_nan": int(ev_all["amp"].isna().sum())}
        for h in HORIZONS:
            cal, ev = cal_all[cal_all["horizon_minutes"] == h], ev_all[ev_all["horizon_minutes"] == h]
            ev_sorted = ev.sort_values("issued_at", kind="stable")
            for model, intervals in intervals_for_group(cal, ev, floor, h):
                if models is not None and model not in models:
                    continue
                rows.append(t4.score_rows(ev_sorted, intervals, {"model": model}))
    out = t4.add_outcomes(pd.concat(rows, ignore_index=True))
    out["group"] = out["station"].map(t4b.reserve_of)
    out["local_day"] = out["issued_at"].dt.date.astype(str)
    out["zero_width"] = out["finite"] & (out["width"] <= 0)
    return out, info


def metrics_tables(rows: pd.DataFrame) -> dict[str, pd.DataFrame]:
    by_g = ["model", "method", "group", "horizon_minutes"]
    m_group = t4.summarise(rows, by_g).merge(
        rows.groupby(by_g)["zero_width"].mean().rename("frac_zero_width").reset_index(), on=by_g)
    m_station = t4.summarise(rows, ["model", "method", "group", "station", "horizon_minutes"])
    equal = m_group.groupby(["model", "method", "horizon_minutes"])[["coverage", "frac_infinite", "mean_width", "winkler"]].mean().reset_index()
    return {"metrics_reserve": m_group, "metrics_station": m_station, "metrics_equal_reserve": equal}


def comparisons(rows: pd.DataFrame) -> pd.DataFrame:
    """Descriptive Winkler ratios for every model x method vs every ridge B5D-fc method, per reserve x horizon."""
    by = ["group", "horizon_minutes"]
    pairs = [((m, meth), (RIDGE, ref)) for (m, meth) in rows[["model", "method"]].drop_duplicates().itertuples(index=False)
             for ref in ("abs_static", "abs_aci", "abs_aci_amp") if (m, meth) != (RIDGE, ref)]
    out = []
    for cand, ref in pairs:
        r = t4.winkler_ratio_cells(rows, cand, ref, by)
        out.append(r.assign(model=cand[0], method=cand[1], ref_model=ref[0], ref_method=ref[1]))
    return pd.concat(out, ignore_index=True)


def with_ci(table: pd.DataFrame, rows: pd.DataFrame, cand: tuple[str, str], ref: tuple[str, str]) -> pd.DataFrame:
    by = ["group", "horizon_minutes"]
    return t4._with_ci(table, rows, cand, ref, by)


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    if path.exists():
        raise FileExistsError(f"refusing_to_overwrite:{path}")
    frame.to_parquet(path, index=False)


KEEP = ["station", "group", "issued_at", "horizon_minutes", "y", "amp", "model", "method", "lower", "upper"]


# ------------------------------------------------------------------ stages


def stage_dev(_args) -> None:
    out = run_dir() / "dev"
    out.mkdir(parents=True, exist_ok=False)
    frame, load_info = load_frame("dev")
    rows, info = build_rows("dev", frame)
    by = ["group", "horizon_minutes"]
    table = candidate_table(rows, by)
    selection = select_primary(table)
    for name, f in metrics_tables(rows).items():
        t4._write_csv(out / f"{name}.csv", f)
    t4._write_csv(out / "candidate_cells.csv", table)
    t4._write_csv(out / "candidate_cells_vs_ridge3h.csv", candidate_table(rows, by, RIDGE3H))
    t4._write_csv(out / "comparisons.csv", comparisons(rows))
    _write_parquet(out / "intervals-dev.parquet", rows[KEEP])
    t4._write_json(out / "selection.json", {"set": "dev", "exploratory": True, "rule": __doc__.split("Dev selection rule")[1].split("Stages")[0].strip(),
                                            **selection, "load": load_info, "stations": info})
    print(json.dumps({k: v for k, v in selection.items()}, indent=1, default=str))


def stage_init(_args) -> None:
    root = run_dir()
    if (root / "preregistration.json").exists():
        raise FileExistsError("preregistration_already_initialised")
    if not (root / "dev" / "selection.json").exists():
        raise SystemExit("run the dev stage first")
    if (root / "verdict.json").exists():
        raise SystemExit("conf already scored")
    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True, cwd=PREREG_FILE.parent).stdout
    if status.strip():
        raise SystemExit(f"worktree not clean:\n{status}")
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=PREREG_FILE.parent).stdout.strip()
    prereg = json.loads(PREREG_FILE.read_text(encoding="utf-8"))
    selected = json.loads((root / "dev" / "selection.json").read_text(encoding="utf-8"))["selected"]
    if prereg["primary_method"] != selected:
        raise SystemExit(f"preregistered primary {prereg['primary_method']} != dev selection {selected}")
    prereg["git_head"], prereg["source_sha256"] = head, t4._sha256(PREREG_FILE)
    prereg["initialised_at_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
    t4._write_json(root / "preregistration.json", prereg)
    print(f"wrote {root / 'preregistration.json'} at {head}")


def stage_conf(_args) -> None:
    root = run_dir()
    if (root / "verdict.json").exists():
        raise FileExistsError(f"refusing_to_overwrite:{root}")
    stored = json.loads((root / "preregistration.json").read_text(encoding="utf-8"))
    if stored["source_sha256"] != t4._sha256(PREREG_FILE):
        raise SystemExit("preregistration changed after init")
    primary = stored["primary_method"]
    cand, ref = CANDIDATES[primary][:2], reference_of(primary)
    frame, load_info = load_frame("conf")
    rows, info = build_rows("conf", frame)
    by = ["group", "horizon_minutes"]
    table = candidate_table(rows, by)
    prim = with_ci(table[table["candidate"] == primary].reset_index(drop=True), rows, cand, ref)
    per_reserve = reserve_verdict(prim)
    verdict = {
        "primary_method": primary, "reference": list(ref),
        "verdict": overall_verdict(per_reserve),
        "reserves_passing_all_cells": per_reserve,
        "cells_pass": f"{int(prim['cell_pass'].sum())}/{len(prim)}",
        "coverage_only": {"reserves": reserve_verdict(prim, "cell_coverage"), "verdict": overall_verdict(reserve_verdict(prim, "cell_coverage")),
                          "cells": f"{int(prim['cell_coverage'].sum())}/{len(prim)}"},
        "winkler_only": {"reserves": reserve_verdict(prim, "cell_winkler"), "verdict": overall_verdict(reserve_verdict(prim, "cell_winkler")),
                         "cells": f"{int(prim['cell_winkler'].sum())}/{len(prim)}"},
        "load": load_info, "stations": info,
    }
    # secondary (not part of the verdict)
    sens = []
    t = candidate_table(rows, by, RIDGE3H)
    sens.append(t[t["candidate"] == primary].assign(sensitivity="reference_ridge_3h"))
    for name in CANDIDATES:
        if name != primary:
            sens.append(table[table["candidate"] == name].assign(sensitivity=f"other_candidate:{name}"))
    if CANDIDATES[primary][2] == "aci_amp":
        lit = (cand[0], cand[1] + "_literal")
        m = t4.summarise(rows[(rows["model"] == lit[0]) & (rows["method"] == lit[1])], by)
        sens.append(cells(m, t4.winkler_ratio_cells(rows, lit, (RIDGE, "abs_aci_amp_literal"), by), by).assign(sensitivity="literal_gamma"))
    strict, _ = build_rows("conf", frame, STRICT_KNOWN_OFFSET, models=(cand[0], RIDGE))
    m = t4.summarise(strict[(strict["model"] == cand[0]) & (strict["method"] == cand[1])], by)
    sens.append(cells(m, t4.winkler_ratio_cells(strict, cand, ref, by), by).assign(sensitivity="known_at_plus_1min"))
    m = t4.summarise(rows[(rows["model"] == CHRONOS) & (rows["method"] == "cqr_aci_amp")], by)
    sens.append(cells(m, t4.winkler_ratio_cells(rows, (CHRONOS, "cqr_aci_amp"), (RIDGE, "abs_aci_amp"), by), by).assign(sensitivity="chronos_cqr_aci_amp_vs_ridge_aci_amp_T4"))
    sens = pd.concat(sens, ignore_index=True)
    verdict["secondary"] = {s: f"{int(g['cell_pass'].sum())}/{len(g)}" for s, g in sens.groupby("sensitivity")}
    sel = rows[(rows["model"] == cand[0]) & (rows["method"] == cand[1])]
    week = pd.to_datetime(sel["issued_at"]).dt.strftime("%G-W%V")
    weekly, worst = t4.period_coverage(sel, week, ["group", "horizon_minutes"], t4.MIN_ROWS_WEEK_CDMO, "iso_week")
    for name, f in metrics_tables(rows).items():
        t4._write_csv(root / f"{name}.csv", f)
    t4._write_csv(root / "cells_primary.csv", prim)
    t4._write_csv(root / "candidate_cells.csv", table)
    t4._write_csv(root / "sensitivity.csv", sens)
    t4._write_csv(root / "comparisons.csv", comparisons(rows))
    t4._write_csv(root / "weekly_primary.csv", weekly)
    t4._write_csv(root / "worst_week_primary.csv", worst)
    _write_parquet(root / "intervals-conf.parquet", rows[KEEP])
    t4._write_json(root / "verdict.json", verdict)
    print(json.dumps({k: v for k, v in verdict.items() if k not in ("stations", "load")}, indent=1, default=str))


def stage_manifest(_args) -> None:
    root = run_dir()
    files = {p.relative_to(root).as_posix(): t4._sha256(p) for p in sorted(root.rglob("*")) if p.is_file() and p.name != "manifest.json"}
    t4._write_json(root / "manifest.json", {"run": RUN_NAME, "sha256": files})
    print(f"manifest: {len(files)} files")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("dev", "init", "conf", "manifest"))
    args = parser.parse_args()
    {"dev": stage_dev, "init": stage_init, "conf": stage_conf, "manifest": stage_manifest}[args.stage](args)


if __name__ == "__main__":
    main()
