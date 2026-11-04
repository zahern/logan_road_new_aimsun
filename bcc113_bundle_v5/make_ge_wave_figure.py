"""Schematic for Fig. 1(b): what a green extension does to the green wave.

Space-time view of one coordinated band across three junctions.  (a) no action:
the bus arrives at J1 after its green, is held for the rest of the red, and then
meets the next band, losing time at each downstream junction.  (b) GE: the J1
green is extended by delta, the bus passes J1 inside the current band and
crosses J2 and J3 without stopping.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

FIG = r"C:\Users\ahernz\github_for_aimsun\TSP_Paper\TRB_STRIPPED\preprint"
TMP = r"C:\Users\ahernz\AppData\Local\Temp\opencode"

plt.rcParams.update({
    "font.family": "Arial",
    "font.size": 7.5,
    "axes.labelsize": 8,
    "axes.titlesize": 8.5,
    "xtick.labelsize": 7,
    "ytick.labelsize": 8,
    "axes.linewidth": 0.7,
    "pdf.fonttype": 42,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.03,
})

GREEN = "#289650"
RED = "#C82828"
BUS = "#1A1A1A"

# coordinated plan: J2 starts 25 s after J1, J3 25 s after J2; travel 20 s, so a
# bus leaving J1 on time has 5 s of slack in the band at each downstream junction
BANDS = {0: [(0, 40), (90, 130)],
         1: [(25, 65), (115, 155)],
         2: [(50, 90), (140, 180)]}
DELTA = 6.0
T_END = 180

fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.4), sharey=True,
                         gridspec_kw=dict(wspace=0.12))

for ax, title, extended in zip(axes, ("(a) no action", "(b) GE: $+\\delta$"),
                               (False, True)):
    for j, bands in BANDS.items():
        ax.add_patch(Rectangle((0, j - 0.20), T_END, 0.40, facecolor="#F2DEDE",
                               edgecolor="none", zorder=0))
        for (s, e) in bands:
            ax.add_patch(Rectangle((s, j - 0.20), e - s, 0.40, facecolor=GREEN,
                                   alpha=0.35, edgecolor=GREEN, linewidth=0.5,
                                   zorder=1))
    if extended:
        ax.add_patch(Rectangle((40, -0.20), DELTA, 0.40, facecolor=GREEN,
                               alpha=0.9, edgecolor=GREEN, linewidth=0.6,
                               zorder=2))
        ax.annotate("$+\\delta$", xy=(43, -0.22), xytext=(43, -0.52),
                    color=GREEN, ha="center", va="top", fontsize=6.8,
                    fontweight="bold",
                    arrowprops=dict(arrowstyle="-", color=GREEN, linewidth=0.6))

    if not extended:
        traj_t = [18, 44, 90, 110, 115, 135, 140]
        traj_y = [-0.6, 0, 0, 1, 1, 2, 2]
    else:
        traj_t = [18, 44, 64, 84]
        traj_y = [-0.6, 0, 1, 2]
    ax.plot(traj_t, traj_y, color=BUS, linewidth=1.5, zorder=4)
    for t, y in zip(traj_t[1:], traj_y[1:]):
        j = int(round(y))
        inside = any(s <= t <= e for s, e in BANDS[j])
        if extended and j == 0 and 40 <= t <= 40 + DELTA:
            inside = True          # the extension makes J1 green for the bus
        ax.plot(t, y, "o", markersize=5.5, zorder=5,
                markerfacecolor=GREEN if inside else RED,
                markeredgecolor="white", markeredgewidth=0.7)
    if not extended:
        ax.annotate("held for the red", xy=(67, 0), xytext=(67, 0.50),
                    fontsize=6.5, color=RED, ha="center",
                    arrowprops=dict(arrowstyle="-", color=RED, linewidth=0.6))
    else:
        ax.annotate("stays in the band", xy=(66, 1.6), xytext=(96, 2.42),
                    fontsize=6.5, color=GREEN, ha="center",
                    arrowprops=dict(arrowstyle="-", color=GREEN, linewidth=0.6))

    ax.set_yticks([0, 1, 2])
    ax.set_yticklabels(["J1", "J2", "J3"])
    ax.set_ylim(-0.75, 2.60)
    ax.set_xlim(0, T_END)
    ax.set_xticks([0, 30, 60, 90, 120, 150, 180])
    ax.set_xlabel("time (s)")
    ax.set_title(title, pad=4)
    ax.grid(axis="x", color="white", linewidth=0.6)
    ax.set_axisbelow(True)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(axis="y", length=0)

axes[0].set_ylabel("junction (route order)")

fig.savefig(os.path.join(FIG, "ge_wave.pdf"))
fig.savefig(os.path.join(FIG, "ge_wave.png"), dpi=300)
fig.savefig(os.path.join(TMP, "ge_wave.png"), dpi=300)
print("wrote ge_wave.pdf")
