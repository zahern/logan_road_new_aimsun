"""Repair two defects in flag_liveness.py that made the compile gate fail blind.

Symptom: c9compile exits 3 with one "problem" and no FAIL line anywhere.

Cause 1 -- the arms loader stubs every non-literal UPPERCASE module constant to
    None. _ADAPTIVE_DSW_PORT_RO is a computed dict, so it became None, and the
    CHAMPION_ARMS literal then raised TypeError on {**_ADAPTIVE_DSW_PORT_RO}.
    The arm audit therefore never ran at all on this tree. Names that are
    dict-unpacked must stub to {} instead.
Cause 2 -- struct failures for flags that are not set by an arm are never
    printed (the display loop skips them), so the TypeError above was invisible.

Usage:  python _sumo_port/patch_flag_liveness.py [--apply]
"""
import io
import os
import shutil
import sys

PATH = r"Z:\tsp\sumo_hpc\flag_liveness.py"
BACKUP = PATH + ".bak_gamesol_20261106"

REPLACEMENTS = [
    # 1. compute the set of dict-unpacked names
    (
        "    keep = []\n",
        "    keep = []\n"
        "    # A name unpacked as {**NAME} must stub to a mapping: stubbing it to\n"
        "    # None makes the CHAMPION_ARMS literal raise TypeError instead of\n"
        "    # loading, which is how this loader silently failed on _ADAPTIVE_DSW_PORT_RO.\n"
        "    unpacked = set()\n"
        "    for _d in ast.walk(tree):\n"
        "        if isinstance(_d, ast.Dict):\n"
        "            for _k, _v in zip(_d.keys, _d.values):\n"
        "                if _k is None and isinstance(_v, ast.Name):\n"
        "                    unpacked.add(_v.id)\n",
    ),
    # 2. pass as_dict to the stub
    (
        "                keep.append(_stub_assign(nm, getattr(node, 'lineno', 1)))\n",
        "                keep.append(_stub_assign(nm, getattr(node, 'lineno', 1),\n"
        "                                         as_dict=nm in unpacked))\n",
    ),
    # 3. stub signature + body
    (
        "def _stub_assign(name, lineno):\n"
        '    """A well-formed `NAME = None` module-level assignment.\n',
        "def _stub_assign(name, lineno, as_dict=False):\n"
        '    """A well-formed `NAME = <stub>` module-level assignment.\n'
        "\n"
        "    as_dict is for names unpacked as {**NAME}: None cannot be unpacked,\n"
        "    so those must stub to an empty mapping.\n",
    ),
    (
        "    return ast.parse('%s = None  # stub' % name).body[0]\n",
        "    return ast.parse('%s = %s  # stub'\n"
        "                     % (name, '{}' if as_dict else 'None')).body[0]\n",
    ),
    # 4. surface failures that the arm-set-only display loop hides
    (
        "        print('== FLAG STRUCTURE (only arm-set flags are gated) ==')\n",
        "        print('== FLAG STRUCTURE (only arm-set flags are gated) ==')\n"
        "        for _r in struct:\n"
        "            if _r.get('arm_relevant'):\n"
        "                continue\n"
        "            for _p in (_r.get('errors') or _r.get('problems') or []):\n"
        "                print('  FAIL %-34s %s' % (_r.get('flag', '?'), _p))\n",
    ),
]


def main():
    apply = "--apply" in sys.argv
    text = io.open(PATH, encoding="utf-8", newline="").read()
    out = text
    for i, (old, new) in enumerate(REPLACEMENTS, 1):
        n = out.count(old)
        print("anchor %d: %d match(es)  %r" % (i, n, old.splitlines()[0][:60]))
        if n != 1:
            print("REFUSING: anchor %d is not unique" % i)
            return 1
        out = out.replace(old, new)
    print("all %d anchors matched once" % len(REPLACEMENTS))
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
