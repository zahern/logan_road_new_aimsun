"""
Specialized TSP action-selection modes for IntersectionController.

The reference controller is kg/intersection_controller.py (shim) + the shared
engine — NOT kg/intersection_controller_lean.py.  The reference lineage never
implemented these specialized modes, so the ZIG / MP-ECTM / BXT / BARGAIN
generators here were ported from the lean file (the only implementation in the
repo); where their behavior conflicts with the engine's own GE/INS reward
evaluation, the engine's behavior wins.
"""
import sys
sys.path.insert(0, r"C:\AimsunPackages")

import math
import numpy as np

# ── Default constants (overridden by run_config.py / batch_runner) ────────────

DCTSP_ZIG_MODE     = False
DCTSP_MIN_INS_DURATION_S = 10.0
DCTSP_MAX_INS_DURATION_S = 25.0
ZIG_PHASE_OVERLAP_S = 3.0
ZIG_BALANCE_FACTOR  = 1.0
# Lenient admission threshold used ONLY for green-extension candidates: an
# extension that saves bus delay is tolerated up to this cross-street pax-cost
# ratio, even when the strict (insertion) gate would reject it.  GE is a small,
# same-phase intervention, so a cross-traffic penalty up to this factor is
# still worth granting.  Default 2.0 => allow up to 2.0x the strict factor.
ZIG_GE_BALANCE_FACTOR  = 2.0
# Candidate-family gates (Signal-Sequencing sweep): SWAPS only when
# ZIG_ENABLE_SEQ, green-realloc ("TIMES") only when ZIG_ENABLE_GR.
# Default True everywhere preserves legacy behaviour (all candidate types
# generated) for experiments that do not set them.
ZIG_ENABLE_GE  = True
ZIG_ENABLE_INS = True
ZIG_ENABLE_GR  = True
ZIG_ENABLE_SEQ = True
PHASE_ROTATION_MODE = True

MP_ECTM_MODE      = False
MP_ECTM_DT_S      = 1.0
MP_ECTM_MIN_EXT_S = 3.0
MP_ECTM_MAX_EXT_S = 8.0
MP_ECTM_BALANCE_FACTOR = 1.0
MP_ECTM_GE_BALANCE_FACTOR = 2.0
MP_ECTM_CAR_OCC   = 1.6

# ── MP_ECTM_DP: CTMGS grid search + downstream DP look-ahead ─────────────────
# Hybrid Method III: keeps CTMGS' exhaustive grid sweep over [MIN_EXT, MAX_EXT]
# but scores every candidate with a CELLQLEARN-style DP coordination penalty —
# projected downstream-junction delay over the bus trajectory horizon — so the
# grid stops being myopic about corridor-wide cross-traffic harm.
MP_ECTM_DP_MODE      = False
MP_ECTM_DP_HORIZON_S = 90.0
MP_ECTM_DP_STAGE_S   = 15.0
MP_ECTM_DP_COORD_WEIGHT = 0.40

# ── BXT: CTM-based multiagent Q-learning TSP (Chanloha et al. 2014) ───────────
BXT_MODE           = False
BXT_DT_S           = 1.0
BXT_EPSILON        = 0.1
BXT_LEARN          = True   # close the Q-learning loop (credit realized delay back)
BXT_TRAIN_EPSILON  = 0.1    # exploration rate during TRAIN seeds (eval uses 0)
BXT_PHASE          = "per_seed"  # set per replication by AAPIInit: train|eval|per_seed
BXT_ALPHA          = 0.01
BXT_GAMMA          = 0.005
BXT_CAR_OCC        = 1.2
BXT_BALANCE_FACTOR = 1.0
BXT_GE_BALANCE_FACTOR = 2.0
# Cap on a BXT phase-insertion duration (s).  Long insertions truncate the
# current main-street green and are the most disruptive BXT action, so clamp
# them instead of committing the full 15-20 s candidate (mode-commits-own-
# action bypasses the standard BP_upper_bound clamp).
BXT_MAX_INS_S = 12.0

# ── v7 bus-equity & corridor-reward tuning ────────────────────────────────────
# BUS_PAX_WEIGHT: equity multiplier applied to bus pax-s wherever it is weighed
# against car pax-s (decision-time benefit rows, the decider cost veto, and the
# realized-delay learning reward).  Buses are rare but carry ~27x a car's
# occupants (BusOcc=40 vs CarOcc=1.5); this extra tilt makes the optimizer buy
# bus time more eagerly.  NO_ACTION baselines use the same weight so the
# advantage signal stays comparable.
# 2026-08-24 (#3): dialed 2.0 -> 1.3.  At 2.0 the optimizer bought bus time so
# eagerly it committed uncounted OC/GR timing changes that doubled car delay
# (champion search: car +69%, obj -26%).  1.3 keeps a modest bus tilt (buses
# already carry ~27x a car's pax via BusOcc) without over-buying.
BUS_PAX_WEIGHT = 1.3
# GREEN_KEEP_CREDIT_S: reinforcement floor.  benefit = predicted red-wait x occ
# is exactly 0 for a bus predicted to arrive on green, which made the cost veto
# kill EVERY action (measured: 1458 no-actions vs 5 extensions per run).  When
# the bus is inside the reachable window anyway, credit this many seconds of
# protected green (x occ x BUS_PAX_WEIGHT) so near-free reinforcement actions
# can fire while expensive ones still face the veto.
GREEN_KEEP_CREDIT_S = 3.0
# CORRIDOR_REWARD_NEIGHBOR_W: inter-intersection reward sharing.  The realized-
# delay Q-update is otherwise purely LOCAL -- an action that shoves its queue
# onto the next junction scores great locally.  With this weight, each decision
# also credits the SIGNED realized delay delta of its CorridorCoordinator
# neighbors over the same window, so helping the corridor pays and hurting it
# costs (the coordination reward the user asked for).
CORRIDOR_REWARD_NEIGHBOR_W = 0.5

# ── CELLQLEARN_DP: CellQ-Learn with Dynamic Programming ───────────────────────
# V2X-coordinated TSP using queue-length prediction + DP backward recursion.
# Reference: Huang H.-K. & Hsu Y.-T. (2025), "Coordinated transit signal priority
# control with queue length prediction in V2X environments",
# Transportation Letters 18(2), 392-413.
CELLQLEARN_DP_MODE      = False
CELLQLEARN_DP_DT_S      = 1.0
CELLQLEARN_DP_HORIZON_S = 90.0
CELLQLEARN_DP_STAGE_S   = 15.0
CELLQLEARN_DP_COORD_WEIGHT = 0.22
CELLQLEARN_DP_CAR_OCC   = 1.2
CELLQLEARN_DP_BALANCE_FACTOR = 1.0
CELLQLEARN_DP_GE_BALANCE_FACTOR = 2.0

# ── BARGAIN_SPM: Nash bargaining game TSP (AnsariEsfeh & Kattan 2025) ─────────
BARGAIN_SPM_MODE   = False
BG_DET_LVL_IMM_S   = 4.0
BG_DET_LVL_NEAR_S  = 12.0
BG_DET_LVL_FAR_S   = 24.0
BG_BUS_W_IMM       = 1.6
BG_BUS_W_NEAR      = 1.35
BG_BUS_W_FAR       = 1.1
BG_BUS_W_VFAR      = 0.95
BG_SPM_RISK_WEIGHT = 1.8
BG_MIN_BUS_DELAY_S = 5.0
BG_MIN_GAIN_S      = 5.0
BG_CASCADE_MULT    = 2.0
BG_NO_ACTION_BONUS_S = 20.0   # pax·s inertia bonus for NO_ACTION

DCTSP_GREEN_REALLOC_MODE = False
GREEN_REALLOC_RECOVER_FRACTION = 1.0

INS_INTERGREEN_S  = 5.0
SELFORG_MIN_BUS_DELAY_S = 10.0
NETWORK_FACTOR    = 1.0
CROSS_TRAFFIC_COST_MULTIPLIER = 2.0
MAX_GE_EXTENSION_S = 10.0
DCTSP_MULTI_CYCLE_X_THR   = 0.85
DCTSP_MULTI_CYCLE_X_FLOOR = 0.10   # caps the 1/(1-x) multi-cycle amplifier at 4x
                                   # (was 0.02 -> 50x, a major contributor to the
                                   #  1e9 pax-s side-cost blowup)

# ── Future-horizon penalty: each action's cross-traffic cost is scaled by the
# fraction of a cycle it disturbs, projected forward over the lookahead window.
# This makes action rewards horizon-aware — a small GE on a short cycle has less
# future echo than a long insertion on a long cycle. Tune per-experiment via
# run_config / batch_runner.
REWARD_FUTURE_HORIZON_CYCLES = 1.0  # lookahead horizon in cycle-length units
REWARD_FUTURE_DEBT_GAIN      = 0.35 # weight on projected unrecovered green debt
REWARD_FUTURE_OFFSET_GAIN    = 0.20 # weight on projected offset misalignment


def _log_func(self, msg: str, force: bool = False):
    """Call the module-level log_to_file if available."""
    try:
        log_to_file = getattr(self, '_module_log', None)
        if log_to_file is None:
            import inspect
            frame = inspect.currentframe()
            for _ in range(3):
                frame = frame.f_back if frame else None
            caller_globals = frame.f_globals if frame else {}
            log_to_file = caller_globals.get('log_to_file')
            if log_to_file is None:
                log_to_file = caller_globals.get('AKIPrintString')
            if log_to_file is None:
                log_to_file = lambda *a, **k: None
            self._module_log = log_to_file
        log_to_file(msg, force=force)
    except Exception:
        pass


def _safe_float(x, default=0.0):
    try: return float(x)
    except Exception: return default


def _shockwave_optimal_green_s(self, min_s: float = 5.0, max_s: float = 20.0) -> float:
    try:
        q_sat_vps = float(getattr(self, 'SaturationFlow', 1800)) / 3600.0
        k_jam     = float(getattr(self, 'JamDensity', 200.0))
        upf = np.asarray(getattr(self, 'UpFlowList', np.zeros((1,1))), dtype=float)
        rdt = np.asarray(getattr(self, 'RedDurationList', np.zeros((1,1))), dtype=float)
        if upf.ndim < 2 or upf.shape[0] == 0 or rdt.shape[0] == 0:
            return float(np.clip(10.0, min_s, max_s))
        upf_bus = upf[0].ravel()
        rdt_bus = rdt[0].ravel()
        pos_flow = upf_bus[upf_bus > 0.0]
        _cycle = float(getattr(self, 'config', {}).get('CycleTime', 135))
        pos_red = rdt_bus[(rdt_bus > 0.0) & (rdt_bus < 2.0 * _cycle)]
        q_arr_vph = float(np.mean(pos_flow)) if pos_flow.size > 0 else 0.0
        t_red_s   = float(np.max(pos_red))   if pos_red.size  > 0 else 30.0
        q_arr_vps = q_arr_vph / 3600.0
        k_arr  = q_arr_vps * k_jam / max(q_sat_vps, 1e-9)
        w_back = q_arr_vps / max(k_jam - k_arr, 1.0)
        N_q = max(0.0, w_back * t_red_s * k_jam)
        q_discharge = max(0.0, q_sat_vps - q_arr_vps)
        t_clear = (N_q / q_discharge) if q_discharge > 0.01 else float(max_s)
        return float(np.clip(t_clear, min_s, max_s))
    except Exception:
        return float(np.clip(10.0, min_s, max_s))


def _mainline_pax_saved_for_green(self, green_s):
    """Estimate mainline-car passenger-delay saved (pax·s) when `green_s`
    seconds of extra bus-phase green are provided.

    The bus phase serves every mainline vehicle on that approach, not just the
    bus.  Extra green discharges ~q_sat vehicles; each queued vehicle saves on
    average green_s/2 seconds of delay (triangular dissipation).  Previously
    only the bus was credited, so an action that clearly helped the whole
    approach looked like a net cost.
    """
    try:
        q_sat_vph = float(getattr(self, 'SaturationFlow', 1800))
        _car_occ = float(getattr(self, 'CarOcc', 1.6) if hasattr(self, 'CarOcc') else 1.6)
        g = max(0.0, float(green_s))
        q_sat_vps = q_sat_vph / 3600.0
        return q_sat_vps * g * (g / 2.0) * max(_car_occ, 0.0)
    except Exception:
        return 0.0


def _compute_future_horizon_penalty(self, action_type, disturbance_s, cross_cost):
    if action_type in ('NO_ACTION',) or float(disturbance_s) <= 0.0:
        return 0.0
    try:
        _h_cycles = float(globals().get('REWARD_FUTURE_HORIZON_CYCLES', 1.0) or 1.0)
        _debt_gain = float(globals().get('REWARD_FUTURE_DEBT_GAIN', 0.35) or 0.35)
    except Exception:
        return 0.0
    _cycle_s = 135.0
    try:
        if hasattr(self, '_signal_cycle_s'):
            _cycle_s = max(30.0, float(self._signal_cycle_s()))
        else:
            _cfg = getattr(self, 'config', {}) or {}
            _cycle_s = max(30.0, float(_cfg.get('CycleTime', 135.0) or 135.0))
    except Exception:
        pass
    _disturb = max(float(disturbance_s), 1.0)
    _future_frac = min(1.0, (_disturb / _cycle_s) * _h_cycles)
    return _debt_gain * _future_frac * max(0.0, float(cross_cost))


def _dctsp_eval_action(self, action_type, param, sigma_in, no_act_delay,
                       bus_eta_s, wrong_phase=False, remaining_red_s=0.0):
    """Evaluate one candidate action, returning (reward, sigma_out, t_poz,
    bus_pax_saved_s, car_pax_cost_s, no_strategy_delay, strategy_delay)."""
    try:
        _occ = float(getattr(self, 'BusOcc', 40.0))
        _car_occ = float(getattr(self, 'CarOcc', 1.6) if hasattr(self, 'CarOcc') else 1.6)
    except Exception:
        _occ = 40.0; _car_occ = 1.6
    if action_type == 'NO_ACTION':
        sigma_out = sigma_in
        t_poz = 0.0
        bus_pax = max(0.0, float(no_act_delay)) * _occ
        car_pax = 0.0
        strategy_delay = bus_pax
        no_strategy_delay = bus_pax
        reward = -(bus_pax + car_pax)
        return (reward, sigma_out, t_poz, 0.0, 0.0, no_strategy_delay, strategy_delay)
    param = float(param)
    # _dctsp_cross_traffic_delay_s already returns pax·s (CarOcc and
    # NETWORK_FACTOR are applied inside it) — do NOT multiply again here.
    cross_cost = float(self._dctsp_cross_traffic_delay_s(param))
    if action_type in ('GE', 'GREEN_REALLOC'):
        if not bool(wrong_phase):
            bus_saved_s = max(0.0, float(no_act_delay) - max(0.0, float(no_act_delay) - param))
            if float(no_act_delay) <= param:
                bus_saved_s = float(no_act_delay)
            else:
                bus_saved_s = param
            bus_pax_saved = bus_saved_s * _occ
            sigma_out = max(0.0, sigma_in - bus_saved_s)
            t_poz = 0.0
        else:
            bus_pax_saved = -param * _occ
            sigma_out = sigma_in
            t_poz = 0.0
    elif action_type in ('INS', 'INS_POST', 'INS_PRETERM'):
        overhead = float(INS_INTERGREEN_S)
        if action_type == 'INS_POST':
            overhead += float(remaining_red_s)
        elif action_type in ('INS', 'INS_PRETERM'):
            overhead = overhead
            if action_type == 'INS_PRETERM':
                cross_cost += float(self._dctsp_cross_traffic_delay_s(
                    max(0.0, float(remaining_red_s) - float(INS_INTERGREEN_S))))
        bus_saved_s = max(0.0, float(no_act_delay) - overhead)
        eff_green = max(0.0, param - overhead)
        # The bus can only catch the inserted green window if it reaches the
        # stopline before that window closes.  A bus still `bus_eta_s` away
        # gets no benefit from an insertion that ends first — without this
        # ETA gate, INS_PRETERM_3 claimed bus_saved up to 54 500 pax·s (a
        # phantom ~1 300 s of delay from a 3 s action).
        if float(bus_eta_s) > (max(0.0, float(param)) + float(overhead)):
            bus_saved_s = 0.0
        elif eff_green > 0:
            bus_saved_s = min(bus_saved_s, float(no_act_delay))
        else:
            bus_saved_s = 0.0
        bus_pax_saved = bus_saved_s * _occ
        sigma_out = max(0.0, sigma_in - bus_saved_s)
        t_poz = 0.0
    elif action_type == 'EARLY_RED':
        # ER truncates the CURRENT phase by `param`.  On the active bus phase
        # (bus already cleared) it simply returns green to cross traffic — the
        # bus is not waiting, so there is no bus benefit and cross traffic is
        # HELPED (no extra red).  Only a wrong-phase ER (bus genuinely held on
        # a non-bus red) saves bus delay, and then only up to the actual
        # truncation `param`.  Previously `bus_saved_s = remaining_red * 0.5`
        # credited phantom savings (ER_5 showed bus_saved 460–1 113 pax·s)
        # that made the action look free and fired ~109 ER/run.
        if not bool(wrong_phase):
            bus_saved_s = 0.0
        else:
            bus_saved_s = min(max(0.0, float(param)),
                              max(0.0, float(remaining_red_s)))
            cross_cost += float(self._dctsp_cross_traffic_delay_s(
                max(0.0, float(remaining_red_s) - float(INS_INTERGREEN_S))))
        bus_pax_saved = bus_saved_s * _occ
        sigma_out = sigma_in
        t_poz = 0.0
    elif action_type == 'OFFSET_CORRECTION':
        bus_saved_s = param * 0.3 if param > 0 else 0.0
        bus_pax_saved = bus_saved_s * _occ
        sigma_out = sigma_in
        t_poz = 0.0
        cross_cost += float(self._dctsp_cross_traffic_delay_s(abs(float(param))))
    elif action_type == 'PHASE_SKIP':
        bus_saved_s = max(0.0, float(param) * 0.8)
        bus_pax_saved = bus_saved_s * _occ
        sigma_out = max(0.0, sigma_in - bus_saved_s)
        t_poz = 0.0
        cross_cost += float(self._dctsp_cross_traffic_delay_s(float(param)))
    elif action_type == 'PHASE_ROTATION':
        bus_saved_s = max(0.0, float(param) * 0.6)
        bus_pax_saved = bus_saved_s * _occ
        sigma_out = max(0.0, sigma_in - bus_saved_s)
        t_poz = 0.0
        cross_cost += float(self._dctsp_cross_traffic_delay_s(float(param) * 0.7))
    else:
        bus_pax_saved = 0.0; sigma_out = sigma_in; t_poz = 0.0

    # Mainline-car benefit: the bus phase serves every mainline vehicle on that
    # approach, not just the bus.  Adding/inserting bus-phase green discharges
    # extra cars and relieves their queue, so credit that passenger-delay saving
    # (previously only the bus was counted, biasing every action toward NO_ACTION).
    if action_type in ('GE', 'GREEN_REALLOC', 'INS', 'INS_POST', 'INS_PRETERM'):
        mainline_pax_saved = _mainline_pax_saved_for_green(self, param)
    else:
        mainline_pax_saved = 0.0

    # ── Side-cost fallback (minimal configs with empty shockwave arrays) ──────
    # _dctsp_cross_traffic_delay_s returns 0 when UpFlowList is unpopulated (the
    # Logan minimal config), so EVERY phase-modifying action (PT/OC/GR/VP/ER/
    # INS_PRETERM/…) came out with cross_cost=0.  The weight-free Pareto layer
    # then fired hundreds of them "for free" (589 phase rotations/early-reds per
    # run), disrupting the fixed-time plan and making buses SLOWER than NO_TSP.
    # Any action that saves bus time does so by taking green from cross traffic,
    # so it must carry a cost: estimate it from live side-section vehicle counts,
    # the same mechanism GE/INS use in _reward_evaluate_ge/_reward_evaluate_insertion.
    # The gate was `cross_cost < 1.0`, but the analytic path routinely returns
    # a small non-zero value (e.g. 13 pax·s) that masked the fact the real side
    # cost is ~0, so the live-count fallback never fired and ER_5 was priced
    # at ~free.  Apply it whenever an action claims a bus benefit: take the
    # MAX so the measured side cost always binds (never less than analytic).
    if bus_pax_saved > 0.0:
        _eff_red = {
            'GE': param, 'GREEN_REALLOC': param,
            'INS': param + float(INS_INTERGREEN_S),
            'INS_POST': param + float(INS_INTERGREEN_S) + max(0.0, float(remaining_red_s)),
            'INS_PRETERM': param + float(INS_INTERGREEN_S),
            'OFFSET_CORRECTION': abs(param),
            'PHASE_SKIP': param,
            'PHASE_ROTATION': param * 0.7,
            'EARLY_RED': max(0.0, float(remaining_red_s) - float(INS_INTERGREEN_S)),
        }.get(action_type, param)
        try:
            _sd, _ = self._compute_side_delay_penalty(max(0.0, _eff_red),
                                                      _suppress_log=True)
            cross_cost = max(cross_cost, max(0.0, float(_sd)))
        except Exception:
            pass

    no_strategy_delay = max(0.0, float(no_act_delay)) * _occ
    strategy_delay = max(0.0, no_strategy_delay - bus_pax_saved)
    # Weighted-objective reward: Z1 (delay) · Z2 (progression) · Z3 (headway)
    _walpha = float(globals().get('WOBJ_ALPHA', 1.0))
    _wbeta  = float(globals().get('WOBJ_BETA', 0.0))
    _wgamma = float(globals().get('WOBJ_GAMMA', 0.0))
    # CPD-QL / MARL blend (backwards-compatible): DCTSP_W_H is the headway
    # share — pax-delay weight = (1 - W_H), headway weight = W_H on top of the
    # WOBJ_GAMMA lateness term.  DCTSP_CAR_WEIGHT scales the cross-traffic
    # cost.  Absent keys (None) fall back to pure WOBJ_* behaviour.
    _wh = globals().get('DCTSP_W_H')
    if _wh is not None:
        _wh = float(_wh)
        _walpha = _walpha * max(0.0, 1.0 - _wh)
        _wgamma = _wgamma + _wh
    _cw = globals().get('DCTSP_CAR_WEIGHT')
    _cw = 1.0 if _cw is None else float(_cw)
    _sigma_s = max(float(sigma_in), 0.0)
    _lateness_factor = min(_sigma_s / 30.0, 3.0)
    _eff_bus_w  = _walpha + _wgamma * _lateness_factor
    _eff_cross_w = (1.0 + _wbeta) * max(_cw, 0.0)
    reward = _eff_bus_w * (bus_pax_saved + mainline_pax_saved) - _eff_cross_w * cross_cost
    _horizon_penalty = _compute_future_horizon_penalty(
        self, action_type, float(param), cross_cost)
    reward -= _horizon_penalty
    return (reward, sigma_out, t_poz, bus_pax_saved, cross_cost,
            no_strategy_delay, strategy_delay)


def dctsp_zig(self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
              no_act_delay, sigma_in, remaining_red_s=0.0):
    eff_delay = max(0.0, float(no_act_delay) - float(ZIG_PHASE_OVERLAP_S))
    t_sw = _shockwave_optimal_green_s(self,
        min_s=float(DCTSP_MIN_INS_DURATION_S),
        max_s=float(DCTSP_MAX_INS_DURATION_S))
    _wrong_phase = (current_phase != self.BusPhase)
    _cycle_s = float(self._signal_cycle_s()) if hasattr(self, '_signal_cycle_s') else float(self.config.get('CycleTime', 135.0) or 135.0)
    _max_d = max(_cycle_s - float(getattr(self, 'BusPhaseDuration', 20)), 0.0)
    _miss_by = max(0.0, _max_d - float(no_act_delay))
    t_ge = float(np.clip(_miss_by + t_sw,
                          float(DCTSP_MIN_INS_DURATION_S),
                          float(MAX_GE_EXTENSION_S)))
    rows = []
    r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
        self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
    rows.append(('NO_ACTION', 0.0, r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na))
    if not _wrong_phase and ZIG_ENABLE_GE:
        r_ge, so_ge, tp_ge, bps_ge, cpc_ge, nsd_ge, std_ge = _dctsp_eval_action(
            self, 'GE', t_ge, sigma_in, no_act_delay, bus_eta_s, wrong_phase=False)
        rows.append((f'GE_{t_ge:.0f}', t_ge, r_ge, so_ge, tp_ge, bps_ge, cpc_ge, nsd_ge, std_ge))
    if ZIG_ENABLE_INS:
        r_ip, so_ip, tp_ip, bps_ip, cpc_ip, nsd_ip, std_ip = _dctsp_eval_action(
            self, 'INS_POST', t_sw, sigma_in, no_act_delay, bus_eta_s, remaining_red_s=remaining_red_s)
        rows.append((f'INS_POST_{t_sw:.0f}', t_sw, r_ip, so_ip, tp_ip, bps_ip, cpc_ip, nsd_ip, std_ip))
        r_ipt, so_ipt, tp_ipt, bps_ipt, cpc_ipt, nsd_ipt, std_ipt = _dctsp_eval_action(
            self, 'INS_PRETERM', t_sw, sigma_in, no_act_delay, bus_eta_s, remaining_red_s=remaining_red_s)
        rows.append((f'INS_PRETERM_{t_sw:.0f}', t_sw, r_ipt, so_ipt, tp_ipt, bps_ipt, cpc_ipt, nsd_ipt, std_ipt))
        for _zi_dur in [10.0, 15.0, 20.0, 25.0]:
            _zi_dur = float(np.clip(_zi_dur, float(DCTSP_MIN_INS_DURATION_S), float(DCTSP_MAX_INS_DURATION_S)))
            r_zi, so_zi, tp_zi, bps_zi, cpc_zi, nsd_zi, std_zi = _dctsp_eval_action(
                self, 'INS', _zi_dur, sigma_in, no_act_delay, bus_eta_s)
            rows.append((f'INS_{_zi_dur:.0f}', _zi_dur, r_zi, so_zi, tp_zi, bps_zi, cpc_zi, nsd_zi, std_zi))
    if _wrong_phase and ZIG_ENABLE_SEQ:
        r_er, so_er, tp_er, bps_er, cpc_er, nsd_er, std_er = _dctsp_eval_action(
            self, 'EARLY_RED', t_sw, sigma_in, no_act_delay, bus_eta_s, remaining_red_s=remaining_red_s)
        rows.append((f'ER_{t_sw:.0f}', t_sw, r_er, so_er, tp_er, bps_er, cpc_er, nsd_er, std_er))
    best_lbl, best_param = 'NO_ACTION', 0.0
    best_r, best_so, best_tp = r_na, so_na, tp_na
    for (lbl, par, r, so, tp, *_) in rows:
        if r > best_r:
            best_r = r; best_lbl = lbl; best_param = par; best_so = so; best_tp = tp
    best_type = (best_lbl if '_' not in best_lbl
                 else ('GE' if best_lbl.startswith('GE_') else
                       'INS_POST' if best_lbl.startswith('INS_POST_') else
                       'INS_PRETERM' if best_lbl.startswith('INS_PRETERM_') else
                       'INS' if best_lbl.startswith('INS_') else
                       'EARLY_RED' if best_lbl.startswith('ER_') else best_lbl))
    best_r_delta = best_r - r_na
    if eff_delay < float(SELFORG_MIN_BUS_DELAY_S):
        pass
    else:
        try:
            if best_type != 'NO_ACTION':
                _best_row = next((r for r in rows if r[0] == best_lbl), None)
                _best_saved = float(_best_row[5]) if _best_row else 1.0
                _best_cost = float(_best_row[6]) if _best_row else 0.0
                _zig_ratio = _best_cost / max(_best_saved, 1.0)
            else:
                _zig_ratio = 0.0
        except Exception:
            _zig_ratio = 0.0
        # GE is a small same-phase intervention: tolerate a higher cross-street
        # cost ratio for extensions than for (disruptive) insertions.
        _gate_factor = (float(ZIG_GE_BALANCE_FACTOR) if best_type == 'GE'
                        else float(ZIG_BALANCE_FACTOR))
        if _zig_ratio > _gate_factor:
            best_type = 'NO_ACTION'; best_param = 0.0
            best_r = r_na; best_r_delta = 0.0; best_so = so_na; best_tp = tp_na
    return (best_type, best_param, best_r, best_r_delta, best_so, best_tp, rows)


def dctsp_mp_ectm(self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
                  no_act_delay, sigma_in, remaining_red_s=0.0):
    dt = float(MP_ECTM_DT_S)
    q_sat_vps = float(getattr(self, 'SaturationFlow', 1800.0)) / 3600.0
    k_jam = float(getattr(self, 'JamDensity', 200.0))
    _bus_occ = float(getattr(self, 'BusOcc', 40.0))
    _cycle_s = float(self._signal_cycle_s()) if hasattr(self, '_signal_cycle_s') else float(self.config.get('CycleTime', 135.0) or 135.0)
    _bus_g_base = float(getattr(self, 'BusPhaseDuration', 20.0))
    _wrong_phase = (int(current_phase) != int(self.BusPhase))
    _car_occ = float(MP_ECTM_CAR_OCC)
    try:
        upf = np.asarray(getattr(self, 'UpFlowList', np.zeros((1,1))), dtype=float)
        rdt = np.asarray(getattr(self, 'RedDurationList', np.zeros((1,1))), dtype=float)
        upf_bus = upf[0].ravel() if upf.ndim >= 2 and upf.shape[0] > 0 else np.zeros(1)
        rdt_bus = rdt[0].ravel() if rdt.ndim >= 2 and rdt.shape[0] > 0 else np.zeros(1)
        pos_flow = upf_bus[upf_bus > 0.0]
        pos_red = rdt_bus[(rdt_bus > 0.0) & (rdt_bus < 2.0 * _cycle_s)]
        q_arr_bus_vps = (float(np.mean(pos_flow)) / 3600.0 if pos_flow.size > 0 else 300.0 / 3600.0)
        t_red_past = (float(np.max(pos_red)) if pos_red.size > 0 else 60.0)
        k_arr_b = q_arr_bus_vps * k_jam / max(q_sat_vps, 1e-9)
        w_back_b = q_arr_bus_vps / max(k_jam - k_arr_b, 1.0)
        n0_bus = max(0.0, w_back_b * t_red_past * k_jam)
    except Exception:
        q_arr_bus_vps = 300.0 / 3600.0
        n0_bus = 5.0
    _cap_veh = k_jam * 0.15
    # ── Passenger weighting for the approach cell ────────────────────────────
    # `n0_bus` is the LWR/shockwave estimate of the WHOLE approach queue in
    # vehicles and `q_arr_bus_vps` is the WHOLE approach flow -- neither is
    # bus-only -- so passing `_bus_occ` (40 pax/veh) into _ctm_delay_pax priced
    # every queued car as a 40-passenger bus (~16x overstatement).  Same defect
    # fixed in dctsp_bxt, where it drove constant max-length extensions and
    # gridlocked kg seeds 400/500.  Weight the cell by what it holds: the
    # subject bus at BusOcc, the remaining queue at CarOcc.
    _n_cell = max(float(n0_bus), 1.0)
    _cell_occ = ((min(1.0, _n_cell) * _bus_occ
                  + max(0.0, _n_cell - 1.0) * float(_car_occ)) / _n_cell)

    def _ctm_delay_pax(n0, q_arr, q_sat, t_wait, g_dur, occ):
        delay = 0.0; n = max(0.0, float(n0))
        for _ in range(max(0, int(round(float(t_wait) / dt)))):
            n = min(n + q_arr * dt, _cap_veh); delay += n * dt
        for _ in range(max(0, int(round(float(g_dur) / dt)))):
            q_out = min(q_sat, n / max(dt, 1e-9))
            n = max(0.0, n + q_arr * dt - q_out * dt); delay += n * dt
        return delay * float(occ)
    if _wrong_phase:
        _t_wait_na = float(remaining_red_s); _g_bus_na = _bus_g_base
    else:
        _t_wait_na = 0.0; _g_bus_na = float(remaining_red_s)
    # ETA correction: a bus still `bus_eta_s` away has NOT been waiting the full
    # remaining red — it only accrues delay from the moment it reaches the
    # stopline.  Without this, a bus 18 s out was treated as already queued and
    # every action's bus benefit was massively inflated (INS_PRETERM_3 showed
    # bus_saved 21k–54k pax·s for a 3 s action).
    _eta = max(0.0, float(bus_eta_s))
    d_bus_na = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                              max(0.0, _t_wait_na - _eta), _g_bus_na, _cell_occ)
    # _dctsp_cross_traffic_delay_s returns pax·s (occupancy applied inside)
    d_side_na = float(self._dctsp_cross_traffic_delay_s(0.0))
    z_na = d_bus_na + d_side_na
    _d_min = float(MP_ECTM_MIN_EXT_S); _d_max = float(MP_ECTM_MAX_EXT_S)
    _d_step = float(dt)
    best_z = z_na; best_delta = 0.0; best_atype = 'NO_ACTION'
    best_d_bus = d_bus_na; best_d_side = d_side_na
    _sweep_evals = []   # (atype, delta, d_bus, d_side) — the FULL CTM grid
    for _d_raw in np.arange(_d_min, _d_max + _d_step * 0.5, _d_step):
        delta = float(_d_raw)
        if not _wrong_phase:
            d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps, 0.0, float(remaining_red_s) + delta, _cell_occ)
            d_side = float(self._dctsp_cross_traffic_delay_s(delta))
            z_ge = d_bus + d_side
            _sweep_evals.append(('GE', delta, d_bus, d_side))
            if z_ge < best_z:
                best_z = z_ge; best_delta = delta; best_atype = 'GE'
                best_d_bus = d_bus; best_d_side = d_side
        else:
            t_wait_post = float(remaining_red_s) + float(INS_INTERGREEN_S)
            d_bus_post = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                        max(0.0, t_wait_post - _eta), delta, _cell_occ)
            d_side_post = float(self._dctsp_cross_traffic_delay_s(t_wait_post + delta))
            z_post = d_bus_post + d_side_post
            _sweep_evals.append(('INS_POST', delta, d_bus_post, d_side_post))
            if z_post < best_z:
                best_z = z_post; best_delta = delta; best_atype = 'INS_POST'
                best_d_bus = d_bus_post; best_d_side = d_side_post
            _cut = max(0.0, float(remaining_red_s) - float(INS_INTERGREEN_S))
            d_bus_pt = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                      max(0.0, float(INS_INTERGREEN_S) - _eta),
                                      delta, _cell_occ)
            d_side_pt = (float(self._dctsp_cross_traffic_delay_s(float(INS_INTERGREEN_S) + delta))
                         + float(self._dctsp_cross_traffic_delay_s(_cut)))
            z_pt = d_bus_pt + d_side_pt
            _sweep_evals.append(('INS_PRETERM', delta, d_bus_pt, d_side_pt))
            if z_pt < best_z:
                best_z = z_pt; best_delta = delta; best_atype = 'INS_PRETERM'
                best_d_bus = d_bus_pt; best_d_side = d_side_pt
    eff_delay = max(0.0, float(no_act_delay) - float(ZIG_PHASE_OVERLAP_S))
    _satur_override = False
    if eff_delay < float(SELFORG_MIN_BUS_DELAY_S):
        best_atype = 'NO_ACTION'; best_delta = 0.0; _satur_override = True
    else:
        try:
            _o_d = _safe_float(self._safe_array_sum(getattr(self, 'OtherDelay', [0]))) + \
                   _safe_float(self._safe_array_sum(getattr(self, 'SideDelayBaseline', [0])))
            _bus_p = eff_delay * _bus_occ
            _side_p = max(0.0, _o_d) * _car_occ
            _ratio = _side_p / max(_bus_p, 1.0)
        except Exception:
            _ratio = 0.0
        _gate_factor = (float(MP_ECTM_GE_BALANCE_FACTOR) if best_atype == 'GE'
                        else float(MP_ECTM_BALANCE_FACTOR))
        if _ratio > _gate_factor:
            best_atype = 'NO_ACTION'; best_delta = 0.0; _satur_override = True
    r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
        self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
    rows = [('NO_ACTION', 0.0, r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na)]
    # Emit the FULL CTM grid sweep, not just the argmin: each (type, delta)
    # carries the CTM model's own objective vector, so the shared Pareto layer
    # can genuinely distinguish CTMGS's model trade-off from the standard
    # kinematic candidates.  Emitting only the argmin collapsed the mode onto
    # the standard pool (the single CTM row was almost always dominated).
    best_r = r_na; best_so = so_na; best_tp = tp_na; best_r_delta = 0.0
    if not _satur_override:
        for (at, delta, d_bus, d_side) in _sweep_evals:
            # The candidate's objective vector comes from the CTM model ITSELF —
            # re-scoring through _dctsp_eval_action (as before) collapsed ECTM's
            # rows onto the same kinematic vectors ZIG produces, so the shared
            # Pareto layer could never distinguish the two modes.
            try:
                _, so_act, tp_act, _, _, nsd_act, std_act = _dctsp_eval_action(
                    self, at, delta, sigma_in, no_act_delay, bus_eta_s,
                    wrong_phase=_wrong_phase, remaining_red_s=remaining_red_s)
            except Exception:
                so_act, tp_act, nsd_act, std_act = so_na, tp_na, nsd_na, std_na
            bps_ctm = max(0.0, d_bus_na - d_bus)     # CTM bus pax·s saved
            # Cap the claimed savings by the bus's ACTUAL no-action delay: the CTM
            # queue model can still over-credit a short green window when n0_bus is
            # large (INS_PRETERM_3 once claimed 62 000 pax·s ≈ 1 550 s from a 3 s
            # action), so the claimed bus time can never exceed what the bus
            # actually loses without action.  Keeps the CTM vector identity.
            bps_ctm = min(bps_ctm, max(0.0, float(no_act_delay)) * _bus_occ)
            cpc_ctm = max(0.0, d_side - d_side_na)   # CTM side pax·s added
            # Same zero-cost fallback as _dctsp_eval_action: in the minimal config
            # the CTM d_side terms are 0 (empty shockwave arrays), so cost the
            # insertion from live side-section vehicles instead — otherwise ECTM's
            # candidate looks free and the mode behaves identically to the base path.
            # Gate was `cpc_ctm < 1.0`, but the analytic path returns a small
            # non-zero value that masked the true ~0 side cost; use MAX so the
            # live-count side cost binds whenever a bus benefit is claimed.
            if bps_ctm > 0.0:
                try:
                    _ectm_red = float(delta) + float(INS_INTERGREEN_S)
                    _sd, _ = self._compute_side_delay_penalty(_ectm_red, _suppress_log=True)
                    cpc_ctm = max(cpc_ctm, max(0.0, float(_sd)))
                except Exception:
                    pass
            r_ctm   = bps_ctm - cpc_ctm
            rows.append((f'{at}_{delta:.0f}', delta,
                         r_ctm, so_act, tp_act, bps_ctm, cpc_ctm, nsd_act, std_act))
            if at == best_atype and abs(delta - best_delta) < 1e-6:
                best_r = r_ctm; best_so = so_act; best_tp = tp_act
                best_r_delta = r_ctm - r_na
    return (best_atype, best_delta, best_r, best_r_delta, best_so, best_tp, rows)


# ── Mode: MP_ECTM_DP — CTMGS grid + downstream DP coordination look-ahead ──────
# Hybrid Method III: the same exhaustive CTM grid sweep over [MIN_EXT, MAX_EXT]
# as dctsp_mp_ectm, but each candidate also carries a CELLQLEARN-style DP
# coordination penalty: the projected downstream-junction delay (bus + side
# cross-traffic) over the bus-trajectory horizon, geometrically discounted by
# MP_ECTM_DP_COORD_WEIGHT.  This counters CTMGS' myopia — an extension/insertion
# that locally helps the bus but burns cross-street green further along the
# corridor now scores worse.

def dctsp_mp_ectm_dp(self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
                     no_act_delay, sigma_in, remaining_red_s=0.0):
    dt = float(MP_ECTM_DT_S)
    q_sat_vps = float(getattr(self, 'SaturationFlow', 1800.0)) / 3600.0
    k_jam = float(getattr(self, 'JamDensity', 200.0))
    _bus_occ = float(getattr(self, 'BusOcc', 40.0))
    _cycle_s = float(self._signal_cycle_s()) if hasattr(self, '_signal_cycle_s') else float(self.config.get('CycleTime', 135.0) or 135.0)
    _bus_g_base = float(getattr(self, 'BusPhaseDuration', 20.0))
    _wrong_phase = (int(current_phase) != int(self.BusPhase))
    _car_occ = float(MP_ECTM_CAR_OCC)
    try:
        upf = np.asarray(getattr(self, 'UpFlowList', np.zeros((1,1))), dtype=float)
        rdt = np.asarray(getattr(self, 'RedDurationList', np.zeros((1,1))), dtype=float)
        upf_bus = upf[0].ravel() if upf.ndim >= 2 and upf.shape[0] > 0 else np.zeros(1)
        rdt_bus = rdt[0].ravel() if rdt.ndim >= 2 and rdt.shape[0] > 0 else np.zeros(1)
        pos_flow = upf_bus[upf_bus > 0.0]
        pos_red = rdt_bus[(rdt_bus > 0.0) & (rdt_bus < 2.0 * _cycle_s)]
        q_arr_bus_vps = (float(np.mean(pos_flow)) / 3600.0 if pos_flow.size > 0 else 300.0 / 3600.0)
        t_red_past = (float(np.max(pos_red)) if pos_red.size > 0 else 60.0)
        k_arr_b = q_arr_bus_vps * k_jam / max(q_sat_vps, 1e-9)
        w_back_b = q_arr_bus_vps / max(k_jam - k_arr_b, 1.0)
        n0_bus = max(0.0, w_back_b * t_red_past * k_jam)
    except Exception:
        q_arr_bus_vps = 300.0 / 3600.0
        n0_bus = 5.0
    _cap_veh = k_jam * 0.15
    # ── Passenger weighting for the approach cell ────────────────────────────
    # `n0_bus` is the LWR/shockwave estimate of the WHOLE approach queue in
    # vehicles and `q_arr_bus_vps` is the WHOLE approach flow -- neither is
    # bus-only -- so passing `_bus_occ` (40 pax/veh) into _ctm_delay_pax priced
    # every queued car as a 40-passenger bus (~16x overstatement).  Same defect
    # fixed in dctsp_bxt, where it drove constant max-length extensions and
    # gridlocked kg seeds 400/500.  Weight the cell by what it holds: the
    # subject bus at BusOcc, the remaining queue at CarOcc.
    _n_cell = max(float(n0_bus), 1.0)
    _cell_occ = ((min(1.0, _n_cell) * _bus_occ
                  + max(0.0, _n_cell - 1.0) * float(_car_occ)) / _n_cell)

    def _ctm_delay_pax(n0, q_arr, q_sat, t_wait, g_dur, occ):
        delay = 0.0; n = max(0.0, float(n0))
        for _ in range(max(0, int(round(float(t_wait) / dt)))):
            n = min(n + q_arr * dt, _cap_veh); delay += n * dt
        for _ in range(max(0, int(round(float(g_dur) / dt)))):
            q_out = min(q_sat, n / max(dt, 1e-9))
            n = max(0.0, n + q_arr * dt - q_out * dt); delay += n * dt
        return delay * float(occ)
    # ── DP coordination look-ahead: projected downstream delay over the
    # bus-trajectory horizon, discounted per stage by COORD_WEIGHT. ─────────
    _dp_horizon = float(MP_ECTM_DP_HORIZON_S)
    _dp_stage   = float(MP_ECTM_DP_STAGE_S)
    _coord_w    = float(MP_ECTM_DP_COORD_WEIGHT)
    # Real accumulated side-red at the current junction: the longest red being
    # held across non-bus phases becomes the cross-approach queue elapsed, so
    # the projected side cost is grounded in actual queue state (not 0).
    try:
        _rdt_all = np.asarray(getattr(self, 'RedDurationList', np.zeros((1, 1))), dtype=float)
        _side_red_elapsed = float(np.max(_rdt_all)) if _rdt_all.size else float(remaining_red_s)
    except Exception:
        _side_red_elapsed = float(remaining_red_s)
    _side_red_elapsed = max(0.0, min(_side_red_elapsed, 2.0 * _cycle_s))
    def _dp_proj_side_delay(_sr):
        """Real side-queue pax·s imposed by EXTRA red `_sr`: uses the live
        SideUpFlowList/SideUpDenList shockwave model when available (grounded
        in actual accumulated side queue), else the analytic cross model.
        Scaled by CROSS_TRAFFIC_COST_MULTIPLIER so it competes with the
        primary CTM terms (the analytic path already applies that factor)."""
        _cmult = float(CROSS_TRAFFIC_COST_MULTIPLIER or 2.0)
        try:
            _fn = getattr(self, '_compute_side_delay_penalty', None)
            if _fn is not None:
                _v = _fn(max(0.0, float(_sr)), _suppress_log=True)
                if _v and float(_v[0]) > 0.0:
                    return float(_v[0]) * _cmult
        except Exception:
            pass
        try:
            return float(self._dctsp_cross_traffic_delay_s(
                max(0.0, float(_sr)), queue_elapsed_s=_side_red_elapsed))
        except Exception:
            return 0.0
    def _dp_coord_penalty(side_red_s, bus_saved_paxs, shift_sec=0.0):
        """Projected coordination penalty (pax·s) of granting THIS action.
        side_red_s is the FULL extra red imposed on the cross approaches; the
        side term is the real SideUpFlowList-based queue delay, repeated per
        discounted stage.  The bus term is the REAL projected impact at the
        next managed downstream junction (from live corridor state) when a
        corridor coordinator is available; otherwise it falls back to the
        local CTM self-projection of THIS junction's future queue."""
        _proj_dside = _dp_proj_side_delay(side_red_s)
        _pen = 0.0
        _n_stages = max(0, int(_dp_horizon / max(_dp_stage, 1e-9)))
        for _si in range(min(_n_stages, 3)):
            _off = (_si + 1) * _dp_stage
            _proj_n0 = max(0.0, n0_bus - float(bus_saved_paxs) * 0.7
                           + q_arr_bus_vps * _off)
            _proj_dbus = _ctm_delay_pax(_proj_n0, q_arr_bus_vps, q_sat_vps,
                                        0.0, _bus_g_base, _cell_occ)
            _pen += (_proj_dbus + _proj_dside) * (_coord_w ** (_si + 1))
        # ── Real downstream-junction projection (Z2, corridor-aware) ────────
        # The bus time shift at THIS junction moves the bus's arrival at the
        # NEXT managed junction; project its red-wait there from the live
        # downstream phase schedule.  Positive = coordination cost, negative =
        # coordination benefit.  shift_sec is the ACTION's time shift in
        # seconds (capped by the bus's actual no-action delay) — the pax·s
        # savings can be ~0 even for a real action, so the raw action duration
        # is the robust driver of the downstream projection.
        try:
            _coord = getattr(self, '_corridor_coord', None)
            if _coord is not None:
                _bs_sec = max(0.0, float(shift_sec))
                if _bs_sec > 0.0:
                    _pen += float(_coord.project_downstream_delay_paxs(
                        int(self.id), int(veh_id), float(time), float(timeSta),
                        float(bus_eta_s), _bs_sec, _bus_occ))
        except Exception:
            pass
        return _pen
    if _wrong_phase:
        _t_wait_na = float(remaining_red_s); _g_bus_na = _bus_g_base
    else:
        _t_wait_na = 0.0; _g_bus_na = float(remaining_red_s)
    # ETA correction: a bus still `bus_eta_s` away has NOT been waiting the full
    # remaining red — it only accrues delay from the moment it reaches the
    # stopline (same rationale as dctsp_mp_ectm).
    _eta = max(0.0, float(bus_eta_s))
    d_bus_na = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                              max(0.0, _t_wait_na - _eta), _g_bus_na, _cell_occ)
    d_side_na = float(self._dctsp_cross_traffic_delay_s(0.0))
    z_na = d_bus_na + d_side_na
    _d_min = float(MP_ECTM_MIN_EXT_S); _d_max = float(MP_ECTM_MAX_EXT_S)
    _d_step = float(dt)
    best_z = z_na; best_delta = 0.0; best_atype = 'NO_ACTION'
    best_d_bus = d_bus_na; best_d_side = d_side_na; best_dp_pen = 0.0
    _sweep_evals = []   # (atype, delta, d_bus, d_side, dp_pen) — the FULL CTM grid
    for _d_raw in np.arange(_d_min, _d_max + _d_step * 0.5, _d_step):
        delta = float(_d_raw)
        # The action's time shift at THIS junction (seconds): the bus can only
        # be pulled forward by as much as it is actually delayed without action.
        _act_shift = min(delta, max(0.0, float(no_act_delay)))
        if not _wrong_phase:
            d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps, 0.0, float(remaining_red_s) + delta, _cell_occ)
            d_side = float(self._dctsp_cross_traffic_delay_s(delta))
            _pen = _dp_coord_penalty(delta, d_bus_na - d_bus, _act_shift)
            z_ge = d_bus + d_side + _pen
            _sweep_evals.append(('GE', delta, d_bus, d_side, _pen))
            if z_ge < best_z:
                best_z = z_ge; best_delta = delta; best_atype = 'GE'
                best_d_bus = d_bus; best_d_side = d_side; best_dp_pen = _pen
        else:
            t_wait_post = float(remaining_red_s) + float(INS_INTERGREEN_S)
            d_bus_post = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                        max(0.0, t_wait_post - _eta), delta, _cell_occ)
            # ETA gate (mirrors _dctsp_eval_action INS rule): a bus still
            # `bus_eta_s` away cannot catch a short insertion — otherwise the
            # CTM queue model credits phantom savings from a few seconds of
            # green (INS_PRETERM_3 claimed up to ~62 000 pax·s).
            if float(bus_eta_s) > (max(0.0, delta) + float(INS_INTERGREEN_S)):
                d_bus_post = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                            max(0.0, t_wait_post), _bus_g_base, _cell_occ)
            d_side_post = float(self._dctsp_cross_traffic_delay_s(t_wait_post + delta))
            _pen_post = _dp_coord_penalty(t_wait_post + delta, d_bus_na - d_bus_post, _act_shift)
            z_post = d_bus_post + d_side_post + _pen_post
            _sweep_evals.append(('INS_POST', delta, d_bus_post, d_side_post, _pen_post))
            if z_post < best_z:
                best_z = z_post; best_delta = delta; best_atype = 'INS_POST'
                best_d_bus = d_bus_post; best_d_side = d_side_post; best_dp_pen = _pen_post
            _cut = max(0.0, float(remaining_red_s) - float(INS_INTERGREEN_S))
            d_bus_pt = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                      max(0.0, float(INS_INTERGREEN_S) - _eta),
                                      delta, _cell_occ)
            if float(bus_eta_s) > (max(0.0, delta) + float(INS_INTERGREEN_S)):
                d_bus_pt = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                          max(0.0, float(INS_INTERGREEN_S)),
                                          _bus_g_base, _cell_occ)
            d_side_pt = (float(self._dctsp_cross_traffic_delay_s(float(INS_INTERGREEN_S) + delta))
                         + float(self._dctsp_cross_traffic_delay_s(_cut)))
            _pen_pt = _dp_coord_penalty(float(INS_INTERGREEN_S) + delta + _cut, d_bus_na - d_bus_pt, _act_shift)
            z_pt = d_bus_pt + d_side_pt + _pen_pt
            _sweep_evals.append(('INS_PRETERM', delta, d_bus_pt, d_side_pt, _pen_pt))
            if z_pt < best_z:
                best_z = z_pt; best_delta = delta; best_atype = 'INS_PRETERM'
                best_d_bus = d_bus_pt; best_d_side = d_side_pt; best_dp_pen = _pen_pt
    eff_delay = max(0.0, float(no_act_delay) - float(ZIG_PHASE_OVERLAP_S))
    _satur_override = False
    if eff_delay < float(SELFORG_MIN_BUS_DELAY_S):
        best_atype = 'NO_ACTION'; best_delta = 0.0; _satur_override = True
    else:
        try:
            _o_d = _safe_float(self._safe_array_sum(getattr(self, 'OtherDelay', [0]))) + \
                   _safe_float(self._safe_array_sum(getattr(self, 'SideDelayBaseline', [0])))
            _bus_p = eff_delay * _bus_occ
            _side_p = max(0.0, _o_d) * _car_occ
            _ratio = _side_p / max(_bus_p, 1.0)
        except Exception:
            _ratio = 0.0
        _gate_factor = (float(MP_ECTM_GE_BALANCE_FACTOR) if best_atype == 'GE'
                        else float(MP_ECTM_BALANCE_FACTOR))
        if _ratio > _gate_factor:
            best_atype = 'NO_ACTION'; best_delta = 0.0; _satur_override = True
    r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
        self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
    rows = [('NO_ACTION', 0.0, r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na)]
    # Emit the FULL CTM grid sweep (each candidate with its DP coordination
    # penalty folded into the cross-phase cost), not just the argmin — the
    # Pareto layer needs the mode's whole model trade-off to distinguish
    # CTMGS_DP from CTMGS / GR_BASE.
    best_r = r_na; best_so = so_na; best_tp = tp_na; best_r_delta = 0.0
    if not _satur_override:
        for (at, delta, d_bus, d_side, dp_pen) in _sweep_evals:
            try:
                _, so_act, tp_act, bps_gated, _, nsd_act, std_act = _dctsp_eval_action(
                    self, at, delta, sigma_in, no_act_delay, bus_eta_s,
                    wrong_phase=_wrong_phase, remaining_red_s=remaining_red_s)
            except Exception:
                so_act, tp_act, bps_gated, nsd_act, std_act = so_na, tp_na, 0.0, nsd_na, std_na
            # Use the ETA-gated bus benefit from _dctsp_eval_action as the
            # authoritative value: it already applies the INS ETA gate (a bus still
            # `bus_eta_s` away cannot catch a short insertion) and the no_act_delay
            # cap, so the DP's raw CTM delta (d_bus_na - d_bus) cannot claim
            # phantom savings (INS_PRETERM_3 once claimed 62 000 pax·s ≈ 1 550 s
            # from a 3 s action).
            bps_ctm = min(max(0.0, float(bps_gated)),
                          max(0.0, d_bus_na - d_bus))
            cpc_ctm = max(0.0, d_side - d_side_na)
            # Same zero-cost fallback rationale as dctsp_mp_ectm: use MAX so the
            # live-count side cost binds whenever a bus benefit is claimed.
            if bps_ctm > 0.0:
                try:
                    _ectm_red = float(delta) + float(INS_INTERGREEN_S)
                    _sd, _ = self._compute_side_delay_penalty(_ectm_red, _suppress_log=True)
                    cpc_ctm = max(cpc_ctm, max(0.0, float(_sd)))
                except Exception:
                    pass
            # Fold the DP coordination look-ahead penalty into the emitted row's
            # cross-phase cost so the final max-reward / Pareto selection actually
            # sees the downstream impact (previously it only shaped the argmin and
            # was discarded when the row's reward was recomputed in engine.py).
            cpc_ctm += float(dp_pen)
            r_ctm   = bps_ctm - cpc_ctm
            rows.append((f'{at}_{delta:.0f}', delta,
                         r_ctm, so_act, tp_act, bps_ctm, cpc_ctm, nsd_act, std_act))
            if at == best_atype and abs(delta - best_delta) < 1e-6:
                best_r = r_ctm; best_so = so_act; best_tp = tp_act
                best_r_delta = r_ctm - r_na
    return (best_atype, best_delta, best_r, best_r_delta, best_so, best_tp, rows)


# ── Shared action-token helpers ───────────────────────────────────────────────
# Every candidate row uses one canonical label format so the Pareto layer and
# the execution dispatcher in engine.py can parse ANY mode's candidates.

_ACTION_LABEL_PREFIX = {
    'GE':                'GE',
    'INS':               'INS',
    'INS_POST':          'INS_POST',
    'INS_PRETERM':       'INS_PRETERM',
    'EARLY_RED':         'ER',
    'GREEN_REALLOC':     'GR',
    'OFFSET_CORRECTION': 'OC',
    'PHASE_SKIP':        'VP',
    'PHASE_ROTATION':    'PT',
}


def action_label(atype: str, param: float) -> str:
    """Canonical candidate label, e.g. ('GE', 10) -> 'GE_10'."""
    if atype == 'NO_ACTION':
        return 'NO_ACTION'
    _pfx = _ACTION_LABEL_PREFIX.get(str(atype), str(atype))
    # OFFSET_CORRECTION direction is encoded in the label sign ("OC_+5"/"OC_-5")
    # -- the executor reads it from the "+"; force the sign so a positive offset
    # is not mis-executed as negative.
    if str(atype) == 'OFFSET_CORRECTION':
        return f"{_pfx}_{float(param):+.0f}"
    return f"{_pfx}_{float(param):.0f}"


def parse_action_token(tok) -> tuple:
    """Map any candidate label to (exec_kind, param_s).

    exec_kind is one of {'NO_ACTION','GE','INS','GR','ER','OC','VP','PT'}
    — the execution branches implemented in engine.py.  INS_POST / INS_PRETERM
    / INS_close all map to 'INS'.  param_s is the trailing number in the label
    (absolute value; sign for OC stays encoded in the label) or None when the
    label carries no number (e.g. 'INS_close').
    """
    t = str(tok)
    if t == 'NO_ACTION':
        return 'NO_ACTION', 0.0
    _num = None
    if '_' in t:
        try:
            _num = abs(float(t.rsplit('_', 1)[1]))
        except (ValueError, TypeError):
            _num = None
    for _pfx, _kind in (('INS', 'INS'), ('GE', 'GE'),
                        ('EARLY_RED', 'ER'), ('GREEN_REALLOC', 'GR'),
                        ('ER', 'ER'), ('GR', 'GR'), ('OC', 'OC'),
                        ('VP', 'VP'), ('PT', 'PT')):
        if t.startswith(_pfx):
            return _kind, _num
    return 'NO_ACTION', 0.0


# ── Mode: DCTSP-BXT — CTM-based multiagent Q-learning ─────────────────────────
# Ported from kg/intersection_controller_lean.py (only existing implementation;
# the reference kg controller lineage never had BXT).
# Reference: Chanloha P., Chinrungrueng J., Usaha W. & Aswakul C. (2014),
# "Cell Transmission Model-Based Multiagent Q-Learning for Network-Scale
# Signal Control With Transit Priority", The Computer Journal 57(3), 451-466.

DCTSP_RL_ACTION_SPACE = [
    ('NO_ACTION',  0.0),
    ('GE',   5.0), ('GE',  10.0), ('GE',  15.0),
    ('INS', 10.0), ('INS', 15.0), ('INS', 20.0),
    ('EARLY_RED', 10.0), ('EARLY_RED', 20.0), ('EARLY_RED', 30.0),
    ('GREEN_REALLOC', 5.0), ('GREEN_REALLOC', 10.0), ('GREEN_REALLOC', 15.0),
    # NOTE 2026-08-24: OFFSET_CORRECTION×4 REMOVED from the bus-decision grid.
    # Every action here must be taken IN RELATION TO the detected bus (extend /
    # insert / advance the bus green). Offset correction is a NO-BUS coordination
    # action — it shifts a phase offset independent of any specific bus arrival,
    # and the champion search proved decentralized per-junction OC gridlocks the
    # corridor (CELLQLEARN_SAFE: 2–8 OC/run → car +237%). This restores the
    # 13-action bus-serving grid the surrounding code was written for. OC now
    # belongs only to a no-bus background coordinator (see below / TODO).
]

# Indices of the "advance the HELD bus's green" actions (INS + GREEN_REALLOC).
# In a wrong-phase state (bus phase not running) both bring the bus green
# forward; used for optimistic Q-init so a held bus gets served instead of the
# learner defaulting to NO_ACTION.
_BXT_HOLD_SERVING_IDX = [i for i, (a, _) in enumerate(DCTSP_RL_ACTION_SPACE)
                         if a in ('INS', 'GREEN_REALLOC')]

# BXT_INS_OPTIMISTIC_INIT: optimistic Q seed (pax-s) for the held-bus-serving
# actions in wrong-phase state bins. Pessimistic init (Q=0) left INS sample-
# starved -> it never fired in 4-seed training (champion search: INS=0 for every
# CELLQLEARN run) so the learner only ever EXTENDED green and could not match the
# INS-based winners. A small positive seed makes the greedy policy TRY inserting
# when a bus is held on red; the realized-advantage reward then keeps INS only
# where it actually pays (one gridlock outcome drives Q from +seed back to ~0 via
# Q += alpha*(realized_adv - Q)). 0 disables (pure pessimistic init). Tunable.
# 2026-08-24: DISABLED (120->0). The seed made the learner CHOOSE INS, but INS is
# blocked at EXECUTION by the guard stack in dctsp_bxt (esp. `_side_ratio >
# BXT_BALANCE_FACTOR` — insertion steals a cross phase so it is vetoed whenever
# side traffic is non-trivial). The pick converted to NO_ACTION, INS's Q got
# credited with NO_ACTION's outcome (corrupt learning), and the churn GRIDLOCKED
# training (car +55%, obj -20.7%). Selection was never the blocker — execution is.
BXT_INS_OPTIMISTIC_INIT = 0.0

# BXT_CTM_PRIOR_K: weight on the CTM-predicted advantage used to SEED a new
# Q-state (authentic cell-transmission-model Q-learning -- the CTM model provides
# the prior policy, realized experience refines it). 1.0 = seed at the full CTM
# advantage; 0 = old cold start (all-zero, model-free). BXT_CTM_PRIOR_CLIP_PAXS
# bounds any single seed so one over-confident CTM prediction cannot dominate
# before the alpha-scaled realized reward corrects it.
# 2026-08-24: DISABLED (1.0->0.0). The CTM prior GRIDLOCKED catastrophically
# (CELLQLEARN car +294%, obj -64%) and INS STILL = 0. Root cause = the exact flaw
# the old cold-start comment warned about: the CTM's action-benefit is MONOTONE in
# green duration and systematically over-values GE, so seeding from it made the
# learner extend green 31-48x/run -> gridlock, while INS (lower CTM advantage than
# GE) was never picked. The advantage-difference fixed the SCALE but not the
# GE-over-valuation. Confirms CELLQLEARN cannot be made competitive on KG.
BXT_CTM_PRIOR_K = 0.0
BXT_CTM_PRIOR_CLIP_PAXS = 500.0

# Q-table: {jct_id: {state_bin: [Q per action in DCTSP_RL_ACTION_SPACE]}}
_dctsp_bxt_q_table: dict = {}
# {veh_id: (jct_id, atype, aparam, decision_time, state_bin, action_idx)} —
# stored at decision time so a checkout hook can apply the terminal Q-update.
_poz_action_log: dict = {}
# Per-(junction,state) running mean of the realized delay under NO_ACTION.
# Actions are rewarded by their ADVANTAGE vs this baseline, so an action is only
# valued when it realizes LESS total delay than doing nothing typically does in
# that state -- self-baselining, and safe: NO_ACTION stays the reference (Q=0).
_bxt_noaction_baseline: dict = {}   # {(jct, state): [sum_delay, count]}


def _bxt_state_bin(n0_bus: float, side_ratio: float,
                   phase_is_bus: bool, bus_eta_s: float) -> tuple:
    """Discretise the per-decision state into a hashable 4-tuple."""
    if n0_bus < 2.0:    b_b = 0
    elif n0_bus < 8.0:  b_b = 1
    elif n0_bus < 20.0: b_b = 2
    else:               b_b = 3
    if side_ratio < 0.3:   s_b = 0
    elif side_ratio < 0.8: s_b = 1
    elif side_ratio < 1.5: s_b = 2
    else:                  s_b = 3
    if bus_eta_s < 5.0:    e_b = 0
    elif bus_eta_s < 15.0: e_b = 1
    elif bus_eta_s < 30.0: e_b = 2
    else:                  e_b = 3
    return (b_b, s_b, int(phase_is_bus), e_b)


def _bxt_q_key(jct_id: int):
    """Which Q-table a signal reads/writes.

    Default: per-signal independent learners (key = jct_id) -- each intersection
    fills its OWN 128-state x 17-action table from only the buses that pass it,
    which is sample-starved on a handful of training seeds.

    BXT_SHARE_Q_ACROSS_SIGNALS=True pools EVERY signal into one shared table
    (fixed key -1): the per-decision state (bus-queue bin, side-ratio, phase-is-
    bus, eta) is junction-agnostic, so a queue-8/eta-10 s decision at any signal
    trains the same Q entry.  ~N_signals x more samples per (state,action) ->
    convergence in far fewer episodes.  Trade-off: one shared policy, no per-
    junction specialisation (fine at low seed budgets where specialisation has no
    data anyway).
    """
    return -1 if bool(globals().get('BXT_SHARE_Q_ACROSS_SIGNALS', False)) else int(jct_id)


_BXT_POOL_KEY = -1   # cross-signal warm-start pool (option 1)


def _bxt_warmstart_on(jct_id: int) -> bool:
    """Warm-start mode: per-signal Q tables, but a junction's FIRST visit to a
    state is seeded from a cross-signal POOL (what other signals already learned)
    and then fine-tunes its own copy.  Unlike full sharing (§39, which over-
    generalised into gridlock) this keeps per-junction specialisation while still
    getting the sample-efficiency of pooled early experience.  Disabled when full
    sharing is on (the pool key would collide with the shared table)."""
    return (bool(globals().get('BXT_WARMSTART_FROM_SHARED', False))
            and _bxt_q_key(jct_id) != _BXT_POOL_KEY)


def _bxt_get_q(jct_id: int, state_bin: tuple, init_vals=None) -> list:
    """Return (and lazily initialise) the BXT Q-value list for (jct, state)."""
    n = len(DCTSP_RL_ACTION_SPACE)
    tbl = _dctsp_bxt_q_table.setdefault(_bxt_q_key(jct_id), {})
    if state_bin not in tbl:
        _warm = None
        if _bxt_warmstart_on(jct_id):
            _pool = _dctsp_bxt_q_table.get(_BXT_POOL_KEY)
            if _pool and state_bin in _pool:
                _warm = list(_pool[state_bin])   # copy the pooled estimate
        if _warm is not None and len(_warm) == n:
            tbl[state_bin] = _warm
        else:
            _init = (list(init_vals)
                     if (init_vals is not None and len(init_vals) == n)
                     else [0.0] * n)
            # Optimistic init for the held-bus-serving actions (traditional-TSP
            # prior). Only in WRONG-PHASE bins (state_bin[2] == 0 = bus phase not
            # running = a bus is held on red): seed INS / GR positive so the
            # greedy policy advances the bus green instead of defaulting to
            # NO_ACTION. Right-phase bins (bus green already up) keep Q=0 — there
            # the correct held-bus action is GE, learned normally.
            try:
                if len(state_bin) >= 3 and int(state_bin[2]) == 0:
                    _opt = float(globals().get('BXT_INS_OPTIMISTIC_INIT',
                                               BXT_INS_OPTIMISTIC_INIT) or 0.0)
                    if _opt > 0.0:
                        for _i in _BXT_HOLD_SERVING_IDX:
                            if _i < n:
                                _init[_i] = _opt
            except Exception:
                pass
            tbl[state_bin] = _init
    return tbl[state_bin]


def _bxt_update_q(jct_id: int, state_bin: tuple, action_idx: int,
                  r_bxt: float) -> float:
    """Terminal Q update: Q(s,a) += alpha * (r - Q(s,a)). Returns TD error."""
    q_cur = _bxt_get_q(jct_id, state_bin)
    td_err = r_bxt - q_cur[action_idx]
    q_cur[action_idx] += float(BXT_ALPHA) * td_err
    # Keep the cross-signal warm-start pool aggregating so a FUTURE first-visit at
    # another signal inherits this experience (option 1).
    if _bxt_warmstart_on(jct_id):
        _pool = _dctsp_bxt_q_table.setdefault(_BXT_POOL_KEY, {})
        _pn = _pool.get(state_bin)
        if _pn is None:
            _pn = [0.0] * len(DCTSP_RL_ACTION_SPACE); _pool[state_bin] = _pn
        _pn[action_idx] += float(BXT_ALPHA) * (r_bxt - _pn[action_idx])
    return td_err


def _bxt_delay_snapshot(self):
    """Read the junction's cumulative (bus_delay, car_delay) in pax-s.

    These are running totals maintained by the stats layer, so the DIFFERENCE
    between two snapshots is the realized delay accrued at this junction over
    the interval -- the ground-truth outcome an action is judged by.
    """
    try:
        _d = self.stats._inter.get(self.id, {})
        return (float(_d.get('delay_bus', 0.0) or 0.0),
                float(_d.get('delay_car', 0.0) or 0.0))
    except Exception:
        return (0.0, 0.0)


def _bxt_neighbor_jcts(self):
    """Corridor neighbors of this junction (same CorridorCoordinator group).

    Used for inter-intersection reward sharing: a decision here is judged not
    only by this junction's realized delay but also (weighted) by what it did
    to its corridor partners.  Returns [] outside a coordinator group.
    """
    try:
        import sys as _sys
        _eng = _sys.modules.get('shared_tsp_engine.engine')
        _coords = getattr(_eng, 'corridor_coordinators', None) if _eng else None
        _me = int(getattr(self, 'id', 0) or 0)
        for _coord in (_coords or []):
            try:
                _ids = [int(i) for i in (getattr(_coord, 'inter_ids', None) or [])]
            except Exception:
                continue
            if _me in _ids:
                return [i for i in _ids if i != _me]
    except Exception:
        pass
    return []


def _bxt_neighbor_snapshot(self):
    """{jct_id: (bus_delay0, car_delay0)} for each corridor neighbor."""
    _out = {}
    try:
        for _nid in _bxt_neighbor_jcts(self):
            try:
                _nd = self.stats._inter.get(int(_nid), {}) or {}
                _out[int(_nid)] = (float(_nd.get('delay_bus', 0.0) or 0.0),
                                   float(_nd.get('delay_car', 0.0) or 0.0))
            except Exception:
                continue
    except Exception:
        pass
    return _out


def _bxt_apply_pending_updates(self, time):
    """Close the RL loop: for each logged decision whose evaluation window has
    elapsed, measure the REALIZED delay accrued at the junction since the
    decision and apply the Q-update with that measured reward.

    reward = -(realized_bus_delay * BUS_PAX_WEIGHT + realized_car_delay
               + CORRIDOR_REWARD_NEIGHBOR_W * neighbor_delay_delta)  [pax-s]

    Absolute-reward formulation: NO_ACTION and every action are scored on the
    SAME realized-delay basis, so across many buses in the same state bin the
    Q-values converge to the true expected delay per action -- and any
    systematic mis-pricing in the analytic SEED (e.g. underpriced cross cost)
    is corrected by experience.  Lower realized delay -> higher Q -> chosen more.
    """
    if not globals().get('BXT_LEARN', True):
        return
    if str(globals().get('BXT_PHASE', 'per_seed')) == 'eval':
        return                      # frozen policy during evaluation
    if not _poz_action_log:
        return
    _now = float(time)
    _d1b, _d1c = _bxt_delay_snapshot(self)
    _done = []
    for _key, _rec in list(_poz_action_log.items()):
        # Only this junction's own decisions; keys are (jct_id, veh_id).
        if not (isinstance(_key, tuple) and len(_key) == 2 and _key[0] == int(self.id)):
            continue
        if not isinstance(_rec, dict):
            _done.append(_key); continue
        if _now < float(_rec.get('due_t', 0.0)):
            continue
        try:
            # ── REALIZED-delay reward ─────────────────────────────────────
            # The counterfactual reward credited the action's PREDICTED bus
            # benefit (no_act_delay*BusOcc, always large-positive) minus a LOCAL
            # short-window car cost -> systematically positive -> the model
            # learned to ACT MORE (action rate rose 25%->42% over training) and
            # gridlocked.  Proof it was wrong: when acting gridlocked, the BUS
            # delay ALSO exploded (+114%) -- the predicted benefit was never
            # delivered, yet the reward paid it anyway.
            #
            # Measured realized delay (pax-s) accrued at the junction over the
            # window -- the ground-truth outcome of this decision.
            _rb = max(0.0, _d1b - float(_rec.get('delay_bus0', 0.0)))
            _rc = max(0.0, _d1c - float(_rec.get('delay_car0', 0.0)))
            # v7 bus equity: bus pax-s count for BUS_PAX_WEIGHT times a car
            # pax-s in the reward (buses are rare but pack ~27x the people;
            # both NO_ACTION baseline and actions get the same weight).
            _eqw_l = max(0.0, float(globals().get('BUS_PAX_WEIGHT',
                                                  BUS_PAX_WEIGHT) or 1.0))
            # v7 inter-intersection reward sharing: add the SIGNED realized
            # delay delta of this junction's corridor neighbors over the same
            # window (weighted).  Negative delta = neighbors got faster = my
            # action helped the corridor = reward rises; queue-shoving onto the
            # next junction now costs instead of paying locally.
            _nbr_delta = 0.0
            _nbw = float(globals().get('CORRIDOR_REWARD_NEIGHBOR_W',
                                       CORRIDOR_REWARD_NEIGHBOR_W) or 0.0)
            if _nbw > 0.0:
                try:
                    _inter_stats = getattr(getattr(self, 'stats', None), '_inter', {}) or {}
                    for _nid, _snap in (_rec.get('nbr_delay0') or {}).items():
                        try:
                            _nd = _inter_stats.get(int(_nid), {}) or {}
                            _nbr_delta += (
                                (float(_nd.get('delay_bus', 0.0) or 0.0)
                                 - float(_snap[0]))
                                + (float(_nd.get('delay_car', 0.0) or 0.0)
                                   - float(_snap[1])))
                        except Exception:
                            continue
                except Exception:
                    _nbr_delta = 0.0
            _realized = (_rb * _eqw_l + _rc) + _nbw * _nbr_delta
            _reward = 0.0
            _st = _rec['state']
            # Key the NO_ACTION baseline the same way as the Q-table so pooled
            # (shared-Q) learning also pools the baseline it is judged against.
            _bkey = (_bxt_q_key(self.id), tuple(_st) if isinstance(_st, (list, tuple)) else _st)
            _is_action = str(_rec.get('atype', 'NO_ACTION')) != 'NO_ACTION'
            if not _is_action:
                # NO_ACTION defines the baseline: track the running-mean realized
                # delay of doing nothing in this state.  Its own Q stays at the
                # cold-start 0 reference (never updated), so an action must
                # positively BEAT the baseline to be chosen.
                _bl = _bxt_noaction_baseline.setdefault(_bkey, [0.0, 0])
                _bl[0] += _realized; _bl[1] += 1
            else:
                # ADVANTAGE reward: how much LESS delay this action realized than
                # NO_ACTION typically does here.  Positive -> action helped ->
                # Q rises above 0 -> chosen; gridlock -> _realized >> baseline ->
                # large negative -> Q drops -> abandoned.  Skip until a baseline
                # exists (cold start stays conservative: unscored actions keep
                # Q=0 = NO_ACTION, tie -> NO_ACTION).
                _bl = _bxt_noaction_baseline.get(_bkey)
                if _bl and _bl[1] > 0:
                    _baseline = _bl[0] / _bl[1]
                    _reward = _baseline - _realized
                    _bxt_update_q(int(self.id), _st, int(_rec['action_idx']), _reward)
            if globals().get('LOG_REWARD', False):
                _log_func(self,
                    "[BXT_LEARN] inter=%s bus=%s action=%s_%.0f realized_bus=%.0f "
                    "realized_car=%.0f nbr_delta=%.0f reward=%.0f" % (
                        self.id, _key[1], _rec.get('atype'), _rec.get('param', 0.0),
                        _rb, _rc, _nbr_delta, _reward))
        except Exception:
            pass
        _done.append(_key)
    for _k in _done:
        _poz_action_log.pop(_k, None)


def dctsp_bxt(self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
              no_act_delay, sigma_in, remaining_red_s=0.0):
    """CTM red-light-delay Q-learning candidate generation (BXT mode).

    Returns (best_type, best_param, best_r, best_r_delta, best_sigma_out,
    best_t_poz, rows) — same contract as dctsp_zig / dctsp_mp_ectm.
    """
    import random as _rnd_bxt

    dt           = float(BXT_DT_S)
    q_sat_vps    = float(getattr(self, 'SaturationFlow', 1800.0)) / 3600.0
    k_jam        = float(getattr(self, 'JamDensity', 200.0))
    _bus_occ     = float(getattr(self, 'BusOcc', 40.0))
    _cycle_s = float(self._signal_cycle_s()) if hasattr(self, '_signal_cycle_s') else float(self.config.get('CycleTime', 135.0) or 135.0)
    _bus_g_base  = float(getattr(self, 'BusPhaseDuration', 20.0))
    _wrong_phase = (int(current_phase) != int(self.BusPhase))

    # ── Estimate initial bus-approach queue n0 (LWR back-shockwave) ──────────
    try:
        upf = np.asarray(getattr(self, 'UpFlowList', np.zeros((1, 1))), dtype=float)
        rdt = np.asarray(getattr(self, 'RedDurationList', np.zeros((1, 1))), dtype=float)
        upf_bus = upf[0].ravel() if upf.ndim >= 2 and upf.shape[0] > 0 else np.zeros(1)
        rdt_bus = rdt[0].ravel() if rdt.ndim >= 2 and rdt.shape[0] > 0 else np.zeros(1)
        pos_flow = upf_bus[upf_bus > 0.0]
        pos_red = rdt_bus[(rdt_bus > 0.0) & (rdt_bus < 2.0 * _cycle_s)]
        q_arr_bus_vps = (float(np.mean(pos_flow)) / 3600.0
                         if pos_flow.size > 0 else 300.0 / 3600.0)
        t_red_past = (float(np.max(pos_red)) if pos_red.size > 0 else 60.0)
        k_arr_b = q_arr_bus_vps * k_jam / max(q_sat_vps, 1e-9)
        w_back_b = q_arr_bus_vps / max(k_jam - k_arr_b, 1.0)
        n0_bus = max(0.0, w_back_b * t_red_past * k_jam)
    except Exception:
        q_arr_bus_vps = 300.0 / 3600.0
        n0_bus = 5.0

    # ── Passenger weighting for the approach cell ────────────────────────────
    # `n0_bus` is the LWR/shockwave estimate of the WHOLE approach queue in
    # vehicles and `q_arr_bus_vps` is the WHOLE approach flow -- neither is
    # bus-only.  Passing `_bus_occ` (40 pax/veh) into _ctm_red_delay therefore
    # priced every queued car as a 40-passenger bus: a 30-vehicle queue scored
    # 1200 passengers against a true ~1 bus + 29 cars = ~75, a ~16x
    # overstatement.  Combined with the full-cycle horizon that made GE_15 look
    # worth 9-16k pax-s against a ~225 pax-s side cost (a 34-64x benefit/cost
    # ratio), so maximum-length extension won ~90% of evaluations and fired
    # ~300 times per run.  kg seeds 400/500 gridlocked: car delay +105%, bus
    # delay itself +35% from spillback, objective 149->91 and 113->46.
    #
    # Weight the cell by what it actually holds: the subject bus at BusOcc and
    # the remaining queued vehicles at CarOcc.
    _car_occ_cell = float(getattr(self, 'CarOcc', None)
                          or globals().get('BXT_CAR_OCC', 1.2) or 1.2)
    _n_cell = max(float(n0_bus), 1.0)
    _cell_occ = ((min(1.0, _n_cell) * _bus_occ
                  + max(0.0, _n_cell - 1.0) * _car_occ_cell) / _n_cell)

    _cap_veh = k_jam * 0.15

    def _ctm_red_delay(n0, q_arr, q_sat, t_wait_red, g_dur, occ):
        """Pax-seconds accumulated by the bus-approach cell over one cycle.

        Cell recursion (Eq. 29-30): occupancy `n` fills at the arrival rate
        while the approach is red (bounded by cell storage `_cap_veh`) and
        discharges at the sending flow `min(q_sat, n/dt)` while it is green.

        The horizon runs red -> green -> RED-AGAIN for the balance of the
        cycle.  That third segment is what makes the model a cell-transmission
        model rather than a one-shot queue formula: whatever occupancy cannot
        discharge before the signal returns to red PERSISTS in the cell and
        keeps accruing delay.  Without it the green loop drained `n` and then
        threw the state away, which had two consequences that made the action
        set unscoreable:

          * with t_wait_red = 0 (bus already has green) the delay integral is
            empty, so NO_ACTION, GE, EARLY_RED and GREEN_REALLOC all returned
            d_bus = 0 and were indistinguishable;
          * lengthening green (GE/GREEN_REALLOC) or shortening it (EARLY_RED)
            changed only the discarded residual, so the model could not price
            the very mechanism TSP operates through.

        Carrying the residual makes both effects observable in the same units,
        using the identical recursion for every segment.
        """
        delay = 0.0
        n = max(0.0, float(n0))

        def _red(dur):
            nonlocal delay, n
            for _ in range(max(0, int(round(float(dur) / dt)))):
                n = min(n + q_arr * dt, _cap_veh)
                delay += n * dt

        def _green(dur):
            nonlocal n
            for _ in range(max(0, int(round(float(dur) / dt)))):
                q_out = min(q_sat, n / max(dt, 1e-9))
                n = max(0.0, n + q_arr * dt - q_out * dt)

        _red(t_wait_red)
        _green(g_dur)
        # Balance of the cycle: the approach is red again and the un-served
        # residual waits it out under the same fill dynamics.
        _red(max(0.0, _cycle_s - float(t_wait_red) - float(g_dur)))
        return delay * float(occ)

    # ── Solved action durations (replaces the coarse {5,10,15} grid) ─────────
    # The action space offers GE/GR/INS at FIXED durations {5,10,15,20}.  With
    # the cost term underpriced, CTM reward is monotone in duration, so the grid
    # CEILING won ~80% of picks: measured kg seed 500, 265/350 GE picks were
    # GE_15 and 65% of those were on buses with eff_delay < 5 s -- i.e. it held
    # the green a full 15 s for buses that already make it.  A fixed grid also
    # cannot land on the true optimum and is implicitly tuned to kg's 135 s
    # cycle (wrong for Logan's 90-200 s).
    #
    # The legacy GE path (engine.py ~10280) already SOLVES this: extend by the
    # exact deficit the bus is short of clearing the current bus-green, bounded
    # by the network's own limits, and grant ZERO if the bus already makes it.
    # Reproduce that here so BXT stops paying for extensions no bus needs.
    #   deficit = bus_eta_s - green_left   (green_left = current bus-green if the
    #   bus phase is running, else 0 -- a wrong-phase bus needs a new window, not
    #   an extension of the phase it is NOT waiting on).
    _ge_ub = min(float(getattr(self, 'GE_upper_bound', 20.0) or 20.0),
                 float(MAX_GE_EXTENSION_S))
    _green_left = float(remaining_red_s) if not _wrong_phase else 0.0
    _ge_star = min(max(0.0, float(bus_eta_s) - _green_left), _ge_ub)
    # Insertion serves the bus its clearance window, not a fixed 10-20 s block;
    # bound by the disruptiveness cap already applied downstream.
    _ins_star = min(max(0.0, float(bus_eta_s) - _green_left), float(BXT_MAX_INS_S))
    _MIN_EFFECTIVE_GE_S = 1.0
    _solved_param = {'GE': _ge_star, 'GREEN_REALLOC': _ge_star, 'INS': _ins_star}

    # ── Individual-bus catch/miss term ───────────────────────────────────────
    # `_ctm_red_delay` models the APPROACH-QUEUE delay only; for a bus that
    # already has green (right phase) its wait integral is empty, so the CTM
    # cannot see the one thing a green extension buys -- THIS bus catching THIS
    # green instead of waiting a whole cycle for the next one.  Under correct
    # cost that made NO_ACTION win every right-phase decision (the queue term is
    # common to all actions, so only the side cost differed), which is exactly
    # why the old underpriced-cost build had to exist to fire at all.
    #
    # Model it explicitly: a bus that is NOT cleared this cycle incurs
    # `no_act_delay` seconds of wait at bus occupancy; a bus that IS cleared
    # incurs none.  This delta -- not the queue integral -- is what a TSP action
    # actually trades against cross-traffic cost.
    _raw_deficit = max(0.0, float(bus_eta_s) - _green_left)
    _bus_wait_pax = max(0.0, float(no_act_delay)) * _bus_occ

    def _bxt_reward_for(atype, aparam):
        # Grid durations are overridden by the solved value for the families
        # that support it; EARLY_RED keeps its grid (it is a phase truncation,
        # bounded by remaining_red_s, not an extend-to-clear action).
        """Return (r_bxt, d_bus, d_side): r_bxt = -(queue + bus wait + side), pax·s."""
        aparam = _solved_param.get(atype, aparam)
        a_s = float(aparam)
        if atype == 'NO_ACTION':
            if _wrong_phase:
                t_wait = float(remaining_red_s); g_bus = _bus_g_base
            else:
                t_wait = 0.0; g_bus = float(remaining_red_s)
            d_bus = _ctm_red_delay(n0_bus, q_arr_bus_vps, q_sat_vps, t_wait, g_bus, _cell_occ)
            d_bus += _bus_wait_pax                       # bus is NOT cleared
            d_side = float(self._dctsp_cross_traffic_delay_s(0.0))
            return -(d_bus + d_side), d_bus, d_side
        if atype == 'GE':
            if not _wrong_phase:
                d_bus = _ctm_red_delay(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       0.0, float(remaining_red_s) + a_s, _cell_occ)
                d_side = float(self._dctsp_cross_traffic_delay_s(a_s))
                # Cleared iff the extension actually reaches the bus.
                if not (a_s > 0.0 and _raw_deficit <= _ge_ub + 1e-6):
                    d_bus += _bus_wait_pax
            else:
                # Extending the wrong phase does NOT clear the bus (it lengthens
                # the phase the bus is waiting on); no catch credit.
                d_bus = _ctm_red_delay(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       float(remaining_red_s) + a_s, _bus_g_base, _cell_occ)
                d_bus += _bus_wait_pax
                d_side = float(self._dctsp_cross_traffic_delay_s(0.0))
            return -(d_bus + d_side), d_bus, d_side
        if atype == 'INS':
            t_wait = float(remaining_red_s) + float(INS_INTERGREEN_S)
            d_bus = _ctm_red_delay(n0_bus, q_arr_bus_vps, q_sat_vps, t_wait, a_s, _cell_occ)
            if not (a_s > 0.0 and _raw_deficit <= float(BXT_MAX_INS_S) + 1e-6):
                d_bus += _bus_wait_pax
            d_side = float(self._dctsp_cross_traffic_delay_s(t_wait + a_s))
            return -(d_bus + d_side), d_bus, d_side
        if atype == 'GREEN_REALLOC':
            # Reallocation moves `a_s` of green to the BUS phase.  Unlike GE it
            # also helps when the bus is held on red: it brings the bus green
            # forward / lengthens it.  Cross traffic pays for the moved green.
            if not _wrong_phase:
                d_bus = _ctm_red_delay(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       0.0, float(remaining_red_s) + a_s, _cell_occ)
            else:
                d_bus = _ctm_red_delay(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       float(remaining_red_s), _bus_g_base + a_s, _cell_occ)
            if not (a_s > 0.0 and _raw_deficit <= _ge_ub + 1e-6):
                d_bus += _bus_wait_pax
            d_side = float(self._dctsp_cross_traffic_delay_s(a_s))
            return -(d_bus + d_side), d_bus, d_side
        if atype == 'EARLY_RED':
            # ER truncates the CURRENT phase by `a_s`.
            if _wrong_phase:
                # Bus held while a cross phase runs: cutting that phase short
                # brings the bus's green forward by up to `a_s`.  It clears the
                # bus only if that advance covers the deficit.
                d_bus = _ctm_red_delay(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       max(0.0, float(remaining_red_s) - a_s),
                                       _bus_g_base, _cell_occ)
                if not (a_s > 0.0 and a_s + 1e-6 >= _raw_deficit and _raw_deficit > 0.0):
                    d_bus += _bus_wait_pax
                d_side = float(self._dctsp_cross_traffic_delay_s(a_s))
            else:
                # The BUS phase itself is running: truncating it shortens the
                # bus's own green and can only make the bus MORE likely to miss,
                # so it never clears a pending bus.
                d_bus = _ctm_red_delay(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       0.0, max(0.0, float(remaining_red_s) - a_s),
                                       _cell_occ)
                d_bus += _bus_wait_pax
                d_side = float(self._dctsp_cross_traffic_delay_s(0.0))
            return -(d_bus + d_side), d_bus, d_side
        # Unmodelled action type -> fall back to the NO_ACTION evaluation, NOT
        # 0.0.  Every real evaluation returns a NEGATIVE pax-s reward, so a
        # literal 0.0 was the largest value this function could produce and any
        # unmodelled action won the Q-table argmax outright.  EARLY_RED and
        # GREEN_REALLOC (6 of the 13 entries in DCTSP_RL_ACTION_SPACE) hit that
        # path, and _bxt_get_q seeds the table directly from these values, so
        # index 7 -- EARLY_RED 10 s, the first unevaluated entry -- was chosen
        # 44 times in one kg run purely for never having been evaluated.
        # Returning the do-nothing baseline means an unmodelled action can at
        # best TIE with NO_ACTION, and max() resolves ties to the lowest index,
        # which is NO_ACTION itself.  This keeps the failure mode safe if the
        # action space is extended again.
        return _bxt_reward_for('NO_ACTION', 0.0)

    _bxt_evals  = [_bxt_reward_for(_at, _ap) for (_at, _ap) in DCTSP_RL_ACTION_SPACE]
    bxt_rewards = [_e[0] for _e in _bxt_evals]
    # ── CTM-predicted ADVANTAGE of each action vs NO_ACTION (pax·s) ───────────
    # This is the model-based signal that makes the method genuinely CELL-
    # TRANSMISSION-MODEL Q-learning: _ctm_red_delay integrates the approach cell's
    # occupancy over red->green->red (Eq. 29-30) and the bus catch/miss term, so
    # bxt_rewards[a] = -(cell delay + bus wait + cross cost) is the CTM's own
    # prediction of total pax-delay under action a. The DIFFERENCE below cancels
    # the large queue-integral baseline common to every action (that ±100k baseline
    # is exactly why the old code refused to seed Q from raw bxt_rewards), leaving
    # only each action's MARGINAL effect — which is on the same scale as the
    # realized-advantage learning reward, so it is a valid CTM prior for the Q-table.
    _ctm_adv = [float(r) - float(bxt_rewards[0]) for r in bxt_rewards]

    # ── State bins ────────────────────────────────────────────────────────────
    # `eff_delay` is bound HERE, before the [BXT] log below consumes it.  It
    # used to be assigned only after the log statement (in the saturation
    # guard), so every call raised UnboundLocalError, the dispatcher in
    # engine.py swallowed it, and BXT/CellQLearn silently never committed an
    # action -- the run fell through to the generic GE/INS candidate pool.
    # _o_occ / _o_d are pre-seeded for the same reason: they are logged
    # unconditionally but were only bound inside the try below.
    eff_delay = max(0.0, float(no_act_delay) - float(ZIG_PHASE_OVERLAP_S))
    _o_occ = 0.0
    _o_d = 0.0
    try:
        _o_occ = self._estimated_other_vehicle_occupancy()
        _o_d = (_safe_float(self._safe_array_sum(getattr(self, 'OtherDelay', [0])))
                + _safe_float(self._safe_array_sum(
                    getattr(self, 'SideDelayBaseline', [0]))))
        _bus_p = eff_delay * _bus_occ
        _side_p = max(0.0, _o_d) * float(_o_occ)
        _side_ratio = _side_p / max(_bus_p, 1.0)
    except Exception:
        _side_ratio = 0.0
    _bxt_state = _bxt_state_bin(n0_bus, _side_ratio, not _wrong_phase, float(bus_eta_s))

    # ── epsilon-greedy over the Q-table (initialised from CTM rewards) ───────
    # Phase-aware exploration: train seeds explore (BXT_TRAIN_EPSILON, ~0.1) so
    # the Q-table sees alternatives to learn from; eval seeds are GREEDY (eps=0)
    # so the measured policy is deterministic and leakage-free; default/per-seed
    # uses BXT_EPSILON.
    _phase = str(globals().get('BXT_PHASE', 'per_seed'))
    if _phase == 'eval':
        _eff_eps = 0.0
    elif _phase == 'train':
        _eff_eps = float(globals().get('BXT_TRAIN_EPSILON', 0.1))
    else:
        _eff_eps = float(BXT_EPSILON)
    _use_explore = (_rnd_bxt.random() < _eff_eps)
    # ── Q-table SEED: CTM-predicted advantage (authentic CTM Q-learning) ─────
    # A NEW (state) bin starts at the CTM's own prediction of each action's
    # advantage, so the FIRST decision in that state is driven by cell-transmission
    # physics rather than a cold NO_ACTION default (which left INS sample-starved
    # and the whole learner toothless). The realized-advantage reward then REFINES
    # each visited (state,action) toward its measured outcome — model-based init,
    # model-free correction. The old ±100k-scale failure was from seeding the RAW
    # bxt_rewards (which carry the common queue baseline); `_ctm_adv` is the
    # baseline-cancelled DIFFERENCE, on the reward's own scale. Clipped so a single
    # over-confident CTM prediction cannot dominate before experience corrects it.
    # BXT_CTM_PRIOR_K=0 falls back to the old cold start.
    _ctm_k = float(globals().get('BXT_CTM_PRIOR_K', BXT_CTM_PRIOR_K) or 0.0)
    if _ctm_k > 0.0:
        _clip = float(BXT_CTM_PRIOR_CLIP_PAXS)
        _init_q = [max(-_clip, min(_clip, _ctm_k * _a)) for _a in _ctm_adv]
        _init_q[0] = 0.0   # NO_ACTION stays the 0 reference (its own advantage is 0)
    else:
        _init_q = [0.0] * len(DCTSP_RL_ACTION_SPACE)
    q_vals = _bxt_get_q(self.id, _bxt_state, init_vals=_init_q)
    if _use_explore:
        _chosen_idx = _rnd_bxt.randrange(len(DCTSP_RL_ACTION_SPACE))
    else:
        _chosen_idx = max(range(len(q_vals)), key=lambda i: q_vals[i])
    _chosen_atype, _chosen_aparam = DCTSP_RL_ACTION_SPACE[_chosen_idx]

    # ── Solve the action MAGNITUDE against the true total-system-delay ────────
    # The Q-table argmax picks the action FAMILY; the magnitude is not a grid
    # value.  For a green extension to the bus phase (GE, or GREEN_REALLOC while
    # the bus phase runs) we HARMONY-SEARCH the seconds that minimise total
    # passenger delay -- bus_delay*BusOcc + other_delay*other_occ from real
    # shockwave queue dynamics -- and act only if that beats doing nothing.
    # This replaces the discrete grid AND the underpriced CTM cross-cost proxy
    # in one move: the objective's other_delay term is the REAL car/side cost,
    # so the solver cannot over-extend (too much GE raises other_delay and is
    # rejected).  EARLY_RED (a phase truncation) keeps the analytic deficit.
    # Right-phase EARLY_RED shortens the bus's own green -> only hurts the bus.
    if _chosen_atype == 'EARLY_RED' and not _wrong_phase:
        _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    _ge_solve_family = (_chosen_atype == 'GE'
                        or (_chosen_atype == 'GREEN_REALLOC' and not _wrong_phase))
    # Wrong-phase GR advances the bus green by cutting the current CROSS phase
    # short; INS inserts a bus green.  Both are the "bring the held bus's green
    # forward" case, modelled by BP_Objective_Function (total pax delay for the
    # advanced/inserted bus green vs the cross cost of the shortened phase).
    # EARLY_RED on the WRONG phase truncates the current cross phase, advancing
    # the bus green -- mechanically the same "bring the held bus forward" case
    # as wrong-phase GR, so it solves against the same BP objective.  On the
    # RIGHT phase EARLY_RED only shortens the bus's OWN green (pure harm) and is
    # never worth doing -> suppressed below.
    _bp_solve_family = ((_chosen_atype == 'GREEN_REALLOC' and _wrong_phase)
                        or _chosen_atype == 'INS'
                        or (_chosen_atype == 'EARLY_RED' and _wrong_phase))
    # ── Bus benefit from the RELIABLE timing delay (not the degenerate objective)
    # [DELAY_DIAG] proved GE/BP_Objective_Function return ~0 bus delay even for
    # buses held 90-100 s, because they model delay via shockwave KINEMATICS
    # (bus approaching at BusSpeed joining a queue) which collapses to 0 when the
    # bus is STOPPED -- exactly the held-on-red buses TSP exists for.  So the old
    # "act iff opt_pax < base_pax" gate never fired.  Decide instead on the
    # timing delay `no_act_delay` (median 17.5 s on held buses, reliable), and
    # use harmony only to size the magnitude.
    _bus_benefit_paxs = (max(0.0, float(no_act_delay)) * _bus_occ
                         * max(0.0, float(globals().get('BUS_PAX_WEIGHT',
                                                        BUS_PAX_WEIGHT) or 1.0)))
    # A bus crawling at <= 3 m/s is effectively STOPPED in the queue; the
    # kinematic objective treats it as ~0 delay, but it is genuinely waiting, so
    # trust the timing benefit (already does -- no_act_delay ignores BusSpeed).
    try:
        _bus_spd = (float(np.max(np.asarray(self.BusSpeed[0], dtype=float)))
                    if hasattr(self, 'BusSpeed') and len(self.BusSpeed) > 0 else 0.0)
    except Exception:
        _bus_spd = 0.0
    _bus_stopped = _bus_spd <= 3.0

    def _cross_cost_paxs(_mag):
        # Real cross-traffic pax-s cost of an action of _mag seconds.  Take the
        # larger of the analytic estimate and the live side-count penalty so a
        # thin analytic value cannot under-price the action.
        try:
            _a = float(self._dctsp_cross_traffic_delay_s(max(0.0, _mag)))
        except Exception:
            _a = 0.0
        try:
            _sd, _ = self._compute_side_delay_penalty(max(0.0, _mag), _suppress_log=True)
            _b = max(0.0, float(_sd)) * max(safe_float(getattr(self, 'CarOcc', 1.2)), 1.0)
        except Exception:
            _b = 0.0
        return max(_a, _b)

    if _ge_solve_family:
        # Magnitude: harmony-solved (returns ~the deficit when the bus-delay
        # objective is degenerate) bounded to what catches the bus.
        _mag = min(_ge_star, _ge_ub)
        # BXT_SOLVER='deficit' (recommended): use the closed-form deficit `_ge_star`
        # -- exactly the green the bus needs to clear -- and SKIP the objective
        # optimiser. Both harmony and golden minimise the shockwave objective,
        # which returns ~0 bus delay for a stopped bus; optimising that degenerate
        # curve produced worse magnitudes and gridlock (golden: KG 140->105). The
        # deficit is O(1), deterministic, and needs no (broken) objective.
        _use_solver = str(globals().get('BXT_SOLVER', 'harmony')).lower() != 'deficit'
        if (_use_solver and hasattr(self, 'solve_green_extension')
                and _ge_ub > _MIN_EFFECTIVE_GE_S and _raw_deficit >= _MIN_EFFECTIVE_GE_S):
            try:
                _opt_ge, _, _ = self.solve_green_extension(
                    min(_ge_star, _ge_ub), _ge_ub, time)
                if _opt_ge >= _MIN_EFFECTIVE_GE_S:
                    _mag = float(_opt_ge)
            except Exception:
                pass
        # ── ETA-reachability gate (fixes far-ETA GEs that never help the bus) ──
        # A GE extends the CURRENT bus green by at most _ge_ub, so it can only
        # bridge a bus arriving within (green_left + _ge_ub). The corridor pre-arm
        # was firing GE_10 for buses 100-230 s away (measured: 9/12 executed GEs
        # had eta>45 s, median 107 s) -- useless extensions that cost cross
        # traffic but never reach the bus, so bus delay never fell. Require the
        # bus to actually arrive during the extended green.
        _ge_reach = float(_green_left) + float(_ge_ub) + 5.0
        _eta_ok = float(bus_eta_s) <= _ge_reach
        # A stopped bus (<=3 m/s) sitting in the bus-phase queue benefits from
        # extension so the queue discharges and it clears -- its kinematic
        # "deficit" is unreliable, so allow action on benefit vs cost directly --
        # but STILL only if it is within reach (the _bus_stopped bypass + broken
        # Kalman speed was the hole the far-ETA pre-arm GEs slipped through).
        _catchable = _eta_ok and (
            (_raw_deficit >= _MIN_EFFECTIVE_GE_S and _raw_deficit <= _ge_ub + 1e-6)
            or (_bus_stopped and float(no_act_delay) >= _MIN_EFFECTIVE_GE_S))
        if _bus_stopped and _mag < _MIN_EFFECTIVE_GE_S:
            _mag = min(_ge_ub, max(_MIN_EFFECTIVE_GE_S, float(_ge_star) or _ge_ub))
        # Q-argmax already chose to ACT (it picked this family over NO_ACTION);
        # commit at the solved magnitude if the action is physically meaningful.
        # NO benefit>cost veto -- the closed-loop reward (realized car cost) is
        # what teaches the Q-table whether acting here was worth it, so a
        # hard-coded (and underpriced) gate must not override the learned policy.
        if _catchable and _mag >= _MIN_EFFECTIVE_GE_S:
            _chosen_aparam = float(_mag)
        else:
            _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif _bp_solve_family:
        _bp_ub = float(BXT_MAX_INS_S) if _chosen_atype == 'INS' else _ge_ub
        _mag = min(max(_MIN_EFFECTIVE_GE_S,
                       _raw_deficit if _raw_deficit > 0.0 else _MIN_EFFECTIVE_GE_S),
                   _bp_ub)
        # BXT_SOLVER='deficit' skips the (degenerate) objective optimiser here too
        # -- the deficit `_mag` above is the bus's clearance need.
        _use_solver = str(globals().get('BXT_SOLVER', 'harmony')).lower() != 'deficit'
        if _use_solver and hasattr(self, 'solve_bus_phase_green') and _bp_ub > _MIN_EFFECTIVE_GE_S:
            try:
                _opt_bp, _, _ = self.solve_bus_phase_green(
                    min(_MIN_EFFECTIVE_GE_S, _bp_ub), _bp_ub, time)
                if _opt_bp >= _MIN_EFFECTIVE_GE_S:
                    _mag = float(_opt_bp)
            except Exception:
                pass
        # ETA-reachability gate: an insertion/advance can only catch a bus that
        # arrives within ~one cycle; firing it 100-230 s early (corridor pre-arm)
        # just disrupts the cross phase without serving the bus.
        _ins_reach = float(_cycle_s) + 5.0
        _eta_ok = float(bus_eta_s) <= _ins_reach
        # Q-argmax chose to act; commit at the solved magnitude.  No benefit>cost
        # veto (see GE branch) -- the closed-loop reward governs whether this
        # family is worth choosing in this state.
        if _eta_ok and _mag >= _MIN_EFFECTIVE_GE_S:
            _chosen_aparam = float(_mag)
        else:
            _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif _chosen_atype in _solved_param:
        _chosen_aparam = float(_solved_param[_chosen_atype])

    _log_func(self, f"[BXT] inter={self.id} t={time:.1f} bus={veh_id} "
                    f"state={_bxt_state} n0={n0_bus:.1f}veh side_ratio={_side_ratio:.3f} "
                    f"eff_delay={eff_delay:.1f}s o_occ={_o_occ:.2f} o_d={_o_d:.0f}vhs "
                    f"upflow={[round(float(v),0) for v in self.UpFlowList[0].tolist()] if hasattr(self,'UpFlowList') and len(self.UpFlowList)>0 else 'n/a'} "
                    f"explore={_use_explore} chosen={_chosen_atype}_{_chosen_aparam:.0f}s")


    # ── Saturation avoidance (same guard as ZIG / MP_ECTM) ───────────────────
    # eff_delay already bound in the state-bin block above.
    if eff_delay < float(SELFORG_MIN_BUS_DELAY_S):
        _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif _chosen_atype in _solved_param and _chosen_aparam < _MIN_EFFECTIVE_GE_S:
        # Solved deficit is ~0: the bus already clears without help.  This is
        # the case the fixed grid mispriced -- it granted 15 s to a bus facing
        # no delay.  Grant nothing and pay no cross-traffic cost.
        _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif _side_ratio > float(BXT_GE_BALANCE_FACTOR if _chosen_atype == 'GE'
                             else BXT_BALANCE_FACTOR):
        # 2026-08-24: the CTM-override relaxation here was REVERTED — it did not
        # help (INS never fired; GE gridlocked) because the CTM over-values GE.
        _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
    elif _chosen_atype == 'INS' and _chosen_aparam > float(BXT_MAX_INS_S):
        # Clamp the disruptive insertion instead of committing the full
        # 15-20 s candidate (mode-commits-own-action bypasses BP_upper_bound).
        _chosen_aparam = float(BXT_MAX_INS_S)

    # ── Baked-in traditional-TSP rule layer ───────────────────────────────────
    # Domain rules from classic transit-signal-priority practice, applied as HARD
    # constraints AFTER the learned policy + harmony solver have chosen a tactic
    # and magnitude.  Each rule can only make the decision MORE conservative
    # (force NO_ACTION or shrink the grant), never invent an action, so the RL /
    # CTM economics still drive when TSP fires.  Each is independently toggleable;
    # rules that merely add safety are on by default, broadly-suppressive ones are
    # present but off until their data source is confirmed on this network.
    if _chosen_atype != 'NO_ACTION':
        _rule_veto = None

        # (1) Conditional priority: grant only to buses that are behind schedule.
        # Uses the per-bus accumulated lateness (Z3) threaded in as sigma_in.
        # OFF by default (threshold 0) -- enable once lateness tracking is
        # confirmed populated on this network, else it suppresses every bus.
        _cp_min_late = float(globals().get('CONDITIONAL_PRIORITY_MIN_LATENESS_S', 0.0) or 0.0)
        if _cp_min_late > 0.0 and float(sigma_in) < _cp_min_late:
            _rule_veto = f"conditional_priority(lateness={float(sigma_in):.0f}s<{_cp_min_late:.0f}s)"

        # (2) Min-green / pedestrian clearance: never truncate the CURRENT phase
        # below its minimum green.  Applies to tactics that shorten the running
        # cross phase to advance the bus (PT / wrong-phase GR / wrong-phase ER):
        # cap the amount taken so >= MinGreen of the cross phase survives.
        if _rule_veto is None and bool(globals().get('RULE_MIN_GREEN', True)):
            _shortens = (_chosen_atype == 'PHASE_ROTATION'
                         or (_chosen_atype == 'GREEN_REALLOC' and _wrong_phase)
                         or (_chosen_atype == 'EARLY_RED' and _wrong_phase))
            if _shortens:
                _min_green = float(getattr(self, 'MinGreen',
                                   globals().get('MIN_GREEN_S', 5.0)) or 5.0)
                _max_take = max(0.0, float(remaining_red_s) - _min_green)
                if _chosen_aparam > _max_take:
                    if _max_take >= _MIN_EFFECTIVE_GE_S:
                        _chosen_aparam = float(_max_take)   # shrink to protect min green
                    else:
                        _rule_veto = f"min_green(protect {_min_green:.0f}s cross phase)"

        # (3) Cooldown: one grant per bus per junction within a headway window.
        # (Natural-green skip is already enforced by the deficit->NO_ACTION logic
        # above; this adds the anti-double-serve headway.)
        if _rule_veto is None and bool(globals().get('RULE_TSP_COOLDOWN', True)):
            _cd_s = float(globals().get('TSP_PER_BUS_COOLDOWN_S', 60.0) or 0.0)
            if _cd_s > 0.0 and veh_id and int(veh_id) > 0:
                _cd_map = getattr(self, '_bxt_last_served', None)
                if _cd_map is None:
                    _cd_map = {}; self._bxt_last_served = _cd_map
                _last_t = float(_cd_map.get(int(veh_id), -1e9))
                if (float(time) - _last_t) < _cd_s:
                    _rule_veto = f"cooldown(served {float(time)-_last_t:.0f}s<{_cd_s:.0f}s ago)"

        # (4) Occupancy / person-delay warrant: only act when the person-delay the
        # grant would save (bus occupancy x bus delay) clears a threshold, so a
        # near-empty bus never disrupts heavy cross traffic.
        if _rule_veto is None and bool(globals().get('RULE_PERSON_DELAY_WARRANT', True)):
            _pd_min = float(globals().get('PERSON_DELAY_WARRANT_MIN_PAXS', 0.0) or 0.0)
            _pd = max(0.0, float(no_act_delay)) * float(_bus_occ)
            if _pd_min > 0.0 and _pd < _pd_min:
                _rule_veto = f"person_delay({_pd:.0f}pax·s<{_pd_min:.0f})"

        if _rule_veto is not None:
            _log_func(self, f"[TSP RULE] inter={self.id} t={time:.1f} bus={veh_id} "
                            f"vetoed {_chosen_atype} -> NO_ACTION ({_rule_veto})")
            try:
                self.stats.record_tsp_skip(self.id, 'tsp_rule_veto')
            except Exception:
                pass
            _chosen_atype, _chosen_aparam, _chosen_idx = 'NO_ACTION', 0.0, 0
        elif veh_id and int(veh_id) > 0 and _chosen_atype != 'NO_ACTION':
            # Record the serve time for the per-bus cooldown rule.
            _cd_map = getattr(self, '_bxt_last_served', None)
            if _cd_map is None:
                _cd_map = {}; self._bxt_last_served = _cd_map
            _cd_map[int(veh_id)] = float(time)

    # ── Rows for the shared Pareto layer / reward CSV ─────────────────────────
    r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
        self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
    rows = [('NO_ACTION', 0.0, r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na)]

    if _chosen_atype != 'NO_ACTION' and _chosen_aparam > 0.0:
        # Metadata (sigma/t_poz) from the shared evaluator, but the objective
        # vector comes from BXT's own CTM red-delay model so the Pareto layer
        # sees BXT-specific economics (same reasoning as dctsp_mp_ectm).
        _, so_act, tp_act, _, _, nsd_act, std_act = _dctsp_eval_action(
            self, _chosen_atype, _chosen_aparam, sigma_in, no_act_delay, bus_eta_s,
            wrong_phase=_wrong_phase, remaining_red_s=remaining_red_s)
        _, _d_bus_na_c, _d_side_na_c = _bxt_evals[0]
        _, _d_bus_c, _d_side_c = _bxt_evals[_chosen_idx]
        # v7: bus-equity weighting + green-keep reinforcement credit.
        # bps_ctm was exactly 0 whenever the bus is predicted to arrive on
        # green, which let the decider cost veto kill every action (measured
        # 1458 no-actions vs 5 extensions/run).  Weight the bus pax-s by
        # BUS_PAX_WEIGHT and, when the bus is inside the reachable window but
        # no red-wait is predicted anyway, credit a small protected-green
        # floor (GREEN_KEEP_CREDIT_S x occ x weight) so near-free reinforcement
        # actions can fire; expensive ones still lose the veto economics.
        _eqw_r = max(0.0, float(globals().get('BUS_PAX_WEIGHT',
                                              BUS_PAX_WEIGHT) or 1.0))
        _keep_s = max(0.0, float(globals().get('GREEN_KEEP_CREDIT_S',
                                               GREEN_KEEP_CREDIT_S) or 0.0))
        bps_ctm = max(0.0, _d_bus_na_c - _d_bus_c)
        _keep_credit = 0.0
        if bps_ctm < 1.0 and _keep_s > 0.0:
            try:
                _gl_v = float(_green_left)
            except Exception:
                _gl_v = 0.0
            try:
                _ub_v = float(_ge_ub)
            except Exception:
                _ub_v = 0.0
            try:
                _cyc_v = float(_cycle_s)
            except Exception:
                _cyc_v = 135.0
            if current_phase == self.BusPhase:
                # GE protects the running bus phase up to green_left + ub.
                _reach_ok = float(bus_eta_s) <= (_gl_v + _ub_v + 5.0)
            else:
                # INS/advance can bring the bus green forward within a cycle.
                _reach_ok = float(bus_eta_s) <= (_cyc_v + 5.0)
            if _reach_ok:
                _keep_credit = _keep_s * _bus_occ * _eqw_r
        bps_ctm = bps_ctm * _eqw_r + _keep_credit
        # ── Multi-bus benefit: sum over ALL oncoming buses the action serves ──
        # The single detected bus underweights a PLATOON -- an action that also
        # serves a following bus within the (extended) green window is worth more,
        # and should clear the cost veto where one bus wouldn't. Scale the benefit
        # by the total occupancy of oncoming buses inside the reach window (>=1x;
        # only >1 when a second bus is genuinely coming). Capped by
        # MULTIBUS_MAX_FACTOR to avoid runaway. Uses the continuously-corrected
        # trackers (§50) so "oncoming" is accurate.
        if bps_ctm > 0.0:
            try:
                _cc = getattr(self, '_corridor_coord', None)
                if _cc is not None:
                    _reach_win = ((float(_green_left) + float(_ge_ub) + 5.0)
                                  if not _wrong_phase else (float(_cycle_s) + 5.0))
                    _onc = _cc.oncoming_buses(self.id, time, max_eta_s=_reach_win)
                    # 2026-08-24 (#3): default factor rolled back 3.0 -> 1.0
                    # (disabled). The ×3 platoon amplification over-bought bus
                    # time and drove the OC/GR cascade (champion search car +69%).
                    # Set MULTIBUS_MAX_FACTOR>1 to re-enable once GR/OC are gated.
                    _mb_cap = float(globals().get('MULTIBUS_MAX_FACTOR', 1.0) or 1.0)
                    if len(_onc) > 1 and _mb_cap > 1.0:
                        _tot_occ = sum(float(_o[2]) for _o in _onc)
                        _mb = min(max(1.0, _tot_occ / max(float(_bus_occ), 1.0)), _mb_cap)
                        bps_ctm *= _mb
            except Exception:
                pass
        cpc_ctm = max(0.0, _d_side_c - _d_side_na_c)
        # Zero-cost fallback (empty shockwave arrays → CTM side terms are 0).
        if cpc_ctm < 1.0 and bps_ctm > 0.0:
            try:
                _bxt_red = float(_chosen_aparam) + float(INS_INTERGREEN_S)
                _sd, _ = self._compute_side_delay_penalty(_bxt_red, _suppress_log=True)
                cpc_ctm += max(0.0, float(_sd))
            except Exception:
                pass
        r_act = bps_ctm - cpc_ctm
        rows.append((action_label(_chosen_atype, _chosen_aparam), _chosen_aparam,
                     r_act, so_act, tp_act, bps_ctm, cpc_ctm, nsd_act, std_act))
        best_r, best_so, best_tp = r_act, so_act, tp_act
        best_r_delta = r_act - r_na
    else:
        _chosen_atype, _chosen_aparam = 'NO_ACTION', 0.0
        best_r, best_so, best_tp, best_r_delta = r_na, so_na, tp_na, 0.0

    # ── CLOSED-LOOP LEARNING: log this decision + a delay snapshot so the
    # realized outcome (measured from the sim ~1.5 cycles later) can be credited
    # back via _bxt_update_q.  Keyed by (junction, bus) -- one bus visits several
    # junctions and each is a separate decision.  Without this the Q-table stays
    # frozen at its analytic seed and the model can never learn whether its cost
    # prices are wrong.  See _bxt_apply_pending_updates.
    if globals().get('BXT_LEARN', True) and _phase != 'eval':
        try:
            _d0b, _d0c = _bxt_delay_snapshot(self)
            _cyc = float(self._signal_cycle_s()) if hasattr(self, '_signal_cycle_s')                 else float(getattr(self, 'cycle_len_s', 135.0) or 135.0)
            _poz_action_log[(int(self.id), int(veh_id))] = {
                'state': _bxt_state, 'action_idx': int(_chosen_idx),
                'atype': _chosen_atype, 'param': float(_chosen_aparam),
                't': float(time), 'delay_bus0': _d0b, 'delay_car0': _d0c,
                'due_t': float(time) + 1.5 * _cyc,
                # For the counterfactual (advantage) reward: the bus delay this
                # action was meant to AVOID, per-decision, and the occupancy.
                'no_act_delay': max(0.0, float(no_act_delay)),
                'bus_occ': float(_bus_occ),
                # v7 corridor reward sharing: neighbors' delay at decision time
                # so the update can credit their signed delta over the window.
                'nbr_delay0': _bxt_neighbor_snapshot(self),
            }
        except Exception:
            pass

    return (_chosen_atype, _chosen_aparam, best_r, best_r_delta,
            best_so, best_tp, rows)


# ── Mode: BARGAIN_SPM — Nash bargaining game candidate generation ─────────────
# Ported (simplified) from kg/intersection_controller_lean.py: ETA detection
# level sets the bus bargaining weight; a stochastic-shockwave risk multiplier
# (cross-flow CV + saturation ratio) and cascade multiplier scale car cost; the
# main-approach car saving is credited symmetrically.

def dctsp_bargain(self, time, timeSta, acycle, bus_eta_s, veh_id, current_phase,
                  no_act_delay, sigma_in, remaining_red_s=0.0):
    _wrong_phase = (current_phase != self.BusPhase)
    _bus_occ = float(getattr(self, 'BusOcc', 40.0))

    # Bus bargaining weight from ETA detection level
    if bus_eta_s < float(BG_DET_LVL_IMM_S):
        _w_bus = float(BG_BUS_W_IMM)
    elif bus_eta_s < float(BG_DET_LVL_NEAR_S):
        _w_bus = float(BG_BUS_W_NEAR)
    elif bus_eta_s < float(BG_DET_LVL_FAR_S):
        _w_bus = float(BG_BUS_W_FAR)
    else:
        _w_bus = float(BG_BUS_W_VFAR)

    # SPM risk multiplier: recent cross-flow variability + saturation ratio
    _risk_mult = 1.0
    try:
        _up = np.asarray(getattr(self, 'UpFlowList', []), dtype=float)
        if _up.ndim >= 2 and _up.shape[0] > 1 and _up.shape[1] > 0:
            _n_recent = min(5, _up.shape[1])
            _cross = _up[1:, -_n_recent:].ravel()
        else:
            _cross = np.asarray([], dtype=float)
        _cross = _cross[_cross > 0.0]
        if _cross.size > 0:
            _mean = float(np.mean(_cross))
            _cv = float(np.std(_cross)) / max(_mean, 1e-6)
            _sat_ratio = _mean / max(float(getattr(self, 'SaturationFlow', 1800.0)), 1.0)
            _unc = min(1.0, 0.5 * _cv + 0.5 * _sat_ratio)
            _risk_mult = 1.0 + float(BG_SPM_RISK_WEIGHT) * _unc
    except Exception:
        _risk_mult = 1.0

    # ── WOBJ objective targeting (Z1 delay / Z2 progression / Z3 headway) ──
    _wobj_alpha = float(globals().get('WOBJ_ALPHA', 1.0))
    _wobj_beta  = float(globals().get('WOBJ_BETA', 0.0))
    _wobj_gamma = float(globals().get('WOBJ_GAMMA', 0.0))
    _sigma_s = max(float(sigma_in), 0.0)
    _lateness_factor = min(_sigma_s / 30.0, 3.0)
    _eff_bus_w  = _wobj_alpha + _wobj_gamma * _lateness_factor
    _eff_cross_w = 1.0 + _wobj_beta

    # NO_ACTION baseline (inertia bonus keeps marginal actions from firing)
    r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
        self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
    r_na_bg = r_na + float(BG_NO_ACTION_BONUS_S)
    rows = [('NO_ACTION', 0.0, r_na_bg, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na)]

    _cands = []
    for (_at, _ap) in DCTSP_RL_ACTION_SPACE:
        if _at == 'NO_ACTION':
            continue
        # GE only helps when the bus phase is running; INS/ER only when not.
        # GREEN_REALLOC is meaningful in both (extend-as-GE vs advance bus green).
        if _at == 'GE' and _wrong_phase:
            continue
        if _at in ('INS', 'EARLY_RED') and not _wrong_phase:
            continue
        _cands.append((_at, _ap))

    best_lbl, best_param, best_r = 'NO_ACTION', 0.0, r_na_bg
    best_so, best_tp = so_na, tp_na
    best_atype = 'NO_ACTION'
    for (_at, _ap) in _cands:
        r, so, tp, bps, cpc, nsd, std = _dctsp_eval_action(
            self, _at, _ap, sigma_in, no_act_delay, bus_eta_s,
            wrong_phase=_wrong_phase, remaining_red_s=remaining_red_s)
        # Main-approach car saving (phases=[0]); zero for EARLY_RED on the bus
        # phase — cutting the bus green gives the main approach nothing.
        if _at == 'EARLY_RED' and not _wrong_phase:
            _main_sav = 0.0
        else:
            try:
                _main_sav = float(self._dctsp_cross_traffic_delay_s(
                    max(0.0, float(_ap)), phases=[0]))
            except Exception:
                _main_sav = 0.0
        r_bg = (_eff_bus_w * _w_bus * bps
                - _eff_cross_w * _risk_mult * float(BG_CASCADE_MULT) * cpc
                + _main_sav)
        _lbl = action_label(_at, _ap)
        rows.append((_lbl, _ap, r_bg, so, tp, bps, cpc, nsd, std))
        if r_bg > best_r and bps > 0.0:
            best_lbl, best_param, best_r = _lbl, _ap, r_bg
            best_so, best_tp, best_atype = so, tp, _at

    # Gates: minimum bus delay and minimum bargaining gain
    eff_delay = max(0.0, float(no_act_delay) - float(ZIG_PHASE_OVERLAP_S))
    _min_gain_pax_s = float(BG_MIN_GAIN_S) * max(_bus_occ, 1.0)
    if (eff_delay < float(BG_MIN_BUS_DELAY_S)
            or (best_r - r_na_bg) < _min_gain_pax_s):
        best_atype, best_lbl, best_param = 'NO_ACTION', 'NO_ACTION', 0.0
        best_r, best_so, best_tp = r_na_bg, so_na, tp_na

    _log_func(self, f"[BARGAIN] inter={self.id} t={time:.1f} bus={veh_id} "
                    f"w_bus={_w_bus:.2f} risk={_risk_mult:.2f} "
                    f"wobj=(a={_wobj_alpha:.2f} b={_wobj_beta:.2f} g={_wobj_gamma:.2f}) "
                    f"eff_bw={_eff_bus_w:.2f} eff_cw={_eff_cross_w:.2f} "
                    f"chosen={best_lbl} r={best_r:.1f}")

    return (best_atype, best_param, best_r, best_r - r_na_bg,
            best_so, best_tp, rows)


# ── Mode: CELLQLEARN_DP — CellQ-Learn with Dynamic Programming ───────────────
# V2X-coordinated TSP: queue-length prediction via CTM + DP backward recursion
# to find the optimal TSP action sequence along the transit route.
# Reference: Huang H.-K. & Hsu Y.-T. (2025), Transportation Letters.

def dctsp_cellqlearn_dp(self, time, timeSta, acycle, bus_eta_s, veh_id,
                         current_phase, no_act_delay, sigma_in, remaining_red_s=0.0):
    """Coordinated TSP via dynamic programming with CTM queue prediction.

    DP backward recursion from downstream intersections to the current one,
    computing the Pareto-optimal sequence of TSP actions that minimizes total
    passenger delay (bus + general traffic) along the corridor.

    Returns (best_type, best_param, best_r, best_r_delta, best_sigma_out,
    best_t_poz, rows) — same contract as dctsp_bxt / dctsp_zig.
    """
    dt          = float(CELLQLEARN_DP_DT_S)
    q_sat_vps   = float(getattr(self, 'SaturationFlow', 1800.0)) / 3600.0
    k_jam       = float(getattr(self, 'JamDensity', 200.0))
    _bus_occ    = float(getattr(self, 'BusOcc', 40.0))
    _car_occ    = float(CELLQLEARN_DP_CAR_OCC)
    _cycle_s = float(self._signal_cycle_s()) if hasattr(self, '_signal_cycle_s') else float(self.config.get('CycleTime', 135.0) or 135.0)
    _bus_g_base = float(getattr(self, 'BusPhaseDuration', 20.0))
    _wrong_phase = (int(current_phase) != int(self.BusPhase))
    _cap_veh    = k_jam * 0.15

    # ── Estimate initial bus-approach queue (same LWR back-shockwave as BXT) ──
    try:
        upf = np.asarray(getattr(self, 'UpFlowList', np.zeros((1, 1))), dtype=float)
        rdt = np.asarray(getattr(self, 'RedDurationList', np.zeros((1, 1))), dtype=float)
        upf_bus = upf[0].ravel() if upf.ndim >= 2 and upf.shape[0] > 0 else np.zeros(1)
        rdt_bus = rdt[0].ravel() if rdt.ndim >= 2 and rdt.shape[0] > 0 else np.zeros(1)
        pos_flow = upf_bus[upf_bus > 0.0]
        pos_red = rdt_bus[(rdt_bus > 0.0) & (rdt_bus < 2.0 * _cycle_s)]
        q_arr_bus_vps = (float(np.mean(pos_flow)) / 3600.0
                         if pos_flow.size > 0 else 300.0 / 3600.0)
        t_red_past = (float(np.max(pos_red)) if pos_red.size > 0 else 60.0)
        k_arr_b = q_arr_bus_vps * k_jam / max(q_sat_vps, 1e-9)
        w_back_b = q_arr_bus_vps / max(k_jam - k_arr_b, 1.0)
        n0_bus = max(0.0, w_back_b * t_red_past * k_jam)
    except Exception:
        q_arr_bus_vps = 300.0 / 3600.0
        n0_bus = 5.0
        t_red_past = 60.0

    # ── Passenger weighting for the approach cell ────────────────────────────
    # `n0_bus` is the LWR/shockwave estimate of the WHOLE approach queue in
    # vehicles and `q_arr_bus_vps` is the WHOLE approach flow -- neither is
    # bus-only -- so passing `_bus_occ` (40 pax/veh) into _ctm_delay_pax priced
    # every queued car as a 40-passenger bus (~16x overstatement).  Same defect
    # fixed in dctsp_bxt, where it drove constant max-length extensions and
    # gridlocked kg seeds 400/500.  Weight the cell by what it holds: the
    # subject bus at BusOcc, the remaining queue at CarOcc.
    _n_cell = max(float(n0_bus), 1.0)
    _cell_occ = ((min(1.0, _n_cell) * _bus_occ
                  + max(0.0, _n_cell - 1.0) * float(_car_occ)) / _n_cell)

    def _ctm_delay_pax(n0, q_arr, q_sat, t_wait_red, g_dur, occ):
        delay = 0.0
        n = max(0.0, float(n0))
        for _ in range(max(0, int(round(float(t_wait_red) / dt)))):
            n = min(n + q_arr * dt, _cap_veh)
            delay += n * dt
        for _ in range(max(0, int(round(float(g_dur) / dt)))):
            q_out = min(q_sat, n / max(dt, 1e-9))
            n = max(0.0, n + q_arr * dt - q_out * dt)
            delay += n * dt
        return delay * float(occ)

    def _eval_stage_action(atype, aparam_s):
        """Evaluate one TSP action at a single intersection stage.
        Returns (bus_delay_paxs, side_delay_paxs, effective_red_saved)."""
        a_s = float(aparam_s)
        if atype == 'NO_ACTION':
            if _wrong_phase:
                t_wait = float(remaining_red_s); g_bus = _bus_g_base
            else:
                t_wait = 0.0; g_bus = float(remaining_red_s)
            d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                   t_wait, g_bus, _cell_occ)
            d_side = float(self._dctsp_cross_traffic_delay_s(0.0))
            return d_bus, d_side, 0.0
        if atype == 'GE':
            if not _wrong_phase:
                d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       0.0, float(remaining_red_s) + a_s, _cell_occ)
                d_side = float(self._dctsp_cross_traffic_delay_s(a_s))
            else:
                d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       float(remaining_red_s) + a_s, _bus_g_base, _cell_occ)
                d_side = float(self._dctsp_cross_traffic_delay_s(0.0))
            return d_bus, d_side, a_s
        if atype in ('INS', 'INS_POST'):
            t_wait = float(remaining_red_s) + float(INS_INTERGREEN_S)
            # ETA gate (mirrors _dctsp_eval_action INS rule): a bus still
            # `bus_eta_s` away cannot catch a short insertion — otherwise the
            # CTM queue model credits phantom savings from a few seconds of
            # green (INS_PRETERM_3 claimed up to ~62 000 pax·s).
            if float(bus_eta_s) > (a_s + float(INS_INTERGREEN_S)):
                d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       t_wait, _bus_g_base, _cell_occ)
            else:
                d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       t_wait, a_s, _cell_occ)
            d_side = float(self._dctsp_cross_traffic_delay_s(t_wait + a_s))
            return d_bus, d_side, a_s

        # --- V2X-coordinated DP-specific actions: green reallocation, early red ---
        if atype == 'GREEN_REALLOC':
            if not _wrong_phase:
                d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       0.0, float(remaining_red_s) + a_s, _cell_occ)
            else:
                g_advance = max(0.0, a_s - float(remaining_red_s))
                t_wait = max(0.0, float(remaining_red_s) - a_s)
                d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                       t_wait, _bus_g_base + g_advance, _cell_occ)
            d_side = float(self._dctsp_cross_traffic_delay_s(a_s))
            return d_bus, d_side, a_s
        if atype == 'EARLY_RED':
            saved_red = min(float(remaining_red_s), a_s)
            d_bus = _ctm_delay_pax(n0_bus, q_arr_bus_vps, q_sat_vps,
                                   saved_red, _bus_g_base + a_s * 0.5, _cell_occ)
            d_side = float(self._dctsp_cross_traffic_delay_s(a_s))
            return d_bus, d_side, a_s

        return 1e9, 0.0, 0.0

    # ── DP Action space ─────────────────────────────────────────────────────
    _dp_actions = [
        ('NO_ACTION', 0.0),
        ('GE', 5.0), ('GE', 10.0), ('GE', 15.0),
('INS', 10.0), ('INS', 15.0), ('INS', 20.0), ('INS', 25.0),
        ('GREEN_REALLOC', 5.0), ('GREEN_REALLOC', 10.0), ('GREEN_REALLOC', 15.0),
        ('EARLY_RED', 10.0), ('EARLY_RED', 20.0),
    ]
    _dp_action_indices = list(range(len(_dp_actions)))

    _horizon_s = float(CELLQLEARN_DP_HORIZON_S)
    _coord_w   = float(CELLQLEARN_DP_COORD_WEIGHT)
    _stage_s   = float(CELLQLEARN_DP_STAGE_S)
    _dp_stages = max(1, int(_horizon_s / _stage_s))

    # Real accumulated side-red at this junction: longest red held across all
    # phases becomes the cross-approach queue elapsed (Q_0 > 0), so the DP
    # side penalty is grounded in actual queue state instead of a 0.3 fudge.
    try:
        _rdt_all = np.asarray(getattr(self, 'RedDurationList', np.zeros((1, 1))), dtype=float)
        _side_red_elapsed = float(np.max(_rdt_all)) if _rdt_all.size else float(t_red_past)
    except Exception:
        _side_red_elapsed = float(t_red_past)
    _side_red_elapsed = max(0.0, min(_side_red_elapsed, 2.0 * _cycle_s))

    def _dp_proj_side_delay(_ap):
        """Real side-queue pax·s imposed by action red `_ap`: uses the live
        SideUpFlowList/SideUpDenList shockwave model when available (grounded
        in actual accumulated side queue), else the analytic cross model.
        Scaled by CROSS_TRAFFIC_COST_MULTIPLIER so it competes with the
        primary CTM terms (the analytic path already applies that factor)."""
        _cmult = float(CROSS_TRAFFIC_COST_MULTIPLIER or 2.0)
        try:
            _fn = getattr(self, '_compute_side_delay_penalty', None)
            if _fn is not None:
                _v = _fn(max(0.0, float(_ap)), _suppress_log=True)
                if _v and float(_v[0]) > 0.0:
                    return float(_v[0]) * _cmult
        except Exception:
            pass
        try:
            return float(self._dctsp_cross_traffic_delay_s(
                max(0.0, float(_ap)), queue_elapsed_s=_side_red_elapsed))
        except Exception:
            return 0.0

    # For now, the DP stages are virtual "look-ahead windows" along the
    # bus trajectory. Each stage corresponds to an arrival at a downstream
    # intersection or a future cycle boundary.
    # ── DP backward recursion ──────────────────────────────────────────────
    # DP[i][q_state] = min cumulative delay from stage i onward
    # i=0 is "now" (first stage), i=dp_stages-1 is the furthest horizon.
    # We discretise the "remaining queue" state as a coarse bin.
    _n_stages = min(_dp_stages, 6)

    # ── Per-action evaluation at the current stage ─────────────────────────
    _na_dbus, _na_dside, _na_saved = _eval_stage_action('NO_ACTION', 0.0)
    _baseline_total = _na_dbus + _na_dside

    _cand_rows = []
    for _ai, (_at, _ap) in enumerate(_dp_actions):
        if _at == 'NO_ACTION':
            _cand_rows.append((_at, _ap, _na_dbus + _na_dside, _na_dbus, _na_dside, 0.0, 0.0))
            continue
        if _at == 'GE' and _wrong_phase:
            continue
        if _at in ('INS', 'INS_POST', 'EARLY_RED') and not _wrong_phase:
            continue
        _dbus, _dside, _saved = _eval_stage_action(_at, _ap)
        if _dbus >= 1e8:
            continue

        # ── DP look-ahead: estimate downstream delay impact ─────────────────
        # Local CTM self-projection (future queue at THIS junction), then ADD
        # the REAL downstream-junction projection (Z2, corridor-aware): the
        # bus time shift here moves its arrival at the NEXT managed junction;
        # project the red-wait there from the live downstream phase schedule.
        _dp_coord_penalty = 0.0
        _dp_proj_dside = _dp_proj_side_delay(_ap)
        _remaining_horizon = max(0.0, _horizon_s - float(_ap))
        _dp_extra_stages = int(_remaining_horizon / _stage_s)
        for _si in range(min(_dp_extra_stages, 3)):
            _stage_offset = (_si + 1) * _stage_s
            _dp_proj_n0 = max(0.0, n0_bus - _saved * 0.7
                              + q_arr_bus_vps * _stage_offset)
            _dp_proj_dbus = _ctm_delay_pax(
                _dp_proj_n0, q_arr_bus_vps, q_sat_vps,
                0.0, _bus_g_base, _cell_occ)
            _dp_coord_penalty += (_dp_proj_dbus + _dp_proj_dside) * (_coord_w ** (_si + 1))
        try:
            _coord = getattr(self, '_corridor_coord', None)
            if _coord is not None:
                # The bus can only be pulled forward by as much as it is
                # actually delayed without action — cap the downstream shift.
                _shift_sec = min(float(_saved), max(0.0, float(no_act_delay)))
                if _shift_sec > 0.0:
                    _dp_coord_penalty += float(_coord.project_downstream_delay_paxs(
                        int(self.id), int(veh_id), float(time), float(timeSta),
                        float(bus_eta_s), _shift_sec, _bus_occ))
        except Exception:
            pass

        _total = _dbus + _dside + _dp_coord_penalty
        _cand_rows.append((_at, _ap, _total, _dbus, _dside, _saved, _dp_coord_penalty))

    # ── Saturation avoidance guard ──────────────────────────────────────────
    try:
        _o_d = (_safe_float(self._safe_array_sum(getattr(self, 'OtherDelay', [0])))
                + _safe_float(self._safe_array_sum(
                    getattr(self, 'SideDelayBaseline', [0]))))
        _eff_delay = max(0.0, float(no_act_delay) - float(ZIG_PHASE_OVERLAP_S))
        _bus_p = _eff_delay * _bus_occ
        _side_p = max(0.0, _o_d) * _car_occ
        _side_ratio = _side_p / max(_bus_p, 1.0)
    except Exception:
        _side_ratio = 0.0

    _eff_delay_gate = max(0.0, float(no_act_delay) - float(ZIG_PHASE_OVERLAP_S))
    _low_bus_delay = _eff_delay_gate < float(SELFORG_MIN_BUS_DELAY_S)

    # ── Select best action via minimum total delay (DP optimal) ─────────────
    _best_atype, _best_aparam, _best_total = 'NO_ACTION', 0.0, _baseline_total
    _best_dbus, _best_dside, _best_dp_pen = _na_dbus, _na_dside, 0.0
    for (_at, _ap, _tot, _dbus, _dside, _saved, _pen) in _cand_rows:
        if _at == 'NO_ACTION':
            continue
        if _low_bus_delay:
            continue
        # GE is a small same-phase intervention: tolerate a higher cross-street
        # cost ratio for extensions than for (disruptive) insertions.
        _gate_factor = (float(CELLQLEARN_DP_GE_BALANCE_FACTOR) if _at == 'GE'
                        else float(CELLQLEARN_DP_BALANCE_FACTOR))
        if _side_ratio > _gate_factor:
            continue
        if _tot < _best_total:
            _best_total = _tot
            _best_atype, _best_aparam = _at, _ap
            _best_dbus, _best_dside = _dbus, _dside
            _best_dp_pen = _pen

    if _low_bus_delay:
        _best_atype, _best_aparam = 'NO_ACTION', 0.0
        _best_dbus, _best_dside = _na_dbus, _na_dside
        _best_total = _baseline_total

    _log_func(self, f"[CELLQLEARN_DP] inter={self.id} t={time:.1f} bus={veh_id} "
                    f"n0={n0_bus:.1f} side_ratio={_side_ratio:.2f} "
                    f"dp_stages={_n_stages} "
                    f"low_bus_delay={_low_bus_delay} "
                    f"chosen={_best_atype}_{_best_aparam:.0f} "
                    f"total_delay={_best_total:.1f}paxs")

    # ── Build rows for the shared Pareto layer / reward CSV ─────────────────
    # Emit EVERY DP-evaluated candidate that survives the balance gates (not
    # just the argmin), so the Pareto layer sees the mode's full model
    # trade-off across the action space (GE / INS / GREEN_REALLOC / EARLY_RED)
    # instead of collapsing onto the standard pool.  Each row carries the DP
    # model's own CTM-computed bus benefit and cross-phase cost, with the DP
    # coordination look-ahead penalty folded into the cross-phase cost.
    r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na = _dctsp_eval_action(
        self, 'NO_ACTION', 0.0, sigma_in, no_act_delay, bus_eta_s)
    rows = [('NO_ACTION', 0.0, r_na, so_na, tp_na, bps_na, cpc_na, nsd_na, std_na)]

    best_r = r_na; best_so = so_na; best_tp = tp_na; best_r_delta = 0.0
    if not _low_bus_delay:
        for (_at, _ap, _tot, _dbus, _dside, _saved, _pen) in _cand_rows:
            if _at == 'NO_ACTION':
                continue
            # Same balance-gate filtering the argmin loop applied: tolerate a
            # higher cross-street cost ratio for GE than for disruptive actions.
            _gate_factor = (float(CELLQLEARN_DP_GE_BALANCE_FACTOR) if _at == 'GE'
                            else float(CELLQLEARN_DP_BALANCE_FACTOR))
            if _side_ratio > _gate_factor:
                continue
            try:
                _, so_act, tp_act, bps_gated, _, nsd_act, std_act = _dctsp_eval_action(
                    self, _at, _ap, sigma_in, no_act_delay, bus_eta_s,
                    wrong_phase=_wrong_phase, remaining_red_s=remaining_red_s)
            except Exception:
                so_act, tp_act, bps_gated, nsd_act, std_act = so_na, tp_na, 0.0, nsd_na, std_na
            # Use the ETA-gated bus benefit from _dctsp_eval_action as the
            # authoritative value (it already applies the INS ETA gate and the
            # no_act_delay cap — see dctsp_mp_ectm_dp for the phantom-savings
            # rationale), bounded by the DP's raw CTM delta.
            bps_ctm = min(max(0.0, float(bps_gated)),
                          max(0.0, _na_dbus - _dbus))
            cpc_ctm = max(0.0, _dside - _na_dside)
            if cpc_ctm < 1.0 and bps_ctm > 0.0:
                try:
                    _dp_red = float(_ap) + float(INS_INTERGREEN_S)
                    _sd, _ = self._compute_side_delay_penalty(_dp_red, _suppress_log=True)
                    cpc_ctm += max(0.0, float(_sd))
                except Exception:
                    pass
            # Fold the DP coordination look-ahead penalty into the emitted row's
            # cross-phase cost so the final max-reward / Pareto selection actually
            # sees the downstream impact (previously only shaped the argmin).
            cpc_ctm += float(_pen)
            r_act = bps_ctm - cpc_ctm
            rows.append((action_label(_at, _ap), _ap,
                         r_act, so_act, tp_act, bps_ctm, cpc_ctm, nsd_act, std_act))
            if _at == _best_atype and abs(_ap - _best_aparam) < 1e-6:
                best_r = r_act; best_so = so_act; best_tp = tp_act
                best_r_delta = r_act - r_na

    return (_best_atype, _best_aparam, best_r, best_r_delta,
            best_so, best_tp, rows)


# ── Constants that must be propagated from run_config.py into engine globals ───

MODE_FLAGS = [
    'BXT_MODE', 'BXT_DT_S', 'BXT_EPSILON', 'BXT_ALPHA', 'BXT_GAMMA',
    'BXT_CAR_OCC', 'BXT_BALANCE_FACTOR', 'BXT_GE_BALANCE_FACTOR',
    'BXT_MAX_INS_S',
    'CELLQLEARN_DP_MODE', 'CELLQLEARN_DP_DT_S', 'CELLQLEARN_DP_HORIZON_S',
    'CELLQLEARN_DP_STAGE_S', 'CELLQLEARN_DP_COORD_WEIGHT',
    'CELLQLEARN_DP_CAR_OCC', 'CELLQLEARN_DP_BALANCE_FACTOR',
    'CELLQLEARN_DP_GE_BALANCE_FACTOR',
    'BARGAIN_SPM_MODE', 'BG_DET_LVL_IMM_S', 'BG_DET_LVL_NEAR_S',
    'BG_DET_LVL_FAR_S', 'BG_BUS_W_IMM', 'BG_BUS_W_NEAR', 'BG_BUS_W_FAR',
    'BG_BUS_W_VFAR', 'BG_SPM_RISK_WEIGHT', 'BG_MIN_BUS_DELAY_S',
    'BG_MIN_GAIN_S', 'BG_CASCADE_MULT', 'BG_NO_ACTION_BONUS_S',
    'DCTSP_ZIG_MODE', 'MP_ECTM_MODE', 'DCTSP_GREEN_REALLOC_MODE',
    'GREEN_REALLOC_RECOVER_FRACTION',
    'DCTSP_MIN_INS_DURATION_S', 'DCTSP_MAX_INS_DURATION_S',
    'ZIG_PHASE_OVERLAP_S', 'ZIG_BALANCE_FACTOR', 'ZIG_GE_BALANCE_FACTOR',
    'MP_ECTM_DT_S', 'MP_ECTM_MIN_EXT_S', 'MP_ECTM_MAX_EXT_S',
    'MP_ECTM_BALANCE_FACTOR', 'MP_ECTM_GE_BALANCE_FACTOR', 'MP_ECTM_CAR_OCC',
    'MP_ECTM_DP_MODE', 'MP_ECTM_DP_HORIZON_S', 'MP_ECTM_DP_STAGE_S',
    'MP_ECTM_DP_COORD_WEIGHT',
    'INS_INTERGREEN_S', 'NETWORK_FACTOR', 'NETWORK_FACTOR_DENSITY_RAMP',
    'CROSS_TRAFFIC_COST_MULTIPLIER',
    'DCTSP_W_H', 'DCTSP_W_HEADWAY', 'DCTSP_W_PAX_DELAY', 'DCTSP_CAR_WEIGHT',
    'SELFORG_MIN_BUS_DELAY_S', 'MAX_GE_EXTENSION_S',
    'ZIG_ENABLE_GE', 'ZIG_ENABLE_INS', 'ZIG_ENABLE_GR', 'ZIG_ENABLE_SEQ',
    'PHASE_ROTATION_MODE',
    'ZIG_MIN_GAIN_S',
    'DCTSP_MULTI_CYCLE_X_THR', 'DCTSP_MULTI_CYCLE_X_FLOOR',
    'REWARD_FUTURE_HORIZON_CYCLES', 'REWARD_FUTURE_DEBT_GAIN', 'REWARD_FUTURE_OFFSET_GAIN',
    'WOBJ_ALPHA', 'WOBJ_BETA', 'WOBJ_GAMMA',
    'BUS_PAX_WEIGHT', 'GREEN_KEEP_CREDIT_S', 'CORRIDOR_REWARD_NEIGHBOR_W',
    # 2026-08-24: multi-bus rollback (#3) + pre-arm timing hard-veto (#2)
    # + optimistic INS init so the learner inserts like the winning arms
    'MULTIBUS_MAX_FACTOR', 'PREARM_ALLOW_TIMING_ACTIONS',
    'BXT_INS_OPTIMISTIC_INIT',
    # CTM-prior Q-seeding (authentic cell-transmission-model Q-learning)
    'BXT_CTM_PRIOR_K', 'BXT_CTM_PRIOR_CLIP_PAXS',
]

# Mode TOGGLES that gate the dispatch registry.  Each one MUST default to False
# and only be turned on by an experiment that explicitly wants it.  A
# batch_runner writes run_config.py per experiment but only lists the flags an
# experiment turns ON, and this module is loaded ONCE per Aimsun session and
# reused across every experiment — so without an explicit reset a toggle set
# True by experiment N stays True for N+1..end, making later experiments run
# extra modes and produce identical results.  reset_mode_flags() (called from
# AAPIInit before applying each run_config.py) clears this leak.
MODE_TOGGLES = [
    'DCTSP_ZIG_MODE', 'MP_ECTM_MODE', 'MP_ECTM_DP_MODE', 'BXT_MODE',
    'CELLQLEARN_DP_MODE',
    'BARGAIN_SPM_MODE',
    'DCTSP_GREEN_REALLOC_MODE', 'META_TSP_MODE', 'MDN_DELAY_MODE',
    'HS_EXT_MODE', 'REWARD_SELFORG_MODE', 'REWARD_INV_DELAY_MODE',
    'REWARD_V2X_MODE', 'CENTRALIZED_MODE',
]

# Pristine defaults captured at import time (before any run_config is applied).
# Every MODE_FLAGS name that is a module global here is snapshotted so
# reset_mode_flags() can restore it between experiments.
_MODE_FLAG_DEFAULTS = {k: globals()[k] for k in MODE_FLAGS if k in globals()}


def reset_bxt_learning():
    """Clear the Q-table and pending-decision log so each SEED / replication is
    an INDEPENDENT learning episode.  CellQLearn learns within a run (its Q-table
    accrues realized-delay updates across that run's cycles), but must start each
    seed fresh from the analytic seed -- otherwise seed 400/500 inherit seed
    300's learning and the seeds are no longer independent.
    """
    try:
        _dctsp_bxt_q_table.clear()
        _poz_action_log.clear()
        _bxt_noaction_baseline.clear()
    except Exception:
        pass


def reset_mode_flags():
    """Restore every mode flag to its pristine import-time default.

    Call this at the start of each experiment's AAPIInit, BEFORE applying that
    experiment's run_config.py overrides, so no mode leaks in from the previous
    experiment run in the same Aimsun session.  Returns the list of toggles
    that were reset (for the [MODES] banner / diagnostics).
    """
    for _k, _v in _MODE_FLAG_DEFAULTS.items():
        setattr(sys.modules[__name__], _k, _v)
    # Force every known toggle False even if it had no module-level default.
    for _t in MODE_TOGGLES:
        setattr(sys.modules[__name__], _t, False)
    return list(MODE_TOGGLES)
