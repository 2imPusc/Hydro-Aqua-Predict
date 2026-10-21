# Storm + heat-stress advisory (theory + public data) — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** give the Cát Bà cage site (sensor `06M26042804`, anchor NB1) two theory-based hazard indicators that need **no new sensors or water sampling**: (A) tropical-cyclone exposure / risk level and (B) cobia heat-stress level, each with a hindcast on public data.

**Architecture:** two independent parts. Each part = one pure `core/` module (rules from cited literature/regulation, network-free, unit-tested) + one `experiments/` hindcast script that downloads public data write-once into `data/hazards/` and writes a run dir under `artifacts/experiments/`. Part A can ship without Part B. Nothing drives alerts or notifications: every output carries `used_by_alerts: False`, `notification_eligible: False`, `basis: "theory_only_unvalidated"` and a `source` tag.

**Tech stack:** Python 3.11 root `.venv`, pandas/numpy/scipy/requests (already in `requirements.txt`), pytest. No new dependencies.

**Owner decision (2026-10-22):** sensors and water sampling are hard to extend, so research proceeds on theory + public data first. Record as decisions #17 (Task 11).

---

## Data paths: what may drive what

| Path | Data | Allowed use | `source` tag |
| --- | --- | --- | --- |
| Operational (as-issued) | Open-Meteo forecast `wind_speed_10m` (+ `wind_gusts_10m` if present); Open-Meteo marine `sea_surface_temperature`, `wave_height` | Shadow advisory | `forecast` |
| Hindcast exposure | IBTrACS v04r01 best track (post-analysis) | "What did the site experience", climatology. **Never** forecast skill or lead time (roadmap principle 3) | `best_track_oracle` |
| Hindcast weather/SST | ERA5 via Open-Meteo archive; NOAA OISST v2.1 daily | Climatology, Yagi cross-check | `reanalysis` |
| Ground truth (existing, not new) | Sensor `Temperature` 2026-05-29 → 10-14 (`core.greenlab_api.load_cached_history`) | SST → cage bias; storm response description (n = 2) | `sensor` |

Lead-time evaluation (did the forecast warn early enough?) is out of scope here; it needs Open-Meteo Previous Runs (`reconstructed_run`, decisions #13) and gets its own plan.

## Verified facts (checked 2026-10-22)

- IBTrACS CSV: `https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.{WP,last3years}.list.v04r01.csv`. Row 2 is a units row (`skiprows=[1]`), blanks are `" "`. `ISO_TIME` is UTC, 3-hourly. Columns used: `SID, SEASON, NAME, ISO_TIME, LAT, LON, TOKYO_WIND` (10-min kt; blank for 2026 provisional rows), `USA_WIND` (1-min kt), `USA_RMW` (nmi), `USA_R34|R50|R64_{NE,SE,SW,NW}` (nmi).
- Storms within 500 km of NB1 in `last3years`: 25 incl. YAGI 2024 (21 km, TOKYO 90 kt at 2024-09-07 06Z), WIPHA 2025 (21 km), **MAYSAK 2026-07-03 (75 km)** and **NARRA 2026-08-20 (74 km)**. The last two fall inside the sensor history → descriptive sensor-response check.
- ERA5 (Open-Meteo archive) at NB1 on 2024-09-07: max `wind_speed_10m` 29.56 m/s (cấp 11). Reanalysis is known to under-read typhoon cores; use it as a lower bound only.
- Open-Meteo marine SST at NB1: present 2023-07 onward, null for 2022 and earlier → too short for climatology, fine for bias and operations.
- OISST v2.1 via NCEI ERDDAP dataset `ncdc_oisst_v2_avhrr_by_time_zlev_lat_lon`: cell (20.875 N, 107.125 E) is land-masked; nearest valid cell is **(20.625 N, 107.125 E)**, ~13 km from NB1. `coastwatch.pfeg.noaa.gov` timed out; use `www.ncei.noaa.gov/erddap`.

## Thresholds and sources

| Item | Value | Source | Status |
| --- | --- | --- | --- |
| Beaufort lower bounds (m/s) | cấp 6 10.8, 7 13.9, 8 17.2, 9 20.8, 10 24.5, 11 28.5, 12 32.7, 13 37.0, 14 41.5, 15 46.2, 16 51.0, 17 56.1 | Beaufort scale as used in QĐ 18/2021/QĐ-TTg | regulation |
| Storm class | ATNĐ 6–7; bão 8–9; bão mạnh 10–11; bão rất mạnh 12–15; siêu bão ≥16 | QĐ 18/2021/QĐ-TTg | regulation |
| Risk level (storm on coastal waters / Đông Bắc Bộ) | ATNĐ, 8–11 → cấp độ 3; 12–15 → 4; ≥16 → 5 | QĐ 18/2021/QĐ-TTg Điều 42 | regulation |
| 1-min → 10-min wind | 0.93 (at sea); sensitivity 0.88 | Harper et al. 2010, WMO/TD-1555 | **verify table before thesis use** |
| Site action tiers (cấp 6/8/10/12) | see `SITE_ACTIONS_VI` | own proposal | **needs expert / farmer review** |
| Wave threshold for cages | none | no source found | **unset; report wave height as context only** |
| Heat watch | 31 °C daily mean | Sun & Chen 2014: feed-conversion optimum 31 °C (10–200 g) | literature |
| Heat stress | 33 °C | Sun & Chen 2014: growth optimum 33 °C, falls at 35 °C; `cobia_thresholds.json` 33 → 0.5 | literature |
| Heat severe | 34 °C | Le et al. 2024 (doi:10.3389/faquc.2024.1476881): growth −36 % at 34 vs 30 °C, survival 100 % over 6 weeks | literature |
| Persistence | ≥ 3 consecutive days ≥ 31 °C | own choice (DHW-style) | parameter |
| Hot + calm flag | air max ≥ 35 °C and daily mean wind < 3 m/s | stratification → low DO hypothesis | **hypothesis, no DO to test** |

Note: literature conflicts on the optimum (27–29 °C for ~22 g juveniles cited in Le et al. 2024, vs 33 °C in Sun & Chen 2014). Heat levels are therefore labelled **growth/stress risk, not mortality**. Do not edit `hap_shared/thresholds/cobia_thresholds.json`; log the discrepancy in decisions #17.

Sources:
- QĐ 18/2021/QĐ-TTg: https://vupc.mae.gov.vn/Data/files/18_2021_QD-TTg.doc ; Điều 42 summary https://luatduonggia.vn/?p=836289
- IBTrACS v04r01: https://www.ncei.noaa.gov/products/international-best-track-archive
- Sun & Chen 2014: https://sedarweb.org/documents/s58rd39_effects-of-water-temperature-and-fish-size-on-growth-and-bioenergetics-of-cobia-rachycentron-canadum
- Le et al. 2024: https://www.frontiersin.org/journals/aquaculture/articles/10.3389/faquc.2024.1476881/full
- Yagi cage losses (to verify per event row): https://vietnamnews.vn/society/1662575/typhoon-yagi-s-death-toll-rises-to-21-three-remains-missing , https://www.fishfarmermagazine.com/news/many-vietnamese-fish-farms-destroyed-in-typhoon

## Hard rules (all tasks)

- AGENTS.md hard rules. Downloads are **write-once**: never overwrite a file in `data/hazards/`; a re-download gets a new dated name. Run dirs are new per run.
- Paths only via `core/paths.py`. Tests network-free; anything reading `data/` is marked `requires_data`.
- Do not touch `core/alerts.py`, `core/weather_advisory.py` thresholds, or `core/weather.py` `HOURLY_VARIABLES` (snapshot store hashes those features).
- Commits: subject ≤ 72 chars, stage explicit paths, end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. No push without owner approval.

## File map

| File | Responsibility |
| --- | --- |
| `core/paths.py` (modify) | add `HAZARD_DATA_DIR` |
| `core/storm_advisory.py` (create) | Beaufort, storm class, QĐ 18 level, site exposure from IBTrACS rows, operational storm advisory |
| `core/heat_stress.py` (create) | daily heat-stress levels, hot+calm flag, operational heat advisory |
| `experiments/hazard_data.py` (create) | write-once downloads: IBTrACS, OISST, Open-Meteo marine SST, ERA5 |
| `experiments/storm_hindcast.py` (create) | storm climatology, Yagi cross-check, event catalog check, 2026 sensor response |
| `experiments/heat_hindcast.py` (create) | SST bias vs sensor, heat climatology + trend, week-of-year calendar |
| `experiments/hazard_events.csv` (create) | tracked event catalog with source URLs |
| `tests/test_storm_advisory.py`, `tests/test_heat_stress.py`, `tests/test_hazard_data.py` (create) | unit tests |
| `docs/guide/27-hazard-advisory-theory.md`, `docs/decisions.md`, `docs/research-log.md`, `experiments/RESULTS.md` (docs) | record method + results |

---

# Part A — Storm

### Task 1: paths entry

**Files:** Modify `core/paths.py` (after `FOREIGN_DATA_DIR`, line 44)

- [ ] **Step 1: Add the path**

```python
HAZARD_DATA_DIR = DATA_DIR / "hazards"  # theory track: IBTrACS, OISST, ERA5, marine SST downloads (write-once)
```

- [ ] **Step 2: Check isolation and commit**

Run: `.venv\Scripts\python scripts\check_isolation.py` → expect no violations.

```powershell
git add core/paths.py
git commit -m "paths: add HAZARD_DATA_DIR for public hazard data"
```

### Task 2: Beaufort, storm class, QĐ 18 level

**Files:** Create `core/storm_advisory.py`, `tests/test_storm_advisory.py`

- [ ] **Step 1: Write failing tests**

```python
import math

import pytest

from core.storm_advisory import beaufort, qd18_risk_level, site_action, storm_class_vi, to_ms


@pytest.mark.parametrize("speed, level", [(0.0, 0), (10.79, 5), (10.8, 6), (17.1, 7), (17.2, 8),
                                          (24.5, 10), (32.7, 12), (56.1, 17), (80.0, 17)])
def test_beaufort_bounds(speed, level):
    assert beaufort(speed) == level


def test_beaufort_missing():
    assert beaufort(None) is None
    assert beaufort(float("nan")) is None


def test_to_ms_units():
    assert to_ms(36, "km/h") == pytest.approx(10.0)
    assert to_ms(10, "kn") == pytest.approx(5.14444)
    assert to_ms(5, "m/s") == 5.0
    with pytest.raises(ValueError):
        to_ms(1, "furlong/h")


@pytest.mark.parametrize("level, cls", [(5, None), (6, "áp thấp nhiệt đới"), (9, "bão"),
                                        (11, "bão mạnh"), (15, "bão rất mạnh"), (16, "siêu bão")])
def test_storm_class(level, cls):
    assert storm_class_vi(level) == cls


@pytest.mark.parametrize("level, risk", [(None, None), (5, None), (6, 3), (11, 3), (12, 4), (15, 4), (16, 5)])
def test_qd18_level(level, risk):
    assert qd18_risk_level(level) == risk


def test_site_action_tiers():
    assert site_action(5)["tier"] == 0
    assert site_action(7)["tier"] == 1
    assert site_action(9)["tier"] == 2
    assert site_action(11)["tier"] == 3
    assert site_action(13)["tier"] == 4
    assert site_action(13)["basis"] == "proposal_needs_expert_review"
    assert site_action(None)["tier"] is None
```

- [ ] **Step 2: Run, expect FAIL** — `.venv\Scripts\python -m pytest tests/test_storm_advisory.py -q` → `ModuleNotFoundError: core.storm_advisory`.

- [ ] **Step 3: Implement**

```python
"""Tropical-cyclone exposure and risk for a cage site (theory only, shadow).

Beaufort bounds, storm classes and risk levels follow Quyết định 18/2021/QĐ-TTg
(Điều 42 for storms on the coastal waters off Đông Bắc Bộ).  IBTrACS rows are
best-track post-analysis: use them for hindcast exposure only, never as forecast
skill.  Nothing here drives alerts or notifications.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

KNOT_MS = 0.514444
NMI_KM = 1.852
# 1-min sustained -> 10-min mean at sea (Harper et al. 2010, WMO/TD-1555); 0.88 is the sensitivity case.
ONE_MIN_TO_TEN_MIN = 0.93
BEAUFORT_LOWER_MS = (0.0, 0.3, 1.6, 3.4, 5.5, 8.0, 10.8, 13.9, 17.2, 20.8, 24.5, 28.5,
                     32.7, 37.0, 41.5, 46.2, 51.0, 56.1)
_UNIT_TO_MS = {"m/s": 1.0, "ms": 1.0, "km/h": 1 / 3.6, "kmh": 1 / 3.6, "kn": KNOT_MS, "kt": KNOT_MS, "knots": KNOT_MS}
# Own proposal; needs review by farmers and the local disaster-prevention office.
SITE_ACTIONS_VI = (
    (12, 4, "rất nguy hiểm", "Người rời lồng bè vào nơi trú ẩn theo lệnh của địa phương."),
    (10, 3, "nguy hiểm", "Thu hoạch sớm cá thương phẩm nếu kịp; gia cố hoặc kéo lồng vào nơi kín gió; người rời lồng trước khi gió mạnh lên."),
    (8, 2, "chuẩn bị", "Gia cố neo, dây, phao; giảm hoặc ngừng cho ăn; chuẩn bị phương án thu hoạch và di dời."),
    (6, 1, "theo dõi", "Kiểm tra neo, dây, phao; theo dõi bản tin bão."),
)


def _missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value)


def to_ms(value: float, unit: str) -> float:
    key = unit.strip().lower()
    if key not in _UNIT_TO_MS:
        raise ValueError(f"unknown wind unit: {unit}")
    return float(value) * _UNIT_TO_MS[key]


def beaufort(speed_ms: float | None) -> int | None:
    if _missing(speed_ms):
        return None
    level = 0
    for lvl, lower in enumerate(BEAUFORT_LOWER_MS):
        if speed_ms >= lower:
            level = lvl
    return level


def storm_class_vi(level: int | None) -> str | None:
    if level is None or level < 6:
        return None
    if level <= 7:
        return "áp thấp nhiệt đới"
    if level <= 9:
        return "bão"
    if level <= 11:
        return "bão mạnh"
    if level <= 15:
        return "bão rất mạnh"
    return "siêu bão"


def qd18_risk_level(level: int | None) -> int | None:
    """Cấp độ rủi ro for a storm on coastal waters / Đông Bắc Bộ (QĐ 18/2021, Điều 42)."""
    if level is None or level < 6:
        return None
    if level <= 11:
        return 3
    if level <= 15:
        return 4
    return 5


def site_action(level: int | None) -> dict:
    base = {"basis": "proposal_needs_expert_review"}
    if level is None:
        return {**base, "tier": None, "label_vi": None, "action_vi": None}
    for min_level, tier, label, action in SITE_ACTIONS_VI:
        if level >= min_level:
            return {**base, "tier": tier, "label_vi": label, "action_vi": action}
    return {**base, "tier": 0, "label_vi": "bình thường", "action_vi": None}
```

- [ ] **Step 4: Run, expect PASS** — same command.

- [ ] **Step 5: Commit**

```powershell
git add core/storm_advisory.py tests/test_storm_advisory.py
git commit -m "storm_advisory: Beaufort, QD 18/2021 storm class and risk level"
```

### Task 3: site exposure from an IBTrACS track

**Files:** Modify `core/storm_advisory.py`, `tests/test_storm_advisory.py`

Method, per 3-hourly track row: distance and bearing from the storm centre to the site. If the site lies inside a 64/50/34-kt wind radius for its quadrant, its wind is **at least** that radius speed (converted to 10-min) → `exposure_method = "wind_radii"`. Otherwise use a modified Rankine vortex `V(r) = Vmax·r/Rmax` inside, `Vmax·(Rmax/r)^0.5` outside (`"rankine"`). When an R34 radius exists and the site is outside it, cap the Rankine estimate at the 34-kt level (`"rankine_capped_by_r34"`). Storm intensity uses `TOKYO_WIND` (10-min) when present, else `USA_WIND × factor`. Per storm keep the row with the highest site wind.

- [ ] **Step 1: Write failing tests** (append)

```python
import pandas as pd

from core.storm_advisory import (bearing_deg, haversine_km, load_ibtracs, quadrant, rankine_wind_ms,
                                 site_exposure, storm_passages)

SITE = (20.719, 107.043)


def _row(**kw):
    base = {"SID": "S1", "SEASON": 2024, "NAME": "TEST", "ISO_TIME": pd.Timestamp("2024-09-07T06:00Z"),
            "LAT": 20.9, "LON": 107.1, "TOKYO_WIND": 90.0, "USA_WIND": 110.0, "USA_RMW": 15.0}
    for q in ("NE", "SE", "SW", "NW"):
        base.update({f"USA_R34_{q}": float("nan"), f"USA_R50_{q}": float("nan"), f"USA_R64_{q}": float("nan")})
    base.update(kw)
    return pd.Series(base)


def test_haversine_one_degree():
    assert haversine_km(0.0, 0.0, 0.0, 1.0) == pytest.approx(111.19, abs=0.05)


def test_bearing_and_quadrant():
    assert quadrant(bearing_deg(0, 0, 1, 0)) == "NE"      # due north
    assert quadrant(bearing_deg(0, 0, 0, 1)) == "SE"      # due east
    assert quadrant(bearing_deg(0, 0, -1, 0)) == "SW"     # due south
    assert quadrant(bearing_deg(0, 0, 0, -1)) == "NW"     # due west


def test_rankine_profile():
    assert rankine_wind_ms(40.0, 30.0, 30.0) == pytest.approx(40.0)
    assert rankine_wind_ms(40.0, 30.0, 15.0) == pytest.approx(20.0)
    assert rankine_wind_ms(40.0, 30.0, 120.0) == pytest.approx(20.0)


def test_exposure_inside_r64():
    out = site_exposure(_row(USA_R64_SW=45.0, USA_R64_NE=45.0, USA_R64_SE=45.0, USA_R64_NW=45.0), *SITE)
    assert out["exposure_method"] == "wind_radii"
    assert out["site_wind_ms"] == pytest.approx(64 * 0.514444 * 0.93)
    assert out["site_beaufort"] == 11


def test_exposure_outside_r34_is_capped():
    far = _row(LAT=21.9, LON=107.1, USA_RMW=60.0, **{f"USA_R34_{q}": 10.0 for q in ("NE", "SE", "SW", "NW")})
    out = site_exposure(far, *SITE)
    assert out["exposure_method"] == "rankine_capped_by_r34"
    assert out["site_beaufort"] <= beaufort(34 * 0.514444 * 0.93)


def test_exposure_rankine_when_no_radii():
    out = site_exposure(_row(), *SITE)
    assert out["exposure_method"] == "rankine"
    assert out["storm_wind_source"] == "tokyo_10min"
    assert out["site_wind_ms"] > 0


def test_storm_passages_keeps_peak_and_drops_far():
    # 58 km out, outside a 10-nmi R34 -> capped at the 34-kt level, below near_b's 64-kt exposure
    near_a = _row(ISO_TIME=pd.Timestamp("2024-09-07T03:00Z"), LAT=20.7, LON=107.6,
                  **{f"USA_R34_{q}": 10.0 for q in ("NE", "SE", "SW", "NW")})
    near_b = _row(**{f"USA_R64_{q}": 45.0 for q in ("NE", "SE", "SW", "NW")})
    far = _row(SID="S2", NAME="FAR", LAT=10.0, LON=120.0)
    out = storm_passages(pd.DataFrame([near_a, near_b, far]), *SITE, radius_km=500)
    assert list(out["SID"]) == ["S1"]
    row = out.iloc[0]
    assert row["peak_time"] == pd.Timestamp("2024-09-07T06:00Z")
    assert row["site_beaufort"] == 11
    assert row["qd18_level"] == 4               # TOKYO 90 kt -> 46.3 m/s -> cấp 15
    assert row["source"] == "best_track_oracle"


def test_load_ibtracs_skips_units_row(tmp_path):
    csv = tmp_path / "ib.csv"
    csv.write_text("SID,SEASON,NAME,ISO_TIME,LAT,LON,TOKYO_WIND,USA_WIND,USA_RMW\n"
                   " ,Year, , ,degrees_north,degrees_east,kts,kts,nmile\n"
                   "S1,2024,YAGI,2024-09-07 06:00:00,20.9,107.1,90, ,15\n", encoding="utf-8")
    df = load_ibtracs(csv)
    assert len(df) == 1
    assert str(df["ISO_TIME"].dt.tz) == "UTC"
    assert pd.isna(df.loc[0, "USA_WIND"])
    assert "USA_R64_SW" in df.columns          # missing radius columns are added as NaN
```

- [ ] **Step 2: Run, expect FAIL** (ImportError on the new names).

- [ ] **Step 3: Implement** (append to `core/storm_advisory.py`)

```python
EARTH_RADIUS_KM = 6371.0088
DEFAULT_RMW_NMI = 30.0
RANKINE_ALPHA = 0.5
_RADII = (("USA_R64", 64.0), ("USA_R50", 50.0), ("USA_R34", 34.0))
_QUADS = ("NE", "SE", "SW", "NW")
IBTRACS_COLUMNS = ["SID", "SEASON", "NAME", "ISO_TIME", "LAT", "LON", "TOKYO_WIND", "USA_WIND", "USA_RMW",
                   *[f"{p}_{q}" for p, _ in _RADII for q in _QUADS]]


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi, dlmb = p2 - p1, np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    """Initial bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def quadrant(bearing: float) -> str:
    return _QUADS[int(bearing // 90) % 4]


def rankine_wind_ms(vmax_ms: float, rmw_km: float, r_km: float, alpha: float = RANKINE_ALPHA) -> float:
    if r_km <= rmw_km:
        return vmax_ms * r_km / rmw_km
    return vmax_ms * (rmw_km / r_km) ** alpha


def storm_wind_ms(row: pd.Series, factor: float = ONE_MIN_TO_TEN_MIN) -> tuple[float | None, str | None]:
    if not _missing(row.get("TOKYO_WIND")):
        return float(row["TOKYO_WIND"]) * KNOT_MS, "tokyo_10min"
    if not _missing(row.get("USA_WIND")):
        return float(row["USA_WIND"]) * KNOT_MS * factor, "usa_1min_scaled"
    return None, None


def site_exposure(row: pd.Series, site_lat: float, site_lon: float, factor: float = ONE_MIN_TO_TEN_MIN) -> dict:
    dist = float(haversine_km(row["LAT"], row["LON"], site_lat, site_lon))
    quad = quadrant(bearing_deg(row["LAT"], row["LON"], site_lat, site_lon))
    vmax, wind_source = storm_wind_ms(row, factor)
    out = {"dist_km": dist, "quadrant": quad, "storm_wind_ms": vmax, "storm_wind_source": wind_source}
    for prefix, kt in _RADII:
        radius = row.get(f"{prefix}_{quad}")
        if not _missing(radius) and dist <= float(radius) * NMI_KM:
            speed = kt * KNOT_MS * factor
            return {**out, "site_wind_ms": speed, "site_beaufort": beaufort(speed), "exposure_method": "wind_radii"}
    if vmax is None:
        return {**out, "site_wind_ms": None, "site_beaufort": None, "exposure_method": "no_intensity"}
    rmw_nmi = DEFAULT_RMW_NMI if _missing(row.get("USA_RMW")) else float(row["USA_RMW"])
    speed = rankine_wind_ms(vmax, rmw_nmi * NMI_KM, max(dist, 0.1))
    method = "rankine"
    if not _missing(row.get(f"USA_R34_{quad}")):
        speed = min(speed, 34 * KNOT_MS * factor)
        method = "rankine_capped_by_r34"
    return {**out, "site_wind_ms": speed, "site_beaufort": beaufort(speed), "exposure_method": method}


def load_ibtracs(path) -> pd.DataFrame:
    df = pd.read_csv(path, skiprows=[1], low_memory=False, na_values=[" ", ""], keep_default_na=True)
    for col in IBTRACS_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    df = df[IBTRACS_COLUMNS].copy()
    df["ISO_TIME"] = pd.to_datetime(df["ISO_TIME"], utc=True)
    for col in IBTRACS_COLUMNS[4:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def storm_passages(track: pd.DataFrame, site_lat: float, site_lon: float, radius_km: float = 500.0,
                   factor: float = ONE_MIN_TO_TEN_MIN) -> pd.DataFrame:
    """One row per storm passing within ``radius_km``: peak site exposure + QĐ 18 level."""
    cols = ["SID", "SEASON", "NAME", "peak_time", "min_dist_km", "storm_beaufort_max", "storm_class_vi",
            "qd18_level", "site_wind_ms", "site_beaufort", "exposure_method", "source"]
    df = track.dropna(subset=["LAT", "LON"]).copy()
    df["dist_km"] = haversine_km(df["LAT"].to_numpy(), df["LON"].to_numpy(), site_lat, site_lon)
    df = df[df["dist_km"] <= radius_km]
    rows = []
    for sid, grp in df.groupby("SID", sort=False):
        exposures = [site_exposure(r, site_lat, site_lon, factor) for _, r in grp.iterrows()]
        exp = pd.DataFrame(exposures, index=grp.index)
        exp["ISO_TIME"] = grp["ISO_TIME"]
        peak = exp.sort_values(["site_wind_ms", "dist_km"], ascending=[False, True], na_position="last").iloc[0]
        storm_max = exp["storm_wind_ms"].max()
        storm_bf = beaufort(storm_max) if not _missing(storm_max) else None
        rows.append({"SID": sid, "SEASON": grp["SEASON"].iloc[0], "NAME": grp["NAME"].iloc[0],
                     "peak_time": peak["ISO_TIME"], "min_dist_km": float(exp["dist_km"].min()),
                     "storm_beaufort_max": storm_bf, "storm_class_vi": storm_class_vi(storm_bf),
                     "qd18_level": qd18_risk_level(storm_bf), "site_wind_ms": peak["site_wind_ms"],
                     "site_beaufort": peak["site_beaufort"], "exposure_method": peak["exposure_method"],
                     "source": "best_track_oracle"})
    return pd.DataFrame(rows, columns=cols)
```

- [ ] **Step 4: Run, expect PASS.** If `test_exposure_outside_r34_is_capped` fails because the far row is still inside a 10-nmi R34 radius, check the distance (21.9 N is ~130 km away; 10 nmi = 18.5 km) before touching code.

- [ ] **Step 5: Commit**

```powershell
git add core/storm_advisory.py tests/test_storm_advisory.py
git commit -m "storm_advisory: site exposure from IBTrACS wind radii / Rankine"
```

### Task 4: operational storm advisory (forecast path, shadow)

**Files:** Modify `core/storm_advisory.py`, `tests/test_storm_advisory.py`

Input is the existing `get_station_weather()` payload (`hourly.time`, `hourly.wind_speed_10m`, `hourly_units.wind_speed_10m`, default km/h). Look at the next 72 h. Gusts are reported only if the payload has them; `HOURLY_VARIABLES` is not changed.

- [ ] **Step 1: Write failing tests** (append)

```python
from core.storm_advisory import evaluate_storm_advisory

NOW = pd.Timestamp("2026-07-02T00:00Z")


def _weather(speeds_kmh, status="ready"):
    times = pd.date_range("2026-07-02T07:00", periods=len(speeds_kmh), freq="h").strftime("%Y-%m-%dT%H:%M").tolist()
    return {"status": status, "timezone": "Asia/Ho_Chi_Minh", "retrieved_at": "2026-07-02T00:00:00+00:00",
            "hourly_units": {"wind_speed_10m": "km/h"}, "hourly": {"time": times, "wind_speed_10m": speeds_kmh}}


def test_storm_advisory_levels():
    out = evaluate_storm_advisory(_weather([20.0] * 10 + [70.0] + [30.0] * 10), now=NOW)
    assert out["max_wind_ms"] == pytest.approx(70 / 3.6)
    assert out["site_beaufort"] == 8
    assert out["action"]["tier"] == 2
    assert out["qd18_level"] == 3
    assert out["source"] == "forecast"
    assert out["used_by_alerts"] is False and out["notification_eligible"] is False


def test_storm_advisory_keeps_stale_status():
    assert evaluate_storm_advisory(_weather([10.0] * 5, status="stale"), now=NOW)["status"] == "stale"


def test_storm_advisory_unavailable():
    assert evaluate_storm_advisory({"status": "unavailable"}, now=NOW)["status"] == "unavailable"
    assert evaluate_storm_advisory(_weather([]), now=NOW)["status"] == "unavailable"
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement** (append)

```python
_FLAGS = {"used_by_models": False, "used_by_alerts": False, "notification_eligible": False,
          "basis": "theory_only_unvalidated"}


def _future_hourly(weather: dict, key: str, now: pd.Timestamp, hours: int) -> pd.Series:
    hourly = weather.get("hourly") or {}
    times = pd.to_datetime(hourly.get("time") or [], errors="coerce")
    values = hourly.get(key)
    if values is None or len(times) == 0:
        return pd.Series(dtype=float)
    if getattr(times, "tz", None) is None:
        times = times.tz_localize(weather.get("timezone", "Asia/Ho_Chi_Minh"))
    series = pd.Series(pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(), index=times.tz_convert("UTC"))
    start = now.floor("h")
    return series[(series.index >= start) & (series.index < start + pd.Timedelta(hours=hours))].dropna()


def evaluate_storm_advisory(weather: dict | None, now=None, hours: int = 72) -> dict:
    weather = weather or {}
    status = weather.get("status")
    if status not in {"ready", "stale"}:
        return {"status": "unavailable", "reason": weather.get("reason", "weather_unavailable"), **_FLAGS}
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    units = weather.get("hourly_units") or {}
    wind = _future_hourly(weather, "wind_speed_10m", now, hours)
    if wind.empty:
        return {"status": "unavailable", "reason": "no_future_wind_hours", **_FLAGS}
    wind_ms = wind.map(lambda v: to_ms(v, units.get("wind_speed_10m", "km/h")))
    gust = _future_hourly(weather, "wind_gusts_10m", now, hours)
    gust_ms = gust.map(lambda v: to_ms(v, units.get("wind_gusts_10m", "km/h"))) if not gust.empty else gust
    level = beaufort(float(wind_ms.max()))
    return {
        "status": status, "source": "forecast", "retrieved_at": weather.get("retrieved_at"),
        "window_hours": hours, "hours_available": int(len(wind_ms)),
        "max_wind_ms": round(float(wind_ms.max()), 2), "max_wind_at": wind_ms.idxmax().isoformat(),
        "max_gust_ms": round(float(gust_ms.max()), 2) if not gust_ms.empty else None,
        "site_beaufort": level, "storm_class_vi": storm_class_vi(level), "qd18_level": qd18_risk_level(level),
        "action": site_action(level),
        "disclaimer": "Chỉ số lý thuyết, chưa kiểm chứng tại hiện trường; không thay thế bản tin của cơ quan khí tượng.",
        **_FLAGS,
    }
```

Note: `qd18_level` here is computed from site wind, not storm-centre intensity; the doc (Task 11) must say it is an indicative mapping, not an official cấp độ rủi ro.

- [ ] **Step 4: Run, expect PASS.** Then the full suite: `.venv\Scripts\python -m pytest -q` → no new failures.

- [ ] **Step 5: Commit**

```powershell
git add core/storm_advisory.py tests/test_storm_advisory.py
git commit -m "storm_advisory: shadow advisory from Open-Meteo forecast wind"
```

### Task 5: write-once public data downloader

**Files:** Create `experiments/hazard_data.py`, `tests/test_hazard_data.py`

- [ ] **Step 1: Write failing tests** for the pure helpers

```python
import hashlib

import pytest

from experiments.hazard_data import parse_erddap_csv, write_once


def test_write_once_refuses_overwrite(tmp_path):
    target = tmp_path / "a.csv"
    meta = write_once(target, b"x,y\n1,2\n", url="http://example")
    assert meta["sha256"] == hashlib.sha256(b"x,y\n1,2\n").hexdigest()
    assert (tmp_path / "a.csv.manifest.json").exists()
    with pytest.raises(FileExistsError):
        write_once(target, b"other", url="http://example")


def test_parse_erddap_csv_skips_units_row():
    text = ("time,depth,latitude,longitude,sst\nUTC,m,degrees_north,degrees_east,Celsius\n"
            "2024-07-01T12:00:00Z,0.0,20.625,107.125,30.23\n2024-07-02T12:00:00Z,0.0,20.625,107.125,NaN\n")
    s = parse_erddap_csv(text)
    assert list(s.round(2).dropna()) == [30.23]
    assert str(s.index.tz) == "UTC"
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

```python
"""Write-once downloads of public hazard data into paths.HAZARD_DATA_DIR.

    python experiments/hazard_data.py ibtracs --subset WP
    python experiments/hazard_data.py ibtracs --subset last3years
    python experiments/hazard_data.py oisst --start-year 1982
    python experiments/hazard_data.py marine-sst --start 2023-07-01
    python experiments/hazard_data.py era5 --start-year 1982

Every file gets a sidecar ``<name>.manifest.json`` (url, sha256, fetched_at). An existing file
is never overwritten: files carry the download date in their name.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.config import weather_location_for_station  # noqa: E402

STATION = "06M26042804"
IBTRACS_URL = ("https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/"
               "v04r01/access/csv/ibtracs.{subset}.list.v04r01.csv")
OISST_URL = ("https://www.ncei.noaa.gov/erddap/griddap/ncdc_oisst_v2_avhrr_by_time_zlev_lat_lon.csv?"
             "sst%5B({start}T12:00:00Z):1:({end}T12:00:00Z)%5D%5B(0.0)%5D%5B({lat})%5D%5B({lon})%5D")
# Nearest non-land-masked OISST cell to NB1 (checked 2026-10-22; 20.875 N is land).
OISST_CELL = (20.625, 107.125)
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def write_once(target: Path, payload: bytes, url: str) -> dict:
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    meta = {"file": target.name, "url": url, "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "fetched_at": datetime.now(timezone.utc).isoformat()}
    Path(f"{target}.manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def parse_erddap_csv(text: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text), skiprows=[1])
    return pd.Series(pd.to_numeric(df["sst"], errors="coerce").to_numpy(),
                     index=pd.to_datetime(df["time"], utc=True), name="sst")


def _get(url: str, params: dict | None = None, timeout: int = 180) -> requests.Response:
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp


def fetch_ibtracs(subset: str) -> dict:
    url = IBTRACS_URL.format(subset=subset)
    target = paths.HAZARD_DATA_DIR / "ibtracs" / f"ibtracs.{subset}.list.v04r01.{date.today():%Y%m%d}.csv"
    return write_once(target, _get(url, timeout=600).content, url)


def fetch_oisst(start_year: int, end: date) -> dict:
    lat, lon = OISST_CELL
    parts = []
    for year in range(start_year, end.year + 1):
        stop = min(date(year, 12, 31), end)
        url = OISST_URL.format(start=f"{year}-01-01", end=stop.isoformat(), lat=lat, lon=lon)
        parts.append(parse_erddap_csv(_get(url).text))
    series = pd.concat(parts).sort_index()
    target = paths.HAZARD_DATA_DIR / "sst" / f"oisst_{lat}_{lon}_{start_year}_{end:%Y%m%d}.csv"
    return write_once(target, series.rename("sst").to_csv(index_label="time").encode(), OISST_URL)


def _open_meteo_hourly(url: str, params: dict, chunks: list[tuple[str, str]]) -> pd.DataFrame:
    frames = []
    for start, stop in chunks:
        data = _get(url, {**params, "start_date": start, "end_date": stop}).json()
        frames.append(pd.DataFrame(data["hourly"]))
    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize("UTC")
    return df


def fetch_marine_sst(start: str, end: date) -> dict:
    loc = weather_location_for_station(STATION)
    params = {"latitude": loc["latitude"], "longitude": loc["longitude"], "hourly": "sea_surface_temperature,wave_height",
              "cell_selection": "sea", "timezone": "GMT"}
    df = _open_meteo_hourly(MARINE_URL, params, [(start, end.isoformat())])
    target = paths.HAZARD_DATA_DIR / "sst" / f"openmeteo_marine_nb1_{start.replace('-', '')}_{end:%Y%m%d}.csv"
    return write_once(target, df.to_csv(index=False).encode(), MARINE_URL)


def fetch_era5(start_year: int, end: date) -> dict:
    loc = weather_location_for_station(STATION)
    params = {"latitude": loc["latitude"], "longitude": loc["longitude"],
              "hourly": "temperature_2m,wind_speed_10m,wind_gusts_10m", "wind_speed_unit": "ms", "timezone": "GMT"}
    chunks = [(f"{y}-01-01", min(date(y, 12, 31), end).isoformat()) for y in range(start_year, end.year + 1)]
    df = _open_meteo_hourly(ARCHIVE_URL, params, chunks)
    target = paths.HAZARD_DATA_DIR / "era5" / f"era5_nb1_{start_year}_{end:%Y%m%d}.csv"
    return write_once(target, df.to_csv(index=False).encode(), ARCHIVE_URL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ibtracs").add_argument("--subset", choices=["WP", "last3years", "ACTIVE"], required=True)
    for name in ("oisst", "era5"):
        p = sub.add_parser(name)
        p.add_argument("--start-year", type=int, default=1982)
    sub.add_parser("marine-sst").add_argument("--start", default="2023-07-01")
    for p in sub.choices.values():
        p.add_argument("--end", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)
    if args.cmd == "ibtracs":
        meta = fetch_ibtracs(args.subset)
    elif args.cmd == "oisst":
        meta = fetch_oisst(args.start_year, args.end)
    elif args.cmd == "era5":
        meta = fetch_era5(args.start_year, args.end)
    else:
        meta = fetch_marine_sst(args.start, args.end)
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests, expect PASS.**

- [ ] **Step 5: Download** (network; WP file is large, ~250 MB). OISST is ~44 requests; Open-Meteo archive ~45 requests (stay under its free daily limit; if HTTP 429, rerun next day with `--start-year` after the last finished year, since each run writes its own dated file).

```powershell
.venv\Scripts\python experiments\hazard_data.py ibtracs --subset WP
.venv\Scripts\python experiments\hazard_data.py ibtracs --subset last3years
.venv\Scripts\python experiments\hazard_data.py era5 --start-year 1982 --end 2026-10-20
.venv\Scripts\python experiments\hazard_data.py oisst --start-year 1982 --end 2026-10-08
.venv\Scripts\python experiments\hazard_data.py marine-sst --start 2023-07-01 --end 2026-10-20
```

Expected: each prints a manifest. OISST final data lag ~2 weeks; if the last year request returns HTTP 404, retry with `--end` one week earlier.

- [ ] **Step 6: Commit** (code only; `data/` is gitignored)

```powershell
git add experiments/hazard_data.py tests/test_hazard_data.py
git commit -m "hazard_data: write-once IBTrACS/OISST/ERA5/marine SST downloads"
```

### Task 6: event catalog

**Files:** Create `experiments/hazard_events.csv`

- [ ] **Step 1: Create the catalog** with exactly these columns. Seed only Yagi; `verified` stays `no` until the number has been copied from the source page.

```csv
event_id,hazard,start_date,end_date,area,impact_vi,source_url,verified
yagi-2024,storm,2024-09-06,2024-09-08,"Quảng Ninh; Hải Phòng","Hàng nghìn lồng nuôi bị phá hủy hoặc cuốn trôi (con số chính xác: xem nguồn)",https://vietnamnews.vn/society/1662575/typhoon-yagi-s-death-toll-rises-to-21-three-remains-missing,no
```

- [ ] **Step 2: Fill more rows from sources** — open each source, copy the cage/fish loss figure into `impact_vi`, set `verified=yes`. Candidates from `last3years`: WIPHA 2025-07, KAJIKI 2025-08, MAYSAK 2026-07-03, NARRA 2026-08-20; heat events (cá lồng chết do nắng nóng ở Cát Bà / Quảng Ninh) from Chi cục Thủy sản or provincial newspapers. **Never add a row without a source URL.**

- [ ] **Step 3: Commit**

```powershell
git add experiments/hazard_events.csv
git commit -m "hazard_events: tracked event catalog (Yagi seed)"
```

### Task 7: storm hindcast

**Files:** Create `experiments/storm_hindcast.py`

Outputs in `paths.EXPERIMENT_OUTPUT_DIR / f"storm-hindcast-{stamp}"` (refuse if it exists):

| File | Content |
| --- | --- |
| `passages.csv` | `storm_passages()` for WP (all seasons ≥ 1980) ∪ last3years (newer file wins per SID), radius 500 km, factor 0.93, plus `site_beaufort_088` with factor 0.88 |
| `climatology_year.csv` | per season: count of storms by `site_beaufort` band (6–7, 8–9, 10–11, ≥12) and by `qd18_level` |
| `climatology_month.csv` | per calendar month: mean storms/year with `site_beaufort ≥ 8` (seasonal storm calendar) |
| `yagi_check.json` | YAGI 2024 peak row: exposure method, site Beaufort (0.93 and 0.88), vs ERA5 max `wind_speed_10m` / `wind_gusts_10m` at NB1 2024-09-06→08 UTC |
| `events_check.csv` | each `storm` row of `hazard_events.csv`: matched SID (passage peak within event dates ± 1 day), site Beaufort, QĐ 18 level; `matched=False` rows kept |
| `sensor_response_2026.csv` | for passages with `SEASON == 2026` and `min_dist_km ≤ 150`: daily mean Temperature, TSS (and pH only for days ≤ 2026-09-18) and rows/day, from day −3 to +3 around `peak_time` (local date) |
| `manifest.json` | input files + sha256, params, row counts, `"source": "best_track_oracle"` |

- [ ] **Step 1: Implement**

```python
"""Storm hindcast at NB1 from IBTrACS best track (oracle exposure, not forecast skill).

    python experiments/storm_hindcast.py --stamp 20261022
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.config import weather_location_for_station  # noqa: E402
from core.greenlab_api import load_cached_history  # noqa: E402
from core.storm_advisory import beaufort, load_ibtracs, storm_passages  # noqa: E402

STATION = "06M26042804"
BANDS = [(6, 7, "cap6_7"), (8, 9, "cap8_9"), (10, 11, "cap10_11"), (12, 17, "cap12_plus")]
PH_TRUSTED_UNTIL = pd.Timestamp("2026-09-18").date()  # pH probe drift from 09-19 (RL-18)


def _latest(pattern: str) -> Path:
    files = sorted((paths.HAZARD_DATA_DIR).glob(pattern))
    if not files:
        raise FileNotFoundError(f"run experiments/hazard_data.py first: {pattern}")
    return files[-1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_tracks() -> tuple[pd.DataFrame, list[Path]]:
    wp, last3 = _latest("ibtracs/ibtracs.WP.list.*.csv"), _latest("ibtracs/ibtracs.last3years.list.*.csv")
    old, new = load_ibtracs(wp), load_ibtracs(last3)  # last3years spans all basins; distance filter drops the rest
    merged = pd.concat([old[~old["SID"].isin(new["SID"])], new], ignore_index=True)
    return merged[merged["SEASON"] >= 1980], [wp, last3]


def band_counts(passages: pd.DataFrame) -> pd.DataFrame:
    out = passages[["SEASON"]].drop_duplicates().set_index("SEASON")
    for lo, hi, name in BANDS:
        mask = passages["site_beaufort"].between(lo, hi)
        out[name] = passages[mask].groupby("SEASON").size()
    for lvl in (3, 4, 5):
        out[f"qd18_{lvl}"] = passages[passages["qd18_level"] == lvl].groupby("SEASON").size()
    return out.fillna(0).astype(int).sort_index()


def month_calendar(passages: pd.DataFrame, first: int, last: int) -> pd.DataFrame:
    strong = passages[passages["site_beaufort"] >= 8].copy()
    strong["month"] = strong["peak_time"].dt.tz_convert("Asia/Ho_Chi_Minh").dt.month
    per_month = strong.groupby("month").size().reindex(range(1, 13), fill_value=0)
    return (per_month / (last - first + 1)).rename("storms_per_year_site_cap8_plus").to_frame()


def yagi_check(passages: pd.DataFrame, era5: pd.DataFrame) -> dict:
    yagi = passages[(passages["NAME"] == "YAGI") & (passages["SEASON"] == 2024)]
    if yagi.empty:
        return {"status": "unavailable", "reason": "yagi_not_in_tracks"}
    row = yagi.iloc[0]
    start = pd.Timestamp("2024-09-06", tz="UTC")
    window = era5[(era5["time"] >= start) & (era5["time"] < start + pd.Timedelta(days=3))]
    return {"peak_time": row["peak_time"].isoformat(), "min_dist_km": round(row["min_dist_km"], 1),
            "exposure_method": row["exposure_method"], "site_beaufort_093": row["site_beaufort"],
            "site_beaufort_088": row["site_beaufort_088"], "storm_beaufort_max": row["storm_beaufort_max"],
            "qd18_level": row["qd18_level"],
            "era5_max_wind_ms": round(float(window["wind_speed_10m"].max()), 2),
            "era5_max_wind_beaufort": beaufort(float(window["wind_speed_10m"].max())),
            "era5_max_gust_ms": round(float(window["wind_gusts_10m"].max()), 2),
            "note": "ERA5 under-reads typhoon cores; treat as lower bound."}


def events_check(passages: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    local = passages["peak_time"].dt.tz_convert("Asia/Ho_Chi_Minh").dt.date
    for ev in events[events["hazard"] == "storm"].itertuples():
        lo = pd.Timestamp(ev.start_date).date() - pd.Timedelta(days=1)
        hi = pd.Timestamp(ev.end_date).date() + pd.Timedelta(days=1)
        hit = passages[(local >= lo) & (local <= hi)].sort_values("site_beaufort", ascending=False)
        best = hit.iloc[0] if not hit.empty else None
        rows.append({"event_id": ev.event_id, "verified": ev.verified, "matched": best is not None,
                     "SID": None if best is None else best["SID"], "NAME": None if best is None else best["NAME"],
                     "site_beaufort": None if best is None else best["site_beaufort"],
                     "qd18_level": None if best is None else best["qd18_level"]})
    return pd.DataFrame(rows)


def sensor_response(passages: pd.DataFrame) -> pd.DataFrame:
    hist = load_cached_history(STATION)
    hist["date"] = hist["fetchedAt"].dt.tz_convert("Asia/Ho_Chi_Minh").dt.date
    daily = hist.groupby("date").agg(rows=("fetchedAt", "size"), Temperature=("Temperature", "mean"),
                                     TSS=("TSS", "mean"), pH=("pH", "mean"))
    daily.loc[[d > PH_TRUSTED_UNTIL for d in daily.index], "pH"] = float("nan")
    rows = []
    for p in passages[(passages["SEASON"] == 2026) & (passages["min_dist_km"] <= 150)].itertuples():
        peak = p.peak_time.tz_convert("Asia/Ho_Chi_Minh").date()
        for offset in range(-3, 4):
            day = peak + pd.Timedelta(days=offset)
            rec = daily.loc[day].to_dict() if day in daily.index else {"rows": 0}
            rows.append({"SID": p.SID, "NAME": p.NAME, "day_offset": offset, "date": day, **rec})
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stamp", required=True)
    parser.add_argument("--radius-km", type=float, default=500.0)
    args = parser.parse_args(argv)
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / f"storm-hindcast-{args.stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    loc = weather_location_for_station(STATION)
    lat, lon = loc["latitude"], loc["longitude"]
    tracks, track_files = load_tracks()
    passages = storm_passages(tracks, lat, lon, args.radius_km, factor=0.93)
    alt = storm_passages(tracks, lat, lon, args.radius_km, factor=0.88)[["SID", "site_beaufort"]]
    passages = passages.merge(alt.rename(columns={"site_beaufort": "site_beaufort_088"}), on="SID", how="left")
    era5_file = _latest("era5/era5_nb1_*.csv")
    era5 = pd.read_csv(era5_file, parse_dates=["time"])
    events_file = Path(__file__).with_name("hazard_events.csv")
    first, last = int(passages["SEASON"].min()), int(passages["SEASON"].max())
    passages.to_csv(run_dir / "passages.csv", index=False)
    band_counts(passages).to_csv(run_dir / "climatology_year.csv")
    month_calendar(passages, first, last).to_csv(run_dir / "climatology_month.csv")
    (run_dir / "yagi_check.json").write_text(json.dumps(yagi_check(passages, era5), indent=2, default=str), encoding="utf-8")
    events_check(passages, pd.read_csv(events_file)).to_csv(run_dir / "events_check.csv", index=False)
    sensor_response(passages).to_csv(run_dir / "sensor_response_2026.csv", index=False)
    inputs = [*track_files, era5_file, events_file]
    manifest = {"run": run_dir.name, "source": "best_track_oracle", "site": {"lat": lat, "lon": lon, "anchor": "NB1"},
                "params": {"radius_km": args.radius_km, "factor": 0.93, "factor_sensitivity": 0.88},
                "seasons": [first, last], "passages": int(len(passages)),
                "inputs": {p.name: _sha(p) for p in inputs}}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run** — `.venv\Scripts\python experiments\storm_hindcast.py --stamp 20261022`. Expected: manifest printed; `passages.csv` has YAGI 2024, WIPHA 2025, MAYSAK and NARRA 2026.

- [ ] **Step 3: Sanity checks** (fix code, not expectations, if any fail):
  - YAGI `exposure_method == "wind_radii"` and `site_beaufort_093 ≥ 10`; ERA5 Beaufort ≤ that value.
  - `climatology_month.csv`: peak in Jul–Sep (known northern Gulf of Tonkin season). A peak in Dec–Mar means a timezone or unit bug.
  - `sensor_response_2026.csv`: rows per day listed; days with `rows < 1296` (90 % of 1,440) flagged in the write-up as partial.

- [ ] **Step 4: Commit**

```powershell
git add experiments/storm_hindcast.py
git commit -m "storm_hindcast: IBTrACS exposure climatology, Yagi and 2026 checks"
```

---

# Part B — Heat stress

### Task 8: heat-stress levels

**Files:** Create `core/heat_stress.py`, `tests/test_heat_stress.py`

- [ ] **Step 1: Write failing tests**

```python
import numpy as np
import pandas as pd
import pytest

from core.heat_stress import daily_from_hourly, daily_heat_stress, evaluate_heat_advisory, hot_calm_flag


def _days(values):
    return pd.Series(values, index=pd.date_range("2026-07-01", periods=len(values), freq="D"), dtype=float)


def test_levels_runs_and_alert():
    out = daily_heat_stress(_days([30, 31, 31, 31, 33, 34, 29]))
    assert list(out["level"]) == [0, 1, 1, 1, 2, 3, 0]
    assert list(out["run_days"]) == [0, 1, 2, 3, 4, 5, 0]
    assert list(out["alert_level"]) == [0, 1, 1, 1, 2, 3, 0]
    assert list(out["degree_days_7d"]) == [0, 0, 0, 0, 2, 5, 5]


def test_short_spike_is_capped_at_watch():
    out = daily_heat_stress(_days([30, 34, 30]))
    assert list(out["level"]) == [0, 3, 0]
    assert list(out["alert_level"]) == [0, 1, 0]


def test_missing_day_breaks_run():
    out = daily_heat_stress(_days([31, np.nan, 31, 31]))
    assert np.isnan(out["level"].iloc[1])
    assert list(out["run_days"]) == [1, 0, 1, 2]


def test_hot_calm_flag():
    flag = hot_calm_flag(pd.Series([36.0, 36.0, 30.0, np.nan]), pd.Series([2.0, 4.0, 1.0, 1.0]))
    assert list(flag) == [True, False, False, False]


def test_daily_from_hourly_requires_coverage():
    idx = pd.date_range("2026-07-01T00:00", periods=30, freq="h", tz="Asia/Ho_Chi_Minh").tz_convert("UTC")
    daily = daily_from_hourly(pd.Series(30.0, index=idx), min_hours=18)
    assert list(daily.round(1)) == [30.0]      # 2026-07-02 has 6 h only -> dropped


def test_heat_advisory_from_marine_forecast():
    times = pd.date_range("2026-07-02T00:00", periods=72, freq="h").strftime("%Y-%m-%dT%H:%M").tolist()
    marine = {"status": "ready", "timezone": "Asia/Ho_Chi_Minh",
              "hourly": {"time": times, "sea_surface_temperature": [33.5] * 72}}
    out = evaluate_heat_advisory(marine, now=pd.Timestamp("2026-07-01T17:00Z"))
    assert out["max_level"] == 2 and out["max_alert_level"] == 2
    assert out["source"] == "forecast" and out["used_by_alerts"] is False
    assert evaluate_heat_advisory({"status": "disabled"})["status"] == "unavailable"
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

```python
"""Cobia heat-stress levels from water temperature (theory only, shadow).

Levels are growth/stress risk, not mortality:
  31 °C feed-conversion optimum (Sun & Chen 2014, 10–200 g cobia)
  33 °C growth optimum, declining above (Sun & Chen 2014; cobia_thresholds.json 33 -> 0.5)
  34 °C growth −36 % vs 30 °C, survival 100 % over 6 weeks (Le et al. 2024, doi:10.3389/faquc.2024.1476881)
The hot+calm flag (stratification -> low DO) is a hypothesis: no DO sensor to test it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WATCH_C, STRESS_C, SEVERE_C = 31.0, 33.0, 34.0
MIN_RUN_DAYS = 3
DEGREE_BASE_C, DEGREE_WINDOW_DAYS = 31.0, 7
HOT_AIR_C, CALM_WIND_MS = 35.0, 3.0
LABELS_VI = {0: "bình thường", 1: "theo dõi (≥31 °C)", 2: "stress nhiệt (≥33 °C)", 3: "stress nặng (≥34 °C)"}
_FLAGS = {"used_by_models": False, "used_by_alerts": False, "notification_eligible": False,
          "basis": "theory_only_unvalidated"}


def daily_heat_stress(sst_daily: pd.Series) -> pd.DataFrame:
    s = sst_daily.astype(float)
    level = pd.Series(np.select([s >= SEVERE_C, s >= STRESS_C, s >= WATCH_C], [3, 2, 1], 0), index=s.index, dtype=float)
    level[s.isna()] = np.nan
    above = (s >= WATCH_C).astype(int)
    run = above.groupby((above == 0).cumsum()).cumsum()
    alert = level.where(run >= MIN_RUN_DAYS, level.clip(upper=1))
    degree = (s - DEGREE_BASE_C).clip(lower=0).fillna(0).rolling(DEGREE_WINDOW_DAYS, min_periods=1).sum()
    return pd.DataFrame({"temp_c": s, "level": level, "run_days": run, "alert_level": alert,
                         "degree_days_7d": degree.round(3)})


def hot_calm_flag(air_max_c: pd.Series, wind_mean_ms: pd.Series) -> pd.Series:
    return ((air_max_c >= HOT_AIR_C) & (wind_mean_ms < CALM_WIND_MS)).fillna(False).astype(bool)


def daily_from_hourly(series: pd.Series, tz: str = "Asia/Ho_Chi_Minh", min_hours: int = 18, how: str = "mean") -> pd.Series:
    local = series.dropna()
    local.index = local.index.tz_convert(tz)
    grouped = local.groupby(local.index.date)
    daily = grouped.agg(how)[grouped.size() >= min_hours]
    daily.index = pd.to_datetime(daily.index)
    return daily


def evaluate_heat_advisory(marine: dict | None, now=None) -> dict:
    marine = marine or {}
    status = marine.get("status")
    if status not in {"ready", "stale"}:
        return {"status": "unavailable", "reason": marine.get("reason", "marine_unavailable"), **_FLAGS}
    hourly = marine.get("hourly") or {}
    times = pd.to_datetime(hourly.get("time") or [], errors="coerce")
    values = hourly.get("sea_surface_temperature")
    if values is None or len(times) == 0:
        return {"status": "unavailable", "reason": "sst_missing", **_FLAGS}
    if getattr(times, "tz", None) is None:
        times = times.tz_localize(marine.get("timezone", "Asia/Ho_Chi_Minh"))
    sst = pd.Series(pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(), index=times.tz_convert("UTC"))
    if now is not None:
        now = pd.Timestamp(now)
        sst = sst[sst.index >= now.floor("h")]
    days = daily_heat_stress(daily_from_hourly(sst))
    if days.empty:
        return {"status": "unavailable", "reason": "no_complete_forecast_day", **_FLAGS}
    max_alert = int(days["alert_level"].max())
    return {"status": status, "source": "forecast",
            "days": [{"date": d.date().isoformat(), "temp_c": round(r.temp_c, 2), "level": int(r.level),
                      "alert_level": int(r.alert_level)} for d, r in days.iterrows()],
            "max_level": int(days["level"].max()), "max_alert_level": max_alert, "label_vi": LABELS_VI[max_alert],
            "note_vi": "Nguy cơ giảm tăng trưởng / stress, không phải dự báo cá chết. Chuỗi ≥3 ngày chỉ tính trên các ngày dự báo.",
            **_FLAGS}
```

Check of the advisory test: 72 hours from 2026-07-02 00:00 local = three full local days at 33.5 → levels 2,2,2, run 1,2,3 → alert 1,1,2 → `max_alert_level == 2`. `now` = 2026-07-01T17:00Z = 07-02 00:00 local, so no hour is dropped.

- [ ] **Step 4: Run, expect PASS**, then the full suite.

- [ ] **Step 5: Commit**

```powershell
git add core/heat_stress.py tests/test_heat_stress.py
git commit -m "heat_stress: cobia heat-stress levels and shadow advisory"
```

### Task 9: heat hindcast

**Files:** Create `experiments/heat_hindcast.py`

Outputs in `paths.EXPERIMENT_OUTPUT_DIR / f"heat-hindcast-{stamp}"`:

| File | Content |
| --- | --- |
| `bias.json` | sensor daily mean Temperature (days with ≥ 1,296 rows, values 10–40 °C) vs OISST and vs Open-Meteo marine SST: `n_days`, `median_diff_c` (sensor − product), `mae_c`, `pearson_r` |
| `daily_oisst.csv` | `daily_heat_stress()` on OISST, raw and bias-adjusted (`+ median_diff_c` vs OISST) |
| `climatology_year.csv` | per year: days with `alert_level ≥ 1/2/3`, max run, max `degree_days_7d`, hot+calm days (ERA5), for raw and adjusted |
| `trend.json` | Theil–Sen slope (days/decade) of yearly `alert_level ≥ 1` and `≥ 2` days, with 95 % CI (`scipy.stats.theilslopes`) |
| `heat_calendar.csv` | ISO week 1–53: share of years in which any day of that week has `alert_level ≥ 2` (adjusted) — seed for the stocking calendar |
| `manifest.json` | inputs + sha256, thresholds, bias used |

- [ ] **Step 1: Implement**

```python
"""Heat-stress hindcast at NB1: SST product bias vs sensor, climatology, trend, weekly calendar.

    python experiments/heat_hindcast.py --stamp 20261022
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import heat_stress as hs  # noqa: E402
from core import paths  # noqa: E402
from core.greenlab_api import load_cached_history  # noqa: E402

STATION = "06M26042804"
MIN_SENSOR_ROWS = 1296  # 90 % of 1,440 minutes (Phase 0 gate)


def _latest(pattern: str) -> Path:
    files = sorted(paths.HAZARD_DATA_DIR.glob(pattern))
    if not files:
        raise FileNotFoundError(f"run experiments/hazard_data.py first: {pattern}")
    return files[-1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sensor_daily() -> pd.Series:
    hist = load_cached_history(STATION)
    temp = hist.set_index("fetchedAt")["Temperature"]
    temp = temp[(temp >= 10) & (temp <= 40)]
    local = temp.tz_convert("Asia/Ho_Chi_Minh")
    grouped = local.groupby(local.index.date)
    daily = grouped.mean()[grouped.size() >= MIN_SENSOR_ROWS]
    daily.index = pd.to_datetime(daily.index)
    return daily


def compare(sensor: pd.Series, product: pd.Series) -> dict:
    joined = pd.concat([sensor.rename("sensor"), product.rename("product")], axis=1).dropna()
    if len(joined) < 10:
        return {"n_days": int(len(joined)), "status": "insufficient_overlap"}
    diff = joined["sensor"] - joined["product"]
    return {"n_days": int(len(joined)), "first": str(joined.index.min().date()), "last": str(joined.index.max().date()),
            "median_diff_c": round(float(diff.median()), 3), "mae_c": round(float(diff.abs().mean()), 3),
            "pearson_r": round(float(joined["sensor"].corr(joined["product"])), 3)}


def yearly(days: pd.DataFrame, hot_calm: pd.Series) -> pd.DataFrame:
    g = days.groupby(days.index.year)
    out = pd.DataFrame({f"days_alert_ge{k}": g["alert_level"].apply(lambda s, k=k: int((s >= k).sum())) for k in (1, 2, 3)})
    out["max_run_days"] = g["run_days"].max()
    out["max_degree_days_7d"] = g["degree_days_7d"].max()
    out["hot_calm_days"] = hot_calm.groupby(hot_calm.index.year).sum().reindex(out.index).fillna(0).astype(int)
    out["n_days"] = g.size()
    return out[out["n_days"] >= 330]  # drop incomplete years


def trend(year_table: pd.DataFrame, column: str) -> dict:
    slope, intercept, lo, hi = stats.theilslopes(year_table[column].to_numpy(), year_table.index.to_numpy())
    return {"column": column, "days_per_decade": round(slope * 10, 2), "ci95_per_decade": [round(lo * 10, 2), round(hi * 10, 2)],
            "years": [int(year_table.index.min()), int(year_table.index.max())]}


def calendar(days: pd.DataFrame) -> pd.DataFrame:
    iso = days.index.isocalendar()
    hit = (days["alert_level"] >= 2).groupby([iso["year"].to_numpy(), iso["week"].to_numpy()]).any()
    share = hit.groupby(level=1).mean()
    return share.rename("share_years_with_stress_day").to_frame().rename_axis("iso_week")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stamp", required=True)
    args = parser.parse_args(argv)
    run_dir = paths.EXPERIMENT_OUTPUT_DIR / f"heat-hindcast-{args.stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    oisst_file, marine_file, era5_file = _latest("sst/oisst_*.csv"), _latest("sst/openmeteo_marine_nb1_*.csv"), _latest("era5/era5_nb1_*.csv")
    oisst = pd.read_csv(oisst_file, parse_dates=["time"]).set_index("time")["sst"]
    oisst.index = oisst.index.tz_convert("Asia/Ho_Chi_Minh").normalize().tz_localize(None)
    marine = pd.read_csv(marine_file, parse_dates=["time"]).set_index("time")["sea_surface_temperature"]
    marine_daily = hs.daily_from_hourly(marine)
    era5 = pd.read_csv(era5_file, parse_dates=["time"]).set_index("time")
    air_max = hs.daily_from_hourly(era5["temperature_2m"], how="max")
    wind_mean = hs.daily_from_hourly(era5["wind_speed_10m"])
    hot_calm = hs.hot_calm_flag(air_max, wind_mean.reindex(air_max.index))

    sensor = sensor_daily()
    bias = {"vs_oisst": compare(sensor, oisst), "vs_openmeteo_marine": compare(sensor, marine_daily)}
    offset = bias["vs_oisst"].get("median_diff_c", 0.0)
    raw, adj = hs.daily_heat_stress(oisst), hs.daily_heat_stress(oisst + offset)
    raw.join(adj, rsuffix="_adjusted").to_csv(run_dir / "daily_oisst.csv", index_label="date")
    years = yearly(raw, hot_calm).join(yearly(adj, hot_calm), rsuffix="_adjusted")
    years.to_csv(run_dir / "climatology_year.csv", index_label="year")
    trends = [trend(years, c) for c in ("days_alert_ge1", "days_alert_ge2", "days_alert_ge1_adjusted", "days_alert_ge2_adjusted")]
    calendar(adj).to_csv(run_dir / "heat_calendar.csv")
    (run_dir / "bias.json").write_text(json.dumps(bias, indent=2), encoding="utf-8")
    (run_dir / "trend.json").write_text(json.dumps(trends, indent=2), encoding="utf-8")
    manifest = {"run": run_dir.name, "source": "reanalysis", "oisst_offset_c": offset,
                "thresholds_c": {"watch": hs.WATCH_C, "stress": hs.STRESS_C, "severe": hs.SEVERE_C,
                                 "min_run_days": hs.MIN_RUN_DAYS, "hot_air": hs.HOT_AIR_C, "calm_wind_ms": hs.CALM_WIND_MS},
                "inputs": {p.name: _sha(p) for p in (oisst_file, marine_file, era5_file)}, "sensor_days": int(len(sensor))}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({**manifest, "bias": bias, "trends": trends}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run** — `.venv\Scripts\python experiments\heat_hindcast.py --stamp 20261022`.

- [ ] **Step 3: Sanity checks:**
  - `bias.json` `n_days` ≥ 100 vs OISST (sensor 05-29 → 10-14, OISST ends ~2 weeks before download). Cage water in a sheltered bay is expected warmer than the 0.25° offshore cell in summer; a negative `median_diff_c` larger than 1 °C means check the timezone/date alignment first.
  - `heat_calendar.csv` non-zero only in the warm season (≈ weeks 22–38). Winter hits mean a unit or index bug.
  - Report summer 2026 sensor maximum daily mean next to OISST for the same days.

- [ ] **Step 4: Commit**

```powershell
git add experiments/heat_hindcast.py
git commit -m "heat_hindcast: SST bias vs sensor, heat climatology and calendar"
```

---

# Wrap-up

### Task 10: export to research-map (optional, only if the owner asks)

Skip by default. If asked: add `storm_hindcast` / `heat_hindcast` summaries to `scripts/export_research_map_artifacts.py` under H2, labelled `theory_only_unvalidated`, following the existing export pattern (missing inputs → omitted with a reason).

### Task 11: docs

**Files:** Create `docs/guide/27-hazard-advisory-theory.md`; modify `docs/decisions.md`, `docs/research-log.md`, `experiments/RESULTS.md`, `AGENTS.md` (Docs map line)

- [ ] **Step 1: `docs/guide/27-hazard-advisory-theory.md`** (Vietnamese): purpose; the data-path table above; threshold table with sources; method (wind radii → Rankine → cap, factor 0.93/0.88; heat levels, run ≥ 3 days, bias offset); what it is **not** (not an official cấp độ rủi ro; not mortality; no lead-time claim; wave threshold unset; hot+calm untested); how to run (Tasks 5, 7, 9 commands); results summary with numbers from the two run dirs.

- [ ] **Step 2: `docs/decisions.md` #17** — "2026-10-22 · Hướng lý thuyết + dữ liệu công khai cho cảnh báo bão và nắng nóng": owner decision (sensors/sampling hard to extend); IBTrACS = oracle, exposure only; thresholds from QĐ 18/2021 + Sun & Chen 2014 + Le et al. 2024; literature conflict on the cobia optimum (27–29 vs 33 °C) → levels labelled growth/stress, `cobia_thresholds.json` unchanged; action tiers and wave threshold need expert input.

- [ ] **Step 3: `docs/research-log.md` RL-29 (storm) and RL-30 (heat)** in the existing format (Câu hỏi / Thiết lập / Kết quả / Kết luận / Artifact / Tiếp theo), numbers taken from the run outputs only.

- [ ] **Step 4: `experiments/RESULTS.md`** — one row each for `storm-hindcast-<stamp>/` and `heat-hindcast-<stamp>/` with the key result.

- [ ] **Step 5: AGENTS.md** — add `27` to the Docs map line.

- [ ] **Step 6: Full verification**

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python scripts\check_isolation.py
```

Expected: all pass (previous count + new tests), no isolation violations.

- [ ] **Step 7: Commit**

```powershell
git add docs/guide/27-hazard-advisory-theory.md docs/decisions.md docs/research-log.md experiments/RESULTS.md AGENTS.md
git commit -m "docs: hazard advisory theory track (decisions #17, RL-29..30)"
```

## Follow-up plans (not in this plan)

1. Lead time: Open-Meteo Previous Runs for Yagi / Maysak / Narra (`reconstructed_run`) → how many hours ahead the forecast path reached cấp 8 / 10.
2. Wire both advisories into the shadow runner ledger (`runtime/hazard-shadow/*.jsonl`, `MARINE_ENABLED` needed for heat).
3. Disease-risk index (Vibrio/Streptococcus temperature–salinity rules) reusing `heat_stress` daily series.
4. Stocking calendar combining `heat_calendar.csv` and `climatology_month.csv`.
