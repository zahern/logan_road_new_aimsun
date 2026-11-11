"""run_game_ladder_kg_ctmcap_ab.py -- KG: CTM cell cap 24 vs 12, paired A/B.

The two arms are clones of the LightSim NASH game that differ ONLY in
CBQL_CTM_MAX_CELLS and GAME_CTM2_LIGHTSIM_MAX_CELLS, so a same-seed difference
is the cap and nothing else:

  ..._LIGHTSIM_CAP12   the pre-2026-11-09 behaviour: every approach truncated
                       at 12 cells (~133 m); 7 KG sections lose 362.6 m total
  ..._LIGHTSIM_CAP24   smallest cap with zero truncation; section 21546
                       (263.2 m) is the one that forces 24

Neither arm learns (FIXED_TRAIN_SEEDS is cleared), so there is no training
protocol to get wrong. NO_TSP is added by the suite as the paired control.

RUN -- Aimsun console, KG model open, after a FULL Aimsun quit+relaunch
(champion_search.py changed, and Aimsun caches it for the process lifetime):

    import os; os.environ["FIXED_SEEDS"] = "300,400,500,600,700"
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_game_ladder_kg_ctmcap_ab.py").read())

2 arms x 5 seeds + NO_TSP = 15 runs. Then:

    python -I analyse_ctmcap_ab.py --csv <the CSV printed at DONE>

Check the [LOAD] line first: ENGINE_BUILD and sha1(engine.py)[:12] must match
what the launcher prints. CHAMPION_POSTRUN_BUILD_CHECK=1 is exported by the
launcher, so a stale module aborts after run 1 instead of burning the sweep.

Knobs (set before the exec):
    FIXED_SEEDS=300,400,500,600,700   seeds (default here)
    FIXED_OUT=<name>.csv              result CSV (default is timestamped)
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

_BASE = "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_LIGHTSIM"
_ARMS = (_BASE + "_CAP12", _BASE + "_CAP24")

# ── stale-knob guard ────────────────────────────────────────────────────────
# FIXED_ARMS / FIXED_OUT are CALLER knobs and os.environ lives for the whole
# Aimsun process, so exec'ing a DIFFERENT launcher in the same session leaves
# its arm list and output name behind; a bare setdefault() then silently reuses
# them (measured: a ladder run inherited the CELLQ arms and wrote to
# cellq_held_kg.csv). Each launcher stamps the env with its own name, and a
# value left by a DIFFERENT launcher is discarded. An explicit value in a clean
# session -- or a re-run of this same launcher -- is still honoured.
_ENV_OWNER = "FIXED_ENV_OWNER"
_MY_NAME = "run_game_ladder_kg_ctmcap_ab.py"
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


_os.environ["FIXED_ARMS"] = _knob("FIXED_ARMS", ",".join(_ARMS))
_os.environ["FIXED_OUT"] = _knob(
    "FIXED_OUT", "game_ladder_kg_ctmcap_ab_%s.csv"
    % _time.strftime("%Y%m%d_%H%M%S"))
_os.environ[_ENV_OWNER] = _MY_NAME
_os.environ.setdefault("FIXED_TRAIN_SEEDS", "")          # games do not learn
_os.environ.setdefault("FIXED_CORRIDOR", "kg")
_os.environ.setdefault("FIXED_SEEDS", "300,400,500,600,700")
_os.environ["FIXED_HERE"] = _HERE

print("=" * 76)
print("GAME LADDER -- KELVIN GROVE   CTM CELL CAP 24 vs 12  (paired A/B)")
print("  corridor:", _os.environ["FIXED_CORRIDOR"])
print("  seeds   :", _os.environ["FIXED_SEEDS"])
print("  arms    :", _os.environ["FIXED_ARMS"].replace(",", "\n            "))
print("  out     :", _os.environ["FIXED_OUT"])
print("  caps are the ONLY difference between the arms; CAP12 truncates")
print("  7 KG sections (362.6 m), CAP24 truncates none.")
print("  REQUIRES a FULL Aimsun restart -- champion_search.py is cached")
print("=" * 76)

# PREFLIGHT: refuse to start if any configured cap would truncate an approach.
# Requirement is recomputed from the measured geometry, so a rebuilt model that
# needs more cells fails here instead of silently truncating. The CAP12 arm is
# a declared control and passes; see check_ctm_cap_requirement.py.
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location(
    "_ctm_cap_gate", _os.path.join(_HERE, "check_ctm_cap_requirement.py"))
_gate = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_gate)
_fail = _gate.run([_os.environ["FIXED_CORRIDOR"]],
                  _os.environ["FIXED_ARMS"].split(","))
if _fail:
    raise SystemExit(
        "REFUSING: %d CTM cell-cap problem(s) -- fix the caps listed above, or"
        " the payoff will model a truncated approach." % _fail)
print("  preflight: CTM cell caps cover every approach")

# The KG launcher (its banner says CELLQ, but the arms come from FIXED_ARMS):
# it resolves the corridor, the output guard and the post-run build gate.
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
