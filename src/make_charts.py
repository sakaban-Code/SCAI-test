"""
make_charts.py — 行動層圖表產製（讀 data/weeks.json，輸出 charts/*.png）
"""
import json, pathlib
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = pathlib.Path(__file__).resolve().parent.parent

# CJK 字體（Actions 已安裝 fonts-noto-cjk）
for f in font_manager.findSystemFonts():
    if "NotoSansCJK" in f or "NotoSansTC" in f:
        font_manager.fontManager.addfont(f)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
        break
plt.rcParams["axes.unicode_minus"] = False

weeks = json.loads((ROOT / "data" / "weeks.json").read_text(encoding="utf-8"))
cur = weeks[-1]
CH = ROOT / "charts"; CH.mkdir(exist_ok=True)

DIMS = {"技術與研發能力": [3,4,5,6,13], "企業競爭與策略能力": [2,7,9,10,11,12,14],
        "全球市場與供應鏈": [16,21,22,23], "政策與營運資源環境": [15,17,18,19,20,24],
        "制度與產業規範": [0,1,8]}  # 憲法 v2.0 正本（提案書 1–25 編號，0-based）
DIM_COLORS = ["#2563eb", "#059669", "#d97706", "#dc2626", "#7c3aed"]

# ① 四象限定位圖（含歷史軌跡）
fig, ax = plt.subplots(figsize=(7, 7))
ax.axhline(0, color="gray", lw=1); ax.axvline(0, color="gray", lw=1)
ax.set_xlim(-1, 1); ax.set_ylim(-1, 1)
for (tx, ty, label) in [(0.5,0.5,"情境一：全球共榮的盛夏"),(0.5,-0.5,"情境三：孤島韌性突圍"),
                        (-0.5,0.5,"情境二：溫室裡的舞者"),(-0.5,-0.5,"情境四：末日求生戰役")]:
    ax.text(tx, ty, label, ha="center", va="center", fontsize=11, alpha=0.35)
xs = [w["xy"]["x"] for w in weeks]; ys = [w["xy"]["y"] for w in weeks]
ax.plot(xs, ys, "-o", color="#94a3b8", ms=5, alpha=0.7)
ax.plot(xs[-1], ys[-1], "o", color="#dc2626", ms=12)
ax.annotate(cur["week"], (xs[-1], ys[-1]), textcoords="offset points", xytext=(10, 8))
ax.set_xlabel("X：地緣與供應鏈聚合程度（碎裂 ↔ 聚合）")
ax.set_ylabel("Y：資源與政策充沛度（匱乏 ↔ 充沛）")
ax.set_title(f"{cur['week']} 情境定位（{cur['scenario']}）【推斷】")
fig.tight_layout(); fig.savefig(CH / "chart_quadrant.png", dpi=150); plt.close(fig)

# ② 25 項 KDF 權重橫條圖（依維度著色）
fig, ax = plt.subplots(figsize=(9, 10))
colors = []
for i in range(25):
    for j, rng in enumerate(DIMS.values()):
        if i in rng: colors.append(DIM_COLORS[j])
ax.barh(range(24, -1, -1), cur["w"], color=colors)
ax.set_yticks(range(24, -1, -1))
ax.set_yticklabels([f"KDF{i+1}" for i in range(25)], fontsize=8)
ax.axvline(50, color="gray", ls="--", lw=1)
ax.set_title(f"{cur['week']} 25 項 KDF 動態權重（中性=50）【推斷】")
fig.tight_layout(); fig.savefig(CH / "chart_kdf.png", dpi=150); plt.close(fig)

# ③ 五大維度雷達圖（本週實線、上週虛線）
def dim_scores(w): return [sum(w["w"][i] for i in r) / len(r) for r in DIMS.values()]
labels = list(DIMS.keys())
angles = np.linspace(0, 2*np.pi, len(labels), endpoint=False).tolist(); angles += angles[:1]
fig, ax = plt.subplots(figsize=(7, 7), subplot_kw={"polar": True})
v = dim_scores(cur) + dim_scores(cur)[:1]
ax.plot(angles, v, "-o", color="#dc2626", label=cur["week"]); ax.fill(angles, v, alpha=0.15, color="#dc2626")
if len(weeks) > 1:
    p = dim_scores(weeks[-2]) + dim_scores(weeks[-2])[:1]
    ax.plot(angles, p, "--o", color="#64748b", label=weeks[-2]["week"])
ax.set_xticks(angles[:-1]); ax.set_xticklabels(labels, fontsize=9)
ax.set_ylim(0, 100); ax.legend(loc="lower right")
ax.set_title("五大維度匯總分數【推斷】")
fig.tight_layout(); fig.savefig(CH / "chart_radar.png", dpi=150); plt.close(fig)

# ④ 五大維度趨勢折線（W2 起）
if len(weeks) > 1:
    fig, ax = plt.subplots(figsize=(9, 5))
    for j, name in enumerate(labels):
        ax.plot([w["week"] for w in weeks],
                [dim_scores(w)[j] for w in weeks],
                "-o", color=DIM_COLORS[j], label=name)
    ax.axhline(50, color="gray", ls="--", lw=1)
    ax.set_ylim(0, 100); ax.legend(fontsize=8); ax.set_title("五大維度趨勢【推斷】")
    fig.tight_layout(); fig.savefig(CH / "chart_trend.png", dpi=150); plt.close(fig)

print("[ok] 圖表已輸出 → charts/")
