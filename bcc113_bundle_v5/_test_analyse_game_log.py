"""Self-test for analyse_game_log.py on a fixture with hand-computed answers.

The fixture exercises every attribution bucket and every counting decision the
analyser makes, so a regression shows up as an exact count mismatch rather than
a plausible-looking report.

IMPORTANT: the real emitter prints one [CTM2BUS] line per solve (capped at 60
per junction), so the fixture emits one at every solve tick. Emitting only one
per junction would make pairing look broken when the analyser is correct.

Layout (junction: seeding -> what the gate should do):
  A  btp=40, seeded_bus=0   4 picks u_bus=0 -> 4 vetoes, no_bus_in_cells
                            1 orphan HOLD(bus_horizon) with no pick
  B  btp=-1                 2 picks u_bus=0 -> 2 vetoes, btp_unresolved
  C  btp=40, seeded_bus=3   3 picks u_bus=120/200/80 -> committed
                            1 pick  u_bus=0          -> veto, bus_seeded
                            1 pick  NO_ACTION        -> not a gate decision
  D  no [CTM2BUS]           1 pick  u_bus=0, NO hold -> committed = missed veto
                            1 HOLD(congestion)       -> separate gate
  E  no [CTM2BUS]           1 pick  u_bus=0 + hold   -> veto, unpaired
"""
from __future__ import print_function

import csv
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYSER = os.path.join(HERE, 'analyse_game_log.py')

FAIL = []


def check(name, got, want):
    ok = got == want
    print('  %-34s %s (got %r, want %r)'
          % (name, 'ok' if ok else 'FAIL', got, want))
    if not ok:
        FAIL.append(name)


def bus(inter, t, btp, cars, buses, n_sec, reach, chain):
    return ('10:00:00 | [CTM2BUS] jct=%s t=%d btp=%d bus_occ=40 n_sec=%d '
            'seeded_cars=%.0f seeded_bus=%.0f reach_m=%.1f chain_seed=%s'
            % (inter, t, btp, n_sec, cars, buses, reach, chain))


def pick(inter, t, fam, dur, ubus, ucar, joint, bus_id='None'):
    return ('10:00:01 | [GAME_SOLVE] inter=%s t=%d game=nash payoff=ctm2 '
            'bus=%s n=7 feas=6 pick=%s_%ss u_bus=%.0f u_car=%.0f joint=%.0f'
            % (inter, t, bus_id, fam, dur, ubus, ucar, joint))


def noaction(inter, t):
    return ('10:00:01 | [GAME_SOLVE] inter=%s t=%d game=nash payoff=ctm2 '
            'bus=None n=5 feas=0 pick=NO_ACTION (no feasible candidate)'
            % (inter, t))


def hold_bus(inter, t, fam, dur, ubus, ucar):
    return ('10:00:02 | [GAME_SOLVE] inter=%s t=%d HOLD(bus_horizon) '
            'pick=%s_%ss u_bus=%.0f u_car=%.0f (bus not served in horizon)'
            % (inter, t, fam, dur, ubus, ucar))


def hold_cong(inter, t):
    return ('10:00:02 | [GAME_SOLVE] inter=%s t=%d HOLD(congestion) '
            'oversaturated jam=0.91>=0.90' % (inter, t))


def build():
    L = ['10:00:00 | [LOAD] ENGINE_BUILD=2026-11-09T1500-lightsim-ctm-busdiag',
         '10:00:00 | [DUMP] GAME_BUS_IN_HORIZON: True',
         '10:00:00 | [DUMP] GAME_MIN_BUS_BENEFIT_PAXS: 0.0']

    # A: buses exist on the approach but none inside the modelled cells
    for t, fam, dur, ub, uc, jo in [(600, 'GE', 15, 0, 40, 40),
                                    (660, 'GR', 10, 0, 30, 30),
                                    (720, 'ER', 5, 0, 25, 25),
                                    (780, 'INS', 8, 0, 20, 20)]:
        L.append(bus('A', t, 40, 18, 0, 2, 15.0, False))
        L.append(pick('A', t, fam, dur, ub, uc, jo))
        L.append(hold_bus('A', t, fam, dur, ub, uc))
    L.append(hold_bus('A', 999, 'GE', 15, 0, 10))          # orphan: no pick

    # B: BUS_TYPE_POS never resolved
    for t, fam, dur in [(600, 'GE', 15), (660, 'GR', 10)]:
        L.append(bus('B', t, -1, 12, 0, 2, 15.0, False))
        L.append(pick('B', t, fam, dur, 0, 35, 35))
        L.append(hold_bus('B', t, fam, dur, 0, 35))

    # C: bus seeded and in reach -> picks that help it are committed
    for t, fam, dur, ub, uc, jo, bid in [(600, 'GE', 20, 120, 60, 180, '1041'),
                                         (660, 'GE', 25, 200, 60, 260, '1041'),
                                         (720, 'GR', 15, 80, 50, 130, '1088'),
                                         (780, 'ER', 5, 0, 45, 45, '1088')]:
        L.append(bus('C', t, 40, 31, 3, 6, 200.0, True))
        L.append(pick('C', t, fam, dur, ub, uc, jo, bus_id=bid))
        if ub == 0:
            L.append(hold_bus('C', t, fam, dur, ub, uc))
    L.append(noaction('C', 840))

    # D: no seeding record; gate did not hold -> missed veto; congestion gate
    L.append(hold_cong('D', 500))
    L.append(pick('D', 900, 'GE', 15, 0, 15, 15))

    # E: veto with no seeding record at all -> unpaired
    L.append(pick('E', 900, 'GE', 15, 0, 20, 20))
    L.append(hold_bus('E', 900, 'GE', 15, 0, 20))
    return L


LINES = build()


def main():
    tmp = tempfile.mkdtemp(prefix='gamelog_')
    log = os.path.join(tmp, 'Aimsun_TSP_Log_test.txt')
    with open(log, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(LINES) + '\n')
    js = os.path.join(tmp, 'out.json')
    cv = os.path.join(tmp, 'out.csv')

    r = subprocess.run([sys.executable, ANALYSER, log, '--json', js, '--csv', cv,
                        '--sample', '2'], capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0:
        print(r.stderr)
        print('FAIL: analyser exited %d' % r.returncode)
        return 1
    r.stdout.encode('cp1252')          # the human report must be cp1252-safe

    with open(js, encoding='utf-8') as fh:
        s = json.load(fh)

    print('counts')
    check('build', s['build'], '2026-11-09T1500-lightsim-ctm-busdiag')
    check('gate_on', s['gate_on'], True)
    check('pick_lines', s['pick_lines'], 13)
    check('no_action_solves', s['no_action_solves'], 1)
    check('real_picks', s['real_picks'], 12)
    check('vetoed', s['vetoed'], 8)
    check('committed', s['committed'], 4)
    check('veto_share', round(s['veto_share'], 4), round(8 / 12.0, 4))
    check('congestion_holds', s['congestion_holds'], 1)
    check('bus_horizon_hold_lines', s['bus_horizon_hold_lines'], 9)
    check('orphan_holds', s['orphan_holds'], 1)
    check('missed_vetoes', s['missed_vetoes'], 1)
    check('ctm2bus_lines', s['ctm2bus_lines'], 10)
    check('picks_with_ctm2bus', s['picks_with_ctm2bus'], 10)
    check('pairing_coverage', round(s['pairing_coverage'], 4), round(10 / 12.0, 4))

    print('attribution')
    b = s['buckets']
    check('btp_unresolved', b['btp_unresolved'], 2)
    check('no_bus_in_cells', b['no_bus_in_cells'], 4)
    check('bus_seeded', b['bus_seeded'], 1)
    check('unpaired', b['unpaired'], 1)
    check('buckets sum to vetoes', sum(b.values()), s['vetoed'])

    print('thresholds (pick fixed, veto moves)')
    thr = {int(row['min_bus_benefit_paxs']): row for row in s['thresholds']}
    check('at 0', thr[0]['would_veto'], 9)
    check('at 40', thr[40]['would_veto'], 9)      # no pick lands in (0, 40]
    check('at 80', thr[80]['would_veto'], 10)     # + the 80 pax pick
    check('at 160', thr[160]['would_veto'], 11)   # + the 120 pax pick
    check('at 160 commit', thr[160]['would_commit'], 1)

    print('u_bus histogram')
    check('u_bus == 0', s['u_bus_histogram'].get('u_bus == 0'), 9)
    check('u_bus > 40', s['u_bus_histogram'].get('u_bus > 40'), 3)

    print('per junction')
    pj = s['per_junction']
    check('A vetoes', pj['A']['vetoed'], 4)
    check('A share', pj['A']['veto_share'], 1.0)
    check('B vetoes', pj['B']['vetoed'], 2)
    check('C picks', pj['C']['picks'], 4)
    check('C vetoes', pj['C']['vetoed'], 1)
    check('C no_action', pj['C']['no_action'], 1)
    check('C median u_bus', pj['C']['median_u_bus'], 100.0)
    check('D committed', pj['D']['committed'], 1)
    check('D congestion', pj['D']['congestion_holds'], 1)
    check('E vetoes', pj['E']['vetoed'], 1)

    with open(cv, newline='', encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    check('csv rows', len(rows), 12)
    check('csv veto rows', sum(1 for x in rows if x['status'] == 'vetoed'), 8)
    check('csv veto buckets',
          sorted({x['bucket'] for x in rows if x['status'] == 'vetoed'}),
          ['btp_unresolved', 'bus_seeded', 'no_bus_in_cells', 'unpaired'])
    check('csv committed bucket',
          sorted({x['bucket'] for x in rows if x['status'] == 'committed'}), ['-'])

    print('')
    if FAIL:
        print('RESULT: %d failure(s): %s' % (len(FAIL), ', '.join(FAIL)))
        return 1
    print('RESULT: 0 failure(s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
