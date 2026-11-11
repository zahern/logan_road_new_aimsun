"""Fix the LIGHTSIM_MP dispatch: game layer first, MaxPressure as the fallback.

The first patch wired the branch to check_bus_priority(), which does NOT contain
the GAME_SOLUTION / NASH evaluation -- that lives in run_reward_tsp() (its
_run_reward_tsp_evaluate calls).  So as shipped, LIGHTSIM_MP ran the base plan
plus plain bus priority, not "LightSim base + game-theory TSP flavour".

This patch:
  1. replaces the dispatch body with run_reward_tsp() followed by the
     MaxPressure base plan only when no grant was issued in the last second
  2. corrects run_lightsim_mp's docstring to match

Idempotent: aborts if the old text is not found exactly once.

Run:  python patch_engine_lightsim_mp_dispatch.py
"""
from __future__ import annotations

import os
import shutil
import sys

from patch_engine_lightsim_mp import TARGET, sub

BACKUP = TARGET + ".pre_dispatch_fix.bak"

OLD_DISPATCH = '''            elif CONTROL_MODE == "LIGHTSIM_MP":
                # BASE PLAN = LightSim MaxPressure; TSP/game layer on top:
                # check_bus_priority runs FIRST so a grant always overrides the
                # base plan, which only fills ticks where the game layer stood
                # down.  This is the "LightSim controller + TSP flavour" stack.
                tsp_active = self.check_bus_priority(time, timeSta, acycle)
                if not tsp_active:
                    self.run_lightsim_mp(time, timeSta, acycle)
                self.restore_phase_if_needed(time, timeSta, acycle)'''

NEW_DISPATCH = '''            elif CONTROL_MODE == "LIGHTSIM_MP":
                # BASE PLAN = LightSim MaxPressure; TSP + GAME_SOLUTION on top.
                # run_reward_tsp() IS the game layer (its _run_reward_tsp_evaluate
                # calls carry the GAME_SOLUTION / NASH / utilitarian arbitration),
                # so it runs first and always wins.  The MaxPressure base plan
                # only sets the stage on ticks where no grant was issued, which
                # is the "LightSim controller + TSP flavour" stack this mode is
                # for.  apply_action's MIN_GREEN additionally protects a fresh
                # grant for 5 s even if a later tick reaches the base plan.
                self.run_reward_tsp(time, timeSta, acycle)
                _grant_age = float(time) - float(
                    getattr(self, 'last_tsp_action_time', -1e9) or -1e9)
                if _grant_age > 1.0:
                    self.run_lightsim_mp(time, timeSta, acycle)
                self.restore_phase_if_needed(time, timeSta, acycle)'''

OLD_DOC = '''        The CONTROL_MODE == "LIGHTSIM_MP" dispatch calls check_bus_priority
        (the GAME_SOLUTION / NASH / utilitarian layer) FIRST and only reaches
        this method when that layer declined to act on the tick, so every TSP
        grant still wins over the base plan.  Ported from'''

NEW_DOC = '''        The CONTROL_MODE == "LIGHTSIM_MP" dispatch runs run_reward_tsp() -- the
        full TSP + GAME_SOLUTION (NASH / utilitarian) layer -- first, then calls
        this method only when no grant was issued within the last second, so a
        grant always wins over the base plan.  Ported from'''


def main():
    with open(TARGET, "rb") as fh:
        data = fh.read()
    print("patching %s (%.1f MB)" % (TARGET, len(data) / 1e6))
    data = sub(data, OLD_DISPATCH, NEW_DISPATCH, 1, "dispatch -> run_reward_tsp")
    data = sub(data, OLD_DOC, NEW_DOC, 1, "method docstring")
    if not os.path.exists(BACKUP):
        shutil.copy2(TARGET, BACKUP)
        print("backup -> %s" % BACKUP)
    with open(TARGET, "wb") as fh:
        fh.write(data)
    print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
