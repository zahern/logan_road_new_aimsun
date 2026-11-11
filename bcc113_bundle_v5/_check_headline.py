"""Read each run's own global_kpis and reconcile against the pair CSV."""
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
KEYS = ['TotalPassDelay_hrs', 'MainPlusSidePassDelay_hrs', 'MainPassDelay_hrs',
        'SidePassDelay_hrs', 'CorridorPassDelay_hrs', 'NetPassDelay_hrs',
        'DelayScope', 'SimTotalDelay_pax_s', 'SimBusDelay_pax_s',
        'SchedulePenalty_pax_s', 'TotalPassDelayInclSched_hrs',
        'AvgTotalPassDelay_pax_h_per_sim_h']

for label, pat in RUNS:
    d = sorted(glob.glob(pat))[-1]
    p = os.path.join(d, 'summary.json')
    with open(p, encoding='utf-8') as fh:
        s = json.load(fh)
    g = s.get('global_kpis') or s
    print('=' * 70)
    print(label, os.path.basename(d))
    for k in KEYS:
        print('  %-32s %s' % (k, g.get(k)))
    extra = [k for k in g if 'Pass' in k or 'Delay' in k]
    print('  (delay-ish keys: %s)' % ', '.join(sorted(extra)))

print('\n' + '=' * 70)
print('pair CSV rows')
for f in sorted(glob.glob('kg/results/gamesol_pair_kg_lightsim_20261110_1412*.csv')):
    print('file:', f, 'mtime', os.path.getmtime(f))
    with open(f, newline='', encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            arm = (r.get('Strategy') or r.get('strategy') or r.get('Arm')
                   or r.get('TSP_Strategy') or '?')
            print('  %-16s TotalPassDelay=%-10s MainPlusSide=%-10s Main=%-9s Side=%-9s scope=%s'
                  % (arm, r.get('stats_TotalPassDelay_hrs'),
                     r.get('stats_MainPlusSidePassDelay_hrs'),
                     r.get('stats_MainPassDelay_hrs'),
                     r.get('stats_SidePassDelay_hrs'),
                     r.get('stats_DelayScope')))
