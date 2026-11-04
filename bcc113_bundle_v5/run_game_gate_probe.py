"""run_game_gate_probe.py -- 1-seed probe for the GAME self-gate fix.

Run INSIDE the Aimsun console AFTER A FULL RESTART (champion_search.py changed):

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_game_gate_probe.py").read())

Runs NO_TSP (auto-added by the suite) + GAME_BUS + GAME_COOP on seed 300 only.
That is the cheapest test of the fix: before it, both game arms committed 0
actions and were vetoed by [SELFGATE] with conflict_cost=6000. After it, at
least one game arm should execute an action and the [SELFGATE] vetoes should
drop to zero (or only fire on genuinely bad candidates).

Override without editing:
    import os
    os.environ["GAME_PROBE_SEEDS"] = "300,400"
    os.environ["GAME_PROBE_ARMS"] = "CHAMP_ADAPTIVE_DSW_GAME_BUS,CHAMP_ADAPTIVE_DSW_GAME_COOP"
    os.environ["GAME_PROBE_OUT"] = "paper_game_gate_probe.csv"
    exec(open(r"...\\run_game_gate_probe.py").read())
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

SEEDS = _os.environ.get("GAME_PROBE_SEEDS", "300")
ARMS = _os.environ.get("GAME_PROBE_ARMS",
                       "CHAMP_ADAPTIVE_DSW_GAME_BUS,"
                       "CHAMP_ADAPTIVE_DSW_GAME_COOP")
OUT = _os.environ.get("GAME_PROBE_OUT", "paper_game_gate_probe.csv")

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT
_os.environ["ARM_SUITE_CORRIDOR"] = "kg"
# 30 s true-state cadence is enough for this probe (faster than 5 s).
_os.environ.setdefault("STATS_SECTION_INTERVAL_S", "30")

print("=" * 72)
print("GAME SELF-GATE PROBE")
print("  seeds:", SEEDS)
print("  arms :", ARMS)
print("  out  :", _os.path.join(_HERE, OUT))
print("  (M0 NO_TSP is added automatically by the suite)")
print("  EXPECT: GAME_BUS/GAME_COOP execute >=1 action and [SELFGATE]")
print("          vetoes drop from 100% to ~0 once DS_COST_IN_REWARD=False.")
print("  NOTE: full Aimsun console restart required")
print("=" * 72)

_runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
     {"__name__": "__main__"})

print("=" * 72)
print("GAME GATE PROBE DONE --", OUT)
print("  check: python check_game_gate.py", OUT)
print("=" * 72)
