"""Issuance of 3/6/12 h shadow forecasts: guards, skips, provenance, PIs."""
import json

import numpy as np
import pandas as pd
import pytest

from core import forecast_context as fc
from core import forecast_evaluation as fe
from core import sensor_future_long as sfl
from core.realtime_guards import assess_sensor_freshness

STATION = "06M26042804"
NOW = pd.Timestamp("2026-10-16T09:00:30", tz="UTC")


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(fe, "LONG_FORECAST_LOG", tmp_path / "long_forecasts.jsonl")
    monkeypatch.setattr(fe, "LONG_OUTCOME_LOG", tmp_path / "long_outcomes.jsonl")
    monkeypatch.setattr(fe, "LONG_SKIP_LOG", tmp_path / "long_skips.jsonl")
    fe._reset_long_cache()
    yield tmp_path
    fe._reset_long_cache()


def _raw(end=NOW.floor("min"), minutes=180, ph=7.9, source="greenlab_api"):
    time = pd.date_range(end=end, periods=minutes, freq="min", tz="UTC")
    n = len(time)
    raw = pd.DataFrame({"fetchedAt": time, "Temperature": 28 + np.sin(np.arange(n) / 40), "pH": ph + .01 * np.cos(np.arange(n) / 30),
                        "NH4": 60 + np.arange(n) % 3, "TSS": 10.0, "COD": 20.0})
    raw.attrs["data_source"] = source
    return raw


def _snap(retrieved, valid, provenance="captured_live"):
    return {"station": STATION, "location_id": "map_station_NB1", "provider": "open_meteo", "product": "open_meteo_forecast",
            "issued_at": retrieved, "retrieved_at": retrieved, "valid_at": valid, "provenance_class": provenance,
            "raw_payload_hash": "abc", "snapshot_id": f"{retrieved}|{valid}",
            "features": {"cloud_cover": 50, "precipitation": 0.0, "relative_humidity_2m": 80, "surface_pressure": 1006.0,
                         "temperature_2m": 27.0, "wind_direction_10m": 100, "wind_speed_10m": 9.0}}


def _snapshots(path, provenance="captured_live"):
    retrieved = (NOW - pd.Timedelta(minutes=40)).isoformat()
    valid_hours = pd.date_range(NOW.floor("h"), periods=16, freq="h", tz="UTC")
    path.write_text("\n".join(json.dumps(_snap(retrieved, v.isoformat(), provenance)) for v in valid_hours) + "\n", encoding="utf-8")
    return fc.CapturedLiveWeather(path)


def _tide_ok(station, weather):
    times = pd.date_range(NOW.floor("D") - pd.Timedelta(hours=7), periods=72, freq="h", tz="UTC")
    return {"status": "ok", "series": pd.DataFrame({"valid_at": times, "sea_level_m": np.sin(np.arange(72) / 4)}),
            "provenance": {"provider": "open_meteo_marine", "variable": "sea_level_height_msl", "retrieved_at": "2026-10-16T08:00:00+00:00", "cache": "miss", "marine_status": "ready"}}


def _tide_disabled(station, weather):
    return {"status": "skip", "reason": "marine_disabled", "marine_status": "disabled"}


def _issue(raw, tmp_path, store=None, tide=_tide_disabled):
    freshness = assess_sensor_freshness(raw, STATION, now=NOW)
    return sfl.issue_long_horizon(raw, STATION, freshness=freshness, now=NOW, weather_store=store or fc.CapturedLiveWeather(tmp_path / "absent.jsonl"), tide_fn=tide)


def test_stale_sensor_data_issues_nothing_and_writes_nothing(ledger):
    raw = _raw(end=pd.Timestamp("2026-07-26T00:00", tz="UTC"))
    result = _issue(raw, ledger, store=_snapshots(ledger / "snaps.jsonl"), tide=_tide_ok)
    assert result["status"] == "blocked"
    assert result["issued"] == 0
    assert not fe.LONG_FORECAST_LOG.exists() and not fe.LONG_SKIP_LOG.exists() and not fe.LONG_OUTCOME_LOG.exists()


def test_stale_fallback_source_issues_nothing(ledger):
    raw = _raw(source="greenlab_api_cache_stale")
    result = _issue(raw, ledger, store=_snapshots(ledger / "snaps.jsonl"), tide=_tide_ok)
    assert result["status"] == "blocked" and result["issued"] == 0
    assert not fe.LONG_FORECAST_LOG.exists()


def test_missing_weather_and_tide_are_logged_skips_not_values(ledger):
    result = _issue(_raw(), ledger)
    assert result["status"] == "ready"
    forecasts = fe._read_jsonl(fe.LONG_FORECAST_LOG)
    assert {(r["target"], r["feature_set"]) for r in forecasts} == {("Temperature", "B4_quality"), ("Temperature", "B4_quality_nopH")}
    assert len(forecasts) == 6
    skips = fe._read_jsonl(fe.LONG_SKIP_LOG)
    assert {(s["feature_set"], s["reason"]) for s in skips} == {
        ("B5_external_as_issued", "no_captured_live_snapshot_within_24h"),
        ("B5_external_as_issued_nopH", "no_captured_live_snapshot_within_24h"),
        ("B4_quality", "bundle_withdrawn"), ("B6_tide", "bundle_withdrawn"),
    }
    assert len(skips) == 12
    assert all(s["issued_at"] for s in skips)


def test_reconstructed_snapshots_never_feed_b5(ledger):
    _issue(_raw(), ledger, store=_snapshots(ledger / "snaps.jsonl", provenance="reconstructed_run"))
    assert not any(r["feature_set"] == "B5_external_as_issued" for r in fe._read_jsonl(fe.LONG_FORECAST_LOG))
    assert any(s["feature_set"] == "B5_external_as_issued" for s in fe._read_jsonl(fe.LONG_SKIP_LOG))


def test_full_issue_has_provenance_pi_and_freshness(ledger):
    result = _issue(_raw(), ledger, store=_snapshots(ledger / "snaps.jsonl"), tide=_tide_ok)
    assert result["issued"] == 12 and result["skipped"] == 6
    assert {s["reason"] for s in result["skips"]} == {"bundle_withdrawn"}
    forecasts = fe._read_jsonl(fe.LONG_FORECAST_LOG)
    origin = NOW.floor("min").isoformat()
    for record in forecasts:
        assert record["issued_at"] == origin
        assert pd.Timestamp(record["valid_at"]) - pd.Timestamp(origin) == pd.Timedelta(minutes=record["horizon_minutes"])
        assert record["horizon_minutes"] in (180, 360, 720)
        assert record["model_version"].startswith(f"haiphong_{record['target'].lower()}_ridge_{record['feature_set']}")
        assert np.isfinite(record["forecast"])
        for level in ("pi80", "pi90"):
            band = record["pi"][level]
            assert band["lower"] <= record["forecast"] <= band["upper"]
        assert record["pi"]["pi90"]["q"] >= record["pi"]["pi80"]["q"]
        assert record["data_source"] == "greenlab_api"
        assert record["input_freshness"]["origin_age_minutes"] == pytest.approx(0.5)
        assert record["mode"] == "shadow" and record["used_by_alerts"] is False
        if record["feature_set"].startswith("B5_external_as_issued"):
            assert record["weather_provenance"]["provenance_class"] == "captured_live"
            assert pd.Timestamp(record["weather_provenance"]["retrieved_at"]) <= pd.Timestamp(origin)
        if record["feature_set"] == "B6_tide":
            assert record["tide_provenance"]["variable"] == "sea_level_height_msl"
            assert set(record["tide_features"]) == set(sfl.TIDE_COLUMNS)
    assert {r["target"] for r in forecasts} == {"Temperature"}
    assert {r["pi"]["method"] for r in forecasts} == {"aci_scaled"}
    assert {(r["feature_set"], r["model_variant"]) for r in forecasts} == {
        ("B4_quality", "with_pH"), ("B5_external_as_issued", "with_pH"),
        ("B4_quality_nopH", "nopH"), ("B5_external_as_issued_nopH", "nopH")}
    # same origin again: nothing new
    assert _issue(_raw(), ledger, store=_snapshots(ledger / "snaps2.jsonl"), tide=_tide_ok)["issued"] == 0


def test_suspect_ph_tags_with_ph_temperature_and_nopH_still_issues(ledger):
    _issue(_raw(ph=6.9), ledger)
    records = fe._read_jsonl(fe.LONG_FORECAST_LOG)
    assert records and all(r["target"] == "Temperature" for r in records)
    # sensor_status describes the target sensor (Temperature) and gates scoring: never changed by pH
    assert all(r["sensor_status"] == "ok" for r in records)
    with_ph = [r for r in records if r["model_variant"] == "with_pH"]
    no_ph = [r for r in records if r["model_variant"] == "nopH"]
    assert len(with_ph) == 3 and len(no_ph) == 3
    assert all(r["ph_input_status"] == "ph_probe_suspect" for r in with_ph)
    assert all(r["ph_input_status"] == "not_used" for r in no_ph)


def test_plausible_ph_input_is_tagged_ok(ledger):
    _issue(_raw(), ledger)
    records = fe._read_jsonl(fe.LONG_FORECAST_LOG)
    assert {r["ph_input_status"] for r in records if r["model_variant"] == "with_pH"} == {"ok"}


def test_missing_ph_skips_with_ph_but_issues_nopH(ledger):
    raw = _raw()
    raw["pH"] = np.nan
    result = _issue(raw, ledger)
    records = fe._read_jsonl(fe.LONG_FORECAST_LOG)
    assert {r["feature_set"] for r in records} == {"B4_quality_nopH"}
    assert len(records) == 3
    assert all(r["ph_input_status"] == "not_used" for r in records)
    reasons = {(s["feature_set"], s["reason"]) for s in result["skips"]}
    assert ("B4_quality", "insufficient_sensor_history") in reasons


def test_absent_ph_column_issues_nopH(ledger):
    raw = _raw().drop(columns=["pH"])
    _issue(raw, ledger)
    records = fe._read_jsonl(fe.LONG_FORECAST_LOG)
    assert {r["feature_set"] for r in records} == {"B4_quality_nopH"}
    skips = fe._read_jsonl(fe.LONG_SKIP_LOG)
    assert {s["reason"] for s in skips if (s["target"], s["feature_set"]) == ("Temperature", "B4_quality")} == {"feature_missing"}


def test_withdrawn_bundles_never_issue(ledger):
    result = _issue(_raw(), ledger, store=_snapshots(ledger / "snaps.jsonl"), tide=_tide_ok)
    assert not [r for r in fe._read_jsonl(fe.LONG_FORECAST_LOG) if r["target"] == "pH"]
    withdrawn = [s for s in fe._read_jsonl(fe.LONG_SKIP_LOG) if s["reason"] == "bundle_withdrawn"]
    assert len(withdrawn) == 6 and {s["target"] for s in withdrawn} == {"pH"}
    assert all("RL-18" in s["detail"]["withdrawn_reason"] for s in withdrawn)
    assert all(s["issued_at"] for s in withdrawn)
    assert result["issued"] == 12


def test_manifest_marks_ph_withdrawn_and_nopH_parallel():
    manifest = json.loads(sfl.MANIFEST.read_text(encoding="utf-8"))
    entries = manifest["bundles"]
    ph = [e for e in entries if e["target"] == "pH"]
    assert len(ph) == 6
    for entry in ph:
        assert entry["status"] == "withdrawn"
        assert "RL-18" in entry["withdrawn_reason"] and entry["withdrawn_at"]
        assert (sfl.MODEL_DIR / entry["file"]).exists()  # kept for provenance
    no_ph = [e for e in entries if e.get("variant") == "nopH"]
    assert {(e["feature_set"], e["horizon_minutes"]) for e in no_ph} == {
        (fs, h) for fs in ("B4_quality_nopH", "B5_external_as_issued_nopH") for h in (180, 360, 720)}
    for entry in no_ph:
        assert entry["target"] == "Temperature" and entry["role"] == "parallel_shadow" and entry["status"] == "active"
        assert not any(name.startswith("pH_") for name in entry["features"])
        assert (sfl.MODEL_DIR / entry["file"]).exists()
    with_ph = [e for e in entries if e["target"] == "Temperature" and e.get("variant") == "with_pH"]
    assert len(with_ph) == 6 and all(e["status"] == "active" for e in with_ph)


def test_load_bundles_does_not_unpickle_withdrawn(tmp_path):
    manifest = {"bundles": [{"file": "does-not-exist.pkl", "model_version": "x", "target": "pH", "horizon_minutes": 180,
                             "feature_set": "B4_quality", "status": "withdrawn", "withdrawn_reason": "test"}]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    bundles = sfl.load_bundles(path)
    assert len(bundles) == 1 and bundles[0]["status"] == "withdrawn" and "model" not in bundles[0]


def test_nopH_bundles_carry_compatible_calibration_scores():
    for bundle in sfl.load_bundles():
        if bundle.get("variant") != "nopH":
            continue
        assert bundle["pi_method"] == "aci_scaled" and bundle["aci_gamma"] > 0
        assert len(bundle["calibration_scores"]) > 1000 and np.all(np.isfinite(bundle["calibration_scores"]))


def test_ph_tagged_temperature_record_is_still_scored(ledger):
    _issue(_raw(ph=6.9), ledger)
    later = _raw(end=NOW.floor("min") + pd.Timedelta(minutes=725), minutes=900, ph=6.9)
    assert fe.resolve_long_outcomes(later) >= 6
    outcomes = fe._read_jsonl(fe.LONG_OUTCOME_LOG)
    with_ph = [o for o in outcomes if o["model_variant"] == "with_pH"]
    assert with_ph and all(o["status"] == "scored" for o in with_ph)
    assert all(o["ph_input_status"] == "ph_probe_suspect" for o in with_ph)


def test_aci_uses_matured_outcomes_only(ledger):
    bundles = sfl.load_bundles()
    temp = next(b for b in bundles if b["target"] == "Temperature" and b["horizon_minutes"] == 180 and b["feature_set"] == "B4_quality")
    issued = NOW.floor("min") - pd.Timedelta(minutes=200)
    fe.append_long_forecast({"station_serial": STATION, "issued_at": issued.isoformat(), "valid_at": (issued + pd.Timedelta(minutes=180)).isoformat(),
                             "horizon_minutes": 180, "target": "Temperature", "feature_set": "B4_quality", "model_version": temp["model_version"],
                             "forecast": 10.0, "current": 28.0, "sensor_status": "ok",
                             "pi": {"method": "aci_scaled", "night": 0, "pi80": {"q": 0.1}, "pi90": {"q": 0.2}}})
    raw = _raw()
    _issue(raw, ledger)
    record = next(r for r in fe._read_jsonl(fe.LONG_FORECAST_LOG) if r["model_version"] == temp["model_version"] and r["issued_at"] == NOW.floor("min").isoformat())
    assert record["pi"]["pi80"]["n_live"] == 1
    assert record["pi"]["pi80"]["alpha_t"] == pytest.approx(0.2 + temp["aci_gamma"] * (0.2 - 1.0))
