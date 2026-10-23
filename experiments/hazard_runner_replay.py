"""Replay core.hazard_runner on historical inputs (theory only, shadow).

REANALYSIS AS "FORECAST": ERA5 winds (``models=era5``) and OISST / Open-Meteo marine SST are
what actually happened, fed to the runner as if they were a forecast issued at 00:00 UTC each day.
Lead-0 tiers therefore show the runner's *logic* on known weather, not forecast skill (decisions #18).

    python experiments/hazard_runner_replay.py --run-name hazard-replay-20261023

Windows: Yagi 2024-09-04..09 (ERA5 site winds, 14 stations with exposure profile) and the summer-2026
hot spell (marine SST + OISST at the single NB1 cell; all stations share it).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import hazard_runner as hr  # noqa: E402
from core import paths  # noqa: E402
from core.hazard_runner import LOCAL_TZ  # noqa: E402

LABEL = "reanalysis_as_forecast"
YAGI_DAYS = pd.date_range("2024-09-04", "2024-09-09", freq="D", tz="UTC")
HEAT_DAYS = pd.date_range("2026-07-01", "2026-09-15", freq="D", tz="UTC")


def _config() -> dict:
    return hr.load_effective(None, None)


def _latest(pattern: str, root: Path) -> Path:
    files = sorted(root.glob(pattern))
    if not files:
        raise FileNotFoundError(f"{root}/{pattern}")
    return files[-1]


def yagi_wind() -> pd.DataFrame:
    return pd.read_csv(_latest("openmeteo_era5_sites_wind_2024-09-04_2024-09-09_*.csv", paths.HAZARD_DATA_DIR / "era5"))


def _wind_payload(sub: pd.DataFrame) -> dict:
    return {"status": "ready", "timezone": "UTC", "model": "era5", "retrieved_at": None, "label": LABEL,
            "hourly": {"time": sub["time"].tolist(), "wind_speed_10m": sub["wind_speed_10m"].tolist(),
                       "wind_direction_10m": sub["wind_direction_10m"].tolist()},
            "hourly_units": {"wind_speed_10m": "m/s"}}


def sst_marine_hourly() -> pd.Series:
    f = _latest("openmeteo_marine_nb1_*.csv", paths.HAZARD_DATA_DIR / "sst")
    s = pd.read_csv(f, parse_dates=["time"]).set_index("time")["sea_surface_temperature"]
    s.index = s.index.tz_convert("UTC")
    return s


def sst_oisst_hourly() -> pd.Series:
    """Daily OISST repeated over the 24 local hours of each local date (so daily_from_hourly accepts it)."""
    f = max(paths.HAZARD_DATA_DIR.glob("sst/oisst_*.csv"), key=lambda p: (-int(p.stem.split("_")[3]), p.stem))
    d = pd.read_csv(f, parse_dates=["time"]).set_index("time")["sst"]
    d.index = d.index.tz_convert("UTC").normalize().tz_localize(None)
    d = d["2026-06-01":]
    idx = [pd.Timestamp(day).tz_localize(LOCAL_TZ) + pd.Timedelta(hours=h) for day in d.index for h in range(24)]
    return pd.Series(d.repeat(24).to_numpy(), index=pd.DatetimeIndex(idx).tz_convert("UTC"))


def _marine_payload(sst: pd.Series, start: pd.Timestamp, hours: int = 24 * 6, source: str = "") -> dict:
    sel = sst[(sst.index >= start) & (sst.index < start + pd.Timedelta(hours=hours))]
    return {"status": "ready", "timezone": "UTC", "model": source, "retrieved_at": None, "label": LABEL,
            "hourly": {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in sel.index], "sea_surface_temperature": sel.tolist()}}


def replay_yagi(stations: list[dict], cfg: dict) -> list[dict]:
    wind = yagi_wind()
    recs = []
    for st in stations:
        sub = wind[wind["site_id"] == st["id"]]
        if sub.empty:
            continue
        payload = _wind_payload(sub)
        for day in YAGI_DAYS:
            now = day  # 00:00 UTC issue; ERA5 hours before are not in the payload
            w = {**payload, "hourly": {**payload["hourly"]}}
            recs += [{**r, "replay": {"label": LABEL, "scenario": "yagi_2024"}}
                     for r in hr.evaluate_station(st, w, None, now=now, config=cfg, max_age_hours=1e9)
                     if r["hazard"] in ("storm_wind", "wave_height")]
    return recs


def replay_heat(station: dict, cfg: dict) -> list[dict]:
    recs = []
    for name, sst in (("openmeteo_marine", sst_marine_hourly()), ("oisst", sst_oisst_hourly())):
        for day in HEAT_DAYS:
            start = day - pd.Timedelta(hours=7)  # local midnight of the issue date
            m = _marine_payload(sst, start, source=name)
            if not m["hourly"]["time"]:
                continue
            recs += [{**r, "replay": {"label": LABEL, "scenario": "summer_2026", "sst_source": name}}
                     for r in hr.evaluate_station(station, None, m, now=day, config=cfg, max_age_hours=1e9)
                     if r["hazard"] in ("heat", "cold", "disease_env")]
    return recs


def summarise(yagi: list[dict], heat: list[dict]) -> dict:
    y = pd.DataFrame([{"station": r["station"], "exposure_class": r["exposure_class"], "hazard": r["hazard"],
                       "issue": r["issued_at"][:10], "lead": r["lead_hours"], "tier": r["tier"], "value": r["value"],
                       "valid_from": r["valid_from"]} for r in yagi])
    y0 = y[(y["lead"] == 0) & y["tier"].notna()]
    # tier per station per calendar day = lead-0 window of that day's 00:00 issue
    yagi_day = y0.pivot_table(index="station", columns="issue", values="tier", aggfunc="max")
    wind_day = y0[y0.hazard == "storm_wind"].pivot_table(index="station", columns="issue", values="tier", aggfunc="max")
    wave_day = y0[y0.hazard == "wave_height"].pivot_table(index="station", columns="issue", values="tier", aggfunc="max")
    ymax = y[y["tier"].notna()].groupby(["station", "hazard"])["tier"].max().unstack()
    ymax["exposure_class"] = y.groupby("station")["exposure_class"].first()
    h = pd.DataFrame([{"sst_source": r["replay"]["sst_source"], "hazard": r["hazard"], "issue": r["issued_at"][:10],
                       "lead": r["lead_hours"], "tier": r["tier"], "value": r["value"]} for r in heat])
    h0 = h[(h["lead"] == 0) & h["tier"].notna()]
    heat_days = h0.groupby(["sst_source", "hazard", "tier"]).size().unstack(fill_value=0)
    return {"yagi_max_tier": ymax, "yagi_day_tier_max_of_hazards": yagi_day, "yagi_storm_wind_day": wind_day,
            "yagi_wave_day": wave_day, "heat_tier_days": heat_days, "heat_daily": h0}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run-name", default="hazard-replay-20261023")
    args = ap.parse_args(argv)
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / args.run_name
    run_dir.mkdir(parents=True, exist_ok=False)  # write-once: a failed run gets a new name
    cfg = _config()
    stations = [s for s in hr.load_stations() if s["profile"] is not None]
    yagi = replay_yagi(stations, cfg)
    nb1 = next(s for s in stations if s["id"] == "NB1")
    heat = replay_heat(nb1, cfg)
    with (run_dir / "records.jsonl").open("x", encoding="utf-8", newline="\n") as fh:
        for r in yagi + heat:
            fh.write(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n")
    s = summarise(yagi, heat)
    for k, df in s.items():
        df.to_csv(run_dir / f"{k}.csv")
    manifest = {"run_name": args.run_name, "label": LABEL, "config_version": cfg.get("config_version"),
                "note": "Reanalysis (ERA5 models=era5, OISST, Open-Meteo marine SST) used as the forecast; shows runner "
                        "logic on known weather, NOT forecast skill. Persistence uses forecast days only.",
                "exposure_run": stations[0].get("exposure_run"), "n_records": len(yagi) + len(heat),
                "yagi_stations": [x["id"] for x in stations], "heat_station": "NB1",
                "used_by_alerts": False, "notification_eligible": False, "basis": "theory_only_unvalidated"}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(s["yagi_max_tier"].to_string())
    print(s["heat_tier_days"].to_string())
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
