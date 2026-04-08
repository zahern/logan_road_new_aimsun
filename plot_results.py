# =============================================================================
# plot_results.py — compile batch results and visualise strategy benefits
#
# Reads all run folders under RESULTS_ROOT and produces:
#   - Per-intersection avg passenger delay comparison (bar + box)
#   - Global corridor avg passenger delay comparison  (bar + box)
#   - Benefit vs NORMAL baseline (absolute and %)
#   - Key KPI dashboard
#
# Run from any Python environment with matplotlib + pandas:
#   python plot_results.py
#
# Or from the Aimsun Scripting menu (no AAPI required).
# =============================================================================

import os
import json
import glob as _glob
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# =============================================================================
# ── CONFIGURATION ─────────────────────────────────────────────────────────────
# =============================================================================
RESULTS_ROOT   = r"D:\Aimsun_Results"
PLOTS_OUT      = r"D:\Aimsun_Results\plots"
BASELINE       = "NORMAL"          # strategy used as "do-nothing" reference

# Strategies in display order (any not listed here are appended alphabetically)
STRATEGY_ORDER = [
    "NORMAL",
    "URTSP",
    "HARMONY",
    "GROUP_BASED",
    "GROUP_BASED_URTSP",
    "GROUP_BASED_HARMONY",
    "GROUP_BASED_FIXED",
]

STRATEGY_COLOURS = {
    "NORMAL":               "#FF9800",
    "URTSP":                "#4CAF50",
    "HARMONY":              "#2196F3",
    "GROUP_BASED":          "#9C27B0",
    "GROUP_BASED_URTSP":    "#673AB7",
    "GROUP_BASED_HARMONY":  "#3F51B5",
    "GROUP_BASED_FIXED":    "#E91E63",
}
DEFAULT_COLOUR = "#9E9E9E"

STRATEGY_LABELS = {
    "NORMAL":               "NORMAL",
    "URTSP":                "URTSP",
    "HARMONY":              "HARMONY",
    "GROUP_BASED":          "GB",
    "GROUP_BASED_URTSP":    "GB+URTSP",
    "GROUP_BASED_HARMONY":  "GB+HAR",
    "GROUP_BASED_FIXED":    "GB_FIXED",
}

# =============================================================================
# ── DATA LOADING ──────────────────────────────────────────────────────────────
# =============================================================================

def _parse_folder(folder_name):
    """
    Extract strategy and seed from folder names like:
        HARMONY_seed100_scenX_expY_repZ
        GROUP_BASED_URTSP_seed201_...
    Returns (strategy, seed) or (None, None).
    """
    parts = folder_name.split('_')
    for i, p in enumerate(parts):
        if p.lower().startswith('seed') and len(p) > 4:
            try:
                seed     = int(p[4:])
                strategy = '_'.join(parts[:i])
                return strategy, seed
            except ValueError:
                pass
    return None, None


def load_global(results_root):
    """Load simulation_results.csv from every run folder."""
    rows = []
    for folder in os.listdir(results_root):
        fp = os.path.join(results_root, folder)
        if not os.path.isdir(fp):
            continue
        strategy, seed = _parse_folder(folder)
        if strategy is None:
            continue
        csv = os.path.join(fp, "simulation_results.csv")
        if not os.path.exists(csv):
            continue
        try:
            df = pd.read_csv(csv)
            df['_strategy'] = strategy
            df['_seed']     = seed
            rows.append(df)
        except Exception as e:
            print(f"[PLOT] WARNING: {csv}: {e}")
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def load_intersection(results_root):
    """Load simulation_results_per_intersection.csv from every run folder."""
    rows = []
    for folder in os.listdir(results_root):
        fp = os.path.join(results_root, folder)
        if not os.path.isdir(fp):
            continue
        strategy, seed = _parse_folder(folder)
        if strategy is None:
            continue
        csv = os.path.join(fp, "simulation_results_per_intersection.csv")
        if not os.path.exists(csv):
            continue
        try:
            df = pd.read_csv(csv)
            df['_strategy'] = strategy
            df['_seed']     = seed
            rows.append(df)
        except Exception as e:
            print(f"[PLOT] WARNING: {csv}: {e}")
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def load_summaries(results_root):
    """Load summary.json from every run folder into a list of dicts."""
    records = []
    for folder in os.listdir(results_root):
        fp = os.path.join(results_root, folder)
        if not os.path.isdir(fp):
            continue
        strategy, seed = _parse_folder(folder)
        if strategy is None:
            continue
        jpath = os.path.join(fp, "summary.json")
        if not os.path.exists(jpath):
            continue
        try:
            with open(jpath, 'r', encoding='utf-8') as f:
                d = json.load(f)
            d['_strategy'] = strategy
            d['_seed']     = seed
            records.append(d)
        except Exception as e:
            print(f"[PLOT] WARNING: {jpath}: {e}")
    return pd.DataFrame(records) if records else pd.DataFrame()


# =============================================================================
# ── STRATEGY ORDERING ─────────────────────────────────────────────────────────
# =============================================================================

def ordered_strategies(df):
    present = set(df['_strategy'].unique())
    ordered = [s for s in STRATEGY_ORDER if s in present]
    extra   = sorted(present - set(STRATEGY_ORDER))
    return ordered + extra


# =============================================================================
# ── PLOTTING HELPERS ──────────────────────────────────────────────────────────
# =============================================================================

def _col(s):
    return STRATEGY_COLOURS.get(s, DEFAULT_COLOUR)


def _lbl(s):
    return STRATEGY_LABELS.get(s, s)


def bar_box(strategies, means, stds, data_per_strat, ylabel, title, out_path):
    """Two-panel figure: bar chart (mean ± std) + box plot (spread over seeds)."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle(title, fontsize=13, fontweight='bold')

    x    = np.arange(len(strategies))
    cols = [_col(s) for s in strategies]
    lbls = [_lbl(s) for s in strategies]

    # Bar chart
    bars = ax1.bar(x, means, yerr=stds, capsize=5, color=cols,
                   edgecolor='white', linewidth=0.8,
                   error_kw={'elinewidth': 1.5})
    ax1.set_xticks(x)
    ax1.set_xticklabels(lbls, fontsize=9, rotation=20, ha='right')
    ax1.set_ylabel(ylabel, fontsize=10)
    ax1.set_title("Mean ± Std (over seeds)", fontsize=10)
    ax1.yaxis.grid(True, linestyle='--', alpha=0.5)
    ax1.set_axisbelow(True)
    for bar, m in zip(bars, means):
        if m != 0:
            ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.01,
                     f'{m:.3g}', ha='center', va='bottom', fontsize=8)

    # Box plot
    data = [data_per_strat.get(s, []) for s in strategies]
    bp = ax2.boxplot(data, patch_artist=True, notch=False,
                     medianprops=dict(color='black', linewidth=2))
    for patch, col in zip(bp['boxes'], cols):
        patch.set_facecolor(col)
        patch.set_alpha(0.75)
    ax2.set_xticks(range(1, len(strategies) + 1))
    ax2.set_xticklabels(lbls, fontsize=9, rotation=20, ha='right')
    ax2.set_ylabel(ylabel, fontsize=10)
    ax2.set_title("Distribution over seeds", fontsize=10)
    ax2.yaxis.grid(True, linestyle='--', alpha=0.5)
    ax2.set_axisbelow(True)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"[PLOT] Saved: {out_path}")


def benefit_bar(strategies, baseline_mean, means, stds, ylabel_abs, ylabel_pct,
                title, out_path):
    """
    Two-panel figure showing benefit vs NORMAL baseline:
      left  — absolute reduction in delay (s/pax)
      right — percentage reduction (%)
    """
    non_base = [s for s in strategies if s != BASELINE]
    if not non_base:
        return

    abs_vals  = [baseline_mean - means[strategies.index(s)] for s in non_base]
    pct_vals  = [(v / baseline_mean * 100) if baseline_mean else 0
                 for v in abs_vals]
    cols      = [_col(s) for s in non_base]
    lbls      = [_lbl(s) for s in non_base]
    x         = np.arange(len(non_base))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5))
    fig.suptitle(f"Benefit vs {BASELINE} — {title}", fontsize=13, fontweight='bold')

    for ax, vals, lbl in [(ax1, abs_vals, ylabel_abs), (ax2, pct_vals, ylabel_pct)]:
        colours = [_col(s) if v >= 0 else '#f44336' for s, v in zip(non_base, vals)]
        bars = ax.bar(x, vals, color=colours, edgecolor='white', linewidth=0.8)
        ax.axhline(0, color='black', linewidth=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(lbls, fontsize=9, rotation=20, ha='right')
        ax.set_ylabel(lbl, fontsize=10)
        ax.yaxis.grid(True, linestyle='--', alpha=0.5)
        ax.set_axisbelow(True)
        for bar, v in zip(bars, vals):
            ypos = bar.get_height() + (0.005 * max(abs(v) for v in vals + [1]))
            ax.text(bar.get_x() + bar.get_width() / 2, ypos,
                    f'{v:+.2g}', ha='center', va='bottom', fontsize=8)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"[PLOT] Saved: {out_path}")


# =============================================================================
# ── GLOBAL CORRIDOR PLOTS ─────────────────────────────────────────────────────
# =============================================================================

def plot_global_delay(df_global, out_dir):
    """Avg passenger delay for the whole corridor — bar+box + benefit charts."""
    if df_global.empty or 'AvgPassDelay_s' not in df_global.columns:
        print("[PLOT] No global AvgPassDelay_s column found — skipping global plots.")
        return

    strategies = ordered_strategies(df_global)
    means, stds, by_strat = [], [], {}

    for s in strategies:
        vals = df_global[df_global['_strategy'] == s]['AvgPassDelay_s'].dropna().tolist()
        by_strat[s] = vals
        means.append(np.mean(vals) if vals else 0.0)
        stds.append(np.std(vals)  if len(vals) > 1 else 0.0)

    bar_box(
        strategies, means, stds, by_strat,
        ylabel  = "Avg Passenger Delay (s/pax)",
        title   = "Global Corridor — Avg Passenger Delay",
        out_path= os.path.join(out_dir, "global_AvgPassDelay.png"),
    )

    # Benefit vs baseline
    if BASELINE in strategies:
        bi = strategies.index(BASELINE)
        benefit_bar(
            strategies, means[bi], means, stds,
            ylabel_abs = "Delay Reduction (s/pax)",
            ylabel_pct = "Delay Reduction (%)",
            title      = "Avg Passenger Delay",
            out_path   = os.path.join(out_dir, "global_benefit_AvgPassDelay.png"),
        )

    # Bus-specific delay
    if 'AvgBusPassDelay_s' in df_global.columns:
        bm, bs, bby = [], [], {}
        for s in strategies:
            vals = df_global[df_global['_strategy'] == s]['AvgBusPassDelay_s'].dropna().tolist()
            bby[s] = vals
            bm.append(np.mean(vals) if vals else 0.0)
            bs.append(np.std(vals)  if len(vals) > 1 else 0.0)
        bar_box(
            strategies, bm, bs, bby,
            ylabel  = "Avg Bus Passenger Delay (s/pax)",
            title   = "Global Corridor — Avg Bus Passenger Delay",
            out_path= os.path.join(out_dir, "global_AvgBusPassDelay.png"),
        )
        if BASELINE in strategies:
            bi = strategies.index(BASELINE)
            benefit_bar(
                strategies, bm[bi], bm, bs,
                ylabel_abs = "Bus Delay Reduction (s/pax)",
                ylabel_pct = "Bus Delay Reduction (%)",
                title      = "Avg Bus Passenger Delay",
                out_path   = os.path.join(out_dir, "global_benefit_AvgBusPassDelay.png"),
            )


def plot_global_dashboard(df_global, out_dir):
    """Single-figure dashboard with all key global KPIs."""
    if df_global.empty:
        return

    kpis = [
        ("AvgPassDelay_s",      "Avg Pax Delay (s/pax)"),
        ("AvgBusPassDelay_s",   "Avg Bus Delay (s/pax)"),
        ("AvgCarPassDelay_s",   "Avg Car Delay (s/pax)"),
        ("TotalPassDelay_hrs",  "Total Pax Delay (hrs)"),
        ("TSP_Extensions",      "TSP Extensions"),
        ("TSP_Insertions",      "TSP Insertions"),
    ]
    kpis = [(c, l) for c, l in kpis if c in df_global.columns]
    if not kpis:
        return

    strategies = ordered_strategies(df_global)
    n = len(kpis)
    ncols = min(3, n)
    nrows = (n + ncols - 1) // ncols

    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4.5 * nrows))
    axes = np.array(axes).flatten()

    for idx, (col, lbl) in enumerate(kpis):
        ax    = axes[idx]
        means = []
        stds  = []
        for s in strategies:
            vals = df_global[df_global['_strategy'] == s][col].dropna().tolist()
            means.append(np.mean(vals) if vals else 0.0)
            stds.append(np.std(vals)  if len(vals) > 1 else 0.0)

        x    = np.arange(len(strategies))
        cols = [_col(s) for s in strategies]
        ax.bar(x, means, yerr=stds, capsize=4, color=cols,
               edgecolor='white', linewidth=0.8, error_kw={'elinewidth': 1.2})
        ax.set_xticks(x)
        ax.set_xticklabels([_lbl(s) for s in strategies],
                           fontsize=8, rotation=20, ha='right')
        ax.set_ylabel(lbl, fontsize=9)
        ax.set_title(lbl, fontsize=9, fontweight='bold')
        ax.yaxis.grid(True, linestyle='--', alpha=0.5)
        ax.set_axisbelow(True)

    for idx in range(len(kpis), len(axes)):
        axes[idx].set_visible(False)

    fig.suptitle("Strategy Comparison Dashboard (mean ± std over seeds)",
                 fontsize=13, fontweight='bold', y=1.01)
    plt.tight_layout()
    path = os.path.join(out_dir, "dashboard.png")
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"[PLOT] Saved: {path}")


# =============================================================================
# ── PER-INTERSECTION PLOTS ────────────────────────────────────────────────────
# =============================================================================

def plot_intersection_delay(df_inter, out_dir):
    """
    One figure per KPI showing all intersections grouped by strategy.
    Also saves a benefit plot (reduction vs NORMAL) for AvgPassDelay_s.
    """
    if df_inter.empty:
        print("[PLOT] No per-intersection data found.")
        return

    kpis = [
        ("AvgPassDelay_s",      "Avg Pax Delay (s/pax)"),
        ("AvgBusPassDelay_s",   "Avg Bus Delay (s/pax)"),
        ("AvgCarPassDelay_s",   "Avg Car Delay (s/pax)"),
        ("TotalPassDelay_hrs",  "Pax Delay (hrs)"),
    ]
    kpis = [(c, l) for c, l in kpis if c in df_inter.columns]

    strategies    = ordered_strategies(df_inter)
    intersections = sorted(df_inter['IntersectionID'].unique())
    n_inter       = len(intersections)
    x             = np.arange(n_inter)
    width         = 0.8 / max(len(strategies), 1)

    for col, lbl in kpis:
        fig, ax = plt.subplots(figsize=(max(10, n_inter * 1.4), 5.5))

        for si, s in enumerate(strategies):
            sdf    = df_inter[df_inter['_strategy'] == s]
            means  = []
            errors = []
            for iid in intersections:
                vals = sdf[sdf['IntersectionID'] == iid][col].dropna().tolist()
                means.append(np.mean(vals) if vals else 0.0)
                errors.append(np.std(vals) if len(vals) > 1 else 0.0)

            offset = (si - len(strategies) / 2.0 + 0.5) * width
            ax.bar(x + offset, means, width, yerr=errors, capsize=3,
                   label=_lbl(s), color=_col(s),
                   edgecolor='white', linewidth=0.5,
                   error_kw={'elinewidth': 1.0})

        ax.set_xticks(x)
        ax.set_xticklabels([str(i) for i in intersections],
                           rotation=45, ha='right', fontsize=8)
        ax.set_ylabel(lbl, fontsize=10)
        ax.set_title(f"Per-Intersection — {lbl}", fontsize=11, fontweight='bold')
        ax.legend(fontsize=8, ncol=min(len(strategies), 4))
        ax.yaxis.grid(True, linestyle='--', alpha=0.5)
        ax.set_axisbelow(True)

        plt.tight_layout()
        safe = col.replace('/', '_')
        path = os.path.join(out_dir, f"intersection_{safe}.png")
        plt.savefig(path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        print(f"[PLOT] Saved: {path}")

    # Benefit per intersection vs NORMAL baseline (AvgPassDelay_s)
    if 'AvgPassDelay_s' not in df_inter.columns or BASELINE not in strategies:
        return

    non_base = [s for s in strategies if s != BASELINE]
    if not non_base:
        return

    fig, axes = plt.subplots(len(non_base), 1,
                              figsize=(max(10, n_inter * 1.2), 4.5 * len(non_base)))
    if len(non_base) == 1:
        axes = [axes]

    for ax, s in zip(axes, non_base):
        delta = []
        for iid in intersections:
            base_vals = df_inter[
                (df_inter['_strategy'] == BASELINE) &
                (df_inter['IntersectionID'] == iid)
            ]['AvgPassDelay_s'].dropna().tolist()
            s_vals = df_inter[
                (df_inter['_strategy'] == s) &
                (df_inter['IntersectionID'] == iid)
            ]['AvgPassDelay_s'].dropna().tolist()
            b = np.mean(base_vals) if base_vals else 0.0
            v = np.mean(s_vals)    if s_vals    else 0.0
            delta.append(b - v)

        colours = [_col(s) if d >= 0 else '#f44336' for d in delta]
        ax.bar(x, delta, color=colours, edgecolor='white', linewidth=0.6)
        ax.axhline(0, color='black', linewidth=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels([str(i) for i in intersections],
                           rotation=45, ha='right', fontsize=8)
        ax.set_ylabel("Delay Reduction (s/pax)", fontsize=10)
        ax.set_title(f"{_lbl(s)} vs {BASELINE} — Per-Intersection Avg Pax Delay Reduction",
                     fontsize=10, fontweight='bold')
        ax.yaxis.grid(True, linestyle='--', alpha=0.5)
        ax.set_axisbelow(True)

    plt.tight_layout()
    path = os.path.join(out_dir, "intersection_benefit_AvgPassDelay.png")
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"[PLOT] Saved: {path}")


# =============================================================================
# ── SUMMARY TABLE ─────────────────────────────────────────────────────────────
# =============================================================================

def print_summary(df_global, df_inter):
    """Print compact tables to console."""
    if df_global.empty:
        print("[PLOT] No global data loaded.")
        return

    strategies = ordered_strategies(df_global)
    cols = [c for c in [
        "AvgPassDelay_s", "AvgBusPassDelay_s", "AvgCarPassDelay_s",
        "TotalPassDelay_hrs", "TSP_Extensions", "TSP_Insertions",
    ] if c in df_global.columns]

    print("\n" + "=" * 80)
    print("GLOBAL CORRIDOR — mean (std) over seeds")
    print("=" * 80)
    lbl_strats = [_lbl(s) for s in strategies]
    header = f"{'KPI':<28}" + "".join(f"{s:>18}" for s in lbl_strats)
    print(header)
    print("-" * (28 + 18 * len(strategies)))

    baseline_delay = None
    for col in cols:
        lbl = col[:26]
        row = f"{lbl:<28}"
        for s in strategies:
            vals = df_global[df_global['_strategy'] == s][col].dropna().tolist()
            if vals:
                row += f"{np.mean(vals):>12.3g}({np.std(vals):.1g})"
            else:
                row += f"{'N/A':>18}"
        print(row)
        if col == "AvgPassDelay_s":
            bv = df_global[df_global['_strategy'] == BASELINE]['AvgPassDelay_s'].dropna().tolist()
            baseline_delay = np.mean(bv) if bv else None

    print("=" * 80)

    # Benefit row
    if baseline_delay and baseline_delay > 0:
        print(f"\nBenefit vs {BASELINE} (AvgPassDelay_s, mean over seeds):")
        for s in strategies:
            if s == BASELINE:
                continue
            vals = df_global[df_global['_strategy'] == s]['AvgPassDelay_s'].dropna().tolist()
            if vals:
                delta = baseline_delay - np.mean(vals)
                pct   = delta / baseline_delay * 100
                print(f"  {_lbl(s):<20}: {delta:+.2f} s/pax  ({pct:+.1f}%)")

    # Per-intersection summary
    if not df_inter.empty and 'AvgPassDelay_s' in df_inter.columns:
        print(f"\nPER-INTERSECTION AvgPassDelay_s (mean over seeds):")
        intersections = sorted(df_inter['IntersectionID'].unique())
        header2 = f"{'IntersectionID':<20}" + "".join(f"{_lbl(s):>14}" for s in strategies)
        print(header2)
        print("-" * (20 + 14 * len(strategies)))
        for iid in intersections:
            row = f"{iid:<20}"
            for s in strategies:
                vals = df_inter[
                    (df_inter['_strategy'] == s) &
                    (df_inter['IntersectionID'] == iid)
                ]['AvgPassDelay_s'].dropna().tolist()
                row += f"{np.mean(vals):>14.3g}" if vals else f"{'N/A':>14}"
            print(row)
        print("=" * 80)


# =============================================================================
# ── MAIN ──────────────────────────────────────────────────────────────────────
# =============================================================================

def main():
    print(f"[PLOT] Loading results from: {RESULTS_ROOT}")

    df_global = load_global(RESULTS_ROOT)
    df_inter  = load_intersection(RESULTS_ROOT)

    if df_global.empty and df_inter.empty:
        print("[PLOT] No results found. Check RESULTS_ROOT and that runs have completed.")
        return

    print(f"[PLOT] Loaded {len(df_global)} global rows, {len(df_inter)} intersection rows.")
    strategies = ordered_strategies(df_global) if not df_global.empty else []
    print(f"[PLOT] Strategies found: {strategies}")

    os.makedirs(PLOTS_OUT, exist_ok=True)

    print_summary(df_global, df_inter)

    plot_global_dashboard(df_global, PLOTS_OUT)
    plot_global_delay(df_global, PLOTS_OUT)
    plot_intersection_delay(df_inter, PLOTS_OUT)

    print(f"\n[PLOT] All plots saved to: {PLOTS_OUT}")


main()
