"""
corridor_architecture.py
========================
Generates a PNG diagram of the corridor TSP control architecture.
Run directly:  python corridor_architecture.py
Output:        corridor_architecture.png  (same directory as this file)
"""
import os
import sys

sys.path.insert(0, r"C:\AimsunPackages")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
FIG_W, FIG_H = 18, 13
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "corridor_architecture.png")

# Colour palette
C_NORMAL  = "#b0bec5"   # grey   — no TSP
C_LOCAL   = "#81d4fa"   # light blue — local TSP (no CC)
C_COORD   = "#4fc3f7"   # medium blue — phase-based coord (CC active)
C_DISCRETE= "#29b6f6"   # vivid blue  — discrete-time best
C_CC      = "#0277bd"   # dark blue   — Corridor Coordinator box
C_ALGO    = "#e1f5fe"   # very light blue — algorithm option
C_PARAM   = "#f1f8e9"   # light green — parameters
C_JCT     = "#fff9c4"   # yellow — junction boxes
C_ARROW   = "#546e7a"   # dark grey arrows
C_TEXT    = "#212121"

# ---------------------------------------------------------------------------
# Helper: draw a rounded box with centred text
# ---------------------------------------------------------------------------
def rbox(ax, cx, cy, w, h, label, sub="", fc="#ffffff", ec="#90a4ae",
         fontsize=9, subfontsize=7.5, lw=1.2, bold=False):
    box = FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle="round,pad=0.04",
        facecolor=fc, edgecolor=ec, linewidth=lw, zorder=3,
    )
    ax.add_patch(box)
    weight = "bold" if bold else "normal"
    if sub:
        ax.text(cx, cy + 0.03, label, ha="center", va="center",
                fontsize=fontsize, color=C_TEXT, fontweight=weight, zorder=4,
                linespacing=1.3)
        ax.text(cx, cy - h * 0.28, sub, ha="center", va="center",
                fontsize=subfontsize, color="#546e7a", style="italic", zorder=4)
    else:
        ax.text(cx, cy, label, ha="center", va="center",
                fontsize=fontsize, color=C_TEXT, fontweight=weight, zorder=4,
                linespacing=1.3)
    return box


def arrow(ax, x0, y0, x1, y1, label="", color=C_ARROW, lw=1.4, style="->"):
    ax.annotate(
        "", xy=(x1, y1), xytext=(x0, y0),
        arrowprops=dict(arrowstyle=style, color=color,
                        lw=lw, connectionstyle="arc3,rad=0.0"),
        zorder=2,
    )
    if label:
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        ax.text(mx + 0.05, my, label, fontsize=7, color=color, va="center", zorder=5)


# ---------------------------------------------------------------------------
# Build figure
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
ax.set_xlim(0, FIG_W)
ax.set_ylim(0, FIG_H)
ax.axis("off")
fig.patch.set_facecolor("#fafafa")
ax.set_facecolor("#fafafa")

# ── Title ────────────────────────────────────────────────────────────────────
ax.text(FIG_W / 2, FIG_H - 0.4, "Corridor TSP Control Architecture",
        ha="center", va="top", fontsize=14, fontweight="bold", color=C_TEXT)
ax.text(FIG_W / 2, FIG_H - 0.85,
        "CONTROL_MODE selects the strategy; the Corridor Coordinator (CC) is "
        "shared by HARMONY (Phase-Based) and DYNAOPAC (Discrete-Time Best) modes.",
        ha="center", va="top", fontsize=8.5, color="#546e7a")

# ── Row 1: Control mode boxes ─────────────────────────────────────────────────
ROW1_Y = 10.8
MODE_H = 1.15
xs = [1.8, 4.7, 7.6, 11.0, 14.9]

rbox(ax, xs[0], ROW1_Y, 2.6, MODE_H,
     '"NORMAL"', 'Fixed plan\nno bus priority',
     fc=C_NORMAL, ec="#90a4ae", fontsize=9, bold=True)

rbox(ax, xs[1], ROW1_Y, 2.6, MODE_H,
     '"URTSP"', 'Unrestricted TSP\nGE + INS per junction',
     fc=C_LOCAL, ec="#4fc3f7", fontsize=9, bold=True)

rbox(ax, xs[2], ROW1_Y, 2.6, MODE_H,
     '"REWARD_TSP"', 'Cost-benefit TSP\nscores GE/INS/hold\neach step',
     fc=C_LOCAL, ec="#4fc3f7", fontsize=9, bold=True)

rbox(ax, xs[3], ROW1_Y, 3.2, MODE_H,
     '"HARMONY"', 'Phase-Based Coordination\nGE + INS  ·  CC pre-arms\ndownstream junctions',
     fc=C_COORD, ec="#0288d1", fontsize=9, bold=True, lw=2)

rbox(ax, xs[4], ROW1_Y, 3.2, MODE_H,
     '"DYNAOPAC"', 'Discrete-Time Best-Action\noptimizer + CC pre-arming\ncorridor-aware',
     fc=C_DISCRETE, ec="#01579b", fontsize=9, bold=True, lw=2)

# Label the row
ax.text(0.25, ROW1_Y, "Mode\n(CONTROL_MODE)", ha="center", va="center",
        fontsize=7.5, color="#546e7a", rotation=90)

# ── Arrows from HARMONY and DYNAOPAC down to CC ───────────────────────────────
CC_Y = 8.2
arrow(ax, xs[3], ROW1_Y - MODE_H / 2, xs[3], CC_Y + 0.7,
      color="#0288d1", lw=1.8)
arrow(ax, xs[4], ROW1_Y - MODE_H / 2, xs[4], CC_Y + 0.7,
      color="#01579b", lw=1.8)

# ── Corridor Coordinator box ──────────────────────────────────────────────────
CC_W, CC_H = 9.0, 1.4
CC_X = (xs[3] + xs[4]) / 2
rbox(ax, CC_X, CC_Y, CC_W, CC_H,
     "Corridor Coordinator  (CC)",
     "Tracks each bus with Kalman filter · predicts arrival at downstream junctions\n"
     "Fires pre-arm PRE_GREEN_LEAD_S before ETA · expires after PRE_REQ_TIMEOUT_S",
     fc=C_CC, ec="#01579b", fontsize=10.5, subfontsize=8, bold=True, lw=2)
ax.texts[-2].set_color("white")   # main label white on dark bg
ax.texts[-1].set_color("#b3e5fc")  # sub label light blue

# ── CC Parameters box ─────────────────────────────────────────────────────────
PARAM_Y = 6.35
PARAM_X = CC_X
PARAM_W, PARAM_H = 9.0, 1.55

params_lines = (
    "COORDINATED_TSP = True / False         COORDINATION_ALGO = KALMAN | SHOCKWAVE | OBJECTIVE | ADAPTIVE\n"
    "PRE_GREEN_LEAD_S = 50 s                MAX_PRE_ARM = 1  (next junction only)\n"
    "PREARM_MAX_SIGMA_S = 120 s             PRE_REQ_TIMEOUT_S = 120 s\n"
    "MAX_PREARM_HORIZON_S = 240 s           MAX_GE_EXTENSION_S = 10 s   ·   MAX_BP_INSERTION_S = 40 s"
)
box_param = FancyBboxPatch(
    (PARAM_X - PARAM_W / 2, PARAM_Y - PARAM_H / 2), PARAM_W, PARAM_H,
    boxstyle="round,pad=0.04",
    facecolor=C_PARAM, edgecolor="#aed581", linewidth=1.2, zorder=3,
)
ax.add_patch(box_param)
ax.text(PARAM_X, PARAM_Y + 0.38, "CC Parameters", ha="center", va="center",
        fontsize=8.5, fontweight="bold", color="#33691e", zorder=4)
ax.text(PARAM_X, PARAM_Y - 0.08, params_lines, ha="center", va="center",
        fontsize=7.2, color=C_TEXT, family="monospace", zorder=4, linespacing=1.5)

arrow(ax, CC_X, CC_Y - CC_H / 2, CC_X, PARAM_Y + PARAM_H / 2,
      color="#558b2f", lw=1.2)

# ── ETA Algorithm boxes ───────────────────────────────────────────────────────
ALGO_Y = 4.55
ALGO_XS = [CC_X - 4.0, CC_X - 1.33, CC_X + 1.33, CC_X + 4.0]
ALGO_W, ALGO_H = 2.4, 1.2

algo_data = [
    ("KALMAN",
     "1-D Kalman filter\nposition + speed\nBest for free-flow"),
    ("SHOCKWAVE",
     "Kalman ETA +\nqueue-clearance offset\nBest under congestion"),
    ("OBJECTIVE",
     "Variable lead time\nmaximises J = α·bus_saved\n− β·traffic_displaced"),
    ("ADAPTIVE",
     "Kalman + shockwave\n+ dynamic lead scaled\nby ETA uncertainty"),
]
for ax_x, (algo_name, desc) in zip(ALGO_XS, algo_data):
    rbox(ax, ax_x, ALGO_Y, ALGO_W, ALGO_H,
         algo_name, desc,
         fc=C_ALGO, ec="#0288d1", fontsize=8.5, subfontsize=7.5, bold=True)
    arrow(ax, PARAM_X if abs(ax_x - PARAM_X) < 0.1 else ax_x,
          PARAM_Y - PARAM_H / 2,
          ax_x, ALGO_Y + ALGO_H / 2,
          color="#0288d1", lw=1.0)

# Bracket label
ax.text(ALGO_XS[0] - 1.3, ALGO_Y, "ETA\nalgorithm",
        ha="center", va="center", fontsize=7.5, color="#546e7a", rotation=90)

# ── Downstream junction boxes ─────────────────────────────────────────────────
JCT_Y = 2.55
JCT_XS = [CC_X - 3.5, CC_X - 1.0, CC_X + 1.5, CC_X + 4.0]
JCT_W, JCT_H = 2.2, 0.95
jct_labels = [
    ("junction[i]", "bus detected here\nCC wave starts"),
    ("junction[i+1]", "pre-arm fired\n≥ PRE_GREEN_LEAD_S before ETA"),
    ("junction[i+2]", "queued pre-arm\n(if within horizon)"),
    ("junction[i+3]", "queued pre-arm\n(if within horizon)"),
]
for jx, (jname, jdesc) in zip(JCT_XS, jct_labels):
    rbox(ax, jx, JCT_Y, JCT_W, JCT_H, jname, jdesc,
         fc=C_JCT, ec="#f9a825", fontsize=8, subfontsize=7, bold=True)

# Bus direction arrow
arrow(ax, JCT_XS[0] + JCT_W / 2 + 0.05, JCT_Y,
      JCT_XS[-1] - JCT_W / 2 - 0.05, JCT_Y,
      label="bus direction →", color="#f57f17", lw=1.6, style="-|>")

# CC → junction arrows
for jx in JCT_XS[1:]:
    arrow(ax, CC_X, ALGO_Y - ALGO_H / 2 - 0.3, jx, JCT_Y + JCT_H / 2,
          color="#0277bd", lw=0.9)

# Detection arrow at junction[i]
arrow(ax, JCT_XS[0], JCT_Y + JCT_H / 2 + 0.05, CC_X, ALGO_Y - ALGO_H / 2 - 0.05,
      label="notify CC", color="#e65100", lw=1.3)

# ── Legend ────────────────────────────────────────────────────────────────────
legend_items = [
    mpatches.Patch(facecolor=C_NORMAL,   edgecolor="#90a4ae", label="NORMAL — no TSP"),
    mpatches.Patch(facecolor=C_LOCAL,    edgecolor="#4fc3f7", label="Local TSP (no CC)"),
    mpatches.Patch(facecolor=C_COORD,    edgecolor="#0288d1", label="Phase-Based Coord (CC active)"),
    mpatches.Patch(facecolor=C_DISCRETE, edgecolor="#01579b", label="Discrete-Time Best (CC active)"),
    mpatches.Patch(facecolor=C_CC,       edgecolor="#01579b", label="Corridor Coordinator (CC)"),
    mpatches.Patch(facecolor=C_JCT,      edgecolor="#f9a825", label="Junction along route"),
]
ax.legend(handles=legend_items, loc="lower left", fontsize=7.5,
          framealpha=0.9, edgecolor="#cfd8dc",
          bbox_to_anchor=(0.01, 0.01))

# ── Save ─────────────────────────────────────────────────────────────────────
plt.tight_layout(rect=[0, 0, 1, 0.97])
plt.savefig(OUT_PATH, dpi=150, bbox_inches="tight",
            facecolor=fig.get_facecolor())
plt.close(fig)
print(f"Saved: {OUT_PATH}")
