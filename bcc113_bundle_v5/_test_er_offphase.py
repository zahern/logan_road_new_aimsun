"""Test the EARLY_RED off-phase credit.

Extracts real source:
  * _dctsp_off_phase_gain_paxs from engine.py
  * the d_side credit block from _bxt_reward_for (specialized_modes.py)
  * the min_gain / _er_offphase gate block   (specialized_modes.py)

Run: python -I _test_er_offphase.py
"""
import io
import math
import sys

import numpy as np

ENG = "shared_tsp_engine/engine.py"
SM = "shared_tsp_engine/specialized_modes.py"


def safe_float(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    return result


def slice_lines(path, start_marker, end_marker, dedent):
    lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
    si = next(i for i, l in enumerate(lines) if start_marker in l)
    ei = next(i for i in range(si, len(lines)) if end_marker in lines[i])
    out = []
    for l in lines[si:ei + 1]:
        out.append(l[dedent:] if l.startswith(" " * dedent) else l)
    return "\n".join(out)


def slice_to_next_def(path, start_marker, next_marker, dedent):
    """Slice a whole method: from start_marker up to the line before the next
    method definition (keeps trailing except/finally clauses intact)."""
    lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
    si = next(i for i, l in enumerate(lines) if start_marker in l)
    ei = next(i for i in range(si + 1, len(lines)) if next_marker in lines[i])
    out = []
    for l in lines[si:ei]:
        out.append(l[dedent:] if l.startswith(" " * dedent) else l)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


HELPER_SRC = slice_to_next_def(
    ENG,
    "def _dctsp_off_phase_gain_paxs",
    "def _cascade_spillback_paxs",
    4,
)
CREDIT_SRC = slice_lines(
    SM,
    "            # Price the mirror-image gain, as a NEGATIVE cost.",
    "                        d_side = 0.0",
    16,
)
# the `if` header needs a body to parse; the body is irrelevant to the test
GATE_SRC = slice_lines(
    SM,
    "    _er_offphase = (",
    "            and not _er_offphase):",
    4,
) + "\n    pass"

import ast  # noqa: E402
for _n, _s in (("HELPER", HELPER_SRC), ("CREDIT", CREDIT_SRC), ("GATE", GATE_SRC)):
    ast.parse(_s)
    print("[extract] %s: %d lines, parses OK" % (_n, len(_s.splitlines())))

fails = []


def check(label, got, want, tol=1e-6):
    ok = (abs(got - want) <= tol) if isinstance(want, float) else (got == want)
    print("  %-60s %s  (got %r, want %r)"
          % (label, "PASS" if ok else "FAIL", got, want))
    if not ok:
        fails.append(label)


# --------------------------------------------------------------- helper
class Ctrl(object):
    def __init__(self, upf, red=None, car_occ=1.2, sat=1800.0):
        self.UpFlowList = np.array(upf, dtype=float)
        self.RedDurationList = (np.zeros((1, 1)) if red is None
                                else np.array(red, dtype=float))
        self.CarOcc = car_occ
        self.SaturationFlow = sat

    def _nonmain_phase_indices(self):
        return [1, 2]


NETWORK_FACTOR = 1.0
CROSS_TRAFFIC_COST_MULTIPLIER = 2.0
SCALE = NETWORK_FACTOR * CROSS_TRAFFIC_COST_MULTIPLIER


class Spm(object):
    NETWORK_FACTOR = NETWORK_FACTOR
    CROSS_TRAFFIC_COST_MULTIPLIER = CROSS_TRAFFIC_COST_MULTIPLIER


NS = {"np": np, "safe_float": safe_float, "_spm": Spm}
exec(HELPER_SRC, NS)
gain = NS["_dctsp_off_phase_gain_paxs"]


def expected(off_flows_vph, el, a, car_occ=1.2, sat_vps=0.5):
    """Raw pax*s, then scaled exactly as the helper does."""
    tot = 0.0
    for vph in off_flows_vph:
        f = vph / 3600.0
        q0 = f * el
        s_eff = max(sat_vps - f, sat_vps * 0.10)
        tot += min(q0, s_eff * a) * a * car_occ
        tot += f * a * (a / 2.0) * car_occ
    return tot * SCALE


print("\n(a) _dctsp_off_phase_gain_paxs")
# phase 0 = main (ignored), 1 and 2 = off phases at 600 vph
c = Ctrl([[900.0, 900.0], [600.0, 600.0], [600.0, 600.0]],
         red=[[60.0, 60.0]])
check("action_s=0 -> 0 (no truncation, no credit)", gain(c, 0.0), 0.0)
check("action_s<0 -> 0 (never negative)", gain(c, -5.0), 0.0)
check("10 s truncation vs closed form",
      gain(c, 10.0), expected([600.0, 600.0], 60.0, 10.0))
check("20 s > 10 s (monotone in the window)",
      gain(c, 20.0) > gain(c, 10.0), True)
check("gain is positive", gain(c, 10.0) > 0.0, True)
# an empty off phase contributes nothing
c0 = Ctrl([[900.0, 900.0], [0.0, 0.0], [0.0, 0.0]], red=[[60.0, 60.0]])
check("all off-phase rows zero -> 0", gain(c0, 10.0), 0.0)
# main row must NOT be counted: only rows 1,2
c_main = Ctrl([[9999.0, 9999.0], [0.0, 0.0], [0.0, 0.0]],
              red=[[60.0, 60.0]])
check("main phase flow excluded", gain(c_main, 10.0), 0.0)
# no RedDurationList -> falls back to 60 s rather than zeroing the Q0 term
c_nor = Ctrl([[900.0, 900.0], [600.0, 600.0], [600.0, 600.0]])
check("missing RedDurationList still uses 60 s",
      gain(c_nor, 10.0), expected([600.0, 600.0], 60.0, 10.0))
check("60 s default > arrivals-only term",
      gain(c_nor, 10.0) > SCALE * (600.0 / 3600.0 * 10.0 * 5.0 * 1.2) * 2, True)

# scaling behaviour
_no_cmult = type("T", (), {"NETWORK_FACTOR": 1.0})()
NS2 = {"np": np, "safe_float": safe_float, "_spm": _no_cmult}
exec(HELPER_SRC, NS2)
check("missing CROSS_TRAFFIC_COST_MULTIPLIER -> no scaling (conservative)",
      NS2["_dctsp_off_phase_gain_paxs"](c, 10.0), expected([600.0, 600.0], 60.0, 10.0) / SCALE)
check("scaled credit is exactly SCALE x the raw credit",
      gain(c, 10.0), (expected([600.0, 600.0], 60.0, 10.0) / SCALE) * SCALE)

# --------------------------------------------------------------- credit
print("\n(b) d_side credit in the ER branch")


class RCtrl(object):
    def __init__(self, g):
        self._g = g

    def _dctsp_off_phase_gain_paxs(self, a):
        if isinstance(self._g, Exception):
            raise self._g
        return self._g


def run_credit(gain_value, flag=True, weight=1.0):
    ns = {"self": RCtrl(gain_value), "a_s": 10.0,
          "BXT_ER_OFFPHASE_CREDIT": flag,
          "BXT_ER_OFFPHASE_GAIN_WEIGHT": weight}
    exec(CREDIT_SRC, ns)
    return ns["d_side"]


check("credit ON: d_side is NEGATIVE (a benefit)", run_credit(100.0), -100.0)
check("credit OFF: d_side is 0.0 (old build)", run_credit(100.0, flag=False), 0.0)
check("weight 0.5 halves the credit", run_credit(100.0, weight=0.5), -50.0)
check("weight 0 -> no credit", run_credit(100.0, weight=0.0), 0.0)
check("helper raises -> d_side 0.0, no crash",
      run_credit(RuntimeError("boom")), 0.0)
check("zero gain -> 0.0", run_credit(0.0), 0.0)

# --------------------------------------------------------------- gate
print("\n(c) min_gain is not applied to right-phase ER")


def gate_fires(eff_delay, atype, wrong_phase, flag=True, min_gain=1.0):
    ns = {"eff_delay": eff_delay, "_bxt_min_delay_s": min_gain,
          "_explore_bypass": False, "_chosen_atype": atype,
          "_wrong_phase": wrong_phase, "BXT_ER_OFFPHASE_CREDIT": flag}
    exec(GATE_SRC, ns)
    return bool(ns["_er_offphase"])


check("right-phase ER, credit ON -> exempt", gate_fires(0.0, "EARLY_RED", False), True)
check("right-phase ER, credit OFF -> old gate applies",
      gate_fires(0.0, "EARLY_RED", False, flag=False), False)
check("wrong-phase ER -> still graded on bus gain",
      gate_fires(0.0, "EARLY_RED", True), False)
check("GE is unaffected", gate_fires(0.0, "GE", False), False)

# --------------------------------------------------------------- break-even
print("\n(d) break-even: does the credit change the ER decision?")
c = Ctrl([[900.0, 900.0], [600.0, 600.0], [600.0, 600.0]],
         red=[[60.0, 60.0]])
for a in (10.0, 20.0, 30.0):
    g = gain(c, a)
    print("   ER %.0f s -> credit %6.1f pax*s; ER wins iff short-green harm < %.1f"
          % (a, g, g))

print("\n%d failure(s)" % len(fails))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.exit(1)
print("ALL CHECKS PASSED")
