"""run_ladder_5seeds_fixed.py -- full 5-seed run of the fixed ladder.

Run INSIDE the Aimsun console AFTER A FULL RESTART (engine.py,
specialized_modes.py and champion_search.py all changed), with KG open:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_ladder_5seeds_fixed.py").read())

Seeds 300--700, five methods:
  M0 NO_TSP (auto-added by the suite)
  M1 CHAMP_ADAPTIVE_AIMSUN_DSW
  M2 CHAMP_ADAPTIVE_DSW_MARL_BUS   (solved GE [1,10] / INS [1,6])
  M3 CHAMP_ADAPTIVE_DSW_CELLQ_GATED (jitter off, shockwave+DE, GE/INS cap 6,
      per-junction CTM cells + connector link cell + downstream receiving
      constraint + clearance cap; learns on 3 derived bins
      recv/tail/bind instead of the sparse raw cell tuple)
  M4 CHAMP_ADAPTIVE_DSW_GAME_BUS   (NASH_BUS_WEIGHT=1)
  M5 CHAMP_ADAPTIVE_DSW_GAME_COOP  (cooperative team game, side payments)

The egalitarian max-min variant is opt-in (it adds a 7th arm):
  FIXED_ARMS="...,CHAMP_ADAPTIVE_DSW_GAME_COOP,CHAMP_ADAPTIVE_DSW_GAME_EGAL"

Writes paper_ladder_5seeds_fixed.csv; does not overwrite the old run.

Optional OPEN diagnostics (permissive gates) can be added without editing:
    import os
    os.environ["FIXED_ARMS"] = ("CHAMP_ADAPTIVE_AIMSUN_DSW,"
        "CHAMP_ADAPTIVE_DSW_MARL_OPEN,CHAMP_ADAPTIVE_DSW_CELLQ_OPEN,"
        "CHAMP_ADAPTIVE_DSW_GAME_OPEN")
    exec(open(r"...\\run_ladder_5seeds_fixed.py").read())
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
_MY_NAME = "run_ladder_5seeds_fixed.py"
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
# PLANNED 8-ARM LADDER (2026-10-30): the five paper methods plus the two SCATS
# extensions. Kept in one place so KG and Logan run the identical arm set.
#   baseline : CHAMP_NO_TSP (auto-added by the suite)
#   base     : CHAMP_ADAPTIVE_AIMSUN_DSW            (passive DSW)
#   SCATS    : CHAMP_ADAPTIVE_AIMSUN_DSW_SCATS      (SCATS strategic+tactical, no TSP)
#   SCATS+TSP: CHAMP_ADAPTIVE_AIMSUN_DSW_SCATS_VIAB (SCATS + viability-gated TSP)
#   priority : MARL_BUS, CELLQ_GATED, GAME_BUS, GAME_COOP
ARMS = _knob(
    "FIXED_ARMS",
    "CHAMP_ADAPTIVE_AIMSUN_DSW,"
    "CHAMP_ADAPTIVE_AIMSUN_DSW_SCATS,"
    "CHAMP_ADAPTIVE_AIMSUN_DSW_SCATS_VIAB,"
    "CHAMP_ADAPTIVE_DSW_MARL_BUS,"
    "CHAMP_ADAPTIVE_DSW_CELLQ_GATED,"
    "CHAMP_ADAPTIVE_DSW_GAME_BUS,"
    "CHAMP_ADAPTIVE_DSW_GAME_COOP")
# CORRIDOR-AWARE OUTPUT (2026-10-30): respect FIXED_CORRIDOR so the same script
# runs KG and Logan without one overwriting the other's CSV, and so the corridor
# is not hard-wired to kg (it was, so a Logan run silently wrote a KG-named file
# and compared the wrong network).
CORRIDOR = _os.environ.get("FIXED_CORRIDOR", "kg")
OUT = _knob(
    "FIXED_OUT", "paper_ladder_8arm_%s.csv" % CORRIDOR)
# Publish the resolved knobs: the env always reflects what actually runs,
# so a same-owner re-run reads these back instead of reviving a leftover.
_os.environ["FIXED_ARMS"] = ARMS
_os.environ["FIXED_OUT"] = OUT
_os.environ[_ENV_OWNER] = _MY_NAME

_os.environ["ARM_SUITE_SEEDS"] = SEEDS
_os.environ["ARM_SUITE_ARMS"] = ARMS
_os.environ["ARM_SUITE_OUT"] = OUT
_os.environ["ARM_SUITE_CORRIDOR"] = CORRIDOR
# True-state matrix cadence: 5 s (default is 30 s). This feeds
# plot_true_states.py (density/flow/speed/queue heatmaps).
_os.environ.setdefault("STATS_SECTION_INTERVAL_S", "5")

print("=" * 72)
print("FIXED LADDER -- full 5-seed run")
print("  seeds:", SEEDS)
print("  arms :", ARMS)
print("  out  :", _os.path.join(_HERE, OUT))
print("  (M0 NO_TSP is added automatically by the suite)")
print("  NOTE: full Aimsun console restart required")
print("=" * 72)

_runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
     {"__name__": "__main__"})

print("=" * 72)
print("FIXED LADDER DONE --", OUT)
print("  read: python -I summarize_overnight.py", OUT)
print("=" * 72)
