"""run_game_ladder_logan_spill.py -- LOGAN ROAD: the PRICING-CORRECTED game
ladder. Sibling of run_game_ladder_logan.py; runs the spillback/cell-jam
corrected CTM2 game family so the two CSVs form a clean corrected-vs-uncorrected
comparison on the identical arms and seeds.

WHY THIS EXISTS -- the plain _CTM2 ladder (run_game_ladder_logan.py) prices each
grant on a 60 s single-junction CTM horizon with NO downstream spillback throttle
and NO direct-occupancy flooring, so on Logan it (a) reads a ~6x UNDER-counted
queue from the virtual loops and (b) banks phantom car gains from pushing platoons
into jammed arterial links it cannot see -> cascade -> every arm lost to NO_TSP.
This launcher runs the corrected twins instead.

VARIANT (env GAME_SPILL_VARIANT, default "spill2"):
  spill2  (DEFAULT, correct for Logan) CHAMP_..._GAME_SOL_%s_CTM2_SPILL2
          upper bound from the CELL-STATE jam fraction (GAME_CONGESTION_MAX_JAM
          =0.90, veh-count/storage -- trustworthy), DS gate OFF
          (GAME_CONGESTION_MAX_DS=0), no lower car-queue floor, spillback throttle
          + sharpened cross cost (GAME_CROSS_STARVE_MULT=1.5), bus-in-horizon gate.
          This is the family that does NOT rely on Logan's broken 18x DS
          estimator, so it is the right test of whether correct pricing recovers
          the corridor.
  spill   CHAMP_..._GAME_SOL_%s_CTM2_SPILL -- the earlier twin. KEEP IN MIND it
          gates on GAME_CONGESTION_MAX_DS=0.90 against the SAME inflated DS
          estimator (pinned 3-6 on Logan), so it will phantom-hold almost every
          solve and collapse toward the NULL/base. Run it only to demonstrate that
          failure mode, not as the corrected champion.

The eight game-solution arms only (NASH, UTIL, NWELF, EGAL, KS, STACKBUS,
STACKCAR, NONCOOP); no GAME_BUS/GAME_COOP rungs (they have no spill twin) and NO
NULL control. NO_TSP is added by the suite automatically. Games do not learn: no
training seeds.

RUN -- in the Aimsun console with the LOGAN ROAD model open, after a FULL restart.
For the full corrected-vs-uncorrected comparison run all five seeds:

    import os; os.environ["FIXED_SEEDS"] = "300,400,500,600,700"
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_game_ladder_logan_spill.py").read())

Or queue it right after the 600/700 completion run (seeds carry from FIXED_SEEDS).
8 arms x 5 seeds + NO_TSP ~ 45 runs (Logan is 23 intersections -- slower than KG).
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
# GAME_SPILL_VARIANT: spill2 (default, cell-jam upper bound -- correct for Logan)
# or spill (DS-gated upper bound -- will phantom-hold on Logan's inflated DS).
_VAR = _os.environ.get("GAME_SPILL_VARIANT", "spill2").strip().lower()
if _VAR not in ("spill", "spill2"):
    _VAR = "spill2"
_suffix = "_CTM2_SPILL2" if _VAR == "spill2" else "_CTM2_SPILL"
_sol_arms = ["CHAMP_ADAPTIVE_DSW_GAME_SOL_%s%s" % (k, _suffix) for k in _SOL]

# ── stale-knob guard ────────────────────────────────────────────────────────
# FIXED_ARMS / FIXED_OUT are CALLER knobs and os.environ lives for the whole
# Aimsun process, so exec'ing a DIFFERENT launcher in the same session leaves
# its arm list and output name behind; a bare setdefault() then silently reuses
# them (measured: a ladder run inherited the CELLQ arms and wrote to
# cellq_held_kg.csv). Each launcher stamps the env with its own name, and a
# value left by a DIFFERENT launcher is discarded. An explicit value in a clean
# session -- or a re-run of this same launcher -- is still honoured.
_ENV_OWNER = "FIXED_ENV_OWNER"
_MY_NAME = "run_game_ladder_logan_spill.py"
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


_os.environ["FIXED_ARMS"] = _knob("FIXED_ARMS", ",".join(_sol_arms))
_os.environ["FIXED_OUT"] = _knob(
    "FIXED_OUT", "game_ladder_logan_%s_%s.csv"
    % (_VAR, _time.strftime("%Y%m%d_%H%M%S")))
_os.environ[_ENV_OWNER] = _MY_NAME
_os.environ.setdefault("FIXED_TRAIN_SEEDS", "")          # games do not learn
_os.environ.setdefault("FIXED_CORRIDOR", "logan_road_new")
_os.environ["FIXED_HERE"] = _HERE

print("=" * 76)
print("GAME LADDER -- LOGAN ROAD  PRICING-CORRECTED  (variant=%s, no NULL)" % _VAR)
print("  corridor:", _os.environ["FIXED_CORRIDOR"])
print("  seeds   :", _os.environ.get("FIXED_SEEDS", "300,400,500 (default)"))
print("  arms    :", _os.environ["FIXED_ARMS"].replace(",", "\n            "))
if _VAR == "spill":
    print("  NOTE: 'spill' gates on the inflated DS estimator -- expect it to")
    print("        phantom-hold on Logan and collapse toward the base. Use")
    print("        GAME_SPILL_VARIANT=spill2 for the corrected champion family.")
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
