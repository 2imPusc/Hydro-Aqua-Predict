from datetime import datetime, timezone

from app import flow_artifacts


def test_flow_artifact_is_snapshot_bound_and_hides_pseudo_travel_time(tmp_path, monkeypatch):
    static_edge = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[107.0, 20.7], [107.02, 20.7]]},
        "properties": {
            "kind": "water_path_station_edge", "station_a": "A", "station_b": "B",
            "forward_alignment": 0.8, "forward_projected_speed_m_s": 0.2,
            "forward_travel_hours": 2.1,
        },
    }
    streamline = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[107.0, 20.7], [107.01, 20.7]]},
        "properties": {"kind": "flow_streamline"},
    }
    monkeypatch.setattr(flow_artifacts, "add_current_influence", lambda network, current, **_kwargs: {
        **network, "features": [static_edge, streamline],
    })
    snapshot = {
        "snapshot_id": "snapshot-1", "payload_hash": "payload-1", "geometry_hash": "geometry-1",
        "retrieved_at": datetime(2026, 1, 1, tzinfo=timezone.utc), "valid_at": None,
        "layers": [{"layer": "current", "status": "fresh", "provenance": {"source": "test"}}],
    }
    artifact = flow_artifacts.build_flow_artifact(snapshot, {"type": "FeatureCollection", "features": []}, str(tmp_path))

    assert artifact["snapshot_id"] == "snapshot-1"
    assert artifact["streamline_count"] == 1
    supported = next(feature for feature in artifact["features"] if feature["properties"]["kind"] == "current_supported_station_edge")
    assert supported["properties"]["snapshot_id"] == "snapshot-1"
    assert "forward_travel_hours" not in supported["properties"]
    assert flow_artifacts.load_flow_artifact(str(tmp_path), "snapshot-1")["artifact_id"] == artifact["artifact_id"]
