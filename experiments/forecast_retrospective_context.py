"""Prepare explicitly non-causal historical CHIRPS/GLORYS context features.

These helpers are intentionally separate from ``forecast_external_context``.
Their output carries an exploratory label and a conservative availability
delay, preventing reanalysis from being accidentally reported as as-issued
forecast evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def chirps_antecedent(csv_path: Path, *, date_column: str = "date", precipitation_column: str = "precipitation", availability_delay_days: int = 2) -> pd.DataFrame:
    """Build prior-completed-day rainfall features from a locally downloaded CHIRPS v3 CSV."""
    source = pd.read_csv(csv_path)
    if date_column not in source or precipitation_column not in source:
        raise ValueError("chirps_csv_requires_date_and_precipitation")
    source["date"] = pd.to_datetime(source[date_column], utc=True).dt.floor("D")
    rain = source.groupby("date", as_index=True)[precipitation_column].mean().sort_index().rename("chirps_precipitation")
    # Shift first: values in a row are never the same day's observed rainfall.
    delayed = rain.shift(availability_delay_days)
    out = pd.DataFrame(index=rain.index)
    for days in (1, 3, 7, 14):
        out[f"chirps_rain_sum_{days}d"] = delayed.rolling(days, min_periods=days).sum()
    out["chirps_dry_days_7d"] = delayed.eq(0).rolling(7, min_periods=7).sum()
    out["context_kind"] = "retrospective_exploratory"
    out["provider"] = "CHIRPS_v3"
    out["availability_delay_days"] = availability_delay_days
    return out.reset_index().rename(columns={"index": "available_date"})


def write_context_manifest(output: Path, *, source: Path, provider: str, product: str, exploratory: bool = True) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"provider": provider, "product": product, "source": str(source), "exploratory_only": exploratory, "allowed_in_as_issued_b5": False}, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("chirps_csv", type=Path); parser.add_argument("--output", type=Path, required=True); parser.add_argument("--delay-days", type=int, default=2)
    args = parser.parse_args(); result = chirps_antecedent(args.chirps_csv, availability_delay_days=args.delay_days); args.output.parent.mkdir(parents=True, exist_ok=True); result.to_csv(args.output, index=False); write_context_manifest(args.output.with_suffix(".manifest.json"), source=args.chirps_csv, provider="CHIRPS_v3", product="antecedent_rain")


if __name__ == "__main__":
    main()
