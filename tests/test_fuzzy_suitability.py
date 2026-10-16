import numpy as np
import pandas as pd
import pytest

from hap_shared.fuzzy_suitability import (
    COBIA_RANGES, GHADERI_WEIGHTS, direction_stability, distance_membership, integrate, minmax,
    temporal_score, triangular,
)


def test_triangular_shape_and_nan():
    mu = triangular([0.0, 0.25, 0.5, 0.75, 1.0, 1.5, np.nan], *COBIA_RANGES["SWH"])
    assert mu[:6].tolist() == [0.0, 0.5, 1.0, 0.5, 0.0, 0.0]
    assert np.isnan(mu[6])


def test_triangular_is_monotone_up_to_optimum_and_continuous_near_threshold():
    x = np.linspace(16.8, 24.5, 50)
    assert np.all(np.diff(triangular(x, *COBIA_RANGES["SST"])) >= 0)
    near = triangular([32.19, 32.21], *COBIA_RANGES["SST"])
    assert abs(near[0] - near[1]) < 0.01  # no jump at the threshold


def test_triangular_handles_optimum_on_the_edge():
    assert triangular([0.0, 1.0, 2.0], 0.0, 0.0, 2.0).tolist() == [1.0, 0.5, 0.0]


def test_temporal_score_is_fraction_of_time_in_good_range():
    values = pd.DataFrame({"a": [0.5, 0.5, 2.0, 2.0], "b": [0.25, 0.75, np.nan, 0.5]})
    score = temporal_score(values, *COBIA_RANGES["SWH"])
    assert score["a"] == 0.5
    assert score["b"] == pytest.approx((0.5 + 0.5 + 1.0) / 3)


def test_direction_stability_wraps_across_north():
    steady = pd.DataFrame({"p": [350.0, 10.0, 350.0]})   # +-20 deg across 0/360
    flipping = pd.DataFrame({"p": [0.0, 180.0, 0.0]})
    assert direction_stability(steady)["p"] == pytest.approx(1 - 20 / 180)
    assert direction_stability(flipping)["p"] == pytest.approx(0.0)


def test_distance_membership_direction():
    d = [0.0, 5.0, 10.0]
    assert distance_membership(d, closer_is_better=True).tolist() == [1.0, 0.5, 0.0]
    assert distance_membership(d, closer_is_better=False).tolist() == [0.0, 0.5, 1.0]


def test_minmax_constant_is_zero():
    assert minmax([2.0, 2.0]).tolist() == [0.0, 0.0]


def test_integrate_sum_product_gamma():
    scores = pd.DataFrame({"DEP": [1.0, 0.5, 0.0], "SCS": [1.0, 0.5, 1.0]})
    assert integrate(scores, 0.0).tolist() == [1.0, 0.5, 0.5]           # SUM = mean
    assert integrate(scores, 1.0).tolist() == pytest.approx([1.0, 0.5, 0.0])  # PRODUCT kills any zero
    g = integrate(scores, 0.8)
    assert g.iloc[2] == pytest.approx(0.2 * 0.5)


def test_integrate_weights_renormalised_to_present_columns():
    scores = pd.DataFrame({"DEP": [1.0], "SCS": [0.0]})
    w = integrate(scores, 0.0, GHADERI_WEIGHTS).iloc[0]
    assert w == pytest.approx(0.243 / (0.243 + 0.221))
