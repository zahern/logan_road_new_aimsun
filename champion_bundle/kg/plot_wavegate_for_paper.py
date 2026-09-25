# =============================================================================
# plot_wavegate_for_paper.py
# Reads batch_results_wavegate.csv, computes statistics across seeds,
# and generates LaTeX tables + figures for the TRB paper.
#
# Usage: python plot_wavegate_for_paper.py
# =============================================================================
import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(_HERE, "batch_results_wavegate.csv")
TRB_DIR = os.path.join(os.path.dirname(_HERE), "TSP_Paper", "TRB_STRIPPED")

# LaTeX table output
LATEX_TABLES_OUT = os.path.join(_HERE, "plots", "paper_tables.tex")

os.makedirs(os.path.dirname(LATEX_TABLES_OUT), exist_ok=True)


def load_and_aggregate(csv_path):
    """Load CSV, compute mean/std across seeds per experiment."""
    df = pd.read_csv(csv_path)
    _key = 'run_experiment'
    experiments = sorted(df[_key].unique())

    metrics = [
        'stats_AvgPassDelay_s',
        'stats_SimBusDelay_pax_s',
        'stats_SimCarDelay_pax_s',
        'stats_TotalPassDelay_hrs',
        'stats_Objective_PaxPerDelayHr',
        'stats_AvgBusPassDelay_s',
        'stats_AvgCarPassDelay_s',
        'stats_BusTotalTT_hrs',
        'stats_N_BusTrips',
        'stats_TSP_Extensions',
        'stats_TSP_Insertions',
    ]

    results = {}
    for exp in experiments:
        edf = df[df[_key] == exp]
        seeds = edf['run_seed'].nunique()
        row = {'experiment': exp, 'n_seeds': seeds}
        for m in metrics:
            if m in edf.columns:
                vals = edf[m].dropna()
                row[f'{m}_mean'] = vals.mean()
                row[f'{m}_std'] = vals.std() if seeds > 1 else 0.0
        results[exp] = row

    return pd.DataFrame(results.values())


def compute_improvements(agg):
    """Compute % improvement relative to NO_TSP baseline."""
    base = agg[agg['experiment'] == 'NO_TSP']
    if len(base) == 0:
        return agg

    base_delay = base['stats_AvgPassDelay_s_mean'].values[0]
    base_bus = base['stats_SimBusDelay_pax_s_mean'].values[0]
    base_car = base['stats_SimCarDelay_pax_s_mean'].values[0]
    base_obj = base['stats_Objective_PaxPerDelayHr_mean'].values[0]

    agg['delay_improvement_pct'] = agg.apply(
        lambda r: ((r['stats_AvgPassDelay_s_mean'] - base_delay) / base_delay) * 100
        if r['experiment'] != 'NO_TSP' else 0.0, axis=1)

    agg['bus_delay_change_pct'] = agg.apply(
        lambda r: ((r['stats_SimBusDelay_pax_s_mean'] - base_bus) / base_bus) * 100
        if r['experiment'] != 'NO_TSP' else 0.0, axis=1)

    agg['car_delay_change_pct'] = agg.apply(
        lambda r: ((r['stats_SimCarDelay_pax_s_mean'] - base_car) / base_car) * 100
        if r['experiment'] != 'NO_TSP' else 0.0, axis=1)

    agg['obj_improvement_pct'] = agg.apply(
        lambda r: ((r['stats_Objective_PaxPerDelayHr_mean'] - base_obj) / base_obj) * 100
        if r['experiment'] != 'NO_TSP' else 0.0, axis=1)

    # Benefit-cost ratio: (bus saved) / (car saved if negative = car reduced)
    agg['bc_ratio'] = agg.apply(
        lambda r: abs(base_bus - r['stats_SimBusDelay_pax_s_mean']) /
        max(abs(base_car - r['stats_SimCarDelay_pax_s_mean']), 1)
        if r['experiment'] != 'NO_TSP' else 0.0, axis=1)

    return agg


def fmt_val(mean, std, suffix=''):
    """Format mean ± std with optional suffix."""
    if std > 0:
        return f'{mean:.2f} ± {std:.2f}{suffix}'
    return f'{mean:.2f}{suffix}'


def _cfg_label(cfg):
    """Human-readable name for LaTeX tables."""
    return {
        'NO_TSP':        'NO\_TSP (baseline)',
        'WG_MG_1_5':    'WG\_MG\_1.5 (best — 1.5 s gate)',
        'WG_HP_MG1':    'WG\_HP\_MG1 (1.0 s gate)',
        'WG_MG_0_5':    'WG\_MG\_0.5 (0.5 s gate)',
        'WG_MG_2_0':    'WG\_MG\_2.0 (2.0 s gate)',
        'WG_HP_MG3':    'WG\_HP\_MG3 (3.0 s gate)',
        'WG_BEST_STACK':'WG\_BEST\_STACK (MG1+PR+OC)',
        'WG_NO_Z1':     'WG\_NO\_Z1 (no pax-delay obj)',
        'WG_NO_Z2':     'WG\_NO\_Z2 (no bandwidth obj)',
        'WG_NO_Z3':     'WG\_NO\_Z3 (no lateness obj)',
        'WG_Z1ONLY':    'WG\_Z1ONLY (pure delay)',
        'WG_OC_THR2':   'WG\_OC\_THR2 (OC gate=2s)',
        'WG_OC_THR5':   'WG\_OC\_THR5 (OC gate=5s)',
        'WG_OC_MAXADJ10': 'WG\_OC\_MAXADJ10 (max trim=10s)',
        'WG_OC_MAXADJ20': 'WG\_OC\_MAXADJ20 (max trim=20s)',
    }.get(cfg, cfg.replace('_', r'\_'))


def generate_main_results_table(agg):
    """Generate LaTeX for Table: WaveGate Performance — key configs vs NO_TSP."""
    # Ordered: baseline, best, next-best from D/G, objective ablations, OC variants
    configs = [
        'NO_TSP',
        'WG_MG_1_5',    # best overall
        'WG_HP_MG1',    # 1.0 s gate
        'WG_HP_MG3',    # 3.0 s gate
        'WG_BEST_STACK',
        'WG_NO_Z2',     # bandwidth dropped → all Z1+Z3
        'WG_Z1ONLY',    # pure delay
        'WG_OC_THR2',
    ]
    existing = set(agg['experiment'].values)

    rows = []
    for cfg in configs:
        if cfg not in existing:
            continue
        r = agg[agg['experiment'] == cfg].iloc[0]
        label = _cfg_label(cfg)
        delay = fmt_val(r['stats_AvgPassDelay_s_mean'], r['stats_AvgPassDelay_s_std'], 's')
        bus   = fmt_val(r['stats_AvgBusPassDelay_s_mean'], r['stats_AvgBusPassDelay_s_std'], 's')
        total = fmt_val(r['stats_TotalPassDelay_hrs_mean'], r['stats_TotalPassDelay_hrs_std'], 'h')
        obj   = fmt_val(r['stats_Objective_PaxPerDelayHr_mean'], r['stats_Objective_PaxPerDelayHr_std'])
        imp   = r['delay_improvement_pct']
        imp_s = f'{imp:+.1f}\\%' if cfg != 'NO_TSP' else '—'
        rows.append(f'{label} & {delay} & {bus} & {total} & {obj} & {imp_s}')

    table = r'''\begin{table}[!ht]
\caption{WaveGate Sensitivity Sweep — Key Configurations
         (mean $\pm$ std over 5 seeds, seed\,\in\,\{7,42,300,12345,99999\})
         }\label{tab:main_results}
\begin{center}
\small
\begin{tabular}{lrrrrr}
\toprule
Configuration & Avg Delay (s) & Avg Bus Delay (s) & Total Pax (h) & Objective & \%\,Imp. \\
\midrule
'''
    table += ' \\\\\n'.join(rows) + ' \\\\'
    table += r'''
\bottomrule
\end{tabular}
\end{center}
\end{table}'''
    return table


def generate_mingain_sweep_table(agg):
    """Generate LaTeX for Table: ZIG min-gain gate sensitivity."""
    configs = ['NO_TSP', 'WG_MG_0_5', 'WG_HP_MG1', 'WG_MG_1_5', 'WG_MG_2_0', 'WG_HP_MG3']
    existing = set(agg['experiment'].values)

    rows = []
    for cfg in configs:
        if cfg not in existing:
            continue
        r = agg[agg['experiment'] == cfg].iloc[0]
        label = _cfg_label(cfg)
        gate  = {'NO_TSP': '—', 'WG_MG_0_5': '0.5', 'WG_HP_MG1': '1.0',
                 'WG_MG_1_5': '1.5', 'WG_MG_2_0': '2.0', 'WG_HP_MG3': '3.0'}.get(cfg, '—')
        delay = f'{r["stats_AvgPassDelay_s_mean"]:.2f}'
        bus   = f'{r["stats_AvgBusPassDelay_s_mean"]:.2f}'
        obj   = f'{r["stats_Objective_PaxPerDelayHr_mean"]:.3f}'
        imp   = r['delay_improvement_pct']
        imp_s = f'{imp:+.1f}\\%' if cfg != 'NO_TSP' else '—'
        rows.append(f'{label} & {gate} & {delay} & {bus} & {obj} & {imp_s}')

    table = r'''\begin{table}[!ht]
\caption{ZIG Min-Gain Gate Sensitivity ($\tau_{\min}$\,s) vs.\ NO\_TSP Baseline
         (mean over 5 seeds)}\label{tab:mg_sweep}
\begin{center}
\begin{tabular}{lrrrrrr}
\toprule
Configuration & $\tau_{\min}$ (s) & Avg Delay (s) & Bus Delay (s) & Objective & \%\,Imp. \\
\midrule
'''
    table += ' \\\\\n'.join(rows) + ' \\\\'
    table += r'''
\bottomrule
\end{tabular}
\end{center}
\end{table}'''
    return table


def generate_tradeoff_table(agg):
    """Generate LaTeX for Table: Bus pax saving vs cross-traffic cost."""
    configs = ['NO_TSP', 'WG_MG_1_5', 'WG_HP_MG1', 'WG_MG_0_5', 'WG_BEST_STACK']
    existing = set(agg['experiment'].values)

    rows = []
    for cfg in configs:
        if cfg not in existing:
            continue
        r = agg[agg['experiment'] == cfg].iloc[0]
        label  = _cfg_label(cfg)
        bus    = f'{r["stats_SimBusDelay_pax_s_mean"]:,.0f}'
        car    = f'{r["stats_SimCarDelay_pax_s_mean"]:,.0f}'
        bc     = f'{r["bc_ratio"]:.1f}\\times'
        bus_ch = r['bus_delay_change_pct']
        car_ch = r['car_delay_change_pct']
        bus_s  = f'{bus_ch:+.1f}\\%' if cfg != 'NO_TSP' else '—'
        car_s  = f'{car_ch:+.1f}\\%' if cfg != 'NO_TSP' else '—'
        bc_s   = bc if cfg != 'NO_TSP' else '—'
        rows.append(f'{label} & {bus} & {bus_s} & {car} & {car_s} & {bc_s}')

    table = r'''\begin{table}[!ht]
\caption{Bus Saving vs.\ Cross-Traffic Cost (mean over 5 seeds; B/C = bus pax·s saved / car pax·s added)
         }\label{tab:tradeoff}
\begin{center}
\begin{tabular}{lrrrrrr}
\toprule
Configuration & Bus Delay (pax·s) & \%\,Chg & Car Delay (pax·s) & \%\,Chg & B/C \\
\midrule
'''
    table += ' \\\\\n'.join(rows) + ' \\\\'
    table += r'''
\bottomrule
\end{tabular}
\end{center}
\end{table}'''
    return table


def generate_objective_ablation_table(agg):
    """Generate LaTeX for Table: Objective weight ablation (Group C)."""
    configs = ['NO_TSP', 'WG_NO_Z1', 'WG_NO_Z2', 'WG_NO_Z3', 'WG_Z1ONLY']
    labels_extra = {
        'NO_TSP':   r'NO\_TSP',
        'WG_NO_Z1': r'Drop $Z_1$ (pax delay) — $\alpha=0$',
        'WG_NO_Z2': r'Drop $Z_2$ (bandwidth) — $\beta=0$',
        'WG_NO_Z3': r'Drop $Z_3$ (lateness) — $\gamma=0$',
        'WG_Z1ONLY':r'Pure $Z_1$ — $\alpha=1,\beta=\gamma=0$',
    }
    existing = set(agg['experiment'].values)

    rows = []
    for cfg in configs:
        if cfg not in existing:
            continue
        r = agg[agg['experiment'] == cfg].iloc[0]
        label = labels_extra.get(cfg, _cfg_label(cfg))
        delay = f'{r["stats_AvgPassDelay_s_mean"]:.2f}'
        bus   = f'{r["stats_AvgBusPassDelay_s_mean"]:.2f}'
        obj   = f'{r["stats_Objective_PaxPerDelayHr_mean"]:.3f}'
        imp   = r['delay_improvement_pct']
        imp_s = f'{imp:+.1f}\\%' if cfg != 'NO_TSP' else '—'
        rows.append(f'{label} & {delay} & {bus} & {obj} & {imp_s}')

    table = r'''\begin{table}[!ht]
\caption{Objective Weight Ablation (Group C, det=50\,m, $\tau_{\min}=1.5$\,s)
         }\label{tab:obj_ablation}
\begin{center}
\begin{tabular}{lrrrr}
\toprule
Configuration & Avg Delay (s) & Bus Delay (s) & Objective & \%\,Imp. \\
\midrule
'''
    table += ' \\\\\n'.join(rows) + ' \\\\'
    table += r'''
\bottomrule
\end{tabular}
\end{center}
\end{table}'''
    return table


def generate_paper_tables(agg):
    """Generate all paper LaTeX tables and write to file."""
    tables = [
        "% Auto-generated by plot_wavegate_for_paper.py",
        "% Generated on: " + pd.Timestamp.now().strftime('%Y-%m-%d %H:%M'),
        f"% Seeds: {agg['n_seeds'].max()}",
        "% Best config: WG_MG_1_5 (min_gain=1.5s, det=50m, all-equal Z1/Z2/Z3)",
        "",
        generate_main_results_table(agg),
        "",
        generate_mingain_sweep_table(agg),
        "",
        generate_tradeoff_table(agg),
        "",
        generate_objective_ablation_table(agg),
        "",
    ]
    with open(LATEX_TABLES_OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(tables))
    print(f'LaTeX tables written to: {LATEX_TABLES_OUT}')


def plot_delay_comparison(agg):
    """Bar chart: Avg passenger delay by configuration."""
    configs_to_plot = ['NO_TSP', 'WG_MG_0_5', 'WG_HP_MG1', 'WG_MG_1_5',
                       'WG_MG_2_0', 'WG_HP_MG3', 'WG_BEST_STACK',
                       'WG_NO_Z2', 'WG_Z1ONLY', 'WG_OC_THR2']
    existing = set(agg['experiment'].values)
    configs_to_plot = [c for c in configs_to_plot if c in existing]

    fig, ax = plt.subplots(figsize=(9, 4.5))
    x = np.arange(len(configs_to_plot))
    delays = []
    errors = []
    for cfg in configs_to_plot:
        r = agg[agg['experiment'] == cfg].iloc[0]
        delays.append(r['stats_AvgPassDelay_s_mean'])
        errors.append(r['stats_AvgPassDelay_s_std'])

    best_idx = delays.index(min(delays[1:], default=delays[0])) if len(delays) > 1 else 0
    bar_colors = ['#e74c3c' if i == 0 else ('#2ecc71' if i == best_idx else '#3498db')
                  for i in range(len(delays))]
    ax.bar(x, delays, yerr=errors, capsize=5, color=bar_colors, alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels([c.replace('_', '\n') for c in configs_to_plot], rotation=0, ha='center', fontsize=7)
    ax.set_ylabel('Avg Passenger Delay (s)')
    ax.set_title('WaveGate Sensitivity Sweep — Average Passenger Delay (5 seeds each)')
    ax.axhline(y=delays[0], color='red', linestyle='--', alpha=0.5, label=f'NO_TSP baseline ({delays[0]:.1f}s)')
    ax.legend(fontsize=8)
    plt.tight_layout()

    out = os.path.join(_HERE, "plots", "paper_delay_comparison.png")
    fig.savefig(out, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f'Delay comparison chart saved to: {out}')


def plot_mingain_sweep(agg):
    """Bar chart: min-gain gate sweep (Group D+G) highlighting WG_MG_1_5 best."""
    configs = ['NO_TSP', 'WG_MG_0_5', 'WG_HP_MG1', 'WG_MG_1_5', 'WG_MG_2_0', 'WG_HP_MG3']
    existing = set(agg['experiment'].values)
    configs = [c for c in configs if c in existing]
    gate_labels = {'NO_TSP': 'none', 'WG_MG_0_5': '0.5', 'WG_HP_MG1': '1.0',
                   'WG_MG_1_5': '1.5*', 'WG_MG_2_0': '2.0', 'WG_HP_MG3': '3.0'}

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    x = np.arange(len(configs))
    colors = ['#e74c3c' if c == 'NO_TSP' else ('#2ecc71' if c == 'WG_MG_1_5' else '#3498db')
              for c in configs]

    delays = [agg[agg['experiment'] == c].iloc[0]['stats_AvgPassDelay_s_mean'] for c in configs]
    bus_d  = [agg[agg['experiment'] == c].iloc[0]['stats_AvgBusPassDelay_s_mean'] for c in configs]
    d_errs = [agg[agg['experiment'] == c].iloc[0]['stats_AvgPassDelay_s_std'] for c in configs]
    b_errs = [agg[agg['experiment'] == c].iloc[0]['stats_AvgBusPassDelay_s_std'] for c in configs]

    axes[0].bar(x, delays, yerr=d_errs, capsize=4, color=colors, alpha=0.85)
    axes[0].axhline(delays[0], color='#e74c3c', ls='--', alpha=0.4)
    axes[0].set_xticks(x); axes[0].set_xticklabels([gate_labels.get(c, c) for c in configs])
    axes[0].set_xlabel('Min-gain gate τ_min (s)'); axes[0].set_ylabel('Avg Passenger Delay (s)')
    axes[0].set_title('All-passenger delay vs gate threshold')

    axes[1].bar(x, bus_d, yerr=b_errs, capsize=4, color=colors, alpha=0.85)
    axes[1].axhline(bus_d[0], color='#e74c3c', ls='--', alpha=0.4)
    axes[1].set_xticks(x); axes[1].set_xticklabels([gate_labels.get(c, c) for c in configs])
    axes[1].set_xlabel('Min-gain gate τ_min (s)'); axes[1].set_ylabel('Avg Bus Passenger Delay (s)')
    axes[1].set_title('Bus delay vs gate threshold')

    fig.suptitle('ZIG Min-Gain Gate Sensitivity (* = new default, 5 seeds)', fontsize=11)
    plt.tight_layout()
    out = os.path.join(_HERE, "plots", "paper_mingain_sweep.png")
    fig.savefig(out, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f'Min-gain sweep chart saved to: {out}')


def print_summary(agg):
    """Print summary to console for verification."""
    print("\n=== WAVEGATE RESULTS SUMMARY ===")
    print(f"{'Config':20s} | {'AvgDelay':>9} | {'BusDelay':>9} | {'TotalPax':>10} | {'Obj':>8} | {'%Imp':>7} | Seeds")
    print("-" * 85)
    configs = sorted(agg['experiment'].values,
                     key=lambda c: agg[agg['experiment'] == c].iloc[0]['stats_TotalPassDelay_hrs_mean'])
    for cfg in configs:
        r = agg[agg['experiment'] == cfg].iloc[0]
        n = int(r['n_seeds'])
        marker = ' *' if cfg == 'WG_MG_1_5' else ('  ' if cfg != 'NO_TSP' else ' ^')
        print(f"{cfg+marker:22s}| {r['stats_AvgPassDelay_s_mean']:8.2f}s | "
              f"{r['stats_AvgBusPassDelay_s_mean']:8.2f}s | "
              f"{r['stats_TotalPassDelay_hrs_mean']:9.2f}h | "
              f"{r['stats_Objective_PaxPerDelayHr_mean']:8.3f} | "
              f"{r['delay_improvement_pct']:+6.1f}% | n={n}")


# =============================================================================
if __name__ == "__main__":
    if not os.path.exists(CSV_PATH):
        print(f"ERROR: {CSV_PATH} not found. Run batch_runner_wavegate.py first.")
    else:
        agg = load_and_aggregate(CSV_PATH)
        agg = compute_improvements(agg)
        print_summary(agg)
        generate_paper_tables(agg)
        plot_delay_comparison(agg)
        plot_mingain_sweep(agg)
