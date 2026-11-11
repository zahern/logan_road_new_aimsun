"""Behaviour tests for the SUMO windowed schedule match."""
import io
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print('  %s %-40s got=%r' % ('OK ' if ok else 'BAD', name, got))


FILES = [r"Z:\tsp\sumo_hpc\shared_tsp_engine\engine.py",
         r"_sumo_port\shared_tsp_engine\engine.py"]

for F in FILES:
    L = io.open(F, encoding='utf-8', errors='replace').read().splitlines()
    i0 = next(i for i, l in enumerate(L) if l.startswith('def _sched_match_window_s('))
    i1 = next(i for i in range(i0 + 1, len(L))
              if L[i].startswith('def ') and not L[i].startswith('def _match_departure_dev('))
    body = '\n'.join(L[i0:i1])
    ns = {
        '_SCHED_DEPARTURES': {1: [1000.0, 1300.0, 1600.0], 2: [500.0]},
        '_SCHED_SPACING': {1: 300.0, 2: 3000.0},
        '_SCHED_MATCH_MIN_WINDOW_S': 120.0,
        '_SCHED_MATCH_MAX_WINDOW_S': 900.0,
    }
    exec(body, ns)
    md = ns['_match_departure_dev']
    win = ns['_sched_match_window_s']
    print('\n=== %s ===' % F)
    check('window h=300', round(win(1), 1), 150.0)
    check('window h=3000 -> max', round(win(2), 1), 900.0)
    d, t, c, m = md(1, 1010.0)
    check('on time mode/dev/conf', (m, round(d, 1), round(c, 3)),
          ('window', 10.0, 0.933))
    d, t, c, m = md(2, 2000.0)
    check('beyond window mode/dev/conf', (m, round(d, 1), c),
          ('unmatched', 1500.0, 0.0))
    d, t, c, m = md(1, 1065.0, stop_offset_s=60.0)
    check('per-stop offset mode/dev', (m, round(d, 1), round(t, 1)),
          ('window', 5.0, 1060.0))
    check('no timetable', md(77, 1000.0), (None, None, 0.0, None))

print('\nfailures:', fails)
