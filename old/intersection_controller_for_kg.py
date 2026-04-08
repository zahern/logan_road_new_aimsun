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

# ==================== LOGGING SETUP ====================
LOG_DIR = r"D:\Aimsun_Results\Logs"
os.makedirs(LOG_DIR, exist_ok=True)

timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(LOG_DIR, f"Aimsun_TSP_Log_{timestamp}.txt")

def log_to_file(message):
    """Write to both Aimsun console and a text file"""
    full_msg = f"{datetime.datetime.now().strftime('%H:%M:%S')} | {message}"
    AKIPrintString(full_msg)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(full_msg + "\n")
    except Exception:
        pass  # don't crash if file write fails
# =============================================================================
# CONTROL MODE SWITCH
# "RL"          — reinforcement learning agent
# "HARMONY"     — harmony search TSP
# "URTSP"       — position-based URTSP (green extension + phase insertion)
# "GROUP_BASED" — demand-responsive signal group control with conflict matrix
# =============================================================================
CONTROL_MODE = "HARMONY"
GROUP_BASED_BUS_PRIORITY = True

from Simulation_Stats import SimulationStats
stats = SimulationStats(CONTROL_MODE)

from intersection_configs import INTERSECTIONS_CONFIG

controllers = {}


# =============================================================================
# URTSP CONFIGURATION  (per-intersection overrides go in INTERSECTIONS_CONFIG)
# These are the defaults used when a key is absent from the config dict.
# =============================================================================
URTSP_DEFAULTS = {
    # Green extension added to nominal bus-phase duration (seconds)
    "GE_extension":            10.0,
    # Phase insertion: minimum inserted duration before exit is checked
    "insertion_min_duration":  10.0,
    # Phase insertion: safety cap (covers full bus phase if exit det. misses)
    "insertion_max_duration":  65.0,
    # One TSP per cycle — reset window (seconds)
    "cycle_length":           135.0,
    # Detection window (metres) — widens call zone upstream to prevent
    # buses skipping zone between 1-second simulation steps (~14 m/s at 50 km/h)
    "detection_window_m":      20.0,
    # PT line IDs to prioritise — empty = all lines eligible
    "priority_pt_line_ids":    [],
}






# ── ADD AT TOP ────────────────────────────────────────────────

BUS_INJECTION_HEADWAY    = 600.0     # inject one bus every 10 min
BUS_ENTRY_SECTION_ID     = 6483      # from your log: call_sections=[6483]
BUS_PT_LINE_ID           = 35346     # from earlier diagnostic








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
    """Immediately halt simulation. Use on critical errors to freeze log."""
    AKIPrintString(f"[STOP] ========== SIMULATION HALTED ==========")
    AKIPrintString(f"[STOP] Reason: {reason}")
    AKIPrintString(f"[STOP] =========================================")
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

        AKIPrintString(f"===== OD DEMAND {label} =====")
        AKIPrintString(f"  vt=0 (ALL types) : {totals.get(0, 0):.1f}")
        for vt in range(1, n_types + 1):
            AKIPrintString(f"  vt={vt}            : {totals.get(vt, 0):.1f}")
        AKIPrintString(f"  centroids={len(self.centroids)}")









# ── ADD THIS CONSTANT AT TOP OF FILE ──────────────────────────────────────
BUS_FREQUENCY_MULTIPLIER = 25        # 2 = double buses, 3 = triple, etc.
TARGET_PT_LINE_IDS       = []       # [] = all lines, or e.g. [101, 102]

# ── ADD THIS FUNCTION ─────────────────────────────────────────────────────

def _get_bus_type_pos():
    """
    Find bus vehicle type position by iterating all vehicle types.
    Safe to call from AAPILoad unlike ANGConnGetObjectIdByType.
    """
    nb_types = AKIVehGetNbVehTypes()
    AKIPrintString(f"[DEMAND] Total vehicle types: {nb_types}")

    for pos in range(1, nb_types + 1):
        name = AKIVehGetVehTypeName(pos)
        # AKIVehGetVehTypeName returns an Aimsun string — convert it
        try:
            name_str = AKIConvertToAsciiString(name, True).lower()
        except Exception:
            name_str = str(name).lower()
        AKIPrintString(f"[DEMAND]   type pos={pos} name='{name_str}'")
        if "bus" in name_str:
            return pos

    return -1


BUS_TYPE_POS = 1    # confirmed from INIT log: bus_type_pos=1 (internal position)
CAR_TYPE_POS = 2    # confirmed from INIT log: car_type_pos=2 (internal position)





class GroupBasedController:

    # State constants
    IDLE       = "IDLE"
    GREEN      = "GREEN"
    INTERGREEN = "INTERGREEN"

    def __init__(self, junction_id: int, gb_config: dict, stats_ref=None):
        self.junction_id = junction_id
        self._stats      = stats_ref   # SimulationStats reference for TSP event recording

        self.conflict_matrix  = self._load_conflict_matrix(gb_config["conflict_matrix_csv"])
        self.all_sg           = list(gb_config["sg_list"])
        self.min_green        = dict(gb_config["min_green"])
        self.max_green        = dict(gb_config["max_green"])
        self.sections         = list(gb_config["sections"])
        self.bus_det          = list(gb_config.get("bus_det", []))
        self.bus_sg           = gb_config.get("bus_sg", None)
        self.intergreen_dur   = float(gb_config.get("intergreen_duration",   4.0))
        self.starvation_thresh= float(gb_config.get("starvation_threshold", 4000.0))
        self.max_extension    = float(gb_config.get("max_extension",         15.0))

        # State machine
        self.state          = self.IDLE
        self.sg_list        = []              # currently green SG positions
        self.non_activated  = set(self.all_sg)
        self.lower_time     = {}
        self.upper_time     = {}
        self.intergreen_end = 0.0

        # Bus priority
        self.bus_request       = None         # SG position waiting for service
        self.extension_used    = 0.0          # cumulative extension granted
        self.prev_bus_presence = {det: 0 for det in self.bus_det}

        # Starvation tracking (incremented per step when SG has demand but is red)
        self.wait_time = {sg: 0.0 for sg in self.all_sg}

        AKIPrintString(
            f"[GB] Junction {junction_id} | "
            f"SGs={self.all_sg} | bus_sg={self.bus_sg} | "
            f"intergreen={self.intergreen_dur}s | "
            f"starvation={self.starvation_thresh}s | "
            f"max_ext={self.max_extension}s"
        )

    # =========================================================================
    # MAIN STEP
    # =========================================================================

    def step(self, time: float, timeSta: float):
        """Called every simulation step from IntersectionController.update()."""
        queue = self._compute_queue()

        if self.state != self.INTERGREEN:
            self._detect_bus(time)

        self._update_wait_times(queue)

        if self.state == self.IDLE:
            if self.bus_request:
                self._activate_for_bus(time, timeSta)
                self.bus_request = None
            else:
                self._build_new_phase(time, timeSta, queue)
            return

        if self.state == self.GREEN:
            self._handle_bus_logic(time)
            self._check_termination(time, queue)
            self._update_time_bounds(time)
            self._apply_signals(time, timeSta)
            return

        if self.state == self.INTERGREEN:
            if time >= self.intergreen_end:
                self.state = self.IDLE
                queue = self._compute_queue()
                self._build_new_phase(time, timeSta, queue)
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

            AKIPrintString(
                f"[GB] Conflict matrix loaded from {csv_path} "
                f"({len(matrix)} signal groups)"
            )
        except Exception as e:
            AKIPrintString(f"[GB] ERROR loading conflict matrix {csv_path}: {e}")
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
            counts      = self._section_queue(sec_id, lane_groups)
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

    def _detect_bus(self, time: float):
        """Rising-edge presence detection on configured bus detectors."""
        for det in self.bus_det:
            current = AKIDetGetPresenceCyclebyId(det, 1)
            if current == 1 and self.prev_bus_presence[det] == 0:
                if self.bus_sg and self.bus_request is None:
                    self.bus_request = self.bus_sg
                    AKIPrintString(
                        f"[GB] t={time:.1f} jct={self.junction_id} "
                        f"Bus detected det={det} → requesting SG {self.bus_sg}"
                    )
                    if self._stats:
                        self._stats.record_tsp_event(self.junction_id, 'detection')
            self.prev_bus_presence[det] = current

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

    def _build_new_phase(self, time: float, timeSta: float, queue: dict):
        """Select highest-demand (or starved) SG and expand with compatible partners."""
        if not self.non_activated:
            self.non_activated = set(self.all_sg)

        demand = {
            sg: queue.get(sg, 0)
            for sg in self.non_activated
            if queue.get(sg, 0) > 0
        }
        if not demand:
            return

        starved = [
            sg for sg, wt in self.wait_time.items()
            if wt >= self.starvation_thresh and sg in self.non_activated
        ]

        if starved:
            first = max(starved, key=lambda x: queue.get(x, 0))
            AKIPrintString(
                f"[GB] t={time:.1f} jct={self.junction_id} "
                f"Starved SG {first} selected (wait={self.wait_time[first]:.0f}s)"
            )
        else:
            first = max(demand, key=demand.get)

        self.sg_list = [first]
        self._expand_phase(queue)

        for sg in self.sg_list:
            self.non_activated.discard(sg)
            self.lower_time[sg] = time + self.min_green.get(sg, 6.0)
            self.upper_time[sg] = time + self.max_green.get(sg, 40.0)

        AKIPrintString(
            f"[GB] t={time:.1f} jct={self.junction_id} "
            f"New phase: SGs={sorted(self.sg_list)}"
        )
        self._apply_signals(time, timeSta)
        self.state = self.GREEN

    def _expand_phase(self, queue: dict):
        """Greedily add compatible SGs with demand to the current phase."""
        candidates = set()
        for active_sg in self.sg_list:
            row = self.conflict_matrix.get(active_sg, {})
            for sg in self.non_activated:
                if sg not in self.sg_list and row.get(sg, 1) == 0:
                    candidates.add(sg)

        while candidates:
            candidates = {sg for sg in candidates if queue.get(sg, 0) > 0}
            if not candidates:
                break
            next_sg = max(candidates, key=lambda x: queue.get(x, 0))
            self.sg_list.append(next_sg)
            # Remove candidates that conflict with the newly added SG
            next_row = self.conflict_matrix.get(next_sg, {})
            candidates = {
                c for c in candidates
                if next_row.get(c, 1) == 0 and c != next_sg
            }

    def _get_compatible(self, active_list: list) -> list:
        """Return all SG positions compatible with every SG in active_list."""
        compatible = set(self.all_sg)
        for sg in active_list:
            row = self.conflict_matrix.get(sg, {})
            compatible &= {i for i in self.all_sg if row.get(i, 1) == 0}
        return list(compatible)

    # =========================================================================
    # BUS PRIORITY LOGIC
    # =========================================================================

    def _handle_bus_logic(self, time: float):
        """Apply green extension, phase addition, or queue bus for next phase."""
        if not self.bus_request:
            return
        bus_sg = self.bus_request

        # 1. Already green → extend up to max_extension
        if bus_sg in self.sg_list:
            if self.extension_used < self.max_extension:
                self.upper_time[bus_sg] = self.upper_time.get(bus_sg, time) + 1.0
                self.extension_used += 1.0
                AKIPrintString(
                    f"[GB] t={time:.1f} jct={self.junction_id} "
                    f"Extending SG {bus_sg} (+1s, total={self.extension_used:.0f}s)"
                )
                if self._stats and self.extension_used == 1.0:
                    # Record extension once per grant (not every 1s tick)
                    self._stats.record_tsp_event(self.junction_id, 'extension')
            else:
                self.bus_request = None   # extension cap reached — release request
            return

        # 2. Compatible with current phase → add immediately
        compatible = self._get_compatible(self.sg_list)
        if bus_sg in compatible:
            self.sg_list.append(bus_sg)
            self.lower_time[bus_sg] = time + self.min_green.get(bus_sg, 6.0)
            self.upper_time[bus_sg] = time + self.max_green.get(bus_sg, 40.0)
            AKIPrintString(
                f"[GB] t={time:.1f} jct={self.junction_id} "
                f"Added bus SG {bus_sg} to current phase"
            )
            self.bus_request = None
            return

        # 3. Incompatible — keep request; check_termination will force early end
        AKIPrintString(
            f"[GB] t={time:.1f} jct={self.junction_id} "
            f"Bus SG {bus_sg} incompatible with current phase — queued for next"
        )

    def _activate_for_bus(self, time: float, timeSta: float):
        """Start a new phase specifically for a waiting bus request."""
        bus_sg = self.bus_request
        if not bus_sg:
            return

        # Find the best compatible partner from non_activated
        partner = None
        for sg in sorted(self.non_activated):
            if sg != bus_sg and self.conflict_matrix.get(bus_sg, {}).get(sg, 1) == 0:
                partner = sg
                break

        self.sg_list = [bus_sg] if partner is None else [bus_sg, partner]

        for sg in self.sg_list:
            self.non_activated.discard(sg)
            self.lower_time[sg] = time + self.min_green.get(sg, 6.0)
            self.upper_time[sg] = time + self.max_green.get(sg, 40.0)

        self.state = self.GREEN
        AKIPrintString(
            f"[GB] t={time:.1f} jct={self.junction_id} "
            f"Bus priority phase activated: SGs={sorted(self.sg_list)}"
        )
        if self._stats:
            self._stats.record_tsp_event(self.junction_id, 'insertion')
        self._apply_signals(time, timeSta)

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
                    AKIPrintString(
                        f"[GB] t={time:.1f} jct={self.junction_id} "
                        f"Bus SG {self.bus_request} forcing early termination"
                    )
                    terminate = True

        if terminate:
            AKIPrintString(
                f"[GB] t={time:.1f} jct={self.junction_id} "
                f"Terminating phase SGs={sorted(self.sg_list)}"
            )
            self._force_intergreen(time)

    # =========================================================================
    # INTERGREEN (all-red gap)
    # =========================================================================

    def _force_intergreen(self, time: float):
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
            AKIPrintString(
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
            AKIPrintString(
                f"[GB] WARNING jct={self.junction_id} control type={ctrl_type} "
                f"(expected 2=External) — signal change skipped"
            )
            return

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
        
        self.current_phase = 1
        self.stats   = stats
        self.CarOcc  = config['CarOcc']
        self.BusOcc  = config['BusOcc']
        self.id      = config["IntersectionID"]

        self.BusPhase         = config.get("BusPhase",2)
        self.BusPhaseDuration = config["BusPhaseDuration"]
        self.BusDet           = config["BusDet"]
        self.UpDetList        = config["UpDetList"]
        self.SignalGroupIDList = config["SignalGroupIDList"]
        self.PhaseIndex       = config["PhaseIndex"]
        self.VehLength        = config.get("VehLength",4.5)
        self.DetLength        = config["DetLength"]
        self.JamDensity       = config["JamDensity"]
        self.SaturationDensity= config["SaturationDensity"]
        self.SaturationFlow   = config["SaturationFlow"]
        self.GE_lower_bound   = config["GE_lower_bound"]
        self.GE_upper_bound   = config["GE_upper_bound"]
        self.BP_lower_bound   = config["BP_lower_bound"]
        self.BP_upper_bound   = config["BP_upper_bound"]
        self.DetDistance      = config["DetDistance"]
        self.max_iterations   = config["max_iterations"]
        self.harmony_memory_size = config["harmony_memory_size"]
        self.hmcr             = config["hmcr"]
        self.par              = config["par"]
        self.NumberOfLanes    = config["NumberOfLanes"]

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
        self._urtsp_bus_phase_nominal  = -1.0
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
        self.incoming_sections  = self._derive_sections_from_detectors()
        self.phase_list         = []

        num_phases = ECIGetNumberPhases(self.id)
        self.phase_list = list(range(1, num_phases + 1))

        car_id = ANGConnGetObjectIdByType(
            AKIConvertFromAsciiString("Car"),
            AKIConvertFromAsciiString("GKVehicle"), False)
        bus_id = ANGConnGetObjectIdByType(
            AKIConvertFromAsciiString("Bus"),
            AKIConvertFromAsciiString("GKVehicle"), False)
        self.car_type_pos = AKIVehGetVehTypeInternalPosition(car_id)
        self.bus_type_pos = AKIVehGetVehTypeInternalPosition(bus_id)
        

        # fallback to hardcoded if lookup fails
        if self.car_type_pos <= 0:
            self.car_type_pos = config.get('CAR_TYPE_POS', CAR_TYPE_POS)
        if self.bus_type_pos <= 0:
            self.bus_type_pos = config.get('BUS_TYPE_POS', BUS_TYPE_POS)

        AKIPrintString(f"[INIT] Inter {self.id} | car_type_pos={self.car_type_pos} bus_type_pos={self.bus_type_pos}")
        self.print_config_summary()
        AKIPrintString(f"[INIT] Phase list: {self.phase_list}")

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
                AKIPrintString(f"[RL] Agent loaded for intersection {self.id}")
            except Exception as e:
                AKIPrintString(f"[RL] WARNING: Could not load RL agent: {e}")

        # ── GROUP_BASED sub-controller ────────────────────────────────
        self.gb = None
        if CONTROL_MODE == "GROUP_BASED":
            gb_config = config.get("GroupBasedConfig")
            if gb_config and gb_config.get("sg_list"):
                self.gb = GroupBasedController(self.id, gb_config, stats_ref=stats)
            else:
                AKIPrintString(
                    f"[GB] WARNING: intersection {self.id} has no valid "
                    f"GroupBasedConfig — GROUP_BASED mode disabled for this intersection"
                )

        AKIPrintString(f"[URTSP] Intersection {self.id} ready | "
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
                AKIPrintString(f"[URTSP] WARNING: call det {det_id} not found")
                continue
            self._urtsp_call_geometry[det_id] = (
                props.IdSection, props.InitialPosition, props.FinalPosition)
            AKIPrintString(f"[URTSP] call det={det_id} "
                           f"section={props.IdSection} "
                           f"pos=[{props.InitialPosition:.1f},{props.FinalPosition:.1f}]m")

        for det_id in self.urtsp_exit_det_ids:
            props = AKIDetGetPropertiesDetectorById(det_id)
            if props.report < 0:
                AKIPrintString(f"[URTSP] WARNING: exit det {det_id} not found")
                continue
            self._urtsp_exit_geometry[det_id] = (
                props.IdSection, props.InitialPosition, props.FinalPosition)
            AKIPrintString(f"[URTSP] exit det={det_id} "
                           f"section={props.IdSection} "
                           f"pos=[{props.InitialPosition:.1f},{props.FinalPosition:.1f}]m")

        # read nominal bus-phase duration from background plan
        self._urtsp_bus_phase_nominal = GetPhaseDuration(
            self.id, self.BusPhase, 0.0)
        AKIPrintString(f"[URTSP] bus phase nominal = {self._urtsp_bus_phase_nominal:.1f}s")

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
                    AKIPrintString(
                        f"[URTSP] SKIP veh={veh_id} line={line_id} "
                        f"pos={pos:.1f}m reason=tsp_active(flag={self._urtsp_flag})")
                    self._urtsp_served_veh_ids.add(veh_id)
                elif self._urtsp_granted_this_cycle:
                    AKIPrintString(
                        f"[URTSP] SKIP veh={veh_id} line={line_id} "
                        f"pos={pos:.1f}m reason=already_granted_this_cycle")
                    self._urtsp_served_veh_ids.add(veh_id)
                else:
                    AKIPrintString(
                        f"[URTSP] BUS IN ZONE | veh={veh_id} line={line_id} "
                        f"sec={sec_id} pos={pos:.1f}m zone=[{detect_ini:.1f},{detect_fin:.1f}]m")
                    return veh_id, line_id, det_id, pos
        return -1, -1, -1, -1.0

    def _check_urtsp_exit(self, veh_id, pt_vehicles):
        """Return True if veh_id is in any exit detector zone."""
        w = self.urtsp_detection_window
        for _, (sec_id, ini_pos, fin_pos) in self._urtsp_exit_geometry.items():
            detect_ini = max(0.0, fin_pos - w)
            detect_fin = fin_pos
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
                AKIPrintString(
                    f"[URTSP] DIAG t={time:.0f}s inter={self.id} "
                    f"det={det_id} sec={sec_id} "
                    f"veh_on_section={n} pt_vehicles={pt_count}")

        current_phase  = ECIGetCurrentPhase(self.id)
        phase_start    = ECIGetStartingTimePhase(self.id)
        phase_elapsed  = time - phase_start
        phase_duration = GetPhaseDuration(self.id, current_phase, timeSta)

        pt_vehicles = self._get_pt_vehicles()

        # ── per-cycle grant reset ─────────────────────────────────────
        if self._urtsp_granted_this_cycle and time >= self._urtsp_cycle_reset_time:
            AKIPrintString(f"[URTSP] cycle grant reset at t={time:.1f}s")
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
                AKIPrintString(f"[URTSP] EXTENSION ENDED | t={time:.1f}s "
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
                AKIPrintString(
                    f"[URTSP] INSERTION ENDED | t={time:.1f}s | reason={reason} "
                    f"duration={insertion_elapsed:.1f}s | "
                    f"restoring phase={self._urtsp_prev_phase} elapsed={restore_elapsed:.1f}s")
                ECIChangeDirectPhase(self.id, self._urtsp_prev_phase,
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
        AKIPrintString(
            f"[URTSP] DETECTED | t={time:.1f}s | veh={veh_id} line={line_id} "
            f"det={det_id} pos={pos:.1f}m | phase={current_phase} "
            f"elapsed={phase_elapsed:.1f}s dur={phase_duration:.1f}s rem={remaining:.1f}s")

        # ── Strategy 1: GREEN EXTENSION ───────────────────────────────
        if current_phase == self.BusPhase:
            new_dur = self._urtsp_bus_phase_nominal + self.urtsp_ge_extension
            AKIPrintString(
                f"[URTSP] GREEN EXTENSION | new_dur={new_dur:.1f}s "
                f"(nominal={self._urtsp_bus_phase_nominal:.1f}s "
                f"+ {self.urtsp_ge_extension:.0f}s)")
            ECIChangeTimingPhase(self.id, current_phase, new_dur, timeSta)
            self._urtsp_active_veh_id = veh_id
            self._urtsp_flag          = 1
            self._urtsp_n_extensions += 1
            self.highlight_bus(veh_id)   # ✅ ADD THIS
            self.stats.record_tsp_event(self.id, 'extension')

        # ── Strategy 2: PHASE INSERTION ───────────────────────────────
        else:
            AKIPrintString(
                f"[URTSP] PHASE INSERTION | inserting phase={self.BusPhase} "
                f"interrupted phase={current_phase} at {phase_elapsed:.1f}s")
            self._urtsp_prev_phase         = current_phase
            self._urtsp_prev_phase_elapsed = phase_elapsed
            self._urtsp_insertion_start    = time
            self._urtsp_active_veh_id      = veh_id
            ECIChangeDirectPhase(self.id, self.BusPhase,
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
        n_phases = len(self.UpDetList)
        n_lanes  = self.NumberOfLanes

        self.BusJoinQueueTime      = np.zeros((n_phases, n_lanes))
        self.BusStoplineTime       = np.zeros((n_phases, n_lanes))
        self.BusPhaseMinDuration   = np.zeros((n_phases, n_lanes))
        self.UpDetCountList        = np.zeros((n_phases, n_lanes))
        self.UpDetOccList          = np.zeros((n_phases, n_lanes))
        self.UpAveOccList          = np.zeros((n_phases, n_lanes))
        self.RedStartTimeList      = np.zeros((n_phases, n_lanes))
        self.GreenStartTimeList    = np.zeros((n_phases, n_lanes))
        self.RedDurationList       = np.zeros((n_phases, n_lanes))
        self.GreenDurationList     = np.zeros((n_phases, n_lanes))
        self.UpFlowList            = np.zeros((n_phases, n_lanes))
        self.UpDenList             = np.zeros((n_phases, n_lanes))
        self.ShockwaveSpeed1List   = np.zeros((n_phases, n_lanes))
        self.ShockwaveSpeed2List   = np.zeros((n_phases, n_lanes))
        self.ShockwaveSpeed3List   = np.zeros((n_phases, n_lanes))
        self.ShockwaveSpeed4List   = np.zeros((n_phases, n_lanes))
        self.MaxQueueLength        = np.zeros((n_phases, n_lanes))
        self.MaxQueueLengthTime    = np.zeros((n_phases, n_lanes))
        self.MinQueueLength        = np.zeros((n_phases, n_lanes))
        self.MinQueueLengthTime    = np.zeros((n_phases, n_lanes))
        self.QueueDissTime         = np.zeros((n_phases, n_lanes))
        self.HSQueueDissTime       = np.zeros((n_phases, n_lanes))
        self.NextRedStartTime      = np.zeros((n_phases, n_lanes))
        self.BusPresence           = np.zeros((1, len(self.BusDet)))
        self.BusSpeed              = np.zeros((1, len(self.BusDet)))
        self.TSPStrategy           = 0
        self.BusPhaseEndTime       = 1e9   # sentinel — never accidentally True
        self.previous_phase        = ECIGetCurrentPhase(self.id)
        self.phase_start_time      = AKIGetCurrentSimulationTime()
        self.HSRedStartTimeList    = np.zeros((n_phases, n_lanes))
        self.HSRedDurationList     = np.zeros((n_phases, n_lanes))
        self.HSGreenStartTimeList  = np.zeros((n_phases, n_lanes))
        self.HSGreenDurationList   = np.zeros((n_phases, n_lanes))
        self.HSNextRedStartTime    = np.zeros((n_phases, n_lanes))
        self.HSUpFlowList          = np.zeros((n_phases, n_lanes))
        self.HSUpDenList           = np.zeros((n_phases, n_lanes))
        self.HSShockwaveSpeed1List = np.zeros((n_phases, n_lanes))
        self.HSShockwaveSpeed3List = np.zeros((n_phases, n_lanes))
        self.HSMaxQueueLength      = np.zeros((n_phases, n_lanes))
        self.HSMaxQueueLengthTime  = np.zeros((n_phases, n_lanes))
        self.HSMinQueueLength      = np.zeros((n_phases, n_lanes))
        self.BusDelay              = np.zeros((n_phases, n_lanes))
        self.OtherDelay            = np.zeros((n_phases, n_lanes))
        self.TotalVeh              = np.zeros((n_phases, n_lanes))
        self.TimeToTerminateBusPhase = 1e9   # sentinel — never accidentally True
        self.step_delay            = 0.0

        # ── Validate PhaseIndex against UpDetList shape ───────────────────
        n_rows = len(self.UpDetList)
        bad = {ph: idx for ph, idx in self.PhaseIndex.items() if idx >= n_rows}
        if bad:
            log_to_file(
                f"[INIT] WARNING inter={self.id} PhaseIndex entries point beyond "
                f"UpDetList rows (n_rows={n_rows}): {bad}  — will cause IndexError")
        log_to_file(
            f"[INIT] inter={self.id} arrays shape=({n_rows}, {n_lanes}) "
            f"PhaseIndex={self.PhaseIndex} BusDet={self.BusDet} "
            f"BusPhase={self.BusPhase} BusPhaseDuration={self.BusPhaseDuration}")
        AKIPrintString(f"Intersection {self.id} initialized | shape=({n_rows},{n_lanes})")

    def _derive_sections_from_detectors(self):
        sections = set()
        for phase in self.UpDetList:
            for det_id in phase:
                det_info = AKIDetGetPropertiesDetectorById(det_id)
                sections.add(det_info.IdSection)
        return list(sections)

    def _sample_side_sections(self, time):
        """
        Virtual detector for side street sections — no physical detector needed.

        Scans live vehicles on each SideSection via AKIVehStateGetNbVehiclesSection
        and computes upstream flow + density using the LWR triangular model,
        identical to how update_queue_model handles main approach phases.

        Results are stored in self.SideUpFlowList / SideUpDenList /
        SideShockwaveSpeed1 / SideShockwaveSpeed3 — one entry per side section —
        and consumed by GE_Objective_Function and BP_Objective_Function to include
        side-street delay in the harmony-search objective.
        """
        side_secs = self.config.get('SideSections', [])
        if not side_secs:
            return

        if not hasattr(self, 'SideUpFlowList'):
            n = len(side_secs)
            self.SideUpFlowList      = np.zeros(n)
            self.SideUpDenList       = np.zeros(n)
            self.SideShockwaveSpeed1 = np.zeros(n)
            self.SideShockwaveSpeed3 = np.zeros(n)
            self._side_red_start     = np.full(n, time)
            self._side_last_phase    = ECIGetCurrentPhase(self.id)

        current_phase = ECIGetCurrentPhase(self.id)
        if current_phase != self._side_last_phase:
            self._side_red_start  = np.full(len(side_secs), time)
            self._side_last_phase = current_phase

        for idx, sec_id in enumerate(side_secs):
            try:
                n_veh = AKIVehStateGetNbVehiclesSection(sec_id, False)
                if n_veh < 0:
                    n_veh = 0
            except Exception:
                n_veh = 0

            det_dist_m = 50.0
            try:
                sec_length_m = AKIInfNetGetSectionLength(sec_id)
                if sec_length_m > 0:
                    det_dist_m = sec_length_m
            except Exception:
                pass

            density = min(
                (n_veh / (det_dist_m / 1000.0)) if det_dist_m > 0 else 0.0,
                self.JamDensity)
            flow = density * self.SaturationFlow / max(self.SaturationDensity, 1.0)

            self.SideUpFlowList[idx]      = flow
            self.SideUpDenList[idx]       = density
            self.SideShockwaveSpeed1[idx] = ShockwaveSpeed1(
                flow, self.JamDensity, density)
            self.SideShockwaveSpeed3[idx] = ShockwaveSpeed3(
                self.SaturationFlow, flow, self.SaturationDensity, density)

        '''
        log_to_file(
            f"[SIDE_SCAN] inter={self.id} t={time:.0f} "
            f"flow={[round(float(v),1) for v in self.SideUpFlowList]} "
            f"den={[round(float(v),2) for v in self.SideUpDenList]}")
            '''

    def build_state(self):
        state = []
        for sec in self.incoming_sections:
            stat = AKIEstGetParcialStatisticsSection(
                sec, AKIGetCurrentSimulationTime(), 50)
            state.append(min(stat.count / 50.0, 1.0))

        bus_presence = 1.0 if np.any(self.BusPresence) else 0.0
        state.append(bus_presence)
        state.append(min(np.max(self.BusSpeed) / 20.0, 1.0) if bus_presence else 0.0)

        current_phase = ECIGetCurrentPhase(self.id)
        num_phases    = len(self.UpDetList)
        phase_one_hot = [0.0] * num_phases
        if 1 <= current_phase <= num_phases:
            phase_one_hot[current_phase - 1] = 1.0
        state.extend(phase_one_hot)

        start_time  = ECIGetStartingTimePhase(self.id)
        time_in_phase = AKIGetCurrentSimulationTime() - start_time
        state.append(min(time_in_phase / 60.0, 1.0))

        return np.array(state, dtype=np.float32)

    def collect_detector_data(self):
        for i in range(len(self.UpDetList)):
            for j in range(len(self.UpDetList[i])):
                det_id = self.UpDetList[i][j]
                count = AKIDetGetCounterAggregatedbyId(det_id, 0)
                if count >= 0:   # -1 means detector error/not found — skip
                    self.UpDetCountList[i][j] += count

    def detect_bus(self, time):
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

        # Build det_sec_map: section_id -> (det_index, det_distance_m, det_final_pos)
        det_sec_map = {}
        for i, det_id in enumerate(self.BusDet):
            props = AKIDetGetPropertiesDetectorById(det_id)
            if props.report >= 0:
                sec = props.IdSection
                dist = self.config["DetDistance"][0][i]
                if sec not in det_sec_map or dist > det_sec_map[sec][1]:
                    det_sec_map[sec] = (i, dist, props.FinalPosition)

        if not det_sec_map:
            return

        lookahead = self.urtsp_cycle_length   # accept buses arriving within one cycle

        seen = set()

        # ── Primary: registered PT line vehicles ─────────────────────
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
                            continue
                        i, det_dist, det_fin = det_sec_map[inf.idSection]
                        speed_ms  = max(inf.CurrentSpeed / 3.6, 0.5)
                        remaining = max(0.0, det_dist - max(0.0, inf.CurrentPos - det_fin))
                        eta = remaining / speed_ms
                        if eta <= lookahead:
                            if self.BusPresence[0][i] == 0 or eta < self._bus_eta.get(i, (None, 1e9))[1]:
                                self.BusPresence[0][i]    = 1
                                self.BusSpeed[0][i]       = speed_ms
                                self.last_detected_bus_id = veh_id
                                self._bus_eta[i]          = (veh_id, eta, remaining, speed_ms)
                    except Exception:
                        continue
        except Exception:
            pass

        # ── Fallback: direct section scan for injected buses ─────────
        for sec, (i, det_dist, det_fin) in det_sec_map.items():
            try:
                n = AKIVehStateGetNbVehiclesSection(sec, True)
                for vi in range(n):
                    inf = AKIVehStateGetVehicleInfSection(sec, vi)
                    if inf.idVeh in seen or inf.type != self.bus_type_pos:
                        continue
                    seen.add(inf.idVeh)
                    speed_ms  = max(inf.CurrentSpeed / 3.6, 0.5)
                    remaining = max(0.0, det_dist - max(0.0, inf.CurrentPos - det_fin))
                    eta = remaining / speed_ms
                    if eta <= lookahead:
                        if self.BusPresence[0][i] == 0 or eta < self._bus_eta.get(i, (None, 1e9))[1]:
                            self.BusPresence[0][i]    = 1
                            self.BusSpeed[0][i]       = speed_ms
                            self.last_detected_bus_id = inf.idVeh
                            self._bus_eta[i]          = (inf.idVeh, eta, remaining, speed_ms)
            except Exception:
                continue

    def update_queue_model(self, time):
        for i in range(len(self.UpDetList)):
            for j in range(len(self.UpDetList[i])):
                red_duration = time - self.RedStartTimeList[i][j]
                if red_duration > 0:
                    self.RedDurationList[i][j] = red_duration

                    self.UpFlowList[i][j] = (
                        self.UpDetCountList[i][j] * 3600 / red_duration)
                    # LWR: k = q / v_f = q * k_sat / q_sat  (v_f = q_sat/k_sat)
                    self.UpDenList[i][j] = (
                        self.UpFlowList[i][j] * self.SaturationDensity / self.SaturationFlow
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
        AKIPrintString(f"[TSP EVENT] ▶ START | {strategy_name} | veh={veh_id} | inter={self.id}")

    def reset_bus_color(self, veh_id):
        AKIPrintString(f"[TSP EVENT] ■ END   | veh={veh_id} | inter={self.id}")

    def enforce_starvation_protection(self, time, timeSta, acycle):
        MAX_RED       = 1200000
        current_phase = ECIGetCurrentPhase(self.id)
        for phase_id in self.phase_list:
            if phase_id == current_phase or phase_id not in self.PhaseIndex:
                continue
            phase_index = self.PhaseIndex[phase_id]
            red_time    = time - self.RedStartTimeList[phase_index][0]
            if red_time > MAX_RED:
                AKIPrintString(f"STARVATION: phase {phase_id} red for {red_time:.0f}s")
                ECIChangeDirectPhase(self.id, phase_id, timeSta, time, acycle, 0)
                return

    def apply_action(self, action, timeSta, time, acycle):
        current_phase = ECIGetCurrentPhase(self.id)
        start         = ECIGetStartingTimePhase(self.id)
        time_in_phase = time - start
        MIN_GREEN     = 5
        MAX_GREEN     = 60
        if time_in_phase < MIN_GREEN:
            return
        if time_in_phase >= MAX_GREEN:
            next_phase = (current_phase % len(self.phase_list)) + 1
            AKIPrintString(f"MAX_GREEN override → phase {next_phase}")
            ECIChangeDirectPhase(self.id, next_phase, timeSta, time, acycle, 0)
            return
        if action < len(self.phase_list):
            target_phase = self.phase_list[action]
            if target_phase != current_phase:
                ECIChangeDirectPhase(self.id, target_phase, timeSta, time, acycle, 0)

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
        """Original detector-based TSP (kept for reference / regression testing)."""
        currentPhase  = ECIGetCurrentPhase(self.id)
        phaseStart    = ECIGetStartingTimePhase(self.id)
        phaseElapsed  = time - phaseStart
        phaseDuration = GetPhaseDuration(self.id, currentPhase, timeSta)
        busTypePos    = self.bus_type_pos

        busCallActive = any(
            AKIDetGetCounterCyclebyId(det, busTypePos) > 0
            for det in self.BusDet)
        busExitActive = busCallActive  # reuse same detectors as exit proxy

        if busCallActive and currentPhase == self.BusPhase and \
                phaseDuration == self.BusPhaseDuration:
            remaining = phaseDuration - phaseElapsed
            ECIDisableEvents(self.id)
            ECIChangeTimingPhase(self.id, currentPhase, phaseDuration + 10, timeSta)
            self.TimeToTerminateBusPhase = time + remaining + 10
            self.flag = 1
            return

        if busCallActive and currentPhase != self.BusPhase:
            self.previous_phase      = currentPhase
            self.previous_phase_time = phaseElapsed
            ECIChangeDirectPhase(self.id, self.BusPhase, timeSta, time, acycle, 0)
            self.flag = 2
            return

        if self.flag == 1 and time >= self.TimeToTerminateBusPhase:
            ECIChangeTimingPhase(self.id, currentPhase, phaseDuration - 10, timeSta)
            ECIEnableEventsActivatingPhase(self.id, self.BusPhase + 1, 0.0, time)
            self.flag = 0
            return

        if self.flag == 2 and busExitActive and self.previous_phase and self.previous_phase > 0:
            ECIChangeDirectPhase(self.id, self.previous_phase, timeSta, time, acycle,
                                 self.previous_phase_time)
            self.flag = 0

    def restore_phase_if_needed(self, time, timeSta, acycle):
        current_phase = ECIGetCurrentPhase(self.id)

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
                AKIPrintString(
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
                AKIPrintString(
                    f"[HARMONY] Insertion ended | t={time:.1f}s "
                    f"reason={'phase_change' if phase_ended else 'timeout'} "
                    f"restored_phase={self.previous_phase} inter={self.id}")

    def collect_delay(self, time):
        self.step_delay = 0.0
        weighted_delay  = 0.0

        inter_state = self.stats._inter.get(self.id, {})
        main_secs   = set(inter_state.get('main_sections', []))
        side_secs   = set(inter_state.get('side_sections', []))

        all_delay_secs = set(self.incoming_sections) | main_secs | side_secs

        for sec in all_delay_secs:
            is_main = (sec in main_secs) if (main_secs or side_secs) else True

            car_stat = AKIEstGetParcialStatisticsSection(
                sec, time, self.car_type_pos)

            if car_stat.report == 0:
                # Partial stats available (section has a detector)
                car_d    = car_stat.DTa * car_stat.count * self.CarOcc
                bus_stat = AKIEstGetParcialStatisticsSection(
                    sec, time, self.bus_type_pos)
                bus_d    = bus_stat.DTa * bus_stat.count * self.BusOcc
                bus_cnt  = bus_stat.count
                car_cnt  = car_stat.count

            elif sec in side_secs:
                # Side sections have no detectors — fall back to cumulative stats
                # and track the per-step delta ourselves.
                try:
                    car_cum = AKIEstGetCurrentStatisticsSection(
                        sec, self.car_type_pos)
                    bus_cum = AKIEstGetCurrentStatisticsSection(
                        sec, self.bus_type_pos)

                    if not hasattr(self, '_side_sec_prev'):
                        self._side_sec_prev = {}

                    prev_car = self._side_sec_prev.get((sec, 'car'), (0.0, 0))
                    prev_bus = self._side_sec_prev.get((sec, 'bus'), (0.0, 0))

                    car_cnt = max(0, (car_cum.count if car_cum.report == 0 else 0)
                                  - prev_car[1])
                    bus_cnt = max(0, (bus_cum.count if bus_cum.report == 0 else 0)
                                  - prev_bus[1])

                    car_dta = car_cum.DTa if (car_cum.report == 0 and car_cum.DTa > 0) else 0.0
                    bus_dta = bus_cum.DTa if (bus_cum.report == 0 and bus_cum.DTa > 0) else 0.0

                    car_d = car_dta * car_cnt * self.CarOcc
                    bus_d = bus_dta * bus_cnt * self.BusOcc

                    self._side_sec_prev[(sec, 'car')] = (
                        car_dta,
                        car_cum.count if car_cum.report == 0 else prev_car[1])
                    self._side_sec_prev[(sec, 'bus')] = (
                        bus_dta,
                        bus_cum.count if bus_cum.report == 0 else prev_bus[1])

                except Exception:
                    car_d = bus_d = 0.0
                    car_cnt = bus_cnt = 0
            else:
                continue   # main section with no partial stats — skip

            sec_delay = car_d + bus_d
            weighted_delay += sec_delay

            self.stats.add_section_delay_split(
                intersection_id   = self.id,
                weighted_delay    = sec_delay,
                bus_vehicle_count = bus_cnt,
                car_vehicle_count = car_cnt,
                is_main           = is_main,
                bus_delay         = bus_d,
                car_delay         = car_d,
            )

        self.step_delay += weighted_delay

    # =========================================================================
    # MAIN UPDATE  — dispatches to correct control mode
    # =========================================================================

    def update(self, time, timeSta, acycle):
        # ── Periodic heartbeat to logfile (every 60s, not every step) ─────
        if CONTROL_MODE == "HARMONY":
            _t60 = int(time) // 60
            if _t60 != getattr(self, '_last_log_min', -1):
                self._last_log_min = _t60
                current_phase = ECIGetCurrentPhase(self.id)
                log_to_file(
                    f"[HEARTBEAT] t={time:.0f}s inter={self.id} "
                    f"phase={current_phase} flag={self.flag} "
                    f"TSPStrategy={self.TSPStrategy} "
                    f"TSPActiveTime={self.TSPActiveTime:.0f} "
                    f"BusPresence={self.BusPresence[0].tolist()} "
                    f"BusSpeed={[round(v,2) for v in self.BusSpeed[0].tolist()]} "
                    f"MaxQ={[round(v,1) for v in self.MaxQueueLength[0].tolist()]} "
                    f"UpFlow={[round(v,1) for v in self.UpFlowList[0].tolist()]}"
                )



        # GROUP_BASED has its own complete state machine — bypass all
        # phase-based tracking and starvation protection (handled internally).
        if CONTROL_MODE == "GROUP_BASED":
            if self.gb is not None:
                self.gb.step(time, timeSta)
            return

        # track phase transitions for queue model
        current_phase = ECIGetCurrentPhase(self.id)
        if current_phase >= 0 and current_phase != self.previous_phase:
            if current_phase in self.PhaseIndex:
                idx = self.PhaseIndex[current_phase]
                self.GreenStartTimeList[idx][:] = time
                dur = GetPhaseDuration(self.id, current_phase, timeSta)
                self.NextRedStartTime[idx][:]   = time + dur
            if self.previous_phase in self.PhaseIndex:
                idx = self.PhaseIndex[self.previous_phase]
                self.RedStartTimeList[idx][:] = time
                # Reset per-red-phase detector accumulators so UpFlow is
                # computed only over the current red, not the whole simulation.
                self.UpDetCountList[idx][:] = 0.0
                self.UpAveOccList[idx][:]   = 0.0
            self.previous_phase = current_phase

        self.collect_detector_data()
        self.update_queue_model(time)
        self.detect_bus(time)

        if CONTROL_MODE == "NORMAL":
            self.run_normal(time, timeSta, acycle)

        elif CONTROL_MODE == "HARMONY":
            tsp_active = self.check_bus_priority(time, timeSta, acycle)
            self.restore_phase_if_needed(time, timeSta, acycle)

        elif CONTROL_MODE == "RL":
            tsp_active = self.check_bus_priority(time, timeSta, acycle)
            if not tsp_active:
                self.run_rl(time, timeSta, acycle)
            self.restore_phase_if_needed(time, timeSta, acycle)

        elif CONTROL_MODE == "URTSP":
            # Position-based URTSP — no globals, no detector presence API
            self.run_urtsp(time, timeSta, acycle)


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
        current_phase = ECIGetCurrentPhase(self.id)

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

        for i in range(len(self.BusDet)):
            bus_speed = self.BusSpeed[0][i]
            if bus_speed <= 0:
                continue

            if current_phase == self.BusPhase:
                red_start        = self.RedStartTimeList[0][i]
                _ps = ECIGetStartingTimePhase(self.id)
                _pd = GetPhaseDuration(self.id, current_phase, timeSta)
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
                    remain = GetPhaseDuration(self.id, current_phase, timeSta) \
                             - (time - ECIGetStartingTimePhase(self.id))
                    ECIChangeTimingPhase(self.id, current_phase,
                                         self.BusPhaseDuration + float(opt_GE), timeSta)
                    self.TimeToTerminateBusPhase = time + remain + opt_GE
                    self.TSPStrategy = 1
                    self.flag        = 1
                    self.TSPActiveTime = time + float(opt_GE) + 30
                    self._tsp_cycle_grant_until = time + self.config.get('CycleTime', 135)
                    AKIPrintString(
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
                _ps_now        = ECIGetStartingTimePhase(self.id)
                _elapsed       = max(0.0, time - _ps_now)
                _rem_current   = max(0.0,
                    GetPhaseDuration(self.id, current_phase, timeSta) - _elapsed)

                # Walk phase sequence from current to BusPhase
                _time_to_bp = _rem_current
                try:
                    _ci  = self.phase_list.index(current_phase)
                    _bi  = self.phase_list.index(self.BusPhase)
                    _n   = len(self.phase_list)
                    _steps = (_bi - _ci) % _n  # phases between current+1 and BusPhase
                    for _k in range(1, _steps):
                        _ph = self.phase_list[(_ci + _k) % _n]
                        _time_to_bp += GetPhaseDuration(self.id, _ph, timeSta)
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
                    AKIPrintString(
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
                AKIPrintString(
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
            log_to_file(f"    Group {g}: {dets} | DetDistance: {self.DetDistance[g]}")
        log_to_file(f"  MainSections: {self.config.get('MainSections', [])}")
        log_to_file(f"  SideSections: {self.config.get('SideSections', [])}")
        log_to_file(f"  NumberOfLanes: {self.NumberOfLanes}")
        log_to_file(f"  Control mode: {CONTROL_MODE}")
        log_to_file("=" * 80)

    def GE_Objective_Function(self, GE, time):
        # ── Phase 0 (Bus phase) ───────────────────────────────────────────────
        for i in range(len(self.BusDet)):
            self.HSMaxQueueLengthTime[0][i] = self.MaxQueueLengthTime[0][i]
            self.HSGreenStartTimeList[0][i] = self.GreenStartTimeList[0][i]
            self.HSMaxQueueLength[0][i]     = self.MaxQueueLength[0][i]
            self.HSRedDurationList[0][i]    = self.RedDurationList[0][i]
            self.HSQueueDissTime[0][i]      = self.QueueDissTime[0][i]
            self.HSMinQueueLength[0][i]     = self.MinQueueLength[0][i]
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
                self.OtherDelay[0][i] = (
                    (self.HSMaxQueueLength[0][i] * self.HSRedDurationList[0][i] / 2)
                    * (self.JamDensity - self.UpDenList[0][i]) / 1000
                    + ((self.HSQueueDissTime[0][i] - self.HSGreenStartTimeList[0][i])
                       * self.HSMaxQueueLength[0][i] / 2)
                    * (self.SaturationDensity - self.UpDenList[0][i]) / 1000)
            else:
                self.HSMinQueueLength[0][i] = (
                    (self.HSMaxQueueLength[0][i] / abs(self.ShockwaveSpeed3List[0][i])
                     + self.HSMaxQueueLengthTime[0][i]
                     - self.NextRedStartTime[0][i] - GE) /
                    (1 / abs(self.ShockwaveSpeed3List[0][i]) +
                     1 / abs(self.ShockwaveSpeed4List[0][i])))
                self.OtherDelay[0][i] = (
                    (self.HSMaxQueueLength[0][i] * self.HSRedDurationList[0][i] / 2)
                    * (self.JamDensity - self.UpDenList[0][i]) / 1000
                    + ((self.HSQueueDissTime[0][i] - self.HSGreenStartTimeList[0][i])
                       * self.HSMaxQueueLength[0][i]
                       - (self.HSQueueDissTime[0][i] - self.RedStartTimeList[0][i] - GE)
                       * self.HSMinQueueLength[0][i]) / 2
                    * (self.SaturationDensity - self.UpDenList[0][i]) / 1000)

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

                green_since = max(time - self.GreenStartTimeList[i][j], 1.0)
                self.HSUpFlowList[i][j]  = self.UpDetCountList[i][j] * 3600 / green_since
                self.HSUpDenList[i][j]   = (
                    self.HSUpFlowList[i][j] * self.SaturationDensity / self.SaturationFlow
                    if self.SaturationFlow > 0 else 0.0)
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
                if abs(denom) < 1e-6 or abs(w3) < 1e-6:
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
                    self.OtherDelay[i][j] = (
                        abs(w1) * abs(w2) * rd / (abs(w2) - abs(w1)) / 2
                        * (self.JamDensity - self.HSUpDenList[i][j]) / 1000
                        + (self.HSQueueDissTime[i][j] - self.HSGreenStartTimeList[i][j])
                        * self.HSMaxQueueLength[i][j] / 2
                        * (self.SaturationDensity - self.HSUpDenList[i][j]))
                else:
                    if abs(w3) > 1e-6 and abs(w4) > 1e-6:
                        self.HSMinQueueLength[i][j] = (
                            (self.HSMaxQueueLength[i][j] / abs(w3)
                             + self.HSMaxQueueLengthTime[i][j] - (nrs + GE))
                            / (1.0 / abs(w3) + 1.0 / abs(w4)))
                    self.OtherDelay[i][j] = (
                        abs(w1) * abs(w2) * rd / (abs(w2) - abs(w1)) / 2
                        * (self.JamDensity - self.HSUpDenList[i][j]) / 1000
                        + ((self.HSQueueDissTime[i][j] - self.HSGreenStartTimeList[i][j])
                           * self.HSMaxQueueLength[i][j]
                           - (self.HSQueueDissTime[i][j] - nrs - GE)
                           * self.HSMinQueueLength[i][j]) / 2
                        * (self.SaturationDensity - self.HSUpDenList[i][j]) / 1000)

        # ── Side-street delay penalty ─────────────────────────────────────────
        # GE holds each side section at red for an extra GE seconds.
        # Triangle model: growth phase (w1 speed) + discharge phase (w3 speed).
        side_other_delay = 0.0
        side_total_veh   = 0.0
        if hasattr(self, 'SideUpFlowList'):
            w2_side = ShockwaveSpeed2(
                self.SaturationFlow, self.SaturationDensity, self.JamDensity)
            for idx in range(len(self.SideUpFlowList)):
                q_s = float(self.SideUpFlowList[idx])
                k_s = float(self.SideUpDenList[idx])
                if q_s < 1.0:
                    continue
                w1_s = float(self.SideShockwaveSpeed1[idx])
                w3_s = float(self.SideShockwaveSpeed3[idx])
                denom_s = abs(w2_side) - abs(w1_s)
                if abs(denom_s) < 1e-6 or abs(w3_s) < 1e-6:
                    continue
                side_max_q = abs(w2_side) * abs(w1_s) * GE / denom_s
                side_diss  = side_max_q / abs(w3_s)
                side_delay_veh_s = (
                    side_max_q * GE / 2
                    * (self.JamDensity - k_s) / 1000
                    + side_diss * side_max_q / 2
                    * (self.SaturationDensity - k_s) / 1000)
                side_other_delay += side_delay_veh_s * self.CarOcc
                side_total_veh   += q_s * GE / 3600

        bus_delay_total   = float(np.sum(self.BusDelay))
        other_delay_total = float(np.sum(self.OtherDelay)) + side_other_delay
        total_veh         = float(np.sum(self.TotalVeh))   + side_total_veh

        AveragePassengerDelay = (
            bus_delay_total * self.BusOcc +
            other_delay_total * self.CarOcc
        ) / max(total_veh * self.CarOcc + self.BusOcc, 1e-6)

        log_to_file(
            f"[HS GE_OBJ] inter={self.id} GE={GE:.2f}s "
            f"bus_delay={bus_delay_total:.2f} "
            f"other_delay={float(np.sum(self.OtherDelay)):.2f} "
            f"side_delay={side_other_delay:.2f} "
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

            self.HSUpFlowList[0][i]          = self.UpDetCountList[0][i] * 3600 / red_dur
            self.HSUpDenList[0][i]           = (
                self.HSUpFlowList[0][i] * self.SaturationDensity / self.SaturationFlow
                if self.SaturationFlow > 0 else 0.0)
            self.HSShockwaveSpeed1List[0][i] = ShockwaveSpeed1(
                self.HSUpFlowList[0][i], self.JamDensity, self.HSUpDenList[0][i])
            self.HSShockwaveSpeed3List[0][i] = ShockwaveSpeed3(
                self.SaturationFlow, self.HSUpFlowList[0][i],
                self.SaturationDensity, self.UpDenList[0][i])

            log_to_file(f"[HS BP_OBJ] inter={self.id} i={i} "
                        f"HSUpFlow={self.HSUpFlowList[0][i]:.1f} "
                        f"HSUpDen={self.HSUpDenList[0][i]:.4f} "
                        f"w1={self.HSShockwaveSpeed1List[0][i]:.4f} "
                        f"w2={self.ShockwaveSpeed2List[0][i]:.4f} "
                        f"w3={self.HSShockwaveSpeed3List[0][i]:.4f}")

            self.TotalVeh[0][i] = self.HSUpFlowList[0][i] * (red_dur + GreenTime) / 3600

            w1 = self.HSShockwaveSpeed1List[0][i]
            w2 = self.ShockwaveSpeed2List[0][i]
            w3 = self.HSShockwaveSpeed3List[0][i]
            w4 = self.ShockwaveSpeed4List[0][i]
            denom = abs(w2) - abs(w1)

            if abs(denom) < 1e-6 or abs(w3) < 1e-6:
                self.BusDelay[0][i]  = 0.0
                self.OtherDelay[0][i] = 0.0
                continue

            # Projected max queue at insertion green start
            self.HSMaxQueueLength[0][i] = (
                abs(w2) * abs(w1) * (time + 5 - self.HSRedStartTimeList[0][i])
                / denom)
            self.HSMaxQueueLengthTime[0][i] = (
                self.HSRedStartTimeList[0][i]
                + abs(w2) * (time + 5 - self.HSRedStartTimeList[0][i]) / denom)

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
                                f"case=no_stop BusStopline={self.BusStoplineTime[0][i]:.1f} "
                                f"MinDur={self.BusPhaseMinDuration[0][i]:.1f}")

                    for k in range(len(self.BusDet)):
                        self.QueueDissTime[0][k] = (
                            self.HSMaxQueueLengthTime[0][k]
                            + self.HSMaxQueueLength[0][k] / abs(w3))
                        green_end = self.HSGreenStartTimeList[0][k] + GreenTime
                        if self.QueueDissTime[0][k] < green_end:
                            self.OtherDelay[0][k] = (
                                self.HSMaxQueueLength[0][k] * self.HSRedDurationList[0][k]
                                / 2 * (self.JamDensity - self.HSUpDenList[0][k]) / 1000
                                + (self.QueueDissTime[0][k]
                                   - self.HSGreenStartTimeList[0][k])
                                * self.HSMaxQueueLength[0][k] / 2
                                * (self.SaturationDensity - self.HSUpDenList[0][k]) / 1000)
                        else:
                            hsmin = 0.0
                            if abs(w3) > 1e-6 and abs(w4) > 1e-6:
                                nrs_k = self.HSNextRedStartTime[0][k]
                                hsmin = (
                                    (self.HSMaxQueueLength[0][k] / abs(w3)
                                     + self.HSMaxQueueLengthTime[0][k] - (nrs_k + GreenTime))
                                    / (1.0 / abs(w3) + 1.0 / abs(w4)))
                            self.HSMinQueueLength[0][k] = hsmin
                            self.OtherDelay[0][k] = (
                                self.HSMaxQueueLength[0][k] * self.HSRedDurationList[0][k]
                                / 2 * (self.JamDensity - self.HSUpDenList[0][k]) / 1000
                                + ((self.QueueDissTime[0][k]
                                    - self.HSGreenStartTimeList[0][k])
                                   * self.HSMaxQueueLength[0][k]
                                   - (self.QueueDissTime[0][k] - green_end)
                                   * self.HSMinQueueLength[0][k]) / 2
                                * (self.SaturationDensity - self.HSUpDenList[0][k]) / 1000)

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
                        self.QueueDissTime[0][k] = (
                            self.HSRedStartTimeList[0][k]
                            + abs(w2) * self.HSRedDurationList[0][k]
                            / (abs(w2) - abs(w1))
                            + abs(w2) * abs(w1) * self.HSRedDurationList[0][k]
                            / ((abs(w2) - abs(w1)) * abs(w3)))
                        green_end = self.HSGreenStartTimeList[0][k] + GreenTime
                        if self.QueueDissTime[0][k] < green_end:
                            self.OtherDelay[0][k] = (
                                (self.HSMaxQueueLength[0][k]
                                 * self.HSRedDurationList[0][k] / 2)
                                * (self.JamDensity - self.HSUpDenList[0][k]) / 1000
                                + ((self.HSQueueDissTime[0][k]
                                    - self.HSGreenStartTimeList[0][k])
                                   * self.HSMaxQueueLength[0][k] / 2)
                                * (self.SaturationDensity - self.HSUpDenList[0][k]) / 1000)
                        else:
                            self.OtherDelay[0][k] = (
                                (self.HSMaxQueueLength[0][k]
                                 * self.HSRedDurationList[0][k] / 2)
                                * (self.JamDensity - self.HSUpDenList[0][k]) / 1000
                                + ((self.HSQueueDissTime[0][k]
                                    - self.HSGreenStartTimeList[0][k])
                                   * self.HSMaxQueueLength[0][k] / 2)
                                * (self.SaturationDensity - self.HSUpDenList[0][k]) / 1000
                                - (self.HSQueueDissTime[0][k] - green_end) / 2
                                * (self.SaturationDensity - self.HSUpDenList[0][k]) / 1000)

        # ── Interrupted phase (OrderToTerminatePhase = previous_phase index) ──
        otp_phase = self.previous_phase  # phase being interrupted
        if otp_phase in self.PhaseIndex:
            otp_idx = self.PhaseIndex[otp_phase]
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
                    self.OtherDelay[otp_idx][j] = (
                        self.HSMaxQueueLength[otp_idx][j]
                        * self.HSRedDurationList[otp_idx][j] / 2
                        * (self.JamDensity - self.UpDenList[otp_idx][j]) / 1000
                        + (q_diss_o - self.HSGreenStartTimeList[otp_idx][j])
                        * self.HSMaxQueueLength[otp_idx][j] / 2
                        * (self.SaturationDensity - self.UpDenList[otp_idx][j]) / 1000)
                else:
                    if abs(w3o) > 1e-6 and abs(w4o) > 1e-6:
                        min_q = (
                            (self.HSMaxQueueLength[otp_idx][j] / abs(w3o)
                             + self.HSMaxQueueLengthTime[otp_idx][j] - nrs_o)
                            / (1.0 / abs(w3o) + 1.0 / abs(w4o)))
                        self.HSMinQueueLength[otp_idx][j] = min_q
                    self.OtherDelay[otp_idx][j] = (
                        self.HSMaxQueueLength[otp_idx][j]
                        * self.HSRedDurationList[otp_idx][j] / 2
                        * (self.JamDensity - self.UpDenList[otp_idx][j]) / 1000
                        + ((q_diss_o - self.HSGreenStartTimeList[otp_idx][j])
                           * self.HSMaxQueueLength[otp_idx][j]
                           - (q_diss_o - nrs_o)
                           * self.HSMinQueueLength[otp_idx][j]) / 2
                        * (self.SaturationDensity - self.UpDenList[otp_idx][j]) / 1000)

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
                self.TotalVeh[i][j]            = (
                    self.HSUpFlowList[i][j]
                    * (self.HSRedDurationList[i][j] + 35) / 3600)

                w1i = self.ShockwaveSpeed1List[i][j]
                w2i = self.ShockwaveSpeed2List[i][j]
                w3i = self.ShockwaveSpeed3List[i][j]
                w4i = self.ShockwaveSpeed4List[i][j]
                rd_i = self.HSRedDurationList[i][j]
                den_i = abs(w2i) - abs(w1i)
                if abs(den_i) < 1e-6 or abs(w3i) < 1e-6:
                    continue

                self.HSMaxQueueLength[i][j] = (
                    abs(w1i) * abs(w2i) * (rd_i) / den_i)
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
                    self.HSMinQueueLength[i][j] = min_qi
                    self.OtherDelay[i][j] = (
                        self.HSMaxQueueLength[i][j] * rd_i / 2
                        * (self.JamDensity - self.UpDenList[i][j]) / 1000
                        + ((q_diss_i - self.HSGreenStartTimeList[i][j])
                           * self.HSMaxQueueLength[i][j]
                           - (q_diss_i - nrs_i) * self.HSMinQueueLength[i][j]) / 2
                        * (self.SaturationDensity - self.UpDenList[i][j]) / 1000)
                else:
                    self.OtherDelay[i][j] = (
                        self.HSMaxQueueLength[i][j] * rd_i / 2
                        * (self.JamDensity - self.UpDenList[i][j]) / 1000
                        + (q_diss_i - self.HSGreenStartTimeList[i][j])
                        * self.HSMaxQueueLength[i][j] / 2
                        * (self.SaturationDensity - self.UpDenList[i][j]) / 1000)

        # ── Side-street delay penalty ─────────────────────────────────────────
        # Phase insertion forces side sections to wait GreenTime + 5s extra.
        side_other_delay_bp = 0.0
        side_total_veh_bp   = 0.0
        extra_red = GreenTime + 5.0
        if hasattr(self, 'SideUpFlowList'):
            w2_side = ShockwaveSpeed2(
                self.SaturationFlow, self.SaturationDensity, self.JamDensity)
            for idx in range(len(self.SideUpFlowList)):
                q_s = float(self.SideUpFlowList[idx])
                k_s = float(self.SideUpDenList[idx])
                if q_s < 1.0:
                    continue
                w1_s = float(self.SideShockwaveSpeed1[idx])
                w3_s = float(self.SideShockwaveSpeed3[idx])
                denom_s = abs(w2_side) - abs(w1_s)
                if abs(denom_s) < 1e-6 or abs(w3_s) < 1e-6:
                    continue
                side_max_q = abs(w2_side) * abs(w1_s) * extra_red / denom_s
                side_diss  = side_max_q / abs(w3_s)
                side_delay_veh_s = (
                    side_max_q * extra_red / 2
                    * (self.JamDensity - k_s) / 1000
                    + side_diss * side_max_q / 2
                    * (self.SaturationDensity - k_s) / 1000)
                side_other_delay_bp += side_delay_veh_s * self.CarOcc
                side_total_veh_bp   += q_s * extra_red / 3600

        bus_delay_total   = float(np.sum(self.BusDelay))
        other_delay_total = float(np.sum(self.OtherDelay)) + side_other_delay_bp
        total_veh         = float(np.sum(self.TotalVeh))   + side_total_veh_bp

        AveragePassengerDelay = (
            bus_delay_total * self.BusOcc +
            other_delay_total * self.CarOcc
        ) / max(total_veh * self.CarOcc + self.BusOcc, 1e-6)

        log_to_file(
            f"[HS BP_OBJ] inter={self.id} GreenTime={GreenTime:.2f}s "
            f"bus_delay={bus_delay_total:.2f} "
            f"other_delay={float(np.sum(self.OtherDelay)):.2f} "
            f"side_delay={side_other_delay_bp:.2f} "
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
    AKIPrintString("=" * 60)
    AKIPrintString(f"[TSP] Script loaded | mode={CONTROL_MODE}")
    AKIPrintString(f"[TSP] Log file → {LOG_FILE}")
    AKIPrintString(f"[TSP] Intersections configured: {list(INTERSECTIONS_CONFIG.keys())}")
    AKIPrintString("=" * 60)
    log_to_file(f"[LOAD] AAPILoad complete | mode={CONTROL_MODE} | "
                f"n_intersections={len(INTERSECTIONS_CONFIG)}")
    return 0


def AAPIInit():
    global controllers
    dm = DemandMonitor()
    dm.print_demand("AAPIInit")
    for inter_id, config in INTERSECTIONS_CONFIG.items():
        try:
            controllers[inter_id] = IntersectionController(config)
            stats.register_intersection(config)
        except Exception as e:
            AKIPrintString(f"[INIT] ERROR creating controller {inter_id}: {e}")
    AKIPrintString(f"[TSP] Control mode: {CONTROL_MODE} | intersections={list(controllers.keys())}")
    return 0


def AAPISimulationReady():
    global controllers
    try:
        stats.finalise_init()
    except Exception as e:
        AKIPrintString(f"[TSP] WARNING: finalise_init failed: {e}")

    # === FORCE JUNCTIONS TO BE EXTERNALLY CONTROLLED ===
    for iid in list(controllers.keys()):
        try:
            # Aimsun Next 26 uses ECISetSignalControlType, not AKISignalSetControl
            # Control type 2 = External (API-controlled), 0 = None, 1 = Fixed-time
            result = ECISetSignalControlType(iid, 2)
            AKIPrintString(f"[CONTROL] Took external control of junction {iid} (result={result})")
        except Exception as e:
            # Fallback: try the older function name in case of version difference
            try:
                AKISignalSetExternalControl(iid)
                AKIPrintString(f"[CONTROL] Took external control of junction {iid} (fallback)")
            except Exception as e2:
                AKIPrintString(f"[CONTROL ERROR] Failed to control junction {iid}: {e} | fallback: {e2}")

    # === REBUILD PHASE LIST NOW THAT JUNCTIONS ARE UNDER CONTROL ===
    for iid, ctrl in controllers.items():
        try:
            num_phases = ECIGetNumberPhases(iid)
            ctrl.phase_list = list(range(1, num_phases + 1))
            AKIPrintString(f"[CONTROL] Junction {iid}: {num_phases} phases → {ctrl.phase_list}")
        except Exception as e:
            AKIPrintString(f"[CONTROL] WARNING: could not get phases for {iid}: {e}")

    # Force vehicle types (your log showed -1)
    for ctrl in controllers.values():
        ctrl.car_type_pos = 2   # from your earlier INIT log
        ctrl.bus_type_pos = 1
    if hasattr(stats, '_car_pos'): stats._car_pos = 2
    if hasattr(stats, '_bus_pos'): stats._bus_pos = 1

    AKIPrintString(f"[TSP] Simulation ready | mode={CONTROL_MODE} | {len(controllers)} intersections under external control")
    return 0


def AAPIManage(time, timeSta, timeTrans, acycle):
    
    return 0


def AAPIPostManage(time, timeSta, timeTrans, acycle):
    try:
        stats.track_bus_positions(time)
    except Exception as e:
        stop_simulation(f"track_bus_positions crashed t={time:.1f}: {e}")
        return 0

    for inter_id, controller in controllers.items():
        try:
            controller.collect_delay(time)
        except Exception as e:
            stop_simulation(f"collect_delay crashed inter={inter_id} t={time:.1f}: {e}")
            return 0
        try:
            controller.update(time, timeSta, acycle)
        except Exception as e:
            stop_simulation(f"update crashed inter={inter_id} t={time:.1f}: {e}")
            return 0
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
