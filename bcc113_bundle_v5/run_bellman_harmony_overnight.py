"""run_bellman_harmony_overnight.py -- multi-seed overnight comparison.

Run INSIDE the Aimsun Python console AFTER A FULL AIMSUN RESTART, KG model open:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_bellman_harmony_overnight.py").read())

For EACH seed it runs NO_TSP (baseline) + three arms, so the overnight result is a
paired, same-seed comparison (RULE 3):

  * CHAMP_ADAPTIVE_AIMSUN_DSW          -- the adaptive base (the arm to beat, ~155)
  * CHAMP_ADAPTIVE_DSW_BELLMAN_COUPLED -- coupled DP, FIXED integer grid (GE=10/INS=15)
  * CHAMP_ADAPTIVE_DSW_BELLMAN_HARMONY -- coupled DP, continuous-time Harmony solver
                                          + MIN_GAIN=15 (build 3180 tuning)

5 seeds x (NO_TSP + 3 arms) = 20 runs. executeAction is SYNCHRONOUS on Aimsun 26, so
control returns here only after every run finishes (see sync-execute-baseline-hang).

Output (written next to this file):
  bellman_harmony_overnight.csv           per-(seed,arm) rows
  bellman_harmony_overnight_summary.csv   per-arm summary + paired t-test vs NO_TSP
  arm_suite_bars.png / cycle_time / density heatmap (the suite runner's plots)

Edit SEEDS / ARMS below to taste (more seeds = more power, ~1 run each).
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

# --- edit freely -----------------------------------------------------------
SEEDS = _os.environ.get("OVN_SEEDS", "300,400,500,600,700")
# 2026-10-28 DEPTH x COMMITMENT test (seed-300 smoke verdict: chain=2 was the ONLY
# positive DP arm at +1.7%; chain=1 lost -14%, chain=3 reward-hacked to -26%, so
# CHAIN3 is dropped). Two levers isolated at 5 seeds:
#   HARMONY        = chain 1 (2-junction)   -- depth control
#   CHAIN2         = chain 2 (3-junction)   -- the depth winner from the smoke
#   CHAIN2_NOTRUST = chain 2, TRUST_DP OFF  -- lets the net-benefit gate veto the
#                     DP's corridor-negative actions (the commitment lever)
# Everything else identical (delay_w=0.2, credit-once, max_ext 15, min_gain 3).
# NO_TSP + DSW are the fixed-time and adaptive-base references. NO_TSP added per seed.
ARMS = _os.environ.get(
    "OVN_ARMS",
    "CHAMP_ADAPTIVE_AIMSUN_DSW,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_HARMONY,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2_NOTRUST")
OUT = _os.environ.get("OVN_OUT", "bellman_chain_overnight.csv")
# ---------------------------------------------------------------------------

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT

print("=" * 72)
print("BELLMAN HARMONY OVERNIGHT")
print("  seeds:", SEEDS)
print("  arms :", ARMS)
print("  -> NO_TSP + %d arms x %d seeds = %d runs"
      % (len(ARMS.split(",")), len(SEEDS.split(",")),
         (len(ARMS.split(",")) + 1) * len(SEEDS.split(","))))
print("  out  :", _os.path.join(_HERE, OUT))
print("=" * 72)

_runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
     {"__name__": "__main__"})

print("=" * 72)
print("OVERNIGHT DONE -- read", _os.path.splitext(OUT)[0] + "_summary.csv")
print("=" * 72)
