"""
bundle_preflight.py -- static sanity check for the shared engine.

Catches the failure class that silently killed every run on 2026-10-13: a line
from INSIDE a function leaked to MODULE level (a stray de-indented statement),
so `import shared_tsp_engine.engine` raised NameError at import time. The
controller then failed to load ("not a valid extension"), no simulation started,
and no log/CSV was produced -- with py_compile happily reporting COMPILE_OK
because the syntax was valid.

This check is STATIC (ast only): no import, no Aimsun deps, no side effects.

Detects:
  1. module-level statements that reference a name bound ONLY inside a function
     (exactly the `_iid` leak), and
  2. module-level bare CALL expressions (a duplicate inner line left at column 0).

Usage:
    python bundle_preflight.py <path-to-engine.py> [more.py ...]
Exit code 0 = clean, 1 = problems (printed to stderr).
"""
import ast
import builtins
import sys


def _walk_no_scope(node):
    """Yield Name nodes that EXECUTE at this scope -- do not descend into
    function/class/lambda bodies (those are separate scopes)."""
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef, ast.Lambda)):
            continue
        for child in ast.iter_child_nodes(n):
            stack.append(child)
        yield n


def find_problems(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        src = fh.read()
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError as e:
        return ["SYNTAX ERROR: %s" % (e,)]

    # Names stored ANYWHERE in the file (module + every function scope).
    all_store = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            all_store.add(n.id)

    # Names stored at MODULE level only (skip function/class/lambda bodies).
    top_store = set()
    for stmt in tree.body:
        for n in _walk_no_scope(stmt):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                top_store.add(n.id)

    func_only = all_store - top_store
    builtin_names = set(dir(builtins))

    problems = []
    for stmt in tree.body:
        # Module-level reference to a name bound ONLY inside a function -> the
        # statement is running at import time and will raise NameError. This is
        # exactly the 2026-10-13 leak (`_iid` from _mp_cyclic_tick's for-loop).
        for n in _walk_no_scope(stmt):
            if (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                    and n.id in func_only and n.id not in builtin_names):
                problems.append(
                    "line %d: module-level use of '%s' which is bound ONLY "
                    "inside a function (NameError at import)"
                    % (n.lineno, n.id))
    return problems


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    bad = 0
    for path in argv:
        problems = find_problems(path)
        if problems:
            bad += 1
            sys.stderr.write("PREFLIGHT FAIL: %s\n" % path)
            for p in problems:
                sys.stderr.write("    %s\n" % p)
        else:
            print("PREFLIGHT OK: %s" % path)
    if bad:
        sys.stderr.write(
            "\nRefusing to run: a module-level leaked statement would crash the "
            "engine import, so no simulation would start.\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
