"""Paper 2 / F5 step 0: is continuous NH4 from the Korean MOF automatic stations usable? (research-only).

PRE-REGISTRATION (fixed 2026-11-02, committed before any full file is read; ``preregistration.json`` in the run dir
records it with the git head; later changes go to NOTES.md "sai lệch"):

Source.  data.go.kr file datasets "해양수산부_공동활용체계_수질자동측정망(<station>)", MOF, licence "이용허락범위 제한
없음", public download without login.  The six files whose description lists 암모니아성질소 (survey
``docs/paper/2026-11-02-nh4-continuous-candidates.md``): 15159658 Songdo, 15159657 Busan Suyeong, 15159642 Ulsan Onsan,
15159129 Oido, 15159125 Nakdong, 15159128 Yeongdo.  No QC flags.  Raw files go write-once to
``paths.DATA_DIR / "foreign" / "kr_mof" / "raw"`` with ``manifest.json`` (url, time, size, sha256, licence).  A
captcha / download-limit page stops the download (never bypassed).  Files are untrusted: read only with csv/pandas.

Series.  One series per file x 조사수층 (depth layer; a file without that column = one layer).  Time column 관측일시,
NH4 column = the one containing "암모니아".  Duplicate timestamps: median.  A raw NH4 value is valid if finite and >= 0.
Hourly value = median of the valid raw values in the clock hour (rows are 5 min, NH4 is an hourly analyser held
between readings, so the hourly series is the unit).
  stuck     a run of >= 6 consecutive clock hours (no missing hour inside) with identical hourly value -> all hours
            of the run are invalid.
  valid hour = hourly value present and not in a stuck run.
Pass (per series).  Exists a 365-day window (day-aligned start, 8760 h) with valid-hour fraction >= 0.70 AND no gap
> 30 days between consecutive valid hours inside the window (window edges count as valid points, so a hole at
either end also counts).  A station passes if any of its layers passes.
Verdict.  F5 feasible iff >= 3 stations pass.

Also reported (no gate): rows, span, raw sample interval, typical interval between NH4 value changes, NH4 unit
(header / page note / magnitude), percentiles, negative / NaN / zero shares, segments (split at gaps > 30 d) with
span and valid fraction, stuck share + longest stuck run, ceiling share (hours at the series max value), x3 hourly
jump rate, persistent x3 level shifts (median 24 h after vs 24 h before differ >= x3), value resolution, and hourly
coverage of temperature / salinity / DO / pH / turbidity in the best window.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import http.cookiejar
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from experiments.paper2_faults import git_head  # noqa: E402

RUN_NAME = "paper2-f5step0-20261102"
SCRIPT = "experiments/paper2_kr_nh4_step0.py"
KR_DIR = paths.DATA_DIR / "foreign" / "kr_mof"
RAW_DIR = KR_DIR / "raw"
LICENCE = "이용허락범위 제한 없음 (data.go.kr catalog JSON license.name)"

WINDOW_DAYS = 365
MAX_GAP_DAYS = 30
MIN_VALID_FRACTION = 0.70
STUCK_HOURS = 6
MIN_STATIONS = 3
JUMP_RATIO = 3.0
SHIFT_WINDOW_H = 24

DATASETS = {
    "15159658": ("songdo", "인천송도", "uddi:6a3ca5b1-64e0-4a4f-a3a9-e13f6f79e62a"),
    "15159657": ("busan_suyeong", "부산수영", "uddi:9de84a73-9b2b-44d8-b921-85d51a256c8d"),
    "15159642": ("ulsan_onsan", "울산온산", "uddi:8d39b672-bc34-4967-b97d-f4e1d30cb396"),
    "15159129": ("oido", "오이도", "uddi:c37153f6-053c-43e2-af29-ba60e1b51f39"),
    "15159125": ("nakdong", "낙동강", "uddi:a7be0c45-54e6-4db6-93a1-c3645a987a88"),
    "15159128": ("yeongdo", "영도", "uddi:4a893024-37cb-43a3-a538-a3a100b9a84c"),
}
AUX = {"temp": ("수온",), "sal": ("염분",), "do": ("용존산소",), "ph": ("수소이온", "pH"), "turb": ("탁도",)}
MAX_DOWNLOAD_BYTES = 2 * 1024 ** 3
PAUSE_S = 45
UA = "Mozilla/5.0 (research data download; HAP paper 2)"


# ----------------------------------------------------------------------------------------------- scoring core
def hourly_series(times: pd.Series, values: pd.Series) -> pd.Series:
    """Median of valid (finite, >= 0) raw values per clock hour, on a complete hourly index (NaN where none)."""
    t = pd.to_datetime(times, errors="coerce")
    v = pd.to_numeric(values, errors="coerce")
    ok = t.notna() & v.notna() & np.isfinite(v) & (v >= 0)
    s = pd.Series(v[ok].to_numpy(dtype=float), index=t[ok].dt.floor("h"))
    if s.empty:
        return pd.Series(dtype=float)
    h = s.groupby(level=0).median().sort_index()
    return h.reindex(pd.date_range(h.index[0], h.index[-1], freq="h"))


def stuck_mask(hourly: pd.Series, min_hours: int = STUCK_HOURS) -> pd.Series:
    """True on hours inside a run of >= min_hours consecutive present hours with identical value."""
    x = hourly.to_numpy(dtype=float)
    out = np.zeros(len(x), dtype=bool)
    i = 0
    while i < len(x):
        if np.isnan(x[i]):
            i += 1
            continue
        j = i
        while j + 1 < len(x) and not np.isnan(x[j + 1]) and x[j + 1] == x[i]:
            j += 1
        if j - i + 1 >= min_hours:
            out[i:j + 1] = True
        i = j + 1
    return pd.Series(out, index=hourly.index)


def valid_hours(hourly: pd.Series) -> pd.Series:
    return hourly.notna() & ~stuck_mask(hourly)


def best_window(valid: pd.Series, window_days: int = WINDOW_DAYS, max_gap_days: float = MAX_GAP_DAYS) -> dict:
    """Scan day-aligned windows of window_days; return the best one (passing first, then highest fraction)."""
    empty = {"pass": False, "start": None, "end": None, "valid_fraction": 0.0, "max_gap_days": None}
    if valid.empty or not valid.any():
        return empty
    n = window_days * 24
    t0 = valid.index[0].floor("D")
    idx = pd.date_range(t0, valid.index[-1].floor("D") + pd.Timedelta(days=window_days), freq="h", inclusive="left")
    v = valid.reindex(idx, fill_value=False).to_numpy(dtype=bool)
    if len(v) < n:
        return empty
    csum = np.concatenate([[0], np.cumsum(v)])
    pos = np.flatnonzero(v)
    best = None
    for s in range(0, len(v) - n + 1, 24):
        e = s + n
        frac = (csum[e] - csum[s]) / n
        lo, hi = np.searchsorted(pos, s), np.searchsorted(pos, e)
        pts = np.concatenate([[s - 1], pos[lo:hi], [e]])  # edges count as valid points
        gap_days = float(np.max(np.diff(pts)) - 1) / 24.0
        ok = frac >= MIN_VALID_FRACTION and gap_days <= max_gap_days
        key = (ok, frac)
        if best is None or key > best[0]:
            best = (key, s, e, frac, gap_days)
    (ok, _), s, e, frac, gap_days = best
    return {"pass": bool(ok), "start": str(idx[s]), "end": str(idx[e - 1] + pd.Timedelta(hours=1)),
            "valid_fraction": round(float(frac), 4), "max_gap_days": round(gap_days, 2)}


def segments(valid: pd.Series, max_gap_days: float = MAX_GAP_DAYS) -> list[dict]:
    t = valid.index[valid.to_numpy(dtype=bool)]
    if len(t) == 0:
        return []
    cut = np.flatnonzero(np.diff(t.asi8) > max_gap_days * 86400e9)
    out, a = [], 0
    for b in list(cut) + [len(t) - 1]:
        s, e = t[a], t[b]
        hours = (e - s) / pd.Timedelta(hours=1) + 1
        out.append({"start": str(s), "end": str(e), "span_days": round(hours / 24, 1),
                    "valid_fraction": round((b - a + 1) / hours, 4)})
        a = b + 1
    return out


def fault_stats(hourly: pd.Series) -> dict:
    """Diagnostics for the fault paper on the hourly series (stuck hours included in the denominators)."""
    present = hourly.dropna()
    st = stuck_mask(hourly)
    runs, cur = [], 0
    for f in st.to_numpy():
        if f:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    out = {"present_hours": int(len(present)),
           "stuck_share": round(float(st.sum() / max(len(present), 1)), 4),
           "longest_stuck_h": int(max(runs) if runs else 0)}
    if present.empty:
        return out
    mx = float(present.max())
    out.update({"max": mx, "ceiling_hours": int((present == mx).sum()),
                "ceiling_share": round(float((present == mx).mean()), 5),
                "zero_share": round(float((present == 0).mean()), 4)})
    x = hourly.to_numpy(dtype=float)
    a, b = x[:-1], x[1:]
    pair = np.isfinite(a) & np.isfinite(b) & (a > 0) & (b > 0)
    lr = np.abs(np.log(b[pair] / a[pair])) if pair.any() else np.array([])
    days = len(present) / 24.0
    out["jump_x3_pairs"] = int((lr >= np.log(JUMP_RATIO)).sum())
    out["jump_x3_per_30d"] = round(float(out["jump_x3_pairs"] / days * 30), 3) if days else None
    w = SHIFT_WINDOW_H
    pre = hourly.rolling(w, min_periods=w // 2).median()
    post = hourly[::-1].rolling(w, min_periods=w // 2).median()[::-1].shift(-1)
    ratio = (post / pre).replace([np.inf, -np.inf], np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        big = np.abs(np.log(ratio.to_numpy(dtype=float))) >= np.log(JUMP_RATIO)
    jump_at = np.zeros(len(x), dtype=bool)  # jump_at[h]: |log(x[h] / x[h-1])| >= log 3
    jump_at[1:][pair] = lr >= np.log(JUMP_RATIO)
    # persistent: median of the 24 h from h vs median of the 24 h up to h-1 also differ >= x3
    cand = np.flatnonzero(jump_at[1:] & big[:-1]) + 1
    shifts = cand[np.insert(np.diff(cand) > w, 0, True)] if len(cand) else cand
    out["persistent_shift_x3"] = int(len(shifts))
    d = np.diff(np.unique(present.to_numpy()))
    out["resolution"] = float(d[d > 0].min()) if (d > 0).any() else None
    q = present.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
    out.update({f"p{int(k * 100):02d}": round(float(val), 4) for k, val in q.items()})
    return out


# ----------------------------------------------------------------------------------------------- download
def _opener():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def download_one(pk: str, detail_pk: str, opener) -> dict:
    page = f"https://www.data.go.kr/data/{pk}/fileData.do"
    opener.open(urllib.request.Request(page, headers={"User-Agent": UA}), timeout=120).read()
    body = urllib.parse.urlencode({"publicDataDetailPk": detail_pk, "publicDataPk": pk, "atchFileId": "",
                                   "fileDetailSn": "1", "publicDataTyCode": "PR0051"}).encode()
    req = urllib.request.Request("https://www.data.go.kr/tcs/dss/selectFileDataDownload.do", data=body,
                                 headers={"User-Agent": UA, "Referer": page, "X-Requested-With": "XMLHttpRequest"})
    meta = json.loads(opener.open(req, timeout=120).read().decode("utf-8"))
    if not meta.get("status"):
        raise RuntimeError(f"selectFileDataDownload refused for {pk}: {str(meta)[:300]}")
    atch, sn = meta["atchFileId"], meta["fileDetailSn"]
    url = f"https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId={atch}&fileDetailSn={sn}"
    resp = opener.open(urllib.request.Request(url, headers={"User-Agent": UA, "Referer": page}), timeout=1800)
    ctype = resp.headers.get("Content-Type", "")
    disp = resp.headers.get("Content-Disposition", "")
    if "html" in ctype.lower():
        raise RuntimeError(f"download for {pk} returned HTML (limit / captcha?) - stopping, not bypassed")
    clen = resp.headers.get("Content-Length")
    ext = ".zip" if ".zip" in urllib.parse.unquote(disp).lower() else ".csv"
    dest = RAW_DIR / f"{pk}_{DATASETS[pk][0]}{ext}"
    part = dest.with_name(dest.name + ".part")
    h, n, magic = hashlib.sha256(), 0, b""
    with open(part, "xb") as fh:  # write-once; a failed transfer leaves the .part in place
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            if n == 0:
                magic = chunk[:4]
                if chunk.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
                    raise RuntimeError(f"download for {pk} started with HTML - stopping ({part} left)")
            fh.write(chunk)
            h.update(chunk)
            n += len(chunk)
    complete = clen is None or int(clen) == n
    if complete:
        if magic == b"PK\x03\x04" and ext != ".zip":
            dest = dest.with_suffix(".zip")
        os.rename(part, dest)  # rename only; never replaces (FileExistsError on Windows if dest exists)
    return {"publicDataPk": pk, "station": DATASETS[pk][1], "page_url": page, "download_url": url,
            "content_type": ctype, "content_disposition": disp, "content_length": clen, "complete": complete,
            "data_name": (meta.get("dataSetFileDetailInfo") or {}).get("dataNm"),
            "downloaded_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            "file" if complete else "partial_file": (dest if complete else part).name, "bytes": n,
            "sha256": h.hexdigest(), "licence": LICENCE}


def _existing(pk: str) -> Path | None:
    hits = [p for p in RAW_DIR.glob(f"{pk}_*") if not p.name.endswith(".part")]
    return hits[0] if hits else None


def cmd_download(args) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest = RAW_DIR / "manifest.json"
    if manifest.exists():
        raise FileExistsError(f"refusing_to_overwrite:{manifest}")
    opener, rows, total = _opener(), [], 0
    first = True
    for pk, (_, _, detail) in DATASETS.items():
        old = _existing(pk)
        if old is not None:  # earlier interrupted run: keep the file, record it (no re-download, no overwrite)
            hh = hashlib.sha256(old.read_bytes()).hexdigest()
            rows.append({"publicDataPk": pk, "station": DATASETS[pk][1], "file": old.name,
                         "bytes": old.stat().st_size, "sha256": hh, "complete": True,
                         "note": "present before this manifest run", "licence": LICENCE,
                         "page_url": f"https://www.data.go.kr/data/{pk}/fileData.do"})
            total += old.stat().st_size
            continue
        if not first:
            time.sleep(PAUSE_S)
        first = False
        try:
            row = download_one(pk, detail, opener)
        except Exception as exc:  # noqa: BLE001
            rows.append({"publicDataPk": pk, "error": f"{type(exc).__name__}: {exc}"})
            print(f"{pk}: FAILED {exc}", flush=True)
            if "HTML" in str(exc) or "refused" in str(exc):
                break
            continue
        total += row["bytes"]
        rows.append(row)
        print(f"{pk}: {row['bytes'] / 1e6:.1f} MB {row['sha256'][:12]}", flush=True)
        if total > MAX_DOWNLOAD_BYTES:
            print("download budget reached, stopping", flush=True)
            break
    manifest.write_text(json.dumps({"source": "data.go.kr MOF 공동활용체계 수질자동측정망", "licence": LICENCE,
                                    "script": SCRIPT, "git_head": git_head(), "files": rows,
                                    "total_bytes": total}, indent=1, ensure_ascii=False), encoding="utf-8")


# ----------------------------------------------------------------------------------------------- read + score
def read_raw(path: Path, pick=None) -> pd.DataFrame:
    """Read as strings; ``pick(columns) -> columns to keep`` limits memory (header read first)."""
    comp = "zip" if path.suffix == ".zip" else None
    for enc in ("utf-8-sig", "cp949"):
        try:
            cols = list(pd.read_csv(path, encoding=enc, dtype=str, nrows=0, compression=comp).columns)
            use = pick(cols) if pick else None
            return pd.read_csv(path, encoding=enc, dtype=str, quoting=csv.QUOTE_MINIMAL, usecols=use,
                               compression=comp, low_memory=False)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"cannot decode {path}")


def pick_columns(cols: list[str]) -> list[str]:
    keys = [find_col(cols, ("관측일시",)) or find_col(cols, ("일시", "시간", "date", "Date")),
            find_col(cols, ("암모니아",)), find_col(cols, ("수층",))]
    keys += [find_col(cols, k, exclude=("기온",)) for k in AUX.values()]
    return [c for c in dict.fromkeys(keys) if c]


def find_col(cols, keys, exclude=()) -> str | None:
    for c in cols:
        if any(k in c for k in keys) and not any(x in c for x in exclude):
            return c
    return None


def score_series(times: pd.Series, nh4: pd.Series, aux: dict[str, pd.Series]) -> dict:
    hourly = hourly_series(times, nh4)
    valid = valid_hours(hourly) if not hourly.empty else pd.Series(dtype=bool)
    bw = best_window(valid)
    t = pd.to_datetime(times, errors="coerce")
    raw = pd.to_numeric(nh4, errors="coerce")
    tt = t.dropna().sort_values().drop_duplicates()
    dt = tt.diff().dropna()
    chg = hourly.dropna()
    chg_iv = chg.index.to_series().diff()[chg.diff().fillna(0) != 0].dropna()
    row = {"rows": int(len(times)), "time_parse_fail_share": round(float(t.isna().mean()), 5), "time_first": str(tt.iloc[0]) if len(tt) else None,
           "time_last": str(tt.iloc[-1]) if len(tt) else None,
           "raw_interval_median_min": float(dt.median() / pd.Timedelta(minutes=1)) if len(dt) else None,
           "nh4_change_interval_median_min": float(chg_iv.median() / pd.Timedelta(minutes=1)) if len(chg_iv) else None,
           "nh4_raw_nan_share": round(float(raw.isna().mean()), 4),
           "nh4_raw_negative_share": round(float((raw < 0).mean()), 5),
           "nh4_hours_present": int(hourly.notna().sum()), "nh4_hours_valid": int(valid.sum()),
           "best_start": bw["start"], "best_end": bw["end"], "best_valid_fraction": bw["valid_fraction"],
           "best_max_gap_days": bw["max_gap_days"], "pass": bw["pass"]}
    segs = segments(valid) if len(valid) else []
    row["segments"] = len(segs)
    row["longest_segment_days"] = max((s["span_days"] for s in segs), default=0)
    row.update({f"nh4_{k}": v for k, v in fault_stats(hourly).items()})
    if bw["start"]:
        win = (t >= pd.Timestamp(bw["start"])) & (t < pd.Timestamp(bw["end"]))
        for name, s in aux.items():
            if s is None:
                row[f"{name}_cov"] = None
                continue
            ah = hourly_series(times[win], s[win])  # note: drops negatives (fine for these variables)
            row[f"{name}_cov"] = round(float(ah.notna().sum() / (WINDOW_DAYS * 24)), 4) if len(ah) else 0.0
    return row | {"_segments": segs}


def cmd_prereg(args) -> None:
    out = paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME
    out.mkdir(parents=True, exist_ok=True)
    p = out / "preregistration.json"
    if p.exists():
        raise FileExistsError(f"refusing_to_overwrite:{p}")
    p.write_text(json.dumps({
        "run": RUN_NAME, "script": SCRIPT, "git_head": git_head(), "created": pd.Timestamp.now(tz="UTC").isoformat(),
        "datasets": {k: v[:2] for k, v in DATASETS.items()},
        "series": "file x 조사수층 layer; hourly median of valid raw NH4 (finite, >= 0)",
        "stuck": f"run of >= {STUCK_HOURS} consecutive present clock hours with identical hourly value -> invalid",
        "pass_series": f"exists day-aligned {WINDOW_DAYS}-d window with valid-hour fraction >= {MIN_VALID_FRACTION} and "
                       f"max gap between valid hours (edges included) <= {MAX_GAP_DAYS} d",
        "pass_station": "any layer passes",
        "verdict": f"F5 feasible iff >= {MIN_STATIONS} stations pass",
        "reported_no_gate": ["sample interval", "NH4 change interval", "unit", "percentiles", "NaN/negative/zero share",
                             "segments", "stuck share", "ceiling share", f"x{JUMP_RATIO:g} jump rate",
                             f"persistent x{JUMP_RATIO:g} shifts ({SHIFT_WINDOW_H} h medians)", "resolution",
                             "temp/sal/DO/pH/turb hourly coverage in best window"],
        "limitations": "no QC flags in source -> no clean ground truth; first 60 KB of 4 files seen in the survey"},
        indent=1, ensure_ascii=False), encoding="utf-8")
    print(p)


def cmd_score(args) -> None:
    out = paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME
    prereg = json.loads((out / "preregistration.json").read_text(encoding="utf-8"))
    man = json.loads((RAW_DIR / "manifest.json").read_text(encoding="utf-8"))
    rows, segs_all, cols_seen = [], {}, {}
    for f in man["files"]:
        if "file" not in f:
            rows.append({"publicDataPk": f["publicDataPk"], "error": f.get("error")})
            continue
        seen = {}
        df = read_raw(RAW_DIR / f["file"], pick=lambda c: seen.setdefault("all", c) and pick_columns(c))
        cols = list(df.columns)
        cols_seen[f["publicDataPk"]] = {"all": seen.get("all"), "used": cols}
        tcol = find_col(cols, ("관측일시",)) or find_col(cols, ("일시", "시간", "date", "Date"))
        ncol = find_col(cols, ("암모니아",))
        lcol = find_col(cols, ("수층",))
        base = {"publicDataPk": f["publicDataPk"], "station": f["station"], "time_col": tcol, "nh4_col": ncol}
        if tcol is None or ncol is None:
            rows.append(base | {"layer": None, "error": "missing time or NH4 column"})
            continue
        auxc = {k: find_col(cols, keys, exclude=("기온",)) for k, keys in AUX.items()}
        groups = df.groupby(lcol, dropna=False) if lcol else [("all", df)]
        for layer, g in groups:
            r = score_series(g[tcol], g[ncol], {k: (g[c] if c else None) for k, c in auxc.items()})
            segs_all[f"{f['publicDataPk']}|{layer}"] = r.pop("_segments")
            rows.append(base | {"layer": str(layer)} | r)
        print(f"{f['publicDataPk']} {f['station']}: {len(df)} rows", flush=True)
    st = pd.DataFrame(rows)
    passed = sorted(st.loc[st.get("pass", pd.Series(False, index=st.index)).fillna(False).astype(bool),
                           "publicDataPk"].unique())
    verdict = {"run": RUN_NAME, "git_head_prereg": prereg["git_head"], "git_head_score": git_head(),
               "stations_scored": int(st["publicDataPk"].nunique()), "series_scored": int(len(st)),
               "stations_pass": passed, "n_pass": len(passed), "min_stations": MIN_STATIONS,
               "f5_feasible": len(passed) >= MIN_STATIONS}
    for name, obj in (("stations.csv", st), ("segments.json", segs_all), ("columns.json", cols_seen),
                      ("verdict.json", verdict)):
        p = out / name
        if p.exists():
            raise FileExistsError(f"refusing_to_overwrite:{p}")
        if isinstance(obj, pd.DataFrame):
            obj.to_csv(p, index=False)
        else:
            p.write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(verdict, ensure_ascii=False))


def cmd_manifest(args) -> None:
    out = paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME
    p = out / "manifest.json"
    if p.exists():
        raise FileExistsError(f"refusing_to_overwrite:{p}")
    files = sorted(x for x in out.iterdir() if x.is_file() and x.name != "manifest.json")
    def _h(x):
        return hashlib.sha256(x.read_bytes()).hexdigest()
    raw = RAW_DIR / "manifest.json"
    p.write_text(json.dumps({"run": RUN_NAME, "script": SCRIPT, "git_head": git_head(),
                             "created": pd.Timestamp.now(tz="UTC").isoformat(),
                             "inputs": [{"path": str(raw), "sha256": _h(raw)}],
                             "outputs": {x.name: _h(x) for x in files}}, indent=1, ensure_ascii=False),
                 encoding="utf-8")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("prereg", "download", "score", "manifest"))
    args = ap.parse_args(argv)
    {"prereg": cmd_prereg, "download": cmd_download, "score": cmd_score, "manifest": cmd_manifest}[args.cmd](args)


if __name__ == "__main__":
    main()
