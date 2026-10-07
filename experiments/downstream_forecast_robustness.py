"""Research-only forecast-error perturbation for downstream WQI robustness."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.chemistry import emerson_nh3
from hap_shared.forecast_downstream import forecast_kappa


DIRECT = ("Temperature", "pH", "NH4", "TSS")


def evaluate(predictions: pd.DataFrame, *, species: str, draws: int = 100, seed: int = 42) -> pd.DataFrame:
    """Quantify label stability using only empirical errors from the benchmark."""
    rng = np.random.default_rng(seed); rows = []
    wide = predictions.pivot_table(index=["split", "fold", "issued_at", "valid_at", "feature_set", "model", "horizon_minutes"], columns="target", values=["actual", "prediction"], aggfunc="first").dropna()
    if wide.empty:
        return pd.DataFrame()
    actual = wide["actual"].copy(); predicted = wide["prediction"].copy()
    common = [p for p in DIRECT if p in actual and p in predicted]
    if set(common) != set(DIRECT):
        raise ValueError("all_four_direct_targets_required")
    actual["NH3"] = [emerson_nh3(row.NH4, row.pH, row.Temperature) for _, row in actual.iterrows()]
    predicted["NH3"] = [emerson_nh3(row.NH4, row.pH, row.Temperature) for _, row in predicted.iterrows()]
    baseline_kappa = forecast_kappa(actual, predicted, ["Temperature", "pH", "NH3", "TSS"], species)
    residuals = {p: (predicted[p] - actual[p]).dropna().to_numpy() for p in DIRECT}
    for draw in range(draws):
        perturbed = predicted.copy()
        for target, errors in residuals.items():
            perturbed[target] = predicted[target] + rng.choice(errors, size=len(predicted), replace=True)
        perturbed["NH3"] = [emerson_nh3(row.NH4, row.pH, row.Temperature) for _, row in perturbed.iterrows()]
        rows.append({"draw": draw, "kappa": forecast_kappa(actual, perturbed, ["Temperature", "pH", "NH3", "TSS"], species), "baseline_kappa": baseline_kappa})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("predictions", type=Path); parser.add_argument("--species", default="cobia"); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); result = evaluate(pd.read_csv(args.predictions), species=args.species); args.output.parent.mkdir(parents=True, exist_ok=True); result.to_csv(args.output, index=False)


if __name__ == "__main__":
    main()
