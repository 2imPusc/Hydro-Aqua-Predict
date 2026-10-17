"""Loader for the Indian River Lagoon Observatory Network (IRLON, FAU Harbor Branch) (direction 4, H4.7).

Source: the open SECOORA ERDDAP mirror of IRLON
``https://erddap.secoora.org/erddap/tabledap/<dataset_id>.csv`` (no login). The IRLON
portal's own CSV download (irlon.org) requires registration and is not used.
Acknowledgement requested by the provider: "Indian River Lagoon Observatory Network of
Environmental Sensors (IRLON), Harbor Branch Oceanographic Institute at Florida Atlantic
University"; SECOORA licence: free use and redistribution, cite the regional
association / NOAA.

Raw files: one per station x calendar year (UTC), CSV as served, gzip-compressed on
disk, write-once under ``paths.FOREIGN_DATA_DIR / "irlon_secoora" / "raw"``
(``<code>/<code>_<YYYY>.csv.gz``) with an append-only ``raw/download_manifest.csv``
(url, status, bytes, sha256 of the stored gzip). Requests are sequential with a pause
and retries. ERDDAP answers HTTP 404 "Your query produced no matching results" for an
empty year (logged, no file).

QC / selection (documented in SOURCES.md)
* Every variable carries an IOOS QARTOD aggregate flag ``<var>_qc_agg``
  (1 pass, 2 not evaluated, 3 suspect, 4 fail, 9 missing). Only flag 1 is kept for the
  water-quality variables. Exception: station rain is never QARTOD-evaluated (all
  values flag 2), so rain keeps flags 1-2 plus the range check.
* Physical range check on top: Temp 5..40 C, Sal 0..45, DO 0..20 mg/L, pH 6.5..9.5,
  Turb 0..1000 NTU, NO3 -5..200 umol/L (negatives > -5 are clipped to 0: the SUNA
  reports small negative values near zero and QARTOD passes them), PO4 0..20 umol/L,
  rain 0..150 mm/h.
* Nutrients use the umol/L variables (``mole_concentration_of_*``); the mg/L twins are
  rounded to 0.01 mg/L, too coarse for phosphate.
* Data are hourly (one reading per UTC hour); a single reading per hour is accepted
  (deviation from the >= 2 obs/hour used for 15-min networks). Duplicate hours are
  averaged.
* Station rain ``lwe_precipitation_rate`` (mm/h, hourly) is taken as the hourly total.

Run:  .venv\\Scripts\\python experiments\\irlon_load.py download
      .venv\\Scripts\\python experiments\\irlon_load.py summary
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import paths  # noqa: E402

IRLON_DIR = paths.FOREIGN_DATA_DIR / "irlon_secoora"
RAW_DIR = IRLON_DIR / "raw"
DERIVED_DIR = IRLON_DIR / "derived"
USER_AGENT = "Hydro-Aqua-Predict research (academic)"
ERDDAP = "https://erddap.secoora.org/erddap/tabledap/"
PERIOD_END = "2026-10-16T23:59:59Z"   # fixed end for reproducibility (datasets are live)

# ERDDAP dataset id -> (code, label, cluster, lat, lon, first year)
STATIONS = {
    "indian-river-lagoon-titusville-i": ("TV", "IRL Titusville", "north_lagoon", 28.5985, -80.7913, 2022),
    "indian-river-lagoon-banana-river": ("BR", "Banana River", "north_lagoon", 28.4549, -80.6387, 2022),
    "indian-river-lagoon-malabar-irl-": ("MB", "IRL Malabar", "north_lagoon", 27.9751, -80.5368, 2022),
    "indian-river-lagoon-sebastian-ir": ("SB", "IRL Sebastian", "lagoon", 27.8391, -80.4708, 2015),
    "indian-river-lagoon-vero-beach-i": ("VB", "IRL Vero Beach", "lagoon", 27.5901, -80.3553, 2014),
    "indian-river-lagoon-link-port-ir": ("LP", "IRL Link Port", "lagoon", 27.5348, -80.3431, 2014),
    "indian-river-lagoon-fort-pierce-": ("FP", "IRL Fort Pierce", "lagoon", 27.4756, -80.3266, 2014),
    "indian-river-lagoon-jensen-beach": ("JB", "IRL Jensen Beach", "st_lucie", 27.2244, -80.2023, 2015),
    "indian-river-lagoon-st-lucie-est": ("SLE", "IRL at St. Lucie Estuary mouth", "st_lucie", 27.1649, -80.1718, 2015),
    "st-lucie-estuary-middle-estuary-": ("ME", "St. Lucie Middle Estuary", "st_lucie", 27.2089, -80.2480, 2015),
    "st-lucie-estuary-north-fork-sle-": ("NF", "St. Lucie North Fork", "st_lucie", 27.2100, -80.2692, 2015),
    "st-lucie-estuary-south-fork-sle-": ("SF", "St. Lucie South Fork", "st_lucie", 27.1878, -80.2642, 2015),
    "st-lucie-estuary-south-fork-2-sl": ("SF2", "St. Lucie South Fork 2", "st_lucie", 27.1142, -80.2829, 2016),
}
LAST_YEAR = 2026

# ERDDAP variable -> analysis key
VARIABLES = {
    "sea_water_temperature": "Temp",
    "sea_water_practical_salinity": "Sal",
    "mass_concentration_of_oxygen_in_sea_water": "DO",
    "sea_water_ph_reported_on_total_scale": "pH",
    "sea_water_turbidity": "Turb",
    "mole_concentration_of_nitrate_in_sea_water": "NO3",
    "mole_concentration_of_phosphate_in_sea_water": "PO4",
    "lwe_precipitation_rate": "Rain",
    "mass_concentration_of_chlorophyll_in_sea_water": "Chl",
    "nitrate": "NO3_mgL",
    "phosphate": "PO4_mgL",
}
RANGES = {"Temp": (5.0, 40.0), "Sal": (0.0, 45.0), "DO": (0.0, 20.0), "pH": (6.5, 9.5), "Turb": (0.0, 1000.0),
          "NO3": (-5.0, 200.0), "PO4": (0.0, 20.0), "Rain": (0.0, 150.0), "Chl": (0.0, 400.0),
          "NO3_mgL": (-1.0, 20.0), "PO4_mgL": (0.0, 5.0)}
CLIP_NEGATIVE_TO_ZERO = ("NO3", "NO3_mgL")
GOOD_FLAG = 1
# QARTOD is not run on station rain (every value is flag 2 "not evaluated"); rain keeps 1 or 2
ACCEPTED_FLAGS = {"Rain": (1, 2)}


def code_of(dataset_id: str) -> str:
    return STATIONS[dataset_id][0]


def station_table() -> pd.DataFrame:
    rows = [{"site": v[0], "dataset_id": k, "label": v[1], "cluster": v[2], "lat": v[3], "lon": v[4],
             "first_year": v[5]} for k, v in STATIONS.items()]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- download
def request_url(dataset_id: str, year: int) -> str:
    cols = ["time"] + [c for v in VARIABLES for c in (v, f"{v}_qc_agg")]
    start = f"{year}-01-01T00:00:00Z"
    end = f"{year + 1}-01-01T00:00:00Z" if year < LAST_YEAR else PERIOD_END
    op = "%3C" if year < LAST_YEAR else "%3C%3D"
    return (f"{ERDDAP}{dataset_id}.csv?{','.join(cols)}"
            f"&time%3E%3D{urllib.parse.quote(start)}&time{op}{urllib.parse.quote(end)}")


def _get(url: str, retries: int = 5, backoff_s: float = 5.0) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_exc = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read() if hasattr(exc, "read") else b""
            if exc.code == 404:  # ERDDAP: "Your query produced no matching results"
                return 404, body
            last_exc = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_exc = exc
        if attempt < retries - 1:
            time.sleep(backoff_s * (2 ** attempt))
    raise RuntimeError(f"giving up on {url}: {last_exc!r}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _write_once(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(data)


def _log(manifest: Path, row: dict) -> None:
    new = not manifest.exists()
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest, "a", encoding="utf-8", newline="") as handle:  # append-only
        writer = csv.DictWriter(handle, fieldnames=list(row))
        if new:
            writer.writeheader()
        writer.writerow(row)


def raw_path(raw_dir: Path, code: str, year: int) -> Path:
    return raw_dir / code / f"{code}_{year}.csv.gz"


def download(raw_dir: Path = RAW_DIR, pause_s: float = 1.5) -> list[Path]:
    manifest = raw_dir / "download_manifest.csv"
    logged_empty = set()
    if manifest.exists():
        done = pd.read_csv(manifest, dtype=str)
        logged_empty = set(done.loc[done["status"] == "404", "file"])
    written = []
    for dataset_id, (code, *_rest, first_year) in STATIONS.items():
        for year in range(first_year, LAST_YEAR + 1):
            path = raw_path(raw_dir, code, year)
            rel = path.relative_to(raw_dir).as_posix()
            if path.exists() or rel in logged_empty:
                continue
            url = request_url(dataset_id, year)
            row = {"file": rel, "dataset_id": dataset_id, "year": year, "url": url, "status": "", "bytes": 0,
                   "sha256": "", "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            try:
                status, payload = _get(url)
            except RuntimeError as exc:
                _log(manifest, {**row, "status": f"failed: {exc}"[:200]})
                print(f"{code} {year}: FAILED", flush=True)
                time.sleep(pause_s)
                continue
            row["status"] = status
            if status == 200 and payload:
                data = gzip.compress(payload)
                _write_once(path, data)
                row.update(bytes=len(data), sha256=sha256_bytes(data))
                written.append(path)
            _log(manifest, row)
            print(f"{code} {year}: {status} {row['bytes']} B", flush=True)
            time.sleep(pause_s)
    return written


def raw_files(raw_dir: Path = RAW_DIR) -> list[Path]:
    return sorted(raw_dir.glob("*/*.csv.gz"))


# ---------------------------------------------------------------- parse / QC
def parse_erddap_csv(text: str) -> pd.DataFrame:
    """ERDDAP .csv: header row, units row, data rows. Returns raw frame with time_utc."""
    frame = pd.read_csv(io.StringIO(text), skiprows=[1], na_values=["NaN"], low_memory=False)
    frame["time_utc"] = pd.to_datetime(frame.pop("time"), utc=True).dt.tz_localize(None)
    return frame


def qc_long(frame: pd.DataFrame, site: str) -> tuple[pd.DataFrame, list[dict]]:
    """Long table (site, var, hour_utc, value) of QARTOD-pass, in-range values + per-var counts."""
    out, counts = [], []
    hour = frame["time_utc"].dt.floor("h")
    for col, var in VARIABLES.items():
        if col not in frame:
            continue
        val = pd.to_numeric(frame[col], errors="coerce")
        flag = pd.to_numeric(frame.get(f"{col}_qc_agg"), errors="coerce") if f"{col}_qc_agg" in frame \
            else pd.Series(np.nan, index=frame.index)
        lo, hi = RANGES[var]
        present = val.notna()
        good_flag = present & flag.isin(ACCEPTED_FLAGS.get(var, (GOOD_FLAG,)))
        in_range = good_flag & val.between(lo, hi)
        rec = {"site": site, "var": var, "n_rows": int(len(frame)), "n_present": int(present.sum()),
               "n_flag1": int(good_flag.sum()), "n_accepted": int(in_range.sum())}
        for f in (2, 3, 4, 9):
            rec[f"n_flag{f}"] = int((present & (flag == f)).sum())
        rec["n_flag_nan"] = int((present & flag.isna()).sum())
        counts.append(rec)
        v = val[in_range]
        if var in CLIP_NEGATIVE_TO_ZERO:
            v = v.clip(lower=0.0)
        out.append(pd.DataFrame({"site": site, "var": var, "hour_utc": hour[in_range].to_numpy(), "value": v.to_numpy()}))
    long = pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["site", "var", "hour_utc", "value"])
    return long, counts


def hourly_values(long: pd.DataFrame) -> pd.DataFrame:
    """One value per site x var x UTC hour (mean of duplicates; normally one reading per hour)."""
    return long.groupby(["site", "var", "hour_utc"], as_index=False)["value"].mean()


def build_hourly(raw_dir: Path = RAW_DIR) -> tuple[pd.DataFrame, dict]:
    longs, counts, n_rows = [], [], 0
    for path in raw_files(raw_dir):
        site = path.parent.name
        frame = parse_erddap_csv(gzip.decompress(path.read_bytes()).decode("utf-8"))
        frame = frame[frame["time_utc"] <= pd.Timestamp(PERIOD_END).tz_localize(None)]
        n_rows += len(frame)
        long, c = qc_long(frame, site)
        for rec in c:
            rec["file"] = path.name
        longs.append(long)
        counts.extend(c)
    hourly = hourly_values(pd.concat(longs, ignore_index=True))
    qc = pd.DataFrame(counts).groupby(["site", "var"], as_index=False).sum(numeric_only=True)
    return hourly, {"n_raw_rows": n_rows, "n_accepted": int(qc["n_accepted"].sum()), "qc_counts": qc}


def summary(raw_dir: Path = RAW_DIR) -> None:
    hourly, report = build_hourly(raw_dir)
    cov = hourly.groupby(["site", "var"])["hour_utc"].agg(n_hours="size", first="min", last="max")
    with pd.option_context("display.width", 200, "display.max_rows", 500):
        print(cov)
        print(report["qc_counts"])
    print("raw rows", report["n_raw_rows"], "accepted", report["n_accepted"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["download", "summary"])
    ap.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    args = ap.parse_args(argv)
    if args.command == "download":
        written = download(args.raw_dir)
        print(f"{len(written)} new files")
    else:
        summary(args.raw_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
