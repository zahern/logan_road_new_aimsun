"""run_slack_ab.py -- A/B lever 1: SLACK-ONLY harmony search.

Run INSIDE the Aimsun Python console AFTER A FULL AIMSUN RESTART, KG model open:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_slack_ab.py").read())

WHY: with the pre-arm fixed, acting (CHAIN2, 77 actions -> obj 126.6) still loses to
not-acting (NOTRUST ~= DSW ~155). Lever 1 restricts the harmony search to SLACK-
capturing green extensions -- INS/GREEN_REALLOC dropped (they lengthen the cycle +
shift offsets), GE/ER capped at BELLMAN_CTM_SLACK_EXT_S=8s. This tests whether KG
has bus-friendly slack the DP can take without breaking the green wave.

  CHAMP_ADAPTIVE_AIMSUN_DSW              the adaptive base (the bar to beat, ~155)
  CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2       full 4-action harmony menu (slack OFF)
  CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2_SLACK slack-only GE/ER menu (lever 1)
  (+ NO_TSP added per seed automatically)

READ IT: watch the action mix -- CHAIN2_SLACK should fire 0 INS (only GE/ER) with
smaller durations, main_delay should pull toward DSW's 666h, and the question is
whether obj climbs past CHAIN2's 126.6 toward (or past) DSW's 155. If it still
can't reach DSW, KG has no exploitable bus slack and DSW is the answer.

Edit SEEDS for more power (defaults to 1 seed for a fast first look).
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

# --- edit freely -----------------------------------------------------------
SEEDS = _os.environ.get("SLACK_SEEDS", "300")
ARMS = _os.environ.get(
    "SLACK_ARMS",
    "CHAMP_ADAPTIVE_AIMSUN_DSW,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2_SLACK")
OUT = _os.environ.get("SLACK_OUT", "slack_ab.csv")
# ---------------------------------------------------------------------------

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT

print("=" * 72)
print("SLACK-ONLY A/B  (lever 1: BELLMAN_CTM_SLACK_ONLY)")
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
print("SLACK A/B DONE -- read", _os.path.splitext(OUT)[0] + "_summary.csv")
print("  watch: CHAIN2_SLACK should fire 0 INS; does obj climb toward DSW's ~155?")
print("=" * 72)
