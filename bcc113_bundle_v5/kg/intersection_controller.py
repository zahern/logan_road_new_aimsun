from AAPI import *
import sys
import csv
import collections
try:
    AKIPrintString("PYTHON EXECUTABLE: " + sys.executable)
    AKIPrintString("PYTHON VERSION: " + sys.version)
except Exception:
    pass
sys.path.insert(0, r"C:\AimsunPackages")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import random
import datetime
import os
import math
BXT_FREEZE_ON_EVAL = True
BXT_TRAIN_EPSILON = 0.3
BXT_EVAL_SEEDS = []
BXT_TRAIN_SEEDS = []
CPDQL_MODE = False
CPDQL_TRAIN_EPSILON = 0.3
CPDQL_EVAL_SEEDS = []
CPDQL_TRAIN_SEEDS = []
import glob
import sqlite3

# Inject the shared project venv site-packages so post-simulation plot scripts
# (plot_shockwave, plot_queue_monitor, etc.) can import pandas / plotly / etc.
# The venv lives at ../logan_road_new/.venv relative to this file's directory.
_venv_sp = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '..', 'logan_road_new', '.venv', 'Lib', 'site-packages'))
if os.path.isdir(_venv_sp) and _venv_sp not in sys.path:
    sys.path.insert(1, _venv_sp)
del _venv_sp

# =============================================================================
# LOGGING FLAGS  —  set each True/False to control verbosity
# All critical errors are always printed regardless of these flags.
# =============================================================================

# ── Core control modes ────────────────────────────────────────────────────────
LOG_HARMONY   = False  # [HARMONY]    GE/insertion decisions in HARMONY mode
LOG_URTSP     = False   # [URTSP]      detection/extension/insertion in URTSP mode
LOG_REWARD    = False   # [REWARD]     action-reward evaluation in REWARD_TSP mode
LOG_TSP_EVT   = False   # [TSP EVENT]  TSP start/end/cooldown markers (all modes)
LOG_COST_VETO = False  # [COST VETO]  per-event decider cost-veto lines (the
                       #   veto still applies + is counted in TSP_Skipped_*;
                       #   _set_logging(False) silences this during batches)

# ── Initialisation ────────────────────────────────────────────────────────────
LOG_INIT      = False   # [INIT]       controller creation, phase list, veh types
LOG_NODE_ID   = False   # [NODE_ID]    node-ID auto-resolution / AimsunNodeID hints
LOG_SECTION   = False  # [SECTION]    incoming-section & topology init detail
LOG_JUNC_XY   = False  # [JUNC_XY]   junction centroid coordinate resolution
LOG_SIDE_DISC = False  # [SIDE_DISC]  side-street section discovery


# ── PT / bus detection ────────────────────────────────────────────────────────
LOG_PT_SCAN   = False  # [PT_SCAN]    PT-line periodic diagnostic (every 5 min)
LOG_DEMAND    = False  # [DEMAND]     vehicle-type position detection at startup

# ── Delay & statistics ────────────────────────────────────────────────────────
LOG_STATS     = False   # [STATS]      end-of-simulation results summary
LOG_DELAY     = False  # [DELAY]      IntersectionController collect_delay detail

# ── Diagnostic heartbeat ──────────────────────────────────────────────────────
LOG_HEARTBEAT = False  # [HEARTBEAT]  per-60s state dump (phase/flag/queue/flow)
LOG_CORRIDOR  = False   # [CORRIDOR]   corridor-group coordination events and state

# ── Per-intersection detection-level logging ──────────────────────────────────
# List junction IDs to enable verbose per-step detection scans for those junctions.
# Independent of LOG_GB_BUS — logs every vehicle checked even when no request fires.
# Example: LOG_DETECTION_INTERSECTIONS = [17249, 17383]
LOG_DETECTION_INTERSECTIONS: list = []   # [] = disabled; add junction IDs to enable

# ── Detection point marking ───────────────────────────────────────────────────
# MARK_DETECTION_POINTS = True:
#   • Changes the detected bus to a bright RED colour in the Aimsun animation
#     at the exact simulation step when the first TSP request fires.
#     (Colour is reset after the bus clears the intersection.)
#   • Writes every first-detection event to:
#       logs/detection_points.csv   — X, Y, junction_id, veh_id, sim_time, tier
#       logs/detection_points.geojson  — importable as a map layer in any GIS tool
#     The GeoJSON can be loaded via File → Import in Aimsun or opened in QGIS/ArcGIS
#     to see coloured dots exactly where each bus was first detected.
# Only the FIRST detection per (junction, vehicle) is marked to avoid duplicates.
# BUGFIX 2026-09-30: default is now False, not True. Marking is a DEBUG /
# VISUALISATION aid, and every mark call goes through the AAPI canvas path:
# a batch run left this on logged 365,119 mark calls for a single 2.8 h run
# (~5 min of pure overhead per run, and the whole point of a batch is the CSV).
# Scripts that DO want the dots set this back to True per run; the batch
# helpers champion_search._disable_batch_plotting / phase3_sensitivity also
# force it off explicitly, so flipping the default only helps the scripts that
# forgot to.
MARK_DETECTION_POINTS: bool = False
TRACK_BUS_POSITIONS: bool = False
BUS_TRACK_SUPPLEMENT_NETWORK_SCAN: bool = True

# =============================================================================
# AIMSUN CANVAS OVERLAY
# OVERLAY_DETECTIONS_ON_MAP = True:
#   After the simulation finishes (AAPIFinish) this script uses PyANGKernel to
#   create GKAnnotation markers directly in the Aimsun network editor view at
#   the exact model-coordinate location of each bus detection.  Markers persist
#   in the network view after the simulation — no external GIS tool needed.
#
#   Each marker shows:  "● Bus <id>  jct <jct>  t=<sim_time>s  [<tier>]"
#
#   The annotations are created in a named layer "TSP Bus Detections" so you
#   can toggle their visibility from the Aimsun Layers panel.
#
# NOTE: requires PyANGKernel (bundled with Aimsun Next).  Fails silently if
#   the API is unavailable or the model cannot be accessed.
#
# Set False to skip (e.g. if you only want the CSV / PNG outputs).
# =============================================================================
OVERLAY_DETECTIONS_ON_MAP: bool = False

# Safety switch: block all script-driven model catalog mutations
# (newObject/deleteObject/addObjectToFolder) unless explicitly enabled.
# Keep False for normal simulation runs so this script never edits model objects.
ALLOW_MODEL_CATALOG_WRITES: bool = False

# Storage safety preflight: read-only quick_check of companion *.sqlite files.
# If corruption is detected and strict mode is enabled, abort AAPIInit early so
# the simulation does not continue on a damaged model database.
ENABLE_MODEL_DB_PREFLIGHT: bool = True
MODEL_DB_PREFLIGHT_STRICT: bool = True

# =============================================================================
# LIVE STATUS DASHBOARD
# STATUS_DASHBOARD_INTERVAL_S:

# PT frequency scaling via runtime injection (Plan-B scaler):
# 0 = off; 1.0 = calibration run (records natural entries); >1 =
# inject extras to reach that frequency multiple. Set per-level.
BUS_FREQ_INJECT_SCALAR = 0.0
#   How often (in simulation seconds) to print a formatted status table to the
#   Aimsun console showing every intersection's current TSP state.
#   The table always prints regardless of VERBOSE so you can see what the
#   controller is doing at a glance without scrolling through debug logs.
#
#   Columns:  Jct | Phase | Flag | GE-debt | Bus? | det/ext/ins counts
#
#   Set to 0 to disable the dashboard.
# =============================================================================
STATUS_DASHBOARD_INTERVAL_S: float = 0.0

# =============================================================================
# MASTER CONSOLE SWITCH
# VERBOSE = True  → all enabled flags print to Aimsun console AND log file
# VERBOSE = False → NOTHING prints to the Aimsun console; everything still
#                   goes to the log file so you can review it after the run.
#                   Critical errors (simulation halted) are always shown.
# =============================================================================
VERBOSE = False
                  # Aimsun console (per-step [REWARD_TSP]/[SIDE_OBJ] spam is
                  # VERBOSE-gated via log_to_file). Everything still goes to the
                  # log FILE; [RUNNER] progress + [FINISH] validation still show.
                  # Set back to True for a chatty single-arm debug session.

try:
    LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
except Exception:
    LOG_DIR = r"D:\Aimsun_Results\Logs"
os.makedirs(LOG_DIR, exist_ok=True)

timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(LOG_DIR, f"Aimsun_TSP_Log_{timestamp}.txt")

# Read experiment name from run_config.py so it appears in every output filename,
# making it easy to match detection CSVs back to the correct batch row.
_CURRENT_EXPERIMENT = "UNKNOWN"
try:
    _rc_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'run_config.py')
    _rc_ns: dict = {}
    with open(_rc_path, 'r') as _rc_f:
        exec(_rc_f.read(), _rc_ns)
    _CURRENT_EXPERIMENT = str(_rc_ns.get('CURRENT_EXPERIMENT',
                                          _rc_ns.get('CURRENT_STRATEGY', 'UNKNOWN'))).strip()
except Exception:
    pass

# Detection-point output files (written when MARK_DETECTION_POINTS=True)
_DET_CSV      = os.path.join(LOG_DIR, f"detection_points_{_CURRENT_EXPERIMENT}_{timestamp}.csv")
_DET_GEOJSON  = os.path.join(LOG_DIR, f"detection_points_{timestamp}.geojson")
# Junction centroids — written once per junction in AAPIFinish so the plot
# script knows where each intersection is in model coordinates.
_JUNC_CSV     = os.path.join(LOG_DIR, f"junction_centroids_{timestamp}.csv")
_RUN_SUMMARY_TXT = os.path.join(LOG_DIR, f"tsp_run_summary_{timestamp}.txt")
_ALGORITHM_EXPLANATION_TEX = os.path.join(LOG_DIR, f"tsp_algorithm_explanation_{timestamp}.tex")
_WAVE_EVENTS_CSV = os.path.join(LOG_DIR, f"corridor_wave_events_{_CURRENT_EXPERIMENT}_{timestamp}.csv")
_BUS_TRACKING_CSV = os.path.join(LOG_DIR, f"bus_positions_{_CURRENT_EXPERIMENT}_{timestamp}.csv")
_PRESENCE_SNAPSHOT_CSV = os.path.join(LOG_DIR, f"presence_snapshot_{_CURRENT_EXPERIMENT}_{timestamp}.csv")
_NO_INS_SUMMARY_CSV = os.path.join(LOG_DIR, f"no_ins_summary_{_CURRENT_EXPERIMENT}_{timestamp}.csv")
_OBJECTIVE_TRACE_CSV = os.path.join(LOG_DIR, f"objective_trace_{_CURRENT_EXPERIMENT}_{timestamp}.csv")
_objective_trace_header_written: bool = False
# ── Per-cycle reward evaluation CSV (REWARD_TSP mode) ─────────────────────────
# One row per candidate action evaluated. Columns: sim_time_s, junction_id,
# veh_id, bus_eta_s, action, reward, bus_saved_pax_s, other_inc_pax_s,
# side_inc_pax_s, is_chosen.  Lets you plot the full reward surface per cycle.
_REWARD_CYCLE_CSV = os.path.join(LOG_DIR, f"reward_cycle_{_CURRENT_EXPERIMENT}_{timestamp}.csv")
_reward_cycle_header_written: bool = False
# ── Green-wave offset CSV (one row per bus grant, recording inter-junction offsets) ────
_OFFSET_CSV = os.path.join(LOG_DIR, f"green_offsets_{_CURRENT_EXPERIMENT}_{timestamp}.csv")
_offset_header_written: bool = False
# ── 60-second queue snapshot CSV ──────────────────────────────────────────────
_QUEUE_SNAPSHOT_CSV = os.path.join(LOG_DIR, f"queue_snapshot_{_CURRENT_EXPERIMENT}_{timestamp}.csv")
_QUEUE_SNAP_INTERVAL_S = 60.0  # write queue every 60 simulated seconds
_queue_snap_last_t: float = -1e9
_queue_snap_header_written: bool = False

# Tracks (junction_id, veh_id) → last-marked sim_time; prevents duplicate CSV
# rows within the same approach but allows re-recording on later trips
# (gap ≥ _MARK_DET_REARM_S seconds between passes).
_marked_detections: dict = {}
_MARK_DET_REARM_S: float = 120.0  # allow re-detect after bus leaves and returns

# ── Bus position tracking (continuous) ────────────────────────────────────
# Use 1 s updates so zone presence, bus_positions CSV, and transit-link based
# detections are fine-grained enough for per-second TSP decisions.
_BUS_TRACK_INTERVAL_S = 1.0
_bus_track_last_t: float = -1e9
_bus_track_header_written: bool = False
_presence_snapshot_header_written: bool = False
_jct_xy_cache: dict = None
# Track zone state per (veh_id, junction_id) for entry/exit events
_bus_zone_state: dict = {}   # (veh_id, jct_id) → bool (in zone)
# Track when each bus entered each zone to enforce maximum zone occupancy time
_bus_zone_entry_time: dict = {}  # (veh_id, jct_id) → entry_time_s (force exit after 120s)
# Live zone-presence snapshot shared with controller detect_bus as Tier 0.
# Updated every _BUS_TRACK_INTERVAL_S.  Format: {jct_id: {veh_id: (bx, by, spd_kmh)}}
_tracking_zone_presence: dict = {}   # jct_id → {veh_id: (bx, by, spd_kmh)}
# Track whether a bus has ever been logged this run and its last nearest junction
_bus_seen_ids: set = set()
_bus_last_nearest_jct: dict = {}   # veh_id -> jct_id
_active_corridor_bus_count: int = 0  # PT buses with valid XY on the network (updated every _BUS_TRACK_INTERVAL_S)
_net_stats_sections_cache: set | None = None

# ── PT route data (built at AAPISimulationReady) ─────────────────────────────
_pt_line_jct_route: dict = {}    # {line_id: [jct_id, ...]} corridor jcts in route order
_pt_line_section_set: dict = {}  # {line_id: set(section_ids)} all sections in that line
_sec_to_corridor_jct: dict = {}  # {section_id: [jct_id, ...]} reverse map
_bus_line_id: dict = {}          # {veh_id: line_id} populated during tracking
# Live bus (x, y) positions — updated by _track_all_bus_positions every step.
# Coordinator accesses this to embed WHERE the bus was when a prearm fired.
_bus_xy: dict = {}               # {veh_id: (x, y)}
_corridor_jct_incoming: dict = {}# {jct_id: set(section_ids)} from INTERSECTIONS_CONFIG
# Per-bus observed corridor-junction sequence (in entry order from zone_enter events).
# {veh_id: [jct_id, ...]}  Used as a real-time route fallback when _pt_line_jct_route
# has no entry for this bus's PT line (bus-route-aware pre-arm targeting).
_bus_observed_jcts: dict = {}    # {veh_id: [jct_id, ...]} ordered zone-enters
# Per-bus accumulated schedule lateness (seconds behind schedule), updated every
# decision cycle from the bus's no-action delay minus the executed action's saved
# time.  Feeds sigma_in (Z3 lateness) of the weighted-objective reward model.
_bus_lateness: dict = {}         # {veh_id: seconds_late}
# Treat PT-line followers as buses until a real bus type is confirmed.
_bus_type_provisional: bool = False
# Accumulates GeoJSON features; flushed to file in AAPIFinish
_geojson_features: list = []
# Records (sim_time, intersection_id, ge_s, recovery_trimmed_s) for schedule recovery plot
_ge_events: list = []
# Records corridor wave/coordinator lifecycle for post-run tuning plots.
_wave_events: list = []
# Diagnostic counters — incremented in _mark_detection_point regardless of early-returns
_mark_calls_total:   int = 0   # every call (incl. disabled / duplicate)
_mark_calls_written: int = 0   # calls that actually wrote a new row

# Dashboard timer — tracks when the next status table should print
_last_dashboard_t: float = -1e9


# =============================================================================
# CONTROL MODE
#
#   "NORMAL"          — Fixed signal plan, no bus priority.
#
#   "URTSP"           — Unrestricted TSP: green extension (GE) or phase
#                       insertion (INS) at each junction independently.
#
#   "REWARD_TSP"      — Cost-benefit TSP: each step scores GE / INS / hold
#                       in passenger-delay units and takes the best action.
#
#   "HARMONY"         — Phase-based coordination: GE + phase insertion at
#                       each junction; the Corridor Coordinator (CC) pre-arms
#                       downstream junctions as a bus moves along the route.
#
#   "DYNAOPAC"        — Discrete-time best-action: every second the optimizer
#                       tests all candidate durations across all junctions and
#                       activates the network-optimal action (corridor-aware).
#
#   "DYNAOPAC_HARMONY"— Discrete-time best-action + phase-based coordination:
#                       optimizer and CC pre-arming run together.
# =============================================================================
# =============================================================================
# MILP-MPC SETTINGS
# =============================================================================
MILP_MPC_HORIZON_S       = 300.0   # planning horizon (s)
MILP_MPC_REPLAN_S        = 30.0    # re-solve interval (s)
MILP_MPC_TIME_LIMIT_S    = 1.5     # solver time limit (s)
MILP_MPC_EPSILON_LATE_S  = 60.0    # schedule adherence cap (s)
MILP_MPC_EPSILON_Z4_S    = 90.0    # throughput cap (veh·s)
MILP_MPC_Z4_BASELINE     = 380.0   # fixed-time baseline corridor TT (veh·h)

# =============================================================================
# CONTROL MODE
# =============================================================================
TSP_COOLDOWN_OVERRIDE_S = None
CONTROL_MODE = "NORMAL"
GROUP_BASED_BUS_PRIORITY = False
GROUP_BASED_BUS_PRIORITY = False

# =============================================================================
# CORRIDOR COORDINATOR (CC) SETTINGS
#
# The Corridor Coordinator tracks each bus along the route using a Kalman
# filter, predicts arrival time at each downstream junction, and fires a
# pre-arm request early enough for that junction to complete its current
# phase and be ready on green when the bus arrives.
#
# COORDINATED_TSP
#   True  — CC is active; junctions in the same INTERSECTION_GROUPS entry
#           coordinate their signals (pre-arm up to MAX_PRE_ARM junctions
#           ahead of the current bus position).
#   False — Each junction runs independently; no pre-arming.
#
# COORDINATION_ALGO   — ETA prediction method used by CC.
#
#   "KALMAN"    — 1-D Kalman filter on position + speed.  Best for free-flow
#                 or lightly congested conditions.
#
#   "SHOCKWAVE" — Kalman ETA plus a queue-clearance correction: when the
#                 downstream junction has a large queue, adds the time for
#                 the discharge wave to reach the stop line.
#
#   "OBJECTIVE" — Variable lead time: CC picks the lead that maximises
#                   J = COORD_OBJ_ALPHA * bus_delay_saved  (pax-s)
#                     - COORD_OBJ_BETA  * normal_traffic_displaced  (pax-s)
#                 Tune ALPHA / BETA to balance bus priority vs. general delay.
#
#   "ADAPTIVE"  — Hybrid: Kalman ETA → shockwave correction under congestion
#                 → dynamic lead scaled by ETA uncertainty and phase-remaining.
#
# COORD_OBJ_ALPHA / COORD_OBJ_BETA apply only with COORDINATION_ALGO="OBJECTIVE".
# =============================================================================
COORDINATED_TSP = False   # True = CC active (corridor coordination)

MAX_GE_EXTENSION_S   = 10.0   # Max green extension per bus request (s)
MAX_BP_INSERTION_S   = 40.0   # Max bus-phase insertion per request (s)
MIN_GE_EXTENSION_S   = 3.0    # Min green extension if applied (s)
MIN_BP_INSERTION_S   = 5.0    # Min bus-phase insertion if applied (s)
MIN_ER_TRUNCATION_S  = 3.0    # Min early-red truncation if applied (s)
MIN_GR_REDUCTION_S   = 3.0    # Min green-reallocation reduction if applied (s)
INS_TRIGGER_MARGIN_S = 5.0    # Require bus ETA to exceed natural end by this margin before INS
OC_END_TRIGGER_S = 15.0      # Consider adaptive offset correction when the current
                             # (non-bus) phase has less than this remaining (s)
SIDE_QUEUE_ZONE_M = 60.0     # Queue-count reach upstream of the stop line (m).
                             # Walks across short sections but STOPS at the next
                             # signalised junction -- queues beyond it belong to
                             # that junction and would not arrive this cycle.
MAIN_QUEUE_ZONE_M = 60.0     # Same reach for MAIN detector sections whose own
                             # link is a short stub (detector-independent zone
                             # count used when detector counts read empty).
# ── VIRTUAL DETECTORS FROM THE SIGNAL PLAN (2026-10-01) ─────────────────────
# The two constants above are FLAT, and one number cannot be right for both a
# 3-lane main with 50-80 s of green and a side street with ~6 s: the reach that
# captures the main queue under-counts the side one, and the reach that captures
# the side queue counts free-flowing main traffic as queued. Measured on KG with
# the plan-derived rule below, the flat 60 m is too LONG for side approaches
# (derived 32-38 m) and too SHORT for main at high demand (derived 50-114 m).
# That biases BOTH ways: over-priced side cost vetoes grants that were fine,
# while under-priced main queue hides the delay a grant actually causes.
#
# When ON, engine._queue_zone_m() replaces the flat reach with a per-junction,
# per-approach distance derived from that junction's OWN signal plan: place the
# detector just upstream of the maximum queue the approach holds at the end of
# its red, so vehicles downstream of it ARE the queue and vehicles crossing it
# ARE arrivals. It emits one [VDET] line per junction with the computed reach so
# the numbers can be audited before they are trusted. DEFAULT OFF: enable only
# after reading those lines, because the reach scales with demand and the
# no-measurement fallback assumes a design v/c.
VIRTUAL_DET_FROM_PLAN  = False
VIRTUAL_DET_VC_TARGET  = 0.90   # design v/c for the capacity fallback
VIRTUAL_DET_SAFETY     = 1.30   # margin over the computed queue length
VIRTUAL_DET_MARGIN_M   = 15.0   # absolute margin (m)
VIRTUAL_DET_MIN_M      = 30.0   # never shorter than this
VIRTUAL_DET_MAX_M      = 200.0  # never longer than this
# ── BUSES ARE NOT CARS (2026-10-01) ─────────────────────────────────────────
# The zone/flow estimates above are DETECTOR-style and detectors are for general
# traffic. Buses are PT vehicles with known IDs and routes, tracked individually
# through the PT APIs (AKIGetVehicleFollowingPTLine / AKIPTVehGetInf), so leaving
# them in the car queue counts them TWICE: once here at CarOcc and again in the
# bus-delay term at BusOcc (40 pax). AKIVehStateGetVehicleInfSection returns both
# idVeh and type in the same call, so the split costs nothing. When ON, buses in
# the zone are excluded from the car queue and counted separately into
# self._last_zone_bus_cnt so the two populations can be compared, not assumed.
EXCLUDE_BUS_FROM_CAR_QUEUE = False
INS_CLEARANCE_BUFFER_S = 8.0  # Add clearance buffer to ETA when deciding if natural bus phase is truly catchable
INS_MAX_WAIT_TRIGGER_S = 8.0  # If predicted wait for next natural bus phase exceeds this, evaluate INS
# Adaptive bounds for INS trigger margin. A larger ETA should require a
# slightly larger miss of the natural window before forcing insertion.
INS_TRIGGER_MARGIN_MIN_S = 3.0
INS_TRIGGER_MARGIN_MAX_S = 12.0

# ── Reward-TSP weights  (REWARD_TSP mode only) ────────────────────────────────
# Score = -ALPHA*bus_delay_saved - BETA*other_delay_cost - GAMMA*side_delay_cost
# Equal weights (1 / 1 / 1) minimise total passenger delay directly.
REWARD_ALPHA = 1.0
REWARD_BETA = 1.0
REWARD_GAMMA = 1.0
REWARD_GE_CANDIDATES = [5.0, 10.0, 15.0, 20.0]  # candidate GE durations (s)

# ── Multi-objective selection weights (Pareto Z1/Z2/Z3 + _dctsp_eval_action) ──
# Z1 = net passenger delay (THIS junction), Z2 = downstream-junction impact
# (also passenger delay), Z3 = residual bus lateness (schedule, seconds).
# Pure-delay objective with a SMALL schedule term: delay dominates, lateness
# only breaks near-ties. (Before 2026-09-10 these keys did not exist, so the
# engine fell back to (1,1,1) while _spm was force-zeroed to (0,0,0) by the
# propagation copy -- meaning _dctsp_eval_action rows ignored delay weight
# entirely. These explicit values unify both layers on one objective.)
WOBJ_ALPHA = 1.0   # Z1 passenger-delay weight
WOBJ_BETA = 1.0    # Z2 downstream passenger-delay weight
WOBJ_GAMMA = 0.1   # Z3 schedule-lateness weight (small, tie-break only)

# ── CC ETA algorithm parameters ───────────────────────────────────────────────
COORDINATION_ALGO = "KALMAN"  # "KALMAN" | "SHOCKWAVE" | "OBJECTIVE" | "ADAPTIVE"
COORD_OBJ_ALPHA      = 1.0       # bus passenger-delay weight  (OBJECTIVE mode)
COORD_OBJ_BETA       = 0.5       # general-traffic weight      (OBJECTIVE mode)
PREARM_MAX_SIGMA_S   = 90.0      # max ETA uncertainty (s) to allow a pre-arm;
                                  #   gate = max(PREARM_MAX_SIGMA_S, 0.80 * ETA)
MAX_PREARM_HORIZON_S = 135.0      # pre-arm look-ahead window (s) — at least one cycle

import os as _os
import sys as _sys

# ── Bundle-first import guard ──────────────────────────────────────────
# A stale `shared_tsp_engine/` package elsewhere on sys.path (e.g. an old
# working folder) SHADOWS this bundle's engine: same import name, older code,
# silent wrong-version execution (proven 2026-09-06 -- a pre-September engine
# ran while the bundle had newer code, making the MARL/MEAS A/B byte-identical
# and hiding every engine-side fix). This block drops any FOREIGN copy BEFORE
# the real import below and pins the bundle root first. A bundle copy already
# loaded is left alone (learner Q-tables live in module state and must persist
# across replications in one session).
def _bundle_guard():
    _roots = []
    try:
        # NOTE: inside a function dir() lists LOCAL names, so `"__file__" in
        # dir()` was ALWAYS False -- the bundle root from __file__ was never
        # added and the guard fell back to sys.path order, loading a FOREIGN
        # shared_tsp_engine copy (repo-root / C:\AimsunPackages). That is why
        # engine edits never took effect while logs still landed in the bundle
        # (LOG_DIR reads the module global __file__ correctly). Read it from
        # module globals so the bundle root goes FIRST. (fixed 2026-09-07)
        _cf = globals().get('__file__')
        if _cf:
            _roots.append(_os.path.dirname(_os.path.dirname(
                _os.path.abspath(_cf))))
    except Exception:
        pass
    _roots.extend(list(_sys.path))
    try:
        _roots.append(_os.getcwd())
    except Exception:
        pass
    # Filesystem fallback: walk UP from cwd to the drive root. Covers the
    # case where neither __file__ nor sys.path reveals the bundle (proven
    # 2026-09-06: Aimsun console cwd = install dir, shadow resolved instead).
    try:
        _d = _os.path.abspath(_os.getcwd())
        while True:
            if _d not in _roots:
                _roots.append(_d)
            _parent = _os.path.dirname(_d)
            if _parent == _d:
                break
            _d = _parent
    except Exception:
        pass
    _roots.append(r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5")
    _root = None
    for _r in _roots:
        try:
            if (_os.path.isfile(_os.path.join(_r, "shared_tsp_engine", "engine.py"))
                    and _os.path.isfile(_os.path.join(_r, "kg", "intersection_controller.py"))):
                _root = _os.path.abspath(_r)
                break
        except Exception:
            continue
    if _root is None:
        return
    if _root not in _sys.path:
        _sys.path.insert(0, _root)
    _rl = _root.lower()
    for _mn in [m for m in list(_sys.modules)
                if m == "shared_tsp_engine" or m.startswith("shared_tsp_engine.")]:
        try:
            _mf = getattr(_sys.modules[_mn], "__file__", "") or ""
            if _mf and _os.path.abspath(_mf).lower().startswith(_rl):
                continue  # ours: keep (learner state lives here)
            del _sys.modules[_mn]
            print(f"[BUNDLE-GUARD] dropped foreign module {_mn} "
                  f"({_mf or 'no file'}) -- using bundle {_root}")
        except Exception:
            pass


try:
    _bundle_guard()
except Exception:
    pass
try:
    del _bundle_guard
except Exception:
    pass

from Simulation_Stats import SimulationStats
stats = SimulationStats(CONTROL_MODE, verbose=VERBOSE)

from intersection_configs import INTERSECTIONS_CONFIG, INTERSECTION_GROUPS
try:
    from intersection_configs import CORRIDOR_ROUTE_GROUPS as _cfg_route_groups
except ImportError:
    _cfg_route_groups = None
try:
    from intersection_configs import TSP_ACTIVE_INTERSECTIONS as _cfg_active_ints
except ImportError:
    _cfg_active_ints = None

# Full corridor route order (including unmanaged system junctions between managed nodes).
# Loaded from intersection_configs.py; falls back to legacy hardcoded definition.
if _cfg_route_groups is not None:
    CORRIDOR_ROUTE_GROUPS = _cfg_route_groups
else:
    CORRIDOR_ROUTE_GROUPS = {
        "logan_north": [17249, 17308, 17383, 17498, 17628, 17963, 18044, 18942],
        "logan_south": [19196, 19363, 19474, 19882, 21895],
    }

TSP_ACTIVE_INTERSECTIONS = None
_bus_type_needs_recheck = False   # set True at AAPIInit when bus_pos unresolved

# DynaROPAC optimizer — imported lazily so controller loads even without it.
try:
    from dynaropac_controller import (
        DynaROPACOptimizer, IntersectionState, ApproachState,
        BusState, PhaseDefinition,
    )
    _DYNAROPAC_AVAILABLE = True
except Exception as _dyn_err:
    _DYNAROPAC_AVAILABLE = False
    DynaROPACOptimizer = None

controllers = {}

# Global DynaROPAC optimizer instance (shared across all intersections)
_dynaropac_optimizer = None
# Evaluate DYNAOPAC_HARMONY once per second (every simulation step)
_DYNAROPAC_EVAL_INTERVAL_S = 1.0
_dynaropac_last_eval_t: float = -999.0
# CSV for DYNAOPAC decision log: records all durations tested + delays for plotting
_DYNAROPAC_DECISION_CSV: str = ""
_dynaropac_decision_header_written: bool = False


# =============================================================================
# URTSP CONFIGURATION  (per-intersection overrides go in INTERSECTIONS_CONFIG)
# These are the defaults used when a key is absent from the config dict.
# =============================================================================
URTSP_DEFAULTS = {
    # Green extension added to nominal bus-phase duration (seconds)
    "GE_extension":            10.0,
    # Phase insertion: minimum inserted duration before exit is checked
    "insertion_min_duration":  5.0,
    # Phase insertion: safety cap (covers full bus phase if exit det. misses)
    "insertion_max_duration":  15.0,
    # One TSP per cycle — reset window (seconds)
    "cycle_length":           135.0,
    # Detection window (metres) — widens call zone upstream to prevent
    # buses skipping zone between 1-second simulation steps (~14 m/s at 50 km/h)
    "detection_window_m":      20.0,
    # PT line IDs to prioritise — empty = all lines eligible
    "priority_pt_line_ids":    [],
}


# Active TSP tracking for logging
_tsp_active_vehicles = {}   # {veh_id: (strategy_name, start_time, inter_id)}


# =============================================================================
# GLOBAL BUS FOCUS PRIORITY
# =============================================================================
# When a bus is being actively served (TSP granted) at any intersection, it
# becomes the "focus bus".  Other intersections defer new independent TSP
# requests for DIFFERENT buses until the focus bus completes or times out.
# Requests for the SAME focus bus (e.g. at the next downstream junction) are
# always allowed.  This prevents multiple buses competing for priority
# simultaneously and ensures the corridor gives its attention to one bus at a
# time.
#
# The focus is released when:
#   - The active TSP at the focus junction completes (strategy → 0)
#   - The focus bus exits the corridor
#   - A timeout of _FOCUS_TIMEOUT_S elapses (safety net)
#
# Logged as [BUS_FOCUS] in the Aimsun log and recorded in the detection CSV
# with tier="focus_acquire" / "focus_release" / "focus_suppress".
# =============================================================================
_FOCUS_TIMEOUT_S  = 60.0    # auto-release if focus bus stalls
_focus_bus_id:     int   = -1
_focus_jct_id:     int   = -1
_focus_start_t:    float = -1.0
_focus_history:    list  = []  # [(start_t, end_t, veh_id, jct_id, outcome)]
# Junctions the focus bus has already been served at; these are unblocked so
# other buses can resume independent TSP behind the focus bus.
_focus_passed_jcts: set  = set()


# =============================================================================
# HELPERS (module-level, no state)
# =============================================================================


# =============================================================================
# SIMULATION CONTROL — stop sim from Python for debugging
# =============================================================================


# =============================================================================
# SHARED ENGINE — IntersectionController, CorridorCoordinator, and all AAPI
# callbacks live in shared_tsp_engine/engine.py so kg/ and logan_road_new/
# run identical logic instead of two copy-pasted files drifting apart.
# Everything above this point (config constants, logging flags, small
# stable helpers) stays here per-corridor because batch_runner.py regex-
# patches those lines directly in this file before each run.
# =============================================================================
_CORRIDOR_DIR = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.dirname(_CORRIDOR_DIR)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import shared_tsp_engine.engine as _engine
_engine.bind_config(globals())

from shared_tsp_engine.engine import (
    AAPILoad, AAPIInit, AAPISimulationReady, AAPIManage, AAPIPostManage,
    AAPIFinish, AAPIUnLoad, AAPIPreRouteChoiceCalculation,
    AAPIVehicleStartParking, AAPIEnterVehicle, AAPIExitVehicle,
    AAPIEnterVehicleSection, AAPIExitVehicleSection, AAPIEnterPedestrian,
    AAPIExitPedestrian, AAPIActionActivated, AAPIActionDeactivated,
)
