"""Offline test of the CBQL observe step (engine._cbql_observe) and the
Shapley ratio fix in cbql_shapley.py (2026-11-05).

Pulls the REAL _cbql_observe method out of engine.py with ast (so this tests
the patched source, not a copy) and drives it with a fake controller -- no
Aimsun needed:

    python -I _test_cbql_observe.py        (exit 0 = PASS)

Checks:
  1. ratios are never pinned at 1.0/0.0 (the KG log symptom)
  2. the first step credits nothing (R=-)
  3. each later step credits the phase that was green at the PREVIOUS step,
     in the PREVIOUS step's state, with the delay measured NOW -- never the
     logged pick
  4. an interphase step leaves nothing to credit at the next step
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

src = io.open(os.path.join(ENG, 'engine.py'), encoding='utf-8').read()
meth = None
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.FunctionDef) and node.name == '_cbql_observe':
        meth = ast.get_source_segment(src, node)
        break
if meth is None:
    sys.exit('ABORT: _cbql_observe not found in engine.py')

LOG = []
STATE = {'cur': 1}
ns = {
    '_cbql': _cbql,
    'log_to_file': lambda msg, force=False: LOG.append(msg),
    'ECIGetCurrentPhase': lambda jid: STATE['cur'],
    'GetPhaseDuration': lambda jid, ph, t: 30.0,
    'CBQL_SHAPLEY_TEMP_S': 10.0,
}
exec('import textwrap\n' + 'def _cbql_observe' +
     meth.split('def _cbql_observe', 1)[1].replace('\n    ', '\n'), ns)
ns['globals'] = lambda: ns         # engine reads flags via globals().get

STRUCT = _cbql.PhaseStructure(
    38339, 4, {1: 'through', 2: 'through', 3: 'protected_left', 4: 'through'},
    (1,), (2, 3, 4), 120.0)


class RecAgent(_cbql.CbqlShapleyAgent):
    def update(self, state, phase, reward, shapley_v):
        UPDATES.append((state, phase, reward))
        super().update(state, phase, reward, shapley_v)


UPDATES = []


class Ctl(object):
    _cbql_struct = STRUCT
    _cbql_agent = RecAgent(STRUCT)
    _cbql_last_log = -1.0e9

    def _cbql_ensure(self):
        return self._cbql_struct

    def _cbql_phase_delay_flow(self, st):
        return dict(DELAY), {p: 300.0 for p in st.phase_types}


Ctl._cbql_observe = ns['_cbql_observe']
c = Ctl()
fails = []


def check(name, cond, detail=''):
    print('  %-4s %s %s' % ('ok' if cond else 'FAIL', name, detail))
    if not cond:
        fails.append(name)


def ratios(line):
    m = re.search(r"ratios=\{'P': ([\d.]+), 'N': ([\d.]+)\}", line)
    return (float(m.group(1)), float(m.group(2))) if m else None


# step 1: phase 1 green, delays close (55 vs 56) -- the old code gave 1.0/0.0
DELAY = {1: 55.0, 2: 56.0, 3: 56.0, 4: 56.0}
STATE['cur'] = 1
c._cbql_observe(60.0, 0.0)
r = ratios(LOG[-1])
check('ratios not pinned on a 1 s gap', r and 0.4 < r[0] < 0.6, LOG[-1])
check('first step credits nothing', ' R=- ' in LOG[-1] and not UPDATES)
s1 = c._cbql_prev[0]

# step 2: phase 2 now green; phase 1 (green last step) must be credited with
# the delay measured NOW on phase 1, in step 1's state
DELAY = {1: 20.0, 2: 70.0, 3: 70.0, 4: 70.0}
STATE['cur'] = 2
c._cbql_observe(120.0, 0.0)
check('credits previous green phase', UPDATES and UPDATES[-1][1] == 1,
      UPDATES[-1:])
check('reward = delay measured now', UPDATES[-1][2] == -20.0)
check('credited in previous state', UPDATES[-1][0] is s1)
r = ratios(LOG[-1])
check('large gap: strong but not 0/1', r and r[0] > 0.9 and r[1] > 0.0,
      LOG[-1])

# step 3: interphase (99 is not a known phase) -> phase 2 credited, then nothing
# pending for step 4
STATE['cur'] = 99
n = len(UPDATES)
c._cbql_observe(180.0, 0.0)
check('phase 2 credited at step 3', len(UPDATES) == n + 1
      and UPDATES[-1][1] == 2 and UPDATES[-1][2] == -70.0)
check('interphase leaves nothing pending', c._cbql_prev is None)
STATE['cur'] = 3
c._cbql_observe(240.0, 0.0)
check('no credit after interphase', len(UPDATES) == n + 1)

# throttle still 60 s
n_log = len(LOG)
c._cbql_observe(250.0, 0.0)
check('60 s throttle kept', len(LOG) == n_log)

print('\nlast log line:', LOG[-1])
if fails:
    sys.exit('FAIL: %s' % fails)
print('PASS')
