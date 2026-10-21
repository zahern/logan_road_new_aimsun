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
# Calibrated state-bin edges (2026-09-30): same 4 bins per dimension (128
# states, no growth), but edges configurable so a quantile calibration can
# re-cut them to the observed distribution. Defaults reproduce the historical
# hand-tuned edges exactly; behaviour is identical unless overridden.
BXT_STATE_EDGES = {
    "n0_bus": [2.0, 8.0, 20.0],
    "side_ratio": [0.3, 0.8, 1.5],
    "bus_eta_s": [5.0, 15.0, 30.0],
}
# Raw-state logging for quantile calibration (2026-09-30): when True, every
# decision appends its raw continuous values to a CSV for offline quantile
# computation. Off by default (I/O cost); enable for ONE pilot run only.
BXT_LOG_RAW_STATE = False
# Demand warm-start (2026-09-30): populate each junction's whole table from
# offline analytic CTM rollouts before its first real decision. Off by default
# (existing comparisons untouched); enable per-arm. SCENARIOS = demand draws
# per state (exhaustive states x stochastic demand); SAT_FRAC = share drawn
# from the saturated regime (the states training never reaches).
BXT_DEMAND_WARMSTART = False
BXT_WARMSTART_SCENARIOS = 12
BXT_WARMSTART_SAT_FRAC = 0.4
BXT_DT_S           = 1.0
BXT_EPSILON        = 0.1
BXT_LEARN          = True   # close the Q-learning loop (credit realized delay back)
# BXT_BARGAIN_DECISION (2026-09-30): settle on a Nash product instead of a hard
# benefit>cost veto. N = benefit^pT * surplus^pC, surplus = benefit - cross cost.
# pT = 0 (default here) makes the accept test exactly "minimise TOTAL passenger
# delay", which is the paper's objective; pT = 1, pC = 1 is a symmetric bargain.
# Default OFF so behaviour is unchanged until enabled.
BXT_BARGAIN_DECISION = False
BXT_BARGAIN_PT       = 0.0    # bus bargaining power (0 = utilitarian)
BXT_BARGAIN_PC       = 1.0    # surplus bargaining power
BXT_BARGAIN_MIN_N    = 0.0    # optional Nash-value floor
# GE_UB_CAP_BY_JCT: per-junction hard cap (s) on green-extension upper bound
# ({jct_id: cap_s}). Module default here so reset_mode_flags() can restore it and
# a per-arm cap never carries into the next arm (2026-10-01).
GE_UB_CAP_BY_JCT     = {}
# BXT_EVAL_DIAGNOSTICS: run the realized-outcome measurement EVEN in eval (frozen)
# and emit a paired [BXT_EVAL] line per decision -- PREDICTED benefit (bps/cpc the
# decider used to choose) vs REALIZED benefit (delay actually measured ~1.5 cycles
# later). Lets you judge how well the controller's model matches reality without
# unfreezing the policy: the Q-table is NEVER updated in eval, only the NO_ACTION
# baseline accumulates (needed to score realized advantage; not part of the greedy
# policy). Off by default; the smoke pipeline turns it on. Parse with
# analyze_bxt_predictions.py.
BXT_EVAL_DIAGNOSTICS = False
# BXT_FREEZE_ON_EVAL: whether an 'eval'-phase seed may update the Q-table.
# DEFAULT False -- the Q-table is NEVER frozen. CellQLearn keeps crediting
# realized delay in every phase, including the scored seeds, so the policy the
# paper reports is a policy that was still learning while it drove. The old
# behaviour (True) suppressed both the Q-update and the decision log on eval
# seeds, which pinned the table at whatever the train seeds left behind.
# Only set True to reproduce a legacy frozen-policy run.
BXT_FREEZE_ON_EVAL = False
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
MEASURED_SIDE_COST       = True
MEASURED_SIDE_SPILL_GAIN = 3.0    # spillback severity gain: cost *= 1 + gain*sat/(1-sat)
MEASURED_SIDE_FRESH_S    = 90.0   # max age (s) of a latest_section measurement to trust
MEAS_MIN_SECTION_M       = 25.0   # min section length for a count×speed flow estimate (shorter = connector stub -> unmeasurable)
# DELAY CALIBRATION (default OFF): scale the analytic reward toward Aimsun's realised
# .DTa delay, per approach (kappa=EWMA(measured_delay_per_veh/REF)), so the decision
# tracks the microscopic delay it is scored on. Closes the decide-analytic/score-
# measured gap (see delay-mechanism-audit).
DELAY_CALIBRATION        = False  # 2026-10-12: back OFF by default (KG-clean). It was
                                  # proven INERT (byte-identical calibrated vs not, kappa~1.0),
                                  # so ON gained nothing and risked KG comparability; the
                                  # [DELAY_CAL][DIAG] log still fires (it's BEFORE this gate),
                                  # so the inertness diagnosis continues regardless. Flip True
                                  # per-corridor only once the inertness is fixed + A/B'd.
DELAY_CAL_REF_S          = 15.0   # reference delay/veh: kappa=1 at this measured delay
DELAY_CAL_ALPHA          = 0.1    # EWMA smoothing of the calibration factor
DELAY_CAL_MIN            = 0.25   # clamp on kappa
DELAY_CAL_MAX            = 4.0
# MICROSCOPIC QUEUE (default OFF): count a vehicle as queuing only when its speed is
# below the threshold (Aimsun's own queue definition), instead of every in-zone
# vehicle -- aligns the measured queue with the plant so predictions match.
MICRO_QUEUE_MODE         = False
MICRO_QUEUE_SPEED_KMH    = 5.0
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
# SIDLESS_MONITOR_HOLD: with no side sections configured (source=none
# junctions like 20270/20280/20844/19185/17308) a car-only tick has no
# opposing cost to balance against -- every evaluation looks profitable, so
# the junction acts freely and only pays progression/cascade downstream
# (NASH: 44 commits, +64h at 20270). Hold those ticks; bus-present ticks
# still decide normally. False restores legacy behaviour.
SIDLESS_MONITOR_HOLD = True
# SIDE_QUEUE_FLOOR: price standing side queues even when side flow reads ~0.
# Stopped queues are invisible to flow (snapshot needs speed; triangular flow
# ->0 at jam), so a jammed cross street priced zero (22603: 1165 vph side
# flow, pred_side=0 on all 41 commits). Adds zoned standing vehicles x extra
# red alongside the shockwave forming-queue term. False restores legacy.
SIDE_QUEUE_FLOOR = True

# SIDE_QUEUE_STOPPED_THRESHOLD_KMH: speed threshold (km/h) for a vehicle to
# be counted as "stopped/queued" in the side queue floor. Vehicles with
# CurrentSpeed below this are counted; moving vehicles are ignored.
# Default 5 km/h (~1.4 m/s) captures creeping queues but not free-flow.
SIDE_QUEUE_STOPPED_THRESHOLD_KMH = 5.0

# MONITOR_PROG_WEIGHT: price the POG-weighted progression cost INSIDE the
# car-only (monitor) reward, not just via the PROGRESSION_GATE veto. DE500
# (2026-09-27): 65/68 commits were bus=-1 monitor ticks with pred_side=0 and
# R=115..431 clearing MIN_GAIN=50, while the 300 pax-s gate never fired -- the
# reward saw pure car gain and the gate saw sub-threshold shifts, so every
# green broke progression a little (+11.6s car). Weight 1.0 subtracts the full
# Purdue-diagram platoon loss from the monitor benefit before the min-gain
# test. Bus-present ticks are unaffected. 0.0 restores legacy behaviour.
MONITOR_PROG_WEIGHT = 1.0
# MONITOR_BUS_ZERO: on car-only (monitor, bus=-1) ticks, seat specialised-mode
# rows on cost alone (drop the alpha*bus term) and re-derive a mode-committed
# best from the zeroed row. With no bus present there is no bus to save, but
# BXT/CTM row economics credited hundreds of pax-s of bus benefit (DE500:
# 56/57 car-only commits rode on pred_bus mean 405, max 1320), dwarfing the
# MONITOR_PROG price and driving the whole -3% loss. Bus-present ticks are
# unaffected. False restores legacy behaviour.
MONITOR_BUS_ZERO = True
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
# ── SCATS Degree-of-Saturation feed + balance gate + plan adapt (2026-10-14) ──
# These test the SCATS mechanism DIRECTLY -- balance every approach's measured
# degree of saturation -- instead of the analytic-delay ledger. All default OFF
# (inert until an arm enables them). See engine._approach_ds_snapshot /
# _ds_adapt_plan and the DS-BALANCE GATE block in _dctsp_eval_action's veto.
DS_BALANCE_GATE   = False   # veto a time-stealing action when a conflicting
                            # phase is already at/above DS_MAX (SCATS rule).
DS_MAX            = 0.90    # target per-approach degree-of-saturation ceiling.
DS_SPREAD_TOL     = 0.10    # min DS gap before the plan adapter moves green.
DS_CLAMP_MAX      = 2.0     # clamp on reported DS (oversaturation headroom).
# DS_RAW_CLAMP_MAX caps the UNCLAMPED raw DS stored for the cycle/merge law. A stub
# whose density x speed hits the saturation cap could otherwise report DS~167
# ([DS CYCLE] DSmax=167.47) and drive the cycle off a meaningless value.
DS_RAW_CLAMP_MAX  = 5.0
# FLOW_DET_LANE_SCALE: the GKDetectors are lane-specific and not every lane is
# instrumented, so a detector loop count is scaled to the full approach by
# lanes/loops. Off => use the raw summed count.
FLOW_DET_LANE_SCALE = True
# DS_STUB_RESOLVE (2026-10-19): resolve a short phase-origin CONNECTOR stub to the
# real approach section UPSTREAM of it (where the queue forms) before measuring
# DS. Stops at the first section at least DS_STUB_RESOLVE_M long; max
# DS_STUB_MAX_HOPS hops. Non-stub sections are left untouched.
DS_STUB_RESOLVE    = True
DS_STUB_RESOLVE_M  = 30.0
DS_STUB_MAX_HOPS   = 3
# DS_PAXF_MAX caps the passenger factor applied to a phase's DS demand. The raw
# formula 1 + bus_frac*(BusOcc/CarOcc - 1) is UNBOUNDED (one bus among one/two
# vehicles => ~33x), which pinned DS at the clamp whenever a bus was present.
DS_PAXF_MAX        = 2.0
DS_SNAPSHOT_TTL_S = 5.0     # cache the per-phase DS feed this long (one read/tick).
DS_PLAN_ADAPT     = False   # SCATS splits: at rest, equalise DS by retiming the
                            # base plan (_plan_target_greens); permanent, not per-bus.
DS_ADAPT_STEP_S   = 1.0     # bounded green moved per adaptation (s).
DS_MIN_GREEN_S    = 7.0     # never shrink a phase's green below this.
# DS_CAP_FLOOR_GREEN_S: the green used to form a phase's DS CAPACITY is floored at
# this value, so a phase trimmed to the skip floor is not priced as if it only had
# a few seconds of green (which pinned DS at the clamp and starved it forever).
DS_CAP_FLOOR_GREEN_S = 7.0
# Adaptation cadence: 15 s (2026-10-19). It used to be 0 = once per signal cycle
# (~135 s), which made the plan barely move. 15 s lets the split/cycle review run
# ~9x per cycle; the per-interval MOVE is still bounded by the step flags.
DS_ADAPT_EVERY_S  = 15.0
# ── ORDER-PRESERVING DS COMPRESSION (2026-10-20) ──────────────────────────────
# The HARD clamp (DS_CLAMP_MAX=2.0 reported / DS_RAW_CLAMP_MAX=5.0 raw) flattens
# every oversaturated phase to the SAME number, so the split/cycle law cannot
# tell WHICH saturated phase is worse: greens tie-bounce instead of converging
# and the pressure phases are never resolved. DS_ORDER_PRESERVE replaces the
# hard cap with a smooth monotone ASYMPTOTE: identical to raw DS at/below
# DS_CLAMP_MAX, then 2 + (CEIL-2)*(1-exp(-(d-2)/(CEIL-2))) above it -- strictly
# increasing for all d (ordering fully preserved), bounded at DS_ORDER_CEIL
# (a stub's meaningless density reading is still damped), no flat top.
DS_ORDER_PRESERVE = True    # ON (2026-10-20): hard clamp at 2.0 flattened every
                            # oversaturated phase to the SAME value -> no gradient
                            # to tell the worst approach apart -> saturation never
                            # resolved. Compress above 2.0 instead (monotone ->
                            # DS_ORDER_CEIL) so ds_max reflects true severity.
DS_ORDER_CEIL     = 5.0
# ── CYCLE-TIED SOLVE (2026-10-20) ─────────────────────────────────────────────
# Real SCATS re-constitutes the split plan EVERY cycle from the last cycle's
# measured DS, and the per-cycle adjustment is a FRACTION OF THE CYCLE, not a
# fixed 5 s trickle. These two flags make the solve loop faithful:
#   DS_SOLVE_PER_CYCLE: the DS solve is guaranteed to run AT LEAST once per
#       signal cycle (min(DS_ADAPT_EVERY_S, measured cycle)) -- never slacker
#       than SCATS's once-per-cycle review.
#   DS_SPLIT_MAX_MOVE_FRAC: per-solve green move cap as a FRACTION of the live
#       cycle (0 => use the absolute DS_SPLIT_MAX_MOVE_S seconds). A cycle-
#       scaled cap lets the split CONVERGE (0.10 -> ~14 s/solve at C=144 s,
#       i.e. resolved within 2-3 solves) instead of crawling 5 s per window.
DS_SOLVE_PER_CYCLE   = False
DS_SPLIT_MAX_MOVE_FRAC = 0.0
DS_IN_LEARNER_STATE = False # append a DS-regime bin to the BXT learner state.
DS_STATE_EDGES    = None    # edges for the DS-regime bin (None => [0.6,0.85,1.0]).
LOG_DS_ADAPT      = True     # per-move [DS ADAPT] log line (silenced in batches).
# SELF-GATING (no external veto): fold the convex conflicting-approach Webster
# delay into the action's OWN cross_cost so a bad action scores below NO_ACTION
# on its merits. The 1/(1-x) convexity is the gate. Preferred over DS_BALANCE_GATE.
DS_COST_IN_REWARD = False   # add the SCATS self-gating cost to the action reward.
DS_COST_CAP_PAXS  = 6000.0  # bound on the self-gating cost (pax·s).
# ── Transit-aware degree of saturation (2026-10-19) ───────────────────────────
# A bus carries BusOcc passengers vs CarOcc in a car, so an approach serving
# buses carries MORE people per vehicle-second than its raw veh/h flow shows.
# When DS_PAX_WEIGHTED the measured phase demand is scaled by the passenger-
# equivalent of its LIVE vehicle mix (engine._approach_ds_snapshot):
#   factor = 1 + bus_frac * (BusOcc/CarOcc - 1) * DS_BUS_PAX_WEIGHT
# so a bus approach reads a HIGHER DS and SCATS feeds it more of the split.
# Default OFF + weight 1.0 => every other arm's DS stays raw SCATS veh/h.
DS_PAX_WEIGHTED   = False
DS_BUS_PAX_WEIGHT = 1.0
# ── SCATS TRANSIT PRIORITY (graded levels, 2026-10-19) ────────────────────────
# SCATS public-transport priority runs at graded levels. When SCATS_TRANSIT_PRIORITY
# is on, a detected bus raises its phase's DS (bus pax-weight set by the level), so
# the SCATS split law STRETCHES the transit phase's green -- the real SCATS
# mechanism (bias the approach's degree of saturation; no external preemption). It
# reuses the DS_PAX_WEIGHTED machinery with the level's weight: low 0.25 / medium
# 0.5 / high 1.0. SCATS_TP_WEIGHT (>0) overrides the level with an explicit weight.
SCATS_TRANSIT_PRIORITY = False
SCATS_TP_LEVEL         = 'medium'
SCATS_TP_WEIGHT        = 0.0
# ── DS-driven CYCLE-LENGTH adapt (2026-10-19) ─────────────────────────────────
# SCATS cycle selection: grow the cycle when the BUSIEST approach's DS exceeds
# DS_CYCLE_TARGET (more capacity for the critical approach), shrink it when every
# approach is slack (less delay at low demand). Green time is scaled
# proportionally (splits preserved) so the DS split-adapt then balances on the
# new cycle. Driven ONLY by the measured degree of saturation -- no bus term.
DS_CYCLE_ADAPT    = False   # master switch for the cycle-length job.
DS_CYCLE_TARGET   = 0.90    # critical-approach DS the cycle is driven toward.
DS_CYCLE_HYST     = 0.05    # deadband around the target (stops cycle hunting).
DS_CYCLE_STEP_S   = 5.0     # cycle change per adaptation window (s).
# The cycle RANGE is derived from each junction's COMMISSIONED cycle
# (config CycleTime / cycle_length -- never the TSP decision cadence): the
# controller may shrink to MIN_RATIO x the commissioned cycle and grow to
# MAX_RATIO x it (the usual SCATS throw-off band). No hand-picked seconds.
DS_CYCLE_MIN_RATIO = 0.5
DS_CYCLE_MAX_RATIO = 1.5
# Absolute-second fallback ONLY when the commissioned cycle cannot be read.
DS_CYCLE_MIN_S    = 0.0
DS_CYCLE_MAX_S    = 0.0
# ── MASTER (regional) COMMON-CYCLE planner (2026-10-19) ───────────────────────
# SCATS is TWO-LEVEL: the LOCAL controller runs the DS split/cycle logic per
# junction (the tactical half), and a MASTER (regional) planner embeds the
# strategic decision -- ONE common cycle for the whole subsystem, solved from the
# TOTAL system demand (each member's demand-based Webster cycle; the master takes
# the HIGHEST, exactly as SCATS picks the subsystem cycle from its busiest
# junction). The master BROADCASTS that common cycle to every member; local
# controllers then adapt their SPLITS within it. The common cycle is solved
# UPFRONT (first control tick) and embedded in the start plan, then held
# (demand-rated, so it does not hunt). Range = MIN/MAX_RATIO x the group's
# commissioned cycle. There is NO bus-priority here -- the master only retimes.
DS_MASTER_CYCLE      = False
DS_MASTER_INTERVAL_S = 30.0   # master re-solve interval (s).
DS_MASTER_MIN_RATIO  = 0.5    # common cycle >= MIN_RATIO x group commissioned.
DS_MASTER_MAX_RATIO  = 1.5    # common cycle <= MAX_RATIO x group commissioned.
# MEASURED-cycle variant (2026-10-19): build the master common cycle from members'
# COMMISSIONED cycles (the busiest wins, exactly SCATS) instead of the OD demand
# Webster cycle. The OD prior is only a coarse network-wide figure and saturated
# every junction; with this set the whole demand cycle is dropped and the arms run
# purely on the commissioned plan + measured flow (splits) + measured DS (cycle
# feedback). Pair with PLAN_OPTIMIZE=False so no OD start plan is applied.
DS_MASTER_COMMISSIONED = False
# MEASURED-FLOW OFFSETS (2026-10-19): re-solve the subsystem green-wave on the
# master interval from the MEASURED link travel times (congestion-aware harmonic
# space-mean link speed), and stagger each junction's cycle start to it -- the
# SCATS offset layer. Replaces the one-shot fixed-speed bus green-wave seed.
DS_MASTER_OFFSETS  = False
DS_OFFSET_TOL_S    = 3.0    # only re-shift a junction when its offset error exceeds this (s)
DS_OFFSET_MAX_SHIFT_FRAC = 0.5  # cap one offset transient at this fraction of C
# DS_OFFSET_MAX_STEP_S: cap ONE offset transient at this many seconds per master
# interval (SCATS reviews offsets in small increments; a +52 s jump on a 130 s
# cycle destroys the green wave in a single step). Converges over intervals.
DS_OFFSET_MAX_STEP_S = 8.0
# DS_MASTER_DS_MIN_CRIT: the master only moves the common cycle from the critical
# DS once it clears this value. Below it (warm-up / uncongested) the calibration
# curve would falsely shrink the cycle, so the commissioned anchor is kept.
DS_MASTER_DS_MIN_CRIT = 0.30
# SCATS SPLIT LAW (2026-10-19): when set, DS_PLAN_ADAPT re-solves the whole split
# DIRECTLY (green_p proportional to the phase's UNCLAMPED critical DS) each cycle
# so phase DS equalise -- converging in ONE cycle. When off, the legacy 1 s/cycle
# gradient walk runs instead (which cannot converge when DS is clamped and hunts).
DS_SPLIT_PROPORTIONAL = False
# DS_SPLIT_DS_EQUAL (2026-10-20): allocate green so every phase reaches the SAME
# degree of saturation (Webster critical flow ratio, water-filled at the floors):
# g_p = (C-L) * y_p / sum(y). Replaces the floor+proportional form, which did NOT
# equalise DS. Off => the old floor + free*(w/sum w) allocation.
DS_SPLIT_DS_EQUAL = True
# ── REAL-TIME CYCLE / SEQUENCE HEURISTICS (2026-10-20) ────────────────────────
# SCATS_CYCLE_LAW selects how the target cycle is solved each interval:
#   "ds_curve" (SCATS DS->C calibration curve), "webster" (real-time Webster
#   optimal C = (1.5L+5)/(1-Y) from the measured critical flow ratio Y), or
#   "ladder" (the ds_curve target quantised to SCATS_CYCLE_LADDER_S steps).
SCATS_CYCLE_LAW      = "ds_curve"
SCATS_CYCLE_LADDER_S = 5.0
# SCATS_SEQUENCE_BY_Y: order the phase ring by the measured critical flow ratio
# y_p (busiest first) each adaptation, i.e. a real-time phase-SEQUENCE solve.
SCATS_SEQUENCE_BY_Y  = False
# ── ACTUATED GAP-OUT (2026-10-20) ─────────────────────────────────────────────
# "Switch to service when cleared": end the current phase early once its queue is
# GONE and arrivals have dried up, and move to the next phase that HAS demand.
# Guards protect future vehicles: never before the min green, never while a queue
# stands or arrivals are high, only to a phase with demand, not the bus phase, and
# never during a TSP grant.
SCATS_GAP_OUT          = False
SCATS_GAP_MIN_GREEN_S  = 10.0   # earliest early-termination (s of green)
SCATS_GAP_MAX_OCC_VEH  = 1.5    # standing queue must be <= this to count as cleared
SCATS_GAP_MAX_FLOW_VPH = 200.0  # arrival flow must be <= this (else future vehicles)
SCATS_GAP_NEXT_MIN_Y   = 0.02   # next phase needs y above this to be worth serving
SCATS_GAP_EVERY_S      = 1.0    # check cadence
SCATS_GAP_BUS_PHASE    = False  # gap-out the bus phase too (default: no)
# MAX-OUT pair: force-terminate at SCATS_MAX_OUT_S even if the phase is not clear.
# MEASURED REGRESSION (2026-10-21): two follow-on options are kept but DEFAULT
# OFF, because together they cost more than they bought on this network:
#   SCATS_MAX_OUT_PLAN_AWARE    -- bound = max(SCATS_MAX_OUT_S, this phase's
#       commissioned green) instead of the flat cap.
#   SCATS_MAX_OUT_DEMAND_GUARD  -- hold a still-busy phase past that bound.
# Dropping the flat 55/70 s ceiling let the 81-84 s bus phases run full; cycles
# inflated (ACT_EXTEND still adds green elsewhere) and the corridor fell into the
# MP-arm failure basin. Same seed, same build otherwise:
#   CHAMP_SCATS_DSGATE      111.0 -> 75.2
#   CHAMP_SCATS_DSGATE_REL   95.8 -> 52.3
#   NASH_BARGAIN            100.9 -> 51.7
# while untouched arms stayed bit-identical (NO_TSP 127.0, CHAMP_PBIL 119.7),
# which is what isolates the change. Only enable WITH a cycle-level cap
# (extend + max-out <= commissioned cycle), not on its own.
SCATS_MAX_OUT     = False
SCATS_MAX_OUT_S   = 60.0
SCATS_MAX_OUT_PLAN_AWARE   = False
SCATS_MAX_OUT_DEMAND_GUARD = False
SCATS_MAX_OUT_GRACE_S      = 5.0
# DS TRUTH CHECK (2026-10-21): log a per-junction/per-phase estimate snapshot
# every DS_TRUTH_INTERVAL_S and, at AAPIFinish, join it to the results folder's
# section_timeseries.csv (Aimsun's per-section queue_veh at ~30 s). Writes
# ds_truth_check_<exp>_<ts>.csv (row level) and _summary.csv (bias/MAE/RMSE/corr
# per junction), so the DS/queue estimator is scored against the simulator
# instead of trusted. Costs one cached snapshot read per junction per interval.
DS_TRUTH_CHECK             = True
DS_TRUTH_INTERVAL_S        = 30.0
# ── CYCLE CAP (2026-10-21) ───────────────────────────────────────────────────
# The precondition for enabling SCATS_MAX_OUT_PLAN_AWARE. Actuated extend (+ any
# GE/INS debt the cycle recovery could not trim) may add at most
# max(CYCLE_CAP_SLACK_S, CYCLE_CAP_SLACK_FRAC * commissioned_cycle) seconds per
# cycle; once spent, extension stops until the next cycle. This is what stops the
# plan-aware bound from inflating the cycle and breaking coordination -- the
# failure measured when plan-aware max-out ran WITHOUT it (DSGATE 111 -> 75).
# Off by default: enable together with SCATS_MAX_OUT_PLAN_AWARE as a pair.
CYCLE_CAP_ENABLE      = False
CYCLE_CAP_SLACK_S     = 4.0
CYCLE_CAP_SLACK_FRAC  = 0.05
# ── DS BIAS / RELIABILITY (2026-10-21) ───────────────────────────────────────
# _finalize_ds_truth_check writes LOG_DIR/ds_bias_calibration.json every run.
# With DS_BIAS_CORRECT the per-(junction,phase) measured queue bias is subtracted
# from the standing-queue term before it feeds DS. With DS_GATE_REQUIRE_RELIABLE
# the DS gate is bypassed at junctions whose estimate does not correlate with
# Aimsun's measured queue (corr < DS_CALIB_MIN_CORR) or is too biased
# (MAE > DS_CALIB_MAX_MAE_VEH). Both default OFF: calibrate on a known-good run
# first, then enable, so a calibration measured under a broken controller is
# never applied silently.
DS_BIAS_CORRECT            = False
DS_GATE_REQUIRE_RELIABLE   = False
DS_CALIB_MIN_N             = 50
DS_CALIB_MAX_MAE_VEH       = 6.0
DS_CALIB_MIN_CORR          = 0.25
# ── SPILLBACK GATE (2026-10-20) ───────────────────────────────────────────────
# WIN-ONLY actuation that preserves the commissioned backbone: if the CURRENT
# phase's downstream receiving link is >= SPILLBACK_GATE_FRAC full, continuing its
# green only pumps vehicles into a standing queue (the cascade that collapses
# throughput). Force an early switch to a phase whose downstream HAS room. Runs
# inside _actuated_gap_out (so it composes with gap-out / max-out). Downstream
# fullness = veh on the turning TO-section / (length*lanes / JAM_VEH_SPACING_M).
SPILLBACK_GATE      = False
SPILLBACK_GATE_FRAC = 0.80      # downstream >=80% full -> stop feeding it
JAM_VEH_SPACING_M   = 7.0       # m/veh jam storage (veh length + gap)
# SCATS PERSONALITY FALLBACK (2026-10-21): recover a phase with real commissioned
# green but NO ECI signal-group turning (model-geometry blind spot, e.g. 36393
# ph4 / 39587 ph4) by attaching the SCATS-derived SIDE/RT_BAY approach sections
# from kg/scats_channel_sections.py. Makes the unmeasured phase visible to the DS.
# DISABLED 2026-10-21: attaching SCATS SIDE/RT_BAY sections to an undiscovered
# green phase REGRESSED PBIL (739->748/781). Those phases (36393 ph4, 39587 ph4)
# carry NO vehicle turning because they are PEDESTRIAN / clearance / unmodelled --
# the "no turning" was CORRECT, not a gap. Attaching fake vehicle demand made the
# split serve a carless phase. Leave such phases OUT of _phase_origin_sections so
# they are held at their commissioned green (see _nonvehicle_phases freeze).
SCATS_PHASE_ORIGIN_FALLBACK = False
# RELIEF NEEDS DOWNSTREAM (2026-10-21): a standing-queue phase only earns relief
# green if its receiving link can take the discharge. If its downstream is jammed
# (>= SPILLBACK_GATE_FRAC), the queue is downstream-limited -> more green is thrown
# away and starves a phase that CAN discharge, so suppress the queue boost there.
RELIEF_NEEDS_DOWNSTREAM = False
# ── ACTUATED EXTEND (2026-10-21) ──────────────────────────────────────────────
# Companion to gap-out: while the CURRENT phase is still BUSY (standing queue OR
# arrivals above a floor) and its downstream has room, stretch its green by
# ACT_EXTEND_STEP_S once per step, up to ACT_EXTEND_MAX_GREEN_S. With gap-out
# (shorten when cleared) this is a pure vehicle-actuated hold/release controller
# on the current phase. LOCAL (extending shifts the cycle) -> actuated arm only.
ACTUATED_EXTEND        = False
ACT_EXTEND_STEP_S      = 3.0    # seconds added per extension step
ACT_EXTEND_MAX_GREEN_S = 50.0   # absolute hard cap (fallback)
# BOUNDED EXTEND (2026-10-21): real ceiling = commissioned green * (1+BAND), capped
# at commissioned + ABS_CAP_S. Stops a side phase ballooning past the main's slot
# (the CHAMP_ACTUATED 1742-vs-642 gridlock). Keep the extend GENTLE, like splits.
ACT_EXTEND_BAND        = 0.30   # +30% of commissioned green, max
ACT_EXTEND_ABS_CAP_S   = 8.0    # ... and never more than +8s absolute
ACT_EXTEND_MIN_OCC_VEH = 2.0    # busy if standing queue >= this ...
ACT_EXTEND_MIN_FLOW_VPH = 300.0 # ... OR live arrivals >= this
ACT_EXTEND_BUS_PHASE   = False  # leave the bus phase to the bus-priority module
# LEAD/LAG left-turn ordering: heavy through (y >= SCATS_LEADLAG_HEAVY_Y) -> the
# turn LAGS behind it; light through -> the turn LEADS. Applied via _plan_sequence.
SCATS_LEADLAG          = False
SCATS_LEADLAG_HEAVY_Y  = 0.5
# CRITICAL-INTERSECTION cycle selection: the master sets the subsystem cycle from
# the member with the largest total flow ratio Y=sum(y), not the max single DS.
SCATS_CRITICAL_INTERSECTION = True
# PLAN-LIBRARY selection: choose a STORED plan by demand regime (Y bucket) instead
# of re-solving every interval; new solves are stored per regime.
SCATS_PLAN_LIBRARY = False
# POG-DRIVEN OFFSET HILL-CLIMB: nudge each offset by +/- step and keep the direction
# that raised arrivals-on-green; reverse when POG falls (derivative-free).
SCATS_POG_OFFSETS  = False
SCATS_POG_STEP_S   = 3.0
SCATS_POG_EPS      = 0.01
# Small-increment damping for the proportional split: move each phase at most this
# many seconds per cycle toward the flow-ratio target (SCATS reviews/modifies the
# plan "in small increments, almost cycle-by-cycle"). 0 disables the damping.
DS_SPLIT_MAX_MOVE_S = 6.0
# DS_SPLIT_RESTART_S: if a phase's green target moves by more than this many
# seconds vs the live plan, RESTART the cycle (jump to the first phase of the new
# plan) instead of nudging -- a big split change means the old cycle is stale.
DS_SPLIT_RESTART_S = 10.0
# DS_SPLIT_CRITICAL_LANE: use the CRITICAL (max) lane flow ratio as the split
# weight instead of the summed flow ratio -- SCATS balances the worst lane.
DS_SPLIT_CRITICAL_LANE = False
# SCATS subsystem formation: within a corridor, open a NEW subsystem when a
# junction's commissioned cycle exceeds this factor x the running minimum, so a
# 60 s site is never dragged onto a 120-135 s common cycle.
DS_MASTER_SUBSYS_SPREAD = 1.6
# ── DYNAMIC SUBSYSTEM MARRIAGE / DIVORCE (2026-10-19) ─────────────────────────
# SCATS links (marries) adjacent subsystems onto one common cycle while their
# REQUIRED cycles are compatible and splits them (divorces) when demand pushes a
# junction's required cycle away from its neighbours'. When DS_MARRY_DIVORCE is on,
# the master re-partitions each corridor's geographic member list every solve from
# the live required cycles (engine._remarry_subsystems). DS_MARRY_TOL = max
# |req_i-req_j|/max to stay married; DS_MARRY_HYST = hysteresis band so the
# boundary does not flap; DS_MARRY_HOLD_S = a change must persist this long before
# it commits (~1-2 cycles). Off by default => the init-time compatibility grouping.
DS_MARRY_DIVORCE = False
DS_MARRY_TOL     = 0.15
DS_MARRY_HYST    = 0.05
DS_MARRY_HOLD_S  = 120.0
# SCATS PHASE SKIPPING (2026-10-19): a phase whose measured demand weight is
# (near-)zero and is NOT the bus phase drops to SCATS_SKIP_GREEN_S instead of the
# full min-green floor, so its unused green is reclaimed for the critical phase --
# SCATS does not service a phase with no demand. The split walk logs [DS SKIP].
SCATS_PHASE_SKIP   = False
SCATS_SKIP_DS      = 0.05    # phase weight <= this -> skippable
SCATS_SKIP_GREEN_S = 3.0     # green a skipped phase is trimmed to (s)
# SCATS_SIDE_MONITOR: fold a standing queue on the KG SIDE / RT_BAY / SLIP channel
# sections (wired to SECTION ids; the model has no physical side/turn loops) into
# the junction DS as a side-spillback floor on the least-loaded phase, so the
# split law can serve the cross street instead of reading the junction idle.
SCATS_SIDE_MONITOR = True
# PLAN_MEASURED (2026-10-19): run the PLAN_OPTIMIZE warm-start but source the base
# plan from the network's own COMMISSIONED cycle + SPLITS instead of the OD-demand
# Webster prior (which is a network-wide average, near-flat across phases, and
# starves the main approach). Lets every SCATS/SCOOT arm run PLAN_OPTIMIZE=True
# (the plan is still logged/applied/reasserted) without the misleading prior.
PLAN_MEASURED = False
# ── PLAN_SCATS_HIST (2026-10-20): seed the startup plan from the junction's
# REAL SCATS commissioned plan (see engine._plan_opt_scats_hist). Source: the
# iMove SCATS File Share region RAM export (the Central Manager .bak is a SQL
# Server backup, unreadable without a restore). Loader: scats_hist_plan.py.
# SCATS_HIST_DAYTYPE: day-type code in the SCn>DD*HH:MM=plan schedule (8 =
# weekday). SCATS_HIST_TOD_MIN: the time-of-day in minutes used to pick the
# scheduled plan (480 = 08:00; 0 => use the simulation clock).
PLAN_SCATS_HIST = False
SCATS_HIST_SHARE = r'C:\Users\ahernz\github_for_aimsun\iMove SCATS File Share'
SCATS_HIST_DAYTYPE = 8
SCATS_HIST_TOD_MIN = 480.0
# ── VIRTUAL INDUCTIVE LOOP (2026-10-19) ───────────────────────────────────────
# Aimsun's own loop-like count (all-type partial statistics) returns report != 0
# for EVERY KG modeled/virtual section (verified: 0 of 53 live readings landed on
# tier=partial), so the controller was running off a density x speed SNAPSHOT and
# then a FLAT OD seed (1372.8 veh/h on every unmeasured approach) -- the source of
# the garbage Webster splits. This flag makes the flow primitive count vehicle
# CROSSINGS (entries) of the approach section, exactly like an inductive loop:
# flow = crossings in a rolling window. A stopped queue still reports flow and an
# empty approach reports faithful 0. VLOOP_WINDOW_S is the loop's measurement
# window (SCATS reviews almost cycle-by-cycle); VLOOP_WARM_S suppresses the
# initial fill; VLOOP_MIN_WINDOW_S bounds the early-window rate.
VLOOP_EMULATION    = True
VLOOP_WINDOW_S     = 60.0
VLOOP_WARM_S       = 20.0
VLOOP_MIN_WINDOW_S = 10.0
# VLOOP_VISIT_GAP_S: a vehicle is a new CROSSING only if it was last seen on the
#   section longer ago than this (s). Robust to section-boundary flicker, which
#   otherwise re-counts the same vehicle every tick (~5x over-count).
# VLOOP_SANE_FACTOR: reject a loop reading whose implied flow exceeds this factor
#   x the section's saturation (unreliable over-count) and FALL BACK to the
#   density x speed snapshot, instead of clipping to saturation (which pinned DS
#   at the clamp and produced garbage splits/cycle/offsets).
VLOOP_VISIT_GAP_S  = 10.0
VLOOP_SANE_FACTOR  = 1.15
# ── OCCUPANCY / SPILLBACK PRESENCE (2026-10-19) ───────────────────────────────
# A crossing counter misses a vehicle that crosses the loop then STOPS: it ages
# out of the window and flow reads 0 while the queue still stands, so the phase
# looks idle and gets starved (-> spillback). The loop also tracks STANDING
# (stopped) occupancy and real DISCHARGE (vehicles leaving) so a queue that is
# present but not clearing floors DS to saturated. VLOOP_STOP_KPH = speed at/below
# which a vehicle counts as stopped; VLOOP_OCC_ALPHA = occupancy EWMA smoothing;
# VLOOP_OCC_MIN_VEH = standing-queue size that arms the floor; VLOOP_SPILL_DIS_FRAC
# = discharge below this fraction of phase capacity == "not clearing".
VLOOP_OCC_SPILLBACK = True
VLOOP_STOP_KPH      = 3.0
VLOOP_OCC_ALPHA     = 0.3
# VLOOP_OCC_MIN_VEH raised 2 -> 6 (2026-10-19): a 2-vehicle standing queue was
# arming the spillback floor and pinning DS at 1.0 corridor-wide ([SPILLBACK]
# occ=2.0 veh ... DS floored 1.00, 249x/run). A real spillback is a queue that
# cannot clear, not two cars waiting at a red.
VLOOP_OCC_MIN_VEH   = 6.0
VLOOP_SPILL_DIS_FRAC = 0.5
# SCATS measured-only side flow: when on, the side/cross shockwave flow uses the
# virtual loop (0 on an empty approach) instead of the OD demand seed -- SCATS is
# measured-detector, not demand-prior. Off by default (TSP arms keep the seed to
# price cross demand arriving during an extended red).
SIDE_FLOW_MEASURED_ONLY = False
# One-shot DETECTION COVERAGE audit: decompose each node (signal group -> turning
# -> from-section) and flag any signalized approach not mapped to a control phase
# (a DS blind spot). Logs one [COVERAGE] line per junction. Diagnostic; harmless on.
DETECTION_COVERAGE_AUDIT = True
# SCATS GREEN-UTILIZATION DS: compute the base degree of saturation from STOP-LINE
# DISCHARGE (vehicles leaving the section, from the virtual loop) instead of arrival
# flow / capacity -- the real SCATS method (how much of the green was used at
# saturation), bounded near 1.0 instead of blowing past the clamp on arrival spikes.
# The queue + spillback floors still lift DS above 1.0 under oversaturation. Off by
# default (arrival-based v/c); on for the SCATS arms.
SCATS_DS_DISCHARGE = False
# SCATS OCCUPANCY/QUEUE-AWARE split weight: a FLOW ratio collapses to ~0 when the
# approach is jammed (nothing moving), so the proportional split reads a gridlocked
# phase as empty and robs it of green. The real SCATS loop sits occupied under a
# standing queue -> DS high. When on, the split weight (ds_flow) folds in the
# standing queue as an equivalent demand ratio so the queued phase is served.
DS_FLOW_QUEUE_AWARE = True
# GREEN-INDEPENDENT DS: report the flow-ratio DS (demand/full-capacity + queue)
# as the degree of saturation, instead of the green-referenced q/(mu*lanes*g/C)
# which blows up on a short commissioned green and INVERTS the phase ranking
# (minor 6s phase reads higher than the 81s main -> split robs the main, ds_max
# pins at the clamp even on a working plan). When on, the cycle critical-DS, the
# display, and the split weight all read the flow ratio -> true saturation, main
# correctly ranked highest. The green-referenced value is kept as ds_green_ref.
DS_GREEN_INDEPENDENT = False
# PER-MOVEMENT DS (SCATS strategic approach): a shared approach section feeds
# multiple phases, so summing the whole section flow gives every phase the full
# approach demand (a minor turn phase reads the main road -> inversion). When on,
# each phase's demand + lane count come from _phase_lane_flows (only the lanes
# heading to THAT phase's turn movements), so each phase reads its own movement --
# like real SCATS, where each strategic approach has its own detectors.
DS_PER_TURN_FLOW = False
# COMMISSIONED-BAND CLAMP: bound each phase's adaptive green to +/- this fraction
# of its COMMISSIONED green fraction (the SCATS-tuned split that encodes the demand
# asymmetry + the coordination band). The DS-proportional split otherwise FLATTENS
# it (cuts the main arterial's 81s band to ~19s) and gridlocks the corridor. 0 =
# off (unbounded, old behaviour). 0.35 = adapt within +/-35% of commissioned.
DS_SPLIT_COMMISSIONED_BAND = 0.0
# DEMAND-WEIGHTED BAND EXCEPTION (2026-10-20): the commissioned band can
# PERMANENTLY starve a phase the commissioned plan itself under-serves (39590:
# the 4-lane main got a ~6s commissioned green; 1.3x of 6s is 7.8s -- the
# band built to protect the commissioned split cements that mistake). When a
# phase's compressed DS split weight is at/above DS_BAND_DEMAND_DS, its band
# CEILING is lifted to DS_BAND_DEMAND_MULT x its commissioned share (floor
# unchanged). All three must be set: ENABLE + DS threshold + ceiling multiple.
DS_BAND_DEMAND_ENABLE = False
DS_BAND_DEMAND_DS     = 3.0
DS_BAND_DEMAND_MULT   = 3.0
# ── SCATS BUS PRIORITY JIT GATE (2026-10-20) ─────────────────────────────────
# Naive grant = +green whenever a bus sits on the bus-phase approach, even if
# the bus would CLEAR the natural green anyway (pure donor loss) or is so far
# out that the boost is spent before it arrives. With BUS_PRIO_JIT_ENABLE the
# grant happens ONLY when the bus would "just miss": ETA-to-stopline
# (distance/speed + ~2 s/veh queue-discharge) > remaining bus-phase green,
# within BUS_PRIO_JIT_STRIKE_S. Fail-open: unreadable geometry falls back to
# the legacy grant, so behaviour is never worse than before.
BUS_PRIO_JIT_ENABLE   = False
BUS_PRIO_QUEUE_DELAY_S = 2.0
BUS_PRIO_JIT_MARGIN_S = 2.0
BUS_PRIO_JIT_STRIKE_S = 30.0
# BUS EARLY-GREEN / RECALL (2026-10-21): when a bus approaches during a RED bus
# phase and would MISS (ETA <= BUS_PRIO_JIT_STRIKE_S), truncate the current non-bus,
# non-pedestrian phase (after its min-green) and bring the bus green forward. Bounded
# by the bus-prio cooldown; never skips a pedestrian phase.
BUS_PRIO_RECALL_ENABLE = False
# ── QUEUE SERVE FLOOR (2026-10-20) ──────────────────────────────────────────
# "All queued vehicles can at least make it through": a phase whose MEASURED
# standing queue needs longer to discharge than its split floor gets the
# queue-discharge time as a floor, capped at QUEUE_SERVE_CAP_S and at
# QUEUE_SERVE_MAX_FRAC of the green budget (no queue can capture the cycle).
QUEUE_SERVE_FLOOR     = False
QUEUE_SERVE_CAP_S     = 20.0
QUEUE_SERVE_MAX_FRAC  = 0.35
# ── QUEUE RELEASE DIAG (2026-10-20, zero-behaviour) ─────────────────────────
# Per-phase standing queue at green start vs green end -> how much each green
# actually discharged. One [QUEUE REL] summary per junction per period.
QUEUE_RELEASE_DIAG    = True
QUEUE_RELEASE_PERIOD_S = 300.0
# SCATS-style BUS PRIORITY (discrete request, not continuous pax-weighting): on a
# bus detected on the bus-phase approach, grant a BOUNDED green boost to the bus
# phase, taken from other phases down to min-green, with a cooldown. Keeps the DS
# pure-vehicle. BUS_PRIO_MAX_RECALL_S is reserved for early-recall (not yet wired).
SCATS_BUS_PRIORITY   = False
BUS_PRIO_MAX_EXT_S   = 10.0
BUS_PRIO_MAX_RECALL_S = 8.0
BUS_PRIO_COOLDOWN_S  = 60.0
# Reference standing queue (stopped veh per lane) at which the queue-aware split
# weight reaches ~1.0 (= a saturated flow ratio). Smaller => a queue dominates the
# split sooner / harder (serves the backlog more aggressively).
DS_QUEUE_SAT_VEH_PER_LANE = 3.0
# NO-SHUTDOWN GUARD: never let a phase with ANY detected demand (arrivals or a
# standing/stopped queue -- both measurable WITHOUT green) be skipped or folded.
# A discharge-based DS reads 0 for a phase with no green, so without this guard
# phase-skip could permanently starve a phase that actually needs to run and
# relieve the system. Floors that phase's DS + split weight above the skip/fold
# thresholds. PHASE_PRESENCE_FLOOR is the floored weight. Monitored as [STARVE_GUARD].
PHASE_STARVE_GUARD   = True
PHASE_PRESENCE_FLOOR = 0.12
# ── SCATS CYCLE CALIBRATION CURVE (2026-10-19) ────────────────────────────────
# SCATS derives the cycle length from the critical DS via an operator CALIBRATION
# CURVE (two factors), not a fixed threshold step. When on, the DS-cycle law sets
# C = c0 * (1 + K1 * (ds_crit - DS_CYCLE_TARGET)**K2) clamped to the range, then
# moves toward it at DS_CYCLE_STEP_S/window; when off the legacy +/-DS_CYCLE_HYST
# step runs. K1 is the curve gain (s per unit DS), K2 its exponent.
SCATS_CYCLE_CURVE  = True
SCATS_CYCLE_K1     = 0.6
SCATS_CYCLE_K2     = 1.0
# Master (strategic) cycle from the subsystem CRITICAL DS via the same curve --
# the SCATS regional half: the master sets the common cycle from the busiest
# member's DS (calibrated to the group's commissioned anchor), rather than taking
# the coarse demand Webster max. Gated on warm-up (DS_MASTER_DS_WARM_S) and moved
# at most DS_MASTER_DS_STEP_S per solve.
DS_MASTER_DS_CYCLE = True
DS_MASTER_DS_WARM_S = 120.0
DS_MASTER_DS_STEP_S = 5.0
# ── PER-LANE DS / WORST LANE (2026-10-19) ─────────────────────────────────────
# SCATS measures DS per LANE and takes the WORST lane of the movement. The virtual
# loop tags every crossing with the vehicle's lane (InfVeh.numberLane) and the
# turning it serves (InfVeh.idSectionTo); the phase DS is then max over the lanes
# that feed THIS phase's signal groups, so a dedicated TURN lane drives the phase
# whose signal group carries that movement instead of being averaged away by the
# summed q/(mu*lanes*g/C).
DS_LANE_WORST      = True
# ── MASTER BROADCASTS SPLITS (2026-10-19) ─────────────────────────────────────
# The master computes each member's split plan on the common cycle (green ∝
# worst-lane flow ratio) and parks it on the member's _master_split_targets, which
# the local DS adapt adopts as its base -- so the subsystem shares a coherent SPLIT
# plan, not just a common cycle + offsets.
DS_MASTER_SPLITS   = True
# ── PHASE REDUCTION (2026-10-19) ──────────────────────────────────────────────
# At a multi-phase site, fold a phase whose measured demand is negligible and that
# shares an approach with a busier phase INTO the busier phase, and reduce the
# enforced phase sequence accordingly -- the SCATS behaviour of servicing fewer
# phases. RESTRUCTURE_MERGE_DS is the demand weight (worst-lane flow ratio) below
# which a non-bus phase is foldable. Makes >RESTRUCTURE_MAX_PHASES sites eligible.
RESTRUCTURE_MERGE_SAME = False
RESTRUCTURE_MERGE_DS   = 0.10
# ── SCOOT-RS (2026-10-19): the TRL-SCOOT control law ──────────────────────────
# A distinct adaptive law from SCATS, ported from the SCOOT reference (scoot-ai):
#   CYCLE (regional)  -- the MASTER grows the common cycle when the subsystem's
#     CRITICAL (busiest) degree of saturation exceeds SCOOT_RS_TARGET_DS and
#     shrinks it when every member is below (hysteresis band stops hunting). This
#     is SCOOT's "critical intersection" cycle rule, made regional.
#   SPLITS (local)    -- green is proportional to each phase's MEASURED FLOW (the
#     cyclic flow profile): green_p = mg + (eff - n*mg) * q_p / sum(q). The phase
#     carrying more flow gets more green (vs SCATS, which equalises DS).
#   OFFSETS (regional)-- the green starts where the upstream platoon arrives
#     (travel-time cumulant along the route), the coordinator's green-wave solve.
# Bus-free: the only bus effect is the passenger-weighted DS. SCOOT_RS_MODE implies
# the split job; pair with DS_MASTER_CYCLE so the regional cycle is embedded/applied.
SCOOT_RS_MODE         = False
SCOOT_RS_TARGET_DS    = 0.90   # critical-DS threshold (SCOOT's 90% rule)
SCOOT_RS_HYST         = 0.05   # deadband around the threshold (stop hunting)
SCOOT_RS_CYCLE_STEP_S = 5.0    # common-cycle increment per regional update (s)
SCOOT_RS_MIN_RATIO    = 0.5    # common cycle >= MIN_RATIO x group commissioned
SCOOT_RS_MAX_RATIO    = 1.5    # common cycle <= MAX_RATIO x group commissioned
SCOOT_RS_WARMUP_S     = 300.0  # use the demand (Webster) plan until flows warm up
SCOOT_RS_OFFSETS      = True   # regional green-wave offsets (PLAN_OPTIMIZE_OFFSETS)
# ── NET PASSENGER THROUGHPUT objective (2026-10-14) ───────────────────────────
# Make the reward the people PUT THROUGH the system (net of switching capacity
# loss) instead of a delay ledger -- ungameable by starvation. See
# engine._net_pax_throughput_delta. Blend the old ledger back via W_DELAY_LEDGER.
THROUGHPUT_REWARD = False   # net-throughput IS the objective when True.
W_THROUGHPUT      = 1.0     # weight on the net-throughput term (pax·s).
W_DELAY_LEDGER    = 0.0     # weight on the legacy delay ledger (0 => pure throughput).
THRU_STARTUP_LOST_S = 2.0   # per-phase startup lost time in the capacity model.
# Multi-head Q: separate Q-head per objective (bus-priority vs net-throughput),
# each over its own state, mixed by a regime gate. See dctsp_bxt.
MULTIHEAD_Q       = False
MULTIHEAD_ACTION_FAMILY = False   # deliberate redesign: throughput head keys differ by
                                  # action family so the two heads can choose differently.
MULTIHEAD_W_NET   = 1.0     # base weight of the network (throughput) head.
MULTIHEAD_NET_GATE_DSMIN = 0.60  # DS below which the net head is idle (free flow).
# ── Flags that WERE orphans (2026-10-15 flag-propagation audit) ───────────────
# These were read only via globals().get(...) with an inline default and were in
# NEITHER the engine propagation whitelist NOR MODE_FLAGS -> an arm's override
# never took AND (for engine-read ones) could carry over between arms. Declaring
# a module default + listing them in MODE_FLAGS makes AAPIInit reset+propagate
# them to BOTH _spm and engine globals every arm (engine.py ~20034 / ~20330).
MODE_NET_BENEFIT_GATE = True   # engine commit-veto clamp enable (SCATS/THRU arms
                                # set this False to run ungated).
NET_GATE_RATIO        = 1.0    # break-even ratio the clamp targets.
# ── Global-delay break-even + main-corridor floor (2026-10-17) ─────────────
# The scored objective is PaxEquivPassages / TotalPassDelay_hrs (network-wide),
# but every guard above is per-junction and the DS/bargain arms switch
# MODE_NET_BENEFIT_GATE off -- so nothing stopped a locally-"cheap" action from
# blowing up total passenger delay (NASH seed600 +60%, CELLQ +36% vs same-seed
# NO_TSP). NET_PAX_DELAY_GATE is the objective-aligned HARD safety net on the
# full local social ledger (_car_for_veto); MAIN_CORRIDOR_FLOOR_GATE caps the
# pax-seconds of MAIN-approach delay an action may add. See engine._dctsp_eval_action.
NET_PAX_DELAY_GATE     = True   # hard break-even: social_cost <= bus_benefit * ratio.
NET_PAX_DELAY_RATIO    = 1.0    # break-even ratio the net gate targets.
MAIN_CORRIDOR_FLOOR_GATE = True  # cap main-approach delay harm vs the bus benefit.
MAIN_CORRIDOR_HARM_RATIO = 1.0   # main harm must not exceed bus_benefit * ratio.
BXT_WARMSTART_FROM_SHARED = False  # pool early experience across signals (CELLQ
                                   # arms request True via _CELLQ_GATED_BASE).
# Minimum effective bus delay required before BXT may choose a TSP action.
# A positive experiment override replaces SELFORG_MIN_BUS_DELAY_S.
CELLQLEARN_MIN_GAIN_S = 0.0
# Cap on a BXT phase-insertion duration (s).  Long insertions truncate the
# current main-street green and are the most disruptive BXT action, so clamp
# them instead of committing the full 15-20 s candidate (mode-commits-own-
# action bypasses the standard BP_upper_bound clamp).
BXT_MAX_INS_S = 12.0
# ── Timing solver: differential evolution on the integer lattice ─────────────
# BXT_SOLVER='de' routes every committed timing magnitude (GE via
# solve_green_extension, BP/insertion via solve_bus_phase_green, plus the two
# legacy direct harmony_search call sites now dispatched through
# _solve_timing_min) through DE/rand/1/bin on whole seconds: global like
# harmony, discrete + deterministic unlike harmony (stochastic) and golden
# (continuous output). Pure stdlib+numpy (scipy is unloadable in-sim).
TIMING_DE_POP = 10
TIMING_DE_GENS = 6
TIMING_DE_F = 0.7
TIMING_DE_CR = 0.9
TIMING_DE_SEED = 12345
# REWARD_GE_SOLVER: how the GENERIC-pool GE magnitude is chosen. 'grid'
# (legacy) args-maxes over REWARD_GE_CANDIDATES; 'de' runs DE on the DECISION
# reward itself; 'exact' exhaustively arg-maxes the reward over the integer
# lattice in [MIN_GE_EXTENSION_S, MAX_GE_EXTENSION_S] -- the true optimum on
# a ~13-value domain, deterministic, ~13 evaluator calls. Solved modes fall
# back to grid on any failure. Default 'grid' (legacy behaviour).
REWARD_GE_SOLVER = 'grid'
# GE_MAX_FRAC_OF_CYCLE: corridor-agnostic GE bound. A fixed MAX_GE_EXTENSION_S
# means different things on a 60 s cycle vs a 135 s one, so the effective GE
# upper bound is min(MAX_GE_EXTENSION_S, GE_MAX_FRAC_OF_CYCLE * cycle_s) with
# the cycle discovered live per junction (_signal_cycle_s). Solved magnitudes
# ('de'/'exact') additionally clamp to the junction's own recoverable headroom
# (RECOVERABILITY budget + slack), so the solver can only pick what the cycle
# can repay this cycle. 0 disables the fractional cap (global MAX only).
GE_MAX_FRAC_OF_CYCLE = 0.15

# MEASURED_TURN_COST (2026-09-28): price side delay PER TURNING instead of per
# section. A dedicated/protected turn lane is a distinct movement with its own
# queue and phase; the section-level side cost lumps it into the approach
# average. When on, _compute_side_delay_penalty decomposes the side delay over
# each non-bus phase's turnings (from _phase_movement_map), splitting a
# section's zone queue evenly across the turnings that share it and charging
# each under its own phase's extra red. Additive: blended (max) with the
# measured/fallback costs. Default OFF (legacy section-level behaviour).
MEASURED_TURN_COST = False

# FOCUS_SCOPE_RADIUS_M (2026-09-28): the legacy bus-focus mechanism serialised
# TSP actions to ONE bus GLOBALLY -- a bus anywhere in the network suppressed
# every other bus's priority, even on the far side of the corridor. With
# per-window arbitration (R10) and convoy coupling (R11) now handling true
# conflicts, only buses SPATIALLY CO-LOCATED with the focus bus need
# serialising. Buses farther apart than this radius act concurrently. The
# buses themselves are never removed from the network -- focus only gates
# which bus's signal action may fire. 0 = legacy global serialisation.
FOCUS_SCOPE_RADIUS_M = 800.0

# MULTIBUS_JOINT (2026-09-28): observe ALL buses approaching a junction and act
# on the one whose service maximises reward, instead of only the first/late
# detected bus. oncoming_buses() already lists every bus within the horizon;
# this selects the argmax of occupancy x lateness-urgency at each junction
# (R10 keeps one action per window; R11's green-keep covers a following
# convoy). A true network-wide joint search is the follow-up; this is the
# per-junction reward-optimal bus choice. False = legacy (first/late bus).
MULTIBUS_JOINT = False

# MULTIBUS_NETWORK (2026-09-28): the corridor-wide joint pass on top of
# MULTIBUS_JOINT. optimize_network() assigns ONE bus per junction (R10 window
# exclusivity) and arbitrates OPPOSING-direction buses at ADJACENT junctions
# whose windows would collide (the two-direction offset fight): it keeps the
# higher combined-score configuration and demotes the other junction to its
# runner-up. This is the decision per-junction best_bus_for cannot make alone.
# False = per-junction selection only.
MULTIBUS_NETWORK = False

# ── Extended learner state (2026-09-28) ────────────────────────────────────
# The BXT/CellQLearn state is a 4-tuple (bus-queue, side-ratio, phase-match,
# eta). These append richer OBSERVED state so the policy conditions on the
# network, not just the bus:
#   STATE_INCLUDE_FLOW_QUEUE   -> + (t-cycle, main-flow, side-flow,
#                                   main-queue, side-queue, bus-present,
#                                   bus-lateness) bins from the measured feeds
#   STATE_INCLUDE_NEIGHBOUR_TIMING -> + one bin per corridor NEIGHBOUR: the
#                                   relative offset (my bus-green start vs the
#                                   neighbour's, mod cycle) -- the "cycle time
#                                   between intersections" the learner sees,
#                                   so it learns the coordination relationship
#                                   to upstream/downstream, not a lone junction.
# Both add table dimensions (sample cost); gate off for the base comparison.
STATE_INCLUDE_FLOW_QUEUE = False
# Queue SOURCE for the state bins (2026-10-03): the state used to blend a
# MODEL queue (main = MaxQueueLength shockwave) with a MEASURED count (side =
# latest_section.queue_veh). Now PHYSICAL-COUNT-FIRST: the main queue uses the
# live stopped-vehicle count when available (fallback: MaxQueueLength), and the
# side queue falls back to live section counts when the feed is stale -- so the
# state and the reward see the same physical queue. False -> legacy sources.
STATE_QUEUE_PHYSICAL_FIRST = True
STATE_INCLUDE_NEIGHBOUR_TIMING = False
# STATE_INCLUDE_BUS_COUNT (2026-09-30): + (bus-count, bus-share) bins so a
# bus-heavy queue and a car-heavy queue map to different states (40 vs 1.5
# pax/veh want different actions). STATE_INCLUDE_SIGNAL_CLOCKS (2026-09-30):
# + (elapsed-green, clearance-status) bins so dwell/clearance-aware policies
# are learnable. Same sample-cost caveat; both gate off for the base.
STATE_INCLUDE_BUS_COUNT = False
STATE_INCLUDE_SIGNAL_CLOCKS = False

# PROGRESSION_DEGREE_WEIGHT (2026-09-28): MIDDLE junctions are harder than
# ends -- their offset shift must satisfy TWO coordinated neighbours (the
# platoon displaces in BOTH directions), ends only one. The progression cost
# is per-direction POG-weighted; a middle junction should therefore price
# its action against BOTH bands. When on, _progression_cost scales by the
# junction's corridor degree (1 for ends, 2 for middles), so middles act
# conservatively by construction -- the mechanism that feeds the harder
# position through to the decision. False = legacy single-direction cost.
PROGRESSION_DEGREE_WEIGHT = False
# (2026-10-13) Was True. With a True default the CHAMP_CELLQ_DEGREE arm, which
# sets the flag to True, was a no-op and produced results byte-identical to
# CHAMP_CELLQ_CONT_DE on every seed. Default is now False so the arm is a real
# A/B. The term additionally needs (not _opp_ok) and is scaled by
# max(PROGRESSION_DEGREE_MIN_DEGREE, corridor_degree).
PROGRESSION_DEGREE_MIN_DEGREE = 1.0
# Price the offset shift against BOTH coordinated main bands, each by its OWN
# measured flow (not a x2 degree proxy) -- correct on asymmetric corridors.
PROGRESSION_BIDIRECTIONAL = True

# HEADROOM_RESERVE_S (2026-09-28): carve repayable slack into the plan. Logan
# runs every cross phase at/near minimum green, so recovery trims can never
# fire (ret=0 all runs) and every GE/INS is permanent drift. This flag, at
# startup, moves RESERVE seconds from the bus phase to EACH non-bus phase
# (cycle conserved, bus floored at its min green): the cross phases now sit
# RESERVE above minimum, so _reward_get_recoverable returns a real budget and
# TSP debt can actually be repaid. Costs main capacity by RESERVE x n_cross
# seconds/cycle -- the honest A/B. 0 = legacy plan.
HEADROOM_RESERVE_S = 0.0

# ── Offline-retiming load-back (retime/*.csv) ─────────────────────────────
# RETIME_APPLY: at each junction's first tick, load RETIME_CSV (absolute path;
# falls back to <bundle>/retime/retime_v1.csv) and set the listed stage-green
# durations via ECI (splits only, v1). Phase starts shift by construction, so
# part of the DP offset follows automatically; the residual offset walk is
# stage 2 (needs the OC path, not a duration write). Read-back verified per
# junction ([RETIME] lines); any mismatch fails SAFE to the base plan (log +
# continue, never block a batch). Default OFF.
RETIME_APPLY = False
RETIME_CSV = ''

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
# 2026-10-10: 1.3 -> 1.0. Any tilt >1.0 over-weights bus pax vs car pax on top of
# the real occupancy (BusOcc=40 already gives a bus ~27x a car), so the reward was
# NOT minimising TOTAL system delay -- it bought bus time past the point where the
# equal-pax-second car cost outweighed it (served fewer passengers, higher total
# delay -- the starvation pattern the served-pax metric exposed). 1.0 makes
# R = bus_pax_saved - car_pax_added a TRUE signed change in total passenger-delay.
BUS_PAX_WEIGHT = 1.0
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
NASH_BUS_WEIGHT     = 1.0    # bargaining power p_T (1,1 => symmetric Nash; p_T=0 = utilitarian)
NASH_CROSS_WEIGHT   = 1.0    # bargaining power p_C
NASH_MIN_BUS_DELAY_S = 5.0   # gate 1: don't bargain for a barely-delayed bus
NASH_MIN_GAIN_S      = 5.0   # gate 2: min transit gain (s) * bus_occ to act
# STATE-DEPENDENT THREAT POINT (default OFF): the disagreement (NO_ACTION) outcome
# the bargain is measured against should get WORSE for the bus exactly when
# preemption hurts the cross street most, so the transit side must gain MORE to
# strike a bargain on a congested corridor. When on, the transit gain factor in the
# Nash product becomes (bps - d_T) with d_T = NASH_THREAT_CROSS_GAIN * cross_saturation
# * bus_occ (state-dependent), replacing the crude fixed MIN_GAIN as the threshold.
# This is the principled 'vary the threat, not the weights' mechanism (weights are
# policy preference; demand is already in bps; signal timing is already in cpc).
NASH_STATE_THREAT      = False
NASH_THREAT_CROSS_GAIN = 20.0  # pax·s of transit gain required per unit cross saturation
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
# Corridor coupling considers GENERAL traffic in BOTH arterial directions, not
# only the bus's heading: _continuous_corridor_penalty projects the through-platoon
# downstream landing for northbound AND southbound and sums them. Default ON so the
# coupling reflects two-way progression damage (offset shift hurts both platoons).
CORRIDOR_COUPLE_BIDIRECTIONAL  = True
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
# NO_ACTION_QUEUE_AWARE (2026-10-17): add the measured main-approach queue-
# clearance time to the no-action bus-delay baseline (see
# IntersectionController._reward_estimate_no_action).  The baseline was pure
# signal timing, so it returned 0 whenever the bus's ETA landed inside a
# bus-phase green window -- even with a standing queue ahead of the bus -- and
# R(NO_ACTION)=0 became a free option the learner could never beat (every
# action carries a positive cost), so it chose NO_ACTION almost always.
# Default True (the fix); set False to restore the legacy timing-only baseline.
NO_ACTION_QUEUE_AWARE = True
# QUEUE_DISCHARGE_S_PER_VEH: seconds of green one queued vehicle needs to clear
# the stop line (~1 / saturation-flow-per-lane; 2.0 s ~ 1800 veh/h/ln).
QUEUE_DISCHARGE_S_PER_VEH = 2.0
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
# Offensive POG (2026-09-30): POG as opportunity/need, not just cost.
# BXT_POG_BONUS rewards green-giving actions where the wave is intact
# (POG > THRESHOLD); POG_NEED_GATE scales the bus-need threshold by (1-POG)
# so evaluations stand down where the wave already serves the bus. Both
# default OFF: identical behavior when disabled.
BXT_POG_BONUS                  = False
BXT_POG_BONUS_WEIGHT           = 1.0
BXT_POG_BONUS_THRESHOLD        = 0.6
POG_NEED_GATE                  = False
POG_NEED_MIN_S                 = 15.0
POG_NEED_FLOOR                 = 0.2
# PURDUE POG COST INSIDE THE DECISION (default OFF): price the POG-weighted
# progression (green-wave) damage of an offset-shifting action IN the corridor
# decider's surplus and the Nash frontier, via the same _progression_cost the
# executor's PROGRESSION_GATE uses. The gate is a per-action veto that cannot see
# diffuse cumulative damage (many small perturbations each below threshold); making
# progression a first-class COST in the objective lets the controller prefer
# progression-preserving actions. This is the Purdue Coordination Diagram brought
# into the decision, not applied after the fact.
POG_DECISION_COST   = False
POG_DECISION_WEIGHT = 1.0
# POG_ADAPT_GATE (2026-10-19): "act according to POG". Scale the per-interval
# split/cycle move by (1 - POG): a healthy coordinated wave (high POG) is barely
# disturbed, a broken one (low POG) is repaired at full rate. Used by the POG arm.
POG_ADAPT_GATE      = False
# ── OFFLINE WARM-START PLAN OPTIMISATION (PLAN_OPTIMIZE, default OFF) ───────────
# At startup, solve each junction's cycle + phase splits (Webster) from the OD
# demand, transit-weighting the bus phase by the timetable intensity, and apply as
# the base fixed-time plan; the online methods then correct stochastic progression.
PLAN_OPTIMIZE        = False
PLAN_TRANSIT_WEIGHT  = 0.5     # bus-phase split premium per unit timetable intensity
PLAN_CYCLE_MIN_S     = 60.0
PLAN_CYCLE_MAX_S     = 150.0
PLAN_CYCLE_BAND      = 0.20    # +/- fraction of the commissioned cycle the plan /
                               # master common cycle may move within (the anchor).
PLAN_MIN_GREEN_S     = 7.0
PLAN_INTERGREEN_S    = 4.0     # lost time per phase (Webster L = n_phases * this)
PLAN_NOMINAL_HEADWAY_S = 600.0  # timetable-intensity proxy when live headway absent
PLAN_OPTIMIZE_OFFSETS = True    # also seed corridor green-wave offsets (Eq. plan_offset)
PLAN_BUS_SPEED_MS     = 11.0    # corridor bus speed (~40 km/h) for offset travel times

# ── WHOLE-SIGNAL RESTRUCTURE (PLAN_RESTRUCTURE, default OFF) ───────────────────
# The SCATS PLAN-GENERATION half: instead of only retiming the CURRENT phase list
# (DS_PLAN_ADAPT moves green between existing phases; PLAN_OPTIMIZE sets Webster
# cycle+splits on the given sequence), this REWRITES the junction's plan -- it may
# RE-ORDER the phase sequence (bring the bus phase forward) and RE-GROUP movements
# into conflict-free phases (built from the phase->signal-group->turning topology,
# validated against the conflict relation). Adopted only when the predicted bus
# saving clears RESTRUCTURE_MIN_GAIN_S; written into _plan_sequence/_plan_target_greens
# and re-imposed at rest by _reassert_plan, so it is a plan change, not a per-bus nudge.
PLAN_RESTRUCTURE       = False  # master switch (plan-level restructure)
RESTRUCTURE_EVERY_S    = 0.0    # 0 -> attempt once per cycle while at rest
RESTRUCTURE_MIN_GAIN_S = 3.0    # adopt only if predicted bus-delay saving >= this
RESTRUCTURE_ORDER      = True   # allow re-sequencing phases (bus phase earlier)
RESTRUCTURE_GROUP      = True   # allow conflict-free movement re-grouping
RESTRUCTURE_MAX_PHASES = 8      # cap on phases considered (topology scan bound)

# ── GROUP-BASED CONTROL (GROUP_BASED_CONTROL, default OFF) ─────────────────────
# Instantiate the per-junction group-based controller (ctrl.gb) and drive signal
# groups DIRECTLY (ECIChangeSignalGroupState with GREEN/RED) instead of only
# selecting configured phases. Requires control_type in {2,3} (External control);
# the controller logs [GB] CRITICAL and stays inert otherwise. This is the primitive
# that lets the signal HOLD an arbitrary conflict-free group set (a synthesised
# phase) rather than being confined to the pre-configured phase plan.
GROUP_BASED_CONTROL    = False  # enable ctrl.gb + direct signal-group steering
RESTRUCTURE_HOLD_S     = 0.0    # 0 -> hold a regrouped set for its phase's green

# ── OPTIMISED CORRIDOR OFFSET PUSH (BXT_OPT_OFFSET_PUSH, default OFF) ───────────
# The OFFSET half of plan retiming, exposed as an ONLINE action. Deliberately
# NOT the split half: the A/B of 2026-09-28 (retime/apply_retime.py:184) found
# automated Webster shares starve a main-saturated corridor -- Aimsun -46%,
# SUMO throughput -5..-7% -- while OFFSETS-ONLY kept the hand-tuned SCATS
# greens and moved only the stagger. So this action moves the bus-green START
# toward the joint (sequence, offset) optimum solved by retime/optimize.py
# (exact Viterbi DP, two-directional arrival-in-green miss) and leaves every
# green DURATION untouched. Phase splits therefore stay "given" and offsets
# become the online recourse, which is the paper's stated stance.
#
# With no CSV the target offsets come from the coordinator's travel-time cumulant
# (_compute_plan_offsets), i.e. it degenerates to the green-wave stagger only.
BXT_OPT_OFFSET_PUSH   = False   # master switch for the OPP action
BXT_OPT_OFFSET_CSV    = ''      # retime CSV: junction,offset_bus_green_start_s
BXT_OPT_PUSH_MIN_S    = 3.0     # min |delta| worth committing (same as OC)
BXT_OPT_PUSH_MAX_S    = 12.0    # max single push; the remainder re-aims next cycle
BXT_OPT_PUSH_SAT_VETO = 0.90    # skip when main x/capacity exceeds this (refuted-split guard)
BXT_OPT_PUSH_REQUIRE_BEFORE_BUS = True  # only push while the bus phase has yet to run
# ── CELLQLEARN-v2: corridor-demand controller on the cell-transition model ─────
# Reframes CELLQLEARN from bus-triggered (sparse, degenerate state between buses)
# to a CORRIDOR-DEMAND controller that changes the CURRENT phase on the CTM. Dense
# CTM-cell state, small action set {HOLD, EXTEND, END_EARLY} (+ corridor CHANGE_
# CYCLE in stage 3). STAGE 1 = CTM-greedy HEURISTIC (deterministic, doubles as the
# Q-learner's optimistic-init prior). Default OFF.
BXT_CORRIDOR_MODE = False
# Stage 2: when True, the corridor controller uses the tabular Q-LEARNER (over the
# 3 action families, heuristic-seeded, TD-updated with the CTM surplus as immediate
# reward + gamma*maxQ future); False = the stage-1 CTM-greedy heuristic. Reuses
# BXT_ALPHA/GAMMA/EPSILON.
CELLQ_CORRIDOR_LEARN = False
# ── ZIGDOG (2026-10-02): per-cycle receding-horizon AOG optimizer ──────────
# Schedule-driven: every cycle the junction re-solves the NEXT cycle's phase
# service to maximise the expected arrivals-on-green of the buses predicted
# to reach it, using the timetable ETAs + live schedule deviation and the
# MEASURED demands; the choice is cached between boundaries and re-optimised
# at each new cycle. See dctsp_zigdog below.
ZIGDOG_MODE = False
ZIGDOG_BUS_W = 4.0            # weight on the expected-AOG term
ZIGDOG_CAR_W = 1.0            # weight on the corridor (bus+mainline) surplus
ZIGDOG_LATE_BOOST_S = 120.0   # lateness at which the bus AOG term doubles
ZIGDOG_CYCLE_S = 0.0          # 0 -> use the live plan's cycle length
ZIGDOG_MAX_GE_S = 15.0
ZIGDOG_MAX_ER_S = 10.0
# Hard ER ceiling (2026-10-03): even if the grid/cap say more, ER never cuts
# more than 10s (and never more than the green remaining in the phase).
ZIGDOG_ER_ABS_MAX_S = 10.0
# INS / GREEN_REALLOC magnitudes (2026-10-03): same solved treatment as GE/ER
# (1s-resolution seeds + DE refine), bounded by these caps.
ZIGDOG_INS_GR_SOLVER = True
ZIGDOG_INS_MAX_S = 15.0
ZIGDOG_GR_MAX_S = 5.0
# Learner fixes (2026-10-03): explored actions bypass the economic guard stack
# during TRAIN/per-seed so the Q-table can actually observe their outcomes; and
# a frozen all-NO_ACTION greedy table falls back to the timing-benefit family.
BXT_EXPLORE_BYPASS = True
BXT_EVAL_HEURISTIC_FALLBACK = True
BXT_FALLBACK_MIN_BUS_DELAY_S = 15.0
# ER band respect (2026-10-04): cap every ER cut and never eat into the
# coordinated phase's protected green, so the fixed-time progression band
# survives (Aimsun KG car-delay loss of 5-9s on hard seeds).
ZIGDOG_ER_RESPECT_BAND = True
ZIGDOG_BAND_MAX_ER_S = 5.0
ZIGDOG_BAND_PROTECT_GREEN_S = 8.0
# Queue-release prediction (2026-10-04): observe each red phase's queue and
# price candidate schedule shifts by the waiting pax they delay/advance.
ZIGDOG_QUEUE_REL = True
ZIGDOG_QUEUE_W = 1.0
ZIGDOG_QUEUE_LOG_S = 60.0
# Observed-vs-expected accuracy logging for the queue-release prediction.
ZIGDOG_QUEUE_ACC = True
# Predictive arm (ZIGDOG_QP, 2026-10-04): state bits from the queue-release
# prediction and the bus fleet tracker. OFF by default (q-table compatibility).
ZIGDOG_Q_STATE_QUEUE = False
ZIGDOG_Q_STATE_BUS = False
# Traditional-TSP ER rule (2026-10-04): ER is REJECTED unless the current
# phase's queue is fully cleared (stranding discharging vehicles is bad).
ZIGDOG_ER_REQUIRE_CLEARED = True
ZIGDOG_ER_CLEAR_Q_VEH = 1.0
# Failure-corrected reward (2026-10-04): a service action whose bus did not
# improve lateness by at least ZIGDOG_Q_SERVED_MIN_GAIN gets a
# ZIGDOG_Q_FAIL_PENALTY subtracted from the TD reward (useless INS/GE/ER/GR
# must not be rewarded).
ZIGDOG_Q_FAIL_PENALTY = 50.0
ZIGDOG_Q_SERVED_MIN_GAIN = 0.0
# ── ZIGDOG performance knobs (2026-10-12) ─────────────────────────────────────
# These cap the per-solve cost (fleet forecast + seed scan) that made ZIGDOG run
# near real-time on the heavy Logan corridor. DEFAULT OFF (0) = full-resolution,
# exact prior behaviour ("KG-clean") -- so results stay comparable to older runs.
# Enable the speed-up deliberately (e.g. on slow Logan) by setting:
#   ZIGDOG_FLEET_MAX=6, ZIGDOG_MAX_SEEDS=4, ZIGDOG_FLEET_TTL_S=5
ZIGDOG_FLEET_MAX    = 0     # cap fleet forecast to N most-relevant buses (0 = no cap)
ZIGDOG_MAX_SEEDS    = 0     # cap magnitude-solver seeds per family (0 = no cap)
ZIGDOG_FLEET_TTL_S  = 0.0   # throttle: reuse fleet forecast for N s (0 = recompute)
# Kalman-tracker prune-on-exit is behaviour-neutral (only drops buses gone longer
# than the forecast horizon), so it stays ON regardless.
# Intergreen (amber + clearance) before a phase's green actually starts --
# added into the release-time prediction (defaults to PLAN_INTERGREEN_S).
ZIGDOG_INTERGREEN_S = 4.0
# Shockwave clearing correction for the queue-release prediction.
ZIGDOG_SHOCKWAVE_CORRECT = True
ZIGDOG_SHOCKWAVE_VFREEM_S = 11.0
# Inherit the CTM controller's cross cost (the same cell-transmission cell the
# CellQLearn-corridor decider prices with: sending=min(sat,n/dt), jam receiving,
# multi-hop cascade) instead of the analytic Webster/shockwave term.
ZIGDOG_CTM = True
# ── State space (2026-10-02) ──────────────────────────────────────────────
# 'phase' (default): the state is ONLY which phases are green at this
# junction -- one bit per phase. 4 phases -> 4 states per junction (48 across
# a 12-signal corridor). The per-cycle plan cache is keyed by (cycle, state),
# so each cycle re-optimises each phase-state once. 'composite' restores the
# old (bus, phase) key for A/B.
ZIGDOG_STATE_MODE = 'phase'
# ── ZIGDOG-Q (2026-10-02): plain tabular Q-learner on the SAME phase-binary
# state space (one bit per green phase; 4 phases -> 4 states/junction). 3
# actions {HOLD, GE-best, ER-best}; TD(0), epsilon-greedy, optimistic
# heuristic-seeded init (an untrained state acts like ZIGDOG). In-memory per
# replication -- the "normal qlearn" A/B for the state space.
ZIGDOG_Q_MODE = False
ZIGDOG_Q_ALPHA = 0.2
ZIGDOG_Q_GAMMA = 0.9
ZIGDOG_Q_EPSILON = 0.05
# Realized-reward / q-gated ZIGDOG-Q (2026-10-03): TD reward = measured
# standing-cost improvement (Phi_prev - Phi_now), NEUTRAL seed, states past
# ZIGDOG_Q_MIN_VISITS execute on q > 0, exploration bypasses the sign gate,
# and ER pays the same cross-street cost term as GE (fair score comparison).
ZIGDOG_Q_REALIZED_REWARD = True
ZIGDOG_Q_EXECUTE_ON_Q = True
ZIGDOG_Q_MIN_VISITS = 1
ZIGDOG_ER_CROSS_COST = True
# Per-intersection action budget (2026-10-03): caps interventions per cycle
# (ACTIONS all-in, GE-family separately) so repeated extensions cannot make a
# junction unreliable. Counted from EFFECTIVE (executed) actions.
ZIGDOG_ACTION_BUDGET = True
ZIGDOG_MAX_ACTIONS_PER_CYCLE = 3
ZIGDOG_MAX_GE_PER_CYCLE = 2
# Time-aware Q state (2026-10-03): phase bit + remaining-green bucket, so
# "do nothing" advances the state while the natural green runs out.
ZIGDOG_Q_STATE_TIME = True
ZIGDOG_Q_TIME_BUCKETS = 3
# DP-gated future pathways (2026-10-03): beam width x depth of the phase-window
# rollout; the returned best-pathway value is added to each candidate score
# with ZIGDOG_DP_W.
ZIGDOG_DP_ENABLE = True
ZIGDOG_DP_BEAM = 2
ZIGDOG_DP_DEPTH = 4
ZIGDOG_DP_W = 0.5
# Neighbour-state DP (2026-10-03): future prediction uses only the ADJACENT
# junction's live phase windows; a bus served here is credited when it reaches
# the neighbour during one of ITS bus-phase windows (travel = NEIGHBOR_TRAVEL_S).
ZIGDOG_DP_NEIGHBORS = True
ZIGDOG_DP_NEIGHBOR_W = 0.5
ZIGDOG_DP_NEIGHBOR_TRAVEL_S = 30.0
# ER magnitude solver (2026-10-03): 1s-resolution seeds + DE refine instead of
# the {10, 15} grid, so "reduce by 1 second" is available when it scores best.
ZIGDOG_SOLVE_ER = True
ZIGDOG_ER_MIN_S = 1.0
ZIGDOG_ER_FINE_S = 1.0
# HOLD/NO_ACTION == "continue the current signal plan" (the fixed-time
# sequence keeps running). ZIGDOG_FINAL_ALWAYS keeps these arms as the DECIDER
# on monitor ticks too, so the generic GE/INS pool can never override the
# plan-continuation when no intervention is warranted.
ZIGDOG_FINAL_ALWAYS = True
# FLEET AOG (2026-10-02): the re-optimisation sums the expected arrivals-on-
# green over EVERY bus predicted at this junction inside ZIGDOG_HORIZON_S
# (corridor Kalman trackers + scheduled lateness), each weighted by its
# schedule delay so a LATE bus pulls the green forward to catch up. Off ->
# score only the bus that triggered the decision (legacy single-bus term).
ZIGDOG_FLEET_AOG = True
ZIGDOG_HORIZON_S = 180.0
# Queue-first MEASURED cross cost (2026-10-03): for LOW side flow the standing
# queue is the whole cost of an extra red, so price the LIVE queue directly
# (no warm-up, no detector feed, no demand seed) and let it RAISE cpc via max().
# The arrival term (q*extra_red^2/2) is added ONLY from LIVE measured flow and
# only above ZIGDOG_MEASURED_CROSS_ARRIVAL_VPH -- below it, queue-only.
ZIGDOG_MEASURED_CROSS = True
ZIGDOG_MEASURED_CROSS_ARRIVAL_VPH = 150.0
# ── Cycle constraints (2026-10-03) ──────────────────────────────────────────
# Actions only shift SECONDS; they never skip a phase -- the plan's phase
# order is preserved so every phase is still served once per cycle. Guard:
#   * projected cycle stays within [MIN, MAX] (0 -> 0.85C / 1.15C)
#   * a phase is never cut below ZIGDOG_MIN_PHASE_GREEN_S elapsed green
#   * at most ZIGDOG_MAX_ER_PER_CYCLE Early Reds per cycle (stops ER chains
#     collapsing the cycle); GE stays clamped by the recoverability budget.
ZIGDOG_MIN_CYCLE_S = 0.0
ZIGDOG_MAX_CYCLE_S = 0.0
ZIGDOG_MAX_ER_PER_CYCLE = 1
ZIGDOG_MIN_PHASE_GREEN_S = 6.0
# ── Chain rollout (2026-10-03) ──────────────────────────────────────────────
# Instead of scoring an action only against the CURRENT green window, score
# its effect on the REST of the cycle: an Early Red advances every later
# phase (and the bus phase's return) by ~param, so buses arriving later this
# cycle can be covered too. First-order chain -- no tree search; GE is
# recovery-neutral within the cycle (the recoverability gate repays it), so
# only ER shifts the tail. ZIGDOG_CHAIN_TAIL_W weights the tail AOG.
ZIGDOG_CHAIN_PLAN = True
ZIGDOG_CHAIN_TAIL_W = 1.0
# ── INS / GREEN_REALLOC mainline-coordination constraint (2026-10-03) ───────
# Those two actions serve the controller's BusPhase.  They are permitted ONLY
# when BusPhase IS the junction's COORDINATED mainline phase -- the one aligned
# with the UPSTREAM/DOWNSTREAM signals' progression band (engine
# _actuated_coord_phase = the longest fixed phase).  On a coordinated junction
# a mismatch would shove green onto a phase the band does not serve, breaking
# platoon progression downstream -> rejected.  Non-coordinated junctions and
# unresolvable plans are not blocked.  INS_GR_COORD_PHASE_ONLY=False to A/B.
INS_GR_COORD_PHASE_ONLY = True
ZIGDOG_INS_GR_COORD_ONLY = True
# Stage-2b coupling: when True, the corridor decider subtracts the bus-free
# downstream landing cost (CONTINUOUS_CORRIDOR_NEIGHBOR_W * _continuous_corridor_
# penalty) from each green-giving candidate's surplus, so an extension that pushes
# the through-platoon into a downstream red is priced net-negative and vetoed.
# This is the c^corr coupling term of the paper's CellQLearn-v2 derivation.
CELLQ_CORRIDOR_COUPLED = False
# Exact-tracker bus benefit: when True, the corridor decider nets the local bus
# benefit by its CHAINED downstream re-delay (project_chain_delay_paxs on the
# tracked bus), so only bus time that survives the corridor end-to-end is credited
# (fixes the local-saving over-credit that doesn't realize on a coordinated corridor).
CELLQ_CORRIDOR_BUS_CHAIN = False
# CELLQ_CTM_REWARD: price the cross-approach CAR cost in the learner's surplus with
# a genuine Cell-Transmission-Model cell (sending=min(sat,n/dt), receiving=jam-
# density storage cap, conservation), parameterised from the Aimsun plant
# (SaturationFlow, JamDensity, measured arrivals, micro-queue), instead of the
# Webster/shockwave overflow term. Makes CELLQLEARN's reward actually CTM. Default OFF.
CELLQ_CTM_REWARD   = False
CELLQ_CTM_DT_S     = 1.0     # CTM discrete time step (s)
CELLQ_CTM_HORIZON_S = 0.0    # 0 => auto (ONE signal cycle); >0 overrides (seconds)
# CELLQ_STATE_NEIGHBOUR: include the corridor NEIGHBOUR junctions' state in the
# learner state (2 bins: worst neighbour saturation + any neighbour main-green), so
# the policy conditions on the coordination relationship, not a lone junction.
CELLQ_STATE_NEIGHBOUR = True
# CELLQ_CTM_SINGLE_CELL: collapse the Daganzo chain to ONE lumped cell per approach
# (cell length = section length), so storage and the stop-line gate are unchanged but
# there is no inter-cell flow and no backward-wave spillback. Use with
# CELLQ_CTM_REWARD=True to get the single-cell vs multi-cell contrast: the delta is
# then attributable to spatial structure alone, not to storage capacity.
# Default OFF (= multi-cell chain).
CELLQ_CTM_SINGLE_CELL = False
CELLQ_CTM_STATE     = False     # append a per-cell occupancy tuple to the learned Q-table state (spatial detail)
CELLQ_CTM_STATE_CELLS = 4    # fixed number of CTM occupancy bins appended (subsampling/padding)
# MULTI-CELL CTM (Daganzo chain with backward-wave spillback between cells):
CELLQ_CTM_FREEFLOW_KMH = 50.0   # free-flow speed -> cell length L=v_f*dt (per-section speedLimit overrides)
CELLQ_CTM_WAVE_KMH     = 18.0   # backward congestion-wave speed w (receiving R=min(Q,(w/v_f)*(N-n)))
CELLQ_CTM_MAX_CELLS    = 10     # cap on cells per approach (bounds compute)
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
# ── Two-way through-band floors (paper Eqs prog_in/band_*) ───────────────────
# Mirrored here so the engine's per-arm propagation AND reset_mode_flags cover
# them: without module defaults, an arm enabling the band leaked the flag into
# every later arm (batch runs share one Aimsun session). The engine reads the
# ENGINE globals; the _spm.MODE_FLAGS loop copies run_config values into both
# namespaces and reset_mode_flags() restores these defaults between arms.
TWOWAY_BAND_MODE = False
B_PLUS_MIN       = 0.0
B_MINUS_MIN      = 0.0
TWOWAY_GREEN_S   = 35.0

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
# (2026-10-20) REACTIVE MAXPRESSURE upgrades:
#   MP_PER_PHASE_PRESSURES: argmax over the MEASURED per-phase standing queue
#     per lane (engine feed) instead of the main-vs-side proxy (all side
#     phases identical -> arbitrary argmax).
#   MP_EXTEND_ENABLE/_STEP_S/_MAX_S: while the running phase REMAINS argmax,
#     gradually stretch its live duration (ECIChangeTimingPhase) by STEP_S,
#     bounded by G_MAX and MAX_S -- increment & reduce, no fixed-time retiming.
#   MP_DIRECT_TRANSITION: phase injection runs
#     ECIChangeDirectPhaseWithInterphaseTransition (yellow/all-red respected),
#     failing open to the bare direct call.
MP_PER_PHASE_PRESSURES = False
MP_EXTEND_ENABLE       = False
MP_EXTEND_STEP_S       = 3.0
MP_EXTEND_MAX_S        = 40.0
MP_DIRECT_TRANSITION   = True
# (2026-10-21) MP_NASH_ENABLE: cooperative Nash bargaining ON TOP of reactive
# MaxPressure (arm CHAMP_MP_NASH). Utility U_i = -D_i (Webster uniform delay),
# disagreement point D_i0 = min-green-only delay; maximise the Nash product
# max prod_i (U_i - U_i0) by greedy 1 s allocation (_mp_nash_alloc in engine).
# The allocation drives a per-phase token bucket: serve/extend while the
# token remains, then inject the phase with the largest remaining claim.
# Fairness property: low-volume approaches keep some green above their floor
# (their delay can never collapse to the disagreement point). Falls open to
# pure argmax pressure when demand is unmeasurable.
MP_NASH_ENABLE         = False
# ── PBIL TIMING LEARNER (2026-10-21) ──────────────────────────────────────────
# Population-Based Incremental Learning over per-phase timing genes, per
# intersection (upper-level learner of the PBIL/Max-Pressure framework,
# Ahmed-Liu-Gayah 2024; the lower level here is the existing measured split
# re-solve, which the genes modulate). Each generation (PBIL_GEN_S) samples a
# binary gene per phase from the probability vector p (init 0.5); the gene
# scales that phase's demand weight by (1+PBIL_DELTA) / (1-PBIL_DELTA) BEFORE
# the flow-proportional split allocation. Fitness = the window's accumulated
# pax-delay (from collect_delay): delay fell vs the previous generation -> the
# gene is reinforced, else its complement is. p is clamped to
# [PBIL_MIN_P, 1-PBIL_MIN_P]. State persists in a JSON file (LOG_DIR) so
# restarts / batches warm-start -- the learner keeps improving across runs.
PBIL_TS_MODE           = False
PBIL_GEN_S             = 300.0
PBIL_DELTA             = 0.25
PBIL_ALPHA             = 0.20
PBIL_MIN_P             = 0.05
PBIL_WARM_S            = 120.0   # no changes until the network warm-up is over
# ── JALLURI HEURISTIC ADAPTIVE CONTROL (Jalluri et al., OCIT 2025) ────────────
# Phase prioritisation by a weighted score of max-wait + stopped-count + an
# aging bonus; dynamic green = clearance demand x Factor / (Lanes + 1), clamped
# to [Gmin, Gmax]. See engine._jalluri_tick_one.
JALLURI_MODE           = False
JALLURI_MAX_WAIT_W     = 1.0     # weight on the phase's max waiting time
JALLURI_COUNT_W        = 1.0     # weight on the stopped-vehicle count
JALLURI_AGING_W        = 0.5     # weight on the starvation/aging bonus
JALLURI_AGING_UNIT_S   = 60.0    # aging time unit (s)
JALLURI_GREEN_FACTOR   = 1.0     # dynamic-green factor
JALLURI_CLEAR_CAR      = 2.0     # per-vehicle clearance times (s)
JALLURI_CLEAR_BUS      = 2.5
JALLURI_CLEAR_TRUCK    = 2.5
JALLURI_G_MIN          = 8
JALLURI_G_MAX          = 50
MAXPRESSURE_G_MIN     = 5      # min green per phase
MAXPRESSURE_G_MAX     = 50     # max green per phase
MAXPRESSURE_CYCLE_FIX = 120    # fixed cycle duration (Fix)
MAXPRESSURE_CYCLE_FLEX= 120    # nominal cycle for Flex (used for effective-green calc)
# MP FIX commissioned band (2026-10-21): clamp each pressure-proportional split to
# +/-band of its commissioned share, so MP FIX adapts WITHIN the commissioned plan
# (emulates SCATS) instead of flattening the main. 0 = off (raw pressure split).
MP_FIX_COMMISSIONED_BAND = 0.0
# MP FIX re-split cadence (2026-10-21): recompute the pressure split every N s, not
# just once per cycle -> more reactive MaxPressure. 0 = per-cycle (old behaviour).
MP_FIX_RESOLVE_S = 0.0
# GLOBAL OCCUPANCY SELF-CHECK (2026-10-21): corridor-wide [GLOBAL OCC] line each
# GLOBAL_OCC_MONITOR_S comparing MEASURED stopped occupancy vs the GROUND-TRUTH
# direct stopped count; flags "DETECTION NOT TRACKING" when real standing vehicles
# exceed GLOBAL_OCC_MIN_REAL but measured/real ratio < GLOBAL_OCC_RATIO_WARN.
# SIDE PRICE FROM VLOOP (2026-10-21): price a STOPPED side vehicle the earlier
# priorities missed using the embedded virtual-loop occupancy (direct count fallback)
# instead of ZERO -- closes the '% priced at ZERO' side-cost hole so the controller
# stops treating a standing side queue as costless.
SIDE_PRICE_FROM_VLOOP  = True
GLOBAL_OCC_MONITOR     = True
GLOBAL_OCC_MONITOR_S   = 60.0
GLOBAL_OCC_MIN_REAL    = 10.0
GLOBAL_OCC_RATIO_WARN  = 0.3
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
# Integer-time override for the future-horizon penalty (2026-10-03): when >0,
# the horizon is this many SECONDS instead of cycles, so the no-action future
# baseline is evaluated on a fixed integer window that is re-anchored every
# tick (rolling correction -- the window always ends at now+H).
REWARD_FUTURE_HORIZON_S = 120.0
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
    # Integer-time horizon override (2026-10-03): a fixed SECONDS window
    # re-anchored every tick, instead of cycle-length units.
    try:
        _h_s = float(globals().get('REWARD_FUTURE_HORIZON_S', 0.0) or 0.0)
        if _h_s > 0.0:
            _cycle_s = _h_s
    except Exception:
        pass
    _disturb = max(float(disturbance_s), 1.0)
    _future_frac = min(1.0, (_disturb / _cycle_s) * _h_cycles)
    return _debt_gain * _future_frac * max(0.0, float(cross_cost))


def _dctsp_eval_action(self, action_type, param, sigma_in, no_act_delay,
                       bus_eta_s, wrong_phase=False, remaining_red_s=0.0,
                       remaining_green_s=None):
    """Evaluate one candidate action, returning (reward, sigma_out, t_poz,
    bus_pax_saved_s, car_pax_cost_s, no_strategy_delay, strategy_delay).

    remaining_green_s (optional): when the caller supplies the current green's
    remaining seconds, a GE that extends it credits bus benefit ONLY if the bus
    can still be served within the extended window (bus_eta_s <= remaining_green
    + param); a bus that arrives after it earns nothing (mirrors the INS ETA
    gate). Without it the legacy behaviour is kept, so only callers that pass it
    (the corridor decider) get the gate -- validated bus-triggered arms are
    unchanged."""
    try:
        _occ = float(getattr(self, 'BusOcc', 40.0))
        _car_occ = float(getattr(self, 'CarOcc', 1.6) if hasattr(self, 'CarOcc') else 1.6)
    except Exception:
        _occ = 40.0; _car_occ = 1.6
    if action_type == 'NO_ACTION':
        sigma_out = sigma_in
        t_poz = 0.0
        bus_pax = max(0.0, float(no_act_delay)) * _occ
        # TOTAL-PASSENGER BASELINE (2026-10-19): this branch used to price ONLY
        # the bus (car_pax = 0), so doing nothing looked cheap and any action that
        # paid a car cost looked comparatively worse -- biasing the decider toward
        # HOLD. Price the main-street CARS held through the same wait: the MEASURED
        # main standing queue * no_act_delay * car occupancy. Gated by
        # TOTAL_PAX_BASELINE (module default True) so the change can be A/B'd.
        car_pax = 0.0
        if bool(globals().get('TOTAL_PAX_BASELINE', True)):
            try:
                _mq = None
                if hasattr(self, '_measured_main_queue_veh'):
                    _mq = self._measured_main_queue_veh()
                if _mq is not None and float(_mq) > 0.0:
                    car_pax = float(_mq) * max(0.0, float(no_act_delay)) * _car_occ
            except Exception:
                car_pax = 0.0
        strategy_delay = bus_pax + car_pax
        no_strategy_delay = bus_pax + car_pax
        reward = -(bus_pax + car_pax)
        return (reward, sigma_out, t_poz, 0.0, 0.0, no_strategy_delay, strategy_delay)
    param = float(param)
    # _dctsp_cross_traffic_delay_s already returns pax·s (CarOcc and
    # NETWORK_FACTOR are applied inside it) — do NOT multiply again here.
    cross_cost = float(self._dctsp_cross_traffic_delay_s(param))
    # LIVE_COST_ALWAYS: floor the returned cost with the MEASURED main + side
    # congestion so the specialised deciders (NASH/CELLQ/...) price the queues
    # they actually hold -- not just the analytic arrivals estimate.
    if bool(globals().get('LIVE_COST_ALWAYS', False)):
        try:
            _lc_occ = max(safe_float(getattr(self, 'CarOcc', 1.6)), 1.0)
        except Exception:
            _lc_occ = 1.6
        try:
            _lc_sd, _ = self._compute_side_delay_penalty(
                max(0.0, param), _suppress_log=True)
            cross_cost = max(cross_cost, max(0.0, float(_lc_sd)) * _lc_occ)
        except Exception:
            pass
        try:
            _lc_mq = self._measured_main_queue_veh()
            if _lc_mq is not None:
                cross_cost = max(cross_cost, float(_lc_mq) * max(0.0, param) * _lc_occ)
        except Exception:
            pass
    if action_type in ('GE', 'GREEN_REALLOC'):
        if not bool(wrong_phase):
            if remaining_green_s is not None:
                # REALIZABLE bus saving from the exact tracker (only when the
                # caller supplies remaining green). A GE of `param` extends the
                # current green to `remaining_green_s + param`. The bus arrives at
                # `bus_eta_s`; it MISSES the un-extended green by
                # `_miss_by = bus_eta_s - remaining_green_s`.
                #  • _miss_by <= 0  -> the bus already makes the green; GE adds 0.
                #  • 0 < _miss_by <= param -> the extension SERVES the bus, which
                #    avoids its no-action wait. This benefit does NOT grow with
                #    param, so (since cost does) the CTM picks the SMALLEST
                #    sufficient extension instead of always GE_15 -- killing the
                #    old min(no_act_delay,param) phantom that credited 200/400/600
                #    for GE_5/10/15 and a bus 50 s away.
                #  • _miss_by > param -> the extension is too short to reach the
                #    bus (a far bus would need a huge, coordination-wrecking
                #    extension) -> 0.
                _miss_by = float(bus_eta_s) - float(remaining_green_s)
                if _miss_by <= 0.0 or float(param) + 1e-6 < _miss_by:
                    # already makes the green (miss<=0) or the extension is too
                    # short to reach the bus (far bus) -> no bus benefit.
                    bus_saved_s = 0.0
                else:
                    # served: conservative credit (bounded by the extension), NOT
                    # the full next-cycle wait -- crediting the whole wait would
                    # make a served-bus GE look ~3x better and over-act; the gate
                    # above already removes the far-bus phantom.
                    bus_saved_s = min(float(no_act_delay), float(param))
            else:
                # Legacy path (callers that do not pass remaining green): unchanged,
                # so the validated bus-triggered arms behave exactly as before.
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
            # TOTAL-PASSENGER (2026-10-19): with the bus phase currently GREEN,
            # ER truncates the CURRENT (bus/through/main) phase, i.e. it CUTS
            # `param` seconds of MAIN green. The eval previously charged nothing
            # for that (it credited the cross street instead), so ER looked free
            # and fired ~20x/run while main-STREET car delay grew (seed-900:
            # MainPassDelay +42%). Charge the mainline car pax the truncation
            # displaces, symmetric with the mainline benefit GE/INS earn.
            if bool(globals().get('TOTAL_PAX_BASELINE', True)):
                try:
                    cross_cost += float(_mainline_pax_saved_for_green(self, float(param)))
                except Exception:
                    pass
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
    elif action_type == 'OFFSET_PLAN_PUSH':
        # Corridor-plan stagger realignment: move the bus-green START toward the
        # joint (sequence, offset) optimum, changing NO green duration. Priced
        # exactly like OFFSET_CORRECTION -- an advance (negative param) can pull
        # the waiting bus's green earlier, a retard earns no single-bus benefit --
        # because the plan-level platoon gain is not attributable to the one bus
        # that triggered the tick. The batch value shows up in the corridor
        # aggregate, not in this candidate's reward.
        if param >= 0:
            bus_saved_s = 0.0
        else:
            bus_saved_s = max(0.0, min(abs(float(param)),
                                       max(0.0, float(no_act_delay))))
        bus_pax_saved = bus_saved_s * _occ
        sigma_out = max(0.0, sigma_in - bus_saved_s)
        t_poz = 0.0
        cross_cost += float(self._dctsp_cross_traffic_delay_s(abs(float(param))))
    elif action_type in ('PHASE_SKIP', 'PHASE_ROTATION',
                         'PLAN_RESEQUENCE', 'PLAN_REGROUP'):
        # ── Re-timing actions: DERIVED scaling (2026-10-19) ──────────────────
        # Each of these used an arbitrary multiplier on `param` (PS 0.8; PR
        # 0.6 / 0.7; SEQ 0.6 / 0.7; RG 0.7 / 0.7) with no physical basis, so
        # they were mis-priced against GE/INS/OC and rarely won. Derive BOTH
        # sides the way GE/INS/OC already do: the bus can only recover the green
        # time the action actually pulls forward (`param`), capped by its own
        # no-action wait; the cross street pays the measured/analytic delay of
        # exactly that much green. No magic constants.
        #   * PHASE_SKIP / PHASE_ROTATION: engine passes the skipped duration
        #     (= the advance), so `param` IS the green moved.
        #   * PLAN_RESEQUENCE / PLAN_REGROUP: engine passes the committed bus
        #     green; the saving is still capped by the bus's real wait.
        _green_moved = max(0.0, float(param))
        bus_saved_s = max(0.0, min(_green_moved, max(0.0, float(no_act_delay))))
        bus_pax_saved = bus_saved_s * _occ
        sigma_out = max(0.0, sigma_in - bus_saved_s)
        t_poz = 0.0
        cross_cost += float(self._dctsp_cross_traffic_delay_s(_green_moved))
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
    # Gate the cost block on EITHER benefit term (2026-09-26): the old
    # `bus_pax_saved > 0` gate skipped the measured side + opposite-main costs
    # on continuous-monitor ticks that were NOT on the bus phase (bps_bus=0,
    # mainline>0) -- those candidates were priced analytically only.
    if bus_pax_saved > 0.0 or mainline_pax_saved > 0.0:
        # Simulator-accurate switch lost-time: the intergreen (amber + all-red
        # clearance) the plant actually loses on a phase change, READ FROM
        # AIMSUN's control plan (2026-10-10), not the hardcoded 5s -- so the
        # "time taken to change the timing" is charged at the real value. Falls
        # back to INS_INTERGREEN_S off-plant.
        _ig = float(INS_INTERGREEN_S)
        try:
            _ig = float(self._sim_intergreen_s())
        except Exception:
            _ig = float(INS_INTERGREEN_S)
        _eff_red = {
            'GE': param, 'GREEN_REALLOC': param,
            'INS': param + _ig,
            'INS_POST': param + _ig + max(0.0, float(remaining_red_s)),
            'INS_PRETERM': param + _ig,
            'OFFSET_CORRECTION': abs(param),
            'OFFSET_PLAN_PUSH': abs(param),
            'PHASE_SKIP': param,
            'PHASE_ROTATION': param,
            'PLAN_RESEQUENCE': param,
            'PLAN_REGROUP': param,
            'EARLY_RED': max(0.0, float(remaining_red_s) - _ig),
        }.get(action_type, param)
        try:
            _sd, _ = self._compute_side_delay_penalty(max(0.0, _eff_red),
                                                      _suppress_log=True)
            cross_cost = max(cross_cost, max(0.0, float(_sd)))
        except Exception:
            pass
        # ── Opposite-direction mainline cost (2026-09-26) ────────────────────
        # A green-shifting action takes time from the OTHER main direction as
        # well as the cross street, but the mainline benefit above credits only
        # the SERVED direction. Price the measured opposite-approach queue like
        # the side cost, so the action's net benefit is quantified against BOTH
        # corridor directions -- the same both-directions discipline as the
        # two-way band / offset-correction check.
        try:
            _opp_cost = float(self._measured_opposite_main_delay(max(0.0, _eff_red)))
        except Exception:
            _opp_cost = 0.0
        if _opp_cost > 0.0:
            cross_cost = max(0.0, float(cross_cost)) + _opp_cost
        # ── Current-flow DISRUPTION cost (2026-10-10) ─────────────────────────
        # An action that CUTS a running green or REORDERS phases stops the
        # platoon that was flowing mid-stream -- those vehicles must re-accelerate
        # (startup lost time) and the plant loses the intergreen seconds of main
        # discharge. Pricing only the cross benefit under-charged this disruption
        # (the "time taken to disrupt current flow and change the timing" flagged
        # by the operator), so reordering a phase looked cheaper than it is and
        # the mode deciders over-fired on saturated Logan. Charge the MAIN
        # direction the simulator-accurate intergreen lost-time of saturated
        # discharge, BOUNDED by FLOW_DISRUPTION_CAP_PAXS so it can never explode
        # (a ~5s*sat*lanes*occ term, ~8-30 pax·s -- NOT a runaway ramp). Only the
        # cut/reorder actions pay it; GE (which keeps the main flowing) does not.
        # Toggle PRICE_FLOW_DISRUPTION (default on).
        if (bool(globals().get('PRICE_FLOW_DISRUPTION', True))
                and action_type in ('EARLY_RED', 'INS_PRETERM',
                                     'PHASE_SKIP', 'PHASE_ROTATION',
                                     'PLAN_RESEQUENCE', 'PLAN_REGROUP')):
            try:
                _sat_vps = float(getattr(self, 'SaturationFlow', 1800.0)
                                 or 1800.0) / 3600.0
                _occ_d = float(getattr(self, 'CarOcc', 1.6) or 1.6)
                _ln = 1
                try:
                    _ms = (self._get_main_sections()
                           if hasattr(self, '_get_main_sections') else []) or []
                    if _ms:
                        _ln = max(1, max(int(self._sec_lane_count(int(_s)))
                                         for _s in _ms))
                except Exception:
                    _ln = 1
                _disrupt = max(0.0, _ig) * _sat_vps * float(_ln) * _occ_d
                _dcap = float(globals().get('FLOW_DISRUPTION_CAP_PAXS', 60.0)
                              or 60.0)
                _disrupt = min(_disrupt, _dcap)
                if _disrupt > 0.0:
                    cross_cost = max(0.0, float(cross_cost)) + _disrupt
                # ── MAIN-STARVATION served-passenger penalty (2026-10-12) ─────
                # On a SATURATED main, cutting `param` s of green DENIES service
                # to the vehicles that green would have discharged -- they wait
                # ~a cycle for the next green. This is the KG starvation (bus
                # delay DOWN but served-passengers DOWN): the cut shaves bus
                # delay while blocking main entries that NOTHING charged for
                # (anti-starvation protects the CROSS, not the main; the
                # disruption term above is only the ~intergreen). Charge the
                # displaced main throughput x the extra red it now faces, ramped
                # by how OVER-saturated the main is. ZERO when main x <=
                # MAIN_STARVATION_X0 (a cut on a FREE main is unpenalised --
                # keeps legit gains, KG-safe). Bounded + flag-gated; A/B it (new
                # cost terms have mis-scaled here).
                if bool(globals().get('MAIN_STARVATION_COST', True)):
                    _mx = 0.0
                    try:
                        _mx = float((self._flow_stage_snapshot() or {}).get(
                            'main_x', 0.0) or 0.0)
                    except Exception:
                        _mx = 0.0
                    _x0m = float(globals().get('MAIN_STARVATION_X0', 1.0) or 1.0)
                    if _mx > _x0m:
                        _cut = abs(float(param))
                        _cyc = 120.0
                        try:
                            if hasattr(self, '_signal_cycle_s'):
                                _cyc = float(self._signal_cycle_s() or 120.0)
                        except Exception:
                            _cyc = 120.0
                        _extra_red = min(max(10.0, 0.5 * _cyc), 90.0)
                        _displaced = _cut * _sat_vps * float(_ln)  # veh denied
                        _ramp = min((_mx - _x0m) / max(0.5, _x0m), 3.0)
                        _mpen = (_displaced * _extra_red * _occ_d
                                 * min(1.0, 0.33 + 0.67 * _ramp))
                        _mcap = float(globals().get(
                            'MAIN_STARVATION_CAP_PAXS', 4000.0) or 4000.0)
                        _mpen = min(max(0.0, _mpen), _mcap)
                        if _mpen > 0.0:
                            cross_cost = max(0.0, float(cross_cost)) + _mpen
                            if not globals().get('_MAIN_STARV_LOGGED'):
                                globals()['_MAIN_STARV_LOGGED'] = True
                                try:
                                    _log_func(self,
                                        "[MAIN_STARVATION] inter=%s act=%s "
                                        "cut=%.0fs main_x=%.2f displaced=%.1fveh "
                                        "pen=%.0fpaxs (charges blocked main "
                                        "entries -> stops delay-down-by-"
                                        "serving-fewer)" % (
                                            getattr(self, 'id', '?'),
                                            action_type, _cut, _mx,
                                            _displaced, _mpen))
                                except Exception:
                                    pass
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
    # DELAY CALIBRATION: scale the analytic benefit/cost toward Aimsun's REALISED
    # microscopic delay per approach (.DTa), so the decision tracks the plant it is
    # scored on. Main-side kappa scales the bus + mainline benefit, side kappa the
    # cross cost -- DIFFERENTIAL, so the surplus (bps-cpc) actually changes where
    # measured delay is asymmetric. Also scales the RETURNED bps/cpc so the corridor
    # decider's surplus and the Nash frontier inherit the calibration. Default OFF.
    if bool(globals().get('DELAY_CALIBRATION', False)):
        _km = float(getattr(self, '_delay_cal_main', 1.0) or 1.0)
        _ks = float(getattr(self, '_delay_cal_side', 1.0) or 1.0)
        bus_pax_saved *= _km
        mainline_pax_saved *= _km
        cross_cost *= _ks
    # Saturation-relief credit (opt-in, default OFF): benefit-side counterpart to
    # the main-starvation cost. Rewards actions that relieve a saturated main
    # approach, ramping from SAT_RELIEF_MIN_X to full at SAT_RELIEF_MAX_X.
    _relief = _sm_sat_relief_paxs(self, float(param))
    # ── NET PASSENGER THROUGHPUT component (2026-10-14) ───────────────────────
    # The objective the operator specified: maximise the people PUT THROUGH the
    # system, NET of the capacity switching destroys -- not a delay ledger (which
    # a controller games by starving). _net_pax_throughput_delta returns dPhi, the
    # change in passengers discharged per cycle (demand-vs-capacity per phase),
    # minus the intergreen/startup an INS/reorder/cut burns. Converted to pax·s
    # (x cycle C) so it is commensurate with the delay-ledger reward, and the
    # served bus folds in as its own delay saved. Ungameable by starvation: taking
    # green from a SATURATED competitor drops its throughput, so dPhi<0 and the
    # action self-gates. Computed only when a THROUGHPUT/DS/MULTIHEAD flag is on.
    _thru_paxs = 0.0   # net throughput improvement in pax·s (signed)
    if (action_type != 'NO_ACTION'
            and (bool(globals().get('THROUGHPUT_REWARD', False))
                 or bool(globals().get('DS_COST_IN_REWARD', False))
                 or bool(globals().get('MULTIHEAD_Q', False)))):
        try:
            _served_ph = int(_eci_call('ECIGetCurrentPhase', 
                int(getattr(self, 'node_id', 0) or 0) or int(self.id)))
        except Exception:
            _served_ph = -1
        try:
            _cyc = float(self._signal_cycle_s() or 120.0)
            _dphi = float(self._net_pax_throughput_delta(
                action_type, abs(float(param)), _served_ph, 0.0))  # pax/cycle
            # dPhi (pax/cycle) x C (s) = pax·s of delay avoided (a passenger not
            # put through this cycle waits ~one cycle more); + the bus's own saved
            # passenger-seconds. One commensurate currency with the delay ledger.
            _thru_paxs = _dphi * _cyc + float(bus_pax_saved)
        except Exception:
            _thru_paxs = 0.0
    # Reward assembly. THROUGHPUT_REWARD makes net throughput THE objective
    # (blend the old delay ledger back in via W_DELAY_LEDGER if wanted); else the
    # delay ledger stands, optionally self-gated by folding a throughput LOSS into
    # the cost (DS_COST_IN_REWARD).
    try:
        self._last_thru_paxs = float(_thru_paxs)
    except Exception:
        pass
    _ledger = (_eff_bus_w * (bus_pax_saved + mainline_pax_saved + _relief)
               - _eff_cross_w * cross_cost)
    if bool(globals().get('THROUGHPUT_REWARD', False)):
        _wthru = float(globals().get('W_THROUGHPUT', 1.0) or 1.0)
        _wled = float(globals().get('W_DELAY_LEDGER', 0.0) or 0.0)
        reward = _wthru * _thru_paxs + _wled * _ledger
    else:
        if bool(globals().get('DS_COST_IN_REWARD', False)) and _thru_paxs < 0.0:
            cross_cost = max(0.0, float(cross_cost)) + (-_thru_paxs)  # throughput loss = cost
            _ledger = (_eff_bus_w * (bus_pax_saved + mainline_pax_saved + _relief)
                       - _eff_cross_w * cross_cost)
        reward = _ledger
    _horizon_penalty = _compute_future_horizon_penalty(
        self, action_type, float(param), cross_cost)
    reward -= _horizon_penalty
    # Side-channel the reward COMPONENTS (non-breaking: the 7-tuple return is
    # unchanged). The multi-head learner reads these to train a separate Q-head
    # per objective (bus-priority vs network-throughput) over its own state.
    try:
        self._last_reward_components = {
            'bus': float(bus_pax_saved + mainline_pax_saved + _relief),
            'cross': float(cross_cost),
            'throughput': float(_thru_paxs),
            'scalar': float(reward)}
    except Exception:
        pass
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


# ── Estimated-state projections (paper: the unbinned Xt is three projections)
# Parity marker for the Aimsun-vs-SUMO audit (check_sumo_parity.py).
# Every decider receives the same estimator tuple, but each may read ONLY its
# own projection: centralised = net-pax tradeoff fields, Nash = fairness
# fields, max-pressure = stability fields. Constructors are pure views over
# entry scalars (the same expressions the deciders already evaluate, plus
# guard-flag defaults), so behaviour is unchanged: downstream code reads the
# same floats, routed through the projection dict.
_XT_PROJECTION_V1 = "tradeoff/fairness/stability projections v1"


def _xt_centralised_projection(self, bus_eta_s, no_act_delay, current_phase):
    """Tradeoff projection of the estimated state for dctsp_centralised.

    Fields the corridor tradeoff needs: ETA reachability against the cycle +
    margin window, the overlap-corrected effective delay, the phase flag, and
    the minimum-delay gate. Corridor bus occupancy (_mb via oncoming_buses)
    is resolved lazily downstream; the projection carries its reach window.
    Deliberately excludes POG, pressures, and densities.
    """
    _overlap = float(globals().get('ZIG_PHASE_OVERLAP_S', 0.0) or 0.0)
    _eff = max(0.0, float(no_act_delay) - _overlap)
    _wp = (int(current_phase) != int(self.BusPhase))
    _cyc = (float(self._signal_cycle_s()) if hasattr(self, '_signal_cycle_s')
            else float(self.config.get('CycleTime', 135.0) or 135.0))
    _mgn = float(globals().get('CENTRALISED_REACH_MARGIN_S', 5.0))
    return {
        'bus_eta_s': float(bus_eta_s),
        'eff_delay': _eff,
        'wrong_phase': _wp,
        'cycle_s': _cyc,
        'margin_s': _mgn,
        'reachable': (float(bus_eta_s) <= _cyc + _mgn),
        'min_delay_s': float(globals().get('CENTRALISED_MIN_BUS_DELAY_S', 5.0)),
    }


def _xt_nash_projection(self, bus_eta_s, no_act_delay, current_phase, veh_id):
    """Fairness projection of the estimated state for dctsp_nash_bargain.

    Carries the monitor flag (continuous vs bus-present game), the raw phase
    flag (the decider applies the monitor override), the min-delay gate, bus
    occupancy with the min-gain gate input, and the threat / measured-state
    switches. Payoffs (bps/cpc) are evaluated downstream; the projection
    holds their gate inputs. Deliberately excludes POG and pressures.
    """
    _overlap = float(globals().get('ZIG_PHASE_OVERLAP_S', 0.0) or 0.0)
    _eff = max(0.0, float(no_act_delay) - _overlap)
    _wp = (int(current_phase) != int(self.BusPhase))
    _mon = (int(veh_id) < 0) or (float(bus_eta_s) > 1.0e8)
    return {
        'bus_eta_s': float(bus_eta_s),
        'eff_delay': _eff,
        'wrong_phase': _wp,
        'monitor': _mon,
        'min_delay_s': float(globals().get('NASH_MIN_BUS_DELAY_S', 5.0)),
        'bus_occ': max(float(getattr(self, 'BusOcc', 40.0) or 40.0), 1.0),
        'min_gain_s': float(globals().get('NASH_MIN_GAIN_S', 5.0)),
        'threat_on': bool(globals().get('NASH_STATE_THREAT', False)),
        'measured_state_on': bool(globals().get('NASH_MEASURED_STATE', False)
                                  or globals().get('MEASURED_QUEUE_FEED', False)),
    }


def _xt_mp_projection(pressures, current_phase, bus_phase):
    """Stability projection of the estimated state for _mp_binary_decision.

    Pure function of the pressure vector plus the phase flag: main/side/total
    pressure and whether the current green serves the main phase. Live counts,
    detector queues, corridor discount, and dwell blocking are all folded into
    the pressures upstream. Deliberately excludes ETA, schedule deviation,
    and POG (no_act_delay is only a <=0 guard, kept at the call site).
    """
    _pm = float(pressures[0]) if len(pressures) > 0 else 0.0
    _ps = float(max(list(pressures[1:]) or [0.0]))
    try:
        _cim = (int(current_phase) == int(bus_phase))
    except Exception:
        _cim = False
    return {
        'p_main': _pm,
        'p_side': _ps,
        'p_tot': _pm + _ps,
        'cur_is_main': _cim,
    }


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
    # Tradeoff projection of the estimated state (parity: _XT_PROJECTION_V1).
    _proj = _xt_centralised_projection(self, bus_eta_s, no_act_delay,
                                       current_phase)
    _bus_occ = max(float(getattr(self, 'BusOcc', 40.0) or 40.0), 1.0)
    eff_delay = _proj['eff_delay']
    wrong_phase = _proj['wrong_phase']
    _cycle_s = _proj['cycle_s']
    _margin = _proj['margin_s']

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
    _min_delay = _proj['min_delay_s']
    _reachable = _proj['reachable']
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
    'OFFSET_PLAN_PUSH': 'OPP',
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
    if str(atype) in ('OFFSET_CORRECTION', 'OFFSET_PLAN_PUSH'):
        return f"{_pfx}_{float(param):+.0f}"
    return f"{_pfx}_{float(param):.0f}"


def parse_action_token(tok) -> tuple:
    """Map any candidate label to (exec_kind, param_s).

    exec_kind is one of {'NO_ACTION','GE','INS','GR','ER','OC','OPP','VP','PT',
    'SEQ','RG'} — the execution branches implemented in engine.py.  INS_POST /
    INS_PRETERM / INS_close all map to 'INS'.  param_s is the trailing number in
    the label (absolute value; sign for OC stays encoded in the label) or None
    when the label carries no number (e.g. 'INS_close').
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
                        ('OPP', 'OPP'),
                        ('VP', 'VP'), ('PT', 'PT'),
                        ('SEQ', 'SEQ'), ('RG', 'RG')):
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
# MULTI-HEAD (2026-10-14): the NETWORK/throughput head's own Q-table, over the
# DS+queue+downstream state (not the bus-centric state). Same {jct:{state:[Q]}}
# shape and per-seed reset as the main head; trained on the analytic net-
# throughput reward component so it conditions on how saturated the network is.
_dctsp_bxt_qnet_table: dict = {}
# {veh_id: (jct_id, atype, aparam, decision_time, state_bin, action_idx)} —
# stored at decision time so a checkout hook can apply the terminal Q-update.
_poz_action_log: dict = {}
# Per-(junction,state) running mean of the realized delay under NO_ACTION.
# Actions are rewarded by their ADVANTAGE vs this baseline, so an action is only
# valued when it realizes LESS total delay than doing nothing typically does in
# that state -- self-baselining, and safe: NO_ACTION stays the reference (Q=0).
_bxt_noaction_baseline: dict = {}   # {(jct, state): [sum_delay, count]}


def _bxt_bin(v: float, edges) -> int:
    """Bin index for value v given 3 ascending edges (0..3)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0
    if x != x:  # NaN -> bin 0, never crash the decider
        return 0
    b = 0
    for e in (edges or []):
        try:
            if x >= float(e):
                b += 1
            else:
                break
        except (TypeError, ValueError):
            break
    return min(max(b, 0), 3)


def _bxt_state_bin(n0_bus: float, side_ratio: float,
                   phase_is_bus: bool, bus_eta_s: float,
                   side_load: float = 0.0, ds_max: float = None,
                    cell_occ=None) -> tuple:
    """Discretise the per-decision state into a hashable state tuple.

    Base 4-tuple = (bus-queue bin, side-RATIO bin, phase-is-bus, eta bin). When
    BXT_DEMAND_STATE is on, a 5th DEMAND-REGIME bin is appended from `side_load`
    (absolute cross-street pax·s of delay) -- an OBSERVED level, not the ratio, so
    ONE policy can condition on how saturated the network is and behave
    differently at low vs high REAL-TIME demand instead of averaging over regimes.
    When DS_IN_LEARNER_STATE is on, a further SCATS degree-of-saturation bin is
    appended from `ds_max` (the worst approach's measured DS this tick) so the
    policy can condition on the SCATS observable directly. Both flag-gated: with
    both off the state stays the original 4-tuple (existing Q-tables / warm-start
    pools keep their shape). Each extra dimension ~3x's the table so it needs
    proportionally more training.

    Edges come from the BXT_STATE_EDGES module flag (same 4 bins per dimension,
    no growth); defaults reproduce the historical hand-tuned edges exactly.
    """
    _ed = globals().get('BXT_STATE_EDGES') or {}
    if not isinstance(_ed, dict):
        _ed = {}
    _e0 = _ed.get('n0_bus', [2.0, 8.0, 20.0])
    _e1 = _ed.get('side_ratio', [0.3, 0.8, 1.5])
    _e3 = _ed.get('bus_eta_s', [5.0, 15.0, 30.0])
    b_b = _bxt_bin(n0_bus, _e0)
    s_b = _bxt_bin(side_ratio, _e1)
    e_b = _bxt_bin(bus_eta_s, _e3)
    _tup = (b_b, s_b, int(phase_is_bus), e_b)
    if bool(globals().get('BXT_DEMAND_STATE', False)):
        _lo = float(globals().get('BXT_DEMAND_BIN_LO_PAXS', 300.0))
        _hi = float(globals().get('BXT_DEMAND_BIN_HI_PAXS', 1500.0))
        if side_load < _lo:   d_b = 0        # light demand regime
        elif side_load < _hi: d_b = 1        # medium
        else:                 d_b = 2        # heavy / saturated
        _tup = _tup + (d_b,)
    # SCATS DS-regime bin (2026-10-14): condition the policy on the worst
    # approach's MEASURED degree of saturation. Edges default to the SCATS
    # operating points (FREE<0.6, SAT 0.6-0.85, OVER 0.85-1.0, JAM>=1.0).
    if bool(globals().get('DS_IN_LEARNER_STATE', False)) and ds_max is not None:
        _dse = globals().get('DS_STATE_EDGES') or [0.6, 0.85, 1.0]
        _tup = _tup + (_bxt_bin(float(ds_max), _dse),)
    # Per-cell occupancy tuple (2026-10-15): spatial detail from the multi-cell
    # CTM. `cell_occ` is a sequence of per-cell occupancy fractions (0..1) for
    # the main approach. Off unless CELLQ_CTM_STATE; keeps existing states stable.
    if bool(globals().get('CELLQ_CTM_STATE', False)) and cell_occ is not None:
        try:
            _n = max(2, int(globals().get('CELLQ_CTM_STATE_CELLS', 4) or 4))
            _src = list(cell_occ)
            if _src:
                _cells = []
                _L = len(_src)
                for _s in range(_n):
                    _a = (_s * _L) // _n
                    _b = max(_a + 1, (((_s + 1) * _L) // _n))
                    _b = min(_b, _L)
                    _sl = _src[_a:_b] if _b > _a else [_src[min(_a, _L - 1)]]
                    _v = (sum(float(x) for x in _sl) / len(_sl)) if _sl else 0.0
                    if _v >= 0.75: _bb = 3
                    elif _v >= 0.5: _bb = 2
                    elif _v >= 0.25: _bb = 1
                    else: _bb = 0
                    _cells.append(_bb)
                _tup = _tup + (tuple(_cells),)
        except Exception:
            pass
    return _tup


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


def _bxt_ext_state(self, time, bus_eta_s):
    """Extended learner-state bins (2026-09-28), flag-gated.

    STATE_INCLUDE_FLOW_QUEUE: + (t-cycle, main-flow, side-flow, main-queue,
    side-queue, bus-present, bus-lateness) -- the OBSERVED network, from the
    live measured feeds.
    STATE_INCLUDE_NEIGHBOUR_TIMING: + one bin per corridor neighbour = the
    relative offset (my bus-green start vs the neighbour's, mod cycle) -- the
    "cycle time between intersections" the policy conditions on, so it learns
    the coordination relationship, not a lone junction.
    STATE_INCLUDE_BUS_COUNT: + (bus-count, bus-share) -- how many buses are
    approaching and what share of the approach demand they are, so a 3-bus
    queue and a 3-car queue (identical in the base state, different optimal
    actions at 40 vs 1.5 pax/veh) map to different states.
    STATE_INCLUDE_SIGNAL_CLOCKS: + (elapsed-green, clearance-status) -- where
    the signal is in its cycle, so dwell-aware policies (don't act with 2 s
    left on min-green) and clearance-aware policies (don't insert
    mid-clearance) are learnable instead of stumbled into via vetoes.
    Returns a tuple of extra bins (empty tuple when all flags off) so the
    base state shape is unchanged for existing Q-tables/warm-start pools.
    """
    _ext = []
    try:
        if bool(globals().get('STATE_INCLUDE_FLOW_QUEUE', False)):
            _bp = int(getattr(self, 'BusPhase', -1) or -1)
            try:
                _cur = int(_eci_call('ECIGetCurrentPhase', self.node_id))
                _cyc = max(float(self._signal_cycle_s(timeSta=0.0)), 1.0)
                _ps = float(_eci_call('ECIGetStartingTimePhase', self.node_id))
                _tcyc = int(round(float(time) - _ps)) % max(int(_cyc), 1)
                _ext.append(0 if _tcyc < _cyc * 0.4 else (1 if _tcyc < _cyc * 0.8 else 2))
            except Exception:
                _ext.append(0)
            _ls = None
            try:
                import shared_tsp_engine.engine as _E
                _st = globals().get('stats', None) or getattr(self, 'stats', None)
                _ls = getattr(_st, 'latest_section', None)
            except Exception:
                _ls = None
            _mf = _sf = _mq = _sq = 0.0
            try:
                _uf = np.asarray(getattr(self, 'UpFlowList', np.zeros(1)),
                                 dtype=float).ravel()
                _pos = _uf[_uf > 0.0]
                _mf = float(np.mean(_pos)) if _pos.size else 0.0
            except Exception:
                pass
            _side_live = []
            try:
                _side = self._get_side_sections() or []
                for _ss in _side:
                    _side_live.append(int(_ss))
                    if _ls is not None:
                        _stt = _ls.get(int(_ss))
                        if _stt:
                            _sf += max(0.0, float(_stt.get('q', 0.0) or 0.0))
                            _sq += max(0.0, float(_stt.get('queue_veh', 0.0) or 0.0))
            except Exception:
                pass
            # PHYSICAL-COUNT fallback when the measured side feed is stale/empty.
            if (_sq <= 0.0 and _side_live
                    and bool(globals().get('STATE_QUEUE_PHYSICAL_FIRST', True))):
                for _ss in _side_live:
                    try:
                        _sq += max(0, int(_eci_call('AKIVehStateGetNbVehiclesSection', _ss, False) or 0))
                    except Exception:
                        pass
            # Main queue: PHYSICAL stopped/queued count first (same source the
            # reward floor uses); fall back to the analytic MaxQueueLength model.
            _mainq = None
            try:
                if (bool(globals().get('STATE_QUEUE_PHYSICAL_FIRST', True))
                        and hasattr(self, '_measured_main_queue_veh')):
                    _mainq = self._measured_main_queue_veh()
            except Exception:
                _mainq = None
            if _mainq is None:
                try:
                    _mainq = float(getattr(self, 'MaxQueueLength', [[0.0]])[0][0] or 0.0)
                except Exception:
                    _mainq = 0.0
            else:
                _mainq = max(0.0, float(_mainq))
            _ext.append(0 if _mf < 300 else (1 if _mf < 900 else 2))
            _ext.append(0 if _sf < 150 else (1 if _sf < 600 else 2))
            _ext.append(0 if _mainq < 2 else (1 if _mainq < 6 else 2))
            _ext.append(0 if _sq < 2 else (1 if _sq < 6 else 2))
            _ext.append(1 if (bus_eta_s is not None and float(bus_eta_s) < 1.0e8) else 0)
            try:
                _late = float(_E._bus_lateness.get(int(self.id) and 0, 0.0) or 0.0)
            except Exception:
                _late = 0.0
            try:
                _b = int(getattr(self, '_cur_decision_veh', -1) or -1)
                if _b > 0:
                    _late = float(_E._bus_lateness.get(_b, 0.0) or 0.0)
            except Exception:
                pass
            _ext.append(0 if _late < 15 else (1 if _late < 60 else 2))
        if bool(globals().get('STATE_INCLUDE_NEIGHBOUR_TIMING', False)):
            try:
                import shared_tsp_engine.engine as _E
                _cc = getattr(self, '_corridor_coord', None)
                _ps = _E._PLAN_STATE
                _me = int(self.id)
                _ids = []
                if _cc is not None:
                    _ids = [int(j) for j in _cc.inter_ids
                            if j in getattr(_cc, 'corridor_pos', {})]
                if _me in _ids:
                    _ids.sort(key=lambda j: float(
                        _cc.corridor_pos.get(j, 0.0)))
                    _i = _ids.index(_me)
                    _nb = []
                    if _i > 0:
                        _nb.append(_ids[_i - 1])
                    if _i < len(_ids) - 1:
                        _nb.append(_ids[_i + 1])
                    def _bus_start(j):
                        _s = _ps.get(int(j))
                        if not _s:
                            return 0.0
                        _bpj = int(_s.get('bus_phase', -1) or -1)
                        _d = _s.get('durs', {})
                        _acc = 0.0
                        for _ph in sorted(_d, key=lambda p: int(p)):
                            if int(_ph) < _bpj:
                                _acc += float(_d[_ph] or 0.0)
                        return _acc
                    _mystart = _bus_start(_me)
                    for _n in _nb:
                        _off = (_mystart - _bus_start(_n)) % max(
                            _E._global_plan_cycle(_me) or 1.0, 1.0)
                        _ext.append(0 if _off < 0.2 else (1 if _off < 0.5 else 2))
            except Exception:
                pass
        if bool(globals().get('STATE_INCLUDE_BUS_COUNT', False)):
            try:
                import shared_tsp_engine.engine as _E
                _nbus = 0
                try:
                    _cc = getattr(self, '_corridor_coord', None)
                    if _cc is not None and hasattr(_cc, 'oncoming_buses'):
                        _nbus = len(_cc.oncoming_buses(
                            int(self.id), float(time), max_eta_s=180.0) or [])
                except Exception:
                    _nbus = 0
                if _nbus <= 0:
                    try:
                        _nbus = (1 if (bus_eta_s is not None
                                       and float(bus_eta_s) < 1.0e8) else 0)
                    except Exception:
                        _nbus = 0
                _ext.append(0 if _nbus <= 0 else (1 if _nbus == 1 else 2))
                _boc = _coc = 0.0
                try:
                    _occ = _E._bus_occupancy
                    _trk = getattr(_cc, '_trackers', {}) if _cc is not None \
                        else {}
                    for _vid in list(_trk)[:8]:
                        try:
                            _boc += max(float(_occ.get(int(_vid), 40.0)), 1.0)
                        except Exception:
                            _boc += 40.0
                    _mq = float(getattr(self, 'MaxQueueLength', [[0.0]])[0][0]
                                or 0.0)
                    _co = max(float(getattr(self, 'CarOcc', 1.6)
                                    if hasattr(self, 'CarOcc') else 1.6), 1.0)
                    _coc = max(_mq, 0.0) * _co
                except Exception:
                    pass
                _share = (_boc / max(_boc + _coc, 1e-9))
                _ext.append(0 if _share < 0.25 else (1 if _share < 0.6 else 2))
            except Exception:
                pass
        if bool(globals().get('STATE_INCLUDE_SIGNAL_CLOCKS', False)):
            try:
                _cyc = 135.0
                try:
                    _cyc = max(float(self._signal_cycle_s()), 1.0)
                except Exception:
                    pass
                _el = 0.0
                try:
                    _ps = float(_eci_call('ECIGetStartingTimePhase', self.node_id))
                    _el = max(0.0, float(time) - _ps)
                except Exception:
                    _el = 0.0
                _frac = min(_el / max(_cyc, 1.0), 1.0)
                _ext.append(0 if _frac < 0.15 else (1 if _frac < 0.35 else 2))
                # WHICH phase is on (2026-10-03): elapsed fraction alone cannot
                # distinguish phase 1 from phase 3, so identical flow states on
                # different phases collided. Binned 0..3.
                try:
                    _curph = int(_eci_call('ECIGetCurrentPhase', self.node_id))
                except Exception:
                    _curph = 0
                _ext.append(min(max(_curph, 0), 3))
                _clr = 0
                try:
                    _bp = int(getattr(self, 'BusPhase', -1) or -1)
                    _cur = int(_eci_call('ECIGetCurrentPhase', self.node_id))
                    _clr_s = float(globals().get('INS_INTERGREEN_S', 5.0))
                    try:
                        _clr_s = max(float(globals().get(
                            'PLAN_INTERGREEN_S', _clr_s)), 1.0)
                    except Exception:
                        pass
                    if _cur != _bp and _el < _clr_s:
                        _clr = 1
                except Exception:
                    _clr = 0
                _ext.append(int(_clr))
            except Exception:
                pass
    except Exception:
        pass
    return tuple(_ext)


# Per-(junction, state) visit counts (2026-09-30): incremented on every table
# lookup, so pruning / coarse-to-fine / fill diagnostics can distinguish
# visited-once from visited-100x without changing table shape. Keyed exactly
# like the Q-table; reset alongside it.
_bxt_visit_count: dict = {}


def _bxt_get_q(jct_id: int, state_bin: tuple, init_vals=None) -> list:
    """Return (and lazily initialise) the BXT Q-value list for (jct, state)."""
    n = len(DCTSP_RL_ACTION_SPACE)
    _qk = _bxt_q_key(jct_id)
    tbl = _dctsp_bxt_q_table.setdefault(_qk, {})
    try:
        _vc = _bxt_visit_count.setdefault(_qk, {})
        _vc[state_bin] = int(_vc.get(state_bin, 0) or 0) + 1
    except Exception:
        pass
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


def _bxt_net_family(_atype):
    """Action family for the multi-head network head:
       PRIORITY  = hold/gREEN-extend family (bus-phase retention)
       THROUGHPUT = interstitial insertion / reallocation / early red family."""
    _at = str(_atype or "").upper()
    if _at in ("NO_ACTION", "GE"):
        return "PRIORITY"
    return "THROUGHPUT"

def _bxt_family_index(_state_bin, _family):
    if bool(globals().get("MULTIHEAD_ACTION_FAMILY", False)):
        return _state_bin + (_family,)
    return _state_bin

def _bxt_get_qnet(jct_id, state_bin, family="THROUGHPUT"):
    """Network/throughput head Q-values for (jct, net_state). Lazy zero-init; no
    warm-start pool / optimistic prior (those encode bus-phase semantics the net
    head does not share). When MULTIHEAD_ACTION_FAMILY is on, entries are split
    by action family so the two heads can influence decisions differently
    instead of collapsing to one shared argmax."""
    n = len(DCTSP_RL_ACTION_SPACE)
    _f = str(family or "THROUGHPUT").upper()
    tbl = _dctsp_bxt_qnet_table.setdefault(int(jct_id), {}).setdefault(_f, {})
    _sb = _bxt_family_index(state_bin, _f)
    if _sb not in tbl:
        tbl[_sb] = [0.0] * n
    return tbl[_sb]


def _bxt_update_qnet(jct_id, state_bin, action_idx, r_net, family="THROUGHPUT"):
    """Contextual-bandit update for the network head: Q(s,a) += alpha*(r - Q)."""
    try:
        _f = str(family or "THROUGHPUT").upper()
        q = _bxt_get_qnet(jct_id, state_bin, _f)
        q[int(action_idx)] += float(globals().get('BXT_ALPHA', 0.2) or 0.2) * (
            float(r_net) - q[int(action_idx)])
    except Exception as _e:
        log_to_file(f"[MULTIHEAD-NET-UPDATE-FAIL] jct={jct_id} e={_e!r}",
                    force=True)


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


def _eci_call(name, *args):
    """Resolve and call an ECI/AAPI function from specialized_modes.

    engine.py binds the corridor's ECI names into ITS OWN globals (bind_config),
    but specialized_modes is a separate module and never receives them: a bare
    `ECIGetCurrentPhase(...)` / `AKIVehStateGetNbVehiclesSection(...)` here raised
    NameError, which the surrounding try/except silently swallowed. That zeroed
    every state dim needing the API (time-in-phase, neighbour green) and collapsed
    `_mp_pressures_for_junction` onto its MaxQueueLength fallback -- the same array
    for every phase -- so the main-vs-side split vanished (observed: the CELLQ cell
    state's (cur, cross) bins were equal in every decision). Resolve the callable
    through the shared engine module's namespace instead. Raises NameError when
    nothing resolves, so callers keep their explicit fallbacks.
    """
    import sys as _s
    for _mod in (_s.modules.get('shared_tsp_engine.engine'),
                 _s.modules.get('specialized_modes')):
        if _mod is None:
            continue
        _f = getattr(_mod, name, None)
        if callable(_f):
            try:
                return _f(*args)
            except Exception:
                continue
    raise NameError(name)


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
        # Fallback: this controller's OWN coordinator handle. An UNCOORDINATED
        # arm (coordinated=False) still carries a network-level coordinator, but
        # the global list lookup above can miss it; read the per-controller
        # handle so corridor-neighbour state is available to every arm.
        _cc = getattr(self, '_corridor_coord', None)
        if _cc is not None:
            for _attr in ('route_inter_ids', 'inter_ids'):
                _ids = [int(i) for i in (getattr(_cc, _attr, None) or [])]
                if _ids:
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
    _freeze = bool(globals().get('BXT_FREEZE_ON_EVAL', False))
    if _eval and _freeze and not _diag:
        return                      # legacy frozen-policy mode -> no Q update
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


# Junctions already demand-warmed this learning episode (2026-09-30): keyed
# exactly like the Q-table so reset_bxt_learning (which clears tables per
# seed) re-arms warming automatically. Warming is demand-based, not
# seed-based, so it correctly re-runs every episode.
_bxt_demand_warmed: set = set()


def _bxt_demand_warmstart(self) -> bool:
    """Offline model-based warm-start from the known demand distribution.

    Populates this junction's WHOLE base table (128 states x |A| actions)
    from analytic CTM rollouts before its first real decision, so the greedy
    policy acts sensibly from step one instead of waiting for training to
    visit each state. Returns True when warming ran, False when skipped
    (already warmed) -- never raises; failures fall back to existing init.

    Method: exhaustive over states (bin centers from BXT_STATE_EDGES, so it
    respects calibration), stochastic over demand (K scenarios stratified
    across light/medium/saturated regimes). Per (state, action): analytic bus
    delay via _ctm_red_delay + uniform cross-traffic delay, advantage vs
    NO_ACTION averaged over scenarios, written as init values (same semantics
    as the optimistic-init precedent: real TD updates overwrite at rate
    ALPHA, so model bias washes where data arrives and persists only where
    data never comes -- exactly where any prior beats zero).

    Pure arithmetic (~128 x |A| x K CTM calls, milliseconds). Only
    runs when BXT_DEMAND_WARMSTART is on; a single bool check otherwise.
    """
    try:
        if not bool(globals().get('BXT_DEMAND_WARMSTART', False)):
            return False
    except Exception:
        return False
    try:
        _qk = _bxt_q_key(int(getattr(self, 'id', -1) or -1))
    except Exception:
        return False
    try:
        if _qk in _bxt_demand_warmed:
            return False
    except Exception:
        return False
    try:
        import random as _rnd_ws
    except Exception:
        return False
    try:
        _K = max(1, int(globals().get('BXT_WARMSTART_SCENARIOS', 12) or 12))
        _sat_frac = float(globals().get('BXT_WARMSTART_SAT_FRAC', 0.4) or 0.0)
        _sat_frac = min(max(_sat_frac, 0.0), 1.0)
        _q_sat = max(float(getattr(self, 'SaturationFlow', 1800.0)
                           or 1800.0) / 3600.0, 1e-6)
        try:
            _cyc = max(float(self._signal_cycle_s()), 20.0)
        except Exception:
            _cyc = 135.0
        _g0 = max(float(getattr(self, 'BusPhaseDuration', 20.0) or 20.0), 5.0)
        _red0 = max(_cyc - _g0, 5.0)
        _bocc = max(float(getattr(self, 'BusOcc', 40.0) or 40.0), 1.0)
        try:
            _cocc = max(float(getattr(self, 'CarOcc', 1.6)
                              if hasattr(self, 'CarOcc') else 1.6), 1.0)
        except Exception:
            _cocc = 1.6
        try:
            _base_q = float(np.mean(np.asarray(
                getattr(self, 'UpFlowList', np.zeros(1)),
                dtype=float).ravel())) / 3600.0
            if not (_base_q > 0.0):
                _base_q = 300.0 / 3600.0
        except Exception:
            _base_q = 300.0 / 3600.0
        try:
            _acts = list(DCTSP_RL_ACTION_SPACE)
        except Exception:
            return False
        if not _acts:
            return False
        try:
            _ed = globals().get('BXT_STATE_EDGES') or {}
            if not isinstance(_ed, dict):
                _ed = {}
        except Exception:
            _ed = {}

        def _centers(edges, lo, hi):
            try:
                _e = [float(x) for x in (edges or [])]
            except Exception:
                _e = []
            if len(_e) < 3:
                return [lo, (lo + hi) / 2.0, hi, hi * 1.5]
            return [max(_e[0] / 2.0, lo), (_e[0] + _e[1]) / 2.0,
                    (_e[1] + _e[2]) / 2.0, _e[2] * 1.5]

        _n0c = _centers(_ed.get('n0_bus'), 0.0, 25.0)
        _src = _centers(_ed.get('side_ratio'), 0.0, 2.0)
        _rnd = _rnd_ws.Random(12345 + abs(int(_qk)) % 100000)
        # Self-contained CTM cell recursion for the warm-start (mirrors the
        # nested _ctm_red_delay used by the live decider, which is not
        # module-accessible: red -> green -> RED-AGAIN over the cycle, residual
        # persists and keeps accruing). Kept local so offline warming never
        # depends on live controller state; dt=1.0 matches the decider.
        _ws_cap = max(200.0 * 0.15, 1.0)

        def _ws_ctm(_n0, _qa, _qs, _tw, _gd, _oc):
            _d = 0.0
            _n = max(0.0, float(_n0))
            for _ in range(max(0, int(round(float(_tw))))):
                _n = min(_n + _qa, _ws_cap)
                _d += _n
            for _ in range(max(0, int(round(float(_gd))))):
                _qo = min(_qs, _n)
                _n = max(0.0, _n + _qa - _qo)
            _bal = max(0.0, _cyc - float(_tw) - float(_gd))
            for _ in range(max(0, int(round(_bal)))):
                _n = min(_n + _qa, _ws_cap)
                _d += _n
            return _d * float(_oc)

        _acc = {}
        for _bi in range(4):
            for _si in range(4):
                for _pi in range(2):
                    for _ei in range(4):
                        _st = (_bi, _si, _pi, _ei)
                        _n0b = max(_n0c[_bi], 0.0)
                        for _k in range(_K):
                            _r = _rnd.random()
                            if _r < _sat_frac:
                                _lvl = _rnd.uniform(1.2, 1.6)
                            else:
                                _lvl = _rnd.uniform(0.5, 1.1)
                            _qarr = max(_base_q * _lvl, 1e-6)
                            _n0 = max(_n0b * (0.7 + 0.6 * _rnd.random())
                                      * (0.5 + _lvl), 0.0)
                            _tw = max(_rnd.uniform(0.0, _red0)
                                      * (0.5 + 0.5 * _lvl), 0.0)
                            _sq = max(_src[_si] * 8.0 * _lvl, 0.0)
                            try:
                                _na_b = float(_ws_ctm(
                                    _n0, _qarr, _q_sat, _tw, _g0, _bocc))
                            except Exception:
                                continue
                            _na_c = max(_sq, 0.0) * max(_tw, 0.0) * _cocc
                            _na = _na_b + _na_c
                            for _ai, (_at, _ap) in enumerate(_acts):
                                try:
                                    _d = max(float(_ap or 0.0), 0.0)
                                except Exception:
                                    _d = 0.0
                                if _at == 'NO_ACTION' or _d <= 0.0:
                                    _ad = _na
                                elif _at in ('GE', 'GREEN_REALLOC'):
                                    try:
                                        _gb = float(_ws_ctm(
                                            _n0, _qarr, _q_sat, _tw,
                                            _g0 + _d, _bocc))
                                    except Exception:
                                        _gb = _na_b
                                    _gc = max(_sq, 0.0) * max(
                                        _tw + _d / 2.0, 0.0) * _cocc
                                    _ad = _gb + _gc
                                elif _at in ('INS', 'EARLY_RED'):
                                    _tw2 = max(_tw - _d, 0.0)
                                    try:
                                        _gb = float(_ws_ctm(
                                            _n0, _qarr, _q_sat, _tw2,
                                            _g0, _bocc))
                                    except Exception:
                                        _gb = _na_b
                                    _gc = max(_sq, 0.0) * max(
                                        _tw2 + _d / 2.0, 0.0) * _cocc
                                    _ad = _gb + _gc
                                else:
                                    _ad = _na
                                _key = (_st, _ai)
                                _s, _n = _acc.get(_key, (0.0, 0))
                                _acc[_key] = (_s + (_na - _ad), _n + 1)
        if not _acc:
            return False
        try:
            _tbl = _dctsp_bxt_q_table.setdefault(_qk, {})
        except Exception:
            return False
        _n = len(_acts)
        for (_st, _ai), (_s, _cnt) in _acc.items():
            if _cnt <= 0:
                continue
            try:
                _qv = _tbl.setdefault(_st, [0.0] * _n)
                if len(_qv) == _n:
                    _qv[_ai] = float(_s) / float(_cnt)
            except Exception:
                continue
        try:
            _bxt_demand_warmed.add(_qk)
        except Exception:
            pass
        return True
    except Exception:
        return False



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

    # Demand warm-start (2026-09-30): populate this junction's table from
    # offline analytic rollouts before its first real decision, once per
    # learning episode. No-op unless BXT_DEMAND_WARMSTART is on.
    if bool(globals().get('BXT_DEMAND_WARMSTART', False)):
        try:
            _bxt_demand_warmstart(self)
        except Exception:
            pass

    # ── POG need gate (offensive POG, 2026-09-30) ─────────────────────────
    # Bus need scales with (1 - POG): a bus arriving on an intact wave needs
    # little help, one facing a broken wave needs a lot. When POG_NEED_GATE
    # is on, the effective minimum bus delay rises as POG rises, so
    # bus-driven evaluations stand down where the wave already serves the bus
    # and concentrate where it does not. Floor prevents an infinite threshold
    # at POG=1. Off by default: identical behavior when disabled.
    if bool(globals().get('POG_NEED_GATE', False)):
        try:
            _need_pog = float(self._progression_pog())
            _need_floor = max(0.05, float(globals().get(
                'POG_NEED_FLOOR', 0.2)))
            _need = max(1.0 - _need_pog, _need_floor)
            _need_min = float(globals().get('POG_NEED_MIN_S', 15.0))
            if float(no_act_delay) * _need < _need_min:
                _r0, _so0, _tp0, _b0, _c0, _n0, _s0 = _dctsp_eval_action(
                    self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
                return ('NO_ACTION', 0.0, 0.0, 0.0, _so0, _tp0,
                        [('NO_ACTION', 0.0, 0.0, _so0, _tp0, _b0, _c0,
                          _n0, _s0)])
        except Exception:
            pass

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
    # GE_UB_CAP_BY_JCT (2026-09-30): {junction_id: seconds} hard cap on the green
    # extension at named intersections. Motivation is the cycle budget, not taste.
    # Green is served per PHASE (SGs in one SignalGroupIDList entry share the
    # interval), so the recoverable slack at i is
    #     slack_i = cycle_i - (sum_phases max_{sg in phase} min_green[sg]
    #                          + intergreen * n_phases)
    # and a grant is only self-financing if it fits inside slack_i. Measured on KG:
    #     39593  slack 15.4 s   39590 slack 18.2 s (9 phases, 12 SGs -> 36 s of a
    #                            135 s cycle is pure intergreen)
    #     39569  slack 20.6 s   36385  26.1 s   39606  30.6 s   36393  51.6 s
    # With GE_extension = 15 s everywhere, a max grant at 39590/39593 consumes
    # 82-97% of the slack, and 39590 is exactly where the run gridlocks
    # (section 21473: 38 -> 102 veh/km, 14.7 -> 6.3 km/h). Capping there buys
    # recovery room without touching the plan.
    try:
        _cap_map = globals().get('GE_UB_CAP_BY_JCT') or {}
        if _cap_map:
            _cap = float(_cap_map.get(int(self.id), 0.0) or 0.0)
            if _cap > 0.0:
                _ge_ub = min(_ge_ub, _cap)
    except Exception:
        pass
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

    def _bxt_pog_bonus(a_s):
        """POG-weighted BENEFIT for green-giving actions (offensive POG).

        Mirrors _bxt_pog_penalty with opposite sign: where the penalty prices
        "don't break the wave", this prices "extend the intact wave". Only
        fires when POG exceeds BXT_POG_BONUS_THRESHOLD (a wave must actually
        exist) and the action gives green (same branches as the penalty).
        Scales with mainline flow x duration x occupancy = the platoon
        passenger-seconds preserved. Off unless BXT_POG_BONUS is set, in which
        case all three penalty branches subtract this symmetrically.
        """
        if not bool(globals().get('BXT_POG_BONUS', False)):
            return 0.0
        if float(a_s) <= 0.0:
            return 0.0
        try:
            _pog = float(self._progression_pog())
            _thr = float(globals().get('BXT_POG_BONUS_THRESHOLD', 0.6))
            if not (_pog > _thr):
                return 0.0
            _uf = np.asarray(getattr(self, 'UpFlowList', np.zeros(1)),
                             dtype=float).ravel()
            _pos = _uf[_uf > 0.0]
            _mf = float(np.mean(_pos)) if _pos.size else 0.0
            if _mf <= 0.0:
                return 0.0
            _occ = max(float(getattr(self, 'CarOcc', 1.6)
                             if hasattr(self, 'CarOcc') else 1.6), 1.0)
            _w = float(globals().get('BXT_POG_BONUS_WEIGHT', 1.0))
            return _w * _pog * (_mf / 3600.0) * float(a_s) * _occ
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
            return -(d_bus + d_side + _bxt_pog_penalty(a_s)
                     - _bxt_pog_bonus(a_s)), d_bus, d_side
        if atype == 'INS':
            t_wait = float(remaining_red_s) + float(INS_INTERGREEN_S)
            d_bus = _ctm_red_delay(n0_bus, q_arr_bus_vps, q_sat_vps, t_wait, a_s, _cell_occ)
            if not (a_s > 0.0 and _raw_deficit <= float(BXT_MAX_INS_S) + 1e-6):
                d_bus += _bus_wait_pax
            d_side = float(self._dctsp_cross_traffic_delay_s(t_wait + a_s))
            return -(d_bus + d_side + _bxt_pog_penalty(a_s)
                     - _bxt_pog_bonus(a_s)), d_bus, d_side
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
            return -(d_bus + d_side + _bxt_pog_penalty(a_s)
                     - _bxt_pog_bonus(a_s)), d_bus, d_side
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
    # `_ds_max` is the SCATS worst-approach degree of saturation, used only when
    # DS_IN_LEARNER_STATE is on (else it is ignored). Measured once per tick.
    _ds_max = None
    if bool(globals().get('DS_IN_LEARNER_STATE', False)):
        try:
            _dssnap = self._approach_ds_snapshot(timeSta)
            if _dssnap:
                _ds_max = float(_dssnap.get('ds_max'))
        except Exception:
            _ds_max = None
    _cell_occ = None
    try:
        _uf = getattr(self, 'UpFlowList', None)
        if _uf is not None:
            _row = (_uf[0] if hasattr(_uf, '__getitem__') else _uf)
            try:
                _vals = [float(x) for x in (_row.tolist() if hasattr(_row, 'tolist') else list(_row))]
            except Exception:
                _vals = []
            if bool(globals().get('CELLQ_CTM_STATE', False)) and _vals:
                _occ = []
                _sat = float(getattr(self, 'SaturationFlow', 1800.0) or 1800.0)
                for _v in _vals:
                    _o = _v / max(_sat, 1e-6)
                    if _o > 1.0:
                        _o = 1.0
                    _occ.append(float(max(0.0, _o)))
                _cell_occ = tuple(_occ)
    except Exception:
        _cell_occ = None
    _bxt_state = _bxt_state_bin(n0_bus, _side_ratio, not _wrong_phase,
                                float(bus_eta_s), side_load=_side_p,
                                ds_max=_ds_max, cell_occ=_cell_occ)
    # Raw-state logging for quantile calibration (2026-09-30): when
    # BXT_LOG_RAW_STATE is on, record the continuous values behind the bins
    # so an offline calibrator can re-cut edges to the observed distribution.
    # One CSV row per decision; off by default (I/O cost).
    try:
        if bool(globals().get('BXT_LOG_RAW_STATE', False)):
            _rl = globals().setdefault('_BXT_RAW_LOG', [])
            _rl.append((int(getattr(self, 'id', -1) or -1),
                        round(float(n0_bus), 3), round(float(_side_ratio), 4),
                        int(bool(not _wrong_phase)),
                        round(float(bus_eta_s), 2)))
            if len(_rl) >= 20000:
                try:
                    import os as _os
                    _lp = globals().get('_BXT_RAW_CSV') or _os.path.join(
                        _os.getcwd(), 'bxt_raw_state.csv')
                    _new = not _os.path.exists(_lp)
                    with open(_lp, 'a', encoding='utf-8') as _lf:
                        if _new:
                            _lf.write("jct,n0_bus,side_ratio,phase_is_bus,"
                                      "bus_eta_s\n")
                        for _row in _rl:
                            _lf.write("%d,%.3f,%.4f,%d,%.2f\n" % _row)
                except Exception:
                    pass
                finally:
                    try:
                        _rl.clear()
                    except Exception:
                        pass
                    globals()['_BXT_RAW_LOG'] = []
    except Exception:
        pass
    # ── Extended state (2026-09-28): append measured flow/queue/time/bus bins
    # and corridor-neighbour offset bins when enabled, so the policy conditions
    # on the network and the inter-junction timing, not just the bus.
    try:
        if bool(globals().get('STATE_INCLUDE_FLOW_QUEUE', False)) or bool(
                globals().get('STATE_INCLUDE_NEIGHBOUR_TIMING', False)):
            _ext = _bxt_ext_state(self, float(time), float(bus_eta_s))
            if _ext:
                _bxt_state = _bxt_state + _ext
    except Exception:
        pass

    # ── epsilon-greedy over the Q-table (initialised from CTM rewards) ───────
    # Phase-aware exploration: train seeds explore (BXT_TRAIN_EPSILON, ~0.1) so
    # the Q-table sees alternatives to learn from; eval seeds are GREEDY (eps=0)
    # so the measured policy is deterministic and leakage-free; default/per-seed
    # uses BXT_EPSILON.
    # BXT_FREEZE_ON_EVAL=False (the default) keeps the Q-table ALIVE on eval
    # seeds, so eps=0 would still learn only on already-chosen actions and the
    # table could never improve on its train-seed state. When the table is live
    # we therefore keep exploring at BXT_TRAIN_EPSILON; eps=0 is reserved for
    # genuine frozen-policy runs.
    _phase = str(globals().get('BXT_PHASE', 'per_seed'))
    _freeze = bool(globals().get('BXT_FREEZE_ON_EVAL', False))
    if _phase == 'eval' and _freeze:
        _eff_eps = 0.0
    elif _phase in ('eval', 'train'):
        _eff_eps = float(globals().get('BXT_TRAIN_EPSILON', 0.1))
    else:
        _eff_eps = float(BXT_EPSILON)
    _use_explore = (_rnd_bxt.random() < _eff_eps)
    # 2026-10-03 EXPLORATION BYPASS: an explored action must actually EXECUTE,
    # otherwise the guard stack converts it to NO_ACTION and the table credits
    # NO_ACTION with the outcome -- the learner can never discover the action's
    # value (root cause of the all-NO_ACTION frozen tables: CELLQLEARN / GATED
    # / SAFE were byte-identical to fixed-time). TRAIN/per-seed phases only;
    # frozen eval never explores so this cannot leak into measured policies.
    _explore_bypass = (_use_explore
                       and bool(globals().get('BXT_EXPLORE_BYPASS', True))
                       and _phase in ('train', 'per_seed'))
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
    # ── MULTI-HEAD mix (2026-10-14): value = Q_bus(bus-state) + w_net·Q_net(net-
    # state). The network head learns the throughput value over the DS+queue+
    # downstream state; its weight is GATED by saturation (idle in free flow,
    # full when the junction is loaded) so priority runs unimpeded when there is
    # spare capacity and throughput protection kicks in exactly when it matters.
    _mh = bool(globals().get('MULTIHEAD_Q', False))
    _net_state = None
    _mix = q_vals
    if _mh:
        try:
            _net_state = self._ds_net_state()
            if _net_state is not None:
                _dsmax_mh = 0.0
                try:
                    _sn = self._approach_ds_snapshot(timeSta)
                    _dsmax_mh = float(_sn.get('ds_max', 0.0)) if _sn else 0.0
                except Exception:
                    _dsmax_mh = 0.0
                _ds0 = float(globals().get('MULTIHEAD_NET_GATE_DSMIN', 0.60) or 0.60)
                _wnet = (0.0 if _dsmax_mh < _ds0
                          else float(globals().get('MULTIHEAD_W_NET', 1.0) or 1.0)
                               * min(1.0, (_dsmax_mh - _ds0) / max(1.0 - _ds0, 0.05)))
                _family_split = bool(globals().get('MULTIHEAD_ACTION_FAMILY', False))
                _mix = list(q_vals)
                for _i, (_atype, _aparam) in enumerate(DCTSP_RL_ACTION_SPACE):
                    _f = _bxt_net_family(_atype)
                    _sb = ((_net_state + (_f,))
                           if _family_split else _net_state)
                    try:
                        _qnet = _bxt_get_qnet(self.id, _sb, _f)
                        _mix[_i] = float(_mix[_i]) + _wnet * float(_qnet[_i])
                    except Exception as _mi:
                        log_to_file(f"[MULTIHEAD-MIX-FAIL] jct={self.id} i={_i} e={_mi!r}",
                                    force=True)
        except Exception:
            _mix = q_vals
    if _use_explore:
        _chosen_idx = _rnd_bxt.choice(_allowed)
    else:
        _chosen_idx = max(_allowed, key=lambda i: _mix[i])
    _chosen_atype, _chosen_aparam = DCTSP_RL_ACTION_SPACE[_chosen_idx]
    # 2026-10-03 EVAL HEURISTIC FALLBACK: a frozen/degenerate table (greedy
    # NO_ACTION everywhere) must not leave a genuinely held bus unserved. If
    # the greedy pick is NO_ACTION while the action families carry no positive
    # Q signal and the bus's TIMING delay exceeds the bound, fall back to the
    # family the timing benefit favours (GE in-phase / INS when held on red).
    # The reach/net-benefit gates below still apply to the fallback.
    if (not _use_explore) and _chosen_atype == 'NO_ACTION' \
            and bool(globals().get('BXT_EVAL_HEURISTIC_FALLBACK', True)):
        try:
            _fb_sig = max(float(q_vals[i]) for i in range(1, len(q_vals)))
        except Exception:
            _fb_sig = 0.0
        try:
            _fb_delay = max(0.0, float(no_act_delay))
        except Exception:
            _fb_delay = 0.0
        _fb_min = max(float(globals().get('BXT_FALLBACK_MIN_BUS_DELAY_S', 15.0)
                            or 0.0),
                      float(SELFORG_MIN_BUS_DELAY_S))
        if _fb_sig <= 0.0 and _fb_delay >= _fb_min:
            _fb_fam = 'GE' if not _wrong_phase else 'INS'
            try:
                _fb_idx = next(i for i, (a, _p) in enumerate(DCTSP_RL_ACTION_SPACE)
                               if a == _fb_fam)
            except StopIteration:
                _fb_idx = None
            if _fb_idx is not None:
                _chosen_idx = int(_fb_idx)
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

    def _main_starve_cost_paxs(_mag):
        return _sm_main_starve_cost_paxs(self, _mag)

    def _starve_adjusted_cost(_mag):
        # Single place the gate reads its cost from: the cross/side ledger plus
        # the opt-in main-starvation surcharge. Both are pax-s, so _accept's
        # break-even / Nash test stays in one currency.
        try:
            _base = _cross_cost_paxs(_mag)
        except Exception:
            _base = 0.0
        try:
            return _base + _main_starve_cost_paxs(_mag)
        except Exception:
            return _base

    # Bargain params + shared accept test at FUNCTION scope so EVERY action branch
    # (GE / bus-phase / OFFSET_CORRECTION) can call _accept. Defining them inside the
    # GE branch raised "cannot access local variable '_accept'" (UnboundLocalError)
    # on the bus-phase / offset branches, which then fell back to NO_ACTION -- the
    # bug the gated/bargain arms hit on non-GE actions (2026-10-02).
    #
    # 2026-10-03 FIX (UnboundLocalError): the bargain config + _accept() were
    # defined INSIDE the GE branch but referenced by the BP/OC branches too, so
    # any INS / wrong-phase-GR / ER pick crashed the decision call (logged as
    # "[BXT] error: cannot access local variable '_bargain'") and silently fell
    # back to NO_ACTION. Define them once, BEFORE the branches.
    _bargain = bool(globals().get('BXT_BARGAIN_DECISION', False))
    _p_T = float(globals().get('BXT_BARGAIN_PT', 0.0))
    _p_C = float(globals().get('BXT_BARGAIN_PC', 1.0))

    def _accept(_benefit, _cost, _occ=None):
        """Shared accept test: hard veto by default, Nash product when on. _occ is
        accepted for call-site compatibility but unused (both sides are already in
        passenger-seconds). See the GE-branch comment for the bargain rationale."""
        if not _bargain:
            return _benefit > _cost
        _surplus = _benefit - _cost
        if _surplus <= 0.0:
            return False
        if _p_T <= 0.0:
            return True                      # utilitarian: min total delay
        try:
            return ((max(0.0, _benefit) ** _p_T)
                    * (_surplus ** _p_C)) >= float(
                        globals().get('BXT_BARGAIN_MIN_N', 0.0))
        except Exception:
            return _benefit > _cost

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
        # BXT_BARGAIN_DECISION (2026-09-30): CellQLearn plays a BARGAINING GAME,
        # not a hard accept/reject. Default OFF, so this changes nothing until it
        # is switched on -- but it is the lever the KG results point at.
        #
        # Why (measured 2026-09-30, seed 400, objective = pax per delay-hour,
        # higher is better):
        #     NO_TSP  0 actions     223.05
        #     UNCOORD 100 actions  203.38   car +19.6%, bus -16.2%
        #     COORD    14 actions  158.44   car +53.1%, bus +10.3% (worse than
        #                                          doing nothing for buses too)
        # Passenger mix is 68.2% car / 28.5% bus, so a 16.2% bus gain needs only a
        # 6.8% car loss to break even. A hard veto on RAW bus-vs-cross pax*s is the
        # wrong currency: it buys bus pax*s at car pax*s prices with no bargaining
        # power, and on a car-dominated corridor that loses almost every time.
        #
        # The Nash arm already solves this: N = (bus_benefit)^pT *
        # (surplus)^pC with pT, pC bargaining powers, so the learner inherits the
        # weighting that makes the Nash family the best-performing one here.
        # With p_T = 0 this reduces exactly to "minimise TOTAL passenger delay".
        # (_bargain / _p_T / _p_C / _accept are now defined at function scope above.)

        # NET-BENEFIT GATE (BXT_NET_BENEFIT_GATE, default OFF): on a car-dominated,
        # already-well-timed corridor the un-gated learner acts net-negative
        # (measured 2026-09-10: car delay +56%, bus delay +13% vs NO_TSP). When
        # enabled, VETO the action unless the bus benefit (from the reliable
        # timing delay `no_act_delay`) exceeds the cross-traffic cost at the
        # SOLVED magnitude -- both already computed above. Keeps TSP from being
        # worse than NO_TSP; compare CELLQLEARN_GATED vs CELLQLEARN.
        _nb_gate = bool(globals().get('BXT_NET_BENEFIT_GATE', False))
        # BUGFIX 2026-10-01: `(not _nb_gate) or _accept(...)` SHORT-CIRCUITED --
        # with BXT_NET_BENEFIT_GATE False (the default) the left side was True, so
        # _accept() was never called and BXT_BARGAIN_DECISION was dead code. The
        # 2026-10-01 ablation proved it: BARGAIN_PT0 / PT1 / GECAP all returned
        # byte-identical rows to the unflagged arm (201.0). Bargaining must switch
        # the accept test ON by itself, not require the legacy gate as well.
        _nb_ok = (not (_nb_gate or _bargain)) or _accept(
            _bus_benefit_total_paxs, _starve_adjusted_cost(_mag))
        if ((_catchable and _mag >= _MIN_EFFECTIVE_GE_S and _nb_ok)
                or _explore_bypass):
            _chosen_aparam = float(max(_mag, _MIN_EFFECTIVE_GE_S))
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
        _nb_ok = (not (_nb_gate or _bargain)) or _accept(
            _bus_benefit_total_paxs, _starve_adjusted_cost(_mag))
        if ((_eta_ok and _mag >= _MIN_EFFECTIVE_GE_S and _nb_ok)
                or _explore_bypass):
            _chosen_aparam = float(max(_mag, _MIN_EFFECTIVE_GE_S))
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
        _nb_ok = (not _nb_gate) or (_bus_benefit_total_paxs > _starve_adjusted_cost(abs(_oc_shift)))
        if abs(_oc_shift) >= _MIN_EFFECTIVE_GE_S and _nb_ok:
            _chosen_aparam = float(_oc_shift)      # signed -> action_label encodes the sign
        else:
            _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif _chosen_atype in _solved_param:
        _chosen_aparam = float(_solved_param[_chosen_atype])

    # ── Family-canonical Q index (2026-09-26) ────────────────────────────────
    # The argmax above chooses an action FAMILY, but the executed magnitude is
    # SOLVED (deficit / DE / harmony / golden -- see _solve_timing_min), so all
    # grid entries of one family execute identically. Crediting the winning
    # GRID index fragmented one behavior across 3 table entries and
    # misattributed outcomes across magnitudes. Re-index to the family's
    # canonical (first grid) entry so choice, execution, economics, and the
    # pending-update credit all agree. ER keeps per-grid indexing (its grid
    # magnitudes execute as indexed); OFFSET_CORRECTION is a single entry.
    if _chosen_atype in _solved_param:
        try:
            _canon = next(i for i, (a, _) in enumerate(DCTSP_RL_ACTION_SPACE)
                          if a == _chosen_atype)
            _chosen_idx = int(_canon)
        except Exception:
            pass

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
    if eff_delay < _bxt_min_delay_s and not _explore_bypass:
        _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif (_chosen_atype in _solved_param
          and _chosen_aparam < _MIN_EFFECTIVE_GE_S and not _explore_bypass):
        # Solved deficit is ~0: the bus already clears without help.  This is
        # the case the fixed grid mispriced -- it granted 15 s to a bus facing
        # no delay.  Grant nothing and pay no cross-traffic cost.
        _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif (not _explore_bypass) and _side_ratio > float(
            BXT_GE_BALANCE_FACTOR if _chosen_atype == 'GE'
            else BXT_BALANCE_FACTOR):
        # 2026-08-24: the CTM-override relaxation here was REVERTED — it did not
        # help (INS never fired; GE gridlocked) because the CTM over-values GE.
        _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif _chosen_atype == 'INS' and _chosen_aparam > float(BXT_MAX_INS_S):
        # Clamp the disruptive insertion instead of committing the full
        # 15-20 s candidate (mode-commits-own-action bypasses BP_upper_bound).
        _chosen_aparam = float(BXT_MAX_INS_S)

    # Absolute main-approach saturation veto (2026-10-08). The ratio-based side
    # veto below can never fire when the bus is also held up (the seed-600 failure:
    # side/bus ratio stays small while BOTH approaches gridlock). When the LOCAL
    # corridor is already saturated, extending the bus green cannot discharge more
    # main demand and only starves cross streets -> refuse.
    try:
        _kj = max(float(getattr(self, 'JamDensity', 150.0)) or 150.0, 1.0)
        _ds = []
        for _row in (getattr(self, 'UpDenList', []) or []):
            try:
                for _v in _row:
                    _ds.append(float(_v))
            except TypeError:
                _ds.append(float(_row))
        _local_sat = max(_ds) / _kj if _ds else 0.0
    except Exception:
        _local_sat = 0.0
    _sat_veto = float(globals().get('CELLQLEARN_SAT_VETO', 0.85) or 0.85)
    if (_local_sat > _sat_veto and not _explore_bypass
            and _chosen_atype != 'NO_ACTION'):
        _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0

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
    _freeze = bool(globals().get('BXT_FREEZE_ON_EVAL', False))
    _log_ok = (_phase != 'eval') or _diag or (not _freeze)
    if globals().get('BXT_LEARN', True) and _log_ok:
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

    # ── MULTI-HEAD: train the network head on the CHOSEN action's analytic net
    # throughput (pax·s), over the DS+queue+downstream state it was keyed on. The
    # throughput is analytic and available now, so a contextual-bandit update is
    # applied immediately (no deferral). NO_ACTION has zero throughput delta.
    if _mh and _net_state is not None and globals().get('BXT_LEARN', True):
        try:
            if _chosen_atype == 'NO_ACTION':
                _r_net = 0.0
            else:
                _dctsp_eval_action(self, _chosen_atype, float(_chosen_aparam),
                                   sigma_in, no_act_delay, bus_eta_s,
                                   remaining_red_s=remaining_red_s)
                try:
                    _fb = float(getattr(self, '_last_thru_paxs', 0.0) or 0.0)
                except Exception:
                    _fb = 0.0
                _r_net = float((getattr(self, '_last_reward_components', {})
                                or {}).get('throughput', _fb) or _fb)
            try:
                _f_train = _bxt_net_family(getattr(DCTSP_RL_ACTION_SPACE[int(_chosen_idx)],
                                             0, 'NO_ACTION'))
            except Exception:
                _f_train = 'THROUGHPUT'
            _bxt_update_qnet(self.id, _net_state, int(_chosen_idx), _r_net, _f_train)
        except Exception:
            pass
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


def _valid_cpdql_actions(phase_is_bus: bool) -> list:
    """Return list of (action_idx, action_type, param) that are admissible
    given the current phase state, matching the guard-set at lines 4354-4365."""
    _valid = []
    for _i, (_at, _ap) in enumerate(CPDQL_ACTION_SPACE):
        if _at == 'NO_ACTION':
            _valid.append((_i, _at, _ap))
        elif _at == 'GE' and phase_is_bus:
            _valid.append((_i, _at, _ap))
        elif _at == 'INS' and not phase_is_bus:
            _valid.append((_i, _at, _ap))
    if len(_valid) <= 1:
        _valid = [(0, 'NO_ACTION', 0.0)]
    return _valid


def _cpdql_update_q(jct_id: int, state_bin: tuple, action_idx: int,
                    reward: float, next_state=None, next_phase_is_bus: bool = None) -> float:
    """TD(0) update: Q(s,a) += alpha*[r + gamma*max_a' Q(s',a') - Q(s,a)].

    `next_state` is the junction's NEXT decision state (or None = terminus).
    `next_phase_is_bus` filters the bootstrap to only admissible actions
    in the next decision epoch (guard-set awareness).
    Returns the TD error."""
    q_cur = _cpdql_get_q(jct_id, state_bin)
    _boot = 0.0
    if next_state is not None and float(CPDQL_GAMMA) > 0.0:
        q_nxt = _cpdql_get_q(jct_id, next_state)
        # Enhanced: only bootstrap over admissible actions in the next epoch
        if next_phase_is_bus is not None:
            _valid = _valid_cpdql_actions(next_phase_is_bus)
            _q_admissible = [q_nxt[_i] for _i, _, _ in _valid]
            _boot = float(CPDQL_GAMMA) * max(_q_admissible) if _q_admissible else 0.0
        else:
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
                    _next_pib = _next_st[3] if _next_st is not None else None
                    _cpdql_update_q(int(self.id), _st,
                                    int(_rec['action_idx']), _reward,
                                    next_state=_next_st,
                                    next_phase_is_bus=_next_pib)
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
    # 2026-10-09 FIX (NameError: name '_bargain' is not defined): this decider
    # referenced the BXT bargain config (_bargain / _p_T / _p_C) which is defined
    # at FUNCTION scope only in dctsp_bxt, never here. The NET-BENEFIT veto below
    # therefore raised NameError on EVERY chosen BARGAIN action and the decision
    # silently fell back to NO_ACTION (the "[BARGAIN] ... not defined" the user
    # saw). Define them in this scope, mirroring dctsp_bxt (defaults: veto mode).
    _bargain = bool(globals().get('BXT_BARGAIN_DECISION', False))
    _p_T = float(globals().get('BXT_BARGAIN_PT', 0.0))
    _p_C = float(globals().get('BXT_BARGAIN_PC', 1.0))
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
        # rather than a raw benefit>cost veto, so it plays the bargaining game
        # instead of trading bus pax*s for car pax*s at par. p_T=0 reduces exactly
        # to minimising total passenger delay. See _accept() above for the KG
        # numbers that motivate this.
        if _bargain:
            _sur = _bus_benefit_total - float(best_cpc)
            _n_val = 0.0 if _sur <= 0.0 else (
                _sur if _p_T <= 0.0
                else (max(0.0, _bus_benefit_total) ** _p_T) * (_sur ** _p_C))
            _n_ok = _sur > 0.0 and _n_val >= float(
                globals().get('BXT_BARGAIN_MIN_N', 0.0))
        else:
            _n_ok = _bus_benefit_total > float(best_cpc)
        if not _n_ok:
            _log_func(self, f"[BARGAIN] inter={self.id} NET-BENEFIT VETO "
                            f"benefit={_bus_benefit_total:.0f} cpc={best_cpc:.0f}"
                            + (f" N={_n_val:.1f} pT={_p_T:.2f}" if _bargain else "")
                            + " -> NO_ACTION")
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


def _nash_bargain_pick(frontier, p_T=1.0, p_C=1.0, eps=1e-6, threat=0.0):
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
    d_T = max(0.0, float(threat))         # transit-side disagreement (threat) point
    # NASH_NET_GATE_RATIO (2026-10-17): require the transit benefit to clear the
    # cross cost by this MARGIN before an action is eligible to be bargained at all
    # (bps > ratio * cpc). Default 1.0 reproduces the original individual-rationality
    # test (bps > cpc) exactly -- existing results unchanged. Higher values act as a
    # risk-adjusted gate: the cross-street cost `cpc` is a DETECTOR-ESTIMATED lower
    # bound (same finding as CAR_COST_UNCERTAINTY_K on the analytic veto), so a
    # ratio>1 demands the margin the estimate is missing. Measured motivation: the
    # NASH family ran +17% total corridor delay / +13.4% avg passenger delay vs NO_TSP
    # with ratio 1.0, i.e. it accepted transfers whose real cross cost exceeded the
    # estimate.
    _net_ratio = float(globals().get('NASH_NET_GATE_RATIO', 1.0) or 1.0)
    best_i, best_N = None, 0.0
    for i, (bps, cpc) in enumerate(frontier):
        bps = float(bps); cpc = float(cpc)
        surplus = bps - cpc               # net corridor pax·s (>0 to bargain)
        gain_T = bps - d_T                # transit GAIN OVER THREAT (not over 0)
        # individual rationality is now vs the (state-dependent) threat, not a bare
        # 0: on a congested corridor d_T rises, so a small bus gain no longer looks
        # like a bargain against a good NO_ACTION outcome (the fix the fixed
        # MIN_GAIN gate was doing crudely). d_T=0 -> identical to the old form.
        if gain_T <= eps or surplus <= eps or bps < _net_ratio * cpc:
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
            N = (gain_T ** float(p_T)) * (surplus ** float(p_C))
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
    # NASH_THRU_SURPLUS (2026-10-16): bargain on THROUGHPUT (net passengers
    # discharged per cycle) instead of DELAY. `_dctsp_eval_action`'s tp slot is a
    # dead field (always 0.0), so the throughput term is computed HERE from
    # `_net_pax_throughput_delta` -- the same net-throughput objective already wired
    # into the reward behind THROUGHPUT_REWARD. It already nets the served-phase
    # discharge gain, the cross-phase loss and the switching loss, so it IS the
    # surplus; the bargaining powers have no separate transit/cross split to weight.
    _thru_on = bool(globals().get('NASH_THRU_SURPLUS', False))
    _sp = -1
    _ts = 0.0
    if _thru_on:
        try:
            _sp = int(_eci_call('ECIGetCurrentPhase', 
                int(getattr(self, 'node_id', 0) or 0) or int(self.id)))
        except Exception:
            _sp = -1
        try:
            _ts = float(_eci_call('AKIGetCurrentSimulationTime', ))
        except Exception:
            _ts = 0.0

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
            _thru = None
            if _thru_on:
                try:
                    _thru = float(self._net_pax_throughput_delta(
                        atype, float(d), _sp, _ts) or 0.0)
                except Exception:
                    _thru = None
            _cache[d] = (max(0.0, float(bps)), max(0.0, float(cpc)), so, tp, _thru)
            _rows.append((atype, float(d), _cache[d][2], _cache[d][3],
                          _cache[d][0], _cache[d][1]))
        except Exception:
            _cache[d] = None
        return _cache[d]

    def _score(v):
        if not v:
            return -1.0
        bps, cpc = v[0], v[1]
        if _thru_on:
            R = v[4] if len(v) > 4 else None
            if R is None:
                return -1.0
            return (R ** float(p_C)) if R > 0.0 else 0.0
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


def _cellq_state_diag(self, time, st, pres, sat_v, tip_el, ngh_sat_v, ngh_green):
    """[CELLQ_STATE] one line per decision: the RAW inputs behind the 7-bin cell
    state. Without it a dead dim (e.g. always-0 time-in-phase or neighbour green)
    silently collapses the state space and the Q-learner looks merely "bad".
    Silence with CELLQ_STATE_DIAG=False (module default True)."""
    try:
        if not bool(globals().get('CELLQ_STATE_DIAG', True)):
            return
        _log_func(self,
                  f"[CELLQ_STATE] inter={getattr(self, 'id', '?')} "
                  f"t={float(time):.1f} st={tuple(st)} "
                  f"pres={[round(float(p), 1) for p in (pres or [])]} "
                  f"sat={float(sat_v):.3f} tip_el={float(tip_el):.1f} "
                  f"ngh_sat={float(ngh_sat_v):.3f} ngh_green={int(ngh_green)}")
    except Exception:
        pass


def _cellq_corridor_state(self, time, current_phase, no_act_delay):
    """Dense CTM-cell state for BXT_CORRIDOR_MODE, observable EVERY tick (no bus-
    absence degeneracy): (cur_cell, cross_cell, downstream_sat, time_in_phase,
    bus_urgency). cur/cross from the pax-weighted phase pressures; downstream_sat
    from the CTM density lists; bus_urgency is a SINGLE bin (0 when no bus) so a
    missing bus no longer zeroes 3 of 4 state dims."""
    try:
        _pres = _mp_pressures_for_junction(self, time, current_phase)
    except Exception:
        _pres = []
    _pm = float(_pres[0]) if _pres else 0.0
    _psd = float(max(list(_pres[1:]) or [0.0]))
    try:
        _cur_is_main = (int(current_phase) == int(getattr(self, 'BusPhase', -1)))
    except Exception:
        _cur_is_main = False
    _cur = _pm if _cur_is_main else _psd
    _cross = _psd if _cur_is_main else _pm

    def _b3(x, a, b):
        return 0 if x < a else (1 if x < b else 2)

    _sat = 0.0
    try:
        _kj = max(float(getattr(self, 'JamDensity', 150.0)) or 150.0, 1.0)
        _ds = []
        for _row in (getattr(self, 'UpDenList', []) or []):
            try:
                for _v in _row:
                    _ds.append(float(_v))
            except TypeError:
                _ds.append(float(_row))
        for _v in (getattr(self, 'SideUpDenList', []) or []):
            _ds.append(float(_v))
        if _ds:
            _sat = max(0.0, max(_ds) / _kj)
    except Exception:
        pass
    # Fallback (2026-10-19): the density lists are empty/zero at some decision
    # ticks, which pinned the saturation dim at 0 in EVERY observed decision and
    # collapsed the state. Fall back to the MEASURED main standing queue so the
    # dim is live whenever there is queue to reason about.
    if _sat <= 0.0:
        try:
            _mq = self._measured_main_queue_veh()
            if _mq is not None and float(_mq) > 0.0:
                _sat = min(1.0, float(_mq) / 20.0)   # 20 veh ~= saturated main queue
        except Exception:
            pass
    _tip = 0
    _el = -1.0
    try:
        _pst = float(_eci_call('ECIGetStartingTimePhase', self.node_id))
        _el = max(0.0, float(time) - _pst)
        _mg = float((getattr(self, 'config', {}) or {}).get('MinGreen', 5.0) or 5.0)
        _tip = 0 if _el < _mg else (1 if _el < 2.0 * _mg else 2)
    except Exception:
        pass
    try:
        _d = float(no_act_delay or 0.0)
    except Exception:
        _d = 0.0
    _bu = 0 if _d < 1.0 else (1 if _d < 15.0 else 2)

    # ── NEIGHBOUR STATE (2026-10-05, CELLQ_STATE_NEIGHBOUR default True) ──────────
    # Corridor coordination needs the policy to CONDITION on the ADJACENT junctions'
    # state, not just this one -- the most important part. Add two bins describing
    # the corridor neighbours:
    #   ngh_sat  (0/1/2): worst neighbour upstream/side saturation (density/jam) ->
    #                     downstream spillback risk; don't shove a platoon into a
    #                     saturated neighbour.
    #   ngh_green (0/1):  is ANY corridor neighbour currently serving its MAIN
    #                     (through/bus) phase -> a green-wave window is open downstream.
    if bool(globals().get('CELLQ_STATE_NEIGHBOUR', True)):
        _ngh_sat_v = 0.0
        _ngh_green = 0
        try:
            import sys as _sysn
            _engn = _sysn.modules.get('shared_tsp_engine.engine')
            _ctrls = getattr(_engn, 'controllers', {}) or {}
            for _nid in _bxt_neighbor_jcts(self):
                _nc = _ctrls.get(int(_nid))
                if _nc is None:
                    continue
                # neighbour saturation, computed the SAME way as the local _sat
                try:
                    _nkj = max(float(getattr(_nc, 'JamDensity', 150.0)) or 150.0, 1.0)
                    _nds = []
                    for _row in (getattr(_nc, 'UpDenList', []) or []):
                        try:
                            for _v in _row:
                                _nds.append(float(_v))
                        except TypeError:
                            _nds.append(float(_row))
                    for _v in (getattr(_nc, 'SideUpDenList', []) or []):
                        _nds.append(float(_v))
                    if _nds:
                        _ngh_sat_v = max(_ngh_sat_v, max(_nds) / _nkj)
                except Exception:
                    pass
                # neighbour currently green on its MAIN (through/bus) phase?
                try:
                    if int(_eci_call('ECIGetCurrentPhase', _nc.node_id)) == int(getattr(_nc, 'BusPhase', -1)):
                        _ngh_green = 1
                except Exception:
                    pass
        except Exception:
            pass
        _ngh_sat = 0 if _ngh_sat_v < 0.5 else (1 if _ngh_sat_v < 0.85 else 2)
        _st = (_b3(_cur, 5.0, 30.0), _b3(_cross, 5.0, 30.0),
               (0 if _sat < 0.5 else (1 if _sat < 0.85 else 2)), _tip, _bu,
               _ngh_sat, _ngh_green)
        _cellq_state_diag(self, time, _st, _pres, _sat, _el, _ngh_sat_v, _ngh_green)
        return _st

    _st = (_b3(_cur, 5.0, 30.0), _b3(_cross, 5.0, 30.0),
           (0 if _sat < 0.5 else (1 if _sat < 0.85 else 2)), _tip, _bu)
    _cellq_state_diag(self, time, _st, _pres, _sat, _el, -1.0, -1)
    return _st


def _solve_ge_durations(self, bus_eta_s, rem_green, veh_id):
    """SOLVE the green-extension magnitude(s) instead of scanning a fixed grid.
    The GE_DURATIONS_S grid is used only as the [min,max] envelope (a signal's
    realistic min/max extra green); the actual value is solved closed-form:
      (1) BUS serve: the exact green to cover the tracked bus's arrival =
          bus_eta_s - remaining_green (+0.5 s margin) -- the smallest extension
          that serves the bus, so no seconds are wasted stealing cross green.
      (2) DEMAND clear: the green to discharge the MEASURED main queue at
          saturation (Q_main / sat_flow) -- for bus-free / demand action.
    Both clamped to [lo,hi]. Falls back to the grid when nothing solves. A
    closed-form solve is exact for this 1-D magnitude (no DE search needed)."""
    _grid = [float(x) for x in (globals().get('GE_DURATIONS_S') or [5.0, 10.0, 15.0])]
    _lo, _hi = (min(_grid), max(_grid)) if _grid else (5.0, 15.0)
    _cands = []
    try:
        if int(veh_id) >= 0 and rem_green is not None:
            _miss = float(bus_eta_s) - float(rem_green)
            if _miss > 0.0:
                _cands.append(min(max(_miss + 0.5, _lo), _hi))   # solved bus-serve
    except Exception:
        pass
    try:
        _mq = (self._measured_main_queue_veh()
               if hasattr(self, '_measured_main_queue_veh') else None)
        if _mq is not None and float(_mq) > 0.0:
            _sf = max(float(getattr(self, 'SaturationFlow', 1800.0) or 1800.0)
                      / 3600.0, 0.1)
            _cands.append(min(max(float(_mq) / _sf, _lo), _hi))  # solved demand-clear
    except Exception:
        pass
    _cands = sorted({round(float(c), 1) for c in _cands if c > 0.0})
    return _cands or _grid


def _de_solve_magnitude(_eval, lo, hi, seeds=(), n_pop=6, n_gen=6, F=0.6, CR=0.9,
                        rng_seed=None):
    """Differential-evolution solve of a 1-D bounded action magnitude that
    MAXIMISES _eval(x) over [lo,hi]. Used so every timing change (GE/ER/...) has
    its seconds SOLVED against the CTM corridor surplus rather than picked from a
    fixed grid. `seeds` warm-start the population with closed-form guesses (the
    bus-serve / demand-clear values), so few generations suffice and the solve
    never does worse than the closed form. Returns (best_x, best_val).

    DE is a stochastic metaheuristic: its exploration (population init, donor
    selection, crossover) is random BY DESIGN -- that is how it escapes local
    optima on a non-monotone surplus (e.g. a spillback knee). `rng_seed` makes that
    exploration DETERMINISTIC via a LOCAL Random instance (the caller passes a
    per-junction+tick seed), so the same decision state solves identically across
    runs -- clean arm-to-arm A/B -- without touching the global RNG (ε-greedy)."""
    import random as _rnd_de
    _rng = _rnd_de.Random(rng_seed)          # local, seeded; None -> system entropy
    lo = float(lo); hi = float(hi)
    if not (hi > lo):
        return lo, _eval(lo)
    _pop = []
    for _s in (seeds or ()):
        try:
            _pop.append(min(max(float(_s), lo), hi))
        except Exception:
            pass
    while len(_pop) < max(4, int(n_pop)):
        _pop.append(_rng.uniform(lo, hi))
    _val = [_eval(x) for x in _pop]
    _n = len(_pop)
    for _g in range(int(n_gen)):
        for _i in range(_n):
            if _n >= 4:
                _a, _b, _c = _rng.sample([j for j in range(_n) if j != _i], 3)
            else:
                _a, _b, _c = 0, min(1, _n - 1), _n - 1
            _trial = _pop[_a] + F * (_pop[_b] - _pop[_c])
            if _rng.random() > CR:
                _trial = _pop[_i]
            _trial = min(max(_trial, lo), hi)
            _tv = _eval(_trial)
            if _tv > _val[_i]:
                _pop[_i] = _trial; _val[_i] = _tv
    _bi = max(range(_n), key=lambda k: _val[k])
    return _pop[_bi], _val[_bi]


def _de_seed_for(self, atype, time):
    """Deterministic per-(junction, tick, family) DE seed -- integer arithmetic
    only (no string hashing, so it is stable across Python runs regardless of
    PYTHONHASHSEED). DE_SEED_BASE shifts the whole stream if a fresh draw is ever
    wanted."""
    _base = int(globals().get('DE_SEED_BASE', 12345) or 0)
    _atx = {'GE': 1, 'EARLY_RED': 2, 'GREEN_REALLOC': 3,
            'INS': 4, 'INS_POST': 5, 'INS_PRETERM': 6}.get(atype, 0)
    _jid = int(getattr(self, 'id', 0) or 0)
    return (_jid * 1000003 + int(float(time)) * 131 + _atx * 17 + _base) & 0x7fffffff


def dctsp_cellqlearn_corridor(self, time, timeSta, acycle, bus_eta_s, veh_id,
                              current_phase, no_act_delay, sigma_in,
                              remaining_red_s=0.0):
    """CELLQLEARN-v2 (BXT_CORRIDOR_MODE) -- corridor-demand controller on the cell-
    transition model. Small action set {HOLD, EXTEND(GE), END_EARLY(ER)} that CHANGE
    THE CURRENT PHASE, each evaluated on the CTM (_dctsp_eval_action) and scored by
    the CORRIDOR pax-delay surplus (_nash_phase_total_bps = bus + through mainline,
    minus cross cost). STAGE 1 = CTM-greedy HEURISTIC (deterministic); the same
    scoring becomes the Q-learner's optimistic-init prior (stage 2) and a corridor-
    wide CHANGE_CYCLE is added by the coordinator (stage 3). Returns the standard
    decider contract (best_type, best_param, best_r, best_r_delta, best_so, best_tp,
    rows). EARLY_RED / EXTEND remain subject to the recoverability + progression
    gates at execution, so cycle-lengthening/offset-drifting picks are still bounded."""
    import random as _rnd_cq
    _wrong = (int(current_phase) != int(getattr(self, 'BusPhase', current_phase)))
    _state = _cellq_corridor_state(self, time, current_phase, no_act_delay)
    # Remaining green on the current phase -> lets _dctsp_eval_action ETA-gate a
    # GE's bus benefit. Computed by an ENGINE-SIDE method so GetPhaseDuration (an
    # engine wrapper, not an AAPI primitive) resolves natively -- calling it bare
    # from here raised NameError and disabled the bus logic (rem_green=None).
    try:
        _rem_green = self._current_green_remaining_s(time, timeSta)
    except Exception:
        _rem_green = None
    if not getattr(self, '_remgreen_diag_done', False):
        self._remgreen_diag_done = True
        try:
            _log_func(self, f"[REMGREEN] inter={getattr(self, 'id', '?')} "
                            f"rem_green={_rem_green} (None=bus ETA logic OFF)")
        except Exception:
            pass
    r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
        self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
    rows = [('NO_ACTION', 0.0, r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na)]
    _ge_grid = [float(x) for x in (globals().get('GE_DURATIONS_S') or [5.0, 10.0, 15.0])]
    _er_grid = [float(x) for x in (globals().get('ER_DURATIONS_S') or [10.0, 20.0, 30.0])]

    # ── CORRIDOR COUPLING (CELLQ_CORRIDOR_COUPLED, default OFF) ────────────────
    # The local surplus (_nash_phase_total_bps - cpc) credits through-traffic on
    # the extended green but prices only the LOCAL cross + opposite-main cost; it
    # does NOT see the downstream landing cost of shoving the through-platoon into
    # a downstream RED. Without it a green extension shows positive local surplus
    # and fires even when it breaks progression two junctions on (KG A/B: 32 ext,
    # car +31%). When coupled, subtract w_corr * the bus-free downstream landing
    # cost (_continuous_corridor_penalty, green-giving actions only) so an
    # offset-drifting extension goes net-negative and the decider HOLDs. This is
    # the c^corr term the paper's CellQLearn-v2 derivation (sec:cellqlearn_v2)
    # already specifies; the coefficient reuses CONTINUOUS_CORRIDOR_NEIGHBOR_W.
    _coupled = bool(globals().get('CELLQ_CORRIDOR_COUPLED', False))
    _wcorr = float(globals().get('CONTINUOUS_CORRIDOR_NEIGHBOR_W', 0.5) or 0.0)

    # ── EXACT-TRACKER BUS BENEFIT (CELLQ_CORRIDOR_BUS_CHAIN, default OFF) ──────
    # The local bus benefit (bps from _dctsp_eval_action) credits the FULL
    # seconds an extension saves the bus AT THIS junction -- but on a coordinated
    # corridor the bus re-queues downstream, so that local saving does NOT survive
    # end-to-end (KG A/B: 8600 pax·s predicted bus saving, realized bus delay
    # FLAT). When on, net the bus benefit by its CHAINED downstream re-delay from
    # the EXACT bus tracker (project_chain_delay_paxs reads self._trackers[veh_id]
    # speed + corridor geometry), so only bus time that actually survives the
    # corridor is credited. Bus-present green-giving actions only; cars stay on the
    # detector-queue proxies (main/side scans).
    _bus_chain = bool(globals().get('CELLQ_CORRIDOR_BUS_CHAIN', False))
    _coord_cc = getattr(self, '_corridor_coord', None)
    _bocc_cc = max(float(getattr(self, 'BusOcc', 40.0) or 40.0), 1.0)
    _green_giving_cc = ('GE', 'GREEN_REALLOC', 'INS', 'INS_POST', 'INS_PRETERM')
    # PURDUE POG cost in the surplus: price the POG-weighted progression damage of
    # an offset-shifting extension so the decider prefers progression-preserving
    # actions (the fix for the diffuse coordination breakage a per-action veto can't
    # catch). Sample the live POG once so _progression_cost has a fresh reading.
    _pog_on = bool(globals().get('POG_DECISION_COST', False))
    _pog_w = float(globals().get('POG_DECISION_WEIGHT', 1.0) or 0.0)
    if _pog_on:
        try:
            self._sample_progression(current_phase)
        except Exception:
            _pog_on = False
    # CELLQ_CTM_REWARD: price the cross-approach CAR cost with a GENUINE Cell-
    # Transmission-Model cell (sending=min(sat,n/dt), receiving=jam-density storage,
    # conservation) parameterised from the Aimsun plant, instead of the Webster/
    # shockwave overflow term -- so the learner's reward is the CTM it is named for.
    _ctm_reward = (bool(globals().get('CELLQ_CTM_REWARD', False))
                   and hasattr(self, '_ctm_cross_cost_paxs'))

    # ── best action per FAMILY via the CTM (magnitude solved within family) ──
    # families: 0=HOLD, 1=EXTEND(GE), 2=END_EARLY(ER). This keeps the LEARNER's
    # action space tiny (3) while the CTM still picks the best magnitude.
    _fam = {0: ('NO_ACTION', 0.0, 0.0, so_na, tp_na)}      # HOLD, surplus 0

    def _score_action(_atype, _ap):
        """Corridor surplus (pax·s) of one (action, magnitude); appends its row.
        Returns (surplus, so, tp) or None on failure. Shared by the DE solver so
        the magnitude is optimised against the SAME objective the decider ranks."""
        try:
            r, so, tp, bps, cpc, nsd, std = _dctsp_eval_action(
                self, _atype, float(_ap), sigma_in, no_act_delay, bus_eta_s,
                wrong_phase=_wrong, remaining_red_s=remaining_red_s,
                remaining_green_s=_rem_green)
        except Exception:
            return None
        bps = max(0.0, float(bps)); cpc = max(0.0, float(cpc))
        # CTM cross cost (green-giving actions steal cross green -> extra cross red):
        # replace the analytic cpc with the CTM cell cost when enabled.
        if _ctm_reward and _atype in _green_giving_cc:
            try:
                _cpc_ctm = float(self._ctm_cross_cost_paxs(float(_ap), timeSta))
                if _cpc_ctm > 0.0:
                    cpc = _cpc_ctm
            except Exception:
                pass
        # Net the LOCAL bus benefit by its exact-tracker chained downstream
        # re-delay so only end-to-end-surviving bus time is credited.
        if (_bus_chain and bps > 0.0 and int(veh_id) >= 0
                and _atype in _green_giving_cc and _coord_cc is not None):
            try:
                _bsaved_s = float(bps) / _bocc_cc
                _chain_cost = float(_coord_cc.project_chain_delay_paxs(
                    int(getattr(self, 'id', -1)), int(veh_id), float(time),
                    float(timeSta), float(bus_eta_s), _bsaved_s, _bocc_cc))
                bps = max(0.0, bps - max(0.0, _chain_cost))
            except Exception:
                pass
        _s = _nash_phase_total_bps(self, _atype, float(_ap), bps) - cpc  # corridor pax·s
        if _coupled and _wcorr > 0.0:
            try:
                _cp = float(_continuous_corridor_penalty(
                    self, [(_atype, float(_ap))], time, timeSta)[0])
            except Exception:
                _cp = 0.0
            _s -= _wcorr * max(0.0, _cp)                # downstream landing cost
        if _pog_on and _atype in _green_giving_cc:
            try:
                _s -= _pog_w * max(0.0, float(self._progression_cost(float(_ap))))
            except Exception:
                pass
        rows.append((action_label(_atype, float(_ap)), float(_ap), r, so, tp, bps, cpc, nsd, std))
        return (_s, so, tp)

    def _solve_family(_atype, lo, hi, seeds):
        """DE-solve the magnitude of a timing family over [lo,hi], seeded with the
        closed-form guesses. Returns (atype, best_param, surplus, so, tp) or None."""
        def _ev(x):
            _r = _score_action(_atype, float(x))
            return _r[0] if _r is not None else -1.0e18
        try:
            _bx, _ = _de_solve_magnitude(_ev, float(lo), float(hi), seeds=seeds,
                                         rng_seed=_de_seed_for(self, _atype, time))
        except Exception:
            _bx = float(seeds[0]) if seeds else float(lo)
        _r = _score_action(_atype, float(_bx))
        if _r is None:
            return None
        return (_atype, float(_bx), _r[0], _r[1], _r[2])

    _ge_lo, _ge_hi = (min(_ge_grid), max(_ge_grid)) if _ge_grid else (5.0, 15.0)
    _er_lo, _er_hi = (min(_er_grid), max(_er_grid)) if _er_grid else (10.0, 30.0)
    # ── RECOVERABILITY CLAMP on GE (offset preservation) ──────────────────────
    # A GE lengthens the cycle by its seconds, which _apply_cycle_recovery must
    # trim back from the upcoming cross phases THIS cycle to keep the junction on
    # the corridor's coordinated OFFSET. If the extension exceeds the recoverable
    # headroom (upcoming phases' slack above min-green), the debt can't be repaid,
    # the offset drifts, and the green wave breaks downstream over many cycles --
    # the KG failure where even 2 executed GE gave car +49%. The executor's
    # RECOVER_GATE (engine _reward_tsp) never fires for this decider (RECOVER_GATE=0
    # in the logs), so bound the DE's GE search to the recoverable budget here, in
    # the decider, exactly as Nash's grants are bounded. GR/ER are cycle-neutral /
    # cycle-shortening and are exempt.
    _min_ge = float(globals().get('MIN_GE_EXTENSION_S', 3.0))
    _ge_hi_recov = _ge_hi
    if bool(globals().get('RECOVERABILITY_GATE', True)):
        try:
            _recov = float(self._reward_get_recoverable(current_phase, timeSta))
            _kmax = max(1, int(globals().get('RECOVERY_MAX_CYCLES', 1)))
            _slack = float(globals().get('RECOVERABILITY_SLACK_S', 1.0))
            _ge_hi_recov = min(_ge_hi, _recov * _kmax + _slack)
        except Exception:
            _ge_hi_recov = _ge_hi
    if not _wrong and _ge_hi_recov >= _min_ge:
        # SOLVE the GE seconds with DE (seeded by the closed-form bus-serve /
        # demand-clear guesses), bounded to the recoverable headroom.
        _ge_seeds = [min(s, _ge_hi_recov)
                     for s in _solve_ge_durations(self, bus_eta_s, _rem_green, veh_id)]
        _e = _solve_family('GE', min(_ge_lo, _ge_hi_recov), _ge_hi_recov, _ge_seeds)
        if _e is not None:
            _fam[1] = _e
    elif not _wrong:
        _log_func(self, f"[RECOVER_GATE][CELLQ] inter={self.id} t={time:.1f} "
                        f"GE unrecoverable (budget={_ge_hi_recov:.1f}s < "
                        f"{_min_ge:.1f}s) -> GE suppressed (preserve offset)")
    # SOLVE the EARLY_RED seconds with DE over its envelope too.
    _rr = _solve_family('EARLY_RED', _er_lo, _er_hi, [_er_lo, 0.5 * (_er_lo + _er_hi)])
    if _rr is not None:
        _fam[2] = _rr
    _fam_surplus = {k: max(0.0, float(v[2])) for k, v in _fam.items()}

    # ── selection: STAGE 1 greedy heuristic, or STAGE 2 Q-learner ─────────────
    if not bool(globals().get('CELLQ_CORRIDOR_LEARN', False)):
        _pick = max(_fam.keys(), key=lambda k: _fam[k][2])        # CTM-greedy
        _mode_tag = ''
    else:
        # Tabular Q over the 3 families, per junction (MARL-style independent
        # agent). Immediate reward = CTM surplus of the action; discounted future
        # value (gamma*max Q[s']) lets it learn TEMPORAL effects the greedy
        # heuristic can't -- e.g. an extension that pays now but saturates a
        # downstream cell later. OPTIMISTIC INIT from the heuristic so an untrained
        # state acts like the heuristic (no cold-start zeros). 243 states x 3.
        _alpha = float(globals().get('BXT_ALPHA', 0.2) or 0.2)
        _gamma = float(globals().get('BXT_GAMMA', 0.5) or 0.5)
        _eps = float(globals().get('BXT_EPSILON', 0.05) or 0.0)
        try:
            _key = _bxt_q_key(int(getattr(self, 'id', 0)))
        except Exception:
            _key = int(getattr(self, 'id', 0))
        _qtab = getattr(self, '_cellq_q', None)
        if _qtab is None:
            _qtab = {}; self._cellq_q = _qtab
        _qj = _qtab.setdefault(_key, {})
        if _state not in _qj:                                    # heuristic-seeded init
            _qj[_state] = [float(_fam_surplus.get(0, 0.0)),
                           float(_fam_surplus.get(1, 0.0)),
                           float(_fam_surplus.get(2, 0.0))]
        _qrow = _qj[_state]
        # TD update for the PREVIOUS decision now that s' = _state is observed.
        # Enhanced: bootstrap only over families admissible in s' (guard-set
        # awareness, matching the paper's mask). _fam holds the CURRENT state's
        # families (0=HOLD always; 1=GE only when the bus phase runs; 2=ER), so
        # masking max Q(s') to _fam keys excludes phase-inadmissible families.
        _prevs = getattr(self, '_cellq_prev', None)
        if _prevs is None:
            _prevs = {}; self._cellq_prev = _prevs
        _pv = _prevs.get(_key)
        if _pv is not None:
            _ps, _pa, _pr = _pv
            _pq = _qj.get(_ps)
            if _pq is not None and 0 <= int(_pa) < len(_pq):
                _bn = [_qrow[_k] for _k in (0, 1, 2)
                       if _k in _fam and _k < len(_qrow)]
                _boot = _gamma * max(_bn) if _bn else 0.0
                _pq[int(_pa)] += _alpha * (float(_pr) + _boot - _pq[int(_pa)])
        # Selection runs EVERY tick, not only when a previous decision exists:
        # the FIRST decision at a junction has _pv=None but must still pick an
        # action (otherwise _pick is unbound -> UnboundLocalError at _fam[_pick]).
        _avail = [k for k in (0, 1, 2) if k in _fam]
        if _eps > 0.0 and _rnd_cq.random() < _eps:
            _pick = _rnd_cq.choice(_avail)                       # explore
        else:
            _pick = max(_avail, key=lambda k: _qrow[k])          # exploit learned Q
        # record for the next-tick TD update (immediate reward = CTM surplus)
        _prevs[_key] = (_state, _pick, float(_fam_surplus.get(_pick, 0.0)))
        _mode_tag = ' [Q]'

    _at, _ap, _surp, _so, _tp = _fam[_pick]
    if _at == 'NO_ACTION' or _surp <= 0.0:
        return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)
    _log_func(self, f"[CELLQ_CORRIDOR]{_mode_tag} inter={self.id} t={time:.1f} "
                    f"state={_state} fam={_pick} choose={action_label(_at, _ap)} "
                    f"surplus={_surp:.0f}paxs")
    return (_at, _ap, _surp, _surp, _so, _tp, rows)


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
    # GENERAL-TRAFFIC, BOTH DIRECTIONS (2026-10-01): coordination is about the
    # general arterial platoon's progression, not only the bus's heading. A main-
    # street green serves BOTH directions and shifting the offset disturbs the
    # downstream landing of each, so score the through-platoon's downstream re-delay
    # for the northbound AND southbound chains and sum them (distinct platoons ->
    # additive). force_is_nb overrides the (bus-derived) heading inside the projector.
    _bidir = bool(globals().get('CORRIDOR_COUPLE_BIDIRECTIONAL', True))
    _dirs = (True, False) if _bidir else (None,)
    for i, c in enumerate(cand):
        _at, _ap = c[0], c[1]
        _s = abs(float(_ap or 0.0)) if _at in _green_giving else 0.0
        if _s <= 0.0:
            continue
        _acc = 0.0
        for _fnb in _dirs:
            try:
                _d = float(_coord.project_chain_delay_paxs(
                    _atid, -1, float(time), float(timeSta), 0.0, _s, _car_occ,
                    force_is_nb=_fnb))
                _acc += max(0.0, _d)
            except Exception:
                pass
        pen[i] = _acc
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
    # Fairness projection of the estimated state (parity: _XT_PROJECTION_V1).
    _proj = _xt_nash_projection(self, bus_eta_s, no_act_delay, current_phase,
                                veh_id)
    _bus_occ = _proj['bus_occ']
    eff_delay = _proj['eff_delay']
    wrong_phase = _proj['wrong_phase']

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
    _monitor = _proj['monitor']
    if _monitor and not bool(globals().get('NASH_CONTINUOUS_MODE', True)):
        return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)

    # gate 1: do not bargain for a barely-delayed bus (bus-present game only)
    if not _monitor and eff_delay < _proj['min_delay_s']:
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
        # Corridor-agnostic bounds (2026-09-27): same cycle-scaled +
        # recoverable-headroom caps the generic-GE solver uses, so Nash
        # magnitudes can't exceed what the junction's own cycle can repay.
        try:
            _nub = None
            if hasattr(self, '_junction_ge_ub'):
                try:
                    _nub = float(self._junction_ge_ub(timeSta))
                except Exception:
                    _nub = None
            if _nub is None or _nub <= 0.0:
                _nub = float(globals().get('MAX_GE_EXTENSION_S', 10.0) or 10.0)
            try:
                _nrec = float(self._reward_get_recoverable(
                    current_phase, timeSta))
                _nslack = float(globals().get('RECOVERABILITY_SLACK_S', 1.0))
                _nub = min(_nub, max(1.0, _nrec + _nslack))
            except Exception:
                pass
            _ge_hi = int(max(1.0, min(float(_ge_hi), _nub)))
            _ins_hi = int(max(_ins_lo, min(float(_ins_hi), _nub)))
        except Exception:
            pass
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
            # CONTINUOUS (no-bus) game is CAR-ONLY by design: the monitor tick's
            # `no_act_delay` is the no-action cap (cycle - bus green), NOT a real
            # bus delay, so passing _c[4] here fabricated a phantom bus term
            # (bps_bus=600 for GE_15 on bus-phase monitor ticks) that dominated
            # the surplus. Zero it for monitor ticks; the bus-present game keeps
            # its real estimate. (2026-09-26)
            _bt = _nash_phase_total_bps(self, _c[0], _c[1],
                                        (0.0 if _monitor else _c[4]))
            if _pen is not None:
                _bt = max(0.0, _bt - _wnb * _pen[_i])
            _frontier.append((_bt, _c[5]))
        # STATE-DEPENDENT THREAT (bus-present only): the disagreement point gets
        # worse for the bus as the cross street saturates, so a bargain requires a
        # larger transit gain exactly where preemption is most costly.
        _threat = 0.0
        if not _monitor and bool(globals().get('NASH_STATE_THREAT', False)):
            try:
                _kj = max(float(getattr(self, 'JamDensity', 150.0)) or 150.0, 1.0)
                _dens = [float(v) for v in (getattr(self, 'SideUpDenList', []) or [])]
                _xsat = min(max(0.0, (max(_dens) / _kj) if _dens else 0.0), 1.0)
                _threat = (float(globals().get('NASH_THREAT_CROSS_GAIN', 20.0))
                           * _xsat * _bus_occ)
            except Exception:
                _threat = 0.0
        _bi, _ = _nash_bargain_pick(_frontier, p_T, p_C, threat=_threat)
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
    # Monitor ticks use the CAR-ONLY phase total (see the frontier note above).
    _bps_tot = _nash_phase_total_bps(self, _at, _ap,
                                     (0.0 if _monitor else _bps))
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
        _inf = _eci_call('AKIInfNetGetSectionANGInf', int(sid))
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
            n = int(_eci_call('AKIVehStateGetNbVehiclesSection', int(sid), True))
        except Exception:
            n = 0
        n_dwell = 0
        for vi in range(n):
            try:
                inf = _eci_call('AKIVehStateGetVehicleInfSection', int(sid), vi)
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
            _t_now = float(_eci_call('AKIGetCurrentSimulationTime', ))
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
            _cph = _eci_call('ECIGetCurrentPhase', self.node_id)
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
                    up += float(_eci_call('AKIVehStateGetNbVehiclesSection', int(sid), True)) * _car_occ
                    # Bus boost: count buses on this section at BusOcc
                    n_bus = 0
                    try:
                        nb = int(_eci_call('AKIVehStateGetNbVehiclesSection', int(sid), True))
                        for vi in range(nb):
                            inf = _eci_call('AKIVehStateGetVehicleInfSection', int(sid), vi)
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
                            down += float(_eci_call('AKIVehStateGetNbVehiclesSection', ds, True)) * _car_occ
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
        # Stability projection of the estimated state (parity: _XT_PROJECTION_V1).
        _proj = _xt_mp_projection(pressures, current_phase,
                                  getattr(self, 'BusPhase', None))
        _pm = _proj['p_main']
        _ps = _proj['p_side']
        _ptot = _proj['p_tot']
        _cur_is_main = _proj['cur_is_main']
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
# 2026-10-08: GE-specific veto ratio. GE (cheap, small-benefit extensions) was
# held to the tight base ratio while INS enjoyed 3.0, so GE never survived the
# veto despite winning the CTM sweep ~80% of the time it was evaluated
# (measured: 0/4206 GE rows chosen). 2.5 default; tune per-experiment via
# run_config like the other two ratios.
DECIDER_COST_VETO_RATIO_GE = 2.5

# Main-starvation term for the net-benefit gate (2026-10-12). The cross/side cost
# ledger prices only the STREAMS WE CUT. EARLY_RED on a wrong phase truncates the
# current phase to advance the bus; when that phase is the SATURATED MAIN, the
# harm lands on the through-movements that _cross_cost_paxs never sees, and the
# learner books a cheap bus win while the main starves. Measured signature on
# Aimsun: bus delay improves, main throughput collapses. Adding the main queue to
# the COST side of the same accept test makes the gate cover both failure modes --
# over-action (cross cost) and main starvation (this term).
BXT_MAIN_STARVE_GATE = False
# Main-approach queue (veh) at/above which the main counts as saturated. Below
# this the term is 0 and the gate behaves exactly as before.
BXT_MAIN_STARVE_VEH = 8.0
# Passenger-occupancy applied to the queue term so it is in the same pax-s
# currency as _bus_benefit_total_paxs and _cross_cost_paxs.
BXT_MAIN_STARVE_OCC = 1.2
# Seconds of main delay charged per queued vehicle, per second of action magnitude.
# Calibrated so a fully saturated main charges ~ the same order as the cross cost
# of the same action rather than dominating it.
BXT_MAIN_STARVE_S_PER_VEH = 1.0

# Main-starvation COST (2026-10-12). DECLARED HERE so the term is part of
# MODE_FLAGS: AAPIInit copies run_config.py values into this module and
# reset_mode_flags() restores the default between experiments.
#
# It was previously consumed via globals().get('MAIN_STARVATION_COST', True) with
# NO module-level declaration, no MODE_FLAGS entry and no engine propagation
# entry. That made it permanently ON in every arm and impossible to A/B -- the
# same defect documented for BXT_BARGAIN_DECISION at the 2026-10-01 ablation
# (flag set in run_config, ignored at runtime, arms came back byte-identical).
# X0 = main_x above which a green cut is charged at all (a cut on a FREE main is
# unpenalised, which keeps legitimate gains and is KG-safe); CAP bounds the term
# because new cost terms have mis-scaled here before.
MAIN_STARVATION_COST = True
MAIN_STARVATION_X0 = 1.0
MAIN_STARVATION_CAP_PAXS = 4000.0

# Saturation-RELIEF credit (2026-10-12), default OFF. The reward ledger is
# currently asymmetric: `reward = w_bus*(bus_pax_saved + mainline_pax_saved)
# - w_cross*cross_cost` (specialized_modes.py:1552). Saturation appears ONLY on
# the cost side, so an action that relieves a saturated approach WITHOUT
# helping a specific bus scores ~0 or negative -- the network-level benefit is
# never paid for. That is the structural reason the learned class starves.
#
# This term adds the missing benefit side: credit for action magnitude applied
# where the measured main is over-saturated. RELIEF_MAX is a HIGH main_x (where
# relieving matters most); RELIEF_MIN_X is the floor below which the main is not
# considered over-saturated, so the term is 0 on a FREE main and cannot
# manufacture action out of nothing. Rate is pax-s per second of action.
# Flag-gated and default OFF because new reward terms have mis-scaled here.
SAT_RELIEF_BONUS = False
SAT_RELIEF_MIN_X = 0.85          # main_x floor to earn relief credit (OVER tier)
SAT_RELIEF_MAX_X = 1.30          # main_x at/above which credit is full
SAT_RELIEF_RATE_PAXS = 60.0      # pax-s credit per second of action magnitude
SAT_RELIEF_CAP_PAXS = 2500.0     # bound, same reason as MAIN_STARVATION_CAP_PAXS

# Main-starvation COST, degree-of-saturation basis (2026-10-13). -1 = disabled,
# which keeps the legacy measured-queue path in charge. With main_x now
# lane-corrected, a value of 0.85-0.95 means "the main approach is at/over
# capacity", which is the condition the term was written to price but could
# never detect while main_x was pinned at 2.0.
BXT_MAIN_STARVE_X = -1.0

# main_x lane correction (2026-10-13) + saturation-term diagnostics.
MAIN_X_LANE_AWARE = True
TSP_DIAG_SAT_TERMS = True

# Cyclic MaxPressure (Varaiya-faithful): when True, a per-step scheduler in the
# engine re-evaluates pressures every interval and switches phases directly --
# independent of bus detections -- while the detection-path generators below
# stand down. False = legacy bus-triggered behaviour.
MAXPRESSURE_CYCLIC = False

MODE_FLAGS = [
    'BXT_OPT_OFFSET_PUSH', 'BXT_OPT_OFFSET_CSV', 'BXT_OPT_PUSH_MIN_S',
    'BXT_OPT_PUSH_MAX_S', 'BXT_OPT_PUSH_SAT_VETO',
    'BXT_OPT_PUSH_REQUIRE_BEFORE_BUS',
    'BXT_MODE', 'BXT_DT_S', 'BXT_EPSILON', 'BXT_ALPHA', 'BXT_GAMMA',
    'BXT_STATE_EDGES', 'BXT_LOG_RAW_STATE',
    'BXT_DEMAND_WARMSTART', 'BXT_WARMSTART_SCENARIOS', 'BXT_WARMSTART_SAT_FRAC',
    'BXT_CAR_OCC', 'BXT_BALANCE_FACTOR', 'BXT_GE_BALANCE_FACTOR',
    'BXT_MAX_INS_S', 'TIMING_DE_POP', 'TIMING_DE_GENS', 'TIMING_DE_F',
    'TIMING_DE_CR', 'TIMING_DE_SEED',     'BXT_EVAL_DIAGNOSTICS',
    'REWARD_GE_SOLVER', 'GE_MAX_FRAC_OF_CYCLE',
    'RETIME_APPLY', 'RETIME_CSV',
    'MEASURED_TURN_COST', 'HEADROOM_RESERVE_S',
    'FOCUS_SCOPE_RADIUS_M',
    'MULTIBUS_JOINT', 'MULTIBUS_NETWORK',
    'PROGRESSION_DEGREE_WEIGHT', 'PROGRESSION_BIDIRECTIONAL',
    'POG_DECISION_COST', 'POG_DECISION_WEIGHT', 'POG_ADAPT_GATE',
    'PLAN_OPTIMIZE', 'PLAN_TRANSIT_WEIGHT', 'PLAN_CYCLE_MIN_S', 'PLAN_CYCLE_MAX_S',
    'PLAN_MIN_GREEN_S', 'PLAN_INTERGREEN_S', 'PLAN_NOMINAL_HEADWAY_S',
    'PLAN_OPTIMIZE_OFFSETS', 'PLAN_BUS_SPEED_MS',
'DS_MASTER_CYCLE', 'DS_MASTER_INTERVAL_S',
'DS_MASTER_MIN_RATIO', 'DS_MASTER_MAX_RATIO', 'DS_MASTER_COMMISSIONED',
'DS_MASTER_OFFSETS', 'DS_OFFSET_TOL_S', 'DS_OFFSET_MAX_SHIFT_FRAC',
'DS_OFFSET_MAX_STEP_S', 'DS_MASTER_DS_MIN_CRIT',
'DS_SPLIT_PROPORTIONAL', 'DS_SPLIT_MAX_MOVE_S', 'DS_SPLIT_DS_EQUAL',
 'SCATS_CYCLE_LAW', 'SCATS_CYCLE_LADDER_S', 'SCATS_SEQUENCE_BY_Y',
 'DS_SPLIT_RESTART_S', 'DS_SPLIT_CRITICAL_LANE',
'SCATS_GAP_OUT', 'SCATS_GAP_MIN_GREEN_S', 'SCATS_GAP_MAX_OCC_VEH',
'SCATS_GAP_MAX_FLOW_VPH', 'SCATS_GAP_NEXT_MIN_Y', 'SCATS_GAP_EVERY_S',
'SCATS_GAP_BUS_PHASE',
'SCATS_MAX_OUT', 'SCATS_MAX_OUT_S',
'SCATS_MAX_OUT_PLAN_AWARE', 'SCATS_MAX_OUT_DEMAND_GUARD',
'SCATS_MAX_OUT_GRACE_S',
'DS_TRUTH_CHECK', 'DS_TRUTH_INTERVAL_S',
'CYCLE_CAP_ENABLE', 'CYCLE_CAP_SLACK_S', 'CYCLE_CAP_SLACK_FRAC',
'DS_BIAS_CORRECT', 'DS_GATE_REQUIRE_RELIABLE', 'DS_CALIB_MIN_N',
'DS_CALIB_MAX_MAE_VEH', 'DS_CALIB_MIN_CORR',
'SPILLBACK_GATE', 'SPILLBACK_GATE_FRAC', 'JAM_VEH_SPACING_M',
'SCATS_PHASE_ORIGIN_FALLBACK', 'RELIEF_NEEDS_DOWNSTREAM',
'ACTUATED_EXTEND', 'ACT_EXTEND_STEP_S', 'ACT_EXTEND_MAX_GREEN_S',
'ACT_EXTEND_BAND', 'ACT_EXTEND_ABS_CAP_S',
'ACT_EXTEND_MIN_OCC_VEH', 'ACT_EXTEND_MIN_FLOW_VPH', 'ACT_EXTEND_BUS_PHASE',
'SCATS_LEADLAG', 'SCATS_LEADLAG_HEAVY_Y',
 'SCATS_CRITICAL_INTERSECTION', 'SCATS_PLAN_LIBRARY',
 'SCATS_POG_OFFSETS', 'SCATS_POG_STEP_S', 'SCATS_POG_EPS', 'PLAN_MEASURED',
 'PLAN_SCATS_HIST', 'SCATS_HIST_SHARE', 'SCATS_HIST_DAYTYPE',
 'SCATS_HIST_TOD_MIN',
'DS_MASTER_SUBSYS_SPREAD',
'DS_MARRY_DIVORCE', 'DS_MARRY_TOL', 'DS_MARRY_HYST', 'DS_MARRY_HOLD_S',
'SCATS_PHASE_SKIP', 'SCATS_SKIP_DS', 'SCATS_SKIP_GREEN_S', 'SCATS_SIDE_MONITOR',
'PLAN_CYCLE_BAND',
'VLOOP_EMULATION', 'VLOOP_WINDOW_S', 'VLOOP_WARM_S', 'VLOOP_MIN_WINDOW_S',
'VLOOP_VISIT_GAP_S', 'VLOOP_SANE_FACTOR',
'VLOOP_OCC_SPILLBACK', 'VLOOP_STOP_KPH', 'VLOOP_OCC_ALPHA',
'VLOOP_OCC_MIN_VEH', 'VLOOP_SPILL_DIS_FRAC', 'SIDE_FLOW_MEASURED_ONLY',
'DETECTION_COVERAGE_AUDIT', 'SCATS_DS_DISCHARGE', 'DS_FLOW_QUEUE_AWARE',
'DS_GREEN_INDEPENDENT', 'DS_PER_TURN_FLOW',
'DS_ORDER_PRESERVE', 'DS_ORDER_CEIL',
'DS_SOLVE_PER_CYCLE', 'DS_SPLIT_MAX_MOVE_FRAC',
'DS_QUEUE_SAT_VEH_PER_LANE', 'DS_SPLIT_COMMISSIONED_BAND',
'DS_BAND_DEMAND_ENABLE', 'DS_BAND_DEMAND_DS', 'DS_BAND_DEMAND_MULT',
'SCATS_BUS_PRIORITY', 'BUS_PRIO_MAX_EXT_S', 'BUS_PRIO_MAX_RECALL_S',
'BUS_PRIO_JIT_ENABLE', 'BUS_PRIO_QUEUE_DELAY_S', 'BUS_PRIO_JIT_MARGIN_S',
'BUS_PRIO_JIT_STRIKE_S', 'BUS_PRIO_RECALL_ENABLE',
'QUEUE_SERVE_FLOOR', 'QUEUE_SERVE_CAP_S', 'QUEUE_SERVE_MAX_FRAC',
'QUEUE_RELEASE_DIAG', 'QUEUE_RELEASE_PERIOD_S',
'BUS_PRIO_COOLDOWN_S',
'PHASE_STARVE_GUARD', 'PHASE_PRESENCE_FLOOR',
'SCATS_CYCLE_CURVE', 'SCATS_CYCLE_K1', 'SCATS_CYCLE_K2',
'DS_MASTER_DS_CYCLE', 'DS_MASTER_DS_WARM_S', 'DS_MASTER_DS_STEP_S',
'DS_LANE_WORST', 'DS_MASTER_SPLITS',
'RESTRUCTURE_MERGE_SAME', 'RESTRUCTURE_MERGE_DS',
    'SCOOT_RS_MODE', 'SCOOT_RS_TARGET_DS', 'SCOOT_RS_HYST',
    'SCOOT_RS_CYCLE_STEP_S', 'SCOOT_RS_MIN_RATIO', 'SCOOT_RS_MAX_RATIO',
    'SCOOT_RS_WARMUP_S', 'SCOOT_RS_OFFSETS',
    'PLAN_RESTRUCTURE', 'RESTRUCTURE_EVERY_S', 'RESTRUCTURE_MIN_GAIN_S',
    'RESTRUCTURE_ORDER', 'RESTRUCTURE_GROUP', 'RESTRUCTURE_MAX_PHASES',
    'GROUP_BASED_CONTROL', 'RESTRUCTURE_HOLD_S',
    'STATE_INCLUDE_FLOW_QUEUE', 'STATE_INCLUDE_NEIGHBOUR_TIMING',
    'STATE_INCLUDE_BUS_COUNT', 'STATE_INCLUDE_SIGNAL_CLOCKS',
    'STATE_QUEUE_PHYSICAL_FIRST',
    'GE_DURATIONS_S', 'INS_DURATIONS_S', 'ER_DURATIONS_S', 'GR_DURATIONS_S',
    'BXT_ENABLE_GE', 'BXT_ENABLE_INS', 'BXT_ENABLE_GR', 'BXT_ENABLE_ER',
    'BXT_ENABLE_OC',
    'MEASURED_SIDE_COST', 'MEASURED_SIDE_SPILL_GAIN', 'MEASURED_SIDE_FRESH_S', 'MEAS_MIN_SECTION_M',
    'DELAY_CALIBRATION', 'DELAY_CAL_REF_S', 'DELAY_CAL_ALPHA', 'DELAY_CAL_MIN', 'DELAY_CAL_MAX',
    'MICRO_QUEUE_MODE', 'MICRO_QUEUE_SPEED_KMH',
    'MEASURED_SIDE_COST_DIAG', 'DIAG_FLOW_STAGE', 'DIAG_DECISION',
    'RECOVERABILITY_GATE', 'RECOVERABILITY_SLACK_S',
    'RECOVERY_MAX_CYCLES', 'RECOVERY_TRANSITION_RATE',
    'PROGRESSION_GATE', 'PROGRESSION_MAX_LOSS_PAXS',
    'MP_TRANSIT_PAX_WEIGHT', 'CONTINUOUS_MONITOR_MODE',
    'CONTINUOUS_MONITOR_MIN_GAIN_PAXS', 'DEMAND_SEED_WARM_S',
    'MONITOR_STATE_GATE', 'SIDLESS_MONITOR_HOLD', 'SIDE_QUEUE_FLOOR',
    'SIDE_QUEUE_STOPPED_THRESHOLD_KMH',
    'MONITOR_PROG_WEIGHT', 'MONITOR_BUS_ZERO',
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
    'NASH_THRU_SURPLUS', 'NASH_NET_GATE_RATIO',
    'NASH_MIN_BUS_DELAY_S', 'NASH_MIN_GAIN_S', 'NASH_MEASURED_STATE',
    'NASH_STATE_THREAT', 'NASH_THREAT_CROSS_GAIN',
    'NASH_CONTINUOUS_MODE', 'CONTINUOUS_BARGAIN_BUS_WEIGHT',
    'CONTINUOUS_CORRIDOR_MODE', 'CONTINUOUS_CORRIDOR_NEIGHBOR_W',
    'CORRIDOR_COUPLE_BIDIRECTIONAL',
    'BXT_CONTINUOUS_MODE', 'MIN_PHASE_ACTIVE_S', 'NO_ACTION_HOLD_S',
    'NO_ACTION_QUEUE_AWARE', 'QUEUE_DISCHARGE_S_PER_VEH',
    'EMPTY_PHASE_SKIP_MODE', 'EMPTY_PHASE_QUEUE_EPS_PAX',
    'EMPTY_PHASE_MIN_TARGET_PAX', 'BXT_POG_REWARD', 'BXT_POG_WEIGHT',
    'BXT_POG_BONUS', 'BXT_POG_BONUS_WEIGHT', 'BXT_POG_BONUS_THRESHOLD',
    'POG_NEED_GATE', 'POG_NEED_MIN_S', 'POG_NEED_FLOOR',
    'BXT_CORRIDOR_MODE', 'CELLQ_CORRIDOR_LEARN', 'CELLQ_CORRIDOR_COUPLED',
    'CELLQ_CORRIDOR_BUS_CHAIN',
    'ZIGDOG_MODE', 'ZIGDOG_BUS_W', 'ZIGDOG_CAR_W', 'ZIGDOG_LATE_BOOST_S',
    'ZIGDOG_CYCLE_S', 'ZIGDOG_MAX_GE_S', 'ZIGDOG_MAX_ER_S', 'ZIGDOG_CTM',
    'ZIGDOG_STATE_MODE',
    'ZIGDOG_Q_MODE', 'ZIGDOG_Q_ALPHA', 'ZIGDOG_Q_GAMMA', 'ZIGDOG_Q_EPSILON',
    'ZIGDOG_Q_REALIZED_REWARD', 'ZIGDOG_Q_EXECUTE_ON_Q', 'ZIGDOG_Q_MIN_VISITS',
    'ZIGDOG_ER_CROSS_COST',
    'ZIGDOG_ACTION_BUDGET', 'ZIGDOG_MAX_ACTIONS_PER_CYCLE',
    'ZIGDOG_MAX_GE_PER_CYCLE',
    'ZIGDOG_Q_STATE_TIME', 'ZIGDOG_Q_TIME_BUCKETS',
    'ZIGDOG_DP_ENABLE', 'ZIGDOG_DP_BEAM', 'ZIGDOG_DP_DEPTH', 'ZIGDOG_DP_W',
    'ZIGDOG_DP_NEIGHBORS', 'ZIGDOG_DP_NEIGHBOR_W', 'ZIGDOG_DP_NEIGHBOR_TRAVEL_S',
    'ZIGDOG_SOLVE_ER', 'ZIGDOG_ER_MIN_S', 'ZIGDOG_ER_FINE_S',
    'ZIGDOG_ER_ABS_MAX_S',
    'ZIGDOG_INS_GR_SOLVER', 'ZIGDOG_INS_MAX_S', 'ZIGDOG_GR_MAX_S',
    'BXT_EXPLORE_BYPASS', 'BXT_EVAL_HEURISTIC_FALLBACK',
    'BXT_FALLBACK_MIN_BUS_DELAY_S',
    'ZIGDOG_ER_RESPECT_BAND', 'ZIGDOG_BAND_MAX_ER_S',
    'ZIGDOG_BAND_PROTECT_GREEN_S',
    'ZIGDOG_QUEUE_REL', 'ZIGDOG_QUEUE_W', 'ZIGDOG_QUEUE_LOG_S',
    'ZIGDOG_QUEUE_ACC',
    'ZIGDOG_Q_STATE_QUEUE', 'ZIGDOG_Q_STATE_BUS',
    'ZIGDOG_ER_REQUIRE_CLEARED', 'ZIGDOG_ER_CLEAR_Q_VEH',
    'ZIGDOG_Q_FAIL_PENALTY', 'ZIGDOG_Q_SERVED_MIN_GAIN',
    'ZIGDOG_INTERGREEN_S',
    'ZIGDOG_SHOCKWAVE_CORRECT', 'ZIGDOG_SHOCKWAVE_VFREEM_S',
    'ZIGDOG_FINAL_ALWAYS', 'ZIGDOG_FLEET_AOG', 'ZIGDOG_HORIZON_S',
    'ZIGDOG_MEASURED_CROSS', 'ZIGDOG_MEASURED_CROSS_ARRIVAL_VPH',
    'ZIGDOG_MIN_CYCLE_S', 'ZIGDOG_MAX_CYCLE_S', 'ZIGDOG_MAX_ER_PER_CYCLE',
    'ZIGDOG_MIN_PHASE_GREEN_S', 'ZIGDOG_CHAIN_PLAN', 'ZIGDOG_CHAIN_TAIL_W',
    'INS_GR_COORD_PHASE_ONLY', 'ZIGDOG_INS_GR_COORD_ONLY',
    'CELLQ_CTM_REWARD', 'CELLQ_CTM_DT_S', 'CELLQ_CTM_HORIZON_S',
    'CELLQ_STATE_NEIGHBOUR',
    'CELLQ_CTM_FREEFLOW_KMH', 'CELLQ_CTM_WAVE_KMH', 'CELLQ_CTM_MAX_CELLS',
    'CELLQ_CTM_STATE', 'CELLQ_CTM_STATE_CELLS',
    'CELLQ_CTM_SINGLE_CELL',
    # Decision-level ablation levers: MUST reset each arm or a True/value on one
    # arm bleeds into later arms (2026-10-01: A4/A5 inherited A3's bargain and came
    # out byte-identical to A3, invalidating their GE-cap / net-gate tests).
    'BXT_BARGAIN_DECISION', 'BXT_BARGAIN_PT', 'BXT_BARGAIN_PC', 'BXT_BARGAIN_MIN_N',
    'GE_UB_CAP_BY_JCT',
    'ACTUATED_BASE_MODE', 'ACTUATED_MIN_GREEN_S', 'ACTUATED_MAX_GREEN_S',
    'ACTUATED_GAP_QUEUE_EPS_VEH', 'ACTUATED_PERMISSIVE_GATE',
    'ACTUATED_OFFSET_PRESERVE', 'ACTUATED_DRIFT_TOL_S', 'ACTUATED_DRIFT_MAX',
    'NASH_CORRIDOR_MODE', 'NASH_NEIGHBOR_WEIGHT', 'NASH_MAX_ITER',
    'NASH_CONVERGENCE_TOL', 'NASH_INTEGER_DURATIONS',
    'TWOWAY_BAND_MODE', 'B_PLUS_MIN', 'B_MINUS_MIN', 'TWOWAY_GREEN_S',
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
    'REWARD_FUTURE_HORIZON_CYCLES', 'REWARD_FUTURE_HORIZON_S',
    'REWARD_FUTURE_DEBT_GAIN', 'REWARD_FUTURE_OFFSET_GAIN',
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
    'MAXPRESSURE_CYCLE_FIX', 'MAXPRESSURE_CYCLE_FLEX', 'MP_FIX_COMMISSIONED_BAND',
    'MP_FIX_RESOLVE_S', 'SIDE_PRICE_FROM_VLOOP',
    'GLOBAL_OCC_MONITOR', 'GLOBAL_OCC_MONITOR_S',
    'GLOBAL_OCC_MIN_REAL', 'GLOBAL_OCC_RATIO_WARN', 'MAXPRESSURE_T_A',
    'MAXPRESSURE_MEAS_PERIOD',
    'MP_PER_PHASE_PRESSURES', 'MP_EXTEND_ENABLE', 'MP_EXTEND_STEP_S',
    'MP_EXTEND_MAX_S', 'MP_DIRECT_TRANSITION', 'MP_NASH_ENABLE',
    'MAXPRESSURE_CYCLIC',
    # PBIL timing learner (2026-10-21)
    'PBIL_TS_MODE', 'PBIL_GEN_S', 'PBIL_DELTA', 'PBIL_ALPHA',
    'PBIL_MIN_P', 'PBIL_WARM_S',
    # Jalluri heuristic adaptive control (OCIT 2025)
    'JALLURI_MODE', 'JALLURI_MAX_WAIT_W', 'JALLURI_COUNT_W',
    'JALLURI_AGING_W', 'JALLURI_AGING_UNIT_S', 'JALLURI_GREEN_FACTOR',
    'JALLURI_CLEAR_CAR', 'JALLURI_CLEAR_BUS', 'JALLURI_CLEAR_TRUCK',
    'JALLURI_G_MIN', 'JALLURI_G_MAX',
    # MP-TSP-LB: dwelling-bus lane blockage + corridor coordination
    'MP_LANEBLOCK_MODE', 'MP_LANEBLOCK_LANES', 'MP_LANEBLOCK_TOTAL_LANES',
    'MP_DWELL_MIN_S', 'MP_DWELL_REQUIRE_GREEN',
    'MP_CORRIDOR_COORD_MODE', 'MP_CORRIDOR_COORD_WEIGHT',
    'MP_CORRIDOR_SAT_THRESHOLD',
    # Decider cost-veto tuning (see comment above the declarations)
    'DECIDER_COST_VETO_RATIO', 'DECIDER_COST_VETO_RATIO_INS',
    'DECIDER_COST_VETO_RATIO_GE',
    'BXT_MAIN_STARVE_GATE', 'BXT_MAIN_STARVE_VEH',
    'BXT_MAIN_STARVE_OCC', 'BXT_MAIN_STARVE_S_PER_VEH', 'BXT_MAIN_STARVE_X',
    'MAIN_STARVATION_COST', 'MAIN_STARVATION_X0', 'MAIN_STARVATION_CAP_PAXS',
    # SCATS degree-of-saturation feed / balance gate / plan adapt (2026-10-14)
    'DS_BALANCE_GATE', 'DS_MAX', 'DS_SPREAD_TOL', 'DS_CLAMP_MAX', 'DS_RAW_CLAMP_MAX',
'FLOW_DET_LANE_SCALE', 'DS_STUB_RESOLVE', 'DS_STUB_RESOLVE_M', 'DS_STUB_MAX_HOPS',
'DS_PAXF_MAX',
    'DS_SNAPSHOT_TTL_S', 'DS_PLAN_ADAPT', 'DS_ADAPT_STEP_S', 'DS_MIN_GREEN_S',
'DS_CAP_FLOOR_GREEN_S',
    'DS_ADAPT_EVERY_S', 'DS_IN_LEARNER_STATE', 'DS_STATE_EDGES', 'LOG_DS_ADAPT',
    'DS_COST_IN_REWARD', 'DS_COST_CAP_PAXS',
    'DS_PAX_WEIGHTED', 'DS_BUS_PAX_WEIGHT',
    'SCATS_TRANSIT_PRIORITY', 'SCATS_TP_LEVEL', 'SCATS_TP_WEIGHT',
    'DS_CYCLE_ADAPT', 'DS_CYCLE_TARGET', 'DS_CYCLE_HYST', 'DS_CYCLE_STEP_S',
    'DS_CYCLE_MIN_RATIO', 'DS_CYCLE_MAX_RATIO',
    'DS_CYCLE_MIN_S', 'DS_CYCLE_MAX_S',
    # Global-delay break-even + main-corridor floor (2026-10-17).
    'NET_PAX_DELAY_GATE', 'NET_PAX_DELAY_RATIO',
    'MAIN_CORRIDOR_FLOOR_GATE', 'MAIN_CORRIDOR_HARM_RATIO',
    'THROUGHPUT_REWARD', 'W_THROUGHPUT', 'W_DELAY_LEDGER', 'THRU_STARTUP_LOST_S',
    'MULTIHEAD_Q', 'MULTIHEAD_ACTION_FAMILY', 'MULTIHEAD_W_NET', 'MULTIHEAD_NET_GATE_DSMIN',
    # 2026-10-15 flag-audit: these were orphans (no default, not propagated) so an
    # arm's override never took / could carry over. Now reset+propagated per arm.
    'MODE_NET_BENEFIT_GATE', 'NET_GATE_RATIO', 'BXT_WARMSTART_FROM_SHARED',
    'SAT_RELIEF_BONUS', 'SAT_RELIEF_MIN_X', 'SAT_RELIEF_MAX_X',
    'SAT_RELIEF_RATE_PAXS', 'SAT_RELIEF_CAP_PAXS',
    # 2026-10-13: main_x lane correction + saturation-term instrumentation.
    # Without these the degree-of-saturation was inflated by the lane count
    # (pinned at exactly 2.0 on a 2-lane approach), the stage classifier called
    # JAM for 97% of a run, and every x-gated term returned 0.0 forever.
    'MAIN_X_LANE_AWARE', 'TSP_DIAG_SAT_TERMS',
    'MEASURED_TURN_COST',
    'PROGRESSION_DEGREE_MIN_DEGREE',
    'PROACTIVE_MODE', 'PROACTIVE_TICK_S', 'PROACTIVE_MIN_STAGE',
    'PROACTIVE_MAX_HORIZON_S', 'PROACTIVE_REQUIRE_TIMETABLE',
    'PROACTIVE_MAX_ACTIONS_PER_TICK',
    'PURE_STATE_MODE', 'PURE_STATE_TICK_S', 'PURE_STATE_MIN_STAGE',
    'PURE_STATE_MAX_HORIZON_S', 'PURE_STATE_REQUIRE_TIMETABLE',
    'PURE_STATE_MAX_ACTIONS_PER_TICK',
    'PURE_STATE_CAR_OCC', 'PURE_STATE_BUS_OCC', 'PURE_STATE_SAT_RAMP',
    'LIVE_COST_ALWAYS', 'REQUIRE_BUS_FOR_ACTION',
    'AUTO_PLACE_DETECTORS', 'DISABLE_PREARM',
]

SAT_RELIEF_CAP_PAXS = 2500.0

# PROACTIVE MODE (2026-10-12): when ON, the decider runs proactively every
# PROACTIVE_TICK_S seconds at EVERY junction in SAT/OVER/JAM stage, using
# timetable-predicted ETAs instead of waiting for bus detection. This is the
# MaxPressure philosophy applied to TSP: act to relieve saturation before the
# bus arrives, not after it's already queued.
#   PROACTIVE_MODE            master toggle (default OFF)
#   PROACTIVE_TICK_S          evaluation interval (seconds)
#   PROACTIVE_MIN_STAGE       minimum stage to trigger: "SAT", "OVER", "JAM"
#   PROACTIVE_MAX_HORIZON_S   only act if predicted ETA <= this horizon
#   PROACTIVE_REQUIRE_TIMETABLE  require timetable data; if False, skip if no schedule
#   PROACTIVE_MAX_ACTIONS_PER_TICK  max junctions that can act per tick (safety)
PROACTIVE_MODE = False
PROACTIVE_TICK_S = 5.0
PROACTIVE_MIN_STAGE = "SAT"          # "SAT", "OVER", or "JAM"
PROACTIVE_MAX_HORIZON_S = 120.0
PROACTIVE_REQUIRE_TIMETABLE = True
PROACTIVE_MAX_ACTIONS_PER_TICK = 5

# PURE_STATE_SAT_RELIEF (2026-10-12): acts on saturation WITHOUT bus detection.
# Runs every PURE_STATE_TICK_S seconds at ALL junctions in SAT/OVER/JAM stage.
# Computes TOTAL passenger saturation = bus_pax (from timetable) + car_pax (from live flow/queue).
# Evaluates actions by total passenger saturation relief:
#   reward = w_bus * (bus_pax_saved + car_pax_relief) - w_cross * cross_cost
# where car_pax_relief = queue_veh * CarOcc * action_magnitude * saturation_ramp.
# This is the pure MaxPressure philosophy for TSP: relieve total passenger saturation
# whether or not a bus is currently detected, using timetable for bus pax predictions.
PURE_STATE_MODE = False
PURE_STATE_TICK_S = 5.0
PURE_STATE_MIN_STAGE = "SAT"          # "SAT", "OVER", "JAM"
PURE_STATE_MAX_HORIZON_S = 120.0
PURE_STATE_REQUIRE_TIMETABLE = True
PURE_STATE_MAX_ACTIONS_PER_TICK = 5
PURE_STATE_CAR_OCC = 1.5             # car occupancy for pax conversion
PURE_STATE_BUS_OCC = 40.0            # bus occupancy (timetable average)
PURE_STATE_SAT_RAMP = 1.0            # ramp factor for saturation credit

# LIVE_COST_ALWAYS (2026-10-13, default ON): make the MEASURED cost a PERMANENT
# floor on BOTH the MAIN approach and the SIDE/cross-street, applied on EVERY
# decision at EVERY intersection -- not only in the empty-detector fallback. The
# intersection can always inspect its live queues; the cost must hold whether the
# action cuts the main or the side.
# Diagnosis (KG NASH_PURE_STATE): the side cost read 0 (pred_side=0) while the
# cross street held 18-507 queued vehicles, and the main cost went hugely NEGATIVE
# (a phantom benefit) under jam -- so bus-phase actions were approved against an
# empty cross street while the main was credited. Both costs must hold. Requires
# AUTO_PLACE_DETECTORS/MEASURED_SIDE_COST for the measured inputs; falls back to
# the analytic cross cost when no measurement is available (so it is safe/no-op
# off-Aimsun).
LIVE_COST_ALWAYS = True
# REQUIRE_BUS_FOR_ACTION (2026-10-13, default OFF): a bus-priority action must
# serve a bus. When ON, any committed action with NO detected bus (veh_id < 0) --
# e.g. the continuous-monitor path firing large insertions at jammed junctions --
# is vetoed to NO_ACTION. 46 of 53 NASH_PURE_STATE insertions had no bus.
REQUIRE_BUS_FOR_ACTION = False

# AUTO_PLACE_DETECTORS (2026-10-13, default ON): derive each junction's
# UpDetList / BusDet / BusCallDetectors / MainSections / SideSections from the
# LIVE signal plan (each phase's signal-group -> turning -> origin sections) +
# the network section->detector map, at launch. This makes every junction's
# detection CONSISTENT and correct-by-construction, independent of hand-entered
# IDs that go stale and silently blank bus detection. Falls back to the
# configured lists when no plan/detectors are readable (e.g. SUMO/HPC, where the
# Aimsun detector API is absent) -- so it is a no-op off-Aimsun.
AUTO_PLACE_DETECTORS = True
# DISABLE_PREARM (2026-10-13, default OFF): skip the corridor coordinator's
# PRE-ARM. Pre-arming an upstream junction for a bus many seconds away adds a
# speculative action on a guessed ETA; the live tracker + monitor can instead act
# now on the current ETA or do nothing and re-check next tick. When ON, the
# coordinator does not pre-arm; local deciders still act on detection.
DISABLE_PREARM = False

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
    'ZIGDOG_MODE',
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
        _dctsp_bxt_qnet_table.clear()
        _poz_action_log.clear()
        _bxt_noaction_baseline.clear()
        _cpdql_reset()
        try:
            _bxt_demand_warmed.clear()
        except Exception:
            pass
        try:
            _bxt_visit_count.clear()
        except Exception:
            pass
    except Exception:
        pass


# ── Q-table disk persistence (2026-10-09, SUMO/HPC only) ─────────────────────
# Aimsun runs every seed in ONE process, so the in-memory table warm-starts
# train->eval for free. The SUMO sweep runs one process per (arm, seed), so the
# trained table must be serialized between the train job and the eval jobs.
# Gated entirely on the run_config global QTABLE_PATH (only the SUMO runner
# sets it) -- Aimsun is unaffected.
_BXT_QTABLE_LOADED_PATH = None


def _sm_sat_relief_paxs(_ctrl, _mag):
    """Passenger-seconds of CREDIT for applying an action of _mag seconds where
    the measured main is over-saturated -- the benefit-side counterpart to the
    main-starvation COST. The reward ledger is otherwise asymmetric (saturation
    only ever appears as a penalty), so relieving a saturated junction without
    helping a specific bus earns nothing and the learned class starves.

    Linear in |mag|, ramping from SAT_RELIEF_MIN_X (no credit below it, so the
    term cannot manufacture action on a FREE main) to full credit at
    SAT_RELIEF_MAX_X, then bounded by SAT_RELIEF_CAP_PAXS. Returns 0.0 when the
    flag is off or no fresh measurement exists.
    """
    if not bool(globals().get('SAT_RELIEF_BONUS', False)):
        return 0.0
    try:
        _snap = _ctrl._flow_stage_snapshot() or {}
        _x = float(_snap.get('main_x', 0.0) or 0.0)
    except Exception:
        return 0.0
    _xmin = float(globals().get('SAT_RELIEF_MIN_X', 0.85) or 0.85)
    # DIAG (2026-10-13): record whether the gate condition is EVER met, so an
    # arm whose relief credit is always 0.0 is visible rather than silent.
    _diag_relief_gate(_ctrl, _x, _xmin, 'gate')
    if _x < _xmin:
        return 0.0
    _xmax = max(_xmin + 1e-6, float(globals().get('SAT_RELIEF_MAX_X', 1.30) or 1.30))
    _ramp = min(1.0, (_x - _xmin) / (_xmax - _xmin))
    try:
        _rate = float(globals().get('SAT_RELIEF_RATE_PAXS', 60.0) or 60.0)
    except Exception:
        _rate = 60.0
    try:
        _cap = float(globals().get('SAT_RELIEF_CAP_PAXS', 2500.0) or 2500.0)
    except Exception:
        _cap = 2500.0
    _out = min(max(0.0, abs(float(_mag)) * _rate * _ramp), _cap)
    _diag_relief_gate(_ctrl, _x, _xmin, 'fired', value=_out)
    return _out


# Objects that hold saturation-term counters (populated by _diag_relief_gate).
# Cleared at the start of every run by reset_mode_flags() so a run's report
# cannot include owners from a previous replication in the same Aimsun session.
_SAT_DIAG_OWNERS = []


def _diag_relief_gate(_ctrl, _x, _xmin, _what, value=0.0):
    """Count how often the saturation relief / starvation gates are consulted and
    how often their condition is actually met (2026-10-13).

    Both terms returned 0.0 on every decision in earlier campaigns because their
    thresholds (main_x >= 0.85, measured queue >= 8 veh) were never reached, so
    the arms came back byte-identical to their controls and the only evidence was
    a diff. These counters make the frequency visible in the run log.
    Counters live on the corridor coordinator (or the controller) so they are
    aggregated across junctions, and are flushed once at run end.

    2026-10-14: each owner is also appended to _SAT_DIAG_OWNERS so that
    _diag_owners() can find it. Without that, sm_sat_term_diag_report() found
    no owner at all and the engine emitted its misleading "SAT_RELIEF_BONUS is
    off" fallback on every run, which masked the real reason (never consulted).
    """
    try:
        if not bool(globals().get('TSP_DIAG_SAT_TERMS', True)):
            return
        _own = getattr(_ctrl, '_corridor_coord', None) or _ctrl
        # Register the owner by IDENTITY (controllers do not define a cheap
        # __eq__; `in` on a list would call it and may be wrong or slow).
        if not any(_o is _own for _o in _SAT_DIAG_OWNERS):
            _SAT_DIAG_OWNERS.append(_own)
            # This owner is NEW to the current run, so its counter dict is stale
            # from a previous replication: the junction controllers are Aimsun
            # objects that outlive the run, and _diag_relief_gate reused the old
            # dict verbatim, so counts accumulated across the whole session. Drop
            # it so this run's [SAT_TERMS] line describes only this run.
            try:
                _own._tsp_sat_term_diag = None
            except Exception:
                pass
        _c = getattr(_own, '_tsp_sat_term_diag', None)
        if not isinstance(_c, dict):
            _c = {'relief_consults': 0, 'relief_fires': 0,
                  'relief_paxs': 0.0, 'relief_x_max': 0.0,
                  'starve_consults': 0, 'starve_fires': 0,
                  'starve_paxs': 0.0, 'starve_q_max': 0.0,
                  'starve_none_meas': 0}
            _own._tsp_sat_term_diag = _c
        if _what == 'gate':
            _c['relief_consults'] += 1
            if float(_x) > float(_c.get('relief_x_max', 0.0)):
                _c['relief_x_max'] = float(_x)
        elif _what == 'fired':
            _c['relief_fires'] += 1
            _c['relief_paxs'] = float(_c.get('relief_paxs', 0.0)) + float(value)
        elif _what == 'starve_none':
            _c['starve_none_meas'] += 1
        elif _what == 'starve_consult':
            _c['starve_consults'] += 1
        elif _what == 'starve_fired':
            _c['starve_fires'] += 1
            _c['starve_paxs'] = float(_c.get('starve_paxs', 0.0)) + float(value)
        elif _what == 'starve_q':
            if float(value) > float(_c.get('starve_q_max', 0.0)):
                _c['starve_q_max'] = float(value)
    except Exception:
        pass


def sm_sat_term_diag_report():
    """One-line summary of the saturation-term counters, for the end-of-run log.
    Returns a human-readable string; empty when diagnostics are off or unset.

    2026-10-14: aggregate across EVERY registered owner. A 12-junction corridor
    may hand each junction's own controller (they do not all share one
    coordinator object), so returning the first owner with counters reported a
    single junction and hid the corridor total -- e.g. "relief 0/2" when 11 of
    the 12 junctions never even consulted the term.
    """
    try:
        _tot = {'rc': 0, 'rf': 0, 'rp': 0.0, 'rx': 0.0,
                'sc': 0, 'sf': 0, 'sp': 0.0, 'sq': 0.0, 'sn': 0}
        _n_own = 0
        for _own in _diag_owners():
            _c = getattr(_own, '_tsp_sat_term_diag', None)
            if not isinstance(_c, dict) or not _c.get('relief_consults'):
                continue
            _n_own += 1
            _tot['rc'] += int(_c.get('relief_consults', 0))
            _tot['rf'] += int(_c.get('relief_fires', 0))
            _tot['rp'] += float(_c.get('relief_paxs', 0.0))
            _tot['rx'] = max(_tot['rx'], float(_c.get('relief_x_max', 0.0)))
            _tot['sc'] += int(_c.get('starve_consults', 0))
            _tot['sf'] += int(_c.get('starve_fires', 0))
            _tot['sp'] += float(_c.get('starve_paxs', 0.0))
            _tot['sq'] = max(_tot['sq'], float(_c.get('starve_q_max', 0.0)))
            _tot['sn'] += int(_c.get('starve_none_meas', 0))
        if _n_own:
            return (
                "[SAT_TERMS] relief %d/%d fired (x_max=%.3f, %.0f pax-s) | "
                "starve %d/%d fired (q_max=%.1f, %.0f pax-s, %d no-measurement) "
                "[owners=%d]"
                % (_tot['rf'], _tot['rc'], _tot['rx'], _tot['rp'],
                   _tot['sf'], _tot['sc'], _tot['sq'], _tot['sp'],
                   _tot['sn'], _n_own))
    except Exception:
        pass
    return ''


def _diag_owners():
    """Candidate objects that may hold the saturation-term counters.

    BUGFIX 2026-10-14: this used to read only the module globals
    _CORR_COORD / corridor_coord / _CORRIDOR_COORD, none of which are ever
    assigned in this module. _diag_relief_gate instead attaches the counter
    dict to whatever object it is handed (getattr(_ctrl, '_corridor_coord')
    or the controller itself), so the counters lived on instances that this
    function never looked at. sm_sat_term_diag_report() therefore always
    returned None and the engine printed its hardcoded fallback
    "[SAT_TERMS] no counters recorded (relief consults=0: SAT_RELIEF_BONUS is
    off)" -- a message that is wrong whenever the real cause is merely that no
    decision ever CONSULTED the term, or that the owner registry was empty.
    It ran on every arm of the 2026-10-13/14 batches, so that line carried no
    information about SAT_RELIEF_BONUS at all.

    Now the owners actually seen by _diag_relief_gate are recorded in
    _SAT_DIAG_OWNERS and reported from there. The legacy module-global
    lookups are kept as a fallback so an external caller that publishes a
    coordinator that way still gets picked up.
    """
    for _o in list(_SAT_DIAG_OWNERS):
        if _o is not None:
            yield _o
    try:
        _g = globals()
        for _k in ('_CORR_COORD', 'corridor_coord', '_CORRIDOR_COORD'):
            _o = _g.get(_k)
            if _o is not None and not any(_o is _s for _s in _SAT_DIAG_OWNERS):
                yield _o
    except Exception:
        pass


def _sm_main_starve_cost_paxs(_ctrl, _mag):
    """Passenger-seconds of MAIN-line delay that an action of _mag seconds risks
    when the through-movements are already saturated. Unlike the cross/side cost
    ledger this prices the streams we are NOT explicitly cutting: EARLY_RED /
    wrong-phase GR on a saturated main truncates the phase serving the main, and
    that harm is invisible to the cross-cost ledger. Uses the measured main-
    approach queue (detector-based, the same basis the Nash mainline state uses),
    not an occupancy proxy. 0 whenever BXT_MAIN_STARVE_GATE is off, the main is
    below saturation, or no fresh measurement exists.

    THRESHOLD BASIS (2026-10-13): BXT_MAIN_STARVE_VEH is a queue-in-vehicles
    threshold and its default of 8.0 sat above this corridor's ENTIRE measured
    distribution (queue_main max 6.0, p95 2.0 over 1725 samples), so the gate
    returned 0.0 on every decision and MARL_STARVE_GATE came back byte-identical
    to MARL_CONT. Two fixes, both opt-in-able:
      * BXT_MAIN_STARVE_X   -- gate on degree-of-saturation (main_x) instead of
        queue length. main_x is now lane-corrected, so 1.0 really means "at
        capacity". Default -1 (off) to preserve old behaviour.
      * BXT_MAIN_STARVE_VEH -- re-scaled default, calibrated to the measured
        distribution rather than a guess.
    """
    if not bool(globals().get('BXT_MAIN_STARVE_GATE', False)):
        return 0.0
    # ── Option A: degree-of-saturation basis ────────────────────────────────
    try:
        _xthr = float(globals().get('BXT_MAIN_STARVE_X', -1.0))
    except Exception:
        _xthr = -1.0
    if _xthr > 0.0:
        try:
            _snap = _ctrl._flow_stage_snapshot() or {}
            _x = float(_snap.get('main_x', 0.0) or 0.0)
        except Exception:
            _x = 0.0
        _diag_relief_gate(_ctrl, _x, _xthr, 'starve_consult')
        _diag_relief_gate(_ctrl, _x, _xthr, 'starve_q', value=_x)
        if _x < _xthr:
            return 0.0
        try:
            _occ = max(0.0, float(globals().get('BXT_MAIN_STARVE_OCC', 1.2)))
            _s = float(globals().get('BXT_MAIN_STARVE_S_PER_VEH', 1.0) or 1.0)
        except Exception:
            _occ, _s = 1.2, 1.0
        # Scale the surcharge by how far PAST the threshold we are, so the term
        # is continuous across the boundary (0 at the threshold).
        _excess = (_x - _xthr) / max(1.0 - _xthr, 1e-6)
        _out = _excess * _occ * _s * 100.0 * max(0.0, float(_mag))
        _diag_relief_gate(_ctrl, _x, _xthr, 'starve_fired', value=_out)
        return _out
    # ── Option B (legacy): measured queue-length basis ─────────────────────
    try:
        _q = _ctrl._measured_main_queue_veh()
    except Exception:
        _diag_relief_gate(_ctrl, 0.0, 0.0, 'starve_none')
        return 0.0
    if _q is None:
        _diag_relief_gate(_ctrl, 0.0, 0.0, 'starve_none')
        return 0.0
    try:
        _q = float(_q)
    except Exception:
        _diag_relief_gate(_ctrl, 0.0, 0.0, 'starve_none')
        return 0.0
    _thr = float(globals().get('BXT_MAIN_STARVE_VEH', 8.0) or 8.0)
    _diag_relief_gate(_ctrl, _q, _thr, 'starve_consult')
    _diag_relief_gate(_ctrl, _q, _thr, 'starve_q', value=_q)
    if _q < _thr:
        return 0.0
    try:
        _occ = max(0.0, float(globals().get('BXT_MAIN_STARVE_OCC', 1.2)))
    except Exception:
        _occ = 1.2
    try:
        _s = float(globals().get('BXT_MAIN_STARVE_S_PER_VEH', 1.0) or 1.0)
    except Exception:
        _s = 1.0
    # Linear in the queue ABOVE saturation (so the term is 0 at the threshold and
    # the gate is continuous across the boundary) and in the action magnitude,
    # since a longer truncation idles the main for longer.
    _out = (_q - _thr) * _occ * _s * max(0.0, float(_mag))
    _diag_relief_gate(_ctrl, _q, _thr, 'starve_fired', value=_out)
    return _out


def bxt_qtable_load(path=None):
    """Merge a previously-saved BXT Q-table into the in-memory table. Returns
    the number of state entries merged (0 when QTABLE_PATH unset / file missing)."""
    global _BXT_QTABLE_LOADED_PATH
    try:
        import os as _os
        import pickle as _pk
    except Exception:
        return 0
    p = str(path or globals().get('QTABLE_PATH', '') or '')
    if not p or _BXT_QTABLE_LOADED_PATH == p:
        return 0
    _BXT_QTABLE_LOADED_PATH = p
    try:
        if not _os.path.isfile(p):
            return 0
        with open(p, 'rb') as _f:
            d = _pk.load(_f)
    except Exception:
        return 0
    n = 0
    try:
        if isinstance(d, dict):
            for _k, _v in d.items():
                if isinstance(_v, dict):
                    _tgt = _dctsp_bxt_q_table.get(_k)
                    if not isinstance(_tgt, dict):
                        _tgt = _dctsp_bxt_q_table[_k] = {}
                    _tgt.update(_v)
                    n += len(_v)
                else:
                    _dctsp_bxt_q_table[_k] = _v
                    n += 1
    except Exception:
        pass
    return n


def bxt_qtable_save(path=None):
    """Atomically serialize the in-memory BXT Q-table to disk. Returns entries
    saved (0 when QTABLE_PATH unset or the write failed)."""
    try:
        import os as _os
        import pickle as _pk
    except Exception:
        return 0
    p = str(path or globals().get('QTABLE_PATH', '') or '')
    if not p:
        return 0
    try:
        n = sum(len(v) for v in _dctsp_bxt_q_table.values()
                if isinstance(v, dict))
    except Exception:
        n = 0
    try:
        _d = _os.path.dirname(p)
        if _d:
            _os.makedirs(_d, exist_ok=True)
        _tmp = p + '.tmp'
        with open(_tmp, 'wb') as _f:
            _pk.dump(_dctsp_bxt_q_table, _f, protocol=_pk.HIGHEST_PROTOCOL)
        _os.replace(_tmp, p)
    except Exception:
        return 0
    return n


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
    # Drop the previous replication's saturation-term counter owners, otherwise
    # the next run's [SAT_TERMS] line reports counters that were never touched
    # in it (owners keep their stale dict from the prior run's last decision).
    del _SAT_DIAG_OWNERS[:]
    return list(MODE_TOGGLES)


# ═══════════════════════════════════════════════════════════════════════════
# ZIGDOG (2026-10-02) -- per-cycle receding-horizon arrivals-on-green (AOG)
# optimizer, driven by the PT timetable + measured demand.
# ═══════════════════════════════════════════════════════════════════════════
def _ins_gr_coord_phase_ok(self, timeSta):
    """True when INS / GREEN_REALLOC may fire (2026-10-03).

    Those actions serve the controller's BusPhase, so they are permitted only
    when BusPhase IS this junction's COORDINATED mainline phase -- the one
    aligned with the UPSTREAM/DOWNSTREAM signals' progression band (engine
    _actuated_coord_phase = the longest fixed phase).  A mismatch on a
    coordinated junction would shove green onto a phase the band does not
    serve and break platoon progression -> reject.  Junctions outside the
    corridor chain, or with an unresolvable plan, are not blocked."""
    if not bool(globals().get('INS_GR_COORD_PHASE_ONLY', True)):
        return True
    try:
        _bp = int(getattr(self, 'BusPhase', 0) or 0)
    except Exception:
        _bp = 0
    if _bp <= 0:
        return False
    _cc = getattr(self, '_corridor_coord', None)
    _cpos = getattr(_cc, 'corridor_pos', None) if _cc is not None else None
    _jid = int(getattr(self, 'node_id', 0) or 0) or int(getattr(self, 'id', -1))
    if not _cpos or _jid not in _cpos:
        return True
    try:
        _cp = int(self._actuated_coord_phase(timeSta) or 0)
    except Exception:
        _cp = 0
    if _cp <= 0:
        return True
    return _bp == _cp


def _zigdog_cycle_init(self, time, current_phase, cycle_id, cycle_s):
    """Per-junction cycle bookkeeping for the ZIGDOG guard (2026-10-03).

    Tracks, per signal cycle: the phases actually served (order preserved by
    construction -- ER/GE only shift seconds, they never skip a phase), the
    seconds of Early Red / green extension taken, and the number of ERs."""
    _cyc = getattr(self, '_zigdog_cyc', None)
    if _cyc is None or _cyc.get('cycle') != cycle_id:
        _cyc = {'cycle': cycle_id, 'er_s': 0.0, 'ge_s': 0.0, 'er_n': 0,
                'ge_n': 0, 'act_n': 0, 'seen': set()}
        self._zigdog_cyc = _cyc
    try:
        if int(current_phase or 0) > 0:
            _cyc['seen'].add(int(current_phase))
    except Exception:
        pass
    return _cyc


def _zigdog_cycle_gate(self, time, cyc, atype, param, rem_green):
    """Enforce the cycle constraints for one candidate action.

    Returns (ok, reason). Rules:
      * ER: at most ZIGDOG_MAX_ER_PER_CYCLE per cycle; the current phase must
        have run >= ZIGDOG_MIN_PHASE_GREEN_S; projected cycle length
        C + ge - er - param >= MIN_CYCLE.
      * GE/INS: projected cycle C + ge + param - er <= MAX_CYCLE (GE is also
        clamped by the recoverability budget before it gets here).
      * Everything else (HOLD): always allowed."""
    _cfg = getattr(self, 'config', {}) or {}
    _C = 0.0
    try:
        _C = float(getattr(self, 'CycleLength', 0.0) or 0.0)
    except Exception:
        _C = 0.0
    if _C <= 0.0:
        try:
            _C = float(_cfg.get('CycleTime', 135.0) or 135.0)
        except Exception:
            _C = 135.0
    _min_cyc = float(globals().get('ZIGDOG_MIN_CYCLE_S', 0.0) or 0.0) or 0.85 * _C
    _max_cyc = float(globals().get('ZIGDOG_MAX_CYCLE_S', 0.0) or 0.0) or 1.15 * _C
    _max_er = int(globals().get('ZIGDOG_MAX_ER_PER_CYCLE', 1) or 0)
    _min_g = float(globals().get('ZIGDOG_MIN_PHASE_GREEN_S', 6.0) or 6.0)
    _p = max(0.0, float(param or 0.0))
    if atype in ('EARLY_RED', 'ER'):
        if _max_er <= 0:
            return False, 'ER_DISABLED'
        if int(cyc.get('er_n', 0)) >= _max_er:
            return False, 'ER_BUDGET'
        try:
            _el = max(0.0, float(time) - float(_eci_call('ECIGetStartingTimePhase', self.node_id)))
        except Exception:
            _el = _min_g
        if _el < _min_g:
            return False, 'MIN_GREEN'
        _proj = _C + cyc.get('ge_s', 0.0) - cyc.get('er_s', 0.0) - _p
        if _proj < _min_cyc:
            return False, 'MIN_CYCLE'
        return True, ''
    # Per-intersection ACTION BUDGET (2026-10-03): cap how many interventions
    # a junction may fire per cycle so repeated GE_5 chains (observed: six in a
    # row) and mixed sprees cannot make the plan unreliable. Counted from the
    # EFFECTIVE actions committed (see _zigdog_cycle_commit).
    if bool(globals().get('ZIGDOG_ACTION_BUDGET', True)):
        _max_act = int(globals().get('ZIGDOG_MAX_ACTIONS_PER_CYCLE', 3) or 0)
        if _max_act > 0 and int(cyc.get('act_n', 0)) >= _max_act:
            return False, 'ACTION_BUDGET'
        _max_ge = int(globals().get('ZIGDOG_MAX_GE_PER_CYCLE', 2) or 0)
        if (atype in ('GE', 'GREEN_REALLOC', 'INS', 'INS_POST', 'INS_PRETERM')
                and _max_ge > 0 and int(cyc.get('ge_n', 0)) >= _max_ge):
            return False, 'GE_BUDGET'
    if atype in ('GE', 'GREEN_REALLOC', 'INS', 'INS_POST', 'INS_PRETERM'):
        _proj = _C + cyc.get('ge_s', 0.0) + _p - cyc.get('er_s', 0.0)
        if _proj > _max_cyc:
            return False, 'MAX_CYCLE'
        return True, ''
    return True, ''


def _zigdog_cycle_commit(self, cyc, atype, param):
    """Account the chosen action against the cycle budget."""
    try:
        _p = max(0.0, float(param or 0.0))
        if atype in ('EARLY_RED', 'ER'):
            cyc['er_s'] = cyc.get('er_s', 0.0) + _p
            cyc['er_n'] = int(cyc.get('er_n', 0)) + 1
            cyc['act_n'] = int(cyc.get('act_n', 0)) + 1
        elif atype in ('GE', 'GREEN_REALLOC', 'INS', 'INS_POST', 'INS_PRETERM'):
            cyc['ge_s'] = cyc.get('ge_s', 0.0) + _p
            cyc['ge_n'] = int(cyc.get('ge_n', 0)) + 1
            cyc['act_n'] = int(cyc.get('act_n', 0)) + 1
    except Exception:
        pass


def _zigdog_measured_cross_cost(self, action_s):
    """Queue-first MEASURED cross cost for the ZIGDOG scorer (2026-10-03).

    For LOW side flow the standing queue is the whole cost of an extra red,
    so price the LIVE queue directly -- no warm-up, no detector feed, no
    demand seed:
        queue   = n_live * action_s * CarOcc * spill_severity
        arrival = q_live/3600 * action_s^2 / 2 * CarOcc
                  (only when q_live >= ZIGDOG_MEASURED_CROSS_ARRIVAL_VPH)
    n_live = AKIVehStateGetNbVehiclesSection (shim-backed on SUMO); q_live =
    the controller's MEASURED section flow (allow_seed=False inside). Returns
    pax*s, 0.0 when nothing is live/measured."""
    action_s = max(0.0, float(action_s or 0.0))
    if action_s <= 0.0:
        return 0.0
    _car_occ = max(1.0, float(getattr(self, 'CarOcc', 1.6) or 1.6))
    _kjam = max(1.0, float(getattr(self, 'JamDensity', 150.0) or 150.0))
    _thr = max(0.0, float(globals().get(
        'ZIGDOG_MEASURED_CROSS_ARRIVAL_VPH', 150.0) or 150.0))
    _tot = 0.0
    try:
        _sat_vps = max(0.05, float(getattr(
            self, 'SaturationFlow', 1800.0) or 1800.0) / 3600.0)
    except Exception:
        _sat_vps = 0.5
    for _ss in (self._get_side_sections() or []):
        try:
            _n = max(0, int(_eci_call('AKIVehStateGetNbVehiclesSection', int(_ss), False) or 0))
        except Exception:
            _n = 0
        try:
            _q = float(self._measured_section_flow_vph(int(_ss)) or 0.0)
        except Exception:
            _q = 0.0
        _sev = 1.0
        try:
            _lanes = 1
            _si = _eci_call('AKIInfNetGetSectionANGInf', int(_ss))
            if getattr(_si, 'report', -1) >= 0:
                _lanes = max(int(getattr(_si, 'nbCentralLanes', 1))
                             + int(getattr(_si, 'nbSideLanes', 0)), 1)
            _cap = max(1.0, _lanes * (float(globals().get(
                'SIDE_QUEUE_ZONE_M', 60.0)) / 1000.0) * _kjam)
            _sev = 1.0 + 3.0 * min(1.0, _n / _cap)
        except Exception:
            _sev = 1.0
        # 2026-10-09: MARGINAL costing. Charging the whole standing stock
        # bills the action for delay that happens regardless (in JAM this
        # priced every candidate at millions -> permanent NO_ACTION). Only
        # the dischargeable part (sat-flow x action_s) could actually have
        # cleared during the action, so only that part is charged.
        try:
            _dischargeable = _sat_vps * max(1, _lanes) * action_s
        except Exception:
            _dischargeable = float(_n)
        _charge_n = min(float(_n), max(0.0, _dischargeable))
        _tot += _charge_n * action_s * _car_occ * _sev
        if _q >= _thr:
            _tot += (_q / 3600.0) * action_s * action_s * 0.5 * _car_occ
    return max(0.0, _tot)


def _zigdog_fleet(self, time, extra=None):
    """Every bus predicted at THIS junction inside the re-optimisation
    horizon, with its schedule lateness (2026-10-02).

    Uses the corridor coordinator's Kalman trackers + _eta_s_for so the
    per-cycle re-optimisation sees ALL buses, not only the one that triggered
    the decision; the caller weights each by its lateness (catch-up boost).
    Returns [(vid, eta_s, late_s, occ)].  `extra`=(vid, eta, late, occ) is the
    calling bus and is always included even without a tracker."""
    _jid = int(getattr(self, 'node_id', 0) or 0) or int(getattr(self, 'id', -1))
    _occ = max(1.0, float(getattr(self, 'BusOcc', 40.0) or 40.0))
    _hz = float(globals().get('ZIGDOG_HORIZON_S', 180.0) or 180.0)
    # THROTTLE (2026-10-12): the fleet forecast is re-used across the ZIGDOG
    # solver's many candidate evaluations (and across phase-states in a cycle);
    # recomputing the full Kalman-tracker sweep every call dominated the solve.
    # Cache it on self for ZIGDOG_FLEET_TTL_S seconds -- ETAs barely move in 5 s.
    _ttl = float(globals().get('ZIGDOG_FLEET_TTL_S', 5.0) or 0.0)
    if _ttl > 0.0:
        _fc = getattr(self, '_zigdog_fleet_cache', None)
        if _fc is not None and 0.0 <= (float(time) - _fc[0]) < _ttl:
            return list(_fc[1])
    _seen = {}
    _cc = getattr(self, '_corridor_coord', None)
    _trk = getattr(_cc, '_trackers', None) if _cc is not None else None
    _cpos = getattr(_cc, 'corridor_pos', None) if _cc is not None else None
    if _trk and _cpos:
        _tpos = _cpos.get(_jid)
        for _vid in list(_trk.keys()):
            try:
                _tobj = _trk.get(int(_vid))
                if _tobj is None or _tpos is None:
                    continue
                # Same estimator as engine._eta_s_for: tracker.eta() gives the
                # absolute arrival time at the junction's corridor position.
                _eta = max(0.0, float(_tobj.eta(float(_tpos),
                                                float(time))) - float(time))
            except Exception:
                continue
            if float(_eta) < -5.0 or float(_eta) > _hz:
                continue
            try:
                _late = float(self._bus_lateness_for(int(_vid)))
            except Exception:
                _late = 0.0
            _seen[int(_vid)] = (max(0.0, float(_eta)), max(0.0, _late), _occ)
    if extra is not None:
        try:
            _ev, _ee, _el, _eo = extra
            if int(_ev or -1) >= 0:
                _seen.setdefault(int(_ev), (max(0.0, float(_ee)),
                                            max(0.0, float(_el)),
                                            max(1.0, float(_eo or _occ))))
            elif not _seen:
                _seen[-1] = (max(0.0, float(_ee)), max(0.0, float(_el)),
                             max(1.0, float(_eo or _occ)))
        except Exception:
            pass
    _fleet = [(int(_v), _e, _l, _o) for _v, (_e, _l, _o) in _seen.items()]
    # CAP (2026-10-12): the fleet AOG term AND the DP-pathway rollout are
    # evaluated PER candidate PER solver iteration, so an unbounded fleet makes
    # each ZIGDOG solve scale with the live bus count. Keep only the most
    # decision-relevant buses -- LATEST first (biggest catch-up boost), then
    # NEAREST -- bounded by ZIGDOG_FLEET_MAX. The calling bus is already in.
    _fmax = int(globals().get('ZIGDOG_FLEET_MAX', 6) or 0)
    if _fmax > 0 and len(_fleet) > _fmax:
        _fleet.sort(key=lambda t: (-t[2], t[1]))      # late desc, eta asc
        _fleet = _fleet[:_fmax]
    if _ttl > 0.0:
        try:
            self._zigdog_fleet_cache = (float(time), list(_fleet))
        except Exception:
            pass
    return _fleet


def _zigdog_cap_seeds(seeds, n):
    """Bound a magnitude-solver seed list to at most n evenly-spaced values
    (ZIGDOG_MAX_SEEDS), always keeping the endpoints (2026-10-12). ZIGDOG solves
    the time per family with DE refinement, so a dense 1 s-resolution seed scan
    only multiplies the per-seed fleet+DP cost for marginal coverage -- DE still
    finds the optimum between the kept seeds."""
    try:
        _s = sorted({round(float(x), 2) for x in (seeds or [])})
    except Exception:
        return list(seeds or [])
    if n <= 0 or len(_s) <= n:
        return _s
    if n == 1:
        return [_s[len(_s) // 2]]
    _idx = sorted({int(round(i * (len(_s) - 1) / (n - 1))) for i in range(n)})
    return [_s[i] for i in _idx]


def _zigdog_neighbor_windows(self, timeSta, depth, cycle_s):
    """Live signal windows of the ADJACENT downstream neighbour (2026-10-03).

    The future prediction is LOCAL: to value an action only the neighbour
    junction's state is needed -- its current phase, remaining green and the
    bus phase it will serve -- not the whole corridor. Returns
    [(t_start_from_now, duration_s, is_busphase), ...] starting at the
    neighbour's CURRENT phase (first window keeps its remaining green), then
    nominal durations. [] when unresolved (DP then falls back to this
    junction's nominal phases). Never raises."""
    try:
        _nbrs = _bxt_neighbor_jcts(self)
        if not _nbrs:
            return []
        _me = int(getattr(self, 'id', 0) or 0)
        _cc = getattr(self, '_corridor_coord', None)
        _pos = getattr(_cc, 'corridor_pos', None) if _cc is not None else None
        if _pos and _me in _pos:
            _p0 = float(_pos.get(_me, 0.0))
            _up = [j for j in _nbrs if float(_pos.get(int(j), 0.0)) > _p0]
            _dn = [j for j in _nbrs if float(_pos.get(int(j), 0.0)) < _p0]
            _pick = (_up[0] if _up else (_dn[-1] if _dn else _nbrs[0]))
        else:
            _pick = _nbrs[0]
        _nid = int(_pick)
        # neighbour's bus phase (which phase serves transit) via engine registry
        _nb_busph = 0
        try:
            import sys as _sys
            _eng = _sys.modules.get('shared_tsp_engine.engine')
            _ctrls = getattr(_eng, 'controllers', None) if _eng else None
            _nctrl = (_ctrls or {}).get(_nid)
            if _nctrl is not None:
                _nb_busph = int(getattr(_nctrl, 'BusPhase', 0) or 0)
        except Exception:
            _nb_busph = 0
        try:
            _n_ph = int(_eci_call('ECIGetNumberofPhases', _nid))
        except Exception:
            try:
                _n_ph = int(_eci_call('ECIGetNumberPhases', _nid))
            except Exception:
                _n_ph = 0
        if _n_ph <= 0:
            return []
        _cph = int(_eci_call('ECIGetCurrentPhase', _nid) or 1)
        _pst = float(_eci_call('ECIGetStartingTimePhase', _nid) or 0.0)
        try:
            _now = float(_eci_call('AKIGetCurrentSimulationTime', ))
        except Exception:
            _now = _pst
        _out = []
        _t0 = 0.0
        for _k in range(max(1, int(depth))):
            _ph = ((_cph - 1 + _k) % _n_ph) + 1
            try:
                _d = float(_eci_call('GetPhaseDuration', _nid, _ph, timeSta) or 0.0)
            except Exception:
                _d = 0.0
            if _k == 0:
                if _d > 0.0:
                    _d = max(0.0, _d - (_now - _pst))
                else:
                    _d = 0.0
            elif _d <= 0.0:
                _d = max(20.0, float(cycle_s) / max(1, _n_ph))
            _out.append((_t0, _d, 1 if (int(_ph) == _nb_busph > 0) else 0))
            _t0 += _d
        return _out
    except Exception:
        return []


def _zigdog_queue_release_pred(self, timeSta, cur_phase=None, rem_green=None):
    """Per-phase RED-approach queue + NO_ACTION release-time prediction.

    Grounded in the Aimsun microsimulation discharge model: a standing queue
    releases after its remaining red + startup lost time + discharge time at
    the saturation flow (Q / (sat_per_lane x lanes)), i.e. startup headway +
    saturation headway + shockwave clearance. Returns
    {'cur','rem_green','phases': {ph:(Q_veh, lanes, t_green_s, t_release_s)},
     'other_q_paxs': sum_{p != cur} Q_p x CarOcc} -- the pax-seconds waiting on
    every NON-serving phase, which any schedule shift re-prices. Logs a
    throttled [QUEUEREL] line so the prediction is observable. Never raises."""
    out = {'cur': 0, 'rem_green': 0.0, 'phases': {}, 'other_q_paxs': 0.0}
    try:
        try:
            _now = float(_eci_call('AKIGetCurrentSimulationTime', ))
        except Exception:
            _now = 0.0
        try:
            _cur = int(cur_phase) if cur_phase else int(
                _eci_call('ECIGetCurrentPhase', self.node_id))
        except Exception:
            _cur = int(cur_phase or 0)
        try:
            _pst = float(_eci_call('ECIGetStartingTimePhase', self.node_id))
        except Exception:
            _pst = _now
        try:
            _n_ph = max(1, int(len(getattr(self, 'phase_list', []) or [])))
        except Exception:
            _n_ph = 4
        _sat = 1800.0
        _lost = 2.0
        try:
            _cfg = getattr(self, 'config', {}) or {}
            _sat = float(_cfg.get('SaturationFlow', 1800.0) or 1800.0)
            _lost = float(_cfg.get('LostTime', 2.0) or 2.0)
        except Exception:
            pass
        _sat_s = max(0.05, _sat / 3600.0)
        try:
            _psi = self._phase_origin_sections() or {}
        except Exception:
            _psi = {}
        _occ = max(1.0, float(getattr(self, 'CarOcc', 1.2) or 1.2))
        _qs_kmh = float(globals().get('MICRO_QUEUE_SPEED_KMH', 5.0) or 5.0)
        # Intergreen (amber + clearance) BEFORE each phase turns green --
        # factored in so the predicted green-start / release time reflects the
        # real delay before an action actually takes effect.
        _inter = float(globals().get('ZIGDOG_INTERGREEN_S',
                                     globals().get('PLAN_INTERGREEN_S', 4.0)) or 0.0)
        _t0 = 0.0
        for _k in range(_n_ph):
            _ph = ((_cur - 1 + _k) % _n_ph) + 1
            try:
                _d = float(_eci_call('GetPhaseDuration', self.node_id, _ph, timeSta) or 0.0)
            except Exception:
                _d = 0.0
            if _d <= 0.0:
                _d = 30.0
            if _k == 0:
                if rem_green is not None:
                    _rem = max(0.0, float(rem_green))
                else:
                    _rem = max(0.0, _d - (_now - _pst))
                _t_green = 0.0
            else:
                _rem = _d
                _t_green = _t0
            _t0 += (_rem if _k == 0 else _d) + _inter
            _secs = []
            try:
                _secs = list(_psi.get(_ph) or [])
            except Exception:
                _secs = []
            _q = None
            try:
                _q = self._measured_sections_queue_veh(_secs)
            except Exception:
                _q = None
            if _q is None:
                _q = 0.0
                try:
                    for _s2 in _secs:
                        _n2 = int(_eci_call('AKIVehStateGetNbVehiclesSection', int(_s2), True) or 0)
                        for _i2 in range(_n2):
                            _v2 = _eci_call('AKIVehStateGetVehicleInfSection', int(_s2), _i2)
                            if float(getattr(_v2, 'CurrentSpeed', 99.0) or 99.0) <= _qs_kmh:
                                _q += 1.0
                except Exception:
                    pass
            # RELIABLE lane count (2026-10-04): Aimsun section info first
            # (central+side lanes), _sec_profile fallback, else 1.
            _lanes = 0
            try:
                for _s3 in _secs:
                    _ln3 = 0
                    try:
                        _si3 = _eci_call('AKIInfNetGetSectionANGInf', int(_s3))
                        if getattr(_si3, 'report', -1) >= 0:
                            _ln3 = max(int(getattr(_si3, 'nbCentralLanes', 0) or 0)
                                       + int(getattr(_si3, 'nbSideLanes', 0) or 0), 1)
                    except Exception:
                        _ln3 = 0
                    if _ln3 <= 0:
                        _pm = getattr(self, '_sec_profile', {}) or {}
                        _ln3 = int((_pm.get(_s3) or {}).get('n_lanes', 1) or 1)
                    _lanes += max(1, _ln3)
            except Exception:
                _lanes = 0
            _lanes = max(1, _lanes or 1)
            _disch = float(_q) / max(0.05, _sat_s * _lanes)
            # SHOCKWAVE CLEARING CORRECTION (2026-10-04): the last queued
            # vehicle discharges Q/(sat x lanes) after green, but it still has
            # to travel the queue length to reach the stop line -- the release
            # time must include that propagation, else the prediction is
            # systematically early (the "portion action actually discharging
            # properly" requirement).
            if bool(globals().get('ZIGDOG_SHOCKWAVE_CORRECT', True)) and _q > 0.0:
                try:
                    _kjam = max(1.0, float(getattr(self, 'JamDensity', 150.0) or 150.0))
                    _vfree = max(2.0, float(globals().get(
                        'ZIGDOG_SHOCKWAVE_VFREEM_S', 11.0) or 11.0))
                    _qlen = float(_q) / (_kjam * _lanes) * 1000.0
                    _disch += _qlen / _vfree
                except Exception:
                    pass
            _t_rel = _t_green + _lost + _disch
            out['phases'][_ph] = (float(_q), _lanes, _t_green, _t_rel)
            if _k == 0:
                out['cur'] = _cur
                out['rem_green'] = _rem
            else:
                out['other_q_paxs'] += float(_q) * _occ
        try:
            _iv = float(globals().get('ZIGDOG_QUEUE_LOG_S', 60.0) or 0.0)
            if _iv > 0.0 and (_now - float(getattr(self, '_qrel_log_t', -1e9))) >= _iv:
                self._qrel_log_t = _now
                _parts = " ".join(
                    "ph%d:Q=%.0f,T=%.0fs" % (p, v[0], v[3])
                    for p, v in sorted(out['phases'].items()))
                _log_func(self, f"[QUEUEREL] inter={getattr(self, 'id', '?')} "
                                f"t={_now:.0f} cur={_cur} rem={out['rem_green']:.0f}s "
                                f"other_q_paxs={out['other_q_paxs']:.0f} {_parts}",
                          force=True)
        except Exception:
            pass
    except Exception:
        pass
    # ── OBSERVED-vs-EXPECTED accuracy (2026-10-04) ─────────────────────
    # Tracks each phase's predicted queue / green-start against what actually
    # happens, so prediction reliability is MEASURED, not assumed:
    #   [QUEUEREL_ACC] ph=.. GREEN   pred_t.. obs_q vs pred_q
    #   [QUEUEREL_ACC] ph=.. GREEN_END  q_start vs obs residual
    if bool(globals().get('ZIGDOG_QUEUE_ACC', True)):
        try:
            _trk = getattr(self, '_qrel_track', None)
            if _trk is None:
                _trk = self._qrel_track = {}
            _curnow = 0
            try:
                _curnow = int(out.get('cur') or 0)
            except Exception:
                _curnow = 0
            if _curnow <= 0:
                try:
                    _curnow = int(_eci_call('ECIGetCurrentPhase', self.node_id))
                except Exception:
                    _curnow = 0
            try:
                _nowt = float(_eci_call('AKIGetCurrentSimulationTime', ))
            except Exception:
                _nowt = 0.0
            for _ph2, _v2 in (out.get('phases') or {}).items():
                _q2 = float(_v2[0])
                _tg2 = float(_v2[2])
                _ent2 = _trk.get(_ph2)
                if _ph2 == _curnow:
                    if _ent2 is None or not _ent2.get('green_seen'):
                        if _ent2 is None:
                            _ent2 = {}
                            _trk[_ph2] = _ent2
                        _pred_t = float(_ent2.get('t_green_pred', _nowt))
                        _pred_q = float(_ent2.get('q_pred', _q2))
                        _ent2['green_seen'] = True
                        _ent2['t_green_obs'] = _nowt
                        _ent2['q_at_green'] = _q2
                        _log_func(self, f"[QUEUEREL_ACC] inter={getattr(self, 'id', '?')} "
                                        f"ph={_ph2} GREEN t={_nowt:.0f}s "
                                        f"pred_t={_pred_t:.0f}s err_t={_nowt - _pred_t:+.0f}s "
                                        f"obs_q={_q2:.0f} pred_q={_pred_q:.0f}", force=True)
                else:
                    if _ent2 is not None:
                        _ent2['q_pred'] = _q2
                        _ent2['t_green_pred'] = _nowt + _tg2
                        if _ent2.get('green_seen') and not _ent2.get('end_seen'):
                            _ent2['end_seen'] = True
                            _geb = max(0.0, _nowt - float(_ent2.get('t_green_obs', _nowt)))
                            _log_func(self, f"[QUEUEREL_ACC] inter={getattr(self, 'id', '?')} "
                                            f"ph={_ph2} GREEN_END t={_nowt:.0f}s "
                                            f"q_start={float(_ent2.get('q_at_green', 0.0)):.0f} "
                                            f"obs_q_end={_q2:.0f} green_elapsed={_geb:.0f}s",
                                      force=True)
        except Exception:
            pass
    return out


def _zigdog_dp_pathways(self, fleet, cur_phase, rem_green, cycle_s, bus_w,
                        timeSta=0.0):
    """Beam-bounded DP over the upcoming phase windows (2026-10-03).

    The future prediction must not expand an unbounded tree: this walks the
    NEXT ZIGDOG_DP_DEPTH phases (cyclic from cur_phase; the current one keeps
    its remaining green) and, per layer, keeps only the best ZIGDOG_DP_BEAM
    pathways (HOLD / +GE-cap / -ER-cap durations). Value = fleet AOG
    (occupancy x lateness boost) of buses that land on green inside each
    window -- i.e. the DP GATES how many future pathways get expanded
    (BEAM x DEPTH) and values the best one. Never raises, 0.0 when disabled."""
    try:
        if not bool(globals().get('ZIGDOG_DP_ENABLE', True)) or not fleet:
            return 0.0
        _beam = max(1, int(globals().get('ZIGDOG_DP_BEAM', 2) or 2))
        _depth = max(1, int(globals().get('ZIGDOG_DP_DEPTH', 4) or 4))
        try:
            _n_ph = max(1, int(len(getattr(self, 'phase_list', []) or [])))
        except Exception:
            _n_ph = 4
        try:
            _ph0 = max(1, int(cur_phase))
        except Exception:
            _ph0 = 1
        _ge_cap = max(0.0, float(globals().get('ZIGDOG_MAX_GE_S', 15.0) or 15.0))
        _er_cap = max(0.0, float(globals().get('ZIGDOG_MAX_ER_S', 15.0) or 15.0))
        _min_g = max(0.0, float(globals().get(
            'ZIGDOG_MIN_PHASE_GREEN_S', 6.0) or 6.0))
        _w = max(0.0, float(bus_w or 0.0))
        _fs = sorted(fleet, key=lambda z: float(z[1]))
        # ── neighbour-state DP (2026-10-03) ───────────────────────────────
        # Future layers use the ADJACENT junction's live windows; a bus served
        # in THIS junction's window earns a neighbour credit when it reaches
        # the neighbour during one of the neighbour's bus-phase windows.
        _nb_travel = max(0.0, float(globals().get(
            'ZIGDOG_DP_NEIGHBOR_TRAVEL_S', 30.0) or 0.0))
        _nw = max(0.0, float(globals().get('ZIGDOG_DP_NEIGHBOR_W', 0.5) or 0.0))
        _nwin = []
        _nbus_win = []
        if bool(globals().get('ZIGDOG_DP_NEIGHBORS', True)) and _nw > 0.0:
            _nwin = _zigdog_neighbor_windows(self, timeSta, _depth, cycle_s)
            _nbus_win = [w for w in _nwin if w[2]]
        _paths = [(0.0, 0.0, 0)]
        for _k in range(_depth):
            _ph = ((_ph0 - 1 + _k) % _n_ph) + 1
            if _k == 0:
                _d0 = max(0.0, float(rem_green))
            else:
                # DP SOUNDNESS (2026-10-04, finding #3): future layers are
                # THIS junction's own nominal phases. The neighbour's live
                # windows are used ONLY for the arrival credit below -- they
                # are NOT this junction's service schedule (mixing two
                # junctions' plans made the future value unsound).
                try:
                    _d0 = float(_eci_call('GetPhaseDuration', self.node_id, _ph, timeSta)
                                or 0.0)
                except Exception:
                    _d0 = 0.0
                if _d0 <= 0.0:
                    _d0 = max(20.0, float(cycle_s) / max(1, _n_ph))
            _cands = [(_d0, 1.0)]
            if _k == 0 and _d0 > 0.0:
                # DP SOUNDNESS (2026-10-04): candidates must be EXECUTABLE --
                # the ER option is clamped by the band cap the executor will
                # enforce, so the future value is not inflated by actions the
                # cycle/band gates would reject.
                _er_dp = min(_er_cap, max(0.0, float(globals().get(
                    'ZIGDOG_BAND_MAX_ER_S', 5.0) or 0.0)) or _er_cap)
                if _d0 + _ge_cap > _min_g:
                    _cands.append((_d0 + _ge_cap, 1.0))
                if _d0 - _er_dp >= _min_g:
                    _cands.append((max(_min_g, _d0 - _er_dp), 1.0))
            _new = []
            for _v, _t0, _ci in _paths:
                for _d, _cw in _cands:
                    _v2 = _v
                    _ci2 = _ci
                    for (_bv, _be, _bl, _bo) in _fs[_ci2:]:
                        if float(_be) < _t0:
                            _ci2 += 1
                            continue
                        if float(_be) >= _t0 + _d:
                            break
                        _fb = 1.0 + min(1.0, max(0.0, float(_bl)) / 120.0)
                        # DP SOUNDNESS (2026-10-04): FUTURE-only value -- the
                        # current window's fleet capture is already priced in
                        # the base AOG/surplus term; crediting it here again
                        # double-counted it (and ER's chain-tail added a third).
                        # Layer-0 buses are still CONSUMED (ci advances) so the
                        # future layers do not re-credit them.
                        if _k > 0:
                            _v2 += _w * float(_bo) * _fb * _cw
                        if _k == 0 and _nbus_win:
                            _arr = float(_be) + _nb_travel
                            for (_w0, _wd, _wb) in _nbus_win:
                                if _wb and _w0 <= _arr < _w0 + _wd:
                                    _v2 += _nw * float(_bo) * _fb
                                    break
                        _ci2 += 1
                    _new.append((_v2, _t0 + _d, _ci2))
            _new.sort(key=lambda z: z[0], reverse=True)
            _paths = _new[:_beam]
        return float(_paths[0][0]) if _paths else 0.0
    except Exception:
        return 0.0


def dctsp_zigdog(self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
                 no_act_delay, sigma_in, remaining_red_s=0.0):
    """ZIGDOG: schedule-driven AOG optimizer with a ONE-CYCLE receding horizon.

    At every cycle boundary the junction re-solves the next cycle's phase
    service (HOLD / EXTEND(GE) / END_EARLY(ER) and their seconds) to maximise
    the EXPECTED arrivals-on-green of the buses predicted to reach it inside
    that cycle, using the timetable ETA (bus_eta_s + the live schedule
    deviation sigma_in) and the MEASURED demands (the shared cross/queue
    machinery).  Between boundaries the choice is CACHED and replayed, so the
    junction runs one coherent plan per cycle; at the next boundary it
    re-optimises with fresh measurements and updated bus ETAs.  Realisable by
    construction: the same GE/ER families the corridor decider uses, bounded
    by the recoverability budget so the coordinated offset cannot drift.

    Objective per candidate =
        ZIGDOG_BUS_W * AOG_term + ZIGDOG_CAR_W * corridor_surplus - cross_cost
    where AOG_term = +BusOcc*late_boost when the bus's ETA lands inside the
    green window the candidate creates, minus the shortfall fraction when it
    does not (the bus eats another red).  Returns the standard decider
    contract (best_type, best_param, best_r, best_r_delta, best_so, best_tp,
    rows)."""
    r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
        self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
    rows = [('NO_ACTION', 0.0, r_na, so_na, tp_na, bps_na, cpc_na, nsd_na,
             std_na)]

    _wrong = (int(current_phase) != int(getattr(self, 'BusPhase',
                                                current_phase)))
    _occ = max(1.0, float(getattr(self, 'BusOcc', 40.0) or 40.0))
    _eta = max(0.0, float(bus_eta_s or 0.0))
    _late = max(0.0, float(sigma_in or 0.0))
    _boost = 1.0 + min(1.0, _late / max(
        1.0, float(globals().get('ZIGDOG_LATE_BOOST_S', 120.0) or 120.0)))

    # ── cycle horizon: cache the plan, re-solve at every new cycle ─────────
    _cycle_s = float(globals().get('ZIGDOG_CYCLE_S', 0.0) or 0.0)
    if _cycle_s <= 0.0:
        try:
            _cycle_s = float(getattr(self, 'CycleLength', 0.0) or 0.0)
        except Exception:
            _cycle_s = 0.0
    if _cycle_s <= 0.0:
        _cycle_s = 120.0
    _cycle_id = int(float(time) // max(1.0, _cycle_s))
    # ── phase-binary STATE (ZIGDOG_STATE_MODE='phase', default) ───────────
    # The state is ONLY which phases are green at this junction: one bit per
    # phase (4 phases -> 4 states per junction, 48 across a 12-signal
    # corridor). The per-cycle cache is keyed by (cycle, state), so each cycle
    # re-optimises each phase-state once. 'composite' restores the old
    # (bus, phase) key for A/B.
    _state_mode = str(globals().get('ZIGDOG_STATE_MODE', 'phase')
                      or 'phase').lower()
    if _state_mode == 'composite':
        _state = (int(veh_id or -1), int(current_phase))
    else:
        try:
            _n_ph = max(1, int(len(getattr(self, 'phase_list', []) or [])))
        except Exception:
            _n_ph = 4
        _state = 1 << (max(0, min(int(current_phase) - 1, _n_ph - 1)))
    _key = _state
    _plan = getattr(self, '_zigdog_plan', None)
    if (_plan and _plan.get('cycle') == _cycle_id
            and _plan.get('key') == _key):
        _c = _plan['choice']
        return (_c[0], _c[1], _plan['surplus'], _plan['surplus'],
                _plan['so'], _plan['tp'], _plan['rows'])

    try:
        _rem_green = float(self._current_green_remaining_s(time, timeSta) or 0.0)
    except Exception:
        _rem_green = 0.0

    _ge_grid = [float(x) for x in (globals().get('GE_DURATIONS_S')
                                   or [5.0, 10.0, 15.0])]
    _er_grid = [float(x) for x in (globals().get('ER_DURATIONS_S')
                                   or [10.0, 20.0, 30.0])]
    _ins_grid = [float(x) for x in (globals().get('INS_DURATIONS_S')
                                    or [10.0, 15.0, 20.0])]
    _gr_grid = [float(x) for x in (globals().get('GR_DURATIONS_S')
                                   or [5.0, 10.0, 15.0])]
    _ge_cap = min(max(_ge_grid),
                  float(globals().get('ZIGDOG_MAX_GE_S', 15.0) or 15.0))
    _er_cap = min(max(_er_grid),
                  float(globals().get('ZIGDOG_MAX_ER_S', 10.0) or 0.0))
    # 2026-10-03: ER can NEVER exceed the current green LEFT (you cannot cut
    # more than remains) and is hard-capped at ZIGDOG_ER_ABS_MAX_S (10 s) --
    # no long phase cuts.
    try:
        _er_cap = min(_er_cap, max(0.0, float(
            self._current_green_remaining_s(time, timeSta) or 0.0)))
    except Exception:
        pass
    _er_cap = min(_er_cap, max(0.0, float(
        globals().get('ZIGDOG_ER_ABS_MAX_S', 10.0) or 0.0)))
    try:
        _recov = float(self._reward_get_recoverable(current_phase, timeSta))
        _ge_cap = min(_ge_cap, max(0.0, _recov))
    except Exception:
        pass

    _bus_w = float(globals().get('ZIGDOG_BUS_W', 4.0) or 0.0)
    _car_w = float(globals().get('ZIGDOG_CAR_W', 1.0) or 0.0)
    # ── CTM inheritance (ZIGDOG_CTM, default ON) ──────────────────────────
    # Same cell-transmission-model cross cost the CellQLearn-corridor decider
    # prices with (engine _ctm_cross_cost_paxs): sending=min(sat,n/dt), jam
    # receiving, cascade. Falls back cleanly to the analytic cpc when absent.
    _ctm_on = (bool(globals().get('ZIGDOG_CTM', True))
               and hasattr(self, '_ctm_cross_cost_paxs'))
    _green_giving = ('GE', 'GREEN_REALLOC', 'INS', 'INS_POST', 'INS_PRETERM')

    # All buses predicted at THIS junction in the horizon + their lateness
    # (calling bus always included) -- the fleet AOG term below.
    _fleet = _zigdog_fleet(self, time,
                           extra=(int(veh_id or -1), _eta, _late, _occ))
    _cyc = _zigdog_cycle_init(self, time, current_phase, _cycle_id, _cycle_s)

    _qr_pred = None
    try:
        if bool(globals().get('ZIGDOG_QUEUE_REL', True)):
            _qr_pred = _zigdog_queue_release_pred(
                self, timeSta, cur_phase=current_phase,
                rem_green=_rem_green)
    except Exception:
        _qr_pred = None

    def _eval_cand(_atype, _ap):
        try:
            _r, _so, _tp, _bps, _cpc, _nsd, _std = _dctsp_eval_action(
                self, _atype, float(_ap), sigma_in, no_act_delay, bus_eta_s,
                wrong_phase=_wrong, remaining_red_s=remaining_red_s,
                remaining_green_s=_rem_green)
        except Exception:
            return None
        _bps = max(0.0, float(_bps))
        _cpc = max(0.0, float(_cpc))
        if _ctm_on and (_atype in _green_giving
                        or (bool(globals().get('ZIGDOG_ER_CROSS_COST', True))
                            and _atype in ('EARLY_RED', 'ER'))):
            try:
                _ctm_cpc = float(self._ctm_cross_cost_paxs(float(_ap), timeSta))
                if _ctm_cpc > _cpc:
                    _cpc = _ctm_cpc
            except Exception:
                pass
        # Queue-first MEASURED cross cost (2026-10-03): for LOW side flow the
        # standing queue is the whole cost, so raise cpc with the LIVE queue
        # (no warm-up/seed); arrival term only from live flow above threshold.
        if bool(globals().get('ZIGDOG_MEASURED_CROSS', True)):
            try:
                _mc = float(_zigdog_measured_cross_cost(self, float(_ap)))
                if _mc > _cpc:
                    _cpc = _mc
            except Exception:
                pass
        _green = max(0.0, _rem_green)
        if _atype == 'GE':
            _green += float(_ap)
        elif _atype in ('EARLY_RED', 'ER'):
            _green = max(0.0, _green - float(_ap))
        if _wrong:
            _aog = 0.0
        elif bool(globals().get('ZIGDOG_FLEET_AOG', True)) and _fleet:
            # FLEET AOG (2026-10-02): sum over ALL buses predicted at this
            # junction in the horizon, each weighted by its schedule lateness
            # (catch-up boost), so a late bus can pull the green forward even
            # when the calling bus is on time. `_fleet` is [(vid, eta, late,
            # occ)] including the calling bus.
            _aog = 0.0
            for (_bv, _be, _bl, _bo) in _fleet:
                _fb = 1.0 + min(1.0, _bl / max(
                    1.0, float(globals().get('ZIGDOG_LATE_BOOST_S', 120.0)
                               or 120.0)))
                if _be <= _green:
                    _aog += _bo * _fb
                else:
                    _aog -= _bo * _fb * min(
                        1.0, (_be - _green) / max(1.0, _green or 1.0))
            # CHAIN rollout (2026-10-03): score the action's effect on the
            # REST of the cycle. ER advances every later phase (and the bus
            # phase's return) by ~param, so buses arriving later this cycle can
            # be covered; GE is recovery-neutral within the cycle (only ER
            # shifts the tail). Cheap first-order chain, no tree search.
            if (_atype in ('EARLY_RED', 'ER')
                    and bool(globals().get('ZIGDOG_CHAIN_PLAN', True))):
                _tail = 0.0
                for (_bv, _be2, _bl, _bo) in _fleet:
                    if _be2 <= max(0.0, _rem_green):
                        continue          # already in the immediate window
                    _fb = 1.0 + min(1.0, _bl / max(
                        1.0, float(globals().get('ZIGDOG_LATE_BOOST_S', 120.0)
                                   or 120.0)))
                    _gain = min(float(_ap), _be2)
                    _tail += _bo * _fb * min(1.0, _gain / max(1.0, _be2))
                _aog += (float(globals().get('ZIGDOG_CHAIN_TAIL_W', 1.0) or 0.0)
                         * _tail)
        elif _eta <= _green:
            _aog = _occ * _boost
        else:
            _aog = -_occ * min(1.0, (_eta - _green) / max(1.0, _green or 1.0))
        _surp = _nash_phase_total_bps(self, _atype, float(_ap), _bps)
        _score = _bus_w * _aog + _car_w * _surp - _cpc
        # DP-gated future-pathway bonus (2026-10-03): a beam-bounded dynamic-
        # programming rollout over the upcoming phase windows, seeded with THIS
        # candidate's on-green window. ZIGDOG_DP_BEAM/ZIGDOG_DP_DEPTH gate how
        # many future pathways (bus arrival branches) are expanded, keeping the
        # prediction bounded and reliable instead of summing an unbounded tail.
        if bool(globals().get('ZIGDOG_DP_ENABLE', True)) and _fleet:
            try:
                _cyc_s_dp = (float(globals().get('ZIGDOG_CYCLE_S', 0.0) or 0.0)
                             or float(getattr(self, 'CycleLength', 0.0) or 0.0)
                             or 120.0)
                _dp_v = _zigdog_dp_pathways(
                    self, _fleet, current_phase, max(0.0, _green),
                    _cyc_s_dp, _bus_w, timeSta)
                _score += (float(globals().get('ZIGDOG_DP_W', 0.0) or 0.0)
                           * float(_dp_v))
            except Exception:
                pass
        # QUEUE-RELEASE cost (2026-10-04): the candidate's schedule shift
        # (candidate window - remaining green; + for GE-family, - for ER)
        # re-prices every queued vehicle waiting on the OTHER phases:
        # cost += shift x sum_{p!=cur} Q_p x occ.  GE pays for delaying the
        # queued reds; ER is credited for releasing them earlier.  Prediction
        # uses the measured queue + saturation-flow/lost-time discharge model.
        if _qr_pred and bool(globals().get('ZIGDOG_QUEUE_REL', True)):
            try:
                _shift2 = float(_green) - float(_qr_pred.get('rem_green', 0.0))
                _score -= (float(globals().get('ZIGDOG_QUEUE_W', 1.0) or 0.0)
                           * _shift2 * float(_qr_pred.get('other_q_paxs', 0.0)))
            except Exception:
                pass
        # INS/GREEN_REALLOC may only serve the COORDINATED mainline phase (the
        # upstream/downstream progression band), not merely the bus's phase.
        if (_atype in ('INS', 'INS_POST', 'INS_PRETERM', 'GREEN_REALLOC')
                and bool(globals().get('ZIGDOG_INS_GR_COORD_ONLY', True))
                and not _ins_gr_coord_phase_ok(self, timeSta)):
            return None
        # ── ER BAND RESPECT (2026-10-04) ──────────────────────────────────
        # A phase cut desynchronises the fixed-time progression band -- the
        # dominant car-delay loss on the Aimsun KG plan (bus delay improved
        # while car delay rose 5-9 s on the hard seeds). ER is now bounded by
        # ZIGDOG_BAND_MAX_ER_S and may never eat into the coordinated phase's
        # protected green.
        if (_atype in ('EARLY_RED', 'ER')
                and bool(globals().get('ZIGDOG_ER_RESPECT_BAND', True))):
            _maxcut = max(0.0, float(globals().get(
                'ZIGDOG_BAND_MAX_ER_S', 5.0) or 0.0))
            _prot = max(0.0, float(globals().get(
                'ZIGDOG_BAND_PROTECT_GREEN_S', 8.0) or 0.0))
            if _maxcut > 0.0 and float(_ap) > _maxcut:
                return None
            _cph = 0
            try:
                _cph = int(self._actuated_coord_phase(timeSta) or 0)
            except Exception:
                _cph = 0
            if _cph > 0 and int(current_phase) == _cph:
                if float(_ap) > max(0.0, float(_rem_green) - _prot) + 1e-6:
                    return None
        # Cycle constraints: min/max cycle time, min phase green, ER budget.
        _okc, _why = _zigdog_cycle_gate(self, time, _cyc, _atype, float(_ap),
                                        _rem_green)
        if not _okc:
            return None
        rows.append((action_label(_atype, float(_ap)), float(_ap), _r, _so,
                     _tp, _bps, _cpc, _nsd, _std))
        return (_atype, float(_ap), _score, _so, _tp)

    _best = ('NO_ACTION', 0.0, 0.0, so_na, tp_na)
    if not _wrong and _ge_cap >= float(globals().get('MIN_GE_EXTENSION_S', 3.0)):
        # ── GE magnitude is SOLVED, not scanned (2026-10-02) ──────────────
        # Same solver chain the corridor decider uses: _solve_ge_durations
        # gives the closed-form BUS-serve / DEMAND-clear seconds (honouring
        # BXT_SOLVER harmony/deficit/golden where applicable), then DE refines
        # the best value against the ZIGDOG score. The grid is only the
        # envelope fallback when nothing solves.
        try:
            _ge_solved = [float(x) for x in _solve_ge_durations(
                self, bus_eta_s, _rem_green, veh_id)]
        except Exception:
            _ge_solved = []
        _ge_cands = sorted({round(min(x, _ge_cap), 1)
                            for x in (_ge_solved or _ge_grid)})
        _ge_cands = _zigdog_cap_seeds(
            _ge_cands, int(globals().get('ZIGDOG_MAX_SEEDS', 4) or 0))
        try:
            def _ev_ge(_x):
                _c = _eval_cand('GE', float(_x))
                return _c[2] if _c is not None else -1.0e18
            _bx, _ = _de_solve_magnitude(
                _ev_ge, min(_ge_cands), _ge_cap, seeds=_ge_cands)
            _ge_cands = sorted(set(_ge_cands + [round(min(float(_bx), _ge_cap), 1)]))
        except Exception:
            pass
        for _s in _ge_cands:
            _c = _eval_cand('GE', _s)
            if _c and _c[2] > _best[2]:
                _best = _c
    _er_seeds = sorted({round(min(x, _er_cap), 1) for x in _er_grid})
    if bool(globals().get('ZIGDOG_SOLVE_ER', True)) and _er_cap > 0.0:
        # ER magnitude SOLVED (2026-10-03): the old grid {10, 15} was too
        # coarse -- sometimes 1s is optimal. Seed 1s-resolution candidates
        # across the cap and refine with DE against the same composite score
        # the GE path uses (surplus + CTM/measured cross + fleet AOG + DP).
        _er_lo = max(1.0, float(globals().get('ZIGDOG_ER_MIN_S', 1.0) or 1.0))
        _er_st = max(1.0, float(globals().get('ZIGDOG_ER_FINE_S', 1.0) or 1.0))
        _n_st = int(max(0.0, (_er_cap - _er_lo)) / _er_st) + 1
        _er_seeds = sorted(set(
            [round(min(_er_cap, x), 1) for x in _er_grid]
            + [round(_er_lo + i * _er_st, 1) for i in range(_n_st)]))
        _er_seeds = [s for s in _er_seeds if 1.0 <= s <= _er_cap]
        _er_seeds = _zigdog_cap_seeds(
            _er_seeds, int(globals().get('ZIGDOG_MAX_SEEDS', 4) or 0))
        try:
            def _ev_er(_x):
                _c = _eval_cand('EARLY_RED', float(_x))
                return _c[2] if _c is not None else -1.0e18
            _bx_er, _ = _de_solve_magnitude(
                _ev_er, _er_lo, _er_cap, seeds=_er_seeds)
            _er_seeds = sorted(set(_er_seeds
                                   + [round(min(float(_bx_er), _er_cap), 1)]))
        except Exception:
            pass
    for _s in _er_seeds:
        _c = _eval_cand('EARLY_RED', _s)
        if _c and _c[2] > _best[2]:
            _best = _c
    # ── INS / GREEN_REALLOC magnitudes SOLVED (2026-10-03) ─────────────
    # Same treatment as GE/ER: 1s-resolution seeds + DE refine against the
    # composite score. Both are green-giving families (coord-phase gated in
    # _score_fam) and cycle-gated like GE; caps ZIGDOG_INS_MAX_S / ZIGDOG_GR_MAX_S.
    if bool(globals().get('ZIGDOG_INS_GR_SOLVER', True)):
        # 2026-10-09: seeds start at FAMILY MINIMUMS, not 1 s. A 1 s
        # insertion (or sub-grid GR) can never execute (insertion_min 10 s,
        # intergreen, min-green) -- it only pollutes the ledger and drags
        # the family's best-pick down with ~0-benefit rows.
        try:
            _ins_lo = max(1.0, float(globals().get(
                'ZIGDOG_INS_MIN_S', 10.0) or 10.0))
        except Exception:
            _ins_lo = 10.0
        try:
            _gr_lo = max(1.0, float(globals().get(
                'ZIGDOG_GR_MIN_S', 5.0) or 5.0))
        except Exception:
            _gr_lo = 5.0
        _ig_specs = (
            (3, 'INS',
             float(globals().get('ZIGDOG_INS_MAX_S', 15.0) or 0.0), _ins_grid,
             _ins_lo),
            (4, 'GREEN_REALLOC',
             float(globals().get('ZIGDOG_GR_MAX_S', 15.0) or 0.0), _gr_grid,
             _gr_lo))
        for _slot, _famtype, _cap, _grid, _lo in _ig_specs:
            if _cap < _lo:
                continue
            _seeds = sorted(set(
                [round(min(_cap, max(_lo, x)), 1) for x in _grid]
                + [float(_i) for _i in range(int(_lo), int(_cap) + 1)]))
            _seeds = _zigdog_cap_seeds(
                _seeds, int(globals().get('ZIGDOG_MAX_SEEDS', 4) or 0))
            try:
                def _ev_ig(_x, _ft=_famtype):
                    _c = _eval_cand(_ft, float(_x))
                    return _c[2] if _c is not None else -1.0e18
                _bxg, _ = _de_solve_magnitude(_ev_ig, _lo, _cap, seeds=_seeds)
                _seeds = sorted(set(
                    _seeds + [round(min(float(_bxg), _cap), 1)]))
            except Exception:
                pass
            _bg = None
            for _s in _seeds:
                _c = _eval_cand(_famtype, _s)
                if _c and (_bg is None or _c[2] > _bg[2]):
                    _bg = _c
            if _bg is not None and _bg[2] > _best[2]:
                _best = _bg

    # 2026-10-03: only EFFECTIVE actions (score > 0 -> actually executed)
    # consume the cycle budget; otherwise blocked picks exhaust the action
    # budget and later real candidates are gated away (the Q commits this way).
    _zigdog_cycle_commit(self, _cyc,
                         _best[0] if _best[2] > 0.0 else 'NO_ACTION',
                         _best[1] if _best[2] > 0.0 else 0.0)
    _log_func(self, f"[ZIGDOG] inter={getattr(self, 'id', '?')} t={time:.0f} "
                    f"cycle={_cycle_id} state={_state}(0b{int(_state):b}) "
                    f"eta={_eta:.0f}s late={_late:.0f}s "
                    f"rem_green={_rem_green:.0f}s "
                    f"pick={action_label(_best[0], _best[1])} "
                    f"score={_best[2]:.0f}", force=True)
    self._zigdog_plan = {'cycle': _cycle_id, 'key': _key, 'choice': _best,
                         'surplus': _best[2], 'so': _best[3], 'tp': _best[4],
                         'rows': rows}
    if _best[0] == 'NO_ACTION' or _best[2] <= 0.0:
        return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)
    return (_best[0], _best[1], _best[2], _best[2], _best[3], _best[4], rows)


def dctsp_zigdog_q(self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
                   no_act_delay, sigma_in, remaining_red_s=0.0):
    """ZIGDOG-Q: plain tabular Q-learner over the PHASE-BINARY state space.

    State  = one bit per phase currently green (4 phases -> 4 states per
             junction; 48 across a 12-signal corridor).
    Action = {HOLD, EXTEND(GE), END_EARLY(ER)} -- the same three families
             ZIGDOG scores; each family's magnitude is solved by the same
             evaluation, with the CTM controller's cross cost inherited
             (ZIGDOG_CTM).
    Reward = the ZIGDOG candidate score (expected AOG + corridor surplus -
             CTM cross cost).  TD(0) with an OPTIMISTIC heuristic-seeded init,
             so an untrained state already acts like ZIGDOG and learning only
             refines it.  In-memory per replication (no cross-run pickle): this
             is the "normal qlearn" A/B for the phase state space."""
    import random as _rndq
    r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
        self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
    rows = [('NO_ACTION', 0.0, r_na, so_na, tp_na, bps_na, cpc_na, nsd_na,
             std_na)]
    _wrong = (int(current_phase) != int(getattr(self, 'BusPhase',
                                                current_phase)))
    _occ = max(1.0, float(getattr(self, 'BusOcc', 40.0) or 40.0))
    _eta = max(0.0, float(bus_eta_s or 0.0))
    _late = max(0.0, float(sigma_in or 0.0))
    _boost = 1.0 + min(1.0, _late / max(
        1.0, float(globals().get('ZIGDOG_LATE_BOOST_S', 120.0) or 120.0)))
    try:
        _n_ph = max(1, int(len(getattr(self, 'phase_list', []) or [])))
    except Exception:
        _n_ph = 4
    _state = 1 << (max(0, min(int(current_phase) - 1, _n_ph - 1)))
    try:
        _rem_green = float(self._current_green_remaining_s(time, timeSta) or 0.0)
    except Exception:
        _rem_green = 0.0
    # ── well-defined TIME-AWARE state (2026-10-03) ─────────────────────────
    # The phase bit alone is not a Markov state: doing nothing keeps the bit
    # while the natural green runs out, and the same bit is observed with 60s
    # or 2s of green left -- ambiguous futures. Bucketize the REMAINING GREEN
    # so the state advances as the clock does; HOLD then has well-defined
    # transitions (bit stays, bucket moves; at natural green end both reset).
    # State = phase_bit | (bucket << n_ph) -- still tiny (4 phases x 3 buckets).
    if bool(globals().get('ZIGDOG_Q_STATE_TIME', True)):
        try:
            _dur_ph = float(_eci_call('GetPhaseDuration', self.node_id, int(current_phase),
                                             timeSta) or 0.0)
        except Exception:
            _dur_ph = 0.0
        if _dur_ph <= 0.0:
            _dur_ph = max(20.0, float(
                getattr(self, 'CycleLength', 0.0) or 0.0) / max(1, _n_ph))
        _frac = max(0.0, min(1.0, float(_rem_green) / _dur_ph))
        _nb = max(2, int(globals().get('ZIGDOG_Q_TIME_BUCKETS', 3) or 3))
        _bucket = int((1.0 - _frac) * (_nb - 1) + 0.5)   # 0=fresh .. nb-1=ending
        _state |= (_bucket << _n_ph)

    _ge_grid = [float(x) for x in (globals().get('GE_DURATIONS_S')
                                   or [5.0, 10.0, 15.0])]
    _er_grid = [float(x) for x in (globals().get('ER_DURATIONS_S')
                                   or [10.0, 20.0, 30.0])]
    _ins_grid = [float(x) for x in (globals().get('INS_DURATIONS_S')
                                    or [10.0, 15.0, 20.0])]
    _gr_grid = [float(x) for x in (globals().get('GR_DURATIONS_S')
                                   or [5.0, 10.0, 15.0])]
    _ge_cap = min(max(_ge_grid),
                  float(globals().get('ZIGDOG_MAX_GE_S', 15.0) or 15.0))
    _er_cap = min(max(_er_grid),
                  float(globals().get('ZIGDOG_MAX_ER_S', 10.0) or 0.0))
    # 2026-10-03: ER can NEVER exceed the current green LEFT (you cannot cut
    # more than remains) and is hard-capped at ZIGDOG_ER_ABS_MAX_S (10 s) --
    # no long phase cuts.
    try:
        _er_cap = min(_er_cap, max(0.0, float(
            self._current_green_remaining_s(time, timeSta) or 0.0)))
    except Exception:
        pass
    _er_cap = min(_er_cap, max(0.0, float(
        globals().get('ZIGDOG_ER_ABS_MAX_S', 10.0) or 0.0)))
    try:
        _recov = float(self._reward_get_recoverable(current_phase, timeSta))
        _ge_cap = min(_ge_cap, max(0.0, _recov))
    except Exception:
        pass
    _bus_w = float(globals().get('ZIGDOG_BUS_W', 4.0) or 0.0)
    _car_w = float(globals().get('ZIGDOG_CAR_W', 1.0) or 0.0)
    _ctm_on = (bool(globals().get('ZIGDOG_CTM', True))
               and hasattr(self, '_ctm_cross_cost_paxs'))
    _green_giving = ('GE', 'GREEN_REALLOC', 'INS', 'INS_POST', 'INS_PRETERM')

    # All buses predicted at THIS junction in the horizon + their lateness
    # (calling bus always included) -- the fleet AOG term below.
    _fleet = _zigdog_fleet(self, time,
                           extra=(int(veh_id or -1), _eta, _late, _occ))
    try:
        _cycle_s_q = (float(globals().get('ZIGDOG_CYCLE_S', 0.0) or 0.0)
                      or float(getattr(self, 'CycleLength', 0.0) or 0.0)
                      or 120.0)
    except Exception:
        _cycle_s_q = 120.0
    _cyc = _zigdog_cycle_init(self, time, current_phase,
                              int(float(time) // max(1.0, _cycle_s_q)),
                              _cycle_s_q)

    _qr_pred = None
    try:
        if bool(globals().get('ZIGDOG_QUEUE_REL', True)):
            _qr_pred = _zigdog_queue_release_pred(
                self, timeSta, cur_phase=current_phase,
                rem_green=_rem_green)
    except Exception:
        _qr_pred = None

    # ── PREDICTIVE STATE EXTENSION (2026-10-04) ────────────────────────
    # Extra state bits for the predictive arm (ZIGDOG_QP):
    #   * red-queue bucket from the queue-release prediction (other_q_paxs)
    #   * bus-context bit from the fleet tracker (late bus within horizon)
    # Defaults OFF so existing q-tables stay compatible; the arm enables them.
    if bool(globals().get('ZIGDOG_Q_STATE_QUEUE', False)) and _qr_pred:
        try:
            _qq2 = float(_qr_pred.get('other_q_paxs', 0.0) or 0.0)
            _qb2 = 0 if _qq2 <= 1.0 else (1 if _qq2 < 100.0 else (
                2 if _qq2 < 400.0 else 3))
            _state |= (_qb2 << (_n_ph + 2))
        except Exception:
            pass
    if bool(globals().get('ZIGDOG_Q_STATE_BUS', False)):
        try:
            _bb2 = 0
            if _fleet:
                _mx_late = max(float(_b[2]) for _b in _fleet)
                _bb2 = 1 if _mx_late > 60.0 else 2
            _state |= (_bb2 << (_n_ph + 4))
        except Exception:
            pass

    def _score_fam(_atype, _ap):
        try:
            _r, _so, _tp, _bps, _cpc, _nsd, _std = _dctsp_eval_action(
                self, _atype, float(_ap), sigma_in, no_act_delay, bus_eta_s,
                wrong_phase=_wrong, remaining_red_s=remaining_red_s,
                remaining_green_s=_rem_green)
        except Exception:
            return None
        _bps = max(0.0, float(_bps))
        _cpc = max(0.0, float(_cpc))
        if _ctm_on and (_atype in _green_giving
                        or (bool(globals().get('ZIGDOG_ER_CROSS_COST', True))
                            and _atype in ('EARLY_RED', 'ER'))):
            try:
                _ctm_cpc = float(self._ctm_cross_cost_paxs(float(_ap), timeSta))
                if _ctm_cpc > _cpc:
                    _cpc = _ctm_cpc
            except Exception:
                pass
        # Queue-first MEASURED cross cost (2026-10-03): for LOW side flow the
        # standing queue is the whole cost, so raise cpc with the LIVE queue
        # (no warm-up/seed); arrival term only from live flow above threshold.
        if bool(globals().get('ZIGDOG_MEASURED_CROSS', True)):
            try:
                _mc = float(_zigdog_measured_cross_cost(self, float(_ap)))
                if _mc > _cpc:
                    _cpc = _mc
            except Exception:
                pass
        _green = max(0.0, _rem_green)
        if _atype == 'GE':
            _green += float(_ap)
        elif _atype in ('EARLY_RED', 'ER'):
            _green = max(0.0, _green - float(_ap))
        if _wrong:
            _aog = 0.0
        elif bool(globals().get('ZIGDOG_FLEET_AOG', True)) and _fleet:
            # FLEET AOG (2026-10-02): sum over ALL buses predicted at this
            # junction in the horizon, each weighted by its schedule lateness
            # (catch-up boost), so a late bus can pull the green forward even
            # when the calling bus is on time. `_fleet` is [(vid, eta, late,
            # occ)] including the calling bus.
            _aog = 0.0
            for (_bv, _be, _bl, _bo) in _fleet:
                _fb = 1.0 + min(1.0, _bl / max(
                    1.0, float(globals().get('ZIGDOG_LATE_BOOST_S', 120.0)
                               or 120.0)))
                if _be <= _green:
                    _aog += _bo * _fb
                else:
                    _aog -= _bo * _fb * min(
                        1.0, (_be - _green) / max(1.0, _green or 1.0))
            # CHAIN rollout (2026-10-03): score the action's effect on the
            # REST of the cycle. ER advances every later phase (and the bus
            # phase's return) by ~param, so buses arriving later this cycle can
            # be covered; GE is recovery-neutral within the cycle (only ER
            # shifts the tail). Cheap first-order chain, no tree search.
            if (_atype in ('EARLY_RED', 'ER')
                    and bool(globals().get('ZIGDOG_CHAIN_PLAN', True))):
                _tail = 0.0
                for (_bv, _be2, _bl, _bo) in _fleet:
                    if _be2 <= max(0.0, _rem_green):
                        continue          # already in the immediate window
                    _fb = 1.0 + min(1.0, _bl / max(
                        1.0, float(globals().get('ZIGDOG_LATE_BOOST_S', 120.0)
                                   or 120.0)))
                    _gain = min(float(_ap), _be2)
                    _tail += _bo * _fb * min(1.0, _gain / max(1.0, _be2))
                _aog += (float(globals().get('ZIGDOG_CHAIN_TAIL_W', 1.0) or 0.0)
                         * _tail)
        elif _eta <= _green:
            _aog = _occ * _boost
        else:
            _aog = -_occ * min(1.0, (_eta - _green) / max(1.0, _green or 1.0))
        _surp = _nash_phase_total_bps(self, _atype, float(_ap), _bps)
        _score = _bus_w * _aog + _car_w * _surp - _cpc
        # DP-gated future-pathway bonus (2026-10-03): a beam-bounded dynamic-
        # programming rollout over the upcoming phase windows, seeded with THIS
        # candidate's on-green window. ZIGDOG_DP_BEAM/ZIGDOG_DP_DEPTH gate how
        # many future pathways (bus arrival branches) are expanded, keeping the
        # prediction bounded and reliable instead of summing an unbounded tail.
        if bool(globals().get('ZIGDOG_DP_ENABLE', True)) and _fleet:
            try:
                _cyc_s_dp = (float(globals().get('ZIGDOG_CYCLE_S', 0.0) or 0.0)
                             or float(getattr(self, 'CycleLength', 0.0) or 0.0)
                             or 120.0)
                _dp_v = _zigdog_dp_pathways(
                    self, _fleet, current_phase, max(0.0, _green),
                    _cyc_s_dp, _bus_w, timeSta)
                _score += (float(globals().get('ZIGDOG_DP_W', 0.0) or 0.0)
                           * float(_dp_v))
            except Exception:
                pass
        # QUEUE-RELEASE cost (2026-10-04): the candidate's schedule shift
        # (candidate window - remaining green; + for GE-family, - for ER)
        # re-prices every queued vehicle waiting on the OTHER phases:
        # cost += shift x sum_{p!=cur} Q_p x occ.  GE pays for delaying the
        # queued reds; ER is credited for releasing them earlier.  Prediction
        # uses the measured queue + saturation-flow/lost-time discharge model.
        if _qr_pred and bool(globals().get('ZIGDOG_QUEUE_REL', True)):
            try:
                _shift2 = float(_green) - float(_qr_pred.get('rem_green', 0.0))
                _score -= (float(globals().get('ZIGDOG_QUEUE_W', 1.0) or 0.0)
                           * _shift2 * float(_qr_pred.get('other_q_paxs', 0.0)))
            except Exception:
                pass
        # INS/GREEN_REALLOC may only serve the COORDINATED mainline phase (the
        # upstream/downstream progression band), not merely the bus's phase.
        if (_atype in ('INS', 'INS_POST', 'INS_PRETERM', 'GREEN_REALLOC')
                and bool(globals().get('ZIGDOG_INS_GR_COORD_ONLY', True))
                and not _ins_gr_coord_phase_ok(self, timeSta)):
            return None
        # ── ER BAND RESPECT (2026-10-04) ──────────────────────────────────
        # A phase cut desynchronises the fixed-time progression band -- the
        # dominant car-delay loss on the Aimsun KG plan (bus delay improved
        # while car delay rose 5-9 s on the hard seeds). ER is now bounded by
        # ZIGDOG_BAND_MAX_ER_S and may never eat into the coordinated phase's
        # protected green.
        if (_atype in ('EARLY_RED', 'ER')
                and bool(globals().get('ZIGDOG_ER_RESPECT_BAND', True))):
            _maxcut = max(0.0, float(globals().get(
                'ZIGDOG_BAND_MAX_ER_S', 5.0) or 0.0))
            _prot = max(0.0, float(globals().get(
                'ZIGDOG_BAND_PROTECT_GREEN_S', 8.0) or 0.0))
            if _maxcut > 0.0 and float(_ap) > _maxcut:
                return None
            _cph = 0
            try:
                _cph = int(self._actuated_coord_phase(timeSta) or 0)
            except Exception:
                _cph = 0
            if _cph > 0 and int(current_phase) == _cph:
                if float(_ap) > max(0.0, float(_rem_green) - _prot) + 1e-6:
                    return None
        # Cycle constraints: min/max cycle time, min phase green, ER budget.
        _okc, _why = _zigdog_cycle_gate(self, time, _cyc, _atype, float(_ap),
                                        _rem_green)
        if not _okc:
            return None
        rows.append((action_label(_atype, float(_ap)), float(_ap), _r, _so,
                     _tp, _bps, _cpc, _nsd, _std))
        return (_atype, float(_ap), _score, _so, _tp)

    _fam = {0: ('NO_ACTION', 0.0, 0.0, so_na, tp_na)}
    if not _wrong and _ge_cap >= float(globals().get('MIN_GE_EXTENSION_S', 3.0)):
        # GE magnitude SOLVED (closed-form seeds + DE), same as ZIGDOG.
        try:
            _ge_solved = [float(x) for x in _solve_ge_durations(
                self, bus_eta_s, _rem_green, veh_id)]
        except Exception:
            _ge_solved = []
        _ge_cands = sorted({round(min(x, _ge_cap), 1)
                            for x in (_ge_solved or _ge_grid)})
        try:
            def _ev_ge_q(_x):
                _c = _score_fam('GE', float(_x))
                return _c[2] if _c is not None else -1.0e18
            _bxq, _ = _de_solve_magnitude(
                _ev_ge_q, min(_ge_cands), _ge_cap, seeds=_ge_cands)
            _ge_cands = sorted(set(_ge_cands + [round(min(float(_bxq), _ge_cap), 1)]))
        except Exception:
            pass
        _bg = None
        for _s in _ge_cands:
            _c = _score_fam('GE', _s)
            if _c and (_bg is None or _c[2] > _bg[2]):
                _bg = _c
        if _bg is not None:
            _fam[1] = _bg
    _be = None
    _er_seeds = sorted({round(min(x, _er_cap), 1) for x in _er_grid})
    if bool(globals().get('ZIGDOG_SOLVE_ER', True)) and _er_cap > 0.0:
        # ER magnitude SOLVED (2026-10-03): 1s-resolution seeds + DE refine
        # instead of the {10, 15} grid -- "reduce by 1 second" when best.
        _er_lo = max(1.0, float(globals().get('ZIGDOG_ER_MIN_S', 1.0) or 1.0))
        _er_st = max(1.0, float(globals().get('ZIGDOG_ER_FINE_S', 1.0) or 1.0))
        _n_st = int(max(0.0, (_er_cap - _er_lo)) / _er_st) + 1
        _er_seeds = sorted(set(
            [round(min(_er_cap, x), 1) for x in _er_grid]
            + [round(_er_lo + i * _er_st, 1) for i in range(_n_st)]))
        _er_seeds = [s for s in _er_seeds if 1.0 <= s <= _er_cap]
        try:
            def _ev_er_q(_x):
                _c = _score_fam('EARLY_RED', float(_x))
                return _c[2] if _c is not None else -1.0e18
            _bx_erq, _ = _de_solve_magnitude(
                _ev_er_q, _er_lo, _er_cap, seeds=_er_seeds)
            _er_seeds = sorted(set(_er_seeds
                                   + [round(min(float(_bx_erq), _er_cap), 1)]))
        except Exception:
            pass
    for _s in _er_seeds:
        _c = _score_fam('EARLY_RED', _s)
        if _c and (_be is None or _c[2] > _be[2]):
            _be = _c
    if _be is not None:
        _fam[2] = _be
    # ── INS / GREEN_REALLOC magnitudes SOLVED (2026-10-03) ─────────────
    # Same treatment as GE/ER: 1s-resolution seeds + DE refine; the Q's
    # action space grows to 5 ({HOLD, GE, ER, INS, GR}).
    if bool(globals().get('ZIGDOG_INS_GR_SOLVER', True)):
        # 2026-10-09: seeds start at FAMILY MINIMUMS, not 1 s (see above).
        try:
            _ins_lo2 = max(1.0, float(globals().get(
                'ZIGDOG_INS_MIN_S', 10.0) or 10.0))
        except Exception:
            _ins_lo2 = 10.0
        try:
            _gr_lo2 = max(1.0, float(globals().get(
                'ZIGDOG_GR_MIN_S', 5.0) or 5.0))
        except Exception:
            _gr_lo2 = 5.0
        _ig_specs = (
            (3, 'INS',
             float(globals().get('ZIGDOG_INS_MAX_S', 15.0) or 0.0), _ins_grid,
             _ins_lo2),
            (4, 'GREEN_REALLOC',
             float(globals().get('ZIGDOG_GR_MAX_S', 15.0) or 0.0), _gr_grid,
             _gr_lo2))
        for _slot, _famtype, _cap, _grid, _lo in _ig_specs:
            if _cap < _lo:
                continue
            _seeds = sorted(set(
                [round(min(_cap, max(_lo, x)), 1) for x in _grid]
                + [float(_i) for _i in range(int(_lo), int(_cap) + 1)]))
            try:
                def _ev_igq(_x, _ft=_famtype):
                    _c = _score_fam(_ft, float(_x))
                    return _c[2] if _c is not None else -1.0e18
                _bxgq, _ = _de_solve_magnitude(_ev_igq, _lo, _cap,
                                               seeds=_seeds)
                _seeds = sorted(set(
                    _seeds + [round(min(float(_bxgq), _cap), 1)]))
            except Exception:
                pass
            _bgq = None
            for _s in _seeds:
                _c = _score_fam(_famtype, _s)
                if _c and (_bgq is None or _c[2] > _bgq[2]):
                    _bgq = _c
            if _bgq is not None:
                _fam[_slot] = _bgq

    # ── Q table (per junction, phase-binary state, optimistic seed) ────────
    _alpha = float(globals().get('ZIGDOG_Q_ALPHA', 0.2) or 0.2)
    _gamma = float(globals().get('ZIGDOG_Q_GAMMA', 0.9) or 0.9)
    _eps = float(globals().get('ZIGDOG_Q_EPSILON', 0.05) or 0.0)
    _key = int(getattr(self, 'id', 0))
    _q = getattr(self, '_zigq_q', None)
    if _q is None:
        _q = {}
        self._zigq_q = _q
    _qj = _q.setdefault(_key, {})
    _realized = bool(globals().get('ZIGDOG_Q_REALIZED_REWARD', True))
    if _realized:
        # Realized-reward Q (2026-10-03): neutral seed -- value must be
        # EARNED from measured outcomes, not copied from the heuristic's own
        # score (seeding the score made argmax(q) == argmax(score) forever:
        # a guaranteed clone of dctsp_zigdog).
        _seed_row = [0.0, 0.0, 0.0, 0.0, 0.0]
    else:
        _seed_row = [0.0,
                     float(_fam.get(1, ('', 0, 0.0))[2]),
                     float(_fam.get(2, ('', 0, 0.0))[2]),
                     float(_fam.get(3, ('', 0, 0.0))[2]),
                     float(_fam.get(4, ('', 0, 0.0))[2])]
    if _state not in _qj:
        _qj[_state] = list(_seed_row)
    _qrow = _qj[_state]
    # Visit counter per (junction, state) (2026-10-03): the first visit runs
    # the ZIGDOG warm-up (score pick + score gate) so an untrained run starts
    # at the heuristic baseline; from the MIN_VISITS-th revisit the Q's own
    # earned values decide.
    _visits = getattr(self, '_zigq_visits', None)
    if _visits is None:
        _visits = {}
        self._zigq_visits = _visits
    _vj = _visits.setdefault(_key, {})
    _warm = int(_vj.get(_state, 0))
    _vj[_state] = _warm + 1
    _prev = getattr(self, '_zigq_prev', None)
    if _prev is None:
        _prev = {}
        self._zigq_prev = _prev
    # TD(0) next-state semantics: the NEXT state is the phase-bit state
    # OBSERVED at the next decision call. So a HOLD/GE while the phase runs
    # self-loops in the same state (nothing changes if you do nothing), and
    # when the phase advances -- naturally at its last second, or via
    # END_EARLY/rotation -- the next call observes the NEW phase's state and
    # bootstraps from it. No explicit transition model needed; the phase
    # boundary is handled by observation.
    _r_td = 0.0
    # Realized potential Phi (2026-10-03): measured cross-street standing
    # cost (live queue priced at 1 s of red) + measured MAIN queue in pax.
    # The TD reward of the previous action is Phi_prev - Phi_now: the actual
    # change in standing congestion since that decision -- an outcome signal
    # the learner cannot clone from the heuristic's own prediction.
    _phi_now = 0.0
    if _realized:
        try:
            _phi_now = float(_zigdog_measured_cross_cost(self, 1.0))
        except Exception:
            _phi_now = 0.0
        try:
            _phi_now += float(getattr(self, 'CarOcc', 1.6) or 1.6) * max(
                0.0, float(self._measured_main_queue_veh(current_phase) or 0.0))
        except Exception:
            pass
    _pv = _prev.get(_key)
    if _pv is not None:
        _ps, _pa, _pr, _pphi, _pveh, _plate = _pv
        _pq = _qj.get(_ps)
        if _pq is not None and 0 <= int(_pa) < 5:
            if _realized:
                _r_td = float(_pphi) - _phi_now
                # FAILURE-CORRECTED REWARD (2026-10-04): a SERVICE action that
                # did NOT actually serve its bus (lateness did not improve) is
                # terrible -- a phase insertion/extension that lets nothing
                # through is pure disruption. Penalise it so the learner stops
                # repeating useless interventions.
                if int(_pa) != 0 and _pveh is not None:
                    try:
                        _late_now2 = max(0.0, float(
                            self._bus_lateness_for(int(_pveh)) or 0.0))
                        _served = float(_plate) - _late_now2
                        _min_gain = float(globals().get(
                            'ZIGDOG_Q_SERVED_MIN_GAIN', 0.0) or 0.0)
                        if _served < _min_gain:
                            _r_td -= float(globals().get(
                                'ZIGDOG_Q_FAIL_PENALTY', 50.0) or 0.0)
                    except Exception:
                        pass
            else:
                _r_td = float(_pr)
            _pq[int(_pa)] += _alpha * (_r_td + _gamma * max(_qrow)
                                       - _pq[int(_pa)])
    _avail = [0] + [k for k in (1, 2, 3, 4) if k in _fam]
    _explore = _eps > 0.0 and _rndq.random() < _eps
    _min_v = int(globals().get('ZIGDOG_Q_MIN_VISITS', 1) or 0)
    _q_valid = (bool(globals().get('ZIGDOG_Q_EXECUTE_ON_Q', True))
                and _realized and _warm >= _min_v)
    if _explore:
        _pick = _rndq.choice(_avail)
    elif _q_valid:
        _pick = max(_avail, key=lambda k: _qrow[k])
    else:
        # Warm-up / classic path: pick the best heuristically SCORED family
        # (identical to dctsp_zigdog while the state has no earned value).
        _pick = max(_avail, key=lambda k: float(_fam[k][2]))
    _at, _ap, _surp, _so, _tp = _fam[_pick]
    # Execution gate (2026-10-03):
    #   * exploration BYPASSES the gate -- with the classic "execute only if
    #     score > 0" rule every exploratory draw on a non-positive candidate
    #     collapses to NO_ACTION, so the learner can never observe an
    #     exploration outcome and exploration is decorative;
    #   * a state past MIN_VISITS executes on its OWN earned value (q > 0);
    #   * untrained states keep the classic score gate (ZIGDOG baseline).
    if _explore:
        _exec = (_at != 'NO_ACTION')
    elif _q_valid:
        _exec = (_pick != 0 and float(_qrow[_pick]) > 0.0)
    else:
        _exec = (_at != 'NO_ACTION' and _surp > 0.0)
    _prev[_key] = (_state,
                   (_pick if _exec else 0) if _realized else _pick,
                   float(_surp), float(_phi_now),
                   int(veh_id) if (veh_id and int(veh_id) > 0) else None,
                   max(0.0, float(sigma_in or 0.0)))

    _zigdog_cycle_commit(self, _cyc,
                         _at if (_exec or not _realized) else 'NO_ACTION',
                         _ap)
    _log_func(self, f"[ZIGDOG_Q] inter={_key} t={time:.0f} "
                    f"state={_state}(0b{int(_state):b}) eta={_eta:.0f}s "
                    f"late={_late:.0f}s pick={_pick}:"
                    f"{action_label(_at, _ap)} q={[round(float(v), 1) for v in _qrow]} "
                    f"r={_surp:.0f} exec={1 if _exec else 0} warm={_warm} "
                    f"td={_r_td:.0f}", force=True)
    if not _exec:
        return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)
    return (_at, _ap, _surp, _surp, _so, _tp, rows)
