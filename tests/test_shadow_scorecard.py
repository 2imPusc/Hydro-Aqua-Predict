"""H1.5 shadow scorecard: read-only scoring of the long-horizon ledger."""
import json

import numpy as np
import pandas as pd
import pytest

from core import forecast_evaluation as fe
from experiments import shadow_scorecard as sc

STATION = "06M26042804"
START = pd.Timestamp("2026-10-01T00:00:00Z")


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    shadow = tmp_path / "forecast-shadow"
    shadow.mkdir()
    monkeypatch.setattr(fe, "LONG_FORECAST_LOG", shadow / "long_forecasts.jsonl")
    monkeypatch.setattr(fe, "LONG_OUTCOME_LOG", shadow / "long_outcomes.jsonl")
    monkeypatch.setattr(fe, "LONG_SKIP_LOG", shadow / "long_skips.jsonl")
    fe._reset_long_cache()
    yield shadow
    fe._reset_long_cache()


def _truth(times: pd.DatetimeIndex) -> np.ndarray:
    hours = (times - START).total_seconds() / 3600
    return 29.0 + np.sin(2 * np.pi * hours / 24)


def _history(end: pd.Timestamp) -> pd.DataFrame:
    times = pd.date_range(START, end, freq="1min")
    return pd.DataFrame({"fetchedAt": times, "Temperature": _truth(times), "pH": 7.9, "NH4": 50.0, "TSS": 5.0})


def _issue(days: int = 8, every: str = "30min", horizon: int = 180) -> pd.DatetimeIndex:
    issues = pd.date_range(START + pd.Timedelta(hours=1), START + pd.Timedelta(days=days), freq=every, inclusive="left")
    rng = np.random.default_rng(0)
    actual = _truth(issues + pd.Timedelta(minutes=horizon))
    current = _truth(issues)
    records = []
    for feature_set, noise in (("B4_quality", 0.10), ("B4_quality_nopH", 0.20)):
        errors = rng.normal(0.0, noise, len(issues))
        for issued, truth, now_value, err in zip(issues, actual, current, errors):
            value = float(truth + err)
            records.append({
                "station_serial": STATION, "issued_at": issued.isoformat(), "valid_at": (issued + pd.Timedelta(minutes=horizon)).isoformat(),
                "horizon_minutes": horizon, "target": "Temperature", "feature_set": feature_set,
                "model_version": f"temp_{feature_set}_{horizon}", "model_variant": "nopH" if feature_set.endswith("_nopH") else "with_pH",
                "forecast": value, "current": float(now_value), "sensor_status": "ok", "ph_input_status": "ok",
                "pi": {"method": "aci_scaled", "night": 0, "pi80": {"q": 0.15, "lower": value - 0.15, "upper": value + 0.15},
                       "pi90": {"q": 0.25, "lower": value - 0.25, "upper": value + 0.25}},
            })
    # bulk write in the ledger's own format (one append_long_forecast per record is slow on Windows)
    lines = [json.dumps({"record_id": fe.long_record_id(r), "schema_version": fe.LONG_SCHEMA, **r, "mode": "shadow",
                         "used_by_alerts": False}) + "\n" for r in records]
    with fe.LONG_FORECAST_LOG.open("a", encoding="utf-8") as handle:
        handle.write("".join(lines))
    return issues


def _resolve_in_ledger(history: pd.DataFrame) -> int:
    """What the runner's resolve_long_outcomes appends (same long_outcome rule), bulk-written."""
    frame = fe.prepare_long_raw(history)
    series = fe._valid_series(frame, "Temperature")
    rows = []
    for forecast in sc.iter_jsonl(fe.LONG_FORECAST_LOG):
        outcome = fe.long_outcome(forecast, series, frame["fetchedAt"].min(), frame["fetchedAt"].max())
        if outcome is not None:
            rows.append(json.dumps({"record_id": forecast["record_id"] + "|actual", **outcome}) + "\n")
    with fe.LONG_OUTCOME_LOG.open("a", encoding="utf-8") as handle:
        handle.write("".join(rows))
    return len(rows)


def _snapshot(directory):
    return {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in directory.iterdir()}


def test_empty_ledger_is_insufficient_and_writes_report(tmp_path):
    card = sc.compute_scorecard(tmp_path / "missing", STATION, now=pd.Timestamp("2026-10-24T00:00:00Z"))
    assert card["status"] == "insufficient_evidence"
    assert card["ledger"]["n_forecasts"] == 0 and card["groups"] == [] and card["paired"] == []
    assert card["gate"] == card["gate"] | {"status": "collecting", "progress": 0.0, "days_required": 28}
    run_dir = sc.write_scorecard(card, tmp_path / "out")
    assert run_dir.name == "shadow-scorecard-20261024"
    assert json.loads((run_dir / "scorecard.json").read_text(encoding="utf-8"))["schema_version"] == sc.SCHEMA
    assert "insufficient_evidence" in (run_dir / "scorecard.md").read_text(encoding="utf-8")


def test_scores_ledger_and_on_the_fly_outcomes_without_writing(ledger):
    issues = _issue()
    end = issues[-1] + pd.Timedelta(minutes=200)
    history = _history(end)
    # runner resolved the first half; the rest is resolved on the fly by the scorecard
    assert _resolve_in_ledger(history[history["fetchedAt"] < START + pd.Timedelta(days=4)]) > 0
    before = _snapshot(ledger)
    card = sc.compute_scorecard(ledger, STATION, now=end, history_loader=lambda: history, history_label="test")
    assert _snapshot(ledger) == before  # read-only

    ledger_info = card["ledger"]
    assert ledger_info["n_forecasts"] == 2 * len(issues)
    assert ledger_info["n_scored"] == 2 * len(issues) and ledger_info["n_pending"] == 0
    assert 0 < ledger_info["n_on_the_fly"] < ledger_info["n_scored"]
    assert card["status"] == "sufficient"

    groups = {g["variant"]: g for g in card["groups"]}
    with_ph, no_ph = groups["with_pH"], groups["nopH"]
    assert with_ph["evidence"] == "sufficient" and with_ph["days_scored"] >= 7
    assert with_ph["mae"] == pytest.approx(0.08, abs=0.02)  # E|N(0, 0.1)|
    assert with_ph["persistence_mae"] > 0.3 and with_ph["skill"] > 0.7
    assert with_ph["coverage_pi80"] == pytest.approx(0.87, abs=0.06)  # P(|N(0,0.1)| <= 0.15)
    assert with_ph["mean_width_pi80"] == pytest.approx(0.30) and with_ph["mean_width_pi90"] == pytest.approx(0.50)
    assert with_ph["dm_vs_persistence"]["model_better"] is True
    assert no_ph["mae"] > with_ph["mae"]

    pair = card["paired"][0]
    assert pair["n_pairs"] == len(issues) and pair["evidence"] == "sufficient"
    assert pair["mean_diff"] < 0 and pair["share_with_pH_better"] > 0.5
    assert pair["dm"]["better"] == "with_pH"
    assert {w["iso_week"] for w in card["weekly"]} == {"2026-W40", "2026-W41"}


def test_ledger_outcome_matches_on_the_fly_resolution(ledger):
    _issue(days=1, every="2h")
    history = _history(START + pd.Timedelta(days=2))
    fe.resolve_long_outcomes(history)
    from_ledger = sc.compute_scorecard(ledger, STATION, now=START + pd.Timedelta(days=2))
    forecasts = sc.load_forecasts(ledger / "long_forecasts.jsonl", STATION)
    fly = sc.resolve_on_the_fly(forecasts, set(), history, START + pd.Timedelta(days=2))
    ledger_outcomes = sc.load_outcomes(ledger / "long_outcomes.jsonl", STATION)
    assert set(fly) == set(ledger_outcomes)
    for key, outcome in fly.items():
        assert outcome["actual"] == ledger_outcomes[key]["actual"] and outcome["covered"] == ledger_outcomes[key]["covered"]
    assert from_ledger["ledger"]["n_on_the_fly"] == 0


def test_small_ledger_is_insufficient_and_skips_dm(ledger):
    _issue(days=2, every="10min")
    end = START + pd.Timedelta(days=3)
    card = sc.compute_scorecard(ledger, STATION, now=end, history_loader=lambda: _history(end))
    assert card["status"] == "insufficient_evidence"
    for group in card["groups"]:
        assert group["n_scored"] >= 200 and group["evidence"] == "insufficient_evidence"
        assert group["evidence_reasons"] == ["days<7"]
        assert group["dm_vs_persistence"] is None and group["pi80_in_target"] is None
        assert group["mae"] is not None
    assert card["paired"][0]["dm"] is None


def test_not_due_forecasts_stay_pending_and_partial_line_is_ignored(ledger):
    _issue(days=1, every="6h")
    with (ledger / "long_forecasts.jsonl").open("ab") as handle:
        handle.write(b'{"record_id": "partial", "station_serial": "06M')  # runner mid-append
    card = sc.compute_scorecard(ledger, STATION, now=START + pd.Timedelta(hours=2), history_loader=lambda: pytest.fail("not due"))
    assert card["ledger"]["n_pending"] == card["ledger"]["n_forecasts"] == 8


def test_run_dir_is_never_reused(tmp_path):
    now = pd.Timestamp("2026-10-24T05:00:00Z")
    first = sc.new_run_dir(tmp_path, now)
    second = sc.new_run_dir(tmp_path, now)
    assert first.name == "shadow-scorecard-20261024" and second.name == "shadow-scorecard-20261024-1200"
    assert first != second
