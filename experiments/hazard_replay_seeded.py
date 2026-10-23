"""Re-run the hazard-runner replay with Wave-2 behaviour (theory only, shadow).

Differences from ``hazard_runner_replay.py`` (which stays as the Wave-1 record):
  * per-station effective config (``load_effective(station, exposure_class)``: scopes applied);
  * heat/cold persistence seeded with OBSERVED cage-sensor daily means before each issue day
    (``core.hazard_runner.sensor_daily_temperature``); the same days are also run without seeding
    (``persistence_basis: forecast_days_only``) so the effect is visible.

Still reanalysis-as-forecast: it shows runner logic on known weather, NOT forecast skill (decisions #18).

    python experiments/hazard_replay_seeded.py --run-name hazard-replay-20261024
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
from core.greenlab_api import load_cached_history  # noqa: E402
from experiments import hazard_runner_replay as base  # noqa: E402


def replay_heat_seeded(station: dict, cfg: dict, history: pd.DataFrame) -> list[dict]:
    serial = hr.SENSOR_SERIALS[station["id"]]
    recs = []
    for name, sst in (("openmeteo_marine", base.sst_marine_hourly()), ("oisst", base.sst_oisst_hourly())):
        for day in base.HEAT_DAYS:
            m = base._marine_payload(sst, day - pd.Timedelta(hours=7), source=name)
            if not m["hourly"]["time"]:
                continue
            obs = hr.sensor_daily_temperature(serial, day, history=history)
            for seeded, observed in (("seeded", obs), ("unseeded", None)):
                for r in hr.evaluate_station(station, None, m, now=day, config=cfg, max_age_hours=1e9, observed=observed):
                    if r["hazard"] in ("heat", "cold", "disease_env"):
                        recs.append({**r, "replay": {"label": base.LABEL, "scenario": "summer_2026", "sst_source": name,
                                                     "seeding": seeded, "sensor_available": obs is not None}})
    return recs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run-name", required=True)
    args = ap.parse_args(argv)
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / args.run_name
    run_dir.mkdir(parents=True, exist_ok=False)  # write-once: a failed run gets a new name
    stations = [s for s in hr.load_stations() if s["profile"] is not None]
    yagi = []
    versions = set()
    for st in stations:
        cfg = hr.load_effective(st["id"], st.get("exposure_class"))
        versions.add(cfg.get("config_version"))
        yagi += base.replay_yagi([st], cfg)
    nb1 = next(s for s in stations if s["id"] == "NB1")
    cfg = hr.load_effective(nb1["id"], nb1.get("exposure_class"))
    history = load_cached_history(hr.SENSOR_SERIALS["NB1"])
    heat = replay_heat_seeded(nb1, cfg, history)
    with (run_dir / "records.jsonl").open("x", encoding="utf-8", newline="\n") as fh:
        for r in yagi + heat:
            fh.write(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n")
    h = pd.DataFrame([{"sst_source": r["replay"]["sst_source"], "seeding": r["replay"]["seeding"], "hazard": r["hazard"],
                       "issue": r["issued_at"][:10], "lead": r["lead_hours"], "tier": r["tier"], "value": r["value"],
                       "basis": r["inputs"].get("persistence_basis"), "n_seed": len(r["inputs"].get("persistence_seed") or [])}
                      for r in heat])
    h0 = h[(h["lead"] == 0) & h["tier"].notna()]
    tier_days = h0.groupby(["sst_source", "seeding", "hazard", "tier"]).size().unstack(fill_value=0)
    tier_days.to_csv(run_dir / "heat_tier_days_lead0.csv")
    h0.to_csv(run_dir / "heat_daily_lead0.csv", index=False)
    y = pd.DataFrame([{"station": r["station"], "exposure_class": r["exposure_class"], "hazard": r["hazard"],
                       "tier": r["tier"]} for r in yagi])
    ymax = y[y["tier"].notna()].groupby(["station", "hazard"])["tier"].max().unstack()
    ymax["exposure_class"] = y.groupby("station")["exposure_class"].first()
    ymax.to_csv(run_dir / "yagi_max_tier.csv")
    manifest = {"run_name": args.run_name, "label": base.LABEL, "config_versions": sorted(v for v in versions if v),
                "note": "Reanalysis used as the forecast; shows runner logic on known weather, NOT forecast skill. "
                        "Heat/cold persistence seeded with observed cage-sensor daily means (seeded) vs forecast days only (unseeded).",
                "n_records": len(yagi) + len(heat), "yagi_stations": [x["id"] for x in stations], "heat_station": "NB1",
                "sensor_days_with_seed": int((h[(h.lead == 0) & (h.hazard == "heat") & (h.seeding == "seeded")]["n_seed"] > 0).sum()),
                "used_by_alerts": False, "notification_eligible": False, "basis": "theory_only_unvalidated"}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.set_option("display.width", 200)
    print(ymax.to_string())
    print(tier_days.to_string())
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
