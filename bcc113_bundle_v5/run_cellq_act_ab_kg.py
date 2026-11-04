"""run_cellq_act_ab_kg.py -- KG A/B: the paper CellQ head (CELLQ_GATED) vs the
"act more" variant (CELLQ_ACT), to test whether relaxing the cost gate makes 1 s
GE/EARLY_RED common WITHOUT losing on passenger delay.

WHY (2026-10-31, REVISED): forensics on the first A/B showed the CellQ decider
CHOOSES 9-16 insertions/seed, but the DeciderCostVeto (10-16/seed) + NetPaxDelay
veto kill EVERY one -- the earlier cost-veto/relief tweaks only shifted the kill
from one gate to the next, so GATED==ACT byte-identical and the whole +40% gain
came from the DSW base, not the overlay. The real lever is TSP_RATE_LIMIT_MODE:
  * exempt the FIRST insertion of each cycle from both vetoes (so it fires at all
    on a coordinated main), bounded to 1 INS / intersection / cycle;
  * every other action (GE/ER/...) at most ONCE per phase instance -- the overlay
    must wait for the NEXT phase to act again (operator directive).
The per-cycle/per-phase caps REPLACE the blanket one-cycle cooldown as the car-
cascade guard. SMALL_ACTION_RELIEF_S=1.5 keeps small GE judged on the point cost;
DECIDER_VETO_INCLUDE_MAIN credits the main cars moving WITH the bus phase.
ACT is now REGISTERED in LEARNING_ARMS (else it ran cold -> byte-identical).

SPILLBACK_DIRECT_OCC=True (added 2026-11-01): the seed-500 run was -21.6% /
main delay +28% for BOTH arms identically -- not the overlay, but the DSW split
solver bleeding the main because the spillback floor under-read the main queue
at inter 39593 (occ 1.8 veh vs 5.3 true). This floors the occupancy with the
loop-independent micro-API count + arms the floor per-lane. Enabled on ACT only,
so SEED 500 is a clean A/B vs GATED (where the rate-limit does nothing): if
ACT/500 recovers while GATED/500 stays ~119, the spillback fix is the cause.

ARMS (NO_TSP auto-added by the suite):
  M0 NO_TSP                           (auto baseline, 1 per seed)
  A  CHAMP_ADAPTIVE_DSW_CELLQ_GATED   (paper champion -- UNCHANGED)
  B  CHAMP_ADAPTIVE_DSW_CELLQ_ACT     (act-more variant)

RUN -- inside the Aimsun console with the KG model open, AFTER A FULL RESTART on
ENGINE_BUILD=2026-11-01T1000-spillback-direct-occ (verify on the [LOAD] line):

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_cellq_act_ab_kg.py").read())

Read it: compare stats_TSP_Extensions / stats_TSP_EarlyRed (should rise for the
ACT arm) AND stats_Objective_PaxPerDelayHr / stats_AvgCarPassDelay_s (must NOT
degrade -- the memory warns that loosening gates can cause a car-side cascade).
Default 3 seeds to save time; add 600,700 later via FIXED_SEEDS.
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

SEEDS = _os.environ.get("FIXED_SEEDS", "300,400,500")

ARMS = _os.environ.get(
    "FIXED_ARMS",
    "CHAMP_ADAPTIVE_DSW_CELLQ_GATED,"
    "CHAMP_ADAPTIVE_DSW_CELLQ_ACT")

CORRIDOR = _os.environ.get("FIXED_CORRIDOR", "kg")
OUT = _os.environ.get("FIXED_OUT", "cellq_act_ab_kg.csv")

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT
_os.environ["ARM_SUITE_CORRIDOR"] = CORRIDOR
_os.environ.setdefault("STATS_SECTION_INTERVAL_S", "5")

print("=" * 72)
print("CELLQ ACT-MORE A/B -- KG")
print("  seeds:", SEEDS)
print("  arms :", ARMS, "(+ auto NO_TSP)")
print("  out  :", _os.path.join(_HERE, OUT))
print("  NOTE: open the KG model; full restart; verify")
print("        ENGINE_BUILD=2026-11-01T1000-spillback-direct-occ on [LOAD]")
print("  CHECK: SEED 500 obj should recover for ACT (GATED stays ~119);")
print("         watch [SPILLBACK] firing at inter 39593; car delay must NOT degrade")
print("=" * 72)

_runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
     {"__name__": "__main__"})

print("=" * 72)
print("CELLQ ACT-MORE A/B DONE --", OUT)
print("  read: python -I summarize_overnight.py", OUT)
print("=" * 72)
