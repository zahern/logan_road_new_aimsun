"""Phase 2 of the flag_liveness loader repair.

Phase 1 taught the loader to stub dict-unpacked names as {} instead of None.
The arms then loaded far enough to hit the next gap: sweep_arms uses aliased
stdlib imports (`import os as _os`) and helper functions inside its arm
literals, but the AST filter kept ONLY _merge / CHAMPION_* / literal UPPERCASE
assignments -- so every import and every helper vanished from the exec
namespace (NameError: _os, then whatever the arms call next).

Kept now: stdlib imports (engine-dragging ones still skipped), all helper defs
(defining one cannot run engine code), and literal assignments of any case.
Everything else keeps the phase-1 treatment: literal -> kept, computed -> stub.

Usage:  python _sumo_port/patch_flag_liveness2.py [--apply]
"""
import io
import os
import shutil
import sys

PATH = r"Z:\tsp\sumo_hpc\flag_liveness.py"
BACKUP = PATH + ".bak_gamesol_20261106_p2"

OLD = """    for node in tree.body:
        nm = None
        if isinstance(node, ast.Assign) and node.targets and isinstance(node.targets[0], ast.Name):
            nm = node.targets[0].id
        elif isinstance(node, ast.FunctionDef):
            nm = node.name
        if nm in ('_merge', 'CHAMPION_ARMS', 'CHAMPION_LEARNING_ARMS'):
            keep.append(node)
        elif nm and nm.isupper():
            try:
                ast.literal_eval(node.value)
                keep.append(node)
            except Exception:
                keep.append(_stub_assign(nm, getattr(node, 'lineno', 1),
                                         as_dict=nm in unpacked))
"""

NEW = """    _ENGINE_MODS = ('shared_tsp_engine', 'engine', 'specialized_modes',
                    'run_sweep_hpc')
    for node in tree.body:
        # Imports travel with the arms unless they would drag the engine in --
        # keeping the arms loadable without the simulation is the whole point.
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                    else [node.module or ''])
            if any((m or '').split('.')[0] in _ENGINE_MODS for m in mods):
                continue
            keep.append(node)
            continue
        # Helper defs are kept whole: defining one cannot execute engine code,
        # and the arm literals call them (_merge and friends).
        if isinstance(node, ast.FunctionDef):
            keep.append(node)
            continue
        nm = (node.targets[0].id
              if isinstance(node, ast.Assign) and node.targets
              and isinstance(node.targets[0], ast.Name) else None)
        if not nm:
            continue
        if nm in ('CHAMPION_ARMS', 'CHAMPION_LEARNING_ARMS'):
            keep.append(node)
            continue
        try:
            ast.literal_eval(node.value)
            keep.append(node)
        except Exception:
            keep.append(_stub_assign(nm, getattr(node, 'lineno', 1),
                                     as_dict=nm in unpacked))
"""


def main():
    apply = "--apply" in sys.argv
    text = io.open(PATH, encoding="utf-8", newline="").read()
    n = text.count(OLD)
    print("anchor matches: %d" % n)
    if n != 1:
        print("REFUSING: anchor is not unique")
        return 1
    out = text.replace(OLD, NEW)
    if not apply:
        print("dry run only; re-run with --apply")
        return 0
    if not os.path.exists(BACKUP):
        shutil.copy2(PATH, BACKUP)
        print("backup ->", BACKUP)
    io.open(PATH, "w", encoding="utf-8", newline="").write(out)
    print("wrote", PATH, "(%+d bytes)" % (len(out) - len(text)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
