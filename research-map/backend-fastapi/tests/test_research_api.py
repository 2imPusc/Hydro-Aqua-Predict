"""Research router: read-only exports, live long-horizon ledger, weather snapshots (no Postgres)."""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import research
from app.settings import settings

NOW = datetime(2026, 10, 17, 6, 0, tzinfo=timezone.utc)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    export_root = tmp_path / "research-map"
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(research, "settings", replace(
        settings, research_export_dir=str(export_root), hap_runtime_dir=str(runtime),
        weather_snapshots_path=str(tmp_path / "weather-snapshots.jsonl"),
        sensor_future_manifest_path=str(tmp_path / "manifest.json"), ledger_tail_bytes=1 << 20))
    monkeypatch.setattr(research, "_now", lambda: NOW)
    research.clear_cache()
    app = FastAPI()
    app.include_router(research.router)
    return {"client": TestClient(app), "root": export_root, "runtime": runtime, "tmp": tmp_path}


def _write_export(root, stamp="20261017-1200", files=None, omitted=None):
    out = root / stamp
    out.mkdir(parents=True)
    for name, payload in (files or {}).items():
        (out / name).write_text(json.dumps({"status": "ready", "export_version": stamp, **payload}), encoding="utf-8")
    manifest = {"export_version": stamp, "files": {n: {} for n in (files or {})}, "omitted": omitted or {}}
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return out


def _jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_all_export_endpoints_unavailable_without_export(env):
    client = env["client"]
    for url in ("/api/v1/research/overview", "/api/v1/research/forecast/benchmark",
                "/api/v1/research/suitability?variant=A_W_SUM&region=vn", "/api/v1/research/reliability/foreign",
                "/api/v1/research/reliability/vn"):
        body = client.get(url).json()
        assert body["status"] == "unavailable" and body["reason"] == "research_export_missing", url
        assert body["export_version"] is None


def test_newest_export_wins_and_stray_dirs_are_ignored(env):
    _write_export(env["root"], "20261017-1200", {"overview.json": {"directions": [{"id": "H1"}]}})
    _write_export(env["root"], "20261017-1300", {"overview.json": {"directions": [{"id": "H2"}]}})
    (env["root"] / "zzz-not-a-stamp").mkdir()
    (env["root"] / ".20261017-1400.tmp-abc").mkdir()
    body = env["client"].get("/api/v1/research/overview").json()
    assert body["status"] == "ready" and body["export_version"] == "20261017-1300"
    assert body["directions"][0]["id"] == "H2"


def test_omitted_artifact_reports_manifest_reason(env):
    _write_export(env["root"], omitted={"reliability_vn.json": "a6_not_exported"})
    body = env["client"].get("/api/v1/research/reliability/vn").json()
    assert body == {"status": "unavailable", "reason": "a6_not_exported", "export_version": "20261017-1200"}


def test_suitability_validates_params(env):
    _write_export(env["root"], files={"suitability_hk_N1_W_SUM.json": {"variant": "N1_W_SUM", "region": "hk", "auc": 0.75,
                                                                        "cells": {"type": "FeatureCollection", "features": []}}})
    client = env["client"]
    assert client.get("/api/v1/research/suitability?variant=N1_W_SUM&region=hk").json()["auc"] == 0.75
    assert client.get("/api/v1/research/suitability?variant=BAD&region=hk").status_code == 422
    assert client.get("/api/v1/research/suitability?variant=A_W_SUM&region=xx").status_code == 422


def test_benchmark_non_finite_values_become_null(env):
    out = _write_export(env["root"])
    (out / "forecast_benchmark.json").write_text(
        '{"status":"ready","export_version":"20261017-1200","temperature":[{"skill":NaN}],"ph_clean":[],"conformal":[]}',
        encoding="utf-8")
    body = env["client"].get("/api/v1/research/forecast/benchmark").json()
    assert body["temperature"] == [{"skill": None}]


FOREIGN = {
    "id": "usgs_sfbay", "name": "USGS", "credit": "U.S. Geological Survey", "licence": "public domain", "redistributable": True,
    "stations": {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-122.2, 37.5]}, "properties": {"station": "A"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-121.9, 38.0]}, "properties": {"station": "B"}}]},
    "pairs": {"columns": ["anchor", "target", "var", "transfer", "scale", "km", "same_regime", "share"],
              "rows": [["A", "B", "Temp", "raw", "hourly", 60.8, False, 0.25],
                       ["A", "B", "Temp", "calibrated", "hourly", 60.8, False, 0.68],
                       ["A", "B", "Sal", "raw", "hourly", 60.8, False, 0.1]]},
    "radius": [{"var": "Temp", "scale": "hourly", "transfer": "raw", "regime": "same", "gate": "gate80", "radius_km": 10.0},
               {"var": "Sal", "scale": "hourly", "transfer": "raw", "regime": "same", "gate": "gate80", "radius_km": 0.0}],
    "findings": ["f1"], "available": {"vars": ["Sal", "Temp"], "scales": ["hourly"], "transfers": ["calibrated", "raw"]},
}


def test_foreign_detail_filters_and_joins_coordinates(env):
    _write_export(env["root"], files={"reliability_foreign_index.json": {"datasets": [{"id": "usgs_sfbay"}]},
                                      "reliability_foreign_usgs_sfbay.json": FOREIGN},
                  omitted={"reliability_foreign_irlon.json": "run_dir_missing"})
    client = env["client"]
    assert client.get("/api/v1/research/reliability/foreign").json()["datasets"] == [{"id": "usgs_sfbay"}]
    body = client.get("/api/v1/research/reliability/foreign/usgs_sfbay?var=Temp&scale=hourly&transfer=raw").json()
    assert body["status"] == "ready" and body["id"] == "usgs_sfbay"
    assert body["pairs"] == [{"anchor": "A", "target": "B", "var": "Temp", "transfer": "raw", "scale": "hourly", "km": 60.8,
                              "same_regime": False, "share": 0.25, "lon1": -122.2, "lat1": 37.5, "lon2": -121.9, "lat2": 38.0}]
    assert [r["var"] for r in body["radius"]] == ["Temp"]
    assert body["selected"] == {"var": "Temp", "scale": "hourly", "transfer": "raw"}
    assert body["credit"] == "U.S. Geological Survey"
    assert client.get("/api/v1/research/reliability/foreign/nope").status_code == 404
    omitted = client.get("/api/v1/research/reliability/foreign/irlon").json()
    assert omitted == {"status": "unavailable", "reason": "run_dir_missing", "export_version": "20261017-1200", "id": "irlon"}
    assert client.get("/api/v1/research/reliability/foreign/..%2Fsecret").status_code == 404


def _long_record(issued, target="Temperature", horizon=180, feature_set="B4_quality", value=29.1, q80=0.6, q90=float("inf")):
    return {"station_serial": "06M26042804", "issued_at": issued.isoformat(), "valid_at": (issued + timedelta(minutes=horizon)).isoformat(),
            "horizon_minutes": horizon, "target": target, "feature_set": feature_set, "model_variant": "with_pH",
            "bundle_role": "primary_shadow", "forecast": value, "current": 28.9, "sensor_status": "ok", "ph_input_status": "ok",
            "pi": {"method": "aci_scaled", "pi80": {"q": q80, "lower": value - q80, "upper": value + q80},
                   "pi90": {"q": q90, "lower": value - q90, "upper": value + q90}}}


def test_forecast_long_missing_ledger_lists_withdrawn_from_manifest(env):
    (env["tmp"] / "manifest.json").write_text(json.dumps({"bundles": [
        {"target": "pH", "horizon_minutes": 180, "feature_set": "B6_tide", "status": "withdrawn", "withdrawn_reason": "RL-18"},
        {"target": "Temperature", "horizon_minutes": 180, "feature_set": "B4_quality"}]}), encoding="utf-8")
    body = env["client"].get("/api/v1/research/forecast/long?station=06M26042804").json()
    assert body["ledger_state"] == "missing" and body["status"] == "unavailable" and body["items"] == []
    assert body["withdrawn"] == [{"target": "pH", "feature_set": "B6_tide", "horizon_min": 180, "reason": "RL-18", "withdrawn_at": None}]


def test_forecast_long_empty_ledger(env):
    _jsonl(env["runtime"] / "forecast-shadow" / "long_forecasts.jsonl", [])
    body = env["client"].get("/api/v1/research/forecast/long").json()
    assert body["ledger_state"] == "empty" and body["status"] == "ready" and body["items"] == []


def test_forecast_long_active_latest_item_per_series_skips_and_scoring(env):
    shadow = env["runtime"] / "forecast-shadow"
    old = NOW - timedelta(hours=3)
    _jsonl(shadow / "long_forecasts.jsonl", [
        _long_record(old, value=28.0),
        _long_record(NOW - timedelta(minutes=1), value=29.1),
        {**_long_record(NOW - timedelta(minutes=1), feature_set="B4_quality_nopH", value=29.3), "model_variant": "nopH",
         "ph_input_status": "not_used", "bundle_role": "parallel_shadow"},
        {**_long_record(NOW, value=1.0), "station_serial": "OTHER"},
    ])
    with (shadow / "long_forecasts.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"truncated": ')  # partial last line while the runner writes
    _jsonl(shadow / "long_skips.jsonl", [
        {"station_serial": "06M26042804", "issued_at": None, "target": "pH", "horizon_minutes": 180, "feature_set": "B6_tide",
         "reason": "bundle_withdrawn", "detail": {"withdrawn_reason": "RL-18"}, "recorded_at": NOW.isoformat()}])
    _jsonl(shadow / "long_outcomes.jsonl", [
        {"station_serial": "06M26042804", "target": "Temperature", "horizon_minutes": 180, "feature_set": "B4_quality",
         "model_variant": "with_pH", "status": "scored", "forecast": 29.0, "actual": 29.5, "current": 28.5,
         "abs_error": 0.5, "covered": {"pi80": True, "pi90": True}},
        {"station_serial": "06M26042804", "target": "Temperature", "horizon_minutes": 180, "feature_set": "B4_quality",
         "model_variant": "with_pH", "status": "scored", "forecast": 29.0, "actual": 30.0, "current": 29.0,
         "abs_error": 1.0, "covered": {"pi80": False, "pi90": True}},
        {"station_serial": "06M26042804", "target": "Temperature", "horizon_minutes": 180, "feature_set": "B4_quality",
         "model_variant": "with_pH", "status": "excluded_sensor_suspect"}])
    body = env["client"].get("/api/v1/research/forecast/long?station=06M26042804").json()
    assert body["status"] == "ready" and body["ledger_state"] == "active"
    assert body["latest_issued_at"] == (NOW - timedelta(minutes=1)).isoformat()
    items = {item["feature_set"]: item for item in body["items"]}
    assert set(items) == {"B4_quality", "B4_quality_nopH"}
    assert items["B4_quality"]["value"] == 29.1 and items["B4_quality"]["pi80"] == [28.5, 29.7]
    assert items["B4_quality"]["pi90"] is None  # infinite band -> null
    assert items["B4_quality_nopH"]["ph_input_status"] == "not_used"
    assert body["skips"][0]["reason"] == "bundle_withdrawn" and body["skips"][0]["at"] == NOW.isoformat()
    assert body["withdrawn"] == [{"target": "pH", "feature_set": "B6_tide", "horizon_min": 180, "reason": "RL-18", "withdrawn_at": None}]
    score = body["scoring"][0]
    assert score["n"] == 2 and score["mae"] == 0.75 and score["persistence_mae"] == 1.0
    assert score["coverage80"] == 0.5 and score["coverage90"] == 1.0 and score["n_excluded"] == 1


def _snapshot(retrieved, station="06M26042804", valid_offset_h=1):
    return {"station": station, "retrieved_at": retrieved.isoformat(), "valid_at": (retrieved + timedelta(hours=valid_offset_h)).isoformat(),
            "features": {"temperature_2m": 27.0}, "provenance_class": "captured_live"}


def test_weather_status_missing_file(env):
    body = env["client"].get("/api/v1/research/weather/status").json()
    assert body["status"] == "unavailable" and body["health"] == "unavailable" and body["note"] == "observation-only"


def test_weather_status_healthy_and_hourly_strip(env):
    rows = []
    for hours_ago in range(0, 24 * 8):
        t = NOW - timedelta(hours=hours_ago)
        rows += [_snapshot(t, valid_offset_h=1), _snapshot(t, valid_offset_h=2)]  # 2 lines per capture
    rows.append(_snapshot(NOW - timedelta(minutes=10), station="OTHER"))
    _jsonl(env["tmp"] / "weather-snapshots.jsonl", rows)
    body = env["client"].get("/api/v1/research/weather/status?station=06M26042804").json()
    assert body["status"] == "ready" and body["health"] == "healthy"
    assert body["coverage_24h"] == 1.0 and body["coverage_7d"] == 1.0
    assert len(body["hourly"]) == 168 and all(h["captured"] for h in body["hourly"])
    assert body["last_captured_at"] == NOW.isoformat()


def test_weather_status_degraded_when_gappy_or_stale(env):
    rows = [_snapshot(NOW - timedelta(hours=h, minutes=5)) for h in range(0, 24 * 7, 3)]  # every 3rd hour
    _jsonl(env["tmp"] / "weather-snapshots.jsonl", rows)
    body = env["client"].get("/api/v1/research/weather/status").json()
    assert body["health"] == "degraded" and body["reason"] == "coverage_below_min"
    assert 0.3 < body["coverage_7d"] < 0.4
    assert sum(h["captured"] for h in body["hourly"]) == 56
    research.clear_cache()
    _jsonl(env["tmp"] / "weather-snapshots.jsonl", [_snapshot(NOW - timedelta(hours=h + 5)) for h in range(0, 24 * 7)])
    body = env["client"].get("/api/v1/research/weather/status").json()
    assert body["health"] == "degraded" and body["reason"] == "stale_last_capture"
