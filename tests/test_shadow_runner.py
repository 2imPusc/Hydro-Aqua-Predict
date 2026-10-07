import pandas as pd
import pytest
from core import shadow_runner
from core.forecast_evaluation import _read_jsonl
from core.shadow_runner import RISK_LOG

def test_shadow_runner_skips_legacy_pipeline(monkeypatch):
    raw = pd.DataFrame({"fetchedAt": [pd.Timestamp.now(tz="UTC")], "Temperature": [29.], "pH": [7.8], "NH4": [.1], "TSS": [10.]})
    monkeypatch.setattr(shadow_runner, "fetch_raw", lambda station: raw)
    monkeypatch.setattr(shadow_runner, "get_station_weather", lambda station: {"status": "ready"})
    monkeypatch.setattr(shadow_runner, "forecast_sensor_first", lambda raw, station: {"status": "ready"})
    monkeypatch.setattr(shadow_runner, "record_sensor_future", lambda station, future, weather, advisory: 3)
    monkeypatch.setattr(shadow_runner, "record_risk_decision", lambda s, f, w, wa: 1)
    monkeypatch.setattr(shadow_runner, "resolve_sensor_outcomes", lambda raw: 1)
    monkeypatch.setattr(shadow_runner, "sensor_metrics", lambda: [])
    result = shadow_runner.run_once("06M26042804")
    assert result["status"] == "ready"
    assert result["issued_records"] == 4

def test_missing_data_returns_early(monkeypatch):
    monkeypatch.setattr(shadow_runner, "fetch_raw", lambda station: pd.DataFrame())
    result = shadow_runner.run_once("06M26042804")
    assert result["status"] == "no_data"

def test_stale_data_returns_early(monkeypatch):
    raw = pd.DataFrame({"fetchedAt": [pd.Timestamp("2026-01-01", tz="UTC")], "Temperature": [29.]})
    monkeypatch.setattr(shadow_runner, "fetch_raw", lambda station: raw)
    result = shadow_runner.run_once("06M26042804")
    assert result["status"] == "stale_sensor_data"

def test_risk_decision_logic(monkeypatch, tmp_path):
    monkeypatch.setattr(shadow_runner, "RISK_LOG", tmp_path / "risk_decisions.jsonl")
    shadow_runner.record_risk_decision("06M26042804", {}, {"severity": "UNAVAILABLE"}, {"severity": "WARNING", "drivers": [{"metric": "pH"}]})
    records = _read_jsonl(tmp_path / "risk_decisions.jsonl")
    assert len(records) == 1
    assert records[0]["combined_severity"] == "WARNING"
    assert records[0]["data_quality"] == "partial"
    assert not records[0]["notification_sent"]

def test_risk_decision_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(shadow_runner, "RISK_LOG", tmp_path / "risk_decisions.jsonl")
    future = {"base_timestamp": "2026-09-01T00:00:00Z"}
    shadow_runner.record_risk_decision("06M26042804", future, {"severity": "NORMAL"}, {"severity": "NORMAL"})
    shadow_runner.record_risk_decision("06M26042804", future, {"severity": "NORMAL"}, {"severity": "NORMAL"})
    records = _read_jsonl(tmp_path / "risk_decisions.jsonl")
    assert len(records) == 1
