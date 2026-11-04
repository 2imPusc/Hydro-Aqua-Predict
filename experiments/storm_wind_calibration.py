"""Task 2.1 (RL-HZCAL): calibrate the best-track parametric site-wind model against 4TA SYNOP.

    python experiments/storm_wind_calibration.py --run-name storm-wind-cal-20261104

Design fixed in ``experiments/storm_wind_calibration_preregistration.json`` (committed before any
output); this script only implements it.  Best track is an oracle: nothing here is forecast skill,
and nothing is activated (proposals are files in the run dir only).
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.storm_advisory import BEAUFORT_LOWER_MS, beaufort  # noqa: E402
from experiments import synop_storm as ss  # noqa: E402
from experiments.storm_hindcast import load_tracks  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PREREG = Path(__file__).resolve().parent / "storm_wind_calibration_preregistration.json"
DEFAULT_CONFIG = paths.ALERT_CONFIG_DEFAULT
RADIUS_KM = 300.0
NEAR_KM = 100.0
TRAIN = (2000, 2019)
TEST = (2020, 2025)
SYNOP_END = pd.Timestamp("2025-12-05", tz="UTC")
H1_RATIO = 0.85
C2_CV_RATIO = 0.95
BOOT_REPS = 2000
SEED = 20261104


# ---------------------------------------------------------------------------- variants ----
def fit_variants(train: pd.DataFrame) -> dict:
    near = train["min_dist_km"] <= NEAR_KM
    return {"C1": {"k": ss.fit_factor(train["model_max_ms"], train["obs_max_ms"])},
            "C2": {"k_near": ss.fit_factor(train.loc[near, "model_max_ms"], train.loc[near, "obs_max_ms"]),
                   "k_far": ss.fit_factor(train.loc[~near, "model_max_ms"], train.loc[~near, "obs_max_ms"])}}


def apply_variant(df: pd.DataFrame, name: str, params: dict) -> pd.Series:
    m = df["model_max_ms"].astype(float)
    if name == "C0":
        return m
    if name == "C1":
        return m * params["C1"]["k"]
    k = np.where(df["min_dist_km"] <= NEAR_KM, params["C2"]["k_near"], params["C2"]["k_far"])
    return m * k


def loso_cv(train: pd.DataFrame) -> dict:
    err = {"C1": [], "C2": []}
    for season in sorted(train["SEASON"].unique()):
        fit, hold = train[train["SEASON"] != season], train[train["SEASON"] == season]
        params = fit_variants(fit)
        for name in err:
            pred = apply_variant(hold, name, params)
            if name == "C2" and pred.isna().any():  # a band missing in the fit fold -> fall back to C1
                pred = pred.fillna(apply_variant(hold, "C1", params))
            err[name].extend((pred - hold["obs_max_ms"]).abs().tolist())
    return {k: float(np.mean(v)) for k, v in err.items()}


# ---------------------------------------------------------------------------- scoring -----
def tier_stats(obs_bf: pd.Series, pred_bf: pd.Series, thresholds: dict) -> dict:
    to = obs_bf.map(lambda b: ss.tier_from_beaufort(b, thresholds))
    tp = pred_bf.map(lambda b: ss.tier_from_beaufort(b, thresholds))
    out = {"tier_exact_agreement": float((to == tp).mean()) if len(to) else float("nan")}
    for lvl in (8, 10):
        o, p = obs_bf >= lvl, pred_bf >= lvl
        out[f"n_obs_ge{lvl}"] = int(o.sum())
        out[f"n_pred_ge{lvl}"] = int(p.sum())
        out[f"pod_ge{lvl}"] = float((o & p).sum() / o.sum()) if o.sum() else float("nan")
        out[f"far_ge{lvl}"] = float((p & ~o).sum() / p.sum()) if p.sum() else float("nan")
    return out


def score(df: pd.DataFrame, pred: pd.Series, thresholds: dict) -> dict:
    e = pred - df["obs_max_ms"]
    out = {"n": int(len(df)), "n_storms": int(df["SID"].nunique()), "bias": float(e.mean()),
           "mae": float(e.abs().mean())}
    out.update(tier_stats(df["obs_max_ms"].map(beaufort), pred.map(beaufort), thresholds))
    return out


def grouped(df: pd.DataFrame, preds: dict, by: str) -> pd.DataFrame:
    rows = []
    for key, g in df.groupby(by, sort=True):
        for name, p in preds.items():
            e = p.loc[g.index] - g["obs_max_ms"]
            rows.append({by: key, "variant": name, "n": len(g), "n_storms": g["SID"].nunique(),
                         "obs_mean": g["obs_max_ms"].mean(), "pred_mean": p.loc[g.index].mean(),
                         "bias": e.mean(), "mae": e.abs().mean()})
    return pd.DataFrame(rows)


def cluster_bootstrap(df: pd.DataFrame, pred_a: pd.Series, pred_b: pd.Series, reps: int, seed: int) -> dict:
    """MAE(a) - MAE(b), resampling storms (SID) with replacement."""
    ea, eb = (pred_a - df["obs_max_ms"]).abs(), (pred_b - df["obs_max_ms"]).abs()
    by = pd.DataFrame({"SID": df["SID"], "a": ea, "b": eb}).groupby("SID").agg(["sum", "count"])
    sa, sb, cnt = by[("a", "sum")].to_numpy(), by[("b", "sum")].to_numpy(), by[("a", "count")].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(sa), size=(reps, len(sa)))
    diff = (sa[idx].sum(1) - sb[idx].sum(1)) / cnt[idx].sum(1)
    return {"point": float(ea.mean() - eb.mean()), "p2.5": float(np.percentile(diff, 2.5)),
            "p95": float(np.percentile(diff, 95)), "p97.5": float(np.percentile(diff, 97.5)),
            "n_storms": int(len(sa)), "reps": reps, "seed": seed}


def sign_test(df: pd.DataFrame, pred_a: pd.Series, pred_b: pd.Series) -> dict:
    g = pd.DataFrame({"SID": df["SID"], "a": (pred_a - df["obs_max_ms"]).abs(),
                      "b": (pred_b - df["obs_max_ms"]).abs()}).groupby("SID").mean()
    wins, losses = int((g["a"] < g["b"]).sum()), int((g["a"] > g["b"]).sum())
    n = wins + losses
    tail = sum(math.comb(n, i) for i in range(0, min(wins, losses) + 1)) / 2 ** n if n else 1.0
    return {"storms_better": wins, "storms_worse": losses, "ties": int(len(g) - n), "p_two_sided": min(1.0, 2 * tail)}


def proposed_thresholds(k: float, spec: dict) -> dict:
    out = {}
    for tier, lvl in spec["thresholds"].items():
        raw_level = beaufort(BEAUFORT_LOWER_MS[int(lvl)] / k)
        lo, hi = spec["guardrails"]["min"][tier], spec["guardrails"]["max"][tier]
        out[tier] = int(min(max(raw_level, lo), hi))
    return out


# ---------------------------------------------------------------------------- main --------
def build_passages(tracks: pd.DataFrame) -> pd.DataFrame:
    df = ss.load_synop(columns=["obs_local", "obs_utc", "station_code", "lat", "lon", "wspd_ms"])
    meta = df.groupby("station_code")[["lat", "lon"]].first()
    storms = tracks[(tracks["SEASON"] >= TRAIN[0]) & (tracks["SEASON"] <= TEST[1])]
    parts = []
    for code in ss.HPQN_CODES:
        lat, lon = float(meta.loc[code, "lat"]), float(meta.loc[code, "lon"])
        g = df[df["station_code"] == code]
        flagged = ss.flag_wind(g, ss.storm_near(g["obs_utc"], tracks, lat, lon))
        p = ss.station_passages(storms, flagged[flagged["wspd_valid"]], lat, lon, radius_km=RADIUS_KM)
        if len(p):
            parts.append(p.assign(station_code=code, group=ss.STATIONS[code]["group"]))
        print(f"  {code}: {len(p)} passages", flush=True)
    out = pd.concat(parts, ignore_index=True)
    return out[out["window_start"] < SYNOP_END].reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-name", required=True)
    args = ap.parse_args()
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / args.run_name
    if run_dir.exists():
        sys.exit(f"{run_dir} exists; pick a new run name")
    prereg_commit = subprocess.run(["git", "log", "-1", "--format=%H %cI", "--", str(PREREG)], cwd=REPO,
                                   capture_output=True, text=True).stdout.strip()
    if not prereg_commit:
        sys.exit("pre-registration is not committed")
    run_dir.mkdir(parents=True)
    started = datetime.now(timezone.utc)

    config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    spec = config["hazards"]["storm_wind"]
    thresholds = spec["thresholds"]
    tracks, track_files = load_tracks()
    tracks = tracks[tracks["SEASON"] >= 1999]

    allp = build_passages(tracks)
    allp["eligible"] = (allp["n_pairs"] >= 2) & allp["obs_near_peak"] & (allp["model_max_ms"] > 0)
    allp["split"] = np.where(allp["SEASON"] <= TRAIN[1], "train", "test")
    allp["dist_band"] = allp["min_dist_km"].map(ss.distance_band)
    allp["intensity"] = allp["storm_beaufort_closest"].map(ss.intensity_class)
    allp.to_csv(run_dir / "passages_all.csv", index=False)
    p = allp[allp["eligible"]].copy()

    # --- fit + select on train open_sea -------------------------------------------------------
    sea = p[p["group"] == "open_sea"]
    train, test = sea[sea["split"] == "train"], sea[sea["split"] == "test"]
    params = fit_variants(train)
    cv = loso_cv(train)
    selected = "C2" if cv["C2"] < C2_CV_RATIO * cv["C1"] else "C1"

    preds = {name: apply_variant(test, name, params) for name in ("C0", "C1", "C2")}
    preds["selected"] = preds[selected]
    scores = {name: score(test, pr, thresholds) for name, pr in preds.items()}
    scores_train = {name: score(train, apply_variant(train, name, params), thresholds) for name in ("C0", "C1", "C2")}
    boot = cluster_bootstrap(test, preds["selected"], preds["C0"], BOOT_REPS, SEED)
    sign = sign_test(test, preds["selected"], preds["C0"])

    s0, s1 = scores["C0"], scores["selected"]
    h1 = s1["mae"] <= H1_RATIO * s0["mae"]
    h2 = boot["p95"] < 0
    h3 = s1["tier_exact_agreement"] >= s0["tier_exact_agreement"] and (
        s0["n_obs_ge8"] == 0 or s1["pod_ge8"] >= s0["pod_ge8"])
    verdict = "helps" if (h1 and h2 and h3) else ("suggestive" if (h1 and h3) else "does_not_help")

    # --- secondary tables --------------------------------------------------------------------
    for by in ("dist_band", "intensity", "model_max_method"):
        grouped(test, preds, by).round(3).to_csv(run_dir / f"test_open_sea_by_{by}.csv", index=False)
    grouped(test, preds, "station_code").round(3).to_csv(run_dir / "test_open_sea_by_station.csv", index=False)
    cont = test["model_peak_cont_ms"]
    secondary_cont = {"mae_cont_peak_raw": float((cont - test["obs_max_ms"]).abs().mean()),
                      "bias_cont_peak_raw": float((cont - test["obs_max_ms"]).mean())}

    other = []
    for grp in ("coastal", "sheltered"):
        g = p[p["group"] == grp]
        tr, te = g[g["split"] == "train"], g[g["split"] == "test"]
        k = ss.fit_factor(tr["model_max_ms"], tr["obs_max_ms"])
        other.append({"level": "group", "key": grp, "k_train": k, "n_train": len(tr), "n_test": len(te),
                      "mae_test_raw": float((te["model_max_ms"] - te["obs_max_ms"]).abs().mean()),
                      "mae_test_k": float((k * te["model_max_ms"] - te["obs_max_ms"]).abs().mean())})
    for code, g in p.groupby("station_code"):
        tr, te = g[g["split"] == "train"], g[g["split"] == "test"]
        k = ss.fit_factor(tr["model_max_ms"], tr["obs_max_ms"])
        other.append({"level": "station", "key": code, "group": ss.STATIONS[code]["group"], "k_train": k,
                      "n_train": len(tr), "n_test": len(te),
                      "mae_test_raw": float((te["model_max_ms"] - te["obs_max_ms"]).abs().mean()),
                      "mae_test_k": float((k * te["model_max_ms"] - te["obs_max_ms"]).abs().mean())})
    pd.DataFrame(other).round(3).to_csv(run_dir / "factors_other_groups.csv", index=False)

    # Yagi rows, descriptive
    yagi = p[(p["NAME"] == "YAGI") & (p["SEASON"] == 2024)].copy()
    yagi["pred_selected"] = apply_variant(yagi, selected, params)
    yagi[["station_code", "group", "min_dist_km", "obs_max_ms", "obs_max_time", "model_max_ms", "model_max_method",
          "pred_selected", "model_peak_cont_ms", "n_pairs"]].round(2).to_csv(run_dir / "yagi_2024.csv", index=False)

    # --- proposals ---------------------------------------------------------------------------
    k_sel = params["C1"]["k"] if selected == "C1" else params["C2"]["k_near"]
    proposal = {"made": False}
    if verdict == "helps":
        new_th = proposed_thresholds(k_sel, spec)
        proposal = {"made": True, "code_constant": {"variant": selected, **params[selected]},
                    "thresholds": new_th, "threshold_changed": new_th != {k: int(v) for k, v in thresholds.items()}}
        if proposal["threshold_changed"]:
            cfg = json.loads(json.dumps(config))
            cfg["config_version"] = "proposal-hzcal-20261104"
            cfg["hazards"]["storm_wind"]["thresholds"] = new_th
            cfg["hazards"]["storm_wind"]["evidence"] = spec["evidence"] + [f"artifacts/experiments/{args.run_name}"]
            cfg["note_vi"] = ("ĐỀ XUẤT, CHƯA KÍCH HOẠT (RL-HZCAL). Ngưỡng gió bão hiệu chỉnh theo SYNOP 4TA cho gió "
                              "tham số từ best track (phát lại / hồi cứu); không áp cho gió dự báo Open-Meteo.")
            (run_dir / "alert_config_proposal.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False),
                                                                encoding="utf-8")

    result = {
        "run": args.run_name, "prereg": str(PREREG.relative_to(REPO)), "prereg_commit": prereg_commit,
        "started_utc": started.isoformat(timespec="seconds"),
        "passages": {"all": int(len(allp)), "eligible": int(len(p)),
                     "eligible_by_group_split": p.groupby(["group", "split"]).size().to_dict()},
        "params_train_open_sea": params, "cv_mae_train": cv, "selected": selected,
        "scores_test_open_sea": scores, "scores_train_open_sea": scores_train,
        "bootstrap_selected_minus_C0": boot, "sign_test": sign, "secondary_cont_peak": secondary_cont,
        "criteria": {"H1": bool(h1), "H2": bool(h2), "H3": bool(h3)}, "verdict": verdict, "proposal": proposal,
    }
    result["passages"]["eligible_by_group_split"] = {f"{a}/{b}": int(n) for (a, b), n in
                                                     result["passages"]["eligible_by_group_split"].items()}
    (run_dir / "result.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    commit_time = pd.Timestamp(prereg_commit.split()[1]).tz_convert("UTC")
    mtimes = {f.name: datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
              for f in sorted(run_dir.iterdir())}
    manifest = {"run": args.run_name, "prereg_commit": prereg_commit,
                "prereg_before_outputs": all(pd.Timestamp(t) > commit_time for t in mtimes.values()),
                "output_mtimes_utc": mtimes, "ibtracs": [f.name for f in track_files],
                "synop": str(ss.SYNOP_PATH.relative_to(paths.DATA_DIR)),
                "git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
                                           text=True).stdout.strip()}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=1, default=str))


if __name__ == "__main__":
    main()
