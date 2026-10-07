import json
import pandas as pd

from experiments.forecast_external_context import join_as_issued, read_snapshots
from experiments import forecast_snapshot_store
from experiments.forecast_snapshot_store import append_snapshot


def test_snapshot_store_is_idempotent_and_join_is_causal(tmp_path):
    path = tmp_path / "snapshots.jsonl"
    record = {"station": "s1", "provider": "open_meteo", "product": "p", "issued_at": "2026-01-01T00:00:00Z", "retrieved_at": "2026-01-01T00:00:00Z", "valid_at": "2026-01-01T01:00:00Z", "features": {"precipitation": 2.0}}
    assert append_snapshot(path, record) is True
    assert append_snapshot(path, record) is False
    snapshots = read_snapshots(path)
    frame = pd.DataFrame({"station": ["s1"], "issued_at": pd.to_datetime(["2026-01-01T00:30:00Z"]), "valid_at": pd.to_datetime(["2026-01-01T01:00:00Z"])})
    joined = join_as_issued(frame, snapshots, prefix="weather")
    assert joined.loc[0, "weather_precipitation"] == 2.0


def test_future_snapshot_is_not_joined():
    snapshots = pd.DataFrame([{"station": "s1", "issued_at": pd.Timestamp("2026-01-01T02:00:00Z"), "retrieved_at": pd.Timestamp("2026-01-01T02:00:00Z"), "valid_at": pd.Timestamp("2026-01-01T03:00:00Z"), "features": {"wind_speed_10m": 3.0}}])
    frame = pd.DataFrame({"station": ["s1"], "issued_at": [pd.Timestamp("2026-01-01T01:00:00Z")], "valid_at": [pd.Timestamp("2026-01-01T03:00:00Z")]})
    joined = join_as_issued(frame, snapshots, prefix="weather")
    assert pd.isna(joined.loc[0, "weather_wind_speed_10m"])


def test_snapshot_retrieved_after_forecast_origin_is_not_joined():
    snapshots = pd.DataFrame([{
        "station": "s1",
        "issued_at": pd.Timestamp("2026-01-01T00:00:00Z"),
        "retrieved_at": pd.Timestamp("2026-01-01T01:00:00Z"),
        "valid_at": pd.Timestamp("2026-01-01T01:00:00Z"),
        "features": {"precipitation": 99.0},
    }])
    frame = pd.DataFrame({
        "station": ["s1"],
        "issued_at": [pd.Timestamp("2026-01-01T00:30:00Z")],
        "valid_at": [pd.Timestamp("2026-01-01T01:00:00Z")],
    })
    joined = join_as_issued(frame, snapshots, prefix="weather")
    assert pd.isna(joined.loc[0, "weather_precipitation"])


def test_snapshot_for_another_station_is_not_joined():
    snapshots = pd.DataFrame([{
        "station": "s2",
        "issued_at": pd.Timestamp("2026-01-01T00:00:00Z"),
        "retrieved_at": pd.Timestamp("2026-01-01T00:00:00Z"),
        "valid_at": pd.Timestamp("2026-01-01T01:00:00Z"),
        "features": {"precipitation": 99.0},
    }])
    frame = pd.DataFrame({
        "station": ["s1"],
        "issued_at": [pd.Timestamp("2026-01-01T00:30:00Z")],
        "valid_at": [pd.Timestamp("2026-01-01T01:00:00Z")],
    })
    joined = join_as_issued(frame, snapshots, prefix="weather")
    assert pd.isna(joined.loc[0, "weather_precipitation"])


def test_capture_converts_provider_local_time_to_utc(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast_snapshot_store, "weather_location_for_station", lambda _: {"latitude": 20.7, "longitude": 107.0})
    monkeypatch.setattr(forecast_snapshot_store, "_fetch_open_meteo", lambda _: {"timezone": "Asia/Ho_Chi_Minh", "hourly": {"time": ["2026-08-01T00:00"], "temperature_2m": [27.0]}})
    path = tmp_path / "snapshots.jsonl"
    assert forecast_snapshot_store.capture_open_meteo("s1", path) == 1
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["valid_at"] == "2026-07-31T17:00:00+00:00"
    assert len(record["raw_payload_hash"]) == 64
