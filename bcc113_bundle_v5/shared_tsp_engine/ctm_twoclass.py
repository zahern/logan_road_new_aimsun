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
          bus_pce: float) -> Tuple[CellState, Tuple[float, float]]:
    """One CTM step. Returns (new state, (car_held, bus_held)) where *_held
    are vehicles that did NOT leave their cell this step (delayed dt each)."""
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
    y[K - 1] = S[K - 1] if green else 0.0
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
             car_arrival_vph: float = 0.0, bus_pce: float = 2.0) -> CtmResult:
    """Run the two-class CTM over len(green_steps) steps.

    green_steps[k] is the stop-line signal at step k (True = green).
    car_arrival_vph: upstream car arrivals (veh/h) fed into cell 0. Bus
    arrivals are not predicted (buses are only those seeded from live data).
    """
    dt = float(geom.dt_s)
    q_in = max(0.0, float(car_arrival_vph)) / 3600.0 * dt
    s = cells.copy()
    first = True
    d_car = d_bus = 0.0
    q_car = q_bus = 0.0
    for g in green_steps:
        s, (hc, hb) = _step(geom, s, bool(g), q_in, bus_pce)
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
    print("OK: conservation, red/green, spillback, bus PCE, class split, "
          "junction action evaluation.")


if __name__ == "__main__":
    _selftest()
