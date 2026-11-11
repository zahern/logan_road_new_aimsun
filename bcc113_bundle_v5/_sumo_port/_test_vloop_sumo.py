# -*- coding: utf-8 -*-
"""Offline test of the TACTICAL VIRTUAL LOOP layer AS PORTED INTO THE SUMO FORK.

    python _sumo_port/_test_vloop_sumo.py        (exit 0 = PASS)

Drives the REAL ported code: `shockwave_lwr` + `vloop_layout` are imported from
Z:/tsp/sumo_hpc/shared_tsp_engine, and `_vlt_scan` / `_vlt_loops` /
`_vlt_advance_vph` are pulled out of that tree's engine.py with ast, so this
tests the ported methods, not a copy of them.

The point of the layer: a loop placed UPSTREAM of the shockwave max queue counts
arrivals; a section-wide counter counts the queue too. Check 4/6 are the ones
that would catch a port that quietly kept the old behaviour.

Checks
  1  both siblings self-test clean (FD consistency, planner, loops, ledger)
  2  planner: STOPBAR 2 m before the line, ADVANCE upstream of L_max and off a
     near-side bus stop, ADVANCE upstream of a turn bay, EXIT at each turning
  3  emulator: a vehicle passing the ADVANCE loop is one crossing; a standing
     queue does not add crossings
  4  the arrival reading ignores a queue between the loop and the stop line
     (this is the difference from the section-window stub)
  5  STOPBAR counts DEPARTURES over the line, not creep-up, and occupancy /
     stopped / onset are recorded
  6  engine _vlt_advance_vph: None before build, the ADVANCE loop's flow after
     it, even while the section is jammed
  7  engine _vlt_scan: numberLane, laneIndex+1 fallback, bus flag, one scan per
     section per tick
  8  the AAPI shim publishes numberLane (the field _vlt_scan reads)
  9  nothing swallowed
"""
import ast
import io
import os
import sys

FORK = 'Z:/tsp/sumo_hpc/shared_tsp_engine'
if not os.path.isdir(FORK):
    FORK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'shared_tsp_engine')
sys.path.insert(0, FORK)
import shockwave_lwr as _swl   # noqa: E402
import vloop_layout as _vll    # noqa: E402

SRC = io.open(os.path.join(FORK, 'engine.py'), encoding='utf-8').read()
SWALLOWED = []


def grab(name, cls=False):
    """Source of the first def `name` (class-level when cls=True)."""
    for n in ast.walk(ast.parse(SRC)):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            if cls and not (n.col_offset == 4):
                continue
            s = ast.get_source_segment(SRC, n, padded=True)
            if s:
                return s
    sys.exit('MISSING from engine.py: %s' % name)


fails = []


def check(name, cond, detail=''):
    print('  %-4s %s %s' % ('ok' if cond else 'FAIL', name,
                            '' if detail == '' else detail))
    if not cond:
        fails.append(name)


class Inf(object):
    def __init__(self, **k):
        self.__dict__.update(k)


print('tree:', FORK)

# ── 1. siblings ──────────────────────────────────────────────────────────────
print('\n[1] module self-tests')
try:
    _swl._selftest()
    _vll._selftest()
    check('1a shockwave_lwr + vloop_layout self-tests', True)
except AssertionError as e:
    check('1a shockwave_lwr + vloop_layout self-tests', False, repr(e))

FD = _swl.LaneFD(50.0, 200.0, 1800.0)

# ── 2. planner ───────────────────────────────────────────────────────────────
print('\n[2] planner placement')
sp = _vll.ApproachSpec(7, 1, 'bus', 100,
                       [(100, 0.0, 150.0), (90, 150.0, 300.0)], 'managed',
                       (1, 2), 2, None, [120.0], [200, 201], 600.0, 120.0, 30.0)
lay = _vll.plan_layout(sp, FD)
print('   ', _vll.layout_line(lay))
by = {p: lp for lp in lay.loops for p in lp.purposes}
lmax = _vll.max_queue_reach_m(FD, 600.0, 90.0)
check('2a STOPBAR 2 m before the line on the phase lanes',
      by['STOPBAR'].x_m == 2.0 and by['STOPBAR'].lanes == (1, 2), by['STOPBAR'])
check('2b ADVANCE sits upstream of the max queue reach',
      by['ADVANCE'].x_m > lmax, (by['ADVANCE'].x_m, round(lmax, 1)))
check('2c ADVANCE is off the near-side bus stop (120 m)',
      abs(by['ADVANCE'].x_m - 120.0) >= 25.0 - 1e-9, by['ADVANCE'].x_m)
check('2d EXIT loop in each turning section',
      {lp.sec for lp in lay.loops if 'EXIT' in lp.purposes} == {200, 201},
      [lp.sec for lp in lay.loops if 'EXIT' in lp.purposes])
check('2e ADVANCE loop is a DEPARTURE-free crossing loop',
      by['ADVANCE'].depart is False and by['STOPBAR'].depart is True)

sp2 = _vll.ApproachSpec(7, 3, 'side', 300, [(300, 0.0, 60.0)], 'managed',
                        (3,), 3, 40.0, [], [400], 900.0, 120.0, 20.0)
lay2 = _vll.plan_layout(sp2, FD)
by2 = {p: lp for lp in lay2.loops for p in lp.purposes}
check('2f ADVANCE moved upstream of the 40 m turn bay, all lanes',
      by2['ADVANCE'].x_m >= 40.0 and by2['ADVANCE'].lanes == (),
      (by2['ADVANCE'].x_m, by2['ADVANCE'].lanes))
check('2g short reach is reported, not silently accepted',
      any('ADVANCE short' in w for w in lay2.warnings), lay2.warnings)

# ── 3/4. emulator + arrival reading ──────────────────────────────────────────
print('\n[3/4] point-loop emulator')
SEC = 100
adv = _vll.LoopSpec(('ADVANCE',), 100.0, SEC, 50.0, ())
bank = _vll.PointLoopBank([adv])
# 6 vehicles cross the loop (pos 40 -> 60) one per 10 s
for k in range(6):
    bank.update(10.0 * k, {SEC: [(k + 1, 40.0, 30.0, 1, False)]})
    bank.update(10.0 * k + 5.0, {SEC: [(k + 1, 60.0, 30.0, 1, False)]})
n_cross = len(bank.find('ADVANCE')[0].crossings)
check('3a every vehicle that passes the loop is one crossing', n_cross == 6, n_cross)

# 20 queued vehicles stand between the loop (pos 50) and the stop line (pos 150)
q = [(1000 + i, 130.0 + i, 0.0, 1, False) for i in range(20)]
before = len(bank.find('ADVANCE')[0].crossings)
for k in range(20):
    bank.update(60.0 + k, {SEC: q})
after = len(bank.find('ADVANCE')[0].crossings)
check('3b a standing queue adds no crossings at the ADVANCE loop',
      after == before, (before, after))

rd = _vll.PointLoopBank.reading(bank.find('ADVANCE')[0], 79.0, 300.0)
check('4a arrival reading counts arrivals only, queue excluded',
      rd['n'] == 6, rd)
check('4b reading is a vph rate over the window', rd['flow_vph'] > 0.0,
      round(rd['flow_vph'], 1))
# the same section jammed: a section-wide counter would report the queue as flow
check('4c the queue IS present in the scan (so 4a is not vacuous)',
      any(r[1] >= 130.0 for r in q) and len(q) == 20, len(q))

# ── 5. stop bar = departures ─────────────────────────────────────────────────
print('\n[5] stop-bar departure counting')
sb = _vll.LoopSpec(('STOPBAR',), 2.0, SEC, 148.0, (), '', True)
bank2 = _vll.PointLoopBank([sb])
# two cars creep up to the line and STOP on it, then both leave
for k in range(6):
    bank2.update(k, {SEC: [(1, 143.0 + 1.0 * k, 0.0, 1, False),
                           (2, 141.0 + 1.0 * k, 0.0, 1, False)]})
creep = len(bank2.find('STOPBAR')[0].crossings)
st = bank2.find('STOPBAR')[0]
check('5a creeping up ON the loop is not a departure', creep == 0, creep)
check('5b occupancy + stopped are recorded while they sit there',
      st.occ and st.occ[-1][1] and st.occ[-1][2] and len(st.onsets) == 1, st.onsets)
bank2.update(7, {SEC: []})
dep = len(bank2.find('STOPBAR')[0].crossings)
check('5c leaving over the line counts as a departure', dep >= 1, dep)

# ── 6. engine _vlt_advance_vph against a real layout ─────────────────────────
print('\n[6] engine _vlt_advance_vph')
ns = {'_vll': _vll, '_swl': _swl, 'math': __import__('math'),
      '_note_swallow': lambda tag, exc=None: SWALLOWED.append((tag, repr(exc)))}
bad = {}
for n in ast.walk(ast.parse(SRC)):
    if isinstance(n, ast.FunctionDef) and n.name in (
            '_vlt_advance_vph', '_vlt_loops') and n.col_offset == 4:
        bad[n.name] = ast.get_source_segment(SRC, n, padded=True)
missing = [m for m in ('_vlt_advance_vph', '_vlt_loops') if m not in bad]
if missing:
    sys.exit('MISSING methods: %s' % missing)
ns['globals'] = lambda: ns
exec('class T(object):\n' + '\n\n'.join(bad[m] for m in bad), ns)
T = ns['T']()


class Fake(object):
    pass


T._vlt = {'built': False, 'approaches': [{'stop_sec': 100, 'layout': None,
                                          'loop_idx': []}]}
check('6a not built -> None (payoff falls back to the section flow)',
      T._vlt_advance_vph(100) is None)

# build the bank exactly as _vlt_build does, from the real planner
lay3 = _vll.plan_layout(sp, FD)
allloops = list(lay3.loops)
idx = [i for i, lp in enumerate(allloops) if 'ADVANCE' in lp.purposes]
bank3 = _vll.PointLoopBank(allloops)
T._vlt = {'built': True, 'bank': bank3,
          'approaches': [{'stop_sec': 100, 'layout': lay3, 'loop_idx': idx}]}
adv_pos = bank3.loops[idx[0]].spec.pos_m
# 8 arrivals crossing ADVANCE, plus a jam of 25 vehicles at the stop line
for k in range(8):
    bank3.update(10.0 * k, {SEC: [(k + 1, adv_pos - 4.0, 40.0, 1, False)]})
    bank3.update(10.0 * k + 5.0, {SEC: [(k + 1, adv_pos + 4.0, 40.0, 1, False)]})
jam = [(5000 + i, 120.0 + i, 0.0, 1, False) for i in range(25)]
for k in range(8, 20):
    bank3.update(10.0 * k, {SEC: jam})
got = T._vlt_advance_vph(100)
want = _vll.PointLoopBank.reading(bank3.loops[idx[0]],
                                  bank3.loops[idx[0]].occ[-1][0], 300.0)['flow_vph']
check('6b built -> the ADVANCE loop reading', got is not None and abs(got - want) < 1e-6,
      (got, round(want, 1)))
check('6c jammed section does not inflate the arrival rate',
      abs(got - want) < 1e-6 and want < 8 * 3600.0 / 60.0,
      round(want, 1))
check('6d unknown section -> None', T._vlt_advance_vph(999) is None)

# ── 7. engine _vlt_scan ──────────────────────────────────────────────────────
print('\n[7] engine _vlt_scan')
CALLS = {'n': 0}
_rows_old = [Inf(idVeh=11, CurrentPos=10.0, CurrentSpeed=30.0, laneIndex=0, type=1),
             Inf(idVeh=12, CurrentPos=20.0, CurrentSpeed=30.0, laneIndex=2, type=9)]
_rows_new = [Inf(idVeh=11, CurrentPos=10.0, CurrentSpeed=30.0, laneIndex=0,
                 numberLane=1, type=1),
             Inf(idVeh=12, CurrentPos=20.0, CurrentSpeed=30.0, laneIndex=2,
                 numberLane=3, type=9)]
ROW = {'r': _rows_new}


def _nb(sec, b):
    CALLS['n'] += 1
    return len(ROW['r'])


def _inf(sec, i):
    return ROW['r'][i]


ns2 = {'_VLT': {'ledger': None, 'tick_t': -1e9, 'scan_t': None, 'scan': {},
                'errs': 0},
       'AKIVehStateGetNbVehiclesSection': _nb,
       'AKIVehStateGetVehicleInfSection': _inf,
       '_note_swallow': lambda tag, exc=None: SWALLOWED.append((tag, repr(exc)))}
exec(grab('_vlt_scan'), ns2)
scan = ns2['_vlt_scan']
r1 = scan([SEC], 5.0, 9)
check('7a numberLane is the lane', r1[SEC][1][3] == 3, r1[SEC])
check('7b bus flag from the type position', r1[SEC][1][4] is True
      and r1[SEC][0][4] is False, r1[SEC])
ROW['r'] = _rows_old
r2 = scan([SEC], 6.0, 9)
scan([SEC], 6.0, 9)
scan([SEC, SEC], 6.0, 9)
check('7c laneIndex+1 fallback for an older shim', r2[SEC][1][3] == 3, r2[SEC])
check('7d one scan per section per tick (cached)', CALLS['n'] == 2, CALLS['n'])

# ── 8. shim field ────────────────────────────────────────────────────────────
print('\n[8] AAPI shim')
shim = 'Z:/tsp/sumo_hpc/sumo_bridge/aapi_shim.py'
if not os.path.isfile(shim):
    shim = os.path.join(os.path.dirname(FORK), 'sumo_bridge', 'aapi_shim.py')
stxt = io.open(shim, encoding='utf-8').read()
check('8a shim publishes InfVeh.numberLane', 'numberLane=' in stxt)

# ── 9 ────────────────────────────────────────────────────────────────────────
check('9 nothing swallowed', not SWALLOWED, SWALLOWED[:3])
if fails:
    sys.exit('FAIL: %s' % fails)
print('PASS')
