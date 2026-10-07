import pandas as pd

from core import forecast_evaluation


def test_forecast_ledger_records_and_resolves_sensor_actual(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast_evaluation, "STORE_DIR", tmp_path)
    monkeypatch.setattr(forecast_evaluation, "FORECAST_LOG", tmp_path / "forecasts.jsonl")
    monkeypatch.setattr(forecast_evaluation, "OUTCOME_LOG", tmp_path / "outcomes.jsonl")
    future = {"status": "ready", "base_timestamp": "2026-07-01T00:00:00+00:00", "timeline": [{"horizon_minutes": 15, "timestamp": "2026-07-01T00:15:00+00:00", "sensors": {"Temperature": 30., "pH": 7.8, "NH4": .1, "TSS": 10.}, "sensor_sources": {"Temperature": "xgboost_time", "pH": "persistence", "NH4": "persistence", "TSS": "persistence"}, "inferred": {}, "contextual_status": "disabled"}]}
    advisory = {"timeline": [{"horizon_minutes": 15, "severity": "WATCH", "drivers": [{"metric": "DO", "value": 4.8}]}]}
    assert forecast_evaluation.record_sensor_future("06M26042804", future, {"status": "ready", "provider": "open_meteo"}, advisory) == 1
    assert forecast_evaluation.record_sensor_future("06M26042804", future) == 0
    assert forecast_evaluation._read_jsonl(forecast_evaluation.FORECAST_LOG)[0]["risk_advisory"]["severity"] == "WATCH"
    raw = pd.DataFrame([{ "fetchedAt": "2026-07-01T00:15:30Z", "Temperature": 30.2, "pH": 7.7, "NH4": .11, "TSS": 11}])
    assert forecast_evaluation.resolve_sensor_outcomes(raw) == 1
    metric = forecast_evaluation.sensor_metrics()
    assert len(metric) == 4
    assert next(row for row in metric if row["param"] == "Temperature")["n"] == 1


def test_latest_advisory_state_survives_runner_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast_evaluation, "STORE_DIR", tmp_path)
    monkeypatch.setattr(forecast_evaluation, "FORECAST_LOG", tmp_path / "forecasts.jsonl")
    future = {"status": "ready", "base_timestamp": "2026-07-01T00:00:00+00:00", "timeline": [{"horizon_minutes": 15, "timestamp": "2026-07-01T00:15:00+00:00", "sensors": {}, "sensor_sources": {}, "inferred": {}}]}
    advisory = {"severity": "WARNING", "do_risk_count": 2, "notification_eligible": True, "used_by_emergency": False}
    forecast_evaluation.record_sensor_future("06M26042804", future, advisory=advisory)
    assert forecast_evaluation.latest_advisory_state("06M26042804")["do_risk_count"] == 2
