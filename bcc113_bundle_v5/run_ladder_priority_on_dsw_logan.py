"""run_ladder_priority_on_dsw_logan.py -- LOGAN ROAD version of the priority
ladder, with the adaptive AIMSUN_DSW base included AS A SCORED ARM, and trimmed
to THREE seeds to save time (run the extra two later).

WHY (2026-10-31): the KG priority run (run_ladder_priority_on_dsw.py) dropped the
standalone AIMSUN_DSW arm because we already had it from the 8-arm run. For Logan
we have NO such companion run, and the paper's six-method table needs the
AIMSUN_DSW (M1) base row from the SAME run on the SAME build -- so here it is a
scored arm, not dropped. The suite still auto-adds one NO_TSP (M0) baseline per
seed, so the full six-method ladder M0--M5 comes out of this single launcher:

    M0  NO_TSP                              (auto baseline, 1 per seed)
    M1a CHAMP_ADAPTIVE_AIMSUN_DSW           (plain base -- the regression)
    M1b CHAMP_ADAPTIVE_AIMSUN_DSW_LOGAN     (tuned base -- the fix)
    M2  CHAMP_ADAPTIVE_DSW_MARL_BUS_LOGAN
    M3  CHAMP_ADAPTIVE_DSW_CELLQ_GATED_LOGAN
    M4  CHAMP_ADAPTIVE_DSW_GAME_BUS_LOGAN
    M5  CHAMP_ADAPTIVE_DSW_GAME_COOP_LOGAN

UPDATE 2026-10-31: the acting arms are now the LOGAN-TUNED variants. The plain
priority arms sit on the untuned DSW base that steals main green at junction
17308 and loses to NO_TSP; the *_LOGAN siblings re-stack the same priority head
on the fixed base (Logan weights + MAIN_KEEP_FRAC 0.97 + 17308 frozen). The run
ALSO needs the schedule-stat fix in logan_road_new/Simulation_Stats.py (restart
required) -- without it schedule_status comes back 'unavailable'.

SEEDS: 300,400,500 only (3). To add the other two later, re-run with
    FIXED_SEEDS=600,700  and merge the CSVs (or just re-run all five).

Writes paper_ladder_priority_logan.csv (SEPARATE from the KG file).

RUN -- inside the Aimsun console with the LOGAN ROAD model open, AFTER A FULL
RESTART on the current engine build:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_ladder_priority_on_dsw_logan.py").read())

Verify on the [LOAD] line that the corridor resolves to logan_road_new and the
ENGINE_BUILD is the one you intend before trusting the numbers. Logan is
near-saturated, so the champion's correct behaviour is often to stand down to
~=NO_TSP; see the recoverability discussion in the paper.
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

# THREE seeds to save time (add 600,700 later via FIXED_SEEDS).
SEEDS = _os.environ.get("FIXED_SEEDS", "300,400,500")

# LOGAN-TUNED LADDER (2026-10-31). The plain priority arms all sit on the
# adaptive DSW split base, which on Logan steals ~31 s/cycle of main green (79%
# at the 300s bottleneck 17308) and LOSES to NO_TSP -- so the earlier plain
# ladder underperformed. Here every acting arm is the LOGAN-tuned variant
# (Logan demand-responsive weights, MAIN_KEEP_FRAC 0.97, junction 17308 frozen);
# plain AIMSUN_DSW is KEPT as the first row so the CSV shows the regression the
# tuning fixes, side by side on the same build/seeds. NO_TSP is added
# automatically by the suite -- do NOT list it.
#   M1a  CHAMP_ADAPTIVE_AIMSUN_DSW          (plain base -- the regression)
#   M1b  CHAMP_ADAPTIVE_AIMSUN_DSW_LOGAN    (tuned base -- the fix)
#   M2   CHAMP_ADAPTIVE_DSW_MARL_BUS_LOGAN
#   M3   CHAMP_ADAPTIVE_DSW_CELLQ_GATED_LOGAN
#   M4   CHAMP_ADAPTIVE_DSW_GAME_BUS_LOGAN
#   M5   CHAMP_ADAPTIVE_DSW_GAME_COOP_LOGAN
# To run ONLY the tuned ladder (drop the plain-base contrast), set FIXED_ARMS
# without CHAMP_ADAPTIVE_AIMSUN_DSW.
ARMS = _os.environ.get(
    "FIXED_ARMS",
    "CHAMP_ADAPTIVE_AIMSUN_DSW,"
    "CHAMP_ADAPTIVE_AIMSUN_DSW_LOGAN,"
    "CHAMP_ADAPTIVE_DSW_MARL_BUS_LOGAN,"
    "CHAMP_ADAPTIVE_DSW_CELLQ_GATED_LOGAN,"
    "CHAMP_ADAPTIVE_DSW_GAME_BUS_LOGAN,"
    "CHAMP_ADAPTIVE_DSW_GAME_COOP_LOGAN")

# NOTE: the suite's corridor guard compares against _cs.CORRIDOR, which resolves
# to the literal 'logan_road_new' for the Logan model -- so this MUST be
# 'logan_road_new', not 'logan', or the run aborts with "wrong corridor open".
CORRIDOR = _os.environ.get("FIXED_CORRIDOR", "logan_road_new")
OUT = _os.environ.get("FIXED_OUT", "paper_ladder_priority_logan.csv")

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT
_os.environ["ARM_SUITE_CORRIDOR"] = CORRIDOR
_os.environ.setdefault("STATS_SECTION_INTERVAL_S", "5")

print("=" * 72)
print("PRIORITY-ON-DSW LADDER -- LOGAN ROAD, 3-seed run")
print("  seeds:", SEEDS)
print("  arms :", ARMS)
print("  out  :", _os.path.join(_HERE, OUT))
print("  (M0 NO_TSP baseline added automatically by the suite)")
print("  (M1 AIMSUN_DSW IS a scored arm here -- Logan has no companion run)")
print("  NOTE: open the LOGAN model; full Aimsun restart; run 600,700 later")
print("=" * 72)

_runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
     {"__name__": "__main__"})

print("=" * 72)
print("PRIORITY-ON-DSW LADDER (LOGAN) DONE --", OUT)
print("  read: python -I summarize_overnight.py", OUT)
print("  add the other seeds later: FIXED_SEEDS=600,700 then merge")
print("=" * 72)
