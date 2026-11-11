#!/usr/bin/env python3
r"""port_vloop.py -- port the TACTICAL VIRTUAL LOOP layer to the SUMO fork.

Aimsun places real point detectors per approach from the approach's own
geometry and feeds a crossing/occupancy emulator. The fork had none of it, so
`_vlt_advance_vph` fell back to the section's rolling-window crossing count --
the whole section, queue included -- and the CTM2 payoff therefore priced
arrivals measured THROUGH the queue instead of upstream of it.

What this script does, all idempotent:

  1. copies `shockwave_lwr.py` and `vloop_layout.py` (stdlib-only siblings)
  2. adds Aimsun's `numberLane` to the AAPI shim's per-vehicle row -- the loop
     bank reads it, and the shim only published `laneIndex`, so every scan row
     would have been swallowed and the bank would have measured nothing
  3. adds the engine `_vlt` layer: import + `_sec_len_m` + `_VLT` state +
     `_vlt_reset/_vlt_ledger/_vlt_scan/_vlt_tick_all/_vlt_finish`
  4. adds the controller methods: `_sw_lane_fd`, `_vlt_init`, `_vlt_secs`,
     `_vlt_tick`, `_vlt_log`, `_vlt_learn_stops`, `_vlt_build`, `_vlt_loops`,
     `_vlt_checks`, `_vlt_sat_check`, and Aimsun's own `_vlt_advance_vph`
     (replacing the section-window stub)
  5. hooks `_vlt_tick_all` into `_aapi_post_manage_impl`, `_vlt_reset()` into
     `AAPIInit`, `_vlt_finish()` into `AAPIFinish`
  6. gates the CTM2 arrival read on `VLOOP_TAC_FEED_CTM`, as Aimsun does
  7. declares the VLOOP_*/ASSUME_* knobs + MODE_FLAGS entries

Not ported (deliberate): `_vlt_ctm_sample` and `_vlt_tikz_data` feed the TikZ
figures from `tikz_phase.py`, which this tree does not carry; `TIKZ_EXPORT`
defaults False and the sample block is absent. The loop layer, the ledger and
its two CSVs are fully ported.

Usage:
    python _sumo_port/port_vloop.py --check   # anchors only, writes nothing
    python _sumo_port/port_vloop.py           # apply
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(HERE, '..', 'shared_tsp_engine')
DST_DIR = 'Z:/tsp/sumo_hpc/shared_tsp_engine'
SHIM = 'Z:/tsp/sumo_hpc/sumo_bridge/aapi_shim.py'

ENGINE_BUILD_OLD = 'ENGINE_BUILD = "2026-11-06T1500-sumo-ctm2-payoffs"'
ENGINE_BUILD_NEW = 'ENGINE_BUILD = "2026-11-06T1700-sumo-vloop-tactical"'

# ─────────────────────────────────────────────────────────────── text helpers
def read(path):
    with open(path, 'r', encoding='utf-8', newline='') as fh:
        raw = fh.read()
    nl = '\r\n' if '\r\n' in raw else '\n'
    return raw.replace('\r\n', '\n'), nl


def write(path, text, nl):
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(text.replace('\n', nl) if nl != '\n' else text)


def once(text, anchor, what):
    n = text.count(anchor)
    if n != 1:
        raise SystemExit('ANCHOR %s: expected 1 occurrence, found %d' % (what, n))
    return text.index(anchor)


def replace_method(text, name, block, what):
    """Replace `    def name(...)` through the line before the next indent-4 def."""
    head = '    def %s(' % name
    i = once(text, head, what)
    j = text.index('\n', i) + 1
    # walk to the next top-of-class def
    k = j
    while True:
        nxt = text.find('\n    def ', k)
        if nxt < 0:
            raise SystemExit('ANCHOR %s: no following def' % what)
        # a decorator or a nested def at deeper indent cannot match '\n    def '
        return text[:i] + block + text[nxt + 1:]


# ──────────────────────────────────────────────────── 1. sibling modules
MODULES = ('shockwave_lwr.py', 'vloop_layout.py')


def copy_modules(check):
    done = []
    for m in MODULES:
        s = os.path.join(SRC_DIR, m)
        d = os.path.join(DST_DIR, m)
        if not os.path.isfile(s):
            raise SystemExit('missing source module %s' % s)
        exists = os.path.isfile(d)
        same = False
        if exists:
            with open(s, 'rb') as a, open(d, 'rb') as b:
                same = a.read() == b.read()
        done.append((m, 'identical' if same else ('would copy' if check else 'copied')))
        if not check and not same:
            with open(s, 'rb') as a, open(d, 'wb') as b:
                b.write(a.read())
    return done


# ──────────────────────────────────────────────────── 2. AAPI shim field
SHIM_OLD = """                    laneIndex=int(self.conn.vehicle.getLaneIndex(vid)),
"""
SHIM_NEW = """                    laneIndex=int(self.conn.vehicle.getLaneIndex(vid)),
                    # Aimsun's InfVeh.numberLane (1-based). The tactical loop
                    # bank (_vlt_scan) filters vehicles by it; publishing only
                    # laneIndex made every row unreadable there.
                    numberLane=int(self.conn.vehicle.getLaneIndex(vid)) + 1,
"""


def patch_shim(check):
    text, nl = read(SHIM)
    if 'numberLane=' in text:
        return 'already present'
    once(text, SHIM_OLD, 'shim laneIndex row')
    if check:
        return 'would add numberLane'
    write(SHIM, text.replace(SHIM_OLD, SHIM_NEW, 1), nl)
    return 'added numberLane'


# ──────────────────────────────────────────────────── 3. engine module layer
ENGINE_OLD_BLOCK = """# VIRTUAL LOOP LAYER: Aimsun builds one in _vlt_build from vloop_layout. This
# build carries no vloop_layout module, so _vlt stays None and
# _vlt_advance_vph measures the section's rolling-window crossings instead
# (see its docstring). Kept optional so a future port can switch it on.
try:
    try:
        from . import vloop_layout as _vll
    except ImportError:
        import vloop_layout as _vll
except Exception:
    _vll = None
"""

ENGINE_NEW_BLOCK = """# ── TACTICAL VIRTUAL LOOPS (ported 2026-11-06) ───────────────────────────────
# vloop_layout.py places point detectors per approach from THIS approach's own
# geometry and timing (STOPBAR 2 m before the line, QUEUE_MID/TAIL at the
# shockwave max queue, ADVANCE upstream of it, BAY_ENTRY, CTM_INFLOW,
# BUS_CHECKIN, EXIT, SPILLBACK), emulates their crossings/occupancy from the
# per-tick vehicle scan, and keeps a ledger of every model prediction vs what
# the vehicles did. shockwave_lwr.py is its fundamental-diagram sibling. Both
# are stdlib-only, so the fork now measures arrival flow UPSTREAM of the queue
# exactly as Aimsun does, instead of through the whole section.
try:
    try:
        from . import shockwave_lwr as _swl
    except ImportError:
        import shockwave_lwr as _swl
    _SWL_AVAILABLE = True
except Exception as _swl_err:   # pragma: no cover
    _swl = None
    _SWL_AVAILABLE = False

try:
    try:
        from . import vloop_layout as _vll
    except ImportError:
        import vloop_layout as _vll
    _VLL_AVAILABLE = True
except Exception as _vll_err:   # pragma: no cover
    _vll = None
    _VLL_AVAILABLE = False
    _VLL_IMPORT_ERR = repr(_vll_err)

_SEC_LEN_CACHE = {}


def _sec_len_m(sec):
    \"\"\"Section length (m), cached; 0.0 when the section is not readable.\"\"\"
    try:
        _k = int(sec)
    except Exception:
        return 0.0
    _v = _SEC_LEN_CACHE.get(_k)
    if _v is None:
        _v = 0.0
        try:
            _si = AKIInfNetGetSectionANGInf(_k)
            if getattr(_si, 'report', -1) >= 0:
                _v = float(getattr(_si, 'length', 0.0) or 0.0)
        except Exception as _swx:
            _note_swallow('_sec_len_m#1', _swx)
        _SEC_LEN_CACHE[_k] = _v
    return _v


# Per-replication state of the tactical loops: the shared assumption ledger,
# the tick clock and a one-scan-per-section vehicle cache shared by every
# junction in the same tick.
_VLT = {'ledger': None, 'tick_t': -1.0e9, 'scan_t': None, 'scan': {},
        'errs': 0}


def _vlt_reset():
    _VLT['ledger'] = _vll.AssumptionLedger() if _VLL_AVAILABLE else None
    _VLT['tick_t'] = -1.0e9
    _VLT['scan_t'] = None
    _VLT['scan'] = {}
    _VLT['errs'] = 0


def _vlt_ledger():
    if _VLT.get('ledger') is None and _VLL_AVAILABLE:
        _VLT['ledger'] = _vll.AssumptionLedger()
    return _VLT.get('ledger')


def _vlt_scan(secs, now, bus_pos):
    \"\"\"{sec: [(vid, CurrentPos, speed_kmh, lane, is_bus)]}, each section read
    at most once per tick however many junctions ask for it.

    `lane` is Aimsun's 1-based InfVeh.numberLane; the shim publishes it and
    falls back to laneIndex+1 for an older shim.
    \"\"\"
    if _VLT['scan_t'] != now:
        _VLT['scan_t'] = now
        _VLT['scan'] = {}
    sc = _VLT['scan']
    for s_ in secs:
        s_ = int(s_)
        if s_ in sc:
            continue
        rows = []
        try:
            for _i in range(max(int(AKIVehStateGetNbVehiclesSection(s_, True)), 0)):
                try:
                    _v = AKIVehStateGetVehicleInfSection(s_, _i)
                    _ln = getattr(_v, 'numberLane', None)
                    if _ln is None:
                        _ln = int(getattr(_v, 'laneIndex', 0) or 0) + 1
                    rows.append((int(_v.idVeh), float(_v.CurrentPos),
                                 float(_v.CurrentSpeed), int(_ln),
                                 bus_pos > 0 and int(getattr(_v, 'type', -1)) == bus_pos))
                except Exception as _swx:
                    _note_swallow('_vlt_scan#2', _swx)
                    continue
        except Exception as _swx:
            _note_swallow('_vlt_scan#1', _swx)
            pass
        sc[s_] = rows
    return sc


def _vlt_tick_all(time, timeSta):
    if not (_VLL_AVAILABLE and bool(globals().get('VLOOP_TACTICAL', True))):
        return
    _dt = float(globals().get('VLOOP_TAC_DT_S', 1.0) or 1.0)
    if float(time) - _VLT['tick_t'] < _dt - 1e-6:
        return
    _VLT['tick_t'] = float(time)
    for _ctrl in list(controllers.values()):
        try:
            _ctrl._vlt_tick(float(time), timeSta)
        except Exception as _e:
            _note_swallow('_vlt_tick_all#1', _e)
            _VLT['errs'] += 1
            if _VLT['errs'] <= 5:
                log_to_file("[VLOOP] jct=%s tick error: %r"
                            % (getattr(_ctrl, 'id', '?'), _e), force=True)
    _lg = _vlt_ledger()
    if _lg is not None:
        _lg.expire(float(time), 900.0)


def _vlt_finish():
    \"\"\"End of replication: [ASSUME_SUMMARY] lines plus assumption_checks.csv
    and vloop_layout.csv in the run folder.\"\"\"
    if not _VLL_AVAILABLE:
        return
    _lg = _vlt_ledger()
    _rows = []
    if _lg is not None and bool(globals().get('ASSUME_CHECKS', True)):
        for _k, _v in sorted(_lg.summary().items()):
            _n, _b, _mae, _p90 = _v
            if _mae is None:
                log_to_file("[ASSUME_SUMMARY] %-34s n=%-5d true=%.0f%%" % (_k, _n, _b),
                            force=True)
            else:
                log_to_file("[ASSUME_SUMMARY] %-34s n=%-5d bias=%+.2f mae=%.2f p90=%.2f"
                            % (_k, _n, _b, _mae, _p90), force=True)
            _rows.append((_k, _n, _b, _mae, _p90))
    _dir = None
    try:
        _dir = stats._run_path()
    except Exception as _swx:
        _note_swallow('_vlt_finish#4', _swx)
        _dir = None
    if not _dir:
        _dir = (globals().get('_CORRIDOR_DIR')
                or os.path.dirname(os.path.abspath(__file__)))
    try:
        os.makedirs(_dir, exist_ok=True)
        with open(os.path.join(_dir, 'assumption_checks.csv'), 'w') as _fh:
            _fh.write("check,n,bias_or_pct_true,mae,p90\\n")
            for _r in _rows:
                _fh.write(",".join("" if x is None else str(x) for x in _r) + "\\n")
        with open(os.path.join(_dir, 'vloop_layout.csv'), 'w') as _fh:
            _fh.write("junction,phase,role,stop_sec,purposes,x_m,sec,pos_m,lanes,"
                      "l_max_m,reach_m,note,warnings\\n")
            for _ctrl in controllers.values():
                for _ap in (getattr(_ctrl, '_vlt', {}) or {}).get('approaches', []):
                    _lay = _ap.get('layout')
                    if _lay is None:
                        continue
                    for _lp in _lay.loops:
                        _fh.write('%s,%s,%s,%s,%s,%.1f,%s,%.1f,%s,%.1f,%.1f,"%s","%s"\\n' % (
                            _lay.spec.junction, _lay.spec.phase, _lay.spec.role,
                            _lay.spec.stop_sec, '+'.join(_lp.purposes), _lp.x_m,
                            _lp.sec, _lp.pos_m, ' '.join(str(x) for x in _lp.lanes),
                            _lay.l_max_m if math.isfinite(_lay.l_max_m) else -1,
                            _lay.reach_m, _lp.note, ' | '.join(_lay.warnings)))
        log_to_file("[VLOOP] wrote assumption_checks.csv / vloop_layout.csv to %s"
                    % _dir, force=True)
    except Exception as _e:
        _note_swallow('_vlt_finish#3', _e)
        log_to_file("[VLOOP] summary write failed: %r" % (_e,), force=True)
"""

# ──────────────────────────────────────────────────── 4. controller methods
METHODS_BLOCK = '''    def _sw_lane_fd(self, sec=None):
        """Per-lane triangular FD for this junction (section speed limit when
        the section is readable, else CELLQ_CTM_FREEFLOW_KMH)."""
        _vf = float(globals().get('CELLQ_CTM_FREEFLOW_KMH', 50.0) or 50.0)
        if sec is not None:
            try:
                _si = AKIInfNetGetSectionANGInf(int(sec))
                _sl = float(getattr(_si, 'speedLimit', 0.0) or 0.0)
                if _sl > 1.0:
                    _vf = _sl
            except Exception as _swx:
                _note_swallow('_sw_lane_fd#1', _swx)
                pass
        return _swl.LaneFD(_vf, float(getattr(self, 'JamDensity', 200.0) or 200.0),
                           float(getattr(self, 'SaturationFlow', 1800.0) or 1800.0))

    # ── tactical virtual loops (vloop_layout) ─────────────────────────────
    def _vlt_init(self):
        """Approach skeleton: for every real green phase, each origin
        (stop-line) section with its upstream chain to the next signal and the
        exit sections its turnings feed."""
        _st = {'approaches': [], 'built': False, 'learner': _vll.LaneUseLearner(),
               'bank': None, 'cur': None, 'cur_t0': None, 'green_log': {},
               'served': {}, 'ctm_acc': {}, 'ctm_n': 0, 'ctm_t': -1e9,
               'bus_still': {}, 'stops_seen': {}, 'pend_bus': {},
               'onset_done': {}, 'adv_t': -1e9, 'rem_t': -1e9, 'log_t': {}}
        self._vlt = _st
        _po = self._phase_origin_sections() or {}
        try:
            _turns = self._cbql_phase_turnings() or {}
        except Exception as _swx:
            _note_swallow('_vlt_init#2', _swx)
            _turns = {}
        _reach = float(globals().get('VLOOP_TAC_REACH_M', 450.0) or 450.0)
        _bp = int(getattr(self, 'BusPhase', -1) or -1)
        for _ph in sorted(_po):
            for _s in sorted(_po[_ph]):
                try:
                    _segs, _why = self._upstream_chain(int(_s), _reach)
                except Exception as _swx:
                    _note_swallow('_vlt_init#1', _swx)
                    _segs, _why = [], 'error'
                _chain = [(int(a), float(b), float(c)) for a, b, c in (_segs or [])
                          if float(c) > 0.0]
                if not _chain:
                    _L = _sec_len_m(int(_s)) or 50.0
                    _chain = [(int(_s), 0.0, _L)]
                _ex = sorted({int(t) for f, t in _turns.get(_ph, []) if int(f) == int(_s)})
                _st['approaches'].append({
                    'phase': int(_ph), 'role': 'bus' if int(_ph) == _bp else 'side',
                    'stop_sec': int(_s), 'chain': _chain, 'why': str(_why),
                    'exits': _ex, 'layout': None, 'loop_idx': []})
        return _st

    def _vlt_secs(self, built):
        _v = self._vlt
        out = set()
        for _ap in _v['approaches']:
            out.update(c[0] for c in _ap['chain'])
            out.update(_ap['exits'])
        return out

    def _vlt_tick(self, time, timeSta):
        _v = getattr(self, '_vlt', None)
        if _v is None:
            if not (self._phase_origin_sections() or {}):
                return
            _v = self._vlt_init()
        _jid = int(getattr(self, 'node_id', 0) or 0) or int(self.id)
        _btp = int(getattr(self, 'bus_type_pos', -1) or -1)
        _veh = _vlt_scan(self._vlt_secs(_v['built']), time, _btp)
        # ---- bus stop-line crossings -> true corridor offsets --------------
        _cc = getattr(self, '_corridor_coord', None)
        if _cc is not None and _btp > 0 and hasattr(_cc, 'record_bus_crossing'):
            try:
                _seen = _v.setdefault('bus_near', {})
                for _ap in _v['approaches']:
                    _ss = int(_ap['stop_sec'])
                    _rows = _veh.get(_ss)
                    if _rows is None:
                        _rows = _vlt_scan([_ss], time, _btp).get(_ss, [])
                    _L = float(_sec_len_m(_ss) or 0.0)
                    _here = {r[0] for r in _rows if r[4]}
                    for _r in _rows:
                        if _r[4] and _L > 0 and _r[1] >= _L - 15.0:
                            _seen[_r[0]] = (_ss, time)
                    # a bus seen at the stop line that has now left the
                    # section has crossed it
                    for _vid, (_s0, _t0) in list(_seen.items()):
                        if _s0 == _ss and _vid not in _here:
                            del _seen[_vid]
                            if time - _t0 < 30.0:
                                _cc.record_bus_crossing(_vid, _jid, time)
            except Exception as _swx:
                _note_swallow('_vlt_tick#cross', _swx)
        _lg = _vlt_ledger()
        _chk = bool(globals().get('ASSUME_CHECKS', True)) and _lg is not None
        # ---- phase tracking (served greens, rem-green check) --------------
        try:
            _cur = int(ECIGetCurrentPhase(_jid))
        except Exception as _swx:
            _note_swallow('_vlt_tick#3', _swx)
            _cur = None
        _greens = {a['phase'] for a in _v['approaches']}
        _bp = int(getattr(self, 'BusPhase', -1) or -1)
        if _cur != _v['cur']:
            _prev, _t0 = _v['cur'], _v['cur_t0']
            if _prev in _greens and _t0 is not None:
                _v['green_log'].setdefault(_prev, []).append(time - _t0)
                if _chk and _prev == _bp:
                    for _k in ('rem_green_nextred_s', 'rem_green_plan_s'):
                        _r = _lg.resolve(_k, (_jid, _t0), time)
                        if _r is not None:
                            self._vlt_log('rem', time, "[ASSUME] jct=%d %s err=%+.1fs "
                                          "(actual end - predicted end; a GE/ER "
                                          "executed in between also shows here)"
                                          % (_jid, _k, _r[0]))
                if _v['built']:
                    self._vlt_sat_check(_prev, _t0, time)
                    for _ap in _v['approaches']:
                        if _ap['phase'] == _prev:
                            _ap['red_t0'] = time
            _v['cur'], _v['cur_t0'] = _cur, time
            if _cur in _greens:
                _v['served'][_cur] = _v['served'].get(_cur, 0) + 1
        # Not on the step the bus green starts: _vlt_tick_all runs BEFORE
        # controller.update() rewrites NextRedStartTime for the new phase, and
        # the ledger keeps the FIRST prediction, so reading it here would score
        # a stale value (error ~ one green length). Read the bus phase's own
        # PhaseIndex row instead.
        if (_chk and _cur == _bp and _v['cur_t0'] is not None
                and time > _v['cur_t0'] + 0.5
                and time - _v['rem_t'] >= 10.0):
            _v['rem_t'] = time
            try:
                _row = int((getattr(self, 'PhaseIndex', None) or {}).get(_bp, 0))
                _nrs = float(self.NextRedStartTime[_row][0])
                if _nrs >= _v['cur_t0']:
                    _lg.predict('rem_green_nextred_s', (_jid, _v['cur_t0']), _nrs, time)
            except Exception as _swx:
                _note_swallow('_vlt_tick#2', _swx)
                pass
            try:
                _lg.predict('rem_green_plan_s', (_jid, _v['cur_t0']),
                            _v['cur_t0'] + float(GetPhaseDuration(_jid, _bp, timeSta)),
                            time)
            except Exception as _swx:
                _note_swallow('_vlt_tick#1', _swx)
                pass
        # ---- warm-up: learn lane use, bays and bus stops ------------------
        _warm = float(globals().get('VLOOP_TAC_WARM_S', 300.0) or 0.0)
        _origins = {a['stop_sec']: a['chain'][0][2] for a in _v['approaches']}
        _exits = set()
        for a in _v['approaches']:
            _exits.update(a['exits'])
        if not _v['built']:
            _v['learner'].observe(_origins, _exits, _veh,
                                  float(globals().get('VLOOP_TAC_DT_S', 1.0) or 1.0))
            self._vlt_learn_stops(time, _veh)
            if time >= _warm:
                self._vlt_build(time, timeSta, _veh)
            return
        # ---- loops --------------------------------------------------------
        _bank = _v['bank']
        if _bank is None:
            return
        _bank.update(time, {s_: _veh.get(s_, ()) for s_ in _bank.secs})
        if _chk:
            self._vlt_checks(time, timeSta)

    def _vlt_log(self, key, time, msg, every=60.0):
        if not bool(globals().get('ASSUME_LOG', True)):
            return
        _lt = self._vlt['log_t']
        if time - _lt.get(key, -1e9) >= every:
            _lt[key] = time
            log_to_file(msg, force=True)

    def _vlt_learn_stops(self, time, veh):
        """A bus held still (<1 km/h, <2 m moved) for >= 5 s with nobody within
        12 m in front of it in its lane is DWELLING: record where, per
        approach, as metres from the stop line."""
        for _ap in self._vlt['approaches']:
            for (_s, _base, _L) in _ap['chain']:
                _rows = veh.get(_s, ())
                for vid, pos, spd, lane, is_bus in _rows:
                    if not is_bus:
                        continue
                    _k = (vid, _s)
                    _p = self._vlt['bus_still'].get(_k)
                    if spd <= 1.0 and _p and abs(pos - _p[0]) < 2.0:
                        if time - _p[1] >= 5.0 and not _p[2]:
                            _blocked = any(l2 == lane and 0.0 < p2 - pos <= 12.0
                                           for v2, p2, s2, l2, b2 in _rows if v2 != vid)
                            if not _blocked:
                                _d = _base + (_L - pos)
                                self._vlt['stops_seen'].setdefault(
                                    _ap['stop_sec'], []).append(_d)
                            self._vlt['bus_still'][_k] = (_p[0], _p[1], True)
                    elif spd <= 1.0:
                        self._vlt['bus_still'][_k] = (pos, time, False)
                    else:
                        self._vlt['bus_still'].pop(_k, None)

    def _vlt_build(self, time, timeSta, veh):
        _v = self._vlt
        _jid = int(getattr(self, 'node_id', 0) or 0) or int(self.id)
        _lg = _vlt_ledger()
        try:
            _cyc = float(self._signal_cycle_s(timeSta) or 120.0)
        except Exception as _swx:
            _note_swallow('_vlt_build#4', _swx)
            _cyc = 120.0
        _all = []
        for _ap in _v['approaches']:
            _s = _ap['stop_sec']
            _L0 = _ap['chain'][0][2]
            _lanes = _v['learner'].lanes_for(_s, set(_ap['exits'])) if _ap['exits'] else ()
            _nl = max(int(self._sec_lane_count(_s) or 1), 1)
            if len(_lanes) >= _nl:
                _lanes = ()                      # every lane -> no lane filter
            _bay = _v['learner'].bay_len(_s, _lanes, _L0) if _lanes else None
            try:
                _side_lanes = int(getattr(AKIInfNetGetSectionANGInf(_s), 'nbSideLanes', 0) or 0)
            except Exception as _swx:
                _note_swallow('_vlt_build#3', _swx)
                _side_lanes = -1
            if _lg is not None and _side_lanes >= 0 and _bay is not None:
                # a bay learned from vehicles should be a side lane in the model
                _lg.flag('learned_bay_is_model_sidelane', _side_lanes > 0)
            # bus stops: cluster the observed dwell points (>= 2 dwells)
            _seen = sorted(_v['stops_seen'].get(_s, []))
            _stops, _grp = [], []
            for _d in _seen + [1e12]:
                if _grp and _d - _grp[-1] > 15.0:
                    if len(_grp) >= 2:
                        _stops.append(_grp[len(_grp) // 2])
                    _grp = []
                _grp.append(_d)
            try:
                _g = float(GetPhaseDuration(_jid, _ap['phase'], timeSta) or 20.0)
            except Exception as _swx:
                _note_swallow('_vlt_build#2', _swx)
                _g = 20.0
            _qa = 0.0
            try:
                _qa = max(0.0, float(self._measured_section_flow_vph(_s) or 0.0))
            except Exception as _swx:
                _note_swallow('_vlt_build#1', _swx)
                pass
            _nlq = max(len(_lanes) if _lanes else _nl, 1)
            _qa_l = (_qa / _nlq) if _qa > 0 else 0.5 * float(getattr(self, 'SaturationFlow', 1800.0))
            _spec = _vll.ApproachSpec(
                _jid, _ap['phase'], _ap['role'], _s, _ap['chain'], _ap['why'],
                tuple(_lanes), _nl, _bay, _stops, _ap['exits'], _qa_l, _cyc, _g)
            _fd = self._sw_lane_fd(_s)
            _lay = _vll.plan_layout(
                _spec, _fd,
                ctm_reach_m=float(globals().get('CBQL_CTM_MAX_CELLS', 12)) *
                max(float(globals().get('CBQL_CTM_DT_S', 2.0)) * _fd.vf, 5.0),
                bus_cruise_kmh=float(globals().get('SW_BUS_CRUISE_KMH', 40.0) or 40.0),
                bus_lead_s=max(float(globals().get('MAX_GE_EXTENSION_S', 10.0) or 10.0)
                               + float(globals().get('INS_INTERGREEN_S', 5.0) or 5.0), 25.0))
            _ap['layout'] = _lay
            _ap['fd'] = _fd
            _ap['loop_idx'] = list(range(len(_all), len(_all) + len(_lay.loops)))
            _all.extend(_lay.loops)
            log_to_file("[VLOOP_LAYOUT] " + _vll.layout_line(_lay)
                        + " | learned: lanes=%s bay=%s stops=%s sideLanes(model)=%s"
                        % (list(_lanes) or 'all', ('%.0fm' % _bay) if _bay else '-',
                           ['%.0fm' % x for x in _stops] or '-', _side_lanes),
                        force=True)
        _v['bank'] = _vll.PointLoopBank(_all, stop_kmh=float(
            globals().get('VLOOP_STOP_KPH', 3.0) or 3.0))
        _v['built'] = True

    def _vlt_loops(self, ap, purpose):
        _b = self._vlt['bank']
        return [_b.loops[i] for i in ap['loop_idx'] if purpose in _b.loops[i].spec.purposes]

    def _vlt_checks(self, time, timeSta):
        _v = self._vlt
        _lg = _vlt_ledger()
        _jid = int(getattr(self, 'node_id', 0) or 0) or int(self.id)
        _adv_due = time - _v['adv_t'] >= 5.0
        if _adv_due:
            _v['adv_t'] = time
        for _ap in _v['approaches']:
            if _ap.get('layout') is None:
                continue
            # (1) ADVANCE must sit upstream of the queue
            if _adv_due:
                for _ls in self._vlt_loops(_ap, 'ADVANCE'):
                    _lg.flag('advance_clear_of_queue_' + _ap['role'], not _ls.stopped_on)
            # (2) queue formation wave: model u vs onsets STOPBAR -> QUEUE loops
            _sb = self._vlt_loops(_ap, 'STOPBAR')
            _rt = _ap.get('red_t0')
            if _sb and _rt is not None:
                _t_sb = [t for t in _sb[0].onsets if t >= _rt - 1.0]
                for _ls in self._vlt_loops(_ap, 'QUEUE_MID') + self._vlt_loops(_ap, 'QUEUE_TAIL'):
                    _key = (id(_ls), _rt)
                    if _key in _v['onset_done'] or not _t_sb:
                        continue
                    _tq = [t for t in _ls.onsets if t > _t_sb[0] + 1.0]
                    if not _tq:
                        continue
                    _v['onset_done'][_key] = True
                    _meas = (_ls.spec.x_m - _sb[0].spec.x_m) / (_tq[0] - _t_sb[0])
                    _adv = self._vlt_loops(_ap, 'ADVANCE')
                    _qa = None
                    if _adv:
                        _rd = _vll.PointLoopBank.reading(_adv[0], time, 300.0)
                        _nl = len(_adv[0].spec.lanes) or max(int(self._sec_lane_count(_ap['stop_sec']) or 1), 1)
                        _qa = _rd['flow_vph'] / _nl
                    if _qa is not None:
                        _mod = _swl.formation_wave_speed(_ap['fd'], _qa)
                        _lg.compare('queue_formation_wave_ms', _mod, _meas)
                        self._vlt_log(('w', _ap['stop_sec']), time,
                                      "[ASSUME] jct=%d ph=%d sec=%d formation wave "
                                      "model=%.2f m/s measured=%.2f m/s (loops %.0fm->%.0fm, "
                                      "q_a=%.0f vph/lane)" % (
                                          _jid, _ap['phase'], _ap['stop_sec'], _mod,
                                          _meas, _sb[0].spec.x_m, _ls.spec.x_m, _qa), 120.0)
            # (3a) ETA checks resolve on ARRIVAL -- the bus within 15 m of the
            #      stop line, or stopped in the queue -- not on the crossing:
            #      the crossing adds the red wait, which an ETA does not predict.
            if _ap['role'] == 'bus' and _v['pend_bus']:
                _scan = _VLT.get('scan') or {}
                _lmax = _ap['layout'].l_max_m if math.isfinite(_ap['layout'].l_max_m) else 60.0
                for (_cs, _cb, _cl) in _ap['chain']:
                    for _vid, _pos, _spd, _ln, _isb in _scan.get(_cs, ()):
                        if not _isb or _vid not in _v['pend_bus']:
                            continue
                        _d = _cb + (_cl - _pos)
                        if _d <= 15.0 or (_spd <= 3.0 and _d <= _lmax + 20.0):
                            _keep = []
                            for _k in _v['pend_bus'][_vid]:
                                if _k.startswith('eta_'):
                                    _r = _lg.resolve(_k, (_jid, _vid), time)
                                    if _r is not None:
                                        self._vlt_log(('eta', _k), time,
                                                      "[ASSUME] jct=%d bus=%d %s err=%+.1fs "
                                                      "(actual ARRIVAL at %.0fm - predicted; "
                                                      "signal wait excluded)"
                                                      % (_jid, _vid, _k, _r[0], _d), 30.0)
                                else:
                                    _keep.append(_k)
                            _v['pend_bus'][_vid] = _keep
            # (3b) the stop-bar CROSSING resolves the solve predictions (they
            #      include the signal delay) and any ETA the arrival test missed
            if _ap['role'] == 'bus' and _sb:
                for _vid, _tc in list(_sb[0].bus_cross.items()):
                    for _k in _v['pend_bus'].pop(_vid, []):
                        _r = _lg.resolve(_k, (_jid, _vid), _tc)
                        if _r is not None:
                            self._vlt_log(('eta', _k), time,
                                          "[ASSUME] jct=%d bus=%d %s err=%+.1fs (actual "
                                          "stop-line crossing - predicted)"
                                          % (_jid, _vid, _k, _r[0]), 30.0)
                    _sb[0].bus_cross.pop(_vid, None)

    def _vlt_sat_check(self, phase, t0, t1):
        """Saturation headways at the STOPBAR during the green that just ended:
        from the 4th vehicle per lane (start-up lost time excluded), headways
        0.8-3.5 s, >= 3 of them -> measured q_s vs SaturationFlow."""
        _lg = _vlt_ledger()
        for _ap in self._vlt['approaches']:
            if _ap['phase'] != phase or _ap.get('layout') is None:
                continue
            for _ls in self._vlt_loops(_ap, 'STOPBAR'):
                _by = {}
                for (t, lane, _b, _s) in _ls.crossings:
                    if t0 <= t <= t1:
                        _by.setdefault(lane, []).append(t)
                _h = []
                for _ts in _by.values():
                    _ts.sort()
                    _h.extend(b - a for a, b in zip(_ts[3:], _ts[4:]) if 0.8 <= b - a <= 3.5)
                if len(_h) >= 3:
                    _lg.compare('saturation_flow_vph_lane',
                                float(getattr(self, 'SaturationFlow', 1800.0)),
                                3600.0 / (sum(_h) / len(_h)))

    def _vlt_advance_vph(self, sec, window_s=300.0):
        """Arrival flow (veh/h, all lanes) measured at the ADVANCE loop of the
        approach whose stop line is `sec`. None until the loops are built (the
        caller then falls back to _measured_section_flow_vph).

        The ADVANCE loop sits upstream of the shockwave max queue reach and
        upstream of a turn bay, so what it counts is ARRIVALS -- a point-loop
        reading clear of the queue, not the section-wide flow that the queue
        contaminates.
        """
        _v = getattr(self, '_vlt', None)
        if not _v or not _v.get('built'):
            return None
        for _ap in _v['approaches']:
            if _ap['stop_sec'] == int(sec) and _ap.get('layout') is not None:
                _adv = self._vlt_loops(_ap, 'ADVANCE')
                if _adv and _adv[0].occ:
                    return _vll.PointLoopBank.reading(
                        _adv[0], _adv[0].occ[-1][0], window_s)['flow_vph']
        return None

'''

# ──────────────────────────────────────────────────── 5-7. hooks and flags
TICK_ANCHOR = """    global _dynaropac_last_eval_t, _dynaropac_decision_header_written
    if _bus_type_needs_recheck:
"""
TICK_NEW = """    global _dynaropac_last_eval_t, _dynaropac_decision_header_written
    # Tactical virtual loops + assumption checks (never raises).
    try:
        _vlt_tick_all(time, timeSta)
    except Exception as _vlte:
        if _VLT.get('errs', 0) < 3:
            _VLT['errs'] = _VLT.get('errs', 0) + 1
            log_to_file("[VLOOP] tick_all error: %r" % (_vlte,), force=True)
    if _bus_type_needs_recheck:
"""

RESET_ANCHOR = """    # Reset the swallowed-exception tracker for this replication.
    try:
        _swallow_reset()
    except Exception:
        pass
"""
RESET_NEW = RESET_ANCHOR + """    # Tactical virtual loops / assumption ledger (vloop_layout).
    try:
        _vlt_reset()
    except Exception:
        pass
"""

FINISH_ANCHOR = """    # ── Q-table persistence: SAVE on train-phase runs (2026-10-12) ──────────
"""
FINISH_NEW = """    # ── Tactical virtual loops: [ASSUME_SUMMARY] + the two CSVs ─────────────
    try:
        _vlt_finish()
    except Exception as _vlfe:
        log_to_file("[VLOOP] finish error: %r" % (_vlfe,), force=True)

""" + FINISH_ANCHOR

PAYOFF_OLD = """            _arr = None
            try:
                _arr = self._vlt_advance_vph(_s)
            except Exception as _swx:
                _note_swallow('_game_ctm2_payoffs#adv', _swx)
"""
PAYOFF_NEW = """            _arr = None
            if bool(globals().get('VLOOP_TAC_FEED_CTM', True)):
                try:
                    _arr = self._vlt_advance_vph(_s)   # ADVANCE loop, clear of the queue
                except Exception as _swx:
                    _note_swallow('_game_ctm2_payoffs#adv', _swx)
"""

SM_BLOCK = """# ── TACTICAL VIRTUAL LOOPS (ported 2026-11-06) ───────────────────────────────
# vloop_layout.PointLoopBank measures arrival flow at an ADVANCE loop placed
# upstream of the shockwave max queue -- the CTM2 payoff's arrival rate.
# VLOOP_TAC_WARM_S is how long the layout learns lanes / bays / bus stops from
# observed vehicles before it is built and logged as [VLOOP_LAYOUT].
VLOOP_TACTICAL = True
VLOOP_TAC_DT_S = 1.0            # loop sampling period (s)
VLOOP_TAC_WARM_S = 300.0        # learn lanes / bays / stops for this long first
VLOOP_TAC_REACH_M = 450.0       # how far upstream to look (stops at a signal)
VLOOP_TAC_FEED_CTM = True       # CTM2 arrivals from the ADVANCE loop
VLOOP_STOP_KPH = 3.0            # at/below this speed a vehicle is 'stopped'
# Assumption ledger: score every model prediction against what the vehicles
# did ([ASSUME_SUMMARY] + assumption_checks.csv). ASSUME_LOG silences the
# per-check lines only.
ASSUME_CHECKS = True
ASSUME_LOG = True
# TikZ figure export (tikz_phase.py) is NOT ported to this tree.
TIKZ_EXPORT = False

"""

SM_LIST_NEEDLE = "'GAME_CTM2_IG_S',"
SM_LIST_LINES = ("    'VLOOP_TACTICAL', 'VLOOP_TAC_DT_S', 'VLOOP_TAC_WARM_S',\n"
                 "    'VLOOP_TAC_REACH_M', 'VLOOP_TAC_FEED_CTM', 'VLOOP_STOP_KPH',\n"
                 "    'ASSUME_CHECKS', 'ASSUME_LOG', 'TIKZ_EXPORT',")


def patch_engine(check):
    path = os.path.join(DST_DIR, 'engine.py')
    text, nl = read(path)
    notes = []

    # 3. module layer
    if '_vlt_tick_all' in text and 'def _vlt_scan(' in text:
        notes.append('module layer: already present')
    else:
        once(text, ENGINE_OLD_BLOCK, 'stub vloop import block')
        if not check:
            text = text.replace(ENGINE_OLD_BLOCK, ENGINE_NEW_BLOCK, 1)
        notes.append('module layer: ' + ('would insert' if check else 'inserted'))

    # 4. controller methods
    if 'def _vlt_build(' in text:
        notes.append('methods: already present')
    else:
        once(text, '    def _vlt_advance_vph(self, sec, window_s=300.0):\n', 'stub method')
        if not check:
            text = replace_method(text, '_vlt_advance_vph', METHODS_BLOCK, '_vlt_advance_vph')
        notes.append('methods: ' + ('would replace stub' if check else 'replaced stub'))

    # 5. hooks (each identified by the comment it installs: the call text
    # itself also appears in the new def's signature)
    for anchor, new, what, marker in (
            (TICK_ANCHOR, TICK_NEW, 'post_manage tick',
             'Tactical virtual loops + assumption checks (never raises)'),
            (RESET_ANCHOR, RESET_NEW, 'AAPIInit reset',
             'Tactical virtual loops / assumption ledger (vloop_layout)'),
            (FINISH_ANCHOR, FINISH_NEW, 'AAPIFinish finish',
             'Tactical virtual loops: [ASSUME_SUMMARY]')):
        if text.count(marker) >= 1:
            notes.append('%s: already present' % what)
            continue
        once(text, anchor, what)
        if not check:
            text = text.replace(anchor, new, 1)
        notes.append('%s: %s' % (what, 'would hook' if check else 'hooked'))

    # 6. CTM2 gate
    if "VLOOP_TAC_FEED_CTM" in text:
        notes.append('payoff gate: already present')
    else:
        once(text, PAYOFF_OLD, 'payoff arrival read')
        if not check:
            text = text.replace(PAYOFF_OLD, PAYOFF_NEW, 1)
        notes.append('payoff gate: ' + ('would gate' if check else 'gated'))

    # 7. build stamp
    if ENGINE_BUILD_NEW in text:
        notes.append('ENGINE_BUILD: already bumped')
    else:
        once(text, ENGINE_BUILD_OLD, 'ENGINE_BUILD')
        if not check:
            text = text.replace(ENGINE_BUILD_OLD, ENGINE_BUILD_NEW, 1)
        notes.append('ENGINE_BUILD: ' + ('would bump' if check else 'bumped'))

    if not check:
        write(path, text, nl)
    return notes


def patch_modes(check):
    path = os.path.join(DST_DIR, 'specialized_modes.py')
    text, nl = read(path)
    notes = []
    if 'VLOOP_TACTICAL = True' in text:
        notes.append('flags: already present')
    else:
        once(text, 'MODE_FLAGS = [\n', 'MODE_FLAGS head')
        if not check:
            text = text.replace('MODE_FLAGS = [\n', SM_BLOCK + 'MODE_FLAGS = [\n', 1)
        notes.append('flags: ' + ('would declare' if check else 'declared'))
    if "'VLOOP_TAC_WARM_S'," in text:
        notes.append('MODE_FLAGS entries: already present')
    else:
        # the list is mixed-CRLF, so locate the line instead of matching text
        lines = text.split('\n')
        idx = [i for i, l in enumerate(lines) if SM_LIST_NEEDLE in l]
        if len(idx) != 1:
            raise SystemExit('ANCHOR MODE_FLAGS ctm2 line: found %d' % len(idx))
        if not check:
            lines.insert(idx[0] + 1, SM_LIST_LINES)
            text = '\n'.join(lines)
        notes.append('MODE_FLAGS entries: ' + ('would add' if check else 'added'))
    if not check:
        write(path, text, nl)
    return notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    if not os.path.isdir(DST_DIR):
        raise SystemExit('target tree not found: %s' % DST_DIR)
    print('mode:', 'CHECK (writes nothing)' if a.check else 'APPLY')
    for name, state in copy_modules(a.check):
        print('  module %-18s %s' % (name, state))
    print('  shim aapi_shim.py       %s' % patch_shim(a.check))
    for n in patch_engine(a.check):
        print('  engine: %s' % n)
    for n in patch_modes(a.check):
        print('  modes:  %s' % n)
    if a.check:
        print('check done: every anchor resolved, nothing written')
    else:
        print('applied')


if __name__ == '__main__':
    main()
