# =============================================================================
# batch_runner.py — Aimsun Next 26 batch runner (REV06)
# =============================================================================
#
# QUICK-START:
#   1. Edit EXPERIMENTS — add/remove runs; set coordinated=True/False per run.
#   2. Edit SEEDS and DEMAND_SCALARS for replication / demand sweeps.
#   3. Run from Aimsun's "Run Script" menu (or Python console inside Aimsun).
#
# EXPERIMENT DICT KEYS:
#   name                — output folder prefix and display label
#   strategy            — NORMAL | URTSP | HARMONY | REWARD_TSP |
#                         GROUP_BASED | GROUP_BASED_URTSP | GROUP_BASED_HARMONY |
#                         DYNAOPAC | DYNAOPAC_HARMONY
#   coordinated         — True  → COORDINATED_TSP = True  (corridor coordination ON)
#                         False → COORDINATED_TSP = False (independent intersections)
#   active_intersections— None (all) or list of junction IDs e.g. [17383, 19196]
#
# LOGGING:
#   When batch mode starts ALL console/log flags in the controller are disabled:
#     VERBOSE = False
#     every LOG_* flag = False
#     STATUS_DASHBOARD_INTERVAL_S = 0
#     MARK_DETECTION_POINTS = False
#     OVERLAY_DETECTIONS_ON_MAP = False
#   The controller still writes results CSVs and summary.json regardless.
#   After the batch finishes all flags are restored to True.
#
# METRICS:
#   After every run the batch runner reads the controller's output CSVs and
#   appends a row to batch_results.csv in the project directory.  This gives
#   a single file that can be opened in Excel to compare all experiments.
# =============================================================================

import os as _os
import re
import json
import csv
import glob
import shutil
import sys as _sys
import time as _time
from PyANGKernel import GKSystem

# Script directory — used for dashboard import
_SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))

# Weighted-objective (Z1/Z2 composite) metric collection lives in
# collect_run_metrics() section 7 below: it reads the per-run
# logs/weighted_objective_<experiment>_<timestamp>.csv trace written by
# intersection_controller.py (already accumulated as sum-over-horizon totals —
# Z1_total/Z2_total/objective_total — via _accumulate_weighted_objective)
# and folds wobj_Z1_total/wobj_Z2_total/wobj_objective_total/alpha/beta/
# weights/rho plus total_weighted_delay/offset_correction_magnitude aliases
# into the run's metrics dict. Z4 (total travel time in the corridor, veh·h)
# is computed separately in the same section from
# Net_TotalTT_h_Car/Bus/Truck (already collected in section 1) as
# wobj_Z4_total / corridor_total_travel_time_veh_h. append_master_csv() then
# writes the merged metrics dict to batch_results.csv.



# =============================================================================
# ── EXPERIMENT DEFINITIONS ───────────────────────────────────────────────────
# =============================================================================

EXPERIMENTS = [
    # ── Baseline: no TSP — runs first to establish baseline before TSP runs ───
    {
        "name":              "NO_TSP",
        "enabled":           True,
        "strategy":          "NORMAL",
        "coordinated":       False,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
    },
    # ── DC TSP multi-agent — tuned weights (Hu et al. 2025) ────────────────────
    # Tuned: lower wh (0.6→0.45) so CPD delta gets more weight (0.55 vs 0.40).
    # This means bus-headway improvement is less dominant and the reward is more
    # sensitive to the actual pax·s saved vs car delay cost.
    {
        "name":              "DCTSP_MARL",
        "enabled":           False,  # DISABLED FOR THIS RUN
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":    True,
            "REWARD_ALPHA":          1.0,
            "REWARD_BETA":           1.0,
            "REWARD_GAMMA":          1.0,
            "REWARD_INV_DELAY_MODE": False,
            "DCTSP_GREEN_REALLOC_MODE": True,   # GR: zero net cost green reallocation
            "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            "DCTSP_W_H":             0.50,   # balanced: headway = pax delay
            "DCTSP_CAR_WEIGHT":      1.00,   # full car cost — per passenger
            "BUS_OCC_OVERRIDE":      None,   # use junction defaults (bus=40, car=1.2) — per passenger
            "WOBJ_Z1_SCALE":         3000000.0,
            "WOBJ_Z2_SCALE":         7500.0,
            "WOBJ_Z3_SCALE":         12000.0,
        },
    },
    # ── MARL + Harmony Search ──────────────────────────────────────────────────
    # MARL reward (GLOBAL_REWARD_MODE, tuned wh/car_weight) with Harmony Search
    # solving for the optimal continuous action duration via shockwave equations
    # instead of evaluating a discrete set {5,10,15} s.  HS searches [5,20] s
    # per action type (GR, GE, INS).
    {
        "name":              "DCTSP_MARL_HS",
        "enabled":           False,  # covered by PREDICTION_SWEEP
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":       True,
            "REWARD_SELFORG_MODE":      False,
            "REWARD_INV_DELAY_MODE":    False,
            "REWARD_V2X_MODE":          False,
            "DCTSP_ZIG_MODE":           False,
            "BARGAIN_SPM_MODE":         False,
            "META_TSP_MODE":            False,
            "MDN_DELAY_MODE":           False,
            "HS_EXT_MODE":              True,
            "DCTSP_GREEN_REALLOC_MODE": True,
            "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            "DCTSP_W_H":                0.50,   # balanced: headway = pax delay
            "DCTSP_CAR_WEIGHT":         1.00,   # full car cost — total delay
            "BUS_OCC_OVERRIDE":      1.0,
            "CAR_OCC_OVERRIDE":      1.0,
            "HS_EXT_T_MIN":             5.0,
            "HS_EXT_T_MAX":             20.0,
            "HS_EXT_HMS":               5,
            "HS_EXT_HMCR":              0.75,
            "HS_EXT_PAR":               0.35,
            "HS_EXT_BW":                2.0,
            "HS_EXT_NITER":             20,
            "WOBJ_Z1_SCALE":            3000000.0,
            "WOBJ_Z2_SCALE":            7500.0,
            "WOBJ_Z3_SCALE":            12000.0,
        },
    },
    # ── DC TSP inverse-delay reward variant ───────────────────────────────────
    # Action selection criterion:  r = 1 / (D̄_after + ε)
    # where D̄_after = (bus_delay_after × BusOcc + α_car × car_cost) / BusOcc.
    # Each intersection independently picks the action that minimises its
    # expected post-action average passenger delay.  This matches the inverse-
    # delay formulation used in several published MARL-TSP papers.
    {
        "name":              "DCTSP_INV_DELAY",
        "enabled":           False,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":    True,
            "REWARD_INV_DELAY_MODE": True,
            "INV_DELAY_EPSILON":     0.5,    # tuned: smaller epsilon → steeper reward surface
            "INV_DELAY_CAR_WEIGHT":  1.2,    # tuned: reduced from 2.0 → less car-cost aversion
            "INV_DELAY_MIN_DELAY_S": 3.0,   # tuned: reduced from 5s → act on smaller delays
            # NETWORK_FACTOR: corrects the local cross-traffic cost underestimate.
            # Previous runs: NF=1.0 → all DCTSP modes worse than NO_TSP (+114% for INV_DELAY).
            # NF=4.0 makes the reward penalise coordination disruption 4× more, preventing
            # TSP fires when car network impact > bus benefit.
            "NETWORK_FACTOR":        4.0,
        },
    },
    # ── DC TSP V2X / BOCS-inspired reward ─────────────────────────────────────
    # r = 1 / (D_total + C_crowd + ε)
    # D_total uses FULL bus-phase blocking (bp_dur + action_s + oc_s) so the
    # reward penalises total throughput impact on ALL road users, not just the
    # incremental delta.  Crowding penalty (BOCS Eq 21) added for overloaded bus.
    {
        "name":              "DCTSP_V2X",
        "enabled":           False,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE": True,
            "REWARD_V2X_MODE":    True,
            "V2X_MAX_BUS_OCC":    40.0,
            "V2X_CROWDING_SCALE": 10.0,
            "V2X_EPSILON":        0.5,    # tuned: smaller epsilon → more discriminating
            "V2X_MIN_DELAY_S":    8.0,    # tuned: raised threshold → only act on meaningful delay
            # NETWORK_FACTOR: corrects the local cross-traffic cost underestimate.
            # Root cause analysis: V2X D_total = (bus_cost + car_cost × CAR_WEIGHT) / bus_occ.
            # With bus_occ≈25, the car_cost is divided by 25 making it tiny vs bus_delay.
            # For INS_10 at 400vph×3ph, NF=2: car_term≈2.8s vs bus_delay≈30s → always fires.
            # Need NF=5 (same as ZIG) to scale car_term up to be meaningful:
            #   car_term = 0.7 × 100×5 / 25 = 14s → fires only when bus_delay > 14s (reasonable).
            # ZIG at NF=5 achieved 24.3% action rate; V2X at NF=5 targets ~25-30%.
            "NETWORK_FACTOR":     5.0,    # tuned: match ZIG's NF=5.0 for calibrated car costs
            "DCTSP_CAR_WEIGHT":   0.5,    # tuned: increase from 0.35 → less car-cost underestimate
            # V2X_BALANCE_FACTOR: ZIG-style pax·s cost-benefit guard.
            # Without it, car_term = car_pax/bus_occ ≈ 3-14s << bus_delay ≈ 30-80s → always fires.
            # With 0.50: block when car pax cost > 50% of bus pax savings (same as ZIG default).
            "V2X_BALANCE_FACTOR": 0.50,   # tuned: ZIG-equivalent balance threshold
        },
    },
    # ── DC TSP Self-Organizing (Cesme & Furth 2014 §4 + IEEE ICARCE 2023) ────
    # Self-organizing SE rule (Cesme & Furth 2014 §4) + phase-overlap correction
    # (IEEE ICARCE 2023: GTE for Phase Overlapping Intersections).
    # RL Q-table is bypassed entirely — purely deterministic rule-based control.
    # Acts whenever effective bus delay ≥ SELFORG_MIN_BUS_DELAY_S (5 s) AND
    # side-pressure / bus-pressure ratio ≤ SELFORG_BALANCE_FACTOR (1.0).
    # SELFORG_PHASE_OVERLAP_S: set to measured overlap duration at this site (0 = none).
    {
        "name":              "DCTSP_SELFORG",
        "enabled":           False,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":          True,
            "REWARD_SELFORG_MODE":         True,
            "REWARD_INV_DELAY_MODE":       False,
            "REWARD_V2X_MODE":             False,
            "SELFORG_MIN_BUS_DELAY_S":     12.0,  # tuned: raised threshold → only act on meaningful delays
            # SELFORG_BALANCE_FACTOR: PCE-weighted side_pressure/bus_pressure threshold.
            # Root cause of 78% action rate: pax·s comparison dominated by bus_occ≈25 vs
            # car_occ≈1.5 → ratio≈0.05 always ≤ any threshold → balance check trivially passes.
            # Second fix (this version): PCE-weighted comparison in intersection_controller.py:
            #   bus_side  = bus_delay × BUS_PCE (PCE≈3)
            #   car_side  = cross_veh_s = cross_pax_s / car_occ
            # Now SELFORG_BALANCE_FACTOR=0.85 matches Cesme & Furth (2014) original value.
            # With NF=3, 400 vph × 2 phases, car_occ=1.5: cross_veh_s≈48
            #   → blocked at bus_delay≈15s (ratio=1.07); fires at bus_delay≈20s (ratio=0.80)
            "SELFORG_BALANCE_FACTOR":      0.85,  # restored to Cesme & Furth original (PCE fix makes it meaningful)
            # SELFORG_MAX_SE_S: cap at 15s to match max GE action (DCTSP_GE_ACTIONS max = 15s).
            # Previous value 12s → always rounded to GE_10 regardless of bus delay.
            # With 15s: delay 12-20s → GE_10; delay 20s+ → GE_15 (more responsive to high delay).
            # For INS actions: DCTSP_INS_DURATIONS = [10, 15, 20]; 15s cap → rounds to INS_15 or INS_10.
            "SELFORG_MAX_SE_S":            15.0,  # fixed: was 12s, always picked GE_10 regardless of delay
            "SELFORG_MIN_SE_S":            5.0,
            "SELFORG_SE_FRACTION":         0.70,  # tuned: shorter SE relative to delay (was 0.90)
            "SELFORG_PHASE_OVERLAP_S":     0.0,
            # NETWORK_FACTOR corrects cross-traffic estimate underestimation.
            # NF=3.0: corridor amplification for PCE comparison (was 2.0 before PCE fix).
            # With NF=3.0 + PCE: balance check fires only when bus delay meaningfully exceeds
            # cross-traffic disruption in PCE-equivalent terms.
            "NETWORK_FACTOR":              3.0,   # tuned: corridor amplification (NF=3 matches INV_DELAY NF=4 at lower sensitivity)
        },
    },
    # ── DC TSP ZIG (Zero-Interference-Grant, shockwave-optimal) ──────────────
    # Replaces the discrete {5,10,15,20} s candidate search with a single
    # analytically-derived optimal duration from the LWR triangular fundamental
    # diagram (Newell 1993 / Daganzo 1994).
    # Action space: NO_ACTION, GE (shockwave-optimal), INS_POST (natural sequence),
    # INS_PRETERM (immediate phase termination + insertion).
    # Phase-overlap correction applied: ZIG_PHASE_OVERLAP_S = 0 (no overlap at this site).
    # Saturation avoidance: side_ratio > ZIG_BALANCE_FACTOR (1.0) → NO_ACTION.
    
    #todo wheres the delay values for car vs main vs bus vs side
    {
        "name":              "DCTSP_ZIG",
        "enabled":           True,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "SHOCKWAVE",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":     True,
            "REWARD_SELFORG_MODE":    False,
            "REWARD_INV_DELAY_MODE":  False,
            "REWARD_V2X_MODE":        False,
            "DCTSP_ZIG_MODE":         True,
            "ZIG_PHASE_OVERLAP_S":    0.5,    # set to overlap duration if applicable
            # ZIG_BALANCE_FACTOR is now the COST-BENEFIT threshold (not OtherDelay ratio).
            # With fixed saturation avoidance (uses car_pax_cost / bus_pax_saved):
            #   0.75 → fire only when car network cost < 75% of bus saving
            #   0.50 → more conservative: fire only when car cost < 50% of bus saving
            # Previous runs: broken OtherDelay check never triggered → ZIG fired
            # every detection at MAX duration → +256% entry delay vs NO_TSP.
            "ZIG_BALANCE_FACTOR":     0.50,   # tuned: conservative cost-benefit threshold
            # NETWORK_FACTOR: corrects local cross-traffic cost underestimate.
            # NF=5.0 makes ZIG's cost-benefit ratio realistic for corridor spillback.
            "NETWORK_FACTOR":         5.0,
        },
    },
    # ── DC TSP MP-ECTM (Mathematical Programming + Enhanced CTM) ─────────────
    # Minimises total passenger delay Z = Σ_t [α_bus×n_bus(t) + α_car×D_side(t)]×Δt
    # over one cycle horizon by grid-searching extension δ ∈ [3, 20] s.
    # Bus-approach queue simulated with 1D CTM (ECTM Eq. 2-9, 21-23); action type
    # (GE / INS_POST / INS_PRETERM) and duration δ* jointly selected to minimise Z.
    # Reference: Bao et al. (2026) Transportmetrica B 14(1) 2625383.
    {
        "name":              "DCTSP_MP_ECTM",
        "enabled":           False,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":     True,
            "REWARD_SELFORG_MODE":    False,
            "REWARD_INV_DELAY_MODE":  False,
            "REWARD_V2X_MODE":        False,
            "DCTSP_ZIG_MODE":         False,
            "MP_ECTM_MODE":           True,
            "MP_ECTM_DT_S":           1.0,    # CTM time step (s)
            "MP_ECTM_MIN_EXT_S":      3.0,    # minimum extension (s)
            "MP_ECTM_MAX_EXT_S":      8.0,    # tuned: short max — minimise network cycle disruption
            "MP_ECTM_CAR_OCC":        1.6,    # tuned: higher car weight → Z-function favours fewer/shorter actions
            "MP_ECTM_BALANCE_FACTOR": 0.75,   # tuned: stricter guard → less cross-street spillback
        },
    },
    # ── DC TSP BXT (Chanloha et al. 2014, Comput. J. 57(3) 451-466) ──────────
    # CTM-based multiagent Q-learning.  Reward = negative red-light delay
    # ϒ(t) = Σ n_i(t)·Δt·occ_i for all approaches facing red (Eq. 29-32).
    # ε-greedy Q-table (ε=0.1, α=0.01, γ=0.005 per paper Table 1).
    # State: (bus_queue_bin, side_ratio_bin, phase_bin, eta_bin) → 128 states.
    # Separate Q-table from MARL; same 7-action space.
    # DOI: 10.1093/comjnl/bxt126
    {
        "name":              "DCTSP_BXT",
        "enabled":           False,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":     True,
            "REWARD_SELFORG_MODE":    False,
            "REWARD_INV_DELAY_MODE":  False,
            "REWARD_V2X_MODE":        False,
            "DCTSP_ZIG_MODE":         False,
            "MP_ECTM_MODE":           False,
            "BXT_MODE":               True,
            "BXT_DT_S":               1.0,    # CTM time step Δt (s)
            "BXT_EPSILON":            0.05,   # tuned: less exploration → faster exploitation of good actions
            "BXT_ALPHA":              0.05,   # tuned: faster learning (was 0.01) → converge in 1 seed
            "BXT_GAMMA":              0.01,   # tuned: slightly higher discount
            "BXT_CAR_OCC":            1.2,    # average car occupancy (pax/veh)
            "BXT_BALANCE_FACTOR":     1.1,    # tuned: slightly relaxed saturation guard
        },
    },
    # ── DCTSP Bargaining-SPM (TRC 2025 inspired) ─────────────────────────────
    # Cooperative phase bargaining with ETA-tiered bus bargaining weights and
    # stochastic shockwave risk scaling from live cross-flow variability.
    # Uses existing ETA detection levels (5/15/30 s) as bargaining stages.
    #
    # V3 fixes (current):
    #   - mc_mult NOT applied to phases=[0] (main approach savings no longer inflated)
    #   - BG_MIN_GAIN_S raised 2.5→5.0 (more selective)
    #   - BG_CASCADE_MULT raised 1.5→2.0 (realistic cascade penalty)
    #   - DCTSP_CONGESTION_GATE=True at fraction=0.75 (suppress TSP at saturated intersections)
    # V4 fix (intersection_controller.py — no new run_config params):
    #   - INS/ER never chosen when bus_pax_saved_s==0 (bus can't catch inserted window)
    #     Prevents TSP firing for main-car-savings alone when bus gets no benefit
    #     Root cause of +16% vs NO_TSP: 122 INS many with bus_save=0 harming jcts 39593/39576/36393
    {
        "name":              "DCTSP_BARGAIN_SPM",
        "enabled":           False,  # covered by PREDICTION_SWEEP
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "SHOCKWAVE",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":       True,
            "REWARD_SELFORG_MODE":      False,
            "REWARD_INV_DELAY_MODE":    False,
            "REWARD_V2X_MODE":          False,
            "DCTSP_ZIG_MODE":           False,
            "MP_ECTM_MODE":             False,
            "BXT_MODE":                 False,
            "META_TSP_MODE":            False,
            "MDN_DELAY_MODE":           False,
            "BARGAIN_SPM_MODE":         True,
            "DCTSP_GREEN_REALLOC_MODE": True,
            "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            "BG_DET_LVL_IMM_S":         4.0,
            "BG_DET_LVL_NEAR_S":        12.0,
            "BG_DET_LVL_FAR_S":         24.0,
            "BG_BUS_W_IMM":             1.6,
            "BG_BUS_W_NEAR":            1.35,
            "BG_BUS_W_FAR":             1.10,
            "BG_BUS_W_VFAR":            0.95,
            "BG_SPM_RISK_WEIGHT":       1.8,
            "BG_EQ_FAIRNESS_WEIGHT":    0.55,
            "BG_MIN_BUS_DELAY_S":       5.0,    # V4: lowered from 10→5 (eff_sigma fix makes small delays worthwhile)
            "BG_MIN_GAIN_S":            5.0,
            "BG_CASCADE_MULT":          2.0,
            "BG_MB_WEIGHT":             0.30,
            "DCTSP_CONGESTION_GATE":    True,   # V3: suppress TSP at saturated crossings
            "DCTSP_CONGESTION_GATE_FRACTION": 0.75,
            "REWARD_SIDE_SECTION_WEIGHT": 0.5,  # MP: side traffic delay at half main weight
        },
    },
    # ── DCTSP_HSExt: Harmony-Search duration optimizer ────────────────────────
    # Same as BARGAIN_SPM but replaces discrete GE/GR/INS candidate loops with
    # a Harmony Search (Geem et al. 2001) that finds the continuous optimal
    # action duration in [5, 20] s for each of GR, GE, INS (PI) independently.
    # ER is NOT evaluated in HS mode (user spec: only GR, GE, PI).
    {
        "name":              "DCTSP_HSExt",
        "enabled":           False,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":       True,
            "REWARD_SELFORG_MODE":      False,
            "REWARD_INV_DELAY_MODE":    False,
            "REWARD_V2X_MODE":          False,
            "DCTSP_ZIG_MODE":           False,
            "MP_ECTM_MODE":             False,
            "BXT_MODE":                 False,
            "META_TSP_MODE":            False,
            "MDN_DELAY_MODE":           False,
            "BARGAIN_SPM_MODE":         True,
            "HS_EXT_MODE":              True,   # enable Harmony Search optimizer
            "DCTSP_GREEN_REALLOC_MODE": True,
            "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            "BG_DET_LVL_IMM_S":         4.0,
            "BG_DET_LVL_NEAR_S":        12.0,
            "BG_DET_LVL_FAR_S":         24.0,
            "BG_BUS_W_IMM":             1.6,
            "BG_BUS_W_NEAR":            1.35,
            "BG_BUS_W_FAR":             1.10,
            "BG_BUS_W_VFAR":            0.95,
            "BG_SPM_RISK_WEIGHT":       1.8,
            "BG_EQ_FAIRNESS_WEIGHT":    0.55,
            "BG_MIN_BUS_DELAY_S":       5.0,
            "BG_MIN_GAIN_S":            5.0,
            "BG_CASCADE_MULT":          2.0,
            "BG_MB_WEIGHT":             0.30,
            "DCTSP_CONGESTION_GATE":    True,
            "DCTSP_CONGESTION_GATE_FRACTION": 0.75,
            "REWARD_SIDE_SECTION_WEIGHT": 0.5,  # MP: side traffic delay at half main weight
            # HS tuning parameters
            "HS_EXT_T_MIN":             5.0,    # minimum action duration (s); < 5 → rejected
            "HS_EXT_T_MAX":             20.0,   # hard cap on action duration (s)
            "HS_EXT_HMS":               5,      # Harmony Memory Size
            "HS_EXT_HMCR":              0.75,   # Memory Consideration Rate
            "HS_EXT_PAR":               0.35,   # Pitch Adjustment Rate
            "HS_EXT_BW":                2.0,    # Pitch bandwidth (seconds)
            "HS_EXT_NITER":             20,     # iterations per action type
        },
    },
    # ── BARGAIN_SPM parameter sweep variants ──────────────────────────────────
    # Enable one or more to compare tuning configurations.
    # mc_mult NOT applied to phases=[0] in all variants (V3 code fix).
    # Vary: BG_MIN_GAIN_S, BG_CASCADE_MULT, DCTSP_CONGESTION_GATE_FRACTION.
    {
        "name":              "DCTSP_SPM_V3_NOGATE",
        "enabled":           False,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE": True, "BARGAIN_SPM_MODE": True,
            "DCTSP_GREEN_REALLOC_MODE": True, "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            "BG_DET_LVL_IMM_S": 4.0, "BG_DET_LVL_NEAR_S": 12.0, "BG_DET_LVL_FAR_S": 24.0,
            "BG_BUS_W_IMM": 1.6, "BG_BUS_W_NEAR": 1.35, "BG_BUS_W_FAR": 1.10, "BG_BUS_W_VFAR": 0.95,
            "BG_SPM_RISK_WEIGHT": 1.8, "BG_EQ_FAIRNESS_WEIGHT": 0.55,
            "BG_MIN_BUS_DELAY_S": 10.0,
            "BG_MIN_GAIN_S":     5.0,   # same as base
            "BG_CASCADE_MULT":   2.0,   # same as base
            "BG_MB_WEIGHT":      0.30,
            "DCTSP_CONGESTION_GATE": False,  # gate OFF — mc_mult fix alone
        },
    },
    {
        "name":              "DCTSP_SPM_V3_STRICT",
        "enabled":           False,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE": True, "BARGAIN_SPM_MODE": True,
            "DCTSP_GREEN_REALLOC_MODE": True, "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            "BG_DET_LVL_IMM_S": 4.0, "BG_DET_LVL_NEAR_S": 12.0, "BG_DET_LVL_FAR_S": 24.0,
            "BG_BUS_W_IMM": 1.6, "BG_BUS_W_NEAR": 1.35, "BG_BUS_W_FAR": 1.10, "BG_BUS_W_VFAR": 0.95,
            "BG_SPM_RISK_WEIGHT": 1.8, "BG_EQ_FAIRNESS_WEIGHT": 0.55,
            "BG_MIN_BUS_DELAY_S": 10.0,
            "BG_MIN_GAIN_S":     8.0,   # raised: require larger benefit before acting
            "BG_CASCADE_MULT":   2.0,
            "BG_MB_WEIGHT":      0.30,
            "DCTSP_CONGESTION_GATE": True,
            "DCTSP_CONGESTION_GATE_FRACTION": 0.75,
        },
    },
    {
        "name":              "DCTSP_SPM_V3_CASCADE",
        "enabled":           False,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE": True, "BARGAIN_SPM_MODE": True,
            "DCTSP_GREEN_REALLOC_MODE": True, "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            "BG_DET_LVL_IMM_S": 4.0, "BG_DET_LVL_NEAR_S": 12.0, "BG_DET_LVL_FAR_S": 24.0,
            "BG_BUS_W_IMM": 1.6, "BG_BUS_W_NEAR": 1.35, "BG_BUS_W_FAR": 1.10, "BG_BUS_W_VFAR": 0.95,
            "BG_SPM_RISK_WEIGHT": 1.8, "BG_EQ_FAIRNESS_WEIGHT": 0.55,
            "BG_MIN_BUS_DELAY_S": 10.0,
            "BG_MIN_GAIN_S":     5.0,
            "BG_CASCADE_MULT":   2.5,   # raised: more conservative cascade penalty
            "BG_MB_WEIGHT":      0.30,
            "DCTSP_CONGESTION_GATE": True,
            "DCTSP_CONGESTION_GATE_FRACTION": 0.75,
        },
    },
    {
        "name":              "DCTSP_SPM_V3_CONSERVATIVE",
        "enabled":           False,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE": True, "BARGAIN_SPM_MODE": True,
            "DCTSP_GREEN_REALLOC_MODE": True, "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            "BG_DET_LVL_IMM_S": 4.0, "BG_DET_LVL_NEAR_S": 12.0, "BG_DET_LVL_FAR_S": 24.0,
            "BG_BUS_W_IMM": 1.6, "BG_BUS_W_NEAR": 1.35, "BG_BUS_W_FAR": 1.10, "BG_BUS_W_VFAR": 0.95,
            "BG_SPM_RISK_WEIGHT": 1.8, "BG_EQ_FAIRNESS_WEIGHT": 0.55,
            "BG_MIN_BUS_DELAY_S": 10.0,
            "BG_MIN_GAIN_S":     8.0,   # strict gain gate
            "BG_CASCADE_MULT":   2.5,   # strict cascade penalty
            "BG_MB_WEIGHT":      0.30,
            "DCTSP_CONGESTION_GATE": True,
            "DCTSP_CONGESTION_GATE_FRACTION": 0.70,  # stricter congestion gate
        },
    },
    {
        "name":              "DCTSP_SPM_V3_TIGHTEST",
        "enabled":           False,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE": True, "BARGAIN_SPM_MODE": True,
            "DCTSP_GREEN_REALLOC_MODE": True, "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            "BG_DET_LVL_IMM_S": 4.0, "BG_DET_LVL_NEAR_S": 12.0, "BG_DET_LVL_FAR_S": 24.0,
            "BG_BUS_W_IMM": 1.6, "BG_BUS_W_NEAR": 1.35, "BG_BUS_W_FAR": 1.10, "BG_BUS_W_VFAR": 0.95,
            "BG_SPM_RISK_WEIGHT": 2.5,  # higher risk aversion
            "BG_EQ_FAIRNESS_WEIGHT": 0.55,
            "BG_MIN_BUS_DELAY_S": 12.0, # higher bus delay threshold
            "BG_MIN_GAIN_S":     12.0,  # very strict gain gate
            "BG_CASCADE_MULT":   3.0,   # strong cascade penalty
            "BG_MB_WEIGHT":      0.30,
            "DCTSP_CONGESTION_GATE": True,
            "DCTSP_CONGESTION_GATE_FRACTION": 0.65,  # most aggressive gate
        },
    },
    # ── META_TSP: System-optimal adaptive transit signal priority ─────────────
    # Minimises TOTAL system passenger delay (bus + car + truck) using CTM
    # queue simulation with an adaptive bus weight that scales with headway
    # deviation (schedule lateness).  Bus priority is applied only when the
    # net benefit to all passengers exceeds META_MIN_THRESHOLD_PAX_S.
    #
    # Key design parameters:
    #   META_BASE_BUS_WEIGHT   = 1.0  → equal treatment when on-time
    #   META_HW_SENSITIVITY    = 1.5  → up to 1.5× extra weight when severely late
    #   META_HW_REF_S          = 60   → full sensitivity at 60 s headway deviation
    #   META_MIN_THRESHOLD_PAX_S = 18 → min net pax·s benefit to commit to TSP
    #   META_BALANCE_FACTOR    = 0.85 → strict saturation guard
    #   META_MIN_BUS_DELAY_S   = 8.0  → only act on meaningful bus delays
    #   META_OC_WEIGHT         = 0.4  → multi-horizon OC-recovery penalty weight
    #
    # References:
    #   Bao et al. (2026) Transportmetrica B — total pax-delay objective
    #   Hu et al. (2025) DCTSP — headway-adaptive weighting (Eq. 6)
    #   Chanloha et al. (2014) Comput. J. 57(3) — CTM queue simulation
    #   Newell (1993) / Daganzo (1994) — LWR shockwave-optimal duration
    {
        "name":              "DCTSP_META_TSP",
        "enabled":           False,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "SHOCKWAVE",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":       True,
            "REWARD_SELFORG_MODE":      False,
            "REWARD_INV_DELAY_MODE":    False,
            "REWARD_V2X_MODE":          False,
            "DCTSP_ZIG_MODE":           False,
            "MP_ECTM_MODE":             False,
            "BXT_MODE":                 False,
            "META_TSP_MODE":            True,
            "META_DT_S":                1.0,    # CTM time step (s)
            "META_BASE_BUS_WEIGHT":     1.0,    # bus weight when on-time (= car)
            "META_HW_SENSITIVITY":      1.5,    # max additional weight when late
            "META_HW_REF_S":            60.0,   # full sensitivity at 60 s deviation
            "META_MIN_THRESHOLD_PAX_S": 18.0,  # tuned: higher net benefit required → fewer interventions
            "META_BALANCE_FACTOR":      0.85,  # tuned: strict guard → prevent cross-street saturation spillback
            "META_MIN_BUS_DELAY_S":     8.0,   # tuned: only act on meaningful bus delays
            "META_OC_WEIGHT":           0.4,    # OC-recovery cost lookahead weight
            "META_CAR_OCC":             1.2,    # tuned: higher car weight → system-optimal cost more conservative
        },
    },
    # ── DC TSP Conservative (ultra-low-overhead, network-delay-aware) ─────────
    # Variant of MP-ECTM with very short maximum action duration (5 s) and a
    # ── DCTSP-MDN (Zhu et al. 2026, JTEPBS.TEENG-9465) ──────────────────────
    # Movement-Wise Delay Distribution Estimation reward using an analytical
    # 3-component Mixture Density Network (MDN) approximation.
    #
    # Unlike all other DCTSP modes that evaluate only the *incremental* cost
    # of a TSP action on cross-traffic, the MDN mode estimates the *total*
    # expected person-delay across ALL intersection approaches under each
    # candidate action (vs the current-status no-action baseline).  This
    # provides a proper current-status vs strategy comparison.
    #
    # Per-approach delay model (Zhu et al. 2026 §"Distribution Modeling"):
    #   K=3 mixture components — free-flow (π₀,μ≈0), uniform-stop (π₁,μ=r/2),
    #   overflow (π₂,μ=N_res/q_d).  Movement-Wise Coefficient (MWC) adapts
    #   weights per approach from v/c and g/C ratios.
    #   Delay Distribution Transform (DDT, Eq.7): z = y^0.5 stabilises the
    #   heavy-tailed distribution; E[y] recovered via inverse transform E[y]=(Σπ√μ)².
    #
    # Reward: R = w_hw × Δheadway + (1-w_hw) × (mdn_NO_ACTION − mdn_action) / bus_occ
    #   Delta-based formula — same scale as MARL (pax·s), no 2.0 cap.
    #
    # References:
    #   Zhu et al. (2026) J. Transp. Eng., Part A: Systems 152(4): 04026007
    {
        "name":              "DCTSP_MDN",
        "enabled":           False,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "SHOCKWAVE",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":    True,
            "REWARD_SELFORG_MODE":   False,
            "REWARD_INV_DELAY_MODE": False,
            "REWARD_V2X_MODE":       False,
            "DCTSP_ZIG_MODE":        False,
            "MP_ECTM_MODE":          False,
            "BXT_MODE":              False,
            "META_TSP_MODE":         False,
            "MDN_DELAY_MODE":        True,
            "MDN_DDT_POWER":         0.5,    # DDT power transform p (Zhu et al. default)
            "MDN_N_COMPONENTS":      3,      # K=3 mixture components
            "MDN_EPSILON":           0.5,    # legacy — no longer used in reward (delta formula)
        },
    },
    # ── Centralised per-second corridor controller (Method 0 in paper) ──────────
    # Bypasses bus-triggered detection entirely; instead evaluates all 12
    # intersections every 1 s via _centralized_corridor_step() (AAPIPostManage).
    # Bus positions are read directly from Aimsun PT API — no AVL/GPS dependency.
    # Equivalent to perfect real-time location knowledge at 1 Hz resolution.
    # Per-junction update() returns immediately when CENTRALIZED_MODE=True.
    # coord_algo=KALMAN is used only for the bus ETA predictor sub-step inside
    # _centralized_corridor_step(); the main action logic is rule-based (HOLD /
    # TRANSITION / PHASE_ROTATION based on ETA, phase state, and flow estimates).
    #
    # PREREQUISITE: 4 junctions (39576, 38339, 36393, 36385) must have Control Type
    # set to "External" in the Aimsun scenario editor. Otherwise they return
    # ControlType=-2007 and the centralized controller cannot override phases.
    {
        "name":              "CENTRALISED",
        "enabled":           False,  # DISABLED FOR THIS RUN
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":    True,
            "CENTRALIZED_MODE":      True,
            "CENTRALIZED_INTERVAL_S": 1.0,
        },
    },
    # ── Other experiments (uncomment to include in a run) ─────────────────────
    # {
    #     "name":              "DCTSP_QUEUE_MODEL",
    #     "strategy":          "GLOBAL_REWARD",
    #     "coordinated":       True,
    #     "coordination_algo": "KALMAN",
    #     "active_intersections": None,
    #     "reward_overrides": {
    #         "GLOBAL_REWARD_MODE":      True,
    #         "REWARD_SELFORG_MODE":     False,
    #         "REWARD_INV_DELAY_MODE":   False,
    #         "REWARD_V2X_MODE":         False,
    #         "DCTSP_ZIG_MODE":          False,
    #         "MP_ECTM_MODE":            False,
    #         "BXT_MODE":                False,
    #         "META_TSP_MODE":           False,
    #         "MDN_DELAY_MODE":          False,
    #         "QUEUE_MODEL_MODE":        True,
    #         "QUEUE_MODEL_SAT_FLOW_VPH": 1800.0,  # saturation flow (veh/h); tune if needed
    #     },
    # },
    # {
    #     "name": "GLOBAL_REWARD",
    #     "strategy": "GLOBAL_REWARD",
    #     "coordinated": True,
    #     "coordination_algo": "KALMAN",
    #     "active_intersections": None,
    #     "reward_overrides": {"GLOBAL_REWARD_MODE": True},
    # },
    # {
    #     "name": "LOCAL_REWARD",
    #     "strategy": "GLOBAL_REWARD",
    #     "coordinated": True,
    #     "coordination_algo": "KALMAN",
    #     "active_intersections": None,
    #     "reward_overrides": {"GLOBAL_REWARD_MODE": False},
    # },
    # {
    #     "name":                 "HARMONY_INDEP",
    #     "strategy":             "HARMONY",
    #     "coordinated":          False,
    #     "coordination_algo":    "KALMAN",
    #     "active_intersections": None,
    # },
    # {
    #     "name":                 "HARMONY_COORD",
    #     "strategy":             "HARMONY",
    #     "coordinated":          True,
    #     "coordination_algo":    "KALMAN",
    #     "active_intersections": None,
    # },
    # {
    #     "name":                 "DRL_DENSITY",
    #     "strategy":             "DRL_DENSITY",
    #     "coordinated":          True,
    #     "coordination_algo":    "ADAPTIVE",
    #     "active_intersections": None,
    #     "reward_overrides": {
    #         "REWARD_ALPHA": 1.0, "REWARD_BETA": 0.75,
    #         "REWARD_GAMMA": 0.50, "REWARD_DENSITY": 0.25,
    #     },
    # },
]

# ── Weighted-objective (Z1/Z2) weight sweep ──────────────────────────────────
# Generates one experiment per (ALPHA, BETA) combo so a batch run traces the
# Pareto frontier of total_weighted_delay (Z1) vs offset_correction_magnitude
# (Z2) — see collect_run_metrics() section 7 for how those are read back from
# each run's weighted_objective trace CSV. Each combo overrides WOBJ_ALPHA/
# WOBJ_BETA via reward_overrides -> run_config.py -> intersection_controller's
# per-replication global refresh (AAPISimulationReady). Flip WOBJ_SWEEP_ENABLED
# to include the sweep in a batch run.
WOBJ_SWEEP_ENABLED = False              # was True — not needed for slides
WOBJ_SWEEP_ALPHAS  = [0.7, 0.8, 0.9]
WOBJ_SWEEP_BETAS   = [0.1, 0.2, 0.3]
for _wa in WOBJ_SWEEP_ALPHAS:
    for _wb in WOBJ_SWEEP_BETAS:
        EXPERIMENTS.append({
            "name":              f"WOBJ_SWEEP_A{_wa:.1f}_B{_wb:.1f}".replace(".", ""),
            "enabled":           WOBJ_SWEEP_ENABLED,
            "strategy":          "GLOBAL_REWARD",
            "coordinated":       True,
            "coordination_algo": "KALMAN",
            "active_intersections": None,
            "reward_overrides": {
                "GLOBAL_REWARD_MODE": True,
                "WOBJ_ALPHA":         _wa,
                "WOBJ_BETA":          _wb,
            },
        })

# ── ZIG main-vs-secondary objective sensitivity sweep ─────────────────────────
# Sweeps WOBJ_ALPHA (main objective weight — now propagates to REWARD_BETA/
# REWARD_GAMMA, controlling bus-vs-cross-traffic tradeoff) × WOBJ_BETA
# (secondary objective weight — offset-correction penalty, Z2).  ZIG mode
# provides the cost-benefit gating layer; the WOBJ weights determine the
# underlying reward shape.
# ── MARL_HS main-vs-secondary objective sensitivity sweep ──────────────────────
# Sweeps WOBJ_ALPHA × WOBJ_BETA for the MARL+Harmony Search strategy.
# MARL_HS uses the MARL reward (GLOBAL_REWARD_MODE, wh=0.45, car_weight=0.35)
# with Harmony Search solving for the optimal continuous action duration via
# shockwave equations instead of discrete candidates {5,10,15}s.
#   WOBJ_ALPHA → propagates to REWARD_BETA/REWARD_GAMMA (bus-vs-cross-traffic)
#   WOBJ_BETA  → offset-correction penalty (Z2, progression quality)
MARL_HS_SWEEP_ENABLED       = False
MARL_HS_SWEEP_WOBJ_ALPHAS   = [0.6, 0.8, 1.0]
MARL_HS_SWEEP_WOBJ_BETAS    = [0.1, 0.3, 0.5]
for _ma in MARL_HS_SWEEP_WOBJ_ALPHAS:
    for _mb in MARL_HS_SWEEP_WOBJ_BETAS:
        EXPERIMENTS.append({
            "name":              f"MARL_HS_SWEEP_A{_ma:.1f}_B{_mb:.1f}".replace(".", ""),
            "enabled":           MARL_HS_SWEEP_ENABLED,
            "strategy":          "GLOBAL_REWARD",
            "coordinated":       True,
            "coordination_algo": "KALMAN",
            "active_intersections": None,
            "reward_overrides": {
                "GLOBAL_REWARD_MODE":       True,
                "REWARD_SELFORG_MODE":      False,
                "REWARD_INV_DELAY_MODE":    False,
                "REWARD_V2X_MODE":          False,
                "DCTSP_ZIG_MODE":           False,
                "BARGAIN_SPM_MODE":         False,
                "META_TSP_MODE":            False,
                "MDN_DELAY_MODE":           False,
                "HS_EXT_MODE":              True,
                "DCTSP_GREEN_REALLOC_MODE": True,
                "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
                "DCTSP_W_H":                0.45,
                "DCTSP_CAR_WEIGHT":         0.35,
                "HS_EXT_T_MIN":             5.0,
                "HS_EXT_T_MAX":             20.0,
                "HS_EXT_HMS":               5,
                "HS_EXT_HMCR":              0.75,
                "HS_EXT_PAR":               0.35,
                "HS_EXT_BW":                2.0,
                "HS_EXT_NITER":             20,
                "WOBJ_ALPHA":               _ma,
                "WOBJ_BETA":                _mb,
            },
        })

# ── ZIG Game-Theory sensitivity sweep ─────────────────────────────────────────
# Sweeps ZIG_BALANCE_FACTOR (cost-benefit threshold gate) × NETWORK_FACTOR
# (cross-traffic amplification).  Lower BALANCE → fewer TSP grants (more
# conservative).  Higher NETWORK_FACTOR → heavier penalty on cross-traffic.
# ZIG uses discrete candidate evaluation {5,10,15}s with shockwave-optimal
# duration selection — the simplest and most interpretable game-theoretic method.
ZIG_SWEEP_ENABLED          = False            # was True — not needed for slides
ZIG_SWEEP_BALANCE_FACTORS  = [0.25, 0.50, 0.75, 1.00]
ZIG_SWEEP_NETWORK_FACTORS  = [3.0, 5.0, 7.0]
for _zbf in ZIG_SWEEP_BALANCE_FACTORS:
    for _znf in ZIG_SWEEP_NETWORK_FACTORS:
        EXPERIMENTS.append({
            "name":              f"ZIG_SWEEP_B{_zbf:.2f}_N{_znf:.1f}".replace(".", ""),
            "enabled":           ZIG_SWEEP_ENABLED,
            "strategy":          "GLOBAL_REWARD",
            "coordinated":       True,
            "coordination_algo": "SHOCKWAVE",
            "active_intersections": None,
            "reward_overrides": {
                "GLOBAL_REWARD_MODE":     True,
                "REWARD_SELFORG_MODE":    False,
                "DCTSP_ZIG_MODE":         True,
                "ZIG_PHASE_OVERLAP_S":    0.5,
                "ZIG_BALANCE_FACTOR":     _zbf,
                "NETWORK_FACTOR":         _znf,
            },
        })

# ── Main-vs-Side corridor priority weight sweep ────────────────────────────────
# Sweeps REWARD_MAIN_SECTION_WEIGHT (w_main) × REWARD_SIDE_SECTION_WEIGHT (w_side).
# Higher w_main → prioritises corridor traffic (buses + main-road cars).
# Higher w_side → protects cross-street traffic from TSP disruption.
# This directly targets the Z₁ objective's main-vs-side passenger delay tradeoff.
# Uses ZIG mode (DCTSP_ZIG_MODE = True) with fixed BALANCE=0.50, NETWORK=5.0
# so the sensitivity is purely about corridor-vs-cross-street priority.
MAIN_SIDE_SWEEP_ENABLED = False           # was True — not needed for slides
MAIN_SIDE_SWEEP_W_MAIN  = [0.5, 0.8, 1.0]
MAIN_SIDE_SWEEP_W_SIDE  = [0.3, 0.6, 0.9]
for _wm in MAIN_SIDE_SWEEP_W_MAIN:
    for _ws in MAIN_SIDE_SWEEP_W_SIDE:
        EXPERIMENTS.append({
            "name":              f"MAINSIDE_SWEEP_WM{_wm:.1f}_WS{_ws:.1f}".replace(".", ""),
            "enabled":           MAIN_SIDE_SWEEP_ENABLED,
            "strategy":          "GLOBAL_REWARD",
            "coordinated":       True,
            "coordination_algo": "SHOCKWAVE",
            "active_intersections": None,
            "reward_overrides": {
                "GLOBAL_REWARD_MODE":         True,
                "REWARD_SELFORG_MODE":        False,
                "DCTSP_ZIG_MODE":             True,
                "ZIG_PHASE_OVERLAP_S":        0.5,
                "ZIG_BALANCE_FACTOR":         0.50,
                "NETWORK_FACTOR":             5.0,
                "REWARD_MAIN_SECTION_WEIGHT": _wm,
                "REWARD_SIDE_SECTION_WEIGHT": _ws,
            },
        })

# ── MDN Reinforcement-Learning sensitivity sweep ──────────────────────────────
# Vary the Delay Distribution Transform power p (MDN_DDT_POWER) and the number
# of Gaussian mixture components (MDN_N_COMPONENTS).  Higher p → skews delay
# distribution toward higher values (more conservative).  More components →
# finer delay modelling.
MDN_SWEEP_ENABLED      = False
MDN_SWEEP_DDT_POWERS   = [0.25, 0.50, 0.75]
MDN_SWEEP_COMPONENTS   = [2, 3, 4]
for _mp in MDN_SWEEP_DDT_POWERS:
    for _mc in MDN_SWEEP_COMPONENTS:
        EXPERIMENTS.append({
            "name":              f"MDN_SWEEP_P{_mp:.2f}_C{_mc}".replace(".", ""),
            "enabled":           MDN_SWEEP_ENABLED,
            "strategy":          "GLOBAL_REWARD",
            "coordinated":       True,
            "coordination_algo": "SHOCKWAVE",
            "active_intersections": None,
            "reward_overrides": {
                "GLOBAL_REWARD_MODE":    True,
                "REWARD_SELFORG_MODE":   False,
                "DCTSP_ZIG_MODE":        False,
                "BARGAIN_SPM_MODE":      False,
                "HS_EXT_MODE":           False,
                "META_TSP_MODE":         False,
                "MDN_DELAY_MODE":        True,
                "MDN_DDT_POWER":         _mp,
                "MDN_N_COMPONENTS":      _mc,
            },
        })

# ── HS_EXT Harmony-Search sensitivity sweep ───────────────────────────────────
# Vary the exploration/exploitation balance of the Geem et al. (2001) HS
# metaheuristic.  HMCR = Harmony Memory Consideration Rate (higher = exploit
# more); PAR = Pitch Adjustment Rate (higher = explore more).  Both affect the
# optimal GE/INS duration found by the solver.
HS_EXT_SWEEP_ENABLED  = False
HS_EXT_SWEEP_HMCR     = [0.50, 0.75, 0.90]
HS_EXT_SWEEP_PAR      = [0.10, 0.35, 0.60]
for _hmcr in HS_EXT_SWEEP_HMCR:
    for _par in HS_EXT_SWEEP_PAR:
        EXPERIMENTS.append({
            "name":              f"HSEXT_SWEEP_H{_hmcr:.2f}_P{_par:.2f}".replace(".", ""),
            "enabled":           HS_EXT_SWEEP_ENABLED,
            "strategy":          "GLOBAL_REWARD",
            "coordinated":       True,
            "coordination_algo": "SHOCKWAVE",
            "active_intersections": None,
            "reward_overrides": {
                "GLOBAL_REWARD_MODE":       True,
                "BARGAIN_SPM_MODE":         True,
                "HS_EXT_MODE":              True,
                "DCTSP_GREEN_REALLOC_MODE": True,
                "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
                "HS_EXT_HMCR":             _hmcr,
                "HS_EXT_PAR":              _par,
            },
        })

# ── Bus Priority Sensitivity sweep ────────────────────────────────────────────
# Sweeps the thresholds that control *when* bus priority is granted.
#
#   META_MIN_BUS_DELAY_S      — minimum bus delay (s) before TSP is considered.
#     0  = always consider TSP (even if bus is on time)
#     10 = only late buses (>10s behind schedule) get priority
#     20 = only very late buses (>20s behind) get priority
#
#   META_MIN_THRESHOLD_PAX_S  — minimum net passenger-second benefit required.
#     0  = grant priority for any positive net benefit
#     10 = only grant when net benefit ≥ 10 pax·s
#     40 = only grant substantial benefits
#
#   META_LATENESS_TAKEOVER_S  — bus lateness (headway deviation s) that forces
#     unconditional TSP, bypassing both the min-delay and saturation gates.
#     60  = takeover at >1min late
#     120 = takeover at >2min late
#     9999 = never takeover (disabled — normal gating applies)
#
# Combined, these three parameters define the "bus priority sensitivity profile":
#   high sensitivity (low thresholds) = grant priority generously
#   low sensitivity  (high thresholds) = grant only when clearly justified
#
# Uses META_TSP mode because it has the most explicit lateness-gating logic.
BUS_PRIO_SWEEP_ENABLED         = False       # was True — not needed for slides
BUS_PRIO_SWEEP_MIN_BUS_DELAY   = [0, 10, 20]
BUS_PRIO_SWEEP_MIN_PAX         = [0, 40]
BUS_PRIO_SWEEP_TAKEOVER        = [30, 60]
for _mbd in BUS_PRIO_SWEEP_MIN_BUS_DELAY:
    for _mpx in BUS_PRIO_SWEEP_MIN_PAX:
        for _lto in BUS_PRIO_SWEEP_TAKEOVER:
            EXPERIMENTS.append({
                "name":              f"BUSPRIO_SWEEP_D{_mbd}_P{_mpx}_T{_lto}".replace(".", ""),
                "enabled":           BUS_PRIO_SWEEP_ENABLED,
                "strategy":          "GLOBAL_REWARD",
                "coordinated":       True,
                "coordination_algo": "SHOCKWAVE",
                "active_intersections": None,
                "reward_overrides": {
                    "GLOBAL_REWARD_MODE":        True,
                    "REWARD_SELFORG_MODE":       False,
                    "DCTSP_ZIG_MODE":            False,
                    "BARGAIN_SPM_MODE":          False,
                    "HS_EXT_MODE":               False,
                    "MDN_DELAY_MODE":            False,
                    "META_TSP_MODE":             True,
                    "META_MIN_BUS_DELAY_S":      _mbd,
                    "META_MIN_THRESHOLD_PAX_S":  _mpx,
                    "META_LATENESS_TAKEOVER_S":  _lto,
                },
            })

# ── Lateness Takeover sweep ───────────────────────────────────────────────────
# Targeted follow-up to BUS_PRIO_SWEEP (above). BUS_PRIO_SWEEP established that
# the gate region META_MIN_BUS_DELAY_S=20 / META_MIN_THRESHOLD_PAX_S=0 ("D20/P0")
# gives the best total-delay result of all 48 experiments (952.4 pax-hrs vs
# NoPriority's 1261.1) AND the smallest Mean-sigma gap among the improving
# configurations (+1.4s vs NoPriority's 35.5s). No configuration in the batch
# beats NoPriority's Mean sigma outright. This sweep anchors at D20/P0 and
# explores the two mechanisms BUS_PRIO_SWEEP did not vary independently:
#
#   META_LATENESS_TAKEOVER_S — bus headway-deviation (seconds) that triggers
#   unconditional TSP, bypassing the minimum-delay/min-benefit gates entirely.
#   At D20/P0, BUS_PRIO_SWEEP's T30->T60 change was the single most sensitive
#   swing in the whole batch (-212 pax-hrs), so this sweep brackets the two
#   extremes: 60 (known-good) vs 9999 (takeover disabled). Of the 12
#   BUS_PRIO_SWEEP configs, only 9 were numerically distinct (n_min/takeover
#   often non-binding), so intermediate takeover values (90, 120) were dropped
#   to keep this follow-up sweep small.
#
#   META_HW_SENSITIVITY — slope of the adaptive bus-weight term
#   w_bus(sigma_in) = META_BASE_BUS_WEIGHT + META_HW_SENSITIVITY *
#   clip(|sigma_in|/META_HW_REF_S, 0, 1). BUS_PRIO_SWEEP never varied this from
#   its default (1.5); this sweep brackets it at {0.5, 1.5, 2.5}.
#
# Goal: find a (takeover, sensitivity) pair that pushes Mean sigma below the
# NoPriority baseline (35.5s) WITHOUT worsening D20/P0/T60's average-travel-time
# cost (Delta Avg TT = +34.1s/vehicle vs NoPriority -- already worse than
# CellSearch's +21.9s, WaveGate's +25.5s and NashGate's +28.9s). Track Delta
# Avg TT alongside Mean sigma for every config: a config that improves sigma
# but pushes Delta Avg TT further above CellSearch's +21.9s is not a win.
# T60/S1.5 reproduces BUSPRIO_SWEEP_D20_P0_T60 exactly (952.4 pax-hrs,
# Mean sigma=36.9s, Delta Avg TT=+34.1s) and serves as a built-in cross-check.
LATENESS_SWEEP_ENABLED               = False  # was True — not needed for slides
LATENESS_SWEEP_TAKEOVER              = [60, 9999]
LATENESS_SWEEP_HW_SENSITIVITY        = [0.5, 1.5, 2.5]
for _lto in LATENESS_SWEEP_TAKEOVER:
    for _lhw in LATENESS_SWEEP_HW_SENSITIVITY:
        EXPERIMENTS.append({
            "name":              f"LATENESS_SWEEP_T{_lto}_S{_lhw:.1f}".replace(".", ""),
            "enabled":           LATENESS_SWEEP_ENABLED,
            "strategy":          "GLOBAL_REWARD",
            "coordinated":       True,
            "coordination_algo": "SHOCKWAVE",
            "active_intersections": None,
            "reward_overrides": {
                "GLOBAL_REWARD_MODE":        True,
                "REWARD_SELFORG_MODE":       False,
                "DCTSP_ZIG_MODE":            False,
                "BARGAIN_SPM_MODE":          False,
                "HS_EXT_MODE":               False,
                "MDN_DELAY_MODE":            False,
                "META_TSP_MODE":             True,
                "META_MIN_BUS_DELAY_S":      20,
                "META_MIN_THRESHOLD_PAX_S":  0,
                "META_LATENESS_TAKEOVER_S":  _lto,
                "META_HW_SENSITIVITY":       _lhw,
            },
        })

# ── Bus ETA Predictor comparison sweep ───────────────────────────────────────
# Sweeps three bus ETA predictor methods × four TSP algorithm variants = 12 runs.
#
#   Predictors (bus position tracking):
#     KALMAN          — constant-velocity Kalman filter (Faragher 2012)
#     ADAPTIVE_KALMAN — TVAKF with EWMA dynamic factor (Ding et al. 2022)
#     LSTM_SS         — 2-layer bidirectional LSTM (Zhou et al. 2026)
#
#   Algorithms (TSP decision policy):
#     NO_TSP          — baseline (predictor has no effect; sanity check)
#     CPDQL           — cooperative per-junction Q-learning (DCTSP_MARL)
#     WaveGate        — LWR shockwave-optimal gating (DCTSP_ZIG)
#     NashGate        — Nash bargaining SPM (DCTSP_BARGAIN_SPM)
#
# coord_algo = SHOCKWAVE for WaveGate/NashGate, KALMAN for CPDQL.
# Enable with PREDICTOR_SWEEP_ENABLED = True.
PREDICTOR_SWEEP_ENABLED = True
_PREDICTOR_STRATEGIES = [
    # NO_TSP is excluded — the predictor has no effect on a baseline-only run,
    # so three identical PRED_{PRED}_NO_TSP experiments would be redundant.
    # The standalone NO_TSP experiment above serves as the shared baseline.
    # CPDQL DISABLED FOR THIS RUN
    # {
    #     "label":    "CPDQL",
    #     "strategy": "GLOBAL_REWARD",
    #     "coordinated": True,
    #     "coordination_algo": "KALMAN",
    #     "reward_overrides": {
    #         "GLOBAL_REWARD_MODE":           True,
    #         "BARGAIN_SPM_MODE":             False,
    #         "DCTSP_ZIG_MODE":               False,
    #         "META_TSP_MODE":                False,
    #         "MDN_DELAY_MODE":               False,
    #         "HS_EXT_MODE":                  False,
    #         "DCTSP_GREEN_REALLOC_MODE":     True,
    #         "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
    #         "DCTSP_W_H":                    0.50,
    #         "DCTSP_CAR_WEIGHT":             1.00,
    #         # Pure exploitation — no random exploration during single-episode eval
    #         "RL_EPSILON_START":             0.0,
    #         "RL_EPSILON_END":               0.0,
    #     },
    # },
    {
        "label":    "WaveGate",
        "strategy": "GLOBAL_REWARD",
        "coordinated": True,
        "coordination_algo": "SHOCKWAVE",
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":     True,
            "BARGAIN_SPM_MODE":       False,
            "DCTSP_ZIG_MODE":         True,
            "META_TSP_MODE":          False,
            "MDN_DELAY_MODE":         False,
            "HS_EXT_MODE":            False,
            "ZIG_PHASE_OVERLAP_S":    0.5,
            "ZIG_BALANCE_FACTOR":     0.50,
            "NETWORK_FACTOR":         5.0,
            # DE solver parameters (Storn & Price 1997, DE/rand/1/bin)
            "ZIG_DE_POP":             12,
            "ZIG_DE_ITER":            30,
            "ZIG_DE_F":               0.8,
            "ZIG_DE_CR":              0.9,
            # Minimum reward delta to grant TSP; blocks marginal insertions
            "ZIG_MIN_GAIN_S":         40.0,
        },
    },
    {
        "label":    "MambaATSP",
        "strategy": "GLOBAL_REWARD",
        "coordinated": True,
        "coordination_algo": "SHOCKWAVE",
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":           True,
            "BARGAIN_SPM_MODE":             False,
            "DCTSP_ZIG_MODE":               False,
            "MAMBA_ATSP_MODE":              True,
            "META_TSP_MODE":                False,
            "MDN_DELAY_MODE":               False,
            "HS_EXT_MODE":                  False,
            "DCTSP_GREEN_REALLOC_MODE":     True,
            "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            # Mamba-ATSP hyperparameters (Li et al. 2026, Alexandria Eng. J. 137:414-423)
            "MAMBA_ATTENTION_HEADS":        4,
            "MAMBA_HIDDEN_DIM":             64,
            "MAMBA_SSM_SCAN_STRIDE":        2,
            "MAMBA_DATA_FUSION_ALPHA":      0.5,
            "MAMBA_ATTENTION_TEMP":         1.0,
        },
    },
    {
        "label":    "NashGate",
        "strategy": "GLOBAL_REWARD",
        "coordinated": True,
        "coordination_algo": "SHOCKWAVE",
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":           True,
            "BARGAIN_SPM_MODE":             True,
            "DCTSP_ZIG_MODE":               False,
            "META_TSP_MODE":                False,
            "MDN_DELAY_MODE":               False,
            "HS_EXT_MODE":                  False,
            "DCTSP_GREEN_REALLOC_MODE":     True,
            "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
        },
    },
]
for _ps in _PREDICTOR_STRATEGIES:
    # KALMAN filter DISABLED — using only ADAPTIVE_KALMAN and LSTM_SS
    for _pred in ("ADAPTIVE_KALMAN", "LSTM_SS"):
        EXPERIMENTS.append({
            "name":              f"PRED_{_pred}_{_ps['label']}",
            "enabled":           PREDICTOR_SWEEP_ENABLED,
            "strategy":          _ps["strategy"],
            "coordinated":       _ps["coordinated"],
            "coordination_algo": _ps["coordination_algo"],
            "bus_predictor":     _pred,
            "active_intersections": None,
            "reward_overrides":  _ps["reward_overrides"],
        })

# ── Tracking-method comparison sweep ─────────────────────────────────────────
# Compares the three bus-position predictor methods (Section 4.1 of paper)
# across the three core coordinated strategies (CPD-QL, WaveGate, Centralised).
# This is the primary sweep for the tracking-method sensitivity analysis.
#
#   Strategies:
#     CPD-QL        — tabular Q-learning (DCTSP_MARL / GLOBAL_REWARD_MODE)
#     WaveGate      — Harmony Search + LWR shockwave gate (DCTSP_ZIG)
#     Centralised   — per-second corridor controller (CENTRALIZED_MODE=True)
#
#   Predictors:
#     KALMAN         — constant-velocity Kalman filter (baseline)
#     ADAPTIVE_KALMAN— time-varying adaptive KF with EWMA dynamic factor
#                      (Ding et al. 2022, TVAKF; 2.52% MAPE)
#     LSTM_SS        — 2-layer bidirectional LSTM single-step predictor
#                      (Zhou et al. 2026, online training during simulation)
#
# coord_algo stays at SHOCKWAVE for WaveGate (standard queue-aware correction).
# CPD-QL and Centralised use KALMAN coord_algo (default ETA correction loop).
# TRACKING_METHOD_SWEEP_ENABLED = False — user enables and runs Aimsun.
TRACKING_METHOD_SWEEP_ENABLED = False

_TRACKING_STRATEGIES = [
    {
        "label":    "CPDQL",
        "strategy": "GLOBAL_REWARD",
        "coordinated": True,
        "coordination_algo": "KALMAN",
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":    True,
            "REWARD_ALPHA":          1.0,
            "REWARD_BETA":           1.0,
            "REWARD_GAMMA":          1.0,
            "DCTSP_W_H":             0.50,
            "DCTSP_CAR_WEIGHT":      1.00,
            "DCTSP_GREEN_REALLOC_MODE": True,
            "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
        },
    },
    {
        "label":    "WAVEGATE",
        "strategy": "GLOBAL_REWARD",
        "coordinated": True,
        "coordination_algo": "SHOCKWAVE",
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":     True,
            "REWARD_SELFORG_MODE":    False,
            "DCTSP_ZIG_MODE":         True,
            "ZIG_PHASE_OVERLAP_S":    0.5,
            "ZIG_BALANCE_FACTOR":     0.50,
            "NETWORK_FACTOR":         5.0,
        },
    },
    {
        "label":    "CENTRALISED",
        "strategy": "GLOBAL_REWARD",
        "coordinated": True,
        "coordination_algo": "KALMAN",
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":     True,
            "CENTRALIZED_MODE":       True,
            "CENTRALIZED_INTERVAL_S": 1.0,
        },
    },
]

for _ts in _TRACKING_STRATEGIES:
    for _pred in ("KALMAN", "ADAPTIVE_KALMAN", "LSTM_SS"):
        EXPERIMENTS.append({
            "name":              f"TRACK_{_pred}_{_ts['label']}",
            "enabled":           TRACKING_METHOD_SWEEP_ENABLED,
            "strategy":          _ts["strategy"],
            "coordinated":       _ts["coordinated"],
            "coordination_algo": _ts["coordination_algo"],
            "bus_predictor":     _pred,
            "active_intersections": None,
            "reward_overrides":  _ts["reward_overrides"],
        })

# ── Raw Travel-Time (Z4) weight sweep -- SUPERSEDED ──────────────────────────
# Originally a follow-up to the "lower total delay but higher Avg TT" paradox
# documented for every TSP configuration (Section sec:res_rho): Z1's
# occupancy weighting (rho_bus=40 vs rho_car=1.5) makes the aggregate
# car-side travel-time cost invisible to the objective, so Delta Avg TT rises
# even when Z1/pax-delay falls. The original design added an online
# Z4 = main_bus+main_car+side_bus+side_car (veh.s, rho=1, w_main=w_side=1)
# term and a WOBJ_DELTA weight: objective = WOBJ_ALPHA*Z1 + WOBJ_BETA*Z2 +
# WOBJ_DELTA*Z4, swept over WOBJ_DELTA in {0, 2, 8, 32}.
#
# Z4 has since been redefined as the corridor's TOTAL TRAVEL TIME (veh-h) --
# Net_TotalTT_h_Car+Bus+Truck, the same figure as the "Total hours of travel"
# KPI -- a network-level quantity computed post-hoc for every run (section 7
# of collect_run_metrics), not a per-cycle weighted term. WOBJ_DELTA and the
# online Z4 term have been removed from compute_weighted_objective(), so the
# 4 configs below are now operationally IDENTICAL to each other and to
# D20/P0/T60/S2.5 (LATENESS_SWEEP_T60_S25, 918.1 pax-hrs, -27.2% vs
# NoPriority, the lowest-total-delay configuration of all 60 executed
# experiments but with Delta Avg TT +33.0s, still worse than CellSearch's
# +21.9s). The 4 TRAVELTIME_SWEEP_D* rows already collected in
# batch_results.csv report that same corridor total-travel-time value for Z4.
# Disabled to avoid re-running 4 duplicate experiments; kept (unchanged) for
# naming continuity with the already-collected results.
TRAVELTIME_SWEEP_ENABLED = False
TRAVELTIME_SWEEP_DELTAS  = [0, 2, 8, 32]
for _td in TRAVELTIME_SWEEP_DELTAS:
    EXPERIMENTS.append({
        "name":              f"TRAVELTIME_SWEEP_D{_td}".replace(".", ""),
        "enabled":           TRAVELTIME_SWEEP_ENABLED,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "SHOCKWAVE",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":        True,
            "REWARD_SELFORG_MODE":       False,
            "DCTSP_ZIG_MODE":            False,
            "BARGAIN_SPM_MODE":          False,
            "HS_EXT_MODE":               False,
            "MDN_DELAY_MODE":            False,
            "META_TSP_MODE":             True,
            "META_MIN_BUS_DELAY_S":      20,
            "META_MIN_THRESHOLD_PAX_S":  0,
            "META_LATENESS_TAKEOVER_S":  60,
            "META_HW_SENSITIVITY":       2.5,
        },
    })

# ── Cross-Strategy sweep ─────────────────────────────────────────────────────
# Sweeps across the three analytical TSP strategies (game-theory / ZIG,
# reinforcement-learning / MDN, harmony-search / HS_EXT) × their key sensitivity
# parameters × the weighted-objective tradeoff (WOBJ_ALPHA).
#
# Each strategy gets its characteristic sensitivity axis:
#   ZIG:    ZIG_BALANCE_FACTOR  [0.25, 0.50, 0.75]  — cost-benefit gate
#   MDN:    MDN_DDT_POWER       [0.25, 0.50, 0.75]  — delay-distribution skew
#   HS_EXT: HS_EXT_HMCR         [0.50, 0.75, 0.90]  — harmony-memory exploit rate
#
# All crossed with WOBJ_ALPHA [0.7, 0.8, 0.9] which now propagates into
# REWARD_BETA/REWARD_GAMMA (bus-vs-cross-traffic penalty).
#
# Bus-priority sensitivity (META_MIN_BUS_DELAY_S / META_MIN_THRESHOLD_PAX_S /
# META_LATENESS_TAKEOVER_S) is swept separately in BUS_PRIO_SWEEP.
CROSS_STRATEGY_SWEEP_ENABLED = False

# Strategy definitions: (name_label, mode_flags, sensitivity_axis)
_STRATEGIES = [
    ("ZIG",    {"DCTSP_ZIG_MODE": True,
                "REWARD_SELFORG_MODE": False,
                "ZIG_PHASE_OVERLAP_S": 0.5,
                "NETWORK_FACTOR": 5.0},
     "ZIG_BALANCE_FACTOR", [0.25, 0.50, 0.75]),

    ("MDN",    {"MDN_DELAY_MODE": True,
                "MDN_N_COMPONENTS": 3},
     "MDN_DDT_POWER",      [0.25, 0.50, 0.75]),

    ("HSEXT",  {"HS_EXT_MODE": True,
                "BARGAIN_SPM_MODE": True,
                "DCTSP_GREEN_REALLOC_MODE": True,
                "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
                "HS_EXT_PAR": 0.35},
     "HS_EXT_HMCR",        [0.50, 0.75, 0.90]),
]

CROSS_STRATEGY_WOBJ_ALPHAS = [0.7, 0.8, 0.9]

for _strat_label, _mode_flags, _sens_key, _sens_values in _STRATEGIES:
    for _sv in _sens_values:
        for _wa in CROSS_STRATEGY_WOBJ_ALPHAS:
            _overrides = {
                "GLOBAL_REWARD_MODE": True,
                "REWARD_SELFORG_MODE": False,
                "DCTSP_ZIG_MODE":     False,
                "BARGAIN_SPM_MODE":   False,
                "HS_EXT_MODE":        False,
                "MDN_DELAY_MODE":     False,
                "META_TSP_MODE":      False,
                "WOBJ_ALPHA":         _wa,
            }
            _overrides.update(_mode_flags)
            _overrides[_sens_key] = _sv
            _name = f"CROSS_{_strat_label}_S{_sv}_A{_wa:.1f}".replace(".", "")
            EXPERIMENTS.append({
                "name":              _name,
                "enabled":           CROSS_STRATEGY_SWEEP_ENABLED,
                "strategy":          "GLOBAL_REWARD",
                "coordinated":       True,
                "coordination_algo": "SHOCKWAVE",
                "active_intersections": None,
                "reward_overrides":  _overrides,
            })


def _marl_base_overrides():
    """DCTSP_MARL (RL) base — GLOBAL_REWARD with equal vehicle weighting.
    Reward optimises for total average vehicle delay (occ=1), not passenger-weighted.
    Output KPIs still report original occupancy-weighted total delay."""
    return {
        "GLOBAL_REWARD_MODE":    True,
        "REWARD_ALPHA":          1.0,
        "REWARD_BETA":           1.0,
        "REWARD_GAMMA":          1.0,
        "REWARD_INV_DELAY_MODE": False,
        "DCTSP_W_H":             0.45,
        "DCTSP_CAR_WEIGHT":      0.35,
        "BUS_OCC_OVERRIDE":      1.0,   # equal vehicle weight in reward
        "CAR_OCC_OVERRIDE":      1.0,   # total avg delay, not pax-weighted
    }

def _nashgate_base_overrides():
    """DCTSP_BARGAIN_SPM (NashGate) base with Harmony Search for shockwave-optimal
    action durations instead of discrete {5,10,15}s candidates."""
    return {
        "GLOBAL_REWARD_MODE":       True,
        "REWARD_SELFORG_MODE":      False,
        "REWARD_INV_DELAY_MODE":    False,
        "REWARD_V2X_MODE":          False,
        "DCTSP_ZIG_MODE":           False,
        "MP_ECTM_MODE":             False,
        "BXT_MODE":                 False,
        "META_TSP_MODE":            False,
        "MDN_DELAY_MODE":           False,
        "BARGAIN_SPM_MODE":         True,
        "HS_EXT_MODE":              False,   # discrete {5,10,15}s — HS_EXT makes results worse
        "HS_EXT_T_MIN":             5.0,
        "HS_EXT_T_MAX":             30.0,
        "HS_EXT_HMS":               5,
        "HS_EXT_HMCR":              0.75,
        "HS_EXT_PAR":                0.35,
        "HS_EXT_BW":                 2.0,
        "HS_EXT_NITER":              20,
        "DCTSP_GREEN_REALLOC_MODE": True,
        "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
        "BG_DET_LVL_IMM_S":         4.0,
        "BG_DET_LVL_NEAR_S":        12.0,
        "BG_DET_LVL_FAR_S":         24.0,
        "BG_BUS_W_IMM":             1.6,
        "BG_BUS_W_NEAR":            1.35,
        "BG_BUS_W_FAR":             1.10,
        "BG_BUS_W_VFAR":            0.95,
        "BG_SPM_RISK_WEIGHT":       1.8,
        "BG_EQ_FAIRNESS_WEIGHT":    0.55,
        "BG_MIN_BUS_DELAY_S":       5.0,
        "BG_MIN_GAIN_S":            5.0,
        "BG_CASCADE_MULT":          2.0,
        "BG_MB_WEIGHT":             0.30,
        "DCTSP_CONGESTION_GATE":    True,
        "DCTSP_CONGESTION_GATE_FRACTION": 0.75,
        "REWARD_SIDE_SECTION_WEIGHT": 0.5,
    }


def _wavegate_base_overrides():
    """DCTSP_ZIG (WaveGate) base overrides — mirrors the DCTSP_ZIG entry above."""
    return {
        "GLOBAL_REWARD_MODE":     True,
        "REWARD_SELFORG_MODE":    False,
        "REWARD_INV_DELAY_MODE":  False,
        "REWARD_V2X_MODE":        False,
        "DCTSP_ZIG_MODE":         True,
        "ZIG_PHASE_OVERLAP_S":    0.5,
        "ZIG_BALANCE_FACTOR":     0.50,
        "NETWORK_FACTOR":         5.0,
        "ZIG_MIN_GAIN_S":         40.0,
    }


# ── Detection-level sensitivity sweep (WaveGate / DCTSP_ZIG) ─────────────────
# Sweeps DETECTION_PROB -- the probability that a ~5s AVL/GPS bus-tracking
# cycle successfully registers an in-range bus (see DETECTION_PROB in
# intersection_controller.py). P100 reproduces DCTSP_ZIG's result exactly
# (cross-check); lower values simulate progressively less reliable AVL/GPS.
DETECTION_SWEEP_ENABLED = False
DETECTION_SWEEP_PROBS   = [1.00, 0.75, 0.50, 0.25]
for _dp in DETECTION_SWEEP_PROBS:
    _det_ov = _wavegate_base_overrides()
    _det_ov["DETECTION_PROB"] = _dp
    EXPERIMENTS.append({
        "name":              f"DETECTION_SWEEP_WAVEGATE_P{int(round(_dp * 100)):03d}",
        "enabled":           DETECTION_SWEEP_ENABLED,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "SHOCKWAVE",
        "active_intersections": None,
        "reward_overrides":  _det_ov,
    })

# ── Occupancy-level sensitivity sweep (WaveGate / DCTSP_ZIG) ─────────────────
# Sweeps paired bus/car occupancy assumptions (pax/veh) via BUS_OCC_OVERRIDE /
# CAR_OCC_OVERRIDE (see intersection_controller.py). BASE (40/1.2) is a
# cross-check against DCTSP_ZIG's junction-config default; LOW/HIGH bracket
# off-peak vs peak passenger-loading assumptions.
OCC_SWEEP_ENABLED = False
OCC_SWEEP_LEVELS = {
    "LOW":  (20.0, 1.0),
    "BASE": (40.0, 1.2),
    "HIGH": (60.0, 1.5),
}
for _ol, (_bus_occ, _car_occ) in OCC_SWEEP_LEVELS.items():
    _occ_ov = _wavegate_base_overrides()
    _occ_ov["BUS_OCC_OVERRIDE"] = _bus_occ
    _occ_ov["CAR_OCC_OVERRIDE"] = _car_occ
    EXPERIMENTS.append({
        "name":              f"OCC_SWEEP_WAVEGATE_{_ol}",
        "enabled":           OCC_SWEEP_ENABLED,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "SHOCKWAVE",
        "active_intersections": None,
        "reward_overrides":  _occ_ov,
    })

# ── Decision-cycle / lookahead-horizon sensitivity sweep (NashGate / DCTSP_BARGAIN_SPM) ──
# Sweeps TSP_CYCLE_LENGTH_OVERRIDE_S -- the per-junction "recalculation" window
# in which the controller makes one grant/no-action decision per bus -- crossed
# with REWARD_FUTURE_HORIZON_CYCLES -- how many cycles of future bus/cross-
# traffic delay disturbance the lookahead reward term projects.
# NOTE: this 90-180s x 1.0-2.0-cycle grid predates the operating-default change
# to TSP_CYCLE_LENGTH_OVERRIDE_S=10.0s / REWARD_FUTURE_HORIZON_CYCLES=1.0 (see
# globals in intersection_controller.py); C135_H1.5 no longer reproduces the new
# default. Re-centering this sweep's ranges around the 10s/1-cycle baseline is
# left to future work (see PPTX slide "1.4 - Future work"). The existing 9
# combinations remain valid as a standalone slower-recalculation comparison.
CYCLE_HORIZON_SWEEP_ENABLED = False
CYCLE_HORIZON_SWEEP_CYCLES  = [90.0, 135.0, 180.0]   # TSP_CYCLE_LENGTH_OVERRIDE_S [s]
CYCLE_HORIZON_SWEEP_HORIZONS = [1.0, 1.5, 2.0]       # REWARD_FUTURE_HORIZON_CYCLES [cycles]
for _ch_cycle in CYCLE_HORIZON_SWEEP_CYCLES:
    for _ch_horizon in CYCLE_HORIZON_SWEEP_HORIZONS:
        _ch_ov = _nashgate_base_overrides()
        _ch_ov["TSP_CYCLE_LENGTH_OVERRIDE_S"] = _ch_cycle
        _ch_ov["REWARD_FUTURE_HORIZON_CYCLES"] = _ch_horizon
        EXPERIMENTS.append({
            "name":              f"CYCLE_HORIZON_SWEEP_NASHGATE_C{int(round(_ch_cycle)):03d}_H{_ch_horizon:.1f}".replace(".", ""),
            "enabled":           CYCLE_HORIZON_SWEEP_ENABLED,
            "strategy":          "GLOBAL_REWARD",
            "coordinated":       True,
            "coordination_algo": "SHOCKWAVE",
            "active_intersections": None,
            "reward_overrides":  _ch_ov,
        })

# ── WOBJ 5-profile weight sweep (NashGate / DCTSP_BARGAIN_SPM) ──────────────
# 5 weight profiles exploring the full objective space for the PPT.
#   EQ Z1+Z2: alpha=0.50, beta=0.50, gamma=0.00
#   EQ ALL3:  alpha=0.33, beta=0.33, gamma=0.33
#   Only Z1:  alpha=1.00, beta=0.00, gamma=0.00
#   Only Z2:  alpha=0.00, beta=1.00, gamma=0.00
#   Only TT:  alpha=1.00, beta=0.00, gamma=0.00, occ=1/1 — unweighted vehicle delay = proxy for Z4
WOBJ_5PROFILE_SWEEP_ENABLED = False  # NashGate disabled; re-enable when DCTSP_BARGAIN_SPM runs
WOBJ_5PROFILE_WEIGHTS = [
    ("EQ_Z1Z2", 0.50, 0.50, 0.00, None),       # default occupancy
    ("EQ_ALL3",  0.33, 0.33, 0.33, None),
    ("ONLY_Z1",  1.00, 0.00, 0.00, None),
    ("ONLY_Z2",  0.00, 1.00, 0.00, None),
    ("ONLY_TT",  1.00, 0.00, 0.00, (1.0, 1.0)),  # bus_occ=1, car_occ=1 → unweighted veh delay
]
for _wl, _wa, _wb, _wg, _occ in WOBJ_5PROFILE_WEIGHTS:
    _wp_ov = _nashgate_base_overrides()
    _wp_ov["WOBJ_ALPHA"] = _wa
    _wp_ov["WOBJ_BETA"]  = _wb
    _wp_ov["WOBJ_GAMMA"] = _wg
    if _occ is not None:
        _wp_ov["BUS_OCC_OVERRIDE"] = _occ[0]
        _wp_ov["CAR_OCC_OVERRIDE"] = _occ[1]
    EXPERIMENTS.append({
        "name":              f"WOBJ_SWEEP_NASHGATE_{_wl}",
        "enabled":           WOBJ_5PROFILE_SWEEP_ENABLED,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "SHOCKWAVE",
        "active_intersections": None,
        "reward_overrides":  _wp_ov,
    })

# ── Flow + Lateness balanced sweep (NashGate, α=0, β=γ=0.5, scaling enabled) ──
# Objective = -0.5*(Z2/Z2_ref) + 0.5*(Z3/Z3_ref)
# Z2 = flow-weighted bandwidth (maximise), Z3 = bus lateness (minimise).
# Scale factors normalise to comparable magnitude so β and γ have equal influence.
FLOW_LATE_SWEEP_ENABLED = False  # disabled — only core strategies needed
if FLOW_LATE_SWEEP_ENABLED:
    _fl_ov = _nashgate_base_overrides()
    _fl_ov["WOBJ_ALPHA"] = 0.0     # ignore passenger delay
    _fl_ov["WOBJ_BETA"]  = 0.5     # flow maximisation
    _fl_ov["WOBJ_GAMMA"] = 0.5     # lateness minimisation
    _fl_ov["WOBJ_Z1_SCALE"] = 3000000.0  # normalise Z1 (~3e6 pax-s)
    _fl_ov["WOBJ_Z2_SCALE"] = 7500.0     # normalise Z2 (~500*15s bandwidth)
    _fl_ov["WOBJ_Z3_SCALE"] = 12000.0    # normalise Z3 (~worst lateness)
    EXPERIMENTS.append({
        "name":              "FLOW_LATE_BALANCED",
        "enabled":           True,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "SHOCKWAVE",
        "active_intersections": None,
        "reward_overrides":  _fl_ov,
    })

# ── Prediction strategy sweep (Kalman vs Adaptive vs LSTM) ──────────────────
# 4 strategies × 3 predictor types = 12 experiments
# Each strategy uses its own reward function; only the ETA predictor varies.
PREDICTION_SWEEP_ENABLED = True
PREDICTION_SWEEP_STRATEGIES = {
    "BARGAIN": {"GLOBAL_REWARD_MODE": True, "BARGAIN_SPM_MODE": True,
                "DCTSP_GREEN_REALLOC_MODE": True, "GREEN_REALLOC_RECOVER_FRACTION": 1.0},
}
PREDICTION_TYPES = ["KALMAN", "ADAPTIVE_KALMAN", "LSTM_SS"]
PREDICTION_TYPES = ["KALMAN", "ADAPTIVE_KALMAN", "LSTM_SS"]
for _ps, _ps_ov in PREDICTION_SWEEP_STRATEGIES.items():
    for _pt in PREDICTION_TYPES:
        _ov = dict(_ps_ov)
        _ov["BUS_PREDICTOR_TYPE"] = _pt
        _ov["WOBJ_Z1_SCALE"] = 3000000.0
        _ov["WOBJ_Z2_SCALE"] = 7500.0
        _ov["WOBJ_Z3_SCALE"] = 12000.0
        EXPERIMENTS.append({
            "name":              f"PRED_{_ps}_{_pt}",
            "enabled":           PREDICTION_SWEEP_ENABLED,
            "strategy":          "GLOBAL_REWARD",
            "coordinated":       True,
            "coordination_algo": "SHOCKWAVE",
            "active_intersections": None,
            "reward_overrides":  _ov,
        })

SEEDS           = [300]              # 1 seed; restore [300, 42, 12345] for 3-seed replication
# ── Flow sensitivity sweep ────────────────────────────────────────────────────
# Literature (Robertson 1969; Hounsell & Wu 2003; Dion et al. 2004) shows TSP
# relative benefit peaks at moderate congestion (v/c ≈ 0.65–0.80): below that
# buses catch green naturally; above v/c ≈ 0.90 cross-traffic penalty dominates.
# Use 5-level sweep: 0.70 (undersaturated) → 1.30 (oversaturated).
# For a quick baseline-only run, set DEMAND_SCALARS = [1.0].
# NOTE: DCTSP_CONGESTION_GATE_FRACTION=0.75 was tuned at scalar=1.0; at lower
# scalars all intersections fall below the gate (always open), at higher scalars
# more junctions are gated (TSP suppressed) — both effects are informative.
DEMAND_SCALARS  = [1.0]              # baseline demand only — no demand scaling yet
SCALE_TRUCKS    = True   # scale trucks proportionally → consistent car/truck ratio across scalars

TARGET_DEMAND_NAMES = ["01d Logan Rd 2025 AM", "01d Logan Rd 2025 PM"]

# ── DEMAND SWEEP MODE (sensitivity — demand levels) ──────────────────────────
# Off by default: DEMAND_SCALARS multiplies the run count for the WHOLE
# EXPERIMENTS list, so enabling this narrows EXPERIMENTS to NoPriority +
# NashGate (DCTSP_BARGAIN_SPM) and sweeps demand at +/-20%
# (6 x len(SEEDS) runs total).
# TARGET_DEMAND_NAMES above is named for the Logan Rd dataset; for this
# Kelvin Grove Rd corridor that name likely matches zero traffic-demand
# matrices, so set_demand_scalar() would silently scale nothing. Overriding
# it to None here makes _is_target_demand() match ALL GKTrafficDemand
# matrices in the active model -- the correct behaviour for a network-wide
# demand-level sweep regardless of matrix naming.
DEMAND_SWEEP_ENABLED = False
if DEMAND_SWEEP_ENABLED:
    DEMAND_SCALARS = [0.8, 1.0, 1.2]
    TARGET_DEMAND_NAMES = None
    EXPERIMENTS = [e for e in EXPERIMENTS if e['name'] in ('NO_TSP', 'DCTSP_ZIG')]

# =============================================================================
# ── INTERNAL CONFIG ───────────────────────────────────────────────────────────
# =============================================================================
CAR_KEYWORDS   = ("car",)
TRUCK_KEYWORDS = ("truck",)

# How long to wait (seconds) after patching the controller before starting the
# simulation — gives the OS time to flush the file to disk.
PATCH_SETTLE_S = 0.5

# =============================================================================
# ── LOGGING ───────────────────────────────────────────────────────────────────
# =============================================================================
def log(msg):
    if _QUIET:
        return
    print("[RUNNER] " + str(msg))


_QUIET = True  # set False to debug


# =============================================================================
# ── PROJECT DIR ───────────────────────────────────────────────────────────────
# =============================================================================
def get_project_dir():
    model = GKSystem.getSystem().getActiveModel()
    if model is None:
        raise RuntimeError("No active model found. Open your project first.")
    try:
        project_dir = model.getDocumentDirectory().absolutePath()
    except Exception:
        try:
            filename = model.getDocumentFileName()
            if filename:
                project_dir = _os.path.dirname(filename)
            else:
                raise RuntimeError("Model has no document file name.")
        except Exception as e:
            raise RuntimeError(f"Could not determine project path: {e}")
    log("Project directory: " + project_dir)
    return project_dir


# =============================================================================
# ── DEMAND SCALING ────────────────────────────────────────────────────────────
# =============================================================================
def _is_scalable_matrix(matrix):
    try:
        v = matrix.getVehicle()
        vname = v.getName().lower() if v else ""
    except Exception:
        vname = ""
    is_car   = any(k in vname for k in CAR_KEYWORDS)
    is_truck = any(k in vname for k in TRUCK_KEYWORDS)
    return is_car or (is_truck and SCALE_TRUCKS)


def _is_target_demand(demand):
    if TARGET_DEMAND_NAMES is None:
        return True
    name = demand.getName().lower()
    return any(t.lower() in name for t in TARGET_DEMAND_NAMES)


def set_demand_scalar(scalar, base_demands):
    """Scale car (and optionally truck) demand. base_demands prevents compounding."""
    model = GKSystem.getSystem().getActiveModel()
    demand_type = model.getType("GKTrafficDemand")
    objs = model.getCatalog().getObjectsByType(demand_type)
    if not objs:
        log("WARNING: No GKTrafficDemand objects found.")
        return

    demand_list = list(objs.values()) if isinstance(objs, dict) else list(objs)
    n_scaled = 0

    for demand in demand_list:
        if not _is_target_demand(demand):
            continue
        schedule = demand.getSchedule()
        if not schedule:
            continue
        for sched_item in schedule:
            matrix = sched_item.getTrafficDemandItem()
            if matrix is None or not _is_scalable_matrix(matrix):
                continue
            item_key = id(sched_item)
            if item_key not in base_demands:
                original_factor_str = sched_item.getFactor()
                try:
                    base_demands[item_key] = float(original_factor_str)
                except Exception:
                    raise RuntimeError(
                        f"Schedule factor for '{matrix.getName()}' "
                        f"is not numeric: {original_factor_str}"
                    )
            new_factor = base_demands[item_key] * float(scalar)
            sched_item.setFactor("{:.6f}".format(new_factor))
            n_scaled += 1

    log(f"Demand scalar {scalar}x applied to {n_scaled} matrices.")


# =============================================================================
# ── CONTROLLER PATCHING ───────────────────────────────────────────────────────
# =============================================================================

def _read_controller(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def _write_controller(path, text):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    # Flush OS buffer so Aimsun reads the updated file
    _time.sleep(PATCH_SETTLE_S)


def _purge_pyc(controller_path):
    """Delete any cached .pyc so Aimsun re-reads the patched .py next run."""
    base = _os.path.splitext(controller_path)[0]
    py_dir  = _os.path.dirname(controller_path)
    py_name = _os.path.basename(base)
    # __pycache__ is the normal location (Python 3)
    pycache = _os.path.join(py_dir, '__pycache__')
    for pyc in glob.glob(_os.path.join(pycache, py_name + '*.pyc')):
        try:
            _os.remove(pyc)
            log(f"Purged pyc cache: {pyc}")
        except Exception:
            pass
    # Legacy same-dir .pyc
    for pyc in glob.glob(base + '*.pyc'):
        try:
            _os.remove(pyc)
        except Exception:
            pass


def _set_logging(controller_path, enabled):
    """
    Patch ALL console/logging flags in the controller to True or False.

    When enabled=False the following are silenced:
      • VERBOSE
      • every LOG_* flag
      • STATUS_DASHBOARD_INTERVAL_S  (set to 0 / restored to 60)
      • OVERLAY_DETECTIONS_ON_MAP    (set to False — stops canvas annotation)

    NOTE: MARK_DETECTION_POINTS is intentionally NOT disabled during batch runs.
    It writes per-bus detection CSVs that the green-wave plot depends on.
    The per-run overhead is small and the data is valuable for post-analysis.

    The controller still writes simulation_results.csv / summary.json because
    those are triggered by save_results(), not by the LOG_* flags.
    """
    text = _read_controller(controller_path)
    val  = "True" if enabled else "False"

    # VERBOSE = ...
    text, n0 = re.subn(
        r'^(VERBOSE\s*=\s*).*',
        'VERBOSE = ' + val,
        text, flags=re.MULTILINE)

    # Every LOG_xxx = True/False line
    text, n1 = re.subn(
        r'^(LOG_\w+\s*=\s*)(True|False)',
        r'\g<1>' + val,
        text, flags=re.MULTILINE)

    # MARK_DETECTION_POINTS — always restored to True so detection CSVs are
    # generated for every run (green-wave plot needs them).
    text, n2 = re.subn(
        r'^(MARK_DETECTION_POINTS\s*:\s*bool\s*=\s*)(True|False)',
        r'\g<1>True',
        text, flags=re.MULTILINE)

    # OVERLAY_DETECTIONS_ON_MAP = True/False
    text, n3 = re.subn(
        r'^(OVERLAY_DETECTIONS_ON_MAP\s*:\s*bool\s*=\s*)(True|False)',
        r'\g<1>' + val,
        text, flags=re.MULTILINE)

    # STATUS_DASHBOARD_INTERVAL_S: 0 when disabled, 60 when re-enabled
    dash_val = "60.0" if enabled else "0.0"
    text, n4 = re.subn(
        r'^(STATUS_DASHBOARD_INTERVAL_S\s*:\s*float\s*=\s*)[\d.]+',
        r'\g<1>' + dash_val,
        text, flags=re.MULTILINE)

    _write_controller(controller_path, text)

    total = n0 + n1 + n2 + n3 + n4
    if total > 0:
        log(f"Logging {'enabled' if enabled else 'disabled'} in controller "
            f"(VERBOSE + {n1} LOG_* + MARK_DETECT=True(always) "
            f"+ OVERLAY={val} + DASHBOARD={dash_val}).")
    else:
        log("WARNING: no logging flags found in controller — check file path.")


def set_control_mode(strategy, controller_path, active_intersections=None):
    """
    Patch CONTROL_MODE, GROUP_BASED_BUS_PRIORITY, and TSP_ACTIVE_INTERSECTIONS.
    Verifies the patch was applied by re-reading the file after writing.
    """
    if strategy == "GROUP_BASED_FIXED":
        mode     = "GROUP_BASED"
        priority = "False"
    elif strategy in ("REWARD_TSP", "DRL_DENSITY", "HARMONY", "URTSP", "NORMAL"):
        # Explicitly keep phase-based strategies out of any group-based path.
        mode     = strategy
        priority = "False"
    elif strategy == "GLOBAL_REWARD":
        # GLOBAL_REWARD uses the DRL_DENSITY reward path; GLOBAL_REWARD_MODE flag
        # (written to run_config.py) switches the aggregation behaviour at runtime.
        mode     = "DRL_DENSITY"
        priority = "False"
    else:
        mode     = strategy
        priority = "True"

    text = _read_controller(controller_path)

    text, n1 = re.subn(
        r'^(CONTROL_MODE\s*=\s*)["\'].*?["\']',
        'CONTROL_MODE = "' + mode + '"',
        text, flags=re.MULTILINE)

    text, n2 = re.subn(
        r'^(GROUP_BASED_BUS_PRIORITY\s*=\s*).*',
        'GROUP_BASED_BUS_PRIORITY = ' + priority,
        text, flags=re.MULTILINE)

    if n2 == 0:
        # Insert after CONTROL_MODE line
        text = re.sub(
            r'^(CONTROL_MODE\s*=\s*["\'].*?["\'])',
            r'\1\nGROUP_BASED_BUS_PRIORITY = ' + priority,
            text, flags=re.MULTILINE)

    tsp_value = repr(active_intersections)
    text, n3 = re.subn(
        r'^(TSP_ACTIVE_INTERSECTIONS\s*=\s*).*',
        'TSP_ACTIVE_INTERSECTIONS = ' + tsp_value,
        text, flags=re.MULTILINE)

    if n1 == 0:
        raise RuntimeError("CONTROL_MODE line not found in " + controller_path)
    if n3 == 0:
        log("WARNING: TSP_ACTIVE_INTERSECTIONS not found in controller.")

    _write_controller(controller_path, text)

    # ── Verify patch was applied ──────────────────────────────────────────────
    verify = _read_controller(controller_path)
    if f'CONTROL_MODE = "{mode}"' not in verify:
        raise RuntimeError(
            f"Patch verification FAILED: CONTROL_MODE is not '{mode}' in "
            f"{controller_path} after writing.  Check file permissions."
        )

    active_label = "all" if active_intersections is None else str(active_intersections)
    log(f"CONTROL_MODE -> {mode} | bus_priority={priority} | "
        f"TSP_ACTIVE -> {active_label}  [patch verified OK]")


def set_reward_weights(controller_path, overrides=None):
    """Patch reward-weight constants in controller for reward-based modes.

    Handles two groups of parameters:
      float_cfg  — numeric weights patched as Python floats.
      bool_cfg   — boolean flags patched as True / False literals.

    All keys reset to defaults when overrides is None so settings never
    leak between consecutive batch runs.
    """
    # ── Bool mode flags (all default False so a previous run's flag can't leak) ─
    bool_cfg = {
        "REWARD_INV_DELAY_MODE": False,
        "REWARD_V2X_MODE":       False,
        "REWARD_SELFORG_MODE":   False,
        "DCTSP_ZIG_MODE":        False,
        "MP_ECTM_MODE":          False,
        "BXT_MODE":              False,
        "DCTSP_GREEN_REALLOC_MODE": False,
        "BARGAIN_SPM_MODE":      False,
        "HS_EXT_MODE":           False,
        "META_TSP_MODE":         False,
        "MDN_DELAY_MODE":        False,
    }
    # ── Float params (all default to neutral/baseline values) ──────────────────
    float_cfg = {
        "REWARD_ALPHA":            1.0,
        "REWARD_BETA":             1.0,
        "REWARD_GAMMA":            1.0,
        "REWARD_MAIN_SECTION_WEIGHT": 1.0,
        "REWARD_SIDE_SECTION_WEIGHT": 0.50,  # initial: side traffic at half main weight
        "REWARD_DENSITY":          1.0,
        "INV_DELAY_EPSILON":       1.0,
        "INV_DELAY_CAR_WEIGHT":    2.0,
        "INV_DELAY_MIN_DELAY_S":   0.0,
        "V2X_MAX_BUS_OCC":         80.0,
        "V2X_CROWDING_SCALE":      10.0,
        "V2X_EPSILON":             1.0,
        "V2X_MIN_DELAY_S":         0.0,
        "V2X_BALANCE_FACTOR":      1.0,   # default=1.0 (no blocking); V2X exp uses 0.50
        "SELFORG_MIN_BUS_DELAY_S": 10.0,
        "SELFORG_BALANCE_FACTOR":  1.0,
        "SELFORG_MAX_SE_S":        30.0,
        "SELFORG_MIN_SE_S":        5.0,
        "SELFORG_SE_FRACTION":     0.5,
        "SELFORG_PHASE_OVERLAP_S": 5.0,
        "ZIG_PHASE_OVERLAP_S":     3.0,
        "ZIG_BALANCE_FACTOR":      1.0,
        "MP_ECTM_DT_S":            1.0,
        "MP_ECTM_MIN_EXT_S":       3.0,
        "MP_ECTM_MAX_EXT_S":       20.0,
        "MP_ECTM_CAR_OCC":         1.2,
        "MP_ECTM_BALANCE_FACTOR":  1.0,
        "BXT_DT_S":                1.0,
        "BXT_EPSILON":             0.10,
        "BXT_ALPHA":               0.01,
        "BXT_GAMMA":               0.005,
        "BXT_CAR_OCC":             1.2,
        "BXT_BALANCE_FACTOR":      1.0,
        "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
        "BG_DET_LVL_IMM_S":        4.0,
        "BG_DET_LVL_NEAR_S":       12.0,
        "BG_DET_LVL_FAR_S":        24.0,
        "BG_BUS_W_IMM":            1.6,
        "BG_BUS_W_NEAR":           1.35,
        "BG_BUS_W_FAR":            1.10,
        "BG_BUS_W_VFAR":           0.95,
        "BG_SPM_RISK_WEIGHT":      1.8,
        "BG_EQ_FAIRNESS_WEIGHT":   0.55,
        "BG_MIN_BUS_DELAY_S":      10.0,
        "BG_MIN_GAIN_S":           2.5,
        "BG_CASCADE_MULT":         1.5,
        "DCTSP_CONGESTION_GATE_FRACTION": 0.85,
        "META_LATENESS_TAKEOVER_S":  9999.0,   # disabled by default
    }
    bool_cfg["DCTSP_CONGESTION_GATE"] = False
    if overrides:
        for k, v in overrides.items():
            if k in bool_cfg:
                bool_cfg[k] = bool(v)
            elif k in float_cfg:
                try:
                    float_cfg[k] = float(v)
                except Exception:
                    pass

    text = _read_controller(controller_path)
    n_total = 0
    for k, v in float_cfg.items():
        # Normalise spacing so the canonical single-space form is always written,
        # making the verification check below reliable regardless of original indent.
        text, n = re.subn(
            rf'^{k}\s*=\s*.*$',
            f'{k} = {v}',
            text, flags=re.MULTILINE)
        n_total += n
    for k, v in bool_cfg.items():
        text, n = re.subn(
            rf'^{k}\s*=\s*.*$',
            f'{k} = {repr(v)}',
            text, flags=re.MULTILINE)
        n_total += n
    _write_controller(controller_path, text)

    verify = _read_controller(controller_path)
    for k, v in float_cfg.items():
        if f"{k} = {v}" not in verify:
            log(f"WARNING: could not verify {k}={v} in controller")
    for k, v in bool_cfg.items():
        if f"{k} = {repr(v)}" not in verify:
            log(f"WARNING: could not verify {k}={repr(v)} in controller")

    log("Reward weights -> "
        + ", ".join(f"{k}={float_cfg[k]}" for k in float_cfg)
        + " | "
        + ", ".join(f"{k}={bool_cfg[k]}" for k in bool_cfg))


def set_coordinated(controller_path, coordinated: bool):
    """
    Patch COORDINATED_TSP = True/False in the controller.
    True  → corridor-wide bus-priority coordination across intersections.
    False → each intersection runs independently.

    The regex normalises any existing whitespace around the '=' so the
    verification string ('COORDINATED_TSP = True/False') always matches.
    """
    val  = "True" if coordinated else "False"
    text = _read_controller(controller_path)

    # Normalise spacing: replace 'COORDINATED_TSP <spaces>=<spaces> True/False'
    # with the canonical single-space form so verification is reliable.
    text, n = re.subn(
        r'^COORDINATED_TSP\s*=\s*(True|False)',
        f'COORDINATED_TSP = {val}',
        text, flags=re.MULTILINE)

    if n == 0:
        log("WARNING: COORDINATED_TSP not found in controller — cannot set.")
        return

    _write_controller(controller_path, text)

    # Verify (normalised form is now always present)
    verify = _read_controller(controller_path)
    if f'COORDINATED_TSP = {val}' not in verify:
        log(f"WARNING: COORDINATED_TSP patch verification failed. "
            f"Expected 'COORDINATED_TSP = {val}' in file.")
    else:
        log(f"COORDINATED_TSP -> {val}  [patch verified OK]")


def set_coordination_algo(controller_path, algo: str):
    """
    Patch COORDINATION_ALGO = "..." in the controller.
    Supported values: KALMAN | SHOCKWAVE | OBJECTIVE | ADAPTIVE.
    """
    algo_u = str(algo or "KALMAN").strip().upper()
    if algo_u not in {"KALMAN", "SHOCKWAVE", "OBJECTIVE", "ADAPTIVE"}:
        log(f"WARNING: unsupported COORDINATION_ALGO '{algo_u}', defaulting to KALMAN")
        algo_u = "KALMAN"

    text = _read_controller(controller_path)
    # Normalise spacing so the canonical single-space form is always written.
    text, n = re.subn(
        r'^COORDINATION_ALGO\s*=\s*["\'].*?["\']',
        f'COORDINATION_ALGO = "{algo_u}"',
        text, flags=re.MULTILINE)

    if n == 0:
        log("WARNING: COORDINATION_ALGO not found in controller — cannot set.")
        return

    _write_controller(controller_path, text)

    verify = _read_controller(controller_path)
    if f'COORDINATION_ALGO = "{algo_u}"' in verify:
        log(f"COORDINATION_ALGO -> {algo_u}  [patch verified OK]")
    else:
        log(f"WARNING: COORDINATION_ALGO patch verification failed for {algo_u}")


def write_run_config(experiment_name, strategy, seed, scalar,
                     coordinated, coordination_algo, run_config_path,
                     global_reward_mode=False, reward_cfg=None,
                     bus_predictor="KALMAN"):
    content = (
        "CURRENT_STRATEGY = "        + repr(strategy)           + "\n"
        "CURRENT_EXPERIMENT = "      + repr(experiment_name)    + "\n"
        "CURRENT_SEED = "            + repr(seed)               + "\n"
        "CURRENT_DEMAND_SCALAR = "   + repr(scalar)             + "\n"
        "CURRENT_COORDINATED = "     + repr(coordinated)        + "\n"
        "CURRENT_COORDINATION_ALGO = "+ repr(coordination_algo) + "\n"
        "BUS_PREDICTOR_TYPE = "      + repr(str(bus_predictor).upper()) + "\n"
        "GLOBAL_REWARD_MODE = "      + repr(bool(global_reward_mode)) + "\n"
        "BARGAIN_SPM_MODE = "        + repr(bool((reward_cfg or {}).get('BARGAIN_SPM_MODE', False))) + "\n"
        "DCTSP_GREEN_REALLOC_MODE = "+ repr(bool((reward_cfg or {}).get('DCTSP_GREEN_REALLOC_MODE', False))) + "\n"
        "GREEN_REALLOC_RECOVER_FRACTION = " + repr(float((reward_cfg or {}).get('GREEN_REALLOC_RECOVER_FRACTION', 1.0))) + "\n"
    )
    for k, v in (reward_cfg or {}).items():
        content += f"{k} = {repr(v)}\n"
    with open(run_config_path, 'w', encoding='utf-8') as f:
        f.write(content)
    log(f"run_config written: experiment={experiment_name} "
        f"seed={seed} scalar={scalar} coordinated={coordinated} "
        f"coord_algo={coordination_algo} predictor={bus_predictor} "
        f"global_reward={global_reward_mode} "
        f"INV_DELAY={reward_cfg.get('REWARD_INV_DELAY_MODE',False) if reward_cfg else False} "
        f"V2X={reward_cfg.get('REWARD_V2X_MODE',False) if reward_cfg else False} "
        f"SELFORG={reward_cfg.get('REWARD_SELFORG_MODE',False) if reward_cfg else False} "
        f"ZIG={reward_cfg.get('DCTSP_ZIG_MODE',False) if reward_cfg else False} "
        f"MP_ECTM={reward_cfg.get('MP_ECTM_MODE',False) if reward_cfg else False} "
        f"BXT={reward_cfg.get('BXT_MODE',False) if reward_cfg else False} "
        f"GREEN_REALLOC={reward_cfg.get('DCTSP_GREEN_REALLOC_MODE',False) if reward_cfg else False} "
        f"BARGAIN_SPM={reward_cfg.get('BARGAIN_SPM_MODE',False) if reward_cfg else False} "
        f"META_TSP={reward_cfg.get('META_TSP_MODE',False) if reward_cfg else False}")


# =============================================================================
# ── REPLICATION HELPERS ───────────────────────────────────────────────────────
# =============================================================================
def get_first_replication():
    model = GKSystem.getSystem().getActiveModel()
    if model is None:
        raise RuntimeError("No active model.")
    rep_type = model.getType("GKReplication")
    if rep_type is None:
        raise RuntimeError("No GKReplication type found.")
    reps = model.getCatalog().getObjectsByType(rep_type)
    if not reps:
        raise RuntimeError("No replications found.")
    return next(iter(reps.values())) if isinstance(reps, dict) else reps[0]


def set_seed(rep, seed):
    try:
        rep.setRandomSeed(seed)
    except Exception:
        try:
            rep.getExperiment().setRandomSeed(seed)
        except Exception as e:
            log("WARNING: could not set seed: " + str(e))
    log("Seed -> " + str(seed))


def _close_dialogs(app):
    if app is None:
        return
    app.processEvents()
    try:
        from PyQt5.QtWidgets import QDialog, QPushButton
        for w in app.topLevelWidgets():
            if not w.isVisible():
                continue
            title = w.windowTitle().lower()
            if not any(k in title for k in ('result', 'statistic', 'summary',
                                             'finish', 'output')):
                continue
            clicked = False
            for btn in w.findChildren(QPushButton):
                if any(t in btn.text().lower().replace('&', '')
                       for t in ('close', 'ok', 'cancel')):
                    btn.click()
                    clicked = True
                    break
            if not clicked and isinstance(w, QDialog):
                w.reject()
        app.processEvents()
    except Exception:
        pass


def run_replication(rep):
    try:
        rep.setStorePaths(False)
    except Exception:
        pass
    try:
        rep.setOutputPathAssignment(None)
    except Exception:
        pass
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
    except ImportError:
        app = None

    GKSystem.getSystem().executeAction("execute", rep, [], "")
    _time.sleep(2.0)
    if app:
        app.processEvents()

    waited  = 0.0
    started = False
    while waited < 7200.0:
        if app:
            app.processEvents()
        try:
            status = rep.getSimulationStatus()
        except Exception:
            status = -1
        if not started and status == 1:
            started = True
            log("Simulation running...")
        if started and status != 1:
            break
        if not started and waited > 30.0:
            log("Assuming synchronous completion.")
            break
        _time.sleep(0.5)
        waited += 0.5
        if started and int(waited) % 30 == 0:
            log(f"  still running... {int(waited)}s")

    _time.sleep(2.0)
    if app:
        app.processEvents()
        _close_dialogs(app)


# =============================================================================
# ── METRICS COLLECTION ────────────────────────────────────────────────────────
# =============================================================================

def _find_results_folder(project_dir, strategy, seed, scalar, exp_name=None):
    """
    Locate the most-recently-written per-run results folder.

    The SimulationStats class writes to:
        <project>/results/<strategy>_seed<N>_<scenario>_<experiment>_<rep>/

    Newer runs write to:
        <project>/results/<experiment>_seed<N>_<scenario>_<experimentId>_<rep>/

    Older runs used '<strategy>_seed<seed>_...'. Try experiment prefix first,
    then fall back to strategy prefix for backward compatibility.
    """
    results_base = _os.path.join(project_dir, 'results')
    if not _os.path.isdir(results_base):
        return None

    prefixes = []
    if exp_name:
        safe_exp = ''.join(ch if ch.isalnum() or ch in ('_', '-') else '_' for ch in str(exp_name)).strip('_')
        if safe_exp:
            prefixes.append(f"{safe_exp}_seed{seed}")
    prefixes.append(f"{strategy}_seed{seed}")

    candidates = []
    for prefix in prefixes:
        candidates = [
            d for d in _os.scandir(results_base)
            if d.is_dir() and d.name.startswith(prefix)
        ]
        if candidates:
            break

    if not candidates:
        return None

    return max(candidates, key=lambda d: d.stat().st_mtime).path


def _read_csv_first_row(csv_path):
    """Read the LAST data row of a CSV as a dict (most recent run appended)."""
    if not _os.path.isfile(csv_path):
        return {}
    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        return rows[-1] if rows else {}
    except Exception:
        return {}


def _read_json(json_path):
    if not _os.path.isfile(json_path):
        return {}
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _latest_rows_by_intersection(rows):
    """
    Keep only the latest row per intersection ID.

    simulation_results_per_intersection.csv is append-only across repeated runs,
    so run-scoped filtering can still return historical duplicates. Taking the
    latest row per intersection recovers the current-run snapshot.
    """
    latest = {}
    for r in rows:
        iid = str(r.get("IntersectionID", "")).strip()
        if not iid:
            continue
        latest[iid] = r
    return list(latest.values())


def _clear_previous_outputs(project_dir):
    """
    Start batch from a clean state.

    Removes old logs and prior generated batch artifacts so dashboard and CSV
    metrics always reflect the current batch only.
    """
    removed = {"files": 0, "dirs": 0}

    def _safe_remove(path):
        try:
            if _os.path.isdir(path):
                shutil.rmtree(path)
                removed["dirs"] += 1
            elif _os.path.isfile(path):
                _os.remove(path)
                removed["files"] += 1
        except Exception as e:
            log(f"WARNING: could not remove {path}: {e}")

    # 1) logs/ folder contents
    logs_dir = _os.path.join(project_dir, "logs")
    if _os.path.isdir(logs_dir):
        for name in _os.listdir(logs_dir):
            _safe_remove(_os.path.join(logs_dir, name))

    # 2) Batch-level artifacts
    for p in (
        _os.path.join(project_dir, "batch_results.csv"),
        _os.path.join(project_dir, "batch_manifest.json"),
        _os.path.join(project_dir, "tsp_dashboard.html"),
    ):
        _safe_remove(p)

    # 3) Per-run result CSV/JSON files inside results/* folders
    results_dir = _os.path.join(project_dir, "results")
    if _os.path.isdir(results_dir):
        for d in _os.scandir(results_dir):
            if not d.is_dir():
                continue
            for fname in (
                "simulation_results.csv",
                "simulation_results_per_intersection.csv",
                "summary.json",
                "bus_trips.csv",
                # section_stats.csv is append-only and accumulates rows across
                # repeated runs (same folder, same Aimsun IDs).  Delete it so
                # each batch starts with a clean per-section snapshot and the
                # dashboard never averages old high-density runs with new ones.
                "section_stats.csv",
            ):
                _safe_remove(_os.path.join(d.path, fname))

    log(f"Startup cleanup done: removed {removed['files']} files, {removed['dirs']} folders")


def collect_run_metrics(project_dir, strategy, seed, scalar,
                        exp_name, coordinated, elapsed_s, success,
                        bus_predictor="KALMAN"):
    """
    After a simulation run, read SimulationStats output files and return a
    flat dict of all key metrics for this run.

    Sources
    -------
    simulation_results.csv          — global KPIs (delay, pax, TSP events)
    simulation_results_per_intersection.csv — per-junction detail (first row only)
    summary.json                    — quick overview
    Aimsun model objects            — network-level flow/density/speed via PyANGKernel
    """
    meta = {
        "run_experiment":       exp_name,
        "run_strategy":         strategy,
        "run_coordinated":      coordinated,
        "run_seed":             seed,
        "run_demand_scalar":    scalar,
        "run_elapsed_s":        elapsed_s,
        "run_success":          success,
        "run_bus_predictor":    str(bus_predictor).upper(),
    }

    if not success:
        return meta

    folder = _find_results_folder(project_dir, strategy, seed, scalar, exp_name)
    if folder is None:
        log(f"  WARNING: results folder not found for {strategy} seed={seed}")
        return meta

    # Store the results folder path so generate_dashboard.py can load per-intersection CSVs
    meta["stats_results_folder"] = folder

    # ── 1. Global simulation_results.csv ──────────────────────────────────────
    global_row = _read_csv_first_row(_os.path.join(folder, "simulation_results.csv"))
    for k, v in global_row.items():
        if k is not None:
            meta["stats_" + k] = v

    # ── 2. summary.json ───────────────────────────────────────────────────────
    summary = _read_json(_os.path.join(folder, "summary.json"))
    for k, v in summary.items():
        if isinstance(v, (int, float, str, bool)):
            meta["json_" + k] = v

    # ── 3. Per-intersection aggregates from simulation_results_per_intersection.csv
    inter_csv = _os.path.join(folder, "simulation_results_per_intersection.csv")
    if _os.path.isfile(inter_csv):
        try:
            with open(inter_csv, 'r', newline='', encoding='utf-8') as f:
                rows = list(csv.DictReader(f))
            # Aggregate numeric columns across all intersections for this run
            # (all rows belong to this run — filter by TSP_Strategy to be safe)
            # Filter to THIS run only using the IDs from the global CSV row.
            # Without this, accumulated CSV rows from prior runs of the same
            # strategy inflate inter_sum (e.g. 2 runs × 9 intersections = 18 rows).
            _scen = str(global_row.get("ScenarioID", "")).strip()
            _exp  = str(global_row.get("ExperimentID", "")).strip()
            _rep  = str(global_row.get("ReplicationID", "")).strip()
            if _scen and _exp and _rep:
                run_rows = [
                    r for r in rows
                    if str(r.get("ScenarioID","")).strip()  == _scen
                    and str(r.get("ExperimentID","")).strip() == _exp
                    and str(r.get("ReplicationID","")).strip() == _rep
                ]
            else:
                run_rows = [r for r in rows if r.get("TSP_Strategy", "") == strategy]
            if not run_rows:
                run_rows = [r for r in rows if r.get("TSP_Strategy", "") == strategy] or rows

            # Historical rows accumulate across repeated runs in the same folder.
            # Keep the latest row per intersection to isolate current-run values.
            run_rows = _latest_rows_by_intersection(run_rows)
            agg_cols = [
                "TotalPassDelay_hrs", "MainPassDelay_hrs", "SidePassDelay_hrs",
                "BusTotalTT_hrs", "N_BusTrips", "N_DistinctBuses",
                "N_DistinctCars", "N_DistinctTrucks",
                "BusVehPassages", "CarVehPassages", "TruckVehPassages",
                "PaxEquivPassages", "BusPaxEquivPassages", "CarPaxEquivPassages",
                "AvgBusTT_s", "AvgPassDelay_s",
                "AvgBusPassDelay_s", "AvgCarPassDelay_s", "AvgTruckPassDelay_s",
                "TSP_Detections", "TSP_Extensions", "TSP_Insertions",
                "TSP_Skipped_GE", "TSP_Skipped_Ins", "TSP_Detected_NoAction",
                "TSP_NaturalGreen",   # bus caught green without any TSP action
            ]
            for col in agg_cols:
                vals = []
                for r in run_rows:
                    try:
                        vals.append(float(r[col]))
                    except Exception:
                        pass
                if vals:
                    meta[f"inter_sum_{col}"] = round(sum(vals), 4)
                    meta[f"inter_avg_{col}"] = round(sum(vals) / len(vals), 4)
                    meta[f"inter_n"]          = len(run_rows)
        except Exception as e:
            log(f"  WARNING: could not parse per-intersection CSV: {e}")

    # ── 4. Aimsun model network-level statistics (PyANGKernel) ───────────────
    try:
        aimsun_stats = _collect_aimsun_network_stats()
        meta.update(aimsun_stats)
    except Exception as e:
        log(f"  INFO: Aimsun network stats not available: {e}")

    # ── 5. Fallback: section_stats.csv for density/speed/flow ─────────────────
    # When simulation_results.csv is missing or has empty/unreasonable network
    # stats, read from section_stats.csv which is always written by save_results().
    # Also override when Net_TotalFlowVeh > 50 000 veh/h — that indicates Aimsun
    # returned a cumulative passage count rather than a flow rate (known bug when
    # the wrong GKSystemStatistic type is resolved, e.g. DCTSP_MARL ~673 M).
    _flow_from_sim    = float(meta.get('stats_Net_TotalFlowVeh', 0) or 0)
    _density_from_sim = float(meta.get('stats_Net_AvgDensity_vkm', 0) or 0)
    _speed_from_sim   = float(meta.get('stats_Net_AvgSpeed_kmh', 0) or 0)
    # Flow is bogus when Aimsun returns a cumulative passage count (e.g. 1 B)
    # instead of a rate.  Density and speed from GKSystemStatistic are usually
    # correct even when flow is wrong, so treat them independently.
    _flow_bogus       = (_flow_from_sim > 50_000.0 or _flow_from_sim <= 0.0)
    _density_missing  = not _density_from_sim
    _need_net_fallback = _flow_bogus or _density_missing
    sec_csv = _os.path.join(folder, "section_stats.csv")
    if _need_net_fallback and _os.path.isfile(sec_csv):
        try:
            with open(sec_csv, 'r', newline='', encoding='utf-8') as _f:
                _all_sec_rows = list(csv.DictReader(_f))
            # De-duplicate: section_stats.csv is append-only; multiple runs append
            # rows for the same SectionID. Keep the LAST row per SectionID (last
            # written = most recent simulation run) to use only current-run data.
            _last_by_sec = {}
            for _sr in _all_sec_rows:
                _sid = str(_sr.get('SectionID', '') or '')
                if _sid:
                    _last_by_sec[_sid] = _sr   # always overwrite → keeps last
            _sec_rows = list(_last_by_sec.values()) if _last_by_sec else []
            if _sec_rows:
                _tot_len = 0.0; _wt_dens = 0.0; _wt_spd = 0.0; _wt_flow = 0.0
                _tot_q = 0.0;  _n_sec = 0
                for _sr in _sec_rows:
                    try:
                        _l = float(_sr.get('Length_km', 0) or 0)
                        _d = float(_sr.get('AvgDensity_vkm', 0) or 0)
                        _s = float(_sr.get('AvgSpeed_kmh', 0) or 0)
                        _fl = float(_sr.get('AvgFlow_veh_h', 0) or 0)
                        _q = float(_sr.get('AvgQueue_veh', 0) or 0)
                        if _l > 0 and _s > 0:
                            _tot_len += _l; _wt_dens += _d * _l
                            _wt_spd  += _s * _l; _wt_flow += _fl * _l
                            _tot_q   += _q; _n_sec += 1
                    except Exception:
                        pass
                if _tot_len > 0:
                    # Only use section_stats density/speed if missing from sim results.
                    # GKSystemStatistic density/speed are correct even when flow is bogus;
                    # overwriting them with section-level averages would make things worse.
                    if _density_missing:
                        meta['stats_Net_AvgDensity_vkm'] = round(_wt_dens / _tot_len, 4)
                        meta['stats_Net_Density_All']     = round(_wt_dens / _tot_len, 4)
                    if not _speed_from_sim:
                        meta['stats_Net_AvgSpeed_kmh'] = round(_wt_spd / _tot_len, 3)
                    # For flow: prefer (N_DistinctVeh / SimDuration_hrs) over the
                    # section-level length-weighted average.  The latter is a per-section
                    # flow (~1 400 veh/h/section) which is not the same metric as the
                    # network-level exit flow (~7 000 veh/h) that other experiments report.
                    if _flow_bogus:
                        _n_cars   = float(meta.get('stats_N_DistinctCars',   0) or 0)
                        _n_buses  = float(meta.get('stats_N_DistinctBuses',  0) or 0)
                        _n_trucks = float(meta.get('stats_N_DistinctTrucks', 0) or 0)
                        _sim_dur  = float(meta.get('stats_SimDuration_hrs',  0) or 0)
                        if (_n_cars + _n_buses) > 0 and _sim_dur > 0:
                            meta['stats_Net_TotalFlowVeh'] = round(
                                (_n_cars + _n_buses + _n_trucks) / _sim_dur)
                            log(f"  Flow estimated from distinct vehicles: "
                                f"{meta['stats_Net_TotalFlowVeh']} veh/h "
                                f"({int(_n_cars)}+{int(_n_buses)}+{int(_n_trucks)} / {_sim_dur:.2f}h)")
                        elif _wt_flow > 0:
                            meta['stats_Net_TotalFlowVeh'] = round(_wt_flow / _tot_len, 2)
                            log(f"  Flow from section_stats fallback: {meta['stats_Net_TotalFlowVeh']}")
                    meta['section_avg_queue_veh'] = round(_tot_q / _n_sec, 2) if _n_sec else 0
                    log(f"  section_stats.csv used for {'density/speed ' if _density_missing else ''}"
                        f"{'flow' if _flow_bogus else ''} ({_n_sec} sections)")
        except Exception as _e:
            log(f"  INFO: section_stats.csv fallback failed: {_e}")

    # ── 6. TSP event counts from detection_points CSV ────────────────────────
    # Fallback when simulation_results.csv has no TSP stats (empty or missing):
    # count harmony-ge-local / harmony-ins-local / IC-detect tiers from the
    # detection_points log which is always written by AAPIFinish.
    _need_tsp_fallback = not meta.get("stats_TSP_Extensions")
    if _need_tsp_fallback:
        _logs_dir = _os.path.join(_os.path.dirname(folder), '..', 'logs')
        _logs_dir = _os.path.normpath(_logs_dir)
        if not _os.path.isdir(_logs_dir):
            _logs_dir = _os.path.join(_os.path.dirname(__file__), 'logs')
        # Find detection_points CSV matching this experiment
        _exp_lower = exp_name.lower()
        _det_csvs  = sorted(glob.glob(_os.path.join(_logs_dir, "detection_points_*.csv")),
                            key=_os.path.getmtime)
        _det_csv = None
        for _f in reversed(_det_csvs):
            _stem = _os.path.splitext(_os.path.basename(_f))[0].lower()
            _payload = _stem.replace("detection_points_", "")
            _parts = _payload.split("_")
            if len(_parts) >= 3 and _parts[-1].isdigit() and _parts[-2].isdigit():
                _tok = "_".join(_parts[:-2])
                if _tok == _exp_lower:
                    _det_csv = _f
                    break
        if _det_csv and _os.path.isfile(_det_csv):
            try:
                _ge = _ins = _det = 0
                with open(_det_csv, newline='', encoding='utf-8') as _df:
                    for _dr in csv.DictReader(_df):
                        _tier = str(_dr.get('tier', '') or '')
                        if _tier == 'harmony-ge-local':
                            _ge += 1
                        elif _tier == 'harmony-ins-local':
                            _ins += 1
                        elif _tier == 'IC-detect':
                            _det += 1
                meta['stats_TSP_Extensions']  = _ge
                meta['stats_TSP_Insertions']  = _ins
                meta['stats_TSP_Detections']  = _det
                log(f"  TSP events from detection CSV: GE={_ge} INS={_ins} DET={_det}")
            except Exception as _de:
                log(f"  INFO: detection_points TSP count failed: {_de}")

    # ── 7. Weighted-objective (Z1/Z2/Z4 composite) totals for this run ──────────
    # intersection_controller.py writes one row per evaluated cycle to
    # logs/weighted_objective_<experiment>_<timestamp>.csv with running totals
    # (Z1_total, Z2_total, objective_total) plus alpha/beta/weights/rho. Read
    # the LAST row (= final accumulated totals) so a weight-sweep batch can
    # plot total_weighted_delay (Z1) vs offset_correction_magnitude (Z2) — i.e.
    # find the Pareto frontier across an ALPHA/BETA grid. Z4 (total travel time
    # in the corridor, veh·h) is a network/corridor-level quantity, not a
    # per-cycle one -- it is computed directly below from
    # Net_TotalTT_h_Car/Bus/Truck (already in `meta` from section 1).
    _wobj_logs_dir = _os.path.join(_os.path.dirname(folder), '..', 'logs')
    _wobj_logs_dir = _os.path.normpath(_wobj_logs_dir)
    if not _os.path.isdir(_wobj_logs_dir):
        _wobj_logs_dir = _os.path.join(_os.path.dirname(__file__), 'logs')
    _wobj_exp_lower = exp_name.lower()
    _wobj_csvs = sorted(glob.glob(_os.path.join(_wobj_logs_dir, "weighted_objective_*.csv")),
                        key=_os.path.getmtime)
    _wobj_csv = None
    for _f in reversed(_wobj_csvs):
        _stem = _os.path.splitext(_os.path.basename(_f))[0].lower()
        _payload = _stem.replace("weighted_objective_", "")
        _parts = _payload.split("_")
        if len(_parts) >= 3 and _parts[-1].isdigit() and _parts[-2].isdigit():
            _tok = "_".join(_parts[:-2])
            if _tok == _wobj_exp_lower:
                _wobj_csv = _f
                break
    if _wobj_csv and _os.path.isfile(_wobj_csv):
        try:
            with open(_wobj_csv, newline='', encoding='utf-8') as _wf:
                _wobj_rows = list(csv.DictReader(_wf))
            if _wobj_rows:
                _last = _wobj_rows[-1]
                meta['wobj_Z1_total']        = float(_last.get('Z1_total', 0) or 0)
                meta['wobj_Z2_total']        = float(_last.get('Z2_total', 0) or 0)
                meta['wobj_Z3_total']        = float(_last.get('Z3_total', 0) or 0)
                meta['wobj_objective_total'] = float(_last.get('objective_total', 0) or 0)
                meta['wobj_n']               = int(float(_last.get('n', 0) or 0))
                meta['wobj_alpha']           = float(_last.get('alpha', 0) or 0)
                meta['wobj_beta']            = float(_last.get('beta', 0) or 0)
                meta['wobj_gamma']           = float(_last.get('gamma', 0) or 0)
                meta['wobj_w_main']          = float(_last.get('w_main', 0) or 0)
                meta['wobj_w_side']          = float(_last.get('w_side', 0) or 0)
                meta['wobj_rho_bus']         = float(_last.get('rho_bus', 0) or 0)
                meta['wobj_rho_car']         = float(_last.get('rho_car', 0) or 0)
                # Convenience aliases matching the Pareto-plot axes by name
                meta['total_weighted_delay']        = meta['wobj_Z1_total']
                meta['offset_correction_magnitude'] = meta['wobj_Z2_total']
                meta['bus_lateness_total']          = meta['wobj_Z3_total']
                log(f"  Weighted objective totals: Z1={meta['wobj_Z1_total']:.1f} "
                    f"Z2={meta['wobj_Z2_total']:.1f} "
                    f"Z3={meta['wobj_Z3_total']:.1f} "
                    f"obj={meta['wobj_objective_total']:.1f} "
                    f"(alpha={meta['wobj_alpha']} beta={meta['wobj_beta']} "
                    f"gamma={meta['wobj_gamma']}, n={meta['wobj_n']})")
        except Exception as _we:
            log(f"  INFO: weighted_objective CSV parse failed: {_we}")

    # ── Z4: total vehicle kilometres in the corridor (veh·km), network-level ───────────
    # Z4 now represents total vehicle-km travelled (throughput metric).
    # This is calculated as sum(flow_veh/h × section_length_km) across network.
    # Prefer aimsun_total_veh_km_h if available; fall back to travel time for comparison.
    meta['wobj_Z4_total'] = float(meta.get('aimsun_total_veh_km_h', 0) or 0)
    if meta['wobj_Z4_total'] <= 0:
        # Fallback to travel time if vehicle-km not available
        meta['wobj_Z4_total'] = (float(meta.get('stats_Net_TotalTT_h_Car', 0) or 0)
                                  + float(meta.get('stats_Net_TotalTT_h_Bus', 0) or 0)
                                  + float(meta.get('stats_Net_TotalTT_h_Truck', 0) or 0))
    meta['corridor_total_veh_km'] = meta['wobj_Z4_total']
    log(f"  Corridor total vehicle-km (Z4): {meta['wobj_Z4_total']:.1f} veh-km")

    # ── Z1/Z2/Z3 fallback for any run without a weighted_objective CSV ──────────
    # TSP experiments write weighted_objective_*.csv; NO_TSP does not.
    # Use Aimsun network-wide stats for fallbacks — these are stable regardless
    # of which junctions the TSP controller monitors (unlike stats_MainPassDelay_hrs
    # which changes when new intersections are added to INTERSECTIONS_CONFIG).
    _z1 = meta.get('wobj_Z1_total', 0) or 0
    if abs(_z1) < 0.01:
        try:
            # Z1: use direct Aimsun simulation total pax delay (network stat, not
            # TSP-controller-scoped) so NO_TSP baseline is stable across config changes.
            _sim_z1 = float(meta.get('stats_SimTotalDelay_pax_s', 0) or 0)
            if _sim_z1 > 0:
                meta['wobj_Z1_total'] = _sim_z1
                meta['wobj_objective_total'] = 0.8 * _sim_z1
                log(f"  Z1 (fallback, SimTotalDelay): {_sim_z1:.1f} pax-s")
            else:
                # Older formula fallback using main/side delay split
                _md = float(meta.get('stats_MainPassDelay_hrs', 0) or 0)
                _sd = float(meta.get('stats_SidePassDelay_hrs', 0) or 0)
                _bp = float(meta.get('stats_BusPaxEquivPassages', 0) or 0)
                _cp = float(meta.get('stats_CarPaxEquivPassages', 0) or 0)
                _tp = _bp + _cp
                if _tp > 0 and (_md > 0 or _sd > 0):
                    _bs = _bp / _tp
                    _cs = _cp / _tp
                    _rb = 40.0; _rc = 1.5
                    _bvs = _md * 3600 * _bs / _rb
                    _cvm = _md * 3600 * _cs / _rc
                    _cvs = _sd * 3600 / _rc
                    _z1_approx = 0.8 * _rb * _bvs + 0.8 * _rc * _cvm + 0.6 * _rc * _cvs
                    meta['wobj_Z1_total'] = _z1_approx
                    meta['wobj_objective_total'] = 0.8 * _z1_approx
                    log(f"  Z1 (fallback, formula): {_z1_approx:.1f} pax-s")
        except Exception:
            pass

    # Z2 (bandwidth) fallback: estimate from natural-green rate when not in wobj CSV
    _z2 = meta.get('wobj_Z2_total', 0) or 0
    if abs(_z2) < 0.01:
        try:
            _dets = float(meta.get('stats_TSP_Detections', 0) or 0)
            _natg = float(meta.get('stats_TSP_NaturalGreen', 0) or 0)
            if _dets > 0:
                _rate = _natg / _dets
                # Natural green = bus arrives to existing green (~12 s effective window);
                # non-natural = bus arrives to red (effective window ~3 s).
                _avg_bw = _rate * 12.0 + (1.0 - _rate) * 3.0
                meta['wobj_Z2_total'] = _dets * _avg_bw
                log(f"  Z2 (fallback, natural-green): {meta['wobj_Z2_total']:.0f} s")
        except Exception:
            pass

    # Z3 (bus lateness) fallback: use total bus pax delay from simulation as proxy
    _z3 = meta.get('wobj_Z3_total', 0) or 0
    if abs(_z3) < 0.01:
        try:
            _sim_z3 = float(meta.get('stats_SimBusDelay_pax_s', 0) or 0)
            if _sim_z3 > 0:
                meta['wobj_Z3_total'] = _sim_z3
                log(f"  Z3 (fallback, SimBusDelay proxy): {_sim_z3:.1f} pax-s")
        except Exception:
            pass

    log(f"  Metrics collected from: {folder}")
    return meta


def _collect_aimsun_network_stats():
    """
    Read network-level statistics from the Aimsun model object after a run.

    Returns a dict with keys prefixed 'aimsun_'.
    Falls back gracefully if any API call fails.

    Aimsun Next 25/26 statistics API is version-dependent. We try multiple
    patterns in order:
      1. getDataValueString / getDataValue (Aimsun Next 25+)
      2. Direct attribute access (getFlow, getDensity, getMeanSpeed)
      3. No-arg getStatistic() for some column IDs
    """
    out = {}
    try:
        model = GKSystem.getSystem().getActiveModel()
        if model is None:
            return out

        sec_type = model.getType("GKSection")
        if sec_type is None:
            return out

        sections = model.getCatalog().getObjectsByType(sec_type)
        if not sections:
            return out

        sec_list = list(sections.values()) if isinstance(sections, dict) else list(sections)

        # Length-weighted accumulators (all vehicles and per-type)
        # Aimsun reports length-weighted averages: total(metric×length) / total(length)
        wt_flow     = 0.0;  wt_density  = 0.0;  wt_speed    = 0.0;  wt_delay    = 0.0
        wt_flow_car = 0.0;  wt_dens_car = 0.0;  wt_spd_car  = 0.0;  wt_dly_car  = 0.0
        wt_flow_bus = 0.0;  wt_dens_bus = 0.0;  wt_spd_bus  = 0.0;  wt_dly_bus  = 0.0
        wt_flow_trk = 0.0;  wt_dens_trk = 0.0;  wt_spd_trk  = 0.0;  wt_dly_trk  = 0.0
        # Total throughput: sum(flow_vph × len_km) = network veh-km/h produced
        sum_flow_veh_km_h     = 0.0
        sum_flow_car_veh_km_h = 0.0
        sum_flow_bus_veh_km_h = 0.0
        total_len   = 0.0
        n_sec       = 0
        n_flow_ok   = 0

        for sec in sec_list:
            try:
                # Section length in metres → km
                sec_len_km = 0.0
                for attr in ("length2D", "length", "getLengthInMeters"):
                    try:
                        fn = getattr(sec, attr, None)
                        v = fn() if callable(fn) else fn
                        if v is not None and float(v) > 0:
                            sec_len_km = float(v) / 1000.0
                            break
                    except Exception:
                        pass
                if sec_len_km <= 0:
                    sec_len_km = 0.1  # 100 m default so unresolved sections still contribute

                flow    = _safe_stat_v2(sec, "flow")
                density = _safe_stat_v2(sec, "density")
                speed   = _safe_stat_v2(sec, "speed")
                delay   = _safe_stat_v2(sec, "delay")

                n_sec += 1
                if flow > 0:
                    n_flow_ok += 1
                wt_flow    += flow    * sec_len_km
                wt_density += density * sec_len_km
                wt_speed   += speed   * sec_len_km
                wt_delay   += delay   * sec_len_km
                total_len  += sec_len_km
                sum_flow_veh_km_h += flow * sec_len_km

                # Per-vehicle-type: try car, bus, truck via named-type stat methods
                for _prefix, _ttype in (("car", "Car"), ("bus", "Bus"), ("truck", "Truck")):
                    _flow  = _safe_stat_v2_typed(sec, "flow",    _ttype)
                    _dens  = _safe_stat_v2_typed(sec, "density", _ttype)
                    _spd   = _safe_stat_v2_typed(sec, "speed",   _ttype)
                    _dly   = _safe_stat_v2_typed(sec, "delay",   _ttype)
                    if _prefix == "car":
                        wt_flow_car += _flow * sec_len_km; wt_dens_car += _dens * sec_len_km
                        wt_spd_car  += _spd  * sec_len_km; wt_dly_car  += _dly  * sec_len_km
                        sum_flow_car_veh_km_h += _flow * sec_len_km
                    elif _prefix == "bus":
                        wt_flow_bus += _flow * sec_len_km; wt_dens_bus += _dens * sec_len_km
                        wt_spd_bus  += _spd  * sec_len_km; wt_dly_bus  += _dly  * sec_len_km
                        sum_flow_bus_veh_km_h += _flow * sec_len_km
                    else:
                        wt_flow_trk += _flow * sec_len_km; wt_dens_trk += _dens * sec_len_km
                        wt_spd_trk  += _spd  * sec_len_km; wt_dly_trk  += _dly  * sec_len_km
            except Exception:
                pass

        if n_sec > 0 and total_len > 0:
            out["aimsun_n_sections"]        = n_sec
            out["aimsun_flow_sections_ok"]  = n_flow_ok
            # Total throughput: sum(flow × length) — not biased by network size
            # Use this to compare strategies: higher means more vehicles moved
            out["aimsun_total_veh_km_h"]     = round(sum_flow_veh_km_h, 1)
            out["aimsun_total_car_veh_km_h"] = round(sum_flow_car_veh_km_h, 1)
            out["aimsun_total_bus_veh_km_h"] = round(sum_flow_bus_veh_km_h, 1)
            # Length-weighted network averages — match Aimsun's Time Series output
            if wt_flow > 0:
                out["aimsun_total_flow_veh"]   = round(wt_flow    / total_len, 2)
                out["aimsun_avg_density_vkm"]  = round(wt_density / total_len, 4)
                out["aimsun_avg_speed_kmh"]    = round(wt_speed   / total_len, 4)
                out["aimsun_avg_delay_s_km"]   = round(wt_delay   / total_len, 2)
            else:
                # Fallback: use stats_Net_TotalFlowVeh if section stats unavailable
                _fallback_flow = float(meta.get('stats_Net_TotalFlowVeh', 0) or 0)
                out["aimsun_total_flow_veh"]   = _fallback_flow if _fallback_flow > 0 else 0.0
                out["aimsun_avg_density_vkm"]  = 0.0
                out["aimsun_avg_speed_kmh"]    = 0.0
                out["aimsun_avg_delay_s_km"]   = 0.0
            # Per-type averages (car, bus, truck) — always populate even if 0
            for _pfx, _wf, _wd, _ws, _wdly in [
                ("car", wt_flow_car, wt_dens_car, wt_spd_car, wt_dly_car),
                ("bus", wt_flow_bus, wt_dens_bus, wt_spd_bus, wt_dly_bus),
                ("truck", wt_flow_trk, wt_dens_trk, wt_spd_trk, wt_dly_trk),
            ]:
                if _wf > 0 and total_len > 0:
                    out[f"aimsun_flow_{_pfx}"]    = round(_wf   / total_len, 2)
                    out[f"aimsun_density_{_pfx}"] = round(_wd   / total_len, 4)
                    out[f"aimsun_speed_{_pfx}"]   = round(_ws   / total_len, 4)
                    out[f"aimsun_delay_{_pfx}"]   = round(_wdly / total_len, 2)
                else:
                    # Fallback: use type-specific net stats
                    _fb_flow = float(meta.get(f'stats_Net_TotalFlow{_pfx.capitalize()}Veh', 0) or 0)
                    out[f"aimsun_flow_{_pfx}"]    = _fb_flow if _fb_flow > 0 else 0.0
                    out[f"aimsun_density_{_pfx}"] = 0.0
                    out[f"aimsun_speed_{_pfx}"]   = 0.0
                    out[f"aimsun_delay_{_pfx}"]   = 0.0

    except Exception as e:
        out["aimsun_error"] = str(e)

    # Also try reading aggregate network stats from the active experiment
    try:
        model = GKSystem.getSystem().getActiveModel()
        if model is not None:
            for attr in ("getFlow", "getMeanTravelTime", "getMeanDelay"):
                fn = getattr(model, attr, None)
                if fn:
                    try:
                        v = fn()
                        if v is not None and float(v) > 0:
                            out[f"aimsun_model_{attr[3:].lower()}"] = round(float(v), 3)
                    except Exception:
                        pass
    except Exception:
        pass

    return out


def _safe_stat_v2(section, stat_name: str) -> float:
    """
    Try multiple Aimsun API patterns to read a per-section aggregate statistic.
    Returns 0.0 if nothing works — callers must guard against all-zero results.

    Known working patterns (version-dependent):
      • getFlow() / getDensity() / getMeanSpeed() — zero-arg property methods
      • getDataValueString(col_id, rep, interval, vehtype) — Aimsun 25+
      • Direct attribute access (rarely used but included as fallback)
    """
    # Map stat name → common zero-arg method names and attribute names
    _method_map = {
        "flow":    ("getFlow",     "flow"),
        "density": ("getDensity",  "density"),
        "speed":   ("getMeanSpeed","speed",   "getMeanTravelSpeed"),
        "delay":   ("getMeanDelay","delay",   "getDelay"),
    }
    candidates = _method_map.get(stat_name, (stat_name,))

    for name in candidates:
        # Try as zero-arg method
        fn = getattr(section, name, None)
        if callable(fn):
            try:
                v = fn()
                if v is not None:
                    fv = float(v)
                    if fv >= 0:
                        return fv
            except Exception:
                pass
        # Try as attribute
        v = getattr(section, name, None)
        if v is not None:
            try:
                fv = float(v)
                if fv >= 0:
                    return fv
            except Exception:
                pass

    # Aimsun Next 25+ API: getDataValueString(column_type, replication, interval, vehtype)
    # Column type IDs differ by version; we try common ones
    _col_ids = {
        "flow":    [0x0001, 1],
        "density": [0x0002, 2],
        "speed":   [0x0004, 4],
        "delay":   [0x0020, 32],
    }
    for col_id in _col_ids.get(stat_name, []):
        for method_name in ("getDataValue", "getStatistic"):
            fn = getattr(section, method_name, None)
            if not callable(fn):
                continue
            for args in ((col_id, None, None, None), (col_id,), (col_id, None)):
                try:
                    v = fn(*args)
                    if v is not None:
                        fv = float(v)
                        if fv >= 0:
                            return fv
                except Exception:
                    pass

    return 0.0


def _safe_stat_v2_typed(section, stat_name: str, veh_type_name: str) -> float:
    """
    Like _safe_stat_v2 but attempts to read a per-vehicle-type statistic.
    veh_type_name: 'Car', 'Bus', 'Truck' (or lowercase)
    Returns 0.0 if unavailable.
    """
    # Try method variants: getCarFlow, getBusFlow, etc.
    vtn = veh_type_name.capitalize()
    stat_cap = stat_name.capitalize()
    for name in (f"get{vtn}{stat_cap}", f"get{vtn}Mean{stat_cap}", f"get{stat_cap}For{vtn}"):
        fn = getattr(section, name, None)
        if callable(fn):
            try:
                v = fn()
                if v is not None:
                    fv = float(v)
                    if fv >= 0:
                        return fv
            except Exception:
                pass
    return 0.0


# =============================================================================
# ── CORE OUTPUT CSV ────────────────────────────────────────────────────────────
# =============================================================================
# Writes a clean per-run + per-intersection CSV with only the core metrics and
# the key sweep parameters so results are directly comparable across runs.

def _per_intersection_rows(folder, global_row):
    """Return list of per-intersection dicts for the current run."""
    inter_csv = _os.path.join(folder, "simulation_results_per_intersection.csv")
    rows = []
    if not _os.path.isfile(inter_csv):
        return rows
    try:
        with open(inter_csv, 'r', newline='', encoding='utf-8') as f:
            all_rows = list(csv.DictReader(f))
    except Exception:
        return rows
    _scen = str(global_row.get("ScenarioID", "")).strip()
    _exp  = str(global_row.get("ExperimentID", "")).strip()
    _rep  = str(global_row.get("ReplicationID", "")).strip()
    if _scen and _exp and _rep:
        run_rows = [r for r in all_rows
                    if str(r.get("ScenarioID","")).strip()  == _scen
                    and str(r.get("ExperimentID","")).strip() == _exp
                    and str(r.get("ReplicationID","")).strip() == _rep]
    else:
        run_rows = all_rows
    return run_rows or []


def write_core_output(core_path, metrics, reward_overrides):
    """
    Append one row to core_output.csv with:
      - Run identity + key sweep parameters
      - Global totals: pax delay, bus delay, car delay, main/side delay,
        bus TT, car TT, buses serviced, cars serviced
      - Averages for the same metrics
      - Per-intersection rows (same fields, one per intersection)
    """
    _folder = metrics.get("stats_results_folder", "")
    if not _folder:
        return

    # ── Read global CSV for Scenario/Experiment/Replication IDs ────────────
    _global_csv = _os.path.join(_folder, "simulation_results.csv")
    _global_row = {}
    if _os.path.isfile(_global_csv):
        _global_row = _read_csv_first_row(_global_csv) or {}

    # ── Global totals from simulation_results.csv ──────────────────────────
    def _f(key, default=""):
        v = metrics.get(key)
        if v is None:
            return default
        try:
            return float(v)
        except (TypeError, ValueError):
            return v

    # ── Key sweep parameters from the experiment config ────────────────────
    _overrides = dict(reward_overrides or {})

    # Build one dict with all the core fields
    row = {
        # Run identity
        "experiment":     _f("run_experiment"),
        "strategy":       _f("run_strategy"),
        "coordinated":    _f("run_coordinated"),
        "seed":           _f("run_seed"),
        "demand_scalar":  _f("run_demand_scalar"),
        "elapsed_s":      _f("run_elapsed_s"),
        "success":        _f("run_success"),

        # Key sweep parameters (what varied in this run)
        "bus_predictor":           _f("run_bus_predictor"),
        "GLOBAL_REWARD_MODE":      _overrides.get("GLOBAL_REWARD_MODE", ""),
        "WOBJ_ALPHA":              _overrides.get("WOBJ_ALPHA", ""),
        "WOBJ_BETA":               _overrides.get("WOBJ_BETA", ""),
        "strategy_mode": (
            "MAMBA" if _overrides.get("MAMBA_ATSP_MODE")
            else "ZIG" if _overrides.get("DCTSP_ZIG_MODE")
            else "MDN" if _overrides.get("MDN_DELAY_MODE")
            else "HS_EXT" if _overrides.get("HS_EXT_MODE")
            else "META_TSP" if _overrides.get("META_TSP_MODE")
            else "BARGAIN_SPM" if _overrides.get("BARGAIN_SPM_MODE")
            else _f("run_strategy")
        ),
        "ZIG_BALANCE_FACTOR":       _overrides.get("ZIG_BALANCE_FACTOR", ""),
        "ZIG_DE_POP":               _overrides.get("ZIG_DE_POP", ""),
        "ZIG_DE_ITER":              _overrides.get("ZIG_DE_ITER", ""),
        "ZIG_DE_F":                 _overrides.get("ZIG_DE_F", ""),
        "ZIG_DE_CR":                _overrides.get("ZIG_DE_CR", ""),
        "ZIG_MIN_GAIN_S":           _overrides.get("ZIG_MIN_GAIN_S", ""),
        # Mamba-ATSP hyperparameters (Li et al. 2026)
        "MAMBA_ATTENTION_HEADS":    _overrides.get("MAMBA_ATTENTION_HEADS", ""),
        "MAMBA_HIDDEN_DIM":         _overrides.get("MAMBA_HIDDEN_DIM", ""),
        "MAMBA_SSM_SCAN_STRIDE":    _overrides.get("MAMBA_SSM_SCAN_STRIDE", ""),
        "MAMBA_DATA_FUSION_ALPHA":  _overrides.get("MAMBA_DATA_FUSION_ALPHA", ""),
        "MAMBA_ATTENTION_TEMP":     _overrides.get("MAMBA_ATTENTION_TEMP", ""),
        "NETWORK_FACTOR":           _overrides.get("NETWORK_FACTOR", ""),
        "MDN_DDT_POWER":            _overrides.get("MDN_DDT_POWER", ""),
        "MDN_N_COMPONENTS":         _overrides.get("MDN_N_COMPONENTS", ""),
        "HS_EXT_HMCR":              _overrides.get("HS_EXT_HMCR", ""),
        "HS_EXT_PAR":               _overrides.get("HS_EXT_PAR", ""),
        "META_MIN_BUS_DELAY_S":     _overrides.get("META_MIN_BUS_DELAY_S", ""),
        "META_MIN_THRESHOLD_PAX_S": _overrides.get("META_MIN_THRESHOLD_PAX_S", ""),
        "META_LATENESS_TAKEOVER_S": _overrides.get("META_LATENESS_TAKEOVER_S", ""),
        "META_HW_SENSITIVITY":      _overrides.get("META_HW_SENSITIVITY", ""),

        # ── Global core metrics (totals) ──────────────────────────────────
        "total_pass_delay_hrs":     _f("stats_TotalPassDelay_hrs"),
        "total_main_delay_hrs":     _f("stats_MainPassDelay_hrs"),
        "total_side_delay_hrs":     _f("stats_SidePassDelay_hrs"),
        "total_bus_tt_hrs":         _f("stats_BusTotalTT_hrs"),
        "total_car_tt_hrs":         _f("stats_Net_TotalTT_h_Car"),
        "total_truck_tt_hrs":       _f("stats_Net_TotalTT_h_Truck"),
        "total_all_tt_hrs":         _f("stats_Net_TotalTT_h_All"),
        "total_bus_trips":          _f("stats_N_BusTrips"),
        "total_distinct_buses":     _f("stats_N_DistinctBuses"),
        "total_distinct_cars":      _f("stats_N_DistinctCars"),
        "total_distinct_trucks":    _f("stats_N_DistinctTrucks"),
        "total_bus_veh_passages":   _f("stats_BusVehPassages"),
        "total_car_veh_passages":   _f("stats_CarVehPassages"),
        "total_truck_veh_passages": _f("stats_TruckVehPassages"),
        "total_dist_all_km":        _f("stats_Net_TotalDist_All"),
        "total_exit_count_all":     _f("stats_Net_ExitCount_All"),
        # TSP events
        "total_tsp_detections":     _f("stats_TSP_Detections"),
        "total_tsp_extensions":     _f("stats_TSP_Extensions"),
        "total_tsp_insertions":     _f("stats_TSP_Insertions"),

        # ── Aimsun classical outputs: entry/exit delay, density, flow, speed ──
        # Network-level per-type
        "net_flow_car":             _f("stats_Net_Flow_Car"),
        "net_flow_bus":             _f("stats_Net_Flow_Bus"),
        "net_flow_truck":           _f("stats_Net_Flow_Truck"),
        "net_density_car":          _f("stats_Net_Density_Car"),
        "net_density_bus":          _f("stats_Net_Density_Bus"),
        "net_density_truck":        _f("stats_Net_Density_Truck"),
        "net_speed_car":            _f("stats_Net_Speed_Car"),
        "net_speed_bus":            _f("stats_Net_Speed_Bus"),
        "net_speed_truck":          _f("stats_Net_Speed_Truck"),
        "net_delay_car":            _f("stats_Net_Delay_Car"),
        "net_delay_bus":            _f("stats_Net_Delay_Bus"),
        "net_delay_truck":          _f("stats_Net_Delay_Truck"),
        # Entry / Exit delay by class
        "net_entry_delay_all":      _f("stats_Net_EntryDelay_All"),
        "net_exit_delay_all":       _f("stats_Net_ExitDelay_All"),
        "net_entry_delay_car":      _f("stats_Net_EntryDelay_Car"),
        "net_exit_delay_car":       _f("stats_Net_ExitDelay_Car"),
        "net_entry_delay_bus":      _f("stats_Net_EntryDelay_Bus"),
        "net_exit_delay_bus":       _f("stats_Net_ExitDelay_Bus"),
        "net_entry_delay_truck":    _f("stats_Net_EntryDelay_Truck"),
        "net_exit_delay_truck":     _f("stats_Net_ExitDelay_Truck"),
        # Queue metrics
        "net_mean_queue_all":       _f("stats_Net_MeanQueue_All"),
        "net_mean_queue_car":       _f("stats_Net_MeanQueue_Car"),
        "net_mean_queue_bus":       _f("stats_Net_MeanQueue_Bus"),
        "net_max_queue_all":        _f("stats_Net_MaxQueue_All"),
        "net_vq_avg_all":           _f("stats_Net_VQAvg_All"),
        # Distance / flow / count
        "net_total_dist_car":       _f("stats_Net_TotalDist_Car"),
        "net_total_dist_bus":       _f("stats_Net_TotalDist_Bus"),
        "net_input_flow_all":       _f("stats_Net_InputFlow_All"),
        "net_exit_flow_all":        _f("stats_Net_ExitFlow_All"),
        "net_exit_count_car":       _f("stats_Net_ExitCount_Car"),
        "net_exit_count_bus":       _f("stats_Net_ExitCount_Bus"),

        # ── Global averages ───────────────────────────────────────────────
        "avg_pass_delay_s":             _f("stats_AvgPassDelay_s"),
        "avg_bus_pass_delay_s":         _f("stats_AvgBusPassDelay_s"),
        "avg_car_pass_delay_s":         _f("stats_AvgCarPassDelay_s"),
        "avg_truck_pass_delay_s":       _f("stats_AvgTruckPassDelay_s"),
        "avg_bus_tt_s":                 _f("stats_AvgBusTT_s"),
        "avg_net_speed_kmh":            _f("stats_Net_AvgSpeed_kmh"),
        "avg_net_density_vkm":          _f("stats_Net_AvgDensity_vkm"),
        "net_total_flow_veh_h":         _f("stats_Net_TotalFlowVeh"),

        # ── Moving-bottleneck and density breakdown ───────────────────────
        "bus_headway_s":                _f("stats_BusHeadway_s"),
        "car_headway_s":                _f("stats_CarHeadway_s"),
        "total_mb_delay_hrs":           _f("stats_MovingBottleneckDelay_hrs"),
        "avg_queue_behind_bus_veh":     _f("stats_AvgQueueBehindBus_veh"),
        "total_cars_behind_bus":        _f("stats_TotalCarsBehindBus"),

        # ── Scope flag: "global" row ──────────────────────────────────────
        "scope": "global",
    }

    # ── Per-intersection rows ─────────────────────────────────────────────
    _inter_rows = _per_intersection_rows(_folder, _global_row)
    inter_cols = [
        "IntersectionID",
        "TotalPassDelay_hrs", "MainPassDelay_hrs", "SidePassDelay_hrs",
        "BusTotalTT_hrs", "N_BusTrips", "N_DistinctBuses",
        "N_DistinctCars", "N_DistinctTrucks",
        "BusVehPassages", "CarVehPassages", "TruckVehPassages",
        "AvgPassDelay_s", "AvgBusPassDelay_s", "AvgCarPassDelay_s",
        "AvgTruckPassDelay_s", "AvgBusTT_s",
        "AvgDensity_vkm", "AvgSpeed_kmh", "AvgFlow_veh_h", "AvgQueue_veh",
        "TSP_Detections", "TSP_Extensions", "TSP_Insertions",
        "TSP_Skipped_GE", "TSP_Skipped_Ins", "TSP_Detected_NoAction",
    ]
    _inter_dicts = []
    for _ir in _inter_rows:
        _id = {
            "experiment":     _f("run_experiment"),
            "strategy_mode":  row["strategy_mode"],
            "seed":           _f("run_seed"),
            "demand_scalar":  _f("run_demand_scalar"),
            "scope":          "intersection",
        }
        for _c in inter_cols:
            _id[_c] = _ir.get(_c, "")
        _inter_dicts.append(_id)

    # ── Write to CSV ──────────────────────────────────────────────────────
    # Two separate files: global stats (one row per run) and intersection
    # stats (one row per intersection per run).  Cleaner than a mixed CSV
    # with a "scope" column.

    # --- Global file ---
    _global_path = core_path.replace(".csv", "_global.csv")
    _global_keys = [k for k in row.keys() if k != "scope"]
    _write_global_hdr = not _os.path.isfile(_global_path)
    with open(_global_path, "a", newline="", encoding="utf-8") as _gf:
        _gw = csv.DictWriter(_gf, fieldnames=_global_keys, extrasaction='ignore')
        if _write_global_hdr:
            _gw.writeheader()
        _gw.writerow({k: v for k, v in row.items() if k != "scope"})

    # --- Intersection file ---
    _inter_path = core_path.replace(".csv", "_intersections.csv")
    _inter_keys = list(_inter_dicts[0].keys()) if _inter_dicts else []
    _write_inter_hdr = not _os.path.isfile(_inter_path)
    with open(_inter_path, "a", newline="", encoding="utf-8") as _if:
        _iw = csv.DictWriter(_if, fieldnames=_inter_keys, extrasaction='ignore')
        if _write_inter_hdr:
            _iw.writeheader()
        for _id in _inter_dicts:
            _iw.writerow(_id)

    log(f"  Core output: global → {_global_path}, intersections → {_inter_path} ({len(_inter_dicts)} rows)")


# ── MASTER RESULTS CSV ────────────────────────────────────────────────────────
# =============================================================================

def append_master_csv(master_path, row_dict):
    """
    Append one metrics row to the master batch_results.csv.
    Creates the file with headers on the first call.
    All keys in row_dict become columns; missing keys are blank.

    Column expansion: if a later run introduces keys not in the existing
    header, the entire file is rewritten with the union of all headers so
    no run's data is ever silently truncated by extrasaction='ignore'.
    """
    # Deterministic priority column order — appears left-to-right in the CSV.
    #
    # PRIMARY COMPARISON METRICS (density-robust):
    #   stats_AvgBusTT_s          — average bus travel time per trip (lower=better)
    #                               Independent of how many buses are in the network.
    #   stats_AvgBusPassDelay_s   — average delay per bus passenger (lower=better)
    #                               Normalised by passenger count so a run with fewer
    #                               passengers is not artificially rewarded.
    #   stats_Objective_PaxPerDelayHr — passengers moved per delay-hour (higher=better)
    #                               Productivity index: rewards moving more people
    #                               efficiently; not biased by network density.
    #   stats_Net_AvgSpeed_kmh    — length-weighted average network speed (higher=better)
    #
    # AVOID as primary: stats_SimTotalDelay_pax_s / stats_TotalPassDelay_hrs
    #   These sum all passenger-seconds of delay. Better TSP clears intersections
    #   faster → fewer vehicles in the network at any instant → lower total delay
    #   even if per-passenger service quality is unchanged or worse.
    priority_keys = [
        "run_experiment", "run_strategy", "run_coordinated",
        "run_seed", "run_demand_scalar", "run_elapsed_s", "run_success",
        # ── PRIMARY density-robust metrics ───────────────────────────────────
        "stats_AvgBusTT_s",          # avg bus trip travel time (s) — lower is better
        "stats_AvgBusPassDelay_s",   # avg delay per bus passenger (s) — lower is better
        "stats_Objective_PaxPerDelayHr",  # passengers / delay-hour — higher is better
        "stats_Net_AvgSpeed_kmh",    # network speed — higher is better
        "stats_AvgPassDelay_s",      # avg delay all passengers — secondary
        # ── Bus service quality ───────────────────────────────────────────────
        "stats_BusTotalTT_hrs",      "stats_N_BusTrips", "stats_N_DistinctBuses",
        # ── TSP action counts ─────────────────────────────────────────────────
        "stats_TSP_Detections",      "stats_TSP_Extensions", "stats_TSP_Insertions",
        "stats_TSP_Detected_NoAction", "stats_TSP_NaturalGreen",
        "stats_TSP_TotalExtension_s","stats_TSP_AvgExtension_s",
        # ── Global stats (from simulation_results.csv) ────────────────────────
        "stats_TSP_Strategy",
        "stats_TotalPassDelay_hrs", "stats_MainPassDelay_hrs", "stats_SidePassDelay_hrs",
        "stats_SimTotalDelay_pax_s", "stats_SimBusDelay_pax_s",
        "stats_SimCarDelay_pax_s",   "stats_SimTruckDelay_pax_s",
        "stats_PaxEquivPassages",    "stats_BusPaxEquivPassages",
        "stats_CarPaxEquivPassages", "stats_TruckPaxEquivPassages",
        "stats_AvgCarPassDelay_s",   "stats_AvgTruckPassDelay_s",
        "stats_N_BusTrips",          "stats_N_DistinctBuses",
        "stats_N_DistinctCars",      "stats_N_DistinctTrucks",
        "stats_TSP_Detections",      "stats_TSP_Extensions", "stats_TSP_Insertions",
        "stats_TSP_Skipped_GE",      "stats_TSP_Skipped_Ins",
        "stats_TSP_Detected_NoAction", "stats_TSP_NaturalGreen",
        "stats_Prearm_Fired",        "stats_Prearm_Success",
        "stats_Prearm_Missed",       "stats_Prearm_Expired",     "stats_Prearm_Discarded",
        "stats_Prearm_LateSuccess",  "stats_Prearm_LateSuccessDelay_s",
        "stats_TSP_TotalExtension_s","stats_TSP_TotalInsertion_s",
        "stats_TSP_AvgExtension_s",  "stats_TSP_AvgInsertion_s", "stats_TSP_AvgInsertionWait_s",
        "stats_Net_TotalFlowVeh",    "stats_Net_AvgDensity_vkm", "stats_Net_AvgSpeed_kmh",
        "stats_Net_Density_All",
        "stats_Net_Delay_All",        "stats_Net_Delay_Car",       "stats_Net_Delay_Bus",      "stats_Net_Delay_Truck",
        "stats_Net_EntryDelay_All",   "stats_Net_ExitDelay_All",
        "stats_Net_EntryDelay_Car",   "stats_Net_ExitDelay_Car",
        "stats_Net_EntryDelay_Bus",   "stats_Net_ExitDelay_Bus",
        "stats_Net_EntryDelay_HOV",   "stats_Net_ExitDelay_HOV",
        "stats_Net_EntryDelay_Truck", "stats_Net_ExitDelay_Truck",
        "stats_Net_Flow_HOV",         "stats_Net_Density_HOV",     "stats_Net_Speed_HOV",      "stats_Net_Delay_HOV",
        "stats_Objective_PaxPerDelayHr",
        # Per-intersection aggregates
        "inter_n",
        "inter_sum_TotalPassDelay_hrs",
        "inter_sum_BusTotalTT_hrs",
        "inter_sum_N_BusTrips",
        "inter_sum_CarVehPassages",
        "inter_sum_BusVehPassages",
        "inter_sum_PaxEquivPassages",
        "inter_avg_AvgBusTT_s",
        "inter_avg_AvgPassDelay_s",
        "inter_avg_AvgBusPassDelay_s",
        "inter_avg_AvgCarPassDelay_s",
        "inter_sum_TSP_Detections",
        "inter_sum_TSP_Extensions",
        "inter_sum_TSP_Insertions",
        "inter_sum_TSP_Skipped_GE",
        "inter_sum_TSP_Skipped_Ins",
        "inter_sum_TSP_Detected_NoAction",
        "inter_sum_TSP_NaturalGreen",
        # Aimsun network-level stats (from PyANGKernel post-run)
        "aimsun_n_sections",
        "aimsun_total_flow_veh",
        "aimsun_avg_density_vkm",
        "aimsun_avg_speed_kmh",
        "aimsun_total_delay_s",
        # Results folder path (for per-intersection CSV loading in dashboard)
        "stats_results_folder",
    ]
    priority_set = set(priority_keys)

    try:
        file_exists = _os.path.isfile(master_path)

        # ── Read existing header (if any) ─────────────────────────────────────
        existing_header = []
        existing_rows   = []
        if file_exists:
            try:
                with open(master_path, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    existing_header = list(reader.fieldnames or [])
                    existing_rows   = list(reader)
            except Exception:
                existing_header = []
                existing_rows   = []

        # ── Compute the union of all columns in deterministic order ───────────
        # priority_keys first, then any extras already in the file,
        # then any brand-new extras from the current row.
        existing_extra = [k for k in existing_header if k not in priority_set]
        new_extra      = [k for k in sorted(row_dict)
                          if k not in priority_set and k not in existing_header]
        # Deduplicate: existing_header may already have duplicate column names
        # (from a previous buggy run).  Once duplicates are in the file they
        # self-perpetuate through existing_extra.  Eliminate them here.
        _seen_keys: set = set()
        _dedup_keys: list = []
        for _k in priority_keys + existing_extra + new_extra:
            if _k not in _seen_keys:
                _seen_keys.add(_k)
                _dedup_keys.append(_k)
        all_keys = _dedup_keys

        # ── If header changed, rewrite the whole file ─────────────────────────
        if new_extra and existing_rows:
            log(f"  CSV: new columns found ({new_extra}) — rewriting batch_results.csv")
            with open(master_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(existing_rows)
            file_exists = True  # header already written

        # ── Append the new row ────────────────────────────────────────────────
        with open(master_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction='ignore')
            if not file_exists:
                writer.writeheader()
            writer.writerow(row_dict)

    except Exception as e:
        log(f"WARNING: could not write master CSV: {e}")


# =============================================================================
# ── MAIN ──────────────────────────────────────────────────────────────────────
# =============================================================================
def main():
    print("=" * 68)
    log("Batch runner starting (REV06)")

    try:
        PROJECT_DIR = get_project_dir()
    except RuntimeError as e:
        log("FATAL: " + str(e))
        return

    CONTROLLER_PATH = _os.path.join(PROJECT_DIR, "intersection_controller.py")
    RUN_CONFIG_PATH = _os.path.join(PROJECT_DIR, "run_config.py")
    MASTER_CSV_PATH   = _os.path.join(PROJECT_DIR, "batch_results.csv")
    CORE_OUTPUT_PATH  = _os.path.join(PROJECT_DIR, "core_output.csv")
    MANIFEST_PATH     = _os.path.join(PROJECT_DIR, "batch_manifest.json")
    PPTX_PATH         = _os.path.join(PROJECT_DIR, "BCC_progress_meeting_16Jun_update.pptx")

    if not _os.path.isfile(CONTROLLER_PATH):
        log(f"FATAL: controller not found at {CONTROLLER_PATH}")
        return

    # Clean old logs/results so this batch run starts from a deterministic state.
    _clear_previous_outputs(PROJECT_DIR)

    # ── Create batch_results.csv early so waiting scripts don't timeout ─────
    # Write CSV header immediately with all core columns so gen_obj_dashboard.py can detect file exists.
    # append_master_csv() will add additional columns as runs complete.
    _early_header = [
        "run_experiment", "run_strategy", "run_coordinated", "run_seed", "run_demand_scalar",
        "stats_AvgBusTT_s", "stats_AvgBusPassDelay_s", "stats_Objective_PaxPerDelayHr",
        "stats_Net_AvgSpeed_kmh", "stats_AvgPassDelay_s", "wobj_Z1_total", "wobj_Z2_total",
        "wobj_Z3_total", "wobj_Z4_total"
    ]
    try:
        with open(MASTER_CSV_PATH, 'w', encoding='utf-8', newline='') as f:
            f.write(",".join(_early_header) + "\n")
        log(f"  Batch results file created: {MASTER_CSV_PATH}")
    except Exception as e:
        log(f"  WARNING: could not create batch_results.csv: {e}")

    n_total = len(EXPERIMENTS) * len(SEEDS) * len(DEMAND_SCALARS)
    log(f"Experiments : {[e['name'] for e in EXPERIMENTS]}")
    log(f"Seeds       : {SEEDS}")
    log(f"Scalars     : {DEMAND_SCALARS}")
    log(f"Total runs  : {n_total}")
    log(f"Master CSV     : {MASTER_CSV_PATH}")
    log(f"Core global    : {CORE_OUTPUT_PATH.replace('.csv','_global.csv')}")
    log(f"Core intersecs : {CORE_OUTPUT_PATH.replace('.csv','_intersections.csv')}")
    print("=" * 68)

    # ── Disable ALL logging in controller for the entire batch ────────────────
    try:
        _set_logging(CONTROLLER_PATH, enabled=False)
    except Exception as e:
        log(f"WARNING: could not disable controller logging: {e}")

    try:
        rep = get_first_replication()
    except RuntimeError as e:
        log("FATAL: " + str(e))
        return

    run_num      = 0
    failures     = []
    base_demands = {}
    manifest     = []

    for scalar in DEMAND_SCALARS:
        log(f"==== Demand scalar: {scalar}x ====")
        set_demand_scalar(scalar, base_demands)

        for exp in EXPERIMENTS:
            if not exp.get("enabled", True):
                log(f"-- Skipping disabled experiment: {exp['name']}")
                continue
            exp_name      = exp["name"]
            strategy      = exp["strategy"]
            coordinated   = exp.get("coordinated", True)
            coord_algo    = exp.get("coordination_algo", "KALMAN")
            bus_predictor = exp.get("bus_predictor", "KALMAN")
            active_int    = exp.get("active_intersections", None)
            reward_overrides = exp.get("reward_overrides", None)

            # Ensure offset ETA propagation uses queue-aware shockwave logic
            # for coordinated reward-based strategies.
            if coordinated and strategy in ("GLOBAL_REWARD", "REWARD_TSP", "DRL_DENSITY"):
                if str(coord_algo).upper() != "SHOCKWAVE":
                    log(f"[BATCH] forcing coordination_algo=SHOCKWAVE for {exp_name} (was {coord_algo})")
                coord_algo = "SHOCKWAVE"

            # ── Patch CONTROL_MODE ─────────────────────────────────────────
            try:
                set_control_mode(strategy, CONTROLLER_PATH, active_int)
            except Exception as e:
                log(f"FATAL: cannot patch strategy {strategy}: {e}")
                for seed in SEEDS:
                    failures.append({
                        "scalar": scalar, "experiment": exp_name,
                        "seed": seed, "error": str(e),
                    })
                continue

            # ── Patch COORDINATED_TSP ─────────────────────────────────────
            try:
                set_coordinated(CONTROLLER_PATH, coordinated)
            except Exception as e:
                log(f"WARNING: could not patch COORDINATED_TSP: {e}")

            try:
                set_coordination_algo(CONTROLLER_PATH, coord_algo)
            except Exception as e:
                log(f"WARNING: could not patch COORDINATION_ALGO: {e}")

            # ── Patch reward weights for reward-based strategies ───────────
            # GLOBAL_REWARD_MODE is a bool read by the controller from run_config;
            # strip it from overrides before passing numeric-only weights to the file.
            _global_reward_mode = bool(
                (reward_overrides or {}).get("GLOBAL_REWARD_MODE", False)
            )
            _numeric_overrides = {
                k: v for k, v in (reward_overrides or {}).items()
                if k != "GLOBAL_REWARD_MODE"
            }
            if strategy in ("GLOBAL_REWARD", "REWARD_TSP", "DRL_DENSITY"):
                # Side traffic delay weighted at 0.5 (half of main) as initial MP setup.
                _numeric_overrides.setdefault("REWARD_MAIN_SECTION_WEIGHT", 1.0)
                _numeric_overrides.setdefault("REWARD_SIDE_SECTION_WEIGHT", 0.50)
            if not _numeric_overrides:
                _numeric_overrides = None
            try:
                if strategy in ("REWARD_TSP", "DRL_DENSITY", "GLOBAL_REWARD"):
                    set_reward_weights(CONTROLLER_PATH, _numeric_overrides)
                else:
                    # Always restore defaults so settings don't leak between runs.
                    set_reward_weights(CONTROLLER_PATH, None)
            except Exception as e:
                log(f"WARNING: could not patch reward weights: {e}")

            # ── Resolve reward flags for run_config.py (primary per-run mechanism) ─
            # The controller module is cached across replications, so module-level
            # constants patched into the .py file are stale after the first run.
            # Writing the flags to run_config.py and reading them back in AAPIInit
            # is the reliable mechanism for all runs after the first.
            # Write ALL reward_overrides to run_config.py.  Explicit defaults
            # for every mode flag ensure a previous run's flag cannot persist
            # through the module cache when this key is absent from overrides.
            _run_reward_cfg = {
                "REWARD_INV_DELAY_MODE": False,
                "REWARD_V2X_MODE":       False,
                "REWARD_SELFORG_MODE":   False,
                "DCTSP_ZIG_MODE":        False,
                "MP_ECTM_MODE":          False,
                "BXT_MODE":              False,
                "BARGAIN_SPM_MODE":      False,  # reset so HSExt→META_TSP/MDN can't leak
                "HS_EXT_MODE":           False,  # reset so HSExt→META_TSP/MDN can't leak
                "META_TSP_MODE":         False,  # reset so META_TSP→MDN can't leak
                "MDN_DELAY_MODE":        False,
                "REWARD_MAIN_SECTION_WEIGHT": 1.0,
                "REWARD_SIDE_SECTION_WEIGHT": 0.50,  # initial: side traffic at half weight
                "WOBJ_ALPHA":            0.8,   # Z1 (weighted pax-delay) weight — reset so a
                "WOBJ_BETA":             0.2,   # sweep run's value can't leak into the next run
                "WOBJ_GAMMA":            0.0,   # Z3 (bus lateness) weight — reset for the same reason
                "INV_DELAY_EPSILON":     1.0,
                "INV_DELAY_CAR_WEIGHT":  2.0,
                "INV_DELAY_MIN_DELAY_S": 0.0,
                "V2X_MAX_BUS_OCC":       80.0,
                "V2X_CROWDING_SCALE":    10.0,
                "V2X_EPSILON":           1.0,
                "V2X_MIN_DELAY_S":       0.0,
                "V2X_BALANCE_FACTOR":    1.0,   # default: no blocking (V2X exp sets 0.50)
                "META_LATENESS_TAKEOVER_S": 9999.0,  # disabled by default
                "DETECTION_PROB":        1.0,   # default: perfect detection (DETECTION_SWEEP overrides)
                "BUS_OCC_OVERRIDE":      None,  # default: use junction-config BusOcc (OCC_SWEEP overrides)
                "CAR_OCC_OVERRIDE":      None,  # default: use junction-config CarOcc (OCC_SWEEP overrides)
                "REWARD_FUTURE_HORIZON_CYCLES": 1.0,   # default lookahead: 1 decision cycle (CYCLE_HORIZON_SWEEP overrides)
                "TSP_CYCLE_LENGTH_OVERRIDE_S":  10.0,  # default: recompute grant/no-action every 10s (CYCLE_HORIZON_SWEEP overrides)
            }
            # Overlay every key from reward_overrides (GLOBAL_REWARD_MODE stripped above).
            for _k, _v in (_numeric_overrides or {}).items():
                _run_reward_cfg[_k] = _v

            for seed in SEEDS:
                run_num += 1
                print("-" * 68)
                log(f"Run {run_num}/{n_total} | scalar={scalar} "
                    f"| experiment={exp_name} | strategy={strategy} "
                    f"| coordinated={coordinated} | algo={coord_algo} "
                    f"| predictor={bus_predictor} | seed={seed}"
                    f"| global_reward={_global_reward_mode}")

                set_seed(rep, seed)
                write_run_config(exp_name, strategy, seed, scalar,
                                 coordinated, coord_algo, RUN_CONFIG_PATH,
                                 global_reward_mode=_global_reward_mode,
                                 reward_cfg=_run_reward_cfg,
                                 bus_predictor=bus_predictor)

                # Purge .pyc so Aimsun re-reads the patched controller
                _purge_pyc(CONTROLLER_PATH)

                t0      = _time.time()
                success = True
                try:
                    run_replication(rep)
                    elapsed = int(_time.time() - t0)
                    log(f"Run {run_num}/{n_total} DONE in {elapsed}s")
                except Exception as e:
                    elapsed = int(_time.time() - t0)
                    log(f"Run {run_num}/{n_total} FAILED in {elapsed}s: {e}")
                    failures.append({
                        "scalar": scalar, "experiment": exp_name,
                        "seed": seed, "error": str(e),
                    })
                    success = False

                # ── Collect and save metrics ───────────────────────────────
                try:
                    metrics = collect_run_metrics(
                        PROJECT_DIR, strategy, seed, scalar,
                        exp_name, coordinated, elapsed, success,
                        bus_predictor=bus_predictor
                    )
                    append_master_csv(MASTER_CSV_PATH, metrics)
                    if success and metrics.get("stats_results_folder"):
                        try:
                            write_core_output(CORE_OUTPUT_PATH, metrics, reward_overrides)
                        except Exception as _coe:
                            log(f"WARNING: core_output write failed: {_coe}")
                except Exception as e:
                    log(f"WARNING: metrics collection failed: {e}")

                # ── Auto-regenerate bargain-game dashboard after every BARGAIN run ──
                if exp_name == "DCTSP_BARGAIN_SPM":
                    try:
                        import importlib.util as _ilu2
                        _dash_script = _os.path.join(PROJECT_DIR, "plot_bargain_dashboard.py")
                        if _os.path.isfile(_dash_script):
                            _spec2 = _ilu2.spec_from_file_location("plot_bargain_dashboard", _dash_script)
                            _dmod  = _ilu2.module_from_spec(_spec2)
                            _spec2.loader.exec_module(_dmod)
                            _dmod.main()
                            log("Bargain game dashboard regenerated -> bargain_game_dashboard.html")
                    except Exception as _e:
                        log(f"WARNING: bargain dashboard update failed: {_e}")

                # ── Auto-refresh PPT after every completed run ─────────────
                # ── Auto-refresh PPT + objective dashboard after every run ──────
                _pptx_out = _os.path.join(PROJECT_DIR, "BCC_progress_meeting_16Jun_update.pptx")
                _ppt_script = _os.path.join(PROJECT_DIR, "populate_sensitivity_slides.py")
                if _os.path.isfile(_pptx_out) and _os.path.isfile(_ppt_script):
                    try:
                        _ns = {}
                        with open(_ppt_script, 'r', encoding='utf-8') as _pf:
                            exec(compile(_pf.read(), _ppt_script, 'exec'), _ns)
                        _ns['populate_all'](MASTER_CSV_PATH, _pptx_out, quiet=True)
                    except: pass
                # Also regenerate objective dashboard
                _dash_script = _os.path.join(PROJECT_DIR, "gen_obj_dashboard.py")
                if _os.path.isfile(_dash_script):
                    try:
                        _ns2 = {}
                        with open(_dash_script, 'r', encoding='utf-8') as _df:
                            exec(compile(_df.read(), _dash_script, 'exec'), _ns2)
                    except: pass

                manifest.append({
                    "run":                  run_num,
                    "experiment":           exp_name,
                    "strategy":             strategy,
                    "coordinated":          coordinated,
                    "active_intersections": active_int,
                    "seed":                 seed,
                    "demand_scalar":        scalar,
                    "elapsed_s":            elapsed,
                    "success":              success,
                })

    print("=" * 68)
    log(f"Batch complete. {n_total - len(failures)}/{n_total} succeeded.")
    if failures:
        for f in failures:
            log(f"  FAILED: {f}")

    # ── Re-enable logging so interactive use works normally after batch ────────
    try:
        _set_logging(CONTROLLER_PATH, enabled=True)
        log("Controller logging restored to True.")
    except Exception as e:
        log(f"WARNING: could not re-enable controller logging: {e}")

    # ── Baseline comparison: flag experiments worse than NO_TSP ────────────────
    # Reads batch_results.csv, finds the NO_TSP baseline, and reports which
    # sweep experiments had HIGHER total passenger delay than the baseline.
    # Also writes a disabled-experiments snippet so you can paste it into
    # the "enabled": false list for the next batch run.
    _baseline_key = "stats_TotalPassDelay_hrs"
    try:
        _no_tsp_delay = None
        _all_rows = []
        if _os.path.isfile(MASTER_CSV_PATH):
            with open(MASTER_CSV_PATH, 'r', newline='', encoding='utf-8') as _bf:
                _all_rows = list(csv.DictReader(_bf))
        for _br in _all_rows:
            if str(_br.get("run_experiment","")).upper() == "NO_TSP":
                try:
                    _no_tsp_delay = float(_br.get(_baseline_key, 0) or 0)
                except Exception:
                    pass
                break
        if _no_tsp_delay is not None and _no_tsp_delay > 0:
            _worse = []
            for _br in _all_rows:
                _exp = str(_br.get("run_experiment",""))
                if _exp.upper() == "NO_TSP":
                    continue
                try:
                    _td = float(_br.get(_baseline_key, 0) or 0)
                except Exception:
                    _td = 0
                if _td > _no_tsp_delay:
                    _worse.append((_exp, round(_td, 3), round(_td - _no_tsp_delay, 3)))
            if _worse:
                log(f"BASELINE COMPARISON: NO_TSP TotalPassDelay = {_no_tsp_delay:.3f} hrs")
                log(f"  {len(_worse)} experiment(s) had HIGHER delay than NO_TSP:")
                for _wn, _wv, _wd in sorted(_worse, key=lambda x: -x[2]):
                    log(f"    {_wn:45s}  {_wv:.3f} hrs  (+{_wd:.3f} vs baseline)")
                # Write disable-snippet
                _disable_path = _os.path.join(PROJECT_DIR, "experiments_worse_than_NO_TSP.txt")
                with open(_disable_path, 'w') as _df:
                    _df.write("# Experiments with total passenger delay > NO_TSP baseline.\n")
                    _df.write(f"# NO_TSP baseline: {_no_tsp_delay:.3f} hrs\n")
                    _df.write("# Paste these into batch_runner.py EXPERIMENTS list with 'enabled': False\n\n")
                    for _wn, _wv, _wd in sorted(_worse, key=lambda x: -x[2]):
                        _df.write(f"#   {_wn:45s}  {_wv:.3f} hrs  (+{_wd:.3f})\n")
                log(f"  Disable list written to: {_disable_path}")
            else:
                log(f"BASELINE COMPARISON: all experiments <= NO_TSP ({_no_tsp_delay:.3f} hrs)")
        else:
            log("BASELINE COMPARISON: NO_TSP baseline not found in batch_results.csv")
    except Exception as _bce:
        log(f"WARNING: baseline comparison failed: {_bce}")

    # ── Save manifest ─────────────────────────────────────────────────────────
    try:
        with open(MANIFEST_PATH, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)
        log(f"Manifest written: {MANIFEST_PATH}")
    except Exception as e:
        log(f"WARNING: could not write manifest: {e}")

    log(f"Master metrics CSV : {MASTER_CSV_PATH}")
    log(f"Core global CSV     : {CORE_OUTPUT_PATH.replace('.csv','_global.csv')}")
    log(f"Core intersections CSV: {CORE_OUTPUT_PATH.replace('.csv','_intersections.csv')}")

    # ── Generate HTML comparison dashboard ────────────────────────────────────
    try:
        import importlib, sys as _sys
        if _SCRIPT_DIR not in _sys.path:
            _sys.path.insert(0, _SCRIPT_DIR)
        import generate_dashboard as _gd
        importlib.reload(_gd)
        _html = _gd.generate(
            batch_csv=MASTER_CSV_PATH,
            log_dir=_os.path.join(PROJECT_DIR, "logs"),
        )
        if _html:
            log(f"HTML dashboard: {_html}")
    except Exception as _dbe:
        log(f"WARNING: HTML dashboard generation failed: {_dbe}")

    # ── Generate reward breakdown dashboard ───────────────────────────────────
    # Reads reward_cycle_*.csv from logs/ and generates an HTML dashboard
    # showing per-strategy action selection, bus vs car cost breakdown, and
    # reward signal diagnostics.  Runs after every batch so the dashboard is
    # always up-to-date with the latest run.
    try:
        import importlib as _ilib
        if _SCRIPT_DIR not in _sys.path:
            _sys.path.insert(0, _SCRIPT_DIR)
        import plot_reward_breakdown as _prb
        _ilib.reload(_prb)
        _rb_html = _prb.generate(
            log_dir=_os.path.join(PROJECT_DIR, "logs"),
            out_html=_os.path.join(PROJECT_DIR, "reward_breakdown.html"),
        )
        if _rb_html:
            log(f"Reward breakdown dashboard: {_rb_html}")
    except Exception as _rbe:
        log(f"WARNING: Reward breakdown generation failed: {_rbe}")

    # ── Print seed-averaged summary table ─────────────────────────────────────
    try:
        import importlib.util as _ilu
        _summ = _os.path.join(PROJECT_DIR, "summarise_batch.py")
        if _os.path.isfile(_summ):
            _spec = _ilu.spec_from_file_location("summarise_batch", _summ)
            _smod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_smod)
            _smod.main()
    except Exception as _se:
        log(f"WARNING: summarise_batch failed: {_se}")

    # ── Render Quarto sensitivity report (DISABLED — crashes in Aimsun's embedded Python) ──
    # Auto-regenerates sensitivity_report.html from the fresh batch_results.csv.
    # Requires: quarto CLI on PATH, R with tidyverse/scales/gt/patchwork installed.
    # SKIPPED: subprocess.run crashes with UnicodeDecodeError in Aimsun's cp1252 console.
    _qmd_path = _os.path.join(PROJECT_DIR, "sensitivity_report.qmd")
    _QUARTO_ENABLED = False  # set True only when running outside Aimsun
    if _QUARTO_ENABLED and _os.path.isfile(_qmd_path):
        try:
            import subprocess as _sp
            # Find R binary to ensure it's on PATH for quarto's knitr engine
            _r_bin = _os.path.expandvars(
                r"%LOCALAPPDATA%\Programs\R\R-4.4.1\bin")
            if _os.path.isdir(_r_bin):
                _env = _os.environ.copy()
                _env["PATH"] = _r_bin + _os.pathsep + _env.get("PATH", "")
            else:
                _env = None
            _result = _sp.run(
                ["quarto", "render", _qmd_path, "--to", "revealjs"],
                cwd=PROJECT_DIR,
                env=_env,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if _result.returncode == 0:
                log("Quarto report rendered -> sensitivity_report.html")
            else:
                log(f"WARNING: quarto render failed (exit {_result.returncode})")
                if _result.stderr:
                    log(f"  stderr: {_result.stderr[:300]}")
        except FileNotFoundError:
            log("INFO: quarto CLI not found — install from https://quarto.org")
            log("  Then run: quarto render sensitivity_report.qmd --to revealjs")
        except Exception as _qe:
            log(f"WARNING: quarto render failed: {_qe}")

    # ── Populate PowerPoint progress deck ─────────────────────────────────────
    # Auto-populates slides 8-13 with fresh data from the batch run results.
    # Uses populate_sensitivity_slides.py which reads batch_results.csv and
    # writes to BCC_progress_meeting_todo.pptx (or a named output).
    try:
        _pptx_script = _os.path.join(PROJECT_DIR, "populate_sensitivity_slides.py")
        if _os.path.isfile(_pptx_script):
            import importlib.util as _ilu2
            _spec2 = _ilu2.spec_from_file_location("populate_sensitivity_slides",
                                                    _pptx_script)
            _smod2 = _ilu2.module_from_spec(_spec2)
            _spec2.loader.exec_module(_smod2)
            _pptx_out = _os.path.join(PROJECT_DIR, "BCC_progress_meeting_16Jun_update.pptx")
            if _os.path.isfile(_pptx_out):
                _smod2.populate_all(MASTER_CSV_PATH, _pptx_out)
                log(f"PowerPoint deck updated: {_pptx_out}")
            else:
                log("WARNING: BCC_progress_meeting_todo.pptx not found — PPT not updated")
        else:
            log("INFO: populate_sensitivity_slides.py not found — PPT not auto-updated")
    except Exception as _ppe:
        log(f"WARNING: PPT auto-generation failed: {_ppe}")

    print("=" * 68)


main()
