"""_test_ctmcap_ab_arms.py -- the cap A/B must differ ONLY in the two caps.

Offline, no Aimsun (champion_search.py cannot be imported outside Aimsun, so
this reads it as source):

  1. the two *_CAP12 / *_CAP24 arms exist, are clones of the same base arm, and
     their reward_overrides differ in exactly CBQL_CTM_MAX_CELLS and
     GAME_CTM2_LIGHTSIM_MAX_CELLS (12 vs 24);
  2. no OTHER arm override pins either cap below 24 -- the failure mode that
     silently defeats the setting, because an arm's reward_cfg line is written
     into run_config AFTER the writer's own caps line;
  3. that ordering really holds in both write_run_config implementations.

    python -I _test_ctmcap_ab_arms.py      # exit 0 = PASS
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CS = os.path.join(ROOT, 'champion_search.py')
WRITERS = ('logan_road_new/batch_runner.py', 'kg/batch_runner.py')

CAP = 'CBQL_CTM_MAX_CELLS'
LI_CAP = 'GAME_CTM2_LIGHTSIM_MAX_CELLS'
CAPS = (CAP, LI_CAP)
WANT = 24


def _src(path):
    with open(path, encoding='utf-8-sig') as fh:
        return fh.read()


def _module_consts(tree):
    """Module-level `NAME = "literal"` strings, so NAME + "_CAP12" resolves."""
    out = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            out[node.targets[0].id] = node.value.value
    return out


def _str(node, consts):
    """Resolve a str Constant, a module constant Name, or a + of those."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _str(node.left, consts), _str(node.right, consts)
        if left is not None and right is not None:
            return left + right
    return None


def overrides_calls(tree):
    """[(new_name, base_name, extra_dict)] for resolvable _with_overrides calls."""
    consts = _module_consts(tree)
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == '_with_overrides'
                and len(node.args) >= 3):
            continue
        base = _str(node.args[0], consts)
        new = _str(node.args[1], consts)
        if base is None or new is None:
            continue
        try:
            extra = ast.literal_eval(node.args[2])
        except Exception:
            continue          # **spread / computed dict: not a literal pin
        if isinstance(extra, dict):
            out.append((new, base, extra))
    return out


def main():
    fails = 0

    print('1. cap A/B arms (champion_search.py):')
    calls = overrides_calls(ast.parse(_src(CS)))
    cap_arms = [c for c in calls if any(k in c[2] for k in CAPS)]
    ab = [c for c in cap_arms if c[0].endswith(('_CAP12', '_CAP24'))]
    want_names = {'_CAP12', '_CAP24'}
    got_names = {n[-6:] for n, _b, _e in ab}
    ok = len(ab) == 2 and got_names == want_names
    print('   found %d cap-pinning arm(s); A/B arms: %s'
          % (len(cap_arms), sorted(n for n, _b, _e in ab) or 'NONE'))
    fails += 0 if ok else 1
    if ok:
        (_n12, b12, e12), (_n24, b24, e24) = sorted(ab)
        ok = b12 == b24
        print('   same base arm: %s -> %s' % ('ok' if ok else 'FAIL', b12))
        fails += 0 if ok else 1
        diff = {k for k in set(e12) | set(e24) if e12.get(k) != e24.get(k)}
        ok = diff == set(CAPS)
        print('   keys that differ: %s -> %s' % (sorted(diff), 'ok' if ok else 'FAIL'))
        fails += 0 if ok else 1
        ok = (e12.get(CAP) == 12 and e24.get(CAP) == WANT
              and e12.get(LI_CAP) == 12 and e24.get(LI_CAP) == WANT)
        print('   values: CAP12=%r/%r CAP24=%r/%r -> %s'
              % (e12.get(CAP), e12.get(LI_CAP), e24.get(CAP), e24.get(LI_CAP),
                 'ok' if ok else 'FAIL'))
        fails += 0 if ok else 1
        ok = CAP in e12 and CAP in e24 and LI_CAP in e12 and LI_CAP in e24
        print('   both caps pinned in BOTH arms: %s' % ('ok' if ok else 'FAIL'))
        fails += 0 if ok else 1

    print('\n2. no other arm pins a cap below %d:' % WANT)
    stray = []
    for name, _base, extra in cap_arms:
        if name.endswith('_CAP12'):
            continue                      # the deliberate control
        for k in CAPS:
            if k in extra and extra[k] != WANT:
                stray.append((name, k, extra[k]))
    for name, k, v in stray:
        print('   %s sets %s = %r' % (name, k, v))
    print('   %s' % ('ok (none)' if not stray else 'FAIL'))
    fails += 0 if not stray else 1

    print('\n3. arm override is written AFTER the writer caps line:')
    for rel in WRITERS:
        s = _src(os.path.join(ROOT, rel))
        i = s.find('"%s = ' % CAP)
        j = s.find('for k, v in _rc')
        if j < 0:
            j = s.find('for k, v in _rc_src')
        ok = i > 0 and j > 0 and i < j
        print('   %-32s caps@%d < arm-loop@%d -> %s'
              % (rel, i, j, 'ok' if ok else 'FAIL'))
        fails += 0 if ok else 1

    print('\n%s (%d failure(s))' % ('PASS' if not fails else 'FAIL', fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
