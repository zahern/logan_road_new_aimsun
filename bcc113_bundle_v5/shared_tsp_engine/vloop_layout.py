r"""vloop_layout.py -- TACTICAL virtual-loop layout per intersection approach,
a point-loop emulator, and an assumption ledger. Pure stdlib (+ the sibling
shockwave_lwr), no Aimsun: unit-testable on Windows.

Why
---
Aimsun has no runtime API to add a detector, and the engine's existing virtual
loop is a whole-SECTION counter: it cannot separate arrivals from discharge,
cannot see the queue tail and has no notion of where on the approach it is.
Each model the controllers use needs measurements at SPECIFIC places:

  shockwave GE / INS   arrival flow UPSTREAM of the longest queue (else the
                       queue contaminates the count), stop-line discharge and
                       occupancy, and the queue tail to measure the shockwave
  CTM                  inflow at the upstream edge of the modelled reach, and
                       the downstream EXIT (a blocked exit is a receiving limit)
  bus priority         check-in far enough upstream to act in time, check-out
                       past the stop line
  side phases          stop-line presence (demand / gap) and arrivals

The planner places each loop from THIS approach's geometry and timing:

  STOPBAR      2 m before the stop line, on the lanes that serve the phase
  QUEUE_MID /  half / full of the shockwave max queue reach L_max: the queue
  QUEUE_TAIL   tail passing them times the formation wave (measured w)
  ADVANCE      past L_max (+margin); for a TURN BAY it goes upstream of the
               bay entrance on the shared lanes (bay lanes see only turners)
  BAY_ENTRY    3 m inside the bay entrance: bay full -> the through lanes
               are about to be blocked
  CTM_INFLOW   upstream edge of the CTM reach (merged with ADVANCE if close)
  BUS_CHECKIN  bus cruise speed x lead time (GE max + intergreen, at least the
               decision lead) -- bus phase only
  EXIT         10 m into each exit section: discharge + downstream blocking
               (bus crossing it = check-out)
  SPILLBACK    5 m inside the far end of the reach when the queue can reach
               the upstream signal

Tactical rules: nothing beyond the upstream signal (the chain stops there);
loops other than the bus ones are moved off a near-side bus stop (a dwelling
bus would read as a queue); a reach too short for a loop is clamped and the
shortfall is recorded as a WARNING so the run log says which model input is
compromised and by how much.

Lane numbering, bay lengths and stop positions are inputs: the engine takes
them from the Aimsun model where it can and checks them against what the
vehicles actually do (see the ledger kinds below).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from . import shockwave_lwr as _swl
except ImportError:   # pragma: no cover - flat import in-sim / in tests
    try:
        import shockwave_lwr as _swl
    except ImportError:
        import os as _os, sys as _sys
        _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        import shockwave_lwr as _swl


# --------------------------------------------------------------------------- #
# Planner                                                                      #
# --------------------------------------------------------------------------- #
@dataclass
class ApproachSpec:
    junction: int
    phase: int
    role: str                                  # 'bus' | 'side'
    stop_sec: int
    chain: Sequence[Tuple[int, float, float]]  # (sec, dist_base_m, length_m)
    reach_reason: str = 'zone'                 # 'managed' = upstream signal
    lanes: Tuple[int, ...] = ()                # lanes on stop_sec for phase
    n_lanes: int = 1
    bay_len_m: Optional[float] = None          # bay for these lanes, if any
    stops_m: Sequence[float] = ()              # bus stops, m from stop line
    exits: Sequence[int] = ()
    q_arr_vph_lane: float = 600.0
    cycle_s: float = 120.0
    green_s: float = 30.0


@dataclass
class LoopSpec:
    purposes: Tuple[str, ...]
    x_m: float                 # metres upstream of the stop line (<0: exit)
    sec: int
    pos_m: float               # CurrentPos coordinate on `sec`
    lanes: Tuple[int, ...]     # () = all lanes
    note: str = ''
    depart: bool = False       # count vehicles LEAVING the section past it


@dataclass
class Layout:
    spec: ApproachSpec
    loops: List[LoopSpec]
    l_max_m: float
    reach_m: float
    warnings: List[str] = field(default_factory=list)


def _locate(chain, x):
    """(sec, CurrentPos) of the point x m upstream of the stop line."""
    for sec, base, L in chain:
        if base - 1e-9 <= x < base + L:
            return int(sec), max(0.0, float(L) - (x - base))
    sec, base, L = chain[-1]
    return int(sec), 0.0


def max_queue_reach_m(fd, q_arr_vph_lane, red_s):
    """Shockwave max back-of-queue distance for one red (per lane).

    The back forms at u = q_a / (k_j - k_a); from green start the discharge
    wave travels back at w and meets it at  L = u w red / (w - u).
    Oversaturated (u >= w): unbounded -> inf."""
    u = _swl.formation_wave_speed(fd, q_arr_vph_lane)
    w = fd.w
    if u >= w - 1e-9:
        return float('inf')
    return u * w * max(0.0, float(red_s)) / (w - u)


def plan_layout(spec: ApproachSpec, fd=None, *, margin=0.25, stopbar_m=2.0,
                ctm_reach_m=333.0, bus_cruise_kmh=40.0, bus_lead_s=25.0,
                stop_clear_m=25.0, exit_m=10.0) -> Layout:
    fd = fd or _swl.LaneFD()
    chain = list(spec.chain) or [(spec.stop_sec, 0.0, 50.0)]
    reach = max(base + L for _s, base, L in chain)
    warn = []
    red = max(0.0, float(spec.cycle_s) - float(spec.green_s))
    l_max = max_queue_reach_m(fd, spec.q_arr_vph_lane, red)
    lanes = tuple(spec.lanes)
    stops = sorted(float(s) for s in (spec.stops_m or ()))
    far = reach - 5.0                         # last usable point in the reach

    def off_stop(x, label):
        for s in stops:
            if abs(x - s) < stop_clear_m:
                up = s + stop_clear_m
                if up <= far:
                    return up, '%s moved upstream off bus stop @%.0fm' % (label, s)
                dn = s - stop_clear_m
                if dn > stopbar_m + 5.0:
                    return dn, '%s moved downstream off bus stop @%.0fm' % (label, s)
                return x, '%s ON bus stop @%.0fm (no room to move)' % (label, s)
        return x, ''

    raw = []        # (purpose, x, lanes, note)
    raw.append(('STOPBAR', stopbar_m, lanes, ''))
    if math.isfinite(l_max):
        for p, x in (('QUEUE_MID', 0.5 * l_max), ('QUEUE_TAIL', l_max)):
            if x > stopbar_m + 5.0:
                xx = min(x, far)
                xx, n = off_stop(xx, p)
                raw.append((p, xx, lanes, n))
        x_adv = max(l_max * (1.0 + margin) + 7.0, 30.0)
    else:
        warn.append('oversaturated: queue grows every cycle (u>=w) -- '
                    'arrivals cannot be measured clear of the queue')
        x_adv = far
    adv_lanes = lanes
    if spec.bay_len_m and spec.bay_len_m > 0.0:
        bay = float(spec.bay_len_m)
        raw.append(('BAY_ENTRY', max(stopbar_m + 1.0, bay - 3.0), lanes,
                    'bay %.0fm' % bay))
        if x_adv < bay + 10.0:
            x_adv = bay + 10.0
        adv_lanes = ()                        # shared lanes upstream of the bay
        if math.isfinite(l_max) and l_max > bay:
            warn.append('bay overflow: queue reach %.0fm > bay %.0fm -- through '
                        'lanes get blocked' % (l_max, bay))
    if x_adv > far:
        warn.append('ADVANCE short: needs %.0fm, reach is %.0fm (%s) -- arrival '
                    'flow will include queued vehicles'
                    % (x_adv, reach, spec.reach_reason))
        x_adv = max(far, stopbar_m + 5.0)
    x_adv, n = off_stop(x_adv, 'ADVANCE')
    raw.append(('ADVANCE', x_adv, adv_lanes, n))
    x_ctm = min(float(ctm_reach_m), far)
    if x_ctm < float(ctm_reach_m) - 1.0:
        warn.append('CTM reach clamped %.0fm -> %.0fm (%s)'
                    % (ctm_reach_m, x_ctm, spec.reach_reason))
    x_ctm, n_ctm = off_stop(x_ctm, 'CTM_INFLOW')
    raw.append(('CTM_INFLOW', x_ctm, (), n_ctm))
    if spec.role == 'bus':
        x_bus = max(float(bus_cruise_kmh) / 3.6 * float(bus_lead_s), stopbar_m)
        if x_bus > far:
            got = max(far, 0.0) / max(float(bus_cruise_kmh) / 3.6, 0.5)
            warn.append('BUS_CHECKIN short: lead %.0fs needs %.0fm, reach %.0fm -> '
                        'only %.0fs warning (use the route ETA upstream)'
                        % (bus_lead_s, x_bus, reach, got))
            x_bus = far
        n_bus = ''
        for s_ in stops:
            if abs(x_bus - s_) < stop_clear_m:
                # detect the bus AFTER it has dwelt: just downstream of the stop
                x_new = s_ - stop_clear_m
                if x_new > stopbar_m + 5.0:
                    n_bus = ('BUS_CHECKIN moved downstream of bus stop @%.0fm '
                             '(detects after the dwell; lead %.0fs)'
                             % (s_, x_new / max(float(bus_cruise_kmh) / 3.6, 0.5)))
                    x_bus = x_new
                break
        raw.append(('BUS_CHECKIN', x_bus, (), n_bus))
    if math.isfinite(l_max) is False or l_max > far:
        raw.append(('SPILLBACK', far, (), 'queue can reach the upstream end'))

    # merge loops within 8 m of each other (one physical loop, many purposes)
    raw.sort(key=lambda r: r[1])
    merged = []
    for p, x, ln, note in raw:
        if merged and abs(merged[-1][1] - x) < 8.0 and merged[-1][2] == ln:
            mp, mx, mln, mnote = merged[-1]
            merged[-1] = (mp + (p,), mx, mln, '; '.join(t for t in (mnote, note) if t))
        else:
            merged.append(((p,), x, ln, note))
    loops = []
    for ps, x, ln, note in merged:
        sec, pos = _locate(chain, x)
        # The STOP BAR counts DEPARTURES over the stop line: a queued vehicle
        # stops ON the loop, so "front passed the loop" would count cars
        # creeping up, not discharge (saturation flow read ~20 % high).
        loops.append(LoopSpec(tuple(ps), float(x), sec, pos, tuple(ln), note,
                              depart='STOPBAR' in ps))
        if note and 'ON bus stop' in note:
            warn.append(note)
    for e in spec.exits or ():
        loops.append(LoopSpec(('EXIT', 'BUS_CHECKOUT') if spec.role == 'bus'
                              else ('EXIT',), -float(exit_m), int(e),
                              float(exit_m), ()))
    return Layout(spec, loops, l_max, reach, warn)


def layout_line(lay: Layout) -> str:
    s = lay.spec
    parts = []
    for lp in lay.loops:
        parts.append('%s@%s%.0fm(sec%d%s)' % (
            '+'.join(lp.purposes), '-' if lp.x_m < 0 else '', abs(lp.x_m), lp.sec,
            (' L' + ','.join(str(x) for x in lp.lanes)) if lp.lanes else ''))
    return ('jct=%d ph=%d %s stop_sec=%d lanes=%s bay=%s reach=%.0fm(%s) '
            'Lmax=%.0fm loops=[%s]%s' % (
                s.junction, s.phase, s.role, s.stop_sec,
                list(s.lanes) or 'all', ('%.0fm' % s.bay_len_m) if s.bay_len_m else '-',
                lay.reach_m, s.reach_reason, lay.l_max_m if math.isfinite(lay.l_max_m) else -1,
                ' '.join(parts),
                (' WARN: ' + ' | '.join(lay.warnings)) if lay.warnings else ''))


# --------------------------------------------------------------------------- #
# Point-loop emulator                                                          #
# --------------------------------------------------------------------------- #
@dataclass
class LoopState:
    spec: LoopSpec
    crossings: List[Tuple[float, int, bool, float]] = field(default_factory=list)
    occ: List[Tuple[float, bool, bool]] = field(default_factory=list)
    stopped_on: bool = False
    onsets: List[float] = field(default_factory=list)
    bus_cross: Dict[int, float] = field(default_factory=dict)


class PointLoopBank:
    """Point detectors at fixed (section, CurrentPos), fed with the vehicles
    on those sections every tick. A crossing = the front passes the loop
    position between two ticks (or the vehicle first appears just past it).
    Occupancy = any vehicle body over the loop; stopped = occupied at <=
    stop_kmh. Keeps a rolling history of `keep_s` seconds."""

    def __init__(self, loops: Sequence[LoopSpec], veh_len_m=4.5, loop_len_m=2.0,
                 stop_kmh=3.0, keep_s=900.0):
        self.loops = [LoopState(lp) for lp in loops]
        self.veh_len = float(veh_len_m)
        self.loop_len = float(loop_len_m)
        self.stop_kmh = float(stop_kmh)
        self.keep_s = float(keep_s)
        self._prev: Dict[int, Tuple[int, float]] = {}
        self.secs = sorted({lp.sec for lp in loops})

    def update(self, t, vehicles_by_sec):
        """vehicles_by_sec: {sec: [(vid, pos_m, speed_kmh, lane, is_bus), ...]}"""
        t = float(t)
        seen = {}
        now_on = {int(sec): {int(r[0]) for r in vs} for sec, vs in vehicles_by_sec.items()}
        prev_full = getattr(self, '_prev_full', {})
        for ls in self.loops:
            lp = ls.spec
            vs = vehicles_by_sec.get(lp.sec, ())
            occ = stopped = False
            if lp.depart:
                # vehicles that were near the stop line last tick and have left
                for vid, (psec, ppos, plane, pbus, pspd) in prev_full.items():
                    if (psec == lp.sec and ppos >= lp.pos_m - 10.0
                            and vid not in now_on.get(lp.sec, ())
                            and (not lp.lanes or plane in lp.lanes)):
                        ls.crossings.append((t, plane, pbus, pspd))
                        if pbus:
                            ls.bus_cross[vid] = t
            for vid, pos, spd, lane, is_bus in vs:
                if lp.lanes and int(lane) not in lp.lanes:
                    continue
                pos = float(pos)
                prev = self._prev.get(int(vid))
                crossed = False
                if prev is not None and prev[0] == lp.sec:
                    crossed = prev[1] < lp.pos_m <= pos
                elif prev is None or prev[0] != lp.sec:
                    crossed = (lp.pos_m <= pos < lp.pos_m + max(float(spd) / 3.6, 1.0) * 1.5 + 1.0
                               and prev is not None)
                if crossed and not lp.depart:
                    ls.crossings.append((t, int(lane), bool(is_bus), float(spd)))
                    if is_bus:
                        ls.bus_cross[int(vid)] = t
                if lp.pos_m - self.loop_len <= pos <= lp.pos_m + self.veh_len:
                    occ = True
                    if float(spd) <= self.stop_kmh:
                        stopped = True
                seen[int(vid)] = (lp.sec, pos)
            ls.occ.append((t, occ, stopped))
            if stopped and not ls.stopped_on:
                ls.onsets.append(t)
            ls.stopped_on = stopped
            lo = t - self.keep_s
            if ls.crossings and ls.crossings[0][0] < lo:
                ls.crossings = [c for c in ls.crossings if c[0] >= lo]
            if ls.occ and ls.occ[0][0] < lo:
                ls.occ = [o for o in ls.occ if o[0] >= lo]
            if ls.onsets and ls.onsets[0] < lo:
                ls.onsets = [o for o in ls.onsets if o >= lo]
        full = {}
        for sec, vs in vehicles_by_sec.items():
            for vid, pos, spd, lane, isb in vs:
                seen.setdefault(int(vid), (int(sec), float(pos)))
                full[int(vid)] = (int(sec), float(pos), int(lane), bool(isb), float(spd))
        self._prev = seen
        self._prev_full = full

    def find(self, purpose):
        return [ls for ls in self.loops if purpose in ls.spec.purposes]

    @staticmethod
    def reading(ls: LoopState, t, window_s=60.0):
        lo = float(t) - float(window_s)
        cr = [c for c in ls.crossings if c[0] >= lo]
        oc = [o for o in ls.occ if o[0] >= lo]
        span = max(min(float(window_s), (oc[-1][0] - oc[0][0]) if len(oc) > 1 else 0.0), 1.0)
        n_l = max(len(ls.spec.lanes), 1) if ls.spec.lanes else None
        return {
            'flow_vph': len(cr) * 3600.0 / span,
            'flow_vph_lane': (len(cr) * 3600.0 / span / n_l) if n_l else None,
            'occ': (sum(1 for o in oc if o[1]) / len(oc)) if oc else 0.0,
            'stopped': (sum(1 for o in oc if o[2]) / len(oc)) if oc else 0.0,
            'speed_kmh': (sum(c[3] for c in cr) / len(cr)) if cr else None,
            'n_bus': sum(1 for c in cr if c[2]),
            'n': len(cr),
        }


# --------------------------------------------------------------------------- #
# Assumption ledger: prediction vs outcome, with a run summary                 #
# --------------------------------------------------------------------------- #
class AssumptionLedger:
    """predict(kind, key, predicted_abs) ... resolve(kind, key, actual_abs)
    records the error; compare(kind, model, measured) records a direct pair.
    summary() -> {kind: (n, bias, mae, p90)}. Errors are actual - predicted."""

    def __init__(self, max_pending=5000):
        self.pending: Dict[Tuple[str, object], Tuple[float, float, dict]] = {}
        self.errors: Dict[str, List[float]] = {}
        self.flags: Dict[str, List[int]] = {}
        self.max_pending = int(max_pending)

    def predict(self, kind, key, predicted, t, **meta):
        if (kind, key) not in self.pending and len(self.pending) < self.max_pending:
            self.pending[(kind, key)] = (float(predicted), float(t), meta)

    def resolve(self, kind, key, actual):
        p = self.pending.pop((kind, key), None)
        if p is None:
            return None
        err = float(actual) - p[0]
        self.errors.setdefault(kind, []).append(err)
        return err, p

    def compare(self, kind, model, measured):
        if model is None or measured is None:
            return None
        err = float(measured) - float(model)
        self.errors.setdefault(kind, []).append(err)
        return err

    def flag(self, kind, ok):
        self.flags.setdefault(kind, []).append(1 if ok else 0)

    def expire(self, t, max_age_s=600.0):
        old = [k for k, v in self.pending.items() if float(t) - v[1] > max_age_s]
        for k in old:
            self.pending.pop(k, None)
            self.flags.setdefault(k[0] + '_unresolved', []).append(1)

    def summary(self):
        out = {}
        for k, e in self.errors.items():
            if not e:
                continue
            a = sorted(abs(x) for x in e)
            out[k] = (len(e), sum(e) / len(e), sum(a) / len(a),
                      a[min(len(a) - 1, int(0.9 * len(a)))])
        for k, f in self.flags.items():
            out[k + '%'] = (len(f), 100.0 * sum(f) / max(len(f), 1), None, None)
        return out


# --------------------------------------------------------------------------- #
# Lane-use learner (empirical lane -> movement map and bay length)             #
# --------------------------------------------------------------------------- #
class LaneUseLearner:
    """Watches vehicles near the stop line and where they exit, so the lanes
    each movement REALLY uses (and how far back a bay lane is occupied) come
    from behaviour, not from an assumed lane-numbering convention."""

    def __init__(self, near_m=40.0):
        self.near_m = float(near_m)
        self.last: Dict[int, Tuple[int, int]] = {}        # vid -> (sec, lane)
        self.counts: Dict[Tuple[int, int, int], int] = {}  # (sec, lane, exit)
        self.lane_reach: Dict[Tuple[int, int], float] = {}  # (sec, lane) -> max d
        self.lane_seen: Dict[Tuple[int, int], int] = {}

    def observe(self, origin_secs_len, exits, vehicles_by_sec, dt_s=1.0):
        """origin_secs_len {sec: length}; exits: set of exit sections.
        Lane reach adds one sampling step of travel (speed x dt): a vehicle
        first seen d m from the stop line entered that lane up to v*dt
        further back, so a bay is not under-read by the sampling gap."""
        for sec, L in origin_secs_len.items():
            for vid, pos, _spd, lane, _b in vehicles_by_sec.get(sec, ()):
                d = min(float(L), float(L) - float(pos)
                        + max(0.0, float(_spd)) / 3.6 * float(dt_s))
                k = (int(sec), int(lane))
                self.lane_seen[k] = self.lane_seen.get(k, 0) + 1
                if d > self.lane_reach.get(k, -1.0):
                    self.lane_reach[k] = d
                if d <= self.near_m:
                    self.last[int(vid)] = k
        for sec in exits:
            for vid, *_r in vehicles_by_sec.get(sec, ()):
                k = self.last.pop(int(vid), None)
                if k is not None:
                    ck = (k[0], k[1], int(sec))
                    self.counts[ck] = self.counts.get(ck, 0) + 1

    def lanes_for(self, sec, exit_secs, min_share=0.1):
        """Lanes of `sec` whose exits to `exit_secs` are >= min_share of that
        lane's traffic. () when nothing was observed."""
        tot, hit = {}, {}
        for (s, ln, ex), n in self.counts.items():
            if s != int(sec):
                continue
            tot[ln] = tot.get(ln, 0) + n
            if ex in exit_secs:
                hit[ln] = hit.get(ln, 0) + n
        return tuple(sorted(ln for ln in hit if hit[ln] >= min_share * tot[ln]))

    def bay_len(self, sec, lanes, sec_len, frac=0.8):
        """If every lane in `lanes` is only ever occupied within frac*sec_len of
        the stop line while other lanes reach further, those lanes are a bay of
        about that length. None otherwise."""
        if not lanes:
            return None
        r = [self.lane_reach.get((int(sec), int(l)), 0.0) for l in lanes]
        others = [v for (s, l), v in self.lane_reach.items()
                  if s == int(sec) and l not in lanes]
        if not others or max(r) <= 0.0:
            return None
        if max(r) < frac * float(sec_len) and max(others) > max(r) + 10.0:
            return max(r)
        return None


# --------------------------------------------------------------------------- #
# Self-test                                                                    #
# --------------------------------------------------------------------------- #
def _check(c, m):
    if not c:
        raise AssertionError(m)


def _selftest():
    fd = _swl.LaneFD(50.0, 200.0, 1800.0)
    # Long through approach, bus phase, 90 s red, 600 vph/lane, stop at 120 m.
    sp = ApproachSpec(1, 1, 'bus', 100, [(100, 0.0, 150.0), (90, 150.0, 300.0)],
                      'managed', (1, 2), 2, None, [120.0], [200], 600.0, 120.0, 30.0)
    lay = plan_layout(sp, fd)
    print(layout_line(lay))
    lm = max_queue_reach_m(fd, 600.0, 90.0)
    _check(abs(lay.l_max_m - lm) < 1e-9 and 50.0 < lm < 120.0, lm)
    by = {p: lp for lp in lay.loops for p in lp.purposes}
    _check(by['STOPBAR'].x_m == 2.0 and by['STOPBAR'].lanes == (1, 2), by['STOPBAR'])
    _check(by['ADVANCE'].x_m > lm, (by['ADVANCE'].x_m, lm))
    _check(all(abs(lp.x_m - 120.0) >= 25.0 - 1e-9 for lp in lay.loops
               if 'BUS_CHECKIN' not in lp.purposes and lp.x_m > 0), 'off bus stop')
    _check(by['ADVANCE'].sec == 90 or by['ADVANCE'].x_m < 150.0, by['ADVANCE'])
    _check('BUS_CHECKOUT' in by and by['EXIT'].sec == 200, 'exit loop')
    _check(abs(by['BUS_CHECKIN'].x_m - 40.0 / 3.6 * 25.0) < 1e-6, by['BUS_CHECKIN'])
    # Short side approach with a 40 m bay: ADVANCE must sit upstream of the bay
    # on all lanes; the reach is too short -> warnings.
    sp2 = ApproachSpec(1, 3, 'side', 300, [(300, 0.0, 60.0)], 'managed', (3,), 3,
                       40.0, [], [400], 900.0, 120.0, 20.0)
    lay2 = plan_layout(sp2, fd)
    print(layout_line(lay2))
    by2 = {p: lp for lp in lay2.loops for p in lp.purposes}
    _check(by2['ADVANCE'].lanes == () and by2['ADVANCE'].x_m >= 40.0, by2['ADVANCE'])
    _check('BAY_ENTRY' in by2 and abs(by2['BAY_ENTRY'].x_m - 37.0) < 1e-9, by2)
    _check(any('ADVANCE short' in w for w in lay2.warnings), lay2.warnings)
    _check(any('bay overflow' in w for w in lay2.warnings), lay2.warnings)
    _check('BUS_CHECKIN' not in by2, 'side phase has no bus loop')

    # Emulator: one car approaches and stops on the STOPBAR, another crosses.
    bank = PointLoopBank([LoopSpec(('STOPBAR',), 2.0, 100, 148.0, (), '', True),
                          LoopSpec(('ADVANCE',), 100.0, 100, 50.0, ())])
    for k in range(10):
        bank.update(k, {100: [(1, 40.0 + 12.0 * k if k < 9 else 147.0,
                               43.0 if k < 9 else 0.0, 1, False)]})
    sb = bank.find('STOPBAR')[0]
    adv = bank.find('ADVANCE')[0]
    _check(len(adv.crossings) == 1 and len(sb.crossings) == 0, (adv.crossings, sb.crossings))
    _check(sb.stopped_on and len(sb.onsets) == 1, sb.onsets)
    bank.update(10, {100: []})                 # it departs over the stop line
    _check(len(sb.crossings) == 1, sb.crossings)
    r = PointLoopBank.reading(adv, 9.0, 60.0)
    _check(r['n'] == 1, r)

    # Ledger
    led = AssumptionLedger()
    led.predict('eta', 7, 100.0, 0.0)
    _check(led.resolve('eta', 7, 104.0)[0] == 4.0, 'resolve')
    led.compare('w', 3.0, 2.5)
    led.flag('advance_clear', True); led.flag('advance_clear', False)
    sm = led.summary()
    _check(sm['eta'][0] == 1 and sm['advance_clear%'][1] == 50.0, sm)

    # Lane learner: lane 3 only goes to exit 400 and only within 35 m.
    lu = LaneUseLearner()
    for k in range(5):
        lu.observe({300: 60.0}, {400, 500},
                   {300: [(10 + k, 25.0, 10.0, 3, False), (20 + k, 30.0, 10.0, 1, False),
                          (30 + k, 1.0, 10.0, 1, False)]})
        lu.observe({300: 60.0}, {400, 500},
                   {300: [], 400: [(10 + k, 3.0, 20.0, 1, False)],
                    500: [(20 + k, 3.0, 20.0, 1, False)]})
    _check(lu.lanes_for(300, {400}) == (3,), lu.counts)
    _check(lu.bay_len(300, (3,), 60.0) is not None, lu.lane_reach)
    print('OK: tactical layout (bay, bus stop, short reach, bus loops, exits), '
          'point loops, ledger, lane learner.')


if __name__ == '__main__':
    _selftest()
