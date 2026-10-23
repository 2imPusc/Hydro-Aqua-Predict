import numpy as np
import pandas as pd

from experiments.imputation_evaluation import evaluate_predictions, nearest_sensor_context, run_evaluation
from experiments.prepare_ground_truth_dataset import prepare_paired_dataset
from experiments.retrospective_imputation import historical_to_evaluation_frame, run_region_batch, run_retrospective, run_time_ablation


def test_metrics_include_error_and_dangerous_false_negative():
    metrics = evaluate_predictions([2.0, 6.0, 7.0], [4.0, 6.0, 4.0], risk_threshold=3.0)
    assert metrics["n"] == 3
    assert metrics["mae"] == 1.6666666666666667
    assert metrics["risk_decision"]["fn"] == 1
    assert metrics["risk_decision"]["fp"] == 0


def test_nearest_context_respects_station_and_tolerance():
    lab = pd.DataFrame({"observed_at": ["2026-07-01T00:05:00Z"], "station_serial": ["A"], "actual": [5.0]})
    sensors = pd.DataFrame({"fetchedAt": ["2026-07-01T00:03:00Z"], "station_serial": ["A"], "pH": [7.8]})
    matched = nearest_sensor_context(lab, sensors, tolerance="5min")
    assert matched.pH.item() == 7.8


def test_temporal_median_evaluation_never_uses_future_rows_to_fit():
    df = pd.DataFrame({
        "observed_at": pd.date_range("2026-01-01", periods=10, freq="D", tz="UTC"),
        "station_serial": ["A"] * 10,
        "actual": np.arange(10, dtype=float),
    })
    result = run_evaluation(df, split="temporal", model="median")
    assert result["metrics"]["n"] == 2
    assert result["predictions"]["predicted"].tolist() == [3.5, 3.5]


def test_prepare_paired_dataset_requires_confirmed_unit_and_reports_unmatched():
    lab = pd.DataFrame({
        "sample_id": ["L1", "L2"], "observed_at": ["2026-07-01T00:05:00Z", "2026-07-01T01:00:00Z"],
        "station_serial": ["A", "A"], "metric": ["DO", "DO"], "value": [5.0, 4.0],
        "unit": ["mg/L", "mg/L"], "method": ["lab", "lab"],
    })
    sensor = pd.DataFrame({"fetchedAt": ["2026-07-01T00:03:00Z"], "station_serial": ["A"], "pH": [7.8]})
    paired, report = prepare_paired_dataset(lab, sensor, target_metric="DO", target_unit="mg/L", tolerance="5min")
    assert len(paired) == 1
    assert report["unmatched_rows"] == 1


def test_retrospective_adapter_keeps_time_station_and_target_explicit():
    source = pd.DataFrame({"Quarter": ["2026-01-01"], "Station": [7], "DO": [5.2], "pH": [7.8]})
    frame = historical_to_evaluation_frame(source, "DO")
    assert frame.station_serial.item() == "7"
    assert frame.actual.item() == 5.2
    assert frame.target_metric.item() == "DO"


def test_retrospective_marks_historical_scope():
    source = pd.DataFrame({
        "Quarter": pd.date_range("2025-01-01", periods=12, freq="QS"),
        "Station": ["A", "B"] * 6, "DO": np.arange(12, dtype=float), "pH": [7.5] * 12,
    })
    result = run_retrospective(source, target="DO")
    assert result["scope"] == "retrospective_historical_not_realtime_ground_truth"


def test_seasonal_and_linear_models_are_available():
    df = pd.DataFrame({
        "observed_at": pd.date_range("2025-01-01", periods=12, freq="QS", tz="UTC"),
        "station_serial": ["A", "B"] * 6, "actual": np.arange(12, dtype=float),
        "pH": np.arange(12, dtype=float),
    })
    for model in ("seasonal_median", "ridge", "elasticnet", "extra_trees"):
        assert run_evaluation(df, split="temporal", model=model)["metrics"]["n"] == 3


def test_batch_returns_inventory_metrics_and_conservative_verdict():
    source = pd.DataFrame({
        "Quarter": pd.date_range("2017-01-01", periods=36, freq="QS"), "Station": ["A", "B"] * 18,
        "DO": np.arange(36, dtype=float), "pH": np.arange(36, dtype=float),
    })
    inventory, metrics, verdicts = run_region_batch(source, region="demo", targets=["DO"], models=("median", "ridge"), splits=("temporal", "station"), known_artifacts=set())
    assert inventory.target.tolist() == ["DO"]
    assert len(metrics) == 4
    assert verdicts.verdict.item() == "contextual_retrospective_candidate"


def test_verdict_selects_lowest_rmse_winner_not_first_model_name():
    from experiments.retrospective_imputation import retrospective_verdict
    inventory = pd.Series({"artifact_suspect": False, "artifact_reason": ""})
    metrics = pd.DataFrame([
        {"status": "evaluated", "model": "median", "split": "temporal", "rmse": 3.0, "r2": -1.0},
        {"status": "evaluated", "model": "median", "split": "station", "rmse": 3.0, "r2": -1.0},
        {"status": "evaluated", "model": "elasticnet", "split": "temporal", "rmse": 2.0, "r2": 0.2},
        {"status": "evaluated", "model": "elasticnet", "split": "station", "rmse": 2.0, "r2": 0.2},
        {"status": "evaluated", "model": "extra_trees", "split": "temporal", "rmse": 1.0, "r2": 0.3},
        {"status": "evaluated", "model": "extra_trees", "split": "station", "rmse": 1.0, "r2": 0.3},
    ])
    verdict, reason = retrospective_verdict(inventory, metrics)
    assert verdict == "contextual_retrospective_candidate"
    assert reason.startswith("extra_trees_")


def test_time_ablation_adds_only_configured_calendar_features(monkeypatch):
    monkeypatch.setattr("core.impute.SEASONALITY_CONFIG", {"demo": {"Salinity": "month"}})
    source = pd.DataFrame({
        "Quarter": pd.date_range("2017-01-01", periods=36, freq="QS"), "Station": ["A", "B"] * 18,
        "Salinity": np.arange(36, dtype=float), "pH": np.arange(36, dtype=float),
    })
    result = run_time_ablation(source, region="demo", target="Salinity", models=("ridge",))
    assert set(result.variant) == {"sensor_only", "sensor_plus_time"}
    assert result[result.variant == "sensor_plus_time"].features.str.contains("month").all()
