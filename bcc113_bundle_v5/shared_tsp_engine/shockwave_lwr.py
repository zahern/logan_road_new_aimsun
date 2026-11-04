r"""shockwave_lwr.py -- kinematic-wave (LWR / Newell) timing at a signal stop
line, for SOLVING the green-extension (GE) and phase-insertion (INS) seconds.
Pure stdlib, no Aimsun: unit-testable on Windows.

Model
-----
Triangular fundamental diagram PER LANE: free-flow speed v_f, saturation flow
q_s (capacity), jam density k_j. Critical density k_c = q_s / v_f and the
backward (congestion) wave speed is the one CONSISTENT with those three,

    w = q_s / (k_j - k_c)

so the space and time pictures agree (an independently-set w would make the
queue reach and the discharge timing contradict each other).

Newell's simplified kinematic wave theory gives, at a stop line:

* Discharge: from the start of green the stop line passes q_s veh/s per lane
  while a queue remains. The j-th queued vehicle in a lane (j = 1 at the stop
  line) crosses at  t_green + j / q_s  -- the discharge wave leaves the stop
  line at w and that vehicle starts at (j/k_j)/w, then covers (j/k_j) at v_f;
  (1/k_j)(1/w + 1/v_f) = 1/q_s exactly.
* Queue formation wave (arrivals q_a, uncongested density k_a = q_a / v_f):
  speed u = q_a / (k_j - k_a); the queue's back reaches N / (k_j - k_a).
* Queue clearance under green with continuing arrivals: departures q_s*t
  catch cumulative arrivals N + q_a*t at  t = N / (q_s - q_a)  (point-queue
  algebra, but now PER LANE and WITH arrivals -- the two things the old
  closed form dropped). Oversaturated (q_a >= q_s): never clears -> None.

A bus therefore crosses at max(free-run arrival, its slot in the discharge):
    t_cross = max(dist / v_bus, t_green_start + (n_ahead + 1) / q_s)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class LaneFD:
    v_free_kmh: float = 50.0
    k_jam_vkm: float = 200.0          # veh / km / lane
    q_sat_vph: float = 1800.0         # veh / h / lane

    @property
    def vf(self) -> float:            # m/s
        return max(float(self.v_free_kmh) / 3.6, 0.5)

    @property
    def kj(self) -> float:            # veh / m / lane
        return max(float(self.k_jam_vkm) / 1000.0, 1e-4)

    @property
    def qs(self) -> float:            # veh / s / lane
        return max(float(self.q_sat_vph) / 3600.0, 1e-4)

    @property
    def kc(self) -> float:
        return min(self.qs / self.vf, 0.95 * self.kj)

    @property
    def w(self) -> float:             # backward wave speed, m/s (positive)
        return self.qs / max(self.kj - self.kc, 1e-6)


def arrival_density(fd: LaneFD, q_arr_vph: float) -> float:
    """Uncongested-branch density of an arrival flow (veh/m/lane)."""
    return min(max(0.0, float(q_arr_vph)) / 3600.0 / fd.vf, fd.kc)


def formation_wave_speed(fd: LaneFD, q_arr_vph: float) -> float:
    """Speed (m/s, upstream) at which the back of a standing queue grows."""
    qa = max(0.0, float(q_arr_vph)) / 3600.0
    return qa / max(fd.kj - arrival_density(fd, q_arr_vph), 1e-6)


def queue_reach_m(fd: LaneFD, n_queue: float, q_arr_vph: float = 0.0) -> float:
    """Back-of-queue distance from the stop line for n_queue stopped veh/lane."""
    return max(0.0, float(n_queue)) / max(fd.kj - arrival_density(fd, q_arr_vph),
                                          1e-6)


def queue_after_red(n0: float, q_arr_vph: float, red_s: float) -> float:
    """Vehicles per lane queued after red_s more seconds of red."""
    return max(0.0, float(n0)) + max(0.0, float(q_arr_vph)) / 3600.0 * max(0.0, float(red_s))


def queue_clear_time(fd: LaneFD, n_queue: float, q_arr_vph: float
                     ) -> Optional[float]:
    """Seconds of green (from now, green running) to discharge the current
    per-lane queue while arrivals continue. None when oversaturated."""
    qa = max(0.0, float(q_arr_vph)) / 3600.0
    if qa >= fd.qs - 1e-9:
        return None
    return max(0.0, float(n_queue)) / (fd.qs - qa)


def bus_cross_time(fd: LaneFD, dist_m: float, n_ahead: float,
                   green_start_s: float = 0.0, bus_speed_ms: Optional[float] = None
                   ) -> float:
    """Time from now at which the bus crosses the stop line, if its phase is
    green from `green_start_s` (0 = green now) for as long as it needs.

    n_ahead: vehicles in the bus's lane between it and the stop line that will
    discharge before it. bus_speed_ms: the bus's free-run speed (falls back to
    v_f; a crawling bus in a queue is bounded by the discharge term anyway)."""
    v = float(bus_speed_ms) if (bus_speed_ms and bus_speed_ms > 0.5) else fd.vf
    t_free = max(0.0, float(dist_m)) / v
    t_slot = max(0.0, float(green_start_s)) + (max(0.0, float(n_ahead)) + 1.0) / fd.qs
    return max(t_free, t_slot)


def ge_to_serve_bus(fd: LaneFD, rem_green_s: float, dist_m: float,
                    n_ahead: float, bus_speed_ms: Optional[float] = None,
                    margin_s: float = 1.0) -> float:
    """Green extension (s) so the bus crosses before the current green ends.
    0 when it already makes it."""
    t = bus_cross_time(fd, dist_m, n_ahead, 0.0, bus_speed_ms)
    return max(0.0, t + float(margin_s) - max(0.0, float(rem_green_s)))


def ins_green_to_serve_bus(fd: LaneFD, start_in_s: float, dist_m: float,
                           n_ahead: float, bus_speed_ms: Optional[float] = None,
                           margin_s: float = 1.0) -> float:
    """Length (s) of an inserted green starting `start_in_s` from now (e.g. the
    intergreen) that lets the bus cross."""
    t = bus_cross_time(fd, dist_m, n_ahead, start_in_s, bus_speed_ms)
    return max(0.0, t + float(margin_s) - max(0.0, float(start_in_s)))


def ge_to_clear_queue(fd: LaneFD, rem_green_s: float, n_queue: float,
                      q_arr_vph: float) -> Optional[float]:
    """Green extension (s) so the current queue clears before green ends.
    None when it cannot clear (oversaturated)."""
    t = queue_clear_time(fd, n_queue, q_arr_vph)
    if t is None:
        return None
    return max(0.0, t - max(0.0, float(rem_green_s)))


# --------------------------------------------------------------------------- #
# Route ETA: where and when the bus reaches THIS junction's stop line          #
# --------------------------------------------------------------------------- #
@dataclass
class RouteEta:
    dist_m: float            # along the bus's own PT route to the stop line
    run_s: float             # dist / cruise speed
    dwell_s: float           # dwell at the scheduled stops in between
    n_stops: int
    eta_s: float             # run_s + dwell_s (+ any timetable hold)
    hold_s: float = 0.0      # waiting for a timepoint when running early


def route_eta(route_secs, sec_len_m, bus_sec, bus_pos_m, target_sec,
              cruise_ms, stop_secs=(), dwell_s=20.0, stop_sched_abs=None,
              now_s=0.0, hold_early=False) -> Optional[RouteEta]:
    """ETA of a bus to the END (stop line) of `target_sec`, following its line's
    route in order (AKIPTGetIdSectionInLine), from its live section/position.

    stop_secs: sections holding a stop of this line (_SCHED_STOP_SECS). Stops
    on sections AFTER the bus's section, up to and including target_sec, each
    add `dwell_s` (the stop's position inside its section is unknown, so a stop
    on the bus's own section is assumed already served).
    stop_sched_abs: {section: scheduled absolute arrival (s)} for this bus's
    trip; with hold_early=True the bus waits at a stop it would reach early
    (timepoint holding). Returns None if target_sec is not ahead on the route.
    """
    route = [int(s) for s in (route_secs or [])]
    try:
        i0 = route.index(int(bus_sec))
    except ValueError:
        return None
    try:
        i1 = route.index(int(target_sec), i0)
    except ValueError:
        return None
    L = lambda s: max(0.0, float((sec_len_m or {}).get(int(s), 0.0)))
    if i1 == i0:
        dist = max(0.0, L(bus_sec) - float(bus_pos_m))
    else:
        dist = max(0.0, L(bus_sec) - float(bus_pos_m))
        dist += sum(L(s) for s in route[i0 + 1:i1 + 1])
    v = max(float(cruise_ms), 0.5)
    stops = set(int(s) for s in (stop_secs or ()))
    t = float(now_s)
    pos = max(0.0, L(bus_sec) - float(bus_pos_m))      # metres to end of bus sec
    run = pos / v if i1 > i0 else dist / v
    t += run
    dwell = hold = 0.0
    n = 0
    for s in route[i0 + 1:i1 + 1]:
        t += L(s) / v
        run += L(s) / v
        if s in stops:
            n += 1
            dwell += float(dwell_s)
            t += float(dwell_s)
            if hold_early and stop_sched_abs and s in stop_sched_abs:
                _h = max(0.0, float(stop_sched_abs[s]) - t)
                hold += _h
                t += _h
    return RouteEta(dist, run, dwell, n, run + dwell + hold, hold)


# --------------------------------------------------------------------------- #
# Self-test (python -I shockwave_lwr.py)                                       #
# --------------------------------------------------------------------------- #
def _check(c, m):
    if not c:
        raise AssertionError(m)


def _selftest() -> None:
    fd = LaneFD(50.0, 200.0, 1800.0)
    # consistency: (1/kj)(1/w + 1/vf) == 1/qs
    _check(abs((1.0 / fd.kj) * (1.0 / fd.w + 1.0 / fd.vf) - 1.0 / fd.qs) < 1e-9,
           "triangular FD must be consistent")
    print("FD: vf=%.2f m/s  qs=%.3f veh/s  kj=%.3f veh/m  kc=%.4f  w=%.2f m/s "
          "(%.1f km/h)" % (fd.vf, fd.qs, fd.kj, fd.kc, fd.w, fd.w * 3.6))

    # bus 100 m away, free run, nobody ahead -> 100/13.9 = 7.2 s
    _check(abs(bus_cross_time(fd, 100.0, 0) - 100.0 / fd.vf) < 1e-9, "free run")
    # bus behind 10 queued cars at the stop line -> slot 11/qs = 22 s
    _check(abs(bus_cross_time(fd, 60.0, 10) - 11.0 / fd.qs) < 1e-9, "queue slot")
    # GE: 5 s of green left, bus needs 22 s -> 17 s (+1 margin = 18)
    ge = ge_to_serve_bus(fd, 5.0, 60.0, 10)
    _check(abs(ge - (11.0 / fd.qs + 1.0 - 5.0)) < 1e-9, ge)
    # the OLD bus-serve (eta - rem) with eta = 60/13.9 = 4.3 s said "no GE needed"
    _check(60.0 / fd.vf - 5.0 < 0.0 < ge, "old formula misses the queued bus")
    # INS starting after 5 s intergreen, bus 3rd in queue -> 4/qs + 1 = 9 s
    ins = ins_green_to_serve_bus(fd, 5.0, 15.0, 3)
    _check(abs(ins - (4.0 / fd.qs + 1.0)) < 1e-9, ins)
    # queue clear with arrivals vs without
    t0 = queue_clear_time(fd, 10.0, 0.0)
    t1 = queue_clear_time(fd, 10.0, 900.0)
    _check(abs(t0 - 20.0) < 1e-9 and abs(t1 - 40.0) < 1e-9, (t0, t1))
    _check(queue_clear_time(fd, 10.0, 1800.0) is None, "oversaturated")
    # reach: 10 veh at jam ~ 50 m; with arrivals the back is a bit further
    _check(abs(queue_reach_m(fd, 10.0) - 50.0) < 1e-9, queue_reach_m(fd, 10.0))
    _check(queue_reach_m(fd, 10.0, 900.0) > 50.0, "arrival density")
    print("bus-serve GE: shockwave=%.1fs vs old eta-rem=%.1fs (bus behind 10 cars)"
          % (ge, 60.0 / fd.vf - 5.0))
    print("queue clear 10 veh/lane: no arrivals %.0fs, 900 vph arrivals %.0fs"
          % (t0, t1))
    # Route ETA: bus 40 m into a 100 m section, then 200 m (stop) then the
    # 150 m approach: 60 + 200 + 150 = 410 m at 10 m/s + one 20 s dwell.
    r = route_eta([1, 2, 3, 4], {1: 100.0, 2: 200.0, 3: 150.0, 4: 80.0},
                  1, 40.0, 3, 10.0, stop_secs={2, 4}, dwell_s=20.0)
    _check(abs(r.dist_m - 410.0) < 1e-9 and r.n_stops == 1
           and abs(r.eta_s - 61.0) < 1e-9, r)
    # same section: just the remaining length, no stops
    r2 = route_eta([1, 2, 3], {3: 150.0}, 3, 100.0, 3, 10.0, stop_secs={3})
    _check(abs(r2.dist_m - 50.0) < 1e-9 and r2.n_stops == 0, r2)
    # timepoint hold: scheduled at stop 2 at t=100, bus would be there at 26 s
    r3 = route_eta([1, 2, 3], {1: 100.0, 2: 200.0, 3: 150.0}, 1, 40.0, 3, 10.0,
                   stop_secs={2}, dwell_s=0.0, stop_sched_abs={2: 100.0},
                   now_s=0.0, hold_early=True)
    _check(abs(r3.hold_s - 74.0) < 1e-9, r3)
    _check(route_eta([1, 2], {}, 2, 0.0, 1, 10.0) is None, "target behind bus")
    print("route ETA: 410 m, 1 stop -> %.0f s (run %.0f + dwell %.0f)"
          % (r.eta_s, r.run_s, r.dwell_s))
    print("OK: FD consistency, bus crossing, GE/INS to serve, clearance, reach, "
          "route ETA.")


if __name__ == "__main__":
    _selftest()
