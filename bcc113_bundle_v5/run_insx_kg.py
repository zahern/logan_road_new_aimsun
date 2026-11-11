"""run_insx_kg.py -- KG: does the off-phase INSERTION-cost fix help the MARL and
GAME deciders, not just CellQ?

Two paired A/Bs on the SAME build + seeds:

  CHAMP_ADAPTIVE_DSW_MARL_BUS         paper M2 MARL champion, UNCHANGED
  CHAMP_ADAPTIVE_DSW_MARL_BUS_INSX    same, CELLQ_INS_MARGINAL_CROSS=True only
  CHAMP_ADAPTIVE_DSW_GAME_BUS         paper M4 Nash bus game, UNCHANGED
  CHAMP_ADAPTIVE_DSW_GAME_BUS_INSX    same, CELLQ_INS_MARGINAL_CROSS=True only
  (+ NO_TSP, auto-added by the suite as the paired control)

WHY
The off-phase insertion overcharge (an INS priced on the bus's whole pre-existing
red wait, not the green it DISPLACES) was NOT CellQ-only: the same t_wait+delta
pattern lived in the staged DP _eval_stage_action (the DCTSP_MARL decider) and in
dctsp_mp_ectm / dctsp_mp_ectm_dp. CELLQ_INS_MARGINAL_CROSS now gates the marginal
fix (a_s + INS_INTERGREEN_S) at all of those sites. These arms A/B it ON each
decider while changing NOTHING else.

READING THE TWO ARMS
  MARL_BUS_INSX  the staged DP carried the bug and MARL_BUS actually inserts
                 (CPDQL_ENABLE_INS, eps=0.05), so this arm is EXPECTED TO DIVERGE
                 from its base. More insertions committing, car delay not worse ->
                 the fix helps the MARL decider.
  GAME_BUS_INSX  the Nash path prices its INS through _dctsp_eval_action, which
                 was ALREADY marginal. This arm is the CONTROL: it should come out
                 ~identical to CHAMP_ADAPTIVE_DSW_GAME_BUS. If it DIVERGES, the game
                 path has an insertion cost that still needs tracing.

CAVEAT -- the side_ratio veto gate (see run_cellq_held_kg.py) recomputes its own
cross cost via _dctsp_cross_traffic_delay_s, whose 1/(1-x) oversaturation term
diverges on a near-saturated side approach (observed: a 1 s insertion priced at
~2963 pax*s on KG). That gate is NOT what CELLQ_INS_MARGINAL_CROSS fixes, so on a
saturated junction insertions may still be vetoed even with this flag on. Watch
the [CELLQ_HELD] veto=side_ratio(..) tally below; if it dominates, the gate, not
the reward, is the binding constraint.

RUN -- inside the Aimsun console with the KG model open, AFTER A FULL RESTART
(engine.py and specialized_modes.py changed -- RULE 2):

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_insx_kg.py").read())

Check the [LOAD] line: ENGINE_BUILD / SOURCE_HASH must match what this launcher
prints. CHAMPION_POSTRUN_BUILD_CHECK=1 aborts after run 1 on a stale module.

Seeds default to 300,400,500 (15 runs: 3 seeds x [NO_TSP + 4 arms]). Extend with
FIXED_SEEDS. Other env knobs: FIXED_ARMS, FIXED_CORRIDOR, FIXED_OUT.
"""
import glob as _glob
import hashlib as _hashlib
import os as _os
import re as _re
import time as _time

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

# ── stale-knob guard ────────────────────────────────────────────────────────
# FIXED_ARMS / FIXED_OUT are CALLER knobs and os.environ lives for the whole
# Aimsun process, so exec'ing a DIFFERENT launcher in the same session leaves
# its arm list and output name behind. Each launcher stamps the env with its
# own name, and a value left by a DIFFERENT launcher is discarded; an explicit
# value in a clean session -- or a re-run of this same launcher -- is honoured.
_ENV_OWNER = "FIXED_ENV_OWNER"
_MY_NAME = "run_insx_kg.py"
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


SEEDS = _os.environ.get("FIXED_SEEDS", "300,400,500")

ARMS = _knob(
    "FIXED_ARMS",
    "CHAMP_ADAPTIVE_DSW_MARL_BUS,"
    "CHAMP_ADAPTIVE_DSW_MARL_BUS_INSX,"
    "CHAMP_ADAPTIVE_DSW_GAME_BUS,"
    "CHAMP_ADAPTIVE_DSW_GAME_BUS_INSX")

CORRIDOR = _os.environ.get("FIXED_CORRIDOR", "kg")

# Output name. FIXED_OUT honoured exactly; the DEFAULT name is allowed to move to
# a timestamped sibling so an Aimsun script object can re-run with no env var.
_DEFAULT_OUT = "insx_kg.csv"
_FIXED_OUT_RAW = _knob("FIXED_OUT", "")
OUT = _FIXED_OUT_RAW or _DEFAULT_OUT

# Published / previously-reported result files -- never a valid target.
_PROTECTED = {
    "paper_ladder_8arm_kg.csv",
    "paper_ladder_priority_kg.csv",
    "paper_ladder_priority_logan.csv",
    "paper_ladder_priority_logan_500_700.csv",
    "paxwin_arm_suite_5seeds.csv",
    "cellq_act_ab_kg.csv",
    "cellq_held_kg.csv",
    "logan_ladder.csv",
}

_OUT_PATH = _os.path.join(_HERE, OUT)
_OUT_NAME = _os.path.basename(_OUT_PATH).lower()
_ALLOW = _os.environ.get("FIXED_ALLOW_OVERWRITE", "").strip() not in ("", "0")

if _OUT_NAME in _PROTECTED:
    raise SystemExit(
        "REFUSING: %s is a published results file and must not be rewritten.\n"
        "  Pick another FIXED_OUT (the default insx_kg.csv is safe)."
        % _OUT_NAME)

if _os.path.exists(_OUT_PATH) and not _ALLOW:
    if _FIXED_OUT_RAW:
        raise SystemExit(
            "REFUSING: %s already exists.\n"
            "  champion_search DELETES the CSV it is given when it is not resuming\n"
            "  (Aimsun never passes --resume), so this run would destroy those rows.\n"
            "  Rename it, pick a new FIXED_OUT, or pass FIXED_ALLOW_OVERWRITE=1 if\n"
            "  you really intend to discard it." % _OUT_PATH)
    OUT = "%s_%s.csv" % (_os.path.splitext(_DEFAULT_OUT)[0],
                         _time.strftime("%Y%m%d_%H%M%S"))
    _OUT_PATH = _os.path.join(_HERE, OUT)
    print("[OUT] %s already exists -- writing %s instead"
          % (_DEFAULT_OUT, OUT))


def _engine_tag():
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


# Publish the resolved knobs: the env always reflects what actually runs.
_os.environ["FIXED_ARMS"] = ARMS
_os.environ["FIXED_OUT"] = OUT
_os.environ[_ENV_OWNER] = _MY_NAME
_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT
_os.environ["ARM_SUITE_CORRIDOR"] = CORRIDOR
_os.environ.setdefault("STATS_SECTION_INTERVAL_S", "5")
_os.environ["CHAMPION_POSTRUN_BUILD_CHECK"] = "1"

print("=" * 76)
print("INSERTION-COST A/B (MARL + GAME) -- KELVIN GROVE")
print("  seeds:", SEEDS)
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


def _tally(since):
    """Count [CELLQ_ADMIT] / [CELLQ_HELD] by veto name across this session."""
    logs = []
    for _p in _glob.glob(_os.path.join(_HERE, CORRIDOR, "logs",
                                       "Aimsun_TSP_Log_*.txt")):
        try:
            if _os.path.getmtime(_p) + 120.0 >= since:
                logs.append((_os.path.getmtime(_p), _p))
        except OSError:
            pass
    if not logs:
        print("  (no run logs found under %s/logs -- right corridor?)" % CORRIDOR)
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


_T0 = _time.time()

_runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
     {"__name__": "__main__"})

print("=" * 76)
print("INSERTION-COST A/B DONE --", OUT)
print("=" * 76)
print("[CELLQ_HELD] / [CELLQ_ADMIT] TALLY for this session")
try:
    _tally(_T0)
except Exception as _e:
    print("  (tally failed: %r -- read %s/logs by hand)" % (_e, CORRIDOR))
print("-" * 76)
print("  COMPARE per seed vs NO_TSP (same seed only -- RULE 3):")
print("    MARL_BUS vs MARL_BUS_INSX  -> fix expected to CHANGE behaviour")
print("    GAME_BUS vs GAME_BUS_INSX  -> CONTROL, expected ~identical")
print("  CSV: python -I summarize_overnight.py", OUT)
print("  Per-run logs: %s" % _os.path.join(_HERE, CORRIDOR, "logs"))
print("=" * 76)
