# lab/realtime_greenlab/report.py
"""CLI: fetch → QC → monitor → impute → classify → print.

Chạy từ repo root:
    python lab/realtime_greenlab/report.py --station 06M26042804
    python lab/realtime_greenlab/report.py --station 06M26042804 --date 2026-06-01
    python lab/realtime_greenlab/report.py --station 06M26042804 --monitor-only
    python lab/realtime_greenlab/report.py --all-coastal
"""
import argparse
import sys
from datetime import date
from pathlib import Path

# Thêm gốc repo vào sys.path để có thể chạy script trực tiếp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from core.config import STATIONS, COASTAL_STATIONS, REGION_SPECIES
from core.fetch import fetch_daily
from core.monitor import check_params
from core.classify import classify_station

_ICON = {"OK": "OK ", "EXCEED": "!! "}

# params đo trực tiếp (COD chỉ thêm khi sensor ngày đó VALID)
_MEASURED_BASE = ["NH3", "pH", "Temperature", "TSS"]


def _build_measured(day_row) -> dict:
    m = {}
    for p in _MEASURED_BASE:
        v = day_row[p]
        if v == v:   # not NaN
            m[p] = round(float(v), 4)
    if day_row.get("cod_status") == "VALID":
        cod = day_row["COD"]
        if cod == cod:
            m["COD"] = round(float(cod), 4)
    return m


def run_station(serial: str, target_date: date = None, monitor_only: bool = False):
    info = STATIONS.get(serial, {"name_vi": serial, "region": None})
    region = info.get("region") or "haiphong"
    species = REGION_SPECIES.get(region, "cobia")

    daily = fetch_daily(serial)
    if daily.empty:
        print(f"[{serial}] No data.")
        return

    if target_date is not None:
        sel = daily[daily["date"] == target_date]
        day_row = sel.iloc[0] if len(sel) else daily.iloc[-1]
    else:
        day_row = daily.iloc[-1]
    day = day_row["date"]

    measured = _build_measured(day_row)

    print(f"\n{'='*56}")
    print(f" GreenLab Report — {info.get('name_vi', serial)} ({serial})")
    print(f" Ngày: {day} | n_readings: {int(day_row['n_readings'])} | COD sensor: {day_row['cod_status']}")
    print(f"{'='*56}")

    print("\n[MONITORING — QCVN 10:2023/BTNMT B1]")
    for p, st in check_params(measured).items():
        print(f"  {_ICON[st.status]}{p:<12}{st.value:>10.4f}  (QCVN {st.limit_str()})")

    if monitor_only:
        return

    print(f"\n[CLASSIFICATION — {species.upper()} | vùng {region}]")
    r = classify_station(serial, measured, species, date=str(day), region=region)
    print(f"  Score: {r['score']:.3f}  →  {r['label']}")
    print(f"  feature_set: {r['feature_set']} | imputed_fraction: {r['imputed_fraction']:.0%}")
    print(f"  ! {r['warning']}")
    conf = r.get("confidence", {})
    _CMARK = {"strong": " (mạnh)", "weak": " (yếu)"}
    print("\n  Params (mẫu):")
    for grp, params in r["params"].items():
        items = list(params.items())
        shown = ", ".join(
            f"{k}={v}{_CMARK.get(conf.get(k), '') if grp == 'imputed' else ''}"
            for k, v in items[:4])
        more = f" (+{len(items)-4})" if len(items) > 4 else ""
        print(f"    [{grp:<9}] {shown}{more}")


def main():
    ap = argparse.ArgumentParser(description="GreenLab realtime suitability report")
    ap.add_argument("--station")
    ap.add_argument("--date", help="YYYY-MM-DD (default: ngày mới nhất)")
    ap.add_argument("--monitor-only", action="store_true")
    ap.add_argument("--all-coastal", action="store_true")
    args = ap.parse_args()

    td = date.fromisoformat(args.date) if args.date else None
    if args.all_coastal:
        for s in COASTAL_STATIONS:
            run_station(s, td, args.monitor_only)
    elif args.station:
        run_station(args.station, td, args.monitor_only)
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
