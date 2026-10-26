from pathlib import Path

from app.aquaculture_artifacts import build_aquaculture_artifacts, load_aquaculture_artifact


class Repo:
    def latest(self): return {"snapshot_id": "snap_1", "layers": [{"layer": "advisory_forecast", "kind": "point_cloud", "geojson": {"type": "FeatureCollection", "features": [{"geometry": {"type": "Point", "coordinates": [107.0, 20.7]}, "properties": {"rain_6h_mm": 5.0, "wind_6h_kmh": 15.0}}]}}]}
    def latest_sensor(self, _station):
        return [
            {"metric": "NH4", "value": "150", "unit": "ug/L", "qc_status": "PASS", "observed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc)},
            {"metric": "pH", "value": "8.1", "unit": "", "qc_status": "PASS", "observed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc)},
            {"metric": "Temperature", "value": "29", "unit": "C", "qc_status": "PASS", "observed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc)},
        ]


def test_worker_builds_compact_live_and_mock_artifacts(tmp_path: Path):
    build_aquaculture_artifacts(Repo(), str(tmp_path), ("06M26042804",), 20.7, 107.0, .001)
    live = load_aquaculture_artifact(str(tmp_path), "live")
    mock = load_aquaculture_artifact(str(tmp_path), "mock", "rain_wind_watch")
    assert live["features"][0]["properties"]["used_by_models"] is False
    assert mock["features"][0]["properties"]["severity"] == "WATCH"
    assert mock["source"]["sensor"] == "deterministic_demo"


def test_species_names_are_utf8_vietnamese_not_mojibake():
    from app.aquaculture_artifacts import AQUACULTURE_THRESHOLDS
    assert AQUACULTURE_THRESHOLDS["cobia"]["name"] == "Cá giò"
    assert AQUACULTURE_THRESHOLDS["oyster"]["name"] == "Hàu"
    raw = (Path(__file__).parents[1] / "app" / "aquaculture_artifacts.py").read_bytes().decode("utf-8")
    assert "Ã" not in raw


def test_mock_severity_follows_cage_exposure_not_list_position(tmp_path: Path, monkeypatch):
    from app import aquaculture_artifacts as aa
    classes = {"NB1": "exposed", "NB2": "sheltered", "NB3": "semi", "NB4": "exposed"}
    monkeypatch.setattr(aa, "_exposure_classes", lambda: classes)
    build_aquaculture_artifacts(Repo(), str(tmp_path), ("06M26042804",), 20.7, 107.0, .001)
    mock = load_aquaculture_artifact(str(tmp_path), "mock", "rain_wind_watch")
    by_id = {f["properties"]["station_serial"]: f["properties"] for f in mock["features"] if f["properties"].get("station_serial") in classes}
    assert by_id, "registry stations missing"
    for sid, props in by_id.items():
        assert props["exposure_class"] == classes[sid]
        expected = "WATCH" if classes[sid] == "exposed" else "NORMAL"   # 50 km/h open water; ×0.7 / ×0.45 inside
        assert props["severity"] == expected, (sid, props["severity"])


def test_live_feature_separates_tan_from_unionised_toxicity_nh3(tmp_path: Path):
    from app.aquaculture_artifacts import NH3_TOXICITY_LABEL, _condition
    build_aquaculture_artifacts(Repo(), str(tmp_path), ("06M26042804",), 20.7, 107.0, .001)
    props = load_aquaculture_artifact(str(tmp_path), "live")["features"][0]["properties"]
    assert props["tan_mg_l"] == 0.15                       # 150 raw × 0.001 = total ammonium as N
    assert 0 < props["nh3_derived_mg_l"] < props["tan_mg_l"] / 5
    assert props["nh3_derived_basis"] == "unionized_emerson_toxicity"
    # The toxicity rule fires on un-ionised NH3 only, and labels it so.
    _severity, drivers = _condition({"NH4": 400.0, "pH": 8.5, "Temperature": 31.5}, {}, .001, "cobia")
    nh3 = next(d for d in drivers if d["metric"] == "NH3_derived")
    assert nh3["label"] == NH3_TOXICITY_LABEL
