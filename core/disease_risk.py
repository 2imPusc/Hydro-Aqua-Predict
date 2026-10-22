"""Cobia disease-favourable environment index from daily water temperature (theory only, shadow).

Not a diagnosis and not a disease forecast: it says how many pathogen groups find today's water
temperature inside the window where the cited literature reports growth / outbreaks.
Membership = trapezoid (a, b, c, d) on daily mean water temperature; breakpoints:
  vibrio          20, 25, -, -     V. harveyi disease in horse mackerel at >25 C (Zhang, He & Austin 2020,
                                   doi:10.1007/s42995-020-00037-z); V. parahaemolyticus prefers >20 C
                                   (Takemura et al. 2014, doi:10.3389/fmicb.2014.00038). No upper limit read.
  photobacterium  18, 20, 30, 32.5 P. damselae piscicida: outbreaks while SST >20 C, hatchery >18 C all year
                                   (Varvarigos 2020, CIHEAM Options Med. B75:83-96); growth 15-32.5,
                                   optimum 22.5-30 C (Romalde 2002, doi:10.1007/s10123-002-0051-6)
  streptococcus   23, 25, 28, 30   S. iniae mortality 25-28 C in barramundi sea cages (Bromage & Owens 2009,
                                   doi:10.1016/j.aquaculture.2009.02.038); +-2 C shoulders are our choice
  amyloodinium    15, 18, 30, 35   optimal reproduction 18-30 C, interrupted 15 C, damaged 35 C (Paperna 1984,
                                   doi:10.1051/parasite/1984591007)
  cryptocaryon    15, 21, 33, -    no hatching 15 C, low cleavage 15-18 C, 21-33 C full (Yin et al. 2023,
                                   Aquaculture); >33 C not tested
  cold (cobia)    <=15 -> 1, >=22 -> 0; run of >=14 days below 18 C before full weight. Cobia stop feeding
                  <18 C; cold >2 weeks -> fungal/bacterial infections; 15 C >5 weeks -> mass mortality
                  (Nhu et al. 2011, doi:10.1016/j.aquaculture.2010.07.024)
Host-stress flags (own parameters, hypotheses): 3-day rain >=100 mm (daily class: QD 46/2014/QD-TTg
art. 4.15, >100 mm/24 h = mua rat to) as a salinity-drop proxy, and |dT over 3 days| >= 3 C. Pathogen
literature does NOT support rain raising parasite risk (Amyloodinium needs 10-60 ppt, Paperna 1984;
Cryptocaryon infectivity drops at 5 ppt, Kong et al. 2022), so rain acts on the host, as a bump.
Combined: max(mean of warm memberships, cold risk) + STRESS_BUMP if a flag is set, clipped to [0, 1].
"""
from __future__ import annotations

import numpy as np
import pandas as pd

INF = np.inf
WARM_GROUPS: dict[str, tuple[float, float, float, float]] = {
    "vibrio": (20.0, 25.0, INF, INF),
    "photobacterium": (18.0, 20.0, 30.0, 32.5),
    "streptococcus": (23.0, 25.0, 28.0, 30.0),
    "amyloodinium": (15.0, 18.0, 30.0, 35.0),
    "cryptocaryon": (15.0, 21.0, 33.0, INF),
}
COLD_FULL_C, COLD_ZERO_C, COLD_FEED_STOP_C = 15.0, 22.0, 18.0
COLD_RUN_DAYS, COLD_CAP_BEFORE_RUN = 14, 0.6
RAIN_WINDOW_DAYS, RAIN_3D_MM = 3, 100.0
CHANGE_WINDOW_DAYS, RAPID_CHANGE_C = 3, 3.0
STRESS_BUMP = 0.25
MEDIUM, HIGH = 0.4, 0.75
LEVELS_VI = {0: "thấp", 1: "trung bình", 2: "cao"}
NOTE_VI = ("Nguy cơ điều kiện môi trường thuận lợi cho mầm bệnh (lý thuyết, chưa kiểm chứng), "
           "không phải chẩn đoán và không phải dự báo dịch bệnh.")
FLAGS = {"used_by_models": False, "used_by_alerts": False, "notification_eligible": False,
         "basis": "theory_only_unvalidated"}


def trapezoid(t: np.ndarray, bp: tuple[float, float, float, float]) -> np.ndarray:
    a, b, c, d = bp
    t = np.asarray(t, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        up = np.clip((t - a) / (b - a), 0, 1)
        down = np.ones_like(t) if np.isinf(d) else np.clip((d - t) / (d - c), 0, 1)  # d = inf: no upper limit read
    out = np.minimum(up, down)
    out[np.isnan(t)] = np.nan
    return out


def cold_membership(t: np.ndarray, shift_c: float = 0.0) -> np.ndarray:
    full, zero = COLD_FULL_C + shift_c, COLD_ZERO_C + shift_c
    t = np.asarray(t, dtype=float)
    out = np.clip((zero - t) / (zero - full), 0, 1)
    out[np.isnan(t)] = np.nan
    return out


def _shift(bp: tuple[float, float, float, float], s: float) -> tuple[float, float, float, float]:
    return tuple(v + s for v in bp)  # inf + s stays inf


def daily_disease_risk(temp_daily: pd.Series, rain_mm: pd.Series | None = None, shift_c: float = 0.0) -> pd.DataFrame:
    """Daily index from daily mean water temperature (C) and optional daily rain (mm)."""
    s = temp_daily.astype(float).sort_index()
    if isinstance(s.index, pd.DatetimeIndex) and len(s) > 1:
        s = s.asfreq("D")  # absent dates -> NaN days (break runs)
    t = s.to_numpy()
    out = pd.DataFrame({"temp_c": s})
    for name, bp in WARM_GROUPS.items():
        out[f"mu_{name}"] = trapezoid(t, _shift(bp, shift_c))
    mu_cols = [f"mu_{n}" for n in WARM_GROUPS]
    out["warm_index"] = out[mu_cols].mean(axis=1, skipna=False)
    out["warm_max"] = out[mu_cols].max(axis=1, skipna=False)
    out["mu_cold"] = cold_membership(t, shift_c)
    cold = (s < COLD_FEED_STOP_C + shift_c).astype(int)
    out["cold_run_days"] = cold.groupby((cold == 0).cumsum()).cumsum()
    out["cold_risk"] = out["mu_cold"].where(out["cold_run_days"] >= COLD_RUN_DAYS,
                                            out["mu_cold"].clip(upper=COLD_CAP_BEFORE_RUN))
    if rain_mm is not None:
        rain = rain_mm.astype(float).reindex(s.index)
        out["rain_3d_mm"] = rain.rolling(RAIN_WINDOW_DAYS, min_periods=RAIN_WINDOW_DAYS).sum().round(2)
    else:
        out["rain_3d_mm"] = np.nan
    out["heavy_rain_flag"] = (out["rain_3d_mm"] >= RAIN_3D_MM).fillna(False).astype(bool)
    out["temp_change_3d_c"] = (s - s.shift(CHANGE_WINDOW_DAYS)).round(3)
    out["rapid_change_flag"] = (out["temp_change_3d_c"].abs() >= RAPID_CHANGE_C).fillna(False).astype(bool)
    out["base_index"] = np.fmax(out["warm_index"], out["cold_risk"])
    out.loc[s.isna(), "base_index"] = np.nan
    bump = (out["heavy_rain_flag"] | out["rapid_change_flag"]).astype(float) * STRESS_BUMP
    out["index"] = (out["base_index"] + bump).clip(0, 1).round(4)
    out["level"] = pd.Series(np.select([out["index"] >= HIGH, out["index"] >= MEDIUM], [2, 1], 0),
                             index=out.index, dtype=float).where(out["index"].notna())
    out["dominant"] = np.where(out["cold_risk"] > out["warm_index"], "cold", "warm")
    out.loc[s.isna(), "dominant"] = None
    return out


def latest_advisory(days: pd.DataFrame, source: str) -> dict:
    valid = days[days["level"].notna()]
    if valid.empty:
        return {"status": "unavailable", "reason": "no_valid_day", "source": source, **FLAGS}
    d, r = valid.index[-1], valid.iloc[-1]
    groups = {n: round(float(r[f"mu_{n}"]), 3) for n in WARM_GROUPS}
    return {"status": "ready", "source": source, "date": pd.Timestamp(d).date().isoformat(),
            "temp_c": round(float(r["temp_c"]), 2), "index": round(float(r["index"]), 3), "level": int(r["level"]),
            "label_vi": LEVELS_VI[int(r["level"])], "groups": groups, "cold_risk": round(float(r["cold_risk"]), 3),
            "heavy_rain_flag": bool(r["heavy_rain_flag"]), "rapid_change_flag": bool(r["rapid_change_flag"]),
            "note_vi": NOTE_VI, **FLAGS}
