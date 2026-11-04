"""Would right-phase EARLY_RED now be selected?

Extracts the REAL _ctm_red_delay (specialized_modes.py) and
_dctsp_off_phase_gain_paxs (engine.py), then compares, for a bus phase that is
RUNNING, the pax*s ER costs on the running phase against the pax*s it credits
to the off phases.

In the reward, r = -(d_bus + d_side) and NO_ACTION has d_side = 0, so

    ER is selected  <=>  credit(a) > harm(a) = d_bus(ER) - d_bus(NO_ACTION)

Everything else (the bus-miss penalty, POG terms, the cross cost of the
NO_ACTION baseline) is common to both actions and cancels.

Run: python -I _check_er_fires.py
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


# ---- extract the two real functions ----------------------------------------
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

# ---- a realistic KG state ---------------------------------------------------
K_JAM = 150.0
CYCLE_S = 120.0
Q_SAT = 1800.0 / 3600.0        # veh/s
CAR_OCC = 1.2
BUS_OCC = 40.0

# closure stubs the extracted _ctm_red_delay expects
NS["_cycle_s"] = CYCLE_S
NS["_cap_veh"] = 0.15 * K_JAM
NS["_recv_q"] = None
NS["dt"] = 1.0

# approach: q_arr veh/s, n0 vehicles standing, blended passenger occupancy
def cell_occ(n0):
    n = max(n0, 1.0)
    return (min(1.0, n) * BUS_OCC + max(0.0, n - 1.0) * CAR_OCC) / n


class OffCtrl(object):
    """Off phases at a chosen flow, with a chosen measured red duration."""

    def __init__(self, off_vph, red_s):
        self.UpFlowList = np.array([[900.0, 900.0],
                                    [off_vph, off_vph],
                                    [off_vph, off_vph]], dtype=float)
        self.RedDurationList = np.array([[red_s, red_s]], dtype=float)
        self.CarOcc = CAR_OCC
        self.SaturationFlow = 1800.0

    def _nonmain_phase_indices(self):
        return [1, 2]


# GREEN_REMAINING must exceed the truncation, otherwise the action is not
# legal: ER cannot take more green than is left in the phase.
GREEN_REMAINING = 40.0

print("KG-like state: cycle %.0f s, q_sat %.2f veh/s, BusOcc %.0f, CarOcc %.1f"
      % (CYCLE_S, Q_SAT, BUS_OCC, CAR_OCC))
print()
for n0 in (8.0, 20.0):
    for q_vph in (600.0, 900.0):
        q_arr = q_vph / 3600.0
        occ = cell_occ(n0)
        print("--- n0=%.0f veh, arrival %0.f vph, occ %.2f pax/veh, %0.f s green left"
              % (n0, q_vph, occ, GREEN_REMAINING))
        d_na = ctm(n0, q_arr, Q_SAT, 0.0, GREEN_REMAINING, occ)
        for a in (10.0, 20.0, 30.0):
            d_er = ctm(n0, q_arr, Q_SAT, 0.0, GREEN_REMAINING - a, occ)
            harm = d_er - d_na
            ctrl = OffCtrl(600.0, 60.0)
            credit = gain_fn(ctrl, a)
            verdict = "SELECTED" if credit > harm else "rejected"
            print("    ER %2.0f s | harm %8.1f  credit %8.1f  net %+9.1f  -> %s"
                  % (a, harm, credit, credit - harm, verdict))
        print()

print("main-phase cell delay at NO_ACTION (reference): "
      "n0=8 %.1f pax*s, n0=20 %.1f pax*s"
      % (ctm(8.0, 600 / 3600.0, Q_SAT, 0.0, 15.0, cell_occ(8.0)),
         ctm(20.0, 600 / 3600.0, Q_SAT, 0.0, 15.0, cell_occ(20.0))))
