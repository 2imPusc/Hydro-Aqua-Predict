"""experiments/ecmwf_opendata.py: ECMWF Open Data TC-track ("tf" BUFR) fetch + summarise (Track D).

Pure helpers are always tested.  The BUFR decode test needs the optional ``eccodes`` package
(requirements-hazards.txt) and is skipped without it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from experiments import ecmwf_opendata as eo

FIXTURE = Path(__file__).parent / "fixtures" / "ecmwf_tf_2026102212_sample.bufr"
MISSING = -1e100

LISTING = """<a href="/forecasts/20261022/12z/ifs/0p25/enfo/20261022120000-360h-enfo-tf.bufr">x</a>
<a href="/forecasts/20261022/12z/ifs/0p25/enfo/20261022120000-0h-enfo-ef.grib2">y</a>"""


def test_tf_files_from_listing():
    assert eo.tf_files_from_listing(LISTING) == ["/forecasts/20261022/12z/ifs/0p25/enfo/20261022120000-360h-enfo-tf.bufr"]
    assert eo.tf_files_from_listing("<html></html>") == []


def test_candidate_runs_newest_first():
    now = datetime(2026, 10, 23, 8, 30, tzinfo=timezone.utc)
    runs = eo.candidate_runs(now, n=4)
    assert [r.strftime("%Y%m%d%H") for r in runs] == ["2026102306", "2026102300", "2026102218", "2026102212"]


def test_latest_run_skips_runs_without_tf(monkeypatch):
    listings = {
        ("2026102306", "enfo"): "",
        ("2026102300", "enfo"): LISTING.replace("20261022/12z", "20261023/00z").replace("20261022120000", "20261023000000"),
        ("2026102300", "oper"): "",
    }
    monkeypatch.setattr(eo, "_listing", lambda run, stream: listings.get((run.strftime("%Y%m%d%H"), stream), ""))
    found = eo.latest_run(datetime(2026, 10, 23, 8, 30, tzinfo=timezone.utc), n=4)
    assert found["run"].strftime("%Y%m%d%H") == "2026102300"
    assert found["enfo"].endswith("20261023000000-360h-enfo-tf.bufr") and found["oper"] is None


def _ens_message():
    """Two members; member 1 loses the storm after 6 h; t0 uses the per-member (sig 4) position."""
    return [
        ("stormIdentifier", "36W"), ("longStormName", "    CHAMPI"),
        ("ensembleMemberNumber", np.array([0, 1])),
        ("meteorologicalAttributeSignificance", 1), ("latitude", 21.2), ("longitude", 124.9),
        ("meteorologicalAttributeSignificance", np.array([4, 4])), ("latitude", np.array([21.0, 21.4])),
        ("longitude", np.array([125.0, 124.8])), ("pressureReducedToMeanSeaLevel", np.array([99000.0, 99200.0])),
        ("meteorologicalAttributeSignificance", 3), ("latitude", np.array([21.5, 21.6])),
        ("longitude", np.array([125.3, 125.1])), ("windSpeedAt10M", np.array([25.0, 22.0])),
        ("timePeriod", 6), ("meteorologicalAttributeSignificance", 1), ("latitude", np.array([21.5, 21.9])),
        ("longitude", np.array([124.0, 123.8])), ("pressureReducedToMeanSeaLevel", np.array([98800.0, 99100.0])),
        ("meteorologicalAttributeSignificance", 3), ("latitude", np.array([21.8, 22.0])),
        ("longitude", np.array([124.2, 124.0])), ("windSpeedAt10M", np.array([26.0, 23.0])),
        ("timePeriod", 12), ("meteorologicalAttributeSignificance", 1), ("latitude", np.array([22.0, MISSING])),
        ("longitude", np.array([123.0, MISSING])), ("pressureReducedToMeanSeaLevel", np.array([98500.0, MISSING])),
        ("meteorologicalAttributeSignificance", 3), ("latitude", np.array([22.2, MISSING])),
        ("longitude", np.array([123.2, MISSING])), ("windSpeedAt10M", np.array([28.0, MISSING])),
    ]


def test_rows_from_keys_ensemble():
    rows = pd.DataFrame(eo.rows_from_keys(_ens_message(), n_subsets=2, stream="enfo"))
    assert set(rows["member"]) == {"ens00", "ens01"}
    assert rows["storm_id"].unique().tolist() == ["36W"] and rows["name"].iloc[0] == "CHAMPI"
    assert rows["observed"].all()
    t0 = rows[(rows["member"] == "ens01") & (rows["hour"] == 0)].iloc[0]
    assert (t0["lat"], t0["lon"], t0["pmin_hpa"], t0["vmax_ms"]) == (21.4, 124.8, 992.0, 22.0)
    assert rows[rows["member"] == "ens01"]["hour"].tolist() == [0, 6]  # missing at 12 h dropped
    assert rows[rows["member"] == "ens00"]["hour"].tolist() == [0, 6, 12]
    assert rows[(rows["member"] == "ens00") & (rows["hour"] == 12)]["lat"].iloc[0] == 22.0


def test_rows_from_keys_genesis_and_hres():
    msg = [("stormIdentifier", "70W"), ("longStormName", "       70W"), ("ensembleMemberNumber", 51),
           ("meteorologicalAttributeSignificance", 1), ("latitude", MISSING), ("longitude", MISSING),
           ("meteorologicalAttributeSignificance", 5), ("latitude", MISSING), ("longitude", MISSING),
           ("timePeriod", 6), ("meteorologicalAttributeSignificance", 1), ("latitude", 15.0), ("longitude", 115.0)]
    rows = pd.DataFrame(eo.rows_from_keys(msg, n_subsets=1, stream="oper"))
    assert rows["member"].tolist() == ["hres"] and not rows["observed"].any()
    assert rows["hour"].tolist() == [6]


def test_summarize_writes_ledger_and_storm_json(tmp_path, monkeypatch):
    run = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
    hours = range(0, 127, 6)
    rows = []
    for m in range(4):  # 2 of 4 members head for NB1
        west = m < 2
        for h in hours:
            rows.append({"storm_id": "36W", "name": "CHAMPI", "member": f"ens{m:02d}", "hour": h, "observed": True,
                         "lat": 20.7 if west else 20.7 + h / 6, "lon": 122.0 - (h / 6 if west else 0.0),
                         "pmin_hpa": 990.0, "vmax_ms": 25.0})
    tracks = pd.DataFrame(rows)
    stations = [{"id": "NB1", "lat": 20.71894, "lon": 107.04264, "exposure_class": "exposed"},
                {"id": "NB2", "lat": 20.75, "lon": 107.1, "exposure_class": None}]
    out = eo.summarize(tracks, run, stations=stations, runtime_dir=tmp_path,
                       source={"enfo": {"url": "u", "sha256": "abc", "file": "f.bufr"}},
                       issued_at=datetime(2026, 10, 22, 20, tzinfo=timezone.utc))
    storms_json = tmp_path / "hazard-shadow" / "storms_active_2026102212.json"
    ledger = tmp_path / "hazard-shadow" / "hazard_20261022.jsonl"
    assert out["storms_file"] == storms_json and storms_json.exists() and ledger.exists()
    body = json.loads(storms_json.read_text(encoding="utf-8"))
    assert body["status"] == "ready" and body["source"] == "ecmwf_opendata"
    assert body["storms"][0]["id"] == "36W" and body["storms"][0]["p_within_500km_120h"] == 0.5
    assert body["used_by_alerts"] is False and body["reference_site"]["station"] == "NB1"
    recs = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert [r["station"] for r in recs] == ["NB1", "NB2"]
    assert all(r["hazard"] == "storm_watch" and r["tier"] == 1 and r["value"] == 0.5 for r in recs)
    assert recs[0]["inputs"]["sha256"] == "abc"
    # re-running the same run appends nothing and keeps the JSON
    again = eo.summarize(tracks, run, stations=stations, runtime_dir=tmp_path, source={},
                         issued_at=datetime(2026, 10, 22, 21, tzinfo=timezone.utc))
    assert again["ledger_written"] == 0 and again["storms_file_created"] is False
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 2


def test_record_skip_when_no_run(tmp_path):
    stations = [{"id": "NB1", "lat": 20.71894, "lon": 107.04264}]
    n = eo.record_skip(stations, "no_run_available", runtime_dir=tmp_path,
                       issued_at=datetime(2026, 10, 22, 20, tzinfo=timezone.utc))
    recs = [json.loads(x) for x in (tmp_path / "hazard-shadow" / "hazard_20261022.jsonl").read_text("utf-8").splitlines()]
    assert n == 1 and recs[0]["tier"] is None and recs[0]["skip_reason"] == "no_run_available"


def test_exposure_class_from_label():
    assert eo.exposure_class_from_label("hở (exposed)") == "exposed"
    assert eo.exposure_class_from_label("bán kín (semi)") == "semi"
    assert eo.exposure_class_from_label("kín (sheltered)") == "sheltered"
    assert eo.exposure_class_from_label("") is None and eo.exposure_class_from_label(None) is None


@pytest.mark.skipif(not eo.eccodes_available(), reason="eccodes not installed (requirements-hazards.txt)")
def test_decode_fixture_bufr():
    df = eo.decode_bufr(FIXTURE)
    assert set(df["storm_id"]) == {"36W", "76W"}
    champi = df[(df["storm_id"] == "36W")]
    assert champi["observed"].all() and champi["name"].iloc[0] == "CHAMPI"
    assert "hres" in set(champi["member"])
    ens = champi[champi["member"] != "hres"]
    assert ens["member"].nunique() == 51
    t0 = champi[(champi["member"] == "hres") & (champi["hour"] == 0)].iloc[0]
    assert 19 < t0["lat"] < 23 and 123 < t0["lon"] < 127
    assert not df[df["storm_id"] == "76W"]["observed"].any()
    assert df["hour"].max() <= 360 and df["lat"].between(-90, 90).all()


def test_run_download_error_records_skip_and_does_not_raise(tmp_path, monkeypatch, capsys):
    from core import paths
    monkeypatch.setattr(paths, "HAZARD_SHADOW_DIR", tmp_path)
    monkeypatch.setattr(eo, "load_stations", lambda: [{"id": "NB1", "lat": 20.7, "lon": 107.0, "exposure_class": None}])

    def boom():
        raise OSError("network down")
    monkeypatch.setattr(eo, "fetch", boom)
    assert eo.main(["run"]) == 1
    recs = [json.loads(x) for f in tmp_path.glob("hazard_*.jsonl") for x in f.read_text("utf-8").splitlines()]
    assert len(recs) == 1 and recs[0]["tier"] is None and recs[0]["skip_reason"] == "download_failed: OSError"
    assert "download_failed" in capsys.readouterr().out


def test_run_decode_error_records_skip_and_does_not_raise(tmp_path, monkeypatch):
    from core import paths
    monkeypatch.setattr(paths, "HAZARD_SHADOW_DIR", tmp_path)
    monkeypatch.setattr(eo, "load_stations", lambda: [{"id": "NB1", "lat": 20.7, "lon": 107.0, "exposure_class": None}])
    monkeypatch.setattr(eo, "fetch", lambda: {"run": datetime(2026, 10, 22, 12, tzinfo=timezone.utc)})

    def bad(run):
        raise ImportError("eccodes missing")
    monkeypatch.setattr(eo, "decode_run", bad)
    assert eo.main(["run"]) == 1
    recs = [json.loads(x) for f in tmp_path.glob("hazard_*.jsonl") for x in f.read_text("utf-8").splitlines()]
    assert recs[0]["skip_reason"] == "decode_failed: ImportError"


def test_summarize_command_decode_error_returns_1_without_ledger(tmp_path, monkeypatch):
    from core import paths
    monkeypatch.setattr(paths, "HAZARD_SHADOW_DIR", tmp_path)
    monkeypatch.setattr(eo, "newest_local_run", lambda: datetime(2026, 10, 22, 12, tzinfo=timezone.utc))
    monkeypatch.setattr(eo, "decode_run", lambda run: (_ for _ in ()).throw(FileNotFoundError("x")))
    assert eo.main(["summarize"]) == 1
    assert not list(tmp_path.glob("hazard_*.jsonl"))
