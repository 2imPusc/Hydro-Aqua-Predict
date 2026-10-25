"""Tests for experiments/transfer_impute.py (H1.8): harmonisation, split integrity, fine-tune logic."""
import numpy as np
import pandas as pd
import pytest

from experiments import transfer_impute as ti


def _vn(n_stations=6, years=(2021, 2022, 2023, 2024), months=(1, 4, 7, 10), seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(n_stations):
        for y in years:
            for m in months:
                t = 25 + 5 * np.sin(2 * np.pi * m / 12) + rng.normal(0, 0.5)
                rows.append(dict(source="vn", region="r", station=f"S{s}", group=f"S{s}",
                                 date=pd.Timestamp(y, m, 1), year=y, month=m, campaign=f"{y}-{m:02d}",
                                 Temperature=t, pH=8 + rng.normal(0, 0.1), TAN=0.05 + rng.random() * 0.05,
                                 TSS=5 + rng.random() * 5, DO=9.5 - 0.12 * t + rng.normal(0, 0.1),
                                 Salinity=30 + rng.normal(0, 1), PO4=np.nan, Transparency=np.nan))
    return ti.add_season(pd.DataFrame(rows))


def _hk_raw():
    head = ["Water Control Zone", "Station", "Dates", "Sample No", "Depth", "Ammonia Nitrogen (mg/L)",
            "Dissolved Oxygen (%saturation)", "Dissolved Oxygen (mg/L)", "Orthophosphate Phosphorus (mg/L)",
            "pH", "Salinity (psu)", "Secchi Disc Depth (M)", "Suspended Solids (mg/L)", "Temperature (°C)",
            "Turbidity (NTU)", "Unionised Ammonia (mg/L)"]
    rows = [
        ["Z", "A1", "2020-01-11", "1", "Surface Water", "<0.005", "99", "7.8", "<0.002", "7.9", "30.1", "2.5", "<0.5", "21.2", "900", "0.001"],
        ["Z", "A1", "2020-01-11", "1", "Bottom Water", "0.3", "80", "6.0", "0.1", "7.9", "33.0", "2.5", "10", "20.0", "5", "0.002"],
        ["Z", "A2", "2020-07-06", "1", "Surface Water", "0.23", "105", "7.5", "0.14", "7.8", "6.0", "1.0", "19", "31.2", "13.3", "0.012"],
    ]
    return pd.DataFrame(rows, columns=head)


def test_parse_censored_halves_lod():
    v, c = ti.parse_censored(pd.Series(["<0.005", "0.3", "x", " <0.5"]))
    assert v.iloc[0] == pytest.approx(0.0025)
    assert v.iloc[1] == pytest.approx(0.3)
    assert np.isnan(v.iloc[2])
    assert v.iloc[3] == pytest.approx(0.25)
    assert c.tolist() == [True, False, False, True]


def test_harmonise_hk_mapping_surface_and_units():
    df, log = ti.harmonise_hk(_hk_raw())
    assert len(df) == 2  # bottom sample dropped
    a1 = df[df["station"] == "A1"].iloc[0]
    assert a1["TAN"] == pytest.approx(0.0025)  # Ammonia Nitrogen, not Unionised Ammonia
    assert a1["DO"] == pytest.approx(7.8)  # mg/L, not % saturation
    assert a1["TSS"] == pytest.approx(0.25)  # Suspended Solids, never Turbidity (900 NTU)
    assert np.isnan(a1["PO4"])  # censored PO4 is not a target
    assert a1["Transparency"] == pytest.approx(2.5)
    a2 = df[df["station"] == "A2"].iloc[0]
    assert a2["PO4"] == pytest.approx(0.14)
    assert a2["Temperature"] == pytest.approx(31.2)
    assert a2["month"] == 7 and a2["m_sin"] == pytest.approx(np.sin(2 * np.pi * 7 / 12))
    assert set(ti.FEATURES) <= set(df.columns)


def test_screen_targets_drops_implausible_do():
    df = pd.DataFrame({"DO": [6.0, 60.5, 0.0], "Salinity": [30, 41, 0.0]})
    log = ti.screen_targets(df, "x")
    assert df["DO"].isna().tolist() == [False, True, True]
    assert df["Salinity"].isna().tolist() == [False, True, False]
    assert any("DO" in r["item"] for r in log)


def test_duplicate_series_groups_merges_same_model_cell():
    d = pd.date_range("2022-01-01", periods=5, freq="MS")
    rows = []
    for s, off in (("A", 0.0), ("B", 0.0), ("C", 0.3)):
        for i, t in enumerate(d):
            rows.append(dict(station=s, date=t, Temperature=20 + i + off, Salinity=31 + 0.1 * i))
    g = ti.duplicate_series_groups(pd.DataFrame(rows))
    assert g["A"] == g["B"] != g["C"]


@pytest.mark.parametrize("kind", ti.SPLITS)
def test_split_integrity_no_test_station_or_period_in_training(kind):
    df = _vn()
    folds = list(ti.make_splits(df, kind, n_folds=3))
    assert folds
    for _, tr, te in folds:
        assert len(set(tr) & set(te)) == 0
        if kind == "loso":
            assert not set(df.loc[tr, "group"]) & set(df.loc[te, "group"])
        if kind == "time":
            assert df.loc[tr, "year"].max() < df.loc[te, "year"].min()
        if kind == "season":
            assert df.loc[tr, "month"].isin(ti.WET_MONTHS).all()
            assert not df.loc[te, "month"].isin(ti.WET_MONTHS).any()
        # inner tuning folds are drawn from the training rows only
        for itr, iva in ti.inner_folds(df.loc[tr], seed=1):
            assert set(itr) | set(iva) <= set(tr)
            assert not set(iva) & set(te)
    if kind == "loso":
        tested = np.concatenate([te for _, _, te in folds])
        assert sorted(tested) == sorted(df.index)


def test_other_region_rows_respect_split_rule():
    other = _vn(years=(2023, 2024))
    assert ti.other_region_rows(other, "time", 2024)["year"].max() == 2023
    assert ti.other_region_rows(other, "season", 2024)["month"].isin(ti.WET_MONTHS).all()


def test_block_bootstrap_diff_detects_consistent_gain():
    rng = np.random.default_rng(0)
    b = np.abs(rng.normal(1, 0.1, 200))
    a = b - 0.2
    m, lo, hi = ti.block_bootstrap_diff(a, b, np.repeat(np.arange(20), 10), n_boot=500)
    assert m == pytest.approx(-0.2)
    assert hi < 0


def test_class_scores_and_degenerate_flag():
    obs = np.array([True] * 12 + [False] * 88)
    pred = np.array([True] * 10 + [False] * 2 + [True] * 5 + [False] * 83)
    c = ti.class_scores(obs, pred)
    assert c["pod"] == pytest.approx(10 / 12)
    assert c["far"] == pytest.approx(5 / 15)
    assert not c["degenerate"]
    assert ti.class_scores(np.zeros(100, bool), np.zeros(100, bool))["degenerate"]


def test_warm_start_continues_from_pretrained_model():
    rng = np.random.default_rng(0)
    X = rng.random((300, len(ti.FEATURES)))
    base = ti.xgb_fit(X, 10 * X[:, 0])
    Xv = rng.random((40, len(ti.FEATURES)))
    yv = 10 * Xv[:, 0] + 3.0  # VN domain is shifted by +3
    ft = ti.xgb_fit(Xv, yv, base=base)
    assert ft.get_booster().num_boosted_rounds() == 2 * ti.XGB_PARAMS["n_estimators"]
    shift = np.mean(ft.predict(Xv) - base.predict(Xv))
    assert 2.0 < shift < 4.0


def test_tune_weight_uses_training_rows_only_and_predict_variants_shapes():
    vn = _vn()
    foreign = _vn(n_stations=10, seed=5).assign(DO=lambda d: d["DO"] + 1.0, station=lambda d: "F" + d["station"],
                                                group=lambda d: "F" + d["group"])
    tr, te = next(iter(ti.make_splits(vn, "loso", n_folds=3)))[1:]
    seen = []

    def fp(f, a, b, target, w):
        seen.append(set(a.index) | set(b.index))
        return np.full(len(b), a[target].mean())

    w, scores = ti.tune_weight(foreign, vn.loc[tr], "DO", 1, fp)
    assert w in ti.WEIGHT_GRID and set(scores) == set(ti.WEIGHT_GRID)
    assert all(s <= set(tr) for s in seen)
    pre = ti.pretrain_all({"hk": foreign, "hk_sim": foreign}, "DO")
    preds, tune = ti.predict_variants(vn.loc[tr], vn.loc[te], "DO", "r", {"hk": foreign, "hk_sim": foreign},
                                      pre, None, 1)
    for v in ("vn_median", "vn_clim", "vn_runtime", "vn_only", "hk_zero", "pool_w", "pool_w_sim",
              "ft_warm", "stack_feat", "da_std", "mlp_ft"):
        assert len(preds[v]) == len(te), v
    assert tune["pool_w"]["weight"] in ti.WEIGHT_GRID
    # zero-shot on a +1 mg/L shifted foreign domain is biased; fine-tuned / adapted variants are not
    y = vn.loc[te, "DO"].to_numpy()
    assert np.mean(preds["hk_zero"] - y) > 0.5
    assert abs(np.mean(preds["da_std"] - y)) < 0.5
    assert abs(np.mean(preds["ft_warm"] - y)) < 0.5


def test_decide_rule():
    diff = pd.DataFrame([
        dict(variant="pool_w", split="loso", ci_hi_row=-0.01, ci_hi_campaign=-0.01),
        dict(variant="pool_w", split="time", ci_hi_row=-0.02, ci_hi_campaign=0.01),
        dict(variant="pool_w", split="season", ci_hi_row=0.05, ci_hi_campaign=0.05),
    ])
    classes = pd.DataFrame([
        dict(split="loso", event="E", variant="vn_only", pod=0.8, degenerate_obs=False),
        dict(split="loso", event="E", variant="pool_w", pod=0.78, degenerate_obs=False),
        dict(split="time", event="E", variant="vn_only", pod=0.8, degenerate_obs=True),
        dict(split="time", event="E", variant="pool_w", pod=0.1, degenerate_obs=True),
    ])
    d = ti.decide(diff, classes, "pool_w")
    assert d["useful"] and d["n_beat"] == 2 and not d["robust"]
    classes.loc[1, "pod"] = 0.6
    assert not ti.decide(diff, classes, "pool_w")["useful"]


def test_similar_hk_selection_uses_marine_stations_only():
    hk = _vn(n_stations=8, seed=3)
    hk["station"] = [f"H{i % 8}" for i in range(len(hk))]
    hk.loc[hk["station"].isin(["H0", "H1"]), "Salinity"] = 10.0
    prof = ti.select_similar_hk(hk, _vn())
    assert not prof.loc[["H0", "H1"], "selected"].any()
    assert prof["selected"].sum() == 3  # half of 6 marine stations


@pytest.mark.requires_data
def test_load_vn_real_files_qc():
    hp, _ = ti.load_vn("haiphong")
    qn, _ = ti.load_vn("quangninh")
    assert hp["DO"].max() <= 20 and qn["DO"].max() <= 20
    assert qn["PO4"].isna().all()  # LOQ-censored, excluded
    assert hp["group"].nunique() < hp["station"].nunique()  # GLORYS-duplicate stations merged
    assert not hp.duplicated(["station", "date"]).any()
