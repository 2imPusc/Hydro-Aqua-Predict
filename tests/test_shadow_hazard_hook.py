from datetime import datetime, timedelta, timezone

from core import shadow_runner as sr

T0 = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def _patch_runner(monkeypatch, calls, raises=False):
    from core import hazard_runner

    def fake(now=None, *a, **k):
        calls.append(now)
        if raises:
            raise RuntimeError("boom")
        return {"n_records": 3}
    monkeypatch.setattr(hazard_runner, "run_once", fake)


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("HAZARD_RUNNER_ENABLED", raising=False)
    monkeypatch.setattr(sr, "_last_hazard_run", None)
    calls = []
    _patch_runner(monkeypatch, calls)
    assert sr.maybe_run_hazards(T0) is None and calls == []


def test_enabled_runs_and_throttles(monkeypatch):
    monkeypatch.setenv("HAZARD_RUNNER_ENABLED", "true")
    monkeypatch.delenv("HAZARD_RUNNER_INTERVAL_MINUTES", raising=False)
    monkeypatch.setattr(sr, "_last_hazard_run", None)
    calls = []
    _patch_runner(monkeypatch, calls)
    assert sr.maybe_run_hazards(T0) == {"n_records": 3}
    assert sr.maybe_run_hazards(T0 + timedelta(minutes=30)) is None
    assert sr.maybe_run_hazards(T0 + timedelta(minutes=61)) == {"n_records": 3}
    assert len(calls) == 2


def test_hazard_failure_does_not_raise(monkeypatch):
    monkeypatch.setenv("HAZARD_RUNNER_ENABLED", "1")
    monkeypatch.setattr(sr, "_last_hazard_run", None)
    _patch_runner(monkeypatch, [], raises=True)
    out = sr.maybe_run_hazards(T0)
    assert out["status"] == "error" and "RuntimeError" in out["reason"]
