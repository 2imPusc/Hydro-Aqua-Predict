"""4TA SYNOP row parser and QC flags (scripts/import_vn_synop.py)."""
import pandas as pd

from scripts.import_vn_synop import parse_line, to_frame

HEADER = "Obs            TenTram     MaTram      Vido      Kinhdo    Mua06h(mm)  Mua24h(mm)  T2m(oC)"
FULL = ("2024090713     Bai Chay    48836       20.97     107.07     45.0        120.3      26.1"
        "        97.0        975.2       NE             45          25.0        29.4        ")
CALM = ("2000010107     Muong Te    48/01       22.37     102.83     0.0         0.0        10.5"
        "        xxxxx       xxxxxx      NaN            01          10.4        xxxx        ")
MISSING = ("2000010107     Tam Duong   48/03       22.42     103.48    xxxxxx      xxxxxx      xxxx"
           "        xxxxx       xxxxxx                     xx          xxxx        xxxx        ")


def test_header_and_comment_lines_skipped():
    assert parse_line(HEADER) is None
    assert parse_line("#  xxxx: la cac gia tri khong phat bao") is None
    assert parse_line("SO LIEU QUAN TRAC BE MAT") is None


def test_full_row_columns():
    row = parse_line(FULL)
    assert row[:3] == ["2024090713", "Bai Chay", "48836"]
    assert row[10] == "NE" and row[11] == "45"


def test_blank_wind_direction_keeps_alignment():
    row = parse_line(MISSING)
    assert len(row) == 14
    assert row[10] == "" and row[11] == "xx" and row[13] == "xxxx"


def test_frame_types_utc_and_missing():
    df = to_frame([parse_line(FULL), parse_line(CALM), parse_line(MISSING)])
    assert df.loc[0, "obs_utc"] == pd.Timestamp("2024-09-07 06:00")
    assert df.loc[0, "wspd_ms"] == 45.0 and df.loc[0, "wdir"] == "NE"
    assert pd.isna(df.loc[1, "wdir"]) and pd.isna(df.loc[1, "rh_pct"])
    assert df.loc[2, ["t2m_c", "wspd_ms", "ps_hpa"]].isna().all()
    assert (df["qc_flags"] == "").all()


def test_out_of_range_flagged_not_dropped():
    bad = FULL.replace("NE             45", "NE             98")
    df = to_frame([parse_line(bad)])
    assert df.loc[0, "wspd_ms"] == 98.0
    assert df.loc[0, "qc_flags"] == "wspd_ms;"
