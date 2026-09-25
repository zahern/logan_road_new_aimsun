"""
generate_paper_plots.py
Generates seed-averaged paper plots + LaTeX table from batch_results.csv.

Run: python3.12 generate_paper_plots.py [batch_results.csv]

Outputs to TSP_Paper/plots/:
  fig_total_delay.pdf       — total pax delay bar (main KPI)
  fig_main_side.pdf         — main vs side corridor delay split
  fig_bus_car_tt.pdf        — bus TT + car TT grouped bar
  fig_vkt.pdf               — total vehicle-km throughput
  fig_objectives.pdf        — Z2 bandwidth / Z3 lateness / Z5 bandwidth-flow
  fig_bus_improvement.pdf   — bus delay % improvement
  fig_bus_vs_car.pdf        — bus vs car delay scatter (pareto)
  fig_lateness.pdf          — NO_TSP bus lateness distribution

  paper_kpi_table.tex       — LaTeX booktabs table of all KPIs
  paper_kpi_table.csv       — CSV version of the same table
"""

import os, csv, math, glob, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BATCH_CSV  = sys.argv[1] if len(sys.argv) > 1 else os.path.join(SCRIPT_DIR, "batch_results.csv")
PLOTS_DIR  = os.path.join(SCRIPT_DIR, "..", "TSP_Paper", "plots")
os.makedirs(PLOTS_DIR, exist_ok=True)

# ── Display order and labels ───────────────────────────────────────────────────
STRATEGY_ORDER = [
    "NO_TSP",
    "DCTSP_ZIG",
    "PRED_BARGAIN_KALMAN",
    "PRED_BARGAIN_ADAPTIVE_KALMAN",
    "PRED_BARGAIN_LSTM_SS",
    "PRED_ADAPTIVE_KALMAN_WaveGate",
    "PRED_ADAPTIVE_KALMAN_NashGate",
    "PRED_ADAPTIVE_KALMAN_MambaATSP",
    "PRED_LSTM_SS_WaveGate",
    "PRED_LSTM_SS_NashGate",
    "PRED_LSTM_SS_MambaATSP",
]
STRATEGY_LABELS = {
    "NO_TSP":                        "NoPriority",
    "DCTSP_ZIG":                     "WaveGate (Kalman)",
    "PRED_BARGAIN_KALMAN":           "BARGAIN / Kalman",
    "PRED_BARGAIN_ADAPTIVE_KALMAN":  "BARGAIN / Adapt-K",
    "PRED_BARGAIN_LSTM_SS":          "BARGAIN / LSTM-SS",
    "PRED_ADAPTIVE_KALMAN_WaveGate": "WaveGate / Adapt-K",
    "PRED_ADAPTIVE_KALMAN_NashGate": "NashGate / Adapt-K",
    "PRED_ADAPTIVE_KALMAN_MambaATSP":"MambaATSP / Adapt-K",
    "PRED_LSTM_SS_WaveGate":         "WaveGate / LSTM-SS",
    "PRED_LSTM_SS_NashGate":         "NashGate / LSTM-SS",
    "PRED_LSTM_SS_MambaATSP":        "MambaATSP / LSTM-SS",
}
STRATEGY_COLOURS = {
    "NO_TSP":                        "#FF9800",
    "DCTSP_ZIG":                     "#00BCD4",
    "PRED_BARGAIN_KALMAN":           "#4CAF50",
    "PRED_BARGAIN_ADAPTIVE_KALMAN":  "#2196F3",
    "PRED_BARGAIN_LSTM_SS":          "#9C27B0",
    "PRED_ADAPTIVE_KALMAN_WaveGate": "#E91E63",
    "PRED_ADAPTIVE_KALMAN_NashGate": "#F44336",
    "PRED_ADAPTIVE_KALMAN_MambaATSP":"#FF5722",
    "PRED_LSTM_SS_WaveGate":         "#009688",
    "PRED_LSTM_SS_NashGate":         "#795548",
    "PRED_LSTM_SS_MambaATSP":        "#607D8B",
}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9,
    "axes.titlesize": 11, "axes.labelsize": 9,
    "xtick.labelsize": 8, "ytick.labelsize": 8,
    "figure.dpi": 150, "savefig.dpi": 300,
    "axes.spines.top": False, "axes.spines.right": False,
    "legend.fontsize": 8,
})

# ── Helpers ────────────────────────────────────────────────────────────────────
def _flt(v):
    try: return float(v) if v not in (None, "", "None") else None
    except Exception: return None

def safe_mean(vals):
    v = [x for x in vals if x is not None and math.isfinite(x)]
    return sum(v)/len(v) if v else None

def safe_std(vals):
    v = [x for x in vals if x is not None and math.isfinite(x)]
    if len(v) < 2: return 0.0
    m = sum(v)/len(v)
    return math.sqrt(sum((x-m)**2 for x in v)/(len(v)-1))

def ci95(vals):
    n = len([x for x in vals if x is not None and math.isfinite(x)])
    return 1.96 * safe_std(vals) / math.sqrt(n) if n > 1 else 0.0

# ── Load & average ─────────────────────────────────────────────────────────────
with open(BATCH_CSV, newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

# Deduplicate on (experiment, seed) — keep last
seen = {}
for r in rows:
    seen[(r.get("run_experiment",""), r.get("run_seed",""))] = r

groups = defaultdict(list)
for (exp, _), r in seen.items():
    groups[exp].append(r)

def avg(exp, col):
    return safe_mean([_flt(r.get(col)) for r in groups[exp]])
def err(exp, col):
    return ci95([_flt(r.get(col)) for r in groups[exp]])

# Compute Z5 (bandwidth flow) = dets * (rate*12 + (1-rate)*3) — same as gen_obj_dashboard
def z5(exp):
    dets_v = [_flt(r.get("stats_TSP_Detections")) for r in groups[exp]]
    natg_v = [_flt(r.get("stats_TSP_NaturalGreen")) for r in groups[exp]]
    vals = []
    for d, ng in zip(dets_v, natg_v):
        if d and d > 0:
            rate = (ng or 0) / d
            vals.append(d * (rate*12.0 + (1-rate)*3.0))
    return safe_mean(vals), ci95(vals) if len(vals) > 1 else 0.0

# Z2 fallback: use wobj_Z2_total if present, else z5 formula
def z2(exp):
    raw = [_flt(r.get("wobj_Z2_total")) for r in groups[exp]]
    raw_ok = [v for v in raw if v is not None and v > 0]
    if raw_ok:
        return safe_mean(raw_ok), ci95(raw_ok)
    # fallback: z5 bandwidth estimate
    dets_v = [_flt(r.get("stats_TSP_Detections")) for r in groups[exp]]
    natg_v = [_flt(r.get("stats_TSP_NaturalGreen")) for r in groups[exp]]
    vals = []
    for d, ng in zip(dets_v, natg_v):
        if d and d > 0:
            rate = (ng or 0) / d
            vals.append(d * (rate*12.0 + (1-rate)*3.0))
    return (safe_mean(vals), ci95(vals)) if vals else (None, 0.0)

n_seeds = max(len(v) for v in groups.values())
print(f"Loaded {len(seen)} rows -> {len(groups)} experiments, up to {n_seeds} seeds each")

# Ordered experiment list (keep only those present in the data)
ordered = [e for e in STRATEGY_ORDER if e in groups]
# Add any extras not in the predefined order
ordered += [e for e in sorted(groups) if e not in ordered]

labels  = [STRATEGY_LABELS.get(e, e) for e in ordered]
colors  = [STRATEGY_COLOURS.get(e, "#9E9E9E") for e in ordered]

# Base values
base = "NO_TSP"
b_del  = avg(base, "stats_TotalPassDelay_hrs") or 1.0
b_main = avg(base, "stats_MainPassDelay_hrs")  or 1.0
b_side = avg(base, "stats_SidePassDelay_hrs")  or 1.0
b_bus  = avg(base, "stats_AvgBusPassDelay_s")  or 1.0
b_car  = avg(base, "stats_AvgCarPassDelay_s")  or 1.0
b_btt  = avg(base, "stats_BusTotalTT_hrs")     or 1.0
b_ctt  = avg(base, "stats_Net_TotalTT_h_Car")  or 1.0
b_vkt  = avg(base, "aimsun_total_veh_km_h")    or 1.0

subtitle = f"Mean ± 95% CI across {n_seeds} seed(s)"

def hbar(ax, vals, cis, ylabel, title, baseline=None, pct_label=False, base_val=1.0):
    """Horizontal bar chart helper."""
    y = np.arange(len(vals))
    ax.barh(y, vals, color=colors, height=0.6)
    ax.errorbar(vals, y, xerr=cis, fmt="none", color="gray", capsize=3, lw=1.0)
    if baseline is not None:
        ax.axvline(baseline, color="#FF9800", lw=1.2, ls="--", alpha=0.7, label="NoPriority")
    for i, (v, ci) in enumerate(zip(vals, cis)):
        if v is None: continue
        if pct_label and base_val:
            pct = 100*(v - base_val)/base_val
            ax.text(v + ci + abs(max(vals, default=1))*0.01, i,
                    f"{v:.2f}  ({pct:+.1f}%)", va="center", fontsize=7)
        else:
            ax.text(v + ci + abs(max(vals, default=1))*0.01, i,
                    f"{v:.2f}", va="center", fontsize=7)
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel(ylabel); ax.set_title(title, pad=4)
    if baseline is not None:
        ax.legend(loc="lower right", fontsize=7)

# ── Figure 1: Total, Main, Side pax delay ─────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=True)
for ax, col, base_v, title in [
    (axes[0], "stats_TotalPassDelay_hrs", b_del, "Total Pax Delay (hrs)"),
    (axes[1], "stats_MainPassDelay_hrs",  b_main, "Main Corridor Delay (hrs)"),
    (axes[2], "stats_SidePassDelay_hrs",  b_side, "Side Street Delay (hrs)"),
]:
    vals = [avg(e, col) or 0 for e in ordered]
    cis  = [err(e, col)      for e in ordered]
    hbar(ax, vals, cis, "hrs", title, baseline=base_v, pct_label=True, base_val=base_v)
axes[0].set_ylabel("")
fig.suptitle(f"Passenger Delay by Strategy — {subtitle}", fontsize=11)
fig.tight_layout()
fig.savefig(os.path.join(PLOTS_DIR, "fig_main_side.png"), dpi=300)
plt.close(fig)
print("Saved: fig_main_side.pdf")

# ── Figure 2: Bus TT + Car TT ─────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
for ax, col, base_v, title, unit in [
    (axes[0], "stats_BusTotalTT_hrs",   b_btt, "Bus Total Travel Time (hrs)",  "hrs"),
    (axes[1], "stats_Net_TotalTT_h_Car",b_ctt, "Car Total Travel Time (hrs)",  "hrs"),
]:
    vals = [avg(e, col) or 0 for e in ordered]
    cis  = [err(e, col)      for e in ordered]
    hbar(ax, vals, cis, unit, title, baseline=base_v, pct_label=True, base_val=base_v)
fig.suptitle(f"Vehicle Travel Time by Strategy — {subtitle}", fontsize=11)
fig.tight_layout()
fig.savefig(os.path.join(PLOTS_DIR, "fig_bus_car_tt.png"), dpi=300)
plt.close(fig)
print("Saved: fig_bus_car_tt.pdf")

# ── Figure 3: Total VKT (vehicle-km throughput) ────────────────────────────────
fig, ax = plt.subplots(figsize=(8, 5))
vals = [avg(e, "aimsun_total_veh_km_h") or 0 for e in ordered]
cis  = [err(e, "aimsun_total_veh_km_h")      for e in ordered]
hbar(ax, vals, cis, "veh-km / h", "Total Corridor VKT (higher = better throughput)",
     baseline=b_vkt, pct_label=True, base_val=b_vkt)
ax.set_title(f"Total Vehicle-km Throughput — {subtitle}")
fig.tight_layout()
fig.savefig(os.path.join(PLOTS_DIR, "fig_vkt.png"), dpi=300)
plt.close(fig)
print("Saved: fig_vkt.pdf")

# ── Figure 4: Z2 / Z3 / Z5 objectives ────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=True)

# Z2: flow-weighted bandwidth (higher = better)
z2_vals = [z2(e)[0] or 0 for e in ordered]
z2_cis  = [z2(e)[1]      for e in ordered]
y = np.arange(len(ordered))
axes[0].barh(y, z2_vals, color=colors, height=0.6)
axes[0].errorbar(z2_vals, y, xerr=z2_cis, fmt="none", color="gray", capsize=3, lw=1)
axes[0].set_yticks(y); axes[0].set_yticklabels(labels, fontsize=8)
axes[0].set_xlabel("s"); axes[0].set_title("Z2: Flow-Weighted Bandwidth (higher=better)")
for i, v in enumerate(z2_vals):
    axes[0].text(v + max(z2_vals, default=1)*0.01, i, f"{v:.0f}", va="center", fontsize=7)

# Z3: bus lateness (lower = better)
z3_vals = [avg(e, "wobj_Z3_total") or 0 for e in ordered]
z3_cis  = [err(e, "wobj_Z3_total")      for e in ordered]
axes[1].barh(y, z3_vals, color=colors, height=0.6)
axes[1].errorbar(z3_vals, y, xerr=z3_cis, fmt="none", color="gray", capsize=3, lw=1)
axes[1].set_yticks(y); axes[1].set_yticklabels([], fontsize=8)
axes[1].set_xlabel("pax-s"); axes[1].set_title("Z3: Bus Lateness (lower=better)")
for i, v in enumerate(z3_vals):
    axes[1].text(v + max(z3_vals, default=1)*0.01, i, f"{v/1000:.1f}k", va="center", fontsize=7)

# Z5: natural-green bandwidth flow (higher = better, same formula as Z2 estimate)
z5_vals = [z5(e)[0] or 0 for e in ordered]
z5_cis  = [z5(e)[1]      for e in ordered]
axes[2].barh(y, z5_vals, color=colors, height=0.6)
axes[2].errorbar(z5_vals, y, xerr=z5_cis, fmt="none", color="gray", capsize=3, lw=1)
axes[2].set_yticks(y); axes[2].set_yticklabels([], fontsize=8)
axes[2].set_xlabel("s"); axes[2].set_title("Z5: Natural-Green Bandwidth Flow (higher=better)")
for i, v in enumerate(z5_vals):
    axes[2].text(v + max(z5_vals, default=1)*0.01, i, f"{v:.0f}", va="center", fontsize=7)

fig.suptitle(f"MILP Objectives — {subtitle}", fontsize=11)
fig.tight_layout()
fig.savefig(os.path.join(PLOTS_DIR, "fig_objectives.png"), dpi=300)
plt.close(fig)
print("Saved: fig_objectives.pdf")

# ── Figure 5: Bus delay % improvement (horizontal) ────────────────────────────
fig, ax = plt.subplots(figsize=(8, 5))
bus_vals = [avg(e, "stats_AvgBusPassDelay_s") or 0 for e in ordered]
bus_cis  = [err(e, "stats_AvgBusPassDelay_s")      for e in ordered]
improv   = [100*(b_bus - v)/b_bus for v in bus_vals]
imp_cis  = [100*ci/b_bus for ci in bus_cis]
y = np.arange(len(ordered))
ax.barh(y, improv, color=colors, height=0.6)
ax.errorbar(improv, y, xerr=imp_cis, fmt="none", color="gray", capsize=3, lw=1)
ax.axvline(0, color="gray", lw=0.8, ls="--")
for i, (v, ci, bv) in enumerate(zip(improv, imp_cis, bus_vals)):
    ax.text(v + ci + 0.3, i, f"{v:+.1f}%  ({bv:.1f}s)", va="center", fontsize=7.5)
ax.set_yticks(y); ax.set_yticklabels(labels)
ax.set_xlabel("Bus Delay Change vs NoPriority (%)")
ax.set_title(f"Bus Delay Reduction per Strategy\n{subtitle} | Baseline: {b_bus:.1f} s/pax")
fig.tight_layout()
fig.savefig(os.path.join(PLOTS_DIR, "fig_bus_improvement.png"), dpi=300)
plt.close(fig)
print("Saved: fig_bus_improvement.pdf")

# ── Figure 6: Total delay ranked bar ──────────────────────────────────────────
fig, ax = plt.subplots(figsize=(8, 5))
td_vals = [avg(e, "stats_TotalPassDelay_hrs") or 0 for e in ordered]
td_cis  = [err(e, "stats_TotalPassDelay_hrs")      for e in ordered]
hbar(ax, td_vals, td_cis, "Total Pax Delay (hrs)", "Total Passenger Delay by Strategy",
     baseline=b_del, pct_label=True, base_val=b_del)
ax.set_title(f"Total Passenger Delay — {subtitle}")
fig.tight_layout()
fig.savefig(os.path.join(PLOTS_DIR, "fig_total_delay.png"), dpi=300)
plt.close(fig)
print("Saved: fig_total_delay.pdf")

# ── Figure 7: Bus vs Car scatter ───────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(9, 6))
ax.axhline(b_car, color="#D2691E", lw=0.8, ls="--", alpha=0.6)
ax.axvline(b_bus, color="#4682B4", lw=0.8, ls="--", alpha=0.6)
ax.fill_between([0, b_bus], [0, 0], [b_car, b_car], alpha=0.06, color="#3CB371")
ax.text(b_bus*0.5, b_car*0.94, "Both better", color="#3CB371", fontsize=8)
for e, lbl in zip(ordered, labels):
    bv = avg(e, "stats_AvgBusPassDelay_s")
    cv = avg(e, "stats_AvgCarPassDelay_s")
    if bv is None or cv is None: continue
    det = avg(e, "stats_TSP_Detections") or 1
    ext = avg(e, "stats_TSP_Extensions") or 0
    ins = avg(e, "stats_TSP_Insertions") or 0
    gr  = (ext + ins) / det
    col = STRATEGY_COLOURS.get(e, "#9E9E9E")
    be  = err(e, "stats_AvgBusPassDelay_s")
    ce  = err(e, "stats_AvgCarPassDelay_s")
    ax.errorbar(bv, cv, xerr=be, yerr=ce, fmt="none", color=col, alpha=0.45, capsize=2.5)
    ax.scatter(bv, cv, s=max(40, gr*500), color=col, alpha=0.85,
               edgecolors="white", lw=0.5, zorder=3)
    ax.annotate(lbl, (bv, cv), xytext=(5, 4), textcoords="offset points",
                fontsize=7, color=col)
ax.set_xlabel("Avg Bus Delay (s/pax)"); ax.set_ylabel("Avg Car Delay (s/pax)")
ax.set_title(f"Bus vs Car Delay Tradeoff\n{subtitle} | point size = grant rate")
fig.tight_layout()
fig.savefig(os.path.join(PLOTS_DIR, "fig_bus_vs_car.png"), dpi=300)
plt.close(fig)
print("Saved: fig_bus_vs_car.pdf")

# ── Figure 8: Bus lateness distribution (NO_TSP, all seeds combined) ──────────
bus_csv_glob = glob.glob(os.path.join(SCRIPT_DIR, "results", "NO_TSP*", "bus_trips.csv"))
if bus_csv_glob:
    all_tt = []
    for fp in bus_csv_glob:
        try:
            with open(fp, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    v = _flt(r.get("TravelTime_s"))
                    if v and v > 0: all_tt.append(v)
        except Exception: pass
    if all_tt:
        sched_tt = np.percentile(all_tt, 10)
        lat = np.array(all_tt) - sched_tt
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
        ax1.hist(lat, bins=60, color="#4682B4", alpha=0.85, edgecolor="white", lw=0.2)
        for thr, col in [(30, "#D2691E"), (60, "#CD5C5C")]:
            ax1.axvline(thr, ls="--", color=col, lw=1.2)
            ax1.text(thr+2, ax1.get_ylim()[1]*0.88, f"{thr}s", color=col, fontsize=8)
        ax1.set_xlabel("Delay vs Scheduled TT (s)"); ax1.set_ylabel("Bus Trips")
        ax1.set_title(f"NO_TSP Bus Delay | {len(bus_csv_glob)} seed(s) | "
                      f"Mean: {np.mean(all_tt):.1f}s")
        thrs = [10, 20, 30, 50, 60, 90, 120]
        pcts = [100*np.mean(lat > t) for t in thrs]
        ax2.bar([str(t) for t in thrs], pcts, color="#CD5C5C", width=0.6)
        for i, p in enumerate(pcts):
            ax2.text(i, p+0.5, f"{p:.0f}%", ha="center", fontsize=7.5)
        ax2.set_xlabel("Lateness Threshold (s)"); ax2.set_ylabel("% Trips Exceeding")
        ax2.set_title("Lateness Violation Rates")
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS_DIR, "fig_lateness.png"), dpi=300)
        plt.close(fig)
        print("Saved: fig_lateness.pdf")

# ── LaTeX + CSV results table ─────────────────────────────────────────────────
COLS = [
    ("Total Pax (hrs)",    "stats_TotalPassDelay_hrs",     1.0,  False),
    ("Main (hrs)",         "stats_MainPassDelay_hrs",       1.0,  False),
    ("Side (hrs)",         "stats_SidePassDelay_hrs",       1.0,  False),
    ("Bus TT (hrs)",       "stats_BusTotalTT_hrs",          1.0,  False),
    ("Car TT (hrs)",       "stats_Net_TotalTT_h_Car",       1.0,  False),
    ("VKT (veh-km/h)",     "aimsun_total_veh_km_h",         1.0,  True),   # higher=better
    ("Avg Bus (s)",        "stats_AvgBusPassDelay_s",       1.0,  False),
    ("Avg Car (s)",        "stats_AvgCarPassDelay_s",       1.0,  False),
    ("Avg Truck (s)",      "stats_AvgTruckPassDelay_s",     1.0,  False),
    ("Z2 BW (s)",          "_Z2",                            1.0,  True),   # higher=better
    ("Z3 Lateness",        "wobj_Z3_total",                 1000, False),   # reported in k pax-s
    ("Z5 Nat-BW",          "_Z5",                            1.0,  True),   # higher=better
]

# Build table rows
table_rows = []
for exp in ordered:
    row = {"Strategy": STRATEGY_LABELS.get(exp, exp)}
    for hdr, col, scale, higher_better in COLS:
        if col == "_Z2":
            v, ci = z2(exp)
        elif col == "_Z5":
            v, ci = z5(exp)
        else:
            v  = avg(exp, col)
            ci = err(exp, col)
        if v is not None:
            row[hdr]          = round(v / scale, 2)
            row[hdr + "_ci"]  = round(ci / scale, 2)
        else:
            row[hdr] = None; row[hdr + "_ci"] = None
    table_rows.append(row)

# ── CSV export ────────────────────────────────────────────────────────────────
csv_path = os.path.join(PLOTS_DIR, "paper_kpi_table.csv")
hdrs_csv = ["Strategy"] + [c[0] for c in COLS] + [c[0]+"_ci" for c in COLS]
with open(csv_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=hdrs_csv)
    w.writeheader(); w.writerows(table_rows)
print(f"Saved: paper_kpi_table.csv")

# ── LaTeX export ──────────────────────────────────────────────────────────────
def fmt_cell(v, ci, hb, base_v):
    """Format mean (Dv%) with optional delta vs baseline."""
    if v is None: return "---"
    pct = 100*(v - base_v)/abs(base_v) if base_v else 0
    sign = "" if hb else ""   # both have sign from pct
    pct_s = f"{pct:+.1f}\\%"
    ci_s  = f"\\pm{ci:.1f}" if ci and ci > 0 else ""
    # colour: green=improvement, red=worse
    if abs(pct) < 0.5:
        col = ""
    elif (hb and pct > 0) or (not hb and pct < 0):
        col = "\\cellcolor{green!15}"
    else:
        col = "\\cellcolor{red!10}"
    return f"{col}{v:.1f}{ci_s} ({pct_s})"

def fmt_base(v, ci):
    if v is None: return "---"
    ci_s = f"\\pm{ci:.1f}" if ci and ci > 0 else ""
    return f"{v:.1f}{ci_s}"

# Base values per column
base_vals = {}
base_row = next((r for r in table_rows if r["Strategy"] == "NoPriority"), None)
for hdr, col, scale, hb in COLS:
    base_vals[hdr] = base_row[hdr] if base_row else None

col_hdrs = " & ".join(["\\textbf{Strategy}"] + [f"\\textbf{{{c[0]}}}" for c in COLS])
latex_rows = []
for row in table_rows:
    cells = [row["Strategy"].replace("/", "/\\allowbreak ")]
    for hdr, col, scale, hb in COLS:
        v  = row.get(hdr)
        ci = row.get(hdr + "_ci", 0) or 0
        bv = base_vals.get(hdr)
        if row["Strategy"] == "NoPriority":
            cells.append(fmt_base(v, ci))
        else:
            cells.append(fmt_cell(v, ci, hb, bv))
    latex_rows.append(" & ".join(cells) + " \\\\")

# Determine number of columns
ncols = 1 + len(COLS)
col_spec = "l" + "r" * len(COLS)

latex = f"""% Auto-generated by generate_paper_plots.py — {n_seeds} seeds averaged
% Paste into TSP_Paper.tex; requires \\usepackage{{booktabs,colortbl,xcolor}}
\\begin{{table}}[htbp]
\\centering
\\caption{{KPI summary: mean $\\pm$ 95\\%\\,CI across {n_seeds} replication seeds.
  $\\Delta\\%$ shown relative to NoPriority baseline.
  Green = improvement vs baseline; red = worse.
  Z2/Z5: higher is better (bandwidth); all other delay/TT metrics: lower is better.
  VKT = total vehicle-kilometres per simulated hour.
  Z3 in k\\,pax\\,s.}}
\\label{{tab:results_kpi}}
\\tiny
\\setlength{{\\tabcolsep}}{{3pt}}
\\begin{{tabular}}{{{col_spec}}}
\\toprule
{col_hdrs} \\\\
\\midrule
""" + "\n".join(latex_rows) + f"""
\\bottomrule
\\end{{tabular}}
\\end{{table}}
"""

tex_path = os.path.join(PLOTS_DIR, "paper_kpi_table.tex")
with open(tex_path, "w", encoding="utf-8") as f:
    f.write(latex)
print(f"Saved: paper_kpi_table.tex")

print(f"\nAll outputs written to {PLOTS_DIR}/")
print(f"Seeds averaged: {n_seeds} per experiment")
