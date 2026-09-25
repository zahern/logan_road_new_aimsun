"""
Generate corridor TSP-effect visualization for the LaTeX paper.
Shows per-junction passenger delay changes under WaveGate vs NO_TSP.
Uses actual network coordinates and per-intersection simulation results.
"""
import os, json, glob
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

KG_DIR = r'C:\Users\ahernz\github_for_aimsun\kg'
OUTPUT_DIR = r'C:\Users\ahernz\github_for_aimsun\TSP_Paper\TRB_STRIPPED'
OUTPUT_FILE = 'fig_corridor_tsp_effect.png'

# UTM coordinates of junctions (north to south)
JUNCTION_COORDS_UTM = {
    38339:  (500084.0, 6967501.8),
    39572:  (499518.6, 6966649.1),
    39569:  (499894.5, 6966541.3),
    1043762:(499993.1, 6966493.8),
    39587:  (500491.1, 6965703.3),
    39578:  (500459.2, 6965697.1),
    39576:  (500135.2, 6965615.4),
    39593:  (500700.5, 6964925.2),
    36385:  (500672.0, 6964570.2),
    36393:  (500751.2, 6964307.8),
    39590:  (500895.9, 6964115.5),
    39606:  (500949.1, 6964042.8),
}

ROUTE_ORDER = [38339, 39572, 39569, 1043762, 39587, 39578, 39576,
               39593, 36385, 36393, 39590, 39606]

# Active TSP junctions (exclude passive)
ACTIVE_JCTS = {39606, 39590, 36393, 36385, 39593, 39587, 39576, 39578, 1043762, 39569}


def load_per_intersection_data():
    """Read all per-intersection CSVs and compute mean AvgPassDelay per junction per config."""
    results_dir = os.path.join(KG_DIR, 'results')
    configs_of_interest = ['NO_TSP', 'WG_HP_MG1', 'WG_MG_1_5', 'WG_OC_THR2', 'WG_BEST_STACK']

    all_data = []
    for cfg in configs_of_interest:
        # Find all matching result folders
        matches = [d for d in os.listdir(results_dir) if d.startswith(cfg)]
        for folder_name in matches:
            folder = os.path.join(results_dir, folder_name)
            csv_path = os.path.join(folder, 'simulation_results_per_intersection.csv')
            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path)
                df['config'] = cfg
                # Infer seed from folder name
                seed = 300  # default
                for part in folder_name.split('_'):
                    if part.startswith('seed') and part[4:].isdigit():
                        seed = int(part[4:])
                        break
                df['seed'] = seed
                all_data.append(df)

    if not all_data:
        print('ERROR: No per-intersection data found')
        return {}, {}

    combined = pd.concat(all_data, ignore_index=True)

    # Average across seeds per junction per config
    grouped = combined.groupby(['config', 'IntersectionID'])['AvgPassDelay_s'].agg(['mean', 'count']).reset_index()
    grouped.columns = ['config', 'junction_id', 'avg_delay_s', 'n_samples']

    # Pivot to get NO_TSP baseline per junction
    pivot = grouped.pivot(index='junction_id', columns='config', values='avg_delay_s')

    # Compute changes
    for cfg in ['WG_HP_MG1', 'WG_MG_1_5', 'WG_OC_THR2', 'WG_BEST_STACK']:
        if cfg in pivot.columns and 'NO_TSP' in pivot.columns:
            pivot[f'{cfg}_delta'] = pivot[cfg] - pivot['NO_TSP']
            pivot[f'{cfg}_pct'] = (pivot[f'{cfg}_delta'] / pivot['NO_TSP']) * 100

    return grouped, pivot


def plot_corridor_tsp_effect(grouped, pivot):
    """Create multi-panel corridor visualization showing TSP effects."""
    configs_to_show = ['NO_TSP', 'WG_HP_MG1', 'WG_MG_1_5']
    titles = ['NO_TSP (Baseline)', 'WG_HP_MG1 (Balanced, MG=1.0)', 'WG_MG_1_5 (Aggressive, MG=1.5)']
    colors = ['#999999', '#2ca02c', '#d62728']

    # Layout: 3 panels side by side
    fig, axes = plt.subplots(1, 3, figsize=(12, 6), dpi=200)
    fig.suptitle('Kelvin Grove Corridor — Per-Junction Passenger Delay Under WaveGate TSP',
                 fontsize=10, fontweight='bold', y=0.98)

    # Corridor extent
    all_x = [c[0] for c in JUNCTION_COORDS_UTM.values()]
    all_y = [c[1] for c in JUNCTION_COORDS_UTM.values()]
    pad = 150
    xlim = (min(all_x) - 400, max(all_x) + 300)
    ylim = (min(all_y) - pad, max(all_y) + pad)

    # Global min/max delay for consistent color scale
    all_delays = []
    for cfg in configs_to_show:
        for jid in ROUTE_ORDER:
            if jid in pivot.index and cfg in pivot.columns:
                all_delays.append(pivot.loc[jid, cfg])
    vmin, vmax = min(all_delays), max(all_delays)

    for ax_idx, (cfg, title, base_color) in enumerate(zip(configs_to_show, titles, colors)):
        ax = axes[ax_idx]
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        ax.set_aspect('auto')
        ax.axis('off')
        ax.set_title(title, fontsize=8, fontweight='bold', pad=6)

        # Draw corridor spine
        route_x = [JUNCTION_COORDS_UTM[j][0] for j in ROUTE_ORDER]
        route_y = [JUNCTION_COORDS_UTM[j][1] for j in ROUTE_ORDER]
        ax.plot(route_x, route_y, color='#666666', linewidth=2, alpha=0.5, zorder=1)

        # Draw junction markers sized and colored by delay
        for jid in ROUTE_ORDER:
            x, y = JUNCTION_COORDS_UTM[jid]
            is_active = jid in ACTIVE_JCTS

            # Get delay value
            delay = None
            if jid in pivot.index and cfg in pivot.columns:
                delay = pivot.loc[jid, cfg]

            if delay is not None and not np.isnan(delay):
                # Color: green=low delay, red=high delay
                ratio = (delay - vmin) / (vmax - vmin) if vmax > vmin else 0.5
                color = plt.cm.RdYlGn_r(ratio)
                size = 80 if is_active else 35
                ax.scatter(x, y, s=size, c=[color], edgecolors='black',
                          linewidth=0.5 if is_active else 0.3, zorder=5)

                # Label
                label = f'{delay:.0f}s'
                ax.annotate(label, xy=(x, y), xytext=(8, 4),
                           textcoords='offset points', fontsize=5.5,
                           color='#333333', ha='left', va='bottom', zorder=6)
            else:
                ax.scatter(x, y, s=25, c='#cccccc', edgecolors='black',
                          linewidth=0.3, zorder=4)

        # Corridor extent labels
        nx, ny = JUNCTION_COORDS_UTM[ROUTE_ORDER[0]]
        sx, sy = JUNCTION_COORDS_UTM[ROUTE_ORDER[-1]]
        ax.annotate('N', xy=(nx, ny), xytext=(0, 12),
                   textcoords='offset points', fontsize=7, color='#555555',
                   ha='center', va='bottom', fontweight='bold',
                   arrowprops=dict(arrowstyle='->', color='#888888', lw=0.5))
        ax.annotate('S', xy=(sx, sy), xytext=(0, -12),
                   textcoords='offset points', fontsize=7, color='#555555',
                   ha='center', va='top', fontweight='bold',
                   arrowprops=dict(arrowstyle='->', color='#888888', lw=0.5))

    # Colorbar
    sm = plt.cm.ScalarMappable(cmap=plt.cm.RdYlGn_r, norm=plt.Normalize(vmin=vmin, vmax=vmax))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=axes, orientation='vertical', fraction=0.02, pad=0.02)
    cbar.set_label('Avg Passenger Delay (s)', fontsize=7)
    cbar.ax.tick_params(labelsize=6)

    # Legend
    legend_elements = [
        Line2D([0], [0], marker='o', color='w', markerfacecolor='#2ca02c', markersize=8,
               markeredgecolor='black', markeredgewidth=0.5, label='TSP-active junction'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor='#cccccc', markersize=6,
               markeredgecolor='black', markeredgewidth=0.3, label='Passive junction'),
    ]
    axes[0].legend(handles=legend_elements, loc='lower right', fontsize=5.5, framealpha=0.9)

    plt.tight_layout(rect=[0, 0, 0.92, 0.95])

    output_path = f'{OUTPUT_DIR}\\{OUTPUT_FILE}'
    fig.savefig(output_path, dpi=300, bbox_inches=None)
    print(f'Saved TSP effect corridor map to: {output_path}')
    plt.close(fig)


def plot_delay_change_map(pivot):
    """Create a single-panel map showing delay change (delta) under WG_HP_MG1 vs NO_TSP."""
    fig, ax = plt.subplots(figsize=(5, 6.5), dpi=200)

    all_x = [c[0] for c in JUNCTION_COORDS_UTM.values()]
    all_y = [c[1] for c in JUNCTION_COORDS_UTM.values()]
    pad = 120
    xlim = (min(all_x) - 60, max(all_x) + 60)
    ylim = (min(all_y) - pad, max(all_y) + pad)

    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_aspect('auto')
    ax.axis('off')
    ax.set_title('Delay Change Under WaveGate HP_MG1 vs NO_TSP\n(negative = improvement)', fontsize=9, fontweight='bold')

    # Draw corridor line
    route_x = [JUNCTION_COORDS_UTM[j][0] for j in ROUTE_ORDER]
    route_y = [JUNCTION_COORDS_UTM[j][1] for j in ROUTE_ORDER]
    ax.plot(route_x, route_y, color='#888888', linewidth=1.5, alpha=0.4, zorder=1)

    cfg = 'WG_HP_MG1'
    delta_col = f'{cfg}_delta'
    pct_col = f'{cfg}_pct'

    deltas = []
    for jid in ROUTE_ORDER:
        if jid in pivot.index and delta_col in pivot.columns:
            d = pivot.loc[jid, delta_col]
            if not np.isnan(d):
                deltas.append(d)

    vmin, vmax = min(deltas), max(deltas)
    vmax_abs = max(abs(vmin), abs(vmax))
    vmin, vmax = -vmax_abs, vmax_abs

    for jid in ROUTE_ORDER:
        x, y = JUNCTION_COORDS_UTM[jid]
        is_active = jid in ACTIVE_JCTS

        delta = None
        pct = None
        if jid in pivot.index and delta_col in pivot.columns:
            delta = pivot.loc[jid, delta_col]
            pct = pivot.loc[jid, pct_col] if pct_col in pivot.columns else None

        if delta is not None and not np.isnan(delta):
            ratio = (delta - vmin) / (vmax - vmin) if vmax > vmin else 0.5
            color = plt.cm.RdBu(ratio)
            size = 90 if is_active else 30

            ax.scatter(x, y, s=size, c=[color], edgecolors='black',
                      linewidth=0.6, zorder=5)

            if is_active and pct is not None and not np.isnan(pct):
                label = f'{pct:+.0f}%'
                ax.annotate(label, xy=(x, y), xytext=(7, 3),
                           textcoords='offset points', fontsize=6,
                           color='#222222', ha='left', va='bottom',
                           fontweight='bold', zorder=6)
        else:
            ax.scatter(x, y, s=20, c='#dddddd', edgecolors='black',
                      linewidth=0.3, zorder=4)

    sm = plt.cm.ScalarMappable(cmap=plt.cm.RdBu, norm=plt.Normalize(vmin=vmin, vmax=vmax))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, orientation='horizontal', fraction=0.05, pad=0.04)
    cbar.set_label('Avg Delay Change (s)', fontsize=7)
    cbar.ax.tick_params(labelsize=6)

    plt.tight_layout(pad=0.5)

    output_path = f'{OUTPUT_DIR}\\fig_corridor_delta.png'
    fig.savefig(output_path, dpi=300, bbox_inches=None)
    print(f'Saved delay delta map to: {output_path}')
    plt.close(fig)


def print_summary(pivot):
    """Print per-junction summary for verification."""
    print('\n=== PER-JUNCTION DELAY COMPARISON ===')
    print(f'{"Jct":>8s}  {"NO_TSP":>7s}  {"HP_MG1":>7s}  {"MG_1_5":>7s}  {"Delta":>7s}')
    print('-' * 45)
    for jid in ROUTE_ORDER:
        if jid in pivot.index:
            base = pivot.loc[jid, 'NO_TSP'] if 'NO_TSP' in pivot.columns else float('nan')
            mg1 = pivot.loc[jid, 'WG_HP_MG1'] if 'WG_HP_MG1' in pivot.columns else float('nan')
            mg15 = pivot.loc[jid, 'WG_MG_1_5'] if 'WG_MG_1_5' in pivot.columns else float('nan')
            delta = pivot.loc[jid, 'WG_HP_MG1_delta'] if 'WG_HP_MG1_delta' in pivot.columns else float('nan')
            active = '*' if jid in ACTIVE_JCTS else ' '
            if not np.isnan(base):
                print(f'{active}{jid:>7d}  {base:7.1f}  {mg1:7.1f}  {mg15:7.1f}  {delta:+7.1f}')


# =============================================================================
if __name__ == "__main__":
    grouped, pivot = load_per_intersection_data()
    if not grouped.empty:
        print_summary(pivot)
        plot_corridor_tsp_effect(grouped, pivot)
        plot_delay_change_map(pivot)
