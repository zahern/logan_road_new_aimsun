"""Reconcile MainPlusSidePassDelay_hrs against the headline TotalPassDelay_hrs.

Per junction the stats module computes
    total = delay_total + added_bus_delay
    main  = delay_main  + added_bus_delay
    side  = delay_side
so added_bus_delay cancels out of (main + side - total), leaving

    excess_j = delay_main + delay_side - delay_total

After summing, the headline is adjusted twice more, but only the headline:
    - bus delay is REPLACED by the pure red-wait definition
      sim_total_delay += new_bus - old_bus
    - the timetable penalty is added then subtracted (net zero)

The split is never adjusted, so

    gap = main+side - headline
        = sum(excess_j)  +  (sum(old_bus) - new_bus)

This script measures both terms from the run artifacts and checks the identity.
"""
import csv
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

RUNS = [
    ('NO_TSP', 'kg/results/NO_TSP_seed300_*_141527'),
    ('LIGHTSIM_MP', 'kg/results/CHAMP_*NASH_CTM2_SPILL2_LIGHTSIM_MP_seed300_*_142647'),
]


def _find(pat):
    hits = sorted(glob.glob(pat))
    if not hits:
        raise SystemExit('no run folder for %s' % pat)
    return hits[-1]


def _col(row, name):
    for k, v in row.items():
        if k and k.strip().lstrip('\ufeff') == name:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def load(run_dir):
    rows = []
    with open(os.path.join(run_dir, 'simulation_results_per_intersection.csv'),
              newline='', encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            jid = int(float(r['IntersectionID']))
            total = _col(r, 'TotalPassDelay_hrs') * 3600.0
            main = _col(r, 'MainPassDelay_hrs') * 3600.0
            side = _col(r, 'SidePassDelay_hrs') * 3600.0
            bus_paxs = (_col(r, 'AvgBusPassDelay_s')
                        * _col(r, 'BusPaxEquivPassages'))
            rows.append({'jid': jid, 'total': total, 'main': main,
                         'side': side, 'bus': bus_paxs,
                         'excess': main + side - total})
    sw = {}
    p = os.path.join(run_dir, 'signal_wait_summary.json')
    if os.path.exists(p):
        with open(p, encoding='utf-8') as fh:
            sw = json.load(fh)
    summ = {}
    p = os.path.join(run_dir, 'summary.json')
    if os.path.exists(p):
        with open(p, encoding='utf-8') as fh:
            summ = json.load(fh)
    return rows, sw, summ


def report(label, rows, sw, summ):
    print('\n' + '=' * 78)
    print('%s   (%d junctions)' % (label, len(rows)))
    print('=' * 78)
    print('%-12s %10s %10s %10s %12s %10s'
          % ('junction', 'total_h', 'main_h', 'side_h', 'main+side-tot', 'bus_paxs'))
    for r in sorted(rows, key=lambda z: -abs(z['excess'])):
        print('%-12d %10.3f %10.3f %10.3f %+12.3f %10.0f'
              % (r['jid'], r['total'] / 3600.0, r['main'] / 3600.0,
                 r['side'] / 3600.0, r['excess'] / 3600.0, r['bus']))

    sum_total = sum(r['total'] for r in rows)
    sum_main = sum(r['main'] for r in rows)
    sum_side = sum(r['side'] for r in rows)
    sum_excess = sum(r['excess'] for r in rows)
    sum_bus = sum(r['bus'] for r in rows)
    new_bus = float(sw.get('total_pax_wait_s', 0.0) or 0.0)

    print('-' * 78)
    print('  sum total (per-junction)   : %10.3f h' % (sum_total / 3600.0))
    print('  sum main                   : %10.3f h' % (sum_main / 3600.0))
    print('  sum side                   : %10.3f h' % (sum_side / 3600.0))
    print('  main+side - total          : %+10.3f h  <- term 1 (split defect)'
          % (sum_excess / 3600.0))
    print('  old bus (section)          : %10.3f h  (%d pax-s)'
          % (sum_bus / 3600.0, sum_bus))
    print('  new bus (red-wait only)    : %10.3f h  (%d pax-s)'
          % (new_bus / 3600.0, new_bus))
    print('  bus swap (old-new)         : %+10.3f h  <- term 2'
          % ((sum_bus - new_bus) / 3600.0))
    print('  predicted gap (1+2)        : %+10.3f h' % ((sum_excess + sum_bus - new_bus) / 3600.0))

    # observed gap from the exported headline and the stored split
    head = summ.get('stats_TotalPassDelay_hrs')
    ms = summ.get('stats_MainPlusSidePassDelay_hrs')
    if head is None:
        head = summ.get('TotalPassDelay_hrs')
    if ms is None:
        ms = summ.get('MainPlusSidePassDelay_hrs')
    if head is not None and ms is not None:
        head = float(head)
        ms = float(ms)
        print('  observed headline          : %10.3f h' % head)
        print('  observed main+side         : %10.3f h' % ms)
        print('  observed gap               : %+10.3f h' % (ms - head))
        resid = (ms - head) - (sum_excess + sum_bus - new_bus) / 3600.0
        print('  residual (obs-pred)        : %+10.3f h  %s'
              % (resid, 'MATCH' if abs(resid) < 0.5 else 'UNEXPLAINED'))
    else:
        print('  observed headline/split    : not found in summary.json')
        print('  summary.json keys          : %s' % sorted(summ)[:12])
    if new_bus <= 0:
        print('  NOTE: no red-wait records -> term 2 must be 0 for this arm')


for label, pat in RUNS:
    rows, sw, summ = load(_find(pat))
    report(label, rows, sw, summ)
