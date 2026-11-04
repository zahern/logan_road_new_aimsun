"""run_buswave_ab.py -- A/B the BUS GREEN-WAVE reward on top of lever 1.

Run INSIDE the Aimsun Python console AFTER A FULL AIMSUN RESTART, KG model open:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_buswave_ab.py").read())

WHY: the chain reward paid the bus premium ONCE (at the final stop line), so the DP
had no reason to time the MIDDLE junctions for the bus -- its actions made bus delay
WORSE (16->19.7). BUS_CHAIN_CREDIT pays the ~40-pax premium at EACH junction the bus
clears on green (a bus green-wave), built from SLACK green (lever 1) so cars aren't hit.
"Act iteratively on top of DSW to push bus throughput, which lowers system delay."

  CHAMP_ADAPTIVE_AIMSUN_DSW                       the base to beat (~155, bus 16.1s)
  CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2_SLACK          lever 1 only (slack GE/ER)
  CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2_SLACK_BUSWAVE  lever 1 + per-junction bus credit
  (+ NO_TSP added per seed automatically)

READ IT -- judge on the HONEST metrics, not the inflated objective:
  * bus_delay_per_pax_s  -> does BUSWAVE push it BELOW DSW's 16.1 ? (the real goal)
  * main_delay_hrs       -> stays near DSW's 666 (slack = cars not hurt) ?
  * action mix           -> GE-heavy, 0 INS; BUSWAVE may fire more GE than SLACK
The objective double-counts junction-crossings (obj ~= 3600/AvgPassDelay over
per-junction passages), so a bus green-wave will LOOK large -- trust bus delay +
network ExitFlow/TotalPassDelay to tell if it is real.

Edit SEEDS for more power (defaults to 1 seed for a fast first look).
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

# --- edit freely -----------------------------------------------------------
SEEDS = _os.environ.get("BUSWAVE_SEEDS", "300")
ARMS = _os.environ.get(
    "BUSWAVE_ARMS",
    "CHAMP_ADAPTIVE_AIMSUN_DSW,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2_SLACK,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2_SLACK_BUSWAVE")
OUT = _os.environ.get("BUSWAVE_OUT", "buswave_ab.csv")
# ---------------------------------------------------------------------------

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT

print("=" * 72)
print("BUS GREEN-WAVE A/B  (BELLMAN_CTM_BUS_CHAIN_CREDIT on slack)")
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
print("BUS GREEN-WAVE A/B DONE -- read", _os.path.splitext(OUT)[0] + "_summary.csv")
print("  JUDGE ON: bus_delay_per_pax_s (< DSW 16.1?) + main_delay (~666?), NOT obj")
print("=" * 72)
