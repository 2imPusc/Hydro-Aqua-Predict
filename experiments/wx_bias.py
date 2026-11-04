"""Task 2.2 (RL-WXBIAS): how wrong are the Open-Meteo forecasts the advisory reads, at coastal SYNOP stations?

Truth: 4TA SYNOP (``paths.VN_SYNOP_DIR / derived/synop_3h_v2.parquet``, decisions #30) at Bai Chay, Phu Lien,
Bach Long Vi, Hon Dau, Co To.  Licence unconfirmed -> system use only, not paper data.
Forecasts: Open-Meteo Previous Runs (``*_previous_dayN``, N = 1..7 ~ 24N h lead; nominal issue time
valid - 24 h * N, exact cycle unknown) for ``best_match`` (core/weather.py, no ``models=``), ``ecmwf_ifs025``
(core/hazard_runner.py) and ``gfs_seamless`` (secondary), at each station's lat/lon, default cell selection.

    python -I experiments/wx_bias.py download            # write-once JSON under paths.WEATHER_PREVIOUS_RUNS_DIR
    python -I experiments/wx_bias.py run --stamp 20261104

Go/no-go on a correction is pre-registered in ``experiments/wx_bias_preregistration.json`` (committed before
any forecast was downloaded).  Nothing here drives alerts; the proposed correction config stays inactive.
"""
from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "2")

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from datetime import date, datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402

PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
DOWNLOAD_SUBDIR = "synop-coastal-2024-2025"
STATIONS = {"48833": "Bai Chay", "48826": "Phu Lien", "48839": "Bach Long Vi", "48828": "Hon Dau", "48834": "Co To"}
MODELS = ("best_match", "ecmwf_ifs025", "gfs_seamless")
API_VARS = {"t2m": "temperature_2m", "rh": "relative_humidity_2m", "wind": "wind_speed_10m", "precip": "precipitation"}
OBS_COLS = {"t2m": "t2m_c", "rh": "rh_pct", "wind": "wspd_ms"}
LEADS = tuple(range(1, 8))
FETCH_START, FETCH_END = date(2024, 1, 1), date(2025, 12, 4)
CHUNK_DAYS = 120
SLEEP_S = 4.0
SPLIT = pd.Timestamp("2025-01-01")
YAGI = (pd.Timestamp("2024-09-06"), pd.Timestamp("2024-09-09"))  # [start, end) UTC
KMH35_MS = 35 / 3.6
BEAUFORT_MS = {6: 10.8, 8: 17.2, 10: 24.5}
WIND_THRESHOLDS = {"watch_35kmh": KMH35_MS, "bf6": 10.8, "bf8": 17.2, "bf10": 24.5}
RAIN_THRESHOLDS = {"rain6h": (10.0,), "rain24h": (16.0, 50.0, 100.0), "rain72h": (100.0,)}
SEASONS = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM", 6: "JJA", 7: "JJA", 8: "JJA",
           9: "SON", 10: "SON", 11: "SON"}
QM_PROBS = np.concatenate([np.linspace(0.0, 0.99, 100), [0.995, 0.999, 1.0]])
PREREG = Path(__file__).with_name("wx_bias_preregistration.json")


# ---------------------------------------------------------------- download
def chunk_ranges(start: date, end: date, days: int = CHUNK_DAYS) -> list[tuple[date, date]]:
    out, cur = [], start
    while cur <= end:
        stop = min(cur + timedelta(days=days - 1), end)
        out.append((cur, stop))
        cur = stop + timedelta(days=1)
    return out


def hourly_names() -> list[str]:
    return [f"{api}_previous_day{n}" for api in API_VARS.values() for n in LEADS]


def station_coords(synop: pd.DataFrame) -> dict[str, tuple[float, float]]:
    first = synop.drop_duplicates("station_code").set_index("station_code")
    return {c: (round(float(first.loc[c, "lat"]), 4), round(float(first.loc[c, "lon"]), 4)) for c in STATIONS}


def download(out_dir: Path, coords: dict[str, tuple[float, float]], sleep_s: float = SLEEP_S) -> list[dict]:
    import requests

    from experiments.hazard_data import write_once

    log = []
    for code, (lat, lon) in coords.items():
        for model in MODELS:
            for a, b in chunk_ranges(FETCH_START, FETCH_END):
                target = out_dir / f"{code}_{model}_{a:%Y%m%d}_{b:%Y%m%d}.json"
                if target.exists():
                    log.append({"file": target.name, "status": "exists"})
                    continue
                params = {"latitude": lat, "longitude": lon, "hourly": ",".join(hourly_names()),
                          "start_date": a.isoformat(), "end_date": b.isoformat(), "timezone": "UTC",
                          "wind_speed_unit": "ms", "models": model}
                body = None
                for attempt in range(4):
                    try:
                        r = requests.get(PREVIOUS_RUNS_URL, params=params, timeout=300)
                        if r.status_code in (429, 502, 503, 504):
                            raise RuntimeError(f"HTTP {r.status_code}")
                        r.raise_for_status()
                        body = r.json()
                        break
                    except (RuntimeError, ValueError, requests.RequestException) as exc:
                        print(f"retry {attempt + 1} {target.name}: {exc}", flush=True)
                        time.sleep(60 * (attempt + 1))
                if body is None:
                    raise RuntimeError(f"giving up: {target.name}")
                if "hourly" not in body:
                    raise RuntimeError(f"no hourly in response for {target.name}: {str(body)[:200]}")
                meta = write_once(target, r.content, r.url, {
                    "station_code": code, "station_name": STATIONS[code], "model": model,
                    "request_lat": lat, "request_lon": lon, "grid_lat": body.get("latitude"),
                    "grid_lon": body.get("longitude"), "grid_elevation": body.get("elevation"),
                    "start": a.isoformat(), "end": b.isoformat(), "wind_speed_unit": "ms", "timezone": "UTC"})
                log.append({**meta, "status": "fetched"})
                print(target.name, meta["bytes"], flush=True)
                time.sleep(sleep_s)
    return log


def parse_payload(payload: dict) -> pd.DataFrame:
    """API JSON -> frame indexed by naive UTC hour; columns ``<var>_d<N>`` (NaN where null)."""
    hourly = payload["hourly"]
    idx = pd.DatetimeIndex(pd.to_datetime(hourly["time"]), name="time")
    cols = {}
    for var, api in API_VARS.items():
        for n in LEADS:
            vals = hourly.get(f"{api}_previous_day{n}")
            cols[f"{var}_d{n}"] = pd.to_numeric(pd.Series(vals if vals is not None else [None] * len(idx)),
                                                errors="coerce").to_numpy(dtype=float)
    return pd.DataFrame(cols, index=idx)


def load_forecasts(src: Path) -> dict[tuple[str, str], pd.DataFrame]:
    """(station, model) -> hourly frame over the whole period."""
    parts: dict[tuple[str, str], list[pd.DataFrame]] = {}
    for f in sorted(src.glob("*.json")):
        if f.name.endswith(".manifest.json") or f.name.startswith("manifest"):
            continue
        code, rest = f.stem.split("_", 1)
        model = rest.rsplit("_", 2)[0]
        parts.setdefault((code, model), []).append(parse_payload(json.loads(f.read_text(encoding="utf-8"))))
    return {k: pd.concat(v).sort_index().pipe(lambda d: d[~d.index.duplicated()]) for k, v in parts.items()}


# ---------------------------------------------------------------- truth
def qc_ok(df: pd.DataFrame, col: str) -> pd.Series:
    """True where ``col`` is present and not flagged; flags of other variables do not drop the value."""
    flags = df["qc_flags"].fillna("").astype(str)
    flagged = flags.str.split(";").map(lambda xs: col in xs)
    return df[col].notna() & ~flagged


def load_synop(path: Path | None = None) -> pd.DataFrame:
    path = path or paths.VN_SYNOP_DIR / "derived" / "synop_3h_v2.parquet"
    d = pd.read_parquet(path, filters=[("station_code", "in", list(STATIONS))])
    return d[d["obs_utc"] >= pd.Timestamp(FETCH_START)].reset_index(drop=True)


# ---------------------------------------------------------------- alignment
def window_sum(hourly: pd.Series, ends: pd.DatetimeIndex, hours: int) -> pd.Series:
    """Total over the ``hours`` ending at each end time.

    Open-Meteo hourly ``precipitation`` at hour h is the total of the preceding hour (h-1, h], so the window
    (H - hours, H] is hours H-hours+1 .. H inclusive.  NaN if any hour is missing.
    """
    full = hourly.reindex(pd.date_range(hourly.index.min(), hourly.index.max(), freq="h"))
    roll = full.rolling(hours, min_periods=hours).sum()
    return roll.reindex(ends)


def season(ts: pd.Series) -> pd.Series:
    """Season from local (UTC+7) month of the valid time."""
    return (ts + pd.Timedelta(hours=7)).dt.month.map(SEASONS)


def rain_truth(synop_station: pd.DataFrame) -> dict[str, pd.Series]:
    s = synop_station.set_index("obs_utc").sort_index()
    r6 = s.loc[qc_ok(s, "rain6h_mm") & s.index.hour.isin([0, 6, 12, 18]), "rain6h_mm"].astype(float)
    r24 = s.loc[qc_ok(s, "rain24h_mm") & (s.index.hour == 12), "rain24h_mm"].astype(float)
    r24 = r24[~r24.index.duplicated()]
    daily = r24.reindex(pd.date_range(r24.index.min(), r24.index.max(), freq="24h")) if len(r24) else r24
    r72 = daily.rolling(3, min_periods=3).sum().dropna()
    return {"rain6h": r6, "rain24h": r24, "rain72h": r72}


def build_pairs(synop: pd.DataFrame, fc: dict[tuple[str, str], pd.DataFrame]) -> pd.DataFrame:
    """Long table: station, model, variable, lead, valid_utc, obs, fc (both present)."""
    rows = []
    for (code, model), f in fc.items():
        st = synop[synop["station_code"] == code]
        if st.empty:
            continue
        s = st.set_index("obs_utc").sort_index()
        s = s[~s.index.duplicated()]
        truths = {v: s.loc[qc_ok(s, c), c].astype(float) for v, c in OBS_COLS.items()}
        truths.update(rain_truth(st))
        for var, obs in truths.items():
            for n in LEADS:
                if var in OBS_COLS:
                    pred = f[f"{var}_d{n}"].reindex(obs.index)
                else:
                    hours = int(var.removeprefix("rain").removesuffix("h"))
                    pred = window_sum(f[f"precip_d{n}"], obs.index, hours)
                ok = pred.notna() & obs.notna()
                if ok.any():
                    rows.append(pd.DataFrame({"station": code, "model": model, "variable": var, "lead": n,
                                              "valid_utc": obs.index[ok], "obs": obs[ok].to_numpy(),
                                              "fc": pred[ok].to_numpy()}))
    out = pd.concat(rows, ignore_index=True)
    out["season"] = season(out["valid_utc"])
    return out


# ---------------------------------------------------------------- scores
def continuous_scores(p: pd.DataFrame) -> pd.Series:
    e = p["fc"] - p["obs"]
    return pd.Series({"n": len(e), "bias": e.mean(), "mae": e.abs().mean(), "rmse": float(np.sqrt((e ** 2).mean())),
                      "obs_mean": p["obs"].mean(), "fc_mean": p["fc"].mean()})


def contingency(obs, fc, thr: float) -> dict:
    o = np.asarray(obs, dtype=float) >= thr
    f = np.asarray(fc, dtype=float) >= thr
    a, b, c, d = int((o & f).sum()), int((~o & f).sum()), int((o & ~f).sum()), int((~o & ~f).sum())

    def div(x, y):
        return x / y if y else np.nan

    return {"threshold": thr, "n": a + b + c + d, "obs_events": a + c, "fc_events": a + b, "hits": a,
            "false_alarms": b, "misses": c, "correct_neg": d, "pod": div(a, a + c), "far": div(b, a + b),
            "csi": div(a, a + b + c), "freq_bias": div(a + b, a + c)}


def fit_additive(obs, fc) -> float:
    return float(np.mean(np.asarray(fc, float) - np.asarray(obs, float)))


def fit_qm(obs, fc, probs: np.ndarray = QM_PROBS) -> dict:
    """Empirical quantile table fc->obs (same probabilities; values made non-decreasing)."""
    q_fc = np.maximum.accumulate(np.quantile(np.asarray(fc, float), probs))
    q_obs = np.maximum.accumulate(np.quantile(np.asarray(obs, float), probs))
    return {"probs": probs.tolist(), "q_fc": q_fc.tolist(), "q_obs": q_obs.tolist()}


def apply_qm(x, table: dict, floor: float = 0.0) -> np.ndarray:
    """Map forecasts through the table; flat stretches of q_fc (ties, e.g. many zeros) use their mean q_obs;
    beyond the top fitted forecast quantile keep the top shift (q_obs - q_fc)."""
    x = np.asarray(x, dtype=float)
    q_fc, q_obs = np.asarray(table["q_fc"]), np.asarray(table["q_obs"])
    uq, inv = np.unique(q_fc, return_inverse=True)
    uo = np.bincount(inv, weights=q_obs) / np.bincount(inv)
    out = np.interp(x, uq, uo) if len(uq) > 1 else np.full_like(x, uo[0])
    top = x > uq[-1]
    out[top] = x[top] + (uo[-1] - uq[-1])
    return np.maximum(out, floor)


def tier_map(obs, fc, thr: float) -> dict:
    """Forecast value with the same exceedance frequency as ``obs >= thr`` (F_fc^-1(F_obs(thr)))."""
    obs, fc = np.asarray(obs, float), np.asarray(fc, float)
    p_exc = float((obs >= thr).mean()) if len(obs) else np.nan
    n_obs = int((obs >= thr).sum())
    fc_thr = float(np.quantile(fc, 1 - p_exc)) if n_obs > 0 else np.nan
    return {"threshold": thr, "n": len(obs), "n_obs_exceed": n_obs, "n_fc_exceed": int((fc >= thr).sum()),
            "p_obs_exceed": p_exc, "fc_equiv_threshold": fc_thr}


# ---------------------------------------------------------------- run
def _group_scores(pairs: pd.DataFrame) -> pd.DataFrame:
    keys = ["station", "model", "variable", "lead"]
    allp = pairs.groupby(keys).apply(continuous_scores, include_groups=False).reset_index().assign(season="all")
    bys = pairs.groupby(keys + ["season"]).apply(continuous_scores, include_groups=False).reset_index()
    out = pd.concat([allp, bys], ignore_index=True)
    out["station_name"] = out["station"].map(STATIONS)
    return out


def contingency_table(pairs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    specs = [(v, t) for v, ts in RAIN_THRESHOLDS.items() for t in ts] + [("wind", t) for t in WIND_THRESHOLDS.values()]
    for var, thr in specs:
        sub = pairs[pairs["variable"] == var]
        for (model, lead), g in sub.groupby(["model", "lead"]):
            rows.append({"station": "pooled", "model": model, "variable": var, "lead": lead, **contingency(g.obs, g.fc, thr)})
            for st, gs in g.groupby("station"):
                rows.append({"station": st, "model": model, "variable": var, "lead": lead, **contingency(gs.obs, gs.fc, thr)})
    return pd.DataFrame(rows)


def daily_max_wind(pairs: pd.DataFrame, min_hours: int = 6) -> pd.DataFrame:
    """Daily (local day) max over matched synoptic hours only, so forecast and obs see the same sample."""
    w = pairs[pairs["variable"] == "wind"].copy()
    w["day"] = (w["valid_utc"] + pd.Timedelta(hours=7)).dt.floor("D")
    g = w.groupby(["station", "model", "lead", "day"]).agg(obs=("obs", "max"), fc=("fc", "max"), k=("obs", "size")).reset_index()
    return g[g["k"] >= min_hours]


def wind_tail(pairs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    w = pairs[pairs["variable"] == "wind"]
    yagi = (w["valid_utc"] >= YAGI[0]) & (w["valid_utc"] < YAGI[1])
    for label, sub in (("all", w), ("no_yagi", w[~yagi])):
        for (st, model, lead), g in sub.groupby(["station", "model", "lead"]):
            for name, thr in WIND_THRESHOLDS.items():
                rows.append({"sample": label, "station": st, "model": model, "lead": lead, "tier": name, **tier_map(g.obs, g.fc, thr)})
        for (model, lead), g in sub.groupby(["model", "lead"]):
            for name, thr in WIND_THRESHOLDS.items():
                rows.append({"sample": label, "station": "pooled", "model": model, "lead": lead, "tier": name, **tier_map(g.obs, g.fc, thr)})
    q = []
    for (st, model, lead), g in w.groupby(["station", "model", "lead"]):
        for p in (0.5, 0.9, 0.95, 0.99, 0.995, 0.999):
            q.append({"station": st, "model": model, "lead": lead, "prob": p, "q_obs": g.obs.quantile(p),
                      "q_fc": g.fc.quantile(p), "n": len(g)})
    return pd.DataFrame(rows), pd.DataFrame(q)


def evaluate_preregistered(pairs: pd.DataFrame, prereg: dict) -> dict:
    """Fit on valid < SPLIT, test on >= SPLIT; verdict per (rule, candidate) using the registered thresholds."""
    out = {"rules": [], "continuous_secondary": None}
    min_events = 30
    for rule in prereg["primary_rules"]:
        var, model, thr, leads = rule["variable"], rule["model"], rule["threshold"], prereg["leads"][rule["id"]]
        sub = pairs[(pairs["variable"] == var) & (pairs["model"] == model) & pairs["lead"].isin(leads)]
        raw_o, raw_f, corr = [], [], {"additive": [], "quantile_mapping": []}
        fits = {}
        for (st, lead), g in sub.groupby(["station", "lead"]):
            fit, test = g[g["valid_utc"] < SPLIT], g[g["valid_utc"] >= SPLIT]
            if len(fit) < 50 or test.empty:
                continue
            add = fit_additive(fit.obs, fit.fc)
            qm = fit_qm(fit.obs, fit.fc)
            fits[f"{st}_d{lead}"] = {"additive_bias": add, "n_fit": len(fit), "n_test": len(test)}
            raw_o.append(test.obs.to_numpy())
            raw_f.append(test.fc.to_numpy())
            corr["additive"].append(np.maximum(test.fc.to_numpy() - add, 0.0))
            corr["quantile_mapping"].append(apply_qm(test.fc.to_numpy(), qm))
        if not raw_o:
            out["rules"].append({**rule, "verdict": "insufficient", "reason": "no test data"})
            continue
        o, f = np.concatenate(raw_o), np.concatenate(raw_f)
        raw = contingency(o, f, thr)
        for cand, arrs in corr.items():
            c = contingency(o, np.concatenate(arrs), thr)
            if raw["obs_events"] < min_events:
                verdict, reason = "insufficient", f"obs_events {raw['obs_events']} < {min_events}"
            else:
                d_csi = (c["csi"] if not np.isnan(c["csi"]) else 0) - (raw["csi"] if not np.isnan(raw["csi"]) else 0)
                fb_ok = abs(c["freq_bias"] - 1) < abs(raw["freq_bias"] - 1)
                far_raw = raw["far"] if not np.isnan(raw["far"]) else 0.0
                far_ok = (c["far"] if not np.isnan(c["far"]) else 0.0) <= far_raw + 0.02
                passed = d_csi >= 0.05 and fb_ok and far_ok
                verdict = "go" if passed else "no-go"
                reason = f"dCSI={d_csi:+.3f} (>=0.05: {d_csi >= 0.05}); FB {raw['freq_bias']:.2f}->{c['freq_bias']:.2f} (closer to 1: {fb_ok}); FAR {raw['far']:.2f}->{c['far']:.2f} (ok: {far_ok})"
            out["rules"].append({"id": rule["id"], "model": model, "variable": var, "threshold": thr, "leads": leads,
                                 "candidate": cand, "raw": raw, "corrected": c, "verdict": verdict, "reason": reason})
    # continuous secondary: additive wind, best_match, leads 1-3, >=10 % MAE cut at >=4/5 stations
    w = pairs[(pairs["variable"] == "wind") & (pairs["model"] == "best_match") & pairs["lead"].isin([1, 2, 3])]
    per = {}
    for st, g in w.groupby("station"):
        maes_raw, maes_cor = [], []
        for lead, gl in g.groupby("lead"):
            fit, test = gl[gl["valid_utc"] < SPLIT], gl[gl["valid_utc"] >= SPLIT]
            if len(fit) < 50 or test.empty:
                continue
            add = fit_additive(fit.obs, fit.fc)
            maes_raw.append(np.abs(test.fc - test.obs).to_numpy())
            maes_cor.append(np.abs(np.maximum(test.fc - add, 0) - test.obs).to_numpy())
        if maes_raw:
            r, c = np.concatenate(maes_raw).mean(), np.concatenate(maes_cor).mean()
            per[st] = {"mae_raw": r, "mae_additive": c, "reduction": 1 - c / r}
    k = sum(v["reduction"] >= 0.10 for v in per.values())
    out["continuous_secondary"] = {"per_station": per, "stations_ge_10pct": k,
                                   "verdict": "go" if k >= 4 else "no-go"}
    return out


def model_identity(fc: dict[tuple[str, str], pd.DataFrame], ref: str = "best_match", atol: float = 1e-6) -> pd.DataFrame:
    """Share of hours where ``ref`` equals another model (which model best_match actually serves here)."""
    rows = []
    for (st, model), f in fc.items():
        if model == ref or (st, ref) not in fc:
            continue
        r = fc[(st, ref)]
        common = r.index.intersection(f.index)
        for col in r.columns:
            a, b = r.loc[common, col], f.loc[common, col]
            ok = a.notna() & b.notna()
            if ok.any():
                rows.append({"station": st, "ref": ref, "other": model, "column": col, "n": int(ok.sum()),
                             "equal_share": float((np.abs(a[ok] - b[ok]) <= atol).mean())})
    return pd.DataFrame(rows)


def figures(scores: pd.DataFrame, cont: pd.DataFrame, pairs: pd.DataFrame, out: Path) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    made = []
    s = scores[scores["season"] == "all"]
    for metric in ("mae", "bias"):
        fig, axes = plt.subplots(len(MODELS), 6, figsize=(22, 10), sharex=True)
        for i, model in enumerate(MODELS):
            for j, var in enumerate(("t2m", "rh", "wind", "rain6h", "rain24h", "rain72h")):
                ax = axes[i, j]
                for st, g in s[(s.model == model) & (s.variable == var)].groupby("station"):
                    ax.plot(g["lead"], g[metric], marker="o", label=STATIONS[st])
                if metric == "bias":
                    ax.axhline(0, color="grey", lw=0.8)
                ax.set_title(f"{model} · {var}", fontsize=9)
                if j == 0:
                    ax.set_ylabel(metric)
        axes[0, 0].legend(fontsize=7)
        for ax in axes[-1]:
            ax.set_xlabel("lead day")
        fig.tight_layout()
        name = f"fig_{metric}_by_lead.png"
        fig.savefig(out / name, dpi=110)
        plt.close(fig)
        made.append(name)
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), sharey=True)
    for ax, (var, thr) in zip(axes, (("rain6h", 10.0), ("rain24h", 50.0), ("wind", 10.8))):
        c = cont[(cont.station == "pooled") & (cont.variable == var) & (cont.threshold == thr)]
        for model, g in c.groupby("model"):
            ax.plot(g["lead"], g["csi"], marker="o", label=f"{model} CSI")
            ax.plot(g["lead"], g["pod"], ls="--", marker=".", label=f"{model} POD")
        ax.set_title(f"pooled {var} >= {thr:g}")
        ax.set_xlabel("lead day")
    axes[0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out / "fig_contingency_by_lead.png", dpi=110)
    plt.close(fig)
    made.append("fig_contingency_by_lead.png")
    fig, axes = plt.subplots(1, 5, figsize=(22, 4.5))
    w = pairs[(pairs.variable == "wind") & (pairs.lead == 1)]
    probs = np.concatenate([np.linspace(0.5, 0.99, 50), [0.995, 0.999]])
    for ax, st in zip(axes, STATIONS):
        for model in MODELS:
            g = w[(w.station == st) & (w.model == model)]
            if len(g):
                ax.plot(g.fc.quantile(probs), g.obs.quantile(probs), marker=".", label=model)
        lim = [0, 25]
        ax.plot(lim, lim, color="grey", lw=0.8)
        for thr in (KMH35_MS, 10.8, 17.2):
            ax.axhline(thr, color="red", lw=0.5, ls=":")
        ax.set_title(f"{STATIONS[st]} wind QQ (lead 1, p>=0.5)", fontsize=9)
        ax.set_xlabel("forecast m/s")
    axes[0].set_ylabel("SYNOP obs m/s")
    axes[0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out / "fig_wind_qq_lead1.png", dpi=110)
    plt.close(fig)
    made.append("fig_wind_qq_lead1.png")
    return made


def correction_config(verdicts: dict, pairs: pd.DataFrame, run: str) -> dict:
    """Versioned, inactive config.  Parameters only for (rule, candidate) pairs that passed; fit on all data."""
    entries = []
    for r in verdicts["rules"]:
        if r.get("verdict") != "go":
            continue
        sub = pairs[(pairs.variable == r["variable"]) & (pairs.model == r["model"])]
        params = {}
        for (st, lead), g in sub.groupby(["station", "lead"]):
            key = f"{st}_d{lead}"
            params[key] = ({"additive_bias": fit_additive(g.obs, g.fc)} if r["candidate"] == "additive"
                           else {"qm": fit_qm(g.obs, g.fc)})
        entries.append({"rule": r["id"], "variable": r["variable"], "model": r["model"], "candidate": r["candidate"],
                        "params": params})
    decisions = [{"rule": r["id"], "candidate": r.get("candidate"), "verdict": r["verdict"], "reason": r["reason"]}
                 for r in verdicts["rules"]]
    return {"name": "weather_bias_correction", "version": "v0", "active": False,
            "status": "proposal only; weather is observation-only and must not drive alerts (AGENTS.md rule 4)",
            "source_run": run, "preregistration": "experiments/wx_bias_preregistration.json",
            "scope": "SYNOP coastal stations 48833/48826/48839/48828/48834; transfer to NB1 not validated",
            "decisions": decisions, "continuous_secondary": verdicts["continuous_secondary"], "corrections": entries}


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (pd.Timestamp, datetime, date)):
        return o.isoformat()
    raise TypeError(type(o))


def run(stamp: str) -> Path:
    out = paths.EXPERIMENT_OUTPUT_DIR / f"wx-bias-{stamp}"
    if out.exists():
        raise FileExistsError(out)
    src = paths.WEATHER_PREVIOUS_RUNS_DIR / DOWNLOAD_SUBDIR
    synop = load_synop()
    fc = load_forecasts(src)
    pairs = build_pairs(synop, fc)
    out.mkdir(parents=True)
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    first_valid = {f"{st}_{m}": str(f.dropna(how="all").index.min()) for (st, m), f in fc.items()}
    coverage = pairs.groupby(["station", "model", "variable", "lead"]).agg(
        n=("obs", "size"), first=("valid_utc", "min"), last=("valid_utc", "max")).reset_index()
    scores = _group_scores(pairs)
    cont = contingency_table(pairs)
    dm = daily_max_wind(pairs)
    dm_rows = []
    for (model, lead), g in dm.groupby(["model", "lead"]):
        for name, thr in WIND_THRESHOLDS.items():
            dm_rows.append({"station": "pooled", "model": model, "lead": lead, "tier": name, **contingency(g.obs, g.fc, thr)})
        for st, gs in g.groupby("station"):
            for name, thr in WIND_THRESHOLDS.items():
                dm_rows.append({"station": st, "model": model, "lead": lead, "tier": name, **contingency(gs.obs, gs.fc, thr)})
    tail, wq = wind_tail(pairs)
    verdicts = evaluate_preregistered(pairs, prereg)
    cfg = correction_config(verdicts, pairs, out.name)
    model_identity(fc).to_csv(out / "best_match_identity.csv", index=False)
    pairs.to_parquet(out / "pairs.parquet", index=False)
    coverage.to_csv(out / "coverage.csv", index=False)
    scores.to_csv(out / "scores_station_model_var_lead_season.csv", index=False)
    cont.to_csv(out / "contingency.csv", index=False)
    pd.DataFrame(dm_rows).to_csv(out / "wind_dailymax_contingency.csv", index=False)
    tail.to_csv(out / "wind_tier_mapping.csv", index=False)
    wq.to_csv(out / "wind_quantiles.csv", index=False)
    figs = figures(scores, cont, pairs, out)
    (out / "verdict.json").write_text(json.dumps(verdicts, indent=1, default=_json_default), encoding="utf-8")
    (out / "weather_bias_correction.v0.json").write_text(json.dumps(cfg, indent=1, default=_json_default), encoding="utf-8")
    (out / "preregistration.json").write_bytes(PREREG.read_bytes())
    files = sorted(p for p in out.iterdir() if p.is_file())
    manifest = {"run": out.name, "created": datetime.now(timezone.utc).isoformat(), "forecast_dir": str(src),
                "first_valid_forecast_hour": first_valid, "split": str(SPLIT), "figures": figs,
                "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("download")
    r = sub.add_parser("run")
    r.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d"))
    a = ap.parse_args(argv)
    if a.cmd == "download":
        dest = paths.WEATHER_PREVIOUS_RUNS_DIR / DOWNLOAD_SUBDIR
        dest.mkdir(parents=True, exist_ok=True)
        log = download(dest, station_coords(load_synop()))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (dest / f"manifest-{stamp}.json").write_text(json.dumps(
            {"url": PREVIOUS_RUNS_URL, "models": MODELS, "variables": hourly_names(), "stations": STATIONS,
             "period": [FETCH_START.isoformat(), FETCH_END.isoformat()], "wind_speed_unit": "ms (requested; "
             "the task said convert km/h, asking the API for m/s avoids rounding)", "log": log}, indent=1),
            encoding="utf-8")
        print(f"{sum(x['status'] == 'fetched' for x in log)} fetched, {len(log)} total")
    else:
        print(run(a.stamp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
