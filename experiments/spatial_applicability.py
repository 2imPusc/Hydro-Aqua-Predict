"""P0 audit and historical benchmark for spatial applicability.

This module intentionally stays outside ``core/``.  It establishes evidence
for transferring an anchor-station value to another location; it does not
produce realtime map values or alert evidence.

The legacy HSI-radius rule is recreated only as an *observed-HSI diagnostic*.
It reads target-location observations for the same period, therefore it is
explicitly labelled non-operational and must never be used as a live radius.
The anchor-copy baseline, in contrast, evaluates the actual error incurred by
representing a target station with its anchor.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import paths  # noqa: E402

REGION_PATHS = {
    "haiphong": paths.clean_data("haiphong"),
    "quangninh": paths.clean_data("quangninh"),
}
COBIA_RULES = {
    "DO": ("min", 6.0), "Temperature": ("range", 24.0, 28.0),
    "pH": ("range", 8.0, 8.5), "Salinity": ("range", 27.0, 33.0),
    "NH3": ("max", 0.1), "TSS": ("max", 50.0),
}
RISK_RULES = {"DO": (3.0, "below"), "Salinity": (20.0, "below"), "NH3": (0.05, "above")}
HSI_BINS = [0.0, .5, 1.0, 2.0, 5.0]
WATER_MASK = paths.WATER_SHAPEFILE
CMEMS_CACHE = paths.CMEMS_CACHE_DIR


def file_sha256(path: Path) -> str | None:
    """Return a content hash for an immutable experiment manifest."""
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def context_availability() -> dict:
    """Declare, rather than infer, what independent map context is available.

    No missing field is synthesized.  In particular, thetao/so are not
    mislabeled as currents, sea-surface height, or mixed-layer depth.
    """
    fields = {"thetao": False, "so": False, "uo": False, "vo": False, "zos": False, "mlotst": False}
    files = []
    for path in sorted(CMEMS_CACHE.glob("*.nc")) if CMEMS_CACHE.exists() else []:
        variables: list[str] = []
        try:
            import xarray as xr
            with xr.open_dataset(path) as dataset:
                variables = sorted(dataset.data_vars)
        except Exception:
            variables = ["unreadable"]
        for name in fields:
            fields[name] = fields[name] or name in variables
        files.append({"path": str(path), "sha256": file_sha256(path), "variables": variables})
    return {
        "scope": "historical_research_only",
        "water_mask": {"available": WATER_MASK.exists(), "path": str(WATER_MASK), "sha256": file_sha256(WATER_MASK)},
        "bathymetry": {"available": False, "reason_code": "no_verified_gebco_or_equivalent_source_cached"},
        "cmems": {"files": files, "fields_available": fields,
                  "required_for_current_overlay": ["uo", "vo"],
                  "required_for_ssh_overlay": ["zos"],
                  "required_for_mld_overlay": ["mlotst"]},
    }


def distance_km(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance for projected VN-2000 coordinates, in kilometres."""
    return float(np.hypot(float(x1) - float(x2), float(y1) - float(y2)) / 1000.0)


def prepare_source(source: pd.DataFrame) -> pd.DataFrame:
    required = {"Station", "Quarter", "X", "Y"}
    missing = required - set(source.columns)
    if missing:
        raise ValueError(f"historical source missing: {sorted(missing)}")
    frame = source.copy()
    frame["Station"] = frame["Station"].astype(str)
    frame["observed_at"] = pd.to_datetime(frame["Quarter"], utc=True, errors="coerce")
    frame["X"] = pd.to_numeric(frame["X"], errors="coerce")
    frame["Y"] = pd.to_numeric(frame["Y"], errors="coerce")
    frame = frame.dropna(subset=["Station", "observed_at", "X", "Y"]).copy()
    return frame


def station_catalog(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return one coordinate row per station and coordinate consistency findings."""
    grouped = frame.groupby("Station", sort=True)
    catalog = grouped.agg(
        x=("X", "median"), y=("Y", "median"), n_records=("Station", "size"),
        n_periods=("observed_at", "nunique"), n_x=("X", "nunique"), n_y=("Y", "nunique"),
    ).reset_index().rename(columns={"Station": "station"})
    catalog["coordinate_consistent"] = (catalog.n_x == 1) & (catalog.n_y == 1)
    findings = catalog.loc[~catalog.coordinate_consistent, ["station", "n_x", "n_y"]].copy()
    return catalog, findings


def cobia_hsi(row: pd.Series) -> float:
    """Small, explicit reproduction of the existing cobia HSI scoring shape."""
    scores: list[float] = []
    for name, rule in COBIA_RULES.items():
        value = pd.to_numeric(row.get(name), errors="coerce")
        if pd.isna(value):
            continue
        if rule[0] == "range":
            low, high = rule[1], rule[2]
            score = value / low if value < low else (2 * high - value) / high if value > high else 1.0
        elif rule[0] == "min":
            score = min(1.0, value / rule[1])
        else:
            score = 1.0 - value / rule[1]
        scores.append(float(np.clip(score, 0.0, 1.0)))
    return float(np.mean(scores)) if scores else np.nan


def hsi_label(value: float) -> str:
    if value >= .85:
        return "very_suitable"
    if value >= .75:
        return "suitable"
    if value >= .5:
        return "less_suitable"
    return "not_suitable"


def legacy_local_radius(period: pd.DataFrame, anchor: str, *, max_dist_km: float = 30.0, bin_km: float = 1.0, alpha: float = .6) -> float:
    """Exact decision structure of aqua-forecast's old local-R rule."""
    center = period.loc[period.Station.eq(anchor)]
    if len(center) != 1 or period.hsi.isna().all():
        return np.nan
    center = center.iloc[0]
    sigma = period.hsi.std()
    if not np.isfinite(sigma) or sigma == 0:
        return np.nan
    records = []
    for neighbour in period.itertuples(index=False):
        if neighbour.Station == anchor or not np.isfinite(neighbour.hsi):
            continue
        dist = distance_km(center.X, center.Y, neighbour.X, neighbour.Y)
        if dist <= max_dist_km:
            records.append((dist, abs(center.hsi - neighbour.hsi), hsi_label(neighbour.hsi)))
    if not records:
        return np.nan
    neighbours = pd.DataFrame(records, columns=["distance_km", "delta_hsi", "label"])
    bins = np.arange(0, max_dist_km + bin_km, bin_km)
    neighbours["bin"] = pd.cut(neighbours.distance_km, bins=bins, include_lowest=True)
    result = 0.0
    anchor_label = hsi_label(center.hsi)
    for interval, group in neighbours.groupby("bin", observed=True):
        if group.delta_hsi.mean() >= alpha * sigma or (group.label != anchor_label).any():
            break
        result = float(interval.right)
    return min(max_dist_km, max(result, .5))


def pairwise_anchor_copy(frame: pd.DataFrame, target: str) -> pd.DataFrame:
    """Pair simultaneous station observations; prediction is simply anchor value."""
    if target not in frame.columns:
        return pd.DataFrame()
    subset = frame[["Station", "observed_at", "X", "Y", target]].copy()
    subset[target] = pd.to_numeric(subset[target], errors="coerce")
    subset = subset.dropna(subset=[target])
    records: list[dict] = []
    for observed_at, group in subset.groupby("observed_at", sort=True):
        rows = list(group.itertuples(index=False))
        for left, right in combinations(rows, 2):
            for anchor, destination in ((left, right), (right, left)):
                records.append({
                    "observed_at": observed_at, "parameter": target,
                    "anchor_station": anchor.Station, "target_station": destination.Station,
                    "distance_km": distance_km(anchor.X, anchor.Y, destination.X, destination.Y),
                    "anchor_value": float(getattr(anchor, target)), "actual": float(getattr(destination, target)),
                })
    pairs = pd.DataFrame(records)
    if pairs.empty:
        return pairs
    pairs["predicted"] = pairs.anchor_value
    pairs["absolute_error"] = (pairs.predicted - pairs.actual).abs()
    pairs["distance_bin_km"] = pd.cut(pairs.distance_km, bins=[0, .5, 1, 2, 5, 10, 20, np.inf], include_lowest=True)
    return pairs


def hsi_water_path_pairs(frame: pd.DataFrame, *, max_distance_km: float = 5.0) -> pd.DataFrame:
    """Held-out HSI transfer pairs using only water-traversable distance."""
    from core.spatial_overlay import water_path_distances
    coordinates = pd.read_csv(paths.STATION_COORDINATES, usecols=["Station", "Lat", "Lon"])
    work = frame.copy()
    work["hsi"] = work.apply(cobia_hsi, axis=1)
    work = work.dropna(subset=["hsi"]).merge(coordinates, on="Station", how="inner", validate="many_to_one")
    station_points = coordinates.set_index("Station")
    distance_lookup: dict[tuple[str, str], float] = {}
    for anchor, anchor_point in station_points.iterrows():
        targets = station_points.drop(index=anchor).reset_index()
        distances = water_path_distances(float(anchor_point.Lon), float(anchor_point.Lat), targets, max_distance_km=max_distance_km)
        for index, target in targets.iterrows():
            if np.isfinite(distances.loc[index]) and distances.loc[index] <= max_distance_km:
                distance_lookup[(str(anchor), str(target.Station))] = float(distances.loc[index])
    records: list[dict] = []
    for observed_at, period in work.groupby("observed_at", sort=True):
        period = period.drop_duplicates("Station").reset_index(drop=True)
        for anchor in sorted(period.Station.unique()):
            anchor_row = period.loc[period.Station.eq(anchor)].iloc[0]
            targets = period.loc[~period.Station.eq(anchor), ["Station", "hsi"]].copy()
            for _index, target in targets.iterrows():
                water_distance = distance_lookup.get((str(anchor), str(target.Station)))
                if water_distance is None:
                    continue
                anchor_label, target_label = hsi_label(float(anchor_row.hsi)), hsi_label(float(target.hsi))
                records.append({"observed_at": observed_at, "parameter": "HSI", "anchor_station": anchor,
                                "target_station": str(target.Station), "distance_km": water_distance,
                                "anchor_value": float(anchor_row.hsi), "actual": float(target.hsi),
                                "anchor_hsi_label": anchor_label, "target_hsi_label": target_label,
                                "same_hsi_label": anchor_label == target_label,
                                "false_favourable": anchor_label in {"very_suitable", "suitable"} and target_label not in {"very_suitable", "suitable"}})
    pairs = pd.DataFrame(records)
    if pairs.empty:
        return pairs
    pairs["predicted"] = pairs.anchor_value
    pairs["absolute_error"] = (pairs.predicted - pairs.actual).abs()
    pairs["distance_bin_km"] = pd.cut(pairs.distance_km, bins=HSI_BINS, include_lowest=True)
    return pairs


def hsi_label_diagnostics(predictions: pd.DataFrame) -> pd.DataFrame:
    """Classification diagnostics never used as an inference feature or gate."""
    if predictions.empty:
        return pd.DataFrame()
    from sklearn.metrics import f1_score
    rows = []
    for split, part in predictions.groupby("split"):
        rows.append({"split": split, "parameter": "HSI", "n_pairs": len(part),
                     "label_agreement": float((part.anchor_hsi_label == part.target_hsi_label).mean()),
                     "macro_f1": float(f1_score(part.target_hsi_label, part.anchor_hsi_label, average="macro", zero_division=0)),
                     "false_favourable_rate": float(part.false_favourable.mean())})
    return pd.DataFrame(rows)


def metric_summary(pairs: pd.DataFrame, target: str) -> pd.DataFrame:
    if pairs.empty:
        return pd.DataFrame()
    risk = RISK_RULES.get(target)
    rows = []
    for distance_bin, part in pairs.groupby("distance_bin_km", observed=True):
        error = part.predicted - part.actual
        row = {
            "parameter": target, "distance_bin_km": str(distance_bin), "n_pairs": len(part),
            "mae": float(error.abs().mean()), "rmse": float(np.sqrt(np.mean(error ** 2))),
            "bias": float(error.mean()), "p95_absolute_error": float(error.abs().quantile(.95)),
        }
        if risk:
            threshold, direction = risk
            actual_risk = part.actual <= threshold if direction == "below" else part.actual >= threshold
            predicted_risk = part.predicted <= threshold if direction == "below" else part.predicted >= threshold
            tp, fn = int((actual_risk & predicted_risk).sum()), int((actual_risk & ~predicted_risk).sum())
            row["risk_recall"] = tp / (tp + fn) if tp + fn else np.nan
            row["risk_false_negative"] = fn
        rows.append(row)
    return pd.DataFrame(rows)


def error_bound_features(pairs: pd.DataFrame) -> pd.DataFrame:
    """Features available when only the anchor observation is known.

    No target value, target identifier, HSI label, or future timestamp is used
    as a feature.  This is the input contract for a future map cell.
    """
    work = pairs.copy()
    month = pd.to_datetime(work["observed_at"], utc=True).dt.month
    return pd.DataFrame({
        "distance_km": work.distance_km.to_numpy(float),
        "anchor_value": work.anchor_value.to_numpy(float),
        "month_sin": np.sin(2 * np.pi * month / 12),
        "month_cos": np.cos(2 * np.pi * month / 12),
    }, index=work.index)


def _fit_quantile_bound(train: pd.DataFrame, calibration: pd.DataFrame, test: pd.DataFrame, *, coverage: float) -> pd.DataFrame:
    """Fit a fast distance-bin quantile bound then conformally calibrate it.

    This is the deliberately simple P1 baseline.  It is transparent and cheap
    enough to run across every leave-target-station-out fold.  A nonlinear
    model may replace it only if it beats this bound on both outer protocols.
    """
    global_bound = float(np.quantile(train.absolute_error, coverage))
    per_bin = train.groupby("distance_bin_km", observed=True).absolute_error.agg(
        lambda values: float(np.quantile(values, coverage)) if len(values) >= 20 else global_bound
    )

    def predict_bound(frame: pd.DataFrame) -> np.ndarray:
        return np.asarray([per_bin.get(value, global_bound) for value in frame.distance_bin_km], dtype=float)

    calibration_bound = predict_bound(calibration)
    # Split-conformal correction makes the stated bound empirically checkable.
    correction = float(np.quantile(calibration.absolute_error.to_numpy(float) - calibration_bound, coverage, method="higher"))
    correction = max(0.0, correction)
    output = test.copy()
    output["model_bound"] = np.maximum(0.0, predict_bound(test) + correction)
    output["fixed_calibration_bound"] = float(np.quantile(calibration.absolute_error, coverage))
    output["conformal_correction"] = correction
    output["coverage_target"] = coverage
    return output


def _bound_metrics(predictions: pd.DataFrame, *, split: str, parameter: str, coverage: float) -> list[dict]:
    rows = []
    for model, column in (("distance_bin_quantile_conformal", "model_bound"), ("fixed_calibration_quantile", "fixed_calibration_bound")):
        for distance_bin, part in predictions.groupby("distance_bin_km", observed=True):
            rows.append({
                "split": split, "parameter": parameter, "model": model,
                "distance_bin_km": str(distance_bin), "n_pairs": int(len(part)),
                "coverage_target": coverage, "empirical_coverage": float((part.absolute_error <= part[column]).mean()),
                "mean_bound": float(part[column].mean()), "p95_bound": float(part[column].quantile(.95)),
                "mean_absolute_error": float(part.absolute_error.mean()),
            })
    return rows


def temporal_error_bound_benchmark(pairs: pd.DataFrame, parameter: str, *, coverage: float = .9) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Forward train/calibration/test benchmark; no future period trains a model."""
    work = pairs.loc[pairs.parameter.eq(parameter)].copy()
    periods = np.array(sorted(work.observed_at.unique()))
    if len(periods) < 5:
        return pd.DataFrame(), pd.DataFrame()
    train_end, calibration_end = max(1, int(len(periods) * .6)), max(2, int(len(periods) * .8))
    train_periods, calibration_periods, test_periods = periods[:train_end], periods[train_end:calibration_end], periods[calibration_end:]
    train = work.loc[work.observed_at.isin(train_periods)]
    calibration = work.loc[work.observed_at.isin(calibration_periods)]
    test = work.loc[work.observed_at.isin(test_periods)]
    if min(len(train), len(calibration), len(test)) < 20:
        return pd.DataFrame(), pd.DataFrame()
    predictions = _fit_quantile_bound(train, calibration, test, coverage=coverage)
    predictions["split"] = "forward_temporal"
    return predictions, pd.DataFrame(_bound_metrics(predictions, split="forward_temporal", parameter=parameter, coverage=coverage))


def station_error_bound_benchmark(pairs: pd.DataFrame, parameter: str, *, coverage: float = .9) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Leave each target station out of train/calibration, then pool its results."""
    work = pairs.loc[pairs.parameter.eq(parameter)].copy()
    outputs = []
    for held_station in sorted(work.target_station.unique()):
        test = work.loc[work.target_station.eq(held_station)]
        pool = work.loc[~work.target_station.eq(held_station)].sort_values("observed_at")
        boundary = max(1, int(len(pool) * .8))
        train, calibration = pool.iloc[:boundary], pool.iloc[boundary:]
        if min(len(train), len(calibration), len(test)) < 20:
            continue
        predicted = _fit_quantile_bound(train, calibration, test, coverage=coverage)
        predicted["split"] = "leave_target_station_out"
        predicted["held_target_station"] = held_station
        outputs.append(predicted)
    if not outputs:
        return pd.DataFrame(), pd.DataFrame()
    predictions = pd.concat(outputs, ignore_index=True)
    return predictions, pd.DataFrame(_bound_metrics(predictions, split="leave_target_station_out", parameter=parameter, coverage=coverage))


def error_bound_benchmarks(pairs: pd.DataFrame, targets: list[str], *, coverages: tuple[float, ...] = (.8, .9, .95)) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run both outer protocols for each requested, predeclared coverage."""
    all_predictions, all_metrics = [], []
    for parameter in targets:
        for coverage in coverages:
            if not 0 < coverage < 1:
                raise ValueError("coverages must be strictly between 0 and 1")
            for runner in (temporal_error_bound_benchmark, station_error_bound_benchmark):
                predictions, metrics = runner(pairs, parameter, coverage=coverage)
                if not predictions.empty:
                    all_predictions.append(predictions)
                if not metrics.empty:
                    all_metrics.append(metrics)
    return (
        pd.concat(all_predictions, ignore_index=True) if all_predictions else pd.DataFrame(),
        pd.concat(all_metrics, ignore_index=True) if all_metrics else pd.DataFrame(),
    )


def wilson_lower_bound(successes: int, total: int, *, z: float = 1.96) -> float:
    """Conservative lower confidence bound for an observed coverage rate."""
    if total <= 0:
        return np.nan
    proportion = successes / total
    denominator = 1 + z ** 2 / total
    centre = proportion + z ** 2 / (2 * total)
    spread = z * np.sqrt((proportion * (1 - proportion) + z ** 2 / (4 * total)) / total)
    return float((centre - spread) / denominator)


def _distance_bin_upper(distance_bin: str) -> float:
    """Read the upper edge from the stable string emitted by pandas.cut."""
    upper = distance_bin.split(",", 1)[1].rstrip("]").strip()
    return float(upper) if upper != "inf" else np.inf


def spatial_gate_summary(metrics: pd.DataFrame, *, min_pairs: int = 30, research_max_distance_km: float = 10.0) -> pd.DataFrame:
    """Emit map-safe applicability gates; absence of evidence means reject.

    A bin is a shadow candidate only when both outer protocols have at least the
    required sample count and their 95% Wilson lower bound reaches the stated
    coverage.  This is intentionally stricter than merely observing 90% once.
    """
    required = {"split", "parameter", "model", "distance_bin_km", "n_pairs", "coverage_target", "empirical_coverage"}
    if metrics.empty or not required.issubset(metrics.columns):
        return pd.DataFrame()
    candidate = metrics.loc[metrics.model.eq("distance_bin_quantile_conformal")].copy()
    candidate["coverage_successes"] = (candidate.n_pairs * candidate.empirical_coverage).round().astype(int)
    candidate["coverage_wilson_lower_95"] = [wilson_lower_bound(success, total) for success, total in zip(candidate.coverage_successes, candidate.n_pairs)]
    rows = []
    grouped = candidate.groupby(["parameter", "coverage_target", "distance_bin_km"], sort=True)
    for (parameter, coverage, distance_bin), part in grouped:
        protocol_rows = {row.split: row for row in part.itertuples(index=False)}
        missing = {"forward_temporal", "leave_target_station_out"} - set(protocol_rows)
        reasons = []
        for split, row in protocol_rows.items():
            if row.n_pairs < min_pairs:
                reasons.append(f"{split}:insufficient_pairs")
            elif row.coverage_wilson_lower_95 < coverage:
                reasons.append(f"{split}:uncalibrated_coverage")
        if missing:
            reasons.append("missing_protocol:" + ",".join(sorted(missing)))
        if _distance_bin_upper(str(distance_bin)) > research_max_distance_km:
            reasons.append("distance_exceeds_research_cap")
        rows.append({
            "parameter": parameter, "coverage_target": coverage, "distance_bin_km": distance_bin,
            "required_protocols": "forward_temporal+leave_target_station_out", "min_pairs_required": min_pairs,
            "gate_status": "shadow_candidate" if not reasons else "not_applicable",
            "reason_codes": ";".join(reasons),
            "max_distance_interpretation": f"research_cap_{research_max_distance_km:g}_km;observed_bin:{distance_bin}",
        })
    return pd.DataFrame(rows)


def observed_hsi_radius_diagnostic(frame: pd.DataFrame, *, max_dist_km: float = 30.0, bin_km: float = 1.0, alpha: float = .6) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Recreate legacy radius with observed HSI and measure its optimistic coverage.

    This consumes same-time target values, therefore output includes
    ``diagnostic_only_observed_hsi_leakage`` and cannot be deployed.
    """
    needed = set(COBIA_RULES)
    if not needed.intersection(frame.columns):
        return pd.DataFrame(), pd.DataFrame()
    work = frame.copy()
    work["hsi"] = work.apply(cobia_hsi, axis=1)
    radius_rows, accepted_rows = [], []
    for observed_at, period in work.groupby("observed_at", sort=True):
        period = period.dropna(subset=["hsi"]).reset_index(drop=True)
        n = len(period)
        if n < 2 or not np.isfinite(period.hsi.std()) or period.hsi.std() == 0:
            continue
        x, y, hsi = period.X.to_numpy(float), period.Y.to_numpy(float), period.hsi.to_numpy(float)
        distances = np.hypot(x[:, None] - x[None, :], y[:, None] - y[None, :]) / 1000.0
        labels = np.array([hsi_label(value) for value in hsi])
        sigma = float(np.std(hsi, ddof=1))
        for index, anchor in enumerate(period.Station):
            valid = (np.arange(n) != index) & (distances[index] <= max_dist_km)
            radius = np.nan
            if valid.any():
                # Equivalent to pd.cut(..., right=True, include_lowest=True), but
                # avoids constructing 99 pandas groupbys per period.
                bins = np.maximum(0, np.ceil(distances[index, valid] / bin_km).astype(int) - 1)
                deltas = np.abs(hsi[index] - hsi[valid])
                neighbour_labels = labels[valid]
                result = 0.0
                for bin_index in np.unique(bins):
                    in_bin = bins == bin_index
                    if deltas[in_bin].mean() >= alpha * sigma or (neighbour_labels[in_bin] != labels[index]).any():
                        break
                    result = (int(bin_index) + 1) * bin_km
                radius = min(max_dist_km, max(result, .5))
            radius_rows.append({"observed_at": observed_at, "anchor_station": anchor, "radius_km": radius,
                                "method": "diagnostic_only_observed_hsi_leakage"})
            if not np.isfinite(radius):
                continue
            accepted = valid & (distances[index] <= radius)
            for target_index in np.flatnonzero(accepted):
                accepted_rows.append({"observed_at": observed_at, "anchor_station": anchor,
                    "target_station": period.Station.iloc[target_index], "distance_km": float(distances[index, target_index]),
                    "radius_km": radius, "same_hsi_label": labels[index] == labels[target_index],
                    "absolute_hsi_delta": float(abs(hsi[index] - hsi[target_index])),
                    "method": "diagnostic_only_observed_hsi_leakage"})
    return pd.DataFrame(radius_rows), pd.DataFrame(accepted_rows)


def hsi_gate_config(gates: pd.DataFrame, metrics: pd.DataFrame) -> dict:
    candidates = []
    if gates.empty or "gate_status" not in gates:
        return {"version": "spatial-applicability-hsi-v2", "scope": "research_shadow_only", "distance_metric": "water_path", "research_max_distance_km": 5.0, "candidates": candidates}
    for row in gates.loc[gates.gate_status.eq("shadow_candidate")].itertuples(index=False):
        relevant = metrics.loc[(metrics.parameter.eq("HSI")) & (metrics.model.eq("distance_bin_quantile_conformal")) & (metrics.coverage_target.eq(row.coverage_target)) & (metrics.distance_bin_km.astype(str).eq(str(row.distance_bin_km)))]
        candidates.append({"parameter": "HSI", "coverage_target": float(row.coverage_target), "distance_bin_km": str(row.distance_bin_km), "outer_km": _distance_bin_upper(str(row.distance_bin_km)), "mean_bound": float(relevant.mean_bound.mean()) if not relevant.empty else None, "gate_status": "shadow_candidate", "reason_codes": ""})
    return {"version": "spatial-applicability-hsi-v2", "scope": "research_shadow_only", "distance_metric": "water_path", "research_max_distance_km": 5.0, "candidates": candidates}


def run(region: str, targets: list[str], *, max_dist_km: float = 30.0, bin_km: float = 1.0, alpha: float = .6, coverages: tuple[float, ...] = (.8, .9, .95)) -> dict[str, pd.DataFrame | dict]:
    source_path = REGION_PATHS[region]
    frame = prepare_source(pd.read_csv(source_path))
    catalog, coordinate_findings = station_catalog(frame)
    pair_outputs = [pairwise_anchor_copy(frame, target) for target in targets]
    pairs = pd.concat([item for item in pair_outputs if not item.empty], ignore_index=True) if any(not item.empty for item in pair_outputs) else pd.DataFrame()
    summaries = [metric_summary(pairs.loc[pairs.parameter.eq(target)], target) for target in targets] if not pairs.empty else []
    metrics = pd.concat([item for item in summaries if not item.empty], ignore_index=True) if any(not item.empty for item in summaries) else pd.DataFrame()
    bound_predictions, bound_metrics = error_bound_benchmarks(pairs, targets, coverages=coverages) if not pairs.empty else (pd.DataFrame(), pd.DataFrame())
    gate_summary = spatial_gate_summary(bound_metrics)
    hsi_pairs = hsi_water_path_pairs(frame, max_distance_km=5.0)
    hsi_predictions, hsi_metrics = error_bound_benchmarks(hsi_pairs, ["HSI"], coverages=(.9,)) if not hsi_pairs.empty else (pd.DataFrame(), pd.DataFrame())
    hsi_gates = spatial_gate_summary(hsi_metrics, min_pairs=30, research_max_distance_km=5.0)
    hsi_diagnostics = hsi_label_diagnostics(hsi_predictions)
    radii, accepted = observed_hsi_radius_diagnostic(frame, max_dist_km=max_dist_km, bin_km=bin_km, alpha=alpha)
    radius_summary = pd.DataFrame([{
        "method": "diagnostic_only_observed_hsi_leakage", "n_radius_rows": len(radii),
        "n_accepted_pairs": len(accepted),
        "same_hsi_label_rate": float(accepted.same_hsi_label.mean()) if not accepted.empty else np.nan,
        "median_radius_km": float(radii.radius_km.median()) if not radii.empty else np.nan,
    }])
    audit = {"region": region, "source": str(source_path), "source_sha256": file_sha256(source_path), "n_rows": len(frame), "n_stations": int(catalog.station.nunique()),
             "n_periods": int(frame.observed_at.nunique()), "coordinate_inconsistent_stations": int(len(coordinate_findings)),
             "pairwise_baseline": "anchor_copy_observed_value", "legacy_radius_status": "diagnostic_only_observed_hsi_leakage",
             "hsi_protocol": {"target": "historical_hsi", "distance_metric": "water_path", "grid_resolution_m": 500,
                              "max_distance_km": 5, "coverage_target": .9, "minimum_pairs_per_bin": 30,
                              "outer_splits": ["forward_temporal", "leave_target_station_out"]}}
    return {"audit": audit, "station_catalog": catalog, "coordinate_findings": coordinate_findings,
            "anchor_copy_pairs": pairs, "anchor_copy_metrics": metrics, "legacy_radius": radii,
            "legacy_radius_accepted_pairs": accepted, "legacy_radius_summary": radius_summary,
            "error_bound_predictions": bound_predictions, "error_bound_metrics": bound_metrics,
            "spatial_gate_summary": gate_summary, "hsi_water_path_pairs": hsi_pairs,
            "hsi_error_bound_predictions": hsi_predictions, "hsi_error_bound_metrics": hsi_metrics,
            "hsi_gate_summary": hsi_gates, "hsi_label_diagnostics": hsi_diagnostics,
            "hsi_gate_config": hsi_gate_config(hsi_gates, hsi_metrics),
            "context_availability": context_availability()}


def main() -> None:
    parser = argparse.ArgumentParser(description="P0 spatial applicability audit and historical benchmark.")
    parser.add_argument("--region", choices=sorted(REGION_PATHS), required=True)
    parser.add_argument("--targets", nargs="+", default=["DO", "Salinity"])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-dist-km", type=float, default=30.0)
    parser.add_argument("--bin-km", type=float, default=1.0)
    parser.add_argument("--alpha", type=float, default=.6)
    parser.add_argument("--coverages", nargs="+", type=float, default=[.8, .9, .95])
    args = parser.parse_args()
    result = run(args.region, args.targets, max_dist_km=args.max_dist_km, bin_km=args.bin_km, alpha=args.alpha, coverages=tuple(args.coverages))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in result.items():
        if isinstance(value, pd.DataFrame):
            value.to_csv(args.output_dir / f"{name}.csv", index=False)
    (args.output_dir / "hsi_gate_config.json").write_text(json.dumps(result["hsi_gate_config"], ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "context_availability.json").write_text(json.dumps(result["context_availability"], ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "audit.json").write_text(json.dumps(result["audit"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["audit"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
