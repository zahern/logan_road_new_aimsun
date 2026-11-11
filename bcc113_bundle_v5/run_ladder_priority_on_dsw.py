"""run_ladder_priority_on_dsw.py -- 5-seed run of ONLY the priority strategies,
each ON TOP of the adaptive AIMSUN_DSW plan base.

WHY this exists (2026-10-31): the full 8-arm ladder already gave us NO_TSP and the
standalone AIMSUN_DSW results, and the two SCATS arms (DS split re-solve) just
break KG's commissioned coordination -- they are not worth re-running. All we want
now is the learner/game strategies layered on the DSW base, re-run on the NEW
engine build (2026-10-31T0730-ctm-spatial-cells) so the CELLQ spatial-cell fix is
exercised. So this launcher DROPS:
    - CHAMP_ADAPTIVE_AIMSUN_DSW        (standalone passive base -- already have it)
    - CHAMP_ADAPTIVE_AIMSUN_DSW_SCATS  (SCATS, degrades KG)
    - CHAMP_ADAPTIVE_AIMSUN_DSW_SCATS_VIAB
and keeps the four priority arms, which already carry the DSW base internally:
    M1 CHAMP_ADAPTIVE_DSW_MARL_BUS    (DCTSP MARL, solved GE/INS)
    M2 CHAMP_ADAPTIVE_DSW_CELLQ_GATED (CTM cell learner -- the arm the 0730 fix targets)
    M3 CHAMP_ADAPTIVE_DSW_GAME_BUS    (Nash bus-priority game)
    M4 CHAMP_ADAPTIVE_DSW_GAME_COOP   (cooperative team game)

NO_TSP NOTE: the arm suite ALWAYS runs ONE NO_TSP baseline per seed (it is the
paired control the "% vs NO_TSP" summary + significance test read from). That is
only 5 runs and, on the new build, gives a correct same-build baseline -- so it is
kept on purpose, not a re-run of the old standalone sweep. To reuse the OLD NO_TSP
instead and skip even that, you would have to merge CSVs by hand; not worth it.

Writes paper_ladder_priority_<corridor>.csv -- a SEPARATE file, so it never
overwrites paper_ladder_8arm_<corridor>.csv (compare across the two: NO_TSP/DSW
baselines live in the 8-arm CSV, the re-run priority arms here).

RUN (inside the Aimsun console, AFTER A FULL RESTART -- Aimsun caches engine.py
and specialized_modes.py for the process lifetime), KG open:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_ladder_priority_on_dsw.py").read())

Before trusting the numbers, compare the [LOAD] line's ENGINE_BUILD against the
EXPECTED value this launcher prints (read from engine.py on disk, so it cannot go
stale here). A mismatch means the module is STALE: quit Aimsun completely and
reopen the model.

For a protected run that will not overwrite the published CSV, use
run_ladder_nashheld_kg.py instead -- champion_search deletes the file it is
handed, so running THIS launcher at its default FIXED_OUT destroys
paper_ladder_priority_kg.csv.
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

# ── stale-knob guard ────────────────────────────────────────────────────────
# FIXED_ARMS / FIXED_OUT are CALLER knobs and os.environ lives for the whole
# Aimsun process, so exec'ing a DIFFERENT launcher in the same session leaves
# its arm list and output name behind. Each launcher stamps the env with its
# own name, and a value left by a DIFFERENT launcher is discarded; an explicit
# value in a clean session -- or a re-run of this same launcher -- is honoured.
_ENV_OWNER = "FIXED_ENV_OWNER"
_MY_NAME = "run_ladder_priority_on_dsw.py"
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


SEEDS = _os.environ.get("FIXED_SEEDS", "300,400,500,600,700")

def _engine_build_tag():
    """Current ENGINE_BUILD from disk, printed so the expectation cannot go stale."""
    try:
        import re as _re
        with open(_os.path.join(_HERE, "shared_tsp_engine", "engine.py"),
                  "r", encoding="utf-8", errors="replace") as _fh:
            _m = _re.search(r'^ENGINE_BUILD\s*=\s*["\']([^"\']+)', _fh.read(), _re.M)
        return _m.group(1) if _m else "?"
    except Exception:
        return "?"


# The FOUR priority strategies, each on the DSW base. NO SCATS, NO standalone DSW.
ARMS = _knob(
    "FIXED_ARMS",
    "CHAMP_ADAPTIVE_DSW_MARL_BUS,"
    "CHAMP_ADAPTIVE_DSW_CELLQ_GATED,"
    "CHAMP_ADAPTIVE_DSW_GAME_BUS,"
    "CHAMP_ADAPTIVE_DSW_GAME_COOP")

CORRIDOR = _os.environ.get("FIXED_CORRIDOR", "kg")
OUT = _knob("FIXED_OUT", "paper_ladder_priority_%s.csv" % CORRIDOR)
# Publish the resolved knobs: the env always reflects what actually runs,
# so a same-owner re-run reads these back instead of reviving a leftover.
_os.environ["FIXED_ARMS"] = ARMS
_os.environ["FIXED_OUT"] = OUT
_os.environ[_ENV_OWNER] = _MY_NAME

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT
_os.environ["ARM_SUITE_CORRIDOR"] = CORRIDOR
# True-state matrix cadence 5 s (feeds plot_true_states.py), same as the 8-arm run.
_os.environ.setdefault("STATS_SECTION_INTERVAL_S", "5")

print("=" * 72)
print("PRIORITY-ON-DSW LADDER -- full 5-seed run")
print("  seeds:", SEEDS)
print("  arms :", ARMS)
print("  out  :", _os.path.join(_HERE, OUT))
print("  (M0 NO_TSP baseline added automatically by the suite -- 5 runs)")
print("  (SCATS + standalone AIMSUN_DSW intentionally dropped)")
print("  NOTE: full Aimsun restart required; expect build %s" % _engine_build_tag())
print("=" * 72)

_runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
     {"__name__": "__main__"})

print("=" * 72)
print("PRIORITY-ON-DSW LADDER DONE --", OUT)
print("  read: python -I summarize_overnight.py", OUT)
print("  baselines (NO_TSP/DSW) for context are in paper_ladder_8arm_%s.csv" % CORRIDOR)
print("=" * 72)
