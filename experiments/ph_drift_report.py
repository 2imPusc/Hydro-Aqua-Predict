"""Quantify the pH probe drift of one station (research-only, read-only on the history).

Per local (Asia/Ho_Chi_Minh) day: n, median / p05 / p95 / min / max pH, share of readings
flagged by ``core.quality`` (outside PH_PLAUSIBLE_BAND, |ΔpH 60 min| > 0.5, outside the hard
PLAUSIBLE_RANGE), ``sensor_day_health`` status, and the pH–Temperature correlation (the
diurnal cycle; RL-13 found it inverted after the drift).  Also a per-period summary.

    python experiments/ph_drift_report.py <history.csv> --station 06M26042804 --output <run-dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.quality import is_in_range, ph_in_band, ph_rate_suspect, sensor_day_health  # noqa: E402

LOCAL_TZ = "Asia/Ho_Chi_Minh"


def load(path: Path, station: str) -> pd.DataFrame:
    raw = pd.read_csv(path, usecols=["device", "fetchedAt", "pH", "Temperature"])
    raw = raw[raw["device"].astype(str).eq(station)]
    raw["fetchedAt"] = pd.to_datetime(raw["fetchedAt"], utc=True)
    frame = raw.groupby("fetchedAt")[["pH", "Temperature"]].median().sort_index()
    frame["local_date"] = frame.index.tz_convert(LOCAL_TZ).date
    return frame


def flags(frame: pd.DataFrame) -> pd.DataFrame:
    ph = frame["pH"].dropna()
    out = pd.DataFrame(index=ph.index)
    out["pH"] = ph
    out["Temperature"] = frame["Temperature"].reindex(ph.index)
    out["local_date"] = frame["local_date"].reindex(ph.index)
    out["hard_range_ok"] = ph.map(lambda v: is_in_range("pH", v))
    out["out_of_band"] = ~ph.map(ph_in_band).astype(bool)
    out["rate_jump"] = ph_rate_suspect(ph).to_numpy(dtype=bool)
    out["suspect"] = out["out_of_band"] | out["rate_jump"]
    return out


def daily(flagged: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for day, grp in flagged.groupby("local_date"):
        health = sensor_day_health("pH", grp["pH"])
        temp = grp["Temperature"]
        corr = grp["pH"].corr(temp) if temp.notna().sum() > 30 else float("nan")
        rows.append({"local_date": str(day), "n": len(grp), "median": grp["pH"].median(),
                     "p05": grp["pH"].quantile(.05), "p95": grp["pH"].quantile(.95), "min": grp["pH"].min(), "max": grp["pH"].max(),
                     "daily_range": grp["pH"].max() - grp["pH"].min(),
                     "frac_out_of_band": grp["out_of_band"].mean(), "frac_rate_jump": grp["rate_jump"].mean(),
                     "frac_suspect": grp["suspect"].mean(), "frac_outside_hard_range": 1 - grp["hard_range_ok"].mean(),
                     "health": health["status"], "health_reasons": ";".join(health["reasons"]), "corr_pH_temperature": corr})
    return pd.DataFrame(rows)


def periods(flagged: pd.DataFrame, cuts: dict[str, tuple[str, str]]) -> pd.DataFrame:
    rows = []
    dates = pd.to_datetime(flagged["local_date"])
    for name, (start, end) in cuts.items():
        grp = flagged[(dates >= start) & (dates <= end)]
        if grp.empty:
            continue
        day = daily(grp)
        rows.append({"period": name, "start": start, "end": end, "days": len(day), "n": len(grp),
                     "median": grp["pH"].median(), "p05": grp["pH"].quantile(.05), "p95": grp["pH"].quantile(.95),
                     "mean_daily_range": day["daily_range"].mean(), "frac_out_of_band": grp["out_of_band"].mean(),
                     "frac_rate_jump": grp["rate_jump"].mean(), "frac_suspect": grp["suspect"].mean(),
                     "days_health_suspect_or_invalid": int((day["health"] != "OK").sum()),
                     "median_daily_corr_pH_temperature": day["corr_pH_temperature"].median()})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv", type=Path)
    parser.add_argument("--station", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--drift-start", default="2026-09-19")
    parser.add_argument("--lockbox-start", default="2026-10-10", help="first local date of the forecast lockbox (for the summary only)")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    targets = [args.output / name for name in ("ph_drift_daily.csv", "ph_drift_periods.csv", "ph_drift_manifest.json")]
    for path in targets:
        if path.exists():
            raise FileExistsError(f"refusing_to_overwrite:{path}")
    flagged = flags(load(args.csv, args.station))
    last = str(flagged["local_date"].max())
    first = str(flagged["local_date"].min())
    pre_end = (pd.Timestamp(args.drift_start) - pd.Timedelta(days=1)).date().isoformat()
    cuts = {"pre_drift": (first, pre_end), "post_drift": (args.drift_start, last),
            "post_drift_before_lockbox": (args.drift_start, (pd.Timestamp(args.lockbox_start) - pd.Timedelta(days=1)).date().isoformat()),
            "lockbox": (args.lockbox_start, last)}
    daily(flagged).to_csv(targets[0], index=False)
    periods(flagged, cuts).to_csv(targets[1], index=False)
    targets[2].write_text(json.dumps({"input": str(args.csv), "station": args.station, "periods": cuts,
                                      "rules": "core.quality: PH_PLAUSIBLE_BAND 7.0-8.6, PH_MAX_CHANGE_PER_HOUR 0.5, PLAUSIBLE_RANGE 6.0-9.5, sensor_day_health"}, indent=1), encoding="utf-8")
    print(pd.read_csv(targets[1]).to_string(index=False))


if __name__ == "__main__":
    main()
