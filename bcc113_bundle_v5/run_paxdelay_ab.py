"""run_paxdelay_ab.py -- A/B passenger-weighted delay on the bus-wave DP.

Run INSIDE the Aimsun Python console AFTER A FULL AIMSUN RESTART, KG model open:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_paxdelay_ab.py").read())

WHY (operator: "buses have lots more passengers -> cut system delay"): the DP reward
credited the bus 40x on THROUGHPUT but penalized the queue in VEHICLES (a queued bus = 1,
not 40). BELLMAN_CTM_PAX_DELAY prices the queue in PAX and charges the bus's WAIT at
~40 pax/s until it clears, so the solver trades a little car delay for a lot of bus-pax
delay -- and the heavier queue penalty tends to pick FEWER, bus-targeted actions.

  CHAMP_ADAPTIVE_AIMSUN_DSW                              the base to beat (~155, bus 16.1)
  CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2_SLACK_BUSWAVE         slack + bus-wave (pax-delay OFF)
  CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2_SLACK_BUSWAVE_PAXDELAY  + pax-weighted delay
  (+ NO_TSP added per seed automatically)

READ IT with the FAIR summarizer (python -I summarize_overnight.py paxdelay_ab.csv):
  * fair_obj / delay_per_pax_s -> does PAXDELAY beat DSW's 17.9 / 201s ? (the real test)
  * bus_delay_per_pax_s        -> below DSW's 16.1 ?
  * action count (GE/ER)       -> fewer than BUSWAVE's ~75 ? (pax penalty = conservative)
The headline obj is junction-crossing inflated -- trust the fair block.

Edit SEEDS for more power (defaults to 1 seed for a fast first look).
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

# --- edit freely -----------------------------------------------------------
SEEDS = _os.environ.get("PAXDELAY_SEEDS", "300")
ARMS = _os.environ.get(
    "PAXDELAY_ARMS",
    "CHAMP_ADAPTIVE_AIMSUN_DSW,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2_SLACK_BUSWAVE,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2_SLACK_BUSWAVE_PAXDELAY")
OUT = _os.environ.get("PAXDELAY_OUT", "paxdelay_ab.csv")
# ---------------------------------------------------------------------------

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT

print("=" * 72)
print("PAX-DELAY A/B  (BELLMAN_CTM_PAX_DELAY on the bus-wave DP)")
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
print("PAX-DELAY A/B DONE -- run: python -I summarize_overnight.py", OUT)
print("  JUDGE: fair_obj vs DSW 17.9, bus_delay/pax vs DSW 16.1 (NOT headline obj)")
print("=" * 72)
