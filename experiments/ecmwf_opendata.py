"""ECMWF Open Data tropical-cyclone tracks -> basin storm watch (shadow, Track D).

Source (no login, CC BY 4.0; only the last ~4 days are kept on the server):
    https://data.ecmwf.int/forecasts/<YYYYMMDD>/<HH>z/ifs/0p25/enfo/<YYYYMMDDHH>0000-<360|144>h-enfo-tf.bufr  (ENS)
    https://data.ecmwf.int/forecasts/<YYYYMMDD>/<HH>z/ifs/0p25/oper/<YYYYMMDDHH>0000-<step>h-oper-tf.bufr      (HRES)
ENS tracks: 00/12 UTC to 360 h, 06/18 UTC to 144 h; control + 50 members.  BUFR edition 4,
template 3 16 082 (one message per storm, one subset per member, 6-hourly fixes).  Decoding
uses ECMWF ``eccodes`` (pip wheel, works on Windows; optional dependency in
``requirements-hazards.txt``).  pybufrkit 0.2.25 was tried and fails with bitstring >= 5.

    python experiments/ecmwf_opendata.py fetch                 # newest run with an ENS tf file, write-once
    python experiments/ecmwf_opendata.py summarize [--run 2026102212]   # -> runtime/hazard-shadow
    python experiments/ecmwf_opendata.py run                   # fetch + summarize
    python experiments/ecmwf_opendata.py list [--run ...]      # print every storm in the run (global)

Downloads go to ``paths.ECMWF_OPENDATA_DIR`` (write-once, ``<file>.manifest.json`` with URL, sha256,
run time and model).  ``summarize`` appends one C2 record (hazard ``storm_watch``) per station to
``runtime/hazard-shadow/hazard_<YYYYMMDD>.jsonl`` and creates ``storms_active_<run>.json`` for
``GET /api/v1/research/storms/active``.  A run already summarised (its JSON exists) is skipped.
Probabilities: ``core/storm_tracks.py`` (same rule as the TIGGE evaluation in storm_basin.py).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core import storm_tracks as st  # noqa: E402
from experiments.hazard_data import write_once  # noqa: E402

HOST = "https://data.ecmwf.int"
BASE_URL = f"{HOST}/forecasts"
STREAMS = {"enfo": "ecmwf_ifs_ens", "oper": "ecmwf_ifs_hres"}  # stream -> model name (decisions #18)
RUN_HOURS = (0, 6, 12, 18)
MISSING_THRESHOLD = -1e99  # eccodes CODES_MISSING_DOUBLE = -1e100
MISSING_LONG = 2147483647
_TF_HREF = re.compile(r'href="([^"]*-tf\.bufr)"')
_RANK = re.compile(r"^#\d+#")
_WANTED = {"stormIdentifier", "longStormName", "ensembleMemberNumber", "timePeriod",
           "meteorologicalAttributeSignificance", "latitude", "longitude",
           "pressureReducedToMeanSeaLevel", "windSpeedAt10M"}
_STRING_KEYS = {"stormIdentifier", "longStormName"}
DEFAULT_SITE = {"id": "NB1", "lat": 20.71894498573044, "lon": 107.042635855355}
LICENCE = "CC BY 4.0 (ECMWF Open Data)"


# --------------------------------------------------------------------------- discovery
def run_dir_url(run: datetime, stream: str) -> str:
    return f"{BASE_URL}/{run:%Y%m%d}/{run:%H}z/ifs/0p25/{stream}/"


def tf_files_from_listing(html: str) -> list[str]:
    return _TF_HREF.findall(html or "")


def candidate_runs(now: datetime, n: int = 12) -> list[datetime]:
    """The ``n`` most recent synoptic runs (00/06/12/18 UTC) at or before ``now``, newest first."""
    t = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    t = t.replace(hour=max(h for h in RUN_HOURS if h <= t.hour))
    return [t - timedelta(hours=6 * i) for i in range(n)]


def _listing(run: datetime, stream: str) -> str:
    try:
        resp = requests.get(run_dir_url(run, stream), timeout=60)
    except requests.RequestException:
        return ""
    return resp.text if resp.status_code == 200 else ""


def latest_run(now: datetime | None = None, n: int = 12) -> dict | None:
    """Newest run whose ENS tf file is listed: ``{"run", "enfo": href, "oper": href | None}``."""
    for run in candidate_runs(now or datetime.now(timezone.utc), n=n):
        enfo = tf_files_from_listing(_listing(run, "enfo"))
        if enfo:
            oper = tf_files_from_listing(_listing(run, "oper"))
            return {"run": run, "enfo": enfo[0], "oper": oper[0] if oper else None}
    return None


def _run_at(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y%m%d%H").replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- download (write-once)
def local_path(href: str) -> Path:
    return paths.ECMWF_OPENDATA_DIR / href.rsplit("/", 1)[-1]


def download(href: str, run: datetime, stream: str) -> dict:
    """Write-once download; an existing file is reused (its manifest returned)."""
    target = local_path(href)
    manifest = Path(f"{target}.manifest.json")
    if target.exists():
        return json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {"file": target.name}
    url = HOST + href if href.startswith("/") else href
    resp = requests.get(url, timeout=300)
    resp.raise_for_status()
    return write_once(target, resp.content, url, extra={
        "run_time": run.strftime("%Y-%m-%dT%H:%M:%SZ"), "stream": stream, "models": STREAMS[stream],
        "product": "ECMWF IFS tropical-cyclone tracks (tf), BUFR edition 4, template 316082",
        "licence": LICENCE})


def fetch(now: datetime | None = None) -> dict | None:
    found = latest_run(now)
    if found is None:
        return None
    out = {"run": found["run"], "enfo": download(found["enfo"], found["run"], "enfo")}
    if found["oper"]:
        try:
            out["oper"] = download(found["oper"], found["run"], "oper")
        except requests.RequestException as exc:  # HRES is optional context only
            out["oper"] = {"error": str(exc)}
    return out


def local_files(run: datetime) -> dict[str, Path]:
    stamp = f"{run:%Y%m%d%H}0000"
    out = {}
    for stream in STREAMS:
        hits = sorted(paths.ECMWF_OPENDATA_DIR.glob(f"{stamp}-*h-{stream}-tf.bufr"))
        if hits:
            out[stream] = hits[-1]
    return out


def newest_local_run() -> datetime | None:
    stamps = sorted(p.name[:10] for p in paths.ECMWF_OPENDATA_DIR.glob("*-enfo-tf.bufr"))
    return _run_at(stamps[-1]) if stamps else None


# --------------------------------------------------------------------------- BUFR decode
def eccodes_available() -> bool:
    try:
        import eccodes  # noqa: F401
    except (ImportError, RuntimeError, OSError):
        return False
    return True


def _as_array(value, n: int) -> np.ndarray:
    arr = np.atleast_1d(np.asarray(value))
    if arr.size == 1 and n > 1:
        arr = np.repeat(arr, n)
    return arr


def _first_valid(value) -> float | None:
    for v in np.atleast_1d(np.asarray(value, dtype=float)):
        if v > MISSING_THRESHOLD and v != MISSING_LONG:
            return float(v)
    return None


def rows_from_keys(items: list[tuple[str, object]], n_subsets: int, stream: str) -> list[dict]:
    """Track fixes from one decoded message, given its data keys in order (rank prefixes stripped).

    State machine over the template: ``timePeriod`` opens a forecast step (0 before the first one);
    ``meteorologicalAttributeSignificance`` sets what the next latitude/longitude describe:
    1 storm centre, 3 max-wind location, 4 centre in the perturbed analysis (ENS t0), 5 centre in
    the analysis (HRES t0).  The centre at step 0 is the member's own (4/5), else the observed (1).
    """
    sid, name, members = None, None, None
    period, sig = 0.0, None
    pos: dict[tuple[float, int], dict] = {}
    pres: dict[float, np.ndarray] = {}
    wind: dict[float, np.ndarray] = {}
    for key, value in items:
        if key == "stormIdentifier" and sid is None:
            sid = str(np.atleast_1d(value)[0]).strip()
        elif key == "longStormName" and name is None:
            name = str(np.atleast_1d(value)[0]).strip()
        elif key == "ensembleMemberNumber" and members is None:
            members = _as_array(value, n_subsets).astype(int)
        elif key == "timePeriod":
            p = _first_valid(value)
            period = p if p is not None else period
            sig = None
        elif key == "meteorologicalAttributeSignificance":
            s = _first_valid(value)
            sig = int(s) if s is not None else None
        elif key in ("latitude", "longitude") and sig is not None:
            pos.setdefault((period, sig), {}).setdefault(key, _as_array(value, n_subsets).astype(float))
        elif key == "pressureReducedToMeanSeaLevel":
            pres.setdefault(period, _as_array(value, n_subsets).astype(float))
        elif key == "windSpeedAt10M":
            wind.setdefault(period, _as_array(value, n_subsets).astype(float))
    if members is None:
        members = np.arange(n_subsets)
    obs = pos.get((0.0, 1), {}).get("latitude")
    observed = obs is not None and bool((obs > MISSING_THRESHOLD).any())
    labels = ["hres"] * n_subsets if stream == "oper" else [f"ens{int(m):02d}" for m in members]
    rows = []
    for period_h in sorted({p for p, _ in pos}):
        centre = None
        for s in ((4, 5, 1) if period_h == 0 else (1,)):
            c = pos.get((period_h, s))
            if c and "latitude" in c and "longitude" in c:
                centre = c
                break
        if centre is None:
            continue
        lat, lon = centre["latitude"], centre["longitude"]
        pr, wd = pres.get(period_h), wind.get(period_h)
        for i in range(n_subsets):
            if not (lat[i] > MISSING_THRESHOLD and lon[i] > MISSING_THRESHOLD):
                continue
            p_hpa = pr[i] / 100.0 if pr is not None and pr[i] > MISSING_THRESHOLD else None
            v_ms = float(wd[i]) if wd is not None and wd[i] > MISSING_THRESHOLD else None
            rows.append({"storm_id": sid, "name": name or sid, "member": labels[i], "hour": int(period_h),
                         "lat": round(float(lat[i]), 4), "lon": round(float(lon[i]), 4), "observed": observed,
                         "pmin_hpa": p_hpa, "vmax_ms": v_ms, "stream": stream})
    return rows


def _stream_of(path: Path) -> str:
    return "oper" if "-oper-" in path.name else "enfo"


def decode_bufr(path: Path, stream: str | None = None) -> pd.DataFrame:
    """All messages of a tf BUFR file -> track fixes (columns ``core.storm_tracks.TRACK_COLUMNS`` + stream)."""
    import eccodes as ec

    rows: list[dict] = []
    with open(path, "rb") as fh:
        while True:
            h = ec.codes_bufr_new_from_file(fh)
            if h is None:
                break
            try:
                ec.codes_set(h, "unpack", 1)
                n = int(ec.codes_get(h, "numberOfSubsets"))
                # oper messages carry ensembleMemberNumber 51 with forecast type 0; label by stream
                msg_stream = stream or ("oper" if n == 1 and int(ec.codes_get_array(h, "ensembleForecastType")[0]) == 0
                                        else _stream_of(Path(path)))
                it = ec.codes_bufr_keys_iterator_new(h)
                names = []
                while ec.codes_bufr_keys_iterator_next(it):
                    names.append(ec.codes_bufr_keys_iterator_get_name(it))
                ec.codes_bufr_keys_iterator_delete(it)
                items = []
                for full in names:
                    base = _RANK.sub("", full)
                    if base not in _WANTED:
                        continue
                    if base in _STRING_KEYS:
                        items.append((base, ec.codes_get_string(h, full)))
                    else:
                        items.append((base, ec.codes_get_array(h, full)))
                rows += rows_from_keys(items, n, msg_stream)
            finally:
                ec.codes_release(h)
    return pd.DataFrame(rows, columns=[*st.TRACK_COLUMNS, "stream"])


# --------------------------------------------------------------------------- stations
def exposure_class_from_label(label: str | None) -> str | None:
    m = re.search(r"\((sheltered|semi|exposed)\)", label or "")
    return m.group(1) if m else None


def _exposure_classes() -> dict[str, str]:
    runs = sorted(paths.EXPERIMENT_OUTPUT_DIR.glob("site-exposure-*/stations.csv"))
    if not runs:
        return {}
    with open(runs[-1], encoding="utf-8") as fh:
        return {r["site_id"]: exposure_class_from_label(r.get("exposure_class")) for r in csv.DictReader(fh)}


def load_stations() -> list[dict]:
    exposure = _exposure_classes()
    if not paths.STATION_COORDINATES.exists():
        return [{**DEFAULT_SITE, "exposure_class": exposure.get("NB1")}]
    with open(paths.STATION_COORDINATES, encoding="utf-8") as fh:
        return [{"id": r["Station"], "lat": float(r["Lat"]), "lon": float(r["Lon"]),
                 "exposure_class": exposure.get(r["Station"])} for r in csv.DictReader(fh)]


# --------------------------------------------------------------------------- summarise
def _hazard_dir(runtime_dir: Path | None) -> Path:
    return (Path(runtime_dir) / "hazard-shadow") if runtime_dir else paths.HAZARD_SHADOW_DIR


def _append_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def summarize(tracks: pd.DataFrame, run: datetime, stations: list[dict] | None = None, runtime_dir: Path | None = None,
              source: dict | None = None, issued_at: datetime | None = None) -> dict:
    """C2 records per station + ``storms_active_<run>.json``; no-op when that JSON already exists."""
    issued = issued_at or datetime.now(timezone.utc)
    stations = stations or load_stations()
    out_dir = _hazard_dir(runtime_dir)
    storms_file = out_dir / f"storms_active_{run:%Y%m%d%H}.json"
    if storms_file.exists():
        return {"storms_file": storms_file, "storms_file_created": False, "ledger_written": 0}
    source = source or {}
    ens = tracks[tracks["member"] != "hres"] if "member" in tracks else tracks
    hres = tracks[tracks["member"] == "hres"] if "member" in tracks else tracks.iloc[0:0]
    enfo_meta = source.get("enfo", {})
    inputs = {"file": enfo_meta.get("file"), "url": enfo_meta.get("url"), "sha256": enfo_meta.get("sha256")}
    records, summaries = [], {}
    for station in stations:
        config = st.load_alert_config(station_id=station["id"], exposure_class=station.get("exposure_class"))
        summ = st.summarize_run(ens, station["lat"], station["lon"], run_time=run)
        summaries[station["id"]] = (summ, config)
        records.append(st.watch_record(station, summ, config, run_time=run, issued_at=issued, inputs=inputs))
    ref = next((s for s in stations if s["id"] == DEFAULT_SITE["id"]), stations[0])
    summ, config = summaries[ref["id"]]
    for storm in summ["storms"]:
        h = hres[hres["storm_id"] == storm["id"]] if len(hres) else hres
        if len(h):
            hs = st.summarize_storm(h, ref["lat"], ref["lon"], run_time=run)
            storm["hres"] = {k: hs[k] for k in ("closest_approach_km_median", "eta_hours_median", "track_median")}
    body = {"status": "ready", "source": "ecmwf_opendata", "fetched_at": source.get("fetched_at") or enfo_meta.get("fetched_at"),
            "issued_at": _iso(issued), "run_time": _iso(run), "models": STREAMS["enfo"],
            "reference_site": {"station": ref["id"], "lat": ref["lat"], "lon": ref["lon"]},
            "config_version": config.get("config_version"),
            "watch": {"value": summ["max_p_within_500km_120h"], "storm_id": summ["driving_storm"],
                      "tier": st.watch_tier(summ["max_p_within_500km_120h"], config)},
            "storms": summ["storms"], "genesis": summ["genesis"],
            "rule": "share of ENS members with a forecast fix 0 < h <= 120 within R km of the site "
                    "(storm_basin.tigge_eval); 6-hourly fixes, no interpolation",
            "lon_convention": "degrees east, -180..180",
            "sources": {k: {kk: v.get(kk) for kk in ("file", "url", "sha256", "fetched_at")} for k, v in source.items()
                        if isinstance(v, dict)},
            **st.FLAGS}
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(storms_file, "x", encoding="utf-8") as fh:  # exclusive create: append-only per run
        json.dump(body, fh, ensure_ascii=False, indent=1)
    _append_jsonl(out_dir / f"hazard_{issued:%Y%m%d}.jsonl", records)
    return {"storms_file": storms_file, "storms_file_created": True, "ledger_written": len(records), "body": body}


def record_skip(stations: list[dict], reason: str, runtime_dir: Path | None = None,
                issued_at: datetime | None = None) -> int:
    issued = issued_at or datetime.now(timezone.utc)
    recs = [st.watch_record(s, None, st.load_alert_config(station_id=s["id"], exposure_class=s.get("exposure_class")),
                            run_time=None, issued_at=issued, skip_reason=reason) for s in stations]
    _append_jsonl(_hazard_dir(runtime_dir) / f"hazard_{issued:%Y%m%d}.jsonl", recs)
    return len(recs)


def decode_run(run: datetime) -> tuple[pd.DataFrame, dict]:
    files = local_files(run)
    if "enfo" not in files:
        raise FileNotFoundError(f"no local ENS tf file for {run:%Y%m%d%H}")
    frames, source = [], {}
    for stream, path in files.items():
        frames.append(decode_bufr(path, stream=stream))
        man = Path(f"{path}.manifest.json")
        source[stream] = json.loads(man.read_text(encoding="utf-8")) if man.exists() else {"file": path.name}
    return pd.concat(frames, ignore_index=True), source


def storm_list(tracks: pd.DataFrame) -> pd.DataFrame:
    t0 = tracks[tracks["hour"] == tracks.groupby(["storm_id", "member"])["hour"].transform("min")]
    g = t0.groupby("storm_id")
    return pd.DataFrame({"name": g["name"].first(), "observed": g["observed"].first(),
                         "ens_members": tracks[tracks["member"] != "hres"].groupby("storm_id")["member"].nunique(),
                         "first_lat": g["lat"].median(), "first_lon": g["lon"].median(),
                         "max_hour": tracks.groupby("storm_id")["hour"].max()}).fillna({"ens_members": 0})


def _fail(cmd: str, kind: str, exc: Exception) -> int:
    """Report a download/decode error; ``run`` also leaves per-station skip records (reason names the error)."""
    reason = f"{kind}: {type(exc).__name__}"
    print(f"{kind}: {type(exc).__name__}: {exc}")
    if cmd == "run":
        try:
            record_skip(load_stations(), reason)
        except Exception as exc2:  # the ledger itself is unwritable: say so, still do not raise
            print(f"could not write skip records: {type(exc2).__name__}: {exc2}")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    for name in ("summarize", "list"):
        p = sub.add_parser(name)
        p.add_argument("--run", help="YYYYMMDDHH (default: newest local ENS tf file)")
    sub.add_parser("run")
    args = ap.parse_args(argv)
    if args.cmd in ("fetch", "run"):
        try:
            got = fetch()
        except Exception as exc:  # network / listing / disk errors: never raise out of a scheduled run
            return _fail(args.cmd, "download_failed", exc)
        if got is None:
            print("no ECMWF Open Data run with an ENS tf file found")
            if args.cmd == "run":
                record_skip(load_stations(), "no_run_available")
            return 1
        print(json.dumps({"run": _iso(got["run"]), **{k: v for k, v in got.items() if k != "run"}}, indent=1, default=str))
        if args.cmd == "fetch":
            return 0
        run = got["run"]
    else:
        run = _run_at(args.run) if args.run else newest_local_run()
        if run is None:
            print("no local ENS tf file; run `fetch` first")
            return 1
    try:
        tracks, source = decode_run(run)
    except Exception as exc:  # missing eccodes, corrupt BUFR, missing file
        return _fail(args.cmd, "decode_failed", exc)
    if args.cmd == "list":
        pd.set_option("display.width", 200)
        print(storm_list(tracks).to_string())
        return 0
    try:
        res = summarize(tracks, run, source=source)
    except Exception as exc:
        return _fail(args.cmd, "summarize_failed", exc)
    body = res.get("body")
    print(f"{res['storms_file']} created={res['storms_file_created']} ledger_records={res['ledger_written']}")
    if body:
        for s in body["storms"]:
            print(f"  {s['id']:>4} {s['name']:<12} members={s['members']:>2} p500={s['p_within_500km_120h']:.2f} "
                  f"p200={s['p_within_200km_120h']:.2f} closest={s['closest_approach_km_median']} km "
                  f"eta={s['eta_hours_median']}")
        print(f"  genesis pooled: p500={body['genesis']['p_within_500km_120h']} watch={body['watch']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
