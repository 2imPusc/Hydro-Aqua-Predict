import pandas as pd
import pytest

from core.storm_advisory import (KNOT_MS, beaufort, bearing_deg, evaluate_storm_advisory, haversine_km, interpolate_track,
                                 load_ibtracs,
                                 qd18_risk_level, quadrant, rankine_wind_ms, site_action, site_exposure, storm_wind_ms,
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
    out = storm_passages(pd.DataFrame([near_a, near_b, far]), *SITE, radius_km=500, interp_step=None)
    assert list(out["SID"]) == ["S1"]
    row = out.iloc[0]
    assert row["peak_time"] == pd.Timestamp("2024-09-07T06:00Z")
    assert row["site_beaufort"] == 11
    assert row["qd18_level"] == 4               # TOKYO 90 kt -> 46.3 m/s -> cấp 15
    assert row["source"] == "best_track_oracle"
    assert row["storm_wind_source"] == "tokyo_10min"
    assert bool(row["site_wind_lower_bound"]) is True        # wind_radii gives only a floor
    for col in ("storm_beaufort_max", "qd18_level", "site_beaufort"):
        assert str(out[col].dtype) == "Int64"


def test_storm_passages_intensity_only_within_coastal_radius():
    near = _row(TOKYO_WIND=60.0)                              # 30.9 m/s -> cấp 11
    far = _row(ISO_TIME=pd.Timestamp("2024-09-06T06:00Z"), LAT=24.77, LON=107.043, TOKYO_WIND=105.0)
    out = storm_passages(pd.DataFrame([near, far]), *SITE, radius_km=500, interp_step=None)
    assert len(out) == 1 and 440 < haversine_km(24.77, 107.043, *SITE) < 460
    assert out.iloc[0]["storm_beaufort_max"] == 11
    assert out.iloc[0]["qd18_level"] == 3
    assert out.iloc[0]["min_dist_km"] < 50


def test_storm_passages_no_row_in_coastal_radius_is_na():
    far = _row(LAT=24.77, LON=107.043, TOKYO_WIND=105.0)
    out = storm_passages(pd.DataFrame([far]), *SITE, radius_km=500)
    assert len(out) == 1
    row = out.iloc[0]
    assert pd.isna(row["storm_beaufort_max"]) and pd.isna(row["qd18_level"]) and row["storm_class_vi"] is None
    assert bool(row["site_wind_lower_bound"]) is False


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


def test_storm_advisory_unknown_unit_is_unavailable():
    w = _weather([20.0] * 5)
    w["hourly_units"] = {"wind_speed_10m": "furlong/h"}
    out = evaluate_storm_advisory(w, now=NOW)
    assert out["status"] == "unavailable" and out["reason"] == "unknown_wind_unit"
    assert out["used_by_alerts"] is False


def test_storm_advisory_passes_through_stale_info():
    w = _weather([10.0] * 5, status="stale")
    w.update({"stale_age_seconds": 7200, "reason": "fetch_failed"})
    out = evaluate_storm_advisory(w, now=NOW)
    assert out["status"] == "stale" and out["stale_age_seconds"] == 7200 and out["reason"] == "fetch_failed"
    assert "stale_age_seconds" not in evaluate_storm_advisory(_weather([10.0] * 5), now=NOW)


_NAN = float("nan")


def test_storm_wind_precedence_tokyo_wins():
    row = _row(TOKYO_WIND=50.0, HKO_WIND=60.0, USA_WIND=70.0, CMA_WIND=80.0)
    assert storm_wind_ms(row) == (pytest.approx(50.0 * KNOT_MS), "tokyo_10min")


def test_storm_wind_hko_fallback_beats_usa():
    row = _row(TOKYO_WIND=_NAN, HKO_WIND=60.0, USA_WIND=70.0, CMA_WIND=80.0)
    assert storm_wind_ms(row) == (pytest.approx(60.0 * KNOT_MS), "hko_10min")


def test_storm_wind_usa_beats_cma():
    row = _row(TOKYO_WIND=_NAN, HKO_WIND=_NAN, USA_WIND=70.0, CMA_WIND=80.0)
    assert storm_wind_ms(row, 0.93) == (pytest.approx(70.0 * KNOT_MS * 0.93), "usa_1min_scaled")


def test_storm_wind_cma_last_resort_unscaled():
    row = _row(TOKYO_WIND=_NAN, HKO_WIND=_NAN, USA_WIND=_NAN, CMA_WIND=58.0)
    assert storm_wind_ms(row, 0.93) == (pytest.approx(58.0 * KNOT_MS), "cma_2min_unscaled")


def test_site_exposure_uses_cma_when_only_intensity():
    out = site_exposure(_row(TOKYO_WIND=_NAN, USA_WIND=_NAN, CMA_WIND=58.0), *SITE)
    assert out["exposure_method"] != "no_intensity"
    assert out["storm_wind_source"] == "cma_2min_unscaled"


def test_load_ibtracs_coerces_cma_hko(tmp_path):
    csv = tmp_path / "t.csv"
    csv.write_text("SID,SEASON,NAME,ISO_TIME,LAT,LON,TOKYO_WIND,HKO_WIND,CMA_WIND\n"
                   ",,,,degrees_north,degrees_east,kts,kts,kts\n"
                   "S1,2024,X,2024-09-07 06:00:00,20.9,107.1, ,45,50\n", encoding="utf-8")
    df = load_ibtracs(csv)
    assert df.loc[0, "HKO_WIND"] == 45.0 and df.loc[0, "CMA_WIND"] == 50.0
    assert pd.isna(df.loc[0, "TOKYO_WIND"])


def test_interpolation_catches_eyewall_between_rows():
    # two rows 3 h apart, ~30 km either side of the site along a meridian; RMW 10 nmi, no radii
    a = _row(ISO_TIME=pd.Timestamp("2024-09-07T03:00Z"), LAT=SITE[0] - 0.27, LON=SITE[1], TOKYO_WIND=80.0,
             USA_WIND=float("nan"), USA_RMW=10.0)
    b = _row(ISO_TIME=pd.Timestamp("2024-09-07T06:00Z"), LAT=SITE[0] + 0.27, LON=SITE[1], TOKYO_WIND=80.0,
             USA_WIND=float("nan"), USA_RMW=10.0)
    track = pd.DataFrame([a, b])
    storm_bf = beaufort(80 * KNOT_MS)
    raw = storm_passages(track, *SITE, interp_step=None).iloc[0]
    dense = storm_passages(track, *SITE, interp_step="30min").iloc[0]
    assert raw["site_beaufort"] < storm_bf - 1
    assert dense["site_beaufort"] >= storm_bf - 1
    assert dense["min_dist_km"] < raw["min_dist_km"]


def test_interpolate_track_keeps_nan_ends_and_flags():
    rows = [_row(ISO_TIME=pd.Timestamp("2024-09-07T00:00Z"), LAT=20.0, LON=107.0, TOKYO_WIND=float("nan"), USA_WIND=60.0),
            _row(ISO_TIME=pd.Timestamp("2024-09-07T03:00Z"), LAT=21.0, LON=107.0, TOKYO_WIND=80.0, USA_WIND=100.0)]
    out = interpolate_track(pd.DataFrame(rows), "1h")
    assert list(out["interpolated"]) == [False, True, True, False]
    assert out["TOKYO_WIND"].isna().iloc[:3].all() and out["TOKYO_WIND"].iloc[3] == 80.0
    assert out["USA_WIND"].iloc[1] == pytest.approx(73.333, abs=0.01)
    assert out["LAT"].iloc[1] == pytest.approx(20.3333, abs=1e-3)
    assert (out["SID"] == "S1").all()


def test_interpolate_track_original_nan_stays_nan():
    times = ["2024-09-07T00:00Z", "2024-09-07T02:00Z", "2024-09-07T04:00Z"]
    winds = [50.0, float("nan"), 70.0]
    rows = [_row(ISO_TIME=pd.Timestamp(t), LAT=20.0 + i, LON=107.0, TOKYO_WIND=w) for i, (t, w) in enumerate(zip(times, winds))]
    out = interpolate_track(pd.DataFrame(rows), "1h")
    assert list(out["interpolated"]) == [False, True, False, True, False]
    assert out["TOKYO_WIND"].iloc[0] == 50.0 and out["TOKYO_WIND"].iloc[4] == 70.0
    assert out["TOKYO_WIND"].iloc[1:4].isna().all()
    assert out["LAT"].notna().all()


def test_interpolate_track_duplicate_time_keeps_fullest_row():
    t = pd.Timestamp("2024-09-07T00:00Z")
    sparse = _row(ISO_TIME=t, LAT=20.0, LON=107.0, TOKYO_WIND=float("nan"), USA_WIND=float("nan"))
    full = _row(ISO_TIME=t, LAT=20.0, LON=107.0, TOKYO_WIND=65.0, USA_WIND=70.0)
    nxt = _row(ISO_TIME=pd.Timestamp("2024-09-07T02:00Z"), LAT=21.0, LON=107.0, TOKYO_WIND=65.0, USA_WIND=70.0)
    for order in ([sparse, full, nxt], [full, sparse, nxt]):
        out = interpolate_track(pd.DataFrame(order), "1h")
        assert len(out) == 3 and out["TOKYO_WIND"].iloc[0] == 65.0
