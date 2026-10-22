"""Theory-based stocking (tha giong) calendar for cobia cages at NB1 / Cat Ba.

Expected hazard exposure of a stocking week = mean over past years of heat, cold and storm
events inside the grow-out window. NOT validated against ground truth (none exists).

    python experiments/stocking_calendar.py --stamp 20261023
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import paths  # noqa: E402
import heat_hindcast as hh  # noqa: E402

GROWOUT_WEEKS = (26, 39)
EARLY_WEEKS = 8
YEARS_ALL = (1991, 2025)
YEARS_LAST10 = (2016, 2025)
OFFSET_BASE = 0.30  # sensor - OISST median (heat-hindcast-20261022/bias.json), single season
HEAT = (31.0, 33.0)  # watch / stress, C (Sun & Chen 2014; doc 27)
COLD = (20.0, 18.0)  # cobia_thresholds.json: 18 C -> score 0.5; 20 C = assumed growth-slowing level
SUIT = (25.0, 30.0)  # cobia_thresholds.json: score 1.0 band
WEIGHTS = {"heat": 0.20, "cold": 0.20, "storm": 0.25, "early": 0.20, "growth": 0.15}
STORM_BEAU = (8, 6)
STORM_SOFT = 0.25  # weight of a cap-6/7 passage relative to a cap>=8 one
HEAT2_W, COLD2_W = 2.0, 2.0  # a stress (>=33) / very cold (<18) day counts double a watch day
WEIGHT_SETS = {
    "base": WEIGHTS,
    "equal": dict.fromkeys(WEIGHTS, 0.2),
    "storm_heavy": {"heat": 0.1, "cold": 0.15, "storm": 0.45, "early": 0.2, "growth": 0.1},
    "cold_heavy": {"heat": 0.1, "cold": 0.45, "storm": 0.15, "early": 0.2, "growth": 0.1},
    "heat_heavy": {"heat": 0.45, "cold": 0.1, "storm": 0.15, "early": 0.2, "growth": 0.1},
    "growth_heavy": {"heat": 0.1, "cold": 0.1, "storm": 0.15, "early": 0.2, "growth": 0.45},
    "no_early": {"heat": 0.25, "cold": 0.25, "storm": 0.3, "early": 0.0, "growth": 0.2},
}
N_DIRICHLET, SEED = 1000, 20261023
ROBUST_SHARE = 0.8  # robust window: in top-5 for >= 80 % of weightings


# ---- pure helpers -------------------------------------------------------------
def iso_week_start(year: int, week: int) -> pd.Timestamp:
    return pd.Timestamp(date.fromisocalendar(year, week, 1))


def window_sst_counts(sst: pd.Series, start: pd.Timestamp, n_days: int, heat, cold, suit) -> dict | None:
    """Day counts in [start, start+n_days). None unless every day has a valid SST value."""
    w = sst.reindex(pd.date_range(start, periods=n_days, freq="D"))
    if w.isna().any():
        return None
    return {"heat_ge1": int((w >= heat[0]).sum()), "heat_ge2": int((w >= heat[1]).sum()),
            "cold_ge1": int((w < cold[0]).sum()), "cold_ge2": int((w < cold[1]).sum()),
            "suitable": int(((w >= suit[0]) & (w <= suit[1])).sum())}


def window_storm_counts(dates: pd.DatetimeIndex, beaufort: np.ndarray, start: pd.Timestamp, n_days: int, min_beau: int) -> int:
    end = start + pd.Timedelta(days=n_days)
    return int(((dates >= start) & (dates < end) & (beaufort >= min_beau)).sum())


def minmax(s: pd.Series) -> pd.Series:
    rng = s.max() - s.min()
    return s * 0.0 if rng == 0 else (s - s.min()) / rng


def composite_score(risks: pd.DataFrame, weights: dict) -> pd.Series:
    """1 - weighted mean of 0..1 risks (higher = better stocking week)."""
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise ValueError("weights must sum to 1")
    return 1.0 - sum(weights[k] * risks[k] for k in weights)


def top_k(score: pd.Series, k: int) -> list:
    return [int(x) for x in score.sort_values(ascending=False, kind="stable").index[:k]]


def top_share(scores: list[pd.Series], k: int) -> pd.Series:
    hits = pd.Series(0.0, index=scores[0].index)
    for s in scores:
        hits[top_k(s, k)] += 1
    return hits / len(scores)


def month_of_week(week: int) -> int:
    return date.fromisocalendar(2023, week, 4).month  # Thursday rule


# ---- computation --------------------------------------------------------------
def week_table(sst: pd.Series, storm_dates, storm_beau, years, n_weeks: int, thr: dict) -> pd.DataFrame:
    """Expected per-week metrics (mean over complete years) for the whole grow-out and its first 8 weeks."""
    rows = []
    for wk in range(1, 53):
        acc = []
        for y in range(years[0], years[1] + 1):
            start = iso_week_start(y, wk)
            full = window_sst_counts(sst, start, 7 * n_weeks, thr["heat"], thr["cold"], thr["suit"])
            early = window_sst_counts(sst, start, 7 * EARLY_WEEKS, thr["heat"], thr["cold"], thr["suit"])
            if full is None or early is None:
                continue
            rec = dict(full)
            for tag, n in (("", 7 * n_weeks), ("early_", 7 * EARLY_WEEKS)):
                for b in STORM_BEAU:
                    rec[f"{tag}storm_ge{b}"] = window_storm_counts(storm_dates, storm_beau, start, n, b)
            rec.update({f"early_{k}": v for k, v in early.items()})
            acc.append(rec)
        if not acc:
            continue
        m = pd.DataFrame(acc).mean()
        m["n_years"] = len(acc)
        m.name = wk
        rows.append(m)
    return pd.DataFrame(rows).rename_axis("iso_week")


def risks_from(t: pd.DataFrame) -> pd.DataFrame:
    def storm(prefix):
        return t[f"{prefix}storm_ge8"] + STORM_SOFT * (t[f"{prefix}storm_ge6"] - t[f"{prefix}storm_ge8"])

    r = pd.DataFrame(index=t.index)
    r["heat"] = minmax(t["heat_ge1"] + (HEAT2_W - 1) * t["heat_ge2"])
    r["cold"] = minmax(t["cold_ge1"] + (COLD2_W - 1) * t["cold_ge2"])
    r["storm"] = minmax(storm(""))
    r["early"] = (minmax(t["early_heat_ge1"] + (HEAT2_W - 1) * t["early_heat_ge2"])
                  + minmax(t["early_cold_ge1"] + (COLD2_W - 1) * t["early_cold_ge2"]) + minmax(storm("early_"))) / 3
    r["growth"] = 1.0 - minmax(t["suitable"])
    return r


def classify_months(score_by_len: dict[int, pd.Series]) -> pd.DataFrame:
    """Per month: mean score over its ISO weeks, per grow-out length; rank class (4 good / 4 caution / 4 avoid), worse of the lengths."""
    cols = {}
    for n, s in score_by_len.items():
        m = s.groupby([month_of_week(w) for w in s.index]).mean()
        rk = m.rank(ascending=False, method="first")
        cols[f"score_{n}w"] = m
        cols[f"class_{n}w"] = rk.map(lambda r: "good" if r <= 4 else ("caution" if r <= 8 else "avoid"))
    out = pd.DataFrame(cols).rename_axis("month")
    order = ["good", "caution", "avoid"]
    out["class"] = [order[max(order.index(out.loc[i, f"class_{n}w"]) for n in score_by_len)] for i in out.index]
    return out


def load_inputs(oisst_path: Path, passages_path: Path):
    o = pd.read_csv(oisst_path, parse_dates=["time"]).set_index("time")["sst"]
    o.index = o.index.tz_convert("UTC").normalize().tz_localize(None)
    p = pd.read_csv(passages_path)
    pt = pd.to_datetime(p["peak_time"], utc=True).dt.normalize().dt.tz_localize(None)
    return o.sort_index(), pd.DatetimeIndex(pt), {"site_beaufort": p["site_beaufort"].fillna(0).to_numpy(),
                                                    "site_beaufort_088": p["site_beaufort_088"].fillna(0).to_numpy()}


def _shift(t: dict, d: float) -> dict:
    return {k: tuple(x + d for x in v) for k, v in t.items()}


def sensitivity_cases() -> dict:
    base = {"heat": HEAT, "cold": COLD, "suit": SUIT}
    mk = lambda **kw: {"offset": OFFSET_BASE, "years": YEARS_ALL, "thr": base, "beau": "site_beaufort", **kw}  # noqa: E731
    return {"base": mk(), "offset_0": mk(offset=0.0), "offset_1.18": mk(offset=1.18),
            "thr_-0.5": mk(thr=_shift(base, -0.5)), "thr_+0.5": mk(thr=_shift(base, +0.5)),
            "last10y": mk(years=YEARS_LAST10), "storm_wind_0.88": mk(beau="site_beaufort_088")}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _json(o):
    return o.item() if hasattr(o, "item") else str(o)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", required=True)
    ap.add_argument("--oisst", type=Path, default=None)
    ap.add_argument("--passages", type=Path, default=paths.EXPERIMENT_OUTPUT_DIR / "storm-hindcast-20261022d" / "passages.csv")
    args = ap.parse_args(argv)
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / f"stocking-calendar-{args.stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    oisst_file = args.oisst or hh._longest_oisst()
    sst, sdates, beaus = load_inputs(oisst_file, args.passages)

    cases = sensitivity_cases()
    tables, scores, sens_rows = {}, {}, []
    for name, c in cases.items():
        for n in GROWOUT_WEEKS:
            t = week_table(sst + c["offset"], sdates, beaus[c["beau"]], c["years"], n, c["thr"])
            tables[(name, n)] = t
            scores[(name, n)] = composite_score(risks_from(t), WEIGHTS)
            sens_rows.append({"case": name, "growout_weeks": n, "top3": top_k(scores[(name, n)], 3),
                              "top5": top_k(scores[(name, n)], 5)})
    pd.DataFrame(sens_rows).to_csv(run_dir / "sensitivity_top3.csv", index=False)

    rng = np.random.default_rng(SEED)
    rank_out = {}
    for n in GROWOUT_WEEKS:
        t = tables[("base", n)]
        r = risks_from(t)
        s0 = scores[("base", n)]
        allw = [composite_score(r, w) for w in WEIGHT_SETS.values()]
        allw += [composite_score(r, dict(zip(WEIGHTS, w))) for w in rng.dirichlet(np.ones(len(WEIGHTS)), N_DIRICHLET)]
        rk = t.join(r.add_prefix("risk_")).assign(score=s0, rank=s0.rank(ascending=False, method="first").astype(int))
        rk["share_top3"], rk["share_top5"] = top_share(allw, 3), top_share(allw, 5)
        rk["robust_top5"] = rk["share_top5"] >= ROBUST_SHARE
        l10 = tables[("last10y", n)].drop(columns="n_years").add_prefix("last10_")
        rk = rk.join(l10)
        rk.sort_values("rank").to_csv(run_dir / f"ranking_{n}w.csv", index_label="iso_week")
        rank_out[n] = rk
    months = classify_months({n: scores[("base", n)] for n in GROWOUT_WEEKS})
    months.to_csv(run_dir / "month_classes.csv")

    stab = {}
    for n in GROWOUT_WEEKS:
        base3 = top_k(scores[("base", n)], 3)
        rows = []
        for name in cases:
            s = scores[(name, n)]
            t3, t5 = top_k(s, 3), top_k(s, 5)
            rows.append({"case": name, "top3": t3, "overlap_with_base_top3": len(set(t3) & set(base3)),
                         "base_top3_within_top5": sum(w in t5 for w in base3),
                         "base_top3_within_2wk_of_top3": sum(any(abs(w - x) <= 2 for x in t3) for w in base3)})
        stab[n] = rows
    manifest = {"run": run_dir.name, "source": "reanalysis+best_track_oracle", "validated_against_ground_truth": False,
                "offset_c_base": OFFSET_BASE, "offset_note": "single-season median sensor-OISST (summer-autumn 2026), applied to all months",
                "years_all": YEARS_ALL, "years_last10": YEARS_LAST10, "growout_weeks": GROWOUT_WEEKS, "early_weeks": EARLY_WEEKS,
                "thresholds": {"heat": HEAT, "cold": COLD, "suit": SUIT, "storm_beaufort": STORM_BEAU},
                "weights_base": WEIGHTS, "weight_sets": WEIGHT_SETS, "dirichlet": {"n": N_DIRICHLET, "seed": SEED},
                "robust_rule": f"top-5 share >= {ROBUST_SHARE}", "score_definition": "1 - sum(w*minmax risk)",
                "inputs": {p.name: _sha(p) for p in (oisst_file, args.passages)},
                "sst_last_day": str(sst.index.max().date()), "stability": stab,
                "top3_base": {n: top_k(scores[("base", n)], 3) for n in GROWOUT_WEEKS},
                "robust_weeks": {n: [int(w) for w in rank_out[n].index[rank_out[n]["robust_top5"]]] for n in GROWOUT_WEEKS}}
    text = json.dumps(manifest, indent=2, default=_json)
    (run_dir / "manifest.json").write_text(text, encoding="utf-8")
    print(text)
    print(months.round(3).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
