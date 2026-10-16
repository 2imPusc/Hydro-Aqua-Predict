"""Loader for the Texas Water Development Board (TWDB) coastal sonde network -- H4.2.

Source: https://www.waterdatafortexas.org/coastal (REST API, CSV, no key).
Raw files live under ``paths.FOREIGN_DATA_DIR / "texas_twdb"`` (gitignored,
write-once: an existing file is never re-downloaded or overwritten).

What this module does
---------------------
* ``download`` (CLI): station list + per-station parameter metadata, a daily-mean
  coverage scan (default API binning), then raw ``binning=min`` CSVs for every
  station x parameter x year that the scan shows has data.
* Parses raw CSVs. Timestamps carry the America/Chicago offset (-0600 / -0500,
  DST); they are converted to fixed **local standard time (CST, UTC-6)**.
* QC (the CSV has no per-value flag column; the provider only removes obvious
  outliers, "provisional"): we apply the provider's own per-parameter limits from
  ``/api/stations/{code}/parameters``:
    - range: value outside [MPRMIN, MPRMAX] or outside a physical sanity band
      (Temp 0-40 C, Sal 0-45 psu, DO 0-20 mg/L) -> ``range``;
    - spike: |x - median(x[i-1], x[i], x[i+1])| > THRSHLD_LOW (the provider's
      "suspect" step; Temp 10 C, Sal 10 psu, DO 3 mg/L) when both neighbours lie
      within 2 h -> ``spike``;
    - flatline: >= REP_CNT_FAIL consecutive identical values (compared after
      rounding to REP_TOLERANCE decimals; Temp 8, Sal 12, DO 5 samples) ->
      ``flatline``. Salinity <= 1 psu is exempt (fresh delta water legitimately
      sits at the sensor floor).
  Only ``ok`` values are kept.
* Hourly means, hour-start labelled, in LST. **Cadence-aware minimum count**: the
  network logged hourly until ~2019-2020 and every 15 min afterwards. Where the
  native cadence (median spacing per station x variable x year) is < 60 min an
  hour needs >= 2 good values (common H4 protocol); where it is hourly the single
  native reading is accepted (protocol deviation, documented; ``n_obs`` is kept).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import paths  # noqa: E402

TWDB_DIR = paths.FOREIGN_DATA_DIR / "texas_twdb"
RAW_DIR = TWDB_DIR / "raw"
META_DIR = RAW_DIR / "meta"
DAILY_DIR = RAW_DIR / "daily_scan"
MIN_DIR = RAW_DIR / "min"
DERIVED_DIR = TWDB_DIR / "derived"

API = "https://waterdatafortexas.org/coastal/api"
USER_AGENT = "Hydro-Aqua-Predict research (academic)"
LST_OFFSET_H = -6  # CST, no DST
YEARS = range(2008, 2026)

# evaluation key (matches nerrs_reliability.TOLERANCES) -> TWDB parameter code
PARAMETERS = {
    "Temp": "water_temperature",
    "Sal": "seawater_salinity",
    "DO_mgl": "water_dissolved_oxygen_concentration",
}
PHYSICAL_RANGE = {"Temp": (0.0, 40.0), "Sal": (0.0, 45.0), "DO_mgl": (0.0, 20.0)}
FLATLINE_EXEMPT_BELOW = {"Sal": 1.0}
# Fallback QC limits (provider values as published 2026-10-17) if a parameters file is missing.
DEFAULT_QC = {
    "Temp": {"MPRMIN": -5.0, "MPRMAX": 50.0, "THRSHLD_LOW": 10.0, "REP_TOLERANCE": 3, "REP_CNT_FAIL": 8},
    "Sal": {"MPRMIN": 0.001, "MPRMAX": 100.0, "THRSHLD_LOW": 10.0, "REP_TOLERANCE": 3, "REP_CNT_FAIL": 12},
    "DO_mgl": {"MPRMIN": 0.01, "MPRMAX": 50.0, "THRSHLD_LOW": 3.0, "REP_TOLERANCE": 3, "REP_CNT_FAIL": 5},
}

# Systems with hourly (or finer) sonde records 2008-2025. LCRA Matagorda sites
# (6984/6985/6990/6996/MB02/NCM4) are excluded: the API serves them as daily values only.
STATIONS = {
    "Guadalupe": ["DELT", "SANT", "MOSQ", "CHKN", "CONT", "SOPA"],
    "Trinity-Galveston": ["TRIN", "FISH", "MIDG", "BOLI", "HANN", "WESTB"],
    "Colorado-Lavaca": ["LAVC", "MATA", "EMB", "TPAL"],
    "Sabine": ["SAB1", "SAB2"],
}
SYSTEM_OF = {code: system for system, codes in STATIONS.items() for code in codes}


# ---------------------------------------------------------------- download
def http_get(url: str, retries: int = 5, pause: float = 0.4) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=120) as resp:
                body = resp.read()
            time.sleep(pause)
            return body
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == retries - 1:
                raise
        time.sleep(2 ** attempt * 2)
    raise RuntimeError("unreachable")


def write_once(path: Path, body: bytes) -> bool:
    """Write ``body`` to ``path`` only if it does not exist yet. Returns True if written."""
    path = Path(path)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    with open(part, "wb") as handle:
        handle.write(body)
    if path.exists():  # raced -- keep the existing file
        part.unlink()
        return False
    os.rename(part, path)
    return True


def data_url(code: str, parameter: str, start: str, end: str, binning: str | None) -> str:
    url = f"{API}/stations/{code}/data/{parameter}?start_date={start}&end_date={end}&output_format=csv"
    return url + (f"&binning={binning}" if binning else "")


def daily_scan_path(code: str, parameter: str) -> Path:
    return DAILY_DIR / f"{code}__{parameter}__daily_{YEARS[0]}-{YEARS[-1]}.csv"


def raw_path(code: str, parameter: str, year: int) -> Path:
    return MIN_DIR / code / f"{code}__{parameter}__{year}.csv"


def years_with_data(daily_csv: Path) -> list[int]:
    series = parse_csv(daily_csv)
    return sorted({int(y) for y in series.index.year if YEARS[0] <= y <= YEARS[-1]})


def download(log=print) -> dict:
    stamp = date.today().isoformat()
    stations_file = META_DIR / f"stations_{stamp}.json"
    if not list(META_DIR.glob("stations_*.json")):
        write_once(stations_file, http_get(f"{API}/stations"))
    counts = {"written": 0, "skipped": 0}
    for code in SYSTEM_OF:
        if write_once(META_DIR / f"parameters_{code}.json", http_get(f"{API}/stations/{code}/parameters")):
            counts["written"] += 1
        for parameter in PARAMETERS.values():
            scan = daily_scan_path(code, parameter)
            if write_once(scan, http_get(data_url(code, parameter, f"{YEARS[0]}-01-01", f"{YEARS[-1]}-12-31", None))):
                counts["written"] += 1
            for year in years_with_data(scan):
                target = raw_path(code, parameter, year)
                if target.exists():
                    counts["skipped"] += 1
                    continue
                write_once(target, http_get(data_url(code, parameter, f"{year}-01-01", f"{year}-12-31", "min")))
                counts["written"] += 1
                log(f"{code} {parameter} {year}")
    return counts


# ---------------------------------------------------------------- parsing
def parse_csv(path: Path) -> pd.Series:
    """TWDB CSV ('#' header, datetime with UTC offset, value) -> Series indexed by naive LST (UTC-6)."""
    frame = pd.read_csv(path, comment="#")
    if frame.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], name="time_lst"), name="value")
    utc = pd.to_datetime(frame["datetime"], utc=True, format="ISO8601")
    lst = (utc + pd.Timedelta(hours=LST_OFFSET_H)).dt.tz_localize(None)
    series = pd.Series(pd.to_numeric(frame["value"], errors="coerce").to_numpy(),
                       index=pd.DatetimeIndex(lst, name="time_lst"), name="value")
    series = series[~series.index.duplicated(keep="first")].sort_index()
    return series


def load_qc_limits(code: str, meta_dir: Path = META_DIR) -> dict:
    limits = {k: dict(v) for k, v in DEFAULT_QC.items()}
    path = Path(meta_dir) / f"parameters_{code}.json"
    if not path.exists():
        return limits
    by_code = {p["code"]: p for p in json.loads(path.read_text(encoding="utf-8"))}
    for var, parameter in PARAMETERS.items():
        if parameter in by_code:
            for key in limits[var]:
                if by_code[parameter].get(key) is not None:
                    limits[var][key] = by_code[parameter][key]
    return limits


# ---------------------------------------------------------------- QC
def _run_lengths(values: np.ndarray) -> np.ndarray:
    """Length of the run of identical consecutive values each element belongs to."""
    n = len(values)
    if n == 0:
        return np.zeros(0, int)
    change = np.r_[True, values[1:] != values[:-1]]
    run_id = np.cumsum(change)
    lengths = np.bincount(run_id)
    return lengths[run_id]


def qc_series(series: pd.Series, var: str, limits: dict) -> pd.DataFrame:
    """Return frame(value, flag) with flag in {ok, missing, range, spike, flatline}."""
    lim = limits[var]
    s = series.dropna().sort_index()
    v = s.to_numpy(float)
    flag = np.full(len(v), "ok", dtype=object)
    lo, hi = PHYSICAL_RANGE[var]
    bad_range = (v < max(lo, lim["MPRMIN"])) | (v > min(hi, lim["MPRMAX"]))
    flag[bad_range] = "range"

    keep = ~bad_range
    vk, tk = v[keep], s.index[keep]
    spike = np.zeros(len(vk), bool)
    if len(vk) >= 3 and lim.get("THRSHLD_LOW") is not None:
        triple = np.vstack([vk[:-2], vk[1:-1], vk[2:]])
        med = np.median(triple, axis=0)
        gap_prev = (tk[1:-1] - tk[:-2]) <= pd.Timedelta(hours=2)
        gap_next = (tk[2:] - tk[1:-1]) <= pd.Timedelta(hours=2)
        spike[1:-1] = (np.abs(vk[1:-1] - med) > float(lim["THRSHLD_LOW"])) & np.asarray(gap_prev) & np.asarray(gap_next)
    flat = np.zeros(len(vk), bool)
    if lim.get("REP_CNT_FAIL"):
        rounded = np.round(vk, int(lim.get("REP_TOLERANCE") or 3))
        flat = _run_lengths(rounded) >= int(lim["REP_CNT_FAIL"])
        if var in FLATLINE_EXEMPT_BELOW:
            flat &= vk > FLATLINE_EXEMPT_BELOW[var]
    sub = np.where(spike, "spike", np.where(flat, "flatline", "ok"))
    flag[np.flatnonzero(keep)] = sub
    return pd.DataFrame({"value": v, "flag": flag}, index=s.index)


def native_cadence_minutes(index: pd.DatetimeIndex) -> float:
    if len(index) < 3:
        return np.nan
    return float(pd.Series(index).diff().dropna().median() / pd.Timedelta(minutes=1))


def hourly_from_good(good: pd.Series, cadence_min: float) -> pd.DataFrame:
    """Hour-start-labelled mean + count; min count 2 if cadence < 60 min else 1."""
    min_obs = 2 if np.isfinite(cadence_min) and cadence_min < 60 else 1
    grouped = good.groupby(good.index.floor("h"))
    out = pd.DataFrame({"value": grouped.mean(), "n_obs": grouped.count()})
    out = out[out["n_obs"] >= min_obs]
    out["cadence_min"] = cadence_min
    return out


def value_resolution(values: pd.Series) -> float:
    """Coarsest decimal step that >= 95 % of values sit on (1.0, 0.1, 0.01 or 0.001)."""
    v = values.dropna().to_numpy(float)
    if len(v) == 0:
        return np.nan
    for step in (1.0, 0.1, 0.01):
        if np.mean(np.abs(v / step - np.round(v / step)) < 1e-6) >= 0.95:
            return step
    return 0.001


def load_hourly(stations=None, variables=PARAMETERS, data_dir: Path = RAW_DIR, years=None
                ) -> tuple[pd.DataFrame, pd.DataFrame, list[Path]]:
    """Long hourly table (station, variable, time_lst, value, n_obs, cadence_min) + QC summary + files used.

    ``years`` restricts the files read. NB: from ~2020 the API serves the 15-min
    record quantised (salinity to 1 psu, temperature to 0.1 C); ``resolution`` in
    the QC summary records this per file.
    """
    stations = list(stations or SYSTEM_OF)
    data_dir = Path(data_dir)
    frames, qc_rows, used = [], [], []
    for code in stations:
        limits = load_qc_limits(code, data_dir / "meta")
        for var in variables:
            parameter = PARAMETERS[var]
            for path in sorted((data_dir / "min" / code).glob(f"{code}__{parameter}__*.csv")):
                year = int(path.stem.rsplit("__", 1)[1])
                if years is not None and year not in set(years):
                    continue
                raw = parse_csv(path)
                raw = raw[raw.index.year == year]  # guard against boundary rows
                used.append(path)
                if raw.empty:
                    continue
                checked = qc_series(raw, var, limits)
                good = checked.loc[checked["flag"] == "ok", "value"]
                cadence = native_cadence_minutes(raw.index)
                hourly = hourly_from_good(good, cadence)
                tally = checked["flag"].value_counts()
                qc_rows.append({"station": code, "variable": var, "year": year, "n_raw": int(raw.notna().sum()),
                                **{f"n_{k}": int(tally.get(k, 0)) for k in ("range", "spike", "flatline", "ok")},
                                "cadence_min": cadence, "resolution": value_resolution(raw), "hours_kept": int(len(hourly)),
                                "hours_single_obs": int((hourly["n_obs"] == 1).sum())})
                if not hourly.empty:
                    frames.append(hourly.reset_index(names="time_lst").assign(station=code, variable=var))
    cols = ["station", "variable", "time_lst", "value", "n_obs", "cadence_min"]
    long = pd.concat(frames, ignore_index=True)[cols] if frames else pd.DataFrame(columns=cols)
    long = long.drop_duplicates(["station", "variable", "time_lst"]).sort_values(cols[:3]).reset_index(drop=True)
    return long, pd.DataFrame(qc_rows), used


def station_table(meta_dir: Path = META_DIR, stations=None) -> pd.DataFrame:
    files = sorted(Path(meta_dir).glob("stations_*.json"))
    if not files:
        raise FileNotFoundError(f"no stations_*.json in {meta_dir}; run `python experiments/twdb_load.py download`")
    records = json.loads(files[-1].read_text(encoding="utf-8"))
    rows = [{"station": r["station_code"], "system": SYSTEM_OF.get(r["station_code"]),
             "lat": float(r["coordinates"][1]), "lon": float(r["coordinates"][0]),
             "agency": r["agency"]["abbreviation"], "status": r["stationstatus"]["name"],
             "estuary": r["estuary"], "bay": r["bay"], "description": (r["description"] or "").strip()}
            for r in records if r["station_code"] in set(stations or SYSTEM_OF)]
    return pd.DataFrame(rows).sort_values(["system", "station"]).reset_index(drop=True)


# ---------------------------------------------------------------- rain (ERA5 via Open-Meteo)
def load_or_fetch_rain_hourly(name: str, lat: float, lon: float, start: str, end: str,
                              derived_dir: Path = DERIVED_DIR, allow_fetch: bool = True) -> tuple[pd.Series | None, dict]:
    """Hourly ERA5 precipitation (mm) at a point, indexed by LST hour start. Write-once cache."""
    path = Path(derived_dir) / f"open_meteo_era5_precip_hourly_{name}_{lat:.3f}_{lon:.3f}_{start}_{end}.csv"
    url = ("https://archive-api.open-meteo.com/v1/archive?"
           f"latitude={lat:.3f}&longitude={lon:.3f}&start_date={start}&end_date={end}"
           "&hourly=precipitation&models=era5&timezone=GMT")
    meta = {"file": str(path), "url": url}
    if not path.exists():
        if not allow_fetch:
            return None, {**meta, "status": "absent_no_fetch"}
        payload = json.loads(http_get(url, pause=1.0).decode("utf-8"))
        frame = pd.DataFrame({"time_utc": payload["hourly"]["time"], "precip_mm": payload["hourly"]["precipitation"]})
        write_once(path, frame.to_csv(index=False).encode("utf-8"))
        write_once(path.with_suffix(".json"), json.dumps(
            {"url": url, "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "grid_lat": payload.get("latitude"), "grid_lon": payload.get("longitude")}, indent=2).encode("utf-8"))
    frame = pd.read_csv(path)
    index = pd.to_datetime(frame["time_utc"]) + pd.Timedelta(hours=LST_OFFSET_H)
    rain = pd.Series(frame["precip_mm"].astype(float).to_numpy(), index=pd.DatetimeIndex(index, name="time_lst"))
    return rain, {**meta, "status": "ok"}


def write_raw_manifest(twdb_dir: Path = TWDB_DIR) -> Path:
    """Write-once CSV (relative path, bytes, sha256) of every file under raw/ and derived/."""
    import hashlib

    rows = []
    for path in sorted(p for sub in ("raw", "derived") for p in (Path(twdb_dir) / sub).rglob("*") if p.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append({"file": path.relative_to(twdb_dir).as_posix(), "bytes": path.stat().st_size, "sha256": digest})
    target = Path(twdb_dir) / f"raw_manifest_{date.today().isoformat()}.csv"
    if not write_once(target, pd.DataFrame(rows).to_csv(index=False).encode("utf-8")):
        raise FileExistsError(target)
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="TWDB coastal sonde loader")
    parser.add_argument("command", choices=["download", "summary", "manifest"])
    args = parser.parse_args(argv)
    if args.command == "download":
        print(download())
    elif args.command == "manifest":
        print(write_raw_manifest())
    else:
        long, qc, used = load_hourly()
        print(qc.groupby(["station", "variable"])[["n_raw", "n_range", "n_spike", "n_flatline", "hours_kept"]].sum())
        print(f"{len(used)} files, {sum(p.stat().st_size for p in used) / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
