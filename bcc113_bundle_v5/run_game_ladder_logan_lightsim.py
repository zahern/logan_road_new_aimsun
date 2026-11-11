"""run_game_ladder_logan_lightsim.py -- LOGAN ROAD: LightSim-CTM vs SPILL2 A/B.

Pairs each game's _CTM2_SPILL2 arm (baseline: scalar per-phase downstream jam
fraction) against its _CTM2_SPILL2_LIGHTSIM twin (the block term priced by the
LightSim-style NETWORK CTM), so a difference between the two is attributable to
the block MODEL, not to the game played.

  CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2            (baseline)
  CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_LIGHTSIM   (LightSim block)

Both solutions by default: 5 seeds x (NO_TSP + 2 pairs x 2 arms) = 25 runs,
which is close to Aimsun's ~30-run per-session stability ceiling. Narrow with
LIGHTSIM_SOLS=NASH (15 runs) or FIXED_SEEDS=300,400,500 (15 runs).

Needs the LightSim engine build (engine.py + specialized_modes.py + the new
shared_tsp_engine/ctm_lightsim.py were edited), so a FULL Aimsun restart is
REQUIRED (RULE 2). Verify the build tag on the [LOAD] banner first.

RUN -- Aimsun console, LOGAN model open, after a full restart:

    import os; os.environ["FIXED_SEEDS"] = "300,400,500,600,700"
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_game_ladder_logan_lightsim.py").read())

Then: python -I diagnose_run_log.py --all --csv <the CSV printed at DONE>

Useful knobs (set before the exec):
    FIXED_CORRIDOR=logan_road_new     corridor to run (default logan)
    LIGHTSIM_SOLS=NASH,UTIL           which games to pair (default NASH,UTIL)
    FIXED_SEEDS=300,400,500,600,700   seeds

STALE-ENV: FIXED_ARMS / FIXED_OUT are caller knobs, but os.environ survives for
the whole Aimsun process, so after running a DIFFERENT launcher in the same
session its arm list and output name are still in the environment. This
launcher DETECTS that (see the stale-knob guard below), prints an [ENV] line
and discards those values. An explicit FIXED_ARMS set in a clean session, or a
re-run of this same launcher, is still honoured -- no cleanup needed first.
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

# One game solution per A/B pair; each contributes baseline + LightSim twin.
_PAIRS = _os.environ.get("LIGHTSIM_SOLS", "NASH,UTIL").replace(" ", "").split(",")
_arms = []
for _k in _PAIRS:
    if not _k:
        continue
    _arms.append("CHAMP_ADAPTIVE_DSW_GAME_SOL_%s_CTM2_SPILL2" % _k)
    _arms.append("CHAMP_ADAPTIVE_DSW_GAME_SOL_%s_CTM2_SPILL2_LIGHTSIM" % _k)

# ── stale-knob guard ────────────────────────────────────────────────────────
# FIXED_ARMS / FIXED_OUT are CALLER knobs and os.environ lives for the whole
# Aimsun process, so exec'ing a DIFFERENT launcher in the same session leaves
# its arm list and output name behind; a bare setdefault() then silently reuses
# them (measured: a ladder run inherited the CELLQ arms and wrote to
# cellq_held_kg.csv). Each launcher stamps the env with its own name, and a
# value left by a DIFFERENT launcher is discarded. An explicit value in a clean
# session -- or a re-run of this same launcher -- is still honoured.
_ENV_OWNER = "FIXED_ENV_OWNER"
_MY_NAME = "run_game_ladder_logan_lightsim.py"
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
    "FIXED_OUT", "game_ladder_logan_lightsim_%s.csv"
    % _time.strftime("%Y%m%d_%H%M%S"))
_os.environ[_ENV_OWNER] = _MY_NAME
_os.environ.setdefault("FIXED_TRAIN_SEEDS", "")          # games do not learn
_os.environ.setdefault("FIXED_CORRIDOR", "logan_road_new")
_os.environ["FIXED_HERE"] = _HERE

print("=" * 76)
print("GAME LADDER -- LOGAN ROAD  LIGHTSIM-CTM vs SPILL2  (block model A/B)")
print("  corridor:", _os.environ["FIXED_CORRIDOR"])
print("  seeds   :", _os.environ.get("FIXED_SEEDS", "300,400,500 (default)"))
print("  arms    :", _os.environ["FIXED_ARMS"].replace(",", "\n            "))
print("  REQUIRES the LightSim engine build -- FULL Aimsun restart (RULE 2)")
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
