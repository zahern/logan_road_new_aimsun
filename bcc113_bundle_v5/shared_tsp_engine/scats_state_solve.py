"""scats_state_solve.py -- pure math for the SCATS full-state startup solve.

No Aimsun / PyANGKernel imports: everything here is deterministic arithmetic so
it can be unit-tested outside the simulator. The engine feeds it

  * the SCATS seed (cycle + stage greens) from scats_hist_plan.py,
  * the model's commissioned phase greens and bus phase,
  * the timetable-predicted bus arrival times at each junction,

and gets back

  * a split vector over the model phases (SCATS main-stage share + model
    relative side shares), and
  * the offset that maximises arrivals-on-green (POG) for those arrivals.

Why not map every SCATS stage to a model phase? The RAM export we decode
(scats_hist_plan.py) carries stage END times only -- the stage -> signal-group
composition lives in the Central Manager database, not the export. Inventing a
stage<->phase permutation would silently flatten or invert the plan (the
2026-10-20 equal-split regression). So the defensible full state is:

    cycle  = SCATS PDnCL (or the subsystem common cycle)
    splits = SCATS main-stage green share for the bus phase; the remaining
             green is split over the other model phases in proportion to the
             model's own commissioned greens (their real asymmetry is kept)
    offset = EXACT 1 s search over [0, C) maximising timetable POG

"Exact" here means exhaustive over the integer-lattice offset domain, not a
gradient/hill-climb, and independent per junction given the predicted arrival
times -- so it is the global optimum of the stated objective.
"""


BUILD = "2026-10-22T1800-guards2"


def _clean_greens(greens):
    out = []
    for g in greens or ():
        try:
            v = float(g)
        except Exception:
            continue
        if v > 0.0:
            out.append(v)
    return out


def main_stage_share(stage_greens):
    """Share of the cycle held by the largest SCATS stage (the main stage).

    Returns None when there is no usable stage list. The 1.0 s transition
    stages some sites expose cannot win the max, so they do not distort the
    main share.
    """
    g = _clean_greens(stage_greens)
    if not g:
        return None
    tot = sum(g)
    if tot <= 0.0:
        return None
    return max(g) / tot


def scale_splits(phase_greens, cycle_s, min_green=7.0):
    """Rescale a plan's greens to `cycle_s` keeping its SHARES (no SCATS
    share). Used by the cycle-clamp-only arm so the only change vs the base
    plan is the cycle length."""
    try:
        C = float(cycle_s)
    except Exception:
        return None
    if C <= 0.0:
        return None
    base = {}
    for p, g in (phase_greens or {}).items():
        try:
            base[int(p)] = max(0.0, float(g))
        except Exception:
            continue
    if not base:
        return None
    mg = max(0.0, float(min_green or 0.0))
    tot = sum(base.values())
    if tot <= 0.0:
        n = len(base)
        return {p: round(C / n, 1) for p in base}
    out = {p: max(mg, C * v / tot) for p, v in base.items()}
    out = {p: round(v, 1) for p, v in out.items()}
    resid = round(C - sum(out.values()), 1)
    if abs(resid) >= 0.05:
        p = max(out, key=lambda k: out[k])
        if out[p] + resid >= mg:
            out[p] = round(out[p] + resid, 1)
        else:
            return None
    if any(v < mg - 0.05 for v in out.values()):
        return None
    return out


def target_splits(phase_greens, bus_phase, cycle_s, main_share,
                  min_green=7.0):
    """Split vector {phase: green_s} summing to `cycle_s`.

    bus/main phase gets `main_share * cycle_s`; every other phase gets its
    commissioned share of the remaining green. Min-green is preserved. Returns
    None when the inputs cannot produce a feasible plan.
    """
    try:
        C = float(cycle_s)
        ms = float(main_share)
    except Exception:
        return None
    if C <= 0.0 or not (0.0 < ms < 1.0):
        return None
    base = {}
    for p, g in (phase_greens or {}).items():
        try:
            base[int(p)] = max(0.0, float(g))
        except Exception:
            continue
    if not base:
        return None
    bus_phase = int(bus_phase)
    if bus_phase not in base:
        return None
    mg = max(0.0, float(min_green or 0.0))
    others = [p for p in base if p != bus_phase]
    if not others:
        return {bus_phase: round(C, 1)}

    n_other = len(others)
    if C < mg * (n_other + 1):
        mg = max(0.0, C / float(n_other + 1) - 0.1)

    want_bus = C * ms
    lo_bus = mg
    hi_bus = C - mg * n_other
    if hi_bus < lo_bus:
        return None
    g_bus = max(lo_bus, min(hi_bus, want_bus))

    rem = max(0.0, C - g_bus)
    sum_o = sum(base[p] for p in others)
    out = {bus_phase: g_bus}
    for p in others:
        w = (base[p] / sum_o) if sum_o > 0.0 else (1.0 / n_other)
        out[p] = max(mg, rem * w)

    # Round + water-fill so the plan sums to the cycle exactly.
    out = {p: round(v, 1) for p, v in out.items()}
    resid = round(C - sum(out.values()), 1)
    if abs(resid) >= 0.05:
        # Give the residue to the phase with the most slack above min-green.
        slack = {p: max(0.0, out[p] - mg) for p in out}
        p = max(slack, key=lambda k: slack[k])
        if out[p] + resid >= mg:
            out[p] = round(out[p] + resid, 1)
        else:
            return None
    if any(v < mg - 0.05 for v in out.values()):
        return None
    return out


def arrival_histogram(arrival_times_s, cycle_s):
    """1 s circular histogram of arrival times (bin = arrival mod C)."""
    C = int(round(float(cycle_s)))
    if C <= 0:
        return None
    h = [0] * C
    for t in arrival_times_s or ():
        try:
            h[int(round(float(t))) % C] += 1
        except Exception:
            continue
    return h


def _window_sum(hist, start, length):
    n = len(hist)
    if n == 0 or length <= 0:
        return 0
    g = max(1, min(int(round(length)), n))
    pref = [0] * (2 * n + 1)
    for i in range(2 * n):
        pref[i + 1] = pref[i] + hist[i % n]
    s0 = int(round(start)) % n
    return pref[s0 + g] - pref[s0]


def best_offset(hist, green_start, green_len, cycle_s):
    """(offset_s, predicted_pog) maximising the green-window arrival count.

    The green window starts at `green_start` in the un-offset plan; adding an
    offset phi shifts it to (green_start + phi) mod C. Exhaustive over every
    integer phi in [0, C), so this is the exact optimum on the 1 s lattice.
    """
    C = int(round(float(cycle_s)))
    if not hist or C <= 0 or len(hist) != C:
        return (0.0, 0.0)
    total = float(sum(hist))
    if total <= 0.0 or float(green_len) <= 0.0:
        return (0.0, 0.0)
    best_val = -1
    best_phi = 0
    for phi in range(C):
        val = _window_sum(hist, float(green_start) + phi, green_len)
        if val > best_val:
            best_val = val
            best_phi = phi
    return (float(best_phi), float(best_val) / total)


def pog_at_offset(hist, green_start, green_len, cycle_s, offset_s):
    """Predicted POG for a fixed offset (for diagnostics / before-after)."""
    C = int(round(float(cycle_s)))
    if not hist or C <= 0 or len(hist) != C:
        return 0.0
    total = float(sum(hist))
    if total <= 0.0:
        return 0.0
    val = _window_sum(hist, float(green_start) + float(offset_s), green_len)
    return float(val) / total


def circular_shift(target_s, have_s, cycle_s):
    """Forward shift (s) in [0, C) that moves the plan from have to target."""
    try:
        C = float(cycle_s)
        if C <= 0.0:
            return 0.0
        return (float(target_s) - float(have_s)) % C
    except Exception:
        return 0.0
