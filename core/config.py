"""Central config — env, stations, QCVN thresholds, QC ranges, feature sets."""
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

from core import paths

DATA_DIR = paths.DATA_DIR

# Single project .env (MongoDB, GreenLab credentials, feature flags).
load_dotenv(paths.ENV_FILE, override=False)

# --- MongoDB ---
MONGODB_URI        = os.getenv("MONGODB_URI", "")
MONGODB_DB_NAME    = os.getenv("MONGODB_DB_NAME", "data")
MONGODB_COLLECTION = os.getenv("MONGODB_COLLECTION_NAME", "quan_trac")

# --- GreenLab REST API + local raw cache (preferred live source) ---
GREENLAB_API_ENABLED = os.getenv("GREENLAB_API_ENABLED", "true").lower() in ("1", "true", "yes")
GREENLAB_API_BASE_URL = os.getenv("GREENLAB_API_BASE_URL", "https://thegreenlab.xyz")
GREENLAB_API_USERNAME = os.getenv("TK_DHTB", "")
GREENLAB_API_PASSWORD = os.getenv("MK_DHTB", "")
GREENLAB_API_CACHE_DIR = paths.GREENLAB_LIVE_CACHE_DIR

# Data source policy.  ``cache`` is useful for a stable offline demo: it uses
# the complete append-only local history and never waits on an unavailable API.
# ``live`` requests the latest API snapshot, appends it, then reads that history.
GREENLAB_FETCH_MODE = os.getenv("GREENLAB_FETCH_MODE", "live").strip().lower()

# --- Dev mode: đọc CSV thay vì MongoDB ---
USE_LOCAL_CSV  = os.getenv("USE_LOCAL_CSV", "false").lower() in ("1", "true", "yes")
LOCAL_CSV_PATH = paths.GREENLAB_EXPORT_CSV

# --- NH4 unit (chưa xác nhận vendor; default µg/L → mg/L) ---
NH4_UNIT_SCALE = float(os.getenv("NH4_UNIT_SCALE", "0.001"))
NH4_CONVERSION_CONFIRMED = os.getenv("NH4_CONVERSION_CONFIRMED", "false").lower() in ("1", "true", "yes")

# --- Weather enrichment (observation-only; never drives alerts directly) ---
WEATHER_ENABLED = os.getenv("WEATHER_ENABLED", "false").lower() in ("1", "true", "yes")
WEATHER_PROVIDER = os.getenv("WEATHER_PROVIDER", "open_meteo")
WEATHER_CACHE_TTL_MINUTES = int(os.getenv("WEATHER_CACHE_TTL_MINUTES", "60"))
# Marine context is opt-in until the installation GPS has been surveyed.  The
# research-map service remains the regional-grid source; this flag enables a
# station-level point context for the sensor pipeline.
MARINE_ENABLED = os.getenv("MARINE_ENABLED", "false").lower() in ("1", "true", "yes")
MARINE_PROVIDER = os.getenv("MARINE_PROVIDER", "open_meteo")
NH4_UNIT_NOTE  = os.getenv("NH4_UNIT_NOTE", "µg/L (×0.001) — chưa xác nhận vendor")

# --- Station registry từ stations.yaml ---
_STATIONS_PATH = paths.STATIONS_YAML
with open(_STATIONS_PATH, encoding="utf-8") as _f:
    _cfg = yaml.safe_load(_f)

STATIONS         = {s["serial"]: s for s in _cfg["stations"]}
COASTAL_STATIONS = [s["serial"] for s in _cfg["stations"] if s.get("aquaculture_relevant")]


def weather_location_for_station(station_serial: str) -> dict | None:
    """Return station-level weather location, optionally overridden by environment."""
    station = STATIONS.get(station_serial, {})
    location = dict(station.get("weather_location") or {})
    lat_override = os.getenv(f"WEATHER_{station_serial}_LATITUDE")
    lon_override = os.getenv(f"WEATHER_{station_serial}_LONGITUDE")
    if lat_override is not None and lon_override is not None:
        location.update({"latitude": float(lat_override), "longitude": float(lon_override), "accuracy": "installation_gps", "source": "environment_override"})
    if "latitude" not in location or "longitude" not in location:
        return None
    return location


def map_reference_station_for_sensor(station_serial: str) -> str | None:
    """Historical station used as the explicit map/model anchor for a sensor."""
    reference = STATIONS.get(station_serial, {}).get("map_reference_station")
    return str(reference).strip() if reference else None

# --- QN/HP training data ---
QN_DATA_PATH = paths.clean_data("quangninh")
HP_DATA_PATH = paths.clean_data("haiphong")
HY_DATA_PATH = paths.clean_data("hungyen")

# --- Imputer model dir ---
IMPUTER_DIR = paths.MODELS_DIR
IMPUTER_DIR.mkdir(exist_ok=True)

# --- Region → species (mirror hap_shared/species.py) ---
REGION_SPECIES = {"quangninh": "oyster", "haiphong": "cobia", "DongThuyAnh-HY": "unknown", "ThaiNinh-HY": "unknown"}

# --- QCVN 10:2023/BTNMT cột B1 ---
QCVN10_B1 = {
    "COD":         {"max": 10},
    "NH3":         {"max": 0.1},
    "pH":          {"min": 6.5, "max": 8.5},
    "Temperature": {"max": 30},
    "TSS":         {"max": 50},
}

# --- QC: dải giá trị vật lý hợp lý (ngoài dải → sensor lỗi) ---
PLAUSIBLE_RANGE = {
    "COD":         (0.0, 100.0),    # coastal hiếm khi >100; rail 558.8 bị loại
    "NH4":         (0.0, 500.0),    # raw sensor (trước scale)
    "NH3":         (0.0, 2.0),      # derived mg/L; guard against unit mismatch
    "DO":          (0.0, 20.0),     # direct sensor, mg/L
    "pH":          (6.0, 9.5),
    "Temperature": (0.0, 45.0),
    "TSS":         (0.0, 1000.0),
}

# --- pH plausibility for coastal seawater (SUSPECT, not INVALID; PLAUSIBLE_RANGE stays the hard range).
# Cat Ba probe drifted from 2026-09-19 (research log RL-13): before, 112 local days were 7.30-8.43 with
# no reading outside 7.0-8.6 and no 60-min change > 0.5; after, daily medians fell to ~6.7-7.1.
PH_PLAUSIBLE_BAND = (7.0, 8.6)          # coastal seawater ~7.5-8.5 plus margin
PH_MAX_CHANGE_PER_HOUR = 0.5            # |pH(t) - pH(t-60 min)| above this -> SUSPECT reading
# Day is SUSPECT if its median is out of band or more than this share of readings is (~2.4 h/day).
# Pre-drift days have 0 % out of band, so 10 % separates cleanly; > 50 % would add nothing over the
# median rule and miss 09-19, 09-22/23, 09-29, 10-01..05 and 10-10.
PH_DAY_MAX_OUT_OF_BAND_FRACTION = 0.10

# --- Imputer feature sets (adaptive theo COD validity) ---
FEATURES_5 = ["COD", "NH3", "pH", "Temperature", "TSS"]
FEATURES_4 = ["NH3", "pH", "Temperature", "TSS"]
