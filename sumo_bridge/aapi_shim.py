# aapi_shim.py
# Drop-in replacement for Aimsun's SWIG `AAPI` module, backed by TraCI.
#
# The runner installs this as sys.modules["AAPI"] BEFORE importing
# shared_tsp_engine.engine / corridor scripts, so `from AAPI import *`
# resolves here and the unmodified engine runs against SUMO.
#
# Fidelity notes (verify during calibration):
# - speeds are m/s, positions metres, times seconds (Aimsun micro API units)
# - detector counters approximate Aimsun cycle/aggregated semantics
# - ECIChangeTimingPhase on a non-active phase is applied when it turns green

import json
import os
import time as _time

try:
    import traci
except ImportError:  # runner adds SUMO tools to sys.path first
    traci = None


class SimulationStopped(Exception):
    pass


# --------------------------------------------------------------- out params
class _OutParam(object):
    def __init__(self, v=0.0):
        self._v = v
    def assign(self, v):
        self._v = v
    def value(self):
        return self._v
    def __repr__(self):
        return "<%s %s>" % (type(self).__name__, self._v)


def doublep(v=0.0):  return _OutParam(float(v))
def floatp(v=0.0):   return _OutParam(float(v))
def intp(v=0):       return _OutParam(int(v))


# ------------------------------------------------------------------- structs
class _S(object):
    """generic duck-typed struct"""
    def __init__(self, **kw):
        self.report = 0
        for k, v in kw.items():
            setattr(self, k, v)


# ------------------------------------------------------------------- bridge
class Bridge(object):
    def __init__(self):
        self.conn = None            # traci module-level API bound to our conn
        self.scenario_dir = None
        self.replication_id = 11129240
        self.scenario_id = 11129236
        self.experiment_id = 11129237
        self.step_length = 1.0
        self.aggregation_s = 60.0   # AKIDetGetCounterAggregatedbyId window

        self.now = 0.0
        self.stopped = False

        # net registries (filled by init_net)
        self.section_ids = []       # aimsun section ids (int)
        self.edge_of_section = {}   # sid -> edge id str ("s<sid>")
        self.section_of_edge = {}
        self.edge_len = {}
        self.edge_lanes = {}
        self.edge_speed = {}        # m/s
        self.node_turns = {}        # node int -> [(turn_id, from_sid, to_sid)]
        self.turn_info = {}         # turn_id -> (node, from_sid, to_sid)

        # tls state
        self.tls_phases = {}        # tls id -> [ {duration,state} ]
        self.tls_cur = {}           # tls id -> phase idx
        self.tls_start = {}         # tls id -> sim time phase started
        self.tls_pending = {}       # tls id -> {phase idx: duration override}

        # detectors
        self.det_order = []         # aimsun det ids in enumeration order
        self.det_meta = {}          # did -> meta dict
        self.det_hist = {}          # did -> list[(t,count)]
        self.det_cycle = {}         # did -> vehicles since last cycle reset
        self.det_cycle_bus = {}     # did -> BUSES since last cycle reset
        # AKIDetGetCounterCyclebyId is per-CYCLE in Aimsun (system resets it,
        # reads are non-destructive).  Emulate with a fixed window; default
        # matches the kg corridor's TSP_CYCLE_LENGTH_OVERRIDE_S.
        self.det_cycle_len_s = float(os.environ.get("DET_CYCLE_RESET_S", "135"))
        self._det_cycle_reset_t = None

        # vehicles
        self._vid_int = {}
        self._int_vid = {}
        self._next_vid = 1
        self.sec_vehs = {}          # sid -> [InfVeh] for current step
        self.vtypes = ["car", "bus"]
        self.bus_type_pos = 1
        # per-step caches (cleared in step_refresh)
        self._veh_cache = {}        # sumo vid -> InfVeh struct
        self._bus_ids_cache = []
        self.line_bus_vids = {}     # line -> [veh int ids]
        self.line_bus_count = {}
        self._sec_stats = {}        # sid -> stats struct (per step memo)
        self._global_stats = None

        # PT lines: line_id -> {"sections":[sid...], "name":str}
        self.pt_lines = {}

    # ------------------------------------------------------------ lifecycle
    def init(self, traci_api, scenario_dir, replication_id=11129240,
             scenario_id=11129236, experiment_id=11129237, step_length=1.0):
        import xml.etree.ElementTree as ET
        self.conn = traci_api
        self.scenario_dir = scenario_dir
        self.replication_id = replication_id
        self.scenario_id = scenario_id
        self.experiment_id = experiment_id
        self.step_length = step_length
        self.now = 0.0

        # edges exist right after load; find them
        self.section_ids = []
        for e in sorted(self.conn.edge.getIDList()):
            if not e.startswith("s"):
                continue
            try:
                sid = int(e[1:])
            except ValueError:
                continue
            self.section_ids.append(sid)
            self.edge_of_section[sid] = e
            self.section_of_edge[e] = sid
            lanes = self.conn.edge.getLaneNumber(e)
            self.edge_lanes[e] = lanes
            self.edge_len[e] = self.conn.lane.getLength("%s_0" % e)
            self.edge_speed[e] = self.conn.lane.getMaxSpeed("%s_0" % e)

        # parse net.xml once: connections per tls -> turn registry + link states
        net_path = None
        for cand in os.listdir(scenario_dir):
            if cand.endswith(".net.xml"):
                net_path = os.path.join(scenario_dir, cand)
                break
        if net_path:
            root = ET.parse(net_path).getroot()
            links_by_tls = {}
            for c in root.iter("connection"):
                tl = c.get("tl")
                if not tl:
                    continue
                idx = int(c.get("linkIndex", "0"))
                links_by_tls.setdefault(tl, []).append((idx, c.get("from"), c.get("to")))
            for tl, links in links_by_tls.items():
                node = self._node_int(tl)
                turns = []
                for idx, fe, te in sorted(links):
                    tid = node * 1000 + idx
                    fsid = self.section_of_edge.get(fe)
                    tsid = self.section_of_edge.get(te)
                    if fsid is None or tsid is None:
                        continue
                    self.turn_info[tid] = (node, fsid, tsid)
                    turns.append((tid, fsid, tsid))
                self.node_turns[node] = turns
                logics = self.conn.trafficlight.getAllProgramLogics(tl)
                phases = [{"duration": float(p.duration), "state": p.state}
                          for p in logics[0].phases]
                self.tls_phases[tl] = phases
                self.tls_start[tl] = 0.0

        # detectors metadata written by build_sumo_scenario.py
        dm = os.path.join(scenario_dir, "detectors_meta.json")
        if os.path.exists(dm):
            with open(dm, encoding="utf-8") as f:
                raw = json.load(f)
            for did_s, m in raw.items():
                did = int(did_s)
                self.det_meta[did] = m
                self.det_order.append(did)
                self.det_hist[did] = []
                self.det_cycle[did] = 0

        # PT lines metadata
        pm = os.path.join(scenario_dir, "pt_meta.json")
        if os.path.exists(pm):
            with open(pm, encoding="utf-8") as f:
                self.pt_lines = json.load(f)

    @staticmethod
    def _node_int(tls_id):
        try:
            return int(str(tls_id).lstrip("n"))
        except ValueError:
            return -1

    def step_refresh(self):
        """call after each simulationStep - single-pass vehicle snapshot"""
        self.now += self.step_length
        # tls bookkeeping
        for tl in self.tls_phases:
            ph = self.conn.trafficlight.getPhase(tl)
            if self.tls_cur.get(tl) != ph:
                self.tls_cur[tl] = ph
                self.tls_start[tl] = self.now
                pend = self.tls_pending.pop(tl, None)
                if pend and ph in pend:
                    remaining = max(float(pend[ph]) - self.phase_elapsed(tl), 0.1)
                    self.conn.trafficlight.setPhaseDuration(tl, remaining)
        # ---- one traci call-set per vehicle; everything else reads cache ----
        self.sec_vehs.clear()
        self._veh_cache.clear()
        self._sec_stats.clear()
        self._global_stats = None
        line_bus_vids = {}
        for vid in list(self.conn.vehicle.getIDList()):
            try:
                vtype = self.conn.vehicle.getTypeID(vid)
            except Exception:
                continue  # departed between getIDList and getTypeID
            try:
                _line = self.conn.vehicle.getLine(vid) or ""
            except Exception:
                _line = ""
            is_bus = vtype in ("bus", "pt_bus", "Bus") or _line != ""
            tpos = self._type_pos_cached(vtype)
            lane = ""
            try:
                lane = self.conn.vehicle.getLaneID(vid)
            except Exception:
                continue
            if not lane or lane.startswith(":"):
                continue
            edge = lane.rsplit("_", 1)[0]
            sid = self.section_of_edge.get(edge)
            if sid is None:
                continue
            try:
                x, y = self.conn.vehicle.getPosition(vid)
            except Exception:
                continue
            try:
                inf = _S(
                    report=0,
                    idVeh=self._int_id(vid),
                    idSection=sid,
                    CurrentPos=float(self.conn.vehicle.getLanePosition(vid)),
                    CurrentSpeed=float(self.conn.vehicle.getSpeed(vid)) * 3.6,
                    speed=float(self.conn.vehicle.getSpeed(vid)),
                    xCurrentPos=float(x), yCurrentPos=float(y),
                    xCoord=float(x), yCoord=float(y),
                    typePos=tpos, type=tpos,
                    laneIndex=int(self.conn.vehicle.getLaneIndex(vid)),
                    sumo_id=vid,
                )
            except Exception:
                continue
            self._veh_cache[vid] = inf
            self.sec_vehs.setdefault(sid, []).append(inf)
            if is_bus:
                try:
                    line = self.conn.vehicle.getLine(vid) or "BUS"
                except Exception:
                    line = "BUS"
                line_bus_vids.setdefault(line, []).append(inf.idVeh)
        for sid in self.sec_vehs:
            self.sec_vehs[sid].sort(key=lambda i: i.CurrentPos)
        # PT line membership (section sets prepared once per line at init)
        self.line_bus_vids = {}
        self.line_bus_count = {}
        if not hasattr(self, "_line_sec_sets"):
            self._line_sec_sets = {
                lid: set(m.get("sections", []))
                for lid, m in self.pt_lines.items()}
        for line, vids in line_bus_vids.items():
            secs = self._line_sec_sets.get(str(line))
            if secs is None:
                # unknown line id: attribute to lines whose route contains them
                for lid, lsecs in self._line_sec_sets.items():
                    hit = [v for v in vids
                           if self._veh_cache[self._int_vid[v]].idSection in lsecs]
                    if hit:
                        self.line_bus_vids.setdefault(lid, []).extend(hit)
            else:
                hit = [v for v in vids
                       if self._veh_cache[self._int_vid[v]].idSection in secs]
                if hit:
                    self.line_bus_vids[line] = hit
        for lid, vs in self.line_bus_vids.items():
            self.line_bus_count[lid] = len(vs)
        # detector counters
        # per-cycle reset window (Aimsun cycle-counter semantics)
        if self._det_cycle_reset_t is None:
            self._det_cycle_reset_t = self.now
        elif self.now - self._det_cycle_reset_t >= self.det_cycle_len_s:
            for _k in self.det_cycle:          # keep pre-seeded keys
                self.det_cycle[_k] = 0
            self.det_cycle_bus = {}            # sparse dict, safe to replace
            self._det_cycle_reset_t = self.now
        for did, m in self.det_meta.items():
            try:
                n = int(self.conn.inductionloop.getLastStepVehicleNumber(m["sumo_id"]))
            except Exception:
                n = 0
            if n > 0:
                self.det_hist[did].append((self.now, n))
                self.det_cycle[did] += n
                try:
                    vids = self.conn.inductionloop.getLastStepVehicleIDs(
                        m["sumo_id"]) or []
                    nb = 0
                    for sv in vids:
                        try:
                            vt = str(self.conn.vehicle.getTypeID(sv)).lower()
                        except Exception:
                            continue
                        if "bus" in vt:
                            nb += 1
                    if nb:
                        self.det_cycle_bus[did] = (
                            self.det_cycle_bus.get(did, 0) + nb)
                except Exception:
                    pass
            cutoff = self.now - self.aggregation_s
            h = self.det_hist[did]
            while h and h[0][0] < cutoff:
                h.pop(0)
        self._bus_ids_cache = [
            inf.sumo_id for inf in self._veh_cache.values()
            if getattr(inf, "typePos", 0) == self.bus_type_pos]
        if self.stopped:
            raise SimulationStopped()

    # ------------------------------------------------------------- helpers
    def _int_id(self, sumo_vid):
        iv = self._vid_int.get(sumo_vid)
        if iv is None:
            iv = self._next_vid
            self._next_vid += 1
            self._vid_int[sumo_vid] = iv
            self._int_vid[iv] = sumo_vid
        return iv

    def _sumo_id(self, veh_int):
        return self._int_vid.get(veh_int)

    def _type_pos(self, sumo_vid):
        inf = self._veh_cache.get(sumo_vid)
        if inf is not None:
            return inf.typePos
        try:
            t = self.conn.vehicle.getTypeID(sumo_vid)
        except Exception:
            return 0
        return self._type_pos_cached(t)

    def _type_pos_cached(self, tname):
        if tname in ("bus", "pt_bus", "Bus"):
            return self.bus_type_pos
        if tname not in self.vtypes:
            self.vtypes.append(tname)
        try:
            return max(self.vtypes.index(tname), 0)
        except ValueError:
            return 0

    def phase_elapsed(self, tl):
        return max(self.now - self.tls_start.get(tl, self.now), 0.0)

    def _tls_key(self, node):
        k = "n%d" % int(node)
        return k if k in self.tls_phases else None

    def bus_ids(self):
        return list(self._bus_ids_cache)


BRIDGE = Bridge()


# ===========================================================================
# AAPI surface
# ===========================================================================
def _sid(edge):
    try:
        return int(str(edge)[1:])
    except (TypeError, ValueError):
        return -1


def AKIPrintString(s):
    print("[AAPI] %s" % s)
    return 0


def AKIGetCurrentSimulationTime():
    return BRIDGE.now


def AKIGetSimulationTime():
    return BRIDGE.now


def AKISimulationStop():
    BRIDGE.stopped = True
    return 0


def AKISetSimulationStopped(flag):
    BRIDGE.stopped = bool(flag)
    return 0


def AKIConvertFromAsciiString(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return hash(str(s)) & 0x7fffffff


def AKIConvertToAsciiString(i):
    return str(i)


# -------------------------------------------------------------- detectors
def AKIDetGetNumberDetectors():
    return len(BRIDGE.det_order)


def AKIDetGetIdDetector(index):
    return BRIDGE.det_order[index]


def AKIDetGetPropertiesDetectorById(det_id):
    m = BRIDGE.det_meta.get(int(det_id))
    if not m:
        return _S(report=-1)
    return _S(report=0, IdSection=_sid(m["edge"]), InitialPosition=float(m["pos"]),
              FinalPosition=float(m["pos"]) + float(m.get("length", 2.0)),
              LaneId=m.get("lane", 0))


def AKIDetGetCounterAggregatedbyId(det_id, interval_idx=0):
    return int(sum(n for _t, n in BRIDGE.det_hist.get(int(det_id), [])))


def AKIDetGetCounterCyclebyId(det_id, bus_type_pos=None):
    """Per-cycle detector counter.  Aimsun's is NON-destructive (the system
    resets it each cycle); the old shim reset on read, so the engine's second
    read of the same detector in a tick always saw 0.  When bus_type_pos is
    given, count BUSES only -- that is how the engine calls it."""
    did = int(det_id)
    if bus_type_pos is None:
        return int(BRIDGE.det_cycle.get(did, 0))
    if int(bus_type_pos) == int(getattr(BRIDGE, "bus_type_pos", 1)):
        return int(BRIDGE.det_cycle_bus.get(did, 0))
    # other vehicle-type positions: only car/bus exist in the bridge demand
    return int(BRIDGE.det_cycle.get(did, 0)) - int(BRIDGE.det_cycle_bus.get(did, 0))


# --------------------------------------------------------------- vehicles
def AKIVehStateGetNbVehiclesSection(sec, include_exiting=True):
    return len(BRIDGE.sec_vehs.get(int(sec), []))


def AKIVehStateGetVehicleInfSection(sec, index):
    lst = BRIDGE.sec_vehs.get(int(sec))
    if not lst or index >= len(lst) or index < 0:
        return _S(report=-4002)
    return lst[index]


def AKIVehGetNbVehTypes():
    return len(BRIDGE.vtypes)


def AKIVehGetVehTypeNamePos(pos):
    return BRIDGE.vtypes[pos] if 0 <= pos < len(BRIDGE.vtypes) else ""


def AKIVehGetVehTypeName(pos):
    return AKIVehGetVehTypeNamePos(pos)


def AKIVehGetVehTypeInternalPosition(name):
    n = str(name).lower()
    for i, t in enumerate(BRIDGE.vtypes):
        if t.lower() == n:
            return i
    return 0


def AKIVehSetVehicleColor(veh_id, color):
    return 0


def AKIVehGetVehicleStaticInfSection(veh_id, section=None):
    vid = BRIDGE._sumo_id(int(veh_id))
    if not vid:
        return _S(report=-1)
    return _S(report=0, idVeh=int(veh_id),
              type=BRIDGE._type_pos(vid), typePos=BRIDGE._type_pos(vid),
              length=12.0 if BRIDGE._type_pos(vid) == BRIDGE.bus_type_pos else 4.5)


def AKIVehInfPath(veh_id):
    return _S(report=-1, sections=[])


# ----------------------------------------------------------------- PT lines
def _line_ids():
    return sorted(BRIDGE.pt_lines.keys(), key=lambda x: int(x) if str(x).isdigit() else 0)


def AKIPTGetNumberLines():
    return len(BRIDGE.pt_lines)


def AKIPTGetIdLine(i):
    ids = _line_ids()
    return int(ids[i]) if i < len(ids) and str(ids[i]).isdigit() else 1


def AKIPTGetNumberSectionsInLine(line):
    return len(BRIDGE.pt_lines.get(str(line), {}).get("sections", []))


def AKIPTGetIdSectionInLine(line, i):
    secs = BRIDGE.pt_lines.get(str(line), {}).get("sections", [])
    return int(secs[i])


def AKIGetNbVehiclesFollowingPTLine(line):
    return int(BRIDGE.line_bus_count.get(str(line), 0))


def AKIGetVehicleFollowingPTLine(line, vi):
    vids = BRIDGE.line_bus_vids.get(str(line), [])
    if 0 <= vi < len(vids):
        return vids[vi]
    return -1


def AKIPTVehGetInf(veh_id):
    vid = BRIDGE._sumo_id(int(veh_id))
    inf = BRIDGE._veh_cache.get(vid) if vid else None
    if inf is None:
        return _S(report=-1)
    # reuse the cached snapshot; add point-like accessors
    inf.getX = lambda: inf.xCurrentPos
    inf.getY = lambda: inf.yCurrentPos
    inf.line = ""
    return inf


# ------------------------------------------------------------------ network
def AKIInfNetNbSectionsANG():
    return len(BRIDGE.section_ids)


def AKIInfNetGetSectionANGId(i):
    return BRIDGE.section_ids[i]


def AKIInfNetGetSectionANGInf(sid):
    e = BRIDGE.edge_of_section.get(int(sid))
    if not e:
        return _S(report=-1)
    return _S(report=0, IdSection=int(sid),
              length=float(BRIDGE.edge_len[e]),
              numberLanes=int(BRIDGE.edge_lanes[e]),
              idNodeFrom=-1, idNodeTo=-1,
              speed=float(BRIDGE.edge_speed[e]))


def AKIInfNetGetNbTurnsInNode(node):
    return len(BRIDGE.node_turns.get(int(node), []))


def _turn_at(node, ti):
    """Aimsun signature: (node_id, turn_index) -> (from_sid, to_sid) or None"""
    turns = BRIDGE.node_turns.get(int(node))
    if not turns:
        return None
    i = int(ti)
    if 0 <= i < len(turns):
        return turns[i][1], turns[i][2]
    return None


def AKIInfNetGetOriginSectionInTurn(node, ti=0):
    t = _turn_at(node, ti)
    return t[0] if t else -1


def AKIInfNetGetDestinationSectionInTurn(node, ti=0):
    t = _turn_at(node, ti)
    return t[1] if t else -1


def ANGConnGetObjectIdByType(obj_type):
    t = str(obj_type).lower()
    if "detect" in t:
        return list(BRIDGE.det_order)
    if "junction" in t or "node" in t:
        return sorted({ti[0] for ti in BRIDGE.turn_info.values()})
    if "section" in t:
        return list(BRIDGE.section_ids)
    return []


def ANGConnGetReplicationId():
    return BRIDGE.replication_id


def ANGConnGetScenarioId():
    return BRIDGE.scenario_id


def ANGConnGetExperimentId():
    return BRIDGE.experiment_id


def AKIInfNetNbCentroids():
    return 0


def AKIInfNetGetCentroidId(_i):
    return -1


# ------------------------------------------------------------------ control
def ECIGetControlType(node):
    # Aimsun: 0=none, 1=fixed, 2=external(API), 3=actuated - engines gate on 2/3
    return 2 if BRIDGE._tls_key(node) else 0


def ECIGetNumberPhases(node):
    k = BRIDGE._tls_key(node)
    return len(BRIDGE.tls_phases[k]) if k else 0


def ECIGetCurrentPhase(node):
    k = BRIDGE._tls_key(node)
    return BRIDGE.tls_cur.get(k, 0) if k else -1


def ECIGetStartingTimePhase(node):
    k = BRIDGE._tls_key(node)
    return float(BRIDGE.tls_start.get(k, 0.0)) if k else 0.0


def ECIChangeDirectPhase(node, phase, timeSta, simtime, acycle, flag=0):
    k = BRIDGE._tls_key(node)
    if not k:
        return -1
    BRIDGE.conn.trafficlight.setPhase(k, int(phase))
    BRIDGE.tls_cur[k] = int(phase)
    BRIDGE.tls_start[k] = BRIDGE.now
    return 0


def ECIChangeTimingPhase(node, phase, new_duration, timeSta):
    k = BRIDGE._tls_key(node)
    if not k:
        return -1
    cur = BRIDGE.tls_cur.get(k, 0)
    if int(phase) == cur:
        remaining = max(float(new_duration) - BRIDGE.phase_elapsed(k), 0.1)
        BRIDGE.conn.trafficlight.setPhaseDuration(k, remaining)
    else:
        BRIDGE.tls_pending.setdefault(k, {})[int(phase)] = float(new_duration)
    return 0


def ECIGetDurationsPhase(node, phase, timeSta, normal_p=None, max_p=None, min_p=None):
    k = BRIDGE._tls_key(node)
    dur = 0.0
    if k:
        phs = BRIDGE.tls_phases[k]
        i = int(phase)
        dur = phs[i]["duration"] if 0 <= i < len(phs) else 30.0
        pend = BRIDGE.tls_pending.get(k, {}).get(i)
        if pend:
            dur = pend
    if normal_p is not None:
        normal_p.assign(dur)
    if max_p is not None:
        max_p.assign(dur)
    if min_p is not None:
        min_p.assign(dur)
    return 0


def ECIEnableEventsActivatingPhase(node, phase, enable):
    return 0


def ECIGetNbSignalGroupsPhaseofJunction(node, phase):
    k = BRIDGE._tls_key(node)
    if not k:
        return 0
    st = BRIDGE.tls_phases[k][int(phase)]["state"]
    return sum(1 for c in st if c in "gG")


def ECIGetSignalGroupPhaseofJunction(node, phase, sg_index):
    k = BRIDGE._tls_key(node)
    if not k:
        return -1
    st = BRIDGE.tls_phases[k][int(phase)]["state"]
    greens = [i for i, c in enumerate(st) if c in "gG"]
    return greens[sg_index] if sg_index < len(greens) else -1


# -------------------------------------------------------------------- stats
_AGG_WINDOW_S = 300.0


def _section_stats(sec):
    memo = BRIDGE._sec_stats.get(int(sec))
    if memo is not None:
        return memo
    st = _build_section_stats(sec)
    BRIDGE._sec_stats[int(sec)] = st
    return st


def _build_section_stats(sec):
    e = BRIDGE.edge_of_section.get(int(sec))
    if not e:
        return _S(report=-1)
    count = int(BRIDGE.conn.edge.getLastStepVehicleNumber(e))
    speed = float(BRIDGE.conn.edge.getLastStepMeanSpeed(e))
    flow = count * 3600.0 / _AGG_WINDOW_S
    length = float(BRIDGE.edge_len[e])
    dens = count * 1000.0 / max(length * BRIDGE.edge_lanes[e], 1.0)
    free_t = length / max(float(BRIDGE.edge_speed[e]), 1e-3)
    tt = length / speed if speed > 0.5 else length / max(free_t, 1e-3) * 10.0
    dta = max(tt - free_t, 0.0)          # mean delay per vehicle (s)
    return _S(report=0, IdSection=int(sec), count=count, flow=flow,
              speed=speed, density=dens, DTa=dta, dtime=dta,
              input_count=count, input_flow=flow,
              traveltime=tt,
              qmean=0.0, qmax=0.0, wtimeVQ=0.0, stime=0.0, nstops=0)


def AKIEstGetCurrentStatisticsSection(sec, tp=0):
    return _section_stats(sec)


def AKIEstGetParcialStatisticsSection(sec, tim_sta=0.0, tp=0):
    return _section_stats(sec)


def AKIEstGetGlobalStatisticsSection(sec, tp=0):
    return _section_stats(sec)


def AKIEstGetGlobalStatisticsSystem(tp=0):
    if BRIDGE._global_stats is not None:
        return BRIDGE._global_stats
    tot_count = 0
    tot_flow = 0.0
    w_speed = 0.0
    tot_delay = 0.0
    for e in BRIDGE.section_of_edge:
        try:
            c = int(BRIDGE.conn.edge.getLastStepVehicleNumber(e))
            s = float(BRIDGE.conn.edge.getLastStepMeanSpeed(e))
        except Exception:
            continue
        tot_count += c
        tot_flow += c * 3600.0 / _AGG_WINDOW_S
        w_speed += s * c
        length = float(BRIDGE.edge_len[e])
        free_t = length / max(float(BRIDGE.edge_speed[e]), 1e-3)
        tt = length / s if s > 0.5 else free_t * 10.0
        tot_delay += max(tt - free_t, 0.0) * c
    return _S(report=0, count=tot_count, flow=tot_flow,
              speed=(w_speed / tot_count if tot_count else 0.0),
              density=0.0, DTa=(tot_delay / tot_count if tot_count else 0.0),
              travel=tot_count, traveltime=0.0, dtime=0.0)


# ----------------------------------------------------------------------- OD
def AKIODDemandGetNumSlicesOD(_a=0, _b=0):
    return 1


def AKIODDemandGetDemandODPair(_matrix=0, _origin=0, _dest=0, _slice=0, _tpos=0):
    return 0.0


# keep a reference so `import time` inside engine never shadows anything we need
_TIME = _time
