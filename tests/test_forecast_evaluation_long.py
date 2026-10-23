"""Long-horizon (3/6/12 h) shadow ledger: issuance, resolution, PI coverage."""
import json

import pandas as pd
import pytest

from core import forecast_evaluation as fe


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(fe, "LONG_FORECAST_LOG", tmp_path / "long_forecasts.jsonl")
    monkeypatch.setattr(fe, "LONG_OUTCOME_LOG", tmp_path / "long_outcomes.jsonl")
    monkeypatch.setattr(fe, "LONG_SKIP_LOG", tmp_path / "long_skips.jsonl")
    fe._reset_long_cache()
    yield tmp_path
    fe._reset_long_cache()


def _record(issued="2026-10-16T00:00:00+00:00", horizon=180, target="Temperature", value=29.0, q80=0.5, q90=0.8, status="ok", version="v1"):
    issued_at = pd.Timestamp(issued)
    return {
        "station_serial": "06M26042804", "issued_at": issued_at.isoformat(),
        "valid_at": (issued_at + pd.Timedelta(minutes=horizon)).isoformat(), "horizon_minutes": horizon,
        "target": target, "feature_set": "B4_quality", "model_version": version, "forecast": value, "current": 28.5,
        "pi": {"method": "aci_scaled", "night": 0, "pi80": {"q": q80, "lower": value - q80, "upper": value + q80},
               "pi90": {"q": q90, "lower": value - q90, "upper": value + q90}},
        "sensor_status": status,
    }


def _raw(times, temperature=29.3, ph=7.9):
    return pd.DataFrame({"fetchedAt": pd.to_datetime(times, utc=True), "Temperature": temperature, "pH": ph, "NH4": 60.0, "TSS": 10.0})


def test_append_is_idempotent_and_shadow_only(ledger):
    assert fe.append_long_forecast(_record()) is True
    assert fe.append_long_forecast(_record()) is False
    rows = fe._read_jsonl(fe.LONG_FORECAST_LOG)
    assert len(rows) == 1
    assert rows[0]["mode"] == "shadow" and rows[0]["used_by_alerts"] is False and rows[0]["notification_eligible"] is False
    assert rows[0]["schema_version"] == "sensor-future-long-v1"


def test_resolution_uses_two_minute_alignment_and_records_coverage(ledger):
    fe.append_long_forecast(_record(value=29.0))
    raw = _raw(["2026-10-16T02:58:00Z", "2026-10-16T03:01:30Z", "2026-10-16T03:10:00Z"], temperature=[1.0, 29.6, 1.0])
    assert fe.resolve_long_outcomes(raw) == 1
    outcome = fe._read_jsonl(fe.LONG_OUTCOME_LOG)[0]
    assert outcome["status"] == "scored"
    assert outcome["actual"] == 29.6
    assert outcome["observed_at"] == "2026-10-16T03:01:30+00:00"
    assert outcome["known_at"] == "2026-10-16T03:01:30+00:00"
    assert outcome["abs_error"] == pytest.approx(0.6)
    assert outcome["covered"] == {"pi80": False, "pi90": True}
    assert fe.resolve_long_outcomes(raw) == 0


def test_not_due_and_no_observation(ledger):
    fe.append_long_forecast(_record())
    assert fe.resolve_long_outcomes(_raw(["2026-10-16T02:50:00Z"])) == 0
    # raw covers the valid window but has no reading within 2 minutes
    assert fe.resolve_long_outcomes(_raw(["2026-10-16T02:50:00Z", "2026-10-16T03:05:00Z"])) == 1
    outcome = fe._read_jsonl(fe.LONG_OUTCOME_LOG)[0]
    assert outcome["status"] == "no_observation"
    assert "actual" not in outcome


def test_suspect_ph_is_resolved_but_excluded(ledger):
    fe.append_long_forecast(_record(target="pH", value=7.0, status="ph_probe_suspect", version="ph1"))
    fe.append_long_forecast(_record(issued="2026-10-16T00:01:00+00:00", target="pH", value=7.0, status="ok", version="ph1"))
    raw = _raw(["2026-10-16T03:00:00Z", "2026-10-16T03:01:00Z", "2026-10-16T03:05:00Z"], ph=6.8)
    assert fe.resolve_long_outcomes(raw) == 2
    outcomes = fe._read_jsonl(fe.LONG_OUTCOME_LOG)
    assert {o["status"] for o in outcomes} == {"excluded_sensor_suspect"}
    assert {o["excluded_reason"] for o in outcomes} == {"input_ph_probe_suspect", "actual_ph_outside_plausible_band"}
    assert fe.matured_outcomes("ph1", pd.Timestamp("2026-10-17", tz="UTC")) == []
    metric = fe.long_metrics()[0]
    assert metric["n_scored"] == 0 and metric["n_excluded"] == 2


def test_matured_outcomes_are_causal(ledger):
    fe.append_long_forecast(_record(value=29.0))
    fe.resolve_long_outcomes(_raw(["2026-10-16T03:00:00Z", "2026-10-16T03:05:00Z"], temperature=29.2))
    assert fe.matured_outcomes("v1", pd.Timestamp("2026-10-16T02:59:59", tz="UTC")) == []
    matured = fe.matured_outcomes("v1", pd.Timestamp("2026-10-16T03:00:00", tz="UTC"))
    assert len(matured) == 1
    assert matured[0]["abs_error"] == pytest.approx(0.2)


def test_metrics_include_coverage_and_width(ledger):
    for minute, actual in enumerate([29.1, 29.4, 29.7, 30.5]):
        issued = pd.Timestamp("2026-10-16T00:00", tz="UTC") + pd.Timedelta(minutes=minute)
        fe.append_long_forecast(_record(issued=issued.isoformat(), value=29.0))
    times = [pd.Timestamp("2026-10-16T03:00", tz="UTC") + pd.Timedelta(minutes=m) for m in range(4)] + [pd.Timestamp("2026-10-16T03:20", tz="UTC")]
    fe.resolve_long_outcomes(_raw(times, temperature=[29.1, 29.4, 29.7, 30.5, 29.0]))
    metric = fe.long_metrics()[0]
    assert metric["n_scored"] == 4
    assert metric["coverage_pi80"] == pytest.approx(0.5)
    assert metric["coverage_pi90"] == pytest.approx(0.75)
    assert metric["mean_width_pi80"] == pytest.approx(1.0)
    assert metric["mae"] == pytest.approx((0.1 + 0.4 + 0.7 + 1.5) / 4)
    assert metric["persistence_mae"] == pytest.approx((0.6 + 0.9 + 1.2 + 2.0) / 4)


def test_index_sees_lines_appended_by_another_process(ledger):
    fe.append_long_forecast(_record())
    with fe.LONG_FORECAST_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"record_id": "external", **_record(issued="2026-10-16T00:05:00+00:00")}) + "\n")
    assert fe.append_long_forecast(_record(issued="2026-10-16T00:05:00+00:00")) is True  # different id: external line has a foreign id
    assert len(fe._long_index(fe.LONG_FORECAST_LOG).records) == 3


def test_skip_log_deduplicates_per_hour(ledger):
    skip = {"station_serial": "06M26042804", "issued_at": "2026-10-16T00:00:00+00:00", "target": "Temperature", "horizon_minutes": 180,
            "feature_set": "B5_external_as_issued", "model_version": "v1", "reason": "no_captured_live_snapshot_within_24h"}
    assert fe.append_long_skip(skip) is True
    assert fe.append_long_skip({**skip, "issued_at": "2026-10-16T00:30:00+00:00"}) is False
    assert fe.append_long_skip({**skip, "issued_at": "2026-10-16T01:00:00+00:00"}) is True
