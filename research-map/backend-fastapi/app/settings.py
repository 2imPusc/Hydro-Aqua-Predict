from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _csv_env(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


def _default_cache_dir() -> str:
    docker_cache = Path("/cache")
    if docker_cache.is_dir():
        return str(docker_cache)
    return str(Path(__file__).resolve().parents[2] / "cache")


def _default_copernicus_bathymetry_path() -> str:
    docker_path = Path("/workspace/data/depth/haiphong_copernicus_bathymetry_100m_202511.nc")
    if docker_path.exists():
        return str(docker_path)
    return str(Path(__file__).resolve().parents[3] / "data/depth/haiphong_copernicus_bathymetry_100m_202511.nc")


def _default_etopo_bathymetry_path() -> str:
    relative = "data/depth/etopo2022-20261023/etopo2022_15s_hp_qn.nc"  # scripts/download_etopo2022_bathymetry.py
    docker_path = Path("/workspace") / relative
    if docker_path.exists():
        return str(docker_path)
    return str(Path(__file__).resolve().parents[3] / relative)


def _workspace_root() -> Path:
    """Repo root: the read-only Docker mount when present, else this checkout.

    Checks the mount itself (not a leaf path) so a not-yet-created export dir
    under /workspace never falls back to a path inside the image.
    """
    docker_root = Path("/workspace")
    if docker_root.is_dir():
        return docker_root
    return Path(__file__).resolve().parents[3]


# Vite dev server (5173, or 5174 when 5173 is taken) and the docker frontend (8083),
# under both localhost and 127.0.0.1. Override with a comma-separated CORS_ALLOW_ORIGINS.
DEFAULT_CORS_ORIGINS = ",".join(
    f"http://{host}:{port}" for port in (5173, 5174, 8083) for host in ("localhost", "127.0.0.1"))


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "postgresql://context_user:change_me@localhost:5434/context_research")
    latitude: float = float(os.getenv("CONTEXT_LATITUDE", "20.71894498573044"))
    longitude: float = float(os.getenv("CONTEXT_LONGITUDE", "107.042635855355"))
    snapshot_minutes: int = int(os.getenv("CONTEXT_SNAPSHOT_MINUTES", "30"))
    stale_minutes: int = int(os.getenv("CONTEXT_STALE_MINUTES", "90"))
    context_buffer_m: int = int(os.getenv("CONTEXT_BUFFER_M", "5000"))
    copernicus_username: str = os.getenv("COPERNICUS_USERNAME", "")
    copernicus_password: str = os.getenv("COPERNICUS_PASSWORD", "")
    copernicus_physics_dataset: str = os.getenv("COPERNICUS_PHYSICS_DATASET", "")
    copernicus_current_dataset: str = os.getenv("COPERNICUS_CURRENT_DATASET", "")
    copernicus_sea_level_dataset: str = os.getenv("COPERNICUS_SEA_LEVEL_DATASET", "")
    copernicus_mld_dataset: str = os.getenv("COPERNICUS_MLD_DATASET", "")
    copernicus_wave_dataset: str = os.getenv("COPERNICUS_WAVE_DATASET", "")
    gebco_raster_path: str = os.getenv("GEBCO_RASTER_PATH", "/cache/gebco.tif")
    copernicus_bathymetry_path: str = os.getenv("COPERNICUS_BATHYMETRY_PATH", _default_copernicus_bathymetry_path())
    etopo_bathymetry_path: str = os.getenv("ETOPO_BATHYMETRY_PATH", _default_etopo_bathymetry_path())
    cache_dir: str = os.getenv("CONTEXT_CACHE_DIR", _default_cache_dir())
    sensor_stale_minutes: int = int(os.getenv("SENSOR_STALE_MINUTES", "10"))
    sensor_ingest_token: str = os.getenv("SENSOR_INGEST_TOKEN", "")
    greenlab_api_enabled: bool = os.getenv("GREENLAB_API_ENABLED", "true").lower() in {"1", "true", "yes"}
    greenlab_api_base_url: str = os.getenv("GREENLAB_API_BASE_URL", "https://thegreenlab.xyz")
    greenlab_api_username: str = os.getenv("TK_DHTB", "")
    greenlab_api_password: str = os.getenv("MK_DHTB", "")
    greenlab_station_serials: tuple[str, ...] = _csv_env("GREENLAB_STATION_SERIALS", "06M26042804")
    sensor_poll_seconds: int = int(os.getenv("SENSOR_POLL_SECONDS", "60"))
    nh4_unit_scale: float = float(os.getenv("NH4_UNIT_SCALE", "0.001"))
    nh3_max_metric_gap_minutes: int = int(os.getenv("NH3_MAX_METRIC_GAP_MINUTES", "5"))
    # Read-only research views (app/research.py). Nothing here is ever written by the API.
    research_export_dir: str = os.getenv("RESEARCH_EXPORT_DIR", str(_workspace_root() / "artifacts" / "research-map"))
    hap_runtime_dir: str = os.getenv("RESEARCH_RUNTIME_DIR", str(_workspace_root() / "runtime"))
    weather_snapshots_path: str = os.getenv(
        "WEATHER_SNAPSHOTS_PATH", str(_workspace_root() / "artifacts" / "experiments" / "forecast-v2" / "weather-snapshots.jsonl"))
    sensor_future_manifest_path: str = os.getenv(
        "SENSOR_FUTURE_MANIFEST_PATH", str(_workspace_root() / "core" / "models" / "sensor_future" / "sensor_future_long_manifest.json"))
    cors_allow_origins: tuple[str, ...] = _csv_env("CORS_ALLOW_ORIGINS", DEFAULT_CORS_ORIGINS)
    ledger_tail_bytes: int = int(os.getenv("RESEARCH_LEDGER_TAIL_BYTES", str(16 * 1024 * 1024)))


settings = Settings()
