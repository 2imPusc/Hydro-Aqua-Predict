"""Export compact, versioned research artifacts for the research map (write-once).

Reads finished experiment runs (rows of ``experiments/RESULTS.md``) and writes small
JSON files that the research-map backend serves read-only:

    artifacts/research-map/<YYYYMMDD-HHMM>/
        overview.json                      H1-H4 headlines/findings (numbers from artifacts or quoted RL entries)
        forecast_benchmark.json            gate #16 tables (H1.2, A1 nopH, A3 pH clean) + conformal coverage
        suitability_<vn|hk>_<variant>.json cells (GeoJSON points) + farms + AUC/notes, variant A_W_SUM | N1_W_SUM
        reliability_foreign_index.json     dataset cards (credit, licence, headline, bbox, scales)
        reliability_foreign_<id>.json      stations, pair statistics, radius table per foreign dataset
        reliability_vn.json                A6 salinity-regime layer (only when that run exists)
        hazards.json                       H2 theory track: storm/heat climatology + skill, disease, stocking calendar
        manifest.json                      sources (sha256), output files (sha256), omitted outputs + reason

Missing inputs are omitted with a reason in the manifest, never filled in. Maryland DNR
(Chesapeake) raw data must not be redistributed: only aggregated pair/radius statistics
and station coordinates are exported. Every run writes a new stamped directory (re-run
later to pick up new experiment runs); existing export directories are never touched.

    .venv\\Scripts\\python scripts\\export_research_map_artifacts.py [--stamp 20261017-1500]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402

SCHEMA_VERSION = "research-map-export-v1"
STAMP_RE = re.compile(r"^\d{8}-\d{4}$")

# ---------------------------------------------------------------- input runs (experiments/RESULTS.md)
H12_TEMPERATURE_RUN = "forecast-h1.2-20261016-Temperature"
H12_ADDON_RUN = "forecast-h1.2-20261016-addon-dm"
A1_RUN = "forecast-a1-temperature-nopH-20261017"
A3_RUN = "forecast-a3-ph-pre-drift-20261017"
CONFORMAL_V3_RUN = "forecast-h1.3-conformal-20261016-v3"
CONFORMAL_AMP_RUN = "forecast-h1.3-conformal-20261017-amp"
SUIT_VN_DRAFT_RUN = "suitability-h3-2024-draft"
SUIT_VN_NEARSHORE_RUN = "suitability-h3-2024-nearshore"
SUIT_HK_RUN = "suitability-hk-2024"
MULTISCALE_RUN = "h4-multiscale-20261017"
VN_REGIME_RUN = "vn-salinity-regime-h41-20261017"

SUIT_VARIANTS = ("A_W_SUM", "N1_W_SUM")
SUIT_REGIONS = ("vn", "hk")
CONFORMAL_METHODS = ("static", "static_night", "aci_scaled", "aci_amp")
SCALE_ORDER = ("monthly", "hourly", "daily_mean", "daily_min", "daily_max", "weekly_mean")
GATE16_RULE = "gate #16 (decisions #16): >= 4/5 rolling folds beat persistence and lockbox DM p < 0.05 (ridge)"

# Wet-season median salinity classes: A6 cuts (experiments/spatial_regime.py, 20 / 28 psu) plus 'fresh' < 0.5 psu.
REGIME_CLASS_RULE = "wet-season median salinity: fresh < 0.5, estuarine_brackish < 20, transitional 20-28, marine >= 28 psu"
VAR_MAP = {"DO_mgl": "DO", "Turbidity": "Turb"}
TRANSFER_MAP = {"raw": "raw", "persistence_in_space": "raw", "calibrated": "calibrated",
                "calibrated_30d": "calibrated", "calibrated_24m": "calibrated"}
REGIME_MAP = {"same": "same", "similar_regime": "same", "different": "different", "different_regime": "different",
              "all": "all", "any": "all"}

MDDNR_CREDIT = ("Data provided by the Maryland Department of Natural Resources, "
                "Tidewater Ecosystem Assessment Division.")

# Dataset cards. Licence/credit text from data/foreign/*/SOURCES.md, probe_korea_irlon/NOTES.md and
# CANDIDATES-H4.md; headlines quoted from docs/research-log.md (RL id in brackets).
FOREIGN: dict[str, dict] = {
    "hk_epd": {
        "run": "hk-epd-reliability-20261016", "adapter": "hk", "rl": "RL-14",
        "name": "Hong Kong EPD — quan trắc chất lượng nước biển", "region": "Hong Kong", "country": "HK",
        "cadence": "monthly", "period": "2015–2025", "climate": "cận nhiệt đới gió mùa",
        "licence": "chưa ghi nhận điều khoản trong repo; chỉ xuất thống kê tổng hợp",
        "credit": "Environmental Protection Department, HKSAR Government (marine water quality data; station points via CSDI)",
        "redistributable": False,
        "headline": "Chế độ mặn quyết định, không phải nhãn vùng; bán kính 80 % cùng chế độ: Temp 5 km, Sal 5 km, pH > 20 km (mẫu tháng) [RL-14]",
        "findings": ["Nhãn vùng kiểm soát nước (WCZ) gần như không thêm thông tin (±0.05) [RL-14]",
                     "Cặp khác chế độ mặn không đạt 80 % ở bất kỳ khoảng cách nào; DO, TSS, NH3 không có bán kính [RL-14]",
                     "Mưa ≥ 20 mm trong 3 ngày trước làm tỷ lệ đạt của Sal giảm 0.30 [RL-14]"],
    },
    "nerrs_jobos": {
        "run": "nerrs-h4-pilot-20261016", "adapter": "jobos", "rl": "RL-12",
        "name": "NOAA NERRS — Jobos Bay (Puerto Rico)", "region": "Puerto Rico", "country": "US",
        "cadence": "15 min → hourly", "period": "2007–2011", "climate": "nhiệt đới, triều nhỏ",
        "licence": "U.S. Government work, public (NCEI archive)",
        "credit": "NOAA National Estuarine Research Reserve System (NERRS), System-wide Monitoring Program; CDMO, via NCEI",
        "redistributable": True,
        "headline": "Lấy nguyên giá trị trạm neo không đạt ô nào (0/936); loại môi trường quan trọng hơn khoảng cách [RL-12]",
        "findings": ["Cặp 09↔19 cách 1.0 km nhưng khác môi trường: Temp 0.30; cặp 19↔20 cách 2.3 km cùng môi trường: 0.68 [RL-12]",
                     "Ánh xạ hiệu chỉnh: chỉ pH ±0.2 đạt 80 % (5/12 cặp) [RL-12]",
                     "Mưa ≥ 10 mm/24 h làm ánh xạ hiệu chỉnh kém đi (Δ −0.11) [RL-12]"],
    },
    "nerrs_multi": {
        "run": "nerrs-multi-h4-reliability-20261017", "adapter": "generic", "rl": "RL-20",
        "group_col": "reserve", "station_filter": ("kind", "wq"),
        "name": "NOAA NERRS — 8 khu cận nhiệt đới/nhiệt đới", "region": "US Gulf/Atlantic, Puerto Rico", "country": "US",
        "cadence": "15 min → hourly", "period": "2007–2011", "climate": "cận nhiệt đới / nhiệt đới",
        "licence": "U.S. Government work, public (NCEI archive)",
        "credit": "NOAA National Estuarine Research Reserve System (NERRS), System-wide Monitoring Program; CDMO, via NCEI accession 0052765",
        "redistributable": True,
        "headline": "Đạt 80 %: Temp/Sal/DO/Turb 0/90 cặp; pH hiệu chỉnh 39/90; bán kính gộp 0 km [RL-20]",
        "findings": ["|Δ độ mặn| làm giảm độ tin cậy Sal/pH/Turb thô; khoảng cách không có ý nghĩa trong mọi mô hình [RL-20]",
                     "Mưa ≥ 20 mm/3 ngày: pH thô −0.16, kém đi có ý nghĩa ở 8/8 khu [RL-20]"],
    },
    "mddnr": {
        "run": "mddnr-h4-reliability-20261017", "adapter": "generic", "rl": "RL-21", "max_km": 30.0,
        "name": "Maryland DNR ConMon — Chesapeake Bay", "region": "Chesapeake Bay", "country": "US",
        "cadence": "15 min → hourly (theo mùa 4–10)", "period": "2004–2009", "climate": "ôn đới",
        "licence": "Eyes on the Bay data-use policy: không phát tán lại dữ liệu thô; chỉ xuất thống kê tổng hợp",
        "credit": MDDNR_CREDIT, "redistributable": False,
        "headline": "Chỉ độ mặn chuyển được (hiệu chỉnh đạt 80 % tới ≥ 30 km); Temp/DO/pH/Turb không đạt kể cả 0–2 km [RL-21]",
        "findings": ["Chế độ mặn > khoảng cách chỉ với Sal và pH thô; Temp và DO theo khoảng cách [RL-21]",
                     "Iron Pot ↔ Jug Bay (1.7 km, đầm lầy so với lòng kênh) lệch nhiệt ~1.7 °C [RL-21]"],
    },
    "twdb": {
        "run": "twdb-h4-reliability-20261017", "adapter": "generic", "rl": "RL-22",
        "name": "Texas Water Development Board — cửa sông Texas", "region": "Texas coast", "country": "US",
        "cadence": "hourly", "period": "2008–2019", "climate": "cận nhiệt đới, vi triều",
        "licence": "Texas Water Development Board public data (no warranty)",
        "credit": "TWDB Texas Coastal Hydrology data, waterdatafortexas.org/coastal",
        "redistributable": True,
        "headline": "Không biến nào đạt 80 % ở bất kỳ khoảng cách nào; Sal theo chế độ, Temp theo khoảng cách [RL-22]",
        "findings": ["Chỉ 3 cặp cùng chế độ ≤ 30 km; dữ liệu từ 2020 bị loại (độ mặn làm tròn 1 psu) [RL-22]"],
    },
    "usgs_sfbay": {
        "run": "usgs-sfbay-h4-reliability-20261017", "adapter": "generic", "rl": "RL-23",
        "name": "USGS — vịnh San Francisco", "region": "San Francisco Bay", "country": "US",
        "cadence": "15 min → hourly", "period": "WY2018–2025", "climate": "Địa Trung Hải, mùa mưa đông",
        "licence": "U.S. public domain (USGS)",
        "credit": "U.S. Geological Survey, National Water Information System",
        "redistributable": True,
        "headline": "Bán kính 80 %: Temp 10 km (cùng chế độ) / 5 km (khác); Sal 0 km; Turb không có [RL-23]",
        "findings": ["Sal: chế độ > khoảng cách (R² 0.55 so với 0.15); Temp: khoảng cách > chế độ (R² 0.66 so với 0.19) [RL-23]",
                     "Mưa ≥ 20 mm/72 h (mùa ướt): Sal hiệu chỉnh −0.09…−0.11 [RL-23]"],
    },
    "irlon": {
        # -20261017 and -r2 are aborted partial runs (MemoryError, no manifest); -r3 is the complete one.
        "run": "irlon-h4-reliability-20261017-r3", "adapter": "generic", "rl": "RL-28",
        "name": "IRLON (HBOI-FAU) — Indian River Lagoon", "region": "Indian River Lagoon, Florida", "country": "US",
        "cadence": "hourly", "period": "2014/15–2026", "climate": "cận nhiệt đới",
        "licence": "SECOORA ERDDAP: dùng và phát tán tự do, ghi nguồn hệ thống quan trắc vùng/NOAA",
        "credit": ("Indian River Lagoon Observatory Network of Environmental Sensors (IRLON), Harbor Branch "
                   "Oceanographic Institute at Florida Atlantic University; via SECOORA ERDDAP"),
        "redistributable": True,
        "headline": "Bán kính 80 % theo giờ: Temp 5 km, còn lại 0; theo ngày: Temp 10 km, pH hiệu chỉnh 10 km [RL-28]",
        "findings": ["Sal, pH: chế độ mặn > khoảng cách (R² 0.61/0.67 so với ≈ 0) [RL-28]",
                     "DO, độ đục không chuyển được ở bất kỳ khoảng cách nào; chỉ 2 cặp cùng chế độ ≤ 30 km [RL-28]"],
    },
}
MULTISCALE_DATASETS = {"nerrs_pooled": "nerrs_multi", "nerrs": "nerrs_multi", "mddnr": "mddnr", "twdb": "twdb",
                       "usgs_sfbay": "usgs_sfbay", "usgs": "usgs_sfbay", "irlon": "irlon"}


# ---------------------------------------------------------------- helpers
def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean(obj):
    """JSON-safe copy: NaN/inf -> None, numpy scalars -> Python."""
    if isinstance(obj, dict):
        return {str(key): clean(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(value) for value in obj]
    if obj is None or obj is pd.NA or obj is pd.NaT:
        return None
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        value = float(obj)
        return value if math.isfinite(value) else None
    return obj


def _num(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _r(value, digits: int = 4) -> float | None:
    out = _num(value)
    return None if out is None else round(out, digits)


def _int(value) -> int | None:
    out = _num(value)
    return None if out is None else int(round(out))


def _sig(value, digits: int = 3) -> float | None:
    out = _num(value)
    return None if out is None else float(f"{out:.{digits}g}")


def _str(value) -> str | None:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    text = str(value).strip()
    return text or None


def _gate_status(value) -> str | None:
    text = _str(value)
    return None if text is None else text.lower()


def _gate_name(value) -> str | None:
    match = re.search(r"(\d+)", str(value))
    return f"gate{match.group(1)}" if match else None


def _regime(value) -> str | None:
    text = _str(value)
    return None if text is None else REGIME_MAP.get(text, text)


def regime_class(wet_sal) -> str:
    value = _num(wet_sal)
    if value is None:
        return "unknown"
    if value < 0.5:
        return "fresh"
    if value < 20.0:
        return "estuarine_brackish"
    return "transitional" if value < 28.0 else "marine"


def _radius_value(value) -> tuple[float | None, str | None]:
    """'5 km' -> (5, '5 km'); '>20 km' -> (20, '>20 km'); 'insufficient' / NaN -> (None, label)."""
    numeric = _num(value)
    if numeric is not None:
        return numeric, None
    text = _str(value)
    if text is None:
        return None, None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    return (float(match.group(1)) if match else None), text


def _point(lon, lat, properties: dict) -> dict:
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [_r(lon, 5), _r(lat, 5)]},
            "properties": properties}


def _round_coords(coords, digits: int = 5):
    if isinstance(coords, (list, tuple)) and coords and isinstance(coords[0], (int, float)):
        return [round(float(c), digits) for c in coords]
    return [_round_coords(c, digits) for c in coords]


def _round_geojson(collection: dict, digits: int = 3) -> dict:
    features = []
    for feature in collection.get("features", []):
        geometry = feature.get("geometry") or {}
        props = {key: (_r(value, digits) if isinstance(value, float) else value)
                 for key, value in (feature.get("properties") or {}).items()}
        features.append({"type": "Feature", "properties": props,
                         "geometry": {**geometry, "coordinates": _round_coords(geometry.get("coordinates", []))}
                         if geometry else None})
    return {"type": "FeatureCollection", "features": features}


class Ctx:
    """Input locations plus a record of every file read (path -> sha256) and every skipped run."""

    def __init__(self, experiments_dir: Path, data_dir: Path, research_log: Path | None):
        self.exp = Path(experiments_dir)
        self.data = Path(data_dir)
        self.research_log = Path(research_log) if research_log else None
        self.sources: dict[str, str] = {}
        self.skipped: dict[str, str] = {}

    def _rel(self, path: Path) -> str:
        path = Path(path).resolve()
        try:
            return path.relative_to(paths.PROJECT_ROOT.resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    def track(self, path: Path) -> None:
        self.sources[self._rel(path)] = sha256(path)

    def read_csv(self, path: Path, **kwargs) -> pd.DataFrame:
        frame = pd.read_csv(path, **kwargs)
        self.track(path)
        return frame

    def read_json(self, path: Path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        self.track(path)
        return payload

    def run(self, name: str, required: tuple[str, ...]) -> Path | None:
        """Run dir when every required file exists; otherwise record why and return None."""
        directory = self.exp / name
        if not directory.is_dir():
            self.skipped[name] = "run_dir_missing"
            return None
        if not any(directory.iterdir()):
            self.skipped[name] = "run_dir_empty"
            return None
        missing = [f for f in required if not (directory / f).is_file()]
        if missing:
            self.skipped[name] = "missing_files:" + ",".join(missing)
            return None
        return directory


# ---------------------------------------------------------------- H1 forecast benchmark
def _variant(target: str, feature_set: str) -> str:
    if target == "pH":
        return "pH_target"
    return "nopH" if str(feature_set).endswith("_nopH") else "with_pH"


def gate16_from_metrics(metrics: pd.DataFrame, dm: pd.DataFrame, model: str = "ridge") -> pd.DataFrame:
    """Recompute the gate #16 summary (same rule and columns as A1/A3 ``gate16_summary.csv``)."""
    rows = []
    keys = ["target", "horizon_minutes", "feature_set"]
    persistence = metrics[metrics["model"] == "persistence"]
    for (target, horizon, feature_set), grp in metrics[metrics["model"] == model].groupby(keys):
        base = persistence[(persistence["target"] == target) & (persistence["horizon_minutes"] == horizon)
                           & (persistence["feature_set"] == feature_set)]
        roll = grp[grp["split"] == "rolling"].set_index("fold")["mae"]
        proll = base[base["split"] == "rolling"].set_index("fold")["mae"].reindex(roll.index)
        lock, plock = grp[grp["split"] == "lockbox"]["mae"], base[base["split"] == "lockbox"]["mae"]
        if roll.empty or lock.empty or plock.empty:
            continue
        won = int((roll < proll).sum())
        test = dm[(dm["target"] == target) & (dm["horizon_minutes"] == horizon)
                  & (dm["feature_set"] == feature_set) & (dm["model"] == model)]
        p_value = float(test["p_value"].iloc[0]) if len(test) else math.nan
        stat = float(test["dm_stat"].iloc[0]) if len(test) else math.nan
        passed = won >= 4 and p_value < 0.05 and stat < 0
        rows.append({"target": target, "horizon_minutes": int(horizon), "feature_set": feature_set,
                     "n_lock": None, "lock_mae": float(lock.iloc[0]), "pers_mae": float(plock.iloc[0]),
                     "skill_pct": (1 - float(lock.iloc[0]) / float(plock.iloc[0])) * 100,
                     "rolling_skill_pct_mean": float(((proll - roll) / proll * 100).mean()),
                     "folds_won": f"{won}/{len(roll)}", "dm_p": p_value, "dm_stat": stat,
                     "gate": "PASS" if passed else "fail"})
    return pd.DataFrame(rows)


def _gate16_rows(frame: pd.DataFrame, source: str, source_run: str) -> list[dict]:
    rows = []
    for rec in frame.to_dict("records"):
        rows.append({"target": rec["target"], "horizon_min": int(rec["horizon_minutes"]),
                     "feature_set": rec["feature_set"], "variant": _variant(rec["target"], rec["feature_set"]),
                     "skill": _r(rec.get("skill_pct"), 1), "rolling_skill": _r(rec.get("rolling_skill_pct_mean"), 1),
                     "folds_won": _str(rec.get("folds_won")), "dm_p": _sig(rec.get("dm_p")),
                     "gate": _gate_status(rec.get("gate")), "lock_mae": _r(rec.get("lock_mae")),
                     "persistence_mae": _r(rec.get("pers_mae")), "source": source, "source_run": source_run})
    return rows


def _conformal_rows(frame: pd.DataFrame, targets: tuple[str, ...], source_run: str, validity: str | None) -> list[dict]:
    frame = frame[(frame["model"] == "ridge") & frame["method"].isin(CONFORMAL_METHODS) & frame["target"].isin(targets)]
    rows = []
    for rec in frame.to_dict("records"):
        rows.append({"target": rec["target"], "feature_set": rec["feature_set"], "method": rec["method"],
                     "horizon_min": int(rec["horizon_minutes"]), "level": _r(rec.get("nominal"), 2),
                     "coverage": _r(rec.get("coverage"), 3), "coverage_late": _r(rec.get("coverage_late"), 3),
                     "width": _r(rec.get("mean_width"), 3), "winkler": _r(rec.get("winkler"), 3),
                     "frac_infinite": _r(rec.get("frac_infinite"), 3), "gate": _gate_status(rec.get("gate_pi80_pass")),
                     "source_run": source_run, "validity": validity})
    return rows


def build_forecast_benchmark(ctx: Ctx) -> tuple[dict | None, str | None]:
    temperature, ph_clean, conformal, missing = [], [], [], []
    if (run := ctx.run(H12_TEMPERATURE_RUN, ("metrics_per_fold.csv", "dm_tests.csv"))):
        metrics = ctx.read_csv(run / "metrics_per_fold.csv")
        dm = ctx.read_csv(run / "dm_tests.csv")
        temperature += _gate16_rows(gate16_from_metrics(metrics, dm), "H1.2", H12_TEMPERATURE_RUN)
    else:
        missing.append(H12_TEMPERATURE_RUN)
    if (run := ctx.run(A1_RUN, ("gate16_summary.csv",))):
        temperature += _gate16_rows(ctx.read_csv(run / "gate16_summary.csv"), "A1", A1_RUN)
    else:
        missing.append(A1_RUN)
    if (run := ctx.run(A3_RUN, ("gate16_summary.csv",))):
        ph_clean += _gate16_rows(ctx.read_csv(run / "gate16_summary.csv"), "A3", A3_RUN)
    else:
        missing.append(A3_RUN)
    if (run := ctx.run(CONFORMAL_AMP_RUN, ("coverage.csv",))):
        conformal += _conformal_rows(ctx.read_csv(run / "coverage.csv"), ("Temperature",), CONFORMAL_AMP_RUN, None)
    else:
        missing.append(CONFORMAL_AMP_RUN)
    if (run := ctx.run(CONFORMAL_V3_RUN, ("coverage.csv",))):
        conformal += _conformal_rows(ctx.read_csv(run / "coverage.csv"), ("pH",), CONFORMAL_V3_RUN,
                                     "invalidated_ph_probe_drift_RL-13")
    else:
        missing.append(CONFORMAL_V3_RUN)
    if not (temperature or ph_clean or conformal):
        return None, "forecast_runs_missing"
    return {
        "gate_rule": GATE16_RULE,
        "temperature": temperature, "ph_clean": ph_clean, "conformal": conformal, "missing_runs": missing,
        "notes": [
            "H1.2 (sensor-history-20261014, lockbox đến 14/10): gate #16 tính lại từ metrics_per_fold + dm_tests (ridge).",
            "A1 (sensor-history-20261015, lockbox 01–15/10): nhiệt độ có/không có lag pH [RL-18].",
            "A3: pH trên giai đoạn sạch (lockbox 04–18/09); kết luận pH của H1.2 bị bác bỏ [RL-13, RL-18].",
            "aci_amp: cửa sổ 24 h chọn sau khi xem lockbox → gần in-sample, cần shadow xác nhận [RL-19].",
            "Độ phủ conformal pH (v3) nằm trong giai đoạn đầu dò pH trôi → không có giá trị [RL-13].",
        ],
    }, None


# ---------------------------------------------------------------- H3 suitability
VN_SUIT_RUNS = {"A_W_SUM": (SUIT_VN_DRAFT_RUN, SUIT_VN_NEARSHORE_RUN), "N1_W_SUM": (SUIT_VN_NEARSHORE_RUN,)}


def _cell_size(values: pd.Series) -> float | None:
    unique = np.unique(np.round(values.dropna().to_numpy(dtype=float), 6))
    steps = np.diff(unique)
    steps = steps[steps > 1e-6]
    return round(float(np.median(steps)), 5) if len(steps) else None


def _cells(scores: pd.DataFrame, fuzzy: pd.DataFrame, id_col: str, variant: str) -> dict:
    layers = fuzzy.set_index(id_col)
    percentile = scores[variant].rank(pct=True)
    features = []
    for idx, rec in scores.iterrows():
        layer_row = layers.loc[rec[id_col]] if rec[id_col] in layers.index else None
        props = {"id": rec[id_col], "score": _r(rec[variant], 3), "percentile": _r(percentile[idx], 3),
                 "layers": {} if layer_row is None else {col: _r(layer_row[col], 3) for col in layers.columns}}
        features.append(_point(rec["lon"], rec["lat"], props))
    return {"type": "FeatureCollection", "cell_size_deg": _cell_size(scores["lon"]), "features": features}


def _vn_farms(ctx: Ctx) -> dict | None:
    path = ctx.data / "suitability" / "osm_features.csv"
    if not path.is_file():
        return None
    osm = ctx.read_csv(path)
    farms = osm[osm["kind"] == "aquaculture"]
    return {"type": "FeatureCollection", "features": [
        _point(rec["lon"], rec["lat"], {"name": _str(rec.get("name")), "osm_id": _str(rec.get("osm_id")),
                                        "source": "OpenStreetMap (aquaculture, centroid)"})
        for rec in farms.to_dict("records")]}


def _hk_farms(ctx: Ctx) -> dict | None:
    path = ctx.data / "foreign" / "hk_epd" / "fish_culture_zones.csv"
    if not path.is_file():
        return None
    from shapely import wkt
    from shapely.geometry import mapping

    zones = ctx.read_csv(path)
    features = []
    for rec in zones.to_dict("records"):
        geometry = mapping(wkt.loads(rec["wkt"]))
        features.append({"type": "Feature", "geometry": {"type": geometry["type"],
                                                         "coordinates": _round_coords(geometry["coordinates"])},
                         "properties": {"fcz_id": rec.get("fcz_id"), "code": _str(rec.get("code")),
                                        "name_en": _str(rec.get("name_en")), "area_sqm": _num(rec.get("area_sqm")),
                                        "source": "AFCD fish culture zones (CSDI)"}})
    return {"type": "FeatureCollection", "features": features}


def build_suitability(ctx: Ctx, region: str, variant: str) -> tuple[dict | None, str | None]:
    notes: list[str] = []
    if region == "vn":
        run = scores = None
        for name in VN_SUIT_RUNS[variant]:
            candidate = ctx.run(name, ("scores.csv", "criteria_fuzzy.csv"))
            if candidate is None:
                continue
            frame = pd.read_csv(candidate / "scores.csv")
            if variant in frame.columns:
                run, scores = candidate, frame
                ctx.track(candidate / "scores.csv")
                break
        if run is None:
            return None, "suitability_vn_run_missing"
        fuzzy = ctx.read_csv(run / "criteria_fuzzy.csv")
        cells = _cells(scores, fuzzy, "point_id", variant)
        farms = _vn_farms(ctx)
        auc = auc_ci = None
        notes.append("Không có AUC: Việt Nam chưa có ranh giới vùng nuôi chính thức có tọa độ để kiểm chứng độc lập [RL-11].")
        if (run / "validation_osm_farms.csv").is_file():
            check = ctx.read_csv(run / "validation_osm_farms.csv")
            row = check[check["variant"] == variant]
            if len(row):
                rec = row.iloc[0]
                notes.append(f"Phân vị điểm số trung bình của {int(rec['n_matched'])}/{int(rec['n_farms_marine'])} "
                             f"vùng nuôi OSM trên biển: {float(rec['mean_percentile']):.2f} ({variant}).")
        if farms is not None:
            notes.append(f"Lớp vùng nuôi: {len(farms['features'])} điểm OSM aquaculture (tâm), gồm cả điểm ngoài mặt nạ biển.")
        notes.append("ETOPO1 quá thô gần bờ; 22 vùng nuôi chỉ rơi vào ~5 ô [RL-05].")
        if variant == "N1_W_SUM":
            notes.append("Ngưỡng gần bờ đặt sau khi xem chẩn đoán RL-05 → không phải kiểm chứng độc lập [RL-06].")
        else:
            notes.append("Tiêu chí xa bờ Ghaderi (2026): vùng nuôi chỉ ở phân vị ~24 % (có trọng số) [RL-05].")
        source_run = run.name
    elif region == "hk":
        run = ctx.run(SUIT_HK_RUN, ("scores_coast.csv", "criteria_fuzzy_coast.csv"))
        if run is None:
            return None, "suitability_hk_run_missing"
        scores = ctx.read_csv(run / "scores_coast.csv")
        if variant not in scores.columns:
            return None, f"variant_missing:{variant}"
        cells = _cells(scores, ctx.read_csv(run / "criteria_fuzzy_coast.csv"), "cell_id", variant)
        farms = _hk_farms(ctx)
        auc = auc_ci = None
        if (run / "validation.csv").is_file():
            check = ctx.read_csv(run / "validation.csv")
            row = check[(check["mask"] == "coast") & (check["variant"] == variant)]
            if len(row):
                rec = row.iloc[0]
                auc, auc_ci = _r(rec["auc"], 3), [_r(rec.get("auc_lo"), 3), _r(rec.get("auc_hi"), 3)]
                zones = rec.get("n_zones_evaluable")
                notes.append(f"AUC {auc} [{auc_ci[0]}; {auc_ci[1]}] trên mặt nạ biển theo đường bờ OSM; CI bootstrap theo vùng"
                             + (f", {int(zones)} vùng nuôi có ô." if _num(zones) is not None else "."))
        notes.append("Nhãn dương: ô trong hoặc cách vùng nuôi cá AFCD ≤ 1.8 km; ngưỡng giữ nguyên, không chỉnh lại [RL-16].")
        if variant == "N1_W_SUM":
            notes.append("Phần lợi của bộ gần bờ chủ yếu do bỏ lớp độ sâu và tiêu chí che chắn; ngưỡng khoảng cách bờ không được ủng hộ [RL-16].")
        else:
            notes.append("Tiêu chí xa bờ không hợp với lồng gần bờ: xác nhận ở VN và HK [RL-16].")
        source_run = run.name
    else:
        raise ValueError(f"unknown region {region}")
    return {"variant": variant, "region": region, "source_run": source_run, "cells": cells,
            "farms": farms or {"type": "FeatureCollection", "features": []}, "farms_available": farms is not None,
            "auc": auc, "auc_ci": auc_ci, "notes": notes, "scope": "research_only"}, None


# ---------------------------------------------------------------- H4 foreign reliability
def _stations_fc(stations: list[dict]) -> dict:
    features = []
    for st in stations:
        props = {"station": st["station"], "name": st.get("name"), "habitat": st.get("habitat"),
                 "group": st.get("group"), "wet_sal_median": _r(st.get("wet_sal_median"), 2),
                 "regime_class": regime_class(st.get("wet_sal_median"))}
        features.append(_point(st["lon"], st["lat"], {k: v for k, v in props.items() if v is not None or k in
                                                      ("wet_sal_median", "regime_class")}))
    return {"type": "FeatureCollection", "regime_class_rule": REGIME_CLASS_RULE, "features": features}


def _pair_row(anchor: str, target: str, **fields) -> dict:
    regime = fields.pop("regime", None)
    return {"anchor": anchor, "target": target, **fields,
            "same_regime": None if regime not in ("same", "different") else regime == "same"}


def _first_col(frame: pd.DataFrame, *names: str) -> str | None:
    return next((name for name in names if name in frame.columns), None)


def _wet_sal_col(frame: pd.DataFrame) -> str | None:
    named = _first_col(frame, "sal_wet_median", "wet_sal_median", "sal_spring_median", "sal_median_high_flow")
    if named:
        return named
    return next((c for c in frame.columns if re.search(r"sal.*(wet|high_flow|spring).*median|wet.*sal", c, re.I)), None)


def _radius_rows(frame: pd.DataFrame, scale: str, source_run: str, group_strip: str | None = None) -> list[dict]:
    multi = "dataset" in frame.columns and frame["dataset"].nunique() > 1
    rows = []
    for rec in frame.to_dict("records"):
        radius, label = _radius_value(rec.get("radius_km"))
        row = {"var": VAR_MAP.get(rec["var"], rec["var"]), "regime": _regime(rec.get("regime")),
               "transfer": TRANSFER_MAP.get(rec["transfer"], rec["transfer"]), "scale": rec.get("scale") or scale,
               "gate": _gate_name(rec["gate"]), "radius_km": radius, "radius_label": label, "stop": _str(rec.get("stop")),
               "source_run": source_run}
        if "metric" in rec and _str(rec.get("metric")):
            row["metric"] = rec["metric"]
        if multi:
            group = str(rec["dataset"])
            row["group"] = group[len(group_strip):] if group_strip and group.startswith(group_strip) else group
        rows.append(row)
    return rows


def _generic_foreign(ctx: Ctx, cfg: dict, run: Path) -> dict:
    """NERRS multi / MD DNR / TWDB / USGS / IRLON: stations.csv + pair_reliability.csv + radius.csv (aggregates only)."""
    ids = {"station": str, "site": str, "anchor": str, "target": str, "reserve": str}
    stations_df = ctx.read_csv(run / "stations.csv", dtype=ids)
    if cfg.get("station_filter"):
        col, value = cfg["station_filter"]
        if col in stations_df.columns:
            stations_df = stations_df[stations_df[col] == value]
    id_col = _first_col(stations_df, "site", "station")
    group_col = cfg.get("group_col")
    sal_col = _wet_sal_col(stations_df)
    rel = ctx.read_csv(run / "pair_reliability.csv", dtype=ids)
    if cfg.get("max_km") is not None:
        rel = rel[rel["km"] <= cfg["max_km"]]

    def key(group, station):
        return f"{group}:{station}" if group_col else station

    wet = {}
    if sal_col is None and group_col and (run / "pairs.csv").is_file():  # NERRS: wet medians live in pairs.csv
        pairs = ctx.read_csv(run / "pairs.csv", dtype=ids)
        for side in ("anchor", "target"):
            col = f"sal_wet_{side}"
            if col in pairs.columns:
                for rec in pairs[[group_col, side, col]].dropna().to_dict("records"):
                    wet[key(rec[group_col], rec[side])] = rec[col]
    stations = []
    for rec in stations_df.to_dict("records"):
        station = key(rec.get(group_col), rec[id_col]) if group_col else rec[id_col]
        stations.append({"station": station, "lon": rec["lon"], "lat": rec["lat"],
                         "name": _str(rec.get("name") or rec.get("station_nm") or rec.get("code") or rec.get("description")),
                         "group": _str(rec.get(group_col)) if group_col else None,
                         "wet_sal_median": rec.get(sal_col) if sal_col else wet.get(station)})
    var_col = _first_col(rel, "var", "variable")
    pairs_out = []
    for rec in rel.to_dict("records"):
        anchor = key(rec.get(group_col), rec["anchor"]) if group_col else rec["anchor"]
        target = key(rec.get(group_col), rec["target"]) if group_col else rec["target"]
        pairs_out.append(_pair_row(
            anchor, target, var=VAR_MAP.get(rec[var_col], rec[var_col]),
            transfer=TRANSFER_MAP.get(rec["transfer"], rec["transfer"]), scale="hourly",
            km=_r(rec.get("km"), 3), regime=_regime(rec.get("regime")), dsal=_r(rec.get("dsal"), 2),
            share=_r(rec.get("share")), ci_low=_r(rec.get("ci_low")), n_days=_int(rec.get("n_days")),
            gate80=_gate_status(rec.get("gate80")), gate90=_gate_status(rec.get("gate90")),
            gate95=_gate_status(rec.get("gate95"))))
    radius = []
    if (run / "radius.csv").is_file():
        radius += _radius_rows(ctx.read_csv(run / "radius.csv"), "hourly", run.name, group_strip="nerrs_")
    if (run / "daily_radius.csv").is_file():  # IRLON daily-mean protocol
        radius += _radius_rows(ctx.read_csv(run / "daily_radius.csv"), "daily_mean", run.name)
    return {"stations": stations, "pairs": pairs_out, "radius": radius}


def _jobos(ctx: Ctx, cfg: dict, run: Path) -> dict:
    ids = {"station": str, "anchor": str, "target": str}
    stations_df = ctx.read_csv(run / "stations.csv", dtype=ids)
    stations = [{"station": rec["station"], "lon": rec["lon"], "lat": rec["lat"], "habitat": _str(rec.get("habitat")),
                 "wet_sal_median": None} for rec in stations_df.to_dict("records")]
    rel = ctx.read_csv(run / "pairs.csv", dtype=ids)
    pairs = [_pair_row(rec["anchor"], rec["target"], var=VAR_MAP.get(rec["variable"], rec["variable"]),
                       transfer=TRANSFER_MAP.get(rec["method"], rec["method"]), scale="hourly",
                       km=_r(rec.get("distance_km"), 3), regime=None, dsal=None,
                       same_habitat=str(rec.get("pair_type")) == "same_habitat",
                       share=_r(rec.get("share_within")), ci_low=_r(rec.get("share_ci_lo")), n_days=_int(rec.get("n_days")),
                       gate80=_gate_status(rec.get("gate_80")), gate90=_gate_status(rec.get("gate_90")),
                       gate95=_gate_status(rec.get("gate_95")))
             for rec in rel.to_dict("records")]
    return {"stations": stations, "pairs": pairs, "radius": [],
            "notes": ["Jobos: 4 trạm, phân loại theo môi trường sống (không có độ mặn mùa ướt theo trạm); same_regime = null."]}


HK_MAX_KM = 10.0


def _hk(ctx: Ctx, cfg: dict, run: Path) -> dict:
    stations_df = ctx.read_csv(run / "stations.csv", dtype={"station": str})
    wet, regime_pairs = {}, {}
    if (run / "matched_samples.csv.gz").is_file():
        cols = ["target", "target_date", "t_Sal", "anchor", "wet_sal_median_diff", "regime_relation", "season"]
        samples = ctx.read_csv(run / "matched_samples.csv.gz", usecols=lambda c: c in cols, dtype={"target": str, "anchor": str})
        wet_rows = samples[samples["season"] == "wet"].drop_duplicates(["target", "target_date"])
        wet = wet_rows.groupby("target")["t_Sal"].median().to_dict()
        for rec in samples.drop_duplicates(["anchor", "target"]).to_dict("records"):
            regime_pairs[(rec["anchor"], rec["target"])] = (_regime(rec["regime_relation"]), rec["wet_sal_median_diff"])
    stations = [{"station": rec["station"], "lon": rec["lon"], "lat": rec["lat"],
                 "name": _str(rec.get("water_control_zone")), "wet_sal_median": wet.get(rec["station"])}
                for rec in stations_df.to_dict("records")]
    rel = ctx.read_csv(run / "pairs.csv", dtype={"anchor": str, "target": str})
    rel = rel[rel["distance_km"] <= HK_MAX_KM]
    pairs = []
    for rec in rel.to_dict("records"):
        regime, dsal = regime_pairs.get((rec["anchor"], rec["target"]), (None, None))
        pairs.append(_pair_row(rec["anchor"], rec["target"], var=VAR_MAP.get(rec["variable"], rec["variable"]),
                               transfer=TRANSFER_MAP.get(rec["method"], rec["method"]), scale="monthly",
                               km=_r(rec.get("distance_km"), 3), regime=regime, dsal=_r(dsal, 2),
                               share=_r(rec.get("share_within")), ci_low=None, n_days=_int(rec.get("n_lag0")),
                               gate80=None, gate90=None, gate95=None))
    radius = []
    if (run / "reliability_radius.csv").is_file():
        rad = ctx.read_csv(run / "reliability_radius.csv")
        rad = rad[(rad["lag_scope"] == "lag0") & (rad["season"] == "all") & (rad["split"] == "salinity_regime")]
        rad = rad.rename(columns={"variable": "var", "method": "transfer", "relation": "regime", "radius": "radius_km"})
        radius = _radius_rows(rad, "monthly", run.name)
    return {"stations": stations, "pairs": pairs, "radius": radius,
            "notes": [f"HK: chia sẻ theo cặp (share_within) trên mọi lần ghép ±3 ngày, không có CI/gate theo cặp; "
                      f"gate và bán kính tính theo ô khoảng cách (lag 0). Chỉ xuất cặp ≤ {HK_MAX_KM:g} km.",
                      "Độ mặn mùa ướt (4–9) theo trạm: trung vị các mẫu nước mặt đã ghép cặp."]}


# manifest.json is written last by every experiment script: its presence marks a finished run.
ADAPTERS = {"generic": (_generic_foreign, ("stations.csv", "pair_reliability.csv", "manifest.json")),
            "jobos": (_jobos, ("stations.csv", "pairs.csv", "manifest.json")),
            "hk": (_hk, ("stations.csv", "pairs.csv", "manifest.json"))}
# Pairs are stored as a table (columns + rows) to keep files small; the backend joins station
# coordinates (lon1/lat1/lon2/lat2) and expands rows to the API objects.
PAIR_COLUMNS = ("anchor", "target", "var", "transfer", "scale", "km", "same_regime", "dsal", "share", "ci_low",
                "n_days", "gate80", "gate90", "gate95", "same_habitat")


def _multiscale_radius(ctx: Ctx) -> dict[str, list[dict]]:
    run = ctx.run(MULTISCALE_RUN, ("radius.csv", "manifest.json"))
    if run is None:
        return {}
    frame = pd.read_csv(run / "radius.csv")
    needed = {"dataset", "var", "regime", "scale", "transfer", "gate", "radius_km"}
    if not needed <= set(frame.columns):
        ctx.skipped[MULTISCALE_RUN] = "unrecognized_schema:radius.csv"
        return {}
    ctx.track(run / "radius.csv")
    out: dict[str, list[dict]] = {}
    for dataset, grp in frame.groupby("dataset"):
        target = MULTISCALE_DATASETS.get(str(dataset))
        if target is None:
            continue
        rows = _radius_rows(grp.drop(columns="dataset"), "hourly", MULTISCALE_RUN)
        if target == "nerrs_multi":
            for row in rows:
                row["group"] = "pooled"
        out.setdefault(target, []).extend(rows)
    return out


def _radius_summary(radius: list[dict], scale: str) -> str | None:
    picks = {}
    for row in radius:
        if (row["scale"] == scale and row["gate"] == "gate80" and row["transfer"] == "raw" and row["regime"] == "same"
                and row.get("group") in (None, "pooled") and row.get("metric") in (None, "value")
                and row["source_run"] != MULTISCALE_RUN):
            label, km = row["radius_label"], row["radius_km"]
            picks[row["var"]] = label if (km is None or (label or "").startswith(">")) else f"{km:g} km"
    if not picks:
        return None
    text = ", ".join(f"{var} {value or 'không xác định'}" for var, value in sorted(picks.items()))
    return f"Từ artifact — bán kính 80 % (thô, cùng chế độ, {scale}): {text}."


def _bbox(stations: list[dict]) -> list[float] | None:
    lons = [_num(s["lon"]) for s in stations if _num(s["lon"]) is not None]
    lats = [_num(s["lat"]) for s in stations if _num(s["lat"]) is not None]
    if not lons:
        return None
    return [round(min(lons), 4), round(min(lats), 4), round(max(lons), 4), round(max(lats), 4)]


def _ordered(values) -> list[str]:
    values = {v for v in values if v}
    return sorted(values, key=lambda v: (SCALE_ORDER.index(v) if v in SCALE_ORDER else len(SCALE_ORDER), v))


def build_foreign(ctx: Ctx, dataset_id: str, multiscale: dict[str, list[dict]]) -> tuple[dict | None, str | None]:
    cfg = FOREIGN[dataset_id]
    adapter, required = ADAPTERS[cfg["adapter"]]
    run = ctx.run(cfg["run"], required)
    if run is None:
        return None, ctx.skipped.get(cfg["run"], "run_missing")
    part = adapter(ctx, cfg, run)
    radius = part["radius"] + multiscale.get(dataset_id, [])
    pairs = part["pairs"]
    scales = _ordered([p["scale"] for p in pairs] + [r["scale"] for r in radius])
    native = pairs[0]["scale"] if pairs else (scales[0] if scales else None)
    findings = list(cfg["findings"])
    if native and (summary := _radius_summary(radius, native)):
        findings.append(summary)
    if any(r["source_run"] == MULTISCALE_RUN for r in radius):
        findings.append("Có bán kính đa thang thời gian (ngày/tuần, giá trị và lớp ngưỡng) từ H4.6 (h4-multiscale).")
    detail = {
        "id": dataset_id, "name": cfg["name"], "region": cfg["region"], "country": cfg["country"],
        "cadence": cfg["cadence"], "period": cfg["period"], "climate": cfg["climate"], "licence": cfg["licence"],
        "credit": cfg["credit"], "redistributable": cfg["redistributable"], "research_log": cfg["rl"],
        "headline": cfg["headline"], "source_run": run.name,
        "stations": _stations_fc(part["stations"]),
        "pairs": {"columns": list(PAIR_COLUMNS), "rows": [[p.get(c) for c in PAIR_COLUMNS] for p in pairs]},
        "radius": radius, "findings": findings,
        "notes": part.get("notes", []),
        "available": {"vars": sorted({p["var"] for p in pairs} | {r["var"] for r in radius}) if not pairs
                      else sorted({p["var"] for p in pairs}),
                      "scales": scales, "transfers": sorted({p["transfer"] for p in pairs} | {r["transfer"] for r in radius})},
    }
    card = {key: detail[key] for key in ("id", "name", "region", "country", "cadence", "period", "climate", "licence",
                                          "credit", "redistributable", "headline", "research_log", "source_run")}
    card |= {"n_stations": len(part["stations"]), "n_pairs": len({(p["anchor"], p["target"]) for p in pairs}),
             "bbox": _bbox(part["stations"]), "scales": scales}
    return {"detail": detail, "card": card}, None


# ---------------------------------------------------------------- H4 VN salinity regime (A6)
VN_LAYER_PROPS = ("regime_class", "regime_basis", "nearest_obs_station", "nearest_obs_km", "nearest_obs_wet_median_sal",
                  "idw_obs_wet_median_sal", "idw_obs_regime_class")
VN_STATION_PROPS = ("region", "station", "salinity_source", "wet_median_sal", "dry_median_sal", "regime_class",
                    "coordinate_suspect")


def _slim(collection: dict, keep: tuple[str, ...], drop_unassigned: bool = False) -> tuple[dict, int]:
    """Whitelisted properties only; optionally drop cells with no regime (count returned)."""
    features, dropped = [], 0
    for feature in collection.get("features", []):
        props = feature.get("properties") or {}
        if drop_unassigned and props.get("regime_class") in ("unassigned", "unknown", None):
            dropped += 1
            continue
        features.append({**feature, "properties": {k: props[k] for k in keep if k in props}})
    return _round_geojson({"type": "FeatureCollection", "features": features}), dropped


def build_reliability_vn(ctx: Ctx) -> tuple[dict | None, str | None]:
    run = ctx.run(VN_REGIME_RUN, ("station_regime.geojson", "manifest.json"))
    if run is None:
        return None, "a6_not_exported"
    stations, _ = _slim(ctx.read_json(run / "station_regime.geojson"), VN_STATION_PROPS)
    raw_layer = ctx.read_json(run / "regime_layer.geojson") if (run / "regime_layer.geojson").is_file() else None
    nb1 = ctx.read_json(run / "nb1_regime.json") if (run / "nb1_regime.json").is_file() else None
    counts = ctx.read_csv(run / "pass_counts.csv").to_dict("records") if (run / "pass_counts.csv").is_file() else []
    notes = ["Nghiên cứu (research_only): không dùng cho cảnh báo hay shadow runner.",
             "HP: độ mặn là giá trị mô hình dạng lưới; lớp chế độ dựa trên trạm QN quan sát (A6)."]
    layer = None
    if raw_layer:
        meta = raw_layer.get("metadata") or {}
        layer, dropped = _slim(raw_layer, VN_LAYER_PROPS, drop_unassigned=True)
        layer["grid_step_m"] = meta.get("grid_step_m")
        layer["n_unassigned_omitted"] = dropped
        notes.append(f"Lớp chế độ: {len(layer['features'])} ô lưới có trạm quan sát trong "
                     f"{meta.get('assign_max_km', '?')} km; {dropped} ô không có trạm nào được bỏ qua (không gán chế độ).")
        if meta.get("caveat"):
            notes.append(meta["caveat"])
    return {"source_run": run.name, "stations": stations, "layer": layer, "nb1_regime": nb1,
            "pass_counts": [{k: clean(v) for k, v in rec.items()} for rec in counts], "notes": notes}, None


# ---------------------------------------------------------------- overview (H1-H4)
OVERVIEW_RL = {
    "H1": ["RL-03", "RL-08", "RL-09", "RL-13", "RL-15", "RL-17", "RL-18", "RL-19"],
    "H2": ["RL-08", "RL-13", "RL-15"],
    "H3": ["RL-05", "RL-06", "RL-11", "RL-16"],
    "H4": ["RL-12", "RL-14", "RL-20", "RL-21", "RL-22", "RL-23", "RL-24"],
}


def _rl_titles(ctx: Ctx) -> dict[str, str]:
    log = ctx.research_log
    if not log or not log.is_file():
        return {}
    ctx.track(log)
    titles = {}
    for line in log.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^## (RL-\d+) · [\d-]+ · (.+)$", line.strip())
        if match:
            titles[match.group(1)] = f"{match.group(1)} · {match.group(2)}"
    return titles


def build_overview(ctx: Ctx, bench: dict | None, suitability: dict[str, dict], foreign_cards: list[dict]) -> dict:
    titles = _rl_titles(ctx)
    h1 = ["Bundle pH dài hạn đã rút khỏi shadow: B4/B6 không đạt gate ở 3–12 h trên dữ liệu sạch [RL-18].",
          "aci_amp đạt độ phủ PI80 18/18, PI90 18/18 nhưng gần in-sample; mặc định chưa đổi [RL-19]."]
    h1_head = "Nhiệt độ nước dự báo được tới 12 h (đạt kiểm định gate #16); pH dài hạn không đạt trên dữ liệu sạch."
    if bench:
        b5 = sorted((r["horizon_min"], r["skill"]) for r in bench["temperature"]
                    if r["source"] == "A1" and r["feature_set"] == "B5_external_as_issued")
        if b5:
            h1.insert(0, "Skill B5 so với persistence (A1, có pH): "
                      + " / ".join(f"{h} phút {s:g} %" for h, s in b5 if s is not None) + " — từ artifact.")
        passes = [r for r in bench["temperature"] if r["source"] == "A1"]
        if passes:
            h1.insert(1, f"A1: {sum(r['gate'] == 'pass' for r in passes)}/{len(passes)} cấu hình nhiệt độ (có/không pH) đạt gate #16 — từ artifact.")
        ph = [r for r in bench["ph_clean"] if r["horizon_min"] >= 180]
        if ph:
            h1.insert(2, f"A3 pH sạch, 3–12 h: {sum(r['gate'] == 'pass' for r in ph)}/{len(ph)} cấu hình đạt gate — từ artifact.")
    h2 = ["Bản tin dựng lại (reconstructed_run), chưa phải captured_live; một trạm, lockbox 14 ngày [RL-08]."]
    addon = ctx.exp / H12_ADDON_RUN / "addon_vs_B4_dm.csv"
    if addon.is_file():
        frame = ctx.read_csv(addon)
        sel = frame[(frame["target"] == "Temperature") & (frame["addon"] == "B5_external_as_issued")
                    & (frame["model"] == "ridge") & frame["horizon_minutes"].isin([180, 360, 720])]
        if len(sel):
            h2.insert(0, "Thời tiết (B5) giảm MAE nhiệt độ so với B4: " + ", ".join(
                f"{int(r['horizon_minutes']) // 60} h {r['gain_pct']:+.1f} % (DM p={_sig(r['p_value'], 2)})"
                for r in sel.sort_values("horizon_minutes").to_dict("records")) + " — từ artifact.")
    h3 = ["Tiêu chí xa bờ (Ghaderi) không hợp lồng gần bờ trong vịnh: xác nhận ở VN và HK [RL-05, RL-16].",
          "VN chưa có ranh giới vùng nuôi chính thức có tọa độ → chưa kiểm chứng độc lập [RL-11]."]
    aucs = {v: suitability.get(f"hk_{v}", {}).get("auc") for v in SUIT_VARIANTS}
    if all(aucs.values()):
        h3.insert(0, f"Hong Kong (28 vùng nuôi AFCD): AUC Ghaderi {aucs['A_W_SUM']} so với gần bờ {aucs['N1_W_SUM']} — từ artifact.")
    h4 = ["Với độ mặn (và phần lớn pH), chế độ mặn quyết định chứ không phải khoảng cách [RL-24].",
          "Khác môi trường sống làm hỏng cặp ngay ở 1–2 km; DO và độ đục không chuyển được ở đâu [RL-24].",
          "Bán kính 5 km của HK chỉ đúng với mẫu tháng; ở thang giờ gần như không chuyển được giá trị [RL-24]."]
    if foreign_cards:
        h4.insert(0, f"{len(foreign_cards)} bộ dữ liệu nước ngoài đã xuất: "
                  + ", ".join(f"{c['name']} ({c['n_stations']} trạm)" for c in foreign_cards) + ".")
    directions = [
        {"id": "H1", "title": "Dự báo cảm biến (H1)", "stage": "shadow — nhiệt độ 3–12 h",
         "headline": h1_head, "findings": h1,
         "limitations": ["Một trạm, lockbox 14 ngày; thời tiết dựng lại [RL-18].",
                         "Đầu dò pH trôi từ 19/09; dữ liệu pH sau đó không đáng tin [RL-13]."],
         "next": ["Tích lũy ≥ 4 tuần sổ ghi shadow rồi so độ phủ khoảng tin cậy [RL-15].",
                  "Nối aci_amp vào bundle + ledger [RL-19]."]},
        {"id": "H2", "title": "Khuyến cáo theo thời tiết (H2)", "stage": "nghiên cứu — thu bản tin thời tiết mỗi giờ",
         "headline": "Thời tiết giúp dự báo nhiệt độ nước 3–12 h (sơ bộ); chưa giúp NH4/TSS. Thời tiết chỉ để quan sát, không kích hoạt cảnh báo.",
         "findings": h2,
         "limitations": ["Độ phủ bản tin tự thu thấp trước 15/10 (~29 % số giờ từ 26/09) [RL-15]."],
         "next": ["Lặp lại B5 khi đủ bản tin captured_live (H2.2) [RL-08]."]},
        {"id": "H3", "title": "Phân vùng phù hợp (H3)", "stage": "nghiên cứu — bản nháp",
         "headline": "Bộ tiêu chí gần bờ xếp vùng nuôi cao hơn tiêu chí xa bờ, nhưng xếp hạng rất nhạy với lựa chọn tiêu chí.",
         "findings": h3,
         "limitations": ["Sóng/gió/độ sâu quá thô để thấy độ che chắn trong vịnh [RL-16].",
                         "Ngưỡng gần bờ đặt sau khi xem chẩn đoán VN [RL-06]."],
         "next": ["Độ sâu gần bờ chi tiết (GEBCO/hải đồ); chỉ số che chắn < 1 km [RL-16]."]},
        {"id": "H4", "title": "Độ tin cậy không gian (H4)", "stage": "nghiên cứu — kiểm chứng trên dữ liệu nước ngoài",
         "headline": "Vùng được phép chuyển giá trị = cùng chế độ mặn + cùng loại môi trường sống; không hứa giá trị theo giờ tại điểm khác.",
         "findings": h4,
         "limitations": ["Chỉ chuyển phương pháp, không chuyển con số bán kính sang VN [RL-14].",
                         "Hiệu chỉnh cải thiện một phần là ảo (đích ít biến động) → cần baseline khí hậu [RL-24]."],
         "next": ["Giao thức ở thang ngày và theo lớp ngưỡng, kèm baseline khí hậu; A6 lớp chế độ mặn HP/QN [RL-24].",
                  "Sensor đối chứng thứ hai cùng chế độ mặn với NB1 (H4.4 VN) [RL-14]."]},
    ]
    for direction in directions:
        direction["research_log"] = [titles.get(rl, rl) for rl in OVERVIEW_RL[direction["id"]]]
    return {"directions": directions}


# ---------------------------------------------------------------- H2 hazards (theory track, not field-validated)
STORM_RUN = "storm-hindcast-20261023e"
STORM_LEAD_RUN = "storm-leadtime-20261023d"
HEAT_RUN = "heat-hindcast-20261023b"
HEAT_SKILL_RUN = "heat-skill-20261023b"
DISEASE_RUN = "disease-hindcast-20261023b"
STOCKING_RUN = "stocking-calendar-20261023c"
HAZARD_BASIS = "theory_only_unvalidated"
# Primary truth = the independent one (ERA5); ifs_shortrange is circular for lead 0.
STORM_LEAD_PAIR = "ecmwf_ifs025_vs_era5"
STORM_LEAD_LEVEL_BF = 6
# Rows of heat-skill metrics.csv quoted in docs/eval/2026-10-23-heat-skill.md (LOMO, hot day >= 31 °C).
HEAT_SKILL_ROWS = (
    ("oisst", "same-day hindcast", "raw", "OISST thô"),
    ("air", "same-day hindcast", "offset", "Chỉ nhiệt độ không khí (ERA5 + độ lệch)"),
    ("marine", "same-day hindcast", "lin_air", "SST marine + không khí"),
    ("sensor_lag1", "lead 1 (persistence)", "persistence", "Cảm biến hôm qua (persistence)"),
)
STOCKING_CLASSES = ("good", "caution", "avoid", "avoid_cold")


def _storm(ctx: Ctx) -> tuple[dict | None, str | None]:
    run = ctx.run(STORM_RUN, ("manifest.json", "climatology_month.csv"))
    if run is None:
        return None, ctx.skipped.get(STORM_RUN)
    manifest = ctx.read_json(run / "manifest.json")
    month = ctx.read_csv(run / "climatology_month.csv")
    out = {
        "source_run": STORM_RUN, "basis": HAZARD_BASIS, "source": manifest.get("source"),
        "seasons": manifest.get("seasons"), "passages": _int(manifest.get("passages")),
        "radius_km": _num((manifest.get("params") or {}).get("radius_km")),
        "per_month_cap8": [{"month": _int(row.month), "per_year": _r(row.storms_per_year_site_cap8_plus, 4)}
                           for row in month.itertuples()],
    }
    if (run / "yagi_check.json").is_file():
        yagi = ctx.read_json(run / "yagi_check.json")
        out["yagi"] = {"peak_time": yagi.get("peak_time"), "min_dist_km": _r(yagi.get("min_dist_km"), 1),
                       "site_beaufort": _int(yagi.get("site_beaufort_093")),
                       "site_wind_lower_bound": bool(yagi.get("site_wind_lower_bound")),
                       "era5_max_wind_ms": _r(yagi.get("era5_max_wind_ms"), 2),
                       "era5_max_wind_beaufort": _int(yagi.get("era5_max_wind_beaufort")),
                       "note": yagi.get("note")}
    return out, None


def _storm_lead(ctx: Ctx) -> tuple[dict | None, str | None]:
    pair = STORM_LEAD_PAIR
    run = ctx.run(STORM_LEAD_RUN, ("manifest.json", f"day_contingency_{pair}.csv", f"events_{pair}.csv"))
    if run is None:
        return None, ctx.skipped.get(STORM_LEAD_RUN)
    manifest = ctx.read_json(run / "manifest.json")
    table = ctx.read_csv(run / f"day_contingency_{pair}.csv")
    events = ctx.read_csv(run / f"events_{pair}.csv")
    level = table[table["level"] == STORM_LEAD_LEVEL_BF].sort_values("lead_day")
    if level.empty:
        return None, f"no_bf{STORM_LEAD_LEVEL_BF}_rows"
    by_lead = [{"lead_day": _int(row.lead_day), "pod": _r(row.POD, 3), "far": _r(row.FAR, 3), "csi": _r(row.CSI, 3),
                "hits": _int(row.hits), "misses": _int(row.misses), "false_alarms": _int(row.false_alarms),
                "n_event_days": _int(row.hits + row.misses), "n_days": _int(row.n)} for row in level.itertuples()]
    ev = events[(events["threshold_bf"] == STORM_LEAD_LEVEL_BF) & events["is_event_truth"].astype(bool)]
    storms = [{"name": _str(row.NAME), "peak_time": _str(row.peak_time), "min_dist_km": _r(row.min_dist_km, 0),
               "consistent_lead_days": _int(row.consistent_N_truth),
               "consistent_lead_hours": _r(row.consistent_lead_hours_truth, 1)} for row in ev.itertuples()]
    pair_meta = (manifest.get("pairs") or {}).get(pair) or {}
    return {"source_run": STORM_LEAD_RUN, "basis": HAZARD_BASIS, "model": pair_meta.get("forecast_model"),
            "truth": pair_meta.get("truth_label"), "truth_independent": pair_meta.get("truth_independent"),
            "level_bf": STORM_LEAD_LEVEL_BF, "period": manifest.get("period", {}).get("start", "")[:10] + "/"
            + manifest.get("period", {}).get("end", "")[:10],
            "day_basis": (manifest.get("params") or {}).get("day_basis"),
            "lead_rule": (manifest.get("params") or {}).get("warning_lead"),
            "by_lead": by_lead, "storms": storms}, None


def _heat(ctx: Ctx) -> tuple[dict | None, str | None]:
    run = ctx.run(HEAT_RUN, ("manifest.json", "trend.json"))
    if run is None:
        return None, ctx.skipped.get(HEAT_RUN)
    manifest = ctx.read_json(run / "manifest.json")
    trends = {row.get("column"): row for row in ctx.read_json(run / "trend.json")}

    def trend(column):
        row = trends.get(column)
        if not row:
            return None
        return {"column": column, "value": _r(row.get("days_per_decade"), 2),
                "ci95": [_r(v, 2) for v in row.get("ci95_per_decade") or []], "years": row.get("years")}

    thr = manifest.get("thresholds_c") or {}
    out = {"source_run": HEAT_RUN, "basis": HAZARD_BASIS,
           "thresholds_c": {k: _num(thr.get(k)) for k in ("watch", "stress", "severe", "min_run_days")},
           "oisst_offset_c": _r(manifest.get("oisst_offset_c"), 3), "offset_note": manifest.get("offset_note"),
           # Primary = unadjusted OISST (the offset is a single-season sensitivity case, not a calibration).
           "trend_days_per_decade": trend("days_alert_ge1"),
           "trend_days_per_decade_adjusted": trend("days_alert_ge1_adjusted")}
    # heat_calendar.csv (stress >= 33 °C) is all zero; the watch file carries the signal. Its column is
    # named share_years_with_stress_day in the run, but it counts watch (>= watch threshold) days.
    for name, key in (("heat_calendar_watch.csv", "peak_weeks_watch"), ("heat_calendar.csv", "peak_weeks_stress")):
        if (run / name).is_file():
            frame = ctx.read_csv(run / name)
            out[key] = [{"iso_week": _int(row.iso_week), "share_years": _r(row.share_years_with_stress_day, 3)}
                        for row in frame.itertuples() if (_num(row.share_years_with_stress_day) or 0) > 0]
    return out, None


def _heat_skill(ctx: Ctx) -> tuple[dict | None, str | None]:
    run = ctx.run(HEAT_SKILL_RUN, ("manifest.json", "metrics.csv"))
    if run is None:
        return None, ctx.skipped.get(HEAT_SKILL_RUN)
    manifest = ctx.read_json(run / "manifest.json")
    metrics = ctx.read_csv(run / "metrics.csv")
    lomo = metrics[(metrics["scheme"] == "lomo") & (metrics["target"] == "ge31")]
    rows = []
    for product, horizon, method, label in HEAT_SKILL_ROWS:
        hit = lomo[(lomo["product"] == product) & (lomo["horizon"] == horizon) & (lomo["method"] == method)]
        if hit.empty:
            continue
        row = hit.iloc[0]
        rows.append({"product": product, "method": method, "horizon": horizon, "label": label,
                     "csi": _r(row["CSI"], 3), "pod": _r(row["POD"], 3), "far": _r(row["FAR"], 3),
                     "n_pos": _int(row["n_pos"]), "n": _int(row["n"]), "mae_c": _r(row["MAE_c"], 3)})
    if not rows:
        return None, "no_lomo_ge31_rows"
    return {"source_run": HEAT_SKILL_RUN, "basis": HAZARD_BASIS, "scheme": "lomo", "target": "sensor daily mean >= 31 °C",
            "sensor_period": [manifest.get("sensor_first"), manifest.get("sensor_last")],
            "sensor_days": _int(manifest.get("sensor_days")), "hot_days": _int(manifest.get("sensor_days_ge31")),
            "rows": rows}, None


def _disease(ctx: Ctx) -> tuple[dict | None, str | None]:
    run = ctx.run(DISEASE_RUN, ("manifest.json", "results.json"))
    if run is None:
        return None, ctx.skipped.get(DISEASE_RUN)
    manifest = ctx.read_json(run / "manifest.json")
    results = ctx.read_json(run / "results.json")
    ev = results.get("evaluation") or {}
    return {"source_run": DISEASE_RUN, "basis": manifest.get("basis", HAZARD_BASIS), "note_vi": manifest.get("note_vi"),
            "used_by_alerts": manifest.get("used_by_alerts"), "years": results.get("years"),
            "verdict": ev.get("verdict"), "verdict_pathogen_attributed": ev.get("verdict_pathogen_attributed"),
            "n_events_scored": _int(ev.get("n_scored")), "hits_level2": _int(ev.get("hits_any_level2")),
            "expected_level2": _r(ev.get("mean_clim_p_any_level2"), 3),
            "n_pathogen_attributed": _int(ev.get("n_pathogen_attributed")),
            "robust_to_shift_1c": ev.get("robust_to_shift_1c"),
            "mean_days_high_per_year": _r(results.get("mean_days_level2"), 1),
            "mean_days_cold_high_oisst": _r(results.get("mean_days_cold_high_oisst"), 2),
            "mean_days_cold_high_era5_air": _r(results.get("mean_days_cold_high_era5_air"), 2)}, None


def _stocking(ctx: Ctx) -> tuple[dict | None, str | None]:
    run = ctx.run(STOCKING_RUN, ("manifest.json", "month_classes.csv"))
    if run is None:
        return None, ctx.skipped.get(STOCKING_RUN)
    manifest = ctx.read_json(run / "manifest.json")
    months = ctx.read_csv(run / "month_classes.csv")
    calendars = []
    for weeks in manifest.get("growout_weeks") or (26, 39):
        cls, score = f"class_{weeks}w", f"score_{weeks}w"
        if cls not in months.columns:
            continue
        calendars.append({"growout_weeks": int(weeks), "months": [
            {"month": _int(row["month"]), "class": _str(row[cls]) if _str(row[cls]) in STOCKING_CLASSES else None,
             "score": _r(row.get(score), 3), "feasible_frac": _r(row.get(f"feasible_frac_{weeks}w"), 2)}
            for _, row in months.iterrows()]})
    if not calendars:
        return None, "no_month_classes"
    top3 = {}
    if (run / "sensitivity_top3.csv").is_file():
        sens = ctx.read_csv(run / "sensitivity_top3.csv")
        for row in sens[sens["case"] == "base"].itertuples():
            top3[str(int(row.growout_weeks))] = json.loads(row.top3)
    gate = manifest.get("gate") or {}
    return {"source_run": STOCKING_RUN, "basis": HAZARD_BASIS,
            "validated_against_ground_truth": manifest.get("validated_against_ground_truth"),
            "years": manifest.get("years_all"), "class_cuts": manifest.get("class_cuts"),
            "gate": {"early_weeks": manifest.get("early_weeks"), "early_mean_sst_min_c": gate.get("early_mean_sst_min_c"),
                     "min_share_of_years": gate.get("min_share_of_years")},
            "best_weeks_base": top3, "calendars": calendars}, None


def build_hazards(ctx: Ctx) -> tuple[dict | None, str | None]:
    """Storm / heat / disease / stocking theory-track summaries; each section independent."""
    sections, omitted = {}, {}
    for key, builder in (("storm", _storm), ("storm_lead", _storm_lead), ("heat", _heat),
                         ("heat_skill", _heat_skill), ("disease", _disease), ("stocking", _stocking)):
        payload, reason = builder(ctx)
        if payload is None:
            omitted[key] = reason or "input_missing"
        else:
            sections[key] = payload
    if not sections:
        return None, "no_hazard_runs"
    return {"basis": HAZARD_BASIS, "used_by_alerts": False, **sections, "sections_omitted": omitted}, None


# ---------------------------------------------------------------- export
def _dump(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(clean(payload), ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                    encoding="utf-8")


def default_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M")


def export(experiments_dir: Path, out_root: Path, *, data_dir: Path, research_log: Path | None,
           stamp: str | None = None) -> Path:
    stamp = stamp or default_stamp()
    if not STAMP_RE.match(stamp):
        raise ValueError(f"stamp must look like YYYYMMDD-HHMM, got {stamp!r}")
    out_root = Path(out_root)
    final = out_root / stamp
    if final.exists():
        raise FileExistsError(f"export dir exists, not overwritten: {final}")
    ctx = Ctx(experiments_dir, data_dir, research_log)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    outputs: dict[str, dict] = {}
    omitted: dict[str, str] = {}

    def put(name: str, payload: dict | None, reason: str | None) -> None:
        if payload is None:
            omitted[name] = reason or "input_missing"
        else:
            outputs[name] = {"status": "ready", "export_version": stamp, **payload}

    bench, reason = build_forecast_benchmark(ctx)
    put("forecast_benchmark.json", bench, reason)
    suitability = {}
    for region in SUIT_REGIONS:
        for variant in SUIT_VARIANTS:
            payload, reason = build_suitability(ctx, region, variant)
            put(f"suitability_{region}_{variant}.json", payload, reason)
            if payload:
                suitability[f"{region}_{variant}"] = payload
    multiscale = _multiscale_radius(ctx)
    cards = []
    for dataset_id in FOREIGN:
        result, reason = build_foreign(ctx, dataset_id, multiscale)
        put(f"reliability_foreign_{dataset_id}.json", result and result["detail"], reason)
        if result:
            cards.append(result["card"])
    put("reliability_foreign_index.json", {"datasets": cards} if cards else None, "no_foreign_runs")
    vn, reason = build_reliability_vn(ctx)
    put("reliability_vn.json", vn, reason)
    hazards, reason = build_hazards(ctx)
    put("hazards.json", hazards, reason)
    put("overview.json", {"generated_at": generated_at, **build_overview(ctx, bench, suitability, cards)}, None)

    out_root.mkdir(parents=True, exist_ok=True)
    tmp = out_root / f".{stamp}.tmp-{uuid.uuid4().hex[:8]}"
    tmp.mkdir()
    files = {}
    for name, payload in outputs.items():
        _dump(tmp / name, payload)
        files[name] = {"bytes": (tmp / name).stat().st_size, "sha256": sha256(tmp / name)}
    manifest = {"schema_version": SCHEMA_VERSION, "export_version": stamp, "generated_at": generated_at,
                "script": "scripts/export_research_map_artifacts.py", "files": files,
                "sources": [{"path": p, "sha256": h} for p, h in sorted(ctx.sources.items())],
                "omitted": omitted, "inputs_skipped": ctx.skipped,
                "policy": {"mddnr": "aggregated pair/radius statistics and station coordinates only (no raw data)",
                           "write_once": True, "scope": "research_only"}}
    _dump(tmp / "manifest.json", manifest)
    os.rename(tmp, final)  # fails if `final` appeared meanwhile: never overwrite
    return final


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stamp", default=None, help="export dir name YYYYMMDD-HHMM (default: now, local time)")
    parser.add_argument("--out-root", type=Path, default=paths.RESEARCH_MAP_EXPORT_DIR)
    parser.add_argument("--experiments-dir", type=Path, default=paths.EXPERIMENT_OUTPUT_DIR)
    parser.add_argument("--research-log", type=Path, default=paths.PROJECT_ROOT / "docs" / "research-log.md")
    args = parser.parse_args(argv)
    out = export(args.experiments_dir, args.out_root, data_dir=paths.DATA_DIR, research_log=args.research_log,
                 stamp=args.stamp)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    print(f"export: {out}")
    for name, meta in sorted(manifest["files"].items()):
        print(f"  {name:45s} {meta['bytes'] / 1024:8.1f} KB")
    for name, reason in sorted(manifest["omitted"].items()):
        print(f"  omitted {name}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
