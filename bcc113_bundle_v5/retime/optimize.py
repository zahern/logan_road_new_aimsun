#!/usr/bin/env python3
"""optimize.py -- offline splits + joint sequence/offset optimization.

Inputs: measurements.json + plan.json/corridor.json (see extract.py).
Method:
  Stage 1 -- Webster splits per junction on measured demand (main_x directly
             gives y_main; y_side = side_flow/(1800*side_lanes)). Green budget
             is conserved (yellows/intergreens untouched); min green 7 s.
             >2-stage junctions keep order (splits+offsets only).
  Stage 2 -- joint (sequence, offset) DP along the graph through-route.
             State per junction = (order bit for 2-stage, bus-green start on
             the integer lattice, 5 s step when cycle > 150). Pairwise cost =
             both-direction arrival-in-green misses using segment travel times
             (dist/12 m/s). Exact Viterbi on a chain.
Output: retime_v1.csv (junction, cycle, stage order, stage greens, offset =
        bus-green start) + console diagnostics (headroom created per junction).

Usage: python optimize.py [--dir DIR]
"""
import csv
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_GREEN = 7.0
CROSS_MIN = 10.0   # non-main stages never drop below this: guarantees a
                   # repayable headroom floor for TSP debt even where the
                   # measured cross demand is small
Y_ALLOC_CAP = 0.9  # cap y used for ALLOCATION (measured x>1 is oversat peaking,
                   # not a split target -- allocating to x=1.6 starves the side
                   # to min and creates zero headroom)
SPEED_MS = 12.0
STEP_SMALL, STEP_BIG, STEP_AT = 1, 5, 150


def load(d):
    meas = json.load(open(os.path.join(d, "measurements.json"),
                          encoding="utf-8"))
    corr = json.load(open(os.path.join(d, "corridor.json"), encoding="utf-8"))
    return meas, corr


def webster(entry):
    """(new_stage_greens, y_main, y_side, headroom_s) or None to keep."""
    stages = entry["green_stages"]
    if len(stages) < 2:
        return None
    durs = {int(k): float(v) for k, v in entry["stage_durs"].items()}
    bus_ph = entry["bus_ph"]
    main_st = bus_ph if bus_ph in stages else stages[0]
    side_st = [s for s in stages if s != main_st]
    y_main = float(entry["main_x"]["mean"] or 0.0)
    if y_main <= 0.0:
        return None
    lanes = max(int(entry.get("side_lanes", 0) or 0), 1)
    y_side = float(entry["side_flow_vph"]["mean"] or 0.0) / (1800.0 * lanes)
    tot_g = sum(durs.get(s, 0.0) for s in stages)
    if tot_g <= 0.0:
        return None
    # split the green budget pro-rata, min-green bounded (renormalize)
    ys = {main_st: min(y_main, Y_ALLOC_CAP)}
    for s in side_st:
        ys[s] = max(y_side / max(len(side_st), 1), 0.0)
    g = {}
    for s in stages:
        _floor = CROSS_MIN if s != main_st else MIN_GREEN
        g[s] = max(_floor, tot_g * ys.get(s, 0.0) / max(sum(ys.values()),
                                                        1e-9))
    over = sum(g.values()) - tot_g
    if over > 0:
        flex = [s for s in stages if g[s] > (CROSS_MIN if s != main_st
                                             else MIN_GREEN)]
        if not flex:
            return None
        for s in flex:
            _fl = CROSS_MIN if s != main_st else MIN_GREEN
            g[s] -= over * (g[s] - _fl) / max(
                sum(g[x] - (CROSS_MIN if x != main_st else MIN_GREEN)
                    for x in flex), 1e-9)
    # Repayable budget: what recovery can actually trim = cross green above
    # MIN_GREEN (the trim floor), NOT above CROSS_MIN. The CROSS_MIN floor
    # guarantees ~3 s per cross stage even where cross demand is small.
    headroom = sum(max(0.0, g[s] - MIN_GREEN) for s in stages
                   if s != main_st)
    return ({s: round(g[s], 1) for s in stages}, round(y_main, 3),
            round(y_side, 3), round(headroom, 1))


def bus_start(order_bit, stages, greens, bus_stage, inter_s=4.0):
    """Bus-green start within cycle for a stage order (blocks incl. yellow)."""
    seq = list(stages) if order_bit == 0 else list(reversed(stages))
    t = 0.0
    for s in seq:
        if s == bus_stage:
            return t
        t += greens[s] + inter_s
    return 0.0


def main(argv):
    d = HERE
    it = iter(argv)
    for a in it:
        if a == "--dir":
            d = next(it)
    meas, corr = load(d)
    order = corr["order"]
    segs = corr["seg_dist_m"]

    # ---- stage 1: splits ------------------------------------------------
    splits, diag = {}, {}
    for j in order:
        e = meas.get(j)
        if not e:
            continue
        r = webster(e)
        if r is None:
            splits[j] = {int(k): float(v)
                         for k, v in e["stage_durs"].items()}
            diag[j] = {"kept": True}
        else:
            g, ym, ys, hr = r
            splits[j] = g
            diag[j] = {"y_main": ym, "y_side": ys, "headroom_s": hr}

    # ---- stage 2: joint (order, offset) DP ------------------------------
    cyc = {j: float(meas[j]["cycle_sum"]) for j in order if j in meas}
    bus_st = {j: int(meas[j]["bus_ph"]) for j in order if j in meas}
    stages = {}
    for j in order:
        if j in meas:
            st = [int(s) for s in meas[j]["green_stages"]]
            stages[j] = st

    def states(j):
        c = cyc[j]
        step = STEP_BIG if c > STEP_AT else STEP_SMALL
        offs = list(range(0, int(math.floor(c)), step))
        if len(stages[j]) == 2:
            return [(o, off) for o in (0, 1) for off in offs]
        return [(0, off) for off in offs]

    def green_of(j, o):
        g = splits[j]
        return g

    def start_of(j, o, off):
        # bus-green start absolute-in-cycle given order bit + offset shift
        base = bus_start(o, stages[j], splits[j], bus_st[j])
        return (base + off) % cyc[j]

    def glen(j):
        return splits[j].get(bus_st[j], 0.0)

    def pair_cost(ju, su, jv, sv):
        """both-direction arrival-in-green miss (seconds outside window)."""
        t_uv = segs.get(f"{ju}>{jv}", segs.get(f"{jv}>{ju}", 0.0)) / SPEED_MS
        t_vu = t_uv
        cu, cv = cyc[ju], cyc[jv]
        gu = glen(ju)
        gv = glen(jv)

        def miss(arr, start, glen_, c):
            if glen_ <= 0:
                return 0.0
            rel = (arr - start) % c
            if rel <= glen_:
                return 0.0
            return min(rel - glen_, c - rel)
        # u->v platoon leaves mid of u green
        cost = miss((su + gu / 2.0 + t_uv), sv, gv, cv)
        cost += miss((sv + gv / 2.0 + t_vu), su, gu, cu)
        return cost

    # Viterbi along the chain
    dp, par = {}, {}
    first = order[0]
    for (o, off) in states(first):
        dp[(first, o, off)] = 0.0
    prev_states = {(o, off): start_of(first, o, off)
                   for (o, off) in states(first)}
    hist = [(first, prev_states)]
    for ju, jv in zip(order, order[1:]):
        cur = {}
        for (ov, offv) in states(jv):
            sv = start_of(jv, ov, offv)
            best, bk = None, None
            for (ou, offu), su in prev_states.items():
                c = dp[(ju, ou, offu)] + pair_cost(ju, su, jv, sv)
                if best is None or c < best:
                    best, bk = c, (ou, offu)
            cur[(ov, offv)] = best
            par[(jv, ov, offv)] = bk
        dp = {(jv, ov, offv): v for (ov, offv), v in cur.items()}
        prev_states = {(ov, offv): start_of(jv, ov, offv)
                       for (ov, offv) in cur}
        hist.append((jv, dict(prev_states)))
    # backtrack
    last = order[-1]
    bk = min(prev_states, key=lambda k: dp[(last,) + k])
    sol = {last: bk}
    for j in reversed(order[:-1]):
        jn = order[order.index(j) + 1]
        sol[j] = par[(jn,) + sol[jn]]

    # ---- write retime_v1.csv --------------------------------------------
    outp = os.path.join(d, "retime_v1.csv")
    with open(outp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["junction", "cycle_s", "bus_stage", "stage_order",
                    "stage_greens_s", "offset_bus_green_start_s",
                    "y_main", "y_side", "xheadroom_cross_s", "note"])
        for j in order:
            if j not in meas:
                continue
            o, off = sol[j]
            st = stages[j]
            seq = list(st) if o == 0 else list(reversed(st))
            g = splits[j]
            dg = diag[j]
            w.writerow([
                j, round(cyc[j], 1), bus_st[j],
                ";".join(str(s) for s in seq),
                ";".join(f"{s}={g.get(s, 0.0):.1f}" for s in seq),
                round(start_of(j, o, off), 1),
                dg.get("y_main", ""), dg.get("y_side", ""),
                dg.get("headroom_s", ""),
                "kept" if dg.get("kept") else
                ("order_swapped" if (len(st) == 2 and o == 1) else ""),
            ])
    nswap = sum(1 for j in order
                if j in sol and len(stages.get(j, [])) == 2 and sol[j][0] == 1)
    hr = [(j, diag[j].get("headroom_s", 0)) for j in order if j in diag]
    print(f"wrote {outp}: {len(order)} junctions, "
          f"{nswap} order swaps")
    print("cross headroom (repayable budget) top:",
          sorted(hr, key=lambda x: -x[1])[:6])
    print("kept (no data):",
          [j for j in order if j in diag and diag[j].get("kept")])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
