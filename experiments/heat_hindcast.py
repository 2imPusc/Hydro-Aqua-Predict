"""Heat-stress hindcast at NB1: SST product bias vs sensor, climatology, trend, weekly calendar.

    python experiments/heat_hindcast.py --stamp 20261022
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import heat_stress as hs  # noqa: E402
from core import paths  # noqa: E402
from core.greenlab_api import load_cached_history  # noqa: E402

STATION = "06M26042804"
MIN_SENSOR_ROWS = 1296  # 90 % of 1,440 minutes (Phase 0 gate)
MIN_YEAR_DAYS = 330  # a climatology year needs this many valid SST days
LOCAL_TZ = "Asia/Ho_Chi_Minh"


def _latest(pattern: str) -> Path:
    files = sorted(paths.HAZARD_DATA_DIR.glob(pattern))
    if not files:
        raise FileNotFoundError(f"run experiments/hazard_data.py first: {pattern}")
    return files[-1]


def _longest_oisst() -> Path:
    """OISST file with the earliest start year in its name (..._<start>_<end>.csv).

    Name-sorting would pick a later-starting (shorter) download such as *_2020_*.
    """
    files = list(paths.HAZARD_DATA_DIR.glob("sst/oisst_*.csv"))
    if not files:
        raise FileNotFoundError("run experiments/hazard_data.py first: sst/oisst_*.csv")

    def key(p: Path):
        m = re.search(r"_(\d{4})_(\d{8})\.csv$", p.name)
        return (int(m.group(1)), -int(m.group(2))) if m else (9999, 0)

    return sorted(files, key=key)[0]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sensor_daily() -> pd.Series:
    hist = load_cached_history(STATION)
    temp = hist.set_index("fetchedAt")["Temperature"]
    temp = temp[(temp >= 10) & (temp <= 40)]
    local = temp.tz_convert(LOCAL_TZ)
    grouped = local.groupby(local.index.date)
    daily = grouped.mean()[grouped.size() >= MIN_SENSOR_ROWS]
    daily.index = pd.to_datetime(daily.index)
    return daily


def compare(sensor: pd.Series, product: pd.Series) -> dict:
    joined = pd.concat([sensor.rename("sensor"), product.rename("product")], axis=1).dropna()
    if len(joined) < 10:
        return {"n_days": int(len(joined)), "status": "insufficient_overlap"}
    diff = joined["sensor"] - joined["product"]
    return {"n_days": int(len(joined)), "first": str(joined.index.min().date()), "last": str(joined.index.max().date()),
            "median_diff_c": round(float(diff.median()), 3), "mae_c": round(float(diff.abs().mean()), 3),
            "pearson_r": round(float(joined["sensor"].corr(joined["product"])), 3)}


def yearly(days: pd.DataFrame, hot_calm: pd.Series) -> pd.DataFrame:
    g = days.groupby(days.index.year)
    out = pd.DataFrame({f"days_alert_ge{k}": g["alert_level"].apply(lambda s, k=k: int((s >= k).sum())) for k in (1, 2, 3)})
    out["max_run_days"] = g["run_days"].max()
    out["max_degree_days_7d"] = g["degree_days_7d"].max()
    out["hot_calm_days"] = hot_calm.groupby(hot_calm.index.year).sum().reindex(out.index).fillna(0).astype(int)
    out["n_days"] = g["temp_c"].count()  # valid SST days (calendar-daily frame holds NaN gaps)
    return out[out["n_days"] >= MIN_YEAR_DAYS]  # drop incomplete years


def trend(year_table: pd.DataFrame, column: str) -> dict:
    slope, intercept, lo, hi = stats.theilslopes(year_table[column].to_numpy(), year_table.index.to_numpy())
    return {"column": column, "days_per_decade": round(slope * 10, 2), "ci95_per_decade": [round(lo * 10, 2), round(hi * 10, 2)],
            "years": [int(year_table.index.min()), int(year_table.index.max())]}


def calendar(days: pd.DataFrame, min_level: int = 2) -> pd.DataFrame:
    iso = days.index.isocalendar()
    hit = (days["alert_level"] >= min_level).groupby([iso["year"].to_numpy(), iso["week"].to_numpy()]).any()
    share = hit.groupby(level=1).mean()
    return share.rename("share_years_with_stress_day").to_frame().rename_axis("iso_week")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stamp", required=True)
    parser.add_argument("--oisst", type=Path, default=None, help="override OISST csv (default: earliest start year)")
    args = parser.parse_args(argv)
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / f"heat-hindcast-{args.stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    oisst_file = args.oisst or _longest_oisst()
    marine_file, era5_file = _latest("sst/openmeteo_marine_nb1_*.csv"), _latest("era5/era5_nb1_*.csv")
    oisst = pd.read_csv(oisst_file, parse_dates=["time"]).set_index("time")["sst"]
    # OISST is a daily value stamped 00:00 (or 12:00) UTC: the day is its UTC calendar date, no local shift.
    oisst.index = oisst.index.tz_convert("UTC").normalize().tz_localize(None)
    marine = pd.read_csv(marine_file, parse_dates=["time"]).set_index("time")["sea_surface_temperature"]
    marine_daily = hs.daily_from_hourly(marine)
    era5 = pd.read_csv(era5_file, parse_dates=["time"]).set_index("time")
    air_max = hs.daily_from_hourly(era5["temperature_2m"], how="max")
    wind_mean = hs.daily_from_hourly(era5["wind_speed_10m"])
    hot_calm = hs.hot_calm_flag(air_max, wind_mean.reindex(air_max.index))

    sensor = sensor_daily()
    bias = {"vs_oisst": compare(sensor, oisst), "vs_openmeteo_marine": compare(sensor, marine_daily)}
    offset = bias["vs_oisst"].get("median_diff_c", 0.0)
    raw, adj = hs.daily_heat_stress(oisst), hs.daily_heat_stress(oisst + offset)
    raw.join(adj, rsuffix="_adjusted").to_csv(run_dir / "daily_oisst.csv", index_label="date")
    years = yearly(raw, hot_calm).join(yearly(adj, hot_calm), rsuffix="_adjusted")
    years.to_csv(run_dir / "climatology_year.csv", index_label="year")
    trends = [trend(years, c) for c in ("days_alert_ge1", "days_alert_ge2", "days_alert_ge1_adjusted", "days_alert_ge2_adjusted")]
    # calendar only over complete years, so a partial current year does not bias late weeks
    complete = adj[adj.index.year.isin(years.index)]
    calendar(complete).to_csv(run_dir / "heat_calendar.csv")
    # OISST (0.25 deg offshore) never reaches 33 C, so the level>=2 calendar is empty; keep a watch-level (>=1) one
    calendar(complete, min_level=1).to_csv(run_dir / "heat_calendar_watch.csv")
    (run_dir / "bias.json").write_text(json.dumps(bias, indent=2), encoding="utf-8")
    (run_dir / "trend.json").write_text(json.dumps(trends, indent=2), encoding="utf-8")
    manifest = {"run": run_dir.name, "source": "reanalysis", "oisst_offset_c": offset,
                "thresholds_c": {"watch": hs.WATCH_C, "stress": hs.STRESS_C, "severe": hs.SEVERE_C,
                                 "min_run_days": hs.MIN_RUN_DAYS, "hot_air": hs.HOT_AIR_C, "calm_wind_ms": hs.CALM_WIND_MS},
                "inputs": {p.name: _sha(p) for p in (oisst_file, marine_file, era5_file)}, "sensor_days": int(len(sensor))}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({**manifest, "bias": bias, "trends": trends}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
