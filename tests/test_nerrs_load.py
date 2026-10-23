"""Unit tests for the NERRS Jobos Bay loader (direction-4 methods pilot)."""
import math

import numpy as np
import pandas as pd
import pytest

from experiments.nerrs_load import (
    attribute_station_coordinates,
    dms_to_decimal,
    haversine_km,
    hourly_mean,
    parse_flag,
    parse_met_coordinates,
    parse_met_stated_distances,
    read_met_file,
    read_wq_file,
)


@pytest.mark.parametrize(
    "cell, expected",
    [("<0> ", 0), ("<0> (CND)", 0), ("<1> [SSM] (CSM)", 1), ("<-3>", -3), ("<4>  ", 4), ("", None), (None, None)],
)
def test_parse_flag_reads_integer_and_ignores_trailing_codes(cell, expected):
    assert parse_flag(cell) == expected


def test_dms_to_decimal_west_is_negative():
    assert dms_to_decimal(17, 56, 36.8, "N") == pytest.approx(17.943556, abs=1e-6)
    assert dms_to_decimal(66, 14, 18.5, "W") == pytest.approx(-66.238472, abs=1e-6)


def test_haversine_one_minute_of_latitude_is_about_1_853_km():
    assert haversine_km(17.0, -66.0, 17.0 + 1 / 60, -66.0) == pytest.approx(1.853, abs=0.005)
    assert haversine_km(17.9, -66.2, 17.9, -66.2) == 0.0


def test_attribute_station_coordinates_handles_garbled_degree_and_missing_quotes():
    text = (
        "Station 9 is an impacted site. The station pole is located at 17� 56' 37.22\" N and 66� 14' 18.54\" W. "
        "Station 10 is located in a mangrove lagoon. It provides a reference. The pole is located at "
        "17� 56' 19.00 N, 66� 15' 27.85\" W. Fresh water input ... "
        "Station 20 is located in the inner eastern section. The pole is located at 17�55' 49.14\"N, 66�12' 41.30\"W"
    )
    coords = attribute_station_coordinates(text)
    assert set(coords) == {"09", "10", "20"}
    assert coords["10"] == pytest.approx((17.938611, -66.257736), abs=1e-5)
    assert coords["20"][0] == pytest.approx(17.930317, abs=1e-5)


def test_parse_met_coordinates_and_stated_distances():
    text = (
        "Its coordinates are latitude 17 57� 23.498� and longitude 66 14� 18.690�. "
        "2.2 Km. from S09\r4.2 Km. from S10\r1.8 Km. from S19\r3.1 Km. from S20"
    )
    lat, lon = parse_met_coordinates(text)
    assert lat == pytest.approx(17.956527, abs=1e-5)
    assert lon == pytest.approx(-66.238525, abs=1e-5)
    assert parse_met_stated_distances(text) == {"09": 2.2, "10": 4.2, "19": 1.8, "20": 3.1}


WQ_CSV = (
    '"DateTimeStamp","Historical","ProvisionalPlus","F_Record","Temp","F_Temp","Sal","F_Sal","pH","F_pH",\n'
    '01/01/2008 0:00,0,0,"",26.2,<0> ,35.5,<0> ,8.3,<0> (CND),\n'
    '01/01/2008 0:15,0,0,"",26.4,<1> [GSM],35.4,<0> ,8.2,<-3> ,\n'
    '01/01/2008 0:30,0,0,"","",<-2> ,35.3,<4> ,8.1,<0> ,\n'
)


def test_read_wq_file_keeps_only_good_flag_and_counts_flags(tmp_path):
    path = tmp_path / "job19wq2008.csv"
    path.write_text(WQ_CSV)
    frame, flags = read_wq_file(path, variables=("Temp", "Sal", "pH"))
    assert list(frame["Temp"].dropna()) == [26.2]
    assert list(frame["Sal"].dropna()) == [35.5, 35.4]
    assert list(frame["pH"].dropna()) == [8.3, 8.1]
    assert frame.index[1] == pd.Timestamp("2008-01-01 00:15")
    temp = flags[(flags["variable"] == "Temp")].set_index("flag")["n"].to_dict()
    assert temp == {0: 1, 1: 1, -2: 1}


MET_CSV = (
    '"DatetimeStamp","Historical","ProvisionalPlus","Frequency","F_Record","WSpd","F_WSpd","TotPrcp","F_TotPrcp",\n'
    '01/01/2005 0:00,1,1,144,"",1.4,<0> ,25.0,<0> ,\n'
    '01/01/2005 0:00,1,1,15,"",2.0,<0> ,0.5,<0> ,\n'
    '01/01/2005 0:00,1,1,60,"",1.4,<0> ,2.0,<0> ,\n'
    '01/01/2005 0:15,1,1,15,"",3.0,<0> ,0.25,<0> ,\n'
)


def test_read_met_file_keeps_only_15_minute_rows(tmp_path):
    path = tmp_path / "jobjbmet2005.csv"
    path.write_text(MET_CSV)
    frame, _ = read_met_file(path, variables=("WSpd", "TotPrcp"))
    assert len(frame) == 2
    assert frame["TotPrcp"].sum() == pytest.approx(0.75)


def test_hourly_mean_requires_min_observations():
    idx = pd.to_datetime(["2008-01-01 00:00", "2008-01-01 00:15", "2008-01-01 01:00"])
    frame = pd.DataFrame({"Temp": [26.0, 27.0, 30.0]}, index=idx)
    hourly = hourly_mean(frame, min_obs=2)
    assert hourly.loc[pd.Timestamp("2008-01-01 00:00"), "Temp"] == 26.5
    assert math.isnan(hourly.loc[pd.Timestamp("2008-01-01 01:00"), "Temp"])
    assert np.isfinite(hourly["Temp"]).sum() == 1
