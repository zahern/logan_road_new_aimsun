#!/usr/bin/env python
"""measure_ctm_reach.py -- how many metres of approach does the CTM actually model?

The game's payoff seeds each approach from the vehicles in ONE Aimsun section
(the stop-line section behind that phase's turning origins), and the CTM domain
for that section is

    n_cells  = max(1, min(ceil(L / cell_len), max_cells))   ctm_twoclass.ApproachGeom
    cell_len = max(v_free_ms * dt_s, 5.0)                   (27.8 m at 50 km/h, dt 2 s)
    span     = n_cells * cell_len  >=  L

so every vehicle inside the stop-line section is modelled, and NOTHING upstream
of it is -- the standing queue that extends across the connector chain on a
short-block corridor is invisible to the payoff unless GAME_CTM2_CHAIN_SEED is
on, which walks the upstream chain and caps the domain at
GAME_CTM2_CHAIN_REACH_M (200 m).

Data source (offline, no Aimsun): each run's section_timeseries.csv records
SectionID, IntersectionID, IsMain, Lanes and Length_km -- the same plant length
Engine._cbql_ctm_geom reads via AKIInfNetGetSectionANGInf(sec).length. A single
run only covers the sections it monitored, so lengths are unioned across the
most recent runs (the geometry is static) and the parser reports how many runs
saw each section plus any disagreement between them.

Outputs:
  * per corridor: length distribution, the approaches shorter than a 40 m
    REFERENCE threshold (real setbacks are per-approach, see DET_DISTANCE_M),
    and the sections that collapse to a single CTM cell;
  * ctm_approach_reach.csv: one row per (corridor, junction, section).

Usage:
  python measure_ctm_reach.py
  python measure_ctm_reach.py --runs 80 --top 20 --csv reach.csv
  python measure_ctm_reach.py --run logan_road_new/results/<rundir>
"""
from __future__ import print_function

import argparse
import collections
import csv
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORRIDORS = ('logan_road_new', 'kg')
DT_S = 2.0                 # CBQL_CTM_DT_S default
MAX_CELLS = 12             # CBQL_CTM_MAX_CELLS / GAME_CTM2_LIGHTSIM_MAX_CELLS default
VF_DEFAULT_KMH = 50.0      # CELLQ_CTM_FREEFLOW_KMH default
CHAIN_REACH_M = 200.0      # GAME_CTM2_CHAIN_REACH_M default
# REFERENCE threshold only, NOT the configured setback: KG is uniform 40.0 m,
# but Logan's intersection_configs.py carries per-approach values from 21 m to
# 50 m (DetDistance is [[main...],[side...]]). Verify per junction before
# claiming a bus at its detector is inside the modelled domain.
DET_DISTANCE_M = 40.0
GEOM_FAIL_DEFAULT_M = 150.0  # Engine._cbql_ctm_geom fallback if the ANG call fails


def asc(s):
    return ''.join(c if ord(c) < 128 else '?' for c in s)


def vf_kmh_for(sid, calib):
    try:
        return float(calib['sections'][str(sid)]['v_free_kmh'])
    except Exception:
        return VF_DEFAULT_KMH


def geom(sid, length_m, lanes, calib):
    """Replicate ctm_twoclass.ApproachGeom the way the engine builds it."""
    vf = vf_kmh_for(sid, calib)
    vf_ms = max(vf / 3.6, 1.0)
    cell_len = max(vf_ms * DT_S, 5.0)
    n_cells = max(1, min(int(math.ceil(max(length_m, 1.0) / cell_len)), MAX_CELLS))
    return {'v_free_kmh': vf, 'cell_len_m': cell_len, 'n_cells': n_cells,
            'span_m': n_cells * cell_len}


def newest_runs(root, n):
    files = glob.glob(os.path.join(root, 'results', '**', 'section_timeseries.csv'),
                      recursive=True)
    files.sort(key=os.path.getmtime, reverse=True)
    return files[:max(int(n), 1)]


def load_sections_many(paths):
    """{(jct, sid): {..., votes, runs_seen, conflict}} unioned over runs."""
    votes = collections.defaultdict(collections.Counter)
    meta = {}
    for p in paths:
        seen = set()
        try:
            with open(p, newline='', encoding='utf-8', errors='replace') as fh:
                for row in csv.DictReader(fh):
                    try:
                        sid = int(float(row['SectionID']))
                        jct = int(float(row['IntersectionID']))
                    except Exception:
                        continue
                    try:
                        L = round(float(row['Length_km']), 4)
                    except Exception:
                        L = 0.0
                    try:
                        lanes = max(int(float(row['Lanes'])), 1)
                    except Exception:
                        lanes = 1
                    try:
                        is_main = int(float(row['IsMain'])) == 1
                    except Exception:
                        is_main = False
                    k = (jct, sid)
                    votes[k][L] += 1
                    meta[k] = {'is_main': is_main, 'lanes': lanes}
                    seen.add(k)
        except Exception:
            continue
        for k in seen:
            meta[k].setdefault('runs', 0)
        for k in seen:
            meta[k]['runs'] = meta[k].get('runs', 0) + 1
    out = {}
    for k, cnt in votes.items():
        best = cnt.most_common(1)[0][0]
        out[k] = dict(meta.get(k) or {}, length_km=best,
                      conflict=len(cnt) > 1, variants=len(cnt),
                      runs_seen=int((meta.get(k) or {}).get('runs', 0)))
    return out


def main_side_ids(per_inter_csv):
    out = {}
    if not per_inter_csv or not os.path.isfile(per_inter_csv):
        return out

    def ids(s):
        return {int(float(x)) for x in (s or '').replace(',', '|').split('|')
                if x.strip() not in ('', 'nan', 'None')}

    with open(per_inter_csv, newline='', encoding='utf-8', errors='replace') as fh:
        for r in csv.DictReader(fh):
            try:
                jct = int(float(r['IntersectionID']))
            except Exception:
                continue
            out[jct] = (ids(r.get('MainSectionIDs')), ids(r.get('SideSectionIDs')))
    return out


def configured_ids_from_results(root):
    """Union of MainSectionIDs/SideSectionIDs over the newest per-intersection CSVs."""
    files = glob.glob(os.path.join(root, 'results', '**',
                                   'simulation_results_per_intersection.csv'),
                      recursive=True)
    files.sort(key=os.path.getmtime, reverse=True)
    out = {}
    for f in files[:12]:
        for jct, (mm, ss) in main_side_ids(f).items():
            hit = out.setdefault(jct, [set(), set()])
            hit[0] |= mm
            hit[1] |= ss
    return {j: (a, b) for j, (a, b) in out.items()}


def pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def corridor(root, calib, csvw=None, runs=40, run_dir=None):
    if run_dir:
        paths = [os.path.join(run_dir, 'section_timeseries.csv')]
    else:
        paths = newest_runs(root, runs)
    if not paths or not os.path.isfile(paths[0]):
        print(asc('  no section_timeseries.csv under %s/results' % root))
        return None
    secs = load_sections_many(paths)
    cfg = configured_ids_from_results(root)

    rows = []
    for (jct, sid), d in sorted(secs.items()):
        L = float(d.get('length_km') or 0.0) * 1000.0
        g = geom(sid, L, d['lanes'], calib)
        rows.append({'corridor': os.path.basename(root), 'junction': jct,
                     'section': sid, 'is_main': d['is_main'], 'lanes': d['lanes'],
                     'length_m': L, 'v_free_kmh': g['v_free_kmh'],
                     'cell_len_m': g['cell_len_m'], 'n_cells': g['n_cells'],
                     'span_m': g['span_m'], 'runs_seen': d['runs_seen'],
                     'conflict': d['conflict'],
                     # the domain is n_cells*cell_len; max_cells=12 can make it
                     # SHORTER than the plant section, and seed_cells drops the
                     # vehicles beyond it
                     'horizon_m': min(L, g['span_m']) if L > 0 else 0.0,
                     'cap_binds': g['span_m'] < L - 1e-9,
                     'bus40_inside': L >= DET_DISTANCE_M,
                     'zero_length': L <= 0.0})

    covered = {(r['junction'], r['section']) for r in rows}
    wanted = {(j, s) for j, (mm, ss) in cfg.items() for s in (mm | ss)}
    wanted_main = {(j, s) for j, (mm, ss) in cfg.items() for s in mm}
    wanted_side = {(j, s) for j, (mm, ss) in cfg.items() for s in ss}
    missing = sorted(wanted - covered)
    miss_main = sorted(wanted_main - covered)
    miss_side = sorted(wanted_side - covered)

    by_j = collections.defaultdict(list)
    for r in rows:
        by_j[r['junction']].append(r)

    print(asc('=' * 78))
    print(asc('CORRIDOR %s' % os.path.basename(root)))
    if run_dir:
        print(asc('  source : %s (single run)' % os.path.relpath(paths[0], HERE)))
    else:
        print(asc('  source : %d most recent runs (geometry unioned)' % len(paths)))
    print(asc('  sections measured: %d across %d junctions (%d main / %d side)'
              % (len(rows), len(by_j),
                 sum(1 for r in rows if r['is_main']),
                 sum(1 for r in rows if not r['is_main']))))
    if wanted:
        print(asc('  controller-configured approach sections: %d, measured: %d '
                  '(%.0f%%)' % (len(wanted), len(wanted & covered),
                                100.0 * len(wanted & covered) / len(wanted))))
        print(asc('    MAIN-listed %d/%d | SIDE-listed %d/%d  (a section can be '
                  'listed on both, so these need not sum to the total)'
                  % (len(wanted_main & covered), len(wanted_main),
                     len(wanted_side & covered), len(wanted_side))))
        if missing:
            print(asc('  unmeasured: %d unique (%d main-listed, %d side-listed); their '
                      'length still comes from the ANG API at runtime'
                      % (len(missing), len(miss_main), len(miss_side))))
    conf = [r for r in rows if r['conflict']]
    zero = [r for r in rows if r['zero_length']]
    print(asc('  sections whose length differs between runs: %d' % len(conf)))
    if zero:
        print(asc('  WARNING %d section(s) report Length_km=0 -> the engine falls back '
                  'to %.0f m' % (len(zero), GEOM_FAIL_DEFAULT_M)))

    main = [r['length_m'] for r in rows if r['is_main']]
    side = [r['length_m'] for r in rows if not r['is_main']]
    allL = [r['length_m'] for r in rows]

    def dist(vals, label):
        if not vals:
            return
        print(asc('  %-5s n=%-4d min=%-6.1f p10=%-6.1f median=%-6.1f mean=%-6.1f '
                  'max=%-6.1f' % (label, len(vals), min(vals), pct(vals, 0.10),
                                  pct(vals, 0.50), sum(vals) / len(vals), max(vals))))
        line = []
        for thr in (30.0, 40.0, 60.0):
            k = sum(1 for v in vals if v < thr)
            line.append('<%.0fm %d (%.0f%%)' % (thr, k, 100.0 * k / len(vals)))
        print(asc('        %s' % '  '.join(line)))

    dist(allL, 'all')
    dist(main, 'main')
    dist(side, 'side')

    capped = [r for r in rows if r['cap_binds']]
    hz = [r['horizon_m'] for r in rows]
    print(asc('  effective horizon min(L, 12*cell_len): median %.1f m, min %.1f m, '
              'max %.1f m' % (pct(hz, 0.5) or 0.0, min(hz) if hz else 0.0,
                               max(hz) if hz else 0.0)))
    if capped:
        print(asc('  CELL CAP BINDS on %d/%d sections (12 cells shorter than the '
                  'section): %s%s'
                  % (len(capped), len(rows),
                     [(r['junction'], r['section'], round(r['length_m'], 1))
                      for r in capped[:8]],
                     ' ...' if len(capped) > 8 else '')))
    oned = [r for r in rows if r['n_cells'] == 1]
    never = [j for j, rs in by_j.items()
             if all(r['length_m'] < DET_DISTANCE_M for r in rs)]
    some = [j for j, rs in by_j.items()
            if any(r['length_m'] < DET_DISTANCE_M for r in rs)]
    print(asc('  sections in ONE cell: %d/%d (%.0f%%) | median cell span %.1f m'
              % (len(oned), len(rows), 100.0 * len(oned) / max(len(rows), 1),
                 pct([r['cell_len_m'] for r in rows], 0.5) or 0.0)))
    print(asc('  junctions where EVERY approach < %.0f m: %d/%d | SOME: %d/%d'
              % (DET_DISTANCE_M, len(never), len(by_j), len(some), len(by_j))))

    print(asc('  %-9s %4s %5s %7s %7s %8s %9s %5s %s'
              % ('junction', 'n', 'main', 'min_m', 'med_m', 'max_m', 'avg_cells',
                 'bus40', 'flag')))
    order = sorted(by_j.items(), key=lambda kv: pct([r['length_m'] for r in kv[1]], 0.5))
    for jct, rs in order:
        Ls = [r['length_m'] for r in rs]
        flag = []
        if all(v < DET_DISTANCE_M for v in Ls):
            flag.append('NO-BUS-IN-DOMAIN')
        med = pct(Ls, 0.5)
        if med is not None and med < CHAIN_REACH_M / 4:
            flag.append('short-block')
        if any(r['conflict'] for r in rs):
            flag.append('LEN-CONFLICT')
        if any(r['cap_binds'] for r in rs):
            flag.append('CELL-CAP')
        print(asc('  %-9s %4d %5d %7.1f %7.1f %8.1f %9.1f %5.0f %s'
                  % (jct, len(rs), sum(1 for r in rs if r['is_main']),
                     min(Ls), med, max(Ls),
                     sum(r['n_cells'] for r in rs) / float(len(rs)),
                     100.0 * sum(1 for v in Ls if v >= DET_DISTANCE_M) / len(Ls),
                     ','.join(flag))))

    if csvw:
        for r in rows:
            csvw.writerow([r['corridor'], r['junction'], r['section'],
                           int(r['is_main']), r['lanes'], round(r['length_m'], 1),
                           round(r['v_free_kmh'], 1), round(r['cell_len_m'], 1),
                           r['n_cells'], round(r['span_m'], 1),
                           round(r['horizon_m'], 1), int(r['cap_binds']),
                           int(r['bus40_inside']), r['runs_seen'],
                           int(r['conflict'])])
    return {'rows': rows, 'by_junction': dict(by_j),
            'coverage': (len(wanted & covered), len(wanted))}


def main(argv):
    ap = argparse.ArgumentParser(
        description='Measure the stop-line section lengths the CTM models per junction.')
    ap.add_argument('--run', help='single run directory instead of a multi-run union')
    ap.add_argument('--corridor', choices=CORRIDORS)
    ap.add_argument('--runs', type=int, default=40,
                    help='number of recent runs to union lengths over (default 40)')
    ap.add_argument('--csv', default='ctm_approach_reach.csv')
    ap.add_argument('--no-csv', action='store_true')
    ap.add_argument('--top', type=int, default=0,
                    help='also list the N shortest approaches overall')
    a = ap.parse_args(argv)

    calib = {'sections': {}}
    cp = os.path.join(HERE, 'kg', 'ctm_calibration.json')
    if os.path.isfile(cp):
        try:
            calib = json.load(open(cp, encoding='utf-8'))
        except Exception as e:
            print(asc('(ctm_calibration.json unreadable: %r; using defaults)' % (e,)))

    roots = [a.corridor] if a.corridor else list(CORRIDORS)
    fh = None
    csvw = None
    if not a.no_csv:
        fh = open(a.csv, 'w', newline='', encoding='utf-8')
        csvw = csv.writer(fh)
        csvw.writerow(['corridor', 'junction', 'section', 'is_main', 'lanes',
                       'length_m', 'v_free_kmh', 'cell_len_m', 'n_cells',
                       'cell_span_m', 'horizon_m', 'cell_cap_binds',
                       'bus_at_40m_inside', 'runs_seen', 'length_conflict'])
    out = {}
    for c in roots:
        out[c] = corridor(os.path.join(HERE, c), calib, csvw, a.runs, a.run)
    if fh:
        fh.close()
        n = sum(len(v['rows']) for v in out.values() if v)
        print(asc('\nCSV: %s (%d rows)' % (a.csv, n)))

    if a.top:
        rows = [r for v in out.values() if v for r in v['rows']]
        rows.sort(key=lambda r: r['length_m'])
        print(asc('\nshortest approaches:'))
        print(asc('  %-18s %-9s %-9s %7s %6s %5s'
                  % ('corridor', 'junction', 'section', 'len_m', 'cells', 'main')))
        for r in rows[:a.top]:
            print(asc('  %-18s %-9s %-9s %7.1f %6d %5d'
                      % (r['corridor'], r['junction'], r['section'],
                         r['length_m'], r['n_cells'], int(r['is_main']))))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
