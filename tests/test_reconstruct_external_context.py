import numpy as np
import pandas as pd

from experiments.reconstruct_external_context import VARIABLES, availability, to_records


def test_availability_is_end_of_run_day_plus_lag_and_never_after_valid_for_lead2():
    valid = pd.Series(pd.to_datetime(["2026-09-15 00:00", "2026-09-15 23:00"], utc=True))
    a1 = availability(valid, 1)
    assert (a1 == pd.Timestamp("2026-09-15 12:00", tz="UTC")).all()   # run day 09-14, end + 12 h
    a2 = availability(valid, 2)
    assert (a2 == pd.Timestamp("2026-09-14 12:00", tz="UTC")).all()
    assert (a2 < valid).all()


def test_to_records_schema_and_provenance():
    hourly = pd.DataFrame({"time": ["2026-09-15T06:00", "2026-09-15T07:00"]})
    for v in VARIABLES:
        hourly[f"{v}_previous_day1"] = [1.0, np.nan]
    hourly.loc[1, [f"{v}_previous_day1" for v in VARIABLES]] = np.nan
    records = to_records(hourly, "S", {"source": "map_station_NB1"}, 1)
    assert len(records) == 1  # all-NaN hour dropped
    r = records[0]
    assert r["provenance_class"] == "reconstructed_run"
    assert r["retrieved_at"] == "2026-09-15T12:00:00+00:00"
    assert r["valid_at"] == "2026-09-15T06:00:00+00:00"
    assert set(r["features"]) == set(VARIABLES)
