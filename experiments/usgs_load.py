"""Loader for USGS continuous water-quality sites in San Francisco Bay (direction 4, H4.5).

Source: USGS NWIS instantaneous values (IV), legacy Water Services REST API
``https://waterservices.usgs.gov/nwis/iv/`` (requests older than ~120 days are
301-redirected to ``https://nwis.waterservices.usgs.gov/nwis/iv/``), RDB format,
gzip transfer. Raw files are one per site x calendar quarter; the service returns
HTTP 503 for any request covering 10:00-10:59 UTC on the spring-forward DST day, so
quarters containing it are split (``dst_split``; that one UTC hour per year is not
downloaded), and a quarter that still fails is fetched as monthly pieces. The newer OGC API
(``https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items``) also
answered on 2026-10-17 (fields ``approval_status``/``qualifier``) but is paged
JSON; the RDB service was used.

Raw files are write-once under ``paths.FOREIGN_DATA_DIR / "usgs_sfbay" / "raw"``
(``<site>/<site>_<YYYY>Q<n>[a|b|-dst1|-dst2].rdb.gz`` or ``_<YYYY-MM>...``, gzip bytes as served) with an
append-only ``raw/download_manifest.csv`` (url, status, bytes, sha256).

QC / selection (documented in SOURCES.md)
* Only values whose qualification code is exactly ``"A"`` (approved, no
  qualifier) are kept; ``P`` (provisional), ``A e``/``P e`` (estimated), ``Eqp``,
  ``Mnt``, ``***`` etc. are dropped and counted.
* Physical range check on top (USGS review already removes spikes/flatlines):
  Temp -2..35 C, SpC 0..65000 uS/cm, DO 0..25 mg/L, pH 5..10, Turb 0..4000 FNU.
* One series per site x parameter: near-surface first (descriptions containing
  ``UPPER``, unlabelled single sensors, ``BGC PROJECT``), near-bottom
  (``LOWER``/``BOTTOM``) only if the site has no near-surface series. Several
  same-depth series of one parameter (sensor replacements, e.g. turbidity
  YSI 6136 -> EXO in 2021-22) are spliced; where they overlap the newer TS_ID wins.
* Salinity is derived uniformly from specific conductance (00095, already
  referenced to 25 C) with PSS-78 at t = 25 C, R = SpC / 42914 uS/cm (the
  temperature compensation is done by the instrument, so applying PSS-78 at the
  measured temperature would double-correct). Reported salinity (00480, 90860)
  is used only to validate the derivation.
* Timestamps carry a per-row ``tz_cd`` (PST/PDT); converted to UTC. Hourly
  means (UTC hour) need >= 2 accepted raw values.

Run:  .venv\\Scripts\\python experiments\\usgs_load.py download
      .venv\\Scripts\\python experiments\\usgs_load.py summary
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
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import paths  # noqa: E402

USGS_DIR = paths.FOREIGN_DATA_DIR / "usgs_sfbay"
RAW_DIR = USGS_DIR / "raw"
DERIVED_DIR = USGS_DIR / "derived"
USER_AGENT = "Hydro-Aqua-Predict research (academic)"
IV_URL = "https://nwis.waterservices.usgs.gov/nwis/iv/"
SITE_URL = "https://waterservices.usgs.gov/nwis/site/"
PERIOD_START = date(2017, 10, 1)   # WY2018
PERIOD_END = date(2025, 9, 30)     # WY2025
PARAM_CODES = ("00010", "00095", "00300", "00400", "00480", "63680", "90860")

# site_no -> (short code, label, sub-embayment)
SITES = {
    "11455508": ("VSI", "Suisun Bay at Van Sickle Island", "Suisun"),
    "380318121571501": ("CM24A", "Suisun Bay at Channel Marker 24A", "Suisun"),
    "380337122000301": ("B19", "Suisun Bay at Buoy 19", "Suisun"),
    "380356122023701": ("CM16", "Suisun Bay at Channel Marker 16", "Suisun"),
    "380631122032201": ("GRZ", "Grizzly Bay at Suisun Slough", "Suisun"),
    "381142122015801": ("FMB", "First Mallard Branch (Suisun Marsh slough)", "Suisun Marsh"),
    "11455780": ("BEN", "Suisun Bay at Benicia Bridge", "Carquinez"),
    "11455820": ("CRQ", "Carquinez Strait at Carquinez Bridge", "Carquinez"),
    "375607122264701": ("RSR", "SF Bay at Richmond-San Rafael Bridge", "Central"),
    "374938122251801": ("ALC", "SF Bay at NE shore Alcatraz Island", "Central"),
    "374811122235001": ("P17", "SF Bay at Pier 17", "Central"),
    "11162765": ("SMB", "SF Bay at San Mateo Bridge", "South"),
    "373015122071000": ("DMB", "South SF Bay at Dumbarton Bridge", "South"),
}

# pcode -> variable key used downstream
PARAM_VAR = {"00010": "Temp", "00095": "SpC", "00300": "DO", "00400": "pH", "63680": "Turb",
             "00480": "Sal_reported", "90860": "Sal_reported"}
RANGES = {"Temp": (-2.0, 35.0), "SpC": (0.0, 65000.0), "DO": (0.0, 25.0), "pH": (5.0, 10.0),
          "Turb": (0.0, 4000.0), "Sal_reported": (0.0, 42.0)}
TZ_OFFSET_H = {"PST": -8, "PDT": -7, "UTC": 0, "GMT": 0}
GOOD_CODE = "A"
MIN_OBS_PER_HOUR = 2


# ---------------------------------------------------------------- download
def quarters(start: date, end: date) -> list[tuple[str, date, date]]:
    """Calendar quarters intersecting [start, end] as (label, first, last), clipped."""
    out = []
    y, q = start.year, (start.month - 1) // 3 + 1
    while True:
        first = date(y, 3 * (q - 1) + 1, 1)
        if first > end:
            break
        nxt = date(y + (q == 4), 3 * (q % 4) + 1, 1)
        last = date.fromordinal(nxt.toordinal() - 1)
        out.append((f"{y}Q{q}", max(first, start), min(last, end)))
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


def _get(url: str, retries: int = 5, backoff_s: float = 5.0) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    last_exc = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return 404, b""
            last_exc = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_exc = exc
        if attempt < retries - 1:
            time.sleep(backoff_s * (2 ** attempt))
    raise RuntimeError(f"giving up on {url}: {last_exc!r}")


def _as_gzip(payload: bytes) -> bytes:
    return payload if payload[:2] == b"\x1f\x8b" else gzip.compress(payload)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_once(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(data)


def _log(manifest: Path, row: dict) -> None:
    new = not manifest.exists()
    with open(manifest, "a", encoding="utf-8", newline="") as handle:  # append-only
        writer = csv.DictWriter(handle, fieldnames=list(row))
        if new:
            writer.writeheader()
        writer.writerow(row)


def download_catalog(raw_dir: Path = RAW_DIR) -> Path:
    path = raw_dir / "site_series_catalog.rdb.gz"
    if path.exists():
        return path
    url = (f"{SITE_URL}?format=rdb&sites={','.join(SITES)}&seriesCatalogOutput=true"
           "&outputDataTypeCd=iv&siteStatus=all")
    status, payload = _get(url)
    if status != 200:
        raise RuntimeError(f"catalog request failed: {status}")
    data = _as_gzip(payload)
    _write_once(path, data)
    _log(raw_dir / "download_manifest.csv", {"file": path.name, "site": "ALL", "quarter": "",
         "url": url, "status": status, "bytes": len(data), "sha256": sha256_bytes(data),
         "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return path


def read_rdb_table(text: str) -> pd.DataFrame:
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    if len(lines) < 2:
        return pd.DataFrame()
    return pd.read_csv(io.StringIO("\n".join([lines[0]] + lines[2:])), sep="\t", dtype=str)


def read_catalog(path: Path) -> pd.DataFrame:
    cat = read_rdb_table(gzip.decompress(path.read_bytes()).decode("utf-8"))
    cat = cat[cat["data_type_cd"].isin(["iv", "uv"]) & cat["parm_cd"].isin(PARAM_CODES)].copy()
    cat["begin_date"] = pd.to_datetime(cat["begin_date"])
    cat["end_date"] = pd.to_datetime(cat["end_date"])
    for col in ("dec_lat_va", "dec_long_va"):
        cat[col] = cat[col].astype(float)
    return cat


def month_chunks(first: date, last: date) -> list[tuple[str, date, date]]:
    out, cur = [], date(first.year, first.month, 1)
    while cur <= last:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        out.append((f"{cur.year}-{cur.month:02d}", max(cur, first), min(date.fromordinal(nxt.toordinal() - 1), last)))
        cur = nxt
    return out


def spring_forward(year: int) -> date:
    """US DST start: second Sunday of March."""
    first = date(year, 3, 1)
    return date(year, 3, 1 + (6 - first.weekday()) % 7 + 7)


def dst_split(label: str, first: date, last: date) -> list[tuple[str, str, str]]:
    """(label, startDT, endDT) request pieces avoiding the hour the IV service cannot serve.

    Any request covering 10:00-10:59 UTC on the spring-forward day (03:00 PDT, right after
    the skipped local hour) returns HTTP 503 (verified 2026-10-17). That UTC hour is left out.
    """
    d = spring_forward(first.year)
    if not (first <= d <= last):
        return [(label, first.isoformat(), last.isoformat())]
    nxt = date.fromordinal(d.toordinal() + 1)
    out = []
    if first < d:
        out.append((f"{label}a", first.isoformat(), date.fromordinal(d.toordinal() - 1).isoformat()))
    out.append((f"{label}-dst1", f"{d.isoformat()}T08:00Z", f"{d.isoformat()}T09:59Z"))
    out.append((f"{label}-dst2", f"{d.isoformat()}T11:00Z", f"{nxt.isoformat()}T06:59Z"))
    if d < last:
        out.append((f"{label}b", nxt.isoformat(), last.isoformat()))
    return out


def _fetch_chunk(site, label, start_dt, end_dt, path, manifest, written, retries=5, log_failure=True) -> bool:
    url = (f"{IV_URL}?format=rdb&sites={site}&parameterCd={','.join(PARAM_CODES)}"
           f"&startDT={start_dt}&endDT={end_dt}&siteStatus=all")
    row = {"file": f"{site}/{path.name}", "site": site, "quarter": label, "url": url, "status": "",
           "bytes": 0, "sha256": "", "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        status, payload = _get(url, retries=retries)
    except RuntimeError as exc:
        if log_failure:
            _log(manifest, {**row, "status": f"failed: {exc}"[:200]})
            print(f"{site} {label}: FAILED", flush=True)
        return False
    row["status"] = status
    if status == 200 and payload:
        data = _as_gzip(payload)
        _write_once(path, data)
        row.update(bytes=len(data), sha256=sha256_bytes(data))
        written.append(path)
    _log(manifest, row)
    print(f"{site} {label}: {status} {row['bytes']} B", flush=True)
    return status == 200


def download(raw_dir: Path = RAW_DIR, start: date = PERIOD_START, end: date = PERIOD_END,
             pause_s: float = 1.0) -> list[Path]:
    """Quarter requests (split around the spring DST hour); monthly pieces if a quarter fails.

    Overlapping pieces (after a fallback) are harmless: ``splice`` drops duplicate timestamps.
    """
    catalog = read_catalog(download_catalog(raw_dir))
    manifest = raw_dir / "download_manifest.csv"
    written = []
    for site in SITES:
        rows = catalog[catalog["site_no"] == site]
        if rows.empty:
            print(f"{site}: not in catalog, skipped")
            continue
        s_begin, s_end = rows["begin_date"].min().date(), rows["end_date"].max().date()

        def path_of(piece):
            return raw_dir / site / f"{site}_{piece[0]}.rdb.gz"

        for label, first, last in quarters(max(start, s_begin), min(end, s_end)):
            q_pieces = dst_split(label, first, last)
            m_pieces = [p for m, mf, ml in month_chunks(first, last) for p in dst_split(m, mf, ml)]
            if path_of((label,)).exists() or all(path_of(p).exists() for p in q_pieces)                     or all(path_of(p).exists() for p in m_pieces):
                continue
            month_mode = any(path_of(p).exists() for p in m_pieces)
            if not month_mode:
                for piece in q_pieces:
                    if path_of(piece).exists():
                        continue
                    if not _fetch_chunk(site, *piece, path_of(piece), manifest, written, retries=2, log_failure=False):
                        month_mode = True
                        break
                    time.sleep(pause_s)
            if month_mode:
                for piece in m_pieces:
                    if not path_of(piece).exists():
                        _fetch_chunk(site, *piece, path_of(piece), manifest, written, retries=5)
                        time.sleep(pause_s)
    return written


# ---------------------------------------------------------------- parsing
def parse_series_descriptions(text: str) -> pd.DataFrame:
    """TS_ID / parameter / description rows from the RDB header."""
    rows, in_block = [], False
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        body = line[1:].strip()
        if body.startswith("TS_ID") and "Parameter" in body:
            in_block = True
            continue
        if in_block:
            parts = body.split(None, 2)
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                rows.append({"ts_id": parts[0], "pcode": parts[1], "description": parts[2] if len(parts) > 2 else ""})
            else:
                in_block = False
    return pd.DataFrame(rows, columns=["ts_id", "pcode", "description"])


def depth_rank(description: str) -> int:
    """0 = near-surface / single sensor, 1 = near-bottom."""
    d = (description or "").upper()
    return 1 if ("LOWER" in d or "BOTTOM" in d) else 0


def parse_iv_rdb(text: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Long table (site, ts_id, pcode, time_utc, value, code) + series descriptions."""
    desc = parse_series_descriptions(text)
    table = read_rdb_table(text)
    if table.empty or "tz_cd" not in table:  # "No sites found" = no data in the window
        return pd.DataFrame(columns=["site", "ts_id", "pcode", "time_utc", "value", "code"]), desc
    offset = table["tz_cd"].map(TZ_OFFSET_H)
    if offset.isna().any():
        raise ValueError(f"unknown tz_cd: {sorted(set(table.loc[offset.isna(), 'tz_cd']))}")
    t_utc = pd.to_datetime(table["datetime"]) - pd.to_timedelta(offset, unit="h")
    frames = []
    for col in table.columns:
        parts = col.split("_")
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        code_col = f"{col}_cd"
        frames.append(pd.DataFrame({
            "site": table["site_no"].to_numpy(), "ts_id": parts[0], "pcode": parts[1], "time_utc": t_utc.to_numpy(),
            "value": pd.to_numeric(table[col], errors="coerce").to_numpy(),
            "code": table[code_col].fillna("").str.strip().to_numpy() if code_col in table else ""}))
    long = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    long = long[long["value"].notna() | (long["code"] != "")]
    return long.reset_index(drop=True), desc


def select_series(desc: pd.DataFrame) -> pd.DataFrame:
    """Per (site, pcode): the near-surface series if any, else near-bottom; all of that depth."""
    d = desc.drop_duplicates(["site", "ts_id", "pcode"]).copy()
    d["depth_rank"] = d["description"].map(depth_rank)
    best = d.groupby(["site", "pcode"])["depth_rank"].transform("min")
    return d[d["depth_rank"] == best].reset_index(drop=True)


def splice(long: pd.DataFrame) -> pd.DataFrame:
    """One value per (site, pcode, time): the newest (largest) TS_ID wins on overlap."""
    order = long.assign(_ts=long["ts_id"].astype(np.int64)).sort_values(["site", "pcode", "time_utc", "_ts"])
    return order.drop_duplicates(["site", "pcode", "time_utc"], keep="last").drop(columns="_ts")


# ---------------------------------------------------------------- chemistry / QC
_A = (0.0080, -0.1692, 25.3851, 14.0941, -7.0261, 2.7081)
_B = (0.0005, -0.0056, -0.0066, -0.0375, 0.0636, -0.0144)
C35_15_US_CM = 42914.0


def pss78_salinity(conductivity_us_cm, temp_c=25.0) -> np.ndarray:
    """Practical salinity (PSS-78, UNESCO 1983) from conductivity at temperature t, pressure 0.

    Valid 2-42; values below 2 are returned as computed (low-salinity extension
    of Hill et al. 1986 not applied; SF Bay/Suisun minima are ~0.1 and the error
    there is < 0.01 psu, far below the 1 psu tolerance).
    """
    c = np.asarray(conductivity_us_cm, dtype=float)
    t = np.asarray(temp_c, dtype=float)
    r = c / C35_15_US_CM
    rt35 = 0.6766097 + 2.00564e-2 * t + 1.104259e-4 * t ** 2 - 6.9698e-7 * t ** 3 + 1.0031e-9 * t ** 4
    rt = np.clip(r / rt35, 0, None)
    sq = np.sqrt(rt)
    s = sum(a * sq ** i for i, a in enumerate(_A))
    ds = (t - 15) / (1 + 0.0162 * (t - 15)) * sum(b * sq ** i for i, b in enumerate(_B))
    return s + ds


def qc_mask(var: pd.Series, value: pd.Series, code: pd.Series) -> pd.Series:
    lo = var.map(lambda v: RANGES[v][0])
    hi = var.map(lambda v: RANGES[v][1])
    return (code == GOOD_CODE) & value.between(lo, hi) & value.notna()


def hourly_means(long: pd.DataFrame, min_obs: int = MIN_OBS_PER_HOUR) -> pd.DataFrame:
    """(site, var, hour_utc) mean of accepted values; hours with < min_obs dropped."""
    g = (long.assign(hour_utc=long["time_utc"].dt.floor("h"))
         .groupby(["site", "var", "hour_utc"])["value"].agg(["mean", "count"]).reset_index())
    g = g[g["count"] >= min_obs]
    return g.rename(columns={"mean": "value", "count": "n_raw"})


# ---------------------------------------------------------------- assembly
def raw_files(raw_dir: Path = RAW_DIR) -> list[Path]:
    return sorted(p for p in raw_dir.glob("*/*.rdb.gz"))


def load_raw(raw_dir: Path = RAW_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    longs, descs = [], []
    for path in raw_files(raw_dir):
        long, desc = parse_iv_rdb(gzip.decompress(path.read_bytes()).decode("utf-8"))
        site = path.parent.name
        longs.append(long)
        descs.append(desc.assign(site=site))
    return pd.concat(longs, ignore_index=True), pd.concat(descs, ignore_index=True)


def build_hourly(raw_dir: Path = RAW_DIR) -> tuple[pd.DataFrame, dict]:
    """Hourly (site, var, hour_utc, value) for Temp, Sal, DO, pH, Turb + QC report."""
    long, desc = load_raw(raw_dir)
    chosen = select_series(desc)
    long = long.merge(chosen[["site", "ts_id", "pcode"]], on=["site", "ts_id", "pcode"], how="inner")
    long = splice(long)
    long["var"] = long["pcode"].map(PARAM_VAR)
    long["ok"] = qc_mask(long["var"], long["value"], long["code"])
    long["year"] = long["time_utc"].dt.year
    code_class = np.select([long["code"] == "A", long["code"].str.startswith("A"), long["code"].str.startswith("P")],
                           ["A", "A_qualified", "P"], "other")
    qc = (long.assign(code_class=code_class).groupby(["site", "var", "year", "code_class"]).size()
          .unstack("code_class", fill_value=0).reset_index())
    qc["n_accepted"] = long.groupby(["site", "var", "year"])["ok"].sum().to_numpy()
    good = long[long["ok"]]
    # salinity from SpC (PSS-78 at 25 C, see module docstring)
    spc = good[good["var"] == "SpC"]
    sal = spc.assign(var="Sal", value=pss78_salinity(spc["value"].to_numpy(), 25.0))
    hourly = hourly_means(pd.concat([good[good["var"].isin(["Temp", "DO", "pH", "Turb", "Sal_reported"])], sal]))
    report = {"series": chosen.assign(depth=np.where(chosen["depth_rank"] == 1, "near-bottom", "near-surface")),
              "qc_counts": qc, "n_raw_rows": int(len(long)), "n_accepted": int(long["ok"].sum())}
    return hourly, report


def salinity_validation(hourly: pd.DataFrame) -> pd.DataFrame:
    """Derived (SpC -> PSS-78) vs reported salinity, per site, matched hours."""
    w = hourly.pivot_table(index=["site", "hour_utc"], columns="var", values="value")
    if "Sal_reported" not in w:
        return pd.DataFrame()
    w = w.dropna(subset=["Sal", "Sal_reported"])
    d = w["Sal"] - w["Sal_reported"]
    return (d.groupby(level="site").agg(n_hours="size", bias="mean", mae=lambda x: x.abs().mean(),
                                        p95_abs=lambda x: x.abs().quantile(0.95)).round(3).reset_index())


def station_table(catalog: pd.DataFrame) -> pd.DataFrame:
    s = catalog.drop_duplicates("site_no")[["site_no", "station_nm", "dec_lat_va", "dec_long_va"]]
    s = s.rename(columns={"site_no": "site", "dec_lat_va": "lat", "dec_long_va": "lon"})
    s["code"] = s["site"].map(lambda x: SITES[x][0])
    s["embayment"] = s["site"].map(lambda x: SITES[x][2])
    return s.reset_index(drop=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("action", choices=["download", "summary"])
    args = ap.parse_args(argv)
    if args.action == "download":
        files = download()
        print(f"new files: {len(files)}")
    total = sum(p.stat().st_size for p in raw_files())
    print(f"raw files: {len(raw_files())}, {total / 1e6:.1f} MB")
    if args.action == "summary":
        hourly, report = build_hourly()
        print(report["series"].to_string())
        print(report["qc_counts"].to_string())
        print(salinity_validation(hourly).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
