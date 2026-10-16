"""Reserve-parametrised NERRS SWMP loader + downloader (direction 4, H4.3).

Generalises ``experiments/nerrs_load.py`` (Jobos only) to any reserve of NOAA
NCEI accession 0052765 (NERRS CDMO archive 1995-2011, version 2.2):
``https://www.ncei.noaa.gov/data/oceans/archive/arc0023/0052765/2.2/data/0-data/NERRS_CDMO_Archive_8.3.11/``

Files are named ``<res><st>wq<YYYY>.csv`` / ``<res><st>met<YYYY>.csv`` with
metadata ``<res>wq01-12.<yy>m.doc|txt``. QAQC: only flag ``<0>`` is kept (same
rule as RL-12). The automated CDMO QAQC flags start in 2007; earlier years carry
only ``<4>`` (historical, 30-min) so they are not downloaded.

Reserve data folders: ``paths.FOREIGN_DATA_DIR / "nerrs_ncei" / <code>``; Jobos
stays in its existing ``jobos/`` folder (read-only, not re-downloaded).

CLI
  python experiments/nerrs_multi.py fetch --reserve rkb [--metadata-only]
  python experiments/nerrs_multi.py stations --reserve rkb
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import paths  # noqa: E402
from experiments import nerrs_load as nl  # noqa: E402

NCEI_ACCESSION = "0052765"
NCEI_BASE = ("https://www.ncei.noaa.gov/data/oceans/archive/arc0023/0052765/2.2/data/0-data/"
             "NERRS_CDMO_Archive_8.3.11/")
NCEI_LANDING = "https://www.ncei.noaa.gov/archive/accession/0052765"
USER_AGENT = "Hydro-Aqua-Predict research (academic)"
NERRS_ROOT = paths.FOREIGN_DATA_DIR / "nerrs_ncei"
QC_YEARS = range(2007, 2012)  # years whose files carry automated CDMO QAQC flags (<0> exists)


@dataclass(frozen=True)
class Reserve:
    code: str
    name: str
    state: str
    utc_offset_h: float           # SWMP files are local *standard* time all year
    wq_stations: tuple[str, ...]  # 2-char station codes with 2007-2011 WQ data
    met_stations: tuple[str, ...]  # met station(s); first = preferred where overlapping
    folder: str = ""
    vertical_pairs: tuple[tuple[str, str], ...] = ()  # co-located sondes (surface/bottom)
    coord_overrides: tuple[tuple[str, float, float, str], ...] = ()  # (station, lat, lon, source note)

    @property
    def data_dir(self) -> Path:
        return NERRS_ROOT / (self.folder or self.code)


# Station lists = stations with WQ files in 2007-2011 in the archive listing
# (checked 2026-10-17). UTC offsets = CDMO gmt_off (SWMPr stat_locs). Seasons are
# not hard-coded here: the reliability script derives each reserve's low-salinity
# (wet / high-flow) season from the data.
RESERVES: dict[str, Reserve] = {
    "job": Reserve("job", "Jobos Bay", "PR", -4, ("09", "10", "19", "20"), ("jb",), folder="jobos"),
    "rkb": Reserve("rkb", "Rookery Bay", "FL", -5, ("fb", "fu", "lh", "mb"), ("uh",)),
    "apa": Reserve("apa", "Apalachicola Bay", "FL", -5, ("cp", "db", "eb", "es"), ("eb",),
                   vertical_pairs=(("eb", "es"),),  # East Bay bottom/surface sondes on one piling
                   coord_overrides=(("eb", 29.785833, -84.875333,
                                     "apawq01-12.06m.doc East Bay piling 29 47.15'N 84 52.52'W (EB bottom + ES surface)"),
                                    ("es", 29.785833, -84.875333,
                                     "apawq01-12.06m.doc East Bay piling 29 47.15'N 84 52.52'W (EB bottom + ES surface)"),
                                    ("eb@met", 29.7912, -84.883417, "apamet01-12.07m.doc tower 29 47.472'N 84 53.005'W"))),
    "gtm": Reserve("gtm", "Guana Tolomato Matanzas", "FL", -5, ("fm", "pc", "pi", "ss"), ("pc",),
                   coord_overrides=(("pc@met", 29.657702, -81.232743,
                                     "CDMO stat_locs gtmpc row not matching the WQ sonde (met docs give only reserve corners)"),)),
    "mar": Reserve("mar", "Mission-Aransas", "TX", -6, ("ab", "ce", "cw", "mb", "sc"), ("ce",)),
    "gnd": Reserve("gnd", "Grand Bay", "MS", -6, ("bc", "bh", "bl", "pc"), ("cr",)),
    "wkb": Reserve("wkb", "Weeks Bay", "AL", -6, ("fr", "mb", "mr", "wb"), ("wb", "sh")),
    "sap": Reserve("sap", "Sapelo Island", "GA", -5, ("ca", "dc", "hd", "ld"), ("ml",)),
}

_FILE_RE = re.compile(r"^([a-z]{3})([a-z0-9]{2})(wq|met|nut)(\d{4})\.csv$")
_META_RE = re.compile(r"^([a-z]{3})(wq|met)\d{2}-\d{2}\.(\d{2})m\.(doc|docx|txt)$")


# ---------------------------------------------------------------- listing / download
def parse_listing(html: str) -> pd.DataFrame:
    """Apache index page -> (name, size_text)."""
    rows = re.findall(r'<a href="([^"?/][^"]*)">[^<]*</a></td><td[^>]*>[^<]*</td><td[^>]*>\s*([^<]*?)\s*</td>', html)
    return pd.DataFrame(rows, columns=["name", "size_text"])


def select_files(names, reserve: Reserve, years=QC_YEARS, metadata_only: bool = False) -> list[str]:
    """Archive files needed for one reserve: WQ/met CSVs of ``years`` + every WQ/met metadata doc."""
    out = []
    for name in names:
        meta = _META_RE.match(name)
        if meta and meta.group(1) == reserve.code:
            out.append(name)
            continue
        if metadata_only:
            continue
        m = _FILE_RE.match(name)
        if not m or m.group(1) != reserve.code or int(m.group(4)) not in years:
            continue
        station, kind = m.group(2), m.group(3)
        if (kind == "wq" and station in reserve.wq_stations) or (kind == "met" and station in reserve.met_stations):
            out.append(name)
    return sorted(out)


def _get(url: str, retries: int = 4, timeout: int = 180) -> bytes:
    delay = 5.0
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == retries or (isinstance(exc, urllib.error.HTTPError) and exc.code == 404):
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_reserve(reserve: Reserve, metadata_only: bool = False, listing_html: str | None = None,
                  pause_s: float = 0.5) -> pd.DataFrame:
    """Download (write-once) the selected files; returns/updates ``download_manifest.csv``."""
    if reserve.code == "job":
        raise ValueError("Jobos is already local (jobos/); not re-downloaded")
    out_dir = reserve.data_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    html = listing_html if listing_html is not None else _get(NCEI_BASE).decode("utf-8", "replace")
    names = select_files(parse_listing(html)["name"], reserve, metadata_only=metadata_only)
    rows = []
    for name in names:
        target = out_dir / name
        if not target.exists():
            data = _get(NCEI_BASE + name)
            part = target.with_name(target.name + ".part")
            with open(part, "xb") as handle:  # write-once
                handle.write(data)
            part.rename(target)
            time.sleep(pause_s)
            status = "downloaded"
        else:
            status = "present"
        rows.append({"file": name, "url": NCEI_BASE + name, "bytes": target.stat().st_size,
                     "sha256": sha256_file(target), "status": status,
                     "accessed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    manifest = pd.DataFrame(rows)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with open(out_dir / f"download_manifest_{stamp}.csv", "x", encoding="utf-8", newline="") as handle:
        manifest.to_csv(handle, index=False)
    return manifest


# ---------------------------------------------------------------- loading
def _year_of(path: Path) -> int:
    return int(path.stem[-4:])


def load_wq_hourly(reserve: Reserve, years=QC_YEARS, data_dir: Path | None = None):
    """Hourly good-flag WQ (long: time_lst, station, variable, value) + flag tally."""
    data_dir = Path(data_dir or reserve.data_dir)
    pieces, tallies = [], []
    for code in reserve.wq_stations:
        for path in sorted(data_dir.glob(f"{reserve.code}{code}wq*.csv")):
            year = _year_of(path)
            if years is not None and year not in years:
                continue
            frame, flags = nl.read_wq_file(path)
            flags.insert(0, "station", code)
            flags.insert(1, "year", year)
            tallies.append(flags)
            hourly = nl.hourly_mean(frame).dropna(how="all")
            if hourly.empty:
                continue
            long = hourly.reset_index().melt(id_vars="time_lst", var_name="variable", value_name="value").dropna()
            long.insert(1, "station", code)
            pieces.append(long)
    wq = (pd.concat(pieces, ignore_index=True).drop_duplicates(["time_lst", "station", "variable"])
          if pieces else pd.DataFrame(columns=["time_lst", "station", "variable", "value"]))
    flags = pd.concat(tallies, ignore_index=True) if tallies else pd.DataFrame()
    return wq, flags


def load_met_hourly(reserve: Reserve, years=QC_YEARS, data_dir: Path | None = None):
    """Hourly met; several met stations are merged with the first listed preferred."""
    data_dir = Path(data_dir or reserve.data_dir)
    merged, tallies = None, []
    for code in reserve.met_stations:
        pieces = []
        for path in sorted(data_dir.glob(f"{reserve.code}{code}met*.csv")):
            year = _year_of(path)
            if years is not None and year not in years:
                continue
            frame, flags = nl.read_met_file(path)
            flags.insert(0, "station", f"{code}met")
            flags.insert(1, "year", year)
            tallies.append(flags)
            if not frame.empty:
                pieces.append(nl.hourly_met(frame))
        if not pieces:
            continue
        met = pd.concat(pieces).sort_index()
        met = met[~met.index.duplicated()]
        merged = met if merged is None else merged.combine_first(met)
    if merged is None:
        merged = pd.DataFrame(columns=list(nl.MET_VARIABLES))
    return merged, (pd.concat(tallies, ignore_index=True) if tallies else pd.DataFrame())


# ---------------------------------------------------------------- coordinates
STAT_LOCS_CSV = NERRS_ROOT / "swmpr_stat_locs" / "stat_locs.csv"  # CDMO sampling_locations via SWMPr (CC0)
# Degrees + decimal minutes ("29(47.15' N and longitude 84(52.52' W",
# "[27° 58.791'N, 97° 1.727'W]") or decimal degrees ("26.0257 N 81.7332 W").
_DEG_SEP = r"(?:\s*[^\d\s]{1,2}\s*|\s+)"  # degree sign (often mis-encoded) or a bare space
_DM = r"\b(\d{2,3})" + _DEG_SEP + r"(\d{1,2}\.\d+)\s*[^\d\s]{0,2}\s*N?"
_DM_W = r"(\d{2,3})" + _DEG_SEP + r"(\d{1,2}\.\d+)\s*[^\d\s]{0,2}\s*W"
_DM_PAIR_RE = re.compile(_DM + r"[\s,;]*(?:and\s+)?(?:longitude\s+)?" + _DM_W, re.I)
_DEC_PAIR_RE = re.compile(r"\b(\d{2}\.\d{3,})\s*[^\d\s]{0,2}\s*N[\s,;]*(?:and\s+)?-?(\d{2,3}\.\d{3,})\s*[^\d\s]{0,2}\s*W", re.I)


def read_doc_text(path: Path) -> str:
    """Text of a metadata .doc/.txt (cp1252, binary noise tolerated) or .docx (XML stripped)."""
    path = Path(path)
    if path.suffix == ".docx":
        import zipfile
        xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "replace")
        return re.sub(r"<[^>]+>", " ", xml)
    return nl.read_metadata_text(path)


def parse_coordinates(text: str, reserve_code: str, stations) -> dict[str, tuple[float, float]]:
    """Station -> (lat, lon) for every coordinate pair in ``text``.

    Attribution: nearest preceding station mention, either ``(XX)`` or
    ``(<res>xxwq)``, restricted to known ``stations``. First hit per station wins.
    """
    text = re.sub(r"\s+", " ", text)
    known = {s.lower() for s in stations}
    mention = re.compile(r"\((?:%s)?([A-Za-z0-9]{2})(?:wq)?\)" % re.escape(reserve_code), re.I)
    hits = []
    for match in _DM_PAIR_RE.finditer(text):
        lat = float(match.group(1)) + float(match.group(2)) / 60
        lon = -(float(match.group(3)) + float(match.group(4)) / 60)
        hits.append((match.start(), lat, lon))
    for match in _DEC_PAIR_RE.finditer(text):
        hits.append((match.start(), float(match.group(1)), -float(match.group(2))))
    out: dict[str, tuple[float, float]] = {}
    for pos, lat, lon in sorted(hits):
        if not (10 < lat < 50 and -130 < lon < -60):
            continue
        codes = [m.group(1).lower() for m in mention.finditer(text, 0, pos) if m.group(1).lower() in known]
        if codes:
            out.setdefault(codes[-1], (round(lat, 6), round(lon, 6)))
    return out


def first_coordinate(text: str) -> tuple[float, float] | None:
    """First plausible coordinate pair in a document (either format)."""
    text = re.sub(r"\s+", " ", text)
    hits = [(m.start(), float(m.group(1)) + float(m.group(2)) / 60, -(float(m.group(3)) + float(m.group(4)) / 60))
            for m in _DM_PAIR_RE.finditer(text)]
    hits += [(m.start(), float(m.group(1)), -float(m.group(2))) for m in _DEC_PAIR_RE.finditer(text)]
    hits = [h for h in sorted(hits) if 10 < h[1] < 50 and -130 < h[2] < -60]
    return (round(hits[0][1], 6), round(hits[0][2], 6)) if hits else None


def metadata_docs(reserve: Reserve, kind: str = "wq", data_dir: Path | None = None) -> list[Path]:
    """Metadata documents, newest data year first."""
    data_dir = Path(data_dir or reserve.data_dir)
    docs = [p for p in data_dir.glob(f"{reserve.code}{kind}*-*.*m.*") if p.suffix in (".doc", ".docx", ".txt")]

    def year(p: Path) -> int:
        yy = int(re.search(r"\.(\d{2})m\.", p.name).group(1))
        return 1900 + yy if yy > 50 else 2000 + yy
    return sorted(docs, key=year, reverse=True)


def load_stat_locs(path: Path = STAT_LOCS_CSV) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["reserve"] = frame["station_code"].str[:3]
    frame["station"] = frame["station_code"].str[3:]
    return frame


def station_table(reserve: Reserve, data_dir: Path | None = None, stat_locs: pd.DataFrame | None = None) -> pd.DataFrame:
    """Adopted coordinates per WQ + met station.

    Primary = newest archive metadata document that states the station position
    (same source family as RL-12); fallback = CDMO station list (SWMPr stat_locs).
    Where stat_locs has several rows (relocated station) the row nearest the
    metadata value is used for the cross-check / fallback.
    """
    data_dir = Path(data_dir or reserve.data_dir)
    if stat_locs is None:
        stat_locs = load_stat_locs() if STAT_LOCS_CSV.exists() else pd.DataFrame(
            columns=["reserve", "station", "latitude", "longitude", "gmt_off"])
    if reserve.code == "job":
        jt = nl.station_table(data_dir)
        meta = {r.station if r.station != "jbmet" else "jb": (r.lat, r.lon, r.coord_source) for r in jt.itertuples()}
    else:
        meta = {}
        for kind, stations in (("wq", reserve.wq_stations), ("met", reserve.met_stations)):
            for doc in metadata_docs(reserve, kind, data_dir):
                text = read_doc_text(doc)
                found = parse_coordinates(text, reserve.code, stations)
                if kind == "met" and not found:  # met docs describe one tower: take its first position
                    first = first_coordinate(text)
                    found = {stations[0]: first} if first else {}
                for code, (lat, lon) in found.items():
                    key = code if kind == "wq" else f"{code}@met"
                    meta.setdefault(key, (lat, lon, doc.name))
        for code, lat, lon, note in reserve.coord_overrides:
            meta[code] = (lat, lon, note)
    rows = []
    for kind, stations in (("wq", reserve.wq_stations), ("met", reserve.met_stations)):
        for code in stations:
            m = meta.get(code if (kind == "wq" or reserve.code == "job") else f"{code}@met") or (
                meta.get(code) if kind == "met" else None)
            cand = stat_locs[(stat_locs["reserve"] == reserve.code) & (stat_locs["station"] == code)]
            sl = None
            if len(cand):
                if m is not None:
                    d = [float(nl.haversine_km(m[0], m[1], r.latitude, r.longitude)) for r in cand.itertuples()]
                    sl = cand.iloc[int(np.argmin(d))]
                else:
                    sl = cand.iloc[0]
            if m is not None:
                lat, lon, source = m
            elif sl is not None:
                lat, lon, source = float(sl.latitude), float(sl.longitude), "CDMO sampling_locations (SWMPr stat_locs)"
            else:
                lat = lon = np.nan
                source = "missing"
            rows.append({
                "reserve": reserve.code, "station": code, "kind": kind, "lat": round(float(lat), 6),
                "lon": round(float(lon), 6), "coord_source": source,
                "stat_locs_lat": None if sl is None else float(sl.latitude),
                "stat_locs_lon": None if sl is None else float(sl.longitude),
                "stat_locs_rows": int(len(cand)),
                "stat_locs_discrepancy_km": None if sl is None or not np.isfinite(lat) else round(
                    float(nl.haversine_km(lat, lon, sl.latitude, sl.longitude)), 3),
            })
    table = pd.DataFrame(rows)
    met = table[table["kind"] == "met"].iloc[0]
    table["km_to_met"] = [round(float(nl.haversine_km(r.lat, r.lon, met.lat, met.lon)), 2) for r in table.itertuples()]
    return table


# ---------------------------------------------------------------- CLI
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--reserve", action="append", required=True, choices=[c for c in RESERVES if c != "job"])
    f.add_argument("--metadata-only", action="store_true")
    s = sub.add_parser("stations")
    s.add_argument("--reserve", required=True, choices=list(RESERVES))
    args = parser.parse_args(argv)
    if args.cmd == "fetch":
        html = _get(NCEI_BASE).decode("utf-8", "replace")
        for code in args.reserve:
            manifest = fetch_reserve(RESERVES[code], metadata_only=args.metadata_only, listing_html=html)
            print(code, len(manifest), "files", f"{manifest['bytes'].sum() / 1e6:.1f} MB",
                  manifest["status"].value_counts().to_dict())
    else:
        print(station_table(RESERVES[args.reserve]).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
