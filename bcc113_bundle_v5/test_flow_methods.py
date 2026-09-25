#!/usr/bin/env python3
"""test_flow_methods.py -- offline proof for the controller's flow logic.

Simulation_Stats.py cannot be imported outside Aimsun (top-level AAPI
import), so this harness replicates its pure flow math EXACTLY
(_section_windowed_flow + section flow cap + q/k/v residual) and drives it
with synthetic cumulative-count series, including the traps that produced the
historical 1e9-veh/h blowups. Run anywhere:

    python test_flow_methods.py

A PASS here proves the LOGIC. Whether the live AKI feeds (cumulative count,
TTa, snapshots) behave as assumed is proven separately, in-sim, by the
[FLOW-AUDIT] block (first 3 samples x first sections, logged per run).
"""
import statistics as st

INTERVAL_S = 30.0
MAX_SECTION_FLOW_VPH_PER_LANE = 2400.0  # must match Simulation_Stats


# ── Exact replica of Simulation_Stats._section_windowed_flow ──
class FlowState:
    def __init__(self):
        self.store = {}

    def windowed_flow(self, sec, now, cum, incum=None):
        """cum = cumulative completion count read 'now' (None = API failed).
        incum mirrors the live twin, which re-reads inputCount from the API
        on every call (NOT from the shared store)."""
        if cum is None:
            return None
        prev = self.store.get(int(sec))
        # NOTE: the repo twin tolerates both 2- and 3-tuples the same way.
        self.store[int(sec)] = (cum, cum if incum is None else incum,
                                float(now))
        if prev is None:
            return (cum * 3600.0 / max(float(now), 1.0)) if now > 0 else 0.0
        if len(prev) == 3:
            pc, _pinc, pt = prev
        else:
            pc, pt = prev
        dt = float(now) - float(pt)
        dcount = cum - float(pc)
        if dt <= 0.0 or dcount < 0.0:
            return 0.0
        return dcount * 3600.0 / dt


def cap_flow(flow, lanes):
    return min(flow, MAX_SECTION_FLOW_VPH_PER_LANE * max(float(lanes), 1.0))


def residual(q, k_per_lane, lanes, v):
    return q - k_per_lane * lanes * v


PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, cond, detail=""):
    results.append((PASS if cond else FAIL, name, detail))


# ── T1: steady flow converges to truth after the first sample ──
fs = FlowState()
outs = [fs.windowed_flow(7, t, 10 * (t // 30)) for t in (30, 60, 90, 120)]
# cum at t: 10,20,30,40 -> true rate 10/30s = 1200 veh/h
check("T1 first sample = mean-since-start", abs(outs[0] - 1200.0) < 1e-9, f"{outs[0]}")
check("T1 steady windows exact", all(abs(o - 1200.0) < 1e-9 for o in outs[1:]), f"{outs[1:]}")

# ── T2: THE historical trap -- cumulative count misread as a window count ──
# A section that has (correctly) counted 5000 veh since sim start, sampled at
# t=1500 s with a true 1200 veh/h rate over the last 30 s window.
fs2 = FlowState()
fs2.windowed_flow(7, 1470, 4960)          # prior sample
naive = 5000 * 3600.0 / INTERVAL_S        # old buggy formula on CURRENT cum
true_w = fs2.windowed_flow(7, 1500, 5000)  # delta = 40 -> 4800 veh/h? no: 40*3600/30
check("T2 naive formula explodes", naive > 100000, f"naive={naive:.0f}")
check("T2 windowed stays physical", abs(true_w - 4800.0) < 1e-9, f"windowed={true_w}")

# ── T3: counter reset (Aimsun restarts cumulative on replication reuse) ──
fs3 = FlowState()
fs3.windowed_flow(9, 60, 5000)
r_reset = fs3.windowed_flow(9, 90, 12)     # cum dropped -> must not go negative
r_next = fs3.windowed_flow(9, 120, 22)     # recovers: delta 10 / 30 s
check("T3 reset clamps to 0, no negative", r_reset == 0.0, f"{r_reset}")
check("T3 recovers next window", abs(r_next - 1200.0) < 1e-9, f"{r_next}")

# ── T4: degenerate timing ──
fs4 = FlowState()
fs4.windowed_flow(9, 60, 100)
check("T4 dt<=0 -> 0.0", fs4.windowed_flow(9, 60, 110) == 0.0)
check("T4 t=0 first sample -> 0.0", FlowState().windowed_flow(9, 0, 50) == 0.0)
check("T4 API failure passes None through", FlowState().windowed_flow(9, 60, None) is None)

# ── T5: saturation cap ──
check("T5 cap 2 lanes", cap_flow(9000, 2) == 4800.0)
check("T5 below cap untouched", cap_flow(1200, 2) == 1200.0)

# ── T6: residual semantics ──
# Imposed fallback (q built as k*v*lanes): residual must be ~0 by construction.
check("T6 imposed identity holds", abs(residual(484.7, 16.652, 1, 29.11)) < 1.0,
      "sanity scale only")
q_imp = 16.0 * 2 * 30.0
check("T6 imposed exact", residual(q_imp, 16.0, 2, 30.0) == 0.0)
# Measured triplet off the identity: residual is real signal, nonzero expected.
check("T6 measured mismatch nonzero", residual(6000.0, 16.0, 1, 30.0) != 0.0)

# ── T7: varying-rate tracking (real-time responsiveness) ──
fs7 = FlowState()
cums = [0, 5, 25, 60, 60, 65]   # quiet -> surge -> queue (frozen) -> release
outs7 = [fs7.windowed_flow(3, 30 * (i + 1), c) for i, c in enumerate(cums)]
expect7 = [cums[0] * 3600 / 30] + [(b - a) * 120.0 for a, b in zip(cums, cums[1:])]
check("T7 tracks surge/freeze/release",
      all(abs(o - e) < 1e-9 for o, e in zip(outs7, expect7)),
      f"{[round(o) for o in outs7]}")


# ── T8: upflow twin (inputCount delta) mirrors downflow semantics ──
class UpflowState(FlowState):
    """Replica of _section_windowed_upflow incl. shared-store discipline:
    upflow diffs WITHOUT writing (the flow twin owns the write cadence)."""

    def upflow(self, sec, now, incum):
        if incum is None:
            return None
        prev = self.store.get(int(sec))
        if prev is None:
            return (incum * 3600.0 / max(float(now), 1.0)) if now > 0 else 0.0
        if len(prev) == 3:
            _pc, _pinc, _pt = prev
        else:
            return None
        dt = float(now) - float(_pt)
        dc = incum - float(_pinc)
        if dt <= 0.0 or dc < 0.0:
            return 0.0
        return dc * 3600.0 / dt


def _write(store, sec, cum, incum, now):
    store[int(sec)] = (cum, incum, float(now))


ufs = UpflowState()
# ORDER: upflow must read BEFORE flow advances the shared store.
_write(ufs.store, 5, 100.0, 110.0, 60.0)     # previous pass baseline
u = ufs.upflow(5, 90.0, 125.0)               # delta 15 / 30 s -> 1800
ufs.windowed_flow(5, 90.0, 130.0, 140.0)     # flow twin advances store (fresh incum)
u2 = ufs.upflow(5, 120.0, 155.0)             # delta 15 / 30 s -> 1800
check("T8 upflow-before-flow ordering exact",
      abs(u - 1800.0) < 1e-9 and abs(u2 - 1800.0) < 1e-9, f"{u}, {u2}")
# WRONG order (flow first) zeroes the upflow -- the bug the sampler avoids.
ufs_bad = UpflowState()
_write(ufs_bad.store, 5, 100.0, 110.0, 60.0)
ufs_bad.windowed_flow(5, 90.0, 130.0)        # store advanced first...
u_bad = ufs_bad.upflow(5, 90.0, 125.0)       # ...so dt=0
check("T8 reversed order collapses (documents why order matters)",
      u_bad == 0.0, f"{u_bad}")


# ── T9: contiguous queue metres from stop line ──
def queue_metres(pts, thresh=5.0, anchor=25.0, gap=15.0):
    qp = sorted(d for (d, s) in pts if s < thresh)
    if not qp or qp[0] > anchor:
        return 0.0
    prev, qm = None, 0.0
    for dd in qp:
        if prev is None or (dd - prev) <= gap:
            qm, prev = dd, dd
        else:
            break
    return qm


check("T9 contiguous queue measured",
      queue_metres([(3, 0), (8, 0), (14, 2), (40, 0)]) == 14.0)
check("T9 gap breaks the queue",
      queue_metres([(3, 0), (8, 0), (40, 0), (44, 0)]) == 8.0)
check("T9 far cluster is mid-link, not queue",
      queue_metres([(100, 0), (105, 0)]) == 0.0)
check("T9 fast traffic has no queue",
      queue_metres([(3, 50), (8, 45)]) == 0.0)
# metres <-> vehicles via jam footprint: N queued veh ~= metres / 5.
check("T9 jam-footprint conversion",
      abs((14.0 / 5.0) - 2.8) < 1e-9)


# ── T10: tick-averaged k beats snapshot k under platooning ──
import random
random.seed(7)
lane_km, v = 0.4, 30.0
# True window-mean density 20; snapshots swing with platoon phase.
true_k, errs_snap, errs_avg = 20.0, [], []
for _w in range(200):
    phase = random.random()
    snap = true_k * (0.3 + 1.4 * phase)          # platoon-phase snapshot
    ticks = [true_k * (0.3 + 1.4 * random.random()) for _i in range(15)]
    avg = sum(ticks) / len(ticks)
    q = true_k * v                                # stationary truth
    errs_snap.append(abs(q - snap * v) / q)
    errs_avg.append(abs(q - avg * v) / q)
check("T10 averaged k beats snapshot k",
      st.median(errs_avg) < 0.5 * st.median(errs_snap),
      f"median snap={st.median(errs_snap):.3f} avg={st.median(errs_avg):.3f}")

print("=" * 64)
nfail = 0
for status, name, detail in results:
    if status == FAIL:
        nfail += 1
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and status == FAIL else ""))
print("=" * 64)
print(f"{len(results) - nfail}/{len(results)} checks passed")
if nfail:
    raise SystemExit(1)
print("VERDICT: flow-method logic proven (offline). Live-feed behaviour is")
print("proven separately by [FLOW-AUDIT] in-sim output.")
