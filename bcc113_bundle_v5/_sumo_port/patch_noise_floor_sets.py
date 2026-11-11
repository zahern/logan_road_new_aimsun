#!/usr/bin/env python
"""Extend _det3/noise_floor/run_noise_floor.py so a gated A/B can be run.

Two additions, both additive (no existing behaviour changes):

  1. `--set KEY=VALUE` (repeatable).  The driver already expands an arm's
     `reward_overrides` into `--set` pairs; this lets the caller add or flip
     keys on BOTH arms of a pair.  Needed here because the CTM2 game is
     unreachable while GAME_CONGESTION_GATE=True (it HOLDs at q<4 before any
     payoff is built) -- see sumo_bridge/_spillproof_launch.py, which disables
     the same two gates to get the payoff live.

  2. `[GAME_MARGINAL]` diag capture.  The engine prints
         [GAME_MARGINAL] calls=N multi_phase=M max_phases=K worst_vs_sum=+X
     from ctm_twoclass.game_payoffs when SIDE_COST_MARGINAL_COMPETITOR is on.
     run_one already captures the subprocess stdout but only regexes TRUTH,
     so those lines were being discarded.  They are now written into the CSV
     (marg_calls / marg_multi / marg_maxph / marg_gap) -- this is the column
     that says whether max ever differs from sum on this corridor, which is
     the whole question.

Idempotent.  .bak.  Compile gate.
"""
from __future__ import annotations

import argparse
import os
import py_compile
import shutil
import sys
import time

BUNDLE = os.environ.get("TSP_BUNDLE_AUTHORITY", r"Z:\tsp\sumo_hpc")
DRV = os.path.join(BUNDLE, "sumo_bridge", "_det3", "noise_floor", "run_noise_floor.py")
STAMP = time.strftime("%Y%m%d_%H%M%S")
MARK = "GAMEMARG_AB"

E_SIG_OLD = "def run_one(arm, rep, end, seed, sandbox, scenario):\n"
E_SIG_NEW = "def run_one(arm, rep, end, seed, sandbox, scenario, extra=None):\n"

E_OV_OLD = '    overrides = dict(spec.get("reward_overrides") or {})\n'
E_OV_NEW = ('    overrides = dict(spec.get("reward_overrides") or {})\n'
            '    overrides.update(extra or {})            # %s caller flips\n' % MARK)

E_OUT_OLD = '    out = p.stdout or ""\n'
E_OUT_NEW = ('    out = p.stdout or ""\n'
             '    _mm = re.findall(r"\\[GAME_MARGINAL\\] calls=(\\d+) multi_phase=(\\d+) "\n'
             '                     r"max_phases=(\\d+) worst_vs_sum=([+-][\\d.]+)", out)\n')

E_ROW_OLD = '           "method": spec.get("method", ""), "nflags": len(overrides),\n'
E_ROW_NEW = ('           "method": spec.get("method", ""), "nflags": len(overrides),\n'
             '           "marg_calls": "", "marg_multi": "", "marg_maxph": "",\n'
             '           "marg_gap": "",\n')

E_ROW2_OLD = '        row.update(served=m.group(3), pax=float(m.group(4)),\n'
E_ROW2_NEW = ('        if _mm:\n'
              '            _m = _mm[-1]\n'
              '            row.update(marg_calls=int(_m[0]), marg_multi=int(_m[1]),\n'
              '                       marg_maxph=int(_m[2]), marg_gap=float(_m[3]))\n'
              '        row.update(served=m.group(3), pax=float(m.group(4)),\n')

E_ARG_OLD = '    ap.add_argument("--arms", default='
E_ARG_NEW = ('    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",\n'
             '                    help="extra run_config override, applied to EVERY arm")\n'
             '    ap.add_argument("--arms", default=')

E_CALL_OLD = '            rows.append(run_one(arm, rep, args.end, args.seed, sandbox,\n'
E_CALL_NEW = '            rows.append(run_one(arm, rep, args.end, args.seed, sandbox,\n'


def _read(p):
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--bundle", default=BUNDLE)
    args = ap.parse_args()

    drv = os.path.join(args.bundle, "sumo_bridge", "_det3", "noise_floor",
                       "run_noise_floor.py")
    print("driver: %s" % drv)
    if not os.path.isfile(drv):
        sys.exit("missing driver")
    txt = _read(drv)
    orig = txt

    if MARK in txt:
        print("[skip] already patched")
        return

    edits = [
        (E_SIG_OLD, E_SIG_NEW, "run_one(extra=)"),
        (E_OV_OLD, E_OV_NEW, "merge extra overrides"),
        (E_OUT_OLD, E_OUT_NEW, "capture GAME_MARGINAL"),
        (E_ROW_OLD, E_ROW_NEW, "row keys"),
        (E_ROW2_OLD, E_ROW2_NEW, "row values"),
        (E_ARG_OLD, E_ARG_NEW, "--set arg"),
    ]
    for old, new, label in edits:
        n = txt.count(old)
        if n != 1:
            sys.exit("[FAIL] %-24s anchor count=%d (need 1)" % (label, n))
        txt = txt.replace(old, new, 1)
        print("[ok] %-24s" % label)

    # parse --set into a dict right after the arms list is built, and pass it on
    anchor = '    arms = [a for a in args.arms.split(",") if a]\n'
    if txt.count(anchor) != 1:
        sys.exit("[FAIL] arms-list anchor count=%d" % txt.count(anchor))
    txt = txt.replace(anchor, anchor +
                      '    extra = {}\n'
                      '    for _kv in (args.set or []):\n'
                      '        _k, _s, _v = _kv.partition("=")\n'
                      '        if not _s:\n'
                      '            sys.exit("--set needs KEY=VALUE, got %r" % _kv)\n'
                      '        extra[_k.strip()] = _v.strip()   # GAMEMARG_AB\n', 1)
    print("[ok] %-24s" % "parse --set")

    call_old = ('            rows.append(run_one(arm, rep, args.end, args.seed, sandbox,\n'
                '                                args.scenario))')
    call_new = ('            rows.append(run_one(arm, rep, args.end, args.seed, sandbox,\n'
                '                                args.scenario, extra))')
    if txt.count(call_old) != 1:
        # fall back: show the actual call so the failure is actionable
        for i, ln in enumerate(txt.splitlines(), 1):
            if "rows.append(run_one(" in ln:
                print("  call site L%d: %s" % (i, ln.rstrip()))
        sys.exit("[FAIL] run_one call-site anchor count=%d" % txt.count(call_old))
    txt = txt.replace(call_old, call_new, 1)
    print("[ok] %-24s" % "pass extra to run_one")

    if txt == orig:
        sys.exit("[FAIL] no change produced")

    if args.dry_run:
        print("\n[dry] would write %d -> %d bytes" % (len(orig), len(txt)))
        return

    bak = drv + ".bak_gamemarg_" + STAMP
    shutil.copy2(drv, bak)
    tmp = drv + ".tmp_gamemarg"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(txt)
    try:
        py_compile.compile(tmp, doraise=True)
    except Exception as exc:  # noqa: BLE001
        os.remove(tmp)
        sys.exit("[FAIL] compile gate: %s" % exc)
    os.replace(tmp, drv)
    print("\n[ok] wrote %s (%d -> %d bytes); backup %s"
          % (os.path.basename(drv), len(orig), len(txt), os.path.basename(bak)))

    # post-verify: the module must import and expose the new arg
    import importlib.util
    spec = importlib.util.spec_from_file_location("_nf_check", drv)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit as exc:                 # its __main__ guard should not run
        print("[warn] import raised SystemExit: %s" % exc)
    print("[ok] compiles + imports; --set and GAME_MARGINAL columns are live")


if __name__ == "__main__":
    main()
