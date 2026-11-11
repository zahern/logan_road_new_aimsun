"""Offline self-test for _probe_split_signals.py.

Aimsun cannot be launched here, so this stubs the five ECI getters with values
matching the SUMO export (4-phase 41/4/41/4 partner, 3-phase 81/4/5 partner) and
checks that the probe renders the three verdicts correctly:

  case A  4x 41/4/41/4 vs 3x 81/4/5     -> DIFFERENT, two distinct programs
  case B  all four identical            -> SAME plan structure
  case C  durations unreadable          -> INCONCLUSIVE, not "different"
  case D  clocks advance between calls  -> movement and new offset reported

Also checks that a failing getter prints ERR instead of raising.
"""
import io
import os
import runpy
import sys
import tempfile
import types

PROBE = '_probe_split_signals.py'
STATE = os.path.join(tempfile.gettempdir(), 'split_signal_probe_state.json')


def clear_state():
    try:
        os.remove(STATE)
    except OSError:
        pass

PATTERNS = {
    10158157: [41.0, 4.0, 41.0, 4.0],
    10158160: [81.0, 4.0, 5.0],
    11118206: [41.0, 4.0, 41.0, 4.0],
    11127644: [81.0, 4.0, 5.0],
}
CLOCK = {10158157: 100.0, 10158160: 55.0, 11118206: 100.0, 11127644: 55.0}


def build_stub(pats, raise_dur=False, clock=None):
    m = types.ModuleType('fakeang')
    m.ENGINE_BUILD = 'SELFTEST'

    class doublep(object):
        def __init__(self):
            self._v = 0.0

        def value(self):
            return self._v

    m.doublep = doublep
    m.ECIGetControlType = lambda jid: 2

    def n_phases(jid):
        if jid not in pats:
            raise KeyError(jid)
        return len(pats[jid])

    m.ECIGetNumberPhases = n_phases

    def durations(jid, ph, t, normal, dmax, dmin):
        if raise_dur:
            raise RuntimeError('duration read blocked')
        d = pats[jid][ph]
        normal._v, dmax._v, dmin._v = d, d, d

    m.ECIGetDurationsPhase = durations
    m.ECIGetCurrentPhase = lambda jid: 1
    m.ECIGetStartingTimePhase = lambda jid: (clock or CLOCK)[jid]
    m.ECIGetNbSignalGroupsPhaseofJunction = lambda jid, ph, t: 2
    return m


def run(stub, label):
    sys.modules['fakeang'] = stub
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        g = runpy.run_path(PROBE, run_name='__probe_selftest__')
        g['main']()
    finally:
        sys.stdout = old
    out = buf.getvalue()
    print('=' * 70)
    print('CASE', label)
    print(out)
    return out


fails = []

# A: the real SUMO export - 4-phase partner vs 3-phase partner. The pair differs,
#    so the probe must say so even though both cycles are 90 s.
clear_state()
out_a = run(build_stub(PATTERNS), 'A: SUMO pattern, 4-phase vs 3-phase')
if 'two distinct programs' not in out_a:
    fails.append('case A did not report DIFFERENT')
if 'cycle (sum of normals) : 90.0 s' not in out_a:
    fails.append('case A cycle not 90.0 s')

# B: all four nodes on the same 4-phase pattern -> same plan structure.
mixed = dict(PATTERNS)
mixed[10158160] = [41.0, 4.0, 41.0, 4.0]
mixed[11127644] = [41.0, 4.0, 41.0, 4.0]
clear_state()
out_b = run(build_stub(mixed), 'B: all four on the same 4-phase pattern')
if 'SAME phase count and durations' not in out_b:
    fails.append('case B did not report SAME')

# C: a blocked duration read must degrade honestly, never claim distinct.
clear_state()
out_c = run(build_stub(PATTERNS, raise_dur=True), 'C: duration read fails')
if 'INCONCLUSIVE' not in out_c:
    fails.append('case C did not degrade to INCONCLUSIVE')
if 'two distinct programs' in out_c:
    fails.append('case C wrongly claimed two distinct programs')
if 'ERR:RuntimeError' not in out_c:
    fails.append('case C did not surface the error text')

# D: two invocations 8 s apart must report movement and the new offset (53 s).
clear_state()
run(build_stub(PATTERNS), 'D1: prime the clock memory')
CLOCK[10158157] += 8.0
out_d = run(build_stub(PATTERNS), 'D2: 10158157 advanced 8 s')
if 'clock moved 8.0 s' not in out_d:
    fails.append('clock movement not reported across invocations')
if 'relative phase-clock offset (a-b): 53.0 s' not in out_d:
    fails.append('relative offset not 53.0 s after the advance')
clear_state()

print('=' * 70)
if fails:
    print('SELFTEST FAILED')
    for f in fails:
        print('  -', f)
    sys.exit(1)
print('SELFTEST PASS (4 cases, 8 assertions)')
