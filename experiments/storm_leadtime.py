"""How many days ahead does the operational forecast path warn of strong wind at NB1?

Operational path = Open-Meteo forecast wind at the site (what an advisory could read), not
storm-centre information.  Past forecasts come from the Open-Meteo Previous Runs API:
``wind_speed_10m_previous_dayN`` is the value for a valid hour from the run issued N days earlier
(nominal issue time = valid time - 24 h * N; the exact model cycle is not exposed).

    python experiments/storm_leadtime.py download --model ecmwf_ifs025 --start 2024-01-01
    python experiments/storm_leadtime.py run --stamp 20261023d

Forecast model is pinned (``models=``): primary ``ecmwf_ifs025``; ``best_match`` (legacy file
without ``models=``) and others are secondary.  Model availability of ``*_previous_dayN`` (probed
2026-10-23 at NB1): ecmwf_ifs025 wind d1..7 yes, gust d1..7 none; gfs_seamless wind+gust d1..7;
icon_seamless d1..6 only (no d7); ecmwf_ifs (9 km) no previous days.

Truth: (i) PRIMARY true ERA5 (Open-Meteo archive ``models=era5``) hourly wind at NB1 - reanalysis,
independent of the forecasts, under-reads typhoon cores; (ii) SECONDARY archive ``best_match``
(= ECMWF IFS 9 km short-range from 2017) labelled "IFS short-range (not independent)": the
best_match Previous Runs lead 0 equals it, so it must not be read as verification;
(iii) best-track site wind from storm-hindcast passages.csv (oracle, one value per passage).
A guard raises if any forecast's lead 0 equals the primary truth on > 50 % of hours.
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
from experiments.hazard_data import latest_era5, write_once  # noqa: E402

STATION = "06M26042804"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
LEADS = tuple(range(0, 8))
THRESHOLDS = (6, 8, 10)  # Beaufort
DAY_THRESHOLDS = (6, 8, 10)
EVENT_HALF_WINDOW_H = 24
PASSAGES_DEFAULT = "storm-hindcast-20261023e"
PINNED_MODEL = "ecmwf_ifs025"
SECONDARY_MODELS = ("best_match", "gfs_seamless")
# truth name -> (archive model, label, independent of forecasts?)
TRUTHS = {"era5": ("era5", "ERA5 reanalysis (Open-Meteo models=era5)", True),
          "ifs_shortrange": ("best_match", "IFS short-range (not independent): archive best_match", False)}
MAX_EQUAL_SHARE = 0.5
EQUAL_ATOL = 0.005  # m/s; CSV round-trips keep 2 decimals


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
    """Warning lead for one event window.

    ``consistent_N`` = longest N such that every lead 1..N reaches ``level`` in the window (an
    unbroken warning from N days out); ``any_N`` = longest lead with a hit, gaps allowed.
    Nominal issue time of the first exceeding forecast hour t_f is t_f - 24 h * N, so the lead to the
    truth exceedance is 24 N + (truth_time - t_f) hours.  ``hits`` gives the flag for every N.
    """
    first = {n: first_exceed(fc_win[wind_col(n)], level) for n in leads}
    hits = {n: t is not None for n, t in first.items()}
    any_n = max((n for n, h in hits.items() if h), default=None)
    consistent_n = None
    for n in sorted(hits):
        if not hits[n]:
            break
        consistent_n = n

    def hours(n):
        if n is None or truth_time is None:
            return None
        return 24.0 * n + (truth_time - first[n]).total_seconds() / 3600.0

    return {"consistent_N": consistent_n, "consistent_lead_hours": hours(consistent_n),
            "any_N": any_n, "any_lead_hours": hours(any_n), "hits": hits}


def equal_share(fc: pd.Series, truth: pd.Series, atol: float = EQUAL_ATOL) -> float:
    """Share of common valid hours where forecast and truth agree within ``atol``."""
    d = pd.concat([fc.rename("f"), truth.rename("t")], axis=1).dropna()
    if d.empty:
        return float("nan")
    return float(np.isclose(d["f"], d["t"], atol=atol, rtol=0).mean())


def check_independent(fc_d0: pd.Series, truth: pd.Series, name: str, max_share: float = MAX_EQUAL_SHARE) -> float:
    """Raise if lead 0 equals the truth on > ``max_share`` of hours (truth would be the model itself)."""
    share = equal_share(fc_d0, truth)
    if share > max_share:
        raise ValueError(f"truth {name} equals forecast lead 0 on {share:.1%} of hours: not independent")
    return share


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
        corr = float(d.corr().iloc[0, 1]) if len(d) > 2 else float("nan")
        rows.append({"lead_day": n, "n_hours": len(d), "bias": float(err.mean()) if len(d) else float("nan"),
                     "MAE": float(err.abs().mean()) if len(d) else float("nan"),
                     "RMSE": float(np.sqrt((err ** 2).mean())) if len(d) else float("nan"), "corr": corr})
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


def fetch_previous_runs(start: date, end: date, model: str = PINNED_MODEL) -> dict:
    loc = weather_location_for_station(STATION)
    base = {"latitude": loc["latitude"], "longitude": loc["longitude"], "hourly": ",".join(hourly_variables()),
            "models": model, "wind_speed_unit": "ms", "timezone": "GMT"}
    frames = []
    for a, b in chunk_ranges(start, end):
        frames.append(parse_previous_runs(_get_json({**base, "start_date": a.isoformat(), "end_date": b.isoformat()})))
        time.sleep(1)
    df = pd.concat(frames, ignore_index=True)
    df["time"] = df["time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    target = (paths.HAZARD_DATA_DIR / "forecast_runs"
              / f"previous_runs_{model}_nb1_{start:%Y%m%d}_{end:%Y%m%d}_fetched{date.today():%Y%m%d}.csv")
    return write_once(target, df.to_csv(index=False).encode(), PREVIOUS_RUNS_URL, extra={"model": model})


def latest_forecasts(model: str) -> Path:
    """Newest Previous Runs file for ``model``; the legacy unlabelled file (no models=) is best_match."""
    d = paths.HAZARD_DATA_DIR / "forecast_runs"
    files = sorted(d.glob(f"previous_runs_{model}_nb1_*.csv"))
    if not files and model == "best_match":
        files = sorted(d.glob("previous_runs_nb1_*.csv"))
    if not files:
        raise FileNotFoundError(f"no Previous Runs file for model={model}: run storm_leadtime.py download --model {model}")
    return files[-1]


# ----------------------------------------------------------------------------- evaluation

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_hourly(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").sort_index()


load_forecasts = load_hourly
load_era5 = load_hourly


def bf_label(speed: float | None) -> str:
    if speed is None or pd.isna(speed):
        return "-"
    lvl = 0
    for i, lo in enumerate(BEAUFORT_LOWER_MS):
        if speed >= lo:
            lvl = i
    return str(lvl)


def event_table(fc: pd.DataFrame, truth: pd.Series, passages: pd.DataFrame, level: int) -> pd.DataFrame:
    rows = []
    for _, p in passages.iterrows():
        peak = pd.Timestamp(p["peak_time"])
        if peak.tzinfo is None:
            peak = peak.tz_localize("UTC")
        fw = window(fc, peak)
        tw = window(truth.to_frame("w"), peak)["w"]
        row = {"NAME": p["NAME"], "peak_time": peak, "min_dist_km": p["min_dist_km"],
               "site_beaufort": p["site_beaufort"], "truth_max_ms": tw.max() if len(tw) else np.nan,
               "truth_max_bf": bf_label(tw.max()) if len(tw) else "-", "threshold_bf": level}
        for n in LEADS:
            has = fw[wind_col(n)].notna().any()
            row[f"fc_max_bf_d{n}"] = bf_label(fw[wind_col(n)].max()) if has else "-"
            row[f"fc_max_ms_d{n}"] = fw[wind_col(n)].max() if has else np.nan
        for tag, truth_time in (("truth", first_exceed(tw, level)),
                                ("track", peak if p["site_beaufort"] >= level else None)):
            w = earliest_warning(fw, level, truth_time)
            row[f"is_event_{tag}"] = truth_time is not None
            row[f"consistent_N_{tag}"] = w["consistent_N"]
            row[f"consistent_lead_hours_{tag}"] = w["consistent_lead_hours"]
            row[f"any_N_{tag}"] = w["any_N"]
            row[f"any_lead_hours_{tag}"] = w["any_lead_hours"]
        hits = earliest_warning(fw, level, None)["hits"]
        row["hits_by_N"] = "".join(str(n) for n in hits if hits[n]) or "-"
        rows.append(row)
    return pd.DataFrame(rows)


def error_by_year(joined: pd.DataFrame, truth_col: str = "truth_wind") -> pd.DataFrame:
    """Mean wind and bias vs truth per calendar year: the forecast source may not be homogeneous in time."""
    rows = []
    for year, g in joined.groupby(joined.index.year):
        row = {"year": int(year), "truth_mean": float(g[truth_col].mean())}
        for n in LEADS:
            d = g[[wind_col(n), truth_col]].dropna()
            row[f"mean_d{n}"] = float(d[wind_col(n)].mean()) if len(d) else float("nan")
            row[f"bias_d{n}"] = float((d[wind_col(n)] - d[truth_col]).mean()) if len(d) else float("nan")
        rows.append(row)
    return pd.DataFrame(rows)


def day_contingency(fc: pd.DataFrame, truth: pd.Series, levels=DAY_THRESHOLDS) -> pd.DataFrame:
    obs_d = daily_max(truth)
    rows = []
    for level in levels:
        thr = threshold_ms(level)
        for n in LEADS:
            fc_d = daily_max(fc[wind_col(n)])
            j = pd.concat([fc_d.rename("f"), obs_d.rename("o")], axis=1).dropna()
            rows.append({"level": level, "lead_day": n, **contingency((j["f"] >= thr).to_numpy(), (j["o"] >= thr).to_numpy())})
    return pd.DataFrame(rows)


def _last_valid(s: pd.Series) -> pd.Timestamp:
    return s.dropna().index[-1]


def run(stamp: str, passages_dir: str, model: str = PINNED_MODEL, secondary=SECONDARY_MODELS) -> Path:
    fc_paths = {model: latest_forecasts(model)}
    for m in secondary:
        try:
            fc_paths[m] = latest_forecasts(m)
        except FileNotFoundError as exc:
            print(f"skip secondary {m}: {exc}")
    truth_paths = {name: latest_era5(arch) for name, (arch, _, _) in TRUTHS.items()}
    pas_path = paths.EXPERIMENT_OUTPUT_DIR / passages_dir / "passages.csv"
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / f"storm-leadtime-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)

    fcs = {m: load_hourly(p) for m, p in fc_paths.items()}
    truths = {name: load_hourly(p) for name, p in truth_paths.items()}
    coverage = {m: {f"d{n}": (None if f[wind_col(n)].dropna().empty else f[wind_col(n)].dropna().index[0].isoformat())
                    for n in LEADS} for m, f in fcs.items()}
    # Common period for every forecast/truth pair: all present leads 1..7 of every model valid,
    # ending at the last valid hour of every truth (true ERA5 lags ~5 days) and forecast.
    start = max(f[wind_col(n)].dropna().index[0] for f in fcs.values() for n in range(1, 8)
                if f[wind_col(n)].notna().any())
    end = min([_last_valid(t["wind_speed_10m"]) for t in truths.values()]
              + [_last_valid(f[wind_col(1)]) for f in fcs.values()])

    passages = pd.read_csv(pas_path)
    passages["peak_time"] = pd.to_datetime(passages["peak_time"], utc=True)
    passages = passages[(passages["peak_time"] >= start + pd.Timedelta(hours=EVENT_HALF_WINDOW_H))
                        & (passages["peak_time"] <= end - pd.Timedelta(hours=EVENT_HALF_WINDOW_H))]

    pairs = {}
    truth_counts = {}
    for tname, tdf in truths.items():
        tw = tdf["wind_speed_10m"].loc[start:end]
        truth_counts[tname] = {"exceed_hours": {f"bf{lvl}": int((tw >= threshold_ms(lvl)).sum()) for lvl in THRESHOLDS},
                               "exceed_days": {f"bf{lvl}": int((daily_max(tw) >= threshold_ms(lvl)).sum()) for lvl in THRESHOLDS},
                               "complete_days": int(daily_max(tw).notna().sum())}
    for m, f in fcs.items():
        fc = f.loc[start:end]
        for tname, tdf in truths.items():
            _, label, independent = TRUTHS[tname]
            tw = tdf["wind_speed_10m"].loc[start:end]
            share = check_independent(fc[wind_col(0)], tw, tname) if independent else equal_share(fc[wind_col(0)], tw)
            tag = f"{m}_vs_{tname}"
            ev = pd.concat([event_table(fc, tw, passages, lvl) for lvl in THRESHOLDS], ignore_index=True)
            ev.to_csv(run_dir / f"events_{tag}.csv", index=False)
            day_contingency(fc, tw).to_csv(run_dir / f"day_contingency_{tag}.csv", index=False)
            joined = fc.join(tdf["wind_speed_10m"].rename("truth_wind")).join(tdf["wind_gusts_10m"].rename("truth_gust"))
            error_by_lead(joined, "truth_wind", wind_col).to_csv(run_dir / f"error_wind_by_lead_{tag}.csv", index=False)
            error_by_lead(joined, "truth_gust", gust_col).to_csv(run_dir / f"error_gust_by_lead_{tag}.csv", index=False)
            error_by_year(joined).to_csv(run_dir / f"error_wind_by_year_{tag}.csv", index=False)
            pairs[tag] = {"forecast_model": m, "truth": tname, "truth_label": label, "truth_independent": independent,
                          "primary": m == model and tname == "era5", "d0_equals_truth_share": share}

    manifest = {"run": run_dir.name, "created": datetime.now(timezone.utc).isoformat(),
                "site": weather_location_for_station(STATION),
                "pinned_model": model, "secondary_models": [m for m in fcs if m != model],
                "truths": {k: {"archive_model": v[0], "label": v[1], "independent": v[2], "file": truth_paths[k].name}
                           for k, v in TRUTHS.items()},
                "inputs": {p.name: _sha(p) for p in (*fc_paths.values(), *truth_paths.values(), pas_path)},
                "params": {"leads": list(LEADS), "event_half_window_h": EVENT_HALF_WINDOW_H, "thresholds_bf": list(THRESHOLDS),
                           "day_basis": "UTC calendar day, complete 24 h only", "issue_time": "valid time - 24h * N (nominal)",
                           "independence_guard": f"raise if lead 0 == independent truth (atol {EQUAL_ATOL}) on > {MAX_EQUAL_SHARE:.0%} of hours",
                           "warning_lead": "consistent_N = longest N with hits at every lead 1..N; any_N = longest lead with a hit"},
                "period": {"start": start.isoformat(), "end": end.isoformat(), "n_hours": int(len(fcs[model].loc[start:end])),
                           "first_valid_by_lead": coverage},
                "n_passages_in_period": int(len(passages)), "truth_counts": truth_counts, "pairs": pairs}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download")
    d.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 1))
    d.add_argument("--end", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    d.add_argument("--model", default=PINNED_MODEL)
    r = sub.add_parser("run")
    r.add_argument("--stamp", required=True)
    r.add_argument("--passages-dir", default=PASSAGES_DEFAULT)
    r.add_argument("--model", default=PINNED_MODEL)
    r.add_argument("--secondary", nargs="*", default=list(SECONDARY_MODELS))
    args = parser.parse_args(argv)
    if args.cmd == "download":
        print(json.dumps(fetch_previous_runs(args.start, args.end, args.model), indent=2))
    else:
        run(args.stamp, args.passages_dir, args.model, tuple(args.secondary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
