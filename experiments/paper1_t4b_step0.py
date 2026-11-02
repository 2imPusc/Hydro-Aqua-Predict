"""Paper 1 / T4b step 0: presence-only coverage check of CDMO request 184841 (Apalachicola, Sapelo, Jobos).

Reads only flags / presence (never compares a forecast with an actual). Writes, once, into
``paper1-t4b-20261102/``: ``data-conf/<station>.parquet`` (flag-<0> Temp on the 15-min LST grid), ``weather-fc/`` (Open-Meteo
Previous Runs, same request as T3) and ``step0_coverage.json``.

    python experiments/paper1_t4b_step0.py
"""
from __future__ import annotations

import io
import json
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from experiments import paper1_t3_nerrs as t3  # noqa: E402

RUN_NAME = "paper1-t4b-20261102"
CONF_ZIP = paths.FOREIGN_DATA_DIR / "nerrs_cdmo" / "raw" / "184841.zip"
CONF_ZIP_SHA256 = "04a8c6fd559530c93a21d2f9a7be786339b7b053fa73e406a41c3d9933193d37"
# WQ station -> (reserve, UTC offset of LST); offsets from the zip's sampling_stations.csv.
CONF_STATIONS = {
    "apacpwq": ("Apalachicola", -5), "apadbwq": ("Apalachicola", -5), "apaebwq": ("Apalachicola", -5), "apaeswq": ("Apalachicola", -5),
    "sapcawq": ("Sapelo", -5), "sapdcwq": ("Sapelo", -5), "saphdwq": ("Sapelo", -5), "sapldwq": ("Sapelo", -5),
    "job09wq": ("Jobos", -4), "job10wq": ("Jobos", -4), "job19wq": ("Jobos", -4), "job20wq": ("Jobos", -4),
}
TRAIN = t3.DATASETS["cdmo"]["train"]
TEST = t3.DATASETS["cdmo"]["test"]
ORIGIN_HOURS = t3.DATASETS["cdmo"]["origin_hours"]
TRAIN_ORIGIN_STEPS = 12        # Chronos / hybrid training origins every 3 h
GRID_START = (pd.Timestamp(TRAIN[0]) - pd.Timedelta(days=21)).strftime("%Y-%m-%d")
GRID_END = (pd.Timestamp(TEST[1]) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def run_dir() -> Path:
    return paths.EXPERIMENT_OUTPUT_DIR / RUN_NAME


def read_temp() -> pd.DataFrame:
    """Long frame: station, time_lst, Temp (NaN unless flag <0>), restricted to the grid window."""
    pieces = []
    cols = ["StationCode", "DateTimeStamp", "Temp", "F_Temp"]
    with zipfile.ZipFile(CONF_ZIP) as z, z.open("184841.csv") as f:
        for chunk in pd.read_csv(f, usecols=cols, dtype=str, keep_default_na=False, chunksize=500_000):
            chunk["StationCode"] = chunk["StationCode"].str.strip()
            chunk = chunk[chunk["StationCode"].isin(CONF_STATIONS)]
            times = pd.to_datetime(chunk["DateTimeStamp"].str.strip(), format="%m/%d/%Y %H:%M")
            keep = (times >= GRID_START) & (times < GRID_END)
            pieces.append(pd.DataFrame({"station": chunk.loc[keep, "StationCode"], "time_lst": times[keep],
                                        "Temp": t3.good_values(chunk.loc[keep, "Temp"], chunk.loc[keep, "F_Temp"]).astype("float32")}))
    return pd.concat(pieces, ignore_index=True)


def coordinates() -> dict[str, tuple[float, float]]:
    with zipfile.ZipFile(CONF_ZIP) as z:
        s = pd.read_csv(io.BytesIO(z.read("sampling_stations.csv")), encoding="latin1")
    s.columns = [c.strip() for c in s.columns]
    s["Station Code"] = s["Station Code"].astype(str).str.strip()
    s = s.set_index("Station Code")
    return {code: (float(s.loc[code, "Latitude"]), -abs(float(s.loc[code, "Longitude"]))) for code in CONF_STATIONS}


def fetch_weather(coords: dict[str, tuple[float, float]]) -> None:
    import requests

    out = run_dir() / "weather-fc"
    hourly = ",".join(f"{v}_previous_day{n}" for v in t3.FETCH_FC_VARS for n in t3.FC_LEADS)
    log = []
    for code, (lat, lon) in coords.items():
        path = out / f"{code}.json"
        params = {"latitude": lat, "longitude": lon, "hourly": hourly, "start_date": t3.FC_START, "end_date": t3.FC_END,
                  "timezone": "UTC", "models": "best_match"}
        r = requests.get(t3.PREVIOUS_RUNS_URL, params=params, timeout=300, headers={"User-Agent": "Hydro-Aqua-Predict research (academic)"})
        r.raise_for_status()
        t3._write(path, r.json())
        log.append({"station": code, "url": t3.PREVIOUS_RUNS_URL, "params": params, "retrieved_at_utc": pd.Timestamp.now("UTC").isoformat(),
                    "grid_lat": r.json().get("latitude"), "grid_lon": r.json().get("longitude"), "sha256": t3._sha256(path)})
        time.sleep(2)
    t3._write(out / "fetch_log.json", log)


def conf_station(name: str) -> t3.Station:
    frame = pd.read_parquet(run_dir() / "data-conf" / f"{name}.parquet").set_index("time_lst")
    payload = json.loads((run_dir() / "weather-fc" / f"{name}.json").read_text(encoding="utf-8"))
    return t3.Station(name, frame, CONF_STATIONS[name][1], t3.ForecastAsIssued(pd.DataFrame(payload["hourly"])))


def block_edges(end: str, start: str = TEST[0], n: int = t3.N_BLOCKS) -> pd.DatetimeIndex:
    return pd.date_range(start, pd.Timestamp(end) + pd.Timedelta(minutes=1), periods=n + 1)


def block_of(issued: pd.Series | np.ndarray, end: str) -> np.ndarray:
    edges = block_edges(end)
    return np.clip(np.searchsorted(edges.to_numpy(), np.asarray(issued, dtype="datetime64[ns]"), side="right") - 1, 0, t3.N_BLOCKS - 1)


def main() -> None:
    if t3._sha256(CONF_ZIP) != CONF_ZIP_SHA256:
        raise ValueError("conf_zip_hash_mismatch")
    root = run_dir()
    root.mkdir(parents=True, exist_ok=True)
    coords = coordinates()
    temp = read_temp()
    meta = {}
    for name, part in temp.groupby("station"):
        frame = pd.DataFrame({"Temp": part.set_index("time_lst")["Temp"]})
        for v in t3.OBS_VARS:   # observed met is not used by T4b
            frame[v] = np.nan
        t3._write(root / "data-conf" / f"{name}.parquet", t3.regular_grid(frame, GRID_START, GRID_END).reset_index())
        meta[name] = {"reserve": CONF_STATIONS[name][0], "utc_offset_h": CONF_STATIONS[name][1], "lat": coords[name][0], "lon": coords[name][1]}
    t3._write(root / "data-conf" / "stations.json", meta)
    fetch_weather(coords)

    marks = t3.origin_marks(*TEST, ORIGIN_HOURS, False)
    rows, origin_frames = [], []
    for name in CONF_STATIONS:
        st = conf_station(name)
        s = pd.Series(st.temp, index=pd.date_range(st.t0, periods=st.n, freq="15min"))
        idx = st.index_of(marks.to_numpy())
        ok = t3.eligible(st, idx, ("fc",))
        lo, hi = st.index_of(np.array([np.datetime64(TRAIN[0]), np.datetime64(TRAIN[1])]))
        train_idx = np.arange(lo, hi - t3.LENGTH, TRAIN_ORIGIN_STEPS)
        ok_train = t3.eligible(st, train_idx, ("fc",))
        fc = st.weather("fc", idx, t3.FUTURE)
        rows.append({"station": name, "reserve": CONF_STATIONS[name][0], "lat": coords[name][0], "lon": coords[name][1],
                     "temp_flag0_train": float(s[TRAIN[0]:TRAIN[1]].notna().mean()), "temp_flag0_test": float(s[TEST[0]:TEST[1]].notna().mean()),
                     "temp_flag0_2024": float(s["2024"].notna().mean()), "temp_flag0_2025": float(s["2025"].notna().mean()),
                     "fc_future_present_test": float(np.isfinite(fc).mean()),
                     "test_origins_eligible": int(ok.sum()), "test_origins_possible": int(len(marks)),
                     "train_origins_eligible_3h": int(ok_train.sum()), "train_origins_possible_3h": int(len(train_idx)),
                     "last_eligible": str(marks[ok].max()) if ok.any() else None})
        origin_frames.append(pd.DataFrame({"station": name, "issued_at": marks[ok]}))
    origins = pd.concat(origin_frames, ignore_index=True)
    end = str(origins.issued_at.max())
    origins["block"] = block_of(origins.issued_at, end)
    origins["reserve"] = origins.station.map(lambda c: CONF_STATIONS[c][0])
    per_block = origins.groupby(["reserve", "block"]).size().unstack(fill_value=0)
    per_station_block = origins.groupby(["station", "block"]).size().unstack(fill_value=0)
    fc_hours = {}
    for name in CONF_STATIONS:
        hourly = pd.DataFrame(json.loads((root / "weather-fc" / f"{name}.json").read_text(encoding="utf-8"))["hourly"])
        times = pd.to_datetime(hourly["time"])
        col = hourly[[f"{v}_previous_day1" for v in t3.FC_VARS]].notna().all(axis=1)
        fc_hours[name] = {"first_complete": str(times[col].min()), "last_complete": str(times[col].max()), "fraction_from_2024_01_22": float(col[times >= "2024-01-22"].mean())}
    out = {"zip": str(CONF_ZIP), "zip_sha256": CONF_ZIP_SHA256, "presence_only": True, "train": TRAIN, "test": TEST, "grid": [GRID_START, GRID_END], "block_end": end,
           "stations": rows, "forecast_hours": fc_hours,
           "eligible_by_reserve_block": per_block.to_dict("index"), "eligible_by_station_block": per_station_block.to_dict("index")}
    t3._write(root / "step0_coverage.json", out)
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).drop(columns=["lat", "lon"]).round(3).to_string())
    print(per_block.to_string())
    print(per_station_block.to_string())
    print(json.dumps(fc_hours, indent=0))
    print("block_end", end, "total", len(origins))


if __name__ == "__main__":
    main()
