"""run_ladder_nashheld_logan.py -- re-run the Logan ladder on the instrumented
build so the [NASH_HELD] columns actually populate.

WHY A SEPARATE OUTPUT FILE. The base launcher writes
`paper_ladder_priority_logan.csv`, and champion_search.main(resume=False) DELETES
an existing results CSV before the batch starts (`_os.remove(RESULTS_CSV_)`,
champion_search.py ~6713). Running it with the default FIXED_OUT would therefore
destroy the published 35-row ladder that the paper's table is built from -- and
you need those rows to compare against. This launcher refuses to write to that
path and defaults to a new file instead.

WHAT IT DOES. Delegates to run_ladder_priority_on_dsw_logan.py with
FIXED_SEEDS / FIXED_OUT overridden; that launcher delegates to
run_aimsun_arm_suite_5seeds.py; the suite sets PAXWIN_OUT_CSV and champion_search
runs 6 arms + NO_TSP per seed. Nothing about the arms changes.

RUN -- inside the Aimsun console, LOGAN ROAD model open, AFTER A FULL QUIT AND
RELAUNCH (Aimsun caches the loaded module; a stale one silently produces the old
numbers with no [NASH_HELD] lines at all):

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_ladder_nashheld_logan.py").read())

BEFORE YOU TRUST IT, check the first [LOAD] line of each run's log:

    ENGINE_BUILD=2026-11-02T1400-cascade-units-nashheld   SOURCE_HASH=<12 hex>
    This launcher prints the expected tag and hash(es) on startup, computed from
    the files on disk, so they cannot go stale in this docstring. If the [LOAD]
    tag differs, the module is STALE: quit Aimsun completely and reopen.

    NOTE the [LOAD] line only shows ENGINE.py's hash -- but all three [NASH_HELD]
    emit paths live in specialized_modes.py. A stale copy of THAT would leave the
    tag and hash looking correct while emitting no rows, which reads downstream as
    a measured zero. The preflight content guard covers it: champion_search FATALs
    if any module's own import-time SOURCE_HASH disagrees with disk, so look for
    `[PREFLIGHT] specialized_modes content <hash> (loaded == disk)` in the console
    before trusting the first run.

ABORTS AT RUN 1. This launcher exports CHAMPION_POSTRUN_BUILD_CHECK=1, so
champion_search checks the FIRST completed run against engine.py and
specialized_modes.py on disk (champion_search._postrun_build_gate ->
verify_kg_build.check_or_raise) instead of trusting the start-of-sweep preflight
alone. A mismatch raises before run 2:

    [POSTRUN] FAIL   [LOAD] ENGINE_BUILD          2026-11-01T1000-...  (expected ...)
    [POSTRUN] ABORTING sweep at the first completed run: it did NOT execute the
    build on disk (5 check(s) failed).

An INCONCLUSIVE result (no runner_console.txt for this session) only warns; the
preflight already hard-fails a stale module. Check any run by hand with:

    python verify_kg_build.py --logs logan_road_new/logs

which reads the corridor's own logs directory and compares the same engine on
disk, so it works unchanged for either corridor.

COST. Observed 20-25 min per run on the 2026-11-01 batch (14 logs, 5 h).
    full ladder  = 7 runs x 5 seeds = 35 runs  ~12 h
    one seed     = 7 runs                      ~3 h
For a first look, take a two-seed probe (the healthy seed and the broken one).
Set it as PYTHON, not as a shell assignment -- the Aimsun console is a Python
REPL, so `NASHHELD_SEEDS=300,600` on its own line is a SyntaxError:

    import os
    os.environ["NASHHELD_SEEDS"] = "300,600"      # -> 14 runs, ~5 h
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_ladder_nashheld_logan.py").read())

THEN (outside Aimsun, no model needed):

    python analyze_nash_held.py --run-csv paper_ladder_nashheld_logan_20261102.csv

which prints the published objective beside the new one and the binding-constraint
tally for every arm.

OVERRIDES (set with os.environ BEFORE the exec):
    NASHHELD_SEEDS   default 300,400,500,600,700
    NASHHELD_OUT     default paper_ladder_nashheld_logan_20261102.csv
    NASHHELD_DRYRUN  set to 1 to print this plan and exit without running
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
_BASE = "run_ladder_priority_on_dsw_logan.py"

# ── stale-knob guard ────────────────────────────────────────────────────────
# FIXED_ARMS / FIXED_OUT / FIXED_SEEDS outlive a launcher: os.environ belongs to
# the Aimsun process, not the exec. This launcher SETS FIXED_OUT itself, so it
# stamps ownership and hands the env to the delegate below, which would
# otherwise discard its own values as a foreign leftover. FIXED_ARMS it does
# not set, so a leftover from a different launcher is dropped instead of
# riding the handover into the delegate as if it were ours.
_ENV_OWNER = "FIXED_ENV_OWNER"
_MY_NAME = "run_ladder_nashheld_logan.py"
_prev_owner = _os.environ.get(_ENV_OWNER, "").strip()
_foreign = bool(_prev_owner) and _prev_owner != _MY_NAME


def _drop_foreign(key):
    """Remove a foreign leftover this launcher does not set itself."""
    _v = (_os.environ.get(key, "") or "").strip()
    if _v and _foreign:
        print("[ENV] %s left by %s -- DISCARDED, this launcher does not take it"
              % (key, _prev_owner))
        _os.environ.pop(key, None)

# The published ladder. Never a valid target for this launcher.
_PROTECTED = _os.path.abspath(_os.path.join(_HERE, "paper_ladder_priority_logan.csv"))

_SEEDS = _os.environ.get("NASHHELD_SEEDS", "300,400,500,600,700").strip()
_OUT = _os.environ.get("NASHHELD_OUT",
                       "paper_ladder_nashheld_logan_20261102.csv").strip()

_out_abs = _os.path.abspath(_os.path.join(_HERE, _OUT))
if _out_abs == _PROTECTED:
    raise SystemExit(
        "[NASHHELD] refusing to write to the published ladder CSV\n"
        "  %s\n"
        "  champion_search.main(resume=False) deletes the file it is given, so\n"
        "  this run would destroy the 35 rows the paper table is built from.\n"
        "  Pick another NASHHELD_OUT." % _out_abs)

# Expected identity, computed from the files on disk so the printed check cannot
# drift from the source the way a hardcoded string does.
import hashlib as _hashlib
import re as _re


def _sha12(path):
    try:
        with open(path, "rb") as _fh:
            return _hashlib.sha1(_fh.read()).hexdigest()[:12]
    except OSError as _e:
        return "? (%s)" % _e


def _tag(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as _fh:
            m = _re.search(r'^ENGINE_BUILD\s*=\s*["\']([^"\']+)', _fh.read(), _re.M)
        return m.group(1) if m else "?"
    except OSError:
        return "?"


_ENG_PY = _os.path.join(_HERE, "shared_tsp_engine", "engine.py")
_SPM_PY = _os.path.join(_HERE, "shared_tsp_engine", "specialized_modes.py")
_build_tag = _tag(_ENG_PY)
_eng_hash = _sha12(_ENG_PY)
_spm_hash = _sha12(_SPM_PY)

_n_seeds = len([s for s in _SEEDS.split(",") if s.strip()])
_n_arms = 6                      # the ladder launcher's default arm set
print("=" * 78)
print("LOGAN LADDER ON THE INSTRUMENTED BUILD  ([NASH_HELD] enabled)")
print("  seeds : %s  (%d)" % (_SEEDS, _n_seeds))
print("  arms  : %d scored + NO_TSP baseline per seed" % _n_arms)
print("  runs  : %d   (observed 20-25 min/run -> roughly %.0f h)"
      % (_n_seeds * (_n_arms + 1), _n_seeds * (_n_arms + 1) * 22.5 / 60.0))
print("  out   : %s" % _out_abs)
print("  abort : after run 1 if the [LOAD] build disagrees with disk")
print("  NOT   : %s  (published; preserved)" % _PROTECTED)
print("=" * 78)
print("  EXPECTED [LOAD] ENGINE_BUILD=%s" % _build_tag)
print("  SOURCE_HASH(engine)            = %s" % _eng_hash)
print("  specialized_modes content      = %s   (preflight-guarded)" % _spm_hash)
print("  A stale specialized_modes yields NO [NASH_HELD] lines.")
print("=" * 78)

# Preview the plan without launching a 12-hour batch. Also the ONLY way to exercise
# the guard below without side effects.
if _os.environ.get("NASHHELD_DRYRUN", "").strip() not in ("", "0"):
    print("[NASHHELD] NASHHELD_DRYRUN set: plan printed, nothing executed.")
    raise SystemExit(0)

_drop_foreign("FIXED_ARMS")
_os.environ["FIXED_SEEDS"] = _SEEDS
_os.environ["FIXED_OUT"] = _OUT
_os.environ[_ENV_OWNER] = _MY_NAME
# Abort the sweep after the first completed run if it did not execute this build.
_os.environ["CHAMPION_POSTRUN_BUILD_CHECK"] = "1"

_launcher = _os.path.join(_HERE, _BASE)
# Hand the env over: FIXED_SEEDS / FIXED_OUT above are this launcher's.
_os.environ[_ENV_OWNER] = _BASE
try:
    exec(compile(open(_launcher, encoding="utf-8").read(), _launcher, "exec"),
         {"__name__": "__main__"})
finally:
    _os.environ[_ENV_OWNER] = _MY_NAME

print("=" * 78)
print("LADDER DONE -> %s" % _out_abs)
print("  compare (no Aimsun needed):")
print("    python analyze_nash_held.py --run-csv %s" % _OUT)
print("  If every why-column still reads '-', the module was stale -- check the")
print("  [LOAD] ENGINE_BUILD before concluding anything about the plot.")
print("=" * 78)
