"""Single source of truth for filesystem locations.

Every module that needs a path imports it from here instead of walking
``Path(__file__).parents[N]``. Data-heavy locations can be redirected with
``HAP_*`` environment variables (e.g. to keep ``data/`` on another drive).
"""
from __future__ import annotations

import os
from pathlib import Path


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    return Path(value).expanduser().resolve() if value else default


PROJECT_ROOT = _env_path("HAP_ROOT", Path(__file__).resolve().parents[1])
ENV_FILE = PROJECT_ROOT / ".env"

# --- Code-adjacent resources (tracked in git) ---
CORE_DIR = PROJECT_ROOT / "core"
MODELS_DIR = CORE_DIR / "models"
SPATIAL_MODELS_DIR = MODELS_DIR / "spatial"
ASSETS_DIR = PROJECT_ROOT / "assets"
INGEST_DIR = PROJECT_ROOT / "ingest"
STATIONS_YAML = INGEST_DIR / "stations.yaml"

# --- Local data (gitignored; see docs/data-policy.md) ---
DATA_DIR = _env_path("HAP_DATA_DIR", PROJECT_ROOT / "data")
GREENLAB_DIR = DATA_DIR / "greenlab"
GREENLAB_EXPORTS_DIR = GREENLAB_DIR / "exports"
GREENLAB_ALL_DATA_DIR = GREENLAB_EXPORTS_DIR / "all_data"
GREENLAB_INTERVALS_DIR = GREENLAB_EXPORTS_DIR / "intervals"
GREENLAB_LIVE_CACHE_DIR = GREENLAB_EXPORTS_DIR / "live-cache"
GREENLAB_EXPORT_CSV = GREENLAB_DIR / "greenlab_export.csv"
STATION_COORDINATES = DATA_DIR / "map" / "station_coordinates.csv"
WATER_SHAPEFILE = _env_path("HAP_WATER_SHAPEFILE", DATA_DIR / "map" / "water_polygons_clip" / "water_polygons.shp")
DEPTH_DIR = DATA_DIR / "depth"
CMEMS_CACHE_DIR = DATA_DIR / "haiphong" / "_cmems_cache"
ALERT_CONFIG_DEFAULT = PROJECT_ROOT / "config" / "alert_tiers.default.json"  # tracked defaults
COBIA_THRESHOLDS = PROJECT_ROOT / "hap_shared" / "thresholds" / "cobia_thresholds.json"
SUITABILITY_LAYERS_DIR = DATA_DIR / "suitability"  # direction 3 (HP + QN) site-suitability inputs
SUITABILITY_HK_DIR = DATA_DIR / "suitability_hk"  # direction 3 out-of-sample check (Hong Kong)
FOREIGN_DATA_DIR = DATA_DIR / "foreign"  # direction 4 foreign test datasets, one subfolder per source
HAZARD_DATA_DIR = DATA_DIR / "hazards"  # theory track: IBTrACS, OISST, ERA5, marine SST downloads (write-once)
TERRAIN_DIR = DATA_DIR / "terrain"  # land DEM/DSM tiles (write-once), e.g. Copernicus GLO-30 for wind shelter
CMEMS_DIR = DATA_DIR / "cmems"  # Copernicus Marine point/area extracts (write-once, model named)
ECMWF_OPENDATA_DIR = HAZARD_DATA_DIR / "ecmwf-opendata"  # real-time ECMWF TC track files (write-once)
REFERENCES_DIR = DATA_DIR / "references"  # local text copies of cited sources (write-once)


def clean_data(region: str) -> Path:
    """Historical monitoring table for ``haiphong`` / ``quangninh`` / ``hungyen``."""
    return DATA_DIR / region / "clean_data.csv"


# --- Generated state (gitignored) ---
RUNTIME_DIR = _env_path("HAP_RUNTIME_DIR", PROJECT_ROOT / "runtime")
FORECAST_SHADOW_DIR = RUNTIME_DIR / "forecast-shadow"
HAZARD_SHADOW_DIR = RUNTIME_DIR / "hazard-shadow"  # per-station hazard alerts, append-only JSONL
ALERT_CONFIG_DIR = RUNTIME_DIR / "alert-config"  # admin alert-tier versions, append-only (decisions #20)
ARTIFACTS_DIR = _env_path("HAP_ARTIFACTS_DIR", PROJECT_ROOT / "artifacts")
EXPERIMENT_OUTPUT_DIR = ARTIFACTS_DIR / "experiments"
RESEARCH_MAP_EXPORT_DIR = ARTIFACTS_DIR / "research-map"  # write-once JSON exports read by research-map/


if __name__ == "__main__":
    for key, value in sorted(globals().items()):
        if key.isupper() and isinstance(value, Path):
            print(f"{key:28s} {value}  {'OK' if value.exists() else 'missing'}")
