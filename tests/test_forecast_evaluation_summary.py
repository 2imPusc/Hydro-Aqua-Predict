from core import forecast_evaluation


def test_ledger_summary_is_empty_without_runtime_files(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast_evaluation, "FORECAST_LOG", tmp_path / "forecasts.jsonl")
    monkeypatch.setattr(forecast_evaluation, "OUTCOME_LOG", tmp_path / "outcomes.jsonl")
    summary = forecast_evaluation.ledger_summary()
    assert summary["forecast_records"] == 0
    assert summary["outcome_records"] == 0
    assert summary["metrics"] == []
