import numpy as np
import pandas as pd

from scripts.sensor_coverage import daily_coverage

TZ = "Asia/Ho_Chi_Minh"


def _minutes(start_local: str, periods: int) -> pd.Series:
    return pd.Series(pd.date_range(start_local, periods=periods, freq="min", tz=TZ).tz_convert("UTC"))


def _frame(times: pd.Series, cod) -> pd.DataFrame:
    return pd.DataFrame({"device": "S", "fetchedAt": times, "COD": cod})


def test_daily_coverage_counts_local_minutes_and_fills_missing_days():
    day1 = _frame(_minutes("2026-09-01 00:00", 1440), np.linspace(20, 30, 1440))
    day3 = _frame(_minutes("2026-09-03 00:00", 720), np.linspace(20, 30, 720))
    out = daily_coverage(pd.concat([day1, day3], ignore_index=True)).set_index("date")
    assert out.loc[pd.Timestamp("2026-09-01").date(), "coverage"] == 1.0
    assert bool(out.loc[pd.Timestamp("2026-09-01").date(), "meets_gate"]) is True
    assert out.loc[pd.Timestamp("2026-09-02").date(), "minutes"] == 0
    assert out.loc[pd.Timestamp("2026-09-02").date(), "cod_status"] == "NO_DATA"
    assert out.loc[pd.Timestamp("2026-09-03").date(), "coverage"] == 0.5
    assert bool(out.loc[pd.Timestamp("2026-09-03").date(), "meets_gate"]) is False


def test_daily_coverage_flags_cod_rail_and_out_of_range():
    rail = _frame(_minutes("2026-09-01 00:00", 60), [558.8] * 60)
    high = _frame(_minutes("2026-09-02 00:00", 60), np.linspace(185, 195, 60))
    ok = _frame(_minutes("2026-09-03 00:00", 60), np.linspace(20, 30, 60))
    out = daily_coverage(pd.concat([rail, high, ok], ignore_index=True)).set_index("date")
    d = lambda s: pd.Timestamp(s).date()
    assert out.loc[d("2026-09-01"), "cod_status"] == "INVALID"
    assert out.loc[d("2026-09-01"), "cod_rail_share"] == 1.0
    assert out.loc[d("2026-09-02"), "cod_status"] == "INVALID"   # >100 is outside PLAUSIBLE_RANGE
    assert out.loc[d("2026-09-02"), "cod_in_range_share"] == 0.0
    assert out.loc[d("2026-09-03"), "cod_status"] == "VALID"
    assert out.loc[d("2026-09-03"), "cod_median"] == 25.0


def test_daily_coverage_empty():
    assert daily_coverage(pd.DataFrame(columns=["device", "fetchedAt", "COD"])).empty


def test_daily_coverage_extends_to_until_with_dead_days():
    import datetime as dt

    hist = pd.concat([
        _frame(_minutes("2026-09-20 00:00", 1440), np.linspace(20, 30, 1440)),
        _frame(_minutes("2026-09-21 00:00", 1440), np.linspace(20, 30, 1440)),
    ], ignore_index=True)
    out = daily_coverage(hist, until=dt.date(2026, 9, 25)).set_index("date")
    for day in range(22, 26):
        row = out.loc[dt.date(2026, 9, day)]
        assert row["minutes"] == 0
        assert bool(row["meets_gate"]) is False
        assert row["cod_status"] == "NO_DATA"
    assert not out.tail(3)["meets_gate"].any()


def test_daily_coverage_all_nan_cod_is_no_data():
    out = daily_coverage(_frame(_minutes("2026-09-01 00:00", 60), [np.nan] * 60)).set_index("date")
    row = out.loc[pd.Timestamp("2026-09-01").date()]
    assert row["cod_status"] == "NO_DATA"
    assert row["minutes"] == 60
