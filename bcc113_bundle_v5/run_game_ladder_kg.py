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
_os.environ.setdefault("FIXED_ARMS", ",".join(
    ["CHAMP_ADAPTIVE_DSW_GAME_BUS", "CHAMP_ADAPTIVE_DSW_GAME_COOP"] + _sol_arms))
_os.environ.setdefault("FIXED_TRAIN_SEEDS", "")          # games do not learn
_os.environ.setdefault("FIXED_OUT", "game_ladder_kg_%s.csv"
                       % _time.strftime("%Y%m%d_%H%M%S"))
_os.environ["FIXED_HERE"] = _HERE

print("=" * 76)
print("GAME LADDER -- KELVIN GROVE")
print("  arms :", _os.environ["FIXED_ARMS"].replace(",", "\n         "))
print("=" * 76)

_launcher = _os.path.join(_HERE, "run_cellq_held_kg.py")
exec(compile(open(_launcher, encoding="utf-8").read(), _launcher, "exec"),
     {"__name__": "__main__", "__file__": _launcher})
