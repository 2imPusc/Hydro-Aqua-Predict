"""Pure-helper tests for experiments/storm_damage.py (synthetic frames, no data/network)."""
import hashlib

import pandas as pd
import pytest

from experiments import storm_damage as sd


def test_archive_url_from_available_ok():
    payload = {"archived_snapshots": {"closest": {"available": True, "status": "200",
                                                  "url": "http://web.archive.org/web/2024/https://x.vn/a"}}}
    assert sd.archive_url_from_available(payload) == "https://web.archive.org/web/2024/https://x.vn/a"


@pytest.mark.parametrize("payload", [
    {}, {"archived_snapshots": {}},
    {"archived_snapshots": {"closest": {"available": False, "status": "200", "url": "http://web.archive.org/x"}}},
    {"archived_snapshots": {"closest": {"available": True, "status": "404", "url": "http://web.archive.org/x"}}},
])
def test_archive_url_from_available_missing(payload):
    assert sd.archive_url_from_available(payload) == ""


def test_sha256_file(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"abc")
    assert sd.sha256_file(p) == hashlib.sha256(b"abc").hexdigest()


def test_write_once_copy_creates_and_refuses_overwrite(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("hello", encoding="utf-8")
    dst = tmp_path / "out" / "e1__page.txt"
    assert sd.write_once_copy(src, dst) == hashlib.sha256(b"hello").hexdigest()
    # identical content: reuse silently
    assert sd.write_once_copy(src, dst) == hashlib.sha256(b"hello").hexdigest()
    src.write_text("changed", encoding="utf-8")
    with pytest.raises(FileExistsError):
        sd.write_once_copy(src, dst)
    assert dst.read_text(encoding="utf-8") == "hello"


@pytest.mark.parametrize("a,b", [("Son Tinh", "SON-TINH"), ("son-tinh", "SONTINH"), ("Yagi", "YAGI")])
def test_norm_name(a, b):
    assert sd.norm_name(a) == sd.norm_name(b)


def _passages():
    return pd.DataFrame({
        "SID": ["s1", "s2", "s3"], "SEASON": [2024, 2024, 2012], "NAME": ["YAGI", "TRAMI", "SON-TINH"],
        "site_wind_ms": [30.0, 12.0, 20.0], "site_beaufort": pd.array([11, 6, 8], dtype="Int64"),
    })


def test_match_passage_by_name_and_season():
    row = sd.match_passage(_passages(), "Son Tinh", 2012)
    assert row["SID"] == "s3"
    assert sd.match_passage(_passages(), "Yagi", 2023) is None
    assert sd.match_passage(_passages(), "Unknown", 2024) is None


def test_match_passage_prefers_strongest_duplicate():
    p = pd.concat([_passages(), pd.DataFrame({"SID": ["s4"], "SEASON": [2024], "NAME": ["YAGI"],
                                              "site_wind_ms": [35.0],
                                              "site_beaufort": pd.array([12], dtype="Int64")})])
    assert sd.match_passage(p, "YAGI", 2024)["SID"] == "s4"


@pytest.mark.parametrize("cls,major", [("catastrophic", True), ("major", True), ("minor", False), ("none", False)])
def test_is_major(cls, major):
    assert sd.is_major(cls) is major


def test_is_major_rejects_unknown():
    with pytest.raises(ValueError):
        sd.is_major("bad")


def test_beaufort_band():
    assert sd.beaufort_band(5) == "<=5"
    assert sd.beaufort_band(7) == "6-7"
    assert sd.beaufort_band(9) == "8-9"
    assert sd.beaufort_band(11) == "10-11"
    assert sd.beaufort_band(12) == ">=12"
    assert sd.beaufort_band(pd.NA) == "unknown"


def test_separation_detected():
    out = sd.separation_check([6, 7, 7, 9, 11], [0, 0, 0, 1, 1])
    assert out["separated"] is True
    assert out["max_negative"] == 7 and out["min_positive"] == 9
    assert out["threshold_midpoint"] == 8.0


def test_separation_overlap():
    out = sd.separation_check([6, 8, 9, 9], [0, 1, 0, 1])
    assert out["separated"] is False
    assert out["overlap"] == [8, 9]


def test_fit_fragility_refuses_separated_or_small():
    res = sd.fit_fragility([6, 7, 9, 11], [0, 0, 1, 1], min_n=4)
    assert res["fitted"] is False and res["reason"] == "perfect_separation"
    res = sd.fit_fragility([6, 9, 8], [0, 1, 0], min_n=10)
    assert res["fitted"] is False and res["reason"] == "too_few_events"
    res = sd.fit_fragility([6, 6, 6], [0, 0, 0], min_n=2)
    assert res["fitted"] is False and res["reason"] == "single_class"


def test_fit_fragility_overlapping_data():
    x = [5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11]
    y = [0, 0, 0, 0, 1, 0, 1, 1, 0, 1, 1, 1]
    res = sd.fit_fragility(x, y, min_n=10)
    assert res["fitted"] is True
    assert res["slope"] > 0
    assert 7 < res["beaufort_p50"] < 10


def test_bootstrap_p50_reproducible_and_ordered():
    x = [5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11]
    y = [0, 0, 0, 0, 1, 0, 1, 1, 0, 1, 1, 1]
    a = sd.bootstrap_p50(x, y, n_boot=200, seed=1)
    b = sd.bootstrap_p50(x, y, n_boot=200, seed=1)
    assert a == b
    assert a["p50_lo"] <= a["p50_median"] <= a["p50_hi"]
    assert 0 < a["n_ok"] <= 200


def test_onset_table():
    df = pd.DataFrame({"asset_group": ["wood", "wood", "wood", "hdpe"],
                       "damage_class": ["none", "minor", "major", "none"],
                       "site_beaufort": pd.array([7, 8, 10, 8], dtype="Int64")})
    out = sd.onset_table(df).set_index("asset_group")
    assert out.loc["wood", "min_bf_any_damage"] == 8
    assert out.loc["wood", "min_bf_major"] == 10
    assert out.loc["wood", "max_bf_no_damage"] == 7
    assert out.loc["hdpe", "n_none"] == 1 and pd.isna(out.loc["hdpe", "min_bf_major"])
