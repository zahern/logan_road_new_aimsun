"""run_ladder_probe1.py -- one-seed mechanics probe for the fixed ladder.

Run INSIDE the Aimsun console AFTER A FULL RESTART (specialized_modes.py and
champion_search.py changed), with the KG model open:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_ladder_probe1.py").read())

What is being tested (compared with the first ladder run):

  M3 (CELLQ_GATED): the gentle-jitter flags are now OFF for this arm
      (ACTUATED_EXTEND, SCATS_GAP_OUT, SCATS_MAX_OUT, ACT_EXTEND_DONOR,
      CYCLE_CAP_ENABLE). The first run logged 1,322 [ACT EXT] events for
      seed 300 versus 0 on the DSW base; those events, not the 3 admitted
      CellQ actions, were the +22% degradation.
  M2 (MARL_BUS): CPDQL now selects the ACTION TYPE and SOLVES the duration
      in integer seconds: GE on [1, 10] through the shockwave objective
      (BXT_SOLVER='de'), INS on [1, 6] by DE. The old grid {GE 5/10/15,
      INS 10/15/20} is no longer committed; the seed-300 blow-up came from
      six INS_10 actions.
  M3 (CELLQ_GATED): BXT_SOLVER='de' (shockwave + differential evolution),
      GE cap 6 s, INS cap 6 s, and the gentle-jitter flags are OFF for this
      arm. The first run logged 1,322 [ACT EXT] events for seed 300 versus 0
      on the DSW base; those events, not the 3 admitted CellQ actions, were
      the +22% degradation.
  M4 (GAME_BUS): NASH_BUS_WEIGHT is now 1.0 (the inherited value was 0.0),
      so the bargain has bus power and should act more than 2-5 times;
      durations are HS-solved on the integer lattice, not gridded.

Expected: M3 should still act (counted TSP GE/INS, now solved on 1--6 s), but
the uncounted base jitter should disappear. M2 should commit solved 1--10 s GE
and 1--6 s INS without the old 10--20 s insertion blocks. M4 should act more
than 2--5 times. One seed (300) is enough to see which mechanics changed; a
5-seed run follows only if they behave.

Reading the probe: distinguish the two action streams.
  * [ACT EXT]  = the actuated base layer (2 s extend / gap-out). This is the
    removed jitter; it should fall to ~0 for M3.
  * stats_TSP_Extensions / stats_TSP_Insertions = the actual TSP actions. These
    should remain >0 and should show solved 1--6 s values (TSP_AvgExtension_s),
    not clusters at 5/10/15. Zero TSP actions is only correct if no solved
    action has positive net passenger benefit; it is not the target.
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

SEEDS = _os.environ.get("PROBE_SEEDS", "300")
ARMS = _os.environ.get(
    "PROBE_ARMS",
    "CHAMP_ADAPTIVE_AIMSUN_DSW,"
    "CHAMP_ADAPTIVE_DSW_MARL_BUS,"
    "CHAMP_ADAPTIVE_DSW_CELLQ_GATED,"
    "CHAMP_ADAPTIVE_DSW_GAME_BUS")
OUT = _os.environ.get("PROBE_OUT", "paper_ladder_probe1.csv")

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT
_os.environ["ARM_SUITE_CORRIDOR"] = "kg"

print("=" * 72)
print("LADDER MECHANICS PROBE (KG) -- one seed")
print("  seeds:", SEEDS)
print("  arms :", ARMS)
print("  out  :", _os.path.join(_HERE, OUT))
print("  NOTE: requires a FULL Aimsun console restart (specialized_modes changed)")
print("=" * 72)

_runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
     {"__name__": "__main__"})

print("=" * 72)
print("PROBE DONE --", OUT)
print("  inspect DeciderCostVeto / Extensions / Insertions / ACT EXT counts.")
print("=" * 72)
