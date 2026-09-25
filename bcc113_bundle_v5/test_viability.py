#!/usr/bin/env python3
"""test_viability.py -- _viability_update transition table."""
import sys

sys.path.insert(0, "shared_tsp_engine")
import engine as _eng

fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f" [{extra}]" if extra and not cond else ""))
    if not cond:
        fails.append(name)


V = _eng._viability_update
# gate off: always armed (re-arms a stale False once)
check("gate-off armed stays", V(True, False, False, True, 0.0, 0.7) == (True, False, "gate-off"))
check("gate-off re-arms", V(False, False, True, False, 0.99, 0.7)[0] is True)
# trip on either breach
check("ratio breach disarms",
      V(True, True, True, False, 0.1, 0.7) == (False, True, "ratio"))
check("saturation disarms",
      V(True, True, False, True, 0.7, 0.7) == (False, True, "saturation"))
check("just below trips nothing",
      V(True, True, False, True, 0.69, 0.7) == (True, False, None))
# hold disarmed until BOTH clear with hysteresis
check("rearm needs both",
      V(False, True, False, True, 0.1, 0.7) == (True, True, "rearm"))
check("no rearm on ratio", V(False, True, True, False, 0.1, 0.7)[0] is False)
check("no rearm on sat", V(False, True, False, True, 0.9, 0.7)[0] is False)
check("hysteresis band holds",
      V(False, True, False, True, 0.60, 0.7)[0] is False)  # 0.60 > 0.55
check("hysteresis clears",
      V(False, True, False, True, 0.50, 0.7) == (True, True, "rearm"))
# garbage-proof
check("garbage safe", V(True, True, False, True, "x", "y")[0] is True)

print("ALL OK" if not fails else f"{len(fails)} FAILURES")
sys.exit(1 if fails else 0)
