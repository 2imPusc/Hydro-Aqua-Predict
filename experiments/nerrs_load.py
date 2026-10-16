"""Loader for NERRS SWMP Jobos Bay (Puerto Rico) data -- direction-4 methods pilot.

Source: NCEI archive accession 0052765, copied read-only to
``data/foreign/nerrs_ncei/jobos/`` (see ``docs/data-manifest.md``).

What this module does
---------------------
* Parses water-quality (``jobNNwqYYYY.csv``), meteorological
  (``jobjbmetYYYY.csv``) and nutrient (``jobNNnutYYYY.csv``) files.
* Keeps **only values whose QAQC flag is ``<0>``** ("passed initial QAQC").
  Every other flag (-5..-1, 1 suspect, 2/3 reserved, 4 historical
  pre-auto-QAQC, 5 corrected) is excluded and counted, so the flag shares can
  be reported. Consequence: all pre-2007 data (flag ``<4>``) drops out.
* Builds a station table with WGS84 coordinates parsed from the metadata
  text, attributing each "located at <lat> <lon>" to the nearest preceding
  "Station NN" mention, and cross-checks against the distances the met
  metadata states between the met tower and each station.
* Aggregates to hourly means (local standard time; SWMP files are LST and
  Puerto Rico (AST, UTC-4) has no DST).

Flag definitions (``jobmet01-12.07m.doc`` section 11, CDMO):
-5 above sensor range, -4 below sensor range, -3 rejected by QAQC,
-2 missing, -1 optional parameter not collected, 0 passed initial QAQC,
1 suspect, 2/3 open/reserved, 4 historical data pre-auto-QAQC, 5 corrected.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import paths  # noqa: E402

NERRS_DIR = paths.DATA_DIR / "foreign" / "nerrs_ncei" / "jobos"
WQ_STATIONS = ("09", "10", "19", "20")
WQ_VARIABLES = ("Temp", "Sal", "DO_mgl", "pH", "Turb")
MET_VARIABLES = ("ATemp", "WSpd", "MaxWSpd", "TotPAR", "TotPrcp")
GOOD_FLAG = 0
# Metadata documents used for coordinates, newest first. 2006 metadata corrects
# the Station 10 longitude (older files say 66 45' -> ~55 km west of the bay,
# on another coast: a transcription error) and re-surveys Station 19.
WQ_COORD_PRIMARY = "jobwq01-12.06m.doc"
MET_COORD_DOC = "jobmet01-12.07m.doc"

_FLAG_RE = re.compile(r"<(-?\d)>")
# One DMS token: degrees, garbage (degree sign may be lost/mis-encoded), minutes,
# apostrophe-like char, seconds, optional quote, optional hemisphere.
_DMS = r"(\d{1,3})\s*[^\d\s]?\s*(\d{1,2})\s*[^\d\s]\s*(\d{1,2}(?:\.\d+)?)\s*[^\d\s,NW]?\s*([NW])?"
_LOCATED_RE = re.compile(r"located\s+at\s+" + _DMS + r"[\s,]*(?:and\s+)?" + _DMS, re.I)
_STATION_RE = re.compile(r"Station\s+(?:number\s*)?\(?(\d{1,2})\)?", re.I)
_MET_COORD_RE = re.compile(r"latitude\s+" + _DMS + r".{0,20}?longitude\s+" + _DMS, re.I | re.S)
_MET_DIST_RE = re.compile(r"(\d+(?:\.\d+)?)\s*Km\.?\s*from\s*S(\d{2})", re.I)


# ---------------------------------------------------------------- primitives
def parse_flag(cell) -> int | None:
    """Integer QAQC flag from a cell such as ``"<1> [SSM] (CSM)"``; None if absent."""
    if cell is None or (isinstance(cell, float) and math.isnan(cell)):
        return None
    match = _FLAG_RE.search(str(cell))
    return int(match.group(1)) if match else None


def dms_to_decimal(degrees: float, minutes: float, seconds: float, hemisphere: str) -> float:
    value = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
    return -value if hemisphere.upper() in ("W", "S") else value


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _pair(groups: tuple) -> tuple[float, float]:
    lat = dms_to_decimal(groups[0], groups[1], groups[2], "N")
    lon = dms_to_decimal(groups[4], groups[5], groups[6], "W")  # whole archive is N/W
    return round(lat, 6), round(lon, 6)


def read_metadata_text(path: Path) -> str:
    """Metadata .txt/.doc as text (cp1252 bytes; Word binary noise is tolerated)."""
    text = path.read_bytes().decode("cp1252", errors="replace")
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)


def attribute_station_coordinates(text: str) -> dict[str, tuple[float, float]]:
    """Map station code -> (lat, lon) for each "located at" coordinate pair.

    Attribution rule: the last "Station NN" mention before the coordinate.
    The first pair seen for a station wins (metadata repeats paragraphs).
    """
    out: dict[str, tuple[float, float]] = {}
    for match in _LOCATED_RE.finditer(text):
        mentions = list(_STATION_RE.finditer(text, 0, match.start()))
        if not mentions:
            continue
        code = f"{int(mentions[-1].group(1)):02d}"
        out.setdefault(code, _pair(match.groups()))
    return out


def parse_met_coordinates(text: str) -> tuple[float, float]:
    match = _MET_COORD_RE.search(text)
    if not match:
        raise ValueError("met coordinates not found")
    return _pair(match.groups())


def parse_met_stated_distances(text: str) -> dict[str, float]:
    return {code: float(km) for km, code in _MET_DIST_RE.findall(text)}


# ---------------------------------------------------------------- CSV readers
def _read_raw(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    frame.columns = [c.strip() for c in frame.columns]
    return frame.loc[:, [c for c in frame.columns if c and not c.startswith("Unnamed")]]


def _good_values(raw: pd.DataFrame, variables, source: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    time_col = next(c for c in raw.columns if c.lower() == "datetimestamp")
    index = pd.to_datetime(raw[time_col].str.strip(), format="%m/%d/%Y %H:%M")
    values, counts = {}, []
    for var in variables:
        if var not in raw.columns or f"F_{var}" not in raw.columns:
            continue
        flags = raw[f"F_{var}"].map(parse_flag)
        numeric = pd.to_numeric(raw[var].str.strip(), errors="coerce")
        numeric = numeric.where(numeric > -9999)  # nutrient missing sentinel
        values[var] = numeric.where(flags == GOOD_FLAG).to_numpy()
        tally = pd.to_numeric(flags).fillna(-99).astype(int).value_counts()
        counts += [{"source": source, "variable": var, "flag": int(k), "n": int(v)} for k, v in tally.items()]
    frame = pd.DataFrame(values, index=pd.DatetimeIndex(index, name="time_lst"))
    return frame, pd.DataFrame(counts, columns=["source", "variable", "flag", "n"])


def read_wq_file(path: Path, variables=WQ_VARIABLES) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Good-flag-only values (other cells NaN) + flag tally for one WQ file."""
    return _good_values(_read_raw(path), variables, Path(path).name)


def read_met_file(path: Path, variables=MET_VARIABLES) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Met file restricted to 15-min rows.

    Pre-2007 files interleave 15-min, hourly (60) and daily (144) summary rows
    at the same timestamps; summing all of them would double-count rain.
    """
    raw = _read_raw(path)
    if "Frequency" in raw.columns:
        raw = raw[raw["Frequency"].str.strip() == "15"]
    if "TotPrcp" not in raw.columns:  # jobjbmet2011.csv is a mislabeled empty WQ file
        return pd.DataFrame(), pd.DataFrame(columns=["source", "variable", "flag", "n"])
    return _good_values(raw.reset_index(drop=True), variables, Path(path).name)


def read_nut_file(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    return _good_values(_read_raw(path), ("PO4F", "NH4F", "NO2F", "NO3F", "NO23F", "CHLA_N"), Path(path).name)


def hourly_mean(frame: pd.DataFrame, min_obs: int = 2) -> pd.DataFrame:
    """Hour-start-labelled means; hours with fewer than ``min_obs`` good values -> NaN."""
    grouped = frame.groupby(frame.index.floor("h"))
    return grouped.mean().where(grouped.count() >= min_obs)


def hourly_met(frame: pd.DataFrame) -> pd.DataFrame:
    """Hourly met: rain/PAR are sums (need all 4 quarter-hours), wind/temp means (>=2)."""
    grouped = frame.groupby(frame.index.floor("h"))
    count = grouped.count()
    out = grouped.mean().where(count >= 2)
    for col in ("TotPrcp", "TotPAR"):
        if col in frame:
            out[col] = grouped[col].sum().where(count[col] >= 4)
    return out


# ---------------------------------------------------------------- loaders
def _files(pattern: str, data_dir: Path) -> list[Path]:
    return sorted(Path(data_dir).glob(pattern))


def load_wq_hourly(stations=WQ_STATIONS, years=None, data_dir: Path = NERRS_DIR):
    """Hourly good-flag WQ: long frame (time_lst, station, variable, value) + flag tally."""
    pieces, tallies = [], []
    for code in stations:
        for path in _files(f"job{code}wq*.csv", data_dir):
            year = int(path.stem[-4:])
            if years is not None and year not in years:
                continue
            frame, flags = read_wq_file(path)
            flags.insert(0, "station", code)
            flags.insert(1, "year", year)
            tallies.append(flags)
            hourly = hourly_mean(frame).dropna(how="all")
            long = hourly.reset_index().melt(id_vars="time_lst", var_name="variable", value_name="value").dropna()
            long.insert(1, "station", code)
            pieces.append(long)
    wq = pd.concat(pieces, ignore_index=True).drop_duplicates(["time_lst", "station", "variable"])
    return wq, pd.concat(tallies, ignore_index=True)


def load_met_hourly(years=None, data_dir: Path = NERRS_DIR):
    pieces, tallies = [], []
    for path in _files("jobjbmet*.csv", data_dir):
        year = int(path.stem[-4:])
        if years is not None and year not in years:
            continue
        frame, flags = read_met_file(path)
        flags.insert(0, "station", "jbmet")
        flags.insert(1, "year", year)
        tallies.append(flags)
        if not frame.empty:
            pieces.append(hourly_met(frame))
    met = pd.concat(pieces).sort_index()
    met = met[~met.index.duplicated()]
    return met, pd.concat(tallies, ignore_index=True)


def load_nutrients(stations=WQ_STATIONS, data_dir: Path = NERRS_DIR) -> pd.DataFrame:
    pieces = []
    for code in stations:
        for path in _files(f"job{code}nut*.csv", data_dir):
            frame, _ = read_nut_file(path)
            frame = frame.reset_index()
            frame.insert(1, "station", code)
            pieces.append(frame)
    return pd.concat(pieces, ignore_index=True)


def station_table(data_dir: Path = NERRS_DIR) -> pd.DataFrame:
    """Adopted coordinates (newest WQ metadata) + every variant seen + met cross-check."""
    data_dir = Path(data_dir)
    met_text = read_metadata_text(data_dir / MET_COORD_DOC)
    met_lat, met_lon = parse_met_coordinates(met_text)
    stated = parse_met_stated_distances(met_text)
    adopted = attribute_station_coordinates(read_metadata_text(data_dir / WQ_COORD_PRIMARY))
    variants: dict[str, list[str]] = {}
    for path in sorted(data_dir.glob("jobwq01-12.*m.*")):
        for code, (lat, lon) in attribute_station_coordinates(read_metadata_text(path)).items():
            variants.setdefault(code, []).append(f"{path.name}:{lat:.5f},{lon:.5f}")
    rows = []
    for code in WQ_STATIONS:
        lat, lon = adopted[code]
        computed = haversine_km(met_lat, met_lon, lat, lon)
        rows.append({
            "station": code, "lat": lat, "lon": lon, "coord_source": WQ_COORD_PRIMARY,
            "habitat": "mangrove_lagoon" if code in ("09", "10") else "open_bay_seagrass",
            "depth_m_nominal": 1.0 if code in ("09", "10") else 2.0,
            "met_distance_km_computed": round(computed, 2),
            "met_distance_km_stated": stated.get(code),
            "coord_variants": " | ".join(sorted(set(variants.get(code, [])))),
        })
    rows.append({
        "station": "jbmet", "lat": met_lat, "lon": met_lon, "coord_source": MET_COORD_DOC,
        "habitat": "met_tower", "depth_m_nominal": np.nan,
        "met_distance_km_computed": 0.0, "met_distance_km_stated": 0.0, "coord_variants": "",
    })
    return pd.DataFrame(rows)


def pairwise_distances(stations: pd.DataFrame) -> pd.DataFrame:
    wq = stations[stations["station"].isin(WQ_STATIONS)].set_index("station")
    rows = []
    for a in wq.index:
        for b in wq.index:
            if a != b:
                rows.append({
                    "anchor": a, "target": b,
                    "distance_km": round(haversine_km(wq.at[a, "lat"], wq.at[a, "lon"], wq.at[b, "lat"], wq.at[b, "lon"]), 3),
                    "pair_type": "same_habitat" if wq.at[a, "habitat"] == wq.at[b, "habitat"] else "cross_habitat",
                })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    table = station_table()
    print(table.drop(columns="coord_variants").to_string(index=False))
    print(pairwise_distances(table).to_string(index=False))
