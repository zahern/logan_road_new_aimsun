"""run_logan_nash_qlearn_ab.py -- the Nash-vs-DSW + multi-CTM Q-learn stack on LOGAN.

The Logan port of run_nash_qlearn_ab.py. Same Bellman/Nash/qlearn arms (the engine
is shared and already corridor-aware: the channel map, _CORRIDOR_DIR run_config
read and flag propagation all resolve the ACTIVE model), but pinned to the Logan
corridor and writing Logan-specific CSVs so it never clobbers the KG results.

Run INSIDE the Aimsun console AFTER A FULL AIMSUN RESTART, with the LOGAN ROAD
model open (not KG):

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_logan_nash_qlearn_ab.py").read())

WHY LOGAN (vs KG): KG reconfirmed a structural ceiling -- buses already ride the
fixed-time wave (lowest delay at NO_TSP), ~90-95%% of the objective's passengers
are cars, so no bus-priority action can win; the KG isolation A/B showed the clean
Nash arm only *floors* at DSW (+0.2%%), never beats it. Logan is bus-dominated and
genuinely saturated (SUMO: ~92.6%% bus passengers), so real bus-favourable Pareto
actions exist -- this is the corridor where NASH_DSW_TOL and the QLEARN_NASH stack
can actually clear DSW.

ARMS (same definitions as KG; the active model decides the corridor):
  CHAMP_ADAPTIVE_AIMSUN_DSW                      the base to beat (Logan's own DSW)
  CHAMP_ADAPTIVE_DSW_BELLMAN_NASH_DSW           strict Pareto floor (CAR_TOL=0) --
                                                the SAFETY proof: can't do worse
                                                than DSW by construction.
  CHAMP_ADAPTIVE_DSW_BELLMAN_NASH_DSW_TOL       bus-focused (CAR_TOL=4): a big bus
                                                gain may buy a little car cost --
                                                the variant MEANT to win on slack.
  CHAMP_ADAPTIVE_DSW_BELLMAN_MULTICTM_QLEARN    multi-cell CTM (BINS=3) + Dyna
                                                Q-residual (model foresight
                                                corrected by realized reward).
  CHAMP_ADAPTIVE_DSW_BELLMAN_MULTICTM_QLEARN_NASH   full stack: qlearn correction
                                                under the Nash floor (CAR_TOL=4).
  (+ NO_TSP added per seed automatically)

READ IT with the FAIR summarizer:
    python -I summarize_overnight.py logan_nash_qlearn_ab.csv
  * fair_obj / delay_per_pax_s  -> does any arm clear Logan's DSW?
  * bus_delay_per_pax_s         -> below DSW's bus delay? (the Logan win signal)
  * ext/ins/early-red counts    -> NASH_DSW should fire few (floor); the TOL /
                                   QLEARN arms fire more where real wins exist.
  The headline obj is junction-crossing inflated -- trust the FAIR block.

SEEDS: defaults to 3 (300,400,500). The Nash verdict on Logan needs several seeds
-- SUMO quantified objective fragility at ~+-165 delay-h per action, so a 1-seed
result is inside the noise. For a quick smoke test set LOGANNQ_SEEDS="300"; for a
strong result bump to "300,400,500,600,700". Qlearn also learns online within a
run, so more seeds also let the learned residual show signal.
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

SEEDS = _os.environ.get("LOGANNQ_SEEDS", "300,400,500")
ARMS = _os.environ.get(
    "LOGANNQ_ARMS",
    # 2026-10-29 round 2: the first Logan run showed plain MULTICTM_QLEARN floods
    # ~243 commits (+11%) and NASH_DSW_TOL is identical to NASH_DSW (no bus slack to
    # "buy" -- Logan buses are already 7.66s). Dropped both. Kept QLEARN_NASH next to
    # the new _CLEAN so this is a direct before/after: does the CAR_TOL=-8 margin +
    # qlearn damp pull it from +6.4% back to NASH_DSW's +0.5% (do-no-harm)?
    "CHAMP_ADAPTIVE_AIMSUN_DSW,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_NASH_DSW,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_MULTICTM_QLEARN_NASH,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_MULTICTM_QLEARN_NASH_CLEAN")
OUT = _os.environ.get("LOGANNQ_OUT", "logan_nash_qlearn_ab.csv")

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT
# Pin the suite + driver to Logan -- aborts with a clear message if the KG model
# (or a stale model) is the one actually open.
_os.environ["ARM_SUITE_CORRIDOR"] = "logan_road_new"

print("=" * 72)
print("LOGAN  NASH-vs-DSW + MULTI-CTM Q-LEARN A/B")
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
print("LOGAN NASH+QLEARN A/B DONE -- run: python -I summarize_overnight.py", OUT)
print("  JUDGE: fair_obj vs Logan DSW, bus_delay/pax vs DSW (NOT headline obj).")
print("  NASH_DSW = the floor/safety proof; NASH_DSW_TOL + QLEARN_NASH = the")
print("  arms that can actually WIN on this bus-dominated, saturated corridor.")
print("=" * 72)
