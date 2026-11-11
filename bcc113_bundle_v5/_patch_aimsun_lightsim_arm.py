"""Add the _CTM2_SPILL2_LIGHTSIM twins to the Aimsun arm registry.

Twin of _CTM2_SPILL2 with ONLY the block model swapped: the LightSim-style
network CTM (shared_tsp_engine/ctm_lightsim.py) instead of the scalar per-phase
jam fraction. Keeps the congestion gate and the corridor branch ON, because the
SUMO port needed them off only for its dead detector queue.

EOL-aware, idempotent.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, 'champion_search.py')
MARK = b'_CTM2_SPILL2_LIGHTSIM'

with open(P, 'rb') as fh:
    data = fh.read()
if MARK in data:
    print('ALREADY_PATCHED')
    sys.exit(0)

E = b'\r\n' if b'\r\n' in data else b'\n'


def L(s):
    return s.replace(b'\n', E)


# Insert after the _CTM2_SPILL2_CHAIN block, i.e. after this line ends.
ANCHOR = b'"GAME_CTM2_CHAIN_REACH_M": 200.0}))'
n = data.count(ANCHOR)
assert n == 1, 'anchor count=%d' % n
i = data.find(ANCHOR)
j = data.find(E, i)
assert j > i
before = len(data)

NEW = L(b'''
    # _CTM2_SPILL2_LIGHTSIM twins (2026-11-09): the SPILL2 flag set with the
    # BLOCK term priced by the LightSim-style NETWORK CTM
    # (shared_tsp_engine/ctm_lightsim.py, after Su & Deng arXiv:2602.21852)
    # instead of the scalar per-phase jam fraction: per-movement turn ratios,
    # saturation cap, and proportional merge/diverge resolution over the same
    # 2-hop subnet the inline rollout uses. GAME_CTM2_LIGHTSIM IMPLIES
    # GAME_CTM2_ROLLOUT (it replaces that model, it does not stack on it).
    #   READOUT='entry' is deliberate. 'worst' (the SUMO default) reads the
    #   busiest cell ANYWHERE on the receiving link, which saturates at 1.0
    #   whenever that link's OWN stop line is red: measured 33% of decisions at
    #   1.0 vs 5% for the inline rollout, with median entry occupancy 0.04.
    #   'entry' is cell 0, the cell a discharging movement enters and the one
    #   the CTM itself gates on.
    # The congestion gate and the corridor branch stay ON here: the SUMO port
    # had to switch them off only because its detector queue reads 0.0.
    for _gname, _gsol in GAME_SOL_ARMS:
        _cname = _gname + "_CTM2_SPILL2_LIGHTSIM"
        if _cname not in {a["name"] for a in ARMS}:
            ARMS.append(_with_overrides(
                "CHAMP_ADAPTIVE_DSW_GAME_COOP", _cname,
                {"GAME_SOLUTION": _gsol, "NASH_COOPERATIVE": False,
                 "GAME_TOL_BUS_FRAC": 0.25, "GAME_TOL_CAR_FRAC": 0.25,
                 "GAME_PAYOFF_MODEL": "ctm2", "GAME_CTM2_HORIZON_S": 60.0,
                 "GAME_CTM2_SPILLBACK": True, "GAME_CTM2_SPILLBACK_GAMMA": 1.0,
                 "GAME_BUS_IN_HORIZON": True,
                 "GAME_CONGESTION_GATE": True,
                 "GAME_CONGESTION_MIN_QUEUE_VEH": 0.0,
                 "GAME_CONGESTION_MAX_DS": 0.0,
                 "GAME_CONGESTION_MAX_JAM": 0.90,
                 "GAME_CROSS_STARVE_MULT": 1.5,
                 "GAME_CTM2_ROLLOUT": True,
                 "GAME_CTM2_LIGHTSIM": True,
                 "GAME_CTM2_LIGHTSIM_MAX_CELLS": 12,
                 "GAME_CTM2_LIGHTSIM_READOUT": "entry"}))
''')
data = data[:j + len(E)] + NEW + data[j + len(E):]

tmp = P + '.lsarm.tmp'
with open(tmp, 'wb') as fh:
    fh.write(data)
os.replace(tmp, P)
print('PATCHED size %d -> %d (EOL=%r)' % (before, len(data), E))
