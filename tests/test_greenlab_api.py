import pandas as pd

from core import greenlab_api


def test_latest_snapshot_pivots_sensor_payload(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return [
                {"SensorType": "Temp", "DeviceSerialNumber": "06M26042804", "ReceivedDate": "2026-07-26T00:00:00Z", "Value": 30.0},
                {"SensorType": "NH4", "DeviceSerialNumber": "06M26042804", "ReceivedDate": "2026-07-26T00:00:00Z", "Value": 110.0},
            ]
    monkeypatch.setattr(greenlab_api, "GREENLAB_API_USERNAME", "user")
    monkeypatch.setattr(greenlab_api, "GREENLAB_API_PASSWORD", "password")
    monkeypatch.setattr(greenlab_api.requests, "get", lambda *args, **kwargs: Response())
    result = greenlab_api.fetch_latest_snapshot("06M26042804")
    assert result.iloc[0]["Temperature"] == 30.0
    assert result.iloc[0]["NH4"] == 110.0


def test_append_snapshot_is_idempotent_and_loadable(tmp_path, monkeypatch):
    monkeypatch.setattr(greenlab_api, "GREENLAB_API_CACHE_DIR", tmp_path / "live-cache")
    snapshot = pd.DataFrame([{"device": "06M26042804", "fetchedAt": "2026-07-26T00:00:00Z", "COD": 1., "NH4": 2., "pH": 8., "Temperature": 30., "TSS": 3.}])
    greenlab_api.append_snapshot(snapshot)
    greenlab_api.append_snapshot(snapshot)
    result = greenlab_api.load_cached_history("06M26042804")
    assert len(result) == 1
    assert result.iloc[0]["Temperature"] == 30.0
