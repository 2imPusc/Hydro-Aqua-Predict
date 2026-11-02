"""Paper 1 / T4b: Chronos-2 + ridge hybrids with the SAME weather features, confirmed on unseen NERRS stations.

Why: T3 (RL-75) compared ridge B5D-fc (8 aggregated weather features, learned per station) with zero-shot Chronos-2 (raw
series), so its conclusion mixes model and encoding. Its line "pure Chronos is best at <= 3 h" was only tested against B4D-n.
A post-hoc mean of Chronos none and B5D-fc looked better than both on the same 8 stations, which therefore cannot confirm it.

Arms (per station x horizon, as-issued weather only, every Chronos forecast causal: 672-step context ending at the origin):
  * resid-none:  Chronos none + ridge on its residual, features = exactly the 8 B5D-fc weather features
  * stack-B5D:   ridge B5D-fc (delta target) + feature (Chronos none q50 - current)
  * avg:         (Chronos none + ridge B5D-fc) / 2
  * switch-180:  Chronos none for h <= 180 min, ridge B5D-fc for h > 180 min (the RL-75 claim, verbatim)
Sets: ``dev`` = the 8 T3 stations (exploratory only, already looked at); ``conf`` = 12 stations of CDMO request 184841.
Rules: see VERDICT_RULES and preregistration.json. Stages:

    python experiments/paper1_t4b_hybrid.py init                         # after the code commit; clean worktree required
    python experiments/paper1_t4b_hybrid.py t3-correction                # gate none vs B5D-fc from stored T3 forecasts
    .venv-fm/Scripts/python experiments/paper1_t4b_hybrid.py forecast --set dev|conf [--limit N]
    python experiments/paper1_t4b_hybrid.py fit --set dev|conf
    python experiments/paper1_t4b_hybrid.py evaluate --set dev|conf
    python experiments/paper1_t4b_hybrid.py manifest
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_var] = "2"

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from experiments import paper1_t3_nerrs as t3  # noqa: E402
from experiments import paper1_t4b_step0 as step0  # noqa: E402

RUN_NAME = step0.RUN_NAME
TRACKED_PREREG = Path(__file__).with_name("paper1_t4b_preregistration.json")
SWITCH_MINUTES = 180
HORIZONS = t3.HORIZONS
CHRONOS_MODEL = t3.CHRONOS_MODEL
MIN_FREE_RAM_GB = 3.0
DEV_RESERVES = {"rkb": "Rookery Bay", "gtm": "Guana Tolomato Matanzas", "mar": "Mission-Aransas"}
BLOCK_END = {"dev": t3.DATASETS["cdmo"]["test"][1], "conf": "2025-12-31 06:00"}  # conf: last eligible origin, step 0
ARMS = ("resid-none", "stack-B5D", "avg", "switch-180")
TRAINED_ARMS = ("resid-none", "stack-B5D")
REF_RIDGE = {"resid-none": "ridge-B5D-fc-3h", "stack-B5D": "ridge-B5D-fc-3h", "avg": "ridge-B5D-fc", "switch-180": "ridge-B5D-fc"}

VERDICT_RULES = {
    "gate": "t3.gate_nerrs unchanged (>= 4/5 equal time blocks lower MAE and RMSE, DM-HLN p < 0.05 on per-slot mean absolute loss, lag = ceil(h / 6 h)). Block windows are fixed in advance: dev ends 2025-12-31 12:00 (as T3), conf ends 2025-12-31 06:00 (last eligible origin in step 0).",
    "references": "Each arm is compared with Chronos none and with ridge B5D-fc. Trained arms (resid-none, stack-B5D) use ridge-B5D-fc-3h, a B5D-fc retrained on the identical 3-h training-origin set, so that training stride is not confounded with hybridisation; avg and switch-180 use ridge-B5D-fc in the T3 recipe (30-min training origins). Trained arm vs the T3-recipe ridge and ridge-3h vs T3-recipe ridge are secondary.",
    "holm_family": "conf only, 42 tests: {resid-none, stack-B5D, avg} x {none, ridge reference} x 6 horizons (36) + switch-180 x its non-degenerate reference x 6 horizons (ridge at h <= 180, none at h > 180).",
    "reserve_call": "For a pair at a horizon, 'win' iff pooled gate passes AND Holm p < 0.05 AND MAE ratio < 1 in 3/3 reserves AND day-block bootstrap 95 % CI of the ratio is entirely below 1 in >= 2/3 reserves. 'loss' is the mirror image (reference passes the gate, ratio > 1 in 3/3, CI entirely above 1 in >= 2/3). Otherwise 'tie'. With 3 reserves no inferential test at reserve level exists: this is a descriptive consistency rule, and reserves are the unit of independence.",
    "arm_conclusion": "An arm 'beats both' at a horizon iff its reserve_call is 'win' against both references. Label: 'supported' if >= 4/6 horizons, 'partial' if 1-3, 'not_supported' if 0. Claim 'hybrid helps at 6-12 h' needs 'beats both' at both 360 and 720 for that arm. switch-180 equals one reference at every horizon, so it is judged only against the other: same labels on reserve_call 'win' vs the non-degenerate reference.",
    "encoding_reading": "Read at 360 and 720 min from resid-none vs ridge-B5D-fc-3h: if the call is 'loss' at either horizon, 'ridge advantage survives identical weather features' (the T3 gap is not only encoding); otherwise 'T3 gap at 6-12 h not attributable to the Chronos backbone given identical features'. stack-B5D contains the ridge features and is not used for this reading.",
    "station_level": "Per pair x horizon, secondary, plan section 5.3: share of stations won, median MAE skill, two-sided Wilcoxon signed-rank and sign test on per-station MAE differences. Stations in one reserve are not independent (apaebwq / apaeswq share one site and weather cell), so reserve_call decides, not these tests.",
    "persistence": "Every model vs persistence: gate and ratio per horizon, secondary; skill = 1 - MAE / MAE persistence.",
    "dev_protocol": "dev is exploratory: reported with the same tables, never used to choose an arm, threshold, feature or lambda rule. Only a coding bug found on dev may change the code, and then by a committed amendment listed in NOTES.md before conf is scored.",
    "conf_protocol": "evaluate --set conf runs once into a write-once directory. Anything else on conf is labelled post-hoc in NOTES.md.",
    "negative_results": "A negative or tied verdict is reported as such.",
}


def run_dir() -> Path:
    return paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME


def t3_dir() -> Path:
    return paths.EXPERIMENT_OUTPUT_DIR / t3.RUN_NAME


def reserve_of(station: str) -> str:
    if station in step0.CONF_STATIONS:
        return step0.CONF_STATIONS[station][0]
    return DEV_RESERVES[station[:3]]


def free_ram_gb() -> float | None:
    if sys.platform != "win32":
        return None
    import ctypes

    class Status(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    s = Status()
    s.dwLength = ctypes.sizeof(Status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
    return s.ullAvailPhys / 2 ** 30


# --------------------------------------------------------------------------- sets
def load_stations(which: str) -> dict[str, t3.Station]:
    if which == "dev":
        return t3.stations("cdmo")  # T3 run directory, read-only
    return {name: step0.conf_station(name) for name in step0.CONF_STATIONS}


def test_origins(which: str, sts: dict[str, t3.Station]) -> pd.DataFrame:
    if which == "dev":
        return pd.read_parquet(t3_dir() / "data-cdmo" / t3.ORIGINS_FILE)
    marks = t3.origin_marks(*step0.TEST, step0.ORIGIN_HOURS, False)
    rows = []
    for name, st in sts.items():
        ok = t3.eligible(st, st.index_of(marks.to_numpy()), ("fc",))
        rows.append(pd.DataFrame({"station": name, "issued_at": marks[ok]}))
    return pd.concat(rows, ignore_index=True)


def train_indices_3h(st: t3.Station) -> np.ndarray:
    """Eligible (presence only) 3-h training origins; every target ends before the test period starts."""
    lo, hi = st.index_of(np.array([np.datetime64(step0.TRAIN[0]), np.datetime64(step0.TRAIN[1])]))
    idx = np.arange(lo, hi - t3.LENGTH, step0.TRAIN_ORIGIN_STEPS)
    return idx[t3.eligible(st, idx, ("fc",))]


def train_indices_30min(st: t3.Station) -> np.ndarray:
    lo, hi = st.index_of(np.array([np.datetime64(step0.TRAIN[0]), np.datetime64(step0.TRAIN[1])]))
    return np.arange(lo, hi - t3.LENGTH, t3.TRAIN_EVERY)


# --------------------------------------------------------------------------- Chronos (causal)
def chronos_frame(st: t3.Station, idx: np.ndarray, fm, keep_all_quantiles: bool) -> pd.DataFrame:
    """Chronos none at origins idx. Input is only st.target(idx, t3.PAST): marks t-671 .. t."""
    from experiments import paper1_t1_chronos2 as t1

    if t3.PAST.max() != 0 or len(t3.PAST) != t3.CONTEXT:
        raise AssertionError("context_not_causal")
    q = fm.quantile_paths(st.target(idx, t3.PAST).astype(np.float32), t3.LENGTH, t3.BATCH)
    issued = st.t0 + idx * np.timedelta64(t3.STEP, "m")
    levels = t1.QUANTILES if keep_all_quantiles else (0.5,)
    frames = []
    for h in HORIZONS:
        row = pd.DataFrame({"station": st.name, "issued_at": issued, "horizon_minutes": h})
        for level in levels:
            row[t1.quantile_column(level)] = q[:, h // t3.STEP - 1, t1.QUANTILES.index(level)]
        frames.append(row)
    return pd.concat(frames, ignore_index=True)


def stage_forecast(args) -> None:
    from experiments import paper1_t1_chronos2 as t1
    from experiments import paper1_t2_chronos2_cov as t2

    free = free_ram_gb()
    if free is not None and free < MIN_FREE_RAM_GB:
        raise MemoryError(f"free_ram_gb={free:.2f}")
    sts = load_stations(args.set)
    origins = test_origins(args.set, sts)
    repo, rev = t1.CHRONOS2[CHRONOS_MODEL]
    fm = t2.Chronos2CovForecaster(repo, rev, t3.THREADS)
    out = run_dir() / f"fm-{args.set}"
    if args.limit:   # parity pilot: dev test origins vs T3's stored forecasts, nothing written
        stored = pd.read_parquet(t3_dir() / f"fm-cdmo-{CHRONOS_MODEL}-none.parquet")
        pick = origins.sample(args.limit, random_state=0)
        worst = 0.0
        for name, part in pick.groupby("station"):
            st = sts[name]
            frame = chronos_frame(st, st.index_of(part["issued_at"].to_numpy()), fm, False)
            merged = frame.merge(stored, on=["station", "issued_at", "horizon_minutes"], suffixes=("", "_t3"))
            worst = max(worst, float((merged.q50 - merged.q50_t3).abs().max()))
        print(json.dumps({"parity_max_abs_diff_q50": worst, "n": args.limit}))
        return
    timing = []
    for name, st in sts.items():
        jobs = [("train", train_indices_3h(st), False)]
        if args.set == "conf":
            jobs.append(("test", st.index_of(origins.loc[origins.station == name, "issued_at"].to_numpy()), True))
        for split, idx, full in jobs:
            path = out / f"{split}-{name}.parquet"
            if path.exists():   # write-once: a restarted job resumes after the last finished station
                continue
            start = time.perf_counter()
            frame = chronos_frame(st, idx, fm, full)
            t3._write(path, frame)
            timing.append({"station": name, "split": split, "n_origins": int(len(idx)), "seconds": time.perf_counter() - start})
            print(json.dumps(timing[-1]), flush=True)
    stamp = pd.Timestamp.now("UTC").strftime("%Y%m%dT%H%M%S")
    t3._write(out / f"timing-{stamp}.json", {"repo": repo, "revision": rev, "threads": t3.THREADS, "batch": t3.BATCH, "stations": timing})


def read_chronos(which: str, split: str, station: str) -> pd.DataFrame:
    if which == "dev" and split == "test":
        frame = pd.read_parquet(t3_dir() / f"fm-cdmo-{CHRONOS_MODEL}-none.parquet")
        frame = frame[frame.station == station]
    else:
        frame = pd.read_parquet(run_dir() / f"fm-{which}" / f"{split}-{station}.parquet")
    return frame[["station", "issued_at", "horizon_minutes", "q50"]]


# --------------------------------------------------------------------------- hybrids
def residual_target(actual: np.ndarray, chronos: np.ndarray) -> np.ndarray:
    return actual - chronos


def combine(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the two training-free arms. Needs: horizon_minutes, none, ridge-B5D-fc."""
    out = frame.copy()
    out["avg"] = (out["none"] + out["ridge-B5D-fc"]) / 2.0
    out["switch-180"] = np.where(out["horizon_minutes"] <= SWITCH_MINUTES, out["none"], out["ridge-B5D-fc"])
    return out


def fit_station(st: t3.Station, test_idx: np.ndarray, test_q50: pd.DataFrame, train_q50: pd.DataFrame) -> tuple[list[pd.DataFrame], list[dict]]:
    """Ridge baselines (T3 recipe) and trained arms for one station. q50 frames: issued_at, horizon_minutes, q50."""
    from experiments.transfer_forecast import FEATURES

    s15 = t3._series15(st)
    idx30, idx3 = train_indices_30min(st), train_indices_3h(st)
    test_marks = st.t0 + test_idx * np.timedelta64(t3.STEP, "m")
    core = ["current", "d15", "d30", "d45", "d60", "delta"]
    preds, lambdas = [], []
    for h in HORIZONS:
        te = s15.features(test_idx, h).reset_index(drop=True)
        wte = t3.weather_features(st, "fc", test_idx, h)
        tef = pd.concat([te, wte], axis=1)
        wx = list(wte.columns)
        base = pd.DataFrame({"station": st.name, "issued_at": test_marks, "horizon_minutes": h,
                             "actual": st.target(test_idx, np.array([h // t3.STEP]))[:, 0], "persistence": te["current"].to_numpy()})
        base["diurnal-7d"] = te["current"].to_numpy() + np.nan_to_num(te["prof7"].to_numpy())
        q_te = test_q50[test_q50.horizon_minutes == h].set_index("issued_at")["q50"].reindex(test_marks).to_numpy(dtype=float)
        if not np.isfinite(q_te).all():
            raise AssertionError(f"missing_chronos_test:{st.name}:{h}")
        base["none"] = q_te

        def run(label, frame, cols, keep, test_frame):
            trf = frame.loc[keep]
            pred, lam = t3.ridge_fit_predict(trf, test_frame, cols, h)
            lambdas.append({"station": st.name, "horizon_minutes": h, "model": label, "lambda": lam, "n_train": int(len(trf))})
            return pred

        # T3 recipe, 30-min training origins
        tr = s15.features(idx30, h).reset_index(drop=True)
        wtr = t3.weather_features(st, "fc", idx30, h)
        trf = pd.concat([tr, wtr], axis=1)
        ok_core = tr[core].notna().all(axis=1).to_numpy()
        base["ridge-B4D-n"] = te["current"].to_numpy() + run("ridge-B4D-n", trf, list(FEATURES), ok_core, tef)
        base["ridge-B5D-fc"] = te["current"].to_numpy() + run("ridge-B5D-fc", trf, list(FEATURES) + wx, ok_core & np.isfinite(wtr.to_numpy()).all(1), tef)

        # identical 3-h training origins for the reference and the trained arms
        tr3 = s15.features(idx3, h).reset_index(drop=True)
        wtr3 = t3.weather_features(st, "fc", idx3, h)
        marks3 = st.t0 + idx3 * np.timedelta64(t3.STEP, "m")
        q_tr = train_q50[train_q50.horizon_minutes == h].set_index("issued_at")["q50"].reindex(marks3).to_numpy(dtype=float)
        trf3 = pd.concat([tr3, wtr3], axis=1)
        keep3 = tr3[core].notna().all(axis=1).to_numpy() & np.isfinite(wtr3.to_numpy()).all(1) & np.isfinite(q_tr)
        base["ridge-B5D-fc-3h"] = te["current"].to_numpy() + run("ridge-B5D-fc-3h", trf3, list(FEATURES) + wx, keep3, tef)
        stack_tr = trf3.assign(chronos_delta=q_tr - tr3["current"].to_numpy())
        stack_te = tef.assign(chronos_delta=q_te - te["current"].to_numpy())
        base["stack-B5D"] = te["current"].to_numpy() + run("stack-B5D", stack_tr, list(FEATURES) + wx + ["chronos_delta"], keep3, stack_te)
        resid_tr = trf3.assign(delta=residual_target(tr3["current"].to_numpy() + tr3["delta"].to_numpy(), q_tr))
        base["resid-none"] = q_te + run("resid-none", resid_tr, wx, keep3, tef)
        preds.append(base)
    return preds, lambdas


def stage_fit(args) -> None:
    root = run_dir()
    out_path = root / f"predictions-{args.set}.parquet"
    if out_path.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out_path}")
    sts = load_stations(args.set)
    origins = test_origins(args.set, sts)
    frames, lambdas = [], []
    for name, st in sts.items():
        marks = origins.loc[origins.station == name, "issued_at"].to_numpy()
        preds, lam = fit_station(st, st.index_of(marks), read_chronos(args.set, "test", name), read_chronos(args.set, "train", name))
        frames += preds
        lambdas += lam
        print(f"fit {name}", flush=True)
    wide = combine(pd.concat(frames, ignore_index=True))
    parity = {}
    if args.set == "dev":   # same code path as conf must reproduce T3's stored ridge
        stored = pd.read_parquet(t3_dir() / "ridge-cdmo.parquet")
        merged = wide.merge(stored, on=["station", "issued_at", "horizon_minutes"], suffixes=("", "_t3"), validate="one_to_one")
        if len(merged) != len(wide):
            raise AssertionError("t3_parity_rows")
        for col in ("ridge-B4D-n", "ridge-B5D-fc", "persistence"):
            parity[col] = float((merged[col] - merged[f"{col}_t3"]).abs().max())
            if parity[col] > 1e-6:
                raise AssertionError(f"t3_parity:{col}:{parity[col]}")
    t3._write(out_path, wide)
    t3._write(root / f"lambdas-{args.set}.csv", pd.DataFrame(lambdas))
    t3._write(root / f"fit-{args.set}.json", {"t3_ridge_parity_max_abs": parity, "n_rows": int(len(wide))})
    print(json.dumps(parity))


# --------------------------------------------------------------------------- verdict rules
def reserve_call(row_ratios: dict[str, float], ci_lo: dict[str, float], ci_hi: dict[str, float], gate: bool, rev_gate: bool, holm_p: float) -> str:
    """Pre-registered reserve-level rule for one pair x horizon."""
    n = len(row_ratios)
    if gate and holm_p < 0.05 and all(v < 1 for v in row_ratios.values()) and sum(v < 1 for v in ci_hi.values()) >= n - 1:
        return "win"
    if rev_gate and holm_p < 0.05 and all(v > 1 for v in row_ratios.values()) and sum(v > 1 for v in ci_lo.values()) >= n - 1:
        return "loss"
    return "tie"


def arm_label(n_horizons: int) -> str:
    return "supported" if n_horizons >= 4 else "partial" if n_horizons >= 1 else "not_supported"


def encoding_reading(calls: dict[int, str]) -> str:
    if any(calls[h] == "loss" for h in (360, 720)):
        return "ridge_advantage_survives_identical_weather_features"
    return "t3_gap_not_attributable_to_backbone_given_identical_features"


def primary_pairs() -> list[tuple[str, str, tuple[int, ...]]]:
    pairs = []
    for arm in ("resid-none", "stack-B5D", "avg"):
        pairs += [(arm, "none", HORIZONS), (arm, REF_RIDGE[arm], HORIZONS)]
    pairs += [("switch-180", "ridge-B5D-fc", tuple(h for h in HORIZONS if h <= SWITCH_MINUTES)),
              ("switch-180", "none", tuple(h for h in HORIZONS if h > SWITCH_MINUTES))]
    return pairs


def station_stats(metrics: pd.Series, reference: pd.Series) -> dict:
    """Paired per-station MAE: wins, median skill, Wilcoxon and sign test (two-sided)."""
    from scipy import stats

    diff = (metrics - reference).dropna()
    nz = diff[diff != 0]
    wins = int((diff < 0).sum())
    wil = float(stats.wilcoxon(nz, alternative="two-sided").pvalue) if len(nz) else float("nan")
    sign = float(stats.binomtest(int((nz < 0).sum()), len(nz), 0.5).pvalue) if len(nz) else float("nan")
    return {"stations_won": wins, "n_stations": int(len(diff)), "median_skill": float((1 - metrics / reference).median()), "wilcoxon_p": wil, "sign_p": sign}


def compare(wide: pd.DataFrame, cand: str, ref: str, by_station: pd.DataFrame, reserves: list[str], horizons=HORIZONS, spacing: float = 6.0) -> pd.DataFrame:
    """One row per horizon: pooled gate both directions, bootstrap CI, per-reserve ratio / CI / gate, per-station tests."""
    sub = wide[wide.horizon_minutes.isin(horizons)]
    fwd, rev = t3.gate_nerrs(sub, cand, ref, spacing), t3.gate_nerrs(sub, ref, cand, spacing)
    out = t3.pair_outcomes(fwd, rev)
    out["mae"], out["mae_ref"], out["n"] = fwd["mae"].to_numpy(), fwd["mae_ref"].to_numpy(), fwd["n"].to_numpy()
    out["gate_ref"] = rev["gate_pass"].to_numpy()
    cis = [t3.bootstrap_ratio(sub[sub.horizon_minutes == h], cand, ref) for h in out.horizon_minutes]
    out["ratio_ci_lo"], out["ratio_ci_hi"] = [c[1] for c in cis], [c[2] for c in cis]
    for res in reserves:
        part = sub[sub.reserve == res]
        g = t3.gate_nerrs(part, cand, ref, spacing).set_index("horizon_minutes")
        gr = t3.gate_nerrs(part, ref, cand, spacing).set_index("horizon_minutes")
        rc = [t3.bootstrap_ratio(part[part.horizon_minutes == h], cand, ref) for h in out.horizon_minutes]
        out[f"ratio[{res}]"], out[f"lo[{res}]"], out[f"hi[{res}]"] = [c[0] for c in rc], [c[1] for c in rc], [c[2] for c in rc]
        out[f"gate[{res}]"] = g.loc[out.horizon_minutes, "gate_pass"].to_numpy()
        out[f"gate_ref[{res}]"] = gr.loc[out.horizon_minutes, "gate_pass"].to_numpy()
    rows = [station_stats(by_station[(by_station.model == cand) & (by_station.horizon_minutes == h)].set_index("station").mae,
                          by_station[(by_station.model == ref) & (by_station.horizon_minutes == h)].set_index("station").mae) for h in out.horizon_minutes]
    return pd.concat([out.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def station_metrics(wide: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    rows = []
    for m in models:
        err = wide[m] - wide["actual"]
        for (st, h), e in err.groupby([wide.station, wide.horizon_minutes]):
            rows.append({"station": st, "reserve": reserve_of(st), "model": m, "horizon_minutes": h, "n": len(e), "mae": e.abs().mean(), "rmse": np.sqrt((e ** 2).mean()), "bias": e.mean()})
    return pd.DataFrame(rows)


def scope_metrics(wide: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    rows = []
    for scope, part in [("pooled", wide)] + list(wide.groupby("reserve")):
        for m in models:
            for h, p in part.groupby("horizon_minutes"):
                e = p[m] - p["actual"]
                base = (p["persistence"] - p["actual"]).abs().mean()
                rows.append({"scope": scope, "model": m, "horizon_minutes": h, "n": len(e), "mae": e.abs().mean(), "rmse": np.sqrt((e ** 2).mean()), "bias": e.mean(), "skill_vs_persistence": 1 - e.abs().mean() / base})
    return pd.DataFrame(rows)


MODELS = ["persistence", "diurnal-7d", "ridge-B4D-n", "ridge-B5D-fc", "ridge-B5D-fc-3h", "none", "resid-none", "stack-B5D", "avg", "switch-180"]


def stage_evaluate(args) -> None:
    from experiments import paper1_t1_chronos2 as t1

    out = run_dir() / f"eval-{args.set}"
    if out.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out}")
    wide = pd.read_parquet(run_dir() / f"predictions-{args.set}.parquet").dropna(subset=["actual"]).reset_index(drop=True)
    wide["reserve"] = wide.station.map(reserve_of)
    wide["block"] = step0.block_of(wide["issued_at"], BLOCK_END[args.set])
    empty = sorted(set(range(t3.N_BLOCKS)) - set(wide["block"].unique()))
    if empty:
        raise AssertionError(f"empty_blocks:{empty}")
    reserves = sorted(wide.reserve.unique())
    by_station = station_metrics(wide, MODELS)
    scopes = scope_metrics(wide, MODELS)

    tables = []
    for cand, ref, horizons in primary_pairs():
        tables.append(compare(wide, cand, ref, by_station, reserves, horizons).assign(role="primary"))
    secondary = [("resid-none", "ridge-B5D-fc"), ("stack-B5D", "ridge-B5D-fc"), ("ridge-B5D-fc-3h", "ridge-B5D-fc"), ("none", "ridge-B5D-fc"), ("ridge-B5D-fc", "ridge-B4D-n"), ("none", "ridge-B4D-n")]
    secondary += [(m, "persistence") for m in ("none", "ridge-B5D-fc", "resid-none", "stack-B5D", "avg", "switch-180")]
    for cand, ref in secondary:
        tables.append(compare(wide, cand, ref, by_station, reserves).assign(role="secondary"))
    table = pd.concat(tables, ignore_index=True)
    primary = table.role.eq("primary")
    if int(primary.sum()) != 42:
        raise AssertionError(f"holm_family:{int(primary.sum())}")
    table.loc[primary, "holm_p"] = t1.holm(table.loc[primary, "dm_p"]).to_numpy()

    def call(row) -> str:
        return reserve_call({r: row[f"ratio[{r}]"] for r in reserves}, {r: row[f"lo[{r}]"] for r in reserves}, {r: row[f"hi[{r}]"] for r in reserves},
                            bool(row["gate_pass"]), bool(row["gate_ref"]), float(row["holm_p"]))

    table.loc[primary, "reserve_call"] = table[primary].apply(call, axis=1)
    p = table[primary]
    arms = {}
    for arm in ARMS:
        part = p[p.model == arm]
        if arm == "switch-180":
            wins = sorted(int(h) for h in part.loc[part.reserve_call == "win", "horizon_minutes"])
        else:
            pivot = part.pivot(index="horizon_minutes", columns="reference", values="reserve_call")
            wins = sorted(int(h) for h in pivot.index[(pivot == "win").all(axis=1)])
        arms[arm] = {"beats_both_horizons": wins, "label": arm_label(len(wins)), "helps_6_12h": bool({360, 720} <= set(wins)),
                     "calls": {f"{r.reference}@{int(r.horizon_minutes)}": r.reserve_call for r in part.itertuples()}}
    resid = p[(p.model == "resid-none") & (p.reference == "ridge-B5D-fc-3h")].set_index("horizon_minutes")["reserve_call"].to_dict()
    verdict = {"set": args.set, "status": "exploratory" if args.set == "dev" else "confirmatory", "block_end": BLOCK_END[args.set], "n_rows": int(len(wide)),
               "n_stations": int(wide.station.nunique()), "n_origins": int(wide[["station", "issued_at"]].drop_duplicates().shape[0]), "reserves": reserves,
               "arms": arms, "encoding_reading": encoding_reading({int(k): v for k, v in resid.items()})}
    out.mkdir(parents=True)
    t3._write(out / "metrics_station.csv", by_station)
    t3._write(out / "metrics_scope.csv", scopes)
    t3._write(out / "verdicts.csv", table)
    t3._write(out / "verdict.json", verdict)
    pd.set_option("display.width", 250)
    print(scopes[scopes.scope == "pooled"].pivot(index="horizon_minutes", columns="model", values="mae")[MODELS].round(3).to_string())
    print(json.dumps(verdict, indent=1, default=str))


# --------------------------------------------------------------------------- RL-75 correction
def stage_t3_correction(_args) -> None:
    """Re-analysis of stored T3 forecasts (the ratios were already seen; not a new hypothesis)."""
    from experiments import paper1_t1_chronos2 as t1

    out = run_dir() / "t3-correction"
    if out.exists():
        raise FileExistsError(f"refusing_to_overwrite:{out}")
    wide = pd.read_parquet(t3_dir() / "ridge-cdmo.parquet")
    fm = pd.read_parquet(t3_dir() / f"fm-cdmo-{CHRONOS_MODEL}-none.parquet")[["station", "issued_at", "horizon_minutes", "q50"]].rename(columns={"q50": "none"})
    wide = wide.merge(fm, on=["station", "issued_at", "horizon_minutes"], how="left", validate="one_to_one").dropna(subset=["actual"]).reset_index(drop=True)
    if wide["none"].isna().any():
        raise AssertionError("origin_mismatch")
    wide["reserve"] = wide.station.map(reserve_of)
    wide["block"] = step0.block_of(wide["issued_at"], BLOCK_END["dev"])
    reserves = sorted(wide.reserve.unique())
    by_station = station_metrics(wide, ["none", "ridge-B5D-fc", "ridge-B4D-n", "persistence"])
    tables = [compare(wide, "none", ref, by_station, reserves).assign(role="correction") for ref in ("ridge-B5D-fc", "persistence", "ridge-B4D-n")]
    tables[0]["holm_p"] = t1.holm(tables[0]["dm_p"]).to_numpy()
    table = pd.concat(tables, ignore_index=True)
    out.mkdir(parents=True)
    t3._write(out / "gate_none.csv", table)
    pd.set_option("display.width", 250)
    cols = ["horizon_minutes", "reference", "mae", "mae_ref", "mae_ratio", "ratio_ci_lo", "ratio_ci_hi", "blocks_beating", "blocks_beaten", "dm_p", "holm_p", "outcome", "stations_won", "wilcoxon_p"] + [f"ratio[{r}]" for r in reserves]
    print(table[cols].round(4).to_string())


# --------------------------------------------------------------------------- init / manifest
def preregistration_payload() -> dict:
    from experiments import paper1_t1_chronos2 as t1

    root = run_dir()
    step0_files = [root / "step0_coverage.json", *sorted((root / "data-conf").glob("*")), *sorted((root / "weather-fc").glob("*"))]
    repo, rev = t1.CHRONOS2[CHRONOS_MODEL]
    return {
        "run": RUN_NAME, "written_at_utc": pd.Timestamp.now("UTC").isoformat(), **t3._git_head(),
        "question": __doc__.split("\n\n")[1],
        "sets": {"dev": {"stations": sorted(t3.CDMO_STATIONS), "reserves": list(DEV_RESERVES.values()), "status": "exploratory, already looked at (RL-75, review 2026-11-02)", "source": "paper1-t3-20261029 (read-only)", "origins": "T3 origins-3wx (eligibility includes observed weather)"},
                 "conf": {"stations": {k: v[0] for k, v in step0.CONF_STATIONS.items()}, "status": "confirmatory", "zip": str(step0.CONF_ZIP), "zip_sha256": step0.CONF_ZIP_SHA256,
                          "origins": "eligibility on target and forecast weather presence only; no observed-weather requirement"}},
        "prior_use_of_conf_data": "Temp and forecasts of 184841 were not used by T3. Paper 2 F4 used only DO/Turb of 184841. Step 0 read flags / presence only, never a forecast error.",
        "step0_files_sha256": {str(p.relative_to(root)): t3._sha256(p) for p in step0_files},
        "periods": {"train": step0.TRAIN, "test": step0.TEST, "origin_hours": step0.ORIGIN_HOURS, "block_end": BLOCK_END},
        "weather": {"source": "Open-Meteo Previous Runs best_match at WQ station coordinates (same code as T3)", "variables": list(t3.FC_VARS), "rule": "T3 as-issued lead rule", "features": "t3.weather_features: 8 features, unchanged"},
        "chronos": {"model": CHRONOS_MODEL, "repo": repo, "revision": rev, "config": "none", "context_steps": t3.CONTEXT, "prediction_length": t3.LENGTH, "point": "q50", "threads": t3.THREADS,
                    "train_origins": f"every {step0.TRAIN_ORIGIN_STEPS * t3.STEP} min in the train window, eligibility on presence; targets end before test start. Zero-shot, so train-year forecasts are out-of-sample by construction; the model's own training cutoff is outside this repo's control."},
        "ridge": {"recipe": "t3.ridge_fit_predict, per station x horizon, lambdas and selection as T3", "ridge-B5D-fc": "T3 recipe, 30-min training origins; dev must reproduce T3's stored forecasts to 1e-6",
                  "ridge-B5D-fc-3h": "same features, 3-h training origins = training set of the trained arms",
                  "resid-none": "target actual - q50, features = the 8 weather features only", "stack-B5D": "delta target, B5D-fc features + (q50 - current)"},
        "arms": ARMS, "switch_minutes": SWITCH_MINUTES, "horizons": HORIZONS, "baselines": ["persistence", "diurnal-7d", "ridge-B4D-n", "ridge-B5D-fc", "ridge-B5D-fc-3h", "none"],
        "verdict_rules": VERDICT_RULES, "n_boot": t3.N_BOOT,
        "known_limits_before_scoring": ["Jobos: job19wq has 0 eligible origins in blocks 1-2 and job10wq 3 in block 1, so Jobos block 1 is essentially job09 + job20.",
                                        "apaebwq / apaeswq are bottom and surface sondes of one site and share weather.",
                                        "CDMO 2025 is provisional; same 11-month test year as T3, so dev and conf share weather events only if regional."],
    }


def stage_init(_args) -> None:
    head = t3._git_head()
    if not head["worktree_clean"]:
        raise RuntimeError("worktree_not_clean")
    payload = preregistration_payload()
    t3._write(run_dir() / "preregistration.json", payload)
    t3._write(TRACKED_PREREG, payload)
    print(f"wrote {TRACKED_PREREG}; git_head {head['git_head']}")


def stage_manifest(_args) -> None:
    root = run_dir()
    t3._write(root / "manifest.json", {str(p.relative_to(root)).replace("\\", "/"): t3._sha256(p) for p in sorted(root.rglob("*")) if p.is_file() and p.name != "manifest.json"})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="stage", required=True)
    for name in ("init", "t3-correction", "manifest"):
        sub.add_parser(name)
    for name in ("forecast", "fit", "evaluate"):
        p = sub.add_parser(name)
        p.add_argument("--set", choices=("dev", "conf"), required=True)
        if name == "forecast":
            p.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    {"init": stage_init, "t3-correction": stage_t3_correction, "manifest": stage_manifest, "forecast": stage_forecast, "fit": stage_fit, "evaluate": stage_evaluate}[args.stage](args)


if __name__ == "__main__":
    main()
