import pandas as pd
import pytest

from core.storm_advisory import (beaufort, bearing_deg, evaluate_storm_advisory, haversine_km, load_ibtracs,
                                 qd18_risk_level, quadrant, rankine_wind_ms, site_action, site_exposure,
                                 storm_class_vi, storm_passages, to_ms)


@pytest.mark.parametrize("speed, level", [(0.0, 0), (10.79, 5), (10.8, 6), (17.1, 7), (17.2, 8),
                                          (24.5, 10), (32.7, 12), (56.1, 17), (80.0, 17)])
def test_beaufort_bounds(speed, level):
    assert beaufort(speed) == level


def test_beaufort_missing():
    assert beaufort(None) is None
    assert beaufort(float("nan")) is None


def test_to_ms_units():
    assert to_ms(36, "km/h") == pytest.approx(10.0)
    assert to_ms(10, "kn") == pytest.approx(5.14444)
    assert to_ms(5, "m/s") == 5.0
    with pytest.raises(ValueError):
        to_ms(1, "furlong/h")


@pytest.mark.parametrize("level, cls", [(5, None), (6, "áp thấp nhiệt đới"), (9, "bão"),
                                        (11, "bão mạnh"), (15, "bão rất mạnh"), (16, "siêu bão")])
def test_storm_class(level, cls):
    assert storm_class_vi(level) == cls


@pytest.mark.parametrize("level, risk", [(None, None), (5, None), (6, 3), (11, 3), (12, 4), (15, 4), (16, 5)])
def test_qd18_level(level, risk):
    assert qd18_risk_level(level) == risk


def test_site_action_tiers():
    assert site_action(5)["tier"] == 0
    assert site_action(7)["tier"] == 1
    assert site_action(9)["tier"] == 2
    assert site_action(11)["tier"] == 3
    assert site_action(13)["tier"] == 4
    assert site_action(13)["basis"] == "proposal_needs_expert_review"
    assert site_action(None)["tier"] is None


SITE = (20.719, 107.043)


def _row(**kw):
    base = {"SID": "S1", "SEASON": 2024, "NAME": "TEST", "ISO_TIME": pd.Timestamp("2024-09-07T06:00Z"),
            "LAT": 20.9, "LON": 107.1, "TOKYO_WIND": 90.0, "USA_WIND": 110.0, "USA_RMW": 15.0}
    for q in ("NE", "SE", "SW", "NW"):
        base.update({f"USA_R34_{q}": float("nan"), f"USA_R50_{q}": float("nan"), f"USA_R64_{q}": float("nan")})
    base.update(kw)
    return pd.Series(base)


def test_haversine_one_degree():
    assert haversine_km(0.0, 0.0, 0.0, 1.0) == pytest.approx(111.19, abs=0.05)


def test_bearing_and_quadrant():
    assert quadrant(bearing_deg(0, 0, 1, 0)) == "NE"      # due north
    assert quadrant(bearing_deg(0, 0, 0, 1)) == "SE"      # due east
    assert quadrant(bearing_deg(0, 0, -1, 0)) == "SW"     # due south
    assert quadrant(bearing_deg(0, 0, 0, -1)) == "NW"     # due west


def test_rankine_profile():
    assert rankine_wind_ms(40.0, 30.0, 30.0) == pytest.approx(40.0)
    assert rankine_wind_ms(40.0, 30.0, 15.0) == pytest.approx(20.0)
    assert rankine_wind_ms(40.0, 30.0, 120.0) == pytest.approx(20.0)


def test_exposure_inside_r64():
    out = site_exposure(_row(USA_R64_SW=45.0, USA_R64_NE=45.0, USA_R64_SE=45.0, USA_R64_NW=45.0), *SITE)
    assert out["exposure_method"] == "wind_radii"
    assert out["site_wind_ms"] == pytest.approx(64 * 0.514444 * 0.93)
    assert out["site_beaufort"] == 11


def test_exposure_outside_r34_is_capped():
    far = _row(LAT=21.9, LON=107.1, USA_RMW=60.0, **{f"USA_R34_{q}": 10.0 for q in ("NE", "SE", "SW", "NW")})
    out = site_exposure(far, *SITE)
    assert out["exposure_method"] == "rankine_capped_by_r34"
    assert out["site_beaufort"] <= beaufort(34 * 0.514444 * 0.93)


def test_exposure_rankine_when_no_radii():
    out = site_exposure(_row(), *SITE)
    assert out["exposure_method"] == "rankine"
    assert out["storm_wind_source"] == "tokyo_10min"
    assert out["site_wind_ms"] > 0


def test_storm_passages_keeps_peak_and_drops_far():
    # 58 km out, outside a 10-nmi R34 -> capped at the 34-kt level, below near_b's 64-kt exposure
    near_a = _row(ISO_TIME=pd.Timestamp("2024-09-07T03:00Z"), LAT=20.7, LON=107.6,
                  **{f"USA_R34_{q}": 10.0 for q in ("NE", "SE", "SW", "NW")})
    near_b = _row(**{f"USA_R64_{q}": 45.0 for q in ("NE", "SE", "SW", "NW")})
    far = _row(SID="S2", NAME="FAR", LAT=10.0, LON=120.0)
    out = storm_passages(pd.DataFrame([near_a, near_b, far]), *SITE, radius_km=500)
    assert list(out["SID"]) == ["S1"]
    row = out.iloc[0]
    assert row["peak_time"] == pd.Timestamp("2024-09-07T06:00Z")
    assert row["site_beaufort"] == 11
    assert row["qd18_level"] == 4               # TOKYO 90 kt -> 46.3 m/s -> cấp 15
    assert row["source"] == "best_track_oracle"


def test_load_ibtracs_skips_units_row(tmp_path):
    csv = tmp_path / "ib.csv"
    csv.write_text("SID,SEASON,NAME,ISO_TIME,LAT,LON,TOKYO_WIND,USA_WIND,USA_RMW\n"
                   " ,Year, , ,degrees_north,degrees_east,kts,kts,nmile\n"
                   "S1,2024,YAGI,2024-09-07 06:00:00,20.9,107.1,90, ,15\n", encoding="utf-8")
    df = load_ibtracs(csv)
    assert len(df) == 1
    assert str(df["ISO_TIME"].dt.tz) == "UTC"
    assert pd.isna(df.loc[0, "USA_WIND"])
    assert "USA_R64_SW" in df.columns          # missing radius columns are added as NaN


NOW = pd.Timestamp("2026-07-02T00:00Z")


def _weather(speeds_kmh, status="ready"):
    times = pd.date_range("2026-07-02T07:00", periods=len(speeds_kmh), freq="h").strftime("%Y-%m-%dT%H:%M").tolist()
    return {"status": status, "timezone": "Asia/Ho_Chi_Minh", "retrieved_at": "2026-07-02T00:00:00+00:00",
            "hourly_units": {"wind_speed_10m": "km/h"}, "hourly": {"time": times, "wind_speed_10m": speeds_kmh}}


def test_storm_advisory_levels():
    out = evaluate_storm_advisory(_weather([20.0] * 10 + [70.0] + [30.0] * 10), now=NOW)
    assert out["max_wind_ms"] == pytest.approx(70 / 3.6, abs=0.01)
    assert out["site_beaufort"] == 8
    assert out["action"]["tier"] == 2
    assert "qd18_level" not in out and "storm_class_vi" not in out   # no storm source on this path
    assert out["source"] == "forecast"
    assert out["used_by_alerts"] is False and out["notification_eligible"] is False


def test_storm_advisory_keeps_stale_status():
    assert evaluate_storm_advisory(_weather([10.0] * 5, status="stale"), now=NOW)["status"] == "stale"


def test_storm_advisory_unavailable():
    assert evaluate_storm_advisory({"status": "unavailable"}, now=NOW)["status"] == "unavailable"
    assert evaluate_storm_advisory(_weather([]), now=NOW)["status"] == "unavailable"
