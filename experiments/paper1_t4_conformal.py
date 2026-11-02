"""Paper 1 / T4: conformalise stored Chronos-2 quantiles (PI80) by amplitude regime.

No re-forecasting and no torch: reads T1 / T3 parquet files and the H1 bench.  Pre-registered in
``experiments/paper1_t4_preregistration.json`` (committed before any coverage was computed).

Stages (run in order, each write-once):
    init      copy the pre-registration to the run dir with the git head; requires a clean worktree
    evaluate  all methods, metrics, verdict
    manifest  sha256 of every file in the run dir (after NOTES.md is written)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "ARROW_NUM_THREADS"):
    os.environ[_var] = "2"

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import paths  # noqa: E402
from core.forecast_intervals import aci_amp_half_width  # noqa: E402
from experiments.forecast_conformal import (  # noqa: E402
    AMP_FLOOR_FRAC,
    GATE_MAX_FRAC_INFINITE,
    GATE_PI80,
    MIN_ROWS_PER_DAY,
    aci_intervals,
    calibration_residuals,
    conformal_quantile,
    known_at,
    trailing_amplitude,
)

RUN_NAME = "paper1-t4-20261102"
PREREG_FILE = Path(__file__).with_name("paper1_t4_preregistration.json")
ALPHA = 0.2
HORIZONS = (15, 30, 60, 180, 360, 720)
MAX_WINKLER_RATIO = 1.05
MIN_CELL_ROWS = 50
STEP_PER_LAG = 0.005 * 15  # RL-19: gamma x feedback lag at one origin per minute
STRIDE_NB1 = 15
STRIDE_CDMO = 360
NB1_K_FOLDS = 3
NB1_LARGE_FROM = pd.Timestamp("2026-08-20", tz="UTC")
NB1_MIN_COUNT = 720
NB1_TZ = "Asia/Ho_Chi_Minh"
RIDGE_B5D = "B5_external_as_issued_diurnal"
RIDGE_NB1 = (RIDGE_B5D, "B5_external_as_issued_diurnal_nopH", "B4_quality_diurnal")
CDMO_STATIONS = ("rkbfbwq", "rkbfuwq", "rkblhwq", "rkbmbwq", "gtmfmwq", "gtmpiwq", "gtmsswq", "marscwq")
CDMO_RIDGE = ("ridge-B5D-fc", "ridge-B4D-n")
CDMO_EVAL_START = pd.Timestamp("2025-05-01")
CDMO_TRAIN = ("2024-02-01", "2025-01-31")
CDMO_MIN_COUNT = 48
MIN_ROWS_DAY_CDMO = 4
MIN_ROWS_WEEK_CDMO = 20
N_BOOT = 1000


def run_dir() -> Path:
    return paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, obj) -> None:
    with open(path, "x", encoding="utf-8") as fh:  # "x": refuse to overwrite
        json.dump(obj, fh, indent=1, ensure_ascii=False, default=str)


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    with open(path, "x", encoding="utf-8", newline="") as fh:
        frame.to_csv(fh, index=False)


# ------------------------------------------------------------------ pure functions


def feedback_lag(horizon: int, stride: int) -> int:
    """Origins between issuing a forecast and being able to use its outcome."""
    return max(1, math.ceil(horizon / stride))


def gamma_primary(horizon: int, stride: int) -> float:
    return STEP_PER_LAG / feedback_lag(horizon, stride)


def gamma_literal(horizon: int) -> float:
    return STEP_PER_LAG / horizon


def cqr_score(y, lo, hi) -> np.ndarray:
    return np.maximum(np.asarray(lo, dtype=float) - y, np.asarray(y, dtype=float) - hi)


def interval_from_q(lo, hi, q) -> tuple[np.ndarray, np.ndarray]:
    """``[lo - q, hi + q]``; a negative ``q`` that crosses collapses to the midpoint."""
    lo, hi, q = np.asarray(lo, dtype=float), np.asarray(hi, dtype=float), np.asarray(q, dtype=float)
    lower, upper = lo - q, hi + q
    crossed = lower > upper
    mid = (lo + hi) / 2.0
    return np.where(crossed, mid, lower), np.where(crossed, mid, upper)


def winkler_interval(y, lower, upper, alpha: float = ALPHA) -> np.ndarray:
    y, lower, upper = np.asarray(y, dtype=float), np.asarray(lower, dtype=float), np.asarray(upper, dtype=float)
    return (upper - lower) + (2.0 / alpha) * (np.maximum(0.0, lower - y) + np.maximum(0.0, y - upper))


def aci_amp_path(cal_norm, issued, known, score, amp, floor: float, alpha: float, gamma: float) -> np.ndarray:
    """Half-widths from ``core.forecast_intervals.aci_amp_half_width``, one origin at a time.

    Rows sorted by ``issued``.  Only outcomes with ``known <= issued[i]`` of already-issued origins
    enter the state, so no later outcome can reach interval ``i``.
    """
    issued = pd.DatetimeIndex(issued).asi8
    known = pd.DatetimeIndex(known).asi8
    if len(issued) and np.any(np.diff(issued) < 0):
        raise ValueError("issued_not_sorted")
    if np.any(known < issued):
        raise ValueError("outcome_known_before_issue")
    score = np.asarray(score, dtype=float)
    amp = np.asarray(amp, dtype=float)
    order = np.argsort(known, kind="stable")
    q = np.empty(len(issued))
    matured: list[tuple[float, float, float]] = []
    j = 0
    for i in range(len(issued)):
        while j < len(order) and order[j] < i and known[order[j]] <= issued[i]:
            s = order[j]
            matured.append((float(score[s]), float(amp[s]), float(q[s])))
            j += 1
        q[i] = aci_amp_half_width(cal_norm, matured, float(amp[i]), alpha, gamma, floor)["q"]
    return q


def methods_for_group(cal: pd.DataFrame, block: pd.DataFrame, floor: float, horizon: int, stride: int,
                      kind: str, alpha: float = ALPHA) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Intervals for one (model, station, horizon).  ``kind`` is ``quantile`` or ``point``.

    Frames hold ``y``, ``amp``, ``issued_at``, ``known_at`` and either ``lo``/``hi``/``point`` or ``point``.
    """
    block = block.sort_values("issued_at", kind="stable")
    y, y_cal = block["y"].to_numpy(), cal["y"].to_numpy()
    issued, kn = block["issued_at"].to_numpy(), block["known_at"].to_numpy()
    amp = block["amp"].to_numpy()
    gamma, literal = gamma_primary(horizon, stride), gamma_literal(horizon)
    ok_cal = np.isfinite(cal["amp"].to_numpy())
    cal_scale = np.maximum(cal["amp"].to_numpy()[ok_cal], floor)

    def aci_amp(score, score_cal, g):
        return aci_amp_path(score_cal[ok_cal] / cal_scale, issued, kn, score, amp, floor, alpha, g)

    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    point = block["point"].to_numpy()
    if kind == "quantile":
        lo, hi = block["lo"].to_numpy(), block["hi"].to_numpy()
        s, s_cal = cqr_score(y, lo, hi), cqr_score(y_cal, cal["lo"].to_numpy(), cal["hi"].to_numpy())
        out["raw"] = (lo, hi)
        out["cqr_static"] = interval_from_q(lo, hi, np.full(len(y), conformal_quantile(s_cal, alpha)))
        out["cqr_aci"] = interval_from_q(lo, hi, aci_intervals(s_cal, issued, kn, s, alpha, gamma)[0])
        out["cqr_aci_amp"] = interval_from_q(lo, hi, aci_amp(s, s_cal, gamma))
        out["cqr_aci_amp_literal"] = interval_from_q(lo, hi, aci_amp(s, s_cal, literal))
        r, r_cal = np.abs(y - point), np.abs(y_cal - cal["point"].to_numpy())
        out["sym_aci_amp"] = interval_from_q(point, point, aci_amp(r, r_cal, gamma))
    elif kind == "point":
        r, r_cal = np.abs(y - point), np.abs(y_cal - cal["point"].to_numpy())
        out["ridge_static"] = interval_from_q(point, point, np.full(len(y), conformal_quantile(r_cal, alpha)))
        out["ridge_aci"] = interval_from_q(point, point, aci_intervals(r_cal, issued, kn, r, alpha, gamma)[0])
        out["ridge_aci_amp"] = interval_from_q(point, point, aci_amp(r, r_cal, gamma))
        out["ridge_aci_amp_literal"] = interval_from_q(point, point, aci_amp(r, r_cal, literal))
    else:
        raise ValueError(f"unknown_kind:{kind}")
    return out


def score_rows(block: pd.DataFrame, intervals: dict, ident: dict) -> pd.DataFrame:
    block = block.sort_values("issued_at", kind="stable")
    keep = [c for c in ("station", "issued_at", "horizon_minutes", "y", "amp", "regime") if c in block]
    frames = []
    for method, (lower, upper) in intervals.items():
        f = block[keep].copy()
        f["method"], f["lower"], f["upper"] = method, lower, upper
        for k, v in ident.items():
            f[k] = v
        frames.append(f)
    return pd.concat(frames, ignore_index=True)


def add_outcomes(rows: pd.DataFrame, alpha: float = ALPHA) -> pd.DataFrame:
    rows = rows.copy()
    rows["covered"] = (rows["y"] >= rows["lower"]) & (rows["y"] <= rows["upper"])
    rows["finite"] = np.isfinite(rows["lower"]) & np.isfinite(rows["upper"])
    width = (rows["upper"] - rows["lower"]).where(rows["finite"])
    rows["width"] = width
    w = pd.Series(np.nan, index=rows.index)
    f = rows["finite"].to_numpy()
    w[f] = winkler_interval(rows["y"].to_numpy()[f], rows["lower"].to_numpy()[f], rows["upper"].to_numpy()[f], alpha)
    rows["winkler"] = w
    return rows


def summarise(rows: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    grouped = rows.groupby(by, observed=True, sort=True)
    out = grouped.agg(
        n=("covered", "size"),
        coverage=("covered", "mean"),
        frac_infinite=("finite", lambda s: 1.0 - float(s.mean())),
        mean_width=("width", "mean"),
        median_width=("width", "median"),
        winkler=("winkler", "mean"),
    )
    return out.reset_index()


def winkler_ratio_cells(rows: pd.DataFrame, cand: tuple[str, str], ref: tuple[str, str], by: list[str]) -> pd.DataFrame:
    """Mean-Winkler ratio on rows present and finite for both ``(model, method)`` pairs."""
    key = ["issued_at", "horizon_minutes"] + (["station"] if "station" in rows else [])
    pick = lambda pair: rows[(rows["model"] == pair[0]) & (rows["method"] == pair[1]) & rows["finite"]]  # noqa: E731
    extra = [c for c in by if c not in key]
    merged = pick(cand)[key + extra + ["winkler"]].merge(pick(ref)[key + ["winkler"]], on=key, suffixes=("_cand", "_ref"))
    out = merged.groupby(by, observed=True).agg(
        n_paired=("winkler_cand", "size"), winkler_cand=("winkler_cand", "mean"), winkler_ref=("winkler_ref", "mean"))
    out["winkler_ratio"] = out["winkler_cand"] / out["winkler_ref"]
    return out.reset_index()


def h3_cells(metrics: pd.DataFrame, ratios: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    lo, hi = GATE_PI80
    cells = metrics.merge(ratios, on=by, how="left")
    enough = cells["n"] >= MIN_CELL_ROWS
    cells["h3a_coverage"] = enough & cells["coverage"].between(lo, hi) & (cells["frac_infinite"] <= GATE_MAX_FRAC_INFINITE)
    cells["h3b_winkler"] = enough & (cells["winkler_ratio"] <= MAX_WINKLER_RATIO)
    cells["h3_pass"] = cells["h3a_coverage"] & cells["h3b_winkler"]
    return cells


def verdict_nb1(cells: pd.DataFrame, small_regime_rows: int, column: str = "h3_pass") -> str:
    if len(cells) == 0 or not cells[column].all():
        return "fail"
    return "pass" if small_regime_rows else "not_fully_testable_large_only_pass"


def verdict_cdmo(cells: pd.DataFrame, expected_cells: int = 36, column: str = "h3_pass") -> str:
    return "pass" if len(cells) == expected_cells and bool(cells[column].all()) else "fail"


def verdict_overall(nb1: str, cdmo: str) -> str:
    if nb1 == "fail" or cdmo == "fail":
        return "rejected"
    return "supported" if nb1 == "pass" else "partially_supported"


def block_boot(day, num, den=None, n_boot: int = N_BOOT, seed: int = 0) -> tuple[float, float]:
    """95 % day-block CI of ``sum(num) / len`` or, with ``den``, of ``sum(num) / sum(den)``."""
    frame = pd.DataFrame({"d": day, "n": np.asarray(num, dtype=float), "m": np.ones(len(day)) if den is None else np.asarray(den, dtype=float)})
    daily = frame.groupby("d")[["n", "m"]].sum().to_numpy()
    if not len(daily):
        return math.nan, math.nan
    draw = np.random.default_rng(seed).integers(0, len(daily), (n_boot, len(daily)))
    stats = daily[draw, 0].sum(axis=1) / daily[draw, 1].sum(axis=1)
    return float(np.quantile(stats, 0.025)), float(np.quantile(stats, 0.975))


def period_coverage(rows: pd.DataFrame, period: pd.Series, by: list[str], min_rows: int, label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    grouped = rows.assign(period=period).groupby(by + ["period"], observed=True)["covered"].agg(["mean", "size"])
    full = grouped.rename(columns={"mean": "coverage", "size": "n"}).reset_index()
    full["period_type"] = label
    usable = full[full["n"] >= min_rows]
    worst = usable.groupby(by, observed=True).agg(
        n_periods=("coverage", "size"), worst=("coverage", "min"), best=("coverage", "max"),
        frac_periods_in_band=("coverage", lambda s: float(s.between(*GATE_PI80).mean()))).reset_index()
    worst["period_type"] = label
    return full, worst


def regime_by_median(amp, threshold: float) -> np.ndarray:
    return np.where(np.isnan(amp), "unknown", np.where(np.asarray(amp) < threshold, "small", "large"))


# ------------------------------------------------------------------ data


def _load_bench_nb1(origins: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.Series, Path]:
    path = paths.EXPERIMENT_OUTPUT_DIR / "forecast-h1-diurnal-20261025" / "bench-Temperature" / "predictions.parquet"
    dataset = ds.dataset(path)
    columns = ["feature_set", "horizon_minutes", "issued_at", "valid_at", "actual_at", "actual", "prediction", "split", "fold"]
    arrow_origins = pa.array(origins.tz_convert("UTC"), type=dataset.schema.field("issued_at").type)
    ridge = dataset.to_table(columns=columns, filter=(
        (ds.field("model") == "ridge") & ds.field("feature_set").isin(list(RIDGE_NB1)) & ds.field("issued_at").isin(arrow_origins)
    )).to_pandas()
    ridge["feature_set"] = ridge["feature_set"].astype(str)
    pers = dataset.to_table(columns=["issued_at", "prediction"], filter=(
        (ds.field("model") == "persistence") & (ds.field("feature_set") == RIDGE_B5D) & (ds.field("horizon_minutes") == 15)
    )).to_pandas()
    series = pd.Series(pers["prediction"].to_numpy(), index=pd.DatetimeIndex(pers["issued_at"])).sort_index()
    series = series[np.isfinite(series.to_numpy())]
    return ridge, series[~series.index.duplicated()], path


def _nb1_frame(fm: pd.DataFrame, ridge_b5d: pd.DataFrame, series: pd.Series) -> pd.DataFrame:
    keys = ["issued_at", "horizon_minutes"]
    if fm.duplicated(keys).any():
        raise ValueError("duplicate_t1_rows")
    join = ridge_b5d[keys + ["valid_at", "actual_at", "actual"]].rename(columns={"actual": "actual_bench"})
    frame = fm.merge(join, on=keys, how="left", validate="one_to_one")
    if frame["valid_at"].isna().any() or not np.allclose(frame["actual"], frame["actual_bench"]):
        raise ValueError("t1_bench_join_mismatch")
    frame["split"], frame["known_at"] = frame["split"].astype(str), known_at(frame)
    frame["y"], frame["lo"], frame["hi"], frame["point"] = frame["actual"], frame["q10"], frame["q90"], frame["q50"]
    frame["amp"] = trailing_amplitude(series, frame["issued_at"], "24h", "range", NB1_MIN_COUNT)
    return frame


def _nb1_scenario(frame: pd.DataFrame, ridges: dict[str, pd.DataFrame], cal_rows: pd.DataFrame, block: pd.DataFrame,
                  model: str, floor: float, with_ridge: bool) -> list[pd.DataFrame]:
    out = []
    for h in HORIZONS:
        cal, ev = cal_rows[cal_rows["horizon_minutes"] == h], block[block["horizon_minutes"] == h]
        intervals = methods_for_group(cal, ev, floor, h, STRIDE_NB1, "quantile")
        out.append(score_rows(ev, intervals, {"model": model}))
        if not with_ridge:
            continue
        for name, ridge in ridges.items():
            lookup = ridge[ridge["horizon_minutes"] == h].set_index("issued_at")["prediction"]
            cal_r = cal.assign(point=lookup.reindex(cal["issued_at"]).to_numpy())
            ev_r = ev.assign(point=lookup.reindex(ev["issued_at"]).to_numpy())
            if cal_r["point"].isna().any() or ev_r["point"].isna().any():
                raise ValueError(f"ridge_missing:{name}:{h}")
            out.append(score_rows(ev_r, methods_for_group(cal_r, ev_r, floor, h, STRIDE_NB1, "point"), {"model": name}))
    return out


def evaluate_nb1(root: Path) -> dict:
    t1 = paths.EXPERIMENT_OUTPUT_DIR / "paper1-t1-20261028"
    files = {m: t1 / f"fm-Temperature-{m}-stride15.parquet" for m in ("chronos-2-small", "chronos-2-base")}
    cols = ["split", "fold", "issued_at", "horizon_minutes", "actual", "q10", "q50", "q90"]
    small = pd.read_parquet(files["chronos-2-small"], columns=cols)
    origins = pd.DatetimeIndex(small["issued_at"].unique())
    if origins.min() < NB1_LARGE_FROM:
        raise ValueError("t1_has_origins_before_large_regime_prereg_says_none")
    bench, series, bench_path = _load_bench_nb1(origins)
    ridges = {k: g.copy() for k, g in bench.groupby("feature_set")}
    rows, info = [], {"bench_sha256": _sha256(bench_path), "t1_sha256": {m: _sha256(p) for m, p in files.items()}}
    for model, path in files.items():
        fm = small if model == "chronos-2-small" else pd.read_parquet(path, columns=cols)
        frame = _nb1_frame(fm, ridges[RIDGE_B5D], series)
        lockbox = frame[frame["split"] == "lockbox"]
        rolling = frame[frame["split"] == "rolling"].assign(prediction=lambda d: d["q50"])
        cal, dropped = calibration_residuals(rolling, NB1_K_FOLDS, lockbox["issued_at"].min())
        floor = AMP_FLOOR_FRAC * float(np.nanmedian(cal["amp"]))
        info[model] = {"calibration_folds": sorted(int(f) for f in cal["fold"].unique()), "n_cal": len(cal),
                       "rows_dropped_known_after_lockbox_start": dropped, "floor": floor,
                       "lockbox_amp_nan": int(lockbox["amp"].isna().sum())}
        with_ridge = model == "chronos-2-small"
        rows += [r.assign(scenario="primary") for r in _nb1_scenario(frame, ridges, cal, lockbox, model, floor, with_ridge)]
        if with_ridge:
            ev = rolling[rolling["fold"].isin([3, 4, 5])]
            cal_s1, drop_s1 = calibration_residuals(rolling[rolling["fold"].isin([1, 2])], 2, ev["issued_at"].min())
            floor_s1 = AMP_FLOOR_FRAC * float(np.nanmedian(cal_s1["amp"]))
            info["S1"] = {"n_cal": len(cal_s1), "dropped": drop_s1, "floor": floor_s1}
            rows += [r.assign(scenario="S1") for r in _nb1_scenario(frame, ridges, cal_s1, ev, model, floor_s1, True)]
    out = add_outcomes(pd.concat(rows, ignore_index=True))
    out["regime"] = "large"
    out["station"] = "NB1"
    out["group"] = "NB1"
    out["local_day"] = out["issued_at"].dt.tz_convert(NB1_TZ).dt.date.astype(str)
    return {"rows": out, "info": info}


def _cdmo_amp(root_t3: Path, station: str, origins) -> tuple[np.ndarray, float]:
    data = pd.read_parquet(root_t3 / "data-cdmo" / f"{station}.parquet", columns=["time_lst", "Temp"])
    series = pd.Series(data["Temp"].to_numpy(), index=pd.DatetimeIndex(data["time_lst"])).dropna().sort_index()
    marks = pd.date_range(CDMO_TRAIN[0], CDMO_TRAIN[1], freq="D")
    threshold = float(np.nanmedian(trailing_amplitude(series, marks, "24h", "range", CDMO_MIN_COUNT)))
    return trailing_amplitude(series, origins, "24h", "range", CDMO_MIN_COUNT), threshold


def evaluate_cdmo(root: Path) -> dict:
    t3 = paths.EXPERIMENT_OUTPUT_DIR / "paper1-t3-20261029"
    fm_path, ridge_path = t3 / "fm-cdmo-chronos-2-small-none.parquet", t3 / "ridge-cdmo.parquet"
    fm = pd.read_parquet(fm_path, columns=["station", "issued_at", "horizon_minutes", "q10", "q50", "q90"])
    ridge = pd.read_parquet(ridge_path, columns=["station", "issued_at", "horizon_minutes", "actual", *CDMO_RIDGE])
    keys = ["station", "issued_at", "horizon_minutes"]
    frame = fm.merge(ridge, on=keys, how="inner", validate="one_to_one")
    n_nan = int(frame["actual"].isna().sum())
    frame = frame[frame["actual"].notna()].copy()
    frame["y"], frame["lo"], frame["hi"], frame["point"] = frame["actual"], frame["q10"], frame["q90"], frame["q50"]
    frame["known_at"] = frame["issued_at"] + pd.to_timedelta(frame["horizon_minutes"], unit="min")
    rows, stations_info = [], {}
    for station in CDMO_STATIONS:
        part = frame[frame["station"] == station].copy()
        amp, threshold = _cdmo_amp(t3, station, part["issued_at"])
        part["amp"] = amp
        part["regime"] = regime_by_median(amp, threshold)
        cal_all = part[part["known_at"] < CDMO_EVAL_START]
        ev_all = part[part["issued_at"] >= CDMO_EVAL_START]
        floor = AMP_FLOOR_FRAC * float(np.nanmedian(cal_all["amp"]))
        stations_info[station] = {
            "regime_threshold_train_median": threshold, "floor": floor, "n_cal": len(cal_all), "n_eval": len(ev_all),
            "dropped_straddling_eval_start": int(len(part) - len(cal_all) - len(ev_all)),
            "eval_amp_nan": int(ev_all["amp"].isna().sum()), "eval_frac_large": float((ev_all["regime"] == "large").mean())}
        for h in HORIZONS:
            cal, ev = cal_all[cal_all["horizon_minutes"] == h], ev_all[ev_all["horizon_minutes"] == h]
            rows.append(score_rows(ev, methods_for_group(cal, ev, floor, h, STRIDE_CDMO, "quantile"), {"model": "chronos-2-small"}))
            for name in CDMO_RIDGE:
                c, e = cal.assign(point=cal[name]), ev.assign(point=ev[name])
                rows.append(score_rows(e, methods_for_group(c, e, floor, h, STRIDE_CDMO, "point"), {"model": name}))
    out = add_outcomes(pd.concat(rows, ignore_index=True))
    out["scenario"] = "primary"
    out["group"] = out["station"].str[:3]
    out["local_day"] = out["issued_at"].dt.date.astype(str)
    info = {"fm_sha256": _sha256(fm_path), "ridge_sha256": _sha256(ridge_path), "actual_nan_dropped": n_nan, "stations": stations_info}
    return {"rows": out, "info": info}


# ------------------------------------------------------------------ reports


def _with_ci(cells: pd.DataFrame, rows: pd.DataFrame, cand: tuple[str, str], ref: tuple[str, str], by: list[str]) -> pd.DataFrame:
    a = rows[(rows["model"] == cand[0]) & (rows["method"] == cand[1])]
    key = ["station", "issued_at", "horizon_minutes"]
    b = rows[(rows["model"] == ref[0]) & (rows["method"] == ref[1])][key + ["winkler", "finite"]]
    pair = a.merge(b, on=key, suffixes=("", "_ref"))
    pair = pair[pair["finite"] & pair["finite_ref"]]
    extras = []
    for _, cell in cells.iterrows():
        mask_a = np.logical_and.reduce([a[c] == cell[c] for c in by])
        mask_p = np.logical_and.reduce([pair[c] == cell[c] for c in by])
        lo, hi = block_boot(a.loc[mask_a, "local_day"].to_numpy(), a.loc[mask_a, "covered"].to_numpy())
        rlo, rhi = block_boot(pair.loc[mask_p, "local_day"].to_numpy(), pair.loc[mask_p, "winkler"].to_numpy(), pair.loc[mask_p, "winkler_ref"].to_numpy())
        extras.append({"coverage_lo": lo, "coverage_hi": hi, "winkler_ratio_lo": rlo, "winkler_ratio_hi": rhi})
    return pd.concat([cells.reset_index(drop=True), pd.DataFrame(extras)], axis=1)


def stage_init(_args) -> None:
    root = run_dir()
    root.mkdir(parents=True, exist_ok=False)
    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True, cwd=PREREG_FILE.parent).stdout
    if status.strip():
        raise SystemExit(f"worktree not clean:\n{status}")
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=PREREG_FILE.parent).stdout.strip()
    prereg = json.loads(PREREG_FILE.read_text(encoding="utf-8"))
    prereg["git_head"], prereg["source_sha256"] = head, _sha256(PREREG_FILE)
    _write_json(root / "preregistration.json", prereg)
    print(f"wrote {root / 'preregistration.json'} at {head}")


def stage_evaluate(_args) -> None:
    root = run_dir()
    if (root / "verdict.json").exists():
        raise FileExistsError(f"refusing_to_overwrite:{root}")
    stored = json.loads((root / "preregistration.json").read_text(encoding="utf-8"))
    if stored["source_sha256"] != _sha256(PREREG_FILE):
        raise SystemExit("preregistration changed after init")
    nb1 = evaluate_nb1(root)
    cdmo = evaluate_cdmo(root)
    primary_cand, primary_ref_nb1, primary_ref_cdmo = ("chronos-2-small", "cqr_aci_amp"), (RIDGE_B5D, "ridge_aci_amp"), ("ridge-B5D-fc", "ridge_aci_amp")

    r_nb1, r_cdmo = nb1["rows"], cdmo["rows"]
    prim = r_nb1[r_nb1["scenario"] == "primary"]
    by_nb1 = ["scenario", "model", "method", "horizon_minutes", "regime"]
    by_group = ["model", "method", "group", "horizon_minutes", "regime"]
    by_station = ["model", "method", "group", "station", "horizon_minutes", "regime"]
    known_regime = r_cdmo[r_cdmo["regime"].isin(["small", "large"])]

    metrics_nb1 = summarise(r_nb1, by_nb1)
    amp_split = prim.assign(amp_side=np.where(prim["amp"] < prim.groupby("horizon_minutes")["amp"].transform("median"), "below_median", "at_or_above_median"))
    metrics_amp = summarise(amp_split, ["model", "method", "horizon_minutes", "amp_side"])
    metrics_group = summarise(known_regime, by_group)
    metrics_all_regimes = summarise(r_cdmo, ["model", "method", "group", "horizon_minutes"])
    metrics_station = summarise(known_regime, by_station)
    equal = metrics_group.groupby(["model", "method", "horizon_minutes", "regime"], observed=True)[
        ["coverage", "frac_infinite", "mean_width", "winkler"]].mean().reset_index()

    # verdict cells
    by_cell_nb1 = ["horizon_minutes", "regime"]
    m = metrics_nb1[(metrics_nb1["scenario"] == "primary") & (metrics_nb1["model"] == primary_cand[0]) & (metrics_nb1["method"] == primary_cand[1])]
    ratios = winkler_ratio_cells(prim, primary_cand, primary_ref_nb1, by_cell_nb1)
    cells_nb1 = h3_cells(m.drop(columns=["scenario"]), ratios, by_cell_nb1)
    cells_nb1 = _with_ci(cells_nb1, prim, primary_cand, primary_ref_nb1, by_cell_nb1)
    by_cell = ["group", "horizon_minutes", "regime"]
    m = metrics_group[(metrics_group["model"] == primary_cand[0]) & (metrics_group["method"] == primary_cand[1])]
    ratios = winkler_ratio_cells(known_regime, primary_cand, primary_ref_cdmo, by_cell)
    cells_cdmo = h3_cells(m, ratios, by_cell)
    cells_cdmo = _with_ci(cells_cdmo, known_regime, primary_cand, primary_ref_cdmo, by_cell)

    sensitivity = []
    for name, rows, cand, ref, by in (
        ("nb1_literal_gamma", prim, ("chronos-2-small", "cqr_aci_amp_literal"), (RIDGE_B5D, "ridge_aci_amp_literal"), by_cell_nb1),
        ("nb1_sym", prim, ("chronos-2-small", "sym_aci_amp"), (RIDGE_B5D, "ridge_aci_amp"), by_cell_nb1),
        ("nb1_ridge_nopH", prim, primary_cand, ("B5_external_as_issued_diurnal_nopH", "ridge_aci_amp"), by_cell_nb1),
        ("nb1_ridge_B4D", prim, primary_cand, ("B4_quality_diurnal", "ridge_aci_amp"), by_cell_nb1),
        ("nb1_base_vs_small_ridge", prim, ("chronos-2-base", "cqr_aci_amp"), (RIDGE_B5D, "ridge_aci_amp"), by_cell_nb1),
        ("nb1_S1", r_nb1[r_nb1["scenario"] == "S1"], primary_cand, (RIDGE_B5D, "ridge_aci_amp"), by_cell_nb1),
        ("cdmo_literal_gamma", known_regime, ("chronos-2-small", "cqr_aci_amp_literal"), ("ridge-B5D-fc", "ridge_aci_amp_literal"), by_cell),
        ("cdmo_sym", known_regime, ("chronos-2-small", "sym_aci_amp"), primary_ref_cdmo, by_cell),
        ("cdmo_ridge_B4D", known_regime, primary_cand, ("ridge-B4D-n", "ridge_aci_amp"), by_cell),
    ):
        mm = summarise(rows[(rows["model"] == cand[0]) & (rows["method"] == cand[1])], by)
        sensitivity.append(h3_cells(mm, winkler_ratio_cells(rows, cand, ref, by), by).assign(sensitivity=name))
    sensitivity = pd.concat(sensitivity, ignore_index=True)

    # periods
    daily_nb1, worst_nb1 = period_coverage(prim, prim["local_day"], ["model", "method", "horizon_minutes"], MIN_ROWS_PER_DAY, "day")
    daily_c, worst_c = period_coverage(r_cdmo, r_cdmo["local_day"], ["model", "method", "group", "horizon_minutes"], MIN_ROWS_DAY_CDMO, "day")
    week = pd.to_datetime(r_cdmo["issued_at"]).dt.strftime("%G-W%V")
    weekly_c, worst_w = period_coverage(r_cdmo, week, ["model", "method", "group", "horizon_minutes"], MIN_ROWS_WEEK_CDMO, "iso_week")

    v_nb1, v_cdmo = verdict_nb1(cells_nb1, 0), verdict_cdmo(cells_cdmo)
    verdict = {
        "h3_overall": verdict_overall(v_nb1, v_cdmo),
        "nb1": v_nb1,
        "cdmo": v_cdmo,
        "nb1_cells_pass": f"{int(cells_nb1['h3_pass'].sum())}/{len(cells_nb1)}",
        "cdmo_cells_pass": f"{int(cells_cdmo['h3_pass'].sum())}/{len(cells_cdmo)}",
        "handoff_reading_h3a_coverage_only": {
            "nb1": verdict_nb1(cells_nb1, 0, "h3a_coverage"), "cdmo": verdict_cdmo(cells_cdmo, column="h3a_coverage"),
            "nb1_cells": f"{int(cells_nb1['h3a_coverage'].sum())}/{len(cells_nb1)}", "cdmo_cells": f"{int(cells_cdmo['h3a_coverage'].sum())}/{len(cells_cdmo)}"},
        "h3b_winkler_cells": {"nb1": f"{int(cells_nb1['h3b_winkler'].sum())}/{len(cells_nb1)}", "cdmo": f"{int(cells_cdmo['h3b_winkler'].sum())}/{len(cells_cdmo)}"},
        "cdmo_reserves_passing_all_cells": {g: bool(p["h3_pass"].all()) for g, p in cells_cdmo.groupby("group")},
        "nb1_small_regime_rows": 0,
        "info": {"nb1": nb1["info"], "cdmo": cdmo["info"]},
    }
    for name, frame in (
        ("metrics_nb1", metrics_nb1), ("metrics_nb1_amp_split_descriptive", metrics_amp), ("metrics_cdmo_reserve", metrics_group),
        ("metrics_cdmo_reserve_all_regimes", metrics_all_regimes), ("metrics_cdmo_equal_reserve", equal), ("metrics_cdmo_station", metrics_station),
        ("h3_cells_nb1", cells_nb1), ("h3_cells_cdmo", cells_cdmo), ("sensitivity", sensitivity),
        ("daily_nb1", daily_nb1), ("daily_cdmo", daily_c), ("weekly_cdmo", weekly_c),
        ("worst_period", pd.concat([worst_nb1.assign(group="NB1"), worst_c, worst_w], ignore_index=True)),
    ):
        _write_csv(root / f"{name}.csv", frame)
    keep = ["station", "issued_at", "horizon_minutes", "y", "amp", "regime", "method", "lower", "upper", "model", "scenario"]
    r_nb1[keep].to_parquet(root / "intervals-nb1.parquet", index=False)
    r_cdmo[keep].to_parquet(root / "intervals-cdmo.parquet", index=False)
    _write_json(root / "verdict.json", verdict)
    print(json.dumps({k: v for k, v in verdict.items() if k != "info"}, indent=1))


def stage_manifest(_args) -> None:
    root = run_dir()
    files = {p.relative_to(root).as_posix(): _sha256(p) for p in sorted(root.rglob("*")) if p.is_file() and p.name != "manifest.json"}
    _write_json(root / "manifest.json", {"run": RUN_NAME, "sha256": files})
    print(f"manifest: {len(files)} files")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("init", "evaluate", "manifest"))
    args = parser.parse_args()
    {"init": stage_init, "evaluate": stage_evaluate, "manifest": stage_manifest}[args.stage](args)


if __name__ == "__main__":
    main()
