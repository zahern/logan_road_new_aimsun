# -*- coding: utf-8 -*-
"""Offline test of the CTM2 payoff stack AS PORTED INTO THE SUMO FORK.

    python _sumo_port/_test_ctm2_sumo.py        (exit 0 = PASS)

Pulls the REAL methods out of Z:/tsp/sumo_hpc/shared_tsp_engine/engine.py with
ast and drives them with a fake junction, so it tests the ported code, not a
copy of it. Junction 7: phase 1 = bus (main) phase on section 30, phase 2 =
cross phase on section 40; greens 20 / 30 s, intergreen 5 s.

Checks
  1  bus phase green, 3 s left, bus 25 m back: GE helps the bus, costs the cross
     street; a longer GE never helps the bus less
  2  cross phase running, bus queued: INS helps the bus and costs the cross
     street; GR (cut the cross green) helps the waiting bus
  3  ER while the bus is still approaching hurts it (b < 0)
  4  untimed action -> None entry; interphase -> lead-time payoffs (no fallback)
  5  nothing modelled -> None + one [GAME_CTM2_NA] reason per junction
  6  no bus anywhere -> b == 0 (buses are the BUS class, not cars)
  7  _vlt_advance_vph: None until the ADVANCE loop bank is built (the payoff
     then falls back to _measured_section_flow_vph); the section window counter
     never leaks into the loop reading
  8  _section_jam_frac: 0.0 empty, ~1.0 jammed, >1.0 over storage
  9  GAME_CTM2_SPILLBACK actually bites: with the receiving link full the
     discharge is throttled and the payoffs move (a _SPILL arm must not be
     byte-identical to its non-spill twin)
 10  nothing swallowed
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
import ctm_twoclass as _ctm2  # noqa: E402

src = io.open(os.path.join(FORK, 'engine.py'), encoding='utf-8').read()
WANT = ('_game_ctm2_payoffs', '_cbql_ctm_geom', '_game_ctm2_na',
        '_vlt_advance_vph', '_section_jam_frac', '_phase_downstream_block')
seg = {}
for n in ast.walk(ast.parse(src)):
    if isinstance(n, ast.FunctionDef) and n.name in WANT and n.name not in seg:
        seg[n.name] = ast.get_source_segment(src, n)
missing = [w for w in WANT if w not in seg]
if missing:
    sys.exit('MISSING from engine.py: %s' % missing)


def _dedent(t):
    ls = t.split('\n')
    return '\n'.join([ls[0]] + [l[4:] if l.startswith('    ') else l for l in ls[1:]])


class Inf(object):
    def __init__(self, **k):
        self.__dict__.update(k)


W = {'cur': 1, 'start': 0.0, 'veh': {}, 't': 0.0, 'win': 0.0}
SWALLOWED = []
LOG = []
ns = {
    'log_to_file': lambda m, force=False: LOG.append(m),
    '_ctm2': _ctm2, '_CTM2_AVAILABLE': True, '_vll': None,
    '_note_swallow': lambda tag, exc=None: SWALLOWED.append((tag, repr(exc))),
    'ECIGetCurrentPhase': lambda j: W['cur'],
    'ECIGetStartingTimePhase': lambda j: W['start'],
    'GetPhaseDuration': lambda j, p, ts: {1: 20.0, 2: 30.0}.get(int(p), 0.0),
    'AKIVehStateGetNbVehiclesSection': lambda s, b: len(W['veh'].get(int(s), [])),
    'AKIVehStateGetVehicleInfSection': lambda s, i: W['veh'][int(s)][i],
    'AKIInfNetGetSectionANGInf': lambda s: Inf(report=0, length=150.0,
                                              speedLimit=50.0,
                                              nbCentralLanes=1, nbSideLanes=0),
    'AKIGetCurrentSimulationTime': lambda: W['t'],
    'CBQL_CTM_DT_S': 2.0, 'CBQL_CTM_MAX_CELLS': 12, 'CBQL_CTM_BUS_PCE': 2.0,
    'GAME_CTM2_HORIZON_S': 60.0, 'GAME_CTM2_IG_S': 5.0, 'INS_INTERGREEN_S': 5.0,
    'CELLQ_CTM_FREEFLOW_KMH': 50.0, 'CELLQ_CTM_WAVE_KMH': 18.0,
    'JAM_VEH_SPACING_M': 7.0,
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
    _win = 400.0

    def _phase_origin_sections(self):
        return {1: {30}, 2: {40}}

    def _phase_origin_dests(self):
        return {1: {31}, 2: {41}}

    def _sec_lane_count(self, s):
        return 1

    def _ctm_params(self, s):
        return {}

    def _section_window_flow(self, sec, now, window_s, sec_len_hint=0.0,
                             allow_seed=True):
        return 0.0 if W['win'] is None else W['win']

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


def run(acts, **kw):
    for k, v in kw.items():
        ns[k] = v
    return c._game_ctm2_payoffs(list(acts), 0.0)


print('engine:', os.path.join(FORK, 'engine.py'))
print('ctm_twoclass selftest:', _ctm2._selftest())

# 1. bus phase green with 3 s left; bus 25 m back behind 3 cars; cross queue
W.update(cur=1, start=-17.0)
W['veh'] = {30: [veh(2), veh(7), veh(12), veh(25, bus=True)],
            40: [veh(2), veh(7), veh(12), veh(17)]}
p = run([('GE', 3.0), ('GE', 8.0), ('PHASE_SKIP', 3.0), ('EARLY_RED', 2.0)])
print('  GE3 (B,C,b) =', tuple(round(x) for x in p[0]),
      ' GE8 =', tuple(round(x) for x in p[1]), ' ER2 =', tuple(round(x) for x in p[3]))
check('1 GE helps the bus and costs the cross street', p[0][2] > 0 and p[0][1] > 0, p[0])
check('1b longer GE helps the bus at least as much', p[1][2] >= p[0][2] - 1e-6)
check('4 untimed action -> None', p[2] is None)
check('3 ER while the bus approaches hurts it', p[3][2] < 0, p[3])

# 2. cross phase running (12 s left), bus queued at the bus-phase red
W.update(cur=2, start=-18.0)
W['veh'] = {30: [veh(2), veh(7, bus=True), veh(14)], 40: [veh(2), veh(7)]}
q = run([('INS', 6.0), ('INS', 12.0), ('GREEN_REALLOC', 8.0)])
print('  INS6 =', tuple(round(x) for x in q[0]), ' INS12 =', tuple(round(x) for x in q[1]),
      ' GR8 =', tuple(round(x) for x in q[2]))
check('2 INS helps the waiting bus and costs the cross street',
      q[0][2] > 0 and q[0][1] > 0, q[0])
check('2b longer insertion helps the bus at least as much', q[1][2] >= q[0][2] - 1e-6)
check('2c GR (cut the cross green) helps the waiting bus', q[2][2] > 0, q[2])

# 6. no bus anywhere -> bus payoff exactly 0
W['veh'] = {30: [veh(2), veh(7)], 40: [veh(2), veh(7)]}
z = run([('INS', 6.0)])
check('6 no bus -> b == 0 (cars stay in the car class)', abs(z[0][2]) < 1e-9, z[0])

# 4b. interphase (phase 5, 4 s left): all red, then the ring resumes
W.update(cur=5, start=-1.0)
ns['GetPhaseDuration'] = lambda j, p, ts: {1: 20.0, 2: 30.0, 5: 5.0}.get(int(p), 0.0)
W['veh'] = {30: [veh(2), veh(7, bus=True)], 40: [veh(2)]}
pi = run([('INS', 6.0), ('GE', 3.0)])
check('4b interphase -> lead-time payoffs (no fallback)',
      pi is not None and pi[0] is not None, pi)

# 5c. nothing modelled -> None + one [GAME_CTM2_NA] reason
Ctl._phase_origin_sections = lambda self: {}
check('5c no modelled phases -> None', run([('GE', 3.0)]) is None)
run([('GE', 3.0)])
na = [m for m in LOG if m.startswith('[GAME_CTM2_NA]')]
check('5d reason logged once per junction', len(na) == 1, na)
Ctl._phase_origin_sections = lambda self: {1: {30}, 2: {40}}

# 7. _vlt_advance_vph after the vloop port (2026-11-06): the ADVANCE loop bank
#    is the only source. Not built -> None, and _game_ctm2_payoffs falls back
#    to _measured_section_flow_vph. VLOOP_TAC_FEED_CTM gates even the call.
check('7 loops not built -> None (payoff falls back)', c._vlt_advance_vph(30) is None)
check('7b the fallback itself answers',
      abs(c._measured_section_flow_vph(30) - 400.0) < 1e-6)
W['win'] = 540.0
check('7c the section window counter never leaks into the loop reading',
      c._vlt_advance_vph(30) is None, c._vlt_advance_vph(30))
W['win'] = 400.0
ns['VLOOP_TAC_FEED_CTM'] = False
check('7d VLOOP_TAC_FEED_CTM=False still runs the payoff',
      run([('INS', 6.0)]) is not None)
ns['VLOOP_TAC_FEED_CTM'] = True

# 8. _section_jam_frac: empty 0, jammed ~1, over storage > 1
W['veh'] = {31: []}
check('8 empty link -> 0.0', c._section_jam_frac(31) == 0.0)
_cap = (150.0 * 1) / 7.0
W['veh'] = {31: [veh(5) for _ in range(int(round(_cap)))]}
check('8b full link -> ~1.0', 0.9 <= c._section_jam_frac(31) <= 1.1,
      round(c._section_jam_frac(31), 3))
W['veh'] = {31: [veh(5) for _ in range(int(round(_cap * 1.4)))]}
check('8c over storage -> > 1.0', c._section_jam_frac(31) > 1.1,
      round(c._section_jam_frac(31), 3))

# 9. spillback must bite: same junction, receiving links 101/102 either free or full
W.update(cur=2, start=-18.0)
W['veh'] = {30: [veh(2), veh(7, bus=True), veh(14)], 40: [veh(2), veh(7)]}
Ctl._phase_origin_dests = lambda self: {1: {101}, 2: {102}}
W['veh'][101] = []
W['veh'][102] = []
free = c._game_ctm2_payoffs([('INS', 6.0)], 0.0)
W['veh'][101] = [veh(5) for _ in range(int(_cap * 1.5))]
W['veh'][102] = [veh(5) for _ in range(int(_cap * 1.5))]
block = c._game_ctm2_payoffs([('INS', 6.0)], 0.0)   # spill OFF by default
ns['GAME_CTM2_SPILLBACK'] = True
spill = c._game_ctm2_payoffs([('INS', 6.0)], 0.0)
ns['GAME_CTM2_SPILLBACK'] = False
print('  free =', tuple(round(x) for x in free[0]),
      ' spill(off,jammed) =', tuple(round(x) for x in block[0]),
      ' spill(on,jammed) =', tuple(round(x) for x in spill[0]))
check('9 downstream jam feeds _phase_downstream_block',
      c._phase_downstream_block(1) > 0.5, c._phase_downstream_block(1))
check('9b GAME_CTM2_SPILLBACK changes the payoff (throttled discharge)',
      any(abs(a - b) > 1e-6 for a, b in zip(spill[0], block[0])),
      (spill[0], block[0]))
check('9c spillback off = free-sink CTM regardless of the jam',
      all(abs(a - b) < 1e-6 for a, b in zip(free[0], block[0])))

check('10 nothing swallowed', not SWALLOWED, SWALLOWED[:3])
if fails:
    sys.exit('FAIL: %s' % fails)
print('PASS')
