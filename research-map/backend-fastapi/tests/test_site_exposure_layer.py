"""Site-exposure map layer: newest run, strict GeoJSON + cấp-10 rose, theory-only flags (no Postgres)."""
import csv

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import site_exposure_layer as layer

DIRS = layer.DIRECTIONS


def _feature(site_id, kind="station", exposure="hở (exposed)", lon=107.04, lat=20.72, extra=""):
    return ('{"type": "Feature", "geometry": {"type": "Point", "coordinates": [%s, %s]}, "properties": '
            '{"site_id": "%s", "kind": "%s", "name": "Trạm %s", "exposure_class": "%s", "worst_direction": "SW", '
            '"dangerous_directions": ["SW"], "watch_directions": [], "sheltered_directions": ["ENE"], '
            '"hs_worst_c8_m": 1.8, "hs_worst_c10_m": 2.9, "hs_worst_c12_m": 4.0, "tier_worst_c8": 2, '
            '"tier_worst_c10": 3, "tier_worst_c12": 4, "depth_site_m": %s, "used_by_alerts": false}}'
            % (lon, lat, site_id, kind, site_id, exposure, extra or "1.0"))


def _write_run(root, name="site-exposure-20261023", depth_token="1.0"):
    run = root / name
    run.mkdir(parents=True)
    features = [_feature("NB1", extra=depth_token), _feature("NB17", exposure="kín (sheltered)"), _feature("g0001", kind="grid")]
    (run / "site_exposure.geojson").write_text('{"type": "FeatureCollection", "features": [%s]}' % ", ".join(features), encoding="utf-8")
    # The 20261023 run's stations.json is not strict JSON; the layer must never read it.
    (run / "stations.json").write_text('[{"site_id": "NB1", "depth": NaN', encoding="utf-8")
    with (run / "direction_scenarios.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["site_id", "beaufort_open", "wind_open_ms", "direction", "bearing", "shelter_factor", "local_wind_ms",
                         "local_beaufort", "fetch_m", "depth_m", "hs_m", "t_s", "wave_class", "tier", "label_vi"])
        for site in ("NB1", "NB17", "g0001"):
            for bf in (8, 10, 12):
                for i, d in enumerate(DIRS):
                    hs = 2.5 if (site == "NB1" and d == "SW") else 0.4
                    writer.writerow([site, bf, 0, d, i * 22.5, 1.0, 0, bf, 200000 if d == "SW" else 1500, "" if i % 2 else 5.0,
                                     hs, 3.0, "D" if hs >= 2 else "A", 3 if hs >= 2 else 1, "x"])
    with (run / "per_direction.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["site_id", "direction", "fetch_censored"])
        for d in DIRS:
            writer.writerow(["NB1", d, "True" if d == "SW" else "False"])
    return run


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SITE_EXPOSURE_ROOT", str(tmp_path))
    layer._CACHE.clear()
    app = FastAPI()
    app.include_router(layer.router)
    return TestClient(app)


def test_unavailable_without_run(client):
    body = client.get("/api/v1/research/site-exposure").json()
    assert body["status"] == "unavailable"
    assert body["reason"] == "site_exposure_run_missing"
    assert body["used_by_alerts"] is False and body["notification_eligible"] is False
    assert body["basis"] == "theory_only_unvalidated"


def test_stations_rose_and_flags(client, tmp_path):
    _write_run(tmp_path, "site-exposure-20261022")
    _write_run(tmp_path, "site-exposure-20261023")
    body = client.get("/api/v1/research/site-exposure").json()
    assert body["status"] == "ready"
    assert body["run_name"] == "site-exposure-20261023"  # newest run wins
    assert body["used_by_alerts"] is False and body["notification_eligible"] is False
    assert body["basis"] == "theory_only_unvalidated"
    assert [s["id"] for s in body["stations"]] == ["NB1", "NB17"]  # grid points are not served
    nb1 = body["stations"][0]
    assert nb1["exposure_class"] == "exposed" and nb1["exposure_label_vi"] == "hở"
    assert body["stations"][1]["exposure_class"] == "sheltered"
    assert [r["direction"] for r in nb1["rose"]] == list(DIRS)
    sw = next(r for r in nb1["rose"] if r["direction"] == "SW")
    assert sw["hs_m"] == 2.5 and sw["fetch_km"] == 200.0 and sw["fetch_censored"] is True and sw["tier"] == 3
    assert next(r for r in nb1["rose"] if r["direction"] == "N")["fetch_censored"] is False
    assert body["rose_beaufort"] == 10


def test_nan_tokens_become_null(client, tmp_path):
    _write_run(tmp_path, depth_token="NaN")
    body = client.get("/api/v1/research/site-exposure").json()
    assert body["status"] == "ready"
    assert body["stations"][0]["depth_site_m"] is None


@pytest.mark.parametrize("raw, key", [("hở (exposed)", "exposed"), ("bán kín (semi)", "semi"), ("kín", "sheltered"), ("semi", "semi"), ("?", None)])
def test_exposure_key(raw, key):
    assert layer.exposure_key(raw) == key
