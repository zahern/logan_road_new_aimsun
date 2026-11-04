"""Poster-style KPI change chart for the paper's ladder (reference:
LR_fig_u01_corridor_kpis_poster).  One panel per rung; every row is a corridor
KPI, the dot is the mean paired change against fixed-time on the same seeds,
the whisker is the 95% t-interval across seeds, and the value is printed at the
right.

Usage:
    python -I make_kpi_delta_figure.py kg            # poster size
    python -I make_kpi_delta_figure.py logan
    python -I make_kpi_delta_figure.py kg paper      # journal size
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

B = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
FIG = r"C:\Users\ahernz\github_for_aimsun\TSP_Paper\TRB_STRIPPED\preprint"
TMP = r"C:\Users\ahernz\AppData\Local\Temp\opencode"

COL = {"M1": "#4D4D4D", "M5": "#2850B4", "M4": "#C82828"}

METRICS = [
    ("Person delay", "delay per person, all classes", "stats_AvgPassDelay_s"),
    ("Person delay", "delay per bus passenger", "stats_AvgBusPassDelay_s"),
    ("Person delay", "delay per car occupant", "stats_AvgCarPassDelay_s"),
    ("Person delay", "delay per truck occupant", "stats_AvgTruckPassDelay_s"),
    ("Person delay", "person delay, total", "stats_TotalPassDelay_hrs"),
    ("Corridor and side streets", "on corridor approaches", "stats_MainPassDelay_hrs"),
    ("Corridor and side streets", "on side-street approaches", "stats_SidePassDelay_hrs"),
    ("Traffic", "person passages", "stats_PaxEquivPassages"),
    ("Traffic", "speed at the junctions", "stats_Net_AvgSpeed_kmh"),
    ("Traffic", "queue at the junctions", "__queue__"),
    ("Traffic", "bus passage time at the junctions", "stats_AvgBusTT_s"),
    ("Traffic", "vehicle-km, corridor", "corridor_total_veh_km"),
]


def load(corridor):
    if corridor == "kg":
        kg = pd.read_csv(os.path.join(B, "paper_ladder_priority_kg.csv"))
        eight = pd.read_csv(os.path.join(B, "paper_ladder_8arm_kg.csv"))
        m1 = eight[eight.run_experiment == "CHAMP_ADAPTIVE_AIMSUN_DSW"]
        arms = [
            ("M1", "M1 adaptive base", "8arm", m1),
            ("M5", "M5 cooperative game", "priority",
             kg[kg.run_experiment == "CHAMP_ADAPTIVE_DSW_GAME_COOP"]),
            ("M4", "M4 bus-first game", "priority",
             kg[kg.run_experiment == "CHAMP_ADAPTIVE_DSW_GAME_BUS"]),
        ]
        base = kg[kg.run_experiment == "NO_TSP"]
        jt = pd.read_csv(os.path.join(B, "kg_ladder_junction_timeseries.csv"))
        q = jt.groupby(["arm", "seed"]).queue_total.mean()
        qmap = {(a, s): v for (a, s), v in q.items()}
        qbase = {s: qmap[("NO_TSP", s)] for s in base.run_seed.unique()}
        return arms, base, qmap, qbase
    lg = pd.read_csv(os.path.join(B, "paper_ladder_priority_logan.csv"))
    lg = lg[lg.run_experiment.astype(str).str.endswith("_LOGAN")
            | (lg.run_experiment == "NO_TSP")]
    arms = [
        ("M1", "M1 adaptive base", "logan",
         lg[lg.run_experiment == "CHAMP_ADAPTIVE_AIMSUN_DSW_LOGAN"]),
        ("M5", "M5 cooperative game", "logan",
         lg[lg.run_experiment == "CHAMP_ADAPTIVE_DSW_GAME_COOP_LOGAN"]),
        ("M4", "M4 bus-first game", "logan",
         lg[lg.run_experiment == "CHAMP_ADAPTIVE_DSW_GAME_BUS_LOGAN"]),
    ]
    base = lg[lg.run_experiment == "NO_TSP"]
    q = pd.read_csv(os.path.join(B, "logan_ladder_queue.csv"))
    qmap = {(r.arm, r.seed): r.queue_mean for r in q.itertuples()}
    qbase = {r.seed: r.queue_mean for r in q[q.arm == "NO_TSP"].itertuples()}
    return arms, base, qmap, qbase


def pct_ci(a, b, n):
    a, b = np.asarray(a, float), np.asarray(b, float)
    p = 100.0 * (a - b) / b
    t = {3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571}.get(n, 1.96)
    return p.mean(), t * p.std(ddof=1) / np.sqrt(len(p))


def main(corridor="kg", paper=False):
    base_font = 7.0 if paper else 9.0
    plt.rcParams.update({
        "font.family": "Arial",
        "font.size": base_font,
        "axes.labelsize": base_font + 1,
        "axes.titlesize": base_font + 2,
        "xtick.labelsize": base_font,
        "ytick.labelsize": base_font,
        "axes.linewidth": 0.7,
        "xtick.major.width": 0.7,
        "ytick.major.width": 0.7,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.04,
    })

    arms, base, qmap, qbase = load(corridor)
    seeds = sorted(base.run_seed.unique().tolist())
    n = len(seeds)

    rows, last = [], None
    for grp, label, col in METRICS:
        if col == "__queue__" and qmap is None:
            continue
        if grp != last:
            rows.append(("header", grp, None))
            last = grp
        rows.append(("metric", label, col))

    # compute every point first (also for the headline)
    res = {}
    for key, title, batch, df in arms:
        for kind, label, col in rows:
            if kind == "header":
                continue
            if col == "__queue__":
                a = np.array([qmap[(df.run_experiment.iloc[0], s)] for s in seeds])
                b = np.array([qbase[s] for s in seeds])
            else:
                a = df.groupby("run_seed")[col].mean().reindex(seeds).values
                b = base.groupby("run_seed")[col].mean().reindex(seeds).values
            res[(key, col)] = pct_ci(a, b, n)

    ypos, headers, y = {}, [], 0.0
    for kind, label, col in rows:
        if kind == "header":
            headers.append((y, label))
            y += 1.0
        else:
            ypos[col] = y
            y += 1.0
    ymax = y

    fig, axes = plt.subplots(1, 3,
                             figsize=(10.2, 6.4) if not paper else (7.4, 5.3),
                             sharey=True, gridspec_kw=dict(wspace=0.06))
    for ax, (key, title, batch, df) in zip(axes, arms):
        for kind, label, col in rows:
            if kind == "header":
                continue
            m, h = res[(key, col)]
            ax.errorbar(m, ypos[col], xerr=h, fmt="o", color=COL[key],
                        ecolor=COL[key], elinewidth=1.5, capsize=0,
                        markersize=5.5 if paper else 6.5, zorder=3)
            ax.text(53.0, ypos[col], "%+.1f%%" % m, color=COL[key],
                    fontsize=base_font, ha="right", va="center",
                    fontweight="bold")
        ax.axvline(0, color="black", linewidth=0.9, zorder=2)
        ax.set_xlim(-45, 56)
        ax.set_ylim(ymax + 0.3, -1.5)
        ax.set_xticks([-40, -20, 0, 20, 40])
        ax.set_xlabel("change vs fixed-time (%)")
        ax.set_title(title, pad=5, color=COL[key], fontweight="bold")
        ax.grid(axis="x", color="0.9", linewidth=0.6, zorder=0)
        ax.set_axisbelow(True)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
        ax.tick_params(axis="y", length=0, left=False)

    ax0 = axes[0]
    labels = [""] * int(ymax)
    for col, yy in ypos.items():
        labels[int(yy)] = next(l for k, l, c in METRICS if c == col)
    ax0.set_yticks(range(len(labels)))
    ax0.set_yticklabels(labels)
    for yy, text in headers:
        ax0.text(-0.42, yy, text, transform=ax0.get_yaxis_transform(),
                 ha="left", va="center", fontsize=base_font + 2,
                 fontweight="bold")

    d1 = res[("M1", "stats_TotalPassDelay_hrs")][0]
    d4 = res[("M4", "stats_TotalPassDelay_hrs")][0]
    head = ("Person delay: %+.1f%% under the adaptive base, %+.1f%% under "
            "the bus-first game" % (d1, d4))
    fig.suptitle(head, x=0.012, ha="left",
                 fontsize=base_font + 4, fontweight="bold", y=1.015)

    fig.canvas.draw()
    fig.text(0.5, -0.015,
             "%d seeds per rung; dot = mean paired change against fixed-time on the "
             "same seeds, whisker = 95%% t-interval. Positive = worse for "
             "delay/queue/time, better for speed/passages." % n,
             ha="center", fontsize=base_font - 0.5, color="0.35")

    stem = ("kg" if corridor == "kg" else "logan") + (
        "_kpi_delta_paper" if paper else "_kpi_delta")
    fig.savefig(os.path.join(FIG, stem + ".pdf"))
    fig.savefig(os.path.join(FIG, stem + ".png"), dpi=300)
    fig.savefig(os.path.join(TMP, stem + ".png"), dpi=300)
    print("wrote", stem + ".pdf")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "kg",
         paper=(len(sys.argv) > 2 and sys.argv[2] == "paper"))
