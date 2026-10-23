"""Unit tests for the IRLON (SECOORA ERDDAP) loader (no network)."""
import gzip

import numpy as np
import pandas as pd

from experiments import irlon_load as il

CSV = "\n".join([
    "time,sea_water_temperature,sea_water_temperature_qc_agg,mole_concentration_of_nitrate_in_sea_water,"
    "mole_concentration_of_nitrate_in_sea_water_qc_agg,lwe_precipitation_rate,lwe_precipitation_rate_qc_agg,"
    "sea_water_ph_reported_on_total_scale,sea_water_ph_reported_on_total_scale_qc_agg",
    "UTC,degree_Celsius,,micromol.L-1,,mm.hour-1,,1,",
    "2024-01-01T00:00:00Z,24.0,1,-0.8,1,0.0,2,8.0,1",
    "2024-01-01T00:30:00Z,26.0,1,3.0,1,NaN,2,NaN,2",
    "2024-01-01T01:00:00Z,25.0,3,-9.0,1,2.5,2,12.0,1",
    "2024-01-01T02:00:00Z,45.0,1,1.0,4,1.0,1,8.1,2",
])


def test_request_url_encodes_operators_and_fixed_end():
    url = il.request_url("indian-river-lagoon-fort-pierce-", 2019)
    assert "time%3E%3D2019-01-01T00%3A00%3A00Z" in url and "time%3C2020-01-01" in url
    assert ">" not in url and "<" not in url
    assert "sea_water_temperature_qc_agg" in url
    last = il.request_url("indian-river-lagoon-fort-pierce-", il.LAST_YEAR)
    assert "time%3C%3D2026-10-16T23%3A59%3A59Z" in last


def test_parse_skips_units_row():
    frame = il.parse_erddap_csv(CSV)
    assert len(frame) == 4
    assert frame["time_utc"].iloc[0] == pd.Timestamp("2024-01-01 00:00")
    assert frame["sea_water_temperature"].iloc[0] == 24.0


def test_qc_keeps_flag1_rain_flag2_clips_no3_and_ranges():
    long, counts = il.qc_long(il.parse_erddap_csv(CSV), "FP")
    temp = long[long["var"] == "Temp"]
    # 25.0 is flag 3, 45.0 out of range -> only the two flag-1 readings of hour 0
    assert sorted(temp["value"]) == [24.0, 26.0]
    no3 = long[long["var"] == "NO3"]
    # -0.8 passes and is clipped to 0; -9 out of range; 1.0 flag 4 dropped
    assert sorted(no3["value"]) == [0.0, 3.0]
    rain = long[long["var"] == "Rain"]
    assert sorted(rain["value"]) == [0.0, 1.0, 2.5]  # flag 2 accepted for rain only
    ph = long[long["var"] == "pH"]
    assert list(ph["value"]) == [8.0]  # 12.0 out of range, 8.1 flag 2
    c = pd.DataFrame(counts).set_index("var")
    assert c.at["Temp", "n_flag3"] == 1 and c.at["Temp", "n_accepted"] == 2


def test_hourly_values_average_duplicates():
    long, _ = il.qc_long(il.parse_erddap_csv(CSV), "FP")
    hourly = il.hourly_values(long)
    t = hourly[(hourly["var"] == "Temp")]
    assert len(t) == 1 and t["value"].iloc[0] == 25.0
    assert t["hour_utc"].iloc[0] == pd.Timestamp("2024-01-01 00:00")


def test_build_hourly_reads_gzip_tree(tmp_path):
    path = il.raw_path(tmp_path, "FP", 2024)
    path.parent.mkdir(parents=True)
    path.write_bytes(gzip.compress(CSV.encode()))
    hourly, report = il.build_hourly(tmp_path)
    assert report["n_raw_rows"] == 4
    assert set(hourly["site"]) == {"FP"}
    assert np.isclose(hourly.loc[hourly["var"] == "NO3", "value"].sum(), 1.5)  # mean(0, 3) at hour 0


def test_station_table_codes_unique():
    st = il.station_table()
    assert len(st) == 13 and st["site"].is_unique
    assert set(st["cluster"]) == {"north_lagoon", "lagoon", "st_lucie"}
