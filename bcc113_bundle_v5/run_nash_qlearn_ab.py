"""run_nash_qlearn_ab.py -- A/B the Nash-vs-DSW and multi-CTM+Q-learn extensions.

Run INSIDE the Aimsun Python console AFTER A FULL AIMSUN RESTART (build 3187),
once with the KG model open and once with the Logan model open (same arms; the
active model decides the corridor):

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_nash_qlearn_ab.py").read())

WHAT'S NEW (operator: "bellman mixed with game theory, bus focused" + "multi ctm
on top of bellman with qlearn"):

  CHAMP_ADAPTIVE_AIMSUN_DSW                      the base to beat (KG ~fair 17.9, bus 16.1)
  CHAMP_ADAPTIVE_DSW_BELLMAN_NASH_DSW           Bellman + Nash bargain, DSW = disagreement
                                                point, STRICT Pareto floor (CAR_TOL=0,
                                                chain=3). Can NEVER do worse than DSW by
                                                construction -> KG = the safety proof.
  CHAMP_ADAPTIVE_DSW_BELLMAN_NASH_DSW_TOL       same, bus-focused (CAR_TOL=4): a big bus
                                                gain may buy a little car cost -> the
                                                variant meant to WIN on a slack corridor.
  CHAMP_ADAPTIVE_DSW_BELLMAN_MULTICTM_QLEARN    multi-cell CTM (BINS=3) + Dyna Q-residual:
                                                model foresight corrected by realized reward.
  CHAMP_ADAPTIVE_DSW_BELLMAN_MULTICTM_QLEARN_NASH   the full stack: qlearn correction under
                                                the Nash floor.
  (+ NO_TSP added per seed automatically)

READ IT with the FAIR summarizer (python -I summarize_overnight.py nash_qlearn_ab.csv):
  * fair_obj / delay_per_pax_s   -> does any arm clear DSW (KG 17.9 / 201s)?
  * bus_delay_per_pax_s          -> below DSW's 16.1 ?
  * action count (ext/ins)       -> the Nash floor should fire FEW on KG (near-DSW),
                                     more on Logan where real Pareto wins exist.
The headline obj is junction-crossing inflated -- trust the FAIR block.

EXPECTATION (honest):
  * KG: NASH_DSW should land ~= DSW with ~0 regressions (the floor property is the point);
    a WIN is unlikely because buses already ride the fixed-time wave (no slack).
  * Logan: NASH_DSW_TOL and the QLEARN_NASH stack have the best shot -- real saturation,
    buses not on a clean wave, so genuine bus-favourable Pareto actions exist.
  * QLEARN learns online within a run, so 1 seed is a weak test -- bump SEEDS to see it.

Edit SEEDS for more power (defaults to 1 seed for a fast first look).
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

# --- edit freely -----------------------------------------------------------
SEEDS = _os.environ.get("NASHQL_SEEDS", "300")
ARMS = _os.environ.get(
    "NASHQL_ARMS",
    "CHAMP_ADAPTIVE_AIMSUN_DSW,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_NASH_DSW,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_NASH_DSW_TOL,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_MULTICTM_QLEARN,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_MULTICTM_QLEARN_NASH")
OUT = _os.environ.get("NASHQL_OUT", "nash_qlearn_ab.csv")
# ---------------------------------------------------------------------------

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT

print("=" * 72)
print("NASH-vs-DSW + MULTI-CTM Q-LEARN A/B")
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
print("NASH+QLEARN A/B DONE -- run: python -I summarize_overnight.py", OUT)
print("  JUDGE: fair_obj vs DSW (KG 17.9), bus_delay/pax vs DSW 16.1 (NOT headline obj)")
print("  KG = safety proof (NASH_DSW should ~= DSW, 0 regressions);")
print("  Logan = where NASH_DSW_TOL / QLEARN_NASH can actually win.")
print("=" * 72)
