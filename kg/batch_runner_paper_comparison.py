# =============================================================================
# batch_runner_paper_comparison.py — TRB Paper comprehensive comparison
# =============================================================================
#
# PURPOSE:
#   Runs all experiments needed to support the four main comparisons in the
#   TRB WaveGate paper:
#
#   GROUP M: Method comparison  — positions WaveGate against prior TSP methods
#     NO_TSP          no priority (baseline)
#     DCTSP_LEGACY    DCTSP without ZIG gate (fires on any positive reward)
#     DCTSP_NOGATE    ZIG optimiser, no minimum-gain filter (greedy ZIG)
#     BARGAIN         Nash-bargaining ZIG (cooperative signal game)
#     WG_MG_1_5       WaveGate best (ZIG + 1.5 s gate + equal Z1/Z2/Z3)
#
#   GROUP O: Objective ablation — which objectives contribute?
#     WG_MG_1_5       all-equal reference (α=β=γ=1/3)
#     WG_NO_Z1        no pax-delay term   (α=0)
#     WG_NO_Z2        no bandwidth term   (β=0)
#     WG_NO_Z3        no lateness term    (γ=0)
#     WG_Z1ONLY       pure pax-delay      (α=1, β=γ=0)
#
#   GROUP K: Component stacking — incremental value of each mechanism
#     WG_BASE         ZIG gate only (min_gain=1.5 s, no OC/PR)
#     WG_BASE_OC      ZIG + offset correction
#     WG_BASE_PR      ZIG + phase rotation
#     WG_FULL_STACK   ZIG + OC + PR  (= WG_BEST_STACK)
#
#   GROUP S: Demand sensitivity — robustness across loading levels
#     NO_TSP   × demand ∈ {0.85, 1.0, 1.15}
#     WG_MG_1_5 × demand ∈ {0.85, 1.0, 1.15}
#
# SEEDS: 5 (same set as wavegate sweep for direct comparability)
# TOTAL: ≈ (5+5+4+6) × 5 seeds = 100 simulation runs
#
# USAGE:
#   Open in Aimsun → Run Script.
#   After completion all results, plots, and LaTeX tables are reported.
#
# =============================================================================

import os as _os
import re
import json
import csv
import glob
import shutil
import sys as _sys
import time as _time
import datetime
from PyANGKernel import GKSystem

_SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))

# ── Active junctions (same exclusion logic as wavegate sweep) ─────────────────
_PASSIVE_JCT_IDS = {10157950, 11118289, 1119660, 39568}
try:
    from intersection_configs import INTERSECTIONS_CONFIG as _IC_CFG
    _ACTIVE_JCTS_LIST = [jid for jid, cfg in _IC_CFG.items()
                         if cfg.get('SignalGroupIDList')]
except ImportError:
    _ACTIVE_JCTS_LIST = None

# =============================================================================
# ── Fixed WaveGate base (same as wavegate sweep for comparability) ────────────
# =============================================================================
_WG_BASE = {
    "GLOBAL_REWARD_MODE":            True,
    "BARGAIN_SPM_MODE":              False,
    "DCTSP_ZIG_MODE":                True,
    "META_TSP_MODE":                 False,
    "MDN_DELAY_MODE":                False,
    "HS_EXT_MODE":                   False,
    "DCTSP_GREEN_REALLOC_MODE":      True,
    "GREEN_REALLOC_RECOVER_FRACTION":1.0,
    "BUS_PREDICTOR_TYPE":            "ADAPTIVE_KALMAN",
    "ZIG_BALANCE_FACTOR":            1.0,
    "NETWORK_FACTOR":                1.0,
    "NETWORK_FACTOR_DENSITY_RAMP":   False,
    "ZIG_PHASE_OVERLAP_S":           0.5,
    "ZIG_MIN_GAIN_S":                1.5,
    "ZIG_DE_POP":                    12,
    "ZIG_DE_ITER":                   30,
    "ZIG_DE_F":                      0.8,
    "ZIG_DE_CR":                     0.9,
    "WOBJ_Z1_SCALE":                 3000000.0,
    "WOBJ_Z2_SCALE":                 7500.0,
    "WOBJ_Z3_SCALE":                 12000.0,
    "WOBJ_ALPHA":                    round(1/3, 6),
    "WOBJ_BETA":                     round(1/3, 6),
    "WOBJ_GAMMA":                    round(1/3, 6),
    "DETECTION_WINDOW_M_OVERRIDE":   50.0,
}

_OC_BEST = {
    "OFFSET_CORRECTION_MODE":  True,
    "DCTSP_OC_THRESH_S":       3.0,
    "DCTSP_OC_MAX_ADJ_S":      15.0,
}
_PR_BEST = {
    "PHASE_ROTATION_MODE":          True,
    "PHASE_ROTATION_N_SEQS":        3.0,
    "PHASE_ROTATION_THRESHOLD_S":   5.0,
}


def _wg(name, overrides):
    ov = dict(_WG_BASE)
    ov.update(overrides)
    return {
        "name":                 name,
        "enabled":              True,
        "strategy":             "GLOBAL_REWARD",
        "coordinated":          True,
        "coordination_algo":    "SHOCKWAVE",
        "active_intersections": _ACTIVE_JCTS_LIST,
        "reward_overrides":     ov,
        "sweep_group":          "?",   # will be overridden per experiment
    }


# =============================================================================
# ── EXPERIMENT DEFINITIONS ────────────────────────────────────────────────────
# =============================================================================
# Each experiment carries a "sweep_group" key so plots can separate the groups.

_NO_TSP = {
    "name":                 "NO_TSP",
    "enabled":              True,
    "strategy":             "NORMAL",
    "coordinated":          False,
    "coordination_algo":    "KALMAN",
    "active_intersections": None,
    "reward_overrides":     {},
    "sweep_group":          "M",
}

# ── GROUP M: Method Comparison ────────────────────────────────────────────────
_DCTSP_LEGACY = _wg("DCTSP_LEGACY", {
    # DCTSP without ZIG: fires whenever the MARL reward is positive (old behaviour)
    "DCTSP_ZIG_MODE":   False,
    "ZIG_MIN_GAIN_S":   0.0,
})
_DCTSP_LEGACY["sweep_group"] = "M"

_DCTSP_NOGATE = _wg("DCTSP_NOGATE", {
    # ZIG optimiser running, but no minimum-gain filter — fires on any gain
    "DCTSP_ZIG_MODE":   True,
    "ZIG_MIN_GAIN_S":   0.0,
})
_DCTSP_NOGATE["sweep_group"] = "M"

_BARGAIN = _wg("BARGAIN", {
    # Nash-bargaining cooperative mode — bus and cross-traffic jointly optimise
    "BARGAIN_SPM_MODE": True,
    "ZIG_MIN_GAIN_S":   1.5,
})
_BARGAIN["sweep_group"] = "M"

_WG_BEST_M = _wg("WG_MG_1_5", {})   # proven best, copied into every group
_WG_BEST_M["sweep_group"] = "M"

# ── GROUP O: Objective Ablation ───────────────────────────────────────────────
_WG_BEST_O     = _wg("WG_MG_1_5_O",  {})
_WG_NO_Z1      = _wg("WG_NO_Z1",  {"WOBJ_ALPHA": 0.0, "WOBJ_BETA": 0.5,  "WOBJ_GAMMA": 0.5})
_WG_NO_Z2      = _wg("WG_NO_Z2",  {"WOBJ_ALPHA": 0.5, "WOBJ_BETA": 0.0,  "WOBJ_GAMMA": 0.5})
_WG_NO_Z3      = _wg("WG_NO_Z3",  {"WOBJ_ALPHA": 0.5, "WOBJ_BETA": 0.5,  "WOBJ_GAMMA": 0.0})
_WG_Z1ONLY     = _wg("WG_Z1ONLY", {"WOBJ_ALPHA": 1.0, "WOBJ_BETA": 0.0,  "WOBJ_GAMMA": 0.0})
for _e in [_WG_BEST_O, _WG_NO_Z1, _WG_NO_Z2, _WG_NO_Z3, _WG_Z1ONLY]:
    _e["sweep_group"] = "O"

# ── GROUP K: Component Stacking ───────────────────────────────────────────────
_WG_BASE_K  = _wg("WG_BASE_K",  {})                             # ZIG only
_WG_OC_K    = _wg("WG_OC_K",   dict(_OC_BEST))                  # + OC
_WG_PR_K    = _wg("WG_PR_K",   dict(_PR_BEST))                  # + PR
_WG_FULL_K  = _wg("WG_FULL_K", {**_OC_BEST, **_PR_BEST, "ZIG_MIN_GAIN_S": 1.0})
for _e in [_WG_BASE_K, _WG_OC_K, _WG_PR_K, _WG_FULL_K]:
    _e["sweep_group"] = "K"

# ── GROUP S: Demand Sensitivity ───────────────────────────────────────────────
# These experiments run at DEMAND_SCALARS_S = [0.85, 1.0, 1.15].
# The demand level is embedded in the experiment name so each row is unique.
# (They are separated into a dedicated list and looped with _DEMAND_SCALARS_S.)
_DEMAND_SCALARS_S = [0.85, 1.0, 1.15]

_SENSITIVITY_TEMPLATES = [
    # Just two configs at each demand level: baseline + best WaveGate
    dict(_NO_TSP,    name="NO_TSP_S",   sweep_group="S", enabled=True),
    _wg("WG_BEST_S", {}),
]
_SENSITIVITY_TEMPLATES[-1]["sweep_group"] = "S"


# Combine all fixed-demand groups into a single ordered list
EXPERIMENTS_FIXED = [
    # ── Group M ──
    dict(_NO_TSP),        # also serves as the shared reference
    _DCTSP_LEGACY,
    _DCTSP_NOGATE,
    _BARGAIN,
    _WG_BEST_M,
    # ── Group O ──
    _WG_BEST_O,
    _WG_NO_Z1, _WG_NO_Z2, _WG_NO_Z3, _WG_Z1ONLY,
    # ── Group K ──
    _WG_BASE_K, _WG_OC_K, _WG_PR_K, _WG_FULL_K,
]

SEEDS          = [300, 42, 12345, 7, 99]
DEMAND_SCALARS = [1.0]

BATCH_RESULTS_CSV = _os.path.join(_SCRIPT_DIR, "batch_results_paper_comparison.csv")
PLOTS_DIR         = _os.path.join(_SCRIPT_DIR, "plots", "paper_comparison")
# NOTE: The Kelvin Grove model's demand matrices are NOT named "01d Logan Rd 2025 *".
# Setting TARGET_DEMAND_NAMES = None tells _is_target_demand() to match ALL
# GKTrafficDemand objects, which is correct for this corridor regardless of naming.
# The local variable below has NO effect on the imported _br.set_demand_scalar — we
# must override _br.TARGET_DEMAND_NAMES directly in __main__ (done below).
TARGET_DEMAND_NAMES = None

# =============================================================================
# ── Shared infrastructure — imported from batch_runner.py ────────────────────
# =============================================================================
import importlib.util as _ilu
_br_path = _os.path.join(_SCRIPT_DIR, "batch_runner.py")
_spec    = _ilu.spec_from_file_location("_br", _br_path)
_br      = _ilu.module_from_spec(_spec)
_sys.modules["_br"] = _br
try:
    _spec.loader.exec_module(_br)
except SystemExit:
    pass

log                            = _br.log
set_control_mode               = _br.set_control_mode
set_coordinated                = _br.set_coordinated
set_coordination_algo          = _br.set_coordination_algo
set_seed                       = _br.set_seed
set_reward_weights             = _br.set_reward_weights
write_run_config               = _br.write_run_config
collect_run_metrics            = _br.collect_run_metrics
append_master_csv              = _br.append_master_csv
get_first_replication          = _br.get_first_replication
run_replication                = _br.run_replication
_purge_pyc                     = _br._purge_pyc
set_demand_scalar              = _br.set_demand_scalar
set_junctions_external_control = _br.set_junctions_external_control

CONTROLLER_PATH  = _br.CONTROLLER_PATH
RUN_CONFIG_PATH  = _br.RUN_CONFIG_PATH
PROJECT_DIR      = _br.PROJECT_DIR


# =============================================================================
# ── Run-config builder (same defaults as wavegate sweep) ─────────────────────
# =============================================================================
def _build_run_cfg(reward_overrides):
    cfg = {
        "REWARD_INV_DELAY_MODE":              False,
        "REWARD_V2X_MODE":                    False,
        "REWARD_SELFORG_MODE":                False,
        "DCTSP_ZIG_MODE":                     True,
        "MP_ECTM_MODE":                       False,
        "BXT_MODE":                           False,
        "BARGAIN_SPM_MODE":                   False,
        "HS_EXT_MODE":                        False,
        "META_TSP_MODE":                      False,
        "MDN_DELAY_MODE":                     False,
        "REWARD_MAIN_SECTION_WEIGHT":         1.0,
        "REWARD_SIDE_SECTION_WEIGHT":         0.50,
        "WOBJ_ALPHA":                         round(1/3, 6),
        "WOBJ_BETA":                          round(1/3, 6),
        "WOBJ_GAMMA":                         round(1/3, 6),
        "DETECTION_PROB":                     1.0,
        "BUS_OCC_OVERRIDE":                   None,
        "CAR_OCC_OVERRIDE":                   None,
        "DETECTION_WINDOW_M_OVERRIDE":        50.0,
        "NETWORK_FACTOR":                     1.0,
        "NETWORK_FACTOR_DENSITY_RAMP":        False,
        "REWARD_FUTURE_HORIZON_CYCLES":       1.0,
        "TSP_CYCLE_LENGTH_OVERRIDE_S":        10.0,
        "GREEN_REALLOC_RECOVER_FRACTION":     1.0,
        "DCTSP_CONGESTION_GATE":              False,
        "DCTSP_CONGESTION_GATE_FRACTION":     0.85,
    }
    cfg.update({k: v for k, v in reward_overrides.items() if k != "GLOBAL_REWARD_MODE"})
    return cfg


# =============================================================================
# ── Post-run: generate all paper plots + LaTeX tables ────────────────────────
# =============================================================================
def _generate_paper_plots(csv_path, out_dir):
    """
    Read batch_results_paper_comparison.csv and write:
      - plots/paper_comparison/fig_method_comparison.png
      - plots/paper_comparison/fig_objective_ablation.png
      - plots/paper_comparison/fig_component_stacking.png
      - plots/paper_comparison/fig_demand_sensitivity.png
      - plots/paper_comparison/fig_bus_car_tradeoff.png
      - plots/paper_comparison/tables_paper_comparison.tex
    Returns list of output file paths.
    """
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    _os.makedirs(out_dir, exist_ok=True)

    df = pd.read_csv(csv_path)
    _KEY = 'run_experiment'

    # ── Aggregate across seeds ────────────────────────────────────────────────
    metrics = [
        'stats_AvgPassDelay_s',
        'stats_AvgBusPassDelay_s',
        'stats_AvgCarPassDelay_s',
        'stats_SimBusDelay_pax_s',
        'stats_SimCarDelay_pax_s',
        'stats_TotalPassDelay_hrs',
        'stats_Objective_PaxPerDelayHr',
        'stats_TSP_Extensions',
        'stats_TSP_Insertions',
    ]

    def _agg(subset_df):
        results = {}
        for exp in subset_df[_KEY].unique():
            edf = subset_df[subset_df[_KEY] == exp]
            row = {'experiment': exp, 'n_seeds': edf['run_seed'].nunique()}
            for m in metrics:
                if m in edf.columns:
                    vals = edf[m].dropna()
                    row[f'{m}_mean'] = vals.mean()
                    row[f'{m}_std']  = vals.std(ddof=1) if len(vals) > 1 else 0.0
            # demand scalar if present
            if 'run_demand_scalar' in edf.columns:
                row['demand_scalar'] = edf['run_demand_scalar'].iloc[0]
            results[exp] = row
        return pd.DataFrame(results.values())

    agg = _agg(df)

    # Improvement relative to NO_TSP at demand=1.0
    ref_name = 'NO_TSP'
    ref_rows = agg[agg['experiment'] == ref_name]
    if len(ref_rows) == 0:
        ref_name = agg['experiment'].iloc[0]
        ref_rows = agg[agg['experiment'] == ref_name]
    base_delay = ref_rows.iloc[0]['stats_AvgPassDelay_s_mean']
    base_bus   = ref_rows.iloc[0]['stats_SimBusDelay_pax_s_mean']
    base_car   = ref_rows.iloc[0]['stats_SimCarDelay_pax_s_mean']

    def _imp(row, col='stats_AvgPassDelay_s_mean'):
        return (row[col] - base_delay) / base_delay * 100

    # ── Paper style helpers ────────────────────────────────────────────────────
    PAPER_W, PAPER_H = 8, 4.2
    PAL = {
        'baseline': '#c0392b',
        'M':        '#2980b9',
        'O':        '#8e44ad',
        'K':        '#27ae60',
        'S_notsp':  '#e67e22',
        'S_wg':     '#2980b9',
        'best':     '#27ae60',
    }

    def _bar_style(ax):
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.yaxis.grid(True, linestyle=':', alpha=0.4)
        ax.set_axisbelow(True)

    OUTPUT_FILES = []

    # ══════════════════════════════════════════════════════════════════════════
    # FIG M: Method Comparison
    # ══════════════════════════════════════════════════════════════════════════
    method_cfgs = ['NO_TSP', 'DCTSP_LEGACY', 'DCTSP_NOGATE', 'BARGAIN', 'WG_MG_1_5']
    method_cfgs = [c for c in method_cfgs if c in agg['experiment'].values]
    method_labels = {
        'NO_TSP':       'NO TSP\n(baseline)',
        'DCTSP_LEGACY': 'DCTSP\n(no gate)',
        'DCTSP_NOGATE': 'ZIG\n(greedy)',
        'BARGAIN':      'Bargaining\nZIG',
        'WG_MG_1_5':   'WaveGate\n(best)',
    }

    if method_cfgs:
        fig, axes = plt.subplots(1, 3, figsize=(PAPER_W * 1.3, PAPER_H))
        x = np.arange(len(method_cfgs))
        colors = [PAL['baseline'] if c == 'NO_TSP' else
                  (PAL['best']    if c == 'WG_MG_1_5' else PAL['M'])
                  for c in method_cfgs]

        def _vals(col):
            means, errs = [], []
            for c in method_cfgs:
                r = agg[agg['experiment'] == c].iloc[0]
                means.append(r.get(f'{col}_mean', 0))
                errs.append(r.get(f'{col}_std', 0))
            return np.array(means), np.array(errs)

        lbl_x = [method_labels.get(c, c) for c in method_cfgs]

        d_m, d_e = _vals('stats_AvgPassDelay_s')
        axes[0].bar(x, d_m, yerr=d_e, capsize=4, color=colors, alpha=0.85, edgecolor='#444', linewidth=0.5)
        axes[0].axhline(d_m[0], color=PAL['baseline'], ls='--', lw=1, alpha=0.5)
        axes[0].set_xticks(x); axes[0].set_xticklabels(lbl_x, fontsize=7)
        axes[0].set_ylabel('Avg Passenger Delay (s)'); axes[0].set_title('(a) All-Passenger Delay')
        _bar_style(axes[0])

        b_m, b_e = _vals('stats_AvgBusPassDelay_s')
        axes[1].bar(x, b_m, yerr=b_e, capsize=4, color=colors, alpha=0.85, edgecolor='#444', linewidth=0.5)
        axes[1].axhline(b_m[0], color=PAL['baseline'], ls='--', lw=1, alpha=0.5)
        axes[1].set_xticks(x); axes[1].set_xticklabels(lbl_x, fontsize=7)
        axes[1].set_ylabel('Avg Bus Passenger Delay (s)'); axes[1].set_title('(b) Bus Delay')
        _bar_style(axes[1])

        # Bus vs car pax·s scatter
        bpax_m, _ = _vals('stats_SimBusDelay_pax_s')
        cpax_m, _ = _vals('stats_SimCarDelay_pax_s')
        for i, c in enumerate(method_cfgs):
            axes[2].scatter(cpax_m[i]/1e6, bpax_m[i]/1e6, color=colors[i],
                            s=90, zorder=3, edgecolors='#333', linewidths=0.7,
                            label=method_labels.get(c, c))
            axes[2].annotate(method_labels.get(c, c).replace('\n', ' '),
                             (cpax_m[i]/1e6, bpax_m[i]/1e6),
                             textcoords='offset points', xytext=(5, 3), fontsize=6)
        axes[2].set_xlabel('Car Delay (M pax·s)'); axes[2].set_ylabel('Bus Delay (M pax·s)')
        axes[2].set_title('(c) Bus vs Car Delay Trade-off')
        _bar_style(axes[2])

        fig.suptitle('Figure M — Method Comparison (mean ± std, 5 seeds)', fontsize=10, y=1.01)
        plt.tight_layout()
        out = _os.path.join(out_dir, 'fig_method_comparison.png')
        fig.savefig(out, dpi=200, bbox_inches='tight')
        plt.close(fig)
        OUTPUT_FILES.append(out)
        print(f'  [plot] Method comparison   → {out}')

    # ══════════════════════════════════════════════════════════════════════════
    # FIG O: Objective Ablation
    # ══════════════════════════════════════════════════════════════════════════
    # Use both the dedicated O-group names and the M-group WG_MG_1_5 as reference
    obj_cfgs = ['NO_TSP', 'WG_MG_1_5', 'WG_MG_1_5_O', 'WG_NO_Z1', 'WG_NO_Z2', 'WG_NO_Z3', 'WG_Z1ONLY']
    obj_cfgs = [c for c in obj_cfgs if c in agg['experiment'].values]
    # Merge WG_MG_1_5 and WG_MG_1_5_O to a single display entry
    _ref_wg = 'WG_MG_1_5' if 'WG_MG_1_5' in obj_cfgs else ('WG_MG_1_5_O' if 'WG_MG_1_5_O' in obj_cfgs else None)
    obj_display = [c for c in obj_cfgs if c not in ('WG_MG_1_5', 'WG_MG_1_5_O')]
    if _ref_wg:
        obj_display = ['NO_TSP', _ref_wg] + [c for c in obj_display if c != 'NO_TSP']
    obj_labels = {
        'NO_TSP':       'NO TSP',
        'WG_MG_1_5':   'All-equal\n(α=β=γ=⅓)',
        'WG_MG_1_5_O': 'All-equal\n(α=β=γ=⅓)',
        'WG_NO_Z1':    'α=0\n(no Z₁)',
        'WG_NO_Z2':    'β=0\n(no Z₂)',
        'WG_NO_Z3':    'γ=0\n(no Z₃)',
        'WG_Z1ONLY':   'α=1\n(Z₁ only)',
    }

    if len(obj_display) >= 3:
        fig, axes = plt.subplots(1, 2, figsize=(PAPER_W, PAPER_H))
        x = np.arange(len(obj_display))
        colors_o = [PAL['baseline'] if c == 'NO_TSP' else
                    (PAL['best'] if c in ('WG_MG_1_5', 'WG_MG_1_5_O') else PAL['O'])
                    for c in obj_display]

        d_m = [agg[agg['experiment'] == c].iloc[0]['stats_AvgPassDelay_s_mean'] for c in obj_display]
        d_e = [agg[agg['experiment'] == c].iloc[0]['stats_AvgPassDelay_s_std']  for c in obj_display]
        b_m = [agg[agg['experiment'] == c].iloc[0]['stats_AvgBusPassDelay_s_mean'] for c in obj_display]
        b_e = [agg[agg['experiment'] == c].iloc[0]['stats_AvgBusPassDelay_s_std']  for c in obj_display]

        axes[0].bar(x, d_m, yerr=d_e, capsize=4, color=colors_o, alpha=0.85, edgecolor='#444', linewidth=0.5)
        axes[0].axhline(d_m[0], color=PAL['baseline'], ls='--', lw=1, alpha=0.5)
        axes[0].set_xticks(x); axes[0].set_xticklabels([obj_labels.get(c, c) for c in obj_display], fontsize=7)
        axes[0].set_ylabel('Avg Passenger Delay (s)'); axes[0].set_title('(a) All-Passenger Delay')
        _bar_style(axes[0])

        axes[1].bar(x, b_m, yerr=b_e, capsize=4, color=colors_o, alpha=0.85, edgecolor='#444', linewidth=0.5)
        axes[1].axhline(b_m[0], color=PAL['baseline'], ls='--', lw=1, alpha=0.5)
        axes[1].set_xticks(x); axes[1].set_xticklabels([obj_labels.get(c, c) for c in obj_display], fontsize=7)
        axes[1].set_ylabel('Avg Bus Passenger Delay (s)'); axes[1].set_title('(b) Bus Delay')
        _bar_style(axes[1])

        fig.suptitle('Figure O — Objective Weight Ablation (mean ± std, 5 seeds)', fontsize=10, y=1.01)
        plt.tight_layout()
        out = _os.path.join(out_dir, 'fig_objective_ablation.png')
        fig.savefig(out, dpi=200, bbox_inches='tight')
        plt.close(fig)
        OUTPUT_FILES.append(out)
        print(f'  [plot] Objective ablation  → {out}')

    # ══════════════════════════════════════════════════════════════════════════
    # FIG K: Component Stacking (waterfall)
    # ══════════════════════════════════════════════════════════════════════════
    stack_cfgs = ['NO_TSP', 'WG_BASE_K', 'WG_OC_K', 'WG_PR_K', 'WG_FULL_K']
    stack_cfgs = [c for c in stack_cfgs if c in agg['experiment'].values]
    stack_labels = {
        'NO_TSP':     'NO TSP',
        'WG_BASE_K':  'ZIG\nonly',
        'WG_OC_K':    'ZIG\n+ OC',
        'WG_PR_K':    'ZIG\n+ PR',
        'WG_FULL_K':  'ZIG\n+ OC\n+ PR',
    }

    if len(stack_cfgs) >= 3:
        fig, axes = plt.subplots(1, 2, figsize=(PAPER_W, PAPER_H))
        x = np.arange(len(stack_cfgs))
        colors_k = [PAL['baseline'] if c == 'NO_TSP' else
                    (PAL['best'] if c == 'WG_FULL_K' else PAL['K'])
                    for c in stack_cfgs]

        d_m = [agg[agg['experiment'] == c].iloc[0]['stats_AvgPassDelay_s_mean'] for c in stack_cfgs]
        d_e = [agg[agg['experiment'] == c].iloc[0]['stats_AvgPassDelay_s_std']  for c in stack_cfgs]
        b_m = [agg[agg['experiment'] == c].iloc[0]['stats_AvgBusPassDelay_s_mean'] for c in stack_cfgs]

        axes[0].bar(x, d_m, yerr=d_e, capsize=4, color=colors_k, alpha=0.85, edgecolor='#444', linewidth=0.5)
        axes[0].axhline(d_m[0], color=PAL['baseline'], ls='--', lw=1, alpha=0.5)
        for i in range(1, len(d_m)):
            delta = d_m[i] - d_m[i-1]
            if abs(delta) > 0.1:
                axes[0].annotate(f'{delta:+.1f}s', (x[i], d_m[i] + d_e[i] + 0.3),
                                 ha='center', fontsize=7, color='#333')
        axes[0].set_xticks(x)
        axes[0].set_xticklabels([stack_labels.get(c, c) for c in stack_cfgs], fontsize=7)
        axes[0].set_ylabel('Avg Passenger Delay (s)'); axes[0].set_title('(a) All-Passenger Delay')
        _bar_style(axes[0])

        axes[1].bar(x, b_m, color=colors_k, alpha=0.85, edgecolor='#444', linewidth=0.5)
        axes[1].axhline(b_m[0], color=PAL['baseline'], ls='--', lw=1, alpha=0.5)
        axes[1].set_xticks(x)
        axes[1].set_xticklabels([stack_labels.get(c, c) for c in stack_cfgs], fontsize=7)
        axes[1].set_ylabel('Avg Bus Passenger Delay (s)'); axes[1].set_title('(b) Bus Delay')
        _bar_style(axes[1])

        fig.suptitle('Figure K — Mechanism Contribution (mean ± std, 5 seeds)', fontsize=10, y=1.01)
        plt.tight_layout()
        out = _os.path.join(out_dir, 'fig_component_stacking.png')
        fig.savefig(out, dpi=200, bbox_inches='tight')
        plt.close(fig)
        OUTPUT_FILES.append(out)
        print(f'  [plot] Component stacking  → {out}')

    # ══════════════════════════════════════════════════════════════════════════
    # FIG S: Demand Sensitivity
    # ══════════════════════════════════════════════════════════════════════════
    # Rows have experiment names like "NO_TSP_S_d0.85" or carry run_demand_scalar
    sens_df = df[df[_KEY].str.contains('_S_d', na=False) |
                 (df[_KEY].isin(['NO_TSP_S', 'WG_BEST_S']))]
    if len(sens_df) > 0:
        # Build grouped data: (exp_base, demand_scalar) → mean delay
        records = []
        for _, row in sens_df.iterrows():
            name = row[_KEY]
            # Extract demand scalar from name suffix if present
            import re as _re
            dm = _re.search(r'_d([\d.]+)$', name)
            ds = float(dm.group(1)) if dm else row.get('run_demand_scalar', 1.0)
            base = 'NO_TSP' if 'NO_TSP' in name else 'WG_MG_1_5'
            records.append({'base': base, 'demand': ds,
                            'delay': row.get('stats_AvgPassDelay_s', float('nan')),
                            'bus':   row.get('stats_AvgBusPassDelay_s', float('nan'))})
        if records:
            import pandas as pd
            sens_agg = pd.DataFrame(records).groupby(['base', 'demand']).mean().reset_index()

            fig, axes = plt.subplots(1, 2, figsize=(PAPER_W, PAPER_H))
            for base, col in [('NO_TSP', PAL['S_notsp']), ('WG_MG_1_5', PAL['S_wg'])]:
                sub = sens_agg[sens_agg['base'] == base].sort_values('demand')
                if len(sub) == 0:
                    continue
                axes[0].plot(sub['demand'], sub['delay'], 'o-', color=col,
                             label=base, linewidth=1.8, markersize=6)
                axes[1].plot(sub['demand'], sub['bus'],   'o-', color=col,
                             label=base, linewidth=1.8, markersize=6)

            for ax, title, ylabel in [
                (axes[0], '(a) All-Passenger Delay', 'Avg Passenger Delay (s)'),
                (axes[1], '(b) Bus Delay',            'Avg Bus Passenger Delay (s)'),
            ]:
                ax.set_xlabel('Demand Scalar'); ax.set_ylabel(ylabel)
                ax.set_title(title); ax.legend(fontsize=8)
                ax.xaxis.set_ticks(_DEMAND_SCALARS_S)
                _bar_style(ax)

            fig.suptitle('Figure S — Demand Sensitivity (mean over 5 seeds)', fontsize=10, y=1.01)
            plt.tight_layout()
            out = _os.path.join(out_dir, 'fig_demand_sensitivity.png')
            fig.savefig(out, dpi=200, bbox_inches='tight')
            plt.close(fig)
            OUTPUT_FILES.append(out)
            print(f'  [plot] Demand sensitivity  → {out}')

    # ══════════════════════════════════════════════════════════════════════════
    # LaTeX Tables
    # ══════════════════════════════════════════════════════════════════════════
    def _fmt(m, s, sfx=''):
        return f'{m:.2f} ± {s:.2f}{sfx}' if s and s > 0.005 else f'{m:.2f}{sfx}'

    def _imp_pct(m):
        v = (m - base_delay) / base_delay * 100
        return f'{v:+.1f}\\%' if abs(v) > 0.01 else '—'

    def _latex_row(cfg, row):
        lbl = cfg.replace('_', r'\_')
        d  = _fmt(row['stats_AvgPassDelay_s_mean'],    row.get('stats_AvgPassDelay_s_std', 0), 's')
        b  = _fmt(row['stats_AvgBusPassDelay_s_mean'], row.get('stats_AvgBusPassDelay_s_std', 0), 's')
        tt = _fmt(row['stats_TotalPassDelay_hrs_mean'],row.get('stats_TotalPassDelay_hrs_std', 0), 'h')
        ip = _imp_pct(row['stats_AvgPassDelay_s_mean'])
        return f'{lbl} & {d} & {b} & {tt} & {ip}'

    tables = [
        "% Auto-generated by batch_runner_paper_comparison.py",
        f"% Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    # Table M: Method comparison
    if method_cfgs:
        rows_m = []
        for c in method_cfgs:
            if c not in agg['experiment'].values: continue
            rows_m.append(_latex_row(c, agg[agg['experiment'] == c].iloc[0]))
        tables.append(r"""\begin{table}[!ht]
\caption{Method Comparison — WaveGate vs Prior TSP Approaches
         (mean $\pm$ std, 5 seeds)}\label{tab:method_comparison}
\begin{center}\small
\begin{tabular}{lrrrr}
\toprule
Method & Avg Delay (s) & Bus Delay (s) & Total Pax (h) & \%\,Imp. \\
\midrule
""" + ' \\\\\n'.join(rows_m) + r""" \\
\bottomrule
\end{tabular}
\end{center}
\end{table}""")
        tables.append("")

    # Table O: Objective ablation
    if len(obj_display) >= 3:
        rows_o = []
        for c in obj_display:
            if c not in agg['experiment'].values: continue
            rows_o.append(_latex_row(c, agg[agg['experiment'] == c].iloc[0]))
        tables.append(r"""\begin{table}[!ht]
\caption{Objective Weight Ablation (det=50\,m, $\tau_{\min}=1.5$\,s, 5 seeds)
         }\label{tab:obj_ablation_comparison}
\begin{center}\small
\begin{tabular}{lrrrr}
\toprule
Objective Weights & Avg Delay (s) & Bus Delay (s) & Total Pax (h) & \%\,Imp. \\
\midrule
""" + ' \\\\\n'.join(rows_o) + r""" \\
\bottomrule
\end{tabular}
\end{center}
\end{table}""")
        tables.append("")

    # Table K: Component stacking
    if len(stack_cfgs) >= 3:
        rows_k = []
        for c in stack_cfgs:
            if c not in agg['experiment'].values: continue
            rows_k.append(_latex_row(c, agg[agg['experiment'] == c].iloc[0]))
        tables.append(r"""\begin{table}[!ht]
\caption{Mechanism Contribution — Incremental Stacking
         (ZIG + Offset Correction + Phase Rotation, 5 seeds)}\label{tab:component_stacking}
\begin{center}\small
\begin{tabular}{lrrrr}
\toprule
Configuration & Avg Delay (s) & Bus Delay (s) & Total Pax (h) & \%\,Imp. \\
\midrule
""" + ' \\\\\n'.join(rows_k) + r""" \\
\bottomrule
\end{tabular}
\end{center}
\end{table}""")
        tables.append("")

    tex_out = _os.path.join(out_dir, 'tables_paper_comparison.tex')
    with open(tex_out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(tables))
    OUTPUT_FILES.append(tex_out)
    print(f'  [table] LaTeX tables       → {tex_out}')

    return OUTPUT_FILES


# =============================================================================
# ── Main sweep loop ───────────────────────────────────────────────────────────
# =============================================================================
if __name__ == "__main__":
    _t_start = _time.time()

    # Fresh start
    if _os.path.isfile(BATCH_RESULTS_CSV):
        _os.remove(BATCH_RESULTS_CSV)
        print(f"[PC] Deleted previous results: {_os.path.basename(BATCH_RESULTS_CSV)}")

    _br._QUIET = False

    # ── CRITICAL: override TARGET_DEMAND_NAMES to None so set_demand_scalar()
    # matches ALL GKTrafficDemand objects in the Kelvin Grove model.
    # The default in batch_runner.py is ["01d Logan Rd 2025 AM/PM"] which matches
    # zero matrices here, causing demand scaling to silently do nothing.
    _br.TARGET_DEMAND_NAMES = None
    print(f"[PC] Demand name filter: None (matches ALL GKTrafficDemand objects)")

    try:
        _rt_proj = _br.get_project_dir()
        CONTROLLER_PATH = _os.path.join(_rt_proj, "intersection_controller.py")
        RUN_CONFIG_PATH = _os.path.join(_rt_proj, "run_config.py")
        PROJECT_DIR     = _rt_proj
        _br.CONTROLLER_PATH = CONTROLLER_PATH
        _br.RUN_CONFIG_PATH = RUN_CONFIG_PATH
        _br.PROJECT_DIR     = PROJECT_DIR
        print(f"[PC] Project dir: {PROJECT_DIR}")
    except Exception as _e:
        print(f"[PC] WARNING: cannot resolve project dir: {_e}")

    # Passive junctions
    set_junctions_external_control([10157950, 11118289, 1119660, 39568])

    # ── Build full run list: fixed-demand groups + demand-sensitivity group ────
    enabled_fixed = [e for e in EXPERIMENTS_FIXED if e.get("enabled", True)]
    n_fixed = len(enabled_fixed) * len(SEEDS) * len(DEMAND_SCALARS)

    _SENS_TEMPLATES_ENABLED = [e for e in _SENSITIVITY_TEMPLATES if e.get("enabled", True)]
    n_sens = len(_SENS_TEMPLATES_ENABLED) * len(SEEDS) * len(_DEMAND_SCALARS_S)
    n_total = n_fixed + n_sens

    log("=" * 70)
    log("BATCH_RUNNER_PAPER_COMPARISON — TRB paper comprehensive comparison")
    log(f"  Groups M (method) + O (objectives) + K (stacking) + S (demand sensitivity)")
    log(f"  {len(enabled_fixed)} fixed-demand experiments × {len(SEEDS)} seeds = {n_fixed} runs")
    log(f"  {len(_SENS_TEMPLATES_ENABLED)} sensitivity templates × {len(SEEDS)} seeds × "
        f"{len(_DEMAND_SCALARS_S)} demand levels = {n_sens} runs")
    log(f"  TOTAL: {n_total} runs")
    log(f"  Results → {BATCH_RESULTS_CSV}")
    log(f"  Plots   → {PLOTS_DIR}/")
    log("Experiments:")
    for i, e in enumerate(enabled_fixed, 1):
        log(f"  [{i:>2}/{len(enabled_fixed)+len(_SENS_TEMPLATES_ENABLED)}] "
            f"Group {e.get('sweep_group','?')}  {e['name']}")
    for i, e in enumerate(_SENS_TEMPLATES_ENABLED,
                          len(enabled_fixed) + 1):
        log(f"  [{i:>2}/{len(enabled_fixed)+len(_SENS_TEMPLATES_ENABLED)}] "
            f"Group S  {e['name']}  × demand {_DEMAND_SCALARS_S}")
    log("=" * 70)

    rep          = get_first_replication()
    run_num      = 0
    failures     = []
    base_demands = {}

    # ── Fixed-demand groups (M, O, K) ─────────────────────────────────────────
    for scalar in DEMAND_SCALARS:
        try:
            set_demand_scalar(scalar, base_demands)
            print(f"[PC] Demand scalar {scalar}x applied (check log above for n_scaled)")
        except Exception as e:
            log(f"WARNING: demand scalar {scalar}: {e}")

        for exp in enabled_fixed:
            exp_name         = exp["name"]
            strategy         = exp["strategy"]
            coordinated      = exp.get("coordinated", False)
            coord_algo       = exp.get("coordination_algo", "KALMAN")
            reward_overrides = exp.get("reward_overrides", {})
            sweep_group      = exp.get("sweep_group", "?")
            is_baseline      = (strategy == "NORMAL")
            bus_predictor    = str(reward_overrides.get("BUS_PREDICTOR_TYPE",
                                                        "ADAPTIVE_KALMAN")).upper()

            try:
                set_control_mode(strategy, CONTROLLER_PATH,
                                 exp.get("active_intersections"))
            except Exception as e:
                print(f"[PC] FATAL: cannot patch strategy for {exp_name}: {e}")
                for seed in SEEDS:
                    failures.append({"experiment": exp_name, "seed": seed, "error": str(e)})
                continue

            try:
                set_coordinated(CONTROLLER_PATH, coordinated)
                set_coordination_algo(CONTROLLER_PATH, coord_algo)
            except Exception as e:
                print(f"[PC] WARNING: coord patch for {exp_name}: {e}")

            _global_reward = bool(reward_overrides.get("GLOBAL_REWARD_MODE", False))
            _numeric_ov    = {k: v for k, v in reward_overrides.items()
                              if k != "GLOBAL_REWARD_MODE"}

            _run_cfg = None if is_baseline else _build_run_cfg(reward_overrides)
            if _run_cfg is not None:
                _run_cfg.update(_numeric_ov)

            if not is_baseline:
                try:
                    set_reward_weights(CONTROLLER_PATH, _numeric_ov or None)
                except Exception as e:
                    log(f"WARNING: reward patch: {e}")

            for seed in SEEDS:
                run_num += 1
                rc = _run_cfg or {}
                print("-" * 70)
                print(f"[PC] Run {run_num}/{n_total} | Group {sweep_group} | {exp_name} | "
                      f"seed={seed} | demand={scalar:.2f}")

                set_seed(rep, seed)
                _run_cfg_write = ({"DETECTION_WINDOW_M_OVERRIDE": 50.0}
                                  if is_baseline else _run_cfg)
                write_run_config(exp_name, strategy, seed, scalar,
                                 coordinated, coord_algo, RUN_CONFIG_PATH,
                                 global_reward_mode=_global_reward,
                                 reward_cfg=_run_cfg_write,
                                 bus_predictor=bus_predictor)
                _purge_pyc(CONTROLLER_PATH)

                t0 = _time.time()
                success = True
                try:
                    run_replication(rep)
                except Exception as e:
                    success = False
                    failures.append({"experiment": exp_name, "seed": seed, "error": str(e)})
                    print(f"[PC]   EXCEPTION: {e}")

                elapsed = _time.time() - t0
                print(f"[PC]   elapsed={elapsed:.0f}s  success={success}")
                try:
                    metrics = collect_run_metrics(
                        PROJECT_DIR, strategy, seed, scalar,
                        exp_name, coordinated, elapsed, success,
                        bus_predictor=bus_predictor)
                    metrics["sweep_group"]   = sweep_group
                    metrics["sweep_Z1_weight"] = rc.get("WOBJ_ALPHA", 0.0)
                    metrics["sweep_Z2_weight"] = rc.get("WOBJ_BETA",  0.0)
                    metrics["sweep_Z3_weight"] = rc.get("WOBJ_GAMMA", 0.0)
                    metrics["sweep_min_gain_s"] = rc.get("ZIG_MIN_GAIN_S", None)
                    metrics["sweep_bargain"]   = bool(rc.get("BARGAIN_SPM_MODE", False))
                    metrics["sweep_zig_mode"]  = bool(rc.get("DCTSP_ZIG_MODE", True))
                    metrics["sweep_oc_enabled"]= bool(rc.get("OFFSET_CORRECTION_MODE", False))
                    metrics["sweep_pr_enabled"]= bool(rc.get("PHASE_ROTATION_MODE", False))
                    append_master_csv(BATCH_RESULTS_CSV, metrics)
                    print(f"[PC]   delay={metrics.get('stats_TotalPassDelay_hrs','?')}h  "
                          f"written → {_os.path.basename(BATCH_RESULTS_CSV)}")
                except Exception as e:
                    print(f"[PC]   ERROR collecting metrics: {e}")
                    failures.append({"experiment": exp_name, "seed": seed, "error": str(e)})

    # ── Demand-sensitivity group (S) ──────────────────────────────────────────
    for scalar in _DEMAND_SCALARS_S:
        try:
            set_demand_scalar(scalar, base_demands)
            print(f"[PC] Demand sensitivity scalar {scalar}x applied")
        except Exception as e:
            log(f"WARNING: demand scalar {scalar}: {e}")

        for exp_tmpl in _SENS_TEMPLATES_ENABLED:
            # Embed demand level in experiment name for unambiguous CSV rows
            exp_name_raw = exp_tmpl["name"]
            exp_name     = f"{exp_name_raw}_d{scalar:.2f}"
            strategy     = exp_tmpl["strategy"]
            coordinated  = exp_tmpl.get("coordinated", False)
            coord_algo   = exp_tmpl.get("coordination_algo", "KALMAN")
            reward_overrides = exp_tmpl.get("reward_overrides", {})
            is_baseline  = (strategy == "NORMAL")
            bus_predictor = str(reward_overrides.get("BUS_PREDICTOR_TYPE",
                                                      "ADAPTIVE_KALMAN")).upper()

            try:
                set_control_mode(strategy, CONTROLLER_PATH,
                                 exp_tmpl.get("active_intersections"))
            except Exception as e:
                print(f"[PC] FATAL: cannot patch strategy for {exp_name}: {e}")
                for seed in SEEDS:
                    failures.append({"experiment": exp_name, "seed": seed, "error": str(e)})
                continue

            try:
                set_coordinated(CONTROLLER_PATH, coordinated)
                set_coordination_algo(CONTROLLER_PATH, coord_algo)
            except Exception as e:
                print(f"[PC] WARNING: coord patch: {e}")

            _global_reward = bool(reward_overrides.get("GLOBAL_REWARD_MODE", False))
            _numeric_ov    = {k: v for k, v in reward_overrides.items()
                              if k != "GLOBAL_REWARD_MODE"}
            _run_cfg = None if is_baseline else _build_run_cfg(reward_overrides)
            if _run_cfg is not None:
                _run_cfg.update(_numeric_ov)
            if not is_baseline:
                try:
                    set_reward_weights(CONTROLLER_PATH, _numeric_ov or None)
                except Exception as e:
                    log(f"WARNING: reward patch: {e}")

            for seed in SEEDS:
                run_num += 1
                print("-" * 70)
                print(f"[PC] Run {run_num}/{n_total} | Group S | {exp_name} | "
                      f"seed={seed} | demand={scalar:.2f}")

                set_seed(rep, seed)
                _run_cfg_write = ({"DETECTION_WINDOW_M_OVERRIDE": 50.0}
                                  if is_baseline else _run_cfg)
                write_run_config(exp_name, strategy, seed, scalar,
                                 coordinated, coord_algo, RUN_CONFIG_PATH,
                                 global_reward_mode=_global_reward,
                                 reward_cfg=_run_cfg_write,
                                 bus_predictor=bus_predictor)
                _purge_pyc(CONTROLLER_PATH)

                t0 = _time.time()
                success = True
                try:
                    run_replication(rep)
                except Exception as e:
                    success = False
                    failures.append({"experiment": exp_name, "seed": seed, "error": str(e)})
                    print(f"[PC]   EXCEPTION: {e}")

                elapsed = _time.time() - t0
                print(f"[PC]   elapsed={elapsed:.0f}s  success={success}")
                try:
                    metrics = collect_run_metrics(
                        PROJECT_DIR, strategy, seed, scalar,
                        exp_name, coordinated, elapsed, success,
                        bus_predictor=bus_predictor)
                    metrics["sweep_group"]         = "S"
                    metrics["sweep_demand_scalar"]  = scalar
                    metrics["run_demand_scalar"]    = scalar
                    append_master_csv(BATCH_RESULTS_CSV, metrics)
                    print(f"[PC]   delay={metrics.get('stats_TotalPassDelay_hrs','?')}h  "
                          f"written → {_os.path.basename(BATCH_RESULTS_CSV)}")
                except Exception as e:
                    print(f"[PC]   ERROR collecting metrics: {e}")
                    failures.append({"experiment": exp_name, "seed": seed, "error": str(e)})

    # ══════════════════════════════════════════════════════════════════════════
    # ── POST-RUN: Generate all paper plots and tables ─────────────────────────
    # ══════════════════════════════════════════════════════════════════════════
    total_elapsed = _time.time() - _t_start

    print("\n" + "=" * 70)
    print(f"[PC] ALL RUNS COMPLETE: {run_num} total, {len(failures)} failures")
    print(f"[PC] Wall time: {total_elapsed/3600:.1f} h")
    if failures:
        print("[PC] FAILED RUNS:")
        for f in failures:
            print(f"     {f['experiment']} seed={f.get('seed','?')} — {f['error']}")
    print("=" * 70)

    output_files = []
    print("\n[PC] Generating paper plots and LaTeX tables...")
    try:
        output_files = _generate_paper_plots(BATCH_RESULTS_CSV, PLOTS_DIR)
    except Exception as _pe:
        print(f"[PC] ERROR in plot generation: {_pe}")
        import traceback; traceback.print_exc()

    # Also regenerate the main wavegate dashboard if wavegate CSV is present
    _wg_csv  = _os.path.join(_SCRIPT_DIR, "batch_results_wavegate.csv")
    _wg_html = _os.path.join(_SCRIPT_DIR, "wavegate_dashboard.html")
    _gen_py  = _os.path.join(_SCRIPT_DIR, "generate_dashboard.py")
    if _os.path.isfile(_wg_csv) and _os.path.isfile(_gen_py):
        print("[PC] Regenerating wavegate dashboard with combined data...")
        try:
            import importlib.util as _ilu2
            _gd_spec = _ilu2.spec_from_file_location("generate_dashboard", _gen_py)
            _gd = _ilu2.module_from_spec(_gd_spec)
            _gd_spec.loader.exec_module(_gd)
            _gd.generate(_wg_csv, _wg_html)
            output_files.append(_wg_html)
            print(f"[PC] Dashboard updated → {_wg_html}")
        except Exception as _de:
            print(f"[PC] Dashboard regeneration failed: {_de}")

    # ── Paper-ready file summary ───────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("PAPER-READY OUTPUT FILES")
    print("=" * 70)
    print(f"\n  Raw results CSV:")
    print(f"    {BATCH_RESULTS_CSV}")
    print(f"\n  Figures (include in paper with \\includegraphics):")
    for f in output_files:
        if f.endswith('.png'):
            print(f"    {f}")
    print(f"\n  LaTeX tables (copy into paper with \\input{{...}}):")
    for f in output_files:
        if f.endswith('.tex'):
            print(f"    {f}")
    if _wg_html in output_files:
        print(f"\n  Interactive dashboard:")
        print(f"    {_wg_html}")
    print(f"\n  All plots directory:")
    print(f"    {PLOTS_DIR}/")
    print("=" * 70)
    print("\nDone. Open the figures listed above to include in the TRB paper.\n")
