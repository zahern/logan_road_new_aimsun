"""run_ladder_nashheld_kg.py -- the PROTECTED KG ladder launcher: re-run the KG
priority ladder on the current engine build into a NEW results CSV.

Twin of run_ladder_nashheld_logan.py. Same guard, adapted to KG's arm set, seed
count, corridor name and published file.

WHY A SEPARATE OUTPUT FILE. The base launcher writes
`paper_ladder_priority_kg.csv`, and champion_search.main(resume=False) DELETES an
existing results CSV before the batch starts (`_os.remove(RESULTS_CSV_)`,
champion_search.py ~6713). Running it with the default FIXED_OUT would therefore
destroy the published 25-row KG ladder the paper's cross-corridor table is built
from -- and you need those rows to compare against. This launcher refuses to
write there (and to the Logan ladder CSV, so a mistyped NASHHELD_OUT cannot
destroy the other corridor's table) and defaults to a new file instead.

WHAT IT DOES. Delegates to run_ladder_priority_on_dsw.py with FIXED_SEEDS /
FIXED_OUT overridden; that launcher delegates to run_aimsun_arm_suite_5seeds.py;
the suite sets PAXWIN_OUT_CSV and champion_search runs 4 arms + NO_TSP per seed.
Nothing about the arms changes.

WHICH ENGINE IT RUNS. kg/intersection_controller.py pins this bundle: it strips
every competing shared_tsp_engine root from sys.path, purges foreign
shared_tsp_engine* modules, imports `shared_tsp_engine.engine`, then HARD-FAILS
if the resolved file is outside the bundle:

    [BUNDLE-GUARD] engine pinned: ...\\bcc113_bundle_v5\\shared_tsp_engine\\engine.py

So there is no per-corridor engine copy to update -- patching
shared_tsp_engine/engine.py here is what KG loads. The [LOAD] line repeats it as
`engine_file=...`, which is the field to check if you ever doubt it.

RUN -- inside the Aimsun console, KG model open, AFTER A FULL QUIT AND RELAUNCH
(Aimsun caches the loaded module; a stale copy re-runs the OLD code and produces
the old numbers with a matching-looking tag):

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_ladder_nashheld_kg.py").read())

BEFORE YOU TRUST IT, check the first [LOAD] line of each run's log:

    ENGINE_BUILD=<tag printed by this launcher at startup>   SOURCE_HASH=<12 hex>
    engine_file=...\\bcc113_bundle_v5\\shared_tsp_engine\\engine.py

This launcher prints the expected tag and both content hashes on startup,
computed from the files on disk, so they cannot go stale the way a hardcoded
string does. If the [LOAD] tag differs, the module is STALE: quit Aimsun
completely and reopen.

    NOTE the [LOAD] line only carries ENGINE.py's hash, but the cascade, Nash and
    [NASH_HELD] paths live in specialized_modes.py. A stale copy of THAT would
    leave the tag and hash looking correct while emitting nothing. The preflight
    content guard covers it -- champion_search FATALs if any module's own
    import-time SOURCE_HASH disagrees with disk. Those lines are written to
    `kg/logs/runner_console.txt` (NOT the per-run TSP log), so check them with

        python verify_kg_build.py --wait 20

    armed in a terminal before you paste this launcher: it waits for the first
    new run log and compares the [LOAD] fields and all three preflight hashes
    against engine.py and specialized_modes.py on disk.

ABORTS AT RUN 1. This launcher exports CHAMPION_POSTRUN_BUILD_CHECK=1, so
champion_search re-runs the same check itself once the FIRST run completes. On a
mismatch it raises before run 2 instead of spending the remaining runs on stale
code:

    [POSTRUN] FAIL   [LOAD] ENGINE_BUILD          2026-11-01T1000-...  (expected ...)
    [POSTRUN] ABORTING sweep at the first completed run: it did NOT execute the
    build on disk (4 check(s) failed).

An INCONCLUSIVE gate (missing runner_console.txt) only logs a warning -- the
preflight already hard-fails a stale module, and that is not worth killing a
multi-hour sweep over. The CSV written before the abort keeps its first row, so
nothing is silently lost.

COST. Measured from the 2026-11-01 KG logs: ~7.5-8.5 min per run (KG is much
faster than Logan's 20-25 min).

    5 seeds x (4 arms + NO_TSP) = 25 runs  ~3.5 h
    1 seed  x (4 arms + NO_TSP) =  5 runs  ~40 min

For a single-seed probe set it as PYTHON, not as a shell assignment -- the
Aimsun console is a Python REPL, so `NASHHELD_SEEDS=600` on its own line is a
SyntaxError:

    import os
    os.environ["NASHHELD_SEEDS"] = "600"        # -> 5 runs, ~40 min
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_ladder_nashheld_kg.py").read())

THEN (outside Aimsun, no model needed):

    python analyze_nash_held.py --logs kg/logs --csv paper_ladder_priority_kg.csv --run-csv paper_ladder_nashheld_kg_20261102.csv

Note the KG arm names carry NO _LOGAN suffix, and the published KG rows were all
written on the 2026-11-01T1000 build, i.e. before every fix in this one -- so KG
gives a clean single-build before/after, unlike Logan's table, which is split
across two builds.

OVERRIDES (set with os.environ BEFORE the exec):
    NASHHELD_SEEDS   default 300,400,500,600,700
    NASHHELD_OUT     default paper_ladder_nashheld_kg_20261102.csv
    NASHHELD_DRYRUN  set to 1 to print this plan and exit without running
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
_BASE = "run_ladder_priority_on_dsw.py"

# Published ladders. Never valid targets for this launcher: champion_search
# deletes whatever CSV it is handed, and both files are paper inputs.
_PROTECTED = {
    _os.path.abspath(_os.path.join(_HERE, "paper_ladder_priority_kg.csv")):
        "the published 25-row KG ladder",
    _os.path.abspath(_os.path.join(_HERE, "paper_ladder_priority_logan.csv")):
        "the published 35-row LOGAN ladder",
}

_SEEDS = _os.environ.get("NASHHELD_SEEDS", "300,400,500,600,700").strip()
_OUT = _os.environ.get("NASHHELD_OUT",
                       "paper_ladder_nashheld_kg_20261102.csv").strip()

_out_abs = _os.path.abspath(_os.path.join(_HERE, _OUT))
if _out_abs in _PROTECTED:
    raise SystemExit(
        "[NASHHELD] refusing to write to %s\n  %s\n"
        "  champion_search.main(resume=False) deletes the file it is given, so\n"
        "  this run would destroy rows the paper table is built from.\n"
        "  Pick another NASHHELD_OUT."
        % (_PROTECTED[_out_abs], _out_abs))

# Expected identity, computed from the files on disk so the printed check cannot
# drift from the source the way a hardcoded string does.
import hashlib as _hashlib
import re as _re

_ENG_PY = _os.path.join(_HERE, "shared_tsp_engine", "engine.py")
_SPM_PY = _os.path.join(_HERE, "shared_tsp_engine", "specialized_modes.py")


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


def _rows(path):
    try:
        with open(path, "rb") as _fh:
            return max(0, sum(1 for _ in _fh) - 1)
    except OSError:
        return -1


_build_tag = _tag(_ENG_PY)
_eng_hash = _sha12(_ENG_PY)
_spm_hash = _sha12(_SPM_PY)
_n_seeds = len([s for s in _SEEDS.split(",") if s.strip()])
_n_arms = 4                      # the KG ladder launcher's default arm set
_n_runs = _n_seeds * (_n_arms + 1)
_pub_rows = _rows(_os.path.join(_HERE, "paper_ladder_priority_kg.csv"))

print("=" * 78)
print("KG LADDER ON THE CURRENT BUILD")
print("  seeds : %s  (%d)" % (_SEEDS, _n_seeds))
print("  arms  : %d scored + NO_TSP baseline per seed" % _n_arms)
print("  runs  : %d   (measured 7.5-8.5 min/run -> roughly %.1f h)"
      % (_n_runs, _n_runs * 8.0 / 60.0))
print("  out   : %s" % _out_abs)
print("  abort : after run 1 if the [LOAD] build disagrees with disk")
print("  NOT   : %s  (%s, preserved)"
      % (_os.path.join(_HERE, "paper_ladder_priority_kg.csv"),
         "%d rows" % _pub_rows if _pub_rows >= 0 else "missing"))
print("=" * 78)
print("  EXPECTED [LOAD] ENGINE_BUILD=%s" % _build_tag)
print("  SOURCE_HASH(engine)            = %s" % _eng_hash)
print("  specialized_modes content      = %s   (preflight-guarded)" % _spm_hash)
print("  engine_file must be            = %s" % _ENG_PY)
print("  (KG pins this bundle via [BUNDLE-GUARD] and FATALs on a foreign copy)")
print("=" * 78)

# Preview the plan without launching a multi-hour batch. Also the ONLY way to
# exercise the guard above without side effects.
if _os.environ.get("NASHHELD_DRYRUN", "").strip() not in ("", "0"):
    print("[NASHHELD] NASHHELD_DRYRUN set: plan printed, nothing executed.")
    raise SystemExit(0)

_os.environ["FIXED_SEEDS"] = _SEEDS
_os.environ["FIXED_OUT"] = _OUT
# Abort the sweep after the first completed run if it did not execute this build
# (champion_search._postrun_build_gate -> verify_kg_build.check_or_raise).
_os.environ["CHAMPION_POSTRUN_BUILD_CHECK"] = "1"

_launcher = _os.path.join(_HERE, _BASE)
exec(compile(open(_launcher, encoding="utf-8").read(), _launcher, "exec"),
     {"__name__": "__main__"})

print("=" * 78)
print("KG LADDER DONE -> %s" % _out_abs)
print("  compare against the published rows (no Aimsun needed):")
print("    python analyze_nash_held.py --logs kg/logs "
      "--csv paper_ladder_priority_kg.csv --run-csv %s" % _OUT)
print("  verify the build actually executed (no Aimsun needed):")
print("    python verify_kg_build.py")
print("  If the [LOAD] ENGINE_BUILD was not %s," % _build_tag)
print("  the module was stale -- quit and relaunch Aimsun before trusting this.")
print("=" * 78)
