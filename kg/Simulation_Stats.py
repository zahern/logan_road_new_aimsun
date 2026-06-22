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

        # ── pre-arm coordination stats (populated via record_prearm_stats) ──
        self._prearm_stats: dict = {
            "fired": 0,
            "success": 0,
            "missed": 0,
            "expired": 0,
            "discarded": 0,
            "late_success": 0,
            "late_success_delay_s": 0,
        }

        # ── network-level section stats (populated via collect_network_stats_at_finish)
        self._net_total_flow_veh:  int   = 0
        self._net_avg_density_vkm: float = 0.0
        self._net_avg_speed_kmh:   float = 0.0
        # Per-type total distance traveled (km) — used to convert delay(sec/km) → total pax-delay
        self._net_bus_total_dist_km:   float = 0.0
        self._net_car_total_dist_km:   float = 0.0
        self._net_hov_total_dist_km:   float = 0.0
        self._net_truck_total_dist_km: float = 0.0
        self._net_debug: dict = {
            'sim_time_s': 0.0,
            'section_count': 0,
            'stats_ok_sections': 0,
            'snapshot_ok_sections': 0,
            'snapshot_sections_with_vehicles': 0,
            'stats_zero_sections': 0,
            'snapshot_zero_sections': 0,
            'sections_missing_length': 0,
            'source': 'none',
        }

        # ── incremental network stats accumulator (sampled every N steps) ──
        # These are populated by accumulate_network_step() called from
        # AAPIPostManage and used by collect_network_stats_at_finish as a
        # fallback when the AKIEst API returns zeros at finish time.
        self._incr_net_sections: set = set()
        self._incr_net_flow_sum:    float = 0.0   # cumulative veh/h sum
        self._incr_net_density_sum: float = 0.0   # cumulative veh/km/lane sum
        self._incr_net_speed_sum:   float = 0.0   # cumulative km/h sum
        self._incr_net_delay_sum:   float = 0.0   # cumulative delay s/km sum
        self._incr_net_samples:     int   = 0     # number of sample steps

        # ── per-intersection density/speed/flow/queue accumulators ──
        # Keyed by intersection ID.  Populated by accumulate_intersection_step().
        self._inter_dsf: dict = {}   # {iid: {density_sum, speed_sum, flow_sum, queue_sum, samples}}

        # ── per-section density/speed/flow/queue accumulators ──
        # Keyed by section ID.  Populated alongside intersection accumulation.
        self._section_dsf: dict = {}  # {sec_id: {density_sum, speed_sum, flow_sum, queue_sum, samples, length_km, inter_id}}
        self._section_dsf_last_t: float = -999.0  # last sample time
        self._incr_net_sec_ok:      int   = 0     # sections with data across all samples
        self._incr_net_last_t:      float = -999.0  # last sample time

        # analytical objective (from harmony search / URTSP objective fn)
        self.obj_bus_delay          = 0.0
        self.obj_other_delay        = 0.0
        self.obj_avg_passenger_delay = 0.0
        self.obj_steps              = 0

        # ── vehicle type positions (resolved in finalise_init) ─────────────
        self._car_pos = -1
        self._bus_pos = -1
        self._hov_pos = -1
        self._truck_pos = -1
        self._car_type_name = ''
        self._bus_type_name = ''
        self._hov_type_name = ''
        self._truck_type_name = ''
        self._section_geom_cache: dict = {}

        # ── per-intersection green/red accumulators ──
        # {iid: {'green': total_s, 'red': total_s, 'by_phase': {phase: {'green': s, 'red': s}}}}
        self._inter_signal_times = {}
        self._last_phase_state = {}  # {iid: {'phase': int, 'start_time': float, 'is_green': bool}}

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

    def _get_section_geometry(self, sec_id: int):
        cached = self._section_geom_cache.get(sec_id)
        if cached is not None:
            return cached
        try:
            sec_info = AKIInfNetGetSectionANGInf(sec_id)
            if getattr(sec_info, 'report', -1) < 0:
                self._section_geom_cache[sec_id] = None
                return None
            length_m = float(getattr(sec_info, 'length', 0.0) or 0.0)
            if length_m <= 0.0:
                self._section_geom_cache[sec_id] = None
                return None
            lane_count = max(
                int(getattr(sec_info, 'nbCentralLanes', 0) or 0)
                + int(getattr(sec_info, 'nbSideLanes', 0) or 0),
                1,
            )
            geom = {
                'length_m': length_m,
                'length_km': length_m / 1000.0,
                'lane_count': lane_count,
                'lane_length_km': (length_m / 1000.0) * lane_count,
                'speed_limit_kmh': float(getattr(sec_info, 'speedLimit', 0.0) or 0.0),
            }
            self._section_geom_cache[sec_id] = geom
            return geom
        except Exception:
            self._section_geom_cache[sec_id] = None
            return None

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

        car_occ = float(config.get('CarOcc', 1.2))
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

        # When a junction has NO detectors and NO explicit MainSections (e.g.
        # 19363), we still want side delay.  Use topology to discover ALL
        # incoming sections, classify the corridor ones as main (via BusPhase
        # approach heuristic) and the rest as side.
        if not main_sections and not side_sections:
            all_incoming = self._side_sections_from_topology(iid, [])
            if all_incoming:
                # With no main exclusion list, _side_sections_from_topology
                # returns ALL incoming sections.  We'll treat them all as side
                # sections so side delay is at least tracked.
                side_sections = list(all_incoming)
                self._print(
                    f"[STATS] No detectors for inter={iid} — treating all "
                    f"{len(side_sections)} topology sections as side: {side_sections}"
                )

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

            # No call detectors configured (e.g. junction only has detection_zone_m):
            # fall back to the main approach sections derived from topology.
            # Any bus present on a main approach section is treated as having
            # entered the TT measurement window.
            if not call_sections and main_sections:
                call_sections = list(main_sections)
                self._print(
                    f"[STATS] inter={iid}: no BusCallDetectors — using "
                    f"{len(call_sections)} topology approach section(s) for bus TT"
                )
                if not exit_sections:
                    exit_sections = list(main_sections)
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
            '_section_closed_vids': set(),  # veh_ids whose trip was already recorded by section-based tracker; cleared on zone re-entry
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
            'n_natural_green': 0,  # bus will naturally clear on green — no TSP needed
            # Duration accumulators for average GE / insertion reporting
            'total_extension_s': 0.0,   # sum of all granted GE durations
            'total_insertion_s': 0.0,   # sum of all granted insertion durations
            # Delay between insertion grant and bus arrival at stopline.
            # Captures "insertion granted but bus not immediately at green" outcomes.
            'total_insertion_wait_s': 0.0,
            'n_insertion_wait_samples': 0,
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

        def _vehicle_type_name(pos):
            try:
                raw = AKIVehGetVehTypeName(pos)
            except Exception:
                return ""
            if isinstance(raw, str):
                return raw.lower()
            for flag in (True, False):
                try:
                    converted = AKIConvertToAsciiString(raw, flag)
                    if isinstance(converted, str):
                        return converted.lower()
                    s = str(converted)
                    if "<swig" not in s.lower():
                        return s.lower()
                except Exception:
                    pass
            s_raw = str(raw)
            if "<swig" not in s_raw.lower():
                return s_raw.lower()
            try:
                import ctypes
                if "0x" in s_raw:
                    ptr_val = int(s_raw.split("0x")[1].rstrip(">").strip(), 16)
                    name_w = ctypes.wstring_at(ptr_val)
                    if name_w:
                        return name_w.lower()
            except Exception:
                pass
            try:
                import ctypes
                if "0x" in s_raw:
                    ptr_val = int(s_raw.split("0x")[1].rstrip(">").strip(), 16)
                    name_b = ctypes.string_at(ptr_val, 128)
                    for enc in ("utf-16-le", "utf-8"):
                        txt = name_b.decode(enc, errors="ignore").split("\x00")[0]
                        if txt and txt.isprintable():
                            return txt.lower()
            except Exception:
                pass
            return ""

        try:
            nb = AKIVehGetNbVehTypes()
            for pos in range(1, nb + 1):   # Aimsun positions are 1-based
                name = _vehicle_type_name(pos)
                self._print(f"[STATS] veh type pos={pos} name='{name}'")
                # HOV must be detected BEFORE car — "HOV Car" contains "car".
                # If car matched HOV Car first, the regular Car type would be missed.
                if self._hov_pos < 0 and 'hov' in name:
                    self._hov_pos = pos
                    self._hov_type_name = name
                if self._car_pos < 0 and any(
                        x in name for x in ('car', 'pv', 'private', 'auto', 'vehicle', 'pkw')) \
                        and 'hov' not in name:   # don't absorb "HOV Car" into the car stat
                    self._car_pos = pos
                    self._car_type_name = name
                if self._bus_pos < 0 and any(
                        x in name for x in ('bus', 'transit', 'pt', 'autobus', 'omnibus')):
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

        if self._hov_pos <= 0:
            self._hov_pos = _fallback_type_pos("HOV Car")
            if self._hov_pos <= 0:
                self._hov_pos = _fallback_type_pos("HOV")
            if self._hov_pos > 0 and not self._hov_type_name:
                self._hov_type_name = "hov(fallback)"

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

        # Positional HOV fallback: runs AFTER car/bus/truck are resolved so
        # _taken is populated.  In this Aimsun build AKIVehGetVehTypeName
        # returns SWIG objects (not strings), so named_scan all=-1 and we
        # fall through to here.  HOV gets the first position not used by the
        # other three types (typically position 2 = "HOV Car").
        if self._hov_pos <= 0:
            try:
                nb = AKIVehGetNbVehTypes()
                _taken = {self._car_pos, self._bus_pos, self._truck_pos}
                for _pos in range(1, nb + 1):
                    if _pos not in _taken:
                        self._hov_pos = _pos
                        self._hov_type_name = self._hov_type_name or f"hov(pos{_pos})"
                        break
            except Exception:
                pass

        # PT vehicles are the strongest source of truth for the real bus class.
        try:
            pt_type_counts = {}
            n_lines = AKIPTGetNumberLines()
            for li in range(n_lines):
                line_id = AKIPTGetIdLine(li)
                try:
                    _line_type_fn = globals().get("AKIPTGetVehTypeOfLine")
                    if _line_type_fn is not None:
                        _line_tp = int(_line_type_fn(line_id) or -1)
                        if _line_tp > 0:
                            pt_type_counts[_line_tp] = pt_type_counts.get(_line_tp, 0) + 10
                            continue
                except Exception:
                    pass
                for vi in range(AKIGetNbVehiclesFollowingPTLine(line_id)):
                    veh_id = AKIGetVehicleFollowingPTLine(line_id, vi)
                    inf = AKIPTVehGetInf(veh_id)
                    vtype = int(getattr(inf, 'type', -1) or -1)
                    if getattr(inf, 'report', -1) >= 0 and vtype > 0:
                        pt_type_counts[vtype] = pt_type_counts.get(vtype, 0) + 1
            if pt_type_counts:
                pt_bus_pos = max(pt_type_counts, key=pt_type_counts.get)
                self._bus_pos = _sanitize_type_pos(pt_bus_pos)
                self._bus_type_name = self._bus_type_name or f"pt_inferred_{pt_bus_pos}"
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
            f"truck_pos={self._truck_pos}('{self._truck_type_name}') "
            f"hov_pos={self._hov_pos}('{self._hov_type_name}') | "
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
        # Close stale zone-tracking entries (bus not seen for 60 s = zone exit)
        self._flush_stale_pt_detections(time)

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
                        # Mark so zone-based tracker skips this traversal (dedup)
                        d['_section_closed_vids'].add(veh_id)
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
            'ge_trivial':         'n_skipped_ge',
            'ins_trivial':        'n_skipped_ins',
            'no_action':          'n_detected_no_action',
            'reward_no_action':   'n_detected_no_action',
            'natural_green':      'n_natural_green',
            # Focus / Kalman suppression — another bus has corridor priority
            'focus_suppressed':   'n_focus_suppressed',
            # ETA horizon — bus detected but too far for any useful strategy
            'eta_horizon':        'n_eta_horizon',
        }.get(skip_type)
        if key:
            d.setdefault(key, 0)
            d[key] += 1

    def record_tsp_extension_duration(self, intersection_id: int, duration_s: float):
        """Accumulate the granted GE duration (seconds) for average reporting."""
        if intersection_id not in self._inter:
            return
        self._inter[intersection_id]['total_extension_s'] += max(0.0, float(duration_s))

    def record_tsp_insertion_duration(self, intersection_id: int, duration_s: float):
        """Accumulate the granted insertion phase duration (seconds) for average reporting."""
        if intersection_id not in self._inter:
            return
        self._inter[intersection_id]['total_insertion_s'] += max(0.0, float(duration_s))

    def record_tsp_insertion_wait(self, intersection_id: int, wait_s: float):
        """
        Record time from insertion grant until expected bus stopline arrival.
        This is a direct visibility metric for delayed insertion outcomes.
        """
        if intersection_id not in self._inter:
            return
        wait_s = max(0.0, float(wait_s))
        d = self._inter[intersection_id]
        d['total_insertion_wait_s'] += wait_s
        d['n_insertion_wait_samples'] += 1

    def record_pt_bus_detection(self, intersection_id: int, veh_id: int, time: float):
        """
        Called by the controller every sim-step while a PT bus is within the
        detection radius of this intersection.

        This supplements section-based bus travel time tracking for intersections
        where buses travel on transit-link sections that are invisible to
        AKIVehStateGetVehicleInfSection (those sections return report<0).

        Zone-exit and trip recording is handled by two complementary calls:
          • record_pt_bus_exit()        — called explicitly by _track_all_bus_positions
                                          on zone_exit events (preferred path).
          • _flush_stale_pt_detections() — sweeps entries not refreshed in 60 s
                                          (fallback for when zone_exit is missed).
        """
        if intersection_id not in self._inter:
            return
        d = self._inter[intersection_id]

        # Mark bus as seen (distinct headcount)
        d['_seen_bus_ids'].add(veh_id)

        # Zone-entry: record first-seen time; update last-seen on every call
        pt_entry = d.setdefault('_pt_bus_entry', {})
        pt_last  = d.setdefault('_pt_last_seen', {})
        if veh_id not in pt_entry:
            pt_entry[veh_id] = time   # zone entry
            # Clear the section-closed flag so a fresh traversal can be tracked
            d.get('_section_closed_vids', set()).discard(veh_id)
        pt_last[veh_id] = time        # refresh last-seen on every detection call

    def record_pt_bus_exit(self, intersection_id: int, veh_id: int, time: float):
        """
        Called by _track_all_bus_positions on a zone_exit event for (veh_id, jid).
        Closes the pending bus-TT entry and records the trip if travel time is valid.
        Skips recording if the section-based tracker already recorded this traversal
        (prevents double-counting when call/exit sections fall within the zone radius).
        """
        if intersection_id not in self._inter:
            return
        d = self._inter[intersection_id]
        pt_entry = d.get('_pt_bus_entry', {})
        if veh_id not in pt_entry:
            return
        entry_t  = pt_entry.pop(veh_id)
        d.get('_pt_last_seen', {}).pop(veh_id, None)

        # Skip if section-based tracker already recorded this trip for this veh_id
        closed = d.get('_section_closed_vids', set())
        if veh_id in closed:
            closed.discard(veh_id)
            return

        travel_t = time - entry_t
        if 5.0 < travel_t < 600.0:
            d['bus_trips'].append((entry_t, time, travel_t))
            bus_occ = float(d.get('bus_occ', 40.0))
            # Track minimum zone-transit time as free-flow reference, then compute delay
            min_tt = d.get('bus_min_tt_s', None)
            if min_tt is None or travel_t < min_tt:
                d['bus_min_tt_s'] = travel_t
                min_tt = travel_t
            bus_delay_s = max(travel_t - min_tt, 0.0)
            d['traj_bus_veh_passages'] = d.get('traj_bus_veh_passages', 0) + 1
            d['traj_bus_passengers']   = d.get('traj_bus_passengers', 0.0) + bus_occ
            d['traj_bus_delay']        = d.get('traj_bus_delay', 0.0) + bus_delay_s * bus_occ

    def _flush_stale_pt_detections(self, time: float, stale_gap_s: float = 60.0):
        """
        Sweep all intersections and close bus-TT entries for vehicles not seen
        in >= stale_gap_s seconds (zone exit missed by track_all_bus_positions).
        Called at the start of track_bus_positions every sim step.
        """
        for iid, d in self._inter.items():
            pt_entry = d.get('_pt_bus_entry')
            pt_last  = d.get('_pt_last_seen')
            if not pt_entry or not pt_last:
                continue
            bus_occ = float(d.get('bus_occ', 40.0))
            stale = [
                vid for vid, last_t in list(pt_last.items())
                if vid in pt_entry and (time - last_t) >= stale_gap_s
            ]
            for vid in stale:
                entry_t = pt_entry.pop(vid)
                last_t  = pt_last.pop(vid)
                # Skip if section-based tracker already recorded this traversal
                closed = d.get('_section_closed_vids', set())
                if vid in closed:
                    closed.discard(vid)
                    continue
                travel_t = last_t - entry_t
                if 5.0 < travel_t < 600.0:
                    d['bus_trips'].append((entry_t, last_t, travel_t))
                    min_tt = d.get('bus_min_tt_s', None)
                    if min_tt is None or travel_t < min_tt:
                        d['bus_min_tt_s'] = travel_t
                        min_tt = travel_t
                    bus_delay_s = max(travel_t - min_tt, 0.0)
                    d['traj_bus_veh_passages'] = d.get('traj_bus_veh_passages', 0) + 1
                    d['traj_bus_passengers']   = d.get('traj_bus_passengers', 0.0) + bus_occ
                    d['traj_bus_delay']        = d.get('traj_bus_delay', 0.0) + bus_delay_s * bus_occ

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
        # Two bus delay sources:
        #   delay_bus         — section-based (all steps, approach sections)
        #   traj_bus_delay    — trajectory-based (call→exit detector pairs)
        # We prefer trajectory when it's larger AND use CONSISTENT denominator:
        # if trajectory delay is chosen, use trajectory passengers; if section-based,
        # use section passengers.  Mixing numerator from one source with denominator
        # from the other inflates the denominator when DCTSP activates more trajectory
        # tracking, making avg delay APPEAR lower without real improvement.
        _traj_delay = d.get('traj_bus_delay', 0.0)
        _traj_pax   = d.get('traj_bus_passengers', 0.0)
        _traj_veh   = d.get('traj_bus_veh_passages', 0)
        if _traj_delay > d['delay_bus'] and _traj_pax > 0:
            # Trajectory measurement is richer — use it with its own denominator
            eff_bus_delay = _traj_delay
            eff_bus_passengers   = _traj_pax
            eff_bus_veh_passages = max(d['bus_veh_passages'], _traj_veh)
        else:
            # Fall back to section-based measurement
            eff_bus_delay = d['delay_bus']
            eff_bus_passengers   = d['bus_passengers']
            eff_bus_veh_passages = d['bus_veh_passages']
            # Supplement with trajectory if section coverage was incomplete
            if _traj_pax > eff_bus_passengers:
                eff_bus_passengers   = _traj_pax
                eff_bus_veh_passages = max(eff_bus_veh_passages, _traj_veh)
                eff_bus_delay        = max(eff_bus_delay, _traj_delay)

        # Read accumulated signal times (do NOT reset — accumulators are populated
        # during the simulation by AAPIManage phase-tracking code).
        # Initialise entry lazily so first call never raises KeyError.
        self._inter_signal_times.setdefault(iid, {'green': 0.0, 'red': 0.0, 'by_phase': {}})
        self._last_phase_state.setdefault(iid, {'phase': None, 'start_time': None, 'is_green': None})
        total_green = self._inter_signal_times[iid].get('green', 0.0)
        total_red   = self._inter_signal_times[iid].get('red',   0.0)
        added_bus_delay        = max(0.0, eff_bus_delay - d['delay_bus'])
        added_bus_passengers   = max(0.0, eff_bus_passengers - d['bus_passengers'])
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

        _sim_time_s = float(self._net_debug.get('sim_time_s', 0.0) or 0.0)
        _sim_hrs_inter = max(_sim_time_s / 3600.0, 1.0 / 3600.0)
        avg_main_pass_delay_per_hr = main_delay_hrs / _sim_hrs_inter
        avg_side_pass_delay_per_hr = side_delay_hrs / _sim_hrs_inter
        avg_total_pass_delay_per_hr = total_delay_hrs / _sim_hrs_inter

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
            'avg_main_pass_delay_per_hr': avg_main_pass_delay_per_hr,
            'avg_side_pass_delay_per_hr': avg_side_pass_delay_per_hr,
            'avg_total_pass_delay_per_hr': avg_total_pass_delay_per_hr,
            'sim_duration_hrs':      _sim_hrs_inter,
            'n_detections':          d['n_detections'],
            'n_extensions':          d['n_extensions'],
            'n_insertions':          d['n_insertions'],
            'n_exit_clears':         d['n_exit_clears'],
            'n_cap_clears':          d['n_cap_clears'],
            'n_skipped_ge':          d.get('n_skipped_ge', 0),
            'n_skipped_ins':         d.get('n_skipped_ins', 0),
            'n_detected_no_action':  d.get('n_detected_no_action', 0),
            'n_natural_green':       d.get('n_natural_green', 0),
            'total_extension_s':     d.get('total_extension_s', 0.0),
            'total_insertion_s':     d.get('total_insertion_s', 0.0),
            'total_insertion_wait_s': d.get('total_insertion_wait_s', 0.0),
            'n_insertion_wait_samples': d.get('n_insertion_wait_samples', 0),
            'avg_extension_s': (
                d.get('total_extension_s', 0.0) / d['n_extensions']
                if d['n_extensions'] > 0 else 0.0),
            'avg_insertion_s': (
                d.get('total_insertion_s', 0.0) / d['n_insertions']
                if d['n_insertions'] > 0 else 0.0),
            'avg_insertion_wait_s': (
                d.get('total_insertion_wait_s', 0.0) / d.get('n_insertion_wait_samples', 0)
                if d.get('n_insertion_wait_samples', 0) > 0 else 0.0),
            'total_vehicles':        d['vehicles'] + added_bus_veh_passages,
            'n_main_sections':       len(d.get('main_sections', [])),
            'n_side_sections':       len(d.get('side_sections', [])),
            'side_sections_resolved': bool(d.get('side_sections_resolved', False)),
            'main_sections':         list(d.get('main_sections', [])),
            'side_sections':         list(d.get('side_sections', [])),
            # Density / speed / flow / queue (from incremental vehicle-state sampling)
            'avg_density_vkm':       self._inter_dsf_avg(iid, 'density_sum'),
            'avg_speed_kmh':         self._inter_dsf_avg(iid, 'speed_sum'),
            'avg_flow_veh_h':        self._inter_dsf_avg(iid, 'flow_sum'),
            'avg_queue_veh':         self._inter_dsf_avg(iid, 'queue_sum'),
            # Objective
            'objective':             inter_objective,
            # Green/red totals
            'total_green_s': total_green,
            'total_red_s': total_red,
        }
        return result

    def _inter_dsf_avg(self, iid: int, key: str) -> float:
        """Return time-averaged density/speed/flow for an intersection."""
        acc = self._inter_dsf.get(iid)
        if acc and acc['samples'] > 0:
            return round(float(acc.get(key, 0.0)) / acc['samples'], 4)
        return 0.0

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
        all_distinct_bus_ids = set()
        all_distinct_car_ids = set()
        all_distinct_truck_ids = set()
        total_dets         = 0
        total_exts         = 0
        total_ins          = 0
        total_skipped_ge   = 0
        total_skipped_ins  = 0
        total_no_action    = 0
        total_natural_green = 0
        total_extension_s  = 0.0
        total_insertion_s  = 0.0
        total_insertion_wait_s = 0.0
        total_insertion_wait_n = 0
        sim_total_delay    = 0.0
        sim_bus_delay      = 0.0
        sim_car_delay      = 0.0
        sim_truck_delay    = 0.0
        total_passengers   = 0.0
        bus_passengers     = 0.0
        car_passengers     = 0.0
        truck_passengers   = 0.0

        for iid in self._inter:
            d = self._inter[iid]
            k = self._kpis_for(iid)
            total_bus_tt_hrs    += k['bus_total_tt_hrs']
            total_pass_delay    += k['total_pass_delay_hrs']
            total_main_delay    += k['main_pass_delay_hrs']
            total_side_delay    += k['side_pass_delay_hrs']
            total_n_buses       += k['n_buses']
            all_distinct_bus_ids.update(d.get('_seen_bus_ids', set()))
            all_distinct_car_ids.update(d.get('_seen_car_ids', set()))
            all_distinct_truck_ids.update(d.get('_seen_truck_ids', set()))
            total_dets          += k['n_detections']
            total_exts          += k['n_extensions']
            total_ins           += k['n_insertions']
            total_skipped_ge    += k['n_skipped_ge']
            total_skipped_ins   += k['n_skipped_ins']
            total_no_action     += k['n_detected_no_action']
            total_natural_green += k['n_natural_green']
            total_extension_s   += k['total_extension_s']
            total_insertion_s   += k['total_insertion_s']
            total_insertion_wait_s += k.get('total_insertion_wait_s', 0.0)
            total_insertion_wait_n += k.get('n_insertion_wait_samples', 0)
            sim_total_delay     += k['delay_total_pax_s']
            sim_bus_delay       += k['delay_bus_pax_s']
            sim_car_delay       += k['delay_car_pax_s']
            sim_truck_delay     += k['delay_truck_pax_s']
            total_passengers    += k['passengers']
            bus_passengers      += k['bus_passengers']
            car_passengers      += k['car_passengers']
            truck_passengers    += k['truck_passengers']

        total_distinct_buses = len(all_distinct_bus_ids)
        total_distinct_cars = len(all_distinct_car_ids)
        total_distinct_trucks = len(all_distinct_truck_ids)

        avg_bus_tt_s = (
            (total_bus_tt_hrs * 3600.0 / total_n_buses)
            if total_n_buses > 0 else 0.0
        )
        avg_pass_delay_s = (
            sim_total_delay / total_passengers
            if total_passengers > 0 else 0.0
        )
        avg_obj_delay = (
            self.obj_avg_passenger_delay / self.obj_steps
            if self.obj_steps > 0 else avg_pass_delay_s
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

        # ── Network-level total pax delay from Aimsun per-type stats ─────────────
        # Computed as: Σ [entry_delay(sec/km) × total_distance(km) × occupancy] per type
        # Uses the per-type delay rates and distances collected by collect_network_stats_at_finish.
        # This matches Aimsun's Statistics panel calculation:
        #   pax_delay_pax_s = delay_sec_per_km × total_distance_km × occupancy
        _net_bus_delay_s   = getattr(self, '_net_entry_delay_bus',   0.0) or 0.0
        _net_car_delay_s   = getattr(self, '_net_entry_delay_car',   0.0) or 0.0
        _net_hov_delay_s   = getattr(self, '_net_entry_delay_hov',   0.0) or 0.0
        _net_truck_delay_s = getattr(self, '_net_entry_delay_truck', 0.0) or 0.0
        _net_bus_dist_km   = getattr(self, '_net_bus_total_dist_km',   0.0) or 0.0
        _net_car_dist_km   = getattr(self, '_net_car_total_dist_km',   0.0) or 0.0
        _net_hov_dist_km   = getattr(self, '_net_hov_total_dist_km',   0.0) or 0.0
        _net_truck_dist_km = getattr(self, '_net_truck_total_dist_km', 0.0) or 0.0
        _bus_occ   = float(next(iter(self._inter.values()), {}).get('bus_occ', 40.0) if self._inter else 40.0)
        _car_occ   = float(next(iter(self._inter.values()), {}).get('car_occ', 1.5) if self._inter else 1.5)
        _truck_occ = float(next(iter(self._inter.values()), {}).get('truck_occ', _car_occ) if self._inter else 1.0)
        _hov_occ   = max(_car_occ, 2.0)   # HOV by definition ≥ 2 passengers
        _net_pax_delay_bus_pax_s   = _net_bus_delay_s   * _net_bus_dist_km   * _bus_occ
        _net_pax_delay_car_pax_s   = _net_car_delay_s   * _net_car_dist_km   * _car_occ
        _net_pax_delay_hov_pax_s   = _net_hov_delay_s   * _net_hov_dist_km   * _hov_occ
        _net_pax_delay_truck_pax_s = _net_truck_delay_s * _net_truck_dist_km * _truck_occ
        _net_total_pax_delay_pax_s = (_net_pax_delay_bus_pax_s + _net_pax_delay_car_pax_s
                                      + _net_pax_delay_hov_pax_s + _net_pax_delay_truck_pax_s)

        # [NET_PAX_AUDIT] — Explains why entry/exit delay (s/km rate) and total
        # pax delay (pax·s) can show opposite rankings between strategies:
        #   - entry/exit delay (s/km): Aimsun's average delay RATE per km traveled.
        #     TSP extends green for buses → cross-street reds are longer → higher
        #     average delay rate for ALL vehicles (including cross-street cars).
        #   - total pax delay (pax·s): delay × vehicle_count × occupancy summed.
        #     TSP saves buses (40 pax/veh) at the cost of cars (1.5 pax/veh).
        #     Net pax saving is positive because bus occupancy >> car occupancy.
        #   Result: TSP strategies can show HIGHER s/km delay but LOWER pax·s —
        #   this is correct physics, not a calculation error.
        #
        #   Path chosen: 'network' when _net_total > corridor; else 'corridor'.
        _net_path_reason = (
            f"net={_net_total_pax_delay_pax_s:.0f}pax·s > corr={sim_total_delay:.0f}pax·s → using network"
            if _net_total_pax_delay_pax_s > sim_total_delay
            else f"net={_net_total_pax_delay_pax_s:.0f}pax·s ≤ corr={sim_total_delay:.0f}pax·s → using corridor"
        )
        self._print(
            f"[NET_PAX_AUDIT] bus: delay={_net_bus_delay_s:.1f}s/km dist={_net_bus_dist_km:.1f}veh·km"
            f" → {_net_pax_delay_bus_pax_s:.0f}pax·s | "
            f"car: delay={_net_car_delay_s:.1f}s/km dist={_net_car_dist_km:.1f}veh·km"
            f" → {_net_pax_delay_car_pax_s:.0f}pax·s | {_net_path_reason}"
        )

        # Prefer network-level pax delay when available (non-zero and larger than
        # corridor-only accumulation); fall back to corridor accumulation.
        if _net_total_pax_delay_pax_s > sim_total_delay:
            sim_total_delay = _net_total_pax_delay_pax_s
            sim_bus_delay   = _net_pax_delay_bus_pax_s
            sim_car_delay   = _net_pax_delay_car_pax_s + _net_pax_delay_hov_pax_s
            sim_truck_delay = _net_pax_delay_truck_pax_s
            total_pass_delay = _net_total_pax_delay_pax_s / 3600.0

        # ── Objective metric ──────────────────────────────────────────────────
        _delay_hrs = sim_total_delay / 3600.0
        throughput_per_delay_hr = (
            total_passengers / _delay_hrs
            if _delay_hrs > 1e-6 else 0.0
        )

        # ── Avg delay per simulation-hour (for main and side separately) ──────
        # Divide accumulated delay (pax·hrs) by simulation duration (hrs).
        # sim_time_s comes from the network stats debug dict populated at AAPIFinish.
        _sim_time_s = float(self._net_debug.get('sim_time_s', 0.0) or 0.0)
        _sim_hrs    = max(_sim_time_s / 3600.0, 1.0 / 3600.0)  # at least 1s to avoid div0
        avg_main_pass_delay_per_hr = total_main_delay / _sim_hrs   # pax·hrs of main delay per sim-hour
        avg_side_pass_delay_per_hr = total_side_delay / _sim_hrs   # pax·hrs of side delay per sim-hour
        avg_total_pass_delay_per_hr = total_pass_delay / _sim_hrs  # total pax·hrs delay per sim-hour

        return {
            'bus_total_tt_hrs':          total_bus_tt_hrs,
            'n_buses':                   total_n_buses,
            'n_distinct_buses':          total_distinct_buses,
            'n_distinct_cars':           total_distinct_cars,
            'n_distinct_trucks':         total_distinct_trucks,
            'avg_bus_tt_s':              avg_bus_tt_s,
            'total_pass_delay_hrs':      total_pass_delay,
            'main_pass_delay_hrs':           total_main_delay,
            'side_pass_delay_hrs':           total_side_delay,
            'avg_main_pass_delay_per_hr':    avg_main_pass_delay_per_hr,
            'avg_side_pass_delay_per_hr':    avg_side_pass_delay_per_hr,
            'avg_total_pass_delay_per_hr':   avg_total_pass_delay_per_hr,
            'sim_duration_hrs':              _sim_hrs,
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
            'n_tsp_natural_green':       total_natural_green,
            'total_extension_s':         total_extension_s,
            'total_insertion_s':         total_insertion_s,
            'avg_extension_s': (total_extension_s / total_exts if total_exts > 0 else 0.0),
            'avg_insertion_s': (total_insertion_s / total_ins  if total_ins  > 0 else 0.0),
            'avg_insertion_wait_s': (
                total_insertion_wait_s / total_insertion_wait_n
                if total_insertion_wait_n > 0 else 0.0),
            # Objective
            'throughput_per_delay_hr':   throughput_per_delay_hr,
        }

    # =========================================================================
    # COORDINATION PRE-ARM STATS
    # =========================================================================

    def record_prearm_stats(self, prearm_dict: dict):
        """
        Called from AAPIFinish after aggregating _prearm_stats from all
        CorridorCoordinator instances.
        Keys: fired, success, missed, expired, discarded,
              late_success, late_success_delay_s
        """
        for k in self._prearm_stats:
            if k == "late_success_delay_s":
                self._prearm_stats[k] = float(prearm_dict.get(k, 0.0))
            else:
                self._prearm_stats[k] = int(prearm_dict.get(k, 0))

    # =========================================================================
    # INCREMENTAL NETWORK STATS (called every ~30s from AAPIPostManage)
    # =========================================================================

    def accumulate_network_step(self, section_ids: list, time: float):
        """
        Sample section density/speed/flow periodically during the simulation.

        Called from AAPIPostManage every INCR_NET_INTERVAL_S seconds (default 30).
        Uses live vehicle state snapshots (AKIVehStateGet*) to compute density
        and speed, plus AKIEstGetParcialStatisticsSection .count for flow.

        The .flow/.density/.speed attributes on AKIEst structs are always zero
        in this Aimsun build, but .DTa and .count work fine.  So we derive:
          - density  = n_vehicles_on_section / section_length_km
          - speed    = mean vehicle CurrentSpeed (km/h)
          - flow     = sum of .count across all types / interval_hours  (veh/h)
        """
        INCR_NET_INTERVAL_S = 30.0
        if time - self._incr_net_last_t < INCR_NET_INTERVAL_S:
            return
        self._incr_net_last_t = time

        if not section_ids:
            return

        self._incr_net_sections.update(section_ids)

        step_density_w = 0.0   # sum(k_i * lane_len_i)
        step_speed_w = 0.0     # sum(v_i * L_i)
        step_flow_w = 0.0      # sum(q_i * L_i)
        step_delay_w = 0.0     # sum(d_i * L_i)  where d_i = DTa/sec_len_km (s/km)
        step_len = 0.0
        step_lane_len = 0.0
        step_n = 0

        for sec in section_ids:
            try:
                geom = self._get_section_geometry(sec)
                if geom is None:
                    continue
                sec_len_km = geom['length_km']
                sec_len_m  = geom['length_m']
                sec_lane_len_km = geom['lane_length_km']
                lane_count = max(int(geom.get('lane_count', 1) or 1), 1)

                # Skip short connectors (<20 m) — they inflate density drastically
                if sec_len_m < 20.0:
                    continue

                # ── Primary: AKIEst time-averaged stats (match Aimsun output) ────
                # .count = vehicles that COMPLETED the section in [0, time]
                # .DTa   = mean DELAY time per vehicle (seconds)  — NOT travel time
                # .TTa   = mean travel time per vehicle (seconds)  — use this for speed
                # .flow/.density/.speed are always 0 in this build — do NOT use them
                # ── Density: ALWAYS use instantaneous snapshot (n_veh / section_km) ──
                # This is the standard Aimsun definition and gives the correct
                # time-averaged density when sampled every INCR_NET_INTERVAL_S.
                # Do NOT derive density from flow/speed (q=kv) since that biases
                # toward completing vehicles and misses stationary queued vehicles.
                try:
                    n_veh_snap = max(int(AKIVehStateGetNbVehiclesSection(sec, False)), 0)
                except Exception:
                    n_veh_snap = 0
                sec_density = float(n_veh_snap) / max(sec_lane_len_km, 0.001)  # veh/km/lane
                sec_flow    = 0.0
                sec_speed   = 0.0
                sec_delay   = 0.0   # delay time in s/km (DTa / sec_len_km)

                # ── Flow: use AKIEst 30s window count (completing vehicles) ──────
                _incr_window_start = max(0.0, time - INCR_NET_INTERVAL_S)
                try:
                    st = AKIEstGetParcialStatisticsSection(sec, _incr_window_start, -1)
                    if st.report == 0:
                        _count = float(getattr(st, 'count', 0) or 0)
                        _dta   = float(getattr(st, 'DTa',   0.0) or 0.0)
                        _tta   = float(getattr(st, 'TTa',   0.0) or 0.0)
                        if _count > 0:
                            sec_flow = _count * 3600.0 / max(INCR_NET_INTERVAL_S, 1.0)
                            if _dta > 0.0 and sec_len_km > 0.0:
                                sec_delay = _dta / sec_len_km   # s/km
                        if _tta > 0.0 and sec_len_m > 0.0:
                            sec_speed = (sec_len_m / _tta) * 3.6   # km/h from mean TT (TTa)
                        # Delay fallback: if DTa == 0 but TTa > 0, estimate from
                        # entry-based delay = TTa - free_flow_TT (same as finish path).
                        if sec_delay == 0.0 and _tta > 0.0 and sec_len_m > 0.0:
                            _slim = geom.get('speed_limit_kmh') or 40.0
                            _ff_tt = sec_len_m / max(_slim / 3.6, 1.0)
                            _dta_fb = max(_tta - _ff_tt, 0.0)
                            if _dta_fb > 0.0 and sec_len_km > 0.0:
                                sec_delay = _dta_fb / sec_len_km   # s/km
                except Exception:
                    pass

                # ── Speed fallback: harmonic mean of live vehicle speeds ──────────
                if sec_speed <= 0.0 and n_veh_snap > 0:
                    inv_spd_sum = 0.0
                    spd_n = 0
                    for vi in range(n_veh_snap):
                        try:
                            vinf = AKIVehStateGetVehicleInfSection(sec, vi)
                            s = float(getattr(vinf, 'CurrentSpeed', 0.0) or 0.0)
                            if s > 0:
                                inv_spd_sum += 1.0 / s
                                spd_n += 1
                        except Exception:
                            continue
                    sec_speed = (float(spd_n) / inv_spd_sum) if inv_spd_sum > 0 else 0.0
                    if sec_density > 0 and sec_speed > 0 and sec_flow <= 0:
                        sec_flow = sec_density * sec_speed * lane_count

                # Density fallback for virtual sections (AKIVehState returns -4002 → 0).
                # Per Aimsun manual: k = q / v when snapshot unavailable.
                if sec_density == 0.0 and sec_flow > 0.0 and sec_speed > 0.0:
                    sec_density = sec_flow / (sec_speed * lane_count)

                step_density_w += sec_density * sec_lane_len_km
                step_speed_w   += sec_speed   * sec_len_km
                step_flow_w    += sec_flow    * sec_len_km
                step_delay_w   += sec_delay   * sec_len_km
                step_len += sec_len_km
                step_lane_len += sec_lane_len_km
                step_n   += 1
            except Exception:
                pass

        if step_n > 0 and step_len > 0.0:
            # Store length-weighted network averages for this sample.
            self._incr_net_flow_sum += step_flow_w / step_len
            if step_lane_len > 0.0:
                self._incr_net_density_sum += step_density_w / step_lane_len
            self._incr_net_speed_sum += step_speed_w / step_len
            if step_delay_w > 0.0:
                self._incr_net_delay_sum += step_delay_w / step_len
            self._incr_net_samples += 1
            self._incr_net_sec_ok = max(self._incr_net_sec_ok, step_n)

    def accumulate_intersection_step(self, time: float):
        """
        Sample density/speed/flow per intersection and per section.

        Called from AAPIPostManage every 30 s (same cadence as network stats).
        For each registered intersection, scans its main + side sections and
        accumulates running averages of density (veh/km/lane), speed (km/h),
        flow (veh/h) using vehicle-state snapshots and .count from AKIEst.

        Also populates per-section accumulators in self._section_dsf so a
        corridor-level per-section CSV can be written at save time.
        """
        INTERVAL_S = 30.0
        if time - self._section_dsf_last_t < INTERVAL_S:
            return
        self._section_dsf_last_t = time

        for iid, d in self._inter.items():
            all_secs = list(d.get('main_sections', [])) + list(d.get('side_sections', []))
            if not all_secs:
                continue

            inter_density_w = 0.0
            inter_speed_w = 0.0
            inter_flow_w = 0.0
            inter_queue_w = 0.0
            inter_len = 0.0
            inter_lane_len = 0.0
            inter_n = 0

            for sec in all_secs:
                try:
                    geom = self._get_section_geometry(sec)
                    if geom is None:
                        continue
                    sec_len_km = geom['length_km']
                    sec_len_m  = geom['length_m']
                    sec_lane_len_km = geom['lane_length_km']
                    lane_count = max(int(geom.get('lane_count', 1) or 1), 1)

                    # Skip short connector/internal sections (<20 m): dividing
                    # n_veh by 0.003 km inflates density to 333 veh/km for 1 car
                    if sec_len_m < 20.0:
                        continue

                    # ── Primary: AKIEst time-averaged stats ────────────────────
                    # AKIEstGetParcialStatisticsSection(sec, timSta, type) returns
                    # stats for vehicles that traversed the section SINCE timSta.
                    # Use timSta = time - INTERVAL_S to get the last 30-second window.
                    # .flow / .density / .speed are always 0 — derive from count+TTa.
                    # DTa = mean delay time (s); TTa = mean travel time (s).
                    sec_flow    = 0.0
                    sec_speed   = 0.0
                    sec_density = 0.0
                    _akiest_ok  = False
                    queued_veh  = 0
                    _window_start = max(0.0, time - INTERVAL_S)
                    try:
                        st = AKIEstGetParcialStatisticsSection(sec, _window_start, -1)
                        if st.report == 0:
                            _count = float(getattr(st, 'count', 0) or 0)
                            _dta   = float(getattr(st, 'DTa',   0.0) or 0.0)
                            _tta   = float(getattr(st, 'TTa',   0.0) or 0.0)
                            if _count > 0:
                                # Flow = vehicles completing section in last INTERVAL_S (veh/h)
                                sec_flow = _count * 3600.0 / max(INTERVAL_S, 1.0)
                            if _tta > 0.0 and sec_len_m > 0.0:
                                # Space-mean speed from mean travel time (TTa, not DTa)
                                sec_speed = (sec_len_m / _tta) * 3.6  # km/h
                            if sec_flow > 0.0 and sec_speed > 0.0:
                                _akiest_ok = True
                    except Exception:
                        pass

                    # Snapshot needed for queue count (vehicles moving <5 km/h)
                    # and as fallback for density/speed when AKIEst is insufficient
                    n_veh = max(int(AKIVehStateGetNbVehiclesSection(sec, False)), 0)
                    inv_spd_sum = 0.0
                    spd_n = 0
                    for vi in range(n_veh):
                        try:
                            vinf = AKIVehStateGetVehicleInfSection(sec, vi)
                            s = float(getattr(vinf, 'CurrentSpeed', 0.0) or 0.0)
                            if s < 5.0:
                                queued_veh += 1
                            if s > 0:
                                inv_spd_sum += 1.0 / s
                                spd_n += 1
                        except Exception:
                            continue

                    # ── Fallback: snapshot-based density/speed ─────────────────
                    sec_density = float(n_veh) / max(sec_lane_len_km, 0.001)
                    queued_veh_per_lane = float(queued_veh) / lane_count
                    if not _akiest_ok:
                        sec_speed   = (float(spd_n) / inv_spd_sum) if inv_spd_sum > 0 else 0.0
                        if sec_density > 0 and sec_speed > 0:
                            sec_flow = sec_density * sec_speed * lane_count

                    # Density fallback for virtual sections (AKIVehState returns -4002 → 0).
                    # Per Aimsun manual: k = q / v when snapshot unavailable.
                    if sec_density == 0.0 and sec_flow > 0.0 and sec_speed > 0.0:
                        sec_density = sec_flow / (sec_speed * lane_count)

                    # Per-section accumulator
                    if sec not in self._section_dsf:
                        self._section_dsf[sec] = {
                            'density_sum': 0.0, 'speed_sum': 0.0,
                            'flow_sum': 0.0, 'queue_sum': 0.0, 'samples': 0,
                            'length_km': sec_len_km, 'inter_id': iid,
                            'is_main': sec in set(d.get('main_sections', [])),
                        }
                    sd = self._section_dsf[sec]
                    sd['density_sum'] += sec_density
                    sd['speed_sum'] += sec_speed
                    sd['flow_sum'] += sec_flow
                    sd['queue_sum'] += queued_veh_per_lane
                    sd['samples'] += 1

                    inter_density_w += sec_density * sec_lane_len_km
                    inter_speed_w += sec_speed * sec_len_km
                    inter_flow_w += sec_flow * sec_len_km
                    inter_queue_w += queued_veh_per_lane * sec_lane_len_km
                    inter_len += sec_len_km
                    inter_lane_len += sec_lane_len_km
                    inter_n += 1
                except Exception:
                    continue

            if inter_n > 0 and inter_len > 0.0:
                if iid not in self._inter_dsf:
                    self._inter_dsf[iid] = {
                        'density_sum': 0.0, 'speed_sum': 0.0,
                        'flow_sum': 0.0, 'queue_sum': 0.0, 'samples': 0,
                    }
                acc = self._inter_dsf[iid]
                acc['density_sum'] += inter_density_w / max(inter_lane_len, 0.001)
                acc['speed_sum'] += inter_speed_w / inter_len
                acc['flow_sum'] += inter_flow_w / inter_len
                acc['queue_sum'] += inter_queue_w / max(inter_lane_len, 0.001)
                acc['samples'] += 1

    # =========================================================================
    # NETWORK SECTION STATISTICS (collected at AAPIFinish)
    # =========================================================================

    def collect_network_stats_at_finish(self, section_ids: list):
        """
        Collect cumulative network-level stats (flow, density, speed) across
        all corridor approach sections.

        Strategy (in priority order):
        1. AKIEstGetGlobalStatisticsSystem(vehTypePos) — queries  
           stats by vehicle type. vehTypePos can be:
           -1 (all types), bus_pos, car_pos, truck_pos
        2. If global stats fail, fall back to per-section aggregation.
        3. If stats are unavailable, keep network KPIs at 0 (do not substitute).

        Results stored in self._net_* attributes and written by save_results().
        """
        if not section_ids:
            self._net_debug.update({
                'sim_time_s': 0.0,
                'section_count': 0,
                'stats_ok_sections': 0,
                'snapshot_ok_sections': 0,
                'snapshot_sections_with_vehicles': 0,
                'stats_zero_sections': 0,
                'snapshot_zero_sections': 0,
                'sections_missing_length': 0,
                'source': 'none',
                'vehicle_type_positions': f'bus={self._bus_pos},car={self._car_pos},truck={self._truck_pos}',
            })
            return

        # Ensure vehicle type positions are resolved
        def _fallback_type_pos(type_name: str):
            try:
                for pos in range(1, AKIVehGetNbVehTypes() + 1):
                    vtype = AKIVehGetVehTypeNamePos(pos)
                    if vtype and type_name.lower() in str(vtype).lower():
                        return pos
            except Exception:
                pass
            return -1
        
        if self._bus_pos <= 0:
            self._bus_pos = _fallback_type_pos("Bus")
        if self._car_pos <= 0:
            self._car_pos = _fallback_type_pos("Car")
        if self._hov_pos <= 0:
            self._hov_pos = _fallback_type_pos("HOV")
        if self._truck_pos <= 0:
            self._truck_pos = _fallback_type_pos("Truck")

        # Initialize vehicle type debug logging for this run
        _debug_type_log = (
            f"veh_types[bus={self._bus_pos},car={self._car_pos},"
            f"hov={self._hov_pos},truck={self._truck_pos}];"
        )

        sim_time = 0.0
        # At AAPIFinish, AKIGetSimulationTime() can resolve to 0 in some builds,
        # which would force Net_* metrics to 0. Prefer current sim time first.
        try:
            sim_time = float(AKIGetCurrentSimulationTime())
        except Exception:
            sim_time = 0.0
        if sim_time <= 0.0:
            try:
                sim_time = float(AKIGetSimulationTime())
            except Exception:
                sim_time = 0.0
        if sim_time <= 0:
            # Fallback to incremental samples gathered during AAPIPostManage
            # instead of suppressing all network KPIs to zero.
            if self._incr_net_samples > 0:
                _n = max(int(self._incr_net_samples), 1)
                self._net_total_flow_veh = int(round(self._incr_net_flow_sum / _n))
                self._net_avg_density_vkm = round(self._incr_net_density_sum / _n, 4)
                self._net_avg_speed_kmh = round(self._incr_net_speed_sum / _n, 3)
                if self._incr_net_delay_sum > 0.0:
                    self._net_delay_all = round(self._incr_net_delay_sum / _n, 2)
                self._net_debug.update({
                    'sim_time_s': sim_time,
                    'section_count': len(section_ids),
                    'stats_ok_sections': 0,
                    'snapshot_ok_sections': 0,
                    'snapshot_sections_with_vehicles': 0,
                    'stats_zero_sections': 0,
                    'snapshot_zero_sections': 0,
                    'sections_missing_length': 0,
                    'source': f'incremental-no-sim-time({_n}samples)',
                })
                return

            self._net_total_flow_veh = 0
            self._net_avg_density_vkm = 0.0
            self._net_avg_speed_kmh = 0.0
            self._net_debug.update({
                'sim_time_s': sim_time,
                'section_count': len(section_ids),
                'stats_ok_sections': 0,
                'snapshot_ok_sections': 0,
                'snapshot_sections_with_vehicles': 0,
                'stats_zero_sections': 0,
                'snapshot_zero_sections': 0,
                'sections_missing_length': 0,
                'source': 'no-sim-time',
            })
            return

        sim_hours = sim_time / 3600.0

        def _section_dsf_network_fallback():
            """Return length-weighted network flow/density/speed from sampled section_stats."""
            dens_w = 0.0
            spd_w = 0.0
            flow_w = 0.0
            len_w = 0.0
            for sd in getattr(self, '_section_dsf', {}).values():
                try:
                    n = int(sd.get('samples', 0) or 0)
                    sec_len = float(sd.get('length_km', 0.0) or 0.0)
                    if n <= 0 or sec_len <= 0.0:
                        continue
                    dens = float(sd.get('density_sum', 0.0) or 0.0) / n
                    spd = float(sd.get('speed_sum', 0.0) or 0.0) / n
                    flow = float(sd.get('flow_sum', 0.0) or 0.0) / n
                    dens_w += dens * sec_len
                    spd_w += spd * sec_len
                    flow_w += flow * sec_len
                    len_w += sec_len
                except Exception:
                    continue
            if len_w <= 0.0:
                return 0.0, 0.0, 0.0
            return flow_w / len_w, dens_w / len_w, spd_w / len_w

        def _system_stat(tp: int):
            """
            Fetch system-level statistics for a given vehicle type.
            tp: vehicle type position (-1 = all, or specific type ID like bus_pos)
            Returns: stats object or None if unavailable
            
            Per Aimsun docs (CalculationOfTrafficStatistics.html), this should return:
              - Flow: exit-based flow (veh/h)
              - DTa: average delay (s/km) ← delay per km
              - Density: v/km
              - Sa: average speed (km/h)
              - vehOut / count: vehicle count
            """
            def _has_data(s):
                """Return True if the stats object has at least one non-zero value."""
                if s is None:
                    return False
                return (float(getattr(s, 'Density', 0.0) or 0.0) > 0.0
                        or float(getattr(s, 'Flow', 0.0) or 0.0) > 0.0
                        or float(getattr(s, 'Sa', 0.0) or 0.0) > 0.0
                        or float(getattr(s, 'DTa', 0.0) or 0.0) > 0.0)

            # Try AKIEstGetGlobalStatisticsSystem first (cumulative over all intervals)
            for _fn_name in ('AKIEstGetGlobalStatisticsSystem',
                             'AKIEstGetCurrentStatisticsSystem'):
                _fn = globals().get(_fn_name)
                if _fn is None:
                    continue
                try:
                    st = _fn(tp)
                    if _has_data(st):
                        return st
                    # Some builds require report==0 check
                    if st is not None and int(getattr(st, 'report', -1) or -1) == 0:
                        return st  # report=0 even if values are 0
                except Exception:
                    pass
            return None

        def _read_delay_fields(st):
            """Return (entry_delay_s_per_km, exit_delay_s_per_km) with robust fallbacks."""
            # Many Aimsun builds expose only DTa. Keep both fields explicit and
            # mirror when one is unavailable so downstream CSV consumers can rely
            # on stable columns.
            entry = 0.0
            exit_d = 0.0
            try:
                entry = float(
                    getattr(st, 'EBDTa', 0.0)
                    or getattr(st, 'EBDT', 0.0)
                    or getattr(st, 'EDTa', 0.0)
                    or 0.0
                )
            except Exception:
                entry = 0.0
            try:
                exit_d = float(
                    getattr(st, 'DTa', 0.0)
                    or getattr(st, 'ExitDelay', 0.0)
                    or 0.0
                )
            except Exception:
                exit_d = 0.0
            if entry <= 0.0 and exit_d > 0.0:
                entry = exit_d
            if exit_d <= 0.0 and entry > 0.0:
                exit_d = entry
            return entry, exit_d

        def _live_network_inside_stats(tp: int = -1):
            """
            Approximate network entry-based contribution from vehicles still inside.

            Aimsun entry-based travel-time/delay metrics include vehicles still in the
            network at interval end using a traveled-fraction weighting. We reconstruct
            that from the live vehicles currently found on the monitored sections.
            """
            seen_vids = set()
            inside_count_w = 0.0
            inside_speed_w = 0.0
            inside_delay_w = 0.0

            for _sec in section_ids:
                try:
                    _n_live = max(int(AKIVehStateGetNbVehiclesSection(_sec, False)), 0)
                except Exception:
                    _n_live = 0
                for _vi in range(_n_live):
                    try:
                        _vinf = AKIVehStateGetVehicleInfSection(_sec, _vi)
                        _vid = int(getattr(_vinf, 'idVeh', -1) or -1)
                        if _vid <= 0 or _vid in seen_vids:
                            continue
                        seen_vids.add(_vid)

                        if not _vehicle_matches_type(_vinf, _sec, _vi, tp):
                            continue

                        _pinf = AKIVehInfPath(_vid)
                        if getattr(_pinf, 'report', -1) != 0:
                            continue

                        _path_total_dist = float(getattr(_pinf, 'totalDistance', 0.0) or 0.0)
                        _path_ff_tt = float(getattr(_pinf, 'totalFreeFlowTravelTime', 0.0) or 0.0)
                        _travelled_dist = float(getattr(_vinf, 'TotalDistance', 0.0) or 0.0)
                        if _path_total_dist <= 0.0 or _travelled_dist <= 0.0:
                            continue

                        _frac = min(1.0, max(0.0, _travelled_dist / max(_path_total_dist, 0.001)))
                        if _frac <= 0.0 or _frac >= 1.0:
                            continue

                        _ent_t = float(getattr(_vinf, 'SystemEntranceT', -1.0) or -1.0)
                        _elapsed_s = sim_time - _ent_t if _ent_t >= 0.0 else 0.0
                        if _elapsed_s <= 0.1:
                            continue

                        _est_total_tt = _elapsed_s / max(_frac, 1e-6)
                        _avg_speed_kmh = (_path_total_dist / _est_total_tt) * 3.6 if _est_total_tt > 0.1 else 0.0
                        if _avg_speed_kmh <= 0.0:
                            _avg_speed_kmh = float(getattr(_vinf, 'CurrentSpeed', 0.0) or 0.0)
                        if _avg_speed_kmh <= 0.0:
                            continue

                        _delay_s = max(_est_total_tt - _path_ff_tt, 0.0) if _path_ff_tt > 0.0 else 0.0
                        _dist_km = _path_total_dist / 1000.0 if _path_total_dist > 20.0 else _path_total_dist
                        _delay_skm = (_delay_s / max(_dist_km, 0.001)) if _dist_km > 0.0 else 0.0

                        inside_count_w += _frac
                        inside_speed_w += _frac * _avg_speed_kmh
                        inside_delay_w += _frac * _delay_skm
                    except Exception:
                        continue

            return inside_count_w, inside_speed_w, inside_delay_w

        def _vehicle_matches_type(vinf, sec_id: int, veh_index: int, tp: int) -> bool:
            # In some Aimsun builds, all-vehicles selector can be 0 (not only -1).
            if tp <= 0:
                return True
            candidates = []
            try:
                candidates.append(int(getattr(vinf, 'type', -1) or -1))
            except Exception:
                pass
            try:
                sinf = AKIVehGetVehicleStaticInfSection(sec_id, veh_index)
                candidates.append(int(getattr(sinf, 'type', -1) or -1))
                candidates.append(int(getattr(sinf, 'vehType', -1) or -1))
            except Exception:
                pass
            return any(c == tp for c in candidates if c > 0)

        def _finish_snapshot_density_all() -> float:
            """Compute finish-time network density as total vehicles / total lane-km."""
            tot_veh = 0.0
            tot_lane_km = 0.0
            for _sec in section_ids:
                try:
                    _geom = self._get_section_geometry(_sec)
                    if _geom is None:
                        continue
                    _lane_km = float(_geom.get('lane_length_km', 0.0) or 0.0)
                    if _lane_km <= 0.0:
                        continue
                    _n = float(max(int(AKIVehStateGetNbVehiclesSection(_sec, False)), 0))
                    tot_veh += _n
                    tot_lane_km += _lane_km
                except Exception:
                    continue
            if tot_lane_km <= 0.0:
                return 0.0
            return tot_veh / tot_lane_km

        def _select_all_system_stat():
            """
            Resolve which vehicle type position represents "all vehicles" for
            this Aimsun build. Prefer tp=0, then fallback to tp=-1.
            """
            _best_tp = -1
            _best_st = None
            _best_score = -1.0
            for _cand_tp in (0, -1):
                _cand_st = _system_stat(_cand_tp)
                if _cand_st is None:
                    continue
                _cand_flow = float(getattr(_cand_st, 'Flow', 0.0) or 0.0)
                _cand_density = float(getattr(_cand_st, 'Density', 0.0) or 0.0)
                _cand_speed = float(getattr(_cand_st, 'Sa', 0.0) or 0.0)
                _cand_count = float(getattr(_cand_st, 'vehOut', 0.0) or 0.0)
                if _cand_count <= 0.0:
                    _cand_count = float(getattr(_cand_st, 'count', 0.0) or 0.0)
                # Density is most diagnostic for this bug; then flow/count/speed.
                _score = (_cand_density * 1_000_000.0) + (_cand_flow * 10.0) + _cand_count + _cand_speed
                if _score > _best_score:
                    _best_score = _score
                    _best_tp = _cand_tp
                    _best_st = _cand_st
            return _best_tp, _best_st

        _all_tp_pos, _sys_all = _select_all_system_stat()
        _debug_type_log = f"bus={self._bus_pos},car={self._car_pos},truck={self._truck_pos};"
        
        if _sys_all is not None:
            _sys_flow = float(getattr(_sys_all, 'Flow', 0.0) or 0.0)
            # Sanity cap: Aimsun's GKSystemStatistic.Flow sometimes returns a
            # cumulative passage count rather than veh/h when a wrong statistic
            # type is selected (e.g. DCTSP_MARL returns ~673 M).  Any value
            # above 50 000 veh/h is physically impossible for this corridor.
            if _sys_flow > 50_000.0:
                _sys_flow = 0.0
            _sys_density = float(getattr(_sys_all, 'Density', 0.0) or 0.0)
            _sys_speed = float(getattr(_sys_all, 'Sa', 0.0) or 0.0)
            _sys_delay_entry, _sys_delay_exit = _read_delay_fields(_sys_all)
            _sys_raw_flow = _sys_flow
            _sys_raw_density = _sys_density
            _sys_raw_speed = _sys_speed
            _sys_raw_delay_entry = _sys_delay_entry
            _sys_raw_delay_exit = _sys_delay_exit
            _sys_delay = _sys_delay_entry
            _sys_count = float(getattr(_sys_all, 'vehOut', 0.0) or 0.0)
            if _sys_count <= 0.0:
                _sys_count = float(getattr(_sys_all, 'count', 0.0) or 0.0)
            _debug_type_log += (
                f"all[flow={_sys_flow},density={_sys_density},"
                f"entry_delay={_sys_delay_entry},exit_delay={_sys_delay_exit},count={_sys_count}];"
            )
            
            if _sys_count <= 0.0 and _sys_flow > 0.0 and sim_hours > 0.0:
                _sys_count = _sys_flow * sim_hours
            _sys_inside_cnt, _sys_inside_spd_w, _sys_inside_dly_w = _live_network_inside_stats(_all_tp_pos)
            _sys_count_has_fraction = abs(_sys_count - round(_sys_count)) > 1e-6
            _sys_entry_count = _sys_count if _sys_count_has_fraction else (_sys_count + _sys_inside_cnt)
            if sim_hours > 0.0 and _sys_entry_count > 0.0:
                _sys_flow = _sys_entry_count / sim_hours
            if not _sys_count_has_fraction and _sys_inside_cnt > 0.0:
                if _sys_speed > 0.0:
                    _sys_speed = ((_sys_count * _sys_speed) + _sys_inside_spd_w) / max(_sys_entry_count, 1e-6)
                elif _sys_inside_spd_w > 0.0:
                    _sys_speed = _sys_inside_spd_w / max(_sys_inside_cnt, 1e-6)
                if _sys_delay > 0.0:
                    _sys_delay = ((_sys_count * _sys_delay) + _sys_inside_dly_w) / max(_sys_entry_count, 1e-6)
                elif _sys_inside_dly_w > 0.0:
                    _sys_delay = _sys_inside_dly_w / max(_sys_inside_cnt, 1e-6)

            # Some Aimsun builds return partial system stats (e.g., flow/speed but
            # density and/or delay still zero). Fill missing fields from robust
            # incremental accumulators so Density-All and Delay-All are never blank.
            _sys_filled_from_incr = False
            if self._incr_net_samples > 0:
                _n_incr = max(int(self._incr_net_samples), 1)
                if _sys_density <= 0.0 and self._incr_net_density_sum > 0.0:
                    _sys_density = self._incr_net_density_sum / _n_incr
                    _sys_filled_from_incr = True
                if _sys_speed <= 0.0 and self._incr_net_speed_sum > 0.0:
                    _sys_speed = self._incr_net_speed_sum / _n_incr
                    _sys_filled_from_incr = True
                if _sys_delay_entry <= 0.0 and self._incr_net_delay_sum > 0.0:
                    _sys_delay_entry = self._incr_net_delay_sum / _n_incr
                    _sys_filled_from_incr = True
                if _sys_delay_exit <= 0.0 and self._incr_net_delay_sum > 0.0:
                    _sys_delay_exit = self._incr_net_delay_sum / _n_incr
                    _sys_filled_from_incr = True
            if _sys_delay_entry <= 0.0 and _sys_delay_exit > 0.0:
                _sys_delay_entry = _sys_delay_exit
            if _sys_delay_exit <= 0.0 and _sys_delay_entry > 0.0:
                _sys_delay_exit = _sys_delay_entry
            _sys_delay = _sys_delay_entry

            # If system stats return flow/speed but density=0, use robust fallbacks.
            if _sys_density <= 0.0:
                if self._incr_net_samples > 0 and self._incr_net_density_sum > 0.0:
                    _sys_density = self._incr_net_density_sum / max(self._incr_net_samples, 1)
                    _sys_filled_from_incr = True
                else:
                    _snap_den = _finish_snapshot_density_all()
                    if _snap_den > 0.0:
                        _sys_density = _snap_den

            _fb_flow, _fb_density, _fb_speed = _section_dsf_network_fallback()
            if _sys_density <= 0.0 and _fb_density > 0.0:
                _sys_density = _fb_density
                _sys_filled_from_incr = True
            if _sys_speed <= 0.0 and _fb_speed > 0.0:
                _sys_speed = _fb_speed
                _sys_filled_from_incr = True
            if _fb_speed > 0.0 and 0.0 < _sys_speed < 0.5 * _fb_speed:
                _sys_speed = _fb_speed
                _sys_filled_from_incr = True
            if _sys_flow <= 0.0 and _fb_flow > 0.0:
                _sys_flow = _fb_flow
                _sys_filled_from_incr = True

            if _sys_flow > 0.0 or _sys_density > 0.0 or _sys_speed > 0.0:
                self._net_total_flow_veh = int(round(_sys_flow))
                self._net_avg_density_vkm = round(_sys_density, 4)
                self._net_avg_speed_kmh = round(_sys_speed, 3)

                _sys_type_map = {
                    'all': _all_tp_pos,
                    'car': self._car_pos,
                    'bus': self._bus_pos,
                    'hov': self._hov_pos,
                    'truck': self._truck_pos,
                }
                for _key, _tp in _sys_type_map.items():
                    if _key != 'all' and (_tp is None or _tp < 0):
                        setattr(self, f'_net_flow_{_key}', 0.0)
                        setattr(self, f'_net_density_{_key}', 0.0)
                        setattr(self, f'_net_speed_{_key}', 0.0)
                        setattr(self, f'_net_entry_delay_{_key}', 0.0)
                        setattr(self, f'_net_exit_delay_{_key}', 0.0)
                        setattr(self, f'_net_delay_{_key}', 0.0)
                        continue
                    _st = _sys_all if _key == 'all' else _system_stat(_tp)
                    if _st is None:
                        setattr(self, f'_net_flow_{_key}', 0.0)
                        setattr(self, f'_net_density_{_key}', 0.0)
                        setattr(self, f'_net_speed_{_key}', 0.0)
                        setattr(self, f'_net_entry_delay_{_key}', 0.0)
                        setattr(self, f'_net_exit_delay_{_key}', 0.0)
                        setattr(self, f'_net_delay_{_key}', 0.0)
                        continue
                    _t_flow = float(getattr(_st, 'Flow', 0.0) or 0.0)
                    _t_density = float(getattr(_st, 'Density', 0.0) or 0.0)
                    _t_speed = float(getattr(_st, 'Sa', 0.0) or 0.0)
                    _t_delay_entry, _t_delay_exit = _read_delay_fields(_st)
                    _t_delay = _t_delay_entry
                    _t_count = float(getattr(_st, 'vehOut', 0.0) or 0.0)
                    if _t_count <= 0.0:
                        _t_count = float(getattr(_st, 'count', 0.0) or 0.0)
                    if _t_count <= 0.0 and _t_flow > 0.0 and sim_hours > 0.0:
                        _t_count = _t_flow * sim_hours
                    _t_inside_cnt, _t_inside_spd_w, _t_inside_dly_w = _live_network_inside_stats(_tp)
                    _t_has_fraction = abs(_t_count - round(_t_count)) > 1e-6
                    _t_entry_count = _t_count if _t_has_fraction else (_t_count + _t_inside_cnt)
                    if sim_hours > 0.0 and _t_entry_count > 0.0:
                        _t_flow = _t_entry_count / sim_hours
                    if not _t_has_fraction and _t_inside_cnt > 0.0:
                        if _t_speed > 0.0:
                            _t_speed = ((_t_count * _t_speed) + _t_inside_spd_w) / max(_t_entry_count, 1e-6)
                        elif _t_inside_spd_w > 0.0:
                            _t_speed = _t_inside_spd_w / max(_t_inside_cnt, 1e-6)
                        if _t_delay_entry > 0.0:
                            _t_delay_entry = ((_t_count * _t_delay_entry) + _t_inside_dly_w) / max(_t_entry_count, 1e-6)
                        elif _t_inside_dly_w > 0.0:
                            _t_delay_entry = _t_inside_dly_w / max(_t_inside_cnt, 1e-6)
                        if _t_delay_exit > 0.0:
                            _t_delay_exit = ((_t_count * _t_delay_exit) + _t_inside_dly_w) / max(_t_entry_count, 1e-6)
                        elif _t_inside_dly_w > 0.0:
                            _t_delay_exit = _t_inside_dly_w / max(_t_inside_cnt, 1e-6)
                    if _t_delay_entry <= 0.0 and _t_delay_exit > 0.0:
                        _t_delay_entry = _t_delay_exit
                    if _t_delay_exit <= 0.0 and _t_delay_entry > 0.0:
                        _t_delay_exit = _t_delay_entry
                    setattr(self, f'_net_flow_{_key}', round(_t_flow, 2))
                    setattr(self, f'_net_density_{_key}', round(_t_density, 4))
                    setattr(self, f'_net_speed_{_key}', round(_t_speed, 3))
                    setattr(self, f'_net_entry_delay_{_key}', round(_t_delay_entry, 2))
                    setattr(self, f'_net_exit_delay_{_key}', round(_t_delay_exit, 2))
                    # Backward compatibility: existing Net_Delay_* columns map to Entry-Based
                    setattr(self, f'_net_delay_{_key}', round(_t_delay_entry, 2))

                _type_flow_sum = sum(
                    float(getattr(self, f'_net_flow_{_k}', 0.0) or 0.0)
                    for _k in ('car', 'bus', 'hov', 'truck')
                )
                _type_density_sum = sum(
                    float(getattr(self, f'_net_density_{_k}', 0.0) or 0.0)
                    for _k in ('car', 'bus', 'hov', 'truck')
                )
                if _type_flow_sum > 0.0 and float(self._net_total_flow_veh or 0) < 0.5 * _type_flow_sum:
                    self._net_total_flow_veh = int(round(_type_flow_sum))
                if self._net_avg_density_vkm <= 0.0 and _type_density_sum > 0.0:
                    self._net_avg_density_vkm = round(_type_density_sum, 4)

                self._net_entry_delay_all = round(_sys_delay_entry, 2)
                self._net_exit_delay_all = round(_sys_delay_exit, 2)
                self._net_delay_all = self._net_entry_delay_all
                # AKIEstGetGlobalStatisticsSystem.DTa returns 0 in some Aimsun builds.
                # When that happens, compute Entry-Based Delay from per-section cumulative
                # stats (DTa - free_flow_TT) / section_length, count-weighted average.
                if self._net_delay_all == 0.0 and section_ids:
                    _sec_dly_sum = 0.0
                    _sec_dly_cnt = 0.0
                    for _sec_d in section_ids:
                        _geom_d = self._get_section_geometry(_sec_d)
                        if _geom_d is None:
                            continue
                        _slen_m_d  = _geom_d['length_m']
                        _slen_km_d = _geom_d['length_km']
                        _slim_d    = _geom_d['speed_limit_kmh'] or 40.0
                        _st_d = None
                        try:
                            _st_d = AKIEstGetParcialStatisticsSection(_sec_d, 0.0, -1)
                            if getattr(_st_d, 'report', -1) != 0:
                                _st_d = None
                        except Exception:
                            _st_d = None
                        if _st_d is None:
                            try:
                                _st_d = AKIEstGetCurrentStatisticsSection(_sec_d, 0.0, -1)
                                if getattr(_st_d, 'report', -1) != 0:
                                    _st_d = None
                            except Exception:
                                _st_d = None
                        if _st_d is None:
                            continue
                        _cnt_d = float(getattr(_st_d, 'count', 0) or 0)
                        _dta_d = float(getattr(_st_d, 'DTa', 0.0) or 0.0)
                        _tta_d = float(getattr(_st_d, 'TTa', 0.0) or 0.0)
                        # DTa is often 0 from section stats in this Aimsun build.
                        # Fallback: compute delay as TTa - free-flow TT.
                        if _dta_d <= 0.0 and _tta_d > 0.0 and _slen_m_d > 0.0:
                            _ff_tt_d = _slen_m_d / max(_slim_d / 3.6, 1.0)
                            _dta_d = max(_tta_d - _ff_tt_d, 0.0)
                        if _cnt_d > 0 and _dta_d > 0.0 and _slen_km_d > 0.0:
                            _sec_dly = _dta_d / max(_slen_km_d, 0.001)
                            _sec_dly_sum += _sec_dly * _cnt_d
                            _sec_dly_cnt += _cnt_d
                    if _sec_dly_cnt > 0:
                        self._net_delay_all = round(_sec_dly_sum / _sec_dly_cnt, 2)
                        self._net_entry_delay_all = self._net_delay_all
                        self._net_exit_delay_all = self._net_delay_all
                        # Propagate to per-type delay (best estimate: same as all-vehicle)
                        for _k_d in ('car', 'bus', 'hov', 'truck'):
                            if getattr(self, f'_net_delay_{_k_d}', 0.0) == 0.0:
                                setattr(self, f'_net_delay_{_k_d}', self._net_delay_all)
                            if getattr(self, f'_net_entry_delay_{_k_d}', 0.0) == 0.0:
                                setattr(self, f'_net_entry_delay_{_k_d}', self._net_delay_all)
                            if getattr(self, f'_net_exit_delay_{_k_d}', 0.0) == 0.0:
                                setattr(self, f'_net_exit_delay_{_k_d}', self._net_delay_all)
                    # Section-based fallback also yielded 0; try flow-weighted average of per-type delays.
                    if self._net_delay_all == 0.0:
                        _wt_dly = 0.0
                        _wt_cnt = 0.0
                        for _kd in ('car', 'bus', 'hov', 'truck'):
                            _d = float(getattr(self, f'_net_delay_{_kd}', 0.0) or 0.0)
                            _f = float(getattr(self, f'_net_flow_{_kd}', 0.0) or 0.0)
                            if _d > 0.0 and _f > 0.0:
                                _wt_dly += _d * _f
                                _wt_cnt += _f
                        if _wt_cnt > 0.0:
                            self._net_delay_all = round(_wt_dly / _wt_cnt, 2)
                            self._net_entry_delay_all = self._net_delay_all
                            self._net_exit_delay_all = self._net_delay_all
                self._net_debug.update({
                    'sim_time_s': round(sim_time, 3),
                    'section_count': len(section_ids),
                    'stats_ok_sections': 0,
                    'snapshot_ok_sections': 0,
                    'snapshot_sections_with_vehicles': 0,
                    'stats_zero_sections': 0,
                    'snapshot_zero_sections': 0,
                    'sections_missing_length': 0,
                    'source': ('akiest-system+incr-fill' if _sys_filled_from_incr else 'akiest-system'),
                    'veh_out': int(round(_sys_count)),
                    'sys_raw_flow_veh_h': round(_sys_raw_flow, 4),
                    'sys_raw_density_vkm': round(_sys_raw_density, 4),
                    'sys_raw_speed_kmh': round(_sys_raw_speed, 4),
                    'sys_raw_entry_delay_skm': round(_sys_raw_delay_entry, 4),
                    'sys_raw_exit_delay_skm': round(_sys_raw_delay_exit, 4),
                    'sys_adjusted_entry_count_veh': round(_sys_entry_count, 4),
                    'all_type_pos_selected': _all_tp_pos,
                    'vehicle_types_log': _debug_type_log,
                })
                return

        # Per-vehicle-type network accumulators (length-weighted)
        # Indexed as: [all, car, bus, hov, truck] in that order
        _tp_list = [_all_tp_pos, self._car_pos, self._bus_pos, self._hov_pos, self._truck_pos]
        _tp_keys = ['all', 'car', 'bus', 'hov', 'truck']
        _tp_flow  = {k: 0.0 for k in _tp_keys}
        _tp_dens  = {k: 0.0 for k in _tp_keys}
        _tp_spd   = {k: 0.0 for k in _tp_keys}
        _tp_dly_entry = {k: 0.0 for k in _tp_keys}  # sec/km
        _tp_dly_exit  = {k: 0.0 for k in _tp_keys}  # sec/km
        _tp_cnt   = {k: 0.0 for k in _tp_keys}  # vehicle count (weighting denominator)

        # Length-weighted accumulators — matches Aimsun's Entry-Based statistics
        # which uses network-wide length-weighted averages.
        # Flow: Σ(count_i)/sim_hours gives total vehicle throughput rate.
        # Density and Speed: Σ(metric_i * len_i) / Σ(len_i) = length-weighted avg.
        total_length_km    = 0.0   # Σ section lengths (km)
        total_count_veh    = 0.0   # Σ count_i — divide by sim_hours for total flow
        total_flow_veh_h   = 0.0   # Σ(flow_i * len_i) — for length-weighted avg flow
        total_density_vkm  = 0.0   # Σ(density_i * len_i)
        total_speed_kmh    = 0.0   # Σ(speed_i * len_i)
        n_ok = 0
        stats_zero_sections = 0
        total_lane_km = 0.0

        def _read_section_cumul(sec, tp):
            """
            Read CUMULATIVE stats for the full simulation (timSta=0.0).
            Aimsun: AKIEstGetParcialStatisticsSection(sec, timSta, type)
            With timSta=0.0, returns all vehicles entering the section since
            simulation start.  count and DTa (mean travel time s) are reliable
            in this Aimsun build; .flow/.density/.speed fields are always 0.
            """
            try:
                st = AKIEstGetParcialStatisticsSection(sec, 0.0, tp)
                if getattr(st, 'report', -1) == 0:
                    return st
            except Exception:
                pass
            try:
                st = AKIEstGetCurrentStatisticsSection(sec, 0.0, tp)
                if getattr(st, 'report', -1) == 0:
                    return st
            except Exception:
                pass
            return None

        def _snapshot_section_metrics(sec_id: int, sec_len_km_val: float, lane_count: int = 1, tp: int = -1):
            """Return snapshot flow/density/speed using live vehicles on section."""
            lane_count = max(int(lane_count or 1), 1)
            sec_lane_len_km_val = sec_len_km_val * lane_count
            if sec_lane_len_km_val <= 0.0:
                return 0.0, 0.0, 0.0, 0
            try:
                n_total = max(int(AKIVehStateGetNbVehiclesSection(sec_id, False)), 0)
            except Exception:
                n_total = 0
            n_veh = 0
            inv_spd_sum = 0.0
            spd_n = 0
            for vi in range(n_total):
                try:
                    vinf = AKIVehStateGetVehicleInfSection(sec_id, vi)
                    if not _vehicle_matches_type(vinf, sec_id, vi, tp):
                        continue
                    n_veh += 1
                    s = float(getattr(vinf, 'CurrentSpeed', 0.0) or 0.0)
                    if s > 0.0:
                        inv_spd_sum += 1.0 / s
                        spd_n += 1
                except Exception:
                    continue
            density = float(n_veh) / sec_lane_len_km_val
            speed = (float(spd_n) / inv_spd_sum) if inv_spd_sum > 0.0 else 0.0
            flow = density * speed * lane_count if (density > 0.0 and speed > 0.0) else 0.0
            return flow, density, speed, n_veh

        def _section_inside_entry_stats(sec_id: int, sec_len_m_val: float, sec_len_km_val: float,
                                        sec_speed_limit_kmh_val: float, tp: int = -1):
            """
            Approximate the entry-based contribution of vehicles still inside the section.

            Aimsun's section Entry-Based metrics include a fractional contribution from
            vehicles still in the section at interval end, weighted by traveled fraction.
            We reconstruct that here from live vehicle state when the cumulative AKIEst
            result appears to include completed vehicles only.
            """
            if sec_len_m_val <= 0.0 or sec_len_km_val <= 0.0:
                return 0.0, 0.0, 0.0
            try:
                n_live = max(int(AKIVehStateGetNbVehiclesSection(sec_id, False)), 0)
            except Exception:
                n_live = 0

            inside_count_w = 0.0
            inside_speed_w = 0.0
            inside_delay_w = 0.0
            ff_tt = sec_len_m_val / max(sec_speed_limit_kmh_val / 3.6, 1.0)

            for vi in range(n_live):
                try:
                    vinf = AKIVehStateGetVehicleInfSection(sec_id, vi)
                    if not _vehicle_matches_type(vinf, sec_id, vi, tp):
                        continue

                    current_pos_m = float(getattr(vinf, 'CurrentPos', 0.0) or 0.0)
                    frac = min(1.0, max(0.0, current_pos_m / max(sec_len_m_val, 0.001)))
                    if frac <= 0.0:
                        continue

                    sec_ent_t = float(getattr(vinf, 'SectionEntranceT', -1.0) or -1.0)
                    elapsed_s = sim_time - sec_ent_t if sec_ent_t >= 0.0 else 0.0
                    avg_speed_mps = 0.0
                    if elapsed_s > 0.1 and current_pos_m > 0.0:
                        avg_speed_mps = current_pos_m / elapsed_s
                    if avg_speed_mps <= 0.0:
                        avg_speed_mps = float(getattr(vinf, 'CurrentSpeed', 0.0) or 0.0) / 3.6
                    if avg_speed_mps <= 0.0:
                        continue

                    est_full_tt = sec_len_m_val / max(avg_speed_mps, 0.1)
                    est_delay_skm = max(est_full_tt - ff_tt, 0.0) / max(sec_len_km_val, 0.001)

                    inside_count_w += frac
                    inside_speed_w += frac * (avg_speed_mps * 3.6)
                    inside_delay_w += frac * est_delay_skm
                except Exception:
                    continue

            return inside_count_w, inside_speed_w, inside_delay_w

        for sec in section_ids:
            # Get section geometry — note: speed limit is in 'speedLimit' not 'speed'
            geom = self._get_section_geometry(sec)
            if geom is None:
                continue
            sec_len_km = geom['length_km']
            sec_len_m = geom['length_m']
            sec_lane_len_km = geom['lane_length_km']
            lane_count = max(int(geom.get('lane_count', 1) or 1), 1)
            sec_speed_limit_kmh = geom['speed_limit_kmh'] or 40.0

            # Snapshot metrics for robust fallback when cumulative stats are sparse.
            _snap_flow, _snap_density, _snap_speed, _n_snap = _snapshot_section_metrics(sec, sec_len_km, lane_count)

            sec_flow    = 0.0
            sec_density = 0.0
            sec_speed   = 0.0
            sec_got     = False
            _cnt        = 0.0   # vehicles completing this section (count-weighting)

            # ── Primary: cumulative AKIEst stats (timSta=0.0) ────────────────
            # .count = total vehicles completing section since sim start
            # .TTa   = mean travel time (s/veh) — use for speed computation
            # .DTa   = mean DELAY time (s/veh) — already delay, divide by km for s/km
            # Entry-Based Flow  = count / sim_hours
            # Entry-Based Speed = (section_length_m / TTa) * 3.6 (km/h)
            # Entry-Based Density = flow / speed (from fundamental relation)
            sec_delay_skm = 0.0  # all-vehicle Entry-Based Delay Time (sec/km)
            st_all = _read_section_cumul(sec, -1)
            if st_all is not None:
                _cnt = float(getattr(st_all, 'count', 0) or 0)
                _dta = float(getattr(st_all, 'DTa',   0.0) or 0.0)
                _tta = float(getattr(st_all, 'TTa',   0.0) or 0.0)
                _inside_cnt, _inside_spd_w, _inside_dly_w = _section_inside_entry_stats(
                    sec, sec_len_m, sec_len_km, sec_speed_limit_kmh, -1
                )
                if _cnt > 0 and sim_hours > 0:
                    _count_has_fraction = abs(_cnt - round(_cnt)) > 1e-6
                    _entry_cnt = _cnt if _count_has_fraction else (_cnt + _inside_cnt)
                    sec_flow = _entry_cnt / sim_hours   # veh/h (Entry-Based Flow)
                    if _tta > 0.0 and sec_len_m > 0.0:
                        sec_speed = (sec_len_m / _tta) * 3.6  # km/h from mean travel time
                    # DTa is often 0 from section stats in this Aimsun build.
                    # Fallback: compute delay as TTa - free-flow TT.
                    if _dta <= 0.0 and _tta > 0.0 and sec_len_m > 0.0:
                        _ff_tt = sec_len_m / max(sec_speed_limit_kmh / 3.6, 1.0)
                        _dta = max(_tta - _ff_tt, 0.0)
                    if _dta > 0.0 and sec_len_km > 0.0:
                        sec_delay_skm = _dta / max(sec_len_km, 0.001)
                    if not _count_has_fraction and _inside_cnt > 0.0:
                        if sec_speed > 0.0:
                            sec_speed = ((_cnt * sec_speed) + _inside_spd_w) / max(_entry_cnt, 1e-6)
                        else:
                            sec_speed = _inside_spd_w / max(_inside_cnt, 1e-6)
                        if sec_delay_skm > 0.0:
                            sec_delay_skm = ((_cnt * sec_delay_skm) + _inside_dly_w) / max(_entry_cnt, 1e-6)
                        elif _inside_dly_w > 0.0:
                            sec_delay_skm = _inside_dly_w / max(_inside_cnt, 1e-6)
                    _cnt = _entry_cnt
                    if sec_flow > 0.0 and sec_speed > 0.0:
                        sec_density = sec_flow / max(sec_speed * lane_count, 1e-6)     # veh/km/lane
                    elif _n_snap >= 0:
                        sec_density = _snap_density
                        sec_speed = _snap_speed
                        sec_flow = _snap_flow
                    if _n_snap >= 3 and _snap_flow > 0.0 and sec_flow < 0.25 * _snap_flow:
                        sec_flow = _snap_flow
                        sec_density = _snap_density
                        sec_speed = _snap_speed
                    sec_got = True
                elif _n_snap > 0:
                    sec_flow = _snap_flow
                    sec_density = _snap_density
                    sec_speed = _snap_speed
                    sec_got = True

            if sec_got:
                # Per-vehicle-type collection
                for tp, key in zip(_tp_list, _tp_keys):
                    if tp is None or tp < -1:
                        continue
                    # -1 means "all vehicle types" in AKIEst — only valid for key='all'.
                    # For per-type keys (car/bus/truck), skip when type position
                    # is unresolved (tp=-1) to avoid misattributing all-vehicle
                    # stats to a single type.
                    if key != 'all' and tp < 0:
                        continue
                    _t_cnt_is_veh_count = True  # default; overridden in fallback below
                    if key == 'all':
                        _t_flow = sec_flow
                        _t_spd  = sec_speed
                        _t_dens = sec_density
                        _t_dly_entry = sec_delay_skm   # use pre-computed all-veh delay
                        _t_dly_exit = sec_delay_skm
                        _t_cnt  = _cnt
                    else:
                        _st = _read_section_cumul(sec, tp)
                        _c = float(getattr(_st, 'count', 0) or 0) if _st is not None else 0.0
                        _d = float(getattr(_st, 'DTa',   0.0) or 0.0) if _st is not None else 0.0
                        _t_raw = float(getattr(_st, 'TTa', 0.0) or 0.0) if _st is not None else 0.0
                        _inside_t_cnt, _inside_t_spd_w, _inside_t_dly_w = _section_inside_entry_stats(
                            sec, sec_len_m, sec_len_km, sec_speed_limit_kmh, tp
                        )
                        if _c > 0 and sim_hours > 0:
                            _count_has_fraction = abs(_c - round(_c)) > 1e-6
                            _entry_t_cnt = _c if _count_has_fraction else (_c + _inside_t_cnt)
                            _t_flow = _entry_t_cnt / sim_hours
                            _t_spd  = (sec_len_m / _t_raw) * 3.6 if (_t_raw > 0 and sec_len_m > 0) else 0.0
                            _t_dens = _t_flow / max(_t_spd * lane_count, 1e-6) if (_t_flow > 0 and _t_spd > 0) else 0.0
                            # DTa is already mean delay per vehicle (s); divide by km for s/km
                            _t_dly_entry = _d / max(sec_len_km, 0.001) if _d > 0.0 else 0.0
                            _t_dly_exit = _t_dly_entry
                            if not _count_has_fraction and _inside_t_cnt > 0.0:
                                if _t_spd > 0.0:
                                    _t_spd = ((_c * _t_spd) + _inside_t_spd_w) / max(_entry_t_cnt, 1e-6)
                                else:
                                    _t_spd = _inside_t_spd_w / max(_inside_t_cnt, 1e-6)
                                if _t_dly_entry > 0.0:
                                    _t_dly_entry = ((_c * _t_dly_entry) + _inside_t_dly_w) / max(_entry_t_cnt, 1e-6)
                                elif _inside_t_dly_w > 0.0:
                                    _t_dly_entry = _inside_t_dly_w / max(_inside_t_cnt, 1e-6)
                                if _t_dly_exit > 0.0:
                                    _t_dly_exit = ((_c * _t_dly_exit) + _inside_t_dly_w) / max(_entry_t_cnt, 1e-6)
                                elif _inside_t_dly_w > 0.0:
                                    _t_dly_exit = _inside_t_dly_w / max(_inside_t_cnt, 1e-6)
                                _t_dens = _t_flow / max(_t_spd * lane_count, 1e-6) if (_t_flow > 0 and _t_spd > 0) else 0.0
                            _t_cnt  = _entry_t_cnt
                            _t_cnt_is_veh_count = True   # true vehicle count from AKIEst
                        else:
                            _t_flow, _t_dens, _t_spd, _snap_t_count = _snapshot_section_metrics(sec, sec_len_km, lane_count, tp)
                            if _snap_t_count <= 0:
                                continue
                            _t_dly_entry = 0.0
                            _t_dly_exit = 0.0
                            _t_cnt = float(sec_lane_len_km)
                            _t_cnt_is_veh_count = False  # fallback: _t_cnt is lane-km, not a count
                    # Length-weighted accumulation — consistent with all-vehicle
                    # average which uses length weighting.
                    _tp_flow[key] += _t_flow * sec_lane_len_km
                    _tp_dens[key] += _t_dens * sec_lane_len_km
                    _tp_spd[key]  += _t_spd  * sec_lane_len_km
                    _tp_dly_entry[key] += _t_dly_entry * sec_lane_len_km
                    _tp_dly_exit[key]  += _t_dly_exit  * sec_lane_len_km
                    _tp_cnt[key]  += sec_lane_len_km
                    # Total distance traveled (vehicle-km) = count × section_length_km.
                    # ONLY accumulate when _t_cnt is a true vehicle count from AKIEst.
                    # In the snapshot fallback, _t_cnt holds sec_lane_len_km (km), not
                    # vehicles, so adding it here would give km² (wrong units).
                    if (key in ('bus', 'car', 'hov', 'truck')
                            and _t_cnt_is_veh_count and _t_cnt > 0 and sec_len_km > 0):
                        _dist_attr = f'_net_{key}_total_dist_km'
                        setattr(self, _dist_attr,
                                getattr(self, _dist_attr, 0.0) + _t_cnt * sec_len_km)
            else:
                # Fallback: snapshot-based density for sections where AKIEst gave 0
                if _n_snap > 0 and sec_len_km > 0:
                    sec_flow = _snap_flow
                    sec_density = _snap_density
                    sec_speed = _snap_speed
                    sec_got = True

            if sec_got:
                total_length_km   += sec_len_km
                total_lane_km     += sec_lane_len_km
                # Length-weighted: each section contributes proportional to its length.
                # Sections with more length get more weight, matching Aimsun's
                # network-wide statistics panel aggregation.
                total_count_veh   += _cnt                            # for total flow
                total_flow_veh_h  += sec_flow    * sec_len_km        # length-weighted
                total_density_vkm += sec_density * sec_lane_len_km   # lane-length-weighted
                total_speed_kmh   += sec_speed   * sec_len_km        # length-weighted
                n_ok += 1
                if sec_flow <= 0.0 and sec_density <= 0.0 and sec_speed <= 0.0:
                    stats_zero_sections += 1

        if n_ok > 0 and total_length_km > 0.0:
            # Length-weighted averages — Aimsun statistics panel uses length-weighted
            # network averages for density, speed, flow.
            avg_speed_kmh   = total_speed_kmh   / total_length_km   # km/h
            avg_flow_veh_h  = total_flow_veh_h  / total_length_km   # veh/h per section
            if avg_flow_veh_h <= 0.0 and total_count_veh > 0 and sim_hours > 0:
                avg_flow_veh_h = total_count_veh / sim_hours / max(n_ok, 1)

            # Density: prefer the time-averaged incremental accumulator (samples n_veh
            # every 30s throughout simulation) over the finish-time snapshot/AKIEst.
            # The finish-time approach is biased toward peak congestion (high density).
            # The time-average correctly reflects Aimsun's "Density - All" statistic
            # which is mean(vehicles_on_network) / total_network_km.
            if self._incr_net_samples > 0:
                avg_density_vkm = self._incr_net_density_sum / self._incr_net_samples
            else:
                avg_density_vkm = total_density_vkm / max(total_lane_km, 0.001)

            # Check if all-vehicle stats returned zero (count-based path failed).
            # Fall back to incremental mid-simulation samples in that case.
            all_zero = (avg_flow_veh_h <= 0 and avg_density_vkm <= 0 and avg_speed_kmh <= 0)
            if all_zero and self._incr_net_samples > 0:
                _n = self._incr_net_samples
                avg_flow_veh_h  = self._incr_net_flow_sum  / _n
                avg_density_vkm = self._incr_net_density_sum / _n
                avg_speed_kmh   = self._incr_net_speed_sum   / _n
                _src = f'incremental({_n}samples)'
            else:
                _src = 'akiest-cumul-count/sim_h'

            self._net_total_flow_veh  = int(round(avg_flow_veh_h))
            self._net_avg_density_vkm = round(avg_density_vkm, 4)
            self._net_avg_speed_kmh   = round(avg_speed_kmh,   3)

            # Store per-vehicle-type network stats (written to CSV by save_results)
            # Always set values (even if 0) so CSV does not show missing data.
            # For 'all' vehicle type, always store regardless of flow value.
            for _key in _tp_keys:
                _w = _tp_cnt[_key]
                if _key == 'all' or _w > 0:
                    # For 'all' vehicles, use aggregate calculation
                    if _key == 'all':
                        setattr(self, f'_net_flow_{_key}',    round(avg_flow_veh_h, 2) if avg_flow_veh_h > 0 else 0.0)
                        setattr(self, f'_net_density_{_key}', round(avg_density_vkm, 4) if avg_density_vkm > 0.0 else 0.0)
                        setattr(self, f'_net_speed_{_key}',   round(avg_speed_kmh, 3) if avg_speed_kmh > 0.0 else 0.0)
                    else:
                        # For per-type (car/bus/truck), use count-weighted averages
                        setattr(self, f'_net_flow_{_key}',    round(_tp_flow[_key] / _w, 2) if _w > 0 else 0.0)
                        setattr(self, f'_net_density_{_key}', round(_tp_dens[_key] / _w, 4) if _w > 0 else 0.0)
                        setattr(self, f'_net_speed_{_key}',   round(_tp_spd[_key]  / _w, 3) if _w > 0 else 0.0)
                    # Delay time (sec/km) for all types (entry + exit explicit)
                    _entry_val = round(_tp_dly_entry[_key] / _w, 2) if _w > 0 else 0.0
                    _exit_val = round(_tp_dly_exit[_key] / _w, 2) if _w > 0 else 0.0
                    setattr(self, f'_net_entry_delay_{_key}', _entry_val)
                    setattr(self, f'_net_exit_delay_{_key}', _exit_val)
                    # Backward compatibility
                    setattr(self, f'_net_delay_{_key}', _entry_val)
                else:
                    # No data for this vehicle type — set to 0
                    setattr(self, f'_net_flow_{_key}',    0.0)
                    setattr(self, f'_net_density_{_key}', 0.0)
                    setattr(self, f'_net_speed_{_key}',   0.0)
                    setattr(self, f'_net_entry_delay_{_key}', 0.0)
                    setattr(self, f'_net_exit_delay_{_key}', 0.0)
                    setattr(self, f'_net_delay_{_key}',   0.0)

            # Also set _net_delay_all explicitly for the CSV output
            self._net_delay_all = getattr(self, '_net_delay_all', 0.0)
            self._net_entry_delay_all = getattr(self, '_net_entry_delay_all', self._net_delay_all)
            self._net_exit_delay_all = getattr(self, '_net_exit_delay_all', self._net_delay_all)
            # If still zero, use the incremental sample accumulation as last resort
            if self._net_delay_all == 0.0 and self._incr_net_delay_sum > 0.0 and self._incr_net_samples > 0:
                self._net_delay_all = round(self._incr_net_delay_sum / self._incr_net_samples, 2)
                self._net_entry_delay_all = self._net_delay_all
                self._net_exit_delay_all = self._net_delay_all
            # Final fallback: flow-weighted average of per-type delays.
            # AKIEstGetGlobalStatisticsSystem can return 0 for DTa in some Aimsun builds/runs
            # while per-type stats (AKIEstGetGlobalStatisticsVehicleType) still work.
            if self._net_delay_all == 0.0:
                _wt_dly = 0.0
                _wt_cnt = 0.0
                for _kd in ('car', 'bus', 'hov', 'truck'):
                    _d = float(getattr(self, f'_net_delay_{_kd}', 0.0) or 0.0)
                    _f = float(getattr(self, f'_net_flow_{_kd}', 0.0) or 0.0)
                    if _d > 0.0 and _f > 0.0:
                        _wt_dly += _d * _f
                        _wt_cnt += _f
                if _wt_cnt > 0.0:
                    self._net_delay_all = round(_wt_dly / _wt_cnt, 2)
                    self._net_entry_delay_all = self._net_delay_all
                    self._net_exit_delay_all = self._net_delay_all

            self._net_debug.update({
                'sim_time_s': round(sim_time, 3),
                'section_count': len(section_ids),
                'stats_ok_sections': n_ok,
                'total_length_km': round(total_length_km, 3),
                'snapshot_ok_sections': 0,
                'snapshot_sections_with_vehicles': 0,
                'stats_zero_sections': stats_zero_sections,
                'snapshot_zero_sections': 0,
                'sections_missing_length': 0,
                'source': _src,
            })
        else:
            # No sections had valid length — fall back to incremental samples
            if self._incr_net_samples > 0:
                _n = self._incr_net_samples
                self._net_total_flow_veh  = int(round(self._incr_net_flow_sum / _n))
                self._net_avg_density_vkm = round(self._incr_net_density_sum / _n, 4)
                self._net_avg_speed_kmh   = round(self._incr_net_speed_sum   / _n, 3)
                if self._incr_net_delay_sum > 0.0:
                    self._net_delay_all = round(self._incr_net_delay_sum / _n, 2)
                    self._net_entry_delay_all = self._net_delay_all
                    self._net_exit_delay_all = self._net_delay_all
                self._net_debug.update({
                    'sim_time_s': round(sim_time, 3),
                    'section_count': len(section_ids),
                    'stats_ok_sections': 0,
                    'source': f'incremental-fallback({_n}samples)',
                })
            else:
                self._net_total_flow_veh  = 0
                self._net_avg_density_vkm = 0.0
                self._net_avg_speed_kmh   = 0.0
                self._net_entry_delay_all = 0.0
                self._net_exit_delay_all = 0.0
                self._net_debug.update({
                    'sim_time_s': round(sim_time, 3),
                    'section_count': len(section_ids),
                    'stats_ok_sections': 0,
                    'source': 'no-data',
                })

    # =========================================================================
    # EXTENDED SECTION STATS (ALL StructAkiEstadSection fields)
    # =========================================================================

    def collect_extra_section_stats(self, section_ids: list):
        """
        Collect extended per-section statistics not covered by
        collect_network_stats_at_finish.  Uses AKIEstGetGlobalStatisticsSection
        (cumulative whole-sim totals) to extract ALL StructAkiEstadSection
        fields and aggregates them per the Aimsun
        CalculationOfTrafficStatistics formulas.

        New instance attributes set:  _net_extra_{metric}_{key}
          key  : all | car | bus | hov | truck
          metrics:
            total_dist   (km)        — Σ TotalTravel
            total_tt_h   (h)         — Σ TotalTravelTime / 3600
            exit_count               — Σ count  (exit-based vehicle count)
            input_count              — Σ inputCount
            input_flow   (veh/h)     — input_count / sim_h
            exit_flow    (veh/h)     — exit_count  / sim_h
            total_lc                 — Σ totalLaneChanges
            mean_queue   (veh)       — Σ LongQueueAvg  (network mean queue)
            max_queue    (veh)       — Σ LongQueueMax
            vq_avg       (veh)       — Σ virtualQueueAvg
            vq_max       (veh)       — Σ virtualQueueMax
            vq_veh                   — Σ numVehiclesInVQ
            entry_tt     (sec/km)    — count-weighted avg of TTa/L_km
            exit_tt      (sec/km)    — count-weighted avg of TotalTT/count/L_km
            exit_spd     (km/h)      — count-weighted avg of Sd (exit-based speed)
            stop_time    (sec/km)    — count-weighted avg of STa/L_km
            num_stops    (#/veh/km)  — count-weighted avg of NumStops
            wait_vq      (sec)       — VQ-count-weighted avg waitingTimeVirtualQueue
        """
        if not section_ids:
            return

        # Sim duration for flow (veh/h) calculation
        sim_time_s = 0.0
        try:
            sim_time_s = float(AKIGetCurrentSimulationTime())
        except Exception:
            pass
        if sim_time_s <= 0.0:
            try:
                sim_time_s = float(AKIGetSimulationTime())
            except Exception:
                pass
        sim_hours = sim_time_s / 3600.0 if sim_time_s > 0.0 else 1.0

        _tp_keys = ['all', 'car', 'bus', 'hov', 'truck']
        _tp_pos  = [-1, self._car_pos, self._bus_pos, self._hov_pos, self._truck_pos]

        # Accumulators — direct sums
        total_dist    = {k: 0.0 for k in _tp_keys}   # km
        total_tt_s    = {k: 0.0 for k in _tp_keys}   # seconds
        total_exit    = {k: 0.0 for k in _tp_keys}   # exit count
        total_input   = {k: 0.0 for k in _tp_keys}   # input count
        total_lc      = {k: 0   for k in _tp_keys}   # total lane changes
        mean_queue    = {k: 0.0 for k in _tp_keys}   # sum LongQueueAvg
        max_queue     = {k: 0.0 for k in _tp_keys}   # sum LongQueueMax
        vq_avg        = {k: 0.0 for k in _tp_keys}   # sum virtualQueueAvg
        vq_max        = {k: 0.0 for k in _tp_keys}   # sum virtualQueueMax
        vq_veh        = {k: 0   for k in _tp_keys}   # sum numVehiclesInVQ

        # Numerators for count-weighted averages
        entry_tt_num  = {k: 0.0 for k in _tp_keys}   # Σ (TTa/L_km × count)
        entry_tt_den  = {k: 0.0 for k in _tp_keys}   # Σ count
        exit_tt_num   = {k: 0.0 for k in _tp_keys}   # Σ (TotalTT/count/L_km × count) = Σ (TotalTT/L_km)
        exit_tt_den   = {k: 0.0 for k in _tp_keys}   # Σ count
        exit_spd_num  = {k: 0.0 for k in _tp_keys}   # Σ (Sd × count)
        stop_time_num = {k: 0.0 for k in _tp_keys}   # Σ (STa/L_km × count)
        num_stops_num = {k: 0.0 for k in _tp_keys}   # Σ (NumStops × count)
        wt_vq_num     = {k: 0.0 for k in _tp_keys}   # Σ (waitTimeVQ × vq_veh)
        wt_vq_den     = {k: 0   for k in _tp_keys}   # Σ vq_veh (weight)

        for sec in section_ids:
            geom = self._get_section_geometry(sec)
            if geom is None:
                continue
            L_km = geom['length_km']
            if L_km <= 0.0:
                continue

            for key, tp in zip(_tp_keys, _tp_pos):
                # Skip type-specific when vehicle type is not resolved
                if key != 'all' and (tp is None or tp <= 0):
                    continue

                st = None
                try:
                    st = AKIEstGetGlobalStatisticsSection(sec, tp)
                    if st is None or getattr(st, 'report', -1) != 0:
                        st = None
                except Exception:
                    st = None

                if st is None:
                    try:
                        st = AKIEstGetParcialStatisticsSection(sec, 0.0, tp)
                        if st is None or getattr(st, 'report', -1) != 0:
                            st = None
                    except Exception:
                        st = None

                if st is None:
                    continue

                _count   = float(getattr(st, 'count',                  0)   or 0)
                _tta     = float(getattr(st, 'TTa',                    0.0) or 0.0)
                _sta     = float(getattr(st, 'STa',                    0.0) or 0.0)
                _nstops  = float(getattr(st, 'NumStops',               0.0) or 0.0)
                _tottrv  = float(getattr(st, 'TotalTravel',            0.0) or 0.0)  # km
                _tottt   = float(getattr(st, 'TotalTravelTime',        0.0) or 0.0)  # seconds
                _input_c = float(getattr(st, 'inputCount',             0)   or 0)
                _tlc     = int(  getattr(st, 'totalLaneChanges',       0)   or 0)
                _lq_avg  = float(getattr(st, 'LongQueueAvg',           0.0) or 0.0)
                _lq_max  = float(getattr(st, 'LongQueueMax',           0.0) or 0.0)
                _vqa     = float(getattr(st, 'virtualQueueAvg',        0.0) or 0.0)
                _vqm     = float(getattr(st, 'virtualQueueMax',        0.0) or 0.0)
                _vqveh   = int(  getattr(st, 'numVehiclesInVQ',        0)   or 0)
                _wtvq    = float(getattr(st, 'waitingTimeVirtualQueue', 0.0) or 0.0)
                _sd      = float(getattr(st, 'Sd',                     0.0) or 0.0)  # Exit-Based Speed km/h

                # Direct sums
                total_dist[key]  += _tottrv
                total_tt_s[key]  += _tottt
                total_exit[key]  += _count
                total_input[key] += _input_c
                total_lc[key]    += _tlc
                mean_queue[key]  += _lq_avg
                max_queue[key]   += _lq_max
                vq_avg[key]      += _vqa
                vq_max[key]      += _vqm
                vq_veh[key]      += _vqveh

                # Count-weighted averages
                if _count > 0:
                    entry_tt_num[key]  += (_tta  / L_km) * _count
                    entry_tt_den[key]  += _count
                    stop_time_num[key] += (_sta  / L_km) * _count
                    num_stops_num[key] += _nstops         * _count

                # Exit-Based TT (sec/km): TotalTravelTime (s) / count / L_km
                if _count > 0 and _tottt > 0:
                    _exit_tt_skm = (_tottt / _count) / L_km
                    exit_tt_num[key] += _exit_tt_skm * _count
                    exit_tt_den[key] += _count

                # Exit-Based Speed: prefer Sd (already km/h); fall back via exit TT
                if _count > 0:
                    if _sd > 0.0:
                        exit_spd_num[key] += _sd * _count
                    elif _tottt > 0.0:
                        _avg_tt_h = (_tottt / _count) / 3600.0
                        if _avg_tt_h > 0.0:
                            exit_spd_num[key] += (L_km / _avg_tt_h) * _count

                # VQ-count-weighted waiting time
                if _vqveh > 0 and _wtvq > 0.0:
                    wt_vq_num[key] += _wtvq * _vqveh
                    wt_vq_den[key] += _vqveh

        # Store results as instance attributes
        for key in _tp_keys:
            cnt    = max(entry_tt_den[key], 1.0)
            expcnt = max(exit_tt_den[key],  1.0)
            vqd    = max(wt_vq_den[key],    1)

            setattr(self, f'_net_extra_total_dist_{key}',  round(total_dist[key],  3))
            setattr(self, f'_net_extra_total_tt_h_{key}',  round(total_tt_s[key] / 3600.0, 4))
            setattr(self, f'_net_extra_exit_count_{key}',  int(round(total_exit[key])))
            setattr(self, f'_net_extra_input_count_{key}', int(round(total_input[key])))
            setattr(self, f'_net_extra_input_flow_{key}',  round(total_input[key] / sim_hours, 2))
            setattr(self, f'_net_extra_exit_flow_{key}',   round(total_exit[key]  / sim_hours, 2))
            setattr(self, f'_net_extra_total_lc_{key}',    total_lc[key])
            setattr(self, f'_net_extra_mean_queue_{key}',  round(mean_queue[key], 2))
            setattr(self, f'_net_extra_max_queue_{key}',   round(max_queue[key],  2))
            setattr(self, f'_net_extra_vq_avg_{key}',      round(vq_avg[key],     2))
            setattr(self, f'_net_extra_vq_max_{key}',      round(vq_max[key],     2))
            setattr(self, f'_net_extra_vq_veh_{key}',      vq_veh[key])
            setattr(self, f'_net_extra_wait_vq_{key}',
                    round(wt_vq_num[key] / vqd, 2) if wt_vq_den[key] > 0 else 0.0)
            setattr(self, f'_net_extra_entry_tt_{key}',
                    round(entry_tt_num[key] / cnt, 3) if entry_tt_den[key] > 0 else 0.0)
            setattr(self, f'_net_extra_exit_tt_{key}',
                    round(exit_tt_num[key] / expcnt, 3) if exit_tt_den[key] > 0 else 0.0)
            setattr(self, f'_net_extra_exit_spd_{key}',
                    round(exit_spd_num[key] / cnt, 3) if entry_tt_den[key] > 0 else 0.0)
            setattr(self, f'_net_extra_stop_time_{key}',
                    round(stop_time_num[key] / cnt, 3) if entry_tt_den[key] > 0 else 0.0)
            setattr(self, f'_net_extra_num_stops_{key}',
                    round(num_stops_num[key] / cnt, 4) if entry_tt_den[key] > 0 else 0.0)

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

        self._print("[STATS] ── NETWORK SECTION STATISTICS (Entry-Based, per-vehicle-type) ──")
        self._print(f"[STATS]   All vehicles    : flow={self._net_total_flow_veh} veh/h "
                       f"| density={self._net_avg_density_vkm:.4f} veh/km/lane "
                       f"| speed={self._net_avg_speed_kmh:.3f} km/h "
                       f"| delay={getattr(self, '_net_delay_all', 0.0):.2f} sec/km")
        self._print(f"[STATS]   Cars only       : flow={getattr(self, '_net_flow_car', 0.0):.2f} veh/h "
                       f"| density={getattr(self, '_net_density_car', 0.0):.4f} veh/km/lane "
                       f"| speed={getattr(self, '_net_speed_car', 0.0):.3f} km/h "
                       f"| delay={getattr(self, '_net_delay_car', 0.0):.2f} sec/km")
        self._print(f"[STATS]   Buses only      : flow={getattr(self, '_net_flow_bus', 0.0):.2f} veh/h "
                       f"| density={getattr(self, '_net_density_bus', 0.0):.4f} veh/km/lane "
                       f"| speed={getattr(self, '_net_speed_bus', 0.0):.3f} km/h "
                       f"| delay={getattr(self, '_net_delay_bus', 0.0):.2f} sec/km")
        self._print(f"[STATS]   Trucks only     : flow={getattr(self, '_net_flow_truck', 0.0):.2f} veh/h "
                       f"| density={getattr(self, '_net_density_truck', 0.0):.4f} veh/km/lane "
                       f"| speed={getattr(self, '_net_speed_truck', 0.0):.3f} km/h "
                       f"| delay={getattr(self, '_net_delay_truck', 0.0):.2f} sec/km")

        _src = str(self._net_debug.get('source', '') or '')
        if _src.startswith('akiest-system'):
            _raw_flow = float(self._net_debug.get('sys_raw_flow_veh_h', 0.0) or 0.0)
            _raw_dens = float(self._net_debug.get('sys_raw_density_vkm', 0.0) or 0.0)
            _raw_spd = float(self._net_debug.get('sys_raw_speed_kmh', 0.0) or 0.0)
            _raw_ent = float(self._net_debug.get('sys_raw_entry_delay_skm', 0.0) or 0.0)
            _raw_ext = float(self._net_debug.get('sys_raw_exit_delay_skm', 0.0) or 0.0)
            _adj_cnt = float(self._net_debug.get('sys_adjusted_entry_count_veh', 0.0) or 0.0)
            _exp_dens = float(getattr(self, '_net_avg_density_vkm', 0.0) or 0.0)
            _exp_spd = float(getattr(self, '_net_avg_speed_kmh', 0.0) or 0.0)
            _exp_ent = float(getattr(self, '_net_entry_delay_all', getattr(self, '_net_delay_all', 0.0)) or 0.0)
            _exp_ext = float(getattr(self, '_net_exit_delay_all', getattr(self, '_net_delay_all', 0.0)) or 0.0)
            self._print(
                f"[STATS]   Reconcile(all): direct(flow={_raw_flow:.2f} veh/h, dens={_raw_dens:.4f}, "
                f"spd={_raw_spd:.3f}, ent={_raw_ent:.2f}, exit={_raw_ext:.2f}) -> "
                f"exported(flow_count={self._net_total_flow_veh}, dens={_exp_dens:.4f}, "
                f"spd={_exp_spd:.3f}, ent={_exp_ent:.2f}, exit={_exp_ext:.2f}) "
                f"| adjusted_entry_count={_adj_cnt:.2f}"
            )
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
        experiment_label = 'manual'
        try:
            _cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     'run_config.py')
            _ns = {}
            with open(_cfg_path, 'r') as _f:
                exec(_f.read(), _ns)
            strategy = str(_ns.get('CURRENT_STRATEGY', 'unknown'))
            seed     = str(_ns.get('CURRENT_SEED',     '0'))
            experiment_label = str(_ns.get('CURRENT_EXPERIMENT', 'manual'))
        except Exception:
            pass  # run_config absent — manual run, use defaults

        safe_exp = ''.join(ch if ch.isalnum() or ch in ('_', '-') else '_' for ch in experiment_label).strip('_')
        if not safe_exp:
            safe_exp = strategy

        folder_name = f"{safe_exp}_seed{seed}_{s}_{e}_{r}"

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

    @staticmethod
    def _safe_round(v, n=4):
        """Round v to n decimals; return 0.0 if v is None/NaN/non-numeric."""
        try:
            f = float(v)
            if f != f:   # NaN
                return 0.0
            return round(f, n)
        except Exception:
            return 0.0

    def save_results(self):
        """Write global + per-intersection results to a per-run subfolder."""
        try:
            run_path = self._run_path()
        except Exception as e:
            self._print(f"[STATS] WARNING: could not create output folder: {e}")
            return

        try:
            g = self._global_kpis()
        except Exception as _e:
            self._print(f"[STATS] WARNING: _global_kpis() failed: {_e} — writing empty global row")
            g = {}

        # ── 1. Global summary CSV ───────────────────────────────────────────
        global_csv = os.path.join(run_path, "simulation_results.csv")
        self._append_csv(
            global_csv,
            headers=[
                "ScenarioID", "ExperimentID", "ReplicationID", "TSP_Strategy",
                "BusTotalTT_hrs", "N_BusTrips", "N_DistinctBuses", "N_DistinctCars", "N_DistinctTrucks",
                "AvgBusTT_s",
                "TotalPassDelay_hrs", "SidePassDelay_hrs", "MainPassDelay_hrs",
                "AvgMainPassDelay_pax_h_per_sim_h", "AvgSidePassDelay_pax_h_per_sim_h",
                "AvgTotalPassDelay_pax_h_per_sim_h", "SimDuration_hrs",
                "SimTotalDelay_pax_s", "SimBusDelay_pax_s", "SimCarDelay_pax_s", "SimTruckDelay_pax_s",
                "PaxEquivPassages", "BusPaxEquivPassages", "CarPaxEquivPassages", "TruckPaxEquivPassages",
                "AvgPassDelay_s", "AvgBusPassDelay_s", "AvgCarPassDelay_s", "AvgTruckPassDelay_s",
                "AvgObjPassDelay",
                "TSP_Detections", "TSP_Extensions", "TSP_Insertions",
                "TSP_Skipped_GE", "TSP_Skipped_Ins", "TSP_Detected_NoAction", "TSP_NaturalGreen",
                "TSP_TotalExtension_s", "TSP_TotalInsertion_s",
                "TSP_AvgExtension_s", "TSP_AvgInsertion_s", "TSP_AvgInsertionWait_s",
                # Objective metric
                "Objective_PaxPerDelayHr",
                # Corridor coordinator pre-arm outcomes
                "Prearm_Fired", "Prearm_Success", "Prearm_Missed",
                "Prearm_Expired", "Prearm_Discarded",
                "Prearm_LateSuccess", "Prearm_LateSuccessDelay_s",
                # Network-level stats — Entry-Based (count/sim_h), length-weighted
                "Net_TotalFlowVeh", "Net_AvgDensity_vkm", "Net_AvgSpeed_kmh",
                # Explicit alias to match Aimsun naming
                "Net_Density_All",
                # All-vehicle Entry-Based Delay Time (sec/km, from DTa-freeflow)/length
                "Net_Delay_All",
                "Net_EntryDelay_All", "Net_ExitDelay_All",
                # Per-type network stats: Car, Bus, Truck (flow veh/h, density veh/km, speed km/h, delay sec/km)
                "Net_Flow_Car",   "Net_Density_Car",   "Net_Speed_Car",   "Net_Delay_Car",
                "Net_Flow_Bus",   "Net_Density_Bus",   "Net_Speed_Bus",   "Net_Delay_Bus",
                "Net_Flow_HOV",   "Net_Density_HOV",   "Net_Speed_HOV",   "Net_Delay_HOV",
                "Net_Flow_Truck", "Net_Density_Truck", "Net_Speed_Truck", "Net_Delay_Truck",
                # Explicit Entry/Exit delay split by class
                "Net_EntryDelay_Car", "Net_ExitDelay_Car",
                "Net_EntryDelay_Bus", "Net_ExitDelay_Bus",
                "Net_EntryDelay_HOV", "Net_ExitDelay_HOV",
                "Net_EntryDelay_Truck", "Net_ExitDelay_Truck",
                # ── Extended section stats from collect_extra_section_stats ──
                # Total Distance Traveled (km) — Σ TotalTravel per section
                "Net_TotalDist_All", "Net_TotalDist_Car", "Net_TotalDist_Bus",
                "Net_TotalDist_HOV", "Net_TotalDist_Truck",
                # Total Travel Time (hours) — Σ TotalTravelTime/3600 per section
                "Net_TotalTT_h_All", "Net_TotalTT_h_Car", "Net_TotalTT_h_Bus",
                "Net_TotalTT_h_HOV", "Net_TotalTT_h_Truck",
                # Exit-based vehicle count — Σ count per section
                "Net_ExitCount_All", "Net_ExitCount_Car", "Net_ExitCount_Bus",
                "Net_ExitCount_HOV", "Net_ExitCount_Truck",
                # Input flow (veh/h) — Σ inputCount / sim_h
                "Net_InputFlow_All", "Net_InputFlow_Car", "Net_InputFlow_Bus",
                "Net_InputFlow_HOV", "Net_InputFlow_Truck",
                # Exit flow (veh/h) — Σ count / sim_h
                "Net_ExitFlow_All", "Net_ExitFlow_Car", "Net_ExitFlow_Bus",
                "Net_ExitFlow_HOV", "Net_ExitFlow_Truck",
                # Total Lane Changes — Σ totalLaneChanges per section
                "Net_TotalLC_All", "Net_TotalLC_Car", "Net_TotalLC_Bus",
                "Net_TotalLC_HOV", "Net_TotalLC_Truck",
                # Mean Queue (veh) — Σ LongQueueAvg per section
                "Net_MeanQueue_All", "Net_MeanQueue_Car", "Net_MeanQueue_Bus",
                "Net_MeanQueue_HOV", "Net_MeanQueue_Truck",
                # Max Queue (veh) — Σ LongQueueMax per section
                "Net_MaxQueue_All", "Net_MaxQueue_Car", "Net_MaxQueue_Bus",
                "Net_MaxQueue_HOV", "Net_MaxQueue_Truck",
                # Virtual Queue — Σ virtualQueueAvg / Max per section
                "Net_VQAvg_All", "Net_VQAvg_Car", "Net_VQAvg_Bus",
                "Net_VQAvg_HOV", "Net_VQAvg_Truck",
                "Net_VQMax_All", "Net_VQMax_Car", "Net_VQMax_Bus",
                "Net_VQMax_HOV", "Net_VQMax_Truck",
                # Vehicles in Virtual Queue — Σ numVehiclesInVQ
                "Net_VQVeh_All", "Net_VQVeh_Car", "Net_VQVeh_Bus",
                "Net_VQVeh_HOV", "Net_VQVeh_Truck",
                # Waiting Time in Virtual Queue (sec) — VQ-count-weighted avg
                "Net_WaitVQ_All", "Net_WaitVQ_Car", "Net_WaitVQ_Bus",
                "Net_WaitVQ_HOV", "Net_WaitVQ_Truck",
                # Entry-Based Travel Time (sec/km) — count-weighted avg of TTa/L_km
                "Net_EntryTT_All", "Net_EntryTT_Car", "Net_EntryTT_Bus",
                "Net_EntryTT_HOV", "Net_EntryTT_Truck",
                # Exit-Based Travel Time (sec/km) — count-weighted avg of TotalTT/count/L_km
                "Net_ExitTT_All", "Net_ExitTT_Car", "Net_ExitTT_Bus",
                "Net_ExitTT_HOV", "Net_ExitTT_Truck",
                # Exit-Based Speed (km/h) — count-weighted avg of Sd field
                "Net_ExitSpd_All", "Net_ExitSpd_Car", "Net_ExitSpd_Bus",
                "Net_ExitSpd_HOV", "Net_ExitSpd_Truck",
                # Stop Time (sec/km) — count-weighted avg of STa/L_km
                "Net_StopTime_All", "Net_StopTime_Car", "Net_StopTime_Bus",
                "Net_StopTime_HOV", "Net_StopTime_Truck",
                # Number of Stops (#/veh/km) — count-weighted avg of NumStops
                "Net_NumStops_All", "Net_NumStops_Car", "Net_NumStops_Bus",
                "Net_NumStops_HOV", "Net_NumStops_Truck",
            ],
            row=[
                self.scenario_id, self.experiment_id, self.replication_id,
                self.tsp_strategy,
                self._safe_round(g.get('bus_total_tt_hrs', 0), 4),
                g.get('n_buses', 0),
                g.get('n_distinct_buses', 0),
                g.get('n_distinct_cars', 0),
                g.get('n_distinct_trucks', 0),
                self._safe_round(g.get('avg_bus_tt_s', 0), 1),
                self._safe_round(g.get('total_pass_delay_hrs', 0), 4),
                self._safe_round(g.get('side_pass_delay_hrs', 0), 4),
                self._safe_round(g.get('main_pass_delay_hrs', 0), 4),
                self._safe_round(g.get('avg_main_pass_delay_per_hr', 0),  4),
                self._safe_round(g.get('avg_side_pass_delay_per_hr', 0),  4),
                self._safe_round(g.get('avg_total_pass_delay_per_hr', 0), 4),
                self._safe_round(g.get('sim_duration_hrs', 0), 4),
                self._safe_round(g.get('sim_total_delay', 0), 2),
                self._safe_round(g.get('sim_bus_delay', 0), 2),
                self._safe_round(g.get('sim_car_delay', 0), 2),
                self._safe_round(g.get('sim_truck_delay', 0), 2),
                self._safe_round(g.get('total_passengers', 0), 1),
                self._safe_round(g.get('bus_passengers', 0), 1),
                self._safe_round(g.get('car_passengers', 0), 1),
                self._safe_round(g.get('truck_passengers', 0), 1),
                self._safe_round(g.get('avg_pass_delay_s', 0), 2),
                self._safe_round(g.get('avg_bus_pass_delay_s', 0), 2),
                self._safe_round(g.get('avg_car_pass_delay_s', 0), 2),
                self._safe_round(g.get('avg_truck_pass_delay_s', 0), 2),
                self._safe_round(g.get('avg_obj_pass_delay', 0), 4),
                g.get('n_tsp_detections', 0),
                g.get('n_tsp_extensions', 0),
                g.get('n_tsp_insertions', 0),
                g.get('n_tsp_skipped_ge', 0),
                g.get('n_tsp_skipped_ins', 0),
                g.get('n_tsp_detected_no_action', 0),
                g.get('n_tsp_natural_green', 0),
                self._safe_round(g.get('total_extension_s', 0), 2),
                self._safe_round(g.get('total_insertion_s', 0), 2),
                self._safe_round(g.get('avg_extension_s', 0), 2),
                self._safe_round(g.get('avg_insertion_s', 0), 2),
                self._safe_round(g.get('avg_insertion_wait_s', 0), 2),
                self._safe_round(g.get('throughput_per_delay_hr', 0), 3),
                # Pre-arm coordination stats
                self._prearm_stats.get("fired",     0),
                self._prearm_stats.get("success",   0),
                self._prearm_stats.get("missed",    0),
                self._prearm_stats.get("expired",   0),
                self._prearm_stats.get("discarded", 0),
                self._prearm_stats.get("late_success", 0),
                round(float(self._prearm_stats.get("late_success_delay_s", 0.0)), 2),
                # Network section stats (all-vehicle, Entry-Based from count/sim_h)
                self._net_total_flow_veh,
                self._net_avg_density_vkm,
                self._net_avg_speed_kmh,
                # Explicit alias to match Aimsun naming
                self._net_avg_density_vkm,
                # All-vehicle Entry-Based Delay Time
                getattr(self, '_net_delay_all',   0.0),
                getattr(self, '_net_entry_delay_all', getattr(self, '_net_delay_all', 0.0)),
                getattr(self, '_net_exit_delay_all', getattr(self, '_net_delay_all', 0.0)),
                # Per-vehicle-type network stats (veh/km, veh/h, km/h, sec/km)
                getattr(self, '_net_flow_car',    0.0),
                getattr(self, '_net_density_car', 0.0),
                getattr(self, '_net_speed_car',   0.0),
                getattr(self, '_net_delay_car',   0.0),
                getattr(self, '_net_flow_bus',    0.0),
                getattr(self, '_net_density_bus', 0.0),
                getattr(self, '_net_speed_bus',   0.0),
                getattr(self, '_net_delay_bus',   0.0),
                getattr(self, '_net_flow_hov',    0.0),
                getattr(self, '_net_density_hov', 0.0),
                getattr(self, '_net_speed_hov',   0.0),
                getattr(self, '_net_delay_hov',   0.0),
                getattr(self, '_net_flow_truck',  0.0),
                getattr(self, '_net_density_truck',0.0),
                getattr(self, '_net_speed_truck', 0.0),
                getattr(self, '_net_delay_truck', 0.0),
                getattr(self, '_net_entry_delay_car', 0.0),
                getattr(self, '_net_exit_delay_car', 0.0),
                getattr(self, '_net_entry_delay_bus', 0.0),
                getattr(self, '_net_exit_delay_bus', 0.0),
                getattr(self, '_net_entry_delay_hov', 0.0),
                getattr(self, '_net_exit_delay_hov', 0.0),
                getattr(self, '_net_entry_delay_truck', 0.0),
                getattr(self, '_net_exit_delay_truck', 0.0),
                # ── Extended section stats from collect_extra_section_stats ──
                # Total Distance Traveled (km)
                getattr(self, '_net_extra_total_dist_all',   0.0),
                getattr(self, '_net_extra_total_dist_car',   0.0),
                getattr(self, '_net_extra_total_dist_bus',   0.0),
                getattr(self, '_net_extra_total_dist_hov',   0.0),
                getattr(self, '_net_extra_total_dist_truck', 0.0),
                # Total Travel Time (hours)
                getattr(self, '_net_extra_total_tt_h_all',   0.0),
                getattr(self, '_net_extra_total_tt_h_car',   0.0),
                getattr(self, '_net_extra_total_tt_h_bus',   0.0),
                getattr(self, '_net_extra_total_tt_h_hov',   0.0),
                getattr(self, '_net_extra_total_tt_h_truck', 0.0),
                # Exit Count
                getattr(self, '_net_extra_exit_count_all',   0),
                getattr(self, '_net_extra_exit_count_car',   0),
                getattr(self, '_net_extra_exit_count_bus',   0),
                getattr(self, '_net_extra_exit_count_hov',   0),
                getattr(self, '_net_extra_exit_count_truck', 0),
                # Input Flow (veh/h)
                getattr(self, '_net_extra_input_flow_all',   0.0),
                getattr(self, '_net_extra_input_flow_car',   0.0),
                getattr(self, '_net_extra_input_flow_bus',   0.0),
                getattr(self, '_net_extra_input_flow_hov',   0.0),
                getattr(self, '_net_extra_input_flow_truck', 0.0),
                # Exit Flow (veh/h)
                getattr(self, '_net_extra_exit_flow_all',   0.0),
                getattr(self, '_net_extra_exit_flow_car',   0.0),
                getattr(self, '_net_extra_exit_flow_bus',   0.0),
                getattr(self, '_net_extra_exit_flow_hov',   0.0),
                getattr(self, '_net_extra_exit_flow_truck', 0.0),
                # Total Lane Changes
                getattr(self, '_net_extra_total_lc_all',   0),
                getattr(self, '_net_extra_total_lc_car',   0),
                getattr(self, '_net_extra_total_lc_bus',   0),
                getattr(self, '_net_extra_total_lc_hov',   0),
                getattr(self, '_net_extra_total_lc_truck', 0),
                # Mean Queue (veh)
                getattr(self, '_net_extra_mean_queue_all',   0.0),
                getattr(self, '_net_extra_mean_queue_car',   0.0),
                getattr(self, '_net_extra_mean_queue_bus',   0.0),
                getattr(self, '_net_extra_mean_queue_hov',   0.0),
                getattr(self, '_net_extra_mean_queue_truck', 0.0),
                # Max Queue (veh)
                getattr(self, '_net_extra_max_queue_all',   0.0),
                getattr(self, '_net_extra_max_queue_car',   0.0),
                getattr(self, '_net_extra_max_queue_bus',   0.0),
                getattr(self, '_net_extra_max_queue_hov',   0.0),
                getattr(self, '_net_extra_max_queue_truck', 0.0),
                # Virtual Queue Avg (veh)
                getattr(self, '_net_extra_vq_avg_all',   0.0),
                getattr(self, '_net_extra_vq_avg_car',   0.0),
                getattr(self, '_net_extra_vq_avg_bus',   0.0),
                getattr(self, '_net_extra_vq_avg_hov',   0.0),
                getattr(self, '_net_extra_vq_avg_truck', 0.0),
                # Virtual Queue Max (veh)
                getattr(self, '_net_extra_vq_max_all',   0.0),
                getattr(self, '_net_extra_vq_max_car',   0.0),
                getattr(self, '_net_extra_vq_max_bus',   0.0),
                getattr(self, '_net_extra_vq_max_hov',   0.0),
                getattr(self, '_net_extra_vq_max_truck', 0.0),
                # Vehicles in VQ
                getattr(self, '_net_extra_vq_veh_all',   0),
                getattr(self, '_net_extra_vq_veh_car',   0),
                getattr(self, '_net_extra_vq_veh_bus',   0),
                getattr(self, '_net_extra_vq_veh_hov',   0),
                getattr(self, '_net_extra_vq_veh_truck', 0),
                # Waiting Time in VQ (sec)
                getattr(self, '_net_extra_wait_vq_all',   0.0),
                getattr(self, '_net_extra_wait_vq_car',   0.0),
                getattr(self, '_net_extra_wait_vq_bus',   0.0),
                getattr(self, '_net_extra_wait_vq_hov',   0.0),
                getattr(self, '_net_extra_wait_vq_truck', 0.0),
                # Entry-Based Travel Time (sec/km)
                getattr(self, '_net_extra_entry_tt_all',   0.0),
                getattr(self, '_net_extra_entry_tt_car',   0.0),
                getattr(self, '_net_extra_entry_tt_bus',   0.0),
                getattr(self, '_net_extra_entry_tt_hov',   0.0),
                getattr(self, '_net_extra_entry_tt_truck', 0.0),
                # Exit-Based Travel Time (sec/km)
                getattr(self, '_net_extra_exit_tt_all',   0.0),
                getattr(self, '_net_extra_exit_tt_car',   0.0),
                getattr(self, '_net_extra_exit_tt_bus',   0.0),
                getattr(self, '_net_extra_exit_tt_hov',   0.0),
                getattr(self, '_net_extra_exit_tt_truck', 0.0),
                # Exit-Based Speed (km/h)
                getattr(self, '_net_extra_exit_spd_all',   0.0),
                getattr(self, '_net_extra_exit_spd_car',   0.0),
                getattr(self, '_net_extra_exit_spd_bus',   0.0),
                getattr(self, '_net_extra_exit_spd_hov',   0.0),
                getattr(self, '_net_extra_exit_spd_truck', 0.0),
                # Stop Time (sec/km)
                getattr(self, '_net_extra_stop_time_all',   0.0),
                getattr(self, '_net_extra_stop_time_car',   0.0),
                getattr(self, '_net_extra_stop_time_bus',   0.0),
                getattr(self, '_net_extra_stop_time_hov',   0.0),
                getattr(self, '_net_extra_stop_time_truck', 0.0),
                # Number of Stops (#/veh/km)
                getattr(self, '_net_extra_num_stops_all',   0.0),
                getattr(self, '_net_extra_num_stops_car',   0.0),
                getattr(self, '_net_extra_num_stops_bus',   0.0),
                getattr(self, '_net_extra_num_stops_hov',   0.0),
                getattr(self, '_net_extra_num_stops_truck', 0.0),
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
                    "CarPaxEquivPassages",  # car vehicle passages × CarOcc (1.2 pax/car)
                    "TruckPaxEquivPassages",# truck passages × TruckOcc
                    # Average delay per passenger
                    "AvgPassDelay_s",       # total delay / total passengers (s/pax)
                    "AvgBusPassDelay_s",    # bus delay / bus passengers (s/pax)
                    "AvgCarPassDelay_s",    # car delay / car passengers (s/pax)
                    "AvgTruckPassDelay_s",  # truck delay / truck passengers (s/pax)
                    "AvgMainPassDelay_pax_h_per_sim_h",
                    "AvgSidePassDelay_pax_h_per_sim_h",
                    "AvgTotalPassDelay_pax_h_per_sim_h",
                    "SimDuration_hrs",
                    # Signal timing totals
                    "TotalGreen_s",         # total green time (s)
                    "TotalRed_s",           # total red time (s)
                    # Section metadata
                    "N_MainSections", "N_SideSections", "SideSectionsResolved",
                    "MainSectionIDs", "SideSectionIDs",
                    # Density / speed / flow (time-averaged from vehicle-state sampling)
                    "AvgDensity_vkm",   # mean density across approach sections (veh/km)
                    "AvgSpeed_kmh",     # mean speed across approach sections (km/h)
                    "AvgFlow_veh_h",    # mean flow across approach sections (veh/h)
                    "AvgQueue_veh",     # mean queued vehicles (speed<5 km/h) across sections
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
                    "TSP_NaturalGreen",      # bus naturally clears on green
                    # Duration averages
                    "TSP_AvgExtension_s",    # mean granted GE per extension event
                    "TSP_AvgInsertion_s",    # mean granted BP per insertion event
                    "TSP_AvgInsertionWait_s",# mean wait from insertion grant to bus arrival
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
                    round(k['avg_main_pass_delay_per_hr'], 4),
                    round(k['avg_side_pass_delay_per_hr'], 4),
                    round(k['avg_total_pass_delay_per_hr'], 4),
                    round(k['sim_duration_hrs'], 4),
                    round(k['total_green_s'], 2),
                    round(k['total_red_s'], 2),
                    k['n_main_sections'],
                    k['n_side_sections'],
                    int(k['side_sections_resolved']),
                    "|".join(str(x) for x in k['main_sections']),
                    "|".join(str(x) for x in k['side_sections']),
                    round(k['avg_density_vkm'], 4),
                    round(k['avg_speed_kmh'], 3),
                    round(k['avg_flow_veh_h'], 2),
                    round(k['avg_queue_veh'], 2),
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
                    k['n_natural_green'],
                    round(k['avg_extension_s'], 2),
                    round(k['avg_insertion_s'], 2),
                    round(k['avg_insertion_wait_s'], 2),
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

        # ── 3b. Per-section (corridor) CSV ──────────────────────────────────
        if self._section_dsf:
            section_csv = os.path.join(run_path, "section_stats.csv")
            _MIN_SEC_LEN_KM = 0.015   # exclude connectors shorter than 15 m
            for sec_id in sorted(self._section_dsf.keys()):
                sd = self._section_dsf[sec_id]
                n = sd['samples']
                # Skip sections with no samples or too short to be meaningful.
                # Very short connectors (<15 m) cause inflated density (1 veh /
                # 0.001 km = 1000 veh/km) and are not representative approaches.
                if n == 0 or sd['length_km'] < _MIN_SEC_LEN_KM:
                    continue
                self._append_csv(
                    section_csv,
                    headers=[
                        "ScenarioID", "ExperimentID", "ReplicationID",
                        "TSP_Strategy", "SectionID", "IntersectionID",
                        "IsMain", "Length_km",
                        "AvgDensity_vkm", "AvgSpeed_kmh", "AvgFlow_veh_h", "AvgQueue_veh",
                        "N_Samples",
                    ],
                    row=[
                        self.scenario_id, self.experiment_id, self.replication_id,
                        self.tsp_strategy, sec_id, sd['inter_id'],
                        int(sd['is_main']), round(sd['length_km'], 4),
                        round(sd['density_sum'] / n, 4) if n > 0 else 0.0,
                        round(sd['speed_sum'] / n, 3) if n > 0 else 0.0,
                        round(sd['flow_sum'] / n, 2) if n > 0 else 0.0,
                        round(sd.get('queue_sum', 0.0) / n, 2) if n > 0 else 0.0,
                        n,
                    ],
                )

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
                'avg_density_vkm':      round(k['avg_density_vkm'], 4),
                'avg_speed_kmh':        round(k['avg_speed_kmh'], 3),
                'avg_flow_veh_h':       round(k['avg_flow_veh_h'], 2),
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
                'n_tsp_skipped_ge':      g['n_tsp_skipped_ge'],
                'n_tsp_skipped_ins':     g['n_tsp_skipped_ins'],
                'n_tsp_detected_no_action': g['n_tsp_detected_no_action'],
                'n_tsp_natural_green':   g['n_tsp_natural_green'],
                'total_extension_s':     g.get('total_extension_s', 0.0),
                'total_insertion_s':     g.get('total_insertion_s', 0.0),
                'avg_extension_s': (g.get('total_extension_s', 0.0) / g.get('n_extensions', g.get('n_tsp_extensions', 0))
                                    if g.get('n_extensions', g.get('n_tsp_extensions', 0)) > 0 else 0.0),
                'avg_insertion_s': (g.get('total_insertion_s', 0.0) / g.get('n_insertions', g.get('n_tsp_insertions', 0))
                                    if g.get('n_insertions', g.get('n_tsp_insertions', 0)) > 0 else 0.0),
                'avg_insertion_wait_s': (g.get('total_insertion_wait_s', 0.0) / g.get('n_insertion_wait_samples', 0)
                                            if g.get('n_insertion_wait_samples', 0) > 0 else 0.0),
                'sim_duration_hrs':      g['sim_duration_hrs'],
                'n_detections':          g.get('n_detections', g.get('n_tsp_detections', 0)),
                'n_extensions':          g.get('n_extensions', g.get('n_tsp_extensions', 0)),
                'n_insertions':          g.get('n_insertions', g.get('n_tsp_insertions', 0)),
                'n_exit_clears':         g.get('n_exit_clears', 0),
                'n_cap_clears':          g.get('n_cap_clears', 0),
                'n_skipped_ge':          g.get('n_skipped_ge', 0),
                'n_skipped_ins':         g.get('n_skipped_ins', 0),
                'n_detected_no_action':  g.get('n_detected_no_action', 0),
                'n_natural_green':       g.get('n_natural_green', 0),
                'total_vehicles':        g.get('n_distinct_buses', 0) + g.get('n_distinct_cars', 0) + g.get('n_distinct_trucks', 0),
                'n_main_sections':       len(g.get('main_sections', [])),
                'n_side_sections':       len(g.get('side_sections', [])),
                'side_sections_resolved': bool(g.get('side_sections_resolved', False)),
                'main_sections':         list(g.get('main_sections', [])),
                'side_sections':         list(g.get('side_sections', [])),
                # Density / speed / flow / queue (network-level, not per-intersection)
                'avg_speed_kmh':   self._net_avg_speed_kmh,
                'avg_flow_veh_h':  self._net_total_flow_veh,
                # Green/red totals (not tracked at global level — always 0)
                'total_green_s': 0.0,
                'total_red_s':   0.0,
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

