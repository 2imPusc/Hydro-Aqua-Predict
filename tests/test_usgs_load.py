"""Unit tests for the USGS SF Bay loader (no network)."""
from datetime import date

import numpy as np
import pandas as pd

from experiments.usgs_load import (
    depth_rank,
    hourly_means,
    dst_split,
    month_chunks,
    spring_forward,
    parse_iv_rdb,
    pss78_salinity,
    qc_mask,
    quarters,
    select_series,
    splice,
)

RDB = "\n".join([
    "# ---------------------------------- WARNING ----------------------------------------",
    "# Data provided for site 11455780",
    "#    TS_ID       Parameter Description",
    "#    16225       00010     Temperature, water, degrees Celsius, UPPER - 71 FT FROM BED",
    "#    16226       00010     Temperature, water, degrees Celsius, LOWER - 19 FT FROM BED",
    "#    16223       00095     Specific conductance, water, unfiltered, microsiemens per centimeter at 25 degrees Celsius",
    "#",
    "# Data-value qualification codes included in this output:",
    "#     A  Approved for publication -- Processing and review completed.",
    "#",
    "agency_cd\tsite_no\tdatetime\ttz_cd\t16225_00010\t16225_00010_cd\t16226_00010\t16226_00010_cd"
    "\t16223_00095\t16223_00095_cd",
    "5s\t15s\t20d\t6s\t14n\t10s\t14n\t10s\t14n\t10s",
    "USGS\t11455780\t2021-11-07 01:30\tPDT\t16.0\tA\t15.0\tA\t20000\tA",
    "USGS\t11455780\t2021-11-07 01:30\tPST\t16.2\tP\t15.2\tA\t20100\tA e",
    "USGS\t11455780\t2021-11-07 02:00\tPST\t\t\t15.4\tA\t20200\tA",
])


def test_parse_iv_rdb_tz_and_codes():
    long, desc = parse_iv_rdb(RDB)
    assert set(desc["ts_id"]) == {"16225", "16226", "16223"}
    t = long[(long.ts_id == "16225")].sort_values("time_utc")
    # 01:30 PDT = 08:30 UTC, 01:30 PST = 09:30 UTC (DST fall-back hour kept distinct)
    assert list(t["time_utc"]) == [pd.Timestamp("2021-11-07 08:30"), pd.Timestamp("2021-11-07 09:30")]
    assert list(t["code"]) == ["A", "P"]
    assert long[(long.ts_id == "16223")]["code"].tolist() == ["A", "A e", "A"]


def test_select_series_prefers_near_surface():
    _, desc = parse_iv_rdb(RDB)
    chosen = select_series(desc.assign(site="11455780"))
    assert set(chosen["ts_id"]) == {"16225", "16223"}
    only_lower = pd.DataFrame({"site": ["s"], "ts_id": ["1"], "pcode": ["00300"], "description": ["DO, LOWER-4 FT FROM BED"]})
    assert select_series(only_lower)["ts_id"].tolist() == ["1"]
    assert depth_rank("BOTTOM MOUNT") == 1 and depth_rank("BGC PROJECT") == 0 and depth_rank("") == 0


def test_splice_newer_ts_wins_on_overlap():
    t = pd.Timestamp("2022-01-01")
    long = pd.DataFrame({"site": "s", "pcode": "63680", "ts_id": ["16229", "314958", "16229"],
                         "time_utc": [t, t, t + pd.Timedelta("15min")], "value": [1.0, 2.0, 3.0], "code": "A"})
    out = splice(long).sort_values("time_utc")
    assert out["value"].tolist() == [2.0, 3.0]


def test_qc_mask_only_exact_A_and_in_range():
    var = pd.Series(["Temp", "Temp", "Temp", "pH"])
    val = pd.Series([10.0, 10.0, 50.0, 8.0])
    code = pd.Series(["A", "A e", "A", "P"])
    assert qc_mask(var, val, code).tolist() == [True, False, False, False]


def test_pss78_reference_values():
    assert abs(pss78_salinity([42914.0], 15.0)[0] - 35.0) < 1e-4
    # C(35, 25 C, 0) = 53.065 mS/cm
    assert abs(pss78_salinity([53065.0], 25.0)[0] - 35.0) < 0.01
    assert abs(pss78_salinity([0.0])[0]) < 0.02  # PSS-78 a0 = 0.008 (+ temperature term) at zero conductivity


def test_hourly_means_requires_two_obs():
    t0 = pd.Timestamp("2020-01-01 00:00")
    long = pd.DataFrame({"site": "s", "var": "Temp",
                         "time_utc": [t0, t0 + pd.Timedelta("15min"), t0 + pd.Timedelta("1h")],
                         "value": [10.0, 12.0, 9.0]})
    h = hourly_means(long)
    assert h["hour_utc"].tolist() == [t0] and h["value"].tolist() == [11.0] and h["n_raw"].tolist() == [2]


def test_quarters_and_months_clip():
    q = quarters(date(2017, 10, 15), date(2018, 2, 10))
    assert [x[0] for x in q] == ["2017Q4", "2018Q1"]
    assert q[0][1] == date(2017, 10, 15) and q[-1][2] == date(2018, 2, 10)
    m = month_chunks(date(2017, 12, 5), date(2018, 1, 31))
    assert m == [("2017-12", date(2017, 12, 5), date(2017, 12, 31)), ("2018-01", date(2018, 1, 1), date(2018, 1, 31))]
    assert np.isfinite(len(m))


def test_dst_split_skips_only_the_failing_utc_hour():
    assert spring_forward(2022) == date(2022, 3, 13) and spring_forward(2018) == date(2018, 3, 11)
    pieces = dst_split("2022Q1", date(2022, 1, 1), date(2022, 3, 31))
    assert [p[0] for p in pieces] == ["2022Q1a", "2022Q1-dst1", "2022Q1-dst2", "2022Q1b"]
    assert pieces[0][2] == "2022-03-12" and pieces[1][1:] == ("2022-03-13T08:00Z", "2022-03-13T09:59Z")
    assert pieces[2][1] == "2022-03-13T11:00Z" and pieces[3][1] == "2022-03-14"
    assert dst_split("2022Q2", date(2022, 4, 1), date(2022, 6, 30)) == [("2022Q2", "2022-04-01", "2022-06-30")]
