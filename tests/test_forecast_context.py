"""Runtime weather (B5) and tide (B6) context for the long-horizon shadow forecasts."""
import json

import numpy as np
import pandas as pd
import pytest

from core import forecast_context as fc
from experiments.forecast_external_context import join_as_issued, read_snapshots

STATION = "06M26042804"
LOC = "map_station_NB1"


def _snap(retrieved, valid, provenance="captured_live", temp=27.0, **extra):
    record = {"station": STATION, "location_id": LOC, "provider": "open_meteo", "product": "open_meteo_forecast",
              "issued_at": retrieved, "retrieved_at": retrieved, "valid_at": valid, "provenance_class": provenance,
              "raw_payload_hash": "h" + retrieved, "snapshot_id": f"{retrieved}|{valid}",
              "features": {"cloud_cover": 50, "precipitation": 0.1, "relative_humidity_2m": 80, "surface_pressure": 1006.0,
                           "temperature_2m": temp, "wind_direction_10m": 100, "wind_speed_10m": 9.0}}
    record.update(extra)
    return record


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def test_latest_causal_captured_live_snapshot_is_used(tmp_path):
    path = tmp_path / "snaps.jsonl"
    _write(path, [
        _snap("2026-10-16T01:00:00+00:00", "2026-10-16T05:00:00+00:00", temp=25.0),
        _snap("2026-10-16T02:00:00+00:00", "2026-10-16T05:00:00+00:00", temp=26.0),
        # retrieved after the origin: must never be used
        _snap("2026-10-16T02:30:00+00:00", "2026-10-16T05:00:00+00:00", temp=99.0),
        # reconstructed and legacy (no provenance) rows are never used at runtime
        _snap("2026-10-16T02:10:00+00:00", "2026-10-16T05:00:00+00:00", provenance="reconstructed_run", temp=77.0),
    ])
    store = fc.CapturedLiveWeather(path)
    got = store.features_at(pd.Timestamp("2026-10-16T02:20", tz="UTC"), pd.Timestamp("2026-10-16T05:20", tz="UTC"), STATION, LOC)
    assert got["status"] == "ok"
    assert got["features"]["external_temperature_2m"] == 26.0
    prov = got["provenance"]
    assert prov["provenance_class"] == "captured_live"
    assert prov["retrieved_at"] == "2026-10-16T02:00:00+00:00"
    assert prov["age_hours"] == pytest.approx(20 / 60, abs=1e-3)


def test_matches_join_as_issued_on_captured_live(tmp_path):
    path = tmp_path / "snaps.jsonl"
    records = []
    for hour in range(0, 30):
        retrieved = (pd.Timestamp("2026-10-15T00:05", tz="UTC") + pd.Timedelta(hours=hour)).isoformat()
        for lead in range(0, 15):
            valid = (pd.Timestamp("2026-10-15T00:00", tz="UTC") + pd.Timedelta(hours=hour + lead)).isoformat()
            records.append(_snap(retrieved, valid, temp=20 + hour + lead / 100))
    _write(path, records)
    origins = pd.date_range("2026-10-15T03:00", periods=40, freq="37min", tz="UTC")
    frame = pd.DataFrame({"issued_at": origins, "valid_at": origins + pd.Timedelta(minutes=360), "station": STATION, "location_id": LOC})
    joined = join_as_issued(frame, read_snapshots(path), prefix="external")
    store = fc.CapturedLiveWeather(path)
    for _, row in joined.iterrows():
        got = store.features_at(row.issued_at, row.valid_at, STATION, LOC)
        if pd.isna(row["external_temperature_2m"]):
            assert got["status"] == "skip"
        else:
            assert got["status"] == "ok"
            for name in fc.WEATHER_FIELDS:
                assert got["features"][f"external_{name}"] == pytest.approx(float(row[f"external_{name}"]))


def test_no_snapshot_within_24h_is_a_logged_skip(tmp_path):
    path = tmp_path / "snaps.jsonl"
    _write(path, [_snap("2026-10-14T00:00:00+00:00", "2026-10-16T05:00:00+00:00")])
    store = fc.CapturedLiveWeather(path)
    got = store.features_at(pd.Timestamp("2026-10-16T02:00", tz="UTC"), pd.Timestamp("2026-10-16T05:00", tz="UTC"), STATION, LOC)
    assert got == {"status": "skip", "reason": "no_captured_live_snapshot_within_24h", "latest_retrieved_at": "2026-10-14T00:00:00+00:00"}


def test_missing_file_and_missing_valid_hour(tmp_path):
    store = fc.CapturedLiveWeather(tmp_path / "absent.jsonl")
    got = store.features_at(pd.Timestamp("2026-10-16T02:00", tz="UTC"), pd.Timestamp("2026-10-16T05:00", tz="UTC"), STATION, LOC)
    assert got["status"] == "skip" and got["reason"] == "no_captured_live_snapshot_within_24h"
    path = tmp_path / "snaps.jsonl"
    _write(path, [_snap("2026-10-16T01:00:00+00:00", "2026-10-16T03:00:00+00:00")])
    got = fc.CapturedLiveWeather(path).features_at(pd.Timestamp("2026-10-16T02:00", tz="UTC"), pd.Timestamp("2026-10-16T14:00", tz="UTC"), STATION, LOC)
    assert got["status"] == "skip" and got["reason"] == "snapshot_missing_valid_hour"


def test_null_feature_is_skip_not_zero(tmp_path):
    path = tmp_path / "snaps.jsonl"
    record = _snap("2026-10-16T01:00:00+00:00", "2026-10-16T05:00:00+00:00")
    record["features"]["precipitation"] = None
    _write(path, [record])
    got = fc.CapturedLiveWeather(path).features_at(pd.Timestamp("2026-10-16T02:00", tz="UTC"), pd.Timestamp("2026-10-16T05:00", tz="UTC"), STATION, LOC)
    assert got["status"] == "skip" and got["reason"] == "snapshot_feature_missing"


def test_store_reloads_when_file_grows(tmp_path):
    path = tmp_path / "snaps.jsonl"
    _write(path, [_snap("2026-10-16T01:00:00+00:00", "2026-10-16T05:00:00+00:00", temp=25.0)])
    store = fc.CapturedLiveWeather(path)
    origin, valid = pd.Timestamp("2026-10-16T02:30", tz="UTC"), pd.Timestamp("2026-10-16T05:00", tz="UTC")
    assert store.features_at(origin, valid, STATION, LOC)["features"]["external_temperature_2m"] == 25.0
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_snap("2026-10-16T02:00:00+00:00", "2026-10-16T05:00:00+00:00", temp=26.0)) + "\n")
    assert store.features_at(origin, valid, STATION, LOC)["features"]["external_temperature_2m"] == 26.0


def _marine(status="ready", levels=None):
    times = [f"2026-10-16T{h:02d}:00" for h in range(24)] + [f"2026-10-17T{h:02d}:00" for h in range(24)]
    levels = levels if levels is not None else list(np.round(np.sin(np.arange(48) / 4), 3))
    return {"status": status, "provider": "open_meteo_marine", "retrieved_at": "2026-10-16T02:00:00+00:00", "timezone": "Asia/Ho_Chi_Minh",
            "location": {"source": LOC}, "hourly": {"time": times, "sea_level_height_msl": levels}, "model": None, "cache": "miss"}


def test_tide_series_converts_local_times_to_utc():
    series, prov = fc.tide_series_from_marine(_marine())
    assert series["valid_at"].iloc[0] == pd.Timestamp("2026-10-15T17:00", tz="UTC")
    assert prov["retrieved_at"] == "2026-10-16T02:00:00+00:00"
    assert prov["variable"] == "sea_level_height_msl"


def test_tide_unavailable_marine_is_skip(monkeypatch):
    monkeypatch.setattr(fc, "get_station_environment", lambda station, weather=None: {"marine": {"status": "disabled", "reason": "marine_disabled"}})
    got = fc.marine_tide(STATION, {"status": "ready"})
    assert got == {"status": "skip", "reason": "marine_disabled", "marine_status": "disabled"}


def test_tide_all_null_is_skip(monkeypatch):
    monkeypatch.setattr(fc, "get_station_environment", lambda station, weather=None: {"marine": _marine(levels=[None] * 48)})
    got = fc.marine_tide(STATION, {"status": "ready"})
    assert got["status"] == "skip" and got["reason"] == "sea_level_missing"


def test_tide_ready(monkeypatch):
    monkeypatch.setattr(fc, "_TIDE_HISTORY", {})
    monkeypatch.setattr(fc, "get_station_environment", lambda station, weather=None: {"marine": _marine()})
    got = fc.marine_tide(STATION, {"status": "ready"})
    assert got["status"] == "ok"
    assert len(got["series"]) == 48
    assert got["provenance"]["marine_status"] == "ready"


def test_tide_keeps_earlier_hours_from_previous_retrieval(monkeypatch):
    monkeypatch.setattr(fc, "_TIDE_HISTORY", {})
    first = _marine()
    monkeypatch.setattr(fc, "get_station_environment", lambda station, weather=None: {"marine": first})
    fc.marine_tide(STATION, {"status": "ready"})
    second = _marine()
    second["hourly"] = {"time": first["hourly"]["time"][24:] + [f"2026-10-18T{h:02d}:00" for h in range(24)],
                        "sea_level_height_msl": [9.0] * 48}
    monkeypatch.setattr(fc, "get_station_environment", lambda station, weather=None: {"marine": second})
    got = fc.marine_tide(STATION, {"status": "ready"})
    series = got["series"]
    assert got["provenance"]["earlier_hours_from_previous_retrieval"] == 24
    assert series["valid_at"].min() == pd.Timestamp("2026-10-15T17:00", tz="UTC")
    assert (series[series["valid_at"] >= pd.Timestamp("2026-10-16T17:00", tz="UTC")]["sea_level_m"] == 9.0).all()
    assert series["valid_at"].is_monotonic_increasing
