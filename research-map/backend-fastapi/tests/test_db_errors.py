"""DB-backed endpoints fail as JSON 503 with CORS headers when Postgres is unreachable."""
import psycopg
import pytest
from fastapi.testclient import TestClient

from app import main
from app.settings import DEFAULT_CORS_ORIGINS


class _DownRepository:
    def latest(self):
        raise psycopg.OperationalError("connection refused")

    def by_id(self, snapshot_id):
        raise psycopg.InterfaceError("connection closed")

    def latest_sensor(self, station_serial):
        raise psycopg.errors.UndefinedTable("relation does not exist")


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(main, "repository", _DownRepository())
    # Plain TestClient (no context manager): startup hooks do not run.
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5174", "http://localhost:8083"])
def test_database_down_returns_503_json_with_cors(client, origin):
    response = client.get("/api/v1/context/latest", headers={"Origin": origin})
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "reason": "database_unavailable"}
    assert response.headers.get("access-control-allow-origin") == origin


def test_interface_error_is_also_unavailable(client):
    response = client.get("/api/v1/context/snap-1/layers/wind", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 503
    assert response.json()["reason"] == "database_unavailable"
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_unknown_origin_gets_no_cors_header(client):
    response = client.get("/api/v1/context/latest", headers={"Origin": "http://evil.example"})
    assert response.status_code == 503
    assert "access-control-allow-origin" not in response.headers


def test_default_cors_origins_cover_vite_ports_on_both_hosts():
    origins = set(DEFAULT_CORS_ORIGINS.split(","))
    for port in (5173, 5174, 8083):
        assert {f"http://localhost:{port}", f"http://127.0.0.1:{port}"} <= origins


def test_other_database_errors_are_json_500_with_cors(client):
    response = client.get("/api/v1/stations/06M26042804/latest", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 500
    assert response.json() == {"status": "error", "reason": "database_error"}
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
