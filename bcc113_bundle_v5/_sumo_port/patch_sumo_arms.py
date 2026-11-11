#!/usr/bin/env python3
"""patch_sumo_arms.py -- add the GAME_SOLUTION ladder to the SUMO arm table.

The SUMO fork's `sumo_bridge/sweep_arms.py` has no GAME_SOL_* arms, so the
Aimsun ladder (`champion_search.GAME_SOL_ARMS`) had no SUMO counterpart to
compare against. This appends them, derived from CHAMP_ADAPTIVE_DSW_GAME_COOP
exactly as Aimsun derives them: same DSW base, same payoffs, only
GAME_SOLUTION (plus the cooperative side-payment tolerance) changed.

The _CTM2 twins are deliberately NOT created: GAME_PAYOFF_MODEL='ctm2' needs
_cbql_ctm_geom / _vlt_advance_vph, which this build does not carry, and the
engine logs [GAME_CTM2_NA] before falling back to legacy payoffs.

Idempotent: re-running appends nothing if the arms already exist. Writes a
.bak_gamesol_<stamp> copy of the original file next to it.

    python patch_sumo_arms.py --dry-run
    python patch_sumo_arms.py
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import sys
import time

TARGET = r"Z:\tsp\sumo_hpc\sumo_bridge\sweep_arms.py"
MARK = "# -- GAME SOLUTION-CONCEPT ARMS"

BLOCK = '''

# -- GAME SOLUTION-CONCEPT ARMS (2026-11-06, SUMO port of the Aimsun ladder) --
# Mirrors champion_search.GAME_SOL_ARMS: each arm is CHAMP_ADAPTIVE_DSW_GAME_COOP
# with ONLY the solution concept changed, so a difference between two of these
# arms is attributable to the game played, not to the pipeline underneath.
# The _CTM2 twins are deliberately absent: GAME_PAYOFF_MODEL='ctm2' needs
# _cbql_ctm_geom/_vlt_advance_vph, which this build does not carry (the engine
# logs [GAME_CTM2_NA] and falls back to legacy payoffs).
GAME_SOLUTION_ARMS = [
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH", "nash"),
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL", "utilitarian"),
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_NWELF", "nash_welfare"),
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_EGAL", "egalitarian"),
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_KS", "kalai_smorodinsky"),
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_STACKBUS", "stackelberg_bus"),
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_STACKCAR", "stackelberg_car"),
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_NONCOOP", "noncoop_grant"),
]
for _gname, _gsol in GAME_SOLUTION_ARMS:
    if any(a.get("name") == _gname for a in CHAMPION_ARMS):
        continue
    _gbase = next((a for a in CHAMPION_ARMS
                   if a.get("name") == "CHAMP_ADAPTIVE_DSW_GAME_COOP"), None)
    if _gbase is None:
        break
    _garm = {k: v for k, v in _gbase.items() if k != "reward_overrides"}
    _garm["name"] = _gname
    _garm["reward_overrides"] = dict(
        _gbase.get("reward_overrides") or {},
        GAME_SOLUTION=_gsol, NASH_COOPERATIVE=False,
        GAME_TOL_BUS_FRAC=0.25, GAME_TOL_CAR_FRAC=0.25)
    CHAMPION_ARMS.append(_garm)
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--target", default=TARGET)
    a = ap.parse_args()

    if not os.path.isfile(a.target):
        print("MISSING %s -- is Z: mounted?" % a.target)
        return 2
    src = io.open(a.target, encoding="utf-8", errors="surrogateescape").read()

    if MARK in src:
        print("already patched: GAME_SOLUTION arms present, nothing to do")
        return 0
    # The block references these; fail loudly rather than append dead code.
    for need in ('CHAMPION_ARMS = [', '"CHAMP_ADAPTIVE_DSW_GAME_COOP"'):
        if need not in src:
            print("ANCHOR MISSING %r -- refusing to patch" % need)
            return 3
    if "\nfor _arm in CHAMPION_ARMS:" not in src:
        # the COOP derivation must already have run, else our base is absent
        print("WARNING: COOP derivation loop not found; appending anyway")

    out = src + BLOCK
    # syntax gate before writing anything
    try:
        compile(out, a.target, "exec")
    except SyntaxError as e:
        print("PATCH WOULD NOT COMPILE: %s" % e)
        return 4

    print("target %s: %d -> %d bytes (+%d)"
          % (a.target, len(src), len(out), len(out) - len(src)))
    print("new arms: %d" % sum(1 for l in BLOCK.splitlines()
                               if l.strip().startswith('("CHAMP_ADAPTIVE_DSW_GAME_SOL_')))
    if a.dry_run:
        print("dry run: nothing written")
        return 0

    bak = a.target + ".bak_gamesol_" + time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(a.target, bak)
    io.open(a.target, "w", encoding="utf-8", errors="surrogateescape",
            newline="").write(out)
    print("backup %s" % bak)
    print("written %s" % a.target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
