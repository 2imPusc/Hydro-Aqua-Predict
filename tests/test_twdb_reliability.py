"""Unit tests for the TWDB direction-4 reliability script (synthetic fixtures, no network)."""
import numpy as np
import pandas as pd

from experiments import twdb_reliability as tr


def test_season_and_distance_bins():
    assert tr.season_of(pd.DatetimeIndex(["2015-03-01", "2015-07-31", "2015-08-01", "2015-02-28"])).tolist() == [
        "high_flow", "high_flow", "low_flow", "low_flow"]
    assert tr.distance_bin([0.5, 2.0, 9.9, 25, 31]).tolist() == ["0-2", "2-5", "5-10", "20-30", ">30"]


def test_rain_class():
    out = tr.rain_class(pd.Series([np.nan, 0.5, 5.0, 12.0]), heavy=10.0)
    assert out.tolist() == ["na", "none", "light", "heavy"]


def _hourly_sal(station, values, start="2015-01-01"):
    idx = pd.date_range(start, periods=len(values), freq="h")
    return pd.DataFrame({"station": station, "variable": "Sal", "time_lst": idx, "value": values, "n_obs": 1})


def test_regime_uses_high_flow_median_and_threshold():
    hours = 24 * 365
    hourly = pd.concat([_hourly_sal("A", np.full(hours, 10.0)), _hourly_sal("B", np.full(hours, 11.5)),
                        _hourly_sal("C", np.full(hours, 20.0))])
    med = tr.station_salinity_medians(hourly)
    stations = pd.DataFrame({"station": ["A", "B", "C"], "system": "S", "lat": [28.0, 28.0, 28.1], "lon": [-96.0, -96.01, -96.0]})
    pairs = tr.build_pairs(stations, med).set_index(["anchor", "target"])
    assert pairs.loc[("A", "B"), "regime"] == "same" and pairs.loc[("A", "C"), "regime"] == "different"
    assert pairs.loc[("A", "C"), "dsal"] == 10.0
    assert abs(pairs.loc[("A", "C"), "km"] - 11.12) < 0.05 and pairs.loc[("A", "C"), "distance_bin"] == "10-20"


def _cells(statuses):
    return pd.DataFrame([{"dataset": "T", "var": "Temp", "regime": "all", "transfer": "raw", "distance_bin": b,
                          "gate80": st, "gate90": st, "gate95": st} for b, st in statuses.items()])


def test_radius_skips_empty_bins_and_stops_at_first_failure():
    r = tr.reliability_radius(_cells({"2-5": "pass", "10-20": "pass", "20-30": "fail", ">30": "pass"}),
                              ["dataset", "var", "regime", "transfer"])
    assert r.loc[r.gate == 80, "radius_km"].item() == 20.0
    assert r.loc[r.gate == 80, "stop"].item() == "fail@20-30"
    r = tr.reliability_radius(_cells({"5-10": "fail"}), ["dataset", "var", "regime", "transfer"])
    assert r.loc[r.gate == 80, "radius_km"].item() == 0.0
    r = tr.reliability_radius(_cells({"0-2": "insufficient", "2-5": "pass"}), ["dataset", "var", "regime", "transfer"])
    assert np.isnan(r.loc[r.gate == 80, "radius_km"].item())
    r = tr.reliability_radius(_cells({"20-30": "pass", ">30": "pass"}), ["dataset", "var", "regime", "transfer"])
    assert r.loc[r.gate == 80, "radius_km"].item() == 30.0  # capped, >30 never extends the radius


def test_summarise_pools_days_and_gates():
    days = pd.date_range("2015-01-01", periods=40, freq="D")
    agg = pd.DataFrame({"day": np.r_[days, days], "anchor": "A", "target": np.r_[["B"] * 40, ["C"] * 40],
                        "variable": "Temp", "transfer": "raw", "w": 24, "n": 24, "abs_err_sum": 2.4})
    cells = tr.summarise(agg, ["variable", "transfer"], n_boot=50)
    row = cells.iloc[0]
    assert row["share"] == 1.0 and row["n_days"] == 40 and row["n_pairs"] == 2 and row["gate95"] == "pass"
    assert abs(row["mae"] - 0.1) < 1e-9
    short = tr.summarise(agg[agg.day < days[10]], ["variable", "transfer"], n_boot=50)
    assert short.iloc[0]["gate80"] == "insufficient"


def test_regime_vs_distance_recovers_dominant_salinity_effect():
    rng = np.random.default_rng(0)
    rows = []
    names = [f"S{i}" for i in range(12)]
    for i, a in enumerate(names):
        for j, t in enumerate(names):
            if i == j:
                continue
            km = abs(i - j) * 2.0 + rng.uniform(0, 1)
            dsal = abs((i % 4) - (j % 4)) * 3.0
            share = np.clip(0.95 - 0.08 * dsal / 3 - 0.002 * km, 0.05, 0.99)
            n = 5000
            rows.append({"anchor": a, "target": t, "variable": "Sal", "transfer": "raw", "km": km, "dsal": dsal,
                         "w": int(share * n), "n": n, "n_days": 400})
    out = tr.regime_vs_distance(pd.DataFrame(rows), n_boot=50)
    row = out[(out.scope == "all_km")].iloc[0]
    assert row["logit_beta_dsal"] < 0 and abs(row["logit_beta_dsal"]) > abs(row["logit_beta_km"])
    assert row["ols_beta_dsal"] < row["ols_beta_km"]
    assert bool(row["regime_beats_distance"])


def test_effect_table_detects_rain_degradation():
    days = pd.date_range("2015-01-01", periods=60, freq="D")
    heavy = pd.DataFrame({"day": days, "rain24": "heavy", "rain72": "heavy", "w": 10, "n": 24})
    none = pd.DataFrame({"day": days, "rain24": "none", "rain72": "none", "w": 23, "n": 24})
    agg = pd.concat([heavy, none]).assign(variable="Sal", transfer="raw", regime="all", season="low_flow",
                                          daynight="day")
    eff = tr.effect_table(agg, ["variable", "transfer", "regime"], effects=tr.EFFECTS[:2], n_boot=50)
    row = eff[(eff.effect == "rain24h_ge10_vs_lt1") & (eff.scope == "all")].iloc[0]
    assert row["diff_a_minus_b"] < -0.5 and row["significant"]


def test_evaluate_end_to_end_small():
    hours = pd.date_range("2015-01-01", periods=24 * 400, freq="h")
    base = 20 + 5 * np.sin(np.arange(len(hours)) / 500)
    hourly = pd.concat([
        pd.DataFrame({"station": "A", "variable": "Temp", "time_lst": hours, "value": base, "n_obs": 1}),
        pd.DataFrame({"station": "B", "variable": "Temp", "time_lst": hours, "value": base + 0.2, "n_obs": 1}),
    ])
    pairs = pd.DataFrame({"anchor": ["A", "B"], "target": ["B", "A"], "system_target": "S"})
    strata = tr.build_strata(pd.date_range("2015-01-01", periods=24 * 401, freq="h"), None, 28.5, -96.5)
    n_days, rel, agg = tr.evaluate(hourly, pairs, {"S": strata})
    assert set(n_days["n_days"]) == {400}
    raw = rel[(rel.transfer == "raw")]
    assert (raw["share"] == 1.0).all() and len(rel) == 4
    assert set(agg["daynight"]) == {"day", "night"}
