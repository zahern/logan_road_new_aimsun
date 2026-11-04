"""run_paper_kg_spillback.py -- re-run the KG PAPER strategies and test whether
the spillback-floor engine fix (SPILLBACK_DIRECT_OCC) helps methods beyond CELLQ.

WHY (2026-11-01): the seed-500 "really bad run" (-21.6%) was NOT the CellQ
overlay -- it was the DSW SPLIT SOLVER bleeding the main corridor because the
spillback floor under-read the main queue at inter 39593 (occ 1.8 veh vs 5.3
true, corr 0.09). That split solver is the shared BASE under every DSW paper
method (M1-M5), so the fix should help more than just CELLQ. This launcher runs
each published paper method in BOTH forms, same build + same seeds, so every
method gets a clean same-build A/B instead of a cross-build comparison to the
older paper_ladder_priority_kg.csv:

  M0 NO_TSP                              (auto baseline, 1 per seed)
  M1 CHAMP_ADAPTIVE_AIMSUN_DSW           adaptive DSW base
     CHAMP_ADAPTIVE_AIMSUN_DSW_SPILL       + spillback fix
  M2 CHAMP_ADAPTIVE_DSW_MARL_BUS         DCTSP MARL on the base
     CHAMP_ADAPTIVE_DSW_MARL_BUS_SPILL     + spillback fix
  M3 CHAMP_ADAPTIVE_DSW_CELLQ_GATED      CellQ learner on the base
     CHAMP_ADAPTIVE_DSW_CELLQ_GATED_SPILL  + spillback fix
  M4 CHAMP_ADAPTIVE_DSW_GAME_BUS         Nash bus-priority game
     CHAMP_ADAPTIVE_DSW_GAME_BUS_SPILL     + spillback fix
  M5 CHAMP_ADAPTIVE_DSW_GAME_COOP        cooperative team game
     CHAMP_ADAPTIVE_DSW_GAME_COOP_SPILL    + spillback fix

The *_SPILL arms are byte-identical clones of their base with ONLY
SPILLBACK_DIRECT_OCC=True added (no rate-limit, no relief), so each pair isolates
the single spillback variable. SCATS arms are intentionally excluded (they break
KG's commissioned coordination -- not part of the six-method paper ladder).

READ THE RESULT per method pair: if <arm>_SPILL beats <arm> on the objective --
especially on the bad seeds where the base starves the main (watch main_delay_hrs
and the [SPILLBACK] inter=39593 log line) -- WITHOUT hurting the good seeds, the
fix generalises and is worth promoting to the base default. If a pair is ~tied,
the fix is neutral for that method (expected where the main never saturates).

COST: 11 arms x N seeds + NO_TSP. The full 5 seeds (300..700) is the paper set
but long; for a first look set FIXED_SEEDS=300,500 (300 is a strong base seed,
500 is the collapse) to see the effect in ~1/2 the runs, then widen.

RUN -- inside the Aimsun console with the KG model open, AFTER A FULL RESTART on
ENGINE_BUILD=2026-11-01T1000-spillback-direct-occ (verify on the [LOAD] line):

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_paper_kg_spillback.py").read())

Then: python -I summarize_overnight.py paper_kg_spillback.csv
(or read paper_kg_spillback_summary.csv -- the per-seed objective_pct_vs_no_tsp
and main_delay_hrs columns are what the A/B turns on).
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

# Paper set is 300,400,500,600,700. Override with FIXED_SEEDS=300,500 for a fast
# first look (strong base seed + the collapse seed).
SEEDS = _os.environ.get("FIXED_SEEDS", "300,400,500,600,700")

# Each published paper method, then its +spillback clone, interleaved so the
# console prints base/fix pairs together.
ARMS = _os.environ.get(
    "FIXED_ARMS",
    "CHAMP_ADAPTIVE_AIMSUN_DSW,CHAMP_ADAPTIVE_AIMSUN_DSW_SPILL,"
    "CHAMP_ADAPTIVE_DSW_MARL_BUS,CHAMP_ADAPTIVE_DSW_MARL_BUS_SPILL,"
    "CHAMP_ADAPTIVE_DSW_CELLQ_GATED,CHAMP_ADAPTIVE_DSW_CELLQ_GATED_SPILL,"
    "CHAMP_ADAPTIVE_DSW_GAME_BUS,CHAMP_ADAPTIVE_DSW_GAME_BUS_SPILL,"
    "CHAMP_ADAPTIVE_DSW_GAME_COOP,CHAMP_ADAPTIVE_DSW_GAME_COOP_SPILL")

CORRIDOR = _os.environ.get("FIXED_CORRIDOR", "kg")
OUT = _os.environ.get("FIXED_OUT", "paper_kg_spillback.csv")

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT
_os.environ["ARM_SUITE_CORRIDOR"] = CORRIDOR
_os.environ.setdefault("STATS_SECTION_INTERVAL_S", "5")

print("=" * 76)
print("KG PAPER STRATEGIES x SPILLBACK A/B")
print("  seeds:", SEEDS)
print("  arms :", ARMS, "(+ auto NO_TSP)")
print("  out  :", _os.path.join(_HERE, OUT))
print("  NOTE: open the KG model; full restart; verify")
print("        ENGINE_BUILD=2026-11-01T1000-spillback-direct-occ on [LOAD]")
print("  CHECK per pair: <arm>_SPILL vs <arm> objective + main_delay_hrs;")
print("        watch [SPILLBACK] inter=39593; car delay must NOT degrade")
print("=" * 76)

_runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
     {"__name__": "__main__"})

print("=" * 76)
print("KG PAPER x SPILLBACK DONE --", OUT)
print("  read: python -I summarize_overnight.py", OUT)
print("  compare each <arm> vs <arm>_SPILL on the SAME seed (same-build A/B)")
print("=" * 76)
