"""diagnose_run_log.py -- one-page verdict on a TSP run log: did the controller
learn, did it act, why it held, did the solver find gains, which modelling
assumptions failed, did any code fault get swallowed.

Run LOCALLY after a run (no Aimsun):

    python -I diagnose_run_log.py                       # newest kg/logs/Aimsun_TSP_Log_*.txt
    python -I diagnose_run_log.py --log PATH            # a specific log
    python -I diagnose_run_log.py --all                 # every log from the last 12 h
    python -I diagnose_run_log.py --csv cellq_held_kg_YYYYmmdd_HHMMSS.csv
                                                        # + arm-vs-NO_TSP table

Exit code 0 = no red flags, 1 = at least one RED flag (usable as a gate).

What it reads (all lines the engine already writes):
  [LOAD] / [ARM]           build, arm
  [BXT_PHASE]              learner phase, freeze, Q-states (untrained = red)
  [REWARD_TSP] DECISION=   executed actions vs every NO_ACTION reason
  [SW_SOLVE]               shockwave GE/INS solves: range, optimum, gain
  [SOLVE_NO_GAIN]          solves held because acting raised total delay
  [CELLQ_HELD]/[ADMIT]     decider vetoes by binding constraint
  [ASSUME_SUMMARY]         assumption checks (flags the big ones)
  [VLOOP_LAYOUT]           loop-placement warnings
  [BUS_ROUTE]/_MISS        how bus ETAs were formed
  [SCHED_STOPS_STATUS]     timetable stop data available?
  [SWALLOWED]/[FATAL]      code faults
"""
import argparse
import csv
import glob
import io
import os
import re
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
RED, AMBER, OK = 'RED', 'AMBER', 'ok'


def _num(s):
    try:
        return float(s)
    except Exception:
        return None


def analyse(path):
    txt = io.open(path, encoding='utf-8', errors='replace').read()
    L = txt.splitlines()
    out = []
    flags = []

    def flag(level, msg):
        flags.append((level, msg))

    def grab(pat, default='?'):
        m = re.search(pat, txt)
        return m.group(1) if m else default

    build = grab(r'ENGINE_BUILD=(\S+)')
    arm = grab(r'\[ARM\] exp=(\S+)', grab(r'experiment=(\S+)'))
    out.append('log    : %s' % path)
    out.append('build  : %s' % build)
    out.append('arm    : %s' % arm)

    # ---- learner phase ---------------------------------------------------
    ph = re.search(r'\[BXT_PHASE\] seed=(\d+) phase=(\w+) train=(\[[^\]]*\]) '
                   r'eval=(\[[^\]]*\]) freeze=(\w+) q_states=(\d+)', txt)
    loaded = grab(r'\[BXT_PERSIST\].*?loaded (\d+) Q-state', None)
    if ph:
        seed, phase, train, ev, frz, qs = ph.groups()
        out.append('learner: seed=%s phase=%s train=%s freeze=%s q_states=%s loaded=%s'
                   % (seed, phase, train, frz, qs, loaded))
        if phase == 'eval' and train == '[]' and frz == 'True':
            flag(RED, 'learner scored UNTRAINED and FROZEN (train=[] freeze=True) -- '
                      'set FIXED_TRAIN_SEEDS / ARM_SUITE_TRAIN_SEEDS')
    # ---- decisions -------------------------------------------------------
    dec = Counter()
    acts = Counter()
    for l in L:
        m = re.search(r'\[REWARD_TSP\].*DECISION=(\S+)(.*)', l)
        if not m:
            continue
        d, rest = m.group(1), m.group(2)
        if d == 'NO_ACTION':
            r = re.search(r'\(([^)]*)\)', rest)
            reason = re.sub(r'[0-9]+(\.[0-9]+)?', 'N', r.group(1)) if r else '?'
            dec['hold: ' + reason] += 1
        else:
            dec['ACT'] += 1
            acts[re.sub(r'_.*', '', d)] += 1
    n_dec = sum(dec.values())
    out.append('decisions: %d total, %d acted %s' % (n_dec, dec['ACT'], dict(acts) or ''))
    for k, v in dec.most_common():
        if k != 'ACT':
            out.append('    %5d  %s' % (v, k))
    if n_dec and dec['ACT'] == 0:
        flag(RED, 'controller NEVER acted (%d decisions)' % n_dec)
    elif n_dec and dec['ACT'] < 0.05 * n_dec:
        flag(AMBER, 'controller acted on only %d of %d decisions' % (dec['ACT'], n_dec))
    _floor = sum(v for k, v in dec.items() if 'duration <' in k)
    if _floor:
        flag(RED, '%d solved actions discarded by the MIN_ACTION_DURATION_S floor'
                  % _floor)
    # ---- shockwave solves ------------------------------------------------
    sol = []
    for l in L:
        m = re.search(r'\[SW_SOLVE\] (\w+) .*\[(\d+),(\d+)\] opt=([0-9.]+) pax ([0-9.]+)->([0-9.]+)'
                      r'(?:.*busdelay ([0-9.]+)->([0-9.]+)s)?', l)
        if m:
            k, lo, hi, opt, b0, b1, d0, d1 = m.groups()
            sol.append((k, float(lo), float(hi), float(opt), float(b0), float(b1),
                        _num(d0), _num(d1)))
    if sol:
        gain = sum(1 for s in sol if s[5] < s[4])
        at_lb = sum(1 for s in sol if abs(s[3] - s[1]) < 0.05)
        served = sum(1 for s in sol if s[6] is not None and s[7] is not None
                     and s[7] < 0.5 * s[6])
        blow = sum(1 for s in sol if s[4] > 1e5)
        rng = Counter('%s[%g,%g]' % (s[0], s[1], s[2]) for s in sol)
        out.append('solves : %d (%s) gain=%d at_lower_bound=%d serve_bus=%d objective>1e5=%d'
                   % (len(sol), dict(rng), gain, at_lb, served, blow))
        if gain == 0:
            flag(AMBER, 'no shockwave solve found a delay reduction (%d solves)' % len(sol))
        if at_lb > 0.8 * len(sol):
            flag(AMBER, '%d/%d solves sit on the lower bound -- the range may be '
                        'too short to serve the bus' % (at_lb, len(sol)))
        if blow:
            flag(AMBER, '%d solves had an objective > 1e5 pax.s (legacy shockwave '
                        'term blowing up)' % blow)
    out.append('held by SOLVE_NO_GAIN: %d' % txt.count('[SOLVE_NO_GAIN]'))
    z4 = txt.count('[Z4 GATE]')
    if z4:
        out.append('held by the Z4 gate: %d' % z4)
        if dec.get('ACT', 0) and z4 > dec.get('ACT', 0):
            flag(AMBER, 'the Z4 gate vetoed more actions (%d) than executed (%d)'
                        % (z4, dec.get('ACT', 0)))
    na = re.findall(r'\[GAME_CTM2_NA\] inter=(\S+) (.*) -> legacy payoffs', txt)
    if na:
        out.append('CTM2 payoffs unavailable: %s' % sorted(set(r for _j, r in na)))
    # ---- game solution concepts -------------------------------------------
    gs = re.findall(r'\[GAME_SOLVE\] .*?game=(\w+) (?:payoff=(\S+) )?.*?n=(\d+) '
                    r'feas=(\d+) pick=(\S+)(.*)', txt)
    if gs:
        by = {}
        for g, pm, n, f, pick, rest in gs:
            g = '%s@%s' % (g, pm or 'legacy')
            d = by.setdefault(g, Counter())
            d['solves'] += 1
            d['picked' if pick != 'NO_ACTION' else 'held'] += 1
            if pick == 'NO_ACTION':
                r = re.search(r'\(([^)]*)\)', rest)
                d['held: ' + (r.group(1) if r else '?')] += 1
            d['feasible_sum'] += int(f)
        for g, d in sorted(by.items()):
            out.append('game   : %-18s solves=%d picked=%d held=%d mean feasible=%.1f %s'
                       % (g, d['solves'], d['picked'], d['held'],
                          d['feasible_sum'] / max(d['solves'], 1),
                          {k: v for k, v in d.items() if k.startswith('held:')}))
            if d['picked'] == 0:
                flag(AMBER, 'game %s never picked an action in %d solves'
                            % (g, d['solves']))
    # ---- decider vetoes --------------------------------------------------
    vt = Counter(re.findall(r'\[CELLQ_HELD\].*?veto=([a-z_]+)\(', txt))
    if vt or '[CELLQ_ADMIT]' in txt:
        out.append('CellQ  : admits=%d vetoes=%s' % (txt.count('[CELLQ_ADMIT]'), dict(vt)))
    # ---- assumptions -----------------------------------------------------
    asu = re.findall(r'\[ASSUME_SUMMARY\] (\S+)\s+n=(\d+)\s+(.*)', txt)
    if asu:
        out.append('assumption checks:')
    for k, n, rest in asu:
        out.append('    %-38s n=%-6s %s' % (k, n, rest.strip()))
        m = re.search(r'mae=([0-9.]+)', rest)
        b = re.search(r'bias=([-+0-9.]+)', rest)
        t = re.search(r'true=([0-9.]+)%', rest)
        if k == 'rem_green_plan_s' and m and float(m.group(1)) > 10:
            flag(AMBER, '%s off by %s s on average' % (k, m.group(1)))
        if k.startswith('eta_route') and 'unresolved' not in k and m and float(m.group(1)) > 20:
            flag(AMBER, 'route ETA error %s s (%s)' % (m.group(1), k))
        if k == 'saturation_flow_vph_lane' and b and abs(float(b.group(1))) > 150:
            flag(AMBER, 'saturation flow differs from the model by %s veh/h/lane'
                        % b.group(1))
        if k.startswith('advance_clear') and t and float(t.group(1)) < 90:
            flag(AMBER, '%s only %s%% -- ADVANCE loops sit in the queue' % (k, t.group(1)))
    # ---- loops / ETA sources / stops ------------------------------------
    lay = [l for l in L if '[VLOOP_LAYOUT]' in l]
    if lay:
        w = Counter()
        for l in lay:
            for part in (l.split('WARN:', 1)[1].split('| learned')[0].split('|')
                         if 'WARN:' in l else []):
                w[re.sub(r'[0-9]+', 'N', part.split('--')[0].strip())[:60]] += 1
        out.append('loop layouts: %d approaches, %d with warnings' %
                   (len(lay), sum(1 for l in lay if 'WARN:' in l)))
        for k, v in w.most_common(5):
            out.append('    %4d  %s' % (v, k))
    src = Counter(re.findall(r'\[BUS_ROUTE\].*? src=(\w+)', txt))
    if src:
        out.append('bus ETA source: %s  route misses logged: %d'
                   % (dict(src), txt.count('[BUS_ROUTE_MISS]')))
        if src.get('detect', 0) > 0.3 * sum(src.values()):
            flag(AMBER, 'route ETA fell back to detection for %d of %d buses'
                        % (src['detect'], sum(src.values())))
    st = grab(r'\[SCHED_STOPS_STATUS\] lines with per-stop sections: (\d+)', None)
    if st is not None:
        out.append('timetable stop data: %s lines' % st)
        if st == '0':
            flag(AMBER, 'no timetable stop sections loaded -- route ETA has no dwell')
    # ---- faults ----------------------------------------------------------
    sw = [l.split('|', 1)[-1].strip() for l in L if '[SWALLOWED]' in l]
    fatal = sum(1 for l in L if '[FATAL]' in l or 'Traceback' in l)
    out.append('swallowed: %s' % (sw[-1] if sw else '(no summary line)'))
    for l in sw[:-1][:8]:
        out.append('    ' + l[:200])
    if fatal:
        flag(RED, '%d FATAL / Traceback lines' % fatal)
    if sw and 'none this run' not in sw[-1]:
        flag(AMBER, 'exceptions were swallowed -- see the FIRST-hit lines above')
    tk = grab(r'\[TIKZ\] wrote (\d+) figures', None)
    if tk:
        out.append('tikz   : %s figures written' % tk)
    return out, flags


def compare_csv(path):
    """arm-vs-NO_TSP on the per-run CSV the suite writes (eval seeds only)."""
    rows = list(csv.DictReader(io.open(path, encoding='utf-8-sig', errors='replace')))
    keys = [k for k in ('stats_Objective_PaxPerDelayHr', 'stats_TotalPassDelay_hrs',
                        'stats_AvgBusPassDelay_s', 'stats_MainPassDelay_hrs',
                        'stats_SidePassDelay_hrs', 'stats_TSP_Extensions',
                        'stats_TSP_Insertions') if rows and k in rows[0]]
    _counts = ('stats_TSP_Extensions', 'stats_TSP_Insertions')
    by = {}
    for r in rows:
        by.setdefault(r.get('run_experiment', '?'), {})[r.get('run_seed')] = r
    base = by.get('NO_TSP', {})
    out = ['', 'results vs NO_TSP (%s, mean over paired seeds; Objective is '
               'higher-better, delays lower-better):' % os.path.basename(path)]
    for arm, seeds in sorted(by.items()):
        if arm == 'NO_TSP':
            continue
        cells = []
        for k in keys:
            d = []
            for s, r in seeds.items():
                b = base.get(s)
                if b is None:
                    continue
                x, y = _num(r.get(k)), _num(b.get(k))
                if k in _counts:
                    if x is not None:
                        d.append(x)
                elif x is not None and y not in (None, 0.0):
                    d.append(100.0 * (x - y) / abs(y))
            if d and k in _counts:
                cells.append('%s %.1f/run' % (k.replace('stats_TSP_', ''), sum(d) / len(d)))
            elif d:
                cells.append('%s %+.1f%%' % (k.replace('stats_', ''), sum(d) / len(d)))
        out.append('    %-42s %s' % (arm, '  '.join(cells) or '(no paired seeds)'))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--log')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--csv')
    ap.add_argument('--logs-dir', default=os.path.join(HERE, 'kg', 'logs'))
    a = ap.parse_args()
    if a.log:
        logs = [a.log]
    else:
        cand = sorted(glob.glob(os.path.join(a.logs_dir, 'Aimsun_TSP_Log_*.txt')),
                      key=os.path.getmtime)
        if a.all:
            logs = [p for p in cand if os.path.getmtime(p) > time.time() - 12 * 3600]
        else:
            logs = cand[-1:]
    if not logs and not a.csv:
        print('no logs found in %s (pass --log PATH)' % a.logs_dir)
        return 2
    worst = OK
    for p in logs:
        out, flags = analyse(p)
        print('=' * 78)
        print('\n'.join(out))
        print('-' * 78)
        if not flags:
            print('VERDICT: no red/amber flags')
        for lvl, msg in flags:
            print('%-5s %s' % (lvl, msg))
            if lvl == RED:
                worst = RED
            elif lvl == AMBER and worst == OK:
                worst = AMBER
    if a.csv:
        print('\n'.join(compare_csv(a.csv)))
    print('=' * 78)
    print('OVERALL: %s' % worst)
    return 1 if worst == RED else 0


if __name__ == '__main__':
    sys.exit(main())
