import numpy as np
import pandas as pd

from experiments import train_sensor_future_v2 as tr


def _raw(periods=80_000):
    time = pd.date_range("2026-06-01", periods=periods, freq="min", tz="UTC")
    rng = np.random.default_rng(1)
    return pd.DataFrame({"fetchedAt": time, "Temperature": 29 + np.sin(np.arange(periods) / 300) + rng.normal(0, .05, periods),
                         "pH": 7.9 + rng.normal(0, .02, periods), "NH4": 60 + rng.normal(0, 1, periods), "TSS": 10 + rng.normal(0, 1, periods)})


def test_truncate_local_date_keeps_whole_local_day():
    raw = pd.DataFrame({"fetchedAt": pd.to_datetime(["2026-09-18 16:59", "2026-09-18 17:00", "2026-09-19 03:00"], utc=True)})
    kept = tr.truncate_local_date(raw, "2026-09-18")
    # 2026-09-18 17:00 UTC is 2026-09-19 00:00 local
    assert list(kept["fetchedAt"].astype(str)) == ["2026-09-18 16:59:00+00:00"]
    assert tr.truncate_local_date(raw, None) is raw


def test_bundle_name_encodes_data_and_features():
    a = tr.bundle_name("pH", "B6_tide", 360, "eb84b513e5a1", ["x", "y"])
    b = tr.bundle_name("pH", "B6_tide", 360, "eb84b513e5a1", ["x", "z"])
    assert a.startswith("haiphong_ph_ridge_B6_tide_360m_deb84b513_f")
    assert a != b


def test_train_one_returns_oos_calibration_and_feature_list():
    bundle, entry = tr.train_one(_raw(), "Temperature", 180, "B4_quality", "aci_scaled", "0" * 64, None, None)
    assert bundle["features"] == entry["features"]
    assert bundle["aci_gamma"] == 0.005 * 15 / 180
    assert entry["calibration"]["folds_used"] == [3, 4, 5]
    assert len(bundle["calibration_scores"]) == entry["calibration"]["rows"] > 0
    assert np.all(np.diff(bundle["calibration_scores"]) >= 0)
    assert set(bundle["calibration_scores_by_night"]) == {0, 1}
    q = entry["calibration_quantiles"]
    assert q["pi90"]["static"] >= q["pi80"]["static"]
    prediction = bundle["model"].predict(pd.DataFrame([dict.fromkeys(bundle["features"], 0.0)]))
    assert np.isfinite(prediction).all()
