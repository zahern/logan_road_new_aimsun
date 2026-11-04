"""run_logan_cascade_ab.py -- re-run the cascade seeds on the patched build.

Produces the "AFTER" side of the cascade/action comparison for seed 300 (the
distribution seed) and seed 500 (the paper seed). The published "BEFORE" side
already exists and is read straight from the run logs by analyze_cascade_ab.py:

  seed 300 (7 charges, 2026-10-31T1900)   3.6e3 ... 1.52e7 pax.s, max_sat 0.84-10.49
  seed 500 (1 charge,  2026-11-01T1000)   2.81e6 pax.s,          max_sat 5.96
  seeds 400/600/700                       0 / 0 / 2 charges

WHY SEED 300 IS THE ONE TO ADD
  Seven of the ten published charges are on seed 300, so it is the only seed that
  yields anything resembling a distribution. It is also the only seed where the
  champion beats NO_TSP (+4.5%), while seeds 400 and 600 -- which recorded NO
  charges at all -- are the worst losses. The cascade is therefore not what
  suppresses TSP on the losing seeds, which is worth knowing before spending more
  runs on threshold tuning.

WHAT IT RUNS
  NO_TSP + the champion arm, per seed, same demand, same model:
      seed 300 : 2 runs
      seed 500 : 2 runs
  Floor over CASCAB_SEEDS="300" if you only want the distribution seed.

RUN -- inside the Aimsun console, LOGAN ROAD model open, AFTER A FULL QUIT AND
RELAUNCH (the engine source changed and Aimsun caches the loaded module):

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_logan_cascade_ab.py").read())

FIRST CHECK the [LOAD] line reads ENGINE_BUILD=2026-11-02T1400-cascade-units-
nashheld AND SOURCE_HASH=<12 hex>. The hash is taken from the engine bytes at
import, so it -- not the tag -- is the identity: analyze_cascade_ab.py marks a
run STALE when its hash is not the engine.py on disk. If you see
2026-11-01T1000-spillback-direct-occ you are on the OLD module: quit Aimsun
completely and reopen. A run on the stale module reproduces the old number
exactly and looks like "the fix did nothing".

WHAT THIS BUILD CHANGES -- SMALL AFTER COSTS ARE THE FIX WORKING
  The charge now prices the ADDED platoon's own clearance (_extra/_q_sat_d)
instead of the whole projected cell queue (_proj/_q_sat_d), so the bill is set
by what the action releases rather than by how congested the cell already was.
Expect (a) no more 1e6-1e7 charges, (b) cost driven by action length and
projected saturation, and (c) a 10 s action costing ~100x a 1 s one in the same
cell. A quiet AFTER side is the intended result, not a fix that failed to land.

Re-read the comparison any time afterwards (no Aimsun needed):

    python analyze_cascade_ab.py --seeds 300,500

CAVEAT ON SAMPLE SIZE
  Even the published best case is 7 points. Read the SCALE (1e6 vs 1e3-1e4 pax.s)
  and the max_sat (>1 pegged vs varying), not a median, and treat one seed as a
  direction check rather than evidence.
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

_SEEDS = (_os.environ.get("CASCAB_SEEDS", "300,500") or "300,500").strip()
_OUT = (_os.environ.get("CASCAB_OUT", "")
        or "cascade_ab_seeds%s.csv" % _SEEDS.replace(",", "_")).strip()
_ARM = _os.environ.get("CASCAB_ARM", "CHAMP_ADAPTIVE_DSW_GAME_BUS_LOGAN").strip()

_os.environ["ARM_SUITE_SEEDS"] = _SEEDS
_os.environ["ARM_SUITE_ARMS"] = _ARM
_os.environ["ARM_SUITE_OUT"] = _OUT
_os.environ["ARM_SUITE_CORRIDOR"] = "logan_road_new"

_n_seeds = len([s for s in _SEEDS.split(",") if s.strip()])
print("=" * 84)
print("CASCADE A/B -- seeds %s, patched build" % _SEEDS)
print("  arm : %s" % _ARM)
print("  -> NO_TSP + 1 arm x %d seed(s) = %d runs" % (_n_seeds, 2 * _n_seeds))
print("  out : %s" % _os.path.join(_HERE, _OUT))
print("  EXPECTED [LOAD] ENGINE_BUILD=2026-11-02T1400-cascade-units-nashheld")
print("  and SOURCE_HASH=<12 hex>; the analyzer flags any run whose hash is not"
      " engine.py on disk")
print("=" * 84)

_runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
     {"__name__": "__main__"})

# Report on the runs that just finished. Wrapped so a reporting bug can never
# invalidate a completed (and expensive) set of runs.
print("")
try:
    _apath = _os.path.join(_HERE, "analyze_cascade_ab.py")
    # __file__ MUST be supplied: the analyzer derives its default log dir from it.
    _ns = {"__name__": "cascade_ab", "__file__": _apath}
    exec(compile(open(_apath, encoding="utf-8").read(), _apath, "exec"), _ns)
    _ns["main"](["--seeds", _SEEDS])
except Exception as _e:
    print("cascade analysis skipped:", repr(_e))
    print("  run it manually: python analyze_cascade_ab.py --seeds %s" % _SEEDS)
