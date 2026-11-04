"""Paper 2 figures (research-only): read existing F1-F5 artifacts, write PNG + PDF + the plotted tables.

Reads only (never re-runs a model): NB1 sensor history (``sensor-history-20261024``), F1 ``nb1_fault_catalog.json``,
F2 ``detection_summary.csv``, F3 / F4 / F5 ``summary.csv`` + ``verdict.csv``, F5 ``detection.csv``, F4
``nb1_trajectories.csv``, F5-NB1 re-run ``nb1_illustration.csv`` / ``nb1_changepoints.csv`` (RL-F5NB1).

Figures (each also as ``<name>_data.csv`` = the plotted numbers, the table view):
    fig1_fault_library   real NB1 faults behind the library: NH4 /20 (E1), NH4 x6.7 (E3), COD stuck-0 / rail, pH drop
    fig2_detectors       median detection delay vs false detection on matched shams (F2 NERRS, F5 MOF NH4)
    fig3_benefit_harm    benefit on /20 vs worst harm on fault-free shams, one panel per experiment (F3, F4, F5 x 3)
    fig4_nb1_case        NB1 E1 / E3: observed NH4 and Chronos-2 1-h forecasts under (a), (c'), v2 (F4 run)

Usage (writes a fresh run dir, refuses to overwrite):
    python experiments/paper2_figures.py [--output DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from core import paths  # noqa: E402

RUN_NAME = "paper2-figures-20261104"
EXP = paths.EXPERIMENT_OUTPUT_DIR
RUNS = {"f1": "paper2-f1-20261028", "f2": "paper2-f2-20261028", "f3": "paper2-f3-20261029",
        "f4": "paper2-f4-20261030", "f5": "paper2-f5-20261102", "f5nb1": "paper2-f5nb1-20261104"}
STATIONS = {"15159658": "Songdo", "15159657": "Busan Suyeong", "15159129": "Oido"}

# validated categorical palette (fixed order, never cycled); contrast WARN on 3 slots -> markers + legend + data CSV
MECH_ORDER = ["b", "c", "c_align", "v1", "v2", "v3", "d"]
MECH_LABEL = {"a": "(a) bỏ qua", "b": "(b) mặt nạ QC", "c": "(c) khởi động lại", "c_align": "(c′) căn mức",
              "v1": "F4 v1", "v2": "F4 v2", "v3": "F4 v3", "d": "(d) proxy thích nghi"}
COLOR = dict(zip(MECH_ORDER, ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]))
MARKER = dict(zip(MECH_ORDER, ["o", "s", "D", "^", "v", "P", "X"]))
INK, INK2, MUTED, GRID, BASE, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
OBS_COLOR = "#52514e"

BENEFIT_MIN, HARM_BUDGET, HARM_BUDGET_F4, HARM_CLIP = 0.30, 0.05, 0.10, 2.0


def style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": BASE, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False,
        "axes.spines.right": False, "font.size": 9, "axes.titlesize": 10, "axes.titlecolor": INK,
        "legend.frameon": False, "lines.linewidth": 2.0, "pdf.fonttype": 42})


# =============================================================================================
# tables (pure functions of the artifacts; tested)
# =============================================================================================

def benefit_harm_table(f3_sum: pd.DataFrame, f3_ver: pd.DataFrame, f4_sum: pd.DataFrame, f4_ver: pd.DataFrame,
                       f5_sum: pd.DataFrame, f5_ver: pd.DataFrame, model: str = "ridge") -> pd.DataFrame:
    """One row per experiment x mechanism: benefit = MAE reduction vs (a), 0-24 h after a /20 rescale, h = 1 h;
    harm = worst MAE increase vs (a) on fault-free shams (the harm each step's rule used)."""
    rows = []
    s3 = f3_sum[(f3_sum["model"] == model) & (f3_sum["horizon_min"] == 60) & (f3_sum["kind"] == "scale_down")
                & (~f3_sum["sham"].astype(str).eq("True"))].set_index("mech")
    v3 = f3_ver[f3_ver["model"] == model].set_index("mech")
    for m in ("b", "c", "c_align", "d"):
        if m in s3.index and m in v3.index:
            rows.append({"experiment": "F3 NERRS", "mech": m, "benefit": float(s3.loc[m, "reduction_post24"]),
                         "harm": float(v3.loc[m, "worst_sham_harm"]), "harm_rule": "F3 sham xấu nhất (9 loại)"})
    s4 = f4_sum[(f4_sum["model"] == model) & (f4_sum["set"] == "nerrs") & (f4_sum["split"] == "held")
                & (f4_sum["horizon_min"] == 60) & (f4_sum["kind"] == "scale_down")
                & (~f4_sum["sham"].astype(str).eq("True"))].set_index("mech")
    v4 = f4_ver[(f4_ver["model"] == model) & (f4_ver["split"] == "held")].set_index("variant")
    for m in ("v1", "v2", "v3"):
        if m in s4.index and m in v4.index:
            harm = float(v4.loc[m, ["G2_f2_sham_worst", "G2_cdmo_random", "G2_cdmo_event"]].max())
            rows.append({"experiment": "F4 NERRS (giữ lại)", "mech": m, "benefit": float(s4.loc[m, "reduction_post24"]),
                         "harm": harm, "harm_rule": "F4 G2: max(F2 sham, CDMO ngẫu nhiên, CDMO điểm đổi)"})
    s5 = f5_sum[(f5_sum["model"] == model) & (f5_sum["horizon_min"] == 60) & (f5_sum["window"] == "post24")
                & (f5_sum["set"] == "scale_down")]
    v5 = f5_ver[f5_ver["model"] == model]
    for pk, name in STATIONS.items():
        ss = s5[s5["station"].astype(str) == pk].set_index("mech")
        vv = v5[v5["station"].astype(str) == pk].set_index("mech")
        for m in ("b", "c_align", "v2", "v3", "d"):
            if m in ss.index and m in vv.index:
                rows.append({"experiment": f"F5 {name}", "mech": m, "benefit": float(ss.loc[m, "reduction"]),
                             "harm": float(vv.loc[m, "harm_random"]), "harm_rule": "F5 sham ngẫu nhiên"})
    out = pd.DataFrame(rows)
    if len(out):
        out["useful_zone"] = (out["benefit"] >= BENEFIT_MIN) & (out["harm"] <= HARM_BUDGET)
    return out


def detector_table(f2: pd.DataFrame, f5: pd.DataFrame, model: str = "ridge") -> pd.DataFrame:
    a = f2.assign(source="F2 NERRS (33 trạm)", station="NERRS")[
        ["source", "station", "kind", "n", "detection_rate", "sham_rate", "excess_over_sham", "median_delay_h"]]
    b = f5[f5["model"] == model].rename(columns={"detection": "detection_rate", "delay_h_median": "median_delay_h"})
    b = b.assign(source="F5 MOF NH4", station=b["station"].astype(str).map(STATIONS))[
        ["source", "station", "kind", "n", "detection_rate", "sham_rate", "excess_over_sham", "median_delay_h"]]
    return pd.concat([a, b], ignore_index=True)


# =============================================================================================
# figures
# =============================================================================================

def _save(fig, out: Path, name: str, data: pd.DataFrame | None, written: list) -> None:
    for ext in ("png", "pdf"):
        p = out / f"{name}.{ext}"
        if p.exists():
            raise FileExistsError(f"refusing_to_overwrite:{p}")
        fig.savefig(p, dpi=200 if ext == "png" else None, bbox_inches="tight")
        written.append(p)
    plt.close(fig)
    if data is not None:
        p = out / f"{name}_data.csv"
        if p.exists():
            raise FileExistsError(f"refusing_to_overwrite:{p}")
        data.to_csv(p, index=False)
        written.append(p)


def fig_fault_library(hist: pd.DataFrame, catalog: dict) -> tuple[plt.Figure, pd.DataFrame]:
    ev = catalog.get("nb1_events", {})

    def factor(event: str, var: str) -> float | None:
        for f in ev.get(event, []):
            if f["variable"] == var and f["kind"] == "scale_step":
                return f["params"]["factor"]
        return None

    panels = [
        ("NH4", "2026-07-30 14:00", "2026-08-01 14:00", "2026-07-31 14:06", True,
         f"E1 31/07: đổi thang ÷{1 / (factor('E1_20260731', 'NH4') or np.nan):.1f} trong 1 mẫu".replace(".", ",")),
        ("NH4", "2026-09-15 12:00", "2026-09-17 18:00", "2026-09-16 15:00", True,
         "E3 16/09: đổi thang ×6,7 (sau bảo dưỡng)"),
        ("COD", "2026-06-01", "2026-10-14", None, False, "COD: trần 558,8 và kẹt đúng 0,0 (nhiều tuần)"),
        ("pH", "2026-09-18 12:00", "2026-09-21 00:00", "2026-09-19 06:00", False, "pH 19/09: tụt −1,0 trong ~5 h"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(9.0, 5.6))
    rows = []
    for ax, (var, a, b, mark, logy, title) in zip(axes.ravel(), panels):
        s = hist[var][a:b]
        if var == "COD":
            s = s.resample("1h").median()
        ax.plot(s.index, s.to_numpy(), color=OBS_COLOR, lw=1.0)
        if mark:
            ax.axvline(pd.Timestamp(mark), color=MUTED, ls="--", lw=1)
        if logy:
            ax.set_yscale("log")
        ax.set_title(title, loc="left")
        ax.set_ylabel(f"{var} (thô)" if var != "pH" else "pH")
        ax.tick_params(axis="x", labelrotation=30, labelsize=7)
        rows.append({"panel": title, "variable": var, "start": a, "end": b, "n": int(s.notna().sum()),
                     "min": float(s.min()), "median": float(s.median()), "max": float(s.max())})
    fig.suptitle("Sự cố thật ở NB1 (06M26042804) làm mẫu cho thư viện chèn sự cố F1", x=0.01, ha="left", color=INK)
    fig.tight_layout()
    return fig, pd.DataFrame(rows)


def fig_detectors(tab: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    ax.set_yscale("symlog", linthresh=1.0)
    for src, mk, col in (("F2 NERRS (33 trạm)", "o", COLOR["b"]), ("F5 MOF NH4", "s", COLOR["c"])):
        d = tab[tab["source"] == src]
        ax.scatter(d["sham_rate"], d["median_delay_h"], s=36 + 60 * d["excess_over_sham"].clip(0, 1), marker=mk,
                   facecolor=col, edgecolor=SURFACE, linewidth=1.2, label=src, zorder=3)
        for _, r in d.iterrows():
            lab = r["kind"] if src.startswith("F2") else f"{r['kind']} · {str(r['station'])[:6]}"
            if src.startswith("F2") or r["kind"] in ("drift_down", "scale_up"):
                ax.annotate(lab, (r["sham_rate"], r["median_delay_h"]), xytext=(4, 3), textcoords="offset points",
                            fontsize=6.5, color=INK2)
    ax.set_xlabel("Tỉ lệ báo động trên cửa sổ không sự cố ghép cặp (sham)")
    ax.set_ylabel("Trễ phát hiện trung vị (h, symlog)")
    ax.set_title("Phát hiện: đột ngột thì nhanh, chậm thì muộn (cỡ điểm = vượt sham)", loc="left")
    ax.legend(loc="lower left", fontsize=7.5)
    return fig


def fig_benefit_harm(tab: pd.DataFrame) -> plt.Figure:
    exps = list(dict.fromkeys(tab["experiment"]))
    fig, axes = plt.subplots(1, len(exps), figsize=(2.3 * len(exps) + 0.6, 3.6), sharey=True, sharex=True)
    axes = np.atleast_1d(axes)
    for ax, e in zip(axes, exps):
        ax.set_xscale("symlog", linthresh=0.01, linscale=0.5)
        ax.fill_between([-0.005, HARM_BUDGET], BENEFIT_MIN, 1.0, color="#cde2fb", alpha=0.6, lw=0, zorder=0)
        ax.axhline(BENEFIT_MIN, color=MUTED, ls="--", lw=0.8)
        ax.axvline(HARM_BUDGET, color=MUTED, ls="--", lw=0.8)
        ax.axvline(HARM_BUDGET_F4, color=MUTED, ls=":", lw=0.8)
        ax.axhline(0, color=BASE, lw=0.8)
        d = tab[tab["experiment"] == e]
        for _, r in d.iterrows():
            x = min(r["harm"], HARM_CLIP)
            ax.scatter(x, r["benefit"], marker=MARKER[r["mech"]], s=60, facecolor=COLOR[r["mech"]],
                       edgecolor=SURFACE, linewidth=1.2, zorder=3)
            if r["harm"] > HARM_CLIP:
                ax.annotate(f"→ {r['harm']:.1f}".replace(".", ","), (x, r["benefit"]), xytext=(-8, 8),
                            textcoords="offset points", fontsize=6.5, color=INK2, ha="right")
        ax.set_title(e, loc="left", fontsize=9)
        ax.set_xlim(-0.005, HARM_CLIP * 1.3)
        ax.set_xticks([0, 0.05, 0.5, 2])
        ax.set_xticklabels(["0", "5 %", "50 %", "200 %"], fontsize=7)
        ax.minorticks_off()
        ax.set_ylim(-0.6, 1.0)
        ax.set_xlabel("Hại trên sham (MAE tăng)")
    axes[0].set_ylabel("Lợi ích ÷20, 0–24 h, h = 1 h")
    handles = [plt.Line2D([], [], ls="", marker=MARKER[m], markersize=7, markerfacecolor=COLOR[m],
                          markeredgecolor=SURFACE, label=MECH_LABEL[m]) for m in MECH_ORDER if m in set(tab["mech"])]
    fig.legend(handles=handles, loc="lower center", ncol=len(handles), fontsize=7.5, bbox_to_anchor=(0.5, -0.08))
    fig.suptitle("Không cơ chế nào vào vùng có ích (xanh: lợi ≥ 30 %, hại ≤ 5 %; chấm: ngân sách 10 % của F4) — ridge",
                 x=0.01, ha="left", color=INK, fontsize=10)
    fig.tight_layout()
    return fig


def fig_nb1_case(traj: pd.DataFrame, f5nb1: pd.DataFrame | None, model: str = "chronos2") -> tuple[plt.Figure, pd.DataFrame]:
    events = [("E1_NH4", "2026-07-31 14:00"), ("E3_NH4", "2026-09-16 15:00")]
    mechs = [("a", "#898781"), ("c_align", COLOR["c_align"]), ("v2", COLOR["v2"])]
    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.6))
    rows = []
    for ax, (ev, onset) in zip(axes, events):
        d = traj[(traj["event"] == ev) & (traj["model"] == model)].copy()
        d["origin"] = pd.to_datetime(d["origin"])
        t0 = pd.Timestamp(onset)
        d = d[(d["origin"] >= t0 - pd.Timedelta(hours=24)) & (d["origin"] <= t0 + pd.Timedelta(hours=47))]
        obs = d[d["mech"] == "a"].set_index("origin")["obs_1h"]
        ax.plot(obs.index + pd.Timedelta(hours=1), obs.to_numpy(), color=INK, lw=1.0, label="quan trắc")
        for m, col in mechs:
            dm = d[d["mech"] == m]
            ax.plot(dm["origin"] + pd.Timedelta(hours=1), dm["pred_1h"], color=col, lw=2.0,
                    ls="-" if m != "a" else "--", label=f"{MECH_LABEL[m]} (F4, {model})")
            rows.append({"event": ev, "mech": m, "source": "F4 nb1_trajectories",
                         "mean_pred_post24": float(dm[(dm["origin"] >= t0) & (dm["origin"] < t0 + pd.Timedelta(hours=24))]["pred_1h"].mean())})
        ax.axvline(t0, color=MUTED, ls="--", lw=0.8)
        ax.set_yscale("log")
        ax.set_title(f"NB1 {ev[:2]} — NH4 thô, dự báo 1 h", loc="left")
        ax.tick_params(axis="x", labelrotation=30, labelsize=7)
    if f5nb1 is not None:
        for _, r in f5nb1.iterrows():
            rows.append({"event": r["event"], "mech": r["mech"], "source": "F5-NB1 giờ (RL-F5NB1)",
                         "mean_pred_post24": float(r["mean_fc_post24"]), "obs_pre24": float(r["obs_pre24_median"]),
                         "obs_post24": float(r["obs_post24_median"])})
    axes[0].set_ylabel("NH4 (thô)")
    axes[0].legend(fontsize=7, loc="lower left")
    fig.suptitle("Ca NB1 (không có đáp án): căn mức đưa dự báo về mức trước bậc; (a) bám mức sau bậc",
                 x=0.01, ha="left", color=INK, fontsize=10)
    fig.tight_layout()
    return fig, pd.DataFrame(rows)


# =============================================================================================

def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--output", type=Path, default=None)
    args = ap.parse_args(argv)
    out = args.output or EXP / RUN_NAME
    out.mkdir(parents=True, exist_ok=False)
    style()
    r = {k: EXP / v for k, v in RUNS.items()}
    inputs: list[Path] = []

    def rd(p: Path) -> pd.DataFrame:
        inputs.append(p)
        return pd.read_csv(p)

    written: list[Path] = []
    from experiments.nh4_step_0731 import HISTORY, load_history

    inputs += [HISTORY, r["f1"] / "nb1_fault_catalog.json"]
    fig, data = fig_fault_library(load_history(), json.loads((r["f1"] / "nb1_fault_catalog.json").read_text(encoding="utf-8")))
    _save(fig, out, "fig1_fault_library", data, written)

    det = detector_table(rd(r["f2"] / "detection_summary.csv"), rd(r["f5"] / "detection.csv"))
    _save(fig_detectors(det), out, "fig2_detectors", det, written)

    bh = benefit_harm_table(rd(r["f3"] / "summary.csv"), rd(r["f3"] / "verdict.csv"), rd(r["f4"] / "summary.csv"),
                            rd(r["f4"] / "verdict.csv"), rd(r["f5"] / "summary.csv"), rd(r["f5"] / "verdict.csv"))
    _save(fig_benefit_harm(bh), out, "fig3_benefit_harm", bh, written)

    f5nb1_path = r["f5nb1"] / "nb1_illustration.csv"
    f5nb1 = rd(f5nb1_path) if f5nb1_path.exists() else None
    fig, data = fig_nb1_case(rd(r["f4"] / "nb1_trajectories.csv"), f5nb1)
    _save(fig, out, "fig4_nb1_case", data, written)

    from experiments.paper2_faults import git_head

    (out / "manifest.json").write_text(json.dumps({
        "run": out.name, "script": "experiments/paper2_figures.py", "git_head": git_head(),
        "created": pd.Timestamp.now(tz="UTC").isoformat(),
        "inputs": [{"path": str(p), "sha256": _sha(p)} for p in dict.fromkeys(inputs)],
        "outputs": {p.name: _sha(p) for p in written}}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(written)} files to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
