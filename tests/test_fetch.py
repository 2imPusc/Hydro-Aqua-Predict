import pandas as pd

from core import fetch


def test_cache_mode_uses_complete_cached_history_without_network(monkeypatch):
    history = pd.DataFrame({
        "device": ["06M26042804"],
        "fetchedAt": ["2026-07-26T11:21:29Z"],
        "COD": [1.0], "NH4": [0.1], "pH": [7.8], "Temperature": [29.0], "TSS": [5.0],
    })
    monkeypatch.setattr(fetch, "USE_LOCAL_CSV", False)
    monkeypatch.setattr(fetch, "GREENLAB_FETCH_MODE", "cache")
    monkeypatch.setattr(fetch, "load_cached_history", lambda station: history)
    monkeypatch.setattr(fetch, "fetch_latest_snapshot", lambda station: (_ for _ in ()).throw(AssertionError("network must not run")))

    result = fetch.fetch_raw("06M26042804")

    assert len(result) == 1
    assert result.attrs["data_source"] == "greenlab_api_cache"
    assert "cache du lieu" in result.attrs["data_warning"]
