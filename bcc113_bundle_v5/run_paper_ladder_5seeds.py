"""run_paper_ladder_5seeds.py -- the five-method paper ladder on the DSW base.

Run INSIDE the Aimsun console AFTER A FULL RESTART with the target model open:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_paper_ladder_5seeds.py").read())

Methods (all on the SAME adaptive DSW base; NO_TSP is added per seed by the
suite, so the table is always complete):

  NO_TSP                          fixed-time baseline
  CHAMP_ADAPTIVE_AIMSUN_DSW       adaptive plan + PBIL pressure, no bus priority
  CHAMP_ADAPTIVE_DSW_MARL_BUS     learned bus-weighted priority
  CHAMP_ADAPTIVE_DSW_CELLQ_GATED  admission-controlled CellQLearn priority
  CHAMP_ADAPTIVE_DSW_GAME_BUS     Nash / GAME bus priority

Seeds 300-700 (5 eval). Learners pre-train on 800-1100 through the suite.

KG is the default. For Logan, set PAPER_LADDER_CORRIDOR=logan_road_new (the
suite then writes paper_ladder_5seeds_logan.csv by default if you also set
PAPER_LADDER_OUT). Deliberately NOT in the ladder: CHAMP_ADAPTIVE_DSW_TSP /
H10_TSP (permissive rule priority, +13.3% / +21.8% on KG).
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

SEEDS = _os.environ.get("PAPER_LADDER_SEEDS", "300,400,500,600,700")
ARMS = _os.environ.get(
    "PAPER_LADDER_ARMS",
    "CHAMP_ADAPTIVE_AIMSUN_DSW,"
    "CHAMP_ADAPTIVE_DSW_MARL_BUS,"
    "CHAMP_ADAPTIVE_DSW_CELLQ_GATED,"
    "CHAMP_ADAPTIVE_DSW_GAME_BUS")
CORR = _os.environ.get("PAPER_LADDER_CORRIDOR", "kg")
OUT = _os.environ.get(
    "PAPER_LADDER_OUT",
    "paper_ladder_5seeds_logan.csv" if CORR == "logan_road_new"
    else "paper_ladder_5seeds.csv")

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT
_os.environ["ARM_SUITE_CORRIDOR"] = CORR

print("=" * 72)
print("PAPER LADDER -- NO_TSP + %d methods x %d eval seeds"
      % (len(ARMS.split(",")), len(SEEDS.split(","))))
print("  corridor:", CORR)
print("  arms    :", ARMS)
print("  seeds   :", SEEDS)
print("  out     :", _os.path.join(_HERE, OUT))
print("  methods : NO_TSP | DSW | MARL-Bus | Gated-CellQ | GAME-Bus")
print("  (learners train on 800-1100 via the suite, then freeze)")
print("=" * 72)

_runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
     {"__name__": "__main__"})

print("=" * 72)
print("PAPER LADDER DONE --", OUT)
print("  read: python -I summarize_overnight.py", OUT)
print("=" * 72)
