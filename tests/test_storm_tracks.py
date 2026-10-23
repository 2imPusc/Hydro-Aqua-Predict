"""core.storm_tracks: ensemble TC-track summaries for the basin storm watch (Track D)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from core import paths
from core import storm_tracks as st

NB1 = (20.71894, 107.04264)
KM_PER_DEG = 111.195


def _member_track(member, lat0, lon0, dlat, dlon, hours=range(0, 133, 6), storm_id="36W", name="CHAMPI",
                  observed=True):
    rows = []
    for h in hours:
        rows.append({"storm_id": storm_id, "name": name, "member": member, "hour": h,
                     "lat": lat0 + dlat * h / 6, "lon": lon0 + dlon * h / 6, "observed": observed})
    return rows


def _ensemble(n_hit=3, n_miss=7):
    """Members heading straight west along NB1's latitude ("hit") or recurving north ("miss")."""
    rows = []
    for m in range(n_hit):
        # start 15 deg east of NB1, 1 deg/6 h westward -> crosses 500 km at ~61 h, 200 km at ~79 h
        rows += _member_track(f"ens{m:02d}", NB1[0], NB1[1] + 15, 0.0, -1.0)
    for m in range(n_hit, n_hit + n_miss):
        rows += _member_track(f"ens{m:02d}", NB1[0], NB1[1] + 15, 1.0, 0.0)
    return pd.DataFrame(rows)


def test_member_probabilities_share_of_members_hour0_excluded():
    tr = _ensemble(3, 7)
    p = st.member_probabilities(tr, *NB1)
    assert p["p500_120"] == pytest.approx(0.3)
    assert p["p200_120"] == pytest.approx(0.3)
    assert p["p500_24"] == 0.0
    assert p["n_members"] == 10
    # a storm sitting on the site at hour 0 only does not count (storm_basin rule: 0 < hour <= H)
    on_site = pd.DataFrame(_member_track("ens00", NB1[0], NB1[1], 5.0, 0.0, hours=[0, 6]))
    assert st.member_probabilities(on_site, *NB1)["p500_120"] == 0.0


def test_member_probabilities_explicit_denominator():
    tr = _ensemble(3, 7)
    assert st.member_probabilities(tr, *NB1, n_members=51)["p500_120"] == pytest.approx(3 / 51)


def test_summarize_storm_median_quantities():
    tr = _ensemble(6, 4)
    s = st.summarize_storm(tr, *NB1, run_time="2026-10-22T12:00:00Z")
    assert s["id"] == "36W" and s["name"] == "CHAMPI"
    assert s["members"] == 10
    assert s["p_within_500km_120h"] == pytest.approx(0.6)
    # hit members cross 500 km at ~61 h (fixes are 6-hourly) -> first fix inside: 66 h
    assert s["eta_hours_median"] == 66
    assert s["eta_members"] == 6
    assert s["closest_approach_km_median"] < 50
    assert s["run_time"] == "2026-10-22T12:00:00Z"
    first = s["track_median"][0]
    assert first[0] == pytest.approx(NB1[1] + 15, abs=1e-3) and first[1] == pytest.approx(NB1[0], abs=1e-3)
    assert first[2] == "2026-10-22T12:00:00Z"
    assert s["track_median"][1][2] == "2026-10-22T18:00:00Z"


def test_summarize_storm_eta_none_when_no_member_enters():
    tr = _ensemble(0, 5)
    s = st.summarize_storm(tr, *NB1, run_time="2026-10-22T12:00:00Z")
    assert s["p_within_500km_120h"] == 0.0
    assert s["eta_hours_median"] is None


def test_median_track_drops_steps_with_too_few_members():
    rows = _member_track("ens00", 15, 130, 0, -1, hours=range(0, 49, 6))
    rows += _member_track("ens01", 15, 130, 0, -1, hours=range(0, 13, 6))
    rows += _member_track("ens02", 15, 130, 0, -1, hours=range(0, 13, 6))
    s = st.summarize_storm(pd.DataFrame(rows), *NB1, run_time="2026-10-22T00:00:00Z")
    hours = [pt[2] for pt in s["track_median"]]
    assert hours[-1] == "2026-10-22T12:00:00Z"  # beyond 12 h only 1/3 of members remain


def test_median_track_handles_dateline():
    rows = _member_track("ens00", 20, 179.5, 0, 1.0, hours=[0, 6])
    rows += _member_track("ens01", 20, -179.5, 0, 1.0, hours=[0, 6])
    s = st.summarize_storm(pd.DataFrame(rows), *NB1, run_time="2026-10-22T00:00:00Z")
    lon0 = s["track_median"][0][0]
    assert abs(abs(lon0) - 180.0) < 1e-6


def test_summarize_run_splits_observed_and_genesis():
    obs = _ensemble(3, 7)
    gen = pd.DataFrame(
        _member_track("ens00", NB1[0], NB1[1] + 8, 0, -1, hours=range(12, 61, 6), storm_id="70W", name="70W",
                      observed=False)
        + _member_track("ens05", 10, 150, 0, -1, hours=range(12, 61, 6), storm_id="70W", name="70W",
                        observed=False))
    out = st.summarize_run(pd.concat([obs, gen]), *NB1, run_time="2026-10-22T12:00:00Z", ensemble_size=51)
    assert [s["id"] for s in out["storms"]] == ["36W"]
    g = out["genesis"]
    assert g["n_member_tracks"] == 2
    assert g["p_within_500km_120h"] == pytest.approx(1 / 51, abs=1e-4)
    assert out["max_p_within_500km_120h"] == pytest.approx(0.3)
    assert out["driving_storm"] == "36W"


def test_summarize_run_empty():
    out = st.summarize_run(pd.DataFrame(columns=st.TRACK_COLUMNS), *NB1, run_time="2026-10-22T12:00:00Z")
    assert out["storms"] == [] and out["max_p_within_500km_120h"] == 0.0 and out["driving_storm"] is None


def test_tier_fallback_uses_default_thresholds():
    cfg = st.load_alert_config()
    assert "storm_watch" in cfg["hazards"]
    assert st.watch_tier(0.0, cfg) == 0
    assert st.watch_tier(0.3, cfg) == 1
    assert st.watch_tier(0.59, cfg) == 1
    assert st.watch_tier(0.6, cfg) == 2
    assert st.watch_tier(None, cfg) is None


def test_watch_record_contract_fields():
    cfg = json.loads(json.dumps(st.load_alert_config()))
    summary = st.summarize_run(_ensemble(3, 7), *NB1, run_time="2026-10-22T12:00:00Z", ensemble_size=51)
    rec = st.watch_record({"id": "NB1", "lat": NB1[0], "lon": NB1[1], "exposure_class": "exposed"}, summary,
                          cfg, run_time="2026-10-22T12:00:00Z", issued_at="2026-10-22T20:00:00Z",
                          inputs={"sha256": "x"})
    for key in ("issued_at", "station", "exposure_class", "hazard", "valid_from", "valid_to", "lead_hours", "value",
                "unit", "tier", "action_vi", "inputs", "data_status", "config_version"):
        assert key in rec
    assert rec["hazard"] == "storm_watch" and rec["tier"] == 1
    assert rec["valid_to"] == "2026-10-27T12:00:00Z" and rec["lead_hours"] == 120
    assert rec["used_by_alerts"] is False and rec["notification_eligible"] is False
    assert rec["basis"] == "theory_only_unvalidated"
    assert rec["data_status"] == "fresh"
    assert rec["inputs"]["source"] == "ecmwf_opendata" and rec["inputs"]["storm_id"] == "36W"
    assert rec["inputs"]["sha256"] == "x"


def test_watch_record_stale_and_skip():
    cfg = st.load_alert_config()
    summary = st.summarize_run(_ensemble(3, 7), *NB1, run_time="2026-10-20T00:00:00Z")
    rec = st.watch_record({"id": "NB1", "lat": NB1[0], "lon": NB1[1]}, summary, cfg,
                          run_time="2026-10-20T00:00:00Z", issued_at="2026-10-22T20:00:00Z")
    assert rec["data_status"] == "stale"
    skip = st.watch_record({"id": "NB1", "lat": NB1[0], "lon": NB1[1]}, None, cfg, run_time=None,
                           issued_at="2026-10-22T20:00:00Z", skip_reason="no_run_available")
    assert skip["tier"] is None and skip["skip_reason"] == "no_run_available"
    assert skip["data_status"] == "unavailable" and skip["value"] is None


def test_validation_against_tigge_style_rows():
    """Rows in experiments/tigge_tracks.py column layout go through unchanged (member/hour/lat/lon)."""
    tg = pd.DataFrame({"base_time": "2024-09-03T00:00:00", "member": ["ens00"] * 3 + ["ens01"] * 3,
                       "disturbance_id": "d", "name": "YAGI", "number": "11W", "hour": [0, 48, 96] * 2,
                       "valid_time": "x", "lat": [17, 19, 20.7, 17, 22, 27], "lon": [118, 112, 107.1, 118, 118, 118],
                       "pmin_hpa": np.nan, "vmax_ms": np.nan})
    p = st.member_probabilities(tg, *NB1)
    assert p["p200_120"] == 0.5 and p["p200_48"] == 0.0 and p["n_members"] == 2


def test_merge_duplicate_tracks_relabels_repeat_of_observed_storm():
    obs = _ensemble(1, 1)  # ens00 hits, ens01 misses
    # ens01 also carries a 7xW copy that starts on 36W at hour 0 but heads for NB1: union counts it (storm_basin)
    dup = pd.DataFrame(_member_track("ens01", NB1[0], NB1[1] + 15, 0.0, -1.0, storm_id="70W", name="70W",
                                     observed=False))
    far = pd.DataFrame(_member_track("ens01", 5, 150, 0, -1, hours=range(0, 61, 6), storm_id="71W", name="71W",
                                     observed=False))
    merged = st.merge_duplicate_tracks(pd.concat([obs, dup, far], ignore_index=True))
    assert set(merged.loc[merged["storm_id"] == "36W", "member"]) == {"ens00", "ens01"}
    assert (merged["storm_id"] == "71W").sum() == len(far)
    out = st.summarize_run(pd.concat([obs, dup, far], ignore_index=True), *NB1, run_time="2026-10-22T12:00:00Z")
    assert [s["id"] for s in out["storms"]] == ["36W"]
    assert out["storms"][0]["p_within_500km_120h"] == 1.0 and out["storms"][0]["members"] == 2
    assert out["genesis"]["n_member_tracks"] == 1


_TIGGE_2024 = paths.HAZARD_DATA_DIR / "tigge" / "ecmf_cxml_wp_tracks_20240501_20241215_00z_fetched20261023.csv"
_TIGGE_PROB = paths.EXPERIMENT_OUTPUT_DIR / "storm-basin-20261023b" / "tigge_ens_prob.csv"


@pytest.mark.requires_data
@pytest.mark.skipif(not (_TIGGE_2024.exists() and _TIGGE_PROB.exists()), reason="TIGGE extract / storm-basin run absent")
def test_agrees_with_storm_basin_tigge_eval_yagi():
    """Yagi 2024-09-03 00 UTC TIGGE members -> same probabilities as storm_basin.tigge_eval (all R x H)."""
    tg = pd.read_csv(_TIGGE_2024, low_memory=False)
    g = tg[(tg["name"].astype(str).str.upper() == "YAGI") & (tg["base_time"] == "2024-09-03T00:00:00")
           & tg["member"].str.startswith("ens")]
    assert g["disturbance_id"].nunique() == 1
    ref = pd.read_csv(_TIGGE_PROB)
    ref = ref[(ref["base_time"].str.startswith("2024-09-03 00:00")) & (ref["SID"] == "2024244N09137")]
    assert len(ref) == 1
    p = st.member_probabilities(g, *NB1)
    assert p["n_members"] == int(ref["n_members"].iloc[0]) == 51
    for radius in (200, 500):
        for h in (24, 48, 72, 96, 120):
            assert p[f"p{radius}_{h}"] == pytest.approx(ref[f"ens_p{radius}_{h}"].iloc[0], abs=1e-12)
