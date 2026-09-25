"""
Specialized TSP action-selection modes for IntersectionController.

The reference controller is kg/intersection_controller.py (shim) + the shared
engine — NOT kg/intersection_controller_lean.py.  The reference lineage never
implemented these specialized modes, so the ZIG / MP-ECTM / BXT / BARGAIN
generators here were ported from the lean file (the only implementation in the
repo); where their behavior conflicts with the engine's own GE/INS reward
evaluation, the engine's behavior wins.
"""
import sys
sys.path.insert(0, r"C:\AimsunPackages")

import math
import numpy as np

# ── Default constants (overridden by run_config.py / batch_runner) ────────────

DCTSP_ZIG_MODE     = False
DCTSP_MIN_INS_DURATION_S = 10.0
DCTSP_MAX_INS_DURATION_S = 25.0
ZIG_PHASE_OVERLAP_S = 3.0
ZIG_BALANCE_FACTOR  = 1.0
# Lenient admission threshold used ONLY for green-extension candidates: an
# extension that saves bus delay is tolerated up to this cross-street pax-cost
# ratio, even when the strict (insertion) gate would reject it.  GE is a small,
# same-phase intervention, so a cross-traffic penalty up to this factor is
# still worth granting.  Default 2.0 => allow up to 2.0x the strict factor.
ZIG_GE_BALANCE_FACTOR  = 2.0
# Candidate-family gates (Signal-Sequencing sweep): SWAPS only when
# ZIG_ENABLE_SEQ, green-realloc ("TIMES") only when ZIG_ENABLE_GR.
# Default True everywhere preserves legacy behaviour (all candidate types
# generated) for experiments that do not set them.
ZIG_ENABLE_GE  = True
ZIG_ENABLE_INS = True
ZIG_ENABLE_GR  = True
ZIG_ENABLE_SEQ = True
PHASE_ROTATION_MODE = True

MP_ECTM_MODE      = False
MP_ECTM_DT_S      = 1.0
MP_ECTM_MIN_EXT_S = 3.0
MP_ECTM_MAX_EXT_S = 8.0
MP_ECTM_BALANCE_FACTOR = 1.0
MP_ECTM_GE_BALANCE_FACTOR = 2.0
MP_ECTM_CAR_OCC   = 1.6

# ── MP_ECTM_DP: CTMGS grid search + downstream DP look-ahead ─────────────────
# Hybrid Method III: keeps CTMGS' exhaustive grid sweep over [MIN_EXT, MAX_EXT]
# but scores every candidate with a CELLQLEARN-style DP coordination penalty —
# projected downstream-junction delay over the bus trajectory horizon — so the
# grid stops being myopic about corridor-wide cross-traffic harm.
MP_ECTM_DP_MODE      = False
MP_ECTM_DP_HORIZON_S = 90.0
MP_ECTM_DP_STAGE_S   = 15.0
MP_ECTM_DP_COORD_WEIGHT = 0.40

# ── BXT: CTM-based multiagent Q-learning TSP (Chanloha et al. 2014) ───────────
BXT_MODE           = False
BXT_DT_S           = 1.0
BXT_EPSILON        = 0.1
BXT_LEARN          = True   # close the Q-learning loop (credit realized delay back)
# BXT_EVAL_DIAGNOSTICS: run the realized-outcome measurement EVEN in eval (frozen)
# and emit a paired [BXT_EVAL] line per decision -- PREDICTED benefit (bps/cpc the
# decider used to choose) vs REALIZED benefit (delay actually measured ~1.5 cycles
# later). Lets you judge how well the controller's model matches reality without
# unfreezing the policy: the Q-table is NEVER updated in eval, only the NO_ACTION
# baseline accumulates (needed to score realized advantage; not part of the greedy
# policy). Off by default; the smoke pipeline turns it on. Parse with
# analyze_bxt_predictions.py.
BXT_EVAL_DIAGNOSTICS = False
# BXT action-FAMILY enable flags (default ALL True -> full action space, no change
# to normal runs). Restrict the BXT argmax/explore to enabled families so the
# Phase-3 tactic axis (TIMES=timing GE/GR, SWAPS=order INS/EARLY_RED) is
# meaningful for a BXT champion -- previously the tactic knob (ZIG_ENABLE_*) was
# invisible to BXT so all tactics were byte-identical. See dctsp_bxt family gate.
BXT_ENABLE_GE = True   # green extension (timing)
BXT_ENABLE_INS = True  # green insertion / phase advance (order/swap)
BXT_ENABLE_GR = True   # green reallocation (timing)
BXT_ENABLE_ER = True   # early red (order/swap)
BXT_ENABLE_OC = True   # offset correction (solved bus-phase alignment, 2026-09-22)
# ── MEASURED side (cross) cost ────────────────────────────────────────────────
# The shockwave/CTM side-delay estimate ignores how FULL the cross approach
# already is, so it badly UNDER-prices holding a near-jammed cross street on red
# (spillback) -- the miscalibrated term behind the seed-lottery car cascades
# (predicted cross cost ~uncorrelated with realized; see
# reward-uncalibrated-seed-lottery). When MEASURED_SIDE_COST is on,
# _compute_side_delay_penalty also computes a cost from the MEASURED cross-approach
# state (stats.latest_section: standing queue_veh*lanes + arrivals over the extra
# red) with a SUPERLINEAR spillback severity as measured saturation (density/jam or
# queue_m/length) -> 1, and returns the WORSE of analytic vs measured so a
# congested cross street is never under-priced. This flows into the net-benefit
# gate + cost veto (via _cross_cost_paxs) so harmful actions on a congested cross
# approach get vetoed. Off by default; the champion pipeline turns it on globally.
MEASURED_SIDE_COST       = False
MEASURED_SIDE_SPILL_GAIN = 3.0    # spillback severity gain: cost *= 1 + gain*sat/(1-sat)
MEASURED_SIDE_FRESH_S    = 90.0   # max age (s) of a latest_section measurement to trust
MEASURED_SIDE_COST_DIAG  = False  # log [MEAS_SIDE] per junction: does the measured cross cost engage?
# ── Decision diagnostics (2026-09-25) ─────────────────────────────────────────
# DIAG_FLOW_STAGE: one compact [FLOW_STAGE] line per junction every 60 s
# (throttled with [SIDE_SCAN]): the flow REGIME the controller sees --
# stage FREE/SAT/OVER/JAM from main x + queue + armed, with main/side flows.
# Lets you check "what stage was junction N in?" without digging through
# UpFlowList dumps.
# DIAG_DECISION: one [DECISION] line per COMMITTED (non-NO_ACTION) action, all
# modes: predicted bus_saved / other_inc / side_inc / net + the flow stage at
# commit. Actions are rare (~tens/run) so this never floods. Pair with
# BXT_EVAL_DIAGNOSTICS=1 (CELLQLEARN realized-vs-predicted) and the per-run
# reward_cycle_*.csv ledger, then run diagnose_vs_notsp.py to blame the exact
# actions that made a run worse than NO_TSP and trace their cascade.
DIAG_FLOW_STAGE = True
DIAG_DECISION   = True
# ── Recoverability (offset-preservation) gate (2026-09-23) ────────────────────
# A cycle-lengthening action (GE/INS/VP/PT) is FEASIBLE only if the time it
# borrows can be trimmed back from the upcoming cross phases THIS cycle (slack
# above min-green). Otherwise the offset drifts and the green wave breaks
# downstream -- the dominant failure on saturated corridors (Logan). The engine
# clamps the action to the recoverable headroom, or stands down if even the
# minimum is unrecoverable. Read from engine globals via the MODE_FLAGS loop.
RECOVERABILITY_GATE   = True   # enforce the same-cycle offset-recovery constraint
RECOVERABILITY_SLACK_S = 1.0   # tolerance (s) before an action is clamped/vetoed
# Recovered-cycle-plan (signal-transition) recovery. K=1 (default) = strict
# same-cycle offset recovery. K>1 admits grants recoverable within K cycles and
# walks the offset back over <=K cycles (see engine._solve_recovery_plan +
# restore_phase_if_needed). tau bounds the per-cycle trim (transition smoothness).
RECOVERY_MAX_CYCLES    = 1
RECOVERY_TRANSITION_RATE = 0.5
# Progression (Purdue Coordination Diagram) gate: the controller tracks live
# arrivals-on-green (POG) and vetoes an offset-shifting action whose displaced
# main-platoon pax*s (POG-weighted) exceed PROGRESSION_MAX_LOSS_PAXS -- i.e. it
# refuses to push its own coordinated platoon off green. Conservative default
# (only large shifts on high-flow coordinated approaches fire it).
PROGRESSION_GATE          = True
PROGRESSION_MAX_LOSS_PAXS = 300.0
# Transit-weighted MaxPressure: each bus on a movement adds (BusOcc*weight-CarOcc)
# to its pressure, so the continuous state-based controller prioritises the
# movement carrying more people. weight=1.0 = plain occupancy; >1 favours buses.
MP_TRANSIT_PAX_WEIGHT = 1.0
# CONTINUOUS_MONITOR_MODE (EXPERIMENTAL, default OFF): evaluate the signal-action
# set on the CURRENT traffic state every decision cadence even when NO bus is
# present (car-only objective); a bus, when present, adds its passenger-weighted
# term so it is prioritised. Reframes the reward-TSP layer from bus-triggered to
# continuous state feedback. CONTINUOUS_MONITOR_MIN_GAIN_PAXS = min net pax*s
# benefit for a no-bus (car) action to commit.
CONTINUOUS_MONITOR_MODE = False
CONTINUOUS_MONITOR_MIN_GAIN_PAXS = 50.0
# DEMAND_SEED_WARM_S: sim-time (s) after which the OD-rated demand seed stops
# standing in for measurement -- an unmeasured section then reads faithful 0.
# Fixes the permanent 1800.0 seed (OD prior clamped at saturation) on sides
# whose counters never tick. Measured tiers above the fallback already return
# live values whenever traffic is actually present.
DEMAND_SEED_WARM_S = 300.0
# MONITOR_STATE_GATE: hold no-bus CONTINUOUS monitor ticks unless there is
# state to act on (fresh side feed, occupied side section, or queued main).
# Blocks the FREE / bus=-1 / pred_side=0 commits behind the Logan losses
# (side cost reads 0 either because the approach is truly empty or because
# the counters never tick -- indistinguishable at commit time). Bus-present
# ticks are unaffected. False restores legacy behaviour.
MONITOR_STATE_GATE = True
BXT_TRAIN_EPSILON  = 0.1    # exploration rate during TRAIN seeds (eval uses 0)
BXT_PHASE          = "per_seed"  # set per replication by AAPIInit: train|eval|per_seed
BXT_ALPHA          = 0.01
BXT_GAMMA          = 0.005
BXT_CAR_OCC        = 1.2
BXT_BALANCE_FACTOR = 1.0
BXT_GE_BALANCE_FACTOR = 2.0
# Demand-regime-aware state (task a): append a 5th state bin from the observed
# absolute cross-street load so ONE policy conditions on real-time demand level.
# Off by default (keeps the 4-tuple state + existing Q-tables valid); enable it
# WITH multi-regime training (BXT_TRAIN_DEMAND_SCALARS) or the extra dimension is
# just sample-starved. Thresholds in pax·s (calibrate from a run's [BXT] side_p).
BXT_DEMAND_STATE       = False
BXT_DEMAND_BIN_LO_PAXS = 300.0
BXT_DEMAND_BIN_HI_PAXS = 1500.0
# Minimum effective bus delay required before BXT may choose a TSP action.
# A positive experiment override replaces SELFORG_MIN_BUS_DELAY_S.
CELLQLEARN_MIN_GAIN_S = 0.0
# Cap on a BXT phase-insertion duration (s).  Long insertions truncate the
# current main-street green and are the most disruptive BXT action, so clamp
# them instead of committing the full 15-20 s candidate (mode-commits-own-
# action bypasses the standard BP_upper_bound clamp).
BXT_MAX_INS_S = 12.0

# ── CPD-QL: tabular Q-learning per junction (paper Method I) ───────────────────
# DCTSP_MARL as a REAL learner: each junction is an independent agent with its
# OWN Q-table over the paper's 54-state space (3 headway-deviation x 3 bus-ETA
# x 3 estimated-delay x 2 phase-match bins), acting epsilon-greedy over the
# 7-action set {NA, GE_5/10/15, INS_10/15/20}.  Per-decision selection uses the
# paper reward  r(a) = w_h*rho_bus*(|sigma_in|-|sigma_out(a)|)
#                     + (1-w_h)*((d_NA - d_a)*n_b - D_car(a))   [pax-s]
# and the closed loop (CPDQL_LEARN) credits each action its REALIZED advantage
# vs a per-(junction,state) NO_ACTION baseline, bootstrapped by gamma onto the
# junction's next decision state.  train seeds run epsilon-train exploration;
# eval seeds freeze the learned policy (eps=0, no updates).
CPDQL_MODE           = False
CPDQL_ALPHA          = 0.1   # Q-learning step (paper)
CPDQL_GAMMA          = 0.9   # discount (paper)
CPDQL_EPSILON        = 0.1   # exploration after training / per-seed runs
CPDQL_TRAIN_EPSILON  = 0.3   # exploration during TRAIN seeds (eval uses 0)
CPDQL_LEARN          = True  # close the Q-learning loop (realized reward credit)
CPDQL_PHASE          = "per_seed"  # set per replication by AAPIInit
CPDQL_W_H            = 0.5   # headway-vs-delay weight in the paper reward
CPDQL_CAR_OCC        = 1.5   # paper rho_car
CPDQL_MIN_GAIN_S     = 0.0   # act only when no_act_delay clears this (0 = off)

# ── v7 bus-equity & corridor-reward tuning ────────────────────────────────────
# BUS_PAX_WEIGHT: equity multiplier applied to bus pax-s wherever it is weighed
# against car pax-s (decision-time benefit rows, the decider cost veto, and the
# realized-delay learning reward).  Buses are rare but carry ~27x a car's
# occupants (BusOcc=40 vs CarOcc=1.5); this extra tilt makes the optimizer buy
# bus time more eagerly.  NO_ACTION baselines use the same weight so the
# advantage signal stays comparable.
# 2026-08-24 (#3): dialed 2.0 -> 1.3.  At 2.0 the optimizer bought bus time so
# eagerly it committed uncounted OC/GR timing changes that doubled car delay
# (champion search: car +69%, obj -26%).  1.3 keeps a modest bus tilt (buses
# already carry ~27x a car's pax via BusOcc) without over-buying.
BUS_PAX_WEIGHT = 1.3
# GREEN_KEEP_CREDIT_S: reinforcement floor.  benefit = predicted red-wait x occ
# is exactly 0 for a bus predicted to arrive on green, which made the cost veto
# kill EVERY action (measured: 1458 no-actions vs 5 extensions per run).  When
# the bus is inside the reachable window anyway, credit this many seconds of
# protected green (x occ x BUS_PAX_WEIGHT) so near-free reinforcement actions
# can fire while expensive ones still face the veto.
GREEN_KEEP_CREDIT_S = 3.0
# CORRIDOR_REWARD_NEIGHBOR_W: inter-intersection reward sharing.  The realized-
# delay Q-update is otherwise purely LOCAL -- an action that shoves its queue
# onto the next junction scores great locally.  With this weight, each decision
# also credits the SIGNED realized delay delta of its CorridorCoordinator
# neighbors over the same window, so helping the corridor pays and hurting it
# costs (the coordination reward the user asked for).
CORRIDOR_REWARD_NEIGHBOR_W = 0.5

# ── CELLQLEARN_DP: CellQ-Learn with Dynamic Programming ───────────────────────
# V2X-coordinated TSP using queue-length prediction + DP backward recursion.
# Reference: Huang H.-K. & Hsu Y.-T. (2025), "Coordinated transit signal priority
# control with queue length prediction in V2X environments",
# Transportation Letters 18(2), 392-413.
CELLQLEARN_DP_MODE      = False
CELLQLEARN_DP_DT_S      = 1.0
CELLQLEARN_DP_HORIZON_S = 90.0
CELLQLEARN_DP_STAGE_S   = 15.0
CELLQLEARN_DP_COORD_WEIGHT = 0.22
CELLQLEARN_DP_CAR_OCC   = 1.2
CELLQLEARN_DP_BALANCE_FACTOR = 1.0
CELLQLEARN_DP_GE_BALANCE_FACTOR = 2.0

# ── BARGAIN_SPM: Nash bargaining game TSP (AnsariEsfeh & Kattan 2025) ─────────
BARGAIN_SPM_MODE   = False
NASH_GATE_MODE     = False
BG_DET_LVL_IMM_S   = 4.0
BG_DET_LVL_NEAR_S  = 12.0
BG_DET_LVL_FAR_S   = 24.0
BG_BUS_W_IMM       = 1.6
BG_BUS_W_NEAR      = 1.35
BG_BUS_W_FAR       = 1.1
BG_BUS_W_VFAR      = 0.95
BG_SPM_RISK_WEIGHT = 1.8
BG_MIN_BUS_DELAY_S = 5.0
BG_MIN_GAIN_S      = 5.0
BG_CASCADE_MULT    = 2.0
BG_NO_ACTION_BONUS_S = 20.0   # pax·s inertia bonus for NO_ACTION

DCTSP_GREEN_REALLOC_MODE = False
GREEN_REALLOC_RECOVER_FRACTION = 1.0

# ── GLOBAL_REWARD aggregation (DCTSP_MARL lineage) ──────────────────────
# When True, the common selection layer scores each candidate on corridor-
# global net passenger impact (local net + downstream-chain bus effect)
# instead of this-junction-local net. Default False = legacy local scoring.
GLOBAL_REWARD_MODE = False
# How many downstream managed junctions the chain projection walks (this
# junction excluded). 0 = next-junction only (legacy Z2 behaviour).
GLOBAL_REWARD_CHAIN_HORIZON = 3

MILP_TSP_MODE = False
MILP_TIME_LIMIT_S = 0.1
MILP_HORIZON_CYCLES = 2
MILP_BUS_WEIGHT = 1.0
MILP_CROSS_WEIGHT = 2.0
MILP_REQUIRE_MAIN_FLOW = True
MILP_MIN_MAIN_FLOW_VPH = 1.0
MILP_MIN_GREEN_S = 5.0
MILP_MAX_GREEN_S = 60.0
MILP_CYCLE_S = 135.0

# ── CENTRALISED: perfect-information corridor controller (Method 0 in the paper) ──
CENTRALIZED_MODE = False
CENTRALIZED_INTERVAL_S = 1.0          # documented per-second evaluation cadence
CENTRALISED_MIN_BUS_DELAY_S = 5.0     # only intervene for a genuinely-delayed bus
CENTRALISED_REACH_MARGIN_S = 5.0      # bus must be reachable within cycle + margin

# ── NASH_BARGAIN: real (generalized) Nash bargaining TSP ─────────────────────
# Two-player cooperative game per bus-detection: Transit (T) vs Cross-street (C).
# Gains are measured over a DISAGREEMENT/THREAT point: T's threat = no priority
# (0 gain); C's threat = the worst (most disruptive) candidate action's cross
# cost. The solution maximizes the Nash PRODUCT of gains-over-threat
#   N(a) = G_T(a)^p_T * G_C(a)^p_C ,  G_T=bps(a), G_C=Cmax-cpc(a)
# (a weighted sum, as the old alias used, cannot reject BOTH extremes; the
# product does -> an interior compromise action). Tier 2 (NASH_CORRIDOR_MODE)
# couples junctions along the bus route into a corridor best-response game.
NASH_BARGAIN_MODE   = False
# NASH_MEASURED_STATE: price the bargaining payoffs from the live MEASURED
# detector state -- the mainline through-benefit is bounded by the measured main-
# approach queue (not a constant saturation assumption), and the cross cost uses
# the measured side feed. Makes the game reflect real-time network state. Pair
# with MEASURED_QUEUE_FEED + MEASURED_SIDE_COST. (2026-09-24)
NASH_MEASURED_STATE = False
NASH_BUS_WEIGHT     = 1.0    # bargaining power p_T (1,1 => symmetric Nash)
NASH_CROSS_WEIGHT   = 1.0    # bargaining power p_C
NASH_MIN_BUS_DELAY_S = 5.0   # gate 1: don't bargain for a barely-delayed bus
NASH_MIN_GAIN_S      = 5.0   # gate 2: min transit gain (s) * bus_occ to act
# Tier 2 — corridor Nash equilibrium (best-response over the bus route):
# Continuous play: run the SAME bargain on the traffic state every monitor tick
# even with no bus present (through-traffic vs cross-street). Only takes effect
# when CONTINUOUS_MONITOR_MODE is on (that path is what invokes the no-bus eval).
NASH_CONTINUOUS_MODE = True
# Bargaining power p_T for the CONTINUOUS (no-bus) game. Default 0.0 = utilitarian
# (maximise net surplus = minimise TOTAL passenger delay); the bus-present game
# keeps its own NASH_BUS_WEIGHT. Overrides p_T only on monitor ticks.
CONTINUOUS_BARGAIN_BUS_WEIGHT = 0.0
# Continuous CORRIDOR game (cross-intersection, bus-free): discount each no-bus
# candidate's benefit by the downstream landing cost of the green it adds,
# projected onto the next corridor junctions' LIVE signal windows (no bus needed).
# This is the coupling that stops the continuous game shoving queues one junction
# downstream. Experimental, default OFF. Weight on the coupling term below.
CONTINUOUS_CORRIDOR_MODE       = False
CONTINUOUS_CORRIDOR_NEIGHBOR_W = 0.5
# Make the BXT learner (CELLQLEARN) play continuously too: on a no-bus monitor
# tick its Q argmaxes NO_ACTION (nothing to serve), so route that tick through the
# shared continuous state bargain. The learner still decides bus-PRESENT ticks.
BXT_CONTINUOUS_MODE = True
# ── Controller-timing rules (2026-09-24) ─────────────────────────────────────
# MIN_PHASE_ACTIVE_S: once a phase starts, the controller must run it at least
# this long before ANOTHER TSP action is considered (stops re-actioning a just-
# started green). 0 = off (default; set per-arm, e.g. 5.0, for the continuous
# controller).
MIN_PHASE_ACTIVE_S = 0.0
# NO_ACTION_HOLD_S: after a NO_ACTION outcome, wait this long before re-checking
# (don't re-run the full evaluation every sim step when nothing is changing). The
# next phase boundary re-opens evaluation regardless (subject to MIN_PHASE_ACTIVE).
# Single source of truth for the "NO_ACTION hold" that used to be a hard-coded 5 s
# in the engine; changeable per arm. Default 5.0 preserves the historical value.
NO_ACTION_HOLD_S = 5.0
# EMPTY_PHASE_SKIP_MODE (Rule C): when a phase has essentially no queue, truncate
# its green so the plan advances toward the MOST-PRESSURED phase (gives the freed
# time to real demand). Default OFF. EPS = "empty" queue threshold (pax); TARGET =
# min pressure elsewhere (pax) required before skipping. Respects MinGreen.
EMPTY_PHASE_SKIP_MODE       = False
EMPTY_PHASE_QUEUE_EPS_PAX   = 1.0
EMPTY_PHASE_MIN_TARGET_PAX  = 5.0
# ── CELLQLEARN reward via the Purdue Coordination Diagram (POG) ───────────────
# When on, each offset-shifting BXT action (GE/INS/GREEN_REALLOC) is penalised in
# the LEARNER's reward by BXT_POG_WEIGHT × _progression_cost(shift) — the pax·s of
# the main platoon pushed off green (Percent-on-Green damage). So the learner
# LEARNS to prefer coordination-preserving actions, not just get vetoed by the
# progression gate after the fact. Default OFF. (2026-09-24)
BXT_POG_REWARD = False
BXT_POG_WEIGHT = 1.0
# ── Coordinated-actuated BASE layer (layer 2) ─────────────────────────────────
# The Aimsun plans are FIXED-TIME (no gap-out/max-out/force-off). This adds an
# online demand-responsive base that runs UNDER the TSP algorithms: gap-out an
# empty non-coordinated phase, max-out a long one, and PROTECT the coordinated
# phase (the longest fixed phase = the green band) so its offset is preserved.
# Default OFF (enable per-arm); the coordinated phase is never gapped/maxed here.
ACTUATED_BASE_MODE        = False
ACTUATED_MIN_GREEN_S      = 5.0      # never terminate a phase below this
ACTUATED_MAX_GREEN_S      = 60.0     # max-out cap for non-coordinated phases (0=off)
ACTUATED_GAP_QUEUE_EPS_VEH = 0.5     # gap-out when measured served demand <= this (veh)
ACTUATED_PERMISSIVE_GATE  = False    # if on, the no-bus/continuous decider may act
                                     # only while the coordinated phase is green
ACTUATED_OFFSET_PRESERVE  = False    # hand reclaimed gap/max-out seconds to the
                                     # coordinated phase so cycle length (and the
                                     # offset) is held. DEFAULT OFF (2026-09-24):
                                     # it retimes phases at runtime and is
                                     # unvalidated in Aimsun -- enable only after a
                                     # sim shows the cycle holds (drift guard clean)
# Self-verifying drift guard: each cycle, compare realised coordinated-cycle
# length to nominal; after ACTUATED_DRIFT_MAX cycles off by more than
# ACTUATED_DRIFT_TOL_S, auto-disable offset-preserve and log [ACTBASE][DRIFT].
ACTUATED_DRIFT_TOL_S      = 5.0
ACTUATED_DRIFT_MAX        = 3
NASH_CORRIDOR_MODE   = False # couple route junctions via downstream projection
NASH_NEIGHBOR_WEIGHT = 0.5   # weight on the downstream green-wave coupling term
NASH_MAX_ITER        = 10    # max Gauss-Seidel best-response sweeps
NASH_CONVERGENCE_TOL = 0.01  # stop when max |Δbus_saved_s| across route < tol
# Bargain over the action DURATION at integer-second resolution (coarse-to-fine
# search per action type) instead of the naive coarse {5,10,15} grid.
NASH_INTEGER_DURATIONS = False

DECIDER_COST_VETO_RATIO = 1.0

INS_INTERGREEN_S  = 5.0
SELFORG_MIN_BUS_DELAY_S = 10.0
NETWORK_FACTOR    = 1.0
CROSS_TRAFFIC_COST_MULTIPLIER = 2.0
MAX_GE_EXTENSION_S = 10.0
DCTSP_MULTI_CYCLE_X_THR   = 0.85
DCTSP_MULTI_CYCLE_X_FLOOR = 0.10   # caps the 1/(1-x) multi-cycle amplifier at 4x
                                   # (was 0.02 -> 50x, a major contributor to the
                                   #  1e9 pax-s side-cost blowup)

# ── Future-horizon penalty: each action's cross-traffic cost is scaled by the
# fraction of a cycle it disturbs, projected forward over the lookahead window.
# This makes action rewards horizon-aware — a small GE on a short cycle has less
# future echo than a long insertion on a long cycle. Tune per-experiment via
# run_config / batch_runner.
# ── MaxPressure (Varaiya 2013) — fixed & flexible cycle ─────────────────────
# Ported from sumoITScontrol (DerKevinRiehl, ETHZ, GPL-3.0) into the Aimsun
# shared engine.  Pressure per phase = Σ upstream queue – Σ downstream queue
# (pax-weighted so a queued bus counts ~27× a car).  Fix recomputes a
# proportional green split at each cycle boundary; Flex re-evaluates every T_A.
MAXPRESSURE_FIX_MODE  = False
MAXPRESSURE_FLEX_MODE = False
MAXPRESSURE_T_L       = 3      # yellow / lost time per phase
MAXPRESSURE_G_MIN     = 5      # min green per phase
MAXPRESSURE_G_MAX     = 50     # max green per phase
MAXPRESSURE_CYCLE_FIX = 120    # fixed cycle duration (Fix)
MAXPRESSURE_CYCLE_FLEX= 120    # nominal cycle for Flex (used for effective-green calc)
MAXPRESSURE_T_A       = 5      # re-check interval for Flex
MAXPRESSURE_MEAS_PERIOD = 4    # steps to average queue before deciding (1/step=1s)

# ── MP-TSP-LB: corridor MaxPressure + transit priority + LANE-BLOCKAGE ────────
# Kobeissi, Li, Mahmassani & Chen (2026), "Max-Pressure Signal Control with
# Transit Priority and Lane Blockage Mitigation" (MP-TSP-LB, TRR
# doi:10.1177/03611981261444712).  Extends the plain pax-weighted MaxPressure
# above (which already gives transit priority via the 27x bus queue weight) with
# the paper's two corridor terms.  Both default OFF and layer on top of the
# FLEX/FIX deciders (a dedicated MAXPRESSURE_LB arm turns them on):
#
#   (1) DWELLING-BUS LANE BLOCKAGE (MP_LANEBLOCK_MODE).  A bus dwelling at a
#       near-side stop blocks a through lane, so the served movement's
#       saturation flow drops -- MaxPressure should NOT pour green onto a queue
#       that physically cannot discharge past the stopped bus.  We scale that
#       phase's pressure by the surviving lane fraction (blocked_lanes counted
#       from buses with CurrentStopTime>=MP_DWELL_MIN_S).  This does NOT hurt the
#       bus: it is dwelling (boarding), not waiting for green; when it pulls out
#       the block clears and the now-large queue is served in full.
#
#   (2) CORRIDOR COORDINATION (MP_CORRIDOR_COORD_MODE).  Plain per-junction
#       MaxPressure is blind to whether the DOWNSTREAM corridor link can accept
#       the platoon it is about to release.  We discount the corridor-through
#       phase pressure when the next junction's main approach is near jam
#       (capacity-aware / back-pressure), reusing the CorridorCoordinator route
#       index + the measured downstream queue -- the same infrastructure the
#       cascade-cost term uses.  Prevents pushing a green wave into a link that
#       will spill back and gridlock the corridor.
MP_LANEBLOCK_MODE         = False  # (1) enable dwelling-bus lane-blockage
MP_LANEBLOCK_LANES        = 1.0    # lanes ONE dwelling bus blocks (near-side stop)
MP_LANEBLOCK_TOTAL_LANES  = 2.0    # fallback approach lane count if unmeasured
MP_DWELL_MIN_S            = 5.0    # min CurrentStopTime (s) to count a bus as dwelling
# GREEN-GATE (true dwelling vs red-queue discriminator): a bus stopped while its
# movement is GREEN is not waiting for the light -- it is dwelling at a stop (or
# blocked downstream); either way extending that green is wasted, which is the
# mitigation's whole point. A bus stopped on RED is merely queued and MUST be
# excluded. With this on, a stopped bus counts as lane-blocking only when its
# phase is currently green -- removing the red-queue false positive that plain
# CurrentStopTime carries. Fails OPEN (counts) only when the phase state is
# genuinely undeterminable (BusPhase/current_phase unknown).
MP_DWELL_REQUIRE_GREEN    = True   # gate dwelling on phase-is-green (see above)
MP_CORRIDOR_COORD_MODE    = False  # (2) enable downstream-corridor spillback discount
MP_CORRIDOR_COORD_WEIGHT  = 1.0    # strength of the downstream-storage discount [0..1]
MP_CORRIDOR_SAT_THRESHOLD = 0.6    # downstream sat-frac above which to discount

REWARD_FUTURE_HORIZON_CYCLES = 1.0  # lookahead horizon in cycle-length units
REWARD_FUTURE_DEBT_GAIN      = 0.35 # weight on projected unrecovered green debt
REWARD_FUTURE_OFFSET_GAIN    = 0.20 # weight on projected offset misalignment


def _log_func(self, msg: str, force: bool = False):
    """Call the module-level log_to_file if available."""
    try:
        log_to_file = getattr(self, '_module_log', None)
        if log_to_file is None:
            import inspect
            frame = inspect.currentframe()
            for _ in range(3):
                frame = frame.f_back if frame else None
            caller_globals = frame.f_globals if frame else {}
            log_to_file = caller_globals.get('log_to_file')
            if log_to_file is None:
                log_to_file = caller_globals.get('AKIPrintString')
            if log_to_file is None:
                log_to_file = lambda *a, **k: None
            self._module_log = log_to_file
        log_to_file(msg, force=force)
    except Exception:
        pass


def _safe_float(x, default=0.0):
    try: return float(x)
    except Exception: return default


def _milp_main_flow_state(self):
    """Return the main-flow gate inputs and a diagnostic reason."""
    state = {
        'shape': (),
        'main_flow': [],
        'max_flow': 0.0,
        'sat_flow': 0.0,
        'valid': False,
        'reason': 'unavailable',
    }
    try:
        upf = np.asarray(getattr(self, 'UpFlowList', np.zeros((0, 0))), dtype=float)
        state['shape'] = tuple(upf.shape)
        if upf.ndim < 2 or upf.shape[0] == 0 or upf.shape[1] == 0:
            state['reason'] = 'empty_flow_array'
            return state
        main_flow = upf[0]
        state['main_flow'] = [round(float(value), 3) for value in main_flow.ravel()]
        if not np.all(np.isfinite(main_flow)):
            state['reason'] = 'nonfinite_main_flow'
            return state
        max_flow = float(np.max(main_flow))
        sat_flow = max(float(getattr(self, 'SaturationFlow', 1800.0) or 1800.0), 1.0)
        state['max_flow'] = round(max_flow, 3)
        state['sat_flow'] = round(sat_flow, 3)
        if max_flow < float(MILP_MIN_MAIN_FLOW_VPH):
            state['reason'] = 'below_min_flow'
        elif max_flow > 1.5 * sat_flow:
            state['reason'] = 'above_safety_cap'
        else:
            state['valid'] = True
            state['reason'] = 'ok'
    except Exception:
        state['reason'] = 'flow_read_error'
    return state


def _milp_main_flow_is_valid(self):
    """Require usable main-approach flow before trusting the local scorer."""
    return bool(_milp_main_flow_state(self)['valid'])


def _shockwave_optimal_green_s(self, min_s: float = 5.0, max_s: float = 20.0) -> float:
    try:
        q_sat_vps = float(getattr(self, 'SaturationFlow', 1800)) / 3600.0
        k_jam     = float(getattr(self, 'JamDensity', 200.0))
        upf = np.asarray(getattr(self, 'UpFlowList', np.zeros((1,1))), dtype=float)
        rdt = np.asarray(getattr(self, 'RedDurationList', np.zeros((1,1))), dtype=float)
        if upf.ndim < 2 or upf.shape[0] == 0 or rdt.shape[0] == 0:
            return float(np.clip(10.0, min_s, max_s))
        upf_bus = upf[0].ravel()
        rdt_bus = rdt[0].ravel()
        pos_flow = upf_bus[upf_bus > 0.0]
        _cycle = float(getattr(self, 'config', {}).get('CycleTime', 135))
        pos_red = rdt_bus[(rdt_bus > 0.0) & (rdt_bus < 2.0 * _cycle)]
        q_arr_vph = float(np.mean(pos_flow)) if pos_flow.size > 0 else 0.0
        t_red_s   = float(np.max(pos_red))   if pos_red.size  > 0 else 30.0
        q_arr_vps = q_arr_vph / 3600.0
        k_arr  = q_arr_vps * k_jam / max(q_sat_vps, 1e-9)
        w_back = q_arr_vps / max(k_jam - k_arr, 1.0)
        N_q = max(0.0, w_back * t_red_s * k_jam)
        q_discharge = max(0.0, q_sat_vps - q_arr_vps)
        t_clear = (N_q / q_discharge) if q_discharge > 0.01 else float(max_s)
        return float(np.clip(t_clear, min_s, max_s))
    except Exception:
        return float(np.clip(10.0, min_s, max_s))


def _mainline_pax_saved_for_green(self, green_s):
    """Estimate mainline-car passenger-delay saved (pax·s) when `green_s`
    seconds of extra bus-phase green are provided.

    The bus phase serves every mainline vehicle on that approach, not just the
    bus.  Extra green discharges ~q_sat vehicles; each queued vehicle saves on
    average green_s/2 seconds of delay (triangular dissipation).  Previously
    only the bus was credited, so an action that clearly helped the whole
    approach looked like a net cost.

    NASH_MEASURED_STATE (2026-09-24): the analytic estimate assumes the main
    approach discharges at SATURATION for the whole extension, which over-credits
    an empty/low main phase. When on (or with MEASURED_QUEUE_FEED), bound the
    cleared vehicles by the MEASURED standing queue on the main approaches, so the
    transit-side payoff reflects the ACTUAL cars present -- an empty main phase
    then yields ~0 mainline benefit and the bargain won't extend it.
    """
    try:
        q_sat_vph = float(getattr(self, 'SaturationFlow', 1800))
        _car_occ = float(getattr(self, 'CarOcc', 1.6) if hasattr(self, 'CarOcc') else 1.6)
        g = max(0.0, float(green_s))
        q_sat_vps = q_sat_vph / 3600.0
        _cleared = q_sat_vps * g              # vehicles the extension could discharge
        if (bool(globals().get('NASH_MEASURED_STATE', False))
                or bool(globals().get('MEASURED_QUEUE_FEED', False))):
            _mq = None
            try:
                if hasattr(self, '_measured_main_queue_veh'):
                    _mq = self._measured_main_queue_veh()
            except Exception:
                _mq = None
            if _mq is not None and float(_mq) >= 0.0:
                _cleared = min(_cleared, float(_mq))
        return _cleared * (g / 2.0) * max(_car_occ, 0.0)
    except Exception:
        return 0.0


def _nash_phase_total_bps(self, action_type, param, bps_bus):
    """Transit-side bargaining payoff = ALL passengers served by the bus/through
    phase, not just the bus itself.

    The bus phase discharges every mainline vehicle on that approach, so holding
    or inserting its green saves the through-traffic passengers' delay too. The
    Nash controller must weigh that FULL phase benefit against the cross-street
    cost -- otherwise the surplus (bps - cpc) is bus-only and the p_T=0
    net-surplus outcome minimises BUS delay, not TOTAL passenger delay, which is
    the game's stated goal. `bps_bus` is the bus-only pax*s (from
    _dctsp_eval_action); we add the mainline through-traffic pax*s for the green-
    giving actions (GE/GREEN_REALLOC/INS*), matching the eligibility used when
    _dctsp_eval_action folds mainline into its own reward. EARLY_RED and the
    phase-cutting actions give the served phase nothing extra, so they get no
    mainline credit. Returns bus + mainline pax*s. (2026-09-19)

    IMPORTANT: this is ONLY the bargaining surplus term. The green-wave hand-off
    seconds used by the corridor coupling must stay bus-only (bps_bus / occ);
    callers derive that separately, never from this total.
    """
    _ml = 0.0
    if action_type in ('GE', 'GREEN_REALLOC', 'INS', 'INS_POST', 'INS_PRETERM'):
        try:
            _ml = max(0.0, float(_mainline_pax_saved_for_green(self, param)))
        except Exception:
            _ml = 0.0
    return max(0.0, float(bps_bus)) + _ml


def _compute_future_horizon_penalty(self, action_type, disturbance_s, cross_cost):
    if action_type in ('NO_ACTION',) or float(disturbance_s) <= 0.0:
        return 0.0
    try:
        _h_cycles = float(globals().get('REWARD_FUTURE_HORIZON_CYCLES', 1.0) or 1.0)
        _debt_gain = float(globals().get('REWARD_FUTURE_DEBT_GAIN', 0.35) or 0.35)
    except Exception:
        return 0.0
    _cycle_s = 135.0
    try:
        if hasattr(self, '_signal_cycle_s'):
            _cycle_s = max(30.0, float(self._signal_cycle_s()))
        else:
            _cfg = getattr(self, 'config', {}) or {}
            _cycle_s = max(30.0, float(_cfg.get('CycleTime', 135.0) or 135.0))
    except Exception:
        pass
    _disturb = max(float(disturbance_s), 1.0)
    _future_frac = min(1.0, (_disturb / _cycle_s) * _h_cycles)
    return _debt_gain * _future_frac * max(0.0, float(cross_cost))


def _dctsp_eval_action(self, action_type, param, sigma_in, no_act_delay,
                       bus_eta_s, wrong_phase=False, remaining_red_s=0.0):
    """Evaluate one candidate action, returning (reward, sigma_out, t_poz,
    bus_pax_saved_s, car_pax_cost_s, no_strategy_delay, strategy_delay)."""
    try:
        _occ = float(getattr(self, 'BusOcc', 40.0))
        _car_occ = float(getattr(self, 'CarOcc', 1.6) if hasattr(self, 'CarOcc') else 1.6)
    except Exception:
        _occ = 40.0; _car_occ = 1.6
    if action_type == 'NO_ACTION':
        sigma_out = sigma_in
        t_poz = 0.0
        bus_pax = max(0.0, float(no_act_delay)) * _occ
        car_pax = 0.0
        strategy_delay = bus_pax
        no_strategy_delay = bus_pax
        reward = -(bus_pax + car_pax)
        return (reward, sigma_out, t_poz, 0.0, 0.0, no_strategy_delay, strategy_delay)
    param = float(param)
    # _dctsp_cross_traffic_delay_s already returns pax·s (CarOcc and
    # NETWORK_FACTOR are applied inside it) — do NOT multiply again here.
    cross_cost = float(self._dctsp_cross_traffic_delay_s(param))
    if action_type in ('GE', 'GREEN_REALLOC'):
        if not bool(wrong_phase):
            bus_saved_s = max(0.0, float(no_act_delay) - max(0.0, float(no_act_delay) - param))
            if float(no_act_delay) <= param:
                bus_saved_s = float(no_act_delay)
            else:
                bus_saved_s = param
            bus_pax_saved = bus_saved_s * _occ
            sigma_out = max(0.0, sigma_in - bus_saved_s)
            t_poz = 0.0
        else:
            bus_pax_saved = -param * _occ
            sigma_out = sigma_in
            t_poz = 0.0
    elif action_type in ('INS', 'INS_POST', 'INS_PRETERM'):
        overhead = float(INS_INTERGREEN_S)
        if action_type == 'INS_POST':
            overhead += float(remaining_red_s)
        elif action_type in ('INS', 'INS_PRETERM'):
            overhead = overhead
            if action_type == 'INS_PRETERM':
                cross_cost += float(self._dctsp_cross_traffic_delay_s(
                    max(0.0, float(remaining_red_s) - float(INS_INTERGREEN_S))))
        bus_saved_s = max(0.0, float(no_act_delay) - overhead)
        eff_green = max(0.0, param - overhead)
        # The bus can only catch the inserted green window if it reaches the
        # stopline before that window closes.  A bus still `bus_eta_s` away
        # gets no benefit from an insertion that ends first — without this
        # ETA gate, INS_PRETERM_3 claimed bus_saved up to 54 500 pax·s (a
        # phantom ~1 300 s of delay from a 3 s action).
        if float(bus_eta_s) > (max(0.0, float(param)) + float(overhead)):
            bus_saved_s = 0.0
        elif eff_green > 0:
            bus_saved_s = min(bus_saved_s, float(no_act_delay))
        else:
            bus_saved_s = 0.0
        bus_pax_saved = bus_saved_s * _occ
        sigma_out = max(0.0, sigma_in - bus_saved_s)
        t_poz = 0.0
    elif action_type == 'EARLY_RED':
        # ER truncates the CURRENT phase by `param`.  On the active bus phase
        # (bus already cleared) it simply returns green to cross traffic — the
        # bus is not waiting, so there is no bus benefit and cross traffic is
        # HELPED (no extra red).  Only a wrong-phase ER (bus genuinely held on
        # a non-bus red) saves bus delay, and then only up to the actual
        # truncation `param`.  Previously `bus_saved_s = remaining_red * 0.5`
        # credited phantom savings (ER_5 showed bus_saved 460–1 113 pax·s)
        # that made the action look free and fired ~109 ER/run.
        if not bool(wrong_phase):
            bus_saved_s = 0.0
        else:
            bus_saved_s = min(max(0.0, float(param)),
                              max(0.0, float(remaining_red_s)))
            cross_cost += float(self._dctsp_cross_traffic_delay_s(
                max(0.0, float(remaining_red_s) - float(INS_INTERGREEN_S))))
        bus_pax_saved = bus_saved_s * _occ
        sigma_out = sigma_in
        t_poz = 0.0
    elif action_type == 'OFFSET_CORRECTION':
        # Offset correction shifts the phase boundary to ALIGN the bus-phase start
        # with the bus arrival (magnitude comes from _solve_offset_correction, not
        # a fixed grid). ADVANCE (negative param = shorten the current phase)
        # pulls the green earlier, so the bus recovers up to the advanced seconds,
        # capped by its no-action wait. RETARD (positive param) delays the bus
        # green and does NOT help a bus waiting for it, so it earns no bus benefit
        # (was a bogus 0.3*param that let retards fire for phantom savings, 2026-09-22).
        if param >= 0:
            bus_saved_s = 0.0
        else:
            bus_saved_s = max(0.0, min(abs(float(param)),
                                       max(0.0, float(no_act_delay))))
        bus_pax_saved = bus_saved_s * _occ
        sigma_out = max(0.0, sigma_in - bus_saved_s)
        t_poz = 0.0
        cross_cost += float(self._dctsp_cross_traffic_delay_s(abs(float(param))))
    elif action_type == 'PHASE_SKIP':
        bus_saved_s = max(0.0, float(param) * 0.8)
        bus_pax_saved = bus_saved_s * _occ
        sigma_out = max(0.0, sigma_in - bus_saved_s)
        t_poz = 0.0
        cross_cost += float(self._dctsp_cross_traffic_delay_s(float(param)))
    elif action_type == 'PHASE_ROTATION':
        bus_saved_s = max(0.0, float(param) * 0.6)
        bus_pax_saved = bus_saved_s * _occ
        sigma_out = max(0.0, sigma_in - bus_saved_s)
        t_poz = 0.0
        cross_cost += float(self._dctsp_cross_traffic_delay_s(float(param) * 0.7))
    else:
        bus_pax_saved = 0.0; sigma_out = sigma_in; t_poz = 0.0

    # Mainline-car benefit: the bus phase serves every mainline vehicle on that
    # approach, not just the bus.  Adding/inserting bus-phase green discharges
    # extra cars and relieves their queue, so credit that passenger-delay saving
    # (previously only the bus was counted, biasing every action toward NO_ACTION).
    if action_type in ('GE', 'GREEN_REALLOC', 'INS', 'INS_POST', 'INS_PRETERM'):
        mainline_pax_saved = _mainline_pax_saved_for_green(self, param)
    else:
        mainline_pax_saved = 0.0

    # ── Side-cost fallback (minimal configs with empty shockwave arrays) ──────
    # _dctsp_cross_traffic_delay_s returns 0 when UpFlowList is unpopulated (the
    # Logan minimal config), so EVERY phase-modifying action (PT/OC/GR/VP/ER/
    # INS_PRETERM/…) came out with cross_cost=0.  The weight-free Pareto layer
    # then fired hundreds of them "for free" (589 phase rotations/early-reds per
    # run), disrupting the fixed-time plan and making buses SLOWER than NO_TSP.
    # Any action that saves bus time does so by taking green from cross traffic,
    # so it must carry a cost: estimate it from live side-section vehicle counts,
    # the same mechanism GE/INS use in _reward_evaluate_ge/_reward_evaluate_insertion.
    # The gate was `cross_cost < 1.0`, but the analytic path routinely returns
    # a small non-zero value (e.g. 13 pax·s) that masked the fact the real side
    # cost is ~0, so the live-count fallback never fired and ER_5 was priced
    # at ~free.  Apply it whenever an action claims a bus benefit: take the
    # MAX so the measured side cost always binds (never less than analytic).
    if bus_pax_saved > 0.0:
        _eff_red = {
            'GE': param, 'GREEN_REALLOC': param,
            'INS': param + float(INS_INTERGREEN_S),
            'INS_POST': param + float(INS_INTERGREEN_S) + max(0.0, float(remaining_red_s)),
            'INS_PRETERM': param + float(INS_INTERGREEN_S),
            'OFFSET_CORRECTION': abs(param),
            'PHASE_SKIP': param,
            'PHASE_ROTATION': param * 0.7,
            'EARLY_RED': max(0.0, float(remaining_red_s) - float(INS_INTERGREEN_S)),
        }.get(action_type, param)
        try:
            _sd, _ = self._compute_side_delay_penalty(max(0.0, _eff_red),
                                                      _suppress_log=True)
            cross_cost = max(cross_cost, max(0.0, float(_sd)))
        except Exception:
            pass

    no_strategy_delay = max(0.0, float(no_act_delay)) * _occ
    strategy_delay = max(0.0, no_strategy_delay - bus_pax_saved)
    # Weighted-objective reward: Z1 (delay) · Z2 (progression) · Z3 (headway)
    _walpha = float(globals().get('WOBJ_ALPHA', 1.0))
    _wbeta  = float(globals().get('WOBJ_BETA', 0.0))
    _wgamma = float(globals().get('WOBJ_GAMMA', 0.0))
    # CPD-QL / MARL blend (backwards-compatible): DCTSP_W_H is the headway
    # share — pax-delay weight = (1 - W_H), headway weight = W_H on top of the
    # WOBJ_GAMMA lateness term.  DCTSP_CAR_WEIGHT scales the cross-traffic
    # cost.  Absent keys (None) fall back to pure WOBJ_* behaviour.
    _wh = globals().get('DCTSP_W_H')
    if _wh is not None:
        _wh = float(_wh)
        _walpha = _walpha * max(0.0, 1.0 - _wh)
        _wgamma = _wgamma + _wh
    _cw = globals().get('DCTSP_CAR_WEIGHT')
    _cw = 1.0 if _cw is None else float(_cw)
    _sigma_s = max(float(sigma_in), 0.0)
    _lateness_factor = min(_sigma_s / 30.0, 3.0)
    _eff_bus_w  = _walpha + _wgamma * _lateness_factor
    _eff_cross_w = (1.0 + _wbeta) * max(_cw, 0.0)
    reward = _eff_bus_w * (bus_pax_saved + mainline_pax_saved) - _eff_cross_w * cross_cost
    _horizon_penalty = _compute_future_horizon_penalty(
        self, action_type, float(param), cross_cost)
    reward -= _horizon_penalty
    return (reward, sigma_out, t_poz, bus_pax_saved, cross_cost,
            no_strategy_delay, strategy_delay)


def dctsp_zig(self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
              no_act_delay, sigma_in, remaining_red_s=0.0):
    eff_delay = max(0.0, float(no_act_delay) - float(ZIG_PHASE_OVERLAP_S))
    t_sw = _shockwave_optimal_green_s(self,
        min_s=float(DCTSP_MIN_INS_DURATION_S),
        max_s=float(DCTSP_MAX_INS_DURATION_S))
    _wrong_phase = (current_phase != self.BusPhase)
    _cycle_s = float(self._signal_cycle_s()) if hasattr(self, '_signal_cycle_s') else float(self.config.get('CycleTime', 135.0) or 135.0)
    _max_d = max(_cycle_s - float(getattr(self, 'BusPhaseDuration', 20)), 0.0)
    _miss_by = max(0.0, _max_d - float(no_act_delay))
    t_ge = float(np.clip(_miss_by + t_sw,
                          float(DCTSP_MIN_INS_DURATION_S),
                          float(MAX_GE_EXTENSION_S)))
    rows = []
    r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
        self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
    rows.append(('NO_ACTION', 0.0, r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na))
    if not _wrong_phase and ZIG_ENABLE_GE:
        r_ge, so_ge, tp_ge, bps_ge, cpc_ge, nsd_ge, std_ge = _dctsp_eval_action(
            self, 'GE', t_ge, sigma_in, no_act_delay, bus_eta_s, wrong_phase=False)
        rows.append((f'GE_{t_ge:.0f}', t_ge, r_ge, so_ge, tp_ge, bps_ge, cpc_ge, nsd_ge, std_ge))
    if ZIG_ENABLE_INS:
        r_ip, so_ip, tp_ip, bps_ip, cpc_ip, nsd_ip, std_ip = _dctsp_eval_action(
            self, 'INS_POST', t_sw, sigma_in, no_act_delay, bus_eta_s, remaining_red_s=remaining_red_s)
        rows.append((f'INS_POST_{t_sw:.0f}', t_sw, r_ip, so_ip, tp_ip, bps_ip, cpc_ip, nsd_ip, std_ip))
        r_ipt, so_ipt, tp_ipt, bps_ipt, cpc_ipt, nsd_ipt, std_ipt = _dctsp_eval_action(
            self, 'INS_PRETERM', t_sw, sigma_in, no_act_delay, bus_eta_s, remaining_red_s=remaining_red_s)
        rows.append((f'INS_PRETERM_{t_sw:.0f}', t_sw, r_ipt, so_ipt, tp_ipt, bps_ipt, cpc_ipt, nsd_ipt, std_ipt))
        for _zi_dur in [10.0, 15.0, 20.0, 25.0]:
            _zi_dur = float(np.clip(_zi_dur, float(DCTSP_MIN_INS_DURATION_S), float(DCTSP_MAX_INS_DURATION_S)))
            r_zi, so_zi, tp_zi, bps_zi, cpc_zi, nsd_zi, std_zi = _dctsp_eval_action(
                self, 'INS', _zi_dur, sigma_in, no_act_delay, bus_eta_s)
            rows.append((f'INS_{_zi_dur:.0f}', _zi_dur, r_zi, so_zi, tp_zi, bps_zi, cpc_zi, nsd_zi, std_zi))
    if _wrong_phase and ZIG_ENABLE_SEQ:
        r_er, so_er, tp_er, bps_er, cpc_er, nsd_er, std_er = _dctsp_eval_action(
            self, 'EARLY_RED', t_sw, sigma_in, no_act_delay, bus_eta_s, remaining_red_s=remaining_red_s)
        rows.append((f'ER_{t_sw:.0f}', t_sw, r_er, so_er, tp_er, bps_er, cpc_er, nsd_er, std_er))
    best_lbl, best_param = 'NO_ACTION', 0.0
    best_r, best_so, best_tp = r_na, so_na, tp_na
    for (lbl, par, r, so, tp, *_) in rows:
        if r > best_r:
            best_r = r; best_lbl = lbl; best_param = par; best_so = so; best_tp = tp
    best_type = (best_lbl if '_' not in best_lbl
                 else ('GE' if best_lbl.startswith('GE_') else
                       'INS_POST' if best_lbl.startswith('INS_POST_') else
                       'INS_PRETERM' if best_lbl.startswith('INS_PRETERM_') else
                       'INS' if best_lbl.startswith('INS_') else
                       'EARLY_RED' if best_lbl.startswith('ER_') else best_lbl))
    best_r_delta = best_r - r_na
    if eff_delay < float(SELFORG_MIN_BUS_DELAY_S):
        pass
    else:
        try:
            if best_type != 'NO_ACTION':
                _best_row = next((r for r in rows if r[0] == best_lbl), None)
                _best_saved = float(_best_row[5]) if _best_row else 1.0
                _best_cost = float(_best_row[6]) if _best_row else 0.0
                _zig_ratio = _best_cost / max(_best_saved, 1.0)
            else:
                _zig_ratio = 0.0
        except Exception:
            _zig_ratio = 0.0
        # GE is a small same-phase intervention: tolerate a higher cross-street
        # cost ratio for extensions than for (disruptive) insertions.
        _gate_factor = (float(ZIG_GE_BALANCE_FACTOR) if best_type == 'GE'
                        else float(ZIG_BALANCE_FACTOR))
        if _zig_ratio > _gate_factor:
            best_type = 'NO_ACTION'; best_param = 0.0
            best_r = r_na; best_r_delta = 0.0; best_so = so_na; best_tp = tp_na
    return (best_type, best_param, best_r, best_r_delta, best_so, best_tp, rows)


def dctsp_milp_tsp(self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
                   no_act_delay, sigma_in, remaining_red_s=0.0):
    """Choose one evaluated TSP action with a binary MILP objective."""
    flow_state = _milp_main_flow_state(self)
    if not getattr(self, '_milp_flow_diag_logged', False):
        self._milp_flow_diag_logged = True
        _log_func(
            self,
            f"[MILP GATE] inter={getattr(self, 'id', '?')} "
            f"shape={flow_state['shape']} main_flow={flow_state['main_flow']} "
            f"max={flow_state['max_flow']:.3f} sat={flow_state['sat_flow']:.3f} "
            f"min={float(MILP_MIN_MAIN_FLOW_VPH):.3f} "
            f"updet={len(getattr(self, 'UpDetList', []))} "
            f"incoming={len(getattr(self, 'incoming_sections', []))} "
            f"require={bool(MILP_REQUIRE_MAIN_FLOW)} "
            f"valid={flow_state['valid']} reason={flow_state['reason']}",
            force=True)
    if bool(MILP_REQUIRE_MAIN_FLOW) and not flow_state['valid']:
        return ('NO_ACTION', 0.0, 0.0, 0.0, 0.0, 0.0, [])
    wrong_phase = (current_phase != self.BusPhase)
    candidates = [('NO_ACTION', 0.0)]
    if wrong_phase:
        for action_type in ('INS_POST', 'INS_PRETERM'):
            candidates.extend((action_type, duration)
                              for duration in (10.0, 15.0, 20.0))
        candidates.extend(('EARLY_RED', duration) for duration in (5.0, 10.0))
    else:
        candidates.extend(('GE', duration) for duration in (5.0, 10.0, 15.0))
        candidates.extend(('GREEN_REALLOC', duration)
                           for duration in (5.0, 10.0, 15.0))

    rows = []
    eval_errors = []
    for action_type, parameter in candidates:
        try:
            _, sigma_out, t_poz, bus_saved, cross_cost, no_strategy_delay, strategy_delay = _dctsp_eval_action(
                self, action_type, parameter, sigma_in, no_act_delay, bus_eta_s,
                wrong_phase=wrong_phase, remaining_red_s=remaining_red_s)
        except Exception:
            continue
        bus_saved = max(0.0, float(bus_saved))
        cross_cost = max(0.0, float(cross_cost))
        score = (float(MILP_BUS_WEIGHT) * bus_saved
                 - float(MILP_CROSS_WEIGHT) * cross_cost)
        rows.append((action_label(action_type, parameter), action_type, parameter,
                     score, sigma_out, t_poz, bus_saved, cross_cost,
                     no_strategy_delay, strategy_delay))

    if not rows:
        return ('NO_ACTION', 0.0, 0.0, 0.0, 0.0, 0.0, [])

    chosen_index = max(range(len(rows)), key=lambda index: rows[index][3])
    solver_status = 'greedy'
    try:
        from scipy.optimize import Bounds, LinearConstraint, milp
        objective = -np.asarray([row[3] for row in rows], dtype=float)
        result = milp(
            c=objective,
            integrality=np.ones(len(rows)),
            bounds=Bounds(0.0, 1.0),
            constraints=LinearConstraint(
                np.ones((1, len(rows))), 1.0, 1.0),
            options={'time_limit': max(0.01, float(MILP_TIME_LIMIT_S))})
        if result.success and result.x is not None:
            chosen_index = int(np.argmax(result.x))
            solver_status = 'scipy_success'
        else:
            solver_status = f"scipy_failed:{getattr(result, 'status', '?')}"
    except Exception as error:
        solver_status = f"solver_error:{type(error).__name__}"
        if not getattr(self, '_milp_solver_diag_logged', False):
            self._milp_solver_diag_logged = True
            _log_func(
                self,
                f"[MILP SOLVER] inter={getattr(self, 'id', '?')} "
                f"status={solver_status} error={error!r}",
                force=True)

    chosen = rows[chosen_index]
    _, chosen_type, chosen_parameter, chosen_score, sigma_out, t_poz, bus_saved, cross_cost, no_strategy_delay, strategy_delay = chosen
    if not getattr(self, '_milp_candidate_diag_logged', False):
        self._milp_candidate_diag_logged = True
        _log_func(
            self,
            f"[MILP CANDIDATES] inter={getattr(self, 'id', '?')} "
            f"rows={len(rows)}/{len(candidates)} positive="
            f"{sum(row[3] > 0.0 for row in rows)} "
            f"score_min={min(row[3] for row in rows):.3f} "
            f"score_max={max(row[3] for row in rows):.3f} "
            f"chosen={action_label(chosen_type, chosen_parameter)} "
            f"chosen_score={chosen_score:.3f} solver={solver_status} "
            f"eval_errors={eval_errors}",
            force=True)
    public_rows = [
        (label, parameter, score, row_sigma, row_t_poz, row_bus_saved,
         row_cross_cost, row_no_strategy_delay, row_strategy_delay)
        for (label, _, parameter, score, row_sigma, row_t_poz, row_bus_saved,
             row_cross_cost, row_no_strategy_delay, row_strategy_delay) in rows
    ]
    return (chosen_type, chosen_parameter, chosen_score,
            chosen_score - rows[0][3], sigma_out, t_poz, public_rows)


def dctsp_centralised(self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
                      no_act_delay, sigma_in, remaining_red_s=0.0):
    """CENTRALISED corridor controller (Method 0 in the paper).

    The perfect-information baseline.  Unlike the decentralised learners /
    bargainers, this controller assumes it knows the exact bus positions/ETAs
    (read from the Aimsun PT trackers, no prediction uncertainty) and optimises
    the CORRIDOR passenger objective — the delay of the triggering bus AND every
    other oncoming bus this action would also serve — choosing DETERMINISTICALLY
    (no learning, no exploration, no epsilon).  Decision structure per the paper:

      * NO_ACTION  — the bus is not meaningfully delayed, or is unreachable this
                     cycle (outside cycle + margin).
      * HOLD       — bus is running WITH the green: extend it (GE / GREEN_REALLOC)
                     so the corridor platoon clears.
      * TRANSITION — bus is held on red: advance the bus phase (INS_POST /
                     INS_PRETERM / EARLY_RED) to bring the green forward.

    The cross-street cost is priced directly from the shockwave side model and
    traded off pax·s-for-pax·s.  With perfect information there is no learned Q to
    veto, so the corridor benefit (summed over all served buses) minus the cross
    cost is the objective and the argmax is taken directly.
    """
    _bus_occ = max(float(getattr(self, 'BusOcc', 40.0) or 40.0), 1.0)
    _overlap = float(globals().get('ZIG_PHASE_OVERLAP_S', 0.0) or 0.0)
    eff_delay = max(0.0, float(no_act_delay) - _overlap)
    wrong_phase = (int(current_phase) != int(self.BusPhase))
    _cycle_s = (float(self._signal_cycle_s()) if hasattr(self, '_signal_cycle_s')
                else float(self.config.get('CycleTime', 135.0) or 135.0))
    _margin = float(globals().get('CENTRALISED_REACH_MARGIN_S', 5.0))

    # ── NO_ACTION baseline row ──
    (_r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na) = _dctsp_eval_action(
        self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s,
        wrong_phase=wrong_phase, remaining_red_s=remaining_red_s)
    rows = [('NO_ACTION', 0.0, 0.0, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na)]

    # ── Corridor multi-bus factor: perfect knowledge of every oncoming bus this
    #    junction will serve within the reachable window (>=1.0). ──
    _mb = 1.0
    try:
        _cc = getattr(self, '_corridor_coord', None)
        if _cc is not None:
            _onc = _cc.oncoming_buses(self.id, time, max_eta_s=_cycle_s + _margin)
            if _onc:
                _tot_occ = sum(float(o[2]) for o in _onc)
                _mb = max(1.0, _tot_occ / _bus_occ)
    except Exception:
        _mb = 1.0

    # ── Rule gate: only intervene for a genuinely-delayed, reachable bus ──
    _min_delay = float(globals().get('CENTRALISED_MIN_BUS_DELAY_S', 5.0))
    _reachable = (float(bus_eta_s) <= _cycle_s + _margin)
    if eff_delay < _min_delay or not _reachable:
        return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)

    # ── Candidate actions per phase state (HOLD vs TRANSITION) ──
    if wrong_phase:
        candidates = [('INS_POST', d) for d in (10.0, 15.0, 20.0)]
        candidates += [('INS_PRETERM', d) for d in (10.0, 15.0, 20.0)]
        candidates += [('EARLY_RED', d) for d in (5.0, 10.0)]
    else:
        candidates = [('GE', d) for d in (5.0, 10.0, 15.0)]
        candidates += [('GREEN_REALLOC', d) for d in (5.0, 10.0, 15.0)]

    best_type, best_param = 'NO_ACTION', 0.0
    best_so, best_tp = so_na, tp_na
    best_score = 0.0   # must strictly beat doing nothing
    for atype, param in candidates:
        try:
            (_r, sigma_out, t_poz, bus_saved, cross_cost,
             no_strategy_delay, strategy_delay) = _dctsp_eval_action(
                self, atype, param, sigma_in, no_act_delay, bus_eta_s,
                wrong_phase=wrong_phase, remaining_red_s=remaining_red_s)
        except Exception:
            continue
        bus_saved = max(0.0, float(bus_saved))
        cross_cost = max(0.0, float(cross_cost))
        # Corridor objective: bus pax·s saved (summed over the oncoming platoon)
        # minus the cross-street pax·s cost.  Perfect info -> direct trade-off.
        score = _mb * bus_saved - cross_cost
        rows.append((action_label(atype, param), param, score, sigma_out, t_poz,
                     bus_saved, cross_cost, no_strategy_delay, strategy_delay))
        if score > best_score:
            best_score = score
            best_type, best_param = atype, param
            best_so, best_tp = sigma_out, t_poz

    _log_func(
        self,
        f"[CENTRALISED] inter={getattr(self, 'id', '?')} t={time:.1f} bus={veh_id} "
        f"phase={'RED' if wrong_phase else 'GREEN'} eff_delay={eff_delay:.1f}s "
        f"eta={bus_eta_s:.1f}s cycle={_cycle_s:.0f}s mb={_mb:.2f} "
        f"chosen={action_label(best_type, best_param)} score={best_score:.0f}paxs")
    return (best_type, best_param, best_score, best_score - 0.0,
            best_so, best_tp, rows)


def dctsp_mp_ectm(self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
                  no_act_delay, sigma_in, remaining_red_s=0.0):
    dt = float(MP_ECTM_DT_S)
    q_sat_vps = float(getattr(self, 'SaturationFlow', 1800.0)) / 3600.0
    k_jam = float(getattr(self, 'JamDensity', 200.0))
    _bus_occ = float(getattr(self, 'BusOcc', 40.0))
    _cycle_s = float(self._signal_cycle_s()) if hasattr(self, '_signal_cycle_s') else float(self.config.get('CycleTime', 135.0) or 135.0)
    _bus_g_base = float(getattr(self, 'BusPhaseDuration', 20.0))
    _wrong_phase = (int(current_phase) != int(self.BusPhase))
    _car_occ = float(MP_ECTM_CAR_OCC)
    try:
        upf = np.asarray(getattr(self, 'UpFlowList', np.zeros((1,1))), dtype=float)
        rdt = np.asarray(getattr(self, 'RedDurationList', np.zeros((1,1))), dtype=float)
        upf_bus = upf[0].ravel() if upf.ndim >= 2 and upf.shape[0] > 0 else np.zeros(1)
        rdt_bus = rdt[0].ravel() if rdt.ndim >= 2 and rdt.shape[0] > 0 else np.zeros(1)
        pos_flow = upf_bus[upf_bus > 0.0]
        pos_red = rdt_bus[(rdt_bus > 0.0) & (rdt_bus < 2.0 * _cycle_s)]
        q_arr_bus_vps = (float(np.mean(pos_flow)) / 3600.0 if pos_flow.size > 0 else 300.0 / 3600.0)
        t_red_past = (float(np.max(pos_red)) if pos_red.size > 0 else 60.0)
        k_arr_b = q_arr_bus_vps * k_jam / max(q_sat_vps, 1e-9)
        w_back_b = q_arr_bus_vps / max(k_jam - k_arr_b, 1.0)
        n0_bus = max(0.0, w_back_b * t_red_past * k_jam)
    except Exception:
        q_arr_bus_vps = 300.0 / 3600.0
        n0_bus = 5.0
    _cap_veh = k_jam * 0.15
    # ── Passenger weighting for the approach cell ────────────────────────────
    # `n0_bus` is the LWR/shockwave estimate of the WHOLE approach queue in
    # vehicles and `q_arr_bus_vps` is the WHOLE approach flow -- neither is
    # bus-only -- so passing `_bus_occ` (40 pax/veh) into _ctm_delay_pax priced
    # every queued car as a 40-passenger bus (~16x overstatement).  Same defect
    # fixed in dctsp_bxt, where it drove constant max-length extensions and
    # gridlocked kg seeds 400/500.  Weight the cell by what it holds: the
    # subject bus at BusOcc, the remaining queue at CarOcc.
    _n_cell = max(float(n0_bus), 1.0)
    _cell_occ = ((min(1.0, _n_cell) * _bus_occ
                  + max(0.0, _n_cell - 1.0) * float(_car_occ)) / _n_cell)

    def _ctm_delay_pax(n0, q_arr, q_sat, t_wait, g_dur, occ):
        delay = 0.0; n = max(0.0, float(n0))
        for _ in range(max(0, int(round(float(t_wait) / dt)))):
            n = min(n + q_arr * dt, _cap_veh); delay += n * dt
        for _ in range(max(0, int(round(float(g_dur) / dt)))):
            q_out = min(q_sat, n / max(dt, 1e-9))
            n = max(0.0, n + q_arr * dt - q_out * dt); delay += n * dt
        return delay * float(occ)
    if _wrong_phase:
        _t_wait_na = float(remaining_red_s); _g_bus_na = _bus_g_base
    else:
        _t_wait_na = 0.0; _g_bus_na = float(remaining_red_s)
    # ETA correction: a bus still `bus_eta_s` away has NOT been waiting the full
    # remaining red — it only accrues delay from the moment it reaches the
    # stopline.  Without this, a bus 18 s out was treated as already queued and
    # every action's bus benefit was massively inflated (INS_PRETERM_3 showed
    # bus_saved 21k–54k pax·s for a 3 s action).
    _eta = max(0.0, float(bus_eta_s))
    d_bus_na = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                              max(0.0, _t_wait_na - _eta), _g_bus_na, _cell_occ)
    # _dctsp_cross_traffic_delay_s returns pax·s (occupancy applied inside)
    d_side_na = float(self._dctsp_cross_traffic_delay_s(0.0))
    z_na = d_bus_na + d_side_na
    _d_min = float(MP_ECTM_MIN_EXT_S); _d_max = float(MP_ECTM_MAX_EXT_S)
    _d_step = float(dt)
    best_z = z_na; best_delta = 0.0; best_atype = 'NO_ACTION'
    best_d_bus = d_bus_na; best_d_side = d_side_na
    _sweep_evals = []   # (atype, delta, d_bus, d_side) — the FULL CTM grid
    for _d_raw in np.arange(_d_min, _d_max + _d_step * 0.5, _d_step):
        delta = float(_d_raw)
        if not _wrong_phase:
            d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps, 0.0, float(remaining_red_s) + delta, _cell_occ)
            d_side = float(self._dctsp_cross_traffic_delay_s(delta))
            z_ge = d_bus + d_side
            _sweep_evals.append(('GE', delta, d_bus, d_side))
            if z_ge < best_z:
                best_z = z_ge; best_delta = delta; best_atype = 'GE'
                best_d_bus = d_bus; best_d_side = d_side
        else:
            t_wait_post = float(remaining_red_s) + float(INS_INTERGREEN_S)
            d_bus_post = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                        max(0.0, t_wait_post - _eta), delta, _cell_occ)
            d_side_post = float(self._dctsp_cross_traffic_delay_s(t_wait_post + delta))
            z_post = d_bus_post + d_side_post
            _sweep_evals.append(('INS_POST', delta, d_bus_post, d_side_post))
            if z_post < best_z:
                best_z = z_post; best_delta = delta; best_atype = 'INS_POST'
                best_d_bus = d_bus_post; best_d_side = d_side_post
            _cut = max(0.0, float(remaining_red_s) - float(INS_INTERGREEN_S))
            d_bus_pt = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                      max(0.0, float(INS_INTERGREEN_S) - _eta),
                                      delta, _cell_occ)
            d_side_pt = (float(self._dctsp_cross_traffic_delay_s(float(INS_INTERGREEN_S) + delta))
                         + float(self._dctsp_cross_traffic_delay_s(_cut)))
            z_pt = d_bus_pt + d_side_pt
            _sweep_evals.append(('INS_PRETERM', delta, d_bus_pt, d_side_pt))
            if z_pt < best_z:
                best_z = z_pt; best_delta = delta; best_atype = 'INS_PRETERM'
                best_d_bus = d_bus_pt; best_d_side = d_side_pt
    eff_delay = max(0.0, float(no_act_delay) - float(ZIG_PHASE_OVERLAP_S))
    _satur_override = False
    if eff_delay < float(SELFORG_MIN_BUS_DELAY_S):
        best_atype = 'NO_ACTION'; best_delta = 0.0; _satur_override = True
    else:
        try:
            _o_d = _safe_float(self._safe_array_sum(getattr(self, 'OtherDelay', [0]))) + \
                   _safe_float(self._safe_array_sum(getattr(self, 'SideDelayBaseline', [0])))
            _bus_p = eff_delay * _bus_occ
            _side_p = max(0.0, _o_d) * _car_occ
            _ratio = _side_p / max(_bus_p, 1.0)
        except Exception:
            _ratio = 0.0
        _gate_factor = (float(MP_ECTM_GE_BALANCE_FACTOR) if best_atype == 'GE'
                        else float(MP_ECTM_BALANCE_FACTOR))
        if _ratio > _gate_factor:
            best_atype = 'NO_ACTION'; best_delta = 0.0; _satur_override = True
    r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
        self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
    rows = [('NO_ACTION', 0.0, r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na)]
    # Emit the FULL CTM grid sweep, not just the argmin: each (type, delta)
    # carries the CTM model's own objective vector, so the shared Pareto layer
    # can genuinely distinguish CTMGS's model trade-off from the standard
    # kinematic candidates.  Emitting only the argmin collapsed the mode onto
    # the standard pool (the single CTM row was almost always dominated).
    best_r = r_na; best_so = so_na; best_tp = tp_na; best_r_delta = 0.0
    if not _satur_override:
        for (at, delta, d_bus, d_side) in _sweep_evals:
            # The candidate's objective vector comes from the CTM model ITSELF —
            # re-scoring through _dctsp_eval_action (as before) collapsed ECTM's
            # rows onto the same kinematic vectors ZIG produces, so the shared
            # Pareto layer could never distinguish the two modes.
            try:
                _, so_act, tp_act, _, _, nsd_act, std_act = _dctsp_eval_action(
                    self, at, delta, sigma_in, no_act_delay, bus_eta_s,
                    wrong_phase=_wrong_phase, remaining_red_s=remaining_red_s)
            except Exception:
                so_act, tp_act, nsd_act, std_act = so_na, tp_na, nsd_na, std_na
            bps_ctm = max(0.0, d_bus_na - d_bus)     # CTM bus pax·s saved
            # Cap the claimed savings by the bus's ACTUAL no-action delay: the CTM
            # queue model can still over-credit a short green window when n0_bus is
            # large (INS_PRETERM_3 once claimed 62 000 pax·s ≈ 1 550 s from a 3 s
            # action), so the claimed bus time can never exceed what the bus
            # actually loses without action.  Keeps the CTM vector identity.
            bps_ctm = min(bps_ctm, max(0.0, float(no_act_delay)) * _bus_occ)
            cpc_ctm = max(0.0, d_side - d_side_na)   # CTM side pax·s added
            # Same zero-cost fallback as _dctsp_eval_action: in the minimal config
            # the CTM d_side terms are 0 (empty shockwave arrays), so cost the
            # insertion from live side-section vehicles instead — otherwise ECTM's
            # candidate looks free and the mode behaves identically to the base path.
            # Gate was `cpc_ctm < 1.0`, but the analytic path returns a small
            # non-zero value that masked the true ~0 side cost; use MAX so the
            # live-count side cost binds whenever a bus benefit is claimed.
            if bps_ctm > 0.0:
                try:
                    _ectm_red = float(delta) + float(INS_INTERGREEN_S)
                    _sd, _ = self._compute_side_delay_penalty(_ectm_red, _suppress_log=True)
                    cpc_ctm = max(cpc_ctm, max(0.0, float(_sd)))
                except Exception:
                    pass
            r_ctm   = bps_ctm - cpc_ctm
            rows.append((f'{at}_{delta:.0f}', delta,
                         r_ctm, so_act, tp_act, bps_ctm, cpc_ctm, nsd_act, std_act))
            if at == best_atype and abs(delta - best_delta) < 1e-6:
                best_r = r_ctm; best_so = so_act; best_tp = tp_act
                best_r_delta = r_ctm - r_na
    return (best_atype, best_delta, best_r, best_r_delta, best_so, best_tp, rows)


# ── Mode: MP_ECTM_DP — CTMGS grid + downstream DP coordination look-ahead ──────
# Hybrid Method III: the same exhaustive CTM grid sweep over [MIN_EXT, MAX_EXT]
# as dctsp_mp_ectm, but each candidate also carries a CELLQLEARN-style DP
# coordination penalty: the projected downstream-junction delay (bus + side
# cross-traffic) over the bus-trajectory horizon, geometrically discounted by
# MP_ECTM_DP_COORD_WEIGHT.  This counters CTMGS' myopia — an extension/insertion
# that locally helps the bus but burns cross-street green further along the
# corridor now scores worse.

def dctsp_mp_ectm_dp(self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
                     no_act_delay, sigma_in, remaining_red_s=0.0):
    dt = float(MP_ECTM_DT_S)
    q_sat_vps = float(getattr(self, 'SaturationFlow', 1800.0)) / 3600.0
    k_jam = float(getattr(self, 'JamDensity', 200.0))
    _bus_occ = float(getattr(self, 'BusOcc', 40.0))
    _cycle_s = float(self._signal_cycle_s()) if hasattr(self, '_signal_cycle_s') else float(self.config.get('CycleTime', 135.0) or 135.0)
    _bus_g_base = float(getattr(self, 'BusPhaseDuration', 20.0))
    _wrong_phase = (int(current_phase) != int(self.BusPhase))
    _car_occ = float(MP_ECTM_CAR_OCC)
    try:
        upf = np.asarray(getattr(self, 'UpFlowList', np.zeros((1,1))), dtype=float)
        rdt = np.asarray(getattr(self, 'RedDurationList', np.zeros((1,1))), dtype=float)
        upf_bus = upf[0].ravel() if upf.ndim >= 2 and upf.shape[0] > 0 else np.zeros(1)
        rdt_bus = rdt[0].ravel() if rdt.ndim >= 2 and rdt.shape[0] > 0 else np.zeros(1)
        pos_flow = upf_bus[upf_bus > 0.0]
        pos_red = rdt_bus[(rdt_bus > 0.0) & (rdt_bus < 2.0 * _cycle_s)]
        q_arr_bus_vps = (float(np.mean(pos_flow)) / 3600.0 if pos_flow.size > 0 else 300.0 / 3600.0)
        t_red_past = (float(np.max(pos_red)) if pos_red.size > 0 else 60.0)
        k_arr_b = q_arr_bus_vps * k_jam / max(q_sat_vps, 1e-9)
        w_back_b = q_arr_bus_vps / max(k_jam - k_arr_b, 1.0)
        n0_bus = max(0.0, w_back_b * t_red_past * k_jam)
    except Exception:
        q_arr_bus_vps = 300.0 / 3600.0
        n0_bus = 5.0
    _cap_veh = k_jam * 0.15
    # ── Passenger weighting for the approach cell ────────────────────────────
    # `n0_bus` is the LWR/shockwave estimate of the WHOLE approach queue in
    # vehicles and `q_arr_bus_vps` is the WHOLE approach flow -- neither is
    # bus-only -- so passing `_bus_occ` (40 pax/veh) into _ctm_delay_pax priced
    # every queued car as a 40-passenger bus (~16x overstatement).  Same defect
    # fixed in dctsp_bxt, where it drove constant max-length extensions and
    # gridlocked kg seeds 400/500.  Weight the cell by what it holds: the
    # subject bus at BusOcc, the remaining queue at CarOcc.
    _n_cell = max(float(n0_bus), 1.0)
    _cell_occ = ((min(1.0, _n_cell) * _bus_occ
                  + max(0.0, _n_cell - 1.0) * float(_car_occ)) / _n_cell)

    def _ctm_delay_pax(n0, q_arr, q_sat, t_wait, g_dur, occ):
        delay = 0.0; n = max(0.0, float(n0))
        for _ in range(max(0, int(round(float(t_wait) / dt)))):
            n = min(n + q_arr * dt, _cap_veh); delay += n * dt
        for _ in range(max(0, int(round(float(g_dur) / dt)))):
            q_out = min(q_sat, n / max(dt, 1e-9))
            n = max(0.0, n + q_arr * dt - q_out * dt); delay += n * dt
        return delay * float(occ)
    # ── DP coordination look-ahead: projected downstream delay over the
    # bus-trajectory horizon, discounted per stage by COORD_WEIGHT. ─────────
    _dp_horizon = float(MP_ECTM_DP_HORIZON_S)
    _dp_stage   = float(MP_ECTM_DP_STAGE_S)
    _coord_w    = float(MP_ECTM_DP_COORD_WEIGHT)
    # Real accumulated side-red at the current junction: the longest red being
    # held across non-bus phases becomes the cross-approach queue elapsed, so
    # the projected side cost is grounded in actual queue state (not 0).
    try:
        _rdt_all = np.asarray(getattr(self, 'RedDurationList', np.zeros((1, 1))), dtype=float)
        _side_red_elapsed = float(np.max(_rdt_all)) if _rdt_all.size else float(remaining_red_s)
    except Exception:
        _side_red_elapsed = float(remaining_red_s)
    _side_red_elapsed = max(0.0, min(_side_red_elapsed, 2.0 * _cycle_s))
    def _dp_proj_side_delay(_sr):
        """Real side-queue pax·s imposed by EXTRA red `_sr`: uses the live
        SideUpFlowList/SideUpDenList shockwave model when available (grounded
        in actual accumulated side queue), else the analytic cross model.
        Scaled by CROSS_TRAFFIC_COST_MULTIPLIER so it competes with the
        primary CTM terms (the analytic path already applies that factor)."""
        _cmult = float(CROSS_TRAFFIC_COST_MULTIPLIER or 2.0)
        try:
            _fn = getattr(self, '_compute_side_delay_penalty', None)
            if _fn is not None:
                _v = _fn(max(0.0, float(_sr)), _suppress_log=True)
                if _v and float(_v[0]) > 0.0:
                    return float(_v[0]) * _cmult
        except Exception:
            pass
        try:
            return float(self._dctsp_cross_traffic_delay_s(
                max(0.0, float(_sr)), queue_elapsed_s=_side_red_elapsed))
        except Exception:
            return 0.0
    def _dp_coord_penalty(side_red_s, bus_saved_paxs, shift_sec=0.0):
        """Projected coordination penalty (pax·s) of granting THIS action.
        side_red_s is the FULL extra red imposed on the cross approaches; the
        side term is the real SideUpFlowList-based queue delay, repeated per
        discounted stage.  The bus term is the REAL projected impact at the
        next managed downstream junction (from live corridor state) when a
        corridor coordinator is available; otherwise it falls back to the
        local CTM self-projection of THIS junction's future queue."""
        _proj_dside = _dp_proj_side_delay(side_red_s)
        _pen = 0.0
        _n_stages = max(0, int(_dp_horizon / max(_dp_stage, 1e-9)))
        for _si in range(min(_n_stages, 3)):
            _off = (_si + 1) * _dp_stage
            _proj_n0 = max(0.0, n0_bus - float(bus_saved_paxs) * 0.7
                           + q_arr_bus_vps * _off)
            _proj_dbus = _ctm_delay_pax(_proj_n0, q_arr_bus_vps, q_sat_vps,
                                        0.0, _bus_g_base, _cell_occ)
            _pen += (_proj_dbus + _proj_dside) * (_coord_w ** (_si + 1))
        # ── Real downstream-junction projection (Z2, corridor-aware) ────────
        # The bus time shift at THIS junction moves the bus's arrival at the
        # NEXT managed junction; project its red-wait there from the live
        # downstream phase schedule.  Positive = coordination cost, negative =
        # coordination benefit.  shift_sec is the ACTION's time shift in
        # seconds (capped by the bus's actual no-action delay) — the pax·s
        # savings can be ~0 even for a real action, so the raw action duration
        # is the robust driver of the downstream projection.
        try:
            _coord = getattr(self, '_corridor_coord', None)
            if _coord is not None:
                _bs_sec = max(0.0, float(shift_sec))
                if _bs_sec > 0.0:
                    _pen += float(_coord.project_downstream_delay_paxs(
                        int(self.id), int(veh_id), float(time), float(timeSta),
                        float(bus_eta_s), _bs_sec, _bus_occ))
        except Exception:
            pass
        return _pen
    if _wrong_phase:
        _t_wait_na = float(remaining_red_s); _g_bus_na = _bus_g_base
    else:
        _t_wait_na = 0.0; _g_bus_na = float(remaining_red_s)
    # ETA correction: a bus still `bus_eta_s` away has NOT been waiting the full
    # remaining red — it only accrues delay from the moment it reaches the
    # stopline (same rationale as dctsp_mp_ectm).
    _eta = max(0.0, float(bus_eta_s))
    d_bus_na = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                              max(0.0, _t_wait_na - _eta), _g_bus_na, _cell_occ)
    d_side_na = float(self._dctsp_cross_traffic_delay_s(0.0))
    z_na = d_bus_na + d_side_na
    _d_min = float(MP_ECTM_MIN_EXT_S); _d_max = float(MP_ECTM_MAX_EXT_S)
    _d_step = float(dt)
    best_z = z_na; best_delta = 0.0; best_atype = 'NO_ACTION'
    best_d_bus = d_bus_na; best_d_side = d_side_na; best_dp_pen = 0.0
    _sweep_evals = []   # (atype, delta, d_bus, d_side, dp_pen) — the FULL CTM grid
    for _d_raw in np.arange(_d_min, _d_max + _d_step * 0.5, _d_step):
        delta = float(_d_raw)
        # The action's time shift at THIS junction (seconds): the bus can only
        # be pulled forward by as much as it is actually delayed without action.
        _act_shift = min(delta, max(0.0, float(no_act_delay)))
        if not _wrong_phase:
            d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps, 0.0, float(remaining_red_s) + delta, _cell_occ)
            d_side = float(self._dctsp_cross_traffic_delay_s(delta))
            _pen = _dp_coord_penalty(delta, d_bus_na - d_bus, _act_shift)
            z_ge = d_bus + d_side + _pen
            _sweep_evals.append(('GE', delta, d_bus, d_side, _pen))
            if z_ge < best_z:
                best_z = z_ge; best_delta = delta; best_atype = 'GE'
                best_d_bus = d_bus; best_d_side = d_side; best_dp_pen = _pen
        else:
            t_wait_post = float(remaining_red_s) + float(INS_INTERGREEN_S)
            d_bus_post = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                        max(0.0, t_wait_post - _eta), delta, _cell_occ)
            # ETA gate (mirrors _dctsp_eval_action INS rule): a bus still
            # `bus_eta_s` away cannot catch a short insertion — otherwise the
            # CTM queue model credits phantom savings from a few seconds of
            # green (INS_PRETERM_3 claimed up to ~62 000 pax·s).
            if float(bus_eta_s) > (max(0.0, delta) + float(INS_INTERGREEN_S)):
                d_bus_post = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                            max(0.0, t_wait_post), _bus_g_base, _cell_occ)
            d_side_post = float(self._dctsp_cross_traffic_delay_s(t_wait_post + delta))
            _pen_post = _dp_coord_penalty(t_wait_post + delta, d_bus_na - d_bus_post, _act_shift)
            z_post = d_bus_post + d_side_post + _pen_post
            _sweep_evals.append(('INS_POST', delta, d_bus_post, d_side_post, _pen_post))
            if z_post < best_z:
                best_z = z_post; best_delta = delta; best_atype = 'INS_POST'
                best_d_bus = d_bus_post; best_d_side = d_side_post; best_dp_pen = _pen_post
            _cut = max(0.0, float(remaining_red_s) - float(INS_INTERGREEN_S))
            d_bus_pt = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                      max(0.0, float(INS_INTERGREEN_S) - _eta),
                                      delta, _cell_occ)
            if float(bus_eta_s) > (max(0.0, delta) + float(INS_INTERGREEN_S)):
                d_bus_pt = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                          max(0.0, float(INS_INTERGREEN_S)),
                                          _bus_g_base, _cell_occ)
            d_side_pt = (float(self._dctsp_cross_traffic_delay_s(float(INS_INTERGREEN_S) + delta))
                         + float(self._dctsp_cross_traffic_delay_s(_cut)))
            _pen_pt = _dp_coord_penalty(float(INS_INTERGREEN_S) + delta + _cut, d_bus_na - d_bus_pt, _act_shift)
            z_pt = d_bus_pt + d_side_pt + _pen_pt
            _sweep_evals.append(('INS_PRETERM', delta, d_bus_pt, d_side_pt, _pen_pt))
            if z_pt < best_z:
                best_z = z_pt; best_delta = delta; best_atype = 'INS_PRETERM'
                best_d_bus = d_bus_pt; best_d_side = d_side_pt; best_dp_pen = _pen_pt
    eff_delay = max(0.0, float(no_act_delay) - float(ZIG_PHASE_OVERLAP_S))
    _satur_override = False
    if eff_delay < float(SELFORG_MIN_BUS_DELAY_S):
        best_atype = 'NO_ACTION'; best_delta = 0.0; _satur_override = True
    else:
        try:
            _o_d = _safe_float(self._safe_array_sum(getattr(self, 'OtherDelay', [0]))) + \
                   _safe_float(self._safe_array_sum(getattr(self, 'SideDelayBaseline', [0])))
            _bus_p = eff_delay * _bus_occ
            _side_p = max(0.0, _o_d) * _car_occ
            _ratio = _side_p / max(_bus_p, 1.0)
        except Exception:
            _ratio = 0.0
        _gate_factor = (float(MP_ECTM_GE_BALANCE_FACTOR) if best_atype == 'GE'
                        else float(MP_ECTM_BALANCE_FACTOR))
        if _ratio > _gate_factor:
            best_atype = 'NO_ACTION'; best_delta = 0.0; _satur_override = True
    r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
        self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
    rows = [('NO_ACTION', 0.0, r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na)]
    # Emit the FULL CTM grid sweep (each candidate with its DP coordination
    # penalty folded into the cross-phase cost), not just the argmin — the
    # Pareto layer needs the mode's whole model trade-off to distinguish
    # CTMGS_DP from CTMGS / GR_BASE.
    best_r = r_na; best_so = so_na; best_tp = tp_na; best_r_delta = 0.0
    if not _satur_override:
        for (at, delta, d_bus, d_side, dp_pen) in _sweep_evals:
            try:
                _, so_act, tp_act, bps_gated, _, nsd_act, std_act = _dctsp_eval_action(
                    self, at, delta, sigma_in, no_act_delay, bus_eta_s,
                    wrong_phase=_wrong_phase, remaining_red_s=remaining_red_s)
            except Exception:
                so_act, tp_act, bps_gated, nsd_act, std_act = so_na, tp_na, 0.0, nsd_na, std_na
            # Use the ETA-gated bus benefit from _dctsp_eval_action as the
            # authoritative value: it already applies the INS ETA gate (a bus still
            # `bus_eta_s` away cannot catch a short insertion) and the no_act_delay
            # cap, so the DP's raw CTM delta (d_bus_na - d_bus) cannot claim
            # phantom savings (INS_PRETERM_3 once claimed 62 000 pax·s ≈ 1 550 s
            # from a 3 s action).
            bps_ctm = min(max(0.0, float(bps_gated)),
                          max(0.0, d_bus_na - d_bus))
            cpc_ctm = max(0.0, d_side - d_side_na)
            # Same zero-cost fallback rationale as dctsp_mp_ectm: use MAX so the
            # live-count side cost binds whenever a bus benefit is claimed.
            if bps_ctm > 0.0:
                try:
                    _ectm_red = float(delta) + float(INS_INTERGREEN_S)
                    _sd, _ = self._compute_side_delay_penalty(_ectm_red, _suppress_log=True)
                    cpc_ctm = max(cpc_ctm, max(0.0, float(_sd)))
                except Exception:
                    pass
            # Fold the DP coordination look-ahead penalty into the emitted row's
            # cross-phase cost so the final max-reward / Pareto selection actually
            # sees the downstream impact (previously it only shaped the argmin and
            # was discarded when the row's reward was recomputed in engine.py).
            cpc_ctm += float(dp_pen)
            r_ctm   = bps_ctm - cpc_ctm
            rows.append((f'{at}_{delta:.0f}', delta,
                         r_ctm, so_act, tp_act, bps_ctm, cpc_ctm, nsd_act, std_act))
            if at == best_atype and abs(delta - best_delta) < 1e-6:
                best_r = r_ctm; best_so = so_act; best_tp = tp_act
                best_r_delta = r_ctm - r_na
    return (best_atype, best_delta, best_r, best_r_delta, best_so, best_tp, rows)


# ── Shared action-token helpers ───────────────────────────────────────────────
# Every candidate row uses one canonical label format so the Pareto layer and
# the execution dispatcher in engine.py can parse ANY mode's candidates.

_ACTION_LABEL_PREFIX = {
    'GE':                'GE',
    'INS':               'INS',
    'INS_POST':          'INS_POST',
    'INS_PRETERM':       'INS_PRETERM',
    'EARLY_RED':         'ER',
    'GREEN_REALLOC':     'GR',
    'OFFSET_CORRECTION': 'OC',
    'PHASE_SKIP':        'VP',
    'PHASE_ROTATION':    'PT',
}


def action_label(atype: str, param: float) -> str:
    """Canonical candidate label, e.g. ('GE', 10) -> 'GE_10'."""
    if atype == 'NO_ACTION':
        return 'NO_ACTION'
    _pfx = _ACTION_LABEL_PREFIX.get(str(atype), str(atype))
    # OFFSET_CORRECTION direction is encoded in the label sign ("OC_+5"/"OC_-5")
    # -- the executor reads it from the "+"; force the sign so a positive offset
    # is not mis-executed as negative.
    if str(atype) == 'OFFSET_CORRECTION':
        return f"{_pfx}_{float(param):+.0f}"
    return f"{_pfx}_{float(param):.0f}"


def parse_action_token(tok) -> tuple:
    """Map any candidate label to (exec_kind, param_s).

    exec_kind is one of {'NO_ACTION','GE','INS','GR','ER','OC','VP','PT'}
    — the execution branches implemented in engine.py.  INS_POST / INS_PRETERM
    / INS_close all map to 'INS'.  param_s is the trailing number in the label
    (absolute value; sign for OC stays encoded in the label) or None when the
    label carries no number (e.g. 'INS_close').
    """
    t = str(tok)
    if t == 'NO_ACTION':
        return 'NO_ACTION', 0.0
    _num = None
    if '_' in t:
        try:
            _num = abs(float(t.rsplit('_', 1)[1]))
        except (ValueError, TypeError):
            _num = None
    for _pfx, _kind in (('INS', 'INS'), ('GE', 'GE'),
                        ('EARLY_RED', 'ER'), ('GREEN_REALLOC', 'GR'),
                        ('ER', 'ER'), ('GR', 'GR'), ('OC', 'OC'),
                        ('VP', 'VP'), ('PT', 'PT')):
        if t.startswith(_pfx):
            return _kind, _num
    return 'NO_ACTION', 0.0


# ── Mode: DCTSP-BXT — CTM-based multiagent Q-learning ─────────────────────────
# Ported from kg/intersection_controller_lean.py (only existing implementation;
# the reference kg controller lineage never had BXT).
# Reference: Chanloha P., Chinrungrueng J., Usaha W. & Aswakul C. (2014),
# "Cell Transmission Model-Based Multiagent Q-Learning for Network-Scale
# Signal Control With Transit Priority", The Computer Journal 57(3), 451-466.

# ── Discrete action-duration grids (seconds), TUNABLE per network ─────────────
# The BXT learner SOLVES the exact magnitude at decision time (from the bus
# deficit/ETA, bounded by the running green — see _ge_star/_ins_star), so for BXT
# these are family SELECTORS; the generic pool and the grid modes (ZIG/Nash grid,
# MP-ECTM candidates) use the literal values. They are parameters (not hard-coded)
# so they can be set to realistic magnitudes for a given signal's min/max green.
# Defaults reproduce the historical {GE 5/10/15, INS 10/15/20, ER 10/20/30,
# GR 5/10/15} set. NOTE: INS is additionally capped at BXT_MAX_INS_S at execution,
# so INS grid entries above that are clamped there — raise BXT_MAX_INS_S to honour
# a longer INS grid.
GE_DURATIONS_S = [5.0, 10.0, 15.0]
INS_DURATIONS_S = [10.0, 15.0, 20.0]
ER_DURATIONS_S = [10.0, 20.0, 30.0]
GR_DURATIONS_S = [5.0, 10.0, 15.0]


def _build_rl_action_space():
    """Assemble DCTSP_RL_ACTION_SPACE from the tunable duration grids. OFFSET_
    CORRECTION is a single SOLVED bus-aligned action (param is a placeholder; the
    magnitude is fixed by _solve_offset_correction at decision time), gated by
    BXT_ENABLE_OC."""
    _sp = [('NO_ACTION', 0.0)]
    for _d in (GE_DURATIONS_S or []):
        _sp.append(('GE', float(_d)))
    for _d in (INS_DURATIONS_S or []):
        _sp.append(('INS', float(_d)))
    for _d in (ER_DURATIONS_S or []):
        _sp.append(('EARLY_RED', float(_d)))
    for _d in (GR_DURATIONS_S or []):
        _sp.append(('GREEN_REALLOC', float(_d)))
    _sp.append(('OFFSET_CORRECTION', 0.0))
    return _sp


DCTSP_RL_ACTION_SPACE = _build_rl_action_space()

# Indices of the "advance the HELD bus's green" actions (INS + GREEN_REALLOC).
# In a wrong-phase state (bus phase not running) both bring the bus green
# forward; used for optimistic Q-init so a held bus gets served instead of the
# learner defaulting to NO_ACTION.
_BXT_HOLD_SERVING_IDX = [i for i, (a, _) in enumerate(DCTSP_RL_ACTION_SPACE)
                         if a in ('INS', 'GREEN_REALLOC', 'OFFSET_CORRECTION')]

# Indices of the green-EXTENSION actions. Used by the optimistic Q-init in
# RIGHT-phase bins (bus green already up): extending the running green lets an
# arriving/queued bus clear. Seeding these completes the "act like traditional
# TSP" prior for an UNTRAINED learner -- without it a green-up bus still defaults
# to NO_ACTION (the hold-serving seed above only covers held-on-red buses).
_BXT_GE_SERVING_IDX = [i for i, (a, _) in enumerate(DCTSP_RL_ACTION_SPACE)
                       if a == 'GE']


def rebuild_action_space():
    """Rebuild DCTSP_RL_ACTION_SPACE and its derived index lists from the current
    (possibly run_config-overridden) duration grids. Call after MODE_FLAGS
    propagation in AAPIInit so per-arm GE/INS/ER/GR_DURATIONS_S take effect (the
    grids are structural, unlike scalar flags, so they need an explicit rebuild)."""
    global DCTSP_RL_ACTION_SPACE, _BXT_HOLD_SERVING_IDX, _BXT_GE_SERVING_IDX
    DCTSP_RL_ACTION_SPACE = _build_rl_action_space()
    _BXT_HOLD_SERVING_IDX = [i for i, (a, _) in enumerate(DCTSP_RL_ACTION_SPACE)
                             if a in ('INS', 'GREEN_REALLOC', 'OFFSET_CORRECTION')]
    _BXT_GE_SERVING_IDX = [i for i, (a, _) in enumerate(DCTSP_RL_ACTION_SPACE)
                           if a == 'GE']
    return DCTSP_RL_ACTION_SPACE

# BXT_INS_OPTIMISTIC_INIT: optimistic Q seed (pax-s) for the held-bus-serving
# actions in wrong-phase state bins. Pessimistic init (Q=0) left INS sample-
# starved -> it never fired in 4-seed training (champion search: INS=0 for every
# CELLQLEARN run) so the learner only ever EXTENDED green and could not match the
# INS-based winners. A small positive seed makes the greedy policy TRY inserting
# when a bus is held on red; the realized-advantage reward then keeps INS only
# where it actually pays (one gridlock outcome drives Q from +seed back to ~0 via
# Q += alpha*(realized_adv - Q)). 0 disables (pure pessimistic init). Tunable.
# 2026-08-24: DISABLED (120->0) for TRAINING. The seed made the learner CHOOSE
# INS, but INS is blocked at EXECUTION by the guard stack in dctsp_bxt (esp.
# `_side_ratio > BXT_BALANCE_FACTOR` — insertion steals a cross phase so it is
# vetoed whenever side traffic is non-trivial). The pick converted to NO_ACTION,
# INS's Q got credited with NO_ACTION's outcome (corrupt learning), and the churn
# GRIDLOCKED training (car +55%, obj -20.7%). Selection was never the blocker —
# execution is. So the DEFAULT stays 0 (full-pipeline training is untouched).
# 2026-09-11: re-enabled ONLY in the SMOKE run (champion_search injects it for
# BXT learner arms when smoke). Rationale: a smoke run is EVAL-only with train=[],
# so the Q-table is empty and a frozen learner argmaxes NO_ACTION for every bus
# -> byte-identical to NO_TSP. A positive seed makes an UNTRAINED CELLQLEARN act
# like traditional TSP instead (advance held buses via INS/GR in wrong-phase bins,
# extend green via GE in right-phase bins -- see _bxt_get_q). No learning happens
# in eval, so the training-gridlock caveat above does not apply. The execution
# guard can still veto INS, but with low side traffic (KG smoke: side_ratio~0) it
# passes. All seeded serving actions share _opt, so argmax breaks ties to the
# SMALLEST-magnitude serving action (GE 5s / INS 10s) -- a conservative prior.
BXT_INS_OPTIMISTIC_INIT = 0.0

# BXT_CTM_PRIOR_K: weight on the CTM-predicted advantage used to SEED a new
# Q-state (authentic cell-transmission-model Q-learning -- the CTM model provides
# the prior policy, realized experience refines it). 1.0 = seed at the full CTM
# advantage; 0 = old cold start (all-zero, model-free). BXT_CTM_PRIOR_CLIP_PAXS
# bounds any single seed so one over-confident CTM prediction cannot dominate
# before the alpha-scaled realized reward corrects it.
# 2026-08-24: DISABLED (1.0->0.0). The CTM prior GRIDLOCKED catastrophically
# (CELLQLEARN car +294%, obj -64%) and INS STILL = 0. Root cause = the exact flaw
# the old cold-start comment warned about: the CTM's action-benefit is MONOTONE in
# green duration and systematically over-values GE, so seeding from it made the
# learner extend green 31-48x/run -> gridlock, while INS (lower CTM advantage than
# GE) was never picked. The advantage-difference fixed the SCALE but not the
# GE-over-valuation. Confirms CELLQLEARN cannot be made competitive on KG.
BXT_CTM_PRIOR_K = 0.0
BXT_CTM_PRIOR_CLIP_PAXS = 500.0

# Q-table: {jct_id: {state_bin: [Q per action in DCTSP_RL_ACTION_SPACE]}}
_dctsp_bxt_q_table: dict = {}
# {veh_id: (jct_id, atype, aparam, decision_time, state_bin, action_idx)} —
# stored at decision time so a checkout hook can apply the terminal Q-update.
_poz_action_log: dict = {}
# Per-(junction,state) running mean of the realized delay under NO_ACTION.
# Actions are rewarded by their ADVANTAGE vs this baseline, so an action is only
# valued when it realizes LESS total delay than doing nothing typically does in
# that state -- self-baselining, and safe: NO_ACTION stays the reference (Q=0).
_bxt_noaction_baseline: dict = {}   # {(jct, state): [sum_delay, count]}


def _bxt_state_bin(n0_bus: float, side_ratio: float,
                   phase_is_bus: bool, bus_eta_s: float,
                   side_load: float = 0.0) -> tuple:
    """Discretise the per-decision state into a hashable state tuple.

    Base 4-tuple = (bus-queue bin, side-RATIO bin, phase-is-bus, eta bin). When
    BXT_DEMAND_STATE is on, a 5th DEMAND-REGIME bin is appended from `side_load`
    (absolute cross-street pax·s of delay) -- an OBSERVED level, not the ratio, so
    ONE policy can condition on how saturated the network is and behave
    differently at low vs high REAL-TIME demand instead of averaging over regimes.
    Flag-gated: with it off the state stays the original 4-tuple (existing Q-tables
    / warm-start pools keep their shape). Thresholds are tunable globals; adding
    the dimension ~3x's the table so it needs proportionally more training.
    """
    if n0_bus < 2.0:    b_b = 0
    elif n0_bus < 8.0:  b_b = 1
    elif n0_bus < 20.0: b_b = 2
    else:               b_b = 3
    if side_ratio < 0.3:   s_b = 0
    elif side_ratio < 0.8: s_b = 1
    elif side_ratio < 1.5: s_b = 2
    else:                  s_b = 3
    if bus_eta_s < 5.0:    e_b = 0
    elif bus_eta_s < 15.0: e_b = 1
    elif bus_eta_s < 30.0: e_b = 2
    else:                  e_b = 3
    if not bool(globals().get('BXT_DEMAND_STATE', False)):
        return (b_b, s_b, int(phase_is_bus), e_b)
    _lo = float(globals().get('BXT_DEMAND_BIN_LO_PAXS', 300.0))
    _hi = float(globals().get('BXT_DEMAND_BIN_HI_PAXS', 1500.0))
    if side_load < _lo:   d_b = 0        # light demand regime
    elif side_load < _hi: d_b = 1        # medium
    else:                 d_b = 2        # heavy / saturated
    return (b_b, s_b, int(phase_is_bus), e_b, d_b)


def _bxt_q_key(jct_id: int):
    """Which Q-table a signal reads/writes.

    Default: per-signal independent learners (key = jct_id) -- each intersection
    fills its OWN 128-state x 17-action table from only the buses that pass it,
    which is sample-starved on a handful of training seeds.

    BXT_SHARE_Q_ACROSS_SIGNALS=True pools EVERY signal into one shared table
    (fixed key -1): the per-decision state (bus-queue bin, side-ratio, phase-is-
    bus, eta) is junction-agnostic, so a queue-8/eta-10 s decision at any signal
    trains the same Q entry.  ~N_signals x more samples per (state,action) ->
    convergence in far fewer episodes.  Trade-off: one shared policy, no per-
    junction specialisation (fine at low seed budgets where specialisation has no
    data anyway).
    """
    return -1 if bool(globals().get('BXT_SHARE_Q_ACROSS_SIGNALS', False)) else int(jct_id)


_BXT_POOL_KEY = -1   # cross-signal warm-start pool (option 1)


def _bxt_warmstart_on(jct_id: int) -> bool:
    """Warm-start mode: per-signal Q tables, but a junction's FIRST visit to a
    state is seeded from a cross-signal POOL (what other signals already learned)
    and then fine-tunes its own copy.  Unlike full sharing (§39, which over-
    generalised into gridlock) this keeps per-junction specialisation while still
    getting the sample-efficiency of pooled early experience.  Disabled when full
    sharing is on (the pool key would collide with the shared table)."""
    return (bool(globals().get('BXT_WARMSTART_FROM_SHARED', False))
            and _bxt_q_key(jct_id) != _BXT_POOL_KEY)


def _bxt_get_q(jct_id: int, state_bin: tuple, init_vals=None) -> list:
    """Return (and lazily initialise) the BXT Q-value list for (jct, state)."""
    n = len(DCTSP_RL_ACTION_SPACE)
    tbl = _dctsp_bxt_q_table.setdefault(_bxt_q_key(jct_id), {})
    if state_bin not in tbl:
        _warm = None
        if _bxt_warmstart_on(jct_id):
            _pool = _dctsp_bxt_q_table.get(_BXT_POOL_KEY)
            if _pool and state_bin in _pool:
                _warm = list(_pool[state_bin])   # copy the pooled estimate
        if _warm is not None and len(_warm) == n:
            tbl[state_bin] = _warm
        else:
            _init = (list(init_vals)
                     if (init_vals is not None and len(init_vals) == n)
                     else [0.0] * n)
            # Optimistic init for the held-bus-serving actions (traditional-TSP
            # prior). Only in WRONG-PHASE bins (state_bin[2] == 0 = bus phase not
            # running = a bus is held on red): seed INS / GR positive so the
            # greedy policy advances the bus green instead of defaulting to
            # NO_ACTION. Right-phase bins (bus green already up) keep Q=0 — there
            # the correct held-bus action is GE, learned normally.
            try:
                _opt = float(globals().get('BXT_INS_OPTIMISTIC_INIT',
                                           BXT_INS_OPTIMISTIC_INIT) or 0.0)
                if _opt > 0.0 and len(state_bin) >= 3:
                    if int(state_bin[2]) == 0:
                        # wrong-phase (bus held on red): advance the bus green
                        for _i in _BXT_HOLD_SERVING_IDX:
                            if _i < n:
                                _init[_i] = _opt
                    else:
                        # right-phase (bus green up): extend the running green so
                        # an arriving/queued bus clears -- completes the
                        # traditional-TSP prior for an UNTRAINED learner.
                        for _i in _BXT_GE_SERVING_IDX:
                            if _i < n:
                                _init[_i] = _opt
            except Exception:
                pass
            tbl[state_bin] = _init
    return tbl[state_bin]


def _bxt_update_q(jct_id: int, state_bin: tuple, action_idx: int,
                  r_bxt: float) -> float:
    """Terminal Q update: Q(s,a) += alpha * (r - Q(s,a)). Returns TD error."""
    q_cur = _bxt_get_q(jct_id, state_bin)
    td_err = r_bxt - q_cur[action_idx]
    q_cur[action_idx] += float(BXT_ALPHA) * td_err
    # Keep the cross-signal warm-start pool aggregating so a FUTURE first-visit at
    # another signal inherits this experience (option 1).
    if _bxt_warmstart_on(jct_id):
        _pool = _dctsp_bxt_q_table.setdefault(_BXT_POOL_KEY, {})
        _pn = _pool.get(state_bin)
        if _pn is None:
            _pn = [0.0] * len(DCTSP_RL_ACTION_SPACE); _pool[state_bin] = _pn
        _pn[action_idx] += float(BXT_ALPHA) * (r_bxt - _pn[action_idx])
    return td_err


def _bxt_delay_snapshot(self):
    """Read the junction's cumulative (bus_delay, car_delay) in pax-s.

    These are running totals maintained by the stats layer, so the DIFFERENCE
    between two snapshots is the realized delay accrued at this junction over
    the interval -- the ground-truth outcome an action is judged by.
    """
    try:
        _d = self.stats._inter.get(self.id, {})
        return (float(_d.get('delay_bus', 0.0) or 0.0),
                float(_d.get('delay_car', 0.0) or 0.0))
    except Exception:
        return (0.0, 0.0)


def _bxt_neighbor_jcts(self):
    """Corridor neighbors of this junction (same CorridorCoordinator group).

    Used for inter-intersection reward sharing: a decision here is judged not
    only by this junction's realized delay but also (weighted) by what it did
    to its corridor partners.  Returns [] outside a coordinator group.
    """
    try:
        import sys as _sys
        _eng = _sys.modules.get('shared_tsp_engine.engine')
        _coords = getattr(_eng, 'corridor_coordinators', None) if _eng else None
        _me = int(getattr(self, 'id', 0) or 0)
        for _coord in (_coords or []):
            try:
                _ids = [int(i) for i in (getattr(_coord, 'inter_ids', None) or [])]
            except Exception:
                continue
            if _me in _ids:
                return [i for i in _ids if i != _me]
    except Exception:
        pass
    return []


def _bxt_neighbor_snapshot(self):
    """{jct_id: (bus_delay0, car_delay0)} for each corridor neighbor."""
    _out = {}
    try:
        for _nid in _bxt_neighbor_jcts(self):
            try:
                _nd = self.stats._inter.get(int(_nid), {}) or {}
                _out[int(_nid)] = (float(_nd.get('delay_bus', 0.0) or 0.0),
                                   float(_nd.get('delay_car', 0.0) or 0.0))
            except Exception:
                continue
    except Exception:
        pass
    return _out


def _bxt_apply_pending_updates(self, time):
    """Close the RL loop: for each logged decision whose evaluation window has
    elapsed, measure the REALIZED delay accrued at the junction since the
    decision and apply the Q-update with that measured reward.

    reward = -(realized_bus_delay * BUS_PAX_WEIGHT + realized_car_delay
               + CORRIDOR_REWARD_NEIGHBOR_W * neighbor_delay_delta)  [pax-s]

    Absolute-reward formulation: NO_ACTION and every action are scored on the
    SAME realized-delay basis, so across many buses in the same state bin the
    Q-values converge to the true expected delay per action -- and any
    systematic mis-pricing in the analytic SEED (e.g. underpriced cross cost)
    is corrected by experience.  Lower realized delay -> higher Q -> chosen more.
    """
    if not globals().get('BXT_LEARN', True):
        return
    _eval = (str(globals().get('BXT_PHASE', 'per_seed')) == 'eval')
    _diag = bool(globals().get('BXT_EVAL_DIAGNOSTICS', False))
    if _eval and not _diag:
        return                      # frozen policy, no diagnostics -> nothing to do
    if not _poz_action_log:
        return
    _now = float(time)
    _d1b, _d1c = _bxt_delay_snapshot(self)
    _done = []
    for _key, _rec in list(_poz_action_log.items()):
        # Only this junction's own decisions; keys are (jct_id, veh_id).
        if not (isinstance(_key, tuple) and len(_key) == 2 and _key[0] == int(self.id)):
            continue
        if not isinstance(_rec, dict):
            _done.append(_key); continue
        if _now < float(_rec.get('due_t', 0.0)):
            continue
        try:
            # ── REALIZED-delay reward ─────────────────────────────────────
            # The counterfactual reward credited the action's PREDICTED bus
            # benefit (no_act_delay*BusOcc, always large-positive) minus a LOCAL
            # short-window car cost -> systematically positive -> the model
            # learned to ACT MORE (action rate rose 25%->42% over training) and
            # gridlocked.  Proof it was wrong: when acting gridlocked, the BUS
            # delay ALSO exploded (+114%) -- the predicted benefit was never
            # delivered, yet the reward paid it anyway.
            #
            # Measured realized delay (pax-s) accrued at the junction over the
            # window -- the ground-truth outcome of this decision.
            _rb = max(0.0, _d1b - float(_rec.get('delay_bus0', 0.0)))
            _rc = max(0.0, _d1c - float(_rec.get('delay_car0', 0.0)))
            # v7 bus equity: bus pax-s count for BUS_PAX_WEIGHT times a car
            # pax-s in the reward (buses are rare but pack ~27x the people;
            # both NO_ACTION baseline and actions get the same weight).
            _eqw_l = max(0.0, float(globals().get('BUS_PAX_WEIGHT',
                                                  BUS_PAX_WEIGHT) or 1.0))
            # v7 inter-intersection reward sharing: add the SIGNED realized
            # delay delta of this junction's corridor neighbors over the same
            # window (weighted).  Negative delta = neighbors got faster = my
            # action helped the corridor = reward rises; queue-shoving onto the
            # next junction now costs instead of paying locally.
            _nbr_delta = 0.0
            _nbw = float(globals().get('CORRIDOR_REWARD_NEIGHBOR_W',
                                       CORRIDOR_REWARD_NEIGHBOR_W) or 0.0)
            if _nbw > 0.0:
                try:
                    _inter_stats = getattr(getattr(self, 'stats', None), '_inter', {}) or {}
                    for _nid, _snap in (_rec.get('nbr_delay0') or {}).items():
                        try:
                            _nd = _inter_stats.get(int(_nid), {}) or {}
                            _nbr_delta += (
                                (float(_nd.get('delay_bus', 0.0) or 0.0)
                                 - float(_snap[0]))
                                + (float(_nd.get('delay_car', 0.0) or 0.0)
                                   - float(_snap[1])))
                        except Exception:
                            continue
                except Exception:
                    _nbr_delta = 0.0
            _realized = (_rb * _eqw_l + _rc) + _nbw * _nbr_delta
            _reward = 0.0
            _scored = False
            _st = _rec['state']
            # Key the NO_ACTION baseline the same way as the Q-table so pooled
            # (shared-Q) learning also pools the baseline it is judged against.
            _bkey = (_bxt_q_key(self.id), tuple(_st) if isinstance(_st, (list, tuple)) else _st)
            _is_action = str(_rec.get('atype', 'NO_ACTION')) != 'NO_ACTION'
            if not _is_action:
                # NO_ACTION defines the baseline: track the running-mean realized
                # delay of doing nothing in this state.  Its own Q stays at the
                # cold-start 0 reference (never updated), so an action must
                # positively BEAT the baseline to be chosen.
                _bl = _bxt_noaction_baseline.setdefault(_bkey, [0.0, 0])
                _bl[0] += _realized; _bl[1] += 1
            else:
                # ADVANTAGE reward: how much LESS delay this action realized than
                # NO_ACTION typically does here.  Positive -> action helped ->
                # Q rises above 0 -> chosen; gridlock -> _realized >> baseline ->
                # large negative -> Q drops -> abandoned.  Skip until a baseline
                # exists (cold start stays conservative: unscored actions keep
                # Q=0 = NO_ACTION, tie -> NO_ACTION).
                _bl = _bxt_noaction_baseline.get(_bkey)
                if _bl and _bl[1] > 0:
                    _baseline = _bl[0] / _bl[1]
                    _reward = _baseline - _realized
                    _scored = True
                    # EVAL diagnostics keep the policy frozen: measure + log, but
                    # never write the Q-table (only training updates it).
                    if not _eval:
                        _bxt_update_q(int(self.id), _st, int(_rec['action_idx']), _reward)
            if globals().get('LOG_REWARD', False):
                _log_func(self,
                    "[BXT_LEARN] inter=%s bus=%s action=%s_%.0f realized_bus=%.0f "
                    "realized_car=%.0f nbr_delta=%.0f reward=%.0f" % (
                        self.id, _key[1], _rec.get('atype'), _rec.get('param', 0.0),
                        _rb, _rc, _nbr_delta, _reward))
            if _diag:
                # PREDICTED (decider's chosen benefit) vs REALIZED (measured
                # outcome), one line per decision. pred_adv = pred_bps - pred_cpc;
                # realized_adv = NO_ACTION baseline - realized (NA until a baseline
                # exists / for the NO_ACTION rows that DEFINE the baseline).
                _pb = float(_rec.get('pred_bps', 0.0) or 0.0)
                _pc = float(_rec.get('pred_cpc', 0.0) or 0.0)
                _log_func(self,
                    "[BXT_EVAL] inter=%s bus=%s t=%.1f action=%s_%.0f "
                    "pred_bps=%.0f pred_cpc=%.0f pred_adv=%.0f "
                    "realized_bus=%.0f realized_car=%.0f realized_adv=%s" % (
                        self.id, _key[1], float(_rec.get('t', 0.0)),
                        _rec.get('atype'), _rec.get('param', 0.0),
                        _pb, _pc, _pb - _pc, _rb, _rc,
                        ("%.0f" % _reward) if _scored else "NA"))
        except Exception:
            pass
        _done.append(_key)
    for _k in _done:
        _poz_action_log.pop(_k, None)


def dctsp_bxt(self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
              no_act_delay, sigma_in, remaining_red_s=0.0):
    """CTM red-light-delay Q-learning candidate generation (BXT mode).

    Returns (best_type, best_param, best_r, best_r_delta, best_sigma_out,
    best_t_poz, rows) — same contract as dctsp_zig / dctsp_mp_ectm.
    """
    import random as _rnd_bxt

    # ── CONTINUOUS play for the learner (CELLQLEARN) ──────────────────────────
    # On a no-bus monitor tick (veh_id<0 / bus_eta_s=1e9) the BXT reward model has
    # no bus to serve, so its Q argmaxes NO_ACTION. Route that tick through the
    # SHARED continuous state bargain (mainline-vs-cross green, incl. the bus-free
    # corridor coupling) so CELLQLEARN also acts on the traffic STATE continuously.
    # The learner still decides every bus-PRESENT tick. Gated by BXT_CONTINUOUS_
    # MODE; reached only under CONTINUOUS_MONITOR_MODE. (2026-09-24)
    if (((int(veh_id) < 0) or (float(bus_eta_s) > 1.0e8))
            and bool(globals().get('BXT_CONTINUOUS_MODE', True))):
        return dctsp_nash_bargain(self, time, timeSta, acycle, bus_eta_s, veh_id,
                                  current_phase, no_act_delay, sigma_in,
                                  remaining_red_s=remaining_red_s)

    dt           = float(BXT_DT_S)
    q_sat_vps    = float(getattr(self, 'SaturationFlow', 1800.0)) / 3600.0
    k_jam        = float(getattr(self, 'JamDensity', 200.0))
    _bus_occ     = float(getattr(self, 'BusOcc', 40.0))
    _cycle_s = float(self._signal_cycle_s()) if hasattr(self, '_signal_cycle_s') else float(self.config.get('CycleTime', 135.0) or 135.0)
    _bus_g_base  = float(getattr(self, 'BusPhaseDuration', 20.0))
    _wrong_phase = (int(current_phase) != int(self.BusPhase))

    # ── Estimate initial bus-approach queue n0 (LWR back-shockwave) ──────────
    try:
        upf = np.asarray(getattr(self, 'UpFlowList', np.zeros((1, 1))), dtype=float)
        rdt = np.asarray(getattr(self, 'RedDurationList', np.zeros((1, 1))), dtype=float)
        upf_bus = upf[0].ravel() if upf.ndim >= 2 and upf.shape[0] > 0 else np.zeros(1)
        rdt_bus = rdt[0].ravel() if rdt.ndim >= 2 and rdt.shape[0] > 0 else np.zeros(1)
        pos_flow = upf_bus[upf_bus > 0.0]
        pos_red = rdt_bus[(rdt_bus > 0.0) & (rdt_bus < 2.0 * _cycle_s)]
        q_arr_bus_vps = (float(np.mean(pos_flow)) / 3600.0
                         if pos_flow.size > 0 else 300.0 / 3600.0)
        t_red_past = (float(np.max(pos_red)) if pos_red.size > 0 else 60.0)
        k_arr_b = q_arr_bus_vps * k_jam / max(q_sat_vps, 1e-9)
        w_back_b = q_arr_bus_vps / max(k_jam - k_arr_b, 1.0)
        n0_bus = max(0.0, w_back_b * t_red_past * k_jam)
    except Exception:
        q_arr_bus_vps = 300.0 / 3600.0
        n0_bus = 5.0

    # ── Passenger weighting for the approach cell ────────────────────────────
    # `n0_bus` is the LWR/shockwave estimate of the WHOLE approach queue in
    # vehicles and `q_arr_bus_vps` is the WHOLE approach flow -- neither is
    # bus-only.  Passing `_bus_occ` (40 pax/veh) into _ctm_red_delay therefore
    # priced every queued car as a 40-passenger bus: a 30-vehicle queue scored
    # 1200 passengers against a true ~1 bus + 29 cars = ~75, a ~16x
    # overstatement.  Combined with the full-cycle horizon that made GE_15 look
    # worth 9-16k pax-s against a ~225 pax-s side cost (a 34-64x benefit/cost
    # ratio), so maximum-length extension won ~90% of evaluations and fired
    # ~300 times per run.  kg seeds 400/500 gridlocked: car delay +105%, bus
    # delay itself +35% from spillback, objective 149->91 and 113->46.
    #
    # Weight the cell by what it actually holds: the subject bus at BusOcc and
    # the remaining queued vehicles at CarOcc.
    _car_occ_cell = float(getattr(self, 'CarOcc', None)
                          or globals().get('BXT_CAR_OCC', 1.2) or 1.2)
    _n_cell = max(float(n0_bus), 1.0)
    _cell_occ = ((min(1.0, _n_cell) * _bus_occ
                  + max(0.0, _n_cell - 1.0) * _car_occ_cell) / _n_cell)

    _cap_veh = k_jam * 0.15

    def _ctm_red_delay(n0, q_arr, q_sat, t_wait_red, g_dur, occ):
        """Pax-seconds accumulated by the bus-approach cell over one cycle.

        Cell recursion (Eq. 29-30): occupancy `n` fills at the arrival rate
        while the approach is red (bounded by cell storage `_cap_veh`) and
        discharges at the sending flow `min(q_sat, n/dt)` while it is green.

        The horizon runs red -> green -> RED-AGAIN for the balance of the
        cycle.  That third segment is what makes the model a cell-transmission
        model rather than a one-shot queue formula: whatever occupancy cannot
        discharge before the signal returns to red PERSISTS in the cell and
        keeps accruing delay.  Without it the green loop drained `n` and then
        threw the state away, which had two consequences that made the action
        set unscoreable:

          * with t_wait_red = 0 (bus already has green) the delay integral is
            empty, so NO_ACTION, GE, EARLY_RED and GREEN_REALLOC all returned
            d_bus = 0 and were indistinguishable;
          * lengthening green (GE/GREEN_REALLOC) or shortening it (EARLY_RED)
            changed only the discarded residual, so the model could not price
            the very mechanism TSP operates through.

        Carrying the residual makes both effects observable in the same units,
        using the identical recursion for every segment.
        """
        delay = 0.0
        n = max(0.0, float(n0))

        def _red(dur):
            nonlocal delay, n
            for _ in range(max(0, int(round(float(dur) / dt)))):
                n = min(n + q_arr * dt, _cap_veh)
                delay += n * dt

        def _green(dur):
            nonlocal n
            for _ in range(max(0, int(round(float(dur) / dt)))):
                q_out = min(q_sat, n / max(dt, 1e-9))
                n = max(0.0, n + q_arr * dt - q_out * dt)

        _red(t_wait_red)
        _green(g_dur)
        # Balance of the cycle: the approach is red again and the un-served
        # residual waits it out under the same fill dynamics.
        _red(max(0.0, _cycle_s - float(t_wait_red) - float(g_dur)))
        return delay * float(occ)

    # ── Solved action durations (replaces the coarse {5,10,15} grid) ─────────
    # The action space offers GE/GR/INS at FIXED durations {5,10,15,20}.  With
    # the cost term underpriced, CTM reward is monotone in duration, so the grid
    # CEILING won ~80% of picks: measured kg seed 500, 265/350 GE picks were
    # GE_15 and 65% of those were on buses with eff_delay < 5 s -- i.e. it held
    # the green a full 15 s for buses that already make it.  A fixed grid also
    # cannot land on the true optimum and is implicitly tuned to kg's 135 s
    # cycle (wrong for Logan's 90-200 s).
    #
    # The legacy GE path (engine.py ~10280) already SOLVES this: extend by the
    # exact deficit the bus is short of clearing the current bus-green, bounded
    # by the network's own limits, and grant ZERO if the bus already makes it.
    # Reproduce that here so BXT stops paying for extensions no bus needs.
    #   deficit = bus_eta_s - green_left   (green_left = current bus-green if the
    #   bus phase is running, else 0 -- a wrong-phase bus needs a new window, not
    #   an extension of the phase it is NOT waiting on).
    _ge_ub = min(float(getattr(self, 'GE_upper_bound', 20.0) or 20.0),
                 float(MAX_GE_EXTENSION_S))
    _green_left = float(remaining_red_s) if not _wrong_phase else 0.0
    _ge_star = min(max(0.0, float(bus_eta_s) - _green_left), _ge_ub)
    # Insertion serves the bus its clearance window, not a fixed 10-20 s block;
    # bound by the disruptiveness cap already applied downstream.
    _ins_star = min(max(0.0, float(bus_eta_s) - _green_left), float(BXT_MAX_INS_S))
    _MIN_EFFECTIVE_GE_S = 1.0
    _solved_param = {'GE': _ge_star, 'GREEN_REALLOC': _ge_star, 'INS': _ins_star}

    # ── Individual-bus catch/miss term ───────────────────────────────────────
    # `_ctm_red_delay` models the APPROACH-QUEUE delay only; for a bus that
    # already has green (right phase) its wait integral is empty, so the CTM
    # cannot see the one thing a green extension buys -- THIS bus catching THIS
    # green instead of waiting a whole cycle for the next one.  Under correct
    # cost that made NO_ACTION win every right-phase decision (the queue term is
    # common to all actions, so only the side cost differed), which is exactly
    # why the old underpriced-cost build had to exist to fire at all.
    #
    # Model it explicitly: a bus that is NOT cleared this cycle incurs
    # `no_act_delay` seconds of wait at bus occupancy; a bus that IS cleared
    # incurs none.  This delta -- not the queue integral -- is what a TSP action
    # actually trades against cross-traffic cost.
    _raw_deficit = max(0.0, float(bus_eta_s) - _green_left)
    _bus_wait_pax = max(0.0, float(no_act_delay)) * _bus_occ

    # ── Purdue POG reward term (BXT_POG_REWARD) ──────────────────────────────
    # Sample the coordination state once, then penalise each offset-shifting
    # action by the pax·s of main platoon it pushes off green (Percent-on-Green
    # damage). Folds the Purdue metric into the LEARNER's reward.
    _bxt_pog_on = bool(globals().get('BXT_POG_REWARD', False))
    if _bxt_pog_on:
        try:
            self._sample_progression(current_phase)
        except Exception:
            _bxt_pog_on = False

    def _bxt_pog_penalty(a_s):
        if not _bxt_pog_on or float(a_s) <= 0.0:
            return 0.0
        try:
            return float(globals().get('BXT_POG_WEIGHT', 1.0)) * float(
                self._progression_cost(float(a_s)))
        except Exception:
            return 0.0

    def _bxt_reward_for(atype, aparam):
        # Grid durations are overridden by the solved value for the families
        # that support it; EARLY_RED keeps its grid (it is a phase truncation,
        # bounded by remaining_red_s, not an extend-to-clear action).
        """Return (r_bxt, d_bus, d_side): r_bxt = -(queue + bus wait + side), pax·s.
        Offset-shifting actions also pay a Purdue-POG penalty when BXT_POG_REWARD."""
        aparam = _solved_param.get(atype, aparam)
        a_s = float(aparam)
        if atype == 'NO_ACTION':
            if _wrong_phase:
                t_wait = float(remaining_red_s); g_bus = _bus_g_base
            else:
                t_wait = 0.0; g_bus = float(remaining_red_s)
            d_bus = _ctm_red_delay(n0_bus, q_arr_bus_vps, q_sat_vps, t_wait, g_bus, _cell_occ)
            d_bus += _bus_wait_pax                       # bus is NOT cleared
            d_side = float(self._dctsp_cross_traffic_delay_s(0.0))
            return -(d_bus + d_side), d_bus, d_side
        if atype == 'GE':
            if not _wrong_phase:
                d_bus = _ctm_red_delay(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       0.0, float(remaining_red_s) + a_s, _cell_occ)
                d_side = float(self._dctsp_cross_traffic_delay_s(a_s))
                # Cleared iff the extension actually reaches the bus.
                if not (a_s > 0.0 and _raw_deficit <= _ge_ub + 1e-6):
                    d_bus += _bus_wait_pax
            else:
                # Extending the wrong phase does NOT clear the bus (it lengthens
                # the phase the bus is waiting on); no catch credit.
                d_bus = _ctm_red_delay(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       float(remaining_red_s) + a_s, _bus_g_base, _cell_occ)
                d_bus += _bus_wait_pax
                d_side = float(self._dctsp_cross_traffic_delay_s(0.0))
            return -(d_bus + d_side + _bxt_pog_penalty(a_s)), d_bus, d_side
        if atype == 'INS':
            t_wait = float(remaining_red_s) + float(INS_INTERGREEN_S)
            d_bus = _ctm_red_delay(n0_bus, q_arr_bus_vps, q_sat_vps, t_wait, a_s, _cell_occ)
            if not (a_s > 0.0 and _raw_deficit <= float(BXT_MAX_INS_S) + 1e-6):
                d_bus += _bus_wait_pax
            d_side = float(self._dctsp_cross_traffic_delay_s(t_wait + a_s))
            return -(d_bus + d_side + _bxt_pog_penalty(a_s)), d_bus, d_side
        if atype == 'GREEN_REALLOC':
            # Reallocation moves `a_s` of green to the BUS phase.  Unlike GE it
            # also helps when the bus is held on red: it brings the bus green
            # forward / lengthens it.  Cross traffic pays for the moved green.
            if not _wrong_phase:
                d_bus = _ctm_red_delay(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       0.0, float(remaining_red_s) + a_s, _cell_occ)
            else:
                d_bus = _ctm_red_delay(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       float(remaining_red_s), _bus_g_base + a_s, _cell_occ)
            if not (a_s > 0.0 and _raw_deficit <= _ge_ub + 1e-6):
                d_bus += _bus_wait_pax
            d_side = float(self._dctsp_cross_traffic_delay_s(a_s))
            return -(d_bus + d_side + _bxt_pog_penalty(a_s)), d_bus, d_side
        if atype == 'EARLY_RED':
            # ER truncates the CURRENT phase by `a_s`.
            if _wrong_phase:
                # Bus held while a cross phase runs: cutting that phase short
                # brings the bus's green forward by up to `a_s`.  It clears the
                # bus only if that advance covers the deficit.
                d_bus = _ctm_red_delay(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       max(0.0, float(remaining_red_s) - a_s),
                                       _bus_g_base, _cell_occ)
                if not (a_s > 0.0 and a_s + 1e-6 >= _raw_deficit and _raw_deficit > 0.0):
                    d_bus += _bus_wait_pax
                d_side = float(self._dctsp_cross_traffic_delay_s(a_s))
            else:
                # The BUS phase itself is running: truncating it shortens the
                # bus's own green and can only make the bus MORE likely to miss,
                # so it never clears a pending bus.
                d_bus = _ctm_red_delay(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       0.0, max(0.0, float(remaining_red_s) - a_s),
                                       _cell_occ)
                d_bus += _bus_wait_pax
                d_side = float(self._dctsp_cross_traffic_delay_s(0.0))
            return -(d_bus + d_side), d_bus, d_side
        # Unmodelled action type -> fall back to the NO_ACTION evaluation, NOT
        # 0.0.  Every real evaluation returns a NEGATIVE pax-s reward, so a
        # literal 0.0 was the largest value this function could produce and any
        # unmodelled action won the Q-table argmax outright.  EARLY_RED and
        # GREEN_REALLOC (6 of the 13 entries in DCTSP_RL_ACTION_SPACE) hit that
        # path, and _bxt_get_q seeds the table directly from these values, so
        # index 7 -- EARLY_RED 10 s, the first unevaluated entry -- was chosen
        # 44 times in one kg run purely for never having been evaluated.
        # Returning the do-nothing baseline means an unmodelled action can at
        # best TIE with NO_ACTION, and max() resolves ties to the lowest index,
        # which is NO_ACTION itself.  This keeps the failure mode safe if the
        # action space is extended again.
        return _bxt_reward_for('NO_ACTION', 0.0)

    _bxt_evals  = [_bxt_reward_for(_at, _ap) for (_at, _ap) in DCTSP_RL_ACTION_SPACE]
    bxt_rewards = [_e[0] for _e in _bxt_evals]
    # ── CTM-predicted ADVANTAGE of each action vs NO_ACTION (pax·s) ───────────
    # This is the model-based signal that makes the method genuinely CELL-
    # TRANSMISSION-MODEL Q-learning: _ctm_red_delay integrates the approach cell's
    # occupancy over red->green->red (Eq. 29-30) and the bus catch/miss term, so
    # bxt_rewards[a] = -(cell delay + bus wait + cross cost) is the CTM's own
    # prediction of total pax-delay under action a. The DIFFERENCE below cancels
    # the large queue-integral baseline common to every action (that ±100k baseline
    # is exactly why the old code refused to seed Q from raw bxt_rewards), leaving
    # only each action's MARGINAL effect — which is on the same scale as the
    # realized-advantage learning reward, so it is a valid CTM prior for the Q-table.
    _ctm_adv = [float(r) - float(bxt_rewards[0]) for r in bxt_rewards]

    # ── State bins ────────────────────────────────────────────────────────────
    # `eff_delay` is bound HERE, before the [BXT] log below consumes it.  It
    # used to be assigned only after the log statement (in the saturation
    # guard), so every call raised UnboundLocalError, the dispatcher in
    # engine.py swallowed it, and BXT/CellQLearn silently never committed an
    # action -- the run fell through to the generic GE/INS candidate pool.
    # _o_occ / _o_d are pre-seeded for the same reason: they are logged
    # unconditionally but were only bound inside the try below.
    eff_delay = max(0.0, float(no_act_delay) - float(ZIG_PHASE_OVERLAP_S))
    _o_occ = 0.0
    _o_d = 0.0
    _side_p = 0.0
    try:
        _o_occ = self._estimated_other_vehicle_occupancy()
        _o_d = (_safe_float(self._safe_array_sum(getattr(self, 'OtherDelay', [0])))
                + _safe_float(self._safe_array_sum(
                    getattr(self, 'SideDelayBaseline', [0]))))
        _bus_p = eff_delay * _bus_occ
        _side_p = max(0.0, _o_d) * float(_o_occ)
        _side_ratio = _side_p / max(_bus_p, 1.0)
    except Exception:
        _side_ratio = 0.0
    # `_side_p` (absolute cross-street pax·s) is the demand-regime signal used by
    # _bxt_state_bin when BXT_DEMAND_STATE is on (else it is ignored).
    _bxt_state = _bxt_state_bin(n0_bus, _side_ratio, not _wrong_phase,
                                float(bus_eta_s), side_load=_side_p)

    # ── epsilon-greedy over the Q-table (initialised from CTM rewards) ───────
    # Phase-aware exploration: train seeds explore (BXT_TRAIN_EPSILON, ~0.1) so
    # the Q-table sees alternatives to learn from; eval seeds are GREEDY (eps=0)
    # so the measured policy is deterministic and leakage-free; default/per-seed
    # uses BXT_EPSILON.
    _phase = str(globals().get('BXT_PHASE', 'per_seed'))
    if _phase == 'eval':
        _eff_eps = 0.0
    elif _phase == 'train':
        _eff_eps = float(globals().get('BXT_TRAIN_EPSILON', 0.1))
    else:
        _eff_eps = float(BXT_EPSILON)
    _use_explore = (_rnd_bxt.random() < _eff_eps)
    # ── Q-table SEED: CTM-predicted advantage (authentic CTM Q-learning) ─────
    # A NEW (state) bin starts at the CTM's own prediction of each action's
    # advantage, so the FIRST decision in that state is driven by cell-transmission
    # physics rather than a cold NO_ACTION default (which left INS sample-starved
    # and the whole learner toothless). The realized-advantage reward then REFINES
    # each visited (state,action) toward its measured outcome — model-based init,
    # model-free correction. The old ±100k-scale failure was from seeding the RAW
    # bxt_rewards (which carry the common queue baseline); `_ctm_adv` is the
    # baseline-cancelled DIFFERENCE, on the reward's own scale. Clipped so a single
    # over-confident CTM prediction cannot dominate before experience corrects it.
    # BXT_CTM_PRIOR_K=0 falls back to the old cold start.
    _ctm_k = float(globals().get('BXT_CTM_PRIOR_K', BXT_CTM_PRIOR_K) or 0.0)
    if _ctm_k > 0.0:
        _clip = float(BXT_CTM_PRIOR_CLIP_PAXS)
        _init_q = [max(-_clip, min(_clip, _ctm_k * _a)) for _a in _ctm_adv]
        _init_q[0] = 0.0   # NO_ACTION stays the 0 reference (its own advantage is 0)
    else:
        _init_q = [0.0] * len(DCTSP_RL_ACTION_SPACE)
    q_vals = _bxt_get_q(self.id, _bxt_state, init_vals=_init_q)
    # ── Action-FAMILY gate (tactic sensitivity for a BXT champion) ────────────
    # The Phase-3 tactic axis (SWAPS/TIMES/BOTH) sets ZIG_ENABLE_* flags that only
    # the ZIG candidate builder reads -- the BXT decider always used the full
    # action space, so all tactics were byte-identical (218 duplicate SANITY
    # flags, 2026-09-15). These BXT_ENABLE_* flags (default ALL True -> no change
    # to normal runs) restrict the argmax/explore to the enabled families so the
    # tactic knob actually bites: TIMES=GE+GR, SWAPS=INS+EARLY_RED, BOTH=all.
    _fam_flag = {
        'GE':            bool(globals().get('BXT_ENABLE_GE', BXT_ENABLE_GE)),
        'INS':           bool(globals().get('BXT_ENABLE_INS', BXT_ENABLE_INS)),
        'GREEN_REALLOC': bool(globals().get('BXT_ENABLE_GR', BXT_ENABLE_GR)),
        'EARLY_RED':     bool(globals().get('BXT_ENABLE_ER', BXT_ENABLE_ER)),
        'OFFSET_CORRECTION': bool(globals().get('BXT_ENABLE_OC', BXT_ENABLE_OC)),
    }
    _allowed = [i for i, (_a, _p) in enumerate(DCTSP_RL_ACTION_SPACE)
                if _a == 'NO_ACTION' or _fam_flag.get(_a, True)]
    if not _allowed:
        _allowed = [0]                      # NO_ACTION always available
    if _use_explore:
        _chosen_idx = _rnd_bxt.choice(_allowed)
    else:
        _chosen_idx = max(_allowed, key=lambda i: q_vals[i])
    _chosen_atype, _chosen_aparam = DCTSP_RL_ACTION_SPACE[_chosen_idx]

    # ── Solve the action MAGNITUDE against the true total-system-delay ────────
    # The Q-table argmax picks the action FAMILY; the magnitude is not a grid
    # value.  For a green extension to the bus phase (GE, or GREEN_REALLOC while
    # the bus phase runs) we HARMONY-SEARCH the seconds that minimise total
    # passenger delay -- bus_delay*BusOcc + other_delay*other_occ from real
    # shockwave queue dynamics -- and act only if that beats doing nothing.
    # This replaces the discrete grid AND the underpriced CTM cross-cost proxy
    # in one move: the objective's other_delay term is the REAL car/side cost,
    # so the solver cannot over-extend (too much GE raises other_delay and is
    # rejected).  EARLY_RED (a phase truncation) keeps the analytic deficit.
    # Right-phase EARLY_RED shortens the bus's own green -> only hurts the bus.
    if _chosen_atype == 'EARLY_RED' and not _wrong_phase:
        _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    _ge_solve_family = (_chosen_atype == 'GE'
                        or (_chosen_atype == 'GREEN_REALLOC' and not _wrong_phase))
    # Wrong-phase GR advances the bus green by cutting the current CROSS phase
    # short; INS inserts a bus green.  Both are the "bring the held bus's green
    # forward" case, modelled by BP_Objective_Function (total pax delay for the
    # advanced/inserted bus green vs the cross cost of the shortened phase).
    # EARLY_RED on the WRONG phase truncates the current cross phase, advancing
    # the bus green -- mechanically the same "bring the held bus forward" case
    # as wrong-phase GR, so it solves against the same BP objective.  On the
    # RIGHT phase EARLY_RED only shortens the bus's OWN green (pure harm) and is
    # never worth doing -> suppressed below.
    _bp_solve_family = ((_chosen_atype == 'GREEN_REALLOC' and _wrong_phase)
                        or _chosen_atype == 'INS'
                        or (_chosen_atype == 'EARLY_RED' and _wrong_phase))
    # ── Bus benefit from the RELIABLE timing delay (not the degenerate objective)
    # [DELAY_DIAG] proved GE/BP_Objective_Function return ~0 bus delay even for
    # buses held 90-100 s, because they model delay via shockwave KINEMATICS
    # (bus approaching at BusSpeed joining a queue) which collapses to 0 when the
    # bus is STOPPED -- exactly the held-on-red buses TSP exists for.  So the old
    # "act iff opt_pax < base_pax" gate never fired.  Decide instead on the
    # timing delay `no_act_delay` (median 17.5 s on held buses, reliable), and
    # use harmony only to size the magnitude.
    _bus_benefit_paxs = (max(0.0, float(no_act_delay)) * _bus_occ
                         * max(0.0, float(globals().get('BUS_PAX_WEIGHT',
                                                        BUS_PAX_WEIGHT) or 1.0)))
    # WEIGHT-NEUTRAL bus benefit for the NET-BENEFIT GATE: pure bus
    # passenger-seconds saved (NO BUS_PAX_WEIGHT priority multiplier), so the gate
    # compares like-for-like against the cross-traffic passenger-seconds cost and
    # acts only when the action lowers TOTAL passenger delay -- not merely
    # bus-favoured delay (per user 2026-09-10).
    _bus_benefit_total_paxs = max(0.0, float(no_act_delay)) * _bus_occ
    # A bus crawling at <= 3 m/s is effectively STOPPED in the queue; the
    # kinematic objective treats it as ~0 delay, but it is genuinely waiting, so
    # trust the timing benefit (already does -- no_act_delay ignores BusSpeed).
    try:
        _bus_spd = (float(np.max(np.asarray(self.BusSpeed[0], dtype=float)))
                    if hasattr(self, 'BusSpeed') and len(self.BusSpeed) > 0 else 0.0)
    except Exception:
        _bus_spd = 0.0
    _bus_stopped = _bus_spd <= 3.0

    def _cross_cost_paxs(_mag):
        # Real cross-traffic pax-s cost of an action of _mag seconds.  Take the
        # larger of the analytic estimate and the live side-count penalty so a
        # thin analytic value cannot under-price the action.
        try:
            _a = float(self._dctsp_cross_traffic_delay_s(max(0.0, _mag)))
        except Exception:
            _a = 0.0
        try:
            _sd, _ = self._compute_side_delay_penalty(max(0.0, _mag), _suppress_log=True)
            _b = max(0.0, float(_sd)) * max(safe_float(getattr(self, 'CarOcc', 1.2)), 1.0)
        except Exception:
            _b = 0.0
        return max(_a, _b)

    if _ge_solve_family:
        # Magnitude: harmony-solved (returns ~the deficit when the bus-delay
        # objective is degenerate) bounded to what catches the bus.
        _mag = min(_ge_star, _ge_ub)
        # BXT_SOLVER='deficit' (recommended): use the closed-form deficit `_ge_star`
        # -- exactly the green the bus needs to clear -- and SKIP the objective
        # optimiser. Both harmony and golden minimise the shockwave objective,
        # which returns ~0 bus delay for a stopped bus; optimising that degenerate
        # curve produced worse magnitudes and gridlock (golden: KG 140->105). The
        # deficit is O(1), deterministic, and needs no (broken) objective.
        _use_solver = str(globals().get('BXT_SOLVER', 'harmony')).lower() != 'deficit'
        if (_use_solver and hasattr(self, 'solve_green_extension')
                and _ge_ub > _MIN_EFFECTIVE_GE_S and _raw_deficit >= _MIN_EFFECTIVE_GE_S):
            try:
                _opt_ge, _, _ = self.solve_green_extension(
                    min(_ge_star, _ge_ub), _ge_ub, time)
                if _opt_ge >= _MIN_EFFECTIVE_GE_S:
                    _mag = float(_opt_ge)
            except Exception:
                pass
        # ── ETA-reachability gate (fixes far-ETA GEs that never help the bus) ──
        # A GE extends the CURRENT bus green by at most _ge_ub, so it can only
        # bridge a bus arriving within (green_left + _ge_ub). The corridor pre-arm
        # was firing GE_10 for buses 100-230 s away (measured: 9/12 executed GEs
        # had eta>45 s, median 107 s) -- useless extensions that cost cross
        # traffic but never reach the bus, so bus delay never fell. Require the
        # bus to actually arrive during the extended green.
        _ge_reach = float(_green_left) + float(_ge_ub) + 5.0
        _eta_ok = float(bus_eta_s) <= _ge_reach
        # A stopped bus (<=3 m/s) sitting in the bus-phase queue benefits from
        # extension so the queue discharges and it clears -- its kinematic
        # "deficit" is unreliable, so allow action on benefit vs cost directly --
        # but STILL only if it is within reach (the _bus_stopped bypass + broken
        # Kalman speed was the hole the far-ETA pre-arm GEs slipped through).
        _catchable = _eta_ok and (
            (_raw_deficit >= _MIN_EFFECTIVE_GE_S and _raw_deficit <= _ge_ub + 1e-6)
            or (_bus_stopped and float(no_act_delay) >= _MIN_EFFECTIVE_GE_S))
        if _bus_stopped and _mag < _MIN_EFFECTIVE_GE_S:
            _mag = min(_ge_ub, max(_MIN_EFFECTIVE_GE_S, float(_ge_star) or _ge_ub))
        # Q-argmax already chose to ACT (it picked this family over NO_ACTION);
        # commit at the solved magnitude if the action is physically meaningful.
        # By default NO benefit>cost veto -- the closed-loop reward is meant to
        # teach the Q-table whether acting here was worth it.
        # NET-BENEFIT GATE (BXT_NET_BENEFIT_GATE, default OFF): on a car-dominated,
        # already-well-timed corridor the un-gated learner acts net-negative
        # (measured 2026-09-10: car delay +56%, bus delay +13% vs NO_TSP). When
        # enabled, VETO the action unless the bus benefit (from the reliable
        # timing delay `no_act_delay`) exceeds the cross-traffic cost at the
        # SOLVED magnitude -- both already computed above. Keeps TSP from being
        # worse than NO_TSP; compare CELLQLEARN_GATED vs CELLQLEARN.
        _nb_gate = bool(globals().get('BXT_NET_BENEFIT_GATE', False))
        _nb_ok = (not _nb_gate) or (_bus_benefit_total_paxs > _cross_cost_paxs(_mag))
        if _catchable and _mag >= _MIN_EFFECTIVE_GE_S and _nb_ok:
            _chosen_aparam = float(_mag)
        else:
            _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif _bp_solve_family:
        _bp_ub = float(BXT_MAX_INS_S) if _chosen_atype == 'INS' else _ge_ub
        _mag = min(max(_MIN_EFFECTIVE_GE_S,
                       _raw_deficit if _raw_deficit > 0.0 else _MIN_EFFECTIVE_GE_S),
                   _bp_ub)
        # BXT_SOLVER='deficit' skips the (degenerate) objective optimiser here too
        # -- the deficit `_mag` above is the bus's clearance need.
        _use_solver = str(globals().get('BXT_SOLVER', 'harmony')).lower() != 'deficit'
        if _use_solver and hasattr(self, 'solve_bus_phase_green') and _bp_ub > _MIN_EFFECTIVE_GE_S:
            try:
                _opt_bp, _, _ = self.solve_bus_phase_green(
                    min(_MIN_EFFECTIVE_GE_S, _bp_ub), _bp_ub, time)
                if _opt_bp >= _MIN_EFFECTIVE_GE_S:
                    _mag = float(_opt_bp)
            except Exception:
                pass
        # ETA-reachability gate: an insertion/advance can only catch a bus that
        # arrives within ~one cycle; firing it 100-230 s early (corridor pre-arm)
        # just disrupts the cross phase without serving the bus.
        _ins_reach = float(_cycle_s) + 5.0
        _eta_ok = float(bus_eta_s) <= _ins_reach
        # Q-argmax chose to act; commit at the solved magnitude.  Net-benefit gate
        # (see GE branch): when BXT_NET_BENEFIT_GATE is on, veto unless the bus
        # benefit exceeds the cross cost of this insertion/advance.
        _nb_gate = bool(globals().get('BXT_NET_BENEFIT_GATE', False))
        _nb_ok = (not _nb_gate) or (_bus_benefit_total_paxs > _cross_cost_paxs(_mag))
        if _eta_ok and _mag >= _MIN_EFFECTIVE_GE_S and _nb_ok:
            _chosen_aparam = float(_mag)
        else:
            _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif _chosen_atype == 'OFFSET_CORRECTION':
        # SOLVED offset correction (2026-09-22): the engine solver returns the
        # SIGNED shift that aligns the bus-phase start to THIS bus's arrival
        # (advance = negative, bounded by min-green). Same net-benefit gate as the
        # other families, using |shift| for the cross cost. Falls to NO_ACTION when
        # no feasible/meaningful alignment exists (e.g. the bus already catches the
        # green -> a GE handles that).
        try:
            _oc_shift, _ = self._solve_offset_correction(
                bus_eta_s, current_phase, timeSta, remaining_red_s)
        except Exception:
            _oc_shift = 0.0
        _nb_gate = bool(globals().get('BXT_NET_BENEFIT_GATE', False))
        _nb_ok = (not _nb_gate) or (_bus_benefit_total_paxs > _cross_cost_paxs(abs(_oc_shift)))
        if abs(_oc_shift) >= _MIN_EFFECTIVE_GE_S and _nb_ok:
            _chosen_aparam = float(_oc_shift)      # signed -> action_label encodes the sign
        else:
            _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif _chosen_atype in _solved_param:
        _chosen_aparam = float(_solved_param[_chosen_atype])

    _log_func(self, f"[BXT] inter={self.id} t={time:.1f} bus={veh_id} "
                    f"state={_bxt_state} n0={n0_bus:.1f}veh side_ratio={_side_ratio:.3f} "
                    f"eff_delay={eff_delay:.1f}s o_occ={_o_occ:.2f} o_d={_o_d:.0f}vhs "
                    f"upflow={[round(float(v),0) for v in self.UpFlowList[0].tolist()] if hasattr(self,'UpFlowList') and len(self.UpFlowList)>0 else 'n/a'} "
                    f"explore={_use_explore} chosen={_chosen_atype}_{_chosen_aparam:.0f}s")


    # ── Saturation avoidance (same guard as ZIG / MP_ECTM) ───────────────────
    # eff_delay already bound in the state-bin block above.
    _bxt_min_delay_s = float(globals().get('CELLQLEARN_MIN_GAIN_S',
                                           CELLQLEARN_MIN_GAIN_S) or 0.0)
    if _bxt_min_delay_s <= 0.0:
        _bxt_min_delay_s = float(SELFORG_MIN_BUS_DELAY_S)
    if eff_delay < _bxt_min_delay_s:
        _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif _chosen_atype in _solved_param and _chosen_aparam < _MIN_EFFECTIVE_GE_S:
        # Solved deficit is ~0: the bus already clears without help.  This is
        # the case the fixed grid mispriced -- it granted 15 s to a bus facing
        # no delay.  Grant nothing and pay no cross-traffic cost.
        _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif _side_ratio > float(BXT_GE_BALANCE_FACTOR if _chosen_atype == 'GE'
                             else BXT_BALANCE_FACTOR):
        # 2026-08-24: the CTM-override relaxation here was REVERTED — it did not
        # help (INS never fired; GE gridlocked) because the CTM over-values GE.
        _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif _chosen_atype == 'INS' and _chosen_aparam > float(BXT_MAX_INS_S):
        # Clamp the disruptive insertion instead of committing the full
        # 15-20 s candidate (mode-commits-own-action bypasses BP_upper_bound).
        _chosen_aparam = float(BXT_MAX_INS_S)

    # ── Baked-in traditional-TSP rule layer ───────────────────────────────────
    # Domain rules from classic transit-signal-priority practice, applied as HARD
    # constraints AFTER the learned policy + harmony solver have chosen a tactic
    # and magnitude.  Each rule can only make the decision MORE conservative
    # (force NO_ACTION or shrink the grant), never invent an action, so the RL /
    # CTM economics still drive when TSP fires.  Each is independently toggleable;
    # rules that merely add safety are on by default, broadly-suppressive ones are
    # present but off until their data source is confirmed on this network.
    if _chosen_atype != 'NO_ACTION':
        _rule_veto = None

        # (1) Conditional priority: grant only to buses that are behind schedule.
        # Uses the per-bus accumulated lateness (Z3) threaded in as sigma_in.
        # OFF by default (threshold 0) -- enable once lateness tracking is
        # confirmed populated on this network, else it suppresses every bus.
        _cp_min_late = float(globals().get('CONDITIONAL_PRIORITY_MIN_LATENESS_S', 0.0) or 0.0)
        if _cp_min_late > 0.0 and float(sigma_in) < _cp_min_late:
            _rule_veto = f"conditional_priority(lateness={float(sigma_in):.0f}s<{_cp_min_late:.0f}s)"

        # (2) Min-green / pedestrian clearance: never truncate the CURRENT phase
        # below its minimum green.  Applies to tactics that shorten the running
        # cross phase to advance the bus (PT / wrong-phase GR / wrong-phase ER):
        # cap the amount taken so >= MinGreen of the cross phase survives.
        if _rule_veto is None and bool(globals().get('RULE_MIN_GREEN', True)):
            _shortens = (_chosen_atype == 'PHASE_ROTATION'
                         or (_chosen_atype == 'GREEN_REALLOC' and _wrong_phase)
                         or (_chosen_atype == 'EARLY_RED' and _wrong_phase))
            if _shortens:
                _min_green = float(getattr(self, 'MinGreen',
                                   globals().get('MIN_GREEN_S', 5.0)) or 5.0)
                _max_take = max(0.0, float(remaining_red_s) - _min_green)
                if _chosen_aparam > _max_take:
                    if _max_take >= _MIN_EFFECTIVE_GE_S:
                        _chosen_aparam = float(_max_take)   # shrink to protect min green
                    else:
                        _rule_veto = f"min_green(protect {_min_green:.0f}s cross phase)"

        # (3) Cooldown: one grant per bus per junction within a headway window.
        # (Natural-green skip is already enforced by the deficit->NO_ACTION logic
        # above; this adds the anti-double-serve headway.)
        if _rule_veto is None and bool(globals().get('RULE_TSP_COOLDOWN', True)):
            _cd_s = float(globals().get('TSP_PER_BUS_COOLDOWN_S', 60.0) or 0.0)
            if _cd_s > 0.0 and veh_id and int(veh_id) > 0:
                _cd_map = getattr(self, '_bxt_last_served', None)
                if _cd_map is None:
                    _cd_map = {}; self._bxt_last_served = _cd_map
                _last_t = float(_cd_map.get(int(veh_id), -1e9))
                if (float(time) - _last_t) < _cd_s:
                    _rule_veto = f"cooldown(served {float(time)-_last_t:.0f}s<{_cd_s:.0f}s ago)"

        # (4) Occupancy / person-delay warrant: only act when the person-delay the
        # grant would save (bus occupancy x bus delay) clears a threshold, so a
        # near-empty bus never disrupts heavy cross traffic.
        if _rule_veto is None and bool(globals().get('RULE_PERSON_DELAY_WARRANT', True)):
            _pd_min = float(globals().get('PERSON_DELAY_WARRANT_MIN_PAXS', 0.0) or 0.0)
            _pd = max(0.0, float(no_act_delay)) * float(_bus_occ)
            if _pd_min > 0.0 and _pd < _pd_min:
                _rule_veto = f"person_delay({_pd:.0f}pax·s<{_pd_min:.0f})"

        if _rule_veto is not None:
            _log_func(self, f"[TSP RULE] inter={self.id} t={time:.1f} bus={veh_id} "
                            f"vetoed {_chosen_atype} -> NO_ACTION ({_rule_veto})")
            try:
                self.stats.record_tsp_skip(self.id, 'tsp_rule_veto')
            except Exception:
                pass
            _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
        elif veh_id and int(veh_id) > 0 and _chosen_atype != 'NO_ACTION':
            # Record the serve time for the per-bus cooldown rule.
            _cd_map = getattr(self, '_bxt_last_served', None)
            if _cd_map is None:
                _cd_map = {}; self._bxt_last_served = _cd_map
            _cd_map[int(veh_id)] = float(time)

    # ── Rows for the shared Pareto layer / reward CSV ─────────────────────────
    r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
        self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
    rows = [('NO_ACTION', 0.0, r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na)]

    if _chosen_atype != 'NO_ACTION' and _chosen_aparam > 0.0:
        # Metadata (sigma/t_poz) from the shared evaluator, but the objective
        # vector comes from BXT's own CTM red-delay model so the Pareto layer
        # sees BXT-specific economics (same reasoning as dctsp_mp_ectm).
        _, so_act, tp_act, _, _, nsd_act, std_act = _dctsp_eval_action(
            self, _chosen_atype, _chosen_aparam, sigma_in, no_act_delay, bus_eta_s,
            wrong_phase=_wrong_phase, remaining_red_s=remaining_red_s)
        _, _d_bus_na_c, _d_side_na_c = _bxt_evals[0]
        _, _d_bus_c, _d_side_c = _bxt_evals[_chosen_idx]
        # v7: bus-equity weighting + green-keep reinforcement credit.
        # bps_ctm was exactly 0 whenever the bus is predicted to arrive on
        # green, which let the decider cost veto kill every action (measured
        # 1458 no-actions vs 5 extensions/run).  Weight the bus pax-s by
        # BUS_PAX_WEIGHT and, when the bus is inside the reachable window but
        # no red-wait is predicted anyway, credit a small protected-green
        # floor (GREEN_KEEP_CREDIT_S x occ x weight) so near-free reinforcement
        # actions can fire; expensive ones still lose the veto economics.
        _eqw_r = max(0.0, float(globals().get('BUS_PAX_WEIGHT',
                                              BUS_PAX_WEIGHT) or 1.0))
        _keep_s = max(0.0, float(globals().get('GREEN_KEEP_CREDIT_S',
                                               GREEN_KEEP_CREDIT_S) or 0.0))
        bps_ctm = max(0.0, _d_bus_na_c - _d_bus_c)
        _keep_credit = 0.0
        if bps_ctm < 1.0 and _keep_s > 0.0:
            try:
                _gl_v = float(_green_left)
            except Exception:
                _gl_v = 0.0
            try:
                _ub_v = float(_ge_ub)
            except Exception:
                _ub_v = 0.0
            try:
                _cyc_v = float(_cycle_s)
            except Exception:
                _cyc_v = 135.0
            if current_phase == self.BusPhase:
                # GE protects the running bus phase up to green_left + ub.
                _reach_ok = float(bus_eta_s) <= (_gl_v + _ub_v + 5.0)
            else:
                # INS/advance can bring the bus green forward within a cycle.
                _reach_ok = float(bus_eta_s) <= (_cyc_v + 5.0)
            if _reach_ok:
                _keep_credit = _keep_s * _bus_occ * _eqw_r
        bps_ctm = bps_ctm * _eqw_r + _keep_credit
        # ── Multi-bus benefit: sum over ALL oncoming buses the action serves ──
        # The single detected bus underweights a PLATOON -- an action that also
        # serves a following bus within the (extended) green window is worth more,
        # and should clear the cost veto where one bus wouldn't. Scale the benefit
        # by the total occupancy of oncoming buses inside the reach window (>=1x;
        # only >1 when a second bus is genuinely coming). Capped by
        # MULTIBUS_MAX_FACTOR to avoid runaway. Uses the continuously-corrected
        # trackers (§50) so "oncoming" is accurate.
        if bps_ctm > 0.0:
            try:
                _cc = getattr(self, '_corridor_coord', None)
                if _cc is not None:
                    _reach_win = ((float(_green_left) + float(_ge_ub) + 5.0)
                                  if not _wrong_phase else (float(_cycle_s) + 5.0))
                    _onc = _cc.oncoming_buses(self.id, time, max_eta_s=_reach_win)
                    # 2026-08-24 (#3): default factor rolled back 3.0 -> 1.0
                    # (disabled). The ×3 platoon amplification over-bought bus
                    # time and drove the OC/GR cascade (champion search car +69%).
                    # Set MULTIBUS_MAX_FACTOR>1 to re-enable once GR/OC are gated.
                    _mb_cap = float(globals().get('MULTIBUS_MAX_FACTOR', 1.0) or 1.0)
                    if len(_onc) > 1 and _mb_cap > 1.0:
                        _tot_occ = sum(float(_o[2]) for _o in _onc)
                        _mb = min(max(1.0, _tot_occ / max(float(_bus_occ), 1.0)), _mb_cap)
                        bps_ctm *= _mb
            except Exception:
                pass
        cpc_ctm = max(0.0, _d_side_c - _d_side_na_c)
        # FLOOR the predicted cross cost at the (measured-congestion-aware, when
        # MEASURED_SIDE_COST is on) side penalty on EVERY action -- not just when
        # cpc_ctm<1. The shockwave term under-prices a congested cross approach,
        # which is the seed-lottery car cascade; taking the WORSE estimate keeps
        # the predicted cost (and the [BXT_EVAL] calibration) honest.
        try:
            _bxt_red = float(_chosen_aparam) + float(INS_INTERGREEN_S)
            _sd, _ = self._compute_side_delay_penalty(_bxt_red, _suppress_log=True)
            cpc_ctm = max(cpc_ctm, max(0.0, float(_sd)))
        except Exception:
            pass
        r_act = bps_ctm - cpc_ctm
        rows.append((action_label(_chosen_atype, _chosen_aparam), _chosen_aparam,
                     r_act, so_act, tp_act, bps_ctm, cpc_ctm, nsd_act, std_act))
        best_r, best_so, best_tp = r_act, so_act, tp_act
        best_r_delta = r_act - r_na
    else:
        _chosen_atype, _chosen_aparam = 'NO_ACTION', 0.0
        best_r, best_so, best_tp, best_r_delta = r_na, so_na, tp_na, 0.0

    # ── CLOSED-LOOP LEARNING: log this decision + a delay snapshot so the
    # realized outcome (measured from the sim ~1.5 cycles later) can be credited
    # back via _bxt_update_q.  Keyed by (junction, bus) -- one bus visits several
    # junctions and each is a separate decision.  Without this the Q-table stays
    # frozen at its analytic seed and the model can never learn whether its cost
    # prices are wrong.  See _bxt_apply_pending_updates.
    _diag = bool(globals().get('BXT_EVAL_DIAGNOSTICS', False))
    if globals().get('BXT_LEARN', True) and (_phase != 'eval' or _diag):
        try:
            _d0b, _d0c = _bxt_delay_snapshot(self)
            _cyc = float(self._signal_cycle_s()) if hasattr(self, '_signal_cycle_s')                 else float(getattr(self, 'cycle_len_s', 135.0) or 135.0)
            # PREDICTED benefit the decider used to CHOOSE (0 for NO_ACTION). Stored
            # so the closure can log it beside the REALIZED outcome (calibration).
            _pred_bps = float(locals().get('bps_ctm', 0.0) or 0.0) \
                if _chosen_atype != 'NO_ACTION' else 0.0
            _pred_cpc = float(locals().get('cpc_ctm', 0.0) or 0.0) \
                if _chosen_atype != 'NO_ACTION' else 0.0
            _poz_action_log[(int(self.id), int(veh_id))] = {
                'state': _bxt_state, 'action_idx': int(_chosen_idx),
                'atype': _chosen_atype, 'param': float(_chosen_aparam),
                't': float(time), 'delay_bus0': _d0b, 'delay_car0': _d0c,
                'due_t': float(time) + 1.5 * _cyc,
                'pred_bps': _pred_bps, 'pred_cpc': _pred_cpc,
                'pred_r': _pred_bps - _pred_cpc,
                # For the counterfactual (advantage) reward: the bus delay this
                # action was meant to AVOID, per-decision, and the occupancy.
                'no_act_delay': max(0.0, float(no_act_delay)),
                'bus_occ': float(_bus_occ),
                # v7 corridor reward sharing: neighbors' delay at decision time
                # so the update can credit their signed delta over the window.
                'nbr_delay0': _bxt_neighbor_snapshot(self),
            }
        except Exception:
            pass

    return (_chosen_atype, _chosen_aparam, best_r, best_r_delta,
            best_so, best_tp, rows)


# ── Mode: CPD-QL — tabular Q-learning per junction (DCTSP_MARL as a learner) ──
# Per-junction independent Q-tables (the "cooperative per-junction Q-learning"
# of the DCTSP_MARL lineage): each signal is its own agent over
# CPDQL_ACTION_SPACE; the shared GLOBAL_REWARD objective is expressed through
# per-action reward rows consumed by the common selection layer.

CPDQL_ACTION_SPACE = [
    ('NO_ACTION', 0.0),
    ('GE', 5.0), ('GE', 10.0), ('GE', 15.0),
    ('INS', 10.0), ('INS', 15.0), ('INS', 20.0),
]

# Q-tables: {jct_id: {state_bin: [Q per action in CPDQL_ACTION_SPACE]}}
_cpdql_q_table: dict = {}
# {veh_id: decision record} — written at decision time, applied by
# _cpdql_apply_pending_updates once the evaluation window elapses.
_cpdql_action_log: dict = {}
# {(jct_id, state_bin): [sum_realized_delay, count]} — NO_ACTION per-state
# baseline for the realized-advantage reward.
_cpdql_noaction_baseline: dict = {}


def _cpdql_state_bin(sigma_in: float, bus_eta_s: float, eff_delay: float,
                     phase_is_bus: bool) -> tuple:
    """54-state discretisation (paper Method I): headway deviation (early /
    on-time / late) x bus ETA (<10 / [10,30) / >=30 s) x estimated delay
    (zero / low / high) x phase match.  Returns a hashable 4-tuple."""
    # sigma + = late.  |sigma| < 30 s = on-schedule tolerance.
    if float(sigma_in) < -30.0:
        s_b = 0                       # early
    elif float(sigma_in) <= 30.0:
        s_b = 1                       # on-time
    else:
        s_b = 2                       # late
    if float(bus_eta_s) < 10.0:
        e_b = 0
    elif float(bus_eta_s) < 30.0:
        e_b = 1
    else:
        e_b = 2
    if float(eff_delay) < 2.0:
        d_b = 0                       # zero
    elif float(eff_delay) < 15.0:
        d_b = 1                       # low
    else:
        d_b = 2                       # high
    return (s_b, e_b, d_b, int(bool(phase_is_bus)))


def _cpdql_get_q(jct_id: int, state_bin: tuple, init_vals=None) -> list:
    """Return (and lazily initialise) the CPD-QL Q-value list for (jct, state)."""
    n = len(CPDQL_ACTION_SPACE)
    tbl = _cpdql_q_table.setdefault(int(jct_id), {})
    if not isinstance(state_bin, tuple):
        state_bin = tuple(state_bin)
    if state_bin not in tbl:
        _init = [0.0] * n
        if init_vals is not None:
            for _i, _v in enumerate(init_vals[:n]):
                _init[_i] = float(_v)
        tbl[state_bin] = _init
    return tbl[state_bin]


def _cpdql_update_q(jct_id: int, state_bin: tuple, action_idx: int,
                    reward: float, next_state=None) -> float:
    """TD(0) update: Q(s,a) += alpha*[r + gamma*max_a' Q(s',a') - Q(s,a)].

    `next_state` is the junction's NEXT decision state (or None = terminus).
    Returns the TD error."""
    q_cur = _cpdql_get_q(jct_id, state_bin)
    _boot = 0.0
    if next_state is not None and float(CPDQL_GAMMA) > 0.0:
        q_nxt = _cpdql_get_q(jct_id, next_state)
        _boot = float(CPDQL_GAMMA) * max(q_nxt)
    td_err = float(reward) + _boot - q_cur[action_idx]
    q_cur[action_idx] += float(CPDQL_ALPHA) * td_err
    return td_err


def _cpdql_reset():
    """Clear the CPD-QL tables so each seed is an independent episode."""
    try:
        _cpdql_q_table.clear()
        _cpdql_action_log.clear()
        _cpdql_noaction_baseline.clear()
    except Exception:
        pass


def _cpdql_apply_pending_updates(self, time):
    """Close the RL loop: for each logged decision whose evaluation window has
    elapsed, measure the REALIZED delay accrued at the junction and apply the
    TD update, bootstrapping onto the same junction's next decision state."""
    if not bool(globals().get('CPDQL_LEARN', True)):
        return
    if str(globals().get('CPDQL_PHASE', 'per_seed')) == 'eval':
        return                       # frozen policy during evaluation
    if not _cpdql_action_log:
        return
    _now = float(time)
    _d1b, _d1c = _bxt_delay_snapshot(self)
    _done = []
    for _key, _rec in list(_cpdql_action_log.items()):
        if not (isinstance(_key, tuple) and len(_key) == 2
                and int(_key[0]) == int(self.id)):
            continue
        if not isinstance(_rec, dict):
            _done.append(_key); continue
        if _now < float(_rec.get('due_t', 0.0)):
            continue
        try:
            _rb = max(0.0, _d1b - float(_rec.get('delay_bus0', 0.0)))
            _rc = max(0.0, _d1c - float(_rec.get('delay_car0', 0.0)))
            _realized = _rb + max(1.0, float(CPDQL_CAR_OCC)) * _rc
            _st = _rec['state']
            _bkey = (int(self.id), tuple(_st))
            _is_action = str(_rec.get('atype', 'NO_ACTION')) != 'NO_ACTION'
            if not _is_action:
                _bl = _cpdql_noaction_baseline.setdefault(_bkey, [0.0, 0])
                _bl[0] += _realized; _bl[1] += 1
            else:
                _bl = _cpdql_noaction_baseline.get(_bkey)
                _reward = 0.0
                if _bl and _bl[1] > 0:
                    _reward = (_bl[0] / _bl[1]) - _realized
                    # Bootstrap onto this junction's next decision state.
                    _next_st = None
                    _next_t = None
                    for _k2, _r2 in _cpdql_action_log.items():
                        if (_k2[0] != int(self.id) or _k2 == _key
                                or not isinstance(_r2, dict)):
                            continue
                        _t2 = float(_r2.get('t', 1e18))
                        if _t2 > float(_rec.get('t', 0.0)):
                            if _next_t is None or _t2 < _next_t:
                                _next_t = _t2
                                try:
                                    _next_st = tuple(_r2.get('state'))
                                except Exception:
                                    _next_st = None
                    _cpdql_update_q(int(self.id), _st,
                                    int(_rec['action_idx']), _reward,
                                    next_state=_next_st)
            if globals().get('LOG_REWARD', False):
                _log_func(self,
                    "[CPDQL_LEARN] inter=%s bus=%s action=%s_%.0f realized_bus=%.0f "
                    "realized_car=%.0f reward=%.0f" % (
                        self.id, _key[1], _rec.get('atype'), _rec.get('param', 0.0),
                        _rb, _rc, _reward))
        except Exception:
            pass
        _done.append(_key)
    for _k in _done:
        _cpdql_action_log.pop(_k, None)


def dctsp_cpdql(self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
                no_act_delay, sigma_in, remaining_red_s=0.0):
    """Per-junction tabular Q-learning TSP (CPDQL mode).

    Returns (best_type, best_param, best_r, best_r_delta, best_sigma_out,
    best_t_poz, rows) — same contract as dctsp_bxt.
    """
    import random as _rnd_cpdql

    _bus_occ = float(getattr(self, 'BusOcc', 40.0))
    _car_occ = float(CPDQL_CAR_OCC)
    _wrong_phase = (int(current_phase) != int(self.BusPhase))
    _phase_is_bus = not _wrong_phase
    _eff_delay = max(0.0, float(no_act_delay))
    _sig_in = float(sigma_in or 0.0)

    # ── State bin (54 states) ────────────────────────────────────────────────
    _state = _cpdql_state_bin(_sig_in, float(bus_eta_s), _eff_delay, _phase_is_bus)

    # ── Per-decision paper reward for every action (drives the rows + Q seed) ─
    # r(a) = w_h*rho_bus*(|sigma_in|-|sigma_out(a)|)
    #      + (1-w_h)*((d_NA-d_a)*n_b - D_car(a))
    def _cpdql_sel_reward(_at, _ap):
        try:
            (_r, _so, _tp, _bps, _cpc, _nsd, _std) = _dctsp_eval_action(
                self, _at, _ap, _sig_in, _eff_delay, float(bus_eta_s),
                wrong_phase=_wrong_phase, remaining_red_s=float(remaining_red_s))
        except Exception:
            _r, _so, _tp, _bps, _cpc, _nsd, _std = 0.0, _sig_in, 0.0, 0.0, 0.0, 0.0, 0.0
        _hw_term = float(CPDQL_W_H) * _bus_occ * (abs(_sig_in) - abs(_so))
        _dly_term = float(_bps) - _cpc
        return (_hw_term + (1.0 - float(CPDQL_W_H)) * _dly_term,
                _so, _tp, max(0.0, _bps), max(0.0, _cpc), _nsd, _std)

    # ── Validate the action set: GE only on the bus phase; INS everywhere ────
    # (wrong-phase GE would extend the cross phase and push the bus later —
    #  paper's wrong-phase rejection).
    _valid_actions = []
    for _i, (_at, _ap) in enumerate(CPDQL_ACTION_SPACE):
        if _at == 'NO_ACTION':
            _valid_actions.append((_i, _at, _ap))
        elif _at == 'GE' and _phase_is_bus:
            _valid_actions.append((_i, _at, _ap))
        elif _at == 'INS' and not _phase_is_bus:
            _valid_actions.append((_i, _at, _ap))
    # If no discrete action is valid (wrong phase with GE-only grid state),
    # fall back to NO_ACTION rather than committing an invalid intervention.
    if len(_valid_actions) <= 1:
        _valid_actions = [(0, 'NO_ACTION', 0.0)]

    # ── Warm start: a NEW state bin is seeded with the paper's estimated
    # immediate reward per action so the first visit is not a cold zero-tie
    # (which would make argmax always pick NO_ACTION at index 0).
    _init_q = [0.0] * len(CPDQL_ACTION_SPACE)
    for _i, _at, _ap in _valid_actions:
        try:
            _init_q[_i] = _cpdql_sel_reward(_at, _ap)[0]
        except Exception:
            _init_q[_i] = 0.0

    # ── epsilon-greedy over the Q-table (train: CPDQL_TRAIN_EPSILON) ─────────
    _phase = str(globals().get('CPDQL_PHASE', 'per_seed'))
    if _phase == 'eval':
        _eff_eps = 0.0
    elif _phase == 'train':
        _eff_eps = float(globals().get('CPDQL_TRAIN_EPSILON', 0.3))
    else:
        _eff_eps = float(CPDQL_EPSILON)
    _use_explore = (_rnd_cpdql.random() < _eff_eps)
    q_vals = _cpdql_get_q(self.id, _state, init_vals=_init_q)
    _chosen_idx, _chosen_atype, _chosen_aparam = None, 'NO_ACTION', 0.0
    if _use_explore:
        _i, _at, _ap = _valid_actions[_rnd_cpdql.randrange(len(_valid_actions))]
        _chosen_idx = _i
    else:
        _best_i = max(range(len(_valid_actions)),
                      key=lambda _j: q_vals[_valid_actions[_j][0]])
        _chosen_idx = _valid_actions[_best_i][0]
    _chosen_atype, _chosen_aparam = CPDQL_ACTION_SPACE[_chosen_idx]

    # ── Minimum-gain gate (0 = disabled): never act for a near-free bus ──────
    _gain_min = float(globals().get('CPDQL_MIN_GAIN_S', CPDQL_MIN_GAIN_S) or 0.0)
    if _chosen_atype != 'NO_ACTION' and _eff_delay < _gain_min:
        _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0

    # ── Rows for the shared Pareto layer / reward CSV ────────────────────────
    _r_na, _so_na, _tp_na, _bps_na, _cpc_na, _nsd_na, _std_na = \
        _cpdql_sel_reward('NO_ACTION', 0.0)
    rows = [('NO_ACTION', 0.0, _r_na, _so_na, _tp_na, _bps_na, _cpc_na,
             _nsd_na, _std_na)]
    if _chosen_atype != 'NO_ACTION' and float(_chosen_aparam) > 0.0:
        _r_a, _so_a, _tp_a, _bps_a, _cpc_a, _nsd_a, _std_a = \
            _cpdql_sel_reward(_chosen_atype, _chosen_aparam)
        rows.append((action_label(_chosen_atype, _chosen_aparam),
                     float(_chosen_aparam), _r_a, _so_a, _tp_a, _bps_a,
                     _cpc_a, _nsd_a, _std_a))
        best_r, best_so, best_tp = _r_a, _so_a, _tp_a
        best_r_delta = _r_a - _r_na
    else:
        _chosen_atype, _chosen_aparam = 'NO_ACTION', 0.0
        best_r, best_so, best_tp, best_r_delta = _r_na, _so_na, _tp_na, 0.0

    _log_func(self, f"[CPDQL] inter={self.id} t={time:.1f} bus={veh_id} "
                    f"state={_state} sigma_in={_sig_in:.1f}s eta={float(bus_eta_s):.1f}s "
                    f"eff_delay={_eff_delay:.1f}s phase_is_bus={_phase_is_bus} "
                    f"explore={_use_explore} chosen={_chosen_atype}_{_chosen_aparam:.0f}s")

    # ── Closed-loop learning: log this decision + a delay snapshot so the
    # realized outcome (~1.5 cycles later) can be credited via _cpdql_update_q.
    if bool(globals().get('CPDQL_LEARN', True)) and _phase != 'eval':
        try:
            _d0b, _d0c = _bxt_delay_snapshot(self)
            _cyc = float(self._signal_cycle_s()) if hasattr(self, '_signal_cycle_s') \
                else float(getattr(self, 'cycle_len_s', 135.0) or 135.0)
            _cpdql_action_log[(int(self.id), int(veh_id))] = {
                'state': _state, 'action_idx': int(_chosen_idx),
                'atype': _chosen_atype, 'param': float(_chosen_aparam),
                't': float(time), 'delay_bus0': _d0b, 'delay_car0': _d0c,
                'due_t': float(time) + 1.5 * _cyc,
            }
        except Exception:
            pass

    return (_chosen_atype, _chosen_aparam, best_r, best_r_delta,
            best_so, best_tp, rows)


# ── Mode: BARGAIN_SPM — Nash bargaining game candidate generation ─────────────
# Ported (simplified) from kg/intersection_controller_lean.py: ETA detection
# level sets the bus bargaining weight; a stochastic-shockwave risk multiplier
# (cross-flow CV + saturation ratio) and cascade multiplier scale car cost; the
# main-approach car saving is credited symmetrically.

def dctsp_bargain(self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
                  no_act_delay, sigma_in, remaining_red_s=0.0):
    _wrong_phase = (current_phase != self.BusPhase)
    _bus_occ = float(getattr(self, 'BusOcc', 40.0))

    # Bus bargaining weight from ETA detection level
    if bus_eta_s < float(BG_DET_LVL_IMM_S):
        _w_bus = float(BG_BUS_W_IMM)
    elif bus_eta_s < float(BG_DET_LVL_NEAR_S):
        _w_bus = float(BG_BUS_W_NEAR)
    elif bus_eta_s < float(BG_DET_LVL_FAR_S):
        _w_bus = float(BG_BUS_W_FAR)
    else:
        _w_bus = float(BG_BUS_W_VFAR)

    # SPM risk multiplier: recent cross-flow variability + saturation ratio
    _risk_mult = 1.0
    try:
        _up = np.asarray(getattr(self, 'UpFlowList', []), dtype=float)
        if _up.ndim >= 2 and _up.shape[0] > 1 and _up.shape[1] > 0:
            _n_recent = min(5, _up.shape[1])
            _cross = _up[1:, -_n_recent:].ravel()
        else:
            _cross = np.asarray([], dtype=float)
        _cross = _cross[_cross > 0.0]
        if _cross.size > 0:
            _mean = float(np.mean(_cross))
            _cv = float(np.std(_cross)) / max(_mean, 1e-6)
            _sat_ratio = _mean / max(float(getattr(self, 'SaturationFlow', 1800.0)), 1.0)
            _unc = min(1.0, 0.5 * _cv + 0.5 * _sat_ratio)
            _risk_mult = 1.0 + float(BG_SPM_RISK_WEIGHT) * _unc
    except Exception:
        _risk_mult = 1.0

    # ── WOBJ objective targeting (Z1 delay / Z2 progression / Z3 headway) ──
    _wobj_alpha = float(globals().get('WOBJ_ALPHA', 1.0))
    _wobj_beta  = float(globals().get('WOBJ_BETA', 0.0))
    _wobj_gamma = float(globals().get('WOBJ_GAMMA', 0.0))
    _sigma_s = max(float(sigma_in), 0.0)
    _lateness_factor = min(_sigma_s / 30.0, 3.0)
    _eff_bus_w  = _wobj_alpha + _wobj_gamma * _lateness_factor
    _eff_cross_w = 1.0 + _wobj_beta

    # NO_ACTION baseline (inertia bonus keeps marginal actions from firing)
    r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
        self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
    r_na_bg = r_na + float(BG_NO_ACTION_BONUS_S)
    rows = [('NO_ACTION', 0.0, r_na_bg, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na)]

    _cands = []
    for (_at, _ap) in DCTSP_RL_ACTION_SPACE:
        if _at == 'NO_ACTION':
            continue
        # GE only helps when the bus phase is running; INS/ER only when not.
        # GREEN_REALLOC is meaningful in both (extend-as-GE vs advance bus green).
        if _at == 'GE' and _wrong_phase:
            continue
        if _at in ('INS', 'EARLY_RED') and not _wrong_phase:
            continue
        _cands.append((_at, _ap))

    best_lbl, best_param, best_r = 'NO_ACTION', 0.0, r_na_bg
    best_so, best_tp = so_na, tp_na
    best_atype = 'NO_ACTION'
    best_cpc = cpc_na          # cross cost of the chosen action (for net-benefit veto)
    for (_at, _ap) in _cands:
        r, so, tp, bps, cpc, nsd, std = _dctsp_eval_action(
            self, _at, _ap, sigma_in, no_act_delay, bus_eta_s,
            wrong_phase=_wrong_phase, remaining_red_s=remaining_red_s)
        # Main-approach car saving (phases=[0]); zero for EARLY_RED on the bus
        # phase — cutting the bus green gives the main approach nothing.
        if _at == 'EARLY_RED' and not _wrong_phase:
            _main_sav = 0.0
        else:
            try:
                _main_sav = float(self._dctsp_cross_traffic_delay_s(
                    max(0.0, float(_ap)), phases=[0]))
            except Exception:
                _main_sav = 0.0
        r_bg = (_eff_bus_w * _w_bus * bps
                - _eff_cross_w * _risk_mult * float(BG_CASCADE_MULT) * cpc
                + _main_sav)
        _lbl = action_label(_at, _ap)
        rows.append((_lbl, _ap, r_bg, so, tp, bps, cpc, nsd, std))
        if r_bg > best_r and bps > 0.0:
            best_lbl, best_param, best_r = _lbl, _ap, r_bg
            best_so, best_tp, best_atype = so, tp, _at
            best_cpc = cpc            # cross cost of the chosen action (incl. cascade)

    # Gates: minimum bus delay and minimum bargaining gain
    eff_delay = max(0.0, float(no_act_delay) - float(ZIG_PHASE_OVERLAP_S))
    _min_gain_pax_s = float(BG_MIN_GAIN_S) * max(_bus_occ, 1.0)
    if (eff_delay < float(BG_MIN_BUS_DELAY_S)
            or (best_r - r_na_bg) < _min_gain_pax_s):
        best_atype, best_lbl, best_param = 'NO_ACTION', 'NO_ACTION', 0.0
        best_r, best_so, best_tp = r_na_bg, so_na, tp_na
    # NET-BENEFIT VETO (2026-09-14): BARGAIN's selection is a WEIGHTED SUM
    # (_eff_bus_w*bps - _eff_cross_w*cpc), so a high bus weight can still pick a
    # NET-NEGATIVE action -- unlike CELLQLEARN_GATED it had no HARD veto. Add the
    # same gate: reject the chosen action unless TOTAL-passenger bus benefit
    # (weight-neutral) exceeds its cross cost. best_cpc already includes the
    # measured side cost + (when it fires) the downstream cascade, so this is the
    # lever that lets the network cost actually STOP a harmful bargain.
    if (best_atype != 'NO_ACTION'
            and bool(globals().get('BXT_NET_BENEFIT_GATE', False))):
        _bus_benefit_total = max(0.0, float(no_act_delay)) * max(_bus_occ, 1.0)
        if _bus_benefit_total <= float(best_cpc):
            _log_func(self, f"[BARGAIN] inter={self.id} NET-BENEFIT VETO "
                            f"benefit={_bus_benefit_total:.0f} <= cpc={best_cpc:.0f} "
                            f"-> NO_ACTION")
            best_atype, best_lbl, best_param = 'NO_ACTION', 'NO_ACTION', 0.0
            best_r, best_so, best_tp = r_na_bg, so_na, tp_na

    _log_func(self, f"[BARGAIN] inter={self.id} t={time:.1f} bus={veh_id} "
                    f"w_bus={_w_bus:.2f} risk={_risk_mult:.2f} "
                    f"wobj=(a={_wobj_alpha:.2f} b={_wobj_beta:.2f} g={_wobj_gamma:.2f}) "
                    f"eff_bw={_eff_bus_w:.2f} eff_cw={_eff_cross_w:.2f} "
                    f"chosen={best_lbl} r={best_r:.1f}")

    return (best_atype, best_param, best_r, best_r - r_na_bg,
            best_so, best_tp, rows)


def dctsp_nash_gate(self, time, timeSta, acycle, bus_eta_s, veh_id,
                    current_phase, no_act_delay, sigma_in, remaining_red_s=0.0):
    """Run the NashGate name through the implemented bargaining controller."""
    result = dctsp_bargain(
        self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
        no_act_delay, sigma_in, remaining_red_s=remaining_red_s)
    _log_func(self, f"[NASH_GATE] inter={self.id} t={time:.1f} bus={veh_id} "
                    f"chosen={result[0]} param={float(result[1]):.1f}")
    return result


def _nash_bargain_pick(frontier, p_T=1.0, p_C=1.0, eps=1e-6):
    """Generalized Nash bargaining selection over a discrete action frontier.

    `frontier`: list of (bps, cpc) pax·s pairs for the ACTIVE candidate actions
    (NO_ACTION excluded). bps = transit benefit (pax·s saved, >=0); cpc =
    cross-street cost added (pax·s, >=0). Returns (best_index, best_value) into
    `frontier`, or (None, 0.0) if NO action produces a net corridor surplus -- in
    which case NO_ACTION is the correct bargaining outcome.

    A TSP action is a genuine BARGAIN only when it creates a cooperative surplus:
    the bus saves MORE passenger-seconds than the cross street loses (bps > cpc).
    Actions that fail this (cpc >= bps) are net-harmful transfers and are EXCLUDED
    from the bargaining set (individual rationality / efficiency). Among the
    net-positive actions the Nash solution maximizes the PRODUCT
        N = bps**p_T * surplus**p_C ,   surplus = bps - cpc
    -- balancing raw transit benefit (bps) against the NET social gain (surplus,
    i.e. how little cross cost it takes). p_T, p_C are bargaining powers
    (symmetric = 1,1). Scale-invariant: multiplying all pax·s by a constant does
    not change the argmax (the Nash axiom of invariance to affine rescaling).

    NOTE (2026-09-03 fix): the previous form used a threat point Cmax=max(cpc) and
    accepted any action with bps>0 and Cmax-cpc>0 -- NO net-benefit constraint, so
    it fired net-harmful actions (bps=276 vs cpc=3550) and a single saturated-
    junction outlier in Cmax neutralized the cross penalty for every action ->
    massive over-acting (KG NASH_BARGAIN ranked worst). Requiring surplus>0 and
    using the surplus itself as the cross-side gain removes both pathologies.
    """
    if not frontier:
        return (None, 0.0)
    best_i, best_N = None, 0.0
    for i, (bps, cpc) in enumerate(frontier):
        bps = float(bps); cpc = float(cpc)
        surplus = bps - cpc               # net corridor pax·s (>0 to bargain)
        if bps <= eps or surplus <= eps:  # individual rationality: net-positive only
            continue
        if float(p_T) <= 0.0:
            # p_T=0 -> PURE NET-SURPLUS (utilitarian / Coase-efficient) objective:
            # select the action that reduces TOTAL passenger delay the MOST
            # (surplus = bus pax·s saved - cross pax·s cost). This is the
            # "reduce net total passenger delay" outcome the game is meant to
            # deliver -- the symmetric Nash PRODUCT (p_T=1) instead maximizes
            # bps*surplus, which over-weights raw bus benefit and does NOT
            # minimise total pax delay. (2026-09-10)
            N = surplus if float(p_C) == 1.0 else surplus ** float(p_C)
        else:
            N = (bps ** float(p_T)) * (surplus ** float(p_C))
        if N > best_N:
            best_N, best_i = N, i
    return (best_i, best_N)


def _nash_corridor_solve(order, frontiers, etas, project_fn, occ,
                         w_nb=0.5, max_iter=10, tol=0.01, p_T=1.0, p_C=1.0):
    """Pure Gauss-Seidel best-response solver for the corridor Nash game (Tier 2).

    `order`       : junction ids in bus-travel order (THIS junction first).
    `frontiers`   : {jid: [(at, ap, bps, cpc, s_saved), ...]} real action frontier.
    `etas`        : {jid: bus_eta_s at that junction}.
    `project_fn(jid, eta, s)` : downstream landing cost (pax·s, + = worse red) of
                    saving `s` bus-seconds at `jid`; only called when `jid` has a
                    downstream neighbour still in `order`. May raise -> treated 0.

    Each junction picks the Nash-bargaining action whose transit gain is its local
    benefit minus the NEIGHBOUR-weighted downstream landing cost, credited by the
    downstream junction's own planned saving (green-wave hand-off
    occ*min(s_self, s_down)). Iterated until savings stabilise (max |Δs| < tol) or
    `max_iter`. Returns {jid: chosen_index_or_None}. Pure and Aimsun-free."""
    active = [j for j in order if frontiers.get(j)]
    savings = {j: 0.0 for j in active}
    chosen = {j: None for j in active}
    for _ in range(max(1, int(max_iter))):
        max_delta = 0.0
        for i, j in enumerate(active):
            nxt = active[i + 1] if i + 1 < len(active) else None
            s_down = savings.get(nxt, 0.0) if nxt is not None else 0.0
            fr = []
            for (_at, _ap, _bps, _cpc, _s) in frontiers[j]:
                net = 0.0
                if nxt is not None:
                    try:
                        _dp = float(project_fn(j, etas.get(j, 0.0), _s))
                    except Exception:
                        _dp = 0.0
                    net = max(0.0, _dp - occ * min(_s, s_down))
                fr.append((max(0.0, float(_bps) - float(w_nb) * net), float(_cpc)))
            bi, _N = _nash_bargain_pick(fr, p_T, p_C)
            new_s = savings[j] if bi is None else float(frontiers[j][bi][4])
            max_delta = max(max_delta, abs(new_s - savings[j]))
            savings[j] = new_s
            chosen[j] = bi
        if max_delta < float(tol):
            break
    return chosen


def _nash_duration_search(self, atype, d_lo, d_hi, sigma_in, no_act_delay,
                          bus_eta_s, wrong_phase, remaining_red_s, p_T, p_C):
    """Bargain over the action DURATION at integer-second resolution for one
    action type, instead of the naive coarse {5,10,15} grid.

    Under the net-surplus Nash objective each duration's score
    bps(d)^p_T * (bps(d)-cpc(d))^p_C is SELF-CONTAINED (no cross-candidate
    coupling) and unimodal in d -- bus benefit saturates as the bus clears while
    cross cost keeps growing, so surplus rises then falls. A coarse pass (~5
    points) locates the peak's region and an integer refine (+/-3 s) around it
    finds the true optimum in ~12 evals instead of sweeping the whole range.
    Returns the (atype, dur, so, tp, bps, cpc) rows evaluated; the caller
    Nash-picks across ALL types and durations."""
    d_lo = max(1, int(round(d_lo)))
    d_hi = max(d_lo, int(round(d_hi)))
    _cache = {}
    _rows = []
    def _ev(d):
        d = int(d)
        if d in _cache:
            return _cache[d]
        try:
            r, so, tp, bps, cpc, nsd, std = _dctsp_eval_action(
                self, atype, float(d), sigma_in, no_act_delay, bus_eta_s,
                wrong_phase=wrong_phase, remaining_red_s=remaining_red_s)
            _cache[d] = (max(0.0, float(bps)), max(0.0, float(cpc)), so, tp)
            _rows.append((atype, float(d), _cache[d][2], _cache[d][3],
                          _cache[d][0], _cache[d][1]))
        except Exception:
            _cache[d] = None
        return _cache[d]
    def _score(v):
        if not v:
            return -1.0
        bps, cpc = v[0], v[1]
        s = bps - cpc
        return (bps ** p_T) * (s ** p_C) if (bps > 0.0 and s > 0.0) else 0.0
    # coarse pass across the range
    if d_hi > d_lo:
        _n = min(5, d_hi - d_lo + 1)
        _coarse = sorted(set(int(round(d_lo + i * (d_hi - d_lo) / (_n - 1)))
                             for i in range(_n)))
    else:
        _coarse = [d_lo]
    _best_d, _best_s = d_lo, -1.0
    for _d in _coarse:
        _s = _score(_ev(_d))
        if _s > _best_s:
            _best_s, _best_d = _s, _d
    # integer refine +/-3 s around the coarse optimum
    for _d in range(max(d_lo, _best_d - 3), min(d_hi, _best_d + 3) + 1):
        _ev(_d)
    return _rows


def _continuous_corridor_penalty(self, cand, time, timeSta):
    """Bus-free downstream landing cost (pax*s) for each no-bus continuous
    candidate -- the CROSS-INTERSECTION coupling of the continuous game.

    For a green extension of `s` seconds at THIS junction, ask the corridor
    coordinator how the through-platoon's shifted arrival lands at the downstream
    corridor junctions' LIVE signal windows, via project_chain_delay_paxs called
    with veh_id=-1: no tracker -> geometry travel time (corridor_pos gaps) and a
    synthetic arrival, reading each downstream junction's own signal plan. No bus
    is required -- this is the global signal-plan mechanism. Positive = the
    extension pushes the platoon into a downstream RED (coordination COST); only
    costs are charged (a benefit landing is already rewarded via the local
    surplus). Returns [penalty_paxs per cand]; all-zero if no coordinator / route
    data (degrades cleanly to the local continuous game)."""
    n = len(cand)
    pen = [0.0] * n
    _coord = getattr(self, '_corridor_coord', None)
    if _coord is None or not hasattr(_coord, 'project_chain_delay_paxs'):
        return pen
    _car_occ = float(getattr(self, 'CarOcc', 1.6) or 1.6)
    _atid = int(getattr(self, 'id', getattr(self, 'node_id', -1)))
    _green_giving = ('GE', 'GREEN_REALLOC', 'INS', 'INS_POST', 'INS_PRETERM')
    for i, c in enumerate(cand):
        _at, _ap = c[0], c[1]
        _s = abs(float(_ap or 0.0)) if _at in _green_giving else 0.0
        if _s <= 0.0:
            continue
        try:
            _d = float(_coord.project_chain_delay_paxs(
                _atid, -1, float(time), float(timeSta), 0.0, _s, _car_occ))
            pen[i] = max(0.0, _d)
        except Exception:
            pen[i] = 0.0
    return pen


def dctsp_nash_bargain(self, time, timeSta, acycle, bus_eta_s, veh_id,
                       current_phase, no_act_delay, sigma_in, remaining_red_s=0.0):
    """Real (generalized) Nash bargaining TSP -- Transit vs Cross-street game.

    Tier 1 (per junction): maximizes the Nash PRODUCT of gains-over-threat (see
    `_nash_bargain_pick`), with bargaining powers p_T=NASH_BUS_WEIGHT,
    p_C=NASH_CROSS_WEIGHT. Tier 2 (NASH_CORRIDOR_MODE): delegates the selection
    to the corridor coordinator's best-response solver, which couples this
    junction to the downstream route (green-wave hand-off) and iterates to a
    Nash equilibrium of the corridor game. Falls back to Tier 1 whenever the
    coordinator / downstream data is unavailable.
    """
    _bus_occ = max(float(getattr(self, 'BusOcc', 40.0) or 40.0), 1.0)
    _overlap = float(globals().get('ZIG_PHASE_OVERLAP_S', 0.0) or 0.0)
    eff_delay = max(0.0, float(no_act_delay) - _overlap)
    wrong_phase = (int(current_phase) != int(self.BusPhase))

    r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
        self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
    rows = [('NO_ACTION', 0.0, 0.0, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na)]

    # ── CONTINUOUS play (no bus present) ──────────────────────────────────────
    # The monitor path calls this with veh_id=-1 / bus_eta_s=1e9: there is no bus,
    # so play the SAME bargaining game on the current traffic STATE. The transit
    # side's bus term is 0, leaving the through-traffic (mainline) served by
    # extending the CURRENT green as its payoff, bargained against the cross cost
    # exactly as in the bus-present game (surplus = mainline_paxs - cross_paxs,
    # individual-rationality surplus>0). Only green-giving actions on the current
    # phase are meaningful (INS/EARLY_RED insert a bus phase). Enabled via
    # NASH_CONTINUOUS_MODE; reached only when CONTINUOUS_MONITOR_MODE routed here.
    _monitor = (int(veh_id) < 0) or (float(bus_eta_s) > 1.0e8)
    if _monitor and not bool(globals().get('NASH_CONTINUOUS_MODE', True)):
        return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)

    # gate 1: do not bargain for a barely-delayed bus (bus-present game only)
    if not _monitor and eff_delay < float(globals().get('NASH_MIN_BUS_DELAY_S', 5.0)):
        return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)

    p_T = float(globals().get('NASH_BUS_WEIGHT', 1.0))
    p_C = float(globals().get('NASH_CROSS_WEIGHT', 1.0))
    if _monitor:
        # No bus: the current green IS the served phase (never "wrong phase"),
        # and bus-insertion actions are meaningless. The continuous game is
        # utilitarian by default (p_T=0 -> maximise net surplus = min TOTAL pax
        # delay); the bus-present game keeps NASH_BUS_WEIGHT.
        wrong_phase = False
        p_T = float(globals().get('CONTINUOUS_BARGAIN_BUS_WEIGHT', 0.0))

    # phase-appropriate candidate actions (same filter as dctsp_bargain)
    cand = []                       # (at, ap, so, tp, bps, cpc)
    if bool(globals().get('NASH_INTEGER_DURATIONS', False)):
        # Bargain over the DURATION at integer-second resolution per action type
        # rather than the naive coarse {5,10,15} grid.
        _ge_hi = int(max(1.0, float(globals().get('MAX_GE_EXTENSION_S', 10.0) or 10.0)))
        _ins_lo = int(max(1.0, float(globals().get('DCTSP_MIN_INS_DURATION_S', 5.0))))
        _ins_hi = int(max(_ins_lo, float(globals().get('DCTSP_MAX_INS_DURATION_S', 25.0))))
        if wrong_phase:
            _types = [('INS', _ins_lo, _ins_hi), ('EARLY_RED', 5, 30),
                      ('GREEN_REALLOC', 1, _ge_hi)]
        else:
            _types = [('GE', 1, _ge_hi), ('GREEN_REALLOC', 1, _ge_hi)]
        for (_at, _lo, _hi) in _types:
            for (_a, _d, _so, _tp, _bps, _cpc) in _nash_duration_search(
                    self, _at, _lo, _hi, sigma_in, no_act_delay, bus_eta_s,
                    wrong_phase, remaining_red_s, p_T, p_C):
                cand.append((_a, _d, _so, _tp, _bps, _cpc))
                rows.append((action_label(_a, _d), _d, 0.0, _so, _tp,
                             _bps, _cpc, 0.0, 0.0))
    else:
        for (_at, _ap) in DCTSP_RL_ACTION_SPACE:
            if _at == 'NO_ACTION':
                continue
            if _monitor and _at not in ('GE', 'GREEN_REALLOC'):
                continue          # no-bus: only extend/realloc the CURRENT green
            if _at == 'GE' and wrong_phase:
                continue
            if _at in ('INS', 'EARLY_RED') and not wrong_phase:
                continue
            try:
                r, so, tp, bps, cpc, nsd, std = _dctsp_eval_action(
                    self, _at, _ap, sigma_in, no_act_delay, bus_eta_s,
                    wrong_phase=wrong_phase, remaining_red_s=remaining_red_s)
            except Exception:
                continue
            bps = max(0.0, float(bps)); cpc = max(0.0, float(cpc))
            cand.append((_at, _ap, so, tp, bps, cpc))
            rows.append((action_label(_at, _ap), _ap, 0.0, so, tp, bps, cpc, nsd, std))
    if not cand:
        return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)

    # ── Tier 2: corridor best-response (couples junction to the bus route) ──
    # Returns an int index into `cand`, or None meaning the corridor equilibrium
    # for THIS junction is NO_ACTION. Only an EXCEPTION falls back to Tier 1.
    _bi = None
    _corridor = False
    _corridor_ran = False
    _coord = getattr(self, '_corridor_coord', None)
    if (not _monitor and bool(globals().get('NASH_CORRIDOR_MODE', False))
            and _coord is not None
            and hasattr(_coord, 'nash_corridor_bestresponse')):
        try:
            _bi = _coord.nash_corridor_bestresponse(
                self, veh_id, time, timeSta, bus_eta_s, _bus_occ,
                [(c[0], c[1], c[4], c[5]) for c in cand], p_T, p_C)
            _corridor_ran = True
            _corridor = True
        except Exception as _e:
            _log_func(self, f"[NASH_CORRIDOR] inter={self.id} fallback (err {_e!r})")
            _corridor_ran = False
            _bi = None

    if _corridor_ran:
        if _bi is None:                          # corridor equilibrium = do nothing
            return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)
    else:
        # ── Tier 1: local Nash bargain ──
        # Bargain on the FULL bus-phase benefit (bus + mainline through traffic)
        # vs the cross cost, so the net surplus is the TOTAL passenger-delay
        # change (see _nash_phase_total_bps). The green-wave seconds inside the
        # corridor solver stay bus-only; that path is Tier 2, not here.
        # CONTINUOUS CORRIDOR game: on a no-bus tick, discount each candidate's
        # benefit by the bus-free downstream landing cost (cross-intersection
        # coupling) so the continuous game does not shove queues one junction
        # downstream. Bus-present bargaining is unchanged (Tier 2 owns that).
        _pen = None
        _corr_cont = (_monitor
                      and bool(globals().get('CONTINUOUS_CORRIDOR_MODE', False)))
        if _corr_cont:
            _pen = _continuous_corridor_penalty(self, cand, time, timeSta)
            _wnb = float(globals().get('CONTINUOUS_CORRIDOR_NEIGHBOR_W', 0.5))
        _frontier = []
        for _i, _c in enumerate(cand):
            _bt = _nash_phase_total_bps(self, _c[0], _c[1], _c[4])
            if _pen is not None:
                _bt = max(0.0, _bt - _wnb * _pen[_i])
            _frontier.append((_bt, _c[5]))
        _bi, _ = _nash_bargain_pick(_frontier, p_T, p_C)
        if _bi is None:
            return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)
        if _corr_cont and _pen and _pen[_bi] > 0.0:
            _corridor = True     # tag the log: corridor coupling shaped the pick

    _at, _ap, _so, _tp, _bps, _cpc = cand[_bi]
    # gate 2: minimum meaningful transit gain (kept BUS-only on purpose -- this
    # is a bus-priority controller: do not fire for a negligible bus saving even
    # if the mainline term is large; gate 1 already required a delayed bus).
    # Skipped in continuous (no-bus) play: there is no bus term to gate; the
    # engine's CONTINUOUS_MONITOR_MIN_GAIN_PAXS guard instead requires the SURPLUS
    # (returned below) to clear a minimum before committing.
    if not _monitor and _bps < float(globals().get('NASH_MIN_GAIN_S', 5.0)) * _bus_occ:
        return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)

    # Surplus / Nash value are on the FULL phase benefit (bus + mainline), so a
    # net-surplus (p_T=0) pick is exactly "minimise total passenger delay".
    _bps_tot = _nash_phase_total_bps(self, _at, _ap, _bps)
    _surplus = _bps_tot - _cpc           # net corridor pax·s of the chosen action
    _N = (_bps_tot ** p_T) * (max(0.0, _surplus) ** p_C)
    # Bus-present: report the Nash value. Continuous (no bus): report the SURPLUS
    # (pax·s) so the engine's monitor commit guard threshold is in pax·s units.
    _ret = max(0.0, _surplus) if _monitor else _N
    _log_func(self, f"[NASH_BARGAIN]{' [monitor]' if _monitor else ''} "
                    f"inter={self.id} t={time:.1f} bus={veh_id} "
                    f"pT={p_T:.2f} pC={p_C:.2f} surplus={_surplus:.0f} "
                    f"chosen={action_label(_at, _ap)} bps_bus={_bps:.0f} "
                    f"bps_phase={_bps_tot:.0f} cpc={_cpc:.0f} "
                    f"N={_N:.1f}{' [corridor]' if _corridor else ''}")
    return (_at, _ap, _ret, _ret, _so, _tp, rows)


# ── Mode: CELLQLEARN_DP — CellQ-Learn with Dynamic Programming ───────────────
# V2X-coordinated TSP: queue-length prediction via CTM + DP backward recursion
# to find the optimal TSP action sequence along the transit route.
# Reference: Huang H.-K. & Hsu Y.-T. (2025), Transportation Letters.

def dctsp_cellqlearn_dp(self, time, timeSta, acycle, bus_eta_s, veh_id,
                         current_phase, no_act_delay, sigma_in, remaining_red_s=0.0):
    """Coordinated TSP via dynamic programming with CTM queue prediction.

    DP backward recursion from downstream intersections to the current one,
    computing the Pareto-optimal sequence of TSP actions that minimizes total
    passenger delay (bus + general traffic) along the corridor.

    Returns (best_type, best_param, best_r, best_r_delta, best_sigma_out,
    best_t_poz, rows) — same contract as dctsp_bxt / dctsp_zig.
    """
    dt          = float(CELLQLEARN_DP_DT_S)
    q_sat_vps   = float(getattr(self, 'SaturationFlow', 1800.0)) / 3600.0
    k_jam       = float(getattr(self, 'JamDensity', 200.0))
    _bus_occ    = float(getattr(self, 'BusOcc', 40.0))
    _car_occ    = float(CELLQLEARN_DP_CAR_OCC)
    _cycle_s = float(self._signal_cycle_s()) if hasattr(self, '_signal_cycle_s') else float(self.config.get('CycleTime', 135.0) or 135.0)
    _bus_g_base = float(getattr(self, 'BusPhaseDuration', 20.0))
    _wrong_phase = (int(current_phase) != int(self.BusPhase))
    _cap_veh    = k_jam * 0.15

    # ── Estimate initial bus-approach queue (same LWR back-shockwave as BXT) ──
    try:
        upf = np.asarray(getattr(self, 'UpFlowList', np.zeros((1, 1))), dtype=float)
        rdt = np.asarray(getattr(self, 'RedDurationList', np.zeros((1, 1))), dtype=float)
        upf_bus = upf[0].ravel() if upf.ndim >= 2 and upf.shape[0] > 0 else np.zeros(1)
        rdt_bus = rdt[0].ravel() if rdt.ndim >= 2 and rdt.shape[0] > 0 else np.zeros(1)
        pos_flow = upf_bus[upf_bus > 0.0]
        pos_red = rdt_bus[(rdt_bus > 0.0) & (rdt_bus < 2.0 * _cycle_s)]
        q_arr_bus_vps = (float(np.mean(pos_flow)) / 3600.0
                         if pos_flow.size > 0 else 300.0 / 3600.0)
        t_red_past = (float(np.max(pos_red)) if pos_red.size > 0 else 60.0)
        k_arr_b = q_arr_bus_vps * k_jam / max(q_sat_vps, 1e-9)
        w_back_b = q_arr_bus_vps / max(k_jam - k_arr_b, 1.0)
        n0_bus = max(0.0, w_back_b * t_red_past * k_jam)
    except Exception:
        q_arr_bus_vps = 300.0 / 3600.0
        n0_bus = 5.0
        t_red_past = 60.0

    # ── Passenger weighting for the approach cell ────────────────────────────
    # `n0_bus` is the LWR/shockwave estimate of the WHOLE approach queue in
    # vehicles and `q_arr_bus_vps` is the WHOLE approach flow -- neither is
    # bus-only -- so passing `_bus_occ` (40 pax/veh) into _ctm_delay_pax priced
    # every queued car as a 40-passenger bus (~16x overstatement).  Same defect
    # fixed in dctsp_bxt, where it drove constant max-length extensions and
    # gridlocked kg seeds 400/500.  Weight the cell by what it holds: the
    # subject bus at BusOcc, the remaining queue at CarOcc.
    _n_cell = max(float(n0_bus), 1.0)
    _cell_occ = ((min(1.0, _n_cell) * _bus_occ
                  + max(0.0, _n_cell - 1.0) * float(_car_occ)) / _n_cell)

    def _ctm_delay_pax(n0, q_arr, q_sat, t_wait_red, g_dur, occ):
        delay = 0.0
        n = max(0.0, float(n0))
        for _ in range(max(0, int(round(float(t_wait_red) / dt)))):
            n = min(n + q_arr * dt, _cap_veh)
            delay += n * dt
        for _ in range(max(0, int(round(float(g_dur) / dt)))):
            q_out = min(q_sat, n / max(dt, 1e-9))
            n = max(0.0, n + q_arr * dt - q_out * dt)
            delay += n * dt
        return delay * float(occ)

    def _eval_stage_action(atype, aparam_s):
        """Evaluate one TSP action at a single intersection stage.
        Returns (bus_delay_paxs, side_delay_paxs, effective_red_saved)."""
        a_s = float(aparam_s)
        if atype == 'NO_ACTION':
            if _wrong_phase:
                t_wait = float(remaining_red_s); g_bus = _bus_g_base
            else:
                t_wait = 0.0; g_bus = float(remaining_red_s)
            d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                   t_wait, g_bus, _cell_occ)
            d_side = float(self._dctsp_cross_traffic_delay_s(0.0))
            return d_bus, d_side, 0.0
        if atype == 'GE':
            if not _wrong_phase:
                d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       0.0, float(remaining_red_s) + a_s, _cell_occ)
                d_side = float(self._dctsp_cross_traffic_delay_s(a_s))
            else:
                d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       float(remaining_red_s) + a_s, _bus_g_base, _cell_occ)
                d_side = float(self._dctsp_cross_traffic_delay_s(0.0))
            return d_bus, d_side, a_s
        if atype in ('INS', 'INS_POST'):
            t_wait = float(remaining_red_s) + float(INS_INTERGREEN_S)
            # ETA gate (mirrors _dctsp_eval_action INS rule): a bus still
            # `bus_eta_s` away cannot catch a short insertion — otherwise the
            # CTM queue model credits phantom savings from a few seconds of
            # green (INS_PRETERM_3 claimed up to ~62 000 pax·s).
            if float(bus_eta_s) > (a_s + float(INS_INTERGREEN_S)):
                d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       t_wait, _bus_g_base, _cell_occ)
            else:
                d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       t_wait, a_s, _cell_occ)
            d_side = float(self._dctsp_cross_traffic_delay_s(t_wait + a_s))
            return d_bus, d_side, a_s

        # --- V2X-coordinated DP-specific actions: green reallocation, early red ---
        if atype == 'GREEN_REALLOC':
            if not _wrong_phase:
                d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       0.0, float(remaining_red_s) + a_s, _cell_occ)
            else:
                g_advance = max(0.0, a_s - float(remaining_red_s))
                t_wait = max(0.0, float(remaining_red_s) - a_s)
                d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       t_wait, _bus_g_base + g_advance, _cell_occ)
            d_side = float(self._dctsp_cross_traffic_delay_s(a_s))
            return d_bus, d_side, a_s
        if atype == 'EARLY_RED':
            saved_red = min(float(remaining_red_s), a_s)
            d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                   saved_red, _bus_g_base + a_s * 0.5, _cell_occ)
            d_side = float(self._dctsp_cross_traffic_delay_s(a_s))
            return d_bus, d_side, a_s

        return 1e9, 0.0, 0.0

    # ── DP Action space ─────────────────────────────────────────────────────
    _dp_actions = [
        ('NO_ACTION', 0.0),
        ('GE', 5.0), ('GE', 10.0), ('GE', 15.0),
('INS', 10.0), ('INS', 15.0), ('INS', 20.0), ('INS', 25.0),
        ('GREEN_REALLOC', 5.0), ('GREEN_REALLOC', 10.0), ('GREEN_REALLOC', 15.0),
        ('EARLY_RED', 10.0), ('EARLY_RED', 20.0),
    ]
    _dp_action_indices = list(range(len(_dp_actions)))

    _horizon_s = float(CELLQLEARN_DP_HORIZON_S)
    _coord_w   = float(CELLQLEARN_DP_COORD_WEIGHT)
    _stage_s   = float(CELLQLEARN_DP_STAGE_S)
    _dp_stages = max(1, int(_horizon_s / _stage_s))

    # Real accumulated side-red at this junction: longest red held across all
    # phases becomes the cross-approach queue elapsed (Q_0 > 0), so the DP
    # side penalty is grounded in actual queue state instead of a 0.3 fudge.
    try:
        _rdt_all = np.asarray(getattr(self, 'RedDurationList', np.zeros((1, 1))), dtype=float)
        _side_red_elapsed = float(np.max(_rdt_all)) if _rdt_all.size else float(t_red_past)
    except Exception:
        _side_red_elapsed = float(t_red_past)
    _side_red_elapsed = max(0.0, min(_side_red_elapsed, 2.0 * _cycle_s))

    def _dp_proj_side_delay(_ap):
        """Real side-queue pax·s imposed by action red `_ap`: uses the live
        SideUpFlowList/SideUpDenList shockwave model when available (grounded
        in actual accumulated side queue), else the analytic cross model.
        Scaled by CROSS_TRAFFIC_COST_MULTIPLIER so it competes with the
        primary CTM terms (the analytic path already applies that factor)."""
        _cmult = float(CROSS_TRAFFIC_COST_MULTIPLIER or 2.0)
        try:
            _fn = getattr(self, '_compute_side_delay_penalty', None)
            if _fn is not None:
                _v = _fn(max(0.0, float(_ap)), _suppress_log=True)
                if _v and float(_v[0]) > 0.0:
                    return float(_v[0]) * _cmult
        except Exception:
            pass
        try:
            return float(self._dctsp_cross_traffic_delay_s(
                max(0.0, float(_ap)), queue_elapsed_s=_side_red_elapsed))
        except Exception:
            return 0.0

    # For now, the DP stages are virtual "look-ahead windows" along the
    # bus trajectory. Each stage corresponds to an arrival at a downstream
    # intersection or a future cycle boundary.
    # ── DP backward recursion ──────────────────────────────────────────────
    # DP[i][q_state] = min cumulative delay from stage i onward
    # i=0 is "now" (first stage), i=dp_stages-1 is the furthest horizon.
    # We discretise the "remaining queue" state as a coarse bin.
    _n_stages = min(_dp_stages, 6)

    # ── Per-action evaluation at the current stage ─────────────────────────
    _na_dbus, _na_dside, _na_saved = _eval_stage_action('NO_ACTION', 0.0)
    _baseline_total = _na_dbus + _na_dside

    _cand_rows = []
    for _ai, (_at, _ap) in enumerate(_dp_actions):
        if _at == 'NO_ACTION':
            _cand_rows.append((_at, _ap, _na_dbus + _na_dside, _na_dbus, _na_dside, 0.0, 0.0))
            continue
        if _at == 'GE' and _wrong_phase:
            continue
        if _at in ('INS', 'INS_POST', 'EARLY_RED') and not _wrong_phase:
            continue
        _dbus, _dside, _saved = _eval_stage_action(_at, _ap)
        if _dbus >= 1e8:
            continue

        # ── DP look-ahead: estimate downstream delay impact ─────────────────
        # Local CTM self-projection (future queue at THIS junction), then ADD
        # the REAL downstream-junction projection (Z2, corridor-aware): the
        # bus time shift here moves its arrival at the NEXT managed junction;
        # project the red-wait there from the live downstream phase schedule.
        _dp_coord_penalty = 0.0
        _dp_proj_dside = _dp_proj_side_delay(_ap)
        _remaining_horizon = max(0.0, _horizon_s - float(_ap))
        _dp_extra_stages = int(_remaining_horizon / _stage_s)
        for _si in range(min(_dp_extra_stages, 3)):
            _stage_offset = (_si + 1) * _stage_s
            _dp_proj_n0 = max(0.0, n0_bus - _saved * 0.7
                              + q_arr_bus_vps * _stage_offset)
            _dp_proj_dbus = _ctm_delay_pax(
                _dp_proj_n0, q_arr_bus_vps, q_sat_vps,
                0.0, _bus_g_base, _cell_occ)
            _dp_coord_penalty += (_dp_proj_dbus + _dp_proj_dside) * (_coord_w ** (_si + 1))
        try:
            _coord = getattr(self, '_corridor_coord', None)
            if _coord is not None:
                # The bus can only be pulled forward by as much as it is
                # actually delayed without action — cap the downstream shift.
                _shift_sec = min(float(_saved), max(0.0, float(no_act_delay)))
                if _shift_sec > 0.0:
                    _dp_coord_penalty += float(_coord.project_downstream_delay_paxs(
                        int(self.id), int(veh_id), float(time), float(timeSta),
                        float(bus_eta_s), _shift_sec, _bus_occ))
        except Exception:
            pass

        _total = _dbus + _dside + _dp_coord_penalty
        _cand_rows.append((_at, _ap, _total, _dbus, _dside, _saved, _dp_coord_penalty))

    # ── Saturation avoidance guard ──────────────────────────────────────────
    try:
        _o_d = (_safe_float(self._safe_array_sum(getattr(self, 'OtherDelay', [0])))
                + _safe_float(self._safe_array_sum(
                    getattr(self, 'SideDelayBaseline', [0]))))
        _eff_delay = max(0.0, float(no_act_delay) - float(ZIG_PHASE_OVERLAP_S))
        _bus_p = _eff_delay * _bus_occ
        _side_p = max(0.0, _o_d) * _car_occ
        _side_ratio = _side_p / max(_bus_p, 1.0)
    except Exception:
        _side_ratio = 0.0

    _eff_delay_gate = max(0.0, float(no_act_delay) - float(ZIG_PHASE_OVERLAP_S))
    _low_bus_delay = _eff_delay_gate < float(SELFORG_MIN_BUS_DELAY_S)

    # ── Select best action via minimum total delay (DP optimal) ─────────────
    _best_atype, _best_aparam, _best_total = 'NO_ACTION', 0.0, _baseline_total
    _best_dbus, _best_dside, _best_dp_pen = _na_dbus, _na_dside, 0.0
    for (_at, _ap, _tot, _dbus, _dside, _saved, _pen) in _cand_rows:
        if _at == 'NO_ACTION':
            continue
        if _low_bus_delay:
            continue
        # GE is a small same-phase intervention: tolerate a higher cross-street
        # cost ratio for extensions than for (disruptive) insertions.
        _gate_factor = (float(CELLQLEARN_DP_GE_BALANCE_FACTOR) if _at == 'GE'
                        else float(CELLQLEARN_DP_BALANCE_FACTOR))
        if _side_ratio > _gate_factor:
            continue
        if _tot < _best_total:
            _best_total = _tot
            _best_atype, _best_aparam = _at, _ap
            _best_dbus, _best_dside = _dbus, _dside
            _best_dp_pen = _pen

    if _low_bus_delay:
        _best_atype, _best_aparam = 'NO_ACTION', 0.0
        _best_dbus, _best_dside = _na_dbus, _na_dside
        _best_total = _baseline_total

    _log_func(self, f"[CELLQLEARN_DP] inter={self.id} t={time:.1f} bus={veh_id} "
                    f"n0={n0_bus:.1f} side_ratio={_side_ratio:.2f} "
                    f"dp_stages={_n_stages} "
                    f"low_bus_delay={_low_bus_delay} "
                    f"chosen={_best_atype}_{_best_aparam:.0f} "
                    f"total_delay={_best_total:.1f}paxs")

    # ── Build rows for the shared Pareto layer / reward CSV ─────────────────
    # Emit EVERY DP-evaluated candidate that survives the balance gates (not
    # just the argmin), so the Pareto layer sees the mode's full model
    # trade-off across the action space (GE / INS / GREEN_REALLOC / EARLY_RED)
    # instead of collapsing onto the standard pool.  Each row carries the DP
    # model's own CTM-computed bus benefit and cross-phase cost, with the DP
    # coordination look-ahead penalty folded into the cross-phase cost.
    r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
        self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
    rows = [('NO_ACTION', 0.0, r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na)]

    best_r = r_na; best_so = so_na; best_tp = tp_na; best_r_delta = 0.0
    if not _low_bus_delay:
        for (_at, _ap, _tot, _dbus, _dside, _saved, _pen) in _cand_rows:
            if _at == 'NO_ACTION':
                continue
            # Same balance-gate filtering the argmin loop applied: tolerate a
            # higher cross-street cost ratio for GE than for disruptive actions.
            _gate_factor = (float(CELLQLEARN_DP_GE_BALANCE_FACTOR) if _at == 'GE'
                            else float(CELLQLEARN_DP_BALANCE_FACTOR))
            if _side_ratio > _gate_factor:
                continue
            try:
                _, so_act, tp_act, bps_gated, _, nsd_act, std_act = _dctsp_eval_action(
                    self, _at, _ap, sigma_in, no_act_delay, bus_eta_s,
                    wrong_phase=_wrong_phase, remaining_red_s=remaining_red_s)
            except Exception:
                so_act, tp_act, bps_gated, nsd_act, std_act = so_na, tp_na, 0.0, nsd_na, std_na
            # Use the ETA-gated bus benefit from _dctsp_eval_action as the
            # authoritative value (it already applies the INS ETA gate and the
            # no_act_delay cap — see dctsp_mp_ectm_dp for the phantom-savings
            # rationale), bounded by the DP's raw CTM delta.
            bps_ctm = min(max(0.0, float(bps_gated)),
                          max(0.0, _na_dbus - _dbus))
            cpc_ctm = max(0.0, _dside - _na_dside)
            if cpc_ctm < 1.0 and bps_ctm > 0.0:
                try:
                    _dp_red = float(_ap) + float(INS_INTERGREEN_S)
                    _sd, _ = self._compute_side_delay_penalty(_dp_red, _suppress_log=True)
                    cpc_ctm += max(0.0, float(_sd))
                except Exception:
                    pass
            # Fold the DP coordination look-ahead penalty into the emitted row's
            # cross-phase cost so the final max-reward / Pareto selection actually
            # sees the downstream impact (previously only shaped the argmin).
            cpc_ctm += float(_pen)
            r_act = bps_ctm - cpc_ctm
            rows.append((action_label(_at, _ap), _ap,
                         r_act, so_act, tp_act, bps_ctm, cpc_ctm, nsd_act, std_act))
            if _at == _best_atype and abs(_ap - _best_aparam) < 1e-6:
                best_r = r_act; best_so = so_act; best_tp = tp_act
                best_r_delta = r_act - r_na

    return (_best_atype, _best_aparam, best_r, best_r_delta,
            best_so, best_tp, rows)


# ── Mode: MaxPressure (Varaiya 2013) — Fix & Flex ────────────────────────────
# Ported from sumoITScontrol (Riehl et al. 2026, ETHZ, GPL-3.0):
#   src/sumoITScontrol/control/intersection_management/MaxPressure_Fix.py
#   src/sumoITScontrol/control/intersection_management/MaxPressure_Flex.py
#
# Pressure per phase = Σ upstream_queue – Σ downstream_queue  (pax-weighted).
# Fix: at each cycle boundary, average pressure over measurement_period steps,
#      allocate effective green (cycle – n·T_L) proportional to pressure, clamp
#      to [G_MIN,G_MAX], redistribute to meet cycle exactly, round to int.
# Flex: re-evaluate every T_A seconds, extend current phase if it still has max
#       pressure, otherwise switch (phase rotation) to the max-pressure phase.
#
# Aimsun mapping (uses ALL available information):
#   • Upstream queue: MaxQueueLength per detector + section vehicle count
#     (AKIVehStateGetNbVehiclesSection / AKIDetGetCounter) — per incoming
#     section of each turnings' origin.  Bus vehicles counted at BusOcc (40) vs
#     CarOcc (1.5) so a queued bus dominates pressure.
#   • Downstream queue: same, on the turning's destination sections.
#   • Saturation / turnings / signal groups: from control_plans dump + live
#     ECIGetCurrentPhase / GetPhaseDuration.  Falls back to MainSections/
#     SideSections when dump lacks a junction.
#   • Pressures averaged over MAXPRESSURE_MEAS_PERIOD steps for stability.
_MP_PRESSURE_HIST: dict = {}  # {jct_id: {phase_idx: [recent pressures]}}
_MP_FSM: dict = {}            # {jct_id: {"timer": int, "schedule": [g0..], "idx": int}}


# NOTE: an earlier _mp_queue_pax() helper lived here claiming pax-weighted
# (bus-boosted) queues but implemented plain n_veh * 1.5 with the bus-count
# code computed and discarded. It had no callers (the live pressure path
# weights buses inline); removed 2026-09-10 rather than fixed dead code.


# ── MP-TSP-LB helpers (Kobeissi et al. 2026) ─────────────────────────────────
def _mp_section_lane_count(sid: int) -> float:
    """Approach lane count for a section: measured feed first, then Aimsun ANG
    info, else the MP_LANEBLOCK_TOTAL_LANES fallback."""
    try:
        _ls = getattr(globals().get('stats', None), 'latest_section', None) or {}
        _st = _ls.get(int(sid))
        if _st and int(_st.get('lanes', 0) or 0) > 0:
            return float(int(_st['lanes']))
    except Exception:
        pass
    try:
        _inf = AKIInfNetGetSectionANGInf(int(sid))
        _nl = int(getattr(_inf, 'nbCentralLanes', 0) or 0)
        if _nl > 0:
            return float(_nl)
    except Exception:
        pass
    return float(globals().get('MP_LANEBLOCK_TOTAL_LANES', MP_LANEBLOCK_TOTAL_LANES) or 2.0)


def _mp_dwelling_block_factor(self, secs, phase_green=None) -> float:
    """MP-TSP-LB (1) LANE BLOCKAGE. Saturation multiplier in (0,1] for a phase
    serving `secs`. A bus DWELLING at a near-side stop blocks MP_LANEBLOCK_LANES
    lanes of its approach, so the phase can discharge only the surviving lane
    fraction -- MaxPressure should not pour green onto a queue the stopped bus
    physically blocks. Returns 1.0 when no bus dwells (no blockage).

    A bus qualifies as dwelling when CurrentStopTime>=MP_DWELL_MIN_S AND (when
    MP_DWELL_REQUIRE_GREEN) its phase is currently GREEN -- the discriminator
    that separates a genuine stop dwell / downstream block (stopped on green:
    extending is wasted) from a bus merely QUEUED at red (stopped on red: it will
    discharge on green, so it is NOT a blockage). `phase_green` is that gate,
    supplied by the caller per pressure-phase; None = undeterminable -> fail OPEN
    (count) so the mitigation is never silently disabled. This is the caller's
    only defence -- the outer `_p>0` guard just stops a negative phase being
    promoted, it does NOT keep red-queued buses out."""
    if not bool(globals().get('MP_LANEBLOCK_MODE', MP_LANEBLOCK_MODE)):
        return 1.0
    # GREEN-GATE: a red phase's stopped buses are queued, not dwelling -> skip.
    if (bool(globals().get('MP_DWELL_REQUIRE_GREEN', MP_DWELL_REQUIRE_GREEN))
            and phase_green is False):
        return 1.0
    _dwell_min = float(globals().get('MP_DWELL_MIN_S', MP_DWELL_MIN_S))
    _blk_per   = float(globals().get('MP_LANEBLOCK_LANES', MP_LANEBLOCK_LANES))
    _bus_pos   = int(getattr(self, 'bus_type_pos', 1) or 1)
    _worst = 1.0
    for sid in (secs or []):
        try:
            n = int(AKIVehStateGetNbVehiclesSection(int(sid), True))
        except Exception:
            n = 0
        n_dwell = 0
        for vi in range(n):
            try:
                inf = AKIVehStateGetVehicleInfSection(int(sid), vi)
                if int(getattr(inf, 'type', -1)) != _bus_pos:
                    continue
                if float(getattr(inf, 'CurrentStopTime', 0.0) or 0.0) >= _dwell_min:
                    n_dwell += 1
            except Exception:
                pass
        if n_dwell <= 0:
            continue
        lanes = max(_mp_section_lane_count(int(sid)), 1.0)
        blocked = min(lanes, _blk_per * n_dwell)
        # keep a sliver so a fully-blocked single-lane approach still clears
        _worst = min(_worst, max(0.1, (lanes - blocked) / lanes))
    return _worst


def _mp_downstream_sat_frac(self) -> float:
    """Saturation fraction (0..1) of the DOWNSTREAM corridor main approach (next
    junction on the bus route) via the CorridorCoordinator route index + the
    measured queue -- the same first hop the cascade-cost term uses. 0.0 when no
    downstream junction / no data."""
    _coord = getattr(self, '_corridor_coord', None)
    if _coord is None:
        return 0.0
    try:
        _order = list(getattr(_coord, 'route_inter_ids', []) or [])
        _ri = getattr(_coord, '_route_index', {}) or {}
        idx = _ri.get(int(self.id))
        if idx is None or idx + 1 >= len(_order):
            return 0.0
        _icm = getattr(_coord, '_ic_map', {}) or {}
        _ctm = getattr(_coord, '_ctrl_map', {}) or {}
        down = _icm.get(int(_order[idx + 1])) or _ctm.get(int(_order[idx + 1]))
        if down is None:
            return 0.0
        import numpy as _np
        _ls = getattr(globals().get('stats', None), 'latest_section', None) or {}
        try:
            _t_now = float(AKIGetCurrentSimulationTime())
        except Exception:
            _t_now = -1.0
        _n_down = 0.0
        _dsecs = (list(getattr(down, 'incoming_sections', []) or [])
                  or list(getattr(down, 'main_sections', []) or []))
        for _sid in _dsecs:
            _st = _ls.get(int(_sid))
            if _st is None:
                continue
            if _t_now >= 0.0 and abs(_t_now - float(_st.get('t', -1e9))) > 90.0:
                continue
            _n_down += (float(_st.get('queue_veh', 0) or 0.0)
                        * max(int(_st.get('lanes', 1) or 1), 1))
        if _n_down <= 0.0:
            # fallback: flow x red (matches the cascade term when unmeasured)
            _dupf = _np.asarray(getattr(down, 'UpFlowList', _np.zeros((1, 1))), dtype=float)
            _dq = (float(_np.mean(_dupf[_dupf > 0.0])) / 3600.0 if _np.any(_dupf > 0.0) else 0.0)
            _drdt = _np.asarray(getattr(down, 'RedDurationList', _np.zeros((1, 1))), dtype=float)
            _dred = (float(_np.max(_drdt[_drdt > 0.0])) if _np.any(_drdt > 0.0) else 60.0)
            _n_down = max(0.0, _dq * _dred)
        _kjam = max(float(getattr(down, 'JamDensity',
                                  getattr(down, 'SaturationDensity', 150.0)) or 150.0), 1.0)
        _cap = 0.15 * _kjam
        return max(0.0, min(1.0, _n_down / max(_cap, 1.0)))
    except Exception:
        return 0.0


def _mp_corridor_discount(self) -> float:
    """MP-TSP-LB (2) CORRIDOR COORDINATION. Pressure multiplier in (0,1] for the
    corridor-THROUGH phase: discount when the downstream main link is near jam so
    MaxPressure does not push a platoon into a link that will spill back. 1.0
    when disabled or the downstream link is clear."""
    if not bool(globals().get('MP_CORRIDOR_COORD_MODE', MP_CORRIDOR_COORD_MODE)):
        return 1.0
    _thr = float(globals().get('MP_CORRIDOR_SAT_THRESHOLD', MP_CORRIDOR_SAT_THRESHOLD))
    _w = min(1.0, max(0.0, float(globals().get('MP_CORRIDOR_COORD_WEIGHT',
                                               MP_CORRIDOR_COORD_WEIGHT))))
    sf = _mp_downstream_sat_frac(self)
    if sf <= _thr:
        return 1.0
    sev = (sf - _thr) / max(1.0 - _thr, 1e-6)
    return max(0.1, 1.0 - _w * sev)


def _mp_pressures_for_junction(self, time, current_phase=None) -> list:
    """Return per-phase pressures (pax) for this junction — uses full dump info when present.

    `current_phase` (the live Aimsun phase index) lets the lane-blockage term
    gate dwelling on phase-is-green (see _mp_dwelling_block_factor). When None it
    is queried from ECIGetCurrentPhase; if still unknown the green-gate fails
    open (counts)."""
    cfg = getattr(self, 'config', {}) or {}
    # Resolve the live phase for the green-gate discriminator (main phase green
    # iff current_phase == BusPhase; in the 2-phase proxy pi==0 is main, pi>=1
    # side). Best-effort: unknown -> _main_green=None -> gate fails open.
    _main_green = None
    try:
        _cph = current_phase
        if _cph is None:
            _cph = ECIGetCurrentPhase(self.node_id)
        _bus_ph = getattr(self, 'BusPhase', None)
        if _cph is not None and _bus_ph is not None:
            _main_green = (int(_cph) == int(_bus_ph))
    except Exception:
        _main_green = None
    # Phase list: prefer control_plans dump, else SignalGroupIDList
    phases = []
    try:
        # Try to find control plan entry for this junction — uses the full
        # Aimsun export (sections/turnings/control_plans/PT lines/OD matrices)
        # so pressure is computed from the same truck/bus/car counts, signal
        # phases and turning movements that the simulator runs.  Falls back to
        # SignalGroupIDList when the dump is absent (Logan minimal config).
        import json as _js, os as _os
        corridor = str(getattr(self, '_corridor_dir', '') or '')
        # Prefer the dump matching this corridor's directory name
        cands = []
        if 'logan' in corridor.lower():
            cands = [os.path.join(os.path.dirname(corridor), '..', 'sumo_bridge', 'logan_aimsun_dump.json'),
                     os.path.join(os.path.dirname(corridor), '..', 'sumo_bridge', 'kg_aimsun_dump.json')]
        else:
            cands = [os.path.join(os.path.dirname(corridor), '..', 'sumo_bridge', 'kg_aimsun_dump.json'),
                     os.path.join(os.path.dirname(corridor), '..', 'sumo_bridge', 'logan_aimsun_dump.json')]
        # Also try repo-root relative (HPC layout)
        cands += [os.path.join(os.path.dirname(__file__), '..', '..', 'sumo_bridge', 'kg_aimsun_dump.json'),
                  os.path.join(os.path.dirname(__file__), '..', '..', 'sumo_bridge', 'logan_aimsun_dump.json')]
        dump_path = None
        for cand in cands:
            cand = os.path.normpath(cand)
            if os.path.isfile(cand):
                dump_path = cand
                break
        if dump_path and os.path.isfile(dump_path):
            with open(dump_path, encoding='utf-8') as f:
                dump = _js.load(f)
            for cp in dump.get('control_plans', []):
                j = cp.get('junctions', {}).get(str(self.id))
                if j:
                    phases = j.get('phases', [])
                    break
    except Exception:
        pass
    if not phases:
        # Fallback: derive phase count from SignalGroupIDList
        try:
            phases = cfg.get('SignalGroupIDList', [[1, 2]])
            phases = [{'sg_states': {str(sg): 1}} for sg in phases]
        except Exception:
            phases = [{'sg_states': {}}]
    n_ph = max(len(phases), 1)
    pressures = [0.0] * n_ph
    # Per-phase pressure: upstream - downstream
    # Use Main/Side section groups as proxy when turnings mapping unavailable
    try:
        main_secs = list(cfg.get('MainSections', []) or [])
        side_secs = list(cfg.get('SideSections', []) or [])
        # Passenger-weighted (transit-aware) pressure: count each vehicle by its
        # occupancy so the continuous MaxPressure controller acts on the STATE at
        # every cadence (no bus needed) and simply weights a movement carrying
        # buses UP by its bus passengers when one is present -- more people, more
        # pressure, more green. Configurable occupancies + a tunable transit
        # weight (MP_TRANSIT_PAX_WEIGHT, default 1.0 = plain occupancy). (2026-09-23)
        _car_occ = max(float(getattr(self, 'CarOcc', 1.5) if hasattr(self, 'CarOcc') else 1.5), 1.0)
        _bus_occ = max(float(getattr(self, 'BusOcc', 40.0) or 40.0), 1.0)
        _mp_wt = float(globals().get('MP_TRANSIT_PAX_WEIGHT', 1.0))
        # Simple 2-phase pressure model that is corridor-agnostic and uses all
        # sections: phase 0 ~ main, phase 1 ~ side, remaining phases ~ side
        for pi in range(n_ph):
            # Decide which section set this phase serves
            if pi == 0:
                secs = main_secs if main_secs else list(getattr(self, 'incoming_sections', []) or [])
            else:
                secs = side_secs if side_secs else list(getattr(self, 'incoming_sections', []) or [])
            up = 0.0
            down = 0.0
            for sid in secs:
                try:
                    up += float(AKIVehStateGetNbVehiclesSection(int(sid), True)) * _car_occ
                    # Bus boost: count buses on this section at BusOcc
                    n_bus = 0
                    try:
                        nb = int(AKIVehStateGetNbVehiclesSection(int(sid), True))
                        for vi in range(nb):
                            inf = AKIVehStateGetVehicleInfSection(int(sid), vi)
                            if int(getattr(inf, 'type', -1)) == int(getattr(self, 'bus_type_pos', 1)):
                                n_bus += 1
                    except Exception:
                        pass
                    if n_bus:
                        # upgrade the counted vehicles to bus passengers: each bus
                        # adds (BusOcc*weight - CarOcc) on top of the car-count above.
                        up += n_bus * (_bus_occ * _mp_wt - _car_occ)
                except Exception:
                    pass
                # Downstream: sections reachable via turnings from this section
                try:
                    # Use turning graph if available to find downstream sections
                    for t in self._turnings_from_section(int(sid)) if hasattr(self, '_turnings_from_section') else []:
                        try:
                            ds = int(t.get('to_section', -1))
                            down += float(AKIVehStateGetNbVehiclesSection(ds, True)) * _car_occ
                        except Exception:
                            pass
                except Exception:
                    pass
            # Detector-level queue is more precise for pressure — add MaxQueueLength
            try:
                mq = getattr(self, 'MaxQueueLength', None)
                if mq is not None:
                    import numpy as _np
                    arr = _np.asarray(mq, dtype=float).ravel()
                    if arr.size:
                        up += float(_np.sum(arr[arr > 0])) * _car_occ
            except Exception:
                pass
            _p = float(up - down)
            # MP-TSP-LB corridor terms only ever LOWER a positive pressure, so a
            # negative (over-served) phase is left untouched and cannot be
            # promoted by the scaling.
            if _p > 0.0:
                # (1) dwelling-bus lane blockage on THIS phase's approach.
                # phase_green gates out red-queued buses: pi==0 (main) is green
                # iff _main_green; a side phase (pi>=1) is green iff NOT _main_green.
                _pg = (None if _main_green is None
                       else (_main_green if pi == 0 else (not _main_green)))
                _p *= _mp_dwelling_block_factor(self, secs, _pg)
                # (2) corridor coordination on the through phase (pi==0 proxy)
                if pi == 0:
                    _p *= _mp_corridor_discount(self)
            pressures[pi] = _p
    except Exception:
        pressures = [0.0] * n_ph
    # Averaging window for stability
    hist = _MP_PRESSURE_HIST.setdefault(int(self.id), {})
    for pi, p in enumerate(pressures):
        lst = hist.setdefault(pi, [])
        lst.append(float(p))
        if len(lst) > int(globals().get('MAXPRESSURE_MEAS_PERIOD', MAXPRESSURE_MEAS_PERIOD) or 4):
            lst.pop(0)
    avg = [float(sum(hist.get(pi, [0])) / max(len(hist.get(pi, [0])), 1)) for pi in range(n_ph)]
    return avg


def _mp_compute_greens(pressures: list, n: int, cycle: float, t_l: float, gmin: float, gmax: float) -> list:
    """Proportional green split given pressures — mirrors sumoITScontrol logic."""
    effective = max(0.0, float(cycle) - n * float(t_l))
    total_p = sum(pressures) if pressures else 0
    if total_p <= 0:
        greens = [effective / n] * n if n else []
    else:
        greens = [p / total_p * effective for p in pressures]
    greens = [max(float(gmin), min(float(g), float(gmax))) for g in greens]
    total_alloc = sum(greens)
    diff = effective - total_alloc
    tol = 1e-6
    while abs(diff) > tol:
        if diff > 0:
            adjustable = [i for i, g in enumerate(greens) if g < float(gmax)]
        else:
            adjustable = [i for i, g in enumerate(greens) if g > float(gmin)]
        if not adjustable:
            break
        adj = diff / len(adjustable)
        for i in adjustable:
            greens[i] += adj
            greens[i] = max(float(gmin), min(greens[i], float(gmax)))
        total_alloc = sum(greens)
        diff = effective - total_alloc
    greens = [int(round(g)) for g in greens]
    delta = int(round(effective)) - sum(greens)
    for i in range(abs(delta)):
        idx = i % n
        if delta > 0 and greens[idx] < float(gmax):
            greens[idx] += 1
        elif delta < 0 and greens[idx] > float(gmin):
            greens[idx] -= 1
    return greens


def dctsp_maxpressure_fix(self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
                          no_act_delay, sigma_in, remaining_red_s=0.0):
    # Cyclic mode owns this junction: the per-step scheduler switches phases
    # directly, so the bus-triggered generator stands down entirely.
    if bool(globals().get('MAXPRESSURE_CYCLIC', MAXPRESSURE_CYCLIC)):
        r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
            self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
        return ('NO_ACTION', 0.0, r_na, 0.0, so_na, tp_na,
                [('NO_ACTION', 0.0, r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na)])
    return _mp_binary_decision(self, time, timeSta, acycle, bus_eta_s, veh_id,
                               current_phase, no_act_delay, sigma_in,
                               remaining_red_s, share_scale=0.5)


def _mp_binary_decision(self, time, timeSta, acycle, bus_eta_s, veh_id,
                        current_phase, no_act_delay, sigma_in,
                        remaining_red_s=0.0, share_scale=1.0):
    """Binary MaxPressure on the CURRENT phase (shared FIX/FLEX core).

    Why binary: the only pressure data available without the control-plans
    dump is the main/side proxy (pressures[0] = main, rest = side), so per-
    phase targeting is unresolvable. The old code treated the proxy indices
    as phase positions anyway (int(current_phase) % n -- wrong for 1-based
    and non-contiguous phase numbers) and emitted 25-50 s raw extensions
    past every cap, which is why MP gridlocked (FIX obj ~69 vs NO_TSP ~201).
    This core instead asks the one answerable question -- does the pressured
    direction match the phase holding green? -- and extends (GE, capped) or
    truncates (ER, capped) the CURRENT phase through the standard executor,
    so veto/Pareto/Z4 gates and the MIN/MAX duration clamps all still apply.
    Bus priority survives via the 40-pax bus boost inside the pressures: a
    queued bus keeps main pressure dominant, so green follows buses.
    FIX vs FLEX: share_scale 0.5 (FIX: cautious half-shares, plan-following)
    vs 1.0 (FLEX: full shares, aggressive). Stateless and identically gated;
    the policies genuinely differ in magnitude while sharing the mapping.
    Returns the standard (atype, aparam, best_r, best_r_delta, best_so,
    best_tp, rows) decider tuple.
    """
    try:
        import math as _math
        _max_ge = 10.0
        try:
            _max_ge = float(globals().get('MAX_GE_EXTENSION_S', 10.0)) or 10.0
        except Exception:
            pass
        try:
            _cycle = max(30.0, float(getattr(self, 'cycle_len_s', 135.0) or 135.0))
        except Exception:
            _cycle = 135.0
        pressures = _mp_pressures_for_junction(self, time, current_phase)
        _pm = float(pressures[0]) if len(pressures) > 0 else 0.0
        _ps = float(max(list(pressures[1:]) or [0.0]))
        _ptot = _pm + _ps
        try:
            _cur_is_main = (int(current_phase) == int(self.BusPhase))
        except Exception:
            _cur_is_main = False
        _atype, _aparam = 'NO_ACTION', 0.0
        if _ptot > 0.0:
            try:
                _ssc = max(0.0, min(float(share_scale), 1.0))
            except Exception:
                _ssc = 1.0
            if (_pm >= _ps) == bool(_cur_is_main):
                # Pressured direction holds green: extend it, proportional
                # share (scaled) capped to the corridor GE maximum.
                _pcur = _pm if _cur_is_main else _ps
                _share = _ssc * _cycle * _pcur / _ptot
                if _share >= 3.0:
                    _atype, _aparam = 'GE', min(_share, _max_ge)
            elif _cur_is_main and float(no_act_delay) <= 0.0:
                # Bus catches this natural green: truncating it can only hurt
                # the bus for side pressure. MP serves pressure, but never by
                # cutting a green the detected bus is about to use (the Z4
                # gate cannot see this harm: ER-on-bus books zero bus benefit
                # by construction, so it would pass). NO_ACTION.
                pass
            else:
                # Pressure lies elsewhere: truncate current green so the plan
                # advances to it (standard ER executor floors at 5 s green).
                _poth = _ps if _cur_is_main else _pm
                _cut = _ssc * _cycle * _poth / _ptot
                if _cut >= 3.0:
                    _atype, _aparam = 'EARLY_RED', min(_cut, 10.0)
        r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
            self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
        rows = [('NO_ACTION', 0.0, r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na)]
        best_r, best_so, best_tp, best_r_delta = r_na, so_na, tp_na, 0.0
        if _atype != 'NO_ACTION':
            r, so, tp, bps, cpc, nsd, std = _dctsp_eval_action(
                self, _atype, _aparam, sigma_in, no_act_delay, bus_eta_s,
                wrong_phase=(int(current_phase) != int(self.BusPhase)), remaining_red_s=remaining_red_s)
            rows.append((action_label(_atype, _aparam), _aparam, r, so, tp, bps, cpc, nsd, std))
            best_r, best_so, best_tp = r, so, tp
            best_r_delta = r - r_na
        else:
            _atype, _aparam = 'NO_ACTION', 0.0
        return (_atype, _aparam, best_r, best_r_delta, best_so, best_tp, rows)
    except Exception:
        r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
            self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
        return ('NO_ACTION', 0.0, r_na, 0.0, so_na, tp_na,
                [('NO_ACTION', 0.0, r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na)])


def dctsp_maxpressure_flex(self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
                           no_act_delay, sigma_in, remaining_red_s=0.0):
    # Cyclic stand-down (see _fix above).
    if bool(globals().get('MAXPRESSURE_CYCLIC', MAXPRESSURE_CYCLIC)):
        r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
            self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
        return ('NO_ACTION', 0.0, r_na, 0.0, so_na, tp_na,
                [('NO_ACTION', 0.0, r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na)])
    # Same binary core as FIX (per-phase targeting is unresolvable from the
    # main/side proxy; the old FLEX path additionally emitted raw 25 s
    # extensions past every cap). Cadence difference (re-evaluate every T_A
    # vs per-cycle) lives in the executor's cooldown/cycle-grant gates.
    return _mp_binary_decision(self, time, timeSta, acycle, bus_eta_s, veh_id,
                               current_phase, no_act_delay, sigma_in,
                               remaining_red_s)


# ── Constants that must be propagated from run_config.py into engine globals ───

# Decider cost-veto ratios (2026-08-24). Declared HERE so they are part of
# MODE_FLAGS: AAPIInit copies run_config.py values into this module, and
# reset_mode_flags() restores these defaults between experiments. The engine
# reads them via getattr(_spm, ...) -- reading engine globals instead leaked a
# previous arm's tuned ratio into every later arm in the same Aimsun session.
DECIDER_COST_VETO_RATIO = 1.0
DECIDER_COST_VETO_RATIO_INS = 3.0

# Cyclic MaxPressure (Varaiya-faithful): when True, a per-step scheduler in the
# engine re-evaluates pressures every interval and switches phases directly --
# independent of bus detections -- while the detection-path generators below
# stand down. False = legacy bus-triggered behaviour.
MAXPRESSURE_CYCLIC = False

MODE_FLAGS = [
    'BXT_MODE', 'BXT_DT_S', 'BXT_EPSILON', 'BXT_ALPHA', 'BXT_GAMMA',
    'BXT_CAR_OCC', 'BXT_BALANCE_FACTOR', 'BXT_GE_BALANCE_FACTOR',
    'BXT_MAX_INS_S', 'BXT_EVAL_DIAGNOSTICS',
    'GE_DURATIONS_S', 'INS_DURATIONS_S', 'ER_DURATIONS_S', 'GR_DURATIONS_S',
    'BXT_ENABLE_GE', 'BXT_ENABLE_INS', 'BXT_ENABLE_GR', 'BXT_ENABLE_ER',
    'BXT_ENABLE_OC',
    'MEASURED_SIDE_COST', 'MEASURED_SIDE_SPILL_GAIN', 'MEASURED_SIDE_FRESH_S',
    'MEASURED_SIDE_COST_DIAG', 'DIAG_FLOW_STAGE', 'DIAG_DECISION',
    'RECOVERABILITY_GATE', 'RECOVERABILITY_SLACK_S',
    'RECOVERY_MAX_CYCLES', 'RECOVERY_TRANSITION_RATE',
    'PROGRESSION_GATE', 'PROGRESSION_MAX_LOSS_PAXS',
    'MP_TRANSIT_PAX_WEIGHT', 'CONTINUOUS_MONITOR_MODE',
    'CONTINUOUS_MONITOR_MIN_GAIN_PAXS', 'DEMAND_SEED_WARM_S',
    'MONITOR_STATE_GATE',
    'BXT_DEMAND_STATE', 'BXT_DEMAND_BIN_LO_PAXS', 'BXT_DEMAND_BIN_HI_PAXS',
    'CELLQLEARN_MIN_GAIN_S',
    'CELLQLEARN_DP_MODE', 'CELLQLEARN_DP_DT_S', 'CELLQLEARN_DP_HORIZON_S',
    'CELLQLEARN_DP_STAGE_S', 'CELLQLEARN_DP_COORD_WEIGHT',
    'CELLQLEARN_DP_CAR_OCC', 'CELLQLEARN_DP_BALANCE_FACTOR',
    'CELLQLEARN_DP_GE_BALANCE_FACTOR',
    'BARGAIN_SPM_MODE', 'NASH_GATE_MODE', 'BG_DET_LVL_IMM_S', 'BG_DET_LVL_NEAR_S',
    'BG_DET_LVL_FAR_S', 'BG_BUS_W_IMM', 'BG_BUS_W_NEAR', 'BG_BUS_W_FAR',
    'BG_BUS_W_VFAR', 'BG_SPM_RISK_WEIGHT', 'BG_MIN_BUS_DELAY_S',
    'BG_MIN_GAIN_S', 'BG_CASCADE_MULT', 'BG_NO_ACTION_BONUS_S',
    'DCTSP_ZIG_MODE', 'MP_ECTM_MODE', 'DCTSP_GREEN_REALLOC_MODE',
    'GREEN_REALLOC_RECOVER_FRACTION',
    'GLOBAL_REWARD_MODE', 'GLOBAL_REWARD_CHAIN_HORIZON',
    'MILP_TSP_MODE', 'MILP_TIME_LIMIT_S', 'MILP_HORIZON_CYCLES',
    'MILP_BUS_WEIGHT', 'MILP_CROSS_WEIGHT', 'MILP_REQUIRE_MAIN_FLOW',
    'MILP_MIN_MAIN_FLOW_VPH', 'MILP_MIN_GREEN_S',
    'MILP_MAX_GREEN_S', 'MILP_CYCLE_S',
    'CENTRALIZED_MODE', 'CENTRALIZED_INTERVAL_S',
    'CENTRALISED_MIN_BUS_DELAY_S', 'CENTRALISED_REACH_MARGIN_S',
    'NASH_BARGAIN_MODE', 'NASH_BUS_WEIGHT', 'NASH_CROSS_WEIGHT',
    'NASH_MIN_BUS_DELAY_S', 'NASH_MIN_GAIN_S', 'NASH_MEASURED_STATE',
    'NASH_CONTINUOUS_MODE', 'CONTINUOUS_BARGAIN_BUS_WEIGHT',
    'CONTINUOUS_CORRIDOR_MODE', 'CONTINUOUS_CORRIDOR_NEIGHBOR_W',
    'BXT_CONTINUOUS_MODE', 'MIN_PHASE_ACTIVE_S', 'NO_ACTION_HOLD_S',
    'EMPTY_PHASE_SKIP_MODE', 'EMPTY_PHASE_QUEUE_EPS_PAX',
    'EMPTY_PHASE_MIN_TARGET_PAX', 'BXT_POG_REWARD', 'BXT_POG_WEIGHT',
    'ACTUATED_BASE_MODE', 'ACTUATED_MIN_GREEN_S', 'ACTUATED_MAX_GREEN_S',
    'ACTUATED_GAP_QUEUE_EPS_VEH', 'ACTUATED_PERMISSIVE_GATE',
    'ACTUATED_OFFSET_PRESERVE', 'ACTUATED_DRIFT_TOL_S', 'ACTUATED_DRIFT_MAX',
    'NASH_CORRIDOR_MODE', 'NASH_NEIGHBOR_WEIGHT', 'NASH_MAX_ITER',
    'NASH_CONVERGENCE_TOL', 'NASH_INTEGER_DURATIONS',
    'DECIDER_COST_VETO_RATIO',
    'DCTSP_MIN_INS_DURATION_S', 'DCTSP_MAX_INS_DURATION_S',
    'ZIG_PHASE_OVERLAP_S', 'ZIG_BALANCE_FACTOR', 'ZIG_GE_BALANCE_FACTOR',
    'MP_ECTM_DT_S', 'MP_ECTM_MIN_EXT_S', 'MP_ECTM_MAX_EXT_S',
    'MP_ECTM_BALANCE_FACTOR', 'MP_ECTM_GE_BALANCE_FACTOR', 'MP_ECTM_CAR_OCC',
    'MP_ECTM_DP_MODE', 'MP_ECTM_DP_HORIZON_S', 'MP_ECTM_DP_STAGE_S',
    'MP_ECTM_DP_COORD_WEIGHT',
    'INS_INTERGREEN_S', 'NETWORK_FACTOR', 'NETWORK_FACTOR_DENSITY_RAMP',
    'CROSS_TRAFFIC_COST_MULTIPLIER',
    'DCTSP_W_H', 'DCTSP_W_HEADWAY', 'DCTSP_W_PAX_DELAY', 'DCTSP_CAR_WEIGHT',
    'SELFORG_MIN_BUS_DELAY_S', 'MAX_GE_EXTENSION_S',
    'ZIG_ENABLE_GE', 'ZIG_ENABLE_INS', 'ZIG_ENABLE_GR', 'ZIG_ENABLE_SEQ',
    'PHASE_ROTATION_MODE',
    'ZIG_MIN_GAIN_S',
    'DCTSP_MULTI_CYCLE_X_THR', 'DCTSP_MULTI_CYCLE_X_FLOOR',
    'REWARD_FUTURE_HORIZON_CYCLES', 'REWARD_FUTURE_DEBT_GAIN', 'REWARD_FUTURE_OFFSET_GAIN',
    'WOBJ_ALPHA', 'WOBJ_BETA', 'WOBJ_GAMMA',
    'BUS_PAX_WEIGHT', 'GREEN_KEEP_CREDIT_S', 'CORRIDOR_REWARD_NEIGHBOR_W',
    # 2026-08-24: multi-bus rollback (#3) + pre-arm timing hard-veto (#2)
    # + optimistic INS init so the learner inserts like the winning arms
    'MULTIBUS_MAX_FACTOR', 'PREARM_ALLOW_TIMING_ACTIONS',
    'BXT_INS_OPTIMISTIC_INIT',
    # CTM-prior Q-seeding (authentic cell-transmission-model Q-learning)
    'BXT_CTM_PRIOR_K', 'BXT_CTM_PRIOR_CLIP_PAXS',
    # CPD-QL: per-junction tabular Q-learning (DCTSP_MARL as a learner)
    'CPDQL_MODE', 'CPDQL_ALPHA', 'CPDQL_GAMMA', 'CPDQL_EPSILON',
    'CPDQL_TRAIN_EPSILON', 'CPDQL_W_H', 'CPDQL_CAR_OCC', 'CPDQL_MIN_GAIN_S',
    # MaxPressure (Riehl et al. 2026, ETHZ) — fixed & flexible cycle
    'MAXPRESSURE_FIX_MODE', 'MAXPRESSURE_FLEX_MODE',
    'MAXPRESSURE_T_L', 'MAXPRESSURE_G_MIN', 'MAXPRESSURE_G_MAX',
    'MAXPRESSURE_CYCLE_FIX', 'MAXPRESSURE_CYCLE_FLEX', 'MAXPRESSURE_T_A',
    'MAXPRESSURE_MEAS_PERIOD',
    'MAXPRESSURE_CYCLIC',
    # MP-TSP-LB: dwelling-bus lane blockage + corridor coordination
    'MP_LANEBLOCK_MODE', 'MP_LANEBLOCK_LANES', 'MP_LANEBLOCK_TOTAL_LANES',
    'MP_DWELL_MIN_S', 'MP_DWELL_REQUIRE_GREEN',
    'MP_CORRIDOR_COORD_MODE', 'MP_CORRIDOR_COORD_WEIGHT',
    'MP_CORRIDOR_SAT_THRESHOLD',
    # Decider cost-veto tuning (see comment above the declarations)
    'DECIDER_COST_VETO_RATIO', 'DECIDER_COST_VETO_RATIO_INS',
]

# Mode TOGGLES that gate the dispatch registry.  Each one MUST default to False
# and only be turned on by an experiment that explicitly wants it.  A
# batch_runner writes run_config.py per experiment but only lists the flags an
# experiment turns ON, and this module is loaded ONCE per Aimsun session and
# reused across every experiment — so without an explicit reset a toggle set
# True by experiment N stays True for N+1..end, making later experiments run
# extra modes and produce identical results.  reset_mode_flags() (called from
# AAPIInit before applying each run_config.py) clears this leak.
MODE_TOGGLES = [
    'DCTSP_ZIG_MODE', 'MP_ECTM_MODE', 'MP_ECTM_DP_MODE', 'BXT_MODE',
    'CELLQLEARN_DP_MODE',
    'BARGAIN_SPM_MODE', 'NASH_GATE_MODE',
    'DCTSP_GREEN_REALLOC_MODE', 'META_TSP_MODE', 'MDN_DELAY_MODE',
    'HS_EXT_MODE', 'REWARD_SELFORG_MODE', 'REWARD_INV_DELAY_MODE',
    'REWARD_V2X_MODE', 'CENTRALIZED_MODE', 'GLOBAL_REWARD_MODE',
    'MAXPRESSURE_FIX_MODE', 'MAXPRESSURE_FLEX_MODE',
    'CPDQL_MODE',
]

# Pristine defaults captured at import time (before any run_config is applied).
# Every MODE_FLAGS name that is a module global here is snapshotted so
# reset_mode_flags() can restore it between experiments.
_MODE_FLAG_DEFAULTS = {k: globals()[k] for k in MODE_FLAGS if k in globals()}


def reset_bxt_learning():
    """Clear the Q-table and pending-decision log so each SEED / replication is
    an INDEPENDENT learning episode.  CellQLearn learns within a run (its Q-table
    accrues realized-delay updates across that run's cycles), but must start each
    seed fresh from the analytic seed -- otherwise seed 400/500 inherit seed
    300's learning and the seeds are no longer independent.
    """
    try:
        _dctsp_bxt_q_table.clear()
        _poz_action_log.clear()
        _bxt_noaction_baseline.clear()
        _cpdql_reset()
    except Exception:
        pass


def reset_mode_flags():
    """Restore every mode flag to its pristine import-time default.

    Call this at the start of each experiment's AAPIInit, BEFORE applying that
    experiment's run_config.py overrides, so no mode leaks in from the previous
    experiment run in the same Aimsun session.  Returns the list of toggles
    that were reset (for the [MODES] banner / diagnostics).
    """
    for _k, _v in _MODE_FLAG_DEFAULTS.items():
        setattr(sys.modules[__name__], _k, _v)
    # Force every known toggle False even if it had no module-level default.
    for _t in MODE_TOGGLES:
        setattr(sys.modules[__name__], _t, False)
    return list(MODE_TOGGLES)
