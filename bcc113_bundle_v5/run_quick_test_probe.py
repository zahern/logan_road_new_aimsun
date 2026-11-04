"""run_quick_test_probe.py -- 1-seed test of the cell/game fixes.

Run INSIDE the Aimsun console AFTER A FULL RESTART (engine.py,
specialized_modes.py and champion_search.py changed):

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_quick_test_probe.py").read())

It runs, on seed 300 only:
  NO_TSP (auto-added by the suite)
  CHAMP_ADAPTIVE_DSW_CELLQ_GATED   -> checks [CTM], conn=[...], no solver error
  CHAMP_ADAPTIVE_DSW_GAME_BUS      -> checks DS-balance veto gone, actions > 0
  CHAMP_ADAPTIVE_DSW_GAME_COOP     -> same, cooperative branch

That is ~4 runs (~30-40 min). After it finishes:

    python check_quick_test.py

Then, if the verdict is PASS, run the full ladder:
    exec(open(r"...\\run_ladder_5seeds_fixed.py").read())
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

SEEDS = _os.environ.get("QUICK_SEEDS", "300")
ARMS = _os.environ.get(
    "QUICK_ARMS",
    "CHAMP_ADAPTIVE_DSW_CELLQ_GATED,"
    "CHAMP_ADAPTIVE_DSW_GAME_BUS,"
    "CHAMP_ADAPTIVE_DSW_GAME_COOP")
OUT = _os.environ.get("QUICK_OUT", "paper_quick_test.csv")

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT
_os.environ["ARM_SUITE_CORRIDOR"] = "kg"
_os.environ.setdefault("STATS_SECTION_INTERVAL_S", "30")

print("=" * 72)
print("QUICK CELL/GAME TEST")
print("  seeds:", SEEDS)
print("  arms :", ARMS)
print("  out  :", _os.path.join(_HERE, OUT))
print("  NO_TSP is added automatically by the suite")
print("  EXPECT: [CTM] lines with conn=[...], no solve_bus_phase_green error,")
print("          GAME actions > 0 and DSBalanceVeto ~0.")
print("  NOTE: full Aimsun console restart required")
print("=" * 72)

_runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
     {"__name__": "__main__"})

print("=" * 72)
print("QUICK TEST DONE --", OUT)
print("  check: python check_quick_test.py", OUT)
print("=" * 72)
