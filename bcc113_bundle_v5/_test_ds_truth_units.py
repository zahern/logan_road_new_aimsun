"""Offline test of the DS truth-check UNITS fix (2026-11-06).

section_timeseries.csv writes queue_veh PER LANE; the DS estimate is the TOTAL
standing queue over every lane and section of a phase. The truth must
therefore be  sum_s queue_veh_s * lanes_s. Runs the REAL
_finalize_ds_truth_check and _ds_calibration on synthetic files:

    python -I _test_ds_truth_units.py         (exit 0 = PASS)

Checks
  1. a PERFECT estimator (est = true total) scores bias 0 / MAE 0
     (before the fix it scored bias > 0: truth was a per-lane mean)
  2. the calibration JSON is stamped units=total_veh_v2
  3. a calibration file WITHOUT the stamp is ignored (no correction applied)
"""
import ast
import csv
import datetime
import io
import json
import math
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
src = io.open(os.path.join(HERE, 'shared_tsp_engine', 'engine.py'), encoding='utf-8').read()
seg = {}
for n in ast.parse(src).body:
    if isinstance(n, ast.FunctionDef) and n.name in ('_finalize_ds_truth_check',
                                                     '_ds_calibration'):
        seg[n.name] = ast.get_source_segment(src, n)
assert len(seg) == 2, seg.keys()

D = tempfile.mkdtemp(prefix='dstruth_')
LOG = []


class Stats(object):
    def _run_path(self):
        return D


ns = {'os': os, 'math': math, 'datetime': datetime, 'stats': Stats(), 'LOG_DIR': D,
      'log_to_file': lambda m, force=False: LOG.append(m),
      '_DS_TRUTH_CSV': os.path.join(D, 'ds_truth_check_estimates_TEST_1.csv'),
      '_CURRENT_EXPERIMENT': 'TEST', 'ENGINE_BUILD': 'test', '_DS_CALIB_CACHE': None}
ns['globals'] = lambda: ns
exec(seg['_finalize_ds_truth_check'] + '\n\n' + seg['_ds_calibration'], ns)

# truth: phase 1 of junction 7 is fed by section 10 (3 lanes) and 11 (2 lanes)
with open(os.path.join(D, 'section_timeseries.csv'), 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['SectionID', 't_start_s', 'queue_veh', 'q_veh_h', 'lanes'])
    for k in range(60):
        t = 30.0 * k
        w.writerow([10, t, 2.0 + (k % 5), 600, 3])      # per lane
        w.writerow([11, t, 1.0 + (k % 3), 400, 2])
# a PERFECT estimator: total = 3*q10 + 2*q11
with open(ns['_DS_TRUTH_CSV'], 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['sim_time_s', 'junction_id', 'phase', 'section_ids', 'n_sections',
                'est_queue_veh', 'est_flow_vph', 'est_ds', 'est_ds_flow', 'green_s',
                'lanes', 'current_phase', 'is_bus_phase'])
    for k in range(60):
        tot = 3 * (2.0 + (k % 5)) + 2 * (1.0 + (k % 3))
        w.writerow([30.0 * k, 7, 1, '10|11', 2, tot, 1000, 0.5, 0.5, 20, 5, 1, 1])

ns['_finalize_ds_truth_check']()
fails = []


def check(name, cond, detail=''):
    print('  %-4s %s %s' % ('ok' if cond else 'FAIL', name, detail))
    if not cond:
        fails.append(name)


summ = [p for p in os.listdir(D) if p.endswith('_summary.csv')]
rows = list(csv.DictReader(open(os.path.join(D, summ[0])))) if summ else []
r7 = next((r for r in rows if r['junction_id'] == '7'), None)
check('1 perfect estimator scores bias 0 / MAE 0',
      r7 is not None and abs(float(r7['bias_veh'])) < 1e-6
      and abs(float(r7['mae_veh'])) < 1e-6, r7)
cal = json.load(open(os.path.join(D, 'ds_bias_calibration.json')))
check('2 calibration stamped units=total_veh_v2', cal.get('units') == 'total_veh_v2')
ns['_DS_CALIB_CACHE'] = None
check('2b stamped calibration is loaded', bool(ns['_ds_calibration']()))
old = dict(cal); old.pop('units')
json.dump(old, open(os.path.join(D, 'ds_bias_calibration.json'), 'w'))
ns['_DS_CALIB_CACHE'] = None
check('3 unstamped (pre-fix) calibration is ignored', ns['_ds_calibration']() == {},
      [m for m in LOG if 'IGNORED' in m][:1])
shutil.rmtree(D, ignore_errors=True)
if fails:
    sys.exit('FAIL: %s' % fails)
print('PASS')
