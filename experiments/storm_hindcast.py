"""Storm hindcast at NB1 from IBTrACS best track (oracle exposure, not forecast skill).

    python experiments/storm_hindcast.py --stamp 20261022
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.config import weather_location_for_station  # noqa: E402
from core.greenlab_api import load_cached_history  # noqa: E402
from core.storm_advisory import beaufort, load_ibtracs, storm_passages  # noqa: E402

STATION = "06M26042804"
BANDS = [(6, 7, "cap6_7"), (8, 9, "cap8_9"), (10, 11, "cap10_11"), (12, 17, "cap12_plus")]
PH_TRUSTED_UNTIL = pd.Timestamp("2026-09-18").date()  # pH probe drift from 09-19 (RL-18)
LOCAL_TZ = "Asia/Ho_Chi_Minh"


def _latest(pattern: str) -> Path:
    files = sorted((paths.HAZARD_DATA_DIR).glob(pattern))
    if not files:
        raise FileNotFoundError(f"run experiments/hazard_data.py first: {pattern}")
    return files[-1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_default(value):
    """json.dumps default: pd.NA -> null, numpy scalars -> python scalars."""
    if value is pd.NA:
        return None
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _none_if_na(value):
    return None if pd.isna(value) else value


def load_tracks() -> tuple[pd.DataFrame, list[Path]]:
    wp, last3 = _latest("ibtracs/ibtracs.WP.list.*.csv"), _latest("ibtracs/ibtracs.last3years.list.*.csv")
    old, new = load_ibtracs(wp), load_ibtracs(last3)  # last3years spans all basins; distance filter drops the rest
    merged = pd.concat([old[~old["SID"].isin(new["SID"])], new], ignore_index=True)
    return merged[merged["SEASON"] >= 1980], [wp, last3]


def _flag(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(bool)


def band_counts(passages: pd.DataFrame) -> pd.DataFrame:
    out = passages[["SEASON"]].drop_duplicates().set_index("SEASON")
    for lo, hi, name in BANDS:
        mask = _flag(passages["site_beaufort"].between(lo, hi))
        out[name] = passages[mask].groupby("SEASON").size()
    for lvl in (3, 4, 5):
        mask = _flag(passages["qd18_level"] == lvl)
        out[f"qd18_{lvl}"] = passages[mask].groupby("SEASON").size()
    return out.fillna(0).astype(int).sort_index()


def month_calendar(passages: pd.DataFrame, first: int, last: int) -> pd.DataFrame:
    strong = passages[_flag(passages["site_beaufort"] >= 8)].copy()
    strong["month"] = strong["peak_time"].dt.tz_convert(LOCAL_TZ).dt.month
    per_month = strong.groupby("month").size().reindex(range(1, 13), fill_value=0)
    return (per_month / (last - first + 1)).rename("storms_per_year_site_cap8_plus").to_frame()


def yagi_check(passages: pd.DataFrame, era5: pd.DataFrame) -> dict:
    yagi = passages[(passages["NAME"] == "YAGI") & (passages["SEASON"] == 2024)]
    if yagi.empty:
        return {"status": "unavailable", "reason": "yagi_not_in_tracks"}
    row = yagi.iloc[0]
    start = pd.Timestamp("2024-09-06", tz="UTC")
    window = era5[(era5["time"] >= start) & (era5["time"] < start + pd.Timedelta(days=3))]
    wmax = float(window["wind_speed_10m"].max())
    return {"peak_time": row["peak_time"].isoformat(), "min_dist_km": round(row["min_dist_km"], 1),
            "exposure_method": row["exposure_method"], "site_wind_lower_bound": bool(row["site_wind_lower_bound"]),
            "site_beaufort_093": row["site_beaufort"],
            "site_beaufort_088": row["site_beaufort_088"], "storm_beaufort_max": row["storm_beaufort_max"],
            "qd18_level": row["qd18_level"],
            "era5_max_wind_ms": round(wmax, 2),
            "era5_max_wind_beaufort": beaufort(wmax),
            "era5_max_gust_ms": round(float(window["wind_gusts_10m"].max()), 2),
            "note": "ERA5 under-reads typhoon cores; treat as lower bound."}


def events_check(passages: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    local = passages["peak_time"].dt.tz_convert(LOCAL_TZ).dt.date
    for ev in events[events["hazard"] == "storm"].itertuples():
        lo = (pd.Timestamp(ev.start_date) - pd.Timedelta(days=1)).date()
        hi = (pd.Timestamp(ev.end_date) + pd.Timedelta(days=1)).date()
        hit = passages[(local >= lo) & (local <= hi)].sort_values("site_beaufort", ascending=False, na_position="last")
        best = hit.iloc[0] if not hit.empty else None
        rows.append({"event_id": ev.event_id, "verified": ev.verified, "matched": best is not None,
                     "SID": None if best is None else best["SID"], "NAME": None if best is None else best["NAME"],
                     "site_beaufort": None if best is None else _none_if_na(best["site_beaufort"]),
                     "qd18_level": None if best is None else _none_if_na(best["qd18_level"])})
    return pd.DataFrame(rows, columns=["event_id", "verified", "matched", "SID", "NAME", "site_beaufort", "qd18_level"])


def sensor_response(passages: pd.DataFrame, hist: pd.DataFrame | None = None) -> pd.DataFrame:
    hist = load_cached_history(STATION) if hist is None else hist.copy()
    hist["date"] = hist["fetchedAt"].dt.tz_convert(LOCAL_TZ).dt.date
    daily = hist.groupby("date").agg(rows=("fetchedAt", "size"), Temperature=("Temperature", "mean"),
                                     TSS=("TSS", "mean"), pH=("pH", "mean"))
    daily.loc[[d > PH_TRUSTED_UNTIL for d in daily.index], "pH"] = float("nan")
    rows = []
    for p in passages[(passages["SEASON"] == 2026) & (passages["min_dist_km"] <= 150)].itertuples():
        peak = p.peak_time.tz_convert(LOCAL_TZ).date()
        for offset in range(-3, 4):
            day = peak + pd.Timedelta(days=offset)
            rec = daily.loc[day].to_dict() if day in daily.index else {"rows": 0}
            rows.append({"SID": p.SID, "NAME": p.NAME, "day_offset": offset, "date": day, **rec})
    out = pd.DataFrame(rows)
    out["rows"] = out["rows"].astype("Int64")
    out["partial"] = out["rows"] < 1296
    return out


INTERP_STEP = "30min"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stamp", required=True)
    parser.add_argument("--radius-km", type=float, default=500.0)
    parser.add_argument("--coastal-radius-km", type=float, default=200.0)
    args = parser.parse_args(argv)
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / f"storm-hindcast-{args.stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    loc = weather_location_for_station(STATION)
    lat, lon = loc["latitude"], loc["longitude"]
    tracks, track_files = load_tracks()
    kw = {"coastal_radius_km": args.coastal_radius_km, "interp_step": INTERP_STEP}
    passages = storm_passages(tracks, lat, lon, args.radius_km, factor=0.93, **kw)
    alt = storm_passages(tracks, lat, lon, args.radius_km, factor=0.88, **kw)[["SID", "site_beaufort"]]
    passages = passages.merge(alt.rename(columns={"site_beaufort": "site_beaufort_088"}), on="SID", how="left")
    era5_file = _latest("era5/era5_nb1_*.csv")
    era5 = pd.read_csv(era5_file, parse_dates=["time"])
    events_file = Path(__file__).with_name("hazard_events.csv")
    first, last = int(passages["SEASON"].min()), int(passages["SEASON"].max())
    passages.to_csv(run_dir / "passages.csv", index=False)
    band_counts(passages).to_csv(run_dir / "climatology_year.csv")
    month_calendar(passages, first, last).to_csv(run_dir / "climatology_month.csv")
    (run_dir / "yagi_check.json").write_text(
        json.dumps(yagi_check(passages, era5), indent=2, default=_json_default), encoding="utf-8")
    events_check(passages, pd.read_csv(events_file)).to_csv(run_dir / "events_check.csv", index=False)
    sensor_response(passages).to_csv(run_dir / "sensor_response_2026.csv", index=False)
    inputs = [*track_files, era5_file, events_file]
    manifest = {"run": run_dir.name, "source": "best_track_oracle", "site": {"lat": lat, "lon": lon, "anchor": "NB1"},
                "params": {"radius_km": args.radius_km, "coastal_radius_km": args.coastal_radius_km,
                           "interp_step": INTERP_STEP,
                           "factor": 0.93, "factor_sensitivity": 0.88},
                "seasons": [first, last], "passages": int(len(passages)),
                "exposure_method_counts": passages["exposure_method"].value_counts(dropna=False).to_dict(),
                "storm_wind_source_counts": passages["storm_wind_source"].value_counts(dropna=False).to_dict(),
                "inputs": {p.name: _sha(p) for p in inputs}}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
