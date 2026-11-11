"""run_game_ladder_logan_chain_ab.py -- LOGAN ROAD: chain-seed A/B.

Tests whether seeding the two-class CTM over the RESOLVED UPSTREAM CHAIN (true
vehicle positions on every chained section) instead of only the single stop-line
section buys anything on Logan's short blocks. Pairs each arm's _CTM2_SPILL2
(baseline, single-section seed) against its _CTM2_SPILL2_CHAIN twin
(GAME_CTM2_CHAIN_SEED=True) on the same seeds, plus NO_TSP.

Default arm set is focused to stay under Aimsun's ~30-run-per-session stability
ceiling (the 15 h SPILL2 batch died at run ~36): the champion (asymmetric Nash)
and the heaviest actor (utilitarian), each baseline + chain = 4 arms + NO_TSP:

  CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2         (baseline, single-section)
  CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_CHAIN   (chain seed)
  CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2         (baseline)
  CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2_CHAIN   (chain seed)

4 arms x 5 seeds + NO_TSP = 25 runs. Widen with FIXED_ARMS if you restart between
chunks. Needs ENGINE_BUILD 2026-11-08T1200-game-ctm2-chainseed or newer (verify on
the [LOAD] banner) -- engine.py + specialized_modes.py were edited, so a FULL
Aimsun restart is REQUIRED (RULE 2).

RUN -- Aimsun console, LOGAN model open, after a full restart:

    import os; os.environ["FIXED_SEEDS"] = "300,400,500,600,700"
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_game_ladder_logan_chain_ab.py").read())

Afterwards: python -I diagnose_run_log.py --all --csv <the CSV printed at DONE>
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

# One (game-solution) per A/B pair; each contributes baseline + chain.
_PAIRS = _os.environ.get("CHAIN_AB_SOLS", "NASH,UTIL").replace(" ", "").split(",")
_arms = []
for _k in _PAIRS:
    if not _k:
        continue
    _arms.append("CHAMP_ADAPTIVE_DSW_GAME_SOL_%s_CTM2_SPILL2" % _k)
    _arms.append("CHAMP_ADAPTIVE_DSW_GAME_SOL_%s_CTM2_SPILL2_CHAIN" % _k)

# ── stale-knob guard ────────────────────────────────────────────────────────
# FIXED_ARMS / FIXED_OUT are CALLER knobs and os.environ lives for the whole
# Aimsun process, so exec'ing a DIFFERENT launcher in the same session leaves
# its arm list and output name behind; a bare setdefault() then silently reuses
# them (measured: a ladder run inherited the CELLQ arms and wrote to
# cellq_held_kg.csv). Each launcher stamps the env with its own name, and a
# value left by a DIFFERENT launcher is discarded. An explicit value in a clean
# session -- or a re-run of this same launcher -- is still honoured.
_ENV_OWNER = "FIXED_ENV_OWNER"
_MY_NAME = "run_game_ladder_logan_chain_ab.py"
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


_os.environ["FIXED_ARMS"] = _knob("FIXED_ARMS", ",".join(_arms))
_os.environ["FIXED_OUT"] = _knob(
    "FIXED_OUT", "game_ladder_logan_chain_ab_%s.csv"
    % _time.strftime("%Y%m%d_%H%M%S"))
_os.environ[_ENV_OWNER] = _MY_NAME
_os.environ.setdefault("FIXED_TRAIN_SEEDS", "")          # games do not learn
_os.environ.setdefault("FIXED_CORRIDOR", "logan_road_new")
_os.environ["FIXED_HERE"] = _HERE

print("=" * 76)
print("GAME LADDER -- LOGAN ROAD  CHAIN-SEED A/B  (no NULL)")
print("  corridor:", _os.environ["FIXED_CORRIDOR"])
print("  seeds   :", _os.environ.get("FIXED_SEEDS", "300,400,500 (default)"))
print("  arms    :", _os.environ["FIXED_ARMS"].replace(",", "\n            "))
print("  REQUIRES engine build 2026-11-08T1200-game-ctm2-chainseed (restart!)")
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
