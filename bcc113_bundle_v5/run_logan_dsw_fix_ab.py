"""run_logan_dsw_fix_ab.py -- does the Logan-tuned DSW stop losing to NO_TSP?

Focused A/B isolating the adaptive-DSW BASE fix on Logan (separate from the Nash/
qlearn stack so the CSVs don't clash). Run INSIDE the Aimsun console with the LOGAN
ROAD model open:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_logan_dsw_fix_ab.py").read())

WHY: the 3-seed Logan run showed plain CHAMP_ADAPTIVE_AIMSUN_DSW is +1.3% WORSE than
NO_TSP (network exit flow -4.1%). Root cause (plan_evolution + log): the adaptive SPLIT
solver moves -31 s/cycle off the main corridor, 79%% of it at ONE junction -- 17308, a
300s-cycle bottleneck (main 91%% green, ~2900-veh queue) whose main it cut 273->248.5s
and gave to a low-demand side phase, driven by KG-tuned weights (service_gap=3.0
fairness-dominant) loaded on Logan. See logan-dsw-main-green-theft.

ARMS:
  CHAMP_ADAPTIVE_AIMSUN_DSW         the broken base (+1.3% vs NO_TSP, main theft)
  CHAMP_ADAPTIVE_AIMSUN_DSW_LOGAN   three fixes in one: (1) Logan weights file
                                    (service_gap 3.0->0.5, queue 0.3->0.6, ds_max
                                    0.1->0.4, main_share 0.2->0.3 = demand-responsive,
                                    not fairness); (2) MAIN_KEEP_FRAC 0.90->0.97 (cap
                                    main-green cut at ~3%, was 10%); (3) FREEZE junction
                                    17308 (active_intersections = the other 22) so the
                                    bottleneck holds its commissioned fixed-time plan.
  (+ NO_TSP added per seed automatically)

READ: python -I summarize_overnight.py logan_dsw_fix_ab.csv
  WIN = DSW_LOGAN total_delay BELOW NO_TSP and BELOW plain DSW, with network exit flow
  recovered (check stats_Net_ExitFlow_All) and main_delay down. If DSW_LOGAN finally
  beats NO_TSP, the Bellman/Nash stack is worth re-running ON TOP of this fixed base.
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

SEEDS = _os.environ.get("LOGANDSW_SEEDS", "300,400,500")
ARMS = _os.environ.get(
    "LOGANDSW_ARMS",
    "CHAMP_ADAPTIVE_AIMSUN_DSW,"
    "CHAMP_ADAPTIVE_AIMSUN_DSW_LOGAN")
OUT = _os.environ.get("LOGANDSW_OUT", "logan_dsw_fix_ab.csv")

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT
_os.environ["ARM_SUITE_CORRIDOR"] = "logan_road_new"

print("=" * 72)
print("LOGAN DSW-BASE FIX A/B")
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
print("LOGAN DSW-FIX A/B DONE -- run: python -I summarize_overnight.py", OUT)
print("  WIN = DSW_LOGAN total_delay < NO_TSP AND < plain DSW; exit flow recovered.")
print("=" * 72)
