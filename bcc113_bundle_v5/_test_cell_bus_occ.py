"""Test the CELL_BUS_OCC block: the subject bus is charged only when it can
actually use the green being priced.

Extracts the real block from specialized_modes.py.

Run: python -I _test_cell_bus_occ.py
"""
import ast
import io
import sys

SM = "shared_tsp_engine/specialized_modes.py"
lines = io.open(SM, encoding="utf-8", errors="replace").read().splitlines()
si = next(i for i, l in enumerate(lines) if "---- BEGIN CELL_BUS_OCC" in l)
ei = next(i for i in range(si, len(lines)) if "---- END CELL_BUS_OCC" in lines[i])
BLOCK = "\n".join(l[4:] if l.startswith("    ") else l for l in lines[si:ei + 1])
BLOCK = "\n".join(l for l in BLOCK.splitlines() if not l.strip().startswith("#"))
ast.parse(BLOCK)
print("[extract] CELL_BUS_OCC: %d lines, parses OK" % len(BLOCK.splitlines()))

BUS_OCC, CAR_OCC = 40.0, 1.2
fails = []


def check(label, got, want, tol=1e-9):
    ok = (abs(got - want) <= tol) if isinstance(want, float) else (got == want)
    print("  %-58s %s  (got %r, want %r)"
          % (label, "PASS" if ok else "FAIL", got, want))
    if not ok:
        fails.append(label)


def occ(n0, wrong_phase, bus_eta, green_left, flag=True):
    ns = {
        "BXT_CELL_BUS_OCC_ONLY_IF_ARRIVING": flag,
        "_car_occ_cell": CAR_OCC,
        "_n_cell": max(float(n0), 1.0),
        "_bus_occ": BUS_OCC,
        "_wrong_phase": wrong_phase,
        "bus_eta_s": bus_eta,
        "remaining_red_s": green_left,
    }
    exec(BLOCK, ns)
    return ns["_cell_occ"], ns["_bus_in_cell"]


def blended(n0):
    n = max(float(n0), 1.0)
    return (min(1.0, n) * BUS_OCC + max(0.0, n - 1.0) * CAR_OCC) / n


print("\n(a) bus is charged when it can use the green")
v, in_cell = occ(8, False, 10.0, 40.0)
check("right phase, eta 10 s <= 40 s green -> in cell", in_cell, True)
check("  occupancy == old blended value", v, blended(8))
v, in_cell = occ(20, False, 39.0, 40.0)
check("right phase, eta 39 s <= 40 s -> in cell", in_cell, True)
check("  occupancy == old blended value", v, blended(20))

print("\n(b) bus is NOT charged when it cannot arrive in this green")
v, in_cell = occ(8, False, 60.0, 40.0)
check("right phase, eta 60 s > 40 s green -> not in cell", in_cell, False)
check("  occupancy collapses to CarOcc", v, CAR_OCC)
v, in_cell = occ(20, False, 1e9, 40.0)
check("no bus on this tick (eta 1e9) -> not in cell", in_cell, False)
check("  occupancy == CarOcc, not 40", v, CAR_OCC)
v, in_cell = occ(5, False, 30.0, 0.0)
check("no green left, eta 30 s -> not in cell", in_cell, False)
check("  occupancy == CarOcc", v, CAR_OCC)

print("\n(c) a wrong-phase bus always counts")
v, in_cell = occ(8, True, 60.0, 40.0)
check("wrong phase, eta 60 s -> still in cell (held on red)", in_cell, True)
check("  occupancy == old blended value", v, blended(8))
v, in_cell = occ(8, True, 1e9, 0.0)
check("wrong phase, no eta signal -> defaults to in cell", in_cell, True)

print("\n(d) the old behaviour is recoverable")
v, in_cell = occ(8, False, 60.0, 40.0, flag=False)
check("flag off, remote bus -> still charged (old build)", in_cell, True)
check("  occupancy == old blended value", v, blended(8))

print("\n(e) degenerate inputs")
v, in_cell = occ(0.0, False, 60.0, 40.0)
check("n0=0 -> occupancy CarOcc, no divide-by-zero", v, CAR_OCC)
v, in_cell = occ(1.0, True, 0.0, 40.0)
check("n0=1 wrong phase -> 40 pax/veh (a lone bus)", v, BUS_OCC)
check("occupancy never below CarOcc", occ(8, False, 1e9, 40.0)[0] >= CAR_OCC, True)

print("\n%d failure(s)" % len(fails))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.exit(1)
print("ALL CHECKS PASSED")
