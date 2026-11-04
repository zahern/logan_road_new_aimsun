"""run_ladder_open_5seeds.py -- full 5-seed run of the permissive OPEN arms.

Run INSIDE the Aimsun console AFTER A FULL RESTART, KG open:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_ladder_open_5seeds.py").read())

Seeds 300--700, M1 + the three OPEN diagnostics:
  CHAMP_ADAPTIVE_AIMSUN_DSW
  CHAMP_ADAPTIVE_DSW_MARL_OPEN
  CHAMP_ADAPTIVE_DSW_CELLQ_OPEN
  CHAMP_ADAPTIVE_DSW_GAME_OPEN
Writes paper_ladder_open_5seeds.csv. These release the cost veto, net gate,
min-gain and epsilon policy so the question "can the mechanism act, and does
acting help?" is answered separately from the gated methods.
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

SEEDS = _os.environ.get("OPEN_SEEDS", "300,400,500,600,700")
ARMS = _os.environ.get(
    "OPEN_ARMS",
    "CHAMP_ADAPTIVE_AIMSUN_DSW,"
    "CHAMP_ADAPTIVE_DSW_MARL_OPEN,"
    "CHAMP_ADAPTIVE_DSW_CELLQ_OPEN,"
    "CHAMP_ADAPTIVE_DSW_GAME_OPEN")
OUT = _os.environ.get("OPEN_OUT", "paper_ladder_open_5seeds.csv")

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT
_os.environ["ARM_SUITE_CORRIDOR"] = "kg"
# True-state matrix cadence: 5 s (default is 30 s).
_os.environ.setdefault("STATS_SECTION_INTERVAL_S", "5")

print("=" * 72)
print("OPEN LADDER -- full 5-seed run")
print("  seeds:", SEEDS)
print("  arms :", ARMS)
print("  out  :", _os.path.join(_HERE, OUT))
print("  (M0 NO_TSP is added automatically by the suite)")
print("  NOTE: full Aimsun console restart required")
print("=" * 72)

_runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
     {"__name__": "__main__"})

print("=" * 72)
print("OPEN LADDER DONE --", OUT)
print("  read: python -I summarize_overnight.py", OUT)
print("=" * 72)
