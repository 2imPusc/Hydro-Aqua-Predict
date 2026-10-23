"""Storm damage to cage aquaculture vs site wind from IBTrACS (evidence register + empirical table).

    python experiments/storm_damage.py register --draft <draft.csv> --pages <dir> --out experiments/storm_damage_evidence.csv
    python experiments/storm_damage.py analyze --stamp 20261023

``register`` copies each page text to ``paths.DATA_DIR / "references" / "storm_damage"`` (write-once),
records its sha256 and looks up an existing Wayback snapshot (availability API, GET only; no save
requests).  ``analyze`` matches each evidence row to its IBTrACS passage at the row's lat/lon and
writes a damage-vs-Beaufort table, onset thresholds and (only when the data allow) a logistic
fragility curve.  Site wind is best-track oracle exposure (``wind_radii`` rows are lower bounds).
Nothing here changes ``core/storm_advisory.py`` tiers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.storm_advisory import storm_passages  # noqa: E402

REF_DIR = paths.DATA_DIR / "references" / "storm_damage"
EVIDENCE_CSV = paths.PROJECT_ROOT / "experiments" / "storm_damage_evidence.csv"
WAYBACK_API = "https://archive.org/wayback/available"
DAMAGE_CLASSES = ("none", "minor", "major", "catastrophic")
ASSET_GROUPS = {"fish_cage_wood": "wood_or_mixed", "mollusc_raft": "wood_or_mixed", "mixed": "wood_or_mixed",
                "fish_cage_hdpe": "hdpe", "unknown": "unknown"}
EVIDENCE_COLUMNS = [
    "event_id", "storm", "year", "date", "country", "province_or_area", "lat", "lon", "location_precision",
    "asset_type", "damage_class", "evidence_strength", "analysis_use", "damage_metric", "damage_value",
    "damage_text_vi", "reported_wind_text", "cause", "source_title", "publisher", "published_date", "url",
    "accessed_date", "quote", "archive_url", "verified", "local_copy_file", "local_copy_sha256",
]


# ---------------------------------------------------------------- pure helpers

def archive_url_from_available(payload: dict) -> str:
    """URL of the closest snapshot in a Wayback availability response, or '' if none usable."""
    closest = ((payload or {}).get("archived_snapshots") or {}).get("closest") or {}
    if not closest.get("available") or str(closest.get("status")) != "200" or not closest.get("url"):
        return ""
    return re.sub(r"^http://", "https://", closest["url"])


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_once_copy(src: Path, dst: Path) -> str:
    """Copy ``src`` to ``dst`` unless ``dst`` exists; an existing different file is never overwritten."""
    data = Path(src).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    dst = Path(dst)
    if dst.exists():
        if sha256_file(dst) != digest:
            raise FileExistsError(f"write-once copy differs from source: {dst}")
        return digest
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "xb") as fh:  # "x": fail rather than truncate if it appeared meanwhile
        fh.write(data)
    return digest


def norm_name(name) -> str:
    return re.sub(r"[^A-Z]", "", str(name).upper())


def match_passage(passages: pd.DataFrame, storm: str, year: int) -> pd.Series | None:
    """IBTrACS passage whose NAME matches ``storm`` (case/punctuation-insensitive) in ``year``."""
    if passages is None or passages.empty:
        return None
    hit = passages[(passages["NAME"].map(norm_name) == norm_name(storm)) & (passages["SEASON"] == int(year))]
    if hit.empty:
        return None
    return hit.sort_values("site_wind_ms", ascending=False, na_position="last").iloc[0]


def is_major(damage_class: str) -> bool:
    if damage_class not in DAMAGE_CLASSES:
        raise ValueError(f"unknown damage class: {damage_class}")
    return damage_class in ("major", "catastrophic")


def beaufort_band(level) -> str:
    if level is None or pd.isna(level):
        return "unknown"
    level = int(level)
    if level <= 5:
        return "<=5"
    if level >= 12:
        return ">=12"
    lo = level if level % 2 == 0 else level - 1
    return f"{lo}-{lo + 1}"


BANDS = ["<=5", "6-7", "8-9", "10-11", ">=12", "unknown"]


def separation_check(x, y) -> dict:
    """Do the positive (y=1) Beaufort levels lie strictly above every negative one?"""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=int)
    pos, neg = x[y == 1], x[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return {"separated": None, "max_negative": None, "min_positive": None, "threshold_midpoint": None,
                "overlap": []}
    max_neg, min_pos = float(neg.max()), float(pos.min())
    separated = bool(min_pos > max_neg)
    overlap = sorted({int(v) for v in x if min_pos <= v <= max_neg}) if not separated else []
    return {"separated": separated, "max_negative": max_neg, "min_positive": min_pos,
            "threshold_midpoint": (max_neg + min_pos) / 2 if separated else None, "overlap": overlap}


def fit_fragility(x, y, min_n: int = 10) -> dict:
    """Unpenalised logistic P(y=1 | Beaufort); refuses on small n, one class or perfect separation."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=int)
    base = {"n": int(len(x)), "n_positive": int(y.sum()), "n_negative": int((y == 0).sum())}
    if len(x) < min_n:
        return {**base, "fitted": False, "reason": "too_few_events"}
    if len(set(y.tolist())) < 2:
        return {**base, "fitted": False, "reason": "single_class"}
    sep = separation_check(x, y)
    if sep["separated"]:
        return {**base, "fitted": False, "reason": "perfect_separation", **sep}
    from sklearn.linear_model import LogisticRegression
    model = LogisticRegression(C=np.inf, max_iter=10_000).fit(x.reshape(-1, 1), y)
    slope, intercept = float(model.coef_[0][0]), float(model.intercept_[0])
    return {**base, "fitted": True, "reason": None, "slope": slope, "intercept": intercept,
            "beaufort_p50": -intercept / slope if slope else None, **sep}


def bootstrap_p50(x, y, n_boot: int = 1000, seed: int = 20261023, ci: float = 0.9) -> dict:
    """Case-resampling bootstrap of the Beaufort level at P=0.5; resamples that cannot be fitted
    (one class, separation, slope <= 0) are dropped and counted."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=int)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(x), len(x))
        res = fit_fragility(x[idx], y[idx], min_n=1)
        if res["fitted"] and res["slope"] > 0:
            vals.append(res["beaufort_p50"])
    if not vals:
        return {"n_boot": n_boot, "n_ok": 0, "p50_lo": None, "p50_median": None, "p50_hi": None}
    lo, med, hi = np.quantile(vals, [(1 - ci) / 2, 0.5, 1 - (1 - ci) / 2])
    return {"n_boot": n_boot, "n_ok": len(vals), "ci": ci, "p50_lo": float(lo), "p50_median": float(med),
            "p50_hi": float(hi)}


def onset_table(df: pd.DataFrame) -> pd.DataFrame:
    """Per asset group: lowest site Beaufort with any / major damage, highest with none."""
    rows = []
    for group, g in df.groupby("asset_group", sort=True):
        bf = pd.to_numeric(g["site_beaufort"], errors="coerce")
        dmg, maj, none = g["damage_class"] != "none", g["damage_class"].map(is_major), g["damage_class"] == "none"
        rows.append({"asset_group": group, "n": int(len(g)), "n_none": int(none.sum()),
                     "n_minor": int((g["damage_class"] == "minor").sum()), "n_major_plus": int(maj.sum()),
                     "min_bf_any_damage": bf[dmg].min(), "min_bf_major": bf[maj].min(),
                     "max_bf_no_damage": bf[none].max()})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- I/O

def wayback_lookup(url: str, timeout: float = 30.0) -> str:
    import requests
    try:
        resp = requests.get(WAYBACK_API, params={"url": url}, timeout=timeout)
        resp.raise_for_status()
        return archive_url_from_available(resp.json())
    except Exception:  # network / JSON errors: leave the column empty
        return ""


def register(draft: Path, pages: Path, out: Path, accessed: str, wayback: bool = True) -> pd.DataFrame:
    df = pd.read_csv(draft, dtype=str, keep_default_na=False)
    for col in ("local_copy_file", "local_copy_sha256", "archive_url", "accessed_date"):
        if col not in df.columns:
            df[col] = ""
    for i, row in df.iterrows():
        dst = REF_DIR / f"{row['event_id']}__{row['slug']}.txt"
        df.at[i, "local_copy_sha256"] = write_once_copy(pages / row["page_file"], dst)
        df.at[i, "local_copy_file"] = dst.name
        df.at[i, "accessed_date"] = row["accessed_date"] or accessed
        if wayback and not row["archive_url"]:
            df.at[i, "archive_url"] = wayback_lookup(row["url"])
    cols = [c for c in EVIDENCE_COLUMNS if c in df.columns] + \
           [c for c in df.columns if c not in EVIDENCE_COLUMNS and c not in ("slug", "page_file")]
    df[cols].to_csv(out, index=False, encoding="utf-8")
    return df[cols]


def _site_passage(tracks: pd.DataFrame, storm: str, year: int, lat: float, lon: float, factor: float):
    sub = tracks[(tracks["NAME"].map(norm_name) == norm_name(storm)) & (tracks["SEASON"] == int(year))]
    if sub.empty:
        return None
    return match_passage(storm_passages(sub, lat, lon, radius_km=1500.0, factor=factor), storm, year)


def exposure_table(evidence: pd.DataFrame, tracks: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, ev in evidence.iterrows():
        out = {k: ev[k] for k in ("event_id", "storm", "year", "province_or_area", "location_precision", "asset_type",
                                  "damage_class", "evidence_strength", "analysis_use", "verified")}
        lat, lon = pd.to_numeric(ev["lat"], errors="coerce"), pd.to_numeric(ev["lon"], errors="coerce")
        p = None if pd.isna(lat) or pd.isna(lon) or not ev["storm"] else \
            _site_passage(tracks, ev["storm"], int(ev["year"]), float(lat), float(lon), 0.93)
        p88 = None if p is None else _site_passage(tracks, ev["storm"], int(ev["year"]), float(lat), float(lon), 0.88)
        out.update({"ibtracs_sid": None if p is None else p["SID"],
                    "min_dist_km": None if p is None else round(float(p["min_dist_km"]), 1),
                    "site_wind_ms": None if p is None or pd.isna(p["site_wind_ms"]) else round(float(p["site_wind_ms"]), 2),
                    "site_beaufort": None if p is None else p["site_beaufort"],
                    "site_beaufort_k088": None if p88 is None else p88["site_beaufort"],
                    "exposure_method": None if p is None else p["exposure_method"],
                    "site_wind_lower_bound": None if p is None else bool(p["site_wind_lower_bound"]),
                    "storm_beaufort_max_200km": None if p is None else p["storm_beaufort_max"],
                    "peak_time": None if p is None else p["peak_time"]})
        rows.append(out)
    exp = pd.DataFrame(rows)
    for col in ("site_beaufort", "site_beaufort_k088", "storm_beaufort_max_200km"):
        exp[col] = pd.to_numeric(exp[col], errors="coerce").astype("Int64")
    exp["asset_group"] = exp["asset_type"].map(ASSET_GROUPS).fillna("unknown")
    exp["beaufort_band"] = exp["site_beaufort"].map(beaufort_band)
    exp["source"] = "best_track_oracle"
    return exp


def damage_crosstab(exp: pd.DataFrame) -> pd.DataFrame:
    tab = pd.crosstab(exp["damage_class"], exp["beaufort_band"])
    return tab.reindex(index=list(DAMAGE_CLASSES), columns=BANDS, fill_value=0)


def _json_default(value):
    if value is pd.NA or (isinstance(value, float) and np.isnan(value)):
        return None
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def analyze(stamp: str) -> Path:
    from experiments.storm_hindcast import load_tracks
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / f"storm-damage-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    evidence = pd.read_csv(EVIDENCE_CSV, dtype=str, keep_default_na=False)
    tracks, track_files = load_tracks()
    exp = exposure_table(evidence, tracks)
    exp.to_csv(run_dir / "exposure.csv", index=False)

    use = exp[(exp["analysis_use"] == "primary") & exp["site_beaufort"].notna()].copy()
    damage_crosstab(use).to_csv(run_dir / "damage_vs_beaufort.csv")
    onset_table(use).to_csv(run_dir / "onset_thresholds.csv", index=False)
    onset_direct = onset_table(use[use["evidence_strength"] == "direct"])
    onset_direct.to_csv(run_dir / "onset_thresholds_direct_only.csv", index=False)

    frag = {}
    wood = use[use["asset_group"] == "wood_or_mixed"]
    for name, subset, target in [
        ("all_primary", use, "major"),
        ("wood_or_mixed", wood, "major"),
        ("direct_evidence_only", use[use["evidence_strength"] == "direct"], "major"),
        ("wood_or_mixed_any_damage", wood, "any"),
    ]:
        y = (subset["damage_class"].map(is_major) if target == "major"
             else subset["damage_class"] != "none").astype(int).to_numpy()
        xs = subset["site_beaufort"].astype(float).to_numpy()
        frag[name] = fit_fragility(xs, y)
        if frag[name]["fitted"]:
            frag[name]["bootstrap"] = bootstrap_p50(xs, y)
        frag[name]["target"] = "P(major or catastrophic)" if target == "major" else "P(any damage)"
    (run_dir / "fragility.json").write_text(json.dumps(frag, indent=2, default=_json_default), encoding="utf-8")

    manifest = {
        "run": run_dir.name, "source": "best_track_oracle",
        "evidence_csv": str(EVIDENCE_CSV.relative_to(paths.PROJECT_ROOT)).replace("\\", "/"),
        "evidence_sha256": sha256_file(EVIDENCE_CSV),
        "ibtracs": {p.name: sha256_file(p) for p in track_files},
        "n_evidence_rows": int(len(evidence)), "n_matched": int(exp["ibtracs_sid"].notna().sum()),
        "n_primary_with_exposure": int(len(use)),
        "exposure_methods": exp["exposure_method"].value_counts(dropna=False).to_dict(),
        "factor": 0.93, "sensitivity_factor": 0.88,
        "notes": "site_beaufort from storm_passages at the row lat/lon (radius 1500 km, track filtered to the "
                 "named storm); wind_radii rows are lower bounds; damage_class assigned by hand from the "
                 "quoted source (rules in docs/eval/2026-10-23-storm-damage.md).",
        "fragility": {k: {kk: v[kk] for kk in ("fitted", "reason", "n", "n_positive", "n_negative")}
                      for k, v in frag.items()},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=_json_default), encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=_json_default))
    return run_dir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    reg = sub.add_parser("register")
    reg.add_argument("--draft", type=Path, required=True)
    reg.add_argument("--pages", type=Path, required=True)
    reg.add_argument("--out", type=Path, default=EVIDENCE_CSV)
    reg.add_argument("--accessed", default=pd.Timestamp.now(tz="Asia/Ho_Chi_Minh").strftime("%Y-%m-%d"))
    reg.add_argument("--no-wayback", action="store_true")
    ana = sub.add_parser("analyze")
    ana.add_argument("--stamp", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "register":
        df = register(args.draft, args.pages, args.out, args.accessed, wayback=not args.no_wayback)
        print(f"{len(df)} rows -> {args.out}; copies in {REF_DIR}")
    else:
        analyze(args.stamp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
