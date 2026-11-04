"""plot_dsw_vs_notsp.py -- bar-chart suite + cycle-time pies + system diagram.

Labels used in every figure:
    NO_TSP                        -> "Fixed Time"
    CHAMP_ADAPTIVE_AIMSUN_DSW     -> "Adaptive System with TSP"

Reads:
    paxwin_adaptive_dsw_5seeds.csv
    dsw_vs_notsp_junctions.csv
    dsw_vs_notsp_main_side.csv
    kg/logs/plan_evolution_NO_TSP_*.csv
    kg/logs/plan_evolution_CHAMP_ADAPTIVE_AIMSUN_DSW_*.csv

Writes (PNG, 200 dpi):
    fig1_person_delay_by_mode.png
    fig2_main_vs_side_delay.png
    fig3_junction_speed.png
    fig4_junction_queue.png
    fig5_junction_density.png
    fig6_network_scorecard.png
    fig7_junction_main_side_delay.png
    fig8_system_diagram.png
    fig9_cycle_pie_36385.png
    dsw_vs_notsp_dashboard.png
"""
import glob
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Patch

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_LABEL = "Fixed Time"
ARM_LABEL = "Adaptive System with TSP"
C_BASE = "#9aa4ad"
C_ARM = "#1e6fd9"
C_GOOD = "#2e7d32"
C_BAD = "#c62828"

plt.rcParams.update({
    "figure.dpi": 110, "savefig.dpi": 200, "font.size": 10,
    "axes.titlesize": 11, "axes.titleweight": "bold",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid.axis": "y", "axes.grid": True, "grid.alpha": 0.25,
    "legend.frameon": False, "figure.facecolor": "white",
})

df = pd.read_csv(os.path.join(HERE, "paxwin_adaptive_dsw_5seeds.csv"),
                 encoding="utf-8-sig", engine="python")
df["total_pax_delay_h"] = df["stats_Obj_Z1_delay_paxs"] / 3600.0
df["bus_pax_delay_h"] = df["stats_SimBusDelay_pax_s"] / 3600.0
df["car_pax_delay_h"] = df["stats_SimCarDelay_pax_s"] / 3600.0
df["truck_pax_delay_h"] = df["stats_SimTruckDelay_pax_s"] / 3600.0
J = pd.read_csv(os.path.join(HERE, "dsw_vs_notsp_junctions.csv"))
MS = pd.read_csv(os.path.join(HERE, "dsw_vs_notsp_main_side.csv"))


def _bars(ax, labels, a, b, title, ylabel, fmt="{:.1f}", pct=True,
          higher_is_better=False, show_values=True, xtick_rotation=0):
    x = np.arange(len(labels))
    w = 0.38
    ax.bar(x - w / 2, a, w, label=BASE_LABEL, color=C_BASE, edgecolor="white")
    ax.bar(x + w / 2, b, w, label=ARM_LABEL, color=C_ARM, edgecolor="white")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=xtick_rotation,
                       ha="right" if xtick_rotation else "center")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(fontsize=8, loc="best")
    ymax = max(float(np.nanmax(a)), float(np.nanmax(b)), 1e-9)
    ax.set_ylim(0, ymax * 1.16)
    for xi, (av, bv) in enumerate(zip(a, b)):
        if show_values:
            ax.text(xi - w / 2, av, fmt.format(av), ha="center", va="bottom", fontsize=6.2)
            ax.text(xi + w / 2, bv, fmt.format(bv), ha="center", va="bottom", fontsize=6.2)
        if pct and av not in (0, 0.0):
            good = (bv >= av) if higher_is_better else (bv <= av)
            ax.annotate(f"{(100*(bv-av)/av):+.0f}%", xy=(xi, 0),
                        xycoords=("data", "axes fraction"),
                        xytext=(0, -30), textcoords="offset points",
                        ha="center", va="top", fontsize=7,
                        color=C_GOOD if good else C_BAD, fontweight="bold")


# ── 1. person delay by mode ─────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
dlg = lambda arm, c: df[df.run_experiment == arm][c].mean()
modes = [("bus_pax_delay_h", "Bus"), ("car_pax_delay_h", "Car"),
         ("truck_pax_delay_h", "Truck"), ("total_pax_delay_h", "Total")]
_bars(axes[0], [m[1] for m in modes],
      [dlg("NO_TSP", m[0]) for m in modes],
      [dlg("CHAMP_ADAPTIVE_AIMSUN_DSW", m[0]) for m in modes],
      "Person-delay by mode (pax-hours)", "pax-hours")
per_pax = [("stats_AvgBusPassDelay_s", "Bus"), ("stats_AvgCarPassDelay_s", "Car"),
           ("stats_AvgTruckPassDelay_s", "Truck")]
_bars(axes[1], [m[1] for m in per_pax],
      [dlg("NO_TSP", m[0]) for m in per_pax],
      [dlg("CHAMP_ADAPTIVE_AIMSUN_DSW", m[0]) for m in per_pax],
      "Delay per passenger (s)", "seconds / passenger")
fig.suptitle("Fixed Time vs Adaptive System with TSP — person delay "
             "(5 seeds, mean)", fontweight="bold")
fig.tight_layout()
fig.savefig(os.path.join(HERE, "fig1_person_delay_by_mode.png"), bbox_inches="tight")
plt.close(fig)

# ── 2. main vs side delay ───────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(6.4, 4.2))
parts = [("stats_MainPassDelay_hrs", "Main"), ("stats_SidePassDelay_hrs", "Side"),
         ("stats_TotalPassDelay_hrs", "Total")]
_bars(ax, [p[1] for p in parts],
      [dlg("NO_TSP", p[0]) for p in parts],
      [dlg("CHAMP_ADAPTIVE_AIMSUN_DSW", p[0]) for p in parts],
      "Main vs side passenger-delay", "passenger-delay (h)")
fig.tight_layout()
fig.savefig(os.path.join(HERE, "fig2_main_vs_side_delay.png"), bbox_inches="tight")
plt.close(fig)

# ── 3-5. per-junction speed / queue / density ──────────────────────────────
J = J.sort_values("junction", key=lambda s: s.astype(str)).reset_index(drop=True)
jlab = [f"J{j}" for j in J.junction]
for fname, b, a, title, ylab, hib in [
        ("fig3_junction_speed.png", "speed_base", "speed_dsw",
         "Speed at each junction", "mean speed (km/h)", True),
        ("fig4_junction_queue.png", "queue_base", "queue_dsw",
         "Queue at each junction", "mean queue (veh)", False),
        ("fig5_junction_density.png", "density_base", "density_dsw",
         "Density at each junction", "mean density (veh/km)", False)]:
    fig, ax = plt.subplots(figsize=(11, 4.6))
    _bars(ax, jlab, J[b].values, J[a].values, title, ylab, fmt="{:.1f}",
          higher_is_better=hib)
    ax.tick_params(axis="x", labelsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, fname), bbox_inches="tight")
    plt.close(fig)

# ── 6. network scorecard (% change) ────────────────────────────────────────
score = [
    ("Total person-delay", -3.0, True),
    ("Bus pax delay", -7.3, True),
    ("Car pax delay", -2.4, True),
    ("Main delay", -2.5, True),
    ("Side delay", -3.8, True),
    ("Objective (pax/delay-h)", 8.5, True),
    ("Fleet speed", 1.1, True),
    ("Junction queue", -2.0, True),
    ("Junction density", -2.1, True),
    ("VQ wait", -93.4, True),
]
fig, ax = plt.subplots(figsize=(8.2, 4.6))
names = [s[0] for s in score][::-1]
vals = [s[1] for s in score][::-1]
good = [s[2] for s in score][::-1]
colors = [C_GOOD if g else C_BAD for g in good]
bars = ax.barh(names, vals, color=colors, alpha=0.85, edgecolor="white")
ax.axvline(0, color="black", lw=0.9)
for bar, v in zip(bars, vals):
    ax.text(v + (2 if v >= 0 else -2), bar.get_y() + bar.get_height() / 2,
            f"{v:+.1f}%", va="center", ha="left" if v >= 0 else "right",
            fontsize=8, fontweight="bold")
ax.set_xlim(-105, 18)
ax.set_xlabel("% change vs Fixed Time")
ax.set_title("Adaptive System with TSP — network scorecard\n"
             "(green = improvement, red = worsening)")
ax.grid(axis="x", alpha=0.25); ax.grid(axis="y", visible=False)
fig.tight_layout()
fig.savefig(os.path.join(HERE, "fig6_network_scorecard.png"), bbox_inches="tight")
plt.close(fig)

# ── 7. per-junction main vs side delay ─────────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(11, 6.4), sharex=True)
_bars(axes[0], jlab, J["main_delay_h_base"].values, J["main_delay_h_dsw"].values,
      "Main-corridor delay at each junction", "passenger-delay (h)", fmt="{:.0f}")
_bars(axes[1], jlab, J["side_delay_h_base"].values, J["side_delay_h_dsw"].values,
      "Side-road delay at each junction", "passenger-delay (h)", fmt="{:.1f}")
axes[1].tick_params(axis="x", labelsize=8)
fig.suptitle("Main vs side delay by junction — Fixed Time vs Adaptive System with TSP",
             fontweight="bold")
fig.tight_layout()
fig.savefig(os.path.join(HERE, "fig7_junction_main_side_delay.png"), bbox_inches="tight")
plt.close(fig)

# ── 8. system diagram ──────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(11, 4.6))
ax.set_xlim(0, 10); ax.set_ylim(0, 5); ax.axis("off")

def box(x, y, w, h, txt, fc):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.03,rounding_size=0.12",
                                fc=fc, ec="#37474f", lw=1.2))
    ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center", fontsize=9)

ax.text(2.4, 4.55, "FIXED TIME", ha="center", fontsize=13, fontweight="bold", color="#455a64")
ax.text(7.6, 4.55, "ADAPTIVE SYSTEM WITH TSP", ha="center", fontsize=13,
        fontweight="bold", color=C_ARM)
for i, t in enumerate(["Pre-timed plans", "No adaptation", "No bus priority"]):
    box(0.7, 3.2 - i * 0.95, 3.4, 0.62, t, "#eceff1")
for i, t in enumerate(["1 s measured state", "Cycle-level plan library",
                       "Saturation (DS) dominant plan choice", "Guarded bus TSP overlay"]):
    box(5.9, 3.4 - i * 0.8, 3.4, 0.58, t, "#e3f0ff")
ax.annotate("", xy=(5.7, 2.5), xytext=(4.3, 2.5),
            arrowprops=dict(arrowstyle="->", lw=1.4, color="#37474f"))
ax.text(5.0, 2.72, "adapt", ha="center", fontsize=8, color="#37474f")
ax.text(5.0, 0.55,
        "5 seeds (300/400/500/600/700): total person-delay −3.0%   •   "
        "bus pax −7.3%   •   car pax −2.4%   •   VQ wait −93%",
        ha="center", fontsize=9, style="italic")
ax.set_title("Control architecture compared", fontweight="bold")
fig.tight_layout()
fig.savefig(os.path.join(HERE, "fig8_system_diagram.png"), bbox_inches="tight")
plt.close(fig)

# ── 9. cycle-time pies for one junction ────────────────────────────────────
JUNC = "36385"
no_files = sorted(glob.glob(os.path.join(HERE, "kg", "logs", "plan_evolution_NO_TSP_*.csv")))
arm_files = sorted(glob.glob(os.path.join(HERE, "kg", "logs",
                                          "plan_evolution_CHAMP_ADAPTIVE_AIMSUN_DSW_*.csv")))

def phase_frame(path):
    d = pd.read_csv(path, encoding="utf-8-sig", engine="python")
    d["junction_id"] = d["junction_id"].astype(str)
    return d[d.junction_id == JUNC]

fixed = phase_frame(no_files[-1]).set_index("phase")
fixed_g = fixed["init_green_s"].astype(float)
fixed_cycle = float(fixed["init_cycle_s"].iloc[0])

arm_frames = [phase_frame(f) for f in arm_files if len(phase_frame(f))]
if arm_frames:
    stacked = pd.concat([f.set_index("phase")["final_green_s"] for f in arm_frames],
                        axis=1).astype(float)
    arm_g = stacked.mean(axis=1)
    arm_cycle = float(np.mean([float(f["final_cycle_s"].iloc[0]) for f in arm_frames]))
else:
    arm_g, arm_cycle = fixed_g, fixed_cycle

phases = sorted(set(fixed_g.index) | set(arm_g.index))
fixed_g = fixed_g.reindex(phases).fillna(0.0)
arm_g = arm_g.reindex(phases).fillna(0.0)
cmap = plt.get_cmap("tab10")
colors = [cmap(i % 10) for i in range(len(phases))]
labels = [f"P{p}" for p in phases]

fig, axes = plt.subplots(1, 2, figsize=(11, 5.4))
for ax, g, cyc, title in [
        (axes[0], fixed_g, fixed_cycle, f"{BASE_LABEL}\ncycle = {fixed_cycle:.0f} s"),
        (axes[1], arm_g, arm_cycle,
         f"{ARM_LABEL}\ncycle = {arm_cycle:.1f} s")]:
    wedges, _ = ax.pie(g.values, colors=colors, startangle=90,
                       counterclock=False,
                       wedgeprops=dict(edgecolor="white", linewidth=0.8))
    ax.set_title(title, fontsize=10)
    for wdg, val in zip(wedges, g.values):
        if val / g.sum() >= 0.06:
            ang = np.deg2rad((wdg.theta1 + wdg.theta2) / 2)
            ax.text(0.66 * np.cos(ang), 0.66 * np.sin(ang),
                    f"{val:.0f}s", ha="center", va="center", fontsize=7.5,
                    fontweight="bold", color="black")
handles = [Patch(facecolor=colors[i], edgecolor="white",
                 label=f"{labels[i]}: {fixed_g.values[i]:.0f}s → {arm_g.values[i]:.1f}s")
           for i in range(len(phases))]
fig.legend(handles=handles, loc="lower center", ncol=5, fontsize=7.5,
           bbox_to_anchor=(0.5, -0.14))
fig.suptitle(f"Junction {JUNC} — green-time allocation within the cycle "
             f"(mean of 5 adaptive runs)", fontweight="bold")
fig.tight_layout(rect=(0, 0.02, 1, 0.95))
fig.savefig(os.path.join(HERE, "fig9_cycle_pie_36385.png"), bbox_inches="tight")
plt.close(fig)

# ── dashboard ──────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(14, 9))
gs = fig.add_gridspec(2, 2, hspace=0.42, wspace=0.28)
ax1 = fig.add_subplot(gs[0, 0])
_bars(ax1, [m[1] for m in modes],
      [dlg("NO_TSP", m[0]) for m in modes],
      [dlg("CHAMP_ADAPTIVE_AIMSUN_DSW", m[0]) for m in modes],
      "Person-delay by mode (pax-h)", "pax-hours")
ax2 = fig.add_subplot(gs[0, 1])
_bars(ax2, [p[1] for p in parts],
      [dlg("NO_TSP", p[0]) for p in parts],
      [dlg("CHAMP_ADAPTIVE_AIMSUN_DSW", p[0]) for p in parts],
      "Main vs side delay (h)", "passenger-delay (h)")
ax3 = fig.add_subplot(gs[1, 0])
_bars(ax3, jlab, J["speed_base"].values, J["speed_dsw"].values,
      "Speed at each junction", "km/h", fmt="{:.1f}", higher_is_better=True,
      show_values=False, xtick_rotation=45)
ax3.tick_params(axis="x", labelsize=7)
ax4 = fig.add_subplot(gs[1, 1])
_bars(ax4, jlab, J["queue_base"].values, J["queue_dsw"].values,
      "Queue at each junction", "veh", fmt="{:.1f}",
      show_values=False, xtick_rotation=45)
ax4.tick_params(axis="x", labelsize=7)
fig.suptitle("Fixed Time vs Adaptive System with TSP — 5-seed results",
             fontsize=14, fontweight="bold")
fig.savefig(os.path.join(HERE, "dsw_vs_notsp_dashboard.png"), bbox_inches="tight")
plt.close(fig)

print("wrote:")
for f in ["fig1_person_delay_by_mode.png", "fig2_main_vs_side_delay.png",
          "fig3_junction_speed.png", "fig4_junction_queue.png",
          "fig5_junction_density.png", "fig6_network_scorecard.png",
          "fig7_junction_main_side_delay.png", "fig8_system_diagram.png",
          "fig9_cycle_pie_36385.png", "dsw_vs_notsp_dashboard.png"]:
    p = os.path.join(HERE, f)
    print("  %-38s %s" % (f, "OK" if os.path.isfile(p) else "MISSING"))
