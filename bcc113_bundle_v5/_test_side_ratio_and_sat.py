"""Runtime test of the two patched blocks in specialized_modes.py.

Extracts the REAL source for (a) the marginal side-ratio gate and (b) the
local_sat density read, dedents it, and drives it with stubs. This tests the
bytes on disk rather than a hand-copied replica.

Run: python -I _test_side_ratio_and_sat.py
"""
import ast
import io
import sys
import types

import numpy as np

SRC = "shared_tsp_engine/specialized_modes.py"
lines = io.open(SRC, encoding="utf-8", errors="replace").read().splitlines()

# ---------------------------------------------------------------- extract blocks
def block(start_marker, end_marker, include_start=True):
    si = next(i for i, l in enumerate(lines) if start_marker in l)
    if not include_start:
        si -= 1
    ei = next(i for i in range(si, len(lines)) if end_marker in lines[i])
    raw = "\n".join(lines[si:ei + 1])
    return "\n".join(l[4:] if l.startswith("    ") else l
                     for l in raw.splitlines())


def block_back_to_try(marker, end_marker):
    """Slice from the `try:` that opens the block containing `marker`."""
    mi = next(i for i, l in enumerate(lines) if marker in l)
    si = mi
    while si > 0 and lines[si].strip() != "try:":
        si -= 1
    ei = next(i for i in range(mi, len(lines)) if end_marker in lines[i])
    raw = "\n".join(lines[si:ei + 1])
    return "\n".join(l[4:] if l.startswith("    ") else l
                     for l in raw.splitlines())


# end marker keeps its 12-space indent so it cannot match the 4-space initial
# `_side_ratio_gate = _side_ratio` that sits before the `if`
MARG = block("# 2026-11-02 FIX: the side_ratio gate compared INCOMMENSURABLE",
             "            _side_ratio_gate = _side_ratio")
SAT = block_back_to_try("# 2026-11-02 FIX: UpDenList is np.zeros",
                        "_local_sat = 0.0")

for name, code in (("MARG", MARG), ("SAT", SAT)):
    ast.parse(code)          # must be syntactically whole after dedent
    print("[extract] %s: %d lines, parses OK" % (name, len(code.splitlines())))

fails = []


def check(label, got, want, tol=1e-6):
    ok = (abs(got - want) <= tol) if isinstance(want, float) else (got == want)
    print("  %-58s %s  (got %r, want %r)" % (label, "PASS" if ok else "FAIL", got, want))
    if not ok:
        fails.append(label)


# ---------------------------------------------------------------- (a) marginal gate
def run_marg(side_ratio, chosen, na_db=None, na_ds=None, ch_db=None, ch_ds=None,
             flag=True, raises=False, _cur_na=None, _off_na=None,
             _cur_ch=None, _off_ch=None):
    """Call with either (na_db/na_ds/ch_db/ch_ds) or the phase-named kwargs;
    [1] is the running-phase pax*s term, [2] the off-phase one."""
    if _cur_na is not None:
        na_db, na_ds, ch_db, ch_ds = _cur_na, _off_na, _cur_ch, _off_ch
    ns = {
        "np": np,
        "CELLQ_SIDE_RATIO_MARGINAL": flag,
        "_side_ratio": side_ratio,
        "_chosen_atype": chosen,
        "_chosen_aparam": 5.0,
        "_bxt_evals": [(0.0, na_db, na_ds)],
    }
    if raises:
        def _f(a, p):
            raise RuntimeError("boom")
        ns["_bxt_reward_for"] = _f
    else:
        ns["_bxt_reward_for"] = lambda a, p: (0.0, ch_db, ch_ds)
    exec(MARG, ns)
    return ns["_side_ratio_gate"]


print("\n(a) marginal side-ratio gate")
# bus saves 500 pax*s, cars pay 200 -> 0.4, under the 1.0/1.1 threshold
check("bus_gain 500, side_cost 200 -> 0.40",
      run_marg(119.853, "GE", na_db=1000.0, na_ds=100.0,
               ch_db=500.0, ch_ds=300.0), 0.40)
# the old aggregate ratio would have been 119.853 for the same decision
check("old aggregate ratio would have vetoed (119.853)",
      run_marg(119.853, "GE", na_db=1000.0, na_ds=100.0,
               ch_db=500.0, ch_ds=300.0) < 1.0, True)
# cars pay MORE than the bus saves -> ratio > 2, gate fires
check("bus_gain 100, side_cost 400 -> 4.00 (vetoes)",
      run_marg(2.0, "GE", na_db=1000.0, na_ds=100.0,
               ch_db=900.0, ch_ds=500.0), 4.00)
# no bus gain -> clamped denominator, not a divide-by-zero
check("bus_gain 0 -> side_cost/1.0 (no ZeroDivision)",
      run_marg(5.0, "GE", na_db=100.0, na_ds=100.0,
               ch_db=100.0, ch_ds=250.0), 150.0)
# side gets BETTER than NO_ACTION -> negative clamped to 0, never a credit
check("side improves vs NO_ACTION -> 0.00",
      run_marg(5.0, "GE", na_db=1000.0, na_ds=400.0,
               ch_db=500.0, ch_ds=300.0), 0.0)
# NO_ACTION is never gated -> legacy value passes through
check("chosen NO_ACTION -> legacy _side_ratio untouched",
      run_marg(119.853, "NO_ACTION", 0.0, 0.0, 0.0, 0.0), 119.853)
# flag off -> old behaviour exactly
check("flag=False -> legacy _side_ratio",
      run_marg(119.853, "GE", 1000.0, 100.0, 500.0, 300.0, flag=False), 119.853)
# evaluator raises -> degrade to legacy, do not crash the decision
check("_bxt_reward_for raises -> legacy fallback",
      run_marg(119.853, "GE", 0.0, 0.0, 0.0, 0.0, raises=True), 119.853)

print("\n(a2) the gain is the WHOLE running phase, not the bus alone")
# A platoon clears: the running-phase term drops by 900 pax*s even though the
# subject bus is one 40-pax vehicle. Off phases give up 300. Ratio 0.33 -> the
# gate ALLOWS, because the cars behind the bus count as gain.
check("platoon clears 900, off phases pay 300 -> 0.33 (allowed)",
      run_marg(50.0, "GE", _cur_na=1200.0, _off_na=0.0,
               _cur_ch=300.0, _off_ch=300.0), 300.0 / 900.0)
# Same off-phase cost, but only the bus itself benefits (40 pax*s). Ratio 7.5
# -> vetoed. The pair shows the gate is pricing the PHASE, not the bus.
check("only the bus gains 40, off phases pay 300 -> 7.50 (vetoed)",
      run_marg(0.5, "GE", _cur_na=1200.0, _off_na=0.0,
               _cur_ch=1160.0, _off_ch=300.0), 300.0 / 40.0)
check("same off-phase cost: platoon case passes, lone-bus case does not",
      (run_marg(0.0, "GE", 1200.0, 0.0, 300.0, 300.0) < 1.0)
      and not (run_marg(0.0, "GE", 1200.0, 0.0, 1160.0, 300.0) < 1.0), True)

# ---------------------------------------------------------------- (b) local_sat
class Ctrl(object):
    JamDensity = 150.0

    def __init__(self, upden, side=None, queue=None):
        self.UpDenList = upden
        self.SideUpDenList = np.zeros(3) if side is None else side
        self._q = queue

    def _measured_main_queue_veh(self):
        return self._q


def run_sat(ctrl):
    ns = {"np": np, "self": ctrl}
    ns["__builtins__"] = __builtins__
    exec(SAT, ns)
    return ns["_local_sat"]


print("\n(b) local_sat density read")
# populated numpy 2-D array: the case that used to raise
c = Ctrl(np.array([[0.0, 20.0], [30.0, 5.0]]))
check("2-D np UpDenList, max=30, kj=150 -> 0.200", run_sat(c), 30.0 / 150.0)
check("2-D array did NOT fall back to queue", run_sat(c) > 0.0, True)
# all-zero densities -> measured-queue fallback (the dead-gate case)
c = Ctrl(np.zeros((4, 5)), queue=10.0)
check("all-zero densities, queue 10 veh -> 0.500", run_sat(c), 0.5)
# zero densities and no queue -> genuinely 0, no crash
c = Ctrl(np.zeros((4, 5)), queue=0.0)
check("all-zero densities, no queue -> 0.000", run_sat(c), 0.0)
c = Ctrl(np.zeros((4, 5)), queue=None)
check("all-zero densities, queue None -> 0.000", run_sat(c), 0.0)
# 1-D SideUpDenList contributes when UpDenList is empty
c = Ctrl(np.zeros((0, 0)), side=np.array([0.0, 45.0, 0.0]))
check("empty UpDenList, SideUpDenList max=45 -> 0.300", run_sat(c), 45.0 / 150.0)
# plain python list still works (some tests / older pickles use lists)
c = Ctrl([[0.0, 60.0]])
check("plain list-of-lists max=60 -> 0.400", run_sat(c), 60.0 / 150.0)
# queue fallback is clamped to 1.0
c = Ctrl(np.zeros((2, 2)), queue=500.0)
check("queue 500 veh -> clamp 1.000", run_sat(c), 1.0)
# missing attributes entirely -> 0.0, no AttributeError escapes
c = Ctrl(np.zeros((2, 2)))
del c.UpDenList
check("UpDenList deleted -> 0.000", run_sat(c), 0.0)

print("\n%d failure(s)" % len(fails))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.exit(1)
print("ALL CHECKS PASSED")
