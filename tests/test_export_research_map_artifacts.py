"""Research-map export: synthetic run dirs only (no real artifacts needed)."""
import gzip
import json
import math

import pytest

from scripts import export_research_map_artifacts as ex


def _csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(header)] + [",".join("" if v is None else str(v) for v in row) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _strict(path):
    """JSON must be strict (no NaN/Infinity tokens)."""
    def bad(token):
        raise AssertionError(f"non-strict JSON token {token} in {path.name}")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=bad)


def _pairs(detail):
    return [dict(zip(detail["pairs"]["columns"], row)) for row in detail["pairs"]["rows"]]


def _manifest(run):
    (run / "manifest.json").write_text("{}", encoding="utf-8")


def _export(tmp_path, stamp="20261017-1200", **kw):
    exp = tmp_path / "experiments"
    exp.mkdir(exist_ok=True)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    return ex.export(exp, tmp_path / "out", data_dir=data, research_log=kw.pop("research_log", None), stamp=stamp, **kw)


GATE_HEADER = ["target", "horizon_minutes", "feature_set", "n_lock", "lock_mae", "pers_mae", "skill_pct",
               "rolling_skill_pct_mean", "folds_won", "dm_p", "dm_stat", "gate"]


def _forecast_runs(exp):
    _csv(exp / ex.A1_RUN / "gate16_summary.csv", GATE_HEADER, [
        ["Temperature", 180, "B4_quality", 100, 0.71, 0.92, 22.8, 23.4, "5/5", 3.5e-17, -8.4, "PASS"],
        ["Temperature", 180, "B4_quality_nopH", 100, 0.74, 0.92, 19.9, 22.5, "5/5", 1.4e-11, -6.7, "PASS"],
    ])
    _csv(exp / ex.A3_RUN / "gate16_summary.csv", GATE_HEADER, [
        ["pH", 180, "B0_lags", 100, 0.046, 0.051, 10.0, 1.1, "4/5", 0.00178, -3.1, "PASS"],
        ["pH", 180, "B4_quality", 100, 0.052, 0.051, -2.1, -12.7, "2/5", 0.694, 0.39, "fail"],
    ])
    cov_header = ["target", "horizon_minutes", "feature_set", "model", "method", "nominal", "coverage", "mean_width",
                  "frac_infinite", "winkler", "coverage_late", "gate_pi80_pass"]
    _csv(exp / ex.CONFORMAL_AMP_RUN / "coverage.csv", cov_header, [
        ["Temperature", 180, "B4_quality", "ridge", "aci_amp", 0.8, 0.81, 1.9, 0.0, 3.1, 0.79, "pass"],
        ["Temperature", 180, "B4_quality", "ridge", "aci_scaled", 0.9, 0.85, "inf", 0.12, "", "", "fail"],
        ["Temperature", 180, "B4_quality", "xgboost", "aci_amp", 0.8, 0.5, 1.0, 0.0, 3.0, 0.5, "fail"],
    ])
    # H1.2 Temperature: rolling folds 1-5 + lockbox fold 0, ridge vs persistence
    rows = []
    for fold in range(1, 6):
        rows.append(["rolling", fold, "Temperature", 60, "B4_quality", "ridge", 0.30 if fold != 3 else 0.50])
        rows.append(["rolling", fold, "Temperature", 60, "B4_quality", "persistence", 0.40])
    rows.append(["lockbox", 0, "Temperature", 60, "B4_quality", "ridge", 0.30])
    rows.append(["lockbox", 0, "Temperature", 60, "B4_quality", "persistence", 0.40])
    _csv(exp / ex.H12_TEMPERATURE_RUN / "metrics_per_fold.csv",
         ["split", "fold", "target", "horizon_minutes", "feature_set", "model", "mae"], rows)
    _csv(exp / ex.H12_TEMPERATURE_RUN / "dm_tests.csv",
         ["target", "horizon_minutes", "feature_set", "model", "n", "mean_loss_diff", "dm_stat", "p_value", "model_better"],
         [["Temperature", 60, "B4_quality", "ridge", 10, -0.1, -5.0, 1e-6, True],
          ["Temperature", 60, "B4_quality", "xgboost", 10, 0.1, 5.0, 1e-6, False]])


def test_empty_inputs_write_manifest_with_reasons_and_no_fabricated_files(tmp_path):
    out = _export(tmp_path)
    manifest = _strict(out / "manifest.json")
    assert manifest["export_version"] == "20261017-1200"
    assert "forecast_benchmark.json" in manifest["omitted"]
    assert manifest["omitted"]["reliability_vn.json"] == "a6_not_exported"
    assert not (out / "forecast_benchmark.json").exists()
    assert not (out / "reliability_vn.json").exists()
    overview = _strict(out / "overview.json")
    assert [d["id"] for d in overview["directions"]] == ["H1", "H2", "H3", "H4"]
    for name, meta in manifest["files"].items():
        assert (out / name).stat().st_size == meta["bytes"]


def test_export_dir_is_write_once(tmp_path):
    _export(tmp_path)
    with pytest.raises(FileExistsError):
        _export(tmp_path)


def test_forecast_benchmark_normalises_and_recomputes_h12_gate(tmp_path):
    _forecast_runs(tmp_path / "experiments")
    out = _export(tmp_path)
    bench = _strict(out / "forecast_benchmark.json")
    assert bench["status"] == "ready" and bench["export_version"] == "20261017-1200"
    a1 = [r for r in bench["temperature"] if r["source_run"] == ex.A1_RUN]
    assert {r["variant"] for r in a1} == {"with_pH", "nopH"}
    assert a1[0]["gate"] == "pass" and a1[0]["horizon_min"] == 180 and a1[0]["folds_won"] == "5/5"
    h12 = [r for r in bench["temperature"] if r["source_run"] == ex.H12_TEMPERATURE_RUN]
    assert len(h12) == 1
    assert h12[0]["folds_won"] == "4/5" and h12[0]["skill"] == 25.0 and h12[0]["gate"] == "pass"
    assert [r["gate"] for r in bench["ph_clean"]] == ["pass", "fail"]
    conf = bench["conformal"]
    assert {r["method"] for r in conf} == {"aci_amp", "aci_scaled"}  # ridge only
    scaled = next(r for r in conf if r["method"] == "aci_scaled")
    assert scaled["width"] is None and scaled["coverage_late"] is None and scaled["level"] == 0.9


def _suitability_runs(exp, data):
    score_header = ["point_id", "A_W_SUM", "N1_W_SUM", "lat", "lon"]
    _csv(exp / ex.SUIT_VN_NEARSHORE_RUN / "scores.csv", score_header,
         [["p1", 0.3, 0.5, 20.5, 106.6], ["p2", 0.6, 0.4, 20.5, 106.7]])
    _csv(exp / ex.SUIT_VN_NEARSHORE_RUN / "criteria_fuzzy.csv", ["point_id", "SWH", "DfS"],
         [["p1", 0.12345, 0.9], ["p2", 0.5, ""]])
    _csv(exp / ex.SUIT_VN_NEARSHORE_RUN / "validation_osm_farms.csv",
         ["variant", "n_farms_marine", "n_matched", "mean_percentile"], [["N1_W_SUM", 31, 22, 0.42]])
    _csv(data / "suitability" / "osm_features.csv", ["osm_type", "osm_id", "kind", "name", "lat", "lon", "tags"],
         [["way", 1, "aquaculture", "farm", 20.8, 107.1, "{}"], ["node", 2, "port", "port", 20.9, 107.0, "{}"]])
    hk_header = ["cell_id", "A_W_SUM", "N1_W_SUM", "lat", "lon", "fcz"]
    _csv(exp / ex.SUIT_HK_RUN / "scores_coast.csv", hk_header, [["c1", 0.5, 0.6, 22.2, 114.2, True]])
    _csv(exp / ex.SUIT_HK_RUN / "criteria_fuzzy_coast.csv", ["cell_id", "SWH"], [["c1", 0.7]])
    _csv(exp / ex.SUIT_HK_RUN / "validation.csv", ["mask", "variant", "auc", "auc_lo", "auc_hi", "n_zones_evaluable"],
         [["coast", "N1_W_SUM", 0.7527, 0.6272, 0.8527, 26], ["etopo", "N1_W_SUM", 0.83, 0.49, 0.97, 6]])
    (data / "foreign" / "hk_epd").mkdir(parents=True)
    (data / "foreign" / "hk_epd" / "fish_culture_zones.csv").write_text(
        'fcz_id,code,name_en,area_sqm,wkt\n1,STK,Sha Tau Kok,180000,"POLYGON ((114.1 22.5, 114.2 22.5, 114.2 22.6, 114.1 22.5))"\n',
        encoding="utf-8")


def test_suitability_vn_and_hk(tmp_path):
    _suitability_runs(tmp_path / "experiments", tmp_path / "data")
    out = _export(tmp_path)
    vn = _strict(out / "suitability_vn_N1_W_SUM.json")
    assert vn["region"] == "vn" and vn["variant"] == "N1_W_SUM" and vn["auc"] is None
    feat = vn["cells"]["features"][0]
    assert feat["geometry"] == {"type": "Point", "coordinates": [106.6, 20.5]}
    assert feat["properties"]["score"] == 0.5 and feat["properties"]["layers"]["SWH"] == 0.123
    assert vn["cells"]["features"][1]["properties"]["layers"]["DfS"] is None
    assert len(vn["farms"]["features"]) == 1  # aquaculture only
    assert any("0.42" in note for note in vn["notes"])
    hk = _strict(out / "suitability_hk_N1_W_SUM.json")
    assert hk["auc"] == 0.753 and hk["auc_ci"] == [0.627, 0.853]
    assert hk["farms"]["features"][0]["geometry"]["type"] == "Polygon"
    assert (out / "suitability_vn_A_W_SUM.json").exists()


def _usgs_like(exp, run, dataset="usgs_sfbay"):
    _csv(exp / run / "stations.csv", ["site", "code", "lat", "lon", "sal_wet_median"],
         [["111", "AAA", 37.5, -122.2, 27.3], ["222", "BBB", 38.0, -121.9, 1.5]])
    rel_header = ["dataset", "anchor", "target", "var", "transfer", "km", "distance_bin", "regime", "dsal", "n_days",
                  "share", "ci_low", "gate80", "gate90", "gate95"]
    _csv(exp / run / "pair_reliability.csv", rel_header, [
        [dataset, "111", "222", "Temp", "raw", 60.8, ">30", "different", 25.8, 400, 0.25163, 0.24, "fail", "fail", "fail"],
        [dataset, "111", "222", "Turbidity", "calibrated_30d", 60.8, ">30", "different", 25.8, 400, 0.5, "", "fail", "fail", "fail"],
    ])
    _csv(exp / run / "radius.csv", ["dataset", "var", "regime", "transfer", "gate", "radius_km", "stop"], [
        [dataset, "Temp", "same", "raw", "gate80", 10.0, "fail@10-20"],
        [dataset, "DO", "all", "calibrated_30d", "gate90", "", "no_data"],
    ])
    _csv(exp / run / "pairs.csv", ["anchor", "target", "km", "regime"], [["111", "222", 60.8, "different"]])
    _manifest(exp / run)


def test_foreign_dataset_normalised_with_coordinates(tmp_path):
    _usgs_like(tmp_path / "experiments", ex.FOREIGN["usgs_sfbay"]["run"])
    out = _export(tmp_path)
    index = _strict(out / "reliability_foreign_index.json")
    ds = next(d for d in index["datasets"] if d["id"] == "usgs_sfbay")
    assert ds["n_stations"] == 2 and ds["redistributable"] is True and ds["scales"] == ["hourly"]
    assert ds["bbox"] == [-122.2, 37.5, -121.9, 38.0]
    assert "U.S. Geological Survey" in ds["credit"]
    detail = _strict(out / "reliability_foreign_usgs_sfbay.json")
    st = {f["properties"]["station"]: f for f in detail["stations"]["features"]}
    assert st["111"]["properties"]["regime_class"] == "transitional"
    assert st["222"]["properties"]["regime_class"] == "estuarine_brackish"
    pairs = _pairs(detail)
    assert {(p["var"], p["transfer"], p["scale"]) for p in pairs} == {("Temp", "raw", "hourly"), ("Turb", "calibrated", "hourly")}
    temp = next(p for p in pairs if p["var"] == "Temp")
    assert temp["same_regime"] is False and temp["share"] == 0.2516
    assert st["222"]["geometry"]["coordinates"] == [-121.9, 38.0]
    radius = {(r["var"], r["gate"]): r for r in detail["radius"]}
    assert radius[("Temp", "gate80")]["radius_km"] == 10.0 and radius[("Temp", "gate80")]["scale"] == "hourly"
    assert radius[("DO", "gate90")]["radius_km"] is None and radius[("DO", "gate90")]["transfer"] == "calibrated"
    assert detail["available"]["vars"] == ["Temp", "Turb"]


def test_mddnr_exports_aggregates_only(tmp_path):
    exp = tmp_path / "experiments"
    run = exp / ex.FOREIGN["mddnr"]["run"]
    _csv(run / "stations.csv", ["station", "name", "lat", "lon", "sal_spring_median"],
         [["BOH", "Long Point", 39.47, -75.88, 0.3], ["BCP", "Church Point", 39.45, -76.23, 0.27]])
    _csv(run / "pair_reliability.csv",
         ["pair_id", "variable", "transfer", "dataset", "share", "ci_low", "gate80", "gate90", "gate95", "anchor", "target",
          "km", "dsal", "regime"],
         [[0, "Sal", "raw", "mddnr", 0.9, 0.85, "pass", "fail", "fail", "BOH", "BCP", 29.8, 0.4, "same"],
          [1, "Sal", "raw", "mddnr", 0.9, 0.85, "pass", "fail", "fail", "BOH", "BCP", 45.0, 0.4, "same"]])
    _csv(run / "radius.csv", ["dataset", "var", "regime", "transfer", "gate", "radius_km", "stop"],
         [["mddnr", "Sal", "any", "calibrated", 80, 30.0, "all_pass"]])
    (run / "raw_series.csv").write_text("secret,raw\n1,2\n", encoding="utf-8")
    _manifest(run)
    out = _export(tmp_path)
    manifest = _strict(out / "manifest.json")
    mddnr_sources = [s["path"] for s in manifest["sources"] if ex.FOREIGN["mddnr"]["run"] in s["path"]]
    assert mddnr_sources and not any("raw_series" in p for p in mddnr_sources)
    detail = _strict(out / "reliability_foreign_mddnr.json")
    assert detail["redistributable"] is False
    assert "Tidewater Ecosystem Assessment Division" in detail["credit"]
    assert [p["km"] for p in _pairs(detail)] == [29.8]  # <= 30 km only
    assert detail["radius"][0]["regime"] == "all" and detail["radius"][0]["gate"] == "gate80"
    text = (out / "reliability_foreign_mddnr.json").read_text(encoding="utf-8")
    assert "secret" not in text


def test_hk_pairs_get_regime_from_matched_samples_and_radius_labels(tmp_path):
    exp, data = tmp_path / "experiments", tmp_path / "data"
    run = exp / ex.FOREIGN["hk_epd"]["run"]
    _csv(run / "stations.csv", ["station", "lat", "lon", "water_control_zone"],
         [["DM1", 22.48, 113.98, "Deep Bay"], ["DM2", 22.47, 113.99, "Deep Bay"]])
    _csv(run / "pairs.csv", ["variable", "method", "anchor", "target", "relation", "distance_km", "n_lag0", "share_within"],
         [["Temp", "persistence_in_space", "DM1", "DM2", "same_zone", 2.264, 100, 0.8246],
          ["Temp", "persistence_in_space", "DM1", "DM2", "same_zone", 25.0, 100, 0.5]])
    _csv(run / "reliability_radius.csv",
         ["variable", "method", "lag_scope", "season", "relation", "gate", "radius", "stop", "split"],
         [["Temp", "persistence_in_space", "lag0", "all", "similar_regime", "gate_80", "5 km", "fail@5-10", "salinity_regime"],
          ["pH", "persistence_in_space", "lag0", "all", "similar_regime", "gate_80", ">20 km", "", "salinity_regime"],
          ["DO", "persistence_in_space", "lag0", "all", "similar_regime", "gate_80", "insufficient", "", "salinity_regime"],
          ["Temp", "persistence_in_space", "lag0", "wet", "similar_regime", "gate_80", "10 km", "", "salinity_regime"],
          ["Temp", "persistence_in_space", "lag0", "all", "same_zone", "gate_80", "5 km", "", "water_control_zone"]])
    with gzip.open(run / "matched_samples.csv.gz", "wt", encoding="utf-8") as handle:
        handle.write("target,target_date,t_Sal,anchor,wet_sal_median_diff,regime_relation,season,lag_days\n"
                     "DM2,2015-05-01,24.8,DM1,1.9,similar_regime,wet,0\n"
                     "DM1,2015-05-01,26.0,DM2,1.9,similar_regime,wet,0\n")
    _manifest(run)
    out = _export(tmp_path)
    detail = _strict(out / "reliability_foreign_hk_epd.json")
    assert detail["available"]["scales"] == ["monthly"]
    assert len(_pairs(detail)) == 1  # <= 10 km
    pair = _pairs(detail)[0]
    assert pair["same_regime"] is True and pair["dsal"] == 1.9 and pair["transfer"] == "raw" and pair["ci_low"] is None
    radius = {r["var"]: r for r in detail["radius"]}
    assert set(radius) == {"Temp", "pH", "DO"}  # lag0, season all, regime split only
    assert radius["Temp"]["radius_km"] == 5.0 and radius["Temp"]["regime"] == "same"
    assert radius["pH"]["radius_km"] == 20.0 and radius["pH"]["radius_label"] == ">20 km"
    assert radius["DO"]["radius_km"] is None
    st = {f["properties"]["station"]: f["properties"] for f in detail["stations"]["features"]}
    assert st["DM2"]["wet_sal_median"] == 24.8 and st["DM2"]["regime_class"] == "transitional"


def test_multiscale_radius_merged_and_empty_dir_reported(tmp_path):
    exp = tmp_path / "experiments"
    _usgs_like(exp, ex.FOREIGN["usgs_sfbay"]["run"])
    (exp / ex.MULTISCALE_RUN).mkdir()
    out = _export(tmp_path, stamp="20261017-1200")
    manifest = _strict(out / "manifest.json")
    assert manifest["inputs_skipped"][ex.MULTISCALE_RUN] == "run_dir_empty"
    _csv(exp / ex.MULTISCALE_RUN / "radius.csv",
         ["dataset", "var", "regime", "scale", "metric", "transfer", "gate", "radius_km", "stop"],
         [["usgs_sfbay", "Temp", "same", "daily_mean", "value", "raw", 80, 20.0, "all_pass"],
          ["usgs_sfbay", "Temp", "same", "hourly", "value", "raw", 80, 10.0, "fail"]])
    _manifest(exp / ex.MULTISCALE_RUN)
    out2 = _export(tmp_path, stamp="20261017-1300")
    detail = _strict(out2 / "reliability_foreign_usgs_sfbay.json")
    scales = {(r["scale"], r.get("metric")) for r in detail["radius"] if r["source_run"] == ex.MULTISCALE_RUN}
    assert scales == {("daily_mean", "value"), ("hourly", "value")}
    assert detail["available"]["scales"] == ["hourly", "daily_mean"]


def test_reliability_vn_exported_when_a6_run_present(tmp_path):
    run = tmp_path / "experiments" / ex.VN_REGIME_RUN
    run.mkdir(parents=True)
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [107.123456789, 20.987654321]},
         "properties": {"region": "quangninh", "station": "NB1", "wet_median_sal": 29.123456, "regime_class": "marine",
                        "coordinate_suspect": False, "salinity_source": "observed"}}]}
    (run / "station_regime.geojson").write_text(json.dumps(fc), encoding="utf-8")
    (run / "regime_layer.geojson").write_text(json.dumps(fc), encoding="utf-8")
    (run / "nb1_regime.json").write_text(json.dumps({"nb1_model_derived_class": "marine", "nb1_lat": 20.7}), encoding="utf-8")
    _csv(run / "pass_counts.csv", ["region", "variable", "n_pass"], [["quangninh", "pH", 0]])
    _manifest(run)
    out = _export(tmp_path)
    vn = _strict(out / "reliability_vn.json")
    assert vn["status"] == "ready" and vn["nb1_regime"]["nb1_model_derived_class"] == "marine"
    coords = vn["stations"]["features"][0]["geometry"]["coordinates"]
    assert coords == [107.12346, 20.98765]
    assert vn["pass_counts"] == [{"region": "quangninh", "variable": "pH", "n_pass": 0}]


def test_clean_replaces_nan_and_inf():
    assert ex.clean({"a": float("nan"), "b": [math.inf, 1.23456789], "c": None}) == {"a": None, "b": [None, 1.23456789], "c": None}
