# lab/realtime_greenlab/plot_figures.py
"""Sinh hình trực quan cho BAOCAO.tex.

Chạy từ repo root:
    python lab/realtime_greenlab/plot_figures.py
Xuất ra: lab/realtime_greenlab/figures/*.png
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from core.config import LOCAL_CSV_PATH
from core.impute import build_training_data

FIG_DIR = Path(__file__).resolve().parent / "figures"
FIG_DIR.mkdir(exist_ok=True)

COD_RAIL = 558.8
plt.rcParams.update({"figure.dpi": 130, "font.size": 10, "axes.grid": True,
                     "grid.alpha": 0.3})


def _load_realtime():
    df = pd.read_csv(LOCAL_CSV_PATH)
    df["fetchedAt"] = pd.to_datetime(df["fetchedAt"], utc=True)
    df["t"] = df["fetchedAt"].dt.tz_convert("Asia/Bangkok")
    df["date"] = df["t"].dt.date
    return df.sort_values("t").reset_index(drop=True)


def fig_cod_timeline(df):
    """COD theo thời gian: trôi dần rồi kẹt trần 558.8."""
    daily = df.groupby("date")["COD"].median()
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.scatter(df["t"], df["COD"], s=4, alpha=0.12, color="#1f77b4", label="Reading thô (3-5 phút)")
    ax.plot(pd.to_datetime(list(daily.index)), daily.values, color="#d62728",
            lw=2, marker="o", ms=3, label="Median theo ngày")
    ax.axhline(COD_RAIL, ls="--", color="black", lw=1.2)
    ax.text(df["t"].iloc[len(df)//2], COD_RAIL + 12,
            f"Trần đo (rail) = {COD_RAIL}", fontsize=9)
    ax.axhline(10, ls=":", color="green", lw=1, alpha=0.7)
    ax.text(df["t"].iloc[2], 18, "QCVN B1 = 10", fontsize=8, color="green")
    ax.set_ylabel("COD (mg/L)")
    ax.set_title("Cảm biến COD: trôi dần (06-10/06) rồi chết kẹt trần (từ 11/06)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.legend(loc="center left", fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    out = FIG_DIR / "cod_timeline.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print("saved", out)


def fig_value_dist(df):
    """Phân phối (histogram) giá trị thô của 5 cảm biến — lộ COD bimodal/rail + NH4 cao."""
    specs = [("COD", "COD (mg/L)", "#1f77b4", [(10, "QCVN B1=10", "green"),
                                               (COD_RAIL, f"rail={COD_RAIL}", "black")]),
             ("NH4", "NH4 thô", "#9467bd", []),
             ("pH", "pH", "#2ca02c", [(6.5, "6.5", "red"), (8.5, "8.5", "red")]),
             ("Temperature", "Nhiệt độ (°C)", "#ff7f0e", [(30, "30", "red")]),
             ("TSS", "TSS (mg/L)", "#8c564b", [(50, "QCVN B1=50", "red")])]
    fig, axes = plt.subplots(2, 3, figsize=(10, 5.4))
    axL = axes.ravel()
    for ax, (col, title, color, marks) in zip(axL, specs):
        ax.hist(df[col].values, bins=50, color=color, alpha=0.8)
        for v, lbl, c in marks:
            ax.axvline(v, ls="--", color=c, lw=1.3, alpha=0.8)
        ax.set_title(title, fontsize=10)
        ax.set_ylabel("Số reading")
    axL[-1].axis("off")
    axL[-1].text(0.02, 0.85, "Nhận xét nhanh:", fontsize=10, weight="bold", transform=axL[-1].transAxes)
    axL[-1].text(0.02, 0.05,
                 "• COD: 77.7% dồn ở trần 558.8\n  (cảm biến chết) + cụm nhỏ ~10.\n"
                 "• NH4: 77–160, lệch cao\n  (vấn đề đơn vị).\n"
                 "• pH/Temp ổn định; TSS lệch phải,\n  42% vượt 50.",
                 fontsize=8.5, va="bottom", transform=axL[-1].transAxes)
    fig.suptitle("Phân phối giá trị thô 5 cảm biến (15.475 reading) — đường đứt = ngưỡng QCVN/rail",
                 fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out = FIG_DIR / "value_dist.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print("saved", out)


def fig_data_coverage(df):
    """Số reading mỗi ngày — lộ thay đổi tần suất (3-5 phút -> 1 phút từ 12/06)."""
    pc = df.groupby("date").size()
    x = pd.to_datetime(list(pc.index))
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.bar(x, pc.values, width=0.7, color="#4c78a8", alpha=0.85)
    ax.axhline(288, ls=":", color="gray", lw=1)
    ax.text(x[1], 300, "288/ngày (5 phút/lần)", fontsize=8, color="gray")
    ax.annotate("tăng tần suất\n($\\to$1 phút/lần)", xy=(x[-3], 1440), xytext=(x[5], 1100),
                fontsize=8.5, arrowprops=dict(arrowstyle="->", color="black", lw=1))
    ax.set_ylabel("Số reading / ngày")
    ax.set_title("Độ phủ dữ liệu: 23 ngày (29/05–20/06), 15.475 reading, 1 trạm Cát Bà")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    fig.autofmt_xdate()
    fig.tight_layout()
    out = FIG_DIR / "data_coverage.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print("saved", out)


def fig_sensor_panel(df):
    """Daily-median của 4 cảm biến còn sống: NH4, pH, Temp, TSS."""
    daily = df.groupby("date").median(numeric_only=True)
    x = pd.to_datetime(list(daily.index))
    specs = [("NH4", "NH4 thô", "#9467bd", None),
             ("pH", "pH", "#2ca02c", (6.5, 8.5)),
             ("Temperature", "Nhiệt độ (°C)", "#ff7f0e", (None, 30)),
             ("TSS", "TSS (mg/L)", "#8c564b", (None, 50))]
    fig, axes = plt.subplots(2, 2, figsize=(9, 5.2), sharex=True)
    for ax, (col, title, color, lim) in zip(axes.ravel(), specs):
        ax.plot(x, daily[col].values, color=color, lw=1.8, marker="o", ms=2.5)
        if lim:
            for v in lim:
                if v is not None:
                    ax.axhline(v, ls="--", color="red", lw=1, alpha=0.6)
        ax.set_title(title, fontsize=10)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    fig.suptitle("Bốn cảm biến còn sống (median theo ngày) — đường đỏ = ngưỡng QCVN B1", fontsize=10)
    fig.autofmt_xdate()
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    out = FIG_DIR / "sensor_panel.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print("saved", out)


def fig_do_per_region():
    """DO predicted-vs-actual (LOO-CV) — HP-only đoán được, QN+HP/QN thì không."""
    from sklearn.model_selection import LeaveOneGroupOut
    from sklearn.metrics import r2_score
    from xgboost import XGBRegressor
    from hap_shared.preprocessing import load_data, EXCLUDED_STATIONS
    from core.config import QN_DATA_PATH, HP_DATA_PATH

    F4 = ["NH3", "pH", "Temperature", "TSS"]

    def loo_do(paths):
        dfs = []
        for p in paths:
            d = load_data(str(p))
            d = d[~d["Station"].isin(EXCLUDED_STATIONS)]
            dfs.append(d)
        df = pd.concat(dfs, ignore_index=True).dropna(subset=F4 + ["DO"]).reset_index(drop=True)
        X, y, g = df[F4].values, df["DO"].values, df["Station"].values
        preds, trues = [], []
        for tr, te in LeaveOneGroupOut().split(X, y, g):
            m = XGBRegressor(n_estimators=100, max_depth=4, learning_rate=0.1,
                             random_state=42, verbosity=0)
            m.fit(X[tr], y[tr])
            preds.extend(m.predict(X[te])); trues.extend(y[te])
        return np.array(trues), np.array(preds)

    fig, axes = plt.subplots(1, 2, figsize=(9, 4))
    for ax, (title, paths) in zip(axes, [("HP-only (vùng Cát Bà)", [HP_DATA_PATH]),
                                          ("QN+HP gộp", [QN_DATA_PATH, HP_DATA_PATH])]):
        t, p = loo_do(paths)
        r2 = r2_score(t, p)
        ax.scatter(t, p, s=10, alpha=0.4, color="#2ca02c" if r2 > 0 else "#d62728")
        lim = [min(t.min(), p.min()), max(t.max(), p.max())]
        ax.plot(lim, lim, "k--", lw=1, alpha=0.6)
        ax.set_xlabel("DO thật (mg/L)"); ax.set_ylabel("DO dự đoán (mg/L)")
        ax.set_title(f"{title}\n$R^2$ = {r2:.3f}", fontsize=10)
    fig.suptitle("Dự đoán DO (LOO-CV): tách HP đoán được; gộp QN+HP thì hỏng", fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    out = FIG_DIR / "do_per_region.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print("saved", out)


def fig_median_r2():
    """Chứng minh bằng số: các chỉ số median-default KHÔNG đoán được (trừ Salinity)."""
    import warnings
    warnings.filterwarnings("ignore")
    from sklearn.model_selection import LeaveOneGroupOut
    from sklearn.metrics import r2_score
    from xgboost import XGBRegressor
    from core.impute import build_training_data, FEATURES_4

    PARAMS = ["Salinity", "COD", "CN", "As", "Cd", "Pb", "Cu", "Hg",
              "Zn", "Total_Cr", "Coliform", "H2S"]

    def loo(df, feats, tgt):
        d = df.dropna(subset=feats + [tgt])
        if d["Station"].nunique() < 3 or len(d) < 20:
            return None, False
        s = d[tgt]
        if s.std() == 0:
            return 1.0, True   # cột hằng số → R² degenerate
        X, y, g = d[feats].values, s.values, d["Station"].values
        P, T = [], []
        for tr, te in LeaveOneGroupOut().split(X, y, g):
            if len(set(g[tr])) < 2:
                continue
            m = XGBRegressor(n_estimators=100, max_depth=4, learning_rate=0.1,
                             random_state=42, verbosity=0)
            m.fit(X[tr], y[tr]); P.extend(m.predict(X[te])); T.extend(y[te])
        if len(T) < 5:
            return None, False
        return round(float(r2_score(T, P)), 3), False

    res = {}  # param -> {region: (r2, is_const)}
    for region in ["haiphong", "quangninh"]:
        df = build_training_data(region)
        F = [f for f in FEATURES_4 if f in df.columns]
        for p in PARAMS:
            if p in df.columns and not df[p].isnull().all():
                res.setdefault(p, {})[region] = loo(df, F, p)

    params = [p for p in PARAMS if p in res]
    y = np.arange(len(params))
    fig, ax = plt.subplots(figsize=(9.5, 5.6))
    for off, region, color in [(-0.2, "haiphong", "#2ca02c"), (0.2, "quangninh", "#1f77b4")]:
        vals, consts = [], []
        for p in params:
            rc = res[p].get(region)
            vals.append(np.nan if rc is None else max(rc[0], -0.5))
            consts.append(bool(rc and rc[1]))
        bars = ax.barh(y + off, vals, 0.38, label=region, color=color, alpha=0.85)
        for b, c, v in zip(bars, consts, vals):
            if c:
                b.set_hatch("///"); b.set_edgecolor("black")
                ax.text(1.0, b.get_y() + 0.19, " hằng số→median", va="center", fontsize=7, color="gray")
            elif np.isnan(v):
                ax.text(0.01, b.get_y() + 0.19, "vắng", va="center", fontsize=7, color="gray")
    ax.axvline(0.2, ls="--", color="orange", lw=1.3)
    ax.axvline(0.4, ls="--", color="green", lw=1.3)
    ax.axvline(0, color="black", lw=0.8)
    ax.text(0.21, len(params) - 0.3, "ngưỡng dùng ML (0,2)", color="#cc7a00", fontsize=8)
    ax.set_yticks(y); ax.set_yticklabels(params)
    ax.set_xlabel("$R^2$ (LOO-CV, 4-feat)"); ax.set_xlim(-0.5, 1.15)
    ax.invert_yaxis()
    ax.set_title("Bằng chứng R²: chỉ Salinity đoán được ỔN ĐỊNH cả 2 vùng;\n"
                 "kim loại HP>0,2 là gần-LOD + KHÔNG lặp lại ở QN (97 trạm) → coi là nhiễu, giữ median",
                 fontsize=10)
    ax.legend(loc="lower right", fontsize=9)
    fig.tight_layout()
    out = FIG_DIR / "median_params_r2.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print("saved", out)


def fig_impute_method():
    """Sơ đồ phương pháp nội suy: train từ data thật (X sensor → y thiếu), LOO-CV, deploy."""
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")

    def box(x, y, w, h, text, fc, fs=9, bold=False):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6",
                     fc=fc, ec="black", lw=1.1))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fs, weight="bold" if bold else "normal")

    def arrow(x1, y1, x2, y2):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                     mutation_scale=16, lw=1.4, color="#333"))

    # ---- Hàng trên: HUẤN LUYỆN (offline) ----
    ax.text(2, 95, "HUẤN LUYỆN (offline — data quan trắc thật theo quý)",
            fontsize=10.5, weight="bold", color="#1f4e79")
    box(1, 70, 22, 16, "Data thật\nHP / QN\n(theo trạm, quý)", "#dbe9f6", bold=True)
    box(28, 78, 24, 10, "X = sensor đo:\nNH3, pH, Temp, TSS (+COD)", "#d5efd5")
    box(28, 64, 24, 10, "y = chỉ số thiếu:\nDO, Salinity, PO4, BOD5, ...", "#fde0d0")
    box(57, 70, 17, 16, "XGBoost\n1 model /\nchỉ số / vùng", "#fff2cc", bold=True)
    box(79, 70, 20, 16, "LOO-CV theo trạm:\ntrain n$-$1 trạm,\nvalidate 1 trạm\n$\\to$ R²", "#eadcf6", fs=8.5, bold=True)
    arrow(23, 80, 28, 83)   # data -> X
    arrow(23, 76, 28, 69)   # data -> y
    arrow(52, 82, 57, 80)   # X -> xgb
    arrow(52, 68, 57, 74)   # y -> xgb
    arrow(74, 78, 79, 78)   # xgb -> loocv

    # ---- Hàng dưới: TRIỂN KHAI (online) ----
    ax.text(2, 45, "TRIỂN KHAI (online — sensor GreenLab realtime)",
            fontsize=10.5, weight="bold", color="#1f4e79")
    box(1, 18, 20, 16, "Sensor đo X\nNH3, pH,\nTemp, TSS", "#d5efd5", bold=True)
    box(26, 18, 18, 16, "Model đã\nhuấn luyện\n(theo vùng)", "#fff2cc", bold=True)
    box(49, 18, 20, 16, "$\\hat{y}$ chỉ số thiếu\n(DO, PO4 …)\n+ hạng tin cậy", "#fde0d0", bold=True)
    box(74, 18, 24, 16, "Ghép đủ chỉ số\n$\\to$ phân loại\nphù hợp", "#dbe9f6", bold=True)
    arrow(21, 26, 26, 26); arrow(44, 26, 49, 26); arrow(69, 26, 74, 26)

    ax.text(50, 7,
            "Nội suy CROSS-SECTIONAL: đoán từ chỉ số đo CÙNG LÚC (không phải forecast thời gian). "
            "CV theo trạm $\\Rightarrow$ không rò rỉ không gian.",
            ha="center", fontsize=8.8, style="italic", color="#444")
    fig.tight_layout()
    out = FIG_DIR / "impute_method.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print("saved", out)


def fig_r2_all():
    """R² LOO-CV của TẤT CẢ 5 chỉ số nội suy, đọc từ cv_r2.json đã train."""
    import json
    from core.config import IMPUTER_DIR
    cv = json.loads((Path(IMPUTER_DIR) / "cv_r2.json").read_text())
    targets = ["DO", "Salinity", "PO4", "Transparency", "BOD5", "Alkalinity"]
    # 3 series operative: HP 4-feat (Cát Bà), QN 5-feat, QN 4-feat
    series = [("HP 4-feat", cv["haiphong"]["4feat"], "#2ca02c"),
              ("QN 5-feat", cv["quangninh"]["5feat"], "#1f77b4"),
              ("QN 4-feat", cv["quangninh"]["4feat"], "#ff7f0e")]
    artifacts = {("QN 5-feat", "BOD5"), ("QN 5-feat", "Alkalinity")}
    fig, ax = plt.subplots(figsize=(9.2, 4.2))
    n = len(series); w = 0.26
    x = np.arange(len(targets))
    for i, (lbl, d, color) in enumerate(series):
        vals, hatches = [], []
        for t in targets:
            v = d.get(t)
            vals.append(np.nan if v is None else max(v, -0.7))  # clip + NaN cho cột vắng
            hatches.append("///" if (lbl, t) in artifacts else "")
        bars = ax.bar(x + (i - (n - 1) / 2) * w, vals, w, label=lbl, color=color, alpha=0.85)
        for b, t, h in zip(bars, targets, hatches):
            if h:
                b.set_hatch(h); b.set_edgecolor("black")
                ax.text(b.get_x() + w / 2, 1.0, "†", ha="center", fontsize=12)
            if np.isnan(b.get_height()):
                ax.text(b.get_x() + w / 2, 0.02, "vắng\ncột", ha="center", va="bottom",
                        fontsize=6.5, color="gray")
    # 3 mức tin cậy: dải vàng = ML-yếu (0.2–0.4); trên 0.4 = ML-mạnh; dưới 0.2 = median
    ax.axhspan(0.2, 0.4, color="orange", alpha=0.10, zorder=0)
    ax.axhline(0.4, ls="--", color="green", lw=1.3)
    ax.axhline(0.2, ls="--", color="orange", lw=1.3)
    ax.text(len(targets) - 0.5, 0.42, "mạnh: R² ≥ 0,4", color="green", fontsize=8, ha="right")
    ax.text(len(targets) - 0.5, 0.22, "yếu: 0,2 ≤ R² < 0,4 (gắn cờ)", color="#cc7a00", fontsize=8, ha="right")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(x); ax.set_xticklabels(targets)
    ax.set_ylabel("$R^2$ (LOO-CV)"); ax.set_ylim(-0.75, 1.12)
    ax.set_title("R² nội suy 5 chỉ số × 3 cấu hình — 3 mức: mạnh / yếu / median; † artifact (loại bất kể R²)")
    ax.legend(loc="lower left", fontsize=8.5)
    fig.tight_layout()
    out = FIG_DIR / "r2_all.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print("saved", out)


def fig_bod5_cod_scatter():
    """BOD5 vs COD trong data QN huấn luyện — lộ artifact R²=0.9999."""
    df = build_training_data("quangninh")   # BOD5/Alkalinity chỉ có trong QN
    sub = df[["COD", "BOD5", "Alkalinity"]].dropna()
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.8))
    for ax, col in zip(axes, ["BOD5", "Alkalinity"]):
        ax.scatter(sub["COD"], sub[col], s=8, alpha=0.4, color="#1f77b4")
        r = sub["COD"].corr(sub[col])
        ax.set_xlabel("COD (mg/L)")
        ax.set_ylabel(f"{col} (mg/L)")
        ax.set_title(f"{col} vs COD  (corr = {r:.3f})", fontsize=10)
    fig.suptitle("Data QN/HP: BOD5 & Alkalinity gần như tuyến tính theo COD → R² 0.999 là artifact", fontsize=9.5)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = FIG_DIR / "bod5_cod_scatter.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print("saved", out)


if __name__ == "__main__":
    rt = _load_realtime()
    fig_data_coverage(rt)
    fig_value_dist(rt)
    fig_cod_timeline(rt)
    fig_sensor_panel(rt)
    fig_do_per_region()
    fig_impute_method()
    fig_median_r2()
    fig_r2_all()
    fig_bod5_cod_scatter()
    print("Done. Figures in", FIG_DIR)
