"""Offline test of engine._game_ctm2_payoffs: the two-class CTM payoffs the
games decide on when GAME_PAYOFF_MODEL='ctm2' (2026-11-05). Pulls the REAL
engine methods out of engine.py with ast and drives them with a fake junction:

    python -I _test_game_ctm2_payoffs.py        (exit 0 = PASS)

Junction 7: phase 1 = bus (main) phase on section 30, phase 2 = cross phase
on section 40; greens 20 / 30 s, intergreen 5 s.

Checks
  1. bus phase green, 3 s left, bus 25 m back behind 3 cars: GE helps the bus
     (b > 0), costs the cross street (C > 0); longer GE never helps the bus less
  2. cross phase running, bus queued at the red: INS helps the bus and costs
     the cross street; a longer insertion helps the bus at least as much
  3. ER while the bus is still approaching hurts it (b < 0)
  4. GR (cut the cross green) while the bus waits helps it
  5. untimed action type -> None entry; interphase -> None overall
  6. bus vehicles are counted in the BUS class only (no bus -> b == 0)
  7. nothing swallowed
"""
import ast
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENG = os.path.join(HERE, 'shared_tsp_engine')
sys.path.insert(0, ENG)
import ctm_twoclass as _ctm2  # noqa: E402

src = io.open(os.path.join(ENG, 'engine.py'), encoding='utf-8').read()
seg = {}
for n in ast.walk(ast.parse(src)):
    if isinstance(n, ast.FunctionDef) and n.name in ('_game_ctm2_payoffs', '_cbql_ctm_geom') \
            and n.name not in seg:
        seg[n.name] = ast.get_source_segment(src, n)
assert len(seg) == 2, seg.keys()


def _dedent(t):
    ls = t.split('\n')
    return '\n'.join([ls[0]] + [l[4:] if l.startswith('    ') else l for l in ls[1:]])


class Inf(object):
    def __init__(self, **k):
        self.__dict__.update(k)


W = {'cur': 1, 'start': 0.0, 'veh': {}}
SWALLOWED = []
ns = {
    '_ctm2': _ctm2, '_CTM2_AVAILABLE': True,
    '_note_swallow': lambda tag, exc=None: SWALLOWED.append((tag, repr(exc))),
    'ECIGetCurrentPhase': lambda j: W['cur'],
    'ECIGetStartingTimePhase': lambda j: W['start'],
    'GetPhaseDuration': lambda j, p, ts: {1: 20.0, 2: 30.0}.get(int(p), 0.0),
    'AKIVehStateGetNbVehiclesSection': lambda s, b: len(W['veh'].get(int(s), [])),
    'AKIVehStateGetVehicleInfSection': lambda s, i: W['veh'][int(s)][i],
    'AKIInfNetGetSectionANGInf': lambda s: Inf(report=0, length=150.0, speedLimit=50.0),
    'CBQL_CTM_DT_S': 2.0, 'CBQL_CTM_MAX_CELLS': 12, 'CBQL_CTM_BUS_PCE': 2.0,
    'GAME_CTM2_HORIZON_S': 60.0, 'GAME_CTM2_IG_S': 5.0, 'INS_INTERGREEN_S': 5.0,
    'CELLQ_CTM_FREEFLOW_KMH': 50.0, 'CELLQ_CTM_WAVE_KMH': 18.0,
}
ns['globals'] = lambda: ns
exec('\n\n'.join(_dedent(seg[n]) for n in seg), ns)


class Ctl(object):
    id = 7
    node_id = 7
    BusPhase = 1
    bus_type_pos = 9
    BusOcc = 40.0
    CarOcc = 1.2
    JamDensity = 200.0
    SaturationFlow = 1800.0

    def _phase_origin_sections(self):
        return {1: {30}, 2: {40}}

    def _sec_lane_count(self, s):
        return 1

    def _ctm_params(self, s):
        return {}

    def _vlt_advance_vph(self, s):
        return None

    def _measured_section_flow_vph(self, s):
        return 400.0


for n in seg:
    setattr(Ctl, n, ns[n])
c = Ctl()
fails = []


def check(name, cond, detail=''):
    print('  %-4s %s %s' % ('ok' if cond else 'FAIL', name, detail))
    if not cond:
        fails.append(name)


def veh(d_from_stop, bus=False, spd=0.0):
    return Inf(CurrentPos=150.0 - d_from_stop, type=9 if bus else 1, CurrentSpeed=spd)


# 1. bus phase green with 3 s left; bus 25 m back behind 3 cars; cross queue
W.update(cur=1, start=-17.0)                  # 20 s green started 17 s ago -> 3 s left
W['veh'] = {30: [veh(2), veh(7), veh(12), veh(25, bus=True)],
            40: [veh(2), veh(7), veh(12), veh(17)]}
p = c._game_ctm2_payoffs([('GE', 3.0), ('GE', 8.0), ('PHASE_SKIP', 3.0),
                          ('EARLY_RED', 2.0)], 0.0)
print('  GE3 (B,C,b) =', tuple(round(x) for x in p[0]), ' GE8 =', tuple(round(x) for x in p[1]),
      ' ER2 =', tuple(round(x) for x in p[3]))
check('1 GE helps the bus and costs the cross street', p[0][2] > 0 and p[0][1] > 0, p[0])
check('1b longer GE helps the bus at least as much', p[1][2] >= p[0][2] - 1e-6, (p[0], p[1]))
check('5 untimed action -> None', p[2] is None)
check('3 ER while the bus approaches hurts it', p[3][2] < 0, p[3])

# 2. cross phase running (12 s left), bus queued at the bus-phase red
W.update(cur=2, start=-18.0)
W['veh'] = {30: [veh(2), veh(7, bus=True), veh(14)],
            40: [veh(2), veh(7)]}
q = c._game_ctm2_payoffs([('INS', 6.0), ('INS', 12.0), ('GREEN_REALLOC', 8.0)], 0.0)
print('  INS6 =', tuple(round(x) for x in q[0]), ' INS12 =', tuple(round(x) for x in q[1]),
      ' GR8 =', tuple(round(x) for x in q[2]))
check('2 INS helps the waiting bus and costs the cross street',
      q[0][2] > 0 and q[0][1] > 0, q[0])
check('2b longer insertion helps the bus at least as much', q[1][2] >= q[0][2] - 1e-6,
      (q[0], q[1]))
check('4 GR (cut the cross green) helps the waiting bus', q[2][2] > 0, q[2])

# 6. no bus anywhere -> bus payoff exactly 0
W['veh'] = {30: [veh(2), veh(7)], 40: [veh(2), veh(7)]}
z = c._game_ctm2_payoffs([('INS', 6.0)], 0.0)
check('6 no bus -> b == 0 (cars stay in the car class)', abs(z[0][2]) < 1e-9, z[0])

# 5b. interphase
W.update(cur=5)
check('5b interphase -> None', c._game_ctm2_payoffs([('GE', 3.0)], 0.0) is None)
check('7 nothing swallowed', not SWALLOWED, SWALLOWED[:3])
if fails:
    sys.exit('FAIL: %s' % fails)
print('PASS')
