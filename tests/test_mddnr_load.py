"""Unit tests for the Maryland DNR Eyes on the Bay ConMon loader (no network)."""
import io

import numpy as np
import pandas as pd
import pytest

from experiments import mddnr_load as ml

HEADER = "Sample_date,Sample_Time,DateTime,Station,Layer,Salinity_ppt,pH,DO_mg/L,Turb_NTU,Temp_C\n"


def _csv(rows):
    return io.StringIO(HEADER + "".join(rows))


def test_read_raw_file_parses_justdownload_layout_and_blanks():
    text = _csv([
        "6/1/2010,0:00:23,06/01/2010 00:00,Patuxent River - Mataponi,BS,0.09,6.35,3,18,25.44\n",
        "6/1/2010,0:15:23,06/01/2010 00:15,Patuxent River - Mataponi,BS,0.09,6.35,2.93,,25.24\n",
        "6/1/2010,0:15:23,06/01/2010 00:15,Patuxent River - Mataponi,BS,9,9,9,9,9\n",  # duplicate stamp
    ])
    frame = ml.read_raw_file(text)
    assert sorted(frame.columns) == ["DO_mgl", "Sal", "Temp", "Turb", "pH"]
    assert frame.index.name == "time_est" and len(frame) == 2
    assert np.isnan(frame["Turb"].iloc[1])
    assert frame["Temp"].iloc[1] == pytest.approx(25.24)


def test_flatline_mask_flags_long_runs_but_exempts_fresh_salinity():
    idx = pd.date_range("2006-06-01", periods=20, freq="15min")
    s = pd.Series(np.r_[np.full(13, 7.5), np.arange(7) / 10 + 8], index=idx)
    mask = ml.flatline_mask(s, run=12)
    assert mask.iloc[:13].all() and not mask.iloc[13:].any()
    fresh = pd.Series(np.full(20, 0.1), index=idx)
    assert not ml.flatline_mask(fresh, run=12, exempt_below=0.5).any()


def test_spike_mask_flags_isolated_jump_only():
    idx = pd.date_range("2006-06-01", periods=9, freq="15min")
    s = pd.Series([10, 10.1, 10.2, 10.1, 0.0, 10.2, 10.3, 10.2, 10.1], index=idx)
    mask = ml.spike_mask(s, limit=5.0)
    assert mask.tolist() == [False] * 4 + [True] + [False] * 4


def test_qc_frame_range_then_tally():
    idx = pd.date_range("2006-06-01", periods=6, freq="15min")
    frame = pd.DataFrame({"pH": [7.9, 8.0, 12.0, 8.0, 7.95, np.nan]}, index=idx)
    clean, tally = ml.qc_frame(frame)
    assert np.isnan(clean["pH"].iloc[2])
    (t,) = tally
    assert t["n_range"] == 1 and t["n_blank_source"] == 1 and t["n_good"] == 4


def test_hourly_mean_needs_two_observations():
    idx = pd.to_datetime(["2006-06-01 00:00", "2006-06-01 00:15", "2006-06-01 01:00"])
    frame = pd.DataFrame({"Temp": [20.0, 22.0, 25.0]}, index=idx)
    hourly = ml.hourly_mean(frame)
    assert hourly.loc["2006-06-01 00:00", "Temp"] == pytest.approx(21.0)
    assert np.isnan(hourly.loc["2006-06-01 01:00", "Temp"])


def test_select_station_years_requires_cluster_and_drops_bottom_duplicates():
    table = pd.DataFrame({
        "station": ["A", "B", "C", "D", "E", "F", "PPB"],
        "lat": [38.0, 38.01, 38.02, 38.03, 38.04, 39.5, 38.0],
        "lon": [-76.0] * 5 + [-76.0, -76.0],
        "start": pd.to_datetime(["2005-04-01"] * 7),
        "end": pd.to_datetime(["2006-10-30"] * 4 + ["2005-10-30", "2006-10-30", "2006-10-30"]),
    })
    plan = ml.select_station_years(table, years=[2005, 2006], radius_km=30, min_sites=5)
    y2005 = set(plan.loc[plan.year == 2005, "station"])
    assert y2005 == {"A", "B", "C", "D", "E"}  # F is far; PPB dropped
    assert plan.loc[plan.year == 2006].empty  # only 4 nearby sites active in 2006


def test_data_url_contains_all_parameters_and_year_window():
    url = ml.data_url("CBL", 2004)
    for p in ml.PARAMETERS:
        assert f"parameter={p}" in url
    assert "StartDate=2004-01-01" in url and "EndDate=2004-12-31" in url and "outputtype=2" in url


def test_write_once_refuses_existing(tmp_path):
    target = tmp_path / "x.csv"
    ml.write_once(target, b"a")
    with pytest.raises(FileExistsError):
        ml.write_once(target, b"b")
    assert target.read_bytes() == b"a"
