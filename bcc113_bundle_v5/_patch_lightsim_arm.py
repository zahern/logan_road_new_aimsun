"""CHAMP_ADAPTIVE_DSW_GAME_SOL_*_CTM2_LIGHTSIM arms (sweep_arms.py, on Z:).

Adds the arm that runs the game-theory payoff with the LightSim network CTM as
the downstream-block model.

EOL-aware. Idempotent: re-running prints ALREADY_PATCHED.
"""
import os
import sys

P = r'Z:\tsp\sumo_hpc\sumo_bridge\sweep_arms.py'
if not os.path.exists(P):
    raise SystemExit('missing %s' % P)

with open(P, 'rb') as fh:
    data = fh.read()
if b'CTM2_LIGHTSIM' in data:
    print('ALREADY_PATCHED')
    sys.exit(0)

E = b'\r\n' if b'\r\n' in data else b'\n'


def L(s):
    return s.replace(b'\n', E)


before = len(data)

# ---- 1. the arm's flag set, defined just before the CTM2_ARMS table ----
A1 = L(b'CTM2_ARMS = [\n')
n1 = data.count(A1)
assert n1 == 1, 'A1 count=%d' % n1
R1 = L(b'''#   _CTM2_LIGHTSIM  the same spillback payoff, but the block term comes from the
#                LightSim-style NETWORK CTM (ctm_lightsim.py) instead of the
#                equal-split hop rollout: per-movement turn ratios, saturation
#                cap, proportional merge/diverge. Two flags are forced off
#                because on the SUMO port they return BEFORE the payoff, so the
#                model would never be exercised:
#                  GAME_CONGESTION_GATE  reads q=0.0 (no detector queue is
#                      published) and HOLDs on `q=0.0 < 4.0`.
#                  NASH_CORRIDOR_MODE    (pinned True by the GAME_COOP base arm)
#                      returns before the `elif _gsol:` payoff branch.
_CTM2_LIGHTSIM = dict(
    _CTM2_SPILL,
    GAME_CONGESTION_GATE=False,
    NASH_CORRIDOR_MODE=False,
    GAME_CTM2_ROLLOUT=True,
    GAME_CTM2_LIGHTSIM=True,
    GAME_CTM2_LIGHTSIM_MAX_CELLS=12,
)
CTM2_ARMS = [
''')
data = data.replace(A1, R1, 1)

# ---- 2. the two arms (nash + utilitarian twin) ----
A2 = L(b'    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2", "utilitarian", '
       b'_CTM2_SPILL2),\n')
n2 = data.count(A2)
assert n2 == 1, 'A2 count=%d' % n2
R2 = A2 + L(b'    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_LIGHTSIM", "nash", '
            b'_CTM2_LIGHTSIM),\n'
            b'    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_LIGHTSIM", "utilitarian", '
            b'_CTM2_LIGHTSIM),\n')
data = data.replace(A2, R2, 1)

tmp = P + '.lightsim.tmp'
with open(tmp, 'wb') as fh:
    fh.write(data)
os.replace(tmp, P)
print('PATCHED size %d -> %d (EOL=%r)' % (before, len(data), E))
