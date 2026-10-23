from datetime import date

import pytest

from scripts.backfill_sensor import (
    chunk_path, last_covered_date, plan_chunks, run_backfill, write_new,
)

HEADER = "Date,DeviceSerialNumber,SensorType,Value,Unit,Status\n"


def test_plan_chunks_overlap_by_one_day_and_cap_length():
    chunks = plan_chunks(date(2026, 7, 26), date(2026, 8, 10), max_days=7)
    assert chunks == [
        (date(2026, 7, 26), date(2026, 8, 1)),
        (date(2026, 8, 1), date(2026, 8, 7)),
        (date(2026, 8, 7), date(2026, 8, 10)),
    ]
    assert all((end - start).days <= 6 for start, end in chunks)


def test_plan_chunks_single_day_and_empty():
    assert plan_chunks(date(2026, 9, 1), date(2026, 9, 1)) == [(date(2026, 9, 1), date(2026, 9, 1))]
    assert plan_chunks(date(2026, 9, 2), date(2026, 9, 1)) == []


def test_plan_chunks_rejects_max_days_below_two():
    with pytest.raises(ValueError):
        plan_chunks(date(2026, 9, 1), date(2026, 9, 5), max_days=1)


def test_chunk_path_matches_node_fetcher_naming(tmp_path):
    path = chunk_path(tmp_path, "06M26042804", "HAIPHONG", date(2026, 7, 5), date(2026, 7, 26))
    assert path.name == "06M26042804_HAIPHONG_20260705_to_20260726.csv"


def test_last_covered_date_reads_csv_names_only(tmp_path):
    (tmp_path / "06M26042804_HAIPHONG_20260705_to_20260726.csv").write_text(HEADER)
    (tmp_path / "06M26042804_HAIPHONG_20260801_to_20260901.json").write_text("{}")
    (tmp_path / "06M26042803_QUANGNINH_20260101_to_20261001.csv").write_text(HEADER)
    assert last_covered_date(tmp_path, "06M26042804") == date(2026, 7, 26)
    assert last_covered_date(tmp_path, "XXXX") is None


def test_write_new_never_overwrites(tmp_path):
    target = tmp_path / "a.csv"
    assert write_new(target, "first") is True
    assert write_new(target, "second") is False
    assert target.read_text() == "first"


def test_run_backfill_skips_existing_and_empty_chunks(tmp_path):
    existing = chunk_path(tmp_path, "S", "R", date(2026, 7, 26), date(2026, 8, 1))
    existing.write_text("original")
    calls = []

    def fake_fetch(station, start, end):
        calls.append((start, end))
        if start == "2026-08-07":
            return HEADER  # provider had no rows for this chunk
        return HEADER + f"{start} 00:00,S,pH,8.0,,Good\n"

    results = run_backfill("S", "R", date(2026, 7, 26), date(2026, 8, 10), tmp_path, fetch=fake_fetch, log=lambda _: None)
    assert [r["status"] for r in results] == ["exists", "written", "empty"]
    assert calls == [("2026-08-01", "2026-08-07"), ("2026-08-07", "2026-08-10")]
    assert existing.read_text() == "original"
    assert not chunk_path(tmp_path, "S", "R", date(2026, 8, 7), date(2026, 8, 10)).exists()
