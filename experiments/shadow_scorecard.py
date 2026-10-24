"""H1.5 shadow scorecard: score the live long-horizon ledger (read-only).

Reads ``runtime/forecast-shadow/long_forecasts.jsonl`` (+ ``long_outcomes.jsonl``
and ``long_skips.jsonl`` when present) and scores every issued 3/6/12 h forecast
against the observed sensor value:

* an outcome already resolved by the shadow runner (``long_outcomes.jsonl``) is
  used as is;
* a forecast the runner has not resolved yet is resolved on the fly with the
  same rule (``core.forecast_evaluation.long_outcome``: nearest valid reading
  within +/- 2 minutes of ``valid_at``, same exclusions) from the cached sensor
  history (``core.greenlab_api.load_cached_history``) or a frozen
  ``sensor-history-*`` CSV.  Nothing is written to ``runtime/`` or ``data/``.

Per (target x base feature set x with/without pH x horizon), overall and per ISO
week (local time of ``issued_at``): n, MAE, persistence MAE on the same issue
times (persistence = the ``current`` reading the forecast was issued from),
skill = 1 - MAE / persistence MAE, PI80/PI90 empirical coverage and mean width,
and the paired with-pH vs nopH loss difference on shared issue times.
Diebold-Mariano tests (``experiments.forecast_dm_test``; HAC lag h-1 with
1-minute origins) only run once a group has sufficient evidence.

Evidence threshold: a group is ``insufficient_evidence`` while it has fewer than
``MIN_RESOLVED`` (200) scored forecasts **or** they span fewer than ``MIN_DAYS``
(7) local calendar days.  One-minute origins are strongly autocorrelated, so the
day count is the binding condition.  The H1.5 gate (roadmap) needs
``GATE_DAYS`` (28) days of ledger; until then the gate reads ``collecting``.

Output: a new ``artifacts/experiments/shadow-scorecard-<YYYYMMDD>/`` (``-HHMM``
suffix when the day's dir already exists; never overwritten) with
``scorecard.json`` and ``scorecard.md``.

    python experiments/shadow_scorecard.py --station 06M26042804
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import forecast_evaluation as fe  # noqa: E402
from core import paths  # noqa: E402
from experiments.forecast_dm_test import diebold_mariano  # noqa: E402

SCHEMA = "shadow-scorecard-v1"
RUN_PREFIX = "shadow-scorecard-"
DEFAULT_STATION = "06M26042804"
LOCAL_TZ = "Asia/Ho_Chi_Minh"
MIN_RESOLVED = 200
MIN_DAYS = 7
GATE_DAYS = 28
DM_ALPHA = 0.05
PI_LEVELS = fe.PI_LEVELS
PI_NOMINAL = {"pi80": 0.80, "pi90": 0.90}
PI80_TARGET = (0.75, 0.85)  # roadmap H1.3 gate, re-checked on the live ledger
NOPH_SUFFIX = "_nopH"
GROUP_KEYS = ["target", "base_feature_set", "variant", "horizon_minutes"]
PAIR_KEYS = ["target", "base_feature_set", "horizon_minutes"]


# ------------------------------------------------------------------ read-only ledger access
def iter_jsonl(path: Path) -> Iterator[dict]:
    """Complete JSON lines of an append-only file, opened read-only.

    A trailing line without newline (the runner mid-append) and unparsable
    lines are skipped, never repaired.
    """
    path = Path(path)
    if not path.is_file():
        return
    with path.open("rb") as handle:
        for raw in handle:
            if not raw.endswith(b"\n") or not raw.strip():
                continue
            try:
                yield json.loads(raw)
            except ValueError:
                continue


def _pi_q(pi: dict | None, level: str) -> float:
    band = (pi or {}).get(level)
    if not isinstance(band, dict) or band.get("q") is None:
        return math.nan
    try:
        return float(band["q"])
    except (TypeError, ValueError):
        return math.nan


def load_forecasts(path: Path, station: str) -> list[dict]:
    """Forecast records of one station, slimmed to what scoring needs."""
    keep = ("record_id", "station_serial", "issued_at", "valid_at", "horizon_minutes", "target", "feature_set",
            "model_version", "model_variant", "forecast", "current", "pi", "sensor_status", "ph_input_status", "data_source")
    rows = []
    for record in iter_jsonl(path):
        if record.get("station_serial") != station or not all(record.get(k) for k in ("record_id", "issued_at", "valid_at", "target")):
            continue
        rows.append({key: record.get(key) for key in keep})
    return rows


def load_outcomes(path: Path, station: str) -> dict[str, dict]:
    """Runner-resolved outcomes keyed by forecast record id (first one wins: the ledger is write-once)."""
    out: dict[str, dict] = {}
    for record in iter_jsonl(path):
        if record.get("station_serial") != station:
            continue
        key = record.get("forecast_record_id")
        if key and key not in out:
            out[key] = record
    return out


def load_skips(path: Path, station: str) -> list[dict]:
    rows = []
    for record in iter_jsonl(path):
        if record.get("station_serial") == station:
            rows.append({key: record.get(key) for key in ("target", "feature_set", "horizon_minutes", "reason", "issued_at", "recorded_at")})
    return rows


# ------------------------------------------------------------------ resolution
def resolve_on_the_fly(forecasts: list[dict], resolved_ids: set[str], history: pd.DataFrame | None,
                       now: pd.Timestamp) -> dict[str, dict]:
    """Outcomes for due forecasts the ledger has not resolved yet; nothing is written."""
    due = [f for f in forecasts if f["record_id"] not in resolved_ids
           and pd.Timestamp(f["valid_at"]) - fe.LONG_TOLERANCE <= now]
    if not due or history is None or history.empty:
        return {}
    frame = fe.prepare_long_raw(history)
    if frame.empty:
        return {}
    first, latest = frame["fetchedAt"].min(), frame["fetchedAt"].max()
    series: dict[str, pd.Series] = {}
    out = {}
    for forecast in due:
        target = forecast["target"]
        if target not in series:
            series[target] = fe._valid_series(frame, target)
        outcome = fe.long_outcome(forecast, series[target], first, latest)
        if outcome is not None:
            out[forecast["record_id"]] = outcome
    return out


def scoring_frame(forecasts: list[dict], ledger_outcomes: dict[str, dict], fly_outcomes: dict[str, dict]) -> pd.DataFrame:
    """One row per issued forecast with its outcome status (``pending`` when unresolved)."""
    rows = []
    for f in forecasts:
        outcome, source = ledger_outcomes.get(f["record_id"]), "ledger"
        if outcome is None:
            outcome, source = fly_outcomes.get(f["record_id"]), "on_the_fly"
        if outcome is None:
            source = None
        feature_set = str(f.get("feature_set") or "")
        nopH = feature_set.endswith(NOPH_SUFFIX)
        status = (outcome or {}).get("status", "pending")
        covered = (outcome or {}).get("covered") or {}
        row = {
            "record_id": f["record_id"], "target": f.get("target"), "feature_set": feature_set,
            "base_feature_set": feature_set.removesuffix(NOPH_SUFFIX), "variant": "nopH" if nopH else "with_pH",
            "horizon_minutes": int(f.get("horizon_minutes") or 0), "model_version": f.get("model_version"),
            "issued_at": pd.Timestamp(f["issued_at"]), "valid_at": pd.Timestamp(f["valid_at"]),
            "forecast": float(f["forecast"]) if f.get("forecast") is not None else math.nan,
            "current": float(f["current"]) if f.get("current") is not None else math.nan,
            "q80": _pi_q(f.get("pi"), "pi80"), "q90": _pi_q(f.get("pi"), "pi90"),
            "ph_input_status": f.get("ph_input_status"), "status": status, "outcome_source": source,
            "actual": float(outcome["actual"]) if status == "scored" and outcome.get("actual") is not None else math.nan,
        }
        for level in PI_LEVELS:
            row[f"covered_{level}"] = covered.get(level) if status == "scored" else None
        rows.append(row)
    columns = ["record_id", "target", "feature_set", "base_feature_set", "variant", "horizon_minutes", "model_version", "issued_at",
               "valid_at", "forecast", "current", "q80", "q90", "ph_input_status", "status", "outcome_source", "actual",
               "covered_pi80", "covered_pi90"]
    frame = pd.DataFrame(rows, columns=columns)
    if not frame.empty:
        frame["issued_at"] = pd.to_datetime(frame["issued_at"], utc=True)
        frame["valid_at"] = pd.to_datetime(frame["valid_at"], utc=True)
        local = frame["issued_at"].dt.tz_convert(LOCAL_TZ)
        frame["local_date"] = local.dt.date.astype(str)
        iso = local.dt.isocalendar()
        frame["iso_week"] = iso["year"].astype(str) + "-W" + iso["week"].astype(int).map("{:02d}".format)
    else:
        frame["local_date"], frame["iso_week"] = [], []
    return frame


# ------------------------------------------------------------------ metrics
def _f(value, digits: int = 4):
    if value is None:
        return None
    value = float(value)
    return round(value, digits) if math.isfinite(value) else None


def _evidence(n_scored: int, days: int) -> dict:
    reasons = []
    if n_scored < MIN_RESOLVED:
        reasons.append(f"n_scored<{MIN_RESOLVED}")
    if days < MIN_DAYS:
        reasons.append(f"days<{MIN_DAYS}")
    return {"evidence": "insufficient_evidence" if reasons else "sufficient", "evidence_reasons": reasons}


def _dm(e_model: np.ndarray, e_base: np.ndarray, horizon: int) -> dict:
    statistic, p_value = diebold_mariano(e_model, e_base, horizon_steps=horizon, loss="abs")
    return {"dm_stat": _f(statistic), "p_value": _f(p_value, 6),
            "significant": bool(np.isfinite(p_value) and p_value < DM_ALPHA)}


def score_group(group: pd.DataFrame, horizon: int) -> dict:
    """Metrics of one group of forecasts (any status)."""
    status = group["status"]
    scored = group[status.eq("scored")].sort_values("issued_at")
    days = int(scored["local_date"].nunique())
    row = {"n_issued": int(len(group)), "n_scored": int(len(scored)),
           "n_excluded": int(status.eq("excluded_sensor_suspect").sum()), "n_no_observation": int(status.eq("no_observation").sum()),
           "n_pending": int(status.eq("pending").sum()), "n_on_the_fly": int((group["outcome_source"] == "on_the_fly").sum()),
           "days_scored": days, "first_issued_at": group["issued_at"].min().isoformat() if len(group) else None,
           "last_issued_at": group["issued_at"].max().isoformat() if len(group) else None,
           "model_versions": sorted({str(v) for v in group["model_version"].dropna()})}
    row |= _evidence(len(scored), days)
    empty = {"mae": None, "rmse": None, "bias": None, "persistence_mae": None, "skill": None}
    if scored.empty:
        row |= empty
        for level in PI_LEVELS:
            row |= {f"coverage_{level}": None, f"mean_width_{level}": None, f"n_infinite_{level}": 0}
        row |= {"pi80_in_target": None, "dm_vs_persistence": None}
        return row
    error = scored["forecast"] - scored["actual"]
    persistence = scored["current"] - scored["actual"]
    mae, pmae = float(error.abs().mean()), float(persistence.abs().mean())
    row |= {"mae": _f(mae), "rmse": _f(np.sqrt((error ** 2).mean())), "bias": _f(error.mean()), "persistence_mae": _f(pmae),
            "skill": _f(1.0 - mae / pmae) if pmae > 0 else None}
    for level, q_col in (("pi80", "q80"), ("pi90", "q90")):
        flags = scored[f"covered_{level}"].dropna()
        q = scored[q_col].dropna()
        finite = q[np.isfinite(q)]
        row[f"coverage_{level}"] = _f(flags.astype(bool).mean()) if len(flags) else None
        row[f"mean_width_{level}"] = _f(2 * finite.mean()) if len(finite) else None
        row[f"n_infinite_{level}"] = int(len(q) - len(finite))
    sufficient = row["evidence"] == "sufficient"
    cov80 = row["coverage_pi80"]
    row["pi80_in_target"] = (PI80_TARGET[0] <= cov80 <= PI80_TARGET[1]) if sufficient and cov80 is not None else None
    if sufficient:
        dm = _dm(error.to_numpy(), persistence.to_numpy(), horizon)
        dm["model_better"] = bool(dm["significant"] and (dm["dm_stat"] or 0) < 0)
        row["dm_vs_persistence"] = dm
    else:
        row["dm_vs_persistence"] = None
    return row


def score_pairs(scored: pd.DataFrame) -> pd.DataFrame:
    """with-pH and nopH errors on shared issue times."""
    cols = PAIR_KEYS + ["issued_at"]
    base = scored.assign(abs_error=(scored["forecast"] - scored["actual"]).abs())
    with_ph = base[base["variant"].eq("with_pH")][cols + ["abs_error", "local_date", "iso_week"]]
    no_ph = base[base["variant"].eq("nopH")][cols + ["abs_error"]]
    with_ph = with_ph.drop_duplicates(subset=cols)
    no_ph = no_ph.drop_duplicates(subset=cols)
    return with_ph.merge(no_ph, on=cols, suffixes=("_with_pH", "_nopH"), how="inner")


def pair_metrics(pairs: pd.DataFrame, horizon: int) -> dict:
    pairs = pairs.sort_values("issued_at")
    days = int(pairs["local_date"].nunique())
    row = {"n_pairs": int(len(pairs)), "days": days} | _evidence(len(pairs), days)
    if pairs.empty:
        return row | {"mae_with_pH": None, "mae_nopH": None, "mean_diff": None, "share_with_pH_better": None, "dm": None}
    diff = pairs["abs_error_with_pH"] - pairs["abs_error_nopH"]
    row |= {"mae_with_pH": _f(pairs["abs_error_with_pH"].mean()), "mae_nopH": _f(pairs["abs_error_nopH"].mean()),
            "mean_diff": _f(diff.mean()), "share_with_pH_better": _f((diff < 0).mean())}
    if row["evidence"] == "sufficient":
        dm = _dm(pairs["abs_error_with_pH"].to_numpy(), pairs["abs_error_nopH"].to_numpy(), horizon)
        dm["better"] = ("with_pH" if (dm["dm_stat"] or 0) < 0 else "nopH") if dm["significant"] else "no_significant_difference"
        row["dm"] = dm
    else:
        row["dm"] = None
    return row


def _key_dict(keys: tuple, names: list[str]) -> dict:
    return {name: (int(value) if name == "horizon_minutes" else value) for name, value in zip(names, keys)}


def build_scorecard(frame: pd.DataFrame, skips: list[dict], *, station: str, now: pd.Timestamp, inputs: dict) -> dict:
    """The full scorecard document (JSON-serialisable)."""
    thresholds = {"min_resolved": MIN_RESOLVED, "min_days": MIN_DAYS, "gate_days": GATE_DAYS, "dm_alpha": DM_ALPHA,
                  "pi80_target": list(PI80_TARGET), "pi_nominal": PI_NOMINAL, "tolerance_minutes": fe.LONG_TOLERANCE.total_seconds() / 60,
                  "week": "ISO week of issued_at in Asia/Ho_Chi_Minh", "persistence": "the 'current' reading each forecast was issued from",
                  "skill": "1 - MAE / persistence MAE on the same scored forecasts",
                  "dm": "Diebold-Mariano, absolute loss, Newey-West lag h-1 with 1-minute origins, HLN correction; run only with sufficient evidence"}
    if frame.empty:
        ledger = {"n_forecasts": 0, "first_issued_at": None, "last_issued_at": None, "ledger_days": 0.0, "distinct_days": 0,
                  "n_scored": 0, "n_excluded": 0, "n_no_observation": 0, "n_pending": 0, "n_on_the_fly": 0}
    else:
        first, last = frame["issued_at"].min(), frame["issued_at"].max()
        status = frame["status"]
        ledger = {"n_forecasts": int(len(frame)), "first_issued_at": first.isoformat(), "last_issued_at": last.isoformat(),
                  "ledger_days": round((last - first).total_seconds() / 86400, 3), "distinct_days": int(frame["local_date"].nunique()),
                  "n_scored": int(status.eq("scored").sum()), "n_excluded": int(status.eq("excluded_sensor_suspect").sum()),
                  "n_no_observation": int(status.eq("no_observation").sum()), "n_pending": int(status.eq("pending").sum()),
                  "n_on_the_fly": int((frame["outcome_source"] == "on_the_fly").sum())}
    scored_days = int(frame.loc[frame["status"].eq("scored"), "local_date"].nunique()) if not frame.empty else 0
    overall_evidence = _evidence(ledger["n_scored"], scored_days)
    gate = {"days_required": GATE_DAYS, "ledger_days": ledger["ledger_days"],
            "progress": round(min(1.0, ledger["ledger_days"] / GATE_DAYS), 4),
            "status": "ready_for_review" if ledger["ledger_days"] >= GATE_DAYS else "collecting",
            "note": "H1.5 gate: >= 4 weeks of ledger and stable metrics (roadmap); the decision itself stays with the owner."}

    groups, weekly, paired, paired_weekly = [], [], [], []
    if not frame.empty:
        for keys, group in frame.groupby(GROUP_KEYS, sort=True):
            groups.append(_key_dict(keys, GROUP_KEYS) | score_group(group, int(keys[-1])))
        for keys, group in frame.groupby(["iso_week", *GROUP_KEYS], sort=True):
            weekly.append(_key_dict(keys, ["iso_week", *GROUP_KEYS]) | score_group(group, int(keys[-1])))
        pairs = score_pairs(frame[frame["status"].eq("scored")])
        for keys, group in pairs.groupby(PAIR_KEYS, sort=True):
            paired.append(_key_dict(keys, PAIR_KEYS) | pair_metrics(group, int(keys[-1])))
        for keys, group in pairs.groupby(["iso_week", *PAIR_KEYS], sort=True):
            paired_weekly.append(_key_dict(keys, ["iso_week", *PAIR_KEYS]) | pair_metrics(group, int(keys[-1])))

    skip_counts: dict[tuple, dict] = {}
    for skip in skips:
        key = (skip.get("target"), skip.get("feature_set"), skip.get("horizon_minutes"), skip.get("reason"))
        entry = skip_counts.setdefault(key, {"target": key[0], "feature_set": key[1], "horizon_minutes": key[2], "reason": key[3],
                                             "n": 0, "last_at": None})
        entry["n"] += 1
        at = skip.get("issued_at") or skip.get("recorded_at")
        if at and (entry["last_at"] is None or str(at) > entry["last_at"]):
            entry["last_at"] = str(at)

    return {"schema_version": SCHEMA, "station": station, "generated_at": now.isoformat(), "mode": "shadow",
            "used_by_alerts": False, "status": overall_evidence["evidence"], "evidence_reasons": overall_evidence["evidence_reasons"],
            "thresholds": thresholds, "inputs": inputs, "ledger": ledger | {"scored_days": scored_days}, "gate": gate,
            "groups": groups, "weekly": weekly, "paired": paired, "paired_weekly": paired_weekly,
            "skips": sorted(skip_counts.values(), key=lambda s: (-s["n"], str(s["feature_set"]), s["horizon_minutes"] or 0))}


# ------------------------------------------------------------------ markdown
def _md_num(value, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _md_pct(value) -> str:
    return "—" if value is None else f"{100 * value:.1f} %"


def render_markdown(card: dict) -> str:
    ledger, gate = card["ledger"], card["gate"]
    lines = [f"# Shadow scorecard H1.5 — {card['station']}", "",
             f"- Tạo lúc: {card['generated_at']} · chế độ shadow (không dùng cho cảnh báo)",
             f"- Trạng thái: **{card['status']}**" + (f" ({', '.join(card['evidence_reasons'])})" if card["evidence_reasons"] else ""),
             f"- Sổ ghi: {ledger['n_forecasts']} dự báo, {ledger['first_issued_at']} → {ledger['last_issued_at']} "
             f"({ledger['ledger_days']} ngày, {ledger['distinct_days']} ngày lịch)",
             f"- Đã chấm: {ledger['n_scored']} (trong đó {ledger['n_on_the_fly']} đối chiếu tại chỗ, chưa có trong long_outcomes) · "
             f"loại QC {ledger['n_excluded']} · không có quan trắc {ledger['n_no_observation']} · chờ {ledger['n_pending']}",
             f"- Gate H1.5 (≥ {gate['days_required']} ngày sổ ghi): {gate['status']}, tiến độ {_md_pct(gate['progress'])}",
             f"- Ngưỡng bằng chứng: ≥ {card['thresholds']['min_resolved']} dự báo đã chấm và ≥ {card['thresholds']['min_days']} ngày; "
             f"PI80 mục tiêu {card['thresholds']['pi80_target'][0]}–{card['thresholds']['pi80_target'][1]}", "",
             "## Theo nhóm (toàn kỳ)", "",
             "| Biến | Bộ | pH | h (phút) | n chấm | ngày | MAE | MAE persistence | skill | PI80 phủ | PI80 rộng | PI90 phủ | PI90 rộng | DM vs persistence (p) | bằng chứng |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    for g in card["groups"]:
        dm = g.get("dm_vs_persistence")
        dm_text = "—" if not dm else f"{_md_num(dm['dm_stat'], 2)} ({_md_num(dm['p_value'], 4)})"
        lines.append(f"| {g['target']} | {g['base_feature_set']} | {g['variant']} | {g['horizon_minutes']} | {g['n_scored']} | {g['days_scored']} | "
                     f"{_md_num(g['mae'])} | {_md_num(g['persistence_mae'])} | {_md_num(g['skill'])} | {_md_pct(g['coverage_pi80'])} | "
                     f"{_md_num(g['mean_width_pi80'])} | {_md_pct(g['coverage_pi90'])} | {_md_num(g['mean_width_pi90'])} | {dm_text} | {g['evidence']} |")
    if not card["groups"]:
        lines.append("| — | — | — | — | 0 | 0 | — | — | — | — | — | — | — | — | insufficient_evidence |")
    lines += ["", "## Có pH so với không pH (cùng thời điểm phát hành)", "",
              "| Biến | Bộ | h (phút) | n cặp | ngày | MAE có pH | MAE không pH | chênh (có − không) | tỉ lệ có pH tốt hơn | DM (p) | bằng chứng |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    for p in card["paired"]:
        dm = p.get("dm")
        dm_text = "—" if not dm else f"{_md_num(dm['dm_stat'], 2)} ({_md_num(dm['p_value'], 4)}) → {dm['better']}"
        lines.append(f"| {p['target']} | {p['base_feature_set']} | {p['horizon_minutes']} | {p['n_pairs']} | {p['days']} | {_md_num(p['mae_with_pH'])} | "
                     f"{_md_num(p['mae_nopH'])} | {_md_num(p['mean_diff'])} | {_md_pct(p['share_with_pH_better'])} | {dm_text} | {p['evidence']} |")
    if not card["paired"]:
        lines.append("| — | — | — | 0 | 0 | — | — | — | — | — | insufficient_evidence |")
    lines += ["", "## Theo tuần ISO", "",
              "| Tuần | Biến | Bộ | pH | h | n chấm | MAE | MAE persistence | skill | PI80 phủ | PI90 phủ | bằng chứng |",
              "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for w in card["weekly"]:
        lines.append(f"| {w['iso_week']} | {w['target']} | {w['base_feature_set']} | {w['variant']} | {w['horizon_minutes']} | {w['n_scored']} | "
                     f"{_md_num(w['mae'])} | {_md_num(w['persistence_mae'])} | {_md_num(w['skill'])} | {_md_pct(w['coverage_pi80'])} | "
                     f"{_md_pct(w['coverage_pi90'])} | {w['evidence']} |")
    if not card["weekly"]:
        lines.append("| — | — | — | — | — | 0 | — | — | — | — | — | insufficient_evidence |")
    lines += ["", "## Bỏ qua (long_skips.jsonl)", "", "| Biến | Bộ | h | lý do | số dòng | gần nhất |", "|---|---|---:|---|---:|---|"]
    for s in card["skips"]:
        lines.append(f"| {s['target']} | {s['feature_set']} | {s['horizon_minutes']} | {s['reason']} | {s['n']} | {s['last_at']} |")
    if not card["skips"]:
        lines.append("| — | — | — | — | 0 | — |")
    lines += ["", "## Đầu vào", ""] + [f"- {key}: {value}" for key, value in card["inputs"].items()] + [""]
    return "\n".join(lines)


# ------------------------------------------------------------------ run
def history_from_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if "fetchedAt" not in frame:
        raise ValueError(f"history_csv_without_fetchedAt:{path}")
    return frame


def default_history(station: str) -> pd.DataFrame:
    from core.greenlab_api import load_cached_history  # reads data/greenlab/exports only
    return load_cached_history(station)


def compute_scorecard(shadow_dir: Path, station: str, *, now: pd.Timestamp | None = None,
                      history_loader: Callable[[], pd.DataFrame] | None = None, history_label: str = "none") -> dict:
    """Read the ledger (read-only), resolve what the runner has not, return the scorecard."""
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    shadow_dir = Path(shadow_dir)
    paths_in = {name: shadow_dir / f"long_{name}.jsonl" for name in ("forecasts", "outcomes", "skips")}
    forecasts = load_forecasts(paths_in["forecasts"], station)
    ledger_outcomes = load_outcomes(paths_in["outcomes"], station)
    resolved_ids = set(ledger_outcomes)
    needs_history = any(f["record_id"] not in resolved_ids and pd.Timestamp(f["valid_at"]) - fe.LONG_TOLERANCE <= now for f in forecasts)
    history = history_loader() if (needs_history and history_loader is not None) else None
    fly = resolve_on_the_fly(forecasts, resolved_ids, history, now)
    frame = scoring_frame(forecasts, ledger_outcomes, fly)
    inputs = {name: {"path": str(path), "exists": path.is_file(), "bytes": path.stat().st_size if path.is_file() else 0}
              for name, path in paths_in.items()}
    inputs["history"] = {"source": history_label, "used": history is not None,
                         "rows": int(len(history)) if history is not None else 0,
                         "last_observed_at": (pd.to_datetime(history["fetchedAt"], utc=True).max().isoformat()
                                              if history is not None and not history.empty else None)}
    return build_scorecard(frame, load_skips(paths_in["skips"], station), station=station, now=now, inputs=inputs)


def new_run_dir(root: Path, now: pd.Timestamp) -> Path:
    """Fresh output dir; never reuses (and so never overwrites) an existing one."""
    local = now.tz_convert(LOCAL_TZ)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for name in (f"{RUN_PREFIX}{local:%Y%m%d}", f"{RUN_PREFIX}{local:%Y%m%d-%H%M}", f"{RUN_PREFIX}{local:%Y%m%d-%H%M%S}"):
        candidate = root / name
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise FileExistsError(f"refusing_to_overwrite:{root / RUN_PREFIX}{local:%Y%m%d}*")


def write_scorecard(card: dict, out_root: Path) -> Path:
    run_dir = new_run_dir(out_root, pd.Timestamp(card["generated_at"]))
    for name, text in (("scorecard.json", json.dumps(card, ensure_ascii=False, indent=2, allow_nan=False)),
                       ("scorecard.md", render_markdown(card))):
        with (run_dir / name).open("x", encoding="utf-8") as handle:  # exclusive create
            handle.write(text)
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--station", default=DEFAULT_STATION)
    parser.add_argument("--shadow-dir", type=Path, default=paths.FORECAST_SHADOW_DIR, help="ledger dir (read-only)")
    parser.add_argument("--out-root", type=Path, default=paths.EXPERIMENT_OUTPUT_DIR)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--history-csv", type=Path, help="frozen sensor-history-*/<station>.csv instead of the live cache")
    source.add_argument("--no-history", action="store_true", help="use only outcomes already in long_outcomes.jsonl")
    parser.add_argument("--now", help="ISO time treated as now (tests / replays)")
    args = parser.parse_args(argv)
    if args.no_history:
        loader, label = None, "none"
    elif args.history_csv:
        loader, label = (lambda: history_from_csv(args.history_csv)), f"csv:{args.history_csv}"
    else:
        loader, label = (lambda: default_history(args.station)), f"cache:{paths.GREENLAB_EXPORTS_DIR}"
    card = compute_scorecard(args.shadow_dir, args.station, now=pd.Timestamp(args.now) if args.now else None,
                             history_loader=loader, history_label=label)
    run_dir = write_scorecard(card, args.out_root)
    ledger = card["ledger"]
    print(f"{run_dir}\nstatus={card['status']} forecasts={ledger['n_forecasts']} scored={ledger['n_scored']} "
          f"pending={ledger['n_pending']} ledger_days={ledger['ledger_days']} gate={card['gate']['status']} "
          f"({100 * card['gate']['progress']:.1f} %)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
