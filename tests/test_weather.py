from core import weather


def test_weather_is_disabled_without_env(monkeypatch):
    monkeypatch.setattr(weather, "WEATHER_ENABLED", False)
    assert weather.get_station_weather("06M26042804")["status"] == "disabled"


def test_weather_uses_station_location_and_ttl_cache(monkeypatch):
    monkeypatch.setattr(weather, "WEATHER_ENABLED", True)
    weather._CACHE.clear()
    calls = []
    def fake_fetch(location):
        calls.append(location)
        return {"timezone": "Asia/Ho_Chi_Minh", "hourly": {"time": ["2026-07-25T00:00"]}}
    monkeypatch.setattr(weather, "_fetch_open_meteo", fake_fetch)
    first = weather.get_station_weather("06M26042804", now=100)
    second = weather.get_station_weather("06M26042804", now=101)
    assert first["status"] == "ready"
    assert first["location"]["accuracy"] == "nearby_reference_station"
    assert second["cache"] == "hit"
    assert len(calls) == 1


def test_weather_provider_failure_does_not_raise(monkeypatch):
    monkeypatch.setattr(weather, "WEATHER_ENABLED", True)
    weather._CACHE.clear()
    monkeypatch.setattr(weather, "_fetch_open_meteo", lambda location: (_ for _ in ()).throw(OSError("offline")))
    result = weather.get_station_weather("06M26042804", now=100)
    assert result["status"] == "unavailable"
    assert result["reason"] == "provider_request_failed"


def test_station_environment_keeps_marine_context_separate(monkeypatch):
    monkeypatch.setattr(weather, "MARINE_ENABLED", True)
    monkeypatch.setattr(weather, "MARINE_PROVIDER", "open_meteo")
    weather._MARINE_CACHE.clear()
    monkeypatch.setattr(weather, "_fetch_open_meteo_marine", lambda location: {
        "timezone": "Asia/Ho_Chi_Minh",
        "hourly": {"time": ["2026-07-25T00:00"], "wave_height": [0.7], "ocean_current_velocity": [1.2]},
        "hourly_units": {"wave_height": "m", "ocean_current_velocity": "km/h"},
    })
    result = weather.get_station_environment("06M26042804", weather={"status": "ready"}, now=100)
    assert result["status"] == "ready"
    assert result["marine"]["status"] == "ready"
    assert result["marine"]["hourly"]["wave_height"] == [0.7]
    assert result["marine"]["used_by_models"] is False
