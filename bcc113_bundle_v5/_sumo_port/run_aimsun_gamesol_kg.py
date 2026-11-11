"""run_aimsun_gamesol_kg.py -- the Aimsun half of the game-ladder comparison.

Runs the same arm names the SUMO fork carries, so the two platforms compare
like with like. GAMESOL_PAYOFF picks the set (default: legacy):

  legacy  the nine GAME_SOL arms on the legacy payoff model. SUMO already has
          parts for these (parts/gamesol_*), so that pair can be made today.
  ctm2    the two _CTM2_SPILL2_LIGHTSIM twins (NASH, UTIL): two-class bus/car
          CTM payoffs with the LightSim block term priced in. SUMO has these
          too (parts/ladder_*_eval300..700.csv, five seeds).

The old note here said the _CTM2 twins were excluded "because the SUMO build
cannot score them ([GAME_CTM2_NA])". That stopped being true on 2026-11-09:
the CTM2 rollout, the chain geometry and ctm_lightsim.py were ported into
Z:/tsp/sumo_hpc (ENGINE_BUILD 2026-11-09T1900-sumo-lightsim). Ten HPC jobs
returned Exit_status=0 and their logs carry [LSBLK] block rows, so both twins
have a live SUMO side. GAME_CTM2 reports NA only at the three junctions with
no signal plan.

RUN in the Aimsun console with the KG model open, after a FULL restart
(AGENTS RULE 2 -- Aimsun caches imported modules):

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\_sumo_port\\run_aimsun_gamesol_kg.py").read())

The LightSim twins instead of the legacy nine:

    import os
    os.environ["GAMESOL_PAYOFF"] = "ctm2"
    exec(open(r"...\\_sumo_port\\run_aimsun_gamesol_kg.py").read())

One arm and one seed for a first look (the arm list also decides the payoff,
so a LIGHTSIM arm can never be run on legacy payoffs by accident):

    import os
    os.environ["FIXED_ARMS"] = "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_LIGHTSIM"
    os.environ["FIXED_SEEDS"] = "300"
    exec(open(r"...\\_sumo_port\\run_aimsun_gamesol_kg.py").read())

Then, on Windows:
    legacy  python _sumo_port/compare_game_solution.py
    ctm2    python -I diagnose_run_log.py --all --csv <the CSV printed at DONE>
            (compare_game_solution.py does not list the LIGHTSIM twins yet)
"""
import os as _os
import time as _time

_HERE = _os.environ.get("FIXED_HERE", "").strip()
if not _HERE:
    try:
        _HERE = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    except NameError:
        # exec(open(...).read()) in the Aimsun console defines no __file__.
        _HERE = ""
    if not _HERE or not _os.path.isdir(_os.path.join(_HERE, "shared_tsp_engine")):
        _HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

# Matched arm sets: identical names on both platforms.
_LEGACY_ARMS = [
    "CHAMP_ADAPTIVE_DSW_GAME_COOP",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_NWELF",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_EGAL",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_KS",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_STACKBUS",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_STACKCAR",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_NONCOOP",
]
# SPILL2 + LightSim twins: the arms the SUMO ladder scored on seeds 300-700.
_LIGHTSIM_ARMS = [
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_LIGHTSIM",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2_LIGHTSIM",
]

# -- stale-knob guard (same contract as the launchers) -----------------------
# os.environ lives for the whole Aimsun process, so exec'ing a different
# launcher first leaves its FIXED_ARMS / FIXED_OUT behind. Drop anything a
# different launcher owns; the values written below are ours and survive a
# re-run of this file.
_LAUNCHER = "run_game_ladder_kg.py"
# The launcher hands the env to its delegate for the length of the sweep, so a
# session caught inside a run is still ours -- do not discard the caller's
# arms in that case. Only a genuinely unrelated launcher's leftovers go.
_OWN_CHAIN = (_LAUNCHER, "run_cellq_held_kg.py")
_owner = _os.environ.get("FIXED_ENV_OWNER", "").strip()
if _owner and _owner not in _OWN_CHAIN:
    for _k in ("FIXED_ARMS", "FIXED_OUT", "GAME_LADDER_PAYOFF"):
        _os.environ.pop(_k, None)

_raw_want = _os.environ.get("GAMESOL_PAYOFF", "")
_want = (_raw_want or "legacy").strip().lower()
if _want not in ("legacy", "ctm2"):
    raise SystemExit("[GAMESOL] GAMESOL_PAYOFF=%r: expected 'legacy' or 'ctm2'"
                     % _want)

_caller_arms = [a.strip() for a in
                (_os.environ.get("FIXED_ARMS", "") or "").split(",") if a.strip()]

if _caller_arms:
    # An explicit arm list wins, and it decides the payoff model: the
    # _CTM2_SPILL2_LIGHTSIM twins are only meaningful on ctm2 payoffs and the
    # legacy arms only on legacy payoffs, so a mismatch cannot slip through.
    # Accept BOTH twin spellings: the fixed-plan twins and the _MP twins whose
    # base signal controller is the ported LightSim MaxPressure
    # (CONTROL_MODE="LIGHTSIM_MP"). Same ctm2 payoff either way.
    _ls = [a for a in _caller_arms
           if a.endswith(("_CTM2_SPILL2_LIGHTSIM", "_CTM2_SPILL2_LIGHTSIM_MP"))]
    if _ls and len(_ls) != len(_caller_arms):
        raise SystemExit("[GAMESOL] FIXED_ARMS mixes LIGHTSIM and other arms; "
                         "run the two sets separately")
    _arms = _caller_arms
    _pay = "ctm2" if _ls else "legacy"
    _set = "ctm2" if _ls else "legacy"
    _env_pay = (_os.environ.get("GAME_LADDER_PAYOFF", "") or "").strip().lower()
    if _raw_want.strip() and _want != _pay:
        print("[GAMESOL] GAMESOL_PAYOFF=%s ignored: the arm list decides (%s)"
              % (_want, _pay))
    if _env_pay and _env_pay != _pay:
        print("[GAMESOL] GAME_LADDER_PAYOFF=%s contradicts FIXED_ARMS -- using %s"
              % (_env_pay, _pay))
elif _want == "ctm2":
    _arms, _pay, _set = _LIGHTSIM_ARMS, "ctm2", "ctm2"
else:
    _arms, _pay, _set = _LEGACY_ARMS, "legacy", "legacy"

_os.environ["FIXED_ARMS"] = ",".join(_arms)
_os.environ["GAME_LADDER_PAYOFF"] = _pay
_os.environ.setdefault("FIXED_TRAIN_SEEDS", "")          # games do not learn
# FIXED_OUT lives for the whole session, so a second exec would inherit the
# first run's name and the delegate would abort ("REFUSING: ... already
# exists"). Keep a caller's name only if it is not already on disk; otherwise
# mint a fresh one, tagged by set so the two sweeps cannot be confused.
_out = (_os.environ.get("FIXED_OUT", "") or "").strip()
if _out and _os.path.exists(_os.path.join(_HERE, _out)):
    print("[GAMESOL] FIXED_OUT=%s already on disk -- using a fresh name" % _out)
    _out = ""
_os.environ["FIXED_OUT"] = _out or ("gamesol_pair_kg%s_%s.csv"
                                    % ("_lightsim" if _set == "ctm2" else "",
                                       _time.strftime("%Y%m%d_%H%M%S")))
# Stamp the owner as the launcher we are about to exec. run_game_ladder_kg.py
# discards FIXED_ARMS/FIXED_OUT when a DIFFERENT launcher owns them, and the
# values above are ours, not a leftover -- without this stamp a session that
# ended inside a delegate would throw the arm list away.
_os.environ["FIXED_ENV_OWNER"] = _LAUNCHER
_os.environ["FIXED_HERE"] = _HERE

print("=" * 78)
print("GAME-SOLUTION PAIR (Aimsun side) -- KG, %s payoffs"
      % ("CTM2 + LightSim block" if _pay == "ctm2" else "legacy"))
print("  set  :", _set)
print("  arms :", "\n         ".join(_arms))
print("  seeds:", _os.environ.get("FIXED_SEEDS", "").strip() or "300,400,500")
print("  out  :", _os.environ["FIXED_OUT"])
print("  then :", "python -I diagnose_run_log.py --all --csv <that CSV>"
      if _pay == "ctm2" else "python _sumo_port/compare_game_solution.py")
print("=" * 78)

_launcher = _os.path.join(_HERE, _LAUNCHER)
exec(compile(open(_launcher, encoding="utf-8").read(), _launcher, "exec"),
     {"__name__": "__main__", "__file__": _launcher})
