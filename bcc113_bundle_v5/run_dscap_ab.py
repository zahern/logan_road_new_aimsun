"""run_dscap_ab.py -- A/B the DS-feed fix (DS_ARRIVAL_SAT_CAP_X) in isolation.

Run INSIDE the Aimsun Python console AFTER A FULL AIMSUN RESTART, KG model open:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_dscap_ab.py").read())

WHY: the arrival-flow DS term was uncapped, so ds_base hit 41167 pre-clamp and
ds_max rode the 4.99 order-ceil ~27% of ticks (ds-demand-inflation). Build 3183
adds DS_ARRIVAL_SAT_CAP_X (caps arrival demand at mu*lanes*X; 0=off, 1.15=SCATS).
This isolates its effect on BOTH the base plan and the DP arm, same seed:

  CHAMP_ADAPTIVE_AIMSUN_DSW             cap OFF  -- base plan reference
  CHAMP_ADAPTIVE_AIMSUN_DSW_DSCAP      cap 1.15 -- base plan on a PHYSICAL DS feed
  CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2     cap OFF  -- DP arm (pre-arm already OFF)
  CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2_DSCAP cap 1.15 -- DP arm on a physical feed
  (+ NO_TSP added per seed automatically)

READ IT: in the logs, [DS_STATE] base= should drop from ~41167 to physical (<~2)
on the _DSCAP arms, and ds_max should stop riding 4.99. In the summary, watch
whether DSW_DSCAP changes the 155/666 baseline (the base plan was solving on
corrupted DS) and whether CHAIN2_DSCAP improves over CHAIN2.

Separate from the pre-arm smoke on purpose -- one fix per run, each attributable.
Edit SEEDS for more power (defaults to 1 seed for a fast first look).
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

# --- edit freely -----------------------------------------------------------
SEEDS = _os.environ.get("DSCAP_SEEDS", "300")
ARMS = _os.environ.get(
    "DSCAP_ARMS",
    "CHAMP_ADAPTIVE_AIMSUN_DSW,"
    "CHAMP_ADAPTIVE_AIMSUN_DSW_DSCAP,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2_DSCAP")
OUT = _os.environ.get("DSCAP_OUT", "dscap_ab.csv")
# ---------------------------------------------------------------------------

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT

print("=" * 72)
print("DS-CAP A/B  (DS_ARRIVAL_SAT_CAP_X)")
print("  seeds:", SEEDS)
print("  arms :", ARMS)
print("  -> NO_TSP + %d arms x %d seed(s) = %d runs"
      % (len(ARMS.split(",")), len(SEEDS.split(",")),
         (len(ARMS.split(",")) + 1) * len(SEEDS.split(","))))
print("  out  :", _os.path.join(_HERE, OUT))
print("=" * 72)

_runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
     {"__name__": "__main__"})

print("=" * 72)
print("DS-CAP A/B DONE -- read", _os.path.splitext(OUT)[0] + "_summary.csv")
print("  check logs: [DS_STATE] base= should be physical (<~2) on the _DSCAP arms")
print("=" * 72)
