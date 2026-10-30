"""Paper 1 / T3 helpers in experiments/paper1_t3_nerrs.py (no torch, no data needed)."""
import numpy as np
import pandas as pd
import pytest

from experiments.paper1_t3_nerrs import (
    FC_VARS,
    OBS_VARS,
    ForecastAsIssued,
    Station,
    availability,
    bootstrap_ratio,
    eligible,
    gate_nerrs,
    h1_rule,
    origin_marks,
    pair_outcomes,
    parse_flags,
    profile,
    weather_features,
)


def _forecast(start="2025-01-01", days=6):
    """Lead N value = 100 * N + hour index, so the chosen lead and hour are readable."""
    times = pd.date_range(start, periods=days * 24, freq="h")
    k = np.arange(len(times))
    cols = {"time": times.strftime("%Y-%m-%dT%H:%M")}
    for v in FC_VARS:
        for n in (1, 2, 3):
            cols[f"{v}_previous_day{n}"] = 100.0 * n + k
    return ForecastAsIssued(pd.DataFrame(cols))


def test_flags_parse_codes_with_suffixes():
    assert parse_flags(pd.Series(["<0> ", "<1> [GSM]", "<-3>", ""])).tolist()[:3] == [0, 1, -3]
    assert np.isnan(parse_flags(pd.Series([""]))[0])


def test_availability_is_day_after_run_day_plus_lag():
    v = np.array(["2025-01-03T05:00"], dtype="datetime64[ns]")
    assert availability(v, 1)[0] == np.datetime64("2025-01-03T12:00")
    assert availability(v, 2)[0] == np.datetime64("2025-01-02T12:00")


def test_forecast_lead_rule_future_and_past():
    fc = _forecast()
    origin = np.array(["2025-01-03T06:00"], dtype="datetime64[ns]")
    hours = np.array([["2025-01-03T10:00", "2025-01-03T13:00", "2025-01-04T03:00", "2025-01-02T20:00", "2025-01-03T01:00"]], dtype="datetime64[ns]")
    _, lead = fc.hourly(origin, hours)
    # same day before 12:00 -> lead 2; next day before noon -> lead 3; yesterday 20:00 -> lead 1 (avail 01-02 12:00)
    # today 01:00 (past): min(t, tau+12h) = 06:00 < 12:00 -> lead 2
    assert lead[0].tolist() == [2, 2, 3, 1, 2]


def test_forecast_interpolates_state_and_splits_rain():
    fc = _forecast()
    origin = np.array(["2025-01-05T00:00"], dtype="datetime64[ns]")
    marks = np.array([["2025-01-03T10:15", "2025-01-03T10:00"]], dtype="datetime64[ns]")
    out = fc.at_marks(origin, marks)
    k10 = 2 * 24 + 10
    assert out[0, 0, 0] == pytest.approx(100 + k10 + 0.25)          # lead 1, quarter way to 11:00
    assert out[0, 0, FC_VARS.index("precipitation")] == pytest.approx((100 + k10 + 1) / 4)  # hour ending 11:00
    assert out[0, 1, FC_VARS.index("precipitation")] == pytest.approx((100 + k10) / 4)


def _station(days=12, wx=True):
    idx = pd.date_range("2025-01-01", periods=days * 96, freq="15min", name="time_lst")
    minute = (idx.hour * 60 + idx.minute).to_numpy()
    frame = pd.DataFrame({"Temp": 20 + np.sin(2 * np.pi * minute / 1440)}, index=idx)
    for i, v in enumerate(OBS_VARS):
        frame[v] = float(i) if wx else np.nan
    return Station("S", frame, -5)


def test_profile_round_trip_and_no_lookahead_guard():
    st = _station()
    idx = st.index_of(np.array(["2025-01-10T06:00"], dtype="datetime64[ns]"))
    fut = np.arange(1, 49)
    assert np.allclose(profile(st, idx, fut), st.target(idx, fut))
    with pytest.raises(AssertionError, match="profile_reads_after_issue"):
        profile(st, idx, np.arange(1, 97))


def test_eligibility_needs_weather_and_context():
    st, dry = _station(), _station(wx=False)
    idx = st.index_of(np.array(["2025-01-10T06:00", "2025-01-02T06:00"], dtype="datetime64[ns]"))
    assert eligible(st, idx, ("obs",)).tolist() == [True, False]  # second origin has < 50 % of 7-day context
    assert eligible(dry, idx, ("obs",)).tolist() == [False, False]


def test_weather_features_window_edges():
    st = _station()
    st.obs[:, 0] = np.arange(st.n)  # ATemp = mark index
    idx = np.array([500])
    f = weather_features(st, "obs", idx, 60)
    assert f["wx_fut_ATemp"][0] == pytest.approx(np.mean([501, 502, 503, 504]))
    assert f["wx_past_ATemp"][0] == pytest.approx(np.mean(np.arange(405, 501)))
    assert f["wx_atemp_valid"][0] == 504 and f["wx_atemp_now"][0] == 500


def test_origin_marks_fixed_and_rotating():
    fixed = origin_marks("2025-01-01", "2025-01-02 12:00", (0, 6, 12, 18), rotate=False)
    assert len(fixed) == 7 and fixed[-1] == pd.Timestamp("2025-01-02 12:00")
    rot = origin_marks("2025-01-01", "2025-01-04 23:00", (0, 6, 12, 18), rotate=True)
    assert [t.hour for t in rot] == [0, 6, 12, 18]


def _frame(n_days=50, worse=0.2):
    rng = np.random.default_rng(0)
    t = pd.date_range("2025-01-01", periods=n_days * 4, freq="6h")
    rows = []
    for st in ("a", "b"):
        actual = rng.normal(size=len(t))
        rows.append(pd.DataFrame({"station": st, "issued_at": t, "horizon_minutes": 360, "actual": actual,
                                  "good": actual + rng.normal(0, 0.1, len(t)), "bad": actual + rng.normal(0, 0.1 + worse, len(t)),
                                  "block": np.repeat(np.arange(5), len(t) // 5)}))
    return pd.concat(rows, ignore_index=True)


def test_gate_and_outcomes():
    f = _frame()
    fwd, rev = gate_nerrs(f, "good", "bad", 6.0), gate_nerrs(f, "bad", "good", 6.0)
    assert fwd.gate_pass.all() and not rev.gate_pass.any() and fwd.blocks_beating.iloc[0] == 5
    o = pair_outcomes(fwd, rev)
    assert o.outcome.tolist() == ["candidate_wins"]
    ratio, lo, hi = bootstrap_ratio(f, "good", "bad")
    assert lo <= ratio <= hi < 1


def test_h1_rule_needs_both_long_horizons():
    o = pd.DataFrame({"horizon_minutes": [360, 720], "mae_ratio": [0.9, 0.94], "gate_pass": [True, True]})
    assert h1_rule(o)["holds"]
    o.loc[1, "gate_pass"] = False
    assert not h1_rule(o)["holds"]
