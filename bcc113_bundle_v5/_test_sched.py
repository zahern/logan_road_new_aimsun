"""Behaviour tests for the windowed schedule match and confidence recording."""
import io
import re
import sys
import textwrap

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print('  %s %-40s got=%r' % ('OK ' if ok else 'BAD', name, got))


# ── engine side ─────────────────────────────────────────────────────
E = 'shared_tsp_engine/engine.py'
L = io.open(E, encoding='utf-8', errors='replace').read().splitlines()
i0 = next(i for i, l in enumerate(L) if l.startswith('def _sched_match_window_s('))
i1 = next(i for i in range(i0 + 1, len(L))
          if L[i].startswith('def ') and 'def _match_departure(' not in L[i])
body = '\n'.join(L[i0:i1])
ns = {
    '_SCHED_DEPARTURES': {1: [1000.0, 1300.0, 1600.0], 2: [500.0]},
    '_SCHED_SPACING': {1: 300.0, 2: 3000.0},
    '_SCHED_MATCH_MIN_WINDOW_S': 120.0,
    '_SCHED_MATCH_MAX_WINDOW_S': 900.0,
}
exec(body, ns)
md = ns['_match_departure']
win = ns['_sched_match_window_s']

print('\n=== window ===')
check('window line h=300', round(win(1), 1), 150.0)
check('window line h=3000 clamps to max', round(win(2), 1), 900.0)
check('window unknown line -> max', round(win(99), 1), 900.0)

print('\n=== match ===')
d, t, c, m = md(1, 1010.0)
check('on time-ish mode', m, 'window')
check('on time-ish dev', round(d, 1), 10.0)
check('on time-ish confidence', round(c, 3), 0.933)

d, t, c, m = md(2, 2000.0)
check('beyond window mode', m, 'unmatched')
check('beyond window dev', round(d, 1), 1500.0)
check('beyond window confidence', c, 0.0)

d, t, c, m = md(1, 1065.0, stop_offset_s=60.0)
check('per-stop offset mode', m, 'window')
check('per-stop offset dev', round(d, 1), 5.0)
check('per-stop offset intended', round(t, 1), 1060.0)

d, t, c, m = md(1, 1065.0)
check('no offset -> late', round(d, 1), 65.0)

d, t, c, m = md(77, 1000.0)
check('line without timetable', (d, t, m), (None, None, None))

# ── stats side ──────────────────────────────────────────────────────
print('\n=== stats ===')
import os
for S in ('shared_tsp_engine/Simulation_Stats.py', 'kg/Simulation_Stats.py'):
    if not os.path.exists(S):
        continue
    txt = io.open(S, encoding='utf-8', errors='replace').read()
    lines = txt.splitlines()
    j0 = next(i for i, l in enumerate(lines) if 'def add_schedule_dev(' in l)
    j1 = next(i for i in range(j0 + 1, len(lines))
              if re.match(r'\s{4}def \w+\(', lines[i]))
    j2 = next(i for i in range(j1 + 1, len(lines))
              if re.match(r'\s{4}def \w+\(', lines[i]))
    src = textwrap.dedent('\n'.join(lines[j0:j1] + lines[j1:j2]))

    class Stub:
        SCHED_DEV_CLAMP_S = 900.0

        def __init__(self):
            pass

    ns2 = {}
    exec(src, ns2)
    Stub.add_schedule_dev = ns2['add_schedule_dev']
    Stub.schedule_kpis = ns2['schedule_kpis']
    st = Stub()
    st.add_schedule_dev(1, 10.0, bus_occ=40.0, veh_id=11,
                        headway_s=300.0, match_mode='window',
                        match_confidence=0.933, match_window_s=150.0)
    st.add_schedule_dev(1, -180.0, bus_occ=40.0, veh_id=12,
                        headway_s=300.0, match_mode='unmatched',
                        match_confidence=0.0, match_window_s=150.0)
    k = st.schedule_kpis()
    print('  [%s]' % S)
    check('  n records', k['n'], 2)
    check('  n_unmatched', k['n_unmatched'], 1)
    check('  pct_unmatched', k['pct_unmatched'], 50.0)
    check('  n_matched', k['n_matched'], 1)
    check('  mean_abs_dev_matched', k['mean_abs_dev_matched'], 10.0)
    check('  mean_match_confidence', k['mean_match_confidence'], 0.933)
    check('  penalty capped dev (300 late * 40)', round(st._sched_pen_pax, 1), 400.0 + 6000.0)
    _r = st._schedule_records[1]
    check('  record fields',
          [k for k in ('match_mode', 'match_confidence', 'match_window_s',
                       'stop_offset_s') if k in _r],
          ['match_mode', 'match_confidence', 'match_window_s', 'stop_offset_s'])
    check('  unmatched record mode', _r['match_mode'], 'unmatched')
    check('  unmatched record conf', _r['match_confidence'], 0.0)
    check('  unmatched record window', _r['match_window_s'], 150.0)
    break

print('\nfailures:', fails)
