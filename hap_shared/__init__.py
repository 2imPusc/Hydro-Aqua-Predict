"""Shared scoring/preprocessing helpers vendored from DATN-20225064 (src/, commit 9a95cdd).

This package is now owned by Hydro-Aqua-Predict and has no runtime link back to
DATN. Thresholds JSON live in ``hap_shared/thresholds``; the ML classifier
pickles (``_classify_by_model``) are intentionally not vendored, so callers
fall back to rule-based scoring.
"""
