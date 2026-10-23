"""Admin alert-config API. Writes go to a tmp dir only."""
import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import admin_config
from core import paths


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ALERT_CONFIG_DIR", tmp_path / "alert-config")
    app = FastAPI()
    app.include_router(admin_config.router)
    return TestClient(app)


def _effective(client):
    return client.get("/api/v1/admin/alert-config").json()["effective"]


def test_get_default(client):
    r = client.get("/api/v1/admin/alert-config")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["source"] == "default"
    assert body["config_version"] == body["effective"]["config_version"]
    assert "storm_wind" in body["effective"]["hazards"]
    assert client.get("/api/v1/admin/alert-config/versions").json()["versions"] == []


def test_save_roundtrip(client):
    cfg = _effective(client)
    cfg["hazards"]["storm_wind"]["thresholds"]["2"] = 7
    r = client.post("/api/v1/admin/alert-config", json={"config": cfg, "reason_vi": "hạ ngưỡng", "changed_by": "qa"})
    assert r.status_code == 201
    v = r.json()["config_version"]
    assert v.startswith("v0001-")
    g = client.get("/api/v1/admin/alert-config").json()
    assert g["source"] == "runtime" and g["config_version"] == v
    assert g["effective"]["hazards"]["storm_wind"]["thresholds"]["2"] == 7
    versions = client.get("/api/v1/admin/alert-config/versions").json()["versions"]
    assert versions == [{"config_version": v, "changed_at": versions[0]["changed_at"], "changed_by": "qa",
                         "reason_vi": "hạ ngưỡng", "n_changes": 1}]
    full = client.get(f"/api/v1/admin/alert-config/versions/{v}").json()["version"]
    assert full["changes"][0]["path"] == "hazards.storm_wind.thresholds.2"


def test_save_invalid_422_no_write(client, tmp_path):
    cfg = _effective(client)
    cfg["hazards"]["storm_wind"]["thresholds"]["3"] = 1
    r = client.post("/api/v1/admin/alert-config", json={"config": cfg, "reason_vi": "x"})
    assert r.status_code == 422
    assert r.json()["errors"]
    assert not (tmp_path / "alert-config").exists()


def test_save_requires_reason(client):
    r = client.post("/api/v1/admin/alert-config", json={"config": _effective(client), "reason_vi": "  "})
    assert r.status_code == 422 and any("reason_vi" in e for e in r.json()["errors"])


def test_preview_no_write(client, tmp_path):
    cfg = _effective(client)
    r = client.post("/api/v1/admin/alert-config/preview", json={"config": cfg})
    body = r.json()
    assert r.status_code == 200 and body["errors"] == []
    wind = [e for e in body["tier_examples"] if e["hazard"] == "storm_wind"]
    # at threshold 8: just below -> 1, at -> 2, just above -> 2
    at8 = [e for e in wind if 7.9 < e["value"] < 8.1]
    assert [e["tier"] for e in at8] == [1, 2, 2]
    cold = [e for e in body["tier_examples"] if e["hazard"] == "cold" and 17 < e["value"] < 19]
    assert [e["tier"] for e in cold] == [2, 2, 1]
    assert not (tmp_path / "alert-config").exists()


def test_preview_reports_errors(client):
    cfg = copy.deepcopy(_effective(client))
    cfg["bogus"] = 1
    body = client.post("/api/v1/admin/alert-config/preview", json={"config": cfg}).json()
    assert body["errors"] and body["tier_examples"] == []


@pytest.mark.parametrize("v", ["v9999-20261023T000000Z", "nope", "..%2Fx"])
def test_unknown_version_404(client, v):
    assert client.get(f"/api/v1/admin/alert-config/versions/{v}").status_code == 404
