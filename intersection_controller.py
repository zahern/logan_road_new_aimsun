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

# =============================================================================
# LOGGING FLAGS  —  set each True/False to control verbosity
# All critical errors are always printed regardless of these flags.
# =============================================================================

# ── Core control modes ────────────────────────────────────────────────────────
LOG_HARMONY   = False  # [HARMONY]    GE/insertion decisions in HARMONY mode
LOG_URTSP     = False   # [URTSP]      detection/extension/insertion in URTSP mode
LOG_REWARD    = False   # [REWARD]     action-reward evaluation in REWARD_TSP mode
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
MARK_DETECTION_POINTS: bool = True
TRACK_BUS_POSITIONS: bool = True
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

# =============================================================================
# LIVE STATUS DASHBOARD
# STATUS_DASHBOARD_INTERVAL_S:
#   How often (in simulation seconds) to print a formatted status table to the
#   Aimsun console showing every intersection's current TSP state.
#   The table always prints regardless of VERBOSE so you can see what the
#   controller is doing at a glance without scrolling through debug logs.
#
#   Columns:  Jct | Phase | Flag | GE-debt | Bus? | det/ext/ins counts
#
#   Set to 0 to disable the dashboard.
# =============================================================================
STATUS_DASHBOARD_INTERVAL_S: float = 0.0   # 0 = disabled

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
_BUS_TRACK_INTERVAL_S = 5.0   # log every N seconds (keep lightweight)
_bus_track_last_t: float = -1e9
_bus_track_header_written: bool = False
_jct_xy_cache: dict = None
# Track zone state per (veh_id, junction_id) for entry/exit events
_bus_zone_state: dict = {}   # (veh_id, jct_id) → bool (in zone)
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
_corridor_jct_incoming: dict = {}# {jct_id: set(section_ids)} from INTERSECTIONS_CONFIG
# Per-bus observed corridor-junction sequence (in entry order from zone_enter events).
# {veh_id: [jct_id, ...]}  Used as a real-time route fallback when _pt_line_jct_route
# has no entry for this bus's PT line (bus-route-aware pre-arm targeting).
_bus_observed_jcts: dict = {}    # {veh_id: [jct_id, ...]} ordered zone-enters
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


def _finite_xy(x_val, y_val):
    try:
        x_f = float(x_val)
        y_f = float(y_val)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(x_f) and math.isfinite(y_f)):
        return None
    if x_f == 0.0 and y_f == 0.0:
        return None
    return (x_f, y_f)


def _extract_xy_from_point_like(obj):
    if obj is None:
        return None
    if isinstance(obj, (tuple, list)) and len(obj) >= 2:
        return _finite_xy(obj[0], obj[1])

    for _x_attr, _y_attr in (
        ('x', 'y'),
        ('getX', 'getY'),
        ('xCoord', 'yCoord'),
        ('getx', 'gety'),
    ):
        _x = getattr(obj, _x_attr, None)
        _y = getattr(obj, _y_attr, None)
        if _x is None or _y is None:
            continue
        try:
            _x = _x() if callable(_x) else _x
            _y = _y() if callable(_y) else _y
        except Exception:
            continue
        _xy = _finite_xy(_x, _y)
        if _xy is not None:
            return _xy
    return None


def _extract_xy_from_section_info(sec_info):
    if sec_info is None:
        return None
    for _x_attr, _y_attr in (
        ('xSection', 'ySection'),
        ('xSectionTo', 'ySectionTo'),
        ('xcoordTo', 'ycoordTo'),
        ('xTo', 'yTo'),
        ('xDestination', 'yDestination'),
        ('xEnd', 'yEnd'),
        ('x', 'y'),
    ):
        _xy = _finite_xy(getattr(sec_info, _x_attr, None), getattr(sec_info, _y_attr, None))
        if _xy is not None:
            return _xy
    return None


def _extract_xy_from_catalog_object(obj):
    if obj is None:
        return None

    for _meth in ('getPosition', 'getCenter', 'getCentroid', 'center', 'centroid'):
        _fn = getattr(obj, _meth, None)
        if not callable(_fn):
            continue
        try:
            _xy = _extract_xy_from_point_like(_fn())
        except Exception:
            _xy = None
        if _xy is not None:
            return _xy

    _xy = _extract_xy_from_point_like(obj)
    if _xy is not None:
        return _xy

    for _child_meth in ('getNodes', 'getChildNodes', 'getInternalNodes', 'getSubNodes'):
        _fn = getattr(obj, _child_meth, None)
        if not callable(_fn):
            continue
        try:
            _children = list(_fn() or [])
        except Exception:
            continue
        _pts = []
        for _child in _children:
            _cxy = _extract_xy_from_catalog_object(_child)
            if _cxy is not None:
                _pts.append(_cxy)
        if _pts:
            return (
                sum(_p[0] for _p in _pts) / len(_pts),
                sum(_p[1] for _p in _pts) / len(_pts),
            )

    return None


def _resolve_junction_xy_from_model(node_id: int, incoming_sections=None):
    try:
        from PyANGKernel import GKSystem as _GKS
        _model = _GKS.getSystem().getActiveModel()
        if _model is None:
            return None
        _catalog = _model.getCatalog()
        _candidate_ids = []
        if node_id and node_id > 0:
            _candidate_ids.append(int(node_id))
        for _sec_id in incoming_sections or []:
            try:
                _si = AKIInfNetGetSectionANGInf(int(_sec_id))
                _node_to = int(getattr(_si, 'idNodeTo', 0) or 0)
                if _node_to > 0 and _node_to not in _candidate_ids:
                    _candidate_ids.append(_node_to)
            except Exception:
                continue

        for _cid in _candidate_ids:
            try:
                _obj = _catalog.find(_cid)
            except Exception:
                _obj = None
            _xy = _extract_xy_from_catalog_object(_obj)
            if _xy is not None:
                return _xy
    except Exception:
        return None
    return None


def _network_stats_section_ids():
    global _net_stats_sections_cache
    if _net_stats_sections_cache is not None:
        return list(_net_stats_sections_cache)

    _secs: set = set()
    try:
        _n_secs = int(AKIInfNetNbSectionsANG())
        for _si in range(_n_secs):
            _sid = int(AKIInfNetGetSectionANGId(_si))
            if _sid > 0:
                _secs.add(_sid)
    except Exception:
        pass

    if not _secs:
        for _iid_data in getattr(stats, '_inter', {}).values():
            for _sec in _iid_data.get('main_sections', []):
                if isinstance(_sec, int) and _sec > 0:
                    _secs.add(_sec)
            for _sec in _iid_data.get('side_sections', []):
                if isinstance(_sec, int) and _sec > 0:
                    _secs.add(_sec)
        for _ctrl in controllers.values():
            for _sec in getattr(_ctrl, 'incoming_sections', []):
                if _sec and _sec > 0:
                    _secs.add(int(_sec))

    _net_stats_sections_cache = _secs
    return list(_secs)


def _mark_detection_point(junction_id: int, veh_id: int, x: float, y: float,
                          sim_time: float, tier: str):
    """
    Record the first detection event for this (junction, vehicle) pair.

    1. Writes a row to detection_points.csv immediately (includes signal_phase
       and bus_phase so the green-wave plot can show green/red status).
    2. Appends a GeoJSON feature (flushed to .geojson in AAPIFinish).
    3. Attempts to colour the vehicle bright red in the Aimsun animation.
       The colour API may not exist in all Aimsun builds — failure is silent.
    """
    global _mark_calls_total, _mark_calls_written
    _mark_calls_total += 1

    if not MARK_DETECTION_POINTS:
        return
    key = (junction_id, veh_id)
    _last_t = _marked_detections.get(key, -9999.0)
    if sim_time - _last_t < _MARK_DET_REARM_S:
        return
    _marked_detections[key] = sim_time
    _mark_calls_written += 1

    # ── Capture current signal phase and configured bus phase ─────────────────
    _signal_phase = -1
    try:
        _signal_phase = ECIGetCurrentPhase(junction_id)
    except Exception:
        pass
    _bus_phase = -1
    try:
        _cfg = INTERSECTIONS_CONFIG.get(junction_id, {})
        _bus_phase = int(_cfg.get("BusPhase", -1) or -1)
    except Exception:
        pass
    _phase_start_t = -1.0
    try:
        _phase_start_t = float(ECIGetStartingTimePhase(junction_id))
    except Exception:
        pass

    # ── 1. CSV ────────────────────────────────────────────────────────────────
    # Look up the junction centroid so the map can overlay intersection markers.
    _jct_entry = (_jct_xy_cache or {}).get(junction_id)
    _jct_cx = f"{_jct_entry[0]:.3f}" if _jct_entry else ""
    _jct_cy = f"{_jct_entry[1]:.3f}" if _jct_entry else ""
    write_header = not os.path.isfile(_DET_CSV)
    try:
        with open(_DET_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(["sim_time_s", "junction_id", "veh_id",
                             "x", "y", "tier", "signal_phase", "bus_phase",
                             "phase_start_t", "jct_x", "jct_y"])
            w.writerow([f"{sim_time:.1f}", junction_id, veh_id,
                        f"{x:.3f}", f"{y:.3f}", tier, _signal_phase, _bus_phase,
                        f"{_phase_start_t:.1f}", _jct_cx, _jct_cy])
    except Exception as _e:
        log_to_file(f"[MARK] CSV write failed: {_e}", force=True)

    # ── 2. GeoJSON feature accumulation ───────────────────────────────────────
    _geojson_features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [x, y]},
        "properties": {
            "junction_id": junction_id,
            "veh_id":      veh_id,
            "sim_time_s":  round(sim_time, 1),
            "tier":        tier,
        },
    })

    # ── 3. Colour vehicle red in Aimsun animation ─────────────────────────────
    # AKIVehSetVehicleColor(veh_id, R, G, B) is available in Aimsun Next ≥22.
    # Looked up via globals() so static analysis doesn't flag an undefined name
    # (it arrives via `from AAPI import *`).  Falls back silently if absent.
    try:
        _color_fn = globals().get("AKIVehSetVehicleColor")
        if _color_fn is not None:
            _color_fn(veh_id, 255, 0, 0)   # bright red
    except Exception:
        pass

    log_to_file(
        f"[MARK] jct={junction_id} v={veh_id} tier={tier} "
        f"xy=({x:.1f},{y:.1f}) t={sim_time:.1f}s"
    )


def _record_wave_event(time_s: float, group_name: str, event: str,
                       source_jct: int = -1, target_jct: int = -1,
                       veh_id: int = -1, eta_s: float = -1.0,
                       lead_s: float = -1.0, note: str = ""):
    """Append a structured coordinator event row for post-run diagnostics."""
    _wave_events.append({
        "sim_time_s": round(float(time_s), 1),
        "group": str(group_name),
        "event": str(event),
        "source_jct": int(source_jct),
        "target_jct": int(target_jct),
        "veh_id": int(veh_id),
        "eta_s": round(float(eta_s), 1) if eta_s is not None else -1.0,
        "lead_s": round(float(lead_s), 1) if lead_s is not None else -1.0,
        "note": str(note),
    })


def _track_all_bus_positions(time: float, jct_xy: dict):
    """
    Log every PT-line bus position every _BUS_TRACK_INTERVAL_S seconds.

    Writes: sim_time_s, veh_id, x, y, nearest_jct, dist_m, in_zone, zone_radius_m, event

    event column: 'track' (normal), 'zone_enter' (first time inside zone),
                  'zone_exit' (left zone).

    jct_xy: {junction_id: (x, y, detection_zone_m)} — pre-built from controllers.
    If empty, still records raw bus positions with nearest_jct=-1.
    """
    global _bus_track_last_t, _bus_track_header_written, _bus_zone_state
    global _bus_seen_ids, _bus_last_nearest_jct, _bus_line_id
    global _tracking_zone_presence, _bus_observed_jcts
    global _active_corridor_bus_count
    if time - _bus_track_last_t < _BUS_TRACK_INTERVAL_S:
        return
    _bus_track_last_t = time
    # Rebuild the live zone-presence snapshot from scratch each interval
    _tracking_zone_presence.clear()

    rows = []
    _bus_xy = {}  # veh_id -> (x,y)
    active_veh_ids = set()
    try:
        n_lines = AKIPTGetNumberLines()
        for li in range(n_lines):
            line_id = AKIPTGetIdLine(li)
            n_veh = AKIGetNbVehiclesFollowingPTLine(line_id)
            for vi in range(n_veh):
                veh_id = AKIGetVehicleFollowingPTLine(line_id, vi)
                try:
                    inf = AKIPTVehGetInf(veh_id)
                    if getattr(inf, 'report', -1) < 0:
                        continue
                    bx = float(getattr(inf, 'xCurrentPos', 0.0) or 0.0)
                    by = float(getattr(inf, 'yCurrentPos', 0.0) or 0.0)
                    if bx == 0.0 and by == 0.0:
                        continue
                    bspd = float(getattr(inf, 'CurrentSpeed', 40.0) or 40.0)
                except Exception:
                    continue

                active_veh_ids.add(veh_id)
                _bus_xy[veh_id] = (bx, by)
                # Record which PT line this bus is currently following
                _bus_line_id[veh_id] = line_id

                # ── Section-based detection ───────────────────────────────────
                # If the bus is on a section that feeds a corridor junction,
                # fire an auto-detection even if it hasn't entered the spatial zone.
                # Only mark the NEAREST mapped junction to avoid simultaneous
                # detections at multiple junctions from a shared section.
                try:
                    _bus_sec = int(getattr(inf, 'idSection', -1))
                    if _bus_sec > 0 and _bus_sec in _sec_to_corridor_jct:
                        _sec_jcts = _sec_to_corridor_jct[_bus_sec]
                        if len(_sec_jcts) == 1:
                            _mark_detection_point(_sec_jcts[0], veh_id, bx, by, time, "track-section")
                        elif jct_xy:
                            _nearest_sec_jct = min(
                                _sec_jcts,
                                key=lambda _j: math.sqrt(
                                    (bx - jct_xy[_j][0])**2 + (by - jct_xy[_j][1])**2
                                ) if _j in jct_xy else 1e9
                            )
                            _mark_detection_point(_nearest_sec_jct, veh_id, bx, by, time, "track-section")
                        else:
                            _mark_detection_point(_sec_jcts[0], veh_id, bx, by, time, "track-section")
                except Exception:
                    pass

                if jct_xy:
                    # ── Pre-scan: find the nearest junction newly entering zone ──
                    # When junction detection zones overlap (junctions ~300 m apart,
                    # zones 250 m radius), a single bus can transition from out→in for
                    # multiple junctions in the same scan step.  Restrict zone_enter
                    # events (detection-point marking, route tracking, bus-TT entry)
                    # to the NEAREST newly-entered junction so the bus appears at one
                    # junction at a time and journey charts don't show teleportation.
                    _new_zone_entries_this_step = []
                    _dist_cache_this_bus = {}
                    for _jid_pre, (_jx_pre, _jy_pre, _zr_pre) in jct_xy.items():
                        _d_pre = math.sqrt((bx - _jx_pre)**2 + (by - _jy_pre)**2)
                        _dist_cache_this_bus[_jid_pre] = _d_pre
                        if _d_pre <= _zr_pre and not _bus_zone_state.get((veh_id, _jid_pre), False):
                            _new_zone_entries_this_step.append((_d_pre, _jid_pre))
                    _nearest_new_entry_jct = (
                        min(_new_zone_entries_this_step, key=lambda _x: _x[0])[1]
                        if _new_zone_entries_this_step else None
                    )

                    # Check zone status for EVERY junction (not just nearest)
                    for jid, (jx, jy, zr) in jct_xy.items():
                        d = _dist_cache_this_bus.get(jid) or math.sqrt((bx - jx)**2 + (by - jy)**2)
                        now_in = d <= zr
                        zkey = (veh_id, jid)
                        was_in = _bus_zone_state.get(zkey, False)
                        event = "track"
                        if now_in:
                            # Keep live zone-presence snapshot current so that
                            # detect_bus / _detect_bus can use it as Tier 0.
                            _tracking_zone_presence.setdefault(jid, {})[veh_id] = (bx, by, bspd)
                        if now_in and not was_in:
                            _bus_zone_state[zkey] = True
                            # Only fire zone_enter events for the nearest newly-entered
                            # junction.  Other overlapping zones are marked in-state so
                            # they don't re-fire, but their events are suppressed so the
                            # bus appears sequentially on the journey chart.
                            if jid == _nearest_new_entry_jct:
                                event = "zone_enter"
                                # ── Record observed corridor-junction route ───────
                                try:
                                    obs = _bus_observed_jcts.setdefault(veh_id, [])
                                    if not obs or obs[-1] != jid:
                                        obs.append(jid)
                                except Exception:
                                    pass
                                # ── Auto-detection point ──────────────────────────
                                try:
                                    _mark_detection_point(jid, veh_id, bx, by, time, "track-zone")
                                except Exception:
                                    pass
                                # ── Bus TT zone-entry ─────────────────────────────
                                try:
                                    stats.record_pt_bus_detection(jid, veh_id, time)
                                except Exception:
                                    pass
                        elif not now_in and was_in:
                            event = "zone_exit"
                            _bus_zone_state[zkey] = False
                            # ── Bus TT zone-exit ──────────────────────────────
                            try:
                                stats.record_pt_bus_exit(jid, veh_id, time)
                            except Exception:
                                pass
                        # Only log zone events for non-nearest junctions
                        # Always log one row per bus for nearest junction
                        if event != "track":
                            rows.append((
                                f"{time:.1f}", veh_id,
                                f"{bx:.1f}", f"{by:.1f}",
                                jid, f"{d:.0f}",
                                1 if now_in else 0, f"{zr:.0f}", event,
                            ))

                    # Find nearest junction for the main tracking row
                    best_jct = -1
                    best_dist = 1e9
                    best_zone = 0.0
                    for jid, (jx, jy, zr) in jct_xy.items():
                        d = math.sqrt((bx - jx)**2 + (by - jy)**2)
                        if d < best_dist:
                            best_dist = d
                            best_jct = jid
                            best_zone = zr
                    in_zone = 1 if best_dist <= best_zone else 0
                else:
                    best_jct = -1
                    best_dist = -1.0
                    best_zone = 0.0
                    in_zone = 0
                rows.append((
                    f"{time:.1f}", veh_id,
                    f"{bx:.1f}", f"{by:.1f}",
                    best_jct, f"{best_dist:.0f}",
                    in_zone, f"{best_zone:.0f}", "track",
                ))
    except Exception:
        pass

    # Supplement/fallback: some models do not expose PT-line followers reliably,
    # or may omit injected buses from PT APIs. Scan live section vehicles by
    # inferred bus type to capture missing buses.
    if BUS_TRACK_SUPPLEMENT_NETWORK_SCAN or not rows:
        try:
            _bus_type_pos = int(getattr(stats, '_bus_pos', -1) or -1)
        except Exception:
            _bus_type_pos = -1
        if _bus_type_pos > 0:
            _scan_secs = set()
            try:
                _scan_secs.update(int(_s) for _s in _network_stats_section_ids() if int(_s) > 0)
            except Exception:
                pass
            if not _scan_secs:
                for _ctrl in controllers.values():
                    for _s in getattr(_ctrl, 'incoming_sections', []):
                        if _s and _s > 0:
                            _scan_secs.add(int(_s))
                try:
                    for _d in getattr(stats, '_inter', {}).values():
                        for _s in _d.get('all_sections', []):
                            if _s and _s > 0:
                                _scan_secs.add(int(_s))
                except Exception:
                    pass

            seen_fallback = set()
            _supplement_only_missing = bool(rows)
            for _sec in _scan_secs:
                try:
                    _n = max(int(AKIVehStateGetNbVehiclesSection(_sec, True)), 0)
                except Exception:
                    _n = 0
                for _i in range(_n):
                    try:
                        _inf = AKIVehStateGetVehicleInfSection(_sec, _i)
                        _vid = int(getattr(_inf, 'idVeh', -1) or -1)
                        _typ = int(getattr(_inf, 'type', -1) or -1)
                        if _vid <= 0 or _typ != _bus_type_pos or _vid in seen_fallback:
                            continue
                        if _supplement_only_missing and _vid in _bus_xy:
                            continue
                        _bx = float(getattr(_inf, 'xCurrentPos', 0.0) or 0.0)
                        _by = float(getattr(_inf, 'yCurrentPos', 0.0) or 0.0)
                        if _bx == 0.0 and _by == 0.0:
                            continue
                        seen_fallback.add(_vid)
                        active_veh_ids.add(_vid)
                        _bus_xy[_vid] = (_bx, _by)

                        if jct_xy:
                            _best_j = -1
                            _best_d = 1e9
                            _best_z = 0.0
                            for _jid, (_jx, _jy, _zr) in jct_xy.items():
                                _d = math.sqrt((_bx - _jx)**2 + (_by - _jy)**2)
                                if _d < _best_d:
                                    _best_d = _d
                                    _best_j = _jid
                                    _best_z = _zr
                                # Also update zone-presence for supplement buses
                                # so detect_bus Tier 0 can use them
                                if _d <= _zr:
                                    _tracking_zone_presence.setdefault(_jid, {})[_vid] = (_bx, _by, float(getattr(_inf, 'CurrentSpeed', 40.0) or 40.0))
                            _inz = 1 if _best_d <= _best_z else 0
                        else:
                            _best_j = -1
                            _best_d = -1.0
                            _best_z = 0.0
                            _inz = 0

                        rows.append((
                            f"{time:.1f}", _vid,
                            f"{_bx:.1f}", f"{_by:.1f}",
                            _best_j, f"{_best_d:.0f}",
                            _inz, f"{_best_z:.0f}", "track",
                        ))
                    except Exception:
                        continue

    # Update live corridor bus count for queue snapshot
    _active_corridor_bus_count = len(active_veh_ids)

    # Clean up zone state for vehicles no longer on the network
    stale_keys = [k for k in _bus_zone_state if k[0] not in active_veh_ids]
    for k in stale_keys:
        del _bus_zone_state[k]

    # Add lifecycle events: first time seen in network and nearest-junction change
    if rows:
        for _r in list(rows):
            _vid = int(_r[1])
            _jid = int(_r[4])
            _bx = _r[2]
            _by = _r[3]
            _dist = _r[5]
            _inz = _r[6]
            _zr = _r[7]
            if _vid not in _bus_seen_ids:
                _bus_seen_ids.add(_vid)
                rows.append((
                    f"{time:.1f}", _vid, _bx, _by,
                    _jid, _dist, _inz, _zr, "enter_system",
                ))
            _prev_j = _bus_last_nearest_jct.get(_vid)
            if _prev_j is not None and _jid != _prev_j and _jid > 0:
                rows.append((
                    f"{time:.1f}", _vid, _bx, _by,
                    _jid, _dist, _inz, _zr, "nearest_jct_change",
                ))
            _bus_last_nearest_jct[_vid] = _jid

    if not rows:
        return
    try:
        write_header = not _bus_track_header_written
        with open(_BUS_TRACKING_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(["sim_time_s", "veh_id", "x", "y",
                            "nearest_jct", "dist_m", "in_zone", "zone_radius_m",
                            "event"])
                _bus_track_header_written = True
            w.writerows(rows)
    except Exception as _e:
        log_to_file(f"[BUS_TRACK] CSV write failed: {_e}")


def _write_queue_snapshot(time: float):
    """
    Write per-intersection queue-length snapshot every _QUEUE_SNAP_INTERVAL_S.

    Columns:
        sim_time_s    — simulation time (s)
        junction_id   — intersection ID
        buses_in_zone — distinct buses in detection zone whose PT line serves this junction
        queue_main    — queued vehicles (<5 km/h) on main (bus) approach sections
        queue_side    — queued vehicles (<5 km/h) on side-street sections
        queue_total   — queue_main + queue_side
        tsp_state     — current TSP state string ('IDLE' / 'GE' / 'INS' / 'NORMAL')
        current_phase — current Aimsun phase number at this junction
        delay_total_s — cumulative pax-seconds of total delay at this junction (running total)
        delay_bus_s   — cumulative pax-seconds of bus delay at this junction (running total)
        delay_car_s   — cumulative pax-seconds of car delay at this junction (running total)

    Written to: logs/queue_snapshot_<EXPERIMENT>_<timestamp>.csv
    """
    global _queue_snap_last_t, _queue_snap_header_written

    if time - _queue_snap_last_t < _QUEUE_SNAP_INTERVAL_S:
        return
    _queue_snap_last_t = time

    rows = []
    for iid, ctrl in controllers.items():
        try:
            # Count buses in detection zone, filtered to buses whose PT line serves this junction.
            # Raw zone presence includes ALL PT vehicles within radius — buses on parallel/cross
            # routes inflate the count.  Filter: include bus if its line's route contains iid.
            # Fallback for unknown routes: use _bus_observed_jcts (actual corridor route observed
            # during this simulation).  Only include if the bus has been observed near corridor
            # junctions — prevents cross-route buses from inflating the count.
            raw_zone = _tracking_zone_presence.get(iid, {})
            buses_in_zone = 0
            for _vid in raw_zone:
                _line_id = _bus_line_id.get(_vid, -1)
                _route_jcts = _pt_line_jct_route.get(_line_id) if _line_id > 0 else None
                if _route_jcts is not None:
                    if iid in _route_jcts:
                        buses_in_zone += 1
                else:
                    # Route unknown — fall back to observed junction sequence.
                    # Include only if this bus has been observed specifically entering
                    # THIS junction's zone (recorded in _bus_observed_jcts during the
                    # nearest-zone zone_enter pass).  This prevents cross-route buses
                    # from being counted just because they happen to be physically nearby.
                    _obs = _bus_observed_jcts.get(_vid)
                    if _obs and iid in _obs:
                        buses_in_zone += 1

            # Queue per section (vehicles moving < 5 km/h).
            # Prefer SimulationStats topology-derived main/side sections —
            # they include side-street sections that the controller doesn't
            # hold in incoming_sections (which covers only bus approaches).
            q_main = 0
            q_side = 0
            main_secs: set = set()
            side_secs: set = set()
            try:
                _inter_d = stats._inter.get(iid, {})
                main_secs = set(_inter_d.get('main_sections', []))
                side_secs = set(_inter_d.get('side_sections', []))
            except Exception:
                pass
            if not main_secs and not side_secs:
                # Fallback: controller's incoming sections (bus approach only)
                main_secs = set(getattr(ctrl, 'incoming_sections', []))
            all_secs = main_secs | side_secs

            for sec in all_secs:
                if not sec or sec <= 0:
                    continue
                try:
                    n = max(int(AKIVehStateGetNbVehiclesSection(sec, False)), 0)
                    for vi in range(n):
                        vinf = AKIVehStateGetVehicleInfSection(sec, vi)
                        spd = float(getattr(vinf, 'CurrentSpeed', 0.0) or 0.0)
                        if spd < 5.0:
                            if sec in main_secs:
                                q_main += 1
                            else:
                                q_side += 1
                except Exception:
                    continue

            # TSP state string
            tsp_state = "NORMAL"
            gb = getattr(ctrl, 'gb', None)
            if gb is not None:
                ts = getattr(gb, 'tsp_strategy', 0)
                tsp_state = {0: 'IDLE', 1: 'GE', 2: 'INS_COMPAT', 3: 'INS_FORCED'}.get(ts, 'IDLE')
            elif getattr(ctrl, 'flag', 0) != 0:
                tsp_state = 'ACTIVE'

            try:
                cur_phase = ECIGetCurrentPhase(getattr(ctrl, 'node_id', -1))
            except Exception:
                cur_phase = -1

            # Cumulative delay from stats (person-seconds, running total)
            delay_total_s = 0.0
            delay_bus_s   = 0.0
            delay_car_s   = 0.0
            try:
                _id = stats._inter.get(iid, {})
                delay_total_s = float(_id.get('delay_total', 0.0) or 0.0)
                delay_bus_s   = float(_id.get('delay_bus',   0.0) or 0.0)
                delay_car_s   = float(_id.get('delay_car',   0.0) or 0.0)
            except Exception:
                pass

            rows.append((
                f"{time:.1f}", iid, buses_in_zone,
                q_main, q_side, q_main + q_side,
                tsp_state, cur_phase, _active_corridor_bus_count,
                f"{delay_total_s:.1f}", f"{delay_bus_s:.1f}", f"{delay_car_s:.1f}",
            ))
        except Exception:
            continue

    if not rows:
        return
    try:
        write_header = not _queue_snap_header_written
        with open(_QUEUE_SNAPSHOT_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow([
                    "sim_time_s", "junction_id", "buses_in_zone",
                    "queue_main", "queue_side", "queue_total",
                    "tsp_state", "current_phase", "corridor_bus_count",
                    "delay_total_s", "delay_bus_s", "delay_car_s",
                ])
                _queue_snap_header_written = True
            w.writerows(rows)
    except Exception as _e:
        log_to_file(f"[QUEUE_SNAP] write failed: {_e}")


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


def _plot_schedule_recovery():
    """
    Generate a schedule-recovery chart from _ge_events.

    Each row in _ge_events is (sim_time, intersection_id, ge_s, recovery_s).
    The chart shows:
      • Blue bars  — GE granted (seconds stolen from the cycle)
      • Green bars — recovery trimmed from subsequent phases
      • Red bars   — residual (GE - recovery, i.e. unrecovered drift)

    Saved as logs/schedule_recovery_<timestamp>.png
    """
    if not _ge_events:
        log_to_file("[SCHED] No GE events recorded — skipping recovery plot")
        return

    out_path = os.path.join(LOG_DIR,
                            f"schedule_recovery_{_CURRENT_EXPERIMENT}_{timestamp}.png")

    times    = [e[0] for e in _ge_events]
    ge_vals  = [e[2] for e in _ge_events]
    rec_vals = [e[3] for e in _ge_events]
    res_vals = [max(0.0, g - r) for g, r in zip(ge_vals, rec_vals)]
    iids     = [e[1] for e in _ge_events]

    x = list(range(len(_ge_events)))
    labels = [f"t={t:.0f}s\njct{iid}" for t, iid in zip(times, iids)]

    fig, axes = plt.subplots(2, 1, figsize=(max(8, len(x) * 0.6 + 2), 8))

    # Top panel: per-event bar chart
    ax = axes[0]
    w = 0.28
    ax.bar([xi - w for xi in x], ge_vals,  width=w, color='#29b6f6', label='GE granted (s)')
    ax.bar([xi      for xi in x], rec_vals, width=w, color='#00e676', label='Recovered (s)')
    ax.bar([xi + w for xi in x], res_vals,  width=w, color='#ff5252', label='Residual drift (s)')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7, rotation=45, ha='right')
    ax.set_ylabel('seconds')
    ax.set_title(f'Schedule Recovery per GE Event — {_CURRENT_EXPERIMENT} ({CONTROL_MODE})')
    ax.legend(fontsize=8)
    ax.grid(axis='y', alpha=0.3)

    # Bottom panel: cumulative drift over time
    ax2 = axes[1]
    cum_drift = []
    running = 0.0
    for g, r in zip(ge_vals, rec_vals):
        running += max(0.0, g - r)
        cum_drift.append(running)
    ax2.plot(times, cum_drift, color='#ff5252', marker='o', markersize=4, linewidth=1.5,
             label='Cumulative unrecovered drift (s)')
    ax2.axhline(0, color='#00e676', linewidth=0.8, linestyle='--')
    ax2.set_xlabel('simulation time (s)')
    ax2.set_ylabel('cumulative seconds behind schedule')
    ax2.set_title('Cumulative Timing Drift Over Simulation')
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    log_to_file(f"[SCHED] Schedule recovery plot → {out_path} "
                f"({len(_ge_events)} GE events, "
                f"total_ge={sum(ge_vals):.1f}s "
                f"total_rec={sum(rec_vals):.1f}s "
                f"residual={sum(res_vals):.1f}s)")


def _write_run_summary():
    try:
        g = stats._global_kpis() if hasattr(stats, '_global_kpis') else {}
        with open(_RUN_SUMMARY_TXT, 'w', encoding='utf-8') as f:
            f.write('TSP RUN SUMMARY\n')
            f.write('=' * 80 + '\n')
            f.write(f'Timestamp: {datetime.datetime.now().isoformat()}\n')
            f.write(f'LOG_FILE: {LOG_FILE}\n')
            f.write(f'CONTROL_MODE: {CONTROL_MODE}\n')
            f.write(f'COORDINATED_TSP: {COORDINATED_TSP}\n')
            f.write(f'COORDINATION_ALGO: {COORDINATION_ALGO}\n')
            f.write(f'VERBose: {VERBOSE}\n')
            f.write('\n')
            f.write('[GLOBAL KPIS]\n')
            if g:
                for key, value in sorted(g.items()):
                    f.write(f'  {key}: {value}\n')
            else:
                f.write('  No global KPIs available\n')
            f.write('\n')
            f.write('[CONTROLLER STATUS]\n')
            for iid, ctrl in controllers.items():
                _gb = getattr(ctrl, 'gb', None)
                f.write(f'  Intersection {iid}: node_id={getattr(ctrl, "node_id", None)}')
                if _gb is not None:
                    f.write(
                        f' | bus_sg={getattr(_gb, "bus_sg", None)}'
                        f' | bus_request={getattr(_gb, "bus_request", None)}'
                        f' | external_control={getattr(_gb, "_external_control", None)}'
                        f' | bus_req_count={getattr(_gb, "_gb_bus_request_count", 0)}'
                        f' | activations={getattr(_gb, "_gb_bus_activation_count", 0)}'
                        f' | forced_terminations={getattr(_gb, "_gb_forced_termination_count", 0)}'
                        f' | phase_groups={len(getattr(_gb, "phase_groups", []))}'
                        f' | bus_phase={getattr(_gb, "_bus_aimsun_phase", None)}'
                    )
                f.write('\n')
            f.write('\n')
            f.write('[CORRIDOR SUMMARY]\n')
            if corridor_coordinators:
                for coord in corridor_coordinators:
                    f.write(f'  {coord.summary()}\n')
            else:
                f.write('  No corridor coordinators configured.\n')
    except Exception as e:
        log_to_file(f"[SUMMARY] run summary write failed: {e}", force=True)


def _write_algorithm_explanation_tex():
    tex = r'''
\documentclass{article}
\usepackage{amsmath}
\usepackage{geometry}
\geometry{margin=1in}
\begin{document}
\section*{Aimsun Group-Based TSP Algorithm}

This run uses the \textbf{GROUP\_BASED} signal-priority strategy.
The controller detects buses upstream of a junction, selects a compatible
signal group, and activates or extends service for that group.

\subsection*{Control Condition}
Group-based signal changes require the junction to be under \emph{External API}
control in Aimsun. The expected control type values are 2 or 3.
If the control type is not External, the controller skips any group-based
signal manipulation and preserves the model's normal signal plan.

\subsection*{Bus Detection}\label{sec:bus_detection}
A bus request is raised when a detected bus has estimated arrival time (ETA)
inside an actionable window:
\begin{equation}
\eta_{\min} \le \eta \le \eta_{\max}
\end{equation}

For URTSP-style detection, the grant is computed as:
\begin{equation}
g = \min\left(\max\left(\eta + 5, g_{\min}\right), g_{\max}\right)
\end{equation}
where $g_{\min}$ is the minimum green extension for the bus signal group and
$g_{\max}$ is the configured maximum extension.

\subsection*{Phase Restoration}
After a bus-priority phase completes, the intersection restores the previous
Aimsun phase using a direct phase jump. This avoids permanently altering the
normal signal plan.

\subsection*{Corridor Coordination}
If \texttt{COORDINATED\_TSP=True}, the controller may pre-arm downstream
junctions using a 1-D Kalman filter model or shockwave-based lead time.
The chosen coordination algorithm is:\\
\texttt{%s}

\section*{Practical Note}
If you see warnings about an uncontrolled or fixed junction (e.g., junction
19363), verify the model GUI setting:
\textbf{Properties $\to$ Signal Control $\to$ External API}. 

\end{document}
'''
    try:
        with open(_ALGORITHM_EXPLANATION_TEX, 'w', encoding='utf-8') as f:
            f.write(tex % COORDINATION_ALGO)
    except Exception as e:
        log_to_file(f"[SUMMARY] algorithm explanation write failed: {e}", force=True)


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
CONTROL_MODE = "REWARD_TSP"   # set control mode here
GROUP_BASED_BUS_PRIORITY = True

# =============================================================================
# CORRIDOR COORDINATION SETTINGS
#
# COORDINATED_TSP : True  → intersections in the same INTERSECTION_GROUPS key
#   coordinate their TSP signals.  Bus priority at junction[i] pre-arms
#   junction[i+1..i+3] so downstream greens are ready on arrival.
#   False → each junction runs independently (original behaviour).
#
# COORDINATION_ALGO : algorithm used when COORDINATED_TSP=True.
#
#   "KALMAN"    — 1-D Kalman filter (position + speed state vector).
#                 Robust to measurement noise, adapts to varying bus speeds.
#                 Best choice for free-flow / lightly congested corridors.
#
#   "SHOCKWAVE" — Kalman ETA plus a queue-clearance correction derived from
#                 shockwave theory (ShockwaveSpeed functions).  When the
#                 downstream intersection has a large queue the discharge wave
#                 propagation time is added to the bus travel ETA, giving a
#                 more accurate pre-arm moment under congested conditions.
#
#   "OBJECTIVE" — Adaptive lead time: instead of a fixed PRE_GREEN_LEAD_S the
#                 coordinator picks the lead time that maximises a combined
#                 person-level objective:
#                   J = COORD_OBJ_ALPHA * bus_delay_saved_persons
#                     - COORD_OBJ_BETA  * normal_throughput_displaced_persons
#                 This prevents the perverse incentive of pure delay
#                 minimisation (which can game the metric by serving fewer
#                 vehicles). Adjust ALPHA/BETA to reflect your priorities.
#
#   "ADAPTIVE"  — Hybrid strategy: starts from Kalman ETA, applies the
#                 shockwave queue-clearance correction under congestion, then
#                 adapts lead time using ETA uncertainty + downstream phase
#                 transition time so bus phases are armed early enough.
#
# COORD_OBJ_ALPHA / COORD_OBJ_BETA only apply when COORDINATION_ALGO="OBJECTIVE".
# =============================================================================
COORDINATED_TSP = False        # True to enable corridor-wide TSP coordination, False for independent intersection control
MAX_GE_EXTENSION_S = 20.0      # Hard ceiling on any green extension (seconds). If a bus requires more, the extension is skipped.

# ── REWARD_TSP mode weights ───────────────────────────────────────────────────
# R(action) = -α·ΔD_bus - β·ΔD_other - γ·ΔD_side
# Higher α → stronger bus priority; β,γ penalise disruption to other traffic.
# REWARD_TSP now scores actions in consistent passenger-delay units
# (passenger-seconds saved / incurred), so equal weights minimise total
# passenger delay directly.
REWARD_ALPHA = 1.0
REWARD_BETA  = 1.0
REWARD_GAMMA = 1.0
REWARD_GE_CANDIDATES = [5.0, 10.0, 15.0, 20.0]  # candidate GE durations (seconds)

COORDINATION_ALGO   = "KALMAN"   # "KALMAN" | "SHOCKWAVE" | "OBJECTIVE" | "ADAPTIVE"
COORD_OBJ_ALPHA     = 1.0        # weight on bus person-delay savings
COORD_OBJ_BETA      = 0.5        # weight on displaced normal-traffic throughput

# Full corridor route order, including unmanaged system intersections that can
# still delay buses between coordinated nodes.
CORRIDOR_ROUTE_GROUPS = {
    "logan_north": [17249, 17308, 17383, 17498, 17628, 17963, 18044, 18942],
    "logan_south": [19196, 19363, 19474, 19882, 21895],
}

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
_FOCUS_TIMEOUT_S  = 120.0   # auto-release if focus bus stalls
_focus_bus_id:     int   = -1
_focus_jct_id:     int   = -1
_focus_start_t:    float = -1.0
_focus_history:    list  = []  # [(start_t, end_t, veh_id, jct_id, outcome)]
# Junctions the focus bus has already been served at; these are unblocked so
# other buses can resume independent TSP behind the focus bus.
_focus_passed_jcts: set  = set()


def _acquire_focus(veh_id: int, jct_id: int, time: float):
    """Claim global focus for this bus. Returns True if acquired."""
    global _focus_bus_id, _focus_jct_id, _focus_start_t, _focus_passed_jcts
    # Same bus or no current focus → grant
    if _focus_bus_id <= 0 or _focus_bus_id == veh_id:
        prev = _focus_bus_id
        if _focus_bus_id == veh_id and _focus_jct_id >= 0 and _focus_jct_id != jct_id:
            # Focus bus advancing to a new junction — mark the old one as passed
            _focus_passed_jcts.add(_focus_jct_id)
        elif prev != veh_id:
            # New bus taking focus — reset passed set
            _focus_passed_jcts.clear()
        _focus_bus_id  = veh_id
        _focus_jct_id  = jct_id
        _focus_start_t = time
        if prev != veh_id:
            log_to_file(
                f"[BUS_FOCUS] t={time:.1f} ACQUIRE bus={veh_id} jct={jct_id}",
                force=True)
            _mark_detection_point(jct_id, veh_id, 0.0, 0.0, time, "focus_acquire")
        return True
    # Timeout — force release of stale focus
    if time - _focus_start_t > _FOCUS_TIMEOUT_S:
        _release_focus(time, "timeout")
        _focus_passed_jcts.clear()
        _focus_bus_id  = veh_id
        _focus_jct_id  = jct_id
        _focus_start_t = time
        log_to_file(
            f"[BUS_FOCUS] t={time:.1f} ACQUIRE (after timeout) bus={veh_id} jct={jct_id}",
            force=True)
        _mark_detection_point(jct_id, veh_id, 0.0, 0.0, time, "focus_acquire")
        return True
    # Different bus has focus — suppress
    return False


def _release_focus(time: float, outcome: str = "completed"):
    """Release global bus focus."""
    global _focus_bus_id, _focus_jct_id, _focus_start_t, _focus_passed_jcts
    if _focus_bus_id > 0:
        _focus_history.append((
            _focus_start_t, time, _focus_bus_id, _focus_jct_id, outcome))
        log_to_file(
            f"[BUS_FOCUS] t={time:.1f} RELEASE bus={_focus_bus_id} "
            f"jct={_focus_jct_id} outcome={outcome} "
            f"held={time - _focus_start_t:.1f}s",
            force=True)
    _focus_bus_id  = -1
    _focus_jct_id  = -1
    _focus_start_t = -1.0
    _focus_passed_jcts.clear()


def _is_focus_blocked(veh_id: int, jct_id: int, time: float) -> bool:
    """Return True if this bus should be suppressed due to focus priority.

    Only blocks junctions the focus bus has not yet passed through.
    Once the focus bus clears a junction, other buses are free to use it.
    """
    if _focus_bus_id <= 0:
        return False
    if _focus_bus_id == veh_id:
        return False  # same bus is always allowed
    if time - _focus_start_t > _FOCUS_TIMEOUT_S:
        _release_focus(time, "timeout")
        return False  # timed out and released
    # Allow intersections the focus bus has already been served at
    if jct_id in _focus_passed_jcts:
        return False
    return True


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
    """
    Harmony search optimization with INTEGER values only.
    All candidate solutions are rounded to integer seconds.
    """
    # Convert bounds to integers
    lb_int = int(math.ceil(lower_bound))
    ub_int = int(math.floor(upper_bound))
    if lb_int > ub_int:
        return lb_int  # Edge case: return lower bound
    
    # Initialize harmony memory with integer values
    harmony_memory = [random.randint(lb_int, ub_int)
                      for _ in range(harmony_memory_size)]
    fitness_values = [objective_function(h, time) for h in harmony_memory]

    for _ in range(max_iterations):
        if random.uniform(0, 1) < hmcr:
            new_harmony = random.choice(harmony_memory)
            if random.uniform(0, 1) < par:
                # Pitch adjustment: add integer offset
                new_harmony += random.randint(-int(bandwidth), int(bandwidth))
        else:
            new_harmony = random.randint(lb_int, ub_int)

        # Clamp to integer bounds
        new_harmony = max(lb_int, min(ub_int, new_harmony))
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


def _build_pt_line_corridor_routes():
    """
    Build route-aware maps so coordination only targets junctions a bus will
    actually visit, using its filed PT plan from the Aimsun model.

    Populates four module-level dicts:
      _corridor_jct_incoming  {jct_id: set(section_ids)}  ← approach sections per junction
      _sec_to_corridor_jct    {section_id: [jct_id, ...]} ← reverse map
      _pt_line_section_set    {line_id: set(section_ids)}  ← every section on that PT line
      _pt_line_jct_route      {line_id: [jct_id, ...]}    ← ordered corridor junctions the
                                                              line passes through

    Called once from AAPISimulationReady after corridor positions are set.
    """
    global _corridor_jct_incoming, _sec_to_corridor_jct, _pt_line_section_set, _pt_line_jct_route

    # ── Step 1: build junction → incoming-section map from live controllers ───
    jct_incoming: dict = {}
    for jct_id, ctrl in controllers.items():
        secs = set()
        # primary approach sections (main corridor + topology fallback)
        for s in getattr(ctrl, 'incoming_sections', []):
            if isinstance(s, int) and s > 0:
                secs.add(s)
        # also include side sections so a bus using a side approach is caught
        for s in getattr(ctrl, 'side_sections', []):
            if isinstance(s, int) and s > 0:
                secs.add(s)
        if secs:
            jct_incoming[jct_id] = secs

    _corridor_jct_incoming = jct_incoming

    # ── Step 2: reverse map — section → which corridor junctions it feeds ─────
    sec_to_jct: dict = {}
    for jct_id, secs in jct_incoming.items():
        for sec_id in secs:
            sec_to_jct.setdefault(sec_id, []).append(jct_id)

    _sec_to_corridor_jct = sec_to_jct

    # ── Step 3: iterate every PT line, build section set + ordered jct list ───
    line_section_set: dict = {}
    line_jct_route: dict = {}

    try:
        n_lines = int(AKIPTGetNumberLines())
    except Exception:
        n_lines = 0

    for li in range(n_lines):
        try:
            line_id = AKIPTGetIdLine(li)
        except Exception:
            continue
        if line_id <= 0:
            continue

        try:
            n_secs = int(AKIPTGetNumberSectionsInLine(line_id))
        except Exception:
            n_secs = 0

        secs_on_line: list = []
        for si in range(n_secs):
            try:
                sec_id = int(AKIPTGetIdSectionInLine(line_id, si))
                if sec_id > 0:
                    secs_on_line.append(sec_id)
            except Exception:
                continue

        line_section_set[line_id] = set(secs_on_line)

        # Walk sections in route order; record the first time each corridor
        # junction is encountered (avoids double-counting loops)
        seen_jcts: set = set()
        ordered_jcts: list = []
        for sec_id in secs_on_line:
            for jct_id in sec_to_jct.get(sec_id, []):
                if jct_id not in seen_jcts:
                    seen_jcts.add(jct_id)
                    ordered_jcts.append(jct_id)

        if ordered_jcts:
            line_jct_route[line_id] = ordered_jcts

    _pt_line_section_set = line_section_set
    _pt_line_jct_route   = line_jct_route

    total_lines  = len(line_jct_route)
    total_routes = sum(len(v) for v in line_jct_route.values())
    log_to_file(
        f"[PT-ROUTE] Built corridor route map: {total_lines} PT lines cross "
        f"corridor junctions | {total_routes} (line,jct) pairs | "
        f"corridor junctions covered: "
        + str(sorted(jct_incoming.keys()))
    )


def _log_startup_bus_demand_snapshot(label: str = "init"):
    """
    Log a single startup snapshot of PT-line bus demand visibility.

    Includes:
      - PT line count
      - total PT-line vehicle entries
      - unique PT vehicle ids
      - unique vehicles matching inferred bus type
    """
    try:
        _n_lines = int(AKIPTGetNumberLines())
    except Exception:
        _n_lines = 0

    _all_ids = set()
    _bus_ids = set()
    _entries = 0

    _bus_type = int(getattr(stats, '_bus_pos', -1) or -1)
    if _bus_type <= 0:
        try:
            _bus_type = int(_infer_bus_type_pos_from_pt() or -1)
        except Exception:
            _bus_type = -1

    for _li in range(_n_lines):
        try:
            _line_id = AKIPTGetIdLine(_li)
            _n = int(AKIGetNbVehiclesFollowingPTLine(_line_id))
        except Exception:
            continue
        _entries += max(_n, 0)
        for _vi in range(max(_n, 0)):
            try:
                _vid = int(AKIGetVehicleFollowingPTLine(_line_id, _vi))
                if _vid <= 0:
                    continue
                _all_ids.add(_vid)
                _inf = AKIPTVehGetInf(_vid)
                _typ = int(getattr(_inf, 'type', -1) or -1)
                if _bus_type > 0 and _typ == _bus_type:
                    _bus_ids.add(_vid)
            except Exception:
                continue

    log_to_file(
        f"[DEMAND] startup snapshot ({label}) | pt_lines={_n_lines} "
        f"pt_entries={_entries} unique_pt_veh={len(_all_ids)} "
        f"bus_type_pos={_bus_type} unique_bus_veh={len(_bus_ids)}",
        force=True,
    )


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
        self.max_extension    = min(float(gb_config.get("max_extension", 15.0)), MAX_GE_EXTENSION_S)

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
        self._group_served          = set()   # indices into phase_groups served this cycle
        self._current_group_idx     = None    # index of currently active phase group
        self._interrupted_group_idx = None    # group cut short by forced TSP insertion
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

        self._gb_bad_ctrl_warned = False
        self._external_control = None
        self._gb_bus_request_count = 0
        self._gb_bus_activation_count = 0
        self._gb_forced_termination_count = 0

        # Bus priority
        self.bus_request       = None         # SG position waiting for service
        self.extension_used    = 0.0          # cumulative extension granted
        self.prev_bus_presence = {det: 0 for det in self.bus_det}
        # Junction-level TSP cooldown: after ANY bus phase is served, suppress all
        # new bus requests for this many seconds so normal round-robin can serve
        # remaining phase groups before another bus hijacks the cycle.
        # Default 25 s: short enough that a bus arriving ~30-60 s after the last
        # TSP event is still detected; long enough to prevent back-to-back grants
        # on the same bus that crosses multiple detection tiers rapidly.
        # Override per-intersection via 'tsp_cycle_cooldown' in GroupBasedConfig.
        self._tsp_cycle_cooldown  = float(gb_config.get("tsp_cycle_cooldown", 25.0))
        self._tsp_cooldown_until  = -1.0      # sim time before which bus requests are blocked

        # Minimum lead time (s) the CorridorCoordinator must observe when firing a
        # pre-arm at this junction.  Equal to the longest remaining phase duration
        # the junction could be executing when the pre-arm arrives, plus the
        # intergreen time.  Computed from config; updated dynamically in step().
        # This ensures pre-arm fires early enough for the junction to cycle into
        # its bus phase BEFORE the bus physically arrives.
        _gpd = gb_config.get("GreenPhaseDuration", [])
        _max_phase = max(_gpd) if _gpd else 30.0
        _intergreen = 5.0   # conservative intergreen estimate
        self._min_lead_for_phase_change_s = float(_max_phase + _intergreen)

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
        self._detection_zone_m = float(gb_config.get("detection_zone_m", 150.0))
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

        # Exit-detector-based phase restoration: when the active bus passes one
        # of these detectors the bus priority phase is ended early so normal
        # round-robin can resume immediately rather than waiting for max_green.
        self.bus_exit_det        = list(gb_config.get("bus_exit_det", []))
        self._bus_exit_det_geom  = {}   # {det_id: (section_id, ini_pos, fin_pos)}
        self._active_bus_veh_id  = None # veh_id of the bus currently being served
        # Natural-green logging guard: avoid counting the same bus multiple times
        # while it remains in the detection zone and naturally clears the junction.
        self._natural_green_logged_ids: set = set()
        # ETA-skip logging guard: log once per vehicle when it is in zone but ETA
        # is outside the actionable window (detected but not granted).
        self._det_skip_eta_logged_ids: set = set()
        if self.bus_exit_det:
            self._build_exit_det_geometry()

        # Starvation tracking (incremented per step when SG has demand but is red)
        self.wait_time = {sg: 0.0 for sg in self.all_sg}

        # ── TSP-overlay fields (phase-based, mirrors HARMONY approach) ─────────
        # GROUP_BASED no longer overrides ALL signals every step.  Instead it lets
        # the normal Aimsun signal plan run and only jumps to the bus-compatible
        # phase via ECIChangeDirectPhase during TSP events, then restores afterward.
        self._bus_aimsun_phase  = None   # Aimsun phase number whose SGs include bus_sg
        self._prev_aimsun_phase = None   # phase active before TSP intervention
        self._tsp_active        = False  # currently holding bus priority phase
        self._tsp_grant_until   = -1.0   # sim-time when the current TSP grant expires

        # Corridor coordinator back-reference — set by CorridorCoordinator.__init__
        # after all controllers are created.  None when not part of a corridor group
        # or when COORDINATED_TSP=False.
        self._corridor_coord = None
        # Set True by CorridorCoordinator when it fires a pre-green request here.
        # Cleared once the coordinated phase is activated (_activate_for_bus).
        # While True, the junction is exempt from the corridor wave ban.
        self._coord_sourced_request: bool = False

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
    # EXIT DETECTOR SUPPORT
    # =========================================================================

    def _build_exit_det_geometry(self):
        """Resolve section/position geometry for bus exit detectors."""
        for det_id in self.bus_exit_det:
            try:
                props = AKIDetGetPropertiesDetectorById(det_id)
                if props.report >= 0:
                    self._bus_exit_det_geom[det_id] = (
                        props.IdSection, props.InitialPosition, props.FinalPosition)
            except Exception:
                pass

    def _check_bus_exit_cleared(self) -> bool:
        """
        Return True if the active priority bus has passed an exit detector.
        Scans all PT-line vehicles for self._active_bus_veh_id; if that vehicle
        is at or past the exit detector section/position the bus has cleared.
        If the vehicle is no longer in the network it is also treated as cleared.
        """
        if not self._bus_exit_det_geom or self._active_bus_veh_id is None:
            return False
        try:
            n_lines = AKIPTGetNumberLines()
            bus_found = False
            for li in range(n_lines):
                n_vehs = AKIPTGetNumberVehiclesInLineSection(li, -1, self.bus_type_pos)
                for vi in range(n_vehs):
                    inf = AKIPTGetInfVehicleInLineSection(li, -1, vi, self.bus_type_pos)
                    if not hasattr(inf, 'idVehicle') or inf.report < 0:
                        continue
                    if inf.idVehicle != self._active_bus_veh_id:
                        continue
                    bus_found = True
                    for _, (sec_id, ini_pos, _fin_pos) in self._bus_exit_det_geom.items():
                        if inf.idSection == sec_id and inf.CurrentPos >= ini_pos:
                            return True  # bus is at/past exit detector
            # Bus not found in any PT line — it has left the network
            return not bus_found
        except Exception:
            return False

    # =========================================================================
    # TSP PHASE ACTIVATION / RESTORATION  (phase-based overlay, like HARMONY)
    # =========================================================================

    def _activate_bus_phase(self, time: float, timeSta: float, acycle: float = 0.0):
        self._gb_bus_activation_count += 1
        """
        Activate bus priority by jumping to the Aimsun phase that carries bus_sg.

        Uses ECIChangeDirectPhase (same as HARMONY) so the normal signal plan
        stays intact and only the timing/sequence is overridden for the TSP event.
        After the grant expires the plan is restored via _restore_aimsun_plan().
        """
        if not self.bus_request or self._bus_aimsun_phase is None:
            self.bus_request = None
            return

        if not self._is_external_control():
            self.bus_request = None
            return

        # Save the phase currently running so we can restore it afterward
        try:
            self._prev_aimsun_phase = ECIGetCurrentPhase(self.junction_id)
        except Exception:
            self._prev_aimsun_phase = None

        # Compute how long to hold the bus phase
        if self.tsp_mode == "harmony":
            try:
                grant = self._compute_harmony_extension(time, self.bus_sg,
                                                        self._compute_queue())
            except Exception:
                grant = self.max_extension
        else:
            # URTSP / basic: use ETA-aware grant capped at max_extension
            if self._bus_eta is not None and self._bus_det_time is not None:
                age       = time - self._bus_det_time
                eta_now   = max(0.0, self._bus_eta - age)
                CLEAR_BUF = 5.0
                grant     = min(eta_now + CLEAR_BUF, self.max_extension)
            else:
                grant = self.max_extension

        grant = max(grant, self.min_green.get(self.bus_sg, 6.0))

        try:
            ECIChangeDirectPhase(
                self.junction_id, self._bus_aimsun_phase,
                timeSta, time, acycle, 0)
            ECIChangeTimingPhase(
                self.junction_id, self._bus_aimsun_phase,
                round(grant, 1), timeSta)
        except Exception as _e:
            log_to_file(
                f"[GB] jct={self.junction_id} ECIChangeDirectPhase failed: {_e}"
            )

        self._tsp_active        = True
        self._tsp_grant_until   = time + grant
        self.tsp_strategy       = 1   # green extension / phase jump
        self._tsp_cooldown_until = time + self._tsp_cycle_cooldown
        self.extension_used     = grant

        # ── Acquire global bus focus ──────────────────────────────────────
        _vid = self._active_bus_veh_id or -1
        if _vid > 0:
            _acquire_focus(_vid, self.junction_id, time)

        if LOG_GB_BUS:
            _vprint(
                f"[GB] t={time:.1f} jct={self.junction_id} "
                f"TSP ACTIVATE phase={self._bus_aimsun_phase} "
                f"bus_sg={self.bus_sg} grant={grant:.1f}s "
                f"prev_phase={self._prev_aimsun_phase}"
            )
        if self._stats:
            self._stats.record_tsp_event(self.junction_id, 'extension')
            self._stats.record_tsp_extension_duration(self.junction_id, grant)

        # Notify corridor coordinator
        if self._corridor_coord is not None and COORDINATED_TSP:
            try:
                _vid = self._active_bus_veh_id or -1
                self._corridor_coord.notify_bus_granted(
                    _vid, self.junction_id, time, self.bus_sg)
            except Exception:
                pass

        self.bus_request        = None
        self._coord_sourced_request = False

    def _restore_aimsun_plan(self, time: float, timeSta: float, acycle: float = 0.0):
        """
        Restore the intersection back to its normal Aimsun signal plan after TSP.

        Jumps back to the phase that was running before TSP intervention using
        ECIChangeDirectPhase, then resets all TSP state.
        """
        if self._prev_aimsun_phase and self._prev_aimsun_phase > 0:
            if self._is_external_control():
                try:
                    ECIChangeDirectPhase(
                        self.junction_id, self._prev_aimsun_phase,
                        timeSta, time, acycle, 0)
                except Exception as _e:
                    log_to_file(
                        f"[GB] jct={self.junction_id} restore ECIChangeDirectPhase failed: {_e}"
                    )
            else:
                log_to_file(
                    f"[GB] jct={self.junction_id} restore skipped: junction not under external control"
                )

        if LOG_GB_BUS:
            _vprint(
                f"[GB] t={time:.1f} jct={self.junction_id} "
                f"TSP RESTORE → phase={self._prev_aimsun_phase} "
                f"(was bus phase={self._bus_aimsun_phase})"
            )

        self._tsp_active        = False
        self._tsp_grant_until   = -1.0
        self.tsp_strategy       = 0
        self._active_bus_veh_id = None
        self._interrupted_group_idx = None
        self.extension_used     = 0.0
        self._prev_aimsun_phase = None

        # ── Release global bus focus ──────────────────────────────────────
        _release_focus(time, "gb_completed")

    # =========================================================================
    # MAIN STEP
    # =========================================================================

    def step(self, time: float, timeSta: float, acycle: float = 0.0):
        """
        Called every simulation step from IntersectionController.update().

        TSP-overlay mode: the normal Aimsun signal plan runs untouched.  Only
        when a bus is detected do we jump to the bus-compatible phase via
        ECIChangeDirectPhase (identical to HARMONY), hold it for the computed
        grant duration, then restore the previous phase.  All other steps are
        detection-only — no signal manipulation.
        """
        # ── Always run bus detection ──────────────────────────────────────────
        if self.tsp_mode == "urtsp":
            self._detect_bus_urtsp(time)
        else:
            self._detect_bus(time)

        self._update_wait_times(self._compute_queue())

        # ── If TSP currently active: check whether to restore ─────────────────
        if self._tsp_active:
            bus_cleared = (
                (self.bus_exit_det and self._check_bus_exit_cleared())
                or time >= self._tsp_grant_until
            )
            if bus_cleared:
                _bc_reason = ("exit-det" if self.bus_exit_det
                              and self._check_bus_exit_cleared() else "timeout")
                if LOG_GB_BUS:
                    _vprint(
                        f"[GB] t={time:.1f} jct={self.junction_id} "
                        f"TSP ended ({_bc_reason}) — restoring plan"
                    )
                # Bus-on-red diagnostic: grant expired by timeout but the bus that
                # triggered the grant is still tracked inside the zone, meaning it
                # has not yet passed the stop-line and will likely arrive at red.
                if _bc_reason == "timeout" and self._active_bus_veh_id is not None:
                    _still_in_zone = self._active_bus_veh_id in _tracking_zone_presence.get(
                        self.junction_id, {})
                    if _still_in_zone:
                        log_to_file(
                            f"[BUS_ON_RED] t={time:.1f} jct={self.junction_id} "
                            f"v={self._active_bus_veh_id} grant expired (timeout) "
                            f"but vehicle still in detection zone — likely arriving at red",
                            force=True
                        )
                self._restore_aimsun_plan(time, timeSta, acycle)
            return

        # ── No TSP active: activate if bus request pending ────────────────────
        if self.bus_request:
            # Coordinator-sourced requests (pre-arm from CorridorCoordinator) always
            # bypass the per-junction TSP cooldown.  Rationale: the coordinator's
            # Kalman tracker has already validated that this bus should get priority
            # at this junction as part of a corridor green wave.  Applying a cooldown
            # here would silently discard that carefully-timed request, breaking the
            # chain.  Independent detections still respect the cooldown.
            _bypass_cooldown = getattr(self, '_coord_sourced_request', False)
            _cooldown_clear  = (time >= self._tsp_cooldown_until)

            if _bypass_cooldown or _cooldown_clear:
                if self._bus_aimsun_phase is not None:
                    self._activate_bus_phase(time, timeSta, acycle)
                else:
                    # No phase mapping yet — consume request cleanly
                    self.bus_request = None
                    if getattr(self, '_coord_sourced_request', False):
                        if LOG_CORRIDOR:
                            _vprint(f"[GB COORD] jct={self.junction_id} "
                                    f"coord-prearm discarded: no bus_aimsun_phase")
                        if self._corridor_coord is not None:
                            self._corridor_coord._record_prearm_discarded(
                                self.junction_id)
            else:
                # Independent detection inside cooldown window — discard
                self.bus_request = None

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

        # Per-intersection detection trace: independent of LOG_GB_BUS; lists every
        # vehicle checked so you can see why a detection did or did not fire.
        _log_det = self.junction_id in LOG_DETECTION_INTERSECTIONS

        # Forced 10-minute heartbeat so we can see _detect_bus is running and
        # what state it sees.  Always printed — helps diagnose "no CSV" issues.
        _det_hb_key = '_det_hb_t'
        _det_hb_interval = 600.0
        if time - getattr(self, _det_hb_key, -_det_hb_interval) >= _det_hb_interval:
            setattr(self, _det_hb_key, time)
            try:
                _n_pt_lines = AKIPTGetNumberLines()
            except Exception:
                _n_pt_lines = -1
            log_to_file(
                f"[DET HB] t={time:.0f} jct={self.junction_id} "
                f"bus_sg={self.bus_sg} bus_request={self.bus_request} "
                f"bus_type_pos={self.bus_type_pos} "
                f"bus_det={self.bus_det} "
                f"incoming_secs={self.incoming_sections} "
                f"n_pt_lines={_n_pt_lines} "
                f"junc_xy_cache={getattr(self,'_junction_xy_cache',None)} "
                f"detection_zone_m={self._detection_zone_m:.0f} "
                f"eta_min={self._eta_min_s:.0f}s "
                f"mark_total={_mark_calls_total}",
                force=True
            )

        junc_xy = self._get_junction_xy()
        # Cache on self so _detect_bus_urtsp and coordinator can use it too
        if junc_xy is not None and not getattr(self, '_junction_xy_cache', None):
            self._junction_xy_cache = junc_xy
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

        def _request_bus(veh_id, source, eta, dist_m, approach, xy=None):
            """
            xy : (float, float) | None  — exact bus coordinates at detection.
                 T1 passes (inf.xCurrentPos, inf.yCurrentPos).
                 T2/T3 pass None; junction XY (jx, jy) is used as fallback.

            Returns True when the bus is within the actionable ETA window
            (whether or not a new request was raised), so the caller can stop
            scanning further tiers.  Returns False when ETA is outside the
            window — the bus is not yet actionable and other tiers should
            continue scanning.
            """
            # ── Corridor wave suppression ─────────────────────────────────────
            # When a coordination wave is active this junction is banned from
            # raising independent bus requests.  Requests sourced by the
            # coordinator (_coord_sourced_request already set on self) are exempt
            # — they will be processed in IDLE via _activate_for_bus, not here.
            if (self._corridor_coord is not None
                    and COORDINATED_TSP
                    and self._corridor_coord.is_wave_banned(self.junction_id)):
                if _log_det or LOG_CORRIDOR:
                    _vprint(
                        f"[CORRIDOR WAVE] t={time:.1f} jct={self.junction_id} "
                        f"v={veh_id} — SUPPRESSED (wave active for bus="
                        f"{self._corridor_coord._wave_veh_id})"
                    )
                return False  # suppressed — keep scanning other buses
            # ── ETA gates — return False for out-of-window buses ─────────────
            # Returning False means "this bus is not actionable; keep scanning
            # other tiers in case a closer/faster bus qualifies".
            if eta < self._eta_min_s:
                if LOG_GB_BUS or _log_det:
                    _vprint(
                        f"[DET] t={time:.1f} jct={self.junction_id} "
                        f"v={veh_id} [{approach}] dist={dist_m:.0f}m "
                        f"ETA={eta:.1f}s < min={self._eta_min_s:.0f}s — too close"
                    )
                return False  # already past — keep scanning
            if eta > eta_max:
                if veh_id not in self._det_skip_eta_logged_ids:
                    self._det_skip_eta_logged_ids.add(veh_id)
                    log_to_file(
                        f"[DET SKIP ETA] t={time:.1f} jct={self.junction_id} "
                        f"v={veh_id} [{source}|{approach}] dist={dist_m:.0f}m "
                        f"ETA={eta:.1f}s > max={eta_max:.0f}s "
                        f"window=[{self._eta_min_s:.0f},{eta_max:.0f}]s — in zone but outside window",
                        force=True
                    )
                elif LOG_GB_BUS or _log_det:
                    _vprint(
                        f"[DET] t={time:.1f} jct={self.junction_id} "
                        f"v={veh_id} [{approach}] dist={dist_m:.0f}m "
                        f"ETA={eta:.1f}s > max={eta_max:.0f}s — too far (deferred)"
                    )
                return False  # too far — keep scanning for a closer bus
            # ── Bus is inside the detection zone — mark it (first time only) ──
            # Always write the CSV row; fall back to (0,0) if XY is unavailable
            # so the counter increments and the file is created regardless.
            _mx = (xy[0] if xy is not None else jx) if (xy is not None or jx is not None) else 0.0
            _my = (xy[1] if xy is not None else jy) if (xy is not None or jy is not None) else 0.0
            _mark_detection_point(self.junction_id, veh_id, _mx, _my, time, source)
            # ── Bus is within ETA window; handle it ───────────────────────────
            # Everything below returns True — the bus is actionable; Tier 2/3
            # scanning can stop because we have a bus in the right window.
            if not self.bus_sg or self.bus_request is not None:
                if _log_det:
                    _vprint(
                        f"[DET] t={time:.1f} jct={self.junction_id} "
                        f"v={veh_id} [{source}|{approach}] dist={dist_m:.0f}m "
                        f"ETA={eta:.1f}s — SKIPPED (bus_sg={self.bus_sg} "
                        f"req_active={self.bus_request is not None})"
                    )
                return True  # bus in window, request already active
            # Natural-green case: bus phase is already active and the bus ETA is
            # within the current phase remaining time, so no intervention is needed.
            if self._bus_aimsun_phase is not None:
                try:
                    _cur_ph = ECIGetCurrentPhase(self.junction_id)
                    _ph_start = float(ECIGetStartingTimePhase(self.junction_id))
                    _ph_dur = float(GetPhaseDuration(self.junction_id, _cur_ph, 0.0))
                    _ph_rem = max(0.0, _ph_dur - max(0.0, time - _ph_start))
                    if _cur_ph == self._bus_aimsun_phase and eta <= _ph_rem:
                        if veh_id not in self._natural_green_logged_ids:
                            self._natural_green_logged_ids.add(veh_id)
                            if self._stats:
                                self._stats.record_tsp_event(self.junction_id, 'detection')
                                self._stats.record_tsp_skip(self.junction_id, 'natural_green')
                        if LOG_GB_BUS or _log_det:
                            _vprint(
                                f"[DET] t={time:.1f} jct={self.junction_id} "
                                f"v={veh_id} [{source}|{approach}] ETA={eta:.1f}s "
                                f"<= phase_remaining={_ph_rem:.1f}s — natural green"
                            )
                        return True  # bus in window, natural green
                except Exception:
                    pass
            if time < self._tsp_cooldown_until:
                if _log_det:
                    _vprint(
                        f"[DET] t={time:.1f} jct={self.junction_id} "
                        f"v={veh_id} [{source}|{approach}] dist={dist_m:.0f}m "
                        f"ETA={eta:.1f}s — COOLDOWN until={self._tsp_cooldown_until:.1f}s"
                    )
                return True  # bus in window, in cooldown
            # Compute a best-effort ETA uncertainty (sigma) for scoring.
            # Use the Kalman tracker when available; otherwise approximate as
            # 30 % of the ETA (uncertainty scales with look-ahead distance).
            _jct_pos_for_sigma = (
                self._corridor_coord.corridor_pos.get(self.junction_id)
                if self._corridor_coord is not None else None
            )
            _tracker_for_sigma = (
                self._corridor_coord._trackers.get(veh_id)
                if (self._corridor_coord is not None and veh_id > 0) else None
            )
            if _tracker_for_sigma is not None and _jct_pos_for_sigma is not None:
                _sigma = _tracker_for_sigma.uncertainty_s(_jct_pos_for_sigma)
            else:
                _sigma = max(eta * 0.3, 1.0)
            _score = (eta_max - eta) / max(_sigma, 1.0)
            _candidates.append((_score, veh_id, eta, dist_m, source, approach, xy))
            if LOG_GB_BUS or _log_det:
                _vprint(
                    f"[DET] t={time:.1f} jct={self.junction_id} "
                    f"CANDIDATE [{source}|{approach}] v={veh_id} "
                    f"dist={dist_m:.0f}m ETA={eta:.1f}s sigma={_sigma:.1f}s "
                    f"score={_score:.2f} window=[{self._eta_min_s:.0f},{eta_max:.0f}]s"
                )
            return True  # bus in window, queued as candidate

        # ── Tier 0: position-tracker zone-presence supplement ────────────────
        # Buses on transit-link sections (report<0) are invisible to the
        # per-step PT API scan.  _track_all_bus_positions confirms them inside
        # the zone every 5 s; inject those detections here before Tier 1 so
        # the GB controller raises a bus_request for them.
        _candidates: list = []   # (score, veh_id, eta, dist_m, source, approach, xy)
        seen = set()
        for _tz_vid, (_tz_bx, _tz_by, _tz_spd) in list(
                _tracking_zone_presence.get(self.junction_id, {}).items()):
            if _tz_vid not in seen:
                seen.add(_tz_vid)
                _tz_dist = (math.sqrt((_tz_bx - jx) ** 2 + (_tz_by - jy) ** 2)
                            if jx is not None else float(self._detection_zone_m))
                _tz_eta = _tz_dist / max(_tz_spd / 3.6, 1.0)
                _request_bus(_tz_vid, "track-zone", _tz_eta, _tz_dist,
                              "front", xy=(_tz_bx, _tz_by))

        # ── Tier 1: PT line vehicle coordinate scan ───────────────────────────
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
                            if _log_det:
                                _vprint(
                                    f"[DET T1] t={time:.1f} jct={self.junction_id} "
                                    f"v={veh_id} type={inf.type} "
                                    f"dist={dist:.0f}m > zone={detection_zone_m:.0f}m — out of range"
                                )
                            continue
                        try:
                            spd_kmh = float(inf.CurrentSpeed)
                        except Exception:
                            spd_kmh = 40.0
                        eta      = _eta_from_dist(dist, spd_kmh)
                        approach = _approach_label(getattr(inf, 'idSection', -1))
                        if _log_det:
                            _vprint(
                                f"[DET T1] t={time:.1f} jct={self.junction_id} "
                                f"v={veh_id} type={inf.type} bus_pos={self.bus_type_pos} "
                                f"dist={dist:.0f}m spd={spd_kmh:.0f}km/h "
                                f"ETA={eta:.1f}s [{approach}] sec={getattr(inf,'idSection',-1)}"
                            )
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

                    _bus_xy = (float(inf.xCurrentPos), float(inf.yCurrentPos)) if jx is not None else None
                    _request_bus(veh_id, "PT-coord", eta, dist, approach, xy=_bus_xy)
                except Exception:
                    continue

        # ── Tier 2: section scan for bus-type vehicles ────────────────────────
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
                    # T2 has no per-vehicle XY; junction centroid is best fallback
                    _request_bus(inf.idVeh, f"sec={sec_id}", eta, dist, approach,
                                 xy=(jx, jy) if jx is not None else None)
            except Exception:
                continue

        # ── Tier 3: rising-edge detector presence ─────────────────────────────
        # Detectors are at a known distance from the stop line — use DetDistance
        # (if configured) to compute a distance-based ETA.
        for det in self.bus_det:
            try:
                current = AKIDetGetPresenceCyclebyId(det, 1)
                rising  = current == 1 and self.prev_bus_presence.get(det, 0) == 0
                if _log_det:
                    _vprint(
                        f"[DET T3] t={time:.1f} jct={self.junction_id} "
                        f"det={det} presence={current} prev={self.prev_bus_presence.get(det,0)} "
                        f"rising={rising}"
                    )
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
                # T3 has no vehicle XY; junction centroid is best fallback
                _request_bus(-det, f"det={det}", eta, dist, approach,
                             xy=(jx, jy) if jx is not None else None)
            except Exception:
                pass

        # ── Commit best candidate across all tiers ────────────────────────────
        # Pick the bus with the highest (eta_max - eta) / max(sigma, 1) score:
        # favours buses that are close to the actionable window edge and whose
        # arrival time is most certain.  BusOcc is constant so this is
        # equivalent to minimising total passenger delay.
        if _candidates and self.bus_sg and self.bus_request is None:
            _candidates.sort(key=lambda _c: -_c[0])
            _best_score, _best_vid, _best_eta, _best_dist, _best_src, _best_app, _best_xy = _candidates[0]
            self.bus_request        = self.bus_sg
            self._gb_bus_request_count += 1
            self._bus_eta           = _best_eta
            self._bus_det_time      = time
            self._active_bus_veh_id = _best_vid
            if LOG_GB_BUS or _log_det:
                _vprint(
                    f"[DET] t={time:.1f} jct={self.junction_id} "
                    f"BEST [{_best_src}|{_best_app}] v={_best_vid} "
                    f"dist={_best_dist:.0f}m ETA={_best_eta:.1f}s "
                    f"score={_best_score:.2f} ({len(_candidates)} candidate(s)) "
                    f"→ requesting SG {self.bus_sg}"
                )
            if self._stats:
                self._stats.record_tsp_event(self.junction_id, 'detection')
                try:
                    self._stats.record_pt_bus_detection(self.junction_id, _best_vid, time)
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

        # Per-intersection verbose trace (independent of LOG_GB_BUS)
        _log_det = self.junction_id in LOG_DETECTION_INTERSECTIONS

        # Populate junction XY cache if not already set (used by mark_detection_point)
        if not getattr(self, '_junction_xy_cache', None):
            _jxy = self._get_junction_xy()
            if _jxy:
                self._junction_xy_cache = _jxy

        # 10-minute heartbeat — shows _detect_bus_urtsp IS running even when
        # VERBOSE=False.  Helps diagnose "no CSV" issues.
        _hb_key = '_urtsp_hb_t'
        if time - getattr(self, _hb_key, -601.0) >= 600.0:
            setattr(self, _hb_key, time)
            _jxy_c = getattr(self, '_junction_xy_cache', None)
            try:
                _n_pt = AKIPTGetNumberLines()
            except Exception:
                _n_pt = -1
            log_to_file(
                f"[DET HB URTSP] t={time:.0f} jct={self.junction_id} "
                f"bus_sg={self.bus_sg} bus_req={self.bus_request} "
                f"bus_type_pos={self.bus_type_pos} bus_det={self.bus_det} "
                f"n_pt_lines={_n_pt} jxy_cache={_jxy_c} "
                f"mark_total={_mark_calls_total}",
                force=True
            )

        for det_id in self.bus_det:
            # Track previous presence for rising-edge fallback
            try:
                current_presence = AKIDetGetPresenceCyclebyId(det_id, 1)
            except Exception:
                current_presence = 0
            was_present = self.prev_bus_presence.get(det_id, 0)
            self.prev_bus_presence[det_id] = current_presence

            if _log_det:
                _vprint(
                    f"[DET URTSP] t={time:.1f} jct={self.junction_id} "
                    f"det={det_id} presence={current_presence} prev={was_present} "
                    f"cooldown_ok={time >= self._tsp_cooldown_until}"
                )

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
                            if _log_det:
                                _vprint(
                                    f"[DET URTSP] t={time:.1f} jct={self.junction_id} "
                                    f"det={det_id} v={inf.idVeh} type={inf.type} "
                                    f"≠ bus_pos={self.bus_type_pos} — skipped"
                                )
                            continue
                        # Position filter: within detection window
                        try:
                            pos = float(inf.CurrentPos)
                        except Exception:
                            pos = float(inf.distance2End if hasattr(inf, 'distance2End') else 0)
                        if _log_det:
                            _vprint(
                                f"[DET URTSP] t={time:.1f} jct={self.junction_id} "
                                f"det={det_id} v={inf.idVeh} pos={pos:.1f}m "
                                f"window=[{window_lo:.0f},{window_hi:.0f}]m "
                                f"in_window={window_lo <= pos <= window_hi}"
                            )
                        if window_lo <= pos <= window_hi:
                            _vid = inf.idVeh
                            # Mark detection point (first time only).
                            # Use vehicle XY if available, junction cache next,
                            # (0,0) as last resort — always write the CSV row.
                            _jxy_c = getattr(self, '_junction_xy_cache', None)
                            _vx = float(getattr(inf, 'xCurrentPos',
                                                 _jxy_c[0] if _jxy_c else 0.0))
                            _vy = float(getattr(inf, 'yCurrentPos',
                                                 _jxy_c[1] if _jxy_c else 0.0))
                            _mark_detection_point(
                                self.junction_id, _vid, _vx, _vy,
                                time, f"urtsp-sec={sec_id}"
                            )
                            if (self.bus_sg and self.bus_request is None
                                    and time >= self._tsp_cooldown_until):
                                self.bus_request = self.bus_sg
                                self._gb_bus_request_count += 1
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
                                if LOG_GB_BUS or _log_det:
                                    _eta_s = f"{self._bus_eta:.1f}s" if self._bus_eta is not None else "?"
                                    _vprint(
                                        f"[DET URTSP] t={time:.1f} jct={self.junction_id} "
                                        f"DETECTED [sec={sec_id} pos={pos:.1f}m] "
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
                    _jxy_c = getattr(self, '_junction_xy_cache', None)
                    _mark_detection_point(
                        self.junction_id, -det_id,
                        _jxy_c[0] if _jxy_c else 0.0,
                        _jxy_c[1] if _jxy_c else 0.0,
                        time, f"urtsp-det={det_id}"
                    )
                    if self.bus_sg and self.bus_request is None and time >= self._tsp_cooldown_until:
                        self.bus_request = self.bus_sg
                        self._gb_bus_request_count += 1
                        if LOG_GB_BUS or _log_det:
                            _vprint(
                                f"[DET URTSP] t={time:.1f} jct={self.junction_id} "
                                f"DETECTED [det={det_id} rising-edge] "
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

        # Sort phase groups so bus-friendly groups run earlier in the cycle:
        #   tier 0 — the group that contains bus_sg (Strategy 1 extension)
        #   tier 1 — groups fully compatible with bus_sg (Strategy 2 insertion)
        #   tier 2 — groups that conflict with bus_sg (Strategy 3 forced insertion)
        # Within each tier, sort by total max_green descending so the longest
        # phases (NB/SB through movements) run before shorter turn/side phases.
        if self.bus_sg is not None and self.conflict_matrix:
            _bus_compat = {
                other for other in self.all_sg
                if self.conflict_matrix.get(self.bus_sg, {}).get(other, 1) == 0
            }

            def _bus_tier(g):
                g_set = set(g)
                if self.bus_sg in g_set:
                    return 0   # bus can run here — Strategy 1
                if g_set <= (_bus_compat | {self.bus_sg}):
                    return 1   # bus compatible — Strategy 2 if needed
                return 2       # bus conflicts — requires Strategy 3

            groups.sort(key=lambda g: (
                _bus_tier(g),
                -sum(self.max_green.get(sg, 40.0) for sg in g),
            ))
        else:
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
        if LOG_GB:
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
        self._current_group_idx = best_idx
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

    # =========================================================================
    # INTERRUPTED-PHASE RESTORATION  (group-based equivalent of restore_phase_if_needed)
    # =========================================================================

    def _restore_interrupted_group(self, time: float, timeSta: float, queue: dict):
        """
        Re-activate the phase group that was cut short by a forced TSP insertion
        (Strategy 3).  Mirrors IntersectionController.restore_phase_if_needed()
        flag==2 behaviour: after the bus priority phase ends the interrupted group
        gets at least one full min_green before normal round-robin resumes.

        The restored group uses the same conflict-safe SG list it was running
        when the bus interrupted it — no additional conflict check needed since
        phase_groups is derived from the Bron-Kerbosch clique cover.
        """
        idx = self._interrupted_group_idx
        self._interrupted_group_idx = None   # consume — only one restoration per event

        if idx is None or not self.phase_groups or idx >= len(self.phase_groups):
            # Fallback: no valid interrupted group recorded; run normal round-robin
            self._build_new_phase(time, timeSta, queue)
            return

        group = self.phase_groups[idx]
        if not group:
            self._build_new_phase(time, timeSta, queue)
            return

        self.sg_list = list(group)
        # Mark as served so the cycle advances past it once done
        self._group_served.add(idx)
        self._current_group_idx = idx

        _group_max = max(self.max_green.get(sg, 40.0) for sg in self.sg_list)
        for sg in self.sg_list:
            self.non_activated.discard(sg)
            self.lower_time[sg] = time + self.min_green.get(sg, 6.0)
            self.upper_time[sg] = time + _group_max

        self._apply_signals(time, timeSta)
        self.state = self.GREEN

        if LOG_GB_STATE or LOG_GB_BUS:
            _vprint(
                f"[GB RESTORE] t={time:.1f} jct={self.junction_id} "
                f"Restored interrupted group_idx={idx} SGs={sorted(self.sg_list)} "
                f"min={self.min_green.get(self.sg_list[0], 6.0):.0f}s "
                f"max={_group_max:.0f}s (post-TSP restoration)"
            )

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
                        self._stats.record_tsp_event(self.junction_id, 'detection')
                        self._stats.record_tsp_event(self.junction_id, 'extension')
                        self._stats.record_tsp_extension_duration(self.junction_id, grant)
                elif grant == 0 and remaining > 0:
                    # Bus will naturally clear on green — extension not needed
                    if self._stats:
                        self._stats.record_tsp_event(self.junction_id, 'detection')
                        self._stats.record_tsp_skip(self.junction_id, 'natural_green')
                # remaining <= 0: budget exhausted; detection already counted when
                # the final extension was granted — do not double-count here.
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
                if self._bus_eta is not None and self._bus_det_time is not None:
                    _eta_now = max(0.0, float(self._bus_eta) - max(0.0, time - float(self._bus_det_time)))
                    self._stats.record_tsp_insertion_wait(self.junction_id, _eta_now)
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
                self._current_group_idx = bus_group_idx
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
        # Consume the coord-sourced flag now that the phase is activated.
        # The coordinator's _check_wave_complete watches bus_request (not this flag),
        # so clearing here is safe — it only affects future detection suppression.
        self._coord_sourced_request = False
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
            if self._bus_eta is not None and self._bus_det_time is not None:
                _eta_now = max(0.0, float(self._bus_eta) - max(0.0, time - float(self._bus_det_time)))
                self._stats.record_tsp_insertion_wait(self.junction_id, _eta_now)
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
                    self._gb_forced_termination_count += 1
                    # Record which group was running so we can restore it after
                    # the bus priority phase ends (mirrors phase-based restoration).
                    self._interrupted_group_idx = self._current_group_idx
                    if LOG_GB:
                        _vprint(
                            f"[GB] t={time:.1f} jct={self.junction_id} "
                            f"Bus SG {self.bus_request} forcing early termination "
                            f"(interrupted group_idx={self._interrupted_group_idx})"
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
        self.state              = self.INTERGREEN
        self.intergreen_end     = time + self.intergreen_dur
        self.extension_used     = 0.0
        self._active_bus_veh_id = None   # bus has left the priority phase

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

    def _is_external_control(self) -> bool:
        """Return True when this junction is under External/API control."""
        try:
            ctrl_type = ECIGetControlType(self.junction_id)
        except Exception:
            ctrl_type = -1

        external = ctrl_type in (2, 3)
        if not external:
            if not self._gb_bad_ctrl_warned:
                log_to_file(
                    f"[GB] WARNING jct={self.junction_id} control type={ctrl_type} "
                    f"(expected 2/3 External API) — GROUP_BASED TSP disabled for this junction",
                    force=True
                )
                self._gb_bad_ctrl_warned = True
        else:
            self._gb_bad_ctrl_warned = False

        self._external_control = external
        return external

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

        # ── Conflict-safety pass: never allow two conflicting SGs simultaneously ─
        # Walk sg_list in order; each new candidate is checked against every SG
        # already admitted.  Bus SG (if present) is always admitted first so it
        # is never dropped in favour of an earlier-listed SG.
        if self.conflict_matrix and len(self.sg_list) > 1:
            # Put bus_sg first so it is never the one removed
            ordered = []
            if self.bus_sg and self.bus_sg in self.sg_list:
                ordered.append(self.bus_sg)
            for sg in self.sg_list:
                if sg not in ordered:
                    ordered.append(sg)

            safe = []
            for sg in ordered:
                conflict = False
                for other in safe:
                    if self.conflict_matrix.get(sg, {}).get(other, 0) == 1:
                        conflict = True
                        log_to_file(
                            f"[GB CONFLICT] t={time:.1f} jct={self.junction_id} "
                            f"SG {sg} conflicts with SG {other} — dropped from phase",
                            force=True
                        )
                        break
                if not conflict:
                    safe.append(sg)

            if len(safe) != len(self.sg_list):
                self.sg_list = safe

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

        xs, ys = [], []
        for sec_id in self.incoming_sections:
            try:
                si = AKIInfNetGetSectionANGInf(sec_id)
                if si.report >= 0:
                    _xy = _extract_xy_from_section_info(si)
                    if _xy is not None:
                        xs.append(_xy[0])
                        ys.append(_xy[1])
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
                            _xy = _extract_xy_from_section_info(si)
                            if _xy is not None:
                                xs.append(_xy[0])
                                ys.append(_xy[1])
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

        _model_xy = _resolve_junction_xy_from_model(self.node_id, self.incoming_sections)
        if _model_xy is not None:
            self._junction_xy = _model_xy
            if LOG_JUNC_XY:
                _vprint(
                    f"[JUNC_XY] GB jct={self.junction_id} "
                    f"resolved via model → {self._junction_xy}"
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

        # ── Find the Aimsun phase that carries bus_sg ─────────────────────────
        # This is the phase we jump to via ECIChangeDirectPhase for TSP events.
        self._bus_aimsun_phase = None
        if self.bus_sg is not None:
            try:
                _n_ph = ECIGetNumberPhases(self.junction_id)
                for _ph in range(1, _n_ph + 1):
                    _n_sg = ECIGetNbSignalGroupsPhaseofJunction(
                        self.junction_id, _ph, 0.0)
                    for _pos in range(1, _n_sg + 1):
                        try:
                            _sg_id = ECIGetSignalGroupPhaseofJunction(
                                self.junction_id, _ph, _pos, 0.0)
                            if _sg_id == self.bus_sg:
                                self._bus_aimsun_phase = _ph
                                break
                        except Exception:
                            pass
                    if self._bus_aimsun_phase is not None:
                        break
            except Exception:
                pass
        log_to_file(
            f"[GB] jct={self.junction_id} bus_aimsun_phase={self._bus_aimsun_phase} "
            f"(bus_sg={self.bus_sg})"
        )
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

        NOTE: Because _initialize_sections already grabs ALL turn-origin sections
        (NB, SB, EB, WB) into self.incoming_sections, this method almost always
        returns an empty list.  The correct main/side split is derived by
        SimulationStats.register_intersection from UpDetList (main) and topology
        subtraction (side); collect_delay() uses that Stats-backed data first and
        falls through here only as a last resort.
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

        # ── Section classification: main (bus-approach) vs side (cross-street) ─
        # Priority 1: use SimulationStats-registered sections, which are derived
        #   from UpDetList detectors (main) and topology subtraction (side).
        #   This is the same source IntersectionController.collect_delay uses and
        #   is the only correct split — _initialize_sections grabs ALL approach
        #   sections so self.incoming_sections alone cannot distinguish main vs side.
        _inter_d  = self._stats._inter.get(self.junction_id, {})
        main_secs = set(_inter_d.get('main_sections', []))
        side_secs = set(_inter_d.get('side_sections', []))

        # Priority 2: if Stats has main but no side yet, try Stats topology method
        if main_secs and not side_secs:
            try:
                _resolved = self._stats._side_sections_from_topology(
                    self.junction_id, list(main_secs))
                side_secs = set(int(s) for s in _resolved if s and int(s) not in main_secs)
                if side_secs:
                    _inter_d['side_sections'] = list(sorted(side_secs))
                    _inter_d['side_sections_resolved'] = True
            except Exception:
                pass

        # Priority 3: if Stats has no main sections at all, fall back to the GB
        #   AAPI-based discovery (AKIInfNetGetNbTurnsInNode), but in this case
        #   _discover_side_sections returns empty because all sections are already
        #   in self.incoming_sections — so we treat ALL incoming as main (safe fallback).
        if not main_secs:
            if self._side_sections is None:
                self._discover_side_sections()
            main_secs = set(self.incoming_sections)
            side_secs = set(self._side_sections or []) - main_secs

        # Ensure no double-counting: side takes priority so it can use stop-time scan
        main_secs -= side_secs
        all_secs   = main_secs | side_secs
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
        self.P = np.diag([400.0, 16.0])     # initial state covariance (pos±20m, spd±4m/s)
        # Process noise: Q scales with dt inside predict().
        # q_pos=3 m²/s (bus can jerk, stop at lights), q_spd=0.5 m²/s³ (acceleration noise)
        self.Q = np.diag([3.0, 0.5])
        # Observation noise: std≈30 m accounts for detector placement uncertainty
        # A larger R makes predictions less sensitive to individual position fixes
        # and keeps speed estimates smooth across multiple junctions.
        self.R = 900.0
        self.last_t: float = None
        # Track the corridor-group index of the last junction this bus was seen at.
        # Used by the coordinator to determine travel direction.
        self._prev_inter_idx: int = -1

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
        # Clamp speed to plausible urban bus range [4, 20] m/s (14–72 km/h)
        # A tighter clamp prevents numerical drift and keeps ETAs realistic.
        self.x[1] = max(4.0, min(20.0, abs(self.x[1]))) * (1.0 if self.x[1] >= 0 else -1.0)

    def update_speed_from_travel(self, prev_pos_m: float, curr_pos_m: float,
                                  elapsed_s: float):
        """
        When a bus reaches a new junction we have a direct measurement of
        average speed over the inter-junction segment.  Fuse that observation
        into the state as a second Kalman update step.

        This is far more informative than position-only updates because it
        corrects the velocity component directly, leading to better ETAs at
        the next downstream junction.
        """
        if elapsed_s < 5.0:
            return   # avoid division by near-zero if timestamps are too close
        actual_speed = (curr_pos_m - prev_pos_m) / elapsed_s   # signed m/s
        # Clamp to plausible range before fusing
        actual_speed = max(4.0, min(20.0, abs(actual_speed))) * (1.0 if actual_speed >= 0 else -1.0)
        # Kalman update for speed observation:  H_v = [0, 1]
        H_v   = np.array([0.0, 1.0])
        R_v   = 4.0                                # speed obs noise var (std ≈ 2 m/s)
        innov = actual_speed - self.x[1]
        S_v   = float(H_v @ self.P @ H_v) + R_v
        K_v   = self.P @ H_v / S_v
        self.x = self.x + K_v * innov
        self.P = (np.eye(2) - np.outer(K_v, H_v)) @ self.P
        # Re-clamp after speed update
        self.x[1] = max(4.0, min(20.0, abs(self.x[1]))) * (1.0 if self.x[1] >= 0 else -1.0)

    def eta(self, target_pos_m: float, current_time: float) -> float:
        """
        Estimated arrival time (sim seconds) at target_pos_m.
        Handles both northbound (velocity > 0) and southbound (velocity < 0).
        Returns a very large number if the bus is moving away from the target.
        """
        dist  = target_pos_m - self.x[0]   # positive = target is ahead (north)
        speed = self.x[1]                   # positive = northbound
        if abs(dist) < 1.0:
            return current_time             # already at target
        if speed > 0 and dist > 0:          # northbound, target ahead
            return current_time + dist / speed
        if speed < 0 and dist < 0:          # southbound, target behind
            return current_time + abs(dist) / abs(speed)
        # Bus heading away from target — effectively unreachable
        return current_time + 99999.0

    def uncertainty_s(self, target_pos_m: float) -> float:
        """1-sigma arrival-time uncertainty (seconds)."""
        dist  = abs(target_pos_m - self.x[0])
        speed = max(abs(self.x[1]), 1.0)
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
    # ── Pre-arm lead time ─────────────────────────────────────────────────────
    # How many seconds before estimated bus arrival to fire the pre-arm request.
    # Must be large enough for the downstream junction to:
    #   (a) finish its current phase (worst-case ~50 s for long cycles)
    #   (b) execute intergreen (~5 s)
    #   (c) ramp up its bus phase before the bus reaches the stop line
    # 25 s was too short — a junction mid-phase routinely has 30–50 s remaining,
    # so the bus arrived before the phase could be set up, defeating coordination.
    # 50 s covers worst-case phase-remaining + intergreen for all Logan Rd junctions.
    PRE_GREEN_LEAD_S      = 50.0
    MAX_PRE_ARM            = 3      # max intersections ahead to pre-arm at once
    PRE_REQ_TIMEOUT_S     = 120.0  # stale pre-request expiry (was 90 s)
    MIN_UNMANAGED_DELAY_S = 10.0   # delay buffer per unmanaged in-system junction
    MAX_UNMANAGED_DELAY_S = 25.0

    def __init__(self, group_name: str, inter_ids: list, controllers_map: dict):
        self.name = group_name
        # GB controllers (GROUP_BASED_* modes) — full coordination support.
        self.inter_ids = [
            iid for iid in inter_ids
            if iid in controllers_map and controllers_map[iid].gb is not None
        ]
        self._ctrl_map = {iid: controllers_map[iid].gb for iid in self.inter_ids}

        # HARMONY IntersectionControllers — simplified coordination support.
        # Indexed by inter_id → IntersectionController (no gb attribute).
        # pre-arm sets _harmony_prearm on the controller; check_bus_priority handles it.
        self._ic_map: dict = {
            iid: controllers_map[iid]
            for iid in inter_ids
            if iid in controllers_map and controllers_map[iid].gb is None
        }
        # Merged inter_ids includes both GB and IC intersections
        self.inter_ids = list(dict.fromkeys(self.inter_ids + list(self._ic_map.keys())))
        route_ids = list(CORRIDOR_ROUTE_GROUPS.get(group_name, inter_ids))
        self.route_inter_ids = []
        for iid in route_ids:
            if iid in INTERSECTIONS_CONFIG or iid in self.inter_ids:
                self.route_inter_ids.append(iid)
        for iid in self.inter_ids:
            if iid not in self.route_inter_ids:
                self.route_inter_ids.append(iid)
        self._route_index = {iid: idx for idx, iid in enumerate(self.route_inter_ids)}
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
        self._pre_arm_count: int = 0

        # ── Coord-prearm outcome statistics ───────────────────────────────────
        # Answers "did the coordinator actually deliver a green wave?"
        # Key metrics:
        #   fired    — pre-arm request was set on downstream gb.bus_request
        #   success  — bus physically arrived at that junction during green phase
        #              (logged by GroupBasedController when it activates a coord-sourced request)
        #   missed   — pre-arm fired but bus was still in red on arrival
        #              (this happens when ETA is off or phase didn't have time to cycle)
        #   expired  — pre-request timed out (bus took a different route or was delayed > PRE_REQ_TIMEOUT_S)
        #   discarded— pre-arm fired but GB discarded it (cooldown, no bus_sg, wrong state)
        #   eta_errors_s — list of (actual_arrival − predicted_eta) values, for calibration
        #                  positive = bus arrived later than predicted
        #                  negative = bus arrived earlier than predicted
        self._prearm_stats: dict = {
            "fired":        0,
            "success":      0,
            "missed":       0,
            "expired":      0,
            "discarded":    0,
            "late_success": 0,
            "late_success_delay_s": 0.0,
            "eta_errors_s": [],
        }
        # Tracking: {(inter_id, veh_id): (eta_t, fired_at_t)} for outcome reporting
        self._fired_prearms: dict = {}
        # Lightweight diagnostics to confirm whether algorithm variants are
        # changing queue ETA and pre-arm lead decisions in practice.
        self._algo_diag: dict = {
            "queued": 0,
            "sw_adj_count": 0,
            "sw_adj_total_s": 0.0,
            "sw_adj_max_s": 0.0,
            "adaptive_fire_count": 0,
            "adaptive_dynamic_count": 0,
            "adaptive_lead_total_s": 0.0,
            "adaptive_lead_min_s": 1e9,
            "adaptive_lead_max_s": 0.0,
        }

        # ── Coordination wave state ───────────────────────────────────────────
        # When a bus is granted priority at any corridor junction a "wave" begins.
        # During the wave ALL other junctions block INDEPENDENT bus detections;
        # only coordinator-fired (pre-armed) requests are allowed through.
        # The ban lifts once all pre-requests for that wave vehicle have resolved.
        #
        # _wave_active     : True while a green-wave is in progress
        # _wave_veh_id     : vehicle that triggered the wave
        # _wave_origin     : junction ID where the wave started
        # _wave_served_ids : junctions that have already been pre-armed this wave
        #                    (once served, ban lifts individually for that junction)
        self._wave_active:     bool  = False
        self._wave_veh_id:     int   = -1
        self._wave_origin:     int   = -1
        self._wave_served_ids: set   = set()
        # Junctions where sigma was too high to pre-arm — wave ban is lifted so
        # they can run independent detection instead of waiting for a stale prearm.
        self._wave_uncertain_jcts: set = set()
        # Logged once per (from_jct, target_jct) pair when sigma or horizon gate
        # blocks a pre-arm.  Prevents log spam while keeping diagnostics visible.
        self._prearm_skip_logged_jcts: set = set()

        log_to_file(
            f"[CORRIDOR] group={self.name} members={self.inter_ids} "
            f"route={self.route_inter_ids} "
            f"(GB={len(self._ctrl_map)} IC-HARMONY={len(self._ic_map)} "
            f"of {len(inter_ids)} configured) "
            f"coordinated_tsp={COORDINATED_TSP}"
        )

        # Wire back-reference into each GB controller so it can call
        # notify_bus_granted() without needing the global list.
        for gb in self._ctrl_map.values():
            gb._corridor_coord = self
        # Wire back-reference into HARMONY IntersectionControllers too.
        for ic in self._ic_map.values():
            ic._corridor_coord = self

    # ------------------------------------------------------------------
    def _shockwave_eta_adjust(self, next_gb, next_bus_sg, eta: float, next_ic=None):
        """
        Queue-aware ETA correction using shockwave discharge logic.

        Uses the PREDICTED peak queue from the intersection's own shockwave
        model (MaxQueueLength, already computed from UpFlowList + shockwave
        speeds) rather than the live vehicle count.  The live count is always
        0 at pre-arm time (the bus hasn't arrived yet), which is why the old
        implementation never produced a non-zero correction.

        Falls back to live queue count if the model has no estimate yet.
        For HARMONY intersections (next_gb=None, next_ic set), uses live
        vehicle counts on approach sections as a queue proxy.

        Returns
        -------
        (eta_adj, queue_len_veh, eta_delta)
        """
        # Default parameters
        sat_flow  = 1800.0
        jam_den   = 150.0
        sat_den   = 45.0
        headway_s = 2.0

        if next_gb is not None:
            try:
                sat_flow = max(getattr(next_gb, 'SaturationFlow', 1800.0), 100.0)
                jam_den  = max(getattr(next_gb, 'JamDensity',     150.0),  10.0)
                sat_den  = max(getattr(next_gb, 'SaturationDensity', 45.0), 5.0)
                n_lanes  = max(getattr(next_gb, 'NumberOfLanes',    1),       1)
                headway_s = max(1.2, 3600.0 / sat_flow)

                bus_phase = getattr(next_gb, 'bus_phase', None)
                phase_idx = 0
                if bus_phase is not None and hasattr(next_gb, 'PhaseIndex'):
                    phase_idx = next_gb.PhaseIndex.get(bus_phase, 0)

                mql = getattr(next_gb, 'MaxQueueLength', None)
                queue_len = 0
                if mql is not None and phase_idx < len(mql) and len(mql[phase_idx]) > 0:
                    max_queue_m = float(mql[phase_idx][0])
                    if max_queue_m > 0.5:
                        queue_len = max(1, int(max_queue_m * jam_den / 1000.0 * n_lanes))

                if queue_len <= 0:
                    q = next_gb._compute_queue()
                    queue_len = max(int(q.get(next_bus_sg, 0)), 0)

                if queue_len <= 0:
                    try:
                        q_all = next_gb._compute_queue()
                        queue_len = max((int(v or 0) for v in q_all.values()), default=0)
                    except Exception:
                        queue_len = 0
            except Exception:
                queue_len = 0

        elif next_ic is not None:
            # HARMONY IntersectionController — no GB, use section vehicle counts
            try:
                queue_len = 0
                headway_s = 2.0
                # Count stopped/slow vehicles on approach sections as queue proxy
                for sec_id in getattr(next_ic, 'incoming_sections', []):
                    try:
                        n_veh = max(int(AKIVehStateGetNbVehiclesSection(sec_id, True)), 0)
                        stopped = 0
                        for vi in range(n_veh):
                            try:
                                vinf = AKIVehStateGetVehicleInfSection(sec_id, vi)
                                spd = float(getattr(vinf, 'CurrentSpeed', 0.0) or 0.0)
                                if spd < 5.0:  # km/h — effectively queued
                                    stopped += 1
                            except Exception:
                                continue
                        queue_len += stopped
                    except Exception:
                        continue
            except Exception:
                queue_len = 0
        else:
            return eta, 0, 0.0

        if queue_len <= 0:
            return eta, 0, 0.0

        try:
            # queue_clearance_s: time for all queued vehicles to pass the stopline
            # at saturation flow (simple headway model).
            queue_clearance_s = queue_len * headway_s

            # wave_delay_s: time for the discharge wave to travel back through
            # the entire queue to the bus.
            #   queue_distance_m = queue_len / jam_den_per_m
            #   discharge_wave_speed_ms = ShockwaveSpeed4 (m/s)
            # NOTE: ShockwaveSpeed4 already returns m/s (not km/h), so no
            # extra unit conversion is needed.  The old formula
            # "queue_len / w4 / (jam_den-sat_den) * 1000" was wrong — it
            # double-divided by density and produced the same value as
            # queue_clearance_s, giving an artificially large sw_adj.
            w4 = abs(ShockwaveSpeed4(sat_flow, jam_den, sat_den))  # m/s
            queue_m = queue_len * 1000.0 / max(jam_den, 1.0)       # m
            wave_delay_s = queue_m / max(w4, 0.001)                 # s

            # Use the smaller of the two estimates; cap at 30 s so a single
            # pre-arm event cannot create an excessively long insertion.
            eta_delta = min(queue_clearance_s, wave_delay_s, 30.0)
            return eta + eta_delta, queue_len, eta_delta
        except Exception:
            return eta, 0, 0.0

    # ------------------------------------------------------------------
    def _record_prearm_fired(self, inter_id: int, veh_id: int, eta_t: float, fired_at_t: float):
        self._prearm_stats["fired"] += 1
        self._fired_prearms[(inter_id, veh_id)] = (float(eta_t), float(fired_at_t))
        _record_wave_event(
            fired_at_t, self.name, "prearm_fired",
            source_jct=self._wave_origin,
            target_jct=inter_id,
            veh_id=veh_id,
            eta_s=max(0.0, float(eta_t) - float(fired_at_t)),
        )

    # ------------------------------------------------------------------
    def _record_prearm_discarded(self, inter_id: int):
        self._prearm_stats["discarded"] += 1
        _record_wave_event(
            AKIGetCurrentSimulationTime(), self.name, "prearm_discarded",
            source_jct=self._wave_origin,
            target_jct=inter_id,
            veh_id=self._wave_veh_id,
        )

    # ------------------------------------------------------------------
    def _record_prearm_success(self, inter_id: int, veh_id: int, actual_t: float):
        key = (inter_id, veh_id)
        rec = self._fired_prearms.pop(key, None)
        if rec is None:
            return
        eta_t, _fired_t = rec
        self._prearm_stats["success"] += 1
        eta_err_s = float(actual_t) - float(eta_t)
        self._prearm_stats["eta_errors_s"].append(eta_err_s)
        if eta_err_s > 0.0:
            self._prearm_stats["late_success"] += 1
            self._prearm_stats["late_success_delay_s"] += eta_err_s
        _record_wave_event(
            actual_t, self.name, "prearm_success",
            source_jct=self._wave_origin,
            target_jct=inter_id,
            veh_id=veh_id,
            eta_s=eta_err_s,
            note=("late" if eta_err_s > 0.0 else "on_time_or_early"),
        )

    # ------------------------------------------------------------------
    def _expire_fired_prearms(self, time: float):
        """Close unresolved fired pre-arms as misses after ETA grace period."""
        grace_s = 30.0
        stale = []
        for key, (eta_t, _fired_t) in self._fired_prearms.items():
            if time > eta_t + grace_s:
                stale.append(key)
        for key in stale:
            inter_id, veh_id = key
            self._fired_prearms.pop(key, None)
            self._prearm_stats["missed"] += 1
            _record_wave_event(
                time, self.name, "prearm_missed",
                source_jct=self._wave_origin,
                target_jct=inter_id,
                veh_id=veh_id,
                note="arrival_after_eta_grace",
            )

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
    def _iter_managed_targets(self, at_inter_id: int, is_northbound: bool,
                              veh_id: int = -1) -> list:
        """
          Return the immediate next managed intersection in corridor route order
          that this bus will actually visit.

        Priority:
          1. Bus's filed PT route (from _pt_line_jct_route via _bus_line_id).
                 Only the next managed junction explicitly in the bus's route is
                 returned — so a bus not stopping at junction X won't trigger a
                 pre-arm there, and long-range predictions are avoided.
          2. Geographic corridor order (_route_index / inter_ids) — fallback
             when the bus's PT route is unknown.
        """
        managed = set(self.inter_ids)

        # ── Attempt PT-route-aware targeting ─────────────────────────────────
        if veh_id > 0:
            line_id = _bus_line_id.get(veh_id, -1)
            if line_id > 0:
                route_jcts = _pt_line_jct_route.get(line_id)  # [jct_id, ...] in route order
                if route_jcts:
                    # Find this junction in the bus's route
                    try:
                        my_route_pos = route_jcts.index(at_inter_id)
                    except ValueError:
                        my_route_pos = -1

                    if my_route_pos >= 0:
                        # Slice ahead (direction already known from route order)
                        ahead = route_jcts[my_route_pos + 1:]
                        targets = [j for j in ahead if j in managed][:1]
                        if LOG_CORRIDOR and targets:
                            log_to_file(
                                f"[PT-ROUTE TARGETS] bus={veh_id} line={line_id} "
                                f"jct={at_inter_id} → {targets} (from PT route)"
                            )
                        return targets

        # ── Fallback tier 2: observed-route targeting ─────────────────────────
        # Use the per-bus zone-enter history (_bus_observed_jcts) to determine
        # which corridor junctions this bus has already passed through.
        # If we can confirm which managed junctions are ALREADY BEHIND the bus,
        # we can safely pre-arm the next N in the same direction without risking
        # arming junctions the bus won't visit.
        #
        # Logic:
        #  • Collect all observed junctions for this bus in entry order.
        #  • Find at_inter_id in the observed sequence.
        #  • All junctions after it (in route_inter_ids order that match the
        #    observed direction) are candidate targets, but only the immediate
        #    next managed junction is returned.
        if veh_id > 0:
            observed = _bus_observed_jcts.get(veh_id, [])
            if len(observed) >= 1:
                # Build the corridor-position of each observed junction.
                obs_in_route = [j for j in observed if j in self._route_index]
                if obs_in_route:
                    # Determine direction from the sequence of observed junctions.
                    obs_route_indices = [self._route_index[j] for j in obs_in_route]
                    if len(obs_route_indices) >= 2:
                        # Direction is determined by the trend of route indices.
                        nb_votes = sum(1 for a, b in zip(obs_route_indices, obs_route_indices[1:]) if b > a)
                        sb_votes = len(obs_route_indices) - 1 - nb_votes
                        observed_is_nb = (nb_votes >= sb_votes)
                    else:
                        observed_is_nb = is_northbound  # trust caller when only 1 observed

                    at_route_idx = self._route_index.get(at_inter_id)
                    if at_route_idx is not None:
                        step = 1 if observed_is_nb else -1
                        idx = at_route_idx + step
                        targets = []
                        while 0 <= idx < len(self.route_inter_ids) and len(targets) < 1:
                            iid = self.route_inter_ids[idx]
                            if iid in managed:
                                targets.append(iid)
                            idx += step
                        if targets:
                            if LOG_CORRIDOR:
                                log_to_file(
                                    f"[OBS-ROUTE TARGETS] bus={veh_id} "
                                    f"observed={obs_in_route} dir={'NB' if observed_is_nb else 'SB'} "
                                    f"jct={at_inter_id} → {targets} (from observed route)"
                                )
                            return targets

        # ── Fallback tier 3: geographic corridor order (direction only) ───────
        # Last resort when neither PT route nor observed history is available.
        # Restrict to the IMMEDIATE next junction only to avoid arming junctions
        # the bus won't reach.  Once that junction grants and calls
        # notify_bus_granted, the next pre-arm will be queued with updated info.
        route_idx = self._route_index.get(at_inter_id)
        if route_idx is None:
            try:
                my_idx = self.inter_ids.index(at_inter_id)
            except ValueError:
                return []
            if is_northbound:
                return self.inter_ids[my_idx + 1:my_idx + 2]   # next 1 only
            lo = max(0, my_idx - 1)
            return list(reversed(self.inter_ids[lo:my_idx]))

        step = 1 if is_northbound else -1
        idx = route_idx + step
        targets = []
        while 0 <= idx < len(self.route_inter_ids) and len(targets) < 1:
            iid = self.route_inter_ids[idx]
            if iid in managed:
                targets.append(iid)
            idx += step
        return targets

    # ------------------------------------------------------------------
    def _estimate_unmanaged_delay_s(self, inter_id: int) -> float:
        """Estimate expected delay at an unmanaged system junction."""
        cfg = INTERSECTIONS_CONFIG.get(inter_id, {}) or {}
        phase_durs = cfg.get("GreenPhaseDuration") or []
        cycle_s = 0.0
        try:
            cycle_s = sum(float(x) for x in phase_durs if x not in (None, ""))
        except Exception:
            cycle_s = 0.0

        bus_green_s = None
        try:
            bus_green_s = float(cfg.get("BusPhaseDuration"))
        except Exception:
            bus_green_s = None
        if bus_green_s in (None, 0.0) and phase_durs:
            try:
                bus_phase = int(cfg.get("BusPhase", 1) or 1)
                if 1 <= bus_phase <= len(phase_durs):
                    bus_green_s = float(phase_durs[bus_phase - 1])
            except Exception:
                bus_green_s = None

        if cycle_s > 0.0 and bus_green_s is not None:
            red_s = max(cycle_s - max(bus_green_s, 0.0), 0.0)
            return min(
                self.MAX_UNMANAGED_DELAY_S,
                max(self.MIN_UNMANAGED_DELAY_S, 0.35 * red_s),
            )

        return self.MIN_UNMANAGED_DELAY_S

    # ------------------------------------------------------------------
    def _route_gap_delay_s(self, from_inter_id: int, to_inter_id: int) -> float:
        """Return ETA slack for unmanaged intersections between two managed nodes."""
        from_idx = self._route_index.get(from_inter_id)
        to_idx = self._route_index.get(to_inter_id)
        if from_idx is None or to_idx is None or from_idx == to_idx:
            return 0.0

        lo, hi = sorted((from_idx, to_idx))
        managed = set(self.inter_ids)
        gap_delay_s = 0.0
        for iid in self.route_inter_ids[lo + 1:hi]:
            if iid in managed:
                continue
            gap_delay_s += self._estimate_unmanaged_delay_s(iid)
        return gap_delay_s

    # ------------------------------------------------------------------
    def is_wave_banned(self, inter_id: int) -> bool:
        """
        Return True if junction inter_id should block independent bus detections.

        A junction is banned when:
          • A coordination wave is active (COORDINATED_TSP=True)
          • The junction is not yet in _wave_served_ids
            (served = the coordinator has already pre-armed it this wave)

        Once the coordinator pre-arms junction[j] and the pre-request fires,
        junction[j] is added to _wave_served_ids and its ban is lifted so it
        can react normally to the pre-armed request.
        """
        if not COORDINATED_TSP or not self._wave_active:
            return False
        if inter_id in self._wave_uncertain_jcts:
            return False   # sigma too high to pre-arm — let independent detection run
        return inter_id not in self._wave_served_ids

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

        # If this junction had an active pre-arm record for this bus, mark outcome.
        self._record_prearm_success(at_inter_id, veh_id, time)

        # Update (or create) Kalman tracker for this vehicle
        tracker = self._trackers.get(veh_id)
        if tracker is None:
            tracker = BusKalmanTracker(initial_pos_m=at_pos)
            self._trackers[veh_id] = tracker
        else:
            prev_pos = tracker.x[0]
            prev_t   = tracker.last_t
            if prev_t is not None:
                tracker.predict(max(time - prev_t, 0.0))
            tracker.update(at_pos)
            # Fuse direct speed measurement from inter-junction travel time
            if prev_t is not None and prev_t < time:
                tracker.update_speed_from_travel(prev_pos, at_pos, time - prev_t)
        tracker.last_t = time

        # ── Determine travel direction from junction-sequence history ──────────
        my_idx = self._route_index.get(at_inter_id, -1)
        if my_idx < 0:
            return

        prev_idx = tracker._prev_inter_idx
        if prev_idx >= 0 and prev_idx != my_idx:
            # We know which junction the bus came from → reliable direction
            is_northbound = (my_idx > prev_idx)
            # Align Kalman velocity sign with observed direction
            spd = abs(tracker.x[1])
            tracker.x[1] = spd if is_northbound else -spd
        else:
            # First detection in this corridor — assume northbound (positive velocity)
            is_northbound = (tracker.x[1] >= 0)
        tracker._prev_inter_idx = my_idx

        if LOG_CORRIDOR:
            _dir_tag = "NB" if is_northbound else "SB"
            _vprint(
                f"[CORRIDOR KF] t={time:.1f} bus={veh_id} granted "
                f"jct={at_inter_id} pos={at_pos:.0f}m "
                f"spd={tracker.x[1]:.1f}m/s ({tracker.x[1]*3.6:.0f}km/h) dir={_dir_tag}"
            )
        _record_wave_event(
            time, self.name, "grant",
            source_jct=at_inter_id,
            target_jct=at_inter_id,
            veh_id=veh_id,
            note=("northbound" if is_northbound else "southbound"),
        )

        # Start (or refresh) a coordination wave.
        # All other junctions get a ban on independent bus detection until
        # each of them is individually pre-armed and served.
        if COORDINATED_TSP:
            self._wave_active      = True
            self._wave_veh_id      = veh_id
            self._wave_origin      = at_inter_id
            self._wave_served_ids  = {at_inter_id}   # origin is already "served"
            self._wave_uncertain_jcts = set()         # reset per wave
            if LOG_CORRIDOR:
                _vprint(
                    f"[CORRIDOR WAVE] t={time:.1f} WAVE START bus={veh_id} "
                    f"origin=jct{at_inter_id} dir={'NB' if is_northbound else 'SB'} — "
                    f"banning independent TSP at "
                    f"{[i for i in self.inter_ids if i != at_inter_id]}"
                )

        for next_id in self._iter_managed_targets(at_inter_id, is_northbound, veh_id=veh_id):
            next_pos = self.corridor_pos.get(next_id)
            # Sanity check: target must be in direction of travel
            if next_pos is None:
                continue
            if is_northbound and next_pos <= at_pos:
                continue   # next junction must be north (larger pos)
            if not is_northbound and next_pos >= at_pos:
                continue   # next junction must be south (smaller pos)
            # Signal-aware ETA: chains through intermediate junctions, adding
            # kinematic travel + expected red-wait at each signal encountered
            # before the target.  Falls back to pure kinematic when position data
            # is unavailable for intermediates.
            _eta_kinematic  = tracker.eta(next_pos, time)
            eta             = self._signal_aware_eta(at_inter_id, next_id, tracker, time)
            # Bail if ETA is unreachable (bus heading wrong way — shouldn't happen)
            if eta > time + 99000:
                continue
            _signal_delay_contrib = max(0.0, eta - _eta_kinematic)
            gap_delay_s = 0.0   # now folded into signal_aware_eta
            sigma = tracker.uncertainty_s(next_pos)
            next_gb  = self._ctrl_map.get(next_id)
            next_ic  = self._ic_map.get(next_id)
            next_bus_sg = next_gb.bus_sg if next_gb else None

            # ── Prearm quality gate ───────────────────────────────────────
            # Skip queuing if the ETA prediction is too uncertain (sigma > 25s)
            # or the remaining travel time is so long that GE would exceed the
            # hard cap. This prevents wasted prearms that are likely to miss.
            _eta_from_now = eta - time
            _PREARM_MAX_SIGMA = 25.0
            if sigma > _PREARM_MAX_SIGMA:
                # Lift the wave ban for this junction so it can run its own
                # independent detection rather than wait for a stale prearm.
                self._wave_uncertain_jcts.add(next_id)
                _skip_key_sigma = (at_inter_id, next_id, "sigma")
                if _skip_key_sigma not in self._prearm_skip_logged_jcts:
                    self._prearm_skip_logged_jcts.add(_skip_key_sigma)
                    log_to_file(
                        f"[PREARM SKIP SIGMA] group={self.name} "
                        f"from=jct{at_inter_id} to=jct{next_id} "
                        f"sigma={sigma:.1f}s > {_PREARM_MAX_SIGMA:.0f}s — "
                        f"prediction too uncertain (dist={(abs(next_pos - at_pos)):.0f}m) "
                        f"→ jct{next_id} added to _wave_uncertain_jcts",
                        force=True
                    )
                elif LOG_CORRIDOR:
                    log_to_file(
                        f"[CORRIDOR SKIP QUEUE] jct={next_id} bus={veh_id} "
                        f"sigma={sigma:.1f}s > {_PREARM_MAX_SIGMA:.0f}s — prediction too uncertain"
                    )
                continue
            # Don't queue prearms where the bus is more than 2 cycles away —
            # by the time it fires the ETA will be very stale.
            _max_prearm_horizon_s = float(getattr(self, '_max_prearm_horizon_s', 180.0))
            if _eta_from_now > _max_prearm_horizon_s:
                _skip_key_horizon = (at_inter_id, next_id, "horizon")
                if _skip_key_horizon not in self._prearm_skip_logged_jcts:
                    self._prearm_skip_logged_jcts.add(_skip_key_horizon)
                    log_to_file(
                        f"[PREARM SKIP HORIZON] group={self.name} "
                        f"from=jct{at_inter_id} to=jct{next_id} "
                        f"eta_in={_eta_from_now:.0f}s > horizon={_max_prearm_horizon_s:.0f}s — "
                        f"junction too far ahead (dist={(abs(next_pos - at_pos)):.0f}m)",
                        force=True
                    )
                elif LOG_CORRIDOR:
                    log_to_file(
                        f"[CORRIDOR SKIP QUEUE] jct={next_id} bus={veh_id} "
                        f"eta_in={_eta_from_now:.0f}s > horizon={_max_prearm_horizon_s:.0f}s"
                    )
                continue

            eta_base = eta
            queue_len = 0
            eta_delta = 0.0
            eta_adj = eta

            # Queue-aware ETA correction in SHOCKWAVE and ADAPTIVE modes.
            if COORDINATION_ALGO in ("SHOCKWAVE", "ADAPTIVE"):
                eta_adj, queue_len, eta_delta = self._shockwave_eta_adjust(
                    next_gb, next_bus_sg, eta, next_ic=next_ic)
                if LOG_CORRIDOR and eta_delta > 0.0:
                    log_to_file(
                        f"[CORRIDOR SW] jct={next_id} queue={queue_len}veh "
                        f"ETA_base={eta:.1f}s wave_adj=+{eta_delta:.1f}s ETA_adj={eta_adj:.1f}s"
                    )
                eta = eta_adj

            if LOG_CORRIDOR and _signal_delay_contrib > 0.5:
                _vprint(
                    f"[CORRIDOR SIG] from=jct{at_inter_id} to=jct{next_id} "
                    f"signal_delay=+{_signal_delay_contrib:.1f}s "
                    f"(kinematic={_eta_kinematic - time:.0f}s + sig={_signal_delay_contrib:.0f}s)"
                )

            # ── Deduplication: skip re-queuing if this (junction, bus) was already
            # fired recently.  Without this, every upstream grant re-queues the
            # same downstream junctions causing prearm spam in the wave events CSV.
            _prev_fire = self._fired_prearms.get((next_id, veh_id))
            if _prev_fire is not None:
                _, _prev_fire_t = _prev_fire
                if time - _prev_fire_t < 150.0:  # 150 s cooldown per (junction, bus)
                    if LOG_CORRIDOR:
                        log_to_file(
                            f"[CORRIDOR DEDUP] skipping re-queue jct={next_id} "
                            f"bus={veh_id} — already fired {time - _prev_fire_t:.0f}s ago"
                        )
                    continue

            self._pre_requests[next_id] = (veh_id, eta, next_bus_sg, time)
            self._pre_arm_count += 1
            self._algo_diag["queued"] = int(self._algo_diag.get("queued", 0) or 0) + 1
            if COORDINATION_ALGO in ("SHOCKWAVE", "ADAPTIVE") and eta_delta > 0.0:
                self._algo_diag["sw_adj_count"] = int(self._algo_diag.get("sw_adj_count", 0) or 0) + 1
                self._algo_diag["sw_adj_total_s"] = float(self._algo_diag.get("sw_adj_total_s", 0.0) or 0.0) + float(eta_delta)
                self._algo_diag["sw_adj_max_s"] = max(
                    float(self._algo_diag.get("sw_adj_max_s", 0.0) or 0.0),
                    float(eta_delta),
                )
            if LOG_CORRIDOR:
                _algo_tag = f"[{COORDINATION_ALGO}]"
                log_to_file(
                    f"[CORRIDOR {_algo_tag}] Pre-arm jct={next_id} bus={veh_id} "
                    f"SG={next_bus_sg} ETA={eta:.1f}s "
                    f"(+{eta - time:.0f}s ±{sigma:.0f}s) dist={next_pos - at_pos:.0f}m"
                )
                log_to_file(
                    f"[CORRIDOR DECISION] algo={COORDINATION_ALGO} stage=queue "
                    f"from={at_inter_id} to={next_id} bus={veh_id} "
                    f"eta_base={eta_base:.1f} eta_final={eta:.1f} eta_delta={eta_delta:.1f} "
                    f"sig_delay={_signal_delay_contrib:.1f} queue={queue_len} sigma={sigma:.1f}"
                )
            _record_wave_event(
                time, self.name, "prearm_queued",
                source_jct=at_inter_id,
                target_jct=next_id,
                veh_id=veh_id,
                eta_s=max(0.0, eta - time),
                note=COORDINATION_ALGO,
            )

    # ------------------------------------------------------------------
    def _signal_delay_at_s(self, inter_id: int, arrive_t: float, time: float) -> float:
        """
        Estimate how long (seconds) a bus will wait at junction inter_id
        if it arrives at absolute simulation time arrive_t.

        Queries the live Aimsun phase state at the current sim-time and
        projects the phase sequence forward to arrive_t, returning the
        gap between arrive_t and the start of the next green window for
        the bus direction.

        Falls back to _estimate_unmanaged_delay_s when phase data is
        unavailable (e.g., junctions not under Aimsun external control).
        """
        gb = self._ctrl_map.get(inter_id)
        cfg = INTERSECTIONS_CONFIG.get(inter_id, {}) or {}

        # Which Aimsun phase carries the bus at this junction?
        bus_phase_num: int = 1
        if gb is not None:
            bp = getattr(gb, '_bus_aimsun_phase', None)
            if bp is not None:
                bus_phase_num = int(bp)
            jct_id = gb.junction_id
        else:
            try:
                bus_phase_num = int(cfg.get("BusPhase", 1) or 1)
            except Exception:
                bus_phase_num = 1
            jct_id = inter_id

        try:
            n_phases = int(ECIGetNumberPhases(jct_id))
            if n_phases <= 0:
                return self._estimate_unmanaged_delay_s(inter_id)

            current_phase = int(ECIGetCurrentPhase(jct_id))
            phase_start_t = float(ECIGetStartingTimePhase(jct_id))
            phase_elapsed = max(0.0, time - phase_start_t)

            # Walk one full cycle from the current position, building the
            # absolute timeline for each phase.
            # cycle_timeline: [(phase_num, abs_start, abs_end), ...]
            cycle_timeline = []
            t_cursor = time
            for step in range(n_phases):
                ph = ((current_phase - 1 + step) % n_phases) + 1
                raw_dur = float(GetPhaseDuration(jct_id, ph, 0.0))
                dur = max(raw_dur, 1.0)   # guard against zero-duration phases
                if step == 0:
                    # Current phase: already partially elapsed
                    remaining = max(0.0, dur - phase_elapsed)
                    t_start = phase_start_t
                    t_end   = time + remaining
                else:
                    t_start = t_cursor
                    t_end   = t_cursor + dur
                cycle_timeline.append((ph, t_start, t_end))
                t_cursor = t_end

            cycle_len = t_cursor - time   # total remaining cycle duration

            # First occurrence of the bus phase in this cycle
            green_start = None
            green_end   = None
            for ph, t_s, t_e in cycle_timeline:
                if ph == bus_phase_num:
                    green_start = t_s
                    green_end   = t_e
                    break

            if green_start is None or cycle_len <= 0:
                return self._estimate_unmanaged_delay_s(inter_id)

            if arrive_t >= green_start and arrive_t < green_end:
                return 0.0    # arrives during green — no wait

            if arrive_t < green_start:
                return green_start - arrive_t   # wait until green opens

            # Bus arrives after this cycle's green — project forward by full cycles
            cycles_ahead = math.ceil((arrive_t - green_end) / cycle_len)
            next_green_start = green_start + cycles_ahead * cycle_len
            return max(0.0, next_green_start - arrive_t)

        except Exception:
            return self._estimate_unmanaged_delay_s(inter_id)

    # ------------------------------------------------------------------
    def _signal_aware_eta(self, from_id: int, to_id: int,
                          tracker: 'BusKalmanTracker', time: float) -> float:
        """
        Signal-aware estimated arrival time (sim-seconds) at to_id.

        Rather than pure distance/speed, walks every junction in
        route_inter_ids between from_id and to_id, computing at each step:
          1. Kinematic travel time from the last known position to this junction
          2. Expected red wait at this junction (_signal_delay_at_s)

        The accumulated position+time is used as input to the next kinematic
        leg. Falls back to tracker.eta() when route position data is
        unavailable for intermediate junctions.

        The Kalman tracker state is read but never modified here; regular
        tracker.update() behaviour is undisturbed.
        """
        from_idx = self._route_index.get(from_id)
        to_idx   = self._route_index.get(to_id)
        to_pos   = self.corridor_pos.get(to_id)

        if from_idx is None or to_idx is None or to_pos is None:
            return (tracker.eta(to_pos, time)
                    if to_pos is not None else time + 99999.0)

        lo, hi = sorted((from_idx, to_idx))
        intermediates = self.route_inter_ids[lo + 1: hi]  # exclusive of endpoints

        if not intermediates:
            return tracker.eta(to_pos, time)

        # Propagate at current tracker speed; fall back to default if stalled
        spd = abs(tracker.x[1])
        if spd < 0.5:
            spd = BusKalmanTracker.DEFAULT_SPEED_MS

        # Walk intermediates in route direction
        is_northbound = (to_idx > from_idx)
        step_jcts = intermediates if is_northbound else list(reversed(intermediates))

        t_cursor   = time
        pos_cursor = tracker.x[0]  # current bus position along corridor (m)

        for jct_id in step_jcts:
            jct_pos = self.corridor_pos.get(jct_id)
            if jct_pos is None:
                # No corridor position — add fixed delay estimate and continue
                t_cursor += self._estimate_unmanaged_delay_s(jct_id)
                continue

            dist_m   = abs(jct_pos - pos_cursor)
            t_arrive = t_cursor + dist_m / spd
            t_cursor = t_arrive + self._signal_delay_at_s(jct_id, t_arrive, time)
            pos_cursor = jct_pos

        # Final kinematic leg from last intermediate to target junction
        dist_final = abs(to_pos - pos_cursor)
        t_cursor += dist_final / spd
        return t_cursor

    # ------------------------------------------------------------------
    def _objective_lead_time(self, gb, bus_sg, eta_t: float, time: float,
                              tracker) -> float:
        """
        OBJECTIVE mode: compute the pre-arm lead time that maximises:
          J = COORD_OBJ_ALPHA * bus_delay_saved_persons
            - COORD_OBJ_BETA  * normal_throughput_displaced_persons

        This avoids the perverse incentive of pure delay minimisation
        (fewer vehicles served → lower total delay) by explicitly including
        a throughput benefit term.  Lead times from 5 to 60 s are evaluated;
        the one with the highest J is returned.

        Parameters
        ----------
        gb       : GroupBasedController at the downstream intersection
        bus_sg   : signal group for bus at that intersection
        eta_t    : estimated arrival time (absolute sim seconds)
        time     : current sim time
        tracker  : BusKalmanTracker for this vehicle
        """
        BUS_OCC     = getattr(gb, 'BusOcc',   40.0)
        NORMAL_OCC  = getattr(gb, 'CarOcc',    1.5)
        MAX_RED_WAIT = getattr(gb, '_eta_max_s', 60.0)   # typical max red wait

        try:
            queue    = gb._compute_queue()
            q_bus_sg = queue.get(bus_sg, 0)
        except Exception:
            q_bus_sg = 0

        # Arrival time uncertainty: 1-sigma from Kalman tracker
        try:
            target_pos = self.corridor_pos.get(
                next(iid for iid, c in self._ctrl_map.items() if c is gb), None)
            sigma = tracker.uncertainty_s(target_pos) if target_pos else 15.0
        except Exception:
            sigma = 15.0

        best_J    = -1e9
        best_lead = self.PRE_GREEN_LEAD_S   # fallback to fixed default

        for lead in range(5, 65, 5):
            eta_in = eta_t - time   # seconds until bus arrives
            # P[bus arrives during green] grows as lead / (2*sigma)
            p_green = min(1.0, max(0.0, lead / (2.0 * sigma + 1.0)))

            # Delay saved for bus: avoided red wait × occupancy
            # Maximum possible red wait capped at MAX_RED_WAIT
            delay_saved = min(eta_in, MAX_RED_WAIT) * p_green * BUS_OCC

            # Normal-traffic cost: pre-arming disrupts normal phases for ~lead s.
            # Queue at downstream * occupancy * fractional green lost.
            green_fraction_lost = lead / max(self.PRE_GREEN_LEAD_S * 2, 30.0)
            throughput_lost = q_bus_sg * NORMAL_OCC * green_fraction_lost

            J = COORD_OBJ_ALPHA * delay_saved - COORD_OBJ_BETA * throughput_lost
            if J > best_J:
                best_J    = J
                best_lead = float(lead)

        if LOG_CORRIDOR:
            _vprint(
                f"[CORRIDOR OBJ] Optimal lead={best_lead:.0f}s "
                f"J={best_J:.1f} sigma={sigma:.1f}s q={q_bus_sg}"
            )
        return best_lead

    # ------------------------------------------------------------------
    def _process_pre_requests(self, time: float, timeSta: float):
        """Fire pre-green requests when the bus is within the algorithm's lead time."""
        for inter_id, (veh_id, eta_t, bus_sg, issued_t) in list(self._pre_requests.items()):
            # Stale: bus never arrived or took a different route
            if time - issued_t > self.PRE_REQ_TIMEOUT_S or eta_t - time < -30.0:
                del self._pre_requests[inter_id]
                self._prearm_stats["expired"] += 1
                log_to_file(
                    f"[CORRIDOR PREARM] EXPIRED jct={inter_id} bus={veh_id} "
                    f"age={time - issued_t:.0f}s ETA_was={eta_t:.1f}s now={time:.1f}s"
                )
                _record_wave_event(
                    time, self.name, "prearm_expired",
                    source_jct=self._wave_origin,
                    target_jct=inter_id,
                    veh_id=veh_id,
                    eta_s=eta_t - time,
                )
                continue

            # ── Dynamic lead time computation ─────────────────────────────────
            # Standard fixed-lead fires PRE_GREEN_LEAD_S seconds before ETA.
            # OBJECTIVE algo computes a bus-delay-vs-throughput optimal lead.
            # In addition, we add "phase_lead" — the minimum time the downstream
            # junction needs to finish its current phase and enter intergreen so
            # that the bus phase is ready on arrival.  This prevents the bus from
            # arriving before the pre-armed phase even starts.
            gb = self._ctrl_map.get(inter_id)
            lead_reason = "fixed"
            lead_sigma = None
            phase_lead = 0.0
            if COORDINATION_ALGO == "OBJECTIVE" and gb is not None and bus_sg is not None:
                _tracker = self._trackers.get(veh_id)
                if _tracker is not None:
                    lead_s = self._objective_lead_time(gb, bus_sg, eta_t, time, _tracker)
                    lead_reason = "objective"
                else:
                    lead_s = self.PRE_GREEN_LEAD_S
                    lead_reason = "objective-fallback"
            elif COORDINATION_ALGO == "ADAPTIVE":
                lead_s = self.PRE_GREEN_LEAD_S
                lead_reason = "adaptive-base"
                _tracker = self._trackers.get(veh_id)
                if _tracker is not None:
                    try:
                        _target = self.corridor_pos.get(inter_id)
                        _sigma = _tracker.uncertainty_s(_target) if _target is not None else 12.0
                    except Exception:
                        _sigma = 12.0
                    lead_sigma = _sigma
                    # Adaptive lead: scale with uncertainty.  Low sigma (confident
                    # prediction) → shorter lead; high sigma → longer lead.
                    # Formula: base of 15s + 3×sigma, clamped to [20, 75].
                    # At sigma=8 → 39s, sigma=12 → 51s, sigma=20 → 75s.
                    _adaptive_lead = max(20.0, min(75.0, 15.0 + 3.0 * _sigma))
                    lead_s = _adaptive_lead
                    lead_reason = "adaptive-sigma"
            else:
                lead_s = self.PRE_GREEN_LEAD_S   # KALMAN and SHOCKWAVE: base fixed lead
                lead_reason = "fixed"

            # Add phase-transition overhead if the downstream junction exposes it
            if gb is not None:
                phase_lead = getattr(gb, '_min_lead_for_phase_change_s', 0.0)
                lead_s = max(lead_s, phase_lead)

            if LOG_CORRIDOR:
                _sigma_txt = f"{lead_sigma:.1f}" if lead_sigma is not None else "na"
                log_to_file(
                    f"[CORRIDOR DECISION] algo={COORDINATION_ALGO} stage=fire "
                    f"jct={inter_id} bus={veh_id} eta_in={eta_t - time:.1f} "
                    f"lead={lead_s:.1f} phase_lead={phase_lead:.1f} "
                    f"base_lead={self.PRE_GREEN_LEAD_S:.1f} sigma={_sigma_txt} reason={lead_reason}"
                )

            if COORDINATION_ALGO == "ADAPTIVE":
                self._algo_diag["adaptive_fire_count"] = int(self._algo_diag.get("adaptive_fire_count", 0) or 0) + 1
                self._algo_diag["adaptive_lead_total_s"] = float(self._algo_diag.get("adaptive_lead_total_s", 0.0) or 0.0) + float(lead_s)
                self._algo_diag["adaptive_lead_min_s"] = min(
                    float(self._algo_diag.get("adaptive_lead_min_s", 1e9) or 1e9),
                    float(lead_s),
                )
                self._algo_diag["adaptive_lead_max_s"] = max(
                    float(self._algo_diag.get("adaptive_lead_max_s", 0.0) or 0.0),
                    float(lead_s),
                )
                if abs(float(lead_s) - float(self.PRE_GREEN_LEAD_S)) > 0.1:
                    self._algo_diag["adaptive_dynamic_count"] = int(self._algo_diag.get("adaptive_dynamic_count", 0) or 0) + 1

            if eta_t - time <= lead_s:
                # ── Revalidate ETA with current Kalman state ──────────
                # The prearm was queued earlier — recheck that the tracker
                # still predicts a reasonable arrival.  If the live ETA
                # now exceeds the original by more than 30 s the bus may
                # have been delayed or diverted; skip the fire.
                _tracker_live = self._trackers.get(veh_id)
                _target_pos   = self.corridor_pos.get(inter_id)
                if _tracker_live is not None and _target_pos is not None:
                    try:
                        _live_eta = _tracker_live.eta(_target_pos)
                        if _live_eta is not None and _live_eta > eta_t + 30.0:
                            if LOG_CORRIDOR:
                                log_to_file(
                                    f"[CORRIDOR SKIP FIRE] jct={inter_id} bus={veh_id} "
                                    f"live_eta={_live_eta:.1f}s vs queued_eta={eta_t:.1f}s "
                                    f"— bus delayed, skipping prearm fire"
                                )
                            del self._pre_requests[inter_id]
                            self._prearm_stats.setdefault("revalidation_skip", 0)
                            self._prearm_stats["revalidation_skip"] += 1
                            continue
                    except Exception:
                        pass

                if gb is not None and bus_sg is not None and gb.bus_request is None:
                    # Respect the per-vehicle cooldown at the target junction
                    cooldown_ok = not (
                        veh_id == getattr(gb, '_last_served_veh_id', None)
                        and time - getattr(gb, '_last_served_time', -9999.0)
                        < getattr(gb, '_served_veh_timeout', 120.0)
                    )
                    if not cooldown_ok:
                        # Cooldown active — bus recently served at this junction.
                        # Record as prearm_skipped so the dashboard coord-flow can
                        # show that the coordinator saw the bus but chose not to act.
                        _record_wave_event(
                            time, self.name, "prearm_skipped",
                            source_jct=self._wave_origin,
                            target_jct=inter_id,
                            veh_id=veh_id,
                            eta_s=max(0.0, eta_t - time),
                            note="cooldown",
                        )
                        del self._pre_requests[inter_id]
                        self._prearm_stats.setdefault("skipped_cooldown", 0)
                        self._prearm_stats["skipped_cooldown"] += 1
                        continue
                    if cooldown_ok:
                        gb.bus_request = bus_sg
                        gb._active_bus_veh_id = veh_id
                        gb._bus_eta = max(0.0, eta_t - time)
                        gb._bus_det_time = time
                        # Mark as coordinator-sourced so the detection suppression
                        # logic in _detect_bus/_detect_bus_urtsp knows to let it through.
                        gb._coord_sourced_request = True
                        # Lift the wave ban for this junction: it is now reacting
                        # to coordination, not acting independently.
                        self._wave_served_ids.add(inter_id)
                        self._record_prearm_fired(inter_id, veh_id, eta_t, time)
                        # Use the bus's live position (from position tracker) so
                        # prearm marks show WHERE the bus was when the prearm
                        # fired, not where the downstream junction is.  This
                        # prevents all coord-prearm dots from piling up on the
                        # junction centroid when many buses are served.
                        _bus_live_xy = _bus_xy.get(veh_id)
                        _prearm_x = _bus_live_xy[0] if _bus_live_xy else 0.0
                        _prearm_y = _bus_live_xy[1] if _bus_live_xy else 0.0
                        if not _bus_live_xy:
                            _junc_xy_fb = getattr(gb, '_junction_xy_cache', None)
                            if _junc_xy_fb:
                                _prearm_x, _prearm_y = _junc_xy_fb
                        _mark_detection_point(
                            inter_id, veh_id, _prearm_x, _prearm_y,
                            time, f"coord-prearm/{COORDINATION_ALGO}"
                        )
                        if LOG_CORRIDOR:
                            _vprint(
                                f"[CORRIDOR {COORDINATION_ALGO}] Pre-green FIRED "
                                f"jct={inter_id} bus={veh_id} SG={bus_sg} "
                                f"ETA_in={eta_t - time:.1f}s lead={lead_s:.0f}s "
                                f"— ban lifted for jct{inter_id}"
                            )
                elif inter_id in self._ic_map:
                    # HARMONY intersection — set _harmony_prearm so check_bus_priority
                    # applies TSP immediately using the Kalman ETA.
                    ic = self._ic_map[inter_id]
                    if ic._harmony_prearm is None:
                        ic._harmony_prearm = (veh_id, eta_t, time)
                        self._wave_served_ids.add(inter_id)
                        self._record_prearm_fired(inter_id, veh_id, eta_t, time)
                        # Same as GB path: mark bus's live position, not junction.
                        _bus_live_xy_h = _bus_xy.get(veh_id)
                        _prearm_hx = _bus_live_xy_h[0] if _bus_live_xy_h else 0.0
                        _prearm_hy = _bus_live_xy_h[1] if _bus_live_xy_h else 0.0
                        if not _bus_live_xy_h:
                            try:
                                _junc_xy_h = ic._get_junction_xy()
                                if _junc_xy_h:
                                    _prearm_hx, _prearm_hy = _junc_xy_h
                            except Exception:
                                pass
                        _mark_detection_point(
                            inter_id, veh_id, _prearm_hx, _prearm_hy,
                            time, f"coord-prearm-harmony/{COORDINATION_ALGO}"
                        )
                        if LOG_CORRIDOR:
                            _vprint(
                                f"[CORRIDOR {COORDINATION_ALGO}] HARMONY Pre-arm FIRED "
                                f"jct={inter_id} bus={veh_id} "
                                f"ETA_in={eta_t - time:.1f}s lead={lead_s:.0f}s"
                            )
                del self._pre_requests[inter_id]

    # ------------------------------------------------------------------
    def _check_wave_complete(self, time: float):
        """
        Lift the corridor wave ban once all pre-requests for the current wave
        have been resolved (fired or expired) AND every pre-armed junction has
        cleared its coordinated bus phase (bus_request is None).

        Also expires a wave that has been running for > 2 × PRE_REQ_TIMEOUT_S
        as a safety net against buses that never arrive.
        """
        if not self._wave_active:
            return

        # Safety expiry
        # (we store wave start time lazily — use issued_t of the last stale check)
        # Simple heuristic: if no pre_requests remain and all served junctions
        # have cleared their bus_request, the wave is done.
        pending = bool(self._pre_requests)
        any_coord_pending = any(
            getattr(self._ctrl_map.get(iid), 'bus_request', None) is not None
            and getattr(self._ctrl_map.get(iid), '_coord_sourced_request', False)
            for iid in self._wave_served_ids
            if iid != self._wave_origin
        )
        # Also check HARMONY intersections: wave is pending while _harmony_prearm is set
        any_harmony_pending = any(
            getattr(self._ic_map.get(iid), '_harmony_prearm', None) is not None
            for iid in self._wave_served_ids
            if iid != self._wave_origin
        )

        if not pending and not any_coord_pending and not any_harmony_pending:
            self._wave_active     = False
            self._wave_veh_id     = -1
            self._wave_origin     = -1
            self._wave_served_ids = set()
            if LOG_CORRIDOR:
                _vprint(
                    f"[CORRIDOR WAVE] t={time:.1f} WAVE COMPLETE — "
                    f"independent TSP ban fully lifted for all corridor junctions"
                )
            _record_wave_event(
                time, self.name, "wave_complete",
                source_jct=-1,
                target_jct=-1,
                veh_id=-1,
            )

    # ------------------------------------------------------------------
    def step(self, time: float, timeSta: float):
        """Called every simulation step from AAPIPostManage."""
        if not self._ctrl_map and not self._ic_map:
            return

        # Process Kalman pre-green requests first (works for both GB and HARMONY modes)
        if COORDINATED_TSP:
            self._process_pre_requests(time, timeSta)
            self._expire_fired_prearms(time)
            self._check_wave_complete(time)

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
        _late_n = int(self._prearm_stats.get('late_success', 0) or 0)
        _late_sum = float(self._prearm_stats.get('late_success_delay_s', 0.0) or 0.0)
        _late_avg = (_late_sum / _late_n) if _late_n > 0 else 0.0
        _fired = int(self._prearm_stats.get('fired', 0) or 0)
        _success = int(self._prearm_stats.get('success', 0) or 0)
        _succ_pct = (100.0 * _success / _fired) if _fired > 0 else 0.0
        _q = int(self._algo_diag.get('queued', 0) or 0)
        _sw_n = int(self._algo_diag.get('sw_adj_count', 0) or 0)
        _sw_sum = float(self._algo_diag.get('sw_adj_total_s', 0.0) or 0.0)
        _sw_avg = (_sw_sum / _sw_n) if _sw_n > 0 else 0.0
        _sw_max = float(self._algo_diag.get('sw_adj_max_s', 0.0) or 0.0)
        _adp_n = int(self._algo_diag.get('adaptive_fire_count', 0) or 0)
        _adp_dyn = int(self._algo_diag.get('adaptive_dynamic_count', 0) or 0)
        _adp_sum = float(self._algo_diag.get('adaptive_lead_total_s', 0.0) or 0.0)
        _adp_avg = (_adp_sum / _adp_n) if _adp_n > 0 else 0.0
        _adp_min = float(self._algo_diag.get('adaptive_lead_min_s', 1e9) or 1e9)
        _adp_max = float(self._algo_diag.get('adaptive_lead_max_s', 0.0) or 0.0)
        if _adp_n <= 0 or _adp_min >= 1e8:
            _adp_min = 0.0
        return (
            f"CorridorCoordinator group={self.name} "
            f"members={self.inter_ids} syncs={self._sync_count} "
            f"algo={COORDINATION_ALGO} "
            f"pre_arms_issued={self._pre_arm_count} "
            f"pre_arms_pending={len(self._pre_requests)} "
            f"fired={self._prearm_stats.get('fired', 0)} "
            f"success={self._prearm_stats.get('success', 0)} "
            f"success_pct={_succ_pct:.1f}% "
            f"missed={self._prearm_stats.get('missed', 0)} "
            f"expired={self._prearm_stats.get('expired', 0)} "
            f"discarded={self._prearm_stats.get('discarded', 0)} "
            f"late_success={_late_n} "
            f"late_success_delay_s={_late_sum:.1f} "
            f"avg_late_success_delay_s={_late_avg:.1f} "
            f"sw_adj={_sw_n}/{_q} sw_adj_avg_s={_sw_avg:.1f} sw_adj_max_s={_sw_max:.1f} "
            f"adp_dynamic={_adp_dyn}/{_adp_n} adp_lead_avg_s={_adp_avg:.1f} "
            f"adp_lead_min_s={_adp_min:.1f} adp_lead_max_s={_adp_max:.1f}"
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

        self.BusPhase         = config.get("BusPhase", 2)

        # BusPhaseDuration — use config value if present, otherwise discover
        # from Aimsun live plan.  Allows minimal configs with just IntersectionID.
        _bpd = config.get("BusPhaseDuration")
        if _bpd is None:
            try:
                _bpd = GetPhaseDuration(self.id, self.BusPhase, 0.0)
                if not _bpd or _bpd <= 0:
                    _bpd = 30.0
            except Exception:
                _bpd = 30.0
        self.BusPhaseDuration = float(_bpd)

        self.BusDet           = config.get("BusDet", [])
        self.main_sections = config.get('MainSections', [])
        self.side_sections = config.get('SideSections', [])
        self.call_sections = config.get(
            'call_sections',
            config.get('BusCallDetectors',
                    config.get('BusDet', []))
        )

        # These three fields are optional — minimal configs may omit them.
        # Default to empty so downstream code sees a consistent type (list/dict).
        self.UpDetList        = config.get("UpDetList", [])
        self.SignalGroupIDList = config.get("SignalGroupIDList", [])
        self.PhaseIndex       = config.get("PhaseIndex", {})
        self.VehLength        = config.get("VehLength", 4.5)
        self.DetLength        = config.get("DetLength", 5)
        self.JamDensity       = config.get("JamDensity", 200)
        self.SaturationDensity= config.get("SaturationDensity", 35)
        self.SaturationFlow   = config.get("SaturationFlow", 1800)
        self.GE_lower_bound   = config.get("GE_lower_bound", 0)
        self.GE_upper_bound   = config.get("GE_upper_bound", 20)
        self.BP_lower_bound   = config.get("BP_lower_bound", 5)
        self.BP_upper_bound   = config.get("BP_upper_bound", 60)
                # === TSP COOLDOWN (prevents spam) ===
        self.last_tsp_action_time = 0.0          # ← ADD THIS
        self.tsp_cooldown_seconds = 60.0         # 60 s = one full cycle on most plans
        # Per-bus approach detection debounce: {bus_id: last_detection_record_t}
        # Prevents per-step recording inflating skip/detection counts.
        # Reset when a bus leaves the zone (zone_exit) or after 120 s.
        self._approach_det_t: dict = {}   # bus_id -> sim_time of last stat record
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
        

        # ── URTSP config — read from config dict or use defaults ──────
        u = URTSP_DEFAULTS
        self.urtsp_ge_extension      = min(config.get("GE_extension", u["GE_extension"]), MAX_GE_EXTENSION_S)
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

        # ── Corridor coordination back-reference (HARMONY mode) ──────────
        # Set by CorridorCoordinator.__init__ when CONTROL_MODE == "HARMONY".
        # None when this intersection is not part of a coordinated group.
        self._corridor_coord    = None
        # Pre-arm request fired by coordinator: (veh_id, eta_t, issued_t).
        # When set, check_bus_priority applies TSP immediately without waiting
        # for local detector presence (Kalman ETA replaces BusSpeed-based ETA).
        self._harmony_prearm    = None

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

        # ── GROUP_BASED sub-controller (also used for DYNAOPAC) ──────────
        self.gb = None
        if CONTROL_MODE in ("GROUP_BASED", "GROUP_BASED_URTSP", "GROUP_BASED_HARMONY", "DYNAOPAC"):
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
                        'bus_exit_det':    config.get('BusExitDetectors', []),
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
                    # DYNAOPAC uses harmony TSP + corridor coordination
                    # (coordination algo is chosen by COORDINATION_ALGO / COORDINATED_TSP)
                    "DYNAOPAC":            "harmony",
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
                _release_focus(time, "urtsp_ge_done")
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
                _release_focus(time, "urtsp_ins_done")
            return

        # ── IDLE: scan call detectors ─────────────────────────────────
        veh_id, line_id, det_id, pos = self._scan_urtsp_call(pt_vehicles)
        if veh_id < 0:
            return

        # ── Global bus focus gate ─────────────────────────────────────
        if _is_focus_blocked(veh_id, self.id, time):
            if LOG_URTSP:
                _vprint(
                    f"[BUS_FOCUS] t={time:.1f} inter={self.id} "
                    f"v={veh_id} SUPPRESSED — focus bus={_focus_bus_id}")
            _mark_detection_point(self.id, veh_id, 0.0, 0.0,
                                  time, "focus_suppress")
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
            if veh_id and veh_id > 0:
                _acquire_focus(veh_id, self.id, time)
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
            if veh_id and veh_id > 0:
                _acquire_focus(veh_id, self.id, time)
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

        # ── Cycle-recovery state (GE only) ────────────────────────────────────
        # When a green extension of X seconds is granted the cycle is "in debt".
        # After the GE ends, remaining phases are shortened proportionally so the
        # cycle re-aligns with its nominal start offset as quickly as possible.
        # _ge_debt_s  : seconds still owed (decremented as phases absorb it)
        # _ge_opt_GE  : the extension that was granted (for logging)
        self._ge_debt_s  = 0.0
        self._ge_opt_GE  = 0.0

        # _nominal_phase_durations: lazily-populated on first GE.
        # Stores the ORIGINAL plan durations so cycle recovery always trims
        # relative to the base (not relative to a previously-trimmed value).
        # Without this, repeated GEs compound trimming → permanent short greens.
        self._nominal_phase_durations: dict = {}

        # _phases_to_restore: set after trimming — {phase: nominal_dur}.
        # Restored to their nominals when BusPhase next becomes current
        # (i.e. start of the next signal cycle), ensuring trimmed durations
        # only apply for ONE cycle.
        self._phases_to_restore: dict = {}
        self._restore_fired_this_cycle: bool = False

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
        self._topo_fallback_main = False  # True = main_secs came from topology, not detectors
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
                    self._topo_fallback_main = True
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

    def _classify_sections_by_geometry(self, section_ids):
        """
        Split approach sections into main (corridor, N-S) and side (cross-street, E-W)
        using their geometric orientation relative to the junction centroid.

        Used when no UpDetList detector sections are configured — the only reliable AAPI
        way to distinguish Logan Road (N-S) approaches from cross-street (E-W) approaches.

        Returns (main_secs, side_secs) as lists of int section IDs.
        Falls back to (all_sections, []) if coordinates are unavailable.
        """
        jct_xy = self._get_junction_xy()
        if jct_xy is None:
            return list(section_ids), []

        jx, jy = float(jct_xy[0]), float(jct_xy[1])
        # Try alternate XY attribute names used across Aimsun versions
        _XY_ATTRS = [
            ('xSection',     'ySection'),
            ('xSectionTo',   'ySectionTo'),
            ('xcoordTo',     'ycoordTo'),
            ('xTo',          'yTo'),
            ('xDestination', 'yDestination'),
            ('xcoord',       'ycoord'),
            ('x',            'y'),
        ]

        main_secs, side_secs, unknown_secs = [], [], []
        for sec_id in section_ids:
            try:
                si = AKIInfNetGetSectionANGInf(int(sec_id))
                if getattr(si, 'report', -1) < 0:
                    unknown_secs.append(sec_id)
                    continue
                sx, sy = None, None
                for xa, ya in _XY_ATTRS:
                    _x = getattr(si, xa, None)
                    _y = getattr(si, ya, None)
                    if _x is not None and _y is not None:
                        try:
                            _xf, _yf = float(_x), float(_y)
                            if not (_xf == 0.0 and _yf == 0.0):
                                sx, sy = _xf, _yf
                                break
                        except (TypeError, ValueError):
                            pass
                if sx is None:
                    unknown_secs.append(sec_id)
                    continue
                # Direction vector: from junction centroid → section coordinate.
                # For an incoming section, this vector points AWAY from the junction
                # towards the section's upstream end.
                dx = abs(sx - jx)
                dy = abs(sy - jy)
                if dx < 1.0 and dy < 1.0:
                    # Section centroid essentially at junction — can't determine direction
                    unknown_secs.append(sec_id)
                    continue
                # N-S approach: |dy| dominates; E-W approach: |dx| dominates
                if dy >= dx:
                    main_secs.append(sec_id)   # N-S → Logan Road main corridor
                else:
                    side_secs.append(sec_id)   # E-W → cross-street
            except Exception:
                unknown_secs.append(sec_id)

        # Unknowns are conservatively assigned to main so they use partial stats
        main_secs.extend(unknown_secs)
        if LOG_SIDE_DISC:
            log_to_file(
                f"[SIDE_DISC] inter={self.id} geometry-split: "
                f"main={main_secs} side={side_secs} unknown_kept_main={unknown_secs}"
            )
        return main_secs, side_secs

    def _auto_discover_side_sections(self):
        """
        Discover side-street approach sections feeding into this junction node.
        Uses AKIInfNetGetNbTurnsInNode / AKIInfNetGetOriginSectionInTurn to enumerate
        all incoming sections at the junction, then excludes the main corridor sections
        (those that contain upstream detectors).

        CACHING POLICY:
          • Cache the result only when the AAPI scan itself succeeded (n_turns queried).
          • When the scan fails (exception) or is skipped (_topo_fallback_main), return []
            WITHOUT caching so the next collect_delay call retries.  This prevents a
            transient Aimsun API unavailability at startup from permanently locking in
            an empty side-section set for the whole simulation.
        """
        if hasattr(self, '_cached_side_sections'):
            return self._cached_side_sections

        main_sec_ids = set(self._derive_sections_from_detectors())
        # When all configured detectors are invalid, _derive_sections_from_detectors()
        # returns [].  If incoming_sections was populated from real detectors, use it
        # as the exclusion set.  But if it was populated by topology fallback (no
        # detectors at all), using it would exclude ALL sections → 0 side sections.
        # In that case, use Stats topology discovery which has PyANGKernel info
        # about section names/directions to correctly identify side streets.
        if not main_sec_ids and getattr(self, 'incoming_sections', None):
            if getattr(self, '_topo_fallback_main', False):
                # No detector sections — all incoming_sections came from topology.
                # Use geometric orientation (N-S vs E-W) to split main from side.
                # This is reliable for Logan Road which runs roughly N-S.
                _geo_main, _geo_side = self._classify_sections_by_geometry(
                    self.incoming_sections)
                if _geo_side:
                    # Geometry split succeeded: cache result and refine main sections
                    self._cached_side_sections = _geo_side
                    _inter_d = (self.stats._inter.get(self.id, {})
                                if self.stats else {})
                    if not _inter_d.get('main_sections'):
                        _inter_d['main_sections'] = _geo_main
                        self.config['MainSections'] = _geo_main
                        # Narrow incoming_sections to corridor-only (N-S) sections
                        self.incoming_sections = _geo_main
                        self._topo_fallback_main = False  # geometry split is reliable
                    if LOG_SIDE_DISC:
                        log_to_file(
                            f"[SIDE_DISC] inter={self.id} topo-fallback: "
                            f"geometry resolved main={_geo_main} side={_geo_side}")
                    return _geo_side
                # Geometry couldn't split (coordinates unavailable) — still uncached
                if LOG_SIDE_DISC:
                    log_to_file(
                        f"[SIDE_DISC] inter={self.id} topo-fallback: "
                        f"geometry also failed — treating all incoming as main")
                return []   # intentionally uncached — retry on next call
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
                    f"[SIDE_DISC] inter={self.id} turn-based scan error: {ex} — "
                    f"NOT caching empty result (will retry next call)")
            # AAPI call failed — do NOT cache, allow retry
            return []

        # AAPI scan succeeded (even if n_turns == 0, that is a valid answer).
        # Cache the result so subsequent calls skip the AAPI overhead.
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

    def _compute_side_delay_penalty(self, extra_red, _suppress_log=False):
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
        if not _suppress_log:
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

        xs, ys = [], []

        # First try incoming_sections (detector-based approach sections)
        for sec_id in self.incoming_sections:
            try:
                si = AKIInfNetGetSectionANGInf(sec_id)
                if si.report >= 0:
                    _xy = _extract_xy_from_section_info(si)
                    if _xy is not None:
                        xs.append(_xy[0])
                        ys.append(_xy[1])
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
                            _xy = _extract_xy_from_section_info(si)
                            if _xy is not None:
                                xs.append(_xy[0])
                                ys.append(_xy[1])
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

        _model_xy = _resolve_junction_xy_from_model(self.node_id, self.incoming_sections)
        if _model_xy is not None:
            self._junction_xy = _model_xy
            log_to_file(
                f"[JUNC_XY] IC inter={self.id} resolved via model "
                f"-> ({_model_xy[0]:.1f}, {_model_xy[1]:.1f})"
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
        if isinstance(getattr(self, '_bus_eta', None), dict):
            self._bus_eta.clear()
        else:
            self._bus_eta = {}

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

        def _hit(veh_id, speed_kph, hit_x=None, hit_y=None):
            speed_ms = max(speed_kph / 3.6, 0.5)
            self.BusPresence[0][0]    = 1
            self.BusSpeed[0][0]       = speed_ms
            self.last_detected_bus_id = veh_id
            # Compute actual distance to junction centroid and store in _bus_eta
            # so check_bus_priority can compute a correct ETA (previously it fell
            # back to DetDistance[0][0]=50m, wildly underestimating when the bus
            # is detected 200-500m away — causing "always natural green").
            if not isinstance(getattr(self, '_bus_eta', None), dict):
                self._bus_eta = {}
            if jx is not None and hit_x is not None:
                _dist_m = ((float(hit_x) - jx) ** 2 + (float(hit_y) - jy) ** 2) ** 0.5
            else:
                _dist_m = float(self.config.get("DetDistance", [[50.0]])[0][0])
            _eta_s = _dist_m / speed_ms
            self._bus_eta[0] = (veh_id, _eta_s, _dist_m, speed_ms)
            # Record the bus passage in stats (works for transit-link buses that
            # never appear on regular approach sections)
            try:
                self.stats.record_pt_bus_detection(self.id, veh_id, time)
            except Exception:
                pass
            # Detection-point marker: use vehicle XY, fall back to junction
            # centroid, then (0,0) so the CSV is always written.
            _mx = hit_x if hit_x is not None else (jx if jx is not None else 0.0)
            _my = hit_y if hit_y is not None else (jy if jy is not None else 0.0)
            _mark_detection_point(self.id, veh_id, _mx, _my, time, "IC-detect")

        # ── Tier 0: position-tracker zone-presence supplement ───────────────
        # _track_all_bus_positions maintains _tracking_zone_presence with buses
        # confirmed inside this junction's detection zone at the last 5-second
        # interval.  Buses on transit-link sections (report<0) won't appear in
        # the PT API scan below, so this Tier 0 fills that gap.
        for _tz_vid, (_tz_bx, _tz_by, _tz_spd) in list(
                _tracking_zone_presence.get(self.id, {}).items()):
            if _tz_vid not in seen:
                seen.add(_tz_vid)
                _hit(_tz_vid, _tz_spd, _tz_bx, _tz_by)

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
                            _hit(veh_id, inf.CurrentSpeed,
                                 float(inf.xCurrentPos), float(inf.yCurrentPos))
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
                            _hit(veh_id, inf.CurrentSpeed,
                                 float(getattr(inf, 'xCurrentPos', 0.0)),
                                 float(getattr(inf, 'yCurrentPos', 0.0)))
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
        # Maximum plausible approach flow: 1.5× saturation (handles multi-turn aggregation)
        _max_flow = max(self.SaturationFlow * 1.5, 3600.0)
        for i in range(len(self.UpDetList)):
            for j in range(len(self.UpDetList[i])):
                red_duration = time - self.RedStartTimeList[i][j]
                if red_duration > 0:
                    self.RedDurationList[i][j] = red_duration
                    # Clamp red_duration to at least 5 s before converting count→flow
                    # to prevent explosion when the sim first enters red on the last step.
                    _red_dur_clamped = max(red_duration, 5.0)

                    if self.UpDetCountList[i][j] > 0:
                        # Preferred: aggregated detector count → flow rate
                        flow = self.UpDetCountList[i][j] * 3600.0 / _red_dur_clamped
                        # Safety cap: never exceed 1.5× saturation flow
                        flow = min(flow, _max_flow)
                    else:
                        # Fallback: instantaneous density from live vehicle scan
                        sec_info = det_sec_cache.get((i, j))
                        if sec_info is not None:
                            sec_id, sec_len_m = sec_info
                            try:
                                n_veh = max(int(AKIVehStateGetNbVehiclesSection(sec_id, False)), 0)
                            except Exception:
                                n_veh = 0
                            try:
                                _sec_inf = AKIInfNetGetSectionANGInf(sec_id)
                                n_lanes_sec = max(
                                    int(getattr(_sec_inf, 'nbCentralLanes', 0))
                                    + int(getattr(_sec_inf, 'nbSideLanes', 0)), 1)
                            except Exception:
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

    # ──────────────────────────────────────────────────────────────────────────
    # REWARD_TSP — action-reward based TSP using delay cost-benefit analysis
    # ──────────────────────────────────────────────────────────────────────────
    # Inspired by the MDP framework in Helmstedt & Possingham (2017):
    #   V(s,t) = max_a [ R(s,a) + Σ T_a(s,s')·V(s',t+1) ]
    #
    # Here we use a myopic (one-step lookahead) version:
    #   best_action = argmax_a R(s,a)
    # where R(s,a) = -α·ΔD_bus(a) - β·ΔD_other(a) - γ·ΔD_side(a)
    #
    # Actions evaluated:
    #   NO_ACTION  — do nothing; bus waits for natural green
    #   GE_k       — extend current green by k seconds (if bus phase is active)
    #   INS        — insert bus phase immediately (if bus phase is not active)
    # ──────────────────────────────────────────────────────────────────────────

    def _reward_estimate_no_action(self, time, timeSta, bus_eta_s):
        """Estimate bus delay if no TSP action is taken."""
        cycle = float(self.config.get('CycleTime', 135))
        # Worst-case delay a bus can ever face is one full red phase = cycle - BusPhaseDuration.
        # Use this as a cap so far-away buses (eta >> cycle) don't inflate the estimate.
        _max_delay = max(cycle - float(self.BusPhaseDuration), 0.0)

        current_phase = ECIGetCurrentPhase(self.node_id)
        if current_phase == self.BusPhase:
            # Bus phase is active — how much time remains?
            _ps = ECIGetStartingTimePhase(self.node_id)
            _pd = GetPhaseDuration(self.node_id, current_phase, timeSta)
            _remain = max(0.0, _pd - (time - _ps))
            if bus_eta_s <= _remain:
                return 0.0  # bus makes the natural green
            # Bus misses this green — cap at worst-case one-cycle wait
            raw = bus_eta_s - _remain + _max_delay
            return min(raw, _max_delay)
        else:
            # Compute time until next BusPhase green
            _ps_now = ECIGetStartingTimePhase(self.node_id)
            _elapsed = max(0.0, time - _ps_now)
            _rem_cur = max(0.0,
                GetPhaseDuration(self.node_id, current_phase, timeSta) - _elapsed)
            _time_to_bp = _rem_cur
            try:
                _ci = self.phase_list.index(current_phase)
                _bi = self.phase_list.index(self.BusPhase)
                _n  = len(self.phase_list)
                _steps = (_bi - _ci) % _n
                for _k in range(1, _steps):
                    _ph = self.phase_list[(_ci + _k) % _n]
                    _time_to_bp += GetPhaseDuration(self.node_id, _ph, timeSta)
            except Exception:
                _time_to_bp = cycle
            if bus_eta_s <= _time_to_bp + self.BusPhaseDuration:
                return max(0.0, _time_to_bp - bus_eta_s)
            # Bus misses the next natural green — cap at one full red wait
            return min(_max_delay, max(0.0, _time_to_bp + cycle - bus_eta_s))

    def _reward_objective_snapshot(self, extra_side_red: float = 0.0):
        """
        Snapshot the current objective arrays in passenger-delay units.

        This lets REWARD_TSP compare actions using the same occupancy-weighted
        delay logic as the harmony objective functions.
        """
        other_occ = self._estimated_other_vehicle_occupancy()
        bus_delay_s = max(self._safe_array_sum(self.BusDelay), 0.0)
        other_delay_s = max(self._safe_array_sum(self.OtherDelay), 0.0)
        side_delay_s = 0.0
        if extra_side_red > 1e-6:
            try:
                side_delay_s, _ = self._compute_side_delay_penalty(extra_side_red)
            except Exception:
                side_delay_s = 0.0
        side_delay_s = max(safe_float(side_delay_s), 0.0)
        bus_occ = max(safe_float(self.BusOcc), 0.0)
        return {
            "bus_delay_s": bus_delay_s,
            "other_delay_s": other_delay_s,
            "side_delay_s": side_delay_s,
            "bus_delay_pax_s": bus_delay_s * bus_occ,
            "other_delay_pax_s": other_delay_s * other_occ,
            "side_delay_pax_s": side_delay_s * other_occ,
        }

    def _reward_evaluate_ge(self, ge_s, time, timeSta, bus_eta_s):
        """
        Evaluate a green extension in passenger-delay units.

        Returns (bus_saved_pax_s, other_added_pax_s, side_added_pax_s).
        """
        self.GE_Objective_Function(ge_s, time)
        ge_cost = self._reward_objective_snapshot(extra_side_red=ge_s)

        self.GE_Objective_Function(0.0, time)
        base_cost = self._reward_objective_snapshot(extra_side_red=0.0)

        bus_saved = max(0.0, base_cost["bus_delay_pax_s"] - ge_cost["bus_delay_pax_s"])
        other_increase = max(
            0.0,
            ge_cost["other_delay_pax_s"] - base_cost["other_delay_pax_s"],
        )
        side_delay = max(
            0.0,
            ge_cost["side_delay_pax_s"] - base_cost["side_delay_pax_s"],
        )

        return bus_saved, other_increase, side_delay

    def _reward_evaluate_insertion(self, ins_dur, time, timeSta, bus_eta_s):
        """
        Evaluate a phase insertion in passenger-delay units.

        Returns (bus_saved_pax_s, other_added_pax_s, side_added_pax_s).
        """
        # Bus delay saved: difference between waiting for natural green and insertion
        no_action_bus_delay = self._reward_estimate_no_action(time, timeSta, bus_eta_s)
        baseline_bus_cost = max(0.0, no_action_bus_delay) * max(safe_float(self.BusOcc), 0.0)
        # With insertion, bus gets green immediately — delay is just the ETA
        self.BP_Objective_Function(ins_dur, time)
        action_cost = self._reward_objective_snapshot(extra_side_red=ins_dur + 5.0)
        bus_saved = max(0.0, baseline_bus_cost - action_cost["bus_delay_pax_s"])

        # Other-traffic delay: the interrupted phase loses its remaining green
        other_increase = max(0.0, action_cost["other_delay_pax_s"])
        side_delay = max(0.0, action_cost["side_delay_pax_s"])

        return bus_saved, other_increase, side_delay

    def run_reward_tsp(self, time, timeSta, acycle):
        """REWARD_TSP control mode — action-reward evaluation for TSP decisions.

        When a bus is detected, evaluates all candidate actions (no-action,
        green extensions of various durations, phase insertion) and picks the
        one with the highest reward R = -α·ΔD_bus - β·ΔD_other - γ·ΔD_side.
        """
        # Phase restoration (same as HARMONY — reuse existing method)
        self.restore_phase_if_needed(time, timeSta, acycle)

        # Cooldown guard after a grant
        if time - self.last_tsp_action_time < self.tsp_cooldown_seconds:
            return

        # Short re-evaluation debounce after a NO_ACTION decision — avoids
        # running the full reward calculation on every simulation step when
        # nothing is changing (the 30 s stats debounce only affects counters).
        if time < getattr(self, '_reward_no_action_until', -1.0):
            return

        # Already active — don't re-evaluate
        if self.flag != 0:
            return
        if getattr(self, '_tsp_cycle_grant_until', -1.0) > time:
            return

        current_phase = ECIGetCurrentPhase(self.node_id)
        if current_phase < 0:
            return

        # ── Corridor pre-arm check (REWARD_TSP coordination) ─────────────────
        _prearm = getattr(self, '_harmony_prearm', None)
        if _prearm is not None and self.TSPStrategy == 0:
            _pa_veh, _pa_eta_t, _pa_issued_t = _prearm
            _eta_from_now = _pa_eta_t - time
            if _eta_from_now < -20.0 or time - _pa_issued_t > 120.0:
                self._harmony_prearm = None
            elif 0.0 <= _eta_from_now <= getattr(self, '_eta_max_s', 90.0):
                self._harmony_prearm = None
                # Use reward evaluation with the prearm ETA as the bus ETA
                self._run_reward_tsp_evaluate(
                    time, timeSta, acycle, current_phase,
                    _eta_from_now, _pa_veh)
                return

        # ── Bus detection check ───────────────────────────────────────────────
        _n_det_slots = max(len(self.BusDet), 1)
        bus_detected = False
        bus_speed = 0.0
        det_idx = 0
        for i in range(_n_det_slots):
            if self.BusSpeed[0][i] > 0:
                bus_speed = self.BusSpeed[0][i]
                det_idx = i
                bus_detected = True
                break

        if not bus_detected:
            return

        # ── Approach debounce for detection stats (30 s per bus approach) ───────
        # TSP *actions* still fire when warranted (checked below); only stat
        # recording is suppressed within the debounce window.
        _det_vid_chk = self.last_detected_bus_id
        _reward_stats_ok = True
        if _det_vid_chk and _det_vid_chk > 0:
            _last_rec = self._approach_det_t.get(_det_vid_chk, -999.0)
            if (time - _last_rec) < 30.0:
                _reward_stats_ok = False   # suppress stat recording this step
            else:
                self._approach_det_t[_det_vid_chk] = time

        # ── Global bus focus gate ─────────────────────────────────────────────
        _det_vid = self.last_detected_bus_id
        if _det_vid and _det_vid > 0 and _is_focus_blocked(_det_vid, self.id, time):
            if LOG_REWARD:
                _vprint(
                    f"[REWARD_TSP] t={time:.1f} inter={self.id} "
                    f"v={_det_vid} focus_suppress — focus bus={_focus_bus_id}")
            _mark_detection_point(self.id, _det_vid, 0.0, 0.0, time, "focus_suppress")
            self.stats.record_tsp_event(self.id, 'detection')
            return

        # ── Compute bus ETA ───────────────────────────────────────────────────
        eta_info = getattr(self, '_bus_eta', {}).get(det_idx)
        _det_dist_fb = (
            self.config['DetDistance'][0][det_idx]
            if self.config.get('DetDistance') and len(self.config['DetDistance']) > 0
               and det_idx < len(self.config['DetDistance'][0])
            else 200.0
        )
        bus_eta_s = eta_info[1] if eta_info else (_det_dist_fb / bus_speed)

        # Skip evaluation when bus is too far away to benefit from TSP.
        # 2 × cycle_time is the threshold: beyond that the bus will encounter
        # natural greens and the reward estimate is too noisy to be useful.
        _cycle = float(self.config.get('CycleTime', 135))
        if bus_eta_s > 2.0 * _cycle:
            self._reward_no_action_until = time + 5.0
            return

        self._run_reward_tsp_evaluate(
            time, timeSta, acycle, current_phase, bus_eta_s, _det_vid,
            stats_ok=_reward_stats_ok)

    def _run_reward_tsp_evaluate(self, time, timeSta, acycle,
                                  current_phase, bus_eta_s, veh_id,
                                  stats_ok: bool = True):
        if veh_id and veh_id > 0 and _is_focus_blocked(veh_id, self.id, time):
            if LOG_REWARD:
                _vprint(
                    f"[REWARD_TSP] t={time:.1f} inter={self.id} "
                    f"v={veh_id} focus_suppress — focus bus={_focus_bus_id}")
            _mark_detection_point(self.id, veh_id, 0.0, 0.0, time, "focus_suppress")
            if stats_ok:
                self.stats.record_tsp_event(self.id, 'detection')
            return

        # Action 0: NO_ACTION
        no_action_bus_delay = self._reward_estimate_no_action(time, timeSta, bus_eta_s)
        no_action_bus_cost = max(0.0, no_action_bus_delay) * max(safe_float(self.BusOcc), 0.0)
        reward_no_action = -REWARD_ALPHA * no_action_bus_cost

        best_action = "NO_ACTION"
        best_reward = reward_no_action
        best_ge = 0.0

        log_to_file(
            f"[REWARD_TSP] inter={self.id} t={time:.1f} bus={veh_id} "
            f"eta={bus_eta_s:.1f}s phase={current_phase} "
            f"R(NO_ACTION)={reward_no_action:.1f}")

        if current_phase == self.BusPhase:
            # ── Evaluate GE candidates ────────────────────────────────────
            _ps = ECIGetStartingTimePhase(self.node_id)
            _pd = GetPhaseDuration(self.node_id, current_phase, timeSta)
            _remain = max(0.0, _pd - (time - _ps))
            next_red = time + _remain

            for ge_s in REWARD_GE_CANDIDATES:
                if ge_s > MAX_GE_EXTENSION_S:
                    continue
                # NOTE: No hard recoverable cap here — the reward function already
                # penalises cycle expansion via other_inc (delay on cross traffic).
                # Capping by recoverable headroom was blocking all GE > 5 s when
                # phases are short (6–8 s nominal), forcing avg_extension = 5.0 s.

                bus_saved, other_inc, side_inc = self._reward_evaluate_ge(
                    ge_s, time, timeSta, bus_eta_s)
                reward = (REWARD_ALPHA * bus_saved
                          - REWARD_BETA * other_inc
                          - REWARD_GAMMA * side_inc)

                log_to_file(
                    f"[REWARD_TSP] inter={self.id} "
                    f"R(GE_{ge_s:.0f})={reward:.1f} "
                    f"bus_saved={bus_saved:.1f} other={other_inc:.1f} "
                    f"side={side_inc:.1f}")

                if reward > best_reward:
                    best_reward = reward
                    best_action = f"GE_{ge_s:.0f}"
                    best_ge = ge_s
        else:
            # ── Evaluate INSERTION ────────────────────────────────────────
            ins_dur = min(float(self.BP_upper_bound),
                          max(float(self.BP_lower_bound), bus_eta_s + 5.0))
            bus_saved, other_inc, side_inc = self._reward_evaluate_insertion(
                ins_dur, time, timeSta, bus_eta_s)
            reward_ins = (REWARD_ALPHA * bus_saved
                          - REWARD_BETA * other_inc
                          - REWARD_GAMMA * side_inc)

            log_to_file(
                f"[REWARD_TSP] inter={self.id} "
                f"R(INS_{ins_dur:.0f})={reward_ins:.1f} "
                f"bus_saved={bus_saved:.1f} other={other_inc:.1f} "
                f"side={side_inc:.1f}")

            if reward_ins > best_reward:
                best_reward = reward_ins
                best_action = "INS"
                best_ge = ins_dur

        # ── Record detection (debounce-guarded) ──────────────────────────────
        if stats_ok:
            self.stats.record_tsp_event(self.id, 'detection')

        # ── Execute best action ───────────────────────────────────────────────
        if best_action == "NO_ACTION":
            # Debounce: suppress re-evaluation for 5 s so we don't flood the
            # log with identical NO_ACTION decisions on every simulation step.
            self._reward_no_action_until = time + 5.0
            if stats_ok:
                self.stats.record_tsp_skip(self.id, 'reward_no_action')
            log_to_file(
                f"[REWARD_TSP] inter={self.id} t={time:.1f} bus={veh_id} "
                f"eta={bus_eta_s:.1f}s DECISION=NO_ACTION R={best_reward:.1f} "
                f"(cost to others outweighs bus benefit)")
            # Still propagate corridor coordination
            if self._corridor_coord is not None and COORDINATED_TSP:
                try:
                    self._corridor_coord.notify_bus_granted(
                        veh_id, self.id, time, None)
                except Exception:
                    pass
            return

        if best_action.startswith("GE"):
            # Apply green extension
            _ps = ECIGetStartingTimePhase(self.node_id)
            _pd = GetPhaseDuration(self.node_id, current_phase, timeSta)
            remain = _pd - (time - _ps)
            ECIChangeTimingPhase(self.node_id, current_phase,
                                 self.BusPhaseDuration + best_ge, timeSta)
            self.TimeToTerminateBusPhase = time + remain + best_ge
            self.TSPStrategy  = 1
            self.flag         = 1
            self.TSPActiveTime = time + best_ge + 30
            self._tsp_cycle_grant_until = time + self.config.get('CycleTime', 135)
            self.last_tsp_action_time   = time
            self._ge_debt_s = best_ge
            self._ge_opt_GE = best_ge
            _ge_events.append((time, self.id, best_ge, best_reward))
            self.highlight_bus(veh_id)
            self.stats.record_tsp_event(self.id, 'extension')
            self.stats.record_tsp_extension_duration(self.id, best_ge)
            if veh_id and veh_id > 0:
                _acquire_focus(veh_id, self.id, time)
            if self._corridor_coord is not None and COORDINATED_TSP:
                try:
                    self._corridor_coord.notify_bus_granted(
                        veh_id, self.id, time, None)
                except Exception:
                    pass
            log_to_file(
                f"[REWARD_TSP] inter={self.id} t={time:.1f} bus={veh_id} "
                f"eta={bus_eta_s:.1f}s DECISION={best_action} GE={best_ge:.1f}s "
                f"R={best_reward:.1f}")

        elif best_action == "INS":
            # Apply phase insertion — first set the BusPhase duration so
            # Aimsun holds it for opt_BP seconds, then force the switch.
            self.previous_phase  = current_phase
            self.BusPhaseEndTime = time + best_ge
            ECIChangeTimingPhase(self.id, self.BusPhase, best_ge, timeSta)
            ECIChangeDirectPhase(self.id, self.BusPhase, timeSta, time, acycle, 0)
            self.TSPStrategy  = 2
            self.flag         = 2
            self.TSPActiveTime = time + best_ge + 30
            self._ge_debt_s   = best_ge   # spread cost across remaining phases
            self._tsp_cycle_grant_until = time + self.config.get('CycleTime', 135)
            self.last_tsp_action_time   = time
            self.highlight_bus(veh_id)
            self.stats.record_tsp_event(self.id, 'insertion')
            self.stats.record_tsp_insertion_duration(self.id, best_ge)
            self.stats.record_tsp_insertion_wait(self.id, max(0.0, bus_eta_s))
            if veh_id and veh_id > 0:
                _acquire_focus(veh_id, self.id, time)
            if self._corridor_coord is not None and COORDINATED_TSP:
                try:
                    self._corridor_coord.notify_bus_granted(
                        veh_id, self.id, time, None)
                except Exception:
                    pass
            log_to_file(
                f"[REWARD_TSP] inter={self.id} t={time:.1f} bus={veh_id} "
                f"eta={bus_eta_s:.1f}s DECISION=INS BP={best_ge:.1f}s "
                f"R={best_reward:.1f}")

    def _reward_get_recoverable(self, current_phase, timeSta):
        """Compute recoverable headroom from upcoming phases (same as HARMONY cap logic)."""
        _min_floor = float(self.config.get('MinGreen', 5.0))
        _max_trim_frac = 0.50
        _phase_list = getattr(self, 'phase_list', [])
        if not _phase_list or current_phase not in _phase_list:
            return 999.0
        _ci = _phase_list.index(current_phase)
        _n = len(_phase_list)
        _upcoming = [_phase_list[(_ci + _k) % _n] for _k in range(1, _n)]
        _upcoming = [p for p in _upcoming if p != self.BusPhase and p != current_phase]
        _recoverable = 0.0
        for _ph in _upcoming:
            _nom = self._nominal_phase_durations.get(_ph)
            if _nom is None:
                try:
                    _nom = GetPhaseDuration(self.node_id, _ph, timeSta)
                except Exception:
                    _nom = 15.0
                if not _nom or _nom <= 0:
                    _nom = 15.0
            _nom = max(float(_nom), _min_floor)
            _hr = max(0.0, _nom - _min_floor)
            _hr = min(_hr, _nom * _max_trim_frac)
            _recoverable += _hr
        return _recoverable

    def run_normal(self, time, timeSta, acycle):
        """Passive baseline — data collection only, no signal changes.

        Still records bus detections (mark_detection_point + stats) so that
        NORMAL mode produces detection counts comparable to HARMONY, and the
        batch results show how many buses were 'seen' without TSP action.
        """
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

        # ── Passive detection recording ───────────────────────────────────────
        # Track which detector slots are newly presenting a bus this step.
        # Use a set on self to avoid counting the same bus twice per approach.
        if not hasattr(self, '_normal_det_active'):
            self._normal_det_active = set()   # slots currently presenting

        _newly_detected = False
        for i, det in enumerate(self.BusDet):
            _presence = self.BusPresence[0][i] if i < len(self.BusPresence[0]) else 0
            _counter  = AKIDetGetCounterCyclebyId(det, busTypePos)
            _active   = (_presence > 0) or (_counter > 0)
            if _active and i not in self._normal_det_active:
                # New bus arrival at this detector slot
                self._normal_det_active.add(i)
                _newly_detected = True
                _vid = int(self.last_detected_bus_id) if hasattr(self, 'last_detected_bus_id') else -1
                _mark_detection_point(
                    junction_id=self.id,
                    veh_id=_vid,
                    x=0.0, y=0.0,
                    sim_time=time,
                    tier="NORMAL-detect",
                )
                self.stats.record_tsp_event(self.id, 'detection')
                # Check if the bus phase is currently green (natural green)
                _is_natural = False
                try:
                    _cur_ph = ECIGetCurrentPhase(self.id)
                    if _cur_ph == self.BusPhase:
                        _is_natural = True
                except Exception:
                    pass
                if _is_natural:
                    self.stats.record_tsp_skip(self.id, 'natural_green')
                else:
                    self.stats.record_tsp_skip(self.id, 'no_action')
                try:
                    self.stats.record_pt_bus_detection(self.id, _vid, time)
                except Exception:
                    pass
            elif not _active and i in self._normal_det_active:
                self._normal_det_active.discard(i)

        # Periodic diagnostic — log det counters + BusPresence every 5 minutes
        _diag_t = int(time) // 300
        if _diag_t != getattr(self, '_run_normal_diag_t', -1):
            self._run_normal_diag_t = _diag_t
            counters = [AKIDetGetCounterCyclebyId(d, busTypePos) for d in self.BusDet]
            presence = self.BusPresence[0].tolist()
            log_to_file(
                f"[NORMAL DIAG] t={time:.0f}s inter={self.id} "
                f"det_counters={counters} BusPresence={presence} "
                f"busCallActive={busCallActive} newly_det={_newly_detected}")

    def _apply_cycle_recovery(self, timeSta: float):
        """
        Proportionally shorten the remaining phases in the current cycle to
        recover the time stolen by a green extension.

        Algorithm
        ---------
        1. Build the ordered list of phases AFTER the current one in this cycle.
        2. For each candidate phase (skip BusPhase — already served):
               nominal  = ECIGetDurationsPhase(phase)
               min_dur  = config MinGreen or 5 s hard floor
               headroom = nominal - min_dur   (how much can be trimmed)
               fraction = headroom / total_headroom_remaining
               trim     = min(fraction * debt, headroom)
               new_dur  = nominal - trim
               ECIChangeTimingPhase(phase, new_dur, ...)
        3. Accumulate actual trimmed; update _ge_debt_s with any residual
           (can't always recover 100% if minimums bind).

        Both GE (flag==1) and phase insertion (flag==2) trigger this.
        For insertion, _ge_debt_s is set to opt_BP at insertion time so the
        cost is spread over remaining phases when the insertion ends.
        """
        if self._ge_debt_s <= 0.5:
            self._ge_debt_s = 0.0
            return

        current_phase = ECIGetCurrentPhase(self.node_id)
        phase_list    = getattr(self, 'phase_list', [])
        if not phase_list or current_phase not in phase_list:
            self._ge_debt_s = 0.0
            return

        # Build ordered list of phases still to run this cycle (after current)
        ci = phase_list.index(current_phase)
        n  = len(phase_list)
        upcoming = [phase_list[(ci + k) % n] for k in range(1, n)]
        # Exclude BusPhase (just completed) and current phase
        upcoming = [p for p in upcoming if p != self.BusPhase and p != current_phase]

        if not upcoming:
            self._ge_debt_s = 0.0
            return

        # Gather nominals (always from stored originals, never from a trimmed plan)
        # and minimum floors.
        min_floor   = float(self.config.get('MinGreen', 5.0))
        # Safety cap: never trim more than 50 % of any single phase's nominal.
        max_trim_frac = 0.50
        nominals  = {}
        headrooms = {}
        for ph in upcoming:
            # Prefer the stored nominal from before any trimming happened.
            nom = self._nominal_phase_durations.get(ph)
            if nom is None:
                try:
                    nom = GetPhaseDuration(self.node_id, ph, timeSta)
                except Exception:
                    nom = 15.0
                if not nom or nom <= 0:
                    nom = 15.0
                # Lock in the original value so subsequent GEs don't compound.
                self._nominal_phase_durations[ph] = float(nom)
            nom = max(float(nom), min_floor)
            hr  = max(0.0, nom - min_floor)
            # Apply 50 % cap
            hr  = min(hr, nom * max_trim_frac)
            nominals[ph]  = nom
            headrooms[ph] = hr

        total_headroom = sum(headrooms.values())
        if total_headroom < 0.5:
            # Phases already at minimum — can't recover
            self._ge_debt_s = 0.0
            return

        debt          = self._ge_debt_s
        total_trimmed = 0.0

        for ph in upcoming:
            hr = headrooms[ph]
            if hr <= 0.0 or debt <= 0.0:
                continue
            # Proportional share of the debt for this phase
            trim    = min(hr, debt * (hr / total_headroom))
            new_dur = nominals[ph] - trim
            try:
                ECIChangeTimingPhase(self.node_id, ph, new_dur, timeSta)
            except Exception:
                continue
            total_trimmed += trim
            debt          -= trim
            # Schedule restoration to nominal at the start of the next cycle.
            # This prevents permanent drift: trimmed durations only apply for
            # the recovery cycle, not all subsequent cycles.
            self._phases_to_restore[ph] = nominals[ph]

        self._ge_debt_s = max(0.0, debt)   # residual (if minimums bound)

        # Back-fill recovery amount into the most recent _ge_events entry
        # for this intersection so the schedule-recovery plot can show it.
        for _i in range(len(_ge_events) - 1, -1, -1):
            if _ge_events[_i][1] == self.id:
                _t, _iid, _ge, _rec = _ge_events[_i]
                _ge_events[_i] = (_t, _iid, _ge, _rec + total_trimmed)
                break

        if LOG_HARMONY:
            _vprint(
                f"[HARMONY] Cycle recovery inter={self.id} "
                f"GE={self._ge_opt_GE:.1f}s trimmed={total_trimmed:.1f}s "
                f"residual={self._ge_debt_s:.1f}s phases={upcoming} "
                f"restore_scheduled={list(self._phases_to_restore.keys())}"
            )
        else:
            log_to_file(
                f"[HARMONY] Cycle recovery inter={self.id} "
                f"GE={self._ge_opt_GE:.1f}s trimmed={total_trimmed:.1f}s "
                f"residual={self._ge_debt_s:.1f}s phases={upcoming}"
            )

    def restore_phase_if_needed(self, time, timeSta, acycle):
        current_phase = ECIGetCurrentPhase(self.node_id)

        # ── Restore phases trimmed by cycle recovery in the PREVIOUS cycle ───
        # When BusPhase next becomes current (start of a new cycle) we reset
        # any phases that were shortened for cycle recovery back to their
        # original nominal durations so trimming doesn't accumulate over time.
        if self._phases_to_restore:
            if current_phase == self.BusPhase:
                if not self._restore_fired_this_cycle:
                    _n_restored = 0
                    for _ph, _nom in self._phases_to_restore.items():
                        try:
                            ECIChangeTimingPhase(self.node_id, _ph, _nom, timeSta)
                            _n_restored += 1
                        except Exception:
                            pass
                    if _n_restored:
                        log_to_file(
                            f"[HARMONY] Nominal restore inter={self.id} "
                            f"restored {_n_restored} phases to plan durations"
                        )
                    self._phases_to_restore.clear()
                    self._restore_fired_this_cycle = True
            else:
                self._restore_fired_this_cycle = False

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
                # ── Release global bus focus ──────────────────────────────
                _release_focus(time, "harmony_ge_done")
                # ── Cycle recovery: spread the GE debt across remaining phases
                self._apply_cycle_recovery(timeSta)
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
                _release_focus(time, "harmony_ins_done")
                # ── Cycle recovery: recover the insertion's time cost from
                # the remaining phases this cycle (same as GE recovery).
                self._apply_cycle_recovery(timeSta)
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
        elif main_secs or self.incoming_sections:
            # Use whichever main set is available: stats-registered or topology-derived
            _main_for_topo = main_secs if main_secs else set(self.incoming_sections)
            try:
                resolved_side = self.stats._side_sections_from_topology(
                    self.id, list(_main_for_topo))
                side_secs = set(int(s) for s in resolved_side
                                if s and int(s) not in _main_for_topo)
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

        # Only subtract main from side if the side sections were NOT resolved
        # by Stats topology (PyANGKernel).  For topology-fallback junctions
        # (no detectors), main_secs contains ALL incoming sections from AAPI,
        # while side_secs was correctly derived by PyANGKernel.  Subtracting
        # would incorrectly remove legitimate side sections.
        if not inter_state.get('side_sections_resolved', False):
            side_secs -= main_secs
        else:
            # Side sections resolved by Stats topology — remove them from
            # main_secs to prevent double-counting delay.
            main_secs -= side_secs

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

            if car_stat.report == 0 and is_main:
                # Partial stats available (main sections only).
                # Side sections always fall through to the vehicle-scan path
                # below: queued vehicles on side streets never *exit* the
                # section so their AKIEst count stays 0 even while the
                # vehicles are stopped at the red light accumulating delay.
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
                # ── Side section delay measurement ─────────────────────────
                # Priority A: cumulative stats delta.  Captures ALL delay
                # (stop + running) for vehicles that have exited the section.
                # More accurate than stop-time scanning; works whenever Aimsun
                # has a stats collector on the cross-street section.
                if not hasattr(self, '_cum_side_prev'):
                    self._cum_side_prev = {}
                if not hasattr(self, '_side_stop_prev'):
                    self._side_stop_prev = {}
                car_d = bus_d = truck_d = 0.0
                car_cnt = bus_cnt = truck_cnt = 0
                _cum_ok = False
                try:
                    _cc = AKIEstGetCurrentStatisticsSection(sec, self.car_type_pos)
                    _bc = AKIEstGetCurrentStatisticsSection(sec, self.bus_type_pos)
                    if _cc.report == 0 or _bc.report == 0:
                        _key_c = (sec, 'car')
                        _key_b = (sec, 'bus')
                        _prev_c = self._cum_side_prev.get(_key_c, (0.0, 0))
                        _prev_b = self._cum_side_prev.get(_key_b, (0.0, 0))
                        _now_c = (_cc.DTa * _cc.count) if _cc.report == 0 else 0.0
                        _now_b = (_bc.DTa * _bc.count) if _bc.report == 0 else 0.0
                        car_d = max(0.0, _now_c - _prev_c[0]) * self.CarOcc
                        bus_d = max(0.0, _now_b - _prev_b[0]) * self.BusOcc
                        self._cum_side_prev[_key_c] = (
                            _now_c, _cc.count if _cc.report == 0 else _prev_c[1])
                        self._cum_side_prev[_key_b] = (
                            _now_b, _bc.count if _bc.report == 0 else _prev_b[1])
                        _cum_ok = True
                except Exception:
                    pass

                if not _cum_ok:
                    # Priority B: per-vehicle stop-time scan (speed=0 only).
                    # Used when no Aimsun stats collector exists on the section.
                    _n_side = max(int(AKIVehStateGetNbVehiclesSection(sec, False)), 0)
                    for _vi in range(_n_side):
                        try:
                            _veh = AKIVehStateGetVehicleInfSection(sec, _vi)
                            if _veh.report < 0:
                                continue
                            _vid = int(_veh.idVeh)
                            _stop_now = max(0.0, float(_veh.CurrentStopTime))
                            _prev_stop = self._side_stop_prev.get(_vid, _stop_now)
                            _delta_s = max(0.0, _stop_now - _prev_stop)
                            self._side_stop_prev[_vid] = _stop_now
                            _all_side_veh_ids.add(_vid)
                            if _delta_s <= 0.0:
                                continue
                            _vtype = int(_veh.type)
                            if _vtype == self.bus_type_pos:
                                bus_d   += _delta_s * self.BusOcc
                            else:
                                car_d   += _delta_s * self.CarOcc
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
                _avg_den = self.stats._inter_dsf_avg(self.id, 'density_sum')
                _avg_spd = self.stats._inter_dsf_avg(self.id, 'speed_sum')
                _avg_flw = self.stats._inter_dsf_avg(self.id, 'flow_sum')
                _avg_que = self.stats._inter_dsf_avg(self.id, 'queue_sum')
                log_to_file(
                    f"[DELAY] inter={self.id} t={time:.0f} "
                    f"main_secs={sorted(main_secs)} "
                    f"side_secs={sorted(side_secs)} "
                    f"step_weighted={weighted_delay:.4f} "
                    f"avg_density={_avg_den:.2f}veh/km "
                    f"avg_speed={_avg_spd:.2f}km/h "
                    f"avg_flow={_avg_flw:.1f}veh/h "
                    f"avg_queue={_avg_que:.2f}veh "
                    f"cum_side_delay_s={_inter_d.get('delay_side', 0.0):.2f} "
                    f"cum_main_delay_s={_inter_d.get('delay_main', 0.0):.2f} "
                    f"side_veh_tracked={len(getattr(self, '_side_stop_prev', {}))}"
                )
                self._delay_log_t = time

    # =========================================================================
    # GROUP-BASED READINESS GUARD
    # =========================================================================

    def _group_based_control_ready(self) -> bool:
        """
        Return True when this junction is under external signal control and
        ready to accept GROUP_BASED step() calls.

        ECIGetCurrentPhase returns a negative value when the junction is not
        yet active under API control (e.g. the first few simulation steps).
        Calling gb.step() before the junction is ready causes phase-lookup
        errors; this guard prevents that.
        """
        try:
            return ECIGetCurrentPhase(self.node_id) >= 0
        except Exception:
            return False

    # =========================================================================
    # MAIN UPDATE  — dispatches to correct control mode
    # =========================================================================

    def update(self, time, timeSta, acycle):
        if TSP_ACTIVE_INTERSECTIONS is not None and self.id not in TSP_ACTIVE_INTERSECTIONS:
            return

        try:
            # ── GROUP_BASED family + DYNAOPAC: delegated to GroupBasedController
            # All four variants use the same state machine; tsp_mode selects the
            # bus-detection and extension-optimisation strategy.
            # DYNAOPAC uses 'harmony' tsp_mode with CorridorCoordinator pre-arms
            # when COORDINATED_TSP=True (same as GROUP_BASED_HARMONY but the
            # optimizer policy comes from DynaROPAC person-delay objective).
            if CONTROL_MODE in ("GROUP_BASED", "GROUP_BASED_URTSP", "GROUP_BASED_HARMONY", "DYNAOPAC"):
                if self.gb is not None:
                    if self._group_based_control_ready():
                        self.gb.step(time, timeSta, acycle)
                    return
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

            elif CONTROL_MODE == "REWARD_TSP":
                self.run_reward_tsp(time, timeSta, acycle)

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

        # ── Corridor pre-arm check (HARMONY coordination) ────────────────────
        # When the CorridorCoordinator has pre-armed this intersection, apply TSP
        # immediately using the Kalman ETA rather than waiting for local detector
        # presence. Bypasses harmony search — uses a fixed eta+buffer duration so
        # the bus is guaranteed to arrive during the granted phase.
        _prearm = getattr(self, '_harmony_prearm', None)
        if _prearm is not None and self.TSPStrategy == 0:
            _pa_veh, _pa_eta_t, _pa_issued_t = _prearm
            _eta_from_now = _pa_eta_t - time
            def _notify_coord_prearm_consumed():
                if self._corridor_coord is not None and COORDINATED_TSP:
                    try:
                        self._corridor_coord.notify_bus_granted(_pa_veh, self.id, time, None)
                    except Exception as _coord_e:
                        log_to_file(
                            f"[HARMONY COORD] notify_bus_granted failed "
                            f"inter={self.id} bus={_pa_veh}: {_coord_e}"
                        )
            # Clear stale or already-expired pre-arms
            if _eta_from_now < -20.0 or time - _pa_issued_t > 120.0:
                self._harmony_prearm = None
            elif 0.0 <= _eta_from_now <= getattr(self, '_eta_max_s', 90.0):
                # Bus is expected within actionable window.
                _prearm_dur = max(float(self.BP_lower_bound), _eta_from_now + 5.0)
                _prearm_dur = min(_prearm_dur, float(self.BP_upper_bound))
                self._harmony_prearm = None
                if current_phase == self.BusPhase:
                    # GE path — cap to MAX_GE_EXTENSION_S.
                    # If bus needs more extension than the hard cap, skip entirely.
                    _ge_needed = max(0.0, _eta_from_now + 5.0)
                    if _ge_needed > MAX_GE_EXTENSION_S:
                        if LOG_HARMONY:
                            _vprint(
                                f"[HARMONY COORD GE SKIP] inter={self.id} t={time:.1f} "
                                f"bus_eta={_eta_from_now:.1f}s needs GE={_ge_needed:.1f}s "
                                f"> MAX_GE={MAX_GE_EXTENSION_S:.0f}s — skipping")
                        self.stats.record_tsp_event(self.id, 'detection')
                        self.stats.record_tsp_skip(self.id, 'ge_trivial')
                        _notify_coord_prearm_consumed()
                    else:
                        _prearm_dur = min(_prearm_dur, MAX_GE_EXTENSION_S)
                        # If the current phase already ends after the bus arrives, skip.
                        try:
                            _ps_start  = ECIGetStartingTimePhase(self.node_id)
                            _ph_dur    = GetPhaseDuration(self.node_id, current_phase, timeSta)
                            _remain    = max(0.0, _ph_dur - (time - _ps_start))
                            _next_red  = time + _remain
                            _bus_arr   = time + _eta_from_now
                            if _bus_arr <= _next_red:
                                # Bus will make the natural green — no GE needed
                                if LOG_HARMONY:
                                    _vprint(
                                        f"[HARMONY COORD GE SKIP] inter={self.id} t={time:.1f} "
                                        f"bus_arr={_bus_arr:.1f}s <= next_red={_next_red:.1f}s "
                                        f"— natural green, skipping pre-arm GE")
                                self.stats.record_tsp_event(self.id, 'detection')
                                self.stats.record_tsp_skip(self.id, 'natural_green')
                                _notify_coord_prearm_consumed()
                            else:
                                ECIChangeTimingPhase(
                                    self.node_id, current_phase,
                                    self.BusPhaseDuration + _prearm_dur, timeSta)
                                self.TimeToTerminateBusPhase = time + _remain + _prearm_dur
                                self.TSPStrategy  = 1
                                self.flag         = 1
                                self.TSPActiveTime = time + _prearm_dur + 30
                                self._tsp_cycle_grant_until = time + self.config.get('CycleTime', 135)
                                self.last_tsp_action_time   = time
                                self._ge_debt_s = _prearm_dur
                                self._ge_opt_GE = _prearm_dur
                                _ge_events.append((time, self.id, float(_prearm_dur), 0.0))
                                if LOG_HARMONY:
                                    _vprint(
                                        f"[HARMONY COORD GE] inter={self.id} t={time:.1f} "
                                        f"prearm bus={_pa_veh} eta={_eta_from_now:.1f}s "
                                        f"GE={_prearm_dur:.1f}s")
                                self.stats.record_tsp_event(self.id, 'detection')
                                self.stats.record_tsp_event(self.id, 'extension')
                                self.stats.record_tsp_extension_duration(self.id, float(_prearm_dur))
                                if _pa_veh and _pa_veh > 0:
                                    _acquire_focus(_pa_veh, self.id, time)
                                _notify_coord_prearm_consumed()
                                return True
                        except Exception as _e:
                            log_to_file(f"[HARMONY COORD GE] inter={self.id} failed: {_e}")
                else:
                    # Insertion path — only insert if the bus will miss the next natural BusPhase.
                    try:
                        _ps_now     = ECIGetStartingTimePhase(self.node_id)
                        _elapsed    = max(0.0, time - _ps_now)
                        _rem_cur    = max(0.0,
                            GetPhaseDuration(self.node_id, current_phase, timeSta) - _elapsed)
                        _time_to_bp = _rem_cur
                        try:
                            _ci  = self.phase_list.index(current_phase)
                            _bi  = self.phase_list.index(self.BusPhase)
                            _n   = len(self.phase_list)
                            _steps = (_bi - _ci) % _n
                            for _k in range(1, _steps):
                                _ph = self.phase_list[(_ci + _k) % _n]
                                _time_to_bp += GetPhaseDuration(self.node_id, _ph, timeSta)
                        except Exception:
                            _time_to_bp = float(self.config.get('CycleTime', 135))
                        _nat_end = _time_to_bp + self.BusPhaseDuration
                        if _eta_from_now <= _nat_end:
                            # Bus will catch the natural BusPhase — no insertion needed
                            if LOG_HARMONY:
                                _vprint(
                                    f"[HARMONY COORD INS SKIP] inter={self.id} t={time:.1f} "
                                    f"eta={_eta_from_now:.1f}s <= natural_end={_nat_end:.1f}s "
                                    f"— no pre-arm insertion needed")
                            self.stats.record_tsp_event(self.id, 'detection')
                            self.stats.record_tsp_skip(self.id, 'natural_green')
                            _notify_coord_prearm_consumed()
                        else:
                            _ins_wait_s = max(0.0, float(_eta_from_now))
                            self.previous_phase  = current_phase
                            self.BusPhaseEndTime = time + _prearm_dur
                            ECIChangeTimingPhase(self.id, self.BusPhase, _prearm_dur, timeSta)
                            ECIChangeDirectPhase(
                                self.id, self.BusPhase, timeSta, time, acycle, 0)
                            self.TSPStrategy  = 2
                            self.flag         = 2
                            self.TSPActiveTime = time + _prearm_dur + 30
                            self._ge_debt_s   = float(_prearm_dur)  # cycle recovery
                            self._tsp_cycle_grant_until = time + self.config.get('CycleTime', 135)
                            self.last_tsp_action_time   = time
                            if LOG_HARMONY:
                                _vprint(
                                    f"[HARMONY COORD INS] inter={self.id} t={time:.1f} "
                                    f"prearm bus={_pa_veh} eta={_eta_from_now:.1f}s "
                                    f"BP={_prearm_dur:.1f}s")
                            self.stats.record_tsp_event(self.id, 'detection')
                            self.stats.record_tsp_event(self.id, 'insertion')
                            self.stats.record_tsp_insertion_duration(self.id, float(_prearm_dur))
                            self.stats.record_tsp_insertion_wait(self.id, _ins_wait_s)
                            if _pa_veh and _pa_veh > 0:
                                _acquire_focus(_pa_veh, self.id, time)
                            _notify_coord_prearm_consumed()
                            return True
                    except Exception as _e:
                        log_to_file(f"[HARMONY COORD INS] inter={self.id} failed: {_e}")

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

        # ── Approach-level debounce for detection STATISTICS ─────────────────
        # TSP *actions* (GE, insertion) fire regardless; only stat recording
        # is debounced so skip/detection counts reflect unique bus approaches
        # rather than every simulation step.  Debounce window = 30 s (roughly
        # one signal cycle).  Reset when a new bus is seen at this junction.
        _approach_debounce_s = 30.0
        _det_vid_now = self.last_detected_bus_id
        if _det_vid_now and _det_vid_now > 0:
            _last_rec_t = self._approach_det_t.get(_det_vid_now, -999.0)
            if (time - _last_rec_t) < _approach_debounce_s:
                # Already recorded stats for this bus approach recently.
                _detection_recorded_this_call = True   # suppress further stat writes
            else:
                self._approach_det_t[_det_vid_now] = time
                _detection_recorded_this_call = False
        else:
            _detection_recorded_this_call = False

        # Each detector slot may fire in the same call — count detection only once.
        _coord_notified_this_call = False

        def _notify_coord_bus_progress(veh_id: int, reason: str):
            """Propagate downstream coordination even when local action is natural green."""
            nonlocal _coord_notified_this_call
            if _coord_notified_this_call:
                return
            if self._corridor_coord is None or not COORDINATED_TSP:
                return
            try:
                self._corridor_coord.notify_bus_granted(veh_id, self.id, time, None)
                _coord_notified_this_call = True
                if LOG_CORRIDOR:
                    _vprint(
                        f"[HARMONY COORD] inter={self.id} t={time:.1f} "
                        f"bus={veh_id} propagated ({reason})"
                    )
            except Exception as _coord_e:
                log_to_file(
                    f"[HARMONY COORD] notify_bus_granted failed "
                    f"inter={self.id} bus={veh_id} reason={reason}: {_coord_e}"
                )

        # Iterate at least 1 slot: detect_bus() populates index 0 of
        # BusPresence/BusSpeed even when BusDet is empty (no physical detectors).
        _n_det_slots = max(len(self.BusDet), 1)
        for i in range(_n_det_slots):
            bus_speed = self.BusSpeed[0][i]
            if bus_speed <= 0:
                continue

            # ── Global bus focus gate ─────────────────────────────────────────
            _det_vid = self.last_detected_bus_id
            if _det_vid and _det_vid > 0 and _is_focus_blocked(_det_vid, self.id, time):
                if LOG_HARMONY:
                    _vprint(
                        f"[BUS_FOCUS] t={time:.1f} inter={self.id} "
                        f"v={_det_vid} SUPPRESSED — focus bus={_focus_bus_id}")
                _mark_detection_point(self.id, _det_vid, 0.0, 0.0,
                                      time, "focus_suppress")
                if not _detection_recorded_this_call:
                    self.stats.record_tsp_event(self.id, 'detection')
                    _detection_recorded_this_call = True
                continue

            if current_phase == self.BusPhase:
                red_start        = self.RedStartTimeList[0][i]
                _ps = ECIGetStartingTimePhase(self.node_id)
                _pd = GetPhaseDuration(self.node_id, current_phase, timeSta)
                next_red_start = _ps + _pd
                # Use live remaining distance from ETA tracker if available
                eta_info   = getattr(self, '_bus_eta', {}).get(i)
                _det_dist_fallback = (
                    self.config["DetDistance"][0][i]
                    if self.config.get("DetDistance") and len(self.config["DetDistance"]) > 0
                       and i < len(self.config["DetDistance"][0])
                    else 200.0   # default ~200m upstream detection
                )
                live_dist  = eta_info[2] if eta_info else _det_dist_fallback

                bus_stopline_time = time + live_dist / bus_speed

                if bus_stopline_time <= next_red_start:
                    # Bus will naturally clear on green — no TSP action needed
                    if not _detection_recorded_this_call:
                        self.stats.record_tsp_event(self.id, 'detection')
                        _detection_recorded_this_call = True
                    self.stats.record_tsp_skip(self.id, 'natural_green')
                    _notify_coord_bus_progress(self.last_detected_bus_id, 'natural_green_current_phase')
                    if LOG_HARMONY:
                        _vprint(
                            f"[HARMONY] NAT_GREEN | inter={self.id} "
                            f"bus_arr={bus_stopline_time:.1f}s < red={next_red_start:.1f}s "
                            f"— no action needed")
                    continue

                if bus_stopline_time > next_red_start and self.TSPStrategy == 0:
                    GE_lb = bus_stopline_time - next_red_start

                    # ── Hard cap: skip if bus needs more extension than allowed ─
                    if GE_lb > MAX_GE_EXTENSION_S:
                        if LOG_HARMONY:
                            _vprint(
                                f"[HARMONY] GE SKIP | inter={self.id} "
                                f"needed={GE_lb:.1f}s > MAX_GE={MAX_GE_EXTENSION_S:.0f}s "
                                f"— bus too far, skipping extension")
                        if not _detection_recorded_this_call:
                            self.stats.record_tsp_event(self.id, 'detection')
                            _detection_recorded_this_call = True
                        self.stats.record_tsp_skip(self.id, 'ge_trivial')
                        continue

                    _ge_ub = min(float(self.GE_upper_bound), MAX_GE_EXTENSION_S)
                    opt_GE = harmony_search(
                        self.GE_Objective_Function, GE_lb, _ge_ub,
                        self.max_iterations, self.harmony_memory_size,
                        self.hmcr, self.par, 5, time)
                    if math.isnan(opt_GE) or opt_GE < 0:
                        opt_GE = min(10.0, _ge_ub)

                    # Hard-cap result to MAX_GE_EXTENSION_S
                    opt_GE = min(opt_GE, MAX_GE_EXTENSION_S)

                    # ── Cap GE to what this cycle can actually recover ──────────
                    # Prevents granting 28 s of GE when the remaining phases
                    # only have 5 s of combined headroom — which would leave a
                    # massive irrecoverable debt and inflate cycle length.
                    _min_floor_ge  = float(self.config.get('MinGreen', 5.0))
                    _max_trim_frac = 0.50
                    _phase_list    = getattr(self, 'phase_list', [])
                    if _phase_list and current_phase in _phase_list:
                        _ci = _phase_list.index(current_phase)
                        _n  = len(_phase_list)
                        _upcoming_ge = [
                            _phase_list[(_ci + _k) % _n]
                            for _k in range(1, _n)
                        ]
                        _upcoming_ge = [
                            p for p in _upcoming_ge
                            if p != self.BusPhase and p != current_phase
                        ]
                        _recoverable = 0.0
                        for _ph in _upcoming_ge:
                            _nom = self._nominal_phase_durations.get(_ph)
                            if _nom is None:
                                try:
                                    _nom = GetPhaseDuration(self.node_id, _ph, timeSta)
                                except Exception:
                                    _nom = 15.0
                                if not _nom or _nom <= 0:
                                    _nom = 15.0
                            _nom = max(float(_nom), _min_floor_ge)
                            _hr  = max(0.0, _nom - _min_floor_ge)
                            _hr  = min(_hr, _nom * _max_trim_frac)
                            _recoverable += _hr
                        if _recoverable > 0.5 and opt_GE > _recoverable:
                            if LOG_HARMONY:
                                _vprint(
                                    f"[HARMONY] GE cap | inter={self.id} "
                                    f"opt_GE={opt_GE:.1f}s → capped to "
                                    f"{_recoverable:.1f}s (cycle headroom limit)"
                                )
                            opt_GE = _recoverable

                    # After capping: verify extension is still sufficient to guarantee the bus
                    # makes the light. If the recoverable headroom is less than the minimum
                    # needed (GE_lb = bus_stopline_time − next_red_start), applying an
                    # insufficient extension is worse than no action — skip it instead.
                    if opt_GE < GE_lb:
                        if LOG_HARMONY:
                            _vprint(
                                f"[HARMONY] GE SKIP | inter={self.id} "
                                f"capped_GE={opt_GE:.1f}s < needed={GE_lb:.1f}s "
                                f"(cycle headroom {_recoverable:.1f}s insufficient "
                                f"— bus cannot be guaranteed through the light)")
                        if not _detection_recorded_this_call:
                            self.stats.record_tsp_event(self.id, 'detection')
                            _detection_recorded_this_call = True
                        self.stats.record_tsp_skip(self.id, 'ge_trivial')
                        continue

                    # Skip if harmony says extension is trivially small
                    if opt_GE < 0.5:
                        if LOG_HARMONY:
                            _vprint(
                                f"[HARMONY] GE skip | inter={self.id} "
                                f"opt_GE={opt_GE:.2f}s < 0.5 s — no action")
                        if not _detection_recorded_this_call:
                            self.stats.record_tsp_event(self.id, 'detection')
                            _detection_recorded_this_call = True
                        self.stats.record_tsp_skip(self.id, 'ge_trivial')
                        continue

                    remain = GetPhaseDuration(self.node_id, current_phase, timeSta) \
                             - (time - ECIGetStartingTimePhase(self.node_id))
                    ECIChangeTimingPhase(self.node_id, current_phase,
                                         self.BusPhaseDuration + float(opt_GE), timeSta)
                    self.TimeToTerminateBusPhase = time + remain + opt_GE
                    self.TSPStrategy = 1
                    self.flag        = 1
                    self.TSPActiveTime = time + float(opt_GE) + 30
                    self._tsp_cycle_grant_until = time + self.config.get('CycleTime', 135)
                    # Record the cycle debt so restore_phase_if_needed can
                    # spread the recovery across remaining phases.
                    self._ge_debt_s = float(opt_GE)
                    self._ge_opt_GE = float(opt_GE)
                    _ge_events.append((time, self.id, float(opt_GE), 0.0))
                    if LOG_HARMONY:
                        _vprint(
                            f"[HARMONY] GE | t={time:.1f}s inter={self.id} "
                            f"bus_eta={bus_stopline_time - time:.1f}s "
                            f"next_red={next_red_start - time:.1f}s "
                            f"opt_GE={opt_GE:.1f}s")
                    self.highlight_bus(self.last_detected_bus_id)
                    if not _detection_recorded_this_call:
                        self.stats.record_tsp_event(self.id, 'detection')
                        _detection_recorded_this_call = True
                    self.stats.record_tsp_event(self.id, 'extension')
                    self.stats.record_tsp_extension_duration(self.id, float(opt_GE))
                    # Acquire global bus focus
                    if self.last_detected_bus_id and self.last_detected_bus_id > 0:
                        _acquire_focus(self.last_detected_bus_id, self.id, time)
                    # Notify corridor coordinator so it can Kalman-predict and
                    # pre-arm downstream intersections (HARMONY coordination).
                    if self._corridor_coord is not None and COORDINATED_TSP:
                        try:
                            self._corridor_coord.notify_bus_granted(
                                self.last_detected_bus_id, self.id, time, None)
                        except Exception:
                            pass
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
                _det_dist_fb = (
                    self.config['DetDistance'][0][i]
                    if self.config.get('DetDistance') and len(self.config['DetDistance']) > 0
                       and i < len(self.config['DetDistance'][0])
                    else 200.0
                )
                _bus_eta_s = _eta_info[1] if _eta_info else (_det_dist_fb / bus_speed)

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
                    if not _detection_recorded_this_call:
                        self.stats.record_tsp_event(self.id, 'detection')
                        _detection_recorded_this_call = True
                    self.stats.record_tsp_skip(self.id, 'natural_green')
                    _notify_coord_bus_progress(self.last_detected_bus_id, 'natural_green_future_bus_phase')
                    continue

                # Bus will miss natural green → evaluate insertion.
                # ── Prefer natural phase completion ───────────────────
                # If the current phase is nearly done (< 8s remaining),
                # defer the insertion to the natural transition — this
                # avoids abruptly cutting a phase that's about to end
                # and reduces disruption to other traffic.
                _NATURAL_COMPLETION_THRESHOLD = 8.0
                if _rem_current <= _NATURAL_COMPLETION_THRESHOLD and _rem_current > 0.5:
                    if LOG_HARMONY:
                        _vprint(
                            f"[HARMONY] INS DEFER | inter={self.id} "
                            f"phase_rem={_rem_current:.1f}s < {_NATURAL_COMPLETION_THRESHOLD:.0f}s "
                            f"— waiting for natural phase completion")
                    continue  # will re-evaluate next step when phase transitions

                # The lower bound must guarantee the bus will arrive and clear
                # during the inserted phase: use bus ETA + 2 s headway buffer.
                # If even this minimum exceeds the upper bound, the bus is too far
                # away for a practical insertion — skip rather than insert too short.
                _bp_lb_effective = max(float(self.BP_lower_bound), _bus_eta_s + 2.0)
                if _bp_lb_effective >= float(self.BP_upper_bound):
                    if LOG_HARMONY:
                        _vprint(
                            f"[HARMONY] INS SKIP | inter={self.id} "
                            f"bus_eta={_bus_eta_s:.1f}s → lb={_bp_lb_effective:.1f}s "
                            f">= BP_upper={self.BP_upper_bound:.0f}s "
                            f"— insertion impractical (bus too far away)")
                    if not _detection_recorded_this_call:
                        self.stats.record_tsp_event(self.id, 'detection')
                        _detection_recorded_this_call = True
                    self.stats.record_tsp_skip(self.id, 'ins_trivial')
                    continue

                opt_BP = harmony_search(
                    self.BP_Objective_Function, _bp_lb_effective,
                    self.BP_upper_bound, self.max_iterations,
                    self.harmony_memory_size, self.hmcr, self.par, 5, time)

                # Skip if harmony says insertion phase is trivially short
                if math.isnan(opt_BP) or opt_BP < 0.5:
                    if LOG_HARMONY:
                        _vprint(
                            f"[HARMONY] INS skip | inter={self.id} "
                            f"opt_BP={opt_BP:.2f}s < 0.5 s — no action")
                    if not _detection_recorded_this_call:
                        self.stats.record_tsp_event(self.id, 'detection')
                        _detection_recorded_this_call = True
                    self.stats.record_tsp_skip(self.id, 'ins_trivial')
                    continue

                self.previous_phase  = current_phase
                self.BusPhaseEndTime = time + float(opt_BP)
                # Set bus phase duration first so Aimsun holds it for opt_BP
                # seconds, then force the switch into the bus phase.
                ECIChangeTimingPhase(self.id, self.BusPhase, float(opt_BP), timeSta)
                ECIChangeDirectPhase(
                    self.id, self.BusPhase, timeSta, time, acycle, 0)
                self.TSPStrategy   = 2
                self.flag          = 2
                self.TSPActiveTime = time + float(opt_BP) + 30
                self._ge_debt_s    = float(opt_BP)  # cycle recovery debt
                self._tsp_cycle_grant_until = time + self.config.get('CycleTime', 135)
                if LOG_HARMONY:
                    _vprint(
                        f"[HARMONY] INSERTION | t={time:.1f}s inter={self.id} "
                        f"bus_eta={_bus_eta_s:.1f}s > natural_end={_natural_bus_end:.1f}s "
                        f"opt_BP={opt_BP:.1f}s prev_phase={current_phase}")
                self.highlight_bus(self.last_detected_bus_id)
                if not _detection_recorded_this_call:
                    self.stats.record_tsp_event(self.id, 'detection')
                    _detection_recorded_this_call = True
                self.stats.record_tsp_event(self.id, 'insertion')
                self.stats.record_tsp_insertion_duration(self.id, float(opt_BP))
                self.stats.record_tsp_insertion_wait(self.id, max(0.0, float(_bus_eta_s)))
                # Acquire global bus focus
                if self.last_detected_bus_id and self.last_detected_bus_id > 0:
                    _acquire_focus(self.last_detected_bus_id, self.id, time)
                # Notify corridor coordinator for downstream pre-arming.
                if self._corridor_coord is not None and COORDINATED_TSP:
                    try:
                        self._corridor_coord.notify_bus_granted(
                            self.last_detected_bus_id, self.id, time, None)
                    except Exception:
                        pass
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
        _n_det_slots = max(len(self.BusDet), 1)
        # ── Phase 0 (Bus phase) ───────────────────────────────────────────────
        for i in range(_n_det_slots):
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
                _w1 = abs(self.ShockwaveSpeed1List[0][i])
                _w2 = abs(self.ShockwaveSpeed2List[0][i])
                _bs = abs(self.BusSpeed[0][i])
                _denom_a = (_w1 + _bs) * _w2   # denominator of the queue-join term
                _denom_b = _w1 + _w2            # denominator of the travel-time term
                if _denom_a < 1e-6 or _denom_b < 1e-6:
                    self.BusDelay[0][i] = 0.0
                else:
                    self.BusDelay[0][i] = (
                        self.HSGreenStartTimeList[0][i]
                        + (_w1 * self.DetDistance[0][i]) / _denom_a
                        - (time + self.DetDistance[0][i] / _denom_b)
                    )
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
        side_other_delay, side_total_veh = self._compute_side_delay_penalty(GE, _suppress_log=True)

        bus_delay_total   = self._safe_array_sum(self.BusDelay)
        base_other_delay  = self._safe_array_sum(self.OtherDelay)
        other_delay_total = base_other_delay + safe_float(side_other_delay)
        total_veh         = self._safe_array_sum(self.TotalVeh) + safe_float(side_total_veh)

        other_occ = self._estimated_other_vehicle_occupancy()
        total_pax_delay = (
            bus_delay_total * self.BusOcc +
            other_delay_total * other_occ
        )
        bus_delay_total, other_delay_total, total_veh, total_pax_delay = (
            self._finalize_objective_stats(
                bus_delay_total, other_delay_total, total_veh, total_pax_delay
            )
        )

        # log_to_file(
        #     f"[HS GE_OBJ] inter={self.id} GE={GE:.2f}s "
        #     f"bus_delay={bus_delay_total:.2f} "
        #     f"other_delay={base_other_delay:.2f} "
        #     f"side_delay={safe_float(side_other_delay):.2f} "
        #     f"other_occ={other_occ:.2f} "
        #     f"total_veh={total_veh:.1f} "
        #     f"total_pax_delay={total_pax_delay:.4f}")
        self.stats.store_objective_stats(
            bus_delay=bus_delay_total,
            other_delay=other_delay_total,
            avg_pass_delay=total_pax_delay)
        return total_pax_delay

    def BP_Objective_Function(self, GreenTime, time):
        """
        Bus-phase rotation (phase insertion) objective function.
        Mirrors BP_Objective_Function from Bus_priority_single_intersection_3.py,
        adapted for multi-intersection class with full debug logging.
        """
        self._reset_harmony_work_arrays()
        _n_det_slots = max(len(self.BusDet), 1)
        # ── Phase 0: Bus phase ─────────────────────────────────────────────────
        for i in range(_n_det_slots):
            # log_to_file(f"[HS BP_OBJ] inter={self.id} bus_det_idx={i} "
            #             f"UpDetCount={self.UpDetCountList[0][i]:.0f}")
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

            # log_to_file(f"[HS BP_OBJ] inter={self.id} i={i} "
            #             f"HSUpFlow={self.HSUpFlowList[0][i]:.1f} "
            #             f"HSUpDen={self.HSUpDenList[0][i]:.4f} "
            #             f"w1={self.HSShockwaveSpeed1List[0][i]:.4f} "
            #             f"w2={self.ShockwaveSpeed2List[0][i]:.4f} "
            #             f"w3={self.HSShockwaveSpeed3List[0][i]:.4f}")

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

        for i in range(_n_det_slots):
            w1 = self.HSShockwaveSpeed1List[0][i]
            w2 = self.ShockwaveSpeed2List[0][i]
            w3 = self.HSShockwaveSpeed3List[0][i]
            w4 = self.ShockwaveSpeed4List[0][i]
            denom = abs(w2) - abs(w1)

            if denom <= 1e-6 or abs(w3) < 1e-6:
                self.BusDelay[0][i]  = 0.0
                self.OtherDelay[0][i] = 0.0
                continue

            # log_to_file(f"[HS BP_OBJ] inter={self.id} i={i} "
            #             f"HSMaxQ={self.HSMaxQueueLength[0][i]:.1f} "
            #             f"HSMaxQTime={self.HSMaxQueueLengthTime[0][i]:.1f}")

            bus_speed = self.BusSpeed[0][i]
            if bus_speed > 0:
                # Time bus joins queue front
                self.BusJoinQueueTime[0][i] = (
                    (self.DetDistance[0][i]
                     - abs(w1) * (time - self.HSRedStartTimeList[0][i]))
                    / (bus_speed + abs(w1)) + time)

                # log_to_file(f"[HS BP_OBJ] inter={self.id} i={i} "
                #             f"BusJoinQTime={self.BusJoinQueueTime[0][i]:.1f} "
                #             f"HSMaxQTime={self.HSMaxQueueLengthTime[0][i]:.1f}")

                if self.BusJoinQueueTime[0][i] > self.HSMaxQueueLengthTime[0][i]:
                    # Bus arrives after max queue → no stop
                    self.BusStoplineTime[0][i] = time + self.DetDistance[0][i] / bus_speed
                    self.BusPhaseMinDuration[0][i] = (
                        self.BusStoplineTime[0][i] - self.HSGreenStartTimeList[0][i])
                    self.BusDelay[0][i] = 0.0

                    # log_to_file(f"[HS BP_OBJ] inter={self.id} i={i} "
                    #             f"case=no_stop_queue_clear BusStopline={self.BusStoplineTime[0][i]:.1f} "
                    #             f"MinDur={self.BusPhaseMinDuration[0][i]:.1f}")

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

                    # log_to_file(f"[HS BP_OBJ] inter={self.id} i={i} "
                    #             f"case=joins_queue bus_pos={bus_pos:.1f} "
                    #             f"BusDelay={self.BusDelay[0][i]:.2f}")

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
            # Detector groups can be empty after section-scan cleanup. Use the
            # available per-phase array width instead of assuming UpDetList has
            # a matching entry for every phase.
            _phase_slots = len(self.HSNextRedStartTime) if self.HSNextRedStartTime is not None else 0
            if _phase_slots <= 0:
                return -1000000000
            if otp_idx >= _phase_slots:
                otp_idx = 0
            _det_count = 0
            if otp_idx < len(self.UpDetList):
                _det_count = len(self.UpDetList[otp_idx])
            if _det_count <= 0:
                try:
                    _det_count = len(self.HSNextRedStartTime[otp_idx])
                except Exception:
                    _det_count = 0
            for j in range(_det_count):
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
        side_other_delay_bp, side_total_veh_bp = self._compute_side_delay_penalty(extra_red, _suppress_log=True)

        bus_delay_total   = self._safe_array_sum(self.BusDelay)
        base_other_delay  = self._safe_array_sum(self.OtherDelay)
        other_delay_total = base_other_delay + safe_float(side_other_delay_bp)
        total_veh         = self._safe_array_sum(self.TotalVeh) + safe_float(side_total_veh_bp)

        other_occ = self._estimated_other_vehicle_occupancy()
        total_pax_delay = (
            bus_delay_total * self.BusOcc +
            other_delay_total * other_occ
        )
        bus_delay_total, other_delay_total, total_veh, total_pax_delay = (
            self._finalize_objective_stats(
                bus_delay_total, other_delay_total, total_veh, total_pax_delay
            )
        )

        # log_to_file(
        #     f"[HS BP_OBJ] inter={self.id} GreenTime={GreenTime:.2f}s "
        #     f"bus_delay={bus_delay_total:.2f} "
        #     f"other_delay={base_other_delay:.2f} "
        #     f"side_delay={safe_float(side_other_delay_bp):.2f} "
        #     f"other_occ={other_occ:.2f} "
        #     f"total_veh={total_veh:.1f} "
        #     f"total_pax_delay={total_pax_delay:.4f}")
        self.stats.store_objective_stats(
            bus_delay=bus_delay_total,
            other_delay=other_delay_total,
            avg_pass_delay=total_pax_delay)
        return total_pax_delay


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

    # ── Refresh output file paths for this replication ────────────────────────
    # The module is loaded once per Aimsun session and reused across all batch
    # replications.  run_config.py is rewritten by the batch runner before each
    # run, so we re-read it here to get the correct experiment name and stamp
    # fresh output filenames — otherwise all runs append to the same CSV and
    # the dashboard cannot match bus tracking / detection data by experiment.
    global _CURRENT_EXPERIMENT, _BUS_TRACKING_CSV, _DET_CSV, _WAVE_EVENTS_CSV
    global _DET_GEOJSON, _JUNC_CSV, _RUN_SUMMARY_TXT
    try:
        _rc_path2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'run_config.py')
        _rc_ns2: dict = {}
        with open(_rc_path2, 'r') as _rc_f2:
            exec(_rc_f2.read(), _rc_ns2)
        _CURRENT_EXPERIMENT = str(_rc_ns2.get('CURRENT_EXPERIMENT',
                                               _rc_ns2.get('CURRENT_STRATEGY', 'UNKNOWN'))).strip()
    except Exception:
        pass
    _ts2 = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    _BUS_TRACKING_CSV  = os.path.join(LOG_DIR, f"bus_positions_{_CURRENT_EXPERIMENT}_{_ts2}.csv")
    _DET_CSV           = os.path.join(LOG_DIR, f"detection_points_{_CURRENT_EXPERIMENT}_{_ts2}.csv")
    _WAVE_EVENTS_CSV   = os.path.join(LOG_DIR, f"corridor_wave_events_{_CURRENT_EXPERIMENT}_{_ts2}.csv")
    _DET_GEOJSON       = os.path.join(LOG_DIR, f"detection_points_{_ts2}.geojson")
    _JUNC_CSV          = os.path.join(LOG_DIR, f"junction_centroids_{_ts2}.csv")
    _RUN_SUMMARY_TXT   = os.path.join(LOG_DIR, f"tsp_run_summary_{_ts2}.txt")
    _QUEUE_SNAPSHOT_CSV = os.path.join(LOG_DIR, f"queue_snapshot_{_CURRENT_EXPERIMENT}_{_ts2}.csv")

    # ── Reset per-run detection and tracking state ────────────────────────────
    global _marked_detections, _mark_calls_total, _mark_calls_written
    global _bus_zone_state, _bus_seen_ids, _bus_last_nearest_jct
    global _bus_line_id, _bus_track_last_t, _bus_track_header_written
    global _geojson_features, _ge_events, _wave_events
    global _pt_line_jct_route, _pt_line_section_set, _sec_to_corridor_jct
    global _corridor_jct_incoming, _bus_observed_jcts
    global _last_dashboard_t
    global _queue_snap_last_t, _queue_snap_header_written
    _marked_detections.clear()
    _mark_calls_total        = 0
    _mark_calls_written      = 0
    _bus_zone_state.clear()
    _bus_seen_ids.clear()
    _bus_last_nearest_jct.clear()
    _bus_line_id.clear()
    _bus_observed_jcts.clear()
    _bus_track_last_t        = -1e9
    _bus_track_header_written = False
    _queue_snap_last_t       = -1e9
    _queue_snap_header_written = False
    _geojson_features.clear()
    _ge_events.clear()
    _wave_events.clear()
    _pt_line_jct_route.clear()
    _pt_line_section_set.clear()
    _sec_to_corridor_jct.clear()
    _corridor_jct_incoming.clear()
    _last_dashboard_t        = -1e9

    # ── Deterministic Python RNG — makes harmony search repeatable ────────────
    # The Aimsun replication seed controls vehicle-level stochasticity; this
    # seeds the Python random module so harmony-search results are identical
    # across runs regardless of which Aimsun seed is selected.
    random.seed(12345)

    # ── Clear bus-detection polyline circles left from the previous run ────────
    try:
        from PyANGKernel import GKSystem as _GKS
        _model = _GKS.getSystem().getActiveModel()
        if _model is not None:
            _pl_type = _model.getType("GKPolyline")
            _ann_type = _model.getType("GKAnnotation")
            _n = _clear_existing_markers(_model, [_pl_type, _ann_type])
            if _n and LOG_INIT:
                AKIPrintString(f"[INIT] Cleared {_n} TSP marker(s) from previous run")
    except Exception as _e:
        pass  # non-fatal — PyANGKernel may not be available in all environments
    dm = DemandMonitor()
    dm.print_demand("AAPIInit")
    for inter_id, config in INTERSECTIONS_CONFIG.items():
        try:
            stats.register_intersection(config)
            controllers[inter_id] = IntersectionController(config)
        except Exception as e:
            if LOG_INIT: AKIPrintString(f"[INIT] ERROR creating controller {inter_id}: {e}")

    # ── Log phase-group summary for every GROUP_BASED / DYNAOPAC intersection ─
    if CONTROL_MODE in ("GROUP_BASED", "GROUP_BASED_URTSP", "GROUP_BASED_HARMONY", "DYNAOPAC"):
        if LOG_INIT:
            log_to_file("[INIT] ===== GROUP-BASED PHASE GROUP SUMMARY =====")
        for iid, ctrl in controllers.items():
            if ctrl.gb is not None:
                gb = ctrl.gb
                n_pg = len(gb.phase_groups)
                if LOG_INIT:
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
                        f"bus_sg={gb.bus_sg} bus_phase={gb._bus_aimsun_phase}"
                    )
            else:
                if LOG_INIT:
                    log_to_file(f"[INIT] jct={iid} — GroupBasedController NOT initialised")
                    AKIPrintString(f"[INIT] WARNING jct={iid} — GroupBasedController not initialised")

    # ── Build corridor coordinators from INTERSECTION_GROUPS ─────────────────
    # DYNAOPAC also builds coordinators (uses COORDINATED_TSP / COORDINATION_ALGO
    # to choose shockwave / kalman / adaptive pre-arm policy like GROUP_BASED_HARMONY)
    if CONTROL_MODE in ("GROUP_BASED", "GROUP_BASED_URTSP", "GROUP_BASED_HARMONY", "HARMONY", "REWARD_TSP", "DYNAOPAC"):
        corridor_coordinators = []
        if LOG_INIT:
            log_to_file(f"[INIT] Building corridor coordinators from {len(INTERSECTION_GROUPS)} group(s)")
        for gname, iids in INTERSECTION_GROUPS.items():
            coord = CorridorCoordinator(gname, iids, controllers)
            corridor_coordinators.append(coord)
        if LOG_INIT:
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

    # ── Backup polyline marker clear (AAPIInit clear may fail if PyANGKernel
    #    is not yet bound; by SimulationReady the model is always accessible) ──
    try:
        from PyANGKernel import GKSystem as _GKS2
        _model2 = _GKS2.getSystem().getActiveModel()
        if _model2 is not None:
            _pl2   = _model2.getType("GKPolyline")
            _ann2  = _model2.getType("GKAnnotation")
            _n2    = _clear_existing_markers(_model2, [_pl2, _ann2])
            if _n2 and LOG_INIT:
                AKIPrintString(f"[SIMREADY] Cleared {_n2} TSP marker(s) from previous run")
    except Exception:
        pass  # non-fatal

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
    if CONTROL_MODE in ("GROUP_BASED", "GROUP_BASED_URTSP", "GROUP_BASED_HARMONY", "HARMONY", "REWARD_TSP", "DYNAOPAC"):
        # ── Verify intersections are in External Control mode ─────────────────
        # GROUP_BASED uses ECIChangeSignalGroupState which requires control_type=2/3.
        # HARMONY does not — it rides on top of the normal plan.
        # If an intersection is not External, log a prominent warning.
        _bad_ctrl = []
        for iid, ctrl in controllers.items():
            if ctrl.gb is None:
                continue
            try:
                ct = ECIGetControlType(iid)
                ctrl.gb._external_control = (ct in (2, 3))
                if not ctrl.gb._external_control:
                    _bad_ctrl.append((iid, ct))
            except Exception:
                ctrl.gb._external_control = False
                _bad_ctrl.append((iid, '?'))
        if _bad_ctrl:
            _msg = (
                f"[GB] CRITICAL: {len(_bad_ctrl)} junction(s) NOT in External Control "
                f"mode — GROUP_BASED signals will NOT change (all-red or frozen). "
                f"Set control type = External in Aimsun for: "
                + ", ".join(f"jct={j}(type={t})" for j, t in _bad_ctrl)
            )
            log_to_file(_msg, force=True)   # always prints regardless of VERBOSE

        for iid, ctrl in controllers.items():
            if ctrl.gb is not None and getattr(ctrl.gb, '_external_control', True):
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
                # Iterate ALL route junctions (managed + unmanaged intermediates) so
                # that _signal_aware_eta can look up corridor positions for every
                # junction the bus passes through, not just the coordinated ones.
                for iid in coord.route_inter_ids:
                    gb = coord._ctrl_map.get(iid)
                    ic = coord._ic_map.get(iid)
                    # For intermediate route junctions not in _ctrl_map / _ic_map,
                    # fall back to the global controllers dict (they may have their
                    # own IntersectionController with XY data).
                    if gb is None and ic is None:
                        _fb = controllers.get(iid)
                        if _fb is not None:
                            ic = _fb
                    # Prefer GroupBasedController XY; fall back to HARMONY IC XY
                    try:
                        xy = gb._get_junction_xy() if gb else None
                        if xy is None and ic is not None:
                            xy = ic._get_junction_xy()
                    except Exception:
                        xy = None
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

    # ── Build PT-route-aware corridor maps (needs controllers + incoming_sections) ──
    try:
        _build_pt_line_corridor_routes()
    except Exception as _ptrb_e:
        log_to_file(f"[PT-ROUTE] WARNING: _build_pt_line_corridor_routes failed: {_ptrb_e}")

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

    _log_startup_bus_demand_snapshot("AAPIInit")
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

    # ── Continuous bus position log ───────────────────────────────────────
    if TRACK_BUS_POSITIONS:
        try:
            # Build junction XY lookup lazily and keep merging until all
            # junction centroids are resolved.
            global _jct_xy_cache
            if _jct_xy_cache is None or len(_jct_xy_cache) < len(controllers):
                _jxy = dict(_jct_xy_cache or {})
                for _iid, _ctrl in controllers.items():
                    if _iid in _jxy:
                        continue
                    try:
                        _xy = _ctrl._get_junction_xy()
                        if _xy is not None:
                            _zone_r = float(getattr(_ctrl, '_detection_zone_m',
                                          _ctrl.config.get('detection_zone_m', 250.0)))
                            _jxy[_iid] = (_xy[0], _xy[1], _zone_r)
                    except Exception:
                        pass
                if _jxy:
                    _jct_xy_cache = _jxy
            _track_all_bus_positions(time, _jct_xy_cache or {})
        except Exception:
            pass

    for inter_id, controller in controllers.items():
        try:
            # collect_delay runs identically for all modes — GROUP_BASED no longer
            # calls it internally (gb.step is detection + TSP overlay only).
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

    # ── Incremental network stats sampling (every ~30s) ───────────────────────
    try:
        _all_secs = set(_network_stats_section_ids())
        if _all_secs:
            stats.accumulate_network_step(list(_all_secs), time)
    except Exception:
        pass

    # ── Per-intersection density/speed/flow sampling (every ~30s) ─────────
    try:
        stats.accumulate_intersection_step(time)
    except Exception:
        pass

    # ── Queue length snapshot every 60s (all intersections) ──────────────────
    try:
        _write_queue_snapshot(time)
    except Exception:
        pass

    # ── Live status dashboard ─────────────────────────────────────────────────
    global _last_dashboard_t
    if STATUS_DASHBOARD_INTERVAL_S > 0 and (time - _last_dashboard_t) >= STATUS_DASHBOARD_INTERVAL_S:
        _last_dashboard_t = time
        try:
            _print_status_dashboard(time)
        except Exception as _de:
            log_to_file(f"[DASH] dashboard error: {_de}")

    return 0


# =============================================================================
# LIVE STATUS DASHBOARD
# =============================================================================

def _print_status_dashboard(time: float):
    """
    Print a compact, always-readable status table to the Aimsun console.

    Example output (every STATUS_DASHBOARD_INTERVAL_S seconds):

      [DASH] t=  3600s ══════════════════════════════════════════════════════
      [DASH]  Junction   Phase    TSP       GE-debt  Bus   det/ext/ins
      [DASH]  ─────────────────────────────────────────────────────────────
      [DASH]  17249      3 / 6    GE        12.4 s   YES   3 / 2 / 0
      [DASH]  17383      5 / 7    IDLE       0.0 s    NO   1 / 1 / 0
      [DASH]  19363      1 / 3    IDLE       0.0 s    NO   0 / 0 / 0
      [DASH]  ─────────────────────────────────────────────────────────────
      [DASH]  Active TSP: 17249 (GE, 12.4 s debt)   Corridor wave: OFF
      [DASH] ══════════════════════════════════════════════════════════════
    """
    if STATUS_DASHBOARD_INTERVAL_S <= 0:
        return
    if not controllers:
        return

    _W  = 66     # total table width
    _SEP  = "─" * _W
    _DSEP = "═" * _W

    hh = int(time // 3600)
    mm = int((time % 3600) // 60)
    ss = int(time % 60)
    t_str = f"{hh:02d}:{mm:02d}:{ss:02d}"

    lines = []
    lines.append(f"[DASH] t={t_str}  " + _DSEP[len(t_str)+8:])
    lines.append(f"[DASH]  {'Junction':<10} {'Phase':<8} {'TSP':<10} {'Debt':>7}  {'Bus':<5} {'det/ext/ins':>11}")
    lines.append(f"[DASH]  " + _SEP)

    active_tsp  = []
    wave_active = any(getattr(c, '_wave_active', False)
                      for coord in corridor_coordinators
                      for c in [coord])

    for iid, ctrl in controllers.items():
        # ── Phase info ──────────────────────────────────────────────────
        try:
            cur_ph  = ECIGetCurrentPhase(ctrl.node_id)
            n_ph    = len(ctrl.phase_list) if ctrl.phase_list else "?"
            ph_str  = f"{cur_ph} / {n_ph}"
        except Exception:
            ph_str  = "?"

        # ── TSP flag ────────────────────────────────────────────────────
        flag = getattr(ctrl, 'flag', 0)
        if flag == 1:
            tsp_str = "GE"
        elif flag == 2:
            tsp_str = "INSERTION"
        else:
            # Check GB sub-controller state too
            gb = getattr(ctrl, 'gb', None)
            gb_state = getattr(gb, 'state', None) if gb else None
            if gb_state and gb_state != "IDLE":
                tsp_str = f"GB:{gb_state}"
            else:
                tsp_str = "IDLE"

        # ── GE debt ─────────────────────────────────────────────────────
        debt   = getattr(ctrl, '_ge_debt_s', 0.0)
        debt_s = f"{debt:5.1f} s" if debt > 0.1 else "  0.0 s"

        # ── Bus presence ────────────────────────────────────────────────
        try:
            bus_here = any(ctrl.BusPresence[0] > 0)
        except Exception:
            bus_here = False
        # Also check last detected bus (non -1 and recent)
        if not bus_here:
            bus_here = getattr(ctrl, 'last_detected_bus_id', -1) != -1

        bus_str = "YES" if bus_here else " NO"

        # ── TSP event counts from stats ──────────────────────────────────
        _si = getattr(stats, '_inter', {}).get(iid, {})
        n_det = _si.get('n_detections', 0)
        n_ext = _si.get('n_extensions',  0)
        n_ins = _si.get('n_insertions',  0)
        ev_str = f"{n_det} / {n_ext} / {n_ins}"

        lines.append(
            f"[DASH]  {iid:<10} {ph_str:<8} {tsp_str:<10} {debt_s:>7}  {bus_str:<5} {ev_str:>11}"
        )

        if tsp_str != "IDLE":
            active_tsp.append(f"{iid} ({tsp_str}, {debt:.1f}s debt)")

    lines.append(f"[DASH]  " + _SEP)

    # ── Summary line ─────────────────────────────────────────────────────────
    if active_tsp:
        tsp_summary = "Active TSP: " + ", ".join(active_tsp)
    else:
        tsp_summary = "Active TSP: none"

    wave_str = "ON" if wave_active else "OFF"
    lines.append(f"[DASH]  {tsp_summary:<42}  Corridor wave: {wave_str}")
    lines.append(f"[DASH] " + _DSEP)

    for ln in lines:
        AKIPrintString(ln)
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as _lf:
                _lf.write(ln + "\n")
        except Exception:
            pass


# =============================================================================
# AIMSUN CANVAS OVERLAY — creates GKAnnotation objects in the network view
# =============================================================================

def _write_overlay_script(valid_feats: list) -> str:
    """
    Write a standalone Aimsun GUI Python script that creates GKPolyline circle
    markers for every detection point.  Returns the script path.

    Run it from Aimsun Next: Tools > Run Script  (or Scripts > Run Script File)
    """
    import json as _json

    script_path = _DET_GEOJSON.replace(".geojson", "_overlay_script.py")

    # Embed the coordinates directly so the script is self-contained
    pts_data = [
        {
            "x": float(f["geometry"]["coordinates"][0]),
            "y": float(f["geometry"]["coordinates"][1]),
            "label": (
                f"[{f['properties'].get('tier','?')}] "
                f"Bus {f['properties'].get('veh_id','?')} "
                f"jct {f['properties'].get('junction_id','?')} "
                f"t={f['properties'].get('sim_time_s','?')}s"
            ),
        }
        for f in valid_feats
    ]

    script = f'''\
"""
TSP Bus Detection Overlay Script
Generated automatically by intersection_controller.py

Run from Aimsun Next:  Tools > Run Script  (select this file)

Creates {len(pts_data)} GKPolyline circle markers in layer "TSP Bus Detections".
"""
import math
from PyANGKernel import GKSystem

CIRCLE_R = 8.0    # marker radius in model units (metres)
CIRCLE_N = 16     # polygon segments
LAYER_NAME = "TSP Bus Detections"

PTS = {_json.dumps(pts_data, indent=2)}


def _make_circle_pts(cx, cy):
    coords = []
    for k in range(CIRCLE_N + 1):
        angle = 2.0 * math.pi * k / CIRCLE_N
        coords.append((cx + CIRCLE_R * math.cos(angle),
                       cy + CIRCLE_R * math.sin(angle), 0.0))
    return coords


def _clear_existing_markers(model, gk_types):
    """
    Delete all marker objects whose name starts with a TSP marker prefix.

    Runs up to 3 sweep passes: deleting while iterating can invalidate the
    catalog snapshot, so a second/third pass catches anything missed.
    Uses catalog.remove() first (confirmed working in Aimsun Next 26).
    """
    _PREFIXES = ("[BUS]", "[WAVE]", "[SEC]", "[DET]", "[IC-detect]", "[NORMAL-detect]")
    if model is None:
        return 0
    if not isinstance(gk_types, (list, tuple)):
        gk_types = [gk_types]
    catalog = model.getCatalog()
    if catalog is None:
        return 0

    def _name_of(obj):
        for fn in ("getName", "getExternalName", "getLabel"):
            try:
                v = getattr(obj, fn)() or ""
                if v:
                    return v
            except Exception:
                pass
        return ""

    def _delete_one(obj):
        # catalog.remove() confirmed working in Aimsun Next 26; try others as
        # fallbacks for older/newer versions.
        for _fn in (
            lambda o: catalog.remove(o),
            lambda o: o.remove(),
            lambda o: catalog.removeObject(o),
            lambda o: catalog.unmanageObject(o),
            lambda o: model.remove(o),
            lambda o: model.deleteObject(o),
            lambda o: model.deleteObjectForever(o),
        ):
            try:
                _fn(obj)
                return True
            except AttributeError:
                pass
            except Exception:
                pass
        return False

    total_del = 0
    for _pass in range(3):   # up to 3 passes to catch catalog-iterator misses
        to_del = []
        for gk_type in gk_types:
            if gk_type is None:
                continue
            try:
                objs = catalog.getObjectsByType(gk_type)
            except Exception:
                continue
            if not objs:
                continue
            # Snapshot into a plain list immediately before any deletion
            obj_list = list(objs.values()) if isinstance(objs, dict) else list(objs)
            for obj in obj_list:
                if any(_name_of(obj).startswith(p) for p in _PREFIXES):
                    to_del.append(obj)

        if not to_del:
            break   # nothing left — done

        n_this_pass = sum(1 for o in to_del if _delete_one(o))
        total_del += n_this_pass
        if n_this_pass == 0:
            break   # deletion failing — don't loop

    return total_del


def run():
    model = GKSystem.getSystem().getActiveModel()
    if model is None:
        print("[overlay] ERROR: no active model")
        return

    pl_type = model.getType("GKPolyline")
    if pl_type is None:
        print("[overlay] ERROR: GKPolyline type not found in this model")
        return

    # Remove markers from any previous run before drawing new ones
    _clear_existing_markers(model, pl_type)

    # Find or create the layer
    # Aimsun Next 26: newObject(type) — one arg only; getCreateFolderForType(str)
    layer = None
    try:
        catalog = model.getCatalog()
        lyr_type = model.getType("GKLayer")
        if catalog and lyr_type:
            for lyr in (catalog.getObjectsByType(lyr_type) or []):
                if getattr(lyr, "getName", lambda: "")() == LAYER_NAME:
                    layer = lyr
                    break
        if layer is None and lyr_type:
            layer = model.newObject(lyr_type)
            if layer:
                for fn in ("setName", "setExternalName"):
                    try:
                        getattr(layer, fn)(LAYER_NAME); break
                    except Exception:
                        pass
                try:
                    folder = model.getCreateFolderForType("GKLayer")
                    model.addObjectToFolder(layer, folder)
                except Exception:
                    pass
    except Exception as e:
        print(f"[overlay] Layer setup failed: {{e}} — continuing without layer")

    # Get creation folder for polylines (string arg in Aimsun Next 26)
    pl_folder = None
    try:
        pl_folder = model.getCreateFolderForType("GKPolyline")
    except Exception:
        pass

    n_ok = n_fail = 0
    for pt in PTS:
        try:
            obj = model.newObject(pl_type)
            if obj is None:
                raise RuntimeError("newObject returned None")
            if pl_folder is not None:
                try:
                    model.addObjectToFolder(obj, pl_folder)
                except Exception:
                    pass

            coords = _make_circle_pts(pt["x"], pt["y"])

            set_ok = False
            if not set_ok:
                try:
                    obj.setPoints(coords); set_ok = True
                except Exception:
                    pass
            if not set_ok:
                try:
                    from PyANGKernel import GKPoint
                    gkpts = []
                    for cx, cy, cz in coords:
                        p = GKPoint(); p.x = cx; p.y = cy; p.z = cz
                        gkpts.append(p)
                    obj.setPoints(gkpts); set_ok = True
                except Exception:
                    pass
            if not set_ok:
                try:
                    for cx, cy, cz in coords:
                        obj.addPoint(cx, cy, cz)
                    set_ok = True
                except Exception:
                    pass

            for fn in ("setName", "setExternalName", "setLabel"):
                try:
                    getattr(obj, fn)(pt["label"]); break
                except Exception:
                    pass

            # Set bright red colour so circles are visible
            try:
                from PyANGKernel import GKColor
                obj.setColor(GKColor(220, 30, 30))
            except Exception:
                try:
                    from PyQt5.QtGui import QColor
                    obj.setColor(QColor(220, 30, 30))
                except Exception:
                    pass

            if layer:
                for fn in ("setLayer", "addToLayer"):
                    try:
                        getattr(obj, fn)(layer); break
                    except Exception:
                        pass

            n_ok += 1
        except Exception as e:
            n_fail += 1
            if n_fail == 1:
                print(f"[overlay] First marker failed: {{e}}")

    # Refresh the view
    try:
        GKSystem.getSystem().getGUI().getActiveView().update()
    except Exception:
        pass

    print(f"[overlay] Done: {{n_ok}} circles created, {{n_fail}} failed.")
    print(f"[overlay] Zoom out on the network canvas to see red circles.")
    print(f"[overlay] Or: Catalog panel > GEO objects to find them by name.")


run()
'''

    with open(script_path, "w", encoding="utf-8") as _sf:
        _sf.write(script)
    return script_path


def _overlay_detections_on_aimsun_map():
    """
    After simulation:
    1. Writes a standalone Aimsun GUI script that creates GKPolyline circle
       markers — run it via Tools > Run Script for instant canvas overlay.
    2. Attempts to create the markers directly (AAPI context — may be read-only).

    Uses PyANGKernel (bundled with Aimsun Next).  Any API mismatch is caught
    and logged — the function never raises.
    """
    if not OVERLAY_DETECTIONS_ON_MAP:
        return
    if not MARK_DETECTION_POINTS:
        return

    valid_feats = [
        f for f in _geojson_features
        if not (f["geometry"]["coordinates"][0] == 0.0
                and f["geometry"]["coordinates"][1] == 0.0)
    ]
    if not valid_feats:
        log_to_file("[MAP] No valid-coordinate detections — canvas overlay skipped", force=True)
        return

    # Always write the standalone script — works even if the direct AAPI path fails.
    try:
        _script_path = _write_overlay_script(valid_feats)
        log_to_file(
            f"[MAP] Overlay script written: {_script_path}\n"
            f"      → To show circles in Aimsun: Tools > Run Script > select that file",
            force=True
        )
    except Exception as _se:
        log_to_file(f"[MAP] Overlay script write failed: {_se}", force=True)

    try:
        from PyANGKernel import GKSystem
    except ImportError:
        log_to_file(
            "[MAP] PyANGKernel not available — use the overlay script above.",
            force=True
        )
        return

    try:
        model = GKSystem.getSystem().getActiveModel()
        if model is None:
            log_to_file("[MAP] getActiveModel() returned None — canvas overlay skipped", force=True)
            return
    except Exception as _ge:
        log_to_file(f"[MAP] Could not access Aimsun model: {_ge}", force=True)
        return

    try:
        # Try type names used across different Aimsun Next versions.
        # getType() returns None for unknown names — no exception raised.
        _ANN_NAMES = [
            "GKAnnotation", "GKNote", "GKLabel",
            "GKMapLabel", "GKTextAnnotation", "GKAnnotation3D",
        ]
        ann_type = None
        _ann_name_used = ""
        for _tn in _ANN_NAMES:
            _t = model.getType(_tn)
            if _t is not None:
                ann_type = _t
                _ann_name_used = _tn
                break

        _use_polyline = False
        if ann_type is None:
            # GKAnnotation not available — try GKPolyline circle markers instead
            _pl_type = model.getType("GKPolyline")
            if _pl_type is None:
                # No usable type found — log available types for diagnostics
                _PROBE = [
                    "GKNode", "GKSection", "GKDetector", "GKCentroid",
                    "GKAnnotation", "GKNote", "GKLabel", "GKMapLabel",
                    "GKPolyline", "GKPolygon", "GKBitmap", "GKObject",
                ]
                _found = [n for n in _PROBE if model.getType(n) is not None]
                log_to_file(
                    f"[MAP] No overlay type found (tried {_ANN_NAMES} + GKPolyline). "
                    f"Types present in this model: {_found}. "
                    f"Open the GeoJSON manually: File > Import > {_DET_GEOJSON}",
                    force=True
                )
                return
            _use_polyline = True
            log_to_file("[MAP] Using GKPolyline circles as detection markers", force=True)
        else:
            log_to_file(f"[MAP] Using annotation type '{_ann_name_used}'", force=True)

        # ── Clear markers from any previous simulation run ────────────────────
        _MARKER_PREFIXES = (
            "[BUS]", "[WAVE]", "[SEC]", "[DET]",
            "[IC-detect]", "[NORMAL-detect]",
        )
        _clear_type = _pl_type if _use_polyline else ann_type
        try:
            _catalog = model.getCatalog()
            _all_objs = _catalog.getObjectsByType(_clear_type) if _catalog else None
            _obj_list = (
                list(_all_objs.values()) if isinstance(_all_objs, dict)
                else list(_all_objs or [])
            )
            _n_cleared = 0
            for _old in _obj_list:
                _name = ""
                for _fn in ("getName", "getExternalName"):
                    try:
                        _name = getattr(_old, _fn)() or ""
                        if _name:
                            break
                    except Exception:
                        pass
                if any(_name.startswith(_p) for _p in _MARKER_PREFIXES):
                    try:
                        model.deleteObject(_old)
                        _n_cleared += 1
                    except Exception:
                        pass
            if _n_cleared:
                log_to_file(f"[MAP] Cleared {_n_cleared} marker(s) from previous run", force=True)
        except Exception as _ce:
            log_to_file(f"[MAP] Marker clear failed (non-fatal): {_ce}", force=True)


        # ── Tier → ASCII prefix (emoji may not render in all Aimsun builds) ─
        def _pfx(tier: str) -> str:
            if "IC-detect" in tier or "PT-coord" in tier:
                return "[BUS]"
            if "coord-prearm" in tier:
                return "[WAVE]"
            if "sec" in tier:
                return "[SEC]"
            return "[DET]"

        # ── Object creation helper (Aimsun Next 26 API) ───────────────────────
        # Confirmed signatures:
        #   model.newObject(gktype)                 — one arg, no parent/folder
        #   model.getCreateFolderForType(type_name) — takes str, not GKType
        #   model.addObjectToFolder(obj, folder)    — add to folder after creation
        def _create_obj(gktype, type_name: str):
            """Create and return a new model object, placed in its default folder."""
            obj = model.newObject(gktype)
            if obj is None:
                raise RuntimeError("model.newObject() returned None")
            # Place in the type's default creation folder
            try:
                _folder = model.getCreateFolderForType(type_name)
                model.addObjectToFolder(obj, _folder)
            except Exception:
                pass
            return obj

        # ── Try to find or create a dedicated layer ───────────────────────────
        _layer = None
        _LAYER_NAME = "TSP Bus Detections"
        try:
            # Iterate layers to find an existing one with this name
            _catalog = model.getCatalog()
            if _catalog is not None:
                for _lyr in (_catalog.getObjectsByType(model.getType("GKLayer")) or []):
                    if getattr(_lyr, 'getName', lambda: '')() == _LAYER_NAME:
                        _layer = _lyr
                        break
            # Create new layer if not found
            if _layer is None:
                _lyr_type = model.getType("GKLayer")
                if _lyr_type is not None:
                    try:
                        _layer = _create_obj(_lyr_type, "GKLayer")
                    except Exception:
                        _layer = None
                    for _set_fn in ("setName", "setExternalName"):
                        try:
                            getattr(_layer, _set_fn)(_LAYER_NAME)
                            break
                        except Exception:
                            pass
        except Exception:
            _layer = None   # proceed without a custom layer

        # ── Create one marker per detection ───────────────────────────────────
        import math as _math
        n_ok   = 0
        n_fail = 0

        # GKPolyline circle parameters
        _CIRCLE_R  = 8.0   # radius in model units (metres)
        _CIRCLE_N  = 16    # number of segments

        for feat in valid_feats:
            x     = float(feat["geometry"]["coordinates"][0])
            y     = float(feat["geometry"]["coordinates"][1])
            props = feat["properties"]
            tier  = str(props.get("tier", ""))
            vid   = props.get("veh_id", "?")
            jid   = props.get("junction_id", "?")
            t_s   = props.get("sim_time_s", "?")
            label = f"{_pfx(tier)} Bus {vid}  jct {jid}  t={t_s}s  [{tier}]"

            try:
                if _use_polyline:
                    # ── Draw a small circle using GKPolyline ──────────────────
                    # Build circle coordinates as plain Python tuples — avoids
                    # depending on GKPoints3D / GKPoint which vary across builds.
                    _coords = []
                    for _k in range(_CIRCLE_N + 1):   # +1 closes the circle
                        _angle = 2.0 * _math.pi * _k / _CIRCLE_N
                        _coords.append((
                            x + _CIRCLE_R * _math.cos(_angle),
                            y + _CIRCLE_R * _math.sin(_angle),
                            0.0
                        ))

                    obj = _create_obj(_pl_type, "GKPolyline")

                    # Try every known point-setting API in order of preference.
                    _pts_set = False

                    # Option A: setPoints with list of tuples (simplest)
                    if not _pts_set:
                        try:
                            obj.setPoints(_coords)
                            _pts_set = True
                        except Exception:
                            pass

                    # Option B: GKPoint objects in a plain list
                    if not _pts_set:
                        try:
                            from PyANGKernel import GKPoint as _GKP
                            _gk_pts = []
                            for _cx, _cy, _cz in _coords:
                                _p = _GKP(); _p.x = _cx; _p.y = _cy; _p.z = _cz
                                _gk_pts.append(_p)
                            obj.setPoints(_gk_pts)
                            _pts_set = True
                        except Exception:
                            pass

                    # Option C: addPoint one at a time (tuple variant)
                    if not _pts_set:
                        try:
                            for _cx, _cy, _cz in _coords:
                                obj.addPoint(_cx, _cy, _cz)
                            _pts_set = True
                        except Exception:
                            pass

                    # Option D: addPoint with GKPoint
                    if not _pts_set:
                        try:
                            from PyANGKernel import GKPoint as _GKP
                            for _cx, _cy, _cz in _coords:
                                _p = _GKP(); _p.x = _cx; _p.y = _cy; _p.z = _cz
                                obj.addPoint(_p)
                            _pts_set = True
                        except Exception:
                            pass

                    if not _pts_set:
                        raise RuntimeError("No working setPoints/addPoint API found for GKPolyline")

                    for _fn in ("setName", "setExternalName", "setLabel"):
                        try:
                            getattr(obj, _fn)(label)
                            break
                        except Exception:
                            pass
                else:
                    # ── Create annotation (GKAnnotation or equivalent) ────────
                    obj = _create_obj(ann_type, _ann_name_used)

                    _pos_set = False
                    try:
                        from PyANGKernel import GKPoint
                        _pt = GKPoint()
                        _pt.x = x; _pt.y = y; _pt.z = 0.0
                        obj.setPosition(_pt)
                        _pos_set = True
                    except Exception:
                        pass

                    if not _pos_set:
                        try:
                            obj.setPoints([(x, y, 0.0)])
                            _pos_set = True
                        except Exception:
                            pass

                    if not _pos_set:
                        try:
                            obj.setPosition((x, y, 0.0))
                        except Exception:
                            pass

                    for _fn in ("setLabel", "setText", "setName", "setExternalName"):
                        try:
                            getattr(obj, _fn)(label)
                            break
                        except Exception:
                            pass

                # ── Set colour (bright red so circles are visible) ────────────
                try:
                    from PyANGKernel import GKColor as _GKC
                    obj.setColor(_GKC(220, 30, 30))
                except Exception:
                    pass
                try:
                    from PyQt5.QtGui import QColor as _QC
                    obj.setColor(_QC(220, 30, 30))
                except Exception:
                    pass

                # ── Assign to layer (both paths) ──────────────────────────────
                if _layer is not None:
                    for _fn in ("setLayer", "addToLayer"):
                        try:
                            getattr(obj, _fn)(_layer)
                            break
                        except Exception:
                            pass

                n_ok += 1

            except Exception as _obj_e:
                n_fail += 1
                if n_fail == 1:
                    log_to_file(f"[MAP] Marker creation failed: {_obj_e}", force=True)
                if n_fail >= 2:
                    log_to_file("[MAP] Second failure identical — stopping canvas overlay", force=True)
                    break

        # ── Trigger a view refresh so circles appear immediately ──────────────
        try:
            GKSystem.getSystem().getGUI().getActiveView().update()
        except Exception:
            pass

        _marker_kind = "circle(s)" if _use_polyline else "annotation(s)"
        log_to_file(
            f"[MAP] Canvas overlay complete: {n_ok} {_marker_kind} created "
            f"({n_fail} failed) from {len(valid_feats)} detection points.\n"
            f"      → In Aimsun: zoom out on the network canvas to see red circles.\n"
            f"      → Or open the Catalog panel and look under GEO objects.",
            force=True
        )

    except Exception as _top_e:
        import traceback
        log_to_file(
            f"[MAP] Canvas overlay error: {_top_e}\n{traceback.format_exc()}",
            force=True
        )


def AAPIFinish():
    log_to_file("===== AAPIFinish =====")

    # ── Aggregate corridor coordinator pre-arm stats ───────────────────────────
    try:
        _combined_prearm = {"fired": 0, "success": 0, "missed": 0,
                             "expired": 0, "discarded": 0,
                             "late_success": 0, "late_success_delay_s": 0.0}
        for _coord in corridor_coordinators:
            _ps = getattr(_coord, '_prearm_stats', {})
            for _k in _combined_prearm:
                if _k == "late_success_delay_s":
                    _combined_prearm[_k] += float(_ps.get(_k, 0.0))
                else:
                    _combined_prearm[_k] += int(_ps.get(_k, 0))
        stats.record_prearm_stats(_combined_prearm)
        _fired = int(_combined_prearm.get("fired", 0) or 0)
        _succ = int(_combined_prearm.get("success", 0) or 0)
        _succ_pct = (100.0 * _succ / _fired) if _fired > 0 else 0.0
        log_to_file(f"[FINISH] prearm stats: {_combined_prearm}", force=True)
        log_to_file(
            f"[FINISH] prearm success rate: {_succ}/{_fired} = {_succ_pct:.1f}%",
            force=True,
        )
    except Exception as _pe:
        log_to_file(f"[FINISH] prearm stats error: {_pe}", force=True)

    # ── Collect network-level section statistics ───────────────────────────────
    try:
        # Use ALL network sections for global stats — this matches what Aimsun's
        # Statistics panel shows (network-wide density/flow/speed).
        _all_secs: set = set()
        try:
            _n_secs = int(AKIInfNetNbSectionsANG())
            for _si in range(_n_secs):
                _sid = int(AKIInfNetGetSectionANGId(_si))
                if _sid > 0:
                    _all_secs.add(_sid)
            log_to_file(
                f"[FINISH] network sections from AKIInfNet: {len(_all_secs)}",
                force=True,
            )
        except Exception as _net_e:
            log_to_file(
                f"[FINISH] AKIInfNetNbSectionsANG fallback: {_net_e}", force=True
            )
            # Fallback to approach sections from controllers + stats records
            for _ctrl in controllers.values():
                for _sec in getattr(_ctrl, 'incoming_sections', []):
                    if _sec and _sec > 0:
                        _all_secs.add(_sec)
            for _iid_data in getattr(stats, '_inter', {}).values():
                for _sec in _iid_data.get('main_sections', []):
                    if _sec and isinstance(_sec, int) and _sec > 0:
                        _all_secs.add(_sec)
                for _sec in _iid_data.get('side_sections', []):
                    if _sec and isinstance(_sec, int) and _sec > 0:
                        _all_secs.add(_sec)
        stats.collect_network_stats_at_finish(list(_all_secs))
        log_to_file(f"[FINISH] network stats collected ({len(_all_secs)} sections)", force=True)
        try:
            _net_flow = int(getattr(stats, '_net_total_flow_veh', 0) or 0)
            _net_den = float(getattr(stats, '_net_avg_density_vkm', 0.0) or 0.0)
            _net_spd = float(getattr(stats, '_net_avg_speed_kmh', 0.0) or 0.0)
            _net_dbg = dict(getattr(stats, '_net_debug', {}) or {})
            log_to_file(
                f"[FINISH] network kpis: flow={_net_flow} veh "
                f"density={_net_den:.4f} veh/km speed={_net_spd:.3f} km/h",
                force=True,
            )
            if _net_dbg:
                log_to_file(
                    "[FINISH] network debug: "
                    f"source={_net_dbg.get('source')} sim_time_s={_net_dbg.get('sim_time_s')} "
                    f"sections={_net_dbg.get('section_count')} stats_ok={_net_dbg.get('stats_ok_sections')} "
                    f"stats_zero={_net_dbg.get('stats_zero_sections')} snap_ok={_net_dbg.get('snapshot_ok_sections')} "
                    f"snap_with_veh={_net_dbg.get('snapshot_sections_with_vehicles')} "
                    f"snap_zero={_net_dbg.get('snapshot_zero_sections')} "
                    f"missing_len={_net_dbg.get('sections_missing_length')}",
                    force=True,
                )
            if _net_flow <= 0 and _net_den <= 0 and _net_spd <= 0:
                log_to_file(
                    "[FINISH] network kpis are all zero; check section stats API "
                    "availability and section coverage.",
                    force=True,
                )
        except Exception as _nk:
            log_to_file(f"[FINISH] network kpi log error: {_nk}", force=True)
    except Exception as _ne:
        log_to_file(f"[FINISH] network stats error: {_ne}", force=True)

    try:
        stats.print_results()
        stats.save_results()
        log_to_file("[FINISH] stats saved OK", force=True)
        try:
            _gk = stats._global_kpis()
            _nat = int(_gk.get('n_tsp_natural_green', 0) or 0)
            _det = int(_gk.get('n_tsp_detections', 0) or 0)
            _nat_pct = (100.0 * _nat / _det) if _det > 0 else 0.0
            log_to_file(
                f"[FINISH] natural_green: {_nat}/{_det} = {_nat_pct:.1f}%",
                force=True,
            )
        except Exception:
            pass
    except Exception as e:
        import traceback
        log_to_file(f"[FINISH] stats error: {e}\n{traceback.format_exc()}", force=True)

    try:
        _write_run_summary()
        log_to_file(f"[FINISH] run summary written: {_RUN_SUMMARY_TXT}", force=True)
    except Exception as e:
        log_to_file(f"[FINISH] run summary error: {e}", force=True)

    try:
        _write_algorithm_explanation_tex()
        log_to_file(f"[FINISH] algorithm explanation written: {_ALGORITHM_EXPLANATION_TEX}", force=True)
    except Exception as e:
        log_to_file(f"[FINISH] algorithm explanation error: {e}", force=True)
    for controller in controllers.values():
        if CONTROL_MODE == "URTSP":
            log_to_file(controller.get_urtsp_summary())
    # ── Corridor summary ──────────────────────────────────────────────────────
    for coord in corridor_coordinators:
        log_to_file(f"[FINISH] {coord.summary()}")
    # ── Schedule-recovery plot ────────────────────────────────────────────────
    try:
        _plot_schedule_recovery()
    except Exception as _sre:
        log_to_file(f"[FINISH] schedule recovery plot error: {_sre}")

    # ── Flush detection-point GeoJSON ─────────────────────────────────────────
    if MARK_DETECTION_POINTS and _geojson_features:
        try:
            import json
            geojson = {
                "type": "FeatureCollection",
                "features": _geojson_features,
            }
            with open(_DET_GEOJSON, "w", encoding="utf-8") as _gf:
                json.dump(geojson, _gf, indent=2)
            log_to_file(
                f"[MARK] Detection GeoJSON written: {_DET_GEOJSON} "
                f"({len(_geojson_features)} points)"
            )
        except Exception as _ge:
            log_to_file(f"[MARK] GeoJSON write failed: {_ge}")

    # ── Detection-point diagnostics (always shown) ────────────────────────────
    log_to_file(
        f"[MARK DIAG] MARK_DETECTION_POINTS={MARK_DETECTION_POINTS} | "
        f"_mark_calls_total={_mark_calls_total} | "
        f"_mark_calls_written={_mark_calls_written} | "
        f"unique_pairs={len(_marked_detections)} | "
        f"geojson_features={len(_geojson_features)} | "
        f"CSV_path={_DET_CSV} | "
        f"CSV_exists={os.path.isfile(_DET_CSV)}",
        force=True
    )

    # ── Per-junction detection summary ───────────────────────────────────────
    # Shows exactly how many unique buses were detected at each junction, split
    # by tier (IC-detect, track-section, track-zone, focus, coord, etc.).
    # Useful for diagnosing "not seen" gaps in the dashboard.
    try:
        _det_by_jct: dict = {}  # {jct_id: {tier: count}}
        _det_buses_by_jct: dict = {}  # {jct_id: set(veh_id)}
        for (_dj, _dv) in _marked_detections:
            _det_buses_by_jct.setdefault(_dj, set()).add(_dv)
        # Also load tier breakdown from CSV
        if os.path.isfile(_DET_CSV):
            with open(_DET_CSV, "r", newline="", encoding="utf-8") as _df:
                for _dr in csv.DictReader(_df):
                    try:
                        _jid = int(float(_dr.get("junction_id", -1) or -1))
                        _tier = str(_dr.get("tier", "?") or "?")
                        if _jid > 0:
                            _det_by_jct.setdefault(_jid, {})
                            _det_by_jct[_jid][_tier] = _det_by_jct[_jid].get(_tier, 0) + 1
                    except Exception:
                        pass
        _total_det_buses = len(set(v for pairs in _det_buses_by_jct.values() for v in pairs))
        _total_active    = len(_bus_seen_ids)
        log_to_file(
            f"[DET SUMMARY] Active buses tracked: {_total_active} | "
            f"Unique buses detected at ≥1 junction: {_total_det_buses} | "
            f"PT route map: {len(_pt_line_jct_route)} lines / {len(_sec_to_corridor_jct)} sections",
            force=True)
        for _jid in sorted(_det_buses_by_jct.keys()):
            _n_det = len(_det_buses_by_jct[_jid])
            _tiers = _det_by_jct.get(_jid, {})
            _tier_str = " ".join(f"{t}:{n}" for t, n in sorted(_tiers.items()))
            log_to_file(
                f"[DET SUMMARY] jct={_jid}: {_n_det} unique buses detected | {_tier_str}",
                force=True)
        # Junctions with 0 detections
        _zero_jcts = [j for j in controllers if j not in _det_buses_by_jct]
        if _zero_jcts:
            log_to_file(
                f"[DET SUMMARY] Junctions with 0 detections: {sorted(_zero_jcts)}",
                force=True)
    except Exception as _ds_e:
        log_to_file(f"[DET SUMMARY] error building summary: {_ds_e}", force=True)

    # ── Bus-tracking diagnostics (always shown) ─────────────────────────────
    try:
        _bt_exists = os.path.isfile(_BUS_TRACKING_CSV)
        _bt_rows = 0
        _bt_uniq_bus = set()
        _bt_uniq_jct = set()
        _bt_events = {}
        if _bt_exists:
            with open(_BUS_TRACKING_CSV, "r", newline="", encoding="utf-8") as _bf:
                _br = csv.DictReader(_bf)
                for _r in _br:
                    _bt_rows += 1
                    try:
                        _v = int(float(_r.get("veh_id", 0) or 0))
                        if _v > 0:
                            _bt_uniq_bus.add(_v)
                    except Exception:
                        pass
                    try:
                        _j = int(float(_r.get("nearest_jct", -1) or -1))
                        if _j > 0:
                            _bt_uniq_jct.add(_j)
                    except Exception:
                        pass
                    _ev = str(_r.get("event", "track") or "track")
                    _bt_events[_ev] = int(_bt_events.get(_ev, 0)) + 1
        _ev_text = ", ".join(
            f"{_k}:{_bt_events[_k]}" for _k in sorted(_bt_events.keys())
        ) if _bt_events else "none"
        log_to_file(
            f"[BUS_TRACK DIAG] TRACK_BUS_POSITIONS={TRACK_BUS_POSITIONS} | "
            f"CSV_path={_BUS_TRACKING_CSV} | exists={_bt_exists} | "
            f"rows={_bt_rows} | unique_buses={len(_bt_uniq_bus)} | "
            f"unique_jcts={len(_bt_uniq_jct)} | events={_ev_text}",
            force=True,
        )
    except Exception as _bt_e:
        log_to_file(f"[BUS_TRACK DIAG] error: {_bt_e}", force=True)

    # ── Corridor wave/coordinator event CSV ──────────────────────────────────
    # ── Global bus focus history CSV ──────────────────────────────────────────
    # Flush any still-active focus so the final event is not lost.
    if _focus_bus_id > 0:
        try:
            _t_now = float(AKIGetCurrentSimulationTime())
        except Exception:
            _t_now = float(AKIGetSimulationTime()) if 'AKIGetSimulationTime' in globals() else 0.0
        _release_focus(_t_now, "finish_flush")

    if _focus_history:
        try:

            _focus_csv = _DET_CSV.replace("detection_points_", "focus_history_")
            with open(_focus_csv, "w", newline="", encoding="utf-8") as _ff:
                _fw = csv.writer(_ff)
                _fw.writerow(["start_t", "end_t", "veh_id", "jct_id",
                              "outcome", "held_s"])
                for _fh in _focus_history:
                    _fw.writerow([
                        f"{_fh[0]:.1f}", f"{_fh[1]:.1f}",
                        _fh[2], _fh[3], _fh[4],
                        f"{_fh[1] - _fh[0]:.1f}",
                    ])
            log_to_file(
                f"[BUS_FOCUS] history CSV written: {_focus_csv} "
                f"({len(_focus_history)} events)", force=True)
        except Exception as _fe:
            log_to_file(f"[BUS_FOCUS] history CSV error: {_fe}", force=True)

    if _wave_events:
        try:
            with open(_WAVE_EVENTS_CSV, "w", newline="", encoding="utf-8") as _wf:
                _w = csv.DictWriter(_wf, fieldnames=[
                    "sim_time_s", "group", "event",
                    "source_jct", "target_jct", "veh_id",
                    "eta_s", "lead_s", "note",
                ])
                _w.writeheader()
                _w.writerows(_wave_events)
            log_to_file(
                f"[FINISH] corridor wave events written: {_WAVE_EVENTS_CSV} "
                f"({len(_wave_events)} rows)",
                force=True,
            )
        except Exception as _we:
            log_to_file(f"[FINISH] corridor wave event write error: {_we}", force=True)
    # Dump the bus_sg and tsp_mode of every GB controller so we can see if
    # detection is even plausible
    for _iid, _ctrl in controllers.items():
        _gb = getattr(_ctrl, 'gb', None)
        if _gb is not None:
            log_to_file(
                f"[MARK DIAG] jct={_iid} "
                f"bus_sg={getattr(_gb,'bus_sg',None)} "
                f"tsp_mode={getattr(_gb,'tsp_mode','?')} "
                f"bus_type_pos={getattr(_gb,'bus_type_pos','?')} "
                f"bus_det={getattr(_gb,'bus_det',[])} "
                f"incoming_secs={getattr(_gb,'incoming_sections',[])} "
                f"jxy_cache={getattr(_gb,'_junction_xy_cache',None)}",
                force=True
            )

    # ── Write junction centroids CSV ──────────────────────────────────────────
    # Collected from every controller's cached XY (IntersectionController and
    # GroupBasedController both store _junction_xy / _junction_xy_cache).
    # The plot script reads this to draw intersection markers as a reference frame.
    if MARK_DETECTION_POINTS:
        try:
            with open(_JUNC_CSV, "w", newline="", encoding="utf-8") as _jf:
                _jw = csv.writer(_jf)
                _jw.writerow(["junction_id", "x", "y", "cycle_time_s", "bus_phase", "bus_phase_duration_s"])
                for _jiid, _jctrl in controllers.items():
                    # Try cached value first; if not set, call _get_junction_xy()
                    # to resolve it now (the lazy cache may not have fired if no
                    # buses were detected at this junction this run).
                    _jxy = getattr(_jctrl, '_junction_xy', None)
                    if _jxy is None and hasattr(_jctrl, '_get_junction_xy'):
                        try:
                            _jxy = _jctrl._get_junction_xy()
                        except Exception:
                            pass
                    # GroupBasedController caches in gb._junction_xy_cache
                    if _jxy is None:
                        _gb = getattr(_jctrl, 'gb', None)
                        if _gb is not None:
                            _jxy = getattr(_gb, '_junction_xy_cache', None)
                            if _jxy is None and hasattr(_gb, '_get_junction_xy'):
                                try:
                                    _jxy = _gb._get_junction_xy()
                                except Exception:
                                    pass
                    if _jxy is not None:
                        _jcfg = INTERSECTIONS_CONFIG.get(_jiid, {})
                        _cycle_t = float(_jcfg.get('CycleTime', 0) or 0)
                        _bus_ph  = int(_jcfg.get('BusPhase', -1) or -1)
                        _bus_dur = float(_jcfg.get('BusPhaseDuration', 0) or 0)
                        _jw.writerow([_jiid, f"{_jxy[0]:.3f}", f"{_jxy[1]:.3f}",
                                      f"{_cycle_t:.1f}", _bus_ph, f"{_bus_dur:.1f}"])
            log_to_file(f"[MARK] Junction centroids written: {_JUNC_CSV}", force=True)
        except Exception as _je:
            log_to_file(f"[MARK] Junction centroids write failed: {_je}", force=True)

    # ── Plot detection points to PNG + HTML map (post-simulation) ─────────────
    if MARK_DETECTION_POINTS:
        if not os.path.isfile(_DET_CSV):
            log_to_file("[MARK] Detection plot skipped — no CSV (no buses detected?)", force=True)
        else:
            _script_dir = os.path.dirname(os.path.abspath(__file__))
            if _script_dir not in sys.path:
                sys.path.insert(0, _script_dir)
            try:
                import importlib
                import plot_detections as _pd
                importlib.reload(_pd)
                _junc_csv_arg = _JUNC_CSV if os.path.isfile(_JUNC_CSV) else None
                _pd.run(csv_path=_DET_CSV, junc_csv=_junc_csv_arg)
                log_to_file(f"[MARK] Detection plot written alongside {_DET_CSV}", force=True)
            except Exception as _pe:
                import traceback
                log_to_file(f"[MARK] Detection plot failed: {_pe}\n{traceback.format_exc()}", force=True)

            # ── Green-wave time-space dashboard ───────────────────────────────
            try:
                import importlib
                import plot_green_wave as _pgw
                importlib.reload(_pgw)
                _junc_csv_arg = _JUNC_CSV if os.path.isfile(_JUNC_CSV) else None
                _pgw.run(csv_path=_DET_CSV, junc_csv=_junc_csv_arg)
                log_to_file("[GREEN WAVE] Green-wave dashboard written", force=True)
            except Exception as _gwe:
                import traceback
                log_to_file(
                    f"[GREEN WAVE] Plot failed: {_gwe}\n{traceback.format_exc()}",
                    force=True
                )

            # ── Per-bus detail plots with missed-green diagnostics ─────────────
            try:
                import importlib
                import plot_bus_detail as _pbd
                importlib.reload(_pbd)
                _junc_csv_arg = _JUNC_CSV if os.path.isfile(_JUNC_CSV) else None
                _pbd.run(csv_path=_DET_CSV, junc_csv=_junc_csv_arg)
                log_to_file("[BUS DETAIL] Per-bus plots written", force=True)
            except Exception as _bde:
                import traceback
                log_to_file(
                    f"[BUS DETAIL] Plot failed: {_bde}\n{traceback.format_exc()}",
                    force=True
                )

            # ── Space-time green-wave diagram ─────────────────────────────────
            try:
                import importlib
                import plot_spacetime_wave as _pst
                importlib.reload(_pst)
                _junc_csv_arg = _JUNC_CSV if os.path.isfile(_JUNC_CSV) else None
                _pst.run(csv_path=_DET_CSV, junc_csv=_junc_csv_arg)
                log_to_file("[SPACETIME] Space-time diagram written", force=True)
            except Exception as _ste:
                import traceback
                log_to_file(
                    f"[SPACETIME] Plot failed: {_ste}\n{traceback.format_exc()}",
                    force=True
                )

            # ── HTML comparison dashboard (updates after every run) ────────────
            try:
                import importlib
                import generate_dashboard as _gd
                importlib.reload(_gd)
                _batch_csv = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "batch_results.csv")
                _gd.generate(
                    batch_csv=_batch_csv if os.path.isfile(_batch_csv) else None,
                    log_dir=os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), "logs")
                )
                log_to_file("[DASHBOARD] HTML dashboard written", force=True)
            except Exception as _dbe:
                import traceback
                log_to_file(
                    f"[DASHBOARD] Generation failed: {_dbe}\n{traceback.format_exc()}",
                    force=True
                )

    # ── Aimsun canvas overlay — GKAnnotation markers in the network view ────────
    # Creates persistent markers visible in the Aimsun network editor.
    # Independent of the PNG/HTML outputs — runs even if those fail.
    if MARK_DETECTION_POINTS and _geojson_features:
        _overlay_detections_on_aimsun_map()
    elif OVERLAY_DETECTIONS_ON_MAP and not _geojson_features:
        log_to_file(
            f"[MAP] No detections collected — GeoJSON at {_DET_GEOJSON} for "
            "manual import via File > Import in Aimsun",
            force=True
        )

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
