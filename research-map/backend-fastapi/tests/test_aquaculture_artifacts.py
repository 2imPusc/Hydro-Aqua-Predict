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
