"""Run-result diagnostics: compare 2+ kg/results/<RUN> folders that share a seed.

Answers the question "did today's engine changes break the system" from the
per-intersection result CSVs, WITHOUT opening Aimsun:

  python diag_compare_results.py <NO_TSP_folder> <arm1> [arm2 ...]

Rules (run_local_only: reads Z:/local disks only, never the cluster):
  - Folder 1 is the BASELINE (normally NO_TSP same-seed).
  - Per junction: TotalPassDelay_hrs (lower better), AvgQueue_veh,
    AvgPassDelay_s -- headroom factor = arm/baseline.
  - Global verdict per arm:
      PASS    no junction delay > 1.25x baseline and total <= 1.05x
      SUSPECT no junction > 1.5x but some > 1.25x, or total <= 1.15x
      BROKEN  any junction > 1.5x or total > 1.15x
      (1.15x total = seed noise loses at ~2% observed; 15% is a hard floor)
"""
import csv
import os
import sys

METRICS = ('TotalPassDelay_hrs', 'AvgQueue_veh', 'AvgPassDelay_s')
LIMIT_TOTAL = 1.15
LIMIT_J = 1.5
PASS_J = 1.25


def load(folder):
    path = os.path.join(folder, 'simulation_results_per_intersection.csv')
    with open(path, newline='', encoding='utf-8-sig') as fh:
        rows = list(csv.DictReader(fh))
    ids = []
    data = {}
    for i, r in enumerate(rows):
        jid = (r.get('IntersectionID') or '').strip() or ('row%d' % i)
        ids.append(jid)
        data[jid] = {m: float(r.get(m) or 0.0) for m in METRICS}
    return ids, data


def main(folders):
    base_ids, base = load(folders[0])
    arms = []
    for f in folders[1:]:
        ids, data = load(f)
        if ids != base_ids:
            print(f'!! {os.path.basename(f)}: JunctionID set/order differs '
                  f'from baseline -- row-index aligned, verify manually')
        arms.append((f, data))
    print('Baseline: %s   (total delay %.0f pax-h)' % (
        os.path.basename(folders[0]), sum(v['TotalPassDelay_hrs'] for v in base.values())))
    hdr = '%-14s %-10s' % ('junction', 'baseDelay') + \
        ''.join('%-22s' % os.path.basename(f)[:21] for f, _ in arms)
    print(hdr)
    for jid in base_ids:
        line = '%-14s %-10.1f' % (jid, base[jid]['TotalPassDelay_hrs'])
        for _, data in arms:
            d = data[jid]['TotalPassDelay_hrs']
            line += '%-22s' % ('%.1f (%.2fx)' % (d, d / max(base[jid]['TotalPassDelay_hrs'], 0.01)))
        print(line)
    for f, data in arms:
        ratios = [data[j]['TotalPassDelay_hrs'] / max(base[j]['TotalPassDelay_hrs'], 0.01)
                  for j in base_ids]
        tot = sum(data[j]['TotalPassDelay_hrs'] for j in base_ids)
        base_tot = sum(base[j]['TotalPassDelay_hrs'] for j in base_ids)
        r_tot = tot / max(base_tot, 0.01)
        worst_idx = max(range(len(ratios)), key=lambda i: ratios[i])
        if r_tot > LIMIT_TOTAL or max(ratios) > LIMIT_J:
            verdict = 'BROKEN'
        elif r_tot > PASS_J + 0.0 or max(ratios) > PASS_J:
            # total <= 1.15 but junction pressure > 1.25 -> watch
            verdict = 'SUSPECT'
        else:
            verdict = 'PASS'
        print('%s -> total %.0f pax-h (%.2fx base), worst junction %s %.2fx, queues +%.2fx, VERDICT: %s'
              % (os.path.basename(f), tot, r_tot, base_ids[worst_idx],
                 max(ratios),
                 (sum(data[j]['AvgQueue_veh'] for j in base_ids)
                  / max(sum(base[j]['AvgQueue_veh'] for j in base_ids), 0.01)),
                 verdict))


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit('usage: python diag_compare_results.py <baseline_folder> <arm_folder> [arm2 ...]')
    main(sys.argv[1:])
