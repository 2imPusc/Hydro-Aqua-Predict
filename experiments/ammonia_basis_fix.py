"""Quantify the ammonia-basis fix (TAN vs un-ionised NH3) on the frozen NB1 history.

Provincial data (imputers, HSI, QCVN 10 B1 0.1 mg/L) use total ammonium as N (TAN);
the runtime used to feed un-ionised NH3 (Emerson) into every "NH3" consumer.  This
script replays both routings on ``sensor-history-20261024`` (read-only):

* distributions: provincial "NH3" (= TAN) vs sensor TAN before/after the 31/07 step
  vs un-ionised NH3;
* imputed DO / Salinity / PO4 (HP 4-feature imputers, batch over every QC-valid row)
  with the old input (un-ionised NH3 in the model's "NH3" slot) and the new input (TAN);
  daily medians;
* share of rows outside the imputer training range (p1–p99, imputer_feature_bounds.json);
* QCVN ammonium outcome (daily median vs 0.1) and HSI (classify_station on daily
  medians) old vs new.

    python experiments/ammonia_basis_fix.py [--run-name ammonia-basis-fix-20261026]

Writes a NEW run dir under paths.EXPERIMENT_OUTPUT_DIR (exist_ok=False).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import impute, paths  # noqa: E402
from core.chemistry import nh3_fraction  # noqa: E402
from core.classify import classify_station  # noqa: E402
from core.config import NH4_TO_N_FACTOR, NH4_UNIT_SCALE, QCVN10_B1  # noqa: E402
from core.quality import filter_valid_rows  # noqa: E402

STATION = "06M26042804"
REGION = "haiphong"
SPECIES = "cobia"
TAG = "4feat"   # COD sensor dead on most days; HP 5feat uses the same 4 columns anyway
LOCAL_TZ = "Asia/Bangkok"
HISTORY = paths.EXPERIMENT_OUTPUT_DIR / "sensor-history-20261024" / f"{STATION}.csv"
TARGETS = ("DO", "Salinity", "PO4")
QUANTILES = (0.01, 0.10, 0.25, 0.50, 0.75, 0.90, 0.99)


def load_history() -> pd.DataFrame:
    raw = pd.read_csv(HISTORY)
    raw = raw[raw["device"].astype(str).eq(STATION)].copy()
    raw["fetchedAt"] = pd.to_datetime(raw["fetchedAt"], utc=True)
    valid = filter_valid_rows(raw, ["pH", "Temperature", "TSS", "NH4"]).copy()
    valid["fetchedAt"] = pd.to_datetime(valid["fetchedAt"], utc=True)
    valid = valid.sort_values("fetchedAt").reset_index(drop=True)
    local = valid["fetchedAt"].dt.tz_convert(LOCAL_TZ)
    valid["local_date"] = local.dt.date
    valid["month"] = local.dt.month
    valid["TAN"] = valid["NH4"].clip(lower=0) * NH4_UNIT_SCALE * NH4_TO_N_FACTOR
    valid["NH3_unionized"] = valid["TAN"] * nh3_fraction(valid["pH"].to_numpy(), valid["Temperature"].to_numpy())
    return valid


def find_step(frame: pd.DataFrame) -> pd.Timestamp:
    """First reading on 2026-07-31 (local) after which NH4 stays below 30 raw (the 25× drop)."""
    local = frame["fetchedAt"].dt.tz_convert(LOCAL_TZ)
    day = frame[(local >= pd.Timestamp("2026-07-31", tz=LOCAL_TZ)) & (local < pd.Timestamp("2026-08-01", tz=LOCAL_TZ))]
    low = day[day["NH4"] < 30]
    return low["fetchedAt"].iloc[0]


def batch_impute(frame: pd.DataFrame, ammonia: pd.Series) -> pd.DataFrame:
    """Vectorised replica of impute_params for the HP 4feat imputers; ``ammonia`` fills the 'NH3' slot."""
    cv = impute._load_json(impute._CV_R2_FILE, "CV R²")[REGION][TAG]
    features = impute._load_json(impute._FEATCOLS_FILE, "Feature cols")[REGION][TAG]
    base = frame.assign(NH3=ammonia.to_numpy())
    base["month_sin"] = np.sin(2 * np.pi * base["month"] / 12)
    base["month_cos"] = np.cos(2 * np.pi * base["month"] / 12)
    out = pd.DataFrame(index=frame.index)
    for target in TARGETS:
        tier = impute.r2_tier(target, cv.get(target))
        model_path = impute.IMPUTER_DIR / f"{target}_{REGION}_{TAG}.pkl"
        if tier not in ("strong", "weak") or not model_path.exists():
            continue
        cols = list(features)
        season = impute.SEASONALITY_CONFIG.get(REGION, {}).get(target)
        if season == "month":
            cols.append("month")
        elif season == "cyclical":
            cols.extend(["month_sin", "month_cos"])
        pred = joblib.load(model_path).predict(base[cols].to_numpy(dtype=float))
        out[target] = np.round(np.maximum(0.0, pred), 4)
    return out


def ood_flags(frame: pd.DataFrame, ammonia: pd.Series) -> pd.DataFrame:
    bounds = impute._load_bounds()["regions"][REGION]
    values = frame.assign(NH3=ammonia.to_numpy())
    flags = pd.DataFrame(index=frame.index)
    for feature in ("NH3", "pH", "Temperature", "TSS"):
        lo, hi = bounds[feature]["p_lo"], bounds[feature]["p_hi"]
        flags[feature] = (values[feature] < lo) | (values[feature] > hi)
    flags["any"] = flags.any(axis=1)
    return flags


def quantiles(series: pd.Series) -> dict:
    s = pd.to_numeric(series, errors="coerce").dropna()
    return {"n": int(len(s)), **{f"p{int(q * 100):02d}": round(float(s.quantile(q)), 5) for q in QUANTILES}}


def provincial_distribution() -> dict:
    out = {}
    for region in ("haiphong", "quangninh"):
        path = paths.clean_data(region)
        if path.exists():
            out[region] = quantiles(pd.read_csv(path)["NH3"])
    return out


def classify_day(row: pd.Series, ammonia_key_value: float, extra: dict) -> dict:
    measured = {"TAN": ammonia_key_value, "pH": row["pH"], "Temperature": row["Temperature"], "TSS": row["TSS"], **extra}
    result = classify_station(STATION, measured, SPECIES, date=str(row["local_date"]), region=REGION)
    return {"score": result["score"], "label": result["label"], "ood": ",".join(result["imputation_diagnostics"].get("ood_features", []))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-name", default="ammonia-basis-fix-20261026")
    args = ap.parse_args()
    out_dir = paths.EXPERIMENT_OUTPUT_DIR / args.run_name
    out_dir.mkdir(parents=True, exist_ok=False)

    frame = load_history()
    step = find_step(frame)
    frame["period"] = np.where(frame["fetchedAt"] < step, "before_step", "after_step")

    old_imp = batch_impute(frame, frame["NH3_unionized"]).add_suffix("_old")
    new_imp = batch_impute(frame, frame["TAN"]).add_suffix("_new")
    old_ood = ood_flags(frame, frame["NH3_unionized"]).add_prefix("ood_old_")
    new_ood = ood_flags(frame, frame["TAN"]).add_prefix("ood_new_")
    rows = pd.concat([frame, old_imp, new_imp, old_ood, new_ood], axis=1)

    # Consistency: the batch replica equals impute_params on one row.
    probe = rows.iloc[len(rows) // 3]
    ref = impute.impute_params({"TAN": probe["TAN"], "pH": probe["pH"], "Temperature": probe["Temperature"],
                                "TSS": probe["TSS"], "date": str(probe["local_date"])}, region=REGION)
    consistency = {t: [float(probe[f"{t}_new"]), ref["imputed"].get(t)] for t in TARGETS}

    value_cols = ["NH4", "TAN", "NH3_unionized", "pH", "Temperature", "TSS"] + list(old_imp) + list(new_imp)
    daily = rows.groupby("local_date")[value_cols].median()
    daily["n"] = rows.groupby("local_date").size()
    daily["period"] = rows.groupby("local_date")["period"].agg(lambda s: s.mode().iloc[0])
    flag_cols = list(old_ood) + list(new_ood)
    daily = daily.join(rows.groupby("local_date")[flag_cols].mean().add_prefix("share_"))

    limit = QCVN10_B1["TAN"]["max"]
    daily["qcvn_new_TAN_exceed"] = daily["TAN"] > limit
    daily["qcvn_old_NH3_exceed"] = daily["NH3_unionized"] > limit

    hsi = []
    for day, row in daily.reset_index().iterrows():
        new = classify_day(row, row["TAN"], {"NH3": row["NH3_unionized"]})
        old = classify_day(row, row["NH3_unionized"], {})   # old routing: un-ionised value in every "NH3" slot
        hsi.append({"local_date": row["local_date"], "hsi_score_old": old["score"], "hsi_label_old": old["label"],
                    "hsi_score_new": new["score"], "hsi_label_new": new["label"], "hsi_ood_new": new["ood"]})
    daily = daily.reset_index().merge(pd.DataFrame(hsi), on="local_date")
    daily.to_csv(out_dir / "daily.csv", index=False)

    summary: dict = {"run": args.run_name, "station": STATION, "history": str(HISTORY.name), "region_models": f"{REGION}/{TAG}",
                     "step_utc": step.isoformat(), "step_local": step.tz_convert(LOCAL_TZ).isoformat(),
                     "nh4_unit_scale": NH4_UNIT_SCALE, "nh4_to_n_factor": NH4_TO_N_FACTOR,
                     "rows_qc_valid": int(len(rows)), "days": int(len(daily)), "consistency_batch_vs_impute_params": consistency,
                     "imputer_bounds_haiphong": impute._load_bounds()["regions"][REGION],
                     "distributions": {"provincial_NH3_column_is_TAN": provincial_distribution()}, "periods": {}}
    for period, grp in [("all", rows)] + list(rows.groupby("period")):
        days = daily if period == "all" else daily[daily["period"] == period]
        block = {
            "rows": int(len(grp)), "days": int(len(days)),
            "TAN": quantiles(grp["TAN"]), "NH3_unionized": quantiles(grp["NH3_unionized"]),
            "ratio_TAN_over_NH3_median": round(float((grp["TAN"] / grp["NH3_unionized"]).median()), 2),
            "ood_share_rows": {"old": {k: round(float(grp[f"ood_old_{k}"].mean()), 4) for k in ("NH3", "pH", "Temperature", "TSS", "any")},
                               "new": {k: round(float(grp[f"ood_new_{k}"].mean()), 4) for k in ("NH3", "pH", "Temperature", "TSS", "any")}},
            "imputed_daily_median": {t: {"old": round(float(days[f"{t}_old"].median()), 3), "new": round(float(days[f"{t}_new"].median()), 3),
                                         "median_abs_daily_diff": round(float((days[f"{t}_new"] - days[f"{t}_old"]).abs().median()), 3),
                                         "max_abs_daily_diff": round(float((days[f"{t}_new"] - days[f"{t}_old"]).abs().max()), 3)}
                                     for t in TARGETS if f"{t}_old" in days},
            "qcvn_days_exceed": {"old_unionized_vs_0.1": int(days["qcvn_old_NH3_exceed"].sum()), "new_TAN_vs_0.1": int(days["qcvn_new_TAN_exceed"].sum())},
            "qcvn_rows_exceed_share": {"old": round(float((grp["NH3_unionized"] > limit).mean()), 4), "new": round(float((grp["TAN"] > limit).mean()), 4)},
            "hsi": {"score_median_old": round(float(days["hsi_score_old"].median()), 4), "score_median_new": round(float(days["hsi_score_new"].median()), 4),
                    "labels_old": days["hsi_label_old"].value_counts().to_dict(), "labels_new": days["hsi_label_new"].value_counts().to_dict(),
                    "days_label_changed": int((days["hsi_label_old"] != days["hsi_label_new"]).sum())},
        }
        summary["periods"][period] = block
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    print(f"\nwrote {out_dir}")


if __name__ == "__main__":
    main()
