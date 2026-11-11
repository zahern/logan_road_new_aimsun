# Paste this into Aimsun's Python console AFTER a full quit + relaunch (RULE 2).
# engine.py AND ctm_twoclass.py are both import-cached, so a hot reload is not
# enough -- the process must be new.
#
# Why the three lines at the top: run_cellq_held_kg.py's _knob() refuses to let
# a caller set FIXED_ARMS while FIXED_ENV_OWNER names a DIFFERENT launcher. It
# prints
#     [ENV] FIXED_ARMS = 4 arms was left by <other> -- DISCARDED
# and then runs whatever that owner chose. Claude's snippet omitted this, so it
# would have re-run the wrong arm set and looked like another inert flag.

import os

# 1. Claim this launcher instead of inheriting the previous owner.
os.environ.pop("FIXED_ENV_OWNER", None)

# 2. A stale training-seed list can narrow the run; clear it explicitly.
os.environ["FIXED_TRAIN_SEEDS"] = ""

# 3. The paired experiment: each _MARGINAL twin differs from its base by
#    SIDE_COST_MARGINAL_COMPETITOR only (now on the GAME path, ctm_twoclass).
os.environ["FIXED_CORRIDOR"] = "kg"
os.environ["FIXED_ARMS"] = ",".join([
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_MARGINAL",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2_MARGINAL",
])
os.environ["FIXED_SEEDS"] = "300,400,500,600,700"

exec(open(r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\run_cellq_held_kg.py").read())

# ---------------------------------------------------------------------------
# PRE-FLIGHT CHECK -- do this before trusting any delta:
#
#  a) [LOAD] must say ENGINE_BUILD=2026-11-11T0100-game-ctm2-marginal-competitor-diag
#     (anything older means the restart did not take).
#
#  b) The _MARGINAL arms must print, once per run:
#       [GAME_MARGINAL] CTM2 game cross-cost = WORST single competing phase
#     and then, every 25th action evaluation, the counter:
#       [GAME_MARGINAL] calls=.. multi_phase=.. max_phases=.. worst_vs_sum=..
#     Missing banner = inert flag, byte-identical A/B: do not score it.
#     max_phases=1 with worst_vs_sum=+0.0 = the flag cannot change a decision
#     on that run, so a null A/B is arithmetic, not evidence: do not score it.
#
#     Read the counter against the action mix. Measured on a synthetic 3-phase
#     ring (sum -> worst charged cross cost, pax.s):
#       INS 8 s   223.9 -> 116.7   displaces TWO phases   -> DIFFERS
#       GE  8 s    55.6 ->  55.6   compresses only the NEXT -> no-op
#       ER  4 s     0.0 ->   0.0   both phases gain        -> no-op
#     So the A/B only has power where the arm actually evaluates phase
#     insertions, not just extensions.
#
#  c) Then compare each twin against its OWN base on the same seed (RULE 3):
#     Objective_PaxPerDelayHr higher is better; TotalPassDelay_hrs lower.
# ---------------------------------------------------------------------------
