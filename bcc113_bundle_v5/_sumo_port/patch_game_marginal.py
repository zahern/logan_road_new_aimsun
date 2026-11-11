#!/usr/bin/env python
"""Port the GAME-side marginal-competitor fix to the SUMO authority bundle.

Why this patch exists
---------------------
The first SUMO port put SIDE_COST_MARGINAL_COMPETITOR on
`_compute_side_delay_penalty` / `_ctm_cross_cost_paxs` in engine.py.  Those are
NOT the decision path for the GAME_SOL + CTM2_SPILL arms: their payoffs come
from `_game_ctm2_payoffs` -> `ctm_twoclass.game_payoffs()`, which computes the
cross cost itself as

    cc = sum(base[s].car_delay_vs - o[s].car_delay_vs for s in o
             if s not in main_secs) * car_occ

i.e. SUMMED over every non-main ("competing") approach.  The flag therefore
gated dead code for this family and the A/B came out null.

This mirrors the Aimsun build 2026-11-11T0100-game-ctm2-marginal-competitor:
when the flag is on, group the per-section saved pax.s by the competing PHASE
each section feeds and charge the single WORST phase instead of the sum.
Benefit B is unchanged; only the cost bar C drops sum -> worst.

Idempotent.  .bak per file.  Compile gate before the write is kept.
"""
from __future__ import annotations

import argparse
import os
import py_compile
import shutil
import sys
import time

BUNDLE = os.environ.get("TSP_BUNDLE_AUTHORITY", r"Z:\tsp\sumo_hpc")
CTG = os.path.join(BUNDLE, "shared_tsp_engine", "ctm_twoclass.py")
ENG = os.path.join(BUNDLE, "shared_tsp_engine", "engine.py")

STAMP = time.strftime("%Y%m%d_%H%M%S")
MARK = "GAME_MARGINAL_SUMO"

# ---------------------------------------------------------------- ctm_twoclass
SIG_OLD = "                 bus_occ=40.0, car_occ=1.2, lead=0.0, cross_mult=1.0):\n"
SIG_NEW = (
    "                 bus_occ=40.0, car_occ=1.2, lead=0.0, cross_mult=1.0,\n"
    "                 marginal=False):\n"
)

DIAG_OLD = "def game_payoffs(sec_snap, ring, cur, rem, greens, bus_phase, actions,\n"
DIAG_NEW = (
    "# GAME_MARGINAL_SUMO: diag for the marginal-competitor cost.  Reports how\n"
    "# often more than one competing phase carries loss, i.e. how often\n"
    "# max != sum on this corridor.  Only ever touched when the flag is on.\n"
    '_MARG_DIAG = {"calls": 0, "multi": 0, "maxph": 0, "gap": 0.0}\n'
    "\n"
    "\n"
    "def _marg_diag_note(nph, worst_saved, cc):\n"
    "    d = _MARG_DIAG\n"
    '    d["calls"] += 1\n'
    "    if nph > 1:\n"
    '        d["multi"] += 1\n'
    '    if nph > d["maxph"]:\n'
    '        d["maxph"] = nph\n'
    '    d["gap"] += (cc - worst_saved)\n'
    '    if d["calls"] % 25 == 1:\n'
    '        print("[GAME_MARGINAL] calls=%d multi_phase=%d max_phases=%d "\n'
    '              "worst_vs_sum=%+.1f pax.s"\n'
    '              % (d["calls"], d["multi"], d["maxph"], d["gap"]), flush=True)\n'
    "\n"
    "\n" + DIAG_OLD
)

CC_OLD = (
    "        cc = sum(base[s].car_delay_vs - o[s].car_delay_vs for s in o if s not in main_secs) \\\n"
    "            * float(car_occ)\n"
    "        B = b + cm + max(0.0, cc)\n"
    "        res.append((B, max(0.0, -cc) * cross_mult, b))\n"
)

CC_NEW = (
    "        # GAME_MARGINAL_SUMO: per non-main section, car pax.s SAVED by the\n"
    "        # action (negative = the action costs that competing approach).\n"
    "        _cross = [(s, (base[s].car_delay_vs - o[s].car_delay_vs) * float(car_occ))\n"
    "                  for s in o if s not in main_secs]\n"
    "        cc = 0.0\n"
    "        for _s, _d in _cross:\n"
    "            cc += _d\n"
    "        if marginal:\n"
    "            # MARGINAL-COMPETITOR COST (SIDE_COST_MARGINAL_COMPETITOR): on a\n"
    "            # fixed-cycle coordinated plan the bus hold displaces ONE\n"
    "            # competing phase, not all of them at once, so the opportunity\n"
    "            # cost is the single WORST conflicting phase -- not the SUM over\n"
    "            # every non-main approach.  Benefit B is unchanged; only the\n"
    "            # cost bar C drops from sum -> worst single phase.\n"
    "            _loss_by_phase = {}\n"
    "            for _s, _d in _cross:\n"
    "                for _p in sec_snap[_s][3]:\n"
    "                    if int(_p) == int(bus_phase):\n"
    "                        continue\n"
    "                    _loss_by_phase[int(_p)] = _loss_by_phase.get(int(_p), 0.0) + _d\n"
    "            _worst_saved = min(_loss_by_phase.values()) if _loss_by_phase else cc\n"
    "            _marg_diag_note(len(_loss_by_phase), _worst_saved, cc)\n"
    "            C = max(0.0, -_worst_saved) * cross_mult\n"
    "        else:\n"
    "            C = max(0.0, -cc) * cross_mult\n"
    "        B = b + cm + max(0.0, cc)\n"
    "        res.append((B, C, b))\n"
)

# ---------------------------------------------------------------------- engine
ENG_OLD = (
    "            car_occ=float(getattr(self, 'CarOcc', 1.5) or 1.5), lead=_lead,\n"
    "            cross_mult=float(globals().get('GAME_CROSS_STARVE_MULT', 1.0) or 1.0))\n"
)
ENG_NEW = (
    "            car_occ=float(getattr(self, 'CarOcc', 1.5) or 1.5), lead=_lead,\n"
    "            cross_mult=float(globals().get('GAME_CROSS_STARVE_MULT', 1.0) or 1.0),\n"
    "            marginal=bool(globals().get('SIDE_COST_MARGINAL_COMPETITOR', False)))\n"
)

BUILD_OLD = 'ENGINE_BUILD = "2026-11-10T2900-sumo-side-cost-marginal"'
BUILD_NEW = 'ENGINE_BUILD = "2026-11-11T0200-sumo-game-ctm2-marginal"'


def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _apply(path, edits, dry):
    txt = _read(path)
    orig = txt
    for old, new, label in edits:
        n = txt.count(old)
        if n != 1:
            print("  [FAIL] %-22s anchor count = %d (need 1)" % (label, n))
            return None
        txt = txt.replace(old, new, 1)
        print("  [ok]   %-22s anchored" % label)
    if txt == orig:
        print("  [skip] %s unchanged" % os.path.basename(path))
        return orig
    if dry:
        print("  [dry]  would write %d -> %d bytes"
              % (len(orig), len(txt)))
        return txt
    bak = path + ".bak_gamemarg_" + STAMP
    shutil.copy2(path, bak)
    tmp = path + ".tmp_gamemarg"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(txt)
    try:
        py_compile.compile(tmp, doraise=True)
    except Exception as exc:  # noqa: BLE001
        os.remove(tmp)
        print("  [FAIL] compile gate: %s" % exc)
        print("  [keep] original untouched, backup not needed: %s" % bak)
        return None
    os.replace(tmp, path)
    print("  [ok]   wrote %s (%d -> %d bytes); backup %s"
          % (os.path.basename(path), len(orig), len(txt), os.path.basename(bak)))
    return txt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--bundle", default=BUNDLE)
    args = ap.parse_args()

    global CTG, ENG
    CTG = os.path.join(args.bundle, "shared_tsp_engine", "ctm_twoclass.py")
    ENG = os.path.join(args.bundle, "shared_tsp_engine", "engine.py")

    print("bundle: %s" % args.bundle)
    for p in (CTG, ENG):
        if not os.path.isfile(p):
            sys.exit("missing: %s" % p)

    print("\n[1/2] ctm_twoclass.py")
    ctg_txt = _read(CTG)
    if "_MARG_DIAG" in ctg_txt and "if marginal:" in ctg_txt:
        print("  [skip] already patched (%s)" % MARK)
    else:
        if _apply(CTG, [(SIG_OLD, SIG_NEW, "signature marginal="),
                        (DIAG_OLD, DIAG_NEW, "diag block"),
                        (CC_OLD, CC_NEW, "cc -> worst phase")], args.dry_run) is None:
            sys.exit(1)

    print("\n[2/2] engine.py")
    eng_txt = _read(ENG)
    if "marginal=bool(globals().get('SIDE_COST_MARGINAL_COMPETITOR'" in eng_txt:
        print("  [skip] call site already passes marginal=")
    else:
        if _apply(ENG, [(ENG_OLD, ENG_NEW, "game_payoffs call"),
                        (BUILD_OLD, BUILD_NEW, "ENGINE_BUILD")], args.dry_run) is None:
            sys.exit(1)

    if args.dry_run:
        print("\ndry-run complete; nothing written")
        return

    print("\n[verify] compile both files")
    for p in (CTG, ENG):
        try:
            py_compile.compile(p, doraise=True)
            print("  [ok] %s compiles" % os.path.basename(p))
        except Exception as exc:  # noqa: BLE001
            sys.exit("  [FAIL] %s: %s" % (p, exc))

    print("\n[verify] marginal kwarg present")
    import importlib.util
    spec = importlib.util.spec_from_file_location("_ctm2_check", CTG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses needs the module registered
    spec.loader.exec_module(mod)
    import inspect
    sig = inspect.signature(mod.game_payoffs)
    if "marginal" not in sig.parameters:
        sys.exit("  [FAIL] marginal not in signature: %s" % sig)
    print("  [ok] game_payoffs%s" % sig)
    print("  [ok] default marginal=%r (champion stays byte-identical)"
          % sig.parameters["marginal"].default)


if __name__ == "__main__":
    main()
