"""_test_ctm_max_cells_globals.py -- prove both CTM cell caps reach engine globals.

Offline, no Aimsun: exec each corridor's run_config.py, then evaluate the
engine's OWN lookup expressions with globals() bound to a namespace populated
exactly the way AAPIInit populates it -- specialised_modes.MODE_FLAGS membership
(check_flag_propagation.py documents that path as reset+propagate to _spm AND
engine globals).

    python -I _test_ctm_max_cells_globals.py

Exit 0 = both caps resolve to 24 in every corridor, both writers emit them, and
both names are in MODE_FLAGS.
"""
import ast
import os
import sys
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
SPM = os.path.join(ROOT, 'shared_tsp_engine', 'specialized_modes.py')
CORRIDORS = (('Logan', 'logan_road_new'), ('KG', 'kg'))
WRITERS = ('logan_road_new/batch_runner.py', 'kg/batch_runner.py')

CAP = 'CBQL_CTM_MAX_CELLS'
LI_CAP = 'GAME_CTM2_LIGHTSIM_MAX_CELLS'
WANT = 24

# The exact expressions engine.py evaluates (line refs are engine.py's).
EXPR = (
    ('geometry max_cells (24292)', "int(globals().get('%s', 12) or 12)" % CAP),
    ('reach cells        (23656)', "float(globals().get('%s', 12))" % CAP),
    ('lightsim max_cells (19617)', "int(globals().get('%s', 12) or 12)" % LI_CAP),
)


def _src(path):
    with open(path, encoding='utf-8-sig') as fh:
        return fh.read()


def mode_flags():
    tree = ast.parse(_src(SPM))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'MODE_FLAGS'
                        for t in node.targets)
                and isinstance(node.value, ast.List)):
            return {e.value for e in node.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


def main():
    fails = 0
    mf = mode_flags()

    print('propagation tuple (specialized_modes.MODE_FLAGS):')
    for name in (CAP, LI_CAP):
        ok = name in mf
        print('  %-32s %s' % (name, 'present' if ok else 'MISSING'))
        fails += 0 if ok else 1

    for cname, cdir in CORRIDORS:
        path = os.path.join(ROOT, cdir, 'run_config.py')
        ns = types.ModuleType('run_config_' + cdir)
        exec(compile(_src(path), path, 'exec'), ns.__dict__)

        print('\n%s (%s):' % (cname, os.path.join(cdir, 'run_config.py')))
        for name in (CAP, LI_CAP):
            got = ns.__dict__.get(name, '<absent>')
            ok = got == WANT
            print('  %-32s = %-6r %s' % (name, got, 'ok' if ok else 'FAIL'))
            fails += 0 if ok else 1

        # AAPIInit: every MODE_FLAGS key present in run_config is copied into
        # engine globals. Reproduce exactly that, then run engine.py's lookups.
        eng = types.ModuleType('engine_' + cdir)
        for k in mf:
            if k in ns.__dict__:
                eng.__dict__[k] = ns.__dict__[k]
        print('  propagated %d MODE_FLAGS value(s) into the engine namespace'
              % len([k for k in mf if k in ns.__dict__]))
        for label, expr in EXPR:
            got = eval(expr, eng.__dict__)      # globals() == engine namespace
            ok = abs(float(got) - WANT) < 1e-6
            print('    %s -> %-6.1f %s' % (label, got, 'ok' if ok else 'FAIL'))
            fails += 0 if ok else 1
        reach_m = float(eval(EXPR[1][1], eng.__dict__)) * 11.1
        print('    reach at the KG cell length: %.0f m per approach' % reach_m)

    print('\nsurvives a sweep rewrite (write_run_config emits both caps):')
    for rel in WRITERS:
        src = _src(os.path.join(ROOT, rel))
        ok = ('"%s = ' % CAP in src) and ('"%s = ' % LI_CAP in src)
        print('  %-32s %s' % (rel, 'ok' if ok else 'FAIL'))
        fails += 0 if ok else 1

    print('\n%s (%d failure(s))' % ('PASS' if not fails else 'FAIL', fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
