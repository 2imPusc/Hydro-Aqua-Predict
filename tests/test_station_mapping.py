from core.config import map_reference_station_for_sensor


def test_haiphong_realtime_sensor_uses_nb1_as_explicit_map_anchor():
    assert map_reference_station_for_sensor("06M26042804") == "NB1"


def test_sensor_without_mapping_returns_none():
    assert map_reference_station_for_sensor("unknown") is None
