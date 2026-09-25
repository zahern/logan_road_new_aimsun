"""
Unit tests for the shared TSP strategy dispatch:

  1. parse_action_token / action_label round-trips (every candidate label the
     modes can emit maps to an executable kind + duration).
  2. Side-cost single-counting: _dctsp_eval_action must use the raw pax·s
     value from _dctsp_cross_traffic_delay_s (no extra CarOcc/NETWORK_FACTOR).
  3. Per-mode candidate generation differentiation: ZIG / MP-ECTM / BXT /
     BARGAIN produce distinct candidate sets from identical inputs.
  4. End-to-end engine wiring: a mode-generated candidate flows through the
     shared Pareto layer and is actually EXECUTED (signal-change stub called),
     for both the scalar-argmax path and the Pareto path.

Run:  python tests/test_strategy_dispatch.py        (any python with numpy)
      pytest tests/test_strategy_dispatch.py
"""
import os
import sys
import types

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
# Engine guards `from AAPI import *`; a stub keeps any direct import quiet.
sys.modules.setdefault('AAPI', types.ModuleType('AAPI'))

import numpy as np

import shared_tsp_engine.specialized_modes as spm
import shared_tsp_engine.engine as eng


# ─────────────────────────────────────────────────────────────────────────────
# Fake controller: the minimum surface the mode generators + evaluate use.
# ─────────────────────────────────────────────────────────────────────────────

class FakeStats:
    def __init__(self):
        self.events = []

    def record_tsp_event(self, jct, kind):
        self.events.append((jct, kind))

    def record_tsp_skip(self, jct, reason):
        self.events.append((jct, f"skip:{reason}"))

    def record_tsp_extension_duration(self, jct, dur):
        self.events.append((jct, f"ext:{dur}"))

    def record_tsp_insertion_duration(self, jct, dur):
        self.events.append((jct, f"insdur:{dur}"))

    def record_tsp_insertion_wait(self, jct, wait):
        self.events.append((jct, f"inswait:{wait}"))


class FakeController:
    """Duck-typed IntersectionController for unbound-method calls."""

    def __init__(self, bus_phase=2, cross_pax_per_s=2.0):
        self.id = 17383
        self.node_id = 17383
        self.BusOcc = 40.0
        self.CarOcc = 1.6
        self.BusPhase = bus_phase
        self.BusPhaseDuration = 20.0
        self.BP_lower_bound = 10.0
        self.BP_upper_bound = 40.0
        self.config = {'CycleTime': 135.0, 'MinGreen': 5.0}
        self.phase_list = [1, 2, 3]
        self.cycle_len_s = float(self.config.get('CycleTime', 135))
        self.tsp_cooldown_seconds = 60.0
        self._seq_max_per_cycle = 0
        self._seq_window_start = -1.0
        self._seq_window_count = 0
        self.SaturationFlow = 1800.0
        self.JamDensity = 200.0
        self.UpFlowList = np.array([[400.0, 420.0], [300.0, 310.0], [200.0, 210.0]])
        self.RedDurationList = np.array([[60.0, 55.0], [40.0, 45.0], [30.0, 20.0]])
        self.MaxQueueLength = np.array([[3.0, 4.0]])
        self.OtherDelay = np.zeros(3)
        self.SideDelayBaseline = np.zeros(3)
        self._nominal_phase_durations = {}
        # engine evaluate state
        self.flag = 0
        self.TSPStrategy = 0
        self.last_tsp_action_time = -1e9
        self._tsp_cycle_grant_until = -1.0
        self._reward_no_action_until = -1.0
        self._harmony_prearm = None
        self._corridor_coord = None
        self._phases_to_restore = {}
        self.last_detected_bus_id = -1
        self._last_sigma = 0.0
        self.previous_phase = 0
        self.BusPhaseEndTime = 0.0
        self.TimeToTerminateBusPhase = 0.0
        self.TSPActiveTime = 0.0
        self._ge_debt_s = 0.0
        self._ge_opt_GE = 0.0
        self.stats = FakeStats()
        self._cross_pax_per_s = float(cross_pax_per_s)
        # engine grew detection-recording + debounce state the stub must honor
        self._last_detection_t = -1e9

        def _record_detection(t, *a, **k):
            self._last_detection_t = float(t)
        self._record_detection = _record_detection
        # overridable evaluation results
        self.no_action_delay_s = 40.0
        self.ge_eval = (500.0, 10.0, 5.0)     # bus_saved, other_inc, side_inc
        self.ins_eval = (600.0, 20.0, 10.0)

    # ── stubs the generators / evaluate call ────────────────────────────────
    def _dctsp_cross_traffic_delay_s(self, action_s, queue_elapsed_s=0.0, phases=None):
        # Already pax·s — occupancy + network factor applied "inside".
        if phases == [0]:
            return 0.5 * max(0.0, float(action_s))
        return self._cross_pax_per_s * max(0.0, float(action_s))

    @staticmethod
    def _safe_array_sum(arr):
        return float(np.nan_to_num(np.asarray(arr, dtype=float)).sum())

    def _estimated_other_vehicle_occupancy(self):
        return 1.6

    def _reward_estimate_no_action(self, time, timeSta, bus_eta_s):
        return self.no_action_delay_s

    def _reward_evaluate_ge(self, ge_s, time, timeSta, bus_eta_s):
        return self.ge_eval

    def _reward_evaluate_insertion(self, ins_dur, time, timeSta, bus_eta_s):
        return self.ins_eval

    def highlight_bus(self, veh_id):
        pass

    def reset_bus_color(self, veh_id):
        pass

    def _apply_cycle_recovery(self, timeSta):
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 1. Token parsing / labelling
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_action_token():
    cases = {
        'NO_ACTION':      ('NO_ACTION', 0.0),
        'GE_10':          ('GE', 10.0),
        'INS_15':         ('INS', 15.0),
        'INS_close':      ('INS', None),
        'INS_POST_15':    ('INS', 15.0),
        'INS_PRETERM_8':  ('INS', 8.0),
        'ER_10':          ('ER', 10.0),
        'EARLY_RED_20':   ('ER', 20.0),
        'GR_5':           ('GR', 5.0),
        'GREEN_REALLOC_5': ('GR', 5.0),
        'OC_+5':          ('OC', 5.0),
        'OC_-10':         ('OC', 10.0),
        'VP_12':          ('VP', 12.0),
        'PT_2':           ('PT', 2.0),
    }
    for tok, want in cases.items():
        got = spm.parse_action_token(tok)
        assert got == want, f"parse_action_token({tok!r}) = {got}, want {want}"


def test_action_label_roundtrip():
    for atype, param in [('GE', 10.0), ('INS', 15.0), ('INS_POST', 15.0),
                         ('INS_PRETERM', 8.0), ('EARLY_RED', 10.0),
                         ('GREEN_REALLOC', 5.0)]:
        lbl = spm.action_label(atype, param)
        kind, num = spm.parse_action_token(lbl)
        assert kind in ('GE', 'INS', 'ER', 'GR'), (atype, lbl, kind)
        assert num == param, (atype, lbl, num)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Side-cost single-counting
# ─────────────────────────────────────────────────────────────────────────────

def test_cross_cost_not_double_counted():
    c = FakeController(bus_phase=2, cross_pax_per_s=2.0)
    (_r, _so, _tp, _bps, cpc, _nsd, _std) = spm._dctsp_eval_action(
        c, 'GE', 10.0, sigma_in=0.0, no_act_delay=40.0, bus_eta_s=5.0,
        wrong_phase=False, remaining_red_s=0.0)
    # Raw stub value is 2.0 * 10 = 20 pax·s.  The old code multiplied by
    # CarOcc (1.6) and NETWORK_FACTOR again → 32+.  Must be exactly 20.
    assert abs(cpc - 20.0) < 1e-9, f"cross cost double-counted: {cpc}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Per-mode candidate generation differentiation
# ─────────────────────────────────────────────────────────────────────────────

def _mode_labels(func, ctrl, **kw):
    (_t, _p, _r, _rd, _so, _tp, rows) = func(
        ctrl, 100.0, 100.0, 1.0, 12.0, 9001, 1, 40.0, 0.0, remaining_red_s=30.0)
    return [row[0] for row in rows]


def test_mode_candidate_differentiation():
    spm.BXT_EPSILON = 0.0        # deterministic argmax for the test
    labels = {}
    for name, func in [('ZIG', spm.dctsp_zig), ('ECTM', spm.dctsp_mp_ectm),
                       ('BXT', spm.dctsp_bxt), ('BARGAIN', spm.dctsp_bargain)]:
        ctrl = FakeController(bus_phase=2)   # current_phase=1 → wrong phase
        labels[name] = _mode_labels(func, ctrl)

    # Every mode produces at least the NO_ACTION baseline
    for name, lbls in labels.items():
        assert 'NO_ACTION' in lbls, f"{name} missing NO_ACTION: {lbls}"

    # ZIG explores the INS_POST / INS_PRETERM / INS ladder
    assert any(l.startswith('INS_POST_') for l in labels['ZIG']), labels['ZIG']
    assert any(l.startswith('INS_PRETERM_') for l in labels['ZIG']), labels['ZIG']
    # BARGAIN generates the RL action-space grid (INS + ER + GR at wrong phase)
    assert any(l.startswith('INS_') for l in labels['BARGAIN']), labels['BARGAIN']
    assert any(l.startswith('ER_') for l in labels['BARGAIN']), labels['BARGAIN']
    assert any(l.startswith('GR_') for l in labels['BARGAIN']), labels['BARGAIN']

    # Candidate sets must differ pairwise — that IS the dispatch differentiation
    names = list(labels)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            assert set(labels[a]) != set(labels[b]), \
                f"{a} and {b} generated identical candidate sets: {labels[a]}"

    # Every non-baseline label must map to an executable kind
    for name, lbls in labels.items():
        for l in lbls:
            kind, _ = spm.parse_action_token(l)
            assert kind in ('NO_ACTION', 'GE', 'INS', 'GR', 'ER', 'OC', 'VP', 'PT'), \
                f"{name} label {l!r} not executable (kind={kind})"


# ─────────────────────────────────────────────────────────────────────────────
# 4. End-to-end engine wiring (scalar path + Pareto path)
# ─────────────────────────────────────────────────────────────────────────────

class SignalStub:
    """Records ECI* calls the execution branches make."""

    def __init__(self):
        self.calls = []

    def change_timing(self, node, phase, dur, timeSta):
        self.calls.append(('timing', node, phase, dur))
        return 0

    def change_direct(self, node, phase, timeSta, time, acycle, flag):
        self.calls.append(('direct', node, phase))
        return 0


def _bind_engine_stubs(tmpdir, signal, pareto=False, zig=False, ectm=False,
                       bxt=False, bargain=False):
    import math as _math
    import datetime as _dt
    import random as _rnd
    logs = []
    ns = {
        # stdlib/np modules the shim normally provides via bind_config
        'math': _math, 'np': np, 'datetime': _dt, 'random': _rnd, 'os': os,
        # logging / config the evaluate path reads
        'LOG_REWARD': False, 'LOG_HARMONY': False, 'VERBOSE': False,
        'log_to_file': lambda msg, force=False: logs.append(msg),
        'REWARD_ALPHA': 1.0, 'REWARD_BETA': 1.0, 'REWARD_GAMMA': 1.0,
        'REWARD_GE_CANDIDATES': [5.0, 10.0],
        'MAX_GE_EXTENSION_S': 10.0,
        'REWARD_TSP_ENABLE_GE': True, 'REWARD_TSP_ENABLE_INS': True,
        'PARETO_SELECTION_MODE': pareto,
        'Z4_CONSTRAINT_MODE': False, 'Z4_TOLERANCE_VEH_S': 90.0,
        'COORDINATED_TSP': False,
        '_REWARD_CYCLE_CSV': os.path.join(tmpdir, 'reward_cycle_test.csv'),
        '_reward_cycle_header_written': False,
        '_ge_events': [],
        # detection-marking is out of scope for these tests
        '_mark_detection_point': lambda *a, **k: None,
        # focus-gate globals
        '_focus_bus_id': -1, '_focus_jct_id': -1, '_focus_start_t': -1.0,
        '_focus_history': [], '_focus_passed_jcts': set(),
        '_FOCUS_TIMEOUT_S': 60.0, '_tsp_active_vehicles': {},
        # per-bus lateness map threaded into sigma_in (Z3 conditional priority)
        '_bus_lateness': {},
        # AAPI signal-control stubs
        'ECIGetStartingTimePhase': lambda node: 90.0,
        # Override engine's GetPhaseDuration wrapper (needs AAPI doublep)
        'GetPhaseDuration': lambda node, ph, t: 30.0,
        'ECIChangeTimingPhase': signal.change_timing,
        'ECIChangeDirectPhase': signal.change_direct,
    }
    eng.bind_config(ns)
    spm.DCTSP_ZIG_MODE = zig
    spm.MP_ECTM_MODE = ectm
    spm.BXT_MODE = bxt
    spm.BARGAIN_SPM_MODE = bargain
    spm.BXT_EPSILON = 0.0
    return logs


def test_scalar_path_executes_ge(tmp_path=None):
    tmpdir = str(tmp_path) if tmp_path else os.path.join(
        os.environ.get('TEMP', '/tmp'), 'tsp_dispatch_test')
    os.makedirs(tmpdir, exist_ok=True)
    signal = SignalStub()
    _bind_engine_stubs(tmpdir, signal, pareto=False)

    c = FakeController(bus_phase=2)
    c.ge_eval = (500.0, 10.0, 5.0)     # GE strongly positive
    c.ins_eval = (0.0, 999.0, 999.0)   # INS_close unattractive → GE must win
    # current_phase == BusPhase → GE branch; scalar argmax must EXECUTE it
    eng.IntersectionController._run_reward_tsp_evaluate(
        c, time=200.0, timeSta=200.0, acycle=1.0,
        current_phase=2, bus_eta_s=8.0, veh_id=9001)

    assert c.TSPStrategy == 1, f"GE not executed (TSPStrategy={c.TSPStrategy})"
    assert c.flag == 1
    assert any(k == 'timing' for (k, *_rest) in signal.calls), signal.calls
    assert ('extension' in [e[1] for e in c.stats.events])


def test_seq_cap_binds_independent_of_window(tmp_path=None):
    """PHASE_SEQ_MAX_PER_CYCLE must cap phase rotations per signal cycle even
    when the decision window would allow more.  PT is the best action here
    (wrong phase, high bus delay); with the cap exhausted it must be demoted to
    the next-best non-SEQ candidate (VP), and the counter must not advance."""
    tmpdir = str(tmp_path) if tmp_path else os.path.join(
        os.environ.get('TEMP', '/tmp'), 'tsp_dispatch_test')
    os.makedirs(tmpdir, exist_ok=True)

    def _run(cap, count):
        signal = SignalStub()
        _bind_engine_stubs(tmpdir, signal, pareto=False)
        c = FakeController(bus_phase=2, cross_pax_per_s=0.01)
        c.no_action_delay_s = 60.0
        c.ins_eval = (0.0, 999.0, 999.0)   # INS unattractive
        c._seq_max_per_cycle = cap
        c._seq_window_start = 150.0        # 50 s into the 135 s cycle at t=200
        c._seq_window_count = count
        eng.IntersectionController._run_reward_tsp_evaluate(
            c, time=200.0, timeSta=200.0, acycle=1.0,
            current_phase=1, bus_eta_s=12.0, veh_id=9010)
        return signal, c

    # Control: cap enabled but not yet exhausted → best PT (phase rotation) fires
    _sig0, c0 = _run(cap=1, count=0)
    assert c0.TSPStrategy == 7, \
        f"PT should fire when cap not hit (TSPStrategy={c0.TSPStrategy})"
    assert c0._seq_window_count == 1, "cap counter must increment on a PT grant"

    # Cap exhausted within the same cycle → PT demoted to next-best non-SEQ (VP)
    _sig1, c1 = _run(cap=1, count=1)
    assert c1.TSPStrategy == 6, \
        f"PT must be demoted when cap hit (TSPStrategy={c1.TSPStrategy})"
    assert c1._seq_window_count == 1, "cap counter must not advance for a demoted action"

    # Cap disabled → the counter is never consulted and PT always fires
    _sig2, c2 = _run(cap=0, count=5)
    assert c2.TSPStrategy == 7, \
        f"cap=0 must leave SEQ unconstrained (TSPStrategy={c2.TSPStrategy})"


def test_pareto_path_executes_mode_candidate(tmp_path=None):
    """A ZIG-generated INS_POST candidate must survive the Pareto layer and
    actually fire the insertion (ECIChangeDirectPhase called)."""
    tmpdir = str(tmp_path) if tmp_path else os.path.join(
        os.environ.get('TEMP', '/tmp'), 'tsp_dispatch_test')
    os.makedirs(tmpdir, exist_ok=True)
    signal = SignalStub()
    _bind_engine_stubs(tmpdir, signal, pareto=True, zig=True)

    c = FakeController(bus_phase=2, cross_pax_per_s=0.01)  # negligible side cost
    c.no_action_delay_s = 60.0                              # bus badly delayed
    c.ins_eval = (0.0, 999.0, 999.0)   # standard INS candidate unattractive
    # wrong phase → ZIG rows (INS/INS_POST/INS_PRETERM/ER) enter the pool
    eng.IntersectionController._run_reward_tsp_evaluate(
        c, time=200.0, timeSta=200.0, acycle=1.0,
        current_phase=1, bus_eta_s=12.0, veh_id=9002)

    assert c.TSPStrategy in (2, 3, 4), \
        f"mode candidate not executed (TSPStrategy={c.TSPStrategy})"
    assert signal.calls, "no signal-change call made"


def test_pareto_param_not_reparsed_from_label(tmp_path=None):
    """INS_POST_15 must execute with duration 15, not 0 (the old
    split('_',1) parse produced safe_float('POST_15') == 0 → action was
    silently dropped by the <5 s minimum-duration gate)."""
    tmpdir = str(tmp_path) if tmp_path else os.path.join(
        os.environ.get('TEMP', '/tmp'), 'tsp_dispatch_test')
    os.makedirs(tmpdir, exist_ok=True)
    signal = SignalStub()
    _bind_engine_stubs(tmpdir, signal, pareto=True, zig=True)

    c = FakeController(bus_phase=2, cross_pax_per_s=0.01)
    c.no_action_delay_s = 60.0
    c.ins_eval = (0.0, 999.0, 999.0)
    eng.IntersectionController._run_reward_tsp_evaluate(
        c, time=200.0, timeSta=200.0, acycle=1.0,
        current_phase=1, bus_eta_s=12.0, veh_id=9003)

    # whichever mode candidate won, its executed duration must be >= 5 s
    _dur_calls = [call for call in signal.calls if call[0] == 'timing']
    assert _dur_calls, f"nothing executed: {signal.calls}"
    assert all(call[3] >= 5.0 for call in _dur_calls), \
        f"executed with param parsed to 0: {signal.calls}"


def test_milp_gridlock_guard_blocks_insertion(monkeypatch):
    """A live saturated approach must veto a disruptive MILP insertion."""
    c = FakeController(bus_phase=2)
    c.incoming_sections = [222]
    c._get_side_sections = lambda: [111]
    c._zone_queue_count = lambda sec: (25, 100.0)
    c._normalize_sections = lambda sections: [int(value) for value in sections]
    c._milp_queue_snapshot = types.MethodType(
        eng.IntersectionController._milp_queue_snapshot, c)
    c._milp_recovery_ready = types.MethodType(
        eng.IntersectionController._milp_recovery_ready, c)

    monkeypatch.setattr(
        eng, 'AKIVehStateGetNbVehiclesSection',
        lambda sec, _include_all: 25 if sec == 111 else 0,
        raising=False)
    monkeypatch.setattr(
        eng, 'AKIInfNetGetSectionANGInf',
        lambda _sec: types.SimpleNamespace(
            length=100.0, nbCentralLanes=1, nbSideLanes=0),
        raising=False)
    monkeypatch.setattr(spm, 'MILP_TSP_MODE', True)

    allowed, reason, snapshot = eng.IntersectionController._milp_gridlock_guard(
        c, 'INS_POST_15', 15.0, 100.0, 1)

    assert not allowed
    assert reason == 'spillback_blocks_insertion'
    assert snapshot['side']['max_queue'] == 25.0


def test_milp_recovery_requires_cross_phase_service(monkeypatch):
    """A second bus intervention waits until the bus phase has been followed
    by cross-phase service, even when the time lock has elapsed."""
    c = FakeController(bus_phase=2)
    c._milp_recovery_start = 100.0
    c._milp_recovery_until = 110.0
    c._milp_recovery_bus_seen = True
    c._milp_recovery_cross_seen = False
    c._milp_queue_snapshot = lambda: {
        'side': {'invalid': 0, 'max_queue': 0.0, 'max_storage_ratio': 0.0},
        'main': {'invalid': 0, 'max_queue': 0.0, 'max_storage_ratio': 0.0},
    }
    c._milp_recovery_ready = types.MethodType(
        eng.IntersectionController._milp_recovery_ready, c)
    monkeypatch.setattr(spm, 'MILP_TSP_MODE', True)

    allowed, reason, _snapshot = eng.IntersectionController._milp_gridlock_guard(
        c, 'GE_15', 15.0, 120.0, 2)
    assert not allowed
    assert reason == 'cross_phase_recovery_required'


def test_ins_not_cancelled_by_interphase(tmp_path=None):
    """Regression for held=0.8s: an insertion must NOT be cancelled just
    because ECIGetCurrentPhase does not report the bus phase one step after
    the grant (Aimsun runs an interphase first / applies the change late)."""
    tmpdir = str(tmp_path) if tmp_path else os.path.join(
        os.environ.get('TEMP', '/tmp'), 'tsp_dispatch_test')
    os.makedirs(tmpdir, exist_ok=True)
    signal = SignalStub()
    _bind_engine_stubs(tmpdir, signal, pareto=False)

    phase_holder = [1]   # what ECIGetCurrentPhase reports
    eng.bind_config({'ECIGetCurrentPhase': lambda node: phase_holder[0]})

    c = FakeController(bus_phase=2)
    # Simulate an INS grant at t=100 for 15 s
    c.flag = 2
    c.TSPStrategy = 2
    c.previous_phase = 1
    c.BusPhaseEndTime = 115.0
    c._ins_bus_phase_seen = False
    c._ins_grant_time = 100.0

    # One step later the phase has NOT switched yet (interphase) — the old
    # code ended the insertion here (held=0.8s) and restored the old phase.
    eng.IntersectionController.restore_phase_if_needed(c, 100.8, 100.8, 0.8)
    assert c.flag == 2, "insertion cancelled during interphase transition"

    # Bus phase becomes active at t=103 — hold window re-anchors (+3 s)
    phase_holder[0] = 2
    eng.IntersectionController.restore_phase_if_needed(c, 103.0, 103.0, 0.8)
    assert c.flag == 2
    assert c._ins_bus_phase_seen is True
    assert abs(c.BusPhaseEndTime - 118.0) < 1e-6, c.BusPhaseEndTime

    # Bus phase genuinely ends → NOW the insertion completes
    phase_holder[0] = 3
    eng.IntersectionController.restore_phase_if_needed(c, 110.0, 110.0, 0.8)
    assert c.flag == 0, "insertion did not complete after bus phase ended"


def test_ins_times_out_if_phase_never_switches(tmp_path=None):
    """If the direct-phase change never lands, the timeout (+grace) must
    still end the insertion rather than holding the flag forever."""
    tmpdir = str(tmp_path) if tmp_path else os.path.join(
        os.environ.get('TEMP', '/tmp'), 'tsp_dispatch_test')
    os.makedirs(tmpdir, exist_ok=True)
    signal = SignalStub()
    _bind_engine_stubs(tmpdir, signal, pareto=False)
    eng.bind_config({'ECIGetCurrentPhase': lambda node: 1})   # never switches

    c = FakeController(bus_phase=2)
    c.flag = 2
    c.TSPStrategy = 2
    c.previous_phase = 1
    c.BusPhaseEndTime = 115.0
    c._ins_bus_phase_seen = False
    c._ins_grant_time = 100.0

    eng.IntersectionController.restore_phase_if_needed(c, 120.0, 120.0, 0.8)
    assert c.flag == 2, "grace period not honoured"
    eng.IntersectionController.restore_phase_if_needed(c, 126.0, 126.0, 0.8)
    assert c.flag == 0, "insertion never timed out"


def test_phase_actions_carry_side_cost():
    """Regression: PT/OC/GR/VP actions must NOT be costed at zero.

    With empty shockwave arrays (Logan minimal config) _dctsp_cross_traffic_delay_s
    returns 0, so every phase action came out free and the Pareto layer fired
    hundreds of them, slowing buses below NO_TSP.  The live-vehicle side-cost
    fallback must give any bus-saving action a positive cross cost."""
    class _SideCtrl(FakeController):
        def __init__(self):
            super().__init__(bus_phase=2)
            # Empty shockwave arrays → shockwave cross cost is 0
            self.UpFlowList = np.zeros((1, 1))
        def _dctsp_cross_traffic_delay_s(self, action_s, queue_elapsed_s=0.0, phases=None):
            return 0.0   # force the fallback path
        def _get_side_sections(self):
            return [111, 222]
        def _compute_side_delay_penalty(self, extra_red, _suppress_log=False):
            # 8 live side vehicles, 15% arrive during the window, occ 1.6
            return 8 * float(extra_red) * 1.6 * 0.15, 8.0

    # (action, param, wrong_phase) — all configured so bus_pax_saved > 0
    for atype, param, wp in [('PHASE_ROTATION', 10.0, True),
                             ('OFFSET_CORRECTION', 10.0, True),
                             ('GREEN_REALLOC', 10.0, False),  # right-phase GR helps bus
                             ('PHASE_SKIP', 10.0, True),
                             ('INS_PRETERM', 10.0, True)]:
        c = _SideCtrl()
        (_r, _so, _tp, bps, cpc, _nsd, _std) = spm._dctsp_eval_action(
            c, atype, param, 0.0, no_act_delay=40.0, bus_eta_s=5.0,
            wrong_phase=wp, remaining_red_s=20.0)
        assert bps > 0.0, f"{atype} test setup wrong: bps={bps} should be >0"
        assert cpc > 0.0, f"{atype} still costed at zero (cpc={cpc}, bps={bps})"


def test_early_red_no_penalty_when_bus_already_passed():
    """EARLY_RED with zero bus benefit (bus already cleared) must not be
    charged a cross cost — it gives green back to cross traffic."""
    class _SideCtrl(FakeController):
        def __init__(self):
            super().__init__(bus_phase=2)
        def _dctsp_cross_traffic_delay_s(self, action_s, queue_elapsed_s=0.0, phases=None):
            return 0.0
        def _compute_side_delay_penalty(self, extra_red, _suppress_log=False):
            return 999.0, 5.0   # would be huge if wrongly applied
    c = _SideCtrl()
    # remaining_red_s=0 → bus_saved_s=0 → bus_pax_saved=0 → no penalty
    (_r, _so, _tp, bps, cpc, _n, _s) = spm._dctsp_eval_action(
        c, 'EARLY_RED', 5.0, 0.0, no_act_delay=40.0, bus_eta_s=5.0,
        wrong_phase=False, remaining_red_s=0.0)
    assert bps == 0.0 and cpc == 0.0, f"ER penalised with no bus benefit (cpc={cpc})"


def test_reset_mode_flags_clears_leak():
    """Regression: modes must not leak across experiments in one session.

    HSLWR turns ZIG on; the next experiment (CTMGS) wants ECTM only.  Without
    reset_mode_flags(), ZIG stays True and every later experiment runs ZIG+ECTM
    → identical results across strategies."""
    # Experiment 1 (HSLWR): ZIG on
    spm.DCTSP_ZIG_MODE = True
    # Experiment 2 (CTMGS) AAPIInit: reset first, then apply its own config
    spm.reset_mode_flags()
    assert spm.DCTSP_ZIG_MODE is False, "ZIG leaked past reset"
    assert spm.MP_ECTM_MODE is False
    spm.MP_ECTM_MODE = True   # CTMGS run_config turns ECTM on
    assert spm.DCTSP_ZIG_MODE is False and spm.MP_ECTM_MODE is True

    # Experiment 3 (CENTRALISED): neither mode
    spm.reset_mode_flags()
    assert not any([spm.DCTSP_ZIG_MODE, spm.MP_ECTM_MODE, spm.BXT_MODE,
                    spm.BARGAIN_SPM_MODE, spm.DCTSP_GREEN_REALLOC_MODE]), \
        "a mode leaked into CENTRALISED"


def test_ge_lenient_gate_admits_good_extension():
    """A good green-extension whose cross-street pax-cost ratio falls between
    the strict (BALANCE_FACTOR) and GE-lenient (GE_BALANCE_FACTOR) thresholds
    must still be admitted as GE, not collapsed to NO_ACTION.

    Regression for the batch finding that CELLQLEARN/CTMGS/HSLWR/CELLQLEARN_DP
    applied zero extensions: their strict balance-factor gate rejected GE as
    eagerly as inserts.  GE is a small same-phase action, so it now gets a
    lenient admission threshold."""
    # Ratio geometry: cross_pax_per_s set so that cross-cost = 1.5 * bus-saved,
    # i.e. strictly above strict factor 1.0 but below GE-lenient factor 2.0.
    # (Linear stub: cross_cost = cross_pax_per_s * action_s; bus_pax_saved =
    #  action_s * BusOcc(40).  60/40 = 1.5.)
    c = FakeController(bus_phase=2, cross_pax_per_s=60.0)
    saved = dict(BALANCE=spm.ZIG_BALANCE_FACTOR, GEBAL=spm.ZIG_GE_BALANCE_FACTOR)
    spm.ZIG_BALANCE_FACTOR = 1.0
    spm.ZIG_GE_BALANCE_FACTOR = 2.0
    try:
        # no_act_delay=13 keeps GE as the mode's argmax (an insertion cannot
        # out-save the bus it only just misses), and cross-cost 60*param vs
        # bus-pax-saved 40*param gives ratio 1.5 -- strictly above strict
        # factor 1.0 yet below GE-lenient factor 2.0.
        ctrl = c
        _t, _p, _r, _rd, _so, _tp, rows = spm.dctsp_zig(
            ctrl, 100.0, 100.0, 1.0, 12.0, 9001, 2,   # current_phase=2 == BusPhase
            13.0, 0.0, remaining_red_s=0.0)
        ge_rows = [r for r in rows if r[0].startswith('GE_')]
        assert ge_rows, "ZIG did not generate a GE candidate in-phase"
        assert _t == 'GE', f"lenient gate wrongly collapsed good GE: {_t!r}"
        # Confirmation: with the lenient factor set to the strict value (1.0),
        # the same GE at ratio 1.5 must be rejected by the strict gate.
        spm.ZIG_GE_BALANCE_FACTOR = 1.0
        _t2, _p2, _r2, _rd2, _so2, _tp2, _rows2 = spm.dctsp_zig(
            ctrl, 100.0, 100.0, 1.0, 12.0, 9001, 2, 13.0, 0.0,
            remaining_red_s=0.0)
        assert _t2 == 'NO_ACTION', f"strict gate should have rejected GE: {_t2!r}"
    finally:
        spm.ZIG_BALANCE_FACTOR = saved['BALANCE']
        spm.ZIG_GE_BALANCE_FACTOR = saved['GEBAL']


def test_reset_mode_flags_restores_numeric_defaults():
    """A tuning param overridden by one experiment must return to its default
    for the next experiment that doesn't set it."""
    _default = spm.ZIG_PHASE_OVERLAP_S
    spm.ZIG_PHASE_OVERLAP_S = 99.0   # some experiment overrides it
    spm.reset_mode_flags()
    assert spm.ZIG_PHASE_OVERLAP_S == _default, "numeric param did not reset"


if __name__ == '__main__':
    _tests = [(k, v) for k, v in sorted(globals().items())
              if k.startswith('test_') and callable(v)]
    _failed = 0
    for _name, _fn in _tests:
        try:
            _fn()
            print(f"PASS  {_name}")
        except AssertionError as _e:
            _failed += 1
            print(f"FAIL  {_name}: {_e}")
        except Exception as _e:
            _failed += 1
            print(f"ERROR {_name}: {_e!r}")
    print(f"\n{len(_tests) - _failed}/{len(_tests)} passed")
    sys.exit(1 if _failed else 0)
