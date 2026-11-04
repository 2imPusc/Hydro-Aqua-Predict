"""Paper 2 figures: table builders read the right rows; figures render from small synthetic artifacts."""
import matplotlib

matplotlib.use("Agg")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from experiments import paper2_figures as pf  # noqa: E402


def _f3():
    rows = []
    for model in ("ridge", "bolt"):
        for kind in ("scale_down", "scale_up"):
            for sham in (False, True):
                for h in (60, 360):
                    for m in ("a", "b", "c", "c_align", "d"):
                        val = {"c_align": 0.43, "b": 0.08}.get(m, 0.0) if model == "ridge" else 0.9
                        rows.append({"model": model, "kind": kind, "sham": sham, "horizon_min": h, "mech": m,
                                     "reduction_post24": val if (kind == "scale_down" and h == 60 and not sham) else -9})
    s = pd.DataFrame(rows)
    v = pd.DataFrame({"model": ["ridge"] * 4, "mech": ["b", "c", "c_align", "d"],
                      "worst_sham_harm": [0.106, 0.2, 2.9, 0.003]})
    return s, v


def _f4():
    rows = []
    for split in ("cal", "held"):
        for sham in (False, True):
            for m in ("a", "v1", "v2", "v3"):
                rows.append({"model": "ridge", "set": "nerrs", "split": split, "kind": "scale_down", "sham": sham,
                             "horizon_min": 60, "mech": m,
                             "reduction_post24": 0.77 if (split == "held" and not sham and m == "v1") else -1})
    v = pd.DataFrame({"model": "ridge", "variant": ["v1", "v2", "v3"], "split": "held",
                      "G2_f2_sham_worst": [1.23, 0.5, 0.21], "G2_cdmo_random": [0.3, 0.2, 0.1],
                      "G2_cdmo_event": [0.4, 0.6, 0.22]})
    return pd.DataFrame(rows), v


def _f5():
    rows, vrows = [], []
    for pk in pf.STATIONS:
        for m in ("b", "c_align", "v2", "v3", "d"):
            for w in ("post24", "post7"):
                rows.append({"model": "ridge", "station": int(pk), "set": "scale_down", "mech": m, "horizon_min": 60,
                             "window": w, "reduction": 0.41 if (m == "c_align" and w == "post24") else 0.0})
            vrows.append({"model": "ridge", "station": int(pk), "mech": m, "harm_random": 0.92 if m == "c_align" else 0.01})
    return pd.DataFrame(rows), pd.DataFrame(vrows)


def test_benefit_harm_table_picks_scored_rows():
    (s3, v3), (s4, v4), (s5, v5) = _f3(), _f4(), _f5()
    t = pf.benefit_harm_table(s3, v3, s4, v4, s5, v5)
    f3 = t[t["experiment"] == "F3 NERRS"].set_index("mech")
    assert f3.loc["c_align", "benefit"] == pytest.approx(0.43) and f3.loc["c_align", "harm"] == pytest.approx(2.9)
    f4 = t[t["experiment"].str.startswith("F4")].set_index("mech")
    assert f4.loc["v1", "benefit"] == pytest.approx(0.77)
    assert f4.loc["v2", "harm"] == pytest.approx(0.6)            # max over the three G2 sham sets
    f5 = t[t["experiment"] == "F5 Songdo"].set_index("mech")
    assert f5.loc["c_align", "benefit"] == pytest.approx(0.41) and f5.loc["c_align", "harm"] == pytest.approx(0.92)
    assert not t["useful_zone"].any()
    assert set(t["experiment"]) == {"F3 NERRS", "F4 NERRS (giữ lại)", "F5 Songdo", "F5 Busan Suyeong", "F5 Oido"}


def test_detector_table_maps_stations():
    f2 = pd.DataFrame({"kind": ["scale_down"], "n": [190], "detection_rate": [0.98], "sham_rate": [0.2],
                       "excess_over_sham": [0.78], "median_delay_h": [0.25]})
    f5 = pd.DataFrame({"model": ["ridge", "chronos2"], "station": [15159658, 15159658], "kind": ["stuck", "stuck"],
                       "n": [40, 40], "detection": [1.0, 1.0], "sham_rate": [0.1, 0.1], "excess_over_sham": [0.9, 0.9],
                       "delay_h_median": [3.0, 3.0], "stuck_hit_24h": [1.0, 1.0]})
    t = pf.detector_table(f2, f5)
    assert len(t) == 2 and t.iloc[1]["station"] == "Songdo" and t.iloc[1]["median_delay_h"] == 3.0


def test_figures_render(tmp_path):
    pf.style()
    (s3, v3), (s4, v4), (s5, v5) = _f3(), _f4(), _f5()
    written = []
    pf._save(pf.fig_benefit_harm(pf.benefit_harm_table(s3, v3, s4, v4, s5, v5)), tmp_path, "bh", None, written)
    origins = pd.date_range("2026-07-30 14:00", "2026-08-02 13:00", freq="h")
    traj = pd.concat([pd.DataFrame({"event": ev, "model": "chronos2", "mech": m, "origin": origins + off,
                                    "pred_1h": 100.0, "obs_1h": 100.0})
                      for ev, off in (("E1_NH4", pd.Timedelta(0)), ("E3_NH4", pd.Timedelta(days=47, hours=1)))
                      for m in ("a", "c_align", "v2")])
    fig, data = pf.fig_nb1_case(traj, None)
    pf._save(fig, tmp_path, "nb1", data, written)
    assert all(p.exists() and p.stat().st_size > 0 for p in written) and len(written) == 5
    with pytest.raises(FileExistsError):
        pf._save(pf.fig_benefit_harm(pf.benefit_harm_table(s3, v3, s4, v4, s5, v5)), tmp_path, "bh", None, [])
    assert np.isfinite(data["mean_pred_post24"]).all()
