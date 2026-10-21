import hashlib

import pytest

from experiments.hazard_data import parse_erddap_csv, write_once


def test_write_once_refuses_overwrite(tmp_path):
    target = tmp_path / "a.csv"
    meta = write_once(target, b"x,y\n1,2\n", url="http://example")
    assert meta["sha256"] == hashlib.sha256(b"x,y\n1,2\n").hexdigest()
    assert (tmp_path / "a.csv.manifest.json").exists()
    with pytest.raises(FileExistsError):
        write_once(target, b"other", url="http://example")


def test_parse_erddap_csv_skips_units_row():
    text = ("time,depth,latitude,longitude,sst\nUTC,m,degrees_north,degrees_east,Celsius\n"
            "2024-07-01T12:00:00Z,0.0,20.625,107.125,30.23\n2024-07-02T12:00:00Z,0.0,20.625,107.125,NaN\n")
    s = parse_erddap_csv(text)
    assert list(s.round(2).dropna()) == [30.23]
    assert str(s.index.tz) == "UTC"
