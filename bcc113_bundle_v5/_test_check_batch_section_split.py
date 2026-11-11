"""_test_check_batch_section_split.py -- check_batch must flag an unstable
main-approach set BEFORE the arms are ranked.

WHY. PaxEquivPassages (the objective numerator) is summed over the sections
classified as MAIN, so two seeds of one arm that classified different sections
as main are not comparable even on the same build. That happened on Logan
(21847 came out 2 vs 5 mains), so check_batch now compares each run's
MainSectionIDs per junction across the seeds of an arm.

    python -I _test_check_batch_section_split.py
"""
from __future__ import print_function

import csv
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import check_batch as C  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print('  %-52s %s' % (name, 'ok' if ok else 'FAIL'))
    if not ok:
        print('       got  %r\n       want %r' % (got, want))
        FAIL.append(name)


def make_run(root, name, mains, write_csv=True):
    d = os.path.join(root, name)
    os.makedirs(d)
    if not write_csv:
        return d
    with open(os.path.join(d, C.SECTION_CSV), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['IntersectionID', 'MainSectionIDs'])
        for j in sorted(mains):
            w.writerow([j, '|'.join(str(x) for x in mains[j])])
    return d


def row(arm, seed, folder):
    return {'run_strategy': arm, 'run_seed': seed,
            'stats_results_folder': folder}


A_MAINS = {21847: (10792, 14721), 17963: (61306, 12546)}
B_MAINS = {21847: (2890, 5737, 15262, 10792, 14721), 17963: (61306, 12546)}

root = tempfile.mkdtemp(prefix='_splitcheck_', dir=HERE)
try:
    print('1. same mains on every seed -> nothing to report')
    d1 = make_run(root, 'run_a300', A_MAINS)
    d2 = make_run(root, 'run_a400', A_MAINS)
    rows = [row('NO_TSP', '300', d1), row('NO_TSP', '400', d2)]
    checked, warns = C.section_splits(rows, 'run_strategy', 'run_seed')
    check('runs checked', checked, 2)
    check('warnings', warns, [])

    print('2. one seed classified extra sections as main -> reported')
    d3 = make_run(root, 'run_b400', B_MAINS)
    rows = [row('ARM_X', '300', d1), row('ARM_X', '400', d3)]
    checked, warns = C.section_splits(rows, 'run_strategy', 'run_seed')
    check('runs checked', checked, 2)
    check('one warning group', len(warns), 1)
    arm, seeds, ref_seeds, diffs = warns[0]
    check('arm', arm, 'ARM_X')
    check('deviating seed', seeds, ['400'])
    check('reference seed', ref_seeds, ['300'])
    check('differing junction', [d[0] for d in diffs], [21847])
    check('reference ids', diffs[0][1], (10792, 14721))
    check('deviating ids (sorted)', diffs[0][2],
          (2890, 5737, 10792, 14721, 15262))

    print('3. a missing run folder is a gap, not a difference')
    rows = [row('ARM_X', '300', d1), row('ARM_X', '400', os.path.join(root, 'gone'))]
    checked, warns = C.section_splits(rows, 'run_strategy', 'run_seed')
    check('runs checked', checked, 1)
    check('no false warning', warns, [])

    print('4. a folder without the per-intersection CSV is skipped')
    d4 = make_run(root, 'run_nocsv', A_MAINS, write_csv=False)
    rows = [row('ARM_X', '300', d1), row('ARM_X', '400', d4)]
    checked, warns = C.section_splits(rows, 'run_strategy', 'run_seed')
    check('runs checked', checked, 1)
    check('no false warning', warns, [])

    print('5. a single seed per arm is never flagged')
    rows = [row('ARM_Y', '300', d3)]
    checked, warns = C.section_splits(rows, 'run_strategy', 'run_seed')
    check('runs checked', checked, 1)
    check('no warning', warns, [])

    print('6. nothing readable at all is reported as unchecked, not clean')
    rows = [{'run_strategy': 'ARM_Z', 'run_seed': '300',
             'stats_results_folder': 'None'}]
    checked, warns = C.section_splits(rows, 'run_strategy', 'run_seed')
    check('runs checked', checked, 0)
    check('no warning', warns, [])
    print('7. KG partial rows: comma-separated ids and a stray token')
    d5 = os.path.join(root, 'run_kg_partial_row')
    os.makedirs(d5)
    with open(os.path.join(d5, C.SECTION_CSV), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['IntersectionID', 'MainSectionIDs'])
        w.writerow([36385, '1026438,1026371'])
        w.writerow([36393, '21469|11119129|abc'])
    sig = C.main_section_sets({'stats_results_folder': d5})
    check('comma-separated ids parsed', sig.get(36385), (1026371, 1026438))
    check('stray token dropped', sig.get(36393), (21469, 11119129))

    print('8. a junction only one run reports is coverage, not a split')
    common = {36385: (21472, 1026371), 39569: (21394, 71801)}
    d6 = make_run(root, 'run_kg_short_300', common)
    d8 = make_run(root, 'run_kg_short_500', common)
    full = dict(common)
    full[1043762] = (1043758,)
    d7 = make_run(root, 'run_kg_long_400', full)
    rows = [row('ARM_KG', '300', d6), row('ARM_KG', '400', d7),
            row('ARM_KG', '500', d8)]
    checked, warns = C.section_splits(rows, 'run_strategy', 'run_seed')
    check('three KG runs checked', checked, 3)
    check('one warning group', len(warns), 1)
    arm, seeds, ref_seeds, diffs = warns[0]
    check('majority is the reference', ref_seeds, ['300', '500'])
    check('deviating seed', seeds, ['400'])
    check('coverage junction flagged', [d[0] for d in diffs], [1043762])
    check('nothing claimed for the short runs', diffs[0][1], None)
    check('extra junction on the long run', diffs[0][2], (1043758,))

    print('9. same mains at KG junction ids -> nothing to report')
    rows = [row('ARM_KG', '300', d6), row('ARM_KG', '400', d6)]
    checked, warns = C.section_splits(rows, 'run_strategy', 'run_seed')
    check('no warning', warns, [])

finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print('RESULT: %d failure(s)' % len(FAIL))
raise SystemExit(1 if FAIL else 0)
