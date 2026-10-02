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

# Try to import AKIODDemandSetDemandODPair from the Aimsun API
try:
    from PyANGKernel import AKIODDemandSetDemandODPair
    _HAS_AKIOD_SET = True
except ImportError:
    _HAS_AKIOD_SET = False
    AKIODDemandSetDemandODPair = None

# Script directory — used for dashboard import
_SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))

# Module-level path constants derived from script location.
# These are accessed by batch_runner_wavegate.py when it imports this module,
# so they must be defined at module scope (not inside main()).
PROJECT_DIR     = _SCRIPT_DIR
CONTROLLER_PATH = _os.path.join(_SCRIPT_DIR, "intersection_controller.py")
RUN_CONFIG_PATH = _os.path.join(_SCRIPT_DIR, "run_config.py")

# ── Execute liveness / re-issue tuning ────────────────────────────────────────
# SET TO 3 s ON REQUEST (2026-10-01): re-issue almost immediately when no new sim
# log has appeared, rather than waiting out the measured init.
#
# READ THIS BEFORE TRUSTING IT. The re-issue fires every EXEC_REISSUE_SILENCE_S
# while `not started and not _new_log_files`. Nothing suppresses it until a sim
# log APPEARS -- and Aimsun's own replication init (network + demand + trip-gen)
# can run for minutes BEFORE the engine writes [LOAD]. So with a 3 s window and
# the old cap of 12, the runner can stack up to 12 executes in ~36 s, each of
# which is a FULL replication. That is 12 runs where you wanted 1, and it is the
# same stacking failure that produced the near-identical duplicate result folders
# (observed: CELLQ_LEARN_UNCOORD_CTM_seed300 at 15:24 and again at 15:34).
#
# Damage is therefore bounded by EXEC_MAX_RETRIES, now 1: at most ONE extra
# execute per replication. So the worst case is 2 runs instead of 1, and the best
# case (a genuinely dropped execute) recovers in 3 s instead of 300 s. If you want
# zero duplicates, set EXEC_MAX_RETRIES = 0 -- then a dropped execute is never
# recovered and the arm fails after the dead-man instead.
#
# WATCH [RESULT-DIR]: it logs every candidate folder for an arm/seed and marks
# -> PICKED. Two or more candidates means this window IS double-firing, and for a
# LEARNING arm the twins differ, so which one feeds the CSV starts to matter.
EXEC_REISSUE_SILENCE_S = 3.0
EXEC_MAX_RETRIES      = 1
# ── ADAPTIVE RE-ISSUE WINDOW (2026-10-01) ─────────────────────────────────────
# The 90 s above is only a FIRST-RUN FALLBACK. There is no defensible fixed value:
# a healthy init on this machine has been observed to exceed 180 s, and the engine
# grows between sessions, so any constant is either too short (re-fires into a
# healthy init -- the double-fire that doubles wall clock and result folders) or too
# long (a dropped execute wastes that much time). The runner already MEASURES each
# init (`[TIMING] init took Ns`); so use it. After the first replication the window
# becomes INIT_MULTIPLE x the longest init seen this session, floored at
# EXEC_REISSUE_SILENCE_MIN_S. Set _LAST_INIT_S[0] manually to prime it.
EXEC_REISSUE_SILENCE_MIN_S = 30.0
EXEC_INIT_MULTIPLE         = 2.0     # re-issue only well past a known-good init
_LAST_INIT_S = [0.0]                 # longest observed executeAction->[LOAD] (s)
# Aimsun is BUSY (trip generation / SRC / teardown) if its own CPU advanced by at
# least this many seconds inside the trailing window.
#
# ── 2026-10-01: CPU IS NOW DIAGNOSTIC ONLY, NOT A GATE ────────────────────────
# This signal CANNOT answer "was the execute dropped?", and tuning it is hopeless,
# for a structural reason: os.times() measures THE WHOLE PROCESS, and the runner
# runs IN-PROCESS with Aimsun. So the runner's own polling loop -- 2 Hz
# app.processEvents(), getSimulationStatus(), log globbing, _close_dialogs --
# contributes directly to the number we are trying to attribute to Aimsun.
# Observed: "CPU busy (4.25s CPU / 10s window, needs <1.00s to re-issue)" at 30s
# elapsed, i.e. 42% of a core sustained. Either that is a real init (in which case
# holding is correct but the signal is redundant with the new-log check), or it is
# loop overhead (in which case no threshold above it ever re-issues, and we are
# back to the 2026-09-13 failure where a swallowed execute was NEVER recovered).
# We cannot tell which from inside the process, so the re-issue decision now rests
# only on signals that are unambiguous about the SIMULATION:
#   * a new Aimsun_TSP_Log_*.txt with [LOAD]  -> it started
#   * >= 2 new log files                       -> Aimsun queued them, do not stack
#   * an Aimsun dialog                         -> busy
#   * silence past _reissue_window             -> re-issue
# Waiting too long costs bounded wall clock. Re-firing into a live init costs a
# duplicate simulation AND duplicate result folders -- worse. So we err long.
EXEC_CPU_BUSY_DELTA_S = 1.0
EXEC_CPU_WINDOW_S     = 10.0
# Absolute backstop: if NOTHING has appeared after this long, the start is stuck
# whatever the CPU says, so re-issue regardless of liveness. Without this a busy
# reading can stall the batch indefinitely, which is worse than the double-fire
# this whole guard exists to prevent.
EXEC_ABSOLUTE_START_DEADLINE_S = 300.0
# How long to wait before re-issuing WHEN AIMSUN IS DEMONSTRABLY BUSY (CPU above
# EXEC_CPU_BUSY_DELTA_S). Set to 3 s on request (2026-10-01), same as the idle
# window, so busy and idle behave alike. NOTE this INVERTS the earlier reasoning:
# a busy start is usually a HEALTHY init, so waiting longer was the safe choice,
# and 3 s will fire into a live init. Bounded by EXEC_MAX_RETRIES = 1.
EXEC_BUSY_START_WINDOW_S = 3.0

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
    # ── TEST ARM: continuous Nash bargaining (2026-09-24 changes) ─────────────
    # Exercises: (1) continuous NASH play (bargains on state every tick, no bus
    # needed) via NASH_BARGAIN_MODE + CONTINUOUS_MONITOR_MODE + NASH_CONTINUOUS_
    # MODE; (2) NASH_BUS_WEIGHT=0 = utilitarian (minimise TOTAL pax delay);
    # (3) the recoverability + progression gates (default on) fire on any acting
    # arm. Grep the run log after: ENGINE_BUILD=2026-09-24T14:00-nash-continuous,
    # "[NASH_BARGAIN] [monitor]", "[MONITOR]", "[RECOVER_GATE]", "[PROG_GATE]",
    # and "] error". Disable when done; delete to restore the original batch.
    {
        "name":              "NASH_CONT",
        "enabled":           True,
        "strategy":          "GLOBAL_REWARD",
        "coordinated":       True,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE":       True,
            "NASH_BARGAIN_MODE":        True,
            "CONTINUOUS_MONITOR_MODE":  True,
            "NASH_CONTINUOUS_MODE":     True,
            "NASH_BUS_WEIGHT":          0.0,    # utilitarian: min total pax delay
            "NASH_CROSS_WEIGHT":        1.0,
            "CONTINUOUS_MONITOR_MIN_GAIN_PAXS": 50.0,
            # structural gates left at their defaults (both ON) so this run also
            # confirms they engage; set False here to A/B them if desired.
        },
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
            "WOBJ_Z1_SCALE":         50000000.0,  # Heavily increased to reduce Z1 influence (now ~3% of weight)
            "WOBJ_Z2_SCALE":         7500.0,
            "WOBJ_Z3_SCALE":         12000.0,
            "WOBJ_Z4_SCALE":         50000.0,     # Vehicle-km throughput (maximize)
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
            "NETWORK_FACTOR":        1.0,
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
            "NETWORK_FACTOR":     1.0,
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
            "NETWORK_FACTOR":              1.0,
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
            "ZIG_PHASE_OVERLAP_S":    0.5,
            # Break-even gate: fire when bus pax saving >= car pax cost (ratio <= 1.0).
            # NETWORK_FACTOR removed — was an unprincipled amplifier. Use WOBJ weights
            # to vary objective priority instead (see batch_runner_wavegate.py).
            "ZIG_BALANCE_FACTOR":     1.0,
            "NETWORK_FACTOR":         1.0,
            "NETWORK_FACTOR_DENSITY_RAMP": False,
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
            # ── Analytic cost veto over the learned-Q decider ──
            "DECIDER_COST_VETO_RATIO": 1.0,   # veto learned action if cross_cost > benefit*ratio
            # ── Faster convergence: pool experience across all signals ──
            # Independent per-signal learners are sample-starved (each junction
            # learns from only its own buses). Sharing one Q-table across all
            # signals gives ~N_signals x more samples/(state,action) -> converges
            # in far fewer episodes. Trade-off: one shared policy, no per-junction
            # specialisation. Default OFF; flip True to test faster learning.
            "BXT_SHARE_Q_ACROSS_SIGNALS": False,   # tested: full sharing over-generalises → gridlock (§39)
            # Option 1: per-signal Q, but first-visit states warm-start from a
            # cross-signal pool (sample-efficiency without losing specialisation).
            "BXT_WARMSTART_FROM_SHARED":  True,
            # Log the shockwave-objective delay vs the reliable timing delay so we
            # can verify the harmony/shockwave predictions are sane.
            "BXT_DELAY_DIAG":             True,
            # ── Baked-in traditional-TSP rules (see run_config docs) ──
            "RULE_MIN_GREEN":                 True,
            "MIN_GREEN_S":                    5.0,
            "RULE_TSP_COOLDOWN":              True,
            "TSP_PER_BUS_COOLDOWN_S":         60.0,
            "RULE_PERSON_DELAY_WARRANT":      True,
            "PERSON_DELAY_WARRANT_MIN_PAXS":  0.0,   # 0 = inert; raise to filter near-empty buses
            "CONDITIONAL_PRIORITY_MIN_LATENESS_S": 0.0,  # 0 = inert; raise to serve only late buses
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
ZIG_SWEEP_NETWORK_FACTORS  = [1.0]   # NETWORK_FACTOR fixed at 1.0 — not a tuning param
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
                "NETWORK_FACTOR":             1.0,
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
            "ZIG_BALANCE_FACTOR":     1.0,   # break-even: fire when bus saving >= car cost
            "NETWORK_FACTOR":         1.0,   # no amplification — use raw measured cost
            "NETWORK_FACTOR_DENSITY_RAMP": False,
            # DE solver parameters (Storn & Price 1997, DE/rand/1/bin)
            "ZIG_DE_POP":             12,
            "ZIG_DE_ITER":            30,
            "ZIG_DE_F":               0.8,
            "ZIG_DE_CR":              0.9,
            "ZIG_MIN_GAIN_S":         0.0,
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
            "ZIG_BALANCE_FACTOR":     1.0,
            "NETWORK_FACTOR":         1.0,
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
                "NETWORK_FACTOR": 1.0},
     "ZIG_BALANCE_FACTOR", [0.75, 1.0, 1.25]),

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
        "ZIG_BALANCE_FACTOR":     1.0,
        "NETWORK_FACTOR":         1.0,
        "ZIG_MIN_GAIN_S":         0.0,
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

SEEDS           = [300, 42, 12345, 7, 99]   # 5 seeds for replication
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

# Full-horizon SimDuration on KG (h). Runs covering less than 90% of this are
# truncated (sim aborted early) and must not enter results as comparable rows.
EXPECTED_SIM_DURATION_HRS = 1.25

# KG FIX (2026-08-25): these were Logan Rd demand names and matched ZERO
# GKTrafficDemand objects here, so set_demand_scalar() silently scaled nothing
# (the entire Phase-3 factorial ran 6 identical demand levels overnight). None
# = match ALL traffic-demand matrices, which is correct for network-wide
# demand sweeps regardless of naming. (_is_scalable_matrix still restricts
# scaling to car/truck matrices, so PT stays untouched.)
TARGET_DEMAND_NAMES = None

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


_QUIET = False  # False = print progress/warnings. True once muted ALL runner
                # output, including the [SANITY] gate and zero-scale demand
                # warnings -- a 10-hour sweep must not fly blind.

_NOTE_SHOWN_KEYS = False  # set_reward_weights key-list NOTE prints once/session


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


def _veh_is_bus(vn):
    v = (vn or "").lower()
    return any(k in v for k in ("bus", "transit", "tram", "metro", " pt", "pt "))


def _veh_is_car_truck(vn):
    v = (vn or "").lower()
    return (any(k in v for k in CAR_KEYWORDS)
            or (SCALE_TRUCKS and any(k in v for k in TRUCK_KEYWORDS)))


def _active_demand_of_rep(rep):
    """The GKTrafficDemand the replication's experiment/scenario ACTUALLY uses
    (rep -> experiment -> scenario -> demand). None if it can't be resolved."""
    try:
        _exp = rep.getExperiment() if (rep is not None and hasattr(rep, 'getExperiment')) else None
        _scen = None
        for _m in ('getScenario', 'getScenarioObject'):
            try:
                if _exp is not None and hasattr(_exp, _m):
                    _scen = getattr(_exp, _m)()
                    if _scen is not None:
                        break
            except Exception:
                pass
        for _m in ('getDemand', 'getTrafficDemand'):
            try:
                if _scen is not None and hasattr(_scen, _m):
                    _d = getattr(_scen, _m)()
                    if _d is not None:
                        return _d
            except Exception:
                pass
    except Exception:
        pass
    return None


def set_demand_scalar(scalar, base_demands, rep=None):
    """Scale car (+optionally truck) demand by `scalar`; base_demands prevents
    compounding. When `rep` is given, scales the demand the ACTIVE experiment/
    scenario actually uses (rep->scenario->demand) -- KG has 18 GKTrafficDemand
    objects and the sim reads only ONE ('HOV profiled', id 11131396); scaling the
    others (Prior/updated) did nothing. Falls back to a catalog-wide scan when no
    rep or the active demand can't be resolved.

    HONESTY CONTRACT (2026-09-05 audit): every setFactor is READ BACK via
    getFactor() after the commander commit. Only read-back-verified items are
    counted. A factor that still reads its old value (e.g. stuck at 100) is a
    FAILURE, logged as such -- never as success. Returns n_verified.

    NOTE: on KG this schedule-factor path has never verified (read-back stays
    100). The authoritative demand mechanism is scale_od_matrices_multiply()
    below (console-side GKODMatrix.multiply + commit + assert). This function
    is kept for Phase-1 (scalar 1.0 no-op) and as a diagnostic, NOT for sweeps.

    EARLY SKIP at scalar==1.0 (2026-09-08): Phase 1 calls this every run at 1.0,
    where it wrote each factor to base*1.0 (unchanged) and STILL committed via
    getCommander().addCommand(None). On this Static-OD-Adjustment model a demand
    commit can make Aimsun re-process/re-adjust the OD before the next
    replication -- pure waste when the demand is not actually changing. At 1.0
    we do nothing (no setFactor, no commit), so the already-adjusted OD is left
    untouched between same-demand runs.
    """
    if abs(float(scalar) - 1.0) < 1e-9:
        try:
            log("Demand scalar 1x: no-op (skipped setFactor+commit -- "
                "demand unchanged, OD left as-is).")
        except Exception:
            pass
        return 0
    model = GKSystem.getSystem().getActiveModel()

    def _read_factor(sched_item):
        try:
            return float(sched_item.getFactor())
        except Exception:
            return None

    def _write_factor(sched_item, value):
        # Float first: the API expects a numeric factor. A string ("60.000000")
        # was silently ignored by at least one Aimsun build (read-back stayed
        # 100 with zero error raised) -- string is kept only as fallback.
        try:
            sched_item.setFactor(float(value))
            return
        except Exception:
            pass
        sched_item.setFactor("{:.6f}".format(float(value)))

    def _commit():
        try:
            model.getCommander().addCommand(None)
        except Exception as _ce:
            print(f"[RUNNER] WARN commit (getCommander().addCommand) failed: {_ce}")

    _TOL = 1e-2  # percentage-point tolerance on the % factor scale (100.0 = 1x)

    # ── PRIORITY: scale the ACTIVE demand the replication will read ──────────
    if rep is not None:
        _adem = _active_demand_of_rep(rep)
        if _adem is not None:
            try:
                _aid = _adem.getId()
            except Exception:
                _aid = '?'
            _pending = []  # (sched_item, expected_factor)
            for _si in (_adem.getSchedule() or []):
                _it = _si.getTrafficDemandItem()
                if _it is None:
                    continue
                try:
                    _vn = _it.getVehicle().getName() if _it.getVehicle() else ""
                except Exception:
                    _vn = ""
                if _veh_is_bus(_vn):
                    continue                 # never scale PT/bus demand
                _key = "ACTIVE::%s::%s" % (_aid, getattr(_it, 'getName', lambda: '?')())
                if _key not in base_demands:
                    _f0 = _read_factor(_si)
                    base_demands[_key] = _f0 if _f0 is not None else 100.0
                _pending.append((_si, base_demands[_key] * float(scalar)))
            for _si, _exp in _pending:
                try:
                    _write_factor(_si, _exp)
                except Exception as _e:
                    print(f"[RUNNER] WARN active setFactor failed: {_e}")
            _commit()
            _n_ok, _n_bad, _samples = 0, 0, []
            for _si, _exp in _pending:
                _got = _read_factor(_si)
                if _got is not None and abs(_got - _exp) <= _TOL:
                    _n_ok += 1
                else:
                    _n_bad += 1
                    if len(_samples) < 3:
                        _samples.append(f"exp={_exp:.3f} got={_got}")
            _msg = (f"Demand scalar {scalar:g}x: VERIFIED {_n_ok}/{len(_pending)} item(s) "
                    f"of the ACTIVE demand id={_aid} '{_adem.getName()}'")
            if _n_bad:
                _msg += (f" -- {_n_bad} FAILED read-back (stuck factors; "
                         f"e.g. {'; '.join(_samples)}). Schedule-factor scaling "
                         f"is NOT live; use scale_od_matrices_multiply().")
            print("[RUNNER] " + _msg)
            try:
                _dbg = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                     'logs', 'demand_scale_debug.txt')
                _os.makedirs(_os.path.dirname(_dbg), exist_ok=True)
                with open(_dbg, 'a', encoding='utf-8') as _dfh:
                    _dfh.write("ACTIVE-SCALED " + _msg + "\n")
            except Exception:
                pass
            return _n_ok
        print("[RUNNER] WARNING: could not resolve ACTIVE demand from rep -- "
              "falling back to catalog-wide scan (may miss the demand the sim uses).")

    demand_type = model.getType("GKTrafficDemand")
    objs = model.getCatalog().getObjectsByType(demand_type)
    if not objs:
        print("[RUNNER] WARNING: No GKTrafficDemand objects found -- demand cannot scale.")
        return 0
    demand_list = list(objs.values()) if isinstance(objs, dict) else list(objs)

    # Gather every schedule item once (matrix OR traffic state).
    items = []
    for demand in demand_list:
        if not _is_target_demand(demand):
            continue
        for sched_item in (demand.getSchedule() or []):
            item = sched_item.getTrafficDemandItem()
            if item is None:
                continue
            try:
                _vn = item.getVehicle().getName() if item.getVehicle() else ""
            except Exception:
                _vn = ""
            try:
                _tn = item.getTypeName()
            except Exception:
                _tn = type(item).__name__
            try:
                _nm = item.getName()
            except Exception:
                _nm = "?"
            items.append({"sched": sched_item, "name": _nm, "veh": _vn, "type": _tn})

    # Primary target: car (+truck). Fallback: everything that is NOT bus/PT, so a
    # naming mismatch still varies demand instead of producing identical runs.
    targets = [it for it in items if _veh_is_car_truck(it["veh"])]
    mode = "car-keyword"
    if not targets:
        targets = [it for it in items if not _veh_is_bus(it["veh"])]
        mode = "NON-BUS FALLBACK (car-keyword matched nothing)"

    n_scaled = 0
    _pending_fb = []  # (sched_item, key, expected_factor)
    for it in targets:
        key = it["name"]
        if key not in base_demands:
            _f0 = _read_factor(it["sched"])
            base_demands[key] = _f0 if _f0 is not None else 100.0    # Aimsun schedule factor is a % (default 100)
        new_factor = base_demands[key] * float(scalar)
        try:
            _write_factor(it["sched"], new_factor)
            _pending_fb.append((it["sched"], key, new_factor))
        except Exception as _e:
            print(f"[RUNNER] WARN setFactor failed for {key}: {_e}")

    # COMMIT the modification through the model commander. Per Aimsun's own
    # "change traffic demand factor" example script, setFactor() does NOT take
    # effect until the change is committed / the undo buffer is reset with
    # getCommander().addCommand(None). Omitting this is why GKTrafficDemand
    # factor changes appeared to "have no effect" and the demand sweep stayed flat.
    if _pending_fb:
        _commit()

    # READ-BACK verification: only factors that actually changed count.
    n_scaled = 0
    _n_bad_fb = 0
    for _sched, _key, _exp in _pending_fb:
        _got = _read_factor(_sched)
        if _got is not None and abs(_got - _exp) <= _TOL:
            n_scaled += 1
        else:
            _n_bad_fb += 1

    _sample = "; ".join(
        "%s[veh=%s,type=%s,f0=%.3f->%.3f]"
        % (it["name"], it["veh"] or "?", it["type"],
           base_demands.get(it["name"], 0.0), base_demands.get(it["name"], 0.0) * scalar)
        for it in targets[:6]) or "NONE"
    print(f"[RUNNER] Demand scalar {scalar:g}x: VERIFIED {n_scaled}/{len(_pending_fb)} item(s) via {mode}. "
          f"Sample: {_sample}")
    if _n_bad_fb:
        print(f"[RUNNER] WARNING: {_n_bad_fb} item(s) FAILED read-back verification "
              f"(factors did not change) -- schedule-factor scaling is NOT live; "
              f"use scale_od_matrices_multiply() for sweeps.")
    # Also write to a file so the scaling can be verified after the fact (the
    # console [RUNNER] line is easy to miss). One line appended per call.
    try:
        _dbg = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                             'logs', 'demand_scale_debug.txt')
        _os.makedirs(_os.path.dirname(_dbg), exist_ok=True)
        with open(_dbg, 'a', encoding='utf-8') as _dfh:
            _dfh.write(f"scalar={scalar:g} n_verified={n_scaled}/{len(_pending_fb)} "
                         f"n_failed={_n_bad_fb} mode={mode} "
                         f"n_demand_objs={len(demand_list)} n_items_seen={len(items)} "
                         f"| {_sample}\n")
    except Exception:
        pass
    if n_scaled == 0:
        _seen = ", ".join("%s[veh=%s,type=%s]" % (it["name"], it["veh"] or "?", it["type"])
                          for it in items[:12]) or "NONE"
        print(f"[RUNNER] WARNING: scaled 0 items -> demand will NOT vary across "
              f"scalars! CAR_KEYWORDS={CAR_KEYWORDS}. All demand items seen: {_seen}")
    return n_scaled


# =============================================================================
# ── CONSOLE-SIDE OD-MATRIX SCALING (authoritative demand mechanism) ──────────
# =============================================================================
# 2026-09-05 audit outcome: of the three demand-scaling paths in this bundle,
# ONLY in-console GKODMatrix.multiply() can move the demand the KG simulation
# reads:
#   * set_demand_scalar() schedule factors never verify (read-back stays 100);
#   * engine AKIODDemandSetDemandODPair scales 0 pairs in every run (vehicle
#     names unresolvable + AAPILoad fires before demand loads + the API is
#     restricted to AAPILoad so the per-replication AAPIInit call is a no-op).
# Hence: sweeps (Phase 3, demand tests) MUST use scale_od_matrices_multiply()
# below and NOTHING else. Do not combine it with set_demand_scalar() in the
# same sweep -- that would double-scale (scalar^2).
_OD_VERIFY_MATS = 3      # total this many target matrices for read-back
_OD_VERIFY_RTOL = 0.05   # aggregate-ratio tolerance (float rounding only)


def _od_target_matrices():
    """Yield (key, demand_name, sched_item, matrix) for scalable OD matrices.

    Only matrices exposing multiply() whose vehicle (item, else parent demand)
    matches car/truck keywords and NOT bus keywords. Unknown vehicle naming is
    SKIPPED (never silently scaled -- it could be PT) and reported, so a zero
    result tells you to extend CAR_KEYWORDS/TRUCK_KEYWORDS instead of scaling
    the wrong demand.
    """
    model = GKSystem.getSystem().getActiveModel()
    demand_type = model.getType("GKTrafficDemand")
    objs = model.getCatalog().getObjectsByType(demand_type)
    if not objs:
        return
    demands = list(objs.values()) if isinstance(objs, dict) else list(objs)
    _skipped_unknown = []

    def _vname_of(item, demand):
        for _src in (item, demand):
            try:
                _v = _src.getVehicle() if _src is not None else None
                _n = _v.getName() if _v is not None else ""
                if _n:
                    return str(_n)
            except Exception:
                pass
        return ""

    for demand in demands:
        if not _is_target_demand(demand):
            continue
        try:
            _dname = demand.getName()
        except Exception:
            _dname = "?"
        for sched_item in (demand.getSchedule() or []):
            try:
                item = sched_item.getTrafficDemandItem()
            except Exception:
                continue
            if item is None or not hasattr(item, "multiply"):
                continue  # traffic-state items etc. -- not OD matrices
            try:
                _iname = item.getName()
            except Exception:
                _iname = "?"
            _vn = _vname_of(item, demand)
            if _veh_is_bus(_vn):
                continue  # never scale PT/bus demand
            if not _veh_is_car_truck(_vn):
                _skipped_unknown.append(f"{_dname}::{_iname}[veh={_vn or '?'}]")
                continue
            try:
                _mid = item.getId()
            except Exception:
                _mid = _iname
            yield (f"{_dname}::{_iname}::id={_mid}", _dname, sched_item, item)
    if _skipped_unknown:
        print(f"[RUNNER] OD multiply: skipped {len(_skipped_unknown)} unknown-vehicle "
              f"matrices (not car/truck/bus): {'; '.join(_skipped_unknown[:6])}")


def _od_matrix_total(item):
    """Total trips in a GKODMatrix via getTotalTrips(). None if unreadable.

    Probbed 2026-09-05: this build's GKODMatrix has NO getNumOrigins/
    getDemand/getOriginId cell API -- only getTotalTrips/getTrips and the
    setTrips/multiply writers. calculateSummary() is requested defensively
    before reading so a stale cached summary cannot mask a multiply.
    """
    try:
        try:
            item.calculateSummary()
        except Exception:
            pass
        return float(item.getTotalTrips())
    except Exception:
        return None


def scale_od_matrices_multiply(scalar, state=None):
    """Scale car/truck OD demand to `scalar` via GKODMatrix.multiply().

    THE sweep mechanism. Call from the Aimsun console BEFORE fetching the
    replication for the run (rep caches demand at creation).

    Anti-compounding by construction: `state` (a caller-owned persistent dict,
    one per sweep) tracks the currently applied level; each call multiplies by
    the RATIO scalar/state["current"], so levels never stack. Start sweeps at
    1.0 on a pristine model; restore with scale_od_matrices_multiply(1.0, state).

    Commits via getCommander().addCommand(None), then READ-BACK ASSERTS the
    aggregate matrix total moved by the ratio (tolerance _OD_VERIFY_RTOL).
    Raises RuntimeError on hard failure (no multiply-capable matrices, empty
    demand, or verification mismatch) -- a loud abort beats a silent flat
    sweep. Returns the number of matrices multiplied.

    NOTE on integer cells: OD cells are integer trip counts, so multiply +
    restore can leave +/-1 trip/cell vs pristine. For bit-exact pristine
    state, reload the model.
    """
    if state is None:
        state = {}
    scalar = float(scalar)
    model = GKSystem.getSystem().getActiveModel()
    targets = list(_od_target_matrices())
    if not targets:
        raise RuntimeError(
            "scale_od_matrices_multiply: no multiply-capable car/truck OD matrices "
            "found. Check CAR_KEYWORDS/TRUCK_KEYWORDS against the demand-scale-debug "
            "output; refusing to run a sweep that cannot vary demand."
        )
    if "n_mats" in state and state["n_mats"] != len(targets):
        print(f"[RUNNER] WARNING: OD matrix count changed "
              f"({state['n_mats']} -> {len(targets)}); state may be stale.")
    state["n_mats"] = len(targets)

    prev = float(state.get("current", 1.0))
    ratio = scalar / prev if prev else scalar
    if abs(ratio - 1.0) < 1e-12:
        print(f"[RUNNER] OD multiply: already at {prev:g}x, no-op (target {scalar:g}x).")
        return len(targets)

    # Sampled read-back baseline: full totals of the first matrices with demand.
    _probe_keys, _probe_before = [], []
    for _key, _dn, _si, _m in targets:
        if len(_probe_keys) >= _OD_VERIFY_MATS:
            break
        _t = _od_matrix_total(_m)
        if _t is not None and _t > 0:
            _probe_keys.append(_key)
            _probe_before.append(_t)
    if not _probe_before:
        raise RuntimeError(
            "scale_od_matrices_multiply: all probed OD matrices total zero -- "
            "demand appears empty (or unreadable). Refusing to sweep."
        )
    _sum_before = sum(_probe_before)

    n_mult = 0
    for _key, _dn, _si, _m in targets:
        try:
            _m.multiply(float(ratio))
            try:
                _m.invalidateSummary()  # force getTotalTrips() to recompute
            except Exception:
                pass
            n_mult += 1
        except Exception as _e:
            print(f"[RUNNER] WARN multiply failed for {_key}: {_e}")
    try:
        model.getCommander().addCommand(None)
    except Exception as _ce:
        print(f"[RUNNER] WARN OD multiply commit failed: {_ce}")

    # READ-BACK ASSERT on the same probe matrices.
    _probe_after = []
    for _key, _dn, _si, _m in targets:
        if _key not in _probe_keys:
            continue
        _t = _od_matrix_total(_m)
        _probe_after.append(_t if _t is not None else 0.0)
    _sum_after = sum(_probe_after)
    _expect = _sum_before * ratio
    _den = abs(_expect) if abs(_expect) > 0 else 1.0
    _rel = abs(_sum_after - _expect) / _den
    print(f"[RUNNER] OD multiply {prev:g}x -> {scalar:g}x (ratio {ratio:.6f}): "
          f"{n_mult}/{len(targets)} matrices | probe total "
          f"{_sum_before:.1f} -> {_sum_after:.1f} (expected {_expect:.1f}, "
          f"rel err {_rel:.4f})")
    try:
        _dbg = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                             'logs', 'demand_scale_debug.txt')
        _os.makedirs(_os.path.dirname(_dbg), exist_ok=True)
        with open(_dbg, 'a', encoding='utf-8') as _dfh:
            _dfh.write(f"OD-MULTIPLY {prev:g}x->{scalar:g}x ratio={ratio:.6f} "
                        f"n={n_mult}/{len(targets)} probe={_sum_before:.1f}->"
                        f"{_sum_after:.1f} expect={_expect:.1f} relerr={_rel:.4f}\n")
    except Exception:
        pass
    if _rel > _OD_VERIFY_RTOL:
        raise RuntimeError(
            f"scale_od_matrices_multiply VERIFICATION FAILED: probe total moved "
            f"{_sum_before:.1f} -> {_sum_after:.1f}, expected {_expect:.1f} "
            f"(rel err {_rel:.3f} > {_OD_VERIFY_RTOL}). Demand did NOT scale -- "
            f"aborting rather than producing a flat sweep."
        )
    state["current"] = scalar
    return n_mult


def probe_vehicle_types():
    """Console diagnostic: identify vehicle-type positions (read-only).

    ALWAYS works from the console: the GKTrafficDemand catalog scan (vehicle
    names, multiply support) needs only the open model. The AKI half (type
    positions, OD slices, thesis cross-checks) needs the AAPI namespace, which
    exists only inside a running simulation's API context -- from a plain
    console those checks print as SKIPPED and run instead via the
    [ESTAD-PROBE] block in the TSP log on the next replication.
    """
    _api_errs = []
    try:
        from AAPI import (
            AKIVehGetNbVehTypes, AKIVehGetVehTypeName,
            AKIConvertToAsciiString, AKIODDemandGetNumSlicesOD,
            AKIODDemandGetDemandODPair, AKIInfNetNbCentroids,
            AKIInfNetGetCentroidId,
        )
        _api_src = "AAPI"
        _have_aki = True
    except ImportError as _e1:
        _api_errs.append(f"AAPI: {_e1}")
        try:
            # Pre-Next layouts exposed a subset via PyANGKernel; kept as fallback.
            from PyANGKernel import (
                AKIVehGetNbVehTypes, AKIVehGetVehTypeName,
                AKIConvertToAsciiString, AKIODDemandGetNumSlicesOD,
                AKIODDemandGetDemandODPair, AKIInfNetNbCentroids,
                AKIInfNetGetCentroidId,
            )
            _api_src = "PyANGKernel"
            _have_aki = True
        except ImportError as _e2:
            _api_errs.append(f"PyANGKernel: {_e2}")
            print("[RUNNER] probe: AKI namespace unavailable in this console ("
                  + " | ".join(_api_errs) + "). GK catalog scan below still "
                  "runs; AKI checks run in-sim via [ESTAD-PROBE].")
            _api_src = None
            _have_aki = False
    if _have_aki:
        print(f"[RUNNER] probe: AKI names resolved from {_api_src}")

    def _decode(_raw):
        if isinstance(_raw, str):
            return _raw, "str"
        for _flag in (True, False):
            try:
                _c = AKIConvertToAsciiString(_raw, _flag)
                if isinstance(_c, str):
                    return _c, f"ascii({_flag})"
            except Exception:
                pass
        return f"{_raw}", "UNDECODED"

    _rows = []
    _n, _cents = 0, []
    if _have_aki:
        try:
            _n = AKIVehGetNbVehTypes()
        except Exception as _e:
            print(f"[RUNNER] probe: AKIVehGetNbVehTypes failed: {_e}")
            _n = 0
        try:
            _cents = [AKIInfNetGetCentroidId(i) for i in range(AKIInfNetNbCentroids())]
        except Exception:
            _cents = []
        print(f"[RUNNER] probe: nb_veh_types={_n} n_centroids={len(_cents)}")
    for _pos in range(1, _n + 1):
        try:
            _name, _how = _decode(AKIVehGetVehTypeName(_pos))
        except Exception as _e:
            _name, _how = f"<error {_e}>", "error"
        try:
            _nslices = AKIODDemandGetNumSlicesOD(_pos)
        except Exception:
            _nslices = -1
        _has = False
        if _cents and _nslices and _nslices > 0:
            try:
                for _o in _cents[:8]:
                    for _d in _cents[:8]:
                        if _o == _d:
                            continue
                        if AKIODDemandGetDemandODPair(_o, _d, _pos, 0) > 0:
                            _has = True
                            break
                    if _has:
                        break
            except Exception:
                pass
        print(f"[RUNNER] probe: pos={_pos} name='{_name}' via={_how} "
              f"slices={_nslices} has_OD_demand={_has}")
        _rows.append({"pos": _pos, "name": _name, "via": _how,
                      "slices": _nslices, "has_demand": _has})
    # ── Thesis-era cross-checks (Aimsun 26 API validation) ──
    print("[RUNNER] probe: --- thesis cross-checks (v8 patterns vs this build) ---")
    if not _have_aki:
        print("[RUNNER] probe: SKIPPED in console (no AAPI namespace) -- covered "
              "in-sim by [ESTAD-PROBE]; see the TSP log after any replication.")
    else:
        try:
            import AAPI as _pk
            _ns_src = "AAPI"
            print(f"[RUNNER] probe: namespace checks against {_ns_src}")
            # 1. AKIConvertToAsciiString arity: the v8 SWIG wrapper took THREE args
            #    (string, deleteUshortString, anyNonAsciiChar); the engine calls it
            #    with two. If the 2-arg form throws here, that is why vehicle-type
            #    name resolution fails everywhere.
            try:
                _raw0 = _pk.AKIVehGetVehTypeName(1)
                for _args in ((_raw0, True), (_raw0, True, False)):
                    try:
                        _c = _pk.AKIConvertToAsciiString(*_args)
                        print(f"[RUNNER] probe: AsciiString{len(_args)}-arg -> "
                              f"{type(_c).__name__}: {str(_c)[:80]!r}")
                    except Exception as _e:
                        print(f"[RUNNER] probe: AsciiString{len(_args)}-arg ERR "
                              f"{type(_e).__name__}: {_e}")
            except Exception as _e:
                print(f"[RUNNER] probe: veh-name pointer read failed: {_e!r}")
            # 2. ANGConn object-id path for vehicle-type positions (thesis AAPIInit:
            #    ANGConnGetObjectId(AKIConvertFromAsciiString("car")) ->
            #    AKIVehGetVehTypeInternalPosition). A working alternative to
            #    SWIG-string decoding if the names resolve here.
            if hasattr(_pk, "ANGConnGetObjectId"):
                for _nm in ("car", "truck", "bus"):
                    try:
                        _oid = _pk.ANGConnGetObjectId(_pk.AKIConvertFromAsciiString(_nm), False)
                        _pos = _pk.AKIVehGetVehTypeInternalPosition(_oid)
                        print(f"[RUNNER] probe: ANGConn name={_nm!r} -> objId={_oid} internalPos={_pos}")
                    except Exception as _e:
                        print(f"[RUNNER] probe: ANGConn name={_nm!r} ERR {type(_e).__name__}: {_e}")
            else:
                print("[RUNNER] probe: ANGConnGetObjectId NOT present on this build")
            # 3. ANG section enumeration + misc thesis-time utilities.
            for _fn in ("AKIInfNetNbSectionsANG", "AKIInfNetGetSectionANGId",
                        "AKIInfNetGetSectionANGInf", "AKIGetTotalLengthSystem",
                        "AKIIsGatheringStatistics", "AKIEstGetIntervalStatistics"):
                print(f"[RUNNER] probe: {_fn} "
                      f"{'present' if hasattr(_pk, _fn) else 'NOT present'}")
        except ImportError as _e:
            print(f"[RUNNER] probe: AAPI namespace import failed ({_e})")
    try:
        _model = GKSystem.getSystem().getActiveModel()
        _dt = _model.getType("GKTrafficDemand")
        _objs = _model.getCatalog().getObjectsByType(_dt)
        _ds = list(_objs.values()) if isinstance(_objs, dict) else list(_objs or [])
        print(f"[RUNNER] probe: {len(_ds)} GKTrafficDemand objects; "
              f"schedule-item vehicles:")
        for _d in _ds:
            try:
                _dn = _d.getName()
            except Exception:
                _dn = "?"
            for _si in (_d.getSchedule() or []):
                try:
                    _it = _si.getTrafficDemandItem()
                    _vn = _it.getVehicle().getName() if _it and _it.getVehicle() else ""
                    _mn = _it.getName() if _it else "?"
                    _mult = hasattr(_it, "multiply")
                except Exception:
                    _vn, _mn, _mult = "?", "?", False
                print(f"[RUNNER] probe:   demand='{_dn}' item='{_mn}' "
                      f"veh='{_vn}' multiply={_mult}")
                break  # first schedule item per demand is enough for naming
    except Exception as _e:
        print(f"[RUNNER] probe: catalog scan failed: {_e}")
    return _rows


def set_od_demand_scalar(scalar, base_od_demands=None, rep=None):
    """
    DEPRECATED (2026-09-05): non-functional on this Aimsun build. A console
    probe showed GKODMatrix has NO getNumOrigins/getDemand/getOriginId cell
    API, so every cell read below throws and is swallowed by the bare
    excepts -- this always scales 0 pairs while looking busy. Use
    scale_od_matrices_multiply() instead. Kept only so legacy callers import.
    """
    print("[RUNNER] WARNING: set_od_demand_scalar is deprecated and scales "
          "nothing on this build (GKODMatrix has no cell API); use "
          "scale_od_matrices_multiply(). Returning 0.")
    return 0


def _set_od_demand_scalar_legacy(scalar, base_od_demands=None, rep=None):
    """
    Scale OD demand directly using AKIODDemandSetDemandODPair API.
    This modifies the internal OD matrices directly, bypassing the GKTrafficDemand
    schedule factor caching that causes demand sweep failures.
    
    Args:
        scalar: Demand multiplier (e.g., 0.6, 1.0, 1.6)
        base_od_demands: Dict to store original OD demands (prevents compounding)
        rep: Optional replication to target the active demand
    
    Returns:
        Number of OD pairs scaled
    """
    if not _HAS_AKIOD_SET:
        print("[RUNNER] WARNING: AKIODDemandSetDemandODPair not available in PyANGKernel")
        return 0
    
    model = GKSystem.getSystem().getActiveModel()
    
    # Get the active demand for the replication
    demand = None
    if rep is not None:
        try:
            _adem = _active_demand_of_rep(rep)
            if _adem is not None:
                demand = _adem
        except Exception:
            pass
    
    if demand is None:
        # Fallback: find a car demand
        demand_type = model.getType("GKTrafficDemand")
        objs = model.getCatalog().getObjectsByType(demand_type)
        if not objs:
            return 0
        for d in (objs.values() if isinstance(objs, dict) else objs):
            try:
                _vn = d.getVehicle().getName().lower() if d.getVehicle() else ""
                if "car" in _vn:
                    demand = d
                    break
            except Exception:
                pass
    
    if demand is None:
        return 0
    
    if base_od_demands is None:
        base_od_demands = {}
    
    n_scaled = 0
    
    # Iterate through schedules and OD matrices
    for sched_item in (demand.getSchedule() or []):
        matrix = sched_item.getTrafficDemandItem()
        if matrix is None:
            continue
        
        # Get OD pairs from the matrix
        try:
            num_origins = matrix.getNumOrigins()
            num_destinations = matrix.getNumDestinations()
            num_slices = matrix.getNumTimeSlices()
            num_vehicle_types = matrix.getNumVehicleTypes()
        except Exception:
            continue
        
        for origin_idx in range(num_origins):
            origin_id = matrix.getOriginId(origin_idx)
            for dest_idx in range(num_destinations):
                dest_id = matrix.getDestinationId(dest_idx)
                for slice_idx in range(num_slices):
                    for veh_type_pos in range(1, num_vehicle_types + 1):
                        try:
                            current_demand = matrix.getDemand(origin_idx, dest_idx, slice_idx, veh_type_pos)
                            if current_demand <= 0:
                                continue
                            
                            # Use a stable key for this OD pair
                            key = f"{origin_id}->{dest_id}::slice={slice_idx}::veh={veh_type_pos}"
                            
                            if key not in base_od_demands:
                                base_od_demands[key] = float(current_demand)
                            
                            new_demand = int(round(base_od_demands[key] * float(scalar)))
                            
                            # Use AKIODDemandSetDemandODPair to set the demand
                            # Parameters: origin, destination, vehTypePos, slice, new_demand
                            result = AKIODDemandSetDemandODPair(
                                origin_id, dest_id, veh_type_pos, slice_idx, new_demand
                            )
                            
                            if result >= 0:
                                n_scaled += 1
                        except Exception:
                            continue
    
    print(f"[RUNNER] OD demand scalar {scalar:g}x: scaled {n_scaled} OD pair(s)")
    return n_scaled
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
    """Delete any cached .pyc so Aimsun re-reads the patched .py next run.

    Also purges shared_tsp_engine/engine.py's own cache -- Aimsun's API script
    setting may point directly at that shared module (self-bootstrapping the
    active corridor's config) rather than at controller_path, and it can be
    edited independently of either corridor's intersection_controller.py.
    Simulation_Stats.py is purged too: it holds the global-KPI logic and is
    imported by both the controller and the engine, so a stale cache would
    silently resurrect old KPI behaviour after an edit.
    """
    for _base in (
        _os.path.splitext(controller_path)[0],
        _os.path.splitext(
            _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(controller_path))),
                          "shared_tsp_engine", "engine.py")
        )[0],
        _os.path.splitext(
            _os.path.join(_os.path.dirname(_os.path.abspath(controller_path)),
                          "Simulation_Stats.py")
        )[0],
        # every shared-engine module: partial reloads (new engine
        # + stale pt_inject) caused a live AttributeError 2026-08-25
        *glob.glob(_os.path.join(
            _os.path.dirname(_os.path.dirname(
                _os.path.abspath(controller_path))),
            "shared_tsp_engine", "__pycache__", "*.pyc")),
    ):
        py_dir  = _os.path.dirname(_base)
        py_name = _os.path.basename(_base)
        # __pycache__ is the normal location (Python 3)
        pycache = _os.path.join(py_dir, '__pycache__')
        for pyc in glob.glob(_os.path.join(pycache, py_name + '*.pyc')):
            try:
                _os.remove(pyc)
                log(f"Purged pyc cache: {pyc}")
            except Exception:
                pass
        # Legacy same-dir .pyc
        for pyc in glob.glob(_base + '*.pyc'):
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


def _strategy_to_mode(strategy):
    """Canonical strategy -> (CONTROL_MODE, GROUP_BASED_BUS_PRIORITY bool).

    Single source of truth shared by set_control_mode (controller-file patch,
    effective at load/GUI time) and write_run_config (run_config.py lines,
    effective per-replication via the engine's AAPIInit propagation). The two
    MUST agree: controller-file constants are read once at module load, so in
    a multi-arm batch session only the run_config path actually switches modes
    per run (proven 2026-09-09: 95 rows byte-identical per seed with every arm
    stuck on the load-time NORMAL mode).
    """
    if strategy == "GROUP_BASED_FIXED":
        return "GROUP_BASED", False
    if strategy in ("REWARD_TSP", "DRL_DENSITY", "HARMONY", "URTSP", "NORMAL",
                    "MILP_MPC"):
        # Explicitly keep phase-based / horizon-controller strategies out of any
        # group-based path (MILP_MPC is its own per-second CP-SAT controller, not
        # a group-based bus-priority plan).
        return strategy, False
    if strategy == "GLOBAL_REWARD":
        # GLOBAL_REWARD uses the DRL_DENSITY reward path; GLOBAL_REWARD_MODE flag
        # (written to run_config.py) switches the aggregation behaviour at runtime.
        return "DRL_DENSITY", False
    return strategy, True


def set_control_mode(strategy, controller_path, active_intersections=None):
    """
    Patch CONTROL_MODE, GROUP_BASED_BUS_PRIORITY, and TSP_ACTIVE_INTERSECTIONS.
    Verifies the patch was applied by re-reading the file after writing.
    """
    mode, _priority_bool = _strategy_to_mode(strategy)
    priority = "True" if _priority_bool else "False"

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
    # NOTE (2026-09-07 audit): keys here that NOTHING reads (not in the engine's
    # run_config propagation tuple, not in the controller file, not referenced
    # anywhere) were removed -- they were placebo knobs that silently did
    # nothing no matter what arms set: OFFSET_CORRECTION_MODE,
    # PHASE_SEQUENCE_MODE, REWARD_DENSITY, DCTSP_OC_THRESH_S,
    # DCTSP_OC_MAX_ADJ_S, OFFSET_CORRECTION_STALE_S. (Offset-correction and
    # phase-skip/rotation actions fire via ZIG_ENABLE_SEQ + PHASE_ROTATION_MODE,
    # which remain below.)
    bool_cfg = {
        "REWARD_INV_DELAY_MODE": False,
        "REWARD_V2X_MODE":       False,
        "REWARD_SELFORG_MODE":   False,
        "DCTSP_ZIG_MODE":        False,
        "MP_ECTM_MODE":          False,
        "MP_ECTM_DP_MODE":       False,
        "CELLQLEARN_DP_MODE":    False,
        "BXT_MODE":              False,
        "DCTSP_GREEN_REALLOC_MODE": False,
        "BARGAIN_SPM_MODE":      False,
        "HS_EXT_MODE":           False,
        "META_TSP_MODE":         False,
        "MDN_DELAY_MODE":        False,
        "PHASE_ROTATION_MODE":   False,
        # REWARD_TSP action-set toggles (live) — default True (both actions
        # available). GE = phase timing change (extend current bus-phase
        # green); INS = phase order change (bus phase runs ahead of turn).
        # batch_runner_signal_sequencing.py disables one at a time to isolate
        # timing-only vs order-only sweeps.
        "REWARD_TSP_ENABLE_GE":  True,
        "REWARD_TSP_ENABLE_INS": True,
    }
    # ── Float params (all default to neutral/baseline values) ──────────────────
    float_cfg = {
        "REWARD_ALPHA":            1.0,
        "REWARD_BETA":             1.0,
        "REWARD_GAMMA":            1.0,
        "REWARD_MAIN_SECTION_WEIGHT": 1.0,
        "REWARD_SIDE_SECTION_WEIGHT": 0.50,  # initial: side traffic at half main weight
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
        "PHASE_ROTATION_N_SEQS":     3.0,
        "PHASE_ROTATION_THRESHOLD_S": 5.0,
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
    # Keys absent from the controller file can't be patched into it -- but
    # they ARE delivered per-run via run_config.py + the engine's AAPIInit
    # propagation tuple (proven per-key by check_flag_consumers.py: all 66
    # remaining keys LIVE, 0 dead). Full list once per session, then silent.
    _unver = ([k for k, v in float_cfg.items() if f"{k} = {v}" not in verify]
              + [k for k, v in bool_cfg.items() if f"{k} = {repr(v)}" not in verify])
    if _unver:
        global _NOTE_SHOWN_KEYS
        if not _NOTE_SHOWN_KEYS:
            _NOTE_SHOWN_KEYS = True
            log(f"NOTE: {len(_unver)} keys have no top-level line in the controller "
                f"file (effective via run_config, not patched): " + ", ".join(_unver))
        # else: already listed once this session -- stay quiet

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
                     bus_predictor="KALMAN", results_csv_name="batch_results.csv",
                     active_intersections=None):
    _mode, _priority = _strategy_to_mode(strategy)
    # Record the per-run trip-cache key (seed + demand) for _setup_trip_cache.
    try:
        _TRIP_CACHE_STATE['seed'] = seed
        _TRIP_CACHE_STATE['scalar'] = float(scalar)
    except Exception:
        pass
    content = (
        "CURRENT_STRATEGY = "        + repr(strategy)           + "\n"
        "CURRENT_EXPERIMENT = "      + repr(experiment_name)    + "\n"
        "CURRENT_SEED = "            + repr(seed)               + "\n"
        "CURRENT_DEMAND_SCALAR = "   + repr(scalar)             + "\n"
        "CURRENT_COORDINATED = "     + repr(coordinated)        + "\n"
        "CURRENT_COORDINATION_ALGO = "+ repr(coordination_algo) + "\n"
        # ── Mode dispatch, per-replication ───────────────────────────────
        # Controller-file constants are read ONCE at module load, so in a
        # multi-arm session only these run_config lines actually switch modes
        # per run (engine AAPIInit propagation). Derived from the SAME helper
        # as set_control_mode so the two can never disagree.
        "CONTROL_MODE = "            + repr(_mode)              + "\n"
        "GROUP_BASED_BUS_PRIORITY = " + repr(bool(_priority))   + "\n"
        "TSP_ACTIVE_INTERSECTIONS = " + repr(active_intersections) + "\n"
        "COORDINATED_TSP = "         + repr(bool(coordinated))  + "\n"
        "COORDINATION_ALGO = "       + repr(coordination_algo)  + "\n"
        # Always emit (default True) so a False on one arm never carries over to
        # the next arm in a multi-arm session. When False the coordinator stays
        # live but suppresses the downstream pre-arm push (corridor coupling only).
        "COORD_PREARM_ENABLED = "    + repr(bool((reward_cfg or {}).get('COORD_PREARM_ENABLED', True))) + "\n"
        "BUS_PREDICTOR_TYPE = "      + repr(str(bus_predictor).upper()) + "\n"
        "GLOBAL_REWARD_MODE = "      + repr(bool(global_reward_mode)) + "\n"
        "BARGAIN_SPM_MODE = "        + repr(bool((reward_cfg or {}).get('BARGAIN_SPM_MODE', False))) + "\n"
        "DCTSP_GREEN_REALLOC_MODE = "+ repr(bool((reward_cfg or {}).get('DCTSP_GREEN_REALLOC_MODE', False))) + "\n"
        "GREEN_REALLOC_RECOVER_FRACTION = " + repr(float((reward_cfg or {}).get('GREEN_REALLOC_RECOVER_FRACTION', 1.0))) + "\n"
        # Which batch-results CSV this run's metrics are appended to (e.g.
        # batch_results.csv for the full batch_runner.py sweep, or
        # batch_results_gui.csv for a GUI/studio-driven run) -- AAPIFinish's
        # dashboard generation reads this so tsp_dashboard.html reflects the
        # run(s) that were actually just performed, not every historical
        # experiment ever accumulated in the main CSV.
        "RESULTS_CSV_NAME = "        + repr(str(results_csv_name)) + "\n"
        # Any caller of write_run_config is a batch sweep (GUI/single runs
        # never write run_config): skip per-run matplotlib plots there --
        # the CSVs carry the same numbers and the render costs tens of
        # seconds per run at high event counts.
        "SKIP_PER_RUN_PLOTS = True\n"
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
def set_junctions_external_control(junction_ids, replication=None):
    """
    Attempt to set the given junction IDs to External (API) control type in the
    active Aimsun model so the TSP controller can override their phases.

    PREREQUISITE: each junction must already have a signal plan (phases/signal
    groups) in the Aimsun model.  If a junction is a roundabout or give-way
    (no signal plan) this will log a warning and skip it — you must add a
    signal plan to that junction in the Aimsun scenario editor first.

    Call this once before the simulation loop starts (e.g. after
    get_first_replication() in the batch runner).  The change is written to the
    scenario so it persists across replications in the same session.

    Returns a dict: {junction_id: "ok" | "no_signal_plan" | "error:<msg>"}
    """
    model = GKSystem.getSystem().getActiveModel()
    if model is None:
        log("WARNING: set_junctions_external_control — no active model")
        return {}

    # Aimsun uses scenario-based control plans.  We need the active scenario's
    # master plan to change a node's control type.
    # Try GKNode → getControlJunction(scenario) → setControlType(2)
    node_type = model.getType("GKNode")
    if node_type is None:
        log("WARNING: GKNode type not found in model catalog")
        return {}

    results = {}
    for jid in junction_ids:
        try:
            # Find node by ID
            node = model.getCatalog().find(int(jid))
            if node is None:
                results[jid] = "error:node_not_found"
                log(f"[CTRL_TYPE] jct={jid}: node not found in model catalog")
                continue

            # Get the active master plan / control junction for this scenario
            ctrl_jct = None
            for getter in ("getControlJunction", "getSignalControl",
                           "getCurrentControlJunction"):
                fn = getattr(node, getter, None)
                if callable(fn):
                    try:
                        ctrl_jct = fn() if getter == "getControlJunction" \
                                   else fn(model.getActiveScenario() if hasattr(model, "getActiveScenario") else None)
                        if ctrl_jct is not None:
                            break
                    except Exception:
                        pass

            if ctrl_jct is None:
                # No control junction → no signal plan at all
                results[jid] = "no_signal_plan"
                log(f"[CTRL_TYPE] jct={jid}: no GKControlJunction — "
                    f"junction has no signal plan (roundabout/give-way). "
                    f"Add a signal plan in the Aimsun scenario editor first.")
                continue

            # Read current control type
            cur_type = None
            for getter in ("getControlType", "getSignalControlType", "getType"):
                fn = getattr(ctrl_jct, getter, None)
                if callable(fn):
                    try:
                        cur_type = fn()
                        break
                    except Exception:
                        pass

            if cur_type in (2, 3):
                results[jid] = "ok"
                log(f"[CTRL_TYPE] jct={jid}: already External (type={cur_type}) — no change needed")
                continue

            # Attempt to set to External (type 2 = external with phases)
            set_ok = False
            for setter in ("setControlType", "setSignalControlType"):
                fn = getattr(ctrl_jct, setter, None)
                if callable(fn):
                    try:
                        fn(2)
                        set_ok = True
                        break
                    except Exception as _e:
                        log(f"[CTRL_TYPE] jct={jid}: {setter}(2) failed: {_e}")

            if set_ok:
                results[jid] = "ok"
                log(f"[CTRL_TYPE] jct={jid}: control type set to External (2) "
                    f"(was {cur_type})")
            else:
                results[jid] = "error:setter_failed"
                log(f"[CTRL_TYPE] jct={jid}: could not set control type — "
                    f"set junction to External manually in Aimsun scenario editor")

        except Exception as ex:
            results[jid] = f"error:{ex}"
            log(f"[CTRL_TYPE] jct={jid}: unexpected error: {ex}")

    log(f"[CTRL_TYPE] Results: { {k: v for k, v in results.items()} }")
    return results


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
    _vals = list(reps.values()) if isinstance(reps, dict) else list(reps)

    def _rid(r):
        try: return int(r.getId())
        except Exception: return -1
    def _rname(r):
        try: return str(r.getName() or '')
        except Exception: return ''

    # ── Explicit override wins (set REPLICATION_ID or REPLICATION_NAME on this
    # module, e.g. _br.REPLICATION_NAME = "Replication 1 560 - TSP1"). Use it when
    # the model has several replications and you want a specific known-good one.
    _want_id = globals().get('REPLICATION_ID')
    _want_name = globals().get('REPLICATION_NAME')
    if _want_id is not None:
        for r in _vals:
            if _rid(r) == int(_want_id):
                log("get_first_replication -> OVERRIDE id=%s name=%r" % (_rid(r), _rname(r)))
                return r
        raise RuntimeError("REPLICATION_ID=%r not found among %d replications."
                           % (_want_id, len(_vals)))
    if _want_name:
        for r in _vals:
            if _rname(r) == str(_want_name):
                log("get_first_replication -> OVERRIDE name=%r id=%s" % (_rname(r), _rid(r)))
                return r
        raise RuntimeError("REPLICATION_NAME=%r not found among %d replications."
                           % (_want_name, len(_vals)))

    # ── Auto-pick. Only a real, EXECUTABLE child replication accepts "execute";
    # getObjectsByType also returns the experiment AVERAGE/result (executing it
    # raises "Action execute for object type GKReplication cannot be executed").
    # isAverage() does not exist in this Aimsun build, so the reliable test is
    # MEMBERSHIP in the experiment's child-replication list (the average is NOT in
    # it). Also skip synthetic auto-named entries ("Replication <id>"), which are
    # not the real seeded replications. (2026-10-02)
    def _child_ids(exp):
        out = set()
        for _getter in ('getReplications', 'getReplicationList'):
            try:
                _kids = getattr(exp, _getter)()
                for k in (_kids.values() if hasattr(_kids, 'values') else (_kids or [])):
                    out.add(_rid(k))
                if out:
                    return out
            except Exception:
                continue
        return out

    _exec = []
    for r in _vals:
        try:
            e = r.getExperiment()
            if e is None:
                continue
            _kids = _child_ids(e)
            # keep if it's a known child, or if the experiment exposes no child
            # list at all (then we cannot prove it's the average -> allow it).
            if _kids and _rid(r) not in _kids:
                continue
            _exec.append(r)
        except Exception:
            continue
    if not _exec:
        _exec = list(_vals)
    # prefer real seeded replications over synthetic "Replication <id>" ones, then
    # LOWEST id -- this reproduces the pick (id=11129240 'Replication 1 560') that
    # actually started a sim ("Simulation running...") in the 12:22 run. Use the
    # REPLICATION_NAME/ID override above to force a different one.
    _real = [r for r in _exec if _rname(r).strip() != ("Replication %d" % _rid(r))] or _exec
    try:
        _real = sorted(_real, key=_rid)
    except Exception:
        pass
    if not _real:
        raise RuntimeError(
            "No runnable GKReplication found in the open model. Set "
            "_br.REPLICATION_NAME to the replication you normally run, then re-run.")
    rep = _real[0]
    try:
        log("get_first_replication -> id=%s name=%r exp=%r "
            "(%d real, %d total; set _br.REPLICATION_NAME to override)" % (
                _rid(rep), _rname(rep),
                (rep.getExperiment().getName() if rep.getExperiment() else None),
                len(_real), len(_vals)))
    except Exception:
        pass
    return rep


# Optional explicit replication selection (see get_first_replication). Leave as
# None for auto-pick; set to force a specific replication, e.g.
#   REPLICATION_NAME = "Replication 1 560 - TSP1"
REPLICATION_ID = None
REPLICATION_NAME = None


def set_seed(rep, seed):
    try:
        rep.setRandomSeed(seed)
    except Exception:
        try:
            rep.getExperiment().setRandomSeed(seed)
        except Exception as e:
            log("WARNING: could not set seed: " + str(e))
    log("Seed -> " + str(seed))


# ── Per-seed trip caching ────────────────────────────────────────────────────
# Car/truck trips are (re)generated from the OD matrices every run (~100 s) and
# depend ONLY on (OD demand, seed) -- NOT on the TSP strategy. So the SAME seed
# produces the IDENTICAL vehicle set across every arm, and we regenerate it
# arms-1 times for nothing. Point the replication at a per-(seed,demand) trips
# file: the FIRST run of a key generates + writes it; later runs of that key
# READ it and skip regeneration. This is also a FAIRER comparison (every arm
# faces the exact same demand realisation for a seed). Keyed by demand scalar
# too, so a Phase-3 demand change cannot reuse a stale cache. Best-effort +
# self-probing: it logs the real trip API on the first run and degrades to
# normal (regenerate) on any build/method it can't drive. Set
# TRIP_CACHE_ENABLED=False to disable.
TRIP_CACHE_ENABLED = False   # disabled 2026-09-09 while restoring roll-over; re-enable after the API dump confirms the store/read toggle
_TRIP_CACHE_DIR = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), 'trip_cache')
_TRIP_CACHE_STATE = {'seed': None, 'scalar': 1.0}   # set by write_run_config
_TRIP_API_DUMPED = [False]


def _setup_trip_cache(rep):
    """Point `rep` at its per-(seed,demand) trips cache file and toggle
    read/write. Safe no-op if disabled, key unknown, or the API is absent."""
    if not TRIP_CACHE_ENABLED:
        return
    _seed = _TRIP_CACHE_STATE.get('seed')
    if _seed is None:
        return
    _scal = float(_TRIP_CACHE_STATE.get('scalar', 1.0) or 1.0)
    # One-time: dump the real trip API so the exact store/read mechanism for
    # this Aimsun build is visible in the log and can be finalised.
    if not _TRIP_API_DUMPED[0]:
        _TRIP_API_DUMPED[0] = True
        try:
            _rapi = sorted(m for m in dir(rep) if 'trip' in m.lower())
            log(f"  [TRIP-CACHE] replication trip-API: {_rapi}")
            _exp = rep.getExperiment()
            _eapi = sorted(m for m in dir(_exp) if 'trip' in m.lower())
            log(f"  [TRIP-CACHE] experiment trip-API: {_eapi}")
        except Exception as _e:
            log(f"  [TRIP-CACHE] API dump failed: {_e!r}")
    try:
        _os.makedirs(_TRIP_CACHE_DIR, exist_ok=True)
    except Exception:
        pass
    _path = _os.path.join(
        _TRIP_CACHE_DIR, f"trips_seed{int(_seed)}_x{_scal:.3f}.dpt")
    _exists = _os.path.isfile(_path)
    # 1. Point the replication at the per-key trips file (setter mirrors getter).
    _set_ok = False
    for _m in ("setDefaultTripsFilePath", "setTripsFilePath", "setTripsFile"):
        _fn = getattr(rep, _m, None)
        if callable(_fn):
            try:
                _fn(_path)
                _set_ok = True
                break
            except Exception:
                pass
    # 2. Enable READ on a cache hit, or WRITE/store on a miss, via known toggles.
    _mode = "read(hit)" if _exists else "write(miss)"
    _toggle = None
    _cands = (("setReadTrips", "setUseTripsFromFile", "setReadTripsFromFile",
               "setLoadTrips", "setUseTripsFile")
              if _exists else
              ("setStoreTrips", "setSaveTrips", "setKeepTrips", "setWriteTrips",
               "setGenerateTripsFile"))
    for _m in _cands:
        _fn = getattr(rep, _m, None)
        if callable(_fn):
            try:
                _fn(True)
                _toggle = _m
                break
            except Exception:
                pass
    log(f"  [TRIP-CACHE] seed={_seed} x{_scal:g} {_mode} "
        f"file={_os.path.basename(_path)} set_path={_set_ok} "
        f"toggle={_toggle or 'none-found (regenerates; API dump above)'}")


def _snapshot_dialog_hwnds():
    """Set of our-PID top-level #32770 dialog HWNDs right now (baseline).

    Anything NOT in this set that appears later unprompted mid-run is almost
    certainly a sim popup (finish/results/errors) rather than something the
    user opened deliberately -- those are the safe auto-close candidates.
    """
    found = set()
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        _cbtype = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                     wintypes.LPARAM)
        _mypid = _os.getpid()

        @_cbtype
        def _enum(hwnd, _):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                _pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(_pid))
                if int(_pid.value) != int(_mypid):
                    return True
                if user32.GetParent(hwnd):
                    return True
                _cls = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(hwnd, _cls, 64)
                if _cls.value == "#32770":
                    found.add(int(hwnd))
            except Exception:
                pass
            return True

        try:
            user32.EnumWindows(_enum, 0)
        except Exception:
            pass
    except Exception:
        pass
    return found


def _close_dialogs_win32(new_only_from=None):
    """Binding-free dismissal via Win32 API (no Qt bindings needed).

    Finds this process's OWN top-level windows whose titles look like sim
    result/finish dialogs and posts WM_CLOSE. Matching is restricted to our
    PID so other applications are never touched.

    When new_only_from (a set from _snapshot_dialog_hwnds) is given, ANY
    dialog-class window NOT in that set is closed regardless of title --
    these appeared unprompted mid-run. Titles are always logged first so no
    message is ever lost silently.
    """
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        _cbtype = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                     wintypes.LPARAM)
    except Exception:
        return 0
    closed = [0]
    _mypid = _os.getpid()
    _keywords = ('result', 'statistic', 'summary', 'finish', 'output',
                 'replication')
    _only_new = new_only_from is not None
    try:
        @_cbtype
        def _enum(hwnd, _):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                _pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(_pid))
                if int(_pid.value) != int(_mypid):
                    return True
                if user32.GetParent(hwnd):
                    return True  # top-level windows only
                _cls = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(hwnd, _cls, 64)
                _is_dlg = (_cls.value == "#32770")
                _length = user32.GetWindowTextLengthW(hwnd)
                _title = ""
                if 0 < _length <= 256:
                    _buf = ctypes.create_unicode_buffer(_length + 1)
                    user32.GetWindowTextW(hwnd, _buf, _length + 1)
                    _title = _buf.value or ""
                _match_kw = any(k in _title.lower() for k in _keywords)
                if _only_new:
                    if not _is_dlg or int(hwnd) in new_only_from:
                        return True
                    # New unprompted dialog: log its title (evidence preserved)
                    # then close regardless of title text.
                    try:
                        log(f"  auto-closing new dialog: '{_title}'")
                    except Exception:
                        pass
                elif not _match_kw:
                    return True
                user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                closed[0] += 1
            except Exception:
                pass
            return True
    except Exception:
        return 0
    try:
        user32.EnumWindows(_enum, 0)
    except Exception:
        pass
    if closed[0]:
        try:
            _time.sleep(0.5)
        except Exception:
            pass
    return closed[0]


def _qt_app():
    """QApplication instance on any Qt binding.

    Next 26 is Qt6 (PyQt5 does not exist there), so try PySide6 first, then
    the older bindings. Returns (app, qw_module) or (None, None).
    """
    import importlib
    for _mod in ("PySide6.QtWidgets", "PyQt5.QtWidgets", "PySide2.QtWidgets"):
        try:
            _qw = importlib.import_module(_mod)
            _app = _qw.QApplication.instance()
            if _app is not None:
                return _app, _qw
        except Exception:
            continue
    return None, None


def _close_dialogs(app=None, new_only_from=None):
    # app may be passed in (hot path) or resolved here; None = no Qt binding
    # available -> nothing we can do (this was the Next-26 hang: app was
    # ALWAYS None via the PyQt5-only import, so finish dialogs were never
    # dismissed and the next executeAction blocked forever).
    # new_only_from: set of HWNDs (from _snapshot_dialog_hwnds) to spare;
    # any OTHER dialog-class window is closed regardless of title.
    _qw = None
    if app is None:
        app, _qw = _qt_app()
    if app is None:
        return 0
    if _qw is None:
        try:
            import importlib
            _qw = importlib.import_module(app.__class__.__module__)
        except Exception:
            return 0
    try:
        _QDialog, _QPushButton = _qw.QDialog, _qw.QPushButton
    except Exception:
        return 0
    app.processEvents()
    closed = 0
    try:
        for w in app.topLevelWidgets():
            if not w.isVisible():
                continue
            title = w.windowTitle().lower()
            if not any(k in title for k in ('result', 'statistic', 'summary',
                                             'finish', 'output', 'replication')):
                continue
            clicked = False
            for btn in w.findChildren(_QPushButton):
                if any(t in btn.text().lower().replace('&', '')
                       for t in ('close', 'ok', 'cancel')):
                    btn.click()
                    clicked = True
                    closed += 1
                    break
            if not clicked and isinstance(w, _QDialog):
                w.reject()
                closed += 1
        app.processEvents()
    except Exception:
        pass
    # Binding-free backup: catches dialogs even when no Qt binding imports
    # (e.g. stripped embedded interpreters). Restricted to our own PID.
    try:
        closed += _close_dialogs_win32(new_only_from) or 0
    except Exception:
        pass
    return closed


_RUN_REPL_LAST_DONE = [0.0]   # wall-clock time the previous run finished


def run_replication(rep):
    _t_call = _time.time()
    # Between-run overhead: time from the PREVIOUS run finishing to this call
    # (metrics collection + controller patching + demand handling in the caller).
    if _RUN_REPL_LAST_DONE[0] > 0.0:
        log(f"  [TIMING] runner between-run overhead: "
            f"{_t_call - _RUN_REPL_LAST_DONE[0]:.0f}s "
            f"(prev run done -> this executeAction)")
    try:
        rep.setStorePaths(False)
    except Exception:
        pass
    try:
        rep.setOutputPathAssignment(None)
    except Exception:
        pass
    # Per-seed trip cache: reuse identical (seed,demand) vehicles across arms
    # instead of regenerating (~100 s) every run.
    try:
        _setup_trip_cache(rep)
    except Exception as _tce:
        log(f"  [TRIP-CACHE] setup skipped: {_tce!r}")
    app, _qw = _qt_app()

    # Snapshot open dialogs BEFORE execute: anything dialog-class appearing
    # afterwards arrived unprompted mid-run (e.g. the "simulation ended"
    # popup whose title is just "Aimsun Next") and is safe to auto-close.
    try:
        _dlg_snap = _snapshot_dialog_hwnds()
    except Exception:
        _dlg_snap = set()

    # Pre-execute dismissal: a finish/results dialog left over from the
    # PREVIOUS run is modal and blocks this executeAction. Single-shot close
    # (this is the version that rolled over 3-4 runs/session on 2026-09-09
    # morning; the drain-loop variant regressed to stalling after run 1).
    try:
        _n_closed = _close_dialogs(app) or 0
        if _n_closed:
            log(f"  dismissed {_n_closed} leftover dialog(s) before execute")
    except Exception:
        pass

    _t_exec = _time.time()   # [TIMING] executeAction issued
    # Capture the action result. Aimsun prints "Action execute for object type
    # GKReplication cannot be executed." and returns a FAILED result when the
    # replication is not individually runnable (e.g. a base/average rep in a Micro
    # SRC experiment). The old code discarded the return and then sat in the wait
    # loop for 1800 s re-issuing the same doomed execute -- the "stuck waiting for
    # start, log never updates" symptom. Detect refusal and fail fast. (2026-10-02)
    # Pre-execute diagnostics: the replication's current status + identity. A
    # status of 1 here BEFORE we execute means Aimsun still thinks it is running
    # (stuck from a prior sim) -- which is exactly when it answers execute with
    # "cannot be executed". (2026-10-02)
    try:
        _pre_status = rep.getSimulationStatus()
    except Exception:
        _pre_status = '?'
    try:
        log("  pre-execute: replication id=%s name=%r status=%r "
            "(status==1 => Aimsun thinks it is already running)" % (
                getattr(rep, 'getId', lambda: '?')(),
                getattr(rep, 'getName', lambda: '?')(), _pre_status))
    except Exception:
        pass
    _exec_res = GKSystem.getSystem().executeAction("execute", rep, [], "")
    # Log the raw return so we can see what Aimsun hands back (async executes
    # return a not-yet-"done" handle, which is NORMAL -- do NOT treat that as a
    # refusal or we abort a sim that is actually starting). Only an explicit False
    # is a hard refusal; everything else proceeds to the start-detection loop,
    # which has its own bounded no-start abort. (2026-10-02)
    try:
        log("  executeAction('execute') returned %r" % (_exec_res,))
    except Exception:
        pass
    if _exec_res is False:
        raise RuntimeError(
            "executeAction('execute') returned False for replication id=%s name=%r "
            "('Action execute for object type GKReplication cannot be executed'). "
            "Set _cs._br.REPLICATION_NAME to the replication you run with Play in "
            "the GUI, then re-run." % (
                getattr(rep, 'getId', lambda: '?')(),
                getattr(rep, 'getName', lambda: '?')()))
    _time.sleep(2.0)
    if app:
        app.processEvents()

    # ── Completion detection: a NEW result folder appears ────────────────
    # getSimulationStatus() does NOT reliably report "running" in this Aimsun
    # session (status==1 never observed), and executeAction is asynchronous,
    # so the old status+mtime marker never fired and EVERY arm hit the 900 s
    # dead-man and was recorded as a failure with blank stats (proven
    # 2026-09-07). SimulationStats writes each run to
    # <corridor>/results/<run>/simulation_results.csv at AAPIFinish, with a
    # UNIQUE per-run folder name -- so the reliable completion signal is a NEW
    # such folder appearing that was not present before this executeAction.
    # This is independent of status polling and mtime clock skew. NOTE the
    # results dir is where SimulationStats writes (its own module dir =
    # <corridor>/results), which is NOT necessarily PROJECT_DIR/results -- so
    # scan both.
    _res_bases = []
    for _cand in (
        (_os.path.join(PROJECT_DIR, 'results') if PROJECT_DIR else None),
        _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'results'),
    ):
        if _cand and _os.path.isdir(_cand) and _cand not in _res_bases:
            _res_bases.append(_cand)

    def _folders_with_results():
        _seen = set()
        for _b in _res_bases:
            try:
                for _d in _os.scandir(_b):
                    if _d.is_dir() and _os.path.isfile(
                            _os.path.join(_d.path, 'simulation_results.csv')):
                        _seen.add(_d.path)
            except Exception:
                pass
        return _seen

    _pre_folders = _folders_with_results()

    # Per-sim START/FINISH signal via the engine LOG MARKERS. The result
    # FOLDER is NOT per-sim -- SimulationStats caches _run_folder_ts and REUSES
    # one folder across sims in a session (proven 2026-09-07: 3 completed sims,
    # 1 folder), so "new folder" fails. But the engine writes an explicit
    # "[LOAD] AAPILoad complete" at each sim START and "[FINISH] stats saved OK"
    # at each sim FINISH, appended to the session log. Counting those markers
    # gives a robust per-sim signal that does NOT depend on getSimulationStatus,
    # folder names, or log-flush timing:
    #   * finish-count increased -> THIS sim finished  (completion)
    #   * start-count  increased -> a sim has STARTED   (alive; stop re-issuing)
    _logdir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'logs')

    def _log_marker_counts():
        try:
            _ls = glob.glob(_os.path.join(_logdir, 'Aimsun_TSP_Log_*.txt'))
            if not _ls:
                return (0, 0, 0)
            _n = max(_ls, key=_os.path.getmtime)
            with open(_n, 'r', encoding='utf-8', errors='replace') as _fh:
                _txt = _fh.read()
            return (_txt.count('AAPILoad complete'),
                    _txt.count('stats saved OK'),
                    _txt.count('[SIM_END]'))
        except Exception:
            return (0, 0, 0)

    # ── ENGINE-STAMP GUARD ────────────────────────────────────────────────────
    # Every [LOAD] AAPILoad complete line (ALL modes incl. NORMAL/NO_TSP) is
    # appended with "ENGINE_BUILD=<stamp>" by the bundle engine (engine.py). A
    # FOREIGN/stale shared_tsp_engine copy (repo-root, champion_bundle,
    # C:\AimsunPackages) predates the stamp -> its [LOAD] line has none. Running
    # an arm on a stale engine (old delay double-count, no per-run stats reset)
    # silently poisons the champion CSV and makes NO_TSP-vs-TSP invalid. So the
    # instant a sim's [LOAD] marker appears, verify that line carries the stamp
    # matching THIS bundle's engine.py; abort the batch otherwise.
    def _bundle_expected_build():
        try:
            _ep = _os.path.join(_os.path.dirname(_os.path.dirname(
                _os.path.abspath(__file__))), 'shared_tsp_engine', 'engine.py')
            with open(_ep, 'r', encoding='utf-8', errors='replace') as _fh:
                for _ln in _fh:
                    if _ln.lstrip().startswith('ENGINE_BUILD'):
                        _q = _ln.split('=', 1)[1].strip().strip('"').strip("'")
                        return _q or None
        except Exception:
            pass
        return None

    def _newest_load_line():
        """Return the most-recent '[LOAD] AAPILoad complete' line, or ''."""
        try:
            _ls = glob.glob(_os.path.join(_logdir, 'Aimsun_TSP_Log_*.txt'))
            if not _ls:
                return ''
            _n = max(_ls, key=_os.path.getmtime)
            with open(_n, 'r', encoding='utf-8', errors='replace') as _fh:
                _hit = ''
                for _ln in _fh:
                    if 'AAPILoad complete' in _ln:
                        _hit = _ln.rstrip('\n')
                return _hit
        except Exception:
            return ''

    _expected_build = _bundle_expected_build()

    def _assert_engine_stamp():
        """Raise if the sim that just started ran a stale/foreign engine."""
        _line = _newest_load_line()
        if 'ENGINE_BUILD=' not in _line:
            raise RuntimeError(
                "ENGINE-STAMP GUARD: the sim that just started has NO "
                "'ENGINE_BUILD=' on its [LOAD] line -> it loaded a STALE/FOREIGN "
                "shared_tsp_engine copy (old delay double-count, no per-run "
                "stats reset). Its stats would poison the champion CSV. Sync all "
                "engine copies to the bundle build and re-run. [LOAD] line was:\n"
                f"    {_line or '<no [LOAD] line found>'}")
        if _expected_build:
            _got = _line.split('ENGINE_BUILD=', 1)[1].strip()
            if _got != _expected_build:
                raise RuntimeError(
                    "ENGINE-STAMP GUARD: engine build MISMATCH -- the running "
                    f"engine stamped '{_got}' but this bundle's engine.py is "
                    f"'{_expected_build}'. The engine is imported ONCE per Aimsun "
                    "SESSION, so an engine edit is NOT live until you RESTART "
                    "AIMSUN (reopen the model). Restart Aimsun, then re-run.")

    _pre_starts, _pre_finishes, _pre_sim_ends = _log_marker_counts()
    # Snapshot the set of engine log FILES before this run. A NEW file appearing
    # (with [LOAD]/[FINISH]) is the per-sim start/finish signal that the count
    # baseline above misses (each per-sim log resets the count to 1). See the
    # robust detection block in the wait loop.
    try:
        _pre_logs = set(glob.glob(_os.path.join(_logdir, 'Aimsun_TSP_Log_*.txt')))
    except Exception:
        _pre_logs = set()

    waited  = 0.0
    started = False
    status_not_running_since = None
    _last_heartbeat = 0.0
    _last_check = -999.0
    _done = False
    _last_exec = 0.0
    _exec_retries = 0
    # ── Aimsun liveness tracking (anti-double-fire) ─────────────────────
    # os.times() measures THIS process = Aimsun itself (the runner is
    # in-process). A slow init (teardown + trip-gen + SRC: minutes) is BUSY,
    # not swallowed -- re-firing into it stacks full simulations (proven:
    # near-identical folder pairs for every arm-seed). Re-issue only after
    # EXEC_REISSUE_SILENCE_S of TOTAL silence: no LOAD, no dialogs, CPU idle.
    #
    # 2026-10-01: the window was hardcoded at 20 s, which was safe when a
    # healthy execute produced its [LOAD] marker in ~5 s. The engine has since
    # grown (engine.py 1.2 MB, specialized_modes.py 342 KB), so a healthy init
    # now overruns 20 s and the ORIGINAL execute gets fired at again while still
    # queued. Observed cost: "[TIMING] run_replication total 491s (sim ~22s)" --
    # two full inits, ~2x the wall clock, and the duplicate result folders. The
    # window is now a module constant so it can be tuned without editing the
    # loop, and defaults well clear of a healthy init.
    _init_s = None             # executeAction -> [LOAD] seconds, once known
    _cpu_samples = []          # (waited, proc_user+sys_s), trailing ~15 s
    _last_life = 0.0           # last waited with any sign of Aimsun life
    while waited < 1800.0:
        if app:
            app.processEvents()
        try:
            _pt = _os.times()
            _cpu_samples.append((waited, float(_pt[0]) + float(_pt[1])))
            while _cpu_samples and waited - _cpu_samples[0][0] > 15.0:
                _cpu_samples.pop(0)
        except Exception:
            pass
        # CPU-delta (2026-10-01): Aimsun burning CPU in the trailing window means it
        # is BUSY -- trip generation, SRC path calc, teardown -- not idle with a
        # dropped execute. It WIDENS the re-issue window (below) and does NOT latch
        # liveness. It must not touch _last_life: doing so made _alive permanently
        # true, so the advertised window never applied and only the absolute deadline
        # fired -- producing the self-contradictory log
        #   "quiet 210s of 90s ... will re-issue at 90s (attempt 0/12, 210s elapsed)"
        # i.e. a 90 s window it could never reach.
        _cpu_busy = False
        try:
            _win = [c for _t, c in _cpu_samples if waited - _t <= EXEC_CPU_WINDOW_S]
            if len(_win) >= 2 and (_win[-1] - _win[0]) >= EXEC_CPU_BUSY_DELTA_S:
                _cpu_busy = True
        except Exception:
            pass
        # A dialog since the execute is a sign of life (busy init / finishing teardown).
        # Only a DISCRETE, unambiguous event latches: a dialog closes for good, so
        # this window genuinely expires. CPU cannot be used this way.
        _alive = (waited - _last_life) < EXEC_REISSUE_SILENCE_S
        # Effective window: once a real init has been measured this session, sit
        # well clear of it; before that, fall back to the constant. When Aimsun is
        # demonstrably busy we wait the BUSY window instead of the idle one.
        try:
            _known = float(_LAST_INIT_S[0])
        except Exception:
            _known = 0.0
        _reissue_window = (max(EXEC_REISSUE_SILENCE_MIN_S,
                               EXEC_INIT_MULTIPLE * _known)
                           if _known > 0.0 else EXEC_REISSUE_SILENCE_S)
        if _cpu_busy:
            _reissue_window = max(_reissue_window, EXEC_BUSY_START_WINDOW_S)
        if _reissue_window > EXEC_ABSOLUTE_START_DEADLINE_S:
            _reissue_window = EXEC_ABSOLUTE_START_DEADLINE_S
        # EFFECTIVE window: the re-issue predicate ALSO demands the absolute
        # deadline when _alive (a dialog closed recently). Reporting
        # _reissue_window alone made the log disagree with the code whenever a
        # dialog was present -- it announced "will re-issue at 180s" while the
        # predicate actually required 300 s. Same class of message/predicate drift
        # as the CPU-latch bug; fixed by deriving the number from the SAME
        # condition the predicate uses.
        _eff_window = (_reissue_window if not _alive
                       else max(_reissue_window, EXEC_ABSOLUTE_START_DEADLINE_S))
        # Fast path: if status polling DOES work, use it.
        try:
            status = rep.getSimulationStatus()
        except Exception:
            status = -1
        # STALE-STATUS GUARD (2026-10-02): getSimulationStatus() can be stuck at 1
        # ("running") from the PREVIOUS sim on this same replication. If we trust it
        # as "started" we log "Simulation running..." for a sim that never began,
        # which disables the re-issue AND the no-start abort -> infinite hang (and
        # the stale "running" is also why Aimsun answers executeAction with "cannot
        # be executed"). Only trust status==1 once a NEW engine log / [LOAD] marker
        # since THIS execute confirms a fresh sim actually started.
        if not started and status == 1:
            try:
                _new_since = bool(set(glob.glob(_os.path.join(
                    _logdir, 'Aimsun_TSP_Log_*.txt'))) - _pre_logs)
            except Exception:
                _new_since = False
            _s_now, _, _ = _log_marker_counts()
            if _new_since or _s_now > _pre_starts:
                started = True
                _init_s = _time.time() - _t_exec
                log("Simulation running...")
        if started and status != 1:
            # Status says not running - start 5s grace timer, then assume done
            if status_not_running_since is None:
                status_not_running_since = waited
            elif waited - status_not_running_since >= 5.0:
                log(f"  completion: status != 1 for 5s (status={status}) -- assuming sim finished")
                _done = True
                break
        else:
            status_not_running_since = None
        # _log_marker + folder checks: every 0.5s after sim started, else 2s.
        _check_interval = 0.5 if started else 2.0
        if waited - _last_check >= _check_interval:
            _last_check = waited
            _starts, _finishes, _sim_ends = _log_marker_counts()
            # Completion (FASTEST): [SIM_END] marker = microscopic sim ended, AAPIFinish started
            if _sim_ends > _pre_sim_ends:
                log("  completion: [SIM_END] marker (microscopic sim ended)")
                _done = True
                break
            # Completion: the engine wrote a NEW "[FINISH] stats saved OK".
            if _finishes > _pre_finishes:
                log("  completion: engine [FINISH] marker (sim finished)")
                _done = True
                break
            # Backup completion: a NEW result folder WITH simulation_results.csv
            # (covers the case where SimulationStats does NOT reuse the folder).
            _new = _folders_with_results() - _pre_folders
            if _new:
                log("  completion: new result folder "
                    f"{sorted(_os.path.basename(x) for x in _new)}")
                _done = True
                break
            # ROBUST per-sim-log detection (set difference, not count baseline).
            # The engine writes a NEW timestamped Aimsun_TSP_Log_*.txt per sim,
            # each with exactly 1 [LOAD]/1 [FINISH]. The count-vs-baseline checks
            # below therefore NEVER trip (1 > 1 is false) once a previous log
            # exists -- both start AND finish were missed, so every run hit the
            # 30-min dead-man and was recorded run_success=False with blank stats
            # even though the sim finished fine (2026-09-13). Diffing the log-FILE
            # set is immune to that: a NEW log file with [FINISH] = this sim
            # finished; with [LOAD] = it has started.
            try:
                _cur_logs = set(glob.glob(_os.path.join(_logdir, 'Aimsun_TSP_Log_*.txt')))
                _new_logs = _cur_logs - _pre_logs
                _log_done = False
                for _nl in _new_logs:
                    try:
                        with open(_nl, 'r', encoding='utf-8', errors='replace') as _fh:
                            _nt = _fh.read()
                    except Exception:
                        continue
                    if not started and 'AAPILoad complete' in _nt:
                        started = True
                        _sim_started = True
                        _assert_engine_stamp()
                        _init_s = _time.time() - _t_exec
                        # remember the slowest healthy init seen this session so the
                        # re-issue window can exceed it (see _reissue_window below)
                        try:
                            if _init_s > _LAST_INIT_S[0]:
                                _LAST_INIT_S[0] = float(_init_s)
                        except Exception:
                            pass
                        log(f"  sim started (new sim log {_os.path.basename(_nl)} "
                            f"with [LOAD]) | [TIMING] init took "
                            f"{_init_s:.0f}s")
                    if ('stats saved OK' in _nt) or ('[SIM_END]' in _nt):
                        log(f"  completion: new sim log {_os.path.basename(_nl)} "
                            f"has [FINISH]")
                        _log_done = True
                        break
                if _log_done:
                    _done = True
                    break
            except Exception:
                pass
            # Has a sim STARTED? engine wrote a NEW "[LOAD] AAPILoad complete".
            _sim_started = _starts > _pre_starts
            if _sim_started and not started:
                started = True
                # GUARD: the sim just loaded the engine -- verify it is THIS
                # bundle's build before letting it run to completion + write the
                # CSV. Raises (aborts the batch) on a stale/foreign engine.
                _assert_engine_stamp()
                # [TIMING] executeAction -> sim start = Aimsun replication INIT
                # (network load + OD trip generation + SRC route/path calc).
                # This is the big pre-sim cost the stored-paths / fixed-OD model
                # settings target.
                log(f"  sim started (engine [LOAD] marker) | [TIMING] Aimsun "
                    f"replication init took {_time.time() - _t_exec:.0f}s "
                    f"(executeAction -> sim start)")
            # Keep the "Replication:" outputs dialog closed so the execute is
            # not swallowed. Any dialog produced since the execute is a sign
            # of life (busy init / finishing teardown), NOT a swallow.
            try:
                _ndlg = _close_dialogs(app) or 0
            except Exception:
                _ndlg = 0
            if _ndlg:
                _last_life = waited
            # (Removed 2026-09-13) The CPU-busy "liveness" hold measured
            # _os.times() = THIS process, but the runner's own 2 Hz
            # app.processEvents() + file-scan loop keeps the process above the 3%
            # threshold forever, so it ALWAYS read "busy" -> _last_life reset every
            # tick -> a SWALLOWED execute was NEVER re-issued (Aimsun genuinely
            # idle but reported "busy" for 450s+). Liveness now comes only from
            # real Aimsun DIALOGS (above) and the new-log-FILE signal (below).
            # Re-issue execute ONLY as a LAST RESORT, and only while NO sim has
            # started. EVIDENCE (2026-09-09 session log 134240): a HEALTHY execute produces its [LOAD] marker in
            # ~5 s; the slow gaps were a SWALLOWED execute recovered ONLY by the
            # old one-shot 300 s re-issue -- LOAD landed at ~335 s = 300 (threshold)
            # + ~35 s init, EXACTLY, proving the original was LOST (not queued) and
            # Aimsun was free long before 300 s. So a swallowed execute is a no-op
            # we can safely re-fire early: at 20 s we clear the ~5 s healthy start
            # with margin (never double-firing a healthy init) yet recover a
            # swallow ~15x faster than before. Re-issue every 20 s (not one shot),
            # up to EXEC_MAX_RETRIES times so it keeps trying until Aimsun accepts one; the
            # _sim_started gate stops the instant any [LOAD] appears. If a DOUBLE
            # [LOAD] is ever seen (starts jumps by 2), Aimsun is queuing not
            # dropping -- raise this back and prefer the idle-handshake instead.
            # LIVENESS (2026-09-12, retuned 2026-10-01): fire ONLY after
            # _reissue_window of silence (measured init x2, else the constant).
            # Slow inits are busy, not lost -- firing into them is what stacked
            # every arm-seed into near-identical folder pairs.
            # Reliable swallow signal: has a NEW engine log FILE appeared since
            # this run's execute? The sim writes its own timestamped
            # Aimsun_TSP_Log_*.txt when it starts -- none present => Aimsun dropped
            # the execute => re-fire. >=2 => Aimsun QUEUED them => halt (no stack).
            try:
                _new_log_files = set(glob.glob(_os.path.join(
                    _logdir, 'Aimsun_TSP_Log_*.txt'))) - _pre_logs
            except Exception:
                _new_log_files = set()
            if len(_new_log_files) >= 2 and not started:
                log(f"  {len(_new_log_files)} new sim logs since execute -- Aimsun "
                    f"queues executes; re-issue halted (no stacking)")
                _exec_retries = EXEC_MAX_RETRIES
            elif (not started and not _new_log_files
                    and (waited - _last_exec) >= _reissue_window
                    and _exec_retries < EXEC_MAX_RETRIES
                    and (not _alive
                         or (waited - _last_exec) >= EXEC_ABSOLUTE_START_DEADLINE_S)):
                try:
                    GKSystem.getSystem().executeAction("execute", rep, [], "")
                    _exec_retries += 1
                    _last_exec = waited
                    log(f"  execute swallowed (no new sim log after {waited:.0f}s"
                        f"{', CPU busy but past the %.0fs deadline' % EXEC_ABSOLUTE_START_DEADLINE_S if _cpu_busy else ''}"
                        f") -- re-issued (attempt {_exec_retries}/{EXEC_MAX_RETRIES})")
                except Exception as _ee:
                    log(f"  execute retry failed: {_ee!r}")
        # Early no-start abort: retries exhausted and still no [LOAD]/new sim log
        # after a grace window => Aimsun is REFUSING this replication, not just
        # slow. Fail fast with a pointer instead of sitting out the 1800s deadline
        # ("stuck waiting for start, log never updates"). (2026-10-02)
        if (not started and _exec_retries >= EXEC_MAX_RETRIES
                and (waited - _last_exec) >= max(_eff_window, EXEC_ABSOLUTE_START_DEADLINE_S)):
            raise RuntimeError(
                "run_replication: sim NEVER STARTED after %d execute attempts "
                "(%.0fs; no [LOAD] marker, no new sim log). Aimsun is refusing "
                "replication id=%s name=%r ('Action execute for object type "
                "GKReplication cannot be executed'). It is not individually "
                "runnable -- set  _cs._br.REPLICATION_NAME = \"<name>\"  (the "
                "replication you run with Play in the GUI) and re-run." % (
                    _exec_retries, waited,
                    getattr(rep, 'getId', lambda: '?')(),
                    getattr(rep, 'getName', lambda: '?')()))
        if waited - _last_heartbeat >= 30.0:
            _last_heartbeat = waited
            if started:
                log(f"  waiting for completion (engine [FINISH] marker)... "
                    f"({waited:.0f}s, running)")
            else:
                try:
                    _nlf = len(set(glob.glob(_os.path.join(
                        _logdir, 'Aimsun_TSP_Log_*.txt'))) - _pre_logs)
                except Exception:
                    _nlf = 0
                # Say WHY it is not re-issuing. "attempt 0/12" with no reason was
                # undiagnosable: a continuously-busy CPU reading and a mere quiet
                # wait produce the same line.
                try:
                    _wd = [c for _t, c in _cpu_samples
                           if waited - _t <= EXEC_CPU_WINDOW_S]
                    _cd = (_wd[-1] - _wd[0]) if len(_wd) >= 2 else 0.0
                except Exception:
                    _cd = 0.0
                # Say WHY the window is what it is. CPU widens it, a live dialog
                # forces the absolute deadline, and neither ever suppresses the
                # re-issue entirely -- name whichever applied.
                if _cpu_busy:
                    _cpunote = (' [cpu %.2fs/%.0fs -> BUSY, window widened to '
                                '%.0fs]' % (_cd, EXEC_CPU_WINDOW_S,
                                            EXEC_BUSY_START_WINDOW_S))
                elif _cd > 0:
                    _cpunote = ' [cpu %.2fs/%.0fs -> idle]' % (_cd, EXEC_CPU_WINDOW_S)
                else:
                    _cpunote = ''
                if _alive:
                    _cpunote += (' [dialog seen %.0fs ago -> waiting the %.0fs '
                                 'deadline]' % (waited - _last_life,
                                                EXEC_ABSOLUTE_START_DEADLINE_S))
                _why = ("quiet %.0fs of %.0fs%s, will re-issue at %.0fs"
                          % (waited - _last_exec, _eff_window,
                             (' (measured init %.0fs)' % _known)
                             if _known > 0.0 else
                             ' (no measured init yet, using fallback)',
                             _eff_window)) + _cpunote
                log(f"  waiting for sim to START -- no new sim log yet "
                    f"(new_logs={_nlf}); {_why} "
                    f"(attempt {_exec_retries}/{EXEC_MAX_RETRIES}, {waited:.0f}s elapsed)")
        _time.sleep(0.5)
        waited += 0.5

    if not _done:
        # 30 min with no new result folder: something is wrong, but do NOT
        # silently proceed (a still-running sim would be aborted by the next
        # executeAction). Surface it so the arm is recorded as a failure.
        raise RuntimeError(
            "run_replication: no new result folder appeared after "
            f"{waited:.0f}s -- the sim never completed (or SimulationStats "
            "did not write simulation_results.csv). Check Aimsun is responsive "
            "and no modal dialog is blocking, then re-run.")

    _time.sleep(2.0)
    if app:
        app.processEvents()
        _close_dialogs(app)
    # [TIMING] whole cycle + mark done so the NEXT call can report the gap.
    # Report the init/sim SPLIT honestly: `waited` is the completion-loop time and
    # it INCLUDES the replication init, because the loop starts the moment
    # executeAction is issued. Labelling all of `waited` as "sim" (as this line
    # used to) hid the fact that init is the dominant cost -- and init time is
    # exactly the number needed to size EXEC_BUSY_START_WINDOW_S, so mislabelling
    # it made that tuning impossible to do from the logs.
    _tot = _time.time() - _t_call
    if _init_s is not None:
        log(f"  [TIMING] run_replication total {_tot:.0f}s "
            f"(init {_init_s:.0f}s + sim {max(0.0, waited - _init_s):.0f}s "
            f"+ teardown {max(0.0, _tot - waited):.0f}s)")
        log(f"  [TIMING] SET EXEC_BUSY_START_WINDOW_S ~= {1.5 * _init_s:.0f}s "
            f"(1.5 x this init) if re-issues keep firing early")
    else:
        log(f"  [TIMING] run_replication total {_tot:.0f}s "
            f"(init UNKNOWN -- no [LOAD] marker seen; sim+teardown {waited:.0f}s)")
    _RUN_REPL_LAST_DONE[0] = _time.time()


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

    # A re-execution writes a SECOND timestamped folder rather than overwriting,
    # so twins exist and this function silently picks the newest by mtime. For
    # non-learning arms the twins are bit-identical so the choice is harmless; for
    # a LIVE Q-table they legitimately differ, and then the picked folder decides
    # the CSV row. Log every candidate with its mtime so that selection is visible
    # in the run log instead of being an invisible coin-flip on filesystem order.
    if len(candidates) > 1:
        try:
            import time as _tlog
            _ordered = sorted(candidates, key=lambda d: d.stat().st_mtime)
            print("[RESULT-DIR] %d candidates for prefix=%r -- picking NEWEST "
                  "(st_mtime)" % (len(candidates), prefix))
            for _i, _d in enumerate(_ordered):
                _ts = _tlog.strftime('%Y-%m-%d %H:%M:%S',
                                     _tlog.localtime(_d.stat().st_mtime))
                print("[RESULT-DIR]   %s %s %s" % (
                    '-> PICKED' if _i == len(_ordered) - 1 else '   (ignored)', _ts,
                    _d.name))
            print("[RESULT-DIR]   note: a live-learner re-run produces DIFFERENT "
                  "twins; only the picked folder feeds the CSV row.")
        except Exception as _e:
            print("[RESULT-DIR] WARN could not log candidates: %r" % (_e,))

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
    import time as _tmod
    _t_collect0 = _tmod.perf_counter()
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
    # Flow-source tag (2026-09-05 audit): stats_Net_TotalFlowVeh has carried two
    # different physical quantities across rows (exit throughput vs section-mean
    # fallback). This tag records which branch produced it so analyses can
    # filter to ONE definition. Never compare flows across different sources.
    _sim_flow = str(global_row.get("Net_TotalFlowVeh", "") or "").strip()
    meta["stats_FlowSource"] = "sim_results" if _sim_flow not in ("", "0", "0.0") else "missing"

    # ── Truncated-run guard ───────────────────────────────────────────────────
    # A replication that ended early (e.g. MARL_RL eval seeds 300/400 on
    # 2026-09-06 stopped at 0.68/0.17 h with no error logged) must not enter
    # the master CSV as a comparable row: every KPI covers a fraction of the
    # horizon and the objective is not comparable (a 10-minute slice can show
    # obj=100+ while full runs show ~55).
    try:
        _dur_hrs = float(global_row.get("SimDuration_hrs", 0.0) or 0.0)
        if 0.0 < _dur_hrs < 0.9 * EXPECTED_SIM_DURATION_HRS:
            meta["run_success"] = False
            log(f"  ERROR: run truncated — SimDuration={_dur_hrs:.3f} h "
                f"(expected {EXPECTED_SIM_DURATION_HRS:.2f} h). "
                f"Marking run_success=False.")
    except Exception:
        pass

    # ── 2. summary.json ───────────────────────────────────────────────────────
    summary = _read_json(_os.path.join(folder, "summary.json"))
    for k, v in summary.items():
        if isinstance(v, (int, float, str, bool)):
            meta["json_" + k] = v

    _schedule = summary.get("global_kpis", {}) if isinstance(summary, dict) else {}
    meta["ttotal_bus_tt_deviation_sec"] = _schedule.get(
        "ttotal_bus_tt_deviation_sec",
        global_row.get(
            "ttotal_bus_tt_deviation_sec",
            global_row.get("Schedule_TotalAbsDeviation_s", 0.0),
        ),
    )

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
                            meta['stats_FlowSource'] = "distinct_veh_estimate"
                            log(f"  Flow estimated from distinct vehicles: "
                                f"{meta['stats_Net_TotalFlowVeh']} veh/h "
                                f"({int(_n_cars)}+{int(_n_buses)}+{int(_n_trucks)} / {_sim_dur:.2f}h)")
                        elif _wt_flow > 0:
                            meta['stats_Net_TotalFlowVeh'] = round(_wt_flow / _tot_len, 2)
                            meta['stats_FlowSource'] = "section_stats_mean"
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
            # Z1: Prefer TotalPassDelay (total pax-hours × 3600) as direct pax-second measure.
            # This is more reliable than SimTotalDelay which may have different calculation.
            _total_pass_delay_hrs = float(meta.get('stats_TotalPassDelay_hrs', 0) or 0)
            if _total_pass_delay_hrs > 0:
                meta['wobj_Z1_total'] = _total_pass_delay_hrs * 3600  # Convert hours to seconds
                meta['wobj_objective_total'] = meta['wobj_Z1_total']
                log(f"  Z1 (fallback, TotalPassDelay): {meta['wobj_Z1_total']:.1f} pax-s")
            else:
                # Second: use direct Aimsun simulation total pax delay (network stat)
                _sim_z1 = float(meta.get('stats_SimTotalDelay_pax_s', 0) or 0)
                if _sim_z1 > 0:
                    meta['wobj_Z1_total'] = _sim_z1
                    meta['wobj_objective_total'] = _sim_z1
                    log(f"  Z1 (fallback, SimTotalDelay): {_sim_z1:.1f} pax-s")
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
    try:
        log(f"  collect took {(_tmod.perf_counter() - _t_collect0):.1f}s")
    except Exception:
        pass
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
                out["aimsun_total_flow_veh"]   = 0.0
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
                    out[f"aimsun_flow_{_pfx}"]    = 0.0
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

    # --- Per-run intersection file: one file per experiment name, saved
    # alongside core_output.csv (PROJECT_DIR), e.g. "DCTSP_ZIG_intersections.csv".
    # Appended across replications/seeds of the same experiment name so a
    # single run's full intersection KPIs live in one dedicated file.
    _run_name = str(row.get("experiment") or "run").strip() or "run"
    _safe_run_name = ''.join(ch if ch.isalnum() or ch in ('_', '-') else '_' for ch in _run_name)
    _run_inter_path = _os.path.join(PROJECT_DIR, f"{_safe_run_name}_intersections.csv")
    _write_run_hdr = not _os.path.isfile(_run_inter_path)
    with open(_run_inter_path, "a", newline="", encoding="utf-8") as _rf:
        _rw = csv.DictWriter(_rf, fieldnames=_inter_keys, extrasaction='ignore')
        if _write_run_hdr:
            _rw.writeheader()
        for _id in _inter_dicts:
            _rw.writerow(_id)

    log(f"  Core output: global → {_global_path}, intersections → {_inter_path} ({len(_inter_dicts)} rows), per-run → {_run_inter_path}")


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
        "ttotal_bus_tt_deviation_sec",
        # ── Bus service quality ───────────────────────────────────────────────
        "stats_BusTotalTT_hrs",      "stats_N_BusTrips", "stats_N_DistinctBuses",
        # ── TSP action counts ─────────────────────────────────────────────────
        "stats_TSP_Detections",      "stats_TSP_Extensions", "stats_TSP_Insertions",
        # Previously-uncounted timing actions — the real cascade drivers
        "stats_TSP_GreenRealloc",    "stats_TSP_EarlyRed",   "stats_TSP_OffsetCorr",
        "stats_TSP_PhaseSkip",       "stats_TSP_PhaseRot",
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

    # Resolve project dir at runtime (confirms model is open) and update the
    # module-level constants so sub-scripts importing this module stay in sync.
    global PROJECT_DIR, CONTROLLER_PATH, RUN_CONFIG_PATH
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
        "wobj_Z3_total", "wobj_Z4_total", "ttotal_bus_tt_deviation_sec"
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

    # Passive junctions (10157950, 11118289, 1119660, 39568) were removed from
    # the corridor system — they are give-way/roundabout accesses with no
    # signal plan and contributed nothing to control or KPIs.

    run_num      = 0
    failures     = []
    base_demands = {}
    manifest     = []
    _batch_results_folders = set()

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
                "WOBJ_ALPHA":            0.2,   # Z1 (weighted pax-delay) weight — reduced to 20% to reduce Z1 dominance
                "WOBJ_BETA":             0.8,   # Z2 (flow bandwidth) weight — increased to 80% to dominate objective
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

                log(f"Job {run_num}/{n_total} done, {n_total - run_num} to go")

                # ── Collect and save metrics ───────────────────────────────
                try:
                    metrics = collect_run_metrics(
                        PROJECT_DIR, strategy, seed, scalar,
                        exp_name, coordinated, elapsed, success,
                        bus_predictor=bus_predictor
                    )
                    append_master_csv(MASTER_CSV_PATH, metrics)
                    if success and metrics.get("stats_results_folder"):
                        _batch_results_folders.add(metrics["stats_results_folder"])
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

    # ── Generate offset-correction cycle dashboard ────────────────────────────
    # Reads OFFSET_CORRECTION rows from reward_cycle_*.csv and generates a
    # cycle-dependent (not bus-dependent) dashboard showing offset corrections
    # for green-wave alignment recovery.  Triggered a few seconds before cycle
    # end, independent of individual bus arrivals.
    try:
        import importlib as _ilib
        if _SCRIPT_DIR not in _sys.path:
            _sys.path.insert(0, _SCRIPT_DIR)
        import plot_offset_correction_cycle as _pocc
        _ilib.reload(_pocc)
        # Find the latest reward_cycle CSV
        _logs_dir = _os.path.join(PROJECT_DIR, "logs")
        _reward_csvs = sorted(
            [f for f in _os.listdir(_logs_dir) if f.startswith("reward_cycle_") and f.endswith(".csv")],
            key=lambda x: _os.path.getmtime(_os.path.join(_logs_dir, x)),
            reverse=True
        )
        if _reward_csvs:
            _latest_reward_csv = _os.path.join(_logs_dir, _reward_csvs[0])
            _pocc.generate_offset_correction_cycle_dashboard(
                _latest_reward_csv,
                _os.path.join(PROJECT_DIR, "offset_correction_cycle.html")
            )
            log(f"Offset-correction cycle dashboard generated")
    except Exception as _oce:
        log(f"WARNING: Offset-correction cycle dashboard generation failed: {_oce}")

    # ── Generate bus tracking dashboard ──────────────────────────────────────
    try:
        import importlib as _ilib3
        if _SCRIPT_DIR not in _sys.path:
            _sys.path.insert(0, _SCRIPT_DIR)
        import generate_bus_tracking_dashboard as _gbtd
        _ilib3.reload(_gbtd)
        _gbtd_html = _gbtd.generate(
            log_dir=_os.path.join(PROJECT_DIR, "logs"),
            out_html=_os.path.join(PROJECT_DIR, "bus_tracking_dashboard.html"),
        )
        if _gbtd_html:
            log(f"Bus tracking dashboard: {_gbtd_html}")
    except Exception as _btde:
        log(f"WARNING: Bus tracking dashboard generation failed: {_btde}")

    # ── Generate LaTeX Beamer slides ─────────────────────────────────────────
    try:
        import importlib as _ilib4
        if _SCRIPT_DIR not in _sys.path:
            _sys.path.insert(0, _SCRIPT_DIR)
        import generate_beamer_slides as _gbs
        _ilib4.reload(_gbs)
        _gbs_tex = _gbs.generate(
            batch_csv=MASTER_CSV_PATH,
            out_tex=_os.path.join(PROJECT_DIR, "beamer_slides.tex"),
        )
        if _gbs_tex:
            log(f"Beamer slides: {_gbs_tex}")
    except Exception as _bse:
        log(f"WARNING: Beamer slides generation failed: {_bse}")

    # ── Copy batch dashboards into every run's results/ folder ────────────────
    # The dashboards above compare ALL experiments in this batch and are written
    # once at PROJECT_DIR level. Copy them into each results/<run>/ folder too,
    # so browsing a single run's folder also has the full comparison alongside
    # its own CSVs — no need to hunt for the project-root copy.
    try:
        _dash_files = [
            _os.path.join(PROJECT_DIR, "tsp_dashboard.html"),
            _os.path.join(PROJECT_DIR, "reward_breakdown.html"),
            _os.path.join(PROJECT_DIR, "offset_correction_cycle.html"),
            _os.path.join(PROJECT_DIR, "bus_tracking_dashboard.html"),
            _os.path.join(PROJECT_DIR, "beamer_slides.tex"),
        ]
        _dash_files = [p for p in _dash_files if _os.path.isfile(p)]
        _n_copied = 0
        for _rf in _batch_results_folders:
            for _df_path in _dash_files:
                try:
                    shutil.copy2(_df_path, _os.path.join(_rf, _os.path.basename(_df_path)))
                    _n_copied += 1
                except Exception as _cpe:
                    log(f"WARNING: could not copy {_os.path.basename(_df_path)} to {_rf}: {_cpe}")
            # Copy dashboard_data/ directory (externalized heavy data)
            _data_src = _os.path.join(PROJECT_DIR, "dashboard_data")
            if _os.path.isdir(_data_src):
                _data_dst = _os.path.join(_rf, "dashboard_data")
                try:
                    if _os.path.isdir(_data_dst):
                        shutil.rmtree(_data_dst, ignore_errors=True)
                    shutil.copytree(_data_src, _data_dst)
                    _n_copied += 1
                except Exception as _cpe:
                    log(f"WARNING: could not copy dashboard_data/ to {_rf}: {_cpe}")
        log(f"Copied {len(_dash_files)} dashboard(s) into {len(_batch_results_folders)} "
            f"results folder(s) ({_n_copied} file(s) written)")
    except Exception as _cde:
        log(f"WARNING: dashboard copy-to-results-folders failed: {_cde}")

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


if __name__ == "__main__":
    main()
