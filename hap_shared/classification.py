"""
Phan loai kha nang nuoi trong thuy san cho cac o grid noi suy.
Ho tro nhieu loai: Con Hau, Cay Ban Chua, Ca Gio.

Ho tro 2 phuong phap:
  1. Scoring: tinh diem dua tren breakpoints + trong so (hoat dong voi bat ky tap con params nao)
  2. Model: dung XGBoost classifier da train (can day du params)
"""
import json
import warnings
import numpy as np
import pandas as pd
import joblib
from pathlib import Path

from hap_shared.species import SPECIES, DEFAULT_SPECIES
from hap_shared.scoring import score_param, score_to_label

MODEL_DIR = Path(__file__).resolve().parent / "thresholds"

LABEL_NAMES = {
    0: 'Chưa phù hợp',
    1: 'Phù hợp',
    2: 'Rất phù hợp',
}

LABEL_COLORS = {
    0: '#d73027',   # do
    1: '#fee08b',   # vang
    2: '#1a9850',   # xanh
}


_thresholds_cache = {}
_model_cache = {}


def _load_thresholds(species: str = DEFAULT_SPECIES):
    """Load breakpoints va weights tu JSON theo loai."""
    if species not in _thresholds_cache:
        spec = SPECIES[species]
        path = MODEL_DIR / spec['thresholds_file']
        with open(path, 'r', encoding='utf-8') as f:
            _thresholds_cache[species] = json.load(f)
    return _thresholds_cache[species]


def _load_model(species: str = DEFAULT_SPECIES):
    """Load trained classifier (base or ensemble) + meta from pkl.

    Returns ((model, label_to_idx, idx_to_label), meta) or None.
    """
    if species not in _model_cache:
        spec = SPECIES[species]
        model_path = MODEL_DIR / species / spec['model_file']
        meta_path = MODEL_DIR / species / spec['meta_file']

        if not model_path.exists() or not meta_path.exists():
            _model_cache[species] = None
        else:
            try:
                model_tuple = joblib.load(model_path)  # (model, label_to_idx, idx_to_label)
                meta = joblib.load(meta_path)
                _model_cache[species] = (model_tuple, meta)
            except Exception:
                _model_cache[species] = None

    return _model_cache[species]


# Aliases for backward compatibility (internal use)
_score_param = score_param
_score_to_label = score_to_label


def compute_composite_variance(grid_df: pd.DataFrame, available_params: list,
                                species: str = DEFAULT_SPECIES) -> pd.DataFrame:
    """
    Tinh composite variance = trung binh co trong so cua variance tung chi so.
    Trong so dung importance_rank (giong he thong scoring).
    Chi hoat dong khi grid_df co cot <param>_variance (method=kriging).

    Them cot: composite_variance, <param>_variance_norm
    """
    thresholds = _load_thresholds(species)
    variance_cols = [p for p in available_params
                     if p in thresholds and f'{p}_variance' in grid_df.columns]

    if not variance_cols:
        return grid_df

    grid_df = grid_df.copy()

    # Normalize variance tung chi so ve [0, 1] de so sanh duoc
    for p in variance_cols:
        col = f'{p}_variance'
        vmax = grid_df[col].max()
        if vmax > 0:
            grid_df[f'{p}_variance_norm'] = grid_df[col] / vmax
        else:
            grid_df[f'{p}_variance_norm'] = 0.0

    # Tinh trong so (dynamic max_rank tu thresholds)
    max_rank = max(thresholds[p]['importance_rank'] for p in thresholds)
    raw_weights = {}
    for p in variance_cols:
        rank = thresholds[p]['importance_rank']
        raw_weights[p] = max_rank + 1 - rank
    total_w = sum(raw_weights.values())
    weights = {p: w / total_w for p, w in raw_weights.items()}

    # Composite variance = weighted average of normalized variances
    composite = np.zeros(len(grid_df))
    for p in variance_cols:
        composite += weights[p] * grid_df[f'{p}_variance_norm'].values
    grid_df['composite_variance'] = composite

    return grid_df


def classify_grid(grid_df: pd.DataFrame, available_params: list,
                   species: str = DEFAULT_SPECIES,
                   method: str = 'scoring') -> pd.DataFrame:
    """
    Phan loai kha nang nuoi trong cho moi o grid.

    Parameters
    ----------
    grid_df : DataFrame voi cot grid_x, grid_y, va cac cot chi so nuoc
    available_params : danh sach ten chi so co trong grid_df
    species : 'oyster', 'sonneratia', 'cobia'
    method : 'scoring' (rule-based) hoac 'model' (XGBoost classifier)

    Returns
    -------
    grid_df voi cac cot moi: suitability_score, suitability_label, suitability_name,
                              classification_method
    """
    if method == 'model':
        result = _classify_by_model(grid_df, available_params, species)
        if result is not None:
            return result
        warnings.warn(
            f"Model not available for '{species}', falling back to scoring.",
            stacklevel=2,
        )

    return _classify_by_scoring(grid_df, available_params, species)


def _classify_by_scoring(grid_df: pd.DataFrame, available_params: list,
                          species: str) -> pd.DataFrame:
    """Rule-based classification using breakpoints + weighted scoring."""
    thresholds = _load_thresholds(species)

    usable_params = [p for p in available_params if p in thresholds]
    if not usable_params:
        grid_df = grid_df.copy()
        grid_df['suitability_score'] = 0.5
        grid_df['suitability_label'] = 1
        grid_df['suitability_name'] = LABEL_NAMES[1]
        grid_df['classification_method'] = 'scoring'
        return grid_df

    # Tinh trong so (re-normalize cho tap con params co san)
    max_rank = max(thresholds[p]['importance_rank'] for p in usable_params)
    raw_weights = {}
    for p in usable_params:
        rank = thresholds[p]['importance_rank']
        raw_weights[p] = max_rank + 1 - rank
    total_w = sum(raw_weights.values())
    weights = {p: w / total_w for p, w in raw_weights.items()}

    # Tinh diem cho tung o
    scores = np.zeros(len(grid_df))
    for p in usable_params:
        bps = thresholds[p]['breakpoints']
        w = weights[p]
        vals = grid_df[p].values
        param_scores = np.array([_score_param(v, bps) for v in vals])
        scores += param_scores * w

    # Use species-specific label thresholds
    spec = SPECIES[species]
    label_thresholds = spec.get('label_thresholds')
    labels = np.array([_score_to_label(s, label_thresholds) for s in scores])

    grid_df = grid_df.copy()
    grid_df['suitability_score'] = scores
    grid_df['suitability_label'] = labels
    grid_df['suitability_name'] = [LABEL_NAMES[l] for l in labels]
    grid_df['classification_method'] = 'scoring'

    return grid_df

def _classify_by_model(grid_df: pd.DataFrame, available_params: list,
                        species: str) -> pd.DataFrame | None:
    """XGBoost classifier-based classification.

    Returns None if model is not available or params are insufficient.
    """
    loaded = _load_model(species)
    if loaded is None:
        return None

    (model, _label_to_idx, idx_to_label), meta = loaded
    feature_names = meta['feature_names']

    # Check if all required features are available in grid_df
    missing = [f for f in feature_names if f not in grid_df.columns]
    if missing:
        warnings.warn(
            f"Model requires {missing} but grid_df is missing them. "
            f"Falling back to scoring.",
            stacklevel=2,
        )
        return None

    grid_df = grid_df.copy()

    # Prepare feature matrix (same column order as training)
    X = grid_df[feature_names].values

    # Predict (works for both base models and EnsembleClassifier)
    y_encoded = model.predict(X).flatten()
    labels = np.array([idx_to_label[int(i)] for i in y_encoded])

    # Also compute probability-based score (max probability)
    probas = model.predict_proba(X)
    scores = probas.max(axis=1)

    grid_df['suitability_score'] = scores
    grid_df['suitability_label'] = labels
    grid_df['suitability_name'] = [LABEL_NAMES[l] for l in labels]
    grid_df['classification_method'] = 'model'

    return grid_df
