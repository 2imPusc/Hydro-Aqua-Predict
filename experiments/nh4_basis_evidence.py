"""Evidence on the unit and basis of the GreenLab "NH4" channel (station 06M26042804, NB1 Cát Bà).

Question (owner, 2026-10-26): does the sensor report total ammonium **as N** (TAN, factor
1.0, decision #28) or **NH4+ ion mass** (factor 14.007/18.038 = 0.7766)?  And is the
"raw × 0.001 = mg/L" (µg/L) assumption itself plausible?

Evidence assembled (read-only inputs, all hashed into the manifest):

1. Vendor metadata: the ``Unit`` field of every GreenLab JSON record (all_data, intervals,
   snapshots) per sensor type.
2. Sensor forensics on the native export (``all_data/*.csv``, 1 reading/min, all 4 stations):
   value resolution, rails / full scale, marine vs inland levels; on the frozen history
   (``sensor-history-20261024``): response of NH4 to the Emerson NH3 fraction (an NH3
   gas-sensing probe would scale ~1:1 with it), to pH, temperature and TSS; diurnal range;
   daily correlation with CMEMS surface salinity (Na+/K+ interference on an ISE).
3. Distribution matching: the pre-31/07 sensor level ×0.001 under factor 1.0 vs 0.7766
   against provincial "Amôni (NH4+ tính theo N)" at the Cát Bà stations near the cage
   (NB1/NB2/NB25/NB27, June–August), log-normal likelihood ratio with a bootstrap over the
   provincial samples, plus the implied best-fit scale; tide split (CT / ĐT) from the
   per-tide provincial CSVs when ``--hp-raw-dir`` is given; published Cát Bà ranges.
4. QCVN 10:2023 B1 ammonium (0.1 mg/L) verdict per day under both factors.

The 31/07 14:06 step itself is studied in the sibling run ``nh4-step-0731-*``; here it is
only used as a regime boundary.

    python experiments/nh4_basis_evidence.py [--run-name nh4-basis-evidence-20261026]
        [--hp-raw-dir <folder with hp_2020.csv … hp_2024.csv>]

Writes a NEW run dir under paths.EXPERIMENT_OUTPUT_DIR (exist_ok=False).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import paths  # noqa: E402
from core.chemistry import nh3_fraction  # noqa: E402

STATION = "06M26042804"
LOCAL_TZ = "Asia/Bangkok"
STEP = pd.Timestamp("2026-07-31 14:06", tz=LOCAL_TZ)   # first low reading (RL-69, sibling run)
N_FACTOR_ION = 14.007 / 18.038                          # NH4+ mass -> NH4-N
UNIT_SCALE = 0.001                                      # runtime assumption µg/L -> mg/L
QCVN_B1 = 0.1
CAGE_STATIONS = ("NB1", "NB2", "NB25", "NB27")          # Cát Bà stations nearest the cage
SUMMER_MONTHS = (6, 7, 8)
RECENT_YEARS = (2023, 2024)
NB1_LATLON = (20.71894498573044, 107.042635855355)
VANDON_LATLON = (21.03, 107.45)                         # approximate, Vân Đồn bay (station 03)
GREENLAB_DIR = paths.DATA_DIR / "greenlab" / "exports"
HISTORY = paths.EXPERIMENT_OUTPUT_DIR / "sensor-history-20261024" / f"{STATION}.csv"
CMEMS_DIR = paths.DATA_DIR / "cmems" / "GLOBAL_ANALYSISFORECAST_PHY_001_024"
SEED = 20261026
N_BOOT = 5000

# Published N-NH4+ ranges at Cát Bà cage areas (read from data/vn_public/rimf_farm_zones/).
LITERATURE = [
    {"source": "vjs_2014_le-tuan-son_catba-cage-pollution.pdf", "period": "05 & 09/2013",
     "sites": "Bến Bèo 1", "basis": "N-NH4+ (DREL/2010 trắc quang)", "lo": 0.103, "hi": 0.133},
    {"source": "vjs_2014_le-tuan-son_catba-cage-pollution.pdf", "period": "05 & 09/2013",
     "sites": "Bến Bèo 2", "basis": "N-NH4+", "lo": 0.093, "hi": 0.137},
    {"source": "vjs_2014_le-tuan-son_catba-cage-pollution.pdf", "period": "05 & 09/2013",
     "sites": "Tùng Tràng", "basis": "N-NH4+", "lo": 0.089, "hi": 0.146},
    {"source": "tapchixaydung_2026_tran-huu-long_haiphong-cage.pdf", "period": "04–08 (năm khảo sát không ghi rõ)",
     "sites": "CB1–CB4 (Hang Vẹm–Vụng O, Thoi Quýt–Gia Luận)", "basis": "N-NH4+ (chưng cất + Nessler)",
     "lo": 0.024, "hi": 0.21},
]


# ---------------------------------------------------------------- pure helpers (tested)

def grid_resolution(values: np.ndarray, candidates=(0.001, 0.01, 0.1, 1.0)) -> dict:
    """Coarsest grid step on which (almost) all values lie; share on each candidate grid."""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    shares = {}
    for step in candidates:
        ratio = v / step
        shares[step] = float(np.mean(np.abs(ratio - np.round(ratio)) < 1e-6))
    on_grid = [s for s in candidates if shares[s] >= 0.999]
    return {"resolution": max(on_grid) if on_grid else None, "share_on_grid": shares}


def lognormal_loglik(x: float, samples: np.ndarray) -> float:
    """Log density of ``x`` under a log-normal fitted (MLE) to positive ``samples``."""
    s = np.log(np.asarray(samples, dtype=float))
    mu, sd = s.mean(), s.std(ddof=1)
    lx = np.log(x)
    return float(-0.5 * ((lx - mu) / sd) ** 2 - np.log(sd * np.sqrt(2 * np.pi)) - lx)


def bayes_factor(level_n: float, level_ion: float, samples: np.ndarray) -> float:
    """Likelihood ratio  L(level as N) / L(level as ion) under the provincial log-normal."""
    return float(np.exp(lognormal_loglik(level_n, samples) - lognormal_loglik(level_ion, samples)))


def bootstrap_bayes_factor(level_n: float, level_ion: float, samples: np.ndarray,
                           n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    rng = np.random.default_rng(seed)
    samples = np.asarray(samples, dtype=float)
    bfs = np.array([bayes_factor(level_n, level_ion, rng.choice(samples, samples.size, replace=True))
                    for _ in range(n_boot)])
    bfs = bfs[np.isfinite(bfs)]
    return {"bf": bayes_factor(level_n, level_ion, samples), "bf_p025": float(np.quantile(bfs, 0.025)),
            "bf_p50": float(np.median(bfs)), "bf_p975": float(np.quantile(bfs, 0.975)),
            "share_bf_gt_1": float(np.mean(bfs > 1)), "n_samples": int(samples.size)}


def implied_scale(raw_level: float, samples: np.ndarray, n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """Scale k such that raw_level × k equals the provincial geometric mean (bootstrap CI)."""
    rng = np.random.default_rng(seed)
    samples = np.asarray(samples, dtype=float)
    gm = lambda a: float(np.exp(np.log(a).mean()))  # noqa: E731
    ks = np.array([gm(rng.choice(samples, samples.size, replace=True)) / raw_level for _ in range(n_boot)])
    return {"k_hat": gm(samples) / raw_level, "k_p025": float(np.quantile(ks, 0.025)),
            "k_p975": float(np.quantile(ks, 0.975))}


SEAWATER_NA_MOL = 0.4690    # mol/kg at S = 35 (standard seawater major ions)
SEAWATER_K_MOL = 0.01021
N_MASS, NH4_MASS = 14.007, 18.038


def ise_interference_mg_n(salinity: float, log_k_k: float, log_k_na: float) -> float:
    """Apparent NH4-N (mg/L) read by an NH4+ ISE in ammonium-free seawater (Nikolsky–Eisenman).

    Monovalent ions only, activity coefficients taken equal (they cancel to first order),
    density ≈ 1 kg/L.  ``log_k_*`` are log10 potentiometric selectivity coefficients
    K(NH4+, j) — literature ranges for nonactin membranes, not values of this probe.
    """
    scale = salinity / 35.0
    equiv_mol = 10 ** log_k_k * SEAWATER_K_MOL * scale + 10 ** log_k_na * SEAWATER_NA_MOL * scale
    return float(equiv_mol * N_MASS * 1000.0)


def qcvn_band(tan_n: pd.Series, tan_ion: pd.Series, limit: float = QCVN_B1) -> pd.Series:
    """Per-day verdict when the basis is unknown: both bounds over, straddling, both under."""
    over_n, over_i = tan_n > limit, tan_ion > limit
    out = pd.Series("dưới ngưỡng (cả hai cơ sở)", index=tan_n.index)
    out[over_n & ~over_i] = "không xác định (tuỳ cơ sở)"
    out[over_n & over_i] = "vượt (cả hai cơ sở)"
    out[~over_n & over_i] = "không xác định (tuỳ cơ sở)"
    return out


# ---------------------------------------------------------------- data loading

class Inputs:
    def __init__(self) -> None:
        self.used: dict[str, Path] = {}

    def add(self, path: Path) -> Path:
        self.used[str(path)] = path
        return path

    def manifest(self) -> list[dict]:
        out = []
        for name, path in sorted(self.used.items()):
            h = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            out.append({"path": name, "bytes": path.stat().st_size, "sha256": h.hexdigest()})
        return out


def unit_audit(inputs: Inputs) -> pd.DataFrame:
    rows = []
    for sub in ("all_data", "intervals", "snapshots"):
        for path in sorted((GREENLAB_DIR / sub).glob("*.json")):
            data = json.loads(inputs.add(path).read_text(encoding="utf-8"))
            if not isinstance(data, list):
                continue
            for rec in data:
                rows.append({"folder": sub, "device": rec.get("DeviceSerialNumber"),
                             "sensor": rec.get("SensorType"), "unit": rec.get("Unit")})
    frame = pd.DataFrame(rows)
    return frame.groupby(["sensor", "unit"]).agg(records=("device", "size"), files_devices=("device", "nunique")).reset_index()


def native_exports(inputs: Inputs) -> pd.DataFrame:
    frames = []
    for path in sorted((GREENLAB_DIR / "all_data").glob("*_All.csv")):
        f = pd.read_csv(inputs.add(path))
        f["station_file"] = path.stem
        frames.append(f)
    out = pd.concat(frames, ignore_index=True)
    out["t"] = pd.to_datetime(out["fetchedAt"])   # naive local time (decision #12)
    return out


def forensics_native(native: pd.DataFrame) -> pd.DataFrame:
    rows = []
    window = (native["t"] >= "2026-06-01") & (native["t"] < "2026-07-05")  # all 4 stations online
    for (dev, name), g in native.groupby(["device", "station_file"]):
        nh4 = g["NH4"].dropna()
        res = grid_resolution(nh4.to_numpy())
        diffs = nh4.diff().abs()
        w = g[window.loc[g.index]]
        rows.append({
            "device": dev, "station_file": name, "n": int(nh4.size),
            "first": str(g["t"].min()), "last": str(g["t"].max()),
            "resolution": res["resolution"], "share_on_0.01": round(res["share_on_grid"][0.01], 4),
            "min_nonzero_step": float(diffs[diffs > 0].min()) if (diffs > 0).any() else None,
            "max": float(nh4.max()), "rows_at_500": int((nh4 == 500).sum()),
            "median_jun01_jul04": float(w["NH4"].median()) if len(w) else None,
            "pH_median_jun01_jul04": float(w["pH"].median()) if len(w) else None,
            "water": "marine" if dev in ("06M26042803", "06M26042804") else "inland",
        })
    return pd.DataFrame(rows)


def load_history(inputs: Inputs) -> pd.DataFrame:
    raw = pd.read_csv(inputs.add(HISTORY))
    raw = raw[raw["device"].astype(str).eq(STATION)].copy()
    raw["t"] = pd.to_datetime(raw["fetchedAt"], utc=True).dt.tz_convert(LOCAL_TZ)
    raw = raw[(raw["NH4"] > 0) & raw["pH"].between(5, 10) & raw["Temperature"].between(10, 40)].copy()
    raw["f_nh3"] = nh3_fraction(raw["pH"].to_numpy(), raw["Temperature"].to_numpy())
    raw["regime"] = np.where(raw["t"] < STEP, "pre", "post")
    return raw.sort_values("t").reset_index(drop=True)


def response_forensics(hist: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for regime, g in hist.groupby("regime"):
        h = g.set_index("t")[["NH4", "pH", "Temperature", "f_nh3", "TSS"]].resample("1h").median().dropna()
        detr = lambda x: x - x.rolling(25, center=True, min_periods=12).median()  # noqa: E731
        anom = detr(h).dropna()
        lanom = detr(np.log(h[["NH4", "f_nh3"]])).dropna()
        slope = float(np.polyfit(lanom["f_nh3"], lanom["NH4"], 1)[0])
        hourly = g.groupby(g["t"].dt.hour)["NH4"].median()
        corr = anom.corr(method="spearman")["NH4"]
        rows.append({
            "regime": regime, "hours": int(len(h)),
            "raw_median": float(g["NH4"].median()),
            "slope_dlogNH4_dlogfNH3": round(slope, 3),
            "spearman_anom_pH": round(float(corr["pH"]), 3),
            "spearman_anom_Temperature": round(float(corr["Temperature"]), 3),
            "spearman_anom_fNH3": round(float(corr["f_nh3"]), 3),
            "spearman_anom_TSS": round(float(corr["TSS"]), 3),
            "diurnal_range_rel": round(float((hourly.max() - hourly.min()) / hourly.median()), 3),
            "fNH3_p05": round(float(h["f_nh3"].quantile(0.05)), 4), "fNH3_p95": round(float(h["f_nh3"].quantile(0.95)), 4),
            "NH4_p05_rel": round(float(h["NH4"].quantile(0.05) / h["NH4"].median()), 3),
            "NH4_p95_rel": round(float(h["NH4"].quantile(0.95) / h["NH4"].median()), 3),
        })
    return pd.DataFrame(rows)


def cmems_salinity(inputs: Inputs, pattern: str, latlon: tuple[float, float]) -> pd.Series | None:
    import xarray as xr
    files = sorted(CMEMS_DIR.glob(pattern))
    if not files:
        return None
    ds = xr.open_dataset(inputs.add(files[0]))
    so = ds["so"].isel(depth=0) if "depth" in ds["so"].dims else ds["so"]
    valid = so.notnull().any("time")
    lat, lon = np.meshgrid(ds["latitude"].values, ds["longitude"].values, indexing="ij")
    dist = np.where(valid.values, (lat - latlon[0]) ** 2 + (lon - latlon[1]) ** 2, np.inf)
    i, j = np.unravel_index(np.argmin(dist), dist.shape)
    s = so.isel(latitude=i, longitude=j).to_series()
    s.index = pd.to_datetime(s.index).date
    s.name = f"so_{float(ds['latitude'][i]):.3f}_{float(ds['longitude'][j]):.3f}"
    return s


def salinity_link(inputs: Inputs, hist: pd.DataFrame, native: pd.DataFrame) -> pd.DataFrame:
    rows = []
    cases = [
        (STATION, "anfc_so_d__*.nc", NB1_LATLON,
         hist[hist["regime"] == "pre"].assign(day=lambda f: f["t"].dt.date).groupby("day")["NH4"].median()),
        ("06M26042803", "vandon_anfc_so_d__*.nc", VANDON_LATLON,
         native[(native["device"] == "06M26042803") & (native["NH4"] < 500) & (native["pH"] > 6)]
         .assign(day=lambda f: f["t"].dt.date).groupby("day")["NH4"].median()),
    ]
    for dev, pattern, latlon, daily in cases:
        sal = cmems_salinity(inputs, pattern, latlon)
        if sal is None:
            continue
        joined = pd.concat([daily.rename("NH4"), sal.rename("so")], axis=1, join="inner").dropna()
        if len(joined) < 10:
            continue
        rows.append({"device": dev, "cell": sal.name, "days": int(len(joined)),
                     "spearman_NH4_so": round(float(joined.corr(method="spearman").iloc[0, 1]), 3),
                     "pearson_dNH4_dso": round(float(joined.diff().dropna().corr().iloc[0, 1]), 3),
                     "so_min": round(float(joined["so"].min()), 2), "so_max": round(float(joined["so"].max()), 2)})
    return pd.DataFrame(rows)


def provincial_samples(inputs: Inputs) -> pd.DataFrame:
    f = pd.read_csv(inputs.add(paths.clean_data("haiphong")), encoding="utf-8-sig")
    f["date"] = pd.to_datetime(f["Quarter"])
    f = f[f["Station"].isin(CAGE_STATIONS)].copy()
    f["year"], f["month"] = f["date"].dt.year, f["date"].dt.month
    return f[["Station", "year", "month", "NH3"]].rename(columns={"NH3": "tan"})


def provincial_tide_samples(inputs: Inputs, raw_dir: Path | None) -> pd.DataFrame | None:
    if raw_dir is None or not raw_dir.exists():
        return None
    rows = []
    for path in sorted(raw_dir.glob("hp_20*.csv")):
        year = int(re.search(r"hp_(\d{4})", path.name).group(1))
        f = pd.read_csv(inputs.add(path), encoding="utf-8-sig")
        col = "NH4" if "NH4" in f.columns else next(c for c in f.columns if c.startswith("Amoni"))
        for _, r in f.iterrows():
            m = re.search(r"T(\d{1,2})", str(r["Kí_hiệu"]))
            rows.append({"Station": r["NB"], "year": year, "month": int(m.group(1)) if m else None,
                         "tide": r["Tide"], "tan": pd.to_numeric(r[col], errors="coerce")})
    out = pd.DataFrame(rows).dropna(subset=["tan", "month"])
    return out[out["Station"].isin(CAGE_STATIONS)]


def likelihood_table(raw_level: float, sets: dict[str, np.ndarray]) -> pd.DataFrame:
    rows = []
    n_level, ion_level = raw_level * UNIT_SCALE, raw_level * UNIT_SCALE * N_FACTOR_ION
    for name, samples in sets.items():
        samples = samples[np.isfinite(samples) & (samples > 0)]
        if samples.size < 4:
            continue
        bf = bootstrap_bayes_factor(n_level, ion_level, samples)
        k = implied_scale(raw_level, samples)
        rows.append({"reference": name, **bf,
                     "prov_median": float(np.median(samples)), "prov_p10": float(np.quantile(samples, 0.1)),
                     "prov_p90": float(np.quantile(samples, 0.9)),
                     "pct_rank_N": float(np.mean(samples <= n_level)), "pct_rank_ion": float(np.mean(samples <= ion_level)),
                     "P_N_given_equal_prior": bf["bf"] / (1 + bf["bf"]),
                     **k, "k_ratio_to_0.001": k["k_hat"] / UNIT_SCALE})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- figures

def figures(out: Path, prov: pd.DataFrame, tide: pd.DataFrame | None, daily: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4.2))
    groups = [("Tỉnh HP, NB1/2/25/27, T6–8, 2023–24", prov.query("month in @SUMMER_MONTHS and year in @RECENT_YEARS")["tan"])]
    if tide is not None:
        summer = tide.query("month in @SUMMER_MONTHS and year in @RECENT_YEARS")
        groups += [("… chân triều (CT)", summer.query("tide == 'CT'")["tan"]),
                   ("… đỉnh triều (ĐT)", summer.query("tide == 'ĐT'")["tan"])]
    groups += [("Cảm biến ×0,001 (N, hệ số 1,0)", daily["tan_n"]), ("Cảm biến ×0,001×0,7766 (ion)", daily["tan_ion"])]
    for i, (label, vals) in enumerate(groups):
        vals = np.asarray(vals, dtype=float)
        jitter = np.random.default_rng(i).uniform(-0.15, 0.15, vals.size)
        ax.scatter(vals, np.full(vals.size, i) + jitter, s=14, alpha=0.6, color="#4C72B0" if i < len(groups) - 2 else "#C44E52")
        ax.plot([np.median(vals)] * 2, [i - 0.3, i + 0.3], color="black", lw=2)
    ax.axvline(QCVN_B1, color="grey", ls="--", lw=1)
    ax.text(QCVN_B1, len(groups) - 0.4, " QCVN B1 0,1", color="grey", fontsize=8)
    ax.set_yticks(range(len(groups)), [g[0] for g in groups], fontsize=8)
    ax.set_xscale("log")
    ax.set_xlabel("Amoni theo N (mg/L, thang log)")
    ax.set_title("Mức cảm biến trước 31/07 (trung vị ngày) so với số liệu tỉnh gần lồng")
    fig.tight_layout()
    fig.savefig(out / "fig_distribution.png", dpi=130)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 3.6))
    x = pd.to_datetime(daily.index)
    ax.fill_between(x, daily["tan_ion"], daily["tan_n"], color="#C44E52", alpha=0.25, label="khoảng ion (0,7766) – N (1,0)")
    ax.plot(x, daily["tan_n"], color="#C44E52", lw=1)
    ax.axhline(QCVN_B1, color="grey", ls="--", lw=1, label="QCVN 10:2023 B1 0,1 mg/L")
    ax.set_ylabel("TAN (mg/L N)")
    ax.set_title("TAN theo ngày trước bậc 31/07 dưới hai giả định cơ sở (đơn vị µg/L giả định)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "fig_daily_band.png", dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-name", default="nh4-basis-evidence-20261026")
    parser.add_argument("--hp-raw-dir", type=Path, default=None,
                        help="read-only folder with per-tide provincial CSVs hp_2020.csv … hp_2024.csv")
    args = parser.parse_args(argv)

    out = paths.EXPERIMENT_OUTPUT_DIR / args.run_name
    out.mkdir(parents=True, exist_ok=False)
    inputs = Inputs()

    units = unit_audit(inputs)
    units.to_csv(out / "vendor_unit_labels.csv", index=False)

    native = native_exports(inputs)
    native_table = forensics_native(native)
    native_table.to_csv(out / "native_forensics.csv", index=False)

    hist = load_history(inputs)
    resp = response_forensics(hist)
    resp.to_csv(out / "response_forensics.csv", index=False)
    sal = salinity_link(inputs, hist, native)
    sal.to_csv(out / "salinity_link.csv", index=False)

    pre = hist[hist["regime"] == "pre"].copy()
    pre["day"] = pre["t"].dt.date
    daily = pre.groupby("day")["NH4"].median().to_frame("raw")
    daily = daily[daily.index < STEP.date()]          # whole pre-step days only
    daily["tan_n"] = daily["raw"] * UNIT_SCALE
    daily["tan_ion"] = daily["tan_n"] * N_FACTOR_ION
    daily["qcvn_band"] = qcvn_band(daily["tan_n"], daily["tan_ion"])
    daily.to_csv(out / "daily_pre_step.csv")
    raw_level = float(daily["raw"].median())

    prov = provincial_samples(inputs)
    tide = provincial_tide_samples(inputs, args.hp_raw_dir)
    sets = {
        "clean HP cage stations, T6–8, 2023–24 (tide-mean)": prov.query("month in @SUMMER_MONTHS and year in @RECENT_YEARS")["tan"].to_numpy(),
        "clean HP cage stations, T6–8, 2020–24": prov.query("month in @SUMMER_MONTHS")["tan"].to_numpy(),
        "clean HP cage stations, all months, 2023–24": prov.query("year in @RECENT_YEARS")["tan"].to_numpy(),
        "clean NB1 only, all years": prov.query("Station == 'NB1'")["tan"].to_numpy(),
    }
    if tide is not None:
        summer = tide.query("month in @SUMMER_MONTHS and year in @RECENT_YEARS")
        sets["raw HP per-tide, T6–8, 2023–24, CT+ĐT"] = summer["tan"].to_numpy()
        sets["raw HP per-tide, T6–8, 2023–24, CT (chân triều)"] = summer.query("tide == 'CT'")["tan"].to_numpy()
        sets["raw HP per-tide, T6–8, 2023–24, ĐT (đỉnh triều)"] = summer.query("tide == 'ĐT'")["tan"].to_numpy()
        tide.to_csv(out / "provincial_tide_samples.csv", index=False)
    lik = likelihood_table(raw_level, sets)
    lik.to_csv(out / "likelihood_basis.csv", index=False)
    pd.DataFrame(LITERATURE).to_csv(out / "literature_ranges.csv", index=False)

    interference = pd.DataFrame([
        {"salinity": s, "log_k_k": kk, "log_k_na": kn,
         "apparent_mg_N": ise_interference_mg_n(s, kk, kn),
         "apparent_mg_NH4": ise_interference_mg_n(s, kk, kn) * NH4_MASS / N_MASS}
        for s in (20.0, 33.0) for kk in (-0.9, -1.2) for kn in (-2.4, -3.0)])
    interference.to_csv(out / "ise_interference_estimate.csv", index=False)

    lit_lo, lit_hi = min(r["lo"] for r in LITERATURE), max(r["hi"] for r in LITERATURE)
    post = hist[hist["regime"] == "post"]
    summary = {
        "station": STATION, "step_local": str(STEP), "unit_scale_assumed": UNIT_SCALE, "n_factor_ion": N_FACTOR_ION,
        "vendor_unit_labels": units.to_dict(orient="records"),
        "pre_step": {"days": int(len(daily)), "raw_median_of_daily": raw_level,
                     "tan_n_median": raw_level * UNIT_SCALE, "tan_ion_median": raw_level * UNIT_SCALE * N_FACTOR_ION,
                     "days_over_qcvn_n": int((daily["tan_n"] > QCVN_B1).sum()),
                     "days_over_qcvn_ion": int((daily["tan_ion"] > QCVN_B1).sum()),
                     "qcvn_band_counts": daily["qcvn_band"].value_counts().to_dict(),
                     "inside_literature_range_n": bool(lit_lo <= raw_level * UNIT_SCALE <= lit_hi),
                     "inside_literature_range_ion": bool(lit_lo <= raw_level * UNIT_SCALE * N_FACTOR_ION <= lit_hi)},
        "post_step": {"raw_p05": float(post["NH4"].quantile(0.05)), "raw_median": float(post["NH4"].median()),
                      "raw_p95": float(post["NH4"].quantile(0.95))},
        "likelihood": lik.to_dict(orient="records"),
        "response_forensics": resp.to_dict(orient="records"),
        "salinity_link": sal.to_dict(orient="records"),
        "ise_interference_estimate": interference.round(2).to_dict(orient="records"),
        "native_forensics": native_table.to_dict(orient="records"),
        "hp_raw_dir": str(args.hp_raw_dir) if args.hp_raw_dir else None,
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    figures(out, prov, tide, daily)
    (out / "manifest.json").write_text(json.dumps({
        "script": "experiments/nh4_basis_evidence.py", "run_name": args.run_name, "seed": SEED, "n_boot": N_BOOT,
        "inputs": inputs.manifest(),
        "outputs": sorted(p.name for p in out.iterdir()),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(units.to_string(index=False))
    print(native_table.to_string(index=False))
    print(resp.to_string(index=False))
    print(sal.to_string(index=False))
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(lik.round(4).to_string(index=False))
    print(interference.round(2).to_string(index=False))
    print(json.dumps(summary["pre_step"], ensure_ascii=False, indent=1))
    print(json.dumps(summary["post_step"], indent=1))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
