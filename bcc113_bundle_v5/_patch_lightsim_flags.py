"""GAME_CTM2_LIGHTSIM (flag registration in specialized_modes.py).

EOL-aware. Idempotent: re-running prints ALREADY_PATCHED.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, 'shared_tsp_engine', 'specialized_modes.py')

with open(P, 'rb') as fh:
    data = fh.read()
if b'GAME_CTM2_LIGHTSIM' in data:
    print('ALREADY_PATCHED')
    sys.exit(0)

E = b'\r\n' if b'\r\n' in data else b'\n'


def L(s):
    return s.replace(b'\n', E)


before = len(data)

# ---- 1. the flag definitions, next to the rollout flag ----
A1 = L(b'GAME_CTM2_ROLLOUT = False\n')
n1 = data.count(A1)
assert n1 == 1, 'A1 count=%d' % n1
R1 = L(b'''GAME_CTM2_ROLLOUT = False
# LightSim-style NETWORK CTM as the ALTERNATIVE model for the block term
# (shared_tsp_engine/ctm_lightsim.py, after Su & Deng, arXiv:2602.21852): every
# turning movement carries a turn ratio, is masked by the signal state, capped
# at the saturation rate, and scaled proportionally on merge/diverge, instead of
# the equal-split hop approximation. Implies GAME_CTM2_ROLLOUT (it replaces that
# model, it does not stack on it). Default off (byte-identical).
GAME_CTM2_LIGHTSIM = False
GAME_CTM2_LIGHTSIM_MAX_CELLS = 12
''')
data = data.replace(A1, R1, 1)

# ---- 2. MODE_FLAGS registration (run_config keys reach engine globals) ----
A2 = L(b"    'GAME_CTM2_ROLLOUT',\n")
n2 = data.count(A2)
assert n2 == 1, 'A2 count=%d' % n2
R2 = L(b"    'GAME_CTM2_ROLLOUT',\n"
       b"    'GAME_CTM2_LIGHTSIM', 'GAME_CTM2_LIGHTSIM_MAX_CELLS',\n")
data = data.replace(A2, R2, 1)

tmp = P + '.lightsim.tmp'
with open(tmp, 'wb') as fh:
    fh.write(data)
os.replace(tmp, P)
print('PATCHED size %d -> %d' % (before, len(data)))
