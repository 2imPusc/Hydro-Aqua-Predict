import numpy as np
import pandas as pd

from experiments.forecast_gate16_report import gate16_summary, lockbox_check
from experiments.forecast_sensor_v2 import load_sensor_data, mask_ph_suspect


def _metrics(folds: int, ridge_mae: float = 0.8):
    rows = []
    for fold in range(1, folds + 1):
        rows.append({"split": "rolling", "fold": fold, "target": "T", "horizon_minutes": 60, "feature_set": "B0_lags", "model": "persistence", "mae": 1.0, "n_test": 10})
        rows.append({"split": "rolling", "fold": fold, "target": "T", "horizon_minutes": 60, "feature_set": "B0_lags", "model": "ridge", "mae": ridge_mae, "n_test": 10})
    rows.append({"split": "lockbox", "fold": 0, "target": "T", "horizon_minutes": 60, "feature_set": "B0_lags", "model": "persistence", "mae": 1.0, "n_test": 50})
    rows.append({"split": "lockbox", "fold": 0, "target": "T", "horizon_minutes": 60, "feature_set": "B0_lags", "model": "ridge", "mae": ridge_mae, "n_test": 50})
    return pd.DataFrame(rows)


DM = pd.DataFrame([{"target": "T", "horizon_minutes": 60, "feature_set": "B0_lags", "model": "ridge", "dm_stat": -5.0, "p_value": 1e-6}])


def test_gate16_passes_with_five_folds_and_significant_dm():
    gate = gate16_summary(_metrics(5), DM)
    assert gate.iloc[0]["gate"] == "PASS" and gate.iloc[0]["folds_won"] == "5/5"
    assert gate.iloc[0]["skill_pct"] == 20.0 and gate.iloc[0]["n_lock"] == 50


def test_gate16_fails_with_fewer_than_five_folds():
    gate = gate16_summary(_metrics(4), DM)
    assert gate.iloc[0]["folds_won"] == "4/4" and gate.iloc[0]["gate"] == "fail"


def test_lockbox_check_flags_shared_window_and_clear_labels():
    rows = [{"target": "T", "horizon_minutes": 60, "feature_set": fs, "fold": 1, "max_fold_valid_at": "2026-10-01T00:00:00+00:00",
             "lockbox_start": "2026-10-10T00:00:00+00:00", "last_issued_at": "2026-10-24T00:00:00+00:00"} for fs in ("A", "B")]
    check = lockbox_check(rows)
    assert check["fold_labels_clear_of_lockbox"] and check["all_windows_shared"]
    rows[1]["last_issued_at"] = "2026-10-15T00:00:00+00:00"
    assert not lockbox_check(rows)["all_windows_shared"]


def test_ph_qc_masks_out_of_band_and_jumps_only(tmp_path):
    time = pd.date_range("2026-09-01", periods=200, freq="min", tz="UTC")
    ph = np.full(200, 7.9)
    ph[10:20] = 6.8          # out of the 7.0-8.6 band
    ph[150:] = 8.5           # +0.6 jump vs one hour earlier, still in band
    raw = pd.DataFrame({"fetchedAt": time, "pH": ph, "Temperature": 28.0})
    masked = mask_ph_suspect(raw)
    assert masked["pH"].iloc[10:20].isna().all()
    assert masked["pH"].iloc[150:210].isna().all()  # within 60 min of the jump
    assert masked["pH"].iloc[:10].notna().all() and masked["Temperature"].notna().all()
    path = tmp_path / "s.csv"
    raw.to_csv(path, index=False)
    assert load_sensor_data(path, "s")["pH"].notna().all()
    assert load_sensor_data(path, "s", ph_qc=True)["pH"].isna().sum() == masked["pH"].isna().sum()
