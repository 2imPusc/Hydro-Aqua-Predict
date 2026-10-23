import numpy as np
import pytest
import pandas as pd
from shapely.geometry import LineString, Point, box

from experiments.suitability_hk import (
    auc, label_zones, nearest_index, paired_zone_bootstrap_diff, parse_censored, polygon_from_lines, sea_faces, zone_bootstrap_auc,
    zone_percentiles, zones_in_top,
)


def test_parse_censored_uses_half_loq():
    out = parse_censored(pd.Series(["<0.001", "0.004", "3", None, "<0.5", "n/a"]))
    np.testing.assert_allclose(out.to_numpy()[:3], [0.0005, 0.004, 3.0])
    assert np.isnan(out.iloc[3]) and np.isnan(out.iloc[5])
    assert out.iloc[4] == 0.25


def test_nearest_index_maps_fine_to_coarse():
    coarse = np.array([[0.0, 0.0], [10.0, 0.0]])
    fine = np.array([[1.0, 0.0], [6.0, 1.0], [9.0, -1.0]])
    assert nearest_index(fine, coarse).tolist() == [0, 1, 1]


def test_label_zones_inside_or_within_distance():
    xy = np.array([[0.5, 0.5], [1.5, 0.5], [3.0, 0.5], [10.0, 10.0]])
    zones = {"z1": box(0, 0, 1, 1), "z2": box(9.5, 9.5, 10.5, 10.5)}
    cells = label_zones(xy, zones, max_dist=0.6)
    assert cells["z1"].tolist() == [0, 1]
    assert cells["z2"].tolist() == [3]


def test_label_zones_empty_when_no_cell_near():
    cells = label_zones(np.array([[50.0, 50.0]]), {"z": box(0, 0, 1, 1)}, max_dist=1.0)
    assert cells["z"].size == 0


def test_auc_perfect_and_ties():
    assert auc(np.array([3.0, 4.0]), np.array([1.0, 2.0])) == 1.0
    assert auc(np.array([1.0]), np.array([1.0, 1.0])) == 0.5


def test_zone_bootstrap_auc_perfect_separation():
    scores = np.array([0.9, 0.95, 0.8, 0.85, 0.1, 0.2, 0.3, 0.4])
    zone_cells = {"a": np.array([0, 1]), "b": np.array([2, 3])}
    neg = np.array([False] * 4 + [True] * 4)
    point, lo, hi = zone_bootstrap_auc(scores, zone_cells, neg, n_boot=200, seed=0)
    assert point == 1.0 and lo == 1.0 and hi == 1.0


def test_zone_bootstrap_auc_random_labels_near_half():
    rng = np.random.default_rng(1)
    scores = rng.random(2000)
    zone_cells = {f"z{i}": np.arange(i * 20, i * 20 + 20) for i in range(30)}
    neg = np.ones(2000, dtype=bool)
    neg[:600] = False
    point, lo, hi = zone_bootstrap_auc(scores, zone_cells, neg, n_boot=300, seed=0)
    assert abs(point - 0.5) < 0.05 and lo < 0.5 < hi


def test_zone_percentiles_and_top_counts():
    pct = np.array([0.95, 0.85, 0.55, 0.75, 0.1])
    zone_cells = {"a": np.array([0, 1]), "b": np.array([2, 3]), "c": np.array([4]), "d": np.array([], dtype=int)}
    zp = zone_percentiles(pct, zone_cells)
    assert zp["a"] == pytest.approx(0.9) and zp["b"] == pytest.approx(0.65) and np.isnan(zp["d"])
    assert zones_in_top(zp, 0.2) == 1
    assert zones_in_top(zp, 0.4) == 2


def test_polygon_from_lines_closes_ring_split_in_two_ways():
    ways = [LineString([(0, 0), (2, 0), (2, 2)]), LineString([(2, 2), (0, 2), (0, 0)])]
    poly = polygon_from_lines(ways)
    assert abs(poly.area - 4.0) < 1e-9


def test_sea_faces_keeps_faces_with_seed():
    bbox = (0.0, 0.0, 4.0, 2.0)
    coast = [LineString([(2, -1), (2, 3)])]  # splits the box into a west and an east face
    sea = sea_faces(coast, bbox, seeds=[Point(3, 1)])
    assert sea.contains(Point(3.5, 0.5)) and not sea.contains(Point(1, 1))


def test_paired_zone_bootstrap_diff_identical_and_better():
    rng = np.random.default_rng(2)
    base = rng.random(400)
    zone_cells = {f"z{i}": np.arange(i * 5, i * 5 + 5) for i in range(20)}
    neg = np.ones(400, dtype=bool)
    neg[:100] = False
    d, lo, hi = paired_zone_bootstrap_diff(base, base, zone_cells, neg, n_boot=100, seed=0)
    assert d == 0.0 and lo == 0.0 and hi == 0.0
    better = base.copy()
    better[:100] += 1.0  # every FCZ cell now outranks every other cell
    d, lo, hi = paired_zone_bootstrap_diff(better, base, zone_cells, neg, n_boot=200, seed=0)
    assert d > 0.4 and lo > 0.3 and hi <= 0.5 + 0.1
