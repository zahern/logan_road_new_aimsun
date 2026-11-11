"""_test_main_sections_deterministic.py -- the main/side split must not depend
on WHEN the detector lookup happens to succeed. Runs BOTH corridors.

WHY. ``register_intersection()`` runs at AAPIInit, before
``AKIDetGetPropertiesDetectorById`` is reliable. When the lookup failed it fell
back to "every topology incoming section is main", and
``_re_resolve_main_sections()`` skipped any non-empty main list, so that
topology set survived the whole run. Logan 21847 therefore came out as
2 main / 5 side on one run and 5 main / 2 side on another, which moved
CarVehPassages (and the objective) by 63% with no traffic difference.

This gate extracts the three methods straight out of each corridor's
Simulation_Stats.py and runs them against stubs, so the ordering is exercised
rather than assumed:

    explicit MainSections  >  detector sections resolved at AAPISimulationReady
                           >  topology (only when UpDetList is empty)

    python -I _test_main_sections_deterministic.py
"""
from __future__ import print_function

import io
import os
import sys
import textwrap
import types

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = (
    ("logan", os.path.join(HERE, "logan_road_new", "Simulation_Stats.py")),
    ("kg", os.path.join(HERE, "kg", "Simulation_Stats.py")),
)
FAIL = []


def check(name, got, want):
    ok = got == want
    print('  %-58s %s' % (name, 'ok' if ok else 'FAIL'))
    if not ok:
        print('       got  %r\n       want %r' % (got, want))
        FAIL.append(name)


def extract(path, name):
    lines = io.open(path, encoding='utf-8', errors='replace').read().splitlines()
    start = None
    for i, s in enumerate(lines):
        if s.startswith('    def %s(' % name):
            start = i
            break
    assert start is not None, 'missing %s in %s' % (name, path)
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith('    def '):
            end = j
            break
    return textwrap.dedent('\n'.join(lines[start:end]))


# Static corridor definition the fixed register_intersection consults when the
# engine hands it a config that has lost MainSections/SideSections.
_static = types.ModuleType('intersection_configs')
_static.INTERSECTIONS_CONFIG = {
    17383: {'MainSections': [10693, 60580]},          # logan
    22603: {'MainSections': [3690, 60499], 'SideSections': [3804]},
    39590: {'MainSections': [21504, 21473]},          # kg
    39606: {'MainSections': [21530, 1078795]},
}
sys.modules['intersection_configs'] = _static


class _Inf(object):
    report = 0
    length = 100.0


def _load(path, name):
    ns = {'AKIInfNetGetSectionANGInf': lambda sid: _Inf()}
    exec(compile(extract(path, name), '<%s:%s>' % (os.path.basename(path), name),
                 'exec'), ns)
    return ns[name]


class Fake(object):
    """Stubs every helper register_intersection / _re_resolve / _resolve_sides
    calls."""

    def __init__(self, pending, topo):
        self._inter = {}
        self.pending = list(pending)
        self.topo = dict(topo)
        self.msgs = []

    def _print(self, m):
        self.msgs.append(m)

    def _side_diag(self, m):
        self.msgs.append(m)

    def _fresh_inter_run_state(self):
        return {}

    def _sections_from_detectors(self, up_det_list):
        return list(self.pending)

    def _sections_from_det_ids(self, ids):
        return []

    def _auto_exit_sections(self, iid, call_sections):
        return []

    def _side_sections_from_topology(self, iid, main_sections):
        main = set(main_sections or [])
        return [s for s in self.topo.get(iid, []) if s not in main]

    def _side_sections_from_conflicting_sgs(self, iid, main_sections):
        return []

    def _write_side_sections_report(self):
        pass


CFG = {'IntersectionID': 21847,
       'UpDetList': [[86541, 86542], [86548, 86550]],
       'CarOcc': 1.2, 'BusOcc': 40.0}
DETECTED = [10792, 14721]
TOPOLOGY = [2890, 5737, 15262, 10792, 14721]

# (junction, configured main, detector answer, topology answer)
RECOVERY = (
    (17383, [10693, 60580], [10693, 60580, 15716], [10693, 15716, 60580]),
    (39590, [21504, 21473], [21504, 21473, 21476], [21476, 21504, 21473]),
)


def run_corridor(label, path):
    register = _load(path, 'register_intersection')
    re_resolve = _load(path, '_re_resolve_main_sections')
    resolve_sides = _load(path, '_resolve_side_sections')
    p = label + ': '

    print('')
    print('--- %s (%s) ---' % (label, os.path.relpath(path, HERE)))

    print('1. detectors resolvable at registration -> detector sections are main')
    f = Fake(DETECTED, {21847: TOPOLOGY})
    register(f, CFG)
    check(p + 'main_sections', f._inter[21847]['main_sections'], DETECTED)
    check(p + 'source', f._inter[21847]['main_sections_source'], 'detectors')

    print('2. detectors NOT resolvable at registration -> stays empty, then filled')
    f = Fake([], {21847: TOPOLOGY})
    register(f, CFG)
    check(p + 'main empty after register', f._inter[21847]['main_sections'], [])
    check(p + 'not promoted from topology',
          f._inter[21847]['main_sections_source'], '')
    f.pending = list(DETECTED)
    re_resolve(f)
    check(p + 'filled after re-resolve', f._inter[21847]['main_sections'], DETECTED)
    check(p + 'source now detectors', f._inter[21847]['main_sections_source'],
          'detectors')

    print('3. no UpDetList at all -> topology, and stable across re-resolve')
    cfg_nodet = dict(CFG)
    cfg_nodet.pop('UpDetList')
    f = Fake([], {21847: TOPOLOGY})
    register(f, cfg_nodet)
    check(p + 'topology used', f._inter[21847]['main_sections'], TOPOLOGY)
    check(p + 'source', f._inter[21847]['main_sections_source'], 'topology')
    re_resolve(f)
    check(p + 'stable', f._inter[21847]['main_sections'], TOPOLOGY)

    print('4. explicit config MainSections is never overwritten')
    cfg_exp = {'IntersectionID': 19185, 'MainSections': [5613, 16150, 16755],
               'UpDetList': [[86696, 86698, 86699]],
               'CarOcc': 1.2, 'BusOcc': 40.0}
    f = Fake([999], {19185: [1, 2, 3]})
    register(f, cfg_exp)
    check(p + 'explicit kept', f._inter[19185]['main_sections'], [5613, 16150, 16755])
    check(p + 'source', f._inter[19185]['main_sections_source'], 'explicit')
    f.pending = [888]
    re_resolve(f)
    check(p + 'survives re-resolve', f._inter[19185]['main_sections'],
          [5613, 16150, 16755])

    print('5. transient empty lookup must not downgrade a detector-derived main')
    f = Fake(DETECTED, {21847: TOPOLOGY})
    register(f, CFG)
    f.pending = []
    re_resolve(f)
    check(p + 'main kept', f._inter[21847]['main_sections'], DETECTED)
    check(p + 'source kept', f._inter[21847]['main_sections_source'], 'detectors')

    print('6. two runs differing only in init timing agree after finalise_init')
    a = Fake([], {21847: TOPOLOGY})
    register(a, CFG)
    a.pending = list(DETECTED)
    re_resolve(a)
    resolve_sides(a)
    b = Fake(list(DETECTED), {21847: TOPOLOGY})
    register(b, CFG)
    re_resolve(b)
    resolve_sides(b)
    check(p + 'same main', a._inter[21847]['main_sections'],
          b._inter[21847]['main_sections'])
    check(p + 'same side', a._inter[21847]['side_sections'],
          b._inter[21847]['side_sections'])
    check(p + 'main is the detector set', a._inter[21847]['main_sections'],
          DETECTED)

    print('7. rebuilt config without MainSections -> static corridor split wins')
    for jct, configured, detected, topo in RECOVERY:
        cfg = {'IntersectionID': jct,
               'UpDetList': [[1, 2], [3, 4]],
               'CarOcc': 1.2, 'BusOcc': 40.0}
        f = Fake(detected, {jct: topo})
        register(f, cfg)
        check(p + 'static main %d' % jct, f._inter[jct]['main_sections'], configured)
        check(p + 'source %d' % jct, f._inter[jct]['main_sections_source'],
              'explicit')
        re_resolve(f)
        check(p + 'survives re-resolve %d' % jct,
              f._inter[jct]['main_sections'], configured)


for label, path in FILES:
    run_corridor(label, path)

print('')
print('RESULT: %d failure(s)' % len(FAIL))
raise SystemExit(1 if FAIL else 0)
