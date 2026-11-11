"""Phase 3 (final) of the flag_liveness repair: load the arms for real.

Phases 1-2 patched the AST-filter loader twice and it kept failing on the next
stub: computed constants, then aliased imports, then os.path.join(None). The
approach itself is the defect -- sweep_arms imports cleanly in ~1s (86 arms),
which is exactly what the runner does.

So _load_arms_module is replaced with an importlib load of the same file. The
function keeps its contract (returns CHAMPION_ARMS). _stub_assign and the AST
machinery are left in place, unused, so nothing else that imports them breaks.

Usage:  python _sumo_port/patch_flag_liveness3.py [--apply]
"""
import io
import os
import shutil
import sys

PATH = r"Z:\tsp\sumo_hpc\flag_liveness.py"
BACKUP = PATH + ".bak_gamesol_20261106_p3"
START = "def _load_arms_module():\n"
END = "\ndef _stub_assign("

NEW = '''def _load_arms_module():
    """Import sweep_arms for real and return its CHAMPION_ARMS list.

    This used to exec a hand-picked subset of the module body, to avoid pulling
    the engine in. That filter never worked on this tree: computed constants
    (_ADAPTIVE_DSW_PORT_RO) became None and blew up ** unpacking, then aliased
    imports (_os) and helper calls went missing -- so the arm audit silently did
    not run and c9compile aborted with one problem it never printed. A real
    import costs about a second and is exactly what the sweep runner does.
    """
    import importlib.util
    d = os.path.dirname(os.path.abspath(ARMS))
    if d not in sys.path:
        sys.path.insert(0, d)
    if 'sweep_arms' in sys.modules:
        return getattr(sys.modules['sweep_arms'], 'CHAMPION_ARMS', None)
    spec = importlib.util.spec_from_file_location('sweep_arms', ARMS)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['sweep_arms'] = mod
    spec.loader.exec_module(mod)
    return getattr(mod, 'CHAMPION_ARMS', None)
'''


def main():
    apply = "--apply" in sys.argv
    text = io.open(PATH, encoding="utf-8", newline="").read()
    i = text.find(START)
    j = text.find(END, i)
    if i < 0 or j < 0 or text.count(START) != 1:
        print("REFUSING: could not isolate _load_arms_module (i=%d j=%d)" % (i, j))
        return 1
    old = text[i:j + 1]
    out = text[:i] + NEW + text[j + 1:]
    print("replacing %d chars of loader with %d chars" % (len(old), len(NEW)))
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
