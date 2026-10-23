"""Diebold–Mariano test of a forecast model against persistence (research-only).

``diebold_mariano`` compares two aligned error series with a Newey–West (Bartlett)
HAC long-run variance at lag ``horizon_steps - 1`` (default; the original
DM rectangular truncated kernel is available via ``kernel="rectangular"``) and the Harvey–Leybourne–
Newbold (1997) small-sample correction, referred to Student-t with ``n - 1``
degrees of freedom.  For 1-minute forecast origins ``horizon_steps`` equals the
horizon in minutes: overlapping h-step targets make the loss differential an
MA(h-1) process under the null.

The CLI reads a ``forecast_sensor_v2`` run's ``predictions.parquet`` and writes
``dm_tests.csv`` next to it (lockbox split only, each model paired with the
persistence forecast issued at the same timestamp).

Size caveat (Monte Carlo, two independent MA(h-1) error series, n=3000, 300
reps): Bartlett rejects a true null at 5 % about 8 % of the time for h=15 and
11 % for h=60; the rectangular kernel gives about 5 % and 7 %.  Bartlett is
therefore mildly anti-conservative at long horizons.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

LOSSES = {"abs": np.abs, "squared": np.square}
KERNELS = ("bartlett", "rectangular")
DM_COLUMNS = ["target", "horizon_minutes", "feature_set", "model", "n", "mean_loss_diff", "dm_stat", "p_value", "model_better"]


def _newey_west_variance(d: np.ndarray, lag: int, kernel: str = "bartlett") -> float:
    """Kernel-weighted long-run variance of ``d`` (biased autocovariances)."""
    n = len(d)
    centred = d - d.mean()
    variance = float(np.dot(centred, centred) / n)
    for k in range(1, min(lag, n - 1) + 1):
        weight = 1.0 - k / (lag + 1.0) if kernel == "bartlett" else 1.0
        variance += 2.0 * weight * float(np.dot(centred[k:], centred[:-k]) / n)
    return variance


def diebold_mariano(e_model, e_base, horizon_steps: int, loss: str = "abs", kernel: str = "bartlett") -> tuple[float, float]:
    """Return ``(statistic, two_sided_p_value)``; negative statistic = model better.

    Degenerate cases: identical losses give ``(0.0, 1.0)``; fewer than two
    observations or a non-positive HLN correction give ``(nan, nan)``.  A
    rectangular-kernel variance that comes out non-positive falls back to
    Bartlett, which is positive semi-definite.
    """
    if kernel not in KERNELS:
        raise ValueError(f"unknown_kernel:{kernel}")
    if loss not in LOSSES:
        raise ValueError(f"unknown_loss:{loss}")
    e_model = np.asarray(e_model, dtype=float)
    e_base = np.asarray(e_base, dtype=float)
    if e_model.shape != e_base.shape or e_model.ndim != 1:
        raise ValueError("error_series_must_be_1d_and_aligned")
    d = LOSSES[loss](e_model) - LOSSES[loss](e_base)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 2:
        return (float("nan"), float("nan"))
    h = max(int(horizon_steps), 1)
    mean_d = float(d.mean())
    variance = _newey_west_variance(d, h - 1, kernel)
    if kernel == "rectangular" and not variance > 0:
        variance = _newey_west_variance(d, h - 1, "bartlett")
    if not np.isfinite(variance) or variance <= 0:
        if np.allclose(d, 0.0):
            return (0.0, 1.0)
        # Constant non-zero differential: the test is degenerate, not informative.
        return (float("nan"), float("nan"))
    dm = mean_d / np.sqrt(variance / n)
    radicand = (n + 1 - 2 * h + h * (h - 1) / n) / n
    if radicand <= 0:
        return (float("nan"), float("nan"))
    statistic = float(dm * np.sqrt(radicand))
    p_value = float(min(1.0, 2.0 * stats.t.sf(abs(statistic), df=n - 1)))
    return (statistic, p_value)


def dm_table(predictions: pd.DataFrame, *, loss: str = "abs", alpha: float = 0.05, kernel: str = "bartlett") -> pd.DataFrame:
    """DM rows for every lockbox (target, horizon, feature_set, model != persistence)."""
    lockbox = predictions[predictions["split"].eq("lockbox")].copy()
    lockbox["error"] = lockbox["prediction"] - lockbox["actual"]
    key = ["target", "horizon_minutes", "feature_set"]
    rows = []
    for values, group in lockbox.groupby(key, sort=True, observed=True):
        persistence = group[group["model"].eq("persistence")][["issued_at", "error"]]
        if persistence.empty:
            continue
        for model, candidate in group[~group["model"].eq("persistence")].groupby("model", sort=True, observed=True):
            paired = candidate[["issued_at", "error"]].merge(persistence, on="issued_at", suffixes=("_model", "_base"), validate="one_to_one").sort_values("issued_at")
            paired = paired.dropna(subset=["error_model", "error_base"])
            horizon = int(values[1])
            statistic, p_value = diebold_mariano(paired["error_model"].to_numpy(), paired["error_base"].to_numpy(), horizon_steps=horizon, loss=loss, kernel=kernel)
            mean_diff = float((LOSSES[loss](paired["error_model"]) - LOSSES[loss](paired["error_base"])).mean()) if len(paired) else float("nan")
            rows.append(dict(zip(key, values)) | {"model": model, "n": int(len(paired)), "mean_loss_diff": mean_diff, "dm_stat": statistic, "p_value": p_value, "model_better": bool(np.isfinite(p_value) and statistic < 0 and p_value < alpha)})
    return pd.DataFrame(rows, columns=DM_COLUMNS)


def write_dm_tests(run_dir: Path, *, loss: str = "abs", alpha: float = 0.05, kernel: str = "bartlett") -> Path:
    run_dir = Path(run_dir)
    out = run_dir / "dm_tests.csv"
    if out.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out}")
    predictions = pd.read_parquet(run_dir / "predictions.parquet", columns=["split", "target", "horizon_minutes", "feature_set", "model", "issued_at", "actual", "prediction"])
    table = dm_table(predictions, loss=loss, alpha=alpha, kernel=kernel)
    table.to_csv(out, index=False)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dir", type=Path, help="forecast_sensor_v2 output directory containing predictions.parquet")
    parser.add_argument("--loss", choices=tuple(LOSSES), default="abs")
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--kernel", choices=KERNELS, default="bartlett", help="HAC kernel (bartlett = Newey-West; rectangular = original DM)")
    args = parser.parse_args()
    out = write_dm_tests(args.run_dir, loss=args.loss, alpha=args.alpha, kernel=args.kernel)
    print(pd.read_csv(out).to_string(index=False))


if __name__ == "__main__":
    main()
