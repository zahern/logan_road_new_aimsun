"""Verify:  main+side - headline  ==  (sum per-junction bus term - exported bus)/3600.

Per junction the stats module adds `added_bus_delay` to BOTH total and main, so it
cancels inside (main + side - total) -- which is why that difference is exactly 0.
The bus term only leaves the headline, through the global red-wait replacement,
and never reaches main/side. So the whole gap should equal the difference between
the per-junction bus term and the bus delay the headline actually kept.
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


def num(row, name):
    for k, v in row.items():
        if k and k.strip().lstrip('\ufeff') == name:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


ok = True
for label, pat in RUNS:
    d = sorted(glob.glob(pat))[-1]
    rows = list(csv.DictReader(open(os.path.join(
        d, 'simulation_results_per_intersection.csv'), encoding='utf-8-sig')))
    run = next(csv.DictReader(open(os.path.join(d, 'simulation_results.csv'),
                                   encoding='utf-8-sig')))
    sw = json.load(open(os.path.join(d, 'signal_wait_summary.json')))

    tot = sum(num(r, 'TotalPassDelay_hrs') for r in rows) * 3600.0
    main = sum(num(r, 'MainPassDelay_hrs') for r in rows) * 3600.0
    side = sum(num(r, 'SidePassDelay_hrs') for r in rows) * 3600.0
    bus_term = sum(num(r, 'AvgBusPassDelay_s') * num(r, 'BusPaxEquivPassages')
                   for r in rows)
    head = num(run, 'TotalPassDelay_hrs') * 3600.0
    ms = num(run, 'MainPlusSidePassDelay_hrs') * 3600.0
    bus_kept = num(run, 'SimBusDelay_pax_s')

    gap = ms - head
    predicted = bus_term - bus_kept
    resid = gap - predicted

    print('=' * 72)
    print(label)
    print('  sum per-junction total      %12.1f pax-s' % tot)
    print('  sum main + side             %12.1f pax-s' % (main + side))
    print('  main+side - sum(total)      %+12.2f pax-s   (split self-consistency)'
          % (main + side - tot))
    print('  headline                    %12.1f pax-s' % head)
    print('  main+side (exported)        %12.1f pax-s' % ms)
    print('  gap (main+side - headline)  %+12.1f pax-s  = %+.3f h'
          % (gap, gap / 3600.0))
    print('  per-junction bus term       %12.1f pax-s' % bus_term)
    print('  bus delay kept in headline  %12.1f pax-s  (SimBusDelay_pax_s)' % bus_kept)
    print('  predicted gap               %+12.1f pax-s  = %+.3f h'
          % (predicted, predicted / 3600.0))
    print('  residual                    %+12.2f pax-s  = %+.4f h  %s'
          % (resid, resid / 3600.0,
             'MATCH' if abs(resid) < 3600 * 0.05 else 'UNEXPLAINED'))
    print('  red-wait total (json)       %12.1f pax-s  (%.1f s of hold)'
          % (sw.get('total_pax_wait_s', 0), sw.get('total_wait_s', 0)))
    if abs(resid) >= 3600 * 0.05:
        ok = False

    print('  per-junction bus term, top 6:')
    ranked = sorted(rows, key=lambda r: -(num(r, 'AvgBusPassDelay_s')
                                          * num(r, 'BusPaxEquivPassages')))
    for r in ranked[:6]:
        b = num(r, 'AvgBusPassDelay_s') * num(r, 'BusPaxEquivPassages')
        print('     %-10s %8.0f pax-s  (%.1f%% of the gap)'
              % (r['IntersectionID'], b, 100.0 * b / predicted if predicted else 0.0))

print('=' * 72)
print('IDENTITY HOLDS ON BOTH ARMS' if ok else 'IDENTITY FAILED')
sys.exit(0 if ok else 1)
