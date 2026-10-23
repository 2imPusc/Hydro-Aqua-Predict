import json

import numpy as np
import pandas as pd
import pytest

from core import hazard_runner as hr
from core import paths

NOW = pd.Timestamp("2026-08-10T00:30:00Z")
CFG = json.loads(paths.ALERT_CONFIG_DEFAULT.read_text(encoding="utf-8"))
OPEN = {"id": "NB1", "lat": 20.7, "lon": 107.0, "exposure_class": None, "profile": None}


def _profile(shelter=1.0, fetch=30000.0):
    b = np.arange(0, 360, 22.5)
    return {"bearing": b, "fetch_m": np.full(16, fetch), "depth_m": np.full(16, 20.0),
            "shelter": np.full(16, shelter), "censored": np.zeros(16, dtype=bool)}


def _weather(wind_by_hour, direction=225.0, status="ready", retrieved=NOW):
    times = pd.date_range(NOW.floor("h"), periods=len(wind_by_hour), freq="h")
    return {"status": status, "timezone": "UTC", "model": "ecmwf_ifs025", "retrieved_at": retrieved.isoformat(),
            "hourly": {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in times], "wind_speed_10m": list(wind_by_hour),
                       "wind_direction_10m": [direction] * len(times)}, "hourly_units": {"wind_speed_10m": "m/s"}}


def _marine(temp_by_day, status="ready"):
    # hourly SST in UTC covering local days starting at the local day of NOW
    start = pd.Timestamp("2026-08-10", tz="Asia/Ho_Chi_Minh").tz_convert("UTC")
    times = pd.date_range(start, periods=24 * len(temp_by_day), freq="h")
    vals = np.repeat(temp_by_day, 24)
    return {"status": status, "timezone": "UTC", "retrieved_at": NOW.isoformat(),
            "hourly": {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in times], "sea_surface_temperature": list(vals)}}


def _by(records, hazard):
    return {r["lead_hours"]: r for r in records if r["hazard"] == hazard}


def test_record_contract_fields_and_flags():
    recs = hr.evaluate_station(OPEN, _weather([10.0] * 130), _marine([30.0] * 6), now=NOW, config=CFG)
    r = _by(recs, "storm_wind")[0]
    for k in ("issued_at", "station", "exposure_class", "hazard", "valid_from", "valid_to", "lead_hours", "value", "unit",
              "tier", "action_vi", "inputs", "data_status", "config_version"):
        assert k in r
    assert r["used_by_alerts"] is False and r["notification_eligible"] is False
    assert r["basis"] == "theory_only_unvalidated" and r["config_version"] == CFG["config_version"]
    assert [x["lead_hours"] for x in recs if x["hazard"] == "heat"] == [0, 24, 48, 72]
    assert json.dumps(recs)  # serialisable


def test_storm_wind_open_water_flagged_and_tiered():
    wind = [5.0] * 24 + [18.0] * 24 + [5.0] * 82  # 18 m/s = Beaufort 8 in window 24-48
    recs = hr.evaluate_station(OPEN, _weather(wind), _marine([30.0] * 6), now=NOW, config=CFG)
    w = _by(recs, "storm_wind")
    assert w[24]["value"] == 8 and w[24]["tier"] == 2 and w[0]["tier"] == 0
    assert w[24]["inputs"]["exposure_assumption"] == "open_water_no_exposure_data"
    assert w[24]["inputs"]["wind_dir_deg"] == 225.0 and w[24]["inputs"]["model"] == "ecmwf_ifs025"
    assert w[24]["action_vi"]
    assert _by(recs, "wave_height")[24]["skip_reason"] == "no_exposure_profile"
    assert _by(recs, "wave_height")[24]["tier"] is None


def test_shelter_lowers_site_beaufort_and_wave_height_uses_fetch():
    st = {**OPEN, "exposure_class": "exposed", "profile": _profile(shelter=0.6, fetch=40000.0)}
    wind = [20.0] * 130
    recs = hr.evaluate_station(st, _weather(wind), _marine([30.0] * 6), now=NOW, config=CFG)
    assert _by(recs, "storm_wind")[0]["value"] == sa_beaufort(12.0)  # 20 * 0.6 = 12 m/s
    wave = _by(recs, "wave_height")[0]
    assert wave["value"] > 1.0 and wave["tier"] >= 2 and wave["inputs"]["fetch_m"] == 40000


def sa_beaufort(ms):
    from core.storm_advisory import beaufort
    return beaufort(ms)


def test_stale_and_unavailable_inputs_skip_with_status():
    stale = hr.evaluate_station(OPEN, _weather([20.0] * 130, status="stale"), _marine([30.0] * 6, status="stale"),
                                now=NOW, config=CFG)
    assert all(r["tier"] is None and r["skip_reason"] and r["data_status"] == "stale" for r in stale)
    old = hr.evaluate_station(OPEN, _weather([20.0] * 130, retrieved=NOW - pd.Timedelta(hours=30)), None,
                              now=NOW, config=CFG)
    sw = _by(old, "storm_wind")[0]
    assert sw["data_status"] == "stale" and sw["tier"] is None
    heat = _by(old, "heat")[0]
    assert heat["data_status"] == "unavailable" and heat["skip_reason"]


def test_window_without_forecast_hours_is_skipped_not_zero():
    recs = hr.evaluate_station(OPEN, _weather([10.0] * 60), _marine([30.0] * 6), now=NOW, config=CFG)
    w = _by(recs, "storm_wind")
    assert w[0]["tier"] == 0 and w[72]["skip_reason"] == "no_forecast_hours" and w[72]["value"] is None


def test_heat_requires_persistence_for_tier_two_and_cold_never_with_short_forecast():
    marine = _marine([33.5, 33.5, 31.5, 31.5, 31.5, 31.5])
    h = _by(hr.evaluate_station(OPEN, _weather([5.0] * 130), marine, now=NOW, config=CFG), "heat")
    assert h[0]["tier"] == 1 and h[0]["inputs"]["correction"] == "none"  # 1 day >=33 is not 3 in a row
    assert h[0]["inputs"]["persistence_basis"] == "forecast_days_only"
    run = _marine([33.5, 33.5, 33.5, 33.5, 33.5, 33.5])
    h2 = _by(hr.evaluate_station(OPEN, _weather([5.0] * 130), run, now=NOW, config=CFG), "heat")
    assert h2[0]["tier"] == 1 and h2[48]["tier"] == 2 and h2[48]["value"] == 33.5
    cold = _by(hr.evaluate_station(OPEN, _weather([5.0] * 130), _marine([16.0] * 6), now=NOW, config=CFG), "cold")
    # default cold tier 2 (<= 18 °C) needs 3 consecutive days: day 1 tier 1, day 3 onwards tier 2
    assert cold[0]["tier"] == 1 and cold[48]["tier"] == 2 and cold[72]["tier"] == 2


def test_disease_env_index_tiered():
    d = _by(hr.evaluate_station(OPEN, _weather([5.0] * 130), _marine([28.0] * 6), now=NOW, config=CFG), "disease_env")
    assert 0 <= d[0]["value"] <= 1 and d[0]["tier"] in (0, 1, 2) and d[0]["inputs"]["rain"] == "not_used"


def test_hook_records_are_appended():
    hr.register_hazard("t", lambda st, ctx: [hr.make_record(issued_at=ctx["issued_at"], station=st, hazard="storm_watch",
                                                            window=ctx["windows"][0], config=ctx["config"], value=0.5, tier=1)])
    try:
        recs = hr.evaluate_station(OPEN, None, None, now=NOW, config=CFG)
    finally:
        hr.HAZARD_HOOKS.pop("t")
    assert any(r["hazard"] == "storm_watch" and r["tier"] == 1 for r in recs)


def test_run_once_appends_never_rewrites(tmp_path):
    st = [{**OPEN, "exposure_class": "exposed", "profile": _profile()}]
    args = dict(stations=st, fetch_weather=lambda s: _weather([10.0] * 130), fetch_marine_fn=lambda s: _marine([30.0] * 6),
                config_loader=lambda sid, cls: CFG)
    a = hr.run_once(NOW, tmp_path, **args)
    path = tmp_path / "hazard_20260810.jsonl"
    first = path.read_bytes()
    b = hr.run_once(NOW, tmp_path, **args)
    assert path.read_bytes().startswith(first) and len(path.read_bytes()) == 2 * len(first)
    assert a["n_records"] == b["n_records"] == len(first.splitlines()) and a["n_skipped"] >= 0
    assert [json.loads(l)["station"] for l in first.splitlines()][0] == "NB1"


def test_fetch_failure_does_not_raise(tmp_path):
    st = [{**OPEN}]
    out = hr.run_once(NOW, tmp_path, stations=st, fetch_weather=lambda s: {"status": "unavailable", "reason": "provider_request_failed"},
                      fetch_marine_fn=lambda s: {"status": "disabled", "reason": "marine_disabled"}, config_loader=lambda a, b: CFG)
    assert out["n_skipped"] == out["n_records"] > 0


def test_load_exposure_absent_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(paths, "EXPERIMENT_OUTPUT_DIR", tmp_path / "experiments")
    assert hr.load_exposure() == {}


def test_load_exposure_reads_latest_run(tmp_path, monkeypatch):
    run = tmp_path / "experiments" / "site-exposure-20261023"
    run.mkdir(parents=True)
    pd.DataFrame({"site_id": ["S"], "exposure_class": ["hở (exposed)"]}).to_csv(run / "stations.csv", index=False)
    rows = [{"site_id": "S", "bearing": b, "fetch_straight_m": 1000.0, "depth_mean_m": np.nan, "shelter_factor": 0.9,
             "fetch_censored": False} for b in range(0, 360, 90)]
    pd.DataFrame(rows).to_csv(run / "per_direction.csv", index=False)
    monkeypatch.setattr(paths, "EXPERIMENT_OUTPUT_DIR", tmp_path / "experiments")
    ex = hr.load_exposure()
    assert ex["S"]["exposure_class"] == "exposed" and ex["S"]["profile"]["depth_m"].min() >= 1.0


# --------------------------------------------------------------------------- wave 2 integration
@pytest.fixture(autouse=True)
def _no_real_sensor(monkeypatch):
    monkeypatch.setattr(hr, "default_observed", lambda station, now: None)


def _obs(values, end="2026-08-09", source="cage_sensor"):
    idx = pd.date_range(end=end, periods=len(values), freq="D")
    return {"source": source, "series": pd.Series(values, index=idx)}


def test_observed_seed_makes_heat_tier_two_reachable_on_day_zero():
    marine = _marine([33.5] * 6)  # forecast days all >= 33
    plain = _by(hr.evaluate_station(OPEN, _weather([5.0] * 130), marine, now=NOW, config=CFG), "heat")
    assert plain[0]["tier"] == 1 and plain[0]["inputs"]["persistence_basis"] == "forecast_days_only"
    seeded = _by(hr.evaluate_station(OPEN, _weather([5.0] * 130), marine, now=NOW, config=CFG,
                                     observed=_obs([33.4, 33.6, 33.2])), "heat")
    assert seeded[0]["tier"] == 2 and seeded[0]["inputs"]["persistence_basis"] == "observed+forecast"
    seeds = seeded[0]["inputs"]["persistence_seed"]
    assert [s["date"] for s in seeds] == ["2026-08-07", "2026-08-08", "2026-08-09"]
    assert {s["source"] for s in seeds} == {"cage_sensor"}


def test_observed_gap_breaks_the_run_and_cold_is_seeded_too():
    marine = _marine([33.5] * 6)
    two_days = _obs([33.4, 33.6], end="2026-08-09")
    h = _by(hr.evaluate_station(OPEN, _weather([5.0] * 130), marine, now=NOW, config=CFG, observed=two_days), "heat")
    assert h[0]["tier"] == 2  # 2 observed + first forecast day = 3 consecutive
    gapped = {"source": "cage_sensor", "series": pd.Series([33.4, 33.6], index=pd.to_datetime(["2026-08-05", "2026-08-06"]))}
    h2 = _by(hr.evaluate_station(OPEN, _weather([5.0] * 130), marine, now=NOW, config=CFG, observed=gapped), "heat")
    assert h2[0]["tier"] == 1
    c = _by(hr.evaluate_station(OPEN, _weather([5.0] * 130), _marine([17.0] * 6), now=NOW, config=CFG,
                                observed=_obs([17.0, 17.5])), "cold")
    assert c[0]["tier"] == 2


def test_marine_past_days_seed_when_no_sensor_and_are_labelled():
    start = pd.Timestamp("2026-08-07", tz="Asia/Ho_Chi_Minh").tz_convert("UTC")  # 3 past local days
    times = pd.date_range(start, periods=24 * 9, freq="h")
    marine = {"status": "ready", "timezone": "UTC", "retrieved_at": NOW.isoformat(), "model": "openmeteo_marine_best_match",
              "hourly": {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in times],
                         "sea_surface_temperature": [33.5] * len(times)}}
    h = _by(hr.evaluate_station(OPEN, _weather([5.0] * 130), marine, now=NOW, config=CFG), "heat")
    assert h[0]["tier"] == 2 and h[0]["inputs"]["persistence_basis"] == "observed+forecast"
    assert {s["source"] for s in h[0]["inputs"]["persistence_seed"]} == {"openmeteo_marine_past_days"}
    assert h[0]["inputs"]["model"] == "openmeteo_marine_best_match"


def _history(days, per_day=1300, temp=30.0, start="2026-08-01"):
    rows = []
    for i in range(days):
        day = pd.Timestamp(start, tz="Asia/Ho_Chi_Minh") + pd.Timedelta(days=i)
        t = pd.date_range(day, periods=per_day, freq="min").tz_convert("UTC")
        rows.append(pd.DataFrame({"fetchedAt": t, "Temperature": temp + i * 0.1}))
    return pd.concat(rows, ignore_index=True)


def test_sensor_daily_temperature_requires_rows_range_and_freshness():
    h = _history(9)  # 08-01..08-09 local
    got = hr.sensor_daily_temperature("S", NOW, history=h)
    assert got["source"] == "cage_sensor" and len(got["series"]) == 7
    assert got["series"].index.max() == pd.Timestamp("2026-08-09")
    assert hr.sensor_daily_temperature("S", NOW, history=_history(9, per_day=1000)) is None  # < 1296 rows/day
    assert hr.sensor_daily_temperature("S", NOW, history=_history(9, temp=45.0)) is None  # out of 10-40 degC
    assert hr.sensor_daily_temperature("S", NOW, history=_history(3)) is None  # stale (last 08-03)
    assert hr.sensor_daily_temperature("S", NOW, history=h.iloc[0:0]) is None


def test_default_observed_only_for_cage_station(monkeypatch):
    monkeypatch.undo()
    seen = []
    monkeypatch.setattr(hr, "sensor_daily_temperature", lambda serial, now: seen.append(serial) or {"series": None})
    assert hr.default_observed({"id": "NB1"}, NOW) == {"series": None} and seen == ["06M26042804"]
    assert hr.default_observed({"id": "QN7"}, NOW) is None


def test_run_once_uses_scoped_config_per_station_and_records_version(tmp_path):
    seen = []
    scoped = json.loads(json.dumps(CFG))
    scoped["config_version"] = "v0001-test"
    scoped["hazards"]["storm_wind"]["thresholds"]["1"] = 3

    def loader(sid, cls):
        seen.append((sid, cls))
        return scoped if sid == "A" else CFG
    sts = [{**OPEN, "id": "A", "exposure_class": "exposed"}, {**OPEN, "id": "B", "exposure_class": "sheltered"}]
    out = hr.run_once(NOW, tmp_path, stations=sts, fetch_weather=lambda s: _weather([5.0] * 130),
                      fetch_marine_fn=lambda s: _marine([30.0] * 6), config_loader=loader)
    assert seen == [("A", "exposed"), ("B", "sheltered")]
    recs = [json.loads(x) for x in (tmp_path / "hazard_20260810.jsonl").read_text("utf-8").splitlines()]
    sw = {r["station"]: r for r in recs if r["hazard"] == "storm_wind" and r["lead_hours"] == 0}
    assert sw["A"]["config_version"] == "v0001-test" and sw["A"]["tier"] == 1  # Beaufort 3 >= scoped threshold 3
    assert sw["B"]["config_version"] == CFG["config_version"] and sw["B"]["tier"] == 0
    assert out["config_versions"] == sorted(["v0001-test", CFG["config_version"]])


def test_tier_none_becomes_skip_not_a_value():
    rec = hr.make_record(issued_at=NOW, station=OPEN, hazard="heat", window=(NOW, NOW, 0), config=CFG, value=33.0, tier=None)
    assert rec["tier"] is None and rec["value"] is None and rec["skip_reason"] == "tier_unavailable"


def _write_storms(dirpath, run_time):
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / f"storms_active_{run_time:%Y%m%d%H}.json").write_text(
        json.dumps({"status": "ready", "run_time": run_time.strftime("%Y-%m-%dT%H:%M:%SZ")}), encoding="utf-8")


def test_storm_watch_fresh_file_adds_no_duplicate_record(tmp_path):
    _write_storms(tmp_path, NOW - pd.Timedelta(hours=10))
    assert hr.storm_watch_records(OPEN, CFG, NOW, tmp_path) == []


def test_storm_watch_missing_or_stale_adds_skip_record(tmp_path):
    r = hr.storm_watch_records(OPEN, CFG, NOW, tmp_path)[0]
    assert r["hazard"] == "storm_watch" and r["tier"] is None and r["skip_reason"] == "no_storm_data"
    assert r["used_by_alerts"] is False and r["config_version"] == CFG["config_version"]
    _write_storms(tmp_path, NOW - pd.Timedelta(hours=40))
    r2 = hr.storm_watch_records(OPEN, CFG, NOW, tmp_path)[0]
    assert r2["skip_reason"] == "stale_storm_data" and r2["inputs"]["run_age_hours"] > 36
    (tmp_path / "storms_active_2026081012.json").write_text("{bad", encoding="utf-8")
    assert hr.storm_watch_records(OPEN, CFG, NOW, tmp_path)[0]["skip_reason"] == "storm_file_unreadable"


def test_run_once_includes_storm_watch_status_per_station(tmp_path):
    hr.run_once(NOW, tmp_path, stations=[OPEN], fetch_weather=lambda s: _weather([5.0] * 130),
                fetch_marine_fn=lambda s: _marine([30.0] * 6), config_loader=lambda a, b: CFG)
    recs = [json.loads(x) for x in (tmp_path / "hazard_20260810.jsonl").read_text("utf-8").splitlines()]
    assert {r["hazard"] for r in recs} >= {"storm_wind", "heat", "storm_watch"}


def test_fetch_functions_name_models_and_reject_unknown_keys(monkeypatch):
    import core.config as cfgmod
    calls = []
    monkeypatch.setattr(cfgmod, "MARINE_ENABLED", True)

    def fake(url, params, timeout=15):
        calls.append((url, params))
        if "marine" in url:
            return {"hourly": {"time": ["2026-08-10T00:00"], "sea_surface_temperature": [29.0]}, "hourly_units": {}}
        return {"hourly": {"time": ["2026-08-10T00:00"], "wind_speed_10m": [3.0], "wind_direction_10m": [90]}}
    monkeypatch.setattr(hr, "_get_json", fake)
    w, m = hr.fetch_forecast(OPEN), hr.fetch_marine(OPEN)
    assert w["status"] == "ready" and calls[0][1]["models"] == "ecmwf_ifs025"
    assert m["status"] == "ready" and calls[1][1]["models"] == "best_match" and calls[1][1]["past_days"] == hr.MARINE_PAST_DAYS
    assert m["model"] == "openmeteo_marine_best_match"
    monkeypatch.setattr(hr, "_get_json", lambda *a, **k: {"hourly": {"time": [], "wind_speed_10m_ecmwf_ifs025": []}})
    assert hr.fetch_forecast(OPEN)["reason"] == "unexpected_response_keys"
    assert hr.fetch_marine(OPEN)["reason"] == "unexpected_response_keys"
