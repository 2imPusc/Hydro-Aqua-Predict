"""Paper 1 / T4b helpers (no torch, no data needed)."""
import json

import numpy as np
import pandas as pd

from experiments import paper1_t3_nerrs as t3
from experiments import paper1_t4b_hybrid as t4b
from experiments import paper1_t4b_step0 as step0


class FakeForecaster:
    """Forecast = last context value + step number; records what it saw."""

    def __init__(self):
        self.seen = []

    def quantile_paths(self, context, length, batch):
        self.seen.append(context.copy())
        last = context[:, -1][:, None]
        q = last + np.arange(1, length + 1)[None, :]
        return np.repeat(q[:, :, None], 7, axis=2)


def _station(n=4000, start="2025-01-01"):
    idx = pd.date_range(start, periods=n, freq="15min", name="time_lst")
    frame = pd.DataFrame({"Temp": 20 + np.sin(np.arange(n) * 2 * np.pi / 96)}, index=idx)
    for v in t3.OBS_VARS:
        frame[v] = np.nan
    return t3.Station("apacpwq", frame, -5)


def test_context_ignores_the_future():
    st = _station()
    idx = np.array([1000, 2000])
    fm_a, fm_b = FakeForecaster(), FakeForecaster()
    a = t4b.chronos_frame(st, idx, fm_a, False)
    st.temp[1001:1200] += 50.0   # after origin 1000, before origin 2000's context would be hit is irrelevant for origin 1000
    b = t4b.chronos_frame(st, idx[:1], fm_b, False)
    assert a[a.issued_at == a.issued_at.min()].q50.tolist() == b.q50.tolist()
    assert fm_b.seen[0].shape == (1, t3.CONTEXT)
    assert fm_b.seen[0][0, -1] == np.float32(st.temp[1000])


def test_chronos_frame_picks_the_horizon_step():
    st = _station()
    frame = t4b.chronos_frame(st, np.array([1000]), FakeForecaster(), False)
    got = frame.set_index("horizon_minutes").q50
    for h in t3.HORIZONS:
        assert np.isclose(got[h], st.temp[1000] + h // t3.STEP, atol=1e-5)
    assert set(frame.columns) == {"station", "issued_at", "horizon_minutes", "q50"}


def test_train_origins_end_before_test_and_are_3h():
    n = int((pd.Timestamp(step0.TEST[0]) - pd.Timestamp(step0.GRID_START)).total_seconds() // 900) + 200
    idx = pd.date_range(step0.GRID_START, periods=n, freq="15min", name="time_lst")
    frame = pd.DataFrame({"Temp": 20.0}, index=idx)
    for v in t3.OBS_VARS:
        frame[v] = np.nan
    st = t3.Station("x", frame, -5, _full_forecast())
    got = t4b.train_indices_3h(st)
    assert set(np.diff(got)) <= {12} or (np.diff(got) % 12 == 0).all()
    last_valid = st.t0 + (got.max() + t3.LENGTH) * np.timedelta64(15, "m")
    assert last_valid <= np.datetime64(step0.TEST[0])
    assert st.t0 + got.min() * np.timedelta64(15, "m") >= np.datetime64(step0.TRAIN[0])


def _full_forecast():
    times = pd.date_range(t3.FC_START, t3.FC_END + " 23:00", freq="h")
    cols = {"time": times.strftime("%Y-%m-%dT%H:%M")}
    for v in t3.FC_VARS:
        for n in t3.FC_LEADS:
            cols[f"{v}_previous_day{n}"] = np.ones(len(times))
    return t3.ForecastAsIssued(pd.DataFrame(cols))


def test_residual_and_combine_arms():
    assert t4b.residual_target(np.array([21.0]), np.array([20.5]))[0] == 0.5
    frame = pd.DataFrame({"horizon_minutes": [15, 180, 360, 720], "none": [1.0, 1.0, 1.0, 1.0], "ridge-B5D-fc": [3.0, 3.0, 3.0, 3.0]})
    out = t4b.combine(frame)
    assert out["avg"].tolist() == [2.0] * 4
    assert out["switch-180"].tolist() == [1.0, 1.0, 3.0, 3.0]


def test_fit_station_recovers_a_weather_residual():
    """Chronos misses a term linear in future air temperature: resid-none must learn it causally."""
    n = 96 * 460
    idx = pd.date_range("2024-01-11", periods=n, freq="15min", name="time_lst")
    rng = np.random.default_rng(0)
    times = pd.date_range(t3.FC_START, t3.FC_END + " 23:00", freq="h")
    air = pd.Series(rng.normal(0, 3, len(times)), index=times).rolling(6, min_periods=1).mean().to_numpy()
    cols = {"time": times.strftime("%Y-%m-%dT%H:%M")}
    for v in t3.FC_VARS:
        for lead in t3.FC_LEADS:
            cols[f"{v}_previous_day{lead}"] = air if v == "temperature_2m" else np.zeros(len(times))
    fc = t3.ForecastAsIssued(pd.DataFrame(cols))
    frame = pd.DataFrame({"Temp": 20 + 0.1 * rng.normal(size=n)}, index=idx)
    for v in t3.OBS_VARS:
        frame[v] = np.nan
    st = t3.Station("apacpwq", frame, -5, fc)
    marks = st.t0 + np.arange(n) * np.timedelta64(15, "m")
    utc = marks + np.timedelta64(5, "h")
    pos = ((utc.astype("datetime64[h]") - times[0].to_datetime64()) / np.timedelta64(1, "h")).astype(int)
    st.temp = st.temp + 0.3 * air[np.clip(pos, 0, len(air) - 1)]

    train = t4b.train_indices_3h(st)
    test_idx = st.index_of(t3.origin_marks("2025-02-01", "2025-03-15", (0, 6, 12, 18), False).to_numpy())

    def q50(idx_):
        rows = []
        for h in t3.HORIZONS:
            rows.append(pd.DataFrame({"issued_at": st.t0 + idx_ * np.timedelta64(15, "m"), "horizon_minutes": h, "q50": 20.0}))
        return pd.concat(rows, ignore_index=True)

    preds, lambdas = t4b.fit_station(st, test_idx, q50(test_idx), q50(train))
    wide = pd.concat(preds, ignore_index=True)
    at = wide[wide.horizon_minutes == 720].dropna(subset=["actual"])
    assert (at["resid-none"] - at.actual).abs().mean() < (at["none"] - at.actual).abs().mean()
    labels = {r["model"] for r in lambdas}
    assert labels == {"ridge-B4D-n", "ridge-B5D-fc", "ridge-B5D-fc-3h", "stack-B5D", "resid-none"}
    n3 = {r["model"]: r["n_train"] for r in lambdas if r["horizon_minutes"] == 720}
    assert n3["stack-B5D"] == n3["resid-none"] == n3["ridge-B5D-fc-3h"] < n3["ridge-B5D-fc"]


def test_block_end_leaves_no_empty_block():
    issued = pd.date_range("2025-02-01", "2025-12-31 06:00", freq="6h")
    blocks = step0.block_of(issued, "2025-12-31 06:00")
    assert set(blocks) == set(range(5))
    assert blocks[0] == 0 and blocks[-1] == 4


def _ratios(a, b, c):
    return {"A": a, "B": b, "C": c}


def test_reserve_call_win_needs_every_reserve_and_two_cis():
    hi_ok = _ratios(0.98, 0.99, 1.01)
    lo = _ratios(0.9, 0.9, 0.9)
    assert t4b.reserve_call(_ratios(0.9, 0.9, 0.95), lo, hi_ok, True, False, 0.01) == "win"
    assert t4b.reserve_call(_ratios(0.9, 0.9, 1.01), lo, hi_ok, True, False, 0.01) == "tie"
    assert t4b.reserve_call(_ratios(0.9, 0.9, 0.95), lo, _ratios(0.98, 1.01, 1.01), True, False, 0.01) == "tie"
    assert t4b.reserve_call(_ratios(0.9, 0.9, 0.95), lo, hi_ok, True, False, 0.2) == "tie"
    assert t4b.reserve_call(_ratios(0.9, 0.9, 0.95), lo, hi_ok, False, False, 0.01) == "tie"


def test_reserve_call_loss_is_the_mirror():
    assert t4b.reserve_call(_ratios(1.1, 1.1, 1.05), _ratios(1.02, 1.01, 0.99), _ratios(1.2, 1.2, 1.2), False, True, 0.01) == "loss"
    assert t4b.reserve_call(_ratios(1.1, 1.1, 0.99), _ratios(1.02, 1.01, 0.9), _ratios(1.2, 1.2, 1.2), False, True, 0.01) == "tie"


def test_labels_and_encoding_reading():
    assert [t4b.arm_label(n) for n in (0, 1, 3, 4, 6)] == ["not_supported", "partial", "partial", "supported", "supported"]
    assert t4b.encoding_reading({360: "tie", 720: "loss"}).startswith("ridge_advantage")
    assert t4b.encoding_reading({360: "win", 720: "tie"}).startswith("t3_gap")


def test_holm_family_is_42():
    assert sum(len(h) for _, _, h in t4b.primary_pairs()) == 42
    assert ("switch-180", "ridge-B5D-fc", (15, 30, 60, 180)) in t4b.primary_pairs()
    assert ("switch-180", "none", (360, 720)) in t4b.primary_pairs()


def test_trained_arms_use_same_origin_reference():
    assert all(t4b.REF_RIDGE[a] == "ridge-B5D-fc-3h" for a in t4b.TRAINED_ARMS)


def test_station_stats():
    m = pd.Series(np.arange(1, 13) * 0.9, index=[f"s{i}" for i in range(12)])
    r = pd.Series(np.arange(1, 13) * 1.0, index=m.index)
    s = t4b.station_stats(m, r)
    assert s["stations_won"] == 12 and np.isclose(s["median_skill"], 0.1)
    assert s["sign_p"] < 0.001 and s["wilcoxon_p"] < 0.001


def test_reserve_of_maps_both_sets():
    assert t4b.reserve_of("job09wq") == "Jobos"
    assert t4b.reserve_of("gtmpiwq") == "Guana Tolomato Matanzas"
    assert t4b.reserve_of("marscwq") == "Mission-Aransas"


def test_tracked_preregistration_matches_code():
    if not t4b.TRACKED_PREREG.exists():
        return
    payload = json.loads(t4b.TRACKED_PREREG.read_text(encoding="utf-8"))
    assert payload["verdict_rules"] == t4b.VERDICT_RULES
    assert payload["switch_minutes"] == t4b.SWITCH_MINUTES
    assert tuple(payload["arms"]) == t4b.ARMS
