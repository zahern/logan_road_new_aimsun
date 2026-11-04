"""Is the 6x weight compensating for a real modelling asymmetry?

At weight 1.0 (a straight pax*s comparison, which is what the objective claims
to be) ER never wins. This script asks WHY, by separating the two asymmetries
between the credit and the harm:

  (A) OCCUPANCY. _cell_occ charges the subject bus at BusOcc=40 pax whether or
      not that bus is anywhere near the approach cell. At n0=8 it lifts the
      blended occupancy to 6.05 pax/veh, so the harm is charged almost entirely
      against a bus that may be 300 m back and unable to use the green at all.
      The credit side (off phases) is all cars at CarOcc=1.2.

  (B) MULTIPLIER. _dctsp_cross_traffic_delay_s multiplies its cost by
      CROSS_TRAFFIC_COST_MULTIPLIER, because the analytic cross model is known
      to under-predict. My credit deliberately did not, so it is priced on a
      different basis than the cost it is meant to offset.

If ER competes at weight 1.0 once (A) and (B) are corrected, the 6x weight was
a fudge and should go. Run: python -I _check_er_occupancy.py
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
node = next(n for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.FunctionDef) and n.name == "_ctm_red_delay")
CTM_SRC = "\n".join(l[4:] if l.startswith("    ") else l
                    for l in src.splitlines()[node.lineno - 1:node.end_lineno])

el = io.open(ENG, encoding="utf-8", errors="replace").read().splitlines()
si = next(i for i, l in enumerate(el) if "def _dctsp_off_phase_gain_paxs" in l)
ei = next(i for i in range(si + 1, len(el))
          if "def _cascade_spillback_paxs" in el[i])
HELPER_SRC = "\n".join(l[4:] if l.startswith("    ") else l for l in el[si:ei]).rstrip()

Q_SAT = 1800.0 / 3600.0
CAR_OCC, BUS_OCC = 1.2, 40.0
CROSS_TRAFFIC_COST_MULTIPLIER = 2.0     # live value in specialized_modes.py
GREEN_REMAINING = 40.0

class Spm(object):
    NETWORK_FACTOR = 1.0
    CROSS_TRAFFIC_COST_MULTIPLIER = 2.0


NS = {"np": np, "safe_float": safe_float, "math": math, "float": float,
      "int": int, "max": max, "min": min, "range": range, "round": round,
      "_spm": Spm,
      "_cycle_s": 120.0, "_cap_veh": 0.15 * 150.0, "_recv_q": None, "dt": 1.0}
exec(CTM_SRC, NS)
exec(HELPER_SRC, NS)
ctm = NS["_ctm_red_delay"]
gain_fn = NS["_dctsp_off_phase_gain_paxs"]


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


print("weight = 1.0 (a straight pax*s comparison) in every row")
print("%-18s %10s %11s %11s %9s %s"
      % ("state", "credit", "harm blend", "harm cars", "beats cars", "verdict"))
print("-" * 88)
wins = 0
total = 0
for n0 in (8.0, 20.0):
    for q_vph in (600.0, 900.0):
        q_arr = q_vph / 3600.0
        for a in (10.0, 20.0, 30.0):
            total += 1
            d_na_b = ctm(n0, q_arr, Q_SAT, 0.0, GREEN_REMAINING, cell_occ(n0))
            d_er_b = ctm(n0, q_arr, Q_SAT, 0.0, GREEN_REMAINING - a, cell_occ(n0))
            d_na_c = ctm(n0, q_arr, Q_SAT, 0.0, GREEN_REMAINING, CAR_OCC)
            d_er_c = ctm(n0, q_arr, Q_SAT, 0.0, GREEN_REMAINING - a, CAR_OCC)
            harm_blend = d_er_b - d_na_b
            harm_cars = d_er_c - d_na_c
            # the helper now applies NETWORK_FACTOR * CROSS_TRAFFIC_COST_MULTIPLIER
            # itself, so `credit` is already on the cost model's basis.
            credit = gain_fn(OffCtrl(600.0), a)
            ok_cars = credit > harm_cars
            ok_blend = credit > harm_blend
            wins += 1 if ok_cars else 0
            print("%-18s %10.1f %11.1f %11.1f %9s %s"
                  % ("%.0f/%.0f/%.0f" % (n0, q_vph, a), credit,
                     harm_blend, harm_cars,
                     "yes" if ok_cars else "no",
                     "ER wins" if ok_cars else "ER loses"))
print()
print("Credit is already scaled by NETWORK_FACTOR * CROSS_TRAFFIC_COST_MULTIPLIER.")
print("ER wins %d/%d states at weight 1.0 IF the subject bus is not charged into"
      % (wins, total))
print("the approach-cell occupancy while it is still remote.")
