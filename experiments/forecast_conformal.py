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

``aci_amp`` / ``static_amp`` / ``aci_amp_std`` / ``aci_amp_72h`` (A4)
    Amplitude-normalised scores ``|r| / max(A(t), floor)`` where ``A(t)`` is
    the trailing diurnal amplitude of the target at the origin's issue time:
    max - min (``std`` for ``aci_amp_std``) over a 24 h window (72 h for
    ``aci_amp_72h``) of the observed series.  The observed series is the
    ``persistence`` prediction (the target's ``lag_1m`` value, known at
    ``issued_at``), so ``A(t)`` uses only data available at issue time.  A
    window with fewer than ``AMP_MIN_FRAC`` x window-minutes points gives no
    amplitude: such calibration rows are dropped (counted in the manifest);
    such lockbox rows fall back to the median calibration amplitude (counted).
    ``floor = AMP_FLOOR_FRAC x`` median calibration amplitude.  ``aci_amp``
    runs the delay-scaled ACI (as ``aci_scaled``) on normalised scores, and the
    half-width is ``q_norm_t * max(A(t), floor)``; ``static_amp`` uses the split
    conformal quantile of normalised calibration scores.

Calibration leakage guard: the H1.2 fold-5 test window extends past the
lockbox start, so calibration rows with ``known_at >= min(lockbox issued_at)``
are dropped before the last-``K`` folds are taken (count in ``manifest.json``).

Metrics per (target, horizon, feature_set, model, method, nominal): lockbox
empirical coverage, mean/median width ``2q``, mean Winkler interval score
``2q + (2/alpha) max(0, |r| - q)`` (finite rows), the same three on the
October subset (``_oct``: local date >= 2026-10-01) and before/after
``late_start`` (``_early``/``_late``, default 2026-10-05 local, the cold front
after which the diurnal amplitude grew, RL-13), width relative to the lockbox
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
METHODS = ("static", "static_night", "aci", "aci_scaled", "static_amp", "aci_amp", "aci_amp_std", "aci_amp_72h")
# name -> (amplitude kind, trailing window, delay-scaled ACI?)
AMP_VARIANTS = {
    "aci_amp": ("range", "24h", True),
    "static_amp": ("range", "24h", False),
    "aci_amp_std": ("std", "24h", True),
    "aci_amp_72h": ("range", "72h", True),
}
AMP_PRIMARY = ("range", "24h")
AMP_MIN_FRAC = 0.5
AMP_FLOOR_FRAC = 0.25
LOCAL_TZ = "Asia/Ho_Chi_Minh"
MIN_ROWS_PER_DAY = 60
OCT_START = pd.Timestamp("2026-10-01", tz=LOCAL_TZ)
DEFAULT_LATE_START = pd.Timestamp("2026-10-05", tz=LOCAL_TZ)
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


def observed_series(df: pd.DataFrame) -> pd.Series:
    """Target value known at each ``issued_at``: the persistence (``lag_1m``) prediction."""
    pers = df[df["model"].astype(str) == "persistence"]
    s = pd.Series(pers["prediction"].to_numpy(dtype=float), index=pd.DatetimeIndex(_as_ns(pers["issued_at"])))
    s = s[np.isfinite(s.to_numpy())]
    return s[~s.index.duplicated(keep="first")].sort_index()


def trailing_amplitude(series: pd.Series, at, window: str, kind: str, min_count: int) -> np.ndarray:
    """Amplitude of ``series`` over ``(t - window, t]`` for each ``t`` in ``at``.

    ``series`` is indexed by the time each value became known; only values
    with index ``<= t`` are used (time-based rolling is right-closed and the
    lookup takes the last observation at or before ``t``).  ``kind`` is
    ``range`` (max - min) or ``std``.  NaN when the window holds fewer than
    ``min_count`` values or nothing precedes ``t``.
    """
    s = pd.Series(np.asarray(series, dtype=float), index=pd.DatetimeIndex(_as_ns(series.index))).sort_index()
    s = s[~s.index.duplicated(keep="first")]
    roll = s.rolling(window)
    if kind == "range":
        amp = roll.max() - roll.min()
    elif kind == "std":
        amp = roll.std()
    else:
        raise ValueError(f"unknown_amplitude_kind:{kind}")
    amp = amp.where(roll.count() >= min_count).to_numpy()
    idx = s.index.to_numpy().searchsorted(_as_ns(at), side="right") - 1
    out = np.full(len(idx), np.nan)
    ok = idx >= 0
    out[ok] = amp[idx[ok]]
    return out


def winkler_score(residual, q, alpha: float) -> np.ndarray:
    """Interval score of the symmetric interval ``prediction +/- q``."""
    residual = np.asarray(residual, dtype=float)
    q = np.asarray(q, dtype=float)
    return 2.0 * q + (2.0 / alpha) * np.maximum(0.0, residual - q)


def _window_metrics(mask: np.ndarray, resid: np.ndarray, q: np.ndarray, alpha: float, suffix: str) -> dict:
    r, qm = resid[mask], q[mask]
    finite = np.isfinite(qm)
    return {
        f"n{suffix}": int(mask.sum()),
        f"coverage{suffix}": float((r <= qm).mean()) if mask.any() else math.nan,
        f"mean_width{suffix}": float(2.0 * qm[finite].mean()) if finite.any() else math.nan,
        f"winkler{suffix}": float(winkler_score(r[finite], qm[finite], alpha).mean()) if finite.any() else math.nan,
    }


def _summary(block: pd.DataFrame, q: np.ndarray, persistence_mae: float, n_cal: int, alpha: float = 0.2,
             late_start=DEFAULT_LATE_START) -> tuple[dict, pd.DataFrame]:
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
    issued = block["issued_at"]
    row["winkler"] = _window_metrics(np.ones(len(block), dtype=bool), resid, q, alpha, "")["winkler"]
    for suffix, mask in (("_oct", issued >= OCT_START), ("_early", issued < late_start), ("_late", issued >= late_start)):
        row.update(_window_metrics(mask.to_numpy(), resid, q, alpha, suffix))
    return row, daily


def _window_minutes(window: str) -> float:
    return pd.Timedelta(window).total_seconds() / 60.0


def evaluate_target(
    df: pd.DataFrame,
    alphas=DEFAULT_ALPHAS,
    k_folds: int = DEFAULT_K,
    gamma: float = DEFAULT_GAMMA,
    late_start=DEFAULT_LATE_START,
    amp_variants: dict = AMP_VARIANTS,
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
    series = observed_series(df)
    amp_info, amp_cal, amp_lock, floors = {}, {}, {}, {}
    for spec in sorted({(kind, window) for kind, window, _ in amp_variants.values()}):
        kind, window = spec
        min_count = int(math.ceil(AMP_MIN_FRAC * _window_minutes(window)))
        a_cal = trailing_amplitude(series, cal_all["issued_at"], window, kind, min_count)
        a_lock = trailing_amplitude(series, lockbox["issued_at"], window, kind, min_count)
        med = float(np.nanmedian(a_cal)) if np.isfinite(a_cal).any() else math.nan
        usable = math.isfinite(med) and med > 0
        floors[spec] = AMP_FLOOR_FRAC * med if usable else math.nan
        amp_cal[spec] = pd.Series(a_cal, index=cal_all.index)
        amp_lock[spec] = pd.Series(np.where(np.isfinite(a_lock), a_lock, med), index=lockbox.index)
        amp_info[f"{kind}_{window}"] = {
            "usable": bool(usable),
            "min_count": min_count,
            "median_calibration_amplitude": med,
            "floor": floors[spec],
            "calibration_rows_dropped_no_amplitude": int((~np.isfinite(a_cal)).sum()),
            "lockbox_rows_filled_with_median": int((~np.isfinite(a_lock)).sum()),
            "lockbox_amplitude_quantiles": (
                {str(p): float(np.nanquantile(a_lock, p)) for p in (0.05, 0.5, 0.95)} if np.isfinite(a_lock).any() else {}
            ),
        }
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
            n_all = len(cal_scores)
            methods = [("static", q_static, n_all), ("static_night", q_night, n_all), ("aci", q_aci, n_all), ("aci_scaled", q_scaled, n_all)]
            for name, (kind, window, use_aci) in amp_variants.items():
                spec = (kind, window)
                floor = floors[spec]
                if not math.isfinite(floor):
                    continue
                a_c = amp_cal[spec].loc[cal.index].to_numpy()
                ok = np.isfinite(a_c)
                cal_norm = cal_scores[ok] / np.maximum(a_c[ok], floor)
                scale = np.maximum(amp_lock[spec].loc[block.index].to_numpy(), floor)
                if use_aci:
                    q_norm, _ = aci_intervals(
                        cal_norm, block["issued_at"].to_numpy(), kn, block["residual"].to_numpy() / scale, alpha,
                        gamma * REFERENCE_HORIZON / float(key[0]),
                    )
                else:
                    q_norm = np.full(len(block), conformal_quantile(cal_norm, alpha))
                methods.append((name, q_norm * scale, int(ok.sum())))
            for method, q, n_cal in methods:
                summary, daily = _summary(block, q, p_mae, n_cal, alpha, late_start)
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
        "amplitude": {**amp_info.get(f"{AMP_PRIMARY[0]}_{AMP_PRIMARY[1]}", {}), "variants": amp_info},
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
    parser.add_argument("--late-start", default=str(DEFAULT_LATE_START.date()), help="local date splitting _early/_late")
    args = parser.parse_args(argv)
    late_start = pd.Timestamp(args.late_start, tz=LOCAL_TZ)

    out_dir = paths.EXPERIMENT_OUTPUT_DIR / args.run_name
    if out_dir.exists():
        raise SystemExit(f"refusing to overwrite existing output: {out_dir}")
    coverages, dailies, inputs, infos = [], [], {}, {}
    for target in args.targets:
        path = paths.EXPERIMENT_OUTPUT_DIR / args.input_run.format(target=target) / "predictions.parquet"
        inputs[target] = {"path": str(path.relative_to(paths.PROJECT_ROOT)), "sha256": _sha256(path)}
        df = pd.read_parquet(path, columns=COLUMNS)
        coverage, daily, info = evaluate_target(df, tuple(args.alphas), args.k_folds, args.gamma, late_start)
        del df
        coverages.append(coverage)
        dailies.append(daily)
        infos[target] = info
        print(f"{target}: {len(coverage)} rows; calibration {info}", flush=True)
    manifest = {
        "schema_version": "forecast-conformal-h1.3-amp",
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
            "winkler": "mean of 2q + (2/alpha) max(0, |r| - q) over rows with finite q",
            "amp_variants": {k: {"kind": v[0], "window": v[1], "delay_scaled_aci": v[2]} for k, v in AMP_VARIANTS.items()},
            "amp_series": "persistence prediction (target lag_1m) indexed by issued_at; window (t - w, t]",
            "amp_min_count": f"ceil({AMP_MIN_FRAC} x window minutes); calibration rows without amplitude dropped",
            "amp_floor": f"{AMP_FLOOR_FRAC} x median calibration amplitude",
            "oct_start": str(OCT_START),
            "late_start": str(late_start),
        },
        "calibration": infos,
        "runtime_changed": False,
    }
    write_outputs(out_dir, pd.concat(coverages, ignore_index=True), pd.concat(dailies, ignore_index=True), manifest)
    print(f"wrote {out_dir}")


if __name__ == "__main__":
    main()
