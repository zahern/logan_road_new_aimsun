"""Cost of raising BXT_ER_OFFPHASE_GAIN_WEIGHT.

For each weight, find which (state, truncation) combinations ER now wins, and
report the REAL pax*s trade it accepts at those wins:

    harm   = d_bus(ER) - d_bus(NO_ACTION)     running-phase pax*s given up
    credit = priced off-phase gain            off-phase pax*s saved
    real loss ratio = harm / credit

The weight only changes the DECISION; it does not change the physics. A weight
of W converts "accept L pax*s of real loss" into "worth doing", so every win at
W carries a real-terms loss ratio somewhere in (1, W].

Run: python -I _check_er_weight_cost.py
"""
import ast
import io
import math

import numpy as np

SM = "shared_tsp_engine/specialized_modes.py"
ENG = "shared_tsp_engine/engine.py"


def safe_float(v, d=0.0):
    try:
        r = float(v)
    except (TypeError, ValueError):
        return d
    return r if math.isfinite(r) else d


src = io.open(SM, encoding="utf-8", errors="replace").read()
tree = ast.parse(src)
lines = src.splitlines()
node = next(n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_ctm_red_delay")
CTM_SRC = "\n".join(l[4:] if l.startswith("    ") else l
                    for l in lines[node.lineno - 1:node.end_lineno])

el = io.open(ENG, encoding="utf-8", errors="replace").read().splitlines()
si = next(i for i, l in enumerate(el) if "def _dctsp_off_phase_gain_paxs" in l)
ei = next(i for i in range(si + 1, len(el))
          if "def _cascade_spillback_paxs" in el[i])
HELPER_SRC = "\n".join(l[4:] if l.startswith("    ") else l for l in el[si:ei]).rstrip()

class Spm(object):
    NETWORK_FACTOR = 1.0
    CROSS_TRAFFIC_COST_MULTIPLIER = 2.0


NS = {"np": np, "safe_float": safe_float,
      "math": math, "float": float, "int": int, "max": max, "min": min,
      "range": range, "round": round, "_spm": Spm}
exec(CTM_SRC, NS)
exec(HELPER_SRC, NS)
ctm = NS["_ctm_red_delay"]
gain_fn = NS["_dctsp_off_phase_gain_paxs"]

K_JAM, CYCLE_S, Q_SAT = 150.0, 120.0, 1800.0 / 3600.0
CAR_OCC, BUS_OCC = 1.2, 40.0
GREEN_REMAINING = 40.0
NS["_cycle_s"] = CYCLE_S
NS["_cap_veh"] = 0.15 * K_JAM
NS["_recv_q"] = None
NS["dt"] = 1.0


def cell_occ(n0):
    n = max(n0, 1.0)
    return (min(1.0, n) * BUS_OCC + max(0.0, n - 1.0) * CAR_OCC) / n


class OffCtrl(object):
    def __init__(self, off_vph, red_s=60.0):
        self.UpFlowList = np.array([[900.0, 900.0],
                                    [off_vph, off_vph],
                                    [off_vph, off_vph]], dtype=float)
        self.RedDurationList = np.array([[red_s, red_s]], dtype=float)
        self.CarOcc = CAR_OCC
        self.SaturationFlow = 1800.0

    def _nonmain_phase_indices(self):
        return [1, 2]


# ---- build the state grid ---------------------------------------------------
STATES = []
for n0 in (8.0, 20.0):
    for q_vph in (600.0, 900.0):
        q_arr = q_vph / 3600.0
        occ = cell_occ(n0)
        d_na = ctm(n0, q_arr, Q_SAT, 0.0, GREEN_REMAINING, occ)
        for a in (10.0, 20.0, 30.0):
            d_er = ctm(n0, q_arr, Q_SAT, 0.0, GREEN_REMAINING - a, occ)
            credit = gain_fn(OffCtrl(600.0), a)
            STATES.append({"n0": n0, "q": q_vph, "a": a,
                           "harm": d_er - d_na, "credit": credit})

print("state grid: %d combinations (%d queues x %d arrivals x %d truncations)"
      % (len(STATES), 2, 2, 3))
print()

WEIGHTS = (1.0, 2.0, 4.0, 6.0, 8.0, 10.0, 15.0, 20.0)
print("%-8s %-10s %-12s %s"
      % ("weight", "wins", "real loss", "states won (n0/vph/truncation)"))
print("-" * 100)
summary = {}
for W in WEIGHTS:
    wins = [s for s in STATES if W * s["credit"] > s["harm"]]
    ratios = sorted(s["harm"] / s["credit"] for s in wins)
    span = ("%.2f-%.2fx" % (ratios[0], ratios[-1])) if ratios else "-"
    tags = ", ".join("%.0f/%.0f/%.0f" % (s["n0"], s["q"], s["a"]) for s in wins)
    summary[W] = (len(wins), span)
    print("%-8.1f %-10d %-12s %s" % (W, len(wins), span, tags[:64]))

print()
print("At the shipped default:")
ship = 1.0
wins = [s for s in STATES if ship * s["credit"] > s["harm"]]
by_a = {}
for s in wins:
    by_a.setdefault(s["a"], 0)
    by_a[s["a"]] += 1
print("  weight %.1f -> %d/%d states win" % (ship, len(wins), len(STATES)))
for a in sorted(by_a):
    print("    truncation %.0f s wins in %d/4 states" % (a, by_a[a]))
ratios = sorted(s["harm"] / s["credit"] for s in wins)
if ratios:
    print("  real pax*s loss accepted at those wins: %.2fx to %.2fx"
          % (ratios[0], ratios[-1]))
    print("  worst net real loss: %.0f pax*s"
          % max(s["harm"] - s["credit"] for s in wins))
print()
print("  10 s truncations need weight > %.2f to ever win"
      % max(s["harm"] / s["credit"] for s in STATES if s["a"] == 10.0))

# ---- decompose the harm: how much of it is CAR delay? ----------------------
# The harm above is blended pax*s: the subject bus (BusOcc=40) and the queued
# cars together. For "what does ER cost the CARS?" re-run the same cell at pure
# car occupancy, which isolates the car component; the remainder is the bus's
# own 40 passengers.
print()
print("car-delay cost at the shipped default (weight %.1f)" % ship)
print("%-14s %9s %10s %10s %10s %10s"
      % ("state n0/vph/a", "credit", "harm tot", "car harm", "bus harm",
         "net car"))
print("-" * 70)
for s in wins:
    n0, q_arr = s["n0"], s["q"] / 3600.0
    d_na_car = ctm(n0, q_arr, Q_SAT, 0.0, GREEN_REMAINING, CAR_OCC)
    d_er_car = ctm(n0, q_arr, Q_SAT, 0.0, GREEN_REMAINING - s["a"], CAR_OCC)
    car_harm = d_er_car - d_na_car
    bus_harm = s["harm"] - car_harm
    print("%-14s %9.1f %10.1f %10.1f %10.1f %+10.1f"
          % ("%.0f/%.0f/%.0f" % (s["n0"], s["q"], s["a"]),
             s["credit"], s["harm"], car_harm, bus_harm,
             s["credit"] - car_harm))
