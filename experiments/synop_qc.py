"""Task 1.5: descriptive QC of the 4TA SYNOP archive at the 11 HP/QN (+ Van Ly) stations.

    python experiments/synop_qc.py --run-name synop-qc-hpqn-20261104

Writes a new run dir under ``paths.EXPERIMENT_OUTPUT_DIR`` (refuses to reuse one) and the tracked
summary ``experiments/synop_qc_hpqn.json`` (usable stations / periods + the wind QC rule), which the
storm calibration and the sibling Open-Meteo bias task read.  Never edits ``data/vn_synop``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from experiments import synop_storm as ss  # noqa: E402
from experiments.storm_hindcast import load_tracks  # noqa: E402

TRACKED_SUMMARY = Path(__file__).resolve().parent / "synop_qc_hpqn.json"
MAIN_H = (0, 6, 12, 18)
INTER_H = (3, 9, 15, 21)
BIAS_PERIOD = ("2024-01-01", "2025-12-04 23:59")  # Open-Meteo bias task window (task 2.x sibling)
BIAS_VARS = ["wspd_ms", "t2m_c", "rh_pct", "ps_hpa", "rain6h_mm"]
RAW_SAMPLES = 8


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def switch_month(g: pd.DataFrame) -> str | None:
    """First month from which >= 90 % of the remaining months have >= 80 % of intermediate-hour
    (03/09/15/21 UTC) wind reports, and that month itself does.  None when never."""
    inter = g[g["obs_utc"].dt.hour.isin(INTER_H)]
    m = inter.groupby(inter["obs_utc"].dt.to_period("M"))["wspd_valid"].mean()
    if m.empty:
        return None
    good = (m >= 0.8).to_numpy().astype(float)
    remaining = np.flip(np.cumsum(np.flip(good))) / np.arange(len(good), 0, -1)
    ok = (good == 1) & (remaining >= 0.9)
    return str(m.index[int(np.argmax(ok))]) if ok.any() else None


def eight_per_day_periods(g: pd.DataFrame, min_months: int = 3) -> str:
    """Runs of >= ``min_months`` consecutive months with >= 80 % intermediate-hour wind reports."""
    inter = g[g["obs_utc"].dt.hour.isin(INTER_H)]
    m = inter.groupby(inter["obs_utc"].dt.to_period("M"))["wspd_valid"].mean()
    m = m.reindex(pd.period_range(m.index.min(), m.index.max(), freq="M"), fill_value=0.0) if len(m) else m
    runs, start, prev = [], None, None
    for per, val in m.items():
        if val >= 0.8:
            start = per if start is None else start
            prev = per
        elif start is not None:
            runs.append((start, prev))
            start = None
    if start is not None:
        runs.append((start, prev))
    return "; ".join(f"{a}..{b}" for a, b in runs if (b - a).n + 1 >= min_months)


def raw_lines(rows: pd.DataFrame, archive: Path) -> list[dict]:
    """Original text lines for a few range-flagged reports (files are named by UTC hour)."""
    tar = shutil.which("tar", path=r"C:\Windows\System32") or "tar"
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for _, r in rows.iterrows():
            t = r["obs_utc"]
            member = f"4TA/{t:%Y}/{t:%Y%m}/{t:%Y%m%d}/{t:%Y%m%d%H}.txt"
            subprocess.run([tar, "-xf", str(archive), "-C", tmp, member], capture_output=True)
            f = Path(tmp) / member
            line = None
            if f.exists():
                for ln in f.read_text(encoding="latin-1").splitlines():
                    if ln[27:39].strip() == r["station_code"]:
                        line = ln.rstrip()
            out.append({"station_code": r["station_code"], "obs_local": str(r["obs_local"]),
                        "member": member, "raw_line": line})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-name", required=True)
    args = ap.parse_args()
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / args.run_name
    if run_dir.exists():
        sys.exit(f"{run_dir} exists; pick a new run name")
    run_dir.mkdir(parents=True)

    df = ss.load_synop()
    tracks, track_files = load_tracks()
    tracks = tracks[tracks["SEASON"] >= 1999]
    meta = df.groupby("station_code")[["station_name", "lat", "lon"]].first()

    parts = []
    for code, g in df.groupby("station_code", sort=False):
        lat, lon = float(meta.loc[code, "lat"]), float(meta.loc[code, "lon"])
        near = ss.storm_near(g["obs_utc"], tracks, lat, lon)
        parts.append(ss.flag_wind(g, near).assign(near_storm=near))
    df = pd.concat(parts, ignore_index=True)
    df["year"] = df["obs_local"].dt.year

    # --- coverage --------------------------------------------------------------------------
    cov_year = df.groupby(["station_code", "year"])["wspd_valid"].mean().unstack().round(3)
    cov_year.to_csv(run_dir / "coverage_wind_by_year.csv")
    hours = (df[df["wspd_valid"]].groupby(["station_code", "year", df["obs_utc"].dt.hour]).size()
             .unstack(fill_value=0))
    hours.columns = [f"h{c:02d}utc" for c in hours.columns]
    hours.to_csv(run_dir / "wind_reports_by_year_utc_hour.csv")

    # --- flagged rows ------------------------------------------------------------------------
    fl = df[df["wspd_range_bad"] | df["wspd_spike"]].copy()
    fl["flag"] = np.where(fl["wspd_range_bad"], "range_gt60", "spike")
    srt = df.sort_values(["station_code", "obs_utc"])
    prev = srt.groupby("station_code")["wspd_ms"].shift(1)
    nxt = srt.groupby("station_code")["wspd_ms"].shift(-1)
    fl["prev_wspd"] = prev.reindex(fl.index)
    fl["next_wspd"] = nxt.reindex(fl.index)
    fl[["station_code", "station_name", "obs_local", "obs_utc", "wdir", "wspd_ms", "prev_wspd", "next_wspd",
        "near_storm", "flag"]].sort_values(["station_code", "obs_utc"]).to_csv(run_dir / "flagged_wind.csv", index=False)

    # decode check for 61-98: direction mix vs all reports, digits vs neighbours
    bad = fl[fl["flag"] == "range_gt60"]
    nb = bad[["prev_wspd", "next_wspd"]].mean(axis=1)
    decode = {
        "n": int(len(bad)),
        "wdir_share_flagged": bad["wdir"].fillna("calm/none").value_counts(normalize=True).round(3).to_dict(),
        "wdir_share_all": df.loc[df["wspd_valid"], "wdir"].fillna("calm/none").value_counts(normalize=True)
        .round(3).to_dict(),
        "neighbour_mean_median_ms": float(nb.median()),
        "corr_tens_digit_vs_neighbour": float(np.corrcoef((bad["wspd_ms"] // 10)[nb.notna()], nb.dropna())[0, 1]),
        "corr_units_digit_vs_neighbour": float(np.corrcoef((bad["wspd_ms"] % 10)[nb.notna()], nb.dropna())[0, 1]),
        "near_storm": int(bad["near_storm"].sum()),
        "archive_note": "4TA text files already hold decoded values (direction name + ff in m/s); the original "
                        "dddff group is not in the archive, so 61-98 cannot be re-decoded from it",
        "wdir_missing_when_wspd_le2": bool(df.loc[df["wspd_valid"] & (df["wspd_ms"] <= 2), "wdir"].isna().all()),
    }
    archive = paths.VN_SYNOP_DIR / "raw" / "4TA.rar"
    sample = pd.concat([bad.sample(min(RAW_SAMPLES // 2, len(bad)), random_state=0),
                        fl[fl["flag"] == "spike"].nlargest(RAW_SAMPLES // 2, "wspd_ms")])
    decode["raw_lines"] = raw_lines(sample, archive) if archive.exists() else []

    # --- storm passages (obs side only; the model is not evaluated here) ----------------------
    storm_rows = []
    for code in ss.HPQN_CODES:
        lat, lon = float(meta.loc[code, "lat"]), float(meta.loc[code, "lon"])
        g = df[df["station_code"] == code]
        valid = g[g["wspd_valid"]]
        tr = tracks.assign(dist=ss.haversine_km(tracks["LAT"].to_numpy(), tracks["LON"].to_numpy(), lat, lon))
        near = tr[(tr["dist"] <= 300.0) & (tr["ISO_TIME"] >= pd.Timestamp("2000-01-01", tz="UTC"))
                  & (tr["ISO_TIME"] <= pd.Timestamp("2025-12-05", tz="UTC"))]
        vt = valid["obs_utc"].dt.tz_localize("UTC")
        for sid, s in near.groupby("SID"):
            c = s.loc[s["dist"].idxmin()]
            w = valid[(vt >= s["ISO_TIME"].min() - pd.Timedelta(hours=3)).to_numpy()
                      & (vt <= s["ISO_TIME"].max() + pd.Timedelta(hours=3)).to_numpy()]
            close = valid[(abs(vt - c["ISO_TIME"]) <= pd.Timedelta(hours=3)).to_numpy()]
            storm_rows.append({"station_code": code, "SID": sid, "SEASON": int(c["SEASON"]), "NAME": c["NAME"],
                               "min_dist_km_track_rows": round(float(c["dist"]), 1),
                               "closest_time": c["ISO_TIME"], "obs_within_3h_of_closest": bool(len(close)),
                               "obs_n_in_window": int(len(w)),
                               "obs_max_ms_in_window": float(w["wspd_ms"].max()) if len(w) else np.nan})
    storms = pd.DataFrame(storm_rows)
    storms.to_csv(run_dir / "storm_passages_obs_only.csv", index=False)

    # --- per-station table -------------------------------------------------------------------
    table = []
    for code in ss.HPQN_CODES:
        g = df[df["station_code"] == code]
        v = g.loc[g["wspd_valid"], "wspd_ms"]
        st = storms[storms["station_code"] == code]
        main_cov = g[g["obs_utc"].dt.hour.isin(MAIN_H)]["wspd_valid"].mean()
        inter_cov = g[g["obs_utc"].dt.hour.isin(INTER_H)]["wspd_valid"].mean()
        top = st.nlargest(3, "obs_max_ms_in_window")
        table.append({
            "station_code": code, "name": ss.STATIONS[code]["name"], "group": ss.STATIONS[code]["group"],
            "lat": float(meta.loc[code, "lat"]), "lon": float(meta.loc[code, "lon"]),
            "first_valid_wind": str(g.loc[g["wspd_valid"], "obs_local"].min()),
            "last_valid_wind": str(g.loc[g["wspd_valid"], "obs_local"].max()),
            "wind_valid_frac_all_slots": round(float(g["wspd_valid"].mean()), 3),
            "wind_valid_frac_main_hours": round(float(main_cov), 3),
            "wind_valid_frac_intermediate_hours": round(float(inter_cov), 3),
            "eight_per_day_from_month": switch_month(g),
            "eight_per_day_periods": eight_per_day_periods(g),
            "wspd_mean": round(float(v.mean()), 2), "wspd_p50": float(v.quantile(.5)),
            "wspd_p90": float(v.quantile(.9)), "wspd_p99": float(v.quantile(.99)),
            "wspd_p999": float(v.quantile(.999)), "wspd_max_valid": float(v.max()),
            "calm_frac": round(float((v == 0).mean()), 3),
            "n_range_gt60": int(g["wspd_range_bad"].sum()), "n_spike": int(g["wspd_spike"].sum()),
            "storms_le300km": int(len(st)), "storms_obs_at_closest": int(st["obs_within_3h_of_closest"].sum()),
            "storms_le100km": int((st["min_dist_km_track_rows"] <= 100).sum()),
            "top_storm_obs": "; ".join(f"{r.NAME} {r.SEASON} {r.obs_max_ms_in_window:.0f}" for r in top.itertuples()),
            "note_vi": ss.STATIONS[code]["note_vi"],
        })
    table = pd.DataFrame(table)
    table.to_csv(run_dir / "station_table.csv", index=False)

    # --- usable lists -----------------------------------------------------------------------
    bp = df[(df["obs_local"] >= BIAS_PERIOD[0]) & (df["obs_local"] <= BIAS_PERIOD[1])]
    bias = {}
    for code, g in bp.groupby("station_code"):
        fr = {"wspd_ms": round(float(g["wspd_valid"].mean()), 3)}
        for col in BIAS_VARS[1:]:
            ok = g[col].notna() & ~g["qc_flags"].str.contains(col.split("_")[0], regex=False)
            fr[col] = round(float(ok.mean()), 3)
        bias[code] = {"name": ss.STATIONS[code]["name"], "group": ss.STATIONS[code]["group"],
                      "valid_frac_of_8_slots": fr, "usable": bool(fr["wspd_ms"] >= 0.8 and fr["t2m_c"] >= 0.8)}
    usable = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run": args.run_name, "script": "experiments/synop_qc.py",
        "source": str(ss.SYNOP_PATH.relative_to(paths.DATA_DIR)), "source_sha256": _sha(ss.SYNOP_PATH),
        "wind_qc_rule": {
            "range": f"wspd_ms > {ss.WIND_MAX_VALID_MS} -> invalid (decisions #30)",
            "spike": (f"wspd_ms >= {ss.SPIKE_MIN_MS} and max(valid neighbours of the same station within "
                      f"+-{ss.SPIKE_NEIGHBOR_H} h) < {ss.SPIKE_RATIO} * value (no neighbour = 0), unless an IBTrACS "
                      f"centre is within {ss.STORM_EXEMPT_KM} km within +-{ss.STORM_EXEMPT_H} h -> invalid"),
            "code": "experiments/synop_storm.py: flag_wind, storm_near",
        },
        "licence_vi": "Nguồn và giấy phép chưa xác nhận: chỉ dùng trong hệ thống, không đưa số SYNOP vào bài báo.",
        "storm_calibration": {
            "open_sea": [c for c in ss.HPQN_CODES if ss.STATIONS[c]["group"] == "open_sea"],
            "coastal": [c for c in ss.HPQN_CODES if ss.STATIONS[c]["group"] == "coastal"],
            "sheltered": [c for c in ss.HPQN_CODES if ss.STATIONS[c]["group"] == "sheltered"],
            "note": "all periods usable for storm pairing because the model is evaluated at the obs times; "
                    "4-per-day periods sample the peak more coarsely",
        },
        "open_meteo_bias_2024_2025": bias,
        "eight_per_day_from_month": {r.station_code: r.eight_per_day_from_month for r in table.itertuples()},
        "eight_per_day_periods": {r.station_code: r.eight_per_day_periods for r in table.itertuples()},
        "notes": ["rain6h_mm is reported only at 00/06/12/18 UTC, so its share of 8 slots is ~0.5 by design",
                  "wdir is empty whenever wspd_ms <= 2 (calm / light wind); not a gap"],
        "flag_counts": {"range_gt60": int(df["wspd_range_bad"].sum()), "spike": int(df["wspd_spike"].sum())},
    }
    (run_dir / "usable_stations.json").write_text(json.dumps(usable, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "decode_check.json").write_text(json.dumps(decode, indent=2, ensure_ascii=False, default=str),
                                               encoding="utf-8")
    TRACKED_SUMMARY.write_text(json.dumps(usable, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = {"run": args.run_name, "created_utc": usable["created_utc"],
                "inputs": {"synop": usable["source"], "synop_sha256": usable["source_sha256"],
                           "ibtracs": [p.name for p in track_files]},
                "files": sorted(p.name for p in run_dir.iterdir())}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    pd.set_option("display.width", 250)
    print(table.drop(columns=["note_vi", "lat", "lon"]).to_string(index=False))
    print(json.dumps({k: v for k, v in decode.items() if k != "raw_lines"}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
