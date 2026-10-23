from core.model_alerts import evaluate_inferred_do_alert

def _context(do): return {"status": "ready", "predictions": {"DO": {"status": "accepted", "value": do, "model_version": "v1"}}}
def test_inferred_do_warning_requires_persistence():
    first = evaluate_inferred_do_alert(_context(3.8), {"Temperature": 29, "NH3": .01})
    second = evaluate_inferred_do_alert(_context(3.8), {"Temperature": 29, "NH3": .01}, first)
    assert first["severity"] == "WATCH"
    assert second["severity"] == "WARNING"
def test_rejected_model_blocks_alert():
    assert evaluate_inferred_do_alert({"status": "disabled", "reason": "unit"}, {})["severity"] == "BLOCKED"
