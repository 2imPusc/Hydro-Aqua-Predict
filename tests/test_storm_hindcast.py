"""Pure-helper tests for experiments/storm_hindcast.py (synthetic frames, no data/network)."""
import json

import pandas as pd

from experiments import storm_hindcast as sh


def _passages():
    return pd.DataFrame({
        "SID": ["a", "b", "c", "d"],
        "SEASON": [2000, 2000, 2001, 2001],
        "NAME": ["A", "B", "C", "D"],
        "peak_time": pd.to_datetime(["2000-08-10T03:00Z", "2000-09-01T00:00Z", "2001-09-05T12:00Z", "2001-07-01T00:00Z"]),
        "site_beaufort": pd.array([9, 6, pd.NA, 11], dtype="Int64"),
        "qd18_level": pd.array([3, pd.NA, pd.NA, 3], dtype="Int64"),
    })


def test_band_counts_handles_na():
    out = sh.band_counts(_passages())
    assert out.loc[2000, "cap8_9"] == 1 and out.loc[2000, "cap6_7"] == 1
    assert out.loc[2001, "cap10_11"] == 1 and out.loc[2001, "cap8_9"] == 0
    assert out.loc[2000, "qd18_3"] == 1


def test_month_calendar_rates():
    cal = sh.month_calendar(_passages(), 2000, 2001)
    assert cal.loc[8, "storms_per_year_site_cap8_plus"] == 0.5
    assert cal.loc[7, "storms_per_year_site_cap8_plus"] == 0.5
    assert cal.loc[9, "storms_per_year_site_cap8_plus"] == 0.0  # Beaufort 6 and NA excluded


def test_events_check_match_and_unmatched():
    events = pd.DataFrame({"event_id": ["hit", "miss"], "hazard": ["storm", "storm"],
                           "start_date": ["2000-08-09", "1990-01-01"], "end_date": ["2000-08-11", "1990-01-02"],
                           "verified": ["yes", "no"]})
    out = sh.events_check(_passages(), events)
    assert bool(out.loc[0, "matched"]) and out.loc[0, "SID"] == "a"
    assert not bool(out.loc[1, "matched"]) and out.loc[1, "SID"] is None


def test_json_default_maps_na_to_none():
    assert json.loads(json.dumps({"x": pd.NA}, default=sh._json_default)) == {"x": None}
