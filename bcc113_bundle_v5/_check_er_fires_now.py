"""Does EARLY_RED fire now, at BXT_ER_OFFPHASE_GAIN_WEIGHT = 1.0?

Uses the REAL patched code end to end:
  * the CELL_BUS_OCC block (occupancy now depends on whether the bus can use
    the green being priced),
  * _ctm_red_delay (running-phase pax*s),
  * _dctsp_off_phase_gain_paxs (the off-phase credit, already scaled by
    NETWORK_FACTOR * CROSS_TRAFFIC_COST_MULTIPLIER).

ER is selected iff credit > harm, with harm = d_bus(ER) - d_bus(NO_ACTION),
evaluated with the SAME occupancy on both sides (dctsp_bxt computes _cell_occ
once per decision, before scoring any candidate).

Run: python -I _check_er_fires_now.py
"""
import ast
import io
import math

import numpy as np

SM = "shared_tsp_engine/specialized_modes.py"
ENG = "shared_tsp_engine/engine.py"
Q_SAT = 1800.0 / 3600.0
BUS_OCC, CAR_OCC = 40.0, 1.2
GREEN_LEFT = 40.0


def safe_float(v, d=0.0):
    try:
        r = float(v)
    except (TypeError, ValueError):
        return d
    return r if math.isfinite(r) else d


class Spm(object):
    NETWORK_FACTOR = 1.0
    CROSS_TRAFFIC_COST_MULTIPLIER = 2.0


sm_lines = io.open(SM, encoding="utf-8", errors="replace").read().splitlines()

# --- CELL_BUS_OCC block
si = next(i for i, l in enumerate(sm_lines) if "---- BEGIN CELL_BUS_OCC" in l)
ei = next(i for i in range(si, len(sm_lines)) if "---- END CELL_BUS_OCC" in sm_lines[i])
OCC_SRC = "\n".join(l[4:] if l.startswith("    ") else l
                    for l in sm_lines[si:ei + 1])
OCC_SRC = "\n".join(l for l in OCC_SRC.splitlines() if not l.strip().startswith("#"))

# --- _ctm_red_delay
src = io.open(SM, encoding="utf-8", errors="replace").read()
node = next(n for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.FunctionDef) and n.name == "_ctm_red_delay")
CTM_SRC = "\n".join(l[4:] if l.startswith("    ") else l
                    for l in src.splitlines()[node.lineno - 1:node.end_lineno])

# --- credit helper
el = io.open(ENG, encoding="utf-8", errors="replace").read().splitlines()
si2 = next(i for i, l in enumerate(el) if "def _dctsp_off_phase_gain_paxs" in l)
ei2 = next(i for i in range(si2 + 1, len(el))
           if "def _cascade_spillback_paxs" in el[i])
HELPER_SRC = "\n".join(l[4:] if l.startswith("    ") else l
                       for l in el[si2:ei2]).rstrip()

for nm, s in (("CELL_BUS_OCC", OCC_SRC), ("_ctm_red_delay", CTM_SRC),
              ("credit", HELPER_SRC)):
    ast.parse(s)
print("[extract] %s OK" % nm)

NS = {"np": np, "safe_float": safe_float, "math": math, "float": float,
      "int": int, "max": max, "min": min, "range": range, "round": round,
      "_spm": Spm, "_cycle_s": 120.0, "_cap_veh": 0.15 * 150.0,
      "_recv_q": None, "dt": 1.0}
exec(CTM_SRC, NS)
exec(HELPER_SRC, NS)
ctm = NS["_ctm_red_delay"]
gain_fn = NS["_dctsp_off_phase_gain_paxs"]


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


def occ_for(n0, wrong_phase, bus_eta, green_left=GREEN_LEFT):
    ns = {"BXT_CELL_BUS_OCC_ONLY_IF_ARRIVING": True,
          "_car_occ_cell": CAR_OCC, "_n_cell": max(float(n0), 1.0),
          "_bus_occ": BUS_OCC, "_wrong_phase": wrong_phase,
          "bus_eta_s": bus_eta, "remaining_red_s": green_left}
    exec(OCC_SRC, ns)
    return ns["_cell_occ"], ns["_bus_in_cell"]


BUS_CASES = (
    ("bus ARRIVING (eta 10 s <= 40 s green)", False, 10.0),
    ("bus REMOTE   (eta 60 s >  40 s green)", False, 60.0),
)

for label, wrong_phase, bus_eta in BUS_CASES:
    print()
    print("=== %s ===" % label)
    print("%-18s %7s %9s %9s %9s %s"
          % ("state n0/vph/a", "occ", "credit", "harm", "net", "verdict"))
    print("-" * 74)
    wins = total = 0
    for n0 in (8.0, 20.0):
        for q_vph in (600.0, 900.0):
            q_arr = q_vph / 3600.0
            for a in (10.0, 20.0, 30.0):
                total += 1
                occ, in_cell = occ_for(n0, wrong_phase, bus_eta)
                d_na = ctm(n0, q_arr, Q_SAT, 0.0, GREEN_LEFT, occ)
                d_er = ctm(n0, q_arr, Q_SAT, 0.0, GREEN_LEFT - a, occ)
                harm = d_er - d_na
                credit = gain_fn(OffCtrl(600.0), a)
                ok = credit > harm
                wins += 1 if ok else 0
                print("%-18s %7.2f %9.1f %9.1f %+9.1f %s"
                      % ("%.0f/%.0f/%.0f" % (n0, q_vph, a), occ, credit,
                         harm, credit - harm,
                         "ER wins" if ok else "ER loses"))
    print("-> ER wins %d/%d states at weight 1.0" % (wins, total))
