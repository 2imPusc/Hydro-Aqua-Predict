import numpy as np
import pandas as pd

from experiments.nh4_basis_evidence import (
    N_FACTOR_ION,
    bayes_factor,
    bootstrap_bayes_factor,
    grid_resolution,
    implied_scale,
    ise_interference_mg_n,
    qcvn_band,
)


def test_grid_resolution_detects_hundredths():
    res = grid_resolution(np.array([77.84, 77.59, 105.0, 0.04]))
    assert res["resolution"] == 0.01
    assert res["share_on_grid"][0.1] < 1.0


def test_grid_resolution_averaged_values_fall_to_thousandths():
    res = grid_resolution(np.array([5.325, 5.3, 4.66]))
    assert res["resolution"] == 0.001


def test_bayes_factor_favours_level_nearer_geometric_mean():
    samples = np.exp(np.random.default_rng(0).normal(np.log(0.1), 0.3, 200))
    assert bayes_factor(0.1, 0.1 * N_FACTOR_ION, samples) > 1
    assert bayes_factor(0.1 * N_FACTOR_ION, 0.1, samples) < 1
    # symmetric levels around the geometric mean are equally likely up to the 1/x Jacobian
    gm = float(np.exp(np.log(samples).mean()))
    assert abs(np.log(bayes_factor(gm * 1.2, gm / 1.2, samples)) + np.log(1.44)) < 0.05


def test_bootstrap_bayes_factor_ci_brackets_point_estimate():
    samples = np.exp(np.random.default_rng(1).normal(np.log(0.09), 0.4, 24))
    out = bootstrap_bayes_factor(0.107, 0.083, samples, n_boot=300)
    assert out["bf_p025"] <= out["bf_p50"] <= out["bf_p975"]
    assert out["n_samples"] == 24


def test_implied_scale_recovers_geometric_mean_ratio():
    samples = np.array([0.05, 0.1, 0.2])
    out = implied_scale(100.0, samples, n_boot=200)
    assert abs(out["k_hat"] - 0.001) < 1e-12
    assert out["k_p025"] <= out["k_hat"] <= out["k_p975"]


def test_ise_interference_order_of_magnitude():
    # K+ 10.2 mM × 10^-1 + Na+ 469 mM × 10^-3 ≈ 1.49 mM ≈ 20.9 mg/L N at S = 35
    assert abs(ise_interference_mg_n(35.0, -1.0, -3.0) - 20.9) < 0.2
    assert ise_interference_mg_n(17.5, -1.0, -3.0) == ise_interference_mg_n(35.0, -1.0, -3.0) / 2


def test_qcvn_band_three_states():
    n = pd.Series([0.14, 0.11, 0.09])
    ion = n * N_FACTOR_ION
    assert list(qcvn_band(n, ion)) == ["vượt (cả hai cơ sở)", "không xác định (tuỳ cơ sở)", "dưới ngưỡng (cả hai cơ sở)"]
