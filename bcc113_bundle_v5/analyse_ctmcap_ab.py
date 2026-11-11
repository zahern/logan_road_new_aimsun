"""analyse_ctmcap_ab.py -- paired CAP24 vs CAP12 report from a ladder CSV.

Same-seed pairing only (RULE 3): each seed contributes one CAP12 and one CAP24
row, and the delta is CAP24 - CAP12 on that seed. Metric direction is stated per
row; Objective_PaxPerDelayHr is passengers / delay-hour (higher is better) and
TotalPassDelay_hrs is lower-is-better.

stats_N_BusTrips is printed for reference only: it sums per-junction bus
detection-window clearances, so it scales with junction count and detector
placement and is NOT throughput (RULE 4). The corridor metrics are
N_LoopCompletions, MeanLoopTT_s and LoopsPerBus.

    python -I analyse_ctmcap_ab.py --csv game_ladder_kg_ctmcap_ab_YYYYmmdd_HHMMSS.csv

Accepts either the wide per-run CSV or the *_summary.csv (paired on the seed
column each one carries).
"""
import argparse
import csv
import os
import sys

CAP12 = 'CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_LIGHTSIM_CAP12'
CAP24 = 'CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_LIGHTSIM_CAP24'
NOTSP = 'NO_TSP'

# (column, label, higher_is_better or None)
METRICS = (
    ('stats_Objective_PaxPerDelayHr', 'Objective PaxPerDelayHr', True),
    ('stats_TotalPassDelay_hrs', 'TotalPassDelay_hrs', False),
    ('stats_MainPassDelay_hrs', 'MainPassDelay_hrs', False),
    ('stats_SidePassDelay_hrs', 'SidePassDelay_hrs', False),
    ('stats_AvgBusPassDelay_s', 'AvgBusPassDelay_s', False),
    ('stats_N_LoopCompletions', 'N_LoopCompletions', True),
    ('stats_MeanLoopTT_s', 'MeanLoopTT_s', False),
    ('stats_LoopsPerBus', 'LoopsPerBus', True),
    ('stats_N_BusTrips', 'N_BusTrips (reference only)', None),
)

SEED_COLS = ('run_seed', 'seed', 'run_seed_applied')
ARM_COLS = ('arm', 'strategy', 'experiment', 'run_arm', 'current_strategy',
            'arm_name', 'CURRENT_STRATEGY',
            # the wide per-run ladder CSV names these run_experiment/run_strategy
            'run_experiment', 'run_strategy')


def _arm_col(rows, cols):
    """The column that names the arm. Detected from values, not assumed."""
    for c in ARM_COLS:
        if c in cols and any(r[c].strip() for r in rows):
            vals = {r[c].strip() for r in rows}
            if vals & {CAP12, CAP24, NOTSP} or any('CAP' in v for v in vals):
                return c
    for c in cols:                       # last resort: any column naming CAP12
        if any(CAP12 in (r[c] or '') for r in rows):
            return c
    return None


def _seed_col(rows, cols):
    for c in SEED_COLS:
        if c in cols and any((r[c] or '').strip() for r in rows):
            return c
    return None


def _f(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', required=True)
    a = ap.parse_args()
    if not os.path.exists(a.csv):
        print('missing: %s' % a.csv)
        return 2

    with open(a.csv, newline='', encoding='utf-8-sig') as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print('empty CSV: %s' % a.csv)
        return 2
    cols = list(rows[0].keys())

    ac, sc = _arm_col(rows, cols), _seed_col(rows, cols)
    print('%s\n  rows=%d  arm column=%r  seed column=%r'
          % (os.path.basename(a.csv), len(rows), ac, sc))
    if not ac or not sc:
        print('  cannot locate the arm/seed columns -- columns are:')
        print('  %s' % ', '.join(cols[:40]))
        return 2

    by = {}
    for r in rows:
        arm, seed = (r[ac] or '').strip(), (r[sc] or '').strip()
        if arm and seed:
            by[(arm, seed)] = r
    seeds = sorted({s for (_a, s) in by}, key=lambda s: (len(s), s))
    arms = sorted({a_ for (a_, _s) in by})
    print('  arms: %s' % ', '.join(arms))
    print('  seeds: %s' % ', '.join(seeds))
    paired = [s for s in seeds if (CAP12, s) in by and (CAP24, s) in by]
    print('  paired seeds: %d\n' % len(paired))
    if not paired:
        print('  no seed has BOTH arms -- is this the cap A/B CSV?')
        return 1

    print('%-30s %10s %10s %10s %8s  %s'
          % ('metric', 'CAP12', 'CAP24', 'delta', 'delta%', 'seeds better under CAP24'))
    print('-' * 100)
    for col, label, higher in METRICS:
        if col not in cols:
            print('%-30s %s' % (label, '(column absent)'))
            continue
        v12, v24, better, total = [], [], 0, 0
        for s in paired:
            a12, a24 = _f(by[(CAP12, s)].get(col)), _f(by[(CAP24, s)].get(col))
            if a12 is None or a24 is None:
                continue
            v12.append(a12)
            v24.append(a24)
            total += 1
            if higher is not None:
                better += (a24 > a12) if higher else (a24 < a12)
        if not v12:
            print('%-30s %s' % (label, '(no numeric values)'))
            continue
        m12, m24 = sum(v12) / len(v12), sum(v24) / len(v24)
        d = m24 - m12
        pct = (100.0 * d / m12) if m12 else float('nan')
        tail = ('%d/%d' % (better, total)) if higher is not None else '-'
        if higher is True:
            tail += '  (higher better)'
        elif higher is False:
            tail += '  (lower better)'
        print('%-30s %10.3f %10.3f %+10.3f %+7.1f%%  %s'
              % (label, m12, m24, d, pct, tail))

    if any((NOTSP, s) in by for s in seeds):
        print('\nNO_TSP reference (mean over seeds):')
        for col, label, _h in METRICS:
            if col not in cols:
                continue
            vals = [_f(by[(NOTSP, s)].get(col)) for s in seeds if (NOTSP, s) in by]
            vals = [v for v in vals if v is not None]
            if vals:
                print('  %-30s %10.3f' % (label, sum(vals) / len(vals)))

    print('\nRead it as: a cap that stops truncation should not make the corridor '
          'worse.\nIf Objective falls or TotalPassDelay rises systematically with '
          'CAP24, the\nlarger domain is changing decisions rather than just '
          'correcting the model.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
