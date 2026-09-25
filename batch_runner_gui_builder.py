# =============================================================================
# batch_runner_gui_builder.py — desktop GUI that generates a batch_runner_gui.py
# =============================================================================
#
# Standalone tool (plain Tkinter, no extra deps) — run it with a normal desktop
# Python, NOT inside Aimsun:
#
#     python batch_runner_gui_builder.py
#
# Pick a network (KG or Logan Road), a TSP strategy, objective weights, seeds,
# TSP cycle length, and how many downstream intersections a bus detection
# should pre-arm ("connected" intersections). Click Generate and it writes
# <network>/batch_runner_gui.py — a runnable batch runner that reuses the
# network's own batch_runner.py engine (same pattern as batch_runner_wavegate.py)
# so it can be launched from Aimsun's "Run Script" menu exactly like the other
# batch_runner_*.py files already in that folder.
#
# KG and Logan Road run different versions of intersection_controller.py:
# Logan Road has the full DCTSP research catalogue (WaveGate/MARL/NashGate/
# META_TSP/MDN/BXT/MP_ECTM/SelfOrg/InvDelay/V2X, all under CONTROL_MODE=
# "DRL_DENSITY" + GLOBAL_REWARD_MODE); KG only has the base strategies
# (NORMAL/HARMONY/URTSP/REWARD_TSP/GROUP_BASED*/DYNAOPAC*). The strategy
# dropdown below only offers what the selected network's controller actually
# implements, so Generate can never write a config the controller will
# silently ignore.
# =============================================================================

import os
import re
import datetime
import tkinter as tk
from tkinter import ttk, messagebox

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# =============================================================================
# ── Strategy presets ──────────────────────────────────────────────────────────
# Each preset mirrors an experiment already proven out in batch_runner.py, so
# generated runs use the same strategy/coordination_algo/reward_overrides
# combinations the engine expects (see set_control_mode() in batch_runner.py
# for how "strategy" maps to the controller's CONTROL_MODE).
#
# weight_kind selects which objective-weight fields the GUI shows and which
# run_config keys they're written as:
#   None          — strategy has no tunable reward weights
#   "reward_abg"  — REWARD_ALPHA / REWARD_BETA / REWARD_GAMMA (bus / other-phase / side-street)
#   "wobj"        — WOBJ_ALPHA / WOBJ_BETA / WOBJ_GAMMA (Z1 delay / Z2 progression / Z3 headway)
#                   plus REWARD_MAIN_SECTION_WEIGHT / REWARD_SIDE_SECTION_WEIGHT
# =============================================================================

_BASE_PRESETS = {
    "NO_TSP": dict(label="No TSP (baseline)", strategy="NORMAL",
                   coordinated=False, coordination_algo="KALMAN",
                   weight_kind=None, reward_overrides={}),
    "HARMONY": dict(label="Harmony Search (phase-based)", strategy="HARMONY",
                     coordinated=True, coordination_algo="KALMAN",
                     weight_kind=None, reward_overrides={}),
    "URTSP": dict(label="URTSP (phase-based)", strategy="URTSP",
                   coordinated=False, coordination_algo="KALMAN",
                   weight_kind=None, reward_overrides={}),
    "REWARD_TSP": dict(label="Reward TSP (local reward, phase-based)", strategy="REWARD_TSP",
                        coordinated=True, coordination_algo="KALMAN",
                        weight_kind="reward_abg", reward_overrides={}),
    "GROUP_BASED": dict(label="Group-Based", strategy="GROUP_BASED",
                          coordinated=True, coordination_algo="KALMAN",
                          weight_kind=None, reward_overrides={}),
    "GROUP_BASED_URTSP": dict(label="Group-Based + URTSP", strategy="GROUP_BASED_URTSP",
                                coordinated=True, coordination_algo="KALMAN",
                                weight_kind=None, reward_overrides={}),
    "GROUP_BASED_HARMONY": dict(label="Group-Based + Harmony", strategy="GROUP_BASED_HARMONY",
                                  coordinated=True, coordination_algo="KALMAN",
                                  weight_kind=None, reward_overrides={}),
    "DYNAOPAC": dict(label="DynaOPAC", strategy="DYNAOPAC",
                       coordinated=True, coordination_algo="KALMAN",
                       weight_kind=None, reward_overrides={}),
    "DYNAOPAC_HARMONY": dict(label="DynaOPAC + Harmony", strategy="DYNAOPAC_HARMONY",
                               coordinated=True, coordination_algo="KALMAN",
                               weight_kind=None, reward_overrides={}),
}

_DCTSP_PRESETS = {
    "DCTSP_ZIG": dict(
        label="DCTSP - WaveGate (shockwave-optimal gating)",
        strategy="GLOBAL_REWARD", coordinated=True, coordination_algo="SHOCKWAVE",
        weight_kind="wobj",
        method_overrides={
            "DCTSP_ZIG_MODE": True,
            "ZIG_PHASE_OVERLAP_S": 0.5, "ZIG_BALANCE_FACTOR": 1.0,
            "NETWORK_FACTOR": 1.0, "NETWORK_FACTOR_DENSITY_RAMP": False,
        },
        reward_overrides={"GLOBAL_REWARD_MODE": True},
    ),
    "DCTSP_MARL": dict(
        label="DCTSP - MARL (multi-agent Q-learning, Hu et al. 2025)",
        strategy="GLOBAL_REWARD", coordinated=True, coordination_algo="KALMAN",
        weight_kind="wobj",
        method_overrides={
            "DCTSP_GREEN_REALLOC_MODE": True, "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            "DCTSP_W_H": 0.50, "DCTSP_CAR_WEIGHT": 1.00,
        },
        reward_overrides={"GLOBAL_REWARD_MODE": True},
    ),
    "DCTSP_BARGAIN_SPM": dict(
        label="DCTSP - NashGate (Bargaining SPM)",
        strategy="GLOBAL_REWARD", coordinated=True, coordination_algo="SHOCKWAVE",
        weight_kind="wobj",
        method_overrides={
            "BARGAIN_SPM_MODE": True,
            "DCTSP_GREEN_REALLOC_MODE": True, "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            "BG_DET_LVL_IMM_S": 4.0, "BG_DET_LVL_NEAR_S": 12.0, "BG_DET_LVL_FAR_S": 24.0,
            "BG_BUS_W_IMM": 1.6, "BG_BUS_W_NEAR": 1.35, "BG_BUS_W_FAR": 1.10, "BG_BUS_W_VFAR": 0.95,
            "BG_SPM_RISK_WEIGHT": 1.8, "BG_EQ_FAIRNESS_WEIGHT": 0.55,
            "BG_MIN_BUS_DELAY_S": 5.0, "BG_MIN_GAIN_S": 5.0, "BG_CASCADE_MULT": 2.0, "BG_MB_WEIGHT": 0.30,
            "DCTSP_CONGESTION_GATE": True, "DCTSP_CONGESTION_GATE_FRACTION": 0.75,
        },
        reward_overrides={"GLOBAL_REWARD_MODE": True},
    ),
    "DCTSP_META_TSP": dict(
        label="DCTSP - META_TSP (system-optimal, lateness-adaptive)",
        strategy="GLOBAL_REWARD", coordinated=True, coordination_algo="SHOCKWAVE",
        weight_kind="wobj",
        method_overrides={
            "META_TSP_MODE": True,
            "META_DT_S": 1.0, "META_BASE_BUS_WEIGHT": 1.0, "META_HW_SENSITIVITY": 1.5,
            "META_HW_REF_S": 60.0, "META_MIN_THRESHOLD_PAX_S": 18.0,
            "META_BALANCE_FACTOR": 0.85, "META_MIN_BUS_DELAY_S": 8.0,
            "META_OC_WEIGHT": 0.4, "META_CAR_OCC": 1.2,
        },
        reward_overrides={"GLOBAL_REWARD_MODE": True},
    ),
    "DCTSP_MDN": dict(
        label="DCTSP - MDN (movement-wise delay distribution, Zhu et al. 2026)",
        strategy="GLOBAL_REWARD", coordinated=True, coordination_algo="SHOCKWAVE",
        weight_kind="wobj",
        method_overrides={
            "MDN_DELAY_MODE": True,
            "MDN_DDT_POWER": 0.5, "MDN_N_COMPONENTS": 3, "MDN_EPSILON": 0.5,
        },
        reward_overrides={"GLOBAL_REWARD_MODE": True},
    ),
    "DCTSP_BXT": dict(
        label="DCTSP - BXT (CTM multi-agent Q-learning, Chanloha et al. 2014)",
        strategy="GLOBAL_REWARD", coordinated=True, coordination_algo="KALMAN",
        weight_kind="wobj",
        method_overrides={
            "BXT_MODE": True,
            "BXT_DT_S": 1.0, "BXT_EPSILON": 0.05, "BXT_ALPHA": 0.05, "BXT_GAMMA": 0.01,
            "BXT_CAR_OCC": 1.2, "BXT_BALANCE_FACTOR": 1.1,
        },
        reward_overrides={"GLOBAL_REWARD_MODE": True},
    ),
    "DCTSP_MP_ECTM": dict(
        label="DCTSP - MP-ECTM (math programming + enhanced CTM)",
        strategy="GLOBAL_REWARD", coordinated=True, coordination_algo="KALMAN",
        weight_kind="wobj",
        method_overrides={
            "MP_ECTM_MODE": True,
            "MP_ECTM_DT_S": 1.0, "MP_ECTM_MIN_EXT_S": 3.0, "MP_ECTM_MAX_EXT_S": 8.0,
            "MP_ECTM_CAR_OCC": 1.6, "MP_ECTM_BALANCE_FACTOR": 0.75,
        },
        reward_overrides={"GLOBAL_REWARD_MODE": True},
    ),
    "DCTSP_CELLQLEARN_DP": dict(
        label="DCTSP - CellQ-Learn DP (V2X DP-coordinated TSP, Huang & Hsu 2025)",
        strategy="GLOBAL_REWARD", coordinated=True, coordination_algo="KALMAN",
        weight_kind="wobj",
        method_overrides={
            "CELLQLEARN_DP_MODE": True,
            "CELLQLEARN_DP_DT_S": 1.0, "CELLQLEARN_DP_HORIZON_S": 90.0,
            "CELLQLEARN_DP_STAGE_S": 15.0, "CELLQLEARN_DP_COORD_WEIGHT": 0.22,
            "CELLQLEARN_DP_CAR_OCC": 1.2, "CELLQLEARN_DP_BALANCE_FACTOR": 1.0,
        },
        reward_overrides={"GLOBAL_REWARD_MODE": True},
    ),
    "DCTSP_SELFORG": dict(
        label="DCTSP - Self-Organizing (Cesme & Furth 2014)",
        strategy="GLOBAL_REWARD", coordinated=True, coordination_algo="KALMAN",
        weight_kind="wobj",
        method_overrides={
            "REWARD_SELFORG_MODE": True,
            "SELFORG_MIN_BUS_DELAY_S": 12.0, "SELFORG_BALANCE_FACTOR": 0.85,
            "SELFORG_MAX_SE_S": 15.0, "SELFORG_MIN_SE_S": 5.0,
            "SELFORG_SE_FRACTION": 0.70, "SELFORG_PHASE_OVERLAP_S": 0.0,
        },
        reward_overrides={"GLOBAL_REWARD_MODE": True},
    ),
    "DCTSP_INV_DELAY": dict(
        label="DCTSP - Inverse Delay",
        strategy="GLOBAL_REWARD", coordinated=True, coordination_algo="KALMAN",
        weight_kind="wobj",
        method_overrides={
            "REWARD_INV_DELAY_MODE": True,
            "INV_DELAY_EPSILON": 0.5, "INV_DELAY_CAR_WEIGHT": 1.2, "INV_DELAY_MIN_DELAY_S": 3.0,
        },
        reward_overrides={"GLOBAL_REWARD_MODE": True},
    ),
    "DCTSP_V2X": dict(
        label="DCTSP - V2X / BOCS crowding-aware",
        strategy="GLOBAL_REWARD", coordinated=True, coordination_algo="KALMAN",
        weight_kind="wobj",
        method_overrides={
            "REWARD_V2X_MODE": True,
            "V2X_MAX_BUS_OCC": 40.0, "V2X_CROWDING_SCALE": 10.0, "V2X_EPSILON": 0.5,
            "V2X_MIN_DELAY_S": 8.0, "V2X_BALANCE_FACTOR": 0.50,
        },
        reward_overrides={"GLOBAL_REWARD_MODE": True},
    ),
}

# =============================================================================
# Signal Sequencing presets — phase-adjustment-only TSP sweep (from
# batch_runner_signal_sequencing.py). Three action families:
#   SWAPS — phase-order changes only (phase rotation + wrong-phase GR cut)
#   TIMES — phase-duration changes only (net-zero green reallocation)
#   BOTH  — swaps + times together
# Each at three frequencies (X1/X2/X3 = 1/2/3 interventions per cycle).
# Strategy: CellQLearn / BXT (CTM Q-Learning).
# GE and phase insertion are disabled — phase adjustment only.
# Objective: balanced Z1+Z2+Z3 (WOBJ_ALPHA = WOBJ_BETA = WOBJ_GAMMA = 1/3),
# the same weighted objective as TARGET_Z123_BALANCED — NOT pure-Z1 total
# passenger delay.  Using the balanced objective here keeps the X1/X2/X3
# frequency comparison on identical objective terms (Z1 delay + Z2 progression
# + Z3 headway/lateness), so the number of interventions per cycle is the only
# thing that differs between jobs.
# =============================================================================
_SS_BASE = {
    # Mode flags — CellQLearn / BXT (CTM Q-Learning)
    "GLOBAL_REWARD_MODE": True,
    "BARGAIN_SPM_MODE": False,
    "DCTSP_ZIG_MODE": True,
    "META_TSP_MODE": False,
    "MDN_DELAY_MODE": False,
    "HS_EXT_MODE": False,
    "DCTSP_GREEN_REALLOC_MODE": True,
    "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
    "BUS_PREDICTOR_TYPE": "ADAPTIVE_KALMAN",
    "ZIG_BALANCE_FACTOR": 1.0,
    "NETWORK_FACTOR": 1.0,
    "NETWORK_FACTOR_DENSITY_RAMP": False,
    "ZIG_PHASE_OVERLAP_S": 0.5,
    "ZIG_MIN_GAIN_S": 1.0,
    "ZIG_DE_POP": 12,
    "ZIG_DE_ITER": 30,
    "ZIG_DE_F": 0.8,
    "ZIG_DE_CR": 0.9,
    "WOBJ_ALPHA": round(1 / 3, 6),
    "WOBJ_BETA":  round(1 / 3, 6),
    "WOBJ_GAMMA": round(1 / 3, 6),
    "WOBJ_Z1_SCALE": 3000000.0,
    "WOBJ_Z2_SCALE": 7500.0,
    "WOBJ_Z3_SCALE": 12000.0,
    "DETECTION_WINDOW_M_OVERRIDE": 50.0,
    "ZIG_ENABLE_GE": False,
    "ZIG_ENABLE_INS": False,
}
_SS_FAMILY_OVERRIDES = {
    "SWAPS": {"ZIG_ENABLE_SEQ": True,  "ZIG_ENABLE_GR": False,
              "PHASE_ROTATION_MODE": True},
    "TIMES": {"ZIG_ENABLE_SEQ": False, "ZIG_ENABLE_GR": True,
              "PHASE_ROTATION_MODE": False},
    "BOTH":  {"ZIG_ENABLE_SEQ": True,  "ZIG_ENABLE_GR": True,
              "PHASE_ROTATION_MODE": True},
}
_SS_FREQ_OVERRIDES = {
    "X1": {"TSP_CYCLE_LENGTH_OVERRIDE_S": 135.0, "PHASE_SEQ_MAX_PER_CYCLE": 1},
    "X2": {"TSP_CYCLE_LENGTH_OVERRIDE_S":  67.5, "PHASE_SEQ_MAX_PER_CYCLE": 2},
    "X3": {"TSP_CYCLE_LENGTH_OVERRIDE_S":  45.0, "PHASE_SEQ_MAX_PER_CYCLE": 3},
}

_SS_PRESETS = {}
for _fam_name, _fam_ov in _SS_FAMILY_OVERRIDES.items():
    for _freq_name, _freq_ov in _SS_FREQ_OVERRIDES.items():
        _mo = dict(_SS_BASE)
        _mo.update(_fam_ov)
        _mo.update(_freq_ov)
        _key = f"SS_{_fam_name}_{_freq_name}"
        _SS_PRESETS[_key] = dict(
            label=f"Signal Seq — {_fam_name} phase adj, {_freq_name} freq ("
                  f"{_freq_ov['TSP_CYCLE_LENGTH_OVERRIDE_S']:g}s window, "
                  f"{_freq_ov['PHASE_SEQ_MAX_PER_CYCLE']} per cycle)",
            strategy="GLOBAL_REWARD", coordinated=True, coordination_algo="SHOCKWAVE",
            weight_kind=None,
            method_overrides=_mo,
            reward_overrides={"GLOBAL_REWARD_MODE": True},
        )

SS_BATCH = ["NO_TSP",
            "SS_SWAPS_X1", "SS_SWAPS_X2", "SS_SWAPS_X3",
            "SS_TIMES_X1", "SS_TIMES_X2", "SS_TIMES_X3",
            "SS_BOTH_X1",  "SS_BOTH_X2",  "SS_BOTH_X3"]

# =============================================================================
# Paper strategy presets (shared_tsp_engine/TSP_Paper_refresh.tex, Sections
# "Solution Methods" + "Batch Experiment Design"). One preset per solution-
# method subsection, keyed/labelled after its heading so the experiment name
# (and therefore the dashboard label) matches the paper:
#
#   NoPriority — NO_TSP      : baseline fixed-time control
#   Method 0   — CENTRALISED : Centralised Per-Second Phase Controller
#   Method I   — CPD_QL      : Tabular Q-Learning        (cfg: DCTSP_MARL)
#   Method II  — HSLWR       : Harmony Search with LWR   (cfg: DCTSP_ZIG / WaveGate)
#   Method III — CTMGS       : Exhaustive Grid Search    (cfg: DCTSP_MP_ECTM / CellSearch)
#   Method IV  — CELLQLEARN     : CTM Q-Learning                 (cfg: DCTSP_BXT)
#   Method V   — NASHHS         : Nash Bargaining with HS        (cfg: DCTSP_BARGAIN_SPM / NashGate)
#   Method VI  — CELLQLEARN_DP  : CellQ-Learn with DP (V2X DP)   (cfg: CELLQLEARN_DP)
#
# ALL presets are Pareto-based and weight-free (paper Section "Pareto
# Formulation with Throughput Constraint"): no WOBJ_ALPHA/BETA/GAMMA anywhere.
# Candidate actions are committed via the engine's shared selection layer --
# Z4 throughput gate (hard constraint on net corridor vehicle-time; vehicles
# serviced are never traded away) + Pareto dominance filter + net-pax-s pick.
# coordination_algo is SHOCKWAVE for coordinated GLOBAL_REWARD presets because
# batch_runner.py force-overrides KALMAN->SHOCKWAVE for those at run time.
# =============================================================================
_PARETO_BASE = {
    "GLOBAL_REWARD_MODE": True,
    # Paper methods decide via their OWN reward models (mode-commits-own-action
    # in the engine).  The shared weight-free Pareto layer is disabled so it
    # never overrides the method's own candidate; methods without a dedicated
    # mode generator (CPD_QL, CENTRALISED) fall back to the standard scalar
    # argmax instead of the Pareto ideal-point compromise.
    "PARETO_SELECTION_MODE": False,
    "Z4_CONSTRAINT_MODE": True,
    "Z4_TOLERANCE_VEH_S": 90.0,
    "REWARD_FUTURE_HORIZON_CYCLES": 1.0,
    "REWARD_FUTURE_DEBT_GAIN": 0.35,
    "REWARD_FUTURE_OFFSET_GAIN": 0.20,
}


def _paper_preset(label, method_overrides, coordinated=True):
    return dict(label=label, strategy="GLOBAL_REWARD", coordinated=coordinated,
                coordination_algo="SHOCKWAVE", weight_kind=None,
                method_overrides=method_overrides,
                reward_overrides=dict(_PARETO_BASE))


_PAPER_STRATEGY_PRESETS = {
    "CENTRALISED": _paper_preset(
        "Paper Method 0 — Centralised Per-Second Phase Controller",
        {
            "CENTRALIZED_MODE": True,
            "CENTRALIZED_INTERVAL_S": 1.0,
        }),
    "CPD_QL": _paper_preset(
        "Paper Method I — Tabular Q-Learning (CPD-QL)",
        {
            "REWARD_INV_DELAY_MODE": False,
            "DCTSP_GREEN_REALLOC_MODE": True, "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            "DCTSP_W_H": 0.50, "DCTSP_CAR_WEIGHT": 1.00,
        }),
    "HSLWR": _paper_preset(
        "Paper Method II — Harmony Search with LWR (HSLWR / WaveGate)",
        {
            "DCTSP_ZIG_MODE": True,
            "ZIG_PHASE_OVERLAP_S": 0.5,
            "ZIG_BALANCE_FACTOR": 1.0,
            "NETWORK_FACTOR": 1.0, "NETWORK_FACTOR_DENSITY_RAMP": False,
        }),
    "CTMGS": _paper_preset(
        "Paper Method III — Exhaustive Grid Search (CTMGS / CellSearch)",
        {
            "MP_ECTM_MODE": True,
            "MP_ECTM_DT_S": 1.0,
            "MP_ECTM_MIN_EXT_S": 3.0, "MP_ECTM_MAX_EXT_S": 8.0,
            "MP_ECTM_CAR_OCC": 1.6, "MP_ECTM_BALANCE_FACTOR": 0.75,
        }),
    "CELLQLEARN": _paper_preset(
        "Paper Method IV — CTM Q-Learning (CellQLearn)",
        {
            "BXT_MODE": True,
            "BXT_DT_S": 1.0,
            "BXT_EPSILON": 0.02, "BXT_ALPHA": 0.05, "BXT_GAMMA": 0.01,
            "BXT_CAR_OCC": 1.2, "BXT_BALANCE_FACTOR": 1.1,
        }),
    "CELLQLEARN_DP": _paper_preset(
        "Paper Method VI — CellQ-Learn with Dynamic Programming (V2X DP)",
        {
            "CELLQLEARN_DP_MODE": True,
            "CELLQLEARN_DP_DT_S": 1.0,
            "CELLQLEARN_DP_HORIZON_S": 90.0,
            "CELLQLEARN_DP_STAGE_S": 15.0,
            "CELLQLEARN_DP_COORD_WEIGHT": 0.22,
            "CELLQLEARN_DP_CAR_OCC": 1.2,
            "CELLQLEARN_DP_BALANCE_FACTOR": 1.0,
        }),
    "NASHHS": _paper_preset(
        "Paper Method V — Nash Bargaining with Harmony Search (NashHS / NashGate)",
        {
            "BARGAIN_SPM_MODE": True,
            "DCTSP_GREEN_REALLOC_MODE": True, "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            "BG_DET_LVL_IMM_S": 4.0, "BG_DET_LVL_NEAR_S": 12.0, "BG_DET_LVL_FAR_S": 24.0,
            "BG_BUS_W_IMM": 1.6, "BG_BUS_W_NEAR": 1.35, "BG_BUS_W_FAR": 1.10,
            "BG_BUS_W_VFAR": 0.95,
            "BG_SPM_RISK_WEIGHT": 1.8, "BG_EQ_FAIRNESS_WEIGHT": 0.55,
            "BG_MIN_BUS_DELAY_S": 5.0, "BG_MIN_GAIN_S": 5.0,
            "BG_CASCADE_MULT": 2.0, "BG_MB_WEIGHT": 0.30,
            "DCTSP_CONGESTION_GATE": True, "DCTSP_CONGESTION_GATE_FRACTION": 0.75,
        }),
}

# The paper's full strategy-comparison batch in table order: NoPriority
# baseline + all six methods, one experiment each.
PAPER_STRATEGY_BATCH = ["NO_TSP", "CENTRALISED", "CPD_QL", "HSLWR",
                        "CTMGS", "CELLQLEARN", "CELLQLEARN_DP", "NASHHS"]

# =============================================================================
# Objective-target presets — one experiment per corridor objective, mirroring
# the proven WG_NO_Z*/WG_Z1ONLY ablation pattern in batch_runner_wavegate.py
# (WaveGate/ZIG is the canonical WOBJ-weighted strategy):
#
#   Z1 — weighted passenger delay      (WOBJ_ALPHA)
#   Z2 — progression / bandwidth       (WOBJ_BETA)
#   Z3 — bus headway / lateness        (WOBJ_GAMMA)
#
# Z4 (total corridor travel time / vehicles serviced) is deliberately NOT a
# targetable weight: repo policy is that Z4 is a HARD feasibility constraint
# on every TSP experiment (epsilon-constraint method, engine's
# _pareto_select_candidates). enforce_z4_hard_constraint() below re-asserts
# it at generation time no matter what the preset or user overrides say.
# =============================================================================
def _target_preset(label, alpha, beta, gamma):
    return dict(label=label, strategy="GLOBAL_REWARD", coordinated=True,
                coordination_algo="SHOCKWAVE", weight_kind=None,
                method_overrides={
                    "DCTSP_ZIG_MODE": True,
                    "ZIG_PHASE_OVERLAP_S": 0.5,
                    "ZIG_BALANCE_FACTOR": 1.0,
                    "NETWORK_FACTOR": 1.0,
                    "NETWORK_FACTOR_DENSITY_RAMP": False,
                    "WOBJ_Z1_SCALE": 3000000.0,
                    "WOBJ_Z2_SCALE": 7500.0,
                    "WOBJ_Z3_SCALE": 12000.0,
                    "WOBJ_ALPHA": alpha,
                    "WOBJ_BETA": beta,
                    "WOBJ_GAMMA": gamma,
                    "REWARD_FUTURE_HORIZON_CYCLES": 1.0,
                    "REWARD_FUTURE_DEBT_GAIN": 0.35,
                    "REWARD_FUTURE_OFFSET_GAIN": 0.20,
                },
                reward_overrides={
                    "GLOBAL_REWARD_MODE": True,
                    "PARETO_SELECTION_MODE": False,
                    "Z4_CONSTRAINT_MODE": True,
                    "Z4_TOLERANCE_VEH_S": 300.0,
                })


_OBJECTIVE_TARGET_PRESETS = {
    "TARGET_Z1_DELAY": _target_preset(
        "Objective target — Z1 passenger delay only (Z4 hard constraint)",
        1.0, 0.0, 0.0),
    "TARGET_Z2_PROGRESSION": _target_preset(
        "Objective target — Z2 progression/bandwidth only (Z4 hard constraint)",
        0.0, 1.0, 0.0),
    "TARGET_Z3_HEADWAY": _target_preset(
        "Objective target — Z3 bus headway/lateness only (Z4 hard constraint)",
        0.0, 0.0, 1.0),
    "TARGET_Z123_BALANCED": _target_preset(
        "Objective target — balanced Z1+Z2+Z3 (Z4 hard constraint)",
        round(1 / 3, 6), round(1 / 3, 6), round(1 / 3, 6)),
}

# Objective-targeting batch in objective order: NO_TSP baseline + one
# experiment per targeted objective + the balanced reference.
OBJECTIVE_TARGET_BATCH = ["NO_TSP", "TARGET_Z1_DELAY", "TARGET_Z2_PROGRESSION",
                          "TARGET_Z3_HEADWAY", "TARGET_Z123_BALANCED"]


def objective_weight_overrides(target_key):
    """Return ONLY the objective-weight (WOBJ) overrides of a target preset.

    The full objective-target presets also carry method-changing flags
    (DCTSP_ZIG_MODE, ZIG_*, NETWORK_FACTOR*) because they are built for the
    WaveGate/ZIG strategy. When a paper method is swept across objectives
    those flags MUST NOT leak in — otherwise every experiment silently becomes
    a method+ZIG hybrid instead of the pure paper method. This helper extracts
    just the WOBJ weights + normalisation scales the Pareto selection layer
    (engine `_pareto_select_candidates`) actually consumes.
    """
    preset = _OBJECTIVE_TARGET_PRESETS.get(target_key)
    if preset is None:
        return {}
    mo = preset.get("method_overrides") or {}
    return {k: v for k, v in mo.items() if k.startswith("WOBJ_")}

# ── Assign method key to every preset ─────────────────────────────────────
for _presets_dict in (_BASE_PRESETS, _DCTSP_PRESETS, _SS_PRESETS,
                       _PAPER_STRATEGY_PRESETS, _OBJECTIVE_TARGET_PRESETS):
    for key, preset in _presets_dict.items():
        preset["method"] = key

NETWORKS = {
    "logan_road_new": dict(label="Logan Road", dir_name="logan_road_new",
                            presets={**_BASE_PRESETS, **_DCTSP_PRESETS,
                                     **_SS_PRESETS,
                                     **_PAPER_STRATEGY_PRESETS,
                                     **_OBJECTIVE_TARGET_PRESETS},
                            supports_cycle_length=True),
    "kg": dict(label="KG", dir_name="kg",
               presets={**_BASE_PRESETS, **_DCTSP_PRESETS,
                        **_SS_PRESETS,
                        **_PAPER_STRATEGY_PRESETS, **_OBJECTIVE_TARGET_PRESETS},
               supports_cycle_length=False),
}


def enforce_z4_hard_constraint(experiments):
    """Repo policy: Z4 (corridor throughput) is a hard constraint, never a
    tradeable objective. Force Z4_CONSTRAINT_MODE=True on every TSP
    experiment regardless of preset/user overrides; NORMAL (no-TSP) baselines
    are left untouched since no TSP action can fire there anyway."""
    for exp in experiments:
        if exp.get("strategy") == "NORMAL":
            continue
        ov = dict(exp.get("reward_overrides") or {})
        ov["Z4_CONSTRAINT_MODE"] = True
        ov.setdefault("Z4_TOLERANCE_VEH_S", 300.0)
        exp["reward_overrides"] = ov
    return experiments

WEIGHT_FIELDS = {
    "reward_abg": [
        ("REWARD_ALPHA", "Bus weight (REWARD_ALPHA)", 1.0),
        ("REWARD_BETA",  "Other-phase weight (REWARD_BETA)", 1.0),
        ("REWARD_GAMMA", "Side-street weight (REWARD_GAMMA)", 1.0),
    ],
    "wobj": [
        ("WOBJ_ALPHA", "Z1 - passenger delay weight (WOBJ_ALPHA)", 0.333333),
        ("WOBJ_BETA",  "Z2 - progression/bandwidth weight (WOBJ_BETA)", 0.333333),
        ("WOBJ_GAMMA", "Z3 - bus headway weight (WOBJ_GAMMA)", 0.333333),
    ],
}


def _sanitize_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", name.strip())
    return name.strip("_").upper() or "GUI_RUN"


def _parse_num_list(text: str, cast):
    out = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(cast(part))
    if not out:
        raise ValueError("list is empty")
    return out


# =============================================================================
# ── Generated-file template ───────────────────────────────────────────────────
# Mirrors the established pattern in batch_runner_wavegate.py: load the
# network's own batch_runner.py for its helper functions (patch/run/collect),
# then drive a small local EXPERIMENTS x SEEDS x DEMAND_SCALARS loop so this
# file writes its own batch_results_gui.csv without touching the main batch's
# output.
# =============================================================================

_TEMPLATE = '''# =============================================================================
# batch_runner_{output_tag}.py — GENERATED by batch_runner_gui_builder.py on {timestamp}
# =============================================================================
# Do not hand-edit the EXPERIMENTS / SEEDS / DEMAND_SCALARS block below —
# re-run batch_runner_gui_builder.py and Generate again instead, so this file
# stays reproducible from the GUI settings that produced it.
#
# Run from Aimsun's "Run Script" menu (or the Python console inside Aimsun),
# same as batch_runner.py / batch_runner_wavegate.py in this folder.
# =============================================================================

import os as _os
import sys as _sys
import time as _time
import importlib.util as _ilu
from PyANGKernel import GKSystem

# __file__ is not defined when Aimsun exec's the script in headless/batch
# mode, so fall back to the active model's project directory.
try:
    _SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))
except NameError:
    _model = GKSystem.getSystem().getActiveModel()
    _SCRIPT_DIR = _model.getDocumentDirectory().absolutePath()

if _SCRIPT_DIR not in _sys.path:
    _sys.path.insert(0, _SCRIPT_DIR)

# ── Shared infrastructure — imported from this folder's batch_runner.py ──────
_br_path = _os.path.join(_SCRIPT_DIR, "batch_runner.py")
_spec = _ilu.spec_from_file_location("_br_gui", _br_path)
_br = _ilu.module_from_spec(_spec)
_sys.modules["_br_gui"] = _br
try:
    _spec.loader.exec_module(_br)
except SystemExit:
    pass

log = _br.log
set_control_mode = _br.set_control_mode
set_coordinated = _br.set_coordinated
set_coordination_algo = _br.set_coordination_algo
set_seed = _br.set_seed
set_reward_weights = _br.set_reward_weights
write_run_config = _br.write_run_config
collect_run_metrics = _br.collect_run_metrics
append_master_csv = _br.append_master_csv
write_core_output = _br.write_core_output
get_first_replication = _br.get_first_replication
run_replication = _br.run_replication
_purge_pyc = _br._purge_pyc
set_demand_scalar = _br.set_demand_scalar
_set_logging = _br._set_logging

CONTROLLER_PATH = _br.CONTROLLER_PATH
RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
PROJECT_DIR = _br.PROJECT_DIR

BATCH_RESULTS_CSV = _os.path.join(_SCRIPT_DIR, "{results_csv_name}")
CORE_OUTPUT_PATH = _os.path.join(_SCRIPT_DIR, "{core_output_name}")

# =============================================================================
# ── GUI-configured run definition ─────────────────────────────────────────────
# =============================================================================
SEEDS = {seeds!r}
DEMAND_SCALARS = {scalars!r}

EXPERIMENTS = {experiments}

if __name__ == "__main__":
    try:
        _rt_proj = _br.get_project_dir()
        CONTROLLER_PATH = _os.path.join(_rt_proj, "intersection_controller.py")
        RUN_CONFIG_PATH = _os.path.join(_rt_proj, "run_config.py")
        PROJECT_DIR = _rt_proj
        _br.CONTROLLER_PATH = CONTROLLER_PATH
        _br.RUN_CONFIG_PATH = RUN_CONFIG_PATH
        _br.PROJECT_DIR = PROJECT_DIR
    except Exception as _e:
        print(f"[GUI] WARNING: could not resolve project dir from model: {{_e}} — using script dir")

    enabled = [e for e in EXPERIMENTS if e.get("enabled", True)]
    n_total = len(enabled) * len(SEEDS) * len(DEMAND_SCALARS)

    # Start every run of this generated script with a clean results file.
    # The results CSV and core output are append-only across
    # invocations, so without this, rows from long-past experiment lists
    # (renamed/deleted/failed experiments from a previous Generate) linger
    # forever and end up mixed into the dashboard alongside this run's data.
    # Archived (renamed), never deleted -- old rows stay recoverable on disk.
    _archive_ts = _time.strftime("%Y%m%d_%H%M%S")
    for _stale in (BATCH_RESULTS_CSV, CORE_OUTPUT_PATH):
        try:
            if _os.path.isfile(_stale):
                _base, _ext = _os.path.splitext(_stale)
                _archived = f"{{_base}}_archive_{{_archive_ts}}{{_ext}}"
                _os.rename(_stale, _archived)
                print(f"[GUI] Archived previous results -> {{_os.path.basename(_archived)}}")
        except Exception as _e:
            print(f"[GUI] WARNING: could not archive {{_stale}}: {{_e}}")

    log("=" * 68)
    log("BATCH_RUNNER_{output_tag} — generated from batch_runner_gui_builder.py")
    log(f"  {{len(enabled)}} experiment(s)  x  {{len(SEEDS)}} seed(s)  x  {{len(DEMAND_SCALARS)}} scalar(s)  =  {{n_total}} runs")
    for i, e in enumerate(enabled, 1):
        log(f"  [{{i}}/{{len(enabled)}}] {{e['name']}}  method={{e.get('method', '-')}}  strategy={{e['strategy']}}  coordinated={{e['coordinated']}}")
    log(f"  Results -> {{BATCH_RESULTS_CSV}}")
    log("=" * 68)

    rep = get_first_replication()
    run_num = 0
    failures = []
    base_demands = {{}}

    # ── Auto-calibrated objective scales — measured from the first successful
    # baseline (NO_TSP) seed so each normalised Z* starts at ~1.0 regardless of
    # network, demand, or simulation duration. Once calibrated, all subsequent
    # non-baseline experiments use these values instead of hardcoded defaults.
    _baseline_scales = None

    # Silence VERBOSE/LOG_*/heartbeat/status-dashboard console spam for the
    # duration of the batch, same as batch_runner.py's full sweep does.
    # Restored in `finally` below so interactive use afterward is normal again.
    try:
        _set_logging(CONTROLLER_PATH, enabled=False)
    except Exception as e:
        log(f"WARNING: could not disable controller logging: {{e}}")

    try:
        for scalar in DEMAND_SCALARS:
            try:
                set_demand_scalar(scalar, base_demands)
            except Exception as e:
                log(f"WARNING: demand scalar {{scalar}}: {{e}}")

            for exp in enabled:
                exp_name = exp["name"]
                strategy = exp["strategy"]
                coordinated = exp.get("coordinated", False)
                coord_algo = exp.get("coordination_algo", "KALMAN")
                reward_overrides = exp.get("reward_overrides", {{}}) or {{}}
                method_overrides = exp.get("method_overrides", {{}}) or {{}}
                reward_overrides = dict(reward_overrides)
                reward_overrides.update(method_overrides)
                is_baseline = (strategy == "NORMAL")
                # Z4 hard-constraint policy: re-asserted at run time so even a
                # hand-edited EXPERIMENTS block cannot disable the throughput gate.
                if not is_baseline:
                    reward_overrides["Z4_CONSTRAINT_MODE"] = True
                    reward_overrides.setdefault("Z4_TOLERANCE_VEH_S", 300.0)
                    # Auto-calibrated objective scales from the baseline run so
                    # alpha/beta/gamma weights are directly interpretable:
                    #   Z*_normalised = Z*_raw_per_hour / Z*_SCALE  ≈  1.0 at baseline
                    if _baseline_scales is not None:
                        for _sk, _sv in _baseline_scales.items():
                            reward_overrides.setdefault(_sk, _sv)
                bus_predictor = str(reward_overrides.get("BUS_PREDICTOR_TYPE", "ADAPTIVE_KALMAN")).upper()

                try:
                    set_control_mode(strategy, CONTROLLER_PATH, exp.get("active_intersections"))
                except Exception as e:
                    print(f"[GUI] FATAL: cannot patch strategy for {{exp_name}}: {{e}}")
                    for seed in SEEDS:
                        failures.append({{"experiment": exp_name, "seed": seed, "error": str(e)}})
                    continue

                try:
                    set_coordinated(CONTROLLER_PATH, coordinated)
                    set_coordination_algo(CONTROLLER_PATH, coord_algo)
                except Exception as e:
                    print(f"[GUI] WARNING: coord patch for {{exp_name}}: {{e}}")

                _global_reward = bool(reward_overrides.get("GLOBAL_REWARD_MODE", False))
                _numeric_ov = {{k: v for k, v in reward_overrides.items() if k != "GLOBAL_REWARD_MODE"}}
                _run_cfg = None if (is_baseline and not _numeric_ov) else (_numeric_ov or None)

                if not is_baseline:
                    try:
                        set_reward_weights(CONTROLLER_PATH, _numeric_ov or None)
                    except Exception as e:
                        log(f"WARNING: reward patch: {{e}}")

                for seed in SEEDS:
                    run_num += 1
                    print("-" * 68)
                    print(f"[GUI] Run {{run_num}}/{{n_total}} | {{exp_name}} | seed={{seed}} | scalar={{scalar}}")

                    set_seed(rep, seed)
                    write_run_config(exp_name, strategy, seed, scalar,
                                     coordinated, coord_algo, RUN_CONFIG_PATH,
                                     global_reward_mode=_global_reward,
                                     reward_cfg=_run_cfg,
                                     bus_predictor=bus_predictor,
                                     results_csv_name=_os.path.basename(BATCH_RESULTS_CSV))
                    _purge_pyc(CONTROLLER_PATH)

                    t0 = _time.time()
                    success = True
                    try:
                        run_replication(rep)
                    except Exception as e:
                        success = False
                        failures.append({{"experiment": exp_name, "seed": seed, "error": str(e)}})
                        print(f"[GUI]   EXCEPTION during simulation: {{e}}")

                    elapsed = _time.time() - t0
                    print(f"[GUI]   elapsed={{elapsed:.0f}}s  success={{success}}")
                    try:
                        metrics = collect_run_metrics(
                            PROJECT_DIR, strategy, seed, scalar,
                            exp_name, coordinated, elapsed, success,
                            bus_predictor=bus_predictor)
                        append_master_csv(BATCH_RESULTS_CSV, metrics)
                        write_core_output(CORE_OUTPUT_PATH, metrics, reward_overrides)
                        # Auto-calibrate objective scales from the first
                        # successful baseline seed so normalised Z* values
                        # start at ~1.0 regardless of network or demand.
                        if is_baseline and _baseline_scales is None and success:
                            _sim_h = max(float(metrics.get("stats_SimDuration_hrs", 1.0) or 1.0), 0.1)
                            _z1 = max(float(metrics.get("wobj_Z1_total", 1) or 1), 1.0) / _sim_h
                            _z2 = max(float(metrics.get("wobj_Z2_total", 1) or 1), 1.0) / _sim_h
                            _z3 = max(float(metrics.get("wobj_Z3_total", 1) or 1), 1.0) / _sim_h
                            _baseline_scales = {{
                                "WOBJ_Z1_SCALE": round(_z1, 0),
                                "WOBJ_Z2_SCALE": round(_z2, 0),
                                "WOBJ_Z3_SCALE": round(_z3, 0),
                            }}
                            print(f"[GUI]   auto-calibrated objective scales: "
                                  f"Z1={{_z1:.0f}} Z2={{_z2:.0f}} Z3={{_z3:.0f}} "
                                  f"(per sim-hour from {{exp_name}} seed={{seed}})")
                        print(f"[GUI]   written -> {{_os.path.basename(BATCH_RESULTS_CSV)}}")
                    except Exception as e:
                        print(f"[GUI]   ERROR collecting metrics: {{e}}")
                        failures.append({{"experiment": exp_name, "seed": seed, "error": str(e)}})
    finally:
        # Restore logging regardless of success/failure, same as batch_runner.py.
        try:
            _set_logging(CONTROLLER_PATH, enabled=True)
            log("Controller logging restored to True.")
        except Exception as e:
            log(f"WARNING: could not re-enable controller logging: {{e}}")

    print("=" * 68)
    print(f"[GUI] Batch complete: {{run_num}} runs, {{len(failures)}} failures")
    for f in failures:
        print(f"[GUI]   FAILED: {{f}}")
    print(f"[GUI] Results CSV : {{BATCH_RESULTS_CSV}}")

    # Regenerate the dashboard from the now-COMPLETE results file. AAPIFinish
    # (in shared_tsp_engine/engine.py) already regenerates it after every
    # individual replication, but that happens before this script appends
    # that replication's own row to BATCH_RESULTS_CSV (append_master_csv runs
    # AFTER run_replication() returns here) -- so each in-flight dashboard is
    # always missing the run that just finished. Rebuilding once more here,
    # after every row is in, guarantees the final dashboard is complete.
    try:
        import importlib
        import generate_dashboard as _gd
        importlib.reload(_gd)
        _suffix = "_" + _os.path.splitext(_os.path.basename(BATCH_RESULTS_CSV))[0].removeprefix("batch_results").lstrip("_") \\
                  if _os.path.basename(BATCH_RESULTS_CSV) != "batch_results.csv" else ""
        _gd.generate(
            batch_csv=BATCH_RESULTS_CSV if _os.path.isfile(BATCH_RESULTS_CSV) else None,
            out_html=_os.path.join(_SCRIPT_DIR, f"tsp_dashboard{{_suffix}}.html"),
            log_dir=_os.path.join(_SCRIPT_DIR, "logs"),
        )
        print(f"[GUI] Final dashboard written -> tsp_dashboard{{_suffix}}.html")
    except Exception as e:
        print(f"[GUI] WARNING: final dashboard regeneration failed: {{e}}")

    # ── Beamer deck (policy sweeps only) ─────────────────────────────────────
    # On completion, write the Beamer deck for agency-preference x demand
    # sensitivity batches (experiment names like HSLWR_PRO_BUS). The .tex is
    # always written; it also compiles to PDF when pdflatex is available.
    try:
        import re as _re
        _pol_re = _re.compile(
            r"^(CPD_QL|CELLQLEARN_DP|CELLQLEARN|CTMGS|HSLWR|NASHHS)_(PRO_BUS|PRO_CAR|BALANCED)$")
        _pol_enabled = [e for e in enabled if _pol_re.match(str(e.get("name", "")))]
        if _pol_enabled:
            _deck_dir = _os.path.join(_SCRIPT_DIR, "beamer_report")
            _os.makedirs(_deck_dir, exist_ok=True)
            _bname = _os.path.basename(BATCH_RESULTS_CSV)
            _tag = _bname[len("batch_results_"):-4] if _bname.startswith("batch_results_") else "gui"
            _deck_tex = _os.path.join(_deck_dir, _tag + "_policy_sweep.tex")
            _root = _SCRIPT_DIR
            if not _os.path.isfile(_os.path.join(_root, "beamer_report.py")):
                _root = _os.path.dirname(_SCRIPT_DIR)
            if _root not in _sys.path:
                _sys.path.insert(0, _root)
            try:
                import beamer_report as _beamer
                _beamer.render_deck(
                    BATCH_RESULTS_CSV, _deck_tex,
                    title=_os.path.basename(_SCRIPT_DIR) + " - agency-preference x demand sensitivity",
                    subtitle=_bname)
                print("[GUI] Beamer deck written -> %s" % _deck_tex)
                _ok, _msg = _beamer.compile_deck(_deck_tex)
                print("[GUI] Beamer compile: %s" % _msg)
            except Exception as _e:
                print("[GUI] WARNING: beamer deck generation failed: %s" % _e)
    except Exception as _e:
        print("[GUI] WARNING: beamer deck step failed: %s" % _e)
'''


def _format_experiments(experiments) -> str:
    lines = ["["]
    for exp in experiments:
        lines.append("    {")
        lines.append(f"        \"name\": {exp['name']!r},")
        lines.append(f"        \"enabled\": {exp['enabled']!r},")
        lines.append(f"        \"strategy\": {exp['strategy']!r},")
        lines.append(f"        \"method\": {exp.get('method', '')!r},")
        lines.append(f"        \"coordinated\": {exp['coordinated']!r},")
        lines.append(f"        \"coordination_algo\": {exp['coordination_algo']!r},")
        lines.append(f"        \"active_intersections\": {exp['active_intersections']!r},")
        if exp.get("reward_overrides"):
            lines.append("        \"reward_overrides\": {")
            for k, v in exp["reward_overrides"].items():
                lines.append(f"            {k!r}: {v!r},")
            lines.append("        },")
        else:
            lines.append("        \"reward_overrides\": {},")
        if exp.get("method_overrides"):
            lines.append("        \"method_overrides\": {")
            for k, v in exp["method_overrides"].items():
                lines.append(f"            {k!r}: {v!r},")
            lines.append("        },")
        else:
            lines.append("        \"method_overrides\": {},")
        lines.append("    },")
    lines.append("]")
    return "\n".join(lines)


def render_batch_runner_gui(experiments, seeds, scalars, output_tag="gui") -> str:
    experiments = enforce_z4_hard_constraint(
        [dict(e) for e in experiments])
    return _TEMPLATE.format(
        timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        output_tag=output_tag,
        seeds=seeds,
        scalars=scalars,
        experiments=_format_experiments(experiments),
        results_csv_name=f"batch_results_{output_tag}.csv",
        core_output_name=f"core_output_{output_tag}.csv",
    )


# =============================================================================
# Test-mode template — a quick "do the sweep jobs actually differ?" check.
# Compiles ONE strategy across the sweep focus (the intervention-frequency keys
# TSP_CYCLE_LENGTH_OVERRIDE_S + PHASE_SEQ_MAX_PER_CYCLE) for a single seed.
# For every job it reads the focus keys back out of the run_config.py it just
# wrote (the exact regression for the dead-config bugs), runs the replication,
# and prints a PASS/FAIL verdict on focus-key distinctness + metric spread.
# =============================================================================
_TEST_TEMPLATE = '''# =============================================================================
# batch_runner_{output_tag}_test.py — GENERATED TEST SWEEP by
# batch_runner_gui_builder.py on {timestamp}
# =============================================================================
# Purpose: CONFIRM THE SWEEP JOBS DIFFER. One strategy is compiled across the
# sweep focus (intervention frequency X1/X2/X3) for a single seed, so the only
# thing that changes between jobs is the focus keys:
#     TSP_CYCLE_LENGTH_OVERRIDE_S   (decision window, s)
#     PHASE_SEQ_MAX_PER_CYCLE       (hard SEQ cap per 135 s cycle)
# After each job it reads run_config.py back and asserts the focus keys equal
# what the job intended to write (regression for the dead-config bug), then
# runs the replication and records the passenger-delay metric. A "TEST PASS" is
# printed only if every non-baseline job's focus keys are distinct.
#
# Run from Aimsun's "Run Script" menu, same as the other batch_runner_*.py.
# =============================================================================

import os as _os
import sys as _sys
import time as _time
import importlib.util as _ilu
from PyANGKernel import GKSystem

try:
    _SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))
except NameError:
    _model = GKSystem.getSystem().getActiveModel()
    _SCRIPT_DIR = _model.getDocumentDirectory().absolutePath()

if _SCRIPT_DIR not in _sys.path:
    _sys.path.insert(0, _SCRIPT_DIR)

_br_path = _os.path.join(_SCRIPT_DIR, "batch_runner.py")
_spec = _ilu.spec_from_file_location("_br_gui_test", _br_path)
_br = _ilu.module_from_spec(_spec)
_sys.modules["_br_gui_test"] = _br
try:
    _spec.loader.exec_module(_br)
except SystemExit:
    pass

log = _br.log
set_control_mode = _br.set_control_mode
set_coordinated = _br.set_coordinated
set_coordination_algo = _br.set_coordination_algo
set_seed = _br.set_seed
set_reward_weights = _br.set_reward_weights
write_run_config = _br.write_run_config
collect_run_metrics = _br.collect_run_metrics
append_master_csv = _br.append_master_csv
get_first_replication = _br.get_first_replication
run_replication = _br.run_replication
_purge_pyc = _br._purge_pyc
_set_logging = _br._set_logging

CONTROLLER_PATH = _br.CONTROLLER_PATH
RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
PROJECT_DIR = _br.PROJECT_DIR

BATCH_RESULTS_CSV = _os.path.join(_SCRIPT_DIR, "batch_results_{output_tag}_test.csv")

SEEDS = [300]
DEMAND_SCALARS = [1.0]

# Keys that define the sweep focus — every non-baseline job must differ on all.
SWEEP_KEYS = {sweep_keys!r}

EXPERIMENTS = {experiments}


def _read_run_config_value(key):
    """Read one key back out of run_config.py after it is written."""
    _ns = {{}}
    try:
        with open(RUN_CONFIG_PATH, "r", encoding="utf-8") as _f:
            exec(_f.read(), _ns)
    except Exception as _e:
        return "<read-error: {{}}>".format(_e)
    return _ns.get(key, "<missing>")


if __name__ == "__main__":
    try:
        _rt_proj = _br.get_project_dir()
        CONTROLLER_PATH = _os.path.join(_rt_proj, "intersection_controller.py")
        RUN_CONFIG_PATH = _os.path.join(_rt_proj, "run_config.py")
        PROJECT_DIR = _rt_proj
        _br.CONTROLLER_PATH = CONTROLLER_PATH
        _br.RUN_CONFIG_PATH = RUN_CONFIG_PATH
        _br.PROJECT_DIR = PROJECT_DIR
    except Exception as _e:
        print(f"[SS-TEST] WARNING: could not resolve project dir: {{_e}}")

    if _os.path.isfile(BATCH_RESULTS_CSV):
        try:
            _os.remove(BATCH_RESULTS_CSV)
            print(f"[SS-TEST] Deleted stale results: {{_os.path.basename(BATCH_RESULTS_CSV)}}")
        except Exception as _e:
            print(f"[SS-TEST] WARNING: could not delete {{BATCH_RESULTS_CSV}}: {{_e}}")

    enabled = [e for e in EXPERIMENTS if e.get("enabled", True)]
    print("=" * 70)
    print("[SS-TEST] Sweep-focus job-difference check")
    print(f"[SS-TEST] Focus keys: {{SWEEP_KEYS}}")
    for i, e in enumerate(enabled, 1):
        print(f"[SS-TEST]   [{{i}}/{{len(enabled)}}] {{e['name']}}")
    print("=" * 70)

    try:
        _set_logging(CONTROLLER_PATH, enabled=False)
    except Exception as e:
        log(f"WARNING: could not disable controller logging: {{e}}")

    rep = get_first_replication()
    observed = []   # (experiment, focus-tuple, delay_hrs)
    failures = []
    try:
        for exp in enabled:
            exp_name = exp["name"]
            strategy = exp["strategy"]
            coordinated = exp.get("coordinated", False)
            coord_algo = exp.get("coordination_algo", "KALMAN")
            reward_overrides = exp.get("reward_overrides", {{}}) or {{}}
            method_overrides = exp.get("method_overrides", {{}}) or {{}}
            reward_overrides = dict(reward_overrides)
            reward_overrides.update(method_overrides)
            is_baseline = (strategy == "NORMAL")
            expected = {{k: reward_overrides[k] for k in SWEEP_KEYS if k in reward_overrides}}
            _global_reward = bool(reward_overrides.get("GLOBAL_REWARD_MODE", False))
            _numeric_ov = {{k: v for k, v in reward_overrides.items() if k != "GLOBAL_REWARD_MODE"}}
            _run_cfg = None if (is_baseline and not _numeric_ov) else (_numeric_ov or None)
            _bus_pred = str(reward_overrides.get("BUS_PREDICTOR_TYPE", "ADAPTIVE_KALMAN")).upper()

            try:
                set_control_mode(strategy, CONTROLLER_PATH, exp.get("active_intersections"))
            except Exception as e:
                print(f"[SS-TEST] FATAL: cannot patch strategy for {{exp_name}}: {{e}}")
                failures.append(exp_name)
                continue
            try:
                set_coordinated(CONTROLLER_PATH, coordinated)
                set_coordination_algo(CONTROLLER_PATH, coord_algo)
            except Exception as e:
                print(f"[SS-TEST] WARNING: coord patch for {{exp_name}}: {{e}}")
            if not is_baseline:
                try:
                    set_reward_weights(CONTROLLER_PATH, _numeric_ov or None)
                except Exception as e:
                    log(f"WARNING: reward patch: {{e}}")

            set_seed(rep, 300)
            write_run_config(exp_name, strategy, 300, 1.0, coordinated, coord_algo,
                             RUN_CONFIG_PATH, global_reward_mode=_global_reward,
                             reward_cfg=_run_cfg, bus_predictor=_bus_pred,
                             results_csv_name=_os.path.basename(BATCH_RESULTS_CSV))
            _purge_pyc(CONTROLLER_PATH)

            read_back = {{k: _read_run_config_value(k) for k in SWEEP_KEYS}}
            ok = all(read_back.get(k) == expected.get(k) for k in expected)
            print("-" * 70)
            print(f"[SS-TEST] {{exp_name}}  expected={{expected}}  read_back={{read_back}}  -> "
                  f"{{'OK' if ok else 'MISMATCH'}}")
            if not ok:
                failures.append(exp_name)

            t0 = _time.time()
            success = True
            try:
                run_replication(rep)
            except Exception as e:
                success = False
                failures.append(exp_name)
                print(f"[SS-TEST]   EXCEPTION during simulation: {{e}}")
            elapsed = _time.time() - t0
            print(f"[SS-TEST]   elapsed={{elapsed:.0f}}s  success={{success}}")

            if success:
                try:
                    metrics = collect_run_metrics(
                        PROJECT_DIR, strategy, 300, 1.0, exp_name, coordinated,
                        elapsed, success, bus_predictor=_bus_pred)
                    metrics["sweep_focus"] = str(expected)
                    append_master_csv(BATCH_RESULTS_CSV, metrics)
                    _delay = metrics.get("stats_TotalPassDelay_hrs", "?")
                    print(f"[SS-TEST]   delay={{_delay}}h")
                    observed.append((exp_name, tuple(sorted(read_back.items())), _delay))
                except Exception as e:
                    print(f"[SS-TEST]   ERROR collecting metrics: {{e}}")
                    failures.append(exp_name)
    finally:
        try:
            _set_logging(CONTROLLER_PATH, enabled=True)
        except Exception as e:
            log(f"WARNING: could not re-enable controller logging: {{e}}")

    print("=" * 70)
    focus_rows = [o for o in observed if "NO_TSP" not in str(o[0])]
    distinct = (len(set(o[1] for o in focus_rows)) == len(focus_rows)
                if focus_rows else False)
    print("[SS-TEST] Job comparison (focus keys + passenger delay):")
    for name, keys, delay in observed:
        print(f"[SS-TEST]   {{name:<28}} {{keys}}  delay={{delay}}h")
    if not focus_rows:
        verdict = "FAIL — no non-baseline jobs produced metrics"
    elif failures:
        verdict = f"FAIL — {{len(failures)}} job(s) had mismatches/exceptions"
    elif not distinct:
        verdict = "FAIL — sweep focus keys are IDENTICAL across jobs (config not propagating)"
    else:
        verdict = (f"PASS — {{len(focus_rows)}} jobs differ on focus keys {{SWEEP_KEYS}}; "
                   f"compare their delay values above")
    print(f"[SS-TEST] VERDICT: {{verdict}}")
    print("=" * 70)
'''


def render_batch_runner_test(experiments, output_tag="gui") -> str:
    return _TEST_TEMPLATE.format(
        timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        output_tag=output_tag,
        sweep_keys=["TSP_CYCLE_LENGTH_OVERRIDE_S", "PHASE_SEQ_MAX_PER_CYCLE"],
        experiments=_format_experiments(experiments),
    )


# =============================================================================
# ── GUI ────────────────────────────────────────────────────────────────────
# =============================================================================

class BatchRunnerBuilderApp:
    def __init__(self, root):
        self.root = root
        root.title("Batch Runner GUI Builder")
        root.geometry("620x800")

        self.network_var = tk.StringVar(value="logan_road_new")
        self.preset_var = tk.StringVar()
        self.exp_name_var = tk.StringVar()
        self.coordinated_var = tk.BooleanVar(value=True)
        self.coord_algo_var = tk.StringVar(value="KALMAN")
        self.include_baseline_var = tk.BooleanVar(value=True)
        self.seeds_var = tk.StringVar(value="300")
        self.scalars_var = tk.StringVar(value="1.0")
        self.cycle_len_var = tk.StringVar(value="10.0")
        self.coord_hops_var = tk.StringVar(value="1")
        self.weight_vars = {}  # key -> StringVar, rebuilt per preset
        self.main_side_vars = (tk.StringVar(value="1.0"), tk.StringVar(value="0.5"))
        self.paper_batch_var = tk.BooleanVar(value=False)
        self.weight_sweep_var = tk.BooleanVar(value=False)
        self.ss_bus_batch_var = tk.BooleanVar(value=False)
        self.tag_var = tk.StringVar(value="gui")
        self.bus_demand_var = tk.StringVar(value="1.0, 1.5, 2.0, 3.0")
        self.ss_x1_var = tk.BooleanVar(value=True)
        self.ss_x2_var = tk.BooleanVar(value=True)
        self.ss_x3_var = tk.BooleanVar(value=True)
        self.ss_test_var = tk.BooleanVar(value=False)
        self.ss_strat_vars = {
            "CELLQLEARN_DP": tk.BooleanVar(value=True),
            "NASHHS": tk.BooleanVar(value=True),
            "CELLQLEARN": tk.BooleanVar(value=True),
            "CTMGS": tk.BooleanVar(value=True),
            "HSLWR": tk.BooleanVar(value=True),
            "CPD_QL": tk.BooleanVar(value=True),
        }
        self.SS_CTM_STRATEGIES = ["CELLQLEARN_DP", "NASHHS", "CELLQLEARN",
                                  "CTMGS", "HSLWR", "CPD_QL"]

        self._build_widgets()
        self.seeds_var.trace_add("write", lambda *a: self._update_count_preview())
        self.scalars_var.trace_add("write", lambda *a: self._update_count_preview())
        self._on_network_change()

    # ── layout ────────────────────────────────────────────────────────────
    def _build_widgets(self):
        pad = dict(padx=8, pady=4)

        net_frame = ttk.LabelFrame(self.root, text="Network")
        net_frame.pack(fill="x", **pad)
        for key, cfg in NETWORKS.items():
            ttk.Radiobutton(net_frame, text=cfg["label"], value=key,
                             variable=self.network_var,
                             command=self._on_network_change).pack(side="left", padx=10, pady=6)

        strat_frame = ttk.LabelFrame(self.root, text="Strategy")
        strat_frame.pack(fill="x", **pad)
        self.preset_combo = ttk.Combobox(strat_frame, textvariable=self.preset_var,
                                          state="readonly", width=55)
        self.preset_combo.pack(fill="x", padx=8, pady=6)
        self.preset_combo.bind("<<ComboboxSelected>>", lambda e: self._on_preset_change())

        row = ttk.Frame(strat_frame)
        row.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Checkbutton(row, text="Coordinated (corridor pre-arming)",
                         variable=self.coordinated_var).pack(side="left")
        ttk.Label(row, text="  Coordination algo:").pack(side="left")
        ttk.Combobox(row, textvariable=self.coord_algo_var, state="readonly", width=12,
                     values=["KALMAN", "SHOCKWAVE", "OBJECTIVE", "ADAPTIVE"]).pack(side="left")

        self.weights_frame = ttk.LabelFrame(self.root, text="Objective weights")
        self.weights_frame.pack(fill="x", **pad)

        params_frame = ttk.LabelFrame(self.root, text="Run parameters")
        params_frame.pack(fill="x", **pad)

        def add_row(parent, label, var, hint=None):
            r = ttk.Frame(parent)
            r.pack(fill="x", padx=8, pady=3)
            ttk.Label(r, text=label, width=34, anchor="w").pack(side="left")
            ttk.Entry(r, textvariable=var, width=20).pack(side="left")
            if hint:
                ttk.Label(r, text=hint, foreground="#666").pack(side="left", padx=6)
            return r

        add_row(params_frame, "Experiment name:", self.exp_name_var)
        add_row(params_frame, "Seeds (comma-separated ints):", self.seeds_var)
        add_row(params_frame, "Demand scalars (comma-separated):", self.scalars_var)
        self.cycle_len_row = add_row(params_frame, "TSP cycle length (s):", self.cycle_len_var,
                                      "sim-second time budget per TSP decision cycle")
        add_row(params_frame, "Upstream/downstream connected:", self.coord_hops_var,
                "how many intersections ahead a bus detection pre-arms")
        add_row(params_frame, "Output file tag:", self.tag_var,
                "saved as batch_results_{tag}.csv, core_output_{tag}.csv")
        ttk.Checkbutton(params_frame, text="Also include a NO_TSP baseline run for comparison",
                         variable=self.include_baseline_var,
                         command=self._update_count_preview).pack(anchor="w", padx=8, pady=(4, 8))

        batch_frame = ttk.LabelFrame(self.root, text="Paper strategy batch")
        batch_frame.pack(fill="x", **pad)
        ttk.Checkbutton(batch_frame, text="Generate all paper strategy experiments (NoPriority + Methods 0-V)",
                         variable=self.paper_batch_var,
                         command=self._on_paper_batch_toggle).pack(anchor="w", padx=8, pady=6)

        self.sweep_frame = ttk.LabelFrame(self.root, text="WOBJ weight sweep")
        self.sweep_frame.pack(fill="x", **pad)
        sweep_row = ttk.Frame(self.sweep_frame)
        sweep_row.pack(fill="x", padx=8, pady=6)
        ttk.Checkbutton(sweep_row, text="Enable WOBJ weight sweep (Z1/Z2/Z3)",
                         variable=self.weight_sweep_var,
                         command=self._update_count_preview).pack(side="left")
        ttk.Label(sweep_row, text="  one alpha,beta,gamma per line:", foreground="#666").pack(side="left")
        self.weight_sweep_text = tk.Text(self.sweep_frame, height=5, width=50, font=("Consolas", 10))
        self.weight_sweep_text.pack(fill="x", padx=8, pady=(0, 8))
        self.weight_sweep_text.insert("1.0", (
            "0.333,0.333,0.333\n"
            "1.0,0.0,0.0\n"
            "0.0,1.0,0.0\n"
            "0.0,0.0,1.0"
        ))
        self.weight_sweep_text.bind("<KeyRelease>", lambda e: self._update_count_preview())
        self._update_sweep_visibility()

        self.ss_bus_frame = ttk.LabelFrame(self.root, text="CTM strategy x Frequency x Bus Demand sweep")
        self.ss_bus_frame.pack(fill="x", **pad)
        ttk.Checkbutton(self.ss_bus_frame,
                         text="Enable CTM strategy x Frequency x Bus Demand cross-join sweep",
                         variable=self.ss_bus_var,
                         command=self._on_ss_bus_batch_toggle).pack(anchor="w", padx=8, pady=6)
        self.ss_bus_inner = ttk.Frame(self.ss_bus_frame)
        self.ss_bus_inner.pack(fill="x", padx=8, pady=(0, 6))

        bus_row = ttk.Frame(self.ss_bus_inner)
        bus_row.pack(fill="x", pady=2)
        ttk.Label(bus_row, text="Bus demand scalars:", width=24, anchor="w").pack(side="left")
        ttk.Entry(bus_row, textvariable=self.bus_demand_var, width=30).pack(side="left", padx=4)
        ttk.Label(bus_row, text="(1.0=base, 2.0=double buses)", foreground="#666").pack(side="left")

        fam_row = ttk.Frame(self.ss_bus_inner)
        fam_row.pack(fill="x", pady=2)
        ttk.Label(fam_row, text="CTM strategy:", width=12, anchor="w").pack(side="left")
        _ctm = self.SS_CTM_STRATEGIES
        for i, m in enumerate(_ctm, start=1):
            ttk.Checkbutton(fam_row, text=m,
                            variable=self.ss_strat_vars[m],
                            command=self._update_count_preview).pack(side="left", padx=3)
            if i == 3:
                fam_row2 = ttk.Frame(self.ss_bus_inner)
                fam_row2.pack(fill="x", pady=2)
                ttk.Label(fam_row2, text="", width=12, anchor="w").pack(side="left")
                fam_row = fam_row2

        freq_row = ttk.Frame(self.ss_bus_inner)
        freq_row.pack(fill="x", pady=2)
        ttk.Label(freq_row, text="Frequency:", width=12, anchor="w").pack(side="left")
        ttk.Checkbutton(freq_row, text="X1 (1/cycle)", variable=self.ss_x1_var,
                         command=self._update_count_preview).pack(side="left", padx=3)
        ttk.Checkbutton(freq_row, text="X2 (2/cycle)", variable=self.ss_x2_var,
                         command=self._update_count_preview).pack(side="left", padx=3)
        ttk.Checkbutton(freq_row, text="X3 (3/cycle)", variable=self.ss_x3_var,
                         command=self._update_count_preview).pack(side="left", padx=3)

        ttest_row = ttk.Frame(self.ss_bus_inner)
        ttest_row.pack(fill="x", pady=2)
        ttk.Checkbutton(ttest_row,
                         text="TEST: one strategy, all frequencies, 1 seed "
                              "(confirm sweep jobs differ)",
                         variable=self.ss_test_var,
                         command=self._update_count_preview).pack(side="left")

        ttk.Checkbutton(self.ss_bus_inner, text="Include NO_TSP baseline at each bus level",
                         variable=self.include_baseline_var,
                         command=self._update_count_preview).pack(anchor="w", pady=(2, 0))
        self._update_ss_bus_visibility()

        out_frame = ttk.LabelFrame(self.root, text="Output")
        out_frame.pack(fill="both", expand=True, **pad)
        self.output_label = ttk.Label(out_frame, text="", foreground="#333", wraplength=580, justify="left")
        self.output_label.pack(fill="x", padx=8, pady=(8, 4))
        self.count_label = ttk.Label(out_frame, text="", foreground="#0066cc", wraplength=580, justify="left")
        self.count_label.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Button(out_frame, text="Generate batch_runner_gui.py",
                   command=self._on_generate).pack(padx=8, pady=8)
        self.status_label = ttk.Label(out_frame, text="", foreground="#0a6b0a", wraplength=580, justify="left")
        self.status_label.pack(fill="x", padx=8, pady=(0, 8))

        # ── Delete old runs ──────────────────────────────────────────────────
        _del_row = ttk.Frame(out_frame)
        _del_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(_del_row, text="Delete output CSVs for tag:",
                   command=self._on_delete_runs).pack(side="left")
        self.del_tag_var = tk.StringVar(value="gui")
        ttk.Entry(_del_row, textvariable=self.del_tag_var, width=12).pack(side="left", padx=4)
        ttk.Label(_del_row, text="(archives + live .csv)",
                  foreground="#666").pack(side="left")

    # ── behaviour ─────────────────────────────────────────────────────────
    def _current_network(self):
        return NETWORKS[self.network_var.get()]

    def _current_preset_key(self):
        combo_value = self.preset_var.get()
        for key, preset in self._current_network()["presets"].items():
            if preset["label"] == combo_value:
                return key
        return None

    def _on_network_change(self):
        net = self._current_network()
        labels = [p["label"] for p in net["presets"].values()]
        self.preset_combo["values"] = labels
        if labels:
            self.preset_var.set(labels[0])
        state = "normal" if net["supports_cycle_length"] else "disabled"
        for child in self.cycle_len_row.winfo_children():
            child.configure(state=state)
        if not net["supports_cycle_length"]:
            self.output_label.configure(
                text="KG's controller does not implement TSP_CYCLE_LENGTH_OVERRIDE_S or the "
                     "WOBJ_* DCTSP objective system — that field is disabled and the strategy "
                     "list is limited to what KG's intersection_controller.py actually supports.")
        else:
            self.output_label.configure(text="")
        self._on_preset_change()
        self._update_count_preview()

    def _on_preset_change(self):
        key = self._current_preset_key()
        if key is None:
            return
        preset = self._current_network()["presets"][key]
        self.exp_name_var.set(key)
        self.coordinated_var.set(preset["coordinated"])
        self.coord_algo_var.set(preset["coordination_algo"])
        self._rebuild_weight_fields(preset["weight_kind"])
        self._update_count_preview()

    def _rebuild_weight_fields(self, weight_kind):
        for child in self.weights_frame.winfo_children():
            child.destroy()
        self.weight_vars = {}
        if weight_kind is None:
            ttk.Label(self.weights_frame, text="(this strategy has no tunable reward weights)",
                      foreground="#666").pack(padx=8, pady=6, anchor="w")
            return
        for field_key, field_label, default in WEIGHT_FIELDS[weight_kind]:
            var = tk.StringVar(value=str(default))
            self.weight_vars[field_key] = var
            r = ttk.Frame(self.weights_frame)
            r.pack(fill="x", padx=8, pady=3)
            ttk.Label(r, text=field_label, width=34, anchor="w").pack(side="left")
            ttk.Entry(r, textvariable=var, width=20).pack(side="left")
        if weight_kind == "wobj":
            for lbl, var in zip(("Main-corridor section weight:", "Side-street section weight:"),
                                 self.main_side_vars):
                r = ttk.Frame(self.weights_frame)
                r.pack(fill="x", padx=8, pady=3)
                ttk.Label(r, text=lbl, width=34, anchor="w").pack(side="left")
                ttk.Entry(r, textvariable=var, width=20).pack(side="left")

    def _build_experiment_dict(self, key, preset):
        overrides = dict(preset.get("reward_overrides") or {})
        method_overrides = dict(preset.get("method_overrides") or {})
        weight_kind = preset["weight_kind"]
        try:
            if weight_kind is not None:
                for field_key, var in self.weight_vars.items():
                    method_overrides[field_key] = float(var.get())
            if weight_kind == "wobj":
                method_overrides["REWARD_MAIN_SECTION_WEIGHT"] = float(self.main_side_vars[0].get())
                method_overrides["REWARD_SIDE_SECTION_WEIGHT"] = float(self.main_side_vars[1].get())
        except ValueError as e:
            raise ValueError(f"Invalid objective weight value: {e}")

        net = self._current_network()
        if net["supports_cycle_length"] and preset["strategy"] != "NORMAL" \
                and "TSP_CYCLE_LENGTH_OVERRIDE_S" not in method_overrides:
            try:
                method_overrides["TSP_CYCLE_LENGTH_OVERRIDE_S"] = float(self.cycle_len_var.get())
            except ValueError:
                raise ValueError("TSP cycle length must be a number")

        coordinated = bool(self.coordinated_var.get())
        if coordinated and preset["strategy"] != "NORMAL":
            try:
                hops = int(self.coord_hops_var.get())
            except ValueError:
                raise ValueError("Upstream/downstream connected must be an integer")
            if hops < 1:
                raise ValueError("Upstream/downstream connected must be >= 1")
            method_overrides["COORD_DOWNSTREAM_HOPS"] = hops

        return {
            "name": _sanitize_name(self.exp_name_var.get() or key),
            "enabled": True,
            "strategy": preset["strategy"],
            "method": preset.get("method", key),
            "coordinated": coordinated,
            "coordination_algo": self.coord_algo_var.get(),
            "active_intersections": None,
            "reward_overrides": overrides,
            "method_overrides": method_overrides,
        }

    def _on_paper_batch_toggle(self):
        self._update_sweep_visibility()
        self._update_count_preview()

    def _update_sweep_visibility(self):
        if self.paper_batch_var.get() or self.weight_sweep_var.get():
            self.sweep_frame.pack(fill="x", padx=8, pady=4)
        else:
            self.sweep_frame.pack_forget()

    def _on_ss_bus_batch_toggle(self):
        self._update_ss_bus_visibility()
        self._update_count_preview()

    def _update_ss_bus_visibility(self):
        if self.ss_bus_var.get():
            self.ss_bus_inner.pack(fill="x", padx=8, pady=(0, 6))
        else:
            self.ss_bus_inner.pack_forget()

    def _get_ss_bus_methods(self):
        methods = []
        for m in self.SS_CTM_STRATEGIES:
            if not self.ss_strat_vars[m].get():
                continue
            for freq, fvar in [("X1", self.ss_x1_var), ("X2", self.ss_x2_var),
                                ("X3", self.ss_x3_var)]:
                if fvar.get():
                    methods.append((m, freq))
        return methods

    def _get_ss_test_methods(self):
        """One strategy (the first selected downstream) across ALL frequencies so
        the ONLY thing changing between jobs is the intervention-frequency keys
        (TSP_CYCLE_LENGTH_OVERRIDE_S + PHASE_SEQ_MAX_PER_CYCLE)."""
        selected = [m for m in self.SS_CTM_STRATEGIES if self.ss_strat_vars[m].get()]
        m = selected[0] if selected else "CELLQLEARN_DP"
        return [(m, freq) for freq in ("X1", "X2", "X3")]

    def _parse_weight_combos(self):
        if not self.weight_sweep_var.get():
            return []
        text = self.weight_sweep_text.get("1.0", "end-1c").strip()
        combos = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 3:
                raise ValueError(f"Invalid weight combo (need 3 values alpha,beta,gamma): {line}")
            a, b, g = float(parts[0]), float(parts[1]), float(parts[2])
            combos.append((a, b, g))
        return combos

    def _update_count_preview(self):
        """Show how many runs the current settings will produce."""
        try:
            seeds = _parse_num_list(self.seeds_var.get(), int)
            scalars = _parse_num_list(self.scalars_var.get(), float)
        except ValueError:
            self.count_label.configure(text="(enter valid seeds/scalars to see run count)")
            return
        if self.paper_batch_var.get():
            weight_combos = self._parse_weight_combos()
            n_variants = max(len(weight_combos), 1)
            n_exp = len(PAPER_STRATEGY_BATCH) * n_variants
        elif self.ss_bus_var.get():
            if self.ss_test_var.get():
                # Test: one strategy across all three frequencies, 1 seed,
                # 1 scalar, 1 bus level — the sweep-focus difference check.
                seeds = [300]
                scalars = [1.0]
                n_exp = 3 + (1 if self.include_baseline_var.get() else 0)
            else:
                try:
                    bus_demand = _parse_num_list(self.bus_demand_var.get(), float)
                except ValueError:
                    self.count_label.configure(text="(enter valid bus demand scalars to see run count)")
                    return
                ss_methods = self._get_ss_bus_methods()
                n_ss = len(ss_methods)
                if self.include_baseline_var.get():
                    n_ss += 1
                n_exp = n_ss * len(bus_demand)
        else:
            n_exp = 1
            key = self._current_preset_key()
            if self.include_baseline_var.get() and key is not None and key != "NO_TSP":
                n_exp = 2
            weight_combos = self._parse_weight_combos()
            if key is not None and key != "NO_TSP" and weight_combos:
                n_exp = len(weight_combos) + (1 if self.include_baseline_var.get() else 0)
        n_total = n_exp * len(seeds) * len(scalars)
        self.count_label.configure(
            text=f"Will generate: {n_exp} experiment(s) x {len(seeds)} seed(s) x {len(scalars)} scalar(s) = {n_total} run(s)")

    def _on_generate(self):
        net = self._current_network()
        _tag = str(self.tag_var.get() or "gui").strip() or "gui"

        if self.paper_batch_var.get():
            try:
                weight_combos = self._parse_weight_combos()
                seeds = _parse_num_list(self.seeds_var.get(), int)
                scalars = _parse_num_list(self.scalars_var.get(), float)
            except ValueError as e:
                messagebox.showerror("Batch Runner GUI Builder", str(e))
                return

            experiments = []
            for paper_key in PAPER_STRATEGY_BATCH:
                preset = net["presets"][paper_key]
                base_exp = self._build_experiment_dict(paper_key, preset)

                if weight_combos and paper_key != "NO_TSP":
                    if "PARETO_SELECTION_MODE" in base_exp["reward_overrides"]:
                        base_exp["reward_overrides"] = dict(base_exp["reward_overrides"])
                        base_exp["reward_overrides"].pop("PARETO_SELECTION_MODE", None)
                    for a, b, g in weight_combos:
                        exp = dict(base_exp)
                        exp["name"] = _sanitize_name(f"{paper_key}_W{a:.3f}_{b:.3f}_{g:.3f}")
                        exp["method_overrides"] = dict(exp["method_overrides"])
                        exp["method_overrides"].update({
                            "WOBJ_ALPHA": round(a, 6),
                            "WOBJ_BETA": round(b, 6),
                            "WOBJ_GAMMA": round(g, 6),
                            "WOBJ_Z1_SCALE": 3000000.0,
                            "WOBJ_Z2_SCALE": 7500.0,
                            "WOBJ_Z3_SCALE": 12000.0,
                        })
                        experiments.append(exp)
                else:
                    experiments.append(base_exp)

            if not experiments:
                messagebox.showerror("Batch Runner GUI Builder", "No experiments generated.")
                return

            content = render_batch_runner_gui(experiments, seeds, scalars, output_tag=_tag)
        elif self.ss_bus_var.get():
            if self.ss_test_var.get():
                # ── TEST MODE ─────────────────────────────────────────────
                # Compile ONE strategy across the frequency sweep focus, single
                # seed, and confirm the jobs differ on the focus keys.
                seeds = [300]
                scalars = [1.0]
                ss_test_methods = self._get_ss_test_methods()
                if not ss_test_methods:
                    messagebox.showerror("Batch Runner GUI Builder",
                                          "No SS test methods could be built.")
                    return
                experiments = []
                for method, freq in ss_test_methods:
                    preset = net["presets"].get(method)
                    if preset is None:
                        continue
                    base_exp = self._build_experiment_dict(method, preset)
                    base_exp["method_overrides"] = dict(base_exp.get("method_overrides") or {})
                    base_exp["method_overrides"].update(
                        dict(_SS_FREQ_OVERRIDES.get(freq) or {}))
                    base_exp["name"] = _sanitize_name(f"TEST_{method}_{freq}")
                    base_exp["reward_overrides"] = dict(base_exp.get("reward_overrides") or {})
                    base_exp["reward_overrides"]["_ss_test"] = True
                    experiments.append(base_exp)
                if self.include_baseline_var.get():
                    experiments.append({
                        "name": "TEST_NO_TSP",
                        "enabled": True,
                        "strategy": "NORMAL",
                        "method": "NO_TSP",
                        "coordinated": False,
                        "coordination_algo": "KALMAN",
                        "active_intersections": None,
                        "reward_overrides": {"_ss_test": True},
                        "method_overrides": {},
                    })
                if not experiments:
                    messagebox.showerror("Batch Runner GUI Builder", "No experiments generated.")
                    return
                content = render_batch_runner_test(experiments, output_tag=_tag)
            else:
                try:
                    seeds = _parse_num_list(self.seeds_var.get(), int)
                    scalars = _parse_num_list(self.scalars_var.get(), float)
                    bus_demand = _parse_num_list(self.bus_demand_var.get(), float)
                    ss_methods = self._get_ss_bus_methods()
                except ValueError as e:
                    messagebox.showerror("Batch Runner GUI Builder", str(e))
                    return

                if not ss_methods and not self.include_baseline_var.get():
                    messagebox.showerror("Batch Runner GUI Builder",
                                          "Select at least one CTM strategy/freq combo or the baseline.")
                    return

                experiments = []
                for bus_level in bus_demand:
                    for method, freq in ss_methods:
                        preset = net["presets"].get(method)
                        if preset is None:
                            continue
                        base_exp = self._build_experiment_dict(method, preset)
                        base_exp["method_overrides"] = dict(base_exp.get("method_overrides") or {})
                        base_exp["method_overrides"].update(
                            dict(_SS_FREQ_OVERRIDES.get(freq) or {}))
                        base_exp["name"] = _sanitize_name(f"{method}_{freq}_BUSx{bus_level:g}")
                        base_exp["reward_overrides"] = dict(base_exp.get("reward_overrides") or {})
                        base_exp["reward_overrides"]["_bus_demand_scalar"] = bus_level
                        experiments.append(base_exp)

                    if self.include_baseline_var.get():
                        experiments.append({
                            "name": _sanitize_name(f"NO_TSP_BUSx{bus_level:g}"),
                            "enabled": True,
                            "strategy": "NORMAL",
                            "method": "NO_TSP",
                            "coordinated": False,
                            "coordination_algo": "KALMAN",
                            "active_intersections": None,
                            "reward_overrides": {"_bus_demand_scalar": bus_level},
                            "method_overrides": {},
                        })

                if not experiments:
                    messagebox.showerror("Batch Runner GUI Builder", "No experiments generated.")
                    return

                content = render_batch_runner_gui(experiments, seeds, scalars, output_tag=_tag)
        else:
            key = self._current_preset_key()
            if key is None:
                messagebox.showerror("Batch Runner GUI Builder", "Select a strategy first.")
                return
            preset = net["presets"][key]

            try:
                base_exp = self._build_experiment_dict(key, preset)
                seeds = _parse_num_list(self.seeds_var.get(), int)
                scalars = _parse_num_list(self.scalars_var.get(), float)
                weight_combos = self._parse_weight_combos()
            except ValueError as e:
                messagebox.showerror("Batch Runner GUI Builder", str(e))
                return

            experiments = []
            if self.include_baseline_var.get() and preset["strategy"] != "NORMAL":
                experiments.append({
                    "name": "NO_TSP",
                    "enabled": True,
                    "strategy": "NORMAL",
                    "method": "NO_TSP",
                    "coordinated": False,
                    "coordination_algo": "KALMAN",
                    "active_intersections": None,
                    "reward_overrides": {},
                    "method_overrides": {},
                })

            if weight_combos:
                if "PARETO_SELECTION_MODE" in base_exp["reward_overrides"]:
                    base_exp["reward_overrides"] = dict(base_exp["reward_overrides"])
                    base_exp["reward_overrides"].pop("PARETO_SELECTION_MODE", None)
                for a, b, g in weight_combos:
                    exp = dict(base_exp)
                    exp["name"] = _sanitize_name(f"{key}_W{a:.3f}_{b:.3f}_{g:.3f}")
                    exp["method_overrides"] = dict(exp["method_overrides"])
                    exp["method_overrides"].update({
                        "WOBJ_ALPHA": round(a, 6),
                        "WOBJ_BETA": round(b, 6),
                        "WOBJ_GAMMA": round(g, 6),
                        "WOBJ_Z1_SCALE": 3000000.0,
                        "WOBJ_Z2_SCALE": 7500.0,
                        "WOBJ_Z3_SCALE": 12000.0,
                    })
                    experiments.append(exp)
            else:
                experiments.append(base_exp)

            content = render_batch_runner_gui(experiments, seeds, scalars, output_tag=_tag)

        target_dir = os.path.join(SCRIPT_DIR, net["dir_name"])
        _is_test = bool(self.ss_bus_var.get() and self.ss_test_var.get())
        out_name = "batch_runner_gui_test.py" if _is_test else "batch_runner_gui.py"
        out_path = os.path.join(target_dir, out_name)
        if not os.path.isdir(target_dir):
            messagebox.showerror("Batch Runner GUI Builder",
                                  f"Network folder not found: {target_dir}")
            return
        if not os.path.isfile(os.path.join(target_dir, "batch_runner.py")):
            messagebox.showerror("Batch Runner GUI Builder",
                                  f"{target_dir} has no batch_runner.py to build on top of.")
            return

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)

        self.status_label.configure(
            text=f"Written: {out_path}\n"
                 f"{len(experiments)} experiment(s) x {len(seeds)} seed(s) x {len(scalars)} scalar(s) "
                 f"= {len(experiments) * len(seeds) * len(scalars)} run(s).\n"
                 f"Open this file from Aimsun's Run Script menu in the {net['label']} project.")

    def _on_delete_runs(self):
        net = self._current_network()
        target_dir = os.path.join(SCRIPT_DIR, net["dir_name"])
        _tag = str(self.del_tag_var.get() or "gui").strip() or "gui"
        if not os.path.isdir(target_dir):
            messagebox.showerror("Delete Runs", f"Network folder not found: {target_dir}")
            return

        _patterns = [
            f"batch_results_{_tag}.csv",
            f"batch_results_{_tag}_archive_*.csv",
            f"core_output_{_tag}.csv",
            f"core_output_{_tag}_archive_*.csv",
            f"tsp_dashboard_{_tag}.html",
        ]
        _deleted = 0
        import glob
        for _pat in _patterns:
            for _p in glob.glob(os.path.join(target_dir, _pat)):
                try:
                    _bak = _p + ".deleted"
                    if os.path.exists(_bak):
                        os.remove(_bak)
                    os.rename(_p, _bak)
                    _deleted += 1
                except Exception as _e:
                    try:
                        os.remove(_p)
                        _deleted += 1
                    except Exception:
                        pass

        self.status_label.configure(
            text=f"Deleted {_deleted} file(s) matching tag '{_tag}' in {target_dir}.\n"
                 f"(renamed to .deleted — remove manually if needed)")


def main():
    root = tk.Tk()
    BatchRunnerBuilderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
