import pandas as pd
import pytest

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


_LONG_CSV = (
    "Date,DeviceSerialNumber,SensorType,Value,Unit,Status\r\n"
    "2026-07-27 00:00,06M26042804,pH,8.01,,Good\r\n"
)


def _patch_credentials(monkeypatch):
    monkeypatch.setattr(greenlab_api, "GREENLAB_API_USERNAME", "user")
    monkeypatch.setattr(greenlab_api, "GREENLAB_API_PASSWORD", "password")


def test_fetch_by_date_csv_requests_range_and_returns_text(monkeypatch):
    seen = {}

    class Response:
        content = ("\ufeff" + _LONG_CSV).encode("utf-8")
        def raise_for_status(self): pass

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return Response()

    _patch_credentials(monkeypatch)
    monkeypatch.setattr(greenlab_api.requests, "get", fake_get)
    text = greenlab_api.fetch_by_date_csv("06M26042804", "2026-07-27", "2026-08-02")
    assert seen["url"].endswith("/Datums/DataByDate")
    assert seen["params"] == {"DeviceSerialNumber": "06M26042804", "StartDate": "2026-07-27", "EndDate": "2026-08-02"}
    assert text == _LONG_CSV


def test_fetch_by_date_csv_rejects_unexpected_payload(monkeypatch):
    class Response:
        content = b"<html>login</html>"
        def raise_for_status(self): pass

    _patch_credentials(monkeypatch)
    monkeypatch.setattr(greenlab_api.requests, "get", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="greenlab_by_date_unexpected_payload"):
        greenlab_api.fetch_by_date_csv("06M26042804", "2026-07-27", "2026-07-28")


def test_fetch_by_date_csv_requires_credentials(monkeypatch):
    monkeypatch.setattr(greenlab_api, "GREENLAB_API_USERNAME", "")
    with pytest.raises(RuntimeError, match="greenlab_api_credentials_missing"):
        greenlab_api.fetch_by_date_csv("06M26042804", "2026-07-27", "2026-07-28")
