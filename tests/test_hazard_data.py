import hashlib

import pytest

from datetime import date

from experiments.hazard_data import _year_chunks, era5_precip_target, parse_psl_ncss_csv, write_once


def test_year_chunks_and_precip_target_name():
    chunks = _year_chunks(2025, date(2026, 10, 20))
    assert chunks == [("2025-01-01", "2025-12-31"), ("2026-01-01", "2026-10-20")]
    target = era5_precip_target(1982, date(2026, 10, 20))
    assert target.name == "openmeteo_era5_precip_nb1_1982_20261020.csv"
    assert era5_precip_target(1982, date(2026, 10, 20), "best_match").name == "openmeteo_best_match_precip_nb1_1982_20261020.csv"
    assert target.parent.name == "era5"


def test_write_once_refuses_overwrite(tmp_path):
    target = tmp_path / "a.csv"
    meta = write_once(target, b"x,y\n1,2\n", url="http://example")
    assert meta["sha256"] == hashlib.sha256(b"x,y\n1,2\n").hexdigest()
    assert (tmp_path / "a.csv.manifest.json").exists()
    with pytest.raises(FileExistsError):
        write_once(target, b"other", url="http://example")


def test_parse_psl_ncss_csv_handles_header_and_missing():
    hdr = 'time,station,latitude[unit="degrees_north"],longitude[unit="degrees_east"],sst[unit="degC"]'
    cell = "GridPointRequestedAt[20.625N_107.125E],20.625,107.125"
    rows = [hdr, f"1982-07-01T00:00:00Z,{cell},27.72", f"1982-07-02T00:00:00Z,{cell},NaN",
            f"1982-07-03T00:00:00Z,{cell},"]
    text = "\n".join(rows) + "\n"
    s = parse_psl_ncss_csv(text)
    assert s.name == "sst"
    assert str(s.index.tz) == "UTC"
    assert len(s) == 3
    assert s.iloc[0] == pytest.approx(27.72)
    assert s.isna().sum() == 2


def test_fetch_era5_pins_model_in_params_name_and_manifest(tmp_path, monkeypatch):
    import json
    from datetime import date

    import pandas as pd

    from experiments import hazard_data as hd

    seen = {}

    def fake(url, params, chunks):
        seen.update(params)
        return pd.DataFrame({"time": pd.to_datetime(["2024-01-01T00:00"]).tz_localize("UTC"), "wind_speed_10m": [1.0]})

    monkeypatch.setattr(hd, "_open_meteo_hourly", fake)
    monkeypatch.setattr(hd.paths, "HAZARD_DATA_DIR", tmp_path)
    meta = hd.fetch_era5(2024, date(2024, 1, 2))
    assert seen["models"] == "era5"
    assert meta["file"] == "openmeteo_era5_nb1_2024_20240102.csv" and meta["model"] == "era5"
    manifest = json.loads((tmp_path / "era5" / "openmeteo_era5_nb1_2024_20240102.csv.manifest.json").read_text())
    assert manifest["model"] == "era5"
    hd.fetch_era5(2024, date(2024, 1, 2), model="best_match")
    assert seen["models"] == "best_match"
    with pytest.raises(ValueError):
        hd.fetch_era5(2024, date(2024, 1, 2), model="ifs")


def test_latest_era5_by_model_with_legacy_best_match(tmp_path, monkeypatch):
    from experiments import hazard_data as hd

    monkeypatch.setattr(hd.paths, "HAZARD_DATA_DIR", tmp_path)
    (tmp_path / "era5").mkdir()
    legacy = tmp_path / "era5" / "era5_nb1_1982_20261020.csv"
    legacy.write_text("x")
    (tmp_path / "era5" / "era5_precip_nb1_1982_20261020.csv").write_text("x")
    assert hd.latest_era5("best_match") == legacy  # legacy file was fetched without models= (best_match)
    with pytest.raises(FileNotFoundError):
        hd.latest_era5("era5")  # the legacy file must never pass as true ERA5
    true = tmp_path / "era5" / "openmeteo_era5_nb1_1982_20261016.csv"
    true.write_text("x")
    assert hd.latest_era5("era5") == true
    assert hd.latest_era5("best_match") == legacy


def test_main_era5_model_choice(monkeypatch):
    from experiments import hazard_data as hd

    got = {}
    monkeypatch.setattr(hd, "fetch_era5", lambda start_year, end, model="era5": got.update(model=model) or {"ok": 1})
    hd.main(["era5", "--model", "era5_seamless", "--start-year", "2020", "--end", "2020-01-02"])
    assert got["model"] == "era5_seamless"
    with pytest.raises(SystemExit):
        hd.main(["era5", "--model", "gfs"])


def test_fetch_era5_precip_pins_model_and_records_it(tmp_path, monkeypatch):
    import json
    import pandas as pd
    from experiments import hazard_data as hd

    seen = {}
    monkeypatch.setattr(hd.paths, "HAZARD_DATA_DIR", tmp_path)
    monkeypatch.setattr(hd, "_open_meteo_hourly", lambda url, params, chunks: seen.update(params) or pd.DataFrame({"time": ["t"], "precipitation": [0.1]}))
    meta = hd.fetch_era5_precip(2024, date(2024, 1, 2))
    assert seen["models"] == "era5" and seen["hourly"] == "precipitation"
    assert meta["file"] == "openmeteo_era5_precip_nb1_2024_20240102.csv" and meta["model"] == "era5"
    manifest = json.loads((tmp_path / "era5" / "openmeteo_era5_precip_nb1_2024_20240102.csv.manifest.json").read_text())
    assert manifest["model"] == "era5"
    with pytest.raises(ValueError):
        hd.fetch_era5_precip(2024, date(2024, 1, 2), model="ifs")


def test_latest_precip_by_model_with_legacy_best_match(tmp_path, monkeypatch):
    from experiments import hazard_data as hd

    monkeypatch.setattr(hd.paths, "HAZARD_DATA_DIR", tmp_path)
    (tmp_path / "era5").mkdir()
    legacy = tmp_path / "era5" / "era5_precip_nb1_1982_20261020.csv"
    legacy.write_text("x")
    assert hd.latest_precip("best_match") == legacy
    with pytest.raises(FileNotFoundError):
        hd.latest_precip("era5")
    true = tmp_path / "era5" / "openmeteo_era5_precip_nb1_1982_20261016.csv"
    true.write_text("x")
    assert hd.latest_precip("era5") == true
    assert hd.latest_era5.__name__  # temperature lookup is separate and unaffected


def test_main_era5_precip_model_choice(monkeypatch):
    from experiments import hazard_data as hd

    got = {}
    monkeypatch.setattr(hd, "fetch_era5_precip", lambda start_year, end, model="era5": got.update(model=model) or {"ok": 1})
    hd.main(["era5-precip", "--model", "best_match", "--start-year", "2020", "--end", "2020-01-02"])
    assert got["model"] == "best_match"
