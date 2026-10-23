"""Disease-favourable environment hindcast at NB1 (theory index, core/disease_risk.py).

OISST 1982-2026 (+ ERA5 rain) and the sensor period; days/yr per level, Theil-Sen trend, ISO-week
calendar, +-1 C breakpoint sensitivity, ERA5 air-temperature cold sensitivity, and a check against
documented mass-mortality events (experiments/disease_events.csv).

    python experiments/disease_hindcast.py --stamp 20261023
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hazard_data as hd  # noqa: E402
import heat_hindcast as hh  # noqa: E402
from core import disease_risk as dr  # noqa: E402
from core import heat_stress as hs  # noqa: E402
from core import paths  # noqa: E402

EVENTS_CSV = Path(__file__).with_name("disease_events.csv")
# Events whose stated cause is not environmental (pollution etc.) are listed but not scored.
NON_ENVIRONMENTAL = {"phulong-2026": "suspected_wastewater"}
# Sources name a pathogen / infection: secondary fungal+bacterial infection after cold (Nhu et al. 2011),
# gill fungus (lanha-2018). The others are cold, low O2 or low salinity without a named pathogen.
PATHOGEN_ATTRIBUTED = {"cold-north-2008", "lanha-2018"}
PRE_DAYS = 14
MIN_EVENTS = 5
SHIFTS = (-1.0, 0.0, 1.0)


def oisst_daily(path: Path) -> pd.Series:
    s = pd.read_csv(path, parse_dates=["time"]).set_index("time")["sst"]
    s.index = s.index.tz_convert("UTC").normalize().tz_localize(None)  # OISST day = its UTC date
    return s


def resolve_sources(rain_model: str = "era5", air_model: str = "era5") -> dict:
    """Model-explicit hourly inputs; legacy unlabelled files only ever resolve as best_match."""
    return {"rain_model": rain_model, "air_model": air_model,
            "rain_file": hd.latest_precip(rain_model), "air_file": hd.latest_era5(air_model)}


def rain_daily(path: Path) -> pd.Series:
    hourly = pd.read_csv(path, parse_dates=["time"]).set_index("time")["precipitation"]
    return hs.daily_from_hourly(hourly, min_hours=24, how="sum")


def yearly(days: pd.DataFrame) -> pd.DataFrame:
    g = days.groupby(days.index.year)
    out = pd.DataFrame({
        "days_level2": g["level"].apply(lambda s: int((s == 2).sum())),
        "days_level_ge1": g["level"].apply(lambda s: int((s >= 1).sum())),
        "days_cold_high": g["cold_risk"].apply(lambda s: int((s >= dr.HIGH).sum())),
        "max_cold_run_days": g["cold_run_days"].max(),
        "days_heavy_rain_flag": g["heavy_rain_flag"].sum().astype(int),
        "days_rapid_change_flag": g["rapid_change_flag"].sum().astype(int),
        "n_days": g["temp_c"].count(),
    })
    for name in dr.WARM_GROUPS:
        out[f"days_full_{name}"] = g[f"mu_{name}"].apply(lambda s: int((s >= 1).sum()))
    return out[out["n_days"] >= hh.MIN_YEAR_DAYS]


def week_calendar(days: pd.DataFrame) -> pd.DataFrame:
    """Share of days per ISO week at level 2 (and >= 1), pooled over the given (complete) years."""
    valid = days[days["level"].notna()]
    week = valid.index.isocalendar()["week"].to_numpy()
    return pd.DataFrame({"share_days_level2": (valid["level"] == 2).groupby(week).mean().round(3),
                         "share_days_level_ge1": (valid["level"] >= 1).groupby(week).mean().round(3)}).rename_axis("iso_week")


def _same_window(start: pd.Timestamp, end: pd.Timestamp, year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    def move(d: pd.Timestamp, y: int) -> pd.Timestamp:
        return pd.Timestamp(date(y, d.month, min(d.day, 28) if (d.month, d.day) == (2, 29) else d.day))
    shift = year - end.year
    return move(start, start.year + shift), move(end, year)


def window_stats(days: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    w = days.loc[start:end]
    v = w[w["level"].notna()]
    if v.empty:
        return {"n_valid_days": 0}
    return {"n_valid_days": int(len(v)), "max_index": round(float(v["index"].max()), 3), "max_level": int(v["level"].max()),
            "any_ge1": bool((v["level"] >= 1).any()), "any_level2": bool((v["level"] == 2).any()),
            "max_warm_index": round(float(v["warm_index"].max()), 3), "max_cold_risk": round(float(v["cold_risk"].max()), 3),
            "min_temp_c": round(float(v["temp_c"].min()), 2), "max_temp_c": round(float(v["temp_c"].max()), 2),
            "any_heavy_rain": bool(v["heavy_rain_flag"].any()), "any_rapid_change": bool(v["rapid_change_flag"].any())}


def climatology_hit_rate(days: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, years: list[int]) -> dict:
    hits1, hits2, rain, n = 0, 0, 0, 0
    for y in years:
        s, e = _same_window(start, end, y)
        st = window_stats(days, s, e)
        if st.get("n_valid_days", 0) == 0:
            continue
        n += 1
        hits1 += st["any_ge1"]
        hits2 += st["any_level2"]
        rain += st["any_heavy_rain"]

    def p(k):
        return round(k / n, 3) if n else None
    return {"n_years": n, "p_any_ge1": p(hits1), "p_any_level2": p(hits2), "p_any_heavy_rain": p(rain)}


def evaluate(days: pd.DataFrame, events: pd.DataFrame, years: list[int], air_cold: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    rows = []
    for ev in events.itertuples(index=False):
        start, end = pd.Timestamp(ev.start_date), pd.Timestamp(ev.end_date)
        win_start = start - pd.Timedelta(days=PRE_DAYS)
        row = {"event_id": ev.event_id, "window_start": win_start.date().isoformat(), "window_end": end.date().isoformat(),
               "excluded": NON_ENVIRONMENTAL.get(ev.event_id, "")}
        row.update({f"pre_{k}": v for k, v in window_stats(days, win_start, start - pd.Timedelta(days=1)).items()})
        row.update(window_stats(days, win_start, end))
        row.update({f"clim_{k}": v for k, v in climatology_hit_rate(days, win_start, end, years).items()})
        if air_cold is not None:
            w = air_cold.loc[win_start:end, "cold_risk"].dropna()
            row["air_max_cold_risk"] = round(float(w.max()), 3) if len(w) else None
        rows.append(row)
    table = pd.DataFrame(rows)
    scored = table[(table["excluded"] == "") & (table["n_valid_days"].fillna(0) > 0)]
    n = int(len(scored))
    summary = {"n_events_listed": int(len(table)), "n_scored": n, "pre_days": PRE_DAYS,
               "excluded": {k: v for k, v in NON_ENVIRONMENTAL.items() if k in set(table["event_id"])}}
    if n:
        summary.update({
            "hits_any_ge1": int(scored["any_ge1"].sum()), "hits_any_level2": int(scored["any_level2"].sum()),
            "pre_hits_any_ge1": int(scored["pre_any_ge1"].sum()), "pre_hits_any_level2": int(scored["pre_any_level2"].sum()),
            "mean_clim_p_any_ge1": round(float(scored["clim_p_any_ge1"].mean()), 3),
            "mean_clim_p_any_level2": round(float(scored["clim_p_any_level2"].mean()), 3)})
        hit2, clim2 = summary["hits_any_level2"] / n, summary["mean_clim_p_any_level2"]
        summary["hit_rate_level2"] = round(hit2, 3)
    if n < MIN_EVENTS:
        summary["verdict"] = "insufficient_evidence"
    else:
        summary["verdict"] = "no_skill_over_climatology" if hit2 <= clim2 else "above_climatology_small_n"
    attributed = scored[scored["event_id"].isin(PATHOGEN_ATTRIBUTED)]
    summary["n_pathogen_attributed"] = int(len(attributed))
    summary["verdict_pathogen_attributed"] = "insufficient_evidence" if len(attributed) < MIN_EVENTS else "scored"
    if n:
        summary["hits_heavy_rain_flag"] = int(scored["any_heavy_rain"].sum())
        summary["mean_clim_p_any_heavy_rain"] = round(float(scored["clim_p_any_heavy_rain"].mean()), 3)
    return table, summary


def sensitivity(temp: pd.Series, rain: pd.Series, events: pd.DataFrame) -> list[dict]:
    out = []
    for shift in SHIFTS:
        days = dr.daily_disease_risk(temp, rain_mm=rain, shift_c=shift)
        years = yearly(days)
        complete = days[days.index.year.isin(years.index)]
        cal = week_calendar(complete)
        high_weeks = cal.index[cal["share_days_level2"] >= 0.5]
        _, ev = evaluate(days, events, list(years.index))
        out.append({"shift_c": shift, "mean_days_level2": round(float(years["days_level2"].mean()), 1),
                    "mean_days_level_ge1": round(float(years["days_level_ge1"].mean()), 1),
                    "mean_days_cold_high": round(float(years["days_cold_high"].mean()), 2),
                    "iso_weeks_level2_share_ge_0.5": [int(high_weeks.min()), int(high_weeks.max())] if len(high_weeks) else None,
                    "event_hits_any_level2": ev.get("hits_any_level2"), "event_verdict": ev["verdict"]})
    return out


def _thresholds() -> dict:
    def clean(bp):
        return [None if math.isinf(v) else v for v in bp]
    return {"warm_groups_trapezoid_c": {k: clean(v) for k, v in dr.WARM_GROUPS.items()},
            "cold": {"full_c": dr.COLD_FULL_C, "zero_c": dr.COLD_ZERO_C, "feed_stop_c": dr.COLD_FEED_STOP_C,
                     "run_days": dr.COLD_RUN_DAYS, "cap_before_run": dr.COLD_CAP_BEFORE_RUN},
            "rain_3d_mm": dr.RAIN_3D_MM, "rapid_change_c_3d": dr.RAPID_CHANGE_C, "stress_bump": dr.STRESS_BUMP,
            "levels": {"medium": dr.MEDIUM, "high": dr.HIGH}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stamp", required=True)
    parser.add_argument("--rain-model", choices=hd.ARCHIVE_MODELS, default="era5")
    parser.add_argument("--air-model", choices=hd.ARCHIVE_MODELS, default="era5")
    args = parser.parse_args(argv)
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / f"disease-hindcast-{args.stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    oisst_file = hh._longest_oisst()
    src = resolve_sources(args.rain_model, args.air_model)
    rain_file, era5_file = src["rain_file"], src["air_file"]
    oisst, rain = oisst_daily(oisst_file), rain_daily(rain_file)
    air = hs.daily_from_hourly(pd.read_csv(era5_file, parse_dates=["time"]).set_index("time")["temperature_2m"])
    events = pd.read_csv(EVENTS_CSV, dtype=str)

    days = dr.daily_disease_risk(oisst, rain_mm=rain)
    days["rain_source"] = src["rain_model"]
    days.to_csv(run_dir / "daily_oisst.csv", index_label="date")
    years = yearly(days)
    years.to_csv(run_dir / "climatology_year.csv", index_label="year")
    trends = [hh.trend(years, c) for c in ("days_level2", "days_level_ge1", "days_cold_high",
                                            *(f"days_full_{n}" for n in dr.WARM_GROUPS))]
    complete = days[days.index.year.isin(years.index)]
    week_calendar(complete).to_csv(run_dir / "risk_calendar.csv")

    air_cold = dr.daily_disease_risk(air)[["temp_c", "mu_cold", "cold_run_days", "cold_risk"]]
    air_cold = air_cold.assign(cold_air_source=src["air_model"])
    air_cold.to_csv(run_dir / "daily_air_cold_sensitivity.csv", index_label="date")
    air_years = air_cold.groupby(air_cold.index.year)["cold_risk"].apply(lambda s: int((s >= dr.HIGH).sum()))

    sensor = hh.sensor_daily()
    sensor_days = dr.daily_disease_risk(sensor, rain_mm=rain)
    sensor_days["rain_source"] = src["rain_model"]
    sensor_days.to_csv(run_dir / "daily_sensor.csv", index_label="date")
    overlap = days["level"].reindex(sensor_days["level"].dropna().index).dropna()
    sensor_summary = {"n_days": int(sensor_days["level"].notna().sum()),
                      "first": str(sensor_days.index.min().date()), "last": str(sensor_days.index.max().date()),
                      "days_level2": int((sensor_days["level"] == 2).sum()), "days_level1": int((sensor_days["level"] == 1).sum()),
                      "days_level0": int((sensor_days["level"] == 0).sum()),
                      "oisst_same_days_level2": int((overlap == 2).sum()), "oisst_same_days_n": int(len(overlap)),
                      "level_agreement_with_oisst": round(float((sensor_days.loc[overlap.index, "level"] == overlap).mean()), 3) if len(overlap) else None,
                      "days_heavy_rain_flag": int(sensor_days["heavy_rain_flag"].sum()),
                      "days_rapid_change_flag": int(sensor_days["rapid_change_flag"].sum())}

    table, summary = evaluate(days, events, list(years.index), air_cold=air_cold)
    table.to_csv(run_dir / "event_scores.csv", index=False)
    sens = sensitivity(oisst, rain, events)
    summary["robust_to_shift_1c"] = len({s["event_verdict"] for s in sens}) == 1
    results = {"rain_source": src["rain_model"], "cold_air_source": src["air_model"],
               "years": [int(years.index.min()), int(years.index.max())], "n_years": int(len(years)),
               "mean_days_level2": round(float(years["days_level2"].mean()), 1),
               "mean_days_level_ge1": round(float(years["days_level_ge1"].mean()), 1),
               "mean_days_cold_high_oisst": round(float(years["days_cold_high"].mean()), 2),
               "mean_days_cold_high_era5_air": round(float(air_years[air_years.index.isin(years.index)].mean()), 2),
               "mean_days_full_by_group": {n: round(float(years[f"days_full_{n}"].mean()), 1) for n in dr.WARM_GROUPS},
               "mean_days_heavy_rain_flag": round(float(years["days_heavy_rain_flag"].mean()), 2),
               "mean_days_rapid_change_flag": round(float(years["days_rapid_change_flag"].mean()), 2),
               "trends": trends, "sensor_period": sensor_summary, "evaluation": summary, "sensitivity": sens}
    (run_dir / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = {"run": run_dir.name, "source": {"daily_oisst": "reanalysis", "daily_sensor": "sensor",
                                                "rain": "reanalysis", "air_cold": "reanalysis"},
                "rain_source": src["rain_model"], "cold_air_source": src["air_model"],
                **dr.FLAGS, "note_vi": dr.NOTE_VI, "thresholds": _thresholds(),
                "inputs": {p.name: hh._sha(p) for p in (oisst_file, rain_file, era5_file, EVENTS_CSV)},
                "sensor_days": int(len(sensor))}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"run": run_dir.name, **results}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
