"""Run the Logan priority ladder for seeds 500, 600 and 700.

Seed 500 is repeated on purpose: it is the A/B probe for the CTM group-boundary
connector fix (KG 39593->39576, Logan 18942->19185 / 21895->22232 in
shared_tsp_engine/specialized_modes.py).  If the new seed-500 rows match the
published ones in paper_ladder_priority_logan.csv, the fix is inert for the
scored arms and merge_logan_extra_seeds.py will merge 300,400 (old) with
500,600,700 (new) into a five-seed ladder.  If they differ, the script aborts
and asks for 300,400 to be re-run on the same build instead.

RUN -- inside the Aimsun console with the LOGAN ROAD model open, AFTER A FULL
RESTART (the engine source hash changes with the connector fix):

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_ladder_priority_logan_seeds_500_700.py").read())

Verify on the [LOAD] line that the corridor resolves to logan_road_new and the
ENGINE_BUILD is the new one (it should mention the current engine.py hash), and
that the run log shows `[CTM_CONN] inter=18942 boundary tgt=19185` and
`inter=21895 boundary tgt=22232` instead of `no_index`.
"""
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

# ── stale-knob guard ────────────────────────────────────────────────────────
# This launcher sets FIXED_SEEDS / FIXED_OUT itself and delegates to the Logan
# ladder launcher. Without a stamp that delegate would treat these values as a
# foreign launcher's leftover and throw them away; without dropping a stale
# FIXED_ARMS the handover would launder a THIRD launcher's arm list into the
# delegate as if it were ours.
_ENV_OWNER = "FIXED_ENV_OWNER"
_MY_NAME = "run_ladder_priority_logan_seeds_500_700.py"
_prev_owner = _os.environ.get(_ENV_OWNER, "").strip()
_foreign = bool(_prev_owner) and _prev_owner != _MY_NAME


def _drop_foreign(key):
    """Remove a foreign leftover this launcher does not set itself."""
    _v = (_os.environ.get(key, "") or "").strip()
    if _v and _foreign:
        print("[ENV] %s left by %s -- DISCARDED, this launcher does not take it"
              % (key, _prev_owner))
        _os.environ.pop(key, None)


_drop_foreign("FIXED_ARMS")
_os.environ["FIXED_SEEDS"] = "500,600,700"
_os.environ["FIXED_OUT"] = "paper_ladder_priority_logan_500_700.csv"
_os.environ[_ENV_OWNER] = _MY_NAME

print("=" * 72)
print("LOGAN PRIORITY LADDER -- seeds 500,600,700 (500 = CTM connector A/B)")
print("  base launcher:", _os.path.join(_HERE, "run_ladder_priority_on_dsw_logan.py"))
print("  out          :", _os.path.join(_HERE, "paper_ladder_priority_logan_500_700.csv"))
print("=" * 72)

# Hand the env over: FIXED_SEEDS / FIXED_OUT above are this launcher's.
_os.environ[_ENV_OWNER] = "run_ladder_priority_on_dsw_logan.py"
try:
    exec(compile(
        open(_os.path.join(_HERE, "run_ladder_priority_on_dsw_logan.py"),
             encoding="utf-8").read(),
        _os.path.join(_HERE, "run_ladder_priority_on_dsw_logan.py"), "exec"),
        {"__name__": "__main__"})
finally:
    _os.environ[_ENV_OWNER] = _MY_NAME
