"""Freeze suitability-scoring outputs as a golden fixture (H4.2, decisions #H42).

The fixture ``tests/fixtures/suitability_golden.json`` was generated from the code *before* the
``SuitabilityScorer`` refactor; ``tests/test_suitability_golden.py`` asserts the refactored code
reproduces it bit-for-bit. Re-run only to add cases, never to "fix" a failing golden test:

    python tests/golden/make_suitability_golden.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.spatial_overlay import _legacy_hsi, _legacy_hsi_label  # noqa: E402
from experiments.spatial_applicability import cobia_hsi, hsi_label  # noqa: E402
from hap_shared.classification import _classify_by_scoring, _load_thresholds  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "suitability_golden.json"
SPECIES = ("cobia", "oyster", "sonneratia")
HSI_PARAMS = ("DO", "Temperature", "pH", "Salinity", "NH3", "TSS")
HSI_CUTS = (0.85, 0.75, 0.5)


def _f(value):
    """JSON-safe float that round-trips exactly (repr); NaN as None."""
    value = float(value)
    return None if math.isnan(value) else value


def _candidates(breakpoints, rng) -> list[float]:
    xs = sorted(float(x) for x, _ in breakpoints)
    mids = [(a + b) / 2 for a, b in zip(xs, xs[1:])]
    span = (xs[-1] - xs[0]) or 1.0
    return xs + mids + [xs[0] - 0.1 * span, xs[-1] + 0.1 * span, float("nan")] + \
        list(rng.uniform(xs[0] - 0.05 * span, xs[-1] + 0.05 * span, 6))


def rule_cases(rng) -> dict:
    cases = {}
    for species in SPECIES:
        thresholds = _load_thresholds(species)
        params = list(thresholds)
        values = {p: _candidates(thresholds[p]["breakpoints"], rng) for p in params}
        n_rows = 40
        rows = [{p: values[p][(i * (k + 3) + k) % len(values[p])] for k, p in enumerate(params)} for i in range(n_rows)]
        frame = pd.DataFrame(rows)
        subsets = {"all": params, "reversed": params[::-1], "first1": params[:1], "first3": params[:3],
                   "with_unknown": ["Unknown_param", *params[:4]], "empty": [], "only_unknown": ["Unknown_param"]}
        case = {"rows": [{k: _f(v) for k, v in r.items()} for r in rows], "subsets": {}}
        for name, subset in subsets.items():
            out = _classify_by_scoring(frame, subset, species)
            case["subsets"][name] = {"params": subset,
                                     "score": [_f(v) for v in out["suitability_score"]],
                                     "label": [int(v) for v in out["suitability_label"]],
                                     "name": list(out["suitability_name"]),
                                     "method": list(out["classification_method"])}
        cases[species] = case
    return cases


def hsi_cases(rng) -> dict:
    grid = {"DO": [0.0, 3.0, 5.99, 6.0, 9.0], "Temperature": [10.0, 24.0, 26.0, 28.0, 40.0, 60.0],
            "pH": [4.0, 8.0, 8.25, 8.5, 9.0, 17.5], "Salinity": [0.2, 27.0, 30.0, 33.0, 40.0, 70.0],
            "NH3": [0.0, 0.05, 0.1, 0.25], "TSS": [0.0, 25.0, 50.0, 120.0]}
    rows: list[dict] = []
    for i in range(48):
        row = {}
        for k, p in enumerate(HSI_PARAMS):
            pick = (i * (k + 2) + k) % (len(grid[p]) + 2)
            if pick < len(grid[p]):
                row[p] = grid[p][pick]
            elif pick == len(grid[p]):
                row[p] = None                      # NaN / missing value
            # else: column absent from this row
        rows.append(row)
    for _ in range(16):
        rows.append({p: float(v) for p, v in zip(HSI_PARAMS, rng.uniform([0, 15, 6, 10, 0, 0], [12, 35, 10, 40, 0.3, 100]))})
    rows.append({})
    rows.append({"DO": "n/a", "TSS": "12.5"})       # non-numeric / numeric strings: to_numeric(coerce)
    scores = []
    for row in rows:
        series = pd.Series(row, dtype=object)
        legacy, experiment = _legacy_hsi(series), cobia_hsi(series)
        scores.append({"legacy": _f(legacy), "experiment": _f(experiment),
                       "legacy_label": _legacy_hsi_label(legacy), "experiment_label": hsi_label(experiment)})
    probes = [0.0, 0.4999, 0.5, 0.74999, 0.75, 0.849999, 0.85, 1.0, float("nan")] + [float(v) for v in rng.uniform(0, 1, 12)]
    labels = [{"value": _f(v), "legacy": _legacy_hsi_label(v), "experiment": hsi_label(v)} for v in probes]
    return {"rows": rows, "scores": scores, "label_probes": labels}


def main() -> int:
    rng = np.random.default_rng(20261104)
    payload = {"generated_from": "pre-refactor code (hap_shared.classification._classify_by_scoring, "
                                 "core.spatial_overlay._legacy_hsi, experiments.spatial_applicability.cobia_hsi)",
               "rule": rule_cases(rng), "hsi": hsi_cases(rng)}
    FIXTURE.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE} ({FIXTURE.stat().st_size} bytes, {sum(len(c['subsets']) for c in payload['rule'].values())} rule cases, "
          f"{len(payload['hsi']['rows'])} hsi rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
