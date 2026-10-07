import pandas as pd

from core.chart_timeline import bridge_forecast_from_current


def test_bridge_prefixes_current_observation_for_contiguous_forecast():
    x, y, bridged = bridge_forecast_from_current(
        ["2026-08-01T00:01:00Z", "2026-08-01T00:02:00Z"], [30.1, 30.2],
        current_timestamp="2026-08-01T00:00:00Z", current_value=30.0,
    )
    assert bridged
    assert x[0] == pd.Timestamp("2026-08-01T00:00:00Z")
    assert y == [30.0, 30.1, 30.2]


def test_bridge_does_not_hide_stale_observation_gap():
    x, y, bridged = bridge_forecast_from_current(
        ["2026-08-01T00:10:00Z"], [30.2],
        current_timestamp="2026-08-01T00:00:00Z", current_value=30.0,
    )
    assert not bridged
    assert x == [pd.Timestamp("2026-08-01T00:10:00Z")]
    assert y == [30.2]
