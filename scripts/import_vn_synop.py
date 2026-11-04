"""Import the 4TA SYNOP archive (172 VN stations, 3-hourly, 2000-2025) into data/vn_synop/.

    python scripts/import_vn_synop.py --archive C:/Users/<you>/Downloads/4TA.rar

Steps, all write-once (refuses to overwrite):
  1. copy the archive to data/vn_synop/raw/ and record size + sha256 in raw/manifest.json
  2. stream every text file out of it with Windows tar (bsdtar reads RAR) and parse rows
  3. write derived/synop_3h_v1.parquet (all stations, raw values kept) + derived/summary_v1.json

Values are never edited. QC only adds flag columns; see docs/decisions.md #30.
Obs times in the files are local (UTC+7): obs "...07" is the 00 UTC report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402

RAW_DIR = paths.VN_SYNOP_DIR / "raw"
DERIVED_DIR = paths.VN_SYNOP_DIR / "derived"
VERSION = "v2"  # v1: ps_hpa lower bound 900 flagged highland stations

NUMERIC = ["lat", "lon", "rain6h_mm", "rain24h_mm", "t2m_c", "rh_pct", "ps_hpa", "wspd_ms", "tmin_c", "tmax_c"]
VALUE_COLS = ["lat", "lon", "rain6h_mm", "rain24h_mm", "t2m_c", "rh_pct", "ps_hpa", "wdir", "wspd_ms", "tmin_c", "tmax_c"]
# plausible physical ranges; outside -> flagged, value kept
QC_RANGES = {
    "t2m_c": (-10.0, 45.0),
    "tmin_c": (-10.0, 45.0),
    "tmax_c": (-10.0, 45.0),
    "rh_pct": (1.0, 100.0),
    # station-level pressure: Sa Pa / Da Lat sit at ~840-850 hPa, so no sea-level bound (v1 used 900)
    "ps_hpa": (500.0, 1060.0),
    "rain6h_mm": (0.0, 500.0),
    "rain24h_mm": (0.0, 1000.0),
    # strongest VN station gusts on record are ~50-60 m/s (Yagi 2024: Bai Chay 45 m/s 10-min mean);
    # 60-99 values appear on calm days and look like dddff decoding errors
    "wspd_ms": (0.0, 60.0),
}
BATCH_ROWS = 500_000


def parse_line(line: str) -> list[str] | None:
    """One data row -> 14 strings; None for header/comment lines or malformed rows.

    obs / name / code are fixed width; the rest are whitespace separated and the
    wind direction column is blank (not 'NaN') when the whole report is missing.
    """
    if not line[:1].isdigit():
        return None
    head = [line[0:15].strip(), line[15:27].strip(), line[27:39].strip()]
    rest = line[39:].split()
    if len(rest) == 10:
        rest.insert(7, "")
    if len(rest) != 11 or len(head[0]) != 10:
        return None
    return head + rest


def to_frame(rows: list[list[str]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["obs", "station_name", "station_code", *VALUE_COLS])
    df["obs_local"] = pd.to_datetime(df.pop("obs"), format="%Y%m%d%H")
    df["obs_utc"] = df["obs_local"] - pd.Timedelta(hours=7)
    for col in NUMERIC:
        # 'x', 'xx', 'xxxxx' = not reported
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")
    df["wdir"] = df["wdir"].replace({"": None, "NaN": None})
    flags = pd.Series("", index=df.index)
    for col, (lo, hi) in QC_RANGES.items():
        bad = df[col].notna() & ((df[col] < lo) | (df[col] > hi))
        flags = flags.where(~bad, flags + col + ";")
    df["qc_flags"] = flags
    return df[["obs_local", "obs_utc", "station_code", "station_name", *VALUE_COLS, "qc_flags"]]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_archive(src: Path) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dst = RAW_DIR / src.name
    manifest_path = RAW_DIR / "manifest.json"
    src_hash = sha256(src)
    if dst.exists():
        if sha256(dst) != src_hash:
            sys.exit(f"{dst} exists with a different sha256; not overwriting")
        print(f"archive already in place: {dst}")
    else:
        shutil.copy2(src, dst)
    if not manifest_path.exists():
        manifest_path.write_text(json.dumps({
            "file": dst.name,
            "bytes": dst.stat().st_size,
            "sha256": src_hash,
            "copied_from": str(src),
            "copied_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "content": "SO LIEU QUAN TRAC BE MAT TAI 172 TRAM KHI TUONG SYNOP, 3-hourly txt per UTC hour",
            "provenance": "supplied by the project owner; source and licence not yet confirmed",
        }, indent=2), encoding="utf-8")
    return dst


def stream_rows(archive: Path):
    tar = shutil.which("tar", path=r"C:\Windows\System32") or "tar"
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen([tar, "-xOf", str(archive)], stdout=subprocess.PIPE, stderr=err)
        assert proc.stdout is not None
        for raw in proc.stdout:
            row = parse_line(raw.decode("latin-1").rstrip("\r\n"))
            if row is not None:
                yield row
        proc.wait()
        err.seek(0)
        errors = err.read().decode("latin-1").splitlines()
    # bsdtar fails on RAR directory entries with -O but still streams every file; anything else is fatal
    real = [e for e in errors if "entry marked as a directory" not in e and "Error exit delayed" not in e]
    if real or (proc.returncode != 0 and not errors):
        sys.exit("tar failed:\n" + "\n".join(real or [f"exit {proc.returncode}"]))
    if errors:
        print(f"tar: ignored {len(errors)} directory-entry messages", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()

    out = DERIVED_DIR / f"synop_3h_{VERSION}.parquet"
    summary_path = DERIVED_DIR / f"summary_{VERSION}.json"
    if out.exists() or summary_path.exists():
        sys.exit(f"{out.name} already exists; bump VERSION instead of overwriting")
    archive = copy_archive(args.archive)
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)

    tmp = out.with_suffix(".parquet.partial")
    if tmp.exists():
        sys.exit(f"{tmp} left by an earlier failed run; move it aside first")
    writer = None
    batch: list[list[str]] = []
    n_rows = 0
    per_station: dict[str, dict] = {}
    qc_counts: dict[str, int] = {}

    def flush() -> None:
        nonlocal writer, n_rows
        df = to_frame(batch)
        table = pa.Table.from_pandas(df, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(tmp, table.schema, compression="zstd")
        writer.write_table(table)
        n_rows += len(df)
        reported = df["t2m_c"].notna() | df["wspd_ms"].notna() | df["ps_hpa"].notna()
        for (code, name), g in df.assign(reported=reported).groupby(["station_code", "station_name"]):
            s = per_station.setdefault(code, {"name": name, "rows": 0, "reported": 0, "first": None, "last": None})
            s["rows"] += len(g)
            s["reported"] += int(g["reported"].sum())
            first, last = g["obs_local"].min().isoformat(), g["obs_local"].max().isoformat()
            s["first"] = first if s["first"] is None else min(s["first"], first)
            s["last"] = last if s["last"] is None else max(s["last"], last)
        for flag in df["qc_flags"].str.split(";").explode():
            if flag:
                qc_counts[flag] = qc_counts.get(flag, 0) + 1
        batch.clear()
        print(f"  {n_rows:,} rows", flush=True)

    for row in stream_rows(archive):
        batch.append(row)
        if len(batch) >= BATCH_ROWS:
            flush()
    if batch:
        flush()
    if writer is None:
        sys.exit("no rows parsed")
    writer.close()
    tmp.rename(out)

    summary_path.write_text(json.dumps({
        "version": VERSION,
        "archive": archive.name,
        "archive_sha256": json.loads((RAW_DIR / "manifest.json").read_text(encoding="utf-8"))["sha256"],
        "rows": n_rows,
        "stations": len(per_station),
        "qc_flag_counts": qc_counts,
        "qc_ranges": QC_RANGES,
        "per_station": dict(sorted(per_station.items())),
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out} ({n_rows:,} rows, {len(per_station)} stations)")


if __name__ == "__main__":
    main()
