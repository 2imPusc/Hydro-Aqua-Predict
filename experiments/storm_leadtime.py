"""How many days ahead does the operational forecast path warn of strong wind at NB1?

Operational path = Open-Meteo forecast wind at the site (what an advisory could read), not
storm-centre information.  Past forecasts come from the Open-Meteo Previous Runs API:
``wind_speed_10m_previous_dayN`` is the value for a valid hour from the run issued N days earlier
(nominal issue time = valid time - 24 h * N; the exact model cycle is not exposed).

    python experiments/storm_leadtime.py download --start 2024-01-01
    python experiments/storm_leadtime.py run --stamp 20261023

Truth for the evaluation: (i) ERA5 hourly wind at NB1 (reanalysis, under-reads typhoons) and
(ii) best-track site wind from storm-hindcast passages.csv (oracle, one value per passage).
Nothing here drives alerts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.config import weather_location_for_station  # noqa: E402
from core.storm_advisory import BEAUFORT_LOWER_MS  # noqa: E402
from experiments.hazard_data import write_once  # noqa: E402

STATION = "06M26042804"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
LEADS = tuple(range(0, 8))
THRESHOLDS = (6, 8, 10)  # Beaufort
DAY_THRESHOLDS = (6, 8, 10)
EVENT_HALF_WINDOW_H = 24
PASSAGES_DEFAULT = "storm-hindcast-20261022d"


def wind_col(lead: int) -> str:
    return f"wind_d{lead}"


def gust_col(lead: int) -> str:
    return f"gust_d{lead}"


def api_name(kind: str, lead: int) -> str:
    base = "wind_speed_10m" if kind == "wind" else "wind_gusts_10m"
    return base if lead == 0 else f"{base}_previous_day{lead}"


def hourly_variables() -> list[str]:
    return [api_name(kind, n) for kind in ("wind", "gust") for n in LEADS]


def chunk_ranges(start: date, end: date, days: int = 60) -> list[tuple[date, date]]:
    out, cur = [], start
    while cur <= end:
        stop = min(cur + timedelta(days=days - 1), end)
        out.append((cur, stop))
        cur = stop + timedelta(days=1)
    return out


def parse_previous_runs(payload: dict) -> pd.DataFrame:
    """API JSON -> frame indexed by UTC ``time`` with wind_d0..7 / gust_d0..7 (NaN when null)."""
    hourly = payload["hourly"]
    out = pd.DataFrame({"time": pd.to_datetime(hourly["time"]).tz_localize("UTC")})
    for kind, col in (("wind", wind_col), ("gust", gust_col)):
        for n in LEADS:
            vals = hourly.get(api_name(kind, n))
            out[col(n)] = pd.to_numeric(pd.Series(vals if vals is not None else [None] * len(out)), errors="coerce")
    return out


def threshold_ms(level: int) -> float:
    return BEAUFORT_LOWER_MS[level]


def first_exceed(series: pd.Series, level: int) -> pd.Timestamp | None:
    """First timestamp (index) where the wind speed reaches Beaufort ``level``; None if never."""
    hit = series.dropna()
    hit = hit[hit >= threshold_ms(level)]
    return None if hit.empty else hit.index[0]


def window(df: pd.DataFrame, peak: pd.Timestamp, half_hours: int = EVENT_HALF_WINDOW_H) -> pd.DataFrame:
    return df.loc[peak - pd.Timedelta(hours=half_hours): peak + pd.Timedelta(hours=half_hours)]


def earliest_warning(fc_win: pd.DataFrame, level: int, truth_time: pd.Timestamp | None,
                     leads=range(1, 8)) -> dict:
    """Longest lead N whose forecast in the window reaches ``level``; lead hours relative to truth.

    Nominal issue time of the first exceeding forecast hour t_f is t_f - 24 h * N, so the lead to the
    truth exceedance is 24 N + (truth_time - t_f) hours.  Also returns the hit flag for every N.
    """
    hits = {}
    best = None
    for n in leads:
        t_f = first_exceed(fc_win[wind_col(n)], level)
        hits[n] = t_f is not None
        if t_f is not None:
            best = (n, t_f)  # leads ascend, keep the longest
    lead_hours = None
    if best is not None and truth_time is not None:
        lead_hours = 24.0 * best[0] + (truth_time - best[1]).total_seconds() / 3600.0
    return {"earliest_N": None if best is None else best[0], "lead_hours": lead_hours, "hits": hits}


def contingency(fc: np.ndarray, obs: np.ndarray) -> dict:
    fc, obs = np.asarray(fc, dtype=bool), np.asarray(obs, dtype=bool)
    hits = int((fc & obs).sum())
    misses = int((~fc & obs).sum())
    fa = int((fc & ~obs).sum())
    cn = int((~fc & ~obs).sum())

    def div(a, b):
        return float(a / b) if b else float("nan")

    return {"n": len(fc), "hits": hits, "misses": misses, "false_alarms": fa, "correct_negatives": cn,
            "POD": div(hits, hits + misses), "FAR": div(fa, hits + fa),
            "CSI": div(hits, hits + misses + fa), "freq_bias": div(hits + fa, hits + misses)}


def daily_max(series: pd.Series, min_hours: int = 24) -> pd.Series:
    """UTC daily max, NaN for days with fewer than ``min_hours`` valid hours."""
    grp = series.groupby(series.index.floor("D"))
    return grp.max().where(grp.count() >= min_hours)


def error_by_lead(joined: pd.DataFrame, obs_col: str, col_fn) -> pd.DataFrame:
    rows = []
    for n in LEADS:
        d = joined[[obs_col, col_fn(n)]].dropna()
        err = d[col_fn(n)] - d[obs_col]
        rows.append({"lead_day": n, "n_hours": len(d), "bias": float(err.mean()), "MAE": float(err.abs().mean()),
                     "RMSE": float(np.sqrt((err ** 2).mean())), "corr": float(d.corr().iloc[0, 1])})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- download

def _get_json(params: dict, tries: int = 5) -> dict:
    for attempt in range(tries):
        try:
            resp = requests.get(PREVIOUS_RUNS_URL, params=params, timeout=120)
            if resp.status_code == 429:
                time.sleep(30 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            if attempt == tries - 1:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("rate limited")


def fetch_previous_runs(start: date, end: date) -> dict:
    loc = weather_location_for_station(STATION)
    base = {"latitude": loc["latitude"], "longitude": loc["longitude"], "hourly": ",".join(hourly_variables()),
            "wind_speed_unit": "ms", "timezone": "GMT"}
    frames = []
    for a, b in chunk_ranges(start, end):
        frames.append(parse_previous_runs(_get_json({**base, "start_date": a.isoformat(), "end_date": b.isoformat()})))
        time.sleep(1)
    df = pd.concat(frames, ignore_index=True)
    df["time"] = df["time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    target = (paths.HAZARD_DATA_DIR / "forecast_runs"
              / f"previous_runs_nb1_{start:%Y%m%d}_{end:%Y%m%d}_fetched{date.today():%Y%m%d}.csv")
    return write_once(target, df.to_csv(index=False).encode(), PREVIOUS_RUNS_URL)


# ----------------------------------------------------------------------------- evaluation

def _latest(directory: Path, pattern: str) -> Path:
    files = sorted(directory.glob(pattern))
    if not files:
        raise FileNotFoundError(f"missing {pattern} in {directory}")
    return files[-1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_forecasts(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").sort_index()


def load_era5(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").sort_index()


def bf_label(speed: float | None) -> str:
    if speed is None or pd.isna(speed):
        return "-"
    lvl = 0
    for i, lo in enumerate(BEAUFORT_LOWER_MS):
        if speed >= lo:
            lvl = i
    return str(lvl)


def event_table(fc: pd.DataFrame, era5: pd.Series, passages: pd.DataFrame, level: int) -> pd.DataFrame:
    rows = []
    for _, p in passages.iterrows():
        peak = pd.Timestamp(p["peak_time"])
        if peak.tzinfo is None:
            peak = peak.tz_localize("UTC")
        fw = window(fc, peak)
        ew = window(era5.to_frame("w"), peak)["w"]
        row = {"NAME": p["NAME"], "peak_time": peak, "min_dist_km": p["min_dist_km"],
               "site_beaufort": p["site_beaufort"], "era5_max_ms": ew.max() if len(ew) else np.nan,
               "era5_max_bf": bf_label(ew.max()) if len(ew) else "-", "threshold_bf": level}
        for n in range(0, 8):
            row[f"fc_max_bf_d{n}"] = bf_label(fw[wind_col(n)].max()) if fw[wind_col(n)].notna().any() else "-"
            row[f"fc_max_ms_d{n}"] = fw[wind_col(n)].max()
        for tag, truth_time in (("era5", first_exceed(ew, level)),
                                ("track", peak if p["site_beaufort"] >= level else None)):
            w = earliest_warning(fw, level, truth_time)
            row[f"earliest_N_{tag}"] = w["earliest_N"]
            row[f"lead_hours_{tag}"] = w["lead_hours"]
            row[f"truth_{tag}"] = truth_time is not None
            w6 = earliest_warning(fw, level, truth_time, leads=range(1, 7))
            row[f"earliest_N6_{tag}"] = w6["earliest_N"]
            row[f"lead_hours6_{tag}"] = w6["lead_hours"]
        row["hits_by_N"] = "".join(str(n) for n in range(1, 8) if earliest_warning(fw, level, None)["hits"][n]) or "-"
        rows.append(row)
    return pd.DataFrame(rows)


def error_by_year(joined: pd.DataFrame) -> pd.DataFrame:
    """Mean wind and bias vs ERA5 per calendar year: the forecast source is not homogeneous in time."""
    rows = []
    for year, g in joined.groupby(joined.index.year):
        row = {"year": int(year), "era5_mean": float(g["era5_wind"].mean())}
        for n in LEADS:
            d = g[[wind_col(n), "era5_wind"]].dropna()
            row[f"mean_d{n}"] = float(d[wind_col(n)].mean())
            row[f"bias_d{n}"] = float((d[wind_col(n)] - d["era5_wind"]).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def day_contingency(fc: pd.DataFrame, era5: pd.Series, levels=DAY_THRESHOLDS) -> pd.DataFrame:
    obs_d = daily_max(era5)
    rows = []
    for level in levels:
        thr = threshold_ms(level)
        for n in LEADS:
            fc_d = daily_max(fc[wind_col(n)])
            j = pd.concat([fc_d.rename("f"), obs_d.rename("o")], axis=1).dropna()
            rows.append({"level": level, "lead_day": n, **contingency((j["f"] >= thr).to_numpy(), (j["o"] >= thr).to_numpy())})
    return pd.DataFrame(rows)


def run(stamp: str, passages_dir: str, forecasts: Path | None, era5_path: Path | None) -> Path:
    fc_path = forecasts or _latest(paths.HAZARD_DATA_DIR / "forecast_runs", "previous_runs_nb1_*.csv")
    era_path = era5_path or _latest(paths.HAZARD_DATA_DIR / "era5", "era5_nb1_*.csv")
    pas_path = paths.EXPERIMENT_OUTPUT_DIR / passages_dir / "passages.csv"
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / f"storm-leadtime-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)

    fc = load_forecasts(fc_path)
    era = load_era5(era_path)
    both_end = min(fc.index.max(), era.index.max())
    # Common period: first hour where the lead-1 forecast exists; the whole 1..7 set reported in coverage.
    coverage = {f"d{n}": (None if fc[wind_col(n)].dropna().empty else fc[wind_col(n)].dropna().index[0].isoformat())
                for n in LEADS}
    start = max(fc[wind_col(n)].dropna().index[0] for n in range(1, 8))
    fc = fc.loc[start:both_end]
    era_w = era["wind_speed_10m"].loc[start:both_end]

    passages = pd.read_csv(pas_path)
    passages["peak_time"] = pd.to_datetime(passages["peak_time"], utc=True)
    passages = passages[(passages["peak_time"] >= start + pd.Timedelta(hours=EVENT_HALF_WINDOW_H))
                        & (passages["peak_time"] <= both_end - pd.Timedelta(hours=EVENT_HALF_WINDOW_H))]

    ev = pd.concat([event_table(fc, era_w, passages, lvl) for lvl in THRESHOLDS], ignore_index=True)
    ev.to_csv(run_dir / "events.csv", index=False)
    day = day_contingency(fc, era_w)
    day.to_csv(run_dir / "day_contingency.csv", index=False)
    joined = fc.join(era["wind_speed_10m"].rename("era5_wind")).join(era["wind_gusts_10m"].rename("era5_gust"))
    ew = error_by_lead(joined, "era5_wind", wind_col)
    eg = error_by_lead(joined, "era5_gust", gust_col)
    error_by_year(joined).to_csv(run_dir / "error_wind_by_year.csv", index=False)
    ew.to_csv(run_dir / "error_wind_by_lead.csv", index=False)
    eg.to_csv(run_dir / "error_gust_by_lead.csv", index=False)
    # ERA5 hourly exceedance counts, to show what truth contains.
    counts = {f"bf{lvl}": int((era_w >= threshold_ms(lvl)).sum()) for lvl in THRESHOLDS}
    daily_counts = {f"bf{lvl}": int((daily_max(era_w) >= threshold_ms(lvl)).sum()) for lvl in THRESHOLDS}

    manifest = {"run": run_dir.name, "created": datetime.now(timezone.utc).isoformat(),
                "site": weather_location_for_station(STATION),
                "inputs": {p.name: _sha(p) for p in (fc_path, era_path, pas_path)},
                "params": {"leads": list(LEADS), "event_half_window_h": EVENT_HALF_WINDOW_H, "thresholds_bf": list(THRESHOLDS),
                           "day_basis": "UTC calendar day, complete 24 h only", "issue_time": "valid time - 24h * N (nominal)"},
                "period": {"start": start.isoformat(), "end": both_end.isoformat(), "n_hours": int(len(fc)),
                           "first_valid_by_lead": coverage},
                "n_passages_in_period": int(len(passages)), "era5_exceed_hours": counts, "era5_exceed_days": daily_counts}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download")
    d.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 1))
    d.add_argument("--end", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    r = sub.add_parser("run")
    r.add_argument("--stamp", required=True)
    r.add_argument("--passages-dir", default=PASSAGES_DEFAULT)
    r.add_argument("--forecasts", type=Path)
    r.add_argument("--era5", type=Path)
    args = parser.parse_args(argv)
    if args.cmd == "download":
        print(json.dumps(fetch_previous_runs(args.start, args.end), indent=2))
    else:
        run(args.stamp, args.passages_dir, args.forecasts, args.era5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
