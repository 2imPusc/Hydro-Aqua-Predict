"""Replace the runtime +15 min temperature XGBoost with a guarded ridge B4 (2026-10-25).

The XGBoost bundles behind ``core/sensor_future.py`` were trained on May-July and
cannot extrapolate below 29.15 °C, so from August they lose badly to persistence.
This script (research + one runtime bundle, owner-approved fix):

1. Gate #16 on the frozen history: ``forecast_sensor_v2.run_benchmark`` for
   Temperature and TSS at 15 min (B0 / B4 / B4_nopH, ridge), then
   ``forecast_gate16_report.report`` (lockbox = last 14 days, 10-24/10).
2. Lockbox check of the *runtime* model: ridge B4 fitted before the lockbox, with
   the persistence guard fixed from the pre-lockbox training data (guard trigger
   rate, MAE raw vs guarded, DM vs persistence).
3. Monthly backtest on identical origins: old XGBoost runtime model (inputs
   rebuilt like the old runtime), ridge B4 refitted per month on data before the
   month (expanding, out-of-sample) with guard, persistence.  TSS: old XGBoost
   lags model vs persistence.
4. Final bundle: ridge B4 on the full history (to 24/10) ->
   ``core/models/sensor_future/haiphong_temperature_ridge_B4_quality_15m_v2.pkl``.

Writes ``artifacts/experiments/<run-name>/`` (refuses an existing directory and an
existing bundle file).

    python experiments/sensor_future_15m_fix.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import paths  # noqa: E402
from core import sensor_future as runtime  # noqa: E402
from core.sensor_future_long import b4_feature_names  # noqa: E402
from experiments.forecast_dm_test import diebold_mariano  # noqa: E402
from experiments.forecast_gate16_report import report as gate16_report  # noqa: E402
from experiments.forecast_sensor_v2 import build_frame, feature_subset, load_sensor_data, lockbox_split, run_benchmark  # noqa: E402

STATION = "06M26042804"
DEFAULT_HISTORY = paths.EXPERIMENT_OUTPUT_DIR / "sensor-history-20261024" / f"{STATION}.csv"
DEFAULT_RUN = "sensor-future-15m-fix-20261025"
HORIZON = 15
FEATURE_SET = "B4_quality"
MODEL_VERSION = "hp-temperature-ridge-b4-15m-v2"
# Guard constants, fixed before any lockbox/live result was looked at.  Training
# |15-min change| quantiles (pre-lockbox): p99 0.7, p99.9 1.1 °C.
RANGE_MARGIN_C = 1.5
MAX_ABS_CHANGE_C = 1.5
MIN_TRAIN_DAYS = 3
LOCAL_TZ = "Asia/Ho_Chi_Minh"
TEMPERATURE_VALUED = ("roll_mean_", "roll_median_", "roll_min_", "roll_max_")


def _ridge():
    return make_pipeline(StandardScaler(), Ridge(alpha=1.0))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def guard_features(features: list[str]) -> list[str]:
    """Temperature-valued inputs checked against the training range."""
    return [name for name in features if name.startswith("Temperature_lag_") or name.startswith(TEMPERATURE_VALUED)]


def make_bundle(train: pd.DataFrame, features: list[str], **meta) -> dict:
    model = _ridge().fit(train[features], train["target"])
    seen = pd.concat([train["current"], train["target"]])
    return {
        "model": model, "features": list(features), "target": "Temperature", "horizon_minutes": HORIZON,
        "feature_set": FEATURE_SET, "model_family": "StandardScaler + Ridge(alpha=1.0)",
        "model_version": MODEL_VERSION,
        "training_range": [float(seen.min()), float(seen.max())],
        "range_margin": RANGE_MARGIN_C, "max_abs_change": MAX_ABS_CHANGE_C,
        "guard_features": guard_features(features),
        "feature_ranges": {name: [float(train[name].min()), float(train[name].max())] for name in features},
        "n_train": int(len(train)),
        "train_issued_from": train["issued_at"].min().isoformat(), "train_valid_until": train["valid_at"].max().isoformat(),
        **meta,
    }


def guarded_predictions(bundle: dict, frame: pd.DataFrame) -> pd.DataFrame:
    """Runtime guard (``core.sensor_future.guard_temperature``) applied row by row."""
    raw = bundle["model"].predict(frame[bundle["features"]])
    names = bundle["guard_features"]
    values = frame[names].to_numpy(dtype=float)
    current = frame["current"].to_numpy(dtype=float)
    out_value, out_source = np.empty(len(frame)), []
    for i in range(len(frame)):
        result = runtime.guard_temperature(bundle, dict(zip(names, values[i])), float(current[i]), float(raw[i]))
        out_value[i] = result["value"]
        out_source.append(result["source"])
    return pd.DataFrame({"raw": raw, "guarded": out_value, "source": out_source}, index=frame.index)


def old_temperature_predictions(raw: pd.DataFrame, frame: pd.DataFrame) -> np.ndarray:
    """Old runtime XGBoost (+15 min), inputs rebuilt causally at each origin.

    Runtime: 3-min median bins; lag_1 = latest bin, lag_k = k-th latest non-empty
    bin; calendar features at bin label + 15 min.  The latest bin uses only
    readings up to the origin (expanding median) so nothing after issue is read.
    """
    bundle = joblib.load(runtime._temperature_bundle_path(HORIZON))
    native = raw[["fetchedAt", "Temperature"]].dropna().copy()
    native["bin"] = native["fetchedAt"].dt.floor("3min")
    native["causal"] = native.groupby("bin")["Temperature"].expanding().median().reset_index(level=0, drop=True)
    causal = native.set_index("fetchedAt")
    bins = runtime._series(raw[["fetchedAt", "Temperature"]], "Temperature")
    issued = pd.DatetimeIndex(frame["issued_at"])
    current_bin = issued.floor("3min")
    pos = bins.index.get_indexer(current_bin)
    if (pos < 0).any():
        raise AssertionError("origin_bin_missing")
    values = bins.to_numpy()
    feats = {"lag_1": causal.loc[issued, "causal"].to_numpy()}
    for lag in runtime.LAGS[1:]:
        index = pos - (lag - 1)
        feats[f"lag_{lag}"] = np.where(index >= 0, values[np.clip(index, 0, None)], np.nan)
    future = current_bin + pd.Timedelta(minutes=HORIZON)
    local = future.tz_convert(LOCAL_TZ)
    hour = local.hour + local.minute / 60
    feats.update({"hour_sin": np.sin(2 * np.pi * hour / 24), "hour_cos": np.cos(2 * np.pi * hour / 24),
                  "dow_sin": np.sin(2 * np.pi * local.dayofweek / 7), "dow_cos": np.cos(2 * np.pi * local.dayofweek / 7)})
    table = pd.DataFrame(feats)[bundle["features"]]
    prediction = bundle["model"].predict(table)
    return np.where(table.notna().all(axis=1), prediction, np.nan)


def old_tss_predictions(raw: pd.DataFrame, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Old runtime TSS: XGBoost on the last 1/2/3/5/10 native readings, persistence if 10 readings span > 30 min."""
    bundle = joblib.load(runtime._tss_bundle_path(HORIZON))
    native = raw[["fetchedAt", "TSS"]].dropna().set_index("fetchedAt")["TSS"]
    pos = native.index.get_indexer(pd.DatetimeIndex(frame["issued_at"]))
    if (pos < 0).any():
        raise AssertionError("origin_reading_missing")
    values, times = native.to_numpy(), native.index.to_numpy()
    lags = {f"lag_{lag}": np.where(pos - lag + 1 >= 0, values[np.clip(pos - lag + 1, 0, None)], np.nan) for lag in runtime.LAGS}
    table = pd.DataFrame(lags)[bundle["features"]]
    model = bundle["model"].predict(table.fillna(0))
    first = pos - max(runtime.LAGS) + 1
    span_ok = (first >= 0) & ((times[pos] - times[np.clip(first, 0, None)]) <= np.timedelta64(30, "m"))
    current = values[pos]
    return np.where(span_ok, model, current), span_ok


def _month(frame: pd.DataFrame) -> pd.Series:
    return frame["issued_at"].dt.tz_convert(LOCAL_TZ).dt.strftime("%Y-%m")


def _mae(error: pd.Series) -> float:
    return float(np.abs(error).mean()) if len(error) else float("nan")


def monthly_temperature(raw: pd.DataFrame, frame: pd.DataFrame, features: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = frame.copy()
    frame["month"] = _month(frame)
    frame["old_xgb"] = old_temperature_predictions(raw, frame)
    frame["ridge_raw"] = np.nan
    frame["ridge_guarded"] = np.nan
    frame["ridge_source"] = None
    train_meta = []
    for month in sorted(frame["month"].unique()):
        start = (pd.Timestamp(f"{month}-01", tz=LOCAL_TZ)).tz_convert("UTC")
        train = frame[frame["valid_at"] < start - pd.Timedelta(minutes=60)]
        days = (train["issued_at"].max() - train["issued_at"].min()).total_seconds() / 86400 if len(train) else 0.0
        train_meta.append({"month": month, "train_rows": int(len(train)), "train_days": round(days, 1)})
        if days < MIN_TRAIN_DAYS:
            continue
        bundle = make_bundle(train, features)
        rows = frame["month"].eq(month)
        result = guarded_predictions(bundle, frame.loc[rows])
        frame.loc[rows, "ridge_raw"] = result["raw"]
        frame.loc[rows, "ridge_guarded"] = result["guarded"]
        frame.loc[rows, "ridge_source"] = result["source"]
    meta = pd.DataFrame(train_meta).set_index("month")
    rows = []
    for month, group in frame.groupby("month"):
        actual = group["target"]
        oos = group["ridge_guarded"].notna()
        rows.append({
            "month": month, "n": int(len(group)), "n_old_xgb": int(group["old_xgb"].notna().sum()),
            "mae_old_xgb": _mae(group["old_xgb"].dropna() - actual[group["old_xgb"].notna()]),
            "mae_ridge_raw": _mae(group.loc[oos, "ridge_raw"] - actual[oos]) if oos.any() else np.nan,
            "mae_ridge_guarded": _mae(group.loc[oos, "ridge_guarded"] - actual[oos]) if oos.any() else np.nan,
            "mae_persistence_lag1m": _mae(group["Temperature_lag_1m"] - actual),
            "mae_persistence_current": _mae(group["current"] - actual),
            "guard_fallback_rate": float((group.loc[oos, "ridge_source"] != runtime.TEMPERATURE_SOURCE).mean()) if oos.any() else np.nan,
            "ridge_train_days": meta.loc[month, "train_days"],
            "actual_min": float(actual.min()), "actual_max": float(actual.max()),
            "old_xgb_min_prediction": float(group["old_xgb"].min()),
        })
    return pd.DataFrame(rows), frame


def monthly_tss(raw: pd.DataFrame) -> pd.DataFrame:
    frame, _ = build_frame(raw, "TSS", HORIZON, "B0_lags", station=STATION)
    frame = frame.copy()
    frame["month"] = _month(frame)
    frame["old_xgb"], frame["old_model_used"] = old_tss_predictions(raw, frame)
    rows = []
    for month, group in frame.groupby("month"):
        actual = group["target"]
        rows.append({"month": month, "n": int(len(group)), "mae_old_xgb_runtime": _mae(group["old_xgb"] - actual),
                     "old_model_share": float(group["old_model_used"].mean()),
                     "mae_persistence_current": _mae(group["current"] - actual),
                     "mae_persistence_lag1m": _mae(group["TSS_lag_1m"] - actual),
                     "actual_median": float(actual.median())})
    return pd.DataFrame(rows)


def lockbox_runtime_check(frame: pd.DataFrame, features: list[str]) -> tuple[dict, dict]:
    train, test = lockbox_split(frame)
    bundle = make_bundle(train, features, fit_scope="pre_lockbox")
    result = guarded_predictions(bundle, test)
    actual = test["target"].to_numpy()
    out = {"n_train": int(len(train)), "n_lockbox": int(len(test)),
           "lockbox_from": test["issued_at"].min().isoformat(), "lockbox_to": test["issued_at"].max().isoformat(),
           "training_range": bundle["training_range"], "range_margin": RANGE_MARGIN_C, "max_abs_change": MAX_ABS_CHANGE_C,
           "train_abs_change_quantiles": {str(q): float(v) for q, v in (train["target"] - train["current"]).abs().quantile([.5, .9, .99, .999]).items()},
           "guard_sources": result["source"].value_counts().to_dict()}
    for name, prediction in (("ridge_raw", result["raw"].to_numpy()), ("ridge_guarded", result["guarded"].to_numpy()),
                             ("persistence_lag1m", test["Temperature_lag_1m"].to_numpy()), ("persistence_current", test["current"].to_numpy())):
        out[f"mae_{name}"] = float(np.mean(np.abs(prediction - actual)))
        out[f"p95_{name}"] = float(np.quantile(np.abs(prediction - actual), .95))
    for reference in ("persistence_lag1m", "persistence_current"):
        ref = test["Temperature_lag_1m" if reference == "persistence_lag1m" else "current"].to_numpy()
        stat, p = diebold_mariano(result["guarded"].to_numpy() - actual, ref - actual, horizon_steps=HORIZON, loss="abs", kernel="rectangular")
        out[f"dm_guarded_vs_{reference}"] = {"stat": float(stat), "p": float(p)}
        out[f"skill_guarded_vs_{reference}_pct"] = round((1 - out["mae_ridge_guarded"] / out[f"mae_{reference}"]) * 100, 2)
    return out, bundle


def _fmt(value, digits=3) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "–"
    return f"{value:.{digits}f}".replace(".", ",")


def notes(run: str, history: Path, sha: str, gate: pd.DataFrame, check: dict, temp: pd.DataFrame, tss: pd.DataFrame, final: dict, bundle_path: Path) -> str:
    gate_rows = "\n".join(
        f"| {r.target} | {r.feature_set} | {r.n_lock} | {_fmt(r.lock_mae)} | {_fmt(r.pers_mae)} | {_fmt(r.skill_pct, 1)} | {r.folds_won} | {r.dm_p:.3g} | {r.gate} |"
        for r in gate.itertuples())
    temp_rows = "\n".join(
        f"| {r.month} | {r.n} | {_fmt(r.mae_old_xgb)} | {_fmt(r.mae_ridge_guarded)} | {_fmt(r.mae_ridge_raw)} | {_fmt(r.mae_persistence_lag1m)} | {_fmt(r.mae_persistence_current)} | {_fmt(r.guard_fallback_rate * 100 if np.isfinite(r.guard_fallback_rate) else np.nan, 2)} | {_fmt(r.ridge_train_days, 1)} | {_fmt(r.actual_min, 1)}–{_fmt(r.actual_max, 1)} | {_fmt(r.old_xgb_min_prediction, 2)} |"
        for r in temp.itertuples())
    tss_rows = "\n".join(
        f"| {r.month} | {r.n} | {_fmt(r.mae_old_xgb_runtime)} | {_fmt(r.mae_persistence_current)} | {_fmt(r.old_model_share * 100, 1)} | {_fmt(r.actual_median, 1)} |"
        for r in tss.itertuples())
    dm_lag = check["dm_guarded_vs_persistence_lag1m"]
    dm_cur = check["dm_guarded_vs_persistence_current"]
    return f"""# {run} — sửa dự báo cảm biến +15 phút (nhiệt độ ridge B4 có chặn, TSS persistence)

Chạy: `python experiments/sensor_future_15m_fix.py` · dữ liệu `{history.parent.name}/{history.name}` (sha256 {sha[:8]}…), trạm {STATION}.

## Vấn đề
Bundle XGBoost +15 phút (nhiệt độ, TSS) huấn luyện trên 05–07; cây không ngoại suy được nên nhiệt độ dự báo
không bao giờ dưới ~29,15 °C, từ tháng 8 thua persistence rất xa. TSS học chế độ ~70 mg/L trước 31/07.

## Gate #16 (benchmark `forecast_sensor_v2`, ridge, 15 phút, lockbox 14 ngày cuối)
| Biến | Bộ | n lockbox | MAE | MAE persistence | Skill % | Fold thắng | DM p | Gate |
|---|---|---|---|---|---|---|---|---|
{gate_rows}

Persistence của benchmark = giá trị lúc `issued_at − 1 phút` (`*_lag_1m`).

## Mô hình runtime trên lockbox (fit trước lockbox, chặn cố định từ dữ liệu huấn luyện)
- Lockbox {check['lockbox_from'][:16]} → {check['lockbox_to'][:16]} UTC, n = {check['n_lockbox']}.
- MAE ridge thô {_fmt(check['mae_ridge_raw'])} · ridge có chặn {_fmt(check['mae_ridge_guarded'])} · persistence lag 1 phút {_fmt(check['mae_persistence_lag1m'])} · persistence giá trị hiện tại {_fmt(check['mae_persistence_current'])} °C.
- Skill có chặn: {_fmt(check['skill_guarded_vs_persistence_lag1m_pct'], 1)} % so với persistence lag 1 phút (DM {_fmt(dm_lag['stat'], 2)}, p = {dm_lag['p']:.3g}); {_fmt(check['skill_guarded_vs_persistence_current_pct'], 1)} % so với giá trị hiện tại (DM {_fmt(dm_cur['stat'], 2)}, p = {dm_cur['p']:.3g}).
- Nguồn sau chặn: {json.dumps(check['guard_sources'], ensure_ascii=False)}.
- Chặn (cố định trước khi xem lockbox): đầu vào nhiệt độ (lag, trung bình/trung vị/min/max trượt, giá trị hiện tại) hoặc dự báo nằm ngoài [min − {_fmt(RANGE_MARGIN_C, 1)}, max + {_fmt(RANGE_MARGIN_C, 1)}] °C của dải huấn luyện, hoặc |dự báo − hiện tại| > {_fmt(MAX_ABS_CHANGE_C, 1)} °C → persistence, nhãn `persistence_out_of_range` / `persistence_implausible_change`. Phân vị |thay đổi 15 phút| trong dữ liệu huấn luyện: {json.dumps({k: round(v, 2) for k, v in check['train_abs_change_quantiles'].items()})}.

## Backtest theo tháng — nhiệt độ +15 phút (MAE °C, cùng mốc phát hành)
Mốc = mọi số đọc nhiệt độ hợp lệ (1 phút), nhãn = số đọc gần nhất trong ±2 phút quanh +15 phút (khung B4 của benchmark).
XGBoost cũ: đầu vào dựng lại như runtime cũ (bin 3 phút, bin cuối chỉ dùng số đọc ≤ mốc); 05–07 là **trong mẫu** của nó.
Ridge: fit lại mỗi tháng trên nhãn trước đầu tháng − 60 phút (mở rộng, ngoài mẫu), áp chặn như runtime; tháng có < {MIN_TRAIN_DAYS} ngày huấn luyện bỏ trống (05, 06).
TSS: XGBoost cũ dùng 1/2/3/5/10 số đọc gốc gần nhất (persistence nếu 10 số đọc trải > 30 phút); 05–07 là trong mẫu của nó.

| Tháng | n | XGBoost cũ | Ridge B4 có chặn | Ridge thô | Persistence lag 1 ph | Persistence hiện tại | % rơi về persistence | Ngày huấn luyện | Dải thực đo °C | Dự báo XGB thấp nhất |
|---|---|---|---|---|---|---|---|---|---|---|
{temp_rows}

## Backtest theo tháng — TSS +15 phút (MAE mg/L)
| Tháng | n | XGBoost cũ (runtime) | Persistence hiện tại | % mốc dùng mô hình cũ | Trung vị thực đo |
|---|---|---|---|---|---|
{tss_rows}

## Bundle runtime mới
- `{bundle_path.name}`, `model_version` = `{MODEL_VERSION}`; StandardScaler + Ridge(alpha=1), fit trên toàn bộ lịch sử tới {final['train_valid_until'][:16]} UTC (n = {final['n_train']}).
- Đặc trưng (B4_quality đầy đủ, {len(final['features'])} cột, dựng lại lúc chạy bằng `core.sensor_future_long.origin_features`): {', '.join(final['features'])}.
- Dải huấn luyện nhiệt độ {_fmt(final['training_range'][0], 2)}–{_fmt(final['training_range'][1], 2)} °C; chặn ±{_fmt(RANGE_MARGIN_C, 1)} °C; trần thay đổi {_fmt(MAX_ABS_CHANGE_C, 1)} °C.
- TSS, pH, NH4: persistence (TSS: không mô hình 15 phút ngoại tuyến nào đạt gate, RL-54). Bundle XGBoost cũ giữ trong git, không còn được nạp.
- Biến thể không pH (B4_quality_nopH) kém hơn rất ít ở 15 phút (xem bảng gate); cân nhắc chuyển khi hiệu chuẩn/thay đầu dò pH.

## Hạn chế
- Một trạm, một lockbox 14 ngày; MAE theo tháng của XGBoost cũ ở 05–07 là trong mẫu.
- Ridge vẫn chỉ dùng tối đa 60 phút lịch sử (không có chu kỳ ngày nhiều ngày, RL-62).
- Chặn chỉ kiểm tra đầu vào mang đơn vị nhiệt độ; lag pH/NH4/TSS đã qua QC dải vật lý, trần thay đổi là lớp chặn cuối.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--run-name", default=DEFAULT_RUN)
    args = parser.parse_args()
    out = paths.EXPERIMENT_OUTPUT_DIR / args.run_name
    bundle_path = runtime.MODEL_DIR / runtime.TEMPERATURE_BUNDLE_FILE
    if out.exists():
        raise FileExistsError(f"refusing_existing_run_dir:{out}")
    if bundle_path.exists():
        raise FileExistsError(f"refusing_to_overwrite_bundle:{bundle_path}")
    out.mkdir(parents=True)
    sha = _sha256(args.history)
    raw = load_sensor_data(args.history, STATION)

    run_benchmark(args.history, STATION, out / "benchmark", write_predictions=True,
                  selected_feature_sets=("B0_lags", "B4_quality", "B4_quality_nopH"), selected_models=("ridge",),
                  selected_targets=("Temperature", "TSS"), selected_horizons=(HORIZON,), prediction_models=("ridge",))
    gate = gate16_report(out / "benchmark")["gate"]

    frame, all_features = build_frame(raw, "Temperature", HORIZON, FEATURE_SET, station=STATION)
    features = feature_subset(all_features, "Temperature", FEATURE_SET)
    if features != b4_feature_names("Temperature"):
        raise AssertionError("runtime_feature_order_differs_from_research")
    check, _ = lockbox_runtime_check(frame, features)
    (out / "lockbox_runtime_check.json").write_text(json.dumps(check, indent=1), encoding="utf-8")

    temp, _ = monthly_temperature(raw, frame, features)
    temp.to_csv(out / "monthly_temperature.csv", index=False)
    tss = monthly_tss(raw)
    tss.to_csv(out / "monthly_tss.csv", index=False)

    final = make_bundle(frame, features, fit_scope="full_history",
                        training_data={"path": str(args.history.relative_to(paths.ARTIFACTS_DIR.parent)) if args.history.is_relative_to(paths.ARTIFACTS_DIR.parent) else str(args.history), "sha256": sha},
                        trained_at=datetime.now(timezone.utc).isoformat(), trained_by="experiments/sensor_future_15m_fix.py",
                        evaluation_run=args.run_name,
                        lockbox_gate16={str(k): v for k, v in gate[(gate.target == "Temperature") & (gate.feature_set == FEATURE_SET)].iloc[0].to_dict().items()})
    joblib.dump(final, bundle_path)
    meta = {key: value for key, value in final.items() if key != "model"}
    meta["bundle_file"] = bundle_path.name
    meta["bundle_sha256"] = _sha256(bundle_path)
    (out / "bundle_metadata.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    (out / "NOTES.md").write_text(notes(args.run_name, args.history, sha, gate, check, temp, tss, final, bundle_path), encoding="utf-8")
    manifest = {"run": args.run_name, "script": "experiments/sensor_future_15m_fix.py", "station": STATION, "history": str(args.history),
                "history_sha256": sha, "horizon_minutes": HORIZON, "feature_set": FEATURE_SET, "model_version": MODEL_VERSION,
                "range_margin_c": RANGE_MARGIN_C, "max_abs_change_c": MAX_ABS_CHANGE_C, "runtime_changed": True,
                "bundle": str(bundle_path.relative_to(paths.PROJECT_ROOT)), "created_at": datetime.now(timezone.utc).isoformat()}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(gate.to_string(index=False))
    print(json.dumps({k: v for k, v in check.items() if k.startswith(("mae_", "skill_", "dm_", "guard_"))}, indent=1))
    print(temp.to_string(index=False))
    print(tss.to_string(index=False))


if __name__ == "__main__":
    main()
