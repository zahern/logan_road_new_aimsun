"""run_ladder_open_probe.py -- permissive probe of the three priority layers.

Run INSIDE the Aimsun console AFTER A FULL RESTART (champion_search.py and
engine.py changed), with the KG model open:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_ladder_open_probe.py").read())

The three OPEN arms deliberately release the admission/suppression layer so the
question "can the mechanism act at all?" is separated from "does the gate admit
it?":

  MARL_OPEN : CPDQL_EPSILON=0.1, MIN_GAIN=0, cost-veto OFF (1e9),
              MODE_DECISION_IS_FINAL=False, warm 120 s.
  CELLQ_OPEN: BXT net-benefit gate OFF, cost-veto OFF (1e9), MIN_GAIN=0,
              jitter OFF, BXT_SOLVER='de', GE/INS caps 6 s, epsilon 0.1,
              MODE_DECISION_IS_FINAL=False, warm 120 s.
  GAME_OPEN : NASH_BUS_WEIGHT=1.0, net gate ~off (1e6), MIN_GAIN=0,
              cost-veto OFF (1e9), MODE_DECISION_IS_FINAL=False, warm 120 s.

They are diagnostics, not the paper methods. If an OPEN arm acts but degrades,
the issue is the proposal; if it acts and helps, the gate/tuning is the issue.
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

SEEDS = _os.environ.get("OPEN_SEEDS", "300")
ARMS = _os.environ.get(
    "OPEN_ARMS",
    "CHAMP_ADAPTIVE_AIMSUN_DSW,"
    "CHAMP_ADAPTIVE_DSW_MARL_OPEN,"
    "CHAMP_ADAPTIVE_DSW_CELLQ_OPEN,"
    "CHAMP_ADAPTIVE_DSW_GAME_OPEN")
OUT = _os.environ.get("OPEN_OUT", "paper_ladder_open_probe.csv")

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT
_os.environ["ARM_SUITE_CORRIDOR"] = "kg"

print("=" * 72)
print("LADDER OPEN PROBE (KG) -- release the admission layer")
print("  seeds:", SEEDS)
print("  arms :", ARMS)
print("  out  :", _os.path.join(_HERE, OUT))
print("  NOTE: full Aimsun console restart required (engine/champion_search changed)")
print("=" * 72)

_runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
     {"__name__": "__main__"})

print("=" * 72)
print("OPEN PROBE DONE --", OUT)
print("  read: stats_TSP_Extensions / Insertions, DeciderCostVeto, total delay.")
print("=" * 72)
