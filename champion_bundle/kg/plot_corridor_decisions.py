"""
Generate per-junction TSP decision visualization for the LaTeX paper.
Shows where and what types of TSP actions (GE/INS/GR/ER) are taken
along the corridor for each WaveGate configuration.
"""
import os, glob
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

KG_DIR = r'C:\Users\ahernz\github_for_aimsun\kg'
OUTPUT_DIR = r'C:\Users\ahernz\github_for_aimsun\TSP_Paper\TRB_STRIPPED'
OUTPUT_FILE = 'fig_corridor_decisions.png'

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
ACTIVE_JCTS = {39606, 39590, 36393, 36385, 39593, 39587, 39576, 39578, 1043762, 39569}


def load_decision_data():
    """Read per-intersection CSVs and compute TSP action counts per junction per config."""
    results_dir = os.path.join(KG_DIR, 'results')
    configs = ['WG_HP_MG1', 'WG_MG_1_5', 'WG_OC_THR2']

    all_data = []
    for cfg in configs:
        matches = [d for d in os.listdir(results_dir) if d.startswith(cfg)]
        for folder_name in matches:
            folder = os.path.join(results_dir, folder_name)
            csv_path = os.path.join(folder, 'simulation_results_per_intersection.csv')
            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path)
                df['config'] = cfg
                all_data.append(df)

    if not all_data:
        print('ERROR: No decision data found')
        return None

    combined = pd.concat(all_data, ignore_index=True)

    # Aggregate TSP actions per junction per config
    action_cols = ['TSP_Extensions', 'TSP_Insertions']
    groupings = {c: 'sum' for c in action_cols if c in combined.columns}
    if 'IntersectionID' not in combined.columns:
        print('No IntersectionID column')
        return None

    grouped = combined.groupby(['config', 'IntersectionID']).agg(groupings).reset_index()
    return grouped


def plot_decision_map(decisions):
    """Plot corridor with pie or stacked-bar charts per junction showing TSP action mix."""
    configs = ['WG_HP_MG1', 'WG_MG_1_5', 'WG_OC_THR2']
    titles = ['WG_HP_MG1\nBalanced (MG=1.0)', 'WG_MG_1_5\nAggressive (MG=1.5)', 'WG_OC_THR2\nConservative Offset']

    fig, axes = plt.subplots(1, 3, figsize=(14, 6.5), dpi=200)
    fig.suptitle('Per-Junction TSP Action Distribution — Kelvin Grove Corridor',
                 fontsize=10, fontweight='bold', y=0.97)

    # Bounds
    all_x = [c[0] for c in JUNCTION_COORDS_UTM.values()]
    all_y = [c[1] for c in JUNCTION_COORDS_UTM.values()]
    pad = 140
    xlim = (min(all_x) - 80, max(all_x) + 80)
    ylim = (min(all_y) - pad, max(all_y) + pad)

    # Colors for action types
    action_colors = {
        'GE': '#e74c3c',   # red - green extension
        'INS': '#8e44ad',  # purple - phase insertion
        'ER': '#3498db',   # blue - early red
        'GR': '#27ae60',   # green - green reallocation
    }

    for ax_idx, (cfg, title) in enumerate(zip(configs, titles)):
        ax = axes[ax_idx]
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        ax.set_aspect('auto')
        ax.axis('off')
        ax.set_title(title, fontsize=8, fontweight='bold', pad=6)

        # Corridor spine
        route_x = [JUNCTION_COORDS_UTM[j][0] for j in ROUTE_ORDER]
        route_y = [JUNCTION_COORDS_UTM[j][1] for j in ROUTE_ORDER]
        ax.plot(route_x, route_y, color='#aaaaaa', linewidth=1.5, alpha=0.4, zorder=1)

        cfg_data = decisions[decisions['config'] == cfg]

        for jid in ROUTE_ORDER:
            x, y = JUNCTION_COORDS_UTM[jid]
            is_active = jid in ACTIVE_JCTS

            if not is_active:
                ax.scatter(x, y, s=15, c='#dddddd', edgecolors='black',
                          linewidth=0.3, zorder=3)
                continue

            jrow = cfg_data[cfg_data['IntersectionID'] == jid]
            if jrow.empty:
                ax.scatter(x, y, s=25, c='#cccccc', edgecolors='black',
                          linewidth=0.3, zorder=3)
                continue

            ext = jrow['TSP_Extensions'].values[0] if 'TSP_Extensions' in jrow.columns else 0
            ins = jrow['TSP_Insertions'].values[0] if 'TSP_Insertions' in jrow.columns else 0

            total = ext + ins

            # Marker size proportional to total actions
            max_size = 140
            min_size = 25
            if total > 0:
                # Normalize across all visible configs
                max_total = max(
                    decisions[(decisions['config'] == c) & (decisions['IntersectionID'] == jid)]
                    ['TSP_Extensions'].sum() + decisions[(decisions['config'] == c) & (decisions['IntersectionID'] == jid)]
                    ['TSP_Insertions'].sum()
                    for c in configs
                    if not decisions[(decisions['config'] == c) & (decisions['IntersectionID'] == jid)].empty
                )
                size = min_size + (max_size - min_size) * (total / max(max_total, 1))
            else:
                size = min_size

            # Color by dominant action type
            if ext >= ins and ext > 0:
                color = action_colors['GE']
            elif ins > 0:
                color = action_colors['INS']
            else:
                color = '#cccccc'

            ax.scatter(x, y, s=size, c=color, edgecolors='black',
                      linewidth=0.5, zorder=5, alpha=0.85)

            # Label: action counts
            label = f'{int(total):d}'
            ax.annotate(label, xy=(x, y), xytext=(8, 4),
                       textcoords='offset points', fontsize=5.5,
                       color='#333333', ha='left', va='bottom',
                       fontweight='bold', zorder=6)

        # North/South labels
        nx, ny = JUNCTION_COORDS_UTM[ROUTE_ORDER[0]]
        sx, sy = JUNCTION_COORDS_UTM[ROUTE_ORDER[-1]]
        ax.annotate('N', xy=(nx, ny), xytext=(0, 10),
                   textcoords='offset points', fontsize=7, color='#888888',
                   ha='center', fontweight='bold')
        ax.annotate('S', xy=(sx, sy), xytext=(0, -10),
                   textcoords='offset points', fontsize=7, color='#888888',
                   ha='center', fontweight='bold')

    # Legend
    legend_elements = [
        mpatches.Patch(color=action_colors['GE'], alpha=0.7, label='GE (Green Extension)'),
        mpatches.Patch(color=action_colors['INS'], alpha=0.7, label='INS (Phase Insertion)'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor='#dddddd', markersize=5,
               markeredgecolor='black', markeredgewidth=0.3, label='Passive junction'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor='white', markersize=10,
               label='Marker size = action count'),
    ]
    axes[0].legend(handles=legend_elements, loc='lower right', fontsize=5.5, framealpha=0.9)

    plt.tight_layout(pad=0.5)
    output_path = f'{OUTPUT_DIR}\\{OUTPUT_FILE}'
    fig.savefig(output_path, dpi=300, bbox_inches=None)
    print(f'Saved decision map to: {output_path}')
    plt.close(fig)


# =============================================================================
if __name__ == "__main__":
    decisions = load_decision_data()
    if decisions is not None:
        # Print summary
        for cfg in ['WG_HP_MG1', 'WG_MG_1_5', 'WG_OC_THR2']:
            cdf = decisions[decisions['config'] == cfg]
            if cdf.empty:
                continue
            total_ext = cdf['TSP_Extensions'].sum() if 'TSP_Extensions' in cdf.columns else 0
            total_ins = cdf['TSP_Insertions'].sum() if 'TSP_Insertions' in cdf.columns else 0
            print(f'{cfg}: GE={total_ext}, INS={total_ins}, total={total_ext+total_ins}')

        plot_decision_map(decisions)
