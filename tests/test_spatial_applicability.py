import pandas as pd

from experiments.spatial_applicability import (
    cobia_hsi, legacy_local_radius, observed_hsi_radius_diagnostic,
    pairwise_anchor_copy, prepare_source, station_catalog, temporal_error_bound_benchmark,
    spatial_gate_summary,
)


def _frame():
    return prepare_source(pd.DataFrame({
        "Station": ["A", "B", "C", "A", "B", "C"],
        "Quarter": ["2024-01-01"] * 3 + ["2024-04-01"] * 3,
        "X": [0, 500, 2500, 0, 500, 2500], "Y": [0] * 6,
        "DO": [6.0, 5.8, 2.0, 6.1, 5.9, 2.1],
        "Temperature": [26.0] * 6, "pH": [8.2] * 6, "Salinity": [30.0] * 6,
        "NH3": [.01] * 6, "TSS": [10.0] * 6,
    }))


def test_anchor_copy_builds_directed_same_time_pairs_and_distance():
    pairs = pairwise_anchor_copy(_frame(), "DO")
    assert len(pairs) == 12
    assert set(pairs.columns) >= {"anchor_station", "target_station", "actual", "predicted", "distance_km"}
    assert pairs.distance_km.max() == 2.5


def test_station_catalog_flags_coordinate_changes():
    frame = _frame()
    frame.loc[frame.index[-1], "X"] = 2600
    catalog, findings = station_catalog(frame)
    assert not catalog.loc[catalog.station.eq("C"), "coordinate_consistent"].item()
    assert findings.station.tolist() == ["C"]


def test_legacy_radius_stops_before_different_hsi_label():
    frame = _frame()
    period = frame.loc[frame.observed_at.eq(frame.observed_at.min())].copy()
    period["hsi"] = [0.9, 0.88, 0.3]
    assert legacy_local_radius(period, "A", bin_km=1.0, max_dist_km=10) == 1.0


def test_vectorized_diagnostic_matches_legacy_rule_on_one_period():
    period = _frame().loc[lambda item: item.observed_at.eq(item.observed_at.min())].copy()
    period["hsi"] = period.apply(cobia_hsi, axis=1)
    expected = legacy_local_radius(period, "A", bin_km=1.0, max_dist_km=10)
    radii, _ = observed_hsi_radius_diagnostic(period, bin_km=1.0, max_dist_km=10)
    assert radii.loc[radii.anchor_station.eq("A"), "radius_km"].item() == expected


def test_temporal_error_bound_has_only_future_test_periods():
    station_blocks = []
    for index in range(3):
        block = _frame().copy()
        block["Station"] = block.Station + str(index)
        block["X"] = block.X + index * 3_000
        station_blocks.append(block)
    source = pd.concat(station_blocks, ignore_index=True)
    periods = []
    for offset in range(5):
        item = source.copy()
        item["observed_at"] = item.observed_at + pd.Timedelta(days=90 * offset)
        item["Quarter"] = item.observed_at.astype(str)
        periods.append(item)
    pairs = pairwise_anchor_copy(pd.concat(periods, ignore_index=True), "DO")
    predictions, metrics = temporal_error_bound_benchmark(pairs, "DO")
    assert not predictions.empty
    assert set(metrics.split) == {"forward_temporal"}
    assert predictions.observed_at.min() > pairs.observed_at.quantile(.8)


def test_gate_requires_both_protocols_and_statistical_coverage():
    metrics = pd.DataFrame([
        {"split": "forward_temporal", "parameter": "DO", "model": "distance_bin_quantile_conformal", "distance_bin_km": "(2, 5]", "n_pairs": 100, "coverage_target": .9, "empirical_coverage": 1.0},
        {"split": "leave_target_station_out", "parameter": "DO", "model": "distance_bin_quantile_conformal", "distance_bin_km": "(2, 5]", "n_pairs": 100, "coverage_target": .9, "empirical_coverage": 1.0},
        {"split": "forward_temporal", "parameter": "DO", "model": "distance_bin_quantile_conformal", "distance_bin_km": "(5, 10]", "n_pairs": 10, "coverage_target": .9, "empirical_coverage": 1.0},
    ])
    result = spatial_gate_summary(metrics, min_pairs=30)
    assert result.loc[result.distance_bin_km.eq("(2, 5]"), "gate_status"].item() == "shadow_candidate"
    assert result.loc[result.distance_bin_km.eq("(5, 10]"), "gate_status"].item() == "not_applicable"
