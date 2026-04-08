from AAPI import *
import sys
import csv
import collections
AKIPrintString("PYTHON EXECUTABLE: " + sys.executable)
AKIPrintString("PYTHON VERSION: " + sys.version)
sys.path.insert(0, r"C:\AimsunPackages")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import random
import datetime
import os
import math

# =============================================================================
# LOGGING FLAGS  —  set each True/False to control verbosity
# All critical errors are always printed regardless of these flags.
# =============================================================================

# ── Core control modes ────────────────────────────────────────────────────────
LOG_HARMONY   = False  # [HARMONY]    GE/insertion decisions in HARMONY mode
LOG_URTSP     = False   # [URTSP]      detection/extension/insertion in URTSP mode
LOG_TSP_EVT   = False   # [TSP EVENT]  TSP start/end/cooldown markers (all modes)

# ── Initialisation ────────────────────────────────────────────────────────────
LOG_INIT      = False   # [INIT]       controller creation, phase list, veh types
LOG_NODE_ID   = False   # [NODE_ID]    node-ID auto-resolution / AimsunNodeID hints
LOG_SECTION   = False  # [SECTION]    incoming-section & topology init detail
LOG_JUNC_XY   = False  # [JUNC_XY]   junction centroid coordinate resolution
LOG_SIDE_DISC = False  # [SIDE_DISC]  side-street section discovery

# ── Group-Based controller ────────────────────────────────────────────────────
LOG_GB        = False  # [GB]         phase build/expand/terminate decisions
LOG_GB_BUS    = False   # [GB BUS]     bus detection events inside GroupBasedController
LOG_GB_DELAY  = False  # [GB DELAY]   per-step delay computation in GroupBasedController
LOG_GB_STATE  = False   # [GB STATE]   state-machine transitions + watchdog resets

# ── PT / bus detection ────────────────────────────────────────────────────────
LOG_PT_SCAN   = False  # [PT_SCAN]    PT-line periodic diagnostic (every 5 min)
LOG_DEMAND    = False  # [DEMAND]     vehicle-type position detection at startup

# ── Delay & statistics ────────────────────────────────────────────────────────
LOG_STATS     = True   # [STATS]      end-of-simulation results summary
LOG_DELAY     = False  # [DELAY]      IntersectionController collect_delay detail

# ── Diagnostic heartbeat ──────────────────────────────────────────────────────
LOG_HEARTBEAT = False  # [HEARTBEAT]  per-60s state dump (phase/flag/queue/flow)
LOG_CORRIDOR  = False   # [CORRIDOR]   corridor-group coordination events and state

# =============================================================================
# MASTER CONSOLE SWITCH
# VERBOSE = True  → all enabled flags print to Aimsun console AND log file
# VERBOSE = False → NOTHING prints to the Aimsun console; everything still
#                   goes to the log file so you can review it after the run.
#                   Critical errors (simulation halted) are always shown.
# =============================================================================
VERBOSE = False

try:
    LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
except Exception:
    LOG_DIR = r"D:\Aimsun_Results\Logs"
os.makedirs(LOG_DIR, exist_ok=True)

timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(LOG_DIR, f"Aimsun_TSP_Log_{timestamp}.txt")


def resolve_vehicle_type_positions():
    """
    Dynamically detect vehicle type internal positions.
    Works with Car, Truck, Bus or any custom naming.
    """
    car_pos = -1
    bus_pos = -1
    truck_pos = -1

    n_types = AKIVehGetNbVehTypes()

    for pos in range(1, n_types + 1):
        raw = AKIVehGetVehTypeName(pos)
        try:
            name = AKIConvertToAsciiString(raw, True).lower()
        except:
            name = str(raw).lower()
        '''
        _vprint(f"[VEH DETECT] pos={pos} name={name}")
        '''
        if "bus" in name:
            bus_pos = pos
        elif "truck" in name:
            truck_pos = pos
        elif "car" in name:
            car_pos = pos

    return car_pos, bus_pos, truck_pos

def log_to_file(message, force=False):
    """
    Write message to log file.  Only print to the Aimsun console when
    VERBOSE=True OR force=True (used for critical errors that must always show).
    """
    full_msg = f"{datetime.datetime.now().strftime('%H:%M:%S')} | {message}"
    if VERBOSE or force:
        AKIPrintString(full_msg)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(full_msg + "\n")
    except Exception as _log_err:
        AKIPrintString(f"[LOG] file write failed ({LOG_FILE}): {_log_err}")


def _vprint(msg):
    """
    Verbose-gated console print.
    Calls AKIPrintString only when VERBOSE=True.
    Use this instead of bare AKIPrintString for all non-critical output so
    that setting VERBOSE=False silences everything in one place.
    """
    if VERBOSE:
        AKIPrintString(msg)


# =============================================================================
# CONTROL MODE SWITCH
# "RL"                  — reinforcement learning agent
# "HARMONY"             — harmony search TSP (phase-based)
# "URTSP"               — Unrestricted TSP (URTSP): green extension + phase insertion
# "GROUP_BASED"         — demand-responsive signal group control (3-tier bus detection)
# "GROUP_BASED_URTSP"   — group-based SG control + Unrestricted TSP (URTSP) upstream-detector bus detection
# "GROUP_BASED_HARMONY" — group-based SG control + harmony-search-optimised bus extension
# =============================================================================
CONTROL_MODE = "HARMONY"   # set control mode here
GROUP_BASED_BUS_PRIORITY = True

# Set True to enable Kalman-filter based corridor green-wave coordination.
# When True, granting bus priority at junction[i] pre-arms junction[i+1..i+3]
# using a 1D Kalman tracker so downstream greens are ready on arrival.
# Set False to run each junction independently (original behaviour).
COORDINATED_TSP = False

TSP_ACTIVE_INTERSECTIONS = None
_bus_type_needs_recheck = False   # set True at AAPIInit when bus_pos unresolved

from Simulation_Stats import SimulationStats
stats = SimulationStats(CONTROL_MODE, verbose=VERBOSE)

from intersection_configs import INTERSECTIONS_CONFIG, INTERSECTION_GROUPS

controllers = {}


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
    "insertion_max_duration":  25.0,
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
# HELPERS (module-level, no state)
# =============================================================================

def GetPhaseDuration(IntersectionID, PhaseID, timeSta):
    normalDurationP = doublep()
    maxDurationP    = doublep()
    minDurationP    = doublep()
    ECIGetDurationsPhase(IntersectionID, PhaseID, timeSta,
                         normalDurationP, maxDurationP, minDurationP)
    return normalDurationP.value()


def ShockwaveSpeed1(UpFlow, JamDen, ArrDen):
    den = JamDen - ArrDen
    return (0 - UpFlow) / den * 1000 / 3600 if abs(den) > 1e-6 else 0.0

def ShockwaveSpeed2(SaturationFlow, SaturationDen, JamDen):
    den = SaturationDen - JamDen
    return (SaturationFlow - 0) / den * 1000 / 3600 if abs(den) > 1e-6 else 0.0

def ShockwaveSpeed3(SaturationFlow, UpFlow, SaturationDen, UpDen):
    den = SaturationDen - UpDen
    return (SaturationFlow - UpFlow) / (den if abs(den) > 1e-6 else 1e-6) * 1000 / 3600

def ShockwaveSpeed4(SaturationFlow, JamDen, SaturationDen):
    den = JamDen - SaturationDen
    return (0 - SaturationFlow) / den * 1000 / 3600 if abs(den) > 1e-6 else 0.0


def safe_float(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    return result


def harmony_search(objective_function, lower_bound, upper_bound,
                   max_iterations, harmony_memory_size, hmcr, par, bandwidth, time):
    harmony_memory = [random.uniform(lower_bound, upper_bound)
                      for _ in range(harmony_memory_size)]
    fitness_values = [objective_function(h, time) for h in harmony_memory]

    for _ in range(max_iterations):
        if random.uniform(0, 1) < hmcr:
            new_harmony = random.choice(harmony_memory)
            if random.uniform(0, 1) < par:
                new_harmony += random.uniform(-bandwidth, bandwidth)
        else:
            new_harmony = random.uniform(lower_bound, upper_bound)

        new_harmony = max(lower_bound, min(upper_bound, new_harmony))
        new_fitness = objective_function(new_harmony, time)
        worst_index = int(np.argmax(fitness_values))

        if new_fitness < fitness_values[worst_index]:
            harmony_memory[worst_index] = new_harmony
            fitness_values[worst_index] = new_fitness

    return harmony_memory[int(np.argmin(fitness_values))]


# =============================================================================
# SIMULATION CONTROL — stop sim from Python for debugging
# =============================================================================

def stop_simulation(reason=""):
    """Immediately halt simulation. Always prints regardless of VERBOSE flag."""
    AKIPrintString(f"[STOP] ========== SIMULATION HALTED ==========")
    AKIPrintString(f"[STOP] Reason: {reason}")
    AKIPrintString(f"[STOP] =========================================")
    log_to_file(f"[STOP] {reason}", force=True)
    try:
        AKISimulationStop()
    except Exception:
        try:
            AKISetSimulationStopped()
        except Exception:
            pass


# =============================================================================
# DEMAND MONITOR — inspect OD demand per vehicle type
# Call from AAPILoad() to see demand before/after any boost
# =============================================================================

class DemandMonitor:
    """Print OD demand breakdown per vehicle type and slice."""

    def __init__(self):
        self.centroids = [
            AKIInfNetGetCentroidId(i)
            for i in range(AKIInfNetNbCentroids())
        ]

    def print_demand(self, label=""):
        n_types = AKIVehGetNbVehTypes()
        totals  = {}
        for vt in range(0, n_types + 1):
            num_slices = AKIODDemandGetNumSlicesOD(vt)
            if num_slices <= 0:
                continue
            vt_total = 0.0
            for sl in range(num_slices):
                for orig in self.centroids:
                    for dest in self.centroids:
                        if orig == dest:
                            continue
                        d = AKIODDemandGetDemandODPair(orig, dest, vt, sl)
                        if d > 0:
                            vt_total += d
            totals[vt] = vt_total

        _vprint(f"===== OD DEMAND {label} =====")
        _vprint(f"  vt=0 (ALL types) : {totals.get(0, 0):.1f}")
        for vt in range(1, n_types + 1):
            _vprint(f"  vt={vt}            : {totals.get(vt, 0):.1f}")
        _vprint(f"  centroids={len(self.centroids)}")









# ── ADD THIS CONSTANT AT TOP OF FILE ──────────────────────────────────────
BUS_FREQUENCY_MULTIPLIER = 1        # 2 = double buses, 3 = triple, etc.
TARGET_PT_LINE_IDS       = []       # [] = all lines, or e.g. [101, 102]

# ── ADD THIS FUNCTION ─────────────────────────────────────────────────────

def _vehicle_type_name(pos):
    """
    Return the lowercase name string for vehicle type at position pos.

    Aimsun versions differ in what AKIVehGetVehTypeName returns:
      - Newer SDK  : a Python str directly
      - Older SDK  : an opaque SWIG 'unsigned short *' object that needs
                     AKIConvertToAsciiString to decode
      - Some builds: AKIConvertToAsciiString itself returns another SWIG
                     object (the bug seen in the log: '<swig object...>')

    We try every known decoding path and fall back to an empty string rather
    than letting a '<swig object…>' leak into the keyword matching.
    """
    try:
        raw = AKIVehGetVehTypeName(pos)
    except Exception:
        return ""

    # Path 1 — raw is already a plain Python string
    if isinstance(raw, str):
        return raw.lower()

    # Path 2 — AKIConvertToAsciiString returns a plain string
    try:
        converted = AKIConvertToAsciiString(raw, True)
        if isinstance(converted, str):
            return converted.lower()
        # converted is also a SWIG object — try str() on it and check
        s = str(converted)
        if "<swig" not in s:
            return s.lower()
    except Exception:
        pass

    # Path 3 — try AKIConvertToAsciiString with False flag (some versions differ)
    try:
        converted2 = AKIConvertToAsciiString(raw, False)
        if isinstance(converted2, str):
            return converted2.lower()
        s2 = str(converted2)
        if "<swig" not in s2:
            return s2.lower()
    except Exception:
        pass

    # Path 4 — try direct str() on the raw object
    s_raw = str(raw)
    if "<swig" not in s_raw:
        return s_raw.lower()

    # Path 5 — try bytes decoding (works when raw is a pointer to a C string)
    try:
        import ctypes
        ptr_val = int(str(raw).split("0x")[1].split(">")[0], 16)
        name_bytes = ctypes.string_at(ptr_val)
        return name_bytes.decode("utf-8", errors="replace").lower()
    except Exception:
        pass

    # All paths failed — return empty; caller will rely on PT-line inference
    return ""


def _scan_named_vehicle_type_positions():
    car_pos = -1
    bus_pos = -1
    truck_pos = -1
    nb_types = AKIVehGetNbVehTypes()
    # Always log type names to file so we can diagnose non-English/coded type names
    log_to_file(f"[VEH SCAN] Total vehicle types: {nb_types}")
    for pos in range(1, nb_types + 1):
        name_str = _vehicle_type_name(pos)
        log_to_file(f"[VEH SCAN]   type pos={pos} name='{name_str}'")
        if not name_str:
            log_to_file(
                f"[VEH SCAN]   WARNING pos={pos} name unresolvable — "
                f"will rely on PT-line inference for bus type"
            )
        if bus_pos <= 0 and any(x in name_str for x in ("bus", "transit", "pt", "autobus", "ligne", "omnibus")):
            bus_pos = pos
        elif truck_pos <= 0 and any(x in name_str for x in ("truck", "heavy", "hgv", "lgv", "goods", "freight")):
            truck_pos = pos
        elif car_pos <= 0 and any(x in name_str for x in ("car", "pv", "private", "auto", "vehicle", "voiture", "pkw")):
            car_pos = pos
    return car_pos, bus_pos, truck_pos


def _infer_bus_type_pos_from_pt():
    """
    Infer the bus vehicle-type position by counting vehicle types on PT lines.
    Also tries AKIPTGetVehTypeOfLine (faster; available in some SDK versions).
    Returns the most common type position seen on PT lines, or -1 if none found.
    """
    counts = collections.Counter()

    try:
        n_lines = AKIPTGetNumberLines()
    except Exception:
        n_lines = 0

    for li in range(n_lines):
        try:
            line_id = AKIPTGetIdLine(li)
        except Exception:
            continue

        # Fast path: ask the line directly for its vehicle type (SDK 22+)
        # Wrapped in getattr so it fails silently if this API isn't available.
        try:
            _fn = globals().get("AKIPTGetVehTypeOfLine")
            if _fn is not None:
                vt = _fn(line_id)
                if vt > 0:
                    counts[int(vt)] += 10   # weight fast-path hits
                    continue
        except Exception:
            pass

        # Slow path: iterate vehicles on the line
        try:
            n_veh = AKIGetNbVehiclesFollowingPTLine(line_id)
        except Exception:
            continue
        for vi in range(n_veh):
            try:
                veh_id = AKIGetVehicleFollowingPTLine(line_id, vi)
                inf = AKIPTVehGetInf(veh_id)
                if getattr(inf, 'report', -1) >= 0 and getattr(inf, 'type', -1) > 0:
                    counts[int(inf.type)] += 1
            except Exception:
                continue

    return counts.most_common(1)[0][0] if counts else -1


def _choose_car_type_pos(bus_pos, truck_pos, preferred_pos=-1):
    nb_types = AKIVehGetNbVehTypes()
    exclude = {p for p in (bus_pos, truck_pos) if p and p > 0}
    if preferred_pos > 0 and preferred_pos not in exclude:
        return preferred_pos
    for pos in range(1, nb_types + 1):
        if pos in exclude:
            continue
        name_str = _vehicle_type_name(pos)
        if any(x in name_str for x in ("car", "pv", "private", "auto")):
            return pos
    for pos in range(1, nb_types + 1):
        if pos not in exclude:
            return pos
    return -1





class GroupBasedController:

    # State constants
    IDLE       = "IDLE"
    GREEN      = "GREEN"
    INTERGREEN = "INTERGREEN"

    def __init__(self, junction_id: int, gb_config: dict, stats_ref=None,
                 tsp_mode: str = "basic"):
        """
        Parameters
        ----------
        tsp_mode : str
            "basic"   — 3-tier PT-scan + section-scan + rising-edge detection
            "urtsp"   — URTSP upstream-detector position scan (uses UpDetList geometry)
            "harmony" — same detection as "basic" but bus extension duration is
                        optimised by harmony search rather than granted as a flat cap
        """
        self.junction_id = junction_id
        self.node_id     = junction_id   # Aimsun internal node ID (same as junction_id by default)
        self._stats      = stats_ref     # SimulationStats reference for TSP event recording
        self.tsp_mode    = tsp_mode      # "basic" | "urtsp" | "harmony"

        self.all_sg           = list(gb_config["sg_list"])
        self.min_green        = dict(gb_config["min_green"])
        self.max_green        = dict(gb_config["max_green"])
        self.sections         = list(gb_config.get("sections", []))
        self.bus_det          = list(gb_config.get("bus_det", []))
        self.bus_sg           = gb_config.get("bus_sg", None)
        # Phase structure from config — used as ECI-fallback in _derive_and_save_conflict_matrix
        self._phase_sg_nested = gb_config.get("phase_sg_nested", [])
        self.intergreen_dur   = float(gb_config.get("intergreen_duration",   4.0))
        self.starvation_thresh= float(gb_config.get("starvation_threshold", 4000.0))
        self.max_extension    = float(gb_config.get("max_extension",         15.0))

        # Occupancy factors for delay weighting
        self.CarOcc   = float(gb_config.get("CarOcc",   1.5))
        self.BusOcc   = float(gb_config.get("BusOcc",   40.0))
        self.TruckOcc = float(gb_config.get("TruckOcc", 1.5))

        # Vehicle type positions — inherit from stats if available, else scan
        self.bus_type_pos = -1
        self.car_type_pos = -1
        if stats_ref is not None:
            self.bus_type_pos = getattr(stats_ref, '_bus_pos', -1)
            self.car_type_pos = getattr(stats_ref, '_car_pos', -1)
        if self.bus_type_pos <= 0 or self.car_type_pos <= 0:
            try:
                _cp, _bp, _tp = resolve_vehicle_type_positions()
                if self.bus_type_pos <= 0:
                    self.bus_type_pos = _bp
                if self.car_type_pos <= 0:
                    self.car_type_pos = _cp
                self._truck_pos = _tp
            except Exception:
                pass

        # Conflict matrix — only load from CSV when explicitly configured;
        # otherwise always re-derive from the live Aimsun signal plan so that
        # self.all_sg is always validated against the actual model (prevents
        # "cpsignal group N unknown" errors from stale auto-saved CSVs).
        cm_csv = gb_config.get("conflict_matrix_csv")
        if cm_csv and os.path.isfile(cm_csv):
            self.conflict_matrix = self._load_conflict_matrix(cm_csv)
            # Prune self.all_sg / bus_sg to only positions the CSV confirms,
            # mirroring what _derive_and_save_conflict_matrix does at runtime.
            if self.conflict_matrix:
                _valid = set(self.conflict_matrix.keys())
                _dropped = set(self.all_sg) - _valid
                if _dropped:
                    _vprint(
                        f"[GB] jct={junction_id} CSV prune: dropping "
                        f"{sorted(_dropped)} from sg_list (not in conflict matrix)"
                    )
                self.all_sg = sorted(_valid & set(self.all_sg))
                if self.bus_sg is not None and self.bus_sg not in _valid:
                    _vprint(
                        f"[GB] jct={junction_id} bus_sg={self.bus_sg} not in "
                        f"conflict matrix — clearing bus_sg"
                    )
                    self.bus_sg = None
        else:
            # Always re-derive from the live Aimsun signal plan and persist to CSV.
            # This validates self.all_sg against the actual junction model every run.
            self.conflict_matrix = self._derive_and_save_conflict_matrix()

        # Pre-compute maximum-compatible phase groups (Bron-Kerbosch clique cover).
        # Done once here so _build_new_phase and _activate_for_bus always use the
        # globally-optimal groups — not a greedy per-step expansion from one seed.
        self.phase_groups: list = []
        self._precompute_phase_groups()

        # Section tracking — build incoming_sections from junction topology
        self.incoming_sections = []
        self._junction_xy      = None
        self._side_sections    = None   # discovered lazily
        self._initialize_sections()

        # Delay tracking state
        self._cum_sec_prev   = {}   # {(sec_id, 'car'|'bus'): (cum_dt*cnt, cnt)}
        self._side_stop_prev = {}   # {veh_id: last_stop_time_s}
        self._side_sec_ff    = {}   # {sec_id: free_flow_speed m/s}
        self._delay_log_t    = -1.0
        self._side_prune_t   = 0.0

        # State machine
        self.state          = self.IDLE
        self.sg_list        = []              # currently green SG positions
        self.non_activated  = set(self.all_sg)  # legacy per-SG tracking (kept for starvation)
        self._group_served  = set()           # indices into phase_groups served this cycle
        self.lower_time     = {}
        self.upper_time     = {}
        self.intergreen_end = 0.0

        # Watchdog: detect stuck states (stuck IDLE / stuck INTERGREEN / all-red GREEN)
        # and force an emergency reset back to a live phase.
        # Timeout = 2 * the longest single-phase max_green, minimum 60 s.
        _max_mg = max(self.max_green.values()) if self.max_green else 40.0
        self._watchdog_timeout = max(60.0, 2.0 * _max_mg)
        self._last_phase_t     = -1.0   # sim-time of last successful phase activation
        self._watchdog_armed   = False  # True once first step() has been called

        # Bus priority
        self.bus_request       = None         # SG position waiting for service
        self.extension_used    = 0.0          # cumulative extension granted
        self.prev_bus_presence = {det: 0 for det in self.bus_det}
        # Junction-level TSP cooldown: after ANY bus phase is served, suppress all
        # new bus requests until this time.  This guarantees normal round-robin can
        # serve every phase group (including low-demand right-turn groups) before
        # another bus can hijack the cycle — regardless of how many detectors fire.
        # Duration is configured via "tsp_cycle_cooldown" in GroupBasedConfig;
        # default 60 s gives roughly one non-bus cycle at a typical 135 s plan.
        self._tsp_cycle_cooldown  = float(gb_config.get("tsp_cycle_cooldown", 60.0))
        self._tsp_cooldown_until  = -1.0      # sim time before which bus requests are blocked

        # TSPStrategy (matches original group-based algorithm):
        #   0 = no bus priority active
        #   1 = green extension  (bus SG already green — upper_time pushed out)
        #   2 = phase insertion compatible  (bus SG added to current phase)
        #   3 = phase insertion forced  (bus SG incompatible, current phase terminated early)
        self.tsp_strategy = 0

        # URTSP-mode: cache detector geometry for position-based bus scan
        # {det_id: (section_id, init_pos_m, final_pos_m)}
        self._urtsp_det_geometry: dict = {}
        self._bus_eta: float | None = None      # seconds until bus reaches stop line
        self._bus_det_time: float | None = None  # sim time when ETA was calculated
        if tsp_mode == "urtsp":
            self._build_urtsp_geometry()

        # ETA-aware detection parameters.
        # detection_zone_m  — only detect buses within this Euclidean distance of the
        #   junction centroid.  Replaces the old hard-coded 500 m cap.  Smaller values
        #   prevent premature requests when the bus is too far away for TSP to help.
        # eta_min_s / eta_max_s — only fire a bus_request when the estimated time of
        #   arrival (ETA) is in [eta_min_s, eta_max_s].  If ETA > eta_max_s the bus is
        #   detected but the request is deferred (re-evaluated each step); if ETA < min
        #   the bus is already too close to benefit.
        self._detection_zone_m = float(gb_config.get("detection_zone_m", 300.0))
        self._eta_min_s        = float(gb_config.get("eta_min_s",  5.0))
        self._eta_max_s        = float(gb_config.get("eta_max_s", 60.0))
        # Set of section IDs that feed bus_sg (populated at reinitialise_from_model)
        # Used to classify detections as "front" (bus approach) or "side".
        self._bus_sg_sections: set = set()

        # Harmony-mode: search parameters (can be overridden via gb_config keys)
        self._harmony_memory_size = int(gb_config.get("harmony_memory_size", 10))
        self._harmony_hmcr        = float(gb_config.get("harmony_hmcr",        0.9))
        self._harmony_par         = float(gb_config.get("harmony_par",          0.3))
        self._harmony_bandwidth   = float(gb_config.get("harmony_bandwidth",    2.0))
        self._harmony_iterations  = int(gb_config.get("harmony_iterations",    50))

        # Starvation tracking (incremented per step when SG has demand but is red)
        self.wait_time = {sg: 0.0 for sg in self.all_sg}

        # Corridor coordinator back-reference — set by CorridorCoordinator.__init__
        # after all controllers are created.  None when not part of a corridor group
        # or when COORDINATED_TSP=False.
        self._corridor_coord = None

        _vprint(
            f"[GB] Junction {junction_id} | tsp_mode={tsp_mode} | "
            f"SGs={self.all_sg} | bus_sg={self.bus_sg} | "
            f"intergreen={self.intergreen_dur}s | "
            f"starvation={self.starvation_thresh}s | "
            f"max_ext={self.max_extension}s | "
            f"incoming_secs={self.incoming_sections}"
        )

    # =========================================================================
    # EMERGENCY RESET  ("reset phase")
    # =========================================================================

    def _emergency_reset(self, time: float, timeSta: float, reason: str):
        """
        Force the state machine back to a clean IDLE and immediately activate
        the first available phase group.  Called by the watchdog when signals
        are stuck (all-red, stuck INTERGREEN, or infinite IDLE loop without a
        phase being activated).

        This is the "reset phase" — a guaranteed recovery that always results
        in at least one SG going green, regardless of what caused the deadlock.
        """
        if LOG_GB_STATE:
            _vprint(
                f"[GB STATE] t={time:.1f} jct={self.junction_id} "
                f"⚠ EMERGENCY RESET — {reason}"
            )

        # If phase_groups is empty try to rebuild before giving up
        if not self.phase_groups:
            if self.conflict_matrix and self.all_sg:
                self._precompute_phase_groups()
                if LOG_GB_STATE:
                    _vprint(
                        f"[GB STATE] jct={self.junction_id} "
                        f"rebuilt phase_groups: {len(self.phase_groups)} groups"
                    )
            elif self.all_sg:
                # Absolute fallback: one group per SG (round-robin single-SG phases)
                self.phase_groups = [[sg] for sg in sorted(self.all_sg)]
                if LOG_GB_STATE:
                    _vprint(
                        f"[GB STATE] jct={self.junction_id} "
                        f"fallback: {len(self.phase_groups)} single-SG groups"
                    )

        # Wipe all transient state so the next _build_new_phase starts clean
        self.state          = self.IDLE
        self.sg_list        = []
        self.bus_request    = None
        self.tsp_strategy   = 0
        self.extension_used = 0.0
        self.lower_time.clear()
        self.upper_time.clear()
        self._group_served  = set()
        self.non_activated  = set(self.all_sg)
        self._last_phase_t  = time

        # Activate a phase immediately — signals are already all-red, no need for
        # another intergreen gap before going green.
        queue = self._compute_queue()
        self._build_new_phase(time, timeSta, queue)

        if LOG_GB_STATE:
            _vprint(
                f"[GB STATE] t={time:.1f} jct={self.junction_id} "
                f"reset complete — state={self.state} sg_list={self.sg_list}"
            )

    # =========================================================================
    # MAIN STEP
    # =========================================================================

    def step(self, time: float, timeSta: float):
        """Called every simulation step from IntersectionController.update()."""
        queue = self._compute_queue()

        # ── Watchdog: detect and recover from stuck states ("reset phase") ────
        if not self._watchdog_armed:
            self._watchdog_armed = True
            self._last_phase_t   = time     # seed watchdog clock on first call

        stuck = time - self._last_phase_t
        _wd   = self._watchdog_timeout

        stuck_idle       = self.state == self.IDLE        and stuck > _wd
        stuck_intergreen = self.state == self.INTERGREEN  and stuck > _wd
        stuck_red_green  = (self.state == self.GREEN
                            and not self.sg_list and stuck > _wd)

        if stuck_idle or stuck_intergreen or stuck_red_green:
            reason = (
                f"stuck {self.state} for {stuck:.0f}s "
                f"(sg_list={self.sg_list}, "
                f"phase_groups={len(self.phase_groups)}, "
                f"all_sg={self.all_sg})"
            )
            self._emergency_reset(time, timeSta, reason)
            return

        # ── Normal state machine ───────────────────────────────────────────────
        if self.state != self.INTERGREEN:
            if self.tsp_mode == "urtsp":
                self._detect_bus_urtsp(time)
            else:
                # "basic" and "harmony" both use 3-tier PT/section/rising-edge detection;
                # harmony only differs in how it *grants* the extension, not how it detects.
                self._detect_bus(time)

        self._update_wait_times(queue)
        self.collect_delay(time, timeSta)

        if self.state == self.IDLE:
            self.tsp_strategy = 0          # reset when entering a fresh phase decision
            if self.bus_request:
                self._activate_for_bus(time, timeSta, queue)
                self.bus_request = None
            else:
                self._build_new_phase(time, timeSta, queue)
            self._last_phase_t = time      # any IDLE activation resets the watchdog
            return

        if self.state == self.GREEN:
            self._handle_bus_logic(time, queue)
            self._update_time_bounds(time)
            self._apply_signals(time, timeSta)   # apply current phase signals first
            self._check_termination(time, queue) # then check — _force_intergreen sets
            if self.sg_list:                     # at least one SG is green: healthy
                self._last_phase_t = time
            return                               # all-red cleanly without being overridden

        if self.state == self.INTERGREEN:
            if time >= self.intergreen_end:
                if LOG_GB_STATE:
                    _vprint(
                        f"[GB STATE] t={time:.1f} jct={self.junction_id} "
                        f"INTERGREEN→IDLE "
                        f"(end={self.intergreen_end:.1f} groups={len(self.phase_groups)})"
                    )
                self.state = self.IDLE
                queue = self._compute_queue()
                self._build_new_phase(time, timeSta, queue)
                self._last_phase_t = time
            return

    # =========================================================================
    # CONFLICT MATRIX LOADER
    # =========================================================================

    @staticmethod
    def _load_conflict_matrix(csv_path: str) -> dict:
        """
        Load conflict matrix from CSV file.
        Returns {row_sg: {col_sg: 0|1}} where 0=compatible, 1=conflict.

        Expected CSV format (first row = header, first col = row label):
            ,1,2,3,...
            1,0,0,1,...
            2,0,0,1,...
        """
        matrix = {}
        try:
            with open(csv_path, "r", newline="", encoding="utf-8") as f:
                rows = [r for r in csv.reader(f) if any(c.strip() for c in r)]

            # header row: ['', '1', '2', ..., 'N']
            col_ids = [int(c.strip()) for c in rows[0][1:] if c.strip()]

            for data_row in rows[1:]:
                if not data_row[0].strip():
                    continue
                row_sg = int(data_row[0].strip())
                matrix[row_sg] = {
                    col_sg: int(val.strip())
                    for col_sg, val in zip(col_ids, data_row[1:])
                    if val.strip()
                }

            _vprint(
                f"[GB] Conflict matrix loaded from {csv_path} "
                f"({len(matrix)} signal groups)"
            )
        except Exception as e:
            if LOG_GB: AKIPrintString(f"[GB] ERROR loading conflict matrix {csv_path}: {e}")
        return matrix

    # =========================================================================
    # QUEUE COMPUTATION
    # =========================================================================

    def _compute_queue(self) -> dict:
        """Return {sg_id: vehicle_count} from configured section/lane mappings."""
        queue = {sg: 0 for sg in self.all_sg}
        for sec_cfg in self.sections:
            sec_id      = sec_cfg["section_id"]
            lane_groups = sec_cfg["lane_groups"]
            sg_ids      = sec_cfg["sg_ids"]
            if lane_groups is None:
                # Auto-built entry: count ALL vehicles in the section
                try:
                    total = max(AKIVehStateGetNbVehiclesSection(sec_id, True), 0)
                except Exception:
                    total = 0
                for sg_id in sg_ids:
                    queue[sg_id] = queue.get(sg_id, 0) + total
            else:
                counts = self._section_queue(sec_id, lane_groups)
                for sg_id, count in zip(sg_ids, counts):
                    queue[sg_id] = queue.get(sg_id, 0) + count
        return queue

    @staticmethod
    def _section_queue(section_id: int, lane_groups: list) -> list:
        """Count vehicles per lane group in a section."""
        lane_list = []
        num = AKIVehStateGetNbVehiclesSection(section_id, True)
        for i in range(num):
            lane_list.append(
                AKIVehStateGetVehicleInfSection(section_id, i).numberLane
            )
        counter = collections.Counter(lane_list)
        return [sum(counter.get(ln, 0) for ln in grp) for grp in lane_groups]

    # =========================================================================
    # BUS DETECTION
    # =========================================================================

    def _get_actionable_eta_max(self, time: float) -> float:
        """
        Compute the maximum ETA (seconds from now) for which firing a bus_request
        is still actionable.  If the bus is further away than this, the signal will
        have cycled past the useful window before it arrives.

        GREEN + bus_sg already active  → remaining green + max_extension budget
        GREEN + bus_sg not active       → remaining current phase + intergreen + one phase
        IDLE / INTERGREEN               → one typical phase duration (immediate insertion)
        Hard cap: self._eta_max_s (user-configured)
        """
        if self.state == self.GREEN and self.sg_list:
            if self.bus_sg in self.sg_list:
                remaining = max(0.0, self.upper_time.get(self.bus_sg, time) - time)
                window = remaining + self.max_extension
            else:
                max_remaining = max(
                    (max(0.0, self.upper_time.get(sg, time) - time)
                     for sg in self.sg_list),
                    default=0.0
                )
                # Budget: finish current phase + intergreen + one typical bus phase
                _avg = sum(self.max_green.get(sg, 40.0)
                           for sg in (self.phase_groups[0] if self.phase_groups else [])
                           ) / max(len(self.phase_groups[0]) if self.phase_groups else 1, 1)
                window = max_remaining + self.intergreen_dur + max(_avg, 10.0)
        else:
            # IDLE or INTERGREEN — bus phase can start very soon
            _bus_mg = self.max_green.get(self.bus_sg, 30.0) if self.bus_sg else 30.0
            window  = self.intergreen_dur + _bus_mg

        return min(window, self._eta_max_s)

    def _detect_bus(self, time: float):
        """
        ETA-aware 3-tier bus detection.

        Tier 1  — PT line vehicle coordinate scan (all approaches, uses XY distance)
        Tier 2  — Section scan for bus-type vehicles on incoming sections
        Tier 3  — Rising-edge detector presence (original behaviour, kept as fallback)

        Only fires a bus_request when the bus's ETA is inside the actionable window
        [_eta_min_s, _get_actionable_eta_max()].  This prevents:
          • Premature extension for buses still far away (green expires before arrival)
          • Useless requests for buses already past the stop-line

        Each detection is labelled "front" (bus-SG approach) or "side" (other approach)
        in the log so it is easy to distinguish NB/SB vs EW bus movements.
        """
        detected = False

        junc_xy = self._get_junction_xy()
        jx = jy = None
        if junc_xy is not None:
            jx, jy = junc_xy

        detection_zone_m  = self._detection_zone_m
        eta_max           = self._get_actionable_eta_max(time)

        def _approach_label(sec_id):
            """'front' if section feeds bus_sg, 'side' otherwise."""
            if self._bus_sg_sections and sec_id in self._bus_sg_sections:
                return "front"
            return "side"

        def _eta_from_dist(dist_m: float, speed_kmh: float) -> float:
            speed_ms = max(speed_kmh / 3.6, 1.0)
            return dist_m / speed_ms

        def _request_bus(veh_id, source, eta, dist_m, approach):
            if not self.bus_sg or self.bus_request is not None:
                return
            if time < self._tsp_cooldown_until:
                return
            # ETA gating — ignore if bus is too close or too far
            if eta < self._eta_min_s:
                if LOG_GB_BUS:
                    _vprint(
                        f"[GB BUS] t={time:.1f} jct={self.junction_id} "
                        f"v={veh_id} [{approach}] dist={dist_m:.0f}m "
                        f"ETA={eta:.1f}s < min={self._eta_min_s:.0f}s — skipped (too close)"
                    )
                return
            if eta > eta_max:
                if LOG_GB_BUS:
                    _vprint(
                        f"[GB BUS] t={time:.1f} jct={self.junction_id} "
                        f"v={veh_id} [{approach}] dist={dist_m:.0f}m "
                        f"ETA={eta:.1f}s > max={eta_max:.0f}s — deferred (too far)"
                    )
                return
            self.bus_request   = self.bus_sg
            self._bus_eta      = eta
            self._bus_det_time = time
            if LOG_GB_BUS:
                _vprint(
                    f"[GB BUS] t={time:.1f} jct={self.junction_id} "
                    f"detected [{source}|{approach}] v={veh_id} "
                    f"dist={dist_m:.0f}m ETA={eta:.1f}s "
                    f"window=[{self._eta_min_s:.0f},{eta_max:.0f}]s "
                    f"→ requesting SG {self.bus_sg}"
                )
            if self._stats:
                self._stats.record_tsp_event(self.junction_id, 'detection')
                try:
                    self._stats.record_pt_bus_detection(self.junction_id, veh_id, time)
                except Exception:
                    pass

        # ── Tier 1: PT line vehicle coordinate scan ───────────────────────────
        seen = set()
        try:
            n_lines = AKIPTGetNumberLines()
        except Exception:
            n_lines = 0

        for li in range(n_lines):
            try:
                line_id = AKIPTGetIdLine(li)
                n_vehs  = AKIGetNbVehiclesFollowingPTLine(line_id)
            except Exception:
                continue
            for vi in range(n_vehs):
                try:
                    veh_id = AKIGetVehicleFollowingPTLine(line_id, vi)
                    if veh_id in seen:
                        continue
                    inf = AKIPTVehGetInf(veh_id)
                    if inf.report < 0:
                        continue
                    seen.add(veh_id)
                    if self.bus_type_pos > 0 and inf.type != self.bus_type_pos:
                        continue

                    if jx is not None:
                        dx   = float(inf.xCurrentPos) - jx
                        dy   = float(inf.yCurrentPos) - jy
                        dist = (dx * dx + dy * dy) ** 0.5
                        if dist > detection_zone_m:
                            continue
                        try:
                            spd_kmh = float(inf.CurrentSpeed)
                        except Exception:
                            spd_kmh = 40.0
                        eta      = _eta_from_dist(dist, spd_kmh)
                        approach = _approach_label(getattr(inf, 'idSection', -1))
                    else:
                        # No junction coordinates yet — fall back to section membership
                        if not hasattr(self, '_turn_origin_secs'):
                            _tos = set(self.incoming_sections)
                            try:
                                _nt = AKIInfNetGetNbTurnsInNode(self.node_id)
                                for _ti in range(max(_nt, 0)):
                                    try:
                                        _ts = AKIInfNetGetOriginSectionInTurn(self.node_id, _ti)
                                        if _ts > 0:
                                            _tos.add(_ts)
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                            self._turn_origin_secs = _tos
                        if inf.idSection not in self._turn_origin_secs:
                            try:
                                si = AKIInfNetGetSectionANGInf(inf.idSection)
                                if si.report < 0 or si.idNodeTo != self.node_id:
                                    continue
                            except Exception:
                                continue
                        # No XY — distance unknown; use eta_max as a pass-through
                        dist     = 0.0
                        eta      = self._eta_max_s / 2.0
                        approach = _approach_label(getattr(inf, 'idSection', -1))

                    if not detected:
                        _request_bus(veh_id, "PT-coord", eta, dist, approach)
                    detected = True
                except Exception:
                    continue

        # ── Tier 2: section scan for bus-type vehicles ────────────────────────
        if not detected:
            for sec_id in self.incoming_sections:
                try:
                    n = AKIVehStateGetNbVehiclesSection(sec_id, True)
                    for vi in range(n):
                        inf = AKIVehStateGetVehicleInfSection(sec_id, vi)
                        if inf.idVeh in seen:
                            continue
                        if self.bus_type_pos > 0 and inf.type != self.bus_type_pos:
                            continue
                        # Estimate distance from position-along-section + section length
                        try:
                            si      = AKIInfNetGetSectionANGInf(sec_id)
                            sec_len = float(si.length) if si.report >= 0 else 100.0
                            pos_m   = float(inf.CurrentPos)
                            dist    = max(sec_len - pos_m, 0.0)
                            spd_kmh = max(float(inf.CurrentSpeed), 1.0)
                        except Exception:
                            dist    = 50.0
                            spd_kmh = 40.0
                        if dist > detection_zone_m:
                            continue
                        eta      = _eta_from_dist(max(dist, 1.0), spd_kmh)
                        approach = _approach_label(sec_id)
                        _request_bus(inf.idVeh, f"sec={sec_id}", eta, dist, approach)
                        detected = True
                        break
                except Exception:
                    continue
                if detected:
                    break

        # ── Tier 3: rising-edge detector presence ─────────────────────────────
        # Detectors are at a known distance from the stop line — use DetDistance
        # (if configured) to compute a distance-based ETA.
        for det in self.bus_det:
            try:
                current = AKIDetGetPresenceCyclebyId(det, 1)
                rising  = current == 1 and self.prev_bus_presence.get(det, 0) == 0
                self.prev_bus_presence[det] = current
                if not rising:
                    continue
                # Try to get detector distance from geometry or config
                try:
                    props   = AKIDetGetPropertiesDetectorById(det)
                    sec_id  = int(props.IdSection)
                    ini_pos = float(props.InitialPosition)
                    si      = AKIInfNetGetSectionANGInf(sec_id)
                    sec_len = float(si.length) if si.report >= 0 else 100.0
                    dist    = max(sec_len - ini_pos, 1.0)
                    spd     = 40.0   # assume 40 km/h at detector
                    approach = _approach_label(sec_id)
                except Exception:
                    dist     = 50.0
                    spd      = 40.0
                    approach = "?"
                eta = _eta_from_dist(dist, spd)
                _request_bus(-det, f"det={det}", eta, dist, approach)
            except Exception:
                pass

    # =========================================================================
    # URTSP-MODE DETECTION  (GROUP_BASED_URTSP)
    # =========================================================================

    def _build_urtsp_geometry(self):
        """
        Cache section + position range for each bus-call detector.
        Called once at __init__ when tsp_mode == "urtsp".
        """
        for det_id in self.bus_det:
            try:
                props = AKIDetGetPropertiesDetectorById(det_id)
                if props.report >= 0:
                    self._urtsp_det_geometry[det_id] = (
                        int(props.IdSection),
                        float(props.InitialPosition),
                        float(props.FinalPosition),
                    )
            except Exception:
                pass
        if LOG_GB_BUS:
            _vprint(
                f"[GB URTSP] jct={self.junction_id} "
                f"detector geometry: {self._urtsp_det_geometry}"
            )

    def _detect_bus_urtsp(self, time: float):
        """
        URTSP-style bus detection for GROUP_BASED_URTSP mode.

        Primary:   scans vehicles on each detector's section within a widened
                   position window (±20 m from detector zone) and checks vehicle
                   type.  This is identical to the URTSP call-detector logic and
                   avoids the step-skip gap that pure presence detection suffers
                   at ~50 km/h (~14 m/step).
        Fallback:  rising-edge presence (AKIDetGetPresenceCyclebyId) for detectors
                   whose geometry could not be cached.
        """
        DETECTION_WINDOW_M = 20.0   # metres either side of detector zone

        for det_id in self.bus_det:
            # Track previous presence for rising-edge fallback
            try:
                current_presence = AKIDetGetPresenceCyclebyId(det_id, 1)
            except Exception:
                current_presence = 0
            was_present = self.prev_bus_presence.get(det_id, 0)
            self.prev_bus_presence[det_id] = current_presence

            geo = self._urtsp_det_geometry.get(det_id)
            if geo:
                sec_id, det_init, det_final = geo
                window_lo = max(0.0, det_init - DETECTION_WINDOW_M)
                window_hi = det_final + DETECTION_WINDOW_M
                try:
                    n = AKIVehStateGetNbVehiclesSection(sec_id, True)
                    for vi in range(n):
                        inf = AKIVehStateGetVehicleInfSection(sec_id, vi)
                        # Type filter: only buses
                        if self.bus_type_pos > 0 and inf.type != self.bus_type_pos:
                            continue
                        # Position filter: within detection window
                        try:
                            pos = float(inf.CurrentPos)
                        except Exception:
                            pos = float(inf.distance2End if hasattr(inf, 'distance2End') else 0)
                        if window_lo <= pos <= window_hi:
                            _vid = inf.idVeh
                            if (self.bus_sg and self.bus_request is None
                                    and time >= self._tsp_cooldown_until):
                                self.bus_request = self.bus_sg
                                # Calculate ETA to stop line so TSP can grant
                                # just enough green for the bus to arrive
                                try:
                                    _sinf = AKIInfNetGetSectionANGInf(sec_id)
                                    sec_len = float(_sinf.length) if _sinf.report >= 0 else 100.0
                                    distance_to_stop = max(0.1, sec_len - pos)
                                    speed_ms = max(5.0 / 3.6,
                                                   float(inf.CurrentSpeed) / 3.6)
                                    self._bus_eta = distance_to_stop / speed_ms
                                    self._bus_det_time = time
                                except Exception:
                                    self._bus_eta = None
                                    self._bus_det_time = None
                                if LOG_GB_BUS:
                                    _eta_s = f"{self._bus_eta:.1f}s" if self._bus_eta is not None else "?"
                                    _vprint(
                                        f"[GB URTSP] t={time:.1f} jct={self.junction_id} "
                                        f"detected [sec={sec_id} pos={pos:.1f}m] "
                                        f"v={_vid} ETA={_eta_s} → requesting SG {self.bus_sg}"
                                    )
                                if self._stats:
                                    self._stats.record_tsp_event(self.junction_id, 'detection')
                                    try:
                                        self._stats.record_pt_bus_detection(
                                            self.junction_id, _vid, time)
                                    except Exception:
                                        pass
                            return   # one detection per step is enough
                except Exception:
                    pass
            else:
                # Fallback: rising-edge presence (only fires on 0→1 edge)
                if current_presence == 1 and was_present == 0:
                    if self.bus_sg and self.bus_request is None and time >= self._tsp_cooldown_until:
                        self.bus_request = self.bus_sg
                        if LOG_GB_BUS:
                            _vprint(
                                f"[GB URTSP] t={time:.1f} jct={self.junction_id} "
                                f"detected [det={det_id} rising-edge] "
                                f"→ requesting SG {self.bus_sg}"
                            )
                        if self._stats:
                            self._stats.record_tsp_event(self.junction_id, 'detection')
                    return

    # =========================================================================
    # HARMONY-MODE EXTENSION  (GROUP_BASED_HARMONY)
    # =========================================================================

    def _compute_harmony_extension(self, time: float, bus_sg: int,
                                    queue: dict) -> float:
        """
        Use harmony search to find the optimal green extension for bus_sg.

        Objective: minimise total weighted passenger delay.
          - Extending by `ext` seconds benefits the bus (reduces bus delay)
          - It also forces all other waiting SGs to wait `ext` extra seconds
        The search is bounded by [0, remaining_cap].

        Returns the optimal extension in seconds (0 if cap already exhausted).
        """
        remaining_cap = self.max_extension - self.extension_used
        if remaining_cap <= 0:
            return 0.0

        # Pre-compute total waiting demand for other SGs (used inside objective)
        other_demand_pax = sum(
            cnt * self.CarOcc
            for sg, cnt in queue.items()
            if sg not in self.sg_list
        )

        def _objective(ext: float, _t: float) -> float:
            # Cost: other SGs wait `ext` more seconds
            delay_cost = other_demand_pax * ext
            # Benefit: bus (BusOcc passengers) saves delay proportional to extension
            bus_benefit = self.BusOcc * ext * 0.5   # 0.5 = diminishing returns factor
            return delay_cost - bus_benefit          # minimise

        try:
            opt = harmony_search(
                _objective,
                lower_bound=0.0,
                upper_bound=remaining_cap,
                max_iterations=self._harmony_iterations,
                harmony_memory_size=self._harmony_memory_size,
                hmcr=self._harmony_hmcr,
                par=self._harmony_par,
                bandwidth=self._harmony_bandwidth,
                time=time,
            )
            result = float(max(0.0, min(opt, remaining_cap)))
            if LOG_GB_BUS:
                _vprint(
                    f"[GB HARMONY] t={time:.1f} jct={self.junction_id} "
                    f"harmony extension={result:.1f}s "
                    f"(cap_remaining={remaining_cap:.1f}s)"
                )
            return result
        except Exception:
            return remaining_cap   # fallback: grant full remaining cap

    # =========================================================================
    # STARVATION TRACKING
    # =========================================================================

    def _update_wait_times(self, queue: dict):
        for sg in self.all_sg:
            if sg not in self.sg_list and queue.get(sg, 0) > 0:
                self.wait_time[sg] += 1.0
            else:
                self.wait_time[sg] = 0.0

    # =========================================================================
    # PHASE BUILDING
    # =========================================================================

    def _precompute_phase_groups(self):
        """
        Pre-compute a minimum clique cover of the compatibility graph.

        Uses Bron-Kerbosch (with pivot) to enumerate all maximal cliques of the
        compatibility graph, then a greedy set-cover picks the smallest number of
        those cliques that together cover every SG at least once.

        Result stored in self.phase_groups — a list of sorted SG lists, e.g.
            [[2,3,4,14,15], [7,8,11,13], [6,9,16], ...]

        _build_new_phase and _activate_for_bus use these groups directly, so
        the controller always runs the maximum-compatible set of SGs in each phase
        rather than a greedy one-at-a-time expansion from an arbitrary seed.
        """
        sgs = set(self.all_sg)
        if not sgs:
            self.phase_groups = []
            return

        groups: list = []

        # ── Stage 1: use original SCATS phase structure when available ────────
        # The SCATS SignalGroupIDList encodes the traffic-engineered phase plan
        # for this intersection.  Using it directly as phase groups means the
        # adaptive controller follows the same SG combinations the field engineer
        # designed, rather than deriving potentially different groups from the
        # compatibility graph.  Each unique SG set becomes one phase group;
        # SGs in multiple phases (e.g. a leading-green SG that also runs in the
        # main phase) will appear in multiple groups and be served each time.
        if self._phase_sg_nested:
            seen_keys: set = set()
            for phase in self._phase_sg_nested:
                filtered = [sg for sg in phase if sg in sgs]
                if not filtered:
                    continue
                key = frozenset(filtered)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                groups.append(sorted(filtered))

            # Any SG not covered by any SCATS phase gets its own singleton group
            covered = {sg for g in groups for sg in g}
            for sg in sorted(sgs - covered,
                             key=lambda s: self.max_green.get(s, 40.0),
                             reverse=True):
                groups.append([sg])

            _vprint(
                f"[GB] jct={self.junction_id} phase_groups from SCATS phases "
                f"({len(groups)} groups from {len(self._phase_sg_nested)} phases)"
            )

        else:
            # ── Stage 2 fallback: Bron-Kerbosch clique cover ─────────────────
            # Used when no SCATS phase list is available (e.g. manual GroupBasedConfig).
            compat = {}
            missing_sgs = []
            for sg in sgs:
                row = self.conflict_matrix.get(sg, {})
                if not row:
                    missing_sgs.append(sg)
                compat[sg] = {other for other in sgs if other != sg and row.get(other, 1) == 0}
            if missing_sgs:
                _vprint(
                    f"[GB] WARNING jct={self.junction_id} — {len(missing_sgs)} SG(s) "
                    f"not in conflict matrix → isolated loners: {sorted(missing_sgs)}."
                )

            all_cliques: list = []

            def _bk(R: set, P: set, X: set):
                if not P and not X:
                    if R:
                        all_cliques.append(frozenset(R))
                    return
                pivot = max(P | X, key=lambda u: len(compat[u] & P))
                for v in list(P - compat[pivot]):
                    _bk(R | {v}, P & compat[v], X & compat[v])
                    P = P - {v}
                    X = X | {v}

            try:
                _bk(set(), set(sgs), set())
            except RecursionError:
                _vprint(f"[GB] jct={self.junction_id} BK recursion limit — single-SG fallback")
                self.phase_groups = [[sg] for sg in sorted(sgs)]
                return

            if not all_cliques:
                self.phase_groups = [[sg] for sg in sorted(sgs)]
                return

            def _clique_key(c):
                return (len(c), sum(self.max_green.get(sg, 40.0) for sg in c))
            all_cliques_sorted = sorted(all_cliques, key=_clique_key, reverse=True)

            uncovered = set(sgs)
            while uncovered:
                best = max(
                    all_cliques_sorted,
                    key=lambda c: (
                        len(c & uncovered),
                        sum(self.max_green.get(sg, 40.0) for sg in c & uncovered),
                    ),
                )
                intersection = best & uncovered
                if not intersection:
                    for sg in sorted(uncovered,
                                     key=lambda s: self.max_green.get(s, 40.0),
                                     reverse=True):
                        groups.append([sg])
                    break
                groups.append(sorted(intersection))
                uncovered -= intersection

        # Sort phase groups by total max_green descending so the cycle always
        # starts with the highest-priority (longest) phase — NB/SB through
        # movements first, then turn phases, then minor cross-street phases.
        # This means the bus SG (in the NB/SB group) is group 0, so buses
        # arriving while that group is running trigger Strategy 1 (extension)
        # rather than Strategy 3 (forced insertion).
        groups.sort(
            key=lambda g: sum(self.max_green.get(sg, 40.0) for sg in g),
            reverse=True,
        )

        self.phase_groups = groups
        _pg_summary = (
            f"[GB] jct={self.junction_id} phase_groups={len(groups)} "
            f"sg_count={len(list(self.all_sg))} [sorted by max_green desc]: "
            + " | ".join(
                f"[{','.join(map(str, g))}]"
                f"(mg={sum(self.max_green.get(s,40.) for s in g):.0f}s)"
                for g in groups
            )
        )
        _vprint(_pg_summary)
        # Always write to log file so phase groups are visible even when LOG_GB=False
        log_to_file(_pg_summary)

    def _build_new_phase(self, time: float, timeSta: float, queue: dict):
        """
        Activate the next phase group from the precomputed clique cover.

        Groups are tracked by INDEX (self._group_served) so that a full group
        is always activated — never a partial subset caused by per-SG non_activated
        filtering.  Round-robin through all groups, resetting when every group
        has been served at least once per cycle.

        Within unserved groups, selection priority:
          1. Contains a starved SG (longest-waiting wins)
          2. Highest total demand across the group
          3. Lowest group index (stable round-robin fallback)
        """
        if not self.phase_groups:
            # Fallback: no precomputed groups — activate a single SG
            sg = min(self.all_sg) if self.all_sg else None
            if sg is None:
                if LOG_GB_STATE:
                    _vprint(
                        f"[GB STATE] t={time:.1f} jct={self.junction_id} "
                        f"_build_new_phase: all_sg=[] AND phase_groups=[] — "
                        f"cannot activate any phase (watchdog will recover)"
                    )
                return
            if LOG_GB_STATE:
                _vprint(
                    f"[GB STATE] t={time:.1f} jct={self.junction_id} "
                    f"_build_new_phase fallback (no phase_groups): single SG={sg}"
                )
            self.sg_list = [sg]
            self.lower_time[sg] = time + self.min_green.get(sg, 6.0)
            self.upper_time[sg] = time + self.max_green.get(sg, 40.0)
            self._apply_signals(time, timeSta)
            self.state = self.GREEN
            return

        # Reset cycle when all groups have been served
        if len(self._group_served) >= len(self.phase_groups):
            self._group_served = set()

        # Candidate group indices = those not yet served this cycle
        unserved_indices = [
            i for i in range(len(self.phase_groups))
            if i not in self._group_served
        ]
        if not unserved_indices:
            self._group_served = set()
            unserved_indices = list(range(len(self.phase_groups)))

        # Starvation check across all SGs
        starved_sgs = {
            sg for sg, wt in self.wait_time.items()
            if wt >= self.starvation_thresh
        }

        def _score(idx):
            grp = self.phase_groups[idx]
            has_starved     = any(sg in starved_sgs for sg in grp)
            max_wait        = max((self.wait_time.get(sg, 0.0) for sg in grp), default=0.0)
            total_demand    = sum(queue.get(sg, 0) for sg in grp)
            # Total max_green: used as primary ordering when demand is zero.
            # This keeps the cycle faithful to the original signal plan — phases
            # with longer green allocations (NB/SB through movements) run first.
            total_max_green = sum(self.max_green.get(sg, 40.0) for sg in grp)
            # Priority: starvation > wait_time > demand > green_time > index
            return (has_starved, max_wait, total_demand, total_max_green, -idx)

        best_idx   = max(unserved_indices, key=_score)
        best_group = self.phase_groups[best_idx]

        self._group_served.add(best_idx)
        self.sg_list = list(best_group)   # FULL group — no partial subsetting

        # Use the group's maximum max_green as the shared upper bound so that
        # a short-phase SG (e.g. a 6s protected turn in a group with 29s through
        # movements) does not prematurely terminate the whole group.
        _group_max = max(self.max_green.get(sg, 40.0) for sg in self.sg_list)
        for sg in self.sg_list:
            self.non_activated.discard(sg)   # keep non_activated in sync for starvation
            self.lower_time[sg] = time + self.min_green.get(sg, 6.0)
            self.upper_time[sg] = time + _group_max

        if LOG_GB_BUS or LOG_GB_STATE:
            _vprint(
                f"[GB PHASE] t={time:.1f} jct={self.junction_id} "
                f"▶ group_idx={best_idx} SGs={sorted(self.sg_list)} "
                f"max_green={_group_max:.0f}s "
                f"demand={[queue.get(sg, 0) for sg in sorted(self.sg_list)]} "
                f"groups_remaining={len(self.phase_groups) - len(self._group_served)}"
            )
        elif LOG_GB:
            _vprint(
                f"[GB] t={time:.1f} jct={self.junction_id} "
                f"New phase: SGs={sorted(self.sg_list)}"
            )
        self._apply_signals(time, timeSta)
        self.state = self.GREEN

    def _expand_phase(self, queue: dict):
        """
        Legacy greedy expansion — kept for compatibility but no longer called
        by _build_new_phase or _activate_for_bus (both now use phase_groups).

        Greedily adds compatible non-activated SGs to self.sg_list from the
        current seed.  May not find the global maximum clique.
        """
        candidates: set = set()
        for active_sg in self.sg_list:
            row = self.conflict_matrix.get(active_sg, {})
            for sg in self.non_activated:
                if sg not in self.sg_list and row.get(sg, 1) == 0:
                    candidates.add(sg)

        while candidates:
            next_sg = max(candidates, key=lambda x: (queue.get(x, 0), -x))
            self.sg_list.append(next_sg)
            next_row = self.conflict_matrix.get(next_sg, {})
            candidates = {
                c for c in candidates
                if next_row.get(c, 1) == 0 and c != next_sg
            }

    def _get_compatible(self, active_list: list) -> list:
        """Return all SG positions compatible with every SG in active_list.

        If a signal group has no row in the conflict matrix (matrix incomplete
        or empty), it is treated as compatible with the active group rather than
        conflicting — an empty matrix must not cause permanent Strategy-3 loops.
        """
        compatible = set(self.all_sg)
        for sg in active_list:
            row = self.conflict_matrix.get(sg)
            if row is None:
                # No matrix data for this SG — assume compatible with all rather
                # than defaulting to all-conflict which would force Strategy 3 every step.
                continue
            compatible &= {i for i in self.all_sg if row.get(i, 1) == 0}
        return list(compatible)

    # =========================================================================
    # BUS PRIORITY LOGIC
    # =========================================================================

    def _handle_bus_logic(self, time: float, queue: dict = None):
        """
        Apply green extension, phase addition, or queue bus for next phase.
        Sets self.tsp_strategy to match the original algorithm's TSPStrategy values:
          1 = green extension  (bus SG already active)
          2 = compatible insertion  (bus SG added to current phase)
          3 = forced insertion  (bus SG incompatible — current phase terminated early)
        """
        if not self.bus_request:
            return
        if queue is None:
            queue = {}
        bus_sg = self.bus_request

        # ── Strategy 1: bus SG already green → extend ────────────────────────
        if bus_sg in self.sg_list:
            remaining = self.max_extension - self.extension_used
            if remaining > 0:
                if self.tsp_mode == "harmony":
                    # Harmony search finds the optimal extension duration
                    grant = self._compute_harmony_extension(time, bus_sg, queue)
                else:
                    # URTSP: extend by just enough so the bus arrives on green.
                    # Use stored ETA (age-adjusted if detection happened earlier).
                    CLEAR_BUFFER = 5.0  # seconds buffer for bus to clear stop line
                    if self._bus_eta is not None and self._bus_det_time is not None:
                        age = time - self._bus_det_time
                        eta_now = max(0.0, self._bus_eta - age)
                        current_upper = self.upper_time.get(bus_sg, time)
                        remaining_green = max(0.0, current_upper - time)
                        needed = max(0.0, eta_now + CLEAR_BUFFER - remaining_green)
                        grant = min(needed, remaining)
                    else:
                        # No ETA available (fallback: grant full cap)
                        grant = remaining
                if grant > 0:
                    self.upper_time[bus_sg] = self.upper_time.get(bus_sg, time) + grant
                    self.extension_used += grant
                    self.tsp_strategy = 1
                    self._tsp_cooldown_until = time + self._tsp_cycle_cooldown
                    if LOG_GB_BUS:
                        _eta_info = (
                            f" ETA={self._bus_eta:.1f}s" if self._bus_eta is not None else ""
                        )
                        _vprint(
                            f"[GB] t={time:.1f} jct={self.junction_id} "
                            f"TSPStrategy=1 (green ext) SG {bus_sg} "
                            f"+{grant:.1f}s (total_ext={self.extension_used:.1f}s)"
                            f"{_eta_info} cooldown_until={self._tsp_cooldown_until:.1f}"
                        )
                    if self._stats:
                        self._stats.record_tsp_event(self.junction_id, 'extension')
            # Clear request — detection will re-raise next step if bus still present
            # and extension has remaining budget (after phase resets extension_used).
            self.bus_request = None
            return

        # ── Strategy 2: compatible with current phase → insert immediately ───
        compatible = self._get_compatible(self.sg_list)
        if bus_sg in compatible:
            self.sg_list.append(bus_sg)
            self.lower_time[bus_sg] = time + self.min_green.get(bus_sg, 6.0)
            self.upper_time[bus_sg] = time + self.max_green.get(bus_sg, 40.0)
            self.tsp_strategy = 2
            self._tsp_cooldown_until = time + self._tsp_cycle_cooldown
            if LOG_GB_BUS:
                _vprint(
                    f"[GB] t={time:.1f} jct={self.junction_id} "
                    f"TSPStrategy=2 (compatible insertion) SG {bus_sg} added "
                    f"cooldown_until={self._tsp_cooldown_until:.1f}"
                )
            if self._stats:
                self._stats.record_tsp_event(self.junction_id, 'insertion')
            self.bus_request = None
            return

        # ── Strategy 3: incompatible → keep request, force early termination ─
        # check_termination() will detect the pending incompatible bus_request
        # and terminate after min_green, transitioning to a bus-priority phase.
        if self.tsp_strategy != 3:   # only log once per termination sequence
            self.tsp_strategy = 3
            if LOG_GB_BUS:
                _vprint(
                    f"[GB] t={time:.1f} jct={self.junction_id} "
                    f"TSPStrategy=3 (forced insertion) SG {bus_sg} "
                    f"incompatible — forcing early termination"
                )

    def _activate_for_bus(self, time: float, timeSta: float, queue: dict):
        """
        Start a new phase for a waiting bus request using the precomputed group.

        Looks up the phase group that contains bus_sg so the full maximum-compatible
        set runs alongside the bus SG — not a greedy one-seed expansion.
        If bus_sg is not found in any group (shouldn't happen after pruning),
        falls back to bus_sg alone plus any compatible non-activated SGs via
        _expand_phase.
        """
        bus_sg = self.bus_request
        if not bus_sg:
            return

        # Find the precomputed group that contains this bus SG
        bus_group = None
        bus_group_idx = None
        for idx, group in enumerate(self.phase_groups):
            if bus_sg in group:
                bus_group = group
                bus_group_idx = idx
                break

        if bus_group is not None:
            # Always activate the FULL group (never a partial subset)
            self.sg_list = list(bus_group)
            if bus_group_idx is not None:
                self._group_served.add(bus_group_idx)
        else:
            # Fallback: seed + greedy expand (legacy path, no phase_groups entry)
            self.sg_list = [bus_sg]
            self._expand_phase(queue)

        _bus_group_max = max(self.max_green.get(sg, 40.0) for sg in self.sg_list) if self.sg_list else 40.0
        for sg in self.sg_list:
            self.non_activated.discard(sg)
            self.lower_time[sg] = time + self.min_green.get(sg, 6.0)
            self.upper_time[sg] = time + _bus_group_max

        self.state = self.GREEN
        # Start junction-level cooldown: block new bus requests until the
        # normal round-robin has had time to serve all remaining phase groups.
        self._tsp_cooldown_until = time + self._tsp_cycle_cooldown
        if LOG_GB_BUS:
            _vprint(
                f"[GB] t={time:.1f} jct={self.junction_id} "
                f"Bus priority phase activated: SGs={sorted(self.sg_list)} "
                f"(bus_sg={bus_sg}) cooldown_until={self._tsp_cooldown_until:.1f}"
            )
        if self._stats:
            self._stats.record_tsp_event(self.junction_id, 'insertion')
        self._apply_signals(time, timeSta)

        # Notify corridor coordinator so it can Kalman-predict and pre-arm
        # downstream intersections (only when COORDINATED_TSP is enabled).
        if self._corridor_coord is not None and COORDINATED_TSP:
            _served_veh = getattr(self, '_last_served_veh_id', None) or -1
            try:
                self._corridor_coord.notify_bus_granted(
                    _served_veh, self.junction_id, time, bus_sg)
            except Exception as _ce:
                log_to_file(f"[CORRIDOR] notify_bus_granted error jct={self.junction_id}: {_ce}")

    # =========================================================================
    # TERMINATION
    # =========================================================================

    def _check_termination(self, time: float, queue: dict):
        if not self.sg_list:
            return

        # Upper bound exceeded for any active SG
        terminate = any(
            time >= self.upper_time.get(sg, 0.0) for sg in self.sg_list
        )

        # Lower bound passed AND no remaining demand on all active SGs
        if not terminate:
            if all(
                time >= self.lower_time.get(sg, 0.0) and queue.get(sg, 0) == 0
                for sg in self.sg_list
            ):
                terminate = True

        # Bus forced early termination — after min green, incompatible bus request
        if not terminate and self.bus_request:
            compatible = self._get_compatible(self.sg_list)
            if self.bus_request not in compatible:
                if all(time >= self.lower_time.get(sg, 0.0) for sg in self.sg_list):
                    if LOG_GB:
                        _vprint(
                            f"[GB] t={time:.1f} jct={self.junction_id} "
                            f"Bus SG {self.bus_request} forcing early termination"
                        )
                    terminate = True

        if terminate:
            if LOG_GB:
                _vprint(
                    f"[GB] t={time:.1f} jct={self.junction_id} "
                    f"Terminating phase SGs={sorted(self.sg_list)}"
                )
            self._force_intergreen(time)

    # =========================================================================
    # INTERGREEN (all-red gap)
    # =========================================================================

    def _force_intergreen(self, time: float):
        if LOG_GB_STATE:
            _vprint(
                f"[GB STATE] t={time:.1f} jct={self.junction_id} "
                f"GREEN→INTERGREEN SGs={sorted(self.sg_list)} "
                f"end={time + self.intergreen_dur:.1f}"
            )
        self.state          = self.INTERGREEN
        self.intergreen_end = time + self.intergreen_dur
        self.extension_used = 0.0

        ctrl_type = ECIGetControlType(self.junction_id)
        if ctrl_type in (2, 3):
            ECIDisableEvents(self.junction_id)
            for sg in self.all_sg:
                ECIChangeSignalGroupState(
                    self.junction_id, sg, 0, 0, time, 1)
            ECIEnableEvents(self.junction_id)
        else:
            _vprint(
                f"[GB] WARNING jct={self.junction_id} control type={ctrl_type} "
                f"(expected 2=External) — cannot set all-red"
            )

        self.lower_time.clear()
        self.upper_time.clear()

    # =========================================================================
    # SIGNAL APPLICATION
    # =========================================================================

    def _apply_signals(self, time: float, timeSta: float):
        ctrl_type = ECIGetControlType(self.junction_id)
        if ctrl_type not in (2, 3):
            _vprint(
                f"[GB] WARNING jct={self.junction_id} control type={ctrl_type} "
                f"(expected 2=External) — signal change skipped"
            )
            return

        green_sgs = [sg for sg in self.all_sg if sg in self.sg_list]
        # Throttled diagnostic: log actual applied signal state once per 10 sim-seconds
        if LOG_GB_BUS and int(time) % 10 == 0 and not getattr(self, '_last_apply_log_t', None) == int(time):
            self._last_apply_log_t = int(time)
            _vprint(
                f"[GB APPLY] t={time:.1f} jct={self.junction_id} "
                f"GREEN={green_sgs} RED={[sg for sg in self.all_sg if sg not in self.sg_list]} "
                f"ctrl_type={ctrl_type}"
            )

        ECIDisableEvents(self.junction_id)
        for sg in self.all_sg:
            state = 1 if sg in self.sg_list else 0
            ECIChangeSignalGroupState(
                self.junction_id, sg, state, timeSta, time, 1)
        ECIEnableEvents(self.junction_id)

    # =========================================================================
    # TIME BOUNDS GUARD
    # =========================================================================

    def _update_time_bounds(self, time: float):
        """Ensure every active SG has valid time bounds (defensive guard)."""
        for sg in self.sg_list:
            if sg not in self.lower_time:
                self.lower_time[sg] = time + self.min_green.get(sg, 6.0)
                self.upper_time[sg] = time + self.max_green.get(sg, 40.0)

    # =========================================================================
    # SECTION INITIALISATION
    # =========================================================================

    def _initialize_sections(self):
        """Build self.incoming_sections from junction turn-origin topology."""
        seen = set()
        secs = []
        try:
            n_turns = AKIInfNetGetNbTurnsInNode(self.node_id)
            for ti in range(max(n_turns, 0)):
                try:
                    sec_id = AKIInfNetGetOriginSectionInTurn(self.node_id, ti)
                    if sec_id > 0 and sec_id not in seen:
                        seen.add(sec_id)
                        if AKIVehStateGetNbVehiclesSection(sec_id, False) >= 0:
                            secs.append(sec_id)
                except Exception:
                    pass
        except Exception as ex:
            _vprint(
                f"[GB] WARNING jct={self.junction_id} section init failed: {ex}"
            )
        self.incoming_sections = secs
        if LOG_SECTION:
            _vprint(
                f"[SECTION] GB jct={self.junction_id} "
                f"incoming_sections={secs}"
            )

    # =========================================================================
    # JUNCTION COORDINATE RESOLUTION
    # =========================================================================

    def _get_junction_xy(self):
        """
        Return (x, y) centroid of the junction.
        Tries multiple Aimsun coordinate field-name variants
        (xSection/ySection, xSectionTo/ySectionTo, xcoordTo/ycoordTo, x/y).
        Result is cached only on success — retries every call until resolved.
        """
        if getattr(self, '_junction_xy', None) is not None:
            return self._junction_xy

        _x_fields = ('xSection', 'xSectionTo', 'xcoordTo', 'x')
        _y_fields = ('ySection', 'ySectionTo', 'ycoordTo', 'y')

        def _try_xy(si):
            for xf, yf in zip(_x_fields, _y_fields):
                xv = getattr(si, xf, None)
                yv = getattr(si, yf, None)
                if xv is not None and yv is not None:
                    try:
                        return float(xv), float(yv)
                    except (TypeError, ValueError):
                        pass
            return None, None

        xs, ys = [], []
        for sec_id in self.incoming_sections:
            try:
                si = AKIInfNetGetSectionANGInf(sec_id)
                if si.report >= 0:
                    xv, yv = _try_xy(si)
                    if xv is not None:
                        xs.append(xv)
                        ys.append(yv)
            except Exception:
                pass

        if not xs:
            try:
                n_turns = AKIInfNetGetNbTurnsInNode(self.node_id)
                for ti in range(max(n_turns, 0)):
                    try:
                        sec_id = AKIInfNetGetOriginSectionInTurn(self.node_id, ti)
                        si = AKIInfNetGetSectionANGInf(sec_id)
                        if si.report >= 0:
                            xv, yv = _try_xy(si)
                            if xv is not None:
                                xs.append(xv)
                                ys.append(yv)
                    except Exception:
                        pass
            except Exception:
                pass

        if xs:
            self._junction_xy = (sum(xs) / len(xs), sum(ys) / len(ys))
            if LOG_JUNC_XY:
                _vprint(
                    f"[JUNC_XY] GB jct={self.junction_id} resolved "
                    f"→ {self._junction_xy}"
                )
            return self._junction_xy
        return None   # not cached on failure — will retry next call

    # =========================================================================
    # SIMULATION-READY RE-INITIALISATION
    # =========================================================================

    def _auto_build_section_map(self):
        """
        Auto-discover which incoming sections feed each signal group by scanning
        turning movements via ECIGetFromToofTurningofSignalGroup.

        Builds self.sections entries (same structure as the manual config) so
        that _compute_queue returns real vehicle counts instead of always zero.
        Only fills entries for SGs whose origin sections can be resolved.
        Called from reinitialise_from_model() when sections is empty.
        """
        sg_to_secs: dict = {}   # {sg_pos: [section_id, ...]}
        for sg in self.all_sg:
            try:
                n_turns = ECIGetNumberTurningsofSignalGroup(self.junction_id, sg)
                for ti in range(max(n_turns, 0)):
                    try:
                        fp = intp(); tp = intp()
                        ECIGetFromToofTurningofSignalGroup(
                            self.junction_id, sg, ti, fp, tp)
                        sec = fp.value()
                        if sec > 0:
                            sg_to_secs.setdefault(sg, [])
                            if sec not in sg_to_secs[sg]:
                                sg_to_secs[sg].append(sec)
                    except Exception:
                        pass
            except Exception:
                pass

        # Build one sections entry per (section, sg) pair.
        # lane_groups = [[0]] counts all vehicles in lane 0 as a proxy for
        # total section demand; sg_ids maps that count to the signal group.
        built = []
        seen_pairs: set = set()
        for sg, secs in sg_to_secs.items():
            for sec in secs:
                key = (sec, sg)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                # Use sentinel lane_groups=None to signal "count all vehicles
                # in this section" — avoids needing to know lane count here.
                built.append({
                    "section_id": sec,
                    "lane_groups": None,   # sentinel: use total section count
                    "sg_ids":      [sg],
                })

        self.sections = built
        _vprint(
            f"[GB] jct={self.junction_id} auto-built section map: "
            f"{len(built)} entries covering {len(sg_to_secs)}/{len(self.all_sg)} SGs"
        )
        if len(sg_to_secs) < len(self.all_sg):
            unmapped = sorted(set(self.all_sg) - set(sg_to_secs.keys()))
            _vprint(
                f"[GB] jct={self.junction_id} unmapped SGs (demand=0): {unmapped}"
            )

    def reinitialise_from_model(self):
        """
        Re-derive the conflict matrix and phase groups using live Aimsun ECI
        data.  Called from AAPISimulationReady() once the simulation is running
        and all ECI functions are guaranteed to work.

        This corrects any all-conflict matrix that was built at AAPIInit time
        when the ECI phase scan returned nothing, ensuring phase groups reflect
        real signal-plan compatibility (right-turn groups, cross-street groups,
        etc.) rather than treating every SG as isolated.
        """
        _vprint(f"[GB] jct={self.junction_id} re-initialising conflict matrix from live model")
        self.conflict_matrix = self._derive_and_save_conflict_matrix()
        # Rebuild phase groups from the now-correct matrix (sorted by max_green desc)
        self.phase_groups = []
        self._precompute_phase_groups()
        # Auto-build section→SG demand map if not manually configured
        if not self.sections:
            self._auto_build_section_map()
        # Populate bus-SG section set for front/side approach labelling in _detect_bus
        if self.bus_sg is not None:
            self._bus_sg_sections = {
                cfg["section_id"]
                for cfg in self.sections
                if self.bus_sg in cfg.get("sg_ids", [])
            }
        # Reset cycle tracking so the fresh groups start a clean round-robin
        self._group_served = set()
        self.non_activated = set(self.all_sg)
        self.wait_time     = {sg: 0.0 for sg in self.all_sg}
        # Reset watchdog so it doesn't fire immediately on the first step
        self._last_phase_t   = -1.0
        self._watchdog_armed = False
        _vprint(
            f"[GB] jct={self.junction_id} re-init complete: "
            f"{len(self.phase_groups)} phase groups, "
            f"bus_sg={self.bus_sg}, all_sg={self.all_sg}, "
            f"demand_sections={len(self.sections)}"
        )
        if not self.phase_groups:
            _vprint(
                f"[GB] WARNING jct={self.junction_id} re-init produced 0 phase groups "
                f"— watchdog will recover on first step. all_sg={self.all_sg} "
                f"conflict_matrix keys={sorted(self.conflict_matrix.keys())}"
            )

    # =========================================================================
    # CONFLICT MATRIX AUTO-DERIVATION
    # =========================================================================

    def _derive_and_save_conflict_matrix(self) -> dict:
        """
        Auto-derive conflict matrix for this junction.

        Step 1 — ECI existence scan:
          Scan Aimsun phases to find which SG positions (1-based ints) actually
          exist in the live model.  This prevents 'cpsignal group N unknown'
          errors when ECIChangeSignalGroupState is called.

        Step 2 — Config-based compatibility:
          The config SignalGroupIDList uses the same 1-based position numbering
          as the ECI API.  Two SGs are compatible only if they appear together
          in at least one config phase AND both were confirmed by the ECI scan.
          This is authoritative because:
            a) the real SCATS plan is conflict-free by design, and
            b) Aimsun may group SGs from different SCATS sub-phases into the
               same Aimsun phase period, incorrectly marking conflicts as OK.

        Step 3 — Isolated SGs (ECI-confirmed but absent from config phases):
          Treated as all-conflict with everything; receive their own singleton
          phase group so they still get green time via round-robin.

        The derived matrix is written to
          <script_dir>/conflict_matrix/conflict_<junction_id>.csv.

        Returns
        -------
        dict: {sg_id: {sg_id: 0|1}}
        """
        # Step 1 — ECI existence scan
        aimsun_confirmed: set = set()
        try:
            n_phases = ECIGetNumberPhases(self.junction_id)
            for ph in range(1, n_phases + 1):
                try:
                    n_sg = ECIGetNbSignalGroupsPhaseofJunction(
                        self.junction_id, ph, 0.0)
                    for pos in range(1, n_sg + 1):
                        try:
                            sg_id = ECIGetSignalGroupPhaseofJunction(
                                self.junction_id, ph, pos, 0.0)
                            if sg_id > 0:
                                aimsun_confirmed.add(sg_id)
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception as ex:
            _vprint(
                f"[GB] WARNING jct={self.junction_id} ECI phase scan failed: {ex}"
            )

        # Step 2 — Build phase compatibility from config SignalGroupIDList
        # Both config positions and ECI positions use 1-based numbering.
        phase_sgs = []
        if aimsun_confirmed and self._phase_sg_nested:
            for cfg_phase in self._phase_sg_nested:
                valid = frozenset(sg for sg in cfg_phase if sg in aimsun_confirmed)
                if len(valid) >= 1:
                    phase_sgs.append(valid)
            log_to_file(
                f"[GB] jct={self.junction_id} ECI confirmed {len(aimsun_confirmed)} "
                f"SG positions; {len(phase_sgs)} config-phases filtered to confirmed set"
            )
        elif not aimsun_confirmed and self._phase_sg_nested:
            # ECI returned nothing — use config as-is (API not ready at init time)
            config_sg_set = set(self.all_sg)
            for cfg_phase in self._phase_sg_nested:
                valid = frozenset(sg for sg in cfg_phase if sg in config_sg_set)
                if valid:
                    phase_sgs.append(valid)
            aimsun_confirmed = config_sg_set
            _vprint(
                f"[GB] jct={self.junction_id} ECI scan empty — using config "
                f"SignalGroupIDList as fallback ({len(phase_sgs)} phases)"
            )
        else:
            # No config phases — fall back to raw ECI-derived compatibility
            try:
                n_phases = ECIGetNumberPhases(self.junction_id)
                for ph in range(1, n_phases + 1):
                    try:
                        n_sg = ECIGetNbSignalGroupsPhaseofJunction(
                            self.junction_id, ph, 0.0)
                        sgs = set()
                        for pos in range(1, n_sg + 1):
                            try:
                                sg_id = ECIGetSignalGroupPhaseofJunction(
                                    self.junction_id, ph, pos, 0.0)
                                if sg_id > 0:
                                    sgs.add(sg_id)
                            except Exception:
                                pass
                        if sgs:
                            phase_sgs.append(frozenset(sgs))
                    except Exception:
                        pass
            except Exception:
                pass

        # Determine valid SG set: drop config SGs absent from Aimsun
        config_sgs_set = set(self.all_sg)
        if aimsun_confirmed:
            all_sgs_set = aimsun_confirmed & config_sgs_set
            extra = aimsun_confirmed - config_sgs_set
            if extra:
                _vprint(
                    f"[GB] jct={self.junction_id} ECI-only SGs {sorted(extra)} "
                    f"added (will get singleton phase group)"
                )
                all_sgs_set = all_sgs_set | extra
            dropped = config_sgs_set - aimsun_confirmed
            if dropped:
                _vprint(
                    f"[GB] jct={self.junction_id} dropping {sorted(dropped)} "
                    f"(in config but absent from Aimsun — 'cpsignal unknown')"
                )
        else:
            all_sgs_set = config_sgs_set

        self.all_sg = sorted(all_sgs_set)
        if self.bus_sg is not None and self.bus_sg not in all_sgs_set:
            _vprint(
                f"[GB] jct={self.junction_id} bus_sg={self.bus_sg} not in "
                f"valid SG set — clearing bus_sg"
            )
            self.bus_sg = None

        all_sgs = sorted(all_sgs_set)
        if not all_sgs:
            _vprint(
                f"[GB] WARNING jct={self.junction_id} no signal groups found "
                f"— conflict matrix will be empty"
            )
            return {}

        # Step 3 — Build compatible-pair set from config-filtered phases
        compatible = set()
        for sg in all_sgs:
            compatible.add((sg, sg))
        for sg_set in phase_sgs:
            sg_list_ph = sorted(sg_set & all_sgs_set)
            for i, a in enumerate(sg_list_ph):
                for b in sg_list_ph[i + 1:]:
                    compatible.add((a, b))
                    compatible.add((b, a))

        matrix = {
            a: {b: (0 if (a, b) in compatible else 1) for b in all_sgs}
            for a in all_sgs
        }

        try:
            self._save_conflict_matrix_csv(matrix, all_sgs)
        except Exception as ex:
            _vprint(
                f"[GB] WARNING jct={self.junction_id} conflict matrix CSV "
                f"save failed: {ex}"
            )

        log_to_file(
            f"[GB] jct={self.junction_id} conflict matrix derived: "
            f"{len(all_sgs)} SGs across {len(phase_sgs)} config-phases "
            f"({len(compatible)} compatible pairs)"
        )
        return matrix
    def _save_conflict_matrix_csv(self, matrix: dict, all_sgs: list):
        """
        Write the conflict matrix to
          <script_dir>/conflict_matrix/conflict_<junction_id>.csv

        CSV format (compatible with _load_conflict_matrix):
            ,sg1,sg2,...
            sg1,0,1,...
            sg2,1,0,...
        """
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            script_dir = r"D:\Zeke_DEBUG_ERIC\logan_road_new"
        out_dir = os.path.join(script_dir, "conflict_matrix")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"conflict_{self.junction_id}.csv")
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([""] + [str(sg) for sg in all_sgs])
            for a in all_sgs:
                writer.writerow([str(a)] + [str(matrix[a].get(b, 1)) for b in all_sgs])
        _vprint(
            f"[GB] Conflict matrix saved → {out_path}"
        )

    # =========================================================================
    # DELAY MEASUREMENT
    # =========================================================================

    def _discover_side_sections(self):
        """
        Discover side-street approach sections at this junction.
        All turn-origin sections NOT in self.incoming_sections are side streets.
        Result is cached in self._side_sections after first call.
        """
        main_set = set(self.incoming_sections)
        side = []
        try:
            n_turns = AKIInfNetGetNbTurnsInNode(self.node_id)
            seen = set()
            for ti in range(max(n_turns, 0)):
                try:
                    sec_id = AKIInfNetGetOriginSectionInTurn(self.node_id, ti)
                    if sec_id <= 0 or sec_id in seen or sec_id in main_set:
                        continue
                    seen.add(sec_id)
                    if AKIVehStateGetNbVehiclesSection(sec_id, False) >= 0:
                        side.append(sec_id)
                except Exception:
                    pass
        except Exception:
            pass
        self._side_sections = side
        if LOG_SIDE_DISC:
            _vprint(
                f"[SIDE_DISC] GB jct={self.junction_id} side_sections={side}"
            )

    def collect_delay(self, time: float, timeSta: float = None):
        """
        Measure per-step weighted delay across main (incoming) and side sections
        and forward the result to self._stats.add_section_delay_split.

        Main sections use AKIEstGetParcialStatisticsSection when available,
        falling back to cumulative-delta from AKIEstGetCurrentStatisticsSection.
        Side sections (no stats collection point) use per-vehicle CurrentStopTime
        delta so no Aimsun statistics collector is required.
        """
        if not self._stats:
            return

        stat_time = timeSta if timeSta is not None else time

        # Lazily discover side sections
        if self._side_sections is None:
            self._discover_side_sections()

        main_secs = set(self.incoming_sections)
        side_secs = set(self._side_sections or []) - main_secs
        all_secs  = main_secs | side_secs
        if not all_secs:
            return

        truck_pos = getattr(self._stats, '_truck_pos', -1)
        _all_side_veh_ids = set()

        for sec in all_secs:
            is_main = sec in main_secs
            car_d = bus_d = truck_d = 0.0
            car_cnt = bus_cnt = truck_cnt = 0

            # ── Try partial stats (most accurate) ─────────────────────────
            car_stat = AKIEstGetParcialStatisticsSection(
                sec, stat_time, self.car_type_pos)

            if car_stat.report == 0:
                bus_stat   = AKIEstGetParcialStatisticsSection(
                    sec, stat_time, self.bus_type_pos)
                truck_stat = AKIEstGetParcialStatisticsSection(
                    sec, stat_time, truck_pos)
                car_d   = car_stat.DTa * car_stat.count * self.CarOcc
                bus_d   = (bus_stat.DTa * bus_stat.count * self.BusOcc
                           if bus_stat.report == 0 else 0.0)
                truck_d = (truck_stat.DTa * truck_stat.count * self.TruckOcc
                           if truck_stat.report == 0 and truck_pos > 0 else 0.0)
                car_cnt   = car_stat.count
                bus_cnt   = bus_stat.count   if bus_stat.report   == 0 else 0
                truck_cnt = (truck_stat.count
                             if truck_stat.report == 0 and truck_pos > 0 else 0)

            elif not is_main:
                # ── Side section without stats — use stop-time delta ───────
                if sec not in self._side_sec_ff:
                    try:
                        _sinf = AKIInfNetGetSectionANGInf(sec)
                        self._side_sec_ff[sec] = (
                            max(float(_sinf.speedLimit) / 3.6, 1.0)
                            if _sinf.report >= 0 else 13.9)
                    except Exception:
                        self._side_sec_ff[sec] = 13.9
                try:
                    _n = max(int(AKIVehStateGetNbVehiclesSection(sec, False)), 0)
                except Exception:
                    _n = 0
                for _vi in range(_n):
                    try:
                        _veh = AKIVehStateGetVehicleInfSection(sec, _vi)
                        if _veh.report < 0:
                            continue
                        _vid = int(_veh.idVeh)
                        _stop_now  = max(0.0, float(_veh.CurrentStopTime))
                        _prev_stop = self._side_stop_prev.get(_vid, _stop_now)
                        _delta_s   = max(0.0, _stop_now - _prev_stop)
                        self._side_stop_prev[_vid] = _stop_now
                        _all_side_veh_ids.add(_vid)
                        if _delta_s <= 0.0:
                            continue
                        if self.bus_type_pos > 0 and _veh.type == self.bus_type_pos:
                            bus_d   += _delta_s * self.BusOcc
                            bus_cnt += 1
                        else:
                            car_d   += _delta_s * self.CarOcc
                            car_cnt += 1
                    except Exception:
                        pass

            else:
                # ── Main section — cumulative delta fallback ───────────────
                try:
                    car_cum = AKIEstGetCurrentStatisticsSection(sec, self.car_type_pos)
                    bus_cum = AKIEstGetCurrentStatisticsSection(sec, self.bus_type_pos)
                    if car_cum.report != 0:
                        car_cum = AKIEstGetGlobalStatisticsSection(sec, self.car_type_pos)
                    if bus_cum.report != 0:
                        bus_cum = AKIEstGetGlobalStatisticsSection(sec, self.bus_type_pos)

                    prev_car = self._cum_sec_prev.get((sec, 'car'), (0.0, 0))
                    prev_bus = self._cum_sec_prev.get((sec, 'bus'), (0.0, 0))
                    car_now  = car_cum.DTa * car_cum.count if car_cum.report == 0 else 0.0
                    bus_now  = bus_cum.DTa * bus_cum.count if bus_cum.report == 0 else 0.0
                    car_d  = max(0.0, car_now - prev_car[0]) * self.CarOcc
                    bus_d  = max(0.0, bus_now - prev_bus[0]) * self.BusOcc
                    car_cnt = max(0, (car_cum.count if car_cum.report == 0 else 0) - prev_car[1])
                    bus_cnt = max(0, (bus_cum.count if bus_cum.report == 0 else 0) - prev_bus[1])
                    self._cum_sec_prev[(sec, 'car')] = (
                        car_now,
                        car_cum.count if car_cum.report == 0 else prev_car[1])
                    self._cum_sec_prev[(sec, 'bus')] = (
                        bus_now,
                        bus_cum.count if bus_cum.report == 0 else prev_bus[1])
                except Exception:
                    pass

            sec_delay = car_d + bus_d + truck_d
            if sec_delay > 0.0:
                self._stats.add_section_delay_split(
                    intersection_id     = self.junction_id,
                    weighted_delay      = sec_delay,
                    bus_vehicle_count   = bus_cnt   if is_main else 0,
                    car_vehicle_count   = car_cnt   if is_main else 0,
                    truck_vehicle_count = truck_cnt if is_main else 0,
                    is_main             = is_main,
                    bus_delay           = bus_d,
                    car_delay           = car_d,
                    truck_delay         = truck_d,
                )

        # Prune side stop-time tracker every 60 s to avoid unbounded growth
        if _all_side_veh_ids and hasattr(self, '_side_stop_prev'):
            if time - self._side_prune_t > 60.0:
                self._side_stop_prev = {
                    k: v for k, v in self._side_stop_prev.items()
                    if k in _all_side_veh_ids}
                self._side_prune_t = time

        # Periodic delay diagnostic (every 60 s) — LOG_GB_DELAY flag
        if LOG_GB_DELAY:
            if not hasattr(self, '_gb_delay_log_t'):
                self._gb_delay_log_t = time
            if time - self._gb_delay_log_t >= 60.0:
                self._gb_delay_log_t = time
                _id = self.junction_id
                _d  = (self._stats._inter.get(_id, {}) if self._stats else {})
                _vprint(
                    f"[GB DELAY] t={time:.0f} jct={_id} "
                    f"main_secs={sorted(main_secs)} "
                    f"side_secs={sorted(side_secs)} "
                    f"cum_main={_d.get('delay_main', 0.0):.2f}s "
                    f"cum_side={_d.get('delay_side', 0.0):.2f}s"
                )


# =============================================================================
# BUS KALMAN TRACKER
# 1-D constant-velocity Kalman filter tracking a bus's position (metres) along
# a corridor.  Updated on each detector hit; used by CorridorCoordinator to
# predict when the bus will reach downstream intersections.
# =============================================================================

class BusKalmanTracker:
    """
    State vector: [position_m, speed_m_s]
    Transition:   constant-velocity model  (F = [[1, dt], [0, 1]])
    Observation:  position only            (H = [1, 0])
    """

    DEFAULT_SPEED_MS = 11.0   # ≈ 40 km/h initial speed prior

    def __init__(self, initial_pos_m: float = 0.0):
        self.x = np.array([initial_pos_m, self.DEFAULT_SPEED_MS], dtype=float)
        self.P = np.diag([500.0, 25.0])     # initial state covariance
        self.Q = np.diag([1.0,   0.25])     # process noise per second
        self.R = 225.0                       # observation noise var (std ≈ 15 m)
        self.last_t: float = None

    def predict(self, dt: float):
        dt = max(dt, 0.0)
        F  = np.array([[1.0, dt], [0.0, 1.0]])
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + self.Q * dt

    def update(self, obs_pos_m: float):
        H    = np.array([1.0, 0.0])
        innov = obs_pos_m - self.x[0]
        S    = float(H @ self.P @ H) + self.R
        K    = self.P @ H / S
        self.x = self.x + K * innov
        self.P = (np.eye(2) - np.outer(K, H)) @ self.P
        # Clamp speed to plausible bus range [1, 30] m/s
        self.x[1] = max(1.0, min(30.0, self.x[1]))

    def eta(self, target_pos_m: float, current_time: float) -> float:
        """Estimated arrival time (sim seconds) at target_pos_m."""
        dist = target_pos_m - self.x[0]
        if dist <= 0.0:
            return current_time
        return current_time + dist / max(self.x[1], 1.0)

    def uncertainty_s(self, target_pos_m: float) -> float:
        """1-sigma arrival-time uncertainty (seconds)."""
        dist  = max(target_pos_m - self.x[0], 0.0)
        speed = max(self.x[1], 1.0)
        # propagate position and speed variance to time variance
        var_t = self.P[0, 0] / speed**2 + self.P[1, 1] * (dist / speed**2)**2
        return math.sqrt(max(var_t, 0.0))


# =============================================================================
# CORRIDOR COORDINATOR
# Groups of intersections on the same corridor run their GroupBasedControllers
# in a coordinated way.
#
# When COORDINATED_TSP=False (default): pure state-sync logging only.
# When COORDINATED_TSP=True: Kalman-filter prediction arms downstream
#   intersections before the bus arrives, creating a rolling green wave.
#
# Coordination flow (COORDINATED_TSP=True):
#   1. Bus gets priority at intersection[i]  →  GroupBasedController calls
#      coordinator.notify_bus_granted(veh_id, jct_i, time, bus_sg)
#   2. Coordinator updates the Kalman tracker for that vehicle and predicts
#      arrival ETA at jct[i+1], [i+2], [i+3]
#   3. Each step(), when (ETA - current_time) ≤ PRE_GREEN_LEAD_S, the
#      coordinator fires bus_request on that downstream controller so it
#      has a green phase ready on arrival.
# =============================================================================

class CorridorCoordinator:
    """
    Corridor-level GroupBasedController synchronisation and (optionally)
    Kalman-based green-wave TSP coordination.
    """

    LOG_CORRIDOR_INTERVAL = 30.0   # seconds between periodic state dumps
    PRE_GREEN_LEAD_S      = 25.0   # fire pre-request this many seconds before ETA
    MAX_PRE_ARM            = 3      # max intersections ahead to pre-arm at once
    PRE_REQ_TIMEOUT_S     = 90.0   # stale pre-request expiry (seconds after issue)

    def __init__(self, group_name: str, inter_ids: list, controllers_map: dict):
        self.name = group_name
        # Keep only IDs that have a live GroupBasedController
        self.inter_ids = [
            iid for iid in inter_ids
            if iid in controllers_map and controllers_map[iid].gb is not None
        ]
        self._ctrl_map = {iid: controllers_map[iid].gb for iid in self.inter_ids}
        self._last_log_t   = -self.LOG_CORRIDOR_INTERVAL
        self._last_sync_t  = -999.0
        self._sync_count   = 0

        # Kalman tracking state
        # {veh_id: BusKalmanTracker}
        self._trackers: dict = {}
        # Corridor positions along the route (metres from first intersection)
        # Populated by set_corridor_positions() in AAPISimulationReady.
        self.corridor_pos: dict = {}
        # Pre-green requests: {inter_id: (veh_id, eta_t, bus_sg, issued_t)}
        self._pre_requests: dict = {}

        log_to_file(
            f"[CORRIDOR] group={self.name} members={self.inter_ids} "
            f"({len(self.inter_ids)}/{len(inter_ids)} have active GB controllers) "
            f"coordinated_tsp={COORDINATED_TSP}"
        )
        if len(self.inter_ids) < len(inter_ids):
            missing = [i for i in inter_ids if i not in self._ctrl_map]
            log_to_file(
                f"[CORRIDOR] WARNING group={self.name} "
                f"missing GB controllers for {missing}"
            )

        # Wire back-reference into each GB controller so it can call
        # notify_bus_granted() without needing the global list.
        for gb in self._ctrl_map.values():
            gb._corridor_coord = self

    # ------------------------------------------------------------------
    def set_corridor_positions(self, pos_map: dict):
        """
        Set corridor positions (metres from first intersection) for each member.
        Called from AAPISimulationReady once junction XY is available.
        pos_map: {inter_id: float}
        """
        self.corridor_pos = dict(pos_map)
        log_to_file(
            f"[CORRIDOR] group={self.name} corridor positions set: "
            + ", ".join(f"{iid}:{pos:.0f}m" for iid, pos in sorted(pos_map.items()))
        )

    # ------------------------------------------------------------------
    def notify_bus_granted(self, veh_id: int, at_inter_id: int,
                           time: float, bus_sg=None):
        """
        Called by GroupBasedController._activate_for_bus when bus priority
        is activated at at_inter_id.  Updates the Kalman tracker and
        schedules pre-green requests at downstream intersections.
        Only active when COORDINATED_TSP=True and corridor positions are set.
        """
        if not COORDINATED_TSP or not self.corridor_pos:
            return

        at_pos = self.corridor_pos.get(at_inter_id)
        if at_pos is None:
            return

        # Update (or create) Kalman tracker for this vehicle
        tracker = self._trackers.get(veh_id)
        if tracker is None:
            tracker = BusKalmanTracker(initial_pos_m=at_pos)
            self._trackers[veh_id] = tracker
        else:
            if tracker.last_t is not None:
                tracker.predict(max(time - tracker.last_t, 0.0))
            tracker.update(at_pos)
        tracker.last_t = time

        if LOG_CORRIDOR:
            _vprint(
                f"[CORRIDOR KF] t={time:.1f} bus={veh_id} granted "
                f"jct={at_inter_id} pos={at_pos:.0f}m "
                f"spd={tracker.x[1]:.1f}m/s ({tracker.x[1]*3.6:.0f}km/h)"
            )

        # Schedule pre-green requests for downstream intersections
        my_idx = (self.inter_ids.index(at_inter_id)
                  if at_inter_id in self.inter_ids else -1)
        if my_idx < 0:
            return

        for j in range(my_idx + 1,
                       min(my_idx + 1 + self.MAX_PRE_ARM, len(self.inter_ids))):
            next_id  = self.inter_ids[j]
            next_pos = self.corridor_pos.get(next_id)
            if next_pos is None or next_pos <= at_pos:
                continue
            eta   = tracker.eta(next_pos, time)
            sigma = tracker.uncertainty_s(next_pos)
            next_gb  = self._ctrl_map.get(next_id)
            next_bus_sg = next_gb.bus_sg if next_gb else None
            self._pre_requests[next_id] = (veh_id, eta, next_bus_sg, time)
            if LOG_CORRIDOR:
                _vprint(
                    f"[CORRIDOR KF] Pre-arm jct={next_id} bus={veh_id} "
                    f"SG={next_bus_sg} ETA={eta:.1f}s "
                    f"(+{eta - time:.0f}s ±{sigma:.0f}s) dist={next_pos - at_pos:.0f}m"
                )

    # ------------------------------------------------------------------
    def _process_pre_requests(self, time: float, timeSta: float):
        """Fire pre-green requests when the bus is within PRE_GREEN_LEAD_S."""
        for inter_id, (veh_id, eta_t, bus_sg, issued_t) in list(self._pre_requests.items()):
            # Stale: bus never arrived or took a different route
            if time - issued_t > self.PRE_REQ_TIMEOUT_S or eta_t - time < -30.0:
                del self._pre_requests[inter_id]
                if LOG_CORRIDOR:
                    _vprint(
                        f"[CORRIDOR KF] Stale pre-request expired "
                        f"jct={inter_id} bus={veh_id}"
                    )
                continue

            if eta_t - time <= self.PRE_GREEN_LEAD_S:
                gb = self._ctrl_map.get(inter_id)
                if gb is not None and bus_sg is not None and gb.bus_request is None:
                    # Respect the per-vehicle cooldown at the target junction
                    cooldown_ok = not (
                        veh_id == getattr(gb, '_last_served_veh_id', None)
                        and time - getattr(gb, '_last_served_time', -9999.0)
                        < getattr(gb, '_served_veh_timeout', 120.0)
                    )
                    if cooldown_ok:
                        gb.bus_request = bus_sg
                        if LOG_CORRIDOR:
                            _vprint(
                                f"[CORRIDOR KF] Pre-green FIRED "
                                f"jct={inter_id} bus={veh_id} SG={bus_sg} "
                                f"ETA_in={eta_t - time:.1f}s"
                            )
                del self._pre_requests[inter_id]

    # ------------------------------------------------------------------
    def step(self, time: float, timeSta: float):
        """Called every simulation step from AAPIPostManage."""
        if not self._ctrl_map:
            return

        # Process Kalman pre-green requests first
        if COORDINATED_TSP:
            self._process_pre_requests(time, timeSta)

        states    = {iid: c.state            for iid, c in self._ctrl_map.items()}
        n_groups  = {iid: len(c.phase_groups) for iid, c in self._ctrl_map.items()}
        bus_reqs  = {iid: c.bus_request       for iid, c in self._ctrl_map.items()}

        n_idle       = sum(1 for s in states.values() if s == GroupBasedController.IDLE)
        n_green      = sum(1 for s in states.values() if s == GroupBasedController.GREEN)
        n_intergreen = sum(1 for s in states.values() if s == GroupBasedController.INTERGREEN)
        any_bus_req  = any(v is not None for v in bus_reqs.values())

        # ── Periodic state dump ───────────────────────────────────────────────
        if LOG_CORRIDOR and time - self._last_log_t >= self.LOG_CORRIDOR_INTERVAL:
            self._last_log_t = time
            detail = " | ".join(
                f"{iid}:{states[iid][:1]}pg{n_groups[iid]}"
                for iid in self.inter_ids
            )
            _vprint(
                f"[CORRIDOR] t={time:.0f} group={self.name} "
                f"idle={n_idle} green={n_green} ig={n_intergreen} "
                f"bus_req={any_bus_req} | {detail}"
            )

        # ── Group sync detection ──────────────────────────────────────────────
        all_idle = n_idle == len(self._ctrl_map)
        if all_idle and not any_bus_req and time - self._last_sync_t > 5.0:
            self._last_sync_t = time
            self._sync_count += 1
            if LOG_CORRIDOR:
                _vprint(
                    f"[CORRIDOR SYNC] t={time:.0f} group={self.name} "
                    f"sync#{self._sync_count} — all {len(self._ctrl_map)} members IDLE "
                    f"(phase_groups={list(n_groups.values())})"
                )

    # ------------------------------------------------------------------
    def summary(self) -> str:
        return (
            f"CorridorCoordinator group={self.name} "
            f"members={self.inter_ids} syncs={self._sync_count} "
            f"pre_arms_pending={len(self._pre_requests)}"
        )


# module-level list populated in AAPIInit
corridor_coordinators: list = []


# =============================================================================
# INTERSECTION CONTROLLER
# =============================================================================

class IntersectionController:

    def __init__(self, config):

        # ── static config ─────────────────────────────────────────────
        self.config  = config
        raw_id = config['IntersectionID']
        if not isinstance(raw_id, int):
            raise TypeError(
                f"IntersectionID must be int, got {type(raw_id).__name__}: {raw_id!r} "
                f"— check intersection_configs.py for unfilled placeholder IDs")
        
        self.id = raw_id
        self.TSPStrategy =0
        self.current_phase = 1
        self.stats   = stats
        self.CarOcc  = config['CarOcc']
        self.BusOcc  = config['BusOcc']
        self.id      = config["IntersectionID"]
        # node_id: the Aimsun-internal node ID for all topology/signal API calls.
        # Start with any explicitly configured override, defaulting to self.id.
        # _resolve_node_id() (called after section tracking is set up) will
        # auto-correct this via section topology if the configured value is wrong.
        self.node_id = config.get("AimsunNodeID", self.id)

        self.BusPhase         = config.get("BusPhase",2)
        self.BusPhaseDuration = config["BusPhaseDuration"]
        self.BusDet           = config.get("BusDet", [])
        self.main_sections = config.get('MainSections', [])
        self.side_sections = config.get('SideSections', [])
        self.call_sections = config.get(
            'call_sections',
            config.get('BusCallDetectors',
                    config.get('BusDet', []))
        )
        
        self.UpDetList        = config["UpDetList"]
        self.SignalGroupIDList = config["SignalGroupIDList"]
        self.PhaseIndex       = config["PhaseIndex"]
        self.VehLength        = config.get("VehLength", 4.5)
        self.DetLength        = config.get("DetLength", 5)
        self.JamDensity       = config.get("JamDensity", 200)
        self.SaturationDensity= config.get("SaturationDensity", 35)
        self.SaturationFlow   = config.get("SaturationFlow", 1800)
        self.GE_lower_bound   = config.get("GE_lower_bound", 0)
        self.GE_upper_bound   = config.get("GE_upper_bound", 30)
        self.BP_lower_bound   = config.get("BP_lower_bound", 5)
        self.BP_upper_bound   = config.get("BP_upper_bound", 60)
                # === TSP COOLDOWN (prevents spam) ===
        self.last_tsp_action_time = 0.0          # ← ADD THIS
        self.tsp_cooldown_seconds = 60.0         # 60 s = one full cycle on most plans
        if "DetDistance" in self.config:
            d = self.config["DetDistance"]
            if not isinstance(d, (list, tuple)) or len(d) == 0:
                self.config["DetDistance"] = [[50.0]]
            elif not isinstance(d[0], (list, tuple)):
                self.config["DetDistance"] = [d]
        else:
            self.config["DetDistance"] = [[50.0]]
        self.DetDistance = self.config["DetDistance"]
         
        self.max_iterations   = config.get("max_iterations", 20)
        self.harmony_memory_size = config.get("harmony_memory_size", 10)
        self.hmcr             = config.get("hmcr", 0.9)
        self.par              = config.get("par", 0.3)
        self.NumberOfLanes    = config.get("NumberOfLanes", 1)

        self.CarOcc = config.get('CarOcc', 1.5)
        self.BusOcc = config.get('BusOcc', 40.0)
        self.TruckOcc = config.get('TruckOcc', self.CarOcc)
        
        '''
        self.UpDetList = config.get('UpDetList', [])
        self.SignalGroupIDList = config.get('SignalGroupIDList', [])
        self.PhaseIndex = config.get('PhaseIndex', {})
        self.VehLength = config.get('VehLength', 7.0)
        self.DetLength = config.get('DetLength', 5.0)
        self.JamDensity = config.get('JamDensity', 150)
        self.SaturationDensity = config.get('SaturationDensity', 35)
        self.SaturationFlow = config.get('SaturationFlow', 1800)
        self.GE_lower_bound = config.get('GE_lower_bound', 0)
        self.GE_upper_bound = config.get('GE_upper_bound', 30)
        self.BP_lower_bound = config.get('BP_lower_bound', 5)
        self.BP_upper_bound = config.get('BP_upper_bound', 60)
        self.DetDistance = config.get('DetDistance', [[]])
        self.max_iterations = config.get('max_iterations', 20)
        self.harmony_memory_size = config.get('harmony_memory_size', 10)
        self.hmcr = config.get('hmcr', 0.9)
        self.par = config.get('par', 0.3)
        self.NumberOfLanes = config.get('NumberOfLanes', 1)
        '''

        # ── URTSP config — read from config dict or use defaults ──────
        u = URTSP_DEFAULTS
        self.urtsp_ge_extension      = config.get("GE_extension",           u["GE_extension"])
        self.urtsp_ins_min           = config.get("insertion_min_duration",  u["insertion_min_duration"])
        self.urtsp_ins_max           = config.get("insertion_max_duration",  u["insertion_max_duration"])
        self.urtsp_cycle_length      = config.get("cycle_length",            u["cycle_length"])
        self.urtsp_detection_window  = config.get("detection_window_m",      u["detection_window_m"])
        self.urtsp_pt_line_filter    = config.get("priority_pt_line_ids",    u["priority_pt_line_ids"])

        # call detectors: prefer dedicated URTSP list, else use BusDet
        self.urtsp_call_det_ids = config.get("BusCallDetectors", self.BusDet)
        self.urtsp_exit_det_ids = config.get("BusExitDetectors", [])

        # ── resolve detector geometry once at init ────────────────────
        self._urtsp_call_geometry = {}   # {det_id: (section_id, ini_pos, fin_pos)}
        self._urtsp_exit_geometry = {}
        self._resolve_urtsp_geometry()

        # ── URTSP runtime state (instance variables — no globals) ─────
        self._urtsp_flag               = 0      # 0=idle 1=extension 2=insertion
        self._urtsp_prev_phase         = -1
        self._urtsp_prev_phase_elapsed = -1.0
        self._urtsp_insertion_start    = -1.0
        self._urtsp_granted_this_cycle = False
        self._urtsp_cycle_reset_time   = -1.0
        self._urtsp_served_veh_ids     = set()
        self._urtsp_active_veh_id      = -1
        self._urtsp_bus_phase_nominal  = GetPhaseDuration(self.node_id, self.BusPhase, 0.0)
        # end-of-run counters
        self._urtsp_n_detections   = 0
        self._urtsp_n_extensions   = 0
        self._urtsp_n_insertions   = 0
        self._urtsp_n_exit_clears  = 0
        self._urtsp_n_cap_clears   = 0

        # ── general dynamic state ─────────────────────────────────────
        self.prev_total_delay   = 0.0
        self.TSPActiveTime      = 0
        self.flag               = 0      # used by HARMONY / NORMAL paths
        self.previous_phase     = None
        self.last_detected_bus_id = -1
        self.incoming_sections  = []
        self._initialize_section_tracking()
        self._resolve_node_id()   # verify/auto-fix node_id after sections are known
        self.phase_list         = []

        num_phases = ECIGetNumberPhases(self.id)
        self.phase_list = list(range(1, num_phases + 1))

        stats_car_pos = getattr(self.stats, '_car_pos', -1)
        stats_bus_pos = getattr(self.stats, '_bus_pos', -1)
        scan_car_pos, scan_bus_pos, scan_truck_pos = _scan_named_vehicle_type_positions()

        self.bus_type_pos = stats_bus_pos if stats_bus_pos > 0 else scan_bus_pos
        if self.bus_type_pos <= 0:
            cfg_bus_pos = safe_float(config.get('BUS_TYPE_POS', -1), -1.0)
            self.bus_type_pos = int(cfg_bus_pos) if cfg_bus_pos > 0 else -1

        self.car_type_pos = stats_car_pos if stats_car_pos > 0 else scan_car_pos
        if self.car_type_pos <= 0:
            self.car_type_pos = _choose_car_type_pos(
                self.bus_type_pos,
                scan_truck_pos if scan_truck_pos > 0 else getattr(self.stats, '_truck_pos', -1),
                preferred_pos=self.car_type_pos)

        if LOG_INIT: AKIPrintString(f"[INIT] Inter {self.id} | car_type_pos={self.car_type_pos} bus_type_pos={self.bus_type_pos}")
        self.print_config_summary()
        if LOG_INIT: AKIPrintString(f"[INIT] Phase list: {self.phase_list}")

        self.initialize_state()
        # Warmup: suppress TSP for the first two signal cycles so the
        # network can settle before any priority decisions are made.
        _warmup = 2.0 * float(self.config.get('CycleTime', 135))
        self.TSPActiveTime = _warmup

        initial_state = self.build_state()
        state_dim  = len(initial_state)
        action_dim = len(self.UpDetList)
        # ── RL agent — only load when mode is RL ──────────────────────
        self.rl_agent   = None
        self.TRAIN_MODE = False
        if CONTROL_MODE == 'RL':
            try:
                from rl_agent import RLIntersectionAgent
                self.rl_agent   = RLIntersectionAgent(state_dim, action_dim, algorithm='DQN')
                self.TRAIN_MODE = True
                self.rl_agent.load_model("trained_model.pth")
                if LOG_INIT: AKIPrintString(f"[RL] Agent loaded for intersection {self.id}")
            except Exception as e:
                _vprint(f"[RL] WARNING: Could not load RL agent: {e}")

        # ── GROUP_BASED sub-controller ────────────────────────────────
        self.gb = None
        if CONTROL_MODE in ("GROUP_BASED", "GROUP_BASED_URTSP", "GROUP_BASED_HARMONY"):
            gb_config = config.get("GroupBasedConfig")

            # Auto-build GroupBasedConfig from SignalGroupIDList when not provided
            if not gb_config or not gb_config.get("sg_list"):
                _sg_nested  = config.get("SignalGroupIDList", [])
                _all_sgs    = sorted({sg for phase in _sg_nested for sg in phase})
                _green_durs = config.get("GreenPhaseDuration", [])
                if _all_sgs:
                    _min_green = {sg: 6.0 for sg in _all_sgs}
                    _max_green = {}
                    for _ph_i, _ph_sgs in enumerate(_sg_nested):
                        _dur = _green_durs[_ph_i] if _ph_i < len(_green_durs) else 30.0
                        for _sg in _ph_sgs:
                            # Use the longest green phase this SG appears in as max_green
                            _max_green[_sg] = max(_max_green.get(_sg, 0.0), float(_dur))
                    for _sg in _all_sgs:
                        if _sg not in _max_green:
                            _max_green[_sg] = 30.0
                    # Derive bus_sg: which SG position controls the approach
                    # section that the bus call-detectors are placed on.
                    #
                    # Method 1 — explicit override in config (always wins)
                    # Method 2 — Aimsun API: for each bus detector, get its
                    #            section, then scan SG turning movements to find
                    #            which SG position has that section as its origin
                    # Method 3 — BusPhase fallback: first SG of the bus phase
                    # Method 4 — _all_sgs[0] as final last resort
                    _bus_sg = config.get('BusSG')   # Method 1
                    _bus_sg_method = 1 if _bus_sg is not None else None

                    # Build SG position→ID map so Method 2 returns an ID that
                    # exists in the conflict matrix (not a raw position index).
                    # ECIGetFromToofTurningofSignalGroup uses 1-based positions;
                    # ECIGetSignalGroupPhaseofJunction returns IDs — they differ.
                    _sg_pos_to_id: dict = {}
                    try:
                        _n_sgs_total = ECIGetNumberSignalGroups(self.id)
                        for _ph_scan in range(1, ECIGetNumberPhases(self.id) + 1):
                            _n_in_ph = ECIGetNbSignalGroupsPhaseofJunction(
                                self.id, _ph_scan, 0.0)
                            for _pp in range(1, _n_in_ph + 1):
                                _sg_id_here = ECIGetSignalGroupPhaseofJunction(
                                    self.id, _ph_scan, _pp, 0.0)
                                if _sg_id_here > 0:
                                    # Map position index (pp within phase) back to
                                    # the global SG position.
                                    # Use the ID itself as a best-effort fallback:
                                    # for most Aimsun models position == ID.
                                    _sg_pos_to_id[_sg_id_here] = _sg_id_here
                    except Exception:
                        pass

                    if _bus_sg is None:
                        # Method 2: detector section → SG ID lookup via turning movements
                        _bus_dets = config.get('BusDet', config.get('BusCallDetectors', []))
                        _det_sections: set = set()
                        for _det_id in _bus_dets:
                            try:
                                _dp = AKIDetGetPropertiesDetectorById(_det_id)
                                if _dp.report >= 0 and _dp.IdSection > 0:
                                    _det_sections.add(int(_dp.IdSection))
                            except Exception:
                                pass

                        if _det_sections:
                            try:
                                _n_sgs = ECIGetNumberSignalGroups(self.id)
                                # Build position→ID map from phase scan for accurate lookup
                                _pos_to_id: dict = {}
                                try:
                                    for _ph2 in range(1, ECIGetNumberPhases(self.id) + 1):
                                        _n2 = ECIGetNbSignalGroupsPhaseofJunction(
                                            self.id, _ph2, 0.0)
                                        for _p2 in range(1, _n2 + 1):
                                            _sid = ECIGetSignalGroupPhaseofJunction(
                                                self.id, _ph2, _p2, 0.0)
                                            # Positions are 1..ECIGetNumberSignalGroups.
                                            # We don't have a direct pos→id API call so
                                            # use ID as position key (works when id==pos).
                                            if _sid > 0:
                                                _pos_to_id[_sid] = _sid
                                except Exception:
                                    pass

                                _found_pos = None
                                _found_sec = None
                                for _sg_pos in range(1, _n_sgs + 1):
                                    try:
                                        _n_turns = ECIGetNumberTurningsofSignalGroup(
                                            self.id, _sg_pos)
                                        for _ti in range(_n_turns):
                                            _fp = intp(); _tp = intp()
                                            ECIGetFromToofTurningofSignalGroup(
                                                self.id, _sg_pos, _ti, _fp, _tp)
                                            if _fp.value() in _det_sections:
                                                _found_pos = _sg_pos
                                                _found_sec = _fp.value()
                                                break
                                    except Exception:
                                        pass
                                    if _found_pos is not None:
                                        break

                                if _found_pos is not None:
                                    # SG position == SG ID in standard Aimsun models;
                                    # verify the resolved ID exists in _all_sgs (derived
                                    # from phase scan).  If not, fall through to Method 3.
                                    _candidate_id = _pos_to_id.get(_found_pos, _found_pos)
                                    if _candidate_id in _all_sgs:
                                        _bus_sg = _candidate_id
                                        _bus_sg_method = 2
                                        _vprint(
                                            f"[GB] inter={self.id} bus_sg method2: "
                                            f"pos={_found_pos} → id={_bus_sg} "
                                            f"(det_sec={_found_sec})"
                                        )
                                    else:
                                        _vprint(
                                            f"[GB] inter={self.id} bus_sg method2 "
                                            f"pos={_found_pos} id={_candidate_id} NOT in "
                                            f"all_sgs={_all_sgs} — falling back"
                                        )
                            except Exception:
                                pass
                    else:
                        _det_sections = set()

                    if _bus_sg is None:
                        # Method 3: first SG ID of BusPhase (from Aimsun phase scan)
                        _bus_phase_idx = config.get('BusPhase', 1) - 1
                        _bus_phase_sgs = (
                            _sg_nested[_bus_phase_idx]
                            if 0 <= _bus_phase_idx < len(_sg_nested) else []
                        )
                        # _sg_nested is built from Aimsun phase IDs — use directly
                        _valid_bp = [s for s in _bus_phase_sgs if s in _all_sgs]
                        if _valid_bp:
                            _bus_sg = _valid_bp[0]
                            _bus_sg_method = 3
                            _vprint(
                                f"[GB] inter={self.id} bus_sg method3 (BusPhase): "
                                f"phase_idx={_bus_phase_idx} → id={_bus_sg}"
                            )

                    if _bus_sg is None:
                        _bus_sg = _all_sgs[0] if _all_sgs else None  # Method 4
                        _bus_sg_method = 4
                        _vprint(
                            f"[GB] inter={self.id} bus_sg method4 (fallback): "
                            f"id={_bus_sg}"
                        )

                    gb_config = {
                        'sg_list':         _all_sgs,
                        'min_green':       _min_green,
                        'max_green':       _max_green,
                        'sections':        [],
                        'bus_det':         config.get('BusDet', config.get('BusCallDetectors', [])),
                        'bus_sg':          _bus_sg,
                        'CarOcc':          config.get('CarOcc', 1.5),
                        'BusOcc':          config.get('BusOcc', 40.0),
                        # Preserve the raw phase structure so the controller can
                        # build a correct compatibility fallback when the Aimsun
                        # ECI phase scan returns nothing at AAPIInit time.
                        'phase_sg_nested': _sg_nested,
                        # Detection zone and ETA filter (inherited from main config)
                        'detection_zone_m': config.get('detection_zone_m', 300.0),
                        'eta_min_s':        config.get('eta_min_s',  5.0),
                        'eta_max_s':        config.get('eta_max_s', 60.0),
                    }
                    config['GroupBasedConfig'] = gb_config
                    _vprint(
                        f"[GB] inter={self.id} auto-built GroupBasedConfig "
                        f"SGs={_all_sgs} bus_sg={_bus_sg} (method={_bus_sg_method}) "
                        f"det_sections={_det_sections}"
                    )
                else:
                    _vprint(
                        f"[GB] WARNING inter={self.id} no sg_list and no "
                        f"SignalGroupIDList found — GROUP_BASED disabled "
                        f"for this intersection. Add 'SignalGroupIDList' or "
                        f"'GroupBasedConfig' to its entry in intersection_configs.py"
                    )

            if gb_config and gb_config.get("sg_list"):
                _gb_tsp_mode = {
                    "GROUP_BASED":         "basic",
                    "GROUP_BASED_URTSP":   "urtsp",
                    "GROUP_BASED_HARMONY": "harmony",
                }.get(CONTROL_MODE, "basic")
                self.gb = GroupBasedController(
                    self.id, gb_config, stats_ref=stats, tsp_mode=_gb_tsp_mode)
            if LOG_GB:
                _vprint(
                    f"[GB] inter={self.id} GroupBasedController "
                    f"{'created' if self.gb else 'FAILED — gb=None'}"
                )

        if LOG_URTSP: AKIPrintString(f"[URTSP] Intersection {self.id} ready | "
                       f"mode={CONTROL_MODE} | "
                       f"call_dets={self.urtsp_call_det_ids} | "
                       f"exit_dets={self.urtsp_exit_det_ids}")

    # =========================================================================
    # URTSP — GEOMETRY RESOLUTION
    # =========================================================================


    
    
    def _resolve_urtsp_geometry(self):
        """Cache section_id and positions for call and exit detectors."""
        for det_id in self.urtsp_call_det_ids:
            props = AKIDetGetPropertiesDetectorById(det_id)
            if props.report < 0:
                if LOG_URTSP: AKIPrintString(f"[URTSP] WARNING: call det {det_id} not found")
                continue
            self._urtsp_call_geometry[det_id] = (
                props.IdSection, props.InitialPosition, props.FinalPosition)
            if LOG_URTSP: AKIPrintString(f"[URTSP] call det={det_id} "
                           f"section={props.IdSection} "
                           f"pos=[{props.InitialPosition:.1f},{props.FinalPosition:.1f}]m")

        for det_id in self.urtsp_exit_det_ids:
            props = AKIDetGetPropertiesDetectorById(det_id)
            if props.report < 0:
                if LOG_URTSP: AKIPrintString(f"[URTSP] WARNING: exit det {det_id} not found")
                continue
            self._urtsp_exit_geometry[det_id] = (
                props.IdSection, props.InitialPosition, props.FinalPosition)
            if LOG_URTSP: AKIPrintString(f"[URTSP] exit det={det_id} "
                           f"section={props.IdSection} "
                           f"pos=[{props.InitialPosition:.1f},{props.FinalPosition:.1f}]m")

        # read nominal bus-phase duration from background plan
        self._urtsp_bus_phase_nominal = GetPhaseDuration(
            self.id, self.BusPhase, 0.0)
        if LOG_URTSP: AKIPrintString(f"[URTSP] bus phase nominal = {self._urtsp_bus_phase_nominal:.1f}s")

    
    
    def _resolve_urtsp_geometry(self):
        for det_id in self.urtsp_call_det_ids:
            props = AKIDetGetPropertiesDetectorById(det_id)
            if props.report >= 0:
                self._urtsp_call_geometry[det_id] = (props.IdSection, props.InitialPosition, props.FinalPosition)

        for det_id in self.urtsp_exit_det_ids:
            props = AKIDetGetPropertiesDetectorById(det_id)
            if props.report >= 0:
                self._urtsp_exit_geometry[det_id] = (props.IdSection, props.InitialPosition, props.FinalPosition)

        self._urtsp_bus_phase_nominal = GetPhaseDuration(self.node_id, self.BusPhase, 0.0)
    
    # =========================================================================
    # URTSP — PT VEHICLE HELPERS
    # =========================================================================

    def _get_pt_vehicles(self):
        """
        Return list of (line_id, inf) for PT vehicles AND injected buses.
        Primary: scan registered PT lines.
        Fallback: scan bus vehicles directly on call sections (catches
                  injected buses not registered as PT line vehicles).
        """
        result = []
        seen   = set()
        allowed = set(self.urtsp_pt_line_filter) if self.urtsp_pt_line_filter else None

        # ── Primary: registered PT lines ─────────────────────────────
        for li in range(AKIPTGetNumberLines()):
            line_id = AKIPTGetIdLine(li)
            if allowed is not None and line_id not in allowed:
                continue
            for vi in range(AKIGetNbVehiclesFollowingPTLine(line_id)):
                veh_id = AKIGetVehicleFollowingPTLine(line_id, vi)
                inf    = AKIPTVehGetInf(veh_id)
                if inf.report >= 0:
                    result.append((line_id, inf))
                    seen.add(veh_id)

        # ── Fallback: scan bus vehicles directly on call sections ─────
        for det_id, (sec_id, _, _) in self._urtsp_call_geometry.items():
            n = AKIVehStateGetNbVehiclesSection(sec_id, True)
            for i in range(n):
                inf = AKIVehStateGetVehicleInfSection(sec_id, i)
                if inf.idVeh in seen:
                    continue
                if inf.type != self.bus_type_pos:
                    continue
                result.append((-1, inf))
                seen.add(inf.idVeh)

        return result

    def _scan_urtsp_call(self, pt_vehicles):
        """
        Scan call detector zones for an unserved eligible bus.
        Scans from position 0 to fin_pos + window to catch approaching buses.
        Returns (veh_id, line_id, det_id, pos) or (-1,-1,-1,-1.0).
        """
        w = self.urtsp_detection_window
        for det_id, (sec_id, ini_pos, fin_pos) in self._urtsp_call_geometry.items():
            # Widen UPSTREAM only — fin_pos is the intended downstream boundary.
            # Matches TSP_single_intersection: detect_ini widened by window,
            # detect_fin preserved as fin_pos so buses that already passed are excluded.
            detect_ini = max(0.0, fin_pos - w)
            detect_fin = fin_pos
            for line_id, inf in pt_vehicles:
                if inf.idSection != sec_id:
                    continue
                if not (detect_ini <= inf.CurrentPos <= detect_fin):
                    continue
                veh_id = inf.idVeh
                pos    = inf.CurrentPos
                if veh_id in self._urtsp_served_veh_ids:
                    pass
                elif self._urtsp_flag != 0:
                    _vprint(
                        f"[URTSP] SKIP veh={veh_id} line={line_id} "
                        f"pos={pos:.1f}m reason=tsp_active(flag={self._urtsp_flag})")
                    self._urtsp_served_veh_ids.add(veh_id)
                elif self._urtsp_granted_this_cycle:
                    _vprint(
                        f"[URTSP] SKIP veh={veh_id} line={line_id} "
                        f"pos={pos:.1f}m reason=already_granted_this_cycle")
                    self._urtsp_served_veh_ids.add(veh_id)
                else:
                    _vprint(
                        f"[URTSP] BUS IN ZONE | veh={veh_id} line={line_id} "
                        f"sec={sec_id} pos={pos:.1f}m zone=[{detect_ini:.1f},{detect_fin:.1f}]m")
                    return veh_id, line_id, det_id, pos
        return -1, -1, -1, -1.0

    def _check_urtsp_exit(self, veh_id, pt_vehicles):
        for _, (sec_id, _, fin_pos) in self._urtsp_exit_geometry.items():
            detect_ini = 0.0
            detect_fin = fin_pos + self.urtsp_detection_window
            for _, inf in pt_vehicles:
                if inf.idVeh == veh_id and inf.idSection == sec_id:
                    if detect_ini <= inf.CurrentPos <= detect_fin:
                        return True
        return False

    def _bus_on_call_section(self, veh_id, pt_vehicles):
        """Return True if veh_id is still on any call detector section."""
        for _, (sec_id, _, _) in self._urtsp_call_geometry.items():
            for _, inf in pt_vehicles:
                if inf.idVeh == veh_id and inf.idSection == sec_id:
                    return True
        return False

    # =========================================================================
    # URTSP — MAIN STATE MACHINE  (replaces run_normal / check_bus_priority)
    # =========================================================================

    def run_urtsp(self, time, timeSta, acycle):
        # ── Diagnostic every 300s: confirm buses are on call sections ──
        if int(time) % 300 == 0 and int(time) != getattr(self, '_last_diag_t', -1):
            self._last_diag_t = int(time)
            pt_count = len(self._get_pt_vehicles())
            for det_id, (sec_id, ini, fin) in self._urtsp_call_geometry.items():
                n = AKIVehStateGetNbVehiclesSection(sec_id, True)
                _vprint(
                    f"[URTSP] DIAG t={time:.0f}s inter={self.id} "
                    f"det={det_id} sec={sec_id} "
                    f"veh_on_section={n} pt_vehicles={pt_count}")

        current_phase  = ECIGetCurrentPhase(self.node_id)
        phase_start    = ECIGetStartingTimePhase(self.node_id)
        phase_elapsed  = time - phase_start
        phase_duration = GetPhaseDuration(self.node_id, current_phase, timeSta)

        pt_vehicles = self._get_pt_vehicles()

        # ── per-cycle grant reset ─────────────────────────────────────
        if self._urtsp_granted_this_cycle and time >= self._urtsp_cycle_reset_time:
            if LOG_URTSP: AKIPrintString(f"[URTSP] cycle grant reset at t={time:.1f}s")
            self._urtsp_granted_this_cycle = False

        # ── expire served_veh_ids ─────────────────────────────────────
        self._urtsp_served_veh_ids = {
            vid for vid in self._urtsp_served_veh_ids
            if self._bus_on_call_section(vid, pt_vehicles)
        }

        # ── FLAG 1: GREEN EXTENSION active ────────────────────────────
        if self._urtsp_flag == 1:
            if current_phase != self.BusPhase:
                self.reset_bus_color(self._urtsp_active_veh_id)
                if LOG_URTSP: AKIPrintString(f"[URTSP] EXTENSION ENDED | t={time:.1f}s "
                               f"resumed phase={current_phase}")
                self._urtsp_flag           = 0
                self._urtsp_active_veh_id  = -1
            return

        # ── FLAG 2: PHASE INSERTION active ───────────────────────────
        if self._urtsp_flag == 2:
            insertion_elapsed = time - self._urtsp_insertion_start
            min_ok      = insertion_elapsed >= self.urtsp_ins_min
            bus_cleared = min_ok and self._check_urtsp_exit(
                self._urtsp_active_veh_id, pt_vehicles)
            cap_reached = insertion_elapsed >= self.urtsp_ins_max

            if bus_cleared or cap_reached:
                self.reset_bus_color(self._urtsp_active_veh_id)
                reason          = "exit_detector" if bus_cleared else "cap"
                restore_elapsed = self._urtsp_prev_phase_elapsed if bus_cleared else 0.0
                _vprint(
                    f"[URTSP] INSERTION ENDED | t={time:.1f}s | reason={reason} "
                    f"duration={insertion_elapsed:.1f}s | "
                    f"restoring phase={self._urtsp_prev_phase} elapsed={restore_elapsed:.1f}s")
                ECIChangeDirectPhase(self.node_id, self._urtsp_prev_phase,
                                     timeSta, time, acycle, restore_elapsed)
                if bus_cleared:
                    self._urtsp_n_exit_clears += 1
                    self.stats.record_tsp_event(self.id, 'exit_clear')
                else:
                    self._urtsp_n_cap_clears  += 1
                    self.stats.record_tsp_event(self.id, 'cap_clear')
                self._urtsp_flag               = 0
                self._urtsp_prev_phase         = -1
                self._urtsp_prev_phase_elapsed = -1.0
                self._urtsp_insertion_start    = -1.0
                self._urtsp_active_veh_id      = -1
            return

        # ── IDLE: scan call detectors ─────────────────────────────────
        veh_id, line_id, det_id, pos = self._scan_urtsp_call(pt_vehicles)
        if veh_id < 0:
            return

        self._urtsp_n_detections        += 1
        self._urtsp_served_veh_ids.add(veh_id)
        self._urtsp_granted_this_cycle   = True
        self._urtsp_cycle_reset_time     = time + self.urtsp_cycle_length
        self.stats.record_tsp_event(self.id, 'detection')

        remaining = max(0.0, phase_duration - phase_elapsed)
        _vprint(
            f"[URTSP] DETECTED | t={time:.1f}s | veh={veh_id} line={line_id} "
            f"det={det_id} pos={pos:.1f}m | phase={current_phase} "
            f"elapsed={phase_elapsed:.1f}s dur={phase_duration:.1f}s rem={remaining:.1f}s")

        # ── Strategy 1: GREEN EXTENSION ───────────────────────────────
        if current_phase == self.BusPhase:
            new_dur = self._urtsp_bus_phase_nominal + self.urtsp_ge_extension
            _vprint(
                f"[URTSP] GREEN EXTENSION | new_dur={new_dur:.1f}s "
                f"(nominal={self._urtsp_bus_phase_nominal:.1f}s "
                f"+ {self.urtsp_ge_extension:.0f}s)")
            ECIChangeTimingPhase(self.node_id, current_phase, new_dur, timeSta)
            self._urtsp_active_veh_id = veh_id
            self._urtsp_flag          = 1
            self._urtsp_n_extensions += 1
            self.highlight_bus(veh_id)   # ✅ ADD THIS
            self.stats.record_tsp_event(self.id, 'extension')

        # ── Strategy 2: PHASE INSERTION ───────────────────────────────
        else:
            _vprint(
                f"[URTSP] PHASE INSERTION | inserting phase={self.BusPhase} "
                f"interrupted phase={current_phase} at {phase_elapsed:.1f}s")
            self._urtsp_prev_phase         = current_phase
            self._urtsp_prev_phase_elapsed = phase_elapsed
            self._urtsp_insertion_start    = time
            self._urtsp_active_veh_id      = veh_id
            ECIChangeDirectPhase(self.node_id, self.BusPhase,
                                 timeSta, time, acycle, 0)
            self._urtsp_flag            = 2
            self._urtsp_n_insertions   += 1
            self.highlight_bus(veh_id)
            self.stats.record_tsp_event(self.id, 'insertion')

    def get_urtsp_summary(self):
        """Return a summary string for AAPIFinish."""
        return (
            f"[URTSP] intersection={self.id} | "
            f"detections={self._urtsp_n_detections} | "
            f"extensions={self._urtsp_n_extensions} | "
            f"insertions={self._urtsp_n_insertions} | "
            f"exit_det_clears={self._urtsp_n_exit_clears} | "
            f"cap_clears={self._urtsp_n_cap_clears}"
        )

    # =========================================================================
    # EXISTING METHODS — unchanged from original
    # =========================================================================

    def initialize_state(self):

        n_phases = max(self.config.get("NumberOfPhases", 1), 1)
        n_lanes  = max(self.NumberOfLanes, 1)
        n_busdet = max(len(self.BusDet), 1)
        # Queue arrays must be wide enough for all detectors in the largest UpDetList group.
        # After NB+SB merge a group may have more detectors than n_lanes.
        _max_group = max((len(g) for g in self.UpDetList if g), default=1)
        n_cols = max(n_lanes, _max_group)
        
        
        self.BusPresence           = np.zeros((1, n_busdet))
        self.BusSpeed              = np.zeros((1, n_busdet))

        self.UpDetCountList        = np.zeros((n_phases, n_cols))
        self.UpDetOccList          = np.zeros((n_phases, n_cols))
        self.UpAveOccList          = np.zeros((n_phases, n_cols))
        self.RedStartTimeList      = np.zeros((n_phases, n_cols))
        self.GreenStartTimeList    = np.zeros((n_phases, n_cols))
        self.RedDurationList       = np.zeros((n_phases, n_cols))
        self.GreenDurationList     = np.zeros((n_phases, n_cols))
        self.UpFlowList            = np.zeros((n_phases, n_cols))
        self.UpDenList             = np.zeros((n_phases, n_cols))
        self.ShockwaveSpeed1List   = np.zeros((n_phases, n_cols))
        self.ShockwaveSpeed2List   = np.zeros((n_phases, n_cols))
        self.ShockwaveSpeed3List   = np.zeros((n_phases, n_cols))
        self.ShockwaveSpeed4List   = np.zeros((n_phases, n_cols))
        self.MaxQueueLength        = np.zeros((n_phases, n_cols))
        self.MaxQueueLengthTime    = np.zeros((n_phases, n_cols))
        self.MinQueueLength        = np.zeros((n_phases, n_cols))
        self.MinQueueLengthTime    = np.zeros((n_phases, n_cols))
        self.QueueDissTime         = np.zeros((n_phases, n_cols))
        self.NextRedStartTime      = np.zeros((n_phases, n_cols))

        # Harmony Search arrays
        self.HSRedStartTimeList    = np.zeros((n_phases, n_cols))
        self.HSRedDurationList     = np.zeros((n_phases, n_cols))
        self.HSGreenStartTimeList  = np.zeros((n_phases, n_cols))
        self.HSGreenDurationList   = np.zeros((n_phases, n_cols))
        self.HSNextRedStartTime    = np.zeros((n_phases, n_cols))
        self.HSUpFlowList          = np.zeros((n_phases, n_cols))
        self.HSUpDenList           = np.zeros((n_phases, n_cols))
        self.HSShockwaveSpeed1List = np.zeros((n_phases, n_cols))
        self.HSShockwaveSpeed3List = np.zeros((n_phases, n_cols))
        self.HSMaxQueueLength      = np.zeros((n_phases, n_cols))
        self.HSMaxQueueLengthTime  = np.zeros((n_phases, n_cols))
        self.HSMinQueueLength      = np.zeros((n_phases, n_cols))

        self.BusDelay              = np.zeros((n_phases, n_cols))
        self.OtherDelay            = np.zeros((n_phases, n_cols))
        self.TotalVeh              = np.zeros((n_phases, n_cols))

        side_secs = self._get_side_sections()
        n_side = max(len(side_secs), 1)
        self.SideUpFlowList        = np.zeros(n_side)
        self.SideUpDenList         = np.zeros(n_side)
        self.SideShockwaveSpeed1   = np.zeros(n_side)
        self.SideShockwaveSpeed3   = np.zeros(n_side)
        self._side_red_start       = np.zeros(n_side)
        self._side_last_phase      = ECIGetCurrentPhase(self.node_id)

        # Other state variables
        self.BusJoinQueueTime      = np.zeros((n_phases, n_cols))
        self.BusStoplineTime       = np.zeros((n_phases, n_cols))
        self.BusPhaseMinDuration   = np.zeros((n_phases, n_cols))
        self.HSQueueDissTime       = np.zeros((n_phases, n_cols))

        self.step_delay            = 0.0
        self.TSPActiveTime         = 0.0
        self.flag                  = 0
        self.previous_phase        = ECIGetCurrentPhase(self.node_id)
        self.last_detected_bus_id  = -1

        # Sentinel values
        self.BusPhaseEndTime       = 1e9
        self.TimeToTerminateBusPhase = 1e9

        if LOG_INIT: AKIPrintString(f"[INIT] Inter {self.id} | phases={n_phases} | lanes={n_lanes} | busdets={n_busdet} | arrays initialized safely")

    def _get_inter_state(self):
        inter_map = getattr(self.stats, '_inter', None)
        if inter_map is None:
            return None
        return inter_map.get(self.id)

    def _normalize_sections(self, sections):
        if sections is None:
            return []

        if isinstance(sections, np.ndarray):
            sections = sections.tolist()
        elif isinstance(sections, str):
            sections = sections.replace(';', ',').split(',')
        elif isinstance(sections, (int, float, np.integer, np.floating)):
            sections = [sections]
        else:
            try:
                sections = list(sections)
            except TypeError:
                sections = [sections]

        normalized = []
        seen = set()
        for sec in sections:
            sec_val = safe_float(sec, default=-1.0)
            if sec_val <= 0.0:
                continue
            sec_id = int(sec_val)
            if sec_id not in seen:
                seen.add(sec_id)
                normalized.append(sec_id)
        return normalized

    def _derive_sections_from_detectors(self):
        sections = []
        seen = set()
        invalid_dets = []
        valid_dets = []
        for phase in self.UpDetList:
            for det_id in phase:
                det_info = AKIDetGetPropertiesDetectorById(det_id)
                if getattr(det_info, 'report', -1) < 0:
                    invalid_dets.append(det_id)
                    continue
                valid_dets.append(det_id)
                sec_id = int(getattr(det_info, 'IdSection', 0) or 0)
                if sec_id > 0 and sec_id not in seen:
                    seen.add(sec_id)
                    sections.append(sec_id)
        if invalid_dets:
            # Scan ALL detectors in the model and report any whose IDs are
            # adjacent (±2000) to the invalid IDs — helpful for finding the real IDs.
            _nearby = {}
            _all_det_sec = {}   # det_id → section_id for every valid detector in model
            try:
                n_all = AKIDetGetNumberDetectors()
                for _di in range(n_all):
                    _did = AKIDetGetIdDetector(_di)
                    _p = AKIDetGetPropertiesDetectorById(_did)
                    if getattr(_p, 'report', -1) >= 0:
                        _dsec = getattr(_p, 'IdSection', -1)
                        _all_det_sec[_did] = _dsec
                        for _bad in invalid_dets:
                            if abs(_did - _bad) <= 2000:
                                _nearby[_did] = _dsec
            except Exception:
                pass

            # Junction-based scan: find detectors on turn-origin sections that are
            # NOT in the valid-detector section list — identifies missing approach dets
            _junction_cands = {}
            if True:   # always run: even partial valid_dets can miss an approach
                try:
                    n_turns = AKIInfNetGetNbTurnsInNode(self.node_id)
                    _turn_orig_secs = set()
                    for _ti in range(n_turns):
                        try:
                            _tsec = AKIInfNetGetOriginSectionInTurn(self.node_id, _ti)
                            if _tsec > 0:
                                _turn_orig_secs.add(_tsec)
                        except Exception:
                            pass
                    _missing_secs = _turn_orig_secs - set(sections)
                    for _did, _dsec in _all_det_sec.items():
                        if _dsec in _missing_secs:
                            _junction_cands[_did] = _dsec
                except Exception:
                    pass

            log_to_file(
                f"[INIT_WARN] inter={self.id} "
                f"{len(invalid_dets)} INVALID detector IDs (report<0): {invalid_dets} — "
                f"buses on their sections will NOT be detected. "
                f"Valid detectors: {valid_dets} → sections: {sections}. "
                f"Nearby valid IDs (±2000): {_nearby}. "
                f"Junction-approach candidates: {_junction_cands}")
        return sections

    def _resolve_node_id(self):
        """
        Verify self.node_id is a valid Aimsun node ID by calling
        AKIInfNetGetNbTurnsInNode.  If it returns a negative error code,
        auto-discover the real node ID by querying idNodeTo on each known
        approach section.  Logs the result so the operator can update
        intersection_configs.py with the correct AimsunNodeID.
        """
        test = AKIInfNetGetNbTurnsInNode(self.node_id)
        if test >= 0:
            # Already valid — nothing to do
            return

        # node_id is wrong: find the real node from approach sections
        if LOG_NODE_ID:
            log_to_file(
                f"[NODE_ID] inter={self.id} node_id={self.node_id} invalid "
                f"(AKIInfNetGetNbTurnsInNode returned {test}) — auto-discovering ..."
            )
        candidates = {}   # node_id → count of sections pointing to it
        for sec_id in self.incoming_sections:
            try:
                si = AKIInfNetGetSectionANGInf(sec_id)
                if si.report >= 0 and si.idNodeTo > 0:
                    candidates[si.idNodeTo] = candidates.get(si.idNodeTo, 0) + 1
            except Exception:
                pass

        if candidates:
            best = max(candidates, key=candidates.get)
            # NODE_ID resolution is always logged — critical config hint
            log_to_file(
                f"[NODE_ID] inter={self.id} auto-resolved node_id "
                f"{self.node_id} → {best}  "
                f"(votes: {candidates})  "
                f"*** add AimsunNodeID: {best} to intersection_configs.py ***"
            )
            self.node_id = best
        else:
            # Always log failure — it means signal control is broken
            log_to_file(
                f"[NODE_ID] inter={self.id} could not auto-resolve node_id — "
                f"all approach sections returned report<0 (transit links). "
                f"Signal control and topology calls will be broken for this junction."
            )

    def _initialize_section_tracking(self):
        inter_state = self._get_inter_state()  # may be None if stats not yet registered
        detector_secs = self._derive_sections_from_detectors()

        main_secs = self._normalize_sections(self.config.get('MainSections', []))
        if not main_secs and inter_state is not None:
            main_secs = self._normalize_sections(inter_state.get('main_sections', []))
        for sec_id in detector_secs:
            if sec_id not in main_secs:
                main_secs.append(sec_id)

        side_secs = self._normalize_sections(self.config.get('SideSections', []))
        if not side_secs and inter_state is not None:
            side_secs = self._normalize_sections(inter_state.get('side_sections', []))

        # Topology fallback: when ALL configured detectors are invalid (or BusDet is empty),
        # detector_secs and main_secs are both empty → detect_bus and collect_delay find
        # no sections to scan.  Fall back to every turn-origin section at this junction so
        # the controller can still detect buses and measure delay without physical detectors.
        if not main_secs:
            try:
                _topo_seen = set()
                _topo_secs = []
                n_turns = AKIInfNetGetNbTurnsInNode(self.node_id)
                for _ti in range(n_turns):
                    try:
                        _tsec = AKIInfNetGetOriginSectionInTurn(self.node_id, _ti)
                        if _tsec > 0 and _tsec not in _topo_seen:
                            _topo_seen.add(_tsec)
                            _topo_secs.append(_tsec)
                    except Exception:
                        pass
                if _topo_secs:
                    main_secs = _topo_secs
                    if LOG_SECTION:
                        log_to_file(
                            f"[SECTION] inter={self.id} no valid detector sections — "
                            f"topology fallback: incoming_sections={main_secs}")
            except Exception:
                pass

        self.incoming_sections = list(main_secs)
        self.config['MainSections'] = list(main_secs)
        self.config['SideSections'] = list(side_secs)

        if inter_state is not None:
            inter_state['main_sections'] = list(main_secs)
            inter_state['side_sections'] = list(side_secs)

    def _validate_section_ids(self, sec_ids):
        """Return only section IDs that exist in this Aimsun model."""
        valid = []
        for sid in sec_ids:
            try:
                result = AKIVehStateGetNbVehiclesSection(sid, False)
                if result >= 0:
                    valid.append(sid)
            except Exception:
                pass
        return valid

    def _auto_discover_side_sections(self):
        """
        Discover side-street approach sections feeding into this junction node.
        Uses AKIInfNetGetNbTurnsInNode / AKIInfNetGetOriginSectionInTurn to enumerate
        all incoming sections at the junction, then excludes the main corridor sections
        (those that contain upstream detectors).
        """
        if hasattr(self, '_cached_side_sections'):
            return self._cached_side_sections

        main_sec_ids = set(self._derive_sections_from_detectors())
        # When all configured detectors are invalid, _derive_sections_from_detectors()
        # returns [].  Fall back to incoming_sections (which was itself populated from
        # junction topology by _initialize_section_tracking) so that main corridor
        # sections are correctly excluded from the side-section list.
        if not main_sec_ids and getattr(self, 'incoming_sections', None):
            main_sec_ids = set(self.incoming_sections)
            if LOG_SIDE_DISC:
                log_to_file(
                    f"[SIDE_DISC] inter={self.id} no detector sections — "
                    f"using incoming_sections as main_sec_ids={sorted(main_sec_ids)}")
        side_secs = []
        tried_method = "none"

        try:
            n_turns = AKIInfNetGetNbTurnsInNode(self.node_id)
            tried_method = "AKIInfNetGetNbTurnsInNode"
            if LOG_SIDE_DISC:
                log_to_file(
                    f"[SIDE_DISC] inter={self.id} node={self.node_id} "
                    f"junction has {n_turns} turns; "
                    f"main_secs={sorted(main_sec_ids)}")

            seen = set()
            for t_idx in range(n_turns):
                try:
                    sec_id = AKIInfNetGetOriginSectionInTurn(self.node_id, t_idx)
                except Exception:
                    continue
                if sec_id <= 0 or sec_id in seen:
                    continue
                seen.add(sec_id)
                if sec_id in main_sec_ids:
                    continue
                try:
                    if AKIVehStateGetNbVehiclesSection(sec_id, False) < 0:
                        continue
                except Exception:
                    continue
                side_secs.append(sec_id)

        except Exception as ex:
            if LOG_SIDE_DISC:
                log_to_file(
                    f"[SIDE_DISC] inter={self.id} turn-based scan error: {ex}")

        self._cached_side_sections = side_secs
        if LOG_SIDE_DISC:
            log_to_file(
                f"[SIDE_DISC] inter={self.id} method={tried_method} "
                f"found {len(side_secs)} side sections: {side_secs}")
        if side_secs:
            self.config['SideSections'] = side_secs
        return side_secs

    def _get_side_sections(self):
        # First try config / stats stored IDs, but validate them
        candidate = self._normalize_side_sections(self.config.get('SideSections', []))
        if not candidate:
            inter_state = self._get_inter_state()
            if inter_state is not None:
                candidate = self._normalize_side_sections(inter_state.get('side_sections', []))

        if candidate:
            valid = self._validate_section_ids(candidate)
            if valid:
                self.config['SideSections'] = valid
                return valid
            # All stored IDs were invalid — fall through to auto-discovery

        return self._auto_discover_side_sections()

    def _normalize_side_sections(self, side_secs):
        return self._normalize_sections(side_secs)

    def _ensure_side_section_arrays(self, side_secs, time):
        n = max(len(side_secs), 1)
        if len(self.SideUpFlowList) == n:
            return
        self.SideUpFlowList      = np.zeros(n)
        self.SideUpDenList       = np.zeros(n)
        self.SideShockwaveSpeed1 = np.zeros(n)
        self.SideShockwaveSpeed3 = np.zeros(n)

    def _compute_side_delay_penalty(self, extra_red):
        extra_red = max(safe_float(extra_red), 0.0)
        if extra_red <= 0.0 or not hasattr(self, 'SideUpFlowList') or len(self.SideUpFlowList) == 0:
            return 0.0, 0.0

        side_other_delay = 0.0
        side_total_veh = 0.0
        w2_side = abs(ShockwaveSpeed2(
            self.SaturationFlow, self.SaturationDensity, self.JamDensity))
        if w2_side <= 1e-6:
            return 0.0, 0.0

        jam_density = max(safe_float(self.JamDensity), 0.0)
        sat_density = max(safe_float(self.SaturationDensity), 0.0)

        for idx in range(len(self.SideUpFlowList)):
            q_s = max(safe_float(self.SideUpFlowList[idx]), 0.0)
            if q_s < 1.0:
                continue

            k_s = min(max(safe_float(self.SideUpDenList[idx]), 0.0), jam_density)
            w1_s = abs(safe_float(self.SideShockwaveSpeed1[idx]))
            w3_s = abs(safe_float(self.SideShockwaveSpeed3[idx]))
            denom_s = w2_side - w1_s
            if denom_s <= 1e-6 or w3_s <= 1e-6:
                continue

            side_max_q = w2_side * w1_s * extra_red / denom_s
            if side_max_q <= 0.0:
                continue

            jam_term = max(jam_density - k_s, 0.0) / 1000.0
            sat_term = max(sat_density - k_s, 0.0) / 1000.0
            side_diss = side_max_q / w3_s
            side_delay_veh_s = (
                side_max_q * extra_red * 0.5 * jam_term
                + side_diss * side_max_q * 0.5 * sat_term)
            side_other_delay += side_delay_veh_s
            side_total_veh += q_s * extra_red / 3600.0

        # compute raw vehicle counts for each side section for the log
        _side_secs_log = self._get_side_sections()
        _side_nveh = []
        for _ss in _side_secs_log:
            try:
                _side_nveh.append(int(AKIVehStateGetNbVehiclesSection(_ss, False)))
            except Exception:
                _side_nveh.append(-1)
        # estimated queue lengths (max queue from shockwave model, converted to vehicles)
        _veh_len = max(self.VehLength, 1.0) + 2.0  # vehicle + gap
        _qlen_veh = [round(float(self.SideUpFlowList[_k]) * extra_red / 3600.0, 1)
                     for _k in range(len(self.SideUpFlowList))]
        log_to_file(
            f"[SIDE_OBJ] inter={self.id} extra_red={extra_red:.2f} "
            f"side_secs={_side_secs_log} "
            f"n_veh={_side_nveh} "
            f"flow={[round(float(v),1) for v in self.SideUpFlowList]} "
            f"den={[round(float(v),2) for v in self.SideUpDenList]} "
            f"q_veh={_qlen_veh} "
            f"delay={side_other_delay:.2f} veh={side_total_veh:.2f}"
        )

        return side_other_delay, side_total_veh

    def _reset_harmony_work_arrays(self):
        for arr_name in (
            'BusDelay', 'OtherDelay', 'TotalVeh', 'HSMinQueueLength',
            'HSMaxQueueLength', 'HSMaxQueueLengthTime', 'HSQueueDissTime',
            'BusJoinQueueTime', 'BusStoplineTime', 'BusPhaseMinDuration'
        ):
            arr = getattr(self, arr_name, None)
            if arr is not None:
                arr.fill(0.0)

    @staticmethod
    def _safe_array_sum(arr):
        return float(np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0).sum())

    def _finalize_objective_stats(self, bus_delay_total, other_delay_total,
                                  total_veh, avg_passenger_delay):
        bus_delay_total = max(safe_float(bus_delay_total), 0.0)
        other_delay_total = max(safe_float(other_delay_total), 0.0)
        total_veh = max(safe_float(total_veh), 0.0)
        avg_passenger_delay = max(safe_float(avg_passenger_delay), 0.0)
        return bus_delay_total, other_delay_total, total_veh, avg_passenger_delay

    def _estimated_other_vehicle_occupancy(self):
        inter_state = self._get_inter_state() or {}
        car_passages = max(safe_float(inter_state.get('car_veh_passages', 0.0)), 0.0)
        truck_passages = max(safe_float(inter_state.get('truck_veh_passages', 0.0)), 0.0)
        car_occ = max(safe_float(self.CarOcc), 0.0)
        truck_occ = max(safe_float(getattr(self, 'TruckOcc', self.CarOcc)), 0.0)
        total_other_passages = car_passages + truck_passages
        if total_other_passages <= 1e-6:
            return max(car_occ, 1e-6)
        total_other_pax_equiv = car_passages * car_occ + truck_passages * truck_occ
        return max(total_other_pax_equiv / total_other_passages, 1e-6)

    
    def _sample_side_sections(self, time):
        """
        Virtual detector for side sections using instantaneous density.

        Scans live vehicle count on each side section, converts to density
        via section length (AKIInfNetGetSectionANGInf), then derives flow
        from the LWR triangular model. No aggregation periods needed.
        """
        side_secs = self._get_side_sections()
        if not side_secs:
            return

        self._ensure_side_section_arrays(side_secs, time)

        _nveh_log = []
        _len_log  = []
        for idx, sec_id in enumerate(side_secs):
            try:
                n_veh = max(int(AKIVehStateGetNbVehiclesSection(sec_id, False)), 0)
            except Exception:
                n_veh = 0

            try:
                _sec_inf  = AKIInfNetGetSectionANGInf(sec_id)
                sec_len_m = float(_sec_inf.length) if _sec_inf.report >= 0 else 50.0
                # Actual lane count from the struct (central + side lanes)
                n_lanes_sec = max(int(_sec_inf.nbCentralLanes) + int(_sec_inf.nbSideLanes), 1)
            except Exception:
                sec_len_m   = 50.0
                n_lanes_sec = 1
            sec_len_m = max(sec_len_m, 1.0)

            density_per_lane = n_veh / n_lanes_sec / max(sec_len_m / 1000.0, 0.001)
            density = min(density_per_lane, self.SaturationDensity * 0.9)
            flow    = density * self.SaturationFlow / max(self.SaturationDensity, 1.0)

            self.SideUpFlowList[idx]      = flow
            self.SideUpDenList[idx]       = density
            self.SideShockwaveSpeed1[idx] = ShockwaveSpeed1(flow, self.JamDensity, density)
            self.SideShockwaveSpeed3[idx] = ShockwaveSpeed3(
                self.SaturationFlow, flow, self.SaturationDensity, density)
            _nveh_log.append(n_veh)
            _len_log.append(round(sec_len_m, 0))

        # Throttle: only log every 60 s to avoid flooding the log file
        if not hasattr(self, '_side_scan_log_t'):
            self._side_scan_log_t = -999.0
        if time - self._side_scan_log_t >= 60.0:
            self._side_scan_log_t = time
            log_to_file(
                f"[SIDE_SCAN] inter={self.id} t={time:.0f} "
                f"secs={side_secs} "
                f"n_veh={_nveh_log} len_m={_len_log} "
                f"flow={[round(float(v),1) for v in self.SideUpFlowList]} "
                f"den={[round(float(v),2) for v in self.SideUpDenList]}"
            )
    
    def build_state(self):
        state = []
        for sec in self.incoming_sections:
            stat = AKIEstGetParcialStatisticsSection(
                sec, AKIGetCurrentSimulationTime(), 50)
            state.append(min(stat.count / 50.0, 1.0))

        bus_presence = 1.0 if np.any(self.BusPresence) else 0.0
        state.append(bus_presence)
        state.append(min(np.max(self.BusSpeed) / 20.0, 1.0) if bus_presence else 0.0)

        current_phase = ECIGetCurrentPhase(self.node_id)
        num_phases    = len(self.UpDetList)
        phase_one_hot = [0.0] * num_phases
        if 1 <= current_phase <= num_phases:
            phase_one_hot[current_phase - 1] = 1.0
        state.extend(phase_one_hot)

        start_time  = ECIGetStartingTimePhase(self.node_id)
        time_in_phase = AKIGetCurrentSimulationTime() - start_time
        state.append(min(time_in_phase / 60.0, 1.0))

        return np.array(state, dtype=np.float32)

    def collect_detector_data(self):
        """
        Update UpDetCountList from physical detectors where available.
        Also builds _det_sec_cache for the section-scan fallback used in
        update_queue_model when aggregated counts are still 0.
        """
        if not hasattr(self, '_prev_updet_counter'):
            self._prev_updet_counter = {}
        if not hasattr(self, '_det_sec_cache'):
            # Build once: {(i,j): (sec_id, sec_len_m)} for every valid detector
            self._det_sec_cache = {}
            for i in range(len(self.UpDetList)):
                for j, det_id in enumerate(self.UpDetList[i]):
                    props = AKIDetGetPropertiesDetectorById(det_id)
                    if props.report >= 0:
                        try:
                            sec_len = float(AKIInfNetGetSectionANGInf(props.IdSection).length)
                        except Exception:
                            sec_len = 50.0
                        self._det_sec_cache[(i, j)] = (props.IdSection, max(sec_len, 1.0))

        for i in range(len(self.UpDetList)):
            for j in range(len(self.UpDetList[i])):
                det_id = self.UpDetList[i][j]
                count = AKIDetGetCounterAggregatedbyId(det_id, 0)
                if count >= 0:
                    prev = self._prev_updet_counter.get(det_id)
                    if prev is None:
                        delta = max(count, 0)
                    elif count >= prev:
                        delta = count - prev
                    else:
                        delta = max(count, 0)
                    self._prev_updet_counter[det_id] = count
                    self.UpDetCountList[i][j] += delta

    def detect_bus_old(self, time):
        """
        Position-based continuous bus detection.

        Instead of polling whether a bus is physically over a detector at the
        exact 1-second tick, we scan ALL PT vehicles on call sections every
        step and compute their ETA to the stop line.  BusPresence[0][i] is
        set to 1 if any bus is within cycle_length seconds of arrival.
        BusSpeed[0][i] holds that bus's live speed in m/s.

        This eliminates missed detections caused by the 1-second sampling
        interval — a bus travelling at 50 km/h covers ~14 m per tick, so it
        can easily skip over a narrow detector zone.  Using live position data
        instead means we never miss it.
        """
        self.BusPresence[:] = 0
        self.BusSpeed[:]    = 0.0
        if not hasattr(self, '_bus_eta'):
            self._bus_eta = {}
        self._bus_eta.clear()
        self._detected_buses = []

        # Build det_sec_map: section_id -> [(det_index, det_distance_m, det_final_pos)]
        det_sec_map = {}
        for i, det_id in enumerate(self.BusDet):
            props = AKIDetGetPropertiesDetectorById(det_id)
            if props.report >= 0:
                sec = props.IdSection
                det_dist_group = self.config["DetDistance"][0]
                dist = det_dist_group[i] if i < len(det_dist_group) else 50.0
                det_sec_map.setdefault(sec, []).append((i, dist, props.FinalPosition))

        if not det_sec_map:
            # All physical detector IDs are invalid in this Aimsun model — fall back
            # to scanning incoming_sections directly with a default distance estimate.
            for sec_id in self.incoming_sections:
                try:
                    sec_len_m = float(AKIInfNetGetSectionANGInf(sec_id).length)
                except Exception:
                    sec_len_m = 50.0
                sec_len_m = max(sec_len_m, 1.0)
                det_sec_map[sec_id] = [(0, sec_len_m, sec_len_m)]

        if not det_sec_map:
            return

        lookahead = self.urtsp_cycle_length   # accept buses arriving within one cycle

        seen = set()

        def _record_detected_bus(det_idx, veh_id, speed_ms, remaining, eta):
            prev_eta = self._bus_eta.get(det_idx, (None, 1e9))[1]
            if self.BusPresence[0][det_idx] == 0 or eta < prev_eta:
                self.BusPresence[0][det_idx]    = 1
                self.BusSpeed[0][det_idx]       = speed_ms
                self.last_detected_bus_id       = veh_id
                self._bus_eta[det_idx]          = (veh_id, eta, remaining, speed_ms)
            self._detected_buses.append({
                'detector_index': det_idx,
                'vehicle_id': veh_id,
                'eta_s': eta,
                'remaining_m': remaining,
                'speed_mps': speed_ms,
            })

        # ── Primary: registered PT line vehicles ─────────────────────
        # Periodic diagnostic: every 5 min, log where ALL PT buses are so we
        # can confirm whether any ever reach the detector sections.
        _diag_pt_t = int(time) // 300
        _do_pt_diag = (_diag_pt_t != getattr(self, '_pt_diag_t', -1))
        if _do_pt_diag:
            self._pt_diag_t = _diag_pt_t
        _pt_on_det_sec = []   # (veh_id, section, eta)
        _pt_elsewhere  = []   # (veh_id, section)  — not on det_sec_map
        try:
            n_lines = AKIPTGetNumberLines()
            for li in range(n_lines):
                try:
                    line_id = AKIPTGetIdLine(li)
                    n_vehs  = AKIGetNbVehiclesFollowingPTLine(line_id)
                except Exception:
                    continue
                for vi in range(n_vehs):
                    try:
                        veh_id = AKIGetVehicleFollowingPTLine(line_id, vi)
                        if veh_id in seen:
                            continue
                        inf = AKIPTVehGetInf(veh_id)
                        if inf.report < 0:
                            continue
                        seen.add(veh_id)
                        if inf.idSection not in det_sec_map:
                            if _do_pt_diag:
                                _pt_elsewhere.append((veh_id, inf.idSection))
                            continue
                        speed_ms  = max(inf.CurrentSpeed / 3.6, 0.5)
                        for i, det_dist, det_fin in det_sec_map[inf.idSection]:
                            if inf.CurrentPos <= det_fin:
                                remaining = (det_fin - inf.CurrentPos) + det_dist
                            else:
                                remaining = max(0.0, det_dist - (inf.CurrentPos - det_fin))
                            eta = remaining / speed_ms
                            if _do_pt_diag:
                                _pt_on_det_sec.append((veh_id, inf.idSection, round(eta, 1)))
                            if eta <= lookahead:
                                _record_detected_bus(i, veh_id, speed_ms, remaining, eta)
                    except Exception:
                        continue
        except Exception:
            pass
        if _do_pt_diag:
            log_to_file(
                f"[PT_SCAN] inter={self.id} t={time:.0f} "
                f"det_sec_map_secs={list(det_sec_map.keys())} "
                f"on_det_secs={_pt_on_det_sec} "
                f"elsewhere(veh,sec)={_pt_elsewhere[:10]}"  # cap at 10
            )

        # ── Fallback: direct section scan for injected buses ─────────
        for sec, det_entries in det_sec_map.items():
            try:
                n = AKIVehStateGetNbVehiclesSection(sec, True)
                for vi in range(n):
                    inf = AKIVehStateGetVehicleInfSection(sec, vi)
                    if _do_pt_diag and inf.idVeh not in seen:
                        # Log every vehicle type found on detector sections
                        log_to_file(
                            f"[FALLBACK_SCAN] inter={self.id} t={time:.0f} "
                            f"sec={sec} veh={inf.idVeh} type={inf.type} "
                            f"bus_type_pos={self.bus_type_pos} "
                            f"pos={inf.CurrentPos:.1f} speed={inf.CurrentSpeed:.1f}"
                        )
                    if inf.idVeh in seen or inf.type != self.bus_type_pos:
                        continue
                    seen.add(inf.idVeh)
                    speed_ms  = max(inf.CurrentSpeed / 3.6, 0.5)
                    for i, det_dist, det_fin in det_entries:
                        if inf.CurrentPos <= det_fin:
                            remaining = (det_fin - inf.CurrentPos) + det_dist
                        else:
                            remaining = max(0.0, det_dist - (inf.CurrentPos - det_fin))
                        eta = remaining / speed_ms
                        if eta <= lookahead:
                            _record_detected_bus(i, inf.idVeh, speed_ms, remaining, eta)
            except Exception:
                continue
    
    
    def detect_bus_semi(self, time):
        """
        Production‑safe bus detection.

        ✔ Works with PT vehicles
        ✔ Works without detectors
        ✔ Works if bus type inference changes
        ✔ Cannot throw NameError
        """

        # Reset presence arrays
        self.BusPresence[:] = 0
        self.BusSpeed[:]    = 0.0
        self.last_detected_bus_id = -1

        # Always define this
        bus_found = False

        # ─────────────────────────────────────────────
        # 1️⃣ Primary: PT line vehicles
        # ─────────────────────────────────────────────
        try:
            n_lines = AKIPTGetNumberLines()
        except Exception:
            n_lines = 0

        for li in range(n_lines):
            try:
                line_id = AKIPTGetIdLine(li)
                n_vehs  = AKIGetNbVehiclesFollowingPTLine(line_id)
            except Exception:
                continue

            for vi in range(n_vehs):
                try:
                    veh_id = AKIGetVehicleFollowingPTLine(line_id, vi)
                    inf    = AKIPTVehGetInf(veh_id)

                    if inf.report < 0:
                        continue

                    if inf.idSection in self.incoming_sections:
                        self.BusPresence[0][0] = 1
                        self.BusSpeed[0][0]    = max(inf.CurrentSpeed / 3.6, 0.5)
                        self.last_detected_bus_id = veh_id
                        bus_found = True
                        break

                except Exception:
                    continue

            if bus_found:
                break

        # ─────────────────────────────────────────────
        # 2️⃣ Fallback: direct section scan
        # ─────────────────────────────────────────────
        if not bus_found:

            for sec in self.incoming_sections:
                try:
                    n = AKIVehStateGetNbVehiclesSection(sec, True)

                    for i in range(n):
                        inf = AKIVehStateGetVehicleInfSection(sec, i)

                        if inf.type == self.bus_type_pos:
                            self.BusPresence[0][0] = 1
                            self.BusSpeed[0][0]    = max(inf.CurrentSpeed / 3.6, 0.5)
                            self.last_detected_bus_id = inf.idVeh
                            bus_found = True
                            break

                    if bus_found:
                        break

                except Exception:
                    continue
    
    def _get_junction_xy(self):
        """
        Return the X,Y centroid of this junction.  Tries several coordinate
        field name variants used across Aimsun versions:
          Aimsun 22/26: xSection/ySection (centroid) or xSectionTo/ySectionTo
          Older builds:  xcoordTo/ycoordTo
        Falls back to turn-origin sections from the junction topology if
        incoming_sections are all transit links (report<0).
        Result is cached only on success — retries every call until resolved.
        """
        if getattr(self, '_junction_xy', None) is not None:
            return self._junction_xy   # already resolved — fast path

        # Field name variants to try, in priority order
        _x_fields = ('xSection', 'xSectionTo', 'xcoordTo', 'x')
        _y_fields = ('ySection', 'ySectionTo', 'ycoordTo', 'y')

        def _try_get_xy(si):
            """Extract (x, y) from a section ANGInf struct, trying all known field names."""
            for xf, yf in zip(_x_fields, _y_fields):
                xv = getattr(si, xf, None)
                yv = getattr(si, yf, None)
                if xv is not None and yv is not None:
                    try:
                        return float(xv), float(yv)
                    except (TypeError, ValueError):
                        pass
            return None, None

        xs, ys = [], []

        # First try incoming_sections (detector-based approach sections)
        for sec_id in self.incoming_sections:
            try:
                si = AKIInfNetGetSectionANGInf(sec_id)
                if si.report >= 0:
                    xv, yv = _try_get_xy(si)
                    if xv is not None:
                        xs.append(xv)
                        ys.append(yv)
            except Exception:
                pass

        # If that yielded nothing, try all turn-origin sections at the junction
        if not xs:
            try:
                n_turns = AKIInfNetGetNbTurnsInNode(self.node_id)
                for ti in range(max(n_turns, 0)):
                    try:
                        sec_id = AKIInfNetGetOriginSectionInTurn(self.node_id, ti)
                        if sec_id <= 0:
                            continue
                        si = AKIInfNetGetSectionANGInf(sec_id)
                        if si.report >= 0:
                            xv, yv = _try_get_xy(si)
                            if xv is not None:
                                xs.append(xv)
                                ys.append(yv)
                    except Exception:
                        pass
            except Exception:
                pass

        if xs:
            self._junction_xy = (sum(xs) / len(xs), sum(ys) / len(ys))
            if LOG_JUNC_XY:
                log_to_file(
                    f"[JUNC_XY] inter={self.id} resolved={self._junction_xy} "
                    f"from {len(xs)} sections"
                )
            return self._junction_xy

        # Still nothing — log once (always, regardless of flag) to help diagnose
        if not getattr(self, '_junc_xy_warn_logged', False):
            self._junc_xy_warn_logged = True
            try:
                si = AKIInfNetGetSectionANGInf(self.incoming_sections[0])
                fields = {k: getattr(si, k, '?') for k in dir(si) if not k.startswith('_')}
            except Exception:
                fields = {}
            log_to_file(
                f"[JUNC_XY_FAIL] inter={self.id} cannot resolve junction coordinates. "
                f"incoming_sections={self.incoming_sections} "
                f"section_ANGInf_fields={fields}"
            )
        return None

    def detect_bus(self, time):
        """
        Coordinate-distance bus detection — robust against transit links.

        PT buses in Aimsun travel through transit-link sections whose IDs return
        report<0 from AKIInfNetGetSectionANGInf (no topology info).  Section-based
        detection therefore never fires.  Instead we:

        1. Get the junction centroid X,Y from the 'to' coordinates of approach sections.
        2. For every active PT line vehicle, compute Euclidean distance to the junction.
        3. If distance <= detection_radius_m and type==bus_type_pos → detect.
        4. Fallback: direct section scan on incoming_sections for type==bus_type_pos.

        Periodic [PT_SCAN] log (every 5 min) shows all PT vehicles, their coordinates,
        and distances so we can verify the radius is appropriate.
        """

        self.BusPresence[:] = 0
        self.BusSpeed[:]    = 0.0
        self.last_detected_bus_id = -1

        # Detection radius: ~1 cycle length at 50 km/h ≈ 1875 m, capped at 500 m to
        # avoid false positives from buses at nearby parallel intersections.
        detection_radius_m = min(self.urtsp_cycle_length * 14.0, 500.0)

        # Junction centroid (cached after first call)
        junc_xy = self._get_junction_xy()

        # Periodic diagnostic throttle: every 5 minutes — only when LOG_PT_SCAN=True
        _diag_t = int(time) // 300
        _do_diag = LOG_PT_SCAN and (_diag_t != getattr(self, '_db_diag_t', -1))
        if _do_diag:
            self._db_diag_t = _diag_t
        _pt_info = []   # (veh_id, dist_m, speed) for diagnostic

        seen = set()
        jx = jy = None
        if junc_xy is not None:
            jx, jy = junc_xy

        _prev_presence = int(self.BusPresence[0][0]) if len(self.BusPresence[0]) else 0

        def _hit(veh_id, speed_kph):
            self.BusPresence[0][0]    = 1
            self.BusSpeed[0][0]       = max(speed_kph / 3.6, 0.5)
            self.last_detected_bus_id = veh_id
            # Record the bus passage in stats (works for transit-link buses that
            # never appear on regular approach sections)
            try:
                self.stats.record_pt_bus_detection(self.id, veh_id, time)
            except Exception:
                pass

        # ── Tier 1: PT line vehicle scan ────────────────────────────────────
        # Always runs regardless of whether junction coordinates are available.
        # When coordinates are known: accept buses within detection_radius_m.
        # When coordinates are unknown: accept buses on any incoming_section
        #   OR any bus whose section leads directly to this junction (idNodeTo).
        try:
            n_lines = AKIPTGetNumberLines()
        except Exception:
            n_lines = 0

        for li in range(n_lines):
            try:
                line_id = AKIPTGetIdLine(li)
                n_vehs  = AKIGetNbVehiclesFollowingPTLine(line_id)
            except Exception:
                continue
            for vi in range(n_vehs):
                try:
                    veh_id = AKIGetVehicleFollowingPTLine(line_id, vi)
                    if veh_id in seen:
                        continue
                    inf = AKIPTVehGetInf(veh_id)
                    if inf.report < 0:
                        continue
                    seen.add(veh_id)
                    if inf.type != self.bus_type_pos:
                        continue

                    if jx is not None:
                        # Primary path: coordinate distance
                        dx   = float(inf.xCurrentPos) - jx
                        dy   = float(inf.yCurrentPos) - jy
                        dist = (dx * dx + dy * dy) ** 0.5
                        if _do_diag:
                            _pt_info.append(
                                f"v={veh_id} d={dist:.0f}m "
                                f"spd={inf.CurrentSpeed:.0f}kph "
                                f"sec={inf.idSection}"
                            )
                        if dist <= detection_radius_m:
                            _hit(veh_id, inf.CurrentSpeed)
                    else:
                        # Fallback path — coordinates not yet available.
                        # Build/use a cached set of all sections that feed into
                        # this junction (turn-origin sections from topology).
                        if not hasattr(self, '_turn_origin_secs'):
                            _tos = set(self.incoming_sections)
                            try:
                                _nt = AKIInfNetGetNbTurnsInNode(self.node_id)
                                for _ti in range(max(_nt, 0)):
                                    try:
                                        _ts = AKIInfNetGetOriginSectionInTurn(self.node_id, _ti)
                                        if _ts > 0:
                                            _tos.add(_ts)
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                            self._turn_origin_secs = _tos

                        sec_id = inf.idSection
                        matched = sec_id in self._turn_origin_secs
                        if not matched:
                            try:
                                si = AKIInfNetGetSectionANGInf(sec_id)
                                if si.report >= 0 and si.idNodeTo == self.node_id:
                                    matched = True
                            except Exception:
                                pass
                        if _do_diag:
                            _pt_info.append(
                                f"v={veh_id} sec={sec_id} "
                                f"spd={inf.CurrentSpeed:.0f}kph "
                                f"matched={matched}"
                            )
                        if matched:
                            _hit(veh_id, inf.CurrentSpeed)
                except Exception:
                    continue

        # ── Tier 2: direct section scan on approach sections ────────────────
        if not any(self.BusPresence[0]):
            for sec_id in self.incoming_sections:
                try:
                    n = AKIVehStateGetNbVehiclesSection(sec_id, True)
                    for vi in range(n):
                        inf = AKIVehStateGetVehicleInfSection(sec_id, vi)
                        if inf.idVeh in seen:
                            continue
                        if inf.type == self.bus_type_pos:
                            _hit(inf.idVeh, inf.CurrentSpeed)
                            break
                except Exception:
                    continue
                if any(self.BusPresence[0]):
                    break

        # ── Periodic diagnostic ─────────────────────────────────────────────
        if _do_diag:
            log_to_file(
                f"[PT_SCAN] inter={self.id} t={time:.0f} "
                f"junc_xy={junc_xy} radius={detection_radius_m:.0f}m "
                f"n_lines={n_lines} bus_type_pos={self.bus_type_pos} "
                f"turn_origin_secs={sorted(getattr(self,'_turn_origin_secs',set()))} "
                f"BusPresence={self.BusPresence[0][0]} "
                f"all_type3_buses=[{'; '.join(_pt_info)}]"
            )
    def update_queue_model(self, time):
        det_sec_cache = getattr(self, '_det_sec_cache', {})
        for i in range(len(self.UpDetList)):
            for j in range(len(self.UpDetList[i])):
                red_duration = time - self.RedStartTimeList[i][j]
                if red_duration > 0:
                    self.RedDurationList[i][j] = red_duration

                    if self.UpDetCountList[i][j] > 0:
                        # Preferred: aggregated detector count → flow rate
                        flow = self.UpDetCountList[i][j] * 3600.0 / red_duration
                    else:
                        # Fallback: instantaneous density from live vehicle scan
                        sec_info = det_sec_cache.get((i, j))
                        if sec_info is not None:
                            sec_id, sec_len_m = sec_info
                            try:
                                n_veh = max(int(AKIVehStateGetNbVehiclesSection(sec_id, False)), 0)
                            except Exception:
                                n_veh = 0
                            n_lanes_sec = max(self.NumberOfLanes, 1)
                            density_per_lane = n_veh / n_lanes_sec / max(sec_len_m / 1000.0, 0.001)
                            # Cap at 90% SatDen so shockwave denominator stays non-zero
                            density_fallback = min(density_per_lane, self.SaturationDensity * 0.9)
                            flow = density_fallback * self.SaturationFlow / max(self.SaturationDensity, 1.0)
                        else:
                            flow = 0.0

                    self.UpFlowList[i][j] = flow
                    # LWR: k = q / v_f = q * k_sat / q_sat  (v_f = q_sat/k_sat)
                    self.UpDenList[i][j] = (
                        flow * self.SaturationDensity / self.SaturationFlow
                        if self.SaturationFlow > 0 else 0.0)

                    self.ShockwaveSpeed1List[i][j] = ShockwaveSpeed1(
                        self.UpFlowList[i][j], self.JamDensity, self.UpDenList[i][j])
                    self.ShockwaveSpeed2List[i][j] = ShockwaveSpeed2(
                        self.SaturationFlow, self.SaturationDensity, self.JamDensity)
                    self.ShockwaveSpeed3List[i][j] = ShockwaveSpeed3(
                        self.SaturationFlow, self.UpFlowList[i][j],
                        self.SaturationDensity, self.UpDenList[i][j])
                    self.ShockwaveSpeed4List[i][j] = ShockwaveSpeed4(
                        self.SaturationFlow, self.JamDensity, self.SaturationDensity)

                    w1 = self.ShockwaveSpeed1List[i][j]
                    w2 = self.ShockwaveSpeed2List[i][j]
                    w3 = self.ShockwaveSpeed3List[i][j]
                    w4 = self.ShockwaveSpeed4List[i][j]
                    denom = abs(w2) - abs(w1)
                    if abs(denom) < 1e-6:
                        continue

                    self.MaxQueueLength[i][j]     = abs(w2 * w1 * red_duration / denom)
                    self.MaxQueueLengthTime[i][j] = (
                        self.RedStartTimeList[i][j] + abs(w2) * red_duration / denom)

                    if abs(w3) > 1e-6:
                        self.QueueDissTime[i][j] = (
                            self.MaxQueueLengthTime[i][j]
                            + self.MaxQueueLength[i][j] / abs(w3))
                    else:
                        self.QueueDissTime[i][j] = self.MaxQueueLengthTime[i][j]

                    # Residual queue for next cycle
                    nrs = self.NextRedStartTime[i][j]
                    if self.QueueDissTime[i][j] > nrs and abs(w3) > 1e-6 and abs(w4) > 1e-6:
                        self.MinQueueLength[i][j] = (
                            (self.MaxQueueLength[i][j] / abs(w3)
                             + self.MaxQueueLengthTime[i][j] - nrs)
                            / (1.0 / abs(w3) + 1.0 / abs(w4)))
                        self.MinQueueLengthTime[i][j] = (
                            nrs + self.MinQueueLength[i][j] / abs(w4))
                    else:
                        self.MinQueueLength[i][j]     = 0.0
                        self.MinQueueLengthTime[i][j] = 0.0

        # Refresh virtual side-section detector data for use in GE/BP objectives.
        self._sample_side_sections(time)

    def highlight_bus(self, veh_id):
        strategy_name = {1: "GREEN EXTENSION", 2: "PHASE INSERTION"}.get(self.TSPStrategy, "UNKNOWN")
        if LOG_TSP_EVT: AKIPrintString(f"[TSP EVENT] ▶ START | {strategy_name} | veh={veh_id} | inter={self.id}")

    def reset_bus_color(self, veh_id):
        if LOG_TSP_EVT: AKIPrintString(f"[TSP EVENT] ■ END   | veh={veh_id} | inter={self.id}")

    def enforce_starvation_protection(self, time, timeSta, acycle):
        MAX_RED       = 1200000
        current_phase = ECIGetCurrentPhase(self.node_id)
        for phase_id in self.phase_list:
            if phase_id == current_phase or phase_id not in self.PhaseIndex:
                continue
            phase_index = self.PhaseIndex[phase_id]
            red_time    = time - self.RedStartTimeList[phase_index][0]
            if red_time > MAX_RED:
                _vprint(f"STARVATION: phase {phase_id} red for {red_time:.0f}s")
                ECIChangeDirectPhase(self.node_id, phase_id, timeSta, time, acycle, 0)
                return

    def apply_action(self, action, timeSta, time, acycle):
        current_phase = ECIGetCurrentPhase(self.node_id)
        start         = ECIGetStartingTimePhase(self.node_id)
        time_in_phase = time - start
        MIN_GREEN     = 5
        MAX_GREEN     = 60
        if time_in_phase < MIN_GREEN:
            return
        if time_in_phase >= MAX_GREEN:
            next_phase = (current_phase % len(self.phase_list)) + 1
            _vprint(f"MAX_GREEN override → phase {next_phase}")
            ECIChangeDirectPhase(self.node_id, next_phase, timeSta, time, acycle, 0)
            return
        if action < len(self.phase_list):
            target_phase = self.phase_list[action]
            if target_phase != current_phase:
                ECIChangeDirectPhase(self.node_id, target_phase, timeSta, time, acycle, 0)

    def run_rl(self, time, timeSta, acycle):
        state  = self.build_state()
        action = self.rl_agent.select_action(state)
        self.apply_action(action, timeSta, time, acycle)
        reward = -self.step_delay
        self.prev_total_delay = self.step_delay
        next_state = self.build_state()
        if self.TRAIN_MODE:
            self.rl_agent.update(reward, next_state, done=False)

    def run_normal(self, time, timeSta, acycle):
        """Passive baseline — data collection only, no signal changes."""
        busTypePos = self.bus_type_pos

        # Primary: physical detector crossing this cycle
        busCallActive = any(
            AKIDetGetCounterCyclebyId(det, busTypePos) > 0
            for det in self.BusDet)
        # Fallback: position-based scan (detect_bus already ran this step)
        if not busCallActive:
            busCallActive = any(
                self.BusPresence[0][i] > 0
                for i in range(len(self.BusDet)))

        # Periodic diagnostic — log det counters + BusPresence every 5 minutes
        _diag_t = int(time) // 300
        if _diag_t != getattr(self, '_run_normal_diag_t', -1):
            self._run_normal_diag_t = _diag_t
            counters = [AKIDetGetCounterCyclebyId(d, busTypePos) for d in self.BusDet]
            presence = self.BusPresence[0].tolist()
            log_to_file(
                f"[NORMAL DIAG] t={time:.0f}s inter={self.id} "
                f"det_counters={counters} BusPresence={presence} "
                f"busCallActive={busCallActive}")

    def restore_phase_if_needed(self, time, timeSta, acycle):
        current_phase = ECIGetCurrentPhase(self.node_id)

        # ── Flag 1: GREEN EXTENSION ─────────────────────────────────────────
        # Primary end: Aimsun naturally advanced past BusPhase (phase changed).
        # Fallback:    TimeToTerminateBusPhase elapsed (safety timer).
        if self.flag == 1:
            phase_ended = (current_phase != self.BusPhase)
            timed_out   = (time > self.TimeToTerminateBusPhase)
            if phase_ended or timed_out:
                ECIChangeTimingPhase(
                    self.id, self.BusPhase, self.BusPhaseDuration, timeSta)
                if timed_out and not phase_ended:
                    ECIEnableEventsActivatingPhase(
                        self.id, self.BusPhase + 1, 0.0, time)
                self.flag        = 0
                self.TSPStrategy = 0
                self.reset_bus_color(self.last_detected_bus_id)
                if LOG_HARMONY:
                    _vprint(
                        f"[HARMONY] GE ended | t={time:.1f}s "
                        f"reason={'phase_change' if phase_ended else 'timeout'} "
                        f"inter={self.id}")

        # ── Flag 2: PHASE INSERTION ─────────────────────────────────────────
        # Primary end: BusPhase naturally ended (Aimsun advanced past it).
        # Fallback:    BusPhaseEndTime elapsed.
        # In both cases: restore interrupted phase explicitly — Aimsun does
        # NOT return to the interrupted phase automatically after insertion.
        if self.flag == 2:
            phase_ended = (current_phase != self.BusPhase)
            timed_out   = (time > self.BusPhaseEndTime)
            if phase_ended or timed_out:
                ECIChangeTimingPhase(
                    self.id, self.BusPhase, self.BusPhaseDuration, timeSta)
                if (self.previous_phase
                        and self.previous_phase > 0
                        and current_phase != self.previous_phase):
                    ECIChangeDirectPhase(
                        self.id, self.previous_phase,
                        timeSta, time, acycle, 0)
                self.flag        = 0
                self.TSPStrategy = 0
                if LOG_HARMONY:
                    _vprint(
                        f"[HARMONY] Insertion ended | t={time:.1f}s "
                        f"reason={'phase_change' if phase_ended else 'timeout'} "
                        f"restored_phase={self.previous_phase} inter={self.id}")

    def collect_delay(self, time, timeSta=None):
        self.step_delay = 0.0
        weighted_delay  = 0.0
        # Use timeSta (stats interval start) for partial stats if available;
        # AKIEstGetParcialStatisticsSection expects the interval start time.
        stat_time = timeSta if timeSta is not None else time

        inter_state = self.stats._inter.get(self.id, {})
        main_secs   = set(inter_state.get('main_sections', []))
        side_secs   = set(inter_state.get('side_sections', []))

        # --- resolve side sections -------------------------------------------
        # Priority 1: already stored in inter_state (populated by Stats at init
        #             or by a previous collect_delay call below).
        # Priority 2: try the Stats topology method (PyANGKernel GKSystem).
        # Priority 3: fall back to the controller's own AAPI-based discovery
        #             (_cached_side_sections built by _auto_discover_side_sections)
        #             which uses AKIInfNetGetNbTurnsInNode / GetOriginSectionInTurn
        #             and is guaranteed to work in this Aimsun 26 environment.
        
        # --- resolve side sections (FIXED PRIORITY CHAIN) ---
#    1️⃣ Always prefer controller AAPI discovery (correct section IDs)
        try:
            controller_side = set(self._get_side_sections())
        except Exception:
            controller_side = set()

        if controller_side:
            side_secs = controller_side
            inter_state['side_sections'] = list(sorted(side_secs))
            inter_state['side_sections_resolved'] = True

        # 2️⃣ Only fallback to stats topology if controller found nothing
        elif main_secs:
            try:
                resolved_side = self.stats._side_sections_from_topology(
                    self.id, list(main_secs))
                side_secs = set(int(s) for s in resolved_side
                                if s and int(s) not in main_secs)
                if side_secs:
                    inter_state['side_sections'] = list(sorted(side_secs))
                    inter_state['side_sections_resolved'] = True
            except Exception:
                side_secs = set()
        
        
        # --- resolve main sections -------------------------------------------
        # When inter_state has no main_sections (detector IDs were invalid at
        # init time), fall back to the controller's incoming_sections set, which
        # is derived live from the BusDet detector properties.
        if not main_secs:
            main_secs = set(self.incoming_sections)

        side_secs -= main_secs

        all_delay_secs = set(self.incoming_sections) | main_secs | side_secs

        if not hasattr(self, '_cum_sec_prev'):
            self._cum_sec_prev = {}
        # Accumulate all vehicle IDs seen on side sections this call,
        # used for lazy pruning of the _side_stop_prev dict.
        _all_side_veh_ids = set()

        for sec in all_delay_secs:
            # A section is "main" if it is a known main corridor section.
            # Everything else (auto-discovered cross streets) is "side".
            # When both sets are empty this falls back to True (all main).
            is_main = (sec in main_secs) if (main_secs or side_secs) else True

            car_stat = AKIEstGetParcialStatisticsSection(
                sec, stat_time, self.car_type_pos)
            truck_stat = AKIEstGetParcialStatisticsSection(
                sec, stat_time, getattr(self.stats, '_truck_pos', -1))

            if car_stat.report == 0:
                # Partial stats available — use directly.
                car_d    = car_stat.DTa * car_stat.count * self.CarOcc
                bus_stat = AKIEstGetParcialStatisticsSection(
                    sec, stat_time, self.bus_type_pos)
                bus_d    = bus_stat.DTa * bus_stat.count * self.BusOcc
                truck_d  = (
                    truck_stat.DTa * truck_stat.count * self.TruckOcc
                    if getattr(truck_stat, 'report', -1) == 0 and getattr(self.stats, '_truck_pos', -1) > 0
                    else 0.0
                )
                bus_cnt  = bus_stat.count
                car_cnt  = car_stat.count
                truck_cnt = (
                    truck_stat.count
                    if getattr(truck_stat, 'report', -1) == 0 and getattr(self.stats, '_truck_pos', -1) > 0
                    else 0
                )

            elif not is_main:
                # ── Side section: no stats collection configured in Aimsun ──
                # Use AKIVehStateGetVehicleInfSection to scan every vehicle
                # currently on the section and read InfVeh.CurrentStopTime
                # (accumulated stop time since the vehicle last started moving).
                # Delta from previous step = incremental stopped-time this call.
                # This works without ANY stats collection point on the section.
                if not hasattr(self, '_side_stop_prev'):
                    self._side_stop_prev = {}   # {veh_id: last_stop_time_s}
                if not hasattr(self, '_side_sec_free_flow'):
                    self._side_sec_free_flow = {}  # {sec_id: ff_speed_ms}

                # Cache free-flow speed for this section once
                if sec not in self._side_sec_free_flow:
                    try:
                        _sinf = AKIInfNetGetSectionANGInf(sec)
                        _ff = float(_sinf.speedLimit) / 3.6 if _sinf.report >= 0 else 13.9
                    except Exception:
                        _ff = 13.9
                    self._side_sec_free_flow[sec] = max(_ff, 1.0)

                _n_side = max(int(AKIVehStateGetNbVehiclesSection(sec, False)), 0)
                car_d = bus_d = truck_d = 0.0
                car_cnt = bus_cnt = truck_cnt = 0

                for _vi in range(_n_side):
                    try:
                        _veh = AKIVehStateGetVehicleInfSection(sec, _vi)
                        if _veh.report < 0:
                            continue
                        _vid = int(_veh.idVeh)
                        _stop_now = max(0.0, float(_veh.CurrentStopTime))
                        _prev_stop = self._side_stop_prev.get(_vid, _stop_now)
                        # Delta stop time this simulation step (non-negative)
                        _delta_s = max(0.0, _stop_now - _prev_stop)
                        self._side_stop_prev[_vid] = _stop_now
                        _all_side_veh_ids.add(_vid)

                        if _delta_s <= 0.0:
                            continue

                        _vtype = int(_veh.type)
                        if _vtype == self.bus_type_pos:
                            bus_d   += _delta_s * self.BusOcc
                            bus_cnt += 1
                        else:
                            car_d   += _delta_s * self.CarOcc
                            car_cnt += 1
                    except Exception:
                        pass

            else:
                # ── Main section fallback: partial stats unavailable (warmup) ──
                # Use cumulative delta from AKIEstGetGlobalStatisticsSection.
                try:
                    car_cum = AKIEstGetCurrentStatisticsSection(
                        sec, self.car_type_pos)
                    bus_cum = AKIEstGetCurrentStatisticsSection(
                        sec, self.bus_type_pos)
                    truck_cum = AKIEstGetCurrentStatisticsSection(
                        sec, getattr(self.stats, '_truck_pos', -1))

                    if car_cum.report != 0:
                        car_cum = AKIEstGetGlobalStatisticsSection(
                            sec, self.car_type_pos)
                    if bus_cum.report != 0:
                        bus_cum = AKIEstGetGlobalStatisticsSection(
                            sec, self.bus_type_pos)
                    if getattr(self.stats, '_truck_pos', -1) > 0 and truck_cum.report != 0:
                        truck_cum = AKIEstGetGlobalStatisticsSection(
                            sec, getattr(self.stats, '_truck_pos', -1))

                    prev_car   = self._cum_sec_prev.get((sec, 'car'),   (0.0, 0))
                    prev_bus   = self._cum_sec_prev.get((sec, 'bus'),   (0.0, 0))
                    prev_truck = self._cum_sec_prev.get((sec, 'truck'), (0.0, 0))

                    car_total_now   = (car_cum.DTa   * car_cum.count)   if car_cum.report   == 0 else 0.0
                    bus_total_now   = (bus_cum.DTa   * bus_cum.count)   if bus_cum.report   == 0 else 0.0
                    truck_total_now = (
                        truck_cum.DTa * truck_cum.count
                        if getattr(truck_cum, 'report', -1) == 0 and getattr(self.stats, '_truck_pos', -1) > 0
                        else 0.0)

                    car_cnt   = max(0, (car_cum.count   if car_cum.report   == 0 else 0) - prev_car[1])
                    bus_cnt   = max(0, (bus_cum.count   if bus_cum.report   == 0 else 0) - prev_bus[1])
                    truck_cnt = max(0, (
                        (truck_cum.count if getattr(truck_cum, 'report', -1) == 0 else 0) - prev_truck[1]))

                    car_d   = max(0.0, car_total_now   - prev_car[0])   * self.CarOcc
                    bus_d   = max(0.0, bus_total_now   - prev_bus[0])   * self.BusOcc
                    truck_d = max(0.0, truck_total_now - prev_truck[0]) * self.TruckOcc

                    self._cum_sec_prev[(sec, 'car')]   = (
                        car_total_now,   car_cum.count   if car_cum.report   == 0 else prev_car[1])
                    self._cum_sec_prev[(sec, 'bus')]   = (
                        bus_total_now,   bus_cum.count   if bus_cum.report   == 0 else prev_bus[1])
                    self._cum_sec_prev[(sec, 'truck')] = (
                        truck_total_now,
                        truck_cum.count if getattr(truck_cum, 'report', -1) == 0 else prev_truck[1])

                except Exception:
                    car_d = bus_d = truck_d = 0.0
                    car_cnt = bus_cnt = truck_cnt = 0

            sec_delay = car_d + bus_d + truck_d
            weighted_delay += sec_delay

            # For side sections the `bus_cnt` / `car_cnt` values are per-step
            # stopped-vehicle counts, NOT passage counts. Adding them to the
            # stats passages denominator would inflate PaxEquivPassages by
            # N_stopped_vehicles × N_steps (×1000 s of overcounting).
            # Side-section delay is captured in `delay_side` via `is_main=False`;
            # the passage/passenger denominators only need main-section counts.
            _pass_bus_cnt   = bus_cnt   if is_main else 0
            _pass_car_cnt   = car_cnt   if is_main else 0
            _pass_truck_cnt = truck_cnt if is_main else 0

            self.stats.add_section_delay_split(
                intersection_id   = self.id,
                weighted_delay    = sec_delay,
                bus_vehicle_count = _pass_bus_cnt,
                car_vehicle_count = _pass_car_cnt,
                truck_vehicle_count = _pass_truck_cnt,
                is_main           = is_main,
                bus_delay         = bus_d,
                car_delay         = car_d,
                truck_delay       = truck_d,
            )

            if not is_main and sec in side_secs:
                if not hasattr(self, '_side_red_counts'):
                    self._side_red_counts = {}
                if not hasattr(self, '_side_live_counts'):
                    self._side_live_counts = {}
                live_side_count = 0
                try:
                    live_side_count = max(int(AKIVehStateGetNbVehiclesSection(sec, True)), 0)
                except Exception:
                    live_side_count = 0
                self._side_live_counts[sec] = live_side_count
                self._side_red_counts[sec] = (
                    safe_float(self._side_red_counts.get(sec, 0.0))
                    + max(live_side_count, int(max(0, bus_cnt + car_cnt + truck_cnt)))
                )

        self.step_delay += weighted_delay

        # Prune _side_stop_prev: remove vehicle IDs not seen this call.
        # Only runs every ~60 s to avoid per-step overhead.
        if hasattr(self, '_side_stop_prev') and _all_side_veh_ids:
            if not hasattr(self, '_side_prune_t'):
                self._side_prune_t = time
            if time - self._side_prune_t > 60.0:
                self._side_stop_prev = {
                    k: v for k, v in self._side_stop_prev.items()
                    if k in _all_side_veh_ids}
                self._side_prune_t = time

        # Periodic delay debug log (every 60 s) — LOG_DELAY flag
        if LOG_DELAY:
            if not hasattr(self, '_delay_log_t'):
                self._delay_log_t = time
            if time - self._delay_log_t >= 60.0:
                _inter_d = self.stats._inter.get(self.id, {})
                log_to_file(
                    f"[DELAY] inter={self.id} t={time:.0f} "
                    f"main_secs={sorted(main_secs)} "
                    f"side_secs={sorted(side_secs)} "
                    f"step_weighted={weighted_delay:.4f} "
                    f"cum_side_delay_s={_inter_d.get('delay_side', 0.0):.2f} "
                    f"cum_main_delay_s={_inter_d.get('delay_main', 0.0):.2f} "
                    f"side_veh_tracked={len(getattr(self, '_side_stop_prev', {}))}"
                )
                self._delay_log_t = time

    # =========================================================================
    # MAIN UPDATE  — dispatches to correct control mode
    # =========================================================================

    def update(self, time, timeSta, acycle):
        if TSP_ACTIVE_INTERSECTIONS is not None and self.id not in TSP_ACTIVE_INTERSECTIONS:
            return

        try:
            # ── GROUP_BASED family: fully delegated to GroupBasedController ──
            # All three variants (basic / URTSP / harmony) use the same state
            # machine; the tsp_mode parameter on GroupBasedController selects the
            # bus-detection and extension-optimisation strategy.
            if CONTROL_MODE in ("GROUP_BASED", "GROUP_BASED_URTSP", "GROUP_BASED_HARMONY"):
                if self.gb is not None:
                    self.gb.step(time, timeSta)
                else:
                    if LOG_GB:
                        _vprint(
                            f"[GB] WARNING inter={self.id} t={time:.0f} "
                            f"gb=None — GroupBasedController not initialised"
                        )
                return

            # ── All other modes: phase-based tracking + TSP logic ─────────────
            current_phase = ECIGetCurrentPhase(self.node_id)
            if current_phase < 0:
                return

            # Phase-transition bookkeeping
            if current_phase != getattr(self, 'previous_phase', -1):
                prev_phase = getattr(self, 'previous_phase', -1)
                if prev_phase in self.PhaseIndex:
                    prev_idx = self.PhaseIndex[prev_phase]
                    if prev_idx < len(self.RedStartTimeList):
                        self.RedStartTimeList[prev_idx][:] = time
                        self.UpDetCountList[prev_idx][:] = 0.0
                        self.UpAveOccList[prev_idx][:]   = 0.0
                if current_phase in self.PhaseIndex:
                    idx = self.PhaseIndex[current_phase]
                    if idx < len(self.GreenStartTimeList):
                        self.GreenStartTimeList[idx][:] = time
                        dur = GetPhaseDuration(self.node_id, current_phase, timeSta)
                        if idx < len(self.NextRedStartTime):
                            self.NextRedStartTime[idx][:] = time + dur
                self.previous_phase = current_phase

            self.collect_detector_data()
            self.update_queue_model(time)
            self.detect_bus(time)

            # Periodic heartbeat (every 60 s) — controlled by LOG_HEARTBEAT flag
            if LOG_HEARTBEAT:
                _t60 = int(time) // 60
                if _t60 != getattr(self, '_last_log_min', -1):
                    self._last_log_min = _t60
                    log_to_file(
                        f"[HEARTBEAT] t={time:.0f}s inter={self.id} "
                        f"mode={CONTROL_MODE} phase={current_phase} "
                        f"flag={self.flag} TSPStrategy={self.TSPStrategy} "
                        f"TSPActiveTime={self.TSPActiveTime:.0f} "
                        f"BusPresence={self.BusPresence[0].tolist()} "
                        f"BusSpeed={[round(v,2) for v in self.BusSpeed[0].tolist()]} "
                        f"MaxQ={[round(v,1) for v in self.MaxQueueLength[0].tolist()]} "
                        f"UpFlow={[round(v,1) for v in self.UpFlowList[0].tolist()]}"
                    )

            if CONTROL_MODE == "NORMAL":
                self.run_normal(time, timeSta, acycle)

            elif CONTROL_MODE == "HARMONY":
                self.restore_phase_if_needed(time, timeSta, acycle)
                if time - self.last_tsp_action_time < self.tsp_cooldown_seconds:
                    if LOG_TSP_EVT and int(time) % 15 == 0:
                        _vprint(
                            f"[TSP COOLDOWN] inter={self.id} t={time:.1f} "
                            f"skipping HARMONY (remaining ~"
                            f"{self.tsp_cooldown_seconds-(time-self.last_tsp_action_time):.0f}s)")
                else:
                    _was_idle  = (self.TSPStrategy == 0)
                    tsp_active = self.check_bus_priority(time, timeSta, acycle)
                    if tsp_active and _was_idle:
                        self.last_tsp_action_time = time
                        if LOG_TSP_EVT:
                            _vprint(
                                f"[TSP] inter={self.id} HARMONY action t={time:.1f} "
                                f"next after {time+self.tsp_cooldown_seconds:.1f}s")

            elif CONTROL_MODE == "RL":
                tsp_active = self.check_bus_priority(time, timeSta, acycle)
                if not tsp_active:
                    self.run_rl(time, timeSta, acycle)
                self.restore_phase_if_needed(time, timeSta, acycle)

            elif CONTROL_MODE == "URTSP":
                if time - self.last_tsp_action_time < self.tsp_cooldown_seconds:
                    if LOG_TSP_EVT and int(time) % 10 == 0:
                        _vprint(
                            f"[TSP COOLDOWN] inter={self.id} t={time:.1f} "
                            f"skipping URTSP (remaining ~"
                            f"{self.tsp_cooldown_seconds-(time-self.last_tsp_action_time):.0f}s)")
                else:
                    self.run_urtsp(time, timeSta, acycle)

        except Exception as e:
            stop_simulation(f"update crashed inter={self.id} t={time:.1f}: {e}")
            import traceback
            log_to_file(traceback.format_exc())
            return 0


    # ── HARMONY check_bus_priority kept intact below ──────────────────
    def check_bus_priority(self, time, timeSta, acycle):
        if time < self.TSPActiveTime:
            return False
        if self.flag != 0:
            return True
        # One TSP grant per cycle — prevents re-firing on the same bus
        if getattr(self, '_tsp_cycle_grant_until', -1.0) > time:
            return False

        # Read current phase ONCE — consistent across all detectors this step
        current_phase = ECIGetCurrentPhase(self.node_id)

        # Guard: negative phase means junction not under external control yet
        if current_phase < 0:
            # Log once per minute so we know this is happening
            _t60 = int(time) // 60
            if _t60 != getattr(self, '_last_phase_warn', -1):
                self._last_phase_warn = _t60
                log_to_file(
                    f"[WARN] inter={self.id} t={time:.0f}s ECIGetCurrentPhase={current_phase} "
                    f"— junction NOT under external control. "
                    f"Set junction signal control to 'External' in Aimsun model GUI "
                    f"(Properties → Signal Control → External API).")
            return False

        # ── TSP state snapshot (once per check, not per detector) ─────────────
        _diag_every = getattr(self, '_tsp_diag_t', -1)
        if int(time) != _diag_every:
            self._tsp_diag_t = int(time)
            _main_secs = self.incoming_sections
            _sec_info = []
            for _s in _main_secs:
                try:
                    _nv = AKIVehStateGetNbVehiclesSection(_s, False)
                    _sl = float(AKIInfNetGetSectionANGInf(_s).length)
                    _sec_info.append(f"sec={_s} n={_nv} len={_sl:.0f}m")
                except Exception as _e:
                    _sec_info.append(f"sec={_s} err={_e}")
            log_to_file(
                f"[TSP_DIAG] inter={self.id} t={time:.1f} "
                f"phase={ECIGetCurrentPhase(self.node_id)} flag={self.flag} "
                f"TSPStrat={self.TSPStrategy} "
                f"BusPresence={self.BusPresence[0].tolist()} "
                f"BusSpeed={[round(v,2) for v in self.BusSpeed[0].tolist()]} "
                f"UpFlow={[round(float(v),1) for v in self.UpFlowList[0].tolist()]} "
                f"UpDen={[round(float(v),2) for v in self.UpDenList[0].tolist()]} "
                f"MaxQ={[round(float(v),1) for v in self.MaxQueueLength[0].tolist()]} "
                f"RedDur={[round(float(v),1) for v in self.RedDurationList[0].tolist()]} "
                f"sections={_sec_info}"
            )

        for i in range(len(self.BusDet)):
            bus_speed = self.BusSpeed[0][i]
            if bus_speed <= 0:
                continue

            if current_phase == self.BusPhase:
                red_start        = self.RedStartTimeList[0][i]
                _ps = ECIGetStartingTimePhase(self.node_id)
                _pd = GetPhaseDuration(self.node_id, current_phase, timeSta)
                next_red_start = _ps + _pd
                # Use live remaining distance from ETA tracker if available
                eta_info   = getattr(self, '_bus_eta', {}).get(i)
                live_dist  = eta_info[2] if eta_info else self.config["DetDistance"][0][i]

                bus_stopline_time = time + live_dist / bus_speed

                if bus_stopline_time > next_red_start and self.TSPStrategy == 0:
                    GE_lb = bus_stopline_time - next_red_start
                    opt_GE = harmony_search(
                        self.GE_Objective_Function, GE_lb, self.GE_upper_bound,
                        self.max_iterations, self.harmony_memory_size,
                        self.hmcr, self.par, 5, time)
                    if math.isnan(opt_GE) or opt_GE < 0:
                        opt_GE = 10.0
                    remain = GetPhaseDuration(self.node_id, current_phase, timeSta) \
                             - (time - ECIGetStartingTimePhase(self.node_id))
                    ECIChangeTimingPhase(self.node_id, current_phase,
                                         self.BusPhaseDuration + float(opt_GE), timeSta)
                    self.TimeToTerminateBusPhase = time + remain + opt_GE
                    self.TSPStrategy = 1
                    self.flag        = 1
                    self.TSPActiveTime = time + float(opt_GE) + 30
                    self._tsp_cycle_grant_until = time + self.config.get('CycleTime', 135)
                    if LOG_HARMONY:
                        _vprint(
                            f"[HARMONY] GE | t={time:.1f}s inter={self.id} "
                            f"bus_eta={bus_stopline_time - time:.1f}s "
                            f"next_red={next_red_start - time:.1f}s "
                            f"opt_GE={opt_GE:.1f}s")
                    self.highlight_bus(self.last_detected_bus_id)
                    self.stats.record_tsp_event(self.id, 'detection')
                    self.stats.record_tsp_event(self.id, 'extension')
                    return True

            else:
                # ── Phase insertion need assessment ────────────────────────
                # Theory: only insert if bus will MISS the next natural BusPhase
                # green. Compute time from now to the natural next BusPhase start.
                bus_approaching = (
                    self.BusPresence[0][i] == 1
                    and bus_speed > 0
                )
                if not (current_phase in self.PhaseIndex
                        and bus_approaching
                        and self.TSPStrategy == 0):
                    continue

                # Time remaining in current phase
                _ps_now        = ECIGetStartingTimePhase(self.node_id)
                _elapsed       = max(0.0, time - _ps_now)
                _rem_current   = max(0.0,
                    GetPhaseDuration(self.node_id, current_phase, timeSta) - _elapsed)

                # Walk phase sequence from current to BusPhase
                _time_to_bp = _rem_current
                try:
                    _ci  = self.phase_list.index(current_phase)
                    _bi  = self.phase_list.index(self.BusPhase)
                    _n   = len(self.phase_list)
                    _steps = (_bi - _ci) % _n  # phases between current+1 and BusPhase
                    for _k in range(1, _steps):
                        _ph = self.phase_list[(_ci + _k) % _n]
                        _time_to_bp += GetPhaseDuration(self.node_id, _ph, timeSta)
                except (ValueError, Exception):
                    _time_to_bp = float(self.config.get('CycleTime', 135))

                # Bus ETA to stopline (seconds from now)
                _eta_info  = getattr(self, '_bus_eta', {}).get(i)
                _bus_eta_s = _eta_info[1] if _eta_info else (
                    self.config['DetDistance'][0][i] / bus_speed)

                # Only insert if bus will miss the natural BusPhase window:
                # bus arrives AFTER the natural bus-green ends.
                _natural_bus_end = _time_to_bp + self.BusPhaseDuration
                if _bus_eta_s <= _natural_bus_end:
                    # Bus can catch the natural green — no insertion needed
                    if LOG_HARMONY:
                        _vprint(
                            f"[HARMONY] NO INSERT inter={self.id} "
                            f"bus_eta={_bus_eta_s:.1f}s <= "
                            f"natural_end={_natural_bus_end:.1f}s "
                            f"(to_bp={_time_to_bp:.1f}s + dur={self.BusPhaseDuration:.1f}s)")
                    continue

                # Bus will miss natural green → run harmony search for opt_BP
                opt_BP = harmony_search(
                    self.BP_Objective_Function, self.BP_lower_bound,
                    self.BP_upper_bound, self.max_iterations,
                    self.harmony_memory_size, self.hmcr, self.par, 5, time)
                self.previous_phase  = current_phase
                self.BusPhaseEndTime = time + float(opt_BP)
                # ECIChangeDirectPhase alone — ECIChangeTimingPhase first
                # would reset the background plan duration permanently.
                ECIChangeDirectPhase(
                    self.id, self.BusPhase, timeSta, time, acycle, 0)
                self.TSPStrategy   = 2
                self.flag          = 2
                self.TSPActiveTime = time + float(opt_BP) + 30
                self._tsp_cycle_grant_until = time + self.config.get('CycleTime', 135)
                if LOG_HARMONY:
                    _vprint(
                        f"[HARMONY] INSERTION | t={time:.1f}s inter={self.id} "
                        f"bus_eta={_bus_eta_s:.1f}s > natural_end={_natural_bus_end:.1f}s "
                        f"opt_BP={opt_BP:.1f}s prev_phase={current_phase}")
                self.highlight_bus(self.last_detected_bus_id)
                self.stats.record_tsp_event(self.id, 'detection')
                self.stats.record_tsp_event(self.id, 'insertion')
                return True
        return False
    
    def print_config_summary(self):
        """Comprehensive one-time logfile for debugging TSP logic"""
        log_to_file("=" * 80)
        log_to_file(f"[CONFIG SUMMARY] Intersection {self.id}")
        log_to_file(f"  BusPhase: {self.BusPhase} | Duration: {self.BusPhaseDuration}s")
        log_to_file(f"  PhaseIndex: {self.PhaseIndex}")
        log_to_file(f"  BusDet (NB-only): {self.BusDet}  ← must match DetDistance[0]")
        log_to_file(f"  BusCallDetectors: {self.urtsp_call_det_ids}")
        log_to_file(f"  UpDetList length: {len(self.UpDetList)} groups")
        for g, dets in enumerate(self.UpDetList):
            dd = self.DetDistance[g] if g < len(self.DetDistance) else "N/A"
            log_to_file(f"    Group {g}: {dets} | DetDistance: {dd}")
        log_to_file(f"  MainSections: {self.config.get('MainSections', [])}")
        log_to_file(f"  SideSections: {self.config.get('SideSections', [])}")
        log_to_file(f"  NumberOfLanes: {self.NumberOfLanes}")
        log_to_file(f"  Control mode: {CONTROL_MODE}")
        log_to_file("=" * 80)

    def GE_Objective_Function(self, GE, time):
        self._reset_harmony_work_arrays()
        # ── Phase 0 (Bus phase) ───────────────────────────────────────────────
        for i in range(len(self.BusDet)):
            self.HSMaxQueueLengthTime[0][i] = self.MaxQueueLengthTime[0][i]
            self.HSGreenStartTimeList[0][i] = self.GreenStartTimeList[0][i]
            self.HSMaxQueueLength[0][i]     = self.MaxQueueLength[0][i]
            self.HSRedDurationList[0][i]    = self.RedDurationList[0][i]
            self.HSQueueDissTime[0][i]      = self.QueueDissTime[0][i]
            self.HSMinQueueLength[0][i]     = self.MinQueueLength[0][i]
            self.HSMaxQueueLength[0][i]     = max(self.HSMaxQueueLength[0][i], 0.0)
            self.HSMinQueueLength[0][i]     = max(self.HSMinQueueLength[0][i], 0.0)
            self.TotalVeh[0][i] = (
                self.UpFlowList[0][i] *
                (self.HSRedDurationList[0][i] + 35 + GE) / 3600)
            if self.BusJoinQueueTime[0][i] <= self.HSMaxQueueLengthTime[0][i]:
                self.BusDelay[0][i] = (
                    self.HSGreenStartTimeList[0][i]
                    + (abs(self.ShockwaveSpeed1List[0][i]) * self.DetDistance[0][i]) /
                    ((abs(self.ShockwaveSpeed1List[0][i]) + self.BusSpeed[0][i]) *
                     abs(self.ShockwaveSpeed2List[0][i]))
                    - (time + self.DetDistance[0][i] /
                       (abs(self.ShockwaveSpeed1List[0][i]) +
                        abs(self.ShockwaveSpeed2List[0][i]))))
            else:
                self.BusDelay[0][i] = 0
            if self.HSQueueDissTime[0][i] < self.NextRedStartTime[0][i] + GE:
                self.OtherDelay[0][i] = max(0.0, (
                    (self.HSMaxQueueLength[0][i] * self.HSRedDurationList[0][i] / 2)
                    * (self.JamDensity - self.UpDenList[0][i]) / 1000
                    + ((self.HSQueueDissTime[0][i] - self.HSGreenStartTimeList[0][i])
                       * self.HSMaxQueueLength[0][i] / 2)
                    * (self.SaturationDensity - self.UpDenList[0][i]) / 1000))
            else:
                w3_ge = abs(self.ShockwaveSpeed3List[0][i])
                w4_ge = abs(self.ShockwaveSpeed4List[0][i])
                if w3_ge < 1e-6 or w4_ge < 1e-6:
                    self.OtherDelay[0][i] = 0.0
                else:
                    self.HSMinQueueLength[0][i] = max(0.0, (
                        (self.HSMaxQueueLength[0][i] / w3_ge
                         + self.HSMaxQueueLengthTime[0][i]
                         - self.NextRedStartTime[0][i] - GE) /
                        (1.0 / w3_ge + 1.0 / w4_ge)))
                    self.OtherDelay[0][i] = max(0.0, (
                        (self.HSMaxQueueLength[0][i] * self.HSRedDurationList[0][i] / 2)
                        * (self.JamDensity - self.UpDenList[0][i]) / 1000
                        + ((self.HSQueueDissTime[0][i] - self.HSGreenStartTimeList[0][i])
                           * self.HSMaxQueueLength[0][i]
                           - (self.HSQueueDissTime[0][i] - self.RedStartTimeList[0][i] - GE)
                           * self.HSMinQueueLength[0][i]) / 2
                        * (self.SaturationDensity - self.UpDenList[0][i]) / 1000))

        # ── Other phases (1..N) — project impact of extended green on their queues
        for i in range(1, len(self.UpDetList)):
            for j in range(len(self.UpDetList[i])):
                # Shift green start forward by existing cycle time + GE
                self.HSGreenStartTimeList[i][j] = self.GreenStartTimeList[i][j] + 80 + GE
                self.HSRedDurationList[i][j]    = (
                    self.HSGreenStartTimeList[i][j] - self.RedStartTimeList[i][j])
                self.HSMaxQueueLengthTime[i][j] = self.MaxQueueLengthTime[i][j]
                self.HSQueueDissTime[i][j]      = self.QueueDissTime[i][j]
                self.HSMaxQueueLength[i][j]     = self.MaxQueueLength[i][j]
                self.HSMinQueueLength[i][j]     = self.MinQueueLength[i][j]

                # Use UpFlowList (section-scan fallback already applied)
                self.HSUpFlowList[i][j]  = self.UpFlowList[i][j]
                self.HSUpDenList[i][j]   = (
                    self.HSUpFlowList[i][j] * self.SaturationDensity / self.SaturationFlow
                    if self.SaturationFlow > 0 else 0.0)
                self.HSUpDenList[i][j] = min(
                    max(self.HSUpDenList[i][j], 0.0), self.JamDensity)
                self.HSShockwaveSpeed1List[i][j] = ShockwaveSpeed1(
                    self.HSUpFlowList[i][j], self.JamDensity, self.HSUpDenList[i][j])
                self.HSShockwaveSpeed3List[i][j] = ShockwaveSpeed3(
                    self.SaturationFlow, self.HSUpFlowList[i][j],
                    self.SaturationDensity, self.HSUpDenList[i][j])

                w1 = self.HSShockwaveSpeed1List[i][j]
                w2 = self.ShockwaveSpeed2List[i][j]
                w3 = self.HSShockwaveSpeed3List[i][j]
                w4 = self.ShockwaveSpeed4List[i][j]
                rd = self.HSRedDurationList[i][j]
                denom = abs(w2) - abs(w1)
                if denom <= 1e-6 or abs(w3) < 1e-6:
                    self.TotalVeh[i][j] = self.UpFlowList[i][j] * (rd + GE + 35) / 3600
                    continue

                self.HSMaxQueueLength[i][j]     = abs(w2) * abs(w1) * rd / denom
                self.HSMaxQueueLengthTime[i][j] = (
                    abs(w2) * rd / denom)
                self.HSQueueDissTime[i][j]      = (
                    abs(w1) * abs(w2) * rd /
                    (abs(w3) * (abs(w2) - abs(w1))))
                self.TotalVeh[i][j] = self.UpFlowList[i][j] * (rd + GE + 35) / 3600

                nrs = self.NextRedStartTime[i][j]
                if self.HSQueueDissTime[i][j] < nrs + GE:
                    self.OtherDelay[i][j] = max(0.0, (
                        abs(w1) * abs(w2) * rd / (abs(w2) - abs(w1)) / 2
                        * (self.JamDensity - self.HSUpDenList[i][j]) / 1000
                        + (self.HSQueueDissTime[i][j] - self.HSGreenStartTimeList[i][j])
                        * self.HSMaxQueueLength[i][j] / 2
                        * (self.SaturationDensity - self.HSUpDenList[i][j])))
                else:
                    if abs(w3) > 1e-6 and abs(w4) > 1e-6:
                        self.HSMinQueueLength[i][j] = (
                            (self.HSMaxQueueLength[i][j] / abs(w3)
                             + self.HSMaxQueueLengthTime[i][j] - (nrs + GE))
                            / (1.0 / abs(w3) + 1.0 / abs(w4)))
                    self.HSMinQueueLength[i][j] = max(self.HSMinQueueLength[i][j], 0.0)
                    self.OtherDelay[i][j] = max(0.0, (
                        abs(w1) * abs(w2) * rd / (abs(w2) - abs(w1)) / 2
                        * (self.JamDensity - self.HSUpDenList[i][j]) / 1000
                        + ((self.HSQueueDissTime[i][j] - self.HSGreenStartTimeList[i][j])
                           * self.HSMaxQueueLength[i][j]
                           - (self.HSQueueDissTime[i][j] - nrs - GE)
                           * self.HSMinQueueLength[i][j]) / 2
                        * (self.SaturationDensity - self.HSUpDenList[i][j]) / 1000))

        # ── Side-street delay penalty ─────────────────────────────────────────
        # GE holds each side section at red for an extra GE seconds.
        # Triangle model: growth phase (w1 speed) + discharge phase (w3 speed).
        side_other_delay, side_total_veh = self._compute_side_delay_penalty(GE)

        bus_delay_total   = self._safe_array_sum(self.BusDelay)
        base_other_delay  = self._safe_array_sum(self.OtherDelay)
        other_delay_total = base_other_delay + safe_float(side_other_delay)
        total_veh         = self._safe_array_sum(self.TotalVeh) + safe_float(side_total_veh)

        other_occ = self._estimated_other_vehicle_occupancy()
        AveragePassengerDelay = (
            bus_delay_total * self.BusOcc +
            other_delay_total * other_occ
        ) / max(total_veh * other_occ + self.BusOcc, 1e-6)
        bus_delay_total, other_delay_total, total_veh, AveragePassengerDelay = (
            self._finalize_objective_stats(
                bus_delay_total, other_delay_total, total_veh, AveragePassengerDelay
            )
        )

        log_to_file(
            f"[HS GE_OBJ] inter={self.id} GE={GE:.2f}s "
            f"bus_delay={bus_delay_total:.2f} "
            f"other_delay={base_other_delay:.2f} "
            f"side_delay={safe_float(side_other_delay):.2f} "
            f"other_occ={other_occ:.2f} "
            f"total_veh={total_veh:.1f} "
            f"avg_pass_delay={AveragePassengerDelay:.4f}")
        self.stats.store_objective_stats(
            bus_delay=bus_delay_total,
            other_delay=other_delay_total,
            avg_pass_delay=AveragePassengerDelay)
        return AveragePassengerDelay

    def BP_Objective_Function(self, GreenTime, time):
        """
        Bus-phase rotation (phase insertion) objective function.
        Mirrors BP_Objective_Function from Bus_priority_single_intersection_3.py,
        adapted for multi-intersection class with full debug logging.
        """
        self._reset_harmony_work_arrays()
        # ── Phase 0: Bus phase ─────────────────────────────────────────────────
        for i in range(len(self.BusDet)):
            log_to_file(f"[HS BP_OBJ] inter={self.id} bus_det_idx={i} "
                        f"UpDetCount={self.UpDetCountList[0][i]:.0f}")
            # Projected green start: now + 5s (insertion delay)
            self.HSGreenStartTimeList[0][i] = time + 5
            self.HSRedStartTimeList[0][i]   = self.RedStartTimeList[0][i]
            self.HSRedDurationList[0][i]    = (
                self.HSGreenStartTimeList[0][i] - self.HSRedStartTimeList[0][i])
            red_dur = max(self.HSRedDurationList[0][i], 1.0)

            # Use UpFlowList which already incorporates section-scan fallback
            # when physical detector counts are unavailable (returns 0).
            self.HSUpFlowList[0][i]          = self.UpFlowList[0][i]
            self.HSUpDenList[0][i]           = min(max(
                self.HSUpFlowList[0][i] * self.SaturationDensity / self.SaturationFlow
                if self.SaturationFlow > 0 else 0.0, 0.0), self.JamDensity)
            self.HSShockwaveSpeed1List[0][i] = ShockwaveSpeed1(
                self.HSUpFlowList[0][i], self.JamDensity, self.HSUpDenList[0][i])
            self.HSShockwaveSpeed3List[0][i] = ShockwaveSpeed3(
                self.SaturationFlow, self.HSUpFlowList[0][i],
                self.SaturationDensity, self.HSUpDenList[0][i])

            log_to_file(f"[HS BP_OBJ] inter={self.id} i={i} "
                        f"HSUpFlow={self.HSUpFlowList[0][i]:.1f} "
                        f"HSUpDen={self.HSUpDenList[0][i]:.4f} "
                        f"w1={self.HSShockwaveSpeed1List[0][i]:.4f} "
                        f"w2={self.ShockwaveSpeed2List[0][i]:.4f} "
                        f"w3={self.HSShockwaveSpeed3List[0][i]:.4f}")

            self.TotalVeh[0][i] = self.HSUpFlowList[0][i] * (red_dur + GreenTime) / 3600

            w1 = self.HSShockwaveSpeed1List[0][i]
            w2 = self.ShockwaveSpeed2List[0][i]
            denom = abs(w2) - abs(w1)
            if denom > 1e-6:
                self.HSMaxQueueLength[0][i] = (
                    abs(w2) * abs(w1) * (time + 5 - self.HSRedStartTimeList[0][i])
                    / denom)
                self.HSMaxQueueLengthTime[0][i] = (
                    self.HSRedStartTimeList[0][i]
                    + abs(w2) * (time + 5 - self.HSRedStartTimeList[0][i]) / denom)
                self.HSMaxQueueLength[0][i] = max(self.HSMaxQueueLength[0][i], 0.0)

        for i in range(len(self.BusDet)):
            w1 = self.HSShockwaveSpeed1List[0][i]
            w2 = self.ShockwaveSpeed2List[0][i]
            w3 = self.HSShockwaveSpeed3List[0][i]
            w4 = self.ShockwaveSpeed4List[0][i]
            denom = abs(w2) - abs(w1)

            if denom <= 1e-6 or abs(w3) < 1e-6:
                self.BusDelay[0][i]  = 0.0
                self.OtherDelay[0][i] = 0.0
                continue

            log_to_file(f"[HS BP_OBJ] inter={self.id} i={i} "
                        f"HSMaxQ={self.HSMaxQueueLength[0][i]:.1f} "
                        f"HSMaxQTime={self.HSMaxQueueLengthTime[0][i]:.1f}")

            bus_speed = self.BusSpeed[0][i]
            if bus_speed > 0:
                # Time bus joins queue front
                self.BusJoinQueueTime[0][i] = (
                    (self.DetDistance[0][i]
                     - abs(w1) * (time - self.HSRedStartTimeList[0][i]))
                    / (bus_speed + abs(w1)) + time)

                log_to_file(f"[HS BP_OBJ] inter={self.id} i={i} "
                            f"BusJoinQTime={self.BusJoinQueueTime[0][i]:.1f} "
                            f"HSMaxQTime={self.HSMaxQueueLengthTime[0][i]:.1f}")

                if self.BusJoinQueueTime[0][i] > self.HSMaxQueueLengthTime[0][i]:
                    # Bus arrives after max queue → no stop
                    self.BusStoplineTime[0][i] = time + self.DetDistance[0][i] / bus_speed
                    self.BusPhaseMinDuration[0][i] = (
                        self.BusStoplineTime[0][i] - self.HSGreenStartTimeList[0][i])
                    self.BusDelay[0][i] = 0.0

                    log_to_file(f"[HS BP_OBJ] inter={self.id} i={i} "
                                f"case=no_stop_queue_clear BusStopline={self.BusStoplineTime[0][i]:.1f} "
                                f"MinDur={self.BusPhaseMinDuration[0][i]:.1f}")

                    for k in range(len(self.BusDet)):
                        w3k = abs(self.HSShockwaveSpeed3List[0][k])
                        w4k = abs(self.ShockwaveSpeed4List[0][k])
                        if w3k < 1e-6:
                            self.OtherDelay[0][k] = 0.0
                            continue
                        self.HSQueueDissTime[0][k] = (
                            self.HSMaxQueueLengthTime[0][k]
                            + self.HSMaxQueueLength[0][k] / w3k)
                        green_end = self.HSGreenStartTimeList[0][k] + GreenTime
                        if self.HSQueueDissTime[0][k] < green_end:
                            self.OtherDelay[0][k] = max(0.0, (
                                self.HSMaxQueueLength[0][k] * self.HSRedDurationList[0][k]
                                / 2 * (self.JamDensity - self.HSUpDenList[0][k]) / 1000
                                + (self.HSQueueDissTime[0][k]
                                   - self.HSGreenStartTimeList[0][k])
                                * self.HSMaxQueueLength[0][k] / 2
                                * (self.SaturationDensity - self.HSUpDenList[0][k]) / 1000))
                        else:
                            hsmin = 0.0
                            if w3k > 1e-6 and w4k > 1e-6:
                                nrs_k = self.HSNextRedStartTime[0][k]
                                hsmin = (
                                    (self.HSMaxQueueLength[0][k] / w3k
                                     + self.HSMaxQueueLengthTime[0][k] - (nrs_k + GreenTime))
                                    / (1.0 / w3k + 1.0 / w4k))
                            self.HSMinQueueLength[0][k] = max(hsmin, 0.0)
                            self.OtherDelay[0][k] = max(0.0, (
                                self.HSMaxQueueLength[0][k] * self.HSRedDurationList[0][k]
                                / 2 * (self.JamDensity - self.HSUpDenList[0][k]) / 1000
                                + ((self.HSQueueDissTime[0][k]
                                    - self.HSGreenStartTimeList[0][k])
                                   * self.HSMaxQueueLength[0][k]
                                   - (self.HSQueueDissTime[0][k] - green_end)
                                   * self.HSMinQueueLength[0][k]) / 2
                                * (self.SaturationDensity - self.HSUpDenList[0][k]) / 1000))

                else:
                    # Bus joins queue → compute discharge time
                    bus_pos = (self.DetDistance[0][i]
                               - bus_speed
                               * ((self.DetDistance[0][i]
                                   - abs(w1) * (time - self.RedStartTimeList[0][i]))
                                  / (bus_speed + abs(w1))))
                    bus_discharge = (
                        self.HSGreenStartTimeList[0][i] + bus_pos / abs(w2))
                    self.BusStoplineTime[0][i] = (
                        bus_discharge + bus_pos / abs(w3))
                    if self.BusStoplineTime[0][i] > self.HSGreenStartTimeList[0][i]:
                        self.BusPhaseMinDuration[0][i] = (
                            self.BusStoplineTime[0][i] - self.HSGreenStartTimeList[0][i])
                    self.BusDelay[0][i] = max(0.0,
                        self.HSGreenStartTimeList[0][i]
                        + (self.DetDistance[0][i]
                           - bus_speed * (self.DetDistance[0][i]
                                          - (self.HSGreenStartTimeList[0][i]
                                             - self.HSRedStartTimeList[0][i])
                                          * abs(w1))
                           / (bus_speed + abs(w1))) / abs(w2)
                        - (time + (self.DetDistance[0][i]
                                   - (self.HSGreenStartTimeList[0][i]
                                      - self.HSRedStartTimeList[0][i])
                                   * abs(w1))
                           / (bus_speed + abs(w1))))

                    log_to_file(f"[HS BP_OBJ] inter={self.id} i={i} "
                                f"case=joins_queue bus_pos={bus_pos:.1f} "
                                f"BusDelay={self.BusDelay[0][i]:.2f}")

                    for k in range(len(self.BusDet)):
                        w1k = abs(self.HSShockwaveSpeed1List[0][k])
                        w2k = abs(self.ShockwaveSpeed2List[0][k])
                        w3k = abs(self.HSShockwaveSpeed3List[0][k])
                        if w3k < 1e-6 or (w2k - w1k) <= 1e-6:
                            self.HSQueueDissTime[0][k] = 0.0
                            self.OtherDelay[0][k] = 0.0
                            continue
                        self.HSQueueDissTime[0][k] = (
                            self.HSRedStartTimeList[0][k]
                            + w2k * self.HSRedDurationList[0][k] / (w2k - w1k)
                            + w2k * w1k * self.HSRedDurationList[0][k]
                            / ((w2k - w1k) * w3k))
                        green_end = self.HSGreenStartTimeList[0][k] + GreenTime
                        if self.HSQueueDissTime[0][k] < green_end:
                            self.OtherDelay[0][k] = max(0.0, (
                                (self.HSMaxQueueLength[0][k]
                                 * self.HSRedDurationList[0][k] / 2)
                                * (self.JamDensity - self.HSUpDenList[0][k]) / 1000
                                + ((self.HSQueueDissTime[0][k]
                                    - self.HSGreenStartTimeList[0][k])
                                   * self.HSMaxQueueLength[0][k] / 2)
                                * (self.SaturationDensity - self.HSUpDenList[0][k]) / 1000))
                        else:
                            self.OtherDelay[0][k] = max(0.0, (
                                (self.HSMaxQueueLength[0][k]
                                 * self.HSRedDurationList[0][k] / 2)
                                * (self.JamDensity - self.HSUpDenList[0][k]) / 1000
                                + ((self.HSQueueDissTime[0][k]
                                    - self.HSGreenStartTimeList[0][k])
                                   * self.HSMaxQueueLength[0][k] / 2)
                                * (self.SaturationDensity - self.HSUpDenList[0][k]) / 1000
                                - (self.HSQueueDissTime[0][k] - green_end) / 2
                                * (self.SaturationDensity - self.HSUpDenList[0][k]) / 1000))

        # ── Interrupted phase (OrderToTerminatePhase = previous_phase index) ──
        otp_phase = self.previous_phase  # phase being interrupted
        if otp_phase in self.PhaseIndex:
            otp_idx = self.PhaseIndex[otp_phase]
            # Guard: PhaseIndex can map to group indices that UpDetList doesn't have
            # (e.g. PhaseIndex has values 0-3 but UpDetList only has 1 group).
            # Clamp to the valid range — the interrupted phase is treated as phase 0.
            if otp_idx >= len(self.UpDetList):
                otp_idx = 0
            for j in range(len(self.UpDetList[otp_idx])):
                self.HSNextRedStartTime[otp_idx][j] = (
                    self.NextRedStartTime[otp_idx][j] + time + 5)
                self.HSGreenStartTimeList[otp_idx][j] = self.GreenStartTimeList[0][j]
                self.HSGreenDurationList[otp_idx][j] = (
                    self.HSNextRedStartTime[otp_idx][j]
                    - self.HSGreenStartTimeList[otp_idx][j])
                self.HSUpFlowList[otp_idx][j]          = self.UpFlowList[otp_idx][j]
                self.HSShockwaveSpeed1List[otp_idx][j] = self.ShockwaveSpeed1List[otp_idx][j]
                self.HSShockwaveSpeed3List[otp_idx][j] = self.ShockwaveSpeed3List[otp_idx][j]
                self.HSRedDurationList[otp_idx][j]     = self.RedDurationList[otp_idx][j]
                self.TotalVeh[otp_idx][j] = (
                    self.HSUpFlowList[otp_idx][j] * GreenTime / 3600)

                w1o  = self.HSShockwaveSpeed1List[otp_idx][j]
                w2o  = self.ShockwaveSpeed2List[otp_idx][j]
                w3o  = self.HSShockwaveSpeed3List[otp_idx][j]
                w4o  = self.ShockwaveSpeed4List[otp_idx][j]
                gd   = self.HSGreenDurationList[otp_idx][j]
                denom_o = abs(w2o) - abs(w1o)
                if abs(denom_o) < 1e-6 or abs(w3o) < 1e-6:
                    continue

                residual_cleared = (
                    self.MaxQueueLength[otp_idx][j]
                    - abs(w3o) * gd < 0)
                if residual_cleared:
                    self.HSMaxQueueLength[otp_idx][j] = (
                        abs(w2o) * abs(w1o) * GreenTime / denom_o)
                else:
                    self.HSMaxQueueLength[otp_idx][j] = self.MaxQueueLength[otp_idx][j]

                nrs_o = self.HSNextRedStartTime[otp_idx][j]
                q_diss_o = (
                    self.HSMaxQueueLengthTime[otp_idx][j]
                    + self.HSMaxQueueLength[otp_idx][j] / abs(w3o))
                if q_diss_o < nrs_o:
                    self.OtherDelay[otp_idx][j] = max(0.0, (
                        self.HSMaxQueueLength[otp_idx][j]
                        * self.HSRedDurationList[otp_idx][j] / 2
                        * (self.JamDensity - self.UpDenList[otp_idx][j]) / 1000
                        + (q_diss_o - self.HSGreenStartTimeList[otp_idx][j])
                        * self.HSMaxQueueLength[otp_idx][j] / 2
                        * (self.SaturationDensity - self.UpDenList[otp_idx][j]) / 1000))
                else:
                    if abs(w3o) > 1e-6 and abs(w4o) > 1e-6:
                        min_q = (
                            (self.HSMaxQueueLength[otp_idx][j] / abs(w3o)
                             + self.HSMaxQueueLengthTime[otp_idx][j] - nrs_o)
                            / (1.0 / abs(w3o) + 1.0 / abs(w4o)))
                        self.HSMinQueueLength[otp_idx][j] = max(min_q, 0.0)
                    self.OtherDelay[otp_idx][j] = max(0.0, (
                        self.HSMaxQueueLength[otp_idx][j]
                        * self.HSRedDurationList[otp_idx][j] / 2
                        * (self.JamDensity - self.UpDenList[otp_idx][j]) / 1000
                        + ((q_diss_o - self.HSGreenStartTimeList[otp_idx][j])
                           * self.HSMaxQueueLength[otp_idx][j]
                           - (q_diss_o - nrs_o)
                           * self.HSMinQueueLength[otp_idx][j]) / 2
                        * (self.SaturationDensity - self.UpDenList[otp_idx][j]) / 1000))

        # ── All other phases (not bus=0 and not interrupted) ──────────────────
        otp_idx_val = self.PhaseIndex.get(otp_phase, -1) if otp_phase in self.PhaseIndex else -1
        for i in range(len(self.UpDetList)):
            if i == 0 or i == otp_idx_val:
                continue
            for j in range(len(self.UpDetList[i])):
                self.HSRedStartTimeList[i][j]  = self.RedStartTimeList[i][j]
                self.HSRedDurationList[i][j]   = self.RedDurationList[i][j] + GreenTime + 5
                elapsed = max(time - self.HSRedStartTimeList[i][j], 1.0)
                self.HSUpFlowList[i][j]        = (
                    self.UpDetCountList[i][j] / elapsed * 3600)
                self.HSUpDenList[i][j] = min(
                    max(self.HSUpFlowList[i][j] * self.SaturationDensity / max(self.SaturationFlow, 1.0), 0.0),
                    self.JamDensity)
                self.TotalVeh[i][j]            = (
                    self.HSUpFlowList[i][j]
                    * (self.HSRedDurationList[i][j] + 35) / 3600)

                w1i = self.ShockwaveSpeed1List[i][j]
                w2i = self.ShockwaveSpeed2List[i][j]
                w3i = self.ShockwaveSpeed3List[i][j]
                w4i = self.ShockwaveSpeed4List[i][j]
                rd_i = self.HSRedDurationList[i][j]
                den_i = abs(w2i) - abs(w1i)
                if den_i <= 1e-6 or abs(w3i) < 1e-6:
                    continue

                self.HSMaxQueueLength[i][j] = (
                    abs(w1i) * abs(w2i) * (rd_i) / den_i)
                self.HSMaxQueueLength[i][j] = max(self.HSMaxQueueLength[i][j], 0.0)
                self.HSMaxQueueLengthTime[i][j] = (
                    self.HSRedStartTimeList[i][j]
                    + abs(w2i) * (rd_i + GreenTime + 5) / den_i)
                self.HSGreenStartTimeList[i][j] = (
                    self.HSRedStartTimeList[i][j] + self.HSRedDurationList[i][j])
                self.HSNextRedStartTime[i][j]   = (
                    self.HSGreenStartTimeList[i][j] + 40)
                q_diss_i = (
                    self.HSMaxQueueLengthTime[i][j]
                    + self.HSMaxQueueLength[i][j] / abs(w3i))
                nrs_i = self.HSNextRedStartTime[i][j]
                if q_diss_i > nrs_i:
                    min_qi = 0.0
                    if abs(w3i) > 1e-6 and abs(w4i) > 1e-6:
                        min_qi = (
                            (self.HSMaxQueueLength[i][j] / abs(w3i)
                             + self.HSMaxQueueLengthTime[i][j] - (nrs_i + GreenTime + 5))
                            / (1.0 / abs(w3i) + 1.0 / abs(w4i)))
                    self.HSMinQueueLength[i][j] = max(min_qi, 0.0)
                    self.OtherDelay[i][j] = max(0.0, (
                        self.HSMaxQueueLength[i][j] * rd_i / 2
                        * (self.JamDensity - self.UpDenList[i][j]) / 1000
                        + ((q_diss_i - self.HSGreenStartTimeList[i][j])
                           * self.HSMaxQueueLength[i][j]
                           - (q_diss_i - nrs_i) * self.HSMinQueueLength[i][j]) / 2
                        * (self.SaturationDensity - self.UpDenList[i][j]) / 1000))
                else:
                    self.OtherDelay[i][j] = max(0.0, (
                        self.HSMaxQueueLength[i][j] * rd_i / 2
                        * (self.JamDensity - self.UpDenList[i][j]) / 1000
                        + (q_diss_i - self.HSGreenStartTimeList[i][j])
                        * self.HSMaxQueueLength[i][j] / 2
                        * (self.SaturationDensity - self.UpDenList[i][j]) / 1000))

        # ── Side-street delay penalty ─────────────────────────────────────────
        # Phase insertion forces side sections to wait GreenTime + 5s extra.
        extra_red = GreenTime + 5.0
        side_other_delay_bp, side_total_veh_bp = self._compute_side_delay_penalty(extra_red)

        bus_delay_total   = self._safe_array_sum(self.BusDelay)
        base_other_delay  = self._safe_array_sum(self.OtherDelay)
        other_delay_total = base_other_delay + safe_float(side_other_delay_bp)
        total_veh         = self._safe_array_sum(self.TotalVeh) + safe_float(side_total_veh_bp)

        other_occ = self._estimated_other_vehicle_occupancy()
        AveragePassengerDelay = (
            bus_delay_total * self.BusOcc +
            other_delay_total * other_occ
        ) / max(total_veh * other_occ + self.BusOcc, 1e-6)
        bus_delay_total, other_delay_total, total_veh, AveragePassengerDelay = (
            self._finalize_objective_stats(
                bus_delay_total, other_delay_total, total_veh, AveragePassengerDelay
            )
        )

        log_to_file(
            f"[HS BP_OBJ] inter={self.id} GreenTime={GreenTime:.2f}s "
            f"bus_delay={bus_delay_total:.2f} "
            f"other_delay={base_other_delay:.2f} "
            f"side_delay={safe_float(side_other_delay_bp):.2f} "
            f"other_occ={other_occ:.2f} "
            f"total_veh={total_veh:.1f} "
            f"avg_pass_delay={AveragePassengerDelay:.4f}")
        self.stats.store_objective_stats(
            bus_delay=bus_delay_total,
            other_delay=other_delay_total,
            avg_pass_delay=AveragePassengerDelay)
        return AveragePassengerDelay


# =============================================================================
# AIMSUN CALLBACKS
# =============================================================================

def AAPILoad():
    _vprint("=" * 60)
    if LOG_INIT: AKIPrintString(f"[TSP] Script loaded | mode={CONTROL_MODE}")
    if LOG_INIT: AKIPrintString(f"[TSP] Log file → {LOG_FILE}")
    if LOG_INIT: AKIPrintString(f"[TSP] Intersections configured: {list(INTERSECTIONS_CONFIG.keys())}")
    _vprint("=" * 60)
    log_to_file(f"[LOAD] AAPILoad complete | mode={CONTROL_MODE} | "
                f"n_intersections={len(INTERSECTIONS_CONFIG)}")
    return 0


def AAPIInit():
    global controllers, corridor_coordinators
    dm = DemandMonitor()
    dm.print_demand("AAPIInit")
    for inter_id, config in INTERSECTIONS_CONFIG.items():
        try:
            stats.register_intersection(config)
            controllers[inter_id] = IntersectionController(config)
        except Exception as e:
            if LOG_INIT: AKIPrintString(f"[INIT] ERROR creating controller {inter_id}: {e}")

    # ── Log phase-group summary for every GROUP_BASED intersection ────────────
    if CONTROL_MODE in ("GROUP_BASED", "GROUP_BASED_URTSP", "GROUP_BASED_HARMONY"):
        log_to_file("[INIT] ===== GROUP-BASED PHASE GROUP SUMMARY =====")
        for iid, ctrl in controllers.items():
            if ctrl.gb is not None:
                gb = ctrl.gb
                n_pg = len(gb.phase_groups)
                detail = " | ".join(
                    f"[{','.join(map(str,g))}](mg={sum(gb.max_green.get(s,40.) for s in g):.0f}s)"
                    for g in gb.phase_groups
                )
                log_to_file(
                    f"[INIT] jct={iid} sg_count={len(gb.all_sg)} "
                    f"phase_groups={n_pg} bus_sg={gb.bus_sg} tsp_mode={gb.tsp_mode} | {detail}"
                )
                AKIPrintString(
                    f"[INIT] jct={iid} phase_groups={n_pg} "
                    f"all_sg={gb.all_sg} bus_sg={gb.bus_sg}"
                )
            else:
                log_to_file(f"[INIT] jct={iid} — GroupBasedController NOT initialised (check control type = External)")
                AKIPrintString(f"[INIT] WARNING jct={iid} — GroupBasedController not initialised")

    # ── Build corridor coordinators from INTERSECTION_GROUPS ─────────────────
    if CONTROL_MODE in ("GROUP_BASED", "GROUP_BASED_URTSP", "GROUP_BASED_HARMONY"):
        corridor_coordinators = []
        log_to_file(f"[INIT] Building corridor coordinators from {len(INTERSECTION_GROUPS)} group(s)")
        for gname, iids in INTERSECTION_GROUPS.items():
            coord = CorridorCoordinator(gname, iids, controllers)
            corridor_coordinators.append(coord)
        AKIPrintString(
            f"[INIT] Corridor groups: "
            + ", ".join(
                f"{c.name}({len(c.inter_ids)} intersections)"
                for c in corridor_coordinators
            )
        )

    return 0


def _apply_config_patches(iid, config, ctrl, aimsun_n_phases):
    """
    Patch config dict and live controller attributes to match Aimsun's reality.

    Called once per intersection from validate_intersection_configs after the
    comparison is done.  Only writes a field when the live Aimsun value differs
    from what the config has — so a correct config is untouched.

    Patchable fields
    ----------------
    - NumberOfPhases       → from ECIGetNumberPhases
    - GreenPhaseDuration   → from GetPhaseDuration (each phase, 0-based timeSta)
    - SignalGroupIDList     → rebuilt from ECIGetNumberSignalGroupsPhase /
                              ECIGetSignalGroupId preserving config order where
                              IDs still exist, appending new ones at the end
    - PhaseIndex           → remapped so no value exceeds len(UpDetList)-1;
                              values that are out of range are clamped to 0
    - DetDistance          → wrapped to nested list if still flat
    - controller.PhaseIndex, controller.SignalGroupIDList, controller.phase_list
      updated to stay in sync with the patched config

    Cannot patch at runtime
    -----------------------
    - Control type (must be set in Aimsun GUI)
    - UpDetList / BusDet   (detector wiring, would need re-initialisation)
    """
    patches = []

    try:
        # ── 1. NumberOfPhases ─────────────────────────────────────────────
        if config.get('NumberOfPhases') != aimsun_n_phases:
            config['NumberOfPhases'] = aimsun_n_phases
            patches.append(f'NumberOfPhases → {aimsun_n_phases}')

        # ── 2. GreenPhaseDuration — refresh from Aimsun live plan ─────────
        live_durs = []
        for ph in range(1, aimsun_n_phases + 1):
            try:
                live_durs.append(round(GetPhaseDuration(iid, ph, 0.0), 1))
            except Exception:
                cfg_d = config.get('GreenPhaseDuration', [])
                live_durs.append(cfg_d[ph - 1] if ph - 1 < len(cfg_d) else 10.0)

        cfg_durs = config.get('GreenPhaseDuration', [])
        if live_durs != cfg_durs:
            config['GreenPhaseDuration'] = live_durs
            patches.append(f'GreenPhaseDuration → {live_durs}')

        # ── 3. SignalGroupIDList — rebuild from Aimsun, preserve config order
        live_sg_list = []
        for ph in range(1, aimsun_n_phases + 1):
            try:
                n_sg = ECIGetNbSignalGroupsPhaseofJunction(iid, ph, 0.0)
                ph_sgs = []
                for pos in range(1, n_sg + 1):
                    try:
                        ph_sgs.append(ECIGetSignalGroupPhaseofJunction(iid, ph, pos, 0.0))
                    except Exception:
                        pass
            except Exception:
                ph_sgs = []

            # Preserve config ordering for IDs that still exist; append new ones
            cfg_ph_sgs = (config.get('SignalGroupIDList', [])[ph - 1]
                          if ph - 1 < len(config.get('SignalGroupIDList', []))
                          else [])
            aimsun_set = set(ph_sgs)
            ordered = [sg for sg in cfg_ph_sgs if sg in aimsun_set]
            for sg in ph_sgs:
                if sg not in ordered:
                    ordered.append(sg)
            live_sg_list.append(ordered)

        if live_sg_list != config.get('SignalGroupIDList', []):
            config['SignalGroupIDList'] = live_sg_list
            patches.append(f'SignalGroupIDList rebuilt from Aimsun')
            if ctrl is not None:
                ctrl.SignalGroupIDList = live_sg_list

        # ── 4. PhaseIndex — clamp out-of-range values to 0 ───────────────
        up_det = config.get('UpDetList', [])
        n_groups = max(len(up_det), 1)
        phase_idx = dict(config.get('PhaseIndex', {}))
        clamped = {}
        for k, v in phase_idx.items():
            if v >= n_groups:
                phase_idx[k] = 0
                clamped[k] = v
        if clamped:
            config['PhaseIndex'] = phase_idx
            patches.append(f'PhaseIndex clamped {clamped} → 0 (UpDetList has {n_groups} group(s))')
            if ctrl is not None:
                ctrl.PhaseIndex = phase_idx

        # ── 5. DetDistance — ensure nested ───────────────────────────────
        dd = config.get('DetDistance', [])
        if dd and not isinstance(dd[0], (list, tuple)):
            config['DetDistance'] = [dd]
            patches.append(f'DetDistance wrapped to nested')
            if ctrl is not None:
                ctrl.DetDistance = config['DetDistance']
                ctrl.config['DetDistance'] = config['DetDistance']

        # ── 6. Sync controller phase_list ────────────────────────────────
        if ctrl is not None:
            new_pl = list(range(1, aimsun_n_phases + 1))
            if ctrl.phase_list != new_pl:
                ctrl.phase_list = new_pl
                patches.append(f'phase_list → {new_pl}')

    except Exception as ex:
        log_to_file(f'[PATCH] inter={iid} unexpected error: {ex}')
        _vprint(f'[PATCH] WARNING inter={iid}: patch step failed: {ex}')
        return

    if patches:
        msg = f'[PATCH] inter={iid} auto-corrected: ' + ' | '.join(patches)
        log_to_file(msg)
        _vprint(msg)
    else:
        log_to_file(f'[PATCH] inter={iid}: no patches needed')


def validate_intersection_configs():
    """
    Compare every field in INTERSECTIONS_CONFIG against live Aimsun values.

    Checks per intersection
    -----------------------
    1. Control type        — must be 2 or 3 (External API)
    2. Phase count         — ECIGetNumberPhases vs config NumberOfPhases / SignalGroupIDList length
    3. Phase durations     — GetPhaseDuration vs config GreenPhaseDuration
    4. Signal groups/phase — ECIGetNumberSignalGroupsPhase vs len(SignalGroupIDList[phase-1])
    5. Signal group IDs    — ECIGetSignalGroupId vs SignalGroupIDList values
    6. PhaseIndex sanity   — every value must be < len(UpDetList)
    7. DetDistance shape   — must be nested (list of lists) matching UpDetList shape

    Output: full detail to LOG_FILE, summary warnings to Aimsun console.
    """
    SEP  = '=' * 72
    sep2 = '-' * 72

    log_to_file(SEP)
    log_to_file('[VALIDATE] ===== INTERSECTION CONFIG VALIDATION =====')
    log_to_file(SEP)

    total_warnings = 0
    total_errors   = 0

    for iid, config in INTERSECTIONS_CONFIG.items():
        warnings = []
        errors   = []

        cfg_n_phases   = config.get('NumberOfPhases', len(config.get('SignalGroupIDList', [])))
        cfg_sg_list    = config.get('SignalGroupIDList', [])
        cfg_phase_idx  = config.get('PhaseIndex', {})
        cfg_up_det     = config.get('UpDetList', [])
        cfg_det_dist   = config.get('DetDistance', [])
        cfg_green_dur  = config.get('GreenPhaseDuration', [])

        log_to_file(sep2)
        log_to_file(f'[VALIDATE] Junction {iid}')

        # ── 1. Control type ───────────────────────────────────────────────
        try:
            ctrl_type = ECIGetControlType(iid)
            status = 'OK' if ctrl_type in (2, 3) else 'ERROR'
            log_to_file(f'  ControlType : {ctrl_type}  [{status}]  (expected 2 or 3 = External)')
            if ctrl_type not in (2, 3):
                errors.append(f'control type={ctrl_type} (not External)')
        except Exception as ex:
            errors.append(f'ECIGetControlType failed: {ex}')

        # ── 2. Phase count ────────────────────────────────────────────────
        try:
            aimsun_n = ECIGetNumberPhases(iid)
            match = 'OK' if aimsun_n == cfg_n_phases else 'MISMATCH'
            log_to_file(
                f'  Phases      : Aimsun={aimsun_n}  config={cfg_n_phases}  [{match}]')
            if match != 'OK':
                warnings.append(
                    f'phase count Aimsun={aimsun_n} vs config={cfg_n_phases}')
        except Exception as ex:
            errors.append(f'ECIGetNumberPhases failed: {ex}')
            aimsun_n = cfg_n_phases   # best-guess fallback

        # ── 3. Per-phase: duration, signal groups, SG IDs ─────────────────
        for ph in range(1, aimsun_n + 1):
            ph_idx = ph - 1   # 0-based index into config lists

            # Phase duration
            try:
                aimsun_dur = GetPhaseDuration(iid, ph, 0.0)
                if cfg_green_dur and ph_idx < len(cfg_green_dur):
                    cfg_dur = cfg_green_dur[ph_idx]
                    dur_ok  = abs(aimsun_dur - cfg_dur) < 1.0
                    log_to_file(
                        f'  Phase {ph:2d} dur : Aimsun={aimsun_dur:.1f}s  '
                        f'config={cfg_dur:.1f}s  '
                        f'[{"OK" if dur_ok else "MISMATCH"}]')
                    if not dur_ok:
                        warnings.append(
                            f'phase {ph} duration Aimsun={aimsun_dur:.1f}s '
                            f'vs config={cfg_dur:.1f}s')
                else:
                    log_to_file(
                        f'  Phase {ph:2d} dur : Aimsun={aimsun_dur:.1f}s  '
                        f'config=<not specified>')
            except Exception as ex:
                warnings.append(f'phase {ph} duration query failed: {ex}')

            # Signal group count per phase
            try:
                aimsun_sg_n = ECIGetNbSignalGroupsPhaseofJunction(iid, ph, 0.0)
                cfg_sg_n    = len(cfg_sg_list[ph_idx]) if ph_idx < len(cfg_sg_list) else 0
                sg_n_ok     = (aimsun_sg_n == cfg_sg_n)
                log_to_file(
                    f'  Phase {ph:2d} SGs : Aimsun={aimsun_sg_n}  '
                    f'config={cfg_sg_n}  '
                    f'[{"OK" if sg_n_ok else "MISMATCH"}]')
                if not sg_n_ok:
                    warnings.append(
                        f'phase {ph} SG count Aimsun={aimsun_sg_n} '
                        f'vs config={cfg_sg_n}')

                # Signal group IDs per phase
                aimsun_sgs = []
                for pos in range(1, aimsun_sg_n + 1):
                    try:
                        sg_id = ECIGetSignalGroupPhaseofJunction(iid, ph, pos, 0.0)
                        aimsun_sgs.append(sg_id)
                    except Exception:
                        aimsun_sgs.append(None)

                cfg_sgs = cfg_sg_list[ph_idx] if ph_idx < len(cfg_sg_list) else []
                aimsun_set = set(x for x in aimsun_sgs if x is not None)
                cfg_set    = set(cfg_sgs)
                missing_from_cfg    = aimsun_set - cfg_set
                extra_in_cfg        = cfg_set - aimsun_set

                log_to_file(
                    f'  Phase {ph:2d} IDs : Aimsun={sorted(aimsun_sgs)}  '
                    f'config={sorted(cfg_sgs)}')
                if missing_from_cfg:
                    warnings.append(
                        f'phase {ph} SGs in Aimsun but not config: {sorted(missing_from_cfg)}')
                    log_to_file(
                        f'           WARNING: SGs {sorted(missing_from_cfg)} '
                        f'in Aimsun but missing from config')
                if extra_in_cfg:
                    warnings.append(
                        f'phase {ph} SGs in config but not Aimsun: {sorted(extra_in_cfg)}')
                    log_to_file(
                        f'           WARNING: SGs {sorted(extra_in_cfg)} '
                        f'in config but not found in Aimsun')

            except Exception as ex:
                warnings.append(f'phase {ph} SG query failed: {ex}')

        # ── 4. PhaseIndex vs UpDetList range ──────────────────────────────
        n_det_groups = len(cfg_up_det)
        bad_pi = {k: v for k, v in cfg_phase_idx.items()
                  if v >= n_det_groups and n_det_groups > 0}
        if bad_pi:
            errors.append(
                f'PhaseIndex values {bad_pi} exceed UpDetList length {n_det_groups} '
                f'— will cause IndexError in objective functions')
            log_to_file(
                f'  PhaseIndex  : ERROR — values {bad_pi} out of range '
                f'for UpDetList length {n_det_groups}')
        else:
            log_to_file(
                f'  PhaseIndex  : OK (all values < UpDetList length {n_det_groups})')

        # ── 5. DetDistance shape ──────────────────────────────────────────
        if cfg_det_dist:
            if not isinstance(cfg_det_dist[0], (list, tuple)):
                warnings.append(
                    'DetDistance is flat — should be nested list matching UpDetList '
                    '(auto-fixed at runtime, but config should be corrected)')
                log_to_file(
                    f'  DetDistance : WARN flat list {cfg_det_dist} '
                    f'— auto-nested at runtime')
            else:
                log_to_file(f'  DetDistance : OK nested {cfg_det_dist}')

        # ── Summary for this intersection ─────────────────────────────────
        total_warnings += len(warnings)
        total_errors   += len(errors)

        if errors or warnings:
            _vprint(
                f'[VALIDATE] inter={iid} — '
                f'{len(errors)} error(s), {len(warnings)} warning(s)')
            for e in errors:
                _vprint(f'  [VALIDATE ERROR]   inter={iid}: {e}')
            for w in warnings:
                _vprint(f'  [VALIDATE WARN]    inter={iid}: {w}')
        else:
            _vprint(f'[VALIDATE] inter={iid} — OK')

        # ── Auto-patch: fix the config dict and live controller in-place ──
        # Only touches fields where Aimsun's live values differ from config.
        # Skips control-type errors (can't fix at runtime) and missing junctions.
        ctrl = controllers.get(iid)
        _apply_config_patches(iid, config, ctrl, aimsun_n)

    log_to_file(SEP)
    log_to_file(
        f'[VALIDATE] DONE — {total_errors} errors, {total_warnings} warnings '
        f'across {len(INTERSECTIONS_CONFIG)} intersections')
    log_to_file(f'[VALIDATE] Full detail in log: {LOG_FILE}')
    log_to_file(SEP)
    _vprint(
        f'[VALIDATE] Config check complete — '
        f'{total_errors} error(s), {total_warnings} warning(s). '
        f'See log: {LOG_FILE}')


def AAPISimulationReady():
    global controllers
    try:
        stats.finalise_init()
    except Exception as e:
        _vprint(f"[TSP] WARNING: finalise_init failed: {e}")

    validate_intersection_configs()

    # Junctions must be set to External/API control type in the Aimsun model
    # GUI before running — this cannot be done via the AAPI at runtime.
    # Verify each junction is actually under external control and warn if not.
    for iid in list(controllers.keys()):
        ctrl_type = ECIGetControlType(iid)
        if ctrl_type not in (2, 3):
            _vprint(
                f"[CONTROL] WARNING: junction {iid} control type={ctrl_type} "                f"— expected 2 or 3 (External). "                f"Set junction to 'External' control in the Aimsun model GUI.")

    # === REBUILD PHASE LIST NOW THAT JUNCTIONS ARE UNDER CONTROL ===
    for iid, ctrl in controllers.items():
        try:
            num_phases = ECIGetNumberPhases(iid)
            ctrl.phase_list = list(range(1, num_phases + 1))
            '''
            _vprint(f"[CONTROL] Junction {iid}: {num_phases} phases → {ctrl.phase_list}")
            '''
        except Exception as e:
            _vprint(f"[CONTROL] WARNING: could not get phases for {iid}: {e}")

    # === RE-INITIALISE GROUP-BASED CONTROLLERS WITH LIVE ECI DATA ===
    # AAPIInit runs before the simulation starts — ECI phase scan may return
    # nothing for junctions not yet active, producing an all-conflict matrix
    # and 1-SG-per-group structure.  Now that the sim is running, re-derive
    # from the live model to get correct phase-based compatibility groupings.
    if CONTROL_MODE in ("GROUP_BASED", "GROUP_BASED_URTSP", "GROUP_BASED_HARMONY"):
        for iid, ctrl in controllers.items():
            if ctrl.gb is not None:
                try:
                    ctrl.gb.reinitialise_from_model()
                except Exception as e:
                    _vprint(f"[GB] WARNING jct={iid} reinitialise_from_model failed: {e}")

        # Compute corridor positions (metres along route) for Kalman coordination.
        # Junction XY is available now that the simulation is running.
        # We walk each corridor group in listed order, accumulating Euclidean
        # distance between consecutive junction centroids.  If XY cannot be
        # resolved for a junction, its position is estimated using the previous
        # gap + a 400 m nominal link length.
        if COORDINATED_TSP:
            NOMINAL_LINK_M = 400.0   # fallback inter-junction spacing
            for coord in corridor_coordinators:
                pos_map   = {}
                cum_pos   = 0.0
                prev_xy   = None
                for iid in coord.inter_ids:
                    gb = coord._ctrl_map.get(iid)
                    xy = gb._get_junction_xy() if gb else None
                    if xy is not None and prev_xy is not None:
                        dx = xy[0] - prev_xy[0]
                        dy = xy[1] - prev_xy[1]
                        cum_pos += math.sqrt(dx*dx + dy*dy)
                    elif prev_xy is not None:
                        cum_pos += NOMINAL_LINK_M   # XY unavailable — use nominal
                    pos_map[iid] = cum_pos
                    if xy is not None:
                        prev_xy = xy
                    elif prev_xy is None:
                        prev_xy = (0.0, 0.0)  # anchor first junction at origin
                coord.set_corridor_positions(pos_map)
        else:
            log_to_file("[CORRIDOR] COORDINATED_TSP=False — Kalman pre-arming disabled")

    scan_car_pos, scan_bus_pos, scan_truck_pos = _scan_named_vehicle_type_positions()
    pt_bus_pos = _infer_bus_type_pos_from_pt()
    bus_pos = pt_bus_pos if pt_bus_pos > 0 else (
        getattr(stats, '_bus_pos', -1) if getattr(stats, '_bus_pos', -1) > 0 else scan_bus_pos)
    truck_pos = getattr(stats, '_truck_pos', -1)
    if truck_pos <= 0:
        truck_pos = scan_truck_pos
    car_pos = getattr(stats, '_car_pos', -1)
    if car_pos <= 0 or car_pos == bus_pos:
        car_pos = _choose_car_type_pos(bus_pos, truck_pos, preferred_pos=scan_car_pos)

    log_to_file(
        f"[VEH TYPES] named_scan car={scan_car_pos} bus={scan_bus_pos} truck={scan_truck_pos} | "
        f"pt_inferred_bus={pt_bus_pos} | "
        f"using car={car_pos} bus={bus_pos} truck={truck_pos}")
    for ctrl in controllers.values():
        if car_pos > 0:
            ctrl.car_type_pos = car_pos
        if bus_pos > 0:
            ctrl.bus_type_pos = bus_pos
        if truck_pos > 0:
            ctrl.truck_type_pos = truck_pos
    if car_pos > 0:
        stats._car_pos = car_pos
    if bus_pos > 0:
        stats._bus_pos = bus_pos
    if truck_pos > 0:
        stats._truck_pos = truck_pos
    else:
        stats._truck_pos = -1

    # If bus type still unresolved, schedule a lazy recheck in PostManage
    # (PT vehicles may not exist yet at AAPIInit time)
    global _bus_type_needs_recheck
    _bus_type_needs_recheck = (bus_pos <= 0)
    if _bus_type_needs_recheck:
        log_to_file("[VEH TYPES] bus_pos unresolved at init — will retry from PT vehicles in first 120s")
    '''
    _vprint(f"[TSP] Simulation ready | mode={CONTROL_MODE} | {len(controllers)} intersections under external control")
    '''
    return 0


def AAPIManage(time, timeSta, timeTrans, acycle):
    
    return 0


def AAPIPostManage(time, timeSta, timeTrans, acycle):
    # Lazy bus-type recheck: PT vehicles may not exist at AAPIInit time
    global _bus_type_needs_recheck
    if _bus_type_needs_recheck:
        # Try every 30 s for the first 600 s (10 min) to allow time for buses
        # to enter the network before giving up.  The original 120 s window was
        # too short — buses hadn't appeared yet when the recheck was abandoned.
        _recheck_interval = 30.0
        _recheck_limit    = 600.0
        if time <= _recheck_limit and int(time) % int(_recheck_interval) == 0:
            _pt_bus = _infer_bus_type_pos_from_pt()
            if _pt_bus > 0:
                _bus_type_needs_recheck = False
                for ctrl in controllers.values():
                    ctrl.bus_type_pos = _pt_bus
                    if ctrl.gb is not None:
                        ctrl.gb.bus_type_pos = _pt_bus
                stats._bus_pos = _pt_bus
                log_to_file(
                    f"[VEH TYPES] lazy PT inference at t={time:.0f}: "
                    f"bus_type_pos={_pt_bus} — updated all controllers + GB sub-controllers"
                )
        elif time > _recheck_limit:
            _bus_type_needs_recheck = False
            log_to_file(
                f"[VEH TYPES] lazy recheck exhausted at t={time:.0f} "
                f"({_recheck_limit:.0f}s limit): bus_type_pos still unresolved. "
                f"Check vehicle type names in Aimsun model or add BUS_TYPE_POS "
                f"to INTERSECTIONS_CONFIG entry."
            )

    try:
        stats.track_bus_positions(time)
    except Exception as e:
        stop_simulation(f"track_bus_positions crashed t={time:.1f}: {e}")
        return 0

    for inter_id, controller in controllers.items():
        try:
            controller.collect_delay(time, timeSta)
        except Exception as e:
            stop_simulation(f"collect_delay crashed inter={inter_id} t={time:.1f}: {e}")
            return 0
        try:
            controller.update(time, timeSta, acycle)
        except Exception as e:
            stop_simulation(f"update crashed inter={inter_id} t={time:.1f}: {e}")
            return 0

    # ── Step corridor coordinators (after all individual controllers) ─────────
    for coord in corridor_coordinators:
        try:
            coord.step(time, timeSta)
        except Exception as e:
            log_to_file(f"[CORRIDOR] coordinator {coord.name} crashed t={time:.1f}: {e}")

    return 0


def AAPIFinish():
    log_to_file("===== AAPIFinish =====")
    try:
        stats.print_results()
        stats.save_results()
    except Exception as e:
        log_to_file(f"[FINISH] stats error: {e}")
    for controller in controllers.values():
        if CONTROL_MODE == "URTSP":
            log_to_file(controller.get_urtsp_summary())
    # ── Corridor summary ──────────────────────────────────────────────────────
    for coord in corridor_coordinators:
        log_to_file(f"[FINISH] {coord.summary()}")
    return 0


def AAPIUnLoad():
    return 0


# required stubs
def AAPIPreRouteChoiceCalculation(time, timeSta): return 0
def AAPIVehicleStartParking(idveh, idsection, time): return 0
def AAPIEnterVehicle(idveh, idsection): return 0
def AAPIExitVehicle(idveh, idsection): return 0
def AAPIEnterVehicleSection(idveh, idsection, atime): return 0
def AAPIExitVehicleSection(idveh, idsection, atime): return 0
def AAPIEnterPedestrian(idPedestrian, originCentroid): return 0
def AAPIExitPedestrian(idPedestrian, destinationCentroid): return 0
def AAPIActionActivated(idAction): return 0
def AAPIActionDeactivated(idAction): return 0
