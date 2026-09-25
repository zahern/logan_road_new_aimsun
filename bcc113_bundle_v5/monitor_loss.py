"""monitor_loss.py -- post-run loss-signature watch (read-only).
Reads an Aimsun_TSP log + side_sections_report.csv and flags per junction:
  FREE+pred_side=0 commits, car-only (bus=-1) commits, no-side junctions acting,
  snapshot-zero vs side_max mismatch, stale counters.
Usage (Aimsun console or plain python):
  python monitor_loss.py --log <Aimsun_TSP_Log> [--report side_sections_report.csv] [--top 10]
"""
import argparse, csv, os, re, collections
def parse(args):
    lines = open(args.log, encoding='utf-8', errors='replace').read().splitlines()
    dec = [ln for ln in lines if '[DECISION]' in ln]
    pat = re.compile(r'inter=(\d+).*?bus=(-?\d+).*?action=([A-Z]+)_?.*?pred_bus=([\d.]+).*?pred_other=([\d.]+).*?pred_side=([\d.]+).*?pred_net=([-\d.]+).*?(FREE|SAT|OVER|JAM)?')
    # trailing stage + side/q
    pat2 = re.compile(r'(FREE|SAT|OVER|JAM).*?side=([\d.]+).*?q=([\d.]+)')
    rows = []
    for ln in dec:
        m = pat.search(ln)
        if not m:
            continue
        m2 = pat2.search(ln)
        rows.append({'inter': m.group(1), 'bus': int(m.group(2)), 'act': m.group(3),
                      'pside': float(m.group(6)), 'pnet': float(m.group(7)),
                      'stage': m.group(8) or (m2.group(1) if m2 else '?'),
                      'side': float(m2.group(2)) if m2 else float('nan'),
                      'q': float(m2.group(3)) if m2 else float('nan')})
    # FLOW_STAGE end state
    spat = re.compile(r'\[FLOW_STAGE\]\s+inter=(\d+)\s+t=(\d+).*?main_x=([\d.]+).*?side_max=([\d.]+).*?queue=([\d.]+)')
    last = {}
    for ln in lines:
        if '[FLOW_STAGE]' in ln:
            m = spat.search(ln)
            if m:
                last[m.group(1)] = (int(m.group(2)), float(m.group(3)), float(m.group(4)), float(m.group(5)))
    # stale counters
    stale = collections.Counter()
    for ln in lines:
        if '[noupdate stale=' in ln:
            m = re.search(r'inter=(\d+).*?stale=([0-9,\s]+)', ln)
            if m:
                stale[m.group(1)] += 1
    # no-side junctions
    noside = set()
    if args.report and os.path.isfile(args.report):
        for r in csv.DictReader([ln for ln in open(args.report, encoding='utf-8').read().splitlines() if not ln.startswith('#')]):
            try:
                if int(r.get('n_side', 1)) == 0:
                    noside.add(str(r['intersection_id']).strip())
            except Exception:
                pass
    by = collections.defaultdict(list)
    for r in rows:
        by[r['inter']].append(r)
    print(f"log={os.path.basename(args.log)} DECISION commits={len(rows)} noside_junctions={sorted(noside)}")
    print(f"{'inter':>7} {'n':>4} {'%ps0':>6} {'%bus-1':>7} {'%FREE':>6} {'end_side':>9} {'end_q':>6} {'stale':>6}  flag")
    scored = []
    for iid, rs in by.items():
        n = len(rs)
        f0 = sum(1 for r in rs if r['pside'] == 0.0) / n
        fb = sum(1 for r in rs if r['bus'] < 0) / n
        ff = sum(1 for r in rs if r['stage'] == 'FREE') / n
        es, eq = (last[iid][2], last[iid][3]) if iid in last else (float('nan'), float('nan'))
        flags = []
        if iid in noside and n > 5:
            flags.append('NO-SIDE-ACTING')
        if f0 > 0.8 and n > 5:
            flags.append('PSIDE0')
        if fb > 0.5 and f0 > 0.8:
            flags.append('CAR-ONLY-ZERO-COST')
        if iid in last and es > 500 and f0 > 0.5:
            flags.append('SNAPSHOT-MISS')
        scored.append((n * f0, iid, n, f0, fb, ff, es, eq, stale.get(iid, 0), ','.join(flags)))
    scored.sort(reverse=True)
    for _, iid, n, f0, fb, ff, es, eq, st, fl in scored[:args.top]:
        print(f"{int(iid):>7} {n:>4} {f0:>5.0%} {fb:>6.0%} {ff:>5.0%} {es:>9.0f} {eq:>6.1f} {st:>6}  {fl}")
if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--log', required=True)
    ap.add_argument('--report', default=None)
    ap.add_argument('--top', type=int, default=10)
    a = ap.parse_args()
    if a.report is None:
        here = os.path.dirname(os.path.abspath(__file__))
        cand = os.path.join(here, 'logan_road_new', 'side_sections_report.csv')
        a.report = cand if os.path.isfile(cand) else None
    parse(a)
