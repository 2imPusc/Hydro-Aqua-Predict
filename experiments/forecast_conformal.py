"""Time-ordered split-conformal prediction intervals for sensor forecasts (H1.3).

Reads ``forecast_sensor_v2`` predictions (H1.2 runs) and evaluates symmetric
absolute-residual intervals ``prediction +/- q`` on the lockbox, which is never
used for calibration.

Methods
-------
``static``
    Split conformal.  Calibration scores are ``|actual - prediction|`` of the
    last ``K`` rolling folds (most recent first in time, default ``K=3``).
    ``q`` is the finite-sample conformal quantile: the ``ceil((n+1)(1-alpha))``-th
    smallest score (``inf`` when that index exceeds ``n``).
``static_night``
    Same, stratified (Mondrian) by the ``night`` flag: each lockbox row uses
    the quantile of calibration scores with the same ``night`` value.  ``gap``
    is not used as a stratum (only ~100 gap rows per target).
``aci``
    Adaptive conformal inference (Gibbs & Candes 2021) run over the lockbox in
    ``issued_at`` order with step ``gamma``:
    ``alpha_{t+1} = alpha_t + gamma * (alpha - err_t)``, and ``q_t`` is the
    finite-sample quantile at level ``1 - alpha_t`` of a score pool seeded with
    the static calibration scores.

    **Delayed-feedback (no look-ahead) rule.**  The score and miscoverage
    indicator of a lockbox origin ``s`` only become usable once its actual has
    been observed, i.e. at ``known_at_s = max(valid_at_s, actual_at_s)``
    (``actual_at`` may lag ``valid_at`` by up to 2 min under
    nearest-observation alignment).  Before issuing origin ``t`` the loop
    consumes, in ``known_at`` order, every pending origin with
    ``known_at_s <= issued_at_t``: its score is inserted into the pool and its
    ``err_s`` updates ``alpha``.  An origin whose ``valid_at > issued_at_t`` is
    therefore never seen when interval ``t`` is formed.  ``alpha_t <= 0`` gives
    an infinite interval (counted in ``n_infinite``/``frac_infinite``, excluded
    from width means; ``coverage_finite`` is coverage over finite rows only).
``aci_scaled``
    ACI with ``gamma_h = gamma * REFERENCE_HORIZON / h``.  Feedback lags by
    ``h`` origins (one origin per minute), so with a fixed ``gamma`` alpha can
    drift by ~``h * gamma`` before any correction lands and goes below 0
    (infinite intervals) at long horizons; scaling by the delay keeps the
    effective step per feedback lag constant (unchanged at h = 15).

Calibration leakage guard: the H1.2 fold-5 test window extends past the
lockbox start, so calibration rows with ``known_at >= min(lockbox issued_at)``
are dropped before the last-``K`` folds are taken (count in ``manifest.json``).

Metrics per (target, horizon, feature_set, model, method, nominal): lockbox
empirical coverage, mean/median width ``2q``, width relative to the lockbox
persistence MAE of the same (target, horizon, feature_set), and per-day
coverage (local UTC+7 date of ``issued_at``; days with fewer than
``MIN_ROWS_PER_DAY`` rows are listed but excluded from min/max).  Gate (roadmap
H1.3): PI80 lockbox coverage in [0.75, 0.85] and ``frac_infinite <= 0.01``
(an interval that is often the whole real line is not a usable PI).
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import paths  # noqa: E402

DEFAULT_TARGETS = ("Temperature", "pH", "NH4")
DEFAULT_INPUT_RUN = "forecast-h1.2-20261016-{target}"
DEFAULT_RUN_NAME = "forecast-h1.3-conformal-20261016"
DEFAULT_ALPHAS = (0.2, 0.1)
DEFAULT_K = 3
DEFAULT_GAMMA = 0.005
GATE_PI80 = (0.75, 0.85)
GATE_MAX_FRAC_INFINITE = 0.01
REFERENCE_HORIZON = 15
METHODS = ("static", "static_night", "aci", "aci_scaled")
LOCAL_TZ = "Asia/Ho_Chi_Minh"
MIN_ROWS_PER_DAY = 60
GROUP = ["horizon_minutes", "feature_set", "model"]
COLUMNS = [
    "split", "fold", "target", "horizon_minutes", "feature_set", "model",
    "issued_at", "valid_at", "actual_at", "actual", "prediction", "night",
]


def _rank(n: int, alpha: float) -> int:
    return math.ceil((n + 1) * (1.0 - alpha) - 1e-9)


def conformal_quantile(residuals, alpha: float) -> float:
    """Finite-sample split-conformal quantile (``inf`` if the rank exceeds ``n``)."""
    scores = np.sort(np.asarray(residuals, dtype=float))
    return _sorted_quantile(scores, alpha)


def _sorted_quantile(scores, alpha: float) -> float:
    n = len(scores)
    k = _rank(n, alpha)
    if k > n:
        return math.inf
    if k <= 0:
        return 0.0
    return float(scores[k - 1])


def known_at(df: pd.DataFrame) -> pd.Series:
    """Time at which an origin's actual is observed: ``max(valid_at, actual_at)``.

    ``actual_at`` is missing (NaT) for the H1.2 lockbox rows; ``valid_at`` is
    then used, which is still never earlier than the observation time.
    """
    later = df["actual_at"].notna() & (df["actual_at"] > df["valid_at"])
    return df["valid_at"].where(~later, df["actual_at"])


def calibration_residuals(rolling: pd.DataFrame, k_folds: int, lockbox_start) -> tuple[pd.DataFrame, int]:
    """Rolling rows usable for calibration: known before the lockbox, last ``k_folds`` folds.

    Returns ``(rows_with_residual_column, n_dropped_for_leakage)``.
    """
    rolling = rolling[rolling["split"] == "rolling"] if "split" in rolling else rolling
    safe = known_at(rolling) < lockbox_start
    kept = rolling[safe]
    folds = sorted(kept["fold"].unique())[-k_folds:]
    kept = kept[kept["fold"].isin(folds)].copy()
    kept["residual"] = (kept["actual"] - kept["prediction"]).abs()
    return kept, int((~safe).sum())


def _as_ns(values) -> np.ndarray:
    """Timezone-naive UTC ``datetime64[ns]`` array (tz-aware objects are converted)."""
    idx = pd.DatetimeIndex(pd.Series(values))
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.to_numpy(dtype="datetime64[ns]")


def aci_intervals(cal_residuals, issued_at, known_at_, residual, alpha: float, gamma: float):
    """ACI quantiles for one group's lockbox rows (sorted by ``issued_at``).

    See the module docstring for the delayed-feedback rule.  Returns
    ``(q, alpha_t)`` arrays aligned with the input rows.
    """
    issued_at = _as_ns(issued_at)
    known_at_ = _as_ns(known_at_)
    if np.isnat(known_at_).any() or np.isnat(issued_at).any():
        raise ValueError("missing_timestamps")
    residual = np.asarray(residual, dtype=float)
    pool = sorted(np.asarray(cal_residuals, dtype=float).tolist())
    order = np.argsort(known_at_, kind="stable")
    n = len(issued_at)
    q = np.empty(n)
    alpha_hist = np.empty(n)
    alpha_t = alpha
    j = 0
    for i in range(n):
        # Origins not yet issued (s >= i) cannot be known; wait for them.
        while j < n and order[j] < i and known_at_[order[j]] <= issued_at[i]:
            s = order[j]
            err = 1.0 if residual[s] > q[s] else 0.0
            alpha_t += gamma * (alpha - err)
            bisect.insort(pool, residual[s])
            j += 1
        alpha_hist[i] = alpha_t
        q[i] = _sorted_quantile(pool, alpha_t)
    return q, alpha_hist


def _summary(block: pd.DataFrame, q: np.ndarray, persistence_mae: float, n_cal: int) -> tuple[dict, pd.DataFrame]:
    resid = block["residual"].to_numpy()
    covered = resid <= q
    finite = np.isfinite(q)
    width = 2.0 * q[finite]
    day = block["issued_at"].dt.tz_convert(LOCAL_TZ).dt.date.to_numpy()
    daily = (
        pd.DataFrame({"day": day, "covered": covered})
        .groupby("day")["covered"].agg(["mean", "size"])
        .rename(columns={"mean": "coverage", "size": "n"})
        .reset_index()
    )
    full = daily[daily["n"] >= MIN_ROWS_PER_DAY]
    mean_width = float(width.mean()) if len(width) else math.nan
    row = {
        "n": len(block),
        "n_cal": n_cal,
        "coverage": float(covered.mean()),
        "mean_width": mean_width,
        "median_width": float(np.median(width)) if len(width) else math.nan,
        "n_infinite": int((~finite).sum()),
        "frac_infinite": float((~finite).mean()),
        "coverage_finite": float(covered[finite].mean()) if finite.any() else math.nan,
        "model_mae": float(resid.mean()),
        "persistence_mae": persistence_mae,
        "width_rel_persistence_mae": mean_width / persistence_mae if persistence_mae > 0 else math.nan,
        "day_cov_min": float(full["coverage"].min()) if len(full) else math.nan,
        "day_cov_max": float(full["coverage"].max()) if len(full) else math.nan,
        "n_days": int(len(full)),
    }
    return row, daily


def evaluate_target(
    df: pd.DataFrame,
    alphas=DEFAULT_ALPHAS,
    k_folds: int = DEFAULT_K,
    gamma: float = DEFAULT_GAMMA,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Coverage table, daily coverage table and calibration info for one target."""
    df = df.copy()
    for col in ("split", "target", "feature_set", "model"):
        df[col] = df[col].astype(str)
    df["residual"] = (df["actual"] - df["prediction"]).abs()
    lockbox = df[df["split"] == "lockbox"]
    lockbox_start = lockbox["issued_at"].min()
    target = str(df["target"].iloc[0])
    cal_all, dropped = calibration_residuals(df[df["split"] == "rolling"], k_folds, lockbox_start)
    pers_mae = (
        lockbox[lockbox["model"] == "persistence"].groupby(["horizon_minutes", "feature_set"])["residual"].mean().to_dict()
    )
    cal_groups = {key: g for key, g in cal_all.groupby(GROUP)}
    rows, daily_rows = [], []
    for key, block in lockbox.groupby(GROUP):
        block = block.sort_values("issued_at", kind="stable")
        cal = cal_groups.get(key)
        if cal is None or cal.empty:
            continue
        cal_scores = cal["residual"].to_numpy()
        night_scores = {v: g["residual"].to_numpy() for v, g in cal.groupby("night")}
        p_mae = float(pers_mae.get((key[0], key[1]), math.nan))
        kn = known_at(block).to_numpy()
        for alpha in alphas:
            q_static = np.full(len(block), conformal_quantile(cal_scores, alpha))
            night = block["night"].to_numpy()
            q_night = np.array(
                [conformal_quantile(night_scores.get(v, cal_scores), alpha) for v in (0, 1)]
            )[np.clip(night, 0, 1)]
            q_aci, _ = aci_intervals(
                cal_scores, block["issued_at"].to_numpy(), kn, block["residual"].to_numpy(), alpha, gamma
            )
            q_scaled, _ = aci_intervals(
                cal_scores,
                block["issued_at"].to_numpy(),
                kn,
                block["residual"].to_numpy(),
                alpha,
                gamma * REFERENCE_HORIZON / float(key[0]),
            )
            methods = (("static", q_static), ("static_night", q_night), ("aci", q_aci), ("aci_scaled", q_scaled))
            for method, q in methods:
                summary, daily = _summary(block, q, p_mae, len(cal_scores))
                ident = {
                    "target": target,
                    "horizon_minutes": int(key[0]),
                    "feature_set": key[1],
                    "model": key[2],
                    "method": method,
                    "nominal": round(1.0 - alpha, 4),
                }
                rows.append({**ident, **summary})
                daily_rows.append(daily.assign(**ident))
    coverage = pd.DataFrame(rows)
    if not coverage.empty:
        lo, hi = GATE_PI80
        coverage["gate_pi80_pass"] = np.where(
            np.isclose(coverage["nominal"], 0.8),
            (coverage["coverage"].between(lo, hi) & (coverage["frac_infinite"] <= GATE_MAX_FRAC_INFINITE)).map(
                {True: "pass", False: "fail"}
            ),
            "",
        )
    daily = pd.concat(daily_rows, ignore_index=True) if daily_rows else pd.DataFrame()
    info = {
        "lockbox_start": str(lockbox_start),
        "calibration_folds": sorted(int(f) for f in cal_all["fold"].unique()),
        "calibration_rows": int(len(cal_all)),
        "rolling_rows_dropped_known_after_lockbox_start": dropped,
    }
    return coverage, daily, info


def write_outputs(out_dir: Path, coverage: pd.DataFrame, daily: pd.DataFrame, manifest: dict) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)  # refuse to overwrite an existing run
    coverage.to_csv(out_dir / "coverage.csv", index=False)
    daily.to_csv(out_dir / "daily_coverage.csv", index=False)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--targets", nargs="+", default=list(DEFAULT_TARGETS))
    parser.add_argument("--input-run", default=DEFAULT_INPUT_RUN, help="run dir name template with {target}")
    parser.add_argument("--run-name", default=DEFAULT_RUN_NAME)
    parser.add_argument("--k-folds", type=int, default=DEFAULT_K)
    parser.add_argument("--gamma", type=float, default=DEFAULT_GAMMA)
    parser.add_argument("--alphas", type=float, nargs="+", default=list(DEFAULT_ALPHAS))
    args = parser.parse_args(argv)

    out_dir = paths.EXPERIMENT_OUTPUT_DIR / args.run_name
    if out_dir.exists():
        raise SystemExit(f"refusing to overwrite existing output: {out_dir}")
    coverages, dailies, inputs, infos = [], [], {}, {}
    for target in args.targets:
        path = paths.EXPERIMENT_OUTPUT_DIR / args.input_run.format(target=target) / "predictions.parquet"
        inputs[target] = {"path": str(path.relative_to(paths.PROJECT_ROOT)), "sha256": _sha256(path)}
        df = pd.read_parquet(path, columns=COLUMNS)
        coverage, daily, info = evaluate_target(df, tuple(args.alphas), args.k_folds, args.gamma)
        del df
        coverages.append(coverage)
        dailies.append(daily)
        infos[target] = info
        print(f"{target}: {len(coverage)} rows; calibration {info}", flush=True)
    manifest = {
        "schema_version": "forecast-conformal-h1.3",
        "inputs": inputs,
        "params": {
            "alphas": args.alphas,
            "k_folds": args.k_folds,
            "gamma": args.gamma,
            "methods": list(METHODS),
            "aci_scaled_gamma": f"gamma * {REFERENCE_HORIZON} / horizon_minutes",
            "score": "abs_residual_symmetric",
            "quantile": "ceil((n+1)(1-alpha))-th smallest; inf if > n",
            "known_at": "max(valid_at, actual_at)",
            "aci_delay_rule": "origin s feeds pool/alpha only when known_at_s <= issued_at_t",
            "calibration_leakage_rule": "drop rolling rows with known_at >= min(lockbox issued_at), then last k folds",
            "daily_coverage_day": f"local date ({LOCAL_TZ}) of issued_at; min/max over days with >= {MIN_ROWS_PER_DAY} rows",
            "gate_pi80": list(GATE_PI80),
            "gate_max_frac_infinite": GATE_MAX_FRAC_INFINITE,
            "mean_width": "mean of 2q over rows with finite q",
        },
        "calibration": infos,
        "runtime_changed": False,
    }
    write_outputs(out_dir, pd.concat(coverages, ignore_index=True), pd.concat(dailies, ignore_index=True), manifest)
    print(f"wrote {out_dir}")


if __name__ == "__main__":
    main()
