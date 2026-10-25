"""Small CMEMS ocean-colour subsets around NB1 + a usability summary (write-once).

Products (Copernicus-GlobColour, daily L3, multi-year incl. interim extension):
  OCEANCOLOUR_GLO_BGC_L3_MY_009_103
    cmems_obs-oc_glo_bgc-plankton_my_l3-multi-4km_P1D   CHL           ~4 km
    cmems_obs-oc_glo_bgc-transp_my_l3-multi-4km_P1D     KD490 SPM ZSD ~4 km
    cmems_obs-oc_glo_bgc-plankton_my_l3-olci-300m_P1D   CHL           ~300 m (OLCI only)
There is no 300 m transparency/SPM dataset; a 300 m turbidity proxy would need the
reflectance dataset plus an own algorithm.

Output: ``paths.VN_PUBLIC_DIR/cmems_oceancolour/<name>.nc`` (+ manifest) and, per variable,
``derived/<name>__<var>__usability.csv`` (per-pixel valid fraction, distance to NB1) and
``derived/<name>__<var>__nb1_series.csv`` (daily series of the nearest pixel with
>= MIN_VALID valid days). Existing files are skipped, never overwritten.

Needs the copernicusmarine toolbox with credentials already configured on the machine (free
CMEMS account); the credentials are read by the toolbox and never printed or copied here.
Usage: python scripts/vn_public/fetch_ocean_colour.py [--start 2023-01-01] [--end 2026-10-17] [--dry-run]
"""
from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core import paths  # noqa: E402
from scripts.vn_public.common import (  # noqa: E402
    NB1_LAT, NB1_LON, haversine_km, write_manifest, write_once_bytes,
)

PRODUCT = "OCEANCOLOUR_GLO_BGC_L3_MY_009_103"
MIN_VALID = 0.05  # a pixel is "usable" if >= 5 % of days have a value


@dataclass(frozen=True)
class Subset:
    name: str
    dataset_id: str
    variables: tuple[str, ...]
    bbox: tuple[float, float, float, float]  # min_lon, min_lat, max_lon, max_lat


SUBSETS = [
    Subset("oc_chl_4km", "cmems_obs-oc_glo_bgc-plankton_my_l3-multi-4km_P1D", ("CHL",),
           (106.8, 20.55, 107.35, 20.95)),  # same bbox as data/cmems extracts
    Subset("oc_transp_4km", "cmems_obs-oc_glo_bgc-transp_my_l3-multi-4km_P1D", ("KD490", "SPM", "ZSD"),
           (106.8, 20.55, 107.35, 20.95)),
    Subset("oc_chl_olci300m", "cmems_obs-oc_glo_bgc-plankton_my_l3-olci-300m_P1D", ("CHL",),
           (NB1_LON - 0.1, NB1_LAT - 0.1, NB1_LON + 0.1, NB1_LAT + 0.1)),
]


def pixel_usability(da, lat0: float = NB1_LAT, lon0: float = NB1_LON) -> pd.DataFrame:
    """Per-pixel valid fraction over time and distance to (lat0, lon0), nearest first.

    ``da`` is an xarray DataArray with dims (time, latitude, longitude).
    """
    valid = np.isfinite(da.values)  # (t, y, x)
    frac = valid.mean(axis=0)
    n = valid.sum(axis=0)
    lats, lons = da["latitude"].values, da["longitude"].values
    rows = []
    for i, la in enumerate(lats):
        for j, lo in enumerate(lons):
            rows.append({"lat": float(la), "lon": float(lo), "valid_days": int(n[i, j]),
                         "valid_frac": round(float(frac[i, j]), 4),
                         "dist_km": round(haversine_km(lat0, lon0, float(la), float(lo)), 3)})
    return pd.DataFrame(rows).sort_values(["dist_km", "lat", "lon"]).reset_index(drop=True)


def nearest_usable(usability: pd.DataFrame, min_valid: float = MIN_VALID) -> pd.Series | None:
    ok = usability[usability["valid_frac"] >= min_valid]
    return None if ok.empty else ok.iloc[0]


def _csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False, lineterminator="\n")
    return buf.getvalue().encode("utf-8")


def summarise(nc: Path, sub: Subset, out_dir: Path) -> list[str]:
    import xarray as xr

    lines = []
    with xr.open_dataset(nc) as ds:
        for var in sub.variables:
            da = ds[var].load()
            use = pixel_usability(da)
            best = nearest_usable(use)
            base = f"{sub.name}__{var}"
            targets = {out_dir / f"{base}__usability.csv": _csv_bytes(use)}
            if best is not None:
                s = da.sel(latitude=best["lat"], longitude=best["lon"]).to_series().dropna()
                ser = pd.DataFrame({"date": s.index.strftime("%Y-%m-%d"), var: s.values.round(5),
                                    "pixel_lat": best["lat"], "pixel_lon": best["lon"],
                                    "pixel_dist_nb1_km": best["dist_km"]})
                targets[out_dir / f"{base}__nb1_series.csv"] = _csv_bytes(ser)
            for target, data in targets.items():
                if target.exists():
                    continue
                write_once_bytes(target, data)
                write_manifest(target, url=f"derived from {nc.name}", product_id=PRODUCT,
                               dataset_id=sub.dataset_id, variable=var, min_valid_frac=MIN_VALID,
                               terms="Copernicus Marine Service licence (free, attribution)")
            near = use.iloc[0]
            lines.append(
                f"{base}: nearest pixel {near.dist_km:.2f} km valid {near.valid_frac:.1%}; "
                + (f"nearest usable (>={MIN_VALID:.0%}) {best.dist_km:.2f} km valid {best.valid_frac:.1%} "
                   f"({int(best.valid_days)} days)" if best is not None else "no usable pixel")
                + f"; pixels usable {int((use.valid_frac >= MIN_VALID).sum())}/{len(use)}")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2026-10-17")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import copernicusmarine as cm

    out = paths.VN_PUBLIC_DIR / "cmems_oceancolour"
    derived = out / "derived"
    for sub in SUBSETS:
        b = sub.bbox
        fname = (f"{sub.name}__{sub.dataset_id}__{'-'.join(sub.variables)}__"
                 f"{b[0]:.3f}_{b[1]:.3f}_{b[2]:.3f}_{b[3]:.3f}__{args.start.replace('-', '')}_{args.end.replace('-', '')}.nc")
        nc = out / fname
        query = dict(dataset_id=sub.dataset_id, variables=list(sub.variables),
                     minimum_longitude=b[0], minimum_latitude=b[1], maximum_longitude=b[2], maximum_latitude=b[3],
                     start_datetime=f"{args.start}T00:00:00", end_datetime=f"{args.end}T23:59:59")
        if not nc.exists():
            if args.dry_run:
                print("would fetch", fname, query)
                continue
            out.mkdir(parents=True, exist_ok=True)
            cm.subset(**query, output_directory=str(out), output_filename=fname, disable_progress_bar=True)
            write_manifest(nc, product_id=PRODUCT, dataset_id=sub.dataset_id, variables=list(sub.variables),
                           bbox_lon_lat=list(b), start=args.start, end=args.end,
                           query={k: v for k, v in query.items()},
                           toolbox=f"copernicusmarine {getattr(cm, '__version__', '?')}",
                           url=f"https://data.marine.copernicus.eu/product/{PRODUCT}",
                           terms="Copernicus Marine Service licence: free, registration, attribution required",
                           used_by_alerts=False, basis="observation (satellite L3), context only")
            print("fetched", nc, nc.stat().st_size, "B")
        else:
            print("exists", nc.name)
        for line in summarise(nc, sub, derived):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
