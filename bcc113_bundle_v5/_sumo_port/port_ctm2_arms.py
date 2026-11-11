# -*- coding: utf-8 -*-
"""Add the CTM2 payoff arms to the SUMO fork's sweep_arms.CHAMPION_ARMS.

    python _sumo_port/port_ctm2_arms.py            # apply (backs up first)
    python _sumo_port/port_ctm2_arms.py --check    # report only

Mirrors champion_search.GAME_SOL_*_CTM2[_SPILL[_2]] exactly (same names, same
flags), so a ladder job can name them. The engine now carries
_game_ctm2_payoffs / _cbql_ctm_geom / _vlt_advance_vph and the congestion +
bus-in-horizon gates, which is what these flags drive.
"""
import io
import os
import shutil
import sys

FORK = 'Z:/tsp/sumo_hpc/sumo_bridge/sweep_arms.py'
CHECK_ONLY = '--check' in sys.argv

STALE = """# The _CTM2 twins are deliberately absent: GAME_PAYOFF_MODEL='ctm2' needs
# _cbql_ctm_geom/_vlt_advance_vph, which this build does not carry (the engine
# logs [GAME_CTM2_NA] and falls back to legacy payoffs).
"""

BLOCK = '''
# -- CTM2 PAYOFF ARMS (2026-11-06) --------------------------------------------
# Mirrors champion_search exactly: the GAME_COOP arm with ONLY the payoff model
# switched (GAME_PAYOFF_MODEL='ctm2'), so legacy vs CTM2 separates the PAYOFF
# MODEL from the game played. The engine carries _game_ctm2_payoffs (built on
# _cbql_ctm_geom + _vlt_advance_vph); if ctm_twoclass cannot be imported it logs
# [GAME_CTM2_NA] and falls back to legacy payoffs, which is why these arms were
# previously refused outright.
#   _CTM2        two-class CTM payoffs, free-sink discharge
#   _CTM2_SPILL  + GAME_CTM2_SPILLBACK (discharge throttled by the receiving
#                link's free space), bus-in-horizon and congestion-band gates
#   _CTM2_SPILL2 the productive-action variant: congestion upper bound from the
#                cell-state jam fraction (MAX_JAM 0.90, MAX_DS off, MIN_QUEUE 0)
#                and the cross cost scaled by GAME_CROSS_STARVE_MULT=1.5
_CTM2_BASE = {"GAME_PAYOFF_MODEL": "ctm2", "GAME_CTM2_HORIZON_S": 60.0}
_CTM2_SPILL = dict(
    _CTM2_BASE,
    GAME_CTM2_SPILLBACK=True, GAME_CTM2_SPILLBACK_GAMMA=1.0,
    GAME_BUS_IN_HORIZON=True,
    GAME_CONGESTION_GATE=True,
    GAME_CONGESTION_MIN_QUEUE_VEH=4.0,
    GAME_CONGESTION_MAX_DS=0.90,
)
_CTM2_SPILL2 = dict(
    _CTM2_BASE,
    GAME_CTM2_SPILLBACK=True, GAME_CTM2_SPILLBACK_GAMMA=1.0,
    GAME_BUS_IN_HORIZON=True,
    GAME_CONGESTION_GATE=True,
    GAME_CONGESTION_MIN_QUEUE_VEH=0.0,
    GAME_CONGESTION_MAX_DS=0.0,
    GAME_CONGESTION_MAX_JAM=0.90,
    GAME_CROSS_STARVE_MULT=1.5,
)
CTM2_ARMS = [
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_NULL_CTM2", "null", _CTM2_BASE),
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2", "nash", _CTM2_BASE),
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL", "nash", _CTM2_SPILL),
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL", "utilitarian", _CTM2_SPILL),
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2", "nash", _CTM2_SPILL2),
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2", "utilitarian", _CTM2_SPILL2),
]
for _cname, _cgsol, _cflags in CTM2_ARMS:
    if any(a.get("name") == _cname for a in CHAMPION_ARMS):
        continue
    _cbase = next((a for a in CHAMPION_ARMS
                   if a.get("name") == "CHAMP_ADAPTIVE_DSW_GAME_COOP"), None)
    if _cbase is None:
        break
    _carm = {k: v for k, v in _cbase.items() if k != "reward_overrides"}
    _carm["name"] = _cname
    _carm["reward_overrides"] = dict(
        _cbase.get("reward_overrides") or {},
        GAME_SOLUTION=_cgsol, NASH_COOPERATIVE=False,
        GAME_TOL_BUS_FRAC=0.25, GAME_TOL_CAR_FRAC=0.25, **_cflags)
    CHAMPION_ARMS.append(_carm)
'''

ANCHOR = """        GAME_SOLUTION=_gsol, NASH_COOPERATIVE=False,
        GAME_TOL_BUS_FRAC=0.25, GAME_TOL_CAR_FRAC=0.25)
    CHAMPION_ARMS.append(_garm)
"""


def read(p):
    with io.open(p, encoding='utf-8', newline='') as fh:
        return fh.read()


def write(p, s):
    with io.open(p, 'w', encoding='utf-8', newline='') as fh:
        fh.write(s)


def main():
    src = read(FORK)
    nl = '\r\n' if '\r\n' in src else '\n'
    anchor = ANCHOR.replace('\n', nl)
    if 'CTM2_ARMS' in src:
        print('sweep_arms.py: CTM2 arms already present, nothing to do')
        return 0
    if anchor not in src:
        print('ABORT: GAME_SOLUTION_ARMS loop anchor not found in sweep_arms.py')
        return 2
    print('target: sweep_arms.py (%d lines, nl=%r)' % (src.count(nl), nl))
    if CHECK_ONLY:
        print('--check: anchor resolves, nothing written')
        return 0
    out = src.replace(anchor, anchor + BLOCK.replace('\n', nl), 1)
    if STALE.replace('\n', nl) in out:
        out = out.replace(STALE.replace('\n', nl),
                          "# The _CTM2 twins are declared below (engine port 2026-11-06).\n"
                          .replace('\n', nl), 1)
    shutil.copyfile(FORK, FORK + '.bak_20261106_ctm2arms')
    write(FORK, out)
    try:
        compile(out, 'sweep_arms.py', 'exec')
        print('  ok    sweep_arms.py compiles')
    except SyntaxError as e:
        print('  FAIL  sweep_arms.py: %s line %s' % (e.msg, e.lineno))
        return 1
    print('  ok    +6 CTM2 arms appended to CHAMPION_ARMS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
