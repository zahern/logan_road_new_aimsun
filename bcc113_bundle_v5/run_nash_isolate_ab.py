"""run_nash_isolate_ab.py -- isolate WHY NASH_DSW landed 67h worse than DSW.

Run INSIDE the Aimsun console AFTER A FULL RESTART (build 3188), KG model open:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_nash_isolate_ab.py").read())

The first Nash run: NASH_DSW = 752h vs DSW 686h, only 5 DP extensions, 0 bus benefit,
du_bus CONSTANT 155.2 (BUS_W 4.0 x ~39 pax -> the bargain degenerated to a car-gain
argmax; model under-priced the realized cascade). Two probes resolve it:

  CHAMP_ADAPTIVE_AIMSUN_DSW                the base (686h, fair 17.9, bus 16.1)
  CHAMP_ADAPTIVE_DSW_BELLMAN_NASH_DSW      the 752h result, for reference
  CHAMP_ADAPTIVE_DSW_BELLMAN_NASH_NOACT    decider ON every tick but commits NOTHING
                                           (MIN_GAIN=1e9). ISOLATES the THRU_OPEN
                                           context cost:
                                             ~=686 -> context free, the 5 actions are
                                                      the leak (gate fix can win);
                                             ~=752 -> context (decider+overlay) IS the
                                                      67h; no DP gate can floor at DSW.
  CHAMP_ADAPTIVE_DSW_BELLMAN_NASH_CLEAN    the fix: overlay OFF + BUS_W=1 (real bus
                                           value ~39, not 155) + CAR_TOL=-8 (require a
                                           predicted car SURPLUS, margin vs model
                                           optimism). Should hold at/under DSW.
  (+ NO_TSP added per seed automatically)

READ: python -I summarize_overnight.py nash_isolate_ab.csv
  Compare totdel_h to DSW 685.6 and NOACT. Watch ext/ins counts. Trust the FAIR block.
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

SEEDS = _os.environ.get("NASHISO_SEEDS", "300")
ARMS = _os.environ.get(
    "NASHISO_ARMS",
    "CHAMP_ADAPTIVE_AIMSUN_DSW,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_NASH_DSW,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_NASH_NOACT,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_NASH_CLEAN")
OUT = _os.environ.get("NASHISO_OUT", "nash_isolate_ab.csv")

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT

print("=" * 72)
print("NASH ISOLATION A/B  (context-cost probe + clean fix)")
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
print("NASH ISOLATION DONE -- run: python -I summarize_overnight.py", OUT)
print("  KEY: NOACT ~=686 => context free (fixable); NOACT ~=752 => context is the sink.")
print("=" * 72)
