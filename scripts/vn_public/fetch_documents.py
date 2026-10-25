"""Collect public Vietnamese documents about the Cát Bà / Hạ Long farming zones (write-once).

Downloads a short, hand-verified list of open documents (papers, one archived project page,
one NCHMF tide bulletin as a format sample) into ``paths.VN_PUBLIC_DIR/<source>/`` with a
``.manifest.json`` per file and a ``SOURCES.md`` per source folder. Also writes
``rimf_farm_zones/farm_zone_sampling_points.csv``: the published sampling points of the
RIMF (Viện Nghiên cứu Hải sản) cage-farm monitoring, with distance to NB1.

These documents carry figures and summary statistics, not raw tables; the raw series must be
requested from RIMF (see docs/eval/2026-10-25-vn-public-data.md, request letter).

Usage (from the repo root, data dir of the main checkout):
    python scripts/vn_public/fetch_documents.py [--dry-run]
Existing files are skipped, never overwritten.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core import paths  # noqa: E402
from scripts.vn_public.common import (  # noqa: E402
    NB1_LAT, NB1_LON, haversine_km, manifest_path, write_manifest, write_once_bytes,
)

UA = {"User-Agent": "Hydro-Aqua-Predict research (desk review; contact repo owner)"}


@dataclass(frozen=True)
class Doc:
    source: str
    filename: str
    url: str
    terms: str
    note: str


DOCS = [
    Doc("rimf_farm_zones", "rimf_2024_quan-trac-vung-nuoi-bien_wayback20260614.html",
        "http://web.archive.org/web/20260614105511id_/https://www.rimf.org.vn/ketquanc/chitiet/"
        "quan-trac-canh-bao-va-giam-sat-moi-truong-vung-nuoi-trong-thuy-san-tren-bien-tai-mot-so-tinh-trong-%C4%91iem-nam-2024",
        "Public institute web page (no licence stated); Internet Archive copy because rimf.org.vn "
        "pages returned HTTP 404 on 2026-10-25 (static /Media files still served).",
        "Project summary 2024: 27 bulletins, 7 monthly reports, QN + HP + Kiên Giang sea-farm zones, months 5-11/2024."),
    Doc("rimf_farm_zones", "vimaru_2023_tran-quang-thu_catba-longson.pdf",
        "https://vjol.info.vn/vimaru/article/download/89606/76104/",
        "Open-access journal article (Tạp chí KHCN Hàng hải, số 76, 11/2023) via VJOL; licence not stated - local copy only.",
        "Cát Bà CB1-CB5 coordinates; RIMF programme 'Quan trắc môi trường khu vực nuôi cá biển tập trung 2016-2021'; figures only."),
    Doc("rimf_farm_zones", "tapchixaydung_2026_tran-huu-long_haiphong-cage.pdf",
        "https://cmsnews.tapchixaydung.vn/upload/pdf/2026/06/05/35.-tran-huu-long_05062026153553.pdf",
        "Open-access journal article (Tạp chí Xây dựng 05/2026); licence not stated - local copy only.",
        "Hang Vẹm-Vụng O (CB1, CB2) and Hòn Thoi Quýt-Gia Luận (CB3, CB4) DMS coordinates; monthly Apr-Aug, surface+bottom; figures only."),
    Doc("rimf_farm_zones", "vjs_2014_le-tuan-son_catba-cage-pollution.pdf",
        "https://vjs.ac.vn/index.php/jmst/article/download/3983/5283/20919",
        "Open-access journal article (Tạp chí KH&CN Biển 14(3) 2014, DOI 10.15625/1859-3097/14/3/3983); local copy only.",
        "RIMF annual monitoring May/Sep 2013 at Bến Bèo 1-2, Tùng Tràng, Hải Quân, Vụng Giá; DO 3.64-5.91 mg/L; 2005-2013 trend figures."),
    Doc("nchmf_tide", "dbqg-tthv-20260325_0930.pdf",
        "https://kttv.gov.vn//upload/haivan/2026/3/25/dbqg-tthv-20260325_0930.pdf",
        "Public government bulletin (NCHMF); sample of the 10-day tide forecast format only.",
        "10-day high/low water times and heights incl. Hòn Dấu and Cô Tô; text layer present (pdftotext works)."),
]

# Published sampling points (decimal-minute / DMS strings exactly as printed in the papers).
POINTS = [
    # source_doc, point_id, zone, lat_str, lon_str, period, cadence
    ("vimaru_2023", "CB1", "Cát Bà (RIMF 2021 points)", "20°44.388'", "107°03.595'", "2016-2021", "2/yr (Apr-May, Sep-Oct), surface+bottom, high+low tide"),
    ("vimaru_2023", "CB2", "Cát Bà, Bến Bèo (paper text: high-density cages)", "20°45.524'", "107°02.831'", "2016-2021", "2/yr"),
    ("vimaru_2023", "CB3", "Cát Bà (RIMF 2021 points)", "20°46.253'", "107°04.313'", "2016-2021", "2/yr"),
    ("vimaru_2023", "CB4", "Cát Bà (RIMF 2021 points)", "20°46.250'", "107°04.314'", "2016-2021", "2/yr"),
    ("vimaru_2023", "CB5", "Cát Bà (RIMF 2021 points)", "20°46.722'", "107°04.797'", "2016-2021", "2/yr"),
    ("tapchixaydung_2026", "CB1", "Hang Vẹm - Vụng O", "20°44'18.25\"", "107°3'35.41\"", "Apr-Aug (year not stated)", "monthly, surface+bottom"),
    ("tapchixaydung_2026", "CB2", "Hang Vẹm - Vụng O", "20°44'17.49\"", "107°3'44.16\"", "Apr-Aug (year not stated)", "monthly, surface+bottom"),
    ("tapchixaydung_2026", "CB3", "Hòn Thoi Quýt - Gia Luận", "20°51'48.48\"", "106°58'48.13\"", "Apr-Aug (year not stated)", "monthly, surface+bottom"),
    ("tapchixaydung_2026", "CB4", "Hòn Thoi Quýt - Gia Luận", "20°51'46.32\"", "106°58'59.23\"", "Apr-Aug (year not stated)", "monthly, surface+bottom"),
]

_ANGLE = re.compile(r"^\s*(\d+)\s*°\s*(\d+(?:\.\d+)?)\s*'?\s*(?:(\d+(?:\.\d+)?)\s*\")?\s*$")


def parse_angle(text: str) -> float:
    """Parse ``20°44.388'`` (decimal minutes) or ``20°44'18.25"`` (DMS) to decimal degrees."""
    m = _ANGLE.match(text)
    if not m:
        raise ValueError(f"unparsed angle: {text!r}")
    deg, minutes, seconds = float(m.group(1)), float(m.group(2)), float(m.group(3) or 0.0)
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"out-of-range minutes/seconds: {text!r}")
    return deg + minutes / 60 + seconds / 3600


def sampling_points_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["source_doc", "point_id", "zone", "lat", "lon", "lat_printed", "lon_printed",
                "dist_nb1_km", "period", "cadence"])
    for src, pid, zone, lat_s, lon_s, period, cadence in POINTS:
        lat, lon = parse_angle(lat_s), parse_angle(lon_s)
        w.writerow([src, pid, zone, f"{lat:.5f}", f"{lon:.5f}", lat_s, lon_s,
                    f"{haversine_km(NB1_LAT, NB1_LON, lat, lon):.2f}", period, cadence])
    return buf.getvalue()


def sources_md(source: str) -> str:
    rows = [d for d in DOCS if d.source == source]
    lines = [f"# {source}", "", "Collected by `scripts/vn_public/fetch_documents.py` (write-once).",
             "See docs/eval/2026-10-25-vn-public-data.md.", ""]
    for d in rows:
        lines += [f"- `{d.filename}`", f"  - URL: {d.url}", f"  - Terms: {d.terms}", f"  - Content: {d.note}"]
    if source == "rimf_farm_zones":
        lines += ["- `farm_zone_sampling_points.csv` - points transcribed from the two papers above;",
                  "  vimaru 2023 prints decimal minutes (20°44.388'), tapchixaydung 2026 prints DMS.",
                  "  The two CB1 positions agree to ~150 m, which confirms the decimal-minute reading."]
    return "\n".join(lines) + "\n"


def _save(target: Path, data: bytes, dry_run: bool, **manifest) -> str:
    if target.exists() or manifest_path(target).exists():
        return f"skip (exists) {target}"
    if dry_run:
        return f"would write {target} ({len(data)} B)"
    write_once_bytes(target, data)
    write_manifest(target, **manifest)
    return f"wrote {target} ({len(data)} B)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from-file", action="append", default=[], metavar="FILENAME=PATH",
                    help="use a local copy (e.g. fetched by a browser) when the host is unreachable from this machine")
    args = ap.parse_args()
    local = dict(item.split("=", 1) for item in args.from_file)
    root = paths.VN_PUBLIC_DIR
    for d in DOCS:
        target = root / d.source / d.filename
        if target.exists():
            print("skip (exists)", target)
            continue
        if d.filename in local:
            data = Path(local[d.filename]).read_bytes()
            print(_save(target, data, args.dry_run, url=d.url, terms=d.terms, note=d.note,
                        obtained="local copy of the URL (host unreachable from the collector); same retrieval day"))
            continue
        try:
            resp = requests.get(d.url, headers=UA, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as exc:
            print("FAILED", d.url, type(exc).__name__)
            continue
        print(_save(target, resp.content, args.dry_run, url=d.url, terms=d.terms, note=d.note,
                    content_type=resp.headers.get("Content-Type", "")))
    pts = root / "rimf_farm_zones" / "farm_zone_sampling_points.csv"
    print(_save(pts, sampling_points_csv().encode("utf-8"), args.dry_run,
                url="derived: transcribed from vimaru_2023 + tapchixaydung_2026 PDFs in this folder",
                terms="derived from open-access papers", note="sampling points; distance to NB1 by haversine"))
    for source in sorted({d.source for d in DOCS}):
        md = root / source / "SOURCES.md"
        if md.exists():
            print("skip (exists)", md)
        elif args.dry_run:
            print("would write", md)
        else:
            write_once_bytes(md, sources_md(source).encode("utf-8"))
            print("wrote", md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
