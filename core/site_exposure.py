"""Per-site exposure of a cage site to wind, fetch-limited waves and currents (theory only, shadow).

Pure functions, no I/O.  ``experiments/site_exposure.py`` builds the per-site direction profiles
(fetch from the OSM water mask, shelter from a DSM, depth from ETOPO) and calls ``evaluate_site``.

Sources (numbers read in the cited text, 2026-10-23):

* Waves: Shore Protection Manual 1984 (USACE CERC, 4th ed., vol. 1), ch. 3.
  Wind-stress factor U_A = 0.71 U^1.23 (eq. 3-28a, U in m/s); deep water gH/U_A^2 = 1.6e-3 (gF/U_A^2)^1/2
  (3-33), gT_m/U_A = 2.857e-1 (gF/U_A^2)^1/3 (3-34), duration gt/U_A = 6.88e1 (gF/U_A^2)^2/3 (3-35),
  fully developed gH/U_A^2 = 2.433e-1 (3-36), gT_m/U_A = 8.134 (3-37); shallow water (3-39, 3-40):
  gH/U_A^2 = 0.283 tanh[0.530 (gd/U_A^2)^3/4] tanh{0.00565 (gF/U_A^2)^1/2 / tanh[0.530 (gd/U_A^2)^3/4]},
  gT/U_A = 7.54 tanh[0.833 (gd/U_A^2)^3/8] tanh{0.0379 (gF/U_A^2)^1/3 / tanh[0.833 (gd/U_A^2)^3/8]}.
  SPM 1984 sec. V.4 says effective fetch "should not be used with the growth curves presented herein", so
  wave height uses the straight-line fetch; Saville's cos^2 effective fetch (Saville 1954, as given in
  USBR/TR-69 practice) is reported only as an exposure index.
  The U_A power law was fitted for moderate winds: at storm speeds (cấp 10-12) the result is an
  extrapolation and should be read as an order of magnitude.
* Shelter: Brandle, Zhou & Hodges, "How windbreaks work", UNL Extension EC1763 (2006), Fig. 2, solid
  fence (100 % density): 25 % of open wind at 5H, 70 % at 10H, 90 % at 15H, 95 % at 20H, 100 % at 30H.
  Applying a 2-D windbreak curve to 3-D karst islands (flow goes around as well as over) is an
  approximation; ``SHELTER_FLOOR`` (0.5) is our assumption because storm flow in a lee is gusty.
* Classes: NS 9415 (1st ed.) Table A.1 wave classes A-E by Hs (0-0.5, 0.5-1.0, 1.0-2.0, 2.0-3.0, >3.0 m)
  and Table A.2 current classes a-e (0-0.3, 0.3-0.5, 0.5-1.0, 1.0-1.5, >1.5 m/s), as shown in Lader et al.
  (SINTEF/EXPOSED, OMAE2017-61659 slides).  NACA/FAO Seafarming Project RAS/86/024 (1989), "Site selection
  criteria for marine finfish netcage culture in Asia", Table 1: floating cage wave height < 1.0 m;
  current max < 100 cm/s (ideally < 50 cm/s).
* Wind tiers: ``core.storm_advisory.site_action`` (cấp 6/8/10/12 -> 1/2/3/4, own proposal).

The tier combination rule (max of wind and wave tier, +1 when the current is >= 1.0 m/s) is our
assumption.  Nothing here drives alerts or notifications.
"""
from __future__ import annotations

import math
from typing import Callable, Iterable, Sequence

import numpy as np
from pyproj import Geod

from core.storm_advisory import beaufort, site_action

G = 9.81
GEOD = Geod(ellps="WGS84")
COMPASS16 = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
BEARINGS16 = tuple(i * 22.5 for i in range(16))
SAVILLE_OFFSETS = tuple(range(-42, 43, 6))  # 15 radials at 6 deg, +-42 deg

# EC1763 Fig. 2, solid fence: distance in obstacle heights -> fraction of open wind speed
SHELTER_XH = (5.0, 10.0, 15.0, 20.0, 30.0)
SHELTER_FRAC = (0.25, 0.70, 0.90, 0.95, 1.00)
SHELTER_FLOOR = 0.5  # assumption (storm lee flow is gusty and goes around islands)
SHELTER_MIN_HEIGHT_M = 5.0

WAVE_CLASS_UPPER = ((0.5, "A"), (1.0, "B"), (2.0, "C"), (3.0, "D"))
CURRENT_CLASS_UPPER = ((0.3, "a"), (0.5, "b"), (1.0, "c"), (1.5, "d"))
# assumption: NS 9415 wave class -> action tier (class C exceeds the NACA/FAO 1.0 m floating-cage limit)
WAVE_TIER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
STRONG_CURRENT_MS = 1.0  # NACA/FAO 1989 max for netcages
DEFAULT_DURATION_H = 3.0  # assumption: wind holds its direction ~3 h in a passing storm

FLAGS = {"used_by_models": False, "used_by_alerts": False, "notification_eligible": False,
         "basis": "theory_only_unvalidated"}


def _bad(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


# ---------------------------------------------------------------- waves (SPM 1984)

def wind_stress_factor(u10: float) -> float:
    """SPM 1984 eq. 3-28a, U in m/s."""
    return 0.71 * float(u10) ** 1.23


def spm_deep_wave(u10: float, fetch_m: float) -> tuple[float, float]:
    """Deep-water fetch-limited (Hm0, Tm) from eqs. 3-33/3-34, capped at the fully developed 3-36/3-37."""
    ua = wind_stress_factor(u10)
    if ua <= 0 or fetch_m <= 0:
        return 0.0, 0.0
    x = G * fetch_m / ua ** 2
    h = min(1.6e-3 * x ** 0.5, 0.2433) * ua ** 2 / G
    t = min(0.2857 * x ** (1 / 3), 8.134) * ua / G
    return h, t


def spm_shallow_wave(u10: float, fetch_m: float, depth_m: float) -> tuple[float, float]:
    """Shallow/intermediate water (H, T) from SPM 1984 eqs. 3-39/3-40 (constant depth)."""
    ua = wind_stress_factor(u10)
    if ua <= 0 or fetch_m <= 0 or depth_m <= 0:
        return 0.0, 0.0
    x = G * fetch_m / ua ** 2
    d = G * depth_m / ua ** 2
    a_h = math.tanh(0.530 * d ** 0.75)
    a_t = math.tanh(0.833 * d ** 0.375)
    h = 0.283 * a_h * math.tanh(0.00565 * x ** 0.5 / a_h) * ua ** 2 / G
    t = 7.54 * a_t * math.tanh(0.0379 * x ** (1 / 3) / a_t) * ua / G
    return h, t


def duration_fetch_m(u10: float, duration_h: float) -> float:
    """Fetch equivalent to a wind duration (inverse of SPM eq. 3-35)."""
    ua = wind_stress_factor(u10)
    if ua <= 0 or duration_h <= 0:
        return 0.0
    gt_ua = G * duration_h * 3600.0 / ua
    return (gt_ua / 68.8) ** 1.5 * ua ** 2 / G


def fetch_wave(u10: float, fetch_m: float, depth_m: float | None, duration_h: float = DEFAULT_DURATION_H) -> dict:
    """Significant wave height/period for a local wind over a straight-line fetch.

    Takes the smaller of fetch- and duration-limited growth (SPM p. 3-47: check both), then the
    shallow-water form when a depth is given (it tends to the deep form for large depth).
    """
    if _bad(u10) or u10 <= 0 or _bad(fetch_m) or fetch_m <= 0:
        return {"hs_m": 0.0, "t_s": 0.0, "fetch_used_m": 0.0, "limited_by": None}
    f_dur = duration_fetch_m(u10, duration_h) if duration_h else math.inf
    f = min(fetch_m, f_dur)
    limited = "duration" if f_dur < fetch_m else "fetch"
    h, t = spm_deep_wave(u10, f)
    if depth_m is not None and not _bad(depth_m) and depth_m > 0:
        hs, ts = spm_shallow_wave(u10, f, depth_m)
        h, t = min(h, hs), min(t, ts)
    return {"hs_m": h, "t_s": t, "fetch_used_m": f, "limited_by": limited}


def saville_effective_fetch(radials: Sequence[float], offsets_deg: Sequence[float] = SAVILLE_OFFSETS) -> float:
    """Saville (1954) effective fetch: sum(F_i cos^2 a_i) / sum(cos a_i)."""
    f = np.asarray(radials, dtype=float)
    a = np.radians(np.asarray(offsets_deg, dtype=float))
    return float(np.sum(f * np.cos(a) ** 2) / np.sum(np.cos(a)))


# ---------------------------------------------------------------- shelter

def shelter_factor(distance_m: float, height_m: float, floor: float = SHELTER_FLOOR) -> float:
    """Fraction of open wind behind an obstacle of ``height_m`` at ``distance_m`` (EC1763 solid fence)."""
    if _bad(height_m) or height_m < SHELTER_MIN_HEIGHT_M or distance_m <= 0:
        return 1.0
    xh = distance_m / height_m
    frac = float(np.interp(xh, SHELTER_XH, SHELTER_FRAC, left=SHELTER_FRAC[0], right=1.0))
    return max(floor, frac)


def ray_shelter(distance_m: np.ndarray, elevation_m: np.ndarray, floor: float = SHELTER_FLOOR) -> dict:
    """Most sheltering obstacle along one upwind ray (smallest x/H)."""
    d = np.asarray(distance_m, dtype=float)
    z = np.nan_to_num(np.asarray(elevation_m, dtype=float), nan=0.0)
    ok = (z >= SHELTER_MIN_HEIGHT_M) & (d > 0)
    angle = float(np.degrees(np.arctan2(z[ok], d[ok])).max()) if ok.any() else 0.0
    if not ok.any():
        return {"factor": 1.0, "obstacle_height_m": None, "obstacle_distance_m": None, "max_elevation_angle_deg": angle}
    xh = d[ok] / z[ok]
    i = int(np.argmin(xh))
    return {"factor": shelter_factor(float(d[ok][i]), float(z[ok][i]), floor),
            "obstacle_height_m": float(z[ok][i]), "obstacle_distance_m": float(d[ok][i]),
            "max_elevation_angle_deg": angle}


# ---------------------------------------------------------------- geometry

def ray_points(lon: float, lat: float, bearing: float, distances_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = len(distances_m)
    lons, lats, _ = GEOD.fwd(np.full(n, lon), np.full(n, lat), np.full(n, bearing), distances_m)
    return np.asarray(lons), np.asarray(lats)


def ray_fetch(is_water: Callable[[np.ndarray, np.ndarray], np.ndarray], lon: float, lat: float,
              bearings: Iterable[float], step_m: float = 100.0, max_m: float = 200_000.0,
              extent: tuple[float, float, float, float] | None = None, start_m: float | None = None) -> dict:
    """Straight-line distance to the first non-water sample along each bearing (toward the bearing).

    For a wind FROM bearing b, the fetch is the water upwind, i.e. along the ray cast toward b.
    A ray that leaves ``extent`` (min_lon, min_lat, max_lon, max_lat) before meeting land is
    ``censored`` and gets ``max_m`` (the mask does not say what lies beyond its extent).
    """
    bearings = [float(b) for b in bearings]
    dists = np.arange(start_m or step_m, max_m + step_m / 2, step_m)
    fetch, censored = [], []
    for b in bearings:
        lons, lats = ray_points(lon, lat, b, dists)
        outside = np.zeros(len(dists), dtype=bool)
        if extent is not None:
            outside = (lons < extent[0]) | (lats < extent[1]) | (lons > extent[2]) | (lats > extent[3])
        water = np.asarray(is_water(lons, lats), dtype=bool) & ~outside
        dry = np.flatnonzero(~water)
        if dry.size == 0:
            fetch.append(float(max_m)); censored.append(True)
        elif outside[dry[0]]:
            fetch.append(float(max_m)); censored.append(True)
        else:
            fetch.append(float(dists[dry[0]] - step_m / 2) if dry[0] > 0 else 0.0); censored.append(False)
    return {"bearing": bearings, "fetch_m": fetch, "censored": censored}


def interp_direction(bearings: Sequence[float], values: Sequence[float], direction: float) -> float:
    """Circular linear interpolation of a per-direction quantity."""
    b = np.asarray(bearings, dtype=float) % 360.0
    v = np.asarray(values, dtype=float)
    order = np.argsort(b)
    b, v = b[order], v[order]
    b_ext = np.concatenate([b - 360.0, b, b + 360.0])
    v_ext = np.concatenate([v, v, v])
    return float(np.interp(float(direction) % 360.0, b_ext, v_ext))


def cyclone_wind_from(center_lat: float, center_lon: float, site_lat: float, site_lon: float,
                      inflow_deg: float = 20.0) -> float:
    """Direction the wind blows FROM at a site in a northern-hemisphere cyclone.

    Counter-clockwise tangential flow plus an inflow angle toward the centre (``inflow_deg`` is an
    assumption; ignores the storm's forward motion).
    """
    from core.storm_advisory import bearing_deg
    brg = bearing_deg(center_lat, center_lon, site_lat, site_lon)
    blow_to = brg - 90.0 - inflow_deg
    return (blow_to + 180.0) % 360.0


# ---------------------------------------------------------------- classes and tier

def wave_class(hs_m: float | None) -> str | None:
    if _bad(hs_m):
        return None
    for upper, name in WAVE_CLASS_UPPER:
        if hs_m < upper:
            return name
    return "E"


def current_class(speed_ms: float | None) -> str | None:
    if _bad(speed_ms):
        return None
    for upper, name in CURRENT_CLASS_UPPER:
        if speed_ms < upper:
            return name
    return "e"


def risk_tier(local_wind_ms: float, hs_m: float, current_ms: float | None = None) -> dict:
    """Tier 0-4: max(wind tier, wave tier), +1 if current >= 1.0 m/s and tier >= 1 (assumption)."""
    level = beaufort(local_wind_ms)
    wind_tier = site_action(level)["tier"] or 0
    wclass = wave_class(hs_m)
    wave_tier = WAVE_TIER.get(wclass, 0)
    tier = max(wind_tier, wave_tier)
    bumped = False
    if not _bad(current_ms) and current_ms >= STRONG_CURRENT_MS and tier >= 1:
        tier, bumped = min(4, tier + 1), True
    action = next((a for a in (site_action(lvl) for lvl in (12, 10, 8, 6)) if a["tier"] == tier), None)
    return {"tier": tier, "wind_tier": wind_tier, "wave_tier": wave_tier, "local_beaufort": level,
            "wave_class": wclass, "current_class": current_class(current_ms), "current_bump": bumped,
            "label_vi": action["label_vi"] if action else "bình thường",
            "tier_rule": "max(wind, wave) +1 if current>=1.0 m/s (assumption)"}


def evaluate_site(wind_ms: float | None, wind_from_deg: float | None, profile: dict,
                  current_ms: float | None = None, duration_h: float = DEFAULT_DURATION_H) -> dict:
    """Local wind, fetch-limited wave and tier at a site for an open-water wind and its direction.

    ``profile`` holds per-direction arrays keyed ``bearing`` (wind-from, deg), ``fetch_m`` (straight
    line), ``depth_m`` (mean along the fetch) and ``shelter`` (fraction of open wind).
    """
    if _bad(wind_ms) or _bad(wind_from_deg):
        return {"status": "unavailable", "reason": "missing_wind", **FLAGS}
    b = profile["bearing"]
    shelter = interp_direction(b, profile["shelter"], wind_from_deg)
    fetch = interp_direction(b, profile["fetch_m"], wind_from_deg)
    depth = interp_direction(b, profile["depth_m"], wind_from_deg) if "depth_m" in profile else None
    local = float(wind_ms) * shelter
    wave = fetch_wave(local, fetch, depth, duration_h)
    tier = risk_tier(local, wave["hs_m"], current_ms)
    return {"status": "ok", "wind_ms": float(wind_ms), "wind_from_deg": float(wind_from_deg) % 360.0,
            "shelter_factor": shelter, "local_wind_ms": local, "fetch_m": fetch, "depth_m": depth,
            "hs_m": wave["hs_m"], "t_s": wave["t_s"], "wave_limited_by": wave["limited_by"],
            "current_ms": current_ms, **tier, **FLAGS}
