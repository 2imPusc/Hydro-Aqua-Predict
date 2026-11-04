import json
from pathlib import Path

import numpy as np
import pandas as pd

from experiments import storm_wind_calibration as swc


def _passages():
    rng = np.random.default_rng(0)
    n = 40
    model = rng.uniform(5, 30, n)
    dist = np.where(np.arange(n) % 2 == 0, 50.0, 200.0)
    obs = np.where(dist <= 100, 0.8, 0.5) * model
    return pd.DataFrame({"SID": [f"S{i // 2}" for i in range(n)], "SEASON": 2000 + (np.arange(n) % 10),
                         "min_dist_km": dist, "model_max_ms": model, "obs_max_ms": obs})


def test_fit_and_apply_variants():
    df = _passages()
    params = swc.fit_variants(df)
    assert abs(params["C2"]["k_near"] - 0.8) < 1e-9 and abs(params["C2"]["k_far"] - 0.5) < 1e-9
    assert np.allclose(swc.apply_variant(df, "C2", params), df["obs_max_ms"])
    assert np.allclose(swc.apply_variant(df, "C0", params), df["model_max_ms"])
    cv = swc.loso_cv(df)
    assert cv["C2"] < 1e-9 < cv["C1"]


def test_bootstrap_and_sign_test():
    df = _passages()
    good, bad = df["obs_max_ms"] + 0.1, df["obs_max_ms"] + 2.0
    b = swc.cluster_bootstrap(df, good, bad, 200, 1)
    assert b["point"] < 0 and b["p95"] < 0 and b["n_storms"] == 20
    s = swc.sign_test(df, good, bad)
    assert s["storms_better"] == 20 and s["p_two_sided"] < 1e-5


def test_tier_stats():
    obs = pd.Series([7, 8, 10, 5])
    pred = pd.Series([8, 8, 9, 5])
    t = swc.tier_stats(obs, pred, {"1": 6, "2": 8, "3": 10, "4": 12})
    assert t["tier_exact_agreement"] == 0.5
    assert t["pod_ge8"] == 1.0 and abs(t["far_ge8"] - 1 / 3) < 1e-9 and t["pod_ge10"] == 0.0


def test_proposed_thresholds_respects_guardrails():
    spec = json.loads((Path(swc.DEFAULT_CONFIG)).read_text(encoding="utf-8"))["hazards"]["storm_wind"]
    assert swc.proposed_thresholds(1.0, spec) == {"1": 6, "2": 8, "3": 10, "4": 12}
    up = swc.proposed_thresholds(0.5, spec)  # model twice too strong -> higher raw thresholds, clipped
    assert up == {k: spec["guardrails"]["max"][k] for k in up}
    down = swc.proposed_thresholds(2.0, spec)
    assert down == {k: spec["guardrails"]["min"][k] for k in down}
