"""
Common scoring utilities for suitability classification.
Used by both runtime classification (src/classification.py)
and training scripts (model/train_*.py).
"""
import numpy as np


def score_param(value, breakpoints):
    """Tinh diem 1 chi so dua tren breakpoints (piecewise linear).

    Parameters
    ----------
    value : float
        Gia tri chi so can tinh diem.
    breakpoints : list of (x, y)
        Danh sach cac diem (gia_tri, diem_so), sap xep theo gia_tri tang dan.

    Returns
    -------
    float : diem so trong khoang [0, 1]
    """
    if np.isnan(value):
        return 0.5

    bps = sorted(breakpoints, key=lambda x: x[0])
    if value <= bps[0][0]:
        return bps[0][1]
    if value >= bps[-1][0]:
        return bps[-1][1]

    for i in range(len(bps) - 1):
        x0, y0 = bps[i]
        x1, y1 = bps[i + 1]
        if x0 <= value <= x1:
            if x1 == x0:
                return y1
            t = (value - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return 0.5


DEFAULT_LABEL_THRESHOLDS = (0.60, 0.72)


def score_to_label(score, thresholds=None):
    """Chuyen diem phu hop → nhan phan loai 3 lop.

    Parameters
    ----------
    score : float
    thresholds : tuple of (lo, hi), optional
        Species-specific thresholds. Defaults to (0.60, 0.72).

    Returns
    -------
    int : 0 (Khong phu hop), 1 (Phu hop), 2 (Rat phu hop)
    """
    lo, hi = thresholds if thresholds else DEFAULT_LABEL_THRESHOLDS
    if score < lo:
        return 0
    elif score < hi:
        return 1
    else:
        return 2


def compute_importance_weights(criteria):
    """Tinh trong so tu importance_rank (rank 1 = quan trong nhat).

    Parameters
    ----------
    criteria : dict
        {param_name: {'importance_rank': int, ...}, ...}

    Returns
    -------
    dict : {param_name: weight} da normalize tong = 1
    """
    max_rank = max(c['importance_rank'] for c in criteria.values())
    raw_weights = {}
    for name, c in criteria.items():
        raw_weights[name] = max_rank + 1 - c['importance_rank']
    total = sum(raw_weights.values())
    return {name: w / total for name, w in raw_weights.items()}
