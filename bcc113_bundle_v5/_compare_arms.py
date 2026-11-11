"""Why is the 20261110_162303 pair (NO_TSP vs GLOBAL_REWARD) worse?

Builds a cross-arm table for the day, then a per-junction diff for the pair.
Every number comes from the run artifacts; nothing is recomputed from memory.
"""
import csv
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

RES = 'kg/results'


def num(row, name, default=0.0):
    for k, v in row.items():
        if k and k.strip().lstrip('\ufeff') == name:
            try:
                return float(v)
            except (TypeError, ValueError):
                return default
    return default


def arm_of(d):
    b = os.path.basename(d)
    if b.startswith('NO_TSP'):
        return 'NO_TSP'
    m = re.match(r'CHAMP_ADAPTIVE_DSW_GAME_SOL_(\w+?)_CTM2', b)
    if m:
        return m.group(1)
    return b.split('_seed')[0][:24]


def stamp_of(d):
    m = re.search(r'_(\d{8})_(\d{6})$', os.path.basename(d))
    return (m.group(1)[4:] + '_' + m.group(2)) if m else '?'


def load(d):
    p = os.path.join(d, 'simulation_results.csv')
    if not os.path.exists(p):
        return None
    r = next(csv.DictReader(open(p, encoding='utf-8-sig')))
    rows = []
    q = os.path.join(d, 'simulation_results_per_intersection.csv')
    if os.path.exists(q):
        rows = list(csv.DictReader(open(q, encoding='utf-8-sig')))
    sw = {}
    q = os.path.join(d, 'signal_wait_summary.json')
    if os.path.exists(q):
        sw = json.load(open(q))
    return r, rows, sw


print('=' * 132)
print('%-14s %-11s %8s %9s %10s %10s %8s %8s %6s %6s %6s %7s'
      % ('arm', 'stamp', 'obj', 'Total_h', 'MainSide_h', 'Corridor_h',
         'loops', 'LpBus', 'meanTT', 'speed', 'det', 'ext+ins'))
print('=' * 132)
runs = []
for d in sorted(glob.glob(os.path.join(RES, '*20261110_1[2-8]*'))):
    got = load(d)
    if not got:
        continue
    r, rows, sw = got
    obj = num(r, 'Objective_PaxPerDelayHr')
    tot = num(r, 'TotalPassDelay_hrs')
    ms = num(r, 'MainPlusSidePassDelay_hrs')
    corr = num(r, 'CorridorPassDelay_hrs')
    loops = num(r, 'N_LoopCompletions')
    lpb = num(r, 'LoopsPerBus')
    mtt = num(r, 'MeanLoopTT_s')
    spd = num(r, 'Net_AvgSpeed_kmh')
    det = num(r, 'TSP_Detections')
    ext = num(r, 'TSP_Extensions') + num(r, 'TSP_Insertions')
    runs.append((stamp_of(d), arm_of(d), d, r, rows, sw))
    print('%-14s %-11s %8.2f %9.2f %10.2f %10.2f %8.0f %8.3f %6.2f %6.3f %6.0f %5.0f+%0.0f'
          % (arm_of(d), stamp_of(d), obj, tot, ms, corr, loops, lpb, mtt, spd,
             det, num(r, 'TSP_Extensions'), num(r, 'TSP_Insertions')))

# ---------------------------------------------------------------- pair diff
# The 16:23 CSV's second row is the run in the 163445 folder. Its folder name
# says NASH (stale arm list in the launcher) but simulation_results.csv records
# stats_TSP_Strategy=GLOBAL_REWARD, which is what the CSV row shows.
pair = [x for x in runs if x[0] in ('1110_162523', '1110_163445')]
if len(pair) < 2:
    print('\n[WARN] could not identify both folders for the 16:23 pair; found %s'
          % [(x[1], x[0]) for x in pair])
    sys.exit(0)

a = next(x for x in pair if x[1] == 'NO_TSP')
b = next(x for x in pair if x[0] == '1110_163445')
print('\n' + '=' * 100)
print('PAIR: %s (%s)  vs  %s (%s)' % (a[1], a[0], b[1], b[0]))
print('=' * 100)

ra, rb = a[3], b[3]
for k in ('N_DistinctBuses', 'N_DistinctCars', 'PaxEquivPassages',
          'SimDuration_hrs', 'BusTotalTT_hrs', 'AvgPassDelay_s',
          'SimBusDelay_pax_s', 'SimVQDelay_pax_s', 'VQPeakVeh_s',
          'AvgPassDelay_inclVQ_s', 'SchedulePenalty_pax_s'):
    print('  %-24s %14s %14s' % (k, ra.get(k, '?'), rb.get(k, '?')))

print('\n  per-junction delay (h) and bus term (pax-s):')
print('  %-10s %18s %18s %12s %12s'
      % ('junction', 'NO_TSP main/side', 'GR main/side', 'dTotal_h', 'dBus_paxs'))
by_id = {}
for tag, rows in ((a[1], a[4]), (b[1], b[4])):
    for r in rows:
        jid = int(float(r['IntersectionID']))
        by_id.setdefault(jid, {})[tag] = r

diffs = []
for jid, dd in by_id.items():
    if len(dd) < 2:
        continue
    ra_, rb_ = dd[a[1]], dd[b[1]]
    ta, tb = num(ra_, 'TotalPassDelay_hrs'), num(rb_, 'TotalPassDelay_hrs')
    ma, sa = num(ra_, 'MainPassDelay_hrs'), num(ra_, 'SidePassDelay_hrs')
    mb, sb = num(rb_, 'MainPassDelay_hrs'), num(rb_, 'SidePassDelay_hrs')
    ba = num(ra_, 'AvgBusPassDelay_s') * num(ra_, 'BusPaxEquivPassages')
    bb = num(rb_, 'AvgBusPassDelay_s') * num(rb_, 'BusPaxEquivPassages')
    diffs.append((tb - ta, jid, ta, tb, ma, sa, mb, sb, bb - ba))

for d_tot, jid, ta, tb, ma, sa, mb, sb, dbus in sorted(diffs, reverse=True):
    print('  %-10d %7.2f / %-7.2f %7.2f / %-7.2f %+12.2f %+12.0f'
          % (jid, ma, sa, mb, sb, d_tot, dbus))
print('  %-10s %18.2f %18.2f %+12.2f %+12.0f'
      % ('SUM', sum(x[2] for x in diffs), sum(x[3] for x in diffs),
         sum(x[3] - x[2] for x in diffs), sum(x[8] for x in diffs)))
