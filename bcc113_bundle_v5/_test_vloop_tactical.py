"""End-to-end offline test of the tactical virtual loops, assumption checks and
TikZ export (2026-11-05). Pulls the REAL code out of engine.py with ast and
drives it with a small microscopic stand-in for Aimsun -- no Aimsun needed:

    python -I _test_vloop_tactical.py            (exit 0 = PASS)
    python -I _test_vloop_tactical.py --keep DIR (keep the output folder)

World (junction 7, 60 s cycle: phi1 0-30 s bus, phi2 30-40 s left, phi3 40-60 s):
  bus approach  sec 20 (200 m) -> sec 30 (150 m, stop line) -> exit 50,
                2 lanes, 600 veh/h/lane, a bus every 120 s dwelling 10 s at
                pos 100 on sec 20 (= 250 m from the stop line)
  side approach sec 40 (60 m): lane 1 through -> exit 61 (phi3), lane 2 is a
                30 m LEFT BAY -> exit 60 (phi2); nothing upstream (dead end)
Vehicles keep 5 m spacing (= 1/k_jam), run at 10 m/s, and leave the stop line
one per 2 s per lane on green (= 1800 veh/h/lane).

Checks
  1. warm-up learns: side lanes per movement (phi2 -> lane 2), the 30 m bay,
     the bus stop ~250 m upstream
  2. layouts: one per approach, ADVANCE clear of the shockwave queue and off
     the bus stop, BAY_ENTRY on the bay, side ADVANCE short -> warning
  3. loops count: STOPBAR discharge, ADVANCE arrivals ~ the generated flow
  4. assumption checks populated: saturation flow ~1800, formation wave,
     remaining green, advance-clear, bus ETA resolved at the stop bar
  5. _vlt_finish writes assumption_checks.csv, vloop_layout.csv and TikZ that
     compiles with pdflatex (when installed)
  6. no exception was swallowed anywhere in the new code
"""
import ast
import io
import math
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ENG = os.path.join(HERE, 'shared_tsp_engine')
sys.path.insert(0, ENG)
import shockwave_lwr as _swl  # noqa: E402
import vloop_layout as _vll  # noqa: E402
import tikz_phase as _tkz  # noqa: E402
import ctm_twoclass as _ctm2  # noqa: E402

src = io.open(os.path.join(ENG, 'engine.py'), encoding='utf-8').read()
tree = ast.parse(src)
MOD = ('_vlt_reset', '_vlt_ledger', '_vlt_scan', '_vlt_tick_all', '_vlt_finish',
       '_sec_len_m')
METH = ('_vlt_init', '_vlt_secs', '_vlt_tick', '_vlt_log', '_vlt_learn_stops',
        '_vlt_build', '_vlt_loops', '_vlt_checks', '_vlt_sat_check',
        '_vlt_ctm_sample', '_vlt_advance_vph', '_vlt_tikz_data', '_sw_lane_fd',
        '_cbql_ctm_geom')
seg = {}
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in MOD:
        seg[node.name] = ast.get_source_segment(src, node)
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name in METH and node.name not in seg:
        seg[node.name] = ast.get_source_segment(src, node)
missing = [n for n in MOD + METH if n not in seg]
if missing:
    sys.exit('ABORT: not found: %s' % missing)


def _dedent(t):
    ls = t.split('\n')
    return '\n'.join([ls[0]] + [l[4:] if l.startswith('    ') else l for l in ls[1:]])


# ---------------------------------------------------------------- the world
LEN = {20: 200.0, 30: 150.0, 40: 60.0, 50: 300.0, 60: 300.0, 61: 300.0}
LANES = {20: 2, 30: 2, 40: 2, 50: 2, 60: 1, 61: 1}
DUR = {1: 30.0, 2: 10.0, 3: 20.0}
START = {1: 0.0, 2: 30.0, 3: 40.0}
BUS = 7
SIM = {'t': 0.0}


def phase_at(t):
    c = t % 60.0
    return 1 if c < 30 else (2 if c < 40 else 3)


class Veh(object):
    _n = 0

    def __init__(self, sec, pos, lane, exit_sec, typ=1, dwell_at=None):
        Veh._n += 1
        self.id = Veh._n
        self.sec, self.pos, self.lane, self.exit = sec, pos, lane, exit_sec
        self.type, self.speed = typ, 36.0
        self.dwell_at, self.dwell_left = dwell_at, 10.0


VEHS = []
LAST_OUT = {}


def phase_of(sec, exit_sec):
    return {(30, 50): 1, (40, 60): 2, (40, 61): 3}.get((sec, exit_sec))


def step(t):
    """1 s of traffic: generate, move front-to-back per (sec, lane)."""
    if t % 6 == 0:
        for ln in (1, 2):
            VEHS.append(Veh(20, 0.0, ln, 50))
    if t % 120 == 30:
        VEHS.append(Veh(20, 0.0, 1, 50, BUS, dwell_at=100.0))
    if t % 10 == 0:
        VEHS.append(Veh(40, 0.0, 1, 61))
    if t % 15 == 0:
        VEHS.append(Veh(40, 30.0, 2, 60))         # the bay starts 30 m upstream
    groups = {}
    for v in VEHS:
        groups.setdefault((v.sec, v.lane), []).append(v)
    ph = phase_at(t)
    gone = []
    for (sec, ln), vs in groups.items():
        vs.sort(key=lambda v: -v.pos)
        lead_pos = None
        for k, v in enumerate(vs):
            p0 = v.pos
            want = v.pos + 10.0
            if v.dwell_at is not None and v.sec == 20 and v.pos <= v.dwell_at < want:
                want = v.dwell_at
            if v.dwell_at is not None and v.sec == 20 and abs(v.pos - v.dwell_at) < 1e-6:
                v.dwell_left -= 1.0
                want = v.pos if v.dwell_left > 0 else v.pos + 10.0
                if v.dwell_left <= 0:
                    v.dwell_at = None
            if lead_pos is not None:
                want = min(want, lead_pos - 5.0)
            if sec in (30, 40):
                L = LEN[sec]
                if k == 0 and want >= L:
                    ok = (phase_of(sec, v.exit) == ph
                          and t - LAST_OUT.get((sec, ln), -99) >= 2.0)
                    if ok:
                        LAST_OUT[(sec, ln)] = t
                        v.sec, v.pos, v.speed = v.exit, max(0.0, want - L), 36.0
                        v.lane = min(v.lane, LANES[v.exit])
                        continue
                    want = L - 0.5
            elif sec == 20 and want >= LEN[20]:
                tail = [w.pos for w in VEHS if w.sec == 30 and w.lane == ln]
                if not tail or min(tail) > 5.0:
                    v.sec, v.pos, v.speed = 30, want - LEN[20], 36.0
                    continue
                want = LEN[20] - 0.5
            elif sec in (50, 60, 61) and want > LEN[sec]:
                gone.append(v)
                continue
            want = max(want, p0)
            v.speed = (want - p0) * 3.6
            v.pos = want
            lead_pos = v.pos
    for v in gone:
        VEHS.remove(v)


class Inf(object):
    def __init__(self, **k):
        self.__dict__.update(k)


def _vehs_on(sec):
    return [v for v in VEHS if v.sec == sec]


LOG = []
SWALLOWED = []
OUT = tempfile.mkdtemp(prefix='vloop_test_')


class Stats(object):
    def _run_path(self):
        return OUT


ns = {
    '_vll': _vll, '_tkz': _tkz, '_swl': _swl, '_ctm2': _ctm2,
    '_VLL_AVAILABLE': True, '_CTM2_AVAILABLE': True, '_CBQL_AVAILABLE': False,
    '_SEC_LEN_CACHE': {}, '_CORRIDOR_DIR': OUT, 'os': os, 'math': math,
    'stats': Stats(), '_CURRENT_EXPERIMENT': 'TEST_ARM',
    'log_to_file': lambda m, force=False: LOG.append(m),
    '_note_swallow': lambda tag, exc=None: SWALLOWED.append((tag, repr(exc))),
    'AKIVehStateGetNbVehiclesSection': lambda s, b: len(_vehs_on(int(s))),
    'AKIVehStateGetVehicleInfSection': lambda s, i: (lambda v: Inf(
        idVeh=v.id, CurrentPos=v.pos, CurrentSpeed=v.speed, numberLane=v.lane,
        type=v.type))(_vehs_on(int(s))[i]),
    'AKIInfNetGetSectionANGInf': lambda s: Inf(report=0, length=LEN.get(int(s), 0.0),
                                               speedLimit=36.0,
                                               nbSideLanes=1 if int(s) == 40 else 0),
    'ECIGetCurrentPhase': lambda j: phase_at(SIM['t']),
    'GetPhaseDuration': lambda j, ph, ts: DUR[int(ph)],
    'VLOOP_TACTICAL': True, 'VLOOP_TAC_DT_S': 1.0, 'VLOOP_TAC_WARM_S': 300.0,
    'VLOOP_TAC_REACH_M': 450.0, 'ASSUME_CHECKS': True, 'ASSUME_LOG': True,
    'TIKZ_EXPORT': True, 'TIKZ_SAMPLE_S': 30.0, 'CBQL_CTM_DT_S': 2.0,
    'CBQL_CTM_MAX_CELLS': 12, 'SW_BUS_CRUISE_KMH': 36.0, 'INS_INTERGREEN_S': 5.0,
    'MAX_GE_EXTENSION_S': 10.0, 'CELLQ_CTM_FREEFLOW_KMH': 36.0,
    'CELLQ_CTM_WAVE_KMH': 11.0, 'VLOOP_STOP_KPH': 3.0, 'CBQL_CTM_BUS_PCE': 2.0,
}
ns['globals'] = lambda: ns
ns['_VLT'] = {'ledger': None, 'tick_t': -1.0e9, 'scan_t': None, 'scan': {}, 'errs': 0}
exec('\n\n'.join(seg[n] for n in MOD), ns)
exec('\n\n'.join(_dedent(seg[n]) for n in METH), ns)


class Ctl(object):
    id = 7
    node_id = 7
    BusPhase = 1
    bus_type_pos = BUS
    JamDensity = 200.0
    SaturationFlow = 1800.0

    def __init__(self):
        self.NextRedStartTime = [[30.0]]

    def _phase_origin_sections(self):
        return {1: {30}, 2: {40}, 3: {40}}

    def _cbql_phase_turnings(self):
        return {1: [(30, 50)], 2: [(40, 60)], 3: [(40, 61)]}

    def _upstream_chain(self, sec, reach):
        if int(sec) == 30:
            return [(30, 0.0, 150.0), (20, 150.0, 200.0)], 'managed'
        return [(int(sec), 0.0, LEN[int(sec)])], 'dead'

    def _sec_lane_count(self, s):
        return LANES.get(int(s), 1)

    def _measured_section_flow_vph(self, s):
        return {30: 1200.0, 40: 600.0}.get(int(s), 0.0)

    def _signal_cycle_s(self, ts=0.0):
        return 60.0

    def _ctm_params(self, s):
        return {}

    def _cbql_bearing(self, s):
        return {20: 90.0, 30: 90.0, 50: 90.0, 40: 0.0, 61: 0.0, 60: 90.0}.get(int(s))

    def _cbql_turn_type(self, f, t):
        d = (self._cbql_bearing(t) - self._cbql_bearing(f) + 180) % 360 - 180
        return 'through' if abs(d) <= 35 else ('left' if d > 0 else 'right')


for n in METH:
    setattr(Ctl, n, ns[n])
c = Ctl()
ns['controllers'] = {7: c}
ns['_vlt_reset']()

for t in range(0, 1501):
    SIM['t'] = float(t)
    ph = phase_at(t)
    cs = t - (t % 60)
    c.NextRedStartTime = [[cs + 30.0 if ph == 1 else cs + 60.0 + 30.0]]
    step(t)
    ns['_vlt_tick_all'](float(t), 0.0)
ns['_vlt_finish']()

fails = []


def check(name, cond, detail=''):
    print('  %-4s %s %s' % ('ok' if cond else 'FAIL', name, detail))
    if not cond:
        fails.append(name)


v = c._vlt
aps = {(a['phase'], a['stop_sec']): a for a in v['approaches']}
lay_lines = [m for m in LOG if m.startswith('[VLOOP_LAYOUT]')]
print('\n'.join(lay_lines))
check('1a lanes learned: phi2 uses lane 2 only',
      aps[(2, 40)]['layout'].spec.lanes == (2,), aps[(2, 40)]['layout'].spec.lanes)
check('1b 30 m bay learned on lane 2',
      aps[(2, 40)]['layout'].spec.bay_len_m is not None
      and 25.0 <= aps[(2, 40)]['layout'].spec.bay_len_m <= 31.0,
      aps[(2, 40)]['layout'].spec.bay_len_m)
st = aps[(1, 30)]['layout'].spec.stops_m
check('1c bus stop learned ~250 m', any(240.0 <= s_ <= 260.0 for s_ in st), st)
bl = aps[(1, 30)]['layout']
by = {p: lp for lp in bl.loops for p in lp.purposes}
check('2a bus ADVANCE beyond the shockwave queue', by['ADVANCE'].x_m > bl.l_max_m,
      (by['ADVANCE'].x_m, bl.l_max_m))
check('2b no loop on the bus stop (except check-in)',
      all(abs(lp.x_m - 250.0) >= 25.0 for lp in bl.loops
          if 'BUS_CHECKIN' not in lp.purposes and lp.x_m > 0))
sl = aps[(2, 40)]['layout']
bys = {p: lp for lp in sl.loops for p in lp.purposes}
check('2c BAY_ENTRY on the bay lane', 'BAY_ENTRY' in bys and bys['BAY_ENTRY'].lanes == (2,))
check('2d side ADVANCE short -> warning', any('ADVANCE short' in w for w in sl.warnings),
      sl.warnings)
sb = c._vlt_loops(aps[(1, 30)], 'STOPBAR')[0]
adv = c._vlt_loops(aps[(1, 30)], 'ADVANCE')[0]
r_adv = _vll.PointLoopBank.reading(adv, 1500.0, 600.0)
check('3a STOPBAR counts discharge', len(sb.crossings) > 50, len(sb.crossings))
check('3b ADVANCE ~ generated 1200 veh/h (2 lanes)', 900 <= r_adv['flow_vph'] <= 1400,
      r_adv['flow_vph'])
sm = ns['_vlt_ledger']().summary()
for k in sorted(sm):
    print('     summary %-38s %s' % (k, tuple(None if x is None else round(x, 2) for x in sm[k])))
sat = sm.get('saturation_flow_vph_lane')
check('4a saturation flow measured ~1800', sat is not None and abs(sat[1]) < 200.0, sat)
check('4b formation wave compared', 'queue_formation_wave_ms' in sm)
check('4c remaining-green checks resolved',
      'rem_green_nextred_s' in sm and abs(sm['rem_green_nextred_s'][1]) <= 1.5,
      sm.get('rem_green_nextred_s'))
check('4d advance-clear flag recorded', any(k.startswith('advance_clear') for k in sm))
files = sorted(os.listdir(os.path.join(OUT, 'tikz'))) if os.path.isdir(os.path.join(OUT, 'tikz')) else []
check('5a CSVs written', os.path.isfile(os.path.join(OUT, 'assumption_checks.csv'))
      and os.path.isfile(os.path.join(OUT, 'vloop_layout.csv')))
check('5b TikZ written', 'figures.tex' in files and any('phase_sequence' in f for f in files)
      and any('ctm_cells' in f for f in files), files)
if shutil.which('pdflatex') and 'figures.tex' in files:
    r = subprocess.run(['pdflatex', '-interaction=nonstopmode', 'figures.tex'],
                       cwd=os.path.join(OUT, 'tikz'), capture_output=True, text=True)
    check('5c TikZ compiles', r.returncode == 0 and os.path.isfile(
        os.path.join(OUT, 'tikz', 'figures.pdf')),
          [l for l in r.stdout.splitlines() if l.startswith('!')][:3])
else:
    print('  skip 5c (no pdflatex)')
check('6 nothing swallowed', not SWALLOWED, SWALLOWED[:5])
for m in LOG:
    if m.startswith('[ASSUME]'):
        print('  ' + m)
        break
keep = '--keep' in sys.argv
if keep:
    dst = sys.argv[sys.argv.index('--keep') + 1]
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(OUT, dst)
    print('kept output in', dst)
shutil.rmtree(OUT, ignore_errors=True)
if fails:
    sys.exit('FAIL: %s' % fails)
print('PASS')
