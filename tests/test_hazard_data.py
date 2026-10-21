import hashlib

import pytest

from experiments.hazard_data import parse_psl_ncss_csv, write_once


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
