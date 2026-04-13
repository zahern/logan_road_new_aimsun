# Simulation_Stats.py
# =============================================================================
# Integrated SimulationStats — reads everything from INTERSECTIONS_CONFIG
#
# Design goals
# ------------
# 1. ONE stats object shared across all IntersectionController instances.
# 2. Per-intersection breakdown (delay, bus TT, TSP events) using the
#    section IDs and occupancy values already in INTERSECTIONS_CONFIG.
# 3. Bus travel time tracked via PT vehicle position scan (AKIPTVehGetInf)
#    using BusCallDetectors / BusExitDetectors from each intersection config.
# 4. Delay computed from AKIEstGetParcialStatisticsSection each step —
#    lightweight partial stats rather than slow global stats call.
# 5. All KPIs written to CSV at AAPIFinish via save_results().
#
# What goes in INTERSECTIONS_CONFIG to drive this
# ------------------------------------------------
# Required (already present):
#   CarOcc, BusOcc                  — occupancy weights
#   UpDetList                       — upstream detector lists (gives sections)
#
# Optional (add if you want bus TT per intersection):
#   BusCallDetectors : [det_id, ...]   — approach detectors (bus entry)
#   BusExitDetectors : [det_id, ...]   — downstream detectors (bus exit)
#   MainSections     : [sec_id, ...]   — main corridor sections for KPI2
#   SideSections     : [sec_id, ...]   — side street sections for KPI3
#
# If BusCallDetectors absent, falls back to BusDet.
# If MainSections / SideSections absent, derives sections from UpDetList.
# =============================================================================

from AAPI import *
import csv
import json
import math
import os
import numpy as np

# Output folder — resolved relative to this file's directory on startup.
# Falls back to a hardcoded D: path if __file__ is unavailable (e.g., some
# Aimsun versions don't set __file__ for injected scripts).
try:
    DEFAULT_OUTPUT_FOLDER = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'results')
except Exception:
    DEFAULT_OUTPUT_FOLDER = r"D:\Aimsun_Results"


class SimulationStats:
    """
    Single shared stats object for all intersections.

    Instantiate once at module level in intersection_controller.py:
        stats = SimulationStats(CONTROL_MODE)

    Each IntersectionController calls:
        self.stats.register_intersection(config)    ← in __init__
        self.stats.add_section_delay(...)           ← in collect_delay
        self.stats.store_objective_stats(...)       ← in GE/BP objective fns
        self.stats.record_tsp_event(...)            ← optional, in run_urtsp

    At AAPIFinish:
        stats.collect_bus_travel_times()   ← final PT scan
        stats.print_results()
        stats.save_results()
    """

    def __init__(self, tsp_strategy: str = 'None',
                 output_folder: str = DEFAULT_OUTPUT_FOLDER,
                 verbose: bool = True):

        # Prefer run_config.py's CURRENT_STRATEGY over the raw CONTROL_MODE
        # argument — run_config distinguishes GROUP_BASED_FIXED from GROUP_BASED
        # even though both share CONTROL_MODE='GROUP_BASED' in the controller.
        try:
            _cfg_path = os.path.join(os.path.dirname(__file__), 'run_config.py')
            _ns = {}
            with open(_cfg_path, 'r') as _f:
                exec(_f.read(), _ns)
            _rc_strategy = str(_ns.get('CURRENT_STRATEGY', '')).strip()
            if _rc_strategy:
                tsp_strategy = _rc_strategy
        except Exception:
            pass   # run_config absent (manual run) — use the passed-in value

        self.tsp_strategy    = tsp_strategy
        self.output_folder   = output_folder
        self.verbose         = verbose   # when False: suppress all console prints

        # simulation metadata (populated in AAPIInit via finalise_init)
        self.scenario_id     = None
        self.experiment_id   = None
        self.replication_id  = None

        # ── per-intersection state ──────────────────────────────────────────
        # keyed by intersection_id
        self._inter: dict = {}   # see _inter_template() for structure

        # ── global accumulators ────────────────────────────────────────────
        self.sim_total_delay      = 0.0
        self.sim_bus_delay        = 0.0
        self.sim_car_delay        = 0.0
        self.sim_total_vehicles   = 0      # raw vehicle count
        self.sim_total_passengers = 0.0    # occupancy-weighted total
        self.sim_bus_passengers   = 0.0    # bus_count × BusOcc, global sum
        self.sim_car_passengers   = 0.0    # car_count × CarOcc, global sum
        self.sim_truck_delay      = 0.0
        self.sim_truck_passengers = 0.0

        # analytical objective (from harmony search / URTSP objective fn)
        self.obj_bus_delay          = 0.0
        self.obj_other_delay        = 0.0
        self.obj_avg_passenger_delay = 0.0
        self.obj_steps              = 0

        # ── vehicle type positions (resolved in finalise_init) ─────────────
        self._car_pos = -1
        self._bus_pos = -1
        self._truck_pos = -1
        self._car_type_name = ''
        self._bus_type_name = ''
        self._truck_type_name = ''

    # =========================================================================
    # CONSOLE OUTPUT HELPER
    # =========================================================================

    def _print(self, msg: str, force: bool = False):
        """
        Print to Aimsun console only when self.verbose=True or force=True.
        force=True is reserved for critical warnings that must always show.
        """
        if self.verbose or force:
            AKIPrintString(msg)

    # =========================================================================
    # REGISTRATION  (called once per intersection in IntersectionController.__init__)
    # =========================================================================

    def register_intersection(self, config: dict):
        """
        Register an intersection from its config dict.
        Reads section IDs, occupancy, and detector geometry.
        """
        iid = config['IntersectionID']
        if iid in self._inter:
            return   # already registered

        car_occ = float(config.get('CarOcc', 1.5))
        bus_occ = float(config.get('BusOcc', 40.0))
        truck_occ = float(config.get('TruckOcc', car_occ))

        # ── derive sections from UpDetList if not explicit ─────────────────
        up_det_list   = config.get('UpDetList', [])
        all_sections  = self._sections_from_detectors(up_det_list)

        main_sections = list(config.get('MainSections', []))
        side_sections = list(config.get('SideSections', []))

        # Detector-derived sections are main approaches; side streets should
        # come from topology, not an arbitrary split of detector sections.
        if not main_sections and all_sections:
            main_sections = list(all_sections)

        # if side_sections still empty (single detector group covers only the
        # main corridor), derive side-street sections from junction topology
        if main_sections and not side_sections:
            side_sections = self._side_sections_from_topology(iid, main_sections)
            if side_sections:
                self._print(
                    f"[STATS] Auto-derived side_sections={side_sections} "
                    f"for inter={iid} via topology"
                )

        # ── bus detector geometry for travel time tracking ─────────────────
        # call_sections / exit_sections are only needed for bus travel-time
        # tracking.  If bus detectors are absent or unavailable at init time,
        # default to [] and continue — side_sections (topology-derived) and
        # all delay accounting remain fully functional.
        call_sections = []
        exit_sections = []
        try:
            call_det_ids = config.get('BusCallDetectors',
                           config.get('BusDet', [])) or []
            exit_det_ids = config.get('BusExitDetectors', [])

            call_sections = self._sections_from_det_ids(call_det_ids) if call_det_ids else []
            exit_sections = self._sections_from_det_ids(exit_det_ids) if exit_det_ids else []

            # No exit detectors → auto-detect from network topology.
            if not exit_sections:
                exit_sections = self._auto_exit_sections(iid, call_sections)
                if not exit_sections or exit_sections == call_sections:
                    exit_sections = call_sections  # final fallback
        except Exception as _e:
            self._print(
                f"[STATS] WARNING inter={iid}: could not resolve bus detector "
                f"sections ({_e}) — bus TT tracking disabled for this intersection"
            )

        self._inter[iid] = {
            'config':         config,
            'car_occ':        car_occ,
            'bus_occ':        bus_occ,
            'truck_occ':      truck_occ,
            'all_sections':   all_sections,
            'main_sections':  main_sections,
            'side_sections':  side_sections,
            'side_sections_resolved': bool(side_sections),
            'call_sections':  call_sections,
            'exit_sections':  exit_sections,
            # per-step delay accumulators (pax·s, occupancy-weighted)
            'delay_total':    0.0,
            'delay_main':     0.0,
            'delay_side':     0.0,
            'delay_bus':      0.0,
            'delay_car':      0.0,
            'delay_truck':    0.0,
            'traj_bus_delay': 0.0,
            'traj_bus_veh_passages': 0,
            'traj_bus_passengers': 0.0,
            'bus_min_tt_s':   None,
            # vehicle-passage counts (sum of per-step exit counts — used as
            # denominator for avg delay; NOT a headcount of distinct vehicles)
            'vehicles':       0,
            'bus_veh_passages': 0,   # bus exits across all steps
            'car_veh_passages': 0,   # car exits across all steps
            'truck_veh_passages': 0, # truck exits across all steps
            # occupancy-weighted passage totals (for avg delay denominator)
            'passengers':     0.0,
            'bus_passengers': 0.0,
            'car_passengers': 0.0,
            'truck_passengers': 0.0,
            # distinct-vehicle headcount sets (populated by track_bus/car_positions)
            # these give a true count of unique vehicles seen, not passage counts
            '_seen_bus_ids':  set(),
            '_seen_car_ids':  set(),
            '_seen_truck_ids': set(),
            # bus travel time tracking
            'bus_entry':      {},   # {veh_id: entry_time}
            'bus_on_window':  set(),
            'bus_trips':      [],   # [(entry_t, exit_t, tt_s)]
            # car distinct-vehicle window (mirrors bus tracking)
            'car_entry':      {},
            'car_on_window':  set(),
            'truck_entry':    {},
            'truck_on_window': set(),
            # TSP event counters
            'n_detections':   0,
            'n_extensions':   0,
            'n_insertions':   0,
            'n_exit_clears':  0,
            'n_cap_clears':   0,
            # HARMONY skip counters — detected bus but no action taken
            'n_skipped_ge':   0,   # harmony returned GE ≤ 0.5 s (not worth extending)
            'n_skipped_ins':  0,   # harmony returned BP ≤ 0.5 s (not worth inserting)
            'n_detected_no_action': 0,   # NORMAL mode: bus detected, no TSP applied
        }
        self._print(
            f"[STATS] Registered intersection {iid} | "
            f"CarOcc={car_occ} BusOcc={bus_occ} TruckOcc={truck_occ} | "
            f"main_sections={main_sections} | "
            f"side_sections={side_sections} | "
            f"call_sections={call_sections} | "
            f"exit_sections={exit_sections}"
        )

    # =========================================================================
    # INIT FINALISATION  (call after Aimsun is ready)
    # =========================================================================

    def finalise_init(self):
        """
        Resolve vehicle type positions and simulation metadata.
        Call this from AAPISimulationReady() or AAPIInit() after controllers
        are created.
        """
        try:
            self.scenario_id    = ANGConnGetScenarioId()
            self.experiment_id  = ANGConnGetExperimentId()
            self.replication_id = ANGConnGetReplicationId()
        except Exception:
            pass

        try:
            nb = AKIVehGetNbVehTypes()
            # AKIConvertToAsciiString takes 2 args in most Aimsun versions;
            # fall back to str() if it fails so we never crash here.
            for pos in range(1, nb + 1):   # Aimsun positions are 1-based
                raw = AKIVehGetVehTypeName(pos)
                try:
                    name = AKIConvertToAsciiString(raw, True).lower()
                except Exception:
                    try:
                        name = str(raw).lower()
                    except Exception:
                        name = ''
                self._print(f"[STATS] veh type pos={pos} name='{name}'")
                if self._car_pos < 0 and any(
                        x in name for x in ('car', 'pv', 'private')):
                    self._car_pos = pos
                    self._car_type_name = name
                if self._bus_pos < 0 and any(
                        x in name for x in ('bus', 'transit', 'pt')):
                    self._bus_pos = pos
                    self._bus_type_name = name
                if self._truck_pos < 0 and 'truck' in name:
                    self._truck_pos = pos
                    self._truck_type_name = name
        except Exception as e:
            self._print(f"[STATS] WARNING finalise_init veh-type scan: {e}")

        def _sanitize_type_pos(pos):
            try:
                pos = int(pos)
            except Exception:
                return -1
            return pos if pos > 0 else -1

        def _fallback_type_pos(type_name: str):
            try:
                obj_id = ANGConnGetObjectIdByType(
                    AKIConvertFromAsciiString(type_name),
                    AKIConvertFromAsciiString("GKVehicle"),
                    False)
                if obj_id > 0:
                    return _sanitize_type_pos(AKIVehGetVehTypeInternalPosition(obj_id))
            except Exception:
                return -1
            return -1

        if self._car_pos <= 0:
            self._car_pos = _fallback_type_pos("Car")
            if self._car_pos > 0 and not self._car_type_name:
                self._car_type_name = "car(fallback)"
        if self._bus_pos <= 0:
            self._bus_pos = _fallback_type_pos("Bus")
            if self._bus_pos > 0 and not self._bus_type_name:
                self._bus_type_name = "bus(fallback)"
        if self._truck_pos <= 0:
            self._truck_pos = _fallback_type_pos("Truck")
            if self._truck_pos > 0 and not self._truck_type_name:
                self._truck_type_name = "truck(fallback)"

        # PT vehicles are the strongest source of truth for the real bus class.
        try:
            pt_type_counts = {}
            n_lines = AKIPTGetNumberLines()
            for li in range(n_lines):
                line_id = AKIPTGetIdLine(li)
                for vi in range(AKIGetNbVehiclesFollowingPTLine(line_id)):
                    veh_id = AKIGetVehicleFollowingPTLine(line_id, vi)
                    inf = AKIPTVehGetInf(veh_id)
                    vtype = int(getattr(inf, 'type', -1) or -1)
                    if getattr(inf, 'report', -1) >= 0 and vtype > 0:
                        pt_type_counts[vtype] = pt_type_counts.get(vtype, 0) + 1
            if pt_type_counts:
                pt_bus_pos = max(pt_type_counts, key=pt_type_counts.get)
                self._bus_pos = _sanitize_type_pos(pt_bus_pos)
                if not self._bus_type_name:
                    self._bus_type_name = f"pt_inferred_{pt_bus_pos}"
                if self._car_pos <= 0 or self._car_pos == self._bus_pos:
                    for pos in range(1, AKIVehGetNbVehTypes() + 1):
                        if pos != self._bus_pos and pos != self._truck_pos:
                            self._car_pos = pos
                            if not self._car_type_name:
                                self._car_type_name = f"fallback_nonbus_{pos}"
                            break
        except Exception as e:
            self._print(f"[STATS] WARNING finalise_init PT-bus infer: {e}")

        self._car_pos = _sanitize_type_pos(self._car_pos)
        self._bus_pos = _sanitize_type_pos(self._bus_pos)
        self._truck_pos = _sanitize_type_pos(self._truck_pos)

        # Re-resolve main sections from detectors now that Aimsun is fully
        # ready (AAPISimulationReady). AKIDetGetPropertiesDetectorById is not
        # reliable during AAPIInit, so main_sections may be [] for all
        # intersections after register_intersection. Fix them here first,
        # then derive side sections from topology.
        self._re_resolve_main_sections()
        self._resolve_side_sections()

        self._print(
            f"[STATS] finalise_init | "
            f"car_pos={self._car_pos}('{self._car_type_name}') "
            f"bus_pos={self._bus_pos}('{self._bus_type_name}') "
            f"truck_pos={self._truck_pos}('{self._truck_type_name}') | "
            f"scenario={self.scenario_id} exp={self.experiment_id} "
            f"rep={self.replication_id}"
        )

    # =========================================================================
    # DELAY ACCUMULATION  (called every step from collect_delay)
    # =========================================================================

    def add_section_delay(self, intersection_id: int,
                          weighted_delay: float,
                          bus_vehicle_count: int,
                          car_vehicle_count: int,
                          truck_vehicle_count: int = 0,
                          bus_delay: float = 0.0,
                          car_delay: float = 0.0,
                          truck_delay: float = 0.0):
        """
        Record delay for one step from one intersection.

        Parameters
        ----------
        intersection_id   : which intersection this came from
        weighted_delay    : occupancy-weighted delay (passengers × seconds)
        bus_vehicle_count : bus vehicles that EXITED a section this step
                            (from AKIEstGetParcialStatisticsSection.count)
        car_vehicle_count : car vehicles that exited a section this step
        bus_delay         : bus component of weighted_delay (pax·s)
        car_delay         : car component of weighted_delay (pax·s)

        NOTE on passenger counting
        --------------------------
        AKIEstGetParcialStatisticsSection.count gives the number of vehicles
        that *exited* the section in the last 1-second step.  Summing this
        over all steps gives total vehicle-passages (correct delay denominator),
        NOT the headcount of distinct vehicles.  Distinct-vehicle headcounts
        are maintained separately via track_bus_positions / track_car_positions
        and stored in '_seen_bus_ids' / '_seen_car_ids'.
        """
        self.sim_total_delay    += weighted_delay
        self.sim_bus_delay      += bus_delay
        self.sim_car_delay      += car_delay
        self.sim_truck_delay    += truck_delay
        self.sim_total_vehicles += bus_vehicle_count + car_vehicle_count + truck_vehicle_count

        if intersection_id in self._inter:
            d       = self._inter[intersection_id]
            bus_occ = d['bus_occ']
            car_occ = d['car_occ']
            truck_occ = d.get('truck_occ', car_occ)
            # occupancy-weighted passage sums — used as delay denominators
            bp = bus_vehicle_count * bus_occ
            cp = car_vehicle_count * car_occ
            tp = truck_vehicle_count * truck_occ

            self.sim_total_passengers += bp + cp + tp
            self.sim_bus_passengers   += bp
            self.sim_car_passengers   += cp
            self.sim_truck_passengers += tp

            d['delay_total']      += weighted_delay
            d['delay_bus']        += bus_delay
            d['delay_car']        += car_delay
            d['delay_truck']      += truck_delay
            d['vehicles']         += bus_vehicle_count + car_vehicle_count + truck_vehicle_count
            d['bus_veh_passages'] += bus_vehicle_count
            d['car_veh_passages'] += car_vehicle_count
            d['truck_veh_passages'] += truck_vehicle_count
            d['passengers']       += bp + cp + tp
            d['bus_passengers']   += bp
            d['car_passengers']   += cp
            d['truck_passengers'] += tp

    def add_section_delay_split(self, intersection_id: int,
                                weighted_delay: float,
                                bus_vehicle_count: int,
                                car_vehicle_count: int,
                                is_main: bool,
                                truck_vehicle_count: int = 0,
                                bus_delay: float = 0.0,
                                car_delay: float = 0.0,
                                truck_delay: float = 0.0):
        """
        Same as add_section_delay but also tracks main vs side breakdown.
        Call this from collect_delay if you want KPI 2 vs KPI 3 split.
        """
        self.add_section_delay(intersection_id, weighted_delay,
                               bus_vehicle_count, car_vehicle_count, truck_vehicle_count,
                               bus_delay, car_delay, truck_delay)
        if intersection_id in self._inter:
            d = self._inter[intersection_id]
            if is_main:
                d['delay_main'] += weighted_delay
            else:
                d['delay_side'] += weighted_delay

    # =========================================================================
    # BUS TRAVEL TIME TRACKING  (call from AAPIPostManage)
    # =========================================================================

    
    def track_bus_positions(self, time: float):
        call_sec_to_inter = {}
        exit_sec_to_inter = {}
        for iid, d in self._inter.items():
            for sec in d.get('call_sections', []):
                call_sec_to_inter.setdefault(sec, []).append(iid)
            for sec in d.get('exit_sections', []):
                exit_sec_to_inter.setdefault(sec, []).append(iid)

        # Also scan all approach sections for car headcount
        approach_sec_to_inter = {}
        for iid, d in self._inter.items():
            for sec in d.get('all_sections', []):
                approach_sec_to_inter.setdefault(sec, []).append(iid)

        all_sections = (
            set(call_sec_to_inter)
            | set(exit_sec_to_inter)
            | set(approach_sec_to_inter)
        )
        if not all_sections:
            return

        currently_on_call   = {}
        currently_on_window = {}
        currently_on_approach = {}   # for car headcount
        currently_on_truck_approach = {}
        seen_veh_ids        = set()
        pt_bus_ids = set()
        observed_pt_types = set()
        try:
            for li in range(AKIPTGetNumberLines()):
                line_id = AKIPTGetIdLine(li)
                for vi in range(AKIGetNbVehiclesFollowingPTLine(line_id)):
                    veh_id = AKIGetVehicleFollowingPTLine(line_id, vi)
                    pt_bus_ids.add(veh_id)
                    try:
                        inf = AKIPTVehGetInf(veh_id)
                        vtype = int(getattr(inf, 'type', -1) or -1)
                        if getattr(inf, 'report', -1) >= 0 and vtype > 0:
                            observed_pt_types.add(vtype)
                    except Exception:
                        pass
        except Exception:
            pass

        if observed_pt_types:
            inferred_bus_pos = sorted(observed_pt_types)[0]
            if inferred_bus_pos > 0 and self._bus_pos != inferred_bus_pos:
                self._bus_pos = inferred_bus_pos
                if not self._bus_type_name:
                    self._bus_type_name = f"pt_runtime_{inferred_bus_pos}"
            if self._car_pos <= 0 or self._car_pos == self._bus_pos:
                for pos in range(1, AKIVehGetNbVehTypes() + 1):
                    if pos != self._bus_pos and pos != self._truck_pos:
                        self._car_pos = pos
                        break

        BUS_INTERNAL_POS = getattr(self, '_bus_pos', -1)
        CAR_INTERNAL_POS = getattr(self, '_car_pos', -1)
        TRUCK_INTERNAL_POS = getattr(self, '_truck_pos', -1)

        # Single pass over all relevant sections
        for sec in all_sections:
            try:
                n = AKIVehStateGetNbVehiclesSection(sec, True)
                for i in range(n):
                    inf = AKIVehStateGetVehicleInfSection(sec, i)
                    veh_id = inf.idVeh
                    if veh_id in seen_veh_ids:
                        continue
                    seen_veh_ids.add(veh_id)

                    is_bus = (
                        veh_id in pt_bus_ids
                        or (BUS_INTERNAL_POS > 0 and inf.type == BUS_INTERNAL_POS)
                    )
                    is_truck = (TRUCK_INTERNAL_POS > 0 and inf.type == TRUCK_INTERNAL_POS)
                    is_car = (
                        (CAR_INTERNAL_POS > 0 and inf.type == CAR_INTERNAL_POS)
                        or (not is_bus and not is_truck)
                    )

                    if is_bus:
                        for iid in call_sec_to_inter.get(sec, []):
                            currently_on_call.setdefault(iid, set()).add(veh_id)
                            currently_on_window.setdefault(iid, set()).add(veh_id)
                        for iid in exit_sec_to_inter.get(sec, []):
                            currently_on_window.setdefault(iid, set()).add(veh_id)

                    elif is_car:
                        for iid in approach_sec_to_inter.get(sec, []):
                            currently_on_approach.setdefault(iid, set()).add(veh_id)
                    elif is_truck:
                        for iid in approach_sec_to_inter.get(sec, []):
                            currently_on_truck_approach.setdefault(iid, set()).add(veh_id)
            except Exception:
                continue

        # Update per-intersection state
        for iid, d in self._inter.items():
            on_call     = currently_on_call.get(iid, set())
            on_window   = currently_on_window.get(iid, set())
            on_approach = currently_on_approach.get(iid, set())
            on_truck_approach = currently_on_truck_approach.get(iid, set())

            # ── Bus travel time tracking ──────────────────────────────────────
            for veh_id in on_call:
                if veh_id not in d['bus_entry']:
                    d['bus_entry'][veh_id] = time
                d['_seen_bus_ids'].add(veh_id)

            just_cleared = d['bus_on_window'] - on_window
            for veh_id in just_cleared:
                if veh_id in d['bus_entry']:
                    entry_t  = d['bus_entry'].pop(veh_id)
                    travel_t = time - entry_t
                    if 5.0 < travel_t < 600.0:
                        d['bus_trips'].append((entry_t, time, travel_t))
                        min_tt = d.get('bus_min_tt_s')
                        if min_tt is None or travel_t < min_tt:
                            min_tt = travel_t
                            d['bus_min_tt_s'] = travel_t
                        bus_delay_s = max(travel_t - min_tt, 0.0)
                        bus_occ = d.get('bus_occ', 0.0)
                        d['traj_bus_veh_passages'] = d.get('traj_bus_veh_passages', 0) + 1
                        d['traj_bus_passengers'] = d.get('traj_bus_passengers', 0.0) + bus_occ
                        d['traj_bus_delay'] = d.get('traj_bus_delay', 0.0) + bus_delay_s * bus_occ

            d['bus_on_window'] = on_window

            # ── Car distinct-vehicle headcount ────────────────────────────────
            # Mirrors bus TT logic but without timing — we just need to know
            # when a car leaves the window (approach sections) so we can count
            # it once as a distinct vehicle.
            for veh_id in on_approach:
                if veh_id not in d['car_entry']:
                    d['car_entry'][veh_id] = time

            just_cleared_cars = d['car_on_window'] - on_approach
            for veh_id in just_cleared_cars:
                if veh_id in d['car_entry']:
                    d['car_entry'].pop(veh_id)
                    d['_seen_car_ids'].add(veh_id)

            d['car_on_window'] = on_approach

            for veh_id in on_truck_approach:
                if veh_id not in d.setdefault('truck_entry', {}):
                    d['truck_entry'][veh_id] = time

            just_cleared_trucks = d.setdefault('truck_on_window', set()) - on_truck_approach
            for veh_id in just_cleared_trucks:
                if veh_id in d['truck_entry']:
                    d['truck_entry'].pop(veh_id)
                    d['_seen_truck_ids'].add(veh_id)

            d['truck_on_window'] = on_truck_approach

            # Extra safety: count buses this step for logging
            d.setdefault('buses_this_step', 0)
            d['buses_this_step'] = len(on_call)
    
    #==========================
    # ANALYTICAL OBJECTIVE  (called from harmony search objective functions)
    # =========================================================================

    def store_objective_stats(self, bus_delay: float,
                              other_delay: float,
                              avg_pass_delay: float):
        """
        Record the analytical objective function values from the harmony
        search. Called from GE_Objective_Function / BP_Objective_Function.
        These are model-estimated delays, not simulation-measured delays.
        """
        try:
            bus_delay = float(bus_delay)
        except (TypeError, ValueError):
            bus_delay = 0.0
        try:
            other_delay = float(other_delay)
        except (TypeError, ValueError):
            other_delay = 0.0
        try:
            avg_pass_delay = float(avg_pass_delay)
        except (TypeError, ValueError):
            avg_pass_delay = 0.0

        if not math.isfinite(bus_delay):
            bus_delay = 0.0
        if not math.isfinite(other_delay):
            other_delay = 0.0
        if not math.isfinite(avg_pass_delay):
            avg_pass_delay = 0.0

        bus_delay = max(bus_delay, 0.0)
        other_delay = max(other_delay, 0.0)
        avg_pass_delay = max(avg_pass_delay, 0.0)

        self.obj_bus_delay           = bus_delay
        self.obj_other_delay         = other_delay
        self.obj_avg_passenger_delay += avg_pass_delay   # accumulate — divided by obj_steps in _global_kpis
        self.last_avg_passenger_delay = avg_pass_delay
        self.obj_steps              += 1

    # =========================================================================
    # TSP EVENT RECORDING  (optional — call from run_urtsp)
    # =========================================================================

    def record_tsp_event(self, intersection_id: int, event_type: str):
        """
        Record a TSP event for reporting.
        event_type: 'detection' | 'extension' | 'insertion' |
                    'exit_clear' | 'cap_clear'
        """
        if intersection_id not in self._inter:
            return
        d = self._inter[intersection_id]
        key = {
            'detection':  'n_detections',
            'extension':  'n_extensions',
            'insertion':  'n_insertions',
            'exit_clear': 'n_exit_clears',
            'cap_clear':  'n_cap_clears',
        }.get(event_type)
        if key:
            d[key] += 1

    def record_tsp_skip(self, intersection_id: int, skip_type: str):
        """
        Record a case where a bus was detected but no TSP action was applied.
        skip_type: 'ge_trivial'  — GE opt ≤ 0.5 s (harmony said don't extend)
                   'ins_trivial' — BP opt ≤ 0.5 s (harmony said don't insert)
                   'no_action'   — NORMAL mode: bus seen, no TSP available
        """
        if intersection_id not in self._inter:
            return
        d = self._inter[intersection_id]
        key = {
            'ge_trivial':  'n_skipped_ge',
            'ins_trivial': 'n_skipped_ins',
            'no_action':   'n_detected_no_action',
        }.get(skip_type)
        if key:
            d[key] += 1

    def record_pt_bus_detection(self, intersection_id: int, veh_id: int, time: float):
        """
        Called by the controller whenever a PT bus is newly detected approaching
        this intersection (i.e. BusPresence just went 0→1 for this vehicle).

        This supplements section-based bus travel time tracking for intersections
        where buses travel on transit-link sections that are invisible to
        AKIVehStateGetVehicleInfSection (those sections return report<0).

        The bus is recorded as 'entering' the intersection window.  When the same
        vehicle is later detected again at the NEXT call (or never re-detected),
        the trip is closed and travel time recorded as the gap between successive
        detections.  This gives a coarse but valid TT per intersection passage.
        """
        if intersection_id not in self._inter:
            return
        d = self._inter[intersection_id]

        # Mark bus as seen (distinct headcount)
        d['_seen_bus_ids'].add(veh_id)

        # If this vehicle hasn't been seen yet at this intersection, start its timer
        pt_entry = d.setdefault('_pt_bus_entry', {})
        if veh_id not in pt_entry:
            pt_entry[veh_id] = time
        else:
            # Already seen — close previous trip and start a new one
            entry_t  = pt_entry[veh_id]
            travel_t = time - entry_t
            # Accept trips between 5 s and 600 s as valid corridor traversals
            if 5.0 < travel_t < 600.0:
                d['bus_trips'].append((entry_t, time, travel_t))
                bus_occ = d.get('bus_occ', 40.0)
                d['traj_bus_veh_passages']  = d.get('traj_bus_veh_passages', 0) + 1
                d['traj_bus_passengers']    = d.get('traj_bus_passengers', 0.0) + bus_occ
            pt_entry[veh_id] = time   # reset timer for the next passage

    # =========================================================================
    # KPI COMPUTATION
    # =========================================================================

    def _kpis_for(self, iid: int) -> dict:
        """Compute KPIs for one intersection."""
        d = self._inter[iid]

        # ── Bus travel time (from distinct tracked trips) ─────────────────────
        trips = d['bus_trips']
        if trips:
            total_bus_tt_s   = sum(t[2] for t in trips)
            n_buses          = len(trips)
            avg_bus_tt_s     = total_bus_tt_s / n_buses
            total_bus_tt_hrs = total_bus_tt_s / 3600.0
        else:
            total_bus_tt_hrs = avg_bus_tt_s = 0.0
            n_buses = 0

        # Distinct headcounts — true unique vehicles seen at this intersection
        n_distinct_buses = len(d['_seen_bus_ids'])
        n_distinct_cars  = len(d['_seen_car_ids'])
        n_distinct_trucks = len(d.get('_seen_truck_ids', set()))

        # ── Delay (pax·s accumulated from AKIEstGetParcialStatistics) ─────────
        # delay_total / delay_bus / delay_car are pax·s sums; divide by the
        # occupancy-weighted passage total (passengers) to get avg delay/pax.
        # 'passengers' here is SUM(count_per_step × occupancy) — the correct
        # denominator for an average, NOT a headcount.
        eff_bus_delay = max(d['delay_bus'], d.get('traj_bus_delay', 0.0))
        eff_bus_veh_passages = max(d['bus_veh_passages'], d.get('traj_bus_veh_passages', 0))
        eff_bus_passengers = max(d['bus_passengers'], d.get('traj_bus_passengers', 0.0))
        added_bus_delay = max(0.0, eff_bus_delay - d['delay_bus'])
        added_bus_passengers = max(0.0, eff_bus_passengers - d['bus_passengers'])
        added_bus_veh_passages = max(0, eff_bus_veh_passages - d['bus_veh_passages'])

        total_delay_pax_s = d['delay_total'] + added_bus_delay
        main_delay_pax_s  = d['delay_main']  + added_bus_delay
        side_delay_pax_s  = d['delay_side']

        total_delay_hrs = total_delay_pax_s / 3600.0
        main_delay_hrs  = main_delay_pax_s  / 3600.0
        side_delay_hrs  = side_delay_pax_s  / 3600.0

        passengers     = d['passengers'] + added_bus_passengers
        bus_passengers = eff_bus_passengers
        car_passengers = d['car_passengers']   # car component
        truck_passengers = d.get('truck_passengers', 0.0)

        avg_pass_delay_s     = total_delay_pax_s / passengers     if passengers     > 0 else 0.0
        avg_bus_pass_delay_s = eff_bus_delay     / bus_passengers if bus_passengers > 0 else 0.0
        avg_car_pass_delay_s = d['delay_car']   / car_passengers if car_passengers > 0 else 0.0
        avg_truck_pass_delay_s = d.get('delay_truck', 0.0) / truck_passengers if truck_passengers > 0 else 0.0

        # Per-intersection objective: throughput / delay (same formula as global)
        _delay_hrs_inter = total_delay_pax_s / 3600.0
        inter_objective  = (
            passengers / _delay_hrs_inter
            if _delay_hrs_inter > 1e-6 else 0.0
        )

        return {
            'bus_total_tt_hrs':      total_bus_tt_hrs,
            'n_buses':               n_buses,           # bus trips completed
            'n_distinct_buses':      n_distinct_buses,  # unique bus IDs seen
            'n_distinct_cars':       n_distinct_cars,   # unique car IDs seen
            'n_distinct_trucks':     n_distinct_trucks,
            'avg_bus_tt_s':          avg_bus_tt_s,
            'total_pass_delay_hrs':  total_delay_hrs,
            'main_pass_delay_hrs':   main_delay_hrs,
            'side_pass_delay_hrs':   side_delay_hrs,
            'passengers':            passengers,
            'bus_passengers':        bus_passengers,
            'car_passengers':        car_passengers,
            'truck_passengers':      truck_passengers,
            'bus_veh_passages':      eff_bus_veh_passages,
            'car_veh_passages':      d['car_veh_passages'],
            'truck_veh_passages':    d.get('truck_veh_passages', 0),
            'delay_total_pax_s':     total_delay_pax_s,
            'delay_bus_pax_s':       eff_bus_delay,
            'delay_car_pax_s':       d['delay_car'],
            'delay_truck_pax_s':     d.get('delay_truck', 0.0),
            'avg_pass_delay_s':      avg_pass_delay_s,
            'avg_bus_pass_delay_s':  avg_bus_pass_delay_s,
            'avg_car_pass_delay_s':  avg_car_pass_delay_s,
            'avg_truck_pass_delay_s': avg_truck_pass_delay_s,
            'n_detections':          d['n_detections'],
            'n_extensions':          d['n_extensions'],
            'n_insertions':          d['n_insertions'],
            'n_exit_clears':         d['n_exit_clears'],
            'n_cap_clears':          d['n_cap_clears'],
            'n_skipped_ge':          d.get('n_skipped_ge', 0),
            'n_skipped_ins':         d.get('n_skipped_ins', 0),
            'n_detected_no_action':  d.get('n_detected_no_action', 0),
            'total_vehicles':        d['vehicles'] + added_bus_veh_passages,
            'n_main_sections':       len(d.get('main_sections', [])),
            'n_side_sections':       len(d.get('side_sections', [])),
            'side_sections_resolved': bool(d.get('side_sections_resolved', False)),
            'main_sections':         list(d.get('main_sections', [])),
            'side_sections':         list(d.get('side_sections', [])),
            # Objective
            'objective':             inter_objective,
        }

    def _global_kpis(self) -> dict:
        """Sum KPIs across all intersections."""
        total_bus_tt_hrs   = 0.0
        total_pass_delay   = 0.0
        total_main_delay   = 0.0
        total_side_delay   = 0.0
        total_n_buses      = 0
        total_distinct_buses = 0
        total_distinct_cars  = 0
        total_distinct_trucks = 0
        total_dets         = 0
        total_exts         = 0
        total_ins          = 0
        total_skipped_ge   = 0
        total_skipped_ins  = 0
        total_no_action    = 0
        sim_total_delay    = 0.0
        sim_bus_delay      = 0.0
        sim_car_delay      = 0.0
        sim_truck_delay    = 0.0
        total_passengers   = 0.0
        bus_passengers     = 0.0
        car_passengers     = 0.0
        truck_passengers   = 0.0

        for iid in self._inter:
            k = self._kpis_for(iid)
            total_bus_tt_hrs    += k['bus_total_tt_hrs']
            total_pass_delay    += k['total_pass_delay_hrs']
            total_main_delay    += k['main_pass_delay_hrs']
            total_side_delay    += k['side_pass_delay_hrs']
            total_n_buses       += k['n_buses']
            total_distinct_buses += k['n_distinct_buses']
            total_distinct_cars  += k['n_distinct_cars']
            total_distinct_trucks += k['n_distinct_trucks']
            total_dets          += k['n_detections']
            total_exts          += k['n_extensions']
            total_ins           += k['n_insertions']
            total_skipped_ge    += k['n_skipped_ge']
            total_skipped_ins   += k['n_skipped_ins']
            total_no_action     += k['n_detected_no_action']
            sim_total_delay     += k['delay_total_pax_s']
            sim_bus_delay       += k['delay_bus_pax_s']
            sim_car_delay       += k['delay_car_pax_s']
            sim_truck_delay     += k['delay_truck_pax_s']
            total_passengers    += k['passengers']
            bus_passengers      += k['bus_passengers']
            car_passengers      += k['car_passengers']
            truck_passengers    += k['truck_passengers']

        avg_bus_tt_s = (
            (total_bus_tt_hrs * 3600.0 / total_n_buses)
            if total_n_buses > 0 else 0.0
        )
        avg_obj_delay = (
            self.obj_avg_passenger_delay / self.obj_steps
            if self.obj_steps > 0 else 0.0
        )
        avg_pass_delay_s = (
            sim_total_delay / total_passengers
            if total_passengers > 0 else 0.0
        )
        avg_bus_pass_delay_s = (
            sim_bus_delay / bus_passengers
            if bus_passengers > 0 else 0.0
        )
        avg_car_pass_delay_s = (
            sim_car_delay / car_passengers
            if car_passengers > 0 else 0.0
        )
        avg_truck_pass_delay_s = (
            sim_truck_delay / truck_passengers
            if truck_passengers > 0 else 0.0
        )

        # ── Objective metric ──────────────────────────────────────────────────
        # Goal: maximise passenger flow while minimising total delay.
        # Metric: pax-equivalent throughput per hour of total delay.
        #   Objective = TotalPaxPassages / (TotalDelayPax_s / 3600)
        # Higher is better: more pax moved per hour of queue/delay incurred.
        # Also report raw components so different runs can be compared directly.
        _delay_hrs = sim_total_delay / 3600.0
        throughput_per_delay_hr = (
            total_passengers / _delay_hrs
            if _delay_hrs > 1e-6 else 0.0
        )

        return {
            'bus_total_tt_hrs':          total_bus_tt_hrs,
            'n_buses':                   total_n_buses,
            'n_distinct_buses':          total_distinct_buses,
            'n_distinct_cars':           total_distinct_cars,
            'n_distinct_trucks':         total_distinct_trucks,
            'avg_bus_tt_s':              avg_bus_tt_s,
            'total_pass_delay_hrs':      total_pass_delay,
            'main_pass_delay_hrs':       total_main_delay,
            'side_pass_delay_hrs':       total_side_delay,
            'sim_total_delay':           sim_total_delay,
            'sim_bus_delay':             sim_bus_delay,
            'sim_car_delay':             sim_car_delay,
            'sim_truck_delay':           sim_truck_delay,
            'total_passengers':          total_passengers,
            'bus_passengers':            bus_passengers,
            'car_passengers':            car_passengers,
            'truck_passengers':          truck_passengers,
            'avg_pass_delay_s':          avg_pass_delay_s,
            'avg_bus_pass_delay_s':      avg_bus_pass_delay_s,
            'avg_car_pass_delay_s':      avg_car_pass_delay_s,
            'avg_truck_pass_delay_s':    avg_truck_pass_delay_s,
            'avg_obj_pass_delay':        avg_obj_delay,
            'n_tsp_detections':          total_dets,
            'n_tsp_extensions':          total_exts,
            'n_tsp_insertions':          total_ins,
            'n_tsp_skipped_ge':          total_skipped_ge,
            'n_tsp_skipped_ins':         total_skipped_ins,
            'n_tsp_detected_no_action':  total_no_action,
            # Objective
            'throughput_per_delay_hr':   throughput_per_delay_hr,
        }

    # =========================================================================
    # REPORTING
    # =========================================================================

    def print_results(self):
        sep = '=' * 65
        g   = self._global_kpis()

        self._print(sep)
        self._print(f"[STATS] RESULTS — TSP mode: {self.tsp_strategy}")
        self._print(sep)

        self._print("[STATS] ── GLOBAL KPIs ──")
        self._print(f"[STATS]   KPI 1  Bus Total Travel Time  : "
                       f"{g['bus_total_tt_hrs']:.4f} hrs "
                       f"({g['n_buses']} bus trips, "
                       f"avg {g['avg_bus_tt_s']:.1f} s/trip | "
                       f"distinct buses seen: {g['n_distinct_buses']})")
        self._print(f"[STATS]   KPI 2  Total Passenger Delay  : "
                       f"{g['total_pass_delay_hrs']:.4f} hrs")
        self._print(f"[STATS]   KPI 3  Side Street Delay      : "
                       f"{g['side_pass_delay_hrs']:.4f} hrs")
        self._print(f"[STATS]   Distinct cars seen (global)   : "
                       f"{g['n_distinct_cars']}")
        self._print(f"[STATS]   Distinct trucks seen (global) : "
                       f"{g['n_distinct_trucks']}")
        self._print(f"[STATS]   Type map / occ                : "
                       f"car={self._car_pos}('{self._car_type_name}') occ={self._inter[next(iter(self._inter))]['car_occ'] if self._inter else 0} | "
                       f"bus={self._bus_pos}('{self._bus_type_name}') occ={self._inter[next(iter(self._inter))]['bus_occ'] if self._inter else 0} | "
                       f"truck={self._truck_pos}('{self._truck_type_name}') occ={self._inter[next(iter(self._inter))].get('truck_occ',0) if self._inter else 0}")
        self._print(f"[STATS]   TSP events — det={g['n_tsp_detections']} "
                       f"ext={g['n_tsp_extensions']} "
                       f"ins={g['n_tsp_insertions']} | "
                       f"skipped_GE={g['n_tsp_skipped_ge']} "
                       f"skipped_ins={g['n_tsp_skipped_ins']} "
                       f"no_action(NORMAL)={g['n_tsp_detected_no_action']}")

        self._print(sep)
        self._print("[STATS] ── PER-INTERSECTION BREAKDOWN ──")

        for iid, d in self._inter.items():
            k = self._kpis_for(iid)
            self._print(f"[STATS] Intersection {iid}")
            self._print(f"[STATS]   Bus TT        : {k['bus_total_tt_hrs']:.4f} hrs "
                           f"({k['n_buses']} trips | distinct buses: {k['n_distinct_buses']})")
            self._print(f"[STATS]   Cars only     : {k['n_distinct_cars']} distinct vehicles "
                           f"| {k['car_veh_passages']} passages")
            self._print(f"[STATS]   Trucks only   : {k['n_distinct_trucks']} distinct vehicles "
                           f"| {k['truck_veh_passages']} passages")
            self._print(f"[STATS]   Pass delay    : {k['total_pass_delay_hrs']:.4f} hrs "
                           f"(main={k['main_pass_delay_hrs']:.4f} "
                           f"side={k['side_pass_delay_hrs']:.4f})")
            self._print(f"[STATS]   Avg delay/pax : {k['avg_pass_delay_s']:.2f} s/pax "
                           f"(bus={k['avg_bus_pass_delay_s']:.2f} "
                           f"car={k['avg_car_pass_delay_s']:.2f} "
                           f"truck={k['avg_truck_pass_delay_s']:.2f})")
            self._print(f"[STATS]   Veh passages  : bus={k['bus_veh_passages']} "
                           f"car={k['car_veh_passages']} truck={k['truck_veh_passages']}")
            self._print(f"[STATS]   Pax-eq pass   : total={k['passengers']:.1f} "
                           f"(bus={k['bus_passengers']:.1f} "
                           f"car={k['car_passengers']:.1f} "
                           f"truck={k['truck_passengers']:.1f})")
            self._print(f"[STATS]   Sections      : main={k['n_main_sections']} "
                           f"side={k['n_side_sections']} "
                           f"(resolved={k['side_sections_resolved']})")
            self._print(f"[STATS]   Section IDs   : main={k['main_sections']} "
                           f"side={k['side_sections']}")
            self._print(f"[STATS]   Occupancies   : car={d['car_occ']} "
                           f"bus={d['bus_occ']} truck={d.get('truck_occ', d['car_occ'])}")
            self._print(f"[STATS]   TSP: det={k['n_detections']} "
                           f"ext={k['n_extensions']} ins={k['n_insertions']} "
                           f"exit_clear={k['n_exit_clears']} "
                           f"cap_clear={k['n_cap_clears']}")
            self._print(f"[STATS]   Objective       : {k['objective']:.2f} pax/delay-hr")

        self._print(sep)
        self._print("[STATS] ── SIMULATION DELAY (occupancy-weighted) ──")
        self._print(f"[STATS]   NOTE: 'pax-eq passages' below = occupancy-weighted vehicle passages")
        self._print(f"[STATS]   (each vehicle counted once per second it traverses a section)")
        self._print(f"[STATS]   Use 'distinct buses/cars' above for true headcounts.")
        self._print(f"[STATS]   Total delay       : {g['sim_total_delay']:.2f} pax·s")
        self._print(f"[STATS]   Bus delay         : {g['sim_bus_delay']:.2f} pax·s")
        self._print(f"[STATS]   Car delay         : {g['sim_car_delay']:.2f} pax·s")
        self._print(f"[STATS]   Truck delay       : {g['sim_truck_delay']:.2f} pax·s")
        self._print(f"[STATS]   Pax-eq passages   : {g['total_passengers']:.1f} pax "
                       f"(bus={g['bus_passengers']:.1f} car={g['car_passengers']:.1f} truck={g['truck_passengers']:.1f})")
        self._print(f"[STATS]   Avg delay/pax     : {g['avg_pass_delay_s']:.2f} s/pax")
        self._print(f"[STATS]   Avg delay/bus pax : {g['avg_bus_pass_delay_s']:.2f} s/pax")
        self._print(f"[STATS]   Avg delay/car pax : {g['avg_car_pass_delay_s']:.2f} s/pax")
        self._print(f"[STATS]   Avg delay/trk pax : {g['avg_truck_pass_delay_s']:.2f} s/pax")
        obj_str = (f"{g['avg_obj_pass_delay']:.4f}"
                   if self.obj_steps > 0
                   else f"N/A (not used in {self.tsp_strategy} mode)")
        self._print(f"[STATS]   Avg obj delay     : {obj_str} (model — harmony/URTSP only)")

        self._print(sep)
        self._print("[STATS] ── NETWORK OBJECTIVE (flow vs delay) ──")
        self._print(f"[STATS]   Total pax-equiv throughput : {g['total_passengers']:.1f} pax")
        self._print(f"[STATS]   Total delay (all pax)      : {g['sim_total_delay']:.1f} pax·s "
                       f"({g['total_pass_delay_hrs']:.4f} hrs)")
        self._print(f"[STATS]   OBJECTIVE (pax/delay-hr)   : {g['throughput_per_delay_hr']:.2f} "
                       f"pax per delay-hour")
        self._print(f"[STATS]   (Higher = more pax moved per unit of delay — compare across runs)")
        self._print(sep)

        # CSV summary line for spreadsheet copy-paste
        self._print(
            f"[STATS] CSV: "
            f"{self.tsp_strategy},"
            f"{g['bus_total_tt_hrs']:.4f},"
            f"{g['n_buses']},"
            f"{g['n_distinct_buses']},"
            f"{g['n_distinct_cars']},"
            f"{g['avg_bus_tt_s']:.1f},"
            f"{g['total_pass_delay_hrs']:.4f},"
            f"{g['side_pass_delay_hrs']:.4f},"
            f"{g['main_pass_delay_hrs']:.4f}"
        )

    def _re_resolve_main_sections(self):
        """
        Re-run detector → section lookup for every registered intersection
        that still has empty main_sections (the common case when
        register_intersection was called during AAPIInit before the simulation
        engine was fully ready).

        Updates _inter[iid]['main_sections'] and 'all_sections' in-place.
        Must be called before _resolve_side_sections.
        """
        n_fixed = 0
        for iid, d in self._inter.items():
            if d['main_sections']:
                continue  # already populated — explicit config value, leave it

            config        = d['config']
            up_det_list   = config.get('UpDetList', [])
            all_sections  = self._sections_from_detectors(up_det_list)

            # Filter out invalid IDs (0 or negative mean the detector wasn't found)
            all_sections = [s for s in all_sections if s and s > 0]

            if not all_sections:
                self._print(
                    f"[STATS] WARNING _re_resolve_main_sections: "
                    f"inter={iid} — no valid sections from detectors "
                    f"{up_det_list}. Delay collection will be 0 for this intersection."
                )
                continue

            # All sections from UpDetList are main-corridor approach sections.
            # Side sections are derived from topology in _resolve_side_sections.
            d['all_sections']  = all_sections
            d['main_sections'] = all_sections
            n_fixed += 1
            self._print(
                f"[STATS] inter={iid} main_sections resolved → {all_sections}"
            )

        self._print(
            f"[STATS] _re_resolve_main_sections: {n_fixed} intersections updated"
        )

    def _resolve_side_sections(self):
        """
        Called from finalise_init (i.e. AAPISimulationReady) — the point at
        which PyANGKernel topology is guaranteed to be fully loaded.

        For every registered intersection whose side_sections list is still
        empty, query the junction's incoming turning movements to find approach
        sections that are NOT already in main_sections. Those are the side
        streets. Results are stored directly in self._inter[iid]['side_sections']
        so collect_delay picks them up from the very first simulation step.
        """
        n_total    = len(self._inter)
        n_resolved = 0
        n_already  = 0

        for iid, d in self._inter.items():
            # Only skip if side_sections were explicitly provided in the config.
            # Auto-derived sections from AAPIInit (unreliable topology) are cleared
            # here and re-derived now that PyANGKernel is fully ready.
            if list(d.get('config', {}).get('SideSections', [])):
                d['side_sections'] = [
                    s for s in d.get('side_sections', [])
                    if s not in set(d.get('main_sections', []))
                ]
                d['side_sections_resolved'] = bool(d['side_sections'])
                n_already += 1
                continue   # explicitly configured — preserve it
            d['side_sections'] = []   # reset auto-derived; re-derive below
            d['side_sections_resolved'] = False
            if not d['main_sections']:
                self._print(
                    f"[STATS] inter={iid}: no main_sections — cannot derive sides"
                )
                continue

            main_set = set(d['main_sections'])
            side = [s for s in self._side_sections_from_topology(iid, d['main_sections'])
                    if s not in main_set]
            if side:
                d['side_sections'] = side
                d['side_sections_resolved'] = True
                n_resolved += 1
                self._print(
                    f"[STATS] inter={iid} side_sections resolved → {side}"
                )
            else:
                self._print(
                    f"[STATS] WARNING inter={iid}: topology returned no side "
                    f"sections (main={d['main_sections']}) — "
                    f"side-street delay will be 0 for this intersection"
                )

        self._print(
            f"[STATS] _resolve_side_sections: "
            f"{n_resolved} newly resolved, {n_already} already set, "
            f"{n_total - n_resolved - n_already} unresolved "
            f"(out of {n_total} intersections)"
        )

    def _run_path(self) -> str:
        """Return the per-run output subfolder path, creating it if needed.

        Folder format: {strategy}_seed{N}_{scenario}_{experiment}_{replication}
        Strategy and seed are read from run_config.py written by run_experiments.py.
        Falls back to 'unknown_seedX' if run_config is absent (manual runs).

        Tries candidate base directories in order:
          1. self.output_folder  (relative to this file's directory by default)
          2. sibling 'results' folder next to this file
          3. D:\\Aimsun_Results  (legacy absolute fallback)
          4. user home directory
        """
        s = str(self.scenario_id)    if self.scenario_id    is not None else 'unknown'
        e = str(self.experiment_id)  if self.experiment_id  is not None else 'unknown'
        r = str(self.replication_id) if self.replication_id is not None else 'unknown'

        strategy = 'unknown'
        seed     = '0'
        try:
            _cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     'run_config.py')
            _ns = {}
            with open(_cfg_path, 'r') as _f:
                exec(_f.read(), _ns)
            strategy = str(_ns.get('CURRENT_STRATEGY', 'unknown'))
            seed     = str(_ns.get('CURRENT_SEED',     '0'))
        except Exception:
            pass  # run_config absent — manual run, use defaults

        folder_name = f"{strategy}_seed{seed}_{s}_{e}_{r}"

        # Candidate base directories — tried in order until one succeeds
        try:
            _file_dir = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            _file_dir = None

        candidates = [self.output_folder]
        if _file_dir:
            candidates.append(os.path.join(_file_dir, 'results'))
        candidates += [r"D:\Aimsun_Results",
                       os.path.join(os.path.expanduser("~"), "Aimsun_Results")]

        last_err = None
        for base in candidates:
            try:
                run_folder = os.path.join(base, folder_name)
                os.makedirs(run_folder, exist_ok=True)
                self._print(f"[STATS] Output folder: {run_folder}")
                return run_folder
            except Exception as ex:
                self._print(f"[STATS] Could not use output base {base}: {ex}")
                last_err = ex

        raise RuntimeError(
            f"Could not create any output folder (last error: {last_err})"
        )

    def save_results(self):
        """Write global + per-intersection results to a per-run subfolder."""
        try:
            run_path = self._run_path()
        except Exception as e:
            self._print(f"[STATS] WARNING: could not create output folder: {e}")
            return

        g = self._global_kpis()

        # ── 1. Global summary CSV ───────────────────────────────────────────
        global_csv = os.path.join(run_path, "simulation_results.csv")
        self._append_csv(
            global_csv,
            headers=[
                "ScenarioID", "ExperimentID", "ReplicationID", "TSP_Strategy",
                "BusTotalTT_hrs", "N_BusTrips", "N_DistinctBuses", "N_DistinctCars", "N_DistinctTrucks",
                "AvgBusTT_s",
                "TotalPassDelay_hrs", "SidePassDelay_hrs", "MainPassDelay_hrs",
                "SimTotalDelay_pax_s", "SimBusDelay_pax_s", "SimCarDelay_pax_s", "SimTruckDelay_pax_s",
                "PaxEquivPassages", "BusPaxEquivPassages", "CarPaxEquivPassages", "TruckPaxEquivPassages",
                "AvgPassDelay_s", "AvgBusPassDelay_s", "AvgCarPassDelay_s", "AvgTruckPassDelay_s",
                "AvgObjPassDelay",
                "TSP_Detections", "TSP_Extensions", "TSP_Insertions",
                "TSP_Skipped_GE", "TSP_Skipped_Ins", "TSP_Detected_NoAction",
                # Objective metric
                "Objective_PaxPerDelayHr",
            ],
            row=[
                self.scenario_id, self.experiment_id, self.replication_id,
                self.tsp_strategy,
                round(g['bus_total_tt_hrs'], 4),
                g['n_buses'],
                g['n_distinct_buses'],
                g['n_distinct_cars'],
                g['n_distinct_trucks'],
                round(g['avg_bus_tt_s'], 1),
                round(g['total_pass_delay_hrs'], 4),
                round(g['side_pass_delay_hrs'], 4),
                round(g['main_pass_delay_hrs'], 4),
                round(g['sim_total_delay'], 2),
                round(g['sim_bus_delay'], 2),
                round(g['sim_car_delay'], 2),
                round(g['sim_truck_delay'], 2),
                round(g['total_passengers'], 1),
                round(g['bus_passengers'], 1),
                round(g['car_passengers'], 1),
                round(g['truck_passengers'], 1),
                round(g['avg_pass_delay_s'], 2),
                round(g['avg_bus_pass_delay_s'], 2),
                round(g['avg_car_pass_delay_s'], 2),
                round(g['avg_truck_pass_delay_s'], 2),
                round(g['avg_obj_pass_delay'], 4),
                g['n_tsp_detections'],
                g['n_tsp_extensions'],
                g['n_tsp_insertions'],
                g['n_tsp_skipped_ge'],
                g['n_tsp_skipped_ins'],
                g['n_tsp_detected_no_action'],
                round(g['throughput_per_delay_hr'], 3),
            ],
        )

        # ── 2. Per-intersection CSV ─────────────────────────────────────────
        inter_csv = os.path.join(run_path, "simulation_results_per_intersection.csv")
        for iid in self._inter:
            d = self._inter[iid]
            k = self._kpis_for(iid)
            self._append_csv(
                inter_csv,
                headers=[
                    # Identifiers
                    "ScenarioID", "ExperimentID", "ReplicationID",
                    "TSP_Strategy", "IntersectionID",
                    # Bus travel time
                    "BusTotalTT_hrs",       # total bus travel time (hours)
                    "N_BusTrips",           # bus trips completed (call→exit)
                    "N_DistinctBuses",      # unique bus vehicle IDs seen
                    # Vehicle passage counts (exits from main approach sections)
                    "N_DistinctCars",       # unique car IDs seen on approach
                    "N_DistinctTrucks",     # unique truck IDs seen
                    "BusVehPassages",       # bus vehicles counted exiting main sections
                    "CarVehPassages",       # car vehicles counted exiting main sections
                    "TruckVehPassages",     # truck vehicles (0 if no truck type)
                    "AvgBusTT_s",           # average bus travel time (seconds/trip)
                    # Delay KPIs
                    "TotalPassDelay_hrs",   # total pax·s delay / 3600 (all sections)
                    "MainPassDelay_hrs",    # delay on main corridor sections (hours)
                    "SidePassDelay_hrs",    # delay on side/cross-street sections (hours)
                    # Passenger-equivalent passages: VehicleCount × Occupancy
                    # (denominator for AvgPassDelay; CarOcc=1.5 pax/car, BusOcc=40 pax/bus)
                    "PaxEquivPassages",     # sum(veh_count × occ) across bus+car+truck
                    "BusPaxEquivPassages",  # bus vehicle passages × BusOcc
                    "CarPaxEquivPassages",  # car vehicle passages × CarOcc
                    "TruckPaxEquivPassages",# truck passages × TruckOcc (0 if none)
                    # Average delay per passenger
                    "AvgPassDelay_s",       # total delay / total passengers (s/pax)
                    "AvgBusPassDelay_s",    # bus delay / bus passengers (s/pax)
                    "AvgCarPassDelay_s",    # car delay / car passengers (s/pax)
                    "AvgTruckPassDelay_s",  # truck delay / truck passengers (s/pax)
                    # Section metadata
                    "N_MainSections", "N_SideSections", "SideSectionsResolved",
                    "MainSectionIDs", "SideSectionIDs",
                    # Occupancy / type config
                    "CarOcc",  # passengers per car
                    "BusOcc",  # passengers per bus
                    "TruckOcc",
                    "CarTypePos", "BusTypePos", "TruckTypePos",
                    # TSP event counts
                    "TSP_Detections",   # bus detection triggers
                    "TSP_Extensions",   # green-extension actions
                    "TSP_Insertions",   # phase-insertion actions
                    "TSP_ExitClears", "TSP_CapClears",
                    # Skip counters — bus detected but no action taken
                    "TSP_Skipped_GE",        # harmony GE opt ≤ 0.5 s
                    "TSP_Skipped_Ins",       # harmony BP opt ≤ 0.5 s
                    "TSP_Detected_NoAction", # NORMAL mode detections
                    # Objective metric
                    "Objective_PaxPerDelayHr",
                ],
                row=[
                    self.scenario_id, self.experiment_id, self.replication_id,
                    self.tsp_strategy, iid,
                    round(k['bus_total_tt_hrs'], 4),
                    k['n_buses'],
                    k['n_distinct_buses'],
                    k['n_distinct_cars'],
                    k['n_distinct_trucks'],
                    k['bus_veh_passages'],
                    k['car_veh_passages'],
                    k['truck_veh_passages'],
                    round(k['avg_bus_tt_s'], 1),
                    round(k['total_pass_delay_hrs'], 4),
                    round(k['main_pass_delay_hrs'], 4),
                    round(k['side_pass_delay_hrs'], 4),
                    round(k['passengers'], 1),
                    round(k['bus_passengers'], 1),
                    round(k['car_passengers'], 1),
                    round(k['truck_passengers'], 1),
                    round(k['avg_pass_delay_s'], 2),
                    round(k['avg_bus_pass_delay_s'], 2),
                    round(k['avg_car_pass_delay_s'], 2),
                    round(k['avg_truck_pass_delay_s'], 2),
                    k['n_main_sections'],
                    k['n_side_sections'],
                    int(k['side_sections_resolved']),
                    "|".join(str(x) for x in k['main_sections']),
                    "|".join(str(x) for x in k['side_sections']),
                    d['car_occ'],
                    d['bus_occ'],
                    d.get('truck_occ', d['car_occ']),
                    self._car_pos,
                    self._bus_pos,
                    self._truck_pos,
                    k['n_detections'],
                    k['n_extensions'],
                    k['n_insertions'],
                    k['n_exit_clears'],
                    k['n_cap_clears'],
                    k['n_skipped_ge'],
                    k['n_skipped_ins'],
                    k['n_detected_no_action'],
                    round(k['objective'], 3),
                ],
            )

        # ── 3. Per-bus-trip CSV ─────────────────────────────────────────────
        trips_csv = os.path.join(run_path, "bus_trips.csv")
        trip_headers = [
            "ScenarioID", "ExperimentID", "ReplicationID", "TSP_Strategy",
            "IntersectionID", "EntryTime_s", "ExitTime_s", "TravelTime_s",
        ]
        total_trips = 0
        for iid, d in self._inter.items():
            for (entry_t, exit_t, tt_s) in d['bus_trips']:
                self._append_csv(
                    trips_csv,
                    headers=trip_headers,
                    row=[
                        self.scenario_id, self.experiment_id, self.replication_id,
                        self.tsp_strategy, iid,
                        round(entry_t, 1), round(exit_t, 1), round(tt_s, 1),
                    ],
                )
                total_trips += 1

        # ── 4. JSON summary ─────────────────────────────────────────────────
        inter_list = []
        for iid, d in self._inter.items():
            k = self._kpis_for(iid)
            inter_list.append({
                'intersection_id':      iid,
                'bus_total_tt_hrs':     round(k['bus_total_tt_hrs'], 4),
                'n_buses':              k['n_buses'],
                'avg_bus_tt_s':         round(k['avg_bus_tt_s'], 1),
                'total_pass_delay_hrs': round(k['total_pass_delay_hrs'], 4),
                'main_pass_delay_hrs':  round(k['main_pass_delay_hrs'], 4),
                'side_pass_delay_hrs':  round(k['side_pass_delay_hrs'], 4),
                'pax_equiv_passages':   round(k['passengers'], 1),
                'bus_pax_equiv_passages': round(k['bus_passengers'], 1),
                'car_pax_equiv_passages': round(k['car_passengers'], 1),
                'truck_pax_equiv_passages': round(k['truck_passengers'], 1),
                'bus_veh_passages':     k['bus_veh_passages'],
                'car_veh_passages':     k['car_veh_passages'],
                'truck_veh_passages':   k['truck_veh_passages'],
                'avg_pass_delay_s':     round(k['avg_pass_delay_s'], 2),
                'avg_bus_pass_delay_s': round(k['avg_bus_pass_delay_s'], 2),
                'avg_car_pass_delay_s': round(k['avg_car_pass_delay_s'], 2),
                'avg_truck_pass_delay_s': round(k['avg_truck_pass_delay_s'], 2),
                'main_sections':        k['main_sections'],
                'side_sections':        k['side_sections'],
                'side_sections_resolved': bool(k['side_sections_resolved']),
                'tsp_detections':       k['n_detections'],
                'tsp_extensions':       k['n_extensions'],
                'tsp_insertions':       k['n_insertions'],
                'tsp_exit_clears':      k['n_exit_clears'],
                'tsp_cap_clears':       k['n_cap_clears'],
                'bus_trips': [
                    {'entry_s': round(e, 1), 'exit_s': round(x, 1),
                     'travel_time_s': round(t, 1)}
                    for e, x, t in d['bus_trips']
                ],
            })

        summary = {
            'run': {
                'scenario_id':    self.scenario_id,
                'experiment_id':  self.experiment_id,
                'replication_id': self.replication_id,
                'tsp_strategy':   self.tsp_strategy,
            },
            'global_kpis': {
                'bus_total_tt_hrs':      round(g['bus_total_tt_hrs'], 4),
                'n_buses':               g['n_buses'],
                'avg_bus_tt_s':          round(g['avg_bus_tt_s'], 1),
                'total_pass_delay_hrs':  round(g['total_pass_delay_hrs'], 4),
                'main_pass_delay_hrs':   round(g['main_pass_delay_hrs'], 4),
                'side_pass_delay_hrs':   round(g['side_pass_delay_hrs'], 4),
                'sim_total_delay_pax_s': round(g['sim_total_delay'], 2),
                'sim_bus_delay_pax_s':   round(g['sim_bus_delay'], 2),
                'sim_car_delay_pax_s':   round(g['sim_car_delay'], 2),
                'pax_equiv_passages':    round(g['total_passengers'], 1),
                'bus_pax_equiv_passages': round(g['bus_passengers'], 1),
                'car_pax_equiv_passages': round(g['car_passengers'], 1),
                'truck_pax_equiv_passages': round(g['truck_passengers'], 1),
                'avg_pass_delay_s':      round(g['avg_pass_delay_s'], 2),
                'avg_bus_pass_delay_s':  round(g['avg_bus_pass_delay_s'], 2),
                'avg_car_pass_delay_s':  round(g['avg_car_pass_delay_s'], 2),
                'avg_truck_pass_delay_s': round(g['avg_truck_pass_delay_s'], 2),
                'avg_obj_pass_delay':    round(g['avg_obj_pass_delay'], 4),
                'n_tsp_detections':      g['n_tsp_detections'],
                'n_tsp_extensions':      g['n_tsp_extensions'],
                'n_tsp_insertions':      g['n_tsp_insertions'],
            },
            'intersections': inter_list,
        }

        json_path = os.path.join(run_path, "summary.json")
        try:
            with open(json_path, 'w') as f:
                json.dump(summary, f, indent=2)
        except Exception as e:
            self._print(f"[STATS] WARNING: could not write summary.json: {e}")

        self._print(f"[STATS] Results saved to → {run_path}")
        self._print(f"[STATS]   simulation_results.csv")
        self._print(f"[STATS]   simulation_results_per_intersection.csv")
        self._print(f"[STATS]   bus_trips.csv ({total_trips} trips)")
        self._print(f"[STATS]   summary.json")

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    @staticmethod
    def _sections_from_detectors(up_det_list: list) -> list:
        """Get unique, valid section IDs from a nested detector list.
        Skips detectors that are not found (report < 0) or return an
        invalid section ID (0 or negative).
        """
        sections = []
        seen = set()
        for phase in up_det_list:
            for det_id in phase:
                try:
                    props = AKIDetGetPropertiesDetectorById(det_id)
                    if props.report < 0:
                        continue  # detector not found in model
                    sec = props.IdSection
                    if sec and sec > 0 and sec not in seen:
                        seen.add(sec)
                        sections.append(sec)
                except Exception:
                    pass
        return sections

    @staticmethod
    def _auto_exit_sections(intersection_id: int, call_sections: list) -> list:
        """
        Auto-detect downstream exit sections for an intersection by querying
        the network topology. For each call (approach) section, finds all
        downstream sections reachable via turning movements through the junction.
        Falls back to call_sections if topology query fails.
        """
        try:
            from PyANGKernel import GKSystem
            model = GKSystem.getSystem().getActiveModel()
            if model is None:
                return call_sections

            exit_secs = []
            seen = set()

            # Find node by ID
            node = model.getCatalog().find(intersection_id)
            if node is None:
                return call_sections

            # Iterate all turning movements on the node when this API exists.
            get_conns = getattr(node, 'getInternalConnections', None)
            if callable(get_conns):
                for turn in get_conns():
                    try:
                        dest = turn.getDestination()
                        if dest is None:
                            continue
                        sec_id = dest.getId()
                        if sec_id not in seen and sec_id not in call_sections:
                            seen.add(sec_id)
                            exit_secs.append(sec_id)
                    except Exception:
                        continue

            if exit_secs:
                return exit_secs

            # Fallback: use sections attached to the node as destinations
            for sec in model.getCatalog().getObjectsByType(
                    model.getType('GKSection')):
                try:
                    if sec.getOrigin() and sec.getOrigin().getId() == intersection_id:
                        sec_id = sec.getId()
                        if sec_id not in seen and sec_id not in call_sections:
                            seen.add(sec_id)
                            exit_secs.append(sec_id)
                except Exception:
                    continue

            return exit_secs if exit_secs else call_sections

        except Exception:
            return call_sections

    def _side_sections_from_topology(self, intersection_id: int,
                                     main_sections: list) -> list:
        """
        Derive side-street approach sections by querying junction topology.
        Returns sections that enter the junction but are NOT in main_sections.

        Tries four methods in order:
          1. node.getInternalConnections() -> turn.getOrigin() (some Aimsun versions)
          2. node entrance-section methods: getEntranceSections / getFromSections /
             getEntranceSection variants
          3. GKJunction child-node traversal (intersection_id may be a GKJunction
             whose child GKNodes are the actual network nodes that sections connect to)
          4. Full section-catalog scan matching destination node ID, including
             child-node IDs collected in method 3
          5. One-step upstream feeder expansion from the side sections found
             above, to catch very short junction-adjacent links whose queues
             actually form on the immediately upstream section
        """
        main_set  = set(main_sections)
        side_secs = []
        seen      = set()

        try:
            from PyANGKernel import GKSystem
            model = GKSystem.getSystem().getActiveModel()
            if model is None:
                self._print(
                    f"[STATS] side_sections inter={intersection_id}: "
                    f"PyANGKernel model is None"
                )
                return []

            catalog = model.getCatalog()
            obj = catalog.find(intersection_id)
            gk_sec_type = model.getType('GKSection')
            if gk_sec_type is None:
                return []
            all_sections = list(catalog.getObjectsByType(gk_sec_type))

            def _collect_from_node(node):
                """Try every known entrance-section API on a GKNode/GKJunction."""
                found = []
                seen_local = set()
                for method_name in (
                    'getInternalConnections',
                    'getEntranceSections',
                    'getFromSections',
                    'getIncomingSections',
                    'getEntranceSection',
                ):
                    fn = getattr(node, method_name, None)
                    if not callable(fn):
                        continue
                    try:
                        result = fn()
                        if result is None:
                            continue
                        # getInternalConnections returns turning objects with getOrigin()
                        # entrance/from methods return section objects directly
                        items = list(result) if hasattr(result, '__iter__') else [result]
                        for item in items:
                            try:
                                # Try as a turning (has getOrigin)
                                orig = getattr(item, 'getOrigin', None)
                                if callable(orig):
                                    sec_obj = orig()
                                    if sec_obj is not None:
                                        sid = sec_obj.getId()
                                        if sid and 0 < sid < 10_000_000 and sid not in seen_local:
                                            seen_local.add(sid)
                                            found.append(sid)
                                        continue
                                # Try as a section directly
                                sid = item.getId()
                                if sid and 0 < sid < 10_000_000 and sid not in seen_local:
                                    seen_local.add(sid)
                                    found.append(sid)
                            except Exception:
                                continue
                        if found:
                            self._print(
                                f"[STATS] side_sections inter={intersection_id}: "
                                f"{method_name} -> {found}"
                            )
                    except Exception:
                        continue
                return found

            # ── Method 1 & 2: direct node entrance methods ─────────────────
            if obj is not None:
                result = _collect_from_node(obj)
                for sid in result:
                    # Exclude the junction's own ID — getEntranceSections
                    # sometimes returns the node/junction ID itself, which is
                    # not a road section and has no traffic statistics.
                    if sid == intersection_id:
                        continue
                    if sid not in seen and sid not in main_set:
                        seen.add(sid)
                        side_secs.append(sid)


            # ── Method 3: if obj is a GKJunction, traverse child nodes ─────
            # In many Aimsun models the IntersectionID is the GKJunction (signal
            # controller) ID; the actual network nodes are children of it.
            child_node_ids = set()
            if obj is not None:
                for child_fn in ('getNodes', 'getJunctionNodes', 'getChildNodes'):
                    fn = getattr(obj, child_fn, None)
                    if not callable(fn):
                        continue
                    try:
                        nodes = list(fn())
                        for child in nodes:
                            try:
                                child_node_ids.add(child.getId())
                                result = _collect_from_node(child)
                                for sid in result:
                                    if sid not in seen and sid not in main_set:
                                        seen.add(sid)
                                        side_secs.append(sid)
                            except Exception:
                                continue
                    except Exception:
                        continue

            # ── Method 4: full section-catalog scan ─────────────────────────
            # Match sections whose destination node ID is intersection_id OR
            # any child node ID collected above.
            target_ids = {intersection_id} | child_node_ids

            n_scanned = 0
            for sec in all_sections:
                n_scanned += 1
                try:
                    dest = sec.getDestination()
                    if dest is None:
                        continue
                    if dest.getId() in target_ids:
                        sec_id = sec.getId()
                        if sec_id and sec_id > 0 and sec_id not in seen and sec_id not in main_set:
                            seen.add(sec_id)
                            side_secs.append(sec_id)
                except Exception:
                    continue

            self._print(
                f"[STATS] side_sections inter={intersection_id}: "
                f"method4 (catalog scan {n_scanned} secs, targets={target_ids}) "
                f"-> {side_secs}"
            )

            # Method 5: expand one hop upstream from each side section.
            # This helps when the section touching the junction is very short
            # and the queue actually sits on the feeder section behind it.
            by_dest_node = {}
            sec_origin = {}
            for sec in all_sections:
                try:
                    sec_id = sec.getId()
                    if not sec_id or sec_id <= 0:
                        continue
                    origin = sec.getOrigin()
                    dest = sec.getDestination()
                    origin_id = origin.getId() if origin is not None else None
                    dest_id = dest.getId() if dest is not None else None
                    sec_origin[sec_id] = origin_id
                    if dest_id is not None:
                        by_dest_node.setdefault(dest_id, []).append(sec_id)
                except Exception:
                    continue

            expanded = list(side_secs)
            feeder_map = {}
            for sid in list(side_secs):
                origin_id = sec_origin.get(sid)
                if origin_id is None:
                    continue
                feeders = []
                for feeder_id in by_dest_node.get(origin_id, []):
                    if feeder_id in main_set or feeder_id in seen or feeder_id == sid:
                        continue
                    seen.add(feeder_id)
                    feeders.append(feeder_id)
                    expanded.append(feeder_id)
                if feeders:
                    feeder_map[sid] = sorted(feeders)

            if feeder_map:
                self._print(
                    f"[STATS] side_sections inter={intersection_id}: "
                    f"upstream_feeders -> {feeder_map}"
                )

            return sorted(expanded)

        except Exception as e:
            self._print(
                f"[STATS] side_sections inter={intersection_id}: "
                f"topology query failed: {e}"
            )
            return []

    @staticmethod
    def _sections_from_det_ids(det_ids: list) -> list:
        """Get section IDs from a flat list of detector IDs.
        Skips detectors not found in the model (report < 0) or returning
        an invalid section ID (0 or negative).
        """
        sections = []
        seen = set()
        for det_id in det_ids:
            try:
                props = AKIDetGetPropertiesDetectorById(det_id)
                if props.report < 0:
                    continue  # detector not found in model
                sec = props.IdSection
                if sec and sec > 0 and sec not in seen:
                    seen.add(sec)
                    sections.append(sec)
            except Exception:
                pass
        return sections

    def _append_csv(self, path: str, headers: list, row: list):
        file_exists = os.path.isfile(path)
        try:
            with open(path, 'a', newline='') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(headers)
                writer.writerow(row)
        except Exception as e:
            self._print(f"[STATS] WARNING: could not write {path}: {e}")
