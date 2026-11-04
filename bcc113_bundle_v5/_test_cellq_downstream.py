"""Exercise the new [CELLQ_HELD] downstream attribution against stubs.

Extracts the real function bodies out of specialized_modes.py with ast (so this
tests the patched source, not a copy) and drives them with a fake controller.
"""
import ast
import io
import sys

SRC = 'shared_tsp_engine/specialized_modes.py'
WANT = ('_cellq_held_ok', '_cellq_held_log', '_cellq_admit_log',
        '_cellq_downstream_held')

tree = ast.parse(io.open(SRC, encoding='utf-8').read())
found = {}
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in WANT:
        found[node.name] = ast.get_source_segment(
            io.open(SRC, encoding='utf-8').read(), node)

missing = [w for w in WANT if w not in found]
if missing:
    sys.exit('ABORT: not at module level / not found: %s' % missing)

lines = []
LOG = []


class _Stats:
    def record_tsp_skip(self, *a):
        pass


class Ctl(object):
    """Minimal controller: id, stats, and whatever the helpers setattr on it."""
    id = 19185
    stats = _Stats()


ns = {'__name__': 'cellq_test'}
exec('\n\n'.join(found.values()), ns)


def log_func(self, msg, force=False):
    LOG.append((self.id, msg))


ns['_log_func'] = log_func
ns['CELLQ_HELD_LOG_MAX'] = 3
ns['CELLQ_ADMIT_LOG_MAX'] = 100

admit = ns['_cellq_admit_log']
down = ns['_cellq_downstream_held']
held_log = ns['_cellq_held_log']

fails = []


def check(name, cond, detail=''):
    if cond:
        print('  PASS  %s' % name)
    else:
        print('  FAIL  %s  %s' % (name, detail))
        fails.append(name)


def held_lines():
    return [m for (_i, m) in LOG if m.startswith('[CELLQ_HELD]')]


print('1. admit then a downstream cost veto -> one attributable CELLQ_HELD')
c = Ctl()
admit(c, 1830.0, 41203, 'GE', 5.0, 11.4, 0.412, 0.930)
check('admit stashed the handshake', getattr(c, '_cellq_pending', None) is not None)
LOG.clear()
down(c, 1830.0, 41203, 'cost_veto(cost=1234>benefit=1000*ratio=1.50)',
     ('GE', 5.0))
hs = held_lines()
check('one line emitted', len(hs) == 1, hs)
if hs:
    m = hs[0]
    print('        ' + m)
    check('names the cost veto', 'veto=cost_veto(' in m, m)
    check('carries both sides of the comparison',
          'cost=1234>benefit=1000*ratio=1.50' in m, m)
    check('keeps the discarded action', 'proposed=GE_5s' in m, m)
    check('reuses the admit-time state',
          'eff_delay=11.4s' in m and 'side_ratio=0.412' in m
          and 'local_sat=0.930' in m, m)
    check('line shape matches the pre-gate form',
          m.count('inter=') == 1 and ' local_sat=' in m, m)
check('marker consumed', getattr(c, '_cellq_pending', None) is None)

print('2. a veto with no CellQ admit is NOT attributed')
c2 = Ctl()          # e.g. a NASH or MP_ECTM action
LOG.clear()
down(c2, 1830.0, 1, 'cost_veto(cost=9>benefit=1*ratio=1.00)', ('INS', 5.0))
check('no line for another decider', held_lines() == [], held_lines())

print('3. a second veto without a fresh admit logs nothing')
LOG.clear()
down(c, 1835.0, 41203, 'net_pax(cost=50>benefit=10*ratio=1.00)', ('GE', 5.0))
check('marker does not linger', held_lines() == [], held_lines())

print('4. the post budget is independent of the pre budget')
c3 = Ctl()
for _ in range(ns['CELLQ_HELD_LOG_MAX']):
    held_log(c3, 100.0, 1, 'min_gain(1.0<15.0)', ('GE', 5.0), 1.0, 0.1, 0.1)
LOG.clear()
admit(c3, 200.0, 7, 'INS', 5.0, 20.0, 0.2, 0.5)
down(c3, 200.0, 7, 'net_pax(cost=99>benefit=1*ratio=1.00)', ('INS', 5.0))
check('pre holds exhausted first', len(LOG) == 2)   # [CELLQ_ADMIT] + held
check('downstream still logs', len(held_lines()) == 1, held_lines())

print('5. CELLQ_HELD_LOG_MAX=0 disables downstream logging too')
ns['CELLQ_HELD_LOG_MAX'] = 0
c4 = Ctl()
admit(c4, 1.0, 1, 'GE', 5.0, 20.0, 0.1, 0.1)
LOG.clear()
down(c4, 1.0, 1, 'cost_veto(cost=9>benefit=1*ratio=1.00)', ('GE', 5.0))
check('disabled', held_lines() == [], held_lines())

print('')
if fails:
    sys.exit('FAILED: %s' % fails)
print('ALL CHECKS PASSED')
