"""_test_ctm_cap_report.py -- the per-run CTM cap log line, tested without Aimsun.

Extracts `_ctm_cap_note` / `_ctm_cap_report` from shared_tsp_engine/engine.py by
AST (engine.py cannot be imported outside Aimsun) and runs them in a stub module
namespace with a captured log_to_file, so the emitted line can be asserted:

  1. a truncated section is counted, with its metres lost and the cells it needs;
  2. an all-fitting corridor logs the ok line with 0 truncations;
  3. the report fires ONCE -- the accumulator is cleared, a second call is silent;
  4. both ApproachGeom construction sites feed the tally, and AAPIInit resets it
     and AAPIFinish reports it (source checks, so a future call site cannot be
     added without the counter noticing).

    python -I _test_ctm_cap_report.py      # exit 0 = PASS
"""
import ast
import os
import sys
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(ROOT, 'shared_tsp_engine', 'engine.py')
WANTED = ('_ctm_cap_note', '_ctm_cap_report')


def _src():
    with open(ENGINE, encoding='utf-8', errors='replace') as fh:
        return fh.read()


def load_helpers():
    """Exec the two helpers into a stub namespace; return (ns, lines)."""
    src = _src()
    tree = ast.parse(src)
    keep = [n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name in WANTED]
    names = {getattr(n, 'name', None) for n in keep}
    if names != set(WANTED):
        raise SystemExit('could not find both helpers in engine.py (found %s)'
                         % sorted(n for n in names if n))
    lines = []
    ns = types.ModuleType('engine_stub')
    ns.log_to_file = lambda msg, force=False: lines.append(msg)
    ns.math = __import__('math')
    ns._note_swallow = lambda tag, exc=None: None
    exec(compile(ast.Module(body=keep, type_ignores=[]), ENGINE, 'exec'),
         ns.__dict__)
    return ns, lines


class Geom(object):
    """Stand-in for ctm_twoclass.ApproachGeom."""

    def __init__(self, length_m, cell_len_m, n_cells):
        self.length_m = length_m
        self.cell_len_m = cell_len_m
        self.n_cells = n_cells


def main():
    fails = 0
    src = _src()
    ns, lines = load_helpers()

    # ---- 1. one truncated section among three --------------------------------
    ns._CTM_CAP_SEEN = {}
    ns.CBQL_CTM_MAX_CELLS = 12
    ns.GAME_CTM2_LIGHTSIM_MAX_CELLS = 12
    ns._ctm_cap_note(21546, Geom(263.2, 11.1, 12))   # needs 24 -> truncated
    ns._ctm_cap_note(21403, Geom(171.7, 11.1, 16))
    ns._ctm_cap_note(9001, Geom(55.0, 11.1, 5))
    lines[:] = []
    ns._ctm_cap_report()
    one = lines[0] if lines else ''
    ok = ('TRUNCATED 1/3' in one and '130.0 m' in one
          and '21546' in one and 'needs 24' in one)
    print('1. truncated run  -> %s' % one)
    print('   counts section, lost metres and required cells: %s'
          % ('ok' if ok else 'FAIL'))
    fails += 0 if ok else 1

    # ---- 2. all-fitting corridor --------------------------------------------
    ns._CTM_CAP_SEEN = {}
    ns.CBQL_CTM_MAX_CELLS = 24
    ns.GAME_CTM2_LIGHTSIM_MAX_CELLS = 24
    ns._ctm_cap_note(21546, Geom(263.2, 11.1, 24))
    ns._ctm_cap_note(9001, Geom(55.0, 11.1, 5))
    lines[:] = []
    ns._ctm_cap_report()
    two = lines[0] if lines else ''
    ok = 'ok: 0/2' in two and 'CBQL_CTM_MAX_CELLS=24' in two
    print('2. all-fitting run -> %s' % two)
    print('   logs 0/N with the cap in force: %s' % ('ok' if ok else 'FAIL'))
    fails += 0 if ok else 1

    # ---- 3. exactly once: the accumulator is cleared -------------------------
    lines[:] = []
    ns._ctm_cap_report()
    ok = not lines
    print('3. second report call emitted %d line(s) -> %s'
          % (len(lines), 'ok (silent)' if ok else 'FAIL'))
    fails += 0 if ok else 1

    # ---- 4. wiring: PLANT geom tallies, chain inherits, init resets ---------
    print('4. wiring in engine.py:')
    n_sites = src.count('_ctm2.ApproachGeom(')
    n_note = src.count('_ctm_cap_note(') - 1          # minus the def itself
    ok = n_sites == 2 and n_note == 1
    print('   %d ApproachGeom site(s), %d tally call(s) -> %s'
          % (n_sites, n_note,
             'ok (plant only; chain is a derived domain)' if ok else 'FAIL'))
    fails += 0 if ok else 1
    ok = 'max_cells=_base.max_cells' in src
    print('   chain geometry inherits the same cap -> %s'
          % ('ok' if ok else 'FAIL'))
    fails += 0 if ok else 1
    ok = "globals()['_CTM_CAP_SEEN'] = {}" in src
    print('   AAPIInit resets the tally per replication -> %s'
          % ('ok' if ok else 'FAIL'))
    fails += 0 if ok else 1
    fin = src.split('def AAPIFinish():', 1)[-1][:2000]
    ok = '_ctm_cap_report()' in fin
    print('   AAPIFinish reports it once -> %s' % ('ok' if ok else 'FAIL'))
    fails += 0 if ok else 1

    print('\n%s (%d failure(s))' % ('PASS' if not fails else 'FAIL', fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
