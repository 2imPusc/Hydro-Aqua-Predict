from __future__ import annotations

from datetime import datetime, timezone

from app.sensor_provider import normalize_history_csv

CSV = """Date,DeviceSerialNumber,SensorType,Value,Unit,Status
2026-10-22 00:00,06M26042804,COD,558.8,mg/L,Good
2026-10-22 00:00,06M26042804,COD,558.8,mg/L,Good
2026-10-22 00:01,06M26042804,Temp,29.5,C,Good
2026-10-22 00:01,06M26042804,pH,bad,,Good
2026-10-22 00:01,OTHER,pH,7.9,,Good
"""


def test_history_csv_local_time_dedup_and_alias():
    rows = normalize_history_csv(CSV, "06M26042804", retrieved_at=datetime(2026, 10, 24, tzinfo=timezone.utc))
    assert len(rows) == 2                                   # duplicate, bad value and other station dropped
    cod, temp = rows
    assert cod["observed_at"] == datetime(2026, 10, 21, 17, 0, tzinfo=timezone.utc)   # 00:00 +07 -> 17:00Z
    assert temp["metric"] == "Temperature" and temp["source_type"] == "greenlab_by_date"
