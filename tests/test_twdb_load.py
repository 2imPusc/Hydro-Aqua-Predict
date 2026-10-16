"""Unit tests for the TWDB coastal sonde loader (parsing, QC, cadence-aware hourly means). No network."""
import json

import numpy as np
import pandas as pd

from experiments import twdb_load as tl

HEADER = "# This data has been collected by a Texas Water Development Board datasonde.\n# Unit: C \n"


def _write(path, rows):
    path.write_text(HEADER + "datetime,value\n" + "".join(f"{t},{v}\n" for t, v in rows), encoding="utf-8")
    return path


def test_parse_csv_converts_dst_offsets_to_fixed_cst(tmp_path):
    path = _write(tmp_path / "x.csv", [("2021-07-01T00:00:00-0500", 30.0), ("2021-01-01T00:00:00-0600", 10.0)])
    s = tl.parse_csv(path)
    # summer CDT midnight = 23:00 CST of the previous day; winter unchanged
    assert list(s.index) == [pd.Timestamp("2020-12-31 23:00") + pd.Timedelta(hours=1), pd.Timestamp("2021-06-30 23:00")]
    assert s.loc["2021-06-30 23:00"] == 30.0


def test_parse_csv_empty_file(tmp_path):
    path = tmp_path / "e.csv"
    path.write_text(HEADER + "datetime,value\n", encoding="utf-8")
    assert tl.parse_csv(path).empty


def test_qc_range_spike_and_flatline():
    idx = pd.date_range("2015-01-01", periods=30, freq="h")
    values = 20 + 0.1 * np.arange(30)
    values[5] = 35.0      # spike (> 10 C from neighbours) but in range
    values[8] = 60.0      # outside physical range
    values[15:25] = 22.0  # 10 identical -> flatline (Temp REP_CNT_FAIL 8)
    out = tl.qc_series(pd.Series(values, index=idx), "Temp", tl.DEFAULT_QC)
    assert out["flag"].iloc[5] == "spike"
    assert out["flag"].iloc[8] == "range"
    assert (out["flag"].iloc[15:25] == "flatline").all()
    assert out["flag"].iloc[[0, 1, 2, 10, 26]].eq("ok").all()


def test_qc_spike_needs_close_neighbours():
    idx = pd.DatetimeIndex(["2015-01-01 00:00", "2015-01-01 01:00", "2015-01-03 00:00"])
    out = tl.qc_series(pd.Series([20.0, 35.0, 20.0], index=idx), "Temp", tl.DEFAULT_QC)
    assert out["flag"].tolist() == ["ok", "ok", "ok"]


def test_qc_fresh_salinity_floor_not_flatlined():
    idx = pd.date_range("2015-01-01", periods=20, freq="h")
    out = tl.qc_series(pd.Series(0.1, index=idx), "Sal", tl.DEFAULT_QC)
    assert out["flag"].eq("ok").all()
    out = tl.qc_series(pd.Series(15.0, index=idx), "Sal", tl.DEFAULT_QC)
    assert out["flag"].eq("flatline").all()


def test_hourly_min_obs_depends_on_native_cadence():
    fifteen = pd.Series([1.0, 2.0, 3.0], index=pd.DatetimeIndex(["2020-01-01 00:00", "2020-01-01 00:15", "2020-01-01 01:00"]))
    out = tl.hourly_from_good(fifteen, 15.0)
    assert list(out.index) == [pd.Timestamp("2020-01-01 00:00")] and out["value"].iloc[0] == 1.5
    hourly = pd.Series([1.0, 2.0], index=pd.DatetimeIndex(["2010-01-01 00:00", "2010-01-01 01:00"]))
    out = tl.hourly_from_good(hourly, 60.0)
    assert len(out) == 2 and (out["n_obs"] == 1).all()


def test_native_cadence_minutes():
    assert tl.native_cadence_minutes(pd.date_range("2020-01-01", periods=10, freq="15min")) == 15.0
    assert np.isnan(tl.native_cadence_minutes(pd.DatetimeIndex(["2020-01-01"])))


def test_load_qc_limits_reads_provider_json(tmp_path):
    (tmp_path / "parameters_ABC.json").write_text(json.dumps([
        {"code": "seawater_salinity", "MPRMIN": 0.5, "MPRMAX": 40.0, "THRSHLD_LOW": 7.0, "REP_TOLERANCE": 2,
         "REP_CNT_FAIL": 6}]), encoding="utf-8")
    limits = tl.load_qc_limits("ABC", tmp_path)
    assert limits["Sal"]["THRSHLD_LOW"] == 7.0 and limits["Sal"]["REP_CNT_FAIL"] == 6
    assert limits["Temp"] == tl.DEFAULT_QC["Temp"]


def test_load_hourly_end_to_end(tmp_path):
    raw = tmp_path / "raw"
    rows = [(f"2012-03-01T{h:02d}:00:00-0600", 20 + h * 0.1) for h in range(24)]
    _write((raw / "min" / "AAA").mkdir(parents=True) or raw / "min" / "AAA" / "AAA__water_temperature__2012.csv", rows)
    long, qc, used = tl.load_hourly(stations=["AAA"], variables=["Temp"], data_dir=raw)
    assert len(long) == 24 and set(long["variable"]) == {"Temp"}
    assert qc.loc[0, "hours_single_obs"] == 24 and qc.loc[0, "cadence_min"] == 60.0
    assert len(used) == 1


def test_write_once_never_overwrites(tmp_path):
    target = tmp_path / "a" / "f.csv"
    assert tl.write_once(target, b"first")
    assert not tl.write_once(target, b"second")
    assert target.read_bytes() == b"first"


def test_value_resolution_detects_quantised_salinity():
    assert tl.value_resolution(pd.Series([26.0, 27.0, 25.0])) == 1.0
    assert tl.value_resolution(pd.Series([26.1, 27.3, 25.0])) == 0.1
    assert tl.value_resolution(pd.Series([26.123, 27.301, 25.4])) == 0.001
