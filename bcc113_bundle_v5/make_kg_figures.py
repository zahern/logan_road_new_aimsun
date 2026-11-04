"""Build the three KG telemetry figures for the paper."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

B = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
FIG = r"C:\Users\ahernz\github_for_aimsun\TSP_Paper\TRB_STRIPPED\preprint"
TMP = r"C:\Users\ahernz\AppData\Local\Temp\opencode"

BUSRED = "#C82828"
CARBLUE = "#2850B4"
GREEN = "#289650"
GREY = "#4D4D4D"

plt.rcParams.update({
    "font.family": "Arial",
    "font.size": 7,
    "axes.labelsize": 7,
    "axes.titlesize": 8,
    "xtick.labelsize": 6.5,
    "ytick.labelsize": 6.5,
    "legend.fontsize": 6.5,
    "axes.linewidth": 0.6,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "xtick.major.size": 2.5,
    "ytick.major.size": 2.5,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
})

ORDER = [39606, 39590, 36393, 36385, 39593, 39576, 39578, 39587, 1043762,
         39569, 39572, 38339]
JLAB = ["J%d" % (i + 1) for i in range(12)]

j = pd.read_csv(B + r"\kg_ladder_junction_delay.csv")
t = pd.read_csv(B + r"\kg_ladder_delay_timeseries.csv")
jt = pd.read_csv(B + r"\kg_ladder_junction_timeseries.csv")
a = pd.read_csv(B + r"\kg_ladder_actions.csv")
tr = pd.read_csv(B + r"\kg_ladder_triggers.csv")

ARMS = {"M1": ("8arm", "CHAMP_ADAPTIVE_AIMSUN_DSW"),
        "M5": ("priority", "CHAMP_ADAPTIVE_DSW_GAME_COOP"),
        "M4": ("priority", "CHAMP_ADAPTIVE_DSW_GAME_BUS"),
        "M3": ("priority", "CHAMP_ADAPTIVE_DSW_CELLQ_GATED"),
        "M2": ("priority", "CHAMP_ADAPTIVE_DSW_MARL_BUS"),
        "M0": ("priority", "NO_TSP")}
COL = {"M1": GREY, "M5": CARBLUE, "M4": BUSRED, "M3": "#7B4FB5", "M2": "#D07A00"}


RUNS = 5  # five eval seeds per arm


def junc_delta(label):
    batch, arm = ARMS[label]
    sub = j[j.batch == batch]
    base = (sub[sub.arm == "NO_TSP"].groupby("junction").delay_total_s.mean()
            .reindex(ORDER).div(3600))
    s = (sub[sub.arm == arm].groupby("junction").delay_total_s.mean()
         .reindex(ORDER).div(3600))
    return (s - base).values


# ------------------------------------------------------------------ figure 1
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.0, 2.55),
                               gridspec_kw=dict(width_ratios=[1.62, 1]))

x = np.arange(12)
w = 0.26
for k, lab in enumerate(("M1", "M5", "M4")):
    ax1.bar(x + (k - 1) * w, junc_delta(lab), w, color=COL[lab], label=lab,
            edgecolor="white", linewidth=0.3, zorder=3)
ax1.axhline(0, color="black", linewidth=0.7, zorder=4)
ax1.set_xticks(x)
ax1.set_xticklabels(JLAB)
ax1.set_ylabel("change in passenger delay\nvs fixed-time (pax$\\cdot$h)")
ax1.set_xlabel("junction in route order")
ax1.grid(axis="y", color="0.9", linewidth=0.5, zorder=0)
ax1.set_axisbelow(True)
for sp in ("top", "right"):
    ax1.spines[sp].set_visible(False)
ax1.legend(ncol=3, frameon=False, loc="lower left", handlelength=0.9,
           columnspacing=1.2, borderaxespad=0.2)

d_m1 = junc_delta("M1")
d_m5 = junc_delta("M5")
d_m4 = junc_delta("M4")
ax1.annotate("$J5$: $-21$ (M1), $-20$ (M5)", xy=(4, -20.4),
             xytext=(4.35, -27), fontsize=6, color="0.25",
             arrowprops=dict(arrowstyle="-", color="0.5", linewidth=0.5))
ax1.annotate("J1--J3: $+63$ (M4)", xy=(1.9, 31.1), xytext=(2.2, 40),
             fontsize=6, color=BUSRED,
             arrowprops=dict(arrowstyle="-", color=BUSRED, linewidth=0.5))
ax1.set_ylim(-38, 46)

# cumulative profile: every rung, plus the fixed-time reference at zero
grid_min = np.arange(0, 75.1, 5)
ax2.axhline(0, color="black", linewidth=0.7, linestyle="--", label="M0", zorder=1)
for lab in ("M1", "M2", "M3", "M5", "M4"):
    batch, arm = ARMS[lab]
    s = t[(t.batch == batch) & (t.arm == arm)]
    b = t[(t.batch == batch) & (t.arm == "NO_TSP")]
    def cum(df):
        out = []
        for _, g in df.groupby("seed"):
            g = g.sort_values("sim_time_s")
            out.append(np.interp(grid_min * 60, g.sim_time_s, g.delay_total_s))
        return np.mean(out, axis=0) / 3600
    ax2.plot(grid_min, cum(s) - cum(b), color=COL[lab], label=lab,
             linewidth=1.25 if lab in ("M1", "M5", "M4") else 0.95,
             zorder=3 if lab in ("M1", "M5", "M4") else 2)
ax2.axvline(7, color="0.6", linestyle=":", linewidth=0.7)
ax2.set_xlabel("simulated time (min)")
ax2.set_ylabel("cumulative change in delay\nvs fixed-time (pax$\\cdot$h)")
ax2.grid(color="0.9", linewidth=0.5)
ax2.set_axisbelow(True)
for sp in ("top", "right"):
    ax2.spines[sp].set_visible(False)
_h, _l = ax2.get_legend_handles_labels()
_order = [0, 1, 2, 3, 5, 4]
ax2.legend([_h[i] for i in _order], [_l[i] for i in _order],
           frameon=False, loc="upper left", ncol=3, handlelength=1.0,
           columnspacing=0.9, labelspacing=0.25)

fig.savefig(os.path.join(FIG, "kg_where_wins.pdf"))
fig.savefig(os.path.join(TMP, "kg_where_wins.png"), dpi=210)
plt.close(fig)

# ------------------------------------------------------------------ figure 2
cmap = LinearSegmentedColormap.from_list(
    "kgq", ["#FFFFFF", "#FBE3B6", "#F2A45C", "#D9534F", "#7A1F1F"])
fig, axes = plt.subplots(2, 2, figsize=(6.6, 3.5), sharey=True,
                         gridspec_kw=dict(wspace=0.07, hspace=0.24))
vmax = 50
tgrid = np.arange(0, 76, 1.0)
tcent = np.arange(0.5, 75.5, 1.0)


def queue_matrix(batch, arm):
    s = jt[(jt.batch == batch) & (jt.arm == arm)]
    m = np.zeros((12, len(tcent)))
    for k, jid in enumerate(ORDER):
        per_seed = []
        for seed, g in s[s.junction_id == jid].groupby("seed"):
            g = g.sort_values("sim_time_s")
            per_seed.append(np.interp(tcent * 60, g.sim_time_s, g.queue_total))
        m[k] = np.mean(per_seed, axis=0)
    kernel = np.ones(3) / 3.0
    return np.apply_along_axis(lambda v: np.convolve(v, kernel, mode="same"), 1, m)


m0 = queue_matrix(*ARMS["M0"])
m5 = queue_matrix(*ARMS["M5"])
m4 = queue_matrix(*ARMS["M4"])

panels = [
    (axes[0][0], m0, "M0 NO_TSP (fixed-time state)", cmap, 0, vmax),
    (axes[0][1], m4, "M4 GAME_BUS (state)", cmap, 0, vmax),
    (axes[1][0], m5 - m0, "M5 $-$ M0 (change in queue)", "RdBu_r", -22, 22),
    (axes[1][1], m4 - m0, "M4 $-$ M0 (change in queue)", "RdBu_r", -22, 22),
]
for ax, mat, title, cm, lo, hi in panels:
    mesh = ax.pcolormesh(tgrid, np.arange(13), mat, cmap=cm, vmin=lo, vmax=hi,
                         shading="flat", rasterized=True)
    ax.set_xticks([0, 15, 30, 45, 60, 75])
    ax.set_xlim(0, 75)
    ax.set_title(title, pad=3)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
# shared y axis: invert once so J1 sits at the top in every panel
axes[0][0].invert_yaxis()
axes[0][0].set_yticks(np.arange(12) + 0.5)
axes[0][0].set_yticklabels(JLAB, fontsize=6)
axes[1][0].set_xlabel("time (min)")
axes[1][1].set_xlabel("time (min)")
axes[0][0].set_ylabel("junction (route order)")
axes[1][0].set_ylabel("junction (route order)")
cax1 = fig.add_axes([0.905, 0.575, 0.010, 0.34])
cb1 = fig.colorbar(mesh, cax=cax1)
cax2 = fig.add_axes([0.905, 0.13, 0.010, 0.30])
# colourbars are added after the loop, so build them explicitly from scalars
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
sm1 = ScalarMappable(norm=Normalize(0, vmax), cmap=cmap)
cb1 = fig.colorbar(sm1, cax=cax1)
cb1.set_label("queue (veh)", fontsize=6)
cb1.ax.tick_params(labelsize=5.5)
sm2 = ScalarMappable(norm=Normalize(-22, 22), cmap="RdBu_r")
cb2 = fig.colorbar(sm2, cax=cax2)
cb2.set_label("queue change (veh)", fontsize=6)
cb2.ax.tick_params(labelsize=5.5)
fig.savefig(os.path.join(FIG, "kg_true_states.pdf"))
fig.savefig(os.path.join(TMP, "kg_true_states.png"), dpi=210)
plt.close(fig)

# ------------------------------------------------------------------ figure 3
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.0, 2.5),
                               gridspec_kw=dict(width_ratios=[1.28, 1]))
style = {"M3": dict(marker="o", s=26, color=COL["M3"], label="M3 CELLQ"),
         "M4": dict(marker="^", s=26, color=COL["M4"], label="M4 GAME_BUS"),
         "M5": dict(marker="s", s=22, color=COL["M5"], label="M5 GAME_COOP"),
         "M2": dict(marker="*", s=60, color=COL["M2"], label="M2 MARL")}
side_med = tr[(tr.is_chosen == 1) & (tr.action == "NO_ACTION")].side_max_flow_vph.median()
for lab in ("M2", "M3", "M4", "M5"):
    _, arm = ARMS[lab]
    s = a[a.arm == arm]
    if s.empty:
        continue
    ax1.scatter(s.side_vph.clip(lower=8), s.main_x, alpha=0.9,
                linewidths=0.3, edgecolors="white", **style[lab])
ax1.set_xscale("log")
ax1.set_xlim(7, 6000)
ax1.set_ylim(-0.03, 1.06)
ax1.set_xlabel("side-street flow at the grant (veh/h, log scale)")
ax1.set_ylabel("main-approach degree of saturation $x$")
ax1.axvline(side_med, color="0.45", linestyle="--", linewidth=0.7)
ax1.text(side_med * 1.12, 0.90, "median side flow\nat held decisions", fontsize=5.6,
         color="0.35", va="top")
ax1.grid(color="0.92", linewidth=0.5)
ax1.set_axisbelow(True)
for sp in ("top", "right"):
    ax1.spines[sp].set_visible(False)
ax1.legend(frameon=True, framealpha=0.92, edgecolor="none", loc="lower left",
           handletextpad=0.3, borderaxespad=0.3, labelspacing=0.25)

# median predicted benefit vs cost
labs, ben, oth, neg = [], [], [], []
for lab in ("M2", "M3", "M4", "M5"):
    _, arm = ARMS[lab]
    s = a[a.arm == arm]
    if s.empty:
        continue
    labs.append("%s (%.1f/run)" % (lab, len(s) / RUNS))
    ben.append(s.pred_bus.median())
    oth.append(-s.pred_other.median())
    neg.append(100 * (s.pred_net <= 0).mean())
y = np.arange(len(labs))
ax2.barh(y + 0.19, ben, 0.34, color=GREEN, label="bus benefit")
ax2.barh(y - 0.19, oth, 0.34, color=BUSRED, label="cost to others")
ax2.axvline(0, color="black", linewidth=0.7)
ax2.set_yticks(y)
ax2.set_yticklabels(labs, fontsize=6.2)
ax2.invert_yaxis()
ax2.set_xlim(-500, 2050)
ax2.set_xlabel("median predicted effect at the grant (pax$\\cdot$s)")
ax2.grid(axis="x", color="0.92", linewidth=0.5)
ax2.set_axisbelow(True)
for sp in ("top", "right"):
    ax2.spines[sp].set_visible(False)
for yi, b, nn in zip(y, ben, neg):
    if nn > 0:
        ax2.text(b + 40, yi + 0.19, "%.0f%% net$\\leq$0" % nn,
                 fontsize=6, color=BUSRED, ha="left", va="center")
ax2.legend(frameon=False, loc="upper right", handlelength=0.9,
           borderaxespad=0.2, labelspacing=0.25)
fig.savefig(os.path.join(FIG, "kg_trigger_states.pdf"))
fig.savefig(os.path.join(TMP, "kg_trigger_states.png"), dpi=210)
plt.close(fig)

print("wrote figures")
for f in ("kg_where_wins", "kg_true_states", "kg_trigger_states"):
    print("  %-22s %6d KB" % (f, os.path.getsize(os.path.join(FIG, f + ".pdf")) // 1024))
