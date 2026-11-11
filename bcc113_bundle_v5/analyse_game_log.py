#!/usr/bin/env python
"""analyse_game_log.py -- who vetoes whom in an Aimsun CTM2 game log.

Pairs the line types the CTM2 game + bus gate emit, so the share of picks killed
by the BUS-IN-HORIZON gate is measured instead of inferred.

  [CTM2BUS] jct=<id> t=<s> btp=<bus_type_pos> bus_occ=<pax> n_sec=<n>
            seeded_cars=<n> seeded_bus=<n> reach_m=<m> chain_seed=<bool>
      Emitted inside Engine._game_ctm2_payoffs, once per solve (capped at 60 per
      junction per run), BEFORE the empty-snapshot fallback. So it also appears
      when the payoff could not be built, and the cap means coverage is partial:
      the report states the pairing coverage rather than assuming 1:1.

  [GAME_SOLVE] inter=<id> t=<s> game=<g> payoff=<p> bus=<veh> n=<c> feas=<f>
               pick=<family>_<dur>s u_bus=<pax> u_car=<pax> joint=<pax>
      Emitted for every solve that produced a CTM2 frontier, BEFORE the gates,
      so it records the pick the game wanted, gate or no gate.

  [GAME_SOLVE] inter=<id> t=<s> HOLD(bus_horizon) pick=<family>_<dur>s
               u_bus=<pax> u_car=<pax> (bus not served in horizon)
      Emitted only when GAME_BUS_IN_HORIZON is on and the pick fails
      u_bus > GAME_MIN_BUS_BENEFIT_PAXS. THIS is the veto being counted.

A pick is COMMITTED iff no HOLD(bus_horizon) exists for the same
(inter, t, family, duration), and VETOED otherwise. HOLD(congestion) is a
different, earlier gate and is counted separately -- folding it in would inflate
the gate's share.

Attribution: each veto is bucketed by the [CTM2BUS] record at the same
(inter, t):
  btp_unresolved   btp <= 0        -> bus class never resolved, u_bus is 0 for
                                      structural reasons (BUS_TYPE_POS config)
  no_bus_in_cells  btp > 0, seeded_bus == 0
                                   -> no bus inside n_cells*cell_len_m; reach_m
                                      shows how short the modelled window was
  bus_seeded       btp > 0, seeded_bus > 0
                                   -> the bus IS modelled; the pick simply does
                                      not change its discharge in the horizon
  unpaired         no [CTM2BUS] at that (inter, t) -- cap or lossy log

Usage:
  python analyse_game_log.py run.log
  python analyse_game_log.py s300.log s400.log --csv decisions.csv --json out.json
  python analyse_game_log.py run.log --sample 5      # show example vetoes

ASCII-only output (the Aimsun console is cp1252). No third-party imports.
"""
from __future__ import print_function

import argparse
import csv
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict, deque

NUM = r'[-+]?\d+(?:\.\d+)?'

RE_TS = re.compile(r'^\s*\d{1,2}:\d{2}:\d{2}\s*\|\s*')
RE_CLOCK = re.compile(r'^\s*(\d{1,2}:\d{2}:\d{2})')

RE_CTM2BUS = re.compile(
    r'\[CTM2BUS\]\s+jct=(?P<inter>\S+)\s+t=(?P<t>' + NUM + r')'
    r'\s+btp=(?P<btp>-?\d+)\s+bus_occ=(?P<bus_occ>' + NUM + r')'
    r'\s+n_sec=(?P<n_sec>\d+)\s+seeded_cars=(?P<cars>' + NUM + r')'
    r'\s+seeded_bus=(?P<buses>' + NUM + r')\s+reach_m=(?P<reach>' + NUM + r')'
    r'\s+chain_seed=(?P<chain>\w+)')

RE_HOLD_BUS = re.compile(
    r'\[GAME_SOLVE\]\s+inter=(?P<inter>\S+)\s+t=(?P<t>' + NUM + r')'
    r'\s+HOLD\(bus_horizon\)\s+pick=(?P<fam>[A-Za-z0-9_]+)_(?P<dur>' + NUM + r')s'
    r'\s+u_bus=(?P<ubus>' + NUM + r')\s+u_car=(?P<ucar>' + NUM + r')')

RE_HOLD_CONG = re.compile(
    r'\[GAME_SOLVE\]\s+inter=(?P<inter>\S+)\s+t=(?P<t>' + NUM + r')'
    r'\s+HOLD\(congestion\)\s*(?P<why>.*)$')

RE_PICK = re.compile(
    r'\[GAME_SOLVE\]\s+inter=(?P<inter>\S+)\s+t=(?P<t>' + NUM + r')'
    r'\s+game=(?P<game>\S+)\s+payoff=(?P<payoff>\S+)\s+bus=(?P<bus>\S+)'
    r'\s+n=(?P<n>\d+)\s+feas=(?P<feas>\d+)\s+pick=(?P<rest>.*)$')

RE_PAYLOAD = re.compile(
    r'(?P<fam>[A-Za-z0-9_]+)_(?P<dur>' + NUM + r')s'
    r'\s+u_bus=(?P<ubus>' + NUM + r')'
    r'\s+u_car=(?P<ucar>' + NUM + r')'
    r'\s+joint=(?P<joint>' + NUM + r')')

RE_BUILD = re.compile(r'ENGINE_BUILD\s*[=:]\s*(?P<build>[^\s,;]+)')
RE_FLAG = re.compile(r'\b(?P<name>GAME_BUS_IN_HORIZON|GAME_MIN_BUS_BENEFIT_PAXS)'
                     r'\s*[=:]\s*(?P<val>[^\s,;]+)')

BUCKETS = ('btp_unresolved', 'no_bus_in_cells', 'bus_seeded', 'unpaired')


def asc(s):
    """cp1252-safe text."""
    return ''.join(c if ord(c) < 128 else '?' for c in s)


def tkey(t):
    """Normalise a time token; both emitters use %.0f, so this makes them agree."""
    try:
        return '%.0f' % float(t)
    except (TypeError, ValueError):
        return str(t)


def parse_file(path, acc):
    """Fold one log file into acc."""
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        for raw in fh:
            try:
                line = raw.rstrip('\n').rstrip('\r')
                msg = RE_TS.sub('', line)

                if '[CTM2BUS]' in msg:
                    m = RE_CTM2BUS.search(msg)
                    if m:
                        acc['busrec'].setdefault((m.group('inter'),
                                                  tkey(m.group('t'))), []).append({
                            'btp': int(m.group('btp')),
                            'bus_occ': float(m.group('bus_occ')),
                            'n_sec': int(m.group('n_sec')),
                            'cars': float(m.group('cars')),
                            'buses': float(m.group('buses')),
                            'reach_m': float(m.group('reach')),
                            'chain': m.group('chain'),
                            'file': os.path.basename(path),
                            'line': acc['nlines'] + 1,
                        })
                        acc['n_busrec'] += 1
                    else:
                        acc['unparsed_busrec'] += 1
                    continue

                if '[GAME_SOLVE]' in msg:
                    acc['n_gamesolve'] += 1
                    m = RE_HOLD_BUS.search(msg)
                    if m:
                        acc['holds'].append({
                            'inter': m.group('inter'), 't': tkey(m.group('t')),
                            'fam': m.group('fam'), 'dur': m.group('dur'),
                            'ubus': float(m.group('ubus')),
                            'ucar': float(m.group('ucar')),
                            'file': os.path.basename(path),
                            'line': acc['nlines'] + 1,
                        })
                        acc['n_hold_bus'] += 1
                        continue
                    m = RE_HOLD_CONG.search(msg)
                    if m:
                        acc['cong'].append({
                            'inter': m.group('inter'), 't': tkey(m.group('t')),
                            'why': m.group('why').strip(),
                            'file': os.path.basename(path),
                            'line': acc['nlines'] + 1,
                        })
                        acc['n_hold_cong'] += 1
                        continue
                    m = RE_PICK.search(msg)
                    if m:
                        rest = m.group('rest').strip()
                        pm = RE_PAYLOAD.search(rest)
                        rec = {
                            'inter': m.group('inter'), 't': tkey(m.group('t')),
                            'game': m.group('game'), 'payoff': m.group('payoff'),
                            'bus': m.group('bus'), 'n': int(m.group('n')),
                            'feas': int(m.group('feas')),
                            'raw': rest,
                            'fam': None, 'dur': None,
                            'ubus': None, 'ucar': None, 'joint': None,
                            'dominant': 'dominant=1' in rest,
                            'file': os.path.basename(path),
                            'line': acc['nlines'] + 1,
                        }
                        if pm:
                            rec.update({'fam': pm.group('fam'),
                                        'dur': pm.group('dur'),
                                        'ubus': float(pm.group('ubus')),
                                        'ucar': float(pm.group('ucar')),
                                        'joint': float(pm.group('joint'))})
                        acc['picks'].append(rec)
                        acc['n_pick'] += 1
                        continue
                    acc['n_gamesolve_other'] += 1
                    continue

                if acc['build'] is None:
                    m = RE_BUILD.search(msg)
                    if m:
                        acc['build'] = m.group('build')
                for fm in RE_FLAG.finditer(msg):
                    acc['flags'][fm.group('name')] = fm.group('val')
            except Exception:
                acc['bad_lines'] += 1
            finally:
                acc['nlines'] += 1
    return acc


def new_acc():
    return {'nlines': 0, 'bad_lines': 0, 'n_gamesolve': 0, 'n_pick': 0,
            'n_hold_bus': 0, 'n_hold_cong': 0, 'n_busrec': 0,
            'n_gamesolve_other': 0, 'unparsed_busrec': 0,
            'picks': [], 'holds': [], 'cong': [], 'busrec': {},
            'build': None, 'flags': {}}


def analyse(acc, min_bus=None):
    """Match picks against bus_horizon holds and build the summary."""
    picks, holds = acc['picks'], acc['holds']

    # queue picks per (inter, t, family, duration) so duplicates pair in order
    q = defaultdict(deque)
    for i, p in enumerate(picks):
        if p['fam'] is not None:
            q[(p['inter'], p['t'], p['fam'], p['dur'])].append(i)

    vetoed = {}
    orphans = []
    for h in holds:
        k = (h['inter'], h['t'], h['fam'], h['dur'])
        dq = q.get(k)
        if dq:
            vetoed[dq.popleft()] = h
        else:
            orphans.append(h)

    for i, p in enumerate(picks):
        if p['fam'] is None:
            p['status'] = 'no_action'
        elif i in vetoed:
            p['status'] = 'vetoed'
            p['veto'] = vetoed[i]
        else:
            p['status'] = 'committed'
        recs = acc['busrec'].get((p['inter'], p['t'])) or []
        p['busrec'] = recs[0] if recs else None

    real = [p for p in picks if p['status'] != 'no_action']
    n_veto = sum(1 for p in real if p['status'] == 'vetoed')
    n_commit = len(real) - n_veto

    if min_bus is None:
        try:
            min_bus = float(acc['flags'].get('GAME_MIN_BUS_BENEFIT_PAXS', 0.0))
        except (TypeError, ValueError):
            min_bus = 0.0

    gate_flag = acc['flags'].get('GAME_BUS_IN_HORIZON')
    gate_on = (str(gate_flag).strip().lower() in ('true', '1', 'on', 'yes')
               if gate_flag is not None else None)

    # attribution of vetoes by seeding state
    buckets = Counter()
    for p in real:
        if p['status'] != 'vetoed':
            continue
        r = p['busrec']
        if r is None:
            buckets['unpaired'] += 1
        elif r['btp'] <= 0:
            buckets['btp_unresolved'] += 1
        elif r['buses'] <= 0.0:
            buckets['no_bus_in_cells'] += 1
        else:
            buckets['bus_seeded'] += 1

    # picks that should have been vetoed under the recorded threshold but were
    # not: log truncation, a different gate build, or a threshold change mid-run
    missed = [p for p in real if p['status'] == 'committed'
              and p['ubus'] is not None and p['ubus'] <= min_bus]

    per_j = defaultdict(lambda: {'solves': 0, 'no_action': 0, 'picks': 0,
                                 'veto': 0, 'commit': 0, 'cong': 0,
                                 'ubus': [], 'paired': 0})
    for p in picks:
        d = per_j[p['inter']]
        d['solves'] += 1
        if p['status'] == 'no_action':
            d['no_action'] += 1
        else:
            d['picks'] += 1
            d['veto' if p['status'] == 'vetoed' else 'commit'] += 1
            if p['ubus'] is not None:
                d['ubus'].append(p['ubus'])
            if p['busrec'] is not None:
                d['paired'] += 1
    for g in acc['cong']:
        per_j[g['inter']]['cong'] += 1

    per_junction = {}
    for inter, d in per_j.items():
        ub = sorted(d['ubus'])
        med = None
        if ub:
            m = len(ub) // 2
            med = ub[m] if len(ub) % 2 else 0.5 * (ub[m - 1] + ub[m])
        per_junction[inter] = {
            'solves': d['solves'], 'no_action': d['no_action'],
            'picks': d['picks'], 'vetoed': d['veto'], 'committed': d['commit'],
            'congestion_holds': d['cong'],
            'veto_share': (d['veto'] / float(d['picks'])) if d['picks'] else 0.0,
            'median_u_bus': med,
            'max_u_bus': (max(d['ubus']) if d['ubus'] else None),
            'ctm2bus_paired': d['paired'],
        }

    thresholds = []
    for thr in (0.0, 1.0, 20.0, 40.0, 80.0, 160.0):
        k = sum(1 for p in real if p['ubus'] is not None and p['ubus'] <= thr)
        thresholds.append({'min_bus_benefit_paxs': thr,
                           'would_veto': k,
                           'would_commit': len(real) - k,
                           'veto_share': (k / float(len(real))) if real else 0.0})

    ub_hist = Counter()
    for p in real:
        u = p['ubus'] or 0.0
        ub_hist['u_bus == 0' if u == 0 else
                ('0 < u_bus <= 40' if u <= 40 else 'u_bus > 40')] += 1

    summary = {
        'build': acc['build'],
        'gate_flag': gate_flag,
        'gate_on': gate_on,
        'min_bus_benefit_paxs': min_bus,
        'lines': acc['nlines'],
        'game_solve_lines': acc['n_gamesolve'],
        'pick_lines': len(picks),
        'no_action_solves': len(picks) - len(real),
        'real_picks': len(real),
        'vetoed': n_veto,
        'committed': n_commit,
        'veto_share': (n_veto / float(len(real))) if real else 0.0,
        'congestion_holds': acc['n_hold_cong'],
        'bus_horizon_hold_lines': acc['n_hold_bus'],
        'orphan_holds': len(orphans),
        'missed_vetoes': len(missed),
        'ctm2bus_lines': acc['n_busrec'],
        'picks_with_ctm2bus': sum(1 for p in real if p['busrec'] is not None),
        'pairing_coverage': (sum(1 for p in real if p['busrec'] is not None)
                             / float(len(real))) if real else 0.0,
        'buckets': {b: buckets.get(b, 0) for b in BUCKETS},
        'u_bus_histogram': {k: ub_hist[k] for k in
                            ('u_bus == 0', '0 < u_bus <= 40', 'u_bus > 40')
                            if ub_hist.get(k)},
        'thresholds': thresholds,
        'junction_ids': sorted(per_junction),
        'per_junction': per_junction,
    }
    return summary, real, orphans, missed, per_junction


def report(paths, summary, real, orphans, missed, per_junction, sample=3,
           out=None):
    w = out or sys.stdout
    def wl(s=''):
        w.write(asc(s) + '\n')

    wl('=' * 74)
    wl('BUS-IN-HORIZON GATE: %s' % ', '.join(os.path.basename(p) for p in paths))
    wl('=' * 74)
    wl('build            : %s' % (summary['build'] or 'not in log'))
    gate = summary['gate_flag']
    wl('gate             : GAME_BUS_IN_HORIZON=%s  GAME_MIN_BUS_BENEFIT_PAXS=%s'
       % (gate if gate is not None else '? (not in log)',
          summary['min_bus_benefit_paxs']))
    wl('lines            : %d  ([GAME_SOLVE] %d, [CTM2BUS] %d)'
       % (summary['lines'], summary['game_solve_lines'],
          summary['ctm2bus_lines']))
    wl('pick lines       : %d  = %d NO_ACTION + %d real picks'
       % (summary['pick_lines'], summary['no_action_solves'],
          summary['real_picks']))
    wl('')

    if summary['real_picks']:
        wl('-- BUS GATE ------------------------------------------------------')
        wl('  vetoed        : %d of %d picks  (%.1f%%)'
           % (summary['vetoed'], summary['real_picks'],
              100.0 * summary['veto_share']))
        wl('  committed     : %d  (%.1f%%)'
           % (summary['committed'], 100.0 * (1.0 - summary['veto_share'])))
        if summary['gate_on'] is False:
            wl('  NOTE gate flag reads OFF, yet %d veto lines exist: check the'
               % summary['bus_horizon_hold_lines'])
            wl('       flag actually used by the run (config dump vs override).')
        wl('  HOLD(congestion) is separate and is NOT counted above: %d'
           % summary['congestion_holds'])
        if summary['orphan_holds']:
            wl('  orphan holds  : %d (HOLD(bus_horizon) with no matching pick)'
               % summary['orphan_holds'])
        if summary['missed_vetoes']:
            wl('  missed vetoes : %d picks with u_bus <= threshold that were NOT'
               % summary['missed_vetoes'])
            wl('                  held -> log truncated, or the gate was off for')
            wl('                  those solves; investigate before trusting the')
            wl('                  committed count.')
        wl('')

        wl('-- WHY -----------------------------------------------------------')
        wl('  picks with a [CTM2BUS] record: %d/%d (%.0f%% coverage%s)'
           % (summary['picks_with_ctm2bus'], summary['real_picks'],
              100.0 * summary['pairing_coverage'],
              '; cap is 60 per junction' if summary['pairing_coverage'] < 1.0
              else ''))
        b = summary['buckets']
        for k in BUCKETS:
            if b[k]:
                wl('  %-16s %d' % (k, b[k]))
        if b['btp_unresolved']:
            wl('  -> btp_unresolved: BUS_TYPE_POS never resolved; u_bus is 0 for')
            wl('     every junction and no gate threshold can help. Fix the class')
            wl('     mapping first.')
        if b['no_bus_in_cells']:
            wl('  -> no_bus_in_cells: buses exist on the approach but none inside')
            wl('     n_cells*cell_len_m. Enable CHAIN_SEED (200 m reach) or widen')
            wl('     GAME_CTM2_LIGHTSIM_MAX_CELLS.')
        if b['bus_seeded']:
            wl('  -> bus_seeded: the bus IS modelled, the action just does not move')
            wl('     its discharge within the horizon (green already sufficient,')
            wl('     bus past the stop line, or saturated cell).')
        if b['unpaired']:
            wl('  -> unpaired: no [CTM2BUS] at that (inter, t) -- rerun with')
            wl('     CTM2BUS_LOG=1, or raise the cap in _game_ctm2_payoffs.')
        wl('')

        wl('-- u_bus OF REAL PICKS -------------------------------------------')
        for k, v in summary['u_bus_histogram'].items():
            wl('  %-16s %d' % (k, v))
        wl('  threshold sensitivity (the pick is fixed; only the veto moves):')
        wl('  %10s %10s %10s' % ('min_benefit', 'vetoed', 'share'))
        for row in summary['thresholds']:
            wl('  %10.0f %10d %9.1f%%' % (row['min_bus_benefit_paxs'],
                                         row['would_veto'],
                                         100.0 * row['veto_share']))
        wl('')

    if per_junction:
        wl('-- BY JUNCTION ---------------------------------------------------')
        wl('  %-12s %6s %6s %6s %6s %7s %9s' % ('junction', 'solves', 'picks',
                                              'veto', 'commit', 'share',
                                              'med_u_bus'))
        order = sorted(per_junction.items(),
                       key=lambda kv: (-kv[1]['veto_share'], kv[0]))
        for inter, d in order:
            wl('  %-12s %6d %6d %6d %6d %6.1f%% %9s'
               % (inter, d['solves'], d['picks'], d['vetoed'], d['committed'],
                  100.0 * d['veto_share'],
                  '-' if d['median_u_bus'] is None else '%.0f' % d['median_u_bus']))
        all_in = [kv[0] for kv in order if kv[1]['veto_share'] >= 1.0]
        none_in = [kv[0] for kv in order if kv[1]['picks'] and not kv[1]['vetoed']]
        if all_in:
            wl('  fully vetoed : %s' % ', '.join(all_in))
        if none_in:
            wl('  never vetoed : %s' % ', '.join(none_in))
        wl('')

    if sample:
        vs = [p for p in real if p['status'] == 'vetoed'][:sample]
        if vs:
            wl('-- SAMPLE VETOES -------------------------------------------------')
            for p in vs:
                r = p['busrec']
                wl('  %s t=%s  wanted %s_%ss  u_bus=%.0f u_car=%.0f  bus=%s'
                   % (p['inter'], p['t'], p['fam'], p['dur'], p['ubus'],
                      p['ucar'], p['bus']))
                if r is None:
                    wl('        ctm2bus: (none)')
                else:
                    wl('        ctm2bus: btp=%d seeded_bus=%.0f/%.0fveh '
                       'n_sec=%d reach_m=%.0f chain_seed=%s'
                       % (r['btp'], r['buses'], r['cars'], r['n_sec'],
                          r['reach_m'], r['chain']))
            wl('')

    wl('READ THIS AS: a veto is the gate refusing a pick the game already made.')
    wl('It is not evidence the pick was bad -- only that the CTM could not show')
    wl('a bus benefit for it (see the buckets). Pairing is by (junction, %.0f s')
    wl('tick, family, duration), so a busy junction with two solves at one tick')
    wl('pairs in log order.')


def main(argv):
    ap = argparse.ArgumentParser(
        description='Pair [CTM2BUS] and [GAME_SOLVE] lines and report how often '
                    'the bus-in-horizon gate vetoes a game pick.')
    ap.add_argument('logs', nargs='*', help='Aimsun log file(s)')
    ap.add_argument('--csv', help='write one row per real pick')
    ap.add_argument('--json', help='write the summary as JSON')
    ap.add_argument('--sample', type=int, default=3,
                    help='example vetoes to show (0 = none)')
    ap.add_argument('--min-bus', type=float, default=None,
                    help='override GAME_MIN_BUS_BENEFIT_PAXS for the '
                         'missed-veto check')
    ap.add_argument('--quiet', action='store_true', help='no human report')
    a = ap.parse_args(argv)

    paths = list(a.logs)
    if not paths:
        pats = ('*.log', 'Aimsun_TSP_Log_*.txt',
                os.path.join('kg', 'Aimsun_TSP_Log_*.txt'))
        cands = sorted({p for pat in pats for p in glob.glob(pat)},
                       key=os.path.getmtime, reverse=True)
        if not cands:
            print('no log file given and no *.log in %s' % os.getcwd())
            return 2
        paths = cands[:1]
        print('(no path given; using newest: %s)' % os.path.basename(paths[0]))
    missing = [p for p in paths if not os.path.isfile(p)]
    if missing:
        print('missing: %s' % ', '.join(missing))
        return 2

    acc = new_acc()
    for p in paths:
        parse_file(p, acc)

    summary, real, orphans, missed, per_junction = analyse(acc, a.min_bus)

    if not a.quiet:
        report(paths, summary, real, orphans, missed, per_junction, a.sample)

    if a.csv:
        cols = ['inter', 't', 'fam', 'dur', 'ubus', 'ucar', 'joint', 'status',
                'btp', 'seeded_bus', 'seeded_cars', 'n_sec', 'reach_m',
                'chain_seed', 'bucket', 'game', 'payoff', 'bus']
        with open(a.csv, 'w', newline='', encoding='utf-8') as fh:
            wr = csv.writer(fh)
            wr.writerow(cols)
            for p in real:
                r = p['busrec']
                if p['status'] != 'vetoed':
                    bucket = '-'          # describes a veto, so not applicable
                elif r is None:
                    bucket = 'unpaired'
                elif r['btp'] <= 0:
                    bucket = 'btp_unresolved'
                elif r['buses'] <= 0.0:
                    bucket = 'no_bus_in_cells'
                else:
                    bucket = 'bus_seeded'
                wr.writerow([p['inter'], p['t'], p['fam'], p['dur'], p['ubus'],
                             p['ucar'], p['joint'], p['status'],
                             r['btp'] if r else '', r['buses'] if r else '',
                             r['cars'] if r else '', r['n_sec'] if r else '',
                             '%.1f' % r['reach_m'] if r else '',
                             r['chain'] if r else '', bucket, p['game'],
                             p['payoff'], p['bus']])
        if not a.quiet:
            print('\nCSV: %s (%d rows)' % (a.csv, len(real)))

    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(summary, fh, indent=2, sort_keys=True)
        if not a.quiet:
            print('JSON: %s' % a.json)

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
