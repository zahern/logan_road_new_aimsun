r"""ctm_twoclass.py -- two-class (bus / non-bus) Cell Transmission Model for one
signalised approach. Pure stdlib, no Aimsun: unit-testable on Windows.

Why it exists
-------------
Qin & Zhang (arXiv:2404.19683, Sec. 3.2, eqs. 1-5) model each approach as a
CTM with SEPARATE bus and non-bus densities, rho_bus and rho_non-bus, whose sum
is the cell density. Their flow law as printed, q = min(rho, v * dx) (eqs.
3-4), has no capacity and no receiving (supply) term, so a red light cannot
hold vehicles back and queues cannot spill upstream -- it does not conserve
flow at a signal. This module keeps the paper's TWO-CLASS state but uses the
standard Daganzo send/receive law that the engine's existing single-class CTM
(_ctm_cross_cost_paxs) already uses:

    S_i  = min(n_i, Q)                          sending (pcu / step)
    R_i  = min(Q, (w / v_f) * (N - n_i))        receiving
    y_i  = min(S_i, R_{i+1})                    flow i -> i+1
    stop line: y_{K-1} = S_{K-1} when green, 0 when red

with n_i in PCU (a bus counts BUS_PCE). Each flow is split between the classes
in proportion to the cell's PCU share (FIFO mixing within a cell), so buses and
cars queue and discharge TOGETHER but are accounted SEPARATELY -- that is the
"separate bus density".

Cell length L = v_f * dt, so a vehicle at free flow advances exactly one cell
per step. A vehicle still in its cell after a step was therefore held back for
dt seconds: delay_step(cell i) = (n_i - out_i) * dt, split by class. Summed over
the horizon this is the vehicle-seconds of delay the approach will incur.

Cells are indexed upstream (0) -> stop line (K-1).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass
class ApproachGeom:
    """One approach (Aimsun section) discretised into CTM cells."""
    length_m: float
    lanes: int = 1
    v_free_kmh: float = 50.0
    w_back_kmh: float = 18.0
    k_jam_vkm_lane: float = 200.0
    q_sat_vph_lane: float = 1800.0
    dt_s: float = 2.0
    max_cells: int = 12

    @property
    def vf_ms(self) -> float:
        return max(float(self.v_free_kmh) / 3.6, 1.0)

    @property
    def cell_len_m(self) -> float:
        return max(self.vf_ms * float(self.dt_s), 5.0)

    @property
    def n_cells(self) -> int:
        return max(1, min(int(math.ceil(max(self.length_m, 1.0)
                                        / self.cell_len_m)),
                          int(self.max_cells)))

    @property
    def storage_pcu(self) -> float:
        """N: jam storage per cell (pcu), all lanes."""
        return max(float(self.k_jam_vkm_lane) * (self.cell_len_m / 1000.0)
                   * max(int(self.lanes), 1), 1.0)

    @property
    def cap_pcu_step(self) -> float:
        """Q: max flow per step (pcu), all lanes."""
        return max(float(self.q_sat_vph_lane) / 3600.0 * max(int(self.lanes), 1)
                   * float(self.dt_s), 1e-6)

    @property
    def w_ratio(self) -> float:
        return min(1.0, max(float(self.w_back_kmh) / 3.6, 0.1) / self.vf_ms)


@dataclass
class CellState:
    """Per-cell vehicle counts by class (vehicles, not pcu)."""
    car: List[float]
    bus: List[float]

    def copy(self) -> "CellState":
        return CellState(list(self.car), list(self.bus))


def seed_cells(geom: ApproachGeom,
               vehicles: Sequence[Tuple[float, bool]]) -> CellState:
    """Place live vehicles into cells.

    vehicles: (distance_to_stop_line_m, is_bus) for each vehicle on the
    approach. Vehicles beyond the modelled reach (n_cells * L) are dropped --
    they are outside the horizon the model looks at.
    """
    K = geom.n_cells
    L = geom.cell_len_m
    car = [0.0] * K
    bus = [0.0] * K
    for d, is_bus in vehicles:
        try:
            d = float(d)
        except Exception:
            continue
        if d < 0.0:
            d = 0.0
        k_from_stop = int(d // L)
        if k_from_stop >= K:
            continue
        i = K - 1 - k_from_stop
        if is_bus:
            bus[i] += 1.0
        else:
            car[i] += 1.0
    return CellState(car, bus)


@dataclass
class CtmResult:
    car_delay_vs: float          # vehicle-seconds of car delay over the horizon
    bus_delay_vs: float          # vehicle-seconds of bus delay over the horizon
    car_queue_veh: float         # cars held back at t0 (standing queue now)
    bus_queue_veh: float         # buses held back at t0
    final: CellState = field(default_factory=lambda: CellState([], []))


def _step(geom: ApproachGeom, s: CellState, green: bool, car_in_pcu: float,
          bus_pce: float, out_cap_frac: float = 1.0) -> Tuple[CellState, Tuple[float, float]]:
    """One CTM step. Returns (new state, (car_held, bus_held)) where *_held
    are vehicles that did NOT leave their cell this step (delayed dt each).

    out_cap_frac in [0,1] throttles the STOP-LINE discharge by the DOWNSTREAM
    receiving link's free space: 1.0 = free downstream (discharge into an
    infinite sink, the original behaviour); 0.0 = the receiver is jammed, so a
    green cannot actually move the platoon (spillback). This is how the game
    prices the arterial queue an action creates instead of treating clearance
    as free."""
    K = len(s.car)
    N = geom.storage_pcu
    Q = geom.cap_pcu_step
    wr = geom.w_ratio
    pce = max(float(bus_pce), 1.0)
    n = [s.car[i] + pce * s.bus[i] for i in range(K)]          # pcu
    S = [min(n[i], Q) for i in range(K)]
    R = [min(Q, wr * max(0.0, N - n[i])) for i in range(K)]
    y = [0.0] * K                                                # out of cell i
    for i in range(K - 1):
        y[i] = min(S[i], R[i + 1])
    _ocf = min(max(float(out_cap_frac), 0.0), 1.0)
    y[K - 1] = (S[K - 1] * _ocf) if green else 0.0
    inflow0 = min(max(0.0, car_in_pcu), R[0])

    def split(i, pcu_out):
        """pcu leaving cell i -> (cars, buses) by the cell's pcu share."""
        if n[i] <= 1e-12 or pcu_out <= 0.0:
            return 0.0, 0.0
        f = min(1.0, pcu_out / n[i])
        return s.car[i] * f, s.bus[i] * f

    outs = [split(i, y[i]) for i in range(K)]
    car = list(s.car)
    bus = list(s.bus)
    held_car = held_bus = 0.0
    for i in range(K):
        oc, ob = outs[i]
        held_car += max(0.0, s.car[i] - oc)
        held_bus += max(0.0, s.bus[i] - ob)
        car[i] -= oc
        bus[i] -= ob
        if i + 1 < K:
            car[i + 1] += oc
            bus[i + 1] += ob
    car[0] += inflow0                       # arrivals are cars (pcu == veh)
    car = [x if x > 1e-12 else 0.0 for x in car]
    bus = [x if x > 1e-12 else 0.0 for x in bus]
    return CellState(car, bus), (held_car, held_bus)


def simulate(geom: ApproachGeom, cells: CellState, green_steps: Sequence[bool],
             car_arrival_vph: float = 0.0, bus_pce: float = 2.0,
             out_cap_frac: float = 1.0) -> CtmResult:
    """Run the two-class CTM over len(green_steps) steps.

    green_steps[k] is the stop-line signal at step k (True = green).
    car_arrival_vph: upstream car arrivals (veh/h) fed into cell 0. Bus
    arrivals are not predicted (buses are only those seeded from live data).
    out_cap_frac in [0,1]: downstream receiving-capacity throttle on the
    stop-line discharge (see _step); 1.0 keeps the original free-sink outflow.
    """
    dt = float(geom.dt_s)
    q_in = max(0.0, float(car_arrival_vph)) / 3600.0 * dt
    s = cells.copy()
    first = True
    d_car = d_bus = 0.0
    q_car = q_bus = 0.0
    for g in green_steps:
        s, (hc, hb) = _step(geom, s, bool(g), q_in, bus_pce, out_cap_frac)
        if first:
            q_car, q_bus = hc, hb
            first = False
        d_car += hc * dt
        d_bus += hb * dt
    return CtmResult(d_car, d_bus, q_car, q_bus, s)


def signal_profile(horizon_s: float, dt_s: float, green_now: bool,
                   green_after_s: Optional[float] = None) -> List[bool]:
    """Stop-line signal over the horizon: `green_now` until `green_after_s`
    (if given) flips it, else held for the whole horizon."""
    n = max(1, int(round(float(horizon_s) / max(float(dt_s), 1e-6))))
    out = []
    for k in range(n):
        t = k * float(dt_s)
        g = bool(green_now)
        if green_after_s is not None and t >= float(green_after_s):
            g = not g
        out.append(g)
    return out


# --------------------------------------------------------------------------- #
# Junction level: one snapshot, evaluate the consequence of a phase choice     #
# --------------------------------------------------------------------------- #
# snapshot = {phase_id: [(ApproachGeom, CellState, car_arrival_vph), ...]}
# -- the approaches each phase serves, seeded from live vehicles.
Snapshot = Dict[int, List[Tuple[ApproachGeom, CellState, float]]]


@dataclass
class PhaseOutcome:
    car_delay_vs: float = 0.0
    bus_delay_vs: float = 0.0
    car_queue_veh: float = 0.0
    bus_queue_veh: float = 0.0
    bus_present: float = 0.0        # buses anywhere in the modelled reach


def evaluate_action(snapshot: Snapshot, cur_phase: int, action: int,
                    horizon_s: float = 20.0, intergreen_s: float = 5.0,
                    bus_pce: float = 2.0) -> Dict[int, PhaseOutcome]:
    """Per-phase outcome of choosing `action` as the next green, from now.

    Signal assumed over the horizon, per phase p:
      p == action == cur_phase   green throughout (hold)
      p == action != cur_phase   red for intergreen_s, then green (switch:
                                 the clearance is lost time, so switching
                                 is never free)
      p != action                red throughout
    Each approach is simulated with its phase's profile. An approach that
    feeds several phases is simulated once per phase -- an approximation
    (shared lanes are not split by movement).
    """
    out: Dict[int, PhaseOutcome] = {}
    for ph, apps in snapshot.items():
        o = PhaseOutcome()
        for geom, cells, arr in apps:
            dt = geom.dt_s
            if ph == action and action == cur_phase:
                prof = signal_profile(horizon_s, dt, True)
            elif ph == action:
                prof = signal_profile(horizon_s, dt, False, intergreen_s)
            else:
                prof = signal_profile(horizon_s, dt, False)
            r = simulate(geom, cells, prof, arr, bus_pce)
            o.car_delay_vs += r.car_delay_vs
            o.bus_delay_vs += r.bus_delay_vs
            o.car_queue_veh += r.car_queue_veh
            o.bus_queue_veh += r.bus_queue_veh
            o.bus_present += sum(cells.bus)
        out[int(ph)] = o
    return out


# --------------------------------------------------------------------------- #
# Action timing profiles + per-section evaluation (game payoffs, 2026-11-05)   #
# --------------------------------------------------------------------------- #
# A junction's plan from NOW: the current phase with `rem` s of green left,
# then the ring in order, each phase its planned green, an intergreen between
# phases. Each TSP action rewrites that timeline:
#   NO_ACTION        the plan
#   GE  d            current (bus) green +d; the next phase's green -d (cycle
#                    recovered, as the controller does)
#   GR  d            current (cross) green ends d sooner (>= now); the ring
#                    runs on, so the bus phase arrives d sooner
#   INS d            current phase stops now; intergreen; the bus phase gets d
#                    of green; intergreen; the interrupted phase resumes its
#                    remaining green; then the ring as planned
#   ER  d            current (bus) green ends d sooner; the rest moves earlier
# Unknown action types return None (the caller keeps its legacy payoff).
TIMED_ACTIONS = {'GE': 'GE', 'GREEN_REALLOC': 'GR', 'GR': 'GR', 'INS': 'INS',
                 'INS_POST': 'INS', 'INS_PRETERM': 'INS', 'EARLY_RED': 'ER',
                 'ER': 'ER', 'NO_ACTION': 'NA'}


def action_timeline(action: str, d: float, ring: Sequence[int], cur: int,
                    rem: float, greens: Dict[int, float], bus_phase: int,
                    intergreen: float, horizon: float):
    """[(t0, t1, phase)] green intervals from now (t=0) to `horizon` for the
    junction under `action` of `d` s. None for an action type not modelled."""
    kind = TIMED_ACTIONS.get(str(action))
    if kind is None:
        return None
    ring = [int(p) for p in ring]
    if int(cur) not in ring:
        return None
    d = max(0.0, float(d))
    ig = max(0.0, float(intergreen))
    rem = max(0.0, float(rem))
    g = {int(p): max(0.0, float(greens.get(p, 0.0))) for p in ring}
    out = []
    t = 0.0

    def run_ring(start_idx, t, first_green=None, next_adjust=None):
        i = start_idx
        first = True
        while t < horizon:
            p = ring[i % len(ring)]
            dur = g[p] if not (first and first_green is not None) else first_green
            if not first and next_adjust is not None and next_adjust[0] == p:
                dur = max(0.0, dur + next_adjust[1])
                next_adjust = None
            if dur > 0:
                out.append((t, min(t + dur, horizon), p))
            t += dur + ig
            first = False
            i += 1
        return t

    ci = ring.index(int(cur))
    if kind == 'NA':
        run_ring(ci, 0.0, first_green=rem)
    elif kind == 'GE':
        nxt = ring[(ci + 1) % len(ring)]
        run_ring(ci, 0.0, first_green=rem + d, next_adjust=(nxt, -d))
    elif kind == 'GR':
        run_ring(ci, 0.0, first_green=max(0.0, rem - d))
    elif kind == 'ER':
        run_ring(ci, 0.0, first_green=max(0.0, rem - d))
    elif kind == 'INS':
        t = ig
        if d > 0:
            out.append((t, min(t + d, horizon), int(bus_phase)))
        t += d + ig
        run_ring(ci, t, first_green=rem)
    return [(a, b, p) for a, b, p in out if a < horizon]


def green_steps(timeline, phases, horizon: float, dt: float) -> Dict[int, List[bool]]:
    """{phase: [green at step k]} from a timeline."""
    n = max(1, int(round(float(horizon) / max(float(dt), 1e-6))))
    out = {int(p): [False] * n for p in phases}
    for a, b, p in timeline:
        if int(p) not in out:
            continue
        for k in range(n):
            tk = (k + 0.5) * dt
            if a <= tk < b:
                out[int(p)][k] = True
    return out


@dataclass
class SectionOutcome:
    car_delay_vs: float
    bus_delay_vs: float


def evaluate_sections(sec_snap, steps: Dict[int, List[bool]], bus_pce: float = 2.0
                      ) -> Dict[int, SectionOutcome]:
    """sec_snap: {sec: (ApproachGeom, CellState, car_arrival_vph, phases)}.
    A section is green at step k if ANY phase it feeds is green then (a
    shared approach discharges whenever one of its movements runs)."""
    out = {}
    for sec, entry in sec_snap.items():
        # entry is (geom, cells, arr, phases) or (geom, cells, arr, phases,
        # out_cap_frac) when the caller prices downstream spillback.
        geom, cells, arr, phases = entry[0], entry[1], entry[2], entry[3]
        _ocf = float(entry[4]) if len(entry) > 4 else 1.0
        lists = [steps[p] for p in phases if p in steps]
        if not lists:
            continue
        prof = [any(col) for col in zip(*lists)]
        r = simulate(geom, cells, prof, arr, bus_pce, _ocf)
        out[int(sec)] = SectionOutcome(r.car_delay_vs, r.bus_delay_vs)
    return out


def _shift(tl, lead, horizon):
    if tl is None:
        return None
    return [(a + lead, min(b + lead, horizon), p) for a, b, p in tl if a + lead < horizon]


# GAME_MARGINAL_DIAG: how often the marginal-competitor cost can differ from
# the sum.  Where every non-main approach feeds the SAME competing phase,
# min() over one key is identically the sum, so the flag can only be a no-op --
# this counter is what separates a null A/B from an inert flag.
_MARG_DIAG = {"calls": 0, "multi": 0, "maxph": 0, "gap": 0.0, "maxsec": 0}
_MARG_PENDING = []


def _marg_diag_note(nph, worst_saved, cc, nsec=0):
    """Record one marginal-cost evaluation (one ACTION, not one junction).

    nph  competing phases with NON-ZERO loss (only when two or more
         of them carry loss can min() differ from the sum);
    nsec  non-main sections priced;
    worst_saved  pax.s of the worst phase (the cost charged);
    cc  pax.s summed over every non-main section (what the flag replaces).
    Queues a line every 25th call; engine.py drains it (Aimsun's print() does
    not reach the run log)."""
    d = _MARG_DIAG
    d["calls"] += 1
    if nph > 1:
        d["multi"] += 1
    if nph > d["maxph"]:
        d["maxph"] = nph
    if nsec > d["maxsec"]:
        d["maxsec"] = nsec
    d["gap"] += (cc - worst_saved)
    if d["calls"] % 25 == 1:
        _MARG_PENDING.append(
            "[GAME_MARGINAL] calls=%d multi_phase=%d max_phases=%d "
            "worst_vs_sum=%+.1f pax.s max_sec=%d"
            % (d["calls"], d["multi"], d["maxph"], d["gap"], d["maxsec"]))


def drain_marginal_diag():
    """Return and clear the counter lines queued since the last drain."""
    out = list(_MARG_PENDING)
    del _MARG_PENDING[:]
    return out


def marginal_diag():
    """Final snapshot, for a one-line summary at the end of a run."""
    d = _MARG_DIAG
    return ("calls=%d multi_phase=%d max_phases=%d worst_vs_sum=%+.1f pax.s "
            "max_sec=%d" % (d["calls"], d["multi"], d["maxph"], d["gap"],
                            d["maxsec"]))


def game_payoffs(sec_snap, ring, cur, rem, greens, bus_phase, actions,
                 intergreen=5.0, horizon=60.0, dt=2.0, bus_pce=2.0,
                 bus_occ=40.0, car_occ=1.2, lead=0.0, cross_mult=1.0,
                 marginal=False):
    """Two-class CTM payoffs (B, C, b) in pax.s for each (type, seconds) in
    `actions`, against NO_ACTION over the horizon, in the convention the game
    solvers use:
        b = bus pax.s saved (all approaches)
        car_main  = car pax.s saved on approaches feeding the bus phase
        car_cross = car pax.s saved on the other approaches (usually < 0)
        B = b + car_main + max(0, car_cross)      C = max(0, -car_cross)*cross_mult
    Entries are None for action types this model does not time.
    cross_mult > 1 sharpens the existing cross-starvation cost C (the car
    pax.s LOST on approaches that give up green to this action) WITHOUT touching
    the benefit side B, so the solver must clear a higher cross bar before it
    acts. It reweights the one cross term already computed from the CTM -- it is
    NOT a second parallel cost, so there is no double-count. 1.0 = unchanged.
    lead > 0: every approach is red for `lead` s first (the decision falls in
    an interphase / a phase with no modelled approaches); `cur` is then the
    next modelled phase and `rem` its full planned green."""
    cross_mult = max(0.0, float(cross_mult))
    phases = list(ring)
    lead = max(0.0, float(lead))
    na_tl = _shift(action_timeline('NO_ACTION', 0.0, ring, cur, rem, greens, bus_phase,
                                   intergreen, horizon), lead, horizon)
    if na_tl is None:
        return [None] * len(actions)
    base = evaluate_sections(sec_snap, green_steps(na_tl, phases, horizon, dt), bus_pce)
    main_secs = {s for s, v in sec_snap.items() if int(bus_phase) in v[3]}
    res = []
    for at, ap in actions:
        tl = _shift(action_timeline(at, ap, ring, cur, rem, greens, bus_phase,
                                    intergreen, horizon), lead, horizon)
        if tl is None:
            res.append(None)
            continue
        o = evaluate_sections(sec_snap, green_steps(tl, phases, horizon, dt), bus_pce)
        b = sum(base[s].bus_delay_vs - o[s].bus_delay_vs for s in o) * float(bus_occ)
        cm = sum(base[s].car_delay_vs - o[s].car_delay_vs for s in o if s in main_secs) \
            * float(car_occ)
        # Per non-main section: car pax.s SAVED by the action (negative = the
        # action costs that competing approach). cc = net over all of them.
        _cross = [(s, (base[s].car_delay_vs - o[s].car_delay_vs) * float(car_occ))
                  for s in o if s not in main_secs]
        cc = sum(_d for _s, _d in _cross)
        if marginal:
            # MARGINAL-COMPETITOR COST (SIDE_COST_MARGINAL_COMPETITOR): on a
            # fixed-cycle coordinated plan the bus hold displaces ONE competing
            # phase, not all of them at once, so the opportunity cost is the
            # single WORST conflicting phase -- not the SUM over every non-main
            # approach (which only matches a true floating-cycle extension where
            # the whole downstream sequence slips). Group the per-section saved
            # pax.s by the competing PHASE each section feeds and charge the
            # phase with the largest net LOSS. Benefit B is unchanged (every
            # approach that genuinely gains still gains); only the cost bar C
            # drops from sum -> worst single phase.
            _loss_by_phase = {}
            for _s, _d in _cross:
                for _p in sec_snap[_s][3]:
                    if int(_p) == int(bus_phase):
                        continue
                    _loss_by_phase[int(_p)] = _loss_by_phase.get(int(_p), 0.0) + _d
            _worst_saved = min(_loss_by_phase.values()) if _loss_by_phase else cc
            _nz = [_v for _v in _loss_by_phase.values()
                   if abs(_v) > 1e-9]
            _marg_diag_note(len(_nz), _worst_saved, cc, len(_cross))
            C = max(0.0, -_worst_saved) * cross_mult
        else:
            C = max(0.0, -cc) * cross_mult
        B = b + cm + max(0.0, cc)
        res.append((B, C, b))
    return res


# --------------------------------------------------------------------------- #
# Self-test (python -I ctm_twoclass.py)                                        #
# --------------------------------------------------------------------------- #
def _check(c, m):
    if not c:
        raise AssertionError(m)


def _selftest() -> None:
    g = ApproachGeom(length_m=200.0, lanes=1, dt_s=2.0)
    print("geom: L=%.1fm K=%d N=%.2fpcu Q=%.3fpcu/step w/vf=%.2f"
          % (g.cell_len_m, g.n_cells, g.storage_pcu, g.cap_pcu_step, g.w_ratio))

    # Conservation: red, no arrivals -> nobody leaves, totals constant.
    c = seed_cells(g, [(5.0, False), (10.0, True), (60.0, False), (150.0, False)])
    tot0 = sum(c.car) + sum(c.bus)
    r = simulate(g, c, [False] * 30, 0.0)
    _check(abs(sum(r.final.car) + sum(r.final.bus) - tot0) < 1e-9,
           "red with no arrivals must conserve vehicles")
    _check(r.final.bus[-1] > 0.99, "bus must end in the stop-line cell")

    # Red holds the queue; green discharges at capacity.
    red = simulate(g, c, [False] * 15, 0.0)
    grn = simulate(g, c, [True] * 15, 0.0)
    _check(red.car_delay_vs > grn.car_delay_vs, (red, grn))
    _check(red.bus_delay_vs > grn.bus_delay_vs, (red, grn))
    _check(sum(grn.final.car) + sum(grn.final.bus) < tot0, "green must discharge")

    # Spillback: a long red with heavy arrivals fills cells from the stop line
    # back; the upstream cell's receiving term throttles inflow.
    sp = simulate(g, CellState([0.0] * g.n_cells, [0.0] * g.n_cells),
                  [False] * 200, 1500.0)
    _check(sp.final.car[-1] >= g.storage_pcu - 1e-6, "stop-line cell must jam")
    _check(sum(sp.final.car) <= g.storage_pcu * g.n_cells + 1e-6,
           "storage never exceeded")
    _check(sp.final.car[0] > 0.5 * g.storage_pcu, "queue must spill to cell 0")

    # Bus PCE: one bus takes the space of bus_pce cars.
    one_bus = CellState([0.0] * g.n_cells, [0.0] * g.n_cells)
    one_bus.bus[-1] = 1.0
    _check(abs(simulate(g, one_bus, [False], 0.0, bus_pce=2.0).bus_queue_veh
               - 1.0) < 1e-9, "a bus at a red stop line is held")

    # Separate accounting: same pcu, bus share split by class.
    mix = seed_cells(g, [(1.0, False), (2.0, True)])
    m = simulate(g, mix, [False] * 5, 0.0)
    _check(abs(m.car_queue_veh - 1.0) < 1e-9 and abs(m.bus_queue_veh - 1.0) < 1e-9, m)
    _check(abs(m.bus_delay_vs - 10.0) < 1e-9, m)       # 1 bus x 5 steps x 2 s
    print("red   : car_delay=%.1f veh.s bus_delay=%.1f veh.s"
          % (red.car_delay_vs, red.bus_delay_vs))
    print("green : car_delay=%.1f veh.s bus_delay=%.1f veh.s"
          % (grn.car_delay_vs, grn.bus_delay_vs))
    print("spill : cells", [round(x, 1) for x in sp.final.car])
    # Junction level: holding the phase that has the bus beats switching away,
    # and switching TO it costs the intergreen compared with already having it.
    snap = {1: [(g, seed_cells(g, [(5.0, True), (8.0, False)]), 300.0)],
            2: [(g, seed_cells(g, [(5.0, False)]), 300.0)]}
    hold = evaluate_action(snap, 1, 1)
    away = evaluate_action(snap, 1, 2)
    _check(hold[1].bus_delay_vs < away[1].bus_delay_vs, (hold, away))
    to_bus = evaluate_action(snap, 2, 1)
    _check(hold[1].bus_delay_vs < to_bus[1].bus_delay_vs <= away[1].bus_delay_vs,
           (hold[1], to_bus[1], away[1]))
    _check(hold[1].bus_present == 1.0 and hold[2].bus_present == 0.0, hold)
    print("junction: bus delay hold=%.1f  switch-to=%.1f  away=%.1f veh.s"
          % (hold[1].bus_delay_vs, to_bus[1].bus_delay_vs, away[1].bus_delay_vs))
    # Action timelines: ring [1 (bus), 2], greens 20/30, IG 5, 6 s left on 1.
    ring, gr = [1, 2], {1: 20.0, 2: 30.0}
    na = action_timeline('NO_ACTION', 0, ring, 1, 6.0, gr, 1, 5.0, 80.0)
    _check(na[:3] == [(0.0, 6.0, 1), (11.0, 41.0, 2), (46.0, 66.0, 1)], na)
    ge = action_timeline('GE', 4, ring, 1, 6.0, gr, 1, 5.0, 80.0)
    _check(ge[:2] == [(0.0, 10.0, 1), (15.0, 41.0, 2)], ge)       # +4 bus, -4 cross
    ins = action_timeline('INS', 8, ring, 2, 12.0, gr, 1, 5.0, 80.0)
    _check(ins[:3] == [(5.0, 13.0, 1), (18.0, 30.0, 2), (35.0, 55.0, 1)], ins)
    _check(action_timeline('PHASE_SKIP', 3, ring, 1, 6.0, gr, 1, 5.0, 80.0) is None,
           'unknown action must be None')
    # Game payoffs: a bus 10 m before the bus-phase stop line with 6 s of
    # green left behind 3 cars; cross approach with 4 queued cars.
    gm = ApproachGeom(length_m=120.0, lanes=1, dt_s=2.0)
    gx = ApproachGeom(length_m=120.0, lanes=1, dt_s=2.0)
    snap = {10: (gm, seed_cells(gm, [(2, False), (6, False), (9, False), (14, True)]),
                 300.0, (1,)),
            20: (gx, seed_cells(gx, [(2, False), (6, False), (10, False), (14, False)]),
                 300.0, (2,))}
    pay = game_payoffs(snap, ring, 1, 2.0, gr, 1, [('GE', 6.0), ('ER', 2.0),
                                                   ('PHASE_SKIP', 3.0)])
    B, C, b = pay[0]
    _check(b > 0 and C > 0, ('GE helps the bus and costs the cross street', pay[0]))
    _check(pay[1][2] < 0, ('ER before the bus has cleared makes it miss', pay[1]))
    # ER after the bus has passed (no bus left): bus unaffected, cross gains
    # (empty main approach: with mainline arrivals still coming, cutting the
    #  bus-phase green costs mainline cars more than the cross street gains)
    snap_er = {10: (gm, seed_cells(gm, []), 0.0, (1,)),
               20: snap[20]}
    Be, Ce, be = game_payoffs(snap_er, ring, 1, 6.0, gr, 1, [('ER', 4.0)])[0]
    _check(abs(be) < 1e-9 and Be > 0 and Ce == 0.0, ('ER after the bus', Be, Ce, be))
    _check(pay[2] is None, 'unmodelled action -> None')
    # interphase: 3 s all-red first, then phase 1 with its full 20 s
    pl = game_payoffs(snap, ring, 1, 20.0, gr, 1, [('GE', 4.0)], lead=3.0)
    _check(pl[0] is not None and pl[0][2] >= 0.0, ('lead timeline', pl))
    print("game payoffs GE6: B=%.0f C=%.0f b=%.0f   ER4 (bus gone): B=%.0f C=%.0f b=%.0f pax.s"
          % (B, C, b, Be, Ce, be))
    print("OK: conservation, red/green, spillback, bus PCE, class split, "
          "junction action evaluation, action timelines, game payoffs.")


if __name__ == "__main__":
    _selftest()
