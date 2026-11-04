"""analyze_dsw_vs_notsp.py -- NO_TSP vs CHAMP_ADAPTIVE_AIMSUN_DSW analysis.

Reads the 5-seed batch:
  paxwin_adaptive_dsw_5seeds.csv
plus every result folder it points at:
  <stats_results_folder>/simulation_results_per_intersection.csv  (12 junctions)
  <stats_results_folder>/section_stats.csv                        (main vs side)

Produces:
  dsw_vs_notsp_summary.csv      long-format metric summary (per-seed + mean)
  dsw_vs_notsp_junctions.csv    per-junction speed/queue/density/delay
  dsw_vs_notsp_main_side.csv    main-vs-side section speed/queue/density
  dsw_vs_notsp_report.md        readable report
  dsw_vs_notsp_delay.png        person-delay by mode / main-vs-side

Metric directions (AGENTS.md RULE 3):
  objective_pax_per_delay_hr  higher=better
  all delay / queue / density lower=better
  speed                       higher=better
"""
import os
import numpy as np
import pandas as pd
from scipy import stats as st

HERE = os.path.dirname(os.path.abspath(__file__))
BATCH = os.path.join(HERE, "paxwin_adaptive_dsw_5seeds.csv")
BASE = "NO_TSP"
ARM = "CHAMP_ADAPTIVE_AIMSUN_DSW"

df = pd.read_csv(BATCH, encoding="utf-8-sig", engine="python")
df = df[df["run_success"].astype(str).str.upper() == "TRUE"].copy()
df["run_seed"] = df["run_seed"].astype(int)

# ── derived network/person-delay metrics ───────────────────────────────────
df["total_pax_delay_h"] = df["stats_Obj_Z1_delay_paxs"] / 3600.0
df["bus_pax_delay_h"] = df["stats_SimBusDelay_pax_s"] / 3600.0
df["car_pax_delay_h"] = df["stats_SimCarDelay_pax_s"] / 3600.0
df["truck_pax_delay_h"] = df["stats_SimTruckDelay_pax_s"] / 3600.0

# metric -> (column, higher_is_better, group)
NET_METRICS = [
    ("total person-delay (pax-h)", "total_pax_delay_h", False, "Person delay"),
    ("  bus passengers (pax-h)", "bus_pax_delay_h", False, "Person delay"),
    ("  car passengers (pax-h)", "car_pax_delay_h", False, "Person delay"),
    ("  truck occupants (pax-h)", "truck_pax_delay_h", False, "Person delay"),
    ("bus pax delay per pax (s)", "stats_AvgBusPassDelay_s", False, "Person delay"),
    ("car pax delay per pax (s)", "stats_AvgCarPassDelay_s", False, "Person delay"),
    ("objective (pax/delay-h)", "stats_Objective_PaxPerDelayHr", True, "Person delay"),
    ("bus pax passages", "stats_BusPaxEquivPassages", True, "Person delay"),
    ("car pax passages", "stats_CarPaxEquivPassages", True, "Person delay"),
    ("total pass delay (h)", "stats_TotalPassDelay_hrs", False, "Main vs side"),
    ("main pass delay (h)", "stats_MainPassDelay_hrs", False, "Main vs side"),
    ("side pass delay (h)", "stats_SidePassDelay_hrs", False, "Main vs side"),
    ("corridor pass delay (h)", "stats_CorridorPassDelay_hrs", False, "Main vs side"),
    ("avg speed all sections (km/h)", "stats_Net_AvgSpeed_kmh", True, "Speed"),
    ("avg entry TT (s)", "stats_Net_EntryTT_All", False, "Speed"),
    ("avg exit TT (s)", "stats_Net_ExitTT_All", False, "Speed"),
    ("mean queue all (veh)", "stats_Net_MeanQueue_All", False, "Queue"),
    ("max queue all (veh)", "stats_Net_MaxQueue_All", False, "Queue"),
    ("VQ avg (veh)", "stats_Net_VQAvg_All", False, "Queue"),
    ("VQ wait (s)", "stats_Net_WaitVQ_All", False, "Queue"),
    ("section mean queue (veh)", "section_avg_queue_veh", False, "Queue"),
    ("avg density (veh/km)", "stats_Net_Density_All", False, "Density"),
    ("avg density vkm", "stats_Net_AvgDensity_vkm", False, "Density"),
]


def _paired(metric_col):
    a = df[df.run_experiment == BASE].set_index("run_seed")[metric_col]
    b = df[df.run_experiment == ARM].set_index("run_seed")[metric_col]
    seeds = sorted(set(a.index) & set(b.index))
    a, b = a.loc[seeds].astype(float), b.loc[seeds].astype(float)
    return seeds, a, b


def _pct(a, b):
    return 100.0 * (b - a) / a if a not in (0, 0.0) and np.isfinite(a) else np.nan


rows, lines = [], []
lines.append("# NO_TSP vs CHAMP_ADAPTIVE_AIMSUN_DSW — 5-seed comparison\n")
seeds = sorted(int(s) for s in df.run_seed.unique())
lines.append(f"Seeds: {seeds} (n={len(seeds)}, all runs succeeded)\n")

lines.append("\n## 1. Person delay, by mode (same-seed paired)\n")
lines.append("| metric | NO_TSP mean | DSW mean | Δ | Δ% | better? | seeds better | paired p |")
lines.append("|---|---:|---:|---:|---:|:--:|:--:|---:|")
summary_rows = []
for label, col, higher, group in NET_METRICS:
    if col not in df.columns:
        continue
    s, a, b = _paired(col)
    ma, mb = a.mean(), b.mean()
    d = mb - ma
    pc = _pct(ma, mb)
    if len(s) > 1 and a.std(ddof=1) > 0:
        t, p = st.ttest_rel(b.values, a.values)
    else:
        p = np.nan
    better = (d > 0) == higher if np.isfinite(d) else None
    tag = "yes" if better else "no"
    n_better = int(np.sum((b.values > a.values) if higher else (b.values < a.values)))
    lines.append(f"| {label} | {ma:,.2f} | {mb:,.2f} | {d:+,.2f} | {pc:+.1f}% | {tag} | "
                 f"{n_better}/{len(s)} | {p:.3f} |")
    for seed in s:
        summary_rows.append(dict(group=group, metric=label, seed=seed,
                                 base=a.loc[seed], dsw=b.loc[seed],
                                 delta=b.loc[seed] - a.loc[seed],
                                 pct=_pct(a.loc[seed], b.loc[seed])))
    summary_rows.append(dict(group=group, metric=label, seed="mean",
                             base=ma, dsw=mb, delta=d, pct=pc))

pd.DataFrame(summary_rows).to_csv(
    os.path.join(HERE, "dsw_vs_notsp_summary.csv"), index=False)

# ── per-junction metrics from each run folder ───────────────────────────────
jrows = []
for _, r in df.iterrows():
    folder = str(r["stats_results_folder"])
    p = os.path.join(folder, "simulation_results_per_intersection.csv")
    if not os.path.isfile(p):
        continue
    j = pd.read_csv(p, encoding="utf-8-sig", engine="python")
    for _, x in j.iterrows():
        jrows.append(dict(
            arm=r["run_experiment"], seed=int(r["run_seed"]),
            junction=str(x["IntersectionID"]),
            speed=float(x["AvgSpeed_kmh"]), queue=float(x["AvgQueue_veh"]),
            density=float(x["AvgDensity_vkm"]),
            total_delay_h=float(x["TotalPassDelay_hrs"]),
            main_delay_h=float(x["MainPassDelay_hrs"]),
            side_delay_h=float(x["SidePassDelay_hrs"]),
            avg_pass_delay_s=float(x["AvgPassDelay_s"]),
            objective=float(x["Objective_PaxPerDelayHr"])))
J = pd.DataFrame(jrows)

lines.append("\n## 2. Per-junction comparison (mean over seeds)\n")
if not J.empty:
    jm = (J.groupby(["arm", "junction"])
            .agg(speed=("speed", "mean"), queue=("queue", "mean"),
                 density=("density", "mean"),
                 total_delay_h=("total_delay_h", "mean"),
                 main_delay_h=("main_delay_h", "mean"),
                 side_delay_h=("side_delay_h", "mean"),
                 avg_pass_delay_s=("avg_pass_delay_s", "mean"),
                 objective=("objective", "mean"))
            .reset_index())
    wide = []
    for jn, g in jm.groupby("junction"):
        g = g.set_index("arm")
        if BASE not in g.index or ARM not in g.index:
            continue
        a, b = g.loc[BASE], g.loc[ARM]
        rec = dict(junction=jn)
        for k in ("speed", "queue", "density", "total_delay_h",
                  "main_delay_h", "side_delay_h", "avg_pass_delay_s", "objective"):
            rec[f"{k}_base"] = a[k]
            rec[f"{k}_dsw"] = b[k]
            rec[f"{k}_pct"] = _pct(a[k], b[k])
        wide.append(rec)
    W = pd.DataFrame(wide)
    W.to_csv(os.path.join(HERE, "dsw_vs_notsp_junctions.csv"), index=False)

    lines.append("### 2a. Speed at each junction (km/h)\n")
    lines.append("| junction | NO_TSP | DSW | Δ% |")
    lines.append("|---|---:|---:|---:|")
    for _, w in W.sort_values("junction", key=lambda s: s.astype(str)).iterrows():
        lines.append(f"| {w.junction} | {w.speed_base:.2f} | {w.speed_dsw:.2f} | "
                     f"{w.speed_pct:+.1f}% |")
    lines.append(f"\nFleet mean speed: NO_TSP {W.speed_base.mean():.2f} vs "
                 f"DSW {W.speed_dsw.mean():.2f} km/h "
                 f"({_pct(W.speed_base.mean(), W.speed_dsw.mean()):+.1f}%)\n")

    lines.append("### 2b. Queue at each junction (veh)\n")
    lines.append("| junction | NO_TSP | DSW | Δ% |")
    lines.append("|---|---:|---:|---:|")
    for _, w in W.sort_values("junction", key=lambda s: s.astype(str)).iterrows():
        lines.append(f"| {w.junction} | {w.queue_base:.2f} | {w.queue_dsw:.2f} | "
                     f"{w.queue_pct:+.1f}% |")
    lines.append(f"\nMean junction queue: NO_TSP {W.queue_base.mean():.2f} vs "
                 f"DSW {W.queue_dsw.mean():.2f} veh "
                 f"({_pct(W.queue_base.mean(), W.queue_dsw.mean()):+.1f}%)\n")

    lines.append("### 2c. Density at each junction (veh/km)\n")
    lines.append("| junction | NO_TSP | DSW | Δ% |")
    lines.append("|---|---:|---:|---:|")
    for _, w in W.sort_values("junction", key=lambda s: s.astype(str)).iterrows():
        lines.append(f"| {w.junction} | {w.density_base:.2f} | {w.density_dsw:.2f} | "
                     f"{w.density_pct:+.1f}% |")
    lines.append(f"\nMean junction density: NO_TSP {W.density_base.mean():.2f} vs "
                 f"DSW {W.density_dsw.mean():.2f} veh/km "
                 f"({_pct(W.density_base.mean(), W.density_dsw.mean()):+.1f}%)\n")

    lines.append("### 2d. Main vs side delay at each junction (h)\n")
    lines.append("| junction | main NO_TSP | main DSW | main Δ% | side NO_TSP | side DSW | side Δ% |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for _, w in W.sort_values("junction", key=lambda s: s.astype(str)).iterrows():
        lines.append(f"| {w.junction} | {w.main_delay_h_base:.2f} | {w.main_delay_h_dsw:.2f} | "
                     f"{w.main_delay_h_pct:+.1f}% | {w.side_delay_h_base:.2f} | "
                     f"{w.side_delay_h_dsw:.2f} | {w.side_delay_h_pct:+.1f}% |")

# ── main-vs-side section speed/queue/density ────────────────────────────────
srows = []
for _, r in df.iterrows():
    folder = str(r["stats_results_folder"])
    p = os.path.join(folder, "section_stats.csv")
    if not os.path.isfile(p):
        continue
    s = pd.read_csv(p, encoding="utf-8-sig", engine="python")
    for is_main, g in s.groupby("IsMain"):
        srows.append(dict(arm=r["run_experiment"], seed=int(r["run_seed"]),
                          part="main" if int(is_main) == 1 else "side",
                          n_sections=len(g),
                          speed=float(g["AvgSpeed_kmh"].mean()),
                          queue=float(g["AvgQueue_veh"].mean()),
                          density=float(g["AvgDensity_vkm"].mean()),
                          flow=float(g["AvgFlow_veh_h"].mean())))
S = pd.DataFrame(srows)
lines.append("\n## 3. Main vs side *section* speed / queue / density\n")
if not S.empty:
    sm = S.groupby(["part", "arm"]).agg(
        n_sections=("n_sections", "mean"), speed=("speed", "mean"),
        queue=("queue", "mean"), density=("density", "mean"),
        flow=("flow", "mean")).reset_index()
    sm.to_csv(os.path.join(HERE, "dsw_vs_notsp_main_side.csv"), index=False)
    for part in ("main", "side"):
        g = sm[sm.part == part].set_index("arm")
        if BASE in g.index and ARM in g.index:
            a, b = g.loc[BASE], g.loc[ARM]
            lines.append(f"\n**{part.upper()} sections** "
                         f"({a.n_sections:.0f} sections)\n")
            lines.append("| metric | NO_TSP | DSW | Δ% |")
            lines.append("|---|---:|---:|---:|")
            for k, lab in (("speed", "speed (km/h)"), ("queue", "queue (veh)"),
                           ("density", "density (veh/km)"), ("flow", "flow (veh/h)")):
                lines.append(f"| {lab} | {a[k]:.2f} | {b[k]:.2f} | {_pct(a[k], b[k]):+.1f}% |")

_txt = "\n".join(lines).replace("NO_TSP", "Fixed Time").replace("DSW", "Adaptive")
_txt = _txt.replace("CHAMP_ADAPTIVE_AIMSUN_Adaptive", "Adaptive System with TSP")
with open(os.path.join(HERE, "dsw_vs_notsp_report.md"), "w", encoding="utf-8") as fh:
    fh.write(_txt + "\n")

# ── figure: person delay by mode + main/side ────────────────────────────────
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    modes = [("bus_pax_delay_h", "bus pax"), ("car_pax_delay_h", "car pax"),
             ("truck_pax_delay_h", "truck")]
    x = np.arange(len(modes))
    w = 0.38
    av = [df[df.run_experiment == BASE][c].mean() for c, _ in modes]
    bv = [df[df.run_experiment == ARM][c].mean() for c, _ in modes]
    axes[0].bar(x - w / 2, av, w, label="Fixed Time", color="#9aa4ad")
    axes[0].bar(x + w / 2, bv, w, label="Adaptive System with TSP", color="#1e88e5")
    axes[0].set_xticks(x); axes[0].set_xticklabels([n for _, n in modes])
    axes[0].set_ylabel("person-delay (pax-hours)")
    axes[0].set_title("Person delay by mode")
    axes[0].legend(fontsize=8); axes[0].grid(axis="y", alpha=0.3)

    parts = [("stats_MainPassDelay_hrs", "main"), ("stats_SidePassDelay_hrs", "side")]
    x = np.arange(len(parts))
    av = [df[df.run_experiment == BASE][c].mean() for c, _ in parts]
    bv = [df[df.run_experiment == ARM][c].mean() for c, _ in parts]
    axes[1].bar(x - w / 2, av, w, label="Fixed Time", color="#9aa4ad")
    axes[1].bar(x + w / 2, bv, w, label="Adaptive System with TSP", color="#1e88e5")
    axes[1].set_xticks(x); axes[1].set_xticklabels([n for _, n in parts])
    axes[1].set_ylabel("passenger-delay (h)")
    axes[1].set_title("Main vs side delay")
    axes[1].legend(fontsize=8); axes[1].grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "dsw_vs_notsp_delay.png"), dpi=150)
    print("wrote dsw_vs_notsp_delay.png")
except Exception as e:
    print("figure skipped:", repr(e))

print("\n".join(lines))
