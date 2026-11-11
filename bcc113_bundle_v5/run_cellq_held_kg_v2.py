"""run_cellq_held_kg_v2.py -- run the CellQ held/downstream A/B into a FRESH CSV.

WHY THIS EXISTS. run_cellq_held_kg.py picks its output from FIXED_OUT and
refuses to start if that file already exists, because champion_search deletes
whatever CSV it is handed when not resuming. That is the right guard, but it
makes the base launcher un-runnable a second time: `cellq_held_kg.csv` from the
2026-11-02 batch is still there and is evidence.

Setting FIXED_OUT works only from an interactive console. Aimsun's script panel
runs a saved .py as-is, so nothing can be set before the file starts -- the
guard then fires on the default name every time. This wrapper therefore sets the
variable ITSELF, at the top of the file, and delegates.

Output name carries a timestamp (cellq_held_kg_run_YYYYmmdd_HHMMSS.csv) so a
re-run can never collide with an earlier one and the guard never blocks it.
The chosen name is printed before anything starts, and again by the base
launcher.

WHAT IT RUNS. Seeds 300,400,500 by default (9 runs, ~1.5 h): NO_TSP plus
CHAMP_ADAPTIVE_DSW_CELLQ_GATED and CHAMP_ADAPTIVE_DSW_CELLQ_GATED_OPEN.
This is the arm pair that exercises the 2026-11-02 engine changes -- the
marginal side_ratio gate, the live local_sat input, the off-phase EARLY_RED
credit, and the approach-cell occupancy fix.

RUN -- inside the Aimsun console / script panel, KG model open, AFTER A FULL
QUIT AND RELAUNCH (both engine.py and specialized_modes.py changed today; a
stale module silently re-runs the old code with a matching-looking tag):

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_cellq_held_kg_v2.py").read())

or just open this file in the script panel and run it.

BEFORE TRUSTING IT, arm the build check in a normal terminal:

    python verify_kg_build.py --wait 20

It waits for the first new run log and compares the [LOAD] fields and all three
preflight hashes against the files on disk.

WHAT TO READ AFTERWARDS
    stats_TSP_EarlyRed        -- expect > 0 for the first time (0.0 in all nine
                                 rows of cellq_held_kg.csv)
    stats_TSP_Extensions      -- may DROP: the occupancy fix makes right-phase GE
                                 look ~5x weaker when the bus cannot arrive
    stats_TotalPassDelay_hrs  -- vs the same-seed NO_TSP row in THIS run, never
                                 against the older CSV (different engine)

OVERRIDES (uncomment / edit at the top, then run):
    _OUT_NAME   exact filename instead of the timestamp
    _SEEDS      e.g. "300,400,500,600,700"
"""
import os as _os
import time as _time

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

# ── stale-knob guard ────────────────────────────────────────────────────────
# FIXED_ARMS / FIXED_OUT are CALLER knobs and os.environ lives for the whole
# Aimsun process, so exec'ing a DIFFERENT launcher in the same session leaves
# its arm list and output name behind. Each launcher stamps the env with its
# own name, and a value left by a DIFFERENT launcher is discarded; an explicit
# value in a clean session -- or a re-run of this same launcher -- is honoured.
_ENV_OWNER = "FIXED_ENV_OWNER"
_MY_NAME = "run_cellq_held_kg_v2.py"
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


def _drop_foreign(key):
    """Remove a foreign leftover this launcher does not set itself."""
    _v = (_os.environ.get(key, "") or "").strip()
    if _v and _foreign:
        print("[ENV] %s left by %s -- DISCARDED, this launcher does not take it"
              % (key, _prev_owner))
        _os.environ.pop(key, None)


# --- what this run writes ----------------------------------------------------
_OUT_NAME = _knob(
    "FIXED_OUT",
    "cellq_held_kg_run_%s.csv" % _time.strftime("%Y%m%d_%H%M%S"))
_SEEDS = _os.environ.get("FIXED_SEEDS", "300,400,500")

_out_path = _os.path.join(_HERE, _OUT_NAME)

# Same guard the base launcher applies, checked here first so the failure is a
# clear message instead of a SystemExit from inside the delegation.
if _os.path.exists(_out_path):
    raise SystemExit(
        "REFUSING: %s already exists.\n"
        "  This wrapper timestamps its output so that should be rare -- you\n"
        "  probably passed FIXED_OUT explicitly. Pick another name."
        % _out_path)

_os.environ["FIXED_OUT"] = _OUT_NAME
_os.environ["FIXED_SEEDS"] = _SEEDS
_os.environ[_ENV_OWNER] = _MY_NAME
_os.environ.setdefault("FIXED_CORRIDOR", "kg")

print("=" * 78)
print("CELLQ HELD A/B  ->  %s" % _OUT_NAME)
print("  seeds   : %s  (%d runs incl. NO_TSP per seed)"
      % (_SEEDS, len([s for s in _SEEDS.split(",") if s.strip()]) * 3))
print("  out     : %s" % _out_path)
print("  base    : %s" % _os.path.join(_HERE, "run_cellq_held_kg.py"))
print("  engine  : %s" % _os.path.join(_HERE, "shared_tsp_engine", "engine.py"))
print("  NOTE: full Aimsun restart required -- engine.py and")
print("        specialized_modes.py both changed on 2026-11-02.")
print("=" * 78)

# This launcher does not set FIXED_ARMS, so a leftover from a different
# launcher must not ride the handover into the base launcher as if it were ours.
_drop_foreign("FIXED_ARMS")
_base = _os.path.join(_HERE, "run_cellq_held_kg.py")
# Hand the env over: FIXED_OUT above is this launcher's, not a leftover.
_os.environ[_ENV_OWNER] = "run_cellq_held_kg.py"
try:
    exec(compile(open(_base, encoding="utf-8").read(), _base, "exec"),
         {"__name__": "__main__"})
finally:
    _os.environ[_ENV_OWNER] = _MY_NAME

print("=" * 78)
print("CELLQ HELD A/B DONE -> %s" % _out_path)
print("  summary: %s" % (_os.path.splitext(_out_path)[0] + "_summary.csv"))
print("=" * 78)
