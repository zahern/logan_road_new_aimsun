"""Compare two engine runs: payoff decisions (the [GAME_SOLVE] pick) and the
block values the payoff received ([SPILLPAY]).

Usage: python _cmp_models.py A.out B.out LABEL_A LABEL_B
"""
import re
import statistics
import sys

SOLVE = re.compile(r'\[GAME_SOLVE\] inter=(\S+) t=(-?\d+(?:\.\d+)?) .*?pick=(.*)$')
PAY = re.compile(r'\[SPILLPAY\] jct=(\S+) mode=(\w+) n_ph=(\d+) n_pos=(\d+) max=([\d.]+)')
HOLD = re.compile(r'\[GAME_SOLVE\] inter=(\S+) t=(-?\d+(?:\.\d+)?) HOLD\((\w+)\)')


def load(path):
    acts = {}
    holds = {}
    blocks = []
    modes = {}
    for line in open(path, errors='ignore'):
        if '[GAME_SOLVE]' in line:
            m = SOLVE.search(line)
            if m:
                inter = m.group(1)
                t = float(m.group(2))
                act = m.group(3).split(' u_bus=')[0].strip()
                acts[(inter, t)] = act
            m = HOLD.search(line)
            if m:
                holds[(m.group(1), float(m.group(2)))] = m.group(3)
        elif '[SPILLPAY]' in line:
            m = PAY.search(line)
            if m:
                modes[m.group(2)] = modes.get(m.group(2), 0) + 1
                blocks.append((m.group(1), int(m.group(4)) > 0, float(m.group(5))))
    return acts, holds, blocks, modes


def dist(vals):
    if not vals:
        return 'n=0'
    v = sorted(vals)
    n = len(v)
    return ('n=%d mean=%.3f median=%.3f p90=%.3f max=%.3f  at1.0=%d (%.0f%%)'
            % (n, sum(v) / n, v[n // 2], v[min(int(n * 0.9), n - 1)], v[-1],
               sum(1 for x in v if x >= 0.999),
               100.0 * sum(1 for x in v if x >= 0.999) / n))


a_acts, a_holds, a_blocks, a_modes = load(sys.argv[1])
b_acts, b_holds, b_blocks, b_modes = load(sys.argv[2])
la, lb = sys.argv[3], sys.argv[4]

print('=== %s ===' % la)
print('  solve lines      : %d   holds: %d %s' % (len(a_acts), len(a_holds),
                                                  dict((k, list(a_holds.values()).count(k)) for k in set(a_holds.values()))))
print('  payoff modes     : %s' % a_modes)
print('  blocks (n_pos>0) : %s' % dist([x[2] for x in a_blocks]))
print('  blocks positive  : %d / %d' % (sum(1 for x in a_blocks if x[1]), len(a_blocks)))
print('  acted (real pick): %d' % sum(1 for v in a_acts.values() if not v.startswith('NO_ACTION')))
print('=== %s ===' % lb)
print('  solve lines      : %d   holds: %d' % (len(b_acts), len(b_holds)))
print('  payoff modes     : %s' % b_modes)
print('  blocks (n_pos>0) : %s' % dist([x[2] for x in b_blocks]))
print('  blocks positive  : %d / %d' % (sum(1 for x in b_blocks if x[1]), len(b_blocks)))
print('  acted (real pick): %d' % sum(1 for v in b_acts.values() if not v.startswith('NO_ACTION')))

# ---- decision agreement, matched per junction and decision time ----
keys_a = set(a_acts)
keys_b = set(b_acts)
common = keys_a & keys_b
same = sum(1 for k in common if a_acts[k] == b_acts[k])
print('')
print('=== decision agreement (%s vs %s) ===' % (la, lb))
print('  decisions A=%d B=%d  matched (same jct AND same t)=%d' % (len(keys_a), len(keys_b), len(common)))
if common:
    print('  identical pick  : %d / %d  (%.1f%%)' % (same, len(common), 100.0 * same / len(common)))
    print('  both NO_ACTION  : %d' % sum(1 for k in common
                                        if a_acts[k] == 'NO_ACTION' and b_acts[k] == 'NO_ACTION'))

# ---- how often each arm acted at all, per junction ----
def per_jct(acts):
    d = {}
    for (i, _t), v in acts.items():
        d.setdefault(i, [0, 0])
        d[i][0] += 1
        if not v.startswith('NO_ACTION'):
            d[i][1] += 1
    return d


pa, pb = per_jct(a_acts), per_jct(b_acts)
print('')
print('  per junction: solves / acted   (%s | %s)' % (la, lb))
for j in sorted(set(pa) | set(pb), key=lambda x: -max(pa.get(x, [0])[0], pb.get(x, [0])[0])):
    x = pa.get(j, [0, 0])
    y = pb.get(j, [0, 0])
    print('    jct %-9s %3d/%-3d | %3d/%-3d' % (j, x[0], x[1], y[0], y[1]))

if common:
    diffs = [k for k in sorted(common) if a_acts[k] != b_acts[k]]
    print('')
    print('  first 8 disagreements:')
    for k in diffs[:8]:
        print('    jct %-9s t=%-6.0f %s=%s | %s=%s'
              % (k[0], k[1], la, a_acts[k], lb, b_acts[k]))
