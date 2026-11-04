"""run_cellq_held_kg.py -- KG: why does the CellQ overlay barely act?

Two arms, one paired A/B:

  A  CHAMP_ADAPTIVE_DSW_CELLQ_GATED       the KG paper champion, UNCHANGED
  B  CHAMP_ADAPTIVE_DSW_CELLQ_GATED_OPEN  same champion, four admission gates
                                          relaxed (see the arm comment in
                                          champion_search.py)
  (+ NO_TSP, auto-added by the suite as the paired control)

Nothing about the signal safety bounds changes -- min green, intergreen and
MAX_GE_EXTENSION_S are all still enforced after the gates. The only question is
whether the overlay is refused, and by WHICH constraint.

WHY THE LOG IS THE POINT, NOT THE CSV
The build now attributes every CellQ refusal in one line shape:

    [CELLQ_HELD] inter=<id> t=<s> bus=<id> veto=<name>(<lhs><op><rhs>) ...
                 proposed=<TYPE>_<n>s eff_delay=..s side_ratio=.. local_sat=..
    [CELLQ_ADMIT] inter=<id> t=<s> bus=<id> action=<TYPE>_<n>s eff_delay=.. ...

`veto` names the FIRST failing constraint with both sides of the comparison.
Names and what they mean:

  min_gain(..)        eff_delay below CELLQLEARN_MIN_GAIN_S      (decider)
  solved_deficit(..)  solved green below _MIN_EFFECTIVE_GE_S     (decider)
  side_ratio(..)      conflicting-side balance exceeded          (decider)
  local_sat(..)       absolute main saturation veto              (decider)
  cost_veto(..)       DeciderCostVeto, downstream of the rule layer
  net_pax(..)         NET_PAX_DELAY_GATE, downstream
  main_floor(..)      MAIN_CORRIDOR_FLOOR_GATE, downstream

The first four fire inside dctsp_bxt; the last three fire in the ENGINE, after
the R1--R11 rule layer. Before 2026-11-02 the downstream three were silent on
Logan (LOG_COST_VETO=False) and appeared only as raw [COST VETO] /
[NET DELAY VETO] / [MAIN FLOOR] lines on KG. Now they also emit the uniform
[CELLQ_HELD] line, so one parser reads the whole ledger on both corridors.

HOW TO READ IT
  ADMIT high, HELD dominated by cost_veto/net_pax/main_floor, grants ~0
      -> the decider proposes and the ECONOMICS refuses. The lever is the veto
         ratios, i.e. exactly what arm B changes.
  HELD dominated by min_gain/local_sat
      -> the refusal is upstream; raising the veto ratios will not help.
  No ADMIT lines at all
      -> the decider never produced a candidate on that seed.

NOTE ON VOLUME
Arm B raises CELLQ_HELD_LOG_MAX to 60 (default 8) so the tally is a
distribution. That budget is per junction per RUN and split into 'pre' (the
decider's own gates) and 'post' (the engine vetoes), so neither can starve the
other. [CELLQ_ADMIT] is capped separately at CELLQ_ADMIT_LOG_MAX (400).

RUN -- inside the Aimsun console with the KG model open, AFTER A FULL RESTART
(both engine.py and specialized_modes.py changed; Aimsun caches them for the
process lifetime -- RULE 2):

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_cellq_held_kg.py").read())

Before trusting anything, check the [LOAD] line: ENGINE_BUILD and SOURCE_HASH
must match the values this launcher prints. CHAMPION_POSTRUN_BUILD_CHECK=1 is
exported, so a stale module aborts the sweep after run 1 instead of burning the
rest.

OUTPUT IS PROTECTED. champion_search DELETES the results CSV it is handed when
it is not resuming (and Aimsun never passes --resume), so this launcher refuses
to start if its target exists, and always refuses the published result files.
Override only for a deliberate fresh re-run: FIXED_ALLOW_OVERWRITE=1.
The DEFAULT name is exempt from that refusal: when cellq_held_kg.csv is already
there it is left alone and the run writes cellq_held_kg_<YYYYmmdd_HHMMSS>.csv.
So a second run needs no environment variable at all.

Seeds default to 300,400,500 (9 runs: 3 seeds x [NO_TSP + 2 arms]). Extend with
FIXED_SEEDS=300,400,500,600,700. Other launchers: FIXED_ARMS, FIXED_CORRIDOR,
FIXED_OUT.
"""
import glob as _glob
import hashlib as _hashlib
import os as _os
import re as _re
import time as _time

# The bundle folder. Inside Aimsun this file is run via exec(open(...).read()),
# which defines no __file__, so the hard-coded path below is used exactly as
# before. Run as a script (or from a test / another clone) it resolves to the
# folder this file is actually in, so the output guard checks the RIGHT
# folder. FIXED_HERE overrides both.
_HERE_DEFAULT = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
_HERE = _os.environ.get("FIXED_HERE", "").strip()
if not _HERE:
    try:
        _HERE = _os.path.dirname(_os.path.abspath(__file__))
        if not _os.path.isdir(_os.path.join(_HERE, "shared_tsp_engine")):
            _HERE = _HERE_DEFAULT
    except NameError:
        _HERE = _HERE_DEFAULT

SEEDS = _os.environ.get("FIXED_SEEDS", "300,400,500")

# Learner PRE-TRAINING seeds (the paper's protocol: train on 800-1100, then
# freeze and score on SEEDS). Without them the CellQ arms are scored on an
# untrained, frozen Q-table and hold on every decision (KG run 2026-11-04:
# phase=eval train=[] freeze=True, 0 Q-states loaded). Each learner arm runs
# these extra seeds first (~15 min each). FIXED_TRAIN_SEEDS="" to skip.
TRAIN_SEEDS = _os.environ.get("FIXED_TRAIN_SEEDS", "800,900,1000,1100")

ARMS = _os.environ.get(
    "FIXED_ARMS",
    "CHAMP_ADAPTIVE_DSW_CELLQ_GATED,"
    "CHAMP_ADAPTIVE_DSW_CELLQ_GATED_OPEN")

CORRIDOR = _os.environ.get("FIXED_CORRIDOR", "kg")

# Output name.  FIXED_OUT is honoured exactly; the DEFAULT name is allowed to
# move.  WHY: setting FIXED_OUT only works from an interactive console.  An
# Aimsun script object runs this file as-is, so a guard that rejects the default
# name makes the launcher un-runnable a second time with no way for the caller to
# pass a different one.  A colliding EXPLICIT name is still refused -- that is a
# deliberate choice, and silently writing elsewhere would hide it.
_DEFAULT_OUT = "cellq_held_kg.csv"
_FIXED_OUT_RAW = _os.environ.get("FIXED_OUT", "").strip()
OUT = _FIXED_OUT_RAW or _DEFAULT_OUT

# ── output protection ───────────────────────────────────────────────────────
# Published / previously-reported result files. Refused even with
# FIXED_ALLOW_OVERWRITE=1: those are evidence, not scratch space.
_PROTECTED = {
    "paper_ladder_8arm_kg.csv",
    "paper_ladder_priority_kg.csv",
    "paper_ladder_priority_logan.csv",
    "paper_ladder_priority_logan_500_700.csv",
    "paxwin_arm_suite_5seeds.csv",
    "cellq_act_ab_kg.csv",
    "logan_ladder.csv",
}

_OUT_PATH = _os.path.join(_HERE, OUT)
_OUT_NAME = _os.path.basename(_OUT_PATH).lower()
_ALLOW = _os.environ.get("FIXED_ALLOW_OVERWRITE", "").strip() not in ("", "0")

if _OUT_NAME in _PROTECTED:
    raise SystemExit(
        "REFUSING: %s is a published results file and must not be rewritten.\n"
        "  Pick another FIXED_OUT (the default cellq_held_kg.csv is safe)."
        % _OUT_NAME)

if _os.path.exists(_OUT_PATH) and not _ALLOW:
    if _FIXED_OUT_RAW:
        raise SystemExit(
            "REFUSING: %s already exists.\n"
            "  champion_search DELETES the CSV it is given when it is not resuming\n"
            "  (Aimsun never passes --resume), so this run would destroy those rows.\n"
            "  Rename it, pick a new FIXED_OUT, or pass FIXED_ALLOW_OVERWRITE=1 if\n"
            "  you really intend to discard it." % _OUT_PATH)
    # Default name taken: bump to a timestamped sibling. Nothing can be lost --
    # the existing file is left untouched -- so there is no reason to abort a
    # multi-hour sweep over a filename.
    OUT = "%s_%s.csv" % (_os.path.splitext(_DEFAULT_OUT)[0],
                         _time.strftime("%Y%m%d_%H%M%S"))
    _OUT_PATH = _os.path.join(_HERE, OUT)
    print("[OUT] %s already exists -- writing %s instead"
          % (_DEFAULT_OUT, OUT))


def _engine_tag():
    """ENGINE_BUILD read from disk, so the expectation cannot go stale here."""
    try:
        with open(_os.path.join(_HERE, "shared_tsp_engine", "engine.py"),
                  "r", encoding="utf-8", errors="replace") as _fh:
            _m = _re.search(r'^ENGINE_BUILD\s*=\s*["\']([^"\']+)', _fh.read(),
                            _re.M)
        return _m.group(1) if _m else "?"
    except Exception:
        return "?"


def _sha12(rel):
    try:
        with open(_os.path.join(_HERE, "shared_tsp_engine", rel), "rb") as _fh:
            return _hashlib.sha1(_fh.read()).hexdigest()[:12]
    except Exception:
        return "?"


_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_TRAIN_SEEDS"] = TRAIN_SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT
_os.environ["ARM_SUITE_CORRIDOR"] = CORRIDOR
_os.environ.setdefault("STATS_SECTION_INTERVAL_S", "5")
# Abort after run 1 if the loaded module is not the bytes on disk. See
# verify_kg_build.py -- this is what stops 8 more runs on a stale module.
_os.environ["CHAMPION_POSTRUN_BUILD_CHECK"] = "1"

print("=" * 76)
print("CELLQ GATE A/B -- KELVIN GROVE")
print("  seeds:", SEEDS)
print("  train:", TRAIN_SEEDS or "(none -- learners scored untrained)")
print("  arms :", ARMS)
print("  out  :", _OUT_PATH)
print("  (NO_TSP added automatically by the suite as the paired control)")
print("-" * 76)
print("  EXPECTED BUILD (read from disk now)")
print("    ENGINE_BUILD            %s" % _engine_tag())
print("    sha1(engine.py)[:12]    %s" % _sha12("engine.py"))
print("    sha1(specialized_modes) %s" % _sha12("specialized_modes.py"))
print("  Verify BOTH on the [LOAD] line. A mismatch means Aimsun is running a")
print("  cached module: quit Aimsun COMPLETELY, reopen KG, re-run.")
print("  Post-run build gate is ON -- a stale module aborts after run 1.")
print("=" * 76)


# ── tally the diagnostics after the sweep ───────────────────────────────────
def _tally(since):
    """Count [CELLQ_ADMIT] and [CELLQ_HELD] by veto name across this session."""
    logs = []
    for _p in _glob.glob(_os.path.join(_HERE, CORRIDOR, "logs",
                                       "Aimsun_TSP_Log_*.txt")):
        try:
            if _os.path.getmtime(_p) + 120.0 >= since:
                logs.append((_os.path.getmtime(_p), _p))
        except OSError:
            pass
    if not logs:
        print("  (no run logs found under %s/logs -- is this the right corridor?)"
              % CORRIDOR)
        return
    veto_re = _re.compile(r"veto=([a-z_]+)\(")
    admits = helds = 0
    by_veto = {}
    for _m, _p in sorted(logs):
        try:
            with open(_p, "r", encoding="utf-8", errors="replace") as _fh:
                txt = _fh.read()
        except OSError:
            continue
        _a = txt.count("[CELLQ_ADMIT]")
        _h = veto_re.findall(txt)
        admits += _a
        helds += len(_h)
        for _v in _h:
            by_veto[_v] = by_veto.get(_v, 0) + 1
        print("    %-34s admits=%-5d held=%-5d"
              % (_os.path.basename(_p)[-26:], _a, len(_h)))
    print("")
    print("  TOTAL admits=%d  held=%d  (all runs above)" % (admits, helds))
    if by_veto:
        print("  refusals by binding constraint:")
        for _v, _n in sorted(by_veto.items(), key=lambda kv: -kv[1]):
            print("    %-16s %d" % (_v, _n))
    if admits and not helds:
        print("  Every admit survived to the rule layer -> the overlay is NOT")
        print("  being refused economically; look at stats_TSP_Extensions and")
        print("  the [TSP RULE] lines instead.")


_T0 = _time.time()

_runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
     {"__name__": "__main__"})

print("=" * 76)
print("CELLQ GATE A/B DONE --", OUT)
print("=" * 76)
print("[CELLQ_HELD] / [CELLQ_ADMIT] TALLY for this session")
try:
    _tally(_T0)
except Exception as _e:
    print("  (tally failed: %r -- read %s/logs by hand)" % (_e, CORRIDOR))
print("-" * 76)
print("  CSV: python -I summarize_overnight.py", OUT)
print("  Per-run logs: %s" % _os.path.join(_HERE, CORRIDOR, "logs"))
print("=" * 76)
