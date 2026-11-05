r"""apply_port.py -- port the 2026-11-06 Aimsun engine changes into the SUMO fork.

Ports (from commits a5770dc..HEAD, shared_tsp_engine/):
  * tsp_games.py        new module (copied, not edited here)
  * ctm_twoclass.py     new module (copied, not edited here)
  * specialized_modes.py  flags, insertion-cap stretch, SOLVE_REQUIRES_GAIN,
                          GAME_SOLUTION decider, MODE_FLAGS
  * engine.py           ENGINE_BUILD tag

NOT portable (the SUMO fork does not carry the subsystems): DS-truth units
fix, rem_green_nextred_s ledger check, _game_ctm2_payoffs (needs
_cbql_ctm_geom / _vlt_advance_vph). See PORT_NOTES.md.

Every edit is exact-match with a count assertion: the script refuses to write
if any anchor does not appear exactly once, so it cannot half-apply.
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SM = os.path.join(HERE, "shared_tsp_engine", "specialized_modes.py")
ENG = os.path.join(HERE, "shared_tsp_engine", "engine.py")

# --------------------------------------------------------------------------
# specialized_modes.py
# --------------------------------------------------------------------------
IMPORT_NEW = '''import math
import numpy as np

try:  # one candidate set, many games (stdlib-only sibling module)
    try:
        from . import tsp_games as _tsp_games
    except ImportError:
        import tsp_games as _tsp_games
except Exception:  # pragma: no cover
    _tsp_games = None
'''

FLAGS_NEW = '''GR_DURATIONS_S = [5.0, 10.0, 15.0]

# Minimum viable committed action duration (s). 1.0: the GE / insertion seconds
# are SOLVED (shockwave objective), so a 1 s action is a valid solution. The old
# 5.0 floor discarded every sub-5 s solve (KG 2026-11-04: 35 of 36 solves picked
# 1 s, 22 decisions died on the floor). The solve must also LOWER total
# passenger delay (SOLVE_REQUIRES_GAIN), so a 1 s action only runs when it pays.
# Set 5.0 to restore the old floor.
MIN_ACTION_DURATION_S = 1.0
# Act on a solved GE / insertion only if the objective at the solved seconds is
# LOWER than at 0 s; otherwise the paths proposed actions the model itself said
# made things worse.
SOLVE_REQUIRES_GAIN = True
# Smallest green extension any path will commit (s). Declared so no reader falls
# back to a hidden 3.0 floor.
MIN_GE_EXTENSION_S = 1.0
# Let the insertion cap stretch to the green the shockwave model says the
# waiting bus needs, up to SW_INS_MAX_S (dormant until _sw_ins_needed_s exists).
SW_INS_STRETCH = True
SW_INS_MAX_S = 15.0
# GAME SOLUTION CONCEPT (shared_tsp_engine/tsp_games.py). Empty = the legacy
# dctsp_nash_bargain selection. Set to one of
#   nash | utilitarian | nash_welfare | egalitarian | kalai_smorodinsky |
#   stackelberg_bus | stackelberg_car | noncoop_grant
# to decide the SAME candidate set with that game. nash / utilitarian /
# nash_welfare / egalitarian reproduce the legacy rules exactly. Every pick
# logs [GAME_SOLVE].
GAME_SOLUTION = ''
GAME_TOL_BUS_FRAC = 0.25     # side-payment: share of joint surplus a player may lose
GAME_TOL_CAR_FRAC = 0.25
# Payoff model the games decide on. 'legacy' = analytic evaluator + Daganzo CTM
# cross cost. 'ctm2' needs the two-class CTM payoffs, which this build does not
# carry (see [GAME_CTM2_NA]); asking for it logs that and uses legacy.
GAME_PAYOFF_MODEL = 'legacy'
GAME_CTM2_HORIZON_S = 60.0
GAME_CTM2_IG_S = 5.0
'''

INS_STAR_OLD = '''    _ins_star = min(max(0.0, float(bus_eta_s) - _green_left), float(BXT_MAX_INS_S))
    _MIN_EFFECTIVE_GE_S = 1.0
    _solved_param = {'GE': _ge_star, 'GREEN_REALLOC': _ge_star, 'INS': _ins_star}
'''

INS_STAR_NEW = '''    # EFFECTIVE insertion cap: an arm's BXT_MAX_INS_S (6 s on CELLQ_GATED) was
    # shorter than the green a waiting bus needs to discharge, so every insertion
    # fell just short and only added cost. When the shockwave model says THIS bus
    # needs more, let the cap stretch to that need, up to SW_INS_MAX_S. The solve
    # must still lower total delay to act. Dormant on this build: the SUMO fork
    # has no _sw_ins_needed_s yet, so the hasattr guard leaves the cap alone.
    _ins_cap = float(BXT_MAX_INS_S)
    _ins_need = None
    if bool(globals().get('SW_INS_STRETCH', True)):
        try:
            if hasattr(self, '_sw_ins_needed_s'):
                _ins_need = self._sw_ins_needed_s(int(veh_id), time)
        except Exception:
            _ins_need = None
        _ins_max = float(globals().get('SW_INS_MAX_S', 15.0) or 15.0)
        if _ins_need is not None and _ins_cap < _ins_need <= _ins_max:
            _ins_cap = float(math.ceil(_ins_need))
    _ins_star = min(max(0.0, float(bus_eta_s) - _green_left), _ins_cap)
    _MIN_EFFECTIVE_GE_S = 1.0
    _solve_no_gain = None    # set when the shockwave solve says acting does not pay
    _solved_param = {'GE': _ge_star, 'GREEN_REALLOC': _ge_star, 'INS': _ins_star}
'''

DEBT_OLD = '            if not (a_s > 0.0 and _raw_deficit <= float(BXT_MAX_INS_S) + 1e-6):'
DEBT_NEW = '            if not (a_s > 0.0 and _raw_deficit <= _ins_cap + 1e-6):'

GE_OLD = '''            try:
                _opt_ge, _, _ = self.solve_green_extension(
                    min(_ge_star, _ge_ub), _ge_ub, time)
                if _opt_ge >= _MIN_EFFECTIVE_GE_S:
                    _mag = float(_opt_ge)
            except Exception:
                pass
'''

GE_NEW = '''            try:
                _opt_ge, _b0g, _b1g = self.solve_green_extension(
                    min(_ge_star, _ge_ub), _ge_ub, time)
                if (bool(globals().get('SOLVE_REQUIRES_GAIN', True))
                        and not (float(_b1g) + 1e-9 < float(_b0g))):
                    _mag = 0.0          # solve says it does not pay -> hold
                    _solve_no_gain = ('GE', float(_opt_ge), float(_b0g), float(_b1g))
                    _log_func(self, "[SOLVE_NO_GAIN] inter=%s t=%.0f GE opt=%.1fs "
                              "pax %.0f (no action) -> %.0f (solved): acting does not "
                              "lower total passenger delay -> hold"
                              % (getattr(self, 'id', '?'), float(time), _solve_no_gain[1],
                                 _solve_no_gain[2], _solve_no_gain[3]), force=True)
                elif _opt_ge >= _MIN_EFFECTIVE_GE_S:
                    _mag = float(_opt_ge)
            except Exception:
                pass
'''

STOPPED_OLD = '        if _bus_stopped and _mag < _MIN_EFFECTIVE_GE_S:'
STOPPED_NEW = '        if _bus_stopped and _mag < _MIN_EFFECTIVE_GE_S and _solve_no_gain is None:'

BP_UB_OLD = "        _bp_ub = float(BXT_MAX_INS_S) if _chosen_atype == 'INS' else _ge_ub"
BP_UB_NEW = "        _bp_ub = _ins_cap if _chosen_atype == 'INS' else _ge_ub"

INS_SOLVE_OLD = '''            try:
                _opt_bp, _, _ = self.solve_bus_phase_green(
                    min(_MIN_EFFECTIVE_GE_S, _bp_ub), _bp_ub, time)
                if _opt_bp >= _MIN_EFFECTIVE_GE_S:
                    _mag = float(_opt_bp)
            except Exception:
                pass
'''

INS_SOLVE_NEW = '''            try:
                _opt_bp, _b0b, _b1b = self.solve_bus_phase_green(
                    min(_MIN_EFFECTIVE_GE_S, _bp_ub), _bp_ub, time)
                if (bool(globals().get('SOLVE_REQUIRES_GAIN', True))
                        and not (float(_b1b) + 1e-9 < float(_b0b))):
                    _mag = 0.0          # solve says it does not pay -> hold
                    _solve_no_gain = ('INS', float(_opt_bp), float(_b0b), float(_b1b))
                    _log_func(self, "[SOLVE_NO_GAIN] inter=%s t=%.0f INS opt=%.1fs "
                              "pax %.0f (no action) -> %.0f (solved): acting does not "
                              "lower total passenger delay -> hold"
                              % (getattr(self, 'id', '?'), float(time), _solve_no_gain[1],
                                 _solve_no_gain[2], _solve_no_gain[3]), force=True)
                elif _opt_bp >= _MIN_EFFECTIVE_GE_S:
                    _mag = float(_opt_bp)
            except Exception:
                pass
'''

CLAMP_OLD = '''    elif _chosen_atype == 'INS' and _chosen_aparam > float(BXT_MAX_INS_S):
        # Clamp the disruptive insertion instead of committing the full
        # 15-20 s candidate (mode-commits-own-action bypasses BP_upper_bound).
        _chosen_aparam = float(BXT_MAX_INS_S)
'''

CLAMP_NEW = '''    elif _chosen_atype == 'INS' and _chosen_aparam > _ins_cap:
        # Clamp the disruptive insertion instead of committing the full
        # 15-20 s candidate (mode-commits-own-action bypasses BP_upper_bound).
        _chosen_aparam = _ins_cap
'''

GSOL_OLD = '''    if _corridor_ran:
        if _bi is None:'''

GSOL_NEW = '''    # GAME_SOLUTION: one named solution concept over the same candidate set.
    # Empty (default) leaves the legacy pick below byte-identical.
    _gsol = (str(globals().get('GAME_SOLUTION', '') or '').strip().lower()
             if _tsp_games is not None else '')
    _ctm2_B = None          # GAME_PAYOFF_MODEL='ctm2' phase benefit (unused here)
    if _corridor_ran:
        if _bi is None:'''

BRANCH_OLD = '''            return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)
    else:
'''

BRANCH_NEW = '''            return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)
    elif _gsol:
        # -- GAME_SOLUTION: decide the same candidate set with one named game --
        # Payoffs exactly as the legacy Tier-1 frontier builds them: B = phase
        # total (bus + mainline; car-only on monitor ticks), C = cross cost,
        # b = bus-only benefit. See tsp_games for every concept's rule.
        _gc = []
        _pmodel = str(globals().get('GAME_PAYOFF_MODEL', 'legacy') or 'legacy').lower()
        if _pmodel == 'ctm2' and not hasattr(self, '_game_ctm2_payoffs'):
            # The two-class CTM payoffs need _cbql_ctm_geom / _vlt_advance_vph,
            # which this build does not carry. Say so rather than silently score
            # a different model than the Ainsun arm of the same name.
            try:
                _log_func(self, "[GAME_CTM2_NA] inter=%s GAME_PAYOFF_MODEL=ctm2 needs "
                                "_cbql_ctm_geom/_vlt_advance_vph (absent on this "
                                "build) -> legacy payoffs"
                          % getattr(self, 'id', '?'), force=True)
            except Exception:
                pass
        _pmodel = 'legacy'
        for _c in cand:
            _bt = _nash_phase_total_bps(self, _c[0], _c[1],
                                        (0.0 if _monitor else _c[4]))
            _gc.append(_tsp_games.Cand(str(_c[0]), float(_c[1]), float(_bt),
                                       float(_c[5]), 0.0 if _monitor else float(_c[4])))
        _gp = _tsp_games.Params(
            p_bus=float(p_T), p_car=float(p_C),
            net_ratio=float(globals().get('NASH_NET_GATE_RATIO', 1.0) or 1.0),
            tol_bus_abs=float(globals().get('NASH_COOP_BUS_TOL', 0.0) or 0.0),
            tol_car_abs=float(globals().get('NASH_COOP_CAR_TOL', 0.0) or 0.0),
            tol_bus_frac=float(globals().get('GAME_TOL_BUS_FRAC', 0.25) or 0.0),
            tol_car_frac=float(globals().get('GAME_TOL_CAR_FRAC', 0.25) or 0.0),
            fair_w=float(globals().get('NASH_COOP_FAIR_W', 0.0) or 0.0))
        try:
            _bi, _gd = _tsp_games.solve(_gsol, _gc, _gp)
        except Exception as _ge:
            _log_func(self, "[GAME_SOLVE] inter=%s game=%s error %r"
                      % (getattr(self, 'id', '?'), _gsol, _ge))
            _bi, _gd = None, {'reason': 'error %r' % (_ge,), 'nfeas': 0, 'n': len(_gc)}
        _frontier = [(g.B, g.C, g.b) for g in _gc]
        _ncand = len(_gc)
        _nfeas = int(_gd.get('nfeas', 0) or 0)
        try:
            _log_func(self, "[GAME_SOLVE] inter=%s t=%.0f game=%s payoff=%s bus=%s n=%d "
                            "feas=%d pick=%s%s%s" % (
                getattr(self, 'id', '?'), float(time), _gsol, _pmodel, veh_id, _ncand,
                _nfeas,
                ('%s_%gs u_bus=%.0f u_car=%.0f joint=%.0f' % (
                    _gc[_bi].family, _gc[_bi].duration, _gc[_bi].u_bus,
                    _gc[_bi].u_car, _gc[_bi].joint)) if _bi is not None else 'NO_ACTION',
                (' (%s)' % _gd.get('reason')) if _bi is None and _gd.get('reason') else '',
                (' eq=%s' % _gd.get('equilibria')) if _gd.get('equilibria') else '')
                + (' dominant=1' if _gd.get('dominant') else ''),
                      force=True)
        except Exception:
            pass
        if _bi is None:
            return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)
    else:
'''

GATE_OLD = '''    _bps_gate = _bps
    if bool(globals().get('NASH_MIN_GAIN_INCLUDE_MAIN', True)) and not _monitor:
'''

GATE_NEW = '''    _bps_gate = _bps
    if _ctm2_B is not None:
        _bps_gate = max(float(_bps), _ctm2_B)    # same model as the game's payoffs
    elif bool(globals().get('NASH_MIN_GAIN_INCLUDE_MAIN', True)) and not _monitor:
'''

BPS_TOT_OLD = '''    _bps_tot = _nash_phase_total_bps(self, _at, _ap,
                                     (0.0 if _monitor else _bps))
'''

BPS_TOT_NEW = '''    _bps_tot = (_ctm2_B if _ctm2_B is not None else
                _nash_phase_total_bps(self, _at, _ap,
                                      (0.0 if _monitor else _bps)))
'''

FLAGLIST_OLD = "    'GE_DURATIONS_S', 'INS_DURATIONS_S', 'ER_DURATIONS_S', 'GR_DURATIONS_S',\n"
FLAGLIST_NEW = ("    'GE_DURATIONS_S', 'INS_DURATIONS_S', 'ER_DURATIONS_S', 'GR_DURATIONS_S',\n"
                "    # game ladder + solved-magnitude gates (2026-11-06 port)\n"
                "    'MIN_ACTION_DURATION_S', 'MIN_GE_EXTENSION_S', 'SOLVE_REQUIRES_GAIN',\n"
                "    'SW_INS_STRETCH', 'SW_INS_MAX_S',\n"
                "    'GAME_SOLUTION', 'GAME_TOL_BUS_FRAC', 'GAME_TOL_CAR_FRAC',\n"
                "    'GAME_PAYOFF_MODEL', 'GAME_CTM2_HORIZON_S', 'GAME_CTM2_IG_S',\n")

SM_EDITS = [
    ("import block", "import math\nimport numpy as np\n", IMPORT_NEW),
    ("flags", "GR_DURATIONS_S = [5.0, 10.0, 15.0]\n", FLAGS_NEW),
    ("_ins_cap", INS_STAR_OLD, INS_STAR_NEW),
    ("ins deficit cap", DEBT_OLD, DEBT_NEW),
    ("GE solve", GE_OLD, GE_NEW),
    ("stopped bypass", STOPPED_OLD, STOPPED_NEW),
    ("bp_ub", BP_UB_OLD, BP_UB_NEW),
    ("INS solve", INS_SOLVE_OLD, INS_SOLVE_NEW),
    ("INS clamp", CLAMP_OLD, CLAMP_NEW),
    ("_gsol init", GSOL_OLD, GSOL_NEW),
    ("game branch", BRANCH_OLD, BRANCH_NEW),
    ("bps gate", GATE_OLD, GATE_NEW),
    ("bps tot", BPS_TOT_OLD, BPS_TOT_NEW),
    ("MODE_FLAGS", FLAGLIST_OLD, FLAGLIST_NEW),
]

ENG_EDITS = [
    ("ENGINE_BUILD",
     'ENGINE_BUILD = "2026-11-04T2330-sumo-cbql-cellbp"',
     'ENGINE_BUILD = "2026-11-06T1200-sumo-game-ladder"'),
]


def load(path):
    with io.open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
        return f.read()


def save(path, text):
    with io.open(path, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
        f.write(text)


def plan(text, edits, name):
    crlf = "\r\n" in text
    norm = text.replace("\r\n", "\n")
    out = norm
    for label, old, new in edits:
        n = out.count(old)
        if n != 1:
            raise SystemExit("REFUSING: %s / %s matched %d times (need 1)"
                             % (name, label, n))
        out = out.replace(old, new)
    if crlf:
        out = out.replace("\n", "\r\n")
    return out


def main():
    sm = load(SM)
    eng = load(ENG)
    new_sm = plan(sm, SM_EDITS, "specialized_modes.py")
    new_eng = plan(eng, ENG_EDITS, "engine.py")
    if "--dry-run" in sys.argv:
        print("all %d specialized_modes + %d engine anchors matched once"
              % (len(SM_EDITS), len(ENG_EDITS)))
        return 0
    save(SM, new_sm)
    save(ENG, new_eng)
    print("applied: specialized_modes.py (%d edits), engine.py (%d edits)"
          % (len(SM_EDITS), len(ENG_EDITS)))
    left = new_sm.count("_note_swallow_spm")
    print("stray _note_swallow_spm refs: %d (must be 0)" % left)
    return 0


if __name__ == "__main__":
    sys.exit(main())
