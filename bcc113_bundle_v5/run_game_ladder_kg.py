"""run_game_ladder_kg.py -- KG: play different GAMES on the same TSP decision.

Runs the paper's two game rungs plus one arm per solution concept from
shared_tsp_engine/tsp_games.py, all paired against NO_TSP on the same seeds:

  M4  CHAMP_ADAPTIVE_DSW_GAME_BUS            Nash bargain + corridor best response
  M5  CHAMP_ADAPTIVE_DSW_GAME_COOP           cooperative (Nash-welfare team) game
      CHAMP_ADAPTIVE_DSW_GAME_EGAL           cooperative, egalitarian (legacy path)
      CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH       Nash bargaining, local (new solver)
      CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL       cooperative, utilitarian
      CHAMP_ADAPTIVE_DSW_GAME_SOL_NWELF      cooperative, Nash welfare
      CHAMP_ADAPTIVE_DSW_GAME_SOL_EGAL       cooperative, egalitarian
      CHAMP_ADAPTIVE_DSW_GAME_SOL_KS         Kalai-Smorodinsky bargaining
      CHAMP_ADAPTIVE_DSW_GAME_SOL_STACKBUS   Stackelberg, bus leads
      CHAMP_ADAPTIVE_DSW_GAME_SOL_STACKCAR   Stackelberg, cars lead
      CHAMP_ADAPTIVE_DSW_GAME_SOL_NONCOOP    non-cooperative request/allowance eq.

The GAME_SOL_* arms are GAME_COOP with only GAME_SOLUTION changed, so their
differences are the game. Each also has a *_CTM2 twin deciding on two-class
(bus / car) CTM payoffs (GAME_PAYOFF_MODEL='ctm2'). GAME_LADDER_PAYOFF picks
ctm2 (default: M4, M5 + 8 CTM2 games), legacy, or both. Games do not learn:
no training seeds.

RUN -- in the Aimsun console with the KG model open, after a FULL restart:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_game_ladder_kg.py").read())

11 arms x 3 seeds + NO_TSP ~ 36 runs (~8 h). For a first look set FIXED_ARMS
to a few arms, e.g.
    import os; os.environ["FIXED_ARMS"] = ("CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH,"
        "CHAMP_ADAPTIVE_DSW_GAME_SOL_KS,CHAMP_ADAPTIVE_DSW_GAME_SOL_STACKBUS")
Afterwards:
    python -I diagnose_run_log.py --all --csv <the CSV printed at DONE>
"""
import os as _os
import time as _time

_HERE = _os.environ.get("FIXED_HERE", "").strip()
if not _HERE:
    try:
        _HERE = _os.path.dirname(_os.path.abspath(__file__))
        if not _os.path.isdir(_os.path.join(_HERE, "shared_tsp_engine")):
            raise NameError
    except NameError:
        _HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

_SOL = ["NASH", "UTIL", "NWELF", "EGAL", "KS", "STACKBUS", "STACKCAR", "NONCOOP"]
# GAME_LADDER_PAYOFF: which payoff model the GAME_SOL arms decide on --
#   ctm2   (default) two-class bus/car CTM for every payoff term
#   legacy analytic bus/mainline benefit + Daganzo CTM cross cost
#   both   each game twice, to separate the payoff model from the game
_PAY = _os.environ.get("GAME_LADDER_PAYOFF", "ctm2").strip().lower()
_sol_arms = []
if _PAY in ("legacy", "both"):
    _sol_arms += ["CHAMP_ADAPTIVE_DSW_GAME_SOL_" + k for k in _SOL]
if _PAY in ("ctm2", "both"):
    _sol_arms += ["CHAMP_ADAPTIVE_DSW_GAME_SOL_%s_CTM2" % k for k in _SOL]
    # control: same pipeline, the game never acts (game arm - NULL = game effect)
    _sol_arms += ["CHAMP_ADAPTIVE_DSW_GAME_SOL_NULL_CTM2"]
# ── stale-knob guard ────────────────────────────────────────────────────────
# FIXED_ARMS / FIXED_OUT are CALLER knobs and os.environ lives for the whole
# Aimsun process, so exec'ing a DIFFERENT launcher in the same session leaves
# its arm list and output name behind; a bare setdefault() then silently reuses
# them (measured: a ladder run inherited the CELLQ arms and wrote to
# cellq_held_kg.csv). Each launcher stamps the env with its own name, and a
# value left by a DIFFERENT launcher is discarded. An explicit value in a clean
# session -- or a re-run of this same launcher -- is still honoured.
_ENV_OWNER = "FIXED_ENV_OWNER"
_MY_NAME = "run_game_ladder_kg.py"
_prev_owner = _os.environ.get(_ENV_OWNER, "").strip()
_foreign = bool(_prev_owner) and _prev_owner != _MY_NAME


def _knob(key, default):
    """The caller's value, unless a DIFFERENT launcher left it in the env."""
    _v = (_os.environ.get(key, "") or "").strip()
    if not _v or not _foreign:
        return _v or default
    _shown = ("%d arms" % len(_v.split(","))) if key == "FIXED_ARMS" else _v
    print("[ENV] %s = %s was left by %s -- DISCARDED, this launcher's value wins"
          % (key, _shown, _prev_owner))
    _os.environ.pop(key, None)   # gone from the env, so a re-run cannot revive it
    return default


_os.environ["FIXED_ARMS"] = _knob("FIXED_ARMS", ",".join(
    ["CHAMP_ADAPTIVE_DSW_GAME_BUS", "CHAMP_ADAPTIVE_DSW_GAME_COOP"] + _sol_arms))
_os.environ["FIXED_OUT"] = _knob(
    "FIXED_OUT", "game_ladder_kg_%s.csv" % _time.strftime("%Y%m%d_%H%M%S"))
_os.environ[_ENV_OWNER] = _MY_NAME
_os.environ.setdefault("FIXED_TRAIN_SEEDS", "")          # games do not learn
_os.environ["FIXED_HERE"] = _HERE

print("=" * 76)
print("GAME LADDER -- KELVIN GROVE")
print("  arms :", _os.environ["FIXED_ARMS"].replace(",", "\n         "))
print("=" * 76)

_launcher = _os.path.join(_HERE, "run_cellq_held_kg.py")
# Hand the env to the delegate: the knobs set above are this launcher's, so the
# delegate must keep them rather than treat them as a foreign leftover.
_os.environ[_ENV_OWNER] = "run_cellq_held_kg.py"
try:
    exec(compile(open(_launcher, encoding="utf-8").read(), _launcher, "exec"),
         {"__name__": "__main__", "__file__": _launcher})
finally:
    # Reclaim, so the NEXT launcher in this session sees a foreign owner.
    _os.environ[_ENV_OWNER] = _MY_NAME
