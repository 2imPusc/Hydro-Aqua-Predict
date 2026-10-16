"""Maryland DNR "Eyes on the Bay" continuous monitoring (ConMon) loader for the
direction-4 reliability test (H4.4).

Source (no login): station table
``https://eyesonthebay.dnr.maryland.gov/eyesonthebay/ConMonStationTableDownload.cfm``
and 15-min data per station via the "Download Raw 'Continuous Measurement' 15min
Data" route ``https://eyesonthebay.dnr.maryland.gov/contmon/JustDownload.cfm``
(query: station=<3-letter code>, parameter=..., StartDate, EndDate, outputtype=2).
One file per station x calendar year -> ``raw/<CODE>_<YYYY>.csv`` (write-once).

Data use (EotB data-use policy PDF): no redistribution of raw data to third
parties; cite "Maryland Department of Natural Resources, Eyes on the Bay,
www.eyesonthebay.net". Raw files stay in gitignored ``data/foreign/``.

QC: the CSV has no flag/qualifier columns. Years before the current one are
post-QA (portal footnote: only current-year data are provisional); values that
failed DNR QA are blank. On top of that this loader applies, per station-file:
physical range, spike (|x - median of +/-2 neighbours| > limit), and flatline
(>= FLATLINE_RUN identical consecutive non-missing values; Sal < 0.5 psu exempt,
tidal-fresh salinity legitimately sits on one value). Rejected shares are
reported per station x year x variable.

Time basis: timestamps carry no DST jumps (checked: complete 00-23 h on DST
change days) -> treated as fixed Eastern Standard Time (UTC-5).

Hourly means (hour-start labels) need >= 2 QC-good 15-min values.

Download:  .venv\\Scripts\\python experiments\\mddnr_load.py --download
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import paths  # noqa: E402

MDDNR_DIR = paths.FOREIGN_DATA_DIR / "chesapeake_mddnr"
RAW_DIR_NAME = "raw"
STATION_TABLE_NAME = "ConMonStationTable.csv"
USER_AGENT = "Hydro-Aqua-Predict research (academic)"
TABLE_URL = "https://eyesonthebay.dnr.maryland.gov/eyesonthebay/ConMonStationTableDownload.cfm"
DATA_URL = "https://eyesonthebay.dnr.maryland.gov/contmon/JustDownload.cfm"
PARAMETERS = ("wtemp", "Salinity", "DO", "ph", "TurbNTU")
YEARS = range(2004, 2010)
CLUSTER_RADIUS_KM = 30.0
CLUSTER_MIN_SITES = 5
# co-located bottom sensors (same coordinates as a surface sensor) -> dropped, surface kept
BOTTOM_DUPLICATES = ("GOB", "PPB", "SIB", "AEB", "MSB")
UTC_OFFSET_H = -5

# source column -> evaluation key (keys match experiments.nerrs_reliability.TOLERANCES)
COLUMNS = {"Temp_C": "Temp", "Salinity_ppt": "Sal", "DO_mg/L": "DO_mgl", "pH": "pH", "Turb_NTU": "Turb"}
RANGES = {"Temp": (-2.0, 40.0), "Sal": (0.0, 40.0), "DO_mgl": (0.0, 25.0), "pH": (5.0, 10.5), "Turb": (0.0, 1000.0)}
SPIKE = {"Temp": 3.0, "Sal": 5.0, "DO_mgl": 4.0, "pH": 1.0, "Turb": 200.0}
FLATLINE_RUN = 48          # 12 h of identical 15-min values (shorter runs are legitimate at 0.01 resolution in oligohaline water)
FLATLINE_EXEMPT = {"Sal": 0.5}  # values below this are allowed to repeat


# ---------------------------------------------------------------- geometry / selection
def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(a))


def read_station_table(path: Path) -> pd.DataFrame:
    table = pd.read_csv(path)
    table.columns = [c.strip() for c in table.columns]
    table = table.rename(columns={"StationCode": "station", "Latitude": "lat", "Longitude": "lon",
                                  "SamplingStartDate": "start", "SamplingEndDate": "end",
                                  "StationID": "cbp_station", "Tributary": "tributary", "Station": "name"})
    table["start"] = pd.to_datetime(table["start"])
    table["end"] = pd.to_datetime(table["end"])
    desc = table["InstrumentSampleDepthDescription"].astype(str).str.lower()
    table["sensor_type"] = np.where(desc.str.contains("below the surface|below surface"), "surface", "bottom")
    return table


def select_station_years(table: pd.DataFrame, years=YEARS, radius_km: float = CLUSTER_RADIUS_KM,
                         min_sites: int = CLUSTER_MIN_SITES, drop=BOTTOM_DUPLICATES) -> pd.DataFrame:
    """Station-years whose station had >= min_sites-1 other stations active within radius_km.

    'Active' in a year = table span covers 1 May..1 Oct of that year (span only;
    real coverage is checked from the downloaded data).
    """
    t = table[~table["station"].isin(drop)]
    rows = []
    for year in years:
        act = t[(t["start"] <= pd.Timestamp(f"{year}-10-01")) & (t["end"] >= pd.Timestamp(f"{year}-05-01"))]
        if act.empty:
            continue
        d = haversine_km(act["lat"].to_numpy()[:, None], act["lon"].to_numpy()[:, None],
                         act["lat"].to_numpy()[None], act["lon"].to_numpy()[None])
        n_near = (d <= radius_km).sum(1)  # includes itself
        for code, n in zip(act["station"], n_near):
            if n >= min_sites:
                rows.append({"station": code, "year": int(year), "n_sites_within_radius": int(n)})
    return pd.DataFrame(rows, columns=["station", "year", "n_sites_within_radius"])


# ---------------------------------------------------------------- download (write-once)
def data_url(station: str, year: int) -> str:
    query = [("station", station)] + [("parameter", p) for p in PARAMETERS] + [
        ("StartDate", f"{year}-01-01"), ("EndDate", f"{year}-12-31"), ("outputtype", "2")]
    return DATA_URL + "?" + urllib.parse.urlencode(query)


def _get(url: str, retries: int = 4, timeout: int = 300) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == retries - 1:
                raise
            wait = 5 * 2 ** attempt
            print(f"  retry in {wait}s after {exc!r}", flush=True)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(payload)


def download(data_dir: Path = MDDNR_DIR, years=YEARS, pause_s: float = 1.5) -> pd.DataFrame:
    table_path = data_dir / STATION_TABLE_NAME
    if not table_path.exists():
        write_once(table_path, _get(TABLE_URL))
    table = read_station_table(table_path)
    plan = select_station_years(table, years)
    log = []
    for row in plan.itertuples(index=False):
        path = data_dir / RAW_DIR_NAME / f"{row.station}_{row.year}.csv"
        empty_marker = path.with_suffix(".empty")
        if path.exists() or empty_marker.exists():
            log.append({"station": row.station, "year": row.year, "status": "exists"})
            continue
        payload = _get(data_url(row.station, row.year))
        lines = payload.count(b"\n")
        if lines <= 1:
            write_once(empty_marker, payload)  # remembers the empty answer, no re-query
            status = "empty"
        else:
            write_once(path, payload)
            status = f"ok {len(payload)} B {lines} lines"
        print(f"{row.station} {row.year}: {status}", flush=True)
        log.append({"station": row.station, "year": row.year, "status": status})
        time.sleep(pause_s)
    return pd.DataFrame(log)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------- parsing + QC
def read_raw_file(path_or_buffer) -> pd.DataFrame:
    """JustDownload CSV -> frame indexed by EST timestamp with evaluation-key columns."""
    raw = pd.read_csv(path_or_buffer, dtype=str, keep_default_na=False)
    raw.columns = [c.strip() for c in raw.columns]
    index = pd.to_datetime(raw["DateTime"].str.strip(), format="%m/%d/%Y %H:%M")
    out = pd.DataFrame(index=pd.DatetimeIndex(index, name="time_est"))
    for col, key in COLUMNS.items():
        if col in raw.columns:
            out[key] = pd.to_numeric(raw[col].str.strip(), errors="coerce").to_numpy()
    out = out[~out.index.duplicated(keep="first")].sort_index()
    return out


def flatline_mask(series: pd.Series, run: int = FLATLINE_RUN, exempt_below: float | None = None) -> pd.Series:
    """True where the value belongs to a run of >= ``run`` identical consecutive non-missing values."""
    s = series.dropna()
    if s.empty:
        return pd.Series(False, index=series.index)
    block = (s != s.shift()).cumsum()
    length = s.groupby(block).transform("size")
    mask = length >= run
    if exempt_below is not None:
        mask &= ~(s < exempt_below)
    return mask.reindex(series.index, fill_value=False)


def spike_mask(series: pd.Series, limit: float, half_window: int = 2) -> pd.Series:
    """|x - centred rolling median of the 2*half_window neighbours (incl. x)| > limit."""
    s = series.dropna()
    if s.empty:
        return pd.Series(False, index=series.index)
    med = s.rolling(2 * half_window + 1, center=True, min_periods=3).median()
    mask = (s - med).abs() > limit
    return mask.reindex(series.index, fill_value=False)


def qc_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Apply range -> spike -> flatline; return cleaned frame and per-variable tallies."""
    clean = frame.copy()
    tally = []
    for key in frame.columns:
        s = frame[key]
        n_present = int(s.notna().sum())
        lo, hi = RANGES[key]
        bad_range = s.notna() & ((s < lo) | (s > hi))
        s1 = s.where(~bad_range)
        bad_spike = spike_mask(s1, SPIKE[key])
        s2 = s1.where(~bad_spike)
        bad_flat = flatline_mask(s2, exempt_below=FLATLINE_EXEMPT.get(key))
        clean[key] = s2.where(~bad_flat)
        tally.append({"variable": key, "n_rows": int(len(s)), "n_blank_source": int(len(s) - n_present),
                      "n_range": int(bad_range.sum()), "n_spike": int(bad_spike.sum()),
                      "n_flatline": int(bad_flat.sum()), "n_good": int(clean[key].notna().sum())})
    return clean, tally


def hourly_mean(frame: pd.DataFrame, min_obs: int = 2) -> pd.DataFrame:
    grouped = frame.groupby(frame.index.floor("h"))
    return grouped.mean().where(grouped.count() >= min_obs)


def load_hourly(data_dir: Path = MDDNR_DIR, stations=None, years=None):
    """Long hourly frame (time_est, station, variable, value), QC tally, list of raw files."""
    pieces, tallies, files = [], [], []
    for path in sorted((data_dir / RAW_DIR_NAME).glob("*_*.csv")):
        code, year = path.stem.rsplit("_", 1)
        if (stations is not None and code not in stations) or (years is not None and int(year) not in years):
            continue
        files.append(path)
        frame = read_raw_file(path)
        if frame.empty:
            continue
        clean, tally = qc_frame(frame)
        tallies += [{"station": code, "year": int(year), **t} for t in tally]
        hourly = hourly_mean(clean).dropna(how="all")
        long = hourly.reset_index().melt(id_vars="time_est", var_name="variable", value_name="value").dropna()
        long.insert(1, "station", code)
        pieces.append(long)
    hourly = pd.concat(pieces, ignore_index=True).drop_duplicates(["time_est", "station", "variable"])
    return hourly, pd.DataFrame(tallies), files


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--download", action="store_true", help="fetch missing station-year files (write-once)")
    parser.add_argument("--data-dir", type=Path, default=MDDNR_DIR)
    args = parser.parse_args(argv)
    if args.download:
        log = download(args.data_dir)
        print(log["status"].str.split().str[0].value_counts().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
