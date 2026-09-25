# =============================================================================
# analyse_results.py
# Post-simulation analysis: reads all CSV outputs from D:\Aimsun_Results\
# and produces comparison bar charts + box plots across strategies,
# averaged (and spread) over seeds.
#
# Run from any Python environment with matplotlib + pandas installed:
#   python analyse_results.py
#
# Or from Aimsun Scripting menu (no AAPI needed).
# =============================================================================

import os
import glob
import pandas as pd
import matplotlib
matplotlib.use('Agg')          # headless — saves PNGs, no display needed
import matplotlib.pyplot as plt
import numpy as np

# ── Configuration ─────────────────────────────────────────────────────────────
# Results are saved to <project>/results/ by batch_runner.py.
# Each experiment is in its own subfolder: <EXPERIMENT>_seed<N>_<ids>/
_HERE        = os.path.dirname(os.path.abspath(__file__))
RESULTS_ROOT = os.path.join(_HERE, "results")
PLOTS_OUT    = os.path.join(_HERE, "plots")

# KPIs to compare from simulation_results.csv (global summary)
GLOBAL_KPIS = {
    "BusTotalTT_hrs":       "Bus Total Travel Time (hrs)",
    "N_BusTrips":           "Bus Trips Completed",
    "N_DistinctBuses":      "Distinct Buses Seen",
    "N_DistinctCars":       "Distinct Cars Seen",
    "AvgBusTT_s":           "Avg Bus Travel Time (s)",
    "TotalPassDelay_hrs":   "Total Passenger Delay (hrs)",
    "MainPassDelay_hrs":    "Main Street Passenger Delay (hrs)",
    "SidePassDelay_hrs":    "Side Street Passenger Delay (hrs)",
    "AvgPassDelay_s":       "Avg Passenger Delay (s/pax)",
    "AvgBusPassDelay_s":    "Avg Bus Passenger Delay (s/pax)",
    "AvgCarPassDelay_s":    "Avg Car Passenger Delay (s/pax)",
    "TSP_Detections":       "TSP Detections",
    "TSP_Extensions":       "TSP Green Extensions",
    "TSP_Insertions":       "TSP Phase Insertions",
}

# KPIs from simulation_results_per_intersection.csv
INTER_KPIS = {
    "TotalPassDelay_hrs":   "Passenger Delay (hrs)",
    "AvgPassDelay_s":       "Avg Delay (s/pax)",
    "AvgBusPassDelay_s":    "Avg Bus Delay (s/pax)",
    "AvgCarPassDelay_s":    "Avg Car Delay (s/pax)",
    "TSP_Extensions":       "Green Extensions",
    "TSP_Insertions":       "Phase Insertions",
}

STRATEGY_COLOURS = {
    "HARMONY":          "#2196F3",   # blue
    "NORMAL":           "#FF9800",   # orange
    "URTSP":            "#4CAF50",   # green
    "GROUP_BASED":      "#9C27B0",   # purple
    "GROUP_BASED_FIXED":"#E91E63",   # pink/red
}
DEFAULT_COLOUR = "#9E9E9E"

# Short display labels for chart axes (long names overlap)
STRATEGY_LABELS = {
    "HARMONY":          "HARMONY",
    "NORMAL":           "NORMAL",
    "URTSP":            "URTSP",
    "GROUP_BASED":      "GB+TSP",
    "GROUP_BASED_FIXED":"GB_FIXED",
}

# =============================================================================
# Data loading
# =============================================================================

def parse_folder_name(folder_name):
    """
    Extract strategy and seed from folder names like:
        HARMONY_seed100_scenX_expY_repZ
    Returns (strategy, seed) or (None, None) if pattern doesn't match.
    """
    parts = folder_name.split('_')
    strategy, seed = None, None
    for i, p in enumerate(parts):
        if p.lower().startswith('seed') and len(p) > 4:
            try:
                seed = int(p[4:])
                strategy = '_'.join(parts[:i])   # everything before 'seedN'
            except ValueError:
                pass
            break
    return strategy, seed


def load_global_results(results_root):
    """Load all simulation_results.csv files, tagging each row with strategy+seed."""
    rows = []
    for folder in os.listdir(results_root):
        folder_path = os.path.join(results_root, folder)
        if not os.path.isdir(folder_path):
            continue
        strategy, seed = parse_folder_name(folder)
        if strategy is None:
            continue   # not a run folder (e.g. "plots")
        csv_path = os.path.join(folder_path, "simulation_results.csv")
        if not os.path.exists(csv_path):
            continue
        try:
            df = pd.read_csv(csv_path)
            df['_strategy'] = strategy
            df['_seed']     = seed
            rows.append(df)
        except Exception as e:
            print(f"[ANALYSE] WARNING: could not read {csv_path}: {e}")
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def load_intersection_results(results_root):
    """Load all per-intersection CSVs, tagging each row with strategy+seed."""
    rows = []
    for folder in os.listdir(results_root):
        folder_path = os.path.join(results_root, folder)
        if not os.path.isdir(folder_path):
            continue
        strategy, seed = parse_folder_name(folder)
        if strategy is None:
            continue
        csv_path = os.path.join(folder_path, "simulation_results_per_intersection.csv")
        if not os.path.exists(csv_path):
            continue
        try:
            df = pd.read_csv(csv_path)
            df['_strategy'] = strategy
            df['_seed']     = seed
            rows.append(df)
        except Exception as e:
            print(f"[ANALYSE] WARNING: could not read {csv_path}: {e}")
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


# =============================================================================
# Plotting helpers
# =============================================================================

# Canonical order for consistent chart layout
STRATEGY_ORDER = ["HARMONY", "NORMAL", "URTSP", "GROUP_BASED", "GROUP_BASED_FIXED"]

def get_strategies(df):
    present = set(df['_strategy'].unique())
    ordered = [s for s in STRATEGY_ORDER if s in present]
    extra   = sorted(present - set(STRATEGY_ORDER))
    return ordered + extra


def bar_with_error(ax, strategies, means, stds, colours, ylabel, title):
    """Bar chart with ±1 std error bars."""
    x    = np.arange(len(strategies))
    cols = [colours.get(s, DEFAULT_COLOUR) for s in strategies]
    bars = ax.bar(x, means, yerr=stds, capsize=5, color=cols,
                  edgecolor='white', linewidth=0.8, error_kw={'elinewidth': 1.5})
    ax.set_xticks(x)
    ax.set_xticklabels([STRATEGY_LABELS.get(s, s) for s in strategies], fontsize=9)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_title(title, fontsize=11, fontweight='bold')
    ax.yaxis.grid(True, linestyle='--', alpha=0.5)
    ax.set_axisbelow(True)
    # Value labels on bars
    for bar, m in zip(bars, means):
        ax.text(bar.get_x() + bar.get_width() / 2.0, bar.get_height() * 1.01,
                f'{m:.3g}', ha='center', va='bottom', fontsize=8)


def box_plot(ax, strategies, data_per_strategy, colours, ylabel, title):
    """Box plot showing spread across seeds."""
    data = [data_per_strategy.get(s, []) for s in strategies]
    cols = [colours.get(s, DEFAULT_COLOUR) for s in strategies]
    bp   = ax.boxplot(data, patch_artist=True, notch=False,
                      medianprops=dict(color='black', linewidth=2))
    for patch, col in zip(bp['boxes'], cols):
        patch.set_facecolor(col)
        patch.set_alpha(0.75)
    ax.set_xticks(range(1, len(strategies) + 1))
    ax.set_xticklabels([STRATEGY_LABELS.get(s, s) for s in strategies], fontsize=9)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_title(title, fontsize=11, fontweight='bold')
    ax.yaxis.grid(True, linestyle='--', alpha=0.5)
    ax.set_axisbelow(True)


# =============================================================================
# Plot generation
# =============================================================================

def plot_global_kpis(df, out_dir):
    """One figure per KPI: bar chart (mean ± std) + box plot side by side."""
    if df.empty:
        print("[ANALYSE] No global data to plot.")
        return

    strategies = get_strategies(df)
    os.makedirs(out_dir, exist_ok=True)

    for col, label in GLOBAL_KPIS.items():
        if col not in df.columns:
            print(f"[ANALYSE] Column '{col}' not found — skipping.")
            continue

        means, stds, by_strat = [], [], {}
        for s in strategies:
            vals = df[df['_strategy'] == s][col].dropna().tolist()
            by_strat[s] = vals
            means.append(np.mean(vals) if vals else 0.0)
            stds.append(np.std(vals)  if len(vals) > 1 else 0.0)

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))
        fig.suptitle(label, fontsize=13, fontweight='bold')

        bar_with_error(ax1, strategies, means, stds,
                       STRATEGY_COLOURS, label, "Mean ± Std across seeds")
        box_plot(ax2, strategies, by_strat,
                 STRATEGY_COLOURS, label, "Distribution across seeds")

        plt.tight_layout()
        safe_name = col.replace('/', '_').replace(' ', '_')
        out_path = os.path.join(out_dir, f"global_{safe_name}.png")
        plt.savefig(out_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        print(f"[ANALYSE] Saved: {out_path}")


def plot_summary_dashboard(df, out_dir):
    """Single figure showing key KPIs side-by-side for quick comparison."""
    if df.empty:
        return

    key_kpis = [
        ("BusTotalTT_hrs",     "Bus Total TT (hrs)"),
        ("TotalPassDelay_hrs", "Total Pax Delay (hrs)"),
        ("AvgBusTT_s",         "Avg Bus TT (s)"),
        ("AvgPassDelay_s",     "Avg Pax Delay (s)"),
        ("TSP_Extensions",     "TSP Extensions"),
        ("TSP_Insertions",     "TSP Insertions"),
    ]
    key_kpis = [(c, l) for c, l in key_kpis if c in df.columns]
    if not key_kpis:
        return

    strategies = get_strategies(df)
    n = len(key_kpis)
    cols_per_row = 3
    n_rows = (n + cols_per_row - 1) // cols_per_row

    fig, axes = plt.subplots(n_rows, cols_per_row,
                             figsize=(5 * cols_per_row, 4.5 * n_rows))
    axes = np.array(axes).flatten()

    for idx, (col, label) in enumerate(key_kpis):
        ax = axes[idx]
        means, stds = [], []
        for s in strategies:
            vals = df[df['_strategy'] == s][col].dropna().tolist()
            means.append(np.mean(vals) if vals else 0.0)
            stds.append(np.std(vals)  if len(vals) > 1 else 0.0)
        bar_with_error(ax, strategies, means, stds, STRATEGY_COLOURS, label, label)

    for idx in range(len(key_kpis), len(axes)):
        axes[idx].set_visible(False)

    fig.suptitle("Strategy Comparison — Key KPIs (mean ± std over seeds)",
                 fontsize=14, fontweight='bold', y=1.01)
    plt.tight_layout()
    out_path = os.path.join(out_dir, "dashboard_summary.png")
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"[ANALYSE] Saved: {out_path}")


def plot_per_intersection(df_inter, out_dir):
    """Bar chart per KPI per intersection, grouped by strategy."""
    if df_inter.empty:
        print("[ANALYSE] No per-intersection data to plot.")
        return

    strategies   = get_strategies(df_inter)
    intersections = sorted(df_inter['IntersectionID'].unique())
    n_inter = len(intersections)
    x = np.arange(n_inter)
    width = 0.8 / max(len(strategies), 1)

    os.makedirs(out_dir, exist_ok=True)

    for col, label in INTER_KPIS.items():
        if col not in df_inter.columns:
            continue

        fig, ax = plt.subplots(figsize=(max(10, n_inter * 1.2), 5))

        for si, strategy in enumerate(strategies):
            sdf    = df_inter[df_inter['_strategy'] == strategy]
            means  = []
            errors = []
            for iid in intersections:
                vals = sdf[sdf['IntersectionID'] == iid][col].dropna().tolist()
                means.append(np.mean(vals) if vals else 0.0)
                errors.append(np.std(vals) if len(vals) > 1 else 0.0)

            offset = (si - len(strategies) / 2.0 + 0.5) * width
            ax.bar(x + offset, means, width, yerr=errors, capsize=3,
                   label=strategy,
                   color=STRATEGY_COLOURS.get(strategy, DEFAULT_COLOUR),
                   edgecolor='white', linewidth=0.5,
                   error_kw={'elinewidth': 1.2})

        ax.set_xticks(x)
        ax.set_xticklabels([str(i) for i in intersections], rotation=45, ha='right', fontsize=8)
        ax.set_ylabel(label, fontsize=10)
        ax.set_title(f"Per-Intersection: {label}", fontsize=11, fontweight='bold')
        ax.legend(fontsize=9)
        ax.yaxis.grid(True, linestyle='--', alpha=0.5)
        ax.set_axisbelow(True)

        plt.tight_layout()
        safe_name = col.replace('/', '_')
        out_path = os.path.join(out_dir, f"intersection_{safe_name}.png")
        plt.savefig(out_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        print(f"[ANALYSE] Saved: {out_path}")


def print_summary_table(df):
    """Print a compact results table to console."""
    if df.empty:
        print("[ANALYSE] No data loaded.")
        return

    strategies = get_strategies(df)
    cols = [c for c in GLOBAL_KPIS if c in df.columns]

    print("\n" + "=" * 80)
    print("STRATEGY COMPARISON — mean (std) over seeds")
    print("=" * 80)
    lbl_strats = [STRATEGY_LABELS.get(s, s) for s in strategies]
    header = f"{'KPI':<30}" + "".join(f"{s:>16}" for s in lbl_strats)
    print(header)
    print("-" * (30 + 16 * len(strategies)))

    for col in cols:
        label = GLOBAL_KPIS[col][:28]
        row = f"{label:<30}"
        for s in strategies:
            vals = df[df['_strategy'] == s][col].dropna().tolist()
            if vals:
                row += f"{np.mean(vals):>10.3g}({np.std(vals):.2g})"
            else:
                row += f"{'N/A':>16}"
        print(row)

    print("=" * 80)
    n_seeds = {s: df[df['_strategy'] == s]['_seed'].nunique() for s in strategies}
    print("Seeds per strategy: " + ", ".join(f"{s}={n}" for s, n in n_seeds.items()))


# =============================================================================
# Main
# =============================================================================

def main():
    print("[ANALYSE] Loading results from: " + RESULTS_ROOT)

    df_global = load_global_results(RESULTS_ROOT)
    df_inter  = load_intersection_results(RESULTS_ROOT)

    if df_global.empty and df_inter.empty:
        print("[ANALYSE] No results found. Check RESULTS_ROOT path and that "
              "runs have completed with save_results() called.")
        return

    print(f"[ANALYSE] Loaded {len(df_global)} global rows, "
          f"{len(df_inter)} intersection rows.")

    print_summary_table(df_global)

    os.makedirs(PLOTS_OUT, exist_ok=True)
    plot_summary_dashboard(df_global, PLOTS_OUT)
    plot_global_kpis(df_global, PLOTS_OUT)
    plot_per_intersection(df_inter, PLOTS_OUT)

    print("\n[ANALYSE] All plots saved to: " + PLOTS_OUT)


main()
