"""bench_ctm_max_cells.py -- what raising CBQL_CTM_MAX_CELLS costs per junction.

Measures the REAL solver: shared_tsp_engine/ctm_twoclass.py, driven through
game_payoffs() exactly the way the engine calls it, on the real KG approach
geometry (lengths + free-flow speeds from ctm_approach_reach.csv and
ctm_section_lengths_offline.csv for the sections the timeseries never covered).

The cap only changes the number of cells, and cost is dominated by the per-step
loops in ctm_twoclass._step, so this isolates the cap's whole marginal cost:
vehicle enumeration, AKI calls and the rest of the engine are identical at any
cap and are therefore not in this number.

Cost is reported per junction per game solve, where one solve = the NO_ACTION
baseline plus every candidate action, i.e. what game_payoffs() does in one call.

Usage:
    python bench_ctm_max_cells.py
    python bench_ctm_max_cells.py --caps 12 21 24 --reps 7 --csv bench.csv
"""
from __future__ import print_function

import argparse
import csv
import json
import math
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'shared_tsp_engine'))
sys.path.insert(0, HERE)

import ctm_twoclass as _ctm2          # noqa: E402
from ctm_twoclass import ApproachGeom, CellState, game_payoffs  # noqa: E402

REACH_CSV = os.path.join(HERE, 'ctm_approach_reach.csv')
FILL_CSV = os.path.join(HERE, 'ctm_section_lengths_offline.csv')
CALIB = os.path.join(HERE, 'kg', 'ctm_calibration.json')

# the actions the ladder actually evaluates (see ctm_twoclass.TIMED_ACTIONS)
ACTIONS = [('GE', 4.0), ('GE', 6.0), ('GR', 4.0), ('GR', 6.0),
           ('INS', 6.0), ('INS', 8.0), ('ER', 2.0), ('ER', 4.0)]
HORIZON_S = 60.0
# The workload actually timed: 3x the real horizon, then divided back. Cost is
# linear in steps, so this buys 3x the signal against a roughly constant noise
# floor without changing what is being measured.
BENCH_HORIZON_S = 180.0
DT_S = 2.0
LEAD_S = 0.0
CUR_REM_S = 12.0


def asc(s):
    return ''.join(c if ord(c) < 128 else '?' for c in s)


def load_geometry():
    """{junction: [(section, length_m, v_free_kmh, lanes), ...]} for KG."""
    cal = {}
    try:
        with open(CALIB, encoding='utf-8') as fh:
            cal = json.load(fh).get('sections') or {}
    except Exception:
        pass
    rows = {}
    with open(REACH_CSV, newline='', encoding='utf-8', errors='replace') as fh:
        for r in csv.DictReader(fh):
            if r['corridor'] != 'kg':
                continue
            sid = int(r['section'])
            rows[sid] = [int(r['junction']), float(r['length_m']),
                         float(r['v_free_kmh']), max(int(r['lanes'] or 1), 1)]
    if os.path.isfile(FILL_CSV):
        with open(FILL_CSV, newline='', encoding='utf-8', errors='replace') as fh:
            for r in csv.DictReader(fh):
                if r['corridor'] != 'kg':
                    continue
                sid = int(r['section'])
                if sid in rows:
                    continue
                vf = float((cal.get(str(sid)) or {}).get('v_free_kmh', 50.0) or 50.0)
                lanes = int(r['lanes']) if str(r['lanes'] or '').strip() else 1
                rows[sid] = [int(r['junction']), float(r['length_m']), vf,
                             max(lanes, 1)]
    by_j = {}
    for sid, (j, L, vf, lanes) in rows.items():
        by_j.setdefault(j, []).append((sid, L, vf, lanes))
    for j in by_j:
        by_j[j].sort()
    return by_j


def snapshot_for(secdat, cap, n_phases):
    """One representative snapshot, keyed BY SECTION as game_payoffs expects:
    {sec: (geom, cells, arrivals, phases)}. Sections round-robin over phases,
    each seeded with a queue behind a red light (a bus at the stop line)."""
    snap = {}
    phases = []
    for idx, (sid, L, vf, lanes) in enumerate(secdat):
        g = ApproachGeom(length_m=L, lanes=lanes, v_free_kmh=vf, dt_s=DT_S,
                         max_cells=cap)
        K = g.n_cells
        car = [0.0] * K
        bus = [0.0] * K
        # fill ~40% of the modelled reach from the stop line back
        depth = max(1, int(round(0.4 * K)))
        for k in range(depth):
            car[K - 1 - k] = min(6.0, g.storage_pcu * 0.5)
        bus[K - 1] = 1.0
        ph = (idx % max(1, n_phases)) + 1
        if ph not in phases:
            phases.append(ph)
        snap[sid] = (g, CellState(car, bus), 600.0, (ph,))
    return snap, sorted(phases)


def one_solve(snap, ring, horizon=HORIZON_S):
    """Exactly one game_payoffs call: baseline + every candidate action."""
    return game_payoffs(snap, ring, ring[0], CUR_REM_S,
                        {p: 20.0 for p in ring}, ring[0], ACTIONS,
                        intergreen=5.0, horizon=horizon, dt=DT_S,
                        bus_pce=2.0, lead=LEAD_S)


def truncation(by_j, cap):
    """(n truncated sections, metres of approach not modelled) at this cap."""
    n, lost = 0, 0.0
    for secdat in by_j.values():
        for _, L, vf, ln in secdat:
            g = ApproachGeom(length_m=L, lanes=ln, v_free_kmh=vf, dt_s=DT_S,
                             max_cells=cap)
            span = g.n_cells * g.cell_len_m
            if span < L - 1e-9:
                n += 1
                lost += L - span
    return n, lost


def cells_of(secdat, cap):
    return sum(ApproachGeom(length_m=L, lanes=ln, v_free_kmh=vf, dt_s=DT_S,
                            max_cells=cap).n_cells
               for _, L, vf, ln in secdat)


def time_junction(secdat, cap, n_phases, reps, batch=3):
    """Microseconds for ONE solve at this cap.

    Each sample times `batch` consecutive solves and divides, so the clock read
    is amortised; the MINIMUM across reps is reported because it is the least
    noise-contaminated estimate of the work (GC pauses, OS scheduling and the
    other Python work in this process can only ADD time). Median is returned
    too, so instability is visible rather than hidden.
    """
    snap, ring = snapshot_for(secdat, cap, n_phases)
    for _ in range(2):                          # warm up caches
        one_solve(snap, ring, BENCH_HORIZON_S)
    samples = []
    for _ in range(max(int(reps), 1)):
        # perf_counter, NOT process_time: process_time on this Windows box has
        # ~15.6 ms granularity, which quantised the results onto a grid and made
        # different caps look identical. Each sample must stay well above the
        # noise floor, hence the batch.
        t0 = time.perf_counter()
        for _ in range(max(int(batch), 1)):
            one_solve(snap, ring, BENCH_HORIZON_S)
        samples.append((time.perf_counter() - t0) * 1e6 / max(int(batch), 1))
    return min(samples), statistics.median(samples), statistics.mean(samples)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--caps', type=int, nargs='+', default=[12, 16, 21, 24])
    ap.add_argument('--reps', type=int, default=5)
    ap.add_argument('--batch', type=int, default=10)
    ap.add_argument('--csv', default='ctm_max_cells_bench.csv')
    a = ap.parse_args(argv)

    by_j = load_geometry()
    print('KG junctions: %d | approach sections: %d | actions/solve: %d'
          % (len(by_j), sum(len(v) for v in by_j.values()), len(ACTIONS)))
    print('junctions: %s' % sorted(by_j))
    _scale = BENCH_HORIZON_S / HORIZON_S
    print('reported per solve at the real horizon %.0f s @ dt %.0f s (%d steps);'
          % (HORIZON_S, DT_S, int(HORIZON_S / DT_S)))
    print('timed on CPU time over a %.0f s horizon and divided by %.0f | '
          '%d reps x %d solves, minimum reported\n'
          % (BENCH_HORIZON_S, _scale, a.reps, a.batch))

    hdr = '  %-9s %3s' % ('junction', 'sec')
    for cap in a.caps:
        hdr += ' %10s' % ('cap%d' % cap)
    print(hdr + '   %10s %s' % ('delta_us', 'pct'))
    print('  (microseconds per solve; one solve = baseline + %d actions)' % len(ACTIONS))

    out = []
    base = a.caps[0]
    tot = {cap: 0.0 for cap in a.caps}
    tot_cells = {cap: 0 for cap in a.caps}
    unmapped = by_j.pop(0, [])
    if unmapped:
        print('  (%d measured sections carry no configured junction id -- '
              'excluded: %s)' % (len(unmapped), [s[0] for s in unmapped]))
    for j in sorted(by_j):
        secdat = by_j[j]
        n_ph = 2 if len(secdat) <= 3 else 3
        row = {'junction': j, 'sections': len(secdat)}
        line = '  %-9s %3d' % (j, len(secdat))
        for cap in a.caps:
            med, mid, mean = time_junction(secdat, cap, n_ph, a.reps, a.batch)
            med /= _scale
            row['us_cap%d' % cap] = round(med, 2)
            row['cells_cap%d' % cap] = cells_of(secdat, cap)
            tot[cap] += med
            tot_cells[cap] += row['cells_cap%d' % cap]
            line += ' %10.2f' % med
        d = row['us_cap%d' % a.caps[-1]] - row['us_cap%d' % base]
        pct = 100.0 * d / row['us_cap%d' % base] if row['us_cap%d' % base] else 0.0
        dcells = row['cells_cap%d' % a.caps[-1]] - row['cells_cap%d' % base]
        row['delta_us'] = round(d, 2)
        row['pct'] = round(pct, 1)
        line += '   %10.2f %+6.1f%%' % (d, pct)
        line += '  (dcells %+d)' % dcells
        print(line)
        row['delta_cells'] = dcells
        out.append(row)

    print('  ' + '-' * (len(hdr) + 18))
    line = '  %-9s %3s' % ('TOTAL', '')
    for cap in a.caps:
        line += ' %10.2f' % tot[cap]
    d = tot[a.caps[-1]] - tot[base]
    pct = 100.0 * d / tot[base] if tot[base] else 0.0
    line += '   %10.2f %+6.1f%%' % (d, pct)
    print(line)
    print('  total cells: %s' % {cap: tot_cells[cap] for cap in a.caps})
    print('  per-cell-step cost: %.4f us'
          % ((tot[a.caps[-1]] - tot[base]) /
             max(1.0, (tot_cells[a.caps[-1]] - tot_cells[base]) *
                 (HORIZON_S / DT_S) * (len(ACTIONS) + 1))))

    print('  benefit vs cost:')
    for cap in a.caps:
        n, lost = truncation(by_j, cap)
        print('    cap %2d -> %d section(s) truncated, %6.1f m of approach NOT modelled, '
              '%6.2f ms per corridor-wide solve'
              % (cap, n, lost, tot[cap] / 1000.0))

    with open(a.csv, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader()
        for r in out:
            w.writerow(r)
    print('\nCSV: %s (%d junctions)' % (a.csv, len(out)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
