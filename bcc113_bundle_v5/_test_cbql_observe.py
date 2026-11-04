"""Offline test of the CBQL-TSP engine wiring (2026-11-05): the observe step
(_cbql_observe), the execute step (_cbql_execute), the shared learn step and
the bus-delay measure, against the two-controller learner in cbql_shapley.py.

Pulls the REAL methods out of engine.py with ast (so this tests the patched
source, not a copy) and drives them with a fake controller -- no Aimsun:

    python -I _test_cbql_observe.py        (exit 0 = PASS)

Checks:
  observe
    1. first step credits nothing (R=-)
    2. each later step credits the phase green at the PREVIOUS step, in the
       PREVIOUS state, with BOTH controllers' rewards measured NOW
    3. R_P carries the bus-delay term; R_N does not
    4. an interphase step leaves nothing to credit
    5. ratios are never 0/1; 60 s throttle kept
    6. observe does nothing on the execute arm (no double learning)
  execute
    7. a held phase is credited as a hold; an applied switch as the switch
    8. a RATE-CAPPED switch is credited as the hold it really was
  bus delay
    9. max over buses on priority sections of time-on-section minus
       distance / free speed; cars and non-priority sections ignored
"""
import ast
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENG = os.path.join(HERE, 'shared_tsp_engine')
sys.path.insert(0, ENG)
import cbql_shapley as _cbql  # noqa: E402
import ctm_twoclass as _ctm2  # noqa: E402

src = io.open(os.path.join(ENG, 'engine.py'), encoding='utf-8').read()
WANT = ('_cbql_observe', '_cbql_execute', '_cbql_learn_step',
        '_cbql_bus_delay_s', '_cbql_next_green_phase', '_cbql_ctm_on',
        '_cbql_ctm_geom', '_cbql_ctm_snapshot', '_cbql_ctm_eval',
        '_cbql_ctm_bus_w', '_cbql_make_state', '_cbql_commit')
found = {}
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.FunctionDef) and node.name in WANT:
        found[node.name] = ast.get_source_segment(src, node)
missing = [w for w in WANT if w not in found]
if missing:
    sys.exit('ABORT: not found in engine.py: %s' % missing)


def _dedent_method(seg):
    # first line has no indent (get_source_segment), the body has 8 spaces
    lines = seg.split('\n')
    return '\n'.join([lines[0]] + [l[4:] if l.startswith('    ') else l
                                   for l in lines[1:]])


LOG = []
SIM = {'cur': 1, 'now': 0.0, 'start': 0.0}
SWITCHES = []


class VehInf(object):
    def __init__(self, typ, entered, pos):
        self.type = typ
        self.SectionEntranceT = entered
        self.CurrentPos = pos


VEH = {}          # section -> [VehInf]
class SecInf(object):
    report = 0
    length = 200.0
    speedLimit = 50.0


SWALLOWED = []
ns = {
    '_note_swallow': lambda tag, exc=None: SWALLOWED.append((tag, repr(exc))),
    '_cbql': _cbql,
    '_ctm2': _ctm2,
    '_CTM2_AVAILABLE': True,
    'CBQL_USE_CTM': False,              # first block: measured-delay feed
    'AKIInfNetGetSectionANGInf': lambda s: SecInf(),
    'log_to_file': lambda msg, force=False: LOG.append(msg),
    'ECIGetCurrentPhase': lambda jid: SIM['cur'],
    'ECIGetStartingTimePhase': lambda jid: SIM['start'],
    'GetPhaseDuration': lambda jid, ph, t: 30.0,
    'AKIGetCurrentSimulationTime': lambda: SIM['now'],
    'AKIVehStateGetNbVehiclesSection': lambda s, b: len(VEH.get(s, [])),
    'AKIVehStateGetVehicleInfSection': lambda s, i: VEH[s][i],
    'ECIChangeDirectPhaseWithInterphaseTransition':
        lambda jid, ph, ts, now, cyc: SWITCHES.append((now, ph)),
    'CBQL_EXECUTE': False,
    'CBQL_BUS_DELAY_W': 1.0,
    'CBQL_BUS_FREE_KMH': 36.0,          # 10 m/s -> easy arithmetic
    'CBQL_MIN_GREEN_S': 7.0,
    'CBQL_MAX_GREEN_S': 60.0,
    'CBQL_DECISION_COOLDOWN_S': 0.0,
    'CBQL_MAX_SWITCHES_PER_CYCLE': 4,
}
ns['globals'] = lambda: ns         # engine reads flags via globals().get
exec('\n\n'.join(_dedent_method(found[w]) for w in WANT), ns)

STRUCT = _cbql.PhaseStructure(
    38339, 4, {1: 'through', 2: 'through', 3: 'protected_left', 4: 'through'},
    (1,), (2, 3, 4), 120.0)
LEARNS = []


class RecCtl(_cbql.CbqlTspController):
    def learn(self, prev_state, prev_action, rewards, state):
        LEARNS.append((prev_state, prev_action, dict(rewards)))
        return super().learn(prev_state, prev_action, rewards, state)


class Ctl(object):
    bus_type_pos = 7
    TSPActiveTime = 0.0
    JamDensity = 200.0
    SaturationFlow = 1800.0
    BusOcc = 40.0
    CarOcc = 1.5

    def _sec_lane_count(self, s):
        return 1

    def _ctm_params(self, s):
        return {}

    def _measured_section_flow_vph(self, s):
        return 300.0

    def _vlt_advance_vph(self, s):
        return None          # tactical loops not built -> measured-flow fallback

    def __init__(self):
        self._cbql_struct = STRUCT
        self._cbql_ctl = RecCtl(STRUCT, seed=1)
        self._cbql_prev = None
        self._cbql_last_log = -1.0e9

    def _cbql_ensure(self):
        return self._cbql_struct

    def _cbql_phase_delay_flow(self, st):
        return dict(DELAY), {p: 300.0 for p in st.phase_types}

    def _phase_origin_sections(self):
        return {1: {101}, 2: {201}, 3: {301}, 4: {401}}

    def _ped_protected_phases(self):
        return set()

    def _signal_cycle_s(self, ts):
        return 120.0


for _w in WANT:
    setattr(Ctl, _w, ns[_w])
fails = []


def check(name, cond, detail=''):
    print('  %-4s %s %s' % ('ok' if cond else 'FAIL', name, detail))
    if not cond:
        fails.append(name)


def ratios(line):
    m = re.search(r"ratios=\{'P': ([\d.]+), 'N': ([\d.]+)\}", line)
    return (float(m.group(1)), float(m.group(2))) if m else None


print('observe')
c = Ctl()
DELAY = {1: 55.0, 2: 56.0, 3: 56.0, 4: 56.0}
SIM.update(cur=1, now=60.0)
c._cbql_observe(60.0, 0.0)
check('1 first step credits nothing', ' R=- ' in LOG[-1] and not LEARNS, LOG[-1])
s1 = c._cbql_prev[0]

# a bus on the priority approach: 30 s on section, 100 m covered at 10 m/s
# -> 20 s delay. A car and a bus on a NON-priority section are ignored.
VEH = {101: [VehInf(7, 90.0, 100.0), VehInf(1, 0.0, 0.0)],
       201: [VehInf(7, 0.0, 0.0)]}
DELAY = {1: 20.0, 2: 70.0, 3: 60.0, 4: 80.0}
SIM.update(cur=2, now=120.0)
c._cbql_observe(120.0, 0.0)
pst, pact, rw = LEARNS[-1]
check('2 credits previous green phase in previous state',
      pact == 1 and pst is s1, (pact,))
check('3 R_P = -(dP + bus), R_N = -mean dN',
      rw == {'P': -40.0, 'N': -70.0}, rw)
check('9 bus delay = 20 s (bus on priority section only)',
      'bus=20.0' in LOG[-1], LOG[-1])
r = ratios(LOG[-1])
check('5 ratios not 0/1', r and 0.0 < r[0] < 1.0 and 0.0 < r[1] < 1.0, r)

SIM.update(cur=99, now=180.0)
n = len(LEARNS)
c._cbql_observe(180.0, 0.0)
check('2b phase 2 credited at step 3', len(LEARNS) == n + 1
      and LEARNS[-1][1] == 2)
check('4 interphase leaves nothing pending', c._cbql_prev is None)
SIM.update(cur=3, now=240.0)
c._cbql_observe(240.0, 0.0)
check('4b no credit after interphase', len(LEARNS) == n + 1)
n_log = len(LOG)
c._cbql_observe(250.0, 0.0)
check('5b 60 s throttle kept', len(LOG) == n_log)
ns['CBQL_EXECUTE'] = True
n_log, n = len(LOG), len(LEARNS)
c._cbql_observe(400.0, 0.0)
check('6 observe idle on execute arm', len(LOG) == n_log and len(LEARNS) == n)

print('execute')
VEH.clear()
c = Ctl()
c._cbql_ctl.sample = False        # deterministic picks for the test
LEARNS[:] = []
SWITCHES[:] = []
DELAY = {1: 30.0, 2: 30.0, 3: 30.0, 4: 30.0}
# fresh table, argmax of a uniform mix -> lowest id (1) == current -> HOLD
SIM.update(cur=1, now=10.0, start=0.0)
c._cbql_execute(10.0, 0.0, 0)
check('7 hold stored as current phase', c._cbql_prev[1] == 1 and not SWITCHES)
# force a switch: at max green the executor advances to the next phase
SIM.update(cur=1, now=70.0, start=0.0)
c._cbql_execute(70.0, 0.0, 0)
check('7b applied switch stored as the new phase',
      SWITCHES and SWITCHES[-1][1] == 2 and c._cbql_prev[1] == 2, SWITCHES)
check('7c previous hold was credited', LEARNS and LEARNS[-1][1] == 1)
# rate cap: make the agent want phase 3, with the switch budget exhausted
c._cbql_switch_times = [65.0, 66.0, 67.0, 68.0]
SIM.update(cur=2, now=80.0, start=70.0)
c._cbql_ctl.act = lambda st: (3, {1: 0, 2: 0, 3: 1.0, 4: 0}, {'P': .5, 'N': .5})
n_sw = len(SWITCHES)
c._cbql_execute(80.0, 0.0, 0)
check('8 rate-capped switch not applied', len(SWITCHES) == n_sw)
check('8b ...and credited as a hold of phase 2', c._cbql_prev[1] == 2,
      c._cbql_prev[1])

print('two-class CTM feed')
ns['CBQL_EXECUTE'] = False
ns['CBQL_USE_CTM'] = True
c = Ctl()
LEARNS[:] = []
VEH.clear()
# phase 1 (priority, section 101): a bus 10 m and 3 cars near the stop line;
# phase 2 (section 201): 6 cars queued. Phase 1 green.
VEH[101] = [VehInf(7, 0.0, 190.0), VehInf(1, 0.0, 195.0),
            VehInf(1, 0.0, 185.0), VehInf(1, 0.0, 180.0)]
VEH[201] = [VehInf(1, 0.0, 200.0 - 4.0 * k) for k in range(6)]
DELAY = {1: 10.0, 2: 10.0, 3: 10.0, 4: 10.0}
SIM.update(cur=1, now=1000.0)
c._cbql_observe(1000.0, 0.0)
st1 = c._cbql_prev[0]
check('10 state carries CTM queues + bus level',
      st1.phase_queue is not None and st1.bus_level == 1
      and len(st1.encode()) == 5, st1)
check('10b phase 2 (red) shows its queue, phase 1 (green) little',
      st1.phase_queue[1] >= 5.0 and st1.phase_queue[0] < st1.phase_queue[1],
      st1.phase_queue)
rw_hold = c._cbql_prev[2]
check('11 CTM rewards stored at commit', rw_hold is not None
      and rw_hold['P'] <= 0.0 and rw_hold['N'] < 0.0, rw_hold)
check('11b log shows ctmQ/busLvl', 'ctmQ=' in LOG[-1] and 'busLvl=1' in LOG[-1],
      LOG[-1])
SIM.update(cur=1, now=1060.0)
c._cbql_observe(1060.0, 0.0)
check('12 learn used the STORED CTM rewards, not the .DTa feed',
      LEARNS and LEARNS[-1][2] == rw_hold and LEARNS[-1][0] is st1,
      LEARNS[-1:])
# switching AWAY from the bus phase must cost the priority controller more
# than holding it; switching TO phase 2 helps N
_snap, _nb = c._cbql_ctm_snapshot(STRUCT)
rw_away = c._cbql_commit(STRUCT, st1, _snap, 1, 2)
check('13 switch away from bus phase: R_P worse, R_N better',
      rw_away['P'] < rw_hold['P'] and rw_away['N'] > rw_hold['N'],
      (rw_hold, rw_away))
check('13b bus weight defaults to BusOcc/CarOcc',
      abs(c._cbql_ctm_bus_w() - 40.0 / 1.5) < 1e-9)
ns['CBQL_USE_CTM'] = False
c2 = Ctl()
SIM.update(cur=1, now=2000.0)
c2._cbql_observe(2000.0, 0.0)
check('14 CBQL_USE_CTM=False -> old flow state, no CTM rewards',
      c2._cbql_prev[0].phase_queue is None and c2._cbql_prev[2] is None)

print('\nlast log line:', LOG[-1])
print('swallowed:', SWALLOWED or 'none')
if fails:
    sys.exit('FAIL: %s' % fails)
print('PASS')
