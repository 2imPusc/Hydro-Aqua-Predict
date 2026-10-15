import hashlib
import json

import pytest

from core import greenlab_api
from experiments.forecast_sensor_v2 import load_sensor_data
from scripts.export_sensor_history import export_history

LONG = (
    "Date,DeviceSerialNumber,SensorType,Value,Unit,Status\n"
    "2026-08-01 00:00,06M26042804,Temp,30.1,C,Good\n"
    "2026-08-01 00:00,06M26042804,pH,8.0,,Good\n"
    "2026-08-01 00:01,06M26042804,Temp,30.2,C,Good\n"
    "2026-08-01 00:01,06M26042804,pH,8.1,,Good\n"
)


def test_export_history_writes_hashed_csv_readable_by_benchmark(tmp_path, monkeypatch):
    exports = tmp_path / "exports"
    (exports / "intervals").mkdir(parents=True)
    (exports / "intervals" / "06M26042804_HAIPHONG_20260801_to_20260801.csv").write_text(LONG, encoding="utf-8")
    monkeypatch.setattr(greenlab_api, "GREENLAB_API_CACHE_DIR", exports / "live-cache")

    manifest = export_history("06M26042804", tmp_path / "out")
    csv_path = tmp_path / "out" / manifest["run"] / "06M26042804.csv"
    assert manifest["rows"] == 2
    assert manifest["sha256"] == hashlib.sha256(csv_path.read_bytes()).hexdigest()
    assert json.loads((csv_path.parent / "manifest.json").read_text())["sha256"] == manifest["sha256"]

    frame = load_sensor_data(csv_path, "06M26042804")
    assert list(frame["Temperature"]) == [30.1, 30.2]

    with pytest.raises(FileExistsError):
        export_history("06M26042804", tmp_path / "out")
