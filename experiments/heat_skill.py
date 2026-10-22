"""How well do SST products detect hot days measured at the Cát Bà cage sensor?

Truth: sensor daily mean >= 31 C (also >= 30 C sensitivity). Predictors: OISST, Open-Meteo marine,
each raw / offset-corrected / linear-calibrated (+ ERA5 air temp), corrections fitted out-of-sample.
Forecast leads: Open-Meteo has no SST *_previous_dayN history (probed 2026-10-23), so leads 1-3 are
PERSISTENCE of the product (value known k days earlier), not model forecasts.

    python experiments/heat_skill.py --stamp 20261023
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import heat_stress as hs  # noqa: E402
from core import paths  # noqa: E402
from experiments.heat_hindcast import _latest, _longest_oisst, sensor_daily  # noqa: E402

TARGETS = {"ge31": 31.0, "ge30": 30.0}
TRAIN_END = pd.Timestamp("2026-07-31")  # split A: train <= Jul 31, test Aug 1 onward
LEADS = (1, 2, 3)
MIN_TRAIN = 15


# ---------- pure helpers ----------
def contingency(obs: np.ndarray, pred: np.ndarray) -> dict:
    obs, pred = np.asarray(obs, bool), np.asarray(pred, bool)
    h, m = int((obs & pred).sum()), int((obs & ~pred).sum())
    fa, cn = int((~obs & pred).sum()), int((~obs & ~pred).sum())
    div = lambda a, b: round(a / b, 3) if b else None  # noqa: E731
    return {"n": len(obs), "hits": h, "misses": m, "false_alarms": fa, "correct_neg": cn,
            "POD": div(h, h + m), "FAR": div(fa, h + fa), "CSI": div(h, h + m + fa), "freq_bias": div(h + fa, h + m)}


def continuous(obs: np.ndarray, est: np.ndarray) -> dict:
    d = np.asarray(est, float) - np.asarray(obs, float)
    ok = ~np.isnan(d)
    if ok.sum() < 3:
        return {"bias_c": None, "MAE_c": None, "RMSE_c": None, "r": None}
    r = np.corrcoef(np.asarray(obs, float)[ok], np.asarray(est, float)[ok])[0, 1] if np.std(np.asarray(est, float)[ok]) > 0 else np.nan
    return {"bias_c": round(float(d[ok].mean()), 3), "MAE_c": round(float(np.abs(d[ok]).mean()), 3),
            "RMSE_c": round(float(np.sqrt((d[ok] ** 2).mean())), 3), "r": None if np.isnan(r) else round(float(r), 3)}


def fit_offset(sensor: np.ndarray, product: np.ndarray) -> float:
    return float(np.median(np.asarray(sensor) - np.asarray(product)))


def fit_linear(sensor: np.ndarray, *features: np.ndarray) -> np.ndarray:
    """Least squares sensor ~ a + sum(b_i * feature_i); returns [a, b1, ...]."""
    x = np.column_stack([np.ones(len(sensor)), *features])
    return np.linalg.lstsq(x, np.asarray(sensor, float), rcond=None)[0]


def apply_linear(coef: np.ndarray, *features: np.ndarray) -> np.ndarray:
    return coef[0] + sum(c * np.asarray(f, float) for c, f in zip(coef[1:], features))


def best_threshold(obs: np.ndarray, value: np.ndarray, target_c: float) -> float:
    """Threshold on `value` maximising CSI (ties: closest to target_c); grid 0.1 C."""
    obs, value = np.asarray(obs, bool), np.asarray(value, float)
    grid = np.round(np.arange(np.floor(np.nanmin(value) * 10) / 10 - 0.1, np.nanmax(value) + 0.2, 0.1), 1)
    best = (-1.0, 0.0, target_c)
    for t in grid:
        c = contingency(obs, value >= t)["CSI"] or 0.0
        key = (c, -abs(t - target_c))
        if key > best[:2]:
            best = (c, -abs(t - target_c), float(t))
    return best[2]


def folds(index: pd.DatetimeIndex, scheme: str):
    """Yield (name, train_mask, test_mask). 'split' = Jun-Jul/Aug-Oct; 'lomo' = leave-one-month-out (May joins Jun)."""
    if scheme == "split":
        yield "Aug-Oct", np.asarray(index <= TRAIN_END), np.asarray(index > TRAIN_END)
        return
    month = pd.Series(np.where(index.month == 5, 6, index.month), index=index)
    for m in sorted(month.unique()):
        te = (month == m).to_numpy()
        yield f"m{m:02d}", ~te, te


def oof_predict(df: pd.DataFrame, product: str, method: str, scheme: str, target_c: float) -> pd.DataFrame:
    """Out-of-sample estimate and alarm per day; each day is predicted by a model fitted without it."""
    out = pd.DataFrame(index=df.index, columns=["est", "alarm"], dtype=float)
    thr_log = []
    # lead products only know the air temperature of the issue day (k days earlier), never the target day's
    air_col = "air_lag" + product.rsplit("_lag", 1)[1] if "_lag" in product else "air"
    for name, tr, te in folds(df.index, scheme):
        d_tr = df[tr].dropna(subset=["sensor", product, air_col])
        if len(d_tr) < MIN_TRAIN:
            continue
        s, p, a = d_tr["sensor"].to_numpy(), d_tr[product].to_numpy(), d_tr[air_col].to_numpy()
        x_te, a_te = df.loc[te, product].to_numpy(float), df.loc[te, air_col].to_numpy(float)
        tuned = method.endswith("_tuned")
        base = method.removesuffix("_tuned")
        if base == "raw":
            est_tr, est_te = p, x_te
        elif base == "offset":
            o = fit_offset(s, p); est_tr, est_te = p + o, x_te + o
        elif base == "lin":
            c = fit_linear(s, p); est_tr, est_te = apply_linear(c, p), apply_linear(c, x_te)
        elif base == "lin_air":
            c = fit_linear(s, p, a); est_tr, est_te = apply_linear(c, p, a), apply_linear(c, x_te, a_te)
        else:
            raise ValueError(method)
        thr = best_threshold(s >= target_c, est_tr, target_c) if tuned else target_c
        thr_log.append({"fold": name, "threshold_on_estimate": thr, "n_train": len(d_tr)})
        out.loc[te, "est"] = est_te
        out.loc[te, "alarm"] = np.where(np.isnan(est_te), np.nan, (est_te >= thr).astype(float))
    out.attrs["thresholds"] = thr_log
    return out


# ---------- IO ----------
def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_inputs():
    oisst_file, marine_file, era5_file = _longest_oisst(), _latest("sst/openmeteo_marine_nb1_*.csv"), _latest("era5/era5_nb1_*.csv")
    oisst = pd.read_csv(oisst_file, parse_dates=["time"]).set_index("time")["sst"]
    oisst.index = oisst.index.tz_convert("UTC").normalize().tz_localize(None)
    marine = hs.daily_from_hourly(pd.read_csv(marine_file, parse_dates=["time"]).set_index("time")["sea_surface_temperature"])
    era5 = pd.read_csv(era5_file, parse_dates=["time"]).set_index("time")
    air = hs.daily_from_hourly(era5["temperature_2m"])
    return (oisst_file, marine_file, era5_file), oisst, marine, air


def build_frame(sensor: pd.Series, oisst: pd.Series, marine: pd.Series, air: pd.Series) -> pd.DataFrame:
    idx = pd.date_range(sensor.index.min(), sensor.index.max(), freq="D")
    df = pd.DataFrame({"sensor": sensor.reindex(idx), "oisst": oisst.reindex(idx), "marine": marine.reindex(idx), "air": air.reindex(idx)})
    for k in LEADS:  # persistence: product value as known k days before the target day
        df[f"air_lag{k}"] = air.reindex(idx - pd.Timedelta(days=k)).to_numpy()
        for p, s in (("oisst", oisst), ("marine", marine)):
            df[f"{p}_lag{k}"] = s.reindex(idx - pd.Timedelta(days=k)).to_numpy()
    df["sensor_lag1"] = sensor.reindex(idx - pd.Timedelta(days=1)).to_numpy()  # benchmark: sensor persistence
    return df


def evaluate(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows, daily, thr_rows = [], df.copy(), []
    products = ["oisst", "marine"] + [f"{p}_lag{k}" for k in LEADS for p in ("oisst", "marine")]
    methods = ["raw", "raw_tuned", "offset", "offset_tuned", "lin", "lin_tuned", "lin_air", "lin_air_tuned"]
    for scheme in ("split", "lomo"):
        for tname, tc in TARGETS.items():
            obs_all = df["sensor"] >= tc
            for product in products:
                for method in methods:
                    res = oof_predict(df, product, method, scheme, tc)
                    thr_rows += [{"scheme": scheme, "target": tname, "product": product, "method": method, **t} for t in res.attrs["thresholds"]]
                    ok = df["sensor"].notna() & res["alarm"].notna()
                    if scheme == "split":
                        ok &= df.index > TRAIN_END
                    if ok.sum() == 0:
                        continue
                    rows.append({"scheme": scheme, "target": tname, "product": product, "method": method,
                                 "n_pos": int(obs_all[ok].sum()),
                                 **contingency(obs_all[ok].to_numpy(), res.loc[ok, "alarm"].to_numpy(bool)),
                                 **continuous(df.loc[ok, "sensor"].to_numpy(), res.loc[ok, "est"].to_numpy())})
                    if tname == "ge31" and product in ("oisst", "marine"):
                        daily[f"{scheme}_{product}_{method}_est"] = res["est"]
            # benchmark: yesterday's sensor mean persists (not a product; operationally needs a live sensor)
            ok = df["sensor"].notna() & df["sensor_lag1"].notna() & ((df.index > TRAIN_END) if scheme == "split" else True)
            rows.append({"scheme": scheme, "target": tname, "product": "sensor_lag1", "method": "persistence", "n_pos": int(obs_all[ok].sum()),
                         **contingency(obs_all[ok].to_numpy(), (df.loc[ok, "sensor_lag1"] >= tc).to_numpy()),
                         **continuous(df.loc[ok, "sensor"].to_numpy(), df.loc[ok, "sensor_lag1"].to_numpy())})
    return pd.DataFrame(rows), daily, pd.DataFrame(thr_rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stamp", default="20261023")
    args = parser.parse_args(argv)
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / f"heat-skill-{args.stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    files, oisst, marine, air = load_inputs()
    sensor = sensor_daily()
    df = build_frame(sensor, oisst, marine, air)
    metrics, daily, thr = evaluate(df)
    stress = hs.daily_heat_stress(sensor)
    metrics.to_csv(run_dir / "metrics.csv", index=False)
    thr.to_csv(run_dir / "thresholds.csv", index=False)
    daily.join(stress[["alert_level", "run_days"]]).to_csv(run_dir / "daily.csv", index_label="date")
    manifest = {
        "run": run_dir.name, "split_train_end": str(TRAIN_END.date()), "lomo": "leave-one-month-out, May folded into June",
        "sensor_days": int(sensor.notna().sum()), "sensor_first": str(sensor.index.min().date()), "sensor_last": str(sensor.index.max().date()),
        "sensor_days_ge31": int((sensor >= 31).sum()), "sensor_days_ge30": int((sensor >= 30).sum()), "sensor_days_ge33": int((sensor >= 33).sum()),
        "days_alert_level_ge1": int((stress["alert_level"] >= 1).sum()), "days_alert_level_ge2": int((stress["alert_level"] >= 2).sum()),
        "train_days": int((sensor.index <= TRAIN_END).sum()), "test_days": int((sensor.index > TRAIN_END).sum()),
        "train_days_ge31": int((sensor[sensor.index <= TRAIN_END] >= 31).sum()), "test_days_ge31": int((sensor[sensor.index > TRAIN_END] >= 31).sum()),
        "alert_level_ge1_equals_ge31": bool(((stress["alert_level"] >= 1) == (stress["temp_c"] >= 31)).all()),
        "leads": "persistence of product (known k days earlier); Open-Meteo marine/previous-runs SST *_previous_dayN returned null for 2026-05..10, so no archived forecast SST",
        "inputs": {p.name: _sha(p) for p in files}, "source": "reanalysis/analysis hindcast vs sensor; theory-only, not used by alerts",
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
