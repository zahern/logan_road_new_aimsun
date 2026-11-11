"""offline_section_lengths.py -- recover stop-line section lengths with no Aimsun.

WHY. measure_ctm_reach.py reads lengths from each run's section_timeseries.csv,
so sections the stats never monitored have no length offline: 24 of Logan's 111
configured approach sections and 9 of KG's 49. Their lengths only existed via
AKIInfNetGetSectionANGInf at runtime.

WHERE THEY ACTUALLY ARE. The engine already logs three independent length
carriers, and every one of them is written from the same AKI geometry the CTM
uses, so no model and no new run are needed:

  [PLAN_SCAN] inter=39606 t=0 ph1 origins=['21530(172m,4L)']
      One-time per junction, emitted by Engine._log_plan_scan. Its docstring is
      explicit: "the signal-plan origin sections ... with their REAL length +
      lane count, so the scanned approaches can be checked against the actual
      intersection geometry". Rounded to whole metres. Only covers sections that
      are a signal-plan origin.

  [FLOW SRC] sec=60456 tier=snapshot_alltypes nveh=1 spd=39.2 len=7m flow=...
      Per section, whenever its flow source is resolved. Direct section length.

  [SIDE_SCAN] ... secs=[60448, 60449, ...] len_m=['60.0[zone+model]', '8.0[dead+main+model]', ...]
      NOT a section length in general: [zone+model] is the FULL REACH with
      model-topology hops filling AKI gaps (section 4752 logs 68.0 m of reach
      but is 8 m long). Only the [dead+...]/[main...]/[managed...] tags carry a
      single-section value, so this source is validated per tag class and used
      only where it agrees exactly with the measured sections.

Every claim here is validated against the lengths already measured from
section_timeseries.csv (ctm_approach_reach.csv): a source that disagrees with a
single known section is dropped, not averaged.

Output: ctm_section_lengths_offline.csv
    corridor, junction, section, length_m, lanes, is_main, source, n_obs, was_missing

Usage:
    python offline_section_lengths.py
    python offline_section_lengths.py --logs 6 --csv x.csv
"""
from __future__ import print_function

import argparse
import collections
import csv
import glob
import io
import math
import os
import pathlib
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORRIDORS = ('logan_road_new', 'kg')
LOG_DIRS = {c: os.path.join(HERE, c, 'logs') for c in CORRIDORS}
MEAS_CSV = os.path.join(HERE, 'ctm_approach_reach.csv')
DB_PATHS = {
    'logan_road_new': 'logan_road_new/Logan_RD_for_QUT_with_detectors.sqlite',
    'kg': 'kg/TEG_KGER_T2_2025Base_QUT_AITAN1_RECOVER.sqlite',
}

RE_TAG = re.compile(r'\[([A-Z0-9_]+)\]')
RE_ORIG_BLOCK = re.compile(r'origins=\[(.*?)\]')
RE_ORIG_ONE = re.compile(r"'?(\d+)\((\d+(?:\.\d+)?)m,\s*(\d+)L\)'?")
RE_FLOWSRC = re.compile(r'\[FLOW SRC\]\s+sec=(\d+)\b.*?\blen=(\d+(?:\.\d+)?)m')
RE_SS_HEAD = re.compile(r'\[SIDE_SCAN\]\s+inter=(\d+).*?\bsecs=\[([\d,\s]+)\]')
RE_SS_LEN = re.compile(r"len_m=\[(.*?)\]\s+flow=")
RE_QUOTED = re.compile(r"'([^']*)'")


def asc(s):
    return ''.join(c if ord(c) < 128 else '?' for c in s)


def measured():
    """{(corridor, section): length_m} straight from the timeseries measurement."""
    out = collections.defaultdict(dict)
    if not os.path.isfile(MEAS_CSV):
        return out
    with io.open(MEAS_CSV, newline='', encoding='utf-8', errors='replace') as fh:
        for r in csv.DictReader(fh):
            try:
                out[r['corridor']][int(r['section'])] = float(r['length_m'])
            except Exception:
                pass
    return out


def scan_source(corridor, n_logs):
    """sid -> {source_key: [(length_m, lanes_or_None), ...]} from run logs."""
    logs = sorted(glob.glob(os.path.join(LOG_DIRS[corridor], 'Aimsun_TSP_Log_*.txt')),
                  key=os.path.getmtime, reverse=True)[:max(int(n_logs), 1)]
    obs = collections.defaultdict(lambda: collections.defaultdict(list))
    for lg in logs:
        try:
            txt = io.open(lg, encoding='utf-8', errors='replace').read()
        except Exception:
            continue
        for m in RE_ORIG_BLOCK.finditer(txt):
            for sid, L, lanes in RE_ORIG_ONE.findall(m.group(1)):
                obs[int(sid)]['plan_scan'].append((float(L), int(lanes)))
        for m in RE_FLOWSRC.finditer(txt):
            obs[int(m.group(1))]['flow_src'].append((float(m.group(2)), None))
        for ln in txt.splitlines():
            if '[SIDE_SCAN]' not in ln:
                continue
            h = RE_SS_HEAD.search(ln)
            if not h:
                continue
            ids = [int(x) for x in re.findall(r'\d+', h.group(2))]
            lm = RE_SS_LEN.search(ln)
            if not lm:
                continue
            vals = RE_QUOTED.findall(lm.group(1))
            for sid, raw in zip(ids, vals):
                v = re.match(r'([\d.]+)(\[[^\]]*\])?', raw.strip())
                if not v:
                    continue
                tag = (v.group(2) or '[]').strip('[]')
                obs[sid]['side_scan:%s' % tag].append((float(v.group(1)), None))
    return obs


def db_lengths(corridor):
    """sid -> (length, n) = min over intervals of speed(m/s) * ttime(s).

    The model's output DB (MISECT) has no length column, but a section's traverse
    is recoverable as speed * ttime; the MINIMUM over intervals is the least
    delayed one, so it approaches the geometric length. Unreliable whenever the
    section is queued in every interval, so summarise() must accept it against the
    measured sections before it is used -- it is never trusted on its own.
    """
    p = os.path.join(HERE, DB_PATHS.get(corridor, ''))
    if not p or not os.path.isfile(p) or os.path.getsize(p) == 0:
        return {}
    try:
        con = sqlite3.connect(pathlib.Path(p).resolve().as_uri() + '?mode=ro', uri=True)
        cur = con.cursor()
        best = {}
        for oid, speed, ttime in cur.execute(
                'SELECT oid, speed, ttime FROM MISECT WHERE speed > 0 AND ttime > 0'):
            try:
                L = float(speed) / 3.6 * float(ttime)
                sid = int(oid)
            except Exception:
                continue
            if L > 0:
                best[sid] = min(best.get(sid, L), L)
        con.close()
    except Exception:
        return {}
    return {sid: (round(L, 1), 1) for sid, L in best.items()}


def summarise(obs, meas_corr):
    """Per source key: unique value?, agreement with the measured sections."""
    stats = collections.defaultdict(lambda: {'vals': 0, 'conflict': 0,
                                             'agree': 0, 'disagree': 0,
                                             'worst': 0.0})
    value = {}
    for sid, by_src in obs.items():
        for key, samples in by_src.items():
            vals = sorted({round(v, 1) for v, _ in samples})
            st = stats[key]
            st['vals'] += 1
            if len(vals) > 1:
                st['conflict'] += 1
                continue
            v = vals[0]
            lanes = next((l for _, l in samples if l), None)
            value.setdefault(sid, {})[key] = (v, lanes)
            if sid in meas_corr:
                err = abs(v - meas_corr[sid])
                if err <= 1.0:
                    st['agree'] += 1
                else:
                    st['disagree'] += 1
                    st['worst'] = max(st['worst'], err)
    return stats, value


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--logs', type=int, default=8,
                    help='newest N run logs per corridor to scan (default 8)')
    ap.add_argument('--csv', default='ctm_section_lengths_offline.csv')
    a = ap.parse_args(argv)

    meas = measured()
    try:
        sys.path.insert(0, HERE)
        import measure_ctm_reach as mcr        # reuse the configured-id loaders
    except Exception as e:
        print('cannot import measure_ctm_reach: %r' % (e,))
        return 1

    rows = []
    for corridor in CORRIDORS:
        cfg = mcr.configured_ids_from_results(os.path.join(HERE, corridor))
        main_of, side_of = {}, {}
        for j, (mm, ss) in cfg.items():
            for s in mm:
                main_of.setdefault(s, set()).add(j)
            for s in ss:
                side_of.setdefault(s, set()).add(j)
        configured = set(main_of) | set(side_of)

        obs = scan_source(corridor, a.logs)
        for _sid, (_L, _n) in db_lengths(corridor).items():
            obs[_sid]['db_ttime_min'].append((_L, None))
        stats, value = summarise(obs, meas.get(corridor, {}))

        print('=' * 78)
        print('CORRIDOR %s  (%d configured approach sections, %d measured offline)'
              % (corridor, len(configured), len(meas.get(corridor, {}))))
        print('  source validation against the timeseries-measured lengths:')
        print('  %-26s %6s %9s %7s %9s %8s' %
              ('source', 'sects', 'conflict', 'agree', 'disagree', 'worst_err'))
        usable = []
        for key in sorted(stats):
            st = stats[key]
            ok = st['conflict'] == 0 and st['disagree'] == 0 and st['agree'] > 0
            print('  %-26s %6d %9d %7d %9d %8.1f%s'
                  % (key, st['vals'], st['conflict'], st['agree'],
                     st['disagree'], st['worst'], '' if ok else '   <- DROPPED'))
            if ok:
                usable.append(key)

        priority = (['plan_scan', 'flow_src']
                    + sorted(k for k in usable if k.startswith('side_scan:'))
                    + ['db_ttime_min'])
        remaining = [s for s in configured if s not in meas.get(corridor, {})]
        missing_before = set(remaining)
        for sid in sorted(configured | set(value)):
            pick = None
            for key in priority:
                if key in usable and key in value.get(sid, {}):
                    pick = (key,) + value[sid][key]
                    break
            if pick is None:
                continue
            key, L, lanes = pick
            js = sorted(main_of.get(sid, set()) | side_of.get(sid, set()))
            for j in (js or [0]):
                rows.append({'corridor': corridor, 'junction': j, 'section': sid,
                             'length_m': L, 'lanes': lanes if lanes else '',
                             'is_main': 1 if sid in main_of else 0,
                             'source': key, 'n_obs': len(obs.get(sid, {}).get(key, [])),
                             'was_missing': 1 if (j, sid) and sid in missing_before else 0})
        got = sorted(sid for sid in remaining if sid in value)
        print('  previously unmeasured: %d | now known from logs: %d'
              % (len(remaining), len([s for s in got
                                      if any(k in usable for k in value[s])])))
        still = [s for s in remaining if not any(k in usable for k in value.get(s, {}))]
        if still:
            print('  STILL UNKNOWN (%d): %s' % (len(still), still))

    seen, uniq = set(), []
    for r in rows:
        k = (r['corridor'], r['junction'], r['section'])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    uniq.sort(key=lambda r: (r['corridor'], r['junction'], r['section']))
    with io.open(a.csv, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=['corridor', 'junction', 'section',
                                           'length_m', 'lanes', 'is_main',
                                           'source', 'n_obs', 'was_missing'])
        w.writeheader()
        for r in uniq:
            w.writerow(r)
    n_missing = sum(1 for r in uniq if r['was_missing'])
    print('\nCSV: %s (%d rows, %d recovered previously-unmeasured sections)'
          % (a.csv, len(uniq), n_missing))
    by_src = collections.Counter(r['source'].split(':')[0] for r in uniq if r['was_missing'])
    if by_src:
        print('  recovered by source: %s' % dict(by_src))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
