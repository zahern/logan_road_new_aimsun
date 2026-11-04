"""Offline test of the shockwave bus term that the GE / insertion DE solves now
minimise (2026-11-05). Pulls the REAL engine code out of engine.py with ast
(module helpers _pt_line_of / _pt_route_secs / _sec_len_m and the controller
methods _sw_lane_fd / _sw_bus_route_state / _sw_bus_ctx / _sw_bus_delay) and
drives it with a fake network -- no Aimsun:

    python -I _test_shockwave_solver.py      (exit 0 = PASS)

Network: PT line 900 routes sections 10 -> 20 -> 30; section 30 is the
bus-phase approach of the junction. A stop on section 20. The bus (veh 77)
is on section 10; 6 cars queue on the approach (2 lanes -> 3 per lane).

Checks
  1. the bus is found through the network PT lookup and its line's route
  2. route distance / ETA include the stop's dwell
  3. vehicles ahead come from the approach queue per lane
  4. GE bus delay: a GE too short to serve the bus is never better than no
     GE (a near-miss pushes the next green back); once it serves the bus
     the delay drops to ~0 and stays there
  5. the least serving GE = bus crossing time - remaining green
  6. insertion: too short an inserted green -> waits; long enough -> served
  7. a DE-style minimisation of (bus term x BusOcc + linear car cost) picks
     the least serving green, not the lower bound (the old degenerate result)
"""
import ast
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENG = os.path.join(HERE, 'shared_tsp_engine')
sys.path.insert(0, ENG)
import shockwave_lwr as _swl  # noqa: E402

src = io.open(os.path.join(ENG, 'engine.py'), encoding='utf-8').read()
tree = ast.parse(src)
MOD = ('_pt_line_of', '_pt_route_secs', '_sec_len_m')
METH = ('_sw_lane_fd', '_sw_bus_route_state', '_sw_bus_ctx', '_sw_bus_delay')
seg = {}
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name in MOD + METH \
            and node.name not in seg:
        seg[node.name] = ast.get_source_segment(src, node)
missing = [n for n in MOD + METH if n not in seg]
if missing:
    sys.exit('ABORT: not found: %s' % missing)


def _dedent(t):
    ls = t.split('\n')
    return '\n'.join([ls[0]] + [l[4:] if l.startswith('    ') else l for l in ls[1:]])


class Inf(object):
    def __init__(self, **k):
        self.__dict__.update(k)


SEC = {10: 100.0, 20: 200.0, 30: 150.0}
LOG = []
SWALLOWED = []
ns = {
    '_note_swallow': lambda tag, exc=None: SWALLOWED.append((tag, repr(exc))),
    '_swl': _swl, '_SWL_AVAILABLE': True, '_VLL_AVAILABLE': False,
    '_vlt_ledger': lambda: None,
    '_PT_VEH_LINE': {}, '_PT_VEH_LINE_T': [-1.0], '_PT_ROUTE_SECS': {},
    '_SEC_LEN_CACHE': {}, '_SCHED_STOP_SECS': {900: [20]},
    'AKIPTGetNumberLines': lambda: 1,
    'AKIPTGetIdLine': lambda i: 900,
    'AKIGetNbVehiclesFollowingPTLine': lambda l: 1,
    'AKIGetVehicleFollowingPTLine': lambda l, i: 77,
    'AKIPTGetNumberSectionsInLine': lambda l: 3,
    'AKIPTGetIdSectionInLine': lambda l, i: [10, 20, 30][i],
    'AKIInfNetGetSectionANGInf': lambda s: Inf(report=0, length=SEC.get(s, 0.0),
                                               speedLimit=50.0),
    'AKIPTVehGetInf': lambda v: Inf(report=0, idSection=10, CurrentPos=40.0,
                                    numberLane=1, CurrentSpeed=36.0),
    'AKIVehStateGetNbVehiclesSection': lambda s, b: 0,
    'AKIVehStateGetVehicleInfSection': lambda s, i: None,
    'log_to_file': lambda m, force=False: LOG.append(m),
    'SW_BUS_CRUISE_KMH': 36.0, 'SW_BUS_DWELL_S': 20.0, 'SW_BUS_LOG': True,
    'SHOCKWAVE_BUS_TERM': True, 'CELLQ_CTM_FREEFLOW_KMH': 50.0,
    'INS_INTERGREEN_S': 5.0,
}
ns['globals'] = lambda: ns
exec('\n\n'.join(seg[n] for n in MOD), ns)
exec('\n\n'.join(_dedent(seg[n]) for n in METH), ns)


class Ctl(object):
    id = 5
    BusPhase = 1
    JamDensity = 200.0
    SaturationFlow = 1800.0
    BusPhaseDuration = 30.0
    cycle_len_s = 120.0
    config = {'CycleTime': 120.0}
    NextRedStartTime = [[1000.0 + 5.0]]      # 5 s of bus green left at t=1000
    RedStartTimeList = [[1000.0 - 200.0]]

    def _phase_origin_sections(self):
        return {1: {30}, 2: {40}}

    MEASURED = None               # detector queue (None = no fresh reading)

    def _measured_sections_queue_veh(self, secs):
        return self.MEASURED

    def _zone_queue_count(self, sec):
        return (6, 60.0, 'ok') if int(sec) == 30 else (0, None, 'ok')

    def _sec_lane_count(self, sec):
        return 2


for n in METH:
    setattr(Ctl, n, ns[n])
c = Ctl()
c._bus_eta = {0: (77, 50.0, 300.0, 10.0)}
fails = []


def check(name, cond, detail=''):
    print('  %-4s %s %s' % ('ok' if cond else 'FAIL', name, detail))
    if not cond:
        fails.append(name)


bs = c._sw_bus_route_state(77, 1000.0)
check('1 bus found via PT line + route', bs and bs['line'] == 900
      and bs['target'] == 30 and bs['src'] == 'route', bs)
# 60 m left on 10 + 200 + 150 = 410 m at 10 m/s = 41 s, + 20 s dwell at stop 20
check('2 route distance and ETA with dwell', abs(bs['dist_m'] - 410.0) < 1e-9
      and abs(bs['eta_s'] - 61.0) < 1e-9 and bs['n_stops'] == 1, bs)
check('3 vehicles ahead = approach queue per lane', abs(bs['n_ahead'] - 3.0) < 1e-9)
check('3b [BUS_ROUTE] logged', any('[BUS_ROUTE]' in m for m in LOG))
check('3c no detector reading -> vehicle-scan fallback', bs['ahead_src'] == 'scan')
c.MEASURED = 8.0                  # detectors see 8 queued -> 4 per lane
c._sw_bus_cache = None
bd = c._sw_bus_route_state(77, 1001.0)
check('3d detector queue preferred when fresh', bd['ahead_src'] == 'detector'
      and abs(bd['n_ahead'] - 4.0) < 1e-9, bd)
c.MEASURED = None
c._sw_bus_cache = None

ctx = c._sw_bus_ctx(1000.0, insertion=False)
fd = ctx['fd']
d = [c._sw_bus_delay(ctx, g) for g in range(0, 81)]
need = next(g for g in range(81) if d[g] < 1.0)
check('4 short GE waits >= a red; serving GE ~0 thereafter',
      d[0] > 30.0 and all(x >= d[0] - 1e-9 for x in d[:need])
      and all(x < 1.0 for x in d[need:]), (d[:3], need))
# bus crosses at 20 s dwell + max(41 s run, (3+1)/q_s = 8 s) = 61 s; 5 s left
check('5 least serving GE = 61 - 5 = 56 s', need == 56, need)

c.RedStartTimeList = [[1000.0 - 30.0]]   # bus phase red 30 s of its 90 s
c._sw_bus_cache = None
ci = c._sw_bus_ctx(1000.0, insertion=True)
di = [c._sw_bus_delay(ci, g) for g in range(0, 81)]
ok_i = next(g for g in range(81) if di[g] < 1.0)
check('6 insertion: short waits for the normal green, long enough served',
      di[0] > 10.0 and di[ok_i] < 1.0 and all(x < 1.0 for x in di[ok_i:])
      and ok_i == 56, (di[0], ok_i))

# 7. objective = bus term * 40 pax + car cost 2 pax.s per GE second
obj = [d[g] * 40.0 + 2.0 * g for g in range(0, 81)]
best = min(range(81), key=lambda g: obj[g])
check('7 solve picks least serving GE (not the lower bound)', best == need,
      (best, need))

print('\n' + '\n'.join(m for m in LOG if '[BUS_ROUTE]' in m))
print('swallowed:', SWALLOWED or 'none')
if fails:
    sys.exit('FAIL: %s' % fails)
print('PASS')
