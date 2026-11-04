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

_os.environ["FIXED_SEEDS"] = "500,600,700"
_os.environ["FIXED_OUT"] = "paper_ladder_priority_logan_500_700.csv"

print("=" * 72)
print("LOGAN PRIORITY LADDER -- seeds 500,600,700 (500 = CTM connector A/B)")
print("  base launcher:", _os.path.join(_HERE, "run_ladder_priority_on_dsw_logan.py"))
print("  out          :", _os.path.join(_HERE, "paper_ladder_priority_logan_500_700.csv"))
print("=" * 72)

exec(compile(
    open(_os.path.join(_HERE, "run_ladder_priority_on_dsw_logan.py"),
         encoding="utf-8").read(),
    _os.path.join(_HERE, "run_ladder_priority_on_dsw_logan.py"), "exec"),
    {"__name__": "__main__"})
