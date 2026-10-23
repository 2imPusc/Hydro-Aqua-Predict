# src/forecast_downstream.py
"""Bridge forecast -> suitability classification -> Cohen's kappa.

The forecast param namespace (DO, Temperature, pH, Salinity, NH3, PO4,
Transparency) matches the keys in model/output/{species}_thresholds.json, so
classify_grid matches directly — no renaming needed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score

from hap_shared.classification import classify_grid


def labels_from_param_table(table: pd.DataFrame, params: list, species: str) -> np.ndarray:
    """Classify each row (1 row = 1 water sample with param columns) -> suitability_label.

    method='scoring' (rule-based) is forced on purpose: it works with any subset of
    params, whereas the 'model' classifier needs the full feature vector.
    """
    usable = [p for p in params if p in table.columns]
    out = classify_grid(table[usable].copy(), usable, species=species, method='scoring')
    return out['suitability_label'].to_numpy()


def forecast_kappa(observed: pd.DataFrame, predicted: pd.DataFrame,
                   params: list, species: str) -> float:
    """Cohen's kappa between suitability labels from observed vs predicted param tables.

    observed/predicted: row-aligned DataFrames with the same `params` columns.
    Returns NaN if empty, length-mismatched, or only one label class total.

    Note on the single-class guard: we return NaN ONLY when BOTH series collapse to a
    single class (kappa truly undefined, 0/0). If observed varies but predicted collapses
    (e.g. forecast always says "phù hợp"), we still compute kappa — that low/zero value is
    an informative "forecast lost the signal" result, not something to hide.
    """
    if len(observed) == 0 or len(predicted) == 0 or len(observed) != len(predicted):
        return float('nan')
    lab_obs = labels_from_param_table(observed, params, species)
    lab_pred = labels_from_param_table(predicted, params, species)
    if len(set(lab_obs)) < 2 and len(set(lab_pred)) < 2:
        return float('nan')
    return float(cohen_kappa_score(lab_obs, lab_pred))
