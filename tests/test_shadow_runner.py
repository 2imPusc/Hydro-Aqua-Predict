import pandas as pd
import pytest
from core import shadow_runner
from core.forecast_evaluation import _read_jsonl
from core.shadow_runner import RISK_LOG
from core import forecast_evaluation, forecast_context, sensor_future_long


@pytest.fixture(autouse=True)
def isolated_long_ledger(tmp_path, monkeypatch):
    """No test may touch the real runtime/forecast-shadow long-horizon files."""
    monkeypatch.setattr(forecast_evaluation, "LONG_FORECAST_LOG", tmp_path / "long_forecasts.jsonl")
    monkeypatch.setattr(forecast_evaluation, "LONG_OUTCOME_LOG", tmp_path / "long_outcomes.jsonl")
    monkeypatch.setattr(forecast_evaluation, "LONG_SKIP_LOG", tmp_path / "long_skips.jsonl")
    monkeypatch.setattr(sensor_future_long, "_WEATHER_STORE", forecast_context.CapturedLiveWeather(tmp_path / "no-snapshots.jsonl"))
    monkeypatch.setattr(forecast_context, "get_station_environment", lambda station, weather=None: {"marine": {"status": "disabled", "reason": "marine_disabled"}})
    forecast_evaluation._reset_long_cache()
    yield tmp_path
    forecast_evaluation._reset_long_cache()

def test_shadow_runner_skips_legacy_pipeline(monkeypatch):
    raw = pd.DataFrame({"fetchedAt": [pd.Timestamp.now(tz="UTC")], "Temperature": [29.], "pH": [7.8], "NH4": [.1], "TSS": [10.]})
    monkeypatch.setattr(shadow_runner, "fetch_raw", lambda station: raw)
    monkeypatch.setattr(shadow_runner, "get_station_weather", lambda station: {"status": "ready"})
    monkeypatch.setattr(shadow_runner, "forecast_sensor_first", lambda raw, station: {"status": "ready"})
    monkeypatch.setattr(shadow_runner, "record_sensor_future", lambda station, future, weather, advisory: 3)
    monkeypatch.setattr(shadow_runner, "record_risk_decision", lambda s, f, w, wa: 1)
    monkeypatch.setattr(shadow_runner, "resolve_sensor_outcomes", lambda raw: 1)
    monkeypatch.setattr(shadow_runner, "sensor_metrics", lambda: [])
    monkeypatch.setattr(shadow_runner, "issue_long_horizon", lambda *a, **k: {"status": "ready", "issued": 0})
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


def _mock_legacy(monkeypatch, raw):
    monkeypatch.setattr(shadow_runner, "fetch_raw", lambda station: raw)
    monkeypatch.setattr(shadow_runner, "get_station_weather", lambda station: {"status": "ready"})
    monkeypatch.setattr(shadow_runner, "forecast_sensor_first", lambda raw, station: {"status": "ready"})
    monkeypatch.setattr(shadow_runner, "record_sensor_future", lambda station, future, weather, advisory: 0)
    monkeypatch.setattr(shadow_runner, "record_risk_decision", lambda s, f, w, wa: 0)
    monkeypatch.setattr(shadow_runner, "resolve_sensor_outcomes", lambda raw: 0)
    monkeypatch.setattr(shadow_runner, "sensor_metrics", lambda: [])


def _fresh_raw(end, ph=7.9):
    import numpy as np
    time = pd.date_range(end=end, periods=150, freq="min", tz="UTC")
    raw = pd.DataFrame({"fetchedAt": time, "Temperature": 28 + np.sin(np.arange(150) / 40), "pH": ph, "NH4": 60.0, "TSS": 10.0})
    raw.attrs["data_source"] = "greenlab_api"
    return raw


def test_stale_cache_issues_no_long_horizon_records(monkeypatch, isolated_long_ledger):
    raw = _fresh_raw(pd.Timestamp("2026-10-14T16:58", tz="UTC"))
    raw.attrs["data_source"] = "greenlab_api_cache"
    _mock_legacy(monkeypatch, raw)
    result = shadow_runner.run_once("06M26042804", now=pd.Timestamp("2026-10-16T09:00", tz="UTC"))
    assert result["status"] == "stale_sensor_data"
    assert "long_horizon" not in result
    assert not any(isolated_long_ledger.glob("long_*.jsonl"))


def test_fresh_run_issues_b4_with_and_without_ph_and_logs_skips(monkeypatch, isolated_long_ledger):
    now = pd.Timestamp("2026-10-16T09:00:20", tz="UTC")
    _mock_legacy(monkeypatch, _fresh_raw(now.floor("min")))
    result = shadow_runner.run_once("06M26042804", now=now)
    long_horizon = result["long_horizon"]
    assert long_horizon["status"] == "ready"
    assert long_horizon["issued"] == 6
    assert {s["reason"] for s in long_horizon["skips"]} == {"no_captured_live_snapshot_within_24h", "bundle_withdrawn"}
    issued = _read_jsonl(forecast_evaluation.LONG_FORECAST_LOG)
    assert {r["feature_set"] for r in issued} == {"B4_quality", "B4_quality_nopH"}
    assert all(r["weather_provenance"] is None and r["tide_provenance"] is None for r in issued)
    assert result["issued_records"] == 0  # 15/30/60 counts unchanged by the long-horizon path


def test_long_horizon_error_does_not_break_runner(monkeypatch):
    now = pd.Timestamp("2026-10-16T09:00:20", tz="UTC")
    _mock_legacy(monkeypatch, _fresh_raw(now.floor("min")))
    def boom(*args, **kwargs):
        raise RuntimeError("bad bundle")
    monkeypatch.setattr(shadow_runner, "issue_long_horizon", boom)
    result = shadow_runner.run_once("06M26042804", now=now)
    assert result["status"] == "ready"
    assert result["long_horizon"]["status"] == "error"
