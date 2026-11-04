# -*- coding: utf-8 -*-
"""Add [CELLQ_HELD] / [CELLQ_COMMIT] diagnostics to the CellQ decision path.

WHY: CHAMP_ADAPTIVE_DSW_CELLQ_GATED produces 2 TSP extensions across 5 Logan
seeds. The decider is not silent -- it runs every tick -- but each of its six
sequential vetoes forces NO_ACTION without saying which one fired, so "barely
acting" cannot be attributed. This patch names the binding gate and its margin.

The file contains legacy mojibake, so everything is done on a latin-1 round trip
and anchored on ASCII-only code lines. Every anchor is asserted to be unique.
"""
import io
import sys

SP = r"shared_tsp_engine/specialized_modes.py"
CS = "champion_search.py"

ANCHOR_CONST = "CELLQLEARN_MIN_GAIN_S = 0.0\n"
CONSTS = (
    "CELLQLEARN_MIN_GAIN_S = 0.0\n"
    "# [CELLQ_HELD] (2026-11-02): the CellQ decider's six vetoes all force\n"
    "# NO_ACTION silently, so a run with few extensions cannot say which gate\n"
    "# refused. One line per rejected decision, naming the gate and its margin.\n"
    "# Counted on the CONTROLLER (per run), never in a module global: a global\n"
    "# survives across the seeds of one Aimsun process and silences the rest.\n"
    "CELLQ_HELD_LOG_MAX   = 8     # rejected decisions logged per junction per RUN\n"
    "CELLQ_COMMIT_LOG_MAX = 400   # admitted actions logged per junction per RUN\n"
)

ANCHOR_HELPERS = "def _nash_held_ok(self, slot='main'):"
HELPERS = '''def _cellq_held_ok(self):
    """Consume one [CELLQ_HELD] slot at this junction; False when exhausted."""
    try:
        _cap = int(globals().get('CELLQ_HELD_LOG_MAX', 8) or 0)
    except Exception:
        _cap = 8
    if _cap <= 0:
        return False
    try:
        _n = int(getattr(self, '_cellq_held_n', 0))
        if _n >= _cap:
            return False
        setattr(self, '_cellq_held_n', _n + 1)
        return True
    except Exception:
        return False


def _cellq_held_log(self, time, veh_id, veto, prop, eff_delay, side_ratio,
                    local_sat):
    """One [CELLQ_HELD] line per rejected CellQ decision.

    `veto` is the FIRST failing constraint, with the two quantities that
    compare against each other, so the margin is readable without the code.
    `prop` is the action that was discarded -- logging only the veto would hide
    whether the solver proposed anything worth having.
    """
    if not _cellq_held_ok(self):
        return
    try:
        _log_func(
            self,
            f"[CELLQ_HELD] inter={self.id} t={float(time):.1f} bus={veh_id} "
            f"veto={veto} proposed={prop[0]}_{float(prop[1]):.0f}s "
            f"eff_delay={float(eff_delay):.1f}s "
            f"side_ratio={float(side_ratio):.3f} "
            f"local_sat={float(local_sat):.3f}")
    except Exception:
        pass


def _cellq_commit_log(self, time, veh_id, atype, aparam, eff_delay,
                      side_ratio, local_sat):
    """One [CELLQ_COMMIT] line per ADMITTED CellQ action.

    Unthrottled up to CELLQ_COMMIT_LOG_MAX because the count is the measurement.
    The sim_time is what makes concurrency testable: group the lines by cycle and
    a post-run script can show how many junctions acted in the same cycle, which
    is the question the 2-grant total could not answer.
    """
    try:
        _cap = int(globals().get('CELLQ_COMMIT_LOG_MAX', 400) or 400)
        _n = int(getattr(self, '_cellq_commit_n', 0))
        if _cap <= 0 or _n >= _cap:
            return
        setattr(self, '_cellq_commit_n', _n + 1)
    except Exception:
        pass
    try:
        _log_func(
            self,
            f"[CELLQ_COMMIT] inter={self.id} t={float(time):.1f} bus={veh_id} "
            f"action={atype}_{float(aparam):.0f}s "
            f"eff_delay={float(eff_delay):.1f}s "
            f"side_ratio={float(side_ratio):.3f} "
            f"local_sat={float(local_sat):.3f}")
    except Exception:
        pass


'''

START = "    _bxt_min_delay_s = float(globals().get('CELLQLEARN_MIN_GAIN_S',"
ENDMARK = "if (_local_sat > _sat_veto and not _explore_bypass"

BLOCK = '''    _bxt_min_delay_s = float(globals().get('CELLQLEARN_MIN_GAIN_S',
                                           CELLQLEARN_MIN_GAIN_S) or 0.0)
    if _bxt_min_delay_s <= 0.0:
        _bxt_min_delay_s = float(SELFORG_MIN_BUS_DELAY_S)
    # Every branch below forces NO_ACTION. _cellq_veto records the FIRST failing
    # constraint (with both sides of the comparison) and _cellq_prop keeps the
    # action that was discarded, so a refused decision is attributable.
    _cellq_veto = None
    _cellq_prop = (_chosen_atype, _chosen_aparam)
    if eff_delay < _bxt_min_delay_s and not _explore_bypass:
        _cellq_veto = 'min_gain(%.1f<%.1f)' % (eff_delay, _bxt_min_delay_s)
        _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif (_chosen_atype in _solved_param
          and _chosen_aparam < _MIN_EFFECTIVE_GE_S and not _explore_bypass):
        _cellq_veto = 'solved_deficit(%.1f<%.1f)' % (
            _chosen_aparam, _MIN_EFFECTIVE_GE_S)
        _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif (not _explore_bypass) and _side_ratio > float(
            BXT_GE_BALANCE_FACTOR if _chosen_atype == 'GE'
            else BXT_BALANCE_FACTOR):
        _cellq_veto = 'side_ratio(%.3f>%.3f)' % (
            _side_ratio,
            float(BXT_GE_BALANCE_FACTOR if _chosen_atype == 'GE'
                  else BXT_BALANCE_FACTOR))
        _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif _chosen_atype == 'INS' and _chosen_aparam > float(BXT_MAX_INS_S):
        _chosen_aparam = float(BXT_MAX_INS_S)

    # Absolute main-approach saturation veto: refuse to extend into a jam. It is
    # ABSOLUTE, so on a saturated corridor (density near jam is the normal state
    # where buses are actually held) it can suppress every candidate -- the
    # [CELLQ_HELD] tally is what distinguishes this from the min-gain gate.
    try:
        _kj = max(float(getattr(self, 'JamDensity', 150.0)) or 150.0, 1.0)
        _ds = []
        for _row in (getattr(self, 'UpDenList', []) or []):
            try:
                for _v in _row:
                    _ds.append(float(_v))
            except TypeError:
                _ds.append(float(_row))
        _local_sat = max(_ds) / _kj if _ds else 0.0
    except Exception:
        _local_sat = 0.0
    _sat_veto = float(globals().get('CELLQLEARN_SAT_VETO', 0.85) or 0.85)
    if (_local_sat > _sat_veto and not _explore_bypass
            and _chosen_atype != 'NO_ACTION'):
        _cellq_veto = 'local_sat(%.3f>%.2f)' % (_local_sat, _sat_veto)
        _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0

    if _cellq_veto is not None:
        _cellq_held_log(self, time, veh_id, _cellq_veto, _cellq_prop,
                        eff_delay, _side_ratio, _local_sat)
    elif _chosen_atype != 'NO_ACTION':
        _cellq_commit_log(self, time, veh_id, _chosen_atype, _chosen_aparam,
                          eff_delay, _side_ratio, _local_sat)
'''


def patch_specialized():
    with io.open(SP, 'r', encoding='latin-1', newline='') as fh:
        s = fh.read()
    crlf = '\r\n' in s
    s = s.replace('\r\n', '\n')

    assert s.count(ANCHOR_CONST) == 1, "const anchor not unique"
    assert s.count(ANCHOR_HELPERS) == 1, "helper anchor not unique"
    assert s.count(START) == 1, "start anchor not unique"
    assert s.count(ENDMARK) == 1, "end anchor not unique"
    assert '_cellq_held_log' not in s, "already patched"

    s = s.replace(ANCHOR_CONST, CONSTS, 1)

    a = s.index(START)
    e = s.index(ENDMARK, a)
    m = s.index("_chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0", e)
    m = s.index("\n", m) + 1
    old = s[a:m]
    assert old.count("_chosen_atype, _chosen_aparam, _chosen_idx") == 4, \
        "unexpected veto-branch count: %d" % old.count("_chosen_atype")
    s = s[:a] + BLOCK + s[m:]

    s = s.replace(ANCHOR_HELPERS, HELPERS + ANCHOR_HELPERS, 1)

    if crlf:
        s = s.replace('\n', '\r\n')
    with io.open(SP, 'w', encoding='latin-1', newline='') as fh:
        fh.write(s)
    print("patched", SP)


ANCHOR_CS = '''# Register the ACT variant as a learner (train-then-eval); without this it runs
# with a cold Q-table and produces byte-identical results to GATED regardless of
# any override (see the LEARNING_ARMS comment and champion_search.py:187).
if "CHAMP_ADAPTIVE_DSW_CELLQ_ACT" not in LEARNING_ARMS:
    LEARNING_ARMS.add("CHAMP_ADAPTIVE_DSW_CELLQ_ACT")
'''

CS_ADD = ANCHOR_CS + '''

# CELLQ_OPEN (2026-11-02): the LOGAN CellQ overlay fires 2 extensions in 5 seeds.
# [CELLQ_HELD] attributes each refusal; this arm is the "let it act" side of the
# A/B, and changes ONLY the admission gates -- never the signal safety bounds
# (min green, intergreen, max extension), which stay enforced downstream.
#   CELLQLEARN_MIN_GAIN_S 15 -> 5 s : a 6 s grant (MAX_GE_EXTENSION_S) can never
#       clear a 15 s expected-delay bar, so the gate was unreachable by design.
#   CELLQLEARN_SAT_VETO 0.85 -> 0.95 : the veto is ABSOLUTE; on a corridor where
#       a held bus implies a near-jam approach it suppresses every candidate.
#   DECIDER_COST_VETO_RATIO 1.5 -> 2.5 : allow a 2.5x car cost against bus gain.
#   BXT_NET_BENEFIT_GATE off : it prices the CTM cascade, which is already ON via
#       CASCADE_COST_MODE; keeping both double-charges the same downstream effect.
# No cooldown flag: TSP_COOLDOWN_OVERRIDE_S is already 0.0 for Logan, and the
# cooldown lives on each controller, so independent junctions already act in the
# same cycle. TSP_RATE_LIMIT_MODE bounds the rate instead (1 INS per cycle, one
# action per phase instance), which is what keeps the car cascade in check.
ARMS += [
    _with_overrides(
        "CHAMP_ADAPTIVE_DSW_CELLQ_GATED_LOGAN",
        "CHAMP_ADAPTIVE_DSW_CELLQ_GATED_LOGAN_OPEN",
        {"CELLQLEARN_MIN_GAIN_S": 5.0,
         "CELLQLEARN_SAT_VETO": 0.95,
         "DECIDER_COST_VETO_RATIO": 2.5,
         "BXT_NET_BENEFIT_GATE": False,
         "TSP_RATE_LIMIT_MODE": True,
         "CELLQ_HELD_LOG_MAX": 60}),
]
if "CHAMP_ADAPTIVE_DSW_CELLQ_GATED_LOGAN_OPEN" not in LEARNING_ARMS:
    LEARNING_ARMS.add("CHAMP_ADAPTIVE_DSW_CELLQ_GATED_LOGAN_OPEN")
'''


def patch_champion():
    with io.open(CS, 'r', encoding='utf-8', newline='') as fh:
        s = fh.read()
    crlf = '\r\n' in s
    s = s.replace('\r\n', '\n')
    assert s.count(ANCHOR_CS) == 1, "champion anchor not unique"
    assert 'CELLQ_GATED_LOGAN_OPEN' not in s, "already patched"
    s = s.replace(ANCHOR_CS, CS_ADD, 1)
    if crlf:
        s = s.replace('\n', '\r\n')
    with io.open(CS, 'w', encoding='utf-8', newline='') as fh:
        fh.write(s)
    print("patched", CS)


if __name__ == '__main__':
    patch_specialized()
    patch_champion()
    print("OK")
