import pandas as pd

import core.pipeline as pipeline


def _raw_frame():
    frame = pd.DataFrame(
        [{
            "fetchedAt": pd.Timestamp.now(tz="UTC"),
            "pH": 7.8,
            "Temperature": 29.0,
            "TSS": 12.0,
            "NH4": 0.2,
        }]
    )
    frame.attrs["data_source"] = "test"
    return frame


def _classification(**_kwargs):
    return {"params": {"imputed": {"pH": 7.8}}, "score": 80.0, "label": "Suitable"}


def test_legacy_forecast_is_deferred_on_regular_refresh(monkeypatch):
    monkeypatch.setattr(pipeline, "fetch_raw", lambda _station: _raw_frame())
    monkeypatch.setattr(pipeline, "classify_station", _classification)
    monkeypatch.setattr(pipeline, "forecast", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("legacy forecast should not run")))
    monkeypatch.setattr(pipeline, "evaluate_aquaculture_risk", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline, "get_station_weather", lambda _station: {})

    result = pipeline.run_pipeline("test", region="quangninh")

    assert result["status"] == "success"
    assert result["forecast"]["status"] == "deferred"
    assert result["forecast"]["timeline"] == []


def test_legacy_forecast_runs_only_when_requested(monkeypatch):
    monkeypatch.setattr(pipeline, "fetch_raw", lambda _station: _raw_frame())
    monkeypatch.setattr(pipeline, "classify_station", _classification)
    calls = []
    monkeypatch.setattr(pipeline, "forecast", lambda **kwargs: calls.append(kwargs) or {"timeline": []})
    monkeypatch.setattr(pipeline, "evaluate_aquaculture_risk", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline, "get_station_weather", lambda _station: {})

    pipeline.run_pipeline("test", region="quangninh", include_legacy_forecast=True)

    assert len(calls) == 1


def test_station_future_projects_anchor_forecast_to_virtual_station(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "classify_station",
        lambda **_kwargs: {
            "score": .8,
            "label": "Suitable",
            "params": {"measured": {"Temperature": 30.0}, "imputed": {"DO": 5.0}, "defaulted": {}},
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_score_virtual_stations",
        lambda _params, _species: {"NB2": {"values": {"DO": 4.8}, "wqi": {"score": 75.0, "label": "Suitable"}}},
    )
    sensor_future = {
        "status": "ready",
        "timeline": [{"timestamp": "2026-07-26T12:15:00+00:00", "horizon_minutes": 15, "sensors": {"Temperature": 30.0}}],
    }

    result = pipeline._station_future(sensor_future, "06M26042804", "haiphong", "cobia")

    assert result["06M26042804"][0]["source"] == "sensor_first_forecast"
    assert result["NB2"][0]["source"] == "anchor_sensor_forecast_then_spatial_projection"
    assert result["NB2"][0]["values"]["DO"] == 4.8


def test_stale_sensor_keeps_weather_advisory_but_blocks_water_forecast(monkeypatch):
    stale = _raw_frame()
    stale["fetchedAt"] = pd.Timestamp("2026-08-21T12:00:00Z")
    stale.attrs["data_source"] = "greenlab_api_cache"
    monkeypatch.setattr(pipeline, "fetch_raw", lambda _station: stale)
    monkeypatch.setattr(pipeline, "get_station_weather", lambda _station: {
        "status": "ready", "timezone": "UTC", "hourly": {
            "time": ["2026-08-21T12:00"], "precipitation": [0],
            "wind_speed_10m": [10], "wind_direction_10m": [90],
        },
    })
    result = pipeline.run_pipeline("test", region="haiphong", now="2026-08-21T12:12:00Z")
    assert result["status"] == "degraded"
    assert result["sensor_future"]["status"] == "blocked"
    assert result["weather_advisory"]["status"] == "ready"
    assert result["weather_advisory"]["used_by_classification"] is False
